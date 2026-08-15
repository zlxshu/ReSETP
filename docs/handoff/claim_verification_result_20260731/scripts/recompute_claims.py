#!/usr/bin/env python3
"""Read-only independent recomputations for CLAIM-VERIFICATION-20260731.

The script prints JSON to stdout and never writes outside stdout.  It reads only
the original code, input, and result artifacts named by the verification task.
"""

from __future__ import annotations

import ast
import csv
import functools
import hashlib
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any


getcontext().prec = 80
ROOT = Path(__file__).resolve().parents[4]


def read_json(relative: str | Path) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def read_csv(relative: str | Path) -> list[dict[str, str]]:
    with (ROOT / relative).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def dec(text: Any) -> Decimal:
    return Decimal(str(text))


def dstr(value: Decimal) -> str:
    return format(value, "f")


def clean_json_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.glob("*.json")
        if not path.name.startswith("._")
    )


def clean_csv_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.glob("*.csv")
        if not path.name.startswith("._")
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def recompute_e2() -> dict[str, Any]:
    base = Path("baselines/algorithm_prototypes/china81_vs_opensource_20260727")
    raw = read_json(base / "raw_runs.json")
    grouped: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in raw:
        grouped[(row["instance_id"], int(row["seed"]))][row["arm"]] = row

    win_tie_loss = Counter()
    improvements: list[Decimal] = []
    improvements_float: list[float] = []
    transitions = {name: Counter() for name in ("O_to_F", "F_to_E", "E_to_M", "M_to_MV")}
    monotone = 0
    for arms in grouped.values():
        costs = {arm: dec(arms[arm]["final_cost"]) for arm in ("O", "F", "E", "M", "MV")}
        if costs["MV"] < costs["O"]:
            win_tie_loss["win"] += 1
        elif costs["MV"] > costs["O"]:
            win_tie_loss["loss"] += 1
        else:
            win_tie_loss["tie"] += 1
        improvements.append(Decimal(100) * (costs["O"] - costs["MV"]) / costs["O"])
        o_float = float(arms["O"]["final_cost"])
        mv_float = float(arms["MV"]["final_cost"])
        improvements_float.append(100.0 * (o_float - mv_float) / o_float)
        if costs["O"] >= costs["F"] >= costs["E"] >= costs["M"] >= costs["MV"]:
            monotone += 1
        for left, right in (("O", "F"), ("F", "E"), ("E", "M"), ("M", "MV")):
            label = f"{left}_to_{right}"
            if costs[right] < costs[left]:
                transitions[label]["improve"] += 1
            elif costs[right] > costs[left]:
                transitions[label]["regress"] += 1
            else:
                transitions[label]["tie"] += 1

    sources = Counter(row["data_source"] for row in raw)
    budgets = defaultdict(Counter)
    for row in raw:
        budgets[row["arm"]][(row["budget_rule"], row.get("stop_iterations"))] += 1
    float_mean = sum(improvements_float) / len(improvements_float)
    decision_mean = read_json(base / "decision.json")[
        "mean_MV_improvement_percent_vs_O"
    ]
    decimal_mean = sum(improvements) / len(improvements)
    return {
        "raw_rows": len(raw),
        "paired_units": len(grouped),
        "MV_vs_O": dict(sorted(win_tie_loss.items())),
        "mean_MV_improvement_percent_vs_O_decimal_from_serialized_costs": dstr(decimal_mean),
        "mean_MV_improvement_percent_vs_O_float": repr(float_mean),
        "decision_mean_value": repr(decision_mean),
        "float_difference_from_decision": repr(float_mean - decision_mean),
        "decimal_difference_from_serialized_decision": dstr(
            decimal_mean - Decimal(repr(decision_mean))
        ),
        "monotone_staircase_units": monotone,
        "transition_counts": {key: dict(value) for key, value in transitions.items()},
        "data_source_counts": dict(sources),
        "budget_rule_counts_by_arm": {
            arm: {str(key): count for key, count in counts.items()}
            for arm, counts in budgets.items()
        },
    }


def recompute_e4() -> dict[str, Any]:
    relative = Path("baselines/china_e3_e7/e4_carbon_timing_20260729/raw_runs.csv")
    rows = read_csv(relative)
    asap_decimal = sum(dec(row["asap_charging_emissions_kg"]) for row in rows)
    carbon_decimal = sum(dec(row["carbon_charging_emissions_kg"]) for row in rows)
    reduction_decimal = Decimal(100) * (asap_decimal - carbon_decimal) / asap_decimal
    asap_cost_decimal = sum(
        dec(row["asap_charging_electricity_cost_cny"]) for row in rows
    )
    carbon_cost_decimal = sum(
        dec(row["carbon_charging_electricity_cost_cny"]) for row in rows
    )
    cost_change_decimal = Decimal(100) * (
        carbon_cost_decimal - asap_cost_decimal
    ) / asap_cost_decimal

    # Mirror the source runner's Python-float accumulation over its retained rows.
    asap_float = sum(float(row["asap_charging_emissions_kg"]) for row in rows)
    carbon_float = sum(float(row["carbon_charging_emissions_kg"]) for row in rows)
    reduction_float = 100.0 * (asap_float - carbon_float) / asap_float
    decision_value = read_json(relative.parent / "decision.json")["primary_endpoint_value"]
    return {
        "data_rows": len(rows),
        "asap_sum_decimal": dstr(asap_decimal),
        "carbon_sum_decimal": dstr(carbon_decimal),
        "asap_electricity_cost_sum_decimal": dstr(asap_cost_decimal),
        "carbon_electricity_cost_sum_decimal": dstr(carbon_cost_decimal),
        "charging_electricity_cost_change_pct_decimal": dstr(
            cost_change_decimal
        ),
        "reduction_pct_decimal_from_csv_strings": dstr(reduction_decimal),
        "reduction_pct_float_in_csv_order": repr(reduction_float),
        "decision_value": repr(decision_value),
        "float_difference_from_decision": repr(reduction_float - decision_value),
        "decimal_difference_from_serialized_decision": dstr(
            reduction_decimal - Decimal(repr(decision_value))
        ),
        "search_candidate_count_values": sorted({row["search_candidate_count"] for row in rows}),
        "row_invariants_all_true": all(
            row["fixed_invariants_match"] == "1"
            and row["asap_violation_count"] == "0"
            and row["carbon_violation_count"] == "0"
            for row in rows
        ),
    }


