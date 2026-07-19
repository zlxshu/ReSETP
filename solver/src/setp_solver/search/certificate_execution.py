"""Read-only execution clock derived from a strict multi-trip certificate.

The route schema deliberately has no absolute departure field.  Dynamic
experiments must therefore use the departure/return times certified by
``MultiTripCertificate`` instead of shifting a fresh route schedule to an
arbitrary trigger time.  This module binds a prepared solution to its
certificate and replays every arc from the certified departure time.

It does not mutate the solution, rebuild a schedule, or run a search.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import hashlib
import json
from types import MappingProxyType
from typing import Literal

from ..cost import (
    _arc_loads,
    _price,
    charging_curve_for_action,
    ev_arc_energy_kwh,
)
from ..instance_loader import Instance
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import ChargingAction, Route, Solution, physical_vehicle_id, route_trip_vehicle_id
from .multitrip_schedule import MultiTripCertificate, ScheduledTrip, validate_multitrip_certificate


EXECUTION_CLOCK_CONTRACT_ID = "E7_CERTIFICATE_EXECUTION_CLOCK_V1"
NOT_STARTED = "not_started"
IN_PROGRESS = "in_progress"
COMPLETED = "completed"
_TOL = 1e-6
_DAY_SECONDS = 86_400.0


@dataclass(frozen=True)
class NodeExecution:
    """Absolute clock at one occurrence of a node on one certified trip."""

    position: int
    node_id: str
    arrival_second: float
    service_start_second: float
    departure_second: float


@dataclass(frozen=True)
class TripExecution:
    """Immutable executed-trip witness, indexed by the stable route id."""

    route_id: str
    route_signature: str
    physical_vehicle_id: str
    trip_index: int
    vehicle_type: str
    home_depot_id: str
    departure_second: float
    return_second: float
    drive_energy_kwh: float
    nodes: tuple[NodeExecution, ...]

    def state_at(self, second: float) -> Literal["not_started", "in_progress", "completed"]:
        """Return trip state; depot waiting before departure is not execution."""

        if float(second) < self.departure_second:
            return NOT_STARTED
        if float(second) < self.return_second:
            return IN_PROGRESS
        return COMPLETED


@dataclass(frozen=True)
class PhysicalAsset:
    physical_vehicle_id: str
    vehicle_type: str
    home_depot_id: str
    route_ids: tuple[str, ...]
    first_departure_second: float
    final_return_second: float


@dataclass(frozen=True)
class CertificateExecutionLedger:
    """Read-only route and physical-asset index bound to one certificate."""

    contract_id: str
    certificate_sha256: str
    routes: Mapping[str, TripExecution]
    assets: Mapping[str, PhysicalAsset]

    def trip_state_at(
        self,
        route_id: str,
        second: float,
    ) -> Literal["not_started", "in_progress", "completed"]:
        try:
            trip = self.routes[str(route_id)]
        except KeyError as exc:
            raise KeyError(f"{EXECUTION_CLOCK_CONTRACT_ID}: unknown route {route_id}") from exc
        return trip.state_at(second)


def build_certificate_execution_ledger(
    solution: Solution,
    certificate: MultiTripCertificate,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | object = DEFAULT_PRICES,
) -> CertificateExecutionLedger:
    """Bind and replay a prepared strict-multitrip solution.

    Every clock value is recomputed by following the route from the certified
    ``departure_second``.  A route/certificate mismatch, an inconsistent
    return time, an overlapping physical vehicle, or a broken EV ledger is a
    hard error.  The returned mappings and all nested records are immutable.
    """

    if certificate.status != "PASS":
        raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: certificate status is not PASS")
    validate_multitrip_certificate(certificate, list(solution.routes), prices)

    route_ids = [route.vehicle_id for route in solution.routes]
    certificate_ids = [trip.route_id for trip in certificate.trips]
    if len(route_ids) != len(set(route_ids)):
        raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: solution has duplicate route ids")
    if len(certificate_ids) != len(set(certificate_ids)):
        raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: certificate maps a route more than once")
    if set(route_ids) != set(certificate_ids):
        missing = sorted(set(route_ids) - set(certificate_ids))
        extra = sorted(set(certificate_ids) - set(route_ids))
        raise ValueError(
            f"{EXECUTION_CLOCK_CONTRACT_ID}: route coverage mismatch; "
            f"missing={missing}, extra={extra}"
        )

    routes_by_id = {route.vehicle_id: route for route in solution.routes}
    trips_by_id = {trip.route_id: trip for trip in certificate.trips}
    executions: dict[str, TripExecution] = {}
    for route_id in sorted(routes_by_id):
        route = routes_by_id[route_id]
        trip = trips_by_id[route_id]
        _validate_route_binding(route, trip)
        execution = _replay_trip(route, trip, instance, prices)
        drive_energy = _validated_trip_energy(trip, route, instance, prices)
        execution = replace(execution, drive_energy_kwh=drive_energy)
        executions[route_id] = execution

    assets = _build_asset_map(executions, certificate)
    _validate_charging_ledger(
        solution,
        certificate,
        trips_by_id,
        instance,
        prices,
    )
    certificate_sha256 = _canonical_sha256(certificate.as_dict())
    return CertificateExecutionLedger(
        contract_id=EXECUTION_CLOCK_CONTRACT_ID,
        certificate_sha256=certificate_sha256,
        routes=MappingProxyType(dict(executions)),
        assets=MappingProxyType(dict(assets)),
    )


def _validate_route_binding(route: Route, trip: ScheduledTrip) -> None:
    expected_route_id = route_trip_vehicle_id(trip.physical_vehicle_id, trip.trip_index)
    if route.vehicle_id != expected_route_id:
        raise ValueError(
            f"{EXECUTION_CLOCK_CONTRACT_ID}: route {route.vehicle_id} does not bind to "
            f"{trip.physical_vehicle_id} trip {trip.trip_index}"
        )
    if physical_vehicle_id(route.vehicle_id) != trip.physical_vehicle_id:
        raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: physical vehicle id mismatch for {route.vehicle_id}")
    if route.vehicle_type.lower() != trip.vehicle_type.lower():
        raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: vehicle type mismatch for {route.vehicle_id}")
    if route.home_depot_id != trip.home_depot_id:
        raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: home depot mismatch for {route.vehicle_id}")
    if len(route.node_sequence) < 2:
        raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: route {route.vehicle_id} has no trip")
    if route.node_sequence[0] != trip.home_depot_id or route.node_sequence[-1] != trip.home_depot_id:
        raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: route {route.vehicle_id} is not depot closed")


def _replay_trip(
    route: Route,
    trip: ScheduledTrip,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | object,
) -> TripExecution:
    nodes = {node.node_id: node for node in instance.nodes}
    unknown = [node_id for node_id in route.node_sequence if node_id not in nodes]
    if unknown:
        raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: route {route.vehicle_id} has unknown nodes {unknown}")
    if not all(map(_finite, (trip.departure_second, trip.return_second))):
        raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: route {route.vehicle_id} has a non-finite clock")
    if trip.return_second < trip.departure_second - _TOL:
        raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: route {route.vehicle_id} returns before departure")

    # The certificate's departure is the boundary at which the vehicle leaves
    # its home depot.  Depot waiting/preparation before this instant does not
    # make a later trip "in progress".
    clock = float(trip.departure_second)
    events = [NodeExecution(0, route.node_sequence[0], clock, clock, clock)]
    speed = _price(prices, "v_speed_ms")
    if speed <= 0:
        raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: vehicle speed must be positive")
    for position, (from_id, to_id) in enumerate(
        zip(route.node_sequence, route.node_sequence[1:]),
        start=1,
    ):
        arrival = clock + instance.distance(from_id, to_id) / speed
        node = nodes[to_id]
        service_start = max(arrival, float(node.ready_time))
        if service_start > float(node.due_time) + _TOL:
            raise ValueError(
                f"{EXECUTION_CLOCK_CONTRACT_ID}: route {route.vehicle_id} misses "
                f"{to_id}'s time window"
            )
        clock = service_start + float(node.service_time)
        events.append(NodeExecution(position, to_id, arrival, service_start, clock))

    if abs(clock - float(trip.return_second)) > _TOL:
        raise ValueError(
            f"{EXECUTION_CLOCK_CONTRACT_ID}: route {route.vehicle_id} replay returns at "
            f"{clock:.12f}, certificate says {trip.return_second:.12f}"
        )
    signature = _canonical_sha256(
        {
            "route_id": route.vehicle_id,
            "vehicle_type": route.vehicle_type.lower(),
            "home_depot_id": route.home_depot_id,
            "node_sequence": list(route.node_sequence),
        }
    )
    return TripExecution(
        route_id=route.vehicle_id,
        route_signature=signature,
        physical_vehicle_id=trip.physical_vehicle_id,
        trip_index=int(trip.trip_index),
        vehicle_type=trip.vehicle_type.lower(),
        home_depot_id=trip.home_depot_id,
        departure_second=float(trip.departure_second),
        return_second=clock,
        drive_energy_kwh=0.0,
        nodes=tuple(events),
    )


def _validated_trip_energy(
    trip: ScheduledTrip,
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | object,
) -> float:
    if route.vehicle_type.lower() == "cv":
        if any(
            value is not None
            for value in (
                trip.start_battery_kwh,
                trip.end_battery_kwh,
                trip.charge_start_second,
                trip.charge_energy_kwh,
            )
        ):
            raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: CV route {route.vehicle_id} has an EV ledger")
        return 0.0

    nodes = {node.node_id: node for node in instance.nodes}
    loads = _arc_loads(route.node_sequence, nodes)
    drive_energy = sum(
        ev_arc_energy_kwh(instance.distance(from_id, to_id), loads[index], prices)
        for index, (from_id, to_id) in enumerate(zip(route.node_sequence, route.node_sequence[1:]))
    )
    certificate_energy = float(trip.start_battery_kwh or 0.0) - float(trip.end_battery_kwh or 0.0)
    if abs(drive_energy - certificate_energy) > _TOL:
        raise ValueError(
            f"{EXECUTION_CLOCK_CONTRACT_ID}: route {route.vehicle_id} drive energy "
            "does not close to its certificate battery change"
        )
    return float(drive_energy)


def _build_asset_map(
    executions: Mapping[str, TripExecution],
    certificate: MultiTripCertificate,
) -> dict[str, PhysicalAsset]:
    grouped: dict[str, list[TripExecution]] = {}
    for execution in executions.values():
        grouped.setdefault(execution.physical_vehicle_id, []).append(execution)
    assets: dict[str, PhysicalAsset] = {}
    for physical_id, chain in sorted(grouped.items()):
        ordered = sorted(chain, key=lambda item: item.trip_index)
        if [item.trip_index for item in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: {physical_id} has a broken trip sequence")
        if len({(item.vehicle_type, item.home_depot_id) for item in ordered}) != 1:
            raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: {physical_id} changes type or home depot")
        for previous, current in zip(ordered, ordered[1:]):
            if current.departure_second < previous.return_second - _TOL:
                raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: {physical_id} has overlapping trips")
        assets[physical_id] = PhysicalAsset(
            physical_vehicle_id=physical_id,
            vehicle_type=ordered[0].vehicle_type,
            home_depot_id=ordered[0].home_depot_id,
            route_ids=tuple(item.route_id for item in ordered),
            first_departure_second=ordered[0].departure_second,
            final_return_second=ordered[-1].return_second,
        )
    counts = {
        "cv": sum(asset.vehicle_type == "cv" for asset in assets.values()),
        "ev": sum(asset.vehicle_type == "ev" for asset in assets.values()),
    }
    if counts != {key: int(value) for key, value in certificate.vehicle_counts.items()}:
        raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: physical asset map disagrees with certificate counts")
    return assets


def _validate_charging_ledger(
    solution: Solution,
    certificate: MultiTripCertificate,
    trips_by_id: Mapping[str, ScheduledTrip],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | object,
) -> None:
    actions_by_route: dict[str, list[ChargingAction]] = {}
    for action in solution.charging_actions:
        if action.vehicle_id not in trips_by_id:
            raise ValueError(
                f"{EXECUTION_CLOCK_CONTRACT_ID}: charging action is detached from route {action.vehicle_id}"
            )
        if not all(map(_finite, (action.energy_kwh, action.occupancy_minutes, action.charge_start_second))):
            raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: route {action.vehicle_id} has a non-finite charge")
        if float(action.energy_kwh) < -_TOL or float(action.occupancy_minutes) < -_TOL:
            raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: route {action.vehicle_id} has a negative charge")
        actions_by_route.setdefault(action.vehicle_id, []).append(action)

    by_vehicle: dict[str, list[ScheduledTrip]] = {}
    for trip in certificate.trips:
        by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)
    initial_battery = _price(prices, "initial_ev_battery_kwh")
    for chain in by_vehicle.values():
        ordered = sorted(chain, key=lambda item: item.trip_index)
        for index, trip in enumerate(ordered):
            actions = actions_by_route.get(trip.route_id, [])
            if trip.vehicle_type == "cv":
                if actions:
                    raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: CV route {trip.route_id} has charging")
                continue
            if index == 0:
                expected_energy = float(trip.start_battery_kwh or 0.0) - initial_battery
                expected_action_start_energy = initial_battery
                expected_start = None
                expected_end = float(trip.departure_second)
                expected_day_offset = int(certificate.first_trip_charge_day_offset)
            else:
                previous = ordered[index - 1]
                expected_energy = float(previous.charge_energy_kwh or 0.0)
                expected_action_start_energy = float(
                    previous.end_battery_kwh or 0.0
                )
                expected_start = previous.charge_start_second
                expected_end = float(previous.recharge_end_second)
                expected_day_offset = 0
            if expected_energy < -_TOL:
                raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: route {trip.route_id} loses battery before departure")
            if expected_energy <= _TOL:
                if any(float(action.energy_kwh) > _TOL for action in actions):
                    raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: unexpected charging for {trip.route_id}")
                continue
            if len(actions) != 1:
                raise ValueError(
                    f"{EXECUTION_CLOCK_CONTRACT_ID}: route {trip.route_id} must have exactly one depot charge"
                )
            action = actions[0]
            if action.station_id != trip.home_depot_id:
                raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: route {trip.route_id} charges away from home")
            if abs(float(action.energy_kwh) - expected_energy) > _TOL:
                raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: route {trip.route_id} charge energy does not close")
            curve_state = charging_curve_for_action(action, instance, prices)
            if curve_state is None:
                expected_minutes = (
                    expected_energy
                    / float(certificate.depot_charge_power_kw)
                    * 60.0
                )
                if abs(float(action.occupancy_minutes) - expected_minutes) > _TOL:
                    raise ValueError(
                        f"{EXECUTION_CLOCK_CONTRACT_ID}: route "
                        f"{trip.route_id} charge duration does not close"
                    )
            else:
                _, action_start_energy, action_end_energy = curve_state
                if (
                    abs(
                        action_start_energy
                        - expected_action_start_energy
                    )
                    > _TOL
                    or abs(
                        action_end_energy
                        - (
                            expected_action_start_energy
                            + expected_energy
                        )
                    )
                    > _TOL
                ):
                    raise ValueError(
                        f"{EXECUTION_CLOCK_CONTRACT_ID}: route "
                        f"{trip.route_id} charge energy states do not bind "
                        "to the certificate"
                    )
            if int(action.charge_day_offset) != expected_day_offset:
                raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: route {trip.route_id} charge day is inconsistent")
            absolute_start = float(action.charge_start_second) + expected_day_offset * _DAY_SECONDS
            absolute_end = absolute_start + float(action.occupancy_minutes) * 60.0
            if expected_start is not None:
                if abs(float(action.charge_start_second) - float(expected_start)) > _TOL:
                    raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: route {trip.route_id} charge start drifted")
                if abs(absolute_end - expected_end) > _TOL:
                    raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: route {trip.route_id} charge end drifted")
            elif absolute_end > expected_end + _TOL:
                raise ValueError(f"{EXECUTION_CLOCK_CONTRACT_ID}: first-trip charge ends after departure")


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite(value: object) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and abs(number) != float("inf")
