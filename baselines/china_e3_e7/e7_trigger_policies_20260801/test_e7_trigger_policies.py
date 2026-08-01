from __future__ import annotations

from dataclasses import replace

import pytest

from baselines.china_e3_e7.e7_trigger_policies_20260801.dynamic_adapter import (
    PlanAttempt,
    admit_new_orders_or_reject_individually,
    inject_full_fleet_asset_states,
)
from baselines.china_e3_e7.e7_trigger_policies_20260801.trigger_policies import (
    FIXED_30_MINUTES,
    HYBRID_500KG_OR_30_MINUTES,
    PER_ORDER,
    QIU_REDUCED_DEMAND_FACTOR,
    DynamicOrder,
    DynamicUpdate,
    build_dynamic_orders,
    build_qiu_scaled_stream,
    build_trigger_batches,
    dynamic_order_sha256,
    dynamic_stream_sha256,
)
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.dynamic_multitrip_schedule import (
    DynamicAssetState,
    prepare_dynamic_multitrip_solution,
)
from setp_solver.solution import Route, Solution, physical_vehicle_id


def _order(customer_id: str, minute: float, demand: float, due_minute: float = 700.0) -> DynamicOrder:
    return DynamicOrder(
        event_id=f"ADD_{customer_id}",
        customer_id=customer_id,
        appearance_second=minute * 60.0,
        demand_kg=demand,
        x=1.0,
        y=1.0,
        ready_second=minute * 60.0,
        due_second=due_minute * 60.0,
        service_second=300.0,
        city="test",
    )


def test_hybrid_uses_500kg_or_30_minutes_and_window_end_tail() -> None:
    orders = (
        _order("C1", 485.0, 240.0),
        _order("C2", 490.0, 260.0),
        _order("C3", 535.0, 100.0),
        _order("C4", 595.0, 100.0),
    )
    batches = build_trigger_batches(orders, HYBRID_500KG_OR_30_MINUTES)

    assert [(batch.trigger_second / 60.0, batch.cause, batch.customer_ids) for batch in batches] == [
        (490.0, "demand_threshold", ("C1", "C2")),
        (550.0, "maximum_wait", ("C3",)),
        (600.0, "window_end", ("C4",)),
    ]


def test_three_policies_consume_exactly_the_same_orders() -> None:
    orders = (_order("C1", 481.0, 100.0), _order("C2", 510.0, 150.0), _order("C3", 599.0, 200.0))
    expected_hash = dynamic_order_sha256(orders)
    expected_ids = sorted(order.event_id for order in orders)
    for policy in (PER_ORDER, FIXED_30_MINUTES, HYBRID_500KG_OR_30_MINUTES):
        batches = build_trigger_batches(orders, policy)
        assert sorted(event_id for batch in batches for event_id in batch.event_ids) == expected_ids
        assert dynamic_order_sha256(orders) == expected_hash


def test_cancel_and_reduction_do_not_count_towards_500kg_threshold() -> None:
    events = (
        DynamicUpdate("CANCEL_C0", "cancel", "C0", 485.0 * 60.0, 200.0, 0.0),
        DynamicUpdate("REDUCE_C9", "demand_change", "C9", 486.0 * 60.0, 200.0, 160.0),
        _order("C1", 490.0, 300.0),
        _order("C2", 491.0, 200.0),
    )
    batches = build_trigger_batches(events, HYBRID_500KG_OR_30_MINUTES)

    assert len(batches) == 1
    assert batches[0].trigger_second == 491.0 * 60.0
    assert batches[0].cause == "demand_threshold"
    assert batches[0].demand_kg == 500.0
    assert set(batches[0].event_types) == {"add", "cancel", "demand_change"}


