"""v1 2026-08-07: Duty-HGS decision-object interface tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from duty_hgs.model import (
    DutyChargingSession,
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
    assert_locks_preserved,
)
from setp_solver.solution import ChargingAction, Route, Solution


def _individual() -> DutyIndividual:
    return DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="EV_D0_1",
                vehicle_type="ev",
                home_depot_id="D0",
                trips=(
                    DutyTrip(1, ("C1", "C2"), locked_customer_prefix=("C1",)),
                    DutyTrip(2, ("C3",)),
                ),
                charging_sessions=(
                    DutyChargingSession(
                        trip_index=1,
                        station_id="D0",
                        energy_kwh=4.0,
                        occupancy_minutes=12.0,
                        charge_start_second=300.0,
                        start_energy_kwh=6.0,
                        end_energy_kwh=10.0,
                        charging_curve_id="NL_TEST",
                        locked=True,
                    ),
                ),
            ),
        ),
        unserved_customers=("C4",),
        source="technical-fixture",
    )


def test_solution_round_trip_preserves_vehicle_trip_charge_and_locks() -> None:
    original = _individual()
    solution = original.to_solution()
    restored = DutyIndividual.from_solution(
        solution,
        locked_customer_prefix_by_route={"EV_D0_1#T1": ("C1",)},
        locked_charging_routes={"EV_D0_1#T1"},
        unserved_customers=original.unserved_customers,
        source=original.source,
    )

    assert restored == original
    assert [route.vehicle_id for route in solution.routes] == [
        "EV_D0_1#T1",
        "EV_D0_1#T2",
    ]
    assert solution.charging_actions[0].vehicle_id == "EV_D0_1#T1"


def test_invalid_vehicle_prefix_and_noncontiguous_trips_fail_closed() -> None:
    with pytest.raises(ValueError, match="must start with EV_ or CV_"):
        replace(_individual().duties[0], physical_vehicle_id="vehicle-1")

    with pytest.raises(ValueError, match="contiguous and start at 1"):
        replace(
            _individual().duties[0],
            trips=(DutyTrip(1, ("C1",)), DutyTrip(3, ("C2",))),
        )


def test_locked_prefix_must_be_an_actual_prefix() -> None:
    with pytest.raises(ValueError, match="locked customer prefix"):
        DutyTrip(1, ("C1", "C2"), locked_customer_prefix=("C2",))


def test_public_station_visit_survives_customer_only_partition() -> None:
    solution = Solution(
        routes=[
            Route(
                "EV_D0_1#T1",
                "ev",
                "D0",
                ["D0", "F1", "C1", "D0"],
            )
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id="EV_D0_1#T1",
                station_id="F1",
                energy_kwh=4.0,
                occupancy_minutes=12.0,
                charge_start_second=500.0,
            )
        ],
    )

    individual = DutyIndividual.from_solution(
        solution,
        customer_node_ids={"C1"},
    )

    assert individual.duties[0].trips[0].customer_ids == ("C1",)
    assert individual.duties[0].trips[0].route_visits == ("F1", "C1")
    assert individual.to_solution() == solution


def test_lock_guard_rejects_erased_lock_metadata() -> None:
    reference = _individual()
    changed_trip = replace(
        reference.duties[0].trips[0],
        locked_customer_prefix=(),
    )
    candidate = replace(
        reference,
        duties=(
            replace(
                reference.duties[0],
                trips=(changed_trip, reference.duties[0].trips[1]),
            ),
        ),
    )

    with pytest.raises(ValueError, match="locked prefix"):
        assert_locks_preserved(reference, candidate)
