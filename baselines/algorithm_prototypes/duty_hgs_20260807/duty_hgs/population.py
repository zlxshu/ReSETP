"""Duty-compatible HGS population, diversity, and adaptive penalties.

v1 2026-08-07: independently implement Vidal-style feasible/infeasible
subpopulations, broken-pairs diversity, biased fitness, binary-or-k tournament,
and adaptive feasibility penalties.  The design follows PyVRP 0.12.2, but no
PyVRP runtime object or compiled extension is used by the main algorithm.

v2 2026-08-07: extend the Duty diversity signature to public-station visits
and exact charging-session state, because those are search decisions here.
"""

from __future__ import annotations

import random
from collections import Counter, deque
from dataclasses import dataclass, field
from itertools import pairwise

from .evaluation import FullEvaluation
from .model import DutyChargingSession, DutyIndividual


@dataclass(frozen=True)
class PopulationParameters:
    min_pop_size: int
    generation_size: int
    num_elite: int
    num_close: int
    tournament_size: int
    lb_diversity: float
    ub_diversity: float

    def __post_init__(self) -> None:
        if self.min_pop_size < 1 or self.generation_size < 1:
            raise ValueError("population sizes must be positive")
        if not 0 <= self.num_elite < self.min_pop_size:
            raise ValueError("num_elite must be smaller than min_pop_size")
        if self.num_close < 1 or self.tournament_size < 1:
            raise ValueError("num_close and tournament_size must be positive")
        if not 0.0 <= self.lb_diversity <= self.ub_diversity <= 1.0:
            raise ValueError("diversity bounds must satisfy 0 <= lb <= ub <= 1")

    @property
    def max_pop_size(self) -> int:
        return self.min_pop_size + self.generation_size


@dataclass(frozen=True)
class PenaltyParameters:
    initial_penalty_per_unit: float
    solutions_between_updates: int
    penalty_increase: float
    penalty_decrease: float
    target_feasible: float
    feasibility_tolerance: float
    minimum_penalty: float
    maximum_penalty: float

    def __post_init__(self) -> None:
        if self.initial_penalty_per_unit < 0.0:
            raise ValueError("initial penalty must be non-negative")
        if self.solutions_between_updates < 1:
            raise ValueError("penalty update interval must be positive")
        if self.penalty_increase < 1.0:
            raise ValueError("penalty increase must be at least one")
        if not 0.0 <= self.penalty_decrease <= 1.0:
            raise ValueError("penalty decrease must be in [0, 1]")
        if not 0.0 <= self.target_feasible <= 1.0:
            raise ValueError("target feasible share must be in [0, 1]")
        if not 0.0 <= self.feasibility_tolerance <= 1.0:
            raise ValueError("feasibility tolerance must be in [0, 1]")
        if self.minimum_penalty < 0.0:
            raise ValueError("minimum penalty must be non-negative")
        if self.maximum_penalty < self.minimum_penalty:
            raise ValueError("maximum penalty must not be below minimum")


@dataclass(frozen=True)
class EvaluatedDutyCandidate:
    individual: DutyIndividual
    evaluation: FullEvaluation


@dataclass(frozen=True)
class PopulationAdmission:
    candidate: EvaluatedDutyCandidate
    inserted: bool


@dataclass
class AdaptivePenaltyManager:
    params: PenaltyParameters
    penalties: dict[str, float] = field(default_factory=dict)
    _history: dict[str, deque[bool]] = field(default_factory=dict)

    def register(self, evaluation: FullEvaluation) -> None:
        counts = Counter(violation.type for violation in evaluation.violations)
        known = set(self.penalties).union(counts)
        for violation_type in known:
            self.penalties.setdefault(
                violation_type,
                _clip(
                    self.params.initial_penalty_per_unit,
                    self.params.minimum_penalty,
                    self.params.maximum_penalty,
                ),
            )
            history = self._history.setdefault(
                violation_type,
                deque(maxlen=self.params.solutions_between_updates),
            )
            history.append(counts.get(violation_type, 0) == 0)
            if len(history) == self.params.solutions_between_updates:
                feasible_share = sum(history) / len(history)
                difference = self.params.target_feasible - feasible_share
                if abs(difference) >= self.params.feasibility_tolerance:
                    multiplier = (
                        self.params.penalty_increase
                        if difference > 0.0
                        else self.params.penalty_decrease
                    )
                    self.penalties[violation_type] = _clip(
                        self.penalties[violation_type] * multiplier,
                        self.params.minimum_penalty,
                        self.params.maximum_penalty,
                    )
                history.clear()

    def cost(self, evaluation: FullEvaluation) -> float:
        magnitude_by_type: Counter[str] = Counter()
        for violation, magnitude in zip(
            evaluation.violations,
            evaluation.violation_magnitudes,
            strict=True,
        ):
            magnitude_by_type[violation.type] += float(magnitude)
        return float(evaluation.total_cost) + sum(
            float(magnitude) * self.penalties.get(
                violation_type,
                self.params.initial_penalty_per_unit,
            )
            for violation_type, magnitude in magnitude_by_type.items()
        )