def test_simultaneous_information_is_processed_in_one_arrival_batch() -> None:
    events = (
        _order("C1", 490.0, 100.0),
        _order("C2", 490.0, 200.0),
        DynamicUpdate("CANCEL_C0", "cancel", "C0", 490.0 * 60.0, 300.0, 0.0),
    )
    batches = build_trigger_batches(events, PER_ORDER)

    assert len(batches) == 1
    assert set(batches[0].customer_ids) == {"C0", "C1", "C2"}


def test_original_china81_fields_are_reused_and_born_expired_is_rejected() -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=86_400.0),
            Node("C1", "c", 1.2, 3.4, demand=321.0, ready_time=33_000.0, due_time=35_000.0, service_time=420.0, city="x"),
        ],
        distance_matrix=[[0.0, 1.0], [1.0, 0.0]],
    )
    built = build_dynamic_orders(instance, {"C1": 30_000.0})
    assert built[0].demand_kg == 321.0
    assert (built[0].x, built[0].y) == (1.2, 3.4)
    assert (built[0].ready_second, built[0].due_second, built[0].service_second) == (33_000.0, 35_000.0, 420.0)
    event = built[0].as_solver_event()
    assert (event.new_demand, event.new_ready_time, event.new_due_time, event.new_service_time) == (321.0, 33_000.0, 35_000.0, 420.0)
    with pytest.raises(ValueError, match="strictly before"):
        build_dynamic_orders(instance, {"C1": 35_000.0})


def test_qiu_pattern_scales_to_50_customers_without_changing_the_instance() -> None:
    customers = [
        Node(
            f"C{index:02d}",
            "c",
            float(index),
            1.0,
            demand=100.0 + index,
            ready_time=6.0 * 3600.0,
            due_time=18.0 * 3600.0,
            service_time=300.0,
            city="x",
        )
        for index in range(50)
    ]
    instance = Instance(
        nodes=[Node("D0", "d", 0.0, 0.0, due_time=86_400.0), *customers],
        distance_matrix=[[0.0] * 51 for _ in range(51)],
    )

    stream = build_qiu_scaled_stream(instance, instance_id="case50", stream_seed=1)
    repeated = build_qiu_scaled_stream(instance, instance_id="case50", stream_seed=1)
    other_seed = build_qiu_scaled_stream(instance, instance_id="case50", stream_seed=2)
    event_types = [event.as_solver_event().event_type for event in stream.events]
    initial = set(stream.initial_customer_ids)
    additions = {event.customer_id for event in stream.events if isinstance(event, DynamicOrder)}
    cancellations = {
        event.customer_id
        for event in stream.events
        if isinstance(event, DynamicUpdate) and event.event_type == "cancel"
    }
    reductions = [
        event
        for event in stream.events
        if isinstance(event, DynamicUpdate) and event.event_type == "demand_change"
    ]

    assert len(initial) == 40
    assert event_types.count("add") == 10
    assert event_types.count("cancel") == 4
    assert event_types.count("demand_change") == 2
    assert additions.isdisjoint(initial)
    assert cancellations <= initial
    assert {event.customer_id for event in reductions} <= initial
    assert cancellations.isdisjoint(event.customer_id for event in reductions)
    assert all(event.new_demand_kg == pytest.approx(event.old_demand_kg * QIU_REDUCED_DEMAND_FACTOR) for event in reductions)
    assert all(event.appearance_second < event.due_second for event in stream.events if isinstance(event, DynamicOrder))
    assert dynamic_stream_sha256(stream) == dynamic_stream_sha256(repeated)
    assert dynamic_stream_sha256(stream) != dynamic_stream_sha256(other_seed)


