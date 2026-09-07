from __future__ import annotations

from dataclasses import replace

import pytest

from setp_solver.charging_curve import NL90_MILD
from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.search.dynamic_multitrip_schedule import (
    DynamicAssetState,
    cut_dynamic_certificate_at_trigger,
    prepare_dynamic_multitrip_solution,
    reschedule_dynamic_charging,
    validate_dynamic_multitrip_certificate,
)
from setp_solver.solution import Route, Solution
from solver.tests.china_test_prices import CHINA_TEST_PRICES


def _instance() -> Instance:
    nodes = [
        Node(
            "D0",
            "d",
            0.0,
            0.0,
            ready_time=0.0,
            due_time=30_000.0,
        ),
        Node(
            "C1",
            "c",
            1.0,
            0.0,
            demand=1.0,
            ready_time=6_000.0,
            due_time=7_000.0,
        ),
        Node(
            "C2",
            "c",
            2.0,
            0.0,
            demand=1.0,
            ready_time=14_000.0,
            due_time=15_000.0,
        ),
    ]
    return Instance(
        nodes,
        [
            [0.0, 1_000.0, 1_000.0],
            [1_000.0, 0.0, 1_000.0],
            [1_000.0, 1_000.0, 0.0],
        ],
        num_cv=0,
        num_ev=1,
    )


def _prices() -> PriceParameters:
    return replace(
        CHINA_TEST_PRICES,
        B_battery_kwh=20.0,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
        charging_curve_id=NL90_MILD.curve_id,
        charging_soc_breakpoints=NL90_MILD.soc_breakpoints,
        charging_relative_powers=NL90_MILD.relative_powers,
        depot_charging_curve_id=None,
        depot_charging_soc_breakpoints=None,
        depot_charging_relative_powers=None,
        public_charging_curve_id=None,
        public_charging_soc_breakpoints=None,
        public_charging_relative_powers=None,
    )


def _state() -> DynamicAssetState:
    return DynamicAssetState(
        "EV_D0_7",
        "ev",
        "D0",
        1_000.0,
        0.0,
        3,
    )


def _source(*, two_routes: bool = True) -> Solution:
    routes = [Route("open-a", "ev", "D0", ["D0", "C1", "D0"])]
    if two_routes:
        routes.append(
            Route("open-b", "ev", "D0", ["D0", "C2", "D0"])
        )
    return Solution(routes=routes)


def _prepare(*, two_routes: bool = True):
    state = _state()
    prepared, certificate = prepare_dynamic_multitrip_solution(
        _source(two_routes=two_routes),
        _instance(),
        _prices(),
        asset_states={state.physical_vehicle_id: state},
        stage_start_second=1_000.0,
    )
    return state, prepared, certificate


def test_nonlinear_dynamic_actions_freeze_curve_and_energy_states() -> None:
    state, prepared, certificate = _prepare()
    curve = NL90_MILD.scale(
        capacity_kwh=_prices().B_battery_kwh,
        reference_power_kw=_prices().depot_charge_power_kw,
    )

    assert certificate.charging_curve_id == NL90_MILD.curve_id
    assert prepared.charging_actions
    for action in prepared.charging_actions:
        assert action.charging_curve_id == NL90_MILD.curve_id
        assert action.start_energy_kwh is not None
        assert action.end_energy_kwh is not None
        assert action.end_energy_kwh - action.start_energy_kwh == pytest.approx(
            action.energy_kwh
        )
        assert action.occupancy_minutes * 60.0 == pytest.approx(
            curve.duration_seconds(
                action.start_energy_kwh,
                action.end_energy_kwh,
            )
        )
    validate_dynamic_multitrip_certificate(
        prepared,
        certificate,
        _instance(),
        _prices(),
        asset_states={state.physical_vehicle_id: state},
        stage_start_second=1_000.0,
    )


def test_nonlinear_dynamic_rejects_shortened_or_unidentified_action() -> None:
    state, prepared, certificate = _prepare()
    first = prepared.charging_actions[0]

    shortened = replace(
        prepared,
        charging_actions=[
            replace(
                first,
                occupancy_minutes=first.occupancy_minutes - 1.0,
            ),
            *prepared.charging_actions[1:],
        ],
    )
    with pytest.raises(ValueError, match="occupancy disagrees"):
        validate_dynamic_multitrip_certificate(
            shortened,
            certificate,
            _instance(),
            _prices(),
            asset_states={state.physical_vehicle_id: state},
            stage_start_second=1_000.0,
        )

    unidentified = replace(
        prepared,
        charging_actions=[
            replace(
                first,
                start_energy_kwh=None,
                end_energy_kwh=None,
                charging_curve_id=None,
            ),
            *prepared.charging_actions[1:],
        ],
    )
    with pytest.raises(ValueError, match="missing start/end energy"):
        validate_dynamic_multitrip_certificate(
            unidentified,
            certificate,
            _instance(),
            _prices(),
            asset_states={state.physical_vehicle_id: state},
            stage_start_second=1_000.0,
        )


def test_nonlinear_dynamic_carbon_retiming_uses_exact_curve() -> None:
    state, prepared, certificate = _prepare()
    profile = [
        {
            "time_index": index,
            "horizon_second_start": float(index * 1_800),
            "actual_gco2_per_kwh": 800.0 if index < 3 else 50.0,
            "forecast_gco2_per_kwh": 800.0 if index < 3 else 50.0,
        }
        for index in range(48)
    ]

    naive, _, _ = reschedule_dynamic_charging(
        prepared,
        certificate,
        _instance(),
        profile,
        _prices(),
        asset_states={state.physical_vehicle_id: state},
        stage_start_second=1_000.0,
        strategy="naive",
    )
    aware, _, stats = reschedule_dynamic_charging(
        prepared,
        certificate,
        _instance(),
        profile,
        _prices(),
        asset_states={state.physical_vehicle_id: state},
        stage_start_second=1_000.0,
        strategy="aware",
    )

    naive_emissions = evaluate(
        naive,
        _instance(),
        profile,
        _prices(),
        carbon_quota_kg=float("inf"),
    )["E_ev_indirect"]
    aware_emissions = evaluate(
        aware,
        _instance(),
        profile,
        _prices(),
        carbon_quota_kg=float("inf"),
    )["E_ev_indirect"]
    assert stats["moved_action_count"] >= 1
    assert aware_emissions < naive_emissions


def test_cut_during_nonlinear_charge_releases_at_certified_end_once() -> None:
    state, prepared, certificate = _prepare(two_routes=False)
    action = prepared.charging_actions[0]
    trigger = (
        action.charge_start_second
        + action.occupancy_minutes * 30.0
    )

    cut = cut_dynamic_certificate_at_trigger(
        prepared,
        certificate,
        _instance(),
        _prices(),
        inherited_asset_states={state.physical_vehicle_id: state},
        previous_stage_start_second=1_000.0,
        trigger_second=trigger,
    )
    continued = cut.asset_states[state.physical_vehicle_id]

    assert len(cut.locked_charging_actions) == 1
    assert continued.available_second == pytest.approx(
        action.charge_start_second
        + action.occupancy_minutes * 60.0
    )
    assert continued.remaining_battery_kwh == pytest.approx(
        action.end_energy_kwh
    )
    assert continued.next_trip_index == state.next_trip_index
