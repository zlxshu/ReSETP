"""Versioned physical-vehicle scheduling contract for new E3--E7 evidence.

This module is deliberately additive.  It does not alter the legacy route-level
checker used by frozen E1/E2 artifacts. V1 is retained as the historical
full-recharge audit rule; V2 treats every Route as one trip, assigns
non-overlapping trips to real vehicles, and carries battery between trips.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
import heapq
from typing import Any

from ..charging_curve import (
    ChargingCurveError,
    L100_CONTROL,
    PiecewiseChargingCurve,
    curve_from_parameters,
    pack_trip_chain,
)
from ..cost import _arc_loads, carbon_profile_row_for_slot, charging_slot_breakdown, ev_arc_energy_kwh, _price
from ..instance_loader import Instance
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import ChargingAction, Route, Solution, physical_vehicle_id, route_trip_vehicle_id


LEGACY_CONTRACT_ID = "E3_STRICT_MULTITRIP_V1"
CONTRACT_ID = "E3_STRICT_MULTITRIP_V2"
NONLINEAR_CONTRACT_ID = "E3_STRICT_MULTITRIP_V3_NL"
CHARGE_MODE_FULL = "full"
CHARGE_MODE_PARTIAL = "partial"
CHARGE_MODE_ON_DEMAND = "on_demand"
STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET = -1
STATIC_PREHORIZON_SECONDS = 86_400.0
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
    first_trip_charge_day_offset: int = STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET
    charging_curve_id: str = L100_CONTROL.curve_id
    charging_curve_parameter_sha256: str = L100_CONTROL.parameter_sha256

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def multitrip_certificate_from_dict(
    payload: Mapping[str, Any],
) -> MultiTripCertificate:
    """Load historical V2 and current curve-aware certificate JSON."""

    return MultiTripCertificate(
        contract_id=str(payload["contract_id"]),
        status=str(payload["status"]),
        vehicle_counts={
            str(key): int(value)
            for key, value in dict(payload["vehicle_counts"]).items()
        },
        trips=tuple(
            ScheduledTrip(**dict(row)) for row in payload.get("trips", ())
        ),
        recharge_mode=str(payload["recharge_mode"]),
        depot_charge_power_kw=float(payload["depot_charge_power_kw"]),
        first_trip_charge_day_offset=int(
            payload.get(
                "first_trip_charge_day_offset",
                STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET,
            )
        ),
        charging_curve_id=str(
            payload.get("charging_curve_id", L100_CONTROL.curve_id)
        ),
        charging_curve_parameter_sha256=str(
            payload.get(
                "charging_curve_parameter_sha256",
                L100_CONTROL.parameter_sha256,
            )
        ),
    )


def _curve_for_prices(
    prices: PriceParameters | dict[str, Any] | Any,
) -> PiecewiseChargingCurve:
    try:
        return curve_from_parameters(
            prices,
            capacity_kwh=_price(prices, "B_battery_kwh"),
            reference_power_kw=_price(prices, "depot_charge_power_kw"),
        )
    except ChargingCurveError as exc:
        raise ValueError(f"{NONLINEAR_CONTRACT_ID}: {exc}") from exc


def _certificate_curve(
    certificate: MultiTripCertificate,
    prices: PriceParameters | dict[str, Any] | Any,
) -> PiecewiseChargingCurve:
    curve = _curve_for_prices(prices)
    if certificate.contract_id == CONTRACT_ID:
        if curve.curve_id != L100_CONTROL.curve_id:
            raise ValueError(
                f"{NONLINEAR_CONTRACT_ID}: V2 certificates are linear-only"
            )
    elif certificate.contract_id != NONLINEAR_CONTRACT_ID:
        raise ValueError("unknown multi-trip contract")
    if certificate.charging_curve_id != curve.curve_id:
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: certificate curve id disagrees with prices"
        )
    if certificate.charging_curve_parameter_sha256 != curve.parameter_sha256:
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: certificate curve hash disagrees with prices"
        )
    return curve


def _canonical_curve_energy(
    curve: PiecewiseChargingCurve,
    value: float,
    *,
    label: str,
) -> float:
    """Clamp floating-point dust while rejecting real battery-bound violations."""

    energy = float(value)
    if energy < -_TOL or energy > curve.capacity_kwh + _TOL:
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: {label} lies outside battery bounds"
        )
    return min(curve.capacity_kwh, max(0.0, energy))


def _validate_action_curve_metadata(
    action: ChargingAction,
    *,
    start_energy_kwh: float,
    end_energy_kwh: float,
    curve: PiecewiseChargingCurve,
    require_explicit: bool,
) -> None:
    values = (
        action.start_energy_kwh,
        action.end_energy_kwh,
        action.charging_curve_id,
    )
    if not require_explicit and all(value is None for value in values):
        return
    if any(value is None for value in values):
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: charging action has incomplete curve metadata"
        )
    if action.charging_curve_id != curve.curve_id:
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: charging action curve id disagrees"
        )
    expected_start = _canonical_curve_energy(
        curve,
        start_energy_kwh,
        label="expected charging start energy",
    )
    expected_end = _canonical_curve_energy(
        curve,
        end_energy_kwh,
        label="expected charging end energy",
    )
    actual_start = _canonical_curve_energy(
        curve,
        float(action.start_energy_kwh),
        label="recorded charging start energy",
    )
    actual_end = _canonical_curve_energy(
        curve,
        float(action.end_energy_kwh),
        label="recorded charging end energy",
    )
    if abs(actual_start - expected_start) > _TOL:
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: charging action start energy disagrees"
        )
    if abs(actual_end - expected_end) > _TOL:
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: charging action end energy disagrees"
        )
    duration = curve.duration_seconds(expected_start, expected_end)
    if abs(float(action.occupancy_minutes) * 60.0 - duration) > _TOL:
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: charging action duration disagrees with curve"
        )


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
    # A trip has no departure field in the frozen Route schema. Compute the
    # latest feasible origin service time by the standard backward time-window
    # recursion, then replay forward. The former "remove all waiting" shortcut
    # could push an early-due customer past its deadline on mixed-shift routes.
    elapsed = float(origin.service_time)
    departure_candidates = [float(origin.ready_time) + float(origin.service_time)]
    for from_id, to_id in zip(route.node_sequence, route.node_sequence[1:]):
        elapsed += instance.distance(from_id, to_id) / _price(prices, "v_speed_ms")
        departure_candidates.append(float(nodes[to_id].ready_time) - elapsed)
        elapsed += float(nodes[to_id].service_time)
    preferred_departure = max(departure_candidates)

    latest_start = float(nodes[route.node_sequence[-1]].due_time)
    for index in range(len(route.node_sequence) - 2, -1, -1):
        node = nodes[route.node_sequence[index]]
        next_id = route.node_sequence[index + 1]
        travel = instance.distance(route.node_sequence[index], next_id) / _price(prices, "v_speed_ms")
        latest_start = min(float(node.due_time), latest_start - float(node.service_time) - travel)
    if latest_start < float(origin.ready_time) - _TOL:
        raise ValueError(f"{CONTRACT_ID}: route {route.vehicle_id} has no feasible departure time")
    latest_departure = latest_start + float(origin.service_time)
    depart = min(preferred_departure, latest_departure)
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
    battery_kwh = _price(prices, "B_battery_kwh")
    charging_curve = _curve_for_prices(prices)
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
                battery_kwh=battery_kwh,
                charging_curve=charging_curve,
                recharge_mode=recharge_mode,
                initial_departure_battery_by_route=initial_departure_battery_by_route or {},
            )
        scheduled.extend(group_trips)
        counts[vehicle_type] += group_count
    certificate = MultiTripCertificate(
        (
            CONTRACT_ID
            if charging_curve.curve_id == L100_CONTROL.curve_id
            else NONLINEAR_CONTRACT_ID
        ),
        "PASS",
        counts,
        tuple(sorted(scheduled, key=lambda x: x.route_id)),
        recharge_mode,
        depot_charge_power_kw,
        STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET,
        charging_curve.curve_id,
        charging_curve.parameter_sha256,
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
    charging_curve: PiecewiseChargingCurve,
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
                departure_battery = charging_curve.reachable_energy_kwh(
                    state.battery_kwh,
                    max(0.0, gap_seconds),
                )
                charge_energy = departure_battery - state.battery_kwh
            if departure_battery + _TOL < timing.drive_energy_kwh:
                continue
            candidates.append((departure_battery, -state.available_second, state, charge_energy))
        if candidates:
            _, _, state, charge_energy = max(candidates, key=lambda item: (item[0], item[1], -item[2].local_id))
            if recharge_mode in {CHARGE_MODE_PARTIAL, CHARGE_MODE_ON_DEMAND} and state.previous_route_id is not None:
                previous = scheduled[state.previous_route_id]
                charge_seconds = (
                    charging_curve.duration_seconds(
                        state.battery_kwh, state.battery_kwh + charge_energy
                    )
                    if charge_energy > _TOL
                    else 0.0
                )
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
        charge_seconds_after = (
            charging_curve.duration_seconds(end_battery, battery_kwh)
            if charge_energy_after > _TOL
            else 0.0
        )
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
    result = list(scheduled.values())
    if recharge_mode in {CHARGE_MODE_PARTIAL, CHARGE_MODE_ON_DEMAND}:
        result = _minimize_ev_chain_charging(result, charging_curve)
    return result, next_local_id


def _minimize_ev_chain_charging(
    trips: list[ScheduledTrip],
    charging_curve: PiecewiseChargingCurve,
) -> list[ScheduledTrip]:
    """Remove surplus energy after max-charge feasibility packing.

    Backward recursion computes the least departure battery needed at every
    trip while retaining enough room to survive any later short charging gap.
    Total charged energy then equals driving energy plus the final residual.
    """

    by_vehicle: dict[str, list[ScheduledTrip]] = {}
    for trip in trips:
        by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)
    updated: dict[str, ScheduledTrip] = {}
    for chain in by_vehicle.values():
        ordered = sorted(chain, key=lambda item: item.trip_index)
        energies = [float(trip.start_battery_kwh or 0.0) - float(trip.end_battery_kwh or 0.0) for trip in ordered]
        gaps = [
            max(
                0.0,
                ordered[index + 1].departure_second
                - ordered[index].return_second,
            )
            for index in range(len(ordered) - 1)
        ]
        try:
            packed = pack_trip_chain(charging_curve, energies, gaps)
        except ChargingCurveError as exc:
            raise ValueError(
                f"{NONLINEAR_CONTRACT_ID}: packed EV chain cannot be supported"
            ) from exc
        for index, (trip, row) in enumerate(zip(ordered, packed, strict=True)):
            charge_start = (
                ordered[index + 1].departure_second
                - row.charge_duration_seconds
                if row.charge_energy_kwh > _TOL
                else None
            )
            recharge_end = (
                charge_start + row.charge_duration_seconds
                if charge_start is not None
                else trip.return_second
            )
            updated[trip.route_id] = replace(
                trip,
                start_battery_kwh=row.departure_energy_kwh,
                end_battery_kwh=row.return_energy_kwh,
                charge_energy_kwh=(
                    row.charge_energy_kwh
                    if row.charge_energy_kwh > _TOL
                    else None
                ),
                charge_start_second=charge_start,
                recharge_end_second=recharge_end,
            )
    return [updated[trip.route_id] for trip in trips]


def validate_multitrip_certificate(
    certificate: MultiTripCertificate,
    routes: list[Route],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> None:
    charging_curve = _certificate_curve(certificate, prices)
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
                start_energy = min(
                    charging_curve.capacity_kwh,
                    max(0.0, float(trip.end_battery_kwh or 0.0)),
                )
                end_energy = min(
                    charging_curve.capacity_kwh,
                    max(0.0, start_energy + energy),
                )
                expected_end = (
                    float(trip.charge_start_second)
                    + charging_curve.duration_seconds(
                        start_energy, end_energy
                    )
                )
                if abs(expected_end - trip.recharge_end_second) > _TOL:
                    raise ValueError(
                        f"{NONLINEAR_CONTRACT_ID}: {vehicle_id} charge duration "
                        "disagrees with charging curve"
                    )


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
            recorded_energy = float(previous.charge_energy_kwh or 0.0)
            if recorded_energy <= _TOL:
                continue
            if previous.charge_start_second is None:
                raise ValueError(f"{CONTRACT_ID}: between-trip charge has no start")
            start_energy = float(previous.end_battery_kwh or 0.0)
            end_energy = start_energy + recorded_energy
            actions.append(
                ChargingAction(
                    vehicle_id=current.route_id,
                    station_id=current.home_depot_id,
                    energy_kwh=recorded_energy,
                    occupancy_minutes=(
                        previous.recharge_end_second
                        - float(previous.charge_start_second)
                    )
                    / 60.0,
                    charge_start_second=float(previous.charge_start_second),
                    start_energy_kwh=start_energy,
                    end_energy_kwh=end_energy,
                    charging_curve_id=certificate.charging_curve_id,
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

    already_prepared = bool(solution.routes) and all(
        "#T" in route.vehicle_id and physical_vehicle_id(route.vehicle_id).startswith(("CV_", "EV_"))
        for route in solution.routes
    )
    if already_prepared:
        certificate = _certificate_from_prepared_solution(solution, instance, prices)
    else:
        certificate = None

    battery_cap = _price(prices, "B_battery_kwh")
    charging_curve = _curve_for_prices(prices)
    inherited = _canonical_curve_energy(
        charging_curve,
        _price(prices, "initial_ev_battery_kwh"),
        label="initial EV battery",
    )
    initial_departure: dict[str, float] = {}
    for route in solution.routes:
        if route.vehicle_type.lower() != "ev":
            continue
        depot_energy = sum(
            float(action.energy_kwh)
            for action in solution.charging_actions
            if action.vehicle_id == route.vehicle_id and action.station_id == route.home_depot_id
        )
        initial_departure[route.vehicle_id] = min(
            battery_cap,
            inherited + depot_energy if already_prepared and depot_energy > _TOL else battery_cap,
        )

    if certificate is None:
        certificate = build_multitrip_certificate(
            list(solution.routes),
            instance,
            prices,
            recharge_mode=CHARGE_MODE_ON_DEMAND,
            initial_departure_battery_by_route=initial_departure,
        )
        certificate = _reuse_existing_between_trip_times(certificate, solution, prices)
    scheduled_by_old_id = {trip.route_id: trip for trip in certificate.trips}
    id_map = {
        old_id: route_trip_vehicle_id(trip.physical_vehicle_id, trip.trip_index)
        for old_id, trip in scheduled_by_old_id.items()
    }
    prepared_routes = [replace(route, vehicle_id=id_map[route.vehicle_id]) for route in solution.routes]

    prepared_actions: list[ChargingAction] = []
    first_trip_depot_action: dict[str, ChargingAction] = {}
    for action in solution.charging_actions:
        trip = scheduled_by_old_id.get(action.vehicle_id)
        if trip is None:
            continue
        is_origin_depot = action.station_id == trip.home_depot_id
        if is_origin_depot and trip.trip_index > 1:
            continue
        if is_origin_depot and trip.trip_index == 1:
            first_trip_depot_action[trip.route_id] = action
            continue
        prepared_actions.append(replace(action, vehicle_id=id_map[action.vehicle_id]))

    for trip in certificate.trips:
        if trip.vehicle_type != "ev" or trip.trip_index != 1:
            continue
        target_energy = _canonical_curve_energy(
            charging_curve,
            float(trip.start_battery_kwh or 0.0),
            label="first-trip departure energy",
        )
        energy = max(0.0, target_energy - inherited)
        if energy <= _TOL:
            continue
        duration = charging_curve.duration_seconds(inherited, target_energy)
        latest_start = STATIC_PREHORIZON_SECONDS - duration
        if latest_start < -_TOL:
            raise ValueError(f"{CONTRACT_ID}: first-trip depot precharge exceeds the pre-horizon day")
        old_action = first_trip_depot_action.get(trip.route_id)
        old_start = (
            float(old_action.charge_start_second) % STATIC_PREHORIZON_SECONDS
            if old_action is not None and float(old_action.charge_start_second) >= 0.0
            else None
        )
        start = (
            old_start
            if old_start is not None
            and old_start <= latest_start + _TOL
            else latest_start
        )
        prepared_actions.append(
            ChargingAction(
                vehicle_id=id_map[trip.route_id],
                station_id=trip.home_depot_id,
                energy_kwh=energy,
                occupancy_minutes=duration / 60.0,
                charge_start_second=start,
                charge_day_offset=STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET,
                start_energy_kwh=inherited,
                end_energy_kwh=target_energy,
                charging_curve_id=certificate.charging_curve_id,
            )
        )

    remapped_trips = tuple(
        replace(trip, route_id=id_map[trip.route_id])
        for trip in certificate.trips
    )
    remapped_certificate = replace(certificate, trips=remapped_trips)
    prepared_actions.extend(certificate_charging_actions(remapped_certificate))
    prepared_actions.sort(
        key=lambda action: (
            action.vehicle_id,
            action.station_id,
            float(action.charge_start_second),
            float(action.energy_kwh),
        )
    )
    prepared = Solution(
        routes=prepared_routes,
        charging_actions=prepared_actions,
        cross_site_services=solution.cross_site_services,
    )
    return prepared, remapped_certificate


def _certificate_from_prepared_solution(
    solution: Solution,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
) -> MultiTripCertificate:
    power = _price(prices, "depot_charge_power_kw")
    battery_cap = _price(prices, "B_battery_kwh")
    inherited = _price(prices, "initial_ev_battery_kwh")
    charging_curve = _curve_for_prices(prices)
    require_explicit = charging_curve.curve_id != L100_CONTROL.curve_id
    timings = {route.vehicle_id: route_timing(route, instance, prices) for route in solution.routes}
    routes = {route.vehicle_id: route for route in solution.routes}
    actions: dict[str, list[ChargingAction]] = {}
    for action in solution.charging_actions:
        actions.setdefault(action.vehicle_id, []).append(action)
    by_vehicle: dict[str, list[Route]] = {}
    for route in solution.routes:
        by_vehicle.setdefault(physical_vehicle_id(route.vehicle_id), []).append(route)
    scheduled: list[ScheduledTrip] = []
    counts = {"cv": 0, "ev": 0}
    for physical_id, chain_routes in sorted(by_vehicle.items()):
        ordered = sorted(chain_routes, key=lambda route: int(route.vehicle_id.rsplit("#T", 1)[1]))
        vehicle_type = ordered[0].vehicle_type.lower()
        counts[vehicle_type] += 1
        previous_end: float | None = None
        chain: list[ScheduledTrip] = []
        for position, route in enumerate(ordered):
            trip_index = int(route.vehicle_id.rsplit("#T", 1)[1])
            timing = timings[route.vehicle_id]
            depot_actions = [action for action in actions.get(route.vehicle_id, []) if action.station_id == route.home_depot_id]
            depot_energy = sum(float(action.energy_kwh) for action in depot_actions)
            if vehicle_type == "ev":
                start_battery = inherited + depot_energy if position == 0 else float(previous_end or 0.0) + depot_energy
                if start_battery > battery_cap + _TOL or start_battery + _TOL < timing.drive_energy_kwh:
                    raise ValueError(f"{CONTRACT_ID}: prepared route {route.vehicle_id} has a broken battery ledger")
                end_battery = start_battery - timing.drive_energy_kwh
                if depot_energy > _TOL:
                    if require_explicit and len(depot_actions) != 1:
                        raise ValueError(
                            f"{NONLINEAR_CONTRACT_ID}: prepared route "
                            f"{route.vehicle_id} must have one explicit depot action"
                        )
                    action_start = inherited if position == 0 else float(previous_end or 0.0)
                    for action in depot_actions:
                        _validate_action_curve_metadata(
                            action,
                            start_energy_kwh=action_start,
                            end_energy_kwh=start_battery,
                            curve=charging_curve,
                            require_explicit=require_explicit,
                        )
            else:
                start_battery = end_battery = None
            chain.append(
                ScheduledTrip(
                    route.vehicle_id,
                    physical_id,
                    trip_index,
                    vehicle_type,
                    route.home_depot_id,
                    timing.earliest_departure_second,
                    timing.return_second,
                    timing.return_second,
                    start_battery,
                    end_battery,
                )
            )
            if position > 0 and vehicle_type == "ev" and depot_energy > _TOL:
                if len(depot_actions) != 1:
                    raise ValueError(f"{CONTRACT_ID}: prepared route {route.vehicle_id} must have one depot gap action")
                action = depot_actions[0]
                duration = float(action.occupancy_minutes) * 60.0
                previous = chain[-2]
                chain[-2] = replace(
                    previous,
                    charge_start_second=float(action.charge_start_second),
                    charge_energy_kwh=depot_energy,
                    recharge_end_second=float(action.charge_start_second) + duration,
                )
            previous_end = end_battery
        scheduled.extend(chain)
    certificate = MultiTripCertificate(
        (
            CONTRACT_ID
            if charging_curve.curve_id == L100_CONTROL.curve_id
            else NONLINEAR_CONTRACT_ID
        ),
        "PASS",
        counts,
        tuple(scheduled),
        CHARGE_MODE_ON_DEMAND,
        power,
        STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET,
        charging_curve.curve_id,
        charging_curve.parameter_sha256,
    )
    validate_multitrip_certificate(certificate, list(routes.values()), prices)
    return certificate


def _reuse_existing_between_trip_times(
    certificate: MultiTripCertificate,
    solution: Solution,
    prices: PriceParameters | dict[str, float] | Any,
) -> MultiTripCertificate:
    """Keep an already-valid aware/naive gap placement on repeated scoring."""

    charging_curve = _certificate_curve(certificate, prices)
    require_explicit = charging_curve.curve_id != L100_CONTROL.curve_id
    actions_by_route: dict[str, list[ChargingAction]] = {}
    for action in solution.charging_actions:
        actions_by_route.setdefault(action.vehicle_id, []).append(action)
    by_vehicle: dict[str, list[ScheduledTrip]] = {}
    for trip in certificate.trips:
        by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)
    replacements: dict[str, ScheduledTrip] = {}
    for trips in by_vehicle.values():
        ordered = sorted(trips, key=lambda item: item.trip_index)
        for previous, current in zip(ordered, ordered[1:]):
            expected = float(previous.charge_energy_kwh or 0.0)
            if expected <= _TOL:
                continue
            depot_actions = [
                action
                for action in actions_by_route.get(current.route_id, [])
                if action.station_id == current.home_depot_id
            ]
            if len(depot_actions) != 1:
                continue
            action = depot_actions[0]
            if abs(float(action.energy_kwh) - expected) > _TOL:
                continue
            if require_explicit and (
                action.start_energy_kwh is None
                or action.end_energy_kwh is None
                or action.charging_curve_id is None
            ):
                continue
            _validate_action_curve_metadata(
                action,
                start_energy_kwh=float(previous.end_battery_kwh or 0.0),
                end_energy_kwh=(
                    float(previous.end_battery_kwh or 0.0) + expected
                ),
                curve=charging_curve,
                require_explicit=require_explicit,
            )
            duration = float(action.occupancy_minutes) * 60.0
            start = float(action.charge_start_second)
            end = start + duration
            if start < previous.return_second - _TOL or end > current.departure_second + _TOL:
                continue
            replacements[previous.route_id] = replace(
                previous,
                charge_start_second=start,
                recharge_end_second=end,
            )
    if not replacements:
        return certificate
    updated = replace(
        certificate,
        trips=tuple(replacements.get(trip.route_id, trip) for trip in certificate.trips),
    )
    validate_multitrip_certificate(updated, list(solution.routes), prices)
    return updated


def reschedule_between_trip_charging(
    solution: Solution,
    certificate: MultiTripCertificate,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    *,
    strategy: str,
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None = None,
    intensity_field: str = "actual_gco2_per_kwh",
) -> Solution:
    """Move fixed charging energy within its legal gap without new route search.

    Historical callers pass one repeated daily profile and therefore retain the
    sealed behaviour.  Calendar-aware replays can instead provide one profile
    per ``charge_day_offset`` (for example ``-1`` for the preceding night and
    ``0`` for the operating day) and choose whether timing decisions use the
    forecast or actual carbon-intensity field.  Cost evaluation remains a
    separate concern, so a forecast-timed solution can still be settled against
    actual carbon intensity.
    """

    if strategy not in {"aware", "naive"}:
        raise ValueError(f"unknown between-trip charging strategy {strategy!r}")
    if certificate.charging_curve_id != L100_CONTROL.curve_id:
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: carbon-aware nonlinear rescheduling "
            "is blocked until the NL2 slot integrator is connected"
        )

    def profile_for(day_offset: int) -> list[dict[str, Any]]:
        if carbon_profiles_by_day_offset is None:
            return carbon_profile
        try:
            return carbon_profiles_by_day_offset[int(day_offset)]
        except KeyError as exc:
            raise ValueError(f"missing carbon profile for charge_day_offset={day_offset}") from exc

    by_vehicle: dict[str, list[ScheduledTrip]] = {}
    for trip in certificate.trips:
        by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)
    selected_starts: dict[str, float] = {}
    for trips in by_vehicle.values():
        ordered = sorted(trips, key=lambda item: item.trip_index)
        first = ordered[0]
        if first.vehicle_type == "ev":
            first_actions = [
                action
                for action in solution.charging_actions
                if action.vehicle_id == first.route_id and action.station_id == first.home_depot_id
            ]
            if len(first_actions) == 1 and float(first_actions[0].energy_kwh) > _TOL:
                action = first_actions[0]
                energy = float(action.energy_kwh)
                duration = float(action.occupancy_minutes) * 60.0
                earliest = 0.0
                latest = STATIC_PREHORIZON_SECONDS - duration
                if latest < earliest - _TOL:
                    raise ValueError(f"{CONTRACT_ID}: first-trip depot precharge exceeds the pre-horizon day")
                selected_starts[first.route_id] = (
                    earliest
                    if strategy == "naive"
                    else _lowest_carbon_gap_start(
                        earliest,
                        latest,
                        duration,
                        energy,
                        instance,
                        profile_for(int(action.charge_day_offset)),
                        intensity_field=intensity_field,
                    )
                )
        for previous, current in zip(ordered, ordered[1:]):
            energy = float(previous.charge_energy_kwh or 0.0)
            if energy <= _TOL:
                continue
            if previous.charge_start_second is None:
                raise ValueError(f"{CONTRACT_ID}: between-trip charge has no start")
            duration = (
                previous.recharge_end_second
                - float(previous.charge_start_second)
            )
            earliest = float(previous.return_second)
            latest = float(current.departure_second) - duration
            if latest < earliest - _TOL:
                raise ValueError(f"{CONTRACT_ID}: no legal gap for {current.route_id}")
            selected_starts[current.route_id] = (
                earliest
                if strategy == "naive"
                else _lowest_carbon_gap_start(
                    earliest,
                    latest,
                    duration,
                    energy,
                    instance,
                    profile_for(0),
                    intensity_field=intensity_field,
                )
            )
    actions: list[ChargingAction] = []
    for action in solution.charging_actions:
        if action.vehicle_id in selected_starts and action.station_id in {
            trip.home_depot_id for trip in certificate.trips if trip.route_id == action.vehicle_id
        }:
            actions.append(replace(action, charge_start_second=selected_starts[action.vehicle_id]))
        else:
            actions.append(action)
    return replace(solution, charging_actions=actions)


def drop_multitrip_identity(solution: Solution) -> Solution:
    """Give fixed routes neutral ids before rebuilding a charging schedule."""

    id_map = {
        route.vehicle_id: f"{'EV' if route.vehicle_type.lower() == 'ev' else 'CV'}_REPLAY_{index}"
        for index, route in enumerate(solution.routes, start=1)
    }
    return replace(
        solution,
        routes=[replace(route, vehicle_id=id_map[route.vehicle_id]) for route in solution.routes],
        charging_actions=[replace(action, vehicle_id=id_map.get(action.vehicle_id, action.vehicle_id)) for action in solution.charging_actions],
    )


def _lowest_carbon_gap_start(
    earliest: float,
    latest: float,
    duration: float,
    energy: float,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    *,
    intensity_field: str = "actual_gco2_per_kwh",
) -> float:
    if not carbon_profile or latest <= earliest + _TOL:
        return earliest
    candidates = {earliest, latest}
    slot_seconds = 1800.0
    first_slot = int(earliest // slot_seconds) - 1
    last_slot = int((latest + duration) // slot_seconds) + 1
    for slot_index in range(first_slot, last_slot + 1):
        boundary = slot_index * slot_seconds
        for candidate in (boundary, boundary - duration):
            if earliest - _TOL <= candidate <= latest + _TOL:
                candidates.add(min(latest, max(earliest, candidate)))

    def emissions(start: float) -> float:
        total = 0.0
        for slot in charging_slot_breakdown(
            start,
            duration,
            energy,
            instance,
            n_slots=len(carbon_profile),
            cyclic=True,
        ):
            row = carbon_profile_row_for_slot(carbon_profile, slot.slot_index)
            if intensity_field not in row:
                raise ValueError(f"carbon profile is missing timing field {intensity_field!r}")
            total += slot.y_skt_kwh * float(row[intensity_field])
        return total

    return min(candidates, key=lambda start: (emissions(start), start))
