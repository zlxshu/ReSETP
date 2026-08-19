"""Customer-assignment crossover for physical-vehicle duties."""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass, replace

from .model import (
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
    assert_locks_preserved,
)
from .operators import compact_empty_trips


@dataclass(frozen=True)
class FleetRegistryEntry:
    physical_vehicle_id: str
    vehicle_type: str
    home_depot_id: str


@dataclass(frozen=True)
class DutyCrossoverResult:
    child: DutyIndividual
    changed_duty_ids: frozenset[str]
    donor_duty_ids: tuple[str, ...]
    duplicate_customers_removed: tuple[str, ...]
    unserved_customers: tuple[str, ...]
    deterministic_work_units: int = 1


def canonical_fleet_registry(
    individual: DutyIndividual,
) -> tuple[FleetRegistryEntry, ...]:
    return tuple(
        FleetRegistryEntry(
            duty.physical_vehicle_id,
            duty.vehicle_type,
            duty.home_depot_id,
        )
        for duty in sorted(
            individual.duties,
            key=lambda item: item.physical_vehicle_id,
        )
    )


def trip_assignment_exchange(
    parents: tuple[DutyIndividual, DutyIndividual],
    rng: random.Random,
    customer_coordinates: Mapping[str, tuple[float, float]],
    *,
    customer_home_depot_by_id: Mapping[str, str] | None = None,
    customer_vehicle_type_by_id: Mapping[str, str] | None = None,
    multi_trip_enabled: bool = True,
) -> DutyCrossoverResult:
    """Return the first candidate in the randomized exact assignment order."""

    return trip_assignment_exchange_candidates(
        parents,
        rng,
        customer_coordinates,
        customer_home_depot_by_id=customer_home_depot_by_id,
        customer_vehicle_type_by_id=customer_vehicle_type_by_id,
        multi_trip_enabled=multi_trip_enabled,
    )[0]


