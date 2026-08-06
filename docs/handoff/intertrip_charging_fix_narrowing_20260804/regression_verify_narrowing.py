#!/usr/bin/env python3
"""Read-only T11 narrowing audit.

This script does not run search or mutate the archived 18-run solutions.  It
replays the current checker on those payloads, checks the three positive
witnesses, and compares the current single-date settlement profile with the
counterfactual preceding-date profile for first-trip depot charges.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[3]
T10 = REPO / "docs/handoff/intertrip_charging_fix_20260804"
T7_RUNNER = REPO / "docs/handoff/eval_chain_carbon_consistency_20260804/t7_runner.py"
INSTANCE_ID = "cn-jjj-50c-01-V2-LOCATIONS"
SCENARIO_DATE = "2025-02-12"
PREVIOUS_DATE = "2025-02-11"
AUTHORITY = REPO / "data/ChinaInstances/china81_finite_fleet_authority_v3_20260802"

for entry in (REPO / "solver/src", REPO):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


def _load_t7_runner():
    spec = importlib.util.spec_from_file_location("t11_t7_runner", T7_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {T7_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    from setp_solver.china81 import load_china81_bundle
    from setp_solver.check import CHARGING_TRIP_OVERLAP, check_solution
    from setp_solver.cost import (
        carbon_profile_row_for_slot,
        charging_action_electricity_cost,
        charging_action_emissions_kg,
        charging_action_slot_breakdown,
        time_profile_rows_for_node,
    )
    from setp_solver.model_config import ModelConfig

    t7 = _load_t7_runner()
    config = ModelConfig(
        strict_multitrip=True,
        depot_charger_capacity_mode="unbounded",
    )
    current = load_china81_bundle(
        REPO,
        INSTANCE_ID,
        date=SCENARIO_DATE,
        fleet_authority=AUTHORITY,
        model_config=config,
    )
    previous = load_china81_bundle(
        REPO,
        INSTANCE_ID,
        date=PREVIOUS_DATE,
        fleet_authority=AUTHORITY,
        model_config=config,
    )
    runs = json.loads(
        (T10 / "solution_witnesses.json").read_text(encoding="utf-8")
    )["runs"]
    node_lookup = {node.node_id: node for node in current.instance.nodes}

    first_actions_total = 0
    first_minus1_actions = 0
    first_minus1_energy = 0.0
    current_emissions = 0.0
    previous_emissions = 0.0
    current_cost = 0.0
    previous_cost = 0.0
    t10_violation_count = 0
    public_action_count = 0
    run_rows: list[dict[str, object]] = []

    for run_id in sorted(runs):
        solution = t7._solution_from_payload(runs[run_id]["solution"])
        public_action_count += sum(
            1
            for action in solution.charging_actions
            if node_lookup[action.station_id].node_type.lower() == "f"
            and action.station_id
            in next(
                route.node_sequence
                for route in solution.routes
                if route.vehicle_id == action.vehicle_id
            )
        )
        violations = check_solution(solution, current.instance, current.prices)
        t10_violation_count += len(violations)
        actions = [
            action
            for action in solution.charging_actions
            if "#T1" in action.vehicle_id
            and node_lookup[action.station_id].node_type.lower() == "d"
        ]
        first_actions_total += len(actions)
        run_current_emissions = 0.0
        run_previous_emissions = 0.0
        run_current_cost = 0.0
        run_previous_cost = 0.0
        for action in actions:
            if int(action.charge_day_offset) != -1:
                continue
            first_minus1_actions += 1
            first_minus1_energy += float(action.energy_kwh)
            e_current = charging_action_emissions_kg(
                action, current.instance, current.time_profile, current.prices
            )
            e_previous = charging_action_emissions_kg(
                action, previous.instance, previous.time_profile, previous.prices
            )
            c_current = charging_action_electricity_cost(
                action, current.instance, current.time_profile, current.prices
            )
            c_previous = charging_action_electricity_cost(
                action, previous.instance, previous.time_profile, previous.prices
            )
            current_emissions += e_current
            previous_emissions += e_previous
            current_cost += c_current
            previous_cost += c_previous
            run_current_emissions += e_current
            run_previous_emissions += e_previous
            run_current_cost += c_current
            run_previous_cost += c_previous
        run_rows.append(
            {
                "run_id": run_id,
                "first_depot_action_count": len(actions),
                "first_minus1_energy_kwh": sum(
                    float(action.energy_kwh)
                    for action in actions
                    if int(action.charge_day_offset) == -1
                ),
                "current_same_day_emissions_kg": run_current_emissions,
                "previous_day_profile_emissions_kg": run_previous_emissions,
                "current_same_day_cost_cny": run_current_cost,
                "previous_day_profile_cost_cny": run_previous_cost,
                "violation_types": [str(item.type) for item in violations],
            }
        )

    raw_rows = list(
        csv.DictReader((T10 / "raw_runs.csv").open(newline="", encoding="utf-8"))
    )
    service_pass = all(
        int(row["completed_customer_count"]) == int(row["required_customer_count"])
        and float(row["completed_demand"]) == float(row["required_demand"])
        for row in raw_rows
    )

    positive_path = (
        REPO
        / "docs/handoff/eval_chain_carbon_consistency_20260804/solution_witnesses.json"
    )
    positive_runs = json.loads(positive_path.read_text(encoding="utf-8"))["runs"]
    positive_rows = {}
    for run_id in (
        "C_seed2_budget1000",
        "C_seed1_budget100",
        "C_seed3_budget1000",
    ):
        solution = t7._solution_from_payload(positive_runs[run_id]["solution"])
        violations = check_solution(solution, current.instance, current.prices)
        positive_rows[run_id] = {
            "violation_types": [str(item.type) for item in violations],
            "charging_trip_overlap_count": sum(
                item.type == CHARGING_TRIP_OVERLAP for item in violations
            ),
        }

    sample_solution = t7._solution_from_payload(
        runs["C_seed2_budget1000"]["solution"]
    )
    sample_action = next(
        action
        for action in sample_solution.charging_actions
        if action.vehicle_id == "EV_D_beijing_1#T1"
    )
    sample_profile = time_profile_rows_for_node(
        current.instance, sample_action.station_id, current.time_profile
    )
    sample_profile_rows = []
    for slot in charging_action_slot_breakdown(
        sample_action,
        current.instance,
        current.prices,
        n_slots=len(sample_profile),
        cyclic=True,
    ):
        row = carbon_profile_row_for_slot(sample_profile, int(slot.slot_index))
        sample_profile_rows.append(
            {
                "slot_index_0_based": int(slot.slot_index),
                "half_hour_slot": int(row["half_hour_slot"]),
                "date": row["date"],
                "city": row["city"],
                "horizon_second_start": row["horizon_second_start"],
                "energy_kwh": float(slot.y_skt_kwh),
                "actual_gco2_per_kwh": float(row["actual_gco2_per_kwh"]),
                "depot_energy_cny_per_kwh": float(
                    row["depot_energy_cny_per_kwh"]
                ),
            }
        )

    print(
        json.dumps(
            {
                "task_id": "T11-INTERTRIP-CHARGING-FIX-NARROWING",
                "read_only": True,
                "t10_run_count": len(runs),
                "t10_public_action_count": public_action_count,
                "t10_current_checker_violation_count": t10_violation_count,
                "t10_service_redline_pass": service_pass,
                "first_depot_actions": first_actions_total,
                "first_minus1_actions": first_minus1_actions,
                "first_minus1_energy_kwh": first_minus1_energy,
                "current_code_profile_date": SCENARIO_DATE,
                "previous_date_profile": PREVIOUS_DATE,
                "current_code_same_day_emissions_kg": current_emissions,
                "previous_day_profile_counterfactual_emissions_kg": previous_emissions,
                "same_day_minus_previous_day_emissions_kg": current_emissions
                - previous_emissions,
                "current_code_same_day_cost_cny": current_cost,
                "previous_day_profile_counterfactual_cost_cny": previous_cost,
                "positive_witnesses": positive_rows,
                "sample_action": {
                    "vehicle_id": sample_action.vehicle_id,
                    "station_id": sample_action.station_id,
                    "charge_day_offset": int(sample_action.charge_day_offset),
                    "charge_start_second": float(sample_action.charge_start_second),
                    "energy_kwh": float(sample_action.energy_kwh),
                    "profile_rows": sample_profile_rows,
                },
                "run_rows": run_rows,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
