"""Private NSGA-II population over complete cost and emissions evaluations.

The public solver and the copied single-objective ``ExternalPopulation`` stay
unchanged.  This module is selected only by the private adapter when the
bi-objective mode is explicitly enabled.

Non-dominated sorting, crowding distance, crowded comparison, and survivor
selection follow Deb et al. (2002), Sections III-A--III-C.  The existing
broken-pairs distance is retained solely for the parent-pair diversity bounds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Generic, Iterable, TypeVar

from setp_hgs_kernel.ExternalPopulation import (
    EvaluatedSolution,
    ExternalPopulation,
)
from setp_hgs_kernel._setp_hgs_kernel import PopulationParams


SINGLE_OBJECTIVE = "single_objective"
BI_OBJECTIVE = "bi_objective"
POPULATION_OBJECTIVE_MODES = frozenset({SINGLE_OBJECTIVE, BI_OBJECTIVE})

SolutionT = TypeVar("SolutionT")
EvaluationT = TypeVar("EvaluationT")
ValueT = TypeVar("ValueT")


@dataclass(frozen=True)
class ObjectiveValues:
    """The two minimisation objectives used by the private population."""

    total_cost: float
    total_emissions_kg: float

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.total_cost)):
            raise ValueError("total cost objective must be finite")
        if not math.isfinite(float(self.total_emissions_kg)):
            raise ValueError("total emissions objective must be finite")


@dataclass(frozen=True)
class PopulationPoint(Generic[ValueT]):
    """One candidate projected onto feasibility and objective space."""

    value: ValueT
    objectives: ObjectiveValues
    feasible: bool
    penalised_cost: float
    fingerprint: str

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.penalised_cost)):
            raise ValueError("penalised cost must be finite")
        if not self.fingerprint:
            raise ValueError("population fingerprint cannot be empty")


@dataclass(frozen=True)
class RankedPoint(Generic[ValueT]):
    point: PopulationPoint[ValueT]
    rank: int
    crowding_distance: float


@dataclass(frozen=True)
class BiObjectiveArchiveEntry(Generic[SolutionT, EvaluationT]):
    candidate: EvaluatedSolution[SolutionT, EvaluationT]
    objectives: ObjectiveValues
    fingerprint: str


@dataclass(frozen=True)
class BiObjectiveArchive(Generic[SolutionT, EvaluationT]):
    entries: tuple[BiObjectiveArchiveEntry[SolutionT, EvaluationT], ...]
    cost_priority: BiObjectiveArchiveEntry[SolutionT, EvaluationT] | None
    emissions_priority: BiObjectiveArchiveEntry[SolutionT, EvaluationT] | None


def validate_population_objective_mode(mode: str) -> str:
    value = str(mode)
    if value not in POPULATION_OBJECTIVE_MODES:
        choices = ", ".join(sorted(POPULATION_OBJECTIVE_MODES))
        raise ValueError(f"population objective mode must be one of: {choices}")
    return value


def dominates(
    left: PopulationPoint[ValueT],
    right: PopulationPoint[ValueT],
) -> bool:
    """Return the approved feasibility-first Pareto dominance relation."""

    if left.feasible != right.feasible:
        return left.feasible
    if not left.feasible:
        return float(left.penalised_cost) < float(right.penalised_cost)

    left_values = (
        float(left.objectives.total_cost),
        float(left.objectives.total_emissions_kg),
    )
    right_values = (
        float(right.objectives.total_cost),
        float(right.objectives.total_emissions_kg),
    )
    return all(a <= b for a, b in zip(left_values, right_values, strict=True)) and any(
        a < b for a, b in zip(left_values, right_values, strict=True)
    )


def fast_non_dominated_sort(
    points: Iterable[PopulationPoint[ValueT]],
) -> tuple[tuple[PopulationPoint[ValueT], ...], ...]:
    """Deb's O(MN^2) non-dominated sorting with stable input identities."""

    population = tuple(points)
    if not population:
        return ()

    domination_counts = [0] * len(population)
    dominated_sets: list[list[int]] = [[] for _point in population]
    first_front: list[int] = []

    for left_index, left in enumerate(population):
        for right_index, right in enumerate(population):
            if left_index == right_index:
                continue
            if dominates(left, right):
                dominated_sets[left_index].append(right_index)
            elif dominates(right, left):
                domination_counts[left_index] += 1
        if domination_counts[left_index] == 0:
            first_front.append(left_index)

    front_indices: list[list[int]] = [first_front]
    layer = 0
    while layer < len(front_indices) and front_indices[layer]:
        next_front: list[int] = []
        for left_index in front_indices[layer]:
            for right_index in dominated_sets[left_index]:
                domination_counts[right_index] -= 1
                if domination_counts[right_index] == 0:
                    next_front.append(right_index)
        if next_front:
            front_indices.append(next_front)
        layer += 1

    return tuple(
        tuple(population[index] for index in front) for front in front_indices if front
    )


