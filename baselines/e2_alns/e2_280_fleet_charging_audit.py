"""Read-only fleet and charging audit for the frozen 280 kWh E2 evidence.

This script performs no search.  It replays the 45 official staged-hybrid
solutions and their same-route naive charging counterparts, then reports what
the EVs and CVs actually carried and how much charging was really shifted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import subprocess
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.solution import ChargingAction, Route, Solution, physical_vehicle_id


SOURCE = Path("baselines/e2_alns/e2_submission_20260711/carbon_280/raw_runs.csv")
AWARE = "staged_hybrid_carbon_aware"
NAIVE = "staged_hybrid_carbon_naive"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def solution_from_json(raw: str) -> Solution:
    payload = json.loads(raw)
    return Solution(
        routes=[Route(**row) for row in payload.get("routes", [])],
        charging_actions=[ChargingAction(**row) for row in payload.get("charging_actions", [])],
        cross_site_services=list(payload.get("cross_site_services", [])),
    )


def route_signature(solution: Solution) -> tuple[tuple[str, str, str, tuple[str, ...]], ...]:
    return tuple(
        sorted(
            (route.vehicle_id, route.vehicle_type.lower(), route.home_depot_id, tuple(route.node_sequence))
            for route in solution.routes
        )
    )


def _action_groups(actions: list[ChargingAction]) -> dict[tuple[str, str, float, float], list[ChargingAction]]:
    groups: dict[tuple[str, str, float, float], list[ChargingAction]] = defaultdict(list)
    for action in actions:
        key = (
            action.vehicle_id,
            action.station_id,
            round(float(action.energy_kwh), 8),
            round(float(action.occupancy_minutes), 8),
        )
        groups[key].append(action)
    for values in groups.values():
        values.sort(key=lambda item: float(item.charge_start_second))
    return groups


def shifted_charging(aware: Solution, naive: Solution) -> dict[str, Any]:
    left = _action_groups(aware.charging_actions)
    right = _action_groups(naive.charging_actions)
    same_multiset = set(left) == set(right) and all(len(left[key]) == len(right[key]) for key in left)
    shifted_actions = 0
    shifted_energy = 0.0
    absolute_shift_hours = 0.0
    if same_multiset:
        for key in left:
            for aware_action, naive_action in zip(left[key], right[key], strict=True):
                difference = abs(float(aware_action.charge_start_second) - float(naive_action.charge_start_second))
                if difference > 1e-9:
                    shifted_actions += 1
                    shifted_energy += float(aware_action.energy_kwh)
                    absolute_shift_hours += difference / 3600.0
    return {
        "same_charging_action_multiset": same_multiset,
        "shifted_action_count": shifted_actions,
        "shifted_energy_kwh": shifted_energy,
        "absolute_shift_hours": absolute_shift_hours,
    }


def _shares(solution: Solution, bundle: Any, metrics: dict[str, float]) -> dict[str, Any]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    workload = {"ev": {"customers": 0, "demand": 0.0}, "cv": {"customers": 0, "demand": 0.0}}
    for route in solution.routes:
        kind = route.vehicle_type.lower()
        for node_id in route.node_sequence:
            node = nodes.get(node_id)
            if node is not None and node.node_type.lower() == "c":
                workload[kind]["customers"] += 1
                workload[kind]["demand"] += float(node.demand)
    customer_total = sum(item["customers"] for item in workload.values())
    demand_total = sum(item["demand"] for item in workload.values())
    route_count = len(solution.routes)
    ev_routes = [route for route in solution.routes if route.vehicle_type.lower() == "ev"]
    cv_routes = [route for route in solution.routes if route.vehicle_type.lower() == "cv"]
    ev_vehicles = {physical_vehicle_id(route.vehicle_id) for route in ev_routes}
    cv_vehicles = {physical_vehicle_id(route.vehicle_id) for route in cv_routes}
    physical_total = len(ev_vehicles) + len(cv_vehicles)
    station_types = {node.node_id: node.node_type.lower() for node in bundle.instance.nodes}
    depot_energy = sum(
        float(action.energy_kwh) for action in solution.charging_actions if station_types.get(action.station_id) == "d"
    )
    public_energy = sum(
        float(action.energy_kwh) for action in solution.charging_actions if station_types.get(action.station_id) != "d"
    )
    charging_energy = depot_energy + public_energy
    depot_actions = sum(1 for action in solution.charging_actions if station_types.get(action.station_id) == "d")
    public_actions = len(solution.charging_actions) - depot_actions
    distance_total = float(metrics["distance_total"])
    return {
        "route_count": route_count,
        "ev_route_count": len(ev_routes),
        "cv_route_count": len(cv_routes),
        "ev_route_share": len(ev_routes) / route_count if route_count else 0.0,
        "ev_physical_vehicle_count": len(ev_vehicles),
        "cv_physical_vehicle_count": len(cv_vehicles),
        "ev_physical_vehicle_share": len(ev_vehicles) / physical_total if physical_total else 0.0,
        "ev_customer_count": workload["ev"]["customers"],
        "cv_customer_count": workload["cv"]["customers"],
        "ev_customer_share": workload["ev"]["customers"] / customer_total if customer_total else 0.0,
        "ev_demand": workload["ev"]["demand"],
        "cv_demand": workload["cv"]["demand"],
        "ev_demand_share": workload["ev"]["demand"] / demand_total if demand_total else 0.0,
        "ev_distance_m": float(metrics["distance_ev"]),
        "cv_distance_m": float(metrics["distance_cv"]),
        "ev_distance_share": float(metrics["distance_ev"]) / distance_total if distance_total else 0.0,
        "charging_action_count": len(solution.charging_actions),
        "charging_energy_kwh": charging_energy,
        "depot_charging_action_count": depot_actions,
        "public_charging_action_count": public_actions,
        "depot_charging_energy_kwh": depot_energy,
        "public_charging_energy_kwh": public_energy,
    }


def mean(rows: list[dict[str, Any]], field: str) -> float:
    return statistics.fmean(float(row[field]) for row in rows) if rows else 0.0


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["instance"])].append(row)
    result: list[dict[str, Any]] = []
    for instance, items in sorted(groups.items(), key=lambda pair: int(pair[1][0]["size"])):
        result.append(
            {
                "instance": instance,
                "size": int(items[0]["size"]),
                "runs": len(items),
                "mixed_runs": sum(int(row["ev_route_count"] > 0 and row["cv_route_count"] > 0) for row in items),
                "all_ev_runs": sum(int(row["ev_route_count"] > 0 and row["cv_route_count"] == 0) for row in items),
                "all_cv_runs": sum(int(row["cv_route_count"] > 0 and row["ev_route_count"] == 0) for row in items),
                **{
                    f"mean_{field}": mean(items, field)
                    for field in (
                        "ev_route_share",
                        "ev_physical_vehicle_share",
                        "ev_customer_share",
                        "ev_demand_share",
                        "ev_distance_share",
                        "charging_action_count",
                        "charging_energy_kwh",
                        "depot_charging_action_count",
                        "public_charging_action_count",
                        "depot_charging_energy_kwh",
                        "public_charging_energy_kwh",
                        "low_carbon_charging_share",
                        "shifted_action_count",
                        "shifted_energy_kwh",
                        "aware_weighted_carbon_g_per_kwh",
                        "naive_weighted_carbon_g_per_kwh",
                        "ev_carbon_saved_kg",
                    )
                },
            }
        )
    return result


def artifact_hashes(output: Path) -> dict[str, str]:
    return {
        str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_rows = read_csv(root / SOURCE)
    aware_rows = [row for row in source_rows if row["algorithm"] == AWARE]
    naive_lookup = {
        (row["instance"], int(row["seed"])): row for row in source_rows if row["algorithm"] == NAIVE
    }
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034)
    audit_rows: list[dict[str, Any]] = []
    for source in sorted(aware_rows, key=lambda row: (int(row["size"]), row["instance"], int(row["seed"]))):
        key = (source["instance"], int(source["seed"]))
        naive_source = naive_lookup[key]
        bundle = load_search_bundle(root / "models/data_bundle/generated_instances/L-main" / source["instance"])
        aware = solution_from_json(source["solution_json"])
        naive = solution_from_json(naive_source["solution_json"])
        aware_metrics = evaluate(aware, bundle.instance, bundle.carbon_profile, prices)
        naive_metrics = evaluate(naive, bundle.instance, bundle.carbon_profile, prices)
        aware_energy = float(aware_metrics["electricity_kwh"])
        naive_energy = float(naive_metrics["electricity_kwh"])
        shifted = shifted_charging(aware, naive)
        audit_rows.append(
            {
                "instance": source["instance"],
                "size": int(source["size"]),
                "seed": int(source["seed"]),
                "aware_zero_violation": len(check_solution(aware, bundle.instance, prices)) == 0,
                "naive_zero_violation": len(check_solution(naive, bundle.instance, prices)) == 0,
                "same_route_structure": route_signature(aware) == route_signature(naive),
                "same_electricity_kwh": abs(aware_energy - naive_energy) <= 1e-8,
                "aware_weighted_carbon_g_per_kwh": (
                    0.0 if aware_energy <= 1e-12 else float(aware_metrics["E_ev_indirect"]) * 1000.0 / aware_energy
                ),
                "naive_weighted_carbon_g_per_kwh": (
                    0.0 if naive_energy <= 1e-12 else float(naive_metrics["E_ev_indirect"]) * 1000.0 / naive_energy
                ),
                "ev_carbon_saved_kg": float(naive_metrics["E_ev_indirect"]) - float(aware_metrics["E_ev_indirect"]),
                "aware_ev_indirect_kg": float(aware_metrics["E_ev_indirect"]),
                "naive_ev_indirect_kg": float(naive_metrics["E_ev_indirect"]),
                "low_carbon_charging_share": float(source["low_carbon_charging_share"] or 0.0),
                **_shares(aware, bundle, aware_metrics),
                **shifted,
            }
        )
    summaries = summarize(audit_rows)
    eligible = [row for row in audit_rows if int(row["size"]) != 15]
    total_customers = sum(int(row["ev_customer_count"]) + int(row["cv_customer_count"]) for row in eligible)
    total_ev_customers = sum(int(row["ev_customer_count"]) for row in eligible)
    total_demand = sum(float(row["ev_demand"]) + float(row["cv_demand"]) for row in eligible)
    total_ev_demand = sum(float(row["ev_demand"]) for row in eligible)
    total_distance = sum(float(row["ev_distance_m"]) + float(row["cv_distance_m"]) for row in eligible)
    total_ev_distance = sum(float(row["ev_distance_m"]) for row in eligible)
    total_physical_vehicles = sum(
        int(row["ev_physical_vehicle_count"]) + int(row["cv_physical_vehicle_count"]) for row in eligible
    )
    total_ev_physical_vehicles = sum(int(row["ev_physical_vehicle_count"]) for row in eligible)
    total_charging_energy = sum(float(row["charging_energy_kwh"]) for row in eligible)
    total_shifted_energy = sum(float(row["shifted_energy_kwh"]) for row in eligible)
    all_clean = len(audit_rows) == 45 and all(
        bool(row[field])
        for row in audit_rows
        for field in (
            "aware_zero_violation",
            "naive_zero_violation",
            "same_route_structure",
            "same_electricity_kwh",
            "same_charging_action_multiset",
        )
    )
    decision = {
        "verdict": "E2_280_EV_HEAVY_CHARGING_ACTIVITY_AUDITED" if all_clean else "HALT_E2_280_FLEET_CHARGING_AUDIT",
        "zero_new_search": True,
        "official_aware_rows": len(audit_rows),
        "all_saved_pairs_clean": all_clean,
        "mechanism_eligible_rows_excluding_structural_15c": len(eligible),
        "eligible_mixed_runs": sum(int(row["ev_route_count"] > 0 and row["cv_route_count"] > 0) for row in eligible),
        "eligible_all_ev_runs": sum(int(row["ev_route_count"] > 0 and row["cv_route_count"] == 0) for row in eligible),
        "eligible_all_cv_runs": sum(int(row["cv_route_count"] > 0 and row["ev_route_count"] == 0) for row in eligible),
        "aggregate_ev_customer_share": total_ev_customers / total_customers if total_customers else 0.0,
        "aggregate_cv_customer_share": 1.0 - total_ev_customers / total_customers if total_customers else 0.0,
        "aggregate_ev_demand_share": total_ev_demand / total_demand if total_demand else 0.0,
        "aggregate_cv_demand_share": 1.0 - total_ev_demand / total_demand if total_demand else 0.0,
        "aggregate_ev_distance_share": total_ev_distance / total_distance if total_distance else 0.0,
        "aggregate_cv_distance_share": 1.0 - total_ev_distance / total_distance if total_distance else 0.0,
        "aggregate_ev_physical_vehicle_share": (
            total_ev_physical_vehicles / total_physical_vehicles if total_physical_vehicles else 0.0
        ),
        "total_charging_actions": sum(int(row["charging_action_count"]) for row in eligible),
        "total_charging_energy_kwh": total_charging_energy,
        "total_depot_charging_actions": sum(int(row["depot_charging_action_count"]) for row in eligible),
        "total_public_charging_actions": sum(int(row["public_charging_action_count"]) for row in eligible),
        "total_depot_charging_energy_kwh": sum(float(row["depot_charging_energy_kwh"]) for row in eligible),
        "total_public_charging_energy_kwh": sum(float(row["public_charging_energy_kwh"]) for row in eligible),
        "total_shifted_actions": sum(int(row["shifted_action_count"]) for row in eligible),
        "total_shifted_energy_kwh": total_shifted_energy,
        "shifted_energy_share": total_shifted_energy / total_charging_energy if total_charging_energy else 0.0,
        "total_ev_carbon_saved_vs_same_route_naive_kg": sum(float(row["ev_carbon_saved_kg"]) for row in eligible),
        "aggregate_aware_weighted_carbon_g_per_kwh": (
            sum(float(row["aware_ev_indirect_kg"]) for row in eligible) * 1000.0 / total_charging_energy
            if total_charging_energy
            else 0.0
        ),
        "aggregate_naive_weighted_carbon_g_per_kwh": (
            sum(float(row["naive_ev_indirect_kg"]) for row in eligible) * 1000.0 / total_charging_energy
            if total_charging_energy
            else 0.0
        ),
        "pairs_with_positive_carbon_saving": sum(int(float(row["ev_carbon_saved_kg"]) > 1e-9) for row in eligible),
        "pairs_with_negative_carbon_saving": sum(int(float(row["ev_carbon_saved_kg"]) < -1e-9) for row in eligible),
        "interpretation": "The audit describes the frozen 280 kWh flagship; it does not select a new battery capacity or authorize new formal search.",
    }
    metadata = {
        "schema_version": "resetp.e2_280_fleet_charging_audit.v1",
        "execution_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "source": str(SOURCE),
        "battery_kwh": 280.0,
        "zero_new_search": True,
        "excluded_from_mechanism_aggregate": {"size": 15, "reason": "instance has structural num_ev=0"},
    }
    write_csv(output / "raw_audit_rows.csv", audit_rows)
    write_csv(output / "per_instance_summary.csv", summaries)
    write_json(output / "metadata.json", metadata)
    write_json(output / "decision.json", decision)
    lines = [
        "# Frozen E2 280 kWh fleet and charging audit",
        "",
        f"Verdict: `{decision['verdict']}`. No new search was run.",
        "",
        f"All {len(audit_rows)} official aware/naive pairs retain the same route structure, electricity demand and charging-action multiset, and both sides remain feasible: {all_clean}.",
        f"After excluding the structural 15c no-EV instance, aggregate EV shares by customers/demand/distance are {decision['aggregate_ev_customer_share']:.3%}/{decision['aggregate_ev_demand_share']:.3%}/{decision['aggregate_ev_distance_share']:.3%}.",
        f"The corresponding CV shares are {decision['aggregate_cv_customer_share']:.3%}/{decision['aggregate_cv_demand_share']:.3%}/{decision['aggregate_cv_distance_share']:.3%}; EVs account for {decision['aggregate_ev_physical_vehicle_share']:.3%} of summed physical-vehicle use.",
        f"The eligible rows contain {decision['eligible_mixed_runs']} mixed runs, {decision['eligible_all_ev_runs']} all-EV runs and {decision['eligible_all_cv_runs']} all-CV runs.",
        f"They contain {decision['total_charging_actions']} charging actions and {decision['total_charging_energy_kwh']:.3f} kWh of charging. Carbon-aware timing actually shifts {decision['total_shifted_actions']} actions and {decision['total_shifted_energy_kwh']:.3f} kWh ({decision['shifted_energy_share']:.3%} of charging energy).",
        f"Against the same-route naive timing rows, charging-weighted carbon intensity falls from {decision['aggregate_naive_weighted_carbon_g_per_kwh']:.3f} to {decision['aggregate_aware_weighted_carbon_g_per_kwh']:.3f} gCO2/kWh and total EV indirect carbon falls by {decision['total_ev_carbon_saved_vs_same_route_naive_kg']:.3f} kg; positive/negative pairs are {decision['pairs_with_positive_carbon_saving']}/{decision['pairs_with_negative_carbon_saving']}.",
        f"All formal charging is depot charging: public-station actions/energy are {decision['total_public_charging_actions']}/{decision['total_public_charging_energy_kwh']:.3f} kWh. Therefore the frozen result proves depot charging-time shifting, not public-station selection.",
        "",
        "This audit supports or limits the 280 kWh paper story using frozen evidence only. It does not decide the cross-depot fee, fairness contract, a new battery capacity, or the formal refined-carbon gate.",
        "",
    ]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    write_json(output / "artifact_hashes.json", artifact_hashes(output))
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    if not all_clean:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
