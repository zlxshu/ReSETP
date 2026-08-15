from __future__ import annotations

from dataclasses import replace

import pytest

from setp_solver.check import CHARGING_POWER, check_solution
from setp_solver.charging_curve import NL90_MILD
from setp_solver.cost import (
    charging_action_slot_breakdown,
    evaluate,
)
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters, UK_2025_PRICES
from setp_solver.search.charging import (
    _curve_aware_action,
    solve_charging_fixed_route,
)
from setp_solver.search.multitrip_schedule import (
    prepare_multitrip_solution,
    reschedule_between_trip_charging,
    route_timing,
)
from setp_solver.solution import ChargingAction, Route, Solution


def _prices(
    *,
    capacity_kwh: float = 100.0,
    initial_kwh: float = 80.0,
    power_kw: float = 100.0,
) -> PriceParameters:
    return replace(
        UK_2025_PRICES,
        B_battery_kwh=capacity_kwh,
        initial_ev_battery_kwh=initial_kwh,
        depot_charge_power_kw=power_kw,
        charging_curve_id=NL90_MILD.curve_id,
        charging_soc_breakpoints=NL90_MILD.soc_breakpoints,
        charging_relative_powers=NL90_MILD.relative_powers,
    )


def _zero_distance_instance() -> Instance:
    return Instance(
        nodes=[
            Node("D0", "d", 0, 0, due_time=100_000),
            Node(
                "C1",
                "c",
                0,
                0,
                demand=1,
                due_time=100_000,
            ),
        ],
        distance_matrix=[[0.0, 0.0], [0.0, 0.0]],
        num_ev=1,
        num_cv=0,
    )


def _profile(*values: float) -> list[dict[str, float]]:
    return [
        {
            "horizon_second_start": float(index * 1800),
            "actual_gco2_per_kwh": float(value),
        }
        for index, value in enumerate(values)
    ]


def test_nonlinear_slot_split_uses_taper_phases_not_uniform_average() -> None:
    instance = _zero_distance_instance()
    prices = _prices()
    curve = NL90_MILD.scale(
        capacity_kwh=100.0,
        reference_power_kw=100.0,
    )
    action = ChargingAction(
        "EV1",
        "D0",
        energy_kwh=20.0,
        occupancy_minutes=curve.duration_seconds(80.0, 100.0) / 60.0,
        charge_start_second=1500.0,
        start_energy_kwh=80.0,
        end_energy_kwh=100.0,
        charging_curve_id=NL90_MILD.curve_id,
    )

    slots = charging_action_slot_breakdown(
        action,
        instance,
        prices,
        n_slots=48,
        cyclic=True,
    )

    assert [(row.slot_index, row.g_skt_sec) for row in slots] == [
        (0, 300.0),
        (1, 780.0),
    ]
    assert slots[0].y_skt_kwh == pytest.approx(100.0 * 300.0 / 3600.0)
    assert slots[1].y_skt_kwh == pytest.approx(
        20.0 - slots[0].y_skt_kwh
    )
    uniform_first_slot = 20.0 * 300.0 / 1080.0
    assert slots[0].y_skt_kwh > uniform_first_slot
    assert sum(row.y_skt_kwh for row in slots) == pytest.approx(20.0)


def test_cost_and_checker_share_the_same_nonlinear_action_physics() -> None:
    instance = _zero_distance_instance()
    prices = _prices()
    route = Route("EV1", "ev", "D0", ["D0", "C1", "D0"])
    action = _curve_aware_action(
        vehicle_id=route.vehicle_id,
        station_id="D0",
        start_energy_kwh=80.0,
        energy_kwh=20.0,
        reference_power_kw=100.0,
        prices=prices,
    )
    action = replace(
        action,
        charge_start_second=80_000.0,
        charge_day_offset=-1,
    )
    solution = Solution(routes=[route], charging_actions=[action])
    profile = _profile(*([300.0, 50.0] * 24))

    metrics = evaluate(solution, instance, profile, prices)
    violations = check_solution(solution, instance, prices)

    assert metrics["electricity_kwh"] == pytest.approx(20.0)
    assert not [
        violation
        for violation in violations
        if violation.type == CHARGING_POWER
    ]

    shortened = replace(
        action,
        occupancy_minutes=action.occupancy_minutes - 1.0,
    )
    bad = Solution(routes=[route], charging_actions=[shortened])
    bad_violations = check_solution(bad, instance, prices)
    assert any(
        violation.type == CHARGING_POWER
        and "occupancy disagrees" in violation.detail
        for violation in bad_violations
    )
    with pytest.raises(ValueError, match="occupancy disagrees"):
        evaluate(bad, instance, profile, prices)


