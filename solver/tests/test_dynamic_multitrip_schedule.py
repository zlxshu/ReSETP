from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from setp_solver.instance_loader import Instance, Node
from setp_solver.charging_curve import L100_CONTROL
from setp_solver.cost import evaluate
from setp_solver.prices import UK_2025_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.dynamic_multitrip_schedule import (
    DYNAMIC_CONTRACT_ID,
    DynamicAssetState,
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
    instance_with_inherited_virtual_origins,
    prepare_dynamic_multitrip_solution,
    reschedule_dynamic_charging,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.multitrip_schedule import (
    MultiTripCertificate,
    ScheduledTrip,
    prepare_multitrip_solution,
    route_timing,
)
from setp_solver.solution import ChargingAction, Route, Solution, physical_vehicle_id


ROOT = Path(__file__).resolve().parents[2]
E3 = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
E6 = ROOT / "baselines/e6_fairness/e6_participation_formal_20260714"
INSTANCE = "L-main-threeshift-100c-01"
CASE = f"{INSTANCE}__geographic__seed1__no_loss"


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
    bundle = load_search_bundle(instance_path.parent)
    solution = solution_from_dict(
        json.loads(solution_path.read_text(encoding="utf-8"))
    )
    certificate = _certificate_from_dict(
        json.loads(certificate_path.read_text(encoding="utf-8"))
    )
    prices = replace(
        UK_2025_PRICES,
        B_battery_kwh=280.0,
        initial_ev_battery_kwh=0.0,
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
        UK_2025_PRICES,
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


def test_dynamic_ev_route_keeps_public_station_charge_in_exact_ledger() -> None:
    instance = Instance(
        nodes=[
            Node(
                "D0",
                "d",
                0.0,
                0.0,
                ready_time=0.0,
                due_time=10_000.0,
                charge_power_kw=22.0,
            ),
            Node(
                "F1",
                "f",
                1.0,
                0.0,
                ready_time=0.0,
                due_time=10_000.0,
                charge_power_kw=60.0,
                station_chargers=1,
            ),
            Node(
                "C1",
                "c",
                2.0,
                0.0,
                demand=1.0,
                ready_time=0.0,
                due_time=10_000.0,
            ),
        ],
        distance_matrix=[
            [0.0, 100.0, 200.0],
            [100.0, 0.0, 100.0],
            [200.0, 100.0, 0.0],
        ],
        ev_kwh_per_meter=0.01,
        num_cv=0,
        num_ev=1,
    )
    public = ChargingAction(
        vehicle_id="open-public",
        station_id="F1",
        energy_kwh=2.0,
        occupancy_minutes=2.0,
        charge_start_second=1_000.0,
        start_energy_kwh=1.0,
        end_energy_kwh=3.0,
        charging_curve_id=L100_CONTROL.curve_id,
    )
    source = Solution(
        routes=[
            Route(
                "open-public",
                "ev",
                "D0",
                ["D0", "F1", "C1", "D0"],
            )
        ],
        charging_actions=[public],
    )
    prices = replace(
        UK_2025_PRICES,
        B_battery_kwh=10.0,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
    )
    state = DynamicAssetState("EV_D0_1", "ev", "D0", 100.0, 0.0, 1)

    prepared, certificate = prepare_dynamic_multitrip_solution(
        source,
        instance,
        prices,
        asset_states={state.physical_vehicle_id: state},
        stage_start_second=100.0,
    )

    assert {action.station_id for action in prepared.charging_actions} == {
        "D0",
        "F1",
    }
    public_action = next(
        action
        for action in prepared.charging_actions
        if action.station_id == "F1"
    )
    assert public_action.vehicle_id == "EV_D0_1#T1"
    trip = certificate.trips[0]
    timing = route_timing(
        prepared.routes[0],
        instance,
        prices,
        charging_actions=prepared.charging_actions,
        forced_departure_second=trip.departure_second,
    )
    assert trip.fixed_departure_battery_kwh == pytest.approx(
        timing.required_departure_battery_kwh
    )
    assert trip.in_route_charge_energy_kwh == pytest.approx(2.0)
    assert trip.end_battery_kwh == pytest.approx(
        float(trip.start_battery_kwh)
        + timing.public_charge_energy_kwh
        - timing.drive_energy_kwh
    )


def test_explicit_duty_precedence_prevents_later_trip_from_running_first() -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, ready_time=0.0, due_time=10_000.0),
            Node(
                "C_FIRST",
                "c",
                1.0,
                0.0,
                demand=1.0,
                ready_time=1_000.0,
                due_time=2_000.0,
            ),
            Node(
                "C_SECOND",
                "c",
                2.0,
                0.0,
                demand=1.0,
                ready_time=1_900.0,
                due_time=1_950.0,
            ),
        ],
        distance_matrix=[
            [0.0, 1_000.0, 1_000.0],
            [1_000.0, 0.0, 1_000.0],
            [1_000.0, 1_000.0, 0.0],
        ],
        num_cv=1,
        num_ev=0,
    )
    source = Solution(
        routes=[
            Route("open-first", "cv", "D0", ["D0", "C_FIRST", "D0"]),
            Route("open-second", "cv", "D0", ["D0", "C_SECOND", "D0"]),
        ]
    )
    state = DynamicAssetState("CV_D0_1", "cv", "D0", 0.0, 0.0, 1)

    prepared, certificate = prepare_dynamic_multitrip_solution(
        source,
        instance,
        UK_2025_PRICES,
        asset_states={state.physical_vehicle_id: state},
        stage_start_second=0.0,
        ordered_route_ids=("open-first", "open-second"),
    )

    ordered = sorted(certificate.trips, key=lambda trip: trip.trip_index)
    assert [trip.route_id for trip in ordered] == [
        "CV_D0_1#T1",
        "CV_D0_1#T2",
    ]
    route_customers = [route.node_sequence[1] for route in prepared.routes]
    assert route_customers == ["C_FIRST", "C_SECOND"]
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
        UK_2025_PRICES,
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

    naive_emissions = evaluate(
        naive_solution,
        instance,
        profile,
        prices,
        carbon_quota_kg=float("inf"),
    )["E_ev_indirect"]
    aware_emissions = evaluate(
        aware_solution,
        instance,
        profile,
        prices,
        carbon_quota_kg=float("inf"),
    )["E_ev_indirect"]
    assert aware_emissions <= naive_emissions + 1e-12

    aware_action_by_route = {
        action.vehicle_id: action for action in aware_solution.charging_actions
    }
    ordered = sorted(aware_certificate.trips, key=lambda trip: trip.trip_index)
    for previous, current in zip(ordered, ordered[1:]):
        action = aware_action_by_route.get(current.route_id)
        if action is None:
            continue
        assert previous.charge_start_second == pytest.approx(
            action.charge_start_second
        )
        assert previous.recharge_end_second == pytest.approx(
            action.charge_start_second + action.occupancy_minutes * 60.0
        )

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

    last_charge_end = max(
        action.charge_start_second + action.occupancy_minutes * 60.0
        for action in aware_solution.charging_actions
    )
    final_cut = cut_dynamic_certificate_at_trigger(
        aware_solution,
        aware_certificate,
        instance,
        prices,
        inherited_asset_states={state.physical_vehicle_id: state},
        previous_stage_start_second=1_000.0,
        trigger_second=last_charge_end + 1.0,
    )
    started_trip_energy = sum(
        float(trip.start_battery_kwh or 0.0)
        - float(trip.end_battery_kwh or 0.0)
        for trip in aware_certificate.trips
        if trip.departure_second <= last_charge_end + 1.0
    )
    locked_charge_energy = sum(
        action.energy_kwh for action in final_cut.locked_charging_actions
    )
    assert final_cut.asset_states[state.physical_vehicle_id].remaining_battery_kwh == pytest.approx(
        state.remaining_battery_kwh + locked_charge_energy - started_trip_energy
    )


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
            UK_2025_PRICES,
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
        UK_2025_PRICES,
        asset_states={state.physical_vehicle_id: state},
        stage_start_second=1_000.0,
    )

    assert {physical_vehicle_id(route.vehicle_id) for route in prepared.routes} == {"CV_D0_1"}
    assert len(certificate.trips) == 1
    assert certificate.trips[0].departure_second >= certified_return


