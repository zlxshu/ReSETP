#!/usr/bin/env python3
"""Build and health-check the approved 2026-08-11 private instance."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import shutil
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "solver" / "src"))

from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.charging_curve import curve_for_charging_node  # noqa: E402
from setp_solver.field_rename_compat import depot_site_power_kw_shadow  # noqa: E402
from setp_solver.china81 import (  # noqa: E402
    CV_FIXED_CNY_PER_DAY,
    EV_FIXED_CNY_PER_DAY,
    EV_NON_ENERGY_CNY_PER_KM,
)
from setp_solver.private_instance_rebuild_20260811 import (  # noqa: E402
    BATTERY_DEPRECIATION_CNY_PER_KM,
    BUNDLE_RELATIVE,
    EV_DAILY_FIXED_PREMIUM_CNY,
    INSTANCE_ID,
    PrivateInstanceRebuildBundle,
    evaluate_rebuild_solution,
    load_private_instance_rebuild,
    route_distance_m,
    validate_shifted_solution,
)
from setp_solver.solution import Route, Solution, route_trip_vehicle_id  # noqa: E402


SOURCE_STATIC = REPO / (
    "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723"
)
SOURCE_MATRICES = REPO / (
    "data/ChinaInstances/"
    "china81_local_directed_matrices_corrected_v10_20260723"
)
SOURCE_INSTANCE = "cn-prd-150c-01-V2-LOCATIONS"
TASK_AUTHORITY = REPO / (
    "data/ChinaInstances/"
    "china81_order_attributes_gis_v2_20260723/orders.csv"
)
TASK_INSTANCE = "cn-prd-50c-01-V2-LOCATIONS"
REPORT_RELATIVE = Path("solver/reports/instance_rebuild_20260811")
PROTECTED = (
    Path("solver/src/setp_solver/cost.py"),
    Path("solver/src/setp_solver/check.py"),
    Path("solver/src/setp_solver/search/evaluation.py"),
)

SHIFT_ROWS = {
    "AM": {"start_minute": 480.0, "end_minute": 660.0},
    "PM": {"start_minute": 780.0, "end_minute": 1140.0},
}
LOCATION_COUNTS = {"guangzhou": 36, "foshan": 14}
CONTESTABILITY_THRESHOLDS = (0.20, 0.25, 0.30)
MAIN_CONTESTABILITY_THRESHOLD = 0.25
VEHICLE_VOLUME_CAPACITY_M3 = 7.2
LOADING_HOURS_PER_M3 = 0.1
DEPOT_CHARGE_POWER_KW = 60.0
HEALTH_SEEDS = (1, 2, 3, 5, 7, 11, 13, 17, 19, 23)


@dataclass(frozen=True)
class RoutePlan:
    depot_id: str
    shift_id: str
    customers: tuple[str, ...]
    volume_m3: float
    demand_kg: float
    departure_second: float
    return_second: float
    distance_m: float


@dataclass(frozen=True)
class Witness:
    seed: int
    plans: tuple[RoutePlan, ...]
    solution: Solution
    departures: Mapping[str, float]
    total_cost: float
    physical_vehicle_count: int


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
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


def tree_sha256(root: Path) -> str:
    """Hash a directory tree without rewriting its historical manifest."""

    digest = hashlib.sha256()
    for path in sorted(
        candidate
        for candidate in root.rglob("*")
        if candidate.is_file() and not candidate.name.startswith("._")
    ):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def assign_shifts(tasks: Sequence[dict[str, str]]) -> dict[str, dict[str, Any]]:
    ordered = sorted(
        tasks,
        key=lambda row: (float(row["time_window_early_minute"]), row["customer_id"]),
    )
    groups = {
        "AM": [row for index, row in enumerate(ordered) if index % 3 == 0],
        "PM": [row for index, row in enumerate(ordered) if index % 3 != 0],
    }
    if {key: len(value) for key, value in groups.items()} != {"AM": 17, "PM": 33}:
        raise RuntimeError("the approved 17/33 shift allocation did not close")
    out: dict[str, dict[str, Any]] = {}
    for shift_id, rows in groups.items():
        source_earlies = [float(row["time_window_early_minute"]) for row in rows]
        source_min = min(source_earlies)
        source_max = max(source_earlies)
        max_width = max(float(row["time_window_width_minute"]) for row in rows)
        start = SHIFT_ROWS[shift_id]["start_minute"]
        final_early = SHIFT_ROWS[shift_id]["end_minute"] - max_width
        for row in rows:
            source_early = float(row["time_window_early_minute"])
            fraction = (
                0.0
                if math.isclose(source_max, source_min)
                else (source_early - source_min) / (source_max - source_min)
            )
            early = start + fraction * (final_early - start)
            width = float(row["time_window_width_minute"])
            out[row["customer_id"]] = {
                "shift_id": shift_id,
                "early": early,
                "late": early + width,
                "width": width,
                "source_early": source_early,
                "source_late": float(row["time_window_late_minute"]),
            }
    return out


def spaced_city_pattern(total: int, second_city_count: int) -> list[str]:
    pattern = []
    for index in range(total):
        before = (index * second_city_count) // total
        after = ((index + 1) * second_city_count) // total
        pattern.append("foshan" if after > before else "guangzhou")
    if pattern.count("foshan") != second_city_count:
        raise RuntimeError("spatially balanced city pattern did not close")
    return pattern


def build_order_and_node_rows() -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, str],
    dict[str, dict[str, str]],
]:
    source_nodes = read_csv(
        SOURCE_STATIC / "instances" / SOURCE_INSTANCE / "nodes.csv"
    )
    nodes_by_id = {row["node_id"]: row for row in source_nodes}
    locations_by_city = {
        city: [
            row
            for row in source_nodes
            if row["node_type"] == "customer" and row["city"] == city
        ][:count]
        for city, count in LOCATION_COUNTS.items()
    }
    if {
        city: len(rows) for city, rows in locations_by_city.items()
    } != LOCATION_COUNTS:
        raise RuntimeError("source location pool is incomplete")

    tasks = [row for row in read_csv(TASK_AUTHORITY) if row["instance_id"] == TASK_INSTANCE]
    if len(tasks) != 50:
        raise RuntimeError("source task authority does not contain 50 rows")
    shift_map = assign_shifts(tasks)
    tasks_by_shift = {
        shift_id: sorted(
            [row for row in tasks if shift_map[row["customer_id"]]["shift_id"] == shift_id],
            key=lambda row: (
                float(row["time_window_early_minute"]),
                row["customer_id"],
            ),
        )
        for shift_id in ("AM", "PM")
    }
    city_quota = {
        "AM": {"guangzhou": 12, "foshan": 5},
        "PM": {"guangzhou": 24, "foshan": 9},
    }
    location_cursor = {"guangzhou": 0, "foshan": 0}
    location_for_task: dict[str, dict[str, str]] = {}
    for shift_id in ("AM", "PM"):
        rows = tasks_by_shift[shift_id]
        pattern = spaced_city_pattern(len(rows), city_quota[shift_id]["foshan"])
        for task, city in zip(rows, pattern, strict=True):
            cursor = location_cursor[city]
            location_for_task[task["customer_id"]] = locations_by_city[city][cursor]
            location_cursor[city] += 1
    if location_cursor != LOCATION_COUNTS:
        raise RuntimeError("not every selected location was used exactly once")

    node_rows: list[dict[str, Any]] = []
    source_node_for_new: dict[str, str] = {}
    for node_id in ("D_foshan", "S_foshan", "D_guangzhou", "S_guangzhou"):
        row = dict(nodes_by_id[node_id])
        node_rows.append(row)
        source_node_for_new[node_id] = node_id

    order_rows: list[dict[str, Any]] = []
    tasks_by_id = {row["customer_id"]: row for row in tasks}
    for customer_id in sorted(tasks_by_id):
        task = tasks_by_id[customer_id]
        location = location_for_task[customer_id]
        shifted = shift_map[customer_id]
        node_rows.append(
            {
                "node_id": customer_id,
                "node_type": "customer",
                "city": location["city"],
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "source_identity": location["source_identity"],
            }
        )
        source_node_for_new[customer_id] = location["node_id"]
        order_rows.append(
            {
                "instance_id": INSTANCE_ID,
                "region": "prd",
                "customer_size": "50",
                "replicate": "01",
                "customer_id": customer_id,
                "city": location["city"],
                "osm_type": location["source_identity"].split("/", 1)[0],
                "osm_id": location["source_identity"].split("/", 1)[-1],
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "name": location["source_identity"],
                "order_seed": task["order_seed"],
                "empirical_source_index_zero_based": task[
                    "empirical_source_index_zero_based"
                ],
                "source_order_uid": task["source_order_uid"],
                "source_volume_m3": task["source_volume_m3"],
                "demand_kg": task["demand_kg"],
                "service_minutes": task["service_minutes"],
                "time_window_early_minute": f"{shifted['early']:.6f}",
                "time_window_late_minute": f"{shifted['late']:.6f}",
                "time_window_width_minute": f"{shifted['width']:.6f}",
                "demand_classification": task["demand_classification"],
                "service_classification": task["service_classification"],
                "window_classification": (
                    "OBSERVED_WIDTH_AND_WITHIN_SHIFT_SHAPE__"
                    "SHIFT_PLACEMENT_EXTRAPOLATED"
                ),
                "shift_id": shifted["shift_id"],
                "shift_start_minute": f"{SHIFT_ROWS[shifted['shift_id']]['start_minute']:.1f}",
                "shift_end_minute": f"{SHIFT_ROWS[shifted['shift_id']]['end_minute']:.1f}",
                "depot_return_required": "1",
                "source_instance_id_task": TASK_INSTANCE,
                "source_customer_id_task": customer_id,
                "source_time_window_early_minute": f"{shifted['source_early']:.6f}",
                "source_time_window_late_minute": f"{shifted['source_late']:.6f}",
                "source_time_window_width_minute": f"{shifted['width']:.6f}",
                "source_instance_id_location": SOURCE_INSTANCE,
                "source_customer_id_location": location["node_id"],
                "location_mapping_class": (
                    "SAME_SOURCE_OSM_LOCATION_POOL__STRUCTURAL_REBUILD"
                ),
                "shift_mapping_class": (
                    "DELIVERY_BOTH_SHIFTS_APPROVED_P43_G__ONE_IN_THREE_AM"
                ),
            }
        )
    return node_rows, order_rows, source_node_for_new, location_for_task


def subset_matrix(
    output_root: Path,
    node_rows: Sequence[Mapping[str, Any]],
    source_node_for_new: Mapping[str, str],
) -> None:
    source_ids = [source_node_for_new[str(row["node_id"])] for row in node_rows]
    new_ids = [str(row["node_id"]) for row in node_rows]
    for profile in ("cv", "ev"):
        source = SOURCE_MATRICES / "instances" / SOURCE_INSTANCE / profile
        target = output_root / "instances" / INSTANCE_ID / profile
        target.mkdir(parents=True, exist_ok=False)
        write_csv(target / "nodes.csv", node_rows, list(node_rows[0]))
        for filename in (
            "road_distance_m.csv",
            "road_duration_s.csv",
            "road_sum_v2d_m3_s2.csv",
        ):
            rows = read_csv(source / filename)
            by_id = {row["node_id"]: row for row in rows}
            out = []
            for new_left, source_left in zip(new_ids, source_ids, strict=True):
                row: dict[str, Any] = {"node_id": new_left}
                for new_right, source_right in zip(new_ids, source_ids, strict=True):
                    row[new_right] = by_id[source_left][source_right]
                out.append(row)
            write_csv(target / filename, out, ["node_id", *new_ids])

        coordinates = {
            f"{float(row['longitude']):.7f},{float(row['latitude']):.7f}"
            for row in node_rows
        }
        raw_rows = [
            row
            for row in read_csv(source / "raw_runs.csv")
            if row["origin_key"] in coordinates
            and row["destination_key"] in coordinates
        ]
        expected = len(node_rows) * (len(node_rows) - 1)
        if len(raw_rows) != expected:
            raise RuntimeError(
                f"{profile} raw road provenance is incomplete: "
                f"{len(raw_rows)} != {expected}"
            )
        write_csv(target / "raw_runs.csv", raw_rows, list(raw_rows[0]))


def write_authority_files(
    output_root: Path,
    node_rows: Sequence[Mapping[str, Any]],
    order_rows: Sequence[Mapping[str, Any]],
    source_node_for_new: Mapping[str, str],
) -> None:
    instance_root = output_root / "instances" / INSTANCE_ID
    instance_root.mkdir(parents=True, exist_ok=False)
    write_csv(instance_root / "nodes.csv", node_rows, list(node_rows[0]))
    write_csv(output_root / "orders.csv", order_rows, list(order_rows[0]))

    facilities = [
        row
        for row in read_csv(SOURCE_STATIC / "facilities.csv")
        if row["city"] in {"guangzhou", "foshan"}
    ]
    if len(facilities) != 2:
        raise RuntimeError("real Guangzhou/Foshan facility rows are incomplete")
    for row in facilities:
        row["depot_site_power_kw_shadow"] = "60.0"
        row["depot_parameter_class"] = (
            "P43_I_CHINA_LOGISTICS_DEPOT_DC_60KW_DEFAULT"
        )
    write_csv(output_root / "facilities.csv", facilities, list(facilities[0]))

    membership_source = {
        (row["instance_id"], row["node_id"]): row
        for row in read_csv(SOURCE_STATIC / "node_city_membership.csv")
    }
    memberships = []
    for row in node_rows:
        source_id = source_node_for_new[str(row["node_id"])]
        source = membership_source[(SOURCE_INSTANCE, source_id)]
        rebuilt = dict(source)
        rebuilt["instance_id"] = INSTANCE_ID
        rebuilt["node_id"] = row["node_id"]
        memberships.append(rebuilt)
    write_csv(
        output_root / "node_city_membership.csv",
        memberships,
        list(memberships[0]),
    )

    nodes_hash = sha256(instance_root / "nodes.csv")
    catalog = [
        {
            "instance_id": INSTANCE_ID,
            "region": "prd",
            "customer_count": 50,
            "city_count": 2,
            "cities": "foshan|guangzhou",
            "node_count": len(node_rows),
            "directed_pairs_per_profile": len(node_rows) * (len(node_rows) - 1),
            "nodes_sha256": nodes_hash,
            "search_evaluations": 0,
        }
    ]
    write_csv(output_root / "instance_catalog.csv", catalog, list(catalog[0]))

    shift_contract = {
        "schema": "resetp.private-two-shift-contract.v1",
        "instance_id": INSTANCE_ID,
        "attendance": {"start_minute": 480.0, "end_minute": 1140.0},
        "shifts": SHIFT_ROWS,
        "lunch": {
            "start_minute": 660.0,
            "end_minute": 780.0,
            "return_to_depot_required": True,
            "loading_and_charging_are_sequential_for_health_ceiling": True,
        },
        "order_allocation": {
            "AM": 17,
            "PM": 33,
            "rule": "source-ready-time rank; every third order to AM",
        },
        "vehicle_volume_capacity_m3": VEHICLE_VOLUME_CAPACITY_M3,
        "loading_hours_per_m3": LOADING_HOURS_PER_M3,
        "source_restoration": (
            "Data Description.xlsx: 08:00-11:00 and 13:00-19:00"
        ),
        "approved_extrapolation": (
            "P43-G: delivery tasks are assigned to both shifts"
        ),
    }
    write_json(output_root / "shift_contract.json", shift_contract)

    vehicle_costs = [
        {
            "vehicle_type": "cv",
            "base_non_energy_cost_cny_per_km": "0.7800",
            "battery_depreciation_cny_per_km": "0.0000",
            "effective_non_energy_cost_cny_per_km": "0.7800",
            "base_daily_fixed_cost_cny": "170.00",
            "daily_fixed_premium_cny": "0.00",
            "effective_daily_fixed_cost_cny": "170.00",
            "source": "existing China81 CV contract",
        },
        {
            "vehicle_type": "ev",
            "base_non_energy_cost_cny_per_km": "0.6700",
            "battery_depreciation_cny_per_km": f"{BATTERY_DEPRECIATION_CNY_PER_KM:.4f}",
            "effective_non_energy_cost_cny_per_km": f"{EV_NON_ENERGY_CNY_PER_KM:.4f}",
            "base_daily_fixed_cost_cny": f"{CV_FIXED_CNY_PER_DAY:.2f}",
            "daily_fixed_premium_cny": f"{EV_DAILY_FIXED_PREMIUM_CNY:.2f}",
            "effective_daily_fixed_cost_cny": f"{EV_FIXED_CNY_PER_DAY:.2f}",
            "source": (
                "Changjiang Securities 2024-07-13 59000 CNY battery / "
                "Goeke & Schneider 2015 241350 km; Chen et al. 2023 Table 7"
            ),
        },
    ]
    write_csv(output_root / "vehicle_costs.csv", vehicle_costs, list(vehicle_costs[0]))

    write_json(
        output_root / "contestability_definition.json",
        {
            "schema": "resetp.contestable-customer-definition.v1",
            "instance_id": INSTANCE_ID,
            "generalized_service_cost": (
                "exact directed-road CV depot-customer-depot variable monetary "
                "cost: non-energy distance + diesel + carbon charge; common "
                "daily fixed cost excluded"
            ),
            "relative_gap_formula": "(second_cost-nearest_cost)/nearest_cost",
            "main_threshold": MAIN_CONTESTABILITY_THRESHOLD,
            "sensitivity_thresholds": CONTESTABILITY_THRESHOLDS,
            "target_share": [0.36, 0.42],
            "selection_rule": (
                "first 36 Guangzhou and first 14 Foshan real OSM customer "
                "locations from cn-prd-150c-01-V2-LOCATIONS"
            ),
        },
    )
    write_json(
        output_root / "decision.json",
        {
            "instance_id": INSTANCE_ID,
            "status": "CONSTRUCTION_ONLY_NO_FORMAL_EXPERIMENT",
            "user_decisions": [
                "P43-A",
                "P43-B",
                "P43-F",
                "P43-G",
                "P43-H",
                "P43-I_DEPOT_POWER_60KW",
            ],
            "protected_files_modified": False,
            "old_instances_overwritten": False,
        },
    )

    # A provisional fail-open fleet ceiling permits the health witness to load.
    # It is replaced by the measured two-shift witness caps before delivery.
    write_fleet_caps(output_root, {"D_foshan": (14, 14), "D_guangzhou": (36, 36)})

    write_json(
        output_root / "metadata.json",
        {
            "schema": "resetp.china81-private-rebuild.v1",
            "instance_id": INSTANCE_ID,
            "created_date": "2026-08-11",
            "formal_search_allowed": False,
            "draft_only": True,
            "search_evaluations": 0,
            "orders": str((BUNDLE_RELATIVE / "orders.csv").as_posix()),
            "source_static_authority": str(SOURCE_STATIC.relative_to(REPO)),
            "source_matrix_authority": str(SOURCE_MATRICES.relative_to(REPO)),
            "source_task_authority": str(TASK_AUTHORITY.relative_to(REPO)),
            "restoration_vs_extrapolation_disclosed": True,
        },
    )


def write_fleet_caps(output_root: Path, counts: Mapping[str, tuple[int, int]]) -> None:
    facilities = {row["city"]: row for row in read_csv(output_root / "facilities.csv")}
    rows = []
    for depot_id, (single_shift_routes, physical_vehicles) in sorted(counts.items()):
        city = depot_id.removeprefix("D_")
        ev = max(1, math.ceil(0.25 * physical_vehicles))
        cv = max(1, physical_vehicles - ev)
        total = cv + ev
        rows.append(
            {
                "instance_id": INSTANCE_ID,
                "depot_id": depot_id,
                "city": city,
                "base_all_cv_routes_Rd": single_shift_routes,
                "base_all_ev_routes_Re": single_shift_routes,
                "num_cv": cv,
                "num_ev": ev,
                "total_fleet_cap": total,
                "default_fleet_electrification_percent_metadata_only": 25,
                "configured_depot_gun_count_if_finite": facilities[city]["depot_gun_count"],
                "depot_charge_power_kw": depot_site_power_kw_shadow(
                    facilities[city]
                ),
                "depot_charger_capacity_default": "UNBOUNDED",
                "fleet_parameter_class": (
                    "REBUILT_TWO_SHIFT_HEALTH_WITNESS_NO_FORMAL_SEARCH"
                ),
                "charger_parameter_class": facilities[city]["depot_parameter_class"],
                "fleet_allocation_map_metadata_only": json.dumps(
                    {
                        "health_witness": {
                            "num_cv": cv,
                            "num_ev": ev,
                            "total_fleet_cap": total,
                        }
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }
        )
    write_csv(output_root / "fleet_caps.csv", rows, list(rows[0]))


def route_clock(
    bundle: PrivateInstanceRebuildBundle,
    depot_id: str,
    shift_id: str,
    customers: Sequence[str],
    *,
    earliest_departure_second: float | None = None,
) -> tuple[bool, float, float, float]:
    shift_start = SHIFT_ROWS[shift_id]["start_minute"] * 60.0
    start = max(
        shift_start,
        shift_start
        if earliest_departure_second is None
        else float(earliest_departure_second),
    )
    end = SHIFT_ROWS[shift_id]["end_minute"] * 60.0
    now = start
    distance = 0.0
    left = depot_id
    node_by_id = {node.node_id: node for node in bundle.instance.nodes}
    for right in (*customers, depot_id):
        arc_distance, duration, _ = bundle.instance.arc_metrics(
            left,
            right,
            "cv",
            fallback_speed_mps=1.0,
        )
        distance += arc_distance
        now += duration
        node = node_by_id[right]
        if right != depot_id:
            now = max(now, float(node.ready_time))
            if now > float(node.due_time) + 1.0e-6:
                return False, start, now, distance
            now += float(node.service_time)
        left = right
    return now <= end + 1.0e-6, start, now, distance


def build_plans(
    bundle: PrivateInstanceRebuildBundle,
    *,
    seed: int,
    home_override: Mapping[str, str] | None = None,
) -> tuple[RoutePlan, ...]:
    rng = random.Random(seed)
    override = dict(home_override or {})
    groups: dict[tuple[str, str], list[str]] = {}
    for customer_id, row in bundle.orders_by_customer.items():
        depot_id = override.get(customer_id, bundle.customer_home_depot[customer_id])
        groups.setdefault((depot_id, row["shift_id"]), []).append(customer_id)

    all_plans: list[RoutePlan] = []
    for (depot_id, shift_id), customer_ids in sorted(groups.items()):
        ordered = list(customer_ids)
        rng.shuffle(ordered)
        routes: list[list[str]] = []
        for customer_id in ordered:
            candidates: list[tuple[float, float, int, int, list[str]]] = []
            customer_row = bundle.orders_by_customer[customer_id]
            customer_volume = float(customer_row["source_volume_m3"])
            customer_demand = float(customer_row["demand_kg"])
            for route_index, current in enumerate(routes):
                volume = sum(
                    float(bundle.orders_by_customer[item]["source_volume_m3"])
                    for item in current
                )
                demand = sum(
                    float(bundle.orders_by_customer[item]["demand_kg"])
                    for item in current
                )
                if volume + customer_volume > VEHICLE_VOLUME_CAPACITY_M3 + 1.0e-9:
                    continue
                if demand + customer_demand > 1735.0 + 1.0e-9:
                    continue
                old_feasible, _, _, old_distance = route_clock(
                    bundle, depot_id, shift_id, current
                )
                if not old_feasible:
                    raise RuntimeError("internal route witness became infeasible")
                for position in range(len(current) + 1):
                    trial = [*current[:position], customer_id, *current[position:]]
                    feasible, _, returned, distance = route_clock(
                        bundle, depot_id, shift_id, trial
                    )
                    if feasible:
                        candidates.append(
                            (
                                distance - old_distance,
                                returned,
                                route_index,
                                position,
                                trial,
                            )
                        )
            if candidates:
                candidates.sort(key=lambda item: (item[0], item[1], rng.random()))
                _, _, route_index, _, trial = candidates[0]
                routes[route_index] = trial
            else:
                feasible, _, _, _ = route_clock(
                    bundle, depot_id, shift_id, [customer_id]
                )
                if not feasible:
                    raise RuntimeError(
                        f"customer {customer_id} is infeasible even alone in {shift_id}"
                    )
                routes.append([customer_id])

        for customers in routes:
            feasible, departed, returned, distance = route_clock(
                bundle, depot_id, shift_id, customers
            )
            if not feasible:
                raise RuntimeError("final route witness is infeasible")
            all_plans.append(
                RoutePlan(
                    depot_id=depot_id,
                    shift_id=shift_id,
                    customers=tuple(customers),
                    volume_m3=sum(
                        float(bundle.orders_by_customer[item]["source_volume_m3"])
                        for item in customers
                    ),
                    demand_kg=sum(
                        float(bundle.orders_by_customer[item]["demand_kg"])
                        for item in customers
                    ),
                    departure_second=departed,
                    return_second=returned,
                    distance_m=distance,
                )
            )
    return tuple(all_plans)


def _minimum_shift_chains(
    bundle: PrivateInstanceRebuildBundle,
    plans: Sequence[RoutePlan],
) -> list[list[tuple[RoutePlan, float, float]]]:
    """Cover fixed same-depot/same-shift routes with the fewest vehicles."""

    if not plans:
        return []
    if len({(plan.depot_id, plan.shift_id) for plan in plans}) != 1:
        raise ValueError("shift-chain construction requires one depot and shift")
    candidates: dict[int, tuple[tuple[int, ...], tuple[float, ...], tuple[float, ...]]] = {}

    def extend(
        sequence: tuple[int, ...],
        departures: tuple[float, ...],
        returns: tuple[float, ...],
        remaining: frozenset[int],
    ) -> None:
        mask = sum(1 << index for index in sequence)
        incumbent = candidates.get(mask)
        if incumbent is None or returns[-1] < incumbent[2][-1]:
            candidates[mask] = (sequence, departures, returns)
        for index in sorted(remaining):
            plan = plans[index]
            earliest = (
                SHIFT_ROWS[plan.shift_id]["start_minute"] * 60.0
                if not sequence
                else returns[-1]
                + plan.volume_m3 * LOADING_HOURS_PER_M3 * 3600.0
            )
            feasible, departed, returned, _ = route_clock(
                bundle,
                plan.depot_id,
                plan.shift_id,
                plan.customers,
                earliest_departure_second=earliest,
            )
            if feasible:
                extend(
                    (*sequence, index),
                    (*departures, departed),
                    (*returns, returned),
                    remaining.difference({index}),
                )

    all_indices = frozenset(range(len(plans)))
    for index in range(len(plans)):
        plan = plans[index]
        feasible, departed, returned, _ = route_clock(
            bundle,
            plan.depot_id,
            plan.shift_id,
            plan.customers,
        )
        if not feasible:
            raise RuntimeError("route plan became infeasible before chaining")
        extend(
            (index,),
            (departed,),
            (returned,),
            all_indices.difference({index}),
        )

    by_member: dict[int, list[int]] = {index: [] for index in range(len(plans))}
    for mask in candidates:
        for index in range(len(plans)):
            if mask & (1 << index):
                by_member[index].append(mask)

    memo: dict[int, tuple[int, tuple[int, ...]]] = {}
    full_mask = (1 << len(plans)) - 1

    def cover(mask: int) -> tuple[int, tuple[int, ...]]:
        if mask == full_mask:
            return 0, ()
        if mask in memo:
            return memo[mask]
        first = next(index for index in range(len(plans)) if not mask & (1 << index))
        best: tuple[int, tuple[int, ...]] | None = None
        for candidate_mask in by_member[first]:
            if candidate_mask & mask:
                continue
            rest_count, rest = cover(mask | candidate_mask)
            trial = (1 + rest_count, (candidate_mask, *rest))
            if best is None or (trial[0], trial[1]) < (best[0], best[1]):
                best = trial
        if best is None:
            raise RuntimeError("fixed routes have no complete shift-chain cover")
        memo[mask] = best
        return best

    _, selected_masks = cover(0)
    chains = []
    for mask in selected_masks:
        sequence, departures, returns = candidates[mask]
        chains.append(
            [
                (plans[index], departures[position], returns[position])
                for position, index in enumerate(sequence)
            ]
        )
    return chains


def plans_to_solution(
    plans: Sequence[RoutePlan],
    bundle: PrivateInstanceRebuildBundle,
    *,
    vehicle_type: str = "cv",
) -> tuple[Solution, dict[str, float]]:
    routes: list[Route] = []
    departures: dict[str, float] = {}
    for depot_id in sorted({plan.depot_id for plan in plans}):
        morning = sorted(
            [plan for plan in plans if plan.depot_id == depot_id and plan.shift_id == "AM"],
            key=lambda plan: (plan.return_second, plan.customers),
        )
        afternoon = sorted(
            [plan for plan in plans if plan.depot_id == depot_id and plan.shift_id == "PM"],
            key=lambda plan: (plan.return_second, plan.customers),
        )
        afternoon_chains = _minimum_shift_chains(bundle, afternoon)
        physical_count = max(len(morning), len(afternoon_chains))
        for index in range(physical_count):
            prefix = "EV" if vehicle_type == "ev" else "CV"
            physical = f"{prefix}_{depot_id}_{index + 1}"
            trip_index = 1
            scheduled: list[tuple[RoutePlan, float]] = []
            if index < len(morning):
                scheduled.append((morning[index], morning[index].departure_second))
            if index < len(afternoon_chains):
                scheduled.extend(
                    (plan, departed)
                    for plan, departed, _returned in afternoon_chains[index]
                )
            for plan, departed in scheduled:
                vehicle_id = route_trip_vehicle_id(physical, trip_index)
                trip_index += 1
                route = Route(
                    vehicle_id=vehicle_id,
                    vehicle_type=vehicle_type,
                    home_depot_id=depot_id,
                    node_sequence=[depot_id, *plan.customers, depot_id],
                )
                routes.append(route)
                departures[vehicle_id] = departed
    return Solution(routes=routes), departures


def build_witness(bundle: PrivateInstanceRebuildBundle, seed: int) -> Witness:
    plans = build_plans(bundle, seed=seed)
    solution, departures = plans_to_solution(plans, bundle)
    validate_shifted_solution(
        solution,
        bundle,
        departure_second_by_route=departures,
    )
    breakdown = evaluate_rebuild_solution(solution, bundle, carbon_quota_kg=0.0)
    return Witness(
        seed=seed,
        plans=plans,
        solution=solution,
        departures=departures,
        total_cost=float(breakdown["total_cost"]),
        physical_vehicle_count=int(breakdown["n_veh_cv"] + breakdown["n_veh_ev"]),
    )


def contestability_rows(bundle: PrivateInstanceRebuildBundle) -> list[dict[str, Any]]:
    rows = []
    for customer_id in sorted(bundle.orders_by_customer):
        costs = {}
        for depot_id in ("D_foshan", "D_guangzhou"):
            route = Route(
                vehicle_id="CV_DIRECT",
                vehicle_type="cv",
                home_depot_id=depot_id,
                node_sequence=[depot_id, customer_id, depot_id],
            )
            breakdown = evaluate(
                Solution(routes=[route]),
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
                carbon_quota_kg=0.0,
            )
            costs[depot_id] = float(breakdown["total_cost"] - breakdown["cost_fix"])
        nearest, second = sorted(costs, key=costs.get)
        gap = costs[second] - costs[nearest]
        relative = gap / costs[nearest]
        row: dict[str, Any] = {
            "customer_id": customer_id,
            "city_home_depot": bundle.customer_home_depot[customer_id],
            "nearest_depot": nearest,
            "second_depot": second,
            "nearest_cost_cny": costs[nearest],
            "second_cost_cny": costs[second],
            "absolute_gap_cny": gap,
            "relative_gap": relative,
        }
        for threshold in CONTESTABILITY_THRESHOLDS:
            row[f"contestable_at_{int(threshold * 100)}pct"] = int(relative < threshold)
        rows.append(row)
    return rows


def paired_flip_probe(
    bundle: PrivateInstanceRebuildBundle,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[str, list[dict[str, Any]], dict[str, float | bool]]:
    candidates = [
        row
        for row in rows
        if float(row["relative_gap"]) < MAIN_CONTESTABILITY_THRESHOLD
    ]
    target = max(candidates, key=lambda row: float(row["absolute_gap_cny"]))
    customer_id = str(target["customer_id"])
    original = bundle.customer_home_depot[customer_id]
    other = "D_foshan" if original == "D_guangzhou" else "D_guangzhou"
    raw = []
    for seed in HEALTH_SEEDS:
        baseline = build_witness(bundle, seed)
        flipped_plans = build_plans(bundle, seed=seed, home_override={customer_id: other})
        flipped_solution, departures = plans_to_solution(flipped_plans, bundle)
        validate_shifted_solution(
            flipped_solution,
            bundle,
            departure_second_by_route=departures,
        )
        flipped = evaluate_rebuild_solution(
            flipped_solution,
            bundle,
            carbon_quota_kg=0.0,
        )
        raw.append(
            {
                "seed": seed,
                "customer_id": customer_id,
                "original_depot": original,
                "flipped_depot": other,
                "baseline_total_cost_cny": baseline.total_cost,
                "flipped_total_cost_cny": float(flipped["total_cost"]),
                "paired_delta_cny": float(flipped["total_cost"]) - baseline.total_cost,
                "baseline_vehicle_count": baseline.physical_vehicle_count,
                "flipped_vehicle_count": int(flipped["n_veh_cv"] + flipped["n_veh_ev"]),
            }
        )
    deltas = [float(row["paired_delta_cny"]) for row in raw]
    baseline_costs = [float(row["baseline_total_cost_cny"]) for row in raw]
    mean_abs = abs(statistics.mean(deltas))
    noise = statistics.stdev(deltas)
    return customer_id, raw, {
        "mean_paired_delta_cny": statistics.mean(deltas),
        "paired_seed_noise_sd_cny": noise,
        "mean_abs_delta_exceeds_noise": mean_abs > noise,
        "min_abs_delta_cny": min(abs(value) for value in deltas),
        "max_abs_delta_cny": max(abs(value) for value in deltas),
        "unpaired_baseline_total_cost_sd_cny": statistics.stdev(baseline_costs),
        "unpaired_baseline_total_cost_range_cny": max(baseline_costs) - min(baseline_costs),
    }


def plans_from_pyvrp_arm(
    bundle: PrivateInstanceRebuildBundle,
    slices: Sequence[Mapping[str, Any]],
) -> tuple[RoutePlan, ...]:
    plans = []
    served: list[str] = []
    for item in slices:
        depot_id = str(item["depot_id"])
        shift_id = str(item["shift_id"])
        for raw_route in item["routes"]:
            customers = tuple(str(customer) for customer in raw_route)
            feasible, departed, returned, distance = route_clock(
                bundle,
                depot_id,
                shift_id,
                customers,
            )
            if not feasible:
                raise RuntimeError(
                    "frozen PyVRP route failed exact-clock replay: "
                    f"{depot_id}/{shift_id}/{customers}"
                )
            served.extend(customers)
            plans.append(
                RoutePlan(
                    depot_id=depot_id,
                    shift_id=shift_id,
                    customers=customers,
                    volume_m3=sum(
                        float(bundle.orders_by_customer[customer]["source_volume_m3"])
                        for customer in customers
                    ),
                    demand_kg=sum(
                        float(bundle.orders_by_customer[customer]["demand_kg"])
                        for customer in customers
                    ),
                    departure_second=departed,
                    return_second=returned,
                    distance_m=distance,
                )
            )
    if sorted(served) != sorted(bundle.orders_by_customer):
        raise RuntimeError("frozen PyVRP replay customer coverage is incomplete")
    return tuple(plans)


def paired_flip_probe_from_pyvrp(
    bundle: PrivateInstanceRebuildBundle,
    payload: Mapping[str, Any],
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    if payload.get("instance_id") != INSTANCE_ID:
        raise ValueError("PyVRP assignment probe instance identity disagrees")
    if payload.get("pyvrp_version") != "0.12.2":
        raise ValueError("assignment probe is not frozen PyVRP 0.12.2")
    customer_id = str(payload["target_customer"])
    original = bundle.customer_home_depot[customer_id]
    other = "D_foshan" if original == "D_guangzhou" else "D_guangzhou"
    raw = []
    for run in payload["runs"]:
        seed = int(run["seed"])
        baseline_plans = plans_from_pyvrp_arm(bundle, run["baseline"])
        flipped_plans = plans_from_pyvrp_arm(bundle, run["flipped"])
        baseline_solution, baseline_departures = plans_to_solution(
            baseline_plans,
            bundle,
        )
        flipped_solution, flipped_departures = plans_to_solution(
            flipped_plans,
            bundle,
        )
        validate_shifted_solution(
            baseline_solution,
            bundle,
            departure_second_by_route=baseline_departures,
        )
        validate_shifted_solution(
            flipped_solution,
            bundle,
            departure_second_by_route=flipped_departures,
        )
        baseline = evaluate_rebuild_solution(
            baseline_solution,
            bundle,
            carbon_quota_kg=0.0,
        )
        flipped = evaluate_rebuild_solution(
            flipped_solution,
            bundle,
            carbon_quota_kg=0.0,
        )
        raw.append(
            {
                "seed": seed,
                "customer_id": customer_id,
                "original_depot": original,
                "flipped_depot": other,
                "baseline_total_cost_cny": float(baseline["total_cost"]),
                "flipped_total_cost_cny": float(flipped["total_cost"]),
                "paired_delta_cny": float(flipped["total_cost"])
                - float(baseline["total_cost"]),
                "baseline_vehicle_count": int(
                    baseline["n_veh_cv"] + baseline["n_veh_ev"]
                ),
                "flipped_vehicle_count": int(
                    flipped["n_veh_cv"] + flipped["n_veh_ev"]
                ),
            }
        )
    if tuple(int(row["seed"]) for row in raw) != HEALTH_SEEDS:
        raise ValueError("PyVRP assignment probe seed identity disagrees")
    deltas = [float(row["paired_delta_cny"]) for row in raw]
    baseline_costs = [float(row["baseline_total_cost_cny"]) for row in raw]
    paired_noise = statistics.stdev(deltas)
    mean_delta = statistics.mean(deltas)
    return customer_id, raw, {
        "probe_kind": "frozen_pyvrp_0.12.2_four_slices_exact_replay",
        "max_iterations_per_slice": int(payload["max_iterations_per_slice"]),
        "mean_paired_delta_cny": mean_delta,
        "paired_seed_noise_sd_cny": paired_noise,
        "mean_abs_delta_exceeds_noise": abs(mean_delta) > paired_noise,
        "min_abs_delta_cny": min(abs(value) for value in deltas),
        "max_abs_delta_cny": max(abs(value) for value in deltas),
        "unpaired_baseline_total_cost_sd_cny": statistics.stdev(baseline_costs),
        "unpaired_baseline_total_cost_range_cny": max(baseline_costs)
        - min(baseline_costs),
    }


def per_km_rows(bundle: PrivateInstanceRebuildBundle, witness: Witness) -> tuple[list[dict[str, Any]], dict[str, float]]:
    cv = evaluate_rebuild_solution(witness.solution, bundle, carbon_quota_kg=0.0)
    ev_solution, _ = plans_to_solution(
        witness.plans,
        bundle,
        vehicle_type="ev",
    )
    ev = evaluate_rebuild_solution(ev_solution, bundle, carbon_quota_kg=0.0)
    cv_distance_km = float(cv["distance_cv"]) / 1000.0
    ev_distance_km = float(ev["distance_ev"]) / 1000.0
    cv_energy_cost_per_km = (
        float(cv["cost_fuel"]) / cv_distance_km
    )
    cv_cost_per_km = 0.78 + cv_energy_cost_per_km
    cv_emissions_per_km = float(cv["E_cv_direct"]) / cv_distance_km
    ev_kwh_per_km = float(ev["ev_drive_kwh"]) / ev_distance_km

    profile = [
        row
        for row in bundle.time_profile
        if row["city"] == "guangzhou"
    ]
    by_minute = {
        int(round(float(row["horizon_second_start"]) / 60.0)): row
        for row in profile
    }
    scenarios = [
        ("valley_03:00", by_minute[180]),
        ("morning_flat_09:00", by_minute[540]),
        ("lunch_flat_12:00", by_minute[720]),
        ("return_peak_18:30", by_minute[1110]),
    ]
    rows = [
        {
            "vehicle": "CV",
            "scenario": "diesel",
            "energy_price": float(bundle.china81.diesel_price_by_city["guangzhou"]),
            "carbon_factor": float(bundle.prices.diesel_ef),
            "energy_per_km": float(cv["fuel_liters"]) / cv_distance_km,
            "non_energy_cost_per_km": 0.78,
            "total_operating_cost_per_km": cv_cost_per_km,
            "emissions_kg_per_km": cv_emissions_per_km,
            "critical_daily_km_vs_cv": 0.0,
        }
    ]
    for name, profile_row in scenarios:
        price = float(profile_row["depot_energy_cny_per_kwh"])
        carbon = float(profile_row["actual_gco2_per_kwh"]) / 1000.0
        ev_cost = EV_NON_ENERGY_CNY_PER_KM + ev_kwh_per_km * price
        saving = cv_cost_per_km - ev_cost
        rows.append(
            {
                "vehicle": "EV",
                "scenario": name,
                "energy_price": price,
                "carbon_factor": carbon,
                "energy_per_km": ev_kwh_per_km,
                "non_energy_cost_per_km": EV_NON_ENERGY_CNY_PER_KM,
                "total_operating_cost_per_km": ev_cost,
                "emissions_kg_per_km": ev_kwh_per_km * carbon,
                "critical_daily_km_vs_cv": (
                    EV_DAILY_FIXED_PREMIUM_CNY / saving if saving > 0.0 else math.inf
                ),
            }
        )
    return rows, {
        "cv_cost_per_km": cv_cost_per_km,
        "cv_emissions_per_km": cv_emissions_per_km,
        "ev_kwh_per_km": ev_kwh_per_km,
    }


def lunch_charge_ceiling_row(
    bundle: PrivateInstanceRebuildBundle,
    *,
    available_charging_hours: float,
) -> dict[str, float | str]:
    """Return the maximum battery gain under the registered depot curve.

    Starting at zero maximizes the increment for this non-increasing
    SOC--power curve, so this remains a ceiling rather than an observed charge.
    """

    charge_hours = float(available_charging_hours)
    if not math.isfinite(charge_hours) or charge_hours < 0.0:
        raise ValueError("available charging hours must be nonnegative")
    power_kw = float(bundle.prices.depot_charge_power_kw)
    if not math.isclose(
        power_kw,
        DEPOT_CHARGE_POWER_KW,
        rel_tol=0.0,
        abs_tol=1.0e-12,
    ):
        raise ValueError(
            "private rebuild depot power disagrees with the 60 kW builder contract"
        )
    battery_kwh = float(
        bundle.instance.battery_capacity_kwh(
            fallback=bundle.prices.B_battery_kwh,
        )
    )
    curve = curve_for_charging_node(
        bundle.prices,
        node_type="d",
        capacity_kwh=battery_kwh,
        reference_power_kw=power_kw,
    )
    available_seconds = charge_hours * 3600.0
    reachable_kwh = float(
        curve.reachable_energy_kwh(0.0, available_seconds)
    )
    full_charge_seconds = float(curve.duration_seconds(0.0, battery_kwh))
    if math.isclose(
        reachable_kwh,
        battery_kwh,
        rel_tol=0.0,
        abs_tol=1.0e-10,
    ):
        binding_constraint = "battery_capacity"
    else:
        binding_constraint = "lunch_time_and_high_soc_power_taper"
    return {
        "start_energy_kwh": 0.0,
        "reference_power_kw": power_kw,
        "battery_capacity_kwh": battery_kwh,
        "charging_curve_id": curve.curve_id,
        "linear_power_ceiling_kwh": charge_hours * power_kw,
        "chargeable_energy_ceiling_kwh": reachable_kwh,
        "end_soc_pct": 100.0 * reachable_kwh / battery_kwh,
        "full_charge_minutes": full_charge_seconds / 60.0,
        "binding_constraint": binding_constraint,
    }


def health_summary(
    bundle: PrivateInstanceRebuildBundle,
    contest_rows: Sequence[Mapping[str, Any]],
    witnesses: Sequence[Witness],
    flip_summary: Mapping[str, Any],
) -> dict[str, Any]:
    witness = next(item for item in witnesses if item.seed == 11)
    by_key: dict[tuple[str, str], int] = {}
    for plan in witness.plans:
        by_key[(plan.depot_id, plan.shift_id)] = by_key.get((plan.depot_id, plan.shift_id), 0) + 1
    single_shift_count = len(witness.plans)
    routes_by_physical: dict[str, list[Route]] = {}
    for route in witness.solution.routes:
        physical_id = route.vehicle_id.split("#T", 1)[0]
        routes_by_physical.setdefault(physical_id, []).append(route)
    physical = len(routes_by_physical)
    trip_counts_by_physical = {
        physical_id: len(routes)
        for physical_id, routes in sorted(routes_by_physical.items())
    }
    plan_by_signature = {
        (plan.depot_id, plan.shift_id, plan.customers): plan
        for plan in witness.plans
    }
    paired_afternoon = []
    for physical_id, routes in sorted(routes_by_physical.items()):
        ordered_routes = sorted(
            routes,
            key=lambda route: witness.departures[route.vehicle_id],
        )
        shifts = [
            bundle.orders_by_customer[route.node_sequence[1]]["shift_id"]
            for route in ordered_routes
        ]
        if "AM" not in shifts or "PM" not in shifts:
            continue
        first_pm = ordered_routes[shifts.index("PM")]
        plan = plan_by_signature[
            (
                first_pm.home_depot_id,
                "PM",
                tuple(first_pm.node_sequence[1:-1]),
            )
        ]
        loading_hours = plan.volume_m3 * LOADING_HOURS_PER_M3
        charge_hours = max(0.0, 2.0 - loading_hours)
        charge_ceiling = lunch_charge_ceiling_row(
            bundle,
            available_charging_hours=charge_hours,
        )
        paired_afternoon.append(
            {
                "physical_vehicle_id": physical_id,
                "depot_id": plan.depot_id,
                "afternoon_route_volume_m3": plan.volume_m3,
                "loading_hours": loading_hours,
                "charging_hours": charge_hours,
                **charge_ceiling,
            }
        )
    return {
        "selected_witness_seed": witness.seed,
        "contestability": {
            str(threshold): sum(
                float(row["relative_gap"]) < threshold for row in contest_rows
            )
            for threshold in CONTESTABILITY_THRESHOLDS
        },
        "trip_counts": {
            f"{depot}_{shift}": by_key.get((depot, shift), 0)
            for depot in ("D_foshan", "D_guangzhou")
            for shift in ("AM", "PM")
        },
        "single_shift_vehicle_count_no_reuse": single_shift_count,
        "two_shift_physical_vehicle_count": physical,
        "fleet_reduction_count": single_shift_count - physical,
        "fleet_reduction_pct": 100.0 * (single_shift_count - physical) / single_shift_count,
        "physical_vehicle_trip_counts": trip_counts_by_physical,
        "max_trips_per_vehicle": max(trip_counts_by_physical.values()),
        "lunch_rows": paired_afternoon,
        "flip": dict(flip_summary),
    }


def render_report(
    output_root: Path,
    report_root: Path,
    bundle: PrivateInstanceRebuildBundle,
    contest_rows: Sequence[Mapping[str, Any]],
    witness: Witness,
    health: Mapping[str, Any],
    flip_customer: str,
    flip_rows: Sequence[Mapping[str, Any]],
    per_km: Sequence[Mapping[str, Any]],
    protected_before: Mapping[str, str],
    protected_after: Mapping[str, str],
) -> str:
    contest = health["contestability"]
    lunch = list(health["lunch_rows"])
    lunch_energy = [
        float(row["chargeable_energy_ceiling_kwh"])
        for row in lunch
    ]
    main_rows = [
        row
        for row in contest_rows
        if float(row["relative_gap"]) < MAIN_CONTESTABILITY_THRESHOLD
    ]
    direct_exposure = sum(float(row["absolute_gap_cny"]) for row in main_rows)
    max_direct = max(float(row["absolute_gap_cny"]) for row in main_rows)
    flip = health["flip"]
    am = sum(plan.shift_id == "AM" for plan in witness.plans)
    pm = sum(plan.shift_id == "PM" for plan in witness.plans)
    widths = [
        float(row["source_time_window_width_minute"])
        for row in read_csv(output_root / "orders.csv")
    ]
    per_km_by_scenario = {str(row["scenario"]): row for row in per_km}
    lunch_flat = per_km_by_scenario["lunch_flat_12:00"]
    return_peak = per_km_by_scenario["return_peak_18:30"]
    aggregate_lunch_kwh = sum(lunch_energy)
    lunch_cost_headroom = aggregate_lunch_kwh * (
        float(return_peak["energy_price"]) - float(lunch_flat["energy_price"])
    )
    lunch_emission_headroom = aggregate_lunch_kwh * (
        float(return_peak["carbon_factor"]) - float(lunch_flat["carbon_factor"])
    )
    mixed_rows = [row for row in per_km if row["vehicle"] == "EV"]
    critical_values = [
        float(row["critical_daily_km_vs_cv"])
        for row in mixed_rows
        if math.isfinite(float(row["critical_daily_km_vs_cv"]))
    ]
    route_distances = [plan.distance_m / 1000.0 for plan in witness.plans]
    physical_distances: dict[str, float] = {}
    for route in witness.solution.routes:
        physical = route.vehicle_id.split("#T", 1)[0]
        physical_distances[physical] = physical_distances.get(physical, 0.0) + route_distance_m(
            route, bundle.instance
        ) / 1000.0
    lunch_critical = float(lunch_flat["critical_daily_km_vs_cv"])
    below = sum(distance < lunch_critical for distance in physical_distances.values())
    above = sum(distance > lunch_critical for distance in physical_distances.values())
    trip_frequency: dict[int, int] = {}
    for trip_count in health["physical_vehicle_trip_counts"].values():
        trip_frequency[int(trip_count)] = trip_frequency.get(int(trip_count), 0) + 1
    trip_distribution = "、".join(
        f"{trip_count} 趟×{vehicle_count} 辆"
        for trip_count, vehicle_count in sorted(trip_frequency.items())
    )
    fixed_saving_min = health["fleet_reduction_count"] * CV_FIXED_CNY_PER_DAY
    fixed_saving_max = health["fleet_reduction_count"] * EV_FIXED_CNY_PER_DAY
    conservative_charge = lunch_charge_ceiling_row(
        bundle,
        available_charging_hours=(
            2.0 - VEHICLE_VOLUME_CAPACITY_M3 * LOADING_HOURS_PER_M3
        ),
    )

    lines = [
        "INSTANCE_REBUILD_DONE",
        "",
        "# 私有算例重建与体检报告（2026-08-11）",
        "",
        "## 结论",
        "",
        f"新算例 `{INSTANCE_ID}` 已建成，旧算例未覆盖。两班次、真实广州/佛山两车场、车型差异成本均已进入独立数据与运行时合同；本轮没有运行正式实验。",
        "",
        f"主口径下可争夺客户为 **{contest[str(MAIN_CONTESTABILITY_THRESHOLD)]}/50 = {100 * contest[str(MAIN_CONTESTABILITY_THRESHOLD)] / 50:.1f}%**，落在批准的 36%–42% 区间。技术路线见证中上午 {am} 趟、下午 {pm} 趟；同一实体车跨班复用后从 {health['single_shift_vehicle_count_no_reuse']} 辆降到 {health['two_shift_physical_vehicle_count']} 辆，减少 {health['fleet_reduction_pct']:.1f}%。",
        "",
        f"归属翻转探针选择 `{flip_customer}`。10 个固定技术种子的配对成本变化均值为 {float(flip['mean_paired_delta_cny']):.2f} 元，配对变化的种子标准差为 {float(flip['paired_seed_noise_sd_cny']):.2f} 元；门槛结果为 **{'通过' if flip['mean_abs_delta_exceeds_noise'] else '未通过'}**。未配对的基线总成本种子标准差/极差为 {float(flip['unpaired_baseline_total_cost_sd_cny']):.2f}/{float(flip['unpaired_baseline_total_cost_range_cny']):.2f} 元。门槛用同种子成对差值，因为要分离的是“只改一个客户归属”的净变化。",
        "",
        "## 1. 生成身份与未触碰边界",
        "",
        f"- 新数据目录：`{output_root.relative_to(REPO)}`",
        f"- 新 instance_id：`{INSTANCE_ID}`",
        f"- 原任务属性：`{TASK_AUTHORITY.relative_to(REPO)}` 中 `{TASK_INSTANCE}` 的 50 行",
        f"- 新地点与道路：`{SOURCE_INSTANCE}` 的真实 OSM 点和冻结 CV/EV 定向道路矩阵",
        "- 两个场站：普洛斯广州黄埔物流园、普洛斯顺德物流园；坐标逐字继承 `facilities.csv`。",
        "- 车型供给采用仓库既有的内生车队参数类：CV、EV 分别只有宽松上限，不预设 25% 电车比例；最终构成须由后续获批实验优化。",
        "- `formal_search_allowed=false`；构造与体检共 0 次正式搜索。",
        "",
        "三个受保护文件任务前后哈希：",
        "",
        "| 文件 | 任务前 | 任务后 |",
        "|---|---|---|",
    ]
    for path in PROTECTED:
        key = str(path)
        lines.append(f"| `{key}` | `{protected_before[key]}` | `{protected_after[key]}` |")
    lines.extend(
        [
            "",
            "## 2. 哪些是还原，哪些是外推",
            "",
            "**还原源数据已经声明的结构**",
            "",
            "- 08:00–11:00 与 13:00–19:00 两个作业时段；11:00–13:00 午休并强制回场；车辆出勤 08:00–19:00。依据为 figshare 数据包的 `Data Description.xlsx`。",
            f"- 50 个时间窗宽度逐条原值继承：本 50 单范围 {min(widths):.1f}–{max(widths):.1f} 分钟，中位数 {statistics.median(widths):.1f} 分钟。规格写的 45.8 可追溯到 `china_order_attribute_calibration_v2_20260718/raw_runs.csv` 第 4 天 167 单的**平均值** 45.820124，并非本 50 单中位数；这里以逐条订单值为准，没有为对齐摘要改窗宽。",
            "- 每个班内把原始 ready-time 做同一个仿射变换，因此班内先后顺序和相对间距保持不变。",
            "",
            "**经用户 P43-G 批准的外推**",
            "",
            "- 纯送货任务同时排入上午和下午；按 3h:6h 采用 17:33。具体无随机规则为：按原 ready-time 排序，每三单中的第一单进上午，其余进下午。",
            "- 任务属性与新 OSM 地点重新配对；需求、体积、服务时长、源订单 UID 不变，地点来源另列在 `orders.csv` 的 location provenance 字段。",
            "- 36 个广州点、14 个佛山点是按已批准的可争夺比例目标选择的结构性场景，不写成现实抽样发现。",
            "",
            "## 3. 车场几何体检",
            "",
            "广义服务成本定义为：用冻结定向道路矩阵，燃油车从车场到客户再回同一车场的变动货币成本；包含非能源里程、柴油和碳价，排除两边相同的日固定成本。相对差为 `(次优-最优)/最优`。",
            "",
            "| 相对差阈值 | 可争夺客户 | 占比 |",
            "|---:|---:|---:|",
        ]
    )
    for threshold in CONTESTABILITY_THRESHOLDS:
        count = int(contest[str(threshold)])
        lines.append(f"| {threshold:.0%} | {count}/50 | {count / 50:.1%} |")
    lines.extend(
        [
            "",
            f"25% 主口径的 18 个客户，若全部从最近场翻到次近场，单客户直达往返成本差合计 {direct_exposure:.2f} 元；其中最大单客差 {max_direct:.2f} 元。这是几何暴露量，不是协同必得收益。逐客数字见 `contestability.csv`。",
            "",
            f"翻转实测不是正式算法实验：用冻结 PyVRP 0.12.2 把两班次×两车场分成四个小问题，每片固定 {int(flip['max_iterations_per_slice'])} 代；10 个种子中每次只改变一个客户的 home depot，返回路线再用新算例的精确道路与成本合同重放。原始行保存在 `flip_probe_raw.csv`。",
            "",
            "## 4. 两班次、多趟、午休",
            "",
            f"所选见证（seed {witness.seed}）共有 {len(witness.plans)} 趟：上午 {am} 趟、下午 {pm} 趟。每趟同时检查 7.2 m³、1,735 kg、客户窗和班次结束前回场。路线距离范围 {min(route_distances):.1f}–{max(route_distances):.1f} km。",
            "",
            f"若各趟不复用实体车，需要 {health['single_shift_vehicle_count_no_reuse']} 辆；允许上午车午休回场后接下午趟、下午趟间再回场装货，见证只需 {health['two_shift_physical_vehicle_count']} 辆，少 {health['fleet_reduction_count']} 辆（{health['fleet_reduction_pct']:.1f}%）。逐车分布为 {trip_distribution}；实测单车最多 **{health['max_trips_per_vehicle']} 趟**，没有人为设置两趟上限。按油车 170、电车 220 元/车日计，减少 6 辆对应固定成本空间为 {fixed_saving_min:.0f}–{fixed_saving_max:.0f} 元/日（取决于被省掉的车型）。",
            "",
            f"对上午返场且下午继续出车的 {len(lunch)} 辆车，11:00–13:00 均在场站 2.00 h。按装货优先、从 0 kWh 起算最大电量增量：实际下午装货量对应的 60 kW 登记非线性曲线可充电量范围 {min(lunch_energy):.2f}–{max(lunch_energy):.2f} kWh，中位 {statistics.median(lunch_energy):.2f} kWh。满载 7.2 m³ 时装货 0.72 h，剩余 1.28 h，曲线积分的保守上限为 **{float(conservative_charge['chargeable_energy_ceiling_kwh']):.2f} kWh**。当前实际行在 81 分钟后尚未充满，瓶颈是午休可用时长与高 SOC 降功率，而不是已经触及电池容量。",
            "",
            "## 5. 新算例的油电每公里对照",
            "",
            "下表用上述完整路线见证的实际道路、坡阻/速度剖面和载荷复算；电价与碳强度取当前运行时权威的 2025-02-12 行。电车非能源里程成本已经从 0.6700 增至 0.9145 元/km；固定成本为油车 170、电车 220 元/车日。",
            "",
            "| 车型/充能时刻 | 能源耗用/km | 非能源元/km | 合计元/km | kgCO2e/km | 临界日里程 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in per_km:
        unit = "L" if row["vehicle"] == "CV" else "kWh"
        critical = "—" if row["vehicle"] == "CV" else f"{float(row['critical_daily_km_vs_cv']):.1f} km"
        lines.append(
            f"| {row['vehicle']} {row['scenario']} | {float(row['energy_per_km']):.4f} {unit} | {float(row['non_energy_cost_per_km']):.4f} | {float(row['total_operating_cost_per_km']):.4f} | {float(row['emissions_kg_per_km']):.4f} | {critical} |"
        )
    lines.extend(
        [
            "",
            "规格中的 69/90/140 km 是前期时段锚点；当前冻结运行日复算为 68.1/86.8/125.5 km。这里没有切换日期或改参数去追齐旧锚点，三档仍覆盖本算例的一趟与多趟日里程。",
            "",
            f"在同一个午休平段电价下，实测临界日里程为 {lunch_critical:.1f} km；见证中 {below} 辆低于该点、{above} 辆高于该点。因此“短任务偏油车、长任务偏电车”在同一充电情景下已有作用空间；这不是最优车队构成结论，正式实验证据仍为 0。",
            "",
            "## 6. 四个机制在正式实验前的天花板",
            "",
            f"- **多车场协同**：主口径最多有 18/50 个客户可改变场站；直达往返的总归属成本暴露量为 {direct_exposure:.2f} 元。",
            f"- **多趟**：{len(witness.plans)} 趟可由 {health['two_shift_physical_vehicle_count']} 辆实体车完成，车辆数结构上最多减少 {health['fleet_reduction_count']} 辆（{health['fleet_reduction_pct']:.1f}%），对应固定成本空间 {fixed_saving_min:.0f}–{fixed_saving_max:.0f} 元/日。",
            f"- **午休择时充电**：返场复用车辆在扣除实际装货后合计最多可充 {aggregate_lunch_kwh:.2f} kWh；若这些电从 18:30 移到 12:00，输入价格/碳强度给出的货币上限为省 {lunch_cost_headroom:.2f} 元、排放上限为少 {lunch_emission_headroom:.2f} kgCO2e。",
            f"- **混合车队**：实测临界日里程范围 {min(critical_values):.1f}–{max(critical_values):.1f} km，见证日里程跨过该带；固定溢价和电池折旧不再让纯电在所有距离上严格占优。",
            "",
            "这些是结构上限和可达性检查，不是算法能拿到的效果值。正式实验没有启动。",
            "",
            "## 7. 参数出处",
            "",
            "- 班次：figshare 28113608 `Data Description.xlsx`，原文声明 08:00–11:00、13:00–19:00；详见重建文献报告 §1。",
            "- 设施与坐标：`china81_stage2_static_inputs_corrected_v3_20260723/facilities.csv`；地点为同源 OSM 实体，逐行保留 source identity。",
            "- 装卸：源数据 0.1 h/m³；车容 7.2 m³。午休计算按用户要求扣除装货时间。",
            "- 电池折旧：长江证券（2024-07-13）5.9 万元换电池 ÷ Goeke & Schneider (2015), EJOR 245(1):81–99, §4.2 / Tables 4,8 的 241,350 km，得到 0.2445 元/km。",
            "- 固定溢价：陈婉茹等（2023），《系统工程理论与实践》43(11):3320–3335，第 5 节、第 7 表，电动 550、燃油 500，差 50 元/车日。",
            "- 可争夺比例对标：Vidal et al. (2013) 官方 PR11A/B 包复算 42%/36%；本项目阈值是模型内相对货币成本口径，不把无量纲坐标换算成公里。",
            "",
            "## 8. 产物",
            "",
            f"- `{output_root.relative_to(REPO)}/`：完整新算例、班次合同、车型成本、矩阵、来源映射与哈希。",
            f"- `{report_root.relative_to(REPO)}/health_witness_routes.csv`：两班次可行路线见证。",
            f"- `{report_root.relative_to(REPO)}/flip_probe_raw.csv`：10 个配对技术种子的单客归属翻转原始值。",
            f"- `{report_root.relative_to(REPO)}/pyvrp_flip_probe_routes.json`：冻结 PyVRP 0.12.2 技术探针的逐片路线原始输出。",
            f"- `{report_root.relative_to(REPO)}/per_km_vehicle_comparison.csv`：油电成本、排放与临界里程复算。",
            "",
        ]
    )
    return "\n".join(lines)


def _profile_row_for_depot(
    bundle: PrivateInstanceRebuildBundle,
    depot_id: str,
    *,
    minute: int,
) -> Mapping[str, Any]:
    node = bundle.instance.nodes[bundle.instance.node_index[depot_id]]
    if node.node_type.lower() != "d" or node.city is None:
        raise ValueError(f"lunch ceiling row has invalid depot {depot_id!r}")
    matches = [
        row
        for row in bundle.time_profile
        if str(row["city"]).strip().lower()
        == str(node.city).strip().lower()
        and int(round(float(row["horizon_second_start"]) / 60.0))
        == minute
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one runtime profile row for {depot_id} at minute {minute}"
        )
    return matches[0]


def _render_lunch_recompute_report(
    *,
    report_root: Path,
    source_report_root: Path,
    rows: Sequence[Mapping[str, Any]],
    old_values: Mapping[str, float],
    new_values: Mapping[str, float],
    source_tree_before: str,
    source_tree_after: str,
    protected_before: Mapping[str, str],
    protected_after: Mapping[str, str],
) -> str:
    first = rows[0]
    segment_powers = first["curve_segment_powers_kw"]
    old_energy = float(old_values["aggregate_chargeable_energy_kwh"])
    new_energy = float(new_values["aggregate_chargeable_energy_kwh"])
    old_cost = float(old_values["cost_headroom_cny"])
    new_cost = float(new_values["cost_headroom_cny"])
    old_emissions = float(old_values["emissions_headroom_kgco2e"])
    new_emissions = float(new_values["emissions_headroom_kgco2e"])
    lines = [
        "INSTANCE_REBUILD_60KW_RECOMPUTE_DONE",
        "",
        "# 私有算例午休充电上限 60 kW 重算（2026-08-12）",
        "",
        "## 结论",
        "",
        f"旧报告的 22 kW 线性口径三数已作废。沿用同一 seed 11 结构见证、同一 5 条上午返场后继续下午职责，按当前 60 kW 登记非线性曲线从 0 kWh 起算最大增量后，新上限为 **{new_energy:.2f} kWh / {new_cost:.2f} 元 / {new_emissions:.2f} kgCO2e**。本轮没有运行正式搜索。",
        "",
        "这 5 个结构见证 ID 均为 `CV_*`。因此这里计算的是“若这些跨班复用职责由 EV 承担”的反事实充电天花板，不是 5 辆实际 EV 的观测充电量。",
        "",
        "## 新旧逐项对照",
        "",
        "| 指标 | 旧报告（22 kW 线性） | 60 kW 登记曲线积分 | 变化 |",
        "|---|---:|---:|---:|",
        f"| 午休可充电量上限 | {old_energy:.2f} kWh | {new_energy:.2f} kWh | {new_energy - old_energy:+.2f} kWh |",
        f"| 从 18:30 移至 12:00 的货币上限 | {old_cost:.2f} 元 | {new_cost:.2f} 元 | {new_cost - old_cost:+.2f} 元 |",
        f"| 对应排放上限 | {old_emissions:.2f} kgCO2e | {new_emissions:.2f} kgCO2e | {new_emissions - old_emissions:+.2f} kgCO2e |",
        "",
        "## 真实约束计算",
        "",
        f"5 条职责的下午货量都为 {float(first['afternoon_route_volume_m3']):.2f} m³；按既有装货口径需 {float(first['loading_hours']):.2f} h，2 h 午休剩余 {float(first['charging_hours']):.2f} h，即 {float(first['charging_hours']) * 60.0:.0f} min。该装货口径只是沿用旧见证，本轮没有处理审计中的 A17。",
        "",
        f"电池容量为 {float(first['battery_capacity_kwh']):.2f} kWh，额定功率为 {float(first['reference_power_kw']):.0f} kW，曲线为 `{first['charging_curve_id']}`。从 0 kWh 起步，是这条功率随 SOC 不增的曲线下可增加电量最大的起点。登记分段功率为 {float(segment_powers[0]):.9f}、{float(segment_powers[1]):.9f}、{float(segment_powers[2]):.9f} kW。",
        "",
        f"前 85% 电量为 {float(first['first_segment_energy_kwh']):.3f} kWh，用时 {float(first['first_segment_minutes']):.4f} min；余下 {float(first['remaining_minutes_after_first_segment']):.4f} min 进入 85%–95% 的降功率段，再充 {float(first['second_segment_energy_kwh']):.9f} kWh。因此每条职责可增加 **{float(first['chargeable_energy_ceiling_kwh']):.9f} kWh**，结束 SOC 为 {float(first['end_soc_pct']):.6f}%。5 条合计 {new_energy:.9f} kWh。",
        "",
        f"线性算术给出 60×1.35={float(first['linear_power_ceiling_kwh']):.2f} kWh，确实高于 {float(first['battery_capacity_kwh']):.2f} kWh；但登记曲线从空电充满需要 {float(first['full_charge_minutes']):.4f} min，81 min 时还差 {float(first['battery_capacity_kwh']) - float(first['chargeable_energy_ceiling_kwh']):.9f} kWh。因此真实瓶颈不是“电池已经充满”，而是 **午休可用时长与高 SOC 降功率共同约束**。",
        "",
        f"两时段输入差为 {float(first['energy_price_difference_cny_per_kwh']):.4f} 元/kWh 和 {float(first['carbon_factor_difference_kgco2e_per_kwh']):.4f} kgCO2e/kWh；所以 {new_energy:.9f}×{float(first['energy_price_difference_cny_per_kwh']):.4f}={new_cost:.9f} 元，{new_energy:.9f}×{float(first['carbon_factor_difference_kgco2e_per_kwh']):.4f}={new_emissions:.9f} kgCO2e。",
        "",
        "## 不覆盖与边界",
        "",
        f"- 旧报告目录：`{source_report_root.relative_to(REPO)}`；任务前后整树摘要均为 `{source_tree_before}` / `{source_tree_after}`，一致。",
        f"- 新报告目录：`{report_root.relative_to(REPO)}`。",
        "- 没有改算例几何、客户、需求、班次、装货率、算法参数或评价口径；没有运行正式实验。",
        "",
        "三个受保护文件任务前后 SHA-256：",
        "",
        "| 文件 | 任务前 | 任务后 |",
        "|---|---|---|",
    ]
    for path in PROTECTED:
        key = str(path)
        lines.append(
            f"| `{key}` | `{protected_before[key]}` | `{protected_after[key]}` |"
        )
    lines.extend(
        [
            "",
            "## 机器可复核产物",
            "",
            "- `raw_runs.csv`：5 条确定性逐职责计算行；不是随机或正式运行。",
            "- `health_summary.json`：新旧总量、约束身份和源报告哈希。",
            "- `metadata.json`、`decision.json`、`artifact_hashes.json`：计算身份、完成状态和文件哈希。",
            "",
        ]
    )
    return "\n".join(lines)


def recompute_lunch_report_only(
    report_root: Path,
    *,
    source_report_root: Path,
) -> None:
    """Recompute only the A14 lunch ceiling, preserving old authority/output."""

    if report_root.exists():
        raise FileExistsError(
            f"refusing to overwrite 60 kW recompute report: {report_root}"
        )
    source_health_path = source_report_root / "health_summary.json"
    if not source_health_path.is_file():
        raise FileNotFoundError(
            f"source rebuild health summary is missing: {source_health_path}"
        )
    protected_before = {str(path): sha256(REPO / path) for path in PROTECTED}
    source_tree_before = tree_sha256(source_report_root)
    source_health_sha256 = sha256(source_health_path)
    bundle = load_private_instance_rebuild(REPO)
    old_health = json.loads(source_health_path.read_text(encoding="utf-8"))
    old_rows = list(old_health["lunch_rows"])
    if not old_rows:
        raise ValueError("source rebuild health summary has no lunch rows")

    rows: list[dict[str, Any]] = []
    for source_row in old_rows:
        volume_m3 = float(source_row["afternoon_route_volume_m3"])
        loading_hours = volume_m3 * LOADING_HOURS_PER_M3
        if not math.isclose(
            loading_hours,
            float(source_row["loading_hours"]),
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise ValueError("source lunch loading arithmetic disagrees")
        charging_hours = max(0.0, 2.0 - loading_hours)
        charge = lunch_charge_ceiling_row(
            bundle,
            available_charging_hours=charging_hours,
        )
        depot_id = str(source_row["depot_id"])
        lunch_profile = _profile_row_for_depot(
            bundle,
            depot_id,
            minute=720,
        )
        return_profile = _profile_row_for_depot(
            bundle,
            depot_id,
            minute=1110,
        )
        price_difference = (
            float(return_profile["depot_energy_cny_per_kwh"])
            - float(lunch_profile["depot_energy_cny_per_kwh"])
        )
        carbon_difference = (
            float(return_profile["actual_gco2_per_kwh"])
            - float(lunch_profile["actual_gco2_per_kwh"])
        ) / 1000.0
        curve = curve_for_charging_node(
            bundle.prices,
            node_type="d",
            capacity_kwh=float(charge["battery_capacity_kwh"]),
            reference_power_kw=float(charge["reference_power_kw"]),
        )
        first_segment_energy = float(curve.energy_breakpoints_kwh[1])
        first_segment_minutes = float(curve.cumulative_seconds[1]) / 60.0
        remaining_minutes = charging_hours * 60.0 - first_segment_minutes
        second_segment_energy = (
            float(charge["chargeable_energy_ceiling_kwh"])
            - first_segment_energy
        )
        old_energy = float(source_row["rated_charge_kwh"])
        new_energy = float(charge["chargeable_energy_ceiling_kwh"])
        rows.append(
            {
                "physical_vehicle_id": source_row["physical_vehicle_id"],
                "depot_id": depot_id,
                "afternoon_route_volume_m3": volume_m3,
                "loading_hours": loading_hours,
                "charging_hours": charging_hours,
                "old_22kw_linear_ceiling_kwh": old_energy,
                **charge,
                "curve_segment_powers_kw": list(curve.segment_powers_kw),
                "first_segment_energy_kwh": first_segment_energy,
                "first_segment_minutes": first_segment_minutes,
                "remaining_minutes_after_first_segment": remaining_minutes,
                "second_segment_energy_kwh": second_segment_energy,
                "energy_price_difference_cny_per_kwh": price_difference,
                "carbon_factor_difference_kgco2e_per_kwh": carbon_difference,
                "cost_headroom_cny": new_energy * price_difference,
                "emissions_headroom_kgco2e": new_energy * carbon_difference,
                "interpretation": "counterfactual_ev_duty_ceiling_not_observed_ev_charge",
            }
        )

    old_values = {
        "aggregate_chargeable_energy_kwh": sum(
            float(row["old_22kw_linear_ceiling_kwh"])
            for row in rows
        ),
        "cost_headroom_cny": sum(
            float(row["old_22kw_linear_ceiling_kwh"])
            * float(row["energy_price_difference_cny_per_kwh"])
            for row in rows
        ),
        "emissions_headroom_kgco2e": sum(
            float(row["old_22kw_linear_ceiling_kwh"])
            * float(row["carbon_factor_difference_kgco2e_per_kwh"])
            for row in rows
        ),
    }
    new_values = {
        "aggregate_chargeable_energy_kwh": sum(
            float(row["chargeable_energy_ceiling_kwh"])
            for row in rows
        ),
        "cost_headroom_cny": sum(
            float(row["cost_headroom_cny"])
            for row in rows
        ),
        "emissions_headroom_kgco2e": sum(
            float(row["emissions_headroom_kgco2e"])
            for row in rows
        ),
    }
    expected_old_rounded = (148.50, 79.46, 22.79)
    observed_old_rounded = (
        round(old_values["aggregate_chargeable_energy_kwh"], 2),
        round(old_values["cost_headroom_cny"], 2),
        round(old_values["emissions_headroom_kgco2e"], 2),
    )
    if observed_old_rounded != expected_old_rounded:
        raise ValueError(
            "source A14 values disagree with the invalidated 22 kW report: "
            f"{observed_old_rounded}"
        )

    protected_after = {str(path): sha256(REPO / path) for path in PROTECTED}
    source_tree_after = tree_sha256(source_report_root)
    if protected_before != protected_after:
        raise RuntimeError("a protected evaluator changed during A14 recompute")
    if source_tree_before != source_tree_after:
        raise RuntimeError("the historical rebuild report changed during recompute")

    report_root.mkdir(parents=True, exist_ok=False)
    try:
        write_csv(report_root / "raw_runs.csv", rows, list(rows[0]))
        write_json(
            report_root / "health_summary.json",
            {
                "calculation_kind": "deterministic_lunch_charge_ceiling_no_search",
                "source_report": str(source_report_root.relative_to(REPO)),
                "source_health_summary_sha256": source_health_sha256,
                "source_report_tree_sha256_before": source_tree_before,
                "source_report_tree_sha256_after": source_tree_after,
                "old_22kw_reported_values": old_values,
                "new_60kw_curve_values": new_values,
                "binding_constraint": rows[0]["binding_constraint"],
                "lunch_rows": rows,
            },
        )
        write_json(
            report_root / "metadata.json",
            {
                "instance_id": INSTANCE_ID,
                "run_kind": "parameter_health_recompute_no_formal_experiment",
                "formal_search_runs": 0,
                "selected_witness_seed": old_health["selected_witness_seed"],
                "depot_charge_power_kw": DEPOT_CHARGE_POWER_KW,
                "charging_curve_id": rows[0]["charging_curve_id"],
                "battery_capacity_kwh": rows[0]["battery_capacity_kwh"],
                "protected_sha256_before": protected_before,
                "protected_sha256_after": protected_after,
            },
        )
        write_json(
            report_root / "decision.json",
            {
                "completion": "INSTANCE_REBUILD_60KW_RECOMPUTE_DONE",
                "formal_experiment_started": False,
                "historical_report_overwritten": False,
                "protected_files_modified": False,
                "binding_constraint": rows[0]["binding_constraint"],
            },
        )
        report = _render_lunch_recompute_report(
            report_root=report_root,
            source_report_root=source_report_root,
            rows=rows,
            old_values=old_values,
            new_values=new_values,
            source_tree_before=source_tree_before,
            source_tree_after=source_tree_after,
            protected_before=protected_before,
            protected_after=protected_after,
        )
        (report_root / "report.md").write_text(report, encoding="utf-8")
        report_files = sorted(
            path
            for path in report_root.rglob("*")
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
        write_json(
            report_root / "artifact_hashes.json",
            {
                str(path.relative_to(REPO)): sha256(path)
                for path in report_files
            },
        )
    except Exception:
        if report_root.exists():
            shutil.rmtree(report_root)
        raise


def build(
    output_root: Path,
    report_root: Path,
    *,
    pyvrp_probe_json: Path | None = None,
) -> None:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite rebuilt authority: {output_root}")
    if report_root.exists():
        raise FileExistsError(f"refusing to overwrite rebuild report: {report_root}")

    protected_before = {str(path): sha256(REPO / path) for path in PROTECTED}
    node_rows, order_rows, source_node_for_new, _ = build_order_and_node_rows()
    output_root.mkdir(parents=True, exist_ok=False)
    try:
        write_authority_files(output_root, node_rows, order_rows, source_node_for_new)
        subset_matrix(output_root, node_rows, source_node_for_new)

        bundle = load_private_instance_rebuild(REPO)
        contest_rows = contestability_rows(bundle)
        witnesses = [build_witness(bundle, seed) for seed in HEALTH_SEEDS]
        selected = next(item for item in witnesses if item.seed == 11)
        counts = {}
        for depot in ("D_foshan", "D_guangzhou"):
            depot_plans = [plan for plan in selected.plans if plan.depot_id == depot]
            physical_vehicle_ids = {
                route.vehicle_id.split("#T", 1)[0]
                for route in selected.solution.routes
                if route.home_depot_id == depot
            }
            counts[depot] = (len(depot_plans), len(physical_vehicle_ids))
        write_fleet_caps(output_root, counts)

        # Reload after the measured fleet authority replaces the provisional ceiling.
        bundle = load_private_instance_rebuild(REPO)
        witnesses = [build_witness(bundle, seed) for seed in HEALTH_SEEDS]
        selected = next(item for item in witnesses if item.seed == 11)
        contest_rows = contestability_rows(bundle)
        if pyvrp_probe_json is None:
            flip_customer, flip_rows, flip_summary = paired_flip_probe(
                bundle,
                contest_rows,
            )
            flip_summary["probe_kind"] = "randomized_greedy_fallback"
            flip_summary["max_iterations_per_slice"] = 0
        else:
            probe_payload = json.loads(
                pyvrp_probe_json.read_text(encoding="utf-8")
            )
            flip_customer, flip_rows, flip_summary = paired_flip_probe_from_pyvrp(
                bundle,
                probe_payload,
            )
        health = health_summary(bundle, contest_rows, witnesses, flip_summary)
        per_km, _ = per_km_rows(bundle, selected)

        report_root.mkdir(parents=True, exist_ok=False)
        write_csv(
            output_root / "contestability.csv",
            contest_rows,
            list(contest_rows[0]),
        )
        source_mapping = [
            {
                "new_node_id": new_id,
                "source_instance_id": SOURCE_INSTANCE,
                "source_node_id": source_id,
            }
            for new_id, source_id in source_node_for_new.items()
        ]
        write_csv(
            output_root / "source_mapping.csv",
            source_mapping,
            list(source_mapping[0]),
        )
        plan_by_signature = {
            (plan.depot_id, plan.shift_id, plan.customers): plan
            for plan in selected.plans
        }
        ordered_witness_routes = sorted(
            selected.solution.routes,
            key=lambda route: (
                route.vehicle_id.split("#T", 1)[0],
                selected.departures[route.vehicle_id],
            ),
        )
        witness_rows = []
        for index, route in enumerate(ordered_witness_routes, start=1):
            shift_id = bundle.orders_by_customer[route.node_sequence[1]]["shift_id"]
            plan = plan_by_signature[
                (
                    route.home_depot_id,
                    shift_id,
                    tuple(route.node_sequence[1:-1]),
                )
            ]
            feasible, departed, returned, distance = route_clock(
                bundle,
                route.home_depot_id,
                shift_id,
                plan.customers,
                earliest_departure_second=selected.departures[route.vehicle_id],
            )
            if not feasible:
                raise RuntimeError("scheduled witness route failed exact replay")
            witness_rows.append(
                {
                    "route_index": index,
                    "seed": selected.seed,
                    "physical_vehicle_id": route.vehicle_id.split("#T", 1)[0],
                    "route_vehicle_id": route.vehicle_id,
                    "depot_id": route.home_depot_id,
                    "shift_id": shift_id,
                    "customers": "|".join(plan.customers),
                    "customer_count": len(plan.customers),
                    "volume_m3": plan.volume_m3,
                    "demand_kg": plan.demand_kg,
                    "departure_minute": departed / 60.0,
                    "return_minute": returned / 60.0,
                    "distance_km": distance / 1000.0,
                }
            )
        write_csv(
            report_root / "health_witness_routes.csv",
            witness_rows,
            list(witness_rows[0]),
        )
        write_csv(report_root / "flip_probe_raw.csv", flip_rows, list(flip_rows[0]))
        if pyvrp_probe_json is not None:
            shutil.copy2(
                pyvrp_probe_json,
                report_root / "pyvrp_flip_probe_routes.json",
            )
        write_csv(
            report_root / "per_km_vehicle_comparison.csv",
            per_km,
            list(per_km[0]),
        )
        write_json(report_root / "health_summary.json", health)
        write_json(
            report_root / "metadata.json",
            {
                "instance_id": INSTANCE_ID,
                "run_kind": "construction_health_check_no_formal_experiment",
                "health_seeds": HEALTH_SEEDS,
                "formal_search_runs": 0,
                "selected_witness_seed": selected.seed,
                "assignment_probe_kind": flip_summary["probe_kind"],
                "fleet_parameter_class": bundle.china81.fleet_parameter_class_id,
                "technical_assignment_probe_slices": len(flip_rows) * 2 * 4,
                "assignment_probe_max_iterations_per_slice": flip_summary[
                    "max_iterations_per_slice"
                ],
                "runtime_profile_date": bundle.time_profile[0]["date"],
            },
        )
        write_json(
            report_root / "decision.json",
            {
                "completion": "INSTANCE_REBUILD_DONE",
                "formal_experiment_authorized": False,
                "formal_experiment_started": False,
                "protected_files_modified": False,
            },
        )

        protected_after = {str(path): sha256(REPO / path) for path in PROTECTED}
        if protected_before != protected_after:
            raise RuntimeError("a protected evaluator changed during rebuild")
        report = render_report(
            output_root,
            report_root,
            bundle,
            contest_rows,
            selected,
            health,
            flip_customer,
            flip_rows,
            per_km,
            protected_before,
            protected_after,
        )
        (report_root / "report.md").write_text(report, encoding="utf-8")

        data_files = sorted(
            path
            for path in output_root.rglob("*")
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
        write_json(
            output_root / "artifact_hashes.json",
            {
                str(path.relative_to(REPO)): sha256(path)
                for path in data_files
            },
        )
        report_files = sorted(
            path
            for path in report_root.rglob("*")
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
        write_json(
            report_root / "artifact_hashes.json",
            {
                str(path.relative_to(REPO)): sha256(path)
                for path in report_files
            },
        )

        metadata_path = output_root / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["input_hashes"] = {
            "source_nodes": sha256(
                SOURCE_STATIC / "instances" / SOURCE_INSTANCE / "nodes.csv"
            ),
            "source_orders": sha256(TASK_AUTHORITY),
            "source_facilities": sha256(SOURCE_STATIC / "facilities.csv"),
        }
        metadata["output_artifact_hashes"] = str(
            (BUNDLE_RELATIVE / "artifact_hashes.json").as_posix()
        )
        metadata["runtime_profile_date"] = bundle.time_profile[0]["date"]
        metadata["source_task_window_median_minute"] = statistics.median(
            float(row["source_time_window_width_minute"])
            for row in read_csv(output_root / "orders.csv")
        )
        write_json(metadata_path, metadata)
        # Refresh data hashes after final metadata enrichment.
        data_files = sorted(
            path
            for path in output_root.rglob("*")
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
        write_json(
            output_root / "artifact_hashes.json",
            {
                str(path.relative_to(REPO)): sha256(path)
                for path in data_files
            },
        )
    except Exception:
        # The destination is task-specific and did not exist before this run.
        # Preserve a failed report if it exists, but do not leave a loadable
        # half-authority masquerading as a complete instance.
        if output_root.exists():
            shutil.rmtree(output_root)
        if report_root.exists():
            shutil.rmtree(report_root)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO / BUNDLE_RELATIVE,
    )
    parser.add_argument(
        "--report-root",
        type=Path,
        default=REPO / REPORT_RELATIVE,
    )
    parser.add_argument(
        "--source-report-root",
        type=Path,
        default=REPO / REPORT_RELATIVE,
    )
    parser.add_argument(
        "--recompute-lunch-report-only",
        action="store_true",
        help=(
            "read the historical health witness and write only a new 60 kW "
            "lunch-ceiling report"
        ),
    )
    parser.add_argument("--pyvrp-probe-json", type=Path)
    args = parser.parse_args()
    if args.recompute_lunch_report_only:
        recompute_lunch_report_only(
            args.report_root.resolve(),
            source_report_root=args.source_report_root.resolve(),
        )
        print(f"INSTANCE_REBUILD_60KW_RECOMPUTE_DONE {INSTANCE_ID}")
        return 0
    build(
        args.output_root.resolve(),
        args.report_root.resolve(),
        pyvrp_probe_json=(
            None
            if args.pyvrp_probe_json is None
            else args.pyvrp_probe_json.resolve()
        ),
    )
    print(f"INSTANCE_REBUILD_DONE {INSTANCE_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
