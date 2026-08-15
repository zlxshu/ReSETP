"""Problem-HGS decision objects and the fail-closed legacy Solution adapter.

v1 2026-08-07: represent one physical vehicle's complete ordered day and
preserve dynamic locks as sidecar metadata when crossing the legacy Solution
boundary.

v2 2026-08-07: add one fail-closed lock guard shared by crossover, repair, and
education so a Solution round trip cannot silently erase dynamic commitments.

v3 2026-08-07: refuse an ambiguous public-station decode when customer
identity was not supplied by the caller.

v4 2026-08-07: retain whether a physical asset already has a committed
dynamic history even when that history is kept outside the future candidate.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from functools import cached_property

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
class ScheduleAccountingVector:
    """Additive schedule-local quantities kept separate for Pareto search."""

    electricity_cost: float = 0.0
    emissions_kg: float = 0.0
    occupancy_cost: float = 0.0
    route_time_cost: float = 0.0

    def __post_init__(self) -> None:
        values = (
            float(self.electricity_cost),
            float(self.emissions_kg),
            float(self.occupancy_cost),
            float(self.route_time_cost),
        )
        if any(value < -1.0e-9 for value in values):
            raise ValueError("schedule accounting components cannot be negative")

    @property
    def dominance_components(self) -> tuple[float, ...]:
        return (
            float(self.electricity_cost),
            float(self.emissions_kg),
            float(self.occupancy_cost),
            float(self.route_time_cost),
        )


@dataclass(frozen=True)
class ScheduledTripWitness:
    """One fixed DutyTrip bound to an executable clock and battery state."""

    trip_index: int
    route_signature: str
    departure_second: float
    return_second: float
    start_soc_kwh: float | None
    end_soc_kwh: float | None

    def __post_init__(self) -> None:
        if int(self.trip_index) < 1:
            raise ValueError("scheduled trip index must start at 1")
        if not str(self.route_signature):
            raise ValueError("scheduled trip route signature cannot be empty")
        if float(self.return_second) < float(self.departure_second) - 1.0e-9:
            raise ValueError("scheduled trip returns before it departs")
        if (self.start_soc_kwh is None) != (self.end_soc_kwh is None):
            raise ValueError("scheduled trip SOC endpoints must both be set or absent")


@dataclass(frozen=True)
class ScheduledSOCPoint:
    """One endpoint in the continuous time--SOC execution ledger."""

    event_index: int
    event_kind: str
    trip_index: int
    node_id: str
    event_second: float
    soc_before_kwh: float
    soc_after_kwh: float

    def __post_init__(self) -> None:
        if int(self.event_index) < 0:
            raise ValueError("SOC event index cannot be negative")
        if int(self.trip_index) < 1:
            raise ValueError("SOC event trip index must start at 1")
        if not str(self.event_kind) or not str(self.node_id):
            raise ValueError("SOC event kind and node id cannot be empty")
        if min(float(self.soc_before_kwh), float(self.soc_after_kwh)) < -1.0e-7:
            raise ValueError("SOC event cannot leave the battery below zero")


@dataclass(frozen=True)
class ScheduledChargingSession:
    """One unambiguous pre-trip, inter-trip, or en-route charge witness."""

    relation: str
    after_trip_index: int | None
    before_trip_index: int | None
    route_trip_index: int | None
    station_id: str
    physical_station_id: str
    charge_start_second: float
    charge_end_second: float
    charge_day_offset: int
    start_energy_kwh: float
    end_energy_kwh: float
    energy_kwh: float
    occupancy_minutes: float
    charging_curve_id: str
    locked: bool = False

    def __post_init__(self) -> None:
        relation = str(self.relation).upper()
        object.__setattr__(self, "relation", relation)
        if relation not in {"BEFORE_FIRST", "BETWEEN_TRIPS", "EN_ROUTE"}:
            raise ValueError("unknown scheduled charging relation")
        if relation == "BEFORE_FIRST":
            valid = (
                self.after_trip_index is None
                and self.before_trip_index == 1
                and self.route_trip_index is None
            )
        elif relation == "BETWEEN_TRIPS":
            valid = (
                self.after_trip_index is not None
                and self.before_trip_index is not None
                and int(self.before_trip_index) == int(self.after_trip_index) + 1
                and self.route_trip_index is None
            )
        else:
            valid = (
                self.after_trip_index is None
                and self.before_trip_index is None
                and self.route_trip_index is not None
            )
        if not valid:
            raise ValueError("scheduled charging relation indices are inconsistent")
        if not str(self.station_id) or not str(self.physical_station_id):
            raise ValueError("scheduled charging station identity cannot be empty")
        if not str(self.charging_curve_id):
            raise ValueError("scheduled charging curve id cannot be empty")
        if float(self.energy_kwh) < -1.0e-9:
            raise ValueError("scheduled charging energy cannot be negative")
        if float(self.occupancy_minutes) < -1.0e-9:
            raise ValueError("scheduled charging occupancy cannot be negative")
        if abs(
            (float(self.end_energy_kwh) - float(self.start_energy_kwh))
            - float(self.energy_kwh)
        ) > 1.0e-7:
            raise ValueError("scheduled charging energy states do not close")
        if abs(
            (float(self.charge_end_second) - float(self.charge_start_second))
            - float(self.occupancy_minutes) * 60.0
        ) > 1.0e-6:
            raise ValueError("scheduled charging clock and occupancy do not close")

    @property
    def legacy_trip_index(self) -> int:
        if self.relation == "EN_ROUTE":
            assert self.route_trip_index is not None
            return int(self.route_trip_index)
        assert self.before_trip_index is not None
        return int(self.before_trip_index)

    def to_legacy(self) -> DutyChargingSession:
        """Return the sole compatibility projection used by legacy Solution."""

        return DutyChargingSession(
            trip_index=self.legacy_trip_index,
            station_id=self.station_id,
            energy_kwh=float(self.energy_kwh),
            occupancy_minutes=float(self.occupancy_minutes),
            charge_start_second=float(self.charge_start_second),
            charge_day_offset=int(self.charge_day_offset),
            start_energy_kwh=float(self.start_energy_kwh),
            end_energy_kwh=float(self.end_energy_kwh),
            charging_curve_id=self.charging_curve_id,
            locked=bool(self.locked),
        )


@dataclass(frozen=True)
class ScheduledDuty:
    """The single formal execution witness for one physical-vehicle duty."""

    physical_vehicle_id: str
    vehicle_type: str
    home_depot_id: str
    trip_witnesses: tuple[ScheduledTripWitness, ...]
    soc_points: tuple[ScheduledSOCPoint, ...]
    charging_sessions: tuple[ScheduledChargingSession, ...]
    occupancy_signature: tuple[tuple[str, int, int, str], ...]
    local_accounting_vector: ScheduleAccountingVector
    schedule_contract_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "vehicle_type", str(self.vehicle_type).lower())
        object.__setattr__(self, "trip_witnesses", tuple(self.trip_witnesses))
        object.__setattr__(self, "soc_points", tuple(self.soc_points))
        object.__setattr__(self, "charging_sessions", tuple(self.charging_sessions))
        object.__setattr__(
            self,
            "occupancy_signature",
            tuple(sorted(tuple(item) for item in self.occupancy_signature)),
        )
        indices = [int(item.trip_index) for item in self.trip_witnesses]
        if indices != list(range(1, len(indices) + 1)):
            raise ValueError("scheduled trip witnesses must be contiguous")
        event_indices = [int(item.event_index) for item in self.soc_points]
        if event_indices != list(range(len(event_indices))):
            raise ValueError("scheduled SOC event indices must be contiguous")
        for left, right in zip(self.soc_points, self.soc_points[1:]):
            if abs(float(left.soc_after_kwh) - float(right.soc_before_kwh)) > 1.0e-7:
                raise ValueError("scheduled SOC points do not form one continuous chain")
        digest = str(self.schedule_contract_sha256).lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("schedule contract identity must be a SHA-256 digest")

    @cached_property
    def schedule_fingerprint(self) -> str:
        payload = _canonical_identity(asdict(self))
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def legacy_charging_sessions(self) -> tuple[DutyChargingSession, ...]:
        return tuple(
            sorted(
                (session.to_legacy() for session in self.charging_sessions),
                key=_session_key,
            )
        )


@dataclass(frozen=True)
class PhysicalVehicleDuty:
    """All trips and charging decisions for one physical vehicle."""

    physical_vehicle_id: str
    vehicle_type: str
    home_depot_id: str
    trips: tuple[DutyTrip, ...]
    charging_sessions: tuple[DutyChargingSession, ...] = ()
    has_dynamic_commitment: bool = False
    schedule: ScheduledDuty | None = None

    def __post_init__(self) -> None:
        vehicle_type = str(self.vehicle_type).lower()
        object.__setattr__(self, "vehicle_type", vehicle_type)
        object.__setattr__(self, "trips", tuple(self.trips))
        object.__setattr__(
            self,
            "charging_sessions",
            tuple(self.charging_sessions),
        )
        object.__setattr__(
            self,
            "has_dynamic_commitment",
            bool(self.has_dynamic_commitment),
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
        if self.schedule is not None:
            schedule = self.schedule
            if (
                schedule.physical_vehicle_id != self.physical_vehicle_id
                or schedule.vehicle_type != self.vehicle_type
                or schedule.home_depot_id != self.home_depot_id
            ):
                raise ValueError("scheduled duty identity disagrees with its vehicle")
            if len(schedule.trip_witnesses) != len(self.trips):
                raise ValueError("scheduled duty trip count disagrees with structure")
            for trip, witness in zip(
                self.trips,
                schedule.trip_witnesses,
                strict=True,
            ):
                if (
                    int(trip.trip_index) != int(witness.trip_index)
                    or duty_trip_route_signature(trip) != witness.route_signature
                ):
                    raise ValueError("scheduled duty route identity disagrees with structure")
            projected = schedule.legacy_charging_sessions()
            if self.charging_sessions and self.charging_sessions != projected:
                raise ValueError(
                    "legacy charging sessions disagree with ScheduledDuty projection"
                )
            object.__setattr__(self, "charging_sessions", projected)

    def route_id(self, trip_index: int) -> str:
        return route_trip_vehicle_id(self.physical_vehicle_id, trip_index)

    @property
    def locked_charging_trip_indices(self) -> frozenset[int]:
        return frozenset(
            int(session.trip_index)
            for session in self.charging_sessions
            if session.locked
        )

    @cached_property
    def structure_fingerprint(self) -> str:
        payload = {
            "physical_vehicle_id": self.physical_vehicle_id,
            "vehicle_type": self.vehicle_type,
            "home_depot_id": self.home_depot_id,
            "trips": [asdict(trip) for trip in self.trips],
            "has_dynamic_commitment": bool(self.has_dynamic_commitment),
        }
        encoded = json.dumps(
            _canonical_identity(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class DutyIndividual:
    """One complete Problem-HGS candidate before full-model evaluation."""

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

    @cached_property
    def fingerprint(self) -> str:
        duty_payloads = []
        for duty in self.duties:
            payload = asdict(duty)
            if duty.schedule is None:
                # Preserve every legacy A0 fingerprint until the Oracle is
                # explicitly attached in the later integration steps.
                payload.pop("schedule", None)
            else:
                payload["schedule"] = _canonical_identity(payload["schedule"])
            duty_payloads.append(payload)
        payload = {
            "version": int(self.version),
            "duties": duty_payloads,
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


def duty_trip_route_signature(trip: DutyTrip) -> str:
    """Return the structure-only identity bound into a trip witness."""

    encoded = json.dumps(
        {
            "trip_index": int(trip.trip_index),
            "customer_ids": list(trip.customer_ids),
            "locked_customer_prefix": list(trip.locked_customer_prefix),
            "route_visits": list(trip.effective_route_visits),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_identity(value):
    """Use IEEE-754 hexadecimal strings for schedule identity floats."""

    if isinstance(value, float):
        return {"float_hex": float(value).hex()}
    if isinstance(value, dict):
        return {
            str(key): _canonical_identity(item)
            for key, item in sorted(value.items(), key=lambda row: str(row[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_identity(item) for item in value]
    return value


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
            if reference_duty.has_dynamic_commitment:
                raise ValueError(f"candidate removed committed duty {duty_id!r}")
            if any(trip.locked_customer_prefix for trip in reference_duty.trips):
                raise ValueError(f"candidate removed locked duty {duty_id!r}")
            if any(session.locked for session in reference_duty.charging_sessions):
                raise ValueError(f"candidate removed locked charging duty {duty_id!r}")
            continue
        if (
            candidate_duty.has_dynamic_commitment
            != reference_duty.has_dynamic_commitment
        ):
            raise ValueError(
                f"candidate changed dynamic commitment on {duty_id!r}"
            )
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
