#!/usr/bin/env python3
"""Minimal T7 reproduction/recheck for O/C, budget 1000, seed 1.

``--mode pre-fix-replay`` rechecks the already archived T5 witness without
running search.  ``--mode fixed-run`` runs only the paired O/C validation
instead of the full 18-run matrix and prints both objective ledgers.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from t7_runner import _solution_from_payload, t5


def _bundles():
    from setp_solver.model_config import ModelConfig

    base = t5.load_china81_bundle(
        t5.REPO,
        t5.INSTANCE_ID,
        fleet_authority=t5.AUTHORITY,
        model_config=ModelConfig(
            strict_multitrip=True,
            depot_charger_capacity_mode="unbounded",
        ),
    )
    return t5.arm_bundles(base)


def _print_ledger(label, arm, solution, search_bundle, reporting_bundle):
    search_objective, search_breakdown, search_violations = (
        t5.exact_china81_score(solution, search_bundle)
    )
    final_objective, final_breakdown, final_violations = (
        t5.exact_china81_score(solution, reporting_bundle)
    )
    if search_violations or final_violations:
        raise RuntimeError(
            f"{label} {arm} violations: "
            f"search={search_violations!r}, final={final_violations!r}"
        )
    route_groups, _, _ = t5.canonical_route_structure(
        solution,
        {
            node.node_id
            for node in reporting_bundle.instance.nodes
            if node.node_type.lower() == "c"
        },
    )
    print(
        json.dumps(
            {
                "label": label,
                "arm": arm,
                "route_signature_sha256": t5.canonical_sha256(route_groups),
                "charging_energy_kwh": final_breakdown["electricity_kwh"],
                "search_side_objective_cny": search_objective,
                "search_side_charging_emissions_kg": search_breakdown[
                    "E_ev_indirect"
                ],
                "search_side_charging_cost_cny": search_breakdown["cost_elec"],
                "final_objective_cny": final_objective,
                "final_evaluation_charging_emissions_kg": final_breakdown[
                    "E_ev_indirect"
                ],
                "final_evaluation_charging_cost_cny": final_breakdown[
                    "cost_elec"
                ],
            },
            sort_keys=True,
        )
    )


def pre_fix_replay():
    search, reporting, _ = _bundles()
    witness_path = (
        t5.REPO
        / "docs/handoff/carbon_objective_probe_20260804/solution_witnesses.json"
    )
    runs = json.loads(witness_path.read_text(encoding="utf-8"))["runs"]
    for arm in ("O", "C"):
        solution = _solution_from_payload(runs[f"{arm}_seed1_budget1000"]["solution"])
        _print_ledger(
            "T5 archived pre-fix witness replay",
            arm,
            solution,
            search[arm],
            reporting[arm],
        )


def fixed_run():
    from setp_solver.model_config import ModelConfig, model_config_scope

    search, reporting, _ = _bundles()
    t5.install_probe_local_timing_hooks()
    initial = t5.initial_solution()
    for arm in ("O", "C"):
        with model_config_scope(
            ModelConfig(
                strict_multitrip=True,
                depot_charger_capacity_mode="unbounded",
            )
        ):
            row, _, _, witness = t5.run_one(
                arm=arm,
                budget=1000,
                seed=1,
                search_bundle=search[arm],
                reporting_bundle=reporting[arm],
                initial=initial,
            )
        solution = _solution_from_payload(witness["solution"])
        _print_ledger("T7 fixed two-arm run", arm, solution, search[arm], reporting[arm])
        print(
            json.dumps(
                {
                    "row_search_side_charging_emissions_kg": row[
                        "search_side_charging_emissions_kg"
                    ],
                    "row_final_evaluation_charging_emissions_kg": row[
                        "final_evaluation_charging_emissions_kg"
                    ],
                    "completed_customer_count": row["completed_customer_count"],
                    "completed_demand": row["completed_demand"],
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("pre-fix-replay", "fixed-run"),
        default="fixed-run",
    )
    args = parser.parse_args()
    if args.mode == "pre-fix-replay":
        pre_fix_replay()
    else:
        fixed_run()