def crowding_distances(
    front: Iterable[PopulationPoint[ValueT]],
) -> tuple[float, ...]:
    """Return normalized NSGA-II crowding distances in input order."""

    points = tuple(front)
    size = len(points)
    if size == 0:
        return ()
    distances = [0.0] * size
    objective_getters = (
        lambda point: float(point.objectives.total_cost),
        lambda point: float(point.objectives.total_emissions_kg),
    )
    for objective in objective_getters:
        order = sorted(
            range(size),
            key=lambda index: (
                objective(points[index]),
                points[index].fingerprint,
                index,
            ),
        )
        distances[order[0]] = math.inf
        distances[order[-1]] = math.inf
        lower = objective(points[order[0]])
        upper = objective(points[order[-1]])
        span = upper - lower
        if span == 0.0:
            continue
        for position in range(1, size - 1):
            index = order[position]
            previous_value = objective(points[order[position - 1]])
            next_value = objective(points[order[position + 1]])
            distances[index] += abs(next_value - previous_value) / span
    return tuple(distances)


def rank_and_crowding(
    points: Iterable[PopulationPoint[ValueT]],
) -> tuple[RankedPoint[ValueT], ...]:
    """Return rank and crowding distance for every point in input order."""

    population = tuple(points)
    ranked_by_identity: dict[int, RankedPoint[ValueT]] = {}
    for rank, front in enumerate(fast_non_dominated_sort(population)):
        distances = crowding_distances(front)
        for point, distance in zip(front, distances, strict=True):
            ranked_by_identity[id(point)] = RankedPoint(point, rank, distance)
    return tuple(ranked_by_identity[id(point)] for point in population)


def crowded_comparison_key(ranked: RankedPoint[ValueT]) -> tuple[int, float, str]:
    """Sort key for Deb's crowded comparison: low rank, then high distance."""

    return (
        int(ranked.rank),
        -float(ranked.crowding_distance),
        ranked.point.fingerprint,
    )