def recompute_e5() -> dict[str, Any]:
    rows = read_csv("baselines/china_e3_e7/e5_nonlinear_final_20260730/charging_sessions.csv")
    key_fields = ("instance_id", "seed", "vehicle_id", "session_index")
    by_arm: dict[str, dict[tuple[str, ...], dict[str, str]]] = defaultdict(dict)
    for row in rows:
        key = tuple(row[field] for field in key_fields)
        by_arm[row["arm"]][key] = row
    left = by_arm["L100_control"]
    right = by_arm["NL90_mild"]
    shared_equal = {
        field: all(left[key][field] == right[key][field] for key in left)
        for field in ("start_soc_pct", "end_soc_pct", "energy_kwh")
    }
    end_values = sorted(dec(row["end_soc_pct"]) for row in rows)
    median = (end_values[97] + end_values[98]) / Decimal(2)
    mean = sum(end_values) / len(end_values)
    end_high = {
        tuple(row[field] for field in ("arm",) + key_fields)
        for row in rows
        if dec(row["end_soc_pct"]) >= Decimal("99.9")
    }
    literal_nonzero = {
        tuple(row[field] for field in ("arm",) + key_fields)
        for row in rows
        if dec(row["nonlinear_minus_linear_seconds"]) != 0
    }
    positive = {
        tuple(row[field] for field in ("arm",) + key_fields)
        for row in rows
        if dec(row["nonlinear_minus_linear_seconds"]) > 0
    }
    significant = {
        tuple(row[field] for field in ("arm",) + key_fields)
        for row in rows
        if abs(dec(row["nonlinear_minus_linear_seconds"])) > Decimal("1e-9")
    }
    affected_rows = [row for row in rows if dec(row["end_soc_pct"]) >= Decimal("99.9")]
    schedule_audit = recompute_e5_schedule_audit()
    return {
        "session_rows": len(rows),
        "rows_by_arm": {arm: len(mapping) for arm, mapping in by_arm.items()},
        "paired_key_sets_equal": set(left) == set(right),
        "paired_serialized_values_equal": shared_equal,
        "start_soc_zero_count": sum(dec(row["start_soc_pct"]) == 0 for row in rows),
        "charge_start_zero_count": sum(dec(row["charge_start_second"]) == 0 for row in rows),
        "end_soc_median_decimal": dstr(median),
        "end_soc_mean_decimal": dstr(mean),
        "end_soc_ge_99_9_count": len(end_high),
        "delta_literal_nonzero_count": len(literal_nonzero),
        "delta_positive_count": len(positive),
        "delta_abs_gt_1e_9_count": len(significant),
        "end_high_equals_literal_nonzero": end_high == literal_nonzero,
        "end_high_equals_positive": end_high == positive,
        "end_high_equals_abs_gt_1e_9": end_high == significant,
        "affected_delta_values": sorted({row["nonlinear_minus_linear_seconds"] for row in affected_rows}),
        "affected_linear_duration_values": sorted({row["linear_duration_seconds"] for row in affected_rows}),
        "affected_start_soc_values": sorted({row["start_soc_pct"] for row in affected_rows}),
        "affected_end_soc_values": sorted({row["end_soc_pct"] for row in affected_rows}),
        "affected_charge_start_values": sorted({row["charge_start_second"] for row in affected_rows}),
        "literal_nonzero_not_high_examples": sorted(literal_nonzero - end_high)[:10],
        "schedule_audit": schedule_audit,
    }


@functools.lru_cache(maxsize=None)
def china81_bundle(instance_id: str) -> Any:
    solver_src = str(ROOT / "solver/src")
    helper_src = str(ROOT / "baselines/china_e3_e7")
    if solver_src not in sys.path:
        sys.path.insert(0, solver_src)
    if helper_src not in sys.path:
        sys.path.insert(0, helper_src)
    from setp_solver.china81 import load_china81_bundle

    return load_china81_bundle(ROOT, instance_id)


