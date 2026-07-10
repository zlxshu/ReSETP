from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pytest

from setp_solver.check import DynamicCheckContext, DynamicVehicleState, check_solution
from setp_solver.cost import ev_arc_energy_kwh, route_node_schedule
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.search import dynamic as dynamic_module
from setp_solver.search.dynamic import (
    DynamicEvent,
    RollingParameters,
    RollingPolicyContext,
    RollingPolicyDecision,
    run_rolling_reoptimization,
)
from setp_solver.solution import ChargingAction, Route, Solution


@dataclass(frozen=True)
class ChargerRollingEvidence:
    report: dict[str, Any]
    contexts: tuple[RollingPolicyContext, ...]
    full_ledger_conflicts: tuple[str, ...]


@dataclass(frozen=True)
class LifecycleRollingEvidence:
    report: dict[str, Any] | None
    contexts: tuple[RollingPolicyContext, ...]
    explicit_conflict: str | None = None


def _clock_case() -> tuple[Instance, Route, Solution, DynamicCheckContext]:
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
    return instance, route, solution, context


def test_dynamic_clock_fixture_is_a_ten_second_arc_from_the_inherited_position() -> None:
    instance, route, _solution, context = _clock_case()
    schedule = route_node_schedule(route, instance)

    assert instance.distance("P0", "C_NEW") == pytest.approx(250.0)
    assert schedule[1].t_arrive == pytest.approx(10.0)
    assert context.vehicle_states["CV1"].current_time == pytest.approx(100.0)
    assert context.vehicle_states["CV1"].position_node_id == route.node_sequence[0]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="dynamic checker resets inherited vehicle time to the static route clock",
)
def test_dynamic_clock_starts_at_inherited_vehicle_time() -> None:
    instance, _route, solution, context = _clock_case()
    late = [
        violation
        for violation in check_solution(solution, instance, dynamic_context=context)
        if violation.type == "TIME_WINDOW" and violation.location == "C_NEW"
    ]

    assert len(late) == 1 and "late by 5.000 s" in late[0].detail and "start=110.000" in late[0].detail


def _battery_case() -> tuple[Instance, Solution, DynamicCheckContext, PriceParameters]:
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
    return instance, solution, context, prices


def test_dynamic_battery_fixture_has_an_exact_two_kwh_arc() -> None:
    instance, solution, context, prices = _battery_case()

    assert instance.distance("P0", "D0") == pytest.approx(2_000.0)
    assert ev_arc_energy_kwh(2_000.0, 0.0, prices) == pytest.approx(2.0)
    assert context.vehicle_states["EV1"].remaining_battery_kwh == pytest.approx(1.0)
    assert solution.routes[0].node_sequence == ["P0", "D0"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="dynamic checker resets EV energy to static initial battery",
)
def test_dynamic_ev_uses_inherited_remaining_battery() -> None:
    instance, solution, context, prices = _battery_case()
    depleted = [
        violation
        for violation in check_solution(solution, instance, prices, dynamic_context=context)
        if violation.type == "BATTERY" and violation.location == "P0->D0"
    ]

    assert len(depleted) == 1 and "-1.000000 kWh" in depleted[0].detail


@pytest.fixture(scope="module")
def charger_rolling_evidence(tmp_path_factory: pytest.TempPathFactory) -> ChargerRollingEvidence:
    return _run_charger_rolling_scenario(tmp_path_factory.mktemp("dynamic-charger-truth"))


def test_real_rolling_charger_fixture_reaches_both_stages(
    charger_rolling_evidence: ChargerRollingEvidence,
) -> None:
    evidence = charger_rolling_evidence
    assert [context.stage_index for context in evidence.contexts] == [0, 1]
    assert evidence.contexts[1].trigger_time == pytest.approx(600.0)
    assert evidence.contexts[1].previous_plan is not None
    assert len(evidence.contexts[1].previous_plan.charging_actions) == 1
    assert evidence.contexts[1].previous_plan.charging_actions[0].charge_start_second == pytest.approx(0.0)
    assert evidence.full_ledger_conflicts == ("F1@slot0",)

    if evidence.report.get("gate") != "HALT_E7_STAGE_CHECK":
        stage_one = next(row for row in evidence.report["stage_rows"] if row["stage"] == 1)
        assert stage_one["stage_charging_action_count"] == 1
        assert stage_one["feasible"] is True


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="real rolling stage omits the pre-boundary charger occupancy",
)
def test_dynamic_stage_check_keeps_pre_boundary_charger_occupancy(
    charger_rolling_evidence: ChargerRollingEvidence,
) -> None:
    report = charger_rolling_evidence.report
    violations = report.get("violations", [])

    assert report.get("gate") == "HALT_E7_STAGE_CHECK" and any(
        row.get("constraint_type") == "STATION_CAPACITY" and row.get("nodes") == "F1@slot0"
        for row in violations
    )


