from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.dynamic_multitrip_schedule import (
    DYNAMIC_CONTRACT_ID,
    DynamicAssetState,
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
    prepare_dynamic_multitrip_solution,
    reschedule_dynamic_charging,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.multitrip_schedule import MultiTripCertificate, ScheduledTrip
from setp_solver.solution import ChargingAction, Route, Solution, physical_vehicle_id


ROOT = Path(__file__).resolve().parents[2]
E3 = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
E6 = ROOT / "baselines/e6_fairness/e6_participation_formal_20260714"
INSTANCE = "L-main-threeshift-100c-01"
CASE = f"{INSTANCE}__geographic__seed1__no_loss"
FROZEN_INSTANCE_SHA256 = "59696be304ad9f3c484820439e1cbdb027945e20ad7ecbdb8542dfde7e0d6225"
FROZEN_SOLUTION_SHA256 = "eff30569aea5953b8b9b52707e6f15bb7c1f44f3b17f3bea7bda334e389e62af"
FROZEN_CERTIFICATE_SHA256 = "7127dada4e9942a303155429fb42f83cc6c6952a344d4c8a5d9c4727f5e919d0"


def _certificate_from_dict(payload: dict[str, object]) -> MultiTripCertificate:
    return MultiTripCertificate(
        contract_id=str(payload["contract_id"]),
        status=str(payload["status"]),
        vehicle_counts={
            str(key): int(value)
            for key, value in dict(payload["vehicle_counts"]).items()  # type: ignore[arg-type]
        },
        trips=tuple(
            ScheduledTrip(**row)
            for row in payload["trips"]  # type: ignore[union-attr]
        ),
        recharge_mode=str(payload["recharge_mode"]),
        depot_charge_power_kw=float(payload["depot_charge_power_kw"]),
        first_trip_charge_day_offset=int(payload["first_trip_charge_day_offset"]),
    )


def _formal_221_customer_case():
    instance_path = E3 / "assets" / INSTANCE / "bundle" / "instance.json"
    solution_path = E6 / "solutions" / f"{CASE}.json"
    certificate_path = E6 / "certificates" / f"{CASE}.json"
    assert hashlib.sha256(instance_path.read_bytes()).hexdigest() == FROZEN_INSTANCE_SHA256
    assert hashlib.sha256(solution_path.read_bytes()).hexdigest() == FROZEN_SOLUTION_SHA256
    assert hashlib.sha256(certificate_path.read_bytes()).hexdigest() == FROZEN_CERTIFICATE_SHA256
    bundle = load_search_bundle(instance_path.parent)
    solution = solution_from_dict(
        json.loads(solution_path.read_text(encoding="utf-8"))
    )
    certificate = _certificate_from_dict(
        json.loads(certificate_path.read_text(encoding="utf-8"))
    )
    prices = replace(
        DEFAULT_PRICES,
        B_battery_kwh=280.0,
        initial_ev_battery_kwh=0.0,
        cross_site_cost=0.0,
        carbon_price=0.0,
    )
    assert sum(node.node_type.lower() == "c" for node in bundle.instance.nodes) == 221
    assert bundle.instance.num_cv == 10
    assert bundle.instance.num_ev == 10
    return solution, certificate, bundle, prices


def test_exact_asset_scheduler_reuses_inherited_id_and_trip_sequence() -> None:
    nodes = [
        Node("D0", "d", 0.0, 0.0, ready_time=0.0, due_time=30_000.0),
        Node("C1", "c", 1.0, 0.0, demand=1.0, ready_time=5_000.0, due_time=8_000.0),
        Node("C2", "c", 2.0, 0.0, demand=1.0, ready_time=12_000.0, due_time=15_000.0),
    ]
    instance = Instance(
        nodes=nodes,
        distance_matrix=[
            [0.0, 1_000.0, 1_000.0],
            [1_000.0, 0.0, 1_000.0],
            [1_000.0, 1_000.0, 0.0],
        ],
        num_cv=0,
        num_ev=1,
    )
    source = Solution(
        routes=[
            Route("open-a", "ev", "D0", ["D0", "C1", "D0"]),
            Route("open-b", "ev", "D0", ["D0", "C2", "D0"]),
        ]
    )
    prices = replace(
        DEFAULT_PRICES,
        B_battery_kwh=20.0,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
    )
    state = DynamicAssetState("EV_D0_7", "ev", "D0", 100.0, 0.0, 3)

    prepared, certificate = prepare_dynamic_multitrip_solution(
        source,
        instance,
        prices,
        asset_states={state.physical_vehicle_id: state},
        stage_start_second=100.0,
    )

    assert certificate.contract_id == DYNAMIC_CONTRACT_ID
    assert certificate.vehicle_counts == {"cv": 0, "ev": 1}
    assert [trip.trip_index for trip in sorted(certificate.trips, key=lambda trip: trip.trip_index)] == [3, 4]
    assert {physical_vehicle_id(route.vehicle_id) for route in prepared.routes} == {"EV_D0_7"}
    assert {route.vehicle_id for route in prepared.routes} == {"EV_D0_7#T3", "EV_D0_7#T4"}
    assert all(action.charge_day_offset == 0 for action in prepared.charging_actions)
    assert all(action.charge_start_second >= 100.0 for action in prepared.charging_actions)
    ordered = sorted(certificate.trips, key=lambda trip: trip.trip_index)
    assert ordered[1].departure_second >= ordered[0].return_second


def test_dynamic_carbon_timing_stays_after_stage_start_and_survives_next_cut() -> None:
    nodes = [
        Node("D0", "d", 0.0, 0.0, ready_time=0.0, due_time=30_000.0),
        Node("C1", "c", 1.0, 0.0, demand=1.0, ready_time=6_000.0, due_time=7_000.0),
        Node("C2", "c", 2.0, 0.0, demand=1.0, ready_time=14_000.0, due_time=15_000.0),
    ]
    instance = Instance(
        nodes=nodes,
        distance_matrix=[
            [0.0, 1_000.0, 1_000.0],
            [1_000.0, 0.0, 1_000.0],
            [1_000.0, 1_000.0, 0.0],
        ],
        num_cv=0,
        num_ev=1,
    )
    prices = replace(
        DEFAULT_PRICES,
        B_battery_kwh=20.0,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
    )
    state = DynamicAssetState("EV_D0_7", "ev", "D0", 1_000.0, 0.0, 3)
    source = Solution(
        routes=[
            Route("open-a", "ev", "D0", ["D0", "C1", "D0"]),
            Route("open-b", "ev", "D0", ["D0", "C2", "D0"]),
        ]
    )
    prepared, certificate = prepare_dynamic_multitrip_solution(
        source,
        instance,
        prices,
        asset_states={state.physical_vehicle_id: state},
        stage_start_second=1_000.0,
    )
    assert prepared.charging_actions
    profile = [
        {
            "time_index": index,
            "horizon_second_start": float(index * 1_800),
            "actual_gco2_per_kwh": 800.0 if index < 3 else 50.0,
            "forecast_gco2_per_kwh": 800.0 if index < 3 else 50.0,
        }
        for index in range(48)
    ]

    naive_solution, naive_certificate, _ = reschedule_dynamic_charging(
        prepared,
        certificate,
        instance,
        profile,
        prices,
        asset_states={state.physical_vehicle_id: state},
        stage_start_second=1_000.0,
        strategy="naive",
    )
    aware_solution, aware_certificate, stats = reschedule_dynamic_charging(
        prepared,
        certificate,
        instance,
        profile,
        prices,
        asset_states={state.physical_vehicle_id: state},
        stage_start_second=1_000.0,
        strategy="aware",
    )

    assert all(action.charge_day_offset == 0 for action in aware_solution.charging_actions)
    assert all(action.charge_start_second >= 1_000.0 for action in aware_solution.charging_actions)
    assert stats["moved_action_count"] >= 1
    naive_starts = {action.vehicle_id: action.charge_start_second for action in naive_solution.charging_actions}
    aware_starts = {action.vehicle_id: action.charge_start_second for action in aware_solution.charging_actions}
    assert any(aware_starts[route_id] > naive_starts[route_id] for route_id in aware_starts)

    first_shifted_route = next(
        route_id for route_id in aware_starts if aware_starts[route_id] > naive_starts[route_id]
    )
    trigger = (aware_starts[first_shifted_route] + naive_starts[first_shifted_route]) / 2.0
    naive_cut = cut_dynamic_certificate_at_trigger(
        naive_solution,
        naive_certificate,
        instance,
        prices,
        inherited_asset_states={state.physical_vehicle_id: state},
        previous_stage_start_second=1_000.0,
        trigger_second=trigger,
    )
    aware_cut = cut_dynamic_certificate_at_trigger(
        aware_solution,
        aware_certificate,
        instance,
        prices,
        inherited_asset_states={state.physical_vehicle_id: state},
        previous_stage_start_second=1_000.0,
        trigger_second=trigger,
    )
    assert len(naive_cut.locked_charging_actions) > len(aware_cut.locked_charging_actions)


def test_added_order_is_rejected_when_sole_in_progress_asset_returns_too_late() -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, ready_time=0.0, due_time=20_000.0),
            Node(
                "N_NEW",
                "c",
                1.0,
                0.0,
                demand=1.0,
                ready_time=0.0,
                due_time=4_000.0,
            ),
        ],
        distance_matrix=[[0.0, 1_000.0], [1_000.0, 0.0]],
        num_cv=1,
        num_ev=0,
    )
    added_trip = Solution(
        routes=[Route("S1_ADD_E1", "cv", "D0", ["D0", "N_NEW", "D0"])]
    )
    certified_return = 5_000.0
    state = DynamicAssetState("CV_D0_1", "cv", "D0", certified_return, 0.0, 2)

    with pytest.raises(ValueError, match="no inherited asset can serve open route"):
        prepare_dynamic_multitrip_solution(
            added_trip,
            instance,
            DEFAULT_PRICES,
            asset_states={state.physical_vehicle_id: state},
            stage_start_second=1_000.0,
        )


