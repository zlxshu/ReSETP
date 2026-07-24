"""Genuine HGS with exact ReSETP elite migration between epochs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable

import pyvrp
from pyvrp.GeneticAlgorithm import GeneticAlgorithm
from pyvrp.PenaltyManager import PenaltyManager
from pyvrp.Population import Population
from pyvrp.ProgressPrinter import ProgressPrinter
from pyvrp.Result import Result
from pyvrp.Statistics import Statistics
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
    exact_checkpoint_interval_iterations: int | None = None,
    collect_historical_population_archive: bool = False,
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
    if exact_checkpoint_interval_iterations is not None:
        if max_hgs_iterations is None:
            raise ValueError(
                "exact checkpoints require deterministic HGS iterations"
            )
        if exact_checkpoint_interval_iterations < 1:
            raise ValueError(
                "exact checkpoint interval must be positive"
            )
        if (
            max_hgs_iterations
            % exact_checkpoint_interval_iterations
            != 0
        ):
            raise ValueError(
                "HGS iteration budget must be divisible by the exact "
                "checkpoint interval"
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
        _project_initial_solution(item, data, problem)
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

    def on_exact_checkpoint(
        native: NativeSolution,
        proxy_cost: int,
        iteration: int,
    ) -> None:
        observed_at = perf_counter() - started
        try:
            skeleton = _translate_solution(native, problem)
            completion = complete_china81_route_skeleton(
                skeleton,
                bundle,
            )
            checkpoint_candidates.append(
                (skeleton, completion, int(proxy_cost))
            )
            checkpoint_observations.append(
                {
                    "iteration": int(iteration),
                    "elapsed_seconds": float(observed_at),
                    "proxy_cost": int(proxy_cost),
                    "complete_objective": float(
                        completion.objective
                    ),
                    "status": "PASS",
                }
            )
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            checkpoint_failures.append(str(exc))
            checkpoint_observations.append(
                {
                    "iteration": int(iteration),
                    "elapsed_seconds": float(observed_at),
                    "proxy_cost": int(proxy_cost),
                    "complete_objective": None,
                    "status": "INFEASIBLE_OR_ERROR",
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
    base_exact_candidates = list(exact_candidates)
    exact_candidates.extend(checkpoint_candidates)
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
            "exact_checkpoint_completed": len(
                checkpoint_candidates
            ),
            "exact_checkpoint_failures": checkpoint_failures,
            "exact_checkpoint_observations": (
                checkpoint_observations
            ),
            "common_initial_completion_attempts": 1,
            "proxy_best_completion_attempts": 1,
            "proxy_best_completion_failure": (
                proxy_best_completion_failure
            ),
            "complete_candidate_evaluation_attempts": (
                archive_completion_attempts
                + len(checkpoint_observations)
                + 2
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

    @property
    def historical_population(self) -> tuple[NativeSolution, ...]:
        return tuple(self._historical_population)

    @property
    def population_snapshot_count(self) -> int:
        return int(self._population_snapshot_count)

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