@pytest.fixture(scope="module")
def lifecycle_rolling_evidence(tmp_path_factory: pytest.TempPathFactory) -> LifecycleRollingEvidence:
    return _run_lifecycle_rolling_scenario(tmp_path_factory.mktemp("dynamic-lifecycle-truth"))


def test_real_rolling_lifecycle_fixture_executes_cancel_and_change_events(
    lifecycle_rolling_evidence: LifecycleRollingEvidence,
) -> None:
    evidence = lifecycle_rolling_evidence
    if evidence.explicit_conflict is not None:
        assert "commit" in evidence.explicit_conflict.lower()
        return

    stage_one = _stage_context(evidence.contexts, 1)
    event_ids = {event.event_id for event in stage_one.stage_events}
    previous_customers = _solution_customer_ids(stage_one.previous_plan, stage_one.previous_instance)

    assert event_ids == {
        "1-done-cancel",
        "2-done-change",
        "3-locked-cancel",
        "4-locked-change",
        "5-open-cancel",
        "6-open-change",
    }
    assert {"C_LOCK_CANCEL", "C_LOCK_CHANGE"} <= previous_customers
    assert {"C_OPEN_CANCEL", "C_OPEN_CHANGE"}.isdisjoint(previous_customers)


def test_real_rolling_lifecycle_preserves_completed_and_applies_open_events(
    lifecycle_rolling_evidence: LifecycleRollingEvidence,
) -> None:
    evidence = lifecycle_rolling_evidence
    if evidence.explicit_conflict is not None:
        assert "commit" in evidence.explicit_conflict.lower()
        return

    stage_one = _stage_context(evidence.contexts, 1)
    lookup = {node.node_id: node for node in stage_one.effective_instance.nodes}

    assert lookup["C_DONE_CANCEL"].demand == pytest.approx(10.0)
    assert lookup["C_DONE_CHANGE"].demand == pytest.approx(11.0)
    assert "C_OPEN_CANCEL" not in lookup
    assert lookup["C_OPEN_CHANGE"].demand == pytest.approx(311.0)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="real rolling lifecycle has no distinct committed-but-not-completed state",
)
def test_dynamic_events_distinguish_completed_committed_and_open_customers(
    lifecycle_rolling_evidence: LifecycleRollingEvidence,
) -> None:
    evidence = lifecycle_rolling_evidence
    if evidence.explicit_conflict is not None:
        return

    stage_one = _stage_context(evidence.contexts, 1)
    lookup = {node.node_id: node for node in stage_one.effective_instance.nodes}
    cancel_present = "C_LOCK_CANCEL" in lookup
    cancel_demand = lookup["C_LOCK_CANCEL"].demand if cancel_present else None
    changed_demand = lookup["C_LOCK_CHANGE"].demand
    cancel_preserved = cancel_present and cancel_demand == pytest.approx(20.0)
    demand_preserved = changed_demand == pytest.approx(21.0)

    assert cancel_preserved and demand_preserved, (
        f"locked cancel present={cancel_present}, demand={cancel_demand}; "
        f"locked demand-change observed={changed_demand}, expected=21.0; "
        f"runner committed ids={sorted(stage_one.committed_customer_ids)}"
    )