def recompute_e5_schedule_audit() -> dict[str, Any]:
    """Replay the 20 L100 plans under L100 and NL90 schedule physics.

    The two arm session tables are pairwise identical, so the 18 affected L100
    sessions represent the same 18 physical decisions repeated in NL90 rows.
    """

    solver_src = str(ROOT / "solver/src")
    helper_src = str(ROOT / "baselines/china_e3_e7")
    if solver_src not in sys.path:
        sys.path.insert(0, solver_src)
    if helper_src not in sys.path:
        sys.path.insert(0, helper_src)
    from check_e5_nonlinear_20260729 import curve_bundle, project_to_nl90, solution_from_payload
    from setp_solver.search.multitrip_schedule import prepare_multitrip_solution

    plan_dir = ROOT / "baselines/china_e3_e7/e5_nonlinear_v4_20260730/formal/plans"
    plans = sorted(path for path in plan_dir.glob("*__L100_control.json") if not path.name.startswith("._"))
    affected_slacks: list[Decimal] = []
    changed_trip_fields: list[dict[str, Any]] = []
    affected_records: list[dict[str, Any]] = []
    for path in plans:
        payload = json.loads(path.read_text(encoding="utf-8"))
        instance_id = payload["instance_id"]
        solution = solution_from_payload(payload["solution"])
        bundle = china81_bundle(instance_id)
        linear_bundle = curve_bundle(bundle, "L100_control")
        nonlinear_bundle = curve_bundle(bundle, "NL90_mild")
        linear_prepared, linear_certificate = prepare_multitrip_solution(
            solution, linear_bundle.instance, linear_bundle.prices
        )
        replay, sessions, _, _ = project_to_nl90(solution, nonlinear_bundle)
        nonlinear_prepared, nonlinear_certificate = prepare_multitrip_solution(
            replay, nonlinear_bundle.instance, nonlinear_bundle.prices
        )
        old_to_linear_id = {
            old.vehicle_id: new.vehicle_id
            for old, new in zip(solution.routes, linear_prepared.routes)
        }
        old_to_nonlinear_id = {
            old.vehicle_id: new.vehicle_id
            for old, new in zip(solution.routes, nonlinear_prepared.routes)
        }
        linear_trips = {trip.route_id: trip for trip in linear_certificate.trips}
        nonlinear_trips = {trip.route_id: trip for trip in nonlinear_certificate.trips}
        for old_id in old_to_linear_id:
            linear_trip = linear_trips[old_to_linear_id[old_id]]
            nonlinear_trip = nonlinear_trips[old_to_nonlinear_id[old_id]]
            for field in ("departure_second", "return_second", "recharge_end_second"):
                left = getattr(linear_trip, field)
                right = getattr(nonlinear_trip, field)
                if left != right:
                    changed_trip_fields.append(
                        {
                            "plan": path.name,
                            "vehicle_id": old_id,
                            "field": field,
                            "linear": repr(left),
                            "nonlinear": repr(right),
                        }
                    )
        for session in sessions:
            if dec(session["end_soc_pct"]) < Decimal("99.9"):
                continue
            old_id = session["vehicle_id"]
            nonlinear_trip = nonlinear_trips[old_to_nonlinear_id[old_id]]
            charge_end = (
                dec(session["charge_start_second"])
                + Decimal(int(session["charge_day_offset"])) * Decimal(86400)
                + dec(session["nonlinear_duration_seconds"])
            )
            slack = dec(nonlinear_trip.departure_second) - charge_end
            affected_slacks.append(slack)
            affected_records.append(
                {
                    "plan": path.name,
                    "vehicle_id": old_id,
                    "nonlinear_charge_end_second": dstr(charge_end),
                    "first_trip_departure_second": repr(nonlinear_trip.departure_second),
                    "slack_seconds": dstr(slack),
                }
            )
    return {
        "L100_plan_count": len(plans),
        "affected_L100_session_count": len(affected_slacks),
        "affected_all_arm_row_count_by_pair_duplication": 2 * len(affected_slacks),
        "slack_min_seconds": dstr(min(affected_slacks)),
        "slack_max_seconds": dstr(max(affected_slacks)),
        "slack_values": sorted({dstr(value) for value in affected_slacks}),
        "changed_trip_field_count": len(changed_trip_fields),
        "changed_trip_fields": changed_trip_fields,
        "affected_records": affected_records,
    }


def recompute_e3() -> dict[str, Any]:
    base = Path("baselines/china_e3_e7/e3_zone_joint_20260731")
    assignments = read_csv(base / "input_assignments.csv")
    by_instance_arm = Counter((row["instance_id"], row["arm"]) for row in assignments)
    mismatches = [row for row in assignments if row["registered_differs_from_nearest"].lower() == "true"]
    unique_customers = {(row["instance_id"], row["customer_id"]) for row in assignments}
    depot_counts = Counter(
        (row["instance_id"], row["arm"], row["administrative_registered_depot"])
        for row in assignments
    )

    raw = read_csv(base / "raw_runs.csv")
    grouped: dict[str, dict[str, list[Decimal]]] = defaultdict(lambda: defaultdict(list))
    for row in raw:
        grouped[row["instance_id"]][row["arm"]].append(dec(row["total_cost_cny"]))
    instance_effects = {}
    instance_effects_float = {}
    for instance, arms in grouped.items():
        zone = sum(arms["ZONE"]) / len(arms["ZONE"])
        joint = sum(arms["JOINT"]) / len(arms["JOINT"])
        instance_effects[instance] = {
            "zone_mean_decimal": dstr(zone),
            "joint_mean_decimal": dstr(joint),
            "cost_effect_pct_decimal": dstr(Decimal(100) * (zone - joint) / zone),
        }
        zone_float = statistics.mean(float(value) for value in arms["ZONE"])
        joint_float = statistics.mean(float(value) for value in arms["JOINT"])
        instance_effects_float[instance] = 100.0 * (
            zone_float - joint_float
        ) / zone_float
    overall = sum(dec(value["cost_effect_pct_decimal"]) for value in instance_effects.values()) / len(instance_effects)
    overall_float = statistics.mean(instance_effects_float.values())

    pool_dir = ROOT / "baselines/china_e3_e7/e3_pooling_probe_20260731/raw_units"
    pool_rows = [json.loads(path.read_text(encoding="utf-8")) for path in clean_json_files(pool_dir)]
    pool_group: dict[int, dict[str, Decimal]] = defaultdict(dict)
    for row in pool_rows:
        pool_group[int(row["seed"])][row["arm"]] = dec(row["total_cost"])
    pool_effects = {}
    for seed, arms in sorted(pool_group.items()):
        pool_effects[str(seed)] = {
            "ZONE": dstr(arms["ZONE"]),
            "JOINT": dstr(arms["JOINT"]),
            "POOLED": dstr(arms["POOLED"]),
            "POOLED_vs_JOINT_change_pct": dstr(Decimal(100) * (arms["POOLED"] - arms["JOINT"]) / arms["JOINT"]),
            "POOLED_vs_JOINT_reduction_pct": dstr(Decimal(100) * (arms["JOINT"] - arms["POOLED"]) / arms["JOINT"]),
        }
    all81_mismatch = recompute_all81_mismatch()
    return {
        "assignment_rows": len(assignments),
        "assignment_rows_by_instance_arm": {str(key): value for key, value in by_instance_arm.items()},
        "unique_instance_customer_pairs": len(unique_customers),
        "registered_differs_true_count": len(mismatches),
        "depot_counts": {str(key): value for key, value in depot_counts.items()},
        "raw_rows": len(raw),
        "instance_cost_effects": instance_effects,
        "instance_cost_effects_float": {
            key: repr(value) for key, value in instance_effects_float.items()
        },
        "overall_cost_effect_pct_decimal": dstr(overall),
        "overall_cost_effect_pct_float": repr(overall_float),
        "pooling_probe": pool_effects,
        "all81_mismatch": all81_mismatch,
    }


