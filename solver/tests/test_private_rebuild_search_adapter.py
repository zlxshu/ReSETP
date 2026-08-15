from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import _build_context  # noqa: E402
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    DutyFullEvaluator,
    DutyIncrementalEvaluator,
    _rebuilt_route_constraint_violations,
)
from setp_solver.algorithms.problem_hgs.model import DutyChargingSession  # noqa: E402
from setp_solver.charging_curve import (  # noqa: E402
    M17_22KW_NORMAL_PWL,
    M17_FAST_SHAPE_SCALED_60KW_PWL,
    curve_for_charging_node,
    spec_for_charging_node,
)
from setp_solver.china81 import ENDOGENOUS_FLEET_PARAMETERS  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.private_instance_rebuild_20260811 import (  # noqa: E402
    DEPOT_CHARGING_22KW,
    load_private_instance_rebuild,
)
from setp_solver.solution import Route, Solution  # noqa: E402


INSTANCE_ID = "cn-prd-50c-01-V3-TWO-SHIFT-GZ-FS"
DEPOTSWAP_INSTANCE_ID = "cn-jjj-50c-01-V3-TWO-SHIFT-DEPOTSWAP"


@pytest.fixture(scope="module")
def rebuilt_context():
    repo = Path(__file__).parents[2]
    return _build_context(
        repo,
        INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )


def test_rebuilt_health_witness_is_search_allowed_and_fully_feasible(
    rebuilt_context,
) -> None:
    bundle, initial, _neutral, context = rebuilt_context
    evaluation = DutyFullEvaluator(context).evaluate(initial)
    customers = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    served = {
        customer
        for duty in initial.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }

    assert bundle.formal_search_allowed is True
    assert context.fairness_enabled is False
    assert context.shift_aware_departure_enabled is True
    assert context.independent_profit_identity.externally_frozen is False
    assert context.independent_profit_identity.source_id == (
        "fairness-disabled-neutral-not-pi0"
    )
    assert evaluation.feasible
    assert served == set(customers)
    assert sum(customers[item].demand for item in served) == pytest.approx(
        sum(node.demand for node in customers.values())
    )


def test_depotswap_witness_departures_respect_shift_starts() -> None:
    repo = Path(__file__).parents[2]
    _bundle, initial, _neutral, context = _build_context(
        repo,
        DEPOTSWAP_INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )
    assert context.shift_aware_departure_enabled is True
    assert context.rebuilt_route_constraints is not None

    evaluation = DutyFullEvaluator(context).evaluate(initial)
    routes = {
        route.vehicle_id: route for route in evaluation.prepared_solution.routes
    }
    departures: dict[str, float] = {}
    for trip in evaluation.certificate.trips:
        shifts = {
            context.rebuilt_route_constraints.customer_shift_by_id[node_id]
            for node_id in routes[trip.route_id].node_sequence[1:-1]
            if node_id
            in context.rebuilt_route_constraints.customer_shift_by_id
        }
        assert len(shifts) == 1
        shift_id = next(iter(shifts))
        shift_start = context.rebuilt_route_constraints.shift_window_second_by_id[
            shift_id
        ][0]
        assert trip.departure_second >= shift_start
        departures[trip.route_id] = trip.departure_second

    assert evaluation.feasible
    assert not evaluation.violations
    assert len(departures) == 16
    assert departures["CV_D_beijing_sanjianfang_1#T2"] == 46_800.0


def test_rebuilt_depot_charging_defaults_to_registered_60kw_and_keeps_22kw() -> None:
    repo = Path(__file__).parents[2]
    default_bundle = load_private_instance_rebuild(repo)
    legacy_scenario_bundle = load_private_instance_rebuild(
        repo,
        depot_charging_scenario=DEPOT_CHARGING_22KW,
    )

    assert default_bundle.prices.depot_charge_power_kw == pytest.approx(60.0)
    assert default_bundle.prices.depot_charging_curve_id == (
        M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id
    )
    default_ev = default_bundle.instance.vehicle_parameters["ev"]
    assert default_ev.non_energy_distance_cost_per_km == pytest.approx(0.9145)
    assert default_ev.source_ids.count(
        "BATTERY_DEPRECIATION_CHANGJIANG_2024_GOEKE_SCHNEIDER_2015"
    ) == 1
    assert {
        node.charge_power_kw
        for node in default_bundle.instance.nodes
        if node.node_type.lower() == "d"
    } == {60.0}
    assert legacy_scenario_bundle.prices.depot_charge_power_kw == pytest.approx(
        22.0
    )
    assert legacy_scenario_bundle.prices.depot_charging_curve_id == (
        M17_22KW_NORMAL_PWL.curve_id
    )


