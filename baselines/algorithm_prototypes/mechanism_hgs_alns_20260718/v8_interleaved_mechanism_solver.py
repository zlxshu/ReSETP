"""Development-only ALNS with mechanism education between search chunks.

Unlike v7, the fleet/charging and carbon-time experts are not applied only
after route search. They educate the incumbent every 20 complete route
evaluations, and the next ALNS chunk continues from that mechanism-feasible
incumbent. Exact decoders keep their separate zero-complete-evaluation ledger.
"""

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


def run_mechanism_alns_v8_interleaved(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    chunk_budget: int = 20,
) -> ArmResult:
    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=EvalBudget(limit=0, target=0),
    )
    remaining = max(0, int(eval_budget))
    solution = None
    objective = float("inf")
    evaluations = 0
    chunks: list[dict[str, Any]] = []
    while remaining > 0:
        current_budget = min(max(1, int(chunk_budget)), remaining)
        route_result = run_pure_alns(
            bundle_dir,
            seed=int(seed) + len(chunks) * 1009,
            eval_budget=current_budget,
            prices=prices,
            initial_solution=solution,
        )
        evaluations += int(route_result.evaluations)
        remaining -= int(route_result.evaluations)
        solution = route_result.best_solution
        objective = independent_cost(bundle_dir, solution, prices)
        before = float(objective)
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
        chunks.append(
            {
                "chunk": len(chunks) + 1,
                "route_evaluations": int(route_result.evaluations),
                "before_mechanisms": before,
                "after_mechanisms": float(objective),
                "joint_updates": int(joint.get("exact_decoder_updates", 0)),
                "joint_improvements": int(joint.get("improvements", 0)),
                "carbon_updates": int(carbon.get("exact_decoder_updates", 0)),
                "carbon_improvements": int(carbon.get("improvements", 0)),
                "carbon_actions_retimed": int(carbon.get("actions_retimed", 0)),
            }
        )
        if int(route_result.evaluations) <= 0:
            raise RuntimeError("v8 route chunk consumed no evaluations")
    if solution is None:
        base = run_pure_alns(
            bundle_dir,
            seed=seed,
            eval_budget=0,
            prices=prices,
        )
        solution = base.best_solution
        objective = independent_cost(bundle_dir, solution, prices)
    recomputed = independent_cost(bundle_dir, solution, prices)
    if abs(float(objective) - float(recomputed)) > 1.0e-7:
        raise RuntimeError(
            f"v8 independent objective mismatch: {objective} != {recomputed}"
        )
    violations = check_solution(solution, bundle.instance, prices)
    return ArmResult(
        algorithm="mechanism_alns_v8_interleaved",
        best_solution=solution,
        best_cost=float(recomputed),
        evaluations=evaluations,
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(solution.routes),
        feasible=not violations,
        mechanism_activity={
            "chunk_budget": int(chunk_budget),
            "chunk_count": len(chunks),
            "chunks": chunks,
            "joint_improvement_count": sum(
                int(item["joint_improvements"]) for item in chunks
            ),
            "carbon_improvement_count": sum(
                int(item["carbon_improvements"]) for item in chunks
            ),
            "independent_final_replays": 1,
        },
    )
