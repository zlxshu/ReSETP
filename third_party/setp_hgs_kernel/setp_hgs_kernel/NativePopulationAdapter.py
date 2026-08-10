"""Expose the copied native population through the integrated-loop API."""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from setp_hgs_kernel.ExternalPopulation import EvaluatedSolution
from setp_hgs_kernel.Population import Population

EvaluationT = TypeVar("EvaluationT")


class NativePopulationAdapter(Generic[EvaluationT]):
    """Reuse the compiled native population when native truth is sufficient."""

    def __init__(
        self,
        diversity_op,
        *,
        evaluate: Callable[[object], EvaluatedSolution[object, EvaluationT]],
        cost_evaluator: Callable[[], object],
        params=None,
    ) -> None:
        self._population = Population(diversity_op, params)
        self._evaluate = evaluate
        self._cost_evaluator = cost_evaluator
        self._evaluated_by_solution_id: dict[
            int, EvaluatedSolution[object, EvaluationT]
        ] = {}

    def __len__(self) -> int:
        return len(self._population)

    def add(self, candidate: EvaluatedSolution[object, EvaluationT]) -> bool:
        size_before = len(self._population)
        self._evaluated_by_solution_id[id(candidate.solution)] = candidate
        self._population.add(candidate.solution, self._cost_evaluator())
        if len(self._population) < size_before + 1:
            active_solution_ids = {
                id(solution) for solution in self._population
            }
            self._evaluated_by_solution_id = {
                solution_id: evaluated
                for solution_id, evaluated in (
                    self._evaluated_by_solution_id.items()
                )
                if solution_id in active_solution_ids
            }
        return True

    def clear(self) -> None:
        self._population.clear()
        self._evaluated_by_solution_id.clear()

    def select(self, rng, k: int = 2):
        return tuple(
            self._candidate(solution)
            for solution in self._population.select(
                rng,
                self._cost_evaluator(),
                k,
            )
        )

    def best_feasible(self):
        feasible = tuple(
            solution
            for solution in self._population
            if solution.is_feasible()
        )
        if not feasible:
            return None
        cost_evaluator = self._cost_evaluator()
        return self._candidate(
            min(feasible, key=cost_evaluator.cost)
        )

    def best_penalised(self):
        solutions = tuple(self._population)
        if not solutions:
            return None
        cost_evaluator = self._cost_evaluator()
        return self._candidate(
            min(solutions, key=cost_evaluator.penalised_cost)
        )

    def _candidate(self, solution):
        cached = self._evaluated_by_solution_id.get(id(solution))
        if cached is not None:
            return cached
        evaluated = self._evaluate(solution)
        self._evaluated_by_solution_id[id(solution)] = evaluated
        return evaluated
