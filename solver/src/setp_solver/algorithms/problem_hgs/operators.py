"""Duty-level and problem-specific neighbourhood actions.

v1 2026-08-07: implement the approved relocate, swap, 2-opt, cross-trip,
mixed-fleet, cross-depot/fairness, trip-opening, and charging-retiming channels.
No proxy score accepts a move; the full evaluator decides every comparison.

v2 2026-08-07: add the user-approved whole-duty EV/CV task exchange.  Vehicle
identity, type, depot, fleet registration, and dynamic commitments stay fixed;
the existing nonlinear charging repair rebuilds the exchanged EV duty.

v3 2026-08-08: add the route operators missing from the first prototype:
Or-opt segment relocation, cross-route tail exchange (2-opt*), and whole-trip
two-way exchange.  They still modify the canonical physical-vehicle Duty and
remain subject to the same charging rebuild and complete-model acceptance.

v4 2026-08-08: add the fixed-fleet analogue of Hiermann et al.'s
ShiftAndResize neighbourhood: shift one customer within an EV/CV pair, exchange
the resulting task chains between the two physical vehicle slots, and let the
existing exact charging reconstruction rebuild the new EV duty.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from setp_solver.instance_loader import Instance

from .evaluation import FullEvaluation
from .model import (
    DutyChargingSession,
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)


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
class RelocateSegmentMove:
    """Move one consecutive customer segment between two distinct trips."""

    action_id: str
    channel: str
    source_duty_id: str
    source_trip_index: int
    start: int
    stop: int
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
            raise ValueError("segment relocation requires two distinct trips")
        if self.stop - self.start < 2:
            raise ValueError("Or-opt segment must contain at least two customers")
        if self.start < 0 or self.stop > len(source_trip.customer_ids):
            raise ValueError("Or-opt source segment is outside the trip")
        _assert_position_unlocked(source_duty, source_trip, self.start)
        if source_trip.trip_index in source_duty.locked_charging_trip_indices:
            raise ValueError("Or-opt cannot change a trip with locked charging")
        _assert_insert_unlocked(target_duty, target_trip, self.target_position)
        source = list(source_trip.customer_ids)
        segment = source[self.start : self.stop]
        del source[self.start : self.stop]
        target = list(target_trip.customer_ids)
        target[self.target_position : self.target_position] = segment
        return _replace_trip_customers(
            individual,
            {
                (self.source_duty_id, self.source_trip_index): tuple(source),
                (self.target_duty_id, self.target_trip_index): tuple(target),
            },
            source=f"{self.channel}:{self.action_id}",
        )


@dataclass(frozen=True)
class SwapTailsMove:
    """Exchange two unlocked route suffixes (the standard 2-opt* action)."""

    action_id: str
    channel: str
    left_duty_id: str
    left_trip_index: int
    left_cut: int
    right_duty_id: str
    right_trip_index: int
    right_cut: int

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
            raise ValueError("2-opt* requires two distinct trips")
        _assert_insert_unlocked(left_duty, left_trip, self.left_cut)
        _assert_insert_unlocked(right_duty, right_trip, self.right_cut)
        left_prefix = left_trip.customer_ids[: self.left_cut]
        right_prefix = right_trip.customer_ids[: self.right_cut]
        left = left_prefix + right_trip.customer_ids[self.right_cut :]
        right = right_prefix + left_trip.customer_ids[self.left_cut :]
        if left == left_trip.customer_ids and right == right_trip.customer_ids:
            raise ValueError("2-opt* must change at least one route")
        return _replace_trip_customers(
            individual,
            {
                (self.left_duty_id, self.left_trip_index): tuple(left),
                (self.right_duty_id, self.right_trip_index): tuple(right),
            },
            source=f"{self.channel}:{self.action_id}",
        )


@dataclass(frozen=True)
class WholeTripExchangeMove:
    """Exchange complete unlocked trips while preserving both vehicle slots."""

    action_id: str
    channel: str
    left_duty_id: str
    left_trip_index: int
    right_duty_id: str
    right_trip_index: int

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
            raise ValueError("whole-trip exchange requires two distinct trips")
        if left_trip.customer_ids == right_trip.customer_ids:
            raise ValueError("whole-trip exchange requires different trips")
        _assert_trip_fully_unlocked(left_duty, left_trip)
        _assert_trip_fully_unlocked(right_duty, right_trip)
        return _replace_trip_customers(
            individual,
            {
                (self.left_duty_id, self.left_trip_index): right_trip.customer_ids,
                (self.right_duty_id, self.right_trip_index): left_trip.customer_ids,
            },
            source=f"{self.channel}:{self.action_id}",
        )


@dataclass(frozen=True)
class DutySkeletonMove:
    """Replace complete task chains while preserving physical-asset slots."""

    action_id: str
    channel: str
    replacements: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]
    dynamic_future_only: bool = False

    @property
    def changed_duty_ids(self) -> frozenset[str]:
        return frozenset(duty_id for duty_id, _chain in self.replacements)

    def apply(self, individual: DutyIndividual) -> DutyIndividual:
        customer_universe = {
            customer
            for duty in individual.duties
            for trip in duty.trips
            for customer in trip.customer_ids
        }.union(individual.unserved_customers)
        replacement_by_id = dict(self.replacements)
        if len(replacement_by_id) != len(self.replacements):
            raise ValueError("Duty skeleton replacement repeats a vehicle id")
        unknown = self.changed_duty_ids.difference(
            duty.physical_vehicle_id for duty in individual.duties
        )
        if unknown:
            raise ValueError(
                f"Duty skeleton replacement has unknown assets {sorted(unknown)}"
            )
        rebuilt = []
        for duty in individual.duties:
            chain = replacement_by_id.get(duty.physical_vehicle_id)
            if chain is None:
                rebuilt.append(duty)
                continue
            if _duty_has_locks(duty) and not (
                self.dynamic_future_only
                and duty.has_dynamic_commitment
                and not any(
                    trip.locked_customer_prefix for trip in duty.trips
                )
                and not any(
                    session.locked for session in duty.charging_sessions
                )
            ):
                raise ValueError("Duty skeleton cannot change a locked duty")
            rebuilt.append(
                replace(
                    duty,
                    trips=tuple(
                        DutyTrip(index, tuple(customers))
                        for index, customers in enumerate(chain, start=1)
                        if customers
                    ),
                    charging_sessions=(),
                )
            )
        rebuilt_customers = {
            customer
            for duty in rebuilt
            for trip in duty.trips
            for customer in trip.customer_ids
        }
        introduced = rebuilt_customers.difference(customer_universe)
        if introduced:
            raise ValueError(
                "Duty skeleton introduced customers outside the candidate "
                f"universe: {sorted(introduced)}"
            )
        return replace(
            individual,
            duties=tuple(rebuilt),
            unserved_customers=tuple(
                sorted(customer_universe.difference(rebuilt_customers))
            ),
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
class ChargingScheduleMove:
    """Install one explicit, already certified whole-duty charging schedule."""

    action_id: str
    channel: str
    duty_id: str
    charging_sessions: tuple[DutyChargingSession, ...]
    route_visits_by_trip: tuple[tuple[int, tuple[str, ...]], ...]

    @property
    def changed_duty_ids(self) -> frozenset[str]:
        return frozenset({self.duty_id})

    @property
    def explicit_charging_duty_ids(self) -> frozenset[str]:
        return self.changed_duty_ids

    def apply(self, individual: DutyIndividual) -> DutyIndividual:
        duty = _duty(individual, self.duty_id)
        if duty.vehicle_type != "ev":
            raise ValueError("explicit charging schedule requires an EV duty")
        visits = dict(self.route_visits_by_trip)
        if set(visits) != {trip.trip_index for trip in duty.trips}:
            raise ValueError("charging schedule must cover every duty trip")
        rebuilt = replace(
            duty,
            trips=tuple(
                replace(trip, route_visits=visits[trip.trip_index])
                for trip in duty.trips
            ),
            charging_sessions=tuple(self.charging_sessions),
        )
        return replace(
            individual,
            duties=tuple(
                rebuilt if item.physical_vehicle_id == self.duty_id else item
                for item in individual.duties
            ),
            source=f"{self.channel}:{self.action_id}",
        )


@dataclass(frozen=True)
class WholeDutyTypeExchangeMove:
    """Exchange complete unlocked task chains between same-depot EV/CV duties."""

    action_id: str
    channel: str
    left_duty_id: str
    right_duty_id: str

    @property
    def changed_duty_ids(self) -> frozenset[str]:
        return frozenset({self.left_duty_id, self.right_duty_id})

    def apply(self, individual: DutyIndividual) -> DutyIndividual:
        if self.left_duty_id == self.right_duty_id:
            raise ValueError("whole-duty exchange requires two distinct duties")
        left = _duty(individual, self.left_duty_id)
        right = _duty(individual, self.right_duty_id)
        if left.home_depot_id != right.home_depot_id:
            raise ValueError("whole-duty exchange requires one home depot")
        if {left.vehicle_type, right.vehicle_type} != {"ev", "cv"}:
            raise ValueError("whole-duty exchange requires one EV and one CV")
        if _duty_has_locks(left) or _duty_has_locks(right):
            raise ValueError("whole-duty exchange cannot change a locked duty")
        if _task_chain(left) == _task_chain(right):
            raise ValueError("whole-duty exchange requires different task chains")

        rebuilt_left = replace(
            left,
            trips=_unlocked_task_chain(right),
            charging_sessions=(),
        )
        rebuilt_right = replace(
            right,
            trips=_unlocked_task_chain(left),
            charging_sessions=(),
        )
        return replace(
            individual,
            duties=tuple(
                rebuilt_left
                if duty.physical_vehicle_id == self.left_duty_id
                else rebuilt_right
                if duty.physical_vehicle_id == self.right_duty_id
                else duty
                for duty in individual.duties
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


@dataclass(frozen=True)
class ExchangeUnservedMove:
    """Place a new order by ejecting one unlocked future customer.

    The ejected customer stays explicit in ``unserved_customers`` so the
    standard exact regret repair can reinsert it elsewhere.  This is the
    one-ejection building block used when a late disclosure has no direct
    feasible insertion.
    """

    action_id: str
    channel: str
    duty_id: str
    trip_index: int
    served_customer_id: str
    unserved_customer_id: str

    @property
    def changed_duty_ids(self) -> frozenset[str]:
        return frozenset({self.duty_id})

    def apply(self, individual: DutyIndividual) -> DutyIndividual:
        if self.unserved_customer_id not in individual.unserved_customers:
            raise ValueError("exchange customer is not marked unserved")
        duty, trip = _duty_trip(individual, self.duty_id, self.trip_index)
        customers = list(trip.customer_ids)
        try:
            position = customers.index(self.served_customer_id)
        except ValueError as exc:
            raise ValueError("ejected customer is absent from its trip") from exc
        _assert_position_unlocked(duty, trip, position)
        if trip.trip_index in duty.locked_charging_trip_indices:
            raise ValueError("cannot eject from a trip with locked charging")
        customers[position] = self.unserved_customer_id
        rebuilt_duty = replace(
            duty,
            trips=tuple(
                replace(
                    item,
                    customer_ids=(
                        tuple(customers)
                        if item.trip_index == self.trip_index
                        else item.customer_ids
                    ),
                    route_visits=(
                        ()
                        if item.trip_index == self.trip_index
                        else item.route_visits
                    ),
                )
                for item in duty.trips
            ),
        )
        return replace(
            individual,
            duties=tuple(
                rebuilt_duty
                if item.physical_vehicle_id == self.duty_id
                else item
                for item in individual.duties
            ),
            unserved_customers=(
                *(
                    customer
                    for customer in individual.unserved_customers
                    if customer != self.unserved_customer_id
                ),
                self.served_customer_id,
            ),
            source=f"{self.channel}:{self.action_id}",
        )


def generate_problem_moves(
    individual: DutyIndividual,
    evaluation: FullEvaluation,
    instance: Instance,
    *,
    include_whole_duty_type_exchange: bool = True,
    include_exhaustive_strong_route_moves: bool = False,
) -> tuple[DutyMove, ...]:
    """Generate the legacy neighbourhood and optional strong route actions.

    The stronger route actions are available here for equivalence tests and
    small technical probes.  Production search supplies them through a route
    proposal engine instead of multiplying the Python full-model enumeration.
    """

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

            if include_exhaustive_strong_route_moves and (
                left_trip.customer_ids
                and right_trip.customer_ids
                and not left_trip.locked_customer_prefix
                and not right_trip.locked_customer_prefix
                and left_trip.trip_index
                not in left_duty.locked_charging_trip_indices
                and right_trip.trip_index
                not in right_duty.locked_charging_trip_indices
            ):
                moves.append(
                    WholeTripExchangeMove(
                        action_id=(
                            f"whole-trip-exchange:"
                            f"{left_duty.physical_vehicle_id}#T{left_trip.trip_index}<->"
                            f"{right_duty.physical_vehicle_id}#T{right_trip.trip_index}"
                        ),
                        channel=(
                            "fairness_cross_depot"
                            if left_duty.home_depot_id != right_duty.home_depot_id
                            else "multi_trip"
                        ),
                        left_duty_id=left_duty.physical_vehicle_id,
                        left_trip_index=left_trip.trip_index,
                        right_duty_id=right_duty.physical_vehicle_id,
                        right_trip_index=right_trip.trip_index,
                    )
                )

            for left_cut in (
                range(
                    len(left_trip.locked_customer_prefix),
                    len(left_trip.customer_ids) + 1,
                )
                if include_exhaustive_strong_route_moves
                else ()
            ):
                for right_cut in range(
                    len(right_trip.locked_customer_prefix),
                    len(right_trip.customer_ids) + 1,
                ):
                    left_after = (
                        left_trip.customer_ids[:left_cut]
                        + right_trip.customer_ids[right_cut:]
                    )
                    right_after = (
                        right_trip.customer_ids[:right_cut]
                        + left_trip.customer_ids[left_cut:]
                    )
                    if (
                        left_after == left_trip.customer_ids
                        and right_after == right_trip.customer_ids
                    ):
                        continue
                    moves.append(
                        SwapTailsMove(
                            action_id=(
                                f"2opt-star:{left_duty.physical_vehicle_id}"
                                f"#T{left_trip.trip_index}@{left_cut}<->"
                                f"{right_duty.physical_vehicle_id}"
                                f"#T{right_trip.trip_index}@{right_cut}"
                            ),
                            channel=channel,
                            left_duty_id=left_duty.physical_vehicle_id,
                            left_trip_index=left_trip.trip_index,
                            left_cut=left_cut,
                            right_duty_id=right_duty.physical_vehicle_id,
                            right_trip_index=right_trip.trip_index,
                            right_cut=right_cut,
                        )
                    )

    for source_duty, source_trip in (
        trip_rows if include_exhaustive_strong_route_moves else ()
    ):
        start_min = len(source_trip.locked_customer_prefix)
        for start in range(start_min, len(source_trip.customer_ids) - 1):
            for stop in range(start + 2, len(source_trip.customer_ids) + 1):
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
                            RelocateSegmentMove(
                                action_id=(
                                    f"or-opt:{source_duty.physical_vehicle_id}"
                                    f"#T{source_trip.trip_index}@{start}:{stop}->"
                                    f"{target_duty.physical_vehicle_id}"
                                    f"#T{target_trip.trip_index}@{position}"
                                ),
                                channel=channel,
                                source_duty_id=source_duty.physical_vehicle_id,
                                source_trip_index=source_trip.trip_index,
                                start=start,
                                stop=stop,
                                target_duty_id=target_duty.physical_vehicle_id,
                                target_trip_index=target_trip.trip_index,
                                target_position=position,
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
    if include_whole_duty_type_exchange:
        for left_index, left in enumerate(individual.duties):
            for right in individual.duties[left_index + 1 :]:
                if left.home_depot_id != right.home_depot_id:
                    continue
                if {left.vehicle_type, right.vehicle_type} != {"ev", "cv"}:
                    continue
                if _duty_has_locks(left) or _duty_has_locks(right):
                    continue
                if _task_chain(left) == _task_chain(right):
                    continue
                moves.append(
                    WholeDutyTypeExchangeMove(
                        action_id=(
                            f"whole-duty-type-exchange:"
                            f"{left.physical_vehicle_id}<->"
                            f"{right.physical_vehicle_id}"
                        ),
                        channel="whole_duty_type_exchange",
                        left_duty_id=left.physical_vehicle_id,
                        right_duty_id=right.physical_vehicle_id,
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


def _task_chain(duty: PhysicalVehicleDuty) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(trip.customer_ids) for trip in duty.trips)


def _unlocked_task_chain(duty: PhysicalVehicleDuty) -> tuple[DutyTrip, ...]:
    return tuple(
        DutyTrip(
            trip_index=index,
            customer_ids=tuple(trip.customer_ids),
        )
        for index, trip in enumerate(duty.trips, start=1)
    )


def _duty_has_locks(duty: PhysicalVehicleDuty) -> bool:
    return duty.has_dynamic_commitment or any(
        trip.locked_customer_prefix for trip in duty.trips
    ) or any(
        session.locked for session in duty.charging_sessions
    )


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


def _assert_trip_fully_unlocked(
    duty: PhysicalVehicleDuty,
    trip: DutyTrip,
) -> None:
    if trip.locked_customer_prefix:
        raise ValueError("whole-trip action cannot change a locked prefix")
    if trip.trip_index in duty.locked_charging_trip_indices:
        raise ValueError("whole-trip action cannot change locked charging")


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