class BiObjectiveExternalPopulation(Generic[SolutionT, EvaluationT]):
    """Private NSGA-II population compatible with the copied HGS controller."""

    def __init__(
        self,
        diversity_op: Callable[[SolutionT, SolutionT], float],
        *,
        is_feasible: Callable[[EvaluationT], bool],
        objectives: Callable[[EvaluationT], ObjectiveValues],
        penalised_cost: Callable[[EvaluationT], float],
        fingerprint: Callable[[SolutionT], str],
        params: PopulationParams | None = None,
    ) -> None:
        self._diversity_op = diversity_op
        self._is_feasible = is_feasible
        self._objectives = objectives
        self._penalised_cost = penalised_cost
        self._fingerprint = fingerprint
        self._params = params if params is not None else PopulationParams()
        self._members: list[EvaluatedSolution[SolutionT, EvaluationT]] = []
        self._archive: dict[
            str,
            EvaluatedSolution[SolutionT, EvaluationT],
        ] = {}

    def __iter__(self):
        return iter(tuple(self._members))

    def __len__(self) -> int:
        return len(self._members)

    def clear(self) -> None:
        # HGS restarts clear the live population.  The requested Pareto archive
        # remains run-wide so a restart cannot erase an already found endpoint.
        self._members.clear()

    def add(
        self,
        candidate: EvaluatedSolution[SolutionT, EvaluationT],
    ) -> bool:
        self._update_archive(candidate)
        self._members.append(candidate)
        if len(self._members) > self._params.max_pop_size:
            self._members = self._survivors(self._params.min_pop_size)
        return any(member is candidate for member in self._members)

    def select(self, rng, k: int = 2) -> tuple[
        EvaluatedSolution[SolutionT, EvaluationT],
        EvaluatedSolution[SolutionT, EvaluationT],
    ]:
        if not self._members:
            raise ValueError("cannot select from an empty population")
        ranked = rank_and_crowding(self._population_points())
        by_candidate_identity = {id(item.point.value): item for item in ranked}
        first = self._tournament(rng, k, by_candidate_identity)
        second = self._tournament(rng, k, by_candidate_identity)
        distance = self._diversity_op(first.solution, second.solution)
        tries = 1
        while (
            not (self._params.lb_diversity <= distance <= self._params.ub_diversity)
            and tries <= 10
        ):
            second = self._tournament(rng, k, by_candidate_identity)
            distance = self._diversity_op(first.solution, second.solution)
            tries += 1
        return first, second

    def best_feasible(
        self,
    ) -> EvaluatedSolution[SolutionT, EvaluationT] | None:
        feasible = [
            candidate
            for candidate in self._members
            if self._is_feasible(candidate.evaluation)
        ]
        if not feasible:
            return None
        return min(
            feasible,
            key=lambda candidate: (
                float(self._objectives(candidate.evaluation).total_cost),
                float(self._objectives(candidate.evaluation).total_emissions_kg),
                self._fingerprint(candidate.solution),
            ),
        )

    def best_penalised(
        self,
    ) -> EvaluatedSolution[SolutionT, EvaluationT] | None:
        feasible = self.best_feasible()
        if feasible is not None:
            return feasible
        if not self._members:
            return None
        return min(
            self._members,
            key=lambda candidate: (
                float(self._penalised_cost(candidate.evaluation)),
                self._fingerprint(candidate.solution),
            ),
        )

    def archive(self) -> BiObjectiveArchive[SolutionT, EvaluationT]:
        entries = tuple(
            sorted(
                (
                    BiObjectiveArchiveEntry(
                        candidate,
                        self._objectives(candidate.evaluation),
                        self._fingerprint(candidate.solution),
                    )
                    for candidate in self._archive.values()
                ),
                key=lambda entry: (
                    float(entry.objectives.total_cost),
                    float(entry.objectives.total_emissions_kg),
                    entry.fingerprint,
                ),
            )
        )
        cost_priority = entries[0] if entries else None
        emissions_priority = (
            min(
                entries,
                key=lambda entry: (
                    float(entry.objectives.total_emissions_kg),
                    float(entry.objectives.total_cost),
                    entry.fingerprint,
                ),
            )
            if entries
            else None
        )
        return BiObjectiveArchive(entries, cost_priority, emissions_priority)

    def _population_points(
        self,
    ) -> tuple[PopulationPoint[EvaluatedSolution[SolutionT, EvaluationT]], ...]:
        return tuple(self._point(candidate) for candidate in self._members)

    def _point(
        self,
        candidate: EvaluatedSolution[SolutionT, EvaluationT],
    ) -> PopulationPoint[EvaluatedSolution[SolutionT, EvaluationT]]:
        return PopulationPoint(
            value=candidate,
            objectives=self._objectives(candidate.evaluation),
            feasible=bool(self._is_feasible(candidate.evaluation)),
            penalised_cost=float(self._penalised_cost(candidate.evaluation)),
            fingerprint=self._fingerprint(candidate.solution),
        )

    def _tournament(
        self,
        rng,
        k: int,
        ranked: dict[
            int,
            RankedPoint[EvaluatedSolution[SolutionT, EvaluationT]],
        ],
    ) -> EvaluatedSolution[SolutionT, EvaluationT]:
        if k <= 0:
            raise ValueError("tournament size must be positive")
        sampled = [
            self._members[int(rng.randint(len(self._members)))] for _draw in range(k)
        ]
        return min(
            sampled,
            key=lambda candidate: crowded_comparison_key(ranked[id(candidate)]),
        )

    def _survivors(
        self,
        target_size: int,
    ) -> list[EvaluatedSolution[SolutionT, EvaluationT]]:
        selected: list[EvaluatedSolution[SolutionT, EvaluationT]] = []
        for rank, front in enumerate(
            fast_non_dominated_sort(self._population_points())
        ):
            available = target_size - len(selected)
            if available <= 0:
                break
            if len(front) <= available:
                selected.extend(point.value for point in front)
                continue
            distances = crowding_distances(front)
            ranked_front = [
                RankedPoint(point, rank, distance)
                for point, distance in zip(front, distances, strict=True)
            ]
            ranked_front.sort(key=crowded_comparison_key)
            selected.extend(item.point.value for item in ranked_front[:available])
            break
        return selected

    def _update_archive(
        self,
        candidate: EvaluatedSolution[SolutionT, EvaluationT],
    ) -> None:
        point = self._point(candidate)
        if not point.feasible:
            return
        fingerprint = point.fingerprint
        incumbents = {
            key: value for key, value in self._archive.items() if key != fingerprint
        }
        incumbent_points = {
            key: self._point(value) for key, value in incumbents.items()
        }
        if any(dominates(incumbent, point) for incumbent in incumbent_points.values()):
            return
        self._archive = {
            key: value
            for key, value in incumbents.items()
            if not dominates(point, incumbent_points[key])
        }
        self._archive[fingerprint] = candidate


def make_private_population(
    diversity_op: Callable[[SolutionT, SolutionT], float],
    *,
    objective_mode: str,
    is_feasible: Callable[[EvaluationT], bool],
    objectives: Callable[[EvaluationT], ObjectiveValues],
    penalised_cost: Callable[[EvaluationT], float],
    fingerprint: Callable[[SolutionT], str],
    params: PopulationParams | None = None,
):
    """Return the untouched single-objective class unless explicitly enabled."""

    mode = validate_population_objective_mode(objective_mode)
    if mode == SINGLE_OBJECTIVE:
        return ExternalPopulation(
            diversity_op,
            is_feasible=is_feasible,
            penalised_cost=penalised_cost,
            fingerprint=fingerprint,
            params=params,
        )
    return BiObjectiveExternalPopulation(
        diversity_op,
        is_feasible=is_feasible,
        objectives=objectives,
        penalised_cost=penalised_cost,
        fingerprint=fingerprint,
        params=params,
    )
