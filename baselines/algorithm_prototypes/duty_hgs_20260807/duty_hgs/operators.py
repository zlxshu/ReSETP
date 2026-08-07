"""Duty-level and problem-specific neighbourhood actions.

v1 2026-08-07: implement the approved relocate, swap, 2-opt, cross-trip,
mixed-fleet, cross-depot/fairness, trip-opening, and charging-retiming channels.
No proxy score accepts a move; the full evaluator decides every comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from setp_solver.instance_loader import Instance

from .evaluation import FullEvaluation
from .model import DutyIndividual, DutyTrip, PhysicalVehicleDuty


class DutyMove(Protocol):
    action_id: str
    channel: str

    @property
    def changed_duty_ids(self) -> frozenset[str]: ...

    def apply(self, individual: DutyIndividual) -> DutyIndividual: ...


@dataclass(frozen=True)
class RelocateMove:
    action_id: str
    channel: str
    source_duty_id: str
    source_trip_index: int
    customer_id: str
    target_duty_id: str
    target_trip_index: int
    target_position: int

    @property
    def changed_duty_ids(self) -> frozenset[str]:
        return frozenset({self.source_duty_id, self.target_duty_id})

    def apply(self, individual: DutyIndividual) -> DutyIndividual:
        source_duty, source_trip = _duty_trip(
            individual,
            self.source_duty_id,
            self.source_trip_index,
        )
        target_duty, target_trip = _duty_trip(
            individual,
            self.target_duty_id,
            self.target_trip_index,
        )
        if (self.source_duty_id, self.source_trip_index) == (
            self.target_duty_id,
            self.target_trip_index,
        ):
            raise ValueError("relocate source and target must differ")
        source = list(source_trip.customer_ids)
        target = list(target_trip.customer_ids)
        try:
            source_position = source.index(self.customer_id)
        except ValueError as exc:
            raise ValueError("relocate customer is absent from source") from exc
        _assert_position_unlocked(source_duty, source_trip, source_position)
        _assert_insert_unlocked(target_duty, target_trip, self.target_position)
        source.pop(source_position)
        target.insert(self.target_position, self.customer_id)
        replacements = {
            (self.source_duty_id, self.source_trip_index): tuple(source),
            (self.target_duty_id, self.target_trip_index): tuple(target),
        }
        return _replace_trip_customers(
            individual,
            replacements,
            source=f"{self.channel}:{self.action_id}",
        )


@dataclass(frozen=True)
class SwapMove:
    action_id: str
    channel: str
    left_duty_id: str
    left_trip_index: int
    left_customer_id: str
    right_duty_id: str
    right_trip_index: int
    right_customer_id: str

    @property
    def changed_duty_ids(self) -> frozenset[str]:
        return frozenset({self.left_duty_id, self.right_duty_id})

    def apply(self, individual: DutyIndividual) -> DutyIndividual:
        left_duty, left_trip = _duty_trip(
            individual,
            self.left_duty_id,
            self.left_trip_index,
        )
        right_duty, right_trip = _duty_trip(
            individual,
            self.right_duty_id,
            self.right_trip_index,
        )
        if (self.left_duty_id, self.left_trip_index) == (
            self.right_duty_id,
            self.right_trip_index,
        ):
            raise ValueError("swap requires two distinct trips")
        left = list(left_trip.customer_ids)
        right = list(right_trip.customer_ids)
        try:
            left_position = left.index(self.left_customer_id)
            right_position = right.index(self.right_customer_id)
        except ValueError as exc:
            raise ValueError("swap customer is absent from its source") from exc
        _assert_position_unlocked(left_duty, left_trip, left_position)
        _assert_position_unlocked(right_duty, right_trip, right_position)
        left[left_position], right[right_position] = (
            right[right_position],
            left[left_position],
        )
        return _replace_trip_customers(
            individual,
            {
                (self.left_duty_id, self.left_trip_index): tuple(left),
                (self.right_duty_id, self.right_trip_index): tuple(right),
            },
            source=f"{self.channel}:{self.action_id}",
        )


@dataclass(frozen=True)
class ReverseSegmentMove:
    action_id: str
    channel: str
    duty_id: str
    trip_index: int
    start: int
    stop: int

    @property
    def changed_duty_ids(self) -> frozenset[str]:
        return frozenset({self.duty_id})

    def apply(self, individual: DutyIndividual) -> DutyIndividual:
        duty, trip = _duty_trip(individual, self.duty_id, self.trip_index)
        if self.start < len(trip.locked_customer_prefix):
            raise ValueError("2-opt cannot change a locked prefix")
        if self.start < 0 or self.stop > len(trip.customer_ids):
            raise ValueError("2-opt segment is outside the trip")
        if self.stop - self.start < 2:
            raise ValueError("2-opt segment must contain two customers")
        if self.trip_index in duty.locked_charging_trip_indices:
            raise ValueError("2-opt cannot change a trip with locked charging")
        customers = list(trip.customer_ids)
        customers[self.start : self.stop] = reversed(
            customers[self.start : self.stop]
        )
        return _replace_trip_customers(
            individual,
            {(self.duty_id, self.trip_index): tuple(customers)},
            source=f"{self.channel}:{self.action_id}",
        )


@dataclass(frozen=True)
class OpenTripMove:
    action_id: str
    channel: str
    duty_id: str
    source_trip_index: int
    customer_id: str
    new_trip_index: int

    @property
    def changed_duty_ids(self) -> frozenset[str]:
        return frozenset({self.duty_id})

    def apply(self, individual: DutyIndividual) -> DutyIndividual:
        duty, source_trip = _duty_trip(
            individual,
            self.duty_id,
            self.source_trip_index,
        )
        source = list(source_trip.customer_ids)
        try:
            position = source.index(self.customer_id)
        except ValueError as exc:
            raise ValueError("trip-opening customer is absent") from exc
        _assert_position_unlocked(duty, source_trip, position)
        if len(source) == 1:
            raise ValueError("trip opening cannot leave an empty source trip")
        source.pop(position)
        if not 1 <= self.new_trip_index <= len(duty.trips) + 1:
            raise ValueError("new trip index is outside the duty chain")
        locked_indices = duty.locked_charging_trip_indices
        if locked_indices and self.new_trip_index <= max(locked_indices):
            raise ValueError("new trip cannot renumber a locked charging trip")
        rows: list[tuple[int | None, DutyTrip]] = [
            (
                trip.trip_index,
                replace(
                    trip,
                    customer_ids=(
                        tuple(source)
                        if trip.trip_index == self.source_trip_index
                        else trip.customer_ids
                    ),
                    route_visits=(
                        ()
                        if trip.trip_index == self.source_trip_index
                        else trip.route_visits
                    ),
                ),
            )
            for trip in duty.trips
        ]
        rows.insert(
            self.new_trip_index - 1,
            (None, DutyTrip(1, (self.customer_id,))),
        )
        rebuilt_trips = tuple(
            replace(trip, trip_index=index)
            for index, (_, trip) in enumerate(rows, start=1)
        )
        locked_sessions = tuple(
            session
            for session in duty.charging_sessions
            if session.locked
        )
        rebuilt_duty = replace(
            duty,
            trips=rebuilt_trips,
            charging_sessions=locked_sessions,
        )
        return replace(
            individual,
            duties=tuple(
                rebuilt_duty if item.physical_vehicle_id == self.duty_id else item
                for item in individual.duties
            ),
            source=f"{self.channel}:{self.action_id}",
        )


@dataclass(frozen=True)
class ChargingRetimeMove:
    action_id: str
    channel: str
    duty_id: str

    @property
    def changed_duty_ids(self) -> frozenset[str]:
        return frozenset({self.duty_id})

    def apply(self, individual: DutyIndividual) -> DutyIndividual:
        duty = _duty(individual, self.duty_id)
        if duty.vehicle_type != "ev":
            raise ValueError("charging retiming requires an EV duty")
        retained = tuple(
            session for session in duty.charging_sessions if session.locked
        )
        rebuilt = replace(duty, charging_sessions=retained)
        return replace(
            individual,
            duties=tuple(
                rebuilt if item.physical_vehicle_id == self.duty_id else item
                for item in individual.duties
            ),
            source=f"{self.channel}:{self.action_id}",
        )


@dataclass(frozen=True)
class InsertUnservedMove:
    action_id: str
    channel: str
    customer_id: str
    target_duty_id: str
    target_trip_index: int | None
    target_position: int

    @property
    def changed_duty_ids(self) -> frozenset[str]:
        return frozenset({self.target_duty_id})

    def apply(self, individual: DutyIndividual) -> DutyIndividual:
        if self.customer_id not in individual.unserved_customers:
            raise ValueError("repair customer is not marked unserved")
        duty = _duty(individual, self.target_duty_id)
        if self.target_trip_index is None:
            if self.target_position != 0:
                raise ValueError("new-trip insertion position must be zero")
            rebuilt = replace(
                duty,
                trips=duty.trips
                + (DutyTrip(len(duty.trips) + 1, (self.customer_id,)),),
            )
        else:
            _, trip = _duty_trip(
                individual,
                self.target_duty_id,
                self.target_trip_index,
            )
            _assert_insert_unlocked(duty, trip, self.target_position)
            customers = list(trip.customer_ids)
            customers.insert(self.target_position, self.customer_id)
            rebuilt = replace(
                duty,
                trips=tuple(
                    replace(
                        item,
                        customer_ids=(
                            tuple(customers)
                            if item.trip_index == self.target_trip_index
                            else item.customer_ids
                        ),
                        route_visits=(
                            ()
                            if item.trip_index == self.target_trip_index
                            else item.route_visits
                        ),
                    )
                    for item in duty.trips
                ),
            )
        return replace(
            individual,
            duties=tuple(
                rebuilt
                if item.physical_vehicle_id == self.target_duty_id
                else item
                for item in individual.duties
            ),
            unserved_customers=tuple(
                customer
                for customer in individual.unserved_customers
                if customer != self.customer_id
            ),
            source=f"{self.channel}:{self.action_id}",
        )
def generate_problem_moves(
    individual: DutyIndividual,
    evaluation: FullEvaluation,
    instance: Instance,
) -> tuple[DutyMove, ...]:
    """Generate the complete approved neighbourhood without proxy acceptance."""

    del instance  # Full evaluation, not a local proxy, compares the candidates.
    deficient_depots = {
        depot_id
        for depot_id, margin in evaluation.participation_margin.items()
        if float(margin) < 0.0
    }
    moves: list[DutyMove] = []
    trip_rows = [
        (duty, trip)
        for duty in individual.duties
        for trip in duty.trips
    ]
    for source_duty, source_trip in trip_rows:
        unlocked = source_trip.customer_ids[
            len(source_trip.locked_customer_prefix) :
        ]
        for customer_id in unlocked:
            for target_duty, target_trip in trip_rows:
                if (
                    source_duty.physical_vehicle_id
                    == target_duty.physical_vehicle_id
                    and source_trip.trip_index == target_trip.trip_index
                ):
                    continue
                channel = _relation_channel(
                    source_duty,
                    target_duty,
                    deficient_depots,
                )
                for position in range(
                    len(target_trip.locked_customer_prefix),
                    len(target_trip.customer_ids) + 1,
                ):
                    moves.append(
                        RelocateMove(
                            action_id=(
                                f"relocate:{source_duty.physical_vehicle_id}"
                                f"#T{source_trip.trip_index}:{customer_id}->"
                                f"{target_duty.physical_vehicle_id}"
                                f"#T{target_trip.trip_index}@{position}"
                            ),
                            channel=channel,
                            source_duty_id=source_duty.physical_vehicle_id,
                            source_trip_index=source_trip.trip_index,
                            customer_id=customer_id,
                            target_duty_id=target_duty.physical_vehicle_id,
                            target_trip_index=target_trip.trip_index,
                            target_position=position,
                        )
                    )
            if len(source_trip.customer_ids) > 1:
                first_unlocked_index = (
                    max(source_duty.locked_charging_trip_indices, default=0)
                    + 1
                )
                for new_trip_index in range(
                    first_unlocked_index,
                    len(source_duty.trips) + 2,
                ):
                    moves.append(
                        OpenTripMove(
                            action_id=(
                                f"open-trip:{source_duty.physical_vehicle_id}"
                                f"#T{source_trip.trip_index}:{customer_id}"
                                f"@T{new_trip_index}"
                            ),
                            channel="multi_trip",
                            duty_id=source_duty.physical_vehicle_id,
                            source_trip_index=source_trip.trip_index,
                            customer_id=customer_id,
                            new_trip_index=new_trip_index,
                        )
                    )

    for left_index, (left_duty, left_trip) in enumerate(trip_rows):
        for right_duty, right_trip in trip_rows[left_index + 1 :]:
            channel = _relation_channel(
                left_duty,
                right_duty,
                deficient_depots,
            )
            for left_customer in left_trip.customer_ids[
                len(left_trip.locked_customer_prefix) :
            ]:
                for right_customer in right_trip.customer_ids[
                    len(right_trip.locked_customer_prefix) :
                ]:
                    moves.append(
                        SwapMove(
                            action_id=(
                                f"swap:{left_duty.physical_vehicle_id}"
                                f"#T{left_trip.trip_index}:{left_customer}<->"
                                f"{right_duty.physical_vehicle_id}"
                                f"#T{right_trip.trip_index}:{right_customer}"
                            ),
                            channel=channel,
                            left_duty_id=left_duty.physical_vehicle_id,
                            left_trip_index=left_trip.trip_index,
                            left_customer_id=left_customer,
                            right_duty_id=right_duty.physical_vehicle_id,
                            right_trip_index=right_trip.trip_index,
                            right_customer_id=right_customer,
                        )
                    )

    for duty, trip in trip_rows:
        start_min = len(trip.locked_customer_prefix)
        for start in range(start_min, len(trip.customer_ids) - 1):
            for stop in range(start + 2, len(trip.customer_ids) + 1):
                moves.append(
                    ReverseSegmentMove(
                        action_id=(
                            f"2opt:{duty.physical_vehicle_id}"
                            f"#T{trip.trip_index}@{start}:{stop}"
                        ),
                        channel="route_order",
                        duty_id=duty.physical_vehicle_id,
                        trip_index=trip.trip_index,
                        start=start,
                        stop=stop,
                    )
                )
    for duty in individual.duties:
        if duty.vehicle_type == "ev":
            moves.append(
                ChargingRetimeMove(
                    action_id=f"retime:{duty.physical_vehicle_id}",
                    channel="time_varying_carbon_charge",
                    duty_id=duty.physical_vehicle_id,
                )
            )
    return tuple(moves)


def _relation_channel(
    source: PhysicalVehicleDuty,
    target: PhysicalVehicleDuty,
    deficient_depots: set[str],
) -> str:
    if source.home_depot_id != target.home_depot_id:
        if deficient_depots.intersection(
            {source.home_depot_id, target.home_depot_id}
        ):
            return "fairness_cross_depot"
        return "depot_collaboration"
    if source.vehicle_type != target.vehicle_type:
        return "mixed_fleet"
    if source.physical_vehicle_id == target.physical_vehicle_id:
        return "multi_trip"
    return "relocate"


def _replace_trip_customers(
    individual: DutyIndividual,
    replacements: dict[tuple[str, int], tuple[str, ...]],
    *,
    source: str,
) -> DutyIndividual:
    changed_duty_ids = {duty_id for duty_id, _trip_index in replacements}
    duties = []
    for duty in individual.duties:
        if duty.physical_vehicle_id not in changed_duty_ids:
            duties.append(duty)
            continue
        duties.append(
            compact_empty_trips(
                replace(
                    duty,
                    trips=tuple(
                        replace(
                            trip,
                            customer_ids=replacements.get(
                                (duty.physical_vehicle_id, trip.trip_index),
                                trip.customer_ids,
                            ),
                            route_visits=(
                                ()
                                if (
                                    duty.physical_vehicle_id,
                                    trip.trip_index,
                                )
                                in replacements
                                else trip.route_visits
                            ),
                        )
                        for trip in duty.trips
                    ),
                )
            )
        )
    return replace(individual, duties=duties, source=source)


def compact_empty_trips(duty: PhysicalVehicleDuty) -> PhysicalVehicleDuty:
    """Remove unlocked empty trips without leaving phantom routes or charges."""

    retained = [trip for trip in duty.trips if trip.customer_ids]
    old_to_new = {
        int(trip.trip_index): index
        for index, trip in enumerate(retained, start=1)
    }
    for locked_index in duty.locked_charging_trip_indices:
        if old_to_new.get(locked_index) != locked_index:
            raise ValueError("trip compaction cannot renumber locked charging")
    trips = tuple(
        replace(trip, trip_index=index)
        for index, trip in enumerate(retained, start=1)
    )
    locked_sessions = tuple(
        session for session in duty.charging_sessions if session.locked
    )
    return replace(
        duty,
        trips=trips,
        charging_sessions=locked_sessions,
    )


def _assert_position_unlocked(
    duty: PhysicalVehicleDuty,
    trip: DutyTrip,
    position: int,
) -> None:
    if position < len(trip.locked_customer_prefix):
        raise ValueError("move cannot change a locked customer prefix")
    if trip.trip_index in duty.locked_charging_trip_indices:
        raise ValueError("move cannot change a trip with locked charging")


def _assert_insert_unlocked(
    duty: PhysicalVehicleDuty,
    trip: DutyTrip,
    position: int,
) -> None:
    if position < len(trip.locked_customer_prefix):
        raise ValueError("move cannot insert inside a locked prefix")
    if position > len(trip.customer_ids):
        raise ValueError("move insertion position is outside the trip")
    if trip.trip_index in duty.locked_charging_trip_indices:
        raise ValueError("move cannot change a trip with locked charging")


def _duty_trip(
    individual: DutyIndividual,
    duty_id: str,
    trip_index: int,
) -> tuple[PhysicalVehicleDuty, DutyTrip]:
    duty = _duty(individual, duty_id)
    try:
        trip = next(
            trip
            for trip in duty.trips
            if int(trip.trip_index) == int(trip_index)
        )
    except StopIteration as exc:
        raise ValueError(f"unknown trip {duty_id}#T{trip_index}") from exc
    return duty, trip


def _duty(
    individual: DutyIndividual,
    duty_id: str,
) -> PhysicalVehicleDuty:
    try:
        return next(
            duty
            for duty in individual.duties
            if duty.physical_vehicle_id == duty_id
        )
    except StopIteration as exc:
        raise ValueError(f"unknown duty {duty_id!r}") from exc
