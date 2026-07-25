"""Budget-matched cross-view complete-elite feedback for MV-HGS-SP."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from epochal_hgs import HgsExactEpoch, _run_exact_epoch
from pyvrp_adapter import build_pyvrp_problem
from route_pool_sp import (
    _route_pool_records,
    _solve_set_partitioning,
)
from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import (
    China81CompletionResult,
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.solution import Solution


@dataclass(frozen=True)
class CrossViewFeedbackRun:
    solution: Solution
    completion: China81CompletionResult
    parent_completion: China81CompletionResult
    stage_one: dict[str, HgsExactEpoch]
    stage_two: dict[str, HgsExactEpoch]
    elapsed_seconds: float
    stats: dict[str, Any]


def _solution_key(solution: Solution) -> tuple[Any, ...]:
    return (
        tuple(
            sorted(
                (
                    route.vehicle_type,
                    route.home_depot_id,
                    tuple(route.node_sequence),
                )
                for route in solution.routes
            )
        ),
        tuple(
            sorted(
                (
                    action.station_id,
                    round(float(action.energy_kwh), 9),
                    round(float(action.charge_start_second), 9),
                )
                for action in solution.charging_actions
            )
        ),
    )


def _best_distinct_solutions(
    epochs: dict[str, HgsExactEpoch],
    *,
    limit: int,
) -> tuple[Solution, ...]:
    ranked = sorted(
        (
            completion
            for epoch in epochs.values()
            for completion in epoch.archive_completions
        ),
        key=lambda item: item.objective,
    )
    unique: dict[tuple[Any, ...], Solution] = {}
    for completion in ranked:
        unique.setdefault(
            _solution_key(completion.solution),
            completion.solution,
        )
        if len(unique) >= limit:
            break
    return tuple(unique.values())


def run_cross_view_feedback(
    bundle: China81Bundle,
    common_initial_solution: Solution,
    *,
    seed: int,
    max_hgs_iterations_per_view: int = 5_000,
    archive_candidates_per_stage: int = 11,
    feedback_elite_count: int = 8,
    exact_elites_per_stage: int = 8,
    sp_time_limit_seconds: float = 5.0,
    wallclock_safety_seconds_per_stage: float,
    hard_home_depot_lock: bool = False,
) -> CrossViewFeedbackRun:
    """Run two equal HGS stages and exchange exact elites between views."""

    if max_hgs_iterations_per_view % 2:
        raise ValueError("HGS iteration budget must split exactly in two")
    if archive_candidates_per_stage < 1:
        raise ValueError("archive_candidates_per_stage must be positive")
    started = perf_counter()
    modes = ("cv_only", "naive_ev", "mechanism_ev")
    stage_iterations = max_hgs_iterations_per_view // 2
    problems = {
        mode: build_pyvrp_problem(
            bundle,
            route_proxy_mode=mode,
            hard_home_depot_lock=hard_home_depot_lock,
        )
        for mode in modes
    }
    stage_one = {
        mode: _run_exact_epoch(
            bundle,
            problems[mode],
            common_initial_solution,
            seed=int(seed),
            runtime_seconds=None,
            warm_elites=(),
            exact_elite_count=exact_elites_per_stage,
            max_archive_candidates=archive_candidates_per_stage,
            max_hgs_iterations=stage_iterations,
            wallclock_safety_seconds=wallclock_safety_seconds_per_stage,
        )
        for mode in modes
    }
    feedback = _best_distinct_solutions(
        stage_one,
        limit=feedback_elite_count,
    )
    stage_two = {
        mode: _run_exact_epoch(
            bundle,
            problems[mode],
            common_initial_solution,
            seed=int(seed) + 1_009,
            runtime_seconds=None,
            warm_elites=feedback,
            exact_elite_count=exact_elites_per_stage,
            max_archive_candidates=archive_candidates_per_stage,
            max_hgs_iterations=stage_iterations,
            wallclock_safety_seconds=wallclock_safety_seconds_per_stage,
        )
        for mode in modes
    }
    combined: dict[str, HgsExactEpoch] = {}
    for mode in modes:
        first = stage_one[mode]
        second = stage_two[mode]
        elites = sorted(
            (*first.elite_completions, *second.elite_completions),
            key=lambda item: item.objective,
        )[:exact_elites_per_stage]
        combined[mode] = HgsExactEpoch(
            elite_skeletons=tuple(item.solution for item in elites),
            elite_completions=tuple(elites),
            proxy_best_completion=min(
                (
                    first.proxy_best_completion,
                    second.proxy_best_completion,
                ),
                key=lambda item: item.objective,
            ),
            elapsed_seconds=(
                first.elapsed_seconds + second.elapsed_seconds
            ),
            stats={
                "hgs_iterations": (
                    int(first.stats["hgs_iterations"])
                    + int(second.stats["hgs_iterations"])
                ),
            },
            archive_completions=(
                *first.archive_completions,
                *second.archive_completions,
            ),
        )
    parents = [
        completion
        for epoch in combined.values()
        for completion in epoch.elite_completions
    ]
    parent = min(parents, key=lambda item: item.objective)
    records = _route_pool_records(
        bundle,
        combined,
        hard_home_depot_lock=hard_home_depot_lock,
    )
    recombined, mip_stats = _solve_set_partitioning(
        bundle,
        records,
        time_limit_seconds=sp_time_limit_seconds,
        hard_home_depot_lock=hard_home_depot_lock,
    )
    if recombined is None:
        completion = parent
        selected_source = "best_exact_hgs_parent"
    else:
        candidate = complete_china81_route_skeleton(
            recombined,
            bundle,
        )
        if candidate.objective < parent.objective - 1.0e-9:
            completion = candidate
            selected_source = "time_limited_mip_recombination"
        else:
            completion = parent
            selected_source = "best_exact_hgs_parent"
    objective, _, violations = exact_china81_score(
        completion.solution,
        bundle,
    )
    if violations or abs(objective - completion.objective) > 1.0e-9:
        raise ValueError("cross-view feedback final independent recheck failed")
    complete_attempts = (
        sum(
            int(epoch.stats["complete_candidate_evaluation_attempts"])
            for epochs in (stage_one, stage_two)
            for epoch in epochs.values()
        )
        + 2
    )
    elapsed = perf_counter() - started
    return CrossViewFeedbackRun(
        solution=completion.solution,
        completion=completion,
        parent_completion=parent,
        stage_one=stage_one,
        stage_two=stage_two,
        elapsed_seconds=elapsed,
        stats={
            "algorithm": "MV-HGS-SP-CROSS-VIEW-FEEDBACK",
            "seed": int(seed),
            "stage_iterations": int(stage_iterations),
            "total_hgs_iterations": int(
                2 * len(modes) * stage_iterations
            ),
            "feedback_elite_count": len(feedback),
            "archive_candidates_per_stage": int(
                archive_candidates_per_stage
            ),
            "complete_candidate_evaluation_attempts": int(
                complete_attempts
            ),
            "complete_candidate_budget_exactly_consumed": (
                complete_attempts == 80
            ),
            "wallclock_safety_triggered": any(
                bool(epoch.stats["wallclock_safety_triggered"])
                for epochs in (stage_one, stage_two)
                for epoch in epochs.values()
            ),
            "route_pool_size": len(records),
            "selected_source": selected_source,
            "best_parent_objective": float(parent.objective),
            "final_objective": float(completion.objective),
            "strict_recombination_improvement": bool(
                completion.objective < parent.objective - 1.0e-9
            ),
            "route_pool_mip": mip_stats,
            "measured_elapsed_seconds": float(elapsed),
        },
    )