def recompute_all81_mismatch() -> dict[str, Any]:
    catalog = read_csv(
        "data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723/instance_catalog.csv"
    )
    nonzero: dict[str, dict[str, Any]] = {}
    total_customers = 0
    total_mismatch = 0
    for row in catalog:
        instance_id = row["instance_id"]
        bundle = china81_bundle(instance_id)
        depots = sorted(
            node.node_id
            for node in bundle.instance.nodes
            if node.node_type.lower() == "d"
        )
        mismatch_rows = []
        for customer_id, registered in bundle.customer_home_depot.items():
            nearest = min(
                depots,
                key=lambda depot_id: (
                    float(bundle.instance.distance(depot_id, customer_id)),
                    depot_id,
                ),
            )
            if registered != nearest:
                mismatch_rows.append(
                    {
                        "customer_id": customer_id,
                        "registered": registered,
                        "nearest": nearest,
                        "registered_distance_m": repr(bundle.instance.distance(registered, customer_id)),
                        "nearest_distance_m": repr(bundle.instance.distance(nearest, customer_id)),
                    }
                )
        denominator = len(bundle.customer_home_depot)
        total_customers += denominator
        total_mismatch += len(mismatch_rows)
        if mismatch_rows:
            nonzero[instance_id] = {
                "mismatch_count": len(mismatch_rows),
                "customer_count": denominator,
                "mismatch_pct_decimal": dstr(Decimal(100) * len(mismatch_rows) / denominator),
                "rows": mismatch_rows,
            }
    return {
        "instance_count": len(catalog),
        "customer_count": total_customers,
        "mismatch_count": total_mismatch,
        "nonzero_instance_count": len(nonzero),
        "nonzero_instances": nonzero,
    }


def recompute_e6() -> dict[str, Any]:
    pool = read_csv("baselines/china_e3_e7/e6_fairness_v3_20260731/candidate_pool_summary.csv")
    instance_summary = read_csv(
        "baselines/china_e3_e7/e6_fairness_v3_20260731/instance_summary.csv"
    )
    allocation = read_csv("baselines/china_e3_e7/e6_allocation_20260731/raw_runs.csv")
    feasible = [row for row in allocation if row["participation_feasible_with_transfer"].lower() == "true"]
    infeasible = [row for row in allocation if row["participation_feasible_with_transfer"].lower() != "true"]
    transfers = [dec(row["shapley_transfer_B_to_A_cny"]) for row in feasible]
    savings = [dec(row["system_saving_delta_cny"]) for row in feasible]
    net_gains_guangzhou = [
        dec(row["shapley_reference_net_gain_vs_I_D_guangzhou_cny"])
        for row in feasible
    ]
    net_gains_shenzhen = [
        dec(row["shapley_reference_net_gain_vs_I_D_shenzhen_cny"])
        for row in feasible
    ]
    mean_transfer = sum(transfers) / len(transfers)
    mean_saving = sum(savings) / len(savings)
    mean_net_guangzhou = sum(net_gains_guangzhou) / len(net_gains_guangzhou)
    mean_net_shenzhen = sum(net_gains_shenzhen) / len(net_gains_shenzhen)
    pooled_net_gains = net_gains_guangzhou + net_gains_shenzhen
    mean_net_per_member = sum(pooled_net_gains) / len(pooled_net_gains)
    # The decision's primary fairness figure is the equal-weight mean of the
    # two already-aggregated instance rows.  Keep the pooled-unit calculation
    # separate because it is a different field in decision.json.
    fairness_by_instance: dict[str, list[Decimal]] = defaultdict(list)
    for row in pool:
        fairness_by_instance[row["instance_id"]].append(dec(row["fairness_cost_pct_F_vs_U"]))
    instance_fairness = {
        key: sum(values) / len(values) for key, values in fairness_by_instance.items()
    }
    summary_fairness = {
        row["instance_id"]: dec(row["fairness_cost_pct_F_vs_U"])
        for row in instance_summary
    }
    fairness_equal_instance = sum(summary_fairness.values()) / len(summary_fairness)
    fairness_pooled_unit = sum(instance_fairness.values()) / len(instance_fairness)
    return {
        "pool_rows": len(pool),
        "candidate_full_evaluation_events": sum(int(row["full_evaluation_event_count"]) for row in pool),
        "candidate_pool_unique_total": sum(int(row["candidate_pool_size_unique"]) for row in pool),
        "participation_satisfying_candidates_total": sum(int(row["participation_satisfying_candidate_count"]) for row in pool),
        "units_naturally_pareto": sum(int(row["participation_satisfying_candidate_count"]) > 0 for row in pool),
        "units_f_equals_i": sum(row["f_equals_i"].lower() == "true" for row in pool),
        "fairness_cost_pct_by_instance_summary_decimal": {
            key: dstr(value) for key, value in summary_fairness.items()
        },
        "fairness_cost_pct_equal_instance_decimal": dstr(fairness_equal_instance),
        "fairness_cost_pct_pooled_unit_decimal": dstr(fairness_pooled_unit),
        "allocation_rows": len(allocation),
        "allocation_feasible": len(feasible),
        "allocation_infeasible": len(infeasible),
        "mean_transfer_decimal": dstr(mean_transfer),
        "mean_saving_decimal": dstr(mean_saving),
        "ratio_of_means_decimal": dstr(mean_transfer / mean_saving),
        "mean_net_gain_D_guangzhou_decimal": dstr(mean_net_guangzhou),
        "mean_net_gain_D_shenzhen_decimal": dstr(mean_net_shenzhen),
        "mean_net_gain_per_member_pooled_decimal": dstr(
            mean_net_per_member
        ),
        "infeasible_units": [
            {
                "instance_id": row["instance_id"],
                "seed": row["seed"],
                "system_saving_delta_cny": row["system_saving_delta_cny"],
                "lower": row["core_transfer_lower_cny"],
                "upper": row["core_transfer_upper_cny"],
            }
            for row in infeasible
        ],
        "search_reruns_values": sorted({row["search_reruns"] for row in allocation}),
    }


