"""Duty-compatible HGS population, diversity, and adaptive penalties.

v1 2026-08-07: independently implement Vidal-style feasible/infeasible
subpopulations, broken-pairs diversity, biased fitness, binary-or-k tournament,
and adaptive feasibility penalties.  The design follows IndependentKernel 0.12.2, but no
IndependentKernel runtime object or compiled extension is used by the main algorithm.

v2 2026-08-07: extend the Duty diversity signature to public-station visits.
v3 2026-08-09: keep HGS diversity on route adjacency only. Charging times and
amounts are completion state, not extra route genes.

v4 2026-08-09: match the copied HGS 0.12.2 SubPopulation survivor semantics:
admit duplicate solutions during normal growth and remove duplicates first only
when an oversized subpopulation is purged. Duty evaluation remains local.

v5 2026-08-10: make each adjacency token a complete discrete Duty assignment:
vehicle type, home depot, trip index, and (only for committed duties) physical
asset identity travel with the predecessor/successor pair.  This remains one
Vidal-style distance rather than several weighted diversity views.  Continuous
charging completion is intentionally left to full cost and exact fingerprints.
"""

from __future__ import annotations

import random
from collections import Counter, deque
from dataclasses import dataclass, field
from setp_hgs_kernel import PopulationParams as KernelPopulationParams

from .evaluation import FullEvaluation
from .model import DutyIndividual


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

    @classmethod
    def copied_hgs_defaults(cls) -> PopulationParameters:
        """Return the unmodified population and tournament defaults of HGS 0.12.2."""

        copied = KernelPopulationParams()
        return cls(
            min_pop_size=int(copied.min_pop_size),
            generation_size=int(copied.generation_size),
            num_elite=int(copied.num_elite),
            num_close=int(copied.num_close),
            tournament_size=2,
            lb_diversity=float(copied.lb_diversity),
            ub_diversity=float(copied.ub_diversity),
        )


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
    initial_penalty_by_type: tuple[tuple[str, float], ...] = ()

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
        keys = [str(key) for key, _value in self.initial_penalty_by_type]
        if len(keys) != len(set(keys)):
            raise ValueError("initial penalty types must be unique")
        if any(
            not str(key) or float(value) < 0.0
            for key, value in self.initial_penalty_by_type
        ):
            raise ValueError("typed initial penalties must be named and non-negative")


@dataclass(frozen=True)
class EvaluatedDutyCandidate:
    individual: DutyIndividual
    evaluation: FullEvaluation
    fingerprint: str = field(init=False)
    diversity_neighbours: tuple[tuple[str, str, str], ...] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "fingerprint", self.individual.fingerprint)
        object.__setattr__(
            self,
            "diversity_neighbours",
            _duty_neighbours(self.individual),
        )


@dataclass(frozen=True)
class PopulationAdmission:
    candidate: EvaluatedDutyCandidate
    inserted: bool


