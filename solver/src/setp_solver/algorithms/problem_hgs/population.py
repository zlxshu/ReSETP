"""Copied HGS parameters, Duty diversity, and population-scaled penalties."""

from __future__ import annotations

from dataclasses import dataclass, field
from numpy import errstate, exp
from setp_hgs_kernel import PopulationParams as KernelPopulationParams

from .evaluation import CONSTRAINT_AXES, FullEvaluation
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
class EvaluatedDutyCandidate:
    individual: DutyIndividual
    evaluation: FullEvaluation
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fingerprint", self.individual.fingerprint)


@dataclass
class SelfAdaptivePenalty:
    """Mechanical port of pagmo2 ``detail::penalized_udp``.

    Copyright 2017-2021 PaGMO development team, LGPL-3.0-or-later.
    Source: ``third_party/harvested_materials/09_constraint_handling/``
    ``pagmo2_v2_19_1/upstream/src/algorithms/cstrs_self_adaptive.cpp``.
    """

    minimum_reference_size = 4
    revision: int = field(init=False, default=0)
    c_max: tuple[float, ...] = field(init=False, default=())
    scaling_factor: float = field(init=False, default=0.0)
    i_hat_up: float = field(init=False, default=0.0)
    i_hat_down: float = field(init=False, default=0.0)
    apply_penalty_1: bool = field(init=False, default=False)
    f_hat_up: float = field(init=False, default=0.0)
    f_hat_down: float = field(init=False, default=0.0)

    def update(self, population: tuple[FullEvaluation, ...]) -> None:
        if len(population) < self.minimum_reference_size:
            raise ValueError("self-adaptive penalty requires at least four solutions")
        vectors = tuple(constraint_vector(item) for item in population)
        objectives = tuple(float(item.total_cost) for item in population)
        self.c_max = tuple(max(vector[idx] for vector in vectors) for idx in range(len(CONSTRAINT_AXES)))
        infeasibility = tuple(self._infeasibility(vector) for vector in vectors)
        feasible = [idx for idx, value in enumerate(infeasibility) if value <= 0.0]
        infeasible = [idx for idx, value in enumerate(infeasibility) if value > 0.0]
        self.apply_penalty_1 = False
        if len(feasible) == len(population):
            self.scaling_factor = self.i_hat_up = self.i_hat_down = 0.0
            self.f_hat_up = self.f_hat_down = objectives[0]
            self.revision += 1
            return

        if feasible:
            down = feasible[0]
            for idx in feasible[1:]:
                if objectives[idx] < objectives[down]:
                    down = idx
            better = [idx for idx in infeasible if objectives[idx] < objectives[down]]
            if better:
                up = better[0]
                for idx in infeasible:
                    if (
                        objectives[idx] < objectives[down]
                        and infeasibility[idx] >= infeasibility[up]
                    ):
                        if infeasibility[idx] > infeasibility[up] or (
                            objectives[idx] < objectives[up]
                        ):
                            up = idx
                self.apply_penalty_1 = True
            else:
                up = infeasible[0]
                for idx in infeasible[1:]:
                    if infeasibility[idx] >= infeasibility[up]:
                        if infeasibility[idx] > infeasibility[up] or (
                            objectives[idx] > objectives[up]
                        ):
                            up = idx
        else:
            down = up = 0
            for idx in range(1, len(population)):
                if infeasibility[idx] < infeasibility[down] or (
                    infeasibility[idx] == infeasibility[down]
                    and objectives[idx] < objectives[down]
                ):
                    down = idx
                if infeasibility[idx] > infeasibility[up] or (
                    infeasibility[idx] == infeasibility[up]
                    and objectives[idx] > objectives[up]
                ):
                    up = idx
            self.apply_penalty_1 = True

        round_idx = max(range(len(population)), key=objectives.__getitem__)
        self.f_hat_down, self.f_hat_up = objectives[down], objectives[up]
        self.i_hat_down, self.i_hat_up = infeasibility[down], infeasibility[up]
        f_round = objectives[round_idx]
        denominator = (
            self.f_hat_down
            if self.f_hat_up <= self.f_hat_down
            else self.f_hat_up
        )
        # An idle reference (no vehicle used) has objective 0; the kernel-
        # native search seeds from it under fleet overrides (2026-09-03).
        self.scaling_factor = (
            (f_round - denominator) / denominator if denominator != 0.0 else 0.0
        )
        if self.f_hat_up == f_round:
            self.scaling_factor = 0.0
        self.revision += 1

    def cost(self, evaluation: FullEvaluation) -> float:
        objective = float(evaluation.total_cost)
        vector = constraint_vector(evaluation)
        if not any(vector):
            return objective
        infeasibility = self._infeasibility(vector)
        scaled = infeasibility
        if self.i_hat_up != self.i_hat_down:
            scaled = (infeasibility - self.i_hat_down) / (self.i_hat_up - self.i_hat_down)
        if self.apply_penalty_1:
            objective += scaled * (self.f_hat_down - self.f_hat_up)
        with errstate(over="ignore"):
            return float(objective + self.scaling_factor * abs(objective) * (
                (exp(2.0 * scaled) - 1.0) / (exp(2.0) - 1.0)
            ))

    def _infeasibility(self, vector: tuple[float, ...]) -> float:
        infeasibility = 0.0
        for value, maximum in zip(vector, self.c_max, strict=True):
            if maximum > 0.0:
                infeasibility += value / maximum
        return infeasibility / len(CONSTRAINT_AXES)


def constraint_vector(evaluation: FullEvaluation) -> tuple[float, ...]:
    """Map native-unit violation axes to pagmo2's fixed inequality vector."""

    vector = [0.0] * len(CONSTRAINT_AXES)
    for axis, magnitude in zip(
        evaluation.violation_axes,
        evaluation.violation_magnitudes,
        strict=True,
    ):
        vector[CONSTRAINT_AXES.index(axis)] += max(0.0, float(magnitude))
    return tuple(vector)


_NEIGHBOUR_SIGNATURE_CACHE_MAX_ENTRIES = 2048
_neighbour_signature_cache: dict[str, tuple[tuple[str, str, str], ...]] = {}


def _cached_duty_neighbours(
    individual: DutyIndividual,
) -> tuple[tuple[str, str, str], ...]:
    """Memoise the neighbour signature by fingerprint.

    ``ExternalPopulation.add`` compares the newcomer with every member, so the
    same individual's signature was rebuilt dozens of times per iteration
    (2026-09-02).  The signature is a pure function of the individual.
    """

    key = individual.fingerprint
    cached = _neighbour_signature_cache.get(key)
    if cached is None:
        if len(_neighbour_signature_cache) >= _NEIGHBOUR_SIGNATURE_CACHE_MAX_ENTRIES:
            _neighbour_signature_cache.clear()
        cached = _duty_neighbours(individual)
        _neighbour_signature_cache[key] = cached
    return cached


def broken_pairs_distance(
    left: DutyIndividual,
    right: DutyIndividual,
) -> float:
    """Vidal broken-pairs distance over one complete discrete Duty assignment."""

    return _neighbour_distance(
        _cached_duty_neighbours(left),
        _cached_duty_neighbours(right),
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
