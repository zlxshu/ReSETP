"""Mechanism-aware multi-seed initialisation followed by one continuous ALNS."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from prototype import ArmResult, independent_cost, run_pure_alns
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from v5_carbon_retiming_solver import carbon_aware_depot_retime
from v6_monotone_mechanism_solver import exact_joint_fleet_charge_decode


def run_mechanism_alns_v9_seeded(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    seed_count: int = 4,
    per_seed_budget: int = 10,
) -> ArmResult:
    started = time.perf_counter()
    total = max(0, int(eval_budget))
    seed_total = min(total, max(0, int(seed_count)) * max(0, int(per_seed_budget)))
    if seed_total >= total and total > 0:
        raise ValueError("v9 must reserve a positive continuous-search budget")
    bundle = load_search_bundle(bundle_dir)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=EvalBudget(limit=0, target=0),
    )
    seeds = []
    evaluations = 0
    for index in range(max(0, int(seed_count))):
        budget = min(max(0, int(per_seed_budget)), total - evaluations)
        if budget <= 0:
            break
        result = run_pure_alns(
            bundle_dir,
            seed=int(seed) + index * 1009,
            eval_budget=budget,
            prices=prices,
        )
        evaluations += int(result.evaluations)
        solution = result.best_solution
        objective = independent_cost(bundle_dir, solution, prices)
        solution, objective, joint = exact_joint_fleet_charge_decode(
            solution,
            context,
            incumbent_objective=objective,
        )
        solution, objective, carbon = carbon_aware_depot_retime(
            solution,
            context,
            incumbent_objective=objective,
            consume_complete_evaluation=False,
        )
        seeds.append(
            {
                "index": index,
                "seed": int(seed) + index * 1009,
                "route_evaluations": int(result.evaluations),
                "objective": float(objective),
                "solution": solution,
                "joint_improvements": int(joint.get("improvements", 0)),
                "carbon_improvements": int(carbon.get("improvements", 0)),
            }
        )
    if not seeds:
        fallback = run_pure_alns(
            bundle_dir,
            seed=seed,
            eval_budget=0,
            prices=prices,
        )
        seeds.append(
            {
                "index": 0,
                "seed": seed,
                "route_evaluations": 0,
                "objective": independent_cost(
                    bundle_dir,
                    fallback.best_solution,
                    prices,
                ),
                "solution": fallback.best_solution,
                "joint_improvements": 0,
                "carbon_improvements": 0,
            }
        )
    selected = min(seeds, key=lambda item: float(item["objective"]))
    continuation_budget = total - evaluations
    continuation = run_pure_alns(
        bundle_dir,
        seed=int(seed) + 7919,
        eval_budget=continuation_budget,
        prices=prices,
        initial_solution=selected["solution"],
    )
    evaluations += int(continuation.evaluations)
    solution = continuation.best_solution
    objective = independent_cost(bundle_dir, solution, prices)
    solution, objective, final_joint = exact_joint_fleet_charge_decode(
        solution,
        context,
        incumbent_objective=objective,
    )
    solution, objective, final_carbon = carbon_aware_depot_retime(
        solution,
        context,
        incumbent_objective=objective,
        consume_complete_evaluation=False,
    )
    recomputed = independent_cost(bundle_dir, solution, prices)
    if abs(float(objective) - float(recomputed)) > 1.0e-7:
        raise RuntimeError(
            f"v9 independent objective mismatch: {objective} != {recomputed}"
        )
    violations = check_solution(solution, bundle.instance, prices)
    return ArmResult(
        algorithm="mechanism_alns_v9_seeded",
        best_solution=solution,
        best_cost=float(recomputed),
        evaluations=evaluations,
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(solution.routes),
        feasible=not violations,
        mechanism_activity={
            "seed_count": len(seeds),
            "per_seed_budget": int(per_seed_budget),
            "seed_route_evaluations": sum(
                int(item["route_evaluations"]) for item in seeds
            ),
            "continuation_evaluations": int(continuation.evaluations),
            "selected_seed_index": int(selected["index"]),
            "selected_seed_objective": float(selected["objective"]),
            "seed_summaries": [
                {key: value for key, value in item.items() if key != "solution"}
                for item in seeds
            ],
            "final_joint_improvements": int(final_joint.get("improvements", 0)),
            "final_carbon_improvements": int(final_carbon.get("improvements", 0)),
            "independent_final_replays": 1,
        },
    )
