#!/usr/bin/env python3
"""Deterministic post-processing for T5-CARBON-OBJ-PROBE."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment


OUT = Path(__file__).resolve().parent
TASK_ID = "T5-CARBON-OBJ-PROBE"
MARKER = "DRAFT_METHOD_AWAITING_USER_APPROVAL"
METRICS = (
    "full_model_objective_cny",
    "operating_cost_cny",
    "carbon_cost_cny",
    "fuel_direct_emissions_kg",
    "charging_emissions_kg",
    "system_emissions_kg",
    "enabled_physical_vehicles",
    "assigned_cv",
    "assigned_ev",
    "total_trips",
    "total_distance_m",
    "total_distance_km",
    "charging_energy_kwh",
    "charging_cost_cny",
    "completed_customer_count",
    "completed_demand",
)


def atomic_json(path: Path, payload: Any) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = tuple(rows[0]) if rows else ()
    with tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        json.dumps(
                            value,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                        if isinstance(value, (list, dict, tuple))
                        else value
                    )
                    for key, value in row.items()
                }
            )
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def _group_metadata(witness: dict[str, Any]) -> dict[str, tuple[str, str]]:
    return {
        str(group["canonical_vehicle"]): (
            str(group["vehicle_type"]),
            str(group["home_depot_id"]),
        )
        for group in witness["route_structure"]
    }


def _vehicle_customer_sets(
    witness: dict[str, Any],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for customer, vehicle in witness["customer_assignment"].items():
        result[str(vehicle)].add(str(customer))
    for group in witness["route_structure"]:
        result.setdefault(str(group["canonical_vehicle"]), set())
    return dict(result)


def minimum_relabel_assignment_changes(
    baseline: dict[str, Any],
    comparison: dict[str, Any],
) -> tuple[int, list[str], dict[str, str]]:
    base_sets = _vehicle_customer_sets(baseline)
    comp_sets = _vehicle_customer_sets(comparison)
    base_meta = _group_metadata(baseline)
    comp_meta = _group_metadata(comparison)
    base_labels = sorted(base_sets)
    comp_labels = sorted(comp_sets)
    size = max(len(base_labels), len(comp_labels))
    weights = np.zeros((size, size), dtype=float)
    compatible = np.zeros((size, size), dtype=bool)
    for left, base_label in enumerate(base_labels):
        for right, comp_label in enumerate(comp_labels):
            if base_meta[base_label] == comp_meta[comp_label]:
                compatible[left, right] = True
                weights[left, right] = len(
                    base_sets[base_label] & comp_sets[comp_label]
                )
            else:
                weights[left, right] = -1_000_000.0
    rows, cols = linear_sum_assignment(weights, maximize=True)
    comp_to_base: dict[str, str] = {}
    for left, right in zip(rows, cols, strict=True):
        if (
            left < len(base_labels)
            and right < len(comp_labels)
            and compatible[left, right]
        ):
            comp_to_base[comp_labels[right]] = base_labels[left]
    base_assignment = {
        str(customer): str(vehicle)
        for customer, vehicle in baseline["customer_assignment"].items()
    }
    comp_assignment = {
        str(customer): str(vehicle)
        for customer, vehicle in comparison["customer_assignment"].items()
    }
    if set(base_assignment) != set(comp_assignment):
        raise RuntimeError("paired solutions have different customer sets")
    changed = sorted(
        customer
        for customer in base_assignment
        if comp_to_base.get(comp_assignment[customer])
        != base_assignment[customer]
    )
    return len(changed), changed, dict(sorted(comp_to_base.items()))


def _route_counter(witness: dict[str, Any]) -> Counter[tuple[Any, ...]]:
    result: Counter[tuple[Any, ...]] = Counter()
    for group in witness["route_structure"]:
        for trip in group["trips"]:
            result[
                (
                    group["vehicle_type"],
                    group["home_depot_id"],
                    tuple(trip),
                )
            ] += 1
    return result


def _counter_symdiff_size(
    left: Counter[tuple[Any, ...]],
    right: Counter[tuple[Any, ...]],
) -> int:
    return sum(abs(left[key] - right[key]) for key in set(left) | set(right))


def _slot_index() -> dict[tuple[str, int, int], list[float]]:
    result: dict[tuple[str, int, int], list[float]] = {}
    with (OUT / "slot_distribution.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        for row in csv.DictReader(handle):
            key = (row["arm"], int(row["budget"]), int(row["seed"]))
            result.setdefault(key, [0.0] * 48)[
                int(row["hourly_calendar_row"]) - 1
            ] = float(row["charging_kwh"])
    if any(len(values) != 48 for values in result.values()):
        raise RuntimeError("slot distribution does not contain 48 slots")
    return result


def main() -> int:
    state = json.loads((OUT / "runner_state.json").read_text(encoding="utf-8"))
    if state["terminal_status"] != "RUNNER_COMPLETE":
        raise RuntimeError("runner did not complete")
    if state["run_count"] != 18:
        raise RuntimeError("runner does not contain 18 runs")
    witness_payload = json.loads(
        (OUT / "solution_witnesses.json").read_text(encoding="utf-8")
    )
    witnesses = witness_payload["runs"]
    run_index = {
        (row["arm"], int(row["budget"]), int(row["seed"])): row
        for row in state["runs"]
    }
    if len(run_index) != 18:
        raise RuntimeError("paired run key count is not 18")
    slots = _slot_index()
    comparisons: list[dict[str, Any]] = []
    for budget in (100, 1_000):
        for seed in (1, 2, 3):
            baseline_row = run_index[("O", budget, seed)]
            baseline = witnesses[baseline_row["run_id"]]
            base_arcs = {
                tuple(value) for value in baseline["arc_set"]
            }
            base_routes = _route_counter(baseline)
            base_slots = slots[("O", budget, seed)]
            for arm in ("C", "P"):
                row = run_index[(arm, budget, seed)]
                compared = witnesses[row["run_id"]]
                comp_arcs = {
                    tuple(value) for value in compared["arc_set"]
                }
                assignment_change_count, changed_customers, relabel = (
                    minimum_relabel_assignment_changes(
                        baseline,
                        compared,
                    )
                )
                comp_slots = slots[(arm, budget, seed)]
                slot_l1 = sum(
                    abs(left - right)
                    for left, right in zip(base_slots, comp_slots, strict=True)
                )
                comparison = {
                    "task_id": TASK_ID,
                    "draft_status": MARKER,
                    "comparison": f"{arm}-O",
                    "arm": arm,
                    "baseline_arm": "O",
                    "budget": budget,
                    "seed": seed,
                    "arm_run_id": row["run_id"],
                    "baseline_run_id": baseline_row["run_id"],
                    "arm_route_signature_sha256": row[
                        "route_signature_sha256"
                    ],
                    "baseline_route_signature_sha256": baseline_row[
                        "route_signature_sha256"
                    ],
                    "route_signature_changed": (
                        row["route_signature_sha256"]
                        != baseline_row["route_signature_sha256"]
                    ),
                    "route_count_same": (
                        int(row["route_count"])
                        == int(baseline_row["route_count"])
                    ),
                    "arm_route_count": int(row["route_count"]),
                    "baseline_route_count": int(baseline_row["route_count"]),
                    "route_multiset_symmetric_difference": (
                        _counter_symdiff_size(
                            base_routes,
                            _route_counter(compared),
                        )
                    ),
                    "customer_to_vehicle_assignment_changes": (
                        assignment_change_count
                    ),
                    "changed_customer_ids": changed_customers,
                    "vehicle_relabel_map_to_baseline": relabel,
                    "directed_arc_set_symmetric_difference": len(
                        base_arcs ^ comp_arcs
                    ),
                    "arm_directed_arc_count": len(comp_arcs),
                    "baseline_directed_arc_count": len(base_arcs),
                    "slot_energy_l1_kwh": slot_l1,
                    "energy_relocated_half_l1_kwh": 0.5 * slot_l1,
                    "midday_12_15_kwh_arm": sum(comp_slots[24:30]),
                    "midday_12_15_kwh_baseline": sum(base_slots[24:30]),
                    "delta_midday_12_15_kwh": (
                        sum(comp_slots[24:30]) - sum(base_slots[24:30])
                    ),
                    "system_emissions_reduction_vs_O_kg": (
                        float(baseline_row["system_emissions_kg"])
                        - float(row["system_emissions_kg"])
                    ),
                }
                for metric in METRICS:
                    comparison[f"delta_{metric}"] = (
                        float(row[metric]) - float(baseline_row[metric])
                    )
                comparisons.append(comparison)
    atomic_csv(OUT / "route_diff.csv", comparisons)

    adverse_c = [
        row
        for row in comparisons
        if row["arm"] == "C"
        and (
            row["delta_operating_cost_cny"] > 1.0e-9
            or row["delta_system_emissions_kg"] > 1.0e-9
        )
    ]
    p_distribution = [
        {
            "budget": row["budget"],
            "seed": row["seed"],
            "slot_distribution_changed": row["slot_energy_l1_kwh"] > 1.0e-9,
            "slot_energy_l1_kwh": row["slot_energy_l1_kwh"],
            "energy_relocated_half_l1_kwh": row[
                "energy_relocated_half_l1_kwh"
            ],
            "delta_midday_12_15_kwh": row["delta_midday_12_15_kwh"],
        }
        for row in comparisons
        if row["arm"] == "P"
    ]
    c_by_pair = {
        (row["budget"], row["seed"]): row
        for row in comparisons
        if row["arm"] == "C"
    }
    p_by_pair = {
        (row["budget"], row["seed"]): row
        for row in comparisons
        if row["arm"] == "P"
    }
    c_vs_p = []
    for key in sorted(c_by_pair):
        c_row = c_by_pair[key]
        p_row = p_by_pair[key]
        c_reduction = c_row["system_emissions_reduction_vs_O_kg"]
        p_reduction = p_row["system_emissions_reduction_vs_O_kg"]
        c_vs_p.append(
            {
                "budget": key[0],
                "seed": key[1],
                "c_emissions_reduction_kg": c_reduction,
                "p_emissions_reduction_kg": p_reduction,
                "larger_reduction_arm": (
                    "C"
                    if c_reduction > p_reduction + 1.0e-9
                    else (
                        "P"
                        if p_reduction > c_reduction + 1.0e-9
                        else "TIE"
                    )
                ),
                "c_operating_cost_delta_cny": c_row[
                    "delta_operating_cost_cny"
                ],
                "p_operating_cost_delta_cny": p_row[
                    "delta_operating_cost_cny"
                ],
            }
        )
    summary = {
        "schema": "resetp.t5-carbon-objective-probe-analysis.v1",
        "task_id": TASK_ID,
        "draft_status": MARKER,
        "run_count": 18,
        "comparison_count": len(comparisons),
        "all_full_legal": all(
            row["status"] == "PASS_FULL_LEGAL_SOLUTION"
            and int(row["full_violation_count"]) == 0
            for row in state["runs"]
        ),
        "all_customer_and_demand_complete": all(
            int(row["completed_customer_count"])
            == int(row["required_customer_count"])
            and math.isclose(
                float(row["completed_demand"]),
                float(row["required_demand"]),
                rel_tol=0.0,
                abs_tol=1.0e-9,
            )
            for row in state["runs"]
        ),
        "comparisons": comparisons,
        "c_adverse_pairs": adverse_c,
        "p_distribution_checks": p_distribution,
        "c_vs_p": c_vs_p,
    }
    atomic_json(OUT / "analysis_summary.json", summary)
    print(
        f"ANALYSIS_COMPLETE comparisons={len(comparisons)} "
        f"c_adverse={len(adverse_c)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
