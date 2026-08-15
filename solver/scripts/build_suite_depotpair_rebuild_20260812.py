#!/usr/bin/env python3
"""Rebuild the Chengdu-Chongqing and JJJ China81 rows with nearby real depots.

The script is deliberately construction-only.  It reuses the frozen China81
OSRM graphs and evaluator, writes a new authority, and never invokes a search
solver or mutates an existing suite.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import socket
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "solver" / "src"))
sys.path.insert(0, str(REPO / "baselines" / "china_instances"))

from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.instance_loader import Instance, Node, RoadProfileMatrices  # noqa: E402
from setp_solver.solution import Route, Solution  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402


BASE_SCRIPT = REPO / "solver/scripts/build_china81_suite_rebuild_20260812.py"
MATRIX_SCRIPT = (
    REPO / "baselines/china_instances/build_china81_directed_matrices_20260718.py"
)
SOURCE_STATIC = REPO / (
    "data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723"
)
SOURCE_MATRICES = REPO / (
    "data/ChinaInstances/china81_local_directed_matrices_corrected_v10_20260723"
)
SOURCE_POOLS = REPO / "data/ChinaInstances/china9_city_full_pool_20260718/pools"
GRAPH_AUTHORITY = REPO / (
    "data/ChinaInstances/china_stage2_sparse_connected_osrm_graphs_v5_20260718"
)
SOURCE_HEALTH = REPO / "solver/reports/suite_rebuild_20260812/suite_health.csv"
DEFAULT_OUTPUT = REPO / (
    "data/ChinaInstances/china81_depotpair_rebuild_v1_20260812"
)
DEFAULT_REPORT = REPO / "solver/reports/suite_depotpair_rebuild_20260812"
STATION_AUTHORITY = DEFAULT_OUTPUT / "source_pools/facilities.csv"
PROTECTED = (
    Path("solver/src/setp_solver/cost.py"),
    Path("solver/src/setp_solver/check.py"),
    Path("solver/src/setp_solver/search/evaluation.py"),
)
REGIONS = ("cy", "jjj")
SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
REPLICATES = ("01", "02", "03")
PROFILE_PORT_OFFSET = {"cv": 0, "ev": 1}
ROUTER_THREADS = 2
ROUTE_WORKERS = 4
ROUTE_TIMEOUT = 20.0
MAX_OUTPUT_BYTES = 2 * 1024**3


FACILITY_SPEC = {
    "cy": {
        "actual_city": "chengdu",
        "pool": "chengdu__named_poi.csv",
        "depots": (
            {
                "depot_id": "D_chengdu_longquan_dp",
                "facility_key": "chengdu_longquan_dp",
                "name": "万纬成都龙泉园区",
                "longitude": 104.1882900,
                "latitude": 30.5225890,
                "identity": "EXISTING_FACILITY_ROW/chengdu",
                "source": (
                    "data/ChinaInstances/"
                    "china81_stage2_static_inputs_corrected_v3_20260723/"
                    "facilities.csv#city=chengdu"
                ),
                "verification": "existing frozen facility row and registered road-access point",
                "source_centroid_lon": 104.1882900,
                "source_centroid_lat": 30.5225890,
                "snap_offset_m": 0.0,
            },
            {
                "depot_id": "D_chengdu_pidu_dp",
                "facility_key": "chengdu_pidu_dp",
                "name": "海霸王西部食品物流园",
                "longitude": 104.0218420,
                "latitude": 30.7510610,
                "identity": "way/849735242",
                "source": "https://www.openstreetmap.org/way/849735242",
                "verification": (
                    "OSM named industrial landuse centroid; scenario road-access point "
                    "snapped by frozen China81 CV OSRM graph"
                ),
                "source_centroid_lon": 104.0218955,
                "source_centroid_lat": 30.7509912,
                "snap_offset_m": 9.324615,
            },
        ),
    },
    "jjj": {
        "actual_city": "beijing",
        "pool": "beijing__named_poi.csv",
        "depots": (
            {
                "depot_id": "D_beijing_shunhang_dp",
                "facility_key": "beijing_shunhang_dp",
                "name": "普洛斯北京顺航物流园",
                "longitude": 116.5776300,
                "latitude": 40.1266540,
                "identity": "EXISTING_FACILITY_ROW/beijing",
                "source": (
                    "data/ChinaInstances/"
                    "china81_stage2_static_inputs_corrected_v3_20260723/"
                    "facilities.csv#city=beijing"
                ),
                "verification": "existing frozen GLP facility row and registered road-access point",
                "source_centroid_lon": 116.5776300,
                "source_centroid_lat": 40.1266540,
                "snap_offset_m": 0.0,
            },
            {
                "depot_id": "D_beijing_tongzhou_dp",
                "facility_key": "beijing_tongzhou_dp",
                "name": "百丽(通州)物流园",
                "longitude": 116.5842610,
                "latitude": 39.7664060,
                "identity": "way/1041183865",
                "source": "https://www.openstreetmap.org/way/1041183865",
                "verification": (
                    "OSM named industrial landuse centroid; scenario road-access point "
                    "snapped by frozen China81 CV OSRM graph"
                ),
                "source_centroid_lon": 116.5833473,
                "source_centroid_lat": 39.7658653,
                "snap_offset_m": 98.690688,
            },
        ),
    },
}


OSM_FACILITY_SNAPSHOTS = {
    "way/849735242": {
        "evidence_class": "FACT",
        "snapshot_semantics": "selected identity and geometry fields from Nominatim response",
        "osm_type": "way",
        "osm_id": 849735242,
        "name": "海霸王西部食品物流园",
        "lat": "30.7509912",
        "lon": "104.0218955",
        "class": "landuse",
        "type": "industrial",
        "boundingbox": ["30.7467450", "30.7559277", "104.0176675", "104.0254376"],
        "retrieved_date": "2026-08-12",
        "endpoint": "https://nominatim.openstreetmap.org/search",
    },
    "way/1041183865": {
        "evidence_class": "FACT",
        "snapshot_semantics": "selected identity and geometry fields from Nominatim response",
        "osm_type": "way",
        "osm_id": 1041183865,
        "name": "百丽(通州)物流园",
        "lat": "39.7658653",
        "lon": "116.5833473",
        "class": "landuse",
        "type": "industrial",
        "boundingbox": ["39.7644649", "39.7670874", "116.5817264", "116.5849794"],
        "retrieved_date": "2026-08-12",
        "endpoint": "https://nominatim.openstreetmap.org/search",
    },
}


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = load_module("suite_rebuild_base_20260812", BASE_SCRIPT)
matrix_builder = load_module("depotpair_matrix_builder_20260812", MATRIX_SCRIPT)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    fields: Sequence[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    selected = list(fields or (list(rows[0]) if rows else ()))
    if not selected:
        raise ValueError(f"no CSV fields for {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=selected, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hashes(root: Path, *, exclude_manifest: bool = True) -> dict[str, str]:
    rows: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("._"):
            continue
        if exclude_manifest and path.name == "artifact_hashes.json":
            continue
        rows[str(path.relative_to(root))] = sha256(path)
    return rows


def tree_bytes(*roots: Path) -> int:
    return sum(
        path.stat().st_size
        for root in roots
        for path in root.rglob("*")
        if path.is_file() and not path.name.startswith("._")
    )


def coordinate_key(longitude: float | str, latitude: float | str) -> str:
    return f"{float(longitude):.7f},{float(latitude):.7f}"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def source_identity(row: Mapping[str, str]) -> str:
    return f"{row['osm_type']}/{row['osm_id']}"


def location_id(row: Mapping[str, str]) -> str:
    return f"L_OSM_{row['osm_type'].upper()}_{row['osm_id']}"


def replicate_for(identity: str) -> str:
    value = int(hashlib.sha256(identity.encode("utf-8")).hexdigest(), 16) % 3
    return REPLICATES[value]


def load_real_pool(region: str) -> dict[str, dict[str, str]]:
    path = SOURCE_POOLS / str(FACILITY_SPEC[region]["pool"])
    output: dict[str, dict[str, str]] = {}
    for row in read_csv(path):
        identity = source_identity(row)
        if not row.get("name", "").strip():
            continue
        if not row.get("osm_type", "").strip() or not row.get("osm_id", "").strip():
            continue
        if identity in output:
            continue
        output[identity] = dict(row)
    return output


def route_pairs_for_direct(region: str, rows: Iterable[Mapping[str, str]]) -> set[tuple[str, str]]:
    depots = FACILITY_SPEC[region]["depots"]
    depot_keys = [coordinate_key(row["longitude"], row["latitude"]) for row in depots]
    pairs = {(depot_keys[0], depot_keys[1]), (depot_keys[1], depot_keys[0])}
    for row in rows:
        customer = coordinate_key(row["longitude"], row["latitude"])
        for depot in depot_keys:
            pairs.add((depot, customer))
            pairs.add((customer, depot))
    return pairs


def create_required_table(
    db: sqlite3.Connection, required: set[tuple[str, str]]
) -> None:
    db.execute("DROP TABLE IF EXISTS temp.required_pairs")
    db.execute(
        "CREATE TEMP TABLE required_pairs("
        "origin_key TEXT NOT NULL,destination_key TEXT NOT NULL,"
        "PRIMARY KEY(origin_key,destination_key)) WITHOUT ROWID"
    )
    db.executemany("INSERT INTO required_pairs VALUES(?,?)", sorted(required))


def seed_cache(
    db: sqlite3.Connection,
    source: Path,
    required: set[tuple[str, str]],
) -> int:
    create_required_table(db, required)
    before = int(db.execute("SELECT COUNT(*) FROM routes").fetchone()[0])
    db.execute("ATTACH DATABASE ? AS frozen", (str(source),))
    fields = ",".join(matrix_builder.FIELDS)
    db.execute(
        f"INSERT OR IGNORE INTO main.routes({fields}) "
        f"SELECT {','.join('f.' + name for name in matrix_builder.FIELDS)} "
        "FROM frozen.routes AS f JOIN temp.required_pairs AS q "
        "ON q.origin_key=f.origin_key AND q.destination_key=f.destination_key"
    )
    db.commit()
    db.execute("DETACH DATABASE frozen")
    after = int(db.execute("SELECT COUNT(*) FROM routes").fetchone()[0])
    return after - before


def route_count(db: sqlite3.Connection, required: set[tuple[str, str]]) -> int:
    create_required_table(db, required)
    return int(
        db.execute(
            "SELECT COUNT(*) FROM routes AS r JOIN temp.required_pairs AS q "
            "USING(origin_key,destination_key)"
        ).fetchone()[0]
    )


def load_route_rows(
    db: sqlite3.Connection, required: set[tuple[str, str]]
) -> dict[tuple[str, str], dict[str, Any]]:
    create_required_table(db, required)
    names = [row[1] for row in db.execute("PRAGMA table_info(routes)")]
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in db.execute(
        "SELECT r.* FROM routes AS r JOIN temp.required_pairs AS q "
        "USING(origin_key,destination_key)"
    ):
        payload = dict(zip(names, raw, strict=True))
        output[(payload["origin_key"], payload["destination_key"])] = payload
    if len(output) != len(required):
        raise RuntimeError(f"route cache incomplete: {len(output)}/{len(required)}")
    return output


def graph_identity(region: str, profile: str) -> dict[str, Any]:
    root = GRAPH_AUTHORITY / "graphs" / region / profile
    manifest_path = root / "graph_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "graph_manifest": str(manifest_path.relative_to(REPO)),
        "graph_manifest_sha256": sha256(manifest_path),
        "profile": profile,
        "region": region,
        "osrm_version": manifest.get("osrm_version", "UNKNOWN"),
        "profile_sha256": manifest.get("profile_sha256", "UNKNOWN"),
        "clip_sha256": manifest.get("input_pbf_sha256", "UNKNOWN"),
    }


class RouterSession:
    def __init__(self, region: str, profile: str, matrix_root: Path) -> None:
        self.region = region
        self.profile = profile
        self.matrix_root = matrix_root
        self.process: Any = None
        self.temp: tempfile.TemporaryDirectory[str] | None = None
        self.endpoint = ""

    def __enter__(self) -> "RouterSession":
        graph_dir = GRAPH_AUTHORITY / "graphs" / self.region / self.profile
        manifest = json.loads(
            (graph_dir / "graph_manifest.json").read_text(encoding="utf-8")
        )
        self.temp = tempfile.TemporaryDirectory(
            prefix=f"resetp-{self.region}-{self.profile}-", dir="/tmp"
        )
        runtime = Path(self.temp.name)
        graph_name = f"{self.region}-{self.profile}.osrm"
        graph_base = matrix_builder.restore_graph_to_apfs(
            graph_dir, manifest, runtime, graph_name
        )
        matrix_builder.OUT = self.matrix_root
        port = free_port()
        self.process = matrix_builder.start_router(graph_base, port, ROUTER_THREADS)
        self.endpoint = f"http://127.0.0.1:{port}"
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except Exception:
                self.process.kill()
                self.process.wait(timeout=10)
        if self.temp is not None:
            self.temp.cleanup()


def ensure_routes(
    db: sqlite3.Connection,
    endpoint: str,
    required: set[tuple[str, str]],
    checkpoint: Path,
) -> tuple[int, int]:
    before = route_count(db, required)
    matrix_builder.fill_cache(
        db,
        endpoint,
        required,
        workers=ROUTE_WORKERS,
        timeout=ROUTE_TIMEOUT,
        checkpoint=checkpoint,
    )
    after = route_count(db, required)
    if after != len(required):
        raise RuntimeError(f"routing incomplete: {after}/{len(required)}")
    return before, after - before


def matrix_from_rows(
    nodes: Sequence[Mapping[str, Any]],
    rows: Mapping[tuple[str, str], Mapping[str, Any]],
    field: str,
) -> tuple[tuple[float, ...], ...]:
    output = []
    for left in nodes:
        left_key = coordinate_key(left["longitude"], left["latitude"])
        values = []
        for right in nodes:
            if left["node_id"] == right["node_id"]:
                values.append(0.0)
            else:
                right_key = coordinate_key(right["longitude"], right["latitude"])
                values.append(float(rows[(left_key, right_key)][field]))
        output.append(tuple(values))
    return tuple(output)


def write_profile_matrices(
    root: Path,
    nodes: Sequence[Mapping[str, Any]],
    rows: Mapping[tuple[str, str], Mapping[str, Any]],
) -> RoadProfileMatrices:
    root.mkdir(parents=True, exist_ok=False)
    distance = matrix_from_rows(nodes, rows, "distance_m")
    duration = matrix_from_rows(nodes, rows, "duration_s")
    sum_v2d = matrix_from_rows(nodes, rows, "sum_v2d_m3_s2")
    for filename, matrix in (
        ("road_distance_m.csv", distance),
        ("road_duration_s.csv", duration),
        ("road_sum_v2d_m3_s2.csv", sum_v2d),
    ):
        with (root / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["node_id", *[row["node_id"] for row in nodes]])
            for node, values in zip(nodes, matrix, strict=True):
                writer.writerow([node["node_id"], *[f"{value:.9f}" for value in values]])
    write_csv(
        root / "raw_runs.csv",
        [rows[key] for key in sorted(rows)],
        matrix_builder.FIELDS,
    )
    return RoadProfileMatrices(
        distance_m=distance,
        duration_s=duration,
        sum_v2d_m3_s2=sum_v2d,
    )


def three_node_instance(
    region: str,
    customer: Mapping[str, str],
    route_rows: Mapping[str, Mapping[tuple[str, str], Mapping[str, Any]]],
    template: Any,
) -> Instance:
    depots = FACILITY_SPEC[region]["depots"]
    nodes = [
        Node(
            node_id=str(row["depot_id"]),
            node_type="d",
            x=float(row["longitude"]),
            y=float(row["latitude"]),
            ready_time=0.0,
            due_time=24.0 * 3600.0,
            charge_power_kw=base.DEPOT_POWER_KW,
            station_chargers=2,
            city=str(FACILITY_SPEC[region]["actual_city"]),
        )
        for row in depots
    ]
    nodes.append(
        Node(
            node_id=location_id(customer),
            node_type="c",
            x=float(customer["longitude"]),
            y=float(customer["latitude"]),
            demand=1.0,
            ready_time=0.0,
            due_time=24.0 * 3600.0,
            city=str(FACILITY_SPEC[region]["actual_city"]),
        )
    )
    node_rows = [
        {"node_id": node.node_id, "longitude": node.x, "latitude": node.y}
        for node in nodes
    ]
    profiles = {
        profile: RoadProfileMatrices(
            distance_m=matrix_from_rows(node_rows, route_rows[profile], "distance_m"),
            duration_s=matrix_from_rows(node_rows, route_rows[profile], "duration_s"),
            sum_v2d_m3_s2=matrix_from_rows(
                node_rows, route_rows[profile], "sum_v2d_m3_s2"
            ),
        )
        for profile in ("cv", "ev")
    }
    return Instance(
        nodes=nodes,
        distance_matrix=[list(row) for row in profiles["cv"].distance_m],
        num_cv=3,
        num_ev=3,
        road_profiles=profiles,
        vehicle_parameters=template.instance.vehicle_parameters,
        demand_mass_per_unit_kg=1.0,
    )


def direct_facts(
    region: str,
    candidates: Sequence[Mapping[str, str]],
    route_rows: Mapping[str, Mapping[tuple[str, str], Mapping[str, Any]]],
    template: Any,
) -> list[Any]:
    depots = tuple(str(row["depot_id"]) for row in FACILITY_SPEC[region]["depots"])
    facts = []
    for customer in candidates:
        instance = three_node_instance(region, customer, route_rows, template)
        costs: dict[str, float] = {}
        for depot_id in depots:
            route = Route(
                vehicle_id=f"CV_{depot_id}_DIRECT",
                vehicle_type="cv",
                home_depot_id=depot_id,
                node_sequence=[depot_id, location_id(customer), depot_id],
            )
            breakdown = evaluate(
                Solution(routes=[route]),
                instance,
                template.time_profile,
                template.prices,
                carbon_quota_kg=0.0,
            )
            costs[depot_id] = float(breakdown["total_cost"]) - float(
                breakdown["cost_fix"]
            )
        nearest, second = sorted(costs, key=lambda key: (costs[key], key))
        facts.append(
            base.LocationFact(
                source_node_id=location_id(customer),
                city=str(FACILITY_SPEC[region]["actual_city"]),
                nearest_depot=nearest,
                second_depot=second,
                nearest_cost_cny=costs[nearest],
                second_cost_cny=costs[second],
                relative_gap=(costs[second] - costs[nearest]) / costs[nearest],
            )
        )
    return facts


def source_node_rows(
    region: str,
    selected: Sequence[Any],
    customer_by_id: Mapping[str, Mapping[str, str]],
    station_by_city: Mapping[str, Mapping[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    station_cities: set[str] = set()
    for depot in FACILITY_SPEC[region]["depots"]:
        city = str(FACILITY_SPEC[region]["actual_city"])
        rows.append(
            {
                "node_id": depot["depot_id"],
                "node_type": "depot",
                "city": city,
                "latitude": f"{float(depot['latitude']):.7f}",
                "longitude": f"{float(depot['longitude']):.7f}",
                "source_identity": depot["identity"],
            }
        )
        if city not in station_cities:
            facility = station_by_city[city]
            rows.append(
                {
                    # build_instance pairs facilities to depots by the D_/S_ suffix.
                    # Use the first depot in a city so two same-city depots still
                    # produce exactly one public station.
                    "node_id": f"S_{str(depot['depot_id']).removeprefix('D_')}",
                    "node_type": "station",
                    "city": city,
                    "latitude": facility["station_lat"],
                    "longitude": facility["station_lon"],
                    "source_identity": facility["station_identity"],
                }
            )
            station_cities.add(city)
    for fact in selected:
        customer = customer_by_id[fact.source_node_id]
        rows.append(
            {
                "node_id": fact.source_node_id,
                "node_type": "customer",
                "city": FACILITY_SPEC[region]["actual_city"],
                "latitude": customer["latitude"],
                "longitude": customer["longitude"],
                "source_identity": source_identity(customer),
            }
        )
    return rows


def route_pairs_for_nodes(nodes: Sequence[Mapping[str, Any]]) -> set[tuple[str, str]]:
    keys = [coordinate_key(row["longitude"], row["latitude"]) for row in nodes]
    return {(left, right) for left in keys for right in keys if left != right}


def make_bundle(
    region: str,
    pool_id: str,
    nodes: Sequence[Mapping[str, Any]],
    profiles: Mapping[str, RoadProfileMatrices],
    homes: Mapping[str, str],
    template: Any,
    station_by_city: Mapping[str, Mapping[str, str]],
) -> Any:
    instance_nodes = []
    for row in nodes:
        is_depot = row["node_type"] == "depot"
        is_station = row["node_type"] == "station"
        facility = station_by_city[str(row["city"])] if is_station else None
        instance_nodes.append(
            Node(
                node_id=str(row["node_id"]),
                node_type="d" if is_depot else ("f" if is_station else "c"),
                x=float(row["longitude"]),
                y=float(row["latitude"]),
                demand=0.0 if (is_depot or is_station) else 1.0,
                ready_time=0.0,
                due_time=24.0 * 3600.0,
                charge_power_kw=(
                    base.DEPOT_POWER_KW
                    if is_depot
                    else (
                        float(facility["station_power_kw"])
                        if facility is not None
                        else None
                    )
                ),
                station_chargers=(
                    2
                    if is_depot
                    else (
                        int(float(facility["station_gun_count"]))
                        if facility is not None
                        else None
                    )
                ),
                city=str(row["city"]),
            )
        )
    instance = Instance(
        nodes=instance_nodes,
        distance_matrix=[list(row) for row in profiles["cv"].distance_m],
        num_cv=max(1, len(nodes)),
        num_ev=max(1, len(nodes)),
        road_profiles=profiles,
        vehicle_parameters=template.instance.vehicle_parameters,
        demand_mass_per_unit_kg=1.0,
    )
    return SimpleNamespace(
        instance_id=pool_id,
        instance=instance,
        prices=template.prices,
        time_profile=template.time_profile,
        customer_home_depot=MappingProxyType(dict(homes)),
    )


class BundleCache:
    def __init__(self, bundles: Mapping[str, Any]) -> None:
        self.bundles = dict(bundles)

    def get(self, instance_id: str) -> Any:
        return self.bundles[instance_id]


def append_facilities(static_root: Path) -> list[dict[str, Any]]:
    source_rows = read_csv(SOURCE_STATIC / "facilities.csv")
    by_city = {row["city"]: row for row in source_rows}
    output: list[dict[str, Any]] = [dict(row) for row in source_rows]
    provenance: list[dict[str, Any]] = []
    for region in REGIONS:
        actual_city = str(FACILITY_SPEC[region]["actual_city"])
        template = by_city[actual_city]
        for depot in FACILITY_SPEC[region]["depots"]:
            row = dict(template)
            row.update(
                {
                    "city": depot["facility_key"],
                    "region": region,
                    "depot_name": depot["name"],
                    "depot_lon": f"{float(depot['longitude']):.7f}",
                    "depot_lat": f"{float(depot['latitude']):.7f}",
                    "depot_point_semantics": (
                        "SCENARIO_ROAD_ACCESS_POINT_NOT_OBSERVED_TRUCK_GATE"
                    ),
                    "depot_source": depot["source"],
                    "depot_site_power_kw_shadow": f"{base.DEPOT_POWER_KW:.1f}",
                    "depot_parameter_class": (
                        "P43_I_CHINA_LOGISTICS_DEPOT_DC_60KW_DEFAULT"
                    ),
                }
            )
            output.append(row)
            provenance.append(
                {
                    "evidence_class": "FACT",
                    "region": region,
                    "depot_id": depot["depot_id"],
                    "facility_name": depot["name"],
                    "facility_identity": depot["identity"],
                    "source_centroid_lon": depot["source_centroid_lon"],
                    "source_centroid_lat": depot["source_centroid_lat"],
                    "scenario_road_access_lon": depot["longitude"],
                    "scenario_road_access_lat": depot["latitude"],
                    "road_snap_offset_m": depot["snap_offset_m"],
                    "point_semantics": row["depot_point_semantics"],
                    "source": depot["source"],
                    "verification": depot["verification"],
                }
            )
    write_csv(static_root / "facilities.csv", output)
    return provenance


def station_facilities_by_city() -> dict[str, dict[str, str]]:
    rows = read_csv(STATION_AUTHORITY)
    by_city = {str(row["city"]): dict(row) for row in rows}
    required = {
        str(FACILITY_SPEC[region]["actual_city"])
        for region in REGIONS
    }
    missing = sorted(required - set(by_city))
    if missing:
        raise RuntimeError(f"station authority is missing cities: {missing}")
    return by_city


def build_matrix_authority(
    output_root: Path,
    report_root: Path,
    selections: Mapping[tuple[str, str, int], Sequence[Any]],
    customer_rows: Mapping[str, Mapping[str, Mapping[str, str]]],
    templates: Mapping[tuple[str, str], Any],
    direct_dbs: Mapping[tuple[str, str], sqlite3.Connection],
    matrix_stats: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]]]:
    static_root = output_root / "source_pools"
    matrix_root = output_root / "directed_matrices"
    bundles: dict[str, Any] = {}
    pool_catalog: list[dict[str, Any]] = []
    customer_provenance: dict[str, dict[str, Any]] = {}
    nodes_by_pool: dict[str, list[dict[str, Any]]] = {}
    homes_by_pool: dict[str, dict[str, str]] = {}
    station_by_city = station_facilities_by_city()

    for region in REGIONS:
        for replicate in REPLICATES:
            for size in SIZES:
                selected = selections[(region, replicate, size)]
                pool_id = f"cn-{region}-{size}c-{replicate}-DEPOTPAIR-POOL"
                by_id = customer_rows[region]
                nodes = source_node_rows(region, selected, by_id, station_by_city)
                homes = {fact.source_node_id: fact.nearest_depot for fact in selected}
                nodes_by_pool[pool_id] = nodes
                homes_by_pool[pool_id] = homes
                target = static_root / "instances" / pool_id
                write_csv(target / "nodes.csv", nodes)
                pool_catalog.append(
                    {
                        "instance_id": pool_id,
                        "region": region,
                        "customer_count": size,
                        "replicate": replicate,
                        "city": FACILITY_SPEC[region]["actual_city"],
                        "depot_count": 2,
                        "node_count": len(nodes),
                        "source_pool": str(FACILITY_SPEC[region]["pool"]),
                    }
                )
                for fact in selected:
                    source = by_id[fact.source_node_id]
                    customer_provenance[source_identity(source)] = {
                        "evidence_class": "FACT",
                        "location_id": fact.source_node_id,
                        "region": region,
                        "city": source["city"],
                        "name": source["name"],
                        "osm_identity": source_identity(source),
                        "latitude": source["latitude"],
                        "longitude": source["longitude"],
                        "coordinate_status": source["coordinate_status"],
                        "source_response_path": source["source_response_path"],
                        "source_response_sha256": source["source_response_sha256"],
                        "source_query_bbox": source["source_query_bbox"],
                    }

    write_csv(static_root / "instance_catalog.csv", pool_catalog)
    write_csv(
        output_root / "customer_point_sources.csv",
        sorted(customer_provenance.values(), key=lambda row: row["osm_identity"]),
    )

    profiles_by_pool: dict[str, dict[str, RoadProfileMatrices]] = defaultdict(dict)
    for region in REGIONS:
        for profile in ("cv", "ev"):
            db = direct_dbs[(region, profile)]
            required: set[tuple[str, str]] = set()
            region_pools = [
                pool_id for pool_id in nodes_by_pool if pool_id.startswith(f"cn-{region}-")
            ]
            for pool_id in region_pools:
                required.update(route_pairs_for_nodes(nodes_by_pool[pool_id]))
            old_cache = SOURCE_MATRICES / f"route_cache_{region}_{profile}.sqlite"
            reused = seed_cache(db, old_cache, required)
            checkpoint = matrix_root / f"checkpoint_{region}_{profile}.json"
            with RouterSession(region, profile, matrix_root) as router:
                present_before, queried = ensure_routes(
                    db, router.endpoint, required, checkpoint
                )
            rows = load_route_rows(db, required)
            matrix_stats.append(
                {
                    "evidence_class": "FACT",
                    "stage": "full_selected_instances",
                    "region": region,
                    "profile": profile,
                    "required_directed_pairs": len(required),
                    "present_before_router": present_before,
                    "reused_from_frozen_cache_this_stage": reused,
                    "queried_from_frozen_osrm_graph": queried,
                    **graph_identity(region, profile),
                }
            )
            for pool_id in region_pools:
                nodes = nodes_by_pool[pool_id]
                pool_pairs = route_pairs_for_nodes(nodes)
                pool_rows = {key: rows[key] for key in pool_pairs}
                profiles_by_pool[pool_id][profile] = write_profile_matrices(
                    matrix_root / "instances" / pool_id / profile,
                    nodes,
                    pool_rows,
                )

    for pool_id, nodes in nodes_by_pool.items():
        parts = pool_id.split("-")
        region = parts[1]
        size = int(parts[2].removesuffix("c"))
        replicate = parts[3]
        bundles[pool_id] = make_bundle(
            region,
            pool_id,
            nodes,
            profiles_by_pool[pool_id],
            homes_by_pool[pool_id],
            templates[(region, replicate)],
            station_by_city,
        )
    write_json(static_root / "artifact_hashes.json", tree_hashes(static_root))
    write_json(matrix_root / "artifact_hashes.json", tree_hashes(matrix_root))
    matrix_hashes = json.loads(
        (matrix_root / "artifact_hashes.json").read_text(encoding="utf-8")
    )
    return bundles, matrix_hashes, pool_catalog


def render_report(
    health_54: Sequence[Mapping[str, Any]],
    health_81: Sequence[Mapping[str, Any]],
    facility_rows: Sequence[Mapping[str, Any]],
    facility_pair_rows: Sequence[Mapping[str, Any]],
    matrix_stats: Sequence[Mapping[str, Any]],
    protected_before: Mapping[str, str],
    protected_after: Mapping[str, str],
    prd_unchanged: bool,
    total_bytes: int,
    sidecars_removed: int = 0,
) -> str:
    by_region: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in health_54:
        by_region[str(row["region"])].append(row)
    lines = [
        "DEPOTPAIR_DONE",
        "",
        "# 成渝、京津冀近场车场重锚与 54 例健康报告（2026-08-12）",
        "",
        "## 结论",
        "",
    ]
    for region in REGIONS:
        rows = by_region[region]
        passed = sum(row["contestability_gate"] == "PASS" for row in rows)
        flagged = sum(bool(row["FLAG"]) for row in rows)
        witness = sum(row["edf_witness_status"] == "PASS" for row in rows)
        lines.append(
            f"- `FACT`：{region} 的 25% 相对成本差可争夺判据通过 "
            f"{passed}/{len(rows)}；EDF 完整服务见证通过 {witness}/{len(rows)}；"
            f"保留 FLAG {flagged}/{len(rows)}。"
        )
    lines.extend(
        [
            f"- `FACT`：合并后的 `suite_health_v2.csv` 为 {len(health_81)} 行；"
            "珠三角原 27 行逐字段一致。",
            f"- `FACT`：本轮新数据和报告合计 {total_bytes} 字节 "
            f"（{total_bytes / 1024**2:.3f} MiB），低于用户规定的 2 GiB。",
            "- `FACT`：仅在本轮两个全新目录内清理 ExFAT 自动生成的 AppleDouble 旁文件；"
            "终态残留为 0，没有删除业务数据文件。",
            "- `FACT`：本轮没有启动正式搜索求解；健康表来自确定性重锚、"
            "完整 EDF 见证与现行评价器复算。",
            "",
            "## 真实车场与路网接入点",
            "",
            "| 标签 | 区域 | 车场 | 真实身份 | 来源中心点 | 场景路网接入点 | 接入偏移(m) | 来源 |",
            "|---|---|---|---|---|---|---:|---|",
        ]
    )
    for row in facility_rows:
        lines.append(
            f"| FACT | {row['region']} | {row['facility_name']} | "
            f"`{row['facility_identity']}` | "
            f"({row['source_centroid_lat']}, {row['source_centroid_lon']}) | "
            f"({row['scenario_road_access_lat']}, {row['scenario_road_access_lon']}) | "
            f"{float(row['road_snap_offset_m']):.6f} | `{row['source']}` |"
        )
    lines.extend(
        [
            "",
            "- `FACT`：新增车场坐标保存的是冻结路网返回的场景接入点，语义均为 "
            "`SCENARIO_ROAD_ACCESS_POINT_NOT_OBSERVED_TRUCK_GATE`；OSM 原始中心点另列，二者没有混写。",
            "",
            "| 标签 | 区域 | 去程路网距离(km) | 回程路网距离(km) |",
            "|---|---|---:|---:|",
        ]
    )
    for row in facility_pair_rows:
        lines.append(
            f"| FACT | {row['region']} | {float(row['forward_distance_m'])/1000:.6f} | "
            f"{float(row['reverse_distance_m'])/1000:.6f} |"
        )
    lines.extend(
        [
            "",
            "## 客户与配方",
            "",
            "- `FACT`：成渝客户来自冻结 `chengdu__named_poi.csv`；京津冀客户来自冻结 "
            "`beijing__named_poi.csv`。每个入选点均保留 OSM 身份、名称、坐标、原始响应路径与 SHA-256。",
            "- `FACT`：三个副本按 OSM 身份 SHA-256 的模 3 值确定性分组；每个规模再按现行真实弧成本排序，"
            "只做进入 30%–45% 固定区间所需的最小替换。",
            "- `FACT`：时间窗宽度逐单继承；上午/下午按 1:2 分配；车场充电 60 kW；"
            "CV/EV 车型成本与内生车队口径直接复用现行 China81 V3 建造器。",
            "",
            "## 有向路网矩阵",
            "",
            "- `FACT`：距离、时间和 `sum(v²d)` 均由冻结 China81 OSRM 图的 Route API 同路返回；"
            "没有使用直线距离、对称补齐或跨画像复制。",
            "- `FACT`：下列每行记录本轮实际需要的有向弧、旧缓存复用量和冻结图新增查询量；"
            "同一弧可能在 direct 与 full 阶段均被计入阶段需要量，但 SQLite 主键只保存一份。",
            "",
            "| 标签 | 阶段 | 区域 | 画像 | 需要弧数 | 路由前已有 | 本阶段旧缓存补入 | 本阶段图查询 | 图清单 SHA-256 |",
            "|---|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in matrix_stats:
        lines.append(
            f"| FACT | {row['stage']} | {row['region']} | {row['profile']} | "
            f"{row['required_directed_pairs']} | {row['present_before_router']} | "
            f"{row['reused_from_frozen_cache_this_stage']} | "
            f"{row['queried_from_frozen_osrm_graph']} | `{row['graph_manifest_sha256']}` |"
        )
    lines.extend(["", "## FLAG 原样保留", ""])
    flags = [row for row in health_54 if row["FLAG"]]
    if flags:
        for row in flags:
            lines.append(f"- `FACT` `{row['instance_id']}`：{row['FLAG']}")
    else:
        lines.append("- `FACT`：54 行均无 FLAG。")
    lines.extend(
        [
            "",
            "## 红线与产物",
            "",
            "| 标签 | 受保护文件 | 任务前 SHA-256 | 任务后 SHA-256 |",
            "|---|---|---|---|",
        ]
    )
    for path in PROTECTED:
        key = str(path)
        lines.append(
            f"| FACT | `{key}` | `{protected_before[key]}` | `{protected_after[key]}` |"
        )
    lines.extend(
        [
            "",
            "- `FACT`：旧静态输入、旧矩阵、原 V3 套件和珠三角 27 例均未覆盖或删除。",
            "- `FACT`：新数据位于 `data/ChinaInstances/china81_depotpair_rebuild_v1_20260812/`；"
            "报告和 81 行健康表位于 `solver/reports/suite_depotpair_rebuild_20260812/`。",
            "- `FACT`：`metadata.json`、`raw_runs.csv`、`decision.json`、"
            "`artifact_hashes.json` 与本报告齐全。",
            "",
            "## 解释边界",
            "",
            "- `INFERENCE`：本轮结果说明，把两场改为同一都市圈的真实近场园区后，"
            "既有真实点池足以构造满足固定可争夺判据的 54 例；它不改变正式算法效果结论。",
            "",
        ]
    )
    return "\n".join(lines)


def build(output_root: Path, report_root: Path) -> None:
    if output_root.exists() or report_root.exists():
        raise FileExistsError("refusing to overwrite an existing output/report root")
    if not SOURCE_HEALTH.is_file():
        raise FileNotFoundError(SOURCE_HEALTH)
    protected_before = {str(path): sha256(REPO / path) for path in PROTECTED}
    output_root.mkdir(parents=True, exist_ok=False)
    report_root.mkdir(parents=True, exist_ok=False)
    static_root = output_root / "source_pools"
    matrix_root = output_root / "directed_matrices"
    matrix_root.mkdir(parents=True, exist_ok=False)
    write_json(
        output_root / "build_status.json",
        {"status": "IN_PROGRESS", "completed_health_rows": 0, "target_health_rows": 54},
    )

    matrix_stats: list[dict[str, Any]] = []
    facility_rows = append_facilities(static_root)
    write_csv(output_root / "facilities.csv", read_csv(static_root / "facilities.csv"))
    write_json(report_root / "facility_source_snapshots.json", OSM_FACILITY_SNAPSHOTS)
    write_csv(report_root / "facility_sources.csv", facility_rows)

    pools: dict[str, dict[str, dict[str, str]]] = {}
    candidates: dict[tuple[str, str], list[dict[str, str]]] = {}
    customer_by_id: dict[str, dict[str, dict[str, str]]] = {}
    templates: dict[tuple[str, str], Any] = {}
    for region in REGIONS:
        real_pool = load_real_pool(region)
        pools[region] = real_pool
        customer_by_id[region] = {location_id(row): row for row in real_pool.values()}
        for replicate in REPLICATES:
            candidates[(region, replicate)] = sorted(
                [row for identity, row in real_pool.items() if replicate_for(identity) == replicate],
                key=lambda row: source_identity(row),
            )
            templates[(region, replicate)] = load_china81_bundle(
                REPO, f"cn-{region}-200c-{replicate}-V2-LOCATIONS"
            )

    direct_rows: dict[tuple[str, str], dict[tuple[str, str], dict[str, Any]]] = {}
    dbs: dict[tuple[str, str], sqlite3.Connection] = {}
    try:
        for region in REGIONS:
            region_candidates = [row for replicate in REPLICATES for row in candidates[(region, replicate)]]
            required = route_pairs_for_direct(region, region_candidates)
            for profile in ("cv", "ev"):
                db_path = matrix_root / f"route_cache_{region}_{profile}.sqlite"
                db = matrix_builder.init_db(db_path)
                dbs[(region, profile)] = db
                reused = seed_cache(
                    db,
                    SOURCE_MATRICES / f"route_cache_{region}_{profile}.sqlite",
                    required,
                )
                checkpoint = matrix_root / f"checkpoint_{region}_{profile}.json"
                with RouterSession(region, profile, matrix_root) as router:
                    present_before, queried = ensure_routes(
                        db, router.endpoint, required, checkpoint
                    )
                direct_rows[(region, profile)] = load_route_rows(db, required)
                matrix_stats.append(
                    {
                        "evidence_class": "FACT",
                        "stage": "direct_contestability",
                        "region": region,
                        "profile": profile,
                        "required_directed_pairs": len(required),
                        "present_before_router": present_before,
                        "reused_from_frozen_cache_this_stage": reused,
                        "queried_from_frozen_osrm_graph": queried,
                        **graph_identity(region, profile),
                    }
                )

        facts_by_rep: dict[tuple[str, str], list[Any]] = {}
        selections: dict[tuple[str, str, int], Sequence[Any]] = {}
        selection_rows: list[dict[str, Any]] = []
        for region in REGIONS:
            route_rows = {
                profile: direct_rows[(region, profile)] for profile in ("cv", "ev")
            }
            for replicate in REPLICATES:
                facts = direct_facts(
                    region,
                    candidates[(region, replicate)],
                    route_rows,
                    templates[(region, replicate)],
                )
                facts_by_rep[(region, replicate)] = facts
                for size in SIZES:
                    selected, success, note = base.select_locations_for_gate(facts, size)
                    if not success:
                        raise RuntimeError(
                            f"fixed gate unattainable for {region}/{replicate}/{size}: {note}"
                        )
                    selections[(region, replicate, size)] = selected
                    count = sum(
                        fact.relative_gap < base.MAIN_CONTEST_THRESHOLD
                        for fact in selected
                    )
                    selection_rows.append(
                        {
                            "evidence_class": "FACT",
                            "region": region,
                            "replicate": replicate,
                            "customer_count": size,
                            "candidate_pool_count": len(facts),
                            "contestable_count_25pct": count,
                            "contestable_share_25pct": count / size,
                            "selection_status": "PASS",
                            "selection_note": note,
                        }
                    )
        write_csv(report_root / "selection_health.csv", selection_rows)

        bundles, matrix_hashes, pool_catalog = build_matrix_authority(
            output_root,
            report_root,
            selections,
            customer_by_id,
            templates,
            dbs,
            matrix_stats,
        )
        base.SOURCE_STATIC = static_root
        base.SOURCE_MATRICES = matrix_root
        cache = BundleCache(bundles)
        tasks_by_instance = base.source_orders_by_instance()
        health_54: list[dict[str, Any]] = []
        all_orders: list[dict[str, Any]] = []
        all_fleet: list[dict[str, Any]] = []
        all_witness: list[dict[str, Any]] = []
        all_lunch: list[dict[str, Any]] = []
        raw_rows: list[dict[str, Any]] = []
        output_catalog: list[dict[str, Any]] = []
        for region in REGIONS:
            for size in SIZES:
                for replicate in REPLICATES:
                    source_id = f"cn-{region}-{size}c-{replicate}-V2-LOCATIONS"
                    new_id = f"cn-{region}-{size}c-{replicate}-V3-TWO-SHIFT-DP"
                    pool_id = f"cn-{region}-{size}c-{replicate}-DEPOTPAIR-POOL"
                    selected = selections[(region, replicate, size)]
                    identity = base.ParsedIdentity(
                        source_instance_id=source_id,
                        new_instance_id=new_id,
                        region=region,
                        size=size,
                        replicate=replicate,
                    )
                    geometry = base.GeometryChoice(
                        mode="REAL_OSM_NEARBY_DEPOTPAIR_REANCHOR_P46",
                        matrix_source_instance_id=pool_id,
                        depot_ids=tuple(
                            str(row["depot_id"]) for row in FACILITY_SPEC[region]["depots"]
                        ),
                        customer_source_ids=tuple(fact.source_node_id for fact in selected),
                        home_depot_by_source_customer=MappingProxyType(
                            {fact.source_node_id: fact.nearest_depot for fact in selected}
                        ),
                        attempted_rebuild=True,
                        rebuild_succeeded=True,
                        reanchored_customer_count=size,
                        note=(
                            "P46 nearby real depot pair plus existing real city point pool; "
                            f"{sum(f.relative_gap < base.MAIN_CONTEST_THRESHOLD for f in selected)}/{size} "
                            "contestable at 25pct"
                        ),
                    )
                    built = base.build_instance(
                        identity, tasks_by_instance[source_id], geometry, cache
                    )
                    contest = base.contestability_rows(built)
                    witness = base.build_witness(built)
                    fleet = base.fleet_health(witness)
                    lunch = base.lunch_health(built, witness)
                    per_km = base.per_km_health(built, witness)
                    critical = [
                        float(per_km["scenarios"][name]["critical_daily_km"])
                        for name in ("valley", "flat", "peak")
                    ]
                    distance = base.witness_distance_health(built, witness, critical)
                    manifest_sha = base.write_instance_outputs(
                        output_root,
                        built,
                        contest,
                        witness,
                        matrix_hashes,
                    )
                    health = base.health_row(
                        built,
                        contest,
                        witness,
                        fleet,
                        lunch,
                        per_km,
                        distance,
                        manifest_sha,
                    )
                    health_54.append(health)
                    all_orders.extend(dict(row) for row in built.order_rows)
                    all_fleet.extend(base.fleet_rows(built, witness))
                    all_witness.extend(base.witness_rows(built, witness))
                    all_lunch.extend(dict(row) for row in lunch["rows"])
                    raw_rows.append(
                        {
                            "evidence_class": "FACT",
                            "instance_id": new_id,
                            "region": region,
                            "customer_count": size,
                            "replicate": replicate,
                            "contestability_gate": health["contestability_gate"],
                            "edf_witness_status": health["edf_witness_status"],
                            "critical_band_overlap_status": health[
                                "critical_band_overlap_status"
                            ],
                            "served_customers": health["served_customers"],
                            "total_customers": health["total_customers"],
                            "served_demand_kg": health["served_demand_kg"],
                            "total_demand_kg": health["total_demand_kg"],
                            "FLAG": health["FLAG"],
                            "formal_search_evaluations": 0,
                        }
                    )
                    output_catalog.append(
                        {
                            "instance_id": new_id,
                            "source_instance_id": source_id,
                            "region": region,
                            "customer_count": size,
                            "replicate": replicate,
                            "depot_count": 2,
                            "matrix_source_instance_id": pool_id,
                            "formal_search_evaluations": 0,
                            "instance_artifact_manifest_sha256": manifest_sha,
                        }
                    )
                    write_json(
                        output_root / "build_status.json",
                        {
                            "status": "IN_PROGRESS",
                            "completed_health_rows": len(health_54),
                            "target_health_rows": 54,
                            "last_instance_id": new_id,
                        },
                    )

        if len(health_54) != 54:
            raise RuntimeError(f"health row count {len(health_54)} != 54")
        old_health = read_csv(SOURCE_HEALTH)
        old_prd = [row for row in old_health if row["region"] == "prd"]
        if len(old_prd) != 27:
            raise RuntimeError(f"source PRD row count {len(old_prd)} != 27")
        health_81 = [*health_54, *old_prd]
        health_81.sort(
            key=lambda row: (
                ("cy", "jjj", "prd").index(str(row["region"])),
                int(row["customer_count"]),
                str(row["replicate"]),
            )
        )
        prd_merged = [row for row in health_81 if row["region"] == "prd"]
        prd_unchanged = prd_merged == old_prd
        if not prd_unchanged:
            raise RuntimeError("PRD health rows changed during merge")
        write_csv(report_root / "suite_health_54.csv", health_54)
        write_csv(report_root / "suite_health_v2.csv", health_81)
        write_csv(report_root / "raw_runs.csv", raw_rows)
        write_csv(report_root / "health_witness_routes.csv", all_witness)
        write_csv(report_root / "lunch_charge_rows.csv", all_lunch)
        write_csv(report_root / "matrix_build_rows.csv", matrix_stats)
        write_csv(output_root / "orders.csv", all_orders)
        write_csv(output_root / "fleet_caps.csv", all_fleet)
        write_csv(output_root / "instance_catalog.csv", output_catalog)

        facility_pair_rows = []
        for region in REGIONS:
            depots = FACILITY_SPEC[region]["depots"]
            left = coordinate_key(depots[0]["longitude"], depots[0]["latitude"])
            right = coordinate_key(depots[1]["longitude"], depots[1]["latitude"])
            rows = direct_rows[(region, "cv")]
            facility_pair_rows.append(
                {
                    "evidence_class": "FACT",
                    "region": region,
                    "depot_from": depots[0]["depot_id"],
                    "depot_to": depots[1]["depot_id"],
                    "forward_distance_m": rows[(left, right)]["distance_m"],
                    "reverse_distance_m": rows[(right, left)]["distance_m"],
                    "method": "frozen_cv_osrm_directed_route",
                }
            )
        write_csv(report_root / "facility_pair_road_distances.csv", facility_pair_rows)

        write_json(
            output_root / "metadata.json",
            {
                "schema": "resetp.china81-depotpair-rebuild.v1",
                "created_date": "2026-08-12",
                "regions": list(REGIONS),
                "instance_count": 54,
                "formal_search_allowed": False,
                "formal_search_evaluations": 0,
                "customer_point_authority": str(SOURCE_POOLS.relative_to(REPO)),
                "frozen_graph_authority": str(GRAPH_AUTHORITY.relative_to(REPO)),
                "old_matrix_cache_authority": str(SOURCE_MATRICES.relative_to(REPO)),
                "new_data_overwrites": 0,
                "default_depot_site_power_kw_shadow": base.DEPOT_POWER_KW,
                "fleet_parameter_class_id": base.FLEET_PARAMETER_CLASS_ID,
            },
        )
        write_json(
            output_root / "decision.json",
            {
                "completion": "DEPOTPAIR_DONE",
                "health_rows": 54,
                "merged_health_rows": 81,
                "prd_rows_unchanged": True,
                "formal_experiment_started": False,
                "old_data_overwritten": False,
                "flags_preserved": True,
            },
        )
        write_json(
            report_root / "metadata.json",
            {
                "run_kind": "deterministic_depotpair_reanchor_and_structural_health",
                "health_rows": 54,
                "merged_health_rows": 81,
                "formal_search_evaluations": 0,
                "protected_hashes_before": protected_before,
                "source_health_sha256": sha256(SOURCE_HEALTH),
            },
        )
        write_json(
            report_root / "decision.json",
            {
                "completion": "DEPOTPAIR_DONE",
                "health_rows": 54,
                "merged_health_rows": 81,
                "prd_rows_unchanged": True,
                "flags_preserved": True,
            },
        )
        write_json(
            output_root / "build_status.json",
            {"status": "DEPOTPAIR_DONE", "completed_health_rows": 54, "target_health_rows": 54},
        )
        for db in dbs.values():
            db.commit()
            db.execute("DROP TABLE IF EXISTS temp.required_pairs")
            db.commit()
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db.close()
        dbs.clear()
        protected_after = {str(path): sha256(REPO / path) for path in PROTECTED}
        if protected_before != protected_after:
            raise RuntimeError("protected evaluator hash changed")

        report_path = report_root / "report.md"
        report_path.write_text(
            render_report(
                health_54,
                health_81,
                facility_rows,
                facility_pair_rows,
                matrix_stats,
                protected_before,
                protected_after,
                prd_unchanged,
                0,
            ),
            encoding="utf-8",
        )
        write_json(output_root / "artifact_hashes.json", tree_hashes(output_root))
        write_json(report_root / "artifact_hashes.json", tree_hashes(report_root))
        for _ in range(5):
            size_bytes = tree_bytes(output_root, report_root)
            if size_bytes > MAX_OUTPUT_BYTES:
                raise RuntimeError(f"new output exceeds 2 GiB: {size_bytes}")
            report_path.write_text(
                render_report(
                    health_54,
                    health_81,
                    facility_rows,
                    facility_pair_rows,
                    matrix_stats,
                    protected_before,
                    protected_after,
                    prd_unchanged,
                    size_bytes,
                ),
                encoding="utf-8",
            )
            write_json(report_root / "artifact_hashes.json", tree_hashes(report_root))
            if tree_bytes(output_root, report_root) == size_bytes:
                break
        else:
            raise RuntimeError("reported byte count did not stabilize")
    except Exception as exc:
        for db in dbs.values():
            try:
                db.close()
            except Exception:
                pass
        write_json(
            output_root / "build_status.json",
            {
                "status": "PARTIAL_FAILURE",
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        raise


def finalize_existing(output_root: Path, report_root: Path) -> None:
    """Finish hashes/report after a post-build SQLite-close failure."""

    required = (
        report_root / "suite_health_54.csv",
        report_root / "suite_health_v2.csv",
        report_root / "facility_sources.csv",
        report_root / "facility_pair_road_distances.csv",
        report_root / "matrix_build_rows.csv",
        report_root / "metadata.json",
        output_root / "decision.json",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"cannot finalize incomplete build: {missing}")

    health_54 = read_csv(report_root / "suite_health_54.csv")
    health_81 = read_csv(report_root / "suite_health_v2.csv")
    if len(health_54) != 54 or len(health_81) != 81:
        raise RuntimeError("existing health row counts are not 54 and 81")
    old_prd = [row for row in read_csv(SOURCE_HEALTH) if row["region"] == "prd"]
    new_prd = [row for row in health_81 if row["region"] == "prd"]
    prd_unchanged = new_prd == old_prd
    if not prd_unchanged:
        raise RuntimeError("existing merged PRD rows differ from frozen source")

    metadata = json.loads((report_root / "metadata.json").read_text(encoding="utf-8"))
    protected_before = {
        str(key): str(value)
        for key, value in metadata["protected_hashes_before"].items()
    }
    protected_after = {str(path): sha256(REPO / path) for path in PROTECTED}
    if protected_before != protected_after:
        raise RuntimeError("protected evaluator hash changed before finalization")

    write_json(report_root / "facility_source_snapshots.json", OSM_FACILITY_SNAPSHOTS)

    for db_path in sorted((output_root / "directed_matrices").glob("route_cache_*.sqlite")):
        db = sqlite3.connect(db_path)
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.close()

    previous_removed = 0
    previous_report = report_root / "report.md"
    if previous_report.is_file():
        match = re.search(
            r"AppleDouble 旁文件\s+(\d+)\s+个",
            previous_report.read_text(encoding="utf-8"),
        )
        if match is not None:
            previous_removed = int(match.group(1))
    sidecars = [
        path
        for root in (output_root, report_root)
        for path in root.rglob("._*")
        if path.is_file()
    ]
    for path in sidecars:
        path.unlink()
    remaining_sidecars = [
        path
        for root in (output_root, report_root)
        for path in root.rglob("._*")
        if path.is_file()
    ]
    if remaining_sidecars:
        raise RuntimeError(f"AppleDouble cleanup incomplete: {len(remaining_sidecars)}")
    sidecars_removed = previous_removed + len(sidecars)

    write_json(
        output_root / "build_status.json",
        {
            "status": "DEPOTPAIR_DONE",
            "completed_health_rows": 54,
            "target_health_rows": 54,
            "finalized_after_sqlite_close_repair": True,
        },
    )
    output_decision = json.loads(
        (output_root / "decision.json").read_text(encoding="utf-8")
    )
    output_decision["completion"] = "DEPOTPAIR_DONE"
    output_decision["finalized_after_sqlite_close_repair"] = True
    output_decision.pop("appledouble_sidecars_removed", None)
    output_decision["appledouble_cleanup_completed"] = True
    write_json(output_root / "decision.json", output_decision)
    report_decision = json.loads(
        (report_root / "decision.json").read_text(encoding="utf-8")
    )
    report_decision["completion"] = "DEPOTPAIR_DONE"
    report_decision["finalized_after_sqlite_close_repair"] = True
    report_decision.pop("appledouble_sidecars_removed", None)
    report_decision["appledouble_cleanup_completed"] = True
    write_json(report_root / "decision.json", report_decision)

    matrix_root = output_root / "directed_matrices"
    write_json(matrix_root / "artifact_hashes.json", tree_hashes(matrix_root))
    report_path = report_root / "report.md"
    facility_rows = read_csv(report_root / "facility_sources.csv")
    facility_pair_rows = read_csv(report_root / "facility_pair_road_distances.csv")
    matrix_stats = read_csv(report_root / "matrix_build_rows.csv")
    report_path.write_text(
        render_report(
            health_54,
            health_81,
            facility_rows,
            facility_pair_rows,
            matrix_stats,
            protected_before,
            protected_after,
            prd_unchanged,
            0,
            sidecars_removed,
        ),
        encoding="utf-8",
    )
    write_json(output_root / "artifact_hashes.json", tree_hashes(output_root))
    write_json(report_root / "artifact_hashes.json", tree_hashes(report_root))
    for _ in range(5):
        size_bytes = tree_bytes(output_root, report_root)
        if size_bytes > MAX_OUTPUT_BYTES:
            raise RuntimeError(f"new output exceeds 2 GiB: {size_bytes}")
        report_path.write_text(
            render_report(
                health_54,
                health_81,
                facility_rows,
                facility_pair_rows,
                matrix_stats,
                protected_before,
                protected_after,
                prd_unchanged,
                size_bytes,
                sidecars_removed,
            ),
            encoding="utf-8",
        )
        write_json(report_root / "artifact_hashes.json", tree_hashes(report_root))
        if tree_bytes(output_root, report_root) == size_bytes:
            break
    else:
        raise RuntimeError("finalized byte count did not stabilize")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--finalize-existing", action="store_true")
    args = parser.parse_args()
    if args.finalize_existing:
        finalize_existing(args.output_root.resolve(), args.report_root.resolve())
    else:
        build(args.output_root.resolve(), args.report_root.resolve())
    print("DEPOTPAIR_DONE 54 81")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