def _run_charger_rolling_scenario(root: Path) -> ChargerRollingEvidence:
    instance = _zero_distance_instance(
        [
            Node("D0", "d", 0.0, 0.0, due_time=86_400.0, station_chargers=4),
            Node("F1", "f", 0.0, 0.0, due_time=86_400.0, charge_power_kw=60.0, station_chargers=1),
            Node("C_PAST", "c", 0.0, 0.0, demand=1.0, ready_time=1_200.0, due_time=10_000.0),
        ]
    )
    event = DynamicEvent(
        event_id="1-add-next",
        event_type="add",
        t_appear=600.0,
        customer_id="C_NEXT",
        old_demand=0.0,
        new_demand=1.0,
        x=0.0,
        y=0.0,
        delta_demand=1.0,
        new_ready_time=0.0,
        new_due_time=10_000.0,
    )
    previous_plan = Solution(
        routes=[Route("EV_PAST", "ev", "D0", ["D0", "F1", "C_PAST", "D0"])],
        charging_actions=[ChargingAction("EV_PAST", "F1", 1.0, 30.0, 0.0)],
    )
    next_plan = Solution(
        routes=[Route("EV_NEXT", "ev", "D0", ["D0", "F1", "C_NEXT", "D0"])],
        charging_actions=[ChargingAction("EV_NEXT", "F1", 1.0, 10.0, 900.0)],
    )
    contexts: list[RollingPolicyContext] = []

    def policy(context: RollingPolicyContext) -> RollingPolicyDecision:
        contexts.append(context)
        if context.stage_index == 0:
            return RollingPolicyDecision(
                plan_now_ids={"C_PAST"},
                initial_plan=previous_plan,
                stage_eval_budget=0,
                stage_max_runtime_seconds=2.0,
            )
        if context.stage_index == 1:
            return RollingPolicyDecision(
                plan_now_ids={"C_NEXT"},
                initial_plan=next_plan,
                stage_eval_budget=0,
                stage_max_runtime_seconds=2.0,
            )
        raise RuntimeError(f"unexpected rolling stage {context.stage_index}")

    bundle_dir = root / "bundle"
    _write_truth_bundle(bundle_dir, instance, [event])
    report = run_rolling_reoptimization(
        bundle_dir,
        output_json_path=root / "output" / "report.json",
        seed=1,
        eval_budget=0,
        max_runtime_seconds=2.0,
        stage_eval_budget=0,
        stage_max_runtime_seconds=2.0,
        params=RollingParameters(delta_t_seconds=600.0, q_bar=8, stages=2),
        policy_callback=policy,
    )
    if [context.stage_index for context in contexts] != [0, 1]:
        raise RuntimeError(f"charger truth fixture reached unexpected stages: {[c.stage_index for c in contexts]}")

    revealed = contexts[1].effective_instance
    full_ledger = Solution(
        routes=[*previous_plan.routes, *next_plan.routes],
        charging_actions=[*previous_plan.charging_actions, *next_plan.charging_actions],
    )
    conflicts = tuple(
        violation.location
        for violation in check_solution(full_ledger, revealed)
        if violation.type == "STATION_CAPACITY"
    )
    return ChargerRollingEvidence(report, tuple(contexts), conflicts)


