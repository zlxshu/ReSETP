"""Carbon-aware charging subproblem helpers.

This module is deliberately isolated from the frozen E2 winner entrypoint.
It provides the small, auditable building blocks required by the item-4
mechanism gate before any carbon-aware route-search operator is activated.

The key distinction from the historical charging heuristic is that a charge
is scored over its complete occupancy interval.  A long charge that starts in
one green slot but spills into dirty slots is therefore not mistaken for a
green action.  Complete solution scoring remains the responsibility of the
shared evaluation shell; these helpers only solve a deterministic charging
subproblem and never consume or bypass ``EvalBudget``.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from setp_solver.cost import (
    CARBON_SLOT_SECONDS,
    best_charging_action_start,
    carbon_profile_row_for_slot,
    charging_action_emissions_kg,
    charging_slot_breakdown,
)
from setp_solver.instance_loader import Instance
from setp_solver.prices import PriceParameters
from setp_solver.solution import ChargingAction


@dataclass(frozen=True)
class ChargeTimingChoice:
    start_second: float
    carbon_kg: float
    candidates_evaluated: int


@dataclass(frozen=True)
class ChargeOption:
    station_id: str
    node_type: str
    earliest_start_second: float
    latest_start_second: float
    energy_kwh: float
    power_kw: float
    detour_m: float = 0.0
    occupancy_seconds_override: float | None = None
    start_energy_kwh: float | None = None
    end_energy_kwh: float | None = None
    charging_curve_id: str | None = None

    @property
    def occupancy_seconds(self) -> float:
        if self.occupancy_seconds_override is not None:
            if self.occupancy_seconds_override < 0.0:
                raise ValueError("charging duration must be non-negative")
            return float(self.occupancy_seconds_override)
        if self.power_kw <= 0.0:
            raise ValueError("charge power must be positive")
        if self.energy_kwh < 0.0:
            raise ValueError("charge energy must be non-negative")
        return float(self.energy_kwh) / float(self.power_kw) * 3600.0

    def action_at(self, start_second: float) -> ChargingAction:
        return ChargingAction(
            vehicle_id="CHARGE_OPTION",
            station_id=self.station_id,
            energy_kwh=float(self.energy_kwh),
            occupancy_minutes=self.occupancy_seconds / 60.0,
            charge_start_second=float(start_second),
            start_energy_kwh=self.start_energy_kwh,
            end_energy_kwh=self.end_energy_kwh,
            charging_curve_id=self.charging_curve_id,
        )

    @property
    def has_curve_metadata(self) -> bool:
        values = (
            self.occupancy_seconds_override,
            self.start_energy_kwh,
            self.end_energy_kwh,
            self.charging_curve_id,
        )
        return all(value is not None for value in values)


@dataclass(frozen=True)
class ScoredChargeOption:
    option: ChargeOption
    timing: ChargeTimingChoice
    electricity_cost: float
    occupancy_cost: float
    detour_cost: float
    carbon_cost: float
    total_incremental_cost: float


@dataclass(frozen=True)
class ChargeRequest:
    vehicle_id: str
    station_id: str
    earliest_start_second: float
    latest_start_second: float
    energy_kwh: float
    occupancy_seconds: float


@dataclass(frozen=True)
class ScheduledCharge:
    request: ChargeRequest
    start_second: float
    carbon_kg: float

    @property
    def end_second(self) -> float:
        return float(self.start_second) + float(self.request.occupancy_seconds)


def integrated_charge_carbon_kg(
    start_second: float,
    occupancy_seconds: float,
    energy_kwh: float,
    instance: Instance,
    carbon_profile: list[dict[str, object]],
) -> float:
    """Return emissions for the whole constant-power charging interval."""

    if not carbon_profile:
        raise ValueError("carbon_profile must be non-empty")
    total = 0.0
    for slot in charging_slot_breakdown(
        float(start_second),
        float(occupancy_seconds),
        float(energy_kwh),
        instance,
        n_slots=len(carbon_profile),
        cyclic=True,
    ):
        row = carbon_profile_row_for_slot(carbon_profile, slot.slot_index)
        total += float(slot.y_skt_kwh) * float(row["actual_gco2_per_kwh"]) / 1000.0
    return float(total)


def charge_start_candidates(
    earliest_start_second: float,
    latest_start_second: float,
    occupancy_seconds: float,
) -> tuple[float, ...]:
    """Enumerate all breakpoints needed for exact piecewise-constant timing.

    For uniform-power charging over a piecewise-constant carbon profile, the
    integrated objective is piecewise linear in the start time.  A minimum is
    attained at a window endpoint, a slot boundary, or a slot boundary minus
    the charge duration.  Evaluating exactly those points is therefore enough
    for the timing-only subproblem.
    """

    earliest = float(earliest_start_second)
    latest = float(latest_start_second)
    duration = float(occupancy_seconds)
    if earliest < 0.0:
        raise ValueError("earliest charging start must be non-negative")
    if latest + 1e-9 < earliest:
        raise ValueError("latest charging start precedes earliest start")
    if duration < 0.0:
        raise ValueError("charging duration must be non-negative")

    points = {earliest, latest}
    first_boundary = math.floor((earliest - duration) / CARBON_SLOT_SECONDS) - 1
    last_boundary = math.ceil((latest + duration) / CARBON_SLOT_SECONDS) + 1
    for index in range(first_boundary, last_boundary + 1):
        boundary = float(index) * CARBON_SLOT_SECONDS
        for candidate in (boundary, boundary - duration):
            if earliest - 1e-9 <= candidate <= latest + 1e-9:
                points.add(min(latest, max(earliest, candidate)))
    return tuple(sorted(round(point, 9) for point in points))


def select_integrated_carbon_start(
    earliest_start_second: float,
    latest_start_second: float,
    occupancy_seconds: float,
    energy_kwh: float,
    instance: Instance,
    carbon_profile: list[dict[str, object]],
) -> ChargeTimingChoice:
    """Choose the feasible start with minimum full-interval emissions."""

    candidates = charge_start_candidates(
        earliest_start_second,
        latest_start_second,
        occupancy_seconds,
    )
    scored = [
        (
            integrated_charge_carbon_kg(
                start,
                occupancy_seconds,
                energy_kwh,
                instance,
                carbon_profile,
            ),
            start,
        )
        for start in candidates
    ]
    carbon_kg, start = min(scored, key=lambda item: (item[0], item[1]))
    return ChargeTimingChoice(
        start_second=float(start),
        carbon_kg=float(carbon_kg),
        candidates_evaluated=len(scored),
    )


def score_charge_option(
    option: ChargeOption,
    instance: Instance,
    carbon_profile: list[dict[str, object]],
    prices: PriceParameters,
    *,
    carbon_weight: float = 1.0,
) -> ScoredChargeOption:
    """Score station and timing with the same monetary units as the model."""

    if option.has_curve_metadata:
        template = option.action_at(option.earliest_start_second)
        start = (
            float(option.earliest_start_second)
            if float(carbon_weight) <= 1e-12
            else best_charging_action_start(
                template,
                earliest_start_second=option.earliest_start_second,
                latest_start_second=option.latest_start_second,
                instance=instance,
                carbon_profile=carbon_profile,
                prices=prices,
            )
        )
        timing = ChargeTimingChoice(
            start_second=start,
            carbon_kg=charging_action_emissions_kg(
                option.action_at(start),
                instance,
                carbon_profile,
                prices,
            ),
            candidates_evaluated=-1,
        )
    elif float(carbon_weight) <= 1e-12:
        start = float(option.earliest_start_second)
        timing = ChargeTimingChoice(
            start_second=start,
            carbon_kg=integrated_charge_carbon_kg(
                start,
                option.occupancy_seconds,
                option.energy_kwh,
                instance,
                carbon_profile,
            ),
            candidates_evaluated=1,
        )
    else:
        timing = select_integrated_carbon_start(
            option.earliest_start_second,
            option.latest_start_second,
            option.occupancy_seconds,
            option.energy_kwh,
            instance,
            carbon_profile,
        )
    is_depot = option.node_type.lower() == "d"
    electricity_price = prices.depot_electricity_price if is_depot else prices.station_electricity_price
    electricity_cost = float(option.energy_kwh) * float(electricity_price)
    occupancy_cost = 0.0 if is_depot else option.occupancy_seconds / 60.0 * float(prices.occupancy_fee)
    detour_cost = float(option.detour_m) / 1000.0 * float(prices.c_km)
    carbon_cost = float(timing.carbon_kg) * float(prices.carbon_price) * float(carbon_weight)
    total = electricity_cost + occupancy_cost + detour_cost + carbon_cost
    return ScoredChargeOption(
        option=option,
        timing=timing,
        electricity_cost=electricity_cost,
        occupancy_cost=occupancy_cost,
        detour_cost=detour_cost,
        carbon_cost=carbon_cost,
        total_incremental_cost=float(total),
    )


def select_charge_option(
    options: Iterable[ChargeOption],
    instance: Instance,
    carbon_profile: list[dict[str, object]],
    prices: PriceParameters,
    *,
    carbon_weight: float = 1.0,
) -> ScoredChargeOption:
    """Choose a station and time by complete incremental model cost."""

    scored = [
        score_charge_option(
            option,
            instance,
            carbon_profile,
            prices,
            carbon_weight=carbon_weight,
        )
        for option in options
    ]
    if not scored:
        raise ValueError("at least one charge option is required")
    return min(
        scored,
        key=lambda item: (
            item.total_incremental_cost,
            item.timing.carbon_kg,
            item.option.detour_m,
            item.option.station_id,
            item.timing.start_second,
        ),
    )


def schedule_charge_requests_exact(
    requests: Iterable[ChargeRequest],
    instance: Instance,
    carbon_profile: list[dict[str, object]],
    *,
    station_capacity: dict[str, int],
    max_states: int = 100_000,
) -> tuple[ScheduledCharge, ...]:
    """Exactly schedule a small set of fixed-station charge requests.

    This branch-and-bound routine is intentionally a micro-gate oracle, not a
    large-instance production scheduler.  It proves the station-capacity and
    whole-interval carbon semantics before a scalable label scheduler is
    connected to ALNS.
    """

    pending = list(requests)
    if any(request.occupancy_seconds < 0.0 for request in pending):
        raise ValueError("charging duration must be non-negative")
    choices = {
        request: charge_start_candidates(
            request.earliest_start_second,
            request.latest_start_second,
            request.occupancy_seconds,
        )
        for request in pending
    }
    ordered = sorted(
        pending,
        key=lambda request: (
            len(choices[request]),
            request.latest_start_second - request.earliest_start_second,
            request.station_id,
            request.vehicle_id,
        ),
    )

    best_cost = math.inf
    best_schedule: tuple[ScheduledCharge, ...] | None = None
    partial: list[ScheduledCharge] = []
    states = 0

    def capacity_ok(candidate: ScheduledCharge) -> bool:
        capacity = int(station_capacity.get(candidate.request.station_id, 1))
        if capacity <= 0:
            return False
        relevant = [
            scheduled
            for scheduled in partial
            if scheduled.request.station_id == candidate.request.station_id
        ]
        boundaries = {candidate.start_second, candidate.end_second}
        for scheduled in relevant:
            boundaries.add(scheduled.start_second)
            boundaries.add(scheduled.end_second)
        ordered_bounds = sorted(boundaries)
        for left, right in zip(ordered_bounds, ordered_bounds[1:]):
            if right <= left:
                continue
            probe = (left + right) / 2.0
            active = int(candidate.start_second <= probe < candidate.end_second)
            active += sum(int(item.start_second <= probe < item.end_second) for item in relevant)
            if active > capacity:
                return False
        return True

    def visit(index: int, carbon_so_far: float) -> None:
        nonlocal best_cost, best_schedule, states
        states += 1
        if states > int(max_states):
            raise RuntimeError("exact charging micro-scheduler state limit exceeded")
        if carbon_so_far >= best_cost - 1e-12:
            return
        if index >= len(ordered):
            best_cost = float(carbon_so_far)
            best_schedule = tuple(sorted(partial, key=lambda item: (item.start_second, item.request.vehicle_id)))
            return

        request = ordered[index]
        candidates = []
        for start in choices[request]:
            carbon_kg = integrated_charge_carbon_kg(
                start,
                request.occupancy_seconds,
                request.energy_kwh,
                instance,
                carbon_profile,
            )
            candidates.append((carbon_kg, start))
        for carbon_kg, start in sorted(candidates, key=lambda item: (item[0], item[1])):
            candidate = ScheduledCharge(request=request, start_second=float(start), carbon_kg=float(carbon_kg))
            if not capacity_ok(candidate):
                continue
            partial.append(candidate)
            visit(index + 1, carbon_so_far + float(carbon_kg))
            partial.pop()

    visit(0, 0.0)
    if best_schedule is None:
        raise ValueError("no station-capacity-feasible charging schedule")
    return best_schedule
