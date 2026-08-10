#!/usr/bin/env python3
"""Compare daily-mean and time-varying carbon in the current private HGS."""

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
    _private_accounting_payload,
    _run_arm,
    _served,
    _write_failure_package,
)
from run_integrated_private_fleet_supply_scout import (
    _bundle_for_arm,
    _load_witness,
    _with_available_assets,
    _witness_skeleton,
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
from setp_solver.algorithms.problem_hgs.model import DutyIndividual
from setp_solver.china81_completion import complete_china81_route_skeleton
from setp_solver.search.metaheuristic_baselines import solution_to_dict


def _daily_mean_context(context):
    rows = list(context.bundle.time_profile)
    by_city: dict[str, list[float]] = {}
    for row in rows:
        by_city.setdefault(str(row["city"]), []).append(
            float(row["actual_gco2_per_kwh"])
        )
    means = {
        city: sum(values) / len(values)
        for city, values in by_city.items()
    }
    flat_rows = [
        {
            **row,
            "actual_gco2_per_kwh": means[str(row["city"])],
            "forecast_gco2_per_kwh": means[str(row["city"])],
        }
        for row in rows
    ]
    return replace(
        context,
        bundle=replace(context.bundle, time_profile=flat_rows),
    ), means


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--max-runtime-seconds", type=float, default=1200.0)
    parser.add_argument("--both-types-available", action="store_true")
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
            "purpose": "daily-mean versus time-varying carbon scout; not formal",
            "instance_id": args.instance_id,
            "seed": SEED,
            "iterations": args.iterations,
            "max_runtime_seconds_per_arm": args.max_runtime_seconds,
            "fleet_supply_mode": (
                "BOTH_TYPES_AVAILABLE"
                if args.both_types_available
                else "CURRENT_REGISTERED"
            ),
            "protected_hashes_before": protected_before,
        },
    )

    bundle, initial, _pi0, actual_context = _build_context(
        repo, args.instance_id
    )
    if args.both_types_available:
        witness = _load_witness(repo, bundle)
        bundle = _bundle_for_arm(
            bundle,
            witness,
            "BOTH_TYPES_AVAILABLE",
            "50",
        )
        skeleton = _witness_skeleton(bundle, witness, "50")
        completed = complete_china81_route_skeleton(
            skeleton,
            bundle,
        ).solution
        initial = _with_available_assets(
            DutyIndividual.from_solution(completed),
            bundle,
        )
        actual_context = replace(
            actual_context,
            bundle=bundle,
            fairness_enabled=False,
        )
    flat_context, daily_means = _daily_mean_context(actual_context)
    preparation_evaluator = DutyFullEvaluator(actual_context)
    candidates, *_rest = _prepare_population(
        initial,
        preparation_evaluator,
        _policy(preparation_evaluator),
        require_distinct_selection=False,
    )

    rows = []
    solutions = {}
    for arm, context in (
        ("DAILY_MEAN_CARBON", flat_context),
        ("TIME_VARYING_CARBON", actual_context),
    ):
        result, accounting, arm_initial = _run_arm(
            initial_candidates=candidates,
            context=context,
            iterations=args.iterations,
            max_runtime_seconds=args.max_runtime_seconds,
            include_mechanisms=True,
            include_charging_candidates=True,
        )
        evaluation = result.best.evaluation.full
        if evaluation is None:
            raise RuntimeError(f"{arm} ended without a complete evaluation")
        individual = result.best.evaluation.individual
        actual_evaluation = DutyFullEvaluator(actual_context).evaluate(
            individual
        )
        served_count, served_demand, total_count, total_demand = _served(
            individual, bundle
        )
        if not (
            evaluation.feasible
            and actual_evaluation.feasible
            and served_count == total_count
            and abs(served_demand - total_demand) <= 1e-9
        ):
            raise RuntimeError(f"{arm} did not preserve feasible complete service")
        row = {
            "instance_id": args.instance_id,
            "arm": arm,
            "seed": SEED,
            "iterations": result.accounting.iterations,
            "runtime_seconds": result.accounting.elapsed_seconds,
            "optimisation_initial_cost": arm_initial.total_cost,
            "optimisation_best_cost": evaluation.total_cost,
            "actual_time_varying_cost": actual_evaluation.total_cost,
            "actual_time_varying_emissions_kg": actual_evaluation.breakdown[
                "E_total"
            ],
            "actual_ev_emissions_kg": actual_evaluation.breakdown[
                "E_ev_indirect"
            ],
            "actual_cv_emissions_kg": actual_evaluation.breakdown[
                "E_cv_direct"
            ],
            "electricity_kwh": actual_evaluation.breakdown["electricity_kwh"],
            "used_cv": actual_evaluation.breakdown["n_veh_cv"],
            "used_ev": actual_evaluation.breakdown["n_veh_ev"],
            "customers_served": served_count,
            "customers_total": total_count,
            "demand_served": served_demand,
            "demand_total": total_demand,
        }
        rows.append(row)
        solutions[arm] = {
            "individual": asdict(individual),
            "optimisation_evaluation": {
                "total_cost": evaluation.total_cost,
                "breakdown": dict(evaluation.breakdown),
                "feasible": evaluation.feasible,
            },
            "actual_time_varying_evaluation": {
                "total_cost": actual_evaluation.total_cost,
                "breakdown": dict(actual_evaluation.breakdown),
                "feasible": actual_evaluation.feasible,
                "violations": [
                    asdict(item) for item in actual_evaluation.violations
                ],
                "prepared_solution": solution_to_dict(
                    actual_evaluation.prepared_solution
                ),
            },
            "run_accounting": asdict(result.accounting),
            "private_accounting": _private_accounting_payload(accounting),
        }

    by_arm = {row["arm"]: row for row in rows}
    daily = by_arm["DAILY_MEAN_CARBON"]
    varying = by_arm["TIME_VARYING_CARBON"]
    emissions_pct = 100.0 * (
        varying["actual_time_varying_emissions_kg"]
        - daily["actual_time_varying_emissions_kg"]
    ) / daily["actual_time_varying_emissions_kg"]
    cost_pct = 100.0 * (
        varying["actual_time_varying_cost"]
        - daily["actual_time_varying_cost"]
    ) / daily["actual_time_varying_cost"]
    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    if protected_before != protected_after:
        raise RuntimeError("protected evaluator files changed during the scout")

    with (output / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _json(output / "best_solutions.json", solutions)
    _json(
        output / "decision.json",
        {
            "verdict": "TECHNICAL_CARBON_SCOUT_COMPLETE",
            "formal_experiment": False,
            "instance_id": args.instance_id,
            "time_varying_vs_daily_mean_actual_emissions_pct": emissions_pct,
            "time_varying_vs_daily_mean_actual_cost_pct": cost_pct,
            "daily_mean_gco2_per_kwh_by_city": daily_means,
            "service_and_demand_equal": True,
        },
    )
    (output / "report.md").write_text(
        "# 当前独立算法日均与时变碳完整重优化短试\n\n"
        f"{args.instance_id} 在同一种子和迭代数下，时变碳方案按真实"
        f"时变口径复核的排放相对日均碳方案变化 {emissions_pct:.6f}%，"
        f"成本变化 {cost_pct:.6f}%。两臂均完整服务全部客户和需求。"
        "本次不是正式论文实验。\n",
        encoding="utf-8",
    )
    metadata = json.loads(
        (output / "metadata.json").read_text(encoding="utf-8")
    )
    metadata["status"] = "COMPLETE"
    metadata["daily_mean_gco2_per_kwh_by_city"] = daily_means
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
    print(json.dumps({"output": str(output), "rows": rows}, ensure_ascii=False))
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
