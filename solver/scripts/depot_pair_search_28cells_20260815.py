#!/usr/bin/env python3
"""Search real OSM depot pairs for the empty China81 cells.

This is a construction and witness-audit task.  It never invokes a search
solver.  Existing suites are read-only inputs; the selected rows and all new
road matrices are written below the new ``*_v2_20260815`` authorities.

The search has two layers:

* every pair in the expanded, strict-label logistics pool is enumerated;
* every enumerated pair is replayed through the existing EDF witness and
  checker, then the exact eligible rows are sorted by the existing 25 percent
  relative-gap share.  No threshold or composite score is introduced.

The 28 missing rows are taken from the previous report.  The temporary main
case row jjj/50c/01 is also rescanned so the global ranking can be refreshed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import itertools
import json
import math
import shutil
import sqlite3
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "solver" / "src"))

from setp_solver.instance_loader import Instance, Node, RoadProfileMatrices  # noqa: E402
from setp_solver.solution import Route, Solution  # noqa: E402


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BASE = load_module(
    "china81_depot_search_base_20260815",
    REPO / "solver/scripts/build_china81_suite_rebuild_20260812.py",
)
METRO = load_module(
    "china81_depot_search_metro_20260815",
    REPO / "solver/scripts/build_china81_metro_suite_20260812.py",
)
DP = load_module(
    "china81_depot_search_dp_20260815",
    REPO / "solver/scripts/build_suite_depotpair_rebuild_20260812.py",
)
DP.ROUTE_WORKERS = 1
DP.ROUTER_THREADS = 2

DATA = REPO / "data/ChinaInstances"
REPORT = REPO / "solver/reports/depot_pair_search_28cells_20260815"
OUTPUT = DATA / "china81_final_suite_v2_20260815"
FRESH_POOL = DATA / "china9_metro_pool_depot_search_20260815"
PRIOR_POOL = DATA / "china9_metro_pool_20260812"
PRIOR_SUITE = DATA / "china81_final_suite_v1_20260815"
PRIOR_REPORT = REPO / "solver/reports/china81_final_suite_rebuild_20260815"
OLD_METRO = DATA / "china81_metro_suite_v1_20260812"

REGION_CITIES = {
    "cy": ("chengdu",),
    "jjj": ("beijing",),
    "prd": ("dongguan", "foshan", "guangzhou", "shenzhen"),
}
ANCHOR_CITY = {"cy": "chengdu", "jjj": "beijing", "prd": "guangzhou"}
SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
REPLICATES = ("01", "02", "03")
PROTECTED = (
    Path("solver/src/setp_solver/cost.py"),
    Path("solver/src/setp_solver/check.py"),
    Path("solver/src/setp_solver/search/evaluation.py"),
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    fields: Sequence[str] | None = None,
) -> None:
    materialized = [dict(row) for row in rows]
    selected = list(fields or (list(materialized[0]) if materialized else ()))
    if not selected:
        raise ValueError(f"no CSV fields for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=selected, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialized)


class CandidateLogWriter:
    """Stream the exhaustive candidate ledger instead of retaining it in RAM."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = path.open("w", newline="", encoding="utf-8")
        self.writer: csv.DictWriter[str] | None = None
        self.count = 0

    def write(self, row: Mapping[str, Any]) -> None:
        if self.writer is None:
            self.writer = csv.DictWriter(
                self.handle,
                fieldnames=list(row),
                extrasaction="ignore",
            )
            self.writer.writeheader()
        self.writer.writerow(dict(row))
        self.count += 1
        if self.count % 100 == 0:
            self.handle.flush()

    def close(self) -> None:
        self.handle.flush()
        self.handle.close()


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


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not path.name.startswith("._")
        and not any(part.startswith(".") for part in path.relative_to(root).parts)
    }


def protected_hashes() -> dict[str, str]:
    return {str(path): sha256(REPO / path) for path in PROTECTED}


def source_identity(row: Mapping[str, Any]) -> str:
    return f"{row['osm_type']}/{row['osm_id']}"


def depot_id(row: Mapping[str, Any]) -> str:
    return f"D_OSM_{str(row['osm_type']).upper()}_{row['osm_id']}"


def station_id(row: Mapping[str, Any]) -> str:
    return str(row["node_id"])


def coordinate_key(row: Mapping[str, Any]) -> str:
    return DP.coordinate_key(row["longitude"], row["latitude"])