def test_in_progress_cut_keeps_entered_arc_and_releases_editable_suffix() -> None:
    prices = replace(
        UK_2025_PRICES,
        B_battery_kwh=100.0,
        initial_ev_battery_kwh=0.0,
    )
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=20_000.0),
            Node("C1", "c", 1.0, 0.0, demand=3.0, due_time=20_000.0, service_time=60.0),
            Node("C2", "c", 2.0, 0.0, demand=7.0, due_time=20_000.0),
        ],
        distance_matrix=[
            [0.0, 1_000.0, 2_000.0],
            [1_000.0, 0.0, 1_000.0],
            [2_000.0, 1_000.0, 0.0],
        ],
        ev_kwh_per_meter=0.001,
        num_cv=0,
        num_ev=1,
    )
    source, certificate = prepare_multitrip_solution(
        Solution(routes=[Route("source", "ev", "D0", ["D0", "C1", "C2", "D0"])]),
        instance,
        prices,
    )
    base_trip = certificate.trips[0]
    reserve_kwh = 10.0
    trip = replace(
        base_trip,
        start_battery_kwh=float(base_trip.start_battery_kwh) + reserve_kwh,
        end_battery_kwh=float(base_trip.end_battery_kwh) + reserve_kwh,
    )
    source = replace(source, charging_actions=[])
    certificate = replace(
        certificate,
        trips=(trip,),
        initial_battery_kwh=trip.start_battery_kwh,
        depot_charge_ledger=(),
    )
    route = source.routes[0]
    first_travel = 1_000.0 / UK_2025_PRICES.v_speed_ms
    second_travel = 1_000.0 / UK_2025_PRICES.v_speed_ms
    trigger = trip.departure_second + first_travel + 60.0 + second_travel / 2.0

    cut = cut_certificate_at_trigger(
        source,
        certificate,
        instance,
        prices,
        trigger_second=trigger,
    )

    state = cut.asset_states["EV_D0_1"]
    assert state.continuation_route_id == route.vehicle_id
    assert state.continuation_trip_index == 1
    assert state.executed_prefix == ("D0", "C1")
    assert state.locked_arc == ("C1", "C2")
    assert state.trigger_arc_progress == pytest.approx(0.5)
    assert state.trigger_remaining_load_kg == pytest.approx(7.0)
    assert state.remaining_load_kg == pytest.approx(7.0)
    assert state.editable_suffix == ("C2",)
    assert cut.frozen_arc_prefix_by_route_id[route.vehicle_id] == (
        ("D0", "C1"),
        ("C1", "C2"),
    )
    assert cut.unexecuted_arc_suffix_by_route_id[route.vehicle_id] == (("C2", "D0"),)

    dynamic_instance = instance_with_inherited_virtual_origins(
        instance,
        cut.asset_states,
    )
    assert dynamic_instance.distance(state.virtual_origin_node_id, "C2") == pytest.approx(0.0)
    continuation = Solution(
        routes=[
            Route(
                "open-continuation",
                "ev",
                "D0",
                [state.virtual_origin_node_id, "C2", "D0"],
            )
        ]
    )
    prepared, dynamic_certificate = prepare_dynamic_multitrip_solution(
        continuation,
        dynamic_instance,
        prices,
        asset_states=cut.asset_states,
        stage_start_second=trigger,
    )
    assert prepared.routes[0].vehicle_id == route.vehicle_id
    assert prepared.routes[0].node_sequence[0] == state.virtual_origin_node_id
    assert dynamic_certificate.trips[0].trip_index == 1
    assert dynamic_certificate.trips[0].departure_second >= state.available_second

    pre_release_trigger = (trigger + state.available_second) / 2.0
    pre_release_cut = cut_dynamic_certificate_at_trigger(
        prepared,
        dynamic_certificate,
        dynamic_instance,
        prices,
        inherited_asset_states=cut.asset_states,
        previous_stage_start_second=trigger,
        trigger_second=pre_release_trigger,
    )
    carried = pre_release_cut.asset_states["EV_D0_1"]
    assert route.vehicle_id in pre_release_cut.in_progress_route_ids
    assert carried.locked_arc == ("C1", "C2")
    assert carried.trigger_arc_progress == pytest.approx(0.75)
    assert carried.release_node_id == "C2"
    assert carried.virtual_origin_node_id == state.virtual_origin_node_id
    assert carried.position_node_id != "D0"
    assert carried.available_second == pytest.approx(state.available_second)
    assert state.trigger_remaining_battery_kwh > carried.trigger_remaining_battery_kwh
    assert carried.trigger_remaining_battery_kwh > carried.remaining_battery_kwh

    returned_with_cargo, cargo_certificate = prepare_dynamic_multitrip_solution(
        Solution(
            routes=[
                Route(
                    "open-return-with-cargo",
                    "ev",
                    "D0",
                    [state.virtual_origin_node_id, "D0"],
                )
            ]
        ),
        dynamic_instance,
        prices,
        asset_states=cut.asset_states,
        stage_start_second=trigger,
    )
    cargo_trip = cargo_certificate.trips[0]
    cargo_trigger = (cargo_trip.departure_second + cargo_trip.return_second) / 2.0
    cargo_cut = cut_dynamic_certificate_at_trigger(
        returned_with_cargo,
        cargo_certificate,
        dynamic_instance,
        prices,
        inherited_asset_states=cut.asset_states,
        previous_stage_start_second=trigger,
        trigger_second=cargo_trigger,
    )
    cargo_state = cargo_cut.asset_states["EV_D0_1"]
    assert cargo_state.remaining_load_kg == pytest.approx(7.0)
    assert cargo_state.trigger_remaining_load_kg == pytest.approx(7.0)
    assert cargo_state.continuation_route_id is None
    assert cargo_state.in_progress_route_id == route.vehicle_id
    assert state.remaining_battery_kwh > cargo_state.trigger_remaining_battery_kwh
    assert cargo_state.trigger_remaining_battery_kwh > cargo_state.remaining_battery_kwh

    empty_future, empty_certificate = prepare_dynamic_multitrip_solution(
        Solution(),
        dynamic_instance,
        prices,
        asset_states=cargo_cut.asset_states,
        stage_start_second=cargo_trigger,
    )
    later_cargo_cut = cut_dynamic_certificate_at_trigger(
        empty_future,
        empty_certificate,
        dynamic_instance,
        prices,
        inherited_asset_states=cargo_cut.asset_states,
        previous_stage_start_second=cargo_trigger,
        trigger_second=(cargo_trigger + cargo_trip.return_second) / 2.0,
    )
    later_cargo_state = later_cargo_cut.asset_states["EV_D0_1"]
    assert later_cargo_state.remaining_load_kg == pytest.approx(7.0)
    assert later_cargo_state.position_node_id != "D0"
    assert (
        later_cargo_state.trigger_remaining_battery_kwh
        < cargo_state.trigger_remaining_battery_kwh
    )
    assert (
        later_cargo_state.trigger_remaining_battery_kwh
        > later_cargo_state.remaining_battery_kwh
    )

    continued_trip = dynamic_certificate.trips[0]
    second_trigger = (
        continued_trip.departure_second + continued_trip.return_second
    ) / 2.0
    second_cut = cut_dynamic_certificate_at_trigger(
        prepared,
        dynamic_certificate,
        dynamic_instance,
        prices,
        inherited_asset_states=cut.asset_states,
        previous_stage_start_second=trigger,
        trigger_second=second_trigger,
    )
    second_state = second_cut.asset_states["EV_D0_1"]
    assert second_state.locked_arc == ("C2", "D0")
    assert second_state.continuation_route_id is None
    assert second_state.release_node_id == "D0"
    assert second_state.next_trip_index == 2






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
        UK_2025_PRICES,
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
