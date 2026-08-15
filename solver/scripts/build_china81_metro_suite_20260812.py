#!/usr/bin/env python3
"""Build the real-point metropolitan China81 suite without solver search.

The construction is deliberately split into durable stages.  Customer points
are fixed by a depot-independent hash order, depot pairs are selected from
named OSM logistics facilities, all OSM charging stations inside the selected
customer bounding box are retained, and road matrices come from the frozen
China81 OSRM graphs.  Existing suites are read-only inputs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "solver" / "src"))

from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.instance_loader import (  # noqa: E402
    Instance,
    Node,
    RoadProfileMatrices,
    load_profiled_road_matrices,
)
from setp_solver.solution import Route, Solution  # noqa: E402


BASE_SCRIPT = REPO / "solver/scripts/build_china81_suite_rebuild_20260812.py"
DP_SCRIPT = REPO / "solver/scripts/build_suite_depotpair_rebuild_20260812.py"
POOL_ROOT = REPO / "data/ChinaInstances/china9_metro_pool_20260812"
SOURCE_STATIC = REPO / (
    "data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723"
)
DEFAULT_OUTPUT = REPO / (
    "data/ChinaInstances/china81_metro_suite_v1_20260812"
)
DEFAULT_REPORT = REPO / "solver/reports/metro_rebuild_20260812"
PROTECTED = (
    Path("solver/src/setp_solver/cost.py"),
    Path("solver/src/setp_solver/check.py"),
    Path("solver/src/setp_solver/search/evaluation.py"),
)
REGIONS = ("cy", "jjj", "prd")
SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
REPLICATES = ("01", "02", "03")
ANCHOR_CITY = {"cy": "chengdu", "jjj": "beijing", "prd": "guangzhou"}
BALANCE_MIN_SHARE = 0.35
PAIR_NAME_TERMS = re.compile(
    "物流|仓储|仓库|货仓|货库|冷库|配送|快递|速递|分拨|货运|"
    "货场|物流园|供应链|保税|电商园|储备库|"
    "logistics|warehouse|distribution|freight|cargo|depot",
    re.I,
)
METRO_INSTANCE_RE = re.compile(
    r"^cn-(?P<region>cy|jjj|prd)-(?P<size>\d+)c-"
    r"(?P<replicate>01|02|03)-V3-TWO-SHIFT-METRO$"
)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = load_module("china81_metro_base_20260812", BASE_SCRIPT)
dp = load_module("china81_metro_dp_20260812", DP_SCRIPT)
# The task requires a serial, clean-machine construction run.
dp.ROUTE_WORKERS = 1
dp.ROUTER_THREADS = 2


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
        raise ValueError(f"cannot write headerless CSV: {path}")
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


def clean_appledouble(root: Path) -> list[str]:
    removed: list[str] = []
    if root.exists():
        for path in sorted(root.rglob("._*")):
            if path.is_file():
                removed.append(str(path.relative_to(REPO)))
                path.unlink()
    return removed


def source_identity(row: Mapping[str, str]) -> str:
    return f"{row['osm_type']}/{row['osm_id']}"


def customer_id(row: Mapping[str, str]) -> str:
    return f"L_OSM_{row['osm_type'].upper()}_{row['osm_id']}"


def depot_id(row: Mapping[str, str]) -> str:
    return f"D_OSM_{row['osm_type'].upper()}_{row['osm_id']}"


def station_id(row: Mapping[str, str]) -> str:
    return f"S_OSM_{row['osm_type'].upper()}_{row['osm_id']}"


def valid_coordinate(row: Mapping[str, str]) -> bool:
    try:
        latitude = float(row["latitude"])
        longitude = float(row["longitude"])
    except (KeyError, TypeError, ValueError):
        return False
    return math.isfinite(latitude) and math.isfinite(longitude)


def haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    radius = 6371.0
    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    core = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2.0) ** 2
    )
    return radius * 2.0 * math.atan2(math.sqrt(core), math.sqrt(1.0 - core))


def pool_rows(city: str, feature: str) -> list[dict[str, str]]:
    path = POOL_ROOT / "pools" / f"{city}__{feature}.csv"
    rows: dict[str, dict[str, str]] = {}
    for row in read_csv(path):
        if not valid_coordinate(row):
            continue
        identity = source_identity(row)
        rows.setdefault(identity, dict(row))
    return list(rows.values())


def customer_rank(row: Mapping[str, str]) -> tuple[str, str]:
    identity = source_identity(row)
    return hashlib.sha256(f"METRO_CUSTOMER_V1|{identity}".encode()).hexdigest(), identity


def select_customer_rows(city: str) -> list[dict[str, str]]:
    candidates = [
        row
        for row in pool_rows(city, "named_poi")
        if str(row.get("name") or row.get("brand") or "").strip()
    ]
    selected = sorted(candidates, key=customer_rank)
    if len(selected) < max(SIZES):
        raise RuntimeError(f"{city} named POI pool has only {len(selected)} usable rows")
    return selected[: max(SIZES)]


def named_logistics_facility(row: Mapping[str, str]) -> bool:
    name = str(row.get("name", "")).strip()
    if not name or not PAIR_NAME_TERMS.search(name):
        return False
    tags = json.loads(row.get("tags", "{}") or "{}")
    if str(tags.get("depot", "")).lower() in {
        "bus",
        "light_rail",
        "rail",
        "subway",
        "tram",
    }:
        return False
    return (
        tags.get("building") in {"warehouse", "depot"}
        or tags.get("industrial")
        in {"warehouse", "logistics", "distribution", "depot", "freight"}
        or tags.get("landuse") == "industrial"
        or tags.get("amenity") in {"post_depot", "freight_terminal"}
    )


def customer_bbox(rows: Sequence[Mapping[str, str]]) -> dict[str, float]:
    latitudes = [float(row["latitude"]) for row in rows]
    longitudes = [float(row["longitude"]) for row in rows]
    return {
        "south": min(latitudes),
        "west": min(longitudes),
        "north": max(latitudes),
        "east": max(longitudes),
    }


def stations_inside(
    rows: Sequence[Mapping[str, str]],
    box: Mapping[str, float],
) -> list[dict[str, str]]:
    return sorted(
        [
            dict(row)
            for row in rows
            if box["south"] <= float(row["latitude"]) <= box["north"]
            and box["west"] <= float(row["longitude"]) <= box["east"]
        ],
        key=source_identity,
    )


def nearest_assignment(
    customers: Sequence[Mapping[str, str]],
    left: Mapping[str, str],
    right: Mapping[str, str],
) -> tuple[dict[str, str], Counter[str], float]:
    left_id, right_id = depot_id(left), depot_id(right)
    homes: dict[str, str] = {}
    counts: Counter[str] = Counter()
    contestable = 0
    for row in customers:
        distances = {
            left_id: haversine_km(
                float(row["latitude"]),
                float(row["longitude"]),
                float(left["latitude"]),
                float(left["longitude"]),
            ),
            right_id: haversine_km(
                float(row["latitude"]),
                float(row["longitude"]),
                float(right["latitude"]),
                float(right["longitude"]),
            ),
        }
        nearest, second = sorted(distances, key=lambda key: (distances[key], key))
        homes[customer_id(row)] = nearest
        counts[nearest] += 1
        denominator = max(distances[nearest], 1.0e-9)
        if (distances[second] - distances[nearest]) / denominator < 0.25:
            contestable += 1
    return homes, counts, contestable / len(customers)


def select_depot_pairs(
    report_root: Path,
) -> tuple[
    dict[tuple[str, int], tuple[dict[str, str], dict[str, str]]],
    dict[tuple[str, int], list[dict[str, str]]],
    dict[tuple[str, int], list[dict[str, str]]],
    list[dict[str, Any]],
]:
    selected_pairs: dict[
        tuple[str, int], tuple[dict[str, str], dict[str, str]]
    ] = {}
    customers_by_case: dict[tuple[str, int], list[dict[str, str]]] = {}
    stations_by_case: dict[tuple[str, int], list[dict[str, str]]] = {}
    process_rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    customer_rows: list[dict[str, Any]] = []
    station_rows: list[dict[str, Any]] = []

    for region in REGIONS:
        city = ANCHOR_CITY[region]
        ranked_customers = select_customer_rows(city)
        all_stations = pool_rows(city, "charging_station")
        top_identities = {source_identity(row) for row in ranked_customers}
        facilities = [
            row
            for row in pool_rows(city, "logistics_candidate")
            if named_logistics_facility(row)
            and source_identity(row) not in top_identities
        ]
        facilities.sort(key=source_identity)
        if len(facilities) < 2:
            raise RuntimeError(f"{city} has fewer than two named logistics facilities")

        for size in SIZES:
            customers = [dict(row) for row in ranked_customers[:size]]
            box = customer_bbox(customers)
            stations = stations_inside(all_stations, box)
            customers_by_case[(region, size)] = customers
            stations_by_case[(region, size)] = stations
            choices: list[tuple[tuple[Any, ...], int]] = []
            minimum_count = math.ceil(BALANCE_MIN_SHARE * size - 1.0e-12)
            for left_index, left in enumerate(facilities):
                for right in facilities[left_index + 1 :]:
                    homes, counts, contestable_share = nearest_assignment(
                        customers, left, right
                    )
                    left_id, right_id = depot_id(left), depot_id(right)
                    low = min(counts[left_id], counts[right_id])
                    balance_pass = low >= minimum_count
                    contestability_pass = (
                        base.CONTEST_SHARE_LOWER
                        <= contestable_share
                        <= base.CONTEST_SHARE_UPPER
                    )
                    separation = haversine_km(
                        float(left["latitude"]),
                        float(left["longitude"]),
                        float(right["latitude"]),
                        float(right["longitude"]),
                    )
                    row_index = len(process_rows)
                    process_rows.append(
                        {
                            "evidence_class": "FACT",
                            "region": region,
                            "city": city,
                            "customer_count": size,
                            "left_name": left["name"],
                            "left_osm_identity": source_identity(left),
                            "left_depot_id": left_id,
                            "right_name": right["name"],
                            "right_osm_identity": source_identity(right),
                            "right_depot_id": right_id,
                            "left_assignment_count": counts[left_id],
                            "right_assignment_count": counts[right_id],
                            "minimum_assignment_share": low / size,
                            "balance_threshold_share": BALANCE_MIN_SHARE,
                            "balance_status": "PASS" if balance_pass else "FAIL",
                            "haversine_contestable_share_25pct": contestable_share,
                            "existing_contestability_status": (
                                "PASS" if contestability_pass else "FAIL"
                            ),
                            "haversine_depot_distance_km": separation,
                            "selected": 0,
                            "selection_note": "",
                        }
                    )
                    if balance_pass:
                        score = (
                            0 if contestability_pass else 1,
                            (
                                -separation
                                if contestability_pass
                                else abs(contestable_share - 0.375)
                            ),
                            (
                                abs(contestable_share - 0.375)
                                if contestability_pass
                                else -separation
                            ),
                            source_identity(left),
                            source_identity(right),
                        )
                        choices.append((score, row_index))
            if not choices:
                write_csv(report_root / "depot_pair_selection.csv", process_rows)
                write_json(
                    report_root / "step3_status.json",
                    {
                        "step": 3,
                        "status": "HALT_NO_BALANCED_REAL_DEPOT_PAIR",
                        "region": region,
                        "city": city,
                        "customer_count": size,
                        "required_minimum_count": minimum_count,
                    },
                )
                raise RuntimeError(
                    f"{city}/{size}: no real depot pair reaches {minimum_count}/{size}"
                )
            _, chosen_index = min(choices, key=lambda item: item[0])
            process_rows[chosen_index]["selected"] = 1
            process_rows[chosen_index]["selection_note"] = (
                "balanced pair; prefer existing contestability interval, then "
                "greater depot separation, then closeness to interval midpoint"
            )
            chosen = process_rows[chosen_index]
            left = next(
                row
                for row in facilities
                if source_identity(row) == chosen["left_osm_identity"]
            )
            right = next(
                row
                for row in facilities
                if source_identity(row) == chosen["right_osm_identity"]
            )
            selected_pairs[(region, size)] = (dict(left), dict(right))
            selected_rows.append(dict(chosen))
            for rank, row in enumerate(customers, start=1):
                customer_rows.append(
                    {
                        "evidence_class": "FACT",
                        "region": region,
                        "city": city,
                        "customer_count": size,
                        "rank": rank,
                        "location_id": customer_id(row),
                        "osm_identity": source_identity(row),
                        "name": row.get("name") or row.get("brand"),
                        "latitude": row["latitude"],
                        "longitude": row["longitude"],
                        "source_response_path": row["source_response_path"],
                        "source_response_sha256": row["source_response_sha256"],
                        "source_query_bbox": row["source_query_bbox"],
                    }
                )
            for row in stations:
                distances = [
                    haversine_km(
                        float(row["latitude"]),
                        float(row["longitude"]),
                        float(customer["latitude"]),
                        float(customer["longitude"]),
                    )
                    for customer in customers
                ]
                station_rows.append(
                    {
                        "evidence_class": "FACT",
                        "region": region,
                        "city": city,
                        "customer_count": size,
                        "station_id": station_id(row),
                        "osm_identity": source_identity(row),
                        "name": row.get("name", ""),
                        "latitude": row["latitude"],
                        "longitude": row["longitude"],
                        "nearest_customer_distance_km": min(distances),
                        "parameter_source_city": city,
                        "source_response_path": row["source_response_path"],
                        "source_response_sha256": row["source_response_sha256"],
                        "source_query_bbox": row["source_query_bbox"],
                    }
                )

    write_csv(report_root / "depot_pair_selection.csv", process_rows)
    write_csv(report_root / "selected_depot_pairs.csv", selected_rows)
    write_csv(report_root / "customer_selection.csv", customer_rows)
    write_csv(
        report_root / "station_selection.csv",
        station_rows,
        fields=(
            list(station_rows[0])
            if station_rows
            else (
                "evidence_class",
                "region",
                "city",
                "customer_count",
                "station_id",
                "osm_identity",
                "name",
                "latitude",
                "longitude",
                "nearest_customer_distance_km",
                "parameter_source_city",
                "source_response_path",
                "source_response_sha256",
                "source_query_bbox",
            )
        ),
    )
    write_json(
        report_root / "step3_preselection_status.json",
        {
            "step": 3,
            "status": "PAIR_AND_STATION_PRESELECTION_PASS_FLEET_CAP_REPLAY_PENDING",
            "selected_pair_count": len(selected_pairs),
            "customer_selection_rule": (
                "SHA256(METRO_CUSTOMER_V1|osm_type/osm_id), first N; "
                "independent of depot geometry"
            ),
            "station_range_rule": "inclusive customer latitude-longitude bounding box",
            "balance_rule": "each nearest-depot count is at least 35 percent",
        },
    )
    return selected_pairs, customers_by_case, stations_by_case, process_rows


def coordinate_key(row: Mapping[str, Any]) -> str:
    return dp.coordinate_key(row["longitude"], row["latitude"])


def route_pairs_for_nodes(
    nodes: Sequence[Mapping[str, Any]],
) -> set[tuple[str, str]]:
    keys = [coordinate_key(row) for row in nodes]
    return {(left, right) for left in keys for right in keys if left != right}


def source_pool_id(region: str, size: int) -> str:
    return f"cn-{region}-{size}c-METRO-POOL"


def new_instance_id(region: str, size: int, replicate: str) -> str:
    return f"cn-{region}-{size}c-{replicate}-V3-TWO-SHIFT-METRO"


def build_source_pools(
    output_root: Path,
    report_root: Path,
    selected_pairs: Mapping[
        tuple[str, int], tuple[dict[str, str], dict[str, str]]
    ],
    customers_by_case: Mapping[tuple[str, int], Sequence[dict[str, str]]],
    stations_by_case: Mapping[tuple[str, int], Sequence[dict[str, str]]],
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, str]],
    list[dict[str, Any]],
]:
    static_root = output_root / "source_pools"
    source_facilities = read_csv(SOURCE_STATIC / "facilities.csv")
    facility_by_city = {row["city"]: row for row in source_facilities}
    facilities = [dict(row) for row in source_facilities]
    facility_keys = {row["city"] for row in facilities}
    facility_sources: dict[str, dict[str, Any]] = {}
    station_parameters: dict[tuple[str, str], dict[str, Any]] = {}
    nodes_by_pool: dict[str, list[dict[str, Any]]] = {}
    homes_by_pool: dict[str, dict[str, str]] = {}
    catalog: list[dict[str, Any]] = []
    home_rows: list[dict[str, Any]] = []

    for region in REGIONS:
        city = ANCHOR_CITY[region]
        template = facility_by_city[city]
        for size in SIZES:
            pool_id = source_pool_id(region, size)
            pair = selected_pairs[(region, size)]
            customers = list(customers_by_case[(region, size)])
            stations = list(stations_by_case[(region, size)])
            homes, counts, _ = nearest_assignment(customers, *pair)
            nodes: list[dict[str, Any]] = []
            for depot in pair:
                node_id = depot_id(depot)
                facility_key = node_id.removeprefix("D_")
                nodes.append(
                    {
                        "node_id": node_id,
                        "node_type": "depot",
                        # Runtime price and carbon maps are keyed by the real
                        # city, while fleet_rows resolves the per-depot
                        # facility class separately through the node-id suffix.
                        "city": city,
                        "latitude": f"{float(depot['latitude']):.7f}",
                        "longitude": f"{float(depot['longitude']):.7f}",
                        "source_identity": source_identity(depot),
                    }
                )
                if facility_key not in facility_keys:
                    row = dict(template)
                    row.update(
                        {
                            "city": facility_key,
                            "region": region,
                            "depot_name": depot["name"],
                            "depot_lon": f"{float(depot['longitude']):.7f}",
                            "depot_lat": f"{float(depot['latitude']):.7f}",
                            "depot_point_semantics": "OSM_CENTER_OR_NODE_UNALTERED",
                            "depot_source": depot["source_response_path"],
                            "depot_site_power_kw_shadow": f"{base.DEPOT_POWER_KW:.1f}",
                            "depot_parameter_class": (
                                "P43_I_CHINA_LOGISTICS_DEPOT_DC_60KW_DEFAULT"
                            ),
                        }
                    )
                    facilities.append(row)
                    facility_keys.add(facility_key)
                facility_sources[source_identity(depot)] = {
                    "evidence_class": "FACT",
                    "region": region,
                    "city": city,
                    "depot_id": node_id,
                    "name": depot["name"],
                    "osm_identity": source_identity(depot),
                    "latitude": depot["latitude"],
                    "longitude": depot["longitude"],
                    "tags": depot["tags"],
                    "source_response_path": depot["source_response_path"],
                    "source_response_sha256": depot["source_response_sha256"],
                    "source_query_bbox": depot["source_query_bbox"],
                    "depot_charge_power_kw": base.DEPOT_POWER_KW,
                    "depot_gun_count": template["depot_gun_count"],
                    "parameter_source_city": city,
                }
            for station in stations:
                identity = source_identity(station)
                nodes.append(
                    {
                        "node_id": station_id(station),
                        "node_type": "station",
                        "city": city,
                        "latitude": f"{float(station['latitude']):.7f}",
                        "longitude": f"{float(station['longitude']):.7f}",
                        "source_identity": identity,
                    }
                )
                station_parameters[(pool_id, station_id(station))] = {
                    "power_kw": float(template["station_power_kw"]),
                    "gun_count": int(float(template["station_gun_count"])),
                    "parameter_class": template["station_parameter_class"],
                    "parameter_source_city": city,
                }
            for customer in customers:
                nodes.append(
                    {
                        "node_id": customer_id(customer),
                        "node_type": "customer",
                        "city": city,
                        "latitude": f"{float(customer['latitude']):.7f}",
                        "longitude": f"{float(customer['longitude']):.7f}",
                        "source_identity": source_identity(customer),
                    }
                )
                home_rows.append(
                    {
                        "evidence_class": "FACT",
                        "pool_id": pool_id,
                        "region": region,
                        "city": city,
                        "customer_count": size,
                        "source_customer_id": customer_id(customer),
                        "source_identity": source_identity(customer),
                        "home_depot_id": homes[customer_id(customer)],
                    }
                )
            if len({row["node_id"] for row in nodes}) != len(nodes):
                raise RuntimeError(f"duplicate node identity in {pool_id}")
            nodes_by_pool[pool_id] = nodes
            homes_by_pool[pool_id] = homes
            target = static_root / "instances" / pool_id
            target.mkdir(parents=True, exist_ok=True)
            write_csv(target / "nodes.csv", nodes)
            write_csv(
                target / "home_assignments.csv",
                [row for row in home_rows if row["pool_id"] == pool_id],
            )
            catalog.append(
                {
                    "instance_id": pool_id,
                    "region": region,
                    "city": city,
                    "customer_count": size,
                    "depot_count": 2,
                    "station_count": len(stations),
                    "node_count": len(nodes),
                    "left_assignment_count": counts[depot_id(pair[0])],
                    "right_assignment_count": counts[depot_id(pair[1])],
                    "source_pool": str(POOL_ROOT.relative_to(REPO)),
                }
            )
    write_csv(static_root / "facilities.csv", facilities)
    write_csv(static_root / "instance_catalog.csv", catalog)
    write_csv(output_root / "home_assignments.csv", home_rows)
    write_csv(
        output_root / "facility_sources.csv",
        sorted(facility_sources.values(), key=lambda row: row["osm_identity"]),
    )
    parameter_rows = [
        {
            "evidence_class": "FACT",
            "pool_id": pool_id,
            "station_id": node_id,
            **values,
        }
        for (pool_id, node_id), values in sorted(station_parameters.items())
    ]
    write_csv(
        output_root / "station_parameter_assignments.csv",
        parameter_rows,
        fields=(
            list(parameter_rows[0])
            if parameter_rows
            else (
                "evidence_class",
                "pool_id",
                "station_id",
                "power_kw",
                "gun_count",
                "parameter_class",
                "parameter_source_city",
            )
        ),
    )
    write_json(
        report_root / "step3_source_pool_status.json",
        {
            "step": 3,
            "status": "SOURCE_POOLS_FROZEN",
            "pool_count": len(nodes_by_pool),
            "customer_selection_depends_on_depot_pair": False,
            "station_range_rule": "inclusive customer latitude-longitude bounding box",
        },
    )
    return nodes_by_pool, homes_by_pool, parameter_rows


def matrix_from_rows(
    nodes: Sequence[Mapping[str, Any]],
    rows: Mapping[tuple[str, str], Mapping[str, Any]],
    field: str,
) -> tuple[tuple[float, ...], ...]:
    output: list[tuple[float, ...]] = []
    for left in nodes:
        left_key = coordinate_key(left)
        values: list[float] = []
        for right in nodes:
            right_key = coordinate_key(right)
            if left_key == right_key:
                values.append(0.0)
            else:
                values.append(float(rows[(left_key, right_key)][field]))
        output.append(tuple(values))
    return tuple(output)


def write_profile_matrices(
    root: Path,
    nodes: Sequence[Mapping[str, Any]],
    rows: Mapping[tuple[str, str], Mapping[str, Any]],
) -> RoadProfileMatrices:
    root.mkdir(parents=True, exist_ok=True)
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
        dp.matrix_builder.FIELDS,
    )
    return RoadProfileMatrices(
        distance_m=distance,
        duration_s=duration,
        sum_v2d_m3_s2=sum_v2d,
    )


def build_matrix_authority(
    output_root: Path,
    report_root: Path,
    nodes_by_pool: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    matrix_root = output_root / "directed_matrices"
    matrix_root.mkdir(parents=True, exist_ok=True)
    stats: list[dict[str, Any]] = []
    for region in REGIONS:
        region_pools = [
            pool_id for pool_id in nodes_by_pool if pool_id.startswith(f"cn-{region}-")
        ]
        required: set[tuple[str, str]] = set()
        for pool_id in region_pools:
            required.update(route_pairs_for_nodes(nodes_by_pool[pool_id]))
        for profile in ("cv", "ev"):
            db_path = matrix_root / f"route_cache_{region}_{profile}.sqlite"
            db: sqlite3.Connection = dp.matrix_builder.init_db(db_path)
            try:
                reused = dp.seed_cache(
                    db,
                    dp.SOURCE_MATRICES / f"route_cache_{region}_{profile}.sqlite",
                    required,
                )
                checkpoint = matrix_root / f"checkpoint_{region}_{profile}.json"
                with dp.RouterSession(region, profile, matrix_root) as router:
                    present_before, queried = dp.ensure_routes(
                        db, router.endpoint, required, checkpoint
                    )
                route_rows = dp.load_route_rows(db, required)
                for pool_id in region_pools:
                    nodes = nodes_by_pool[pool_id]
                    pool_pairs = route_pairs_for_nodes(nodes)
                    write_profile_matrices(
                        matrix_root / "instances" / pool_id / profile,
                        nodes,
                        {key: route_rows[key] for key in pool_pairs},
                    )
                stats.append(
                    {
                        "evidence_class": "FACT",
                        "region": region,
                        "profile": profile,
                        "required_directed_pairs": len(required),
                        "present_before_router": present_before,
                        "reused_from_frozen_cache_this_stage": reused,
                        "queried_from_frozen_osrm_graph": queried,
                        "route_workers": 1,
                        **dp.graph_identity(region, profile),
                    }
                )
                write_csv(report_root / "matrix_build_rows.csv", stats)
                write_json(
                    report_root / "step3_matrix_status.json",
                    {
                        "step": 3,
                        "status": "IN_PROGRESS",
                        "completed_region_profiles": len(stats),
                        "target_region_profiles": 6,
                        "last_region": region,
                        "last_profile": profile,
                    },
                )
            finally:
                db.close()
    write_json(
        report_root / "step3_matrix_status.json",
        {
            "step": 3,
            "status": "PASS",
            "completed_region_profiles": len(stats),
            "target_region_profiles": 6,
            "serial_route_workers": 1,
        },
    )
    return stats


def station_parameter_map(output_root: Path) -> dict[tuple[str, str], dict[str, str]]:
    return {
        (row["pool_id"], row["station_id"]): row
        for row in read_csv(output_root / "station_parameter_assignments.csv")
    }


def load_source_bundle(
    output_root: Path,
    pool_id: str,
    template: Any,
) -> Any:
    node_rows = read_csv(output_root / "source_pools/instances" / pool_id / "nodes.csv")
    parameters = station_parameter_map(output_root)
    nodes: list[Node] = []
    for row in node_rows:
        node_type = row["node_type"]
        station = parameters.get((pool_id, row["node_id"]))
        nodes.append(
            Node(
                node_id=row["node_id"],
                node_type=(
                    "d" if node_type == "depot" else ("f" if node_type == "station" else "c")
                ),
                x=float(row["longitude"]),
                y=float(row["latitude"]),
                demand=0.0 if node_type != "customer" else 1.0,
                ready_time=0.0,
                due_time=24.0 * 3600.0,
                charge_power_kw=(
                    base.DEPOT_POWER_KW
                    if node_type == "depot"
                    else (float(station["power_kw"]) if station is not None else None)
                ),
                station_chargers=(
                    2
                    if node_type == "depot"
                    else (int(station["gun_count"]) if station is not None else None)
                ),
                city=row["city"],
            )
        )
    profiles = load_profiled_road_matrices(
        output_root / "directed_matrices/instances" / pool_id,
        nodes,
    )
    homes = {
        row["source_customer_id"]: row["home_depot_id"]
        for row in read_csv(
            output_root / "source_pools/instances" / pool_id / "home_assignments.csv"
        )
    }
    instance = Instance(
        nodes=nodes,
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
        customer_home_depot=MappingProxyType(homes),
    )


class OneBundleCache:
    def __init__(self, bundle: Any) -> None:
        self.bundle = bundle

    def get(self, instance_id: str) -> Any:
        if instance_id != self.bundle.instance_id:
            raise KeyError(instance_id)
        return self.bundle


def augment_all_stations(
    output_root: Path,
    built: Any,
    source_bundle: Any,
) -> Any:
    stations = [
        node for node in source_bundle.instance.nodes if node.node_type.lower() == "f"
    ]
    if not stations:
        return built
    source_rows = {
        row["node_id"]: row
        for row in read_csv(
            output_root
            / "source_pools/instances"
            / built.geometry.matrix_source_instance_id
            / "nodes.csv"
        )
    }
    mapping_by_new = {
        row["new_node_id"]: row for row in built.source_mapping_rows
    }
    depots = [node for node in built.instance.nodes if node.node_type.lower() == "d"]
    customers = [node for node in built.instance.nodes if node.node_type.lower() == "c"]
    station_nodes = [
        replace(
            node,
            ready_time=base.SHIFT_ROWS["AM"]["start_minute"] * 60.0,
            due_time=base.SHIFT_ROWS["PM"]["end_minute"] * 60.0,
        )
        for node in stations
    ]
    new_nodes = [*depots, *station_nodes, *customers]
    source_ids: list[str] = []
    for node in new_nodes:
        if node.node_type.lower() == "f":
            source_ids.append(node.node_id)
        else:
            source_ids.append(mapping_by_new[node.node_id]["source_node_id"])
    source_indices = [source_bundle.instance.node_index[node_id] for node_id in source_ids]
    profiles: dict[str, RoadProfileMatrices] = {}
    for profile_id, matrices in source_bundle.instance.road_profiles.items():
        profiles[profile_id] = RoadProfileMatrices(
            distance_m=tuple(
                tuple(matrices.distance_m[left][right] for right in source_indices)
                for left in source_indices
            ),
            duration_s=tuple(
                tuple(matrices.duration_s[left][right] for right in source_indices)
                for left in source_indices
            ),
            sum_v2d_m3_s2=tuple(
                tuple(matrices.sum_v2d_m3_s2[left][right] for right in source_indices)
                for left in source_indices
            ),
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
            "city": source_rows[node.node_id]["city"],
            "latitude": source_rows[node.node_id]["latitude"],
            "longitude": source_rows[node.node_id]["longitude"],
            "source_identity": source_rows[node.node_id]["source_identity"],
        }
        for node in station_nodes
    ]
    station_mapping = [
        {
            "new_node_id": node.node_id,
            "source_instance_id": built.geometry.matrix_source_instance_id,
            "source_node_id": node.node_id,
            "source_city": source_rows[node.node_id]["city"],
            "latitude": source_rows[node.node_id]["latitude"],
            "longitude": source_rows[node.node_id]["longitude"],
            "mapping_class": "IDENTITY_REAL_OSM_CHARGING_STATION",
        }
        for node in station_nodes
    ]
    depot_rows = [row for row in built.node_rows if row["node_type"] == "depot"]
    customer_rows = [row for row in built.node_rows if row["node_type"] == "customer"]
    depot_mapping = [
        row
        for row in built.source_mapping_rows
        if row["new_node_id"] in {node.node_id for node in depots}
    ]
    customer_mapping = [
        row
        for row in built.source_mapping_rows
        if row["new_node_id"] in {node.node_id for node in customers}
    ]
    return replace(
        built,
        instance=instance,
        node_rows=tuple([*depot_rows, *station_rows, *customer_rows]),
        source_mapping_rows=tuple(
            [*depot_mapping, *station_mapping, *customer_mapping]
        ),
    )


def matrix_hashes(output_root: Path) -> dict[str, str]:
    root = output_root / "directed_matrices"
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted((root / "instances").rglob("*"))
        if path.is_file() and not path.name.startswith("._")
    }


def station_distance_summary(
    stations: Sequence[Mapping[str, str]],
    customers: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    distances = [
        min(
            haversine_km(
                float(station["latitude"]),
                float(station["longitude"]),
                float(customer["latitude"]),
                float(customer["longitude"]),
            )
            for customer in customers
        )
        for station in stations
    ]
    if not distances:
        return {
            "station_count": 0,
            "minimum_km": "",
            "p25_km": "",
            "median_km": "",
            "p75_km": "",
            "maximum_km": "",
        }
    ordered = sorted(distances)
    quartiles = (
        statistics.quantiles(ordered, n=4, method="inclusive")
        if len(ordered) >= 2
        else [ordered[0], ordered[0], ordered[0]]
    )
    return {
        "station_count": len(ordered),
        "minimum_km": min(ordered),
        "p25_km": quartiles[0],
        "median_km": statistics.median(ordered),
        "p75_km": quartiles[2],
        "maximum_km": max(ordered),
    }


def contestability_rows_zero_safe(built: Any) -> list[dict[str, Any]]:
    """Preserve zero-road-cost rows instead of failing on a zero denominator."""

    rows: list[dict[str, Any]] = []
    depots = built.geometry.depot_ids
    for customer_id in sorted(built.orders_by_customer):
        costs: dict[str, float] = {}
        for depot in depots:
            route = Route(
                vehicle_id="CV-DIRECT",
                vehicle_type="cv",
                home_depot_id=depot,
                node_sequence=[depot, customer_id, depot],
            )
            breakdown = evaluate(
                Solution(routes=[route]),
                built.instance,
                built.time_profile,
                built.prices,
                carbon_quota_kg=0.0,
            )
            costs[depot] = float(breakdown["total_cost"]) - float(
                breakdown["cost_fix"]
            )
        nearest, second = sorted(costs, key=lambda key: (costs[key], key))[:2]
        gap = costs[second] - costs[nearest]
        relative = (
            gap / costs[nearest]
            if costs[nearest] > 0.0
            else (0.0 if gap == 0.0 else math.inf)
        )
        row: dict[str, Any] = {
            "instance_id": built.identity.new_instance_id,
            "customer_id": customer_id,
            "home_depot_id": built.customer_home_depot[customer_id],
            "nearest_depot": nearest,
            "second_depot": second,
            "nearest_cost_cny": costs[nearest],
            "second_cost_cny": costs[second],
            "absolute_gap_cny": gap,
            "relative_gap": relative,
            "zero_nearest_direct_cost": int(costs[nearest] == 0.0),
        }
        for threshold in base.CONTEST_THRESHOLDS:
            row[f"contestable_at_{int(threshold * 100)}pct"] = int(
                relative < threshold
            )
        rows.append(row)
    return rows


def build_suite(
    output_root: Path,
    report_root: Path,
    selected_pairs: Mapping[
        tuple[str, int], tuple[dict[str, str], dict[str, str]]
    ],
    customers_by_case: Mapping[tuple[str, int], Sequence[dict[str, str]]],
    stations_by_case: Mapping[tuple[str, int], Sequence[dict[str, str]]],
    matrix_stats: Sequence[Mapping[str, Any]],
    protected_before: Mapping[str, str],
) -> dict[str, Any]:
    base.SOURCE_STATIC = output_root / "source_pools"
    base.SOURCE_MATRICES = output_root / "directed_matrices"
    tasks_by_instance = base.source_orders_by_instance()
    hashes = matrix_hashes(output_root)
    health_rows: list[dict[str, Any]] = []
    witness_rows: list[dict[str, Any]] = []
    fleet_rows: list[dict[str, Any]] = []
    lunch_rows: list[dict[str, Any]] = []
    order_rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    catalog_rows: list[dict[str, Any]] = []
    station_summaries: list[dict[str, Any]] = []
    pair_outcomes: list[dict[str, Any]] = []

    for region in REGIONS:
        city = ANCHOR_CITY[region]
        for size in SIZES:
            pool_id = source_pool_id(region, size)
            pair = selected_pairs[(region, size)]
            customers = list(customers_by_case[(region, size)])
            stations = list(stations_by_case[(region, size)])
            homes, counts, _ = nearest_assignment(customers, *pair)
            station_summary = station_distance_summary(stations, customers)
            station_summaries.append(
                {
                    "evidence_class": "FACT",
                    "region": region,
                    "city": city,
                    "customer_count": size,
                    **station_summary,
                }
            )
            for replicate in REPLICATES:
                source_id = f"cn-{region}-{size}c-{replicate}-V2-LOCATIONS"
                target_id = new_instance_id(region, size, replicate)
                template = load_china81_bundle(
                    REPO,
                    f"cn-{region}-200c-{replicate}-V2-LOCATIONS",
                )
                source_bundle = load_source_bundle(output_root, pool_id, template)
                identity = base.ParsedIdentity(
                    source_instance_id=source_id,
                    new_instance_id=target_id,
                    region=region,
                    size=size,
                    replicate=replicate,
                )
                geometry = base.GeometryChoice(
                    mode="REAL_OSM_METROPOLITAN_DEPOTPAIR_P46_20260812",
                    matrix_source_instance_id=pool_id,
                    depot_ids=tuple(depot_id(row) for row in pair),
                    customer_source_ids=tuple(customer_id(row) for row in customers),
                    home_depot_by_source_customer=MappingProxyType(homes),
                    attempted_rebuild=True,
                    rebuild_succeeded=True,
                    reanchored_customer_count=size,
                    note=(
                        "depot-independent SHA256 customer selection; nearest real "
                        "OSM logistics-facility assignment; all OSM stations inside "
                        "the inclusive customer bounding box"
                    ),
                )
                built = base.build_instance(
                    identity,
                    tasks_by_instance[source_id],
                    geometry,
                    OneBundleCache(source_bundle),
                )
                built = augment_all_stations(output_root, built, source_bundle)
                contest = contestability_rows_zero_safe(built)
                witness = base.build_witness(built)
                fleet = base.fleet_health(witness)
                lunch = base.lunch_health(built, witness)
                per_km = base.per_km_health(built, witness)
                critical = [
                    float(per_km["scenarios"][name]["critical_daily_km"])
                    for name in ("valley", "flat", "peak")
                ]
                distance = base.witness_distance_health(built, witness, critical)
                saved_instance_root = output_root / "instances" / target_id
                if saved_instance_root.exists():
                    if [dict(row) for row in built.node_rows] != read_csv(
                        saved_instance_root / "nodes.csv"
                    ):
                        raise RuntimeError(
                            f"resume replay nodes differ for {target_id}"
                        )
                    replay_orders = [
                        {key: str(value) for key, value in row.items()}
                        for row in built.order_rows
                    ]
                    if replay_orders != read_csv(saved_instance_root / "orders.csv"):
                        raise RuntimeError(
                            f"resume replay orders differ for {target_id}"
                        )
                    base.write_csv(
                        saved_instance_root / "contestability.csv", contest
                    )
                    base.write_json(
                        saved_instance_root / "artifact_hashes.json",
                        base.instance_hash_manifest(saved_instance_root),
                    )
                    manifest_sha = sha256(
                        saved_instance_root / "artifact_hashes.json"
                    )
                else:
                    manifest_sha = base.write_instance_outputs(
                        output_root, built, contest, witness, hashes
                    )
                per_instance_fleet = base.fleet_rows(built, witness)
                fleet_by_depot = {
                    row["depot_id"]: int(row["total_fleet_cap"])
                    for row in per_instance_fleet
                }
                assignment_text = (
                    f"{depot_id(pair[0])}={counts[depot_id(pair[0])]};"
                    f"{depot_id(pair[1])}={counts[depot_id(pair[1])]};"
                    f"min_share={min(counts.values()) / size:.6f};"
                    f"min_max_ratio={min(counts.values()) / max(counts.values()):.6f}"
                )
                cap_text = ";".join(
                    f"{key}={value}" for key, value in sorted(fleet_by_depot.items())
                )
                station_text = (
                    f"count={station_summary['station_count']};"
                    f"median_nearest_customer_km="
                    f"{station_summary['median_km'] if station_summary['median_km'] != '' else 'NA'}"
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
                health.update(
                    {
                        "nearest_assignment_counts_and_balance": assignment_text,
                        "depot_total_fleet_caps": cap_text,
                        "charging_stations_and_nearest_customer_median_km": station_text,
                        "zero_nearest_direct_cost_count": sum(
                            int(row["zero_nearest_direct_cost"])
                            for row in contest
                        ),
                    }
                )
                if any(value < 1 for value in fleet_by_depot.values()):
                    health["FLAG"] = (
                        str(health["FLAG"]) + " | " if health["FLAG"] else ""
                    ) + "DEPOT_FLEET_CAP:one or more total_fleet_cap values below 1"
                health_rows.append(health)
                witness_rows.extend(base.witness_rows(built, witness))
                fleet_rows.extend(per_instance_fleet)
                lunch_rows.extend(dict(row) for row in lunch["rows"])
                order_rows.extend(dict(row) for row in built.order_rows)
                raw_rows.append(
                    {
                        "evidence_class": "FACT",
                        "instance_id": target_id,
                        "source_instance_id": source_id,
                        "region": region,
                        "customer_count": size,
                        "replicate": replicate,
                        "depot_balance_status": (
                            "PASS"
                            if min(counts.values())
                            >= math.ceil(BALANCE_MIN_SHARE * size - 1.0e-12)
                            else "FAIL"
                        ),
                        "fleet_cap_status": (
                            "PASS"
                            if fleet_by_depot and min(fleet_by_depot.values()) >= 1
                            else "FAIL"
                        ),
                        "contestability_gate": health["contestability_gate"],
                        "edf_witness_status": health["edf_witness_status"],
                        "mixed_fleet_two_sides_status": health[
                            "mixed_fleet_two_sides_status"
                        ],
                        "station_count": station_summary["station_count"],
                        "served_customers": health["served_customers"],
                        "total_customers": health["total_customers"],
                        "served_demand_kg": health["served_demand_kg"],
                        "total_demand_kg": health["total_demand_kg"],
                        "formal_search_evaluations": 0,
                        "FLAG": health["FLAG"],
                    }
                )
                pair_outcomes.append(
                    {
                        "evidence_class": "FACT",
                        "instance_id": target_id,
                        "region": region,
                        "city": city,
                        "customer_count": size,
                        "replicate": replicate,
                        "left_depot_id": depot_id(pair[0]),
                        "left_name": pair[0]["name"],
                        "left_osm_identity": source_identity(pair[0]),
                        "left_assignment_count": counts[depot_id(pair[0])],
                        "left_total_fleet_cap": fleet_by_depot.get(depot_id(pair[0]), ""),
                        "right_depot_id": depot_id(pair[1]),
                        "right_name": pair[1]["name"],
                        "right_osm_identity": source_identity(pair[1]),
                        "right_assignment_count": counts[depot_id(pair[1])],
                        "right_total_fleet_cap": fleet_by_depot.get(depot_id(pair[1]), ""),
                        "minimum_assignment_share": min(counts.values()) / size,
                        "haversine_depot_distance_km": haversine_km(
                            float(pair[0]["latitude"]),
                            float(pair[0]["longitude"]),
                            float(pair[1]["latitude"]),
                            float(pair[1]["longitude"]),
                        ),
                    }
                )
                catalog_rows.append(
                    {
                        "instance_id": target_id,
                        "source_instance_id": source_id,
                        "region": region,
                        "customer_count": size,
                        "replicate": replicate,
                        "depot_count": 2,
                        "station_count": station_summary["station_count"],
                        "matrix_source_instance_id": pool_id,
                        "formal_search_evaluations": 0,
                        "instance_artifact_manifest_sha256": manifest_sha,
                    }
                )
                write_json(
                    output_root / "build_status.json",
                    {
                        "status": "IN_PROGRESS",
                        "completed_health_rows": len(health_rows),
                        "target_health_rows": 81,
                        "last_instance_id": target_id,
                    },
                )

    if len(health_rows) != 81:
        raise RuntimeError(f"health row count {len(health_rows)} != 81")
    write_csv(report_root / "suite_health_metro.csv", health_rows)
    write_csv(report_root / "health_witness_routes.csv", witness_rows)
    write_csv(report_root / "station_distance_summary.csv", station_summaries)
    write_csv(report_root / "depot_pair_outcomes.csv", pair_outcomes)
    write_csv(report_root / "raw_runs.csv", raw_rows)
    write_csv(output_root / "orders.csv", order_rows)
    write_csv(output_root / "fleet_caps.csv", fleet_rows)
    write_csv(output_root / "instance_catalog.csv", catalog_rows)
    write_csv(output_root / "lunch_charge_rows.csv", lunch_rows)

    protected_after = {str(path): sha256(REPO / path) for path in PROTECTED}
    decision = {
        "status": "PASS",
        "network_probe_status": "PASS",
        "pool_extraction_status": "PASS",
        "instance_count": len(health_rows),
        "balanced_nearest_assignment_count": sum(
            row["depot_balance_status"] == "PASS" for row in raw_rows
        ),
        "positive_two_depot_fleet_cap_count": sum(
            row["fleet_cap_status"] == "PASS" for row in raw_rows
        ),
        "contestability_gate_pass_count": sum(
            row["contestability_gate"] == "PASS" for row in health_rows
        ),
        "edf_witness_pass_count": sum(
            row["edf_witness_status"] == "PASS" for row in health_rows
        ),
        "mixed_fleet_two_sides_pass_count": sum(
            row["mixed_fleet_two_sides_status"] == "PASS_TWO_SIDES"
            for row in health_rows
        ),
        "protected_files_unchanged": protected_before == protected_after,
        "formal_search_evaluations": 0,
        "flags": [
            {"instance_id": row["instance_id"], "FLAG": row["FLAG"]}
            for row in health_rows
            if row["FLAG"]
        ],
    }
    if (
        decision["balanced_nearest_assignment_count"] != 81
        or decision["positive_two_depot_fleet_cap_count"] != 81
        or not decision["protected_files_unchanged"]
    ):
        decision["status"] = "HALT_CONSTRUCTION_ACCEPTANCE_FAILED"
    write_json(report_root / "decision.json", decision)
    write_json(
        report_root / "step3_status.json",
        {
            "step": 3,
            "status": (
                "PASS" if decision["status"] == "PASS" else decision["status"]
            ),
            "depot_pair_count": len(selected_pairs),
            "instance_fleet_replays": 81,
            "positive_two_depot_fleet_cap_count": decision[
                "positive_two_depot_fleet_cap_count"
            ],
        },
    )
    write_json(
        output_root / "build_status.json",
        {
            "status": "COMPLETE" if decision["status"] == "PASS" else "HALT",
            "completed_health_rows": 81,
            "target_health_rows": 81,
        },
    )
    write_json(
        report_root / "metadata.json",
        {
            "schema": "resetp.metro-rebuild.metadata.v1",
            "task": "real OSM metropolitan spatial-foundation rebuild",
            "network_probe": str(
                (POOL_ROOT / "network_probe/step1.json").relative_to(REPO)
            ),
            "pool_authority": str(POOL_ROOT.relative_to(REPO)),
            "suite_authority": str(output_root.relative_to(REPO)),
            "regions": REGIONS,
            "anchor_city_by_region": ANCHOR_CITY,
            "sizes": SIZES,
            "replicates": REPLICATES,
            "customer_selection": (
                "first N by SHA256(METRO_CUSTOMER_V1|osm identity), "
                "independent of depot geometry"
            ),
            "nearest_depot_ruler": "great-circle distance on unmodified OSM coordinates",
            "station_range": "inclusive customer latitude-longitude bounding box",
            "road_matrices": "frozen China81 OSRM graph, serial Route API",
            "route_workers": 1,
            "depot_charge_power_kw": base.DEPOT_POWER_KW,
            "fleet_parameter_class_id": base.FLEET_PARAMETER_CLASS_ID,
            "formal_search_evaluations": 0,
            "old_suite_modified": False,
            "protected_before": protected_before,
            "protected_after": protected_after,
            "matrix_rows": list(matrix_stats),
        },
    )
    return decision


def tree_hashes(root: Path, *, excludes: set[str] | None = None) -> dict[str, str]:
    excluded = excludes or set()
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.name not in excluded
        and not path.name.startswith("._")
    }


def render_preliminary_report(
    output_root: Path,
    report_root: Path,
    decision: Mapping[str, Any],
) -> str:
    probe = json.loads(
        (POOL_ROOT / "network_probe/step1.json").read_text(encoding="utf-8")
    )
    city_counts = read_csv(POOL_ROOT / "city_counts.csv")
    selected_pairs = read_csv(report_root / "selected_depot_pairs.csv")
    station_rows = read_csv(report_root / "station_distance_summary.csv")
    health = read_csv(report_root / "suite_health_metro.csv")
    metadata = json.loads((report_root / "metadata.json").read_text(encoding="utf-8"))
    tag_contract = json.loads(
        (POOL_ROOT / "logistics_tag_contract.json").read_text(encoding="utf-8")
    )
    lines = [
        "# China81 都市配送空间地基重建",
        "",
        "## 结论",
        "",
        f"- `FACT`：Overpass 最小探测通过，HTTP {probe.get('http_status')}，"
        f"有效元素 {probe.get('element_count')}，耗时 {probe.get('elapsed_seconds')} 秒。",
        f"- `FACT`：九城三类池已重采，新套件已构建 {decision['instance_count']} 个算例；"
        f"最近场双边≥35% 通过 {decision['balanced_nearest_assignment_count']}/81，"
        f"两场车队上限均为正通过 {decision['positive_two_depot_fleet_cap_count']}/81。",
        f"- `FACT`：既有三项健康检查通过数为：可争夺 "
        f"{decision['contestability_gate_pass_count']}/81，EDF 完整服务见证 "
        f"{decision['edf_witness_pass_count']}/81，混合车队临界点两侧 "
        f"{decision['mixed_fleet_two_sides_pass_count']}/81。",
        "- `FACT`：客户点按 OSM 身份的 SHA-256 顺序取前 N；该顺序在车场配对前冻结，"
        "没有为达到几何判据替换或过滤客户。",
        "- `FACT`：路网矩阵使用冻结 China81 OSRM 图串行重放；本步搜索求解评价数为 0。",
        "",
        "## 扩框采集",
        "",
        "| 标签 | 城市 | 区域 | 客户候选 | 物流候选 | 充电站 |",
        "|---|---|---|---:|---:|---:|",
    ]
    counts: dict[tuple[str, str], int] = {
        (row["city"], row["feature"]): int(row["record_count"])
        for row in city_counts
    }
    cities = sorted({row["city"] for row in city_counts})
    region_by_city = {row["city"]: row["region"] for row in city_counts}
    for city in cities:
        lines.append(
            f"| FACT | {city} | {region_by_city[city]} | "
            f"{counts[(city, 'named_poi')]} | "
            f"{counts[(city, 'logistics_candidate')]} | "
            f"{counts[(city, 'charging_station')]} |"
        )
    lines.extend(
        [
            "",
            "### 物流标签合同",
            "",
            "- `FACT`：物流池的精确标签集如下：",
            "",
            "```json",
            json.dumps(tag_contract, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "## 车场对",
            "",
            "| 标签 | 区域 | 规模 | 左场 | 右场 | 分配数 | 最小占比 | 场间直线距离(km) |",
            "|---|---:|---:|---|---|---:|---:|---:|",
        ]
    )
    for row in selected_pairs:
        lines.append(
            f"| FACT | {row['region']} | {row['customer_count']} | "
            f"{row['left_name']} (`{row['left_osm_identity']}`) | "
            f"{row['right_name']} (`{row['right_osm_identity']}`) | "
            f"{row['left_assignment_count']} / {row['right_assignment_count']} | "
            f"{float(row['minimum_assignment_share']):.6f} | "
            f"{float(row['haversine_depot_distance_km']):.6f} |"
        )
    lines.extend(
        [
            "",
            "## 充电站",
            "",
            "- `FACT`：“客户群范围”按该规模客户的纬度最小/最大值和经度最小/最大值形成的包含边界矩形定义；"
            "矩形内全部真实 OSM 充电站都保留。",
            "- `FACT`：新站的功率、枪数和参数类逐站复用同城 `facilities.csv` 现行值；"
            "具体赋值见 `station_parameter_assignments.csv`。",
            "",
            "| 标签 | 区域 | 规模 | 站数 | 最近客户距离 min / p25 / median / p75 / max (km) |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for row in station_rows:
        values = [row[key] for key in ("minimum_km", "p25_km", "median_km", "p75_km", "maximum_km")]
        formatted = " / ".join("NA" if value == "" else f"{float(value):.6f}" for value in values)
        lines.append(
            f"| FACT | {row['region']} | {row['customer_count']} | "
            f"{row['station_count']} | {formatted} |"
        )
    flags = [row for row in health if row.get("FLAG")]
    lines.extend(
        [
            "",
            "## 套件健康与电车距离",
            "",
            "- `FACT`：每个算例的详细三项既有健康检查、两场分配、车队上限、站数和站到最近客户中位距离见 "
            "`suite_health_metro.csv`。",
            "- `FACT`：健康表保留了见证车辆日里程的最小/中位/最大值和混合车队临界带，"
            "可直接与用户指定的 80 kWh、0.605–0.736 kWh/km（满电约 109–132 km）对照。",
            f"- `FACT`：健康表中保留 FLAG 的算例为 {len(flags)}/81，没有删除或隐藏。",
            "",
            "## 保护边界",
            "",
        ]
    )
    for path in PROTECTED:
        key = str(path)
        lines.append(
            f"- `FACT`：`{key}` 任务前后 SHA-256 均为 "
            f"`{metadata['protected_before'][key]}`。"
        )
    lines.extend(
        [
            "- `FACT`：旧套件 `china81_suite_prd_fix_v1_20260812` 未覆盖；新池、新套件和报告均是新目录。",
            "",
            "## 20 主循环",
            "",
            "- `UNKNOWN`：本节等待 `cn-cy-50c-01` 指定配置运行和真尺子复核；完成后才写 `METRO_DONE`。",
            "",
        ]
    )
    return "\n".join(lines)


def load_runtime_payload(
    repo: Path,
    instance_id: str,
    *,
    fleet_parameters: Any,
) -> Any:
    """Replay one saved metropolitan instance for the technical search runner."""

    match = METRO_INSTANCE_RE.fullmatch(instance_id)
    if match is None:
        raise ValueError(f"not a metropolitan suite instance: {instance_id}")
    region = match.group("region")
    size = int(match.group("size"))
    replicate = match.group("replicate")
    output_root = repo / "data/ChinaInstances/china81_metro_suite_v1_20260812"
    report_root = repo / "solver/reports/metro_rebuild_20260812"
    source_id = f"cn-{region}-{size}c-{replicate}-V2-LOCATIONS"
    pool_id = source_pool_id(region, size)
    template = load_china81_bundle(
        repo,
        f"cn-{region}-200c-{replicate}-V2-LOCATIONS",
    )
    source_bundle = load_source_bundle(output_root, pool_id, template)
    source_nodes = read_csv(
        output_root / "source_pools/instances" / pool_id / "nodes.csv"
    )
    homes = {
        row["source_customer_id"]: row["home_depot_id"]
        for row in read_csv(
            output_root / "source_pools/instances" / pool_id / "home_assignments.csv"
        )
    }
    geometry = base.GeometryChoice(
        mode="REAL_OSM_METROPOLITAN_DEPOTPAIR_P46_20260812",
        matrix_source_instance_id=pool_id,
        depot_ids=tuple(
            row["node_id"] for row in source_nodes if row["node_type"] == "depot"
        ),
        customer_source_ids=tuple(
            row["node_id"] for row in source_nodes if row["node_type"] == "customer"
        ),
        home_depot_by_source_customer=MappingProxyType(homes),
        attempted_rebuild=True,
        rebuild_succeeded=True,
        reanchored_customer_count=size,
        note=(
            "depot-independent SHA256 customer selection; nearest real OSM "
            "logistics-facility assignment; all in-range OSM charging stations"
        ),
    )
    identity = base.ParsedIdentity(
        source_instance_id=source_id,
        new_instance_id=instance_id,
        region=region,
        size=size,
        replicate=replicate,
    )
    base.SOURCE_STATIC = output_root / "source_pools"
    base.SOURCE_MATRICES = output_root / "directed_matrices"
    built = base.build_instance(
        identity,
        base.source_orders_by_instance()[source_id],
        geometry,
        OneBundleCache(source_bundle),
    )
    built = augment_all_stations(output_root, built, source_bundle)
    saved_root = output_root / "instances" / instance_id
    if [dict(row) for row in built.node_rows] != read_csv(saved_root / "nodes.csv"):
        raise RuntimeError("metro runtime replay differs from saved nodes.csv")
    replay_orders = [
        {key: str(value) for key, value in row.items()} for row in built.order_rows
    ]
    if replay_orders != read_csv(saved_root / "orders.csv"):
        raise RuntimeError("metro runtime replay differs from saved orders.csv")
    saved_fleet = [
        row
        for row in read_csv(output_root / "fleet_caps.csv")
        if row["instance_id"] == instance_id
    ]
    fleet_caps = MappingProxyType(
        {
            row["depot_id"]: MappingProxyType(
                {
                    "num_cv": int(row["base_all_cv_routes_Rd"]),
                    "num_ev": int(row["base_all_ev_routes_Re"]),
                    "total_fleet_cap": (
                        int(row["base_all_cv_routes_Rd"])
                        + int(row["base_all_ev_routes_Re"])
                    ),
                }
            )
            for row in saved_fleet
        }
    )
    if len(fleet_caps) != 2 or any(
        caps["num_cv"] < 1 or caps["num_ev"] < 1
        for caps in fleet_caps.values()
    ):
        raise ValueError("metro endogenous fleet caps are not positive at both depots")
    instance = replace(
        built.instance,
        num_cv=sum(caps["num_cv"] for caps in fleet_caps.values()),
        num_ev=sum(caps["num_ev"] for caps in fleet_caps.values()),
    )
    charger_rows: dict[str, MappingProxyType[str, Any]] = {}
    for row in saved_fleet:
        charger_rows[row["depot_id"]] = MappingProxyType(
            {
                "charger_count": int(row["configured_depot_gun_count_if_finite"]),
                "active_concurrency_limit": "UNBOUNDED",
                "capacity_mode": "unbounded",
                "charge_power_kw": float(row["depot_charge_power_kw"]),
                "parameter_class": row["charger_parameter_class"],
            }
        )
    station_parameters = station_parameter_map(output_root)
    for node in instance.nodes:
        if node.node_type.lower() != "f":
            continue
        row = station_parameters[(pool_id, node.node_id)]
        charger_rows[node.node_id] = MappingProxyType(
            {
                "charger_count": int(row["gun_count"]),
                "active_concurrency_limit": int(row["gun_count"]),
                "capacity_mode": "finite_station",
                "charge_power_kw": float(row["power_kw"]),
                "parameter_class": row["parameter_class"],
            }
        )
    bundle = replace(
        template,
        instance_id=instance_id,
        region=region,
        instance=instance,
        time_profile=list(built.time_profile),
        prices=built.prices,
        source_paths=MappingProxyType(
            {
                **dict(template.source_paths),
                "suite": str(output_root.relative_to(repo)),
                "instance": str(saved_root.relative_to(repo)),
                "matrix_reference": str(
                    (saved_root / "matrix_reference.json").relative_to(repo)
                ),
                "health_witness_routes": str(
                    (report_root / "health_witness_routes.csv").relative_to(repo)
                ),
            }
        ),
        customer_home_depot=built.customer_home_depot,
        fleet_caps_by_depot=fleet_caps,
        fleet_parameter_class_id=fleet_parameters.parameter_class_id,
        has_additional_total_fleet_cap=(
            fleet_parameters.has_additional_total_fleet_cap
        ),
        charger_scenario_by_node=MappingProxyType(charger_rows),
        static_input_authority=str((output_root / "source_pools").relative_to(repo)),
        road_matrix_authority=str(
            (output_root / "directed_matrices").relative_to(repo)
        ),
        fleet_authority=str(output_root.relative_to(repo)),
        formal_search_allowed=False,
    )
    witness_rows = [
        row
        for row in read_csv(report_root / "health_witness_routes.csv")
        if row["instance_id"] == instance_id
    ]
    if not witness_rows or {row["witness_status"] for row in witness_rows} != {"PASS"}:
        raise ValueError("metro saved health witness is absent or failed")
    shift_contract = json.loads(
        (saved_root / "shift_contract.json").read_text(encoding="utf-8")
    )
    return SimpleNamespace(
        bundle=bundle,
        built=built,
        witness_rows=witness_rows,
        shift_contract=shift_contract,
        saved_root=saved_root,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--stage",
        choices=("select", "all"),
        default="all",
    )
    args = parser.parse_args()
    if not (POOL_ROOT / "step2_status.json").is_file():
        raise FileNotFoundError("metro pool step2_status.json is missing")
    pool_status = json.loads((POOL_ROOT / "step2_status.json").read_text())
    if pool_status.get("status") != "PASS":
        raise RuntimeError(f"metro pool is not complete: {pool_status}")
    report_root = args.report.resolve()
    report_root.mkdir(parents=True, exist_ok=True)
    selected_pairs, customers_by_case, stations_by_case, _ = select_depot_pairs(
        report_root
    )
    if args.stage == "select":
        return 0
    output_root = args.output.resolve()
    resume = False
    if output_root.exists():
        status_path = output_root / "build_status.json"
        if not status_path.is_file():
            raise FileExistsError(
                f"refusing to overwrite unrecognized suite root: {output_root}"
            )
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if status.get("status") != "IN_PROGRESS":
            raise FileExistsError(
                f"refusing to overwrite non-resumable suite root: {output_root}"
            )
        resume = True
    protected_before = {str(path): sha256(REPO / path) for path in PROTECTED}
    output_root.mkdir(parents=True, exist_ok=resume)
    write_json(
        output_root / "build_status.json",
        {"status": "IN_PROGRESS", "completed_health_rows": 0, "target_health_rows": 81},
    )
    nodes_by_pool, _, _ = build_source_pools(
        output_root,
        report_root,
        selected_pairs,
        customers_by_case,
        stations_by_case,
    )
    matrix_stats = build_matrix_authority(output_root, report_root, nodes_by_pool)
    decision = build_suite(
        output_root,
        report_root,
        selected_pairs,
        customers_by_case,
        stations_by_case,
        matrix_stats,
        protected_before,
    )
    removed = [
        *clean_appledouble(output_root),
        *clean_appledouble(report_root),
    ]
    write_json(
        report_root / "appledouble_cleanup.json",
        {"removed_new_output_sidecars": removed, "business_files_deleted": False},
    )
    (report_root / "report.md").write_text(
        render_preliminary_report(output_root, report_root, decision),
        encoding="utf-8",
    )
    write_json(
        output_root / "metadata.json",
        {
            "schema": "resetp.china81-metro-suite.metadata.v1",
            "instance_count": 81,
            "source_pool": str(POOL_ROOT.relative_to(REPO)),
            "formal_search_evaluations": 0,
            "old_suite_modified": False,
        },
    )
    write_json(
        output_root / "artifact_hashes.json",
        {
            "schema": "resetp.china81-metro-suite.artifact-hashes.v1",
            "hash_algorithm": "SHA-256",
            "excluded_self": "artifact_hashes.json",
            "files": tree_hashes(output_root, excludes={"artifact_hashes.json"}),
        },
    )
    write_json(
        report_root / "artifact_hashes.json",
        {
            "schema": "resetp.metro-rebuild.artifact-hashes.v1",
            "hash_algorithm": "SHA-256",
            "excluded_self": "artifact_hashes.json",
            "files": tree_hashes(report_root, excludes={"artifact_hashes.json"}),
            "suite_manifest": str(
                (output_root / "artifact_hashes.json").relative_to(REPO)
            ),
            "suite_manifest_sha256": sha256(output_root / "artifact_hashes.json"),
        },
    )
    return 0 if decision["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
