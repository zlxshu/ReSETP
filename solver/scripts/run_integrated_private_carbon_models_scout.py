#!/usr/bin/env python3
"""Small isolated comparison of three carbon-modelling views.

This is not a formal experiment and does not modify the model or China81.
It runs the current independent private HGS under several sourced carbon
prices, then uses the resulting feasible solutions to expose (1) scalarised
cost, (2) a cost-emissions nondominated set, and (3) emissions-cap choices.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import traceback
from dataclasses import asdict, replace
from pathlib import Path

from run_integrated_private_component_scout import (
    SEED,
    _run_arm,
    _served,
    _write_failure_package,
)
from run_problem_hgs_private_technical import (
    PROTECTED,
    _build_context,
    _json,
    _policy,
    _prepare_population,
    _sha256,
)
from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator
from setp_solver.search.metaheuristic_baselines import solution_to_dict


PRICE_ARMS = (
    ("NO_CARBON_PRICE", 0.0, "economic-cost control"),
    (
        "CEA_2025_06_30_CLOSE",
        0.07502,
        "Shanghai Environment and Energy Exchange, 2025-06-30 close",
    ),
    (
        "CHEN_2023_BASE",
        0.5,
        "Chen et al. (2023), SETP 43(12), Table 6",
    ),
    (
        "CHEN_2023_ROUTE_EXAMPLE",
        2.2,
        "Chen et al. (2023), SETP 43(12), Fig. 4",
    ),
    (
        "CHEN_2023_SENSITIVITY_MAX",
        5.0,
        "Chen et al. (2023), SETP 43(12), Section 5.2.2",
    ),
)


def _context_with_price(context, price_cny_per_kg: float):
    prices = replace(
        context.bundle.prices,
        carbon_price=float(price_cny_per_kg),
    )
    return replace(
        context,
        bundle=replace(context.bundle, prices=prices),
        # This scout isolates carbon objective behaviour.  The technical Pi0
        # is initial-solution-derived rather than a frozen independent-profit
        # baseline, so it must not be allowed to confound the comparison.
        fairness_enabled=False,
    )


def _nondominated(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    frontier = []
    for row in rows:
        cost = float(row["economic_cost_cny"])
        emissions = float(row["total_emissions_kg"])
        dominated = any(
            float(other["economic_cost_cny"]) <= cost + 1e-9
            and float(other["total_emissions_kg"]) <= emissions + 1e-9
            and (
                float(other["economic_cost_cny"]) < cost - 1e-9
                or float(other["total_emissions_kg"]) < emissions - 1e-9
            )
            for other in rows
        )
        if not dominated:
            frontier.append(row)
    return sorted(
        frontier,
        key=lambda row: (
            float(row["total_emissions_kg"]),
            float(row["economic_cost_cny"]),
            str(row["arm"]),
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--max-runtime-seconds", type=float, default=1200.0)
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("iterations must be positive")
    if not 0 < args.max_runtime_seconds <= 1200:
        raise ValueError("runtime must be in (0, 1200] seconds")

    repo = Path(__file__).resolve().parents[2]
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "purpose": "isolated carbon-model behaviour scout; not formal",
            "instance_id": args.instance_id,
            "seed": SEED,
            "iterations": args.iterations,
            "max_runtime_seconds_per_arm": args.max_runtime_seconds,
            "fairness_enabled": False,
            "fairness_reason": (
                "isolate carbon objective; current technical Pi0 is not the "
                "user-approved independent-profit baseline"
            ),
            "price_arms": [
                {
                    "arm": arm,
                    "cny_per_kg": price,
                    "source_identity": source,
                }
                for arm, price, source in PRICE_ARMS
            ],
            "protected_hashes_before": protected_before,
        },
    )

    bundle, initial, _pi0, base_context = _build_context(
        repo, args.instance_id
    )
    base_context = _context_with_price(base_context, 0.0)
    preparation_evaluator = DutyFullEvaluator(base_context)
    candidates, *_rest = _prepare_population(
        initial,
        preparation_evaluator,
        _policy(preparation_evaluator),
        require_distinct_selection=False,
    )

    scalar_rows: list[dict[str, object]] = []
    solutions: dict[str, object] = {}
    for arm, price, source_identity in PRICE_ARMS:
        context = _context_with_price(base_context, price)
        result, accounting, _arm_initial = _run_arm(
            initial_candidates=candidates,
            context=context,
            iterations=args.iterations,
            max_runtime_seconds=args.max_runtime_seconds,
            include_mechanisms=True,
            include_charging_candidates=True,
        )
        selected = result.best.evaluation
        if selected.full is None:
            raise RuntimeError(f"{arm} ended without a complete evaluation")
        common = DutyFullEvaluator(base_context).evaluate(selected.individual)
        served_count, served_demand, total_count, total_demand = _served(
            selected.individual, bundle
        )
        if not (
            selected.full.feasible
            and common.feasible
            and served_count == total_count
            and abs(served_demand - total_demand) <= 1e-9
        ):
            raise RuntimeError(f"{arm} did not preserve feasible complete service")
        row: dict[str, object] = {
            "instance_id": args.instance_id,
            "arm": arm,
            "carbon_price_cny_per_kg": price,
            "source_identity": source_identity,
            "seed": SEED,
            "iterations": result.accounting.iterations,
            "runtime_seconds": result.accounting.elapsed_seconds,
            "scalar_objective_cny": selected.full.total_cost,
            "economic_cost_cny": common.total_cost,
            "total_emissions_kg": common.breakdown["E_total"],
            "cv_direct_emissions_kg": common.breakdown["E_cv_direct"],
            "ev_indirect_emissions_kg": common.breakdown["E_ev_indirect"],
            "used_cv": common.breakdown["n_veh_cv"],
            "used_ev": common.breakdown["n_veh_ev"],
            "electricity_kwh": common.breakdown["electricity_kwh"],
            "customers_served": served_count,
            "customers_total": total_count,
            "demand_served": served_demand,
            "demand_total": total_demand,
            "individual_fingerprint": selected.individual.fingerprint,
        }
        scalar_rows.append(row)
        solutions[arm] = {
            "individual": asdict(selected.individual),
            "selected_evaluation": {
                "total_cost": selected.full.total_cost,
                "breakdown": dict(selected.full.breakdown),
                "feasible": selected.full.feasible,
            },
            "common_zero_price_evaluation": {
                "total_cost": common.total_cost,
                "breakdown": dict(common.breakdown),
                "feasible": common.feasible,
                "prepared_solution": solution_to_dict(common.prepared_solution),
            },
            "run_accounting": asdict(result.accounting),
            "private_accounting": {
                "decoded_candidates": accounting.decoded_candidates,
                "rejected_candidates": accounting.rejected_candidates,
                "charging_rescue_attempts": accounting.charging_rescue_attempts,
                "charging_rescues": accounting.charging_rescues,
                "mechanism_calls": accounting.mechanism_calls,
                "mechanism_improvements": accounting.mechanism_improvements,
            },
        }

    frontier = _nondominated(scalar_rows)
    cap_rows = []
    for frontier_row in frontier:
        cap = float(frontier_row["total_emissions_kg"])
        eligible = [
            row
            for row in scalar_rows
            if float(row["total_emissions_kg"]) <= cap + 1e-9
        ]
        chosen = min(
            eligible,
            key=lambda row: (
                float(row["economic_cost_cny"]),
                float(row["total_emissions_kg"]),
            ),
        )
        cap_rows.append(
            {
                "emissions_cap_kg": cap,
                "selected_arm": chosen["arm"],
                "economic_cost_cny": chosen["economic_cost_cny"],
                "total_emissions_kg": chosen["total_emissions_kg"],
                "used_cv": chosen["used_cv"],
                "used_ev": chosen["used_ev"],
                "individual_fingerprint": chosen["individual_fingerprint"],
            }
        )

    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    if protected_before != protected_after:
        raise RuntimeError("protected evaluator files changed during the scout")

    with (output / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(scalar_rows[0]))
        writer.writeheader()
        writer.writerows(scalar_rows)
    _json(output / "best_solutions.json", solutions)
    _json(
        output / "decision.json",
        {
            "verdict": "TECHNICAL_CARBON_MODEL_SCOUT_COMPLETE",
            "formal_experiment": False,
            "instance_id": args.instance_id,
            "scalar_rows": scalar_rows,
            "nondominated_rows": frontier,
            "emissions_cap_rows": cap_rows,
            "service_and_demand_equal": True,
            "model_or_parameter_changed": False,
        },
    )
    (output / "report.md").write_text(
        "# 三种碳建模口径的隔离短试\n\n"
        "本包用有来源的碳价运行当前独立算法，再从同一批可行解中"
        "整理单一货币目标、成本—排放非支配解和排放上限选择。"
        "这是帮助用户理解三种模型行为的技术短试，不是正式实验，"
        "没有修改正式模型、参数或算例。\n",
        encoding="utf-8",
    )
    metadata = json.loads(
        (output / "metadata.json").read_text(encoding="utf-8")
    )
    metadata["status"] = "COMPLETE"
    metadata["protected_hashes_after"] = protected_after
    _json(output / "metadata.json", metadata)
    _json(
        output / "artifact_hashes.json",
        {
            path.name: _sha256(path)
            for path in sorted(output.iterdir())
            if path.is_file() and path.name != "artifact_hashes.json"
        },
    )
    print(json.dumps({"output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    requested_output = (
        None
        if len(sys.argv) < 2 or sys.argv[1].startswith("-")
        else Path(sys.argv[1]).resolve()
    )
    try:
        raise SystemExit(main())
    except Exception as error:
        if requested_output is not None:
            _write_failure_package(requested_output, error)
        traceback.print_exc()
        raise
