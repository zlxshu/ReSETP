#!/usr/bin/env python3
"""Build a customer-only directed road-matrix feasibility probe from a frozen OSM PBF.

This probe deliberately excludes depots and charging stations.  Its purpose is
to test the offline routing method before verified vehicle entrances are
frozen.  It must not be used for formal optimization.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import osmium
from scipy.spatial import cKDTree


EARTH_RADIUS_M = 6_371_008.8
EXCLUDED_HIGHWAYS = {
    "bridleway",
    "construction",
    "corridor",
    "cycleway",
    "elevator",
    "footway",
    "path",
    "pedestrian",
    "planned",
    "platform",
    "proposed",
    "raceway",
    "steps",
}
DEFAULT_SPEED_KPH = {
    "motorway": 100.0,
    "motorway_link": 50.0,
    "trunk": 80.0,
    "trunk_link": 40.0,
    "primary": 60.0,
    "primary_link": 35.0,
    "secondary": 50.0,
    "secondary_link": 30.0,
    "tertiary": 40.0,
    "tertiary_link": 25.0,
    "unclassified": 30.0,
    "residential": 30.0,
    "living_street": 10.0,
    "service": 20.0,
    "road": 20.0,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    value = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(value))


def parse_maxspeed_kph(raw: str | None) -> float | None:
    if not raw:
        return None
    values: list[float] = []
    for item in raw.replace("|", ";").split(";"):
        text = item.strip().lower()
        if not text:
            continue
        multiplier = 1.609344 if "mph" in text else 1.0
        numeric = "".join(ch for ch in text if ch.isdigit() or ch == ".")
        try:
            value = float(numeric) * multiplier
        except ValueError:
            continue
        if 3.0 <= value <= 160.0:
            values.append(value)
    return min(values) if values else None


def restricted(tags: osmium.osm.TagList) -> bool:
    for key in ("motor_vehicle", "motorcar", "vehicle", "access"):
        value = tags.get(key)
        if value in {"no", "private"}:
            return True
        if value in {"yes", "permissive", "destination", "delivery"}:
            return False
    return False


@dataclass(frozen=True)
class Edge:
    source_osm_id: int
    target_osm_id: int
    distance_m: float
    duration_s: float
    speed_source: str


class RoadGraphHandler(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.coordinates: dict[int, tuple[float, float]] = {}
        self.edges: list[Edge] = []
        self.ways_seen = 0
        self.ways_kept = 0
        self.edges_with_tagged_speed = 0
        self.edges_with_default_speed = 0

    def way(self, way: osmium.osm.Way) -> None:
        self.ways_seen += 1
        highway = way.tags.get("highway")
        if (
            not highway
            or highway in EXCLUDED_HIGHWAYS
            or highway not in DEFAULT_SPEED_KPH
            or restricted(way.tags)
        ):
            return
        points: list[tuple[int, float, float]] = []
        for node in way.nodes:
            if not node.location.valid():
                return
            points.append((node.ref, node.location.lat, node.location.lon))
        if len(points) < 2:
            return

        tagged_speed = parse_maxspeed_kph(way.tags.get("maxspeed"))
        speed_kph = tagged_speed or DEFAULT_SPEED_KPH[highway]
        speed_source = "maxspeed_tag" if tagged_speed else f"probe_default:{highway}"
        oneway = (way.tags.get("oneway") or "").lower()
        is_roundabout = (way.tags.get("junction") or "").lower() == "roundabout"
        forward = oneway != "-1"
        reverse = oneway not in {"yes", "1", "true", "-1"} and not is_roundabout

        self.ways_kept += 1
        for node_id, lat, lon in points:
            self.coordinates[node_id] = (lat, lon)
        pairs = zip(points[:-1], points[1:])
        for left, right in pairs:
            distance = haversine_m(left[1], left[2], right[1], right[2])
            if distance <= 0.0:
                continue
            duration = distance / (speed_kph / 3.6)
            if forward:
                self.edges.append(Edge(left[0], right[0], distance, duration, speed_source))
            if reverse:
                self.edges.append(Edge(right[0], left[0], distance, duration, speed_source))
            if tagged_speed:
                self.edges_with_tagged_speed += int(forward) + int(reverse)
            else:
                self.edges_with_default_speed += int(forward) + int(reverse)


def read_customer_nodes(path: Path, limit: int | None) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["node_type"].strip().lower() != "c":
                continue
            selected.append(
                {
                    "node_id": row["node_id"],
                    "latitude": float(row["latitude"]),
                    "longitude": float(row["longitude"]),
                }
            )
            if limit is not None and len(selected) >= limit:
                break
    if len(selected) < 2:
        raise ValueError("The probe requires at least two customer nodes.")
    return selected


def projected_xy(lat: np.ndarray, lon: np.ndarray, reference_lat: float) -> np.ndarray:
    x = np.radians(lon) * EARTH_RADIUS_M * math.cos(math.radians(reference_lat))
    y = np.radians(lat) * EARTH_RADIUS_M
    return np.column_stack((x, y))


def build_adjacency(
    edges: Iterable[Edge],
) -> tuple[
    dict[int, list[tuple[int, float, float]]],
    dict[tuple[int, int], tuple[float, float]],
]:
    adjacency: dict[int, list[tuple[int, float, float]]] = {}
    edge_lookup: dict[tuple[int, int], tuple[float, float]] = {}
    for edge in edges:
        key = (edge.source_osm_id, edge.target_osm_id)
        previous = edge_lookup.get(key)
        if previous is not None and previous[1] <= edge.duration_s:
            continue
        edge_lookup[key] = (edge.distance_m, edge.duration_s)
    for (source, target), (distance, duration) in edge_lookup.items():
        adjacency.setdefault(source, []).append((target, duration, distance))
    return adjacency, edge_lookup


def fastest_paths(
    adjacency: dict[int, list[tuple[int, float, float]]],
    source: int,
    targets: set[int],
) -> tuple[dict[int, float], dict[int, float]]:
    best_time = {source: 0.0}
    best_distance = {source: 0.0}
    queue: list[tuple[float, int]] = [(0.0, source)]
    remaining = set(targets)
    while queue and remaining:
        time_so_far, current = heapq.heappop(queue)
        if time_so_far != best_time.get(current):
            continue
        remaining.discard(current)
        for target, edge_time, edge_distance in adjacency.get(current, ()):
            candidate_time = time_so_far + edge_time
            if candidate_time < best_time.get(target, math.inf):
                best_time[target] = candidate_time
                best_distance[target] = best_distance[current] + edge_distance
                heapq.heappush(queue, (candidate_time, target))
    return best_time, best_distance


def write_csv_matrix(path: Path, node_ids: list[str], matrix: np.ndarray) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["node_id", *node_ids])
        for node_id, row in zip(node_ids, matrix, strict=True):
            writer.writerow([node_id, *(f"{value:.6f}" for value in row)])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pbf", required=True, type=Path)
    parser.add_argument("--nodes", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-snap-m", type=float, default=1000.0)
    args = parser.parse_args()

    customers = read_customer_nodes(args.nodes, args.limit)
    handler = RoadGraphHandler()
    handler.apply_file(str(args.pbf), locations=True, idx="flex_mem")
    if not handler.coordinates or not handler.edges:
        raise RuntimeError("No routable graph was extracted from the PBF.")

    osm_ids = np.fromiter(handler.coordinates.keys(), dtype=np.int64)
    coordinates = np.asarray([handler.coordinates[int(key)] for key in osm_ids], dtype=float)
    reference_lat = float(np.mean(coordinates[:, 0]))
    tree = cKDTree(projected_xy(coordinates[:, 0], coordinates[:, 1], reference_lat))
    query_lat = np.asarray([float(row["latitude"]) for row in customers])
    query_lon = np.asarray([float(row["longitude"]) for row in customers])
    snap_distances, positions = tree.query(
        projected_xy(query_lat, query_lon, reference_lat), k=1
    )
    snapped_osm_ids = [int(osm_ids[int(position)]) for position in positions]
    duplicate_snap_count = len(snapped_osm_ids) - len(set(snapped_osm_ids))

    adjacency, _ = build_adjacency(handler.edges)
    count = len(customers)
    duration_matrix = np.full((count, count), np.inf, dtype=float)
    distance_matrix = np.full((count, count), np.inf, dtype=float)
    target_set = set(snapped_osm_ids)
    for index, source in enumerate(snapped_osm_ids):
        best_time, best_distance = fastest_paths(adjacency, source, target_set)
        for target_index, target in enumerate(snapped_osm_ids):
            duration_matrix[index, target_index] = best_time.get(target, math.inf)
            distance_matrix[index, target_index] = best_distance.get(target, math.inf)
    np.fill_diagonal(duration_matrix, 0.0)
    np.fill_diagonal(distance_matrix, 0.0)

    args.output.mkdir(parents=True, exist_ok=True)
    node_ids = [str(row["node_id"]) for row in customers]
    write_csv_matrix(args.output / "road_distance_m.csv", node_ids, distance_matrix)
    write_csv_matrix(args.output / "road_duration_s.csv", node_ids, duration_matrix)
    with (args.output / "coordinate_match_audit.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "node_id",
                "source_latitude",
                "source_longitude",
                "matched_osm_node_id",
                "matched_latitude",
                "matched_longitude",
                "snap_distance_m",
                "within_probe_threshold",
            ],
        )
        writer.writeheader()
        for row, osm_id, snap_distance in zip(
            customers, snapped_osm_ids, snap_distances, strict=True
        ):
            matched_lat, matched_lon = handler.coordinates[osm_id]
            writer.writerow(
                {
                    "node_id": row["node_id"],
                    "source_latitude": row["latitude"],
                    "source_longitude": row["longitude"],
                    "matched_osm_node_id": osm_id,
                    "matched_latitude": matched_lat,
                    "matched_longitude": matched_lon,
                    "snap_distance_m": f"{float(snap_distance):.6f}",
                    "within_probe_threshold": bool(snap_distance <= args.max_snap_m),
                }
            )

    finite = bool(np.isfinite(distance_matrix).all() and np.isfinite(duration_matrix).all())
    off_diagonal_mask = ~np.eye(count, dtype=bool)
    positive_off_diagonal = bool(
        np.all(distance_matrix[off_diagonal_mask] > 0.0)
        and np.all(duration_matrix[off_diagonal_mask] > 0.0)
    )
    asymmetric_distance_pairs = int(
        np.count_nonzero(~np.isclose(distance_matrix, distance_matrix.T)) // 2
    )
    asymmetric_duration_pairs = int(
        np.count_nonzero(~np.isclose(duration_matrix, duration_matrix.T)) // 2
    )
    metadata = {
        "schema": "resetp.china.directed-road-matrix-probe.v2",
        "status": "TECHNICAL_CUSTOMER_ONLY_PROBE_NOT_FORMAL",
        "formal_search_allowed": False,
        "pbf_path": str(args.pbf),
        "pbf_sha256": sha256(args.pbf),
        "nodes_path": str(args.nodes),
        "nodes_sha256": sha256(args.nodes),
        "router": "custom pyosmium directed fastest-path probe",
        "speed_model": {
            "maxspeed_tags_used_when_parseable": True,
            "untagged_road_defaults": DEFAULT_SPEED_KPH,
            "default_values_are_unfrozen_probe_assumptions": True,
        },
        "ways_seen": handler.ways_seen,
        "ways_kept": handler.ways_kept,
        "directed_edges": len(handler.edges),
        "edges_with_tagged_speed": handler.edges_with_tagged_speed,
        "edges_with_default_speed": handler.edges_with_default_speed,
        "customer_count": count,
        "max_snap_distance_m": float(np.max(snap_distances)),
        "duplicate_snap_count": duplicate_snap_count,
        "all_snaps_within_probe_threshold": bool(
            np.all(snap_distances <= args.max_snap_m)
        ),
        "all_pairs_reachable": finite,
        "all_off_diagonal_values_positive": positive_off_diagonal,
        "asymmetric_distance_pairs": asymmetric_distance_pairs,
        "asymmetric_duration_pairs": asymmetric_duration_pairs,
        "limitations": [
            "Depots and charging stations are intentionally excluded.",
            "OSM truck restrictions are incomplete in China.",
            "Fallback road-class speeds are probe assumptions, not frozen parameters.",
            "No live or historical traffic is represented.",
        ],
    }
    (args.output / "router_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    decision = {
        "decision": (
            "PASS_TECHNICAL_METHOD_ONLY"
            if (
                finite
                and positive_off_diagonal
                and metadata["all_snaps_within_probe_threshold"]
            )
            else "HALT_TECHNICAL_PROBE"
        ),
        "formal_search_allowed": False,
        "reasons": {
            "all_pairs_reachable": finite,
            "all_off_diagonal_values_positive": positive_off_diagonal,
            "duplicate_snap_count": duplicate_snap_count,
            "all_snaps_within_probe_threshold": metadata[
                "all_snaps_within_probe_threshold"
            ],
            "verified_depot_entrance_included": False,
            "verified_chargers_included": False,
            "speed_defaults_frozen": False,
        },
    }
    (args.output / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (args.output / "raw_runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "status",
                "customer_count",
                "ways_seen",
                "ways_kept",
                "directed_edges",
                "max_snap_distance_m",
                "duplicate_snap_count",
                "all_pairs_reachable",
                "all_off_diagonal_values_positive",
                "asymmetric_distance_pairs",
                "asymmetric_duration_pairs",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "status": decision["decision"],
                "customer_count": count,
                "ways_seen": handler.ways_seen,
                "ways_kept": handler.ways_kept,
                "directed_edges": len(handler.edges),
                "max_snap_distance_m": metadata["max_snap_distance_m"],
                "duplicate_snap_count": duplicate_snap_count,
                "all_pairs_reachable": finite,
                "all_off_diagonal_values_positive": positive_off_diagonal,
                "asymmetric_distance_pairs": asymmetric_distance_pairs,
                "asymmetric_duration_pairs": asymmetric_duration_pairs,
            }
        )
    report = f"""# 中国有向道路矩阵技术探针

