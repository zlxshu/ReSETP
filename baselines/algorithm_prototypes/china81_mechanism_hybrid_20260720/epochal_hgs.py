#!/usr/bin/env python3
"""Genuine HGS with exact ReSETP elite migration between epochs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import pyvrp
from pyvrp._pyvrp import RandomNumberGenerator
from pyvrp._pyvrp import Solution as NativeSolution
from pyvrp.crossover import ordered_crossover, selective_route_exchange
from pyvrp.diversity import broken_pairs_distance
from pyvrp.GeneticAlgorithm import GeneticAlgorithm
from pyvrp.PenaltyManager import PenaltyManager
from pyvrp.Population import Population
from pyvrp.ProgressPrinter import ProgressPrinter
from pyvrp.Result import Result
from pyvrp.search import LocalSearch, compute_neighbours
from pyvrp.solve import SolveParams
from pyvrp.Statistics import Statistics
from pyvrp.stop import MaxIterations, MaxRuntime, MultipleCriteria
from pyvrp_adapter import (
    China81PyVRPProblem,
    _completion_failure_category,
    _native_candidate_id,
    _native_solution_key,
    _project_initial_solution,
    _skeleton_candidate_id,
    _translate_solution,
    build_pyvrp_problem,
)
from setp_solver.charge_timing import DEFAULT_CHARGE_TIMING_POLICY
from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import (
    China81CompletionResult,
    annotate_cross_site_services,
    complete_china81_route_skeleton,
)
from setp_solver.solution import Solution


@dataclass(frozen=True)
class HgsExactEpoch:
    elite_skeletons: tuple[Solution, ...]
    elite_completions: tuple[China81CompletionResult, ...]
    proxy_best_completion: China81CompletionResult
    elapsed_seconds: float
    stats: dict[str, Any]
    archive_completions: tuple[China81CompletionResult, ...] = ()
    base_archive_completions: tuple[
        China81CompletionResult,
        ...,
    ] = ()


@dataclass(frozen=True)
class EpochalMechanismHgsRun:
    solution: Solution
    completion: China81CompletionResult
    epochs: tuple[HgsExactEpoch, ...]
    elapsed_seconds: float
    stats: dict[str, Any]


def run_epochal_mechanism_hgs(
    bundle: China81Bundle,
    common_initial_solution: Solution,
    *,
    base_seed: int,
    total_hgs_seconds: float,
    route_proxy_mode: str,
    epoch_count: int = 2,
    exact_elite_count: int = 4,
    max_archive_candidates: int = 24,
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
) -> EpochalMechanismHgsRun:
    """Run equal-length HGS epochs with exact-model elite migration."""

    if not hasattr(pyvrp, "GeneticAlgorithm"):
        raise RuntimeError("epochal HGS requires PyVRP 0.12.2")
    if total_hgs_seconds <= 0.0:
        raise ValueError("total_hgs_seconds must be positive")
    if epoch_count < 2:
        raise ValueError("epoch_count must be at least two")
    if exact_elite_count < 1 or max_archive_candidates < exact_elite_count:
        raise ValueError("invalid exact elite/archive limits")
    started = perf_counter()
    problem = build_pyvrp_problem(
        bundle,
        route_proxy_mode=route_proxy_mode,
    )
    epoch_seconds = float(total_hgs_seconds) / int(epoch_count)
    warm_elites: tuple[Solution, ...] = ()
    epochs: list[HgsExactEpoch] = []
    for epoch_index in range(int(epoch_count)):
        epoch = _run_exact_epoch(
            bundle,
            problem,
            common_initial_solution,
            seed=int(base_seed) + 1_009 * epoch_index,
            runtime_seconds=epoch_seconds,
            warm_elites=warm_elites,
            exact_elite_count=exact_elite_count,
            max_archive_candidates=max_archive_candidates,
            charge_timing_policy=charge_timing_policy,
        )
        epochs.append(epoch)
        warm_elites = epoch.elite_skeletons
    all_completions = [
        complete_china81_route_skeleton(
            common_initial_solution,
            bundle,
            charge_timing_policy=charge_timing_policy,
        ),
        *[
            completion
            for epoch in epochs
            for completion in epoch.elite_completions
        ],
    ]
    completion = min(
        all_completions,
        key=lambda item: item.objective,
    )
    elapsed = perf_counter() - started
    return EpochalMechanismHgsRun(
        solution=completion.solution,
        completion=completion,
        epochs=tuple(epochs),
        elapsed_seconds=elapsed,
        stats={
            "algorithm": "EM-HGS",
            "algorithm_name_en": (
                "Exact-Mechanism Migrating Hybrid Genetic Search"
            ),
            "algorithm_name_zh": "完整机制精英迁移混合遗传搜索算法",
            "story": (
                "HGS generates a diverse population; the complete nonlinear "
                "ReSETP model re-ranks feasible individuals; several exact "
                "elites migrate into the next HGS epoch as breeding material"
            ),
            "base_seed": int(base_seed),
            "route_proxy_mode": route_proxy_mode,
            "charge_timing_policy": charge_timing_policy,
            "total_hgs_seconds": float(total_hgs_seconds),
            "epoch_count": int(epoch_count),
            "epoch_seconds": epoch_seconds,
            "exact_elite_count": int(exact_elite_count),
            "archive_candidate_limit": int(max_archive_candidates),
            "epoch_best_exact_objectives": [
                min(
                    item.objective
                    for item in epoch.elite_completions
                )
                for epoch in epochs
            ],
            "epoch_proxy_best_exact_objectives": [
                epoch.proxy_best_completion.objective
                for epoch in epochs
            ],
            "final_objective": float(completion.objective),
            "measured_elapsed_seconds": elapsed,
        },
    )


def _run_exact_epoch(
    bundle: China81Bundle,
    problem: China81PyVRPProblem,
    common_initial_solution: Solution,
    *,
    seed: int,
    runtime_seconds: float | None,
    warm_elites: tuple[Solution, ...],
    exact_elite_count: int,
    max_archive_candidates: int,
    max_hgs_iterations: int | None = None,
    wallclock_safety_seconds: float | None = None,
    no_improvement_wallclock_seconds: float | None = None,
    no_improvement_minimum_relative_improvement: float = 0.0,
    exact_checkpoint_interval_iterations: int | None = None,
    collect_historical_population_archive: bool = False,
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
) -> HgsExactEpoch:
    no_improvement_stop: _AuditedNoImprovementWallclock | None = None
    if no_improvement_wallclock_seconds is not None:
        if no_improvement_wallclock_seconds <= 0.0:
            raise ValueError(
                "no-improvement wallclock seconds must be positive"
            )
        if max_hgs_iterations is not None:
            raise ValueError(
                "no-improvement stopping cannot have an iteration cap"
            )
        if runtime_seconds is not None:
            raise ValueError(
                "no-improvement stopping cannot have a total runtime cap"
            )
        if wallclock_safety_seconds is not None:
            raise ValueError(
                "no-improvement stopping cannot have a wallclock safety cap"
            )
        no_improvement_stop = _AuditedNoImprovementWallclock(
            float(no_improvement_wallclock_seconds),
            minimum_relative_improvement=float(
                no_improvement_minimum_relative_improvement
            ),
        )
        stop = no_improvement_stop
        stop_mode = "NO_IMPROVEMENT_WALLCLOCK_UNCAPPED_ITERATIONS"
        safety = None
    elif max_hgs_iterations is None:
        if runtime_seconds is None or runtime_seconds <= 0.0:
            raise ValueError("legacy HGS runtime must be positive")
        stop = MaxRuntime(float(runtime_seconds))
        stop_mode = "LEGACY_WALLCLOCK_PRIMARY"
        safety = None
    else:
        if max_hgs_iterations < 1:
            raise ValueError("max_hgs_iterations must be positive")
        safety = None
        criteria = [MaxIterations(int(max_hgs_iterations))]
        if (
            wallclock_safety_seconds is not None
            and wallclock_safety_seconds > 0.0
        ):
            safety = _AuditedWallclockSafety(
                float(wallclock_safety_seconds)
            )
            criteria.append(safety)
        stop = MultipleCriteria(criteria)
        stop_mode = (
            "DETERMINISTIC_ITERATIONS_WITH_WALLCLOCK_SAFETY"
            if safety is not None
            else "DETERMINISTIC_ITERATIONS_NO_WALLCLOCK"
        )
    if exact_checkpoint_interval_iterations is not None:
        if exact_checkpoint_interval_iterations < 1:
            raise ValueError(
                "exact checkpoint interval must be positive"
            )
    elif collect_historical_population_archive:
        raise ValueError(
            "historical population archive requires exact checkpoints"
        )
    started = perf_counter()
    data = problem.model.data()
    params = SolveParams()
    rng = RandomNumberGenerator(seed=int(seed))
    neighbours = compute_neighbours(data, params.neighbourhood)
    local_search = LocalSearch(data, rng, neighbours)
    active_node_operators: list[str] = []
    for node_op in params.node_ops:
        if node_op.supports(data):
            local_search.add_node_operator(node_op(data))
            active_node_operators.append(node_op.__name__)
    active_route_operators: list[str] = []
    for route_op in params.route_ops:
        if route_op.supports(data):
            local_search.add_route_operator(route_op(data))
            active_route_operators.append(route_op.__name__)
    penalty_manager = PenaltyManager.init_from(data, params.penalty)
    population = Population(broken_pairs_distance, params.population)
    warm_native = [
        _project_initial_solution(item, data, problem, bundle)
        for item in warm_elites
    ]
    warm_input_route_type_counts = [
        dict(
            sorted(
                Counter(
                    str(route.vehicle_type).strip().lower()
                    for route in skeleton.routes
                ).items()
            )
        )
        for skeleton in warm_elites
    ]
    warm_projected_route_type_counts = [
        dict(
            sorted(
                Counter(
                    problem.route_type_by_vehicle_type[
                        int(route.vehicle_type())
                    ]
                    for route in native.routes()
                    for _ in route.trips()
                ).items()
            )
        )
        for native in warm_native
    ]
    if problem.route_proxy_mode == "cv_only":
        warm_expected_route_type_counts = [
            (
                {"cv": sum(counts.values())}
                if counts
                else {}
            )
            for counts in warm_input_route_type_counts
        ]
    else:
        warm_expected_route_type_counts = (
            warm_input_route_type_counts
        )
    warm_route_type_preserved = (
        warm_projected_route_type_counts
        == warm_expected_route_type_counts
    )
    if not warm_route_type_preserved:
        raise RuntimeError(
            "warm-start route types changed during PyVRP projection"
        )
    random_count = max(
        0,
        int(params.population.min_pop_size) - len(warm_native),
    )
    initial_solutions = [
        *warm_native,
        *[
            NativeSolution.make_random(data, rng)
            for _ in range(random_count)
        ],
    ]
    crossover = (
        selective_route_exchange
        if data.num_vehicles > 1
        else ordered_crossover
    )
    checkpoint_candidates: list[
        tuple[Solution, China81CompletionResult, int]
    ] = []
    checkpoint_failures: list[str] = []
    checkpoint_observations: list[dict[str, Any]] = []
    hard_lock_filtered_checkpoint_candidates = 0

    def on_exact_checkpoint(
        native: NativeSolution,
        proxy_cost: int,
        iteration: int,
    ) -> None:
        nonlocal hard_lock_filtered_checkpoint_candidates
        observed_at = perf_counter() - started
        candidate_id = _native_candidate_id(native)
        try:
            skeleton = _translate_solution(native, problem)
            completion = complete_china81_route_skeleton(
                skeleton,
                bundle,
                charge_timing_policy=charge_timing_policy,
            )
            if (
                problem.hard_home_depot_lock
                and completion.solution.cross_site_services
            ):
                hard_lock_filtered_checkpoint_candidates += 1
                checkpoint_observations.append(
                    {
                        "candidate_id": candidate_id,
                        "iteration": int(iteration),
                        "elapsed_seconds": float(observed_at),
                        "proxy_cost": int(proxy_cost),
                        "completion_succeeded": True,
                        "complete_objective": None,
                        "status": "FILTERED_HARD_HOME_DEPOT_LOCK",
                        "exception_type": None,
                        "exception_message": None,
                        "failure_category": None,
                    }
                )
                return
            checkpoint_candidates.append(
                (skeleton, completion, int(proxy_cost))
            )
            checkpoint_observations.append(
                {
                    "candidate_id": candidate_id,
                    "iteration": int(iteration),
                    "elapsed_seconds": float(observed_at),
                    "proxy_cost": int(proxy_cost),
                    "completion_succeeded": True,
                    "complete_objective": float(
                        completion.objective
                    ),
                    "status": "PASS",
                    "exception_type": None,
                    "exception_message": None,
                    "failure_category": None,
                }
            )
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            checkpoint_failures.append(str(exc))
            checkpoint_observations.append(
                {
                    "candidate_id": candidate_id,
                    "iteration": int(iteration),
                    "elapsed_seconds": float(observed_at),
                    "proxy_cost": int(proxy_cost),
                    "completion_succeeded": False,
                    "complete_objective": None,
                    "status": "INFEASIBLE_OR_ERROR",
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "failure_category": _completion_failure_category(
                        str(exc)
                    ),
                }
            )

    if exact_checkpoint_interval_iterations is None:
        algorithm = GeneticAlgorithm(
            data,
            penalty_manager,
            rng,
            population,
            local_search,
            crossover,
            initial_solutions,
            params.genetic,
        )
    else:
        algorithm = _CheckpointGeneticAlgorithm(
            data,
            penalty_manager,
            rng,
            population,
            local_search,
            crossover,
            initial_solutions,
            params.genetic,
            checkpoint_interval=(
                exact_checkpoint_interval_iterations
            ),
            on_checkpoint=on_exact_checkpoint,
            collect_population_history=(
                collect_historical_population_archive
            ),
        )
    result = algorithm.run(
        stop,
        collect_stats=True,
        display=False,
        display_interval=params.display_interval,
    )
    cost_evaluator = penalty_manager.cost_evaluator()
    historical_population_items = list(
        getattr(algorithm, "historical_population", ())
    )
    population_items = [
        *initial_solutions,
        *list(population),
        *historical_population_items,
    ]
    population_items.append(result.best)
    unique: dict[tuple[Any, ...], Any] = {}
    for native in population_items:
        unique.setdefault(_native_solution_key(native), native)
    if collect_historical_population_archive:
        proxy_ranked, quality_archive_count = (
            _quality_diverse_native_archive(
                tuple(unique.values()),
                cost_evaluator,
                limit=int(max_archive_candidates),
            )
        )
    else:
        proxy_ranked = sorted(
            unique.values(),
            key=cost_evaluator.cost,
        )[: int(max_archive_candidates)]
        quality_archive_count = len(proxy_ranked)
    diversity_archive_count = (
        len(proxy_ranked) - quality_archive_count
    )
    exact_candidates: list[
        tuple[Solution, China81CompletionResult, int]
    ] = []
    complete_candidate_evaluation_trace: list[dict[str, Any]] = [
        {
            "candidate_id": observation["candidate_id"],
            "source": "hgs_iteration_checkpoint",
            "iteration": int(observation["iteration"]),
            "completion_succeeded": observation[
                "completion_succeeded"
            ],
            "complete_objective": observation["complete_objective"],
            "status": observation["status"],
            "exception_type": observation["exception_type"],
            "exception_message": observation["exception_message"],
            "failure_category": observation["failure_category"],
        }
        for observation in checkpoint_observations
    ]
    failures: list[str] = []
    archive_completion_attempts = 0
    hard_lock_filtered_archive_candidates = 0
    cross_depot_candidate_attempts = 0
    cross_depot_completed_candidates = 0
    cross_depot_direction_counts: dict[str, int] = {}
    for native in proxy_ranked:
        archive_completion_attempts += 1
        candidate_id = _native_candidate_id(native)
        try:
            skeleton = _translate_solution(native, problem)
            annotated_skeleton = annotate_cross_site_services(
                skeleton,
                bundle.customer_home_depot,
            )
            if annotated_skeleton.cross_site_services:
                cross_depot_candidate_attempts += 1
                for service in annotated_skeleton.cross_site_services:
                    owner = bundle.customer_home_depot[
                        service.customer_id
                    ]
                    direction = (
                        f"{owner}->{service.served_by_depot_id}"
                    )
                    cross_depot_direction_counts[direction] = (
                        cross_depot_direction_counts.get(direction, 0) + 1
                    )
            completion = complete_china81_route_skeleton(
                skeleton,
                bundle,
                charge_timing_policy=charge_timing_policy,
            )
            if (
                problem.hard_home_depot_lock
                and completion.solution.cross_site_services
            ):
                hard_lock_filtered_archive_candidates += 1
                complete_candidate_evaluation_trace.append(
                    {
                        "candidate_id": candidate_id,
                        "source": "terminal_population_archive",
                        "iteration": None,
                        "completion_succeeded": True,
                        "complete_objective": None,
                        "status": "FILTERED_HARD_HOME_DEPOT_LOCK",
                        "exception_type": None,
                        "exception_message": None,
                        "failure_category": None,
                    }
                )
                continue
            if completion.solution.cross_site_services:
                cross_depot_completed_candidates += 1
            exact_candidates.append(
                (
                    skeleton,
                    completion,
                    int(cost_evaluator.cost(native)),
                )
            )
            complete_candidate_evaluation_trace.append(
                {
                    "candidate_id": candidate_id,
                    "source": "terminal_population_archive",
                    "iteration": None,
                    "completion_succeeded": True,
                    "complete_objective": float(
                        completion.objective
                    ),
                    "status": "PASS",
                    "exception_type": None,
                    "exception_message": None,
                    "failure_category": None,
                }
            )
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            failures.append(str(exc))
            complete_candidate_evaluation_trace.append(
                {
                    "candidate_id": candidate_id,
                    "source": "terminal_population_archive",
                    "iteration": None,
                    "completion_succeeded": False,
                    "complete_objective": None,
                    "status": "INFEASIBLE_OR_ERROR",
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "failure_category": _completion_failure_category(
                        str(exc)
                    ),
                }
            )
    base_exact_candidates = list(exact_candidates)
    exact_candidates.extend(checkpoint_candidates)
    common_completion = complete_china81_route_skeleton(
        common_initial_solution,
        bundle,
        charge_timing_policy=charge_timing_policy,
    )
    complete_candidate_evaluation_trace.append(
        {
            "candidate_id": _skeleton_candidate_id(
                common_initial_solution
            ),
            "source": "common_initial_solution",
            "iteration": None,
            "completion_succeeded": True,
            "complete_objective": float(common_completion.objective),
            "status": "PASS",
            "exception_type": None,
            "exception_message": None,
            "failure_category": None,
        }
    )
    if (
        problem.hard_home_depot_lock
        and common_completion.solution.cross_site_services
    ):
        raise ValueError(
            "hard home-depot control initial solution contains "
            "cross-site service"
        )
    exact_candidates.append(
        (
            common_initial_solution,
            common_completion,
            -1,
        )
    )
    base_exact_candidates.append(
        (
            common_initial_solution,
            common_completion,
            -1,
        )
    )
    base_exact_ranked = sorted(
        base_exact_candidates,
        key=lambda item: (
            item[1].objective,
            item[2],
        ),
    )
    exact_ranked = sorted(
        exact_candidates,
        key=lambda item: (
            item[1].objective,
            item[2],
        ),
    )
    selected = exact_ranked[: int(exact_elite_count)]
    proxy_best_completion_failure: str | None = None
    proxy_best_completion_failure_category: str | None = None
    proxy_best_completion_attempts = 1
    hard_lock_filtered_proxy_best_candidates = 0
    proxy_best_candidate_id = _native_candidate_id(result.best)
    try:
        proxy_best_completion = complete_china81_route_skeleton(
            _translate_solution(result.best, problem),
            bundle,
            charge_timing_policy=charge_timing_policy,
        )
        if (
            problem.hard_home_depot_lock
            and proxy_best_completion.solution.cross_site_services
        ):
            hard_lock_filtered_proxy_best_candidates = 1
            proxy_best_completion_failure = (
                "FILTERED_HARD_HOME_DEPOT_LOCK"
            )
            complete_candidate_evaluation_trace.append(
                {
                    "candidate_id": proxy_best_candidate_id,
                    "source": "proxy_best_solution",
                    "iteration": int(result.num_iterations),
                    "completion_succeeded": True,
                    "complete_objective": None,
                    "status": "FILTERED_HARD_HOME_DEPOT_LOCK",
                    "exception_type": None,
                    "exception_message": None,
                    "failure_category": None,
                }
            )
            proxy_best_completion = min(
                (item[1] for item in exact_candidates),
                key=lambda item: item.objective,
            )
        else:
            complete_candidate_evaluation_trace.append(
                {
                    "candidate_id": proxy_best_candidate_id,
                    "source": "proxy_best_solution",
                    "iteration": int(result.num_iterations),
                    "completion_succeeded": True,
                    "complete_objective": float(
                        proxy_best_completion.objective
                    ),
                    "status": "PASS",
                    "exception_type": None,
                    "exception_message": None,
                    "failure_category": None,
                }
            )
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        proxy_best_completion_failure = str(exc)
        proxy_best_completion_failure_category = (
            _completion_failure_category(str(exc))
        )
        complete_candidate_evaluation_trace.append(
            {
                "candidate_id": proxy_best_candidate_id,
                "source": "proxy_best_solution",
                "iteration": int(result.num_iterations),
                "completion_succeeded": False,
                "complete_objective": None,
                "status": "INFEASIBLE_OR_ERROR",
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "failure_category": (
                    proxy_best_completion_failure_category
                ),
            }
        )
        proxy_best_completion = min(
            (item[1] for item in exact_candidates),
            key=lambda item: item.objective,
        )
    complete_candidate_evaluation_attempts = (
        archive_completion_attempts
        + len(checkpoint_observations)
        + 1
        + proxy_best_completion_attempts
    )
    if (
        len(complete_candidate_evaluation_trace)
        != complete_candidate_evaluation_attempts
    ):
        raise RuntimeError(
            "complete-candidate trace does not match the frozen "
            "evaluation-attempt counter"
        )
    completion_failure_category_counts = dict(
        sorted(
            Counter(
                item["failure_category"]
                for item in complete_candidate_evaluation_trace
                if item["failure_category"] is not None
            ).items()
        )
    )
    improvement_trace = list(
        getattr(algorithm, "improvement_trace", ())
    )
    if no_improvement_stop is not None:
        timer_audit = list(no_improvement_stop.improvement_audit)
        if len(timer_audit) != len(improvement_trace):
            raise RuntimeError(
                "no-improvement timer audit does not match the proxy "
                "improvement trace"
            )
        for improvement, audit in zip(improvement_trace, timer_audit):
            if (
                int(improvement["iteration"]) != int(audit["iteration"])
                or int(improvement["objective_before"])
                != int(audit["objective_before"])
                or int(improvement["objective_after"])
                != int(audit["objective_after"])
            ):
                raise RuntimeError(
                    "no-improvement timer audit diverged from the proxy "
                    "improvement trace: "
                    f"trace={improvement!r}, audit={audit!r}"
                )
            improvement.update(
                {
                    "timer_reset": bool(audit["timer_reset"]),
                    "timer_reset_threshold_relative": float(
                        audit["timer_reset_threshold_relative"]
                    ),
                    "timer_observed_improvement_relative": float(
                        audit["improvement_relative"]
                    ),
                }
            )
    if (
        no_improvement_stop is not None
        and no_improvement_stop.triggered
    ):
        hgs_stop_reason = "NO_IMPROVEMENT_WALLCLOCK"
    elif safety is not None and safety.triggered:
        hgs_stop_reason = "WALLCLOCK_SAFETY"
    elif (
        max_hgs_iterations is not None
        and int(result.num_iterations) >= int(max_hgs_iterations)
    ):
        hgs_stop_reason = "MAX_ITERATIONS"
    elif max_hgs_iterations is None:
        hgs_stop_reason = "LEGACY_MAX_RUNTIME"
    else:
        hgs_stop_reason = "UNKNOWN_STOP_CRITERION"
    return HgsExactEpoch(
        elite_skeletons=tuple(item[0] for item in selected),
        elite_completions=tuple(item[1] for item in selected),
        proxy_best_completion=proxy_best_completion,
        elapsed_seconds=perf_counter() - started,
        stats={
            "seed": int(seed),
            "runtime_seconds": (
                None
                if runtime_seconds is None
                else float(runtime_seconds)
            ),
            "hgs_stop_mode": stop_mode,
            "hgs_stop_reason": hgs_stop_reason,
            "max_hgs_iterations": (
                None
                if max_hgs_iterations is None
                else int(max_hgs_iterations)
            ),
            "wallclock_safety_seconds": (
                None
                if wallclock_safety_seconds is None
                else float(wallclock_safety_seconds)
            ),
            "wallclock_safety_triggered": bool(
                safety is not None and safety.triggered
            ),
            "wallclock_safety_enabled": safety is not None,
            "no_improvement_wallclock_seconds": (
                None
                if no_improvement_wallclock_seconds is None
                else float(no_improvement_wallclock_seconds)
            ),
            "no_improvement_minimum_relative_improvement": (
                None
                if no_improvement_stop is None
                else float(
                    no_improvement_stop.minimum_relative_improvement
                )
            ),
            "no_improvement_timer_reset_count": (
                None
                if no_improvement_stop is None
                else int(no_improvement_stop.timer_reset_count)
            ),
            "no_improvement_ignored_strict_improvement_count": (
                None
                if no_improvement_stop is None
                else int(
                    no_improvement_stop.ignored_strict_improvement_count
                )
            ),
            "no_improvement_wallclock_triggered": bool(
                no_improvement_stop is not None
                and no_improvement_stop.triggered
            ),
            "no_improvement_trigger_iteration": (
                None
                if no_improvement_stop is None
                else no_improvement_stop.trigger_iteration
            ),
            "no_improvement_last_improvement_iteration": (
                None
                if no_improvement_stop is None
                else no_improvement_stop.last_improvement_iteration
            ),
            "no_improvement_trigger_elapsed_seconds": (
                None
                if no_improvement_stop is None
                else no_improvement_stop.trigger_elapsed_seconds
            ),
            "no_improvement_last_improvement_elapsed_seconds": (
                None
                if no_improvement_stop is None
                else no_improvement_stop.last_improvement_elapsed_seconds
            ),
            "no_improvement_elapsed_seconds_at_trigger": (
                None
                if no_improvement_stop is None
                else no_improvement_stop.no_improvement_elapsed_seconds
            ),
            "charge_timing_policy": charge_timing_policy,
            "warm_elite_count": len(warm_native),
            "warm_input_route_type_counts": (
                warm_input_route_type_counts
            ),
            "warm_projected_route_type_counts": (
                warm_projected_route_type_counts
            ),
            "warm_route_type_preserved": (
                warm_route_type_preserved
            ),
            "population_size": len(population),
            "unique_feasible_population_size": sum(
                item.is_feasible()
                for item in unique.values()
            ),
            "unique_proxy_population_size": len(unique),
            "proxy_feasible_population_size": sum(
                item.is_feasible()
                for item in unique.values()
            ),
            "archive_candidate_limit": int(max_archive_candidates),
            "historical_population_archive_enabled": bool(
                collect_historical_population_archive
            ),
            "historical_population_snapshot_count": int(
                getattr(algorithm, "population_snapshot_count", 0)
            ),
            "historical_population_candidate_references": len(
                historical_population_items
            ),
            "archive_unique_native_candidates": len(unique),
            "archive_quality_selected_count": (
                quality_archive_count
            ),
            "archive_diversity_selected_count": (
                diversity_archive_count
            ),
            "archive_completion_attempts": (
                archive_completion_attempts
            ),
            "archive_candidates_screened": (
                archive_completion_attempts
            ),
            "hard_lock_filtered_archive_candidates": (
                hard_lock_filtered_archive_candidates
            ),
            "archive_candidates_completed": (
                len(exact_candidates) - 1
            ),
            "archive_completion_failures": failures,
            "exact_checkpoint_interval_iterations": (
                exact_checkpoint_interval_iterations
            ),
            "exact_checkpoint_attempts": len(
                checkpoint_observations
            ),
            "exact_checkpoint_candidates_screened": (
                len(checkpoint_observations)
            ),
            "hard_lock_filtered_checkpoint_candidates": (
                hard_lock_filtered_checkpoint_candidates
            ),
            "exact_checkpoint_completed": len(
                checkpoint_candidates
            ),
            "exact_checkpoint_failures": checkpoint_failures,
            "exact_checkpoint_observations": (
                checkpoint_observations
            ),
            "common_initial_completion_attempts": 1,
            "proxy_best_completion_attempts": (
                proxy_best_completion_attempts
            ),
            "hard_lock_filtered_proxy_best_candidates": (
                hard_lock_filtered_proxy_best_candidates
            ),
            "hard_lock_filtered_candidates": (
                hard_lock_filtered_archive_candidates
                + hard_lock_filtered_checkpoint_candidates
                + hard_lock_filtered_proxy_best_candidates
            ),
            "proxy_best_completion_failure": (
                proxy_best_completion_failure
            ),
            "proxy_best_completion_failure_category": (
                proxy_best_completion_failure_category
            ),
            "completion_failure_category_counts": (
                completion_failure_category_counts
            ),
            "complete_candidate_evaluation_attempts": (
                complete_candidate_evaluation_attempts
            ),
            "complete_candidate_evaluation_trace": (
                complete_candidate_evaluation_trace
            ),
            "proxy_improvement_trace": improvement_trace,
            "proxy_improvement_count": len(improvement_trace),
            "last_proxy_improvement_iteration": (
                None
                if not improvement_trace
                else int(improvement_trace[-1]["iteration"])
            ),
            "hgs_iterations": int(result.num_iterations),
            "active_node_operators": active_node_operators,
            "active_route_operators": active_route_operators,
            "hard_home_depot_lock": bool(
                problem.hard_home_depot_lock
            ),
            "reciprocal_cross_depot_operator": (
                "Exchange11"
                if (
                    not problem.hard_home_depot_lock
                    and "Exchange11" in active_node_operators
                )
                else None
            ),
            "reciprocal_cross_depot_neighbourhood_enabled": bool(
                not problem.hard_home_depot_lock
                and "Exchange11" in active_node_operators
            ),
            "cross_depot_candidate_attempts": (
                cross_depot_candidate_attempts
            ),
            "cross_depot_completed_candidates": (
                cross_depot_completed_candidates
            ),
            "cross_depot_direction_counts": (
                cross_depot_direction_counts
            ),
            "proxy_best_exact_objective": float(
                proxy_best_completion.objective
            ),
            "selected_exact_objectives": [
                float(item[1].objective) for item in selected
            ],
        },
        archive_completions=tuple(
            item[1] for item in exact_ranked
        ),
        base_archive_completions=tuple(
            item[1] for item in base_exact_ranked
        ),
    )


class _CheckpointGeneticAlgorithm(GeneticAlgorithm):
    """PyVRP 0.12.2 loop with deterministic exact-score checkpoints."""

    def __init__(
        self,
        *args: Any,
        checkpoint_interval: int,
        on_checkpoint: Callable[
            [NativeSolution, int, int],
            None,
        ],
        collect_population_history: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._checkpoint_interval = int(checkpoint_interval)
        self._on_checkpoint = on_checkpoint
        self._collect_population_history = bool(
            collect_population_history
        )
        self._historical_population: list[NativeSolution] = []
        self._population_snapshot_count = 0
        self._improvement_trace: list[dict[str, Any]] = []

    @property
    def historical_population(self) -> tuple[NativeSolution, ...]:
        return tuple(self._historical_population)

    @property
    def population_snapshot_count(self) -> int:
        return int(self._population_snapshot_count)

    @property
    def improvement_trace(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._improvement_trace)

    def run(
        self,
        stop: Any,
        collect_stats: bool = True,
        display: bool = False,
        display_interval: float = 5.0,
    ) -> Result:
        printer = ProgressPrinter(display, display_interval)
        printer.start(self._data)
        started = perf_counter()
        stats = Statistics(collect_stats=collect_stats)
        iterations = 0
        iterations_without_improvement = 1
        for solution in self._initial_solutions:
            self._pop.add(solution, self._cost_evaluator)
        use_external_observations = getattr(
            stop,
            "use_external_improvement_observations",
            None,
        )
        if use_external_observations is not None:
            use_external_observations()
        while not stop(self._cost_evaluator.cost(self._best)):
            iterations += 1
            if (
                iterations_without_improvement
                == self._params.num_iters_no_improvement
            ):
                printer.restart()
                iterations_without_improvement = 1
                self._pop.clear()
                for solution in self._initial_solutions:
                    self._pop.add(solution, self._cost_evaluator)
            current_best = self._cost_evaluator.cost(self._best)
            parents = self._pop.select(
                self._rng,
                self._cost_evaluator,
            )
            offspring = self._crossover(
                parents,
                self._data,
                self._cost_evaluator,
                self._rng,
            )
            self._improve_offspring(offspring)
            new_best = self._cost_evaluator.cost(self._best)
            if new_best < current_best:
                self._improvement_trace.append(
                    {
                        "iteration": int(iterations),
                        "objective_before": int(current_best),
                        "objective_after": int(new_best),
                        "improvement_absolute": int(
                            current_best - new_best
                        ),
                        "elapsed_seconds": float(
                            perf_counter() - started
                        ),
                    }
                )
                observe_improvement = getattr(
                    stop,
                    "observe_improvement",
                    None,
                )
                if observe_improvement is not None:
                    observe_improvement(
                        current_best,
                        new_best,
                        iterations,
                    )
                iterations_without_improvement = 1
            else:
                iterations_without_improvement += 1
            if iterations % self._checkpoint_interval == 0:
                if self._collect_population_history:
                    self._historical_population.extend(
                        solution
                        for solution in self._pop
                        if solution.is_feasible()
                    )
                    self._population_snapshot_count += 1
                self._on_checkpoint(
                    self._best,
                    int(new_best),
                    int(iterations),
                )
            stats.collect_from(self._pop, self._cost_evaluator)
            printer.iteration(stats)
        elapsed = perf_counter() - started
        result = Result(self._best, stats, iterations, elapsed)
        printer.end(result)
        return result


def _quality_diverse_native_archive(
    candidates: tuple[NativeSolution, ...],
    cost_evaluator: Any,
    *,
    limit: int,
) -> tuple[list[NativeSolution], int]:
    """Select half by proxy quality and half by broken-pairs diversity."""

    if limit < 1:
        raise ValueError("native archive limit must be positive")
    ranked = sorted(
        candidates,
        key=lambda item: (
            int(cost_evaluator.cost(item)),
            repr(_native_solution_key(item)),
        ),
    )
    if len(ranked) <= limit:
        return ranked, len(ranked)
    quality_count = max(1, int(limit * 0.5))
    selected = list(ranked[:quality_count])
    remaining = list(ranked[quality_count:])
    while remaining and len(selected) < limit:
        chosen_index = min(
            range(len(remaining)),
            key=lambda index: (
                -min(
                    float(
                        broken_pairs_distance(
                            remaining[index],
                            incumbent,
                        )
                    )
                    for incumbent in selected
                ),
                int(cost_evaluator.cost(remaining[index])),
                repr(_native_solution_key(remaining[index])),
            ),
        )
        selected.append(remaining.pop(chosen_index))
    return selected, quality_count


class _AuditedWallclockSafety:
    """Wallclock stop that records whether the safety cap fired."""

    def __init__(self, maximum_seconds: float) -> None:
        self._criterion = MaxRuntime(maximum_seconds)
        self.triggered = False

    def __call__(self, best_cost: float) -> bool:
        self.triggered = bool(self._criterion(best_cost))
        return self.triggered


class _AuditedNoImprovementWallclock:
    """Stop when no threshold-sized improvement resets a wallclock window."""

    def __init__(
        self,
        maximum_no_improvement_seconds: float,
        *,
        minimum_relative_improvement: float = 0.0,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        if maximum_no_improvement_seconds <= 0.0:
            raise ValueError(
                "maximum no-improvement seconds must be positive"
            )
        self.maximum_no_improvement_seconds = float(
            maximum_no_improvement_seconds
        )
        if not 0.0 <= minimum_relative_improvement < 1.0:
            raise ValueError(
                "minimum relative improvement must be in [0, 1)"
            )
        self.minimum_relative_improvement = float(
            minimum_relative_improvement
        )
        self._clock = clock
        self._started_at: float | None = None
        self._last_improvement_at: float | None = None
        self._best_cost: float | None = None
        self._completed_iterations = 0
        self.triggered = False
        self.trigger_iteration: int | None = None
        self.last_improvement_iteration: int | None = None
        self.trigger_elapsed_seconds: float | None = None
        self.last_improvement_elapsed_seconds: float | None = None
        self.no_improvement_elapsed_seconds: float | None = None
        self.timer_reset_count = 0
        self.ignored_strict_improvement_count = 0
        self._improvement_audit: list[dict[str, Any]] = []
        self._external_improvement_observations = False

    @property
    def improvement_audit(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._improvement_audit)

    def use_external_improvement_observations(self) -> None:
        self._external_improvement_observations = True

    def observe_improvement(
        self,
        objective_before: int | float,
        objective_after: int | float,
        iteration: int,
    ) -> None:
        now = float(self._clock())
        if self._started_at is None or self._last_improvement_at is None:
            raise RuntimeError(
                "no-improvement wallclock was not initialized"
            )
        if not objective_after < objective_before:
            raise ValueError("observed improvement must be strict")
        self._record_improvement(
            objective_before=objective_before,
            objective_after=objective_after,
            iteration=int(iteration),
            now=now,
        )

    def _record_improvement(
        self,
        *,
        objective_before: int | float,
        objective_after: int | float,
        iteration: int,
        now: float,
    ) -> None:
        if self._started_at is None:
            raise RuntimeError(
                "no-improvement wallclock was not initialized"
            )
        improvement_absolute = objective_before - objective_after
        improvement_relative = (
            0.0
            if objective_before == 0.0
            else improvement_absolute / abs(objective_before)
        )
        timer_reset = (
            improvement_relative >= self.minimum_relative_improvement
        )
        self._best_cost = objective_after
        if timer_reset:
            self._last_improvement_at = now
            self.last_improvement_iteration = int(iteration)
            self.last_improvement_elapsed_seconds = float(
                now - self._started_at
            )
            self.timer_reset_count += 1
        else:
            self.ignored_strict_improvement_count += 1
        self._improvement_audit.append(
            {
                "iteration": int(iteration),
                "objective_before": objective_before,
                "objective_after": objective_after,
                "improvement_absolute": improvement_absolute,
                "improvement_relative": improvement_relative,
                "timer_reset_threshold_relative": (
                    self.minimum_relative_improvement
                ),
                "timer_reset": timer_reset,
                "elapsed_seconds": float(now - self._started_at),
            }
        )

    def __call__(self, best_cost: float) -> bool:
        now = float(self._clock())
        if self._started_at is None:
            self._started_at = now
            self._last_improvement_at = now
            self._best_cost = float(best_cost)
            self.last_improvement_iteration = 0
            self.last_improvement_elapsed_seconds = 0.0
        elif (
            not self._external_improvement_observations
            and (
                self._best_cost is None
                or float(best_cost) < self._best_cost
            )
        ):
            objective_before = float(self._best_cost)
            objective_after = float(best_cost)
            self._record_improvement(
                objective_before=objective_before,
                objective_after=objective_after,
                iteration=int(self._completed_iterations),
                now=now,
            )

        if self._last_improvement_at is None or self._started_at is None:
            raise RuntimeError(
                "no-improvement wallclock was not initialized"
            )
        no_improvement_elapsed = float(now - self._last_improvement_at)
        if no_improvement_elapsed >= self.maximum_no_improvement_seconds:
            self.triggered = True
            self.trigger_iteration = int(self._completed_iterations)
            self.trigger_elapsed_seconds = float(now - self._started_at)
            self.no_improvement_elapsed_seconds = no_improvement_elapsed
            return True

        self._completed_iterations += 1
        return False
