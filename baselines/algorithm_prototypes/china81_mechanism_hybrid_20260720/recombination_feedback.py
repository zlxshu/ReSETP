"""Budget-matched feedback from route recombination into final HGS search."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from cross_view_feedback import _best_distinct_solutions
from epochal_hgs import HgsExactEpoch, _run_exact_epoch
from pyvrp_adapter import build_pyvrp_problem
from route_pool_sp import _route_pool_records, _solve_set_partitioning
from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import (
    China81CompletionResult,
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.solution import Solution


@dataclass(frozen=True)
class RecombinationFeedbackRun:
    solution: Solution
    completion: China81CompletionResult
    scout_epochs: dict[str, HgsExactEpoch]
    refinement_epoch: HgsExactEpoch
    elapsed_seconds: float
    stats: dict[str, Any]


def run_recombination_feedback(
    bundle: China81Bundle,
    common_initial_solution: Solution,
    *,
    seed: int,
    scout_iterations_per_view: int = 4_000,
    refinement_iterations: int = 3_000,
    scout_archive_candidates_per_view: int = 16,
    refinement_archive_candidates: int = 22,
    feedback_elite_count: int = 8,
    sp_time_limit_seconds: float = 5.0,
    wallclock_safety_seconds: float,
) -> RecombinationFeedbackRun:
    started = perf_counter()
    modes = ("cv_only", "naive_ev", "mechanism_ev")
    scouts = {
        mode: _run_exact_epoch(
            bundle,
            build_pyvrp_problem(bundle, route_proxy_mode=mode),
            common_initial_solution,
            seed=seed,
            runtime_seconds=None,
            warm_elites=(),
            exact_elite_count=8,
            max_archive_candidates=scout_archive_candidates_per_view,
            max_hgs_iterations=scout_iterations_per_view,
            wallclock_safety_seconds=wallclock_safety_seconds,
        )
        for mode in modes
    }
    parents = [
        completion
        for epoch in scouts.values()
        for completion in epoch.elite_completions
    ]
    parent = min(parents, key=lambda item: item.objective)
    records = _route_pool_records(bundle, scouts)
    recombined, mip_stats = _solve_set_partitioning(
        bundle,
        records,
        time_limit_seconds=sp_time_limit_seconds,
    )
    first_completion = (
        parent
        if recombined is None
        else min(
            (
                parent,
                complete_china81_route_skeleton(recombined, bundle),
            ),
            key=lambda item: item.objective,
        )
    )
    distinct = _best_distinct_solutions(
        scouts,
        limit=max(1, feedback_elite_count - 1),
    )
    refinement = _run_exact_epoch(
        bundle,
        build_pyvrp_problem(bundle, route_proxy_mode="mechanism_ev"),
        common_initial_solution,
        seed=seed + 1_009,
        runtime_seconds=None,
        warm_elites=(first_completion.solution, *distinct),
        exact_elite_count=8,
        max_archive_candidates=refinement_archive_candidates,
        max_hgs_iterations=refinement_iterations,
        wallclock_safety_seconds=wallclock_safety_seconds,
    )
    completion = min(
        (
            first_completion,
            refinement.proxy_best_completion,
            *refinement.elite_completions,
        ),
        key=lambda item: item.objective,
    )
    objective, _, violations = exact_china81_score(
        completion.solution,
        bundle,
    )
    if violations or abs(objective - completion.objective) > 1.0e-9:
        raise ValueError("recombination feedback independent recheck failed")
    attempts = (
        sum(
            int(epoch.stats["complete_candidate_evaluation_attempts"])
            for epoch in scouts.values()
        )
        + int(refinement.stats["complete_candidate_evaluation_attempts"])
        + 2
    )
    total_iterations = sum(
        int(epoch.stats["hgs_iterations"]) for epoch in scouts.values()
    ) + int(refinement.stats["hgs_iterations"])
    elapsed = perf_counter() - started
    return RecombinationFeedbackRun(
        solution=completion.solution,
        completion=completion,
        scout_epochs=scouts,
        refinement_epoch=refinement,
        elapsed_seconds=elapsed,
        stats={
            "algorithm": "MV-HGS-SP-RECOMBINATION-FEEDBACK",
            "complete_candidate_evaluation_attempts": attempts,
            "complete_candidate_budget_exactly_consumed": attempts == 80,
            "total_hgs_iterations": total_iterations,
            "wallclock_safety_triggered": any(
                bool(epoch.stats["wallclock_safety_triggered"])
                for epoch in (*scouts.values(), refinement)
            ),
            "first_recombination_objective": float(
                first_completion.objective
            ),
            "refinement_best_objective": float(
                min(
                    (
                        refinement.proxy_best_completion,
                        *refinement.elite_completions,
                    ),
                    key=lambda item: item.objective,
                ).objective
            ),
            "final_objective": float(completion.objective),
            "route_pool_size": len(records),
            "route_pool_mip": mip_stats,
            "feedback_warm_solution_count": 1 + len(distinct),
            "measured_elapsed_seconds": elapsed,
        },
    )