结论：`{decision["decision"]}`。这是客户节点技术探针，不含核验后的车场入口和充电站，不授权正式搜索。

- 客户数：{count}
- OSM 道路 ways：读取 {handler.ways_seen}，保留 {handler.ways_kept}
- 有向边数：{len(handler.edges)}
- 最大道路吸附距离：{metadata["max_snap_distance_m"]:.3f} m
- 重复道路吸附节点数：{duplicate_snap_count}
- 全对可达：{finite}
- 非对角距离和时间均为正：{positive_off_diagonal}
- 非对称距离节点对：{asymmetric_distance_pairs}
- 非对称时间节点对：{asymmetric_duration_pairs}

当前速度缺失道路使用未冻结的道路等级技术默认值；中国货车限高、限重、时段和通行证覆盖不完整。正式矩阵必须在普通商业车场入口、充电站、速度来源和三矩阵语义闭合后重新生成。
"""
    (args.output / "report.md").write_text(report, encoding="utf-8")
    hash_rows = {}
    for path in sorted(args.output.iterdir()):
        if path.is_file() and path.name != "artifact_hashes.json":
            hash_rows[path.name] = sha256(path)
    (args.output / "artifact_hashes.json").write_text(
        json.dumps(hash_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({**decision, "metadata": metadata}, ensure_ascii=False, indent=2))
    return 0 if decision["decision"] == "PASS_TECHNICAL_METHOD_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
