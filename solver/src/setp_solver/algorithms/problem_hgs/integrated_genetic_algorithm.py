"""Project-domain adaptation of the PyVRP 0.12.2 HGS control flow."""

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
        EvaluatedSolution[SolutionT, EvaluationT],
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


@dataclass(frozen=True)
class IntegratedRunAccounting:
    iterations: int
    rejected: int
    repaired: int
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
        best = min(
            initial,
            key=lambda candidate: (
                self._adapter.objective(candidate.evaluation)
                if self._adapter.is_feasible(candidate.evaluation)
                else float("inf")
            ),
        )
        self._best_so_far = best

        def restart() -> None:
            nonlocal restarts
            restarts += 1
            self._pop.clear()
            for candidate in initial:
                self._pop.add(candidate)

        control = HGSControl(
            should_stop=lambda _state: stop(
                self._best_value(self._best_so_far)
            ),
            best_value=lambda: self._best_value(self._best_so_far),
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
            rejected_delta, repaired_delta = self._improve_offspring(candidate)
            rejected += rejected_delta
            repaired += repaired_delta

        state = control.state
        return IntegratedRunResult(
            self._best_so_far,
            IntegratedRunAccounting(
                iterations=state.iterations,
                rejected=rejected,
                repaired=repaired,
                restarts=restarts,
                elapsed_seconds=perf_counter() - started,
            ),
        )

    def _improve_offspring(
        self,
        candidate: EvaluatedSolution[SolutionT, EvaluationT],
    ) -> tuple[int, int]:
        refined = self._adapter.refine(candidate)
        self._pop.add(refined)
        self._register(refined.evaluation)
        self._consider_for_best(refined)

        if (
            self._adapter.is_feasible(refined.evaluation)
            or self._rng.rand() >= self._params.repair_probability
        ):
            return 0, 0

        if self._adapter.repair is None:
            repair_solution = self._search(
                refined.solution,
                self._pm.booster_cost_evaluator(),
            )
            repaired = self._adapter.evaluate(repair_solution)
        else:
            repaired = self._adapter.repair(refined)
        if repaired is None:
            return 1, 0
        if self._adapter.is_feasible(repaired.evaluation):
            self._pop.add(repaired)
            self._register(repaired.evaluation)
        self._consider_for_best(repaired)
        return 0, 1

    def _consider_for_best(
        self,
        candidate: EvaluatedSolution[SolutionT, EvaluationT],
    ) -> None:
        if self._better(candidate, self._best_so_far):
            self._best_so_far = candidate

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
        return float("inf")

    def _better(
        self,
        candidate: EvaluatedSolution[SolutionT, EvaluationT],
        incumbent: EvaluatedSolution[SolutionT, EvaluationT],
    ) -> bool:
        candidate_feasible = self._adapter.is_feasible(candidate.evaluation)
        incumbent_feasible = self._adapter.is_feasible(incumbent.evaluation)
        if not candidate_feasible:
            return False
        return not incumbent_feasible or self._adapter.objective(
            candidate.evaluation
        ) < self._adapter.objective(incumbent.evaluation)
