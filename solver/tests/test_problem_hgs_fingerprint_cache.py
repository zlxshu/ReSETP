from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, asdict

import pytest

from setp_solver.algorithms.problem_hgs.model import (
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
    ScheduleAccountingVector,
    ScheduledDuty,
    ScheduledSOCPoint,
    ScheduledTripWitness,
    duty_trip_route_signature,
)


def _canonical_identity(value):
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


def _sha256_json(payload) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _original_schedule_fingerprint(schedule: ScheduledDuty) -> str:
    return _sha256_json(_canonical_identity(asdict(schedule)))


def _original_structure_fingerprint(duty: PhysicalVehicleDuty) -> str:
    payload = {
        "physical_vehicle_id": duty.physical_vehicle_id,
        "vehicle_type": duty.vehicle_type,
        "home_depot_id": duty.home_depot_id,
        "trips": [asdict(trip) for trip in duty.trips],
        "has_dynamic_commitment": bool(duty.has_dynamic_commitment),
    }
    return _sha256_json(_canonical_identity(payload))


def _original_individual_fingerprint(individual: DutyIndividual) -> str:
    duty_payloads = []
    for duty in individual.duties:
        payload = asdict(duty)
        if duty.schedule is None:
            payload.pop("schedule", None)
        else:
            payload["schedule"] = _canonical_identity(payload["schedule"])
        duty_payloads.append(payload)
    return _sha256_json(
        {
            "version": int(individual.version),
            "duties": duty_payloads,
            "unserved_customers": list(individual.unserved_customers),
        }
    )


def _individuals() -> tuple[DutyIndividual, ...]:
    legacy_trip = DutyTrip(
        trip_index=1,
        customer_ids=("C_1", "C_2"),
        locked_customer_prefix=("C_1",),
        route_visits=("C_1", "S_1", "C_2"),
    )
    legacy = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_1",
                vehicle_type="cv",
                home_depot_id="D_1",
                trips=(legacy_trip,),
                has_dynamic_commitment=True,
            ),
        ),
        unserved_customers=("C_3",),
        version=2,
        source="cache-test-legacy",
    )

    scheduled_trip = DutyTrip(
        trip_index=1,
        customer_ids=("C_4",),
        route_visits=("C_4",),
    )
    schedule = ScheduledDuty(
        physical_vehicle_id="EV_1",
        vehicle_type="ev",
        home_depot_id="D_2",
        trip_witnesses=(
            ScheduledTripWitness(
                trip_index=1,
                route_signature=duty_trip_route_signature(scheduled_trip),
                departure_second=28_800.0,
                return_second=32_400.25,
                start_soc_kwh=70.0,
                end_soc_kwh=51.5,
            ),
        ),
        soc_points=(
            ScheduledSOCPoint(
                event_index=0,
                event_kind="TRIP",
                trip_index=1,
                node_id="D_2",
                event_second=28_800.0,
                soc_before_kwh=70.0,
                soc_after_kwh=51.5,
            ),
        ),
        charging_sessions=(),
        occupancy_signature=(("D_2", 4, 7, "EV_1"),),
        local_accounting_vector=ScheduleAccountingVector(
            electricity_cost=1.25,
            emissions_kg=2.5,
            occupancy_cost=3.75,
            route_time_cost=4.0,
        ),
        schedule_contract_sha256="a" * 64,
    )
    scheduled = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="EV_1",
                vehicle_type="ev",
                home_depot_id="D_2",
                trips=(scheduled_trip,),
                schedule=schedule,
            ),
        ),
        source="cache-test-scheduled",
    )
    return DutyIndividual(duties=()), legacy, scheduled


def test_cached_fingerprints_match_original_implementation() -> None:
    individuals = _individuals()

    for individual in individuals:
        expected = _original_individual_fingerprint(individual)
        first = individual.fingerprint
        assert first == expected
        assert individual.fingerprint == expected
        assert individual.fingerprint is first

        for duty in individual.duties:
            expected_structure = _original_structure_fingerprint(duty)
            first_structure = duty.structure_fingerprint
            assert first_structure == expected_structure
            assert duty.structure_fingerprint == expected_structure
            assert duty.structure_fingerprint is first_structure
            if duty.schedule is not None:
                expected_schedule = _original_schedule_fingerprint(duty.schedule)
                first_schedule = duty.schedule.schedule_fingerprint
                assert first_schedule == expected_schedule
                assert duty.schedule.schedule_fingerprint == expected_schedule
                assert duty.schedule.schedule_fingerprint is first_schedule

    assert len({item.fingerprint for item in individuals}) == len(individuals)


def test_fingerprint_caches_do_not_change_frozen_equality_or_hashing() -> None:
    original = _individuals()[2]
    equal_copy = _individuals()[2]
    original_hash = hash(original)

    assert original == equal_copy
    assert original_hash == hash(equal_copy)
    assert "fingerprint" not in original.__dict__

    _ = original.fingerprint
    _ = original.duties[0].structure_fingerprint
    assert original.duties[0].schedule is not None
    _ = original.duties[0].schedule.schedule_fingerprint

    assert original == equal_copy
    assert hash(original) == original_hash == hash(equal_copy)
    assert asdict(original) == asdict(equal_copy)
    with pytest.raises(FrozenInstanceError):
        original.version = 99