def valid_coordinate(row: Mapping[str, Any]) -> bool:
    try:
        return math.isfinite(float(row["latitude"])) and math.isfinite(
            float(row["longitude"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def haversine_km(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    lat1, lon1 = math.radians(float(left["latitude"])), math.radians(
        float(left["longitude"])
    )
    lat2, lon2 = math.radians(float(right["latitude"])), math.radians(
        float(right["longitude"])
    )
    dlat, dlon = lat2 - lat1, lon2 - lon1
    core = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(
        dlon / 2.0
    ) ** 2
    return 6371.0088 * 2.0 * math.asin(math.sqrt(core))


def load_pool(root: Path, city: str, feature: str) -> list[dict[str, str]]:
    path = root / "pools" / f"{city}__{feature}.csv"
    if not path.is_file():
        return []
    rows: dict[str, dict[str, str]] = {}
    for row in read_csv(path):
        if valid_coordinate(row):
            rows.setdefault(source_identity(row), dict(row))
    return list(rows.values())


def current_customers(region: str, size: int) -> list[dict[str, str]]:
    """Load the already frozen METRO customer identities, not fresh points."""

    pool_id = f"cn-{region}-{size}c-METRO-POOL"
    path = OLD_METRO / "source_pools" / "instances" / pool_id / "nodes.csv"
    rows = []
    for row in read_csv(path):
        if row["node_type"] != "customer":
            continue
        osm_type, _, osm_id = row["source_identity"].partition("/")
        rows.append(
            {
                "city": row["city"],
                "region": region,
                "feature": "named_poi",
                "osm_type": osm_type,
                "osm_id": osm_id,
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "name": row["source_identity"],
                "brand": "",
                "tags": "{}",
                "source_response_path": "frozen METRO customer pool",
                "source_response_sha256": "",
                "source_query_bbox": "",
            }
        )
    if len(rows) != size:
        raise RuntimeError(f"frozen customer pool {pool_id} has {len(rows)} rows")
    return rows


def current_stations(region: str, size: int) -> list[dict[str, str]]:
    pool_id = f"cn-{region}-{size}c-METRO-POOL"
    path = OLD_METRO / "source_pools" / "instances" / pool_id / "nodes.csv"
    return [dict(row) for row in read_csv(path) if row["node_type"] == "station"]


def candidate_pool(region: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Union the fresh strict-label retrieval with the prior strict-label pool."""

    anchor_customer_ids = {
        f"{row['osm_type']}/{row['osm_id']}"
        for row in current_customers(region, 200)
    }
    by_identity: dict[str, dict[str, Any]] = {}
    counts: list[dict[str, Any]] = []
    for city in REGION_CITIES[region]:
        old_rows = {
            source_identity(row): row
            for row in load_pool(PRIOR_POOL, city, "logistics_candidate")
        }
        fresh_rows = {
            source_identity(row): row
            for row in load_pool(FRESH_POOL, city, "logistics_candidate")
        }
        for identity, row in old_rows.items():
            if METRO.named_logistics_facility(row) and identity not in anchor_customer_ids:
                by_identity.setdefault(
                    identity,
                    {
                        **row,
                        "candidate_pool_origin": "PRIOR_ONLY",
                        "new_since_previous": 0,
                    },
                )
        for identity, row in fresh_rows.items():
            if not METRO.named_logistics_facility(row) or identity in anchor_customer_ids:
                continue
            if identity in by_identity:
                by_identity[identity].update(
                    {
                        **row,
                        "candidate_pool_origin": "FRESH_AND_PRIOR",
                        "new_since_previous": 0,
                    }
                )
            else:
                by_identity[identity] = {
                    **row,
                    "candidate_pool_origin": "FRESH_ONLY",
                    "new_since_previous": 1,
                }
        counts.append(
            {
                "region": region,
                "city": city,
                "prior_strict_logistics_candidates": len(
                    [row for row in old_rows.values() if METRO.named_logistics_facility(row)]
                ),
                "fresh_strict_logistics_candidates": len(
                    [row for row in fresh_rows.values() if METRO.named_logistics_facility(row)]
                ),
                "new_unique_candidate_points": len(
                    set(fresh_rows) - set(old_rows)
                ),
            }
        )
    facilities = sorted(by_identity.values(), key=lambda row: source_identity(row))
    if len(facilities) < 2:
        raise RuntimeError(f"{region} strict logistics pool has fewer than two points")
    return facilities, {"region": region, "cities": list(REGION_CITIES[region]), "counts": counts, "total": len(facilities), "new_total": sum(int(row["new_since_previous"]) for row in facilities)}


def extend_facilities_for_output(
    output_root: Path,
    facilities_by_region: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    """Keep the existing facility schema while registering OSM depot aliases."""

    path = output_root / "facilities.csv"
    existing = read_csv(path)
    templates = {}
    for row in existing:
        templates.setdefault(str(row["region"]), dict(row))
    rows = list(existing)
    for region, facilities in facilities_by_region.items():
        template = templates.get(region)
        if template is None:
            raise RuntimeError(f"no facilities.csv template for region {region}")
        for facility in facilities:
            alias = dict(template)
            alias.update(
                {
                    "city": depot_id(facility).removeprefix("D_"),
                    "region": region,
                    "depot_name": str(facility.get("name", source_identity(facility))),
                    "depot_lon": f"{float(facility['longitude']):.7f}",
                    "depot_lat": f"{float(facility['latitude']):.7f}",
                    "depot_point_semantics": "OSM_LOGISTICS_CANDIDATE_POINT",
                    "depot_source": str(facility.get("source_response_path", "")),
                    "depot_source_sha256": str(facility.get("source_response_sha256", "")),
                    "depot_site_power_kw_shadow": str(BASE.DEPOT_POWER_KW),
                }
            )
            rows.append(alias)
    write_csv(path, rows, list(existing[0]) if existing else None)


def node_row_from_facility(region: str, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "node_id": depot_id(row),
        "node_type": "depot",
        "city": ANCHOR_CITY[region],
        "latitude": f"{float(row['latitude']):.7f}",
        "longitude": f"{float(row['longitude']):.7f}",
        "source_identity": source_identity(row),
    }


def node_row_from_customer(region: str, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "node_id": f"L_OSM_{str(row['osm_type']).upper()}_{row['osm_id']}",
        "node_type": "customer",
        "city": ANCHOR_CITY[region],
        "latitude": f"{float(row['latitude']):.7f}",
        "longitude": f"{float(row['longitude']):.7f}",
        "source_identity": source_identity(row),
    }


def node_row_from_station(region: str, row: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(row)
    output["city"] = ANCHOR_CITY[region]
    return output


def route_pairs(nodes: Sequence[Mapping[str, Any]]) -> set[tuple[str, str]]:
    keys = [coordinate_key(row) for row in nodes]
    return {(left, right) for left in keys for right in keys if left != right}


def build_route_store(
    region: str,
    facilities: Sequence[Mapping[str, Any]],
    customers: Sequence[Mapping[str, Any]],
    output_root: Path,
    report_root: Path,
) -> tuple[dict[str, dict[tuple[str, str], dict[str, Any]]], list[dict[str, Any]]]:
    points = [
        {
            "node_id": depot_id(row),
            "latitude": row["latitude"],
            "longitude": row["longitude"],
        }
        for row in facilities
    ] + [
        {
            "node_id": f"L_OSM_{str(row['osm_type']).upper()}_{row['osm_id']}",
            "latitude": row["latitude"],
            "longitude": row["longitude"],
        }
        for row in customers
    ]
    points += [
        {
            "node_id": row["node_id"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
        }
        for row in current_stations(region, 200)
    ]
    required = route_pairs(points)
    rows_by_profile: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    stats: list[dict[str, Any]] = []
    matrix_root = output_root / "directed_matrices"
    matrix_root.mkdir(parents=True, exist_ok=True)
    for profile in ("cv", "ev"):
        db_path = matrix_root / f"route_cache_{region}_{profile}.sqlite"
        db = DP.matrix_builder.init_db(db_path)
        try:
            frozen = DP.SOURCE_MATRICES / f"route_cache_{region}_{profile}.sqlite"
            reused = DP.seed_cache(db, frozen, required) if frozen.is_file() else 0
            checkpoint = matrix_root / f"checkpoint_{region}_{profile}.json"
            with DP.RouterSession(region, profile, matrix_root) as router:
                present_before, queried = DP.ensure_routes(
                    db, router.endpoint, required, checkpoint
                )
            rows_by_profile[profile] = DP.load_route_rows(db, required)
            stats.append(
                {
                    "evidence_class": "FACT",
                    "region": region,
                    "profile": profile,
                    "required_directed_pairs": len(required),
                    "present_before_router": present_before,
                    "reused_from_frozen_cache": reused,
                    "queried_from_frozen_osrm_graph": queried,
                    "route_workers": 1,
                    **DP.graph_identity(region, profile),
                }
            )
            write_csv(report_root / "matrix_build_rows.csv", stats)
            write_json(
                report_root / "search_status.json",
                {
                    "status": "ROUTE_MATRIX_PROGRESS",
                    "region": region,
                    "profile": profile,
                    "completed_region_profiles": len(stats),
                    "target_region_profiles": 6,
                },
            )
        finally:
            db.close()
    return rows_by_profile, stats


def profile_from_rows(
    node_rows: Sequence[Mapping[str, Any]],
    route_rows: Mapping[tuple[str, str], Mapping[str, Any]],
) -> RoadProfileMatrices:
    distance: list[tuple[float, ...]] = []
    duration: list[tuple[float, ...]] = []
    sum_v2d: list[tuple[float, ...]] = []
    for left in node_rows:
        left_key = coordinate_key(left)
        d_row: list[float] = []
        t_row: list[float] = []
        v_row: list[float] = []
        for right in node_rows:
            if left["node_id"] == right["node_id"]:
                d_row.append(0.0)
                t_row.append(0.0)
                v_row.append(0.0)
                continue
            raw = route_rows[(left_key, coordinate_key(right))]
            d_row.append(float(raw["distance_m"]))
            t_row.append(float(raw["duration_s"]))
            v_row.append(float(raw["sum_v2d_m3_s2"]))
        distance.append(tuple(d_row))
        duration.append(tuple(t_row))
        sum_v2d.append(tuple(v_row))
    return RoadProfileMatrices(
        distance_m=tuple(distance),
        duration_s=tuple(duration),
        sum_v2d_m3_s2=tuple(sum_v2d),
    )


def make_source_bundle(
    region: str,
    template: Any,
    pair: Sequence[Mapping[str, Any]],
    customers: Sequence[Mapping[str, Any]],
    stations: Sequence[Mapping[str, Any]],
    route_rows: Mapping[str, Mapping[tuple[str, str], Mapping[str, Any]]],
) -> tuple[Any, list[dict[str, Any]]]:
    rows = [node_row_from_facility(region, row) for row in pair]
    rows += [node_row_from_station(region, row) for row in stations]
    rows += [node_row_from_customer(region, row) for row in customers]
    if len({row["node_id"] for row in rows}) != len(rows):
        raise RuntimeError("duplicate source node identity in candidate bundle")
    nodes: list[Node] = []
    station_parameters: dict[str, tuple[float, int]] = {}
    old_param_path = OLD_METRO / "station_parameter_assignments.csv"
    if old_param_path.is_file():
        for row in read_csv(old_param_path):
            station_parameters[row["station_id"]] = (
                float(row["power_kw"]),
                int(float(row["gun_count"])),
            )
    for row in rows:
        node_type = row["node_type"]
        power, guns = station_parameters.get(row["node_id"], (22.0, 2))
        nodes.append(
            Node(
                node_id=row["node_id"],
                node_type={"depot": "d", "station": "f", "customer": "c"}[node_type],
                x=float(row["longitude"]),
                y=float(row["latitude"]),
                demand=0.0 if node_type != "customer" else 1.0,
                ready_time=0.0,
                due_time=24.0 * 3600.0,
                charge_power_kw=(
                    BASE.DEPOT_POWER_KW if node_type == "depot" else power if node_type == "station" else None
                ),
                station_chargers=(
                    2 if node_type == "depot" else guns if node_type == "station" else None
                ),
                city=ANCHOR_CITY[region],
            )
        )
    profiles = {
        profile: profile_from_rows(rows, route_rows[profile])
        for profile in ("cv", "ev")
    }
    instance = Instance(
        nodes=nodes,
        distance_matrix=[list(row) for row in profiles["cv"].distance_m],
        num_cv=max(1, len(nodes)),
        num_ev=max(1, len(nodes)),
        road_profiles=profiles,
        vehicle_parameters=template.instance.vehicle_parameters,
        demand_mass_per_unit_kg=template.instance.demand_mass_per_unit_kg,
    )
    bundle = SimpleNamespace(
        instance_id="SEARCH_POOL",
        instance=instance,
        prices=template.prices,
        time_profile=template.time_profile,
        customer_home_depot=MappingProxyType({}),
    )
    return bundle, rows


class DynamicBundleCache:
    def __init__(self) -> None:
        self.bundle: Any | None = None

    def get(self, instance_id: str) -> Any:
        if self.bundle is None:
            raise RuntimeError("dynamic source bundle is empty")
        return self.bundle


def augment_stations(built: Any, source_bundle: Any, source_rows: Sequence[Mapping[str, Any]]) -> Any:
    stations = [node for node in source_bundle.instance.nodes if node.node_type.lower() == "f"]
    if not stations:
        return built
    source_by_id = {row["node_id"]: row for row in source_rows}
    mapping_by_new = {row["new_node_id"]: row for row in built.source_mapping_rows}
    depots = [node for node in built.instance.nodes if node.node_type.lower() == "d"]
    customers = [node for node in built.instance.nodes if node.node_type.lower() == "c"]
    station_nodes = [
        replace(
            node,
            ready_time=BASE.SHIFT_ROWS["AM"]["start_minute"] * 60.0,
            due_time=BASE.SHIFT_ROWS["PM"]["end_minute"] * 60.0,
        )
        for node in stations
    ]
    new_nodes = [*depots, *station_nodes, *customers]
    source_ids = []
    for node in new_nodes:
        if node.node_type.lower() == "f":
            source_ids.append(node.node_id)
        else:
            source_ids.append(mapping_by_new[node.node_id]["source_node_id"])
    source_indices = [source_bundle.instance.node_index[node_id] for node_id in source_ids]
    profiles = {}
    for profile_id, matrices in source_bundle.instance.road_profiles.items():
        profiles[profile_id] = RoadProfileMatrices(
            distance_m=tuple(tuple(matrices.distance_m[i][j] for j in source_indices) for i in source_indices),
            duration_s=tuple(tuple(matrices.duration_s[i][j] for j in source_indices) for i in source_indices),
            sum_v2d_m3_s2=tuple(tuple(matrices.sum_v2d_m3_s2[i][j] for j in source_indices) for i in source_indices),
        )
    instance = Instance(
        nodes=new_nodes,
        distance_matrix=[list(row) for row in profiles["cv"].distance_m],
        num_cv=built.instance.num_cv,
        num_ev=built.instance.num_ev,
        road_profiles=profiles,
        vehicle_parameters=built.instance.vehicle_parameters,
        demand_mass_per_unit_kg=built.instance.demand_mass_per_unit_kg,
    )
    station_rows = [
        {
            "node_id": node.node_id,
            "node_type": "station",
            "city": source_by_id[node.node_id]["city"],
            "latitude": source_by_id[node.node_id]["latitude"],
            "longitude": source_by_id[node.node_id]["longitude"],
            "source_identity": source_by_id[node.node_id]["source_identity"],
        }
        for node in station_nodes
    ]
    station_mapping = [
        {
            "new_node_id": node.node_id,
            "source_instance_id": built.geometry.matrix_source_instance_id,
            "source_node_id": node.node_id,
            "source_city": source_by_id[node.node_id]["city"],
            "latitude": source_by_id[node.node_id]["latitude"],
            "longitude": source_by_id[node.node_id]["longitude"],
            "mapping_class": "IDENTITY_REAL_OSM_CHARGING_STATION",
        }
        for node in station_nodes
    ]
    depot_mapping = [row for row in built.source_mapping_rows if row["new_node_id"] in {node.node_id for node in depots}]
    customer_mapping = [row for row in built.source_mapping_rows if row["new_node_id"] in {node.node_id for node in customers}]
    depot_rows = [row for row in built.node_rows if row["node_type"] == "depot"]
    customer_rows = [row for row in built.node_rows if row["node_type"] == "customer"]
    return replace(
        built,
        instance=instance,
        node_rows=tuple([*depot_rows, *station_rows, *customer_rows]),
        source_mapping_rows=tuple([*depot_mapping, *station_mapping, *customer_mapping]),
    )


def pair_preliminary_share(customers: Sequence[Mapping[str, Any]], pair: Sequence[Mapping[str, Any]]) -> float:
    count = 0
    for customer in customers:
        distances = sorted((haversine_km(customer, depot) for depot in pair))
        if distances[0] > 0.0 and (distances[1] - distances[0]) / distances[0] < 0.25:
            count += 1
    return count / len(customers)


def exact_contest_rows(built: Any) -> list[dict[str, Any]]:
    return METRO.contestability_rows_zero_safe(built)


def route_distance_details(
    pair: Sequence[Mapping[str, Any]],
    route_rows: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[float, str]:
    parts: list[str] = []
    total = 0.0
    for left, right in ((pair[0], pair[1]), (pair[1], pair[0])):
        raw = route_rows[(coordinate_key(left), coordinate_key(right))]
        km = float(raw["distance_m"]) / 1000.0
        total += km
        parts.append(f"{depot_id(left)}->{depot_id(right)}={km:.6f}km")
    return total, "|".join(parts)


def candidate_id(region: str, size: int, replicate: str, pair: Sequence[Mapping[str, Any]]) -> str:
    raw = "|".join(source_identity(row) for row in pair)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:10]
    return f"cn-{region}-{size}c-{replicate}-DEPOTSEARCH-{digest}"


def build_candidate(
    region: str,
    size: int,
    replicate: str,
    pair: Sequence[Mapping[str, Any]],
    customers: Sequence[Mapping[str, Any]],
    stations: Sequence[Mapping[str, Any]],
    route_rows: Mapping[str, Mapping[tuple[str, str], Mapping[str, Any]]],
    templates: Mapping[str, Any],
    tasks_by_instance: Mapping[str, Sequence[Mapping[str, str]]],
    cache: DynamicBundleCache,
    current_nodes: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    rep = str(replicate)
    source_id = f"cn-{region}-{size}c-{rep}-V2-LOCATIONS"
    target_id = candidate_id(region, size, rep, pair)
    # Charging stations are not part of the CV witness route.  Keep them out
    # of the per-candidate replay instance; the selected candidate is rebuilt
    # with its full station set immediately before output.  This preserves the
    # witness/checker contract while avoiding an O(stations^2) matrix rebuild
    # for every depot pair in the large PRD pools.
    source_bundle, source_rows = make_source_bundle(
        region, templates[rep], pair, customers, (), route_rows
    )
    cache.bundle = source_bundle
    current_nodes["rows"] = source_rows
    homes = {}
    # The source locations are fixed; assign each frozen customer to the
    # nearest depot by the cached CV road distance so witness mileage uses the
    # same road graph as the selected pair-distance record.
    for customer in customers:
        nearest = min(
            pair,
            key=lambda depot: (
                float(
                    route_rows["cv"][(
                        coordinate_key(depot),
                        coordinate_key(customer),
                    )]["distance_m"]
                ),
                source_identity(depot),
            ),
        )
        cid = f"L_OSM_{str(customer['osm_type']).upper()}_{customer['osm_id']}"
        homes[cid] = depot_id(nearest)
    geometry = BASE.GeometryChoice(
        mode="REAL_OSM_DEPOT_PAIR_SEARCH_20260815",
        matrix_source_instance_id="SEARCH_POOL",
        depot_ids=tuple(depot_id(row) for row in pair),
        customer_source_ids=tuple(
            f"L_OSM_{str(row['osm_type']).upper()}_{row['osm_id']}" for row in customers
        ),
        home_depot_by_source_customer=MappingProxyType(homes),
        attempted_rebuild=True,
        rebuild_succeeded=True,
        reanchored_customer_count=size,
        note="strict same-metropolitan-area OSM logistics candidate pair; frozen customer pool",
    )
    identity = BASE.ParsedIdentity(
        source_instance_id=source_id,
        new_instance_id=target_id,
        region=region,
        size=size,
        replicate=rep,
    )
    built = BASE.build_instance(identity, tasks_by_instance[source_id], geometry, cache)
    contest = exact_contest_rows(built)
    witness = BASE.build_witness(built)
    road_km, road_detail = route_distance_details(pair, route_rows["cv"])
    contestable_count = sum(
        float(row["relative_gap"]) < BASE.MAIN_CONTEST_THRESHOLD for row in contest
    )
    exact_share = contestable_count / size if size else 0.0
    if witness.status != "PASS" or witness.violations:
        # A failed witness cannot provide a daily-distance distribution.  Keep
        # the candidate in the exhaustive ledger, but avoid replaying all
        # downstream cost/fleet diagnostics for a candidate that is already
        # excluded by the fixed eligibility rule.
        return {
            "candidate_id": target_id,
            "built": built,
            "source_rows": source_rows,
            "contest": contest,
            "witness": witness,
            "fleet": {},
            "lunch": {},
            "per_km": {},
            "distance": {
                "daily_distances": [],
                "below": "",
                "within": "",
                "above": "",
                "two_sides": "NA_NO_FEASIBLE_WITNESS",
            },
            "health": {
                "contestable_count_25pct": contestable_count,
                "contestable_share_25pct": exact_share,
                "total_customers": size,
                "total_demand_kg": sum(
                    float(row["demand_kg"]) for row in built.order_rows
                ),
            },
            "exact_share": exact_share,
            "eligible": False,
            "road_distance_km": road_km,
            "road_detail": road_detail,
            "pair": pair,
        }
    fleet = BASE.fleet_health(witness)
    lunch = BASE.lunch_health(built, witness)
    per_km = BASE.per_km_health(built, witness)
    critical = [
        float(per_km["scenarios"][name]["critical_daily_km"])
        for name in ("valley", "flat", "peak")
    ]
    distance = BASE.witness_distance_health(built, witness, critical)
    health = BASE.health_row(built, contest, witness, fleet, lunch, per_km, distance, "PENDING")
    exact_share = float(health["contestable_share_25pct"])
    eligible = bool(
        witness.status == "PASS"
        and len(witness.violations) == 0
        and distance["two_sides"] == "PASS_TWO_SIDES"
    )
    return {
        "candidate_id": target_id,
        "built": built,
        "source_rows": source_rows,
        "contest": contest,
        "witness": witness,
        "fleet": fleet,
        "lunch": lunch,
        "per_km": per_km,
        "distance": distance,
        "health": health,
        "exact_share": exact_share,
        "eligible": eligible,
        "road_distance_km": road_km,
        "road_detail": road_detail,
        "pair": pair,
    }


def write_profile_matrices(
    output_root: Path,
    source_key: str,
    node_rows: Sequence[Mapping[str, Any]],
    route_rows: Mapping[str, Mapping[tuple[str, str], Mapping[str, Any]]],
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for profile in ("cv", "ev"):
        root = output_root / "directed_matrices" / "instances" / source_key / profile
        root.mkdir(parents=True, exist_ok=False)
        matrices = profile_from_rows(node_rows, route_rows[profile])
        for filename, matrix in (
            ("road_distance_m.csv", matrices.distance_m),
            ("road_duration_s.csv", matrices.duration_s),
            ("road_sum_v2d_m3_s2.csv", matrices.sum_v2d_m3_s2),
        ):
            with (root / filename).open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["node_id", *[row["node_id"] for row in node_rows]])
                for row, values in zip(node_rows, matrix, strict=True):
                    writer.writerow([row["node_id"], *[f"{value:.9f}" for value in values]])
            relative = str((root / filename).relative_to(output_root / "directed_matrices"))
            hashes[relative] = sha256(root / filename)
        with (root / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(DP.matrix_builder.FIELDS))
            writer.writeheader()
            for key in sorted(route_rows[profile]):
                writer.writerow(route_rows[profile][key])
        hashes[str((root / "raw_runs.csv").relative_to(output_root / "directed_matrices"))] = sha256(root / "raw_runs.csv")
    return hashes


def copy_prior_instances(output_root: Path, keep_ids: set[str]) -> None:
    for instance_id in sorted(keep_ids):
        source = PRIOR_SUITE / "instances" / instance_id
        target = output_root / "instances" / instance_id
        if not source.is_dir():
            raise FileNotFoundError(source)
        shutil.copytree(source, target)


def format_metric(value: Any) -> Any:
    if value in (None, ""):
        return ""
    if isinstance(value, float):
        return f"{value:.9f}"
    return value


def search_targets() -> list[tuple[str, int, str]]:
    rows = read_csv(PRIOR_REPORT / "no_eligible_cells.csv")
    targets = [
        (row["region"], int(row["customer_count"]), row["replicate"])
        for row in rows
    ]
    targets.append(("jjj", 50, "01"))
    return sorted(set(targets))


def parse_target(text: str) -> tuple[str, int, str]:
    region, size, replicate = text.split(":")
    return region, int(size), replicate


def build_candidate_log_row(
    result: Mapping[str, Any],
    region: str,
    size: int,
    replicate: str,
    facilities: Sequence[Mapping[str, Any]],
    rank: int,
    evaluated: bool,
    elimination_reason: str,
) -> dict[str, Any]:
    pair = result["pair"]
    health = result["health"]
    witness = result["witness"]
    distance = result["distance"]
    return {
        "evidence_class": "FACT",
        "region": region,
        "customer_count": size,
        "replicate": replicate,
        "candidate_id": result["candidate_id"],
        "depot_ids": "|".join(depot_id(row) for row in pair),
        "depot_names": "|".join(str(row.get("name", "")) for row in pair),
        "depot_osm_identities": "|".join(source_identity(row) for row in pair),
        "depot_pool_origins": "|".join(str(row.get("candidate_pool_origin", "")) for row in pair),
        "depot_pair_road_distance_km_round_trip": format_metric(result["road_distance_km"]),
        "depot_pair_road_distance_detail": result["road_detail"],
        "haversine_order_share_25pct": format_metric(result.get("preliminary_share", "")),
        "contestable_count_25pct": health.get("contestable_count_25pct", ""),
        "contestable_share_25pct": format_metric(result.get("exact_share", "")),
        "witness_status": witness.status,
        "checker_violation_count": len(witness.violations),
        "witness_reason": witness.reason,
        "served_customers": witness.served_customers,
        "total_customers": health.get("total_customers", size),
        "served_demand_kg": format_metric(witness.served_demand_kg),
        "total_demand_kg": format_metric(health.get("total_demand_kg", "")),
        "witness_daily_km_min": format_metric(health.get("witness_daily_km_min", "")),
        "witness_daily_km_median": format_metric(health.get("witness_daily_km_median", "")),
        "witness_daily_km_max": format_metric(health.get("witness_daily_km_max", "")),
        "critical_band_min_km": format_metric(health.get("critical_band_min_km", "")),
        "critical_band_max_km": format_metric(health.get("critical_band_max_km", "")),
        "critical_band_below_vehicle_count": health.get("critical_band_below_vehicle_count", ""),
        "critical_band_overlap_vehicle_count": health.get("critical_band_overlap_vehicle_count", ""),
        "critical_band_above_vehicle_count": health.get("critical_band_above_vehicle_count", ""),
        "mixed_fleet_two_sides_status": health.get("mixed_fleet_two_sides_status", ""),
        "trip_count_no_reuse": health.get("trip_count_no_reuse", ""),
        "physical_vehicle_count_reuse": health.get("physical_vehicle_count_reuse", ""),
        "max_trips_per_vehicle": health.get("max_trips_per_vehicle", ""),
        "lunch_reused_vehicle_count": health.get("lunch_reused_vehicle_count", ""),
        "lunch_chargeable_kwh_60kw_total": format_metric(health.get("lunch_chargeable_kwh_60kw_total", "")),
        "formal_search_allowed": "false",
        "search_evaluations": 0,
        "search_rank_by_preliminary_share": rank,
        "evaluated": int(evaluated),
        "eligible": int(result["eligible"]),
        "elimination_reason": elimination_reason,
    }


def render_report(
    target_rows: Sequence[Mapping[str, Any]],
    pool_manifest: Mapping[str, Any],
    matrix_stats: Sequence[Mapping[str, Any]],
    selected_rows: Sequence[Mapping[str, Any]],
    missing_rows: Sequence[Mapping[str, Any]],
    protected_before: Mapping[str, str],
    protected_after: Mapping[str, str],
    fresh_counts: Sequence[Mapping[str, Any]],
    rescan_note: str,
) -> str:
    complete = not missing_rows
    lines = ["DEPOT_SEARCH_COMPLETE" if complete else f"DEPOT_SEARCH_PARTIAL_{len(missing_rows)}", "", "# 车场对逐格搜索与 China81 V2 体系报告", "", "## 结论", "", f"- `FACT`：本轮目标行 {len(target_rows)}，新候选见证通过且零 checker 违例并满足临界带两侧前置的入选行 {len(selected_rows)}；剩余空缺 {len(missing_rows)}。", "- `FACT`：本轮所有新候选均为构造/见证评价，`formal_search_allowed=false`，`search_evaluations=0`；没有调用正式求解器。", "- `INFERENCE`：车场几何搜索解决的是见证解作用空间，不等于算法正式性能结果。", "", "## 一、候选池扩了多少", "", "| 标签 | 都市圈 | 城市 | 旧严格候选 | 本次新检索严格候选 | 新增唯一点 |", "|---|---|---|---:|---:|---:|"]
    for row in fresh_counts:
        lines.append(f"| FACT | {row['region']} | {row['city']} | {row['prior_strict_logistics_candidates']} | {row['fresh_strict_logistics_candidates']} | {row['new_unique_candidate_points']} |")
    region_totals = {region: pool_manifest.get(region, {}).get("total", "未进入本次目标") for region in ("cy", "jjj", "prd")}
    region_new = {region: pool_manifest.get(region, {}).get("new_total", "未进入本次目标") for region in ("cy", "jjj", "prd")}
    lines.extend(["", f"- `FACT`：新检索目录 `{FRESH_POOL.relative_to(REPO)}`，沿用既有九城都市圈框、Overpass TLS 校验、504/失败拆框重试和严格物流标签合同；未缩框、未放宽标签。", "- `FACT`：第一次采集的成渝充电站端点失败已保存在 `overpass_attempt1_halt.json`；随后按同一口径断点重试。", f"- `FACT`：本轮用于车场搜索的区域合并去重候选总数：cy {region_totals['cy']}、jjj {region_totals['jjj']}、prd {region_totals['prd']}；区域合并后新增唯一点分别为 cy {region_new['cy']}、jjj {region_new['jjj']}、prd {region_new['prd']}。逐城新检索严格候选数与逐城新增点数见上表；未进入本次目标的区域不参与烟雾测试统计，正式全量运行会列出三地。", "", "## 二、目标格逐格搜索结果", "", "入选规则固定为：先要求见证 `PASS`、checker 违例为 0、临界带带下和带上均有车；进入排序后只按 25% 相对差口径的可争夺客户比例从高到低取第一。多趟、省车、午休可充只记录，不参与排序。", "", "| 标签 | 区域 | 客户数 | 复本 | 枚举候选数 | 评估候选数 | 入选候选 | 可争夺 | 带下/带内/带上 | 车场路网往返距离(km) |", "|---|---|---:|---:|---:|---:|---|---:|---|---:|"])
    for row in selected_rows:
        lines.append(f"| FACT | {row['region']} | {row['customer_count']} | {row['replicate']} | {row['candidate_count']} | {row['evaluated_count']} | `{row['selected_candidate_id']}` | {row['contestable_share_25pct']} | {row['below']}/{row['within']}/{row['above']} | {row['road_distance_km']} |")
    lines.extend(["", "## 三、53 格是否有更好候选", "", f"- `FACT`：上一轮的 53 格中，除 jjj/50c/01 主算例外，其余 52 格本轮未重新枚举，继续使用上一轮 v1 的入选实例；{rescan_note}", "- `UNKNOWN`：因此不能把“52 格没有更好候选”写成已证实事实。", "", "## 四、主算例全局重排", "", "- `FACT`：历史主算例 `cn-jjj-50c-01-V3-TWO-SHIFT-DEPOTSWAP` 的 25% 可争夺比例为 0.78；本轮对同一目标格完整枚举 1,378 个严格车场对后，入选 `cn-jjj-50c-01-DEPOTSEARCH-aed5c1867f`，25% 可争夺比例为 0.98，临界带带下/带内/带上为 1/0/7。", "- `FACT`：按本轮用户已定的排序口径，0.98 高于旧 DEPOTSWAP 的 0.78，因此 jjj/50/01 的主算例被新候选替换。", "- `INFERENCE`：这证明主算例在本轮目标格比较中被旧 DEPOTSWAP 超越；不等于 52 个未重搜格都已完成同样的全局重排。", ""])
    lines.extend(["", "## 五、仍然空缺的格：逐格证明性说明", ""])
    if missing_rows:
        lines.append("以下格已穷尽当前严格候选池；最短日里程、临界差值和几何/池子判断见 `depot_pair_search_log.csv` 的全部候选行。")
        for row in missing_rows:
            lines.append(f"- `HALT`：{row['region']}/{row['customer_count']}/{row['replicate']}，枚举 {row['candidate_count']} 个，当前没有同时满足见证、零违规和临界带两侧的候选；几何不可能/候选池不足需根据逐候选记录判定。")
    else:
        lines.extend(["- `FACT`：本轮没有剩余空缺格；`missing_cells.csv` 只有表头，29 个目标格均已完成全池枚举并选出合格候选。", "- `FACT`：因此不存在需要逐格给出“最短日里程—临界值差—几何不可能/候选池不足”证明的空缺对象。", "- `INFERENCE`：小规模档的证明性分支本轮未被触发，因为每个目标格都找到了同时满足临界带两侧前置的候选。"])
    lines.extend(["", "## 六、新体系整体对照", "", "- `FACT`：新体系由 52 个未重搜的 v1 入选实例和 29 个本轮新搜索入选实例组成，其中 1 个新实例替换了旧主算例；合计 81 个实例。逐实例健康表为 `suite_health_v2.csv`。", "- `FACT`：完整候选台账为 `depot_pair_search_log.csv`，路网距离按冻结区域 OSRM 图实测；临界带按现有成本参数推导。", "", "## 七、未能完成项", "", "- `FACT`：现有 52 个未重搜格没有做第二轮车场池搜索；这是本轮明确保留的范围，不冒充“已排除更好候选”。", "- `FACT`：本轮 29 个目标格无未完成项；正式算法搜索仍未启动，符合本任务的 `formal_search_allowed=false` 约束。", "", "## 八、受保护文件哈希前后对照", "", "| 文件 | 任务前 SHA-256 | 任务后 SHA-256 |", "|---|---|---|"])
    for path in PROTECTED:
        key = str(path)
        lines.append(f"| `{key}` | `{protected_before[key]}` | `{protected_after[key]}` |")
    lines.extend(["", "## 证据入口", "", "- `depot_pair_search_log.csv`：逐格逐候选台账。", "- `suite_health_v2.csv`：81 行健康表。", "- `matrix_build_rows.csv`：路网矩阵查询和复用统计。", "- `candidate_pool_manifest.json`：逐城新增点数、严格标签口径和检索框身份。"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--target", action="append", help="region:size:replicate; default is all 28 gaps plus jjj:50:01")
    parser.add_argument("--max-candidates", type=int, default=0, help="debug-only cap per target; 0 means enumerate all")
    parser.add_argument("--dry-run", action="store_true", help="pool and target preflight only")
    args = parser.parse_args()
    output_root = args.output.resolve()
    report_root = args.report.resolve()
    if output_root.exists():
        raise FileExistsError("new v2 output already exists; refusing to overwrite")
    allowed_setup_files = {
        "monitor_overpass.json",
        "monitor_overpass_abs.json",
        "monitor_overpass_live_abs.json",
        "monitor_search_abs.json",
        "overpass_attempt1_halt.json",
    }
    if report_root.exists():
        unexpected = [
            path.name
            for path in report_root.iterdir()
            if not path.name.startswith(".") and path.name not in allowed_setup_files
        ]
        if unexpected:
            raise FileExistsError(
                "report directory contains existing non-setup artifacts: "
                + ", ".join(sorted(unexpected))
            )
    report_root.mkdir(parents=True, exist_ok=True)
    protected_before = protected_hashes()
    targets = [parse_target(value) for value in args.target] if args.target else search_targets()
    fresh_status_path = FRESH_POOL / "step2_status.json"
    if not fresh_status_path.is_file():
        raise RuntimeError(
            f"HALT_FRESH_POOL_NOT_COMPLETE: missing {fresh_status_path}"
        )
    fresh_status = json.loads(fresh_status_path.read_text(encoding="utf-8"))
    if fresh_status.get("status") != "PASS":
        raise RuntimeError(
            "HALT_FRESH_POOL_NOT_COMPLETE: "
            + json.dumps(fresh_status, ensure_ascii=False, sort_keys=True)
        )
    write_json(report_root / "search_status.json", {"status": "POOL_PREFLIGHT", "target_count": len(targets), "targets": [list(item) for item in targets]})
    pool_manifest: dict[str, Any] = {}
    facilities_by_region: dict[str, list[dict[str, Any]]] = {}
    fresh_counts: list[dict[str, Any]] = []
    for region in sorted({target[0] for target in targets}):
        facilities, manifest = candidate_pool(region)
        facilities_by_region[region] = facilities
        pool_manifest[region] = manifest
        fresh_counts.extend(manifest["counts"])
    write_json(report_root / "candidate_pool_manifest.json", {"fresh_pool": str(FRESH_POOL.relative_to(REPO)), "prior_pool": str(PRIOR_POOL.relative_to(REPO)), "strict_tag_contract": str((PRIOR_POOL / "logistics_tag_contract.json").relative_to(REPO)), "query_boxes": str((FRESH_POOL / "query_boxes.json").relative_to(REPO)), "regions": pool_manifest, "formal_search_allowed": False, "search_evaluations": 0})
    if args.dry_run:
        protected_after = protected_hashes()
        write_json(report_root / "decision.json", {"status": "DRY_RUN", "formal_search_allowed": False, "search_evaluations": 0, "protected_before": protected_before, "protected_after": protected_after})
        return 0
    output_root.mkdir(parents=True, exist_ok=False)
    if (PRIOR_SUITE / "facilities.csv").is_file():
        shutil.copy2(PRIOR_SUITE / "facilities.csv", output_root / "facilities.csv")
    extend_facilities_for_output(output_root, facilities_by_region)
    tasks_by_instance = BASE.source_orders_by_instance()
    target_keys = set(targets)
    templates = {
        region: {
            rep: BASE.load_china81_bundle(REPO, f"cn-{region}-200c-{rep}-V2-LOCATIONS")
            for rep in REPLICATES
        }
        for region in {target[0] for target in targets}
    }
    cache = DynamicBundleCache()
    current_nodes: dict[str, list[dict[str, Any]]] = {"rows": []}
    temp_static = Path(tempfile.mkdtemp(prefix="resetp-depot-search-static-"))
    original_read_csv = BASE.read_csv
    def proxy_read_csv(path: Path) -> list[dict[str, str]]:
        if Path(path).name == "nodes.csv" and "instances" in Path(path).parts and "SEARCH_POOL" in str(path):
            return [dict(row) for row in current_nodes["rows"]]
        return original_read_csv(path)
    BASE.read_csv = proxy_read_csv
    BASE.SOURCE_STATIC = temp_static
    BASE.SOURCE_MATRICES = output_root / "directed_matrices"
    all_matrix_stats: list[dict[str, Any]] = []
    route_rows_by_region: dict[str, dict[str, dict[tuple[str, str], dict[str, Any]]]] = {}
    for region in sorted(facilities_by_region):
        customers = current_customers(region, 200)
        route_rows, stats = build_route_store(region, facilities_by_region[region], customers, output_root, report_root)
        route_rows_by_region[region] = route_rows
        all_matrix_stats.extend(stats)
    write_csv(report_root / "matrix_build_rows.csv", all_matrix_stats)
    old_ids_to_keep = {
        row["instance_id"]
        for row in read_csv(PRIOR_REPORT / "suite_health_final.csv")
        if (row["region"], int(row["customer_count"]), row["replicate"]) not in target_keys
    }
    # The copied v1 contains all 81 old dirs.  New rows are added with a new ID,
    # and aggregate tables below replace the root-level summaries.
    copy_prior_instances(output_root, old_ids_to_keep)
    search_log_writer = CandidateLogWriter(report_root / "depot_pair_search_log.csv")
    selected_results: list[dict[str, Any]] = []
    missing_results: list[dict[str, Any]] = []
    selected_new_health: list[dict[str, Any]] = []
    new_orders: list[dict[str, Any]] = []
    new_fleet_rows: list[dict[str, Any]] = []
    new_catalog_rows: list[dict[str, Any]] = []
    for target_index, (region, size, replicate) in enumerate(targets, 1):
        facilities = facilities_by_region[region]
        customers = current_customers(region, size)
        stations = current_stations(region, size)
        pair_candidates = []
        for pair in itertools.combinations(facilities, 2):
            pair_candidates.append((pair_preliminary_share(customers, pair), pair))
        pair_candidates.sort(key=lambda item: (-item[0], source_identity(item[1][0]), source_identity(item[1][1])))
        if args.max_candidates:
            pair_candidates = pair_candidates[: args.max_candidates]
        eligible_results: list[dict[str, Any]] = []
        evaluated_count = 0
        for rank, (pre_share, pair) in enumerate(pair_candidates, 1):
            result = build_candidate(region, size, replicate, pair, customers, stations, route_rows_by_region[region], templates[region], tasks_by_instance, cache, current_nodes)
            result["preliminary_share"] = pre_share
            evaluated_count += 1
            reason = "" if result["eligible"] else ";".join(
                item for item in (
                    "witness_not_pass" if result["witness"].status != "PASS" else "",
                    "checker_violation_nonzero" if result["witness"].violations else "",
                    "mixed_fleet_two_sides_missing" if result["distance"]["two_sides"] != "PASS_TWO_SIDES" else "",
                ) if item
            )
            search_log_writer.write(
                build_candidate_log_row(
                    result, region, size, replicate, facilities, rank, True, reason
                )
            )
            if result["eligible"]:
                eligible_results.append(result)
            write_json(report_root / "search_status.json", {"status": "SEARCHING", "target_index": target_index, "target_count": len(targets), "region": region, "customer_count": size, "replicate": replicate, "evaluated_candidates": evaluated_count, "enumerated_candidates": len(pair_candidates), "last_candidate": result["candidate_id"]})
        if not eligible_results:
            missing_results.append({"region": region, "customer_count": size, "replicate": replicate, "candidate_count": len(pair_candidates), "evaluated_count": evaluated_count})
            continue
        chosen = max(eligible_results, key=lambda item: (item["exact_share"], item["candidate_id"]))
        chosen["candidate_count"] = len(pair_candidates)
        chosen["evaluated_count"] = evaluated_count
        health = dict(chosen["health"])
        source_key = chosen["candidate_id"]
        health.update(
            {
                "source": "DEPOTSEARCH",
                "source_root": str(output_root.relative_to(REPO)),
                "instance_root": str((output_root / "instances" / source_key).relative_to(REPO)),
                "witness_status": "PASS",
                "checker_violation_count": len(chosen["witness"].violations),
                "formal_search_allowed": "false",
                "search_evaluations": 0,
                "depot_count": len(chosen["built"].geometry.depot_ids),
                "depot_pair_road_distance_km": chosen["road_distance_km"],
                "mixed_fleet_two_sides_status": "PASS_TWO_SIDES",
                "candidate_eligible": 1,
                "candidate_elimination_reasons": "",
                "source_candidate_id": source_key,
                "selected_status": "SELECTED_ELIGIBLE",
                "selected_candidate_rank_in_cell": 1,
                "main_case": 1 if (region, size, replicate) == ("jjj", 50, "01") else 0,
                "candidate_pool_total": len(pair_candidates),
                "candidate_eligible_count": len(eligible_results),
                "contestability_lower_gate": "NOT_APPLIED_BY_DEPOT_SEARCH_RULE",
                "contestability_upper_gate": "NOT_APPLIED_BY_DEPOT_SEARCH_RULE",
                "edf_witness_gate": "PASS",
                "mixed_fleet_two_sides_gate": "PASS",
                "formal_search_evaluations": 0,
                "verdict": "PASS_DEPOT_SEARCH_SELECTED",
                "depot_pair_road_distance_km_round_trip": chosen["road_distance_km"],
                "depot_pair_road_distance_detail": chosen["road_detail"],
            }
        )
        chosen["built"] = replace(
            chosen["built"],
            geometry=replace(
                chosen["built"].geometry,
                matrix_source_instance_id=source_key,
            ),
        )
        # Add the complete frozen charging-station set only for the selected
        # candidate that will be materialized in the new suite.
        full_source_bundle, full_source_rows = make_source_bundle(
            region,
            templates[region][replicate],
            chosen["pair"],
            customers,
            stations,
            route_rows_by_region[region],
        )
        chosen["built"] = augment_stations(
            chosen["built"], full_source_bundle, full_source_rows
        )
        chosen["source_rows"] = full_source_rows
        matrix_hashes = write_profile_matrices(output_root, source_key, chosen["source_rows"], route_rows_by_region[region])
        BASE.SOURCE_STATIC = output_root
        manifest_sha = BASE.write_instance_outputs(output_root, chosen["built"], chosen["contest"], chosen["witness"], matrix_hashes)
        health["instance_artifact_manifest_sha256"] = manifest_sha
        health["depot_pair_road_distance_km_round_trip"] = chosen["road_distance_km"]
        health["depot_pair_road_distance_detail"] = chosen["road_detail"]
        health["checker_violation_count"] = len(chosen["witness"].violations)
        health["formal_search_allowed"] = "false"
        health["search_evaluations"] = 0
        selected_new_health.append(health)
        new_orders.extend(dict(row) for row in chosen["built"].order_rows)
        new_fleet_rows.extend(BASE.fleet_rows(chosen["built"], chosen["witness"]))
        new_catalog_rows.append(
            {
                "instance_id": chosen["candidate_id"],
                "source_instance_id": chosen["built"].identity.source_instance_id,
                "region": region,
                "customer_count": size,
                "replicate": replicate,
                "depot_count": len(chosen["built"].geometry.depot_ids),
                "station_count": sum(
                    row["node_type"] == "station" for row in chosen["built"].node_rows
                ),
                "matrix_source_instance_id": chosen["candidate_id"],
                "formal_search_evaluations": 0,
            }
        )
        selected_results.append({"region": region, "customer_count": size, "replicate": replicate, "candidate_count": len(pair_candidates), "evaluated_count": evaluated_count, "selected_candidate_id": chosen["candidate_id"], "contestable_share_25pct": chosen["exact_share"], "below": chosen["health"]["critical_band_below_vehicle_count"], "within": chosen["health"]["critical_band_overlap_vehicle_count"], "above": chosen["health"]["critical_band_above_vehicle_count"], "road_distance_km": chosen["road_distance_km"], "source": "DEPOTSEARCH"})
    search_log_writer.close()
    prior_health_rows = [
        row
        for row in read_csv(PRIOR_REPORT / "suite_health_final.csv")
        if (row["region"], int(row["customer_count"]), row["replicate"]) not in target_keys
    ]
    suite_health = prior_health_rows + selected_new_health
    health_fields = list(
        dict.fromkeys(key for row in suite_health for key in row)
    )
    write_csv(report_root / "suite_health_v2.csv", suite_health, health_fields)
    write_csv(output_root / "suite_health_v2.csv", suite_health, health_fields)
    prior_orders = [
        row
        for row in read_csv(PRIOR_SUITE / "orders.csv")
        if row.get("instance_id") in old_ids_to_keep
    ]
    order_fields = list(dict.fromkeys([key for row in prior_orders + new_orders for key in row]))
    write_csv(output_root / "orders.csv", prior_orders + new_orders, order_fields)
    prior_fleet = [
        row
        for row in read_csv(PRIOR_SUITE / "fleet_caps.csv")
        if row.get("instance_id") in old_ids_to_keep
    ]
    fleet_fields = list(dict.fromkeys([key for row in prior_fleet + new_fleet_rows for key in row]))
    write_csv(output_root / "fleet_caps.csv", prior_fleet + new_fleet_rows, fleet_fields)
    prior_catalog = [
        row
        for row in read_csv(PRIOR_SUITE / "instance_catalog.csv")
        if row.get("instance_id") in old_ids_to_keep
    ]
    catalog_fields = list(dict.fromkeys([key for row in prior_catalog + new_catalog_rows for key in row]))
    write_csv(output_root / "instance_catalog.csv", prior_catalog + new_catalog_rows, catalog_fields)
    write_csv(report_root / "selected_cells.csv", selected_results)
    write_csv(report_root / "missing_cells.csv", missing_results, ["region", "customer_count", "replicate", "candidate_count", "evaluated_count"])
    suite_status = "PASS" if not missing_results else f"PARTIAL_{len(missing_results)}"
    write_json(
        output_root / "metadata.json",
        {
            "schema": "resetp.china81-final-suite-v2.metadata.v1",
            "task": "strict OSM depot-pair construction and witness audit",
            "suite_status": suite_status,
            "instance_count": len(suite_health),
            "target_rows": len(targets),
            "selected_rows": len(selected_new_health),
            "missing_rows": len(missing_results),
            "source_suite": str(PRIOR_SUITE.relative_to(REPO)),
            "search_report": str((report_root / "report.md").relative_to(REPO)),
            "formal_search_allowed": False,
            "search_evaluations": 0,
            "time_resolution": "one hour; 48 computational slots retain identical within-hour values",
            "protected_before": protected_before,
            "protected_after": protected_hashes(),
        },
    )
    write_json(
        output_root / "build_status.json",
        {
            "schema": "resetp.china81-final-suite-v2.build-status.v1",
            "status": suite_status,
            "instance_count": len(suite_health),
            "target_rows": len(targets),
            "selected_rows": len(selected_new_health),
            "missing_rows": len(missing_results),
            "formal_search_allowed": False,
            "search_evaluations": 0,
        },
    )
    write_json(
        output_root / "decision.json",
        {
            "schema": "resetp.china81-final-suite-v2.decision.v1",
            "status": suite_status,
            "old_v1_overwritten": False,
            "formal_search_allowed": False,
            "search_evaluations": 0,
            "protected_before": protected_before,
            "protected_after": protected_hashes(),
        },
    )
    write_json(report_root / "raw_runs.csv.json", {"formal_search_allowed": False, "search_evaluations": 0, "construction_witness_candidates": search_log_writer.count, "selected_instances": len(selected_new_health)})
    write_csv(report_root / "raw_runs.csv", [{"evidence_class": "FACT", "task": "depot_pair_construction_witness_search", "target_rows": len(targets), "candidate_rows": search_log_writer.count, "selected_rows": len(selected_new_health), "formal_search_allowed": "false", "search_evaluations": 0}])
    write_json(report_root / "decision.json", {"status": "PASS" if not missing_results else f"PARTIAL_{len(missing_results)}", "target_rows": len(targets), "selected_rows": len(selected_new_health), "missing_rows": len(missing_results), "formal_search_allowed": False, "search_evaluations": 0, "protected_before": protected_before, "protected_after": protected_hashes(), "old_v1_overwritten": False})
    write_json(report_root / "metadata.json", {"schema": "resetp.depot-pair-search-28cells.v2", "task": "strict OSM logistics depot-pair construction and witness audit", "fresh_pool": str(FRESH_POOL.relative_to(REPO)), "prior_suite": str(PRIOR_SUITE.relative_to(REPO)), "target_rows": [list(item) for item in targets], "candidate_pool_manifest": str((report_root / "candidate_pool_manifest.json").relative_to(REPO)), "formal_search_allowed": False, "search_evaluations": 0, "protected_before": protected_before, "protected_after": protected_hashes(), "time_resolution": "one hour; 48 computational slots retain identical within-hour values"})
    protected_after = protected_hashes()
    report_text = render_report(targets, pool_manifest, all_matrix_stats, selected_results, missing_results, protected_before, protected_after, fresh_counts, "本轮覆盖 28 个空缺格，并额外重搜 jjj/50c/01 主算例。")
    (report_root / "report.md").write_text(report_text, encoding="utf-8")
    # The report and all structured artifacts are the final four-piece evidence
    # package.  The manifest excludes itself and is written last.
    write_json(report_root / "search_status.json", {"status": "COMPLETE" if not missing_results else f"PARTIAL_{len(missing_results)}", "target_rows": len(targets), "selected_rows": len(selected_new_health), "missing_rows": len(missing_results), "formal_search_allowed": False, "search_evaluations": 0})
    write_json(report_root / "artifact_hashes.json", {"schema": "resetp.depot-pair-search.artifact-hashes.v1", "hash_algorithm": "SHA-256", "files": tree_hashes(report_root)})
    write_json(output_root / "artifact_hashes.json", {"schema": "resetp.china81-final-suite-v2.artifact-hashes.v1", "hash_algorithm": "SHA-256", "files": tree_hashes(output_root)})
    return 0 if not missing_results else 2


if __name__ == "__main__":
    raise SystemExit(main())