def test_added_order_waits_for_sole_in_progress_asset_to_return_to_depot() -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, ready_time=0.0, due_time=20_000.0),
            Node(
                "N_NEW",
                "c",
                1.0,
                0.0,
                demand=1.0,
                ready_time=5_500.0,
                due_time=8_000.0,
            ),
        ],
        distance_matrix=[[0.0, 1_000.0], [1_000.0, 0.0]],
        num_cv=1,
        num_ev=0,
    )
    added_trip = Solution(
        routes=[Route("S1_ADD_E1", "cv", "D0", ["D0", "N_NEW", "D0"])]
    )
    certified_return = 5_000.0
    state = DynamicAssetState("CV_D0_1", "cv", "D0", certified_return, 0.0, 2)

    prepared, certificate = prepare_dynamic_multitrip_solution(
        added_trip,
        instance,
        DEFAULT_PRICES,
        asset_states={state.physical_vehicle_id: state},
        stage_start_second=1_000.0,
    )

    assert {physical_vehicle_id(route.vehicle_id) for route in prepared.routes} == {"CV_D0_1"}
    assert len(certificate.trips) == 1
    assert certificate.trips[0].departure_second >= certified_return


def test_frozen_221_customer_cut_and_one_event_continuation_use_only_10_plus_10_assets() -> None:
    solution, certificate, bundle, prices = _formal_221_customer_case()
    trigger = 30_000.0
    cut = cut_certificate_at_trigger(
        solution,
        certificate,
        bundle.instance,
        prices,
        trigger_second=trigger,
    )

    partition = (
        set(cut.completed_route_ids)
        | set(cut.in_progress_route_ids)
        | set(cut.editable_route_ids)
    )
    assert len(partition) == len(certificate.trips)
    assert set(cut.completed_route_ids).isdisjoint(cut.in_progress_route_ids)
    assert set(cut.completed_route_ids).isdisjoint(cut.editable_route_ids)
    assert set(cut.in_progress_route_ids).isdisjoint(cut.editable_route_ids)
    assert all((cut.completed_route_ids, cut.in_progress_route_ids, cut.editable_route_ids))
    assert sum(state.vehicle_type == "cv" for state in cut.asset_states.values()) == 10
    assert sum(state.vehicle_type == "ev" for state in cut.asset_states.values()) == 10

    # EV_D0_5 is still serving T1 at the trigger.  It must be released at the
    # certified return with that trip's end battery; its not-yet-started T2
    # charge is deliberately not inherited.
    frozen_t1 = next(trip for trip in certificate.trips if trip.route_id == "EV_D0_5#T1")
    asset = cut.asset_states["EV_D0_5"]
    assert asset.available_second == pytest.approx(frozen_t1.return_second)
    assert asset.remaining_battery_kwh == pytest.approx(frozen_t1.end_battery_kwh)
    assert asset.next_trip_index == 2

    route_lookup = {route.vehicle_id: route for route in solution.routes}
    original = route_lookup["EV_D0_5#T2"]
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    customers = [
        node_id
        for node_id in original.node_sequence
        if node_lookup[node_id].node_type.lower() == "c"
    ]
    cancelled_customer = customers[0]
    open_routes = []
    for index, route_id in enumerate(cut.editable_route_ids):
        route = route_lookup[route_id]
        sequence = list(route.node_sequence)
        if route_id == original.vehicle_id:
            sequence = [node_id for node_id in sequence if node_id != cancelled_customer]
        open_routes.append(replace(route, vehicle_id=f"open-{index}", node_sequence=sequence))
    expected_customers = {
        node_id
        for route in open_routes
        for node_id in route.node_sequence
        if node_lookup[node_id].node_type.lower() == "c"
    }
    prepared, dynamic_certificate = prepare_dynamic_multitrip_solution(
        Solution(routes=open_routes),
        bundle.instance,
        prices,
        asset_states=cut.asset_states,
        stage_start_second=trigger,
        locked_charging_actions=cut.locked_charging_actions,
    )

    assert dynamic_certificate.contract_id == DYNAMIC_CONTRACT_ID
    used_assets = {physical_vehicle_id(route.vehicle_id) for route in prepared.routes}
    assert len(prepared.routes) == len(cut.editable_route_ids)
    assert used_assets <= set(cut.asset_states)
    assert dynamic_certificate.vehicle_counts["cv"] <= 10
    assert dynamic_certificate.vehicle_counts["ev"] <= 10
    observed_customers = {
        node_id
        for route in prepared.routes
        for node_id in route.node_sequence
        if node_lookup[node_id].node_type.lower() == "c"
    }
    assert observed_customers == expected_customers
    assert cancelled_customer not in observed_customers
    assert all(
        trip.trip_index >= cut.asset_states[trip.physical_vehicle_id].next_trip_index
        for trip in dynamic_certificate.trips
    )
    assert all(action.charge_day_offset == 0 for action in prepared.charging_actions)
    assert all(action.charge_start_second >= trigger for action in prepared.charging_actions)