def trip_assignment_exchange_candidates(
    parents: tuple[DutyIndividual, DutyIndividual],
    rng: random.Random,
    customer_coordinates: Mapping[str, tuple[float, float]],
    *,
    customer_home_depot_by_id: Mapping[str, str] | None = None,
    customer_vehicle_type_by_id: Mapping[str, str] | None = None,
    multi_trip_enabled: bool = True,
) -> tuple[DutyCrossoverResult, ...]:
    """Append one compatible donor trip and remove its former occurrences.

    This problem-adapted operator changes the
    assignment of one complete trip without copying an entire day schedule.
    A trip may move across vehicle types and home depots because those belong
    to the receiving physical asset, not to the customer trip.  The receiving
    vehicle keeps its identity, type, depot, and dynamic history; the affected
    unlocked charging decisions are rebuilt by the complete model.
    """

    first, second = parents
    registry = canonical_fleet_registry(first)
    if registry != canonical_fleet_registry(second):
        raise ValueError("trip-assignment parents use different canonical fleets")
    _assert_parent_locks_compatible(first, second)
    universe = _represented_customers(first).union(_represented_customers(second))
    missing_coordinates = sorted(universe.difference(customer_coordinates))
    if missing_coordinates:
        raise ValueError(
            "trip assignment lacks customer coordinates: "
            + ", ".join(missing_coordinates)
        )
    protected_customers = {
        customer
        for duty in first.duties
        for trip in duty.trips
        for position, customer in enumerate(trip.customer_ids)
        if (
            position < len(trip.locked_customer_prefix)
            or trip.trip_index in duty.locked_charging_trip_indices
        )
    }
    origin_duties: dict[str, str] = {
        customer: duty.physical_vehicle_id
        for duty in first.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    candidates: list[
        tuple[PhysicalVehicleDuty, DutyTrip, tuple[PhysicalVehicleDuty, ...]]
    ] = []
    for donor_duty in sorted(
        second.duties,
        key=lambda item: item.physical_vehicle_id,
    ):
        for donor_trip in donor_duty.trips:
            donor_customers = set(donor_trip.customer_ids)
            if (
                not donor_customers
                or donor_trip.locked_customer_prefix
                or donor_trip.trip_index
                in donor_duty.locked_charging_trip_indices
                or donor_customers.intersection(protected_customers)
            ):
                continue
            # A newly disclosed dynamic customer can already be routed in the
            # donor parent while it is still explicitly unserved in the main
            # parent.  Such a customer has no origin duty to exclude: the
            # appended donor occurrence is its first occurrence in the child.
            origins = {
                origin_duties[item]
                for item in donor_customers
                if item in origin_duties
            }
            receivers = tuple(
                duty
                for duty in first.duties
                if duty.physical_vehicle_id not in origins
                and (multi_trip_enabled or not duty.trips)
                and (
                    customer_home_depot_by_id is None
                    or all(
                        customer_home_depot_by_id.get(customer)
                        == duty.home_depot_id
                        for customer in donor_customers
                    )
                )
                and (
                    customer_vehicle_type_by_id is None
                    or all(
                        customer_vehicle_type_by_id.get(customer)
                        == duty.vehicle_type
                        for customer in donor_customers
                    )
                )
            )
            if receivers:
                candidates.append((donor_duty, donor_trip, receivers))
    if not candidates:
        raise ValueError("trip assignment found no compatible movable trip")

    start = rng.randrange(len(candidates))
    ordered_candidates = candidates[start:] + candidates[:start]
    results: list[DutyCrossoverResult] = []
    for donor_duty, donor_trip, receivers in ordered_candidates:
        donor_centroid = _customer_centroid(
            donor_trip.customer_ids,
            customer_coordinates,
        )
        ordered_receivers = sorted(
            receivers,
            key=lambda duty: (
                _squared_distance(
                    _duty_centroid(
                        duty,
                        customer_coordinates,
                        donor_centroid,
                    ),
                    donor_centroid,
                ),
                duty.physical_vehicle_id,
            ),
        )
        results.extend(
            _build_trip_assignment_candidate(
                first,
                second,
                donor_duty,
                donor_trip,
                receiver,
                universe,
            )
            for receiver in ordered_receivers
        )
    return tuple(results)


def _build_trip_assignment_candidate(
    first: DutyIndividual,
    second: DutyIndividual,
    donor_duty: PhysicalVehicleDuty,
    donor_trip: DutyTrip,
    receiver: PhysicalVehicleDuty,
    universe: set[str],
) -> DutyCrossoverResult:
    duties: list[PhysicalVehicleDuty] = []
    preferred_occurrences: dict[str, tuple[int, int, int]] = {}
    for duty_index, duty in enumerate(first.duties):
        if duty.physical_vehicle_id != receiver.physical_vehicle_id:
            duties.append(duty)
            continue
        new_trip_index = len(duty.trips) + 1
        appended_trip = replace(
            donor_trip,
            trip_index=new_trip_index,
            locked_customer_prefix=(),
            route_visits=(),
        )
        duties.append(
            replace(
                duty,
                trips=(*duty.trips, appended_trip),
                charging_sessions=tuple(
                    item for item in duty.charging_sessions if item.locked
                ),
            )
        )
        preferred_occurrences.update(
            {
                customer: (duty_index, len(duty.trips), position)
                for position, customer in enumerate(appended_trip.customer_ids)
            }
        )
    cleaned, duplicate_customers, changed_by_cleanup = _remove_duplicates(
        duties,
        donor_ids={receiver.physical_vehicle_id},
        preferred_occurrences=preferred_occurrences,
    )
    changed = {receiver.physical_vehicle_id, *changed_by_cleanup}
    served = {
        customer
        for duty in cleaned
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    child = DutyIndividual(
        duties=tuple(cleaned),
        unserved_customers=tuple(sorted(universe.difference(served))),
        source="trip-assignment-exchange",
    )
    assert_locks_preserved(first, child)
    assert_locks_preserved(second, child)
    return DutyCrossoverResult(
        child=child,
        changed_duty_ids=frozenset(changed),
        donor_duty_ids=(donor_duty.physical_vehicle_id,),
        duplicate_customers_removed=tuple(sorted(duplicate_customers)),
        unserved_customers=child.unserved_customers,
        deterministic_work_units=1,
    )


def _remove_duplicates(
    duties: list[PhysicalVehicleDuty],
    *,
    donor_ids: set[str],
    preferred_occurrences: Mapping[str, tuple[int, int, int]] | None = None,
) -> tuple[list[PhysicalVehicleDuty], set[str], set[str]]:
    preferred_occurrences = preferred_occurrences or {}
    occurrences: dict[
        str, list[tuple[int, int, int, bool, bool, bool]]
    ] = {}
    for duty_index, duty in enumerate(duties):
        for trip_index, trip in enumerate(duty.trips):
            for position, customer in enumerate(trip.customer_ids):
                occurrences.setdefault(customer, []).append(
                    (
                        duty_index,
                        trip_index,
                        position,
                        position < len(trip.locked_customer_prefix),
                        duty.physical_vehicle_id in donor_ids,
                        trip.trip_index in duty.locked_charging_trip_indices,
                    )
                )

    removals: dict[tuple[int, int], set[int]] = {}
    duplicates: set[str] = set()
    for customer, rows in occurrences.items():
        if len(rows) == 1:
            continue
        duplicates.add(customer)
        locked = [row for row in rows if row[3] or row[5]]
        if len(locked) > 1:
            raise ValueError(
                f"customer {customer!r} appears in incompatible locked trips"
            )
        preferred = preferred_occurrences.get(customer)
        preferred_rows = [row for row in rows if row[:3] == preferred]
        keep = (
            locked[0]
            if locked
            else preferred_rows[0]
            if preferred_rows
            else min(
                rows,
                key=lambda row: (not row[4], row[0], row[1], row[2]),
            )
        )
        for row in rows:
            if row != keep:
                if row[5]:
                    raise ValueError(
                        "duplicate cleanup cannot change a trip with locked charging"
                    )
                removals.setdefault((row[0], row[1]), set()).add(row[2])

    changed: set[str] = set()
    rebuilt: list[PhysicalVehicleDuty] = []
    for duty_index, duty in enumerate(duties):
        trips = []
        duty_changed = False
        for trip_index, trip in enumerate(duty.trips):
            positions = removals.get((duty_index, trip_index), set())
            if not positions:
                trips.append(trip)
                continue
            duty_changed = True
            changed.add(duty.physical_vehicle_id)
            trips.append(
                replace(
                    trip,
                    customer_ids=tuple(
                        customer
                        for position, customer in enumerate(trip.customer_ids)
                        if position not in positions
                    ),
                    route_visits=(),
                )
            )
        rebuilt.append(
            compact_empty_trips(replace(duty, trips=tuple(trips)))
            if duty_changed
            else duty
        )
    return rebuilt, duplicates, changed


def _duty_centroid(
    duty: PhysicalVehicleDuty,
    coordinates: Mapping[str, tuple[float, float]],
    fallback: tuple[float, float],
) -> tuple[float, float]:
    customers = tuple(
        customer for trip in duty.trips for customer in trip.customer_ids
    )
    if not customers:
        return fallback
    return _customer_centroid(customers, coordinates)


def _customer_centroid(
    customers: tuple[str, ...],
    coordinates: Mapping[str, tuple[float, float]],
) -> tuple[float, float]:
    return (
        sum(coordinates[item][0] for item in customers) / len(customers),
        sum(coordinates[item][1] for item in customers) / len(customers),
    )


def _squared_distance(
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    return (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2


def _assert_parent_locks_compatible(
    first: DutyIndividual,
    second: DutyIndividual,
) -> None:
    first_by_id = {
        duty.physical_vehicle_id: duty for duty in first.duties
    }
    second_by_id = {
        duty.physical_vehicle_id: duty for duty in second.duties
    }
    for duty_id, left in first_by_id.items():
        right = second_by_id[duty_id]
        if left.has_dynamic_commitment != right.has_dynamic_commitment:
            raise ValueError(
                f"crossover parents disagree on dynamic commitment for {duty_id}"
            )
        left_prefixes = tuple(
            (trip.trip_index, trip.locked_customer_prefix)
            for trip in left.trips
            if trip.locked_customer_prefix
        )
        right_prefixes = tuple(
            (trip.trip_index, trip.locked_customer_prefix)
            for trip in right.trips
            if trip.locked_customer_prefix
        )
        left_charges = tuple(
            session for session in left.charging_sessions if session.locked
        )
        right_charges = tuple(
            session for session in right.charging_sessions if session.locked
        )
        if left_prefixes != right_prefixes or left_charges != right_charges:
            raise ValueError(
                f"crossover parents disagree on dynamic locks for {duty_id}"
            )


def _represented_customers(individual: DutyIndividual) -> set[str]:
    return {
        customer
        for duty in individual.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }.union(individual.unserved_customers)
