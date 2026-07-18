#!/usr/bin/env python3
"""Build resumable directed road matrices from one frozen local OSRM graph.

Every off-diagonal ordered pair receives its own Route API request. Distance,
duration and sum(v^2*d) come from the same returned route annotation. The
builder has no Euclidean, reverse-copy, symmetry or uniform-speed fallback.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERDICT = "PASS_LOCAL_DIRECTED_SAME_ROUTE_THREE_MATRICES"


class MatrixBuildError(RuntimeError):
    """The frozen directed-matrix contract cannot be satisfied."""


@dataclass(frozen=True)
class Node:
    node_id: str
    node_type: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Metrics:
    distance_m: float
    duration_s: float
    annotation_duration_s: float
    routing_delay_s: float
    sum_v2d_m3_s2: float
    origin_matched_lon: float
    origin_matched_lat: float
    destination_matched_lon: float
    destination_matched_lat: float
    annotation_segments: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_nodes(path: Path) -> list[Node]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    required = {"node_id", "node_type", "latitude", "longitude"}
    if not rows or not required.issubset(rows[0]):
        raise MatrixBuildError(f"nodes file requires {sorted(required)}")
    nodes = [
        Node(
            node_id=row["node_id"],
            node_type=row["node_type"].strip().lower(),
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
        )
        for row in rows
    ]
    if len({node.node_id for node in nodes}) != len(nodes):
        raise MatrixBuildError("node_id values must be unique")
    if len({(node.latitude, node.longitude) for node in nodes}) != len(nodes):
        raise MatrixBuildError("node coordinates must be unique")
    node_types = {node.node_type for node in nodes}
    if not {"depot", "customer", "station"}.issubset(node_types):
        raise MatrixBuildError(
            "formal node set requires depot, customer and station node types"
        )
    return nodes


def route_url(endpoint: str, profile: str, origin: Node, destination: Node) -> str:
    coordinates = (
        f"{origin.longitude:.7f},{origin.latitude:.7f};"
        f"{destination.longitude:.7f},{destination.latitude:.7f}"
    )
    query = urllib.parse.urlencode(
        {
            "alternatives": "false",
            "annotations": "distance,duration",
            "overview": "false",
            "steps": "false",
            "radiuses": "10000;10000",
        }
    )
    return (
        f"{endpoint.rstrip('/')}/route/v1/{profile}/{coordinates}?{query}"
    )


def parse_response(payload: dict[str, Any]) -> Metrics:
    if payload.get("code") != "Ok":
        raise MatrixBuildError(f"OSRM code={payload.get('code')!r}")
    routes = payload.get("routes")
    waypoints = payload.get("waypoints")
    if not isinstance(routes, list) or len(routes) != 1:
        raise MatrixBuildError("exactly one selected route is required")
    if not isinstance(waypoints, list) or len(waypoints) != 2:
        raise MatrixBuildError("exactly two matched waypoints are required")
    legs = routes[0].get("legs")
    if not isinstance(legs, list) or len(legs) != 1:
        raise MatrixBuildError("exactly one route leg is required")
    annotation = legs[0].get("annotation", {})
    distances = annotation.get("distance")
    durations = annotation.get("duration")
    if (
        not isinstance(distances, list)
        or not isinstance(durations, list)
        or not distances
        or len(distances) != len(durations)
    ):
        raise MatrixBuildError("aligned non-empty distance/duration annotations required")

    distance_m = 0.0
    annotation_duration_s = 0.0
    sum_v2d = 0.0
    for raw_distance, raw_duration in zip(distances, durations, strict=True):
        distance = float(raw_distance)
        duration = float(raw_duration)
        if (
            not math.isfinite(distance)
            or not math.isfinite(duration)
            or distance < 0
            or duration < 0
            or (distance > 0 and duration <= 0)
        ):
            raise MatrixBuildError("invalid annotation segment")
        distance_m += distance
        annotation_duration_s += duration
        if distance > 0:
            sum_v2d += (distance / duration) ** 2 * distance

    route_distance = float(routes[0].get("distance", math.nan))
    route_duration = float(routes[0].get("duration", math.nan))
    if (
        distance_m <= 0
        or annotation_duration_s <= 0
        or sum_v2d <= 0
        or not math.isfinite(route_distance)
        or not math.isfinite(route_duration)
        or route_duration <= 0
    ):
        raise MatrixBuildError("same-route metrics must be finite and positive")
    if not math.isclose(
        distance_m, route_distance, abs_tol=max(1.0, route_distance * 1e-4)
    ):
        raise MatrixBuildError("annotation distance does not close to route distance")
    routing_delay = route_duration - annotation_duration_s
    if routing_delay < -1.0:
        raise MatrixBuildError("route duration is shorter than edge annotation time")
    matched = [waypoint.get("location") for waypoint in waypoints]
    if any(not isinstance(value, list) or len(value) != 2 for value in matched):
        raise MatrixBuildError("matched waypoint coordinates are missing")
    return Metrics(
        distance_m=distance_m,
        duration_s=route_duration,
        annotation_duration_s=annotation_duration_s,
        routing_delay_s=routing_delay,
        sum_v2d_m3_s2=sum_v2d,
        origin_matched_lon=float(matched[0][0]),
        origin_matched_lat=float(matched[0][1]),
        destination_matched_lon=float(matched[1][0]),
        destination_matched_lat=float(matched[1][1]),
        annotation_segments=len(distances),
    )


def completed_rows(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.is_file():
        return {}
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MatrixBuildError(
                    f"checkpoint corruption at line {line_number}"
                ) from exc
            key = (row["origin_node_id"], row["destination_node_id"])
            if key in rows:
                raise MatrixBuildError(f"duplicate checkpoint pair: {key}")
            rows[key] = row
    return rows


def verify_graph_manifest(path: Path, payload: dict[str, Any]) -> None:
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise MatrixBuildError("graph manifest has no frozen file hashes")
    graph_dir = path.parent
    for relative, expected in files.items():
        graph_file = graph_dir / relative
        if not graph_file.is_file() or sha256(graph_file) != expected:
            raise MatrixBuildError(f"graph file hash drift: {graph_file}")


def freeze_nodes_copy(source: Path, output: Path) -> None:
    for name in ("nodes.csv", "source_coordinates.csv"):
        target = output / name
        if target.is_file() and sha256(target) != sha256(source):
            raise MatrixBuildError(f"frozen node copy hash drift: {target}")
        if not target.exists():
            shutil.copy2(source, target)


def append_checkpoint(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def append_unreachable(
    path: Path, origin: Node, destination: Node, error: str
) -> None:
    fields = ["origin_node_id", "destination_node_id", "reason"]
    exists = path.is_file()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "origin_node_id": origin.node_id,
                "destination_node_id": destination.node_id,
                "reason": error,
            }
        )


def write_pair_audits(
    output: Path,
    nodes: list[Node],
    rows: dict[tuple[str, str], dict[str, Any]],
) -> None:
    ordered = [
        rows[(origin.node_id, destination.node_id)]
        for origin in nodes
        for destination in nodes
        if origin != destination
    ]
    raw_fields = list(ordered[0])
    with (output / "raw_runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=raw_fields)
        writer.writeheader()
        writer.writerows(ordered)
    audit_fields = [
        "origin_node_id",
        "destination_node_id",
        "origin_matched_lon",
        "origin_matched_lat",
        "destination_matched_lon",
        "destination_matched_lat",
        "response_sha256",
        "request_sha256",
    ]
    with (output / "coordinate_match_audit.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=audit_fields)
        writer.writeheader()
        writer.writerows(
            {field: row[field] for field in audit_fields} for row in ordered
        )
    unreachable = output / "unreachable_pairs.csv"
    if not unreachable.exists():
        unreachable.write_text(
            "origin_node_id,destination_node_id,reason\n", encoding="utf-8"
        )


def write_matrix(
    path: Path,
    nodes: list[Node],
    rows: dict[tuple[str, str], dict[str, Any]],
    field: str,
) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["node_id", *(node.node_id for node in nodes)])
        for origin in nodes:
            values: list[str] = []
            for destination in nodes:
                if origin.node_id == destination.node_id:
                    values.append("0.000000000")
                else:
                    values.append(
                        f"{float(rows[(origin.node_id, destination.node_id)][field]):.9f}"
                    )
            writer.writerow([origin.node_id, *values])
    os.replace(temporary, path)


def write_hashes(output: Path) -> None:
    hashes = {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    (output / "artifact_hashes.json").write_text(
        json.dumps(hashes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:5000")
    parser.add_argument("--profile", default="driving")
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--graph-manifest", type=Path, required=True)
    args = parser.parse_args()

    nodes = load_nodes(args.nodes)
    graph_manifest = json.loads(args.graph_manifest.read_text(encoding="utf-8"))
    verify_graph_manifest(args.graph_manifest, graph_manifest)
    args.output.mkdir(parents=True, exist_ok=True)
    freeze_nodes_copy(args.nodes, args.output)
    unreachable_path = args.output / "unreachable_pairs.csv"
    if unreachable_path.is_file() and len(
        unreachable_path.read_text(encoding="utf-8").splitlines()
    ) > 1:
        raise MatrixBuildError(
            "preserved unreachable-pair evidence requires manual review"
        )
    checkpoint = args.output / "ordered_pairs.checkpoint.jsonl"
    rows = completed_rows(checkpoint)
    expected = len(nodes) * (len(nodes) - 1)
    valid_ids = {node.node_id for node in nodes}
    if any(left not in valid_ids or right not in valid_ids for left, right in rows):
        raise MatrixBuildError("checkpoint contains a node outside the frozen node set")

    for origin in nodes:
        for destination in nodes:
            key = (origin.node_id, destination.node_id)
            if origin == destination or key in rows:
                continue
            url = route_url(args.endpoint, args.profile, origin, destination)
            error = ""
            metrics: Metrics | None = None
            started = time.monotonic()
            for attempt in range(1, args.max_attempts + 1):
                try:
                    request = urllib.request.Request(
                        url, headers={"User-Agent": "ReSETP-local-matrix/20260718"}
                    )
                    with urllib.request.urlopen(
                        request, timeout=args.timeout_s
                    ) as response:
                        payload_bytes = response.read()
                    metrics = parse_response(json.loads(payload_bytes))
                    response_sha = hashlib.sha256(payload_bytes).hexdigest()
                    break
                except (
                    MatrixBuildError,
                    json.JSONDecodeError,
                    urllib.error.URLError,
                    TimeoutError,
                    OSError,
                    ValueError,
                ) as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    if attempt < args.max_attempts:
                        time.sleep(min(2**attempt, 10))
            if metrics is None:
                append_unreachable(
                    args.output / "unreachable_pairs.csv",
                    origin,
                    destination,
                    error,
                )
                raise MatrixBuildError(
                    f"unreachable ordered pair {key} after {args.max_attempts} attempts: {error}"
                )
            row = {
                "origin_node_id": origin.node_id,
                "destination_node_id": destination.node_id,
                **asdict(metrics),
                "response_sha256": response_sha,
                "request_sha256": hashlib.sha256(url.encode()).hexdigest(),
                "elapsed_s": time.monotonic() - started,
            }
            append_checkpoint(checkpoint, row)
            rows[key] = row

    if len(rows) != expected:
        raise MatrixBuildError(f"checkpoint has {len(rows)} of {expected} pairs")
    write_matrix(args.output / "road_distance_m.csv", nodes, rows, "distance_m")
    write_matrix(args.output / "road_duration_s.csv", nodes, rows, "duration_s")
    write_matrix(
        args.output / "road_sum_v2d_m3_s2.csv", nodes, rows, "sum_v2d_m3_s2"
    )
    write_pair_audits(args.output, nodes, rows)
    metadata = {
        "schema": "resetp.china.local-directed-road-matrices.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision": VERDICT,
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "node_count": len(nodes),
        "ordered_pair_requests": expected,
        "nodes_sha256": sha256(args.nodes),
        "graph_manifest_sha256": sha256(args.graph_manifest),
        "graph_manifest": graph_manifest,
        "router_endpoint": args.endpoint,
        "route_api_profile_label": args.profile,
        "same_route_metrics": True,
        "reverse_copy_allowed": False,
        "euclidean_fallback_allowed": False,
        "unreachable_pair_policy": "HALT_INSTANCE_NO_REPLACEMENT_AFTER_RESULTS",
    }
    (args.output / "router_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "decision.json").write_text(
        json.dumps(
            {
                "decision": VERDICT,
                "formal_search_allowed": False,
                "ordered_pairs_complete": True,
                "search_evaluations": 0,
                "formal_acceptance_held_until_g1_freeze": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.output / "report.md").write_text(
        "# 本地有向道路三矩阵\n\n"
        f"判决：`{VERDICT}`。共 {len(nodes)} 个节点、{expected} 个独立有向请求。"
        "距离、时间与 `Σ(v²d)` 均来自同一路线 annotation；没有欧氏、反向复制或对称回退。"
        "本包不运行求解器，且在 G1 冻结前不构成正式验收。\n",
        encoding="utf-8",
    )
    write_hashes(args.output)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
