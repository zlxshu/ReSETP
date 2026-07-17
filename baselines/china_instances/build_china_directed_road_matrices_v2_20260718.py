#!/usr/bin/env python3
"""Probe a candidate directed road-matrix method without freezing it.

The probe requests every ordered origin-destination pair independently from an
OSRM-compatible route endpoint.  Distance, duration and ``sum(v^2 d)`` are all
derived from the *same returned route annotation*.  There is deliberately no
Euclidean, symmetric, or uniform-speed fallback.

This is evidence for a user decision, not a formal road-matrix builder.  The
formal decision remains awaiting user approval even when the technical probe
passes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
DEFAULT_ASSIGNMENTS = (
    REPO
    / "data/ChinaInstances/china81_customer_location_assignments_v2_20260718"
    / "assignments.csv"
)
DEFAULT_ROAD_CONTRACT = (
    REPO / "data/ChinaInstances/china_road_matrix_contract_v2_20260718.json"
)
DEFAULT_DEPOT_MANIFEST = (
    REPO
    / "data/ChinaInstances/china_ordinary_commercial_depot_manifest_v2_20260718.json"
)
DEFAULT_OUTPUT = (
    REPO / "data/ChinaInstances/china_road_matrix_probe_v2_20260718"
)
DEFAULT_INSTANCE = "cn-jjj-10c-01-V2-LOCATIONS"
DEFAULT_ENDPOINT = "https://router.project-osrm.org"
OSRM_API_DOCUMENTATION = "https://project-osrm.org/docs/v5.24.0/api/#route-service"
DECISION = "EVIDENCE_OR_PROBE_READY_ROAD_METHOD_AWAITING_USER_APPROVAL"


class ProbeError(RuntimeError):
    """A route response cannot support the required same-path metrics."""


@dataclass(frozen=True)
class ProbeNode:
    node_id: str
    latitude: float
    longitude: float
    osm_type: str
    osm_id: str
    name: str


@dataclass(frozen=True)
class RouteMetrics:
    distance_m: float
    duration_s: float
    annotation_duration_s: float
    routing_delay_s: float
    sum_v2d_m3_s2: float
    source_snap_distance_m: float
    target_snap_distance_m: float
    source_matched_lon: float
    source_matched_lat: float
    target_matched_lon: float
    target_matched_lat: float
    annotation_segments: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_008.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    value = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * earth_radius_m * math.asin(math.sqrt(value))


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProbeError(f"expected JSON object: {path}")
    return value


def read_probe_nodes(path: Path, instance_id: str, limit: int) -> list[ProbeNode]:
    if limit < 2:
        raise ProbeError("--limit must be at least 2")
    nodes: list[ProbeNode] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get("instance_id") != instance_id:
                continue
            nodes.append(
                ProbeNode(
                    node_id=f"C{int(row['city_selection_rank']):03d}",
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    osm_type=row["osm_type"],
                    osm_id=row["osm_id"],
                    name=row.get("name", ""),
                )
            )
            if len(nodes) == limit:
                break
    if len(nodes) != limit:
        raise ProbeError(
            f"{instance_id} supplied {len(nodes)} nodes; {limit} were requested"
        )
    if len({node.node_id for node in nodes}) != len(nodes):
        raise ProbeError("probe node identifiers are not unique")
    if len({(node.latitude, node.longitude) for node in nodes}) != len(nodes):
        raise ProbeError("probe coordinates are not unique")
    return nodes


def route_url(endpoint: str, source: ProbeNode, target: ProbeNode) -> str:
    coordinates = (
        f"{source.longitude:.7f},{source.latitude:.7f};"
        f"{target.longitude:.7f},{target.latitude:.7f}"
    )
    query = urllib.parse.urlencode(
        {
            "alternatives": "false",
            "annotations": "distance,duration",
            "overview": "false",
            "steps": "false",
        }
    )
    return f"{endpoint.rstrip('/')}/route/v1/driving/{coordinates}?{query}"


def parse_route_response(
    payload: dict[str, Any], source: ProbeNode, target: ProbeNode
) -> RouteMetrics:
    if payload.get("code") != "Ok":
        raise ProbeError(f"router code is {payload.get('code')!r}")
    routes = payload.get("routes")
    waypoints = payload.get("waypoints")
    if not isinstance(routes, list) or len(routes) != 1:
        raise ProbeError("response must contain exactly one selected route")
    if not isinstance(waypoints, list) or len(waypoints) != 2:
        raise ProbeError("response must contain two snapped waypoints")
    legs = routes[0].get("legs")
    if not isinstance(legs, list) or len(legs) != 1:
        raise ProbeError("response must contain exactly one route leg")
    annotation = legs[0].get("annotation")
    if not isinstance(annotation, dict):
        raise ProbeError("route annotation is missing")
    distances = annotation.get("distance")
    durations = annotation.get("duration")
    if not isinstance(distances, list) or not isinstance(durations, list):
        raise ProbeError("distance/duration annotations are missing")
    if len(distances) == 0 or len(distances) != len(durations):
        raise ProbeError("annotation arrays are empty or have different lengths")

    distance_m = 0.0
    annotation_duration_s = 0.0
    sum_v2d = 0.0
    for raw_distance, raw_duration in zip(distances, durations, strict=True):
        distance = float(raw_distance)
        duration = float(raw_duration)
        if not math.isfinite(distance) or not math.isfinite(duration):
            raise ProbeError("route annotation contains a non-finite value")
        if distance < 0.0 or duration < 0.0:
            raise ProbeError("route annotation contains a negative value")
        if distance > 0.0 and duration <= 0.0:
            raise ProbeError("positive-distance annotation has zero duration")
        distance_m += distance
        annotation_duration_s += duration
        if distance > 0.0:
            speed_mps = distance / duration
            sum_v2d += speed_mps * speed_mps * distance

    route_duration = float(routes[0].get("duration", math.nan))
    if (
        distance_m <= 0.0
        or annotation_duration_s <= 0.0
        or not math.isfinite(route_duration)
        or route_duration <= 0.0
        or sum_v2d <= 0.0
    ):
        raise ProbeError("same-path metrics must all be positive")
    route_distance = float(routes[0].get("distance", math.nan))
    distance_tolerance = max(1.0, route_distance * 1e-4)
    if not math.isclose(distance_m, route_distance, abs_tol=distance_tolerance):
        raise ProbeError("annotation distance does not close to route distance")
    routing_delay_s = route_duration - annotation_duration_s
    if routing_delay_s < -1.0:
        raise ProbeError("route duration is shorter than annotated edge time")

    matched: list[tuple[float, float]] = []
    for waypoint in waypoints:
        location = waypoint.get("location")
        if not isinstance(location, list) or len(location) != 2:
            raise ProbeError("waypoint location is missing")
        matched.append((float(location[0]), float(location[1])))
    return RouteMetrics(
        distance_m=distance_m,
        duration_s=route_duration,
        annotation_duration_s=annotation_duration_s,
        routing_delay_s=routing_delay_s,
        sum_v2d_m3_s2=sum_v2d,
        source_snap_distance_m=haversine_m(
            source.latitude, source.longitude, matched[0][1], matched[0][0]
        ),
        target_snap_distance_m=haversine_m(
            target.latitude, target.longitude, matched[1][1], matched[1][0]
        ),
        source_matched_lon=matched[0][0],
        source_matched_lat=matched[0][1],
        target_matched_lon=matched[1][0],
        target_matched_lat=matched[1][1],
        annotation_segments=len(distances),
    )


def fetch_route(
    url: str, timeout_s: float, user_agent: str
) -> tuple[bytes, dict[str, str], int]:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        payload = response.read()
        headers = {key.lower(): value for key, value in response.headers.items()}
        return payload, headers, int(response.status)


def write_matrix(
    path: Path, node_ids: list[str], values: list[list[float | None]]
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["node_id", *node_ids])
        for node_id, row in zip(node_ids, values, strict=True):
            writer.writerow(
                [
                    node_id,
                    *(
                        "" if value is None else f"{value:.9f}"
                        for value in row
                    ),
                ]
            )


def count_asymmetric_pairs(matrix: list[list[float | None]]) -> int:
    count = 0
    for left in range(len(matrix)):
        for right in range(left + 1, len(matrix)):
            forward = matrix[left][right]
            reverse = matrix[right][left]
            if forward is None or reverse is None:
                continue
            if not math.isclose(forward, reverse, rel_tol=1e-9, abs_tol=1e-6):
                count += 1
    return count


def write_hash_manifest(output: Path) -> None:
    rows: dict[str, str] = {}
    for path in sorted(output.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        ):
            rows[str(path.relative_to(output))] = sha256(path)
    (output / "artifact_hashes.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assignments", type=Path, default=DEFAULT_ASSIGNMENTS)
    parser.add_argument("--road-contract", type=Path, default=DEFAULT_ROAD_CONTRACT)
    parser.add_argument("--depot-manifest", type=Path, default=DEFAULT_DEPOT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--instance-id", default=DEFAULT_INSTANCE)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--timeout-s", type=float, default=20.0)
    parser.add_argument("--request-delay-s", type=float, default=0.25)
    args = parser.parse_args()

    road_contract = load_json(args.road_contract)
    depot_manifest = load_json(args.depot_manifest)
    nodes = read_probe_nodes(args.assignments, args.instance_id, args.limit)
    node_ids = [node.node_id for node in nodes]
    size = len(nodes)
    distance: list[list[float | None]] = [
        [0.0 if left == right else None for right in range(size)]
        for left in range(size)
    ]
    duration: list[list[float | None]] = [
        [0.0 if left == right else None for right in range(size)]
        for left in range(size)
    ]
    sum_v2d: list[list[float | None]] = [
        [0.0 if left == right else None for right in range(size)]
        for left in range(size)
    ]

    args.output.mkdir(parents=True, exist_ok=True)
    for sidecar in args.output.rglob("._*"):
        if sidecar.is_file():
            sidecar.unlink()
    raw_dir = args.output / "raw_responses"
    if raw_dir.exists():
        shutil.rmtree(raw_dir)
    raw_dir.mkdir()

    with (args.output / "nodes.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "node_id",
                "node_type",
                "latitude",
                "longitude",
                "osm_type",
                "osm_id",
                "name",
            ],
        )
        writer.writeheader()
        for node in nodes:
            writer.writerow(
                {
                    "node_id": node.node_id,
                    "node_type": "customer",
                    "latitude": f"{node.latitude:.7f}",
                    "longitude": f"{node.longitude:.7f}",
                    "osm_type": node.osm_type,
                    "osm_id": node.osm_id,
                    "name": node.name,
                }
            )
    shutil.copyfile(args.output / "nodes.csv", args.output / "source_coordinates.csv")

    run_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    unreachable_rows: list[dict[str, Any]] = []
    response_headers: dict[str, str] = {}
    data_versions: set[str] = set()
    user_agent = "ReSETP-road-matrix-method-probe/20260718"

    for source_index, source in enumerate(nodes):
        for target_index, target in enumerate(nodes):
            if source_index == target_index:
                continue
            url = route_url(args.endpoint, source, target)
            raw_name = f"{source.node_id}__to__{target.node_id}.json"
            raw_path = raw_dir / raw_name
            started = time.monotonic()
            status = "HALT_NO_ROUTE"
            http_status: int | None = None
            error = ""
            metrics: RouteMetrics | None = None
            raw_sha256 = ""
            try:
                payload_bytes, headers, http_status = fetch_route(
                    url, args.timeout_s, user_agent
                )
                response_headers.update(headers)
                raw_path.write_bytes(payload_bytes)
                raw_sha256 = sha256_bytes(payload_bytes)
                payload = json.loads(payload_bytes)
                if payload.get("data_version"):
                    data_versions.add(str(payload["data_version"]))
                metrics = parse_route_response(payload, source, target)
                distance[source_index][target_index] = metrics.distance_m
                duration[source_index][target_index] = metrics.duration_s
                sum_v2d[source_index][target_index] = metrics.sum_v2d_m3_s2
                status = "ROUTE_ANNOTATION_PROBE_OK"
                audit_rows.append(
                    {
                        "origin_node_id": source.node_id,
                        "destination_node_id": target.node_id,
                        "origin_source_latitude": source.latitude,
                        "origin_source_longitude": source.longitude,
                        "origin_matched_latitude": metrics.source_matched_lat,
                        "origin_matched_longitude": metrics.source_matched_lon,
                        "origin_snap_distance_m": metrics.source_snap_distance_m,
                        "destination_source_latitude": target.latitude,
                        "destination_source_longitude": target.longitude,
                        "destination_matched_latitude": metrics.target_matched_lat,
                        "destination_matched_longitude": metrics.target_matched_lon,
                        "destination_snap_distance_m": metrics.target_snap_distance_m,
                        "route_response": f"raw_responses/{raw_name}",
                        "route_response_sha256": raw_sha256,
                    }
                )
            except (
                ProbeError,
                json.JSONDecodeError,
                urllib.error.URLError,
                TimeoutError,
                OSError,
                ValueError,
            ) as exc:
                error = f"{type(exc).__name__}: {exc}"
                if not raw_path.exists():
                    raw_path.write_text(
                        json.dumps(
                            {"request_url": url, "error": error},
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                raw_sha256 = sha256(raw_path)
                unreachable_rows.append(
                    {
                        "origin_node_id": source.node_id,
                        "destination_node_id": target.node_id,
                        "reason": error,
                        "request_url": url,
                        "evidence_path": f"raw_responses/{raw_name}",
                        "evidence_sha256": raw_sha256,
                    }
                )
            elapsed_s = time.monotonic() - started
            run_rows.append(
                {
                    "origin_node_id": source.node_id,
                    "destination_node_id": target.node_id,
                    "status": status,
                    "http_status": "" if http_status is None else http_status,
                    "elapsed_s": f"{elapsed_s:.6f}",
                    "distance_m": "" if metrics is None else f"{metrics.distance_m:.9f}",
                    "duration_s": "" if metrics is None else f"{metrics.duration_s:.9f}",
                    "annotation_duration_s": (
                        "" if metrics is None else f"{metrics.annotation_duration_s:.9f}"
                    ),
                    "routing_delay_s": (
                        "" if metrics is None else f"{metrics.routing_delay_s:.9f}"
                    ),
                    "sum_v2d_m3_s2": (
                        "" if metrics is None else f"{metrics.sum_v2d_m3_s2:.9f}"
                    ),
                    "annotation_segments": (
                        "" if metrics is None else metrics.annotation_segments
                    ),
                    "raw_response": f"raw_responses/{raw_name}",
                    "raw_response_sha256": raw_sha256,
                    "error": error,
                }
            )
            if args.request_delay_s > 0.0:
                time.sleep(args.request_delay_s)

    run_fields = [
        "origin_node_id",
        "destination_node_id",
        "status",
        "http_status",
        "elapsed_s",
        "distance_m",
        "duration_s",
        "annotation_duration_s",
        "routing_delay_s",
        "sum_v2d_m3_s2",
        "annotation_segments",
        "raw_response",
        "raw_response_sha256",
        "error",
    ]
    with (args.output / "raw_runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=run_fields)
        writer.writeheader()
        writer.writerows(run_rows)

    audit_fields = [
        "origin_node_id",
        "destination_node_id",
        "origin_source_latitude",
        "origin_source_longitude",
        "origin_matched_latitude",
        "origin_matched_longitude",
        "origin_snap_distance_m",
        "destination_source_latitude",
        "destination_source_longitude",
        "destination_matched_latitude",
        "destination_matched_longitude",
        "destination_snap_distance_m",
        "route_response",
        "route_response_sha256",
    ]
    with (args.output / "coordinate_match_audit.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=audit_fields)
        writer.writeheader()
        writer.writerows(audit_rows)
    unreachable_fields = [
        "origin_node_id",
        "destination_node_id",
        "reason",
        "request_url",
        "evidence_path",
        "evidence_sha256",
    ]
    with (args.output / "unreachable_pairs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=unreachable_fields)
        writer.writeheader()
        writer.writerows(unreachable_rows)

    write_matrix(args.output / "road_distance_m.csv", node_ids, distance)
    write_matrix(args.output / "road_duration_s.csv", node_ids, duration)
    write_matrix(args.output / "road_sum_v2d_m3_s2.csv", node_ids, sum_v2d)

    expected_ordered_pairs = size * (size - 1)
    successful_pairs = sum(
        row["status"] == "ROUTE_ANNOTATION_PROBE_OK" for row in run_rows
    )
    technical_probe_passed = successful_pairs == expected_ordered_pairs
    entrance_verified = sum(
        bool(
            record.get("entrance_candidate_evidence", {}).get(
                "truck_gate_identity_verified"
            )
        )
        for record in depot_manifest.get("records", [])
    )
    formal_blockers = [
        "METHOD_REQUIRES_USER_APPROVAL_BEFORE_FORMAL_LOCK",
        f"VERIFIED_TRUCK_ENTRANCES_{entrance_verified}_OF_9",
        "DEPOT_AND_CHARGER_NODES_NOT_INCLUDED_IN_THIS_MINIMAL_PROBE",
        "LIVE_PUBLIC_API_IS_NOT_A_FROZEN_OSM_EXTRACT",
        "ROUTER_NAME_VERSION_AND_MAP_SHA256_NOT_EXPOSED_BY_ENDPOINT",
        "DRIVING_PROFILE_IS_NOT_A_VERIFIED_CHINA_FREIGHT_PROFILE",
    ]
    if not technical_probe_passed:
        formal_blockers.append("ONE_OR_MORE_ORDERED_ROUTE_REQUESTS_FAILED")

    router_metadata = {
        "candidate_method": "OSRM-compatible route API with per-edge annotations",
        "candidate_endpoint": args.endpoint,
        "candidate_documentation": OSRM_API_DOCUMENTATION,
        "routing_profile_requested": "driving",
        "router_name": "Project OSRM compatible endpoint",
        "router_version": None,
        "map_extract_timestamp": None,
        "map_extract_sha256": None,
        "data_versions_exposed_by_responses": sorted(data_versions),
        "http_response_headers_observed": response_headers,
        "same_path_metric_rule": {
            "path_choice": "the single route returned for each ordered pair",
            "distance_m": "sum(annotation.distance)",
            "duration_s": "the selected route total duration, including router turn/junction penalties",
            "annotation_duration_s": "sum(annotation.duration), retained for audit",
            "routing_delay_s": "route.duration - sum(annotation.duration), retained for audit",
            "sum_v2d_m3_s2": "sum((annotation.distance / annotation.duration)^2 * annotation.distance)",
            "uniform_speed_fallback": False,
            "euclidean_fallback": False,
            "symmetric_copy_fallback": False,
        },
        "formal_method_locked": False,
        "user_approval_required": True,
    }
    (args.output / "router_metadata.json").write_text(
        json.dumps(router_metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    metadata = {
        "schema": "resetp.china.directed-road-matrix-method-probe.v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision": DECISION,
        "formal_search_allowed": False,
        "method_status": "CANDIDATE_IMPLEMENTATION_NOT_LOCKED",
        "technical_probe_passed": technical_probe_passed,
        "instance_id": args.instance_id,
        "node_count": size,
        "ordered_pair_requests_expected": expected_ordered_pairs,
        "ordered_pair_requests_successful": successful_pairs,
        "ordered_pair_requests_failed": len(unreachable_rows),
        "assignments_path": str(args.assignments.relative_to(REPO)),
        "assignments_sha256": sha256(args.assignments),
        "road_contract_path": str(args.road_contract.relative_to(REPO)),
        "road_contract_sha256": sha256(args.road_contract),
        "road_contract_status_observed": road_contract.get("status"),
        "road_contract_modified": False,
        "depot_manifest_path": str(args.depot_manifest.relative_to(REPO)),
        "depot_manifest_sha256": sha256(args.depot_manifest),
        "verified_truck_entrances_observed": entrance_verified,
        "distance_asymmetric_pairs": count_asymmetric_pairs(distance),
        "duration_asymmetric_pairs": count_asymmetric_pairs(duration),
        "sum_v2d_asymmetric_pairs": count_asymmetric_pairs(sum_v2d),
        "search_evaluations": 0,
        "formal_blockers": formal_blockers,
    }
    (args.output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    decision = {
        "decision": DECISION,
        "formal_search_allowed": False,
        "technical_probe_passed": technical_probe_passed,
        "candidate_method_may_be_formally_adopted_without_user_approval": False,
        "existing_road_contract_changed": False,
        "formal_blockers": formal_blockers,
    }
    (args.output / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report = f"""# 中国正式有向道路三矩阵方法候选探针

