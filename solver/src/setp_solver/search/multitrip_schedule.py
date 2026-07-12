"""Versioned physical-vehicle scheduling contract for new E3--E7 evidence.

This module is deliberately additive.  It does not alter the legacy route-level
checker used by frozen E1/E2 artifacts.  E3_STRICT_MULTITRIP_V1 treats every
Route as one trip and assigns non-overlapping trips to real vehicles.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import heapq
from typing import Any

from ..cost import _arc_loads, ev_arc_energy_kwh, _price
from ..instance_loader import Instance
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import Route


CONTRACT_ID = "E3_STRICT_MULTITRIP_V1"


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


@dataclass(frozen=True)
class MultiTripCertificate:
    contract_id: str
    status: str
    vehicle_counts: dict[str, int]
    trips: tuple[ScheduledTrip, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def route_timing(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> TripTiming:
    """Compute the earliest legal trip interval without changing route schema."""

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
    # same customer order.  This is the standard route-to-trip scheduling
    # separation: routing chooses the sequence; scheduling chooses its clock.
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
    depot_charge_power_kw: float = 60.0,
) -> MultiTripCertificate:
    """Assign fixed trip intervals optimally to the minimum number of vehicles.

    For fixed intervals, earliest-finish heap partitioning is exact.  EV reuse
    additionally reserves the full post-trip recharge time, so battery state is
    full at each subsequent departure and continuous between trips.
    """

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
        available: list[tuple[float, int, int]] = []
        next_local_id = 0
        for timing in group:
            if available and available[0][0] <= timing.earliest_departure_second + 1e-6:
                _, local_id, trip_index = heapq.heappop(available)
                trip_index += 1
            else:
                next_local_id += 1
                local_id, trip_index = next_local_id, 1
            prefix = "EV" if vehicle_type == "ev" else "CV"
            physical_id = f"{prefix}_{depot}_{local_id}"
            recharge_seconds = 0.0
            start_battery = end_battery = None
            if vehicle_type == "ev":
                battery = _price(prices, "B_battery_kwh")
                start_battery = battery
                end_battery = battery - timing.drive_energy_kwh
                recharge_seconds = timing.drive_energy_kwh / depot_charge_power_kw * 3600.0
            recharge_end = timing.return_second + recharge_seconds
            heapq.heappush(available, (recharge_end, local_id, trip_index))
            scheduled.append(ScheduledTrip(
                timing.route_id, physical_id, trip_index, vehicle_type, depot,
                timing.earliest_departure_second, timing.return_second, recharge_end,
                start_battery, end_battery,
            ))
        counts[vehicle_type] += next_local_id
    certificate = MultiTripCertificate(CONTRACT_ID, "PASS", counts, tuple(sorted(scheduled, key=lambda x: x.route_id)))
    validate_multitrip_certificate(certificate, routes)
    return certificate


def validate_multitrip_certificate(certificate: MultiTripCertificate, routes: list[Route]) -> None:
    if certificate.contract_id != CONTRACT_ID:
        raise ValueError("unknown multi-trip contract")
    if {trip.route_id for trip in certificate.trips} != {route.vehicle_id for route in routes}:
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