def test_ev_daily_premium_enters_full_and_incremental_candidate_cost(
    rebuilt_context,
) -> None:
    bundle, initial, _neutral, context = rebuilt_context
    duties = {duty.physical_vehicle_id: duty for duty in initial.duties}
    source = duties["CV_D_guangzhou_4"]
    target = duties["EV_D_guangzhou_1"]
    assert source.trips and not target.trips
    source_trip = source.trips[0]
    ev_route = Route(
        vehicle_id=f"{target.physical_vehicle_id}#T1",
        vehicle_type="ev",
        home_depot_id=target.home_depot_id,
        node_sequence=[
            target.home_depot_id,
            *source_trip.effective_route_visits,
            target.home_depot_id,
        ],
    )
    energy = evaluate(
        Solution(routes=[ev_route]),
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )["ev_drive_kwh"]
    station = bundle.instance.nodes[bundle.instance.node_index[target.home_depot_id]]
    curve_spec = spec_for_charging_node(
        bundle.prices,
        node_type=station.node_type,
    )
    curve = curve_for_charging_node(
        bundle.prices,
        node_type=station.node_type,
        capacity_kwh=bundle.instance.battery_capacity_kwh(
            fallback=bundle.prices.B_battery_kwh
        ),
        reference_power_kw=bundle.prices.depot_charge_power_kw,
    )
    session = DutyChargingSession(
        trip_index=1,
        station_id=target.home_depot_id,
        energy_kwh=energy,
        occupancy_minutes=curve.duration_seconds(0.0, energy) / 60.0,
        charge_start_second=0.0,
        start_energy_kwh=0.0,
        end_energy_kwh=energy,
        charging_curve_id=curve_spec.curve_id,
    )
    candidate = replace(
        initial,
        duties=tuple(
            replace(duty, trips=())
            if duty.physical_vehicle_id == source.physical_vehicle_id
            else replace(
                duty,
                trips=source.trips,
                charging_sessions=(session,),
            )
            if duty.physical_vehicle_id == target.physical_vehicle_id
            else duty
            for duty in initial.duties
        ),
        source="test-one-duty-ev",
    )
    full = DutyFullEvaluator(context)
    full_result = full.evaluate(candidate)
    assert full_result.feasible
    assert full_result.breakdown["n_veh_ev"] == pytest.approx(1.0)
    assert full_result.breakdown["cost_fix_ev_premium"] == pytest.approx(50.0)
    assert full_result.breakdown["cost_fix"] == pytest.approx(8 * 170.0 + 50.0)

    incremental = DutyIncrementalEvaluator(DutyFullEvaluator(context))
    incremental.seed(initial)
    incremental_result = incremental.evaluate_after_change(
        initial,
        candidate,
        changed_duty_ids={
            source.physical_vehicle_id,
            target.physical_vehicle_id,
        },
        verify_full_truth=True,
    )
    assert incremental_result.total_cost == pytest.approx(full_result.total_cost)
    assert incremental_result.breakdown["cost_fix_ev_premium"] == pytest.approx(
        full_result.breakdown["cost_fix_ev_premium"]
    )


def test_rebuilt_volume_and_1100_return_are_candidate_hard_violations(
    rebuilt_context,
) -> None:
    _bundle, initial, _neutral, context = rebuilt_context
    assert context.rebuilt_route_constraints is not None
    evaluation = DutyFullEvaluator(context).evaluate(initial)
    prepared = evaluation.prepared_solution
    certificate = evaluation.certificate

    route = prepared.routes[0]
    all_customers = tuple(
        context.rebuilt_route_constraints.customer_shift_by_id
    )
    overloaded = replace(
        route,
        node_sequence=[
            route.home_depot_id,
            *all_customers,
            route.home_depot_id,
        ],
    )
    overload_violations = _rebuilt_route_constraint_violations(
        Solution(routes=[overloaded]),
        certificate,
        context.rebuilt_route_constraints,
    )
    assert any(
        violation.type == "CAPACITY" and "Q_volume=7.2" in violation.detail
        for violation in overload_violations
    )

    route_by_id = {item.vehicle_id: item for item in prepared.routes}
    am_scheduled = next(
        trip
        for trip in certificate.trips
        if {
            context.rebuilt_route_constraints.customer_shift_by_id[node_id]
            for node_id in route_by_id[trip.route_id].node_sequence[1:-1]
        }
        == {"AM"}
    )
    late_trip = replace(am_scheduled, return_second=11 * 3600.0 + 60.0)
    late_certificate = replace(
        certificate,
        trips=tuple(
            late_trip if trip.route_id == late_trip.route_id else trip
            for trip in certificate.trips
        ),
    )
    late_violations = _rebuilt_route_constraint_violations(
        prepared,
        late_certificate,
        context.rebuilt_route_constraints,
    )
    assert any(
        violation.type == "TIME_WINDOW"
        and violation.vehicle_id == late_trip.route_id
        and "returns after AM end" in violation.detail
        for violation in late_violations
    )

    customer_by_shift: dict[str, str] = {}
    for customer_id, shift_id in (
        context.rebuilt_route_constraints.customer_shift_by_id.items()
    ):
        customer_by_shift.setdefault(shift_id, customer_id)
    mixed = replace(
        route,
        node_sequence=[
            route.home_depot_id,
            customer_by_shift["AM"],
            customer_by_shift["PM"],
            route.home_depot_id,
        ],
    )
    mixed_violations = _rebuilt_route_constraint_violations(
        Solution(routes=[mixed]),
        certificate,
        context.rebuilt_route_constraints,
    )
    assert any(
        "rebuilt route mixes customer shifts" in violation.detail
        for violation in mixed_violations
    )
