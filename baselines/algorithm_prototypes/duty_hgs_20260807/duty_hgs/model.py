"""Duty-HGS decision objects and the fail-closed legacy Solution adapter.

v1 2026-08-07: represent one physical vehicle's complete ordered day and
preserve dynamic locks as sidecar metadata when crossing the legacy Solution
boundary.

v2 2026-08-07: add one fail-closed lock guard shared by crossover, repair, and
education so a Solution round trip cannot silently erase dynamic commitments.

v3 2026-08-07: refuse an ambiguous public-station decode when customer
identity was not supplied by the caller.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass

from setp_solver.solution import (
    ChargingAction,
    Route,
    Solution,
    physical_vehicle_id,
    route_trip_vehicle_id,
)


@dataclass(frozen=True)
class DutyTrip:
    """One ordered trip in a physical vehicle's day."""

    trip_index: int
    customer_ids: tuple[str, ...]
    locked_customer_prefix: tuple[str, ...] = ()
    route_visits: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "customer_ids", tuple(self.customer_ids))
        object.__setattr__(
            self,
            "locked_customer_prefix",
            tuple(self.locked_customer_prefix),
        )
        normalized_visits = tuple(self.route_visits)
        if normalized_visits == self.customer_ids:
            normalized_visits = ()
        object.__setattr__(self, "route_visits", normalized_visits)
        if int(self.trip_index) < 1:
            raise ValueError("trip_index must start at 1")
        if len(set(self.customer_ids)) != len(self.customer_ids):
            raise ValueError("one trip cannot contain a customer twice")
        prefix = self.customer_ids[: len(self.locked_customer_prefix)]
        if prefix != self.locked_customer_prefix:
            raise ValueError(
                "locked customer prefix must be an actual customer prefix"
            )
        visits = self.route_visits or self.customer_ids
        customer_positions = [
            visits.index(customer)
            for customer in self.customer_ids
            if customer in visits
        ]
        if len(customer_positions) != len(self.customer_ids) or (
            customer_positions != sorted(customer_positions)
        ):
            raise ValueError(
                "route_visits must contain every customer in customer order"
            )

    @property
    def effective_route_visits(self) -> tuple[str, ...]:
        return self.route_visits or self.customer_ids


@dataclass(frozen=True)
class DutyChargingSession:
    """One explicit charging decision attached to a specific trip."""

    trip_index: int
    station_id: str
    energy_kwh: float
    occupancy_minutes: float
    charge_start_second: float
    charge_day_offset: int = 0
    start_energy_kwh: float | None = None
    end_energy_kwh: float | None = None
    charging_curve_id: str | None = None
    locked: bool = False

    def __post_init__(self) -> None:
        if int(self.trip_index) < 1:
            raise ValueError("charging trip_index must start at 1")
        if float(self.energy_kwh) < 0.0:
            raise ValueError("charging energy cannot be negative")
        if float(self.occupancy_minutes) < 0.0:
            raise ValueError("charging occupancy cannot be negative")
        if not str(self.station_id):
            raise ValueError("charging station_id cannot be empty")


@dataclass(frozen=True)
class PhysicalVehicleDuty:
    """All trips and charging decisions for one physical vehicle."""

    physical_vehicle_id: str
    vehicle_type: str
    home_depot_id: str
    trips: tuple[DutyTrip, ...]
    charging_sessions: tuple[DutyChargingSession, ...] = ()

    def __post_init__(self) -> None:
        vehicle_type = str(self.vehicle_type).lower()
        object.__setattr__(self, "vehicle_type", vehicle_type)
        object.__setattr__(self, "trips", tuple(self.trips))
        object.__setattr__(
            self,
            "charging_sessions",
            tuple(self.charging_sessions),
        )
        expected_prefix = "EV_" if vehicle_type == "ev" else "CV_"
        if vehicle_type not in {"cv", "ev"}:
            raise ValueError("vehicle_type must be cv or ev")
        if not self.physical_vehicle_id.startswith(expected_prefix):
            raise ValueError(
                "physical_vehicle_id must start with EV_ or CV_ and match "
                "vehicle_type"
            )
        if "#T" in self.physical_vehicle_id:
            raise ValueError("physical_vehicle_id cannot contain a trip suffix")
        if not self.home_depot_id:
            raise ValueError("home_depot_id cannot be empty")
        indices = [int(trip.trip_index) for trip in self.trips]
        if indices != list(range(1, len(indices) + 1)):
            raise ValueError("duty trip indices must be contiguous and start at 1")
        known = set(indices)
        if any(
            int(session.trip_index) not in known
            for session in self.charging_sessions
        ):
            raise ValueError("charging session refers to a missing duty trip")

    def route_id(self, trip_index: int) -> str:
        return route_trip_vehicle_id(self.physical_vehicle_id, trip_index)

    @property
    def locked_charging_trip_indices(self) -> frozenset[int]:
        return frozenset(
            int(session.trip_index)
            for session in self.charging_sessions
            if session.locked
        )


