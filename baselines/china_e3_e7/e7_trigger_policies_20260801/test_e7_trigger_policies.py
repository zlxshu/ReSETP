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
    DynamicOrder,
    build_dynamic_orders,
    build_trigger_batches,
    dynamic_order_sha256,
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
