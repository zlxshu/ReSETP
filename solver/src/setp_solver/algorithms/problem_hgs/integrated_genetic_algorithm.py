# declared_identity=PROJECT_DOMAIN
# provenance_status=UNKNOWN
# first_seen_commit=15ea9919006a53909745caa8f669f1c68aee0641
# git_commit_author=Leixishu Zhou (not evidence of content authorship)
# original_author=UNKNOWN
# pre_move_sha256=2d40fc90dbbf5b15e3551691f9256ef630f67956275b78f0ee0bd2d881cac788
"""One copied HGS control flow for native and complete-problem evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, Callable, Collection, Generic, TypeVar

from .hgs_control import HGSControl
from .patched_genetic_algorithm import GeneticAlgorithmParams

if TYPE_CHECKING:
    from .external_population import (
        EvaluatedSolution,
        ExternalPopulation,
    )

SolutionT = TypeVar("SolutionT")
EvaluationT = TypeVar("EvaluationT")


@dataclass(frozen=True)
class IntegratedProblemAdapter(Generic[SolutionT, EvaluationT]):
    evaluate: Callable[
        [SolutionT],
        EvaluatedSolution[SolutionT, EvaluationT] | None,
    ]
    refine: Callable[
        [EvaluatedSolution[SolutionT, EvaluationT]],
        tuple[EvaluatedSolution[SolutionT, EvaluationT], ...],
    ]
    is_feasible: Callable[[EvaluationT], bool]
    objective: Callable[[EvaluationT], float]
    penalised_cost: Callable[[EvaluationT], float]
    register: Callable[[EvaluationT], None] | None
    fingerprint: Callable[[SolutionT], str]
    minimum_initial_population_size: int = 1
    breed: Callable[
        [
            tuple[
                EvaluatedSolution[SolutionT, EvaluationT],
                EvaluatedSolution[SolutionT, EvaluationT],
            ]
        ],
        EvaluatedSolution[SolutionT, EvaluationT] | None,
    ] | None = None
    repair: Callable[
        [EvaluatedSolution[SolutionT, EvaluationT]],
        EvaluatedSolution[SolutionT, EvaluationT] | None,
    ] | None = None
    finalise: Callable[
        [EvaluatedSolution[SolutionT, EvaluationT]],
        EvaluatedSolution[SolutionT, EvaluationT] | None,
    ] | None = None


@dataclass(frozen=True)
class IntegratedRunAccounting:
    iterations: int
    rejected: int
    repaired: int
    finalised: int
    restarts: int
    elapsed_seconds: float


@dataclass(frozen=True)
class IntegratedRunResult(Generic[SolutionT, EvaluationT]):
    best: EvaluatedSolution[SolutionT, EvaluationT]
    accounting: IntegratedRunAccounting


class IntegratedGeneticAlgorithm(Generic[SolutionT, EvaluationT]):
    def __init__(
        self,
        data,
        penalty_manager,
        rng,
        population: ExternalPopulation[SolutionT, EvaluationT],
        search_method,
        crossover_op,
        initial_solutions: Collection[SolutionT],
        adapter: IntegratedProblemAdapter[SolutionT, EvaluationT],
        params: GeneticAlgorithmParams = GeneticAlgorithmParams(),
    ) -> None:
        if len(initial_solutions) == 0:
            raise ValueError("Expected at least one initial solution.")
        self._data = data
        self._pm = penalty_manager
        self._rng = rng
        self._pop = population
        self._search = search_method
        self._crossover = crossover_op
        self._initial_solutions = tuple(initial_solutions)
        self._adapter = adapter
        self._params = params
        self._best_so_far = None

    @property
    def _cost_evaluator(self):
        return self._pm.cost_evaluator()

    @property
    def best_so_far(self):
        return self._best_so_far

    def run(self, stop) -> IntegratedRunResult[SolutionT, EvaluationT]:
        started = perf_counter()
        rejected = 0
        repaired = 0
        finalised = 0
        restarts = 0

        initial = []
        for solution in self._initial_solutions:
            candidate = self._adapter.evaluate(solution)
            if candidate is None:
                rejected += 1
                continue
            initial.append(candidate)
            self._pop.add(candidate)
        if len(initial) < self._adapter.minimum_initial_population_size:
            raise ValueError("complete evaluator retained too few initial solutions")
        best = self._best()
        self._best_so_far = best

        def restart() -> None:
            nonlocal restarts
            restarts += 1
            self._pop.clear()
            for candidate in initial:
                self._pop.add(candidate)

        control = HGSControl(
            should_stop=lambda _state: stop(self._best_value(best)),
            best_value=lambda: self._best_value(best),
            restart_after_iterations_without_improvement=(
                self._params.num_iters_no_improvement
            ),
            restart=restart,
            initial_iterations_without_improvement=1,
        )
        for _iteration in control.iterations():
            parents = self._pop.select(self._rng)
            if self._adapter.breed is None:
                offspring = self._crossover(
                    tuple(parent.solution for parent in parents),
                    self._data,
                    self._cost_evaluator,
                    self._rng,
                )
                offspring = self._search(offspring, self._cost_evaluator)
                candidate = self._adapter.evaluate(offspring)
            else:
                candidate = self._adapter.breed(parents)
            if candidate is None:
                rejected += 1
                continue
            refined_candidates = self._adapter.refine(candidate)
            if not refined_candidates:
                raise ValueError("problem refiner returned no candidates")
            for refined in refined_candidates:
                self._pop.add(refined)
                self._register(refined.evaluation)
                if self._better(refined, best):
                    best = refined
                    self._best_so_far = best

            if (
                not self._adapter.is_feasible(candidate.evaluation)
                and self._rng.rand() < self._params.repair_probability
            ):
                if self._adapter.repair is None:
                    repair_solution = self._search(
                        candidate.solution,
                        self._pm.booster_cost_evaluator(),
                    )
                    repaired_candidate = self._adapter.evaluate(
                        repair_solution
                    )
                else:
                    repaired_candidate = self._adapter.repair(candidate)
                if repaired_candidate is None:
                    rejected += 1
                    continue
                repaired += 1
                repaired_candidates = self._adapter.refine(
                    repaired_candidate
                )
                if not repaired_candidates:
                    raise ValueError("problem refiner returned no candidates")
                for refined in repaired_candidates:
                    if self._adapter.is_feasible(refined.evaluation):
                        self._pop.add(refined)
                        self._register(refined.evaluation)
                    if self._better(refined, best):
                        best = refined
                        self._best_so_far = best

        if self._adapter.finalise is not None:
            final_candidate = self._adapter.finalise(best)
            if final_candidate is not None:
                finalised += 1
                self._pop.add(final_candidate)
                self._register(final_candidate.evaluation)
                if self._better(final_candidate, best):
                    best = final_candidate
                    self._best_so_far = best

        state = control.state
        return IntegratedRunResult(
            best,
            IntegratedRunAccounting(
                iterations=state.iterations,
                rejected=rejected,
                repaired=repaired,
                finalised=finalised,
                restarts=restarts,
                elapsed_seconds=perf_counter() - started,
            ),
        )

    def _best(self) -> EvaluatedSolution[SolutionT, EvaluationT]:
        candidate = self._pop.best_feasible() or self._pop.best_penalised()
        if candidate is None:
            raise AssertionError("integrated population is empty")
        return candidate

    def _register(self, evaluation: EvaluationT) -> None:
        if self._adapter.register is not None:
            self._adapter.register(evaluation)

    def _best_value(
        self,
        candidate: EvaluatedSolution[SolutionT, EvaluationT],
    ) -> float:
        evaluation = candidate.evaluation
        if self._adapter.is_feasible(evaluation):
            return self._adapter.objective(evaluation)
        return self._adapter.penalised_cost(evaluation)

    def _better(
        self,
        candidate: EvaluatedSolution[SolutionT, EvaluationT],
        incumbent: EvaluatedSolution[SolutionT, EvaluationT],
    ) -> bool:
        candidate_feasible = self._adapter.is_feasible(candidate.evaluation)
        incumbent_feasible = self._adapter.is_feasible(incumbent.evaluation)
        if candidate_feasible != incumbent_feasible:
            return candidate_feasible
        if candidate_feasible:
            return self._adapter.objective(
                candidate.evaluation
            ) < self._adapter.objective(incumbent.evaluation)
        return self._adapter.penalised_cost(
            candidate.evaluation
        ) < self._adapter.penalised_cost(incumbent.evaluation)