class DutyPopulation:
    """Two-subpopulation HGS store with canonical Duty diversity."""

    def __init__(
        self,
        params: PopulationParameters,
        penalty_manager: AdaptivePenaltyManager,
    ) -> None:
        self.params = params
        self.penalty_manager = penalty_manager
        self._feasible: list[EvaluatedDutyCandidate] = []
        self._infeasible: list[EvaluatedDutyCandidate] = []

    def __len__(self) -> int:
        return len(self._feasible) + len(self._infeasible)

    def clear(self) -> None:
        self._feasible.clear()
        self._infeasible.clear()

    def add(
        self,
        individual: DutyIndividual,
        evaluation: FullEvaluation,
    ) -> PopulationAdmission:
        self.penalty_manager.register(evaluation)
        candidate = EvaluatedDutyCandidate(
            individual=individual,
            evaluation=evaluation,
        )
        subpopulation = (
            self._feasible if evaluation.feasible else self._infeasible
        )
        duplicate = next(
            (
                item
                for item in subpopulation
                if item.individual.fingerprint == individual.fingerprint
            ),
            None,
        )
        if duplicate is not None:
            if self.penalty_manager.cost(
                candidate.evaluation
            ) < self.penalty_manager.cost(duplicate.evaluation):
                subpopulation.remove(duplicate)
            else:
                return PopulationAdmission(duplicate, inserted=False)
        subpopulation.append(candidate)
        if len(subpopulation) > self.params.max_pop_size:
            self._purge(subpopulation)
        return PopulationAdmission(
            candidate,
            inserted=any(item is candidate for item in subpopulation),
        )

    def select(
        self,
        rng: random.Random,
    ) -> tuple[EvaluatedDutyCandidate, EvaluatedDutyCandidate]:
        if len(self) == 0:
            raise ValueError("cannot select parents from an empty population")
        fitness = self._fitness()
        first = self._tournament(rng, fitness)
        second = self._tournament(rng, fitness)
        tries = 1
        distance = broken_pairs_distance(
            first.individual,
            second.individual,
        )
        while not (
            self.params.lb_diversity
            <= distance
            <= self.params.ub_diversity
        ) and tries <= 10:
            second = self._tournament(rng, fitness)
            distance = broken_pairs_distance(
                first.individual,
                second.individual,
            )
            tries += 1
        return first, second

    def best_feasible(self) -> EvaluatedDutyCandidate | None:
        return min(
            self._feasible,
            key=lambda item: (
                float(item.evaluation.total_cost),
                item.individual.fingerprint,
            ),
            default=None,
        )

    def best_penalized(self) -> EvaluatedDutyCandidate | None:
        return min(
            self._feasible + self._infeasible,
            key=lambda item: (
                self.penalty_manager.cost(item.evaluation),
                item.individual.fingerprint,
            ),
            default=None,
        )

    def members(self) -> tuple[EvaluatedDutyCandidate, ...]:
        return tuple(self._feasible + self._infeasible)

    def _tournament(
        self,
        rng: random.Random,
        fitness: dict[str, float],
    ) -> EvaluatedDutyCandidate:
        members = self._feasible + self._infeasible
        sampled = [
            members[rng.randrange(len(members))]
            for _ in range(self.params.tournament_size)
        ]
        return min(
            sampled,
            key=lambda item: (
                fitness[item.individual.fingerprint],
                item.individual.fingerprint,
            ),
        )

    def _fitness(self) -> dict[str, float]:
        fitness: dict[str, float] = {}
        for subpopulation in (self._feasible, self._infeasible):
            if not subpopulation:
                continue
            cost_order = sorted(
                subpopulation,
                key=lambda item: (
                    self.penalty_manager.cost(item.evaluation),
                    item.individual.fingerprint,
                ),
            )
            cost_rank = {
                item.individual.fingerprint: rank
                for rank, item in enumerate(cost_order, start=1)
            }
            diversity_order = sorted(
                subpopulation,
                key=lambda item: (
                    -_average_close_distance(
                        item,
                        subpopulation,
                        self.params.num_close,
                    ),
                    item.individual.fingerprint,
                ),
            )
            diversity_rank = {
                item.individual.fingerprint: rank
                for rank, item in enumerate(diversity_order, start=1)
            }
            diversity_weight = 1.0 - min(
                self.params.num_elite,
                len(subpopulation),
            ) / len(subpopulation)
            for item in subpopulation:
                fingerprint = item.individual.fingerprint
                fitness[fingerprint] = float(cost_rank[fingerprint]) + (
                    diversity_weight * float(diversity_rank[fingerprint])
                )
        return fitness

    def _purge(self, subpopulation: list[EvaluatedDutyCandidate]) -> None:
        while len(subpopulation) > self.params.min_pop_size:
            fitness = self._fitness()
            elite = {
                item.individual.fingerprint
                for item in sorted(
                    subpopulation,
                    key=lambda item: (
                        self.penalty_manager.cost(item.evaluation),
                        item.individual.fingerprint,
                    ),
                )[: self.params.num_elite]
            }
            removable = [
                item
                for item in subpopulation
                if item.individual.fingerprint not in elite
            ]
            if not removable:
                break
            worst = max(
                removable,
                key=lambda item: (
                    fitness[item.individual.fingerprint],
                    item.individual.fingerprint,
                ),
            )
            subpopulation.remove(worst)


