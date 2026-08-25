"""Project-domain adaptation of PyVRP 0.12.2 population semantics."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Generic, TypeVar

from setp_hgs_kernel._setp_hgs_kernel import PopulationParams

if TYPE_CHECKING:
    from collections.abc import Iterator

SolutionT = TypeVar("SolutionT")
EvaluationT = TypeVar("EvaluationT")


@dataclass(frozen=True)
class EvaluatedSolution(Generic[SolutionT, EvaluationT]):
    solution: SolutionT
    evaluation: EvaluationT


@dataclass
class _Item(Generic[SolutionT, EvaluationT]):
    candidate: EvaluatedSolution[SolutionT, EvaluationT]
    fitness: float = 0.0
    proximity: list[tuple[float, int]] = field(default_factory=list)


class ExternalPopulation(Generic[SolutionT, EvaluationT]):
    def __init__(
        self,
        diversity_op: Callable[[SolutionT, SolutionT], float],
        *,
        is_feasible: Callable[[EvaluationT], bool],
        penalised_cost: Callable[[EvaluationT], float],
        refresh_penalties: Callable[[tuple[EvaluationT, ...]], None],
        minimum_penalty_population_size: int,
        fingerprint: Callable[[SolutionT], str],
        params: PopulationParams | None = None,
    ) -> None:
        self._diversity_op = diversity_op
        self._is_feasible = is_feasible
        self._penalised_cost = penalised_cost
        self._refresh_penalties_callback = refresh_penalties
        self._minimum_penalty_population_size = minimum_penalty_population_size
        self._fingerprint = fingerprint
        self._params = params if params is not None else PopulationParams()
        self._feasible: list[_Item[SolutionT, EvaluationT]] = []
        self._infeasible: list[_Item[SolutionT, EvaluationT]] = []

    def __iter__(self) -> Iterator[EvaluatedSolution[SolutionT, EvaluationT]]:
        for item in (*self._feasible, *self._infeasible):
            yield item.candidate

    def __len__(self) -> int:
        return len(self._feasible) + len(self._infeasible)

    def clear(self) -> None:
        self._feasible.clear()
        self._infeasible.clear()

    def add(
        self,
        candidate: EvaluatedSolution[SolutionT, EvaluationT],
    ) -> bool:
        subpopulation = (
            self._feasible
            if self._is_feasible(candidate.evaluation)
            else self._infeasible
        )
        item = _Item(candidate)
        for other in subpopulation:
            distance = self._diversity_op(
                candidate.solution,
                other.candidate.solution,
            )
            other_position = bisect_left(
                [value for value, _identity in other.proximity],
                distance,
            )
            other.proximity.insert(other_position, (distance, id(item)))
            item_position = bisect_left(
                [value for value, _identity in item.proximity],
                distance,
            )
            item.proximity.insert(item_position, (distance, id(other)))
        subpopulation.append(item)
        self._refresh_penalties()
        retained = True
        if len(subpopulation) > self._params.max_pop_size:
            retained = self._purge(subpopulation, candidate)
            self._refresh_penalties()
        return retained

    def select(self, rng, k: int = 2) -> tuple[
        EvaluatedSolution[SolutionT, EvaluationT],
        EvaluatedSolution[SolutionT, EvaluationT],
    ]:
        if len(self) == 0:
            raise ValueError("cannot select from an empty population")
        self._refresh_penalties()
        self._update_fitness(self._feasible)
        self._update_fitness(self._infeasible)
        first = self._tournament(rng, k)
        second = self._tournament(rng, k)
        diversity = self._diversity_op(
            first.solution,
            second.solution,
        )
        tries = 1
        while not (
            self._params.lb_diversity
            <= diversity
            <= self._params.ub_diversity
        ) and tries <= 10:
            second = self._tournament(rng, k)
            diversity = self._diversity_op(
                first.solution,
                second.solution,
            )
            tries += 1
        return first, second

    def best_feasible(self) -> EvaluatedSolution[SolutionT, EvaluationT] | None:
        if not self._feasible:
            return None
        self._refresh_penalties()
        return min(
            (item.candidate for item in self._feasible),
            key=lambda item: self._penalised_cost(item.evaluation),
        )

    def best_penalised(
        self,
    ) -> EvaluatedSolution[SolutionT, EvaluationT] | None:
        candidates = tuple(self)
        if not candidates:
            return None
        self._refresh_penalties()
        return min(
            candidates,
            key=lambda item: self._penalised_cost(item.evaluation),
        )

    def _tournament(self, rng, k: int) -> EvaluatedSolution[SolutionT, EvaluationT]:
        if k <= 0:
            raise ValueError("tournament size must be positive")
        items = (*self._feasible, *self._infeasible)
        sampled = [items[int(rng.randint(len(items)))] for _ in range(k)]
        return min(sampled, key=lambda item: item.fitness).candidate

    def _purge(
        self,
        subpopulation: list[_Item[SolutionT, EvaluationT]],
        inserted: EvaluatedSolution[SolutionT, EvaluationT],
    ) -> bool:
        retained = True
        while len(subpopulation) > self._params.min_pop_size:
            duplicate = self._duplicate_index(subpopulation)
            if duplicate is None:
                break
            if subpopulation[duplicate].candidate is inserted:
                retained = False
            self._remove(subpopulation, duplicate)

        while len(subpopulation) > self._params.min_pop_size:
            self._update_fitness(subpopulation)
            worst = max(
                range(len(subpopulation)),
                key=lambda idx: subpopulation[idx].fitness,
            )
            if subpopulation[worst].candidate is inserted:
                retained = False
            self._remove(subpopulation, worst)
        return retained

    def _refresh_penalties(self) -> None:
        evaluations = tuple(candidate.evaluation for candidate in self)
        if len(evaluations) >= self._minimum_penalty_population_size:
            self._refresh_penalties_callback(evaluations)

    def _duplicate_index(
        self,
        subpopulation: list[_Item[SolutionT, EvaluationT]],
    ) -> int | None:
        by_identity = {id(item): item for item in subpopulation}
        for index, item in enumerate(subpopulation):
            if not item.proximity:
                continue
            other = by_identity[item.proximity[0][1]]
            if self._fingerprint(
                other.candidate.solution
            ) == self._fingerprint(item.candidate.solution):
                # Match copied SubPopulation::purge(): remove the first item
                # that has an identical neighbour, independent of cost.
                return index
        return None

    @staticmethod
    def _remove(
        subpopulation: list[_Item[SolutionT, EvaluationT]],
        index: int,
    ) -> None:
        removed = subpopulation[index]
        removed_identity = id(removed)
        for item in subpopulation:
            if item is removed:
                continue
            item.proximity[:] = [
                entry
                for entry in item.proximity
                if entry[1] != removed_identity
            ]
        subpopulation.pop(index)

    def _update_fitness(
        self,
        subpopulation: list[_Item[SolutionT, EvaluationT]],
    ) -> None:
        size = len(subpopulation)
        if size == 0:
            return
        by_cost = sorted(
            range(size),
            key=lambda idx: self._penalised_cost(
                subpopulation[idx].candidate.evaluation
            ),
        )
        diversity: list[tuple[float, int]] = []
        for cost_rank, idx in enumerate(by_cost):
            proximity = subpopulation[idx].proximity
            closest = proximity[: self._params.num_close]
            total_distance = 0.0
            for distance, _identity in closest:
                # Deliberately use the copied C++ left-to-right accumulation.
                # Python 3.12+ ``sum`` uses a different float algorithm and
                # can reorder diversity ties, changing survivor selection.
                total_distance += distance
            diversity.append(
                (-total_distance / max(
                    len(closest),
                    1,
                ), cost_rank)
            )
        diversity.sort()
        elite = min(self._params.num_elite, size)
        diversity_weight = 1.0 - elite / size
        for diversity_rank, (_distance, cost_rank) in enumerate(diversity):
            idx = by_cost[cost_rank]
            subpopulation[idx].fitness = (
                cost_rank + diversity_weight * diversity_rank
            ) / (2 * size)
