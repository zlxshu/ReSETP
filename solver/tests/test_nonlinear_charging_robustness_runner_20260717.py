from __future__ import annotations

import pytest

from baselines.e4_e5.nonlinear_charging_replay_20260717 import scale_normalized_curve
from baselines.e4_e5.run_nonlinear_charging_robustness_replay_20260717 import (
    ActionContext,
    action_contexts,
    evaluate_action,
    max_exact_concurrency,
    max_slot_concurrency,
)
from setp_solver.search.multitrip_schedule import MultiTripCertificate, ScheduledTrip


def certificate() -> MultiTripCertificate:
    return MultiTripCertificate(
        contract_id="E3_STRICT_MULTITRIP_V2",
        status="PASS",
        vehicle_counts={"cv": 0, "ev": 1},
        trips=(
            ScheduledTrip(
                route_id="EV_D0_1#T1",
                physical_vehicle_id="EV_D0_1",
                trip_index=1,
                vehicle_type="ev",
                home_depot_id="D0",
                departure_second=20_000.0,
                return_second=30_000.0,
                recharge_end_second=36_000.0,
                start_battery_kwh=100.0,
                end_battery_kwh=60.0,
                charge_start_second=30_000.0,
                charge_energy_kwh=40.0,
            ),
            ScheduledTrip(
                route_id="EV_D0_1#T2",
                physical_vehicle_id="EV_D0_1",
                trip_index=2,
                vehicle_type="ev",
                home_depot_id="D0",
                departure_second=40_000.0,
                return_second=50_000.0,
                recharge_end_second=50_000.0,
                start_battery_kwh=100.0,
                end_battery_kwh=50.0,
            ),
        ),
        recharge_mode="on_demand",
        depot_charge_power_kw=22.0,
        first_trip_charge_day_offset=-1,
    )


def profile() -> list[dict[str, float]]:
    return [
        {
            "actual_gco2_per_kwh": 100.0 + index,
            "forecast_gco2_per_kwh": 150.0 + index,
        }
        for index in range(48)
    ]


def test_certificate_reconstructs_first_and_between_trip_energy_windows() -> None:
    contexts = action_contexts(certificate())
    first = contexts["EV_D0_1#T1"]
    assert first.start_energy_kwh == 0.0
    assert first.end_energy_kwh == 100.0
    assert first.earliest_start_second == 0.0
    assert first.latest_finish_second == 86_400.0
    assert first.charge_day_offset == -1

    second = contexts["EV_D0_1#T2"]
    assert second.start_energy_kwh == 60.0
    assert second.end_energy_kwh == 100.0
    assert second.earliest_start_second == 30_000.0
    assert second.latest_finish_second == 40_000.0
    assert second.charge_day_offset == 0


def test_replay_uses_latest_finish_not_linear_latest_start() -> None:
    context = ActionContext(
        vehicle_trip="EV_D0_1#T2",
        station_id="D0",
        charge_scope="same_day_between_trip",
        charge_day_offset=0,
        start_energy_kwh=60.0,
        end_energy_kwh=100.0,
        earliest_start_second=30_000.0,
        latest_finish_second=40_000.0,
    )
    curve = scale_normalized_curve(
        capacity_kwh=280.0,
        soc_breakpoints=(0.0, 0.9, 1.0),
        relative_powers=(1.0, 0.5),
        reference_power_kw=22.0,
    )
    row = {"charge_start_second": "32000"}
    replay = evaluate_action(
        action_row=row,
        context=context,
        charging_curve=curve,
        rule="L->NL-C",
        profile=profile(),
    )
    assert replay["feasible"] is True
    assert float(replay["charge_end_second"]) <= context.latest_finish_second + 1e-6
    assert float(replay["slot_energy_sum_kwh"]) == pytest.approx(40.0)


def test_fixed_linear_start_can_be_nonlinear_infeasible_without_repair() -> None:
    context = ActionContext(
        vehicle_trip="EV_D0_1#T2",
        station_id="D0",
        charge_scope="same_day_between_trip",
        charge_day_offset=0,
        start_energy_kwh=220.0,
        end_energy_kwh=270.0,
        earliest_start_second=30_000.0,
        latest_finish_second=40_000.0,
    )
    curve = scale_normalized_curve(
        capacity_kwh=280.0,
        soc_breakpoints=(0.0, 0.8, 0.9, 1.0),
        relative_powers=(1.0, 0.5, 0.25),
        reference_power_kw=22.0,
    )
    replay = evaluate_action(
        action_row={"charge_start_second": "36000"},
        context=context,
        charging_curve=curve,
        rule="L->NL-F",
        profile=profile(),
    )
    assert replay["feasible"] is False
    assert replay["infeasibility_reason"] in {
        "nonlinear_duration_exceeds_immutable_window",
        "linear_forecast_start_is_nonlinear_infeasible",
    }


def test_exact_and_half_hour_concurrency_are_separate_contracts() -> None:
    sequential_same_slot = (
        (0.0, 600.0, "v1"),
        (600.0, 1200.0, "v2"),
    )
    assert max_exact_concurrency(sequential_same_slot) == 1
    assert max_slot_concurrency(sequential_same_slot) == 2

    overlapping = (
        (0.0, 900.0, "v1"),
        (300.0, 1200.0, "v2"),
    )
    assert max_exact_concurrency(overlapping) == 2
    assert max_slot_concurrency(overlapping) == 2