def _run_lifecycle_rolling_scenario(root: Path) -> LifecycleRollingEvidence:
    instance = _zero_distance_instance(
        [
            Node("D0", "d", 0.0, 0.0, due_time=86_400.0, station_chargers=4),
            Node("C_DONE_CANCEL", "c", 0.0, 0.0, demand=10.0, due_time=10_000.0),
            Node("C_DONE_CHANGE", "c", 0.0, 0.0, demand=11.0, due_time=10_000.0),
            Node("C_LOCK_CANCEL", "c", 0.0, 0.0, demand=20.0, ready_time=1_000.0, due_time=10_000.0),
            Node("C_LOCK_CHANGE", "c", 0.0, 0.0, demand=21.0, ready_time=1_000.0, due_time=10_000.0),
            Node("C_OPEN_CANCEL", "c", 0.0, 0.0, demand=30.0, due_time=10_000.0),
            Node("C_OPEN_CHANGE", "c", 0.0, 0.0, demand=31.0, due_time=10_000.0),
        ]
    )
    events = [
        _event("1-done-cancel", "cancel", "C_DONE_CANCEL", 10.0, 0.0),
        _event("2-done-change", "demand_change", "C_DONE_CHANGE", 11.0, 111.0),
        _event("3-locked-cancel", "cancel", "C_LOCK_CANCEL", 20.0, 0.0),
        _event("4-locked-change", "demand_change", "C_LOCK_CHANGE", 21.0, 211.0),
        _event("5-open-cancel", "cancel", "C_OPEN_CANCEL", 30.0, 0.0),
        _event("6-open-change", "demand_change", "C_OPEN_CHANGE", 31.0, 311.0),
    ]
    locked_ids = {"C_DONE_CANCEL", "C_DONE_CHANGE", "C_LOCK_CANCEL", "C_LOCK_CHANGE"}
    stage_zero_plan = Solution(
        routes=[
            Route(
                "CV_LOCKED",
                "cv",
                "D0",
                ["D0", "C_DONE_CANCEL", "C_DONE_CHANGE", "C_LOCK_CANCEL", "C_LOCK_CHANGE", "D0"],
            )
        ]
    )
    stage_one_plan = Solution(
        routes=[Route("CV_AFTER", "cv", "D0", ["D0", "C_LOCK_CHANGE", "C_OPEN_CHANGE", "D0"])]
    )
    contexts: list[RollingPolicyContext] = []

    def policy(context: RollingPolicyContext) -> RollingPolicyDecision:
        contexts.append(context)
        if context.stage_index == 0:
            return RollingPolicyDecision(
                plan_now_ids=set(locked_ids),
                initial_plan=stage_zero_plan,
                stage_eval_budget=1,
                stage_max_runtime_seconds=2.0,
            )
        if context.stage_index == 1:
            return RollingPolicyDecision(
                plan_now_ids=set(context.active_ids),
                initial_plan=stage_one_plan,
                stage_eval_budget=1,
                stage_max_runtime_seconds=2.0,
            )
        raise RuntimeError(f"unexpected rolling stage {context.stage_index}")

    bundle_dir = root / "bundle"
    _write_truth_bundle(bundle_dir, instance, events)
    try:
        report = run_rolling_reoptimization(
            bundle_dir,
            output_json_path=root / "output" / "report.json",
            seed=1,
            eval_budget=1,
            max_runtime_seconds=2.0,
            stage_eval_budget=1,
            stage_max_runtime_seconds=2.0,
            params=RollingParameters(delta_t_seconds=100.0, q_bar=8, stages=2),
            policy_callback=policy,
        )
    except ValueError as exc:
        message = str(exc)
        if "commit" not in message.lower():
            raise RuntimeError(f"unexpected lifecycle ValueError: {message}") from exc
        return LifecycleRollingEvidence(None, tuple(contexts), message)

    if [context.stage_index for context in contexts] != [0, 1]:
        raise RuntimeError(f"lifecycle truth fixture reached unexpected stages: {[c.stage_index for c in contexts]}")
    return LifecycleRollingEvidence(report, tuple(contexts))


def _write_truth_bundle(path: Path, instance: Instance, events: list[DynamicEvent]) -> None:
    dynamic_module._write_dynamic_bundle(
        path,
        instance,
        _flat_carbon_profile(),
        {"source": "dynamic_truth_test", "num_cv": 4, "num_ev": 4},
    )
    fields = list(asdict(events[0]))
    with (path / "dynamic_events.tsv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(asdict(event) for event in events)


def _zero_distance_instance(nodes: list[Node]) -> Instance:
    return Instance(
        nodes=nodes,
        distance_matrix=[[0.0] * len(nodes) for _ in nodes],
        num_cv=4,
        num_ev=4,
    )


def _event(event_id: str, event_type: str, customer_id: str, old_demand: float, new_demand: float) -> DynamicEvent:
    return DynamicEvent(
        event_id=event_id,
        event_type=event_type,
        t_appear=100.0,
        customer_id=customer_id,
        old_demand=old_demand,
        new_demand=new_demand,
        delta_demand=new_demand - old_demand,
    )


def _stage_context(contexts: tuple[RollingPolicyContext, ...], stage_index: int) -> RollingPolicyContext:
    try:
        return next(context for context in contexts if context.stage_index == stage_index)
    except StopIteration as exc:
        raise RuntimeError(f"rolling context for stage {stage_index} was not captured") from exc


def _solution_customer_ids(solution: Solution | None, instance: Instance | None) -> set[str]:
    if solution is None or instance is None:
        raise RuntimeError("rolling context did not expose previous plan and instance")
    node_lookup = {node.node_id: node for node in instance.nodes}
    return {
        node_id
        for route in solution.routes
        for node_id in route.node_sequence
        if node_lookup.get(node_id) is not None and node_lookup[node_id].node_type.lower() == "c"
    }


def _flat_carbon_profile() -> list[dict[str, object]]:
    return [
        {
            "time_index": index,
            "datetime_utc": "",
            "actual_gco2_per_kwh": 200.0,
            "forecast_gco2_per_kwh": 200.0,
            "index_label": "",
            "index_code": index,
            "horizon_second_start": float(index * 1_800),
        }
        for index in range(48)
    ]