@dataclass(frozen=True)
class DutyIndividual:
    """One complete Duty-HGS candidate before full-model evaluation."""

    duties: tuple[PhysicalVehicleDuty, ...]
    unserved_customers: tuple[str, ...] = ()
    version: int = 1
    source: str = "unknown"

    def __post_init__(self) -> None:
        object.__setattr__(self, "duties", tuple(self.duties))
        object.__setattr__(
            self,
            "unserved_customers",
            tuple(self.unserved_customers),
        )
        ids = [duty.physical_vehicle_id for duty in self.duties]
        if len(ids) != len(set(ids)):
            raise ValueError("physical_vehicle_id must be unique per individual")
        served = [
            customer
            for duty in self.duties
            for trip in duty.trips
            for customer in trip.customer_ids
        ]
        if len(served) != len(set(served)):
            raise ValueError("one customer cannot appear in two duty trips")
        if len(self.unserved_customers) != len(set(self.unserved_customers)):
            raise ValueError("unserved customer ids must be unique")
        overlap = set(served).intersection(self.unserved_customers)
        if overlap:
            raise ValueError(
                "served and unserved customer sets overlap: "
                + ", ".join(sorted(overlap))
            )

    @property
    def fingerprint(self) -> str:
        payload = {
            "version": int(self.version),
            "duties": [asdict(duty) for duty in self.duties],
            "unserved_customers": list(self.unserved_customers),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_solution(self) -> Solution:
        routes: list[Route] = []
        actions: list[ChargingAction] = []
        for duty in self.duties:
            for trip in duty.trips:
                route_id = duty.route_id(trip.trip_index)
                routes.append(
                    Route(
                        vehicle_id=route_id,
                        vehicle_type=duty.vehicle_type,
                        home_depot_id=duty.home_depot_id,
                        node_sequence=[
                            duty.home_depot_id,
                            *trip.effective_route_visits,
                            duty.home_depot_id,
                        ],
                    )
                )
            for session in duty.charging_sessions:
                actions.append(
                    ChargingAction(
                        vehicle_id=duty.route_id(session.trip_index),
                        station_id=session.station_id,
                        energy_kwh=float(session.energy_kwh),
                        occupancy_minutes=float(session.occupancy_minutes),
                        charge_start_second=float(session.charge_start_second),
                        charge_day_offset=int(session.charge_day_offset),
                        start_energy_kwh=session.start_energy_kwh,
                        end_energy_kwh=session.end_energy_kwh,
                        charging_curve_id=session.charging_curve_id,
                    )
                )
        actions.sort(key=_action_key)
        return Solution(routes=routes, charging_actions=actions)

    @classmethod
    def from_solution(
        cls,
        solution: Solution,
        *,
        locked_customer_prefix_by_route: Mapping[str, tuple[str, ...]] | None = None,
        locked_charging_routes: Iterable[str] = (),
        customer_node_ids: Iterable[str] | None = None,
        unserved_customers: Iterable[str] = (),
        source: str = "unknown",
    ) -> DutyIndividual:
        prefixes = locked_customer_prefix_by_route or {}
        locked_routes = set(locked_charging_routes)
        station_ids = {action.station_id for action in solution.charging_actions}
        known_customers = (
            None if customer_node_ids is None else set(customer_node_ids)
        )
        if known_customers is None and any(
            node_id in station_ids and node_id != route.home_depot_id
            for route in solution.routes
            for node_id in route.node_sequence[1:-1]
        ):
            raise ValueError(
                "customer_node_ids is required when a route visits a public station"
            )
        grouped_routes: dict[str, list[tuple[int, Route]]] = {}
        for route in solution.routes:
            base, trip_index = _parse_route_id(route.vehicle_id)
            if physical_vehicle_id(route.vehicle_id) != base:
                raise ValueError("route id has an ambiguous physical vehicle id")
            if (
                len(route.node_sequence) < 2
                or route.node_sequence[0] != route.home_depot_id
                or route.node_sequence[-1] != route.home_depot_id
            ):
                raise ValueError(
                    "Duty adapter requires a closed trip at its home depot"
                )
            grouped_routes.setdefault(base, []).append((trip_index, route))

        actions_by_base: dict[str, list[DutyChargingSession]] = {}
        for action in solution.charging_actions:
            base, trip_index = _parse_route_id(action.vehicle_id)
            actions_by_base.setdefault(base, []).append(
                DutyChargingSession(
                    trip_index=trip_index,
                    station_id=action.station_id,
                    energy_kwh=float(action.energy_kwh),
                    occupancy_minutes=float(action.occupancy_minutes),
                    charge_start_second=float(action.charge_start_second),
                    charge_day_offset=int(action.charge_day_offset),
                    start_energy_kwh=action.start_energy_kwh,
                    end_energy_kwh=action.end_energy_kwh,
                    charging_curve_id=action.charging_curve_id,
                    locked=action.vehicle_id in locked_routes,
                )
            )

        duties: list[PhysicalVehicleDuty] = []
        for base in sorted(grouped_routes):
            ordered = sorted(grouped_routes[base], key=lambda item: item[0])
            first = ordered[0][1]
            if any(
                route.vehicle_type.lower() != first.vehicle_type.lower()
                or route.home_depot_id != first.home_depot_id
                for _, route in ordered
            ):
                raise ValueError(
                    "one physical duty cannot mix vehicle types or home depots"
                )
            trips = tuple(
                DutyTrip(
                    trip_index,
                    tuple(
                        node_id
                        for node_id in route.node_sequence[1:-1]
                        if known_customers is None or node_id in known_customers
                    ),
                    tuple(prefixes.get(route.vehicle_id, ())),
                    tuple(route.node_sequence[1:-1]),
                )
                for trip_index, route in ordered
            )
            sessions = tuple(
                sorted(actions_by_base.get(base, ()), key=_session_key)
            )
            duties.append(
                PhysicalVehicleDuty(
                    physical_vehicle_id=base,
                    vehicle_type=first.vehicle_type,
                    home_depot_id=first.home_depot_id,
                    trips=trips,
                    charging_sessions=sessions,
                )
            )
        detached = set(actions_by_base).difference(grouped_routes)
        if detached:
            raise ValueError(
                "charging actions are detached from physical duties: "
                + ", ".join(sorted(detached))
            )
        return cls(
            duties=tuple(duties),
            unserved_customers=tuple(unserved_customers),
            source=source,
        )


def _parse_route_id(route_id: str) -> tuple[str, int]:
    if route_id.count("#T") != 1:
        raise ValueError(
            "Duty route id must be exactly CV_...#Tn or EV_...#Tn"
        )
    base, raw_index = route_id.rsplit("#T", 1)
    if not base.startswith(("CV_", "EV_")):
        raise ValueError(
            "Duty route id must be exactly CV_...#Tn or EV_...#Tn"
        )
    try:
        trip_index = int(raw_index)
    except ValueError as exc:
        raise ValueError("Duty route trip suffix must be an integer") from exc
    if trip_index < 1 or str(trip_index) != raw_index:
        raise ValueError("Duty route trip suffix must be a positive canonical integer")
    return base, trip_index


def _action_key(action: ChargingAction) -> tuple[object, ...]:
    return (
        action.vehicle_id,
        action.station_id,
        float(action.charge_start_second),
        float(action.energy_kwh),
        float(action.occupancy_minutes),
    )


def _session_key(session: DutyChargingSession) -> tuple[object, ...]:
    return (
        int(session.trip_index),
        session.station_id,
        float(session.charge_start_second),
        float(session.energy_kwh),
        float(session.occupancy_minutes),
    )


def assert_locks_preserved(
    reference: DutyIndividual,
    candidate: DutyIndividual,
) -> None:
    """Reject any candidate that changes a locked customer or charge decision."""

    reference_duties = {
        duty.physical_vehicle_id: duty for duty in reference.duties
    }
    candidate_duties = {
        duty.physical_vehicle_id: duty for duty in candidate.duties
    }
    for duty_id, reference_duty in reference_duties.items():
        candidate_duty = candidate_duties.get(duty_id)
        if candidate_duty is None:
            if any(trip.locked_customer_prefix for trip in reference_duty.trips):
                raise ValueError(f"candidate removed locked duty {duty_id!r}")
            if any(session.locked for session in reference_duty.charging_sessions):
                raise ValueError(f"candidate removed locked charging duty {duty_id!r}")
            continue
        candidate_trips = {
            int(trip.trip_index): trip for trip in candidate_duty.trips
        }
        for reference_trip in reference_duty.trips:
            prefix = reference_trip.locked_customer_prefix
            if not prefix:
                continue
            candidate_trip = candidate_trips.get(int(reference_trip.trip_index))
            if candidate_trip is None or (
                candidate_trip.customer_ids[: len(prefix)] != prefix
                or candidate_trip.locked_customer_prefix != prefix
            ):
                raise ValueError(
                    f"candidate changed locked prefix {duty_id}#T"
                    f"{reference_trip.trip_index}"
                )
        locked_sessions = tuple(
            session
            for session in reference_duty.charging_sessions
            if session.locked
        )
        candidate_locked = tuple(
            session
            for session in candidate_duty.charging_sessions
            if session.locked
        )
        if locked_sessions != candidate_locked:
            raise ValueError(f"candidate changed locked charging on {duty_id!r}")