def test_nonlinear_cost_fails_closed_without_action_energy_states() -> None:
    instance = _zero_distance_instance()
    prices = _prices()
    action = ChargingAction(
        "EV1",
        "D0",
        energy_kwh=20.0,
        occupancy_minutes=18.0,
        charge_start_second=0.0,
    )

    with pytest.raises(ValueError, match="missing start/end energy"):
        evaluate(
            Solution(charging_actions=[action]),
            instance,
            _profile(*([100.0] * 48)),
            prices,
        )


def test_nonlinear_multitrip_carbon_retiming_uses_exact_actions() -> None:
    nodes = [
        Node("D0", "d", 0, 0, due_time=100_000),
        Node(
            "C1",
            "c",
            0,
            0,
            demand=10,
            ready_time=1_000,
            due_time=4_000,
            service_time=100,
        ),
        Node(
            "C2",
            "c",
            0,
            0,
            demand=10,
            ready_time=8_000,
            due_time=12_000,
            service_time=100,
        ),
    ]
    matrix = [
        [0.0 if left == right else 1_000.0 for right in range(3)]
        for left in range(3)
    ]
    instance = Instance(nodes, matrix, num_ev=2, num_cv=0)
    routes = [
        Route("EV_A", "ev", "D0", ["D0", "C1", "D0"]),
        Route("EV_B", "ev", "D0", ["D0", "C2", "D0"]),
    ]
    probe = PriceParameters(B_battery_kwh=280.0)
    drive = route_timing(routes[0], instance, probe).drive_energy_kwh
    prices = _prices(
        capacity_kwh=drive * 1.05,
        initial_kwh=0.0,
        power_kw=22.0,
    )
    prepared, certificate = prepare_multitrip_solution(
        Solution(routes=routes),
        instance,
        prices,
    )
    profile = _profile(*([300.0, 50.0] * 24))

    naive = reschedule_between_trip_charging(
        prepared,
        certificate,
        instance,
        profile,
        strategy="naive",
        prices=prices,
    )
    aware = reschedule_between_trip_charging(
        prepared,
        certificate,
        instance,
        profile,
        strategy="aware",
        prices=prices,
    )

    naive_carbon = evaluate(naive, instance, profile, prices)[
        "E_ev_indirect"
    ]
    aware_carbon = evaluate(aware, instance, profile, prices)[
        "E_ev_indirect"
    ]
    assert aware_carbon < naive_carbon - 1e-12
    assert [
        action.charge_start_second for action in aware.charging_actions
    ] != [
        action.charge_start_second for action in naive.charging_actions
    ]
    assert all(
        action.charging_curve_id == NL90_MILD.curve_id
        for action in aware.charging_actions
    )


def test_fixed_route_charging_repair_emits_curve_bound_actions() -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0, 0, due_time=100_000),
            Node("C1", "c", 0, 0, due_time=100_000),
        ],
        distance_matrix=[[0.0, 80_000.0], [80_000.0, 0.0]],
    )
    route = Route("EV1", "ev", "D0", ["D0", "C1", "D0"])
    prices = _prices()
    actions = solve_charging_fixed_route(
        route,
        instance,
        _profile(*([100.0] * 48)),
        prices,
        strategy="aware",
    )

    assert len(actions) == 1
    action = actions[0]
    assert action.start_energy_kwh == pytest.approx(80.0)
    assert action.end_energy_kwh == pytest.approx(
        80.0 + action.energy_kwh
    )
    assert action.charging_curve_id == NL90_MILD.curve_id
    curve = NL90_MILD.scale(
        capacity_kwh=100.0,
        reference_power_kw=100.0,
    )
    assert action.occupancy_minutes * 60.0 == pytest.approx(
        curve.duration_seconds(
            action.start_energy_kwh,
            action.end_energy_kwh,
        )
    )
