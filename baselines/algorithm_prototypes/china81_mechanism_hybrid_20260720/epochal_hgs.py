"""Genuine HGS with exact ReSETP elite migration between epochs."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

import pyvrp
from pyvrp.GeneticAlgorithm import GeneticAlgorithm
from pyvrp.PenaltyManager import PenaltyManager
from pyvrp.Population import Population
from pyvrp._pyvrp import RandomNumberGenerator
from pyvrp._pyvrp import Solution as NativeSolution
from pyvrp.crossover import ordered_crossover
from pyvrp.crossover import selective_route_exchange
from pyvrp.diversity import broken_pairs_distance
from pyvrp.search import LocalSearch, compute_neighbours
from pyvrp.solve import SolveParams
from pyvrp.stop import MaxIterations, MaxRuntime, MultipleCriteria

from pyvrp_adapter import (
    China81PyVRPProblem,
    _native_solution_key,
    _project_initial_solution,
    _translate_solution,
    build_pyvrp_problem,
)
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
        )
        epochs.append(epoch)
        warm_elites = epoch.elite_skeletons
    all_completions = [
        complete_china81_route_skeleton(
            common_initial_solution,
            bundle,
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
) -> HgsExactEpoch:
    if max_hgs_iterations is None:
        if runtime_seconds is None or runtime_seconds <= 0.0:
            raise ValueError("legacy HGS runtime must be positive")
        stop = MaxRuntime(float(runtime_seconds))
        stop_mode = "LEGACY_WALLCLOCK_PRIMARY"
        safety = None
    else:
        if max_hgs_iterations < 1:
            raise ValueError("max_hgs_iterations must be positive")
        if (
            wallclock_safety_seconds is None
            or wallclock_safety_seconds <= 0.0
        ):
            raise ValueError(
                "deterministic HGS iteration mode requires a positive "
                "wallclock safety cap"
            )
        safety = _AuditedWallclockSafety(
            float(wallclock_safety_seconds)
        )
        stop = MultipleCriteria(
            [
                MaxIterations(int(max_hgs_iterations)),
                safety,
            ]
        )
        stop_mode = "DETERMINISTIC_ITERATIONS_WITH_WALLCLOCK_SAFETY"
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
        _project_initial_solution(item, data, problem)
        for item in warm_elites
    ]
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
    result = algorithm.run(
        stop,
        collect_stats=True,
        display=False,
        display_interval=params.display_interval,
    )
    cost_evaluator = penalty_manager.cost_evaluator()
    population_items = [*initial_solutions, *list(population)]
    population_items.append(result.best)
    unique: dict[tuple[Any, ...], Any] = {}
    for native in population_items:
        unique.setdefault(_native_solution_key(native), native)
    proxy_ranked = sorted(
        unique.values(),
        key=cost_evaluator.cost,
    )[: int(max_archive_candidates)]
    exact_candidates: list[
        tuple[Solution, China81CompletionResult, int]
    ] = []
    failures: list[str] = []
    archive_completion_attempts = 0
    cross_depot_candidate_attempts = 0
    cross_depot_completed_candidates = 0
    cross_depot_direction_counts: dict[str, int] = {}
    for native in proxy_ranked:
        archive_completion_attempts += 1
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
            )
            if (
                problem.hard_home_depot_lock
                and completion.solution.cross_site_services
            ):
                raise ValueError(
                    "hard home-depot control candidate contains "
                    "cross-site service"
                )
            if completion.solution.cross_site_services:
                cross_depot_completed_candidates += 1
            exact_candidates.append(
                (
                    skeleton,
                    completion,
                    int(cost_evaluator.cost(native)),
                )
            )
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            failures.append(str(exc))
    common_completion = complete_china81_route_skeleton(
        common_initial_solution,
        bundle,
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
    exact_ranked = sorted(
        exact_candidates,
        key=lambda item: (
            item[1].objective,
            item[2],
        ),
    )
    selected = exact_ranked[: int(exact_elite_count)]
    proxy_best_completion_failure: str | None = None
    try:
        proxy_best_completion = complete_china81_route_skeleton(
            _translate_solution(result.best, problem),
            bundle,
        )
        if (
            problem.hard_home_depot_lock
            and proxy_best_completion.solution.cross_site_services
        ):
            raise ValueError(
                "hard home-depot control proxy best contains cross-site "
                "service"
            )
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        proxy_best_completion_failure = str(exc)
        proxy_best_completion = min(
            (item[1] for item in exact_candidates),
            key=lambda item: item.objective,
        )
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
            "warm_elite_count": len(warm_native),
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
            "archive_completion_attempts": (
                archive_completion_attempts
            ),
            "archive_candidates_completed": (
                len(exact_candidates) - 1
            ),
            "archive_completion_failures": failures,
            "common_initial_completion_attempts": 1,
            "proxy_best_completion_attempts": 1,
            "proxy_best_completion_failure": (
                proxy_best_completion_failure
            ),
            "complete_candidate_evaluation_attempts": (
                archive_completion_attempts + 2
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
    )


class _AuditedWallclockSafety:
    """Wallclock stop that records whether the safety cap fired."""

    def __init__(self, maximum_seconds: float) -> None:
        self._criterion = MaxRuntime(maximum_seconds)
        self.triggered = False

    def __call__(self, best_cost: float) -> bool:
        self.triggered = bool(self._criterion(best_cost))
        return self.triggered
