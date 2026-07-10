from __future__ import annotations

import pytest

from setp_solver.check import DynamicCheckContext, DynamicVehicleState, check_solution
from setp_solver.cost import ev_arc_energy_kwh, route_node_schedule
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.search import dynamic as dynamic_module
from setp_solver.search.dynamic import DynamicEvent
from setp_solver.solution import ChargingAction, Route, Solution


def _zero_distance_instance(nodes: list[Node]) -> Instance:
    return Instance(nodes=nodes, distance_matrix=[[0.0] * len(nodes) for _ in nodes])


def _event(
    event_id: str,
    event_type: str,
    customer_id: str,
    *,
    old_demand: float,
    new_demand: float,
) -> DynamicEvent:
    return DynamicEvent(
        event_id=event_id,
        event_type=event_type,
        t_appear=10.0,
        customer_id=customer_id,
        old_demand=old_demand,
        new_demand=new_demand,
        delta_demand=new_demand - old_demand,
    )


@pytest.mark.xfail(strict=True, reason="dynamic checker resets inherited vehicle time to the static route clock")
def test_dynamic_clock_starts_at_inherited_vehicle_time() -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=10_000.0),
            Node("P0", "f", 0.0, 0.0, due_time=10_000.0),
            Node("C_NEW", "c", 0.0, 0.0, due_time=105.0),
        ],
        distance_matrix=[
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 250.0],
            [0.0, 250.0, 0.0],
        ],
    )
    route = Route("CV1", "cv", "D0", ["P0", "C_NEW", "D0"])
    solution = Solution(routes=[route])
    context = DynamicCheckContext(
        vehicle_states={
            "CV1": DynamicVehicleState(
                vehicle_id="CV1",
                position_node_id="P0",
                current_time=100.0,
                remaining_load_kg=0.0,
                remaining_battery_kwh=0.0,
            )
        },
        allow_open_start=True,
    )

    static_schedule = route_node_schedule(route, instance)
    violations = check_solution(solution, instance, dynamic_context=context)
    late = [violation for violation in violations if violation.type == "TIME_WINDOW" and violation.location == "C_NEW"]

    assert late, (
        "100 s inherited time + 250 m / 25 m/s = arrival 110 s, so C_NEW "
        f"must be 5 s late; reset schedule observed arrival={static_schedule[1].t_arrive:.3f} s"
    )
    assert "late by 5.000 s" in late[0].detail
    assert "start=110.000" in late[0].detail


@pytest.mark.xfail(strict=True, reason="dynamic checker resets EV energy to static initial battery")
def test_dynamic_ev_uses_inherited_remaining_battery() -> None:
    prices = PriceParameters(
        c_d=0.0,
        m_curb=1.0,
        m_unit=0.0,
        g0=1.0,
        c_r=1.0,
        alpha_e=3_600.0,
        B_battery_kwh=80.0,
        initial_ev_battery_kwh=80.0,
    )
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=10_000.0),
            Node("P0", "f", 0.0, 0.0, due_time=10_000.0),
        ],
        distance_matrix=[
            [0.0, 2_000.0],
            [2_000.0, 0.0],
        ],
    )
    solution = Solution(routes=[Route("EV1", "ev", "D0", ["P0", "D0"])])
    context = DynamicCheckContext(
        vehicle_states={
            "EV1": DynamicVehicleState(
                vehicle_id="EV1",
                position_node_id="P0",
                current_time=0.0,
                remaining_load_kg=0.0,
                remaining_battery_kwh=1.0,
            )
        },
        allow_open_start=True,
    )

    arc_energy = ev_arc_energy_kwh(2_000.0, 0.0, prices)
    assert arc_energy == pytest.approx(2.0)
    violations = check_solution(solution, instance, prices, dynamic_context=context)
    depleted = [violation for violation in violations if violation.type == "BATTERY" and violation.location == "P0->D0"]

    assert depleted, (
        "inherited battery 1 kWh - exact arc use 2 kWh = -1 kWh; "
        f"checker emitted no depletion violation (static initial={prices.initial_ev_battery_kwh:.1f} kWh)"
    )
    assert "-1.000000 kWh" in depleted[0].detail


