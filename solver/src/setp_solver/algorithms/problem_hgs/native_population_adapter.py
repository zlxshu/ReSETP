# declared_identity=PROJECT_DOMAIN
# provenance_status=UNKNOWN
# first_seen_commit=15ea9919006a53909745caa8f669f1c68aee0641
# git_commit_author=Leixishu Zhou (not evidence of content authorship)
# original_author=UNKNOWN
# pre_move_sha256=371b547a18a654a70869340a2031a59d189c3d6e8f6071a891d844b42997fcca
"""Expose the copied native population through the integrated-loop API."""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from setp_hgs_kernel.Population import Population

from .external_population import EvaluatedSolution

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
        self._evaluated: list[
            tuple[object, EvaluatedSolution[object, EvaluationT]]
        ] = []

    def __len__(self) -> int:
        return len(self._population)

    def add(self, candidate: EvaluatedSolution[object, EvaluationT]) -> bool:
        size_before = len(self._population)
        self._evaluated = [
            pair for pair in self._evaluated
            if pair[0] is not candidate.solution
        ]
        self._evaluated.append((candidate.solution, candidate))
        self._population.add(candidate.solution, self._cost_evaluator())
        if len(self._population) < size_before + 1:
            active_solutions = tuple(self._population)
            self._evaluated = [
                pair for pair in self._evaluated
                if any(pair[0] is active for active in active_solutions)
            ]
        return True

    def clear(self) -> None:
        self._population.clear()
        self._evaluated.clear()

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
        for cached_solution, cached in self._evaluated:
            if cached_solution is solution:
                return cached
        evaluated = self._evaluate(solution)
        self._evaluated.append((solution, evaluated))
        return evaluated