def broken_pairs_distance(
    left: DutyIndividual,
    right: DutyIndividual,
) -> float:
    """Vidal broken-pairs distance with duty/trip boundaries kept explicit."""

    left_edges = _duty_edges(left)
    right_edges = _duty_edges(right)
    union = left_edges.union(right_edges)
    if not union:
        return 0.0
    return len(left_edges.symmetric_difference(right_edges)) / len(union)


def _duty_edges(individual: DutyIndividual) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for duty in individual.duties:
        for trip in duty.trips:
            start = f"START:{duty.physical_vehicle_id}#T{trip.trip_index}"
            end = f"END:{duty.physical_vehicle_id}#T{trip.trip_index}"
            sequence = (start, *trip.effective_route_visits, end)
            edges.update(pairwise(sequence))
        charging_by_trip = {
            trip.trip_index: sorted(
                (
                    session
                    for session in duty.charging_sessions
                    if session.trip_index == trip.trip_index
                ),
                key=lambda session: (
                    int(session.charge_day_offset),
                    float(session.charge_start_second),
                    session.station_id,
                    float(session.energy_kwh),
                ),
            )
            for trip in duty.trips
        }
        for trip_index, sessions in charging_by_trip.items():
            if not sessions:
                continue
            start = f"CHARGE_START:{duty.physical_vehicle_id}#T{trip_index}"
            end = f"CHARGE_END:{duty.physical_vehicle_id}#T{trip_index}"
            tokens = tuple(_charging_token(session) for session in sessions)
            sequence = (start, *tokens, end)
            edges.update(pairwise(sequence))
    return edges


def _charging_token(session: DutyChargingSession) -> str:
    def encoded(value: float | None) -> str:
        return "none" if value is None else float(value).hex()

    return ":".join(
        (
            "CHARGE",
            session.station_id,
            encoded(session.energy_kwh),
            encoded(session.occupancy_minutes),
            encoded(session.charge_start_second),
            str(int(session.charge_day_offset)),
            encoded(session.start_energy_kwh),
            encoded(session.end_energy_kwh),
            str(session.charging_curve_id),
            str(bool(session.locked)),
        )
    )


def _average_close_distance(
    candidate: EvaluatedDutyCandidate,
    population: list[EvaluatedDutyCandidate],
    num_close: int,
) -> float:
    distances = sorted(
        broken_pairs_distance(candidate.individual, other.individual)
        for other in population
        if other is not candidate
    )
    if not distances:
        return 0.0
    selected = distances[: min(num_close, len(distances))]
    return sum(selected) / len(selected)


def _clip(value: float, lower: float, upper: float) -> float:
    return min(float(upper), max(float(lower), float(value)))
