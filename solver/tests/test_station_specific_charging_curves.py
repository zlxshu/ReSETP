from dataclasses import replace

import pytest
from setp_solver.charging_action import _curve_aware_action
from setp_solver.charging_curve import (
    L100_CONTROL,
    M17_22KW_NORMAL_PWL,
    M17_FAST_SHAPE_SCALED_60KW_PWL,
)
from setp_solver.check import CHARGING_POWER, check_solution
from setp_solver.cost import charging_curve_for_action
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.solution import Route, Solution


def _prices() -> PriceParameters:
    return PriceParameters(
        B_battery_kwh=77.28,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
        charging_curve_id=L100_CONTROL.curve_id,
        charging_soc_breakpoints=L100_CONTROL.soc_breakpoints,
        charging_relative_powers=L100_CONTROL.relative_powers,
        depot_charging_curve_id=M17_22KW_NORMAL_PWL.curve_id,
        depot_charging_soc_breakpoints=M17_22KW_NORMAL_PWL.soc_breakpoints,
        depot_charging_relative_powers=M17_22KW_NORMAL_PWL.relative_powers,
        public_charging_curve_id=M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id,
        public_charging_soc_breakpoints=(
            M17_FAST_SHAPE_SCALED_60KW_PWL.soc_breakpoints
        ),
        public_charging_relative_powers=(
            M17_FAST_SHAPE_SCALED_60KW_PWL.relative_powers
        ),
    )


def _instance() -> Instance:
    return Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=100_000.0),
            Node(
                "F0",
                "f",
                0.0,
                0.0,
                due_time=100_000.0,
                charge_power_kw=60.0,
                station_chargers=1,
            ),
        ],
        distance_matrix=[[0.0, 0.0], [0.0, 0.0]],
        num_ev=1,
        num_cv=0,
    )


def test_montoya_source_times_and_60kw_shape_transfer_are_exact() -> None:
    normal_source = M17_22KW_NORMAL_PWL.scale(
        capacity_kwh=16.0,
        reference_power_kw=22.0,
    )
    fast_source = M17_FAST_SHAPE_SCALED_60KW_PWL.scale(
        capacity_kwh=16.0,
        reference_power_kw=44.0,
    )
    fast_scaled = M17_FAST_SHAPE_SCALED_60KW_PWL.scale(
        capacity_kwh=16.0,
        reference_power_kw=60.0,
    )

    assert normal_source.duration_seconds(0.0, 16.0) == pytest.approx(
        1.01 * 3_600.0
    )
    assert fast_source.duration_seconds(0.0, 16.0) == pytest.approx(
        0.51 * 3_600.0
    )
    assert fast_scaled.duration_seconds(0.0, 16.0) == pytest.approx(
        0.51 * 3_600.0 * 44.0 / 60.0
    )


def test_depot_and_public_actions_use_distinct_montoya_shapes() -> None:
    instance = _instance()
    prices = _prices()
    depot = _curve_aware_action(
        vehicle_id="EV1",
        station_id="D0",
        start_energy_kwh=0.0,
        energy_kwh=77.28,
        reference_power_kw=22.0,
        prices=prices,
        instance=instance,
    )
    public = _curve_aware_action(
        vehicle_id="EV1",
        station_id="F0",
        start_energy_kwh=0.0,
        energy_kwh=77.28,
        reference_power_kw=60.0,
        prices=prices,
        instance=instance,
    )

    assert depot.charging_curve_id == M17_22KW_NORMAL_PWL.curve_id
    assert public.charging_curve_id == M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id
    assert depot.occupancy_minutes == pytest.approx(
        M17_22KW_NORMAL_PWL.scale(
            capacity_kwh=77.28,
            reference_power_kw=22.0,
        ).duration_seconds(0.0, 77.28)
        / 60.0
    )
    assert public.occupancy_minutes == pytest.approx(
        M17_FAST_SHAPE_SCALED_60KW_PWL.scale(
            capacity_kwh=77.28,
            reference_power_kw=60.0,
        ).duration_seconds(0.0, 77.28)
        / 60.0
    )
    assert depot.occupancy_minutes > public.occupancy_minutes


def test_generation_cost_and_checker_resolve_the_same_station_curve() -> None:
    instance = _instance()
    prices = _prices()
    depot = _curve_aware_action(
        vehicle_id="EV1",
        station_id="D0",
        start_energy_kwh=0.0,
        energy_kwh=10.0,
        reference_power_kw=22.0,
        prices=prices,
        instance=instance,
    )
    public = replace(
        _curve_aware_action(
            vehicle_id="EV1",
            station_id="F0",
            start_energy_kwh=10.0,
            energy_kwh=10.0,
            reference_power_kw=60.0,
            prices=prices,
            instance=instance,
        ),
        charge_start_second=1_000.0,
    )
    solution = Solution(
        routes=[Route("EV1", "ev", "D0", ["D0", "F0", "D0"])],
        charging_actions=[depot, public],
    )

    assert charging_curve_for_action(depot, instance, prices)[0].curve_id == (
        M17_22KW_NORMAL_PWL.curve_id
    )
    assert charging_curve_for_action(public, instance, prices)[0].curve_id == (
        M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id
    )
    assert not [
        violation
        for violation in check_solution(solution, instance, prices)
        if violation.type == CHARGING_POWER
    ]