@dataclass
class AdaptivePenaltyManager:
    params: PenaltyParameters
    penalties: dict[str, float] = field(default_factory=dict)
    _history: dict[str, deque[bool]] = field(default_factory=dict)
    registration_counts: Counter[str] = field(default_factory=Counter)
    update_counts: Counter[str] = field(default_factory=Counter)
    coefficient_change_counts: Counter[str] = field(default_factory=Counter)
    update_feasible_shares: dict[str, list[float]] = field(
        default_factory=dict
    )
    penalty_trajectories: dict[str, list[float]] = field(default_factory=dict)

    def _initial_penalty(self, violation_type: str) -> float:
        configured = dict(self.params.initial_penalty_by_type)
        return float(
            configured.get(
                violation_type,
                self.params.initial_penalty_per_unit,
            )
        )

    def register(self, evaluation: FullEvaluation) -> None:
        counts = Counter(violation.type for violation in evaluation.violations)
        known = set(self.penalties).union(counts)
        for violation_type in known:
            self.penalties.setdefault(
                violation_type,
                _clip(
                    self._initial_penalty(violation_type),
                    self.params.minimum_penalty,
                    self.params.maximum_penalty,
                ),
            )
            self.penalty_trajectories.setdefault(
                violation_type,
                [float(self.penalties[violation_type])],
            )
            self.registration_counts[violation_type] += 1
            history = self._history.setdefault(
                violation_type,
                deque(maxlen=self.params.solutions_between_updates),
            )
            history.append(counts.get(violation_type, 0) == 0)
            if len(history) == self.params.solutions_between_updates:
                feasible_share = sum(history) / len(history)
                self.update_counts[violation_type] += 1
                self.update_feasible_shares.setdefault(
                    violation_type,
                    [],
                ).append(float(feasible_share))
                difference = self.params.target_feasible - feasible_share
                before = float(self.penalties[violation_type])
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
                after = float(self.penalties[violation_type])
                self.penalty_trajectories[violation_type].append(after)
                if after != before:
                    self.coefficient_change_counts[violation_type] += 1
                history.clear()

    def telemetry(self) -> dict[str, object]:
        """Return read-only evidence about typed penalty-window activity."""

        types = sorted(
            set(self.registration_counts)
            | set(self.penalties)
            | set(self.update_counts)
        )
        return {
            "solutions_between_updates": int(
                self.params.solutions_between_updates
            ),
            "by_violation_type": {
                violation_type: {
                    "registration_count": int(
                        self.registration_counts.get(violation_type, 0)
                    ),
                    "update_count": int(
                        self.update_counts.get(violation_type, 0)
                    ),
                    "coefficient_change_count": int(
                        self.coefficient_change_counts.get(
                            violation_type,
                            0,
                        )
                    ),
                    "update_feasible_shares": [
                        float(value)
                        for value in self.update_feasible_shares.get(
                            violation_type,
                            [],
                        )
                    ],
                    "penalty_trajectory": [
                        float(value)
                        for value in self.penalty_trajectories.get(
                            violation_type,
                            [],
                        )
                    ],
                    "penalty_start": (
                        None
                        if not self.penalty_trajectories.get(
                            violation_type,
                            [],
                        )
                        else float(
                            self.penalty_trajectories[violation_type][0]
                        )
                    ),
                    "penalty_end": (
                        None
                        if not self.penalty_trajectories.get(
                            violation_type,
                            [],
                        )
                        else float(
                            self.penalty_trajectories[violation_type][-1]
                        )
                    ),
                }
                for violation_type in types
            },
        }

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
                self._initial_penalty(violation_type),
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
        candidate = EvaluatedDutyCandidate(
            individual=individual,
            evaluation=evaluation,
        )
        subpopulation = (
            self._feasible if evaluation.feasible else self._infeasible
        )
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
        distance_cache: dict[tuple[str, str], float] = {}
        distance = _candidate_distance(first, second, distance_cache)
        while not (
            self.params.lb_diversity
            <= distance
            <= self.params.ub_diversity
        ) and tries <= 10:
            second = self._tournament(rng, fitness)
            distance = _candidate_distance(first, second, distance_cache)
            tries += 1
        return first, second

    def best_feasible(self) -> EvaluatedDutyCandidate | None:
        return min(
            self._feasible,
            key=lambda item: (
                float(item.evaluation.total_cost),
                item.fingerprint,
            ),
            default=None,
        )

    def best_penalized(self) -> EvaluatedDutyCandidate | None:
        return min(
            self._feasible + self._infeasible,
            key=lambda item: (
                self.penalty_manager.cost(item.evaluation),
                item.fingerprint,
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
                fitness[item.fingerprint],
                item.fingerprint,
            ),
        )

    def _fitness(
        self,
        distance_cache: dict[tuple[str, str], float] | None = None,
    ) -> dict[str, float]:
        distances = {} if distance_cache is None else distance_cache
        fitness: dict[str, float] = {}
        for subpopulation in (self._feasible, self._infeasible):
            if not subpopulation:
                continue
            cost_order = sorted(
                subpopulation,
                key=lambda item: (
                    self.penalty_manager.cost(item.evaluation),
                    item.fingerprint,
                ),
            )
            cost_rank = {
                item.fingerprint: rank
                for rank, item in enumerate(cost_order, start=1)
            }
            diversity_order = sorted(
                subpopulation,
                key=lambda item: (
                    -_average_close_distance(
                        item,
                        subpopulation,
                        self.params.num_close,
                        distances,
                    ),
                    item.fingerprint,
                ),
            )
            diversity_rank = {
                item.fingerprint: rank
                for rank, item in enumerate(diversity_order, start=1)
            }
            diversity_weight = 1.0 - min(
                self.params.num_elite,
                len(subpopulation),
            ) / len(subpopulation)
            for item in subpopulation:
                identity = item.fingerprint
                fitness[identity] = float(cost_rank[identity]) + (
                    diversity_weight * float(diversity_rank[identity])
                )
        return fitness

    def _purge(self, subpopulation: list[EvaluatedDutyCandidate]) -> None:
        distance_cache: dict[tuple[str, str], float] = {}
        # Copied HGS 0.12.2 removes duplicates before biased-fitness survivor
        # selection, but only after the subpopulation has exceeded max size.
        while len(subpopulation) > self.params.min_pop_size:
            duplicate_index = next(
                (
                    index
                    for index, item in enumerate(subpopulation)
                    if any(
                        other_index != index
                        and other.fingerprint == item.fingerprint
                        for other_index, other in enumerate(subpopulation)
                    )
                ),
                None,
            )
            if duplicate_index is None:
                break
            subpopulation.pop(duplicate_index)
        while len(subpopulation) > self.params.min_pop_size:
            fitness = self._fitness(distance_cache)
            elite = {
                item.fingerprint
                for item in sorted(
                    subpopulation,
                    key=lambda item: (
                        self.penalty_manager.cost(item.evaluation),
                        item.fingerprint,
                    ),
                )[: self.params.num_elite]
            }
            removable = [
                item
                for item in subpopulation
                if item.fingerprint not in elite
            ]
            if not removable:
                break
            worst = max(
                removable,
                key=lambda item: (
                    fitness[item.fingerprint],
                    item.fingerprint,
                ),
            )
            subpopulation.remove(worst)


