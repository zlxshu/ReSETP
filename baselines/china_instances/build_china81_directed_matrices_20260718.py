#!/usr/bin/env python3
"""Build all China81 directed matrices with a resumable regional route cache."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict
from pathlib import Path

from build_local_directed_road_matrices_20260718 import (
    MatrixBuildError,
    Node,
    parse_response,
    route_url,
    sha256,
)


REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718"
GRAPHS = REPO / "data/ChinaInstances/china_stage2_sparse_connected_osrm_graphs_v5_20260718/graphs"
OUT = REPO / "data/ChinaInstances/china81_local_directed_matrices_v9_20260718"
GRAPH_REGION = {"jjj": "jjj", "prd": "prd", "cy": "cy"}
FIELDS = [
    "origin_key", "destination_key", "distance_m", "duration_s",
    "annotation_duration_s", "routing_delay_s", "sum_v2d_m3_s2",
    "origin_matched_lon", "origin_matched_lat", "destination_matched_lon",
    "destination_matched_lat", "annotation_segments",
    "zero_duration_positive_distance_segments", "colocated_snapped_pair",
    "subresolution_zero_duration_pair", "via_repair", "via_matched_lon",
    "via_matched_lat", "response_sha256",
    "request_sha256",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def key(row: dict[str, str]) -> str:
    return f"{float(row['longitude']):.7f},{float(row['latitude']):.7f}"


def node_from_key(value: str) -> Node:
    lon, lat = map(float, value.split(","))
    return Node(value, "cache", lat, lon)


def init_db(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute(
        """CREATE TABLE IF NOT EXISTS routes(
        origin_key TEXT NOT NULL, destination_key TEXT NOT NULL,
        distance_m REAL NOT NULL, duration_s REAL NOT NULL,
        annotation_duration_s REAL NOT NULL, routing_delay_s REAL NOT NULL,
        sum_v2d_m3_s2 REAL NOT NULL, origin_matched_lon REAL NOT NULL,
        origin_matched_lat REAL NOT NULL, destination_matched_lon REAL NOT NULL,
        destination_matched_lat REAL NOT NULL, annotation_segments INTEGER NOT NULL,
        zero_duration_positive_distance_segments INTEGER NOT NULL,
        colocated_snapped_pair INTEGER NOT NULL,
        subresolution_zero_duration_pair INTEGER NOT NULL,
        via_repair INTEGER NOT NULL,
        via_matched_lon REAL NOT NULL, via_matched_lat REAL NOT NULL,
        response_sha256 TEXT NOT NULL, request_sha256 TEXT NOT NULL,
        PRIMARY KEY(origin_key,destination_key))"""
    )
    db.commit()
    return db


def request_bytes(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": "ReSETP-China81/20260718"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def via_url(endpoint: str, pair: tuple[str, str], via: tuple[float, float]) -> str:
    origin_key, destination_key = pair
    coordinates = (
        f"{origin_key};{via[0]:.7f},{via[1]:.7f};{destination_key}"
    )
    query = urllib.parse.urlencode(
        {
            "alternatives": "false",
            "annotations": "distance,duration",
            "overview": "false",
            "steps": "false",
            "radiuses": "10000;10000;10000",
            "continue_straight": "false",
        }
    )
    return f"{endpoint.rstrip('/')}/route/v1/driving/{coordinates}?{query}"


def nearest_via_candidates(
    endpoint: str, pair: tuple[str, str], timeout: float
) -> list[tuple[float, float, float]]:
    candidates: dict[tuple[float, float], float] = {}
    for coordinate in pair:
        url = (
            f"{endpoint.rstrip('/')}/nearest/v1/driving/{coordinate}"
            "?number=32"
        )
        payload = json.loads(request_bytes(url, timeout))
        if payload.get("code") != "Ok":
            raise MatrixBuildError("nearest candidate query failed")
        for waypoint in payload.get("waypoints", []):
            location = waypoint.get("location")
            if not isinstance(location, list) or len(location) != 2:
                continue
            key = (float(location[0]), float(location[1]))
            offset = float(waypoint.get("distance", float("inf")))
            candidates[key] = min(offset, candidates.get(key, float("inf")))
    return sorted(
        ((offset, longitude, latitude) for (longitude, latitude), offset in candidates.items())
    )


def row_from_response(
    pair: tuple[str, str], url: str, raw: bytes
) -> tuple:
    metrics = parse_response(json.loads(raw))
    return (
        pair[0], pair[1],
        *[getattr(metrics, name) for name in FIELDS[2:-2]],
        hashlib.sha256(raw).hexdigest(),
        hashlib.sha256(url.encode()).hexdigest(),
    )


def fetch(endpoint: str, pair: tuple[str, str], timeout: float) -> tuple:
    origin_key, destination_key = pair
    url = route_url(endpoint, "driving", node_from_key(origin_key), node_from_key(destination_key))
    last = ""
    no_route = False
    for attempt in range(3):
        try:
            return row_from_response(pair, url, request_bytes(url, timeout))
        except urllib.error.HTTPError as exc:
            raw_error = exc.read()
            try:
                no_route = json.loads(raw_error).get("code") == "NoRoute"
            except json.JSONDecodeError:
                no_route = False
            last = f"HTTPError: HTTP {exc.code}"
            if no_route:
                break
        except (OSError, ValueError, TimeoutError, urllib.error.URLError, MatrixBuildError) as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(0.25 * (attempt + 1))
    if no_route:
        best: tuple[tuple[float, float, float, float, float], tuple] | None = None
        for offset, longitude, latitude in nearest_via_candidates(
            endpoint, pair, timeout
        ):
            candidate_url = via_url(
                endpoint, pair, (longitude, latitude)
            )
            try:
                candidate_row = row_from_response(
                    pair, candidate_url, request_bytes(candidate_url, timeout)
                )
            except urllib.error.HTTPError:
                continue
            metrics_key = (
                float(candidate_row[FIELDS.index("distance_m")]),
                float(candidate_row[FIELDS.index("duration_s")]),
                offset,
                longitude,
                latitude,
            )
            if best is None or metrics_key < best[0]:
                best = (metrics_key, candidate_row)
        if best is not None:
            return best[1]
    raise MatrixBuildError(f"unreachable {pair}: {last}")


def required_pairs(region: str, catalog: list[dict[str, str]]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for item in catalog:
        if item["region"] != region:
            continue
        nodes = read_csv(STATIC / "instances" / item["instance_id"] / "nodes.csv")
        keys = [key(row) for row in nodes]
        pairs.update((a, b) for a in keys for b in keys if a != b)
    return pairs


def start_router(graph_base: Path, port: int, threads: int) -> subprocess.Popen:
    log = OUT / "router_logs" / f"{graph_base.parent.parent.name}-{graph_base.parent.name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        ["osrm-routed", "--algorithm", "ch", "--threads", str(threads),
         "--port", str(port), str(graph_base)],
        cwd=REPO, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True,
    )
    endpoint = f"http://127.0.0.1:{port}"
    sample = Node("a", "cache", 39.9, 116.4)
    for _ in range(120):
        if proc.poll() is not None:
            raise MatrixBuildError(f"osrm-routed exited; see {log}")
        try:
            urllib.request.urlopen(route_url(endpoint, "driving", sample, sample), timeout=1).read()
            return proc
        except urllib.error.HTTPError as exc:
            # A same-coordinate Route request is deliberately invalid in OSRM,
            # but an HTTP 400 response proves the routed service is accepting
            # requests. Real ordered pairs still require code=Ok in fetch().
            if exc.code == 400:
                return proc
            time.sleep(0.25)
        except Exception:
            time.sleep(0.25)
    proc.terminate()
    raise MatrixBuildError(f"osrm-routed health timeout; see {log}")


def restore_graph_to_apfs(
    graph_dir: Path, manifest: dict, runtime_dir: Path, graph_name: str
) -> Path:
    expected = manifest.get("apfs_to_archive_copy_hashes", {})
    if not expected:
        raise MatrixBuildError(f"missing APFS/archive copy hashes: {graph_dir}")
    for filename, expected_hash in sorted(expected.items()):
        source = graph_dir / filename
        target = runtime_dir / filename
        if not source.is_file() or sha256(source) != expected_hash:
            raise MatrixBuildError(f"archived graph hash drift: {source}")
        shutil.copy2(source, target)
        if sha256(target) != expected_hash:
            raise MatrixBuildError(f"APFS restore hash drift: {target}")
    graph_base = runtime_dir / graph_name
    if not graph_base.with_suffix(".osrm.hsgr").is_file():
        raise MatrixBuildError(f"restored contracted graph missing: {graph_base}")
    return graph_base


def fill_cache(
    db: sqlite3.Connection, endpoint: str, required: set[tuple[str, str]],
    workers: int, timeout: float, checkpoint: Path,
) -> None:
    existing = set(db.execute("SELECT origin_key,destination_key FROM routes"))
    pending = iter(sorted(required - existing))
    completed = len(existing & required)
    total = len(required)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for _ in range(workers * 4):
            try:
                pair = next(pending)
            except StopIteration:
                break
            futures[pool.submit(fetch, endpoint, pair, timeout)] = pair
        batch = []
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                pair = futures.pop(future)
                batch.append(future.result())
                completed += 1
                try:
                    nxt = next(pending)
                    futures[pool.submit(fetch, endpoint, nxt, timeout)] = nxt
                except StopIteration:
                    pass
            if len(batch) >= 500 or not futures:
                db.executemany(
                    "INSERT OR REPLACE INTO routes VALUES("
                    + ",".join("?" for _ in FIELDS)
                    + ")",
                    batch,
                )
                db.commit()
                batch.clear()
                checkpoint.write_text(
                    json.dumps({"completed": completed, "required": total, "updated": time.time()}) + "\n",
                    encoding="utf-8",
                )


def write_matrix(path: Path, nodes: list[dict[str, str]], cache: dict, field: str) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["node_id", *[r["node_id"] for r in nodes]])
        for left in nodes:
            values = []
            for right in nodes:
                if left["node_id"] == right["node_id"]:
                    values.append("0.000000000")
                else:
                    values.append(f"{cache[(key(left), key(right))][field]:.9f}")
            w.writerow([left["node_id"], *values])


def materialize(
    region: str, profile: str, db: sqlite3.Connection, catalog: list[dict[str, str]]
) -> int:
    columns = [row[1] for row in db.execute("PRAGMA table_info(routes)")]
    cache = {}
    for row in db.execute("SELECT * FROM routes"):
        payload = dict(zip(columns, row, strict=True))
        cache[(payload["origin_key"], payload["destination_key"])] = payload
    count = 0
    for item in catalog:
        if item["region"] != region:
            continue
        nodes = read_csv(STATIC / "instances" / item["instance_id"] / "nodes.csv")
        target = OUT / "instances" / item["instance_id"] / profile
        target.mkdir(parents=True, exist_ok=True)
        source = STATIC / "instances" / item["instance_id"] / "nodes.csv"
        (target / "nodes.csv").write_bytes(source.read_bytes())
        write_matrix(target / "road_distance_m.csv", nodes, cache, "distance_m")
        write_matrix(target / "road_duration_s.csv", nodes, cache, "duration_s")
        write_matrix(target / "road_sum_v2d_m3_s2.csv", nodes, cache, "sum_v2d_m3_s2")
        with (target / "raw_runs.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for left in nodes:
                for right in nodes:
                    if left["node_id"] != right["node_id"]:
                        w.writerow(cache[(key(left), key(right))])
        count += len(nodes) * (len(nodes) - 1)
    return count


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--router-threads", type=int, default=6)
    parser.add_argument("--timeout-s", type=float, default=20)
    args = parser.parse_args()
    if not 1 <= args.workers <= 64:
        raise MatrixBuildError("workers out of range")
    OUT.mkdir(parents=True, exist_ok=True)
    catalog = read_csv(STATIC / "instance_catalog.csv")
    raw_rows = []
    for region_index, region in enumerate(("jjj", "prd", "cy")):
        graph_region = GRAPH_REGION[region]
        for profile_index, profile in enumerate(("cv", "ev")):
            graph_dir = GRAPHS / graph_region / profile
            manifest = graph_dir / "graph_manifest.json"
            archived_base = graph_dir / f"{graph_region}-{profile}.osrm"
            if not manifest.is_file() or not archived_base.with_suffix(".osrm.hsgr").is_file():
                raise MatrixBuildError(f"missing accepted graph: {graph_dir}")
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
            required = required_pairs(region, catalog)
            db_path = OUT / f"route_cache_{region}_{profile}.sqlite"
            db = init_db(db_path)
            port = 5100 + region_index * 10 + profile_index
            started = time.monotonic()
            with tempfile.TemporaryDirectory(
                prefix=f"resetp-matrix-{region}-{profile}-", dir="/tmp"
            ) as runtime_name:
                graph_base = restore_graph_to_apfs(
                    graph_dir,
                    manifest_payload,
                    Path(runtime_name),
                    archived_base.name,
                )
                proc = start_router(graph_base, port, args.router_threads)
                try:
                    fill_cache(db, f"http://127.0.0.1:{port}", required, args.workers,
                               args.timeout_s, OUT / f"checkpoint_{region}_{profile}.json")
                    pairs = materialize(region, profile, db, catalog)
                finally:
                    proc.terminate()
                    try:
                        proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    db.close()
            raw_rows.append({
                "region": region, "profile": profile, "unique_route_requests": len(required),
                "materialized_ordered_pairs": pairs, "elapsed_seconds": time.monotonic() - started,
                "search_evaluations": 0, "status": "PASS",
            })
            with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(raw_rows[0]))
                w.writeheader()
                w.writerows(raw_rows)
    total = sum(int(r["materialized_ordered_pairs"]) for r in raw_rows)
    metadata = {
        "schema": "resetp.china81-local-directed-matrices.v1",
        "router": "OSRM 26.7.3 CH Route API",
        "instances": 81, "profiles": ["cv", "ev"], "ordered_pairs": total,
        "same_route_distance_duration_sum_v2d": True,
        "euclidean_or_symmetry_fallback": False, "search_evaluations": 0,
        "runtime_filesystem": "APFS /tmp with archive hash verification",
        "formal_search_allowed": False, "draft_only": True,
    }
    write_json(OUT / "metadata.json", metadata)
    write_json(OUT / "decision.json", {
        "verdict": "PASS_CHINA81_LOCAL_DIRECTED_THREE_MATRICES__FORMAL_ACCEPTANCE_HELD",
        "ordered_pairs_complete": total == 1578948, "unreachable_pairs": 0,
        "formal_experiment_authorized": False, "search_evaluations": 0,
    })
    (OUT / "report.md").write_text(
        "# China81 本地有向道路三矩阵\n\n"
        f"81 个实例、CV/EV 两套 profile 共物化 {total} 个有向节点对。距离、时间与"
        "`Σ(v²d)`来自同一条 OSRM Route API 路线；无欧氏、对称或反向复制回退。"
        "本任务零求解器搜索，G1 冻结前不构成正式验收。\n", encoding="utf-8",
    )
    hashes = {}
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._"):
            hashes[str(path.relative_to(OUT))] = sha256(path)
    write_json(OUT / "artifact_hashes.json", {"sha256": hashes})
    print(json.dumps(metadata, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
