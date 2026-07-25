#!/usr/bin/env python3
"""D6 corrected S4 route-detail and settlement-key recheck."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[3]
CAMPAIGN_NAME = os.environ.get(
    "RESET_D6_CAMPAIGN_NAME",
    "corrected_china81_rerun_v3_20260724",
)
if (
    not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", CAMPAIGN_NAME)
    or not CAMPAIGN_NAME.startswith("corrected_china81_rerun_")
):
    raise RuntimeError(
        f"invalid RESET_D6_CAMPAIGN_NAME: {CAMPAIGN_NAME!r}"
    )
S4_CASE_ROLE = os.environ.get(
    "RESET_S4_CASE_ROLE",
    "representative",
)
if S4_CASE_ROLE not in {"representative", "mechanism_illustration"}:
    raise RuntimeError(
        f"invalid RESET_S4_CASE_ROLE: {S4_CASE_ROLE!r}"
    )
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / CAMPAIGN_NAME
)
S3 = CAMPAIGN / (
    "mechanism_case_gate"
    if S4_CASE_ROLE == "mechanism_illustration"
    else "representative_gate"
)
OUT = CAMPAIGN / "table4_gate"
for path in (REPO / "solver/src",):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.check import check_solution  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    annotate_cross_site_services,
    exact_china81_score,
)
from setp_solver.cost import (  # noqa: E402
    _arc_loads,
    _evaluate_route,
    carbon_profile_row_for_slot,
    charging_action_slot_breakdown,
    diesel_price_for_route,
    evaluate,
    route_departure_second,
    route_node_schedule,
    time_profile_rows_for_node,
)
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)


REL_TOL = 1.0e-6
ABS_TOL = 1.0e-6
TABLE_FIELDS = [
    "route_index",
    "path",
    "distance_km",
    "cost_cny",
    "time_h",
    "fuel_l",
    "electricity_kwh",
    "emissions_kg",
    "on_time_customer_count",
    "load_rate_pct",
    "vehicle_id",
    "vehicle_type",
    "home_depot_id",
    "home_city",
]
ADDITIVE = (
    "distance_km",
    "cost_cny",
    "time_h",
    "fuel_l",
    "electricity_kwh",
    "emissions_kg",
    "on_time_customer_count",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TABLE_FIELDS)
        writer.writeheader()
        writer.writerows(
            {field: row.get(field, "") for field in TABLE_FIELDS}
            for row in rows
        )


def load_solution(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=[
                    str(item) for item in row["node_sequence"]
                ],
            )
            for row in payload["routes"]
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id=str(row["vehicle_id"]),
                station_id=str(row["station_id"]),
                energy_kwh=float(row["energy_kwh"]),
                occupancy_minutes=float(row["occupancy_minutes"]),
                charge_start_second=float(row["charge_start_second"]),
                charge_day_offset=int(row.get("charge_day_offset", 0)),
                start_energy_kwh=(
                    None
                    if row.get("start_energy_kwh") is None
                    else float(row["start_energy_kwh"])
                ),
                end_energy_kwh=(
                    None
                    if row.get("end_energy_kwh") is None
                    else float(row["end_energy_kwh"])
                ),
                charging_curve_id=row.get("charging_curve_id"),
            )
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                customer_id=str(row["customer_id"]),
                served_by_depot_id=str(row["served_by_depot_id"]),
            )
            for row in payload.get("cross_site_services", [])
        ],
    )


def best_s3_witness() -> tuple[str, int, float, Path, Solution]:
    decision = json.loads((S3 / "decision.json").read_text(encoding="utf-8"))
    if (
        decision.get("verdict")
        not in {
            "PASS_D6_CORRECTED_S3_REPRESENTATIVE",
            "PASS_D6_CORRECTED_S3_MECHANISM_CASE",
        }
    ):
        raise RuntimeError("corrected S3 is not PASS")
    instance_id = str(
        decision.get(
            "case_instance_id",
            decision.get("representative_instance_id"),
        )
    )
    with (S3 / "raw_runs.csv").open(
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["arm"] == "MV-HGS-SP" and row["status"] == "PASS"
        ]
    if len(rows) != 10:
        raise RuntimeError(f"expected 10 fusion rows, found {len(rows)}")
    selected = min(
        rows,
        key=lambda row: (float(row["cost"]), int(row["seed"])),
    )
    witness = REPO / selected["witness_file"]
    payload = json.loads(witness.read_text(encoding="utf-8"))
    return (
        instance_id,
        int(selected["seed"]),
        float(selected["cost"]),
        witness,
        load_solution(payload[selected["witness_key"]]),
    )


def coverage_audit(solution: Solution, bundle: Any) -> dict[str, Any]:
    customers = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    visited = [
        node_id
        for route in solution.routes
        for node_id in route.node_sequence[1:-1]
        if node_id in customers
    ]
    counts = Counter(visited)
    bad = {
        customer_id: counts.get(customer_id, 0)
        for customer_id in sorted(customers)
        if counts.get(customer_id, 0) != 1
    }
    return {
        "customer_count": len(customers),
        "visited_customer_entries": len(visited),
        "bad_customer_counts": bad,
        "passed": not bad and len(visited) == len(customers),
    }


def single_day_charging_audit(
    solution: Solution,
    bundle: Any,
) -> dict[str, Any]:
    invalid = []
    routes = {
        route.vehicle_id: route
        for route in solution.routes
    }
    for action in solution.charging_actions:
        start = float(action.charge_start_second)
        end = start + float(action.occupancy_minutes) * 60.0
        node = bundle.instance.nodes[
            bundle.instance.node_index[action.station_id]
        ]
        departure = (
            route_departure_second(
                routes[action.vehicle_id],
                bundle.instance,
                bundle.prices,
            )
            if node.node_type.lower() == "d"
            else None
        )
        if (
            int(action.charge_day_offset) != 0
            or not 0.0 <= start < 86_400.0
            or end > 86_400.0 + 1.0e-9
            or (
                departure is not None
                and end > departure + 1.0e-9
            )
        ):
            invalid.append(
                {
                    "vehicle_id": action.vehicle_id,
                    "station_id": action.station_id,
                    "charge_day_offset": int(action.charge_day_offset),
                    "start_second": start,
                    "end_second": end,
                    "route_departure_second": departure,
                }
            )
    return {
        "scenario_date": "2025-02-12",
        "charging_action_count": len(solution.charging_actions),
        "invalid_actions": invalid,
        "passed": not invalid,
    }


def route_services(route: Route, bundle: Any) -> list[CrossSiteService]:
    return [
        CrossSiteService(
            customer_id=node_id,
            served_by_depot_id=route.home_depot_id,
        )
        for node_id in route.node_sequence[1:-1]
        if node_id in bundle.customer_home_depot
        and bundle.customer_home_depot[node_id]
        != route.home_depot_id
    ]


def route_row(
    index: int,
    route: Route,
    solution: Solution,
    bundle: Any,
) -> dict[str, Any]:
    lookup = {node.node_id: node for node in bundle.instance.nodes}
    actions = [
        action
        for action in solution.charging_actions
        if action.vehicle_id == route.vehicle_id
    ]
    fragment = annotate_cross_site_services(
        Solution(
            routes=[route],
            charging_actions=actions,
            cross_site_services=route_services(route, bundle),
        ),
        bundle.customer_home_depot,
    )
    breakdown = evaluate(
        fragment,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    energy = _evaluate_route(
        route,
        bundle.instance,
        lookup,
        bundle.prices,
    )
    schedule = route_node_schedule(
        route,
        bundle.instance,
        bundle.prices,
        charging_actions=actions,
    )
    if not schedule:
        raise RuntimeError(f"empty schedule: {route.vehicle_id}")
    on_time = sum(
        1
        for item in schedule
        if lookup[item.node_id].node_type.lower() == "c"
        and item.t_start
        >= lookup[item.node_id].ready_time - 1.0e-9
        and item.t_start
        <= lookup[item.node_id].due_time + 1.0e-9
    )
    loads = _arc_loads(route.node_sequence, lookup)
    capacity = bundle.instance.payload_capacity_kg(
        route.vehicle_type,
        fallback=1.0,
    )
    depot = lookup[route.home_depot_id]
    return {
        "route_index": index,
        "path": "[" + ", ".join(route.node_sequence) + "]",
        "distance_km": energy.distance_m / 1000.0,
        "cost_cny": breakdown["total_cost"],
        "time_h": (
            schedule[-1].t_arrive - schedule[0].t_start
        )
        / 3600.0,
        "fuel_l": energy.fuel_liters,
        "electricity_kwh": breakdown["electricity_kwh"],
        "emissions_kg": breakdown["E_total"],
        "on_time_customer_count": on_time,
        "load_rate_pct": 100.0
        * max(loads, default=0.0)
        / capacity,
        "vehicle_id": route.vehicle_id,
        "vehicle_type": route.vehicle_type,
        "home_depot_id": route.home_depot_id,
        "home_city": str(depot.city).strip().lower(),
    }


def settlement_trace(solution: Solution, bundle: Any) -> dict[str, Any]:
    diesel_rows: list[dict[str, Any]] = []
    for route in solution.routes:
        if route.vehicle_type.lower() != "cv":
            continue
        depot = bundle.instance.nodes[
            bundle.instance.node_index[route.home_depot_id]
        ]
        city = str(depot.city).strip().lower()
        diesel_rows.append(
            {
                "vehicle_id": route.vehicle_id,
                "route_origin_depot": route.home_depot_id,
                "city": city,
                "diesel_zone": bundle.diesel_zone_by_city[city],
                "scenario_date": bundle.date,
                "diesel_price_cny_per_l": diesel_price_for_route(
                    route,
                    bundle.instance,
                    bundle.prices,
                ),
            }
        )
    charging_rows: list[dict[str, Any]] = []
    for action in solution.charging_actions:
        node = bundle.instance.nodes[
            bundle.instance.node_index[action.station_id]
        ]
        city = str(node.city).strip().lower()
        profile = time_profile_rows_for_node(
            bundle.instance,
            action.station_id,
            bundle.time_profile,
        )
        price_field = (
            "depot_energy_cny_per_kwh"
            if node.node_type.lower() == "d"
            else "public_total_cny_per_kwh"
        )
        for slot in charging_action_slot_breakdown(
            action,
            bundle.instance,
            bundle.prices,
            n_slots=len(profile),
            cyclic=True,
        ):
            row = carbon_profile_row_for_slot(
                profile,
                slot.slot_index,
            )
            expected = {
                "date": bundle.date,
                "price_area_id": bundle.price_area_by_city[city],
                "carbon_source_column": (
                    bundle.carbon_source_column_by_city[city]
                ),
                "diesel_zone": bundle.diesel_zone_by_city[city],
                "joint_key_status": (
                    "PASS_CITY_DATE_SLOT_PARAMETER_IDENTITY"
                ),
            }
            if any(row[key] != value for key, value in expected.items()):
                raise RuntimeError(
                    "charging settlement joint key failed closed"
                )
            charging_rows.append(
                {
                    "vehicle_id": action.vehicle_id,
                    "station_id": action.station_id,
                    "node_type": node.node_type,
                    "city": city,
                    "price_area_id": row["price_area_id"],
                    "carbon_source_column": (
                        row["carbon_source_column"]
                    ),
                    "diesel_zone": row["diesel_zone"],
                    "scenario_date": row["date"],
                    "half_hour_slot": int(row["half_hour_slot"]),
                    "energy_kwh": float(slot.y_skt_kwh),
                    "electricity_price_field": price_field,
                    "electricity_price_cny_per_kwh": float(
                        row[price_field]
                    ),
                    "carbon_factor_kgco2e_per_kwh": float(
                        row["actual_gco2_per_kwh"]
                    )
                    / 1000.0,
                }
            )
    return {
        "schema": "resetp.d6-s4-settlement-trace.v1",
        "joint_key_policy": "FAIL_CLOSED_NO_CITY_GROUP_FALLBACK",
        "scenario_date": bundle.date,
        "diesel_routes": diesel_rows,
        "charging_slot_segments": charging_rows,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    instance_id, seed, recorded_cost, witness, solution = best_s3_witness()
    bundle = load_china81_bundle(REPO, instance_id)
    solution = annotate_cross_site_services(
        solution,
        bundle.customer_home_depot,
    )
    charging_day = single_day_charging_audit(solution, bundle)
    direct_violations = check_solution(
        solution,
        bundle.instance,
        bundle.prices,
    )
    direct = evaluate(
        solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    exact_cost, exact, exact_violations = exact_china81_score(
        solution,
        bundle,
    )
    coverage = coverage_audit(solution, bundle)
    rows = [
        route_row(index, route, solution, bundle)
        for index, route in enumerate(solution.routes, start=1)
    ]
    route_sums = {
        field: sum(float(row[field]) for row in rows)
        for field in ADDITIVE
    }
    full_totals = {
        "distance_km": float(direct["distance_total"]) / 1000.0,
        "cost_cny": float(direct["total_cost"]),
        "time_h": route_sums["time_h"],
        "fuel_l": float(direct["fuel_liters"]),
        "electricity_kwh": float(direct["electricity_kwh"]),
        "emissions_kg": float(direct["E_total"]),
        "on_time_customer_count": float(
            route_sums["on_time_customer_count"]
        ),
    }
    closure = {
        field: {
            "route_sum": route_sums[field],
            "full_solution_value": full_totals[field],
            "passed": math.isclose(
                route_sums[field],
                full_totals[field],
                rel_tol=REL_TOL,
                abs_tol=ABS_TOL,
            ),
        }
        for field in ADDITIVE
    }
    mean_row = {
        field: statistics.fmean(float(row[field]) for row in rows)
        for field in ADDITIVE
    }
    mean_row.update(
        {
            "route_index": "mean",
            "path": "mean",
            "load_rate_pct": statistics.fmean(
                float(row["load_rate_pct"]) for row in rows
            ),
        }
    )
    total_row = {
        field: route_sums[field] for field in ADDITIVE
    }
    total_row.update(
        {
            "route_index": "total",
            "path": "total",
            "load_rate_pct": "",
        }
    )
    write_csv(OUT / "route_details.csv", [*rows, mean_row, total_row])
    trace = settlement_trace(solution, bundle)
    write_json(OUT / "settlement_trace.json", trace)
    source_payload = json.loads(witness.read_text(encoding="utf-8"))
    write_json(
        OUT / "best_solution_witness.json",
        {
            "schema": "resetp.d6-corrected-s4-witness.v1",
            "instance_id": instance_id,
            "seed": seed,
            "recorded_s3_cost": recorded_cost,
            "direct_cost": float(direct["total_cost"]),
            "exact_cost": float(exact_cost),
            "source_witness_file": str(witness.relative_to(REPO)),
            "source_witness_sha256": sha256(witness),
            "solution": source_payload["MV-HGS-SP"],
            "coverage_audit": coverage,
            "single_day_charging_audit": charging_day,
            "arithmetic_closure": closure,
        },
    )
    passed = (
        not direct_violations
        and not exact_violations
        and coverage["passed"]
        and charging_day["passed"]
        and all(item["passed"] for item in closure.values())
        and math.isclose(
            recorded_cost,
            exact_cost,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        )
        and math.isclose(
            float(direct["total_cost"]),
            exact_cost,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        )
    )
    decision = {
        "schema": "resetp.d6-corrected-s4.decision.v1",
        "verdict": (
            "PASS_D6_CORRECTED_S4_ROUTE_DETAIL"
            if passed
            else "HALT_D6_CORRECTED_S4_RECHECK"
        ),
        "case_role": S4_CASE_ROLE,
        "case_instance_id": instance_id,
        "best_seed": seed,
        "recorded_s3_cost": recorded_cost,
        "direct_cost": float(direct["total_cost"]),
        "exact_cost": float(exact_cost),
        "full_solution_check_violation_count": len(direct_violations),
        "full_solution_exact_violation_count": len(exact_violations),
        "coverage_audit": coverage,
        "single_day_charging_audit": charging_day,
        "arithmetic_closure": closure,
        "route_count": len(rows),
        "settlement_joint_key_policy": (
            "instance/node -> city/price area/carbon column/diesel zone -> "
            "2025-02-12 -> half-hour slot; fail closed; no group fallback"
        ),
        "diesel_route_count": len(trace["diesel_routes"]),
        "charging_slot_segment_count": len(
            trace["charging_slot_segments"]
        ),
        "claim_boundary": (
            "independent route arithmetic and settlement-key witness; "
            "no search and no result change"
        ),
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.d6-corrected-s4.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    S3 / "decision.json",
                    S3 / "raw_runs.csv",
                    witness,
                    REPO / "solver/src/setp_solver/cost.py",
                    REPO / "solver/src/setp_solver/check.py",
                    REPO / "solver/src/setp_solver/china81.py",
                    Path(__file__).resolve(),
                )
            },
        },
    )
    (OUT / "report.md").write_text(
        "# D6 corrected S4 route-detail recheck\n\n"
        f"Decision: `{decision['verdict']}`.\n\n"
        f"Representative `{instance_id}`, best seed {seed}; recorded, direct "
        f"and exact costs are {exact_cost:.12f}. The full solution has "
        f"{len(exact_violations)} exact violations. Route fragments were "
        "checked arithmetically; customer coverage was checked only on the "
        "complete solution. Diesel was settled by route-origin city and "
        "charging was settled by station city, scenario date and half-hour "
        "slot under the fail-closed joint key; all charging intervals remain "
        "within 2025-02-12.\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