判决：`{DECISION}`。`formal_search_allowed=false`。

本包只证明候选实现是否能从同一条返回路径生成三项指标，不批准、锁定或替换现有道路构造合同。用户批准前不得用于正式算例或正式搜索。

## 技术探针

- 最小子集：`{args.instance_id}` 的前 {size} 个冻结客户位置。
- 有向请求：逐方向独立请求 {expected_ordered_pairs} 对，成功 {successful_pairs}，失败 {len(unreachable_rows)}。
- 技术探针通过：`{technical_probe_passed}`。
- 三矩阵：`road_distance_m.csv`、`road_duration_s.csv`、`road_sum_v2d_m3_s2.csv`。
- 同路径定义：每一有向节点对只采用该次响应选中的一条路线；距离、时间和 `Σ(v²d)` 均由该路线逐段 annotation 同时计算。
- 禁止回退：未使用欧氏距离、直线倍数、统一速度或反向矩阵复制。
- 非对称节点对：距离 {metadata['distance_asymmetric_pairs']}，时间 {metadata['duration_asymmetric_pairs']}，`Σ(v²d)` {metadata['sum_v2d_asymmetric_pairs']}。

## 为什么仍不能正式使用

{chr(10).join(f"- `{item}`" for item in formal_blockers)}

当前车场 manifest 中经核验的货车入口为 {entrance_verified}/9。本探针也不含车场或充电站。公开在线端点没有向本包暴露可冻结的路由器版本和地图 SHA-256，因此即使技术请求全部成功，也只能交给用户决定下一步是否批准本方法，不能写成正式锁定。
"""
    (args.output / "report.md").write_text(report, encoding="utf-8")
    write_hash_manifest(args.output)
    print(json.dumps(decision | {"metadata": metadata}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
