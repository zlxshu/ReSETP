"""Versioned physical-vehicle scheduling contract for new E3--E7 evidence.

This module is deliberately additive.  It does not alter the legacy route-level
checker used by frozen E1/E2 artifacts. V1 is retained as the historical
full-recharge audit rule; V2 treats every Route as one trip, assigns
non-overlapping trips to real vehicles, and carries battery between trips.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import heapq
from typing import Any

from ..cost import _arc_loads, ev_arc_energy_kwh, _price
from ..instance_loader import Instance
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import ChargingAction, Route, Solution, route_trip_vehicle_id


LEGACY_CONTRACT_ID = "E3_STRICT_MULTITRIP_V1"
CONTRACT_ID = "E3_STRICT_MULTITRIP_V2"
CHARGE_MODE_FULL = "full"
CHARGE_MODE_PARTIAL = "partial"
CHARGE_MODE_ON_DEMAND = "on_demand"
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
    recharge_mode: str = CHARGE_MODE_ON_DEMAND,
    initial_departure_battery_by_route: dict[str, float] | None = None,
) -> MultiTripCertificate:
    """Build a reproducible physical-vehicle schedule for one fixed route set.

    This is a *feasibility witness*, not a proof of the minimum vehicle count.
    It deliberately reads depot charging power from the same ``prices`` object
    used by the route checker. ``on_demand`` is the formal V2 rule: carry the
    battery across trips and add only the energy needed to make the next trip.
    ``partial`` remains a backward-compatible spelling for old diagnostic files.
    ``full`` is retained only for replaying the historical V1 audit rule.
    """

    if recharge_mode not in {CHARGE_MODE_FULL, CHARGE_MODE_PARTIAL, CHARGE_MODE_ON_DEMAND}:
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
                initial_departure_battery_by_route=initial_departure_battery_by_route or {},
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
    initial_departure_battery_by_route: dict[str, float],
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
                charge_energy = max(0.0, timing.drive_energy_kwh - state.battery_kwh)
                if charge_energy > battery_kwh - state.battery_kwh + _TOL:
                    continue
                if charge_energy > max(0.0, gap_seconds) * depot_charge_power_kw / 3600.0 + _TOL:
                    continue
                departure_battery = state.battery_kwh + charge_energy
            if departure_battery + _TOL < timing.drive_energy_kwh:
                continue
            candidates.append((departure_battery, -state.available_second, state, charge_energy))
        if candidates:
            _, _, state, charge_energy = max(candidates, key=lambda item: (item[0], item[1], -item[2].local_id))
            if recharge_mode in {CHARGE_MODE_PARTIAL, CHARGE_MODE_ON_DEMAND} and state.previous_route_id is not None:
                previous = scheduled[state.previous_route_id]
                charge_seconds = charge_energy / depot_charge_power_kw * 3600.0
                charge_start = timing.earliest_departure_second - charge_seconds
                scheduled[state.previous_route_id] = replace(
                    previous,
                    recharge_end_second=charge_start + charge_seconds,
                    charge_start_second=charge_start if charge_energy > _TOL else None,
                    charge_energy_kwh=charge_energy,
                )
            state.trip_index += 1
            start_battery = battery_kwh if recharge_mode == CHARGE_MODE_FULL else state.battery_kwh + charge_energy
        else:
            next_local_id += 1
            start_battery = (
                battery_kwh
                if recharge_mode == CHARGE_MODE_FULL
                else float(initial_departure_battery_by_route.get(timing.route_id, battery_kwh))
            )
            if start_battery > battery_kwh + _TOL:
                raise ValueError(f"{CONTRACT_ID}: route {timing.route_id} starts above battery capacity")
            if start_battery + _TOL < timing.drive_energy_kwh:
                raise ValueError(f"{CONTRACT_ID}: route {timing.route_id} has insufficient first-trip departure battery")
            state = _EVVehicleState(next_local_id, 1, timing.earliest_departure_second, start_battery, None)
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
    if certificate.recharge_mode not in {CHARGE_MODE_FULL, CHARGE_MODE_PARTIAL, CHARGE_MODE_ON_DEMAND}:
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
            first_start = float(ordered[0].start_battery_kwh or 0.0)
            if certificate.recharge_mode == CHARGE_MODE_FULL and abs(first_start - _price(prices, "B_battery_kwh")) > _TOL:
                raise ValueError(f"{CONTRACT_ID}: {vehicle_id} first trip does not depart full")
            if certificate.recharge_mode != CHARGE_MODE_FULL and not (-_TOL <= first_start <= _price(prices, "B_battery_kwh") + _TOL):
                raise ValueError(f"{CONTRACT_ID}: {vehicle_id} first-trip departure battery is outside capacity")
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
    recharge_mode: str = CHARGE_MODE_ON_DEMAND,
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


def certificate_charging_actions(certificate: MultiTripCertificate) -> list[ChargingAction]:
    """Convert every between-trip V2 charge into the canonical cost/carbon ledger.

    The action is attached to the following trip id because it raises that
    trip's departure battery.  This helper does not mutate a search solution;
    the E3 runner must explicitly merge these actions before formal evidence.
    """

    by_vehicle: dict[str, list[ScheduledTrip]] = {}
    for trip in certificate.trips:
        by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)
    actions: list[ChargingAction] = []
    for trips in by_vehicle.values():
        ordered = sorted(trips, key=lambda item: item.trip_index)
        for previous, current in zip(ordered, ordered[1:]):
            energy = float(previous.charge_energy_kwh or 0.0)
            if energy <= _TOL:
                continue
            if previous.charge_start_second is None:
                raise ValueError(f"{CONTRACT_ID}: between-trip charge has no start")
            actions.append(
                ChargingAction(
                    vehicle_id=current.route_id,
                    station_id=current.home_depot_id,
                    energy_kwh=energy,
                    occupancy_minutes=energy / certificate.depot_charge_power_kw * 60.0,
                    charge_start_second=float(previous.charge_start_second),
                )
            )
    return actions


def prepare_multitrip_solution(
    solution: Solution,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> tuple[Solution, MultiTripCertificate]:
    """Attach the V2 physical schedule and its real charging ledger.

    Legacy route ids are replaced by the physical-vehicle/trip ids certified
    here. First trips keep their existing depot precharge. Later trips replace
    the legacy route-level precharge with exactly the between-trip energy from
    the V2 battery chain. Public-station actions are never dropped; V2 stops
    earlier in ``route_timing`` if such a route is not yet supported.
    """

    battery_cap = _price(prices, "B_battery_kwh")
    inherited = _price(prices, "initial_ev_battery_kwh")
    initial_departure: dict[str, float] = {}
    for route in solution.routes:
        if route.vehicle_type.lower() != "ev":
            continue
        depot_energy = sum(
            float(action.energy_kwh)
            for action in solution.charging_actions
            if action.vehicle_id == route.vehicle_id and action.station_id == route.home_depot_id
        )
        initial_departure[route.vehicle_id] = min(battery_cap, inherited + depot_energy)

    certificate = build_multitrip_certificate(
        list(solution.routes),
        instance,
        prices,
        recharge_mode=CHARGE_MODE_ON_DEMAND,
        initial_departure_battery_by_route=initial_departure,
    )
    scheduled_by_old_id = {trip.route_id: trip for trip in certificate.trips}
    id_map = {
        old_id: route_trip_vehicle_id(trip.physical_vehicle_id, trip.trip_index)
        for old_id, trip in scheduled_by_old_id.items()
    }
    prepared_routes = [replace(route, vehicle_id=id_map[route.vehicle_id]) for route in solution.routes]

    prepared_actions: list[ChargingAction] = []
    for action in solution.charging_actions:
        trip = scheduled_by_old_id.get(action.vehicle_id)
        if trip is None:
            continue
        is_origin_depot = action.station_id == trip.home_depot_id
        if is_origin_depot and trip.trip_index > 1:
            continue
        prepared_actions.append(replace(action, vehicle_id=id_map[action.vehicle_id]))

    remapped_trips = tuple(
        replace(trip, route_id=id_map[trip.route_id])
        for trip in certificate.trips
    )
    remapped_certificate = replace(certificate, trips=remapped_trips)
    prepared_actions.extend(certificate_charging_actions(remapped_certificate))
    prepared = Solution(
        routes=prepared_routes,
        charging_actions=prepared_actions,
        cross_site_services=solution.cross_site_services,
    )
    return prepared, remapped_certificate
