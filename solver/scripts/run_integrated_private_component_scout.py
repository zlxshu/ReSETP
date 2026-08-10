#!/usr/bin/env python3
"""Compare the current integrated private HGS with its route-only arm."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import traceback
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from run_problem_hgs_private_technical import (
    PROTECTED,
    _build_context,
    _json,
    _policy,
    _prepare_population,
    _sha256,
)
from setp_hgs_kernel.stop import MaxIterations, MaxRuntime, MultipleCriteria
from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator
from setp_solver.algorithms.problem_hgs.integrated_private import (
    build_integrated_private_hgs,
)
from setp_solver.algorithms.problem_hgs.kernel_proposals import (
    IndependentKernelDutyRouteProposalEngine,
)
from setp_solver.algorithms.problem_hgs.population import PenaltyParameters
from setp_solver.search.metaheuristic_baselines import solution_to_dict


SEED = 11
PENALTIES = PenaltyParameters(
    initial_penalty_per_unit=100.0,
    solutions_between_updates=50,
    penalty_increase=1.34,
    penalty_decrease=0.32,
    target_feasible=0.43,
    feasibility_tolerance=0.05,
    minimum_penalty=0.1,
    maximum_penalty=100_000.0,
)


def _private_accounting_payload(accounting) -> dict:
    return {
        "decoded_candidates": accounting.decoded_candidates,
        "rejected_candidates": accounting.rejected_candidates,
        "crossover_calls": accounting.crossover_calls,
        "crossover_noops": accounting.crossover_noops,
        "mechanism_calls": accounting.mechanism_calls,
        "mechanism_improvements": accounting.mechanism_improvements,
        "repair_calls": accounting.repair_calls,
        "repair_improvements": accounting.repair_improvements,
        "rejection_reasons": dict(accounting.rejection_reasons),
        "mechanism": accounting.mechanism.to_dict(),
    }


def _write_failure_package(output: Path, error: Exception) -> None:
    metadata_path = output / "metadata.json"
    if not metadata_path.is_file():
        return
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") != "RUNNING":
        return
    metadata["status"] = "FAILED"
    metadata["failure_type"] = type(error).__name__
    metadata["failure"] = str(error)
    _json(metadata_path, metadata)
    _json(
        output / "decision.json",
        {
            "verdict": "TECHNICAL_SCOUT_FAILED",
            "failure_type": type(error).__name__,
            "failure": str(error),
            "traceback": traceback.format_exc(),
        },
    )
    (output / "report.md").write_text(
        "# 当前独立算法私有组件短试失败\n\n"
        f"本次失败为 {type(error).__name__}: {error}。"
        "已生成的原始行保留，不能当作完整结果包。\n",
        encoding="utf-8",
    )
    _json(
        output / "artifact_hashes.json",
        {
            path.name: _sha256(path)
            for path in sorted(output.iterdir())
            if (
                path.is_file()
                and path.name != "artifact_hashes.json"
                and not path.name.startswith("._")
            )
        },
    )


def _served(best, bundle) -> tuple[int, float, int, float]:
    customers = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    served = {
        customer
        for duty in best.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    return (
        len(served),
        sum(float(customers[item].demand) for item in served),
        len(customers),
        sum(float(node.demand) for node in customers.values()),
    )


def _run_arm(
    *,
    initial_candidates,
    context,
    iterations: int,
    max_runtime_seconds: float,
    include_mechanisms: bool,
    include_charging_candidates: bool,
    seed: int,
):
    deadline = perf_counter() + float(max_runtime_seconds)
    evaluator = DutyFullEvaluator(context)
    initial_evaluation = evaluator.evaluate(initial_candidates[0])
    policy = _policy(evaluator)
    route_engine = IndependentKernelDutyRouteProposalEngine(
        context,
        initial_candidates[0],
        random_seed=seed,
        stream_role="integrated_private_component_scout",
    )
    built = build_integrated_private_hgs(
        tuple(initial_candidates),
        evaluator=evaluator,
        charging_policy=policy,
        route_engine=route_engine,
        penalty_parameters=PENALTIES,
        stagnation_patience=500,
        include_mechanism_refinement=include_mechanisms,
        include_whole_duty_type_exchange=True,
        include_charging_candidates=include_charging_candidates,
        stop_requested=lambda: perf_counter() >= deadline,
    )
    remaining_seconds = max(0.0, deadline - perf_counter())
    result = built.algorithm.run(
        MultipleCriteria(
            [MaxIterations(iterations), MaxRuntime(remaining_seconds)]
        )
    )
    return result, built.accounting, initial_evaluation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--max-runtime-seconds", type=float, default=1200.0)
    parser.add_argument(
        "--compare-charging-candidates",
        action="store_true",
        help=(
            "compare the same full problem components with the approved "
            "multi-candidate charging search disabled and enabled"
        ),
    )
    parser.add_argument(
        "--compare-final-components",
        action="store_true",
        help=(
            "compare route-only search with all current private components, "
            "including incumbent-staged charging refinement"
        ),
    )
    args = parser.parse_args()
    if args.compare_charging_candidates and args.compare_final_components:
        raise ValueError("choose one private component comparison")
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
            "purpose": "current private component scout; not a formal experiment",
            "instance_id": args.instance_id,
            "seed": args.seed,
            "iterations": args.iterations,
            "max_runtime_seconds_per_arm": args.max_runtime_seconds,
            "protected_hashes_before": protected_before,
        },
    )

    bundle, initial, _pi0, context = _build_context(repo, args.instance_id)
    preparation_evaluator = DutyFullEvaluator(context)
    preparation_policy = _policy(preparation_evaluator)
    candidates, _initial_evaluation, *_rest = _prepare_population(
        initial,
        preparation_evaluator,
        preparation_policy,
        require_distinct_selection=False,
    )

    rows = []
    best_payloads = {}
    if args.compare_charging_candidates:
        arms = (
            ("FULL_PROBLEM_COMPONENTS_NO_CHARGE", True, False),
            ("FULL_PROBLEM_COMPONENTS_WITH_CHARGE", True, True),
        )
    elif args.compare_final_components:
        arms = (
            ("ROUTE_ONLY", False, False),
            ("FULL_PROBLEM_COMPONENTS", True, True),
        )
    else:
        arms = (
            ("ROUTE_ONLY", False, False),
            ("FULL_PROBLEM_COMPONENTS", True, False),
        )
    for arm, include_mechanisms, include_charging_candidates in arms:
        result, accounting, arm_initial_evaluation = _run_arm(
            initial_candidates=candidates,
            context=context,
            iterations=args.iterations,
            max_runtime_seconds=args.max_runtime_seconds,
            include_mechanisms=include_mechanisms,
            include_charging_candidates=include_charging_candidates,
            seed=args.seed,
        )
        evaluation = result.best.evaluation.full
        if evaluation is None:
            raise RuntimeError(f"{arm} ended without a complete evaluation")
        served_count, served_demand, total_count, total_demand = _served(
            result.best.evaluation.individual,
            bundle,
        )
        if not (
            evaluation.feasible
            and served_count == total_count
            and abs(served_demand - total_demand) <= 1e-9
        ):
            raise RuntimeError(f"{arm} did not preserve complete feasible service")
        row = {
            "instance_id": args.instance_id,
            "arm": arm,
            "seed": args.seed,
            "requested_iterations": args.iterations,
            "actual_iterations": result.accounting.iterations,
            "runtime_seconds": result.accounting.elapsed_seconds,
            "initial_cost": arm_initial_evaluation.total_cost,
            "best_cost": evaluation.total_cost,
            "cost_change_pct": 100.0
            * (evaluation.total_cost - arm_initial_evaluation.total_cost)
            / arm_initial_evaluation.total_cost,
            "feasible": evaluation.feasible,
            "customers_served": served_count,
            "customers_total": total_count,
            "demand_served": served_demand,
            "demand_total": total_demand,
            "total_emissions_kg": evaluation.breakdown["E_total"],
            "used_cv": evaluation.breakdown["n_veh_cv"],
            "used_ev": evaluation.breakdown["n_veh_ev"],
            "mechanism_calls": accounting.mechanism_calls,
            "mechanism_improvements": accounting.mechanism_improvements,
            "repair_calls": accounting.repair_calls,
            "repair_improvements": accounting.repair_improvements,
            "decoded_candidates": accounting.decoded_candidates,
            "rejected_candidates": accounting.rejected_candidates,
        }
        rows.append(row)
        best_payloads[arm] = {
            "individual": asdict(result.best.evaluation.individual),
            "evaluation": {
                "total_cost": evaluation.total_cost,
                "breakdown": dict(evaluation.breakdown),
                "feasible": evaluation.feasible,
                "violations": [asdict(item) for item in evaluation.violations],
                "participation_margin": dict(evaluation.participation_margin),
                "prepared_solution": solution_to_dict(
                    evaluation.prepared_solution
                ),
            },
            "run_accounting": asdict(result.accounting),
            "private_accounting": _private_accounting_payload(accounting),
        }

    by_arm = {row["arm"]: row for row in rows}
    if args.compare_charging_candidates:
        left = by_arm["FULL_PROBLEM_COMPONENTS_NO_CHARGE"]
        right = by_arm["FULL_PROBLEM_COMPONENTS_WITH_CHARGE"]
        comparison_name = "charging_cost_delta_on_minus_off"
    else:
        left = by_arm["ROUTE_ONLY"]
        right = by_arm["FULL_PROBLEM_COMPONENTS"]
        comparison_name = "component_cost_delta_full_minus_route"
    comparison_delta = right["best_cost"] - left["best_cost"]
    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    if protected_before != protected_after:
        raise RuntimeError("protected evaluator files changed during the scout")

    with (output / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _json(output / "best_solutions.json", best_payloads)
    _json(
        output / "decision.json",
        {
            "verdict": "TECHNICAL_SCOUT_COMPLETE",
            "formal_experiment": False,
            "instance_id": args.instance_id,
            comparison_name: comparison_delta,
            "right_arm_better": comparison_delta < 0,
            "service_and_demand_equal": True,
        },
    )
    (output / "report.md").write_text(
        "# 当前独立算法私有组件短试\n\n"
        f"{args.instance_id} 在同一种子、同迭代数下，左臂成本为 "
        f"{left['best_cost']:.6f}，右臂成本为 "
        f"{right['best_cost']:.6f}，两臂均完整服务全部客户和需求。"
        "本次用于算法定型前贡献归因，不是正式论文实验。\n",
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