def trigger_batches(events_payload: dict[str, Any]) -> list[dict[str, Any]]:
    events = sorted(events_payload["events"], key=lambda event: (float(event["t_appear"]), str(event["event_id"])))
    params = events_payload["rolling_parameters"]
    delta = float(params["delta_t_seconds"])
    q_bar = int(params["q_bar"])
    batches: list[dict[str, Any]] = [{"stage": 0, "trigger_time": 0.0, "trigger_reason": "initial", "events": []}]
    cursor = 0
    last_trigger = 0.0
    stage = 1
    while cursor < len(events):
        deadline = last_trigger + delta
        batch: list[dict[str, Any]] = []
        hit_q = False
        while cursor < len(events) and float(events[cursor]["t_appear"]) <= deadline:
            batch.append(events[cursor])
            cursor += 1
            if len(batch) >= q_bar:
                trigger_time = float(batch[-1]["t_appear"])
                batches.append({"stage": stage, "trigger_time": trigger_time, "trigger_reason": "q_bar", "events": batch})
                last_trigger = trigger_time
                stage += 1
                hit_q = True
                break
        if hit_q:
            continue
        if batch:
            batches.append({"stage": stage, "trigger_time": deadline, "trigger_reason": "delta_t", "events": batch})
            stage += 1
        last_trigger = deadline
    return batches


def parse_top_rejections(reason: str) -> list[tuple[str, int]] | None:
    match = re.search(r"top_rejections=(\[.*\])\)$", reason)
    if not match:
        return None
    value = ast.literal_eval(match.group(1))
    return [(str(message), int(count)) for message, count in value]