def test_unused_legal_vehicle_is_injected_and_mobilized_by_existing_scheduler() -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=30_000.0),
            Node("C1", "c", 1.0, 0.0, demand=1.0, ready_time=1_500.0, due_time=3_000.0),
        ],
        distance_matrix=[[0.0, 1_000.0], [1_000.0, 0.0]],
        num_cv=2,
        num_ev=0,
    )
    busy = DynamicAssetState("CV_D0_1", "cv", "D0", 10_000.0, 0.0, 2)
    full = inject_full_fleet_asset_states(
        {busy.physical_vehicle_id: busy},
        {"D0": {"num_cv": 2, "num_ev": 0}},
        available_second=1_000.0,
        unused_ev_battery_kwh=0.0,
    )
    source = Solution(routes=[Route("open-C1", "cv", "D0", ["D0", "C1", "D0"])])
    prepared, _ = prepare_dynamic_multitrip_solution(
        source,
        instance,
        DEFAULT_PRICES,
        asset_states=full,
        stage_start_second=1_000.0,
    )
    assert set(full) == {"CV_D0_1", "CV_D0_2"}
    assert {physical_vehicle_id(route.vehicle_id) for route in prepared.routes} == {"CV_D0_2"}


def test_unserviceable_order_is_rejected_without_killing_the_unit() -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=30_000.0),
            Node("C_OK", "c", 1.0, 0.0, demand=10.0, ready_time=2_500.0, due_time=5_000.0),
            Node("C_NO", "c", 2.0, 0.0, demand=20.0, ready_time=1_000.0, due_time=1_500.0),
        ],
        distance_matrix=[[0.0, 1_000.0, 1_000.0], [1_000.0, 0.0, 1_000.0], [1_000.0, 1_000.0, 0.0]],
        num_cv=1,
        num_ev=0,
    )
    states = {
        "CV_D0_1": DynamicAssetState("CV_D0_1", "cv", "D0", 2_000.0, 0.0, 2)
    }

    def planner(customer_ids, full_asset_states):
        routes = [Route(f"open-{customer_id}", "cv", "D0", ["D0", customer_id, "D0"]) for customer_id in customer_ids]
        try:
            prepared, certificate = prepare_dynamic_multitrip_solution(
                Solution(routes=routes),
                instance,
                replace(DEFAULT_PRICES, Q_capacity=100.0),
                asset_states=full_asset_states,
                stage_start_second=1_000.0,
            )
        except ValueError as exc:
            return PlanAttempt(False, reason=str(exc))
        return PlanAttempt(True, payload=(prepared, certificate))

    result = admit_new_orders_or_reject_individually(
        (),
        ("C_OK", "C_NO"),
        {"C_OK": 10.0, "C_NO": 20.0},
        revenue_per_kg=1.5,
        full_asset_states=states,
        planner=planner,
    )
    assert result.accepted_customer_ids == ("C_OK",)
    assert result.rejected_customer_ids == ("C_NO",)
    assert result.rejected_revenue == 30.0
    prepared, _ = result.plan_payload
    assert [route.node_sequence[1] for route in prepared.routes] == ["C_OK"]


def test_exact_batch_choice_uses_cost_not_input_or_customer_order() -> None:
    def planner(customer_ids, _asset_states):
        chosen = tuple(customer_ids)
        if len(chosen) > 1:
            return PlanAttempt(False, reason="one vehicle")
        costs = {(): 0.0, ("A",): 80.0, ("B",): 20.0}
        return PlanAttempt(True, payload=chosen, delivery_cost=costs[chosen])

    forward = admit_new_orders_or_reject_individually(
        (),
        ("A", "B"),
        {"A": 100.0, "B": 100.0},
        revenue_per_kg=1.5,
        full_asset_states={},
        planner=planner,
    )
    reversed_input = admit_new_orders_or_reject_individually(
        (),
        ("B", "A"),
        {"A": 100.0, "B": 100.0},
        revenue_per_kg=1.5,
        full_asset_states={},
        planner=planner,
    )

    assert forward.accepted_customer_ids == reversed_input.accepted_customer_ids == ("B",)
    assert forward.rejected_customer_ids == reversed_input.rejected_customer_ids == ("A",)
    assert forward.total_cost == reversed_input.total_cost == 170.0
    assert forward.planner_call_count == reversed_input.planner_call_count == 4
