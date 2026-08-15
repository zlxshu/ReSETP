"""Canonical physical-vehicle registry construction for private Problem-HGS."""

from __future__ import annotations

from dataclasses import replace

from setp_solver.china81 import China81Bundle

from .model import DutyIndividual, PhysicalVehicleDuty


def register_all_vehicle_slots(
    individual: DutyIndividual,
    bundle: China81Bundle,
    *,
    source: str | None = None,
) -> DutyIndividual:
    """Pad every registered CV/EV slot with an explicit empty Duty if idle."""

    by_id = {
        duty.physical_vehicle_id: duty
        for duty in individual.duties
    }
    for depot_id, caps in sorted(bundle.fleet_caps_by_depot.items()):
        expected_ids: set[str] = set()
        for vehicle_type, cap_field in (
            ("cv", "num_cv"),
            ("ev", "num_ev"),
        ):
            for index in range(1, int(caps[cap_field]) + 1):
                vehicle_id = f"{vehicle_type.upper()}_{depot_id}_{index}"
                expected_ids.add(vehicle_id)
                by_id.setdefault(
                    vehicle_id,
                    PhysicalVehicleDuty(
                        physical_vehicle_id=vehicle_id,
                        vehicle_type=vehicle_type,
                        home_depot_id=depot_id,
                        trips=(),
                    ),
                )
        actual_ids = {
            duty.physical_vehicle_id
            for duty in individual.duties
            if duty.home_depot_id == depot_id
        }
        unexpected = actual_ids.difference(expected_ids)
        if unexpected:
            raise RuntimeError(
                "completed solution uses unregistered physical vehicles: "
                + ", ".join(sorted(unexpected))
            )
        if len(expected_ids) > int(caps["total_fleet_cap"]):
            raise RuntimeError("typed fleet caps exceed the total fleet cap")

    registered = tuple(by_id[duty_id] for duty_id in sorted(by_id))
    expected_total = sum(
        int(caps["num_cv"]) + int(caps["num_ev"])
        for caps in bundle.fleet_caps_by_depot.values()
    )
    if len(registered) != expected_total:
        raise RuntimeError(
            "canonical fleet registry size does not match the selected "
            "parameter class"
        )
    return replace(
        individual,
        duties=registered,
        source=individual.source if source is None else source,
    )


def fleet_activation_changes(
    reference: DutyIndividual,
    candidate: DutyIndividual,
) -> tuple[str, ...]:
    """Return registered assets whose empty/non-empty state changed."""

    reference_state = {
        duty.physical_vehicle_id: bool(duty.trips)
        for duty in reference.duties
    }
    candidate_state = {
        duty.physical_vehicle_id: bool(duty.trips)
        for duty in candidate.duties
    }
    if set(reference_state) != set(candidate_state):
        raise ValueError("candidate changed the canonical fleet registry")
    return tuple(
        duty_id
        for duty_id in sorted(reference_state)
        if reference_state[duty_id] != candidate_state[duty_id]
    )


def assert_fleet_activation_allowed(
    reference: DutyIndividual,
    candidate: DutyIndividual,
    *,
    enabled: bool,
) -> None:
    """Reject empty-Duty activation/clearing outside the A3 treatment."""

    changed = fleet_activation_changes(reference, candidate)
    if changed and not enabled:
        raise ValueError(
            "empty Duty activation/clearing is disabled for this arm: "
            + ", ".join(changed)
        )
