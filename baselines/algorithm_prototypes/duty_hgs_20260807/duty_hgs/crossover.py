"""Selective exchange of complete physical-vehicle daily duties.

v1 2026-08-07: adapt the Nagata--Kobayashi/PyVRP SREX selection pattern from
routes to canonical physical duties.  Vehicle identity and locked commitments
never cross registry slots; duplicate customers are removed and missing
customers remain explicit for regret repair.

v2 2026-08-07: duplicate cleanup cannot alter a trip carrying a locked charge.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from .model import DutyIndividual, PhysicalVehicleDuty, assert_locks_preserved
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


def selective_duty_exchange(
    parents: tuple[DutyIndividual, DutyIndividual],
    rng: random.Random,
) -> DutyCrossoverResult:
    """Exchange a random contiguous block of whole canonical Duty entries."""

    first, second = parents
    registry = canonical_fleet_registry(first)
    if registry != canonical_fleet_registry(second):
        raise ValueError("crossover parents use different canonical fleets")
    _assert_parent_locks_compatible(first, second)
    if not registry:
        raise ValueError("Duty crossover requires a non-empty fleet registry")

    count = rng.randrange(len(registry)) + 1
    start = rng.randrange(len(registry))
    donor_ids = tuple(
        registry[(start + offset) % len(registry)].physical_vehicle_id
        for offset in range(count)
    )
    first_by_id = {
        duty.physical_vehicle_id: duty for duty in first.duties
    }
    second_by_id = {
        duty.physical_vehicle_id: duty for duty in second.duties
    }
    duties = [
        first_by_id[entry.physical_vehicle_id]
        if entry.physical_vehicle_id in donor_ids
        else second_by_id[entry.physical_vehicle_id]
        for entry in registry
    ]
    cleaned, duplicate_customers, changed_by_cleanup = _remove_duplicates(
        duties,
        donor_ids=set(donor_ids),
    )
    expected = _represented_customers(first).union(_represented_customers(second))
    served = {
        customer
        for duty in cleaned
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    unserved = tuple(sorted(expected.difference(served)))
    child = DutyIndividual(
        duties=tuple(cleaned),
        unserved_customers=unserved,
        source="selective-duty-exchange",
    )
    assert_locks_preserved(first, child)
    assert_locks_preserved(second, child)
    return DutyCrossoverResult(
        child=child,
        changed_duty_ids=frozenset(set(donor_ids).union(changed_by_cleanup)),
        donor_duty_ids=donor_ids,
        duplicate_customers_removed=tuple(sorted(duplicate_customers)),
        unserved_customers=unserved,
    )


def _remove_duplicates(
    duties: list[PhysicalVehicleDuty],
    *,
    donor_ids: set[str],
) -> tuple[list[PhysicalVehicleDuty], set[str], set[str]]:
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
        locked = [row for row in rows if row[3]]
        if len(locked) > 1:
            raise ValueError(
                f"customer {customer!r} appears in incompatible locked prefixes"
            )
        keep = locked[0] if locked else min(
            rows,
            key=lambda row: (not row[4], row[0], row[1], row[2]),
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
        for trip_index, trip in enumerate(duty.trips):
            positions = removals.get((duty_index, trip_index), set())
            if not positions:
                trips.append(trip)
                continue
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
        rebuilt.append(compact_empty_trips(replace(duty, trips=tuple(trips))))
    return rebuilt, duplicates, changed


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