def test_frozen_221_customer_plan_can_be_cut_again_without_losing_idle_assets() -> None:
    solution, certificate, bundle, prices = _formal_221_customer_case()
    first_trigger = 30_000.0
    first_cut = cut_certificate_at_trigger(
        solution,
        certificate,
        bundle.instance,
        prices,
        trigger_second=first_trigger,
    )
    route_lookup = {route.vehicle_id: route for route in solution.routes}
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    first_open = [
        replace(route_lookup[route_id], vehicle_id=f"first-open-{index}")
        for index, route_id in enumerate(first_cut.editable_route_ids)
    ]
    first_plan, first_certificate = prepare_dynamic_multitrip_solution(
        Solution(routes=first_open),
        bundle.instance,
        prices,
        asset_states=first_cut.asset_states,
        stage_start_second=first_trigger,
        locked_charging_actions=first_cut.locked_charging_actions,
    )

    second_trigger = 51_000.0
    second_cut = cut_dynamic_certificate_at_trigger(
        first_plan,
        first_certificate,
        bundle.instance,
        prices,
        inherited_asset_states=first_cut.asset_states,
        previous_stage_start_second=first_trigger,
        trigger_second=second_trigger,
        inherited_locked_charging_actions=first_cut.locked_charging_actions,
    )

    assert len(second_cut.asset_states) == 20
    assert sum(state.vehicle_type == "cv" for state in second_cut.asset_states.values()) == 10
    assert sum(state.vehicle_type == "ev" for state in second_cut.asset_states.values()) == 10
    assert all(
        (
            second_cut.completed_route_ids,
            second_cut.in_progress_route_ids,
            second_cut.editable_route_ids,
        )
    )
    assert (
        len(second_cut.completed_route_ids)
        + len(second_cut.in_progress_route_ids)
        + len(second_cut.editable_route_ids)
        == len(first_certificate.trips)
    )

    running_charges = [
        action
        for action in first_plan.charging_actions
        if action.charge_start_second < second_trigger
        < action.charge_start_second + action.occupancy_minutes * 60.0
    ]
    assert running_charges
    running_action = running_charges[0]
    running_trip = next(
        trip for trip in first_certificate.trips if trip.route_id == running_action.vehicle_id
    )
    running_state = second_cut.asset_states[running_trip.physical_vehicle_id]
    assert running_state.available_second == pytest.approx(
        running_action.charge_start_second + running_action.occupancy_minutes * 60.0
    )
    assert running_state.remaining_battery_kwh == pytest.approx(running_trip.start_battery_kwh)
    assert running_state.next_trip_index == running_trip.trip_index

    first_plan_lookup = {route.vehicle_id: route for route in first_plan.routes}
    second_open = []
    cancelled_customer = None
    for index, route_id in enumerate(second_cut.editable_route_ids):
        route = first_plan_lookup[route_id]
        sequence = list(route.node_sequence)
        if cancelled_customer is None:
            customers = [
                node_id
                for node_id in sequence
                if node_lookup[node_id].node_type.lower() == "c"
            ]
            if len(customers) > 1:
                cancelled_customer = customers[0]
                sequence = [node_id for node_id in sequence if node_id != cancelled_customer]
        second_open.append(replace(route, vehicle_id=f"second-open-{index}", node_sequence=sequence))
    assert cancelled_customer is not None
    second_plan, second_certificate = prepare_dynamic_multitrip_solution(
        Solution(routes=second_open),
        bundle.instance,
        prices,
        asset_states=second_cut.asset_states,
        stage_start_second=second_trigger,
        locked_charging_actions=second_cut.locked_charging_actions,
    )

    assert cancelled_customer not in {
        node_id
        for route in second_plan.routes
        for node_id in route.node_sequence
    }
    assert {
        physical_vehicle_id(route.vehicle_id) for route in second_plan.routes
    } <= set(second_cut.asset_states)
    assert all(
        trip.trip_index >= second_cut.asset_states[trip.physical_vehicle_id].next_trip_index
        for trip in second_certificate.trips
    )