def broken_pairs_distance(
    left: DutyIndividual,
    right: DutyIndividual,
) -> float:
    """Vidal broken-pairs distance over one complete discrete Duty assignment."""

    return _neighbour_distance(
        _duty_neighbours(left),
        _duty_neighbours(right),
    )


def _neighbour_distance(
    left_signature: tuple[tuple[str, str, str], ...],
    right_signature: tuple[tuple[str, str, str], ...],
) -> float:
    left = {location: (pred, succ) for location, pred, succ in left_signature}
    right = {
        location: (pred, succ) for location, pred, succ in right_signature
    }
    locations = set(left).union(right)
    if not locations:
        return 0.0
    unassigned = ("UNASSIGNED", "UNASSIGNED")
    broken = sum(
        int(left.get(location, unassigned)[0] != right.get(location, unassigned)[0])
        + int(
            left.get(location, unassigned)[1]
            != right.get(location, unassigned)[1]
        )
        for location in locations
    )
    return broken / (2.0 * len(locations))


def _duty_neighbours(
    individual: DutyIndividual,
) -> tuple[tuple[str, str, str], ...]:
    neighbours: dict[str, tuple[str, str]] = {}
    depots: set[str] = set()
    for duty in individual.duties:
        depot = f"DEPOT:{duty.home_depot_id}"
        depots.add(depot)
        committed = bool(
            duty.has_dynamic_commitment
            or duty.locked_charging_trip_indices
            or any(trip.locked_customer_prefix for trip in duty.trips)
        )
        asset = (
            duty.physical_vehicle_id if committed else "INTERCHANGEABLE"
        )
        for trip in duty.trips:
            assignment = (
                f"TYPE:{duty.vehicle_type}|DEPOT:{duty.home_depot_id}|"
                f"TRIP:{trip.trip_index}|ASSET:{asset}"
            )
            visits = trip.effective_route_visits
            positions = {node_id: index for index, node_id in enumerate(visits)}
            for customer in trip.customer_ids:
                index = positions[customer]
                predecessor_node = (
                    depot if index == 0 else f"NODE:{visits[index - 1]}"
                )
                predecessor = f"{assignment}|{predecessor_node}"
                successor = (
                    f"{assignment}|{depot}"
                    if index == len(visits) - 1
                    else f"{assignment}|NODE:{visits[index + 1]}"
                )
                neighbours[f"CUSTOMER:{customer}"] = (
                    predecessor,
                    successor,
                )
    for depot in depots:
        neighbours[depot] = (depot, depot)
    return tuple(
        (location, predecessor, successor)
        for location, (predecessor, successor) in sorted(neighbours.items())
    )


def _average_close_distance(
    candidate: EvaluatedDutyCandidate,
    population: list[EvaluatedDutyCandidate],
    num_close: int,
    distance_cache: dict[tuple[str, str], float] | None = None,
) -> float:
    cache = {} if distance_cache is None else distance_cache
    distances = sorted(
        _candidate_distance(candidate, other, cache)
        for other in population
        if other is not candidate
    )
    if not distances:
        return 0.0
    selected = distances[: min(num_close, len(distances))]
    return sum(selected) / len(selected)


def _candidate_distance(
    left: EvaluatedDutyCandidate,
    right: EvaluatedDutyCandidate,
    cache: dict[tuple[str, str], float],
) -> float:
    key = tuple(sorted((left.fingerprint, right.fingerprint)))
    if key not in cache:
        cache[key] = _neighbour_distance(
            left.diversity_neighbours,
            right.diversity_neighbours,
        )
    return cache[key]


def _clip(value: float, lower: float, upper: float) -> float:
    return min(float(upper), max(float(lower), float(value)))