@pytest.mark.xfail(strict=True, reason="rolling lifecycle drops charger occupancy before the customer is committed")
def test_dynamic_stage_check_keeps_pre_boundary_charger_occupancy() -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=10_000.0),
            Node("F1", "f", 0.0, 0.0, due_time=10_000.0, charge_power_kw=60.0, station_chargers=1),
            Node("C_PAST", "c", 0.0, 0.0, due_time=10_000.0),
            Node("C_NEXT", "c", 0.0, 0.0, due_time=10_000.0),
        ],
        distance_matrix=[
            [0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 25_000.0, 0.0],
            [0.0, 25_000.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ],
    )
    previous_plan = Solution(
        routes=[Route("EV1", "ev", "D0", ["D0", "F1", "C_PAST", "D0"])],
        charging_actions=[
            ChargingAction("EV1", "F1", energy_kwh=1.0, occupancy_minutes=30.0, charge_start_second=0.0)
        ],
    )
    next_plan = Solution(
        routes=[Route("EV2", "ev", "D0", ["D0", "F1", "C_NEXT", "D0"])],
        charging_actions=[
            ChargingAction("EV2", "F1", energy_kwh=1.0, occupancy_minutes=10.0, charge_start_second=900.0)
        ],
    )

    # At t=600 the first charge is already in progress.  Its customer is at
    # least 1000 s away even on the reset schedule (2800 s with charging), so
    # the customer-only commit path has no chunk carrying the reservation.
    newly_committed = dynamic_module._commit_executed_customers(previous_plan, instance, 600.0, set())
    assert newly_committed == set()
    carried = dynamic_module._solution_for_committed_customers(
        previous_plan,
        instance,
        [],
        newly_committed,
        prefix="S1_",
    )
    stage_view = Solution(
        routes=[*carried.routes, *next_plan.routes],
        charging_actions=[*carried.charging_actions, *next_plan.charging_actions],
    )

    full_ledger = Solution(
        routes=[*previous_plan.routes, *next_plan.routes],
        charging_actions=[*previous_plan.charging_actions, *next_plan.charging_actions],
    )
    assert any(violation.type == "STATION_CAPACITY" for violation in check_solution(full_ledger, instance))

    stage_conflicts = [violation for violation in check_solution(stage_view, instance) if violation.type == "STATION_CAPACITY"]
    assert stage_conflicts, (
        "F1 has one charger and both uses occupy slot 0, but the stage check "
        f"carried {len(carried.charging_actions)} historical charging actions"
    )


@pytest.mark.xfail(strict=True, reason="event lifecycle silently treats committed cancellation like an open customer")
def test_dynamic_events_distinguish_completed_committed_and_open_customers() -> None:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=10_000.0),
        Node("C_DONE_CANCEL", "c", 0.0, 0.0, demand=10.0, due_time=10_000.0),
        Node("C_DONE_CHANGE", "c", 0.0, 0.0, demand=11.0, due_time=10_000.0),
        Node("C_COMMIT_CANCEL", "c", 0.0, 0.0, demand=20.0, due_time=10_000.0),
        Node("C_COMMIT_CHANGE", "c", 0.0, 0.0, demand=21.0, due_time=10_000.0),
        Node("C_OPEN_CANCEL", "c", 0.0, 0.0, demand=30.0, due_time=10_000.0),
        Node("C_OPEN_CHANGE", "c", 0.0, 0.0, demand=31.0, due_time=10_000.0),
    ]
    instance = _zero_distance_instance(nodes)
    original = {node.node_id: node for node in nodes}
    completed = {"C_DONE_CANCEL", "C_DONE_CHANGE"}
    frozen = {
        customer_id: original[customer_id]
        for customer_id in {
            *completed,
            "C_COMMIT_CANCEL",
            "C_COMMIT_CHANGE",
        }
    }

    completed_result = dynamic_module._instance_after_events(
        instance,
        [
            _event("done-cancel", "cancel", "C_DONE_CANCEL", old_demand=10.0, new_demand=0.0),
            _event("done-change", "demand_change", "C_DONE_CHANGE", old_demand=11.0, new_demand=111.0),
        ],
        10.0,
        completed,
        frozen,
    )
    completed_lookup = {node.node_id: node for node in completed_result.nodes}
    assert completed_lookup["C_DONE_CANCEL"].demand == pytest.approx(10.0)
    assert completed_lookup["C_DONE_CHANGE"].demand == pytest.approx(11.0)

    open_result = dynamic_module._instance_after_events(
        instance,
        [
            _event("open-cancel", "cancel", "C_OPEN_CANCEL", old_demand=30.0, new_demand=0.0),
            _event("open-change", "demand_change", "C_OPEN_CHANGE", old_demand=31.0, new_demand=311.0),
        ],
        10.0,
        completed,
        frozen,
    )
    open_lookup = {node.node_id: node for node in open_result.nodes}
    assert "C_OPEN_CANCEL" not in open_lookup
    assert open_lookup["C_OPEN_CHANGE"].demand == pytest.approx(311.0)

    committed_events = [
        _event("commit-cancel", "cancel", "C_COMMIT_CANCEL", old_demand=20.0, new_demand=0.0),
        _event("commit-change", "demand_change", "C_COMMIT_CHANGE", old_demand=21.0, new_demand=211.0),
    ]
    for event in committed_events:
        try:
            committed_result = dynamic_module._instance_after_events(
                instance,
                [event],
                10.0,
                completed,
                frozen,
            )
        except ValueError as exc:
            message = str(exc).lower()
            assert "commit" in message and event.customer_id.lower() in message
            continue
        committed_lookup = {node.node_id: node for node in committed_result.nodes}
        assert event.customer_id in committed_lookup, (
            f"committed customer {event.customer_id} was silently treated as open "
            f"under {event.event_type}"
        )
        assert committed_lookup[event.customer_id].demand == pytest.approx(event.old_demand)