def test_dynamic_scheduler_counts_a_locked_charge_against_one_depot_charger() -> None:
    instance = Instance(
        nodes=[
            Node(
                "D0",
                "d",
                0.0,
                0.0,
                ready_time=0.0,
                due_time=30_000.0,
                station_chargers=1,
            ),
            Node("C1", "c", 1.0, 0.0, demand=1.0, ready_time=10_000.0, due_time=12_000.0),
            Node("C2", "c", 2.0, 0.0, demand=1.0, ready_time=10_000.0, due_time=12_000.0),
        ],
        distance_matrix=[
            [0.0, 1_000.0, 1_000.0],
            [1_000.0, 0.0, 1_000.0],
            [1_000.0, 1_000.0, 0.0],
        ],
        num_cv=0,
        num_ev=2,
    )
    source = Solution(
        routes=[
            Route("open-a", "ev", "D0", ["D0", "C1", "D0"]),
        ]
    )
    prices = replace(
        DEFAULT_PRICES,
        B_battery_kwh=20.0,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
    )
    states = {
        "EV_D0_1": DynamicAssetState("EV_D0_1", "ev", "D0", 0.0, 0.0, 1),
        "EV_D0_2": DynamicAssetState(
            "EV_D0_2",
            "ev",
            "D0",
            9_000.0 + 20.0 / 22.0 * 3_600.0,
            20.0,
            1,
        ),
    }
    locked = ChargingAction(
        "EV_D0_2#T1",
        "D0",
        energy_kwh=20.0,
        occupancy_minutes=20.0 / 22.0 * 60.0,
        charge_start_second=9_000.0,
    )

    with pytest.raises(ValueError, match="charger capacity exceeded"):
        prepare_dynamic_multitrip_solution(
            source,
            instance,
            prices,
            asset_states=states,
            stage_start_second=0.0,
            locked_charging_actions=(locked,),
        )


def test_dynamic_scheduler_rejects_open_routes_without_inherited_assets() -> None:
    instance = Instance(
        nodes=[Node("D0", "d", 0.0, 0.0, due_time=10_000.0)],
        distance_matrix=[[0.0]],
    )
    with pytest.raises(ValueError, match="no inherited assets"):
        prepare_dynamic_multitrip_solution(
            Solution(routes=[Route("open", "cv", "D0", ["D0", "D0"])]),
            instance,
            asset_states={},
            stage_start_second=0.0,
        )
