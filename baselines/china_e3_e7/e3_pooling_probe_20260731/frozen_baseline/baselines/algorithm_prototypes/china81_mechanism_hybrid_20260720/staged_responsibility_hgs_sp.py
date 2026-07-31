"""Staged-v5 portfolio with an explicit responsibility-lock switch for E3.

This module leaves the E2-frozen implementation byte-for-byte unchanged.  It
only exposes the preregistered E3 treatment dimension throughout the same
two-stage search: the control arm locks each customer to its registered home
depot, while the treatment arm permits reciprocal cross-depot exchanges.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from epochal_hgs import HgsExactEpoch, _run_exact_epoch
from pyvrp_adapter import build_pyvrp_problem
from route_pool_sp import (
    _accepted_mip_completion,
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


VIEW_ORDER = ("cv_only", "naive_ev", "mechanism_ev")


@dataclass(frozen=True)
class StagedResponsibilityHgsSpRun:
    solution: Solution
    completion: China81CompletionResult
    base_completion: China81CompletionResult
    view_completions: dict[str, China81CompletionResult]
    stages: dict[str, tuple[HgsExactEpoch, HgsExactEpoch]]
    elapsed_seconds: float
    stats: dict[str, Any]


def _best_completion(
    completions: tuple[China81CompletionResult, ...],
    *extra: China81CompletionResult,
) -> China81CompletionResult:
    return min((*completions, *extra), key=lambda item: item.objective)


def _mip_completion(
    bundle: China81Bundle,
    records: Any,
    *,
    seconds: float,
    hard_home_depot_lock: bool,
) -> tuple[China81CompletionResult | None, dict[str, Any]]:
    solution, stats = _solve_set_partitioning(
        bundle,
        records,
        time_limit_seconds=seconds,
        hard_home_depot_lock=hard_home_depot_lock,
    )
    if solution is None:
        return None, stats
    return _accepted_mip_completion(solution, bundle, stats), stats


def _cross_depot_ledger(
    stages: dict[str, tuple[HgsExactEpoch, HgsExactEpoch]],
) -> dict[str, Any]:
    direction_counts: dict[str, int] = {}
    attempts = 0
    completed = 0
    for stage_pair in stages.values():
        for stage in stage_pair:
            attempts += int(stage.stats["cross_depot_candidate_attempts"])
            completed += int(
                stage.stats["cross_depot_completed_candidates"]
            )
            for direction, count in stage.stats[
                "cross_depot_direction_counts"
            ].items():
                direction_counts[direction] = (
                    direction_counts.get(direction, 0) + int(count)
                )
    return {
        "candidate_attempts": attempts,
        "completed_candidates": completed,
        "direction_counts": dict(sorted(direction_counts.items())),
    }


def run_staged_responsibility_hgs_sp(
    bundle: China81Bundle,
    common_initial_solution: Solution,
    *,
    seed: int,
    hard_home_depot_lock: bool,
    stage_1_iterations: int = 5_000,
    stage_2_iterations: int = 20_000,
    stage_1_checkpoint_interval: int = 250,
    stage_2_checkpoint_interval: int = 1_000,
    exact_elites_per_view: int = 8,
    archive_candidates_per_stage: int = 24,
    mip_seconds_per_stage: float = 30.0,
    collect_historical_population_archive: bool = True,
    wallclock_safety_seconds_per_stage: float,
) -> StagedResponsibilityHgsSpRun:
    """Run the frozen staged-v5 algorithm under one E3 responsibility arm."""

    started = perf_counter()
    lock = bool(hard_home_depot_lock)
    stages: dict[str, tuple[HgsExactEpoch, HgsExactEpoch]] = {}
    base_view_epochs: dict[str, HgsExactEpoch] = {}
    expanded_view_epochs: dict[str, HgsExactEpoch] = {}
    view_completions: dict[str, China81CompletionResult] = {}

    for mode in VIEW_ORDER:
        problem = build_pyvrp_problem(
            bundle,
            route_proxy_mode=mode,
            hard_home_depot_lock=lock,
        )
        base_view_epochs[mode] = _run_exact_epoch(
            bundle,
            problem,
            common_initial_solution,
            seed=int(seed),
            runtime_seconds=None,
            warm_elites=(),
            exact_elite_count=exact_elites_per_view,
            max_archive_candidates=archive_candidates_per_stage,
            max_hgs_iterations=stage_1_iterations,
            wallclock_safety_seconds=wallclock_safety_seconds_per_stage,
            exact_checkpoint_interval_iterations=(
                stage_1_checkpoint_interval
            ),
            collect_historical_population_archive=(
                collect_historical_population_archive
            ),
        )

    stage_1_phase_elapsed = perf_counter() - started
    base_parents = [
        _best_completion(
            epoch.base_archive_completions,
            epoch.proxy_best_completion,
        )
        for epoch in base_view_epochs.values()
    ]
    base_parent = min(base_parents, key=lambda item: item.objective)
    base_records = _route_pool_records(
        bundle,
        base_view_epochs,
        hard_home_depot_lock=lock,
        use_base_archive=True,
    )
    base_mip, base_mip_stats = _mip_completion(
        bundle,
        base_records,
        seconds=mip_seconds_per_stage,
        hard_home_depot_lock=lock,
    )
    base_candidates = [("stage_1_parent", base_parent)]
    if base_mip is not None:
        base_candidates.append(("stage_1_base_pool_mip", base_mip))
    base_source, base_completion = min(
        base_candidates,
        key=lambda item: item[1].objective,
    )
    base_phase_elapsed = perf_counter() - started

    for mode in VIEW_ORDER:
        stage_1 = base_view_epochs[mode]
        problem = build_pyvrp_problem(
            bundle,
            route_proxy_mode=mode,
            hard_home_depot_lock=lock,
        )
        stage_2 = _run_exact_epoch(
            bundle,
            problem,
            common_initial_solution,
            seed=int(seed) + 1_009,
            runtime_seconds=None,
            warm_elites=stage_1.elite_skeletons,
            exact_elite_count=exact_elites_per_view,
            max_archive_candidates=archive_candidates_per_stage,
            max_hgs_iterations=stage_2_iterations,
            wallclock_safety_seconds=wallclock_safety_seconds_per_stage,
            exact_checkpoint_interval_iterations=(
                stage_2_checkpoint_interval
            ),
            collect_historical_population_archive=(
                collect_historical_population_archive
            ),
        )
        stages[mode] = (stage_1, stage_2)
        combined = (
            *stage_1.archive_completions,
            *stage_2.archive_completions,
        )
        selected = tuple(
            sorted(combined, key=lambda item: item.objective)[
                :exact_elites_per_view
            ]
        )
        expanded = HgsExactEpoch(
            elite_skeletons=tuple(
                item.solution for item in selected
            ),
            elite_completions=selected,
            proxy_best_completion=min(
                (
                    stage_1.proxy_best_completion,
                    stage_2.proxy_best_completion,
                ),
                key=lambda item: item.objective,
            ),
            elapsed_seconds=(
                stage_1.elapsed_seconds + stage_2.elapsed_seconds
            ),
            stats={
                "stage_count": 2,
                "hgs_iterations": (
                    int(stage_1.stats["hgs_iterations"])
                    + int(stage_2.stats["hgs_iterations"])
                ),
                "complete_candidate_evaluation_attempts": (
                    int(
                        stage_1.stats[
                            "complete_candidate_evaluation_attempts"
                        ]
                    )
                    + int(
                        stage_2.stats[
                            "complete_candidate_evaluation_attempts"
                        ]
                    )
                ),
                "wallclock_safety_triggered": bool(
                    stage_1.stats["wallclock_safety_triggered"]
                    or stage_2.stats["wallclock_safety_triggered"]
                ),
            },
            archive_completions=combined,
            base_archive_completions=(
                stage_1.base_archive_completions
            ),
        )
        expanded_view_epochs[mode] = expanded
        view_completions[mode] = _best_completion(
            combined,
            stage_1.proxy_best_completion,
            stage_2.proxy_best_completion,
        )

    expanded_parent = min(
        view_completions.values(),
        key=lambda item: item.objective,
    )
    expanded_records = _route_pool_records(
        bundle,
        expanded_view_epochs,
        hard_home_depot_lock=lock,
    )
    expanded_mip, expanded_mip_stats = _mip_completion(
        bundle,
        expanded_records,
        seconds=mip_seconds_per_stage,
        hard_home_depot_lock=lock,
    )
    final_candidates = [
        ("protected_stage_1", base_completion),
        ("two_stage_best_parent", expanded_parent),
    ]
    if expanded_mip is not None:
        final_candidates.append(
            ("two_stage_expanded_pool_mip", expanded_mip)
        )
    selected_source, completion = min(
        final_candidates,
        key=lambda item: item[1].objective,
    )
    exact_objective, _, violations = exact_china81_score(
        completion.solution,
        bundle,
    )
    if violations or abs(exact_objective - completion.objective) > 1e-9:
        raise RuntimeError("E3 staged candidate failed final exact check")
    if lock and completion.solution.cross_site_services:
        raise RuntimeError(
            "E3 hard-lock candidate contains cross-site service"
        )
    if any(
        bool(stage.stats["hard_home_depot_lock"]) != lock
        for stage_pair in stages.values()
        for stage in stage_pair
    ):
        raise RuntimeError("E3 responsibility lock drifted inside HGS")
    if not lock and not all(
        bool(
            stage.stats[
                "reciprocal_cross_depot_neighbourhood_enabled"
            ]
        )
        for stage_pair in stages.values()
        for stage in stage_pair
    ):
        raise RuntimeError(
            "E3 reciprocal cross-depot neighbourhood is inactive"
        )

    elapsed = perf_counter() - started
    epoch_attempts = sum(
        int(stage.stats["complete_candidate_evaluation_attempts"])
        for stage_pair in stages.values()
        for stage in stage_pair
    )
    complete_attempts = epoch_attempts + 4
    if complete_attempts != 280:
        raise RuntimeError(
            f"E3 complete-candidate budget drifted: {complete_attempts}"
        )
    cross_depot = _cross_depot_ledger(stages)
    return StagedResponsibilityHgsSpRun(
        solution=completion.solution,
        completion=completion,
        base_completion=base_completion,
        view_completions=view_completions,
        stages=stages,
        elapsed_seconds=elapsed,
        stats={
            "algorithm": "MV-HGS-SP-STAGED-V5-E3",
            "seed": int(seed),
            "hard_home_depot_lock": lock,
            "reciprocal_cross_depot_neighbourhood_enabled": (
                not lock
            ),
            "stage_1_iterations_per_view": int(stage_1_iterations),
            "stage_2_iterations_per_view": int(stage_2_iterations),
            "total_iterations_per_view": int(
                stage_1_iterations + stage_2_iterations
            ),
            "historical_population_archive_enabled": bool(
                collect_historical_population_archive
            ),
            "complete_candidate_evaluation_attempts": (
                complete_attempts
            ),
            "complete_candidate_budget_expected": 280,
            "complete_candidate_budget_exactly_consumed": True,
            "base_source": base_source,
            "selected_source": selected_source,
            "base_objective": float(base_completion.objective),
            "final_objective": float(completion.objective),
            "improvement_over_protected_base": float(
                base_completion.objective - completion.objective
            ),
            "base_route_pool_size": len(base_records),
            "expanded_route_pool_size": len(expanded_records),
            "base_route_pool_mip": base_mip_stats,
            "expanded_route_pool_mip": expanded_mip_stats,
            "cross_depot_candidate_attempts": cross_depot[
                "candidate_attempts"
            ],
            "cross_depot_completed_candidates": cross_depot[
                "completed_candidates"
            ],
            "cross_depot_direction_counts": cross_depot[
                "direction_counts"
            ],
            "stage_1_phase_elapsed_seconds": float(
                stage_1_phase_elapsed
            ),
            "base_phase_elapsed_seconds": float(base_phase_elapsed),
            "stage_2_and_expanded_mip_elapsed_seconds": float(
                elapsed - base_phase_elapsed
            ),
            "wallclock_safety_triggered": any(
                bool(stage.stats["wallclock_safety_triggered"])
                for stage_pair in stages.values()
                for stage in stage_pair
            ),
            "measured_elapsed_seconds": elapsed,
        },
    )
