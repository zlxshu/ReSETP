"""Certified rolling-horizon wiring for future-only Duty candidates."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest
from duty_hgs.dynamic import (
    DutyDynamicState,
    future_individual_from_cut,
    prepare_dynamic_candidate,
)
from duty_hgs.evaluation import DutyFullEvaluator
from duty_hgs.operators import generate_problem_moves
from run_real_input_technical_trial import _build_context
from setp_solver.cost import route_departure_second
from setp_solver.search.dynamic_multitrip_schedule import (
    DynamicAssetState,
    _route_profile,
    cut_certificate_at_trigger,
)

REPO = Path(__file__).resolve().parents[4]
INSTANCE_ID = "cn-jjj-50c-01-V2-LOCATIONS"
TRIGGER_SECOND = 43_200.0


def _dynamic_case(trigger_second: float):
    bundle, initial, _pi0, static_context = _build_context(REPO, INSTANCE_ID)
    static_evaluation = DutyFullEvaluator(static_context).evaluate(initial)
    cut = cut_certificate_at_trigger(
        static_evaluation.prepared_solution,
        static_evaluation.certificate,
        bundle.instance,
        bundle.prices,
        trigger_second=trigger_second,
    )
    assets = dict(cut.asset_states)
    for duty in initial.duties:
        if duty.physical_vehicle_id in assets:
            continue
        assets[duty.physical_vehicle_id] = DynamicAssetState(
            physical_vehicle_id=duty.physical_vehicle_id,
            vehicle_type=duty.vehicle_type,
            home_depot_id=duty.home_depot_id,
            available_second=trigger_second,
            remaining_battery_kwh=(
                float(bundle.prices.initial_ev_battery_kwh)
                if duty.vehicle_type == "ev"
                else 0.0
            ),
            next_trip_index=1,
        )

    customer_ids = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    committed_route_ids = {
        *cut.completed_route_ids,
        *cut.in_progress_route_ids,
    }
    committed_customers = {
        node_id
        for route in static_evaluation.prepared_solution.routes
        if route.vehicle_id in committed_route_ids
        for node_id in route.node_sequence[1:-1]
        if node_id in customer_ids
    }
    state = DutyDynamicState(
        source_solution=static_evaluation.prepared_solution,
        cut=cut,
        asset_states=MappingProxyType(assets),
        future_customer_ids=frozenset(customer_ids.difference(committed_customers)),
        customer_appearance_second={
            customer_id: 0.0 for customer_id in customer_ids
        },
        charging_strategy="aware",
        charging_intensity_field="forecast_gco2_per_kwh",
    )
    future = future_individual_from_cut(
        state,
        static_evaluation.certificate,
        bundle.instance,
    )
    return bundle, static_context, state, future, static_evaluation


@pytest.fixture(scope="module")
def dynamic_fixture():
    bundle, context, state, future, _static = _dynamic_case(TRIGGER_SECOND)
    return bundle, context, state, future


def test_real_cut_preserves_exact_assets_and_scores_full_day(dynamic_fixture) -> None:
    bundle, static_context, state, future = dynamic_fixture
    prepared = prepare_dynamic_candidate(future, state, bundle)
    evaluation = DutyFullEvaluator(
        replace(static_context, dynamic_state=state)
    ).evaluate(future)

    future_customers = [
        node_id
        for route in prepared.future_solution.routes
        for node_id in route.node_sequence[1:-1]
        if node_id in state.future_customer_ids
    ]
    assert set(future_customers) == set(state.future_customer_ids)
    assert len(future_customers) == len(set(future_customers))
    assert {
        trip.physical_vehicle_id
        for trip in prepared.future_certificate.trips
    }.issubset(state.asset_states)
    assert len(future.duties) == len(state.asset_states)
    assert evaluation.feasible


def test_committed_asset_is_excluded_from_whole_duty_exchange(
    dynamic_fixture,
) -> None:
    bundle, static_context, state, future = dynamic_fixture
    evaluation = DutyFullEvaluator(
        replace(static_context, dynamic_state=state)
    ).evaluate(future)
    committed = {
        duty.physical_vehicle_id
        for duty in future.duties
        if duty.has_dynamic_commitment
    }

    exchange_moves = [
        move
        for move in generate_problem_moves(future, evaluation, bundle.instance)
        if move.channel == "whole_duty_type_exchange"
    ]
    assert committed
    assert all(not committed.intersection(move.changed_duty_ids) for move in exchange_moves)


def test_late_asset_is_rejected_instead_of_silently_reassigned(
    dynamic_fixture,
) -> None:
    bundle, _static_context, state, future = dynamic_fixture
    duty = next(
        item
        for item in future.duties
        if item.vehicle_type == "cv" and item.trips
    )
    late = replace(
        state.asset_states[duty.physical_vehicle_id],
        available_second=1_000_000.0,
    )
    late_state = _replace_asset_state(state, late)

    with pytest.raises(ValueError, match="no inherited asset"):
        prepare_dynamic_candidate(future, late_state, bundle)


def test_ev_without_charge_time_is_rejected_instead_of_overcharged(
    dynamic_fixture,
) -> None:
    bundle, _static_context, state, future = dynamic_fixture
    duty = next(
        item
        for item in future.duties
        if item.vehicle_type == "ev" and item.trips
    )
    route = duty.trips[0]
    profile = _route_profile(
        replace(
            state.source_solution.routes[0],
            vehicle_id="energy-negative-open-route",
            vehicle_type="ev",
            home_depot_id=duty.home_depot_id,
            node_sequence=[
                duty.home_depot_id,
                *route.effective_route_visits,
                duty.home_depot_id,
            ],
        ),
        bundle.instance,
        bundle.prices,
    )
    empty_at_deadline = replace(
        state.asset_states[duty.physical_vehicle_id],
        available_second=profile.latest_departure_second,
        remaining_battery_kwh=0.0,
    )
    energy_state = _replace_asset_state(state, empty_at_deadline)

    with pytest.raises(ValueError, match="no inherited asset"):
        prepare_dynamic_candidate(future, energy_state, bundle)


def test_customer_cannot_be_seen_before_its_appearance() -> None:
    bundle, static_context, state, _future, static_evaluation = _dynamic_case(
        TRIGGER_SECOND
    )
    hidden_customer = next(iter(state.future_customer_ids))
    appearances = dict(state.customer_appearance_second)
    appearances[hidden_customer] = state.cut.trigger_second + 1.0
    hidden_state = replace(
        state,
        customer_appearance_second=MappingProxyType(appearances),
    )

    with pytest.raises(ValueError, match="before its appearance"):
        DutyFullEvaluator(replace(static_context, dynamic_state=hidden_state))
    with pytest.raises(ValueError, match="before their appearance"):
        future_individual_from_cut(
            hidden_state,
            static_evaluation.certificate,
            bundle.instance,
        )


def test_running_charge_is_counted_once_in_full_day_account() -> None:
    bundle, static_context, state, future, static_evaluation = _dynamic_case(
        1_000.0
    )
    running = [
        action
        for action in static_evaluation.prepared_solution.charging_actions
        if action.charge_start_second
        < state.cut.trigger_second
        < action.charge_start_second + action.occupancy_minutes * 60.0
    ]
    assert running

    evaluation = DutyFullEvaluator(
        replace(static_context, dynamic_state=state)
    ).evaluate(future)
    for action in running:
        assert evaluation.prepared_solution.charging_actions.count(action) == 1
    assert evaluation.breakdown["electricity_kwh"] == pytest.approx(
        static_evaluation.breakdown["electricity_kwh"]
    )
    assert evaluation.breakdown["E_ev_indirect"] == pytest.approx(
        static_evaluation.breakdown["E_ev_indirect"]
    )


def test_dynamic_departure_and_physical_vehicle_count_survive_full_evaluation(
    dynamic_fixture,
) -> None:
    bundle, static_context, state, future = dynamic_fixture
    source = next(
        duty
        for duty in future.duties
        if duty.vehicle_type == "cv"
        and duty.trips
        and not duty.has_dynamic_commitment
    )
    idle = next(
        duty
        for duty in future.duties
        if duty.vehicle_type == "cv"
        and not duty.trips
        and not duty.has_dynamic_commitment
        and duty.home_depot_id == source.home_depot_id
    )
    candidate = replace(
        future,
        duties=tuple(
            replace(duty, trips=())
            if duty.physical_vehicle_id == source.physical_vehicle_id
            else replace(duty, trips=source.trips)
            if duty.physical_vehicle_id == idle.physical_vehicle_id
            else duty
            for duty in future.duties
        ),
    )
    route = replace(
        state.source_solution.routes[0],
        vehicle_id="delayed-open-route",
        vehicle_type="cv",
        home_depot_id=idle.home_depot_id,
        node_sequence=[
            idle.home_depot_id,
            *source.trips[0].effective_route_visits,
            idle.home_depot_id,
        ],
    )
    natural_departure = route_departure_second(
        route,
        bundle.instance,
        bundle.prices,
    )
    delayed_release = natural_departure + 60.0
    delayed_state = _replace_asset_state(
        state,
        replace(
            state.asset_states[idle.physical_vehicle_id],
            available_second=delayed_release,
        ),
    )
    evaluation = DutyFullEvaluator(
        replace(static_context, dynamic_state=delayed_state)
    ).evaluate(candidate)
    delayed_trip = next(
        trip
        for trip in evaluation.certificate.trips
        if trip.physical_vehicle_id == idle.physical_vehicle_id
    )
    used_physical_ids = {
        route.vehicle_id.split("#T", 1)[0]
        for route in evaluation.prepared_solution.routes
    }

    assert delayed_trip.departure_second >= delayed_release
    assert delayed_trip.departure_second > natural_departure
    assert (
        int(evaluation.breakdown["n_veh_cv"])
        + int(evaluation.breakdown["n_veh_ev"])
        == len(used_physical_ids)
    )


def _replace_asset_state(
    state: DutyDynamicState,
    replacement: DynamicAssetState,
) -> DutyDynamicState:
    assets = dict(state.asset_states)
    assets[replacement.physical_vehicle_id] = replacement
    cut_assets = dict(state.cut.asset_states)
    if replacement.physical_vehicle_id in cut_assets:
        cut_assets[replacement.physical_vehicle_id] = replacement
    return replace(
        state,
        cut=replace(
            state.cut,
            asset_states=MappingProxyType(cut_assets),
        ),
        asset_states=MappingProxyType(assets),
    )