def recompute_e7() -> dict[str, Any]:
    base = ROOT / "baselines/china_e3_e7/e7_dynamic_v3_20260731/formal"
    tasks: list[dict[str, Any]] = []
    task_paths: list[Path] = []
    for scale in ("50c", "100c", "150c"):
        for path in clean_json_files(base / scale / "tasks"):
            task_paths.append(path)
            tasks.append(json.loads(path.read_text(encoding="utf-8")))

    status = Counter(row["status"] for row in tasks)
    status_by_scale = defaultdict(Counter)
    for row in tasks:
        status_by_scale[row["scale"]][row["status"]] += 1
    pass_rows = [row for row in tasks if row["status"] == "PASS"]
    fail_rows = [row for row in tasks if row["status"] == "LEGAL_INFEASIBLE"]
    rolling_fail = [row for row in fail_rows if row["arm"] != "STATIC_FIXED_RECOURSE"]
    static_all = [row for row in tasks if row["arm"] == "STATIC_FIXED_RECOURSE"]
    static_50 = [row for row in tasks if row["scale"] == "50c" and row["arm"] == "STATIC_FIXED_RECOURSE"]

    budget_formula_bad = [
        (row["scale"], row["algorithm_seed"], row["arm"], row["actual_evaluations"], row["completed_stage_count"])
        for row in rolling_fail
        if int(row["actual_evaluations"]) != int(row["completed_stage_count"]) * 1200 + 600
    ]
    group_reasons: dict[tuple[str, int], list[str]] = defaultdict(list)
    for row in rolling_fail:
        group_reasons[(row["scale"], int(row["algorithm_seed"]))].append(row["legal_infeasibility_reason"])
    reason_identical = {
        str(key): len(values) == 3 and len(set(values)) == 1
        for key, values in group_reasons.items()
    }

    top_shapes = Counter()
    top_messages = Counter()
    parse_failures: list[tuple[str, int, str]] = []
    for row in fail_rows:
        parsed = parse_top_rejections(row["legal_infeasibility_reason"])
        if parsed is None:
            top_shapes["no_top_rejections_list"] += 1
            continue
        top_shapes[f"list_len_{len(parsed)}_of_string_int_tuples"] += 1
        for message, count in parsed:
            top_messages[message] += count
            if not isinstance(message, str) or not isinstance(count, int):
                parse_failures.append((row["scale"], row["algorithm_seed"], row["arm"]))

    u1_rows = [row for row in rolling_fail if row["scale"] in {"100c", "150c"}]
    u1_shapes = Counter()
    u1_categories = Counter()
    u1_category_patterns = Counter()
    u1_patterns_by_scale: dict[str, Counter[tuple[str, ...]]] = defaultdict(Counter)
    for row in u1_rows:
        parsed = parse_top_rejections(row["legal_infeasibility_reason"])
        if parsed is None:
            u1_shapes["no_top_rejections_list"] += 1
            continue
        u1_shapes[f"list_len_{len(parsed)}_of_string_int_tuples"] += 1
        pattern: list[str] = []
        for message, count in parsed:
            if "no inherited asset" in message:
                category = "NO_INHERITED_ASSET"
            elif "backtracking exceeded" in message:
                category = "BACKTRACKING_LIMIT"
            elif "exceeds capacity" in message:
                category = "ROUTE_CAPACITY"
            else:
                category = "OTHER"
            pattern.append(category)
            u1_categories[category] += count
        u1_category_patterns[tuple(pattern)] += 1
        u1_patterns_by_scale[row["scale"]][tuple(pattern)] += 1

    budget_lock = read_json(
        "baselines/china_e3_e7/e7_dynamic_v3_20260731/budget_lock.json"
    )

    # Reconstruct every stream's trigger batches from the original event JSON.
    event_base = ROOT / "baselines/china_e3_e7/mechanism_foundation_20260730/inputs/e7_events"
    batch_audit: dict[tuple[str, int], dict[str, Any]] = {}
    most_negative: tuple[float, str, int, int, str] | None = None
    for scale, instance in (("50c", "cn-prd-50c-01-V2-LOCATIONS"), ("100c", "cn-prd-100c-02-V2-LOCATIONS"), ("150c", "cn-prd-150c-01-V2-LOCATIONS")):
        for stream in range(1, 6):
            payload = json.loads((event_base / instance / f"stream_seed{stream}.json").read_text(encoding="utf-8"))
            batches = trigger_batches(payload)
            expired = []
            for batch in batches[1:]:
                for event in batch["events"]:
                    if event["event_type"] != "add":
                        continue
                    slack = float(event["new_due_time"]) - float(batch["trigger_time"])
                    if slack < 0:
                        expired.append({
                            "stage": batch["stage"],
                            "event_id": event["event_id"],
                            "customer_id": event["customer_id"],
                            "due_minus_trigger": repr(slack),
                        })
                        candidate = (slack, scale, stream, int(batch["stage"]), str(event["customer_id"]))
                        if most_negative is None or candidate[0] < most_negative[0]:
                            most_negative = candidate
            batch_audit[(scale, stream)] = {
                "batch_count_excluding_initial": len(batches) - 1,
                "batch_event_counts": [len(batch["events"]) for batch in batches[1:]],
                "trigger_times": [repr(float(batch["trigger_time"])) for batch in batches[1:]],
                "expired_adds": expired,
                "first_expired_stage": min((row["stage"] for row in expired), default=None),
            }

    # Compare 50c stream-level failure stage to the first expired-add stage.
    fifty_matches = []
    for stream in range(1, 6):
        rows = [row for row in rolling_fail if row["scale"] == "50c" and int(row["stream_seed"]) == stream]
        stages = sorted({int(row["failure_stage"]) for row in rows})
        first_expired = batch_audit[("50c", stream)]["first_expired_stage"]
        defined_match = len(stages) == 1 and stages[0] == first_expired
        including_absent_match = defined_match or (
            not stages and first_expired is None
        )
        fifty_matches.append({
            "stream": stream,
            "rolling_failure_stages": stages,
            "first_expired_stage": first_expired,
            "defined_stage_match": defined_match,
            "including_absent_pair_match": including_absent_match,
            "failure_rows": len(rows),
        })

    nominal_sha_by_scale = {
        scale: sorted({row["nominal_plan_sha256"] for row in tasks if row["scale"] == scale})
        for scale in ("50c", "100c", "150c")
    }
    pass_costs = defaultdict(dict)
    for row in pass_rows:
        pass_costs[str(row["algorithm_seed"])][row["arm"]] = repr(row["final_total_cost"])

    fleet_rows = read_csv(
        "data/ChinaInstances/china81_finite_fleet_authority_v2_20260731/fleet_caps.csv"
    )
    instance_by_scale = {
        "50c": "cn-prd-50c-01-V2-LOCATIONS",
        "100c": "cn-prd-100c-02-V2-LOCATIONS",
        "150c": "cn-prd-150c-01-V2-LOCATIONS",
    }
    asset_pool_audit = {}
    for scale, instance_id in instance_by_scale.items():
        representative = next(row for row in tasks if row["scale"] == scale)
        plan_payload = json.loads((ROOT / representative["nominal_plan_path"]).read_text(encoding="utf-8"))
        solution = plan_payload.get("solution", plan_payload)
        physical_ids = {
            str(route["vehicle_id"]).split("#T", 1)[0]
            for route in solution["routes"]
        }
        legal_cap = sum(
            int(row["total_fleet_cap"])
            for row in fleet_rows
            if row["instance_id"] == instance_id
        )
        asset_pool_audit[scale] = {
            "instance_id": instance_id,
            "legal_total_fleet_cap": legal_cap,
            "nominal_used_physical_vehicle_count": len(physical_ids),
            "nominal_used_physical_vehicle_ids": sorted(physical_ids),
        }

    keys_fail = Counter()
    for row in fail_rows:
        keys_fail.update(row.keys())
    return {
        "task_json_count": len(tasks),
        "status_counts": dict(status),
        "status_by_scale": {key: dict(value) for key, value in status_by_scale.items()},
        "pass_rows": [
            {
                "scale": row["scale"],
                "seed": row["algorithm_seed"],
                "stream": row["stream_seed"],
                "arm": row["arm"],
                "has_feasible_key": "feasible" in row,
                "final_total_cost": repr(row["final_total_cost"]),
                "carbon_shift": row["carbon_aware_charging_shift_after_event"],
                "moved": row["moved_charge_actions_after_event"],
                "cross": row["cross_depot_reassignment_after_event"],
            }
            for row in pass_rows
        ],
        "fail_feasible_false": all(row.get("feasible") is False for row in fail_rows),
        "fail_final_cost_null": all(row.get("final_total_cost") is None for row in fail_rows),
        "stream_formula_holds": all(int(row["stream_seed"]) == ((int(row["algorithm_seed"]) - 1) % 5) + 1 for row in tasks),
        "static_50_count": len(static_50),
        "static_50_all_legal_infeasible": all(row["status"] == "LEGAL_INFEASIBLE" for row in static_50),
        "static_count_by_scale": dict(Counter(row["scale"] for row in static_all)),
        "static_total_count": len(static_all),
        "static_all_legal_infeasible": all(
            row["status"] == "LEGAL_INFEASIBLE" for row in static_all
        ),
        "pass_costs": dict(pass_costs),
        "rolling_fail_count": len(rolling_fail),
        "budget_formula_mismatches": budget_formula_bad,
        "rolling_failure_group_count": len(group_reasons),
        "rolling_reason_byte_identical_by_group": reason_identical,
        "rolling_reason_all_groups_identical": all(reason_identical.values()),
        "top_rejections_shapes": dict(top_shapes),
        "top_rejections_parse_failures": parse_failures,
        "top_rejection_aggregate_counts": dict(top_messages.most_common()),
        "u1_100c_150c_failure_audit": {
            "row_count": len(u1_rows),
            "failure_stage_values": sorted({int(row["failure_stage"]) for row in u1_rows}),
            "payload_null_count": sum(row.get("payload") is None for row in u1_rows),
            "physical_vehicle_ids_empty_count": sum(row.get("physical_vehicle_ids") == [] for row in u1_rows),
            "vehicle_count_null_count": sum(row.get("vehicle_count") is None for row in u1_rows),
            "distinct_reason_strings": len({row["legal_infeasibility_reason"] for row in u1_rows}),
            "top_rejections_shapes": dict(u1_shapes),
            "top_rejection_category_aggregate_counts": dict(u1_categories),
            "top_rejection_category_patterns": {
                str(key): value for key, value in u1_category_patterns.items()
            },
            "top_rejection_category_patterns_by_scale": {
                scale: {str(key): value for key, value in counts.items()}
                for scale, counts in u1_patterns_by_scale.items()
            },
        },
        "budget_lock_summary": {
            "status": budget_lock["status"],
            "attempt_count": len(budget_lock["attempts"]),
            "attempts": budget_lock["attempts"],
            "selected_per_search_pass_cap": budget_lock["selected_per_search_pass_cap"],
            "selected_total_stage_cap": budget_lock["selected_total_stage_cap"],
        },
        "event_batch_audit": {str(key): value for key, value in batch_audit.items()},
        "fifty_expiry_failure_comparison": fifty_matches,
        "fifty_expiry_failure_row_count": sum(
            row["failure_rows"] for row in fifty_matches
        ),
        "fifty_defined_expiry_stage_matches": sum(
            row["defined_stage_match"] for row in fifty_matches
        ),
        "fifty_matches_including_absent_pair": sum(
            row["including_absent_pair_match"] for row in fifty_matches
        ),
        "most_negative_due_minus_trigger": None if most_negative is None else {
            "seconds": repr(most_negative[0]),
            "scale": most_negative[1],
            "stream": most_negative[2],
            "stage": most_negative[3],
            "customer_id": most_negative[4],
        },
        "nominal_sha_unique_count_by_scale": {key: len(value) for key, value in nominal_sha_by_scale.items()},
        "nominal_sha_values_by_scale": nominal_sha_by_scale,
        "asset_pool_audit": asset_pool_audit,
        "failure_field_presence_counts": dict(keys_fail),
    }


