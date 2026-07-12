"""Versioned physical-vehicle scheduling contract for new E3--E7 evidence.

This module is deliberately additive.  It does not alter the legacy route-level
checker used by frozen E1/E2 artifacts.  E3_STRICT_MULTITRIP_V1 treats every
Route as one trip and assigns non-overlapping trips to real vehicles.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import heapq
from typing import Any

from ..cost import _arc_loads, ev_arc_energy_kwh, _price
from ..instance_loader import Instance
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import Route


CONTRACT_ID = "E3_STRICT_MULTITRIP_V1"
CHARGE_MODE_FULL = "full"
CHARGE_MODE_PARTIAL = "partial"
_TOL = 1e-6


@dataclass(frozen=True)
class TripTiming:
    route_id: str
    vehicle_type: str
    home_depot_id: str
    earliest_departure_second: float
    return_second: float
    drive_energy_kwh: float


@dataclass(frozen=True)
class ScheduledTrip:
    route_id: str
    physical_vehicle_id: str
    trip_index: int
    vehicle_type: str
    home_depot_id: str
    departure_second: float
    return_second: float
    recharge_end_second: float
    start_battery_kwh: float | None
    end_battery_kwh: float | None
    charge_start_second: float | None = None
    charge_energy_kwh: float | None = None


@dataclass(frozen=True)
class MultiTripCertificate:
    contract_id: str
    status: str
    vehicle_counts: dict[str, int]
    trips: tuple[ScheduledTrip, ...]
    recharge_mode: str
    depot_charge_power_kw: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def route_timing(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> TripTiming:
    """Compute one legal route-to-trip interval without changing route schema.

    The frozen route representation has no departure-time field.  We therefore
    choose a feasible clock that removes avoidable customer waiting.  This is
    deliberately one reproducible witness clock, not a proof that no other
    clock could make a fixed route set use fewer physical vehicles.
    """

    if len(route.node_sequence) < 2:
        raise ValueError(f"{CONTRACT_ID}: route {route.vehicle_id} has no trip")
    if route.node_sequence[0] != route.home_depot_id or route.node_sequence[-1] != route.home_depot_id:
        raise ValueError(f"{CONTRACT_ID}: route {route.vehicle_id} does not return to its home depot")
    nodes = {node.node_id: node for node in instance.nodes}
    if any(node_id not in nodes for node_id in route.node_sequence):
        raise ValueError(f"{CONTRACT_ID}: route {route.vehicle_id} references an unknown node")
    if any(nodes[node_id].node_type.lower() == "f" for node_id in route.node_sequence):
        raise ValueError(f"{CONTRACT_ID}: public-station trips are unsupported by the V1 structural gate")

    origin = nodes[route.home_depot_id]
    # A trip has no departure field in the frozen Route schema.  Start it as
    # late as needed to remove avoidable depot waiting, while retaining the
    # same customer order.  This is one legal schedule, not an optimization
    # over every possible departure time.
    elapsed = float(origin.service_time)
    departure_candidates = [float(origin.ready_time) + float(origin.service_time)]
    for from_id, to_id in zip(route.node_sequence, route.node_sequence[1:]):
        elapsed += instance.distance(from_id, to_id) / _price(prices, "v_speed_ms")
        node = nodes[to_id]
        departure_candidates.append(float(node.ready_time) - elapsed)
        elapsed += float(node.service_time)
    depart = max(departure_candidates)
    earliest_departure = depart
    loads = _arc_loads(route.node_sequence, nodes)
    energy = 0.0
    for idx, (from_id, to_id) in enumerate(zip(route.node_sequence, route.node_sequence[1:])):
        distance = instance.distance(from_id, to_id)
        arrive = depart + distance / _price(prices, "v_speed_ms")
        node = nodes[to_id]
        start = max(arrive, float(node.ready_time))
        if start > float(node.due_time) + 1e-6:
            raise ValueError(f"{CONTRACT_ID}: route {route.vehicle_id} misses {to_id}'s time window")
        depart = start + float(node.service_time)
        if route.vehicle_type.lower() == "ev":
            energy += ev_arc_energy_kwh(distance, loads[idx], prices)
    battery = _price(prices, "B_battery_kwh")
    if route.vehicle_type.lower() == "ev" and energy > battery + 1e-6:
        raise ValueError(f"{CONTRACT_ID}: route {route.vehicle_id} exceeds one full battery")
    return TripTiming(route.vehicle_id, route.vehicle_type.lower(), route.home_depot_id, earliest_departure, depart, energy)


def build_multitrip_certificate(
    routes: list[Route],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    recharge_mode: str = CHARGE_MODE_FULL,
) -> MultiTripCertificate:
    """Build a reproducible physical-vehicle schedule for one fixed route set.

    This is a *feasibility witness*, not a proof of the minimum vehicle count.
    It deliberately reads depot charging power from the same ``prices`` object
    used by the route checker.  ``full`` preserves the approved V1 contract:
    return, replenish the energy used on that trip, then depart full.  ``partial``
    is an evidence-only paper-model diagnostic: battery state is carried across
    trips and only the energy available in the intervening depot window is added.
    It is not a change to the formal E3 contract unless the user later approves it.
    """

    if recharge_mode not in {CHARGE_MODE_FULL, CHARGE_MODE_PARTIAL}:
        raise ValueError(f"unknown recharge_mode={recharge_mode!r}")
    depot_charge_power_kw = _price(prices, "depot_charge_power_kw")
    if depot_charge_power_kw <= 0:
        raise ValueError("depot_charge_power_kw must be positive")
    timings = [route_timing(route, instance, prices) for route in routes]
    scheduled: list[ScheduledTrip] = []
    counts = {"cv": 0, "ev": 0}
    for (depot, vehicle_type) in sorted({(t.home_depot_id, t.vehicle_type) for t in timings}):
        group = sorted(
            (t for t in timings if t.home_depot_id == depot and t.vehicle_type == vehicle_type),
            key=lambda t: (t.earliest_departure_second, t.return_second, t.route_id),
        )
        if vehicle_type == "cv":
            group_trips, group_count = _schedule_cv_group(group, depot)
        else:
            group_trips, group_count = _schedule_ev_group(
                group,
                depot,
                battery_kwh=_price(prices, "B_battery_kwh"),
                depot_charge_power_kw=depot_charge_power_kw,
                recharge_mode=recharge_mode,
            )
        scheduled.extend(group_trips)
        counts[vehicle_type] += group_count
    certificate = MultiTripCertificate(
        CONTRACT_ID,
        "PASS",
        counts,
        tuple(sorted(scheduled, key=lambda x: x.route_id)),
        recharge_mode,
        depot_charge_power_kw,
    )
    validate_multitrip_certificate(certificate, routes, prices)
    return certificate


@dataclass
class _EVVehicleState:
    local_id: int
    trip_index: int
    available_second: float
    battery_kwh: float
    previous_route_id: str | None


def _schedule_cv_group(group: list[TripTiming], depot: str) -> tuple[list[ScheduledTrip], int]:
    available: list[tuple[float, int, int]] = []
    next_local_id = 0
    scheduled: list[ScheduledTrip] = []
    for timing in group:
        if available and available[0][0] <= timing.earliest_departure_second + _TOL:
            _, local_id, trip_index = heapq.heappop(available)
            trip_index += 1
        else:
            next_local_id += 1
            local_id, trip_index = next_local_id, 1
        physical_id = f"CV_{depot}_{local_id}"
        heapq.heappush(available, (timing.return_second, local_id, trip_index))
        scheduled.append(ScheduledTrip(
            timing.route_id, physical_id, trip_index, "cv", depot,
            timing.earliest_departure_second, timing.return_second, timing.return_second,
            None, None,
        ))
    return scheduled, next_local_id


def _schedule_ev_group(
    group: list[TripTiming],
    depot: str,
    *,
    battery_kwh: float,
    depot_charge_power_kw: float,
    recharge_mode: str,
) -> tuple[list[ScheduledTrip], int]:
    """Greedily build one valid EV schedule, retaining the actual battery path."""

    states: list[_EVVehicleState] = []
    scheduled: dict[str, ScheduledTrip] = {}
    next_local_id = 0
    for timing in group:
        candidates: list[tuple[float, float, _EVVehicleState, float]] = []
        for state in states:
            gap_seconds = timing.earliest_departure_second - state.available_second
            if gap_seconds < -_TOL:
                continue
            if recharge_mode == CHARGE_MODE_FULL:
                # Under the V1 contract the previous trip was replenished to
                # full before the vehicle became available again.
                departure_battery = battery_kwh
                charge_energy = 0.0
            else:
                charge_energy = min(
                    battery_kwh - state.battery_kwh,
                    max(0.0, gap_seconds) * depot_charge_power_kw / 3600.0,
                )
                departure_battery = state.battery_kwh + charge_energy
            if departure_battery + _TOL < timing.drive_energy_kwh:
                continue
            candidates.append((departure_battery, -state.available_second, state, charge_energy))
        if candidates:
            _, _, state, charge_energy = max(candidates, key=lambda item: (item[0], item[1], -item[2].local_id))
            if recharge_mode == CHARGE_MODE_PARTIAL and state.previous_route_id is not None:
                previous = scheduled[state.previous_route_id]
                charge_seconds = charge_energy / depot_charge_power_kw * 3600.0
                scheduled[state.previous_route_id] = replace(
                    previous,
                    recharge_end_second=previous.return_second + charge_seconds,
                    charge_start_second=previous.return_second,
                    charge_energy_kwh=charge_energy,
                )
            state.trip_index += 1
            start_battery = battery_kwh if recharge_mode == CHARGE_MODE_FULL else state.battery_kwh + charge_energy
        else:
            next_local_id += 1
            state = _EVVehicleState(next_local_id, 1, timing.earliest_departure_second, battery_kwh, None)
            start_battery = battery_kwh
        end_battery = start_battery - timing.drive_energy_kwh
        physical_id = f"EV_{depot}_{state.local_id}"
        charge_energy_after = timing.drive_energy_kwh if recharge_mode == CHARGE_MODE_FULL else 0.0
        charge_seconds_after = charge_energy_after / depot_charge_power_kw * 3600.0
        scheduled[timing.route_id] = ScheduledTrip(
            timing.route_id,
            physical_id,
            state.trip_index,
            "ev",
            depot,
            timing.earliest_departure_second,
            timing.return_second,
            timing.return_second + charge_seconds_after,
            start_battery,
            end_battery,
            timing.return_second if charge_energy_after > _TOL else None,
            charge_energy_after if charge_energy_after > _TOL else None,
        )
        state.available_second = timing.return_second + charge_seconds_after if recharge_mode == CHARGE_MODE_FULL else timing.return_second
        state.battery_kwh = battery_kwh if recharge_mode == CHARGE_MODE_FULL else end_battery
        state.previous_route_id = timing.route_id
        if state not in states:
            states.append(state)
    return list(scheduled.values()), next_local_id


def validate_multitrip_certificate(
    certificate: MultiTripCertificate,
    routes: list[Route],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> None:
    if certificate.contract_id != CONTRACT_ID:
        raise ValueError("unknown multi-trip contract")
    if certificate.recharge_mode not in {CHARGE_MODE_FULL, CHARGE_MODE_PARTIAL}:
        raise ValueError(f"{CONTRACT_ID}: unknown recharge mode")
    expected_power_kw = _price(prices, "depot_charge_power_kw")
    if certificate.depot_charge_power_kw <= _TOL:
        raise ValueError(f"{CONTRACT_ID}: depot charge power must be positive")
    if abs(certificate.depot_charge_power_kw - expected_power_kw) > _TOL:
        raise ValueError(f"{CONTRACT_ID}: certificate depot charge power disagrees with prices")
    if len(certificate.trips) != len(routes) or {trip.route_id for trip in certificate.trips} != {route.vehicle_id for route in routes}:
        raise ValueError(f"{CONTRACT_ID}: certificate does not cover every route exactly once")
    by_vehicle: dict[str, list[ScheduledTrip]] = {}
    for trip in certificate.trips:
        by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)
    for vehicle_id, trips in by_vehicle.items():
        ordered = sorted(trips, key=lambda trip: trip.trip_index)
        if [trip.trip_index for trip in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError(f"{CONTRACT_ID}: {vehicle_id} has a broken trip sequence")
        if len({(trip.home_depot_id, trip.vehicle_type) for trip in ordered}) != 1:
            raise ValueError(f"{CONTRACT_ID}: {vehicle_id} changes depot or vehicle type")
        for previous, current in zip(ordered, ordered[1:]):
            if current.departure_second + 1e-6 < previous.recharge_end_second:
                raise ValueError(f"{CONTRACT_ID}: {vehicle_id} has overlap or incomplete recharge")
            if current.vehicle_type == "ev":
                if certificate.recharge_mode == CHARGE_MODE_FULL:
                    if abs(float(current.start_battery_kwh or 0.0) - _price(prices, "B_battery_kwh")) > _TOL:
                        raise ValueError(f"{CONTRACT_ID}: {vehicle_id} does not depart full")
                elif abs(float(current.start_battery_kwh or 0.0) - (float(previous.end_battery_kwh or 0.0) + float(previous.charge_energy_kwh or 0.0))) > _TOL:
                    raise ValueError(f"{CONTRACT_ID}: {vehicle_id} battery ledger is discontinuous")
        if ordered and ordered[0].vehicle_type == "ev":
            if abs(float(ordered[0].start_battery_kwh or 0.0) - _price(prices, "B_battery_kwh")) > _TOL:
                raise ValueError(f"{CONTRACT_ID}: {vehicle_id} first trip does not depart full")
        for trip in ordered:
            if trip.vehicle_type != "ev":
                continue
            battery_kwh = _price(prices, "B_battery_kwh")
            start_battery = float(trip.start_battery_kwh or 0.0)
            if float(trip.end_battery_kwh or 0.0) < -_TOL:
                raise ValueError(f"{CONTRACT_ID}: {vehicle_id} has negative battery")
            if start_battery > battery_kwh + _TOL:
                raise ValueError(f"{CONTRACT_ID}: {vehicle_id} exceeds battery capacity at departure")
            energy = float(trip.charge_energy_kwh or 0.0)
            if certificate.recharge_mode == CHARGE_MODE_FULL:
                needed = battery_kwh - float(trip.end_battery_kwh or 0.0)
                if abs(energy - needed) > _TOL:
                    raise ValueError(f"{CONTRACT_ID}: {vehicle_id} full recharge does not replenish used energy")
            elif float(trip.end_battery_kwh or 0.0) + energy > battery_kwh + _TOL:
                raise ValueError(f"{CONTRACT_ID}: {vehicle_id} partial recharge exceeds battery capacity")
            if energy > _TOL:
                if trip.charge_start_second is None:
                    raise ValueError(f"{CONTRACT_ID}: {vehicle_id} charge has no start time")
                expected_end = float(trip.charge_start_second) + energy / certificate.depot_charge_power_kw * 3600.0
                if abs(expected_end - trip.recharge_end_second) > _TOL:
                    raise ValueError(f"{CONTRACT_ID}: {vehicle_id} charge duration disagrees with depot power")


def strict_multitrip_violations(
    routes: list[Route],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    recharge_mode: str = CHARGE_MODE_FULL,
) -> list[str]:
    """Return new-contract failures without changing the legacy checker."""

    try:
        certificate = build_multitrip_certificate(routes, instance, prices, recharge_mode=recharge_mode)
    except ValueError as exc:
        return [str(exc)]
    failures: list[str] = []
    if instance.num_cv is not None and certificate.vehicle_counts["cv"] > int(instance.num_cv):
        failures.append(f"{CONTRACT_ID}: needs {certificate.vehicle_counts['cv']} CV but cap is {instance.num_cv}")
    if instance.num_ev is not None and certificate.vehicle_counts["ev"] > int(instance.num_ev):
        failures.append(f"{CONTRACT_ID}: needs {certificate.vehicle_counts['ev']} EV but cap is {instance.num_ev}")
    return failures