def compare_json_without_schema(left: Any, right: Any) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        left_keys = set(left) - {"schema"}
        right_keys = set(right) - {"schema"}
        return left_keys == right_keys and all(
            compare_json_without_schema(left[key], right[key]) for key in left_keys
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            compare_json_without_schema(a, b) for a, b in zip(left, right)
        )
    return left == right


def recompute_infrastructure() -> dict[str, Any]:
    v1 = Path("data/ChinaInstances/china81_finite_fleet_authority_v1_20260723")
    v2 = Path("data/ChinaInstances/china81_finite_fleet_authority_v2_20260731")
    caps1 = read_csv(v1 / "fleet_caps.csv")
    caps2 = read_csv(v2 / "fleet_caps.csv")
    cap_key = lambda row: (row["instance_id"], row["depot_id"])
    map1 = {cap_key(row): row for row in caps1}
    map2 = {cap_key(row): row for row in caps2}
    cap_differences = []
    for key in sorted(set(map1) | set(map2)):
        if map1.get(key) != map2.get(key):
            cap_differences.append({"key": key, "v1": map1.get(key), "v2": map2.get(key)})

    witness1 = ROOT / v1 / "witnesses"
    witness2 = ROOT / v2 / "witnesses"
    witness_names = sorted(path.name for path in clean_json_files(witness1))
    witness_mismatches = []
    for name in witness_names:
        left = json.loads((witness1 / name).read_text(encoding="utf-8"))
        right = json.loads((witness2 / name).read_text(encoding="utf-8"))
        if not compare_json_without_schema(left, right):
            witness_mismatches.append(name)

    ev_route_audit = recompute_ev_witness_route_energy(caps2, witness2)
    calendar_path = Path(
        "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/"
        "tariff_carbon_hourly_calendar.csv"
    )
    if not (ROOT / calendar_path).is_file():
        matches = list((ROOT / "data/ChinaInstances").glob("**/tariff_carbon_hourly_calendar.csv"))
        if len(matches) != 1:
            raise RuntimeError(f"calendar candidates: {matches}")
        calendar_path = matches[0].relative_to(ROOT)
    calendar_rows = read_csv(calendar_path)
    gb_carbon_rows = read_csv(
        "data/Carbon/时变碳强度/Carbon_Intensity_Data.csv"
    )
    gb_actual_key = "Actual Carbon Intensity (gCO2/kWh)"
    gb_forecast_key = "Forecast Carbon Intensity (gCO2/kWh)"
    gb_differences = [
        dec(row[gb_actual_key]) - dec(row[gb_forecast_key])
        for row in gb_carbon_rows
    ]

    manifest_path = Path("data/Carbon/中国情景/cef_dataset_full_20260731/download_manifest.json")
    manifest = read_json(manifest_path)
    manifest_checks = []
    file_rows = manifest.get("files", manifest.get("downloads", []))
    for row in file_rows:
        rel = row.get("local_path") or row.get("path") or row.get("file")
        if rel is None and row.get("local_file"):
            rel = str(manifest_path.parent / row["local_file"])
        expected = row.get("md5") or row.get("expected_md5") or row.get("published_md5")
        path = ROOT / str(rel)
        actual = hashlib.md5(path.read_bytes()).hexdigest() if path.is_file() else None
        manifest_checks.append(
            {"path": str(rel), "expected_md5": expected, "actual_md5": actual, "matches": actual == expected}
        )
    return {
        "fleet_caps": {
            "v1_rows": len(caps1),
            "v2_rows": len(caps2),
            "key_sets_equal": set(map1) == set(map2),
            "row_differences": cap_differences,
            "v1_totals": {
                "R_d": sum(int(row["base_all_cv_routes_Rd"]) for row in caps1),
                "num_cv": sum(int(row["num_cv"]) for row in caps1),
                "num_ev": sum(int(row["num_ev"]) for row in caps1),
            },
            "v2_totals": {
                "R_d": sum(int(row["base_all_cv_routes_Rd"]) for row in caps2),
                "num_cv": sum(int(row["num_cv"]) for row in caps2),
                "num_ev": sum(int(row["num_ev"]) for row in caps2),
            },
            "reserve_factor_values": sorted({row["main_reserve_factor"] for row in caps2}),
            "num_ev_formula_violations": [
                cap_key(row)
                for row in caps2
                if int(row["num_ev"])
                != max(1, (int(row["base_all_cv_routes_Rd"]) + 3) // 4)
            ],
        },
        "witnesses": {
            "count": len(witness_names),
            "equal_excluding_schema_count": len(witness_names) - len(witness_mismatches),
            "mismatches_excluding_schema": witness_mismatches,
        },
        "ev_witness_route_audit": ev_route_audit,
        "calendar": {
            "path": str(calendar_path),
            "data_rows": len(calendar_rows),
            "fieldnames": list(calendar_rows[0]) if calendar_rows else [],
            "carbon_related_fieldnames": [
                key for key in (list(calendar_rows[0]) if calendar_rows else []) if "carbon" in key.lower()
            ],
        },
        "gb_actual_forecast": {
            "data_rows": len(gb_carbon_rows),
            "different_rows": sum(value != 0 for value in gb_differences),
            "equal_rows": sum(value == 0 for value in gb_differences),
            "actual_minus_forecast_min": dstr(min(gb_differences)),
            "actual_minus_forecast_max": dstr(max(gb_differences)),
        },
        "carbon_dataset_manifest": {
            "manifest_keys": sorted(manifest),
            "file_count": len(file_rows),
            "checks": manifest_checks,
            "all_md5_match": len(file_rows) == 7 and all(row["matches"] for row in manifest_checks),
        },
    }


def recompute_ev_witness_route_energy(
    caps: list[dict[str, str]], witness_dir: Path
) -> dict[str, Any]:
    solver_src = str(ROOT / "solver/src")
    if solver_src not in sys.path:
        sys.path.insert(0, solver_src)
    from setp_solver.cost import _arc_loads, ev_instance_arc_energy_kwh

    caps_by_instance_depot = {
        (row["instance_id"], row["depot_id"]): row for row in caps
    }
    depot_rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    for witness_path in clean_json_files(witness_dir):
        witness = json.loads(witness_path.read_text(encoding="utf-8"))
        instance_id = witness["instance_id"]
        bundle = china81_bundle(instance_id)
        node_lookup = {node.node_id: node for node in bundle.instance.nodes}
        battery = bundle.instance.battery_capacity_kwh(fallback=bundle.prices.B_battery_kwh)
        ev_payload = bundle.instance.payload_capacity_kg(
            "ev", fallback=float(bundle.prices.Q_capacity)
        )
        by_depot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for route in witness["routes"]:
            sequence = list(route["node_sequence"])
            loads = _arc_loads(sequence, node_lookup)
            energy = sum(
                ev_instance_arc_energy_kwh(
                    bundle.instance,
                    from_id,
                    to_id,
                    loads[index],
                    bundle.prices,
                )
                for index, (from_id, to_id) in enumerate(zip(sequence, sequence[1:]))
            )
            max_load = max(loads, default=0.0)
            row = {
                "instance_id": instance_id,
                "depot_id": route["home_depot_id"],
                "witness_vehicle_id": route["vehicle_id"],
                "ev_energy_kwh": repr(energy),
                "battery_kwh": repr(battery),
                "max_load_kg": repr(max_load),
                "ev_payload_kg": repr(ev_payload),
                "energy_feasible": energy <= battery + 1e-9,
                "payload_feasible": max_load <= ev_payload + 1e-9,
                "both_feasible": energy <= battery + 1e-9 and max_load <= ev_payload + 1e-9,
            }
            route_rows.append(row)
            by_depot[route["home_depot_id"]].append(row)
        for depot_id, rows in sorted(by_depot.items()):
            cap = caps_by_instance_depot[(instance_id, depot_id)]
            num_ev = int(cap["num_ev"])
            energy_feasible = sum(row["energy_feasible"] for row in rows)
            both_feasible = sum(row["both_feasible"] for row in rows)
            depot_rows.append(
                {
                    "instance_id": instance_id,
                    "depot_id": depot_id,
                    "num_ev": num_ev,
                    "witness_route_count": len(rows),
                    "energy_feasible_route_count": energy_feasible,
                    "energy_and_payload_feasible_route_count": both_feasible,
                    "zero_energy_feasible_routes": energy_feasible == 0,
                    "energy_feasible_routes_less_than_num_ev": energy_feasible < num_ev,
                    "zero_energy_and_payload_feasible_routes": both_feasible == 0,
                    "both_feasible_routes_less_than_num_ev": both_feasible < num_ev,
                }
            )
    return {
        "instance_count": len({row["instance_id"] for row in depot_rows}),
        "depot_count": len(depot_rows),
        "route_count": len(route_rows),
        "battery_values_kwh": sorted({row["battery_kwh"] for row in route_rows}),
        "ev_payload_values_kg": sorted({row["ev_payload_kg"] for row in route_rows}),
        "depots_zero_energy_feasible": [
            {"instance_id": row["instance_id"], "depot_id": row["depot_id"], "num_ev": row["num_ev"]}
            for row in depot_rows
            if row["zero_energy_feasible_routes"]
        ],
        "depots_energy_feasible_less_than_num_ev": [
            row for row in depot_rows if row["energy_feasible_routes_less_than_num_ev"]
        ],
        "depots_zero_both_feasible": [
            {"instance_id": row["instance_id"], "depot_id": row["depot_id"], "num_ev": row["num_ev"]}
            for row in depot_rows
            if row["zero_energy_and_payload_feasible_routes"]
        ],
        "depots_both_feasible_less_than_num_ev": [
            row for row in depot_rows if row["both_feasible_routes_less_than_num_ev"]
        ],
        "route_energy_min_kwh": repr(min(float(row["ev_energy_kwh"]) for row in route_rows)),
        "route_energy_max_kwh": repr(max(float(row["ev_energy_kwh"]) for row in route_rows)),
        "route_rows": route_rows,
        "depot_rows": depot_rows,
    }


def main() -> None:
    output = {
        "E2": recompute_e2(),
        "E4": recompute_e4(),
        "E5": recompute_e5(),
        "E3": recompute_e3(),
        "E6": recompute_e6(),
        "E7": recompute_e7(),
        "INF": recompute_infrastructure(),
    }
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
