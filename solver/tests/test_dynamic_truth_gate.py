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
from setp_solver.solution import ChargingAction, Route, Solution, physical_vehicle_id


@dataclass(frozen=True)
class ChargerRollingEvidence:
    report: dict[str, Any]
    contexts: tuple[RollingPolicyContext, ...]
    previous_stage_output: Solution
    stage_one_output: Solution | None


@dataclass(frozen=True)
class LifecycleRollingEvidence:
    event_type: str
    report: dict[str, Any]
    contexts: tuple[RollingPolicyContext, ...]


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


def test_dynamic_ev_uses_inherited_remaining_battery() -> None:
    instance, solution, context, prices = _battery_case()
    depleted = [
        violation
        for violation in check_solution(solution, instance, prices, dynamic_context=context)
        if violation.type == "BATTERY" and violation.location == "P0->D0"
    ]

    assert len(depleted) == 1 and "-1.000000 kWh" in depleted[0].detail


def test_dynamic_route_cannot_redeliver_more_than_the_inherited_remaining_load() -> None:
    instance = _zero_distance_instance(
        [
            Node("D0", "d", 0.0, 0.0, due_time=10_000.0),
            Node("P0", "f", 0.0, 0.0, due_time=10_000.0),
            Node("C_REMAIN", "c", 0.0, 0.0, demand=10.0, due_time=10_000.0),
        ]
    )
    solution = Solution(routes=[Route("CV1", "cv", "D0", ["P0", "C_REMAIN", "D0"])])
    context = DynamicCheckContext(
        vehicle_states={
            "CV1": DynamicVehicleState(
                vehicle_id="CV1",
                position_node_id="P0",
                current_time=100.0,
                remaining_load_kg=5.0,
                remaining_battery_kwh=0.0,
            )
        },
        allow_open_start=True,
    )

    violations = check_solution(solution, instance, dynamic_context=context)

    assert any(
        violation.type == "CAPACITY"
        and violation.location == "C_REMAIN"
        and "remaining load" in violation.detail
        for violation in violations
    )


def test_dynamic_stage_cannot_reuse_an_in_progress_physical_vehicle() -> None:
    instance = _zero_distance_instance(
        [
            Node("D0", "d", 0.0, 0.0, due_time=10_000.0),
            Node("C_NEW", "c", 0.0, 0.0, demand=1.0, due_time=10_000.0),
        ]
    )
    solution = Solution(routes=[Route("CV1#T1", "cv", "D0", ["D0", "C_NEW", "D0"])])
    context = DynamicCheckContext(reserved_physical_vehicle_ids=("CV1",))

    violations = check_solution(solution, instance, dynamic_context=context)

    assert any(
        violation.type == "ROUTE_STRUCTURE"
        and violation.location == "CV1"
        and "in-progress vehicle" in violation.detail
        for violation in violations
    )


@pytest.fixture(scope="module")
def charger_rolling_evidence(tmp_path_factory: pytest.TempPathFactory) -> ChargerRollingEvidence:
    return _run_charger_rolling_scenario(tmp_path_factory.mktemp("dynamic-charger-truth"))


def test_real_rolling_charger_fixture_reaches_both_stages(
    charger_rolling_evidence: ChargerRollingEvidence,
) -> None:
    evidence = charger_rolling_evidence
    expected_stages = [0, 1] if evidence.report.get("gate") == "HALT_E7_STAGE_CHECK" else [0, 1, 2]
    assert [context.stage_index for context in evidence.contexts] == expected_stages
    assert evidence.contexts[1].trigger_time == pytest.approx(600.0)
    assert evidence.contexts[1].previous_plan is evidence.previous_stage_output
    assert len(evidence.previous_stage_output.charging_actions) == 1
    prior_action = evidence.previous_stage_output.charging_actions[0]
    prior_route = next(route for route in evidence.previous_stage_output.routes if "C_PAST" in route.node_sequence)
    assert prior_action.station_id == "F1"
    assert prior_action.charge_start_second == pytest.approx(0.0)
    assert prior_action.occupancy_minutes == pytest.approx(30.0)
    assert prior_action.vehicle_id == prior_route.vehicle_id and prior_route.vehicle_type == "ev"

    if evidence.stage_one_output is None:
        _require_exact_stage_one_charger_halt(evidence.report)
    else:
        assert evidence.contexts[2].previous_plan is evidence.stage_one_output
        assert len(evidence.stage_one_output.charging_actions) == 1
        stage_one_action = evidence.stage_one_output.charging_actions[0]
        stage_one_route = next(route for route in evidence.stage_one_output.routes if "C_NEXT" in route.node_sequence)
        assert stage_one_action.station_id == "F1"
        assert stage_one_action.charge_start_second == pytest.approx(900.0)
        assert stage_one_action.occupancy_minutes == pytest.approx(10.0)
        assert stage_one_action.vehicle_id == stage_one_route.vehicle_id and stage_one_route.vehicle_type == "ev"
        assert stage_one_action.vehicle_id != prior_action.vehicle_id
        full_ledger = _cross_stage_charging_ledger_for_audit(
            evidence.previous_stage_output,
            evidence.stage_one_output,
        )
        assert full_ledger.routes == [prior_route, stage_one_route]
        assert full_ledger.charging_actions == [prior_action, stage_one_action]
        audit_instance = dynamic_module._subinstance_for_customers(
            evidence.contexts[1].effective_instance,
            {"C_PAST", "C_NEXT"},
        )
        audit_customers = {
            node.node_id for node in audit_instance.nodes if node.node_type.lower() == "c"
        }
        assert audit_customers == {"C_PAST", "C_NEXT"}
        assert _solution_customer_ids(full_ledger, audit_instance) == audit_customers
        assert {route.vehicle_id for route in full_ledger.routes} == {
            prior_action.vehicle_id,
            stage_one_action.vehicle_id,
        }
        assert [
            (violation.type, violation.location)
            for violation in check_solution(full_ledger, audit_instance)
        ] == [("STATION_CAPACITY", "F1@slot0")]
        stage_one = next(row for row in evidence.report["stage_rows"] if row["stage"] == 1)
        assert stage_one["stage_charging_action_count"] == 1
        assert stage_one["feasible"] is True


def test_dynamic_stage_check_keeps_pre_boundary_charger_occupancy(
    charger_rolling_evidence: ChargerRollingEvidence,
) -> None:
    report = charger_rolling_evidence.report
    violations = report.get("violations", [])

    assert report.get("gate") == "HALT_E7_STAGE_CHECK" and any(
        row.get("constraint_type") == "STATION_CAPACITY" and row.get("nodes") == "F1@slot0"
        for row in violations
    )
    prior_action = charger_rolling_evidence.previous_stage_output.charging_actions[0]
    assert physical_vehicle_id(prior_action.vehicle_id) in report.get("reserved_physical_vehicle_ids", [])


@pytest.fixture(scope="module")
def lifecycle_rolling_evidence(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[LifecycleRollingEvidence, LifecycleRollingEvidence]:
    evidence: list[LifecycleRollingEvidence] = []
    failures: list[Exception] = []
    for event_type in ("cancel", "demand_change"):
        try:
            evidence.append(
                _run_lifecycle_rolling_scenario(
                    tmp_path_factory.mktemp(f"dynamic-lifecycle-{event_type}"),
                    event_type,
                )
            )
        except Exception as exc:
            # Run the other independent scenario before surfacing either error.
            # No runner exception is accepted as lifecycle truth.
            failures.append(exc)
    if failures:
        raise ExceptionGroup("independent lifecycle rolling scenarios failed", failures)
    if len(evidence) != 2:
        raise RuntimeError(f"expected two lifecycle rolling reports, got {len(evidence)}")
    return evidence[0], evidence[1]


def test_real_rolling_lifecycle_fixture_executes_cancel_and_change_events(
    lifecycle_rolling_evidence: tuple[LifecycleRollingEvidence, LifecycleRollingEvidence],
) -> None:
    assert {evidence.event_type for evidence in lifecycle_rolling_evidence} == {"cancel", "demand_change"}
    for evidence in lifecycle_rolling_evidence:
        assert [context.stage_index for context in evidence.contexts] == [0, 1]
        assert {"gate", "first_bad_stage", "violations"}.isdisjoint(evidence.report)
        assert evidence.report["dynamic_solver_backend"] == "setp_solver.algorithms.resetp_alns"
        assert evidence.report["static_control_backend"] == "setp_solver.algorithms.resetp_alns"
        stage_one = _stage_context(evidence.contexts, 1)
        assert {event.event_id for event in stage_one.stage_events} == {
            f"1-done-{evidence.event_type}",
            f"2-locked-{evidence.event_type}",
            f"3-planned-open-{evidence.event_type}",
            f"4-open-{evidence.event_type}",
        }
        previous_customers = _solution_customer_ids(stage_one.previous_plan, stage_one.previous_instance)
        assert previous_customers == {"C_DONE", "C_LOCK", "C_PLANNED_OPEN"}
        assert next(
            route.vehicle_id for route in stage_one.previous_plan.routes if "C_LOCK" in route.node_sequence
        ) == "CV_PREVIOUS"
        assert "C_OPEN" not in previous_customers
        assert stage_one.served_customers == {"C_DONE"}
        assert stage_one.trigger_time == pytest.approx(100.0)

        if stage_one.previous_plan is None or stage_one.previous_instance is None:
            raise RuntimeError("lifecycle rolling stage did not expose its real previous-stage output")
        starts = {
            row.node_id: row.t_start
            for route in stage_one.previous_plan.routes
            for row in route_node_schedule(route, stage_one.previous_instance)
            if row.node_id in previous_customers
        }
        assert starts == pytest.approx({"C_DONE": 0.0, "C_LOCK": 150.0, "C_PLANNED_OPEN": 1_000.0})


def test_real_rolling_lifecycle_preserves_completed_and_applies_open_events(
    lifecycle_rolling_evidence: tuple[LifecycleRollingEvidence, LifecycleRollingEvidence],
) -> None:
    for evidence in lifecycle_rolling_evidence:
        stage_one = _stage_context(evidence.contexts, 1)
        lookup = {node.node_id: node for node in stage_one.effective_instance.nodes}
        assert lookup["C_DONE"].demand == pytest.approx(10.0)
        if evidence.event_type == "cancel":
            assert "C_OPEN" not in lookup
            assert "C_PLANNED_OPEN" not in lookup
        else:
            assert lookup["C_OPEN"].demand == pytest.approx(130.0)
            assert lookup["C_PLANNED_OPEN"].demand == pytest.approx(140.0)


def test_dynamic_events_distinguish_completed_committed_and_open_customers(
    lifecycle_rolling_evidence: tuple[LifecycleRollingEvidence, LifecycleRollingEvidence],
) -> None:
    outcomes: list[bool] = []
    diagnostics: list[str] = []
    for evidence in lifecycle_rolling_evidence:
        stage_one = _stage_context(evidence.contexts, 1)
        lookup = {node.node_id: node for node in stage_one.effective_instance.nodes}
        explicit_four_states = (
            stage_one.served_customers == {"C_DONE"}
            and stage_one.committed_customer_ids == {"C_LOCK"}
            and "C_PLANNED_OPEN" not in stage_one.committed_customer_ids
            and "C_OPEN" not in stage_one.committed_customer_ids
        )
        locked_event_preserved = "C_LOCK" in lookup and lookup["C_LOCK"].demand == pytest.approx(20.0)
        locked_not_replanned = "C_LOCK" not in evidence.report.get("final_repair_customer_ids", [])
        snapshots = evidence.report.get("locked_route_snapshots", [])
        locked_snapshot = next(
            (row for row in snapshots if row.get("fixed_customer_order") == ["C_LOCK"]),
            None,
        )
        locked_source_vehicle = next(
            route.vehicle_id
            for route in stage_one.previous_plan.routes
            if "C_LOCK" in route.node_sequence
        )
        state_continues = bool(
            locked_snapshot
            and locked_snapshot["vehicle_id"] == locked_source_vehicle
            and locked_snapshot["covered_customer_order"] == ["C_DONE", "C_LOCK"]
            and locked_snapshot["state"]["current_time"] == pytest.approx(100.0)
            and locked_snapshot["state"]["position_node_id"] == "C_LOCK"
            and locked_snapshot["state"]["remaining_load_kg"] == pytest.approx(60.0)
        )
        no_final_solver = (
            evidence.report.get("final_repair_customer_count") == 0
            and evidence.report.get("final_repair_evaluations") == 0
        )
        locked_final_routes = [
            row
            for row in evidence.report.get("dynamic_final_routes", [])
            if "C_LOCK" in row.get("node_sequence", [])
        ]
        final_assignment_unchanged = (
            len(locked_final_routes) == 1
            and locked_final_routes[0]["vehicle_id"] == locked_source_vehicle
            and locked_final_routes[0]["node_sequence"].index("C_DONE")
            < locked_final_routes[0]["node_sequence"].index("C_LOCK")
        )
        outcomes.append(
            bool(
                explicit_four_states
                and locked_event_preserved
                and locked_not_replanned
                and state_continues
                and no_final_solver
                and final_assignment_unchanged
            )
        )
        diagnostics.append(
            f"{evidence.event_type}: served={sorted(stage_one.served_customers)}, "
            f"committed-not-completed={sorted(stage_one.committed_customer_ids)}, "
            f"C_LOCK present={'C_LOCK' in lookup}, "
            f"demand={lookup.get('C_LOCK').demand if 'C_LOCK' in lookup else None}, "
            f"final-repair={evidence.report.get('final_repair_customer_ids', [])}"
        )

    assert all(outcomes), "; ".join(diagnostics)


def test_real_rolling_keeps_mid_arc_position_load_and_battery_on_the_original_vehicle(tmp_path: Path) -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=86_400.0, station_chargers=2),
            Node("C_DONE", "c", 100.0, 0.0, demand=10.0, due_time=10_000.0, service_time=50.0),
            Node("C_LOCK", "c", 200.0, 0.0, demand=20.0, due_time=10_000.0),
        ],
        distance_matrix=[
            [0.0, 100.0, 200.0],
            [100.0, 0.0, 100.0],
            [200.0, 100.0, 0.0],
        ],
        num_cv=2,
        num_ev=2,
    )
    event = DynamicEvent(
        event_id="add-midarc",
        event_type="add",
        t_appear=56.0,
        customer_id="C_NEW",
        old_demand=0.0,
        new_demand=1.0,
        x=0.0,
        y=0.0,
        new_ready_time=56.0,
        new_due_time=10_000.0,
    )
    stage_zero = Solution(
        routes=[Route("EV_PREVIOUS", "ev", "D0", ["D0", "C_DONE", "C_LOCK", "D0"])]
    )
    stage_one = Solution(
        routes=[Route("CV_AFTER", "cv", "D0", ["D0", "C_NEW", "D0"])]
    )

    def policy(context: RollingPolicyContext) -> RollingPolicyDecision:
        if context.stage_index == 0:
            return RollingPolicyDecision(initial_plan=stage_zero, stage_eval_budget=0)
        return RollingPolicyDecision(initial_plan=stage_one, stage_eval_budget=0)

    bundle_dir = tmp_path / "midarc" / "bundle"
    _write_truth_bundle(bundle_dir, instance, [event])
    report = run_rolling_reoptimization(
        bundle_dir,
        output_json_path=tmp_path / "midarc" / "report.json",
        seed=3,
        eval_budget=0,
        max_runtime_seconds=2.0,
        stage_eval_budget=0,
        stage_max_runtime_seconds=2.0,
        params=RollingParameters(delta_t_seconds=56.0, q_bar=8, stages=2),
        prices=PriceParameters(initial_ev_battery_kwh=80.0, B_battery_kwh=80.0),
        policy_callback=policy,
    )

    assert "gate" not in report
    snapshot = next(row for row in report["locked_route_snapshots"] if row["fixed_customer_order"] == ["C_LOCK"])
    state = snapshot["state"]
    assert state["location_kind"] == "arc"
    assert state["position_node_id"] == "C_DONE"
    assert state["next_node_id"] == "C_LOCK"
    assert state["arc_progress"] == pytest.approx(0.5)
    assert state["current_time"] == pytest.approx(56.0)
    assert state["remaining_load_kg"] == pytest.approx(20.0)
    assert 0.0 < state["remaining_battery_kwh"] < 80.0
    locked_routes = [
        row for row in report["dynamic_final_routes"] if "C_LOCK" in row["node_sequence"]
    ]
    assert len(locked_routes) == 1
    assert snapshot["vehicle_id"] == "EV_PREVIOUS"
    assert locked_routes[0]["vehicle_id"] == snapshot["vehicle_id"]
    assert locked_routes[0]["node_sequence"][:3] == ["D0", "C_DONE", "C_LOCK"]
    stage_one_row = next(row for row in report["stage_rows"] if row["stage"] == 1)
    assert stage_one_row["solver_backend"] == "setp_solver.algorithms.resetp_alns"


def test_real_stage_solver_cannot_depart_before_the_dynamic_trigger(tmp_path: Path) -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=10_000.0, station_chargers=2),
            Node("C_DONE", "c", 0.0, 0.0, demand=1.0, due_time=10_000.0),
        ],
        distance_matrix=[[0.0, 0.0], [0.0, 0.0]],
        num_cv=2,
        num_ev=0,
    )
    event = DynamicEvent(
        event_id="late-add",
        event_type="add",
        t_appear=60.0,
        customer_id="C_TOO_LATE",
        old_demand=0.0,
        new_demand=1.0,
        x=250.0,
        y=0.0,
        new_ready_time=60.0,
        new_due_time=65.0,
    )
    bundle_dir = tmp_path / "clock-runner" / "bundle"
    _write_truth_bundle(bundle_dir, instance, [event])

    report = run_rolling_reoptimization(
        bundle_dir,
        output_json_path=tmp_path / "clock-runner" / "report.json",
        seed=5,
        eval_budget=0,
        max_runtime_seconds=2.0,
        stage_eval_budget=0,
        stage_max_runtime_seconds=2.0,
        params=RollingParameters(delta_t_seconds=60.0, q_bar=8, stages=2),
    )

    assert report.get("gate") == "HALT_E7_STAGE_CHECK"
    assert report.get("first_bad_stage") == 1
    assert any(
        row.get("constraint_type") == "TIME_WINDOW" and row.get("nodes") == "C_TOO_LATE"
        for row in report.get("violations", [])
    )


def test_real_stage_solver_cannot_invent_a_second_vehicle_while_the_only_vehicle_is_in_progress(
    tmp_path: Path,
) -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=10_000.0, station_chargers=2),
            Node("C_DONE", "c", 100.0, 0.0, demand=1.0, due_time=10_000.0, service_time=50.0),
            Node("C_LOCK", "c", 200.0, 0.0, demand=1.0, due_time=10_000.0),
        ],
        distance_matrix=[[0.0, 100.0, 200.0], [100.0, 0.0, 100.0], [200.0, 100.0, 0.0]],
        num_cv=1,
        num_ev=0,
    )
    event = DynamicEvent(
        event_id="add-with-no-idle-vehicle",
        event_type="add",
        t_appear=56.0,
        customer_id="C_NEW",
        old_demand=0.0,
        new_demand=1.0,
        x=0.0,
        y=0.0,
        new_ready_time=56.0,
        new_due_time=10_000.0,
    )
    stage_zero = Solution(
        routes=[Route("CV1#T1", "cv", "D0", ["D0", "C_DONE", "C_LOCK", "D0"])]
    )

    def policy(context: RollingPolicyContext) -> RollingPolicyDecision:
        if context.stage_index == 0:
            return RollingPolicyDecision(initial_plan=stage_zero, stage_eval_budget=0)
        return RollingPolicyDecision(stage_eval_budget=0)

    bundle_dir = tmp_path / "one-vehicle" / "bundle"
    _write_truth_bundle(bundle_dir, instance, [event])
    report = run_rolling_reoptimization(
        bundle_dir,
        output_json_path=tmp_path / "one-vehicle" / "report.json",
        seed=11,
        eval_budget=0,
        max_runtime_seconds=2.0,
        stage_eval_budget=0,
        stage_max_runtime_seconds=2.0,
        params=RollingParameters(delta_t_seconds=56.0, q_bar=8, stages=2),
        policy_callback=policy,
    )

    assert report.get("gate") == "HALT_E7_STAGE_CHECK"
    assert report.get("first_bad_stage") == 1
    assert report.get("reserved_physical_vehicle_ids") == ["CV1"]
    assert any(
        row.get("constraint_type") in {"FLEET_SIZE", "ROUTE_STRUCTURE"}
        for row in report.get("violations", [])
    )


def _run_charger_rolling_scenario(root: Path) -> ChargerRollingEvidence:
    instance = _zero_distance_instance(
        [
            Node("D0", "d", 0.0, 0.0, due_time=86_400.0, station_chargers=4),
            Node("F1", "f", 0.0, 0.0, due_time=86_400.0, charge_power_kw=60.0, station_chargers=1),
            Node("C_ANCHOR", "c", 0.0, 0.0, demand=1.0, due_time=10_000.0),
            Node("C_PAST", "c", 0.0, 0.0, demand=1.0, ready_time=1_200.0, due_time=10_000.0),
        ]
    )
    events = [
        DynamicEvent(
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
        ),
        DynamicEvent(
            event_id="2-cancel-past-after-capture",
            event_type="cancel",
            t_appear=1_200.0,
            customer_id="C_PAST",
            old_demand=1.0,
            new_demand=0.0,
            delta_demand=-1.0,
        ),
    ]
    previous_plan = Solution(
        routes=[
            Route("EV_ANCHOR", "ev", "D0", ["D0", "C_ANCHOR", "D0"]),
            Route("EV_PAST", "ev", "D0", ["D0", "F1", "C_PAST", "D0"]),
        ],
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
                plan_now_ids={"C_ANCHOR", "C_PAST"},
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
        if context.stage_index == 2 and not context.active_ids:
            return RollingPolicyDecision(
                plan_now_ids=set(),
                initial_plan=Solution(),
                stage_eval_budget=0,
                stage_max_runtime_seconds=2.0,
            )
        raise RuntimeError(f"unexpected rolling stage {context.stage_index}")

    bundle_dir = root / "bundle"
    _write_truth_bundle(bundle_dir, instance, events)
    report = run_rolling_reoptimization(
        bundle_dir,
        output_json_path=root / "output" / "report.json",
        seed=1,
        eval_budget=0,
        max_runtime_seconds=2.0,
        stage_eval_budget=0,
        stage_max_runtime_seconds=2.0,
        params=RollingParameters(delta_t_seconds=600.0, q_bar=8, stages=3),
        policy_callback=policy,
    )
    gate = report.get("gate")
    if gate is not None:
        _require_exact_stage_one_charger_halt(report)
        if [context.stage_index for context in contexts] != [0, 1]:
            raise RuntimeError(f"charger halt reached unexpected stages: {[c.stage_index for c in contexts]}")
        prior_output = contexts[1].previous_plan
        if prior_output is None:
            raise RuntimeError("charger halt did not expose the real previous-stage output")
        return ChargerRollingEvidence(report, tuple(contexts), prior_output, None)
    if [context.stage_index for context in contexts] != [0, 1, 2]:
        raise RuntimeError(f"charger truth fixture reached unexpected stages: {[c.stage_index for c in contexts]}")
    prior_output = contexts[1].previous_plan
    stage_one_output = contexts[2].previous_plan
    if prior_output is None or stage_one_output is None:
        raise RuntimeError("charger truth fixture did not capture both real stage outputs")

    return ChargerRollingEvidence(report, tuple(contexts), prior_output, stage_one_output)


def _cross_stage_charging_ledger_for_audit(
    previous_output: Solution,
    stage_one_output: Solution,
) -> Solution:
    previous_action = previous_output.charging_actions[0]
    stage_one_action = stage_one_output.charging_actions[0]
    if previous_action.vehicle_id == stage_one_action.vehicle_id:
        raise RuntimeError("real cross-stage charging actions reuse one route vehicle id")

    def charging_route(output: Solution, vehicle_id: str) -> Route:
        matches = [route for route in output.routes if route.vehicle_id == vehicle_id]
        if len(matches) != 1:
            raise RuntimeError(f"expected one real charging route for {vehicle_id}, got {len(matches)}")
        return matches[0]

    return Solution(
        routes=[
            charging_route(previous_output, previous_action.vehicle_id),
            charging_route(stage_one_output, stage_one_action.vehicle_id),
        ],
        charging_actions=[previous_action, stage_one_action],
        cross_site_services=[*previous_output.cross_site_services, *stage_one_output.cross_site_services],
    )


def _require_exact_stage_one_charger_halt(report: dict[str, Any]) -> None:
    violations = report.get("violations")
    exact = (
        report.get("gate") == "HALT_E7_STAGE_CHECK"
        and report.get("first_bad_stage") == 1
        and isinstance(violations, list)
        and len(violations) == 1
        and violations[0].get("constraint_type") == "STATION_CAPACITY"
        and violations[0].get("nodes") == "F1@slot0"
    )
    if not exact:
        raise RuntimeError(f"unexpected charger rolling halt: {report.get('gate')}, {violations}")


def _run_lifecycle_rolling_scenario(root: Path, event_type: str) -> LifecycleRollingEvidence:
    if event_type not in {"cancel", "demand_change"}:
        raise ValueError(f"unsupported lifecycle truth event type: {event_type}")

    instance = _zero_distance_instance(
        [
            Node("D0", "d", 0.0, 0.0, due_time=86_400.0, station_chargers=4),
            Node("C_DONE", "c", 0.0, 0.0, demand=10.0, due_time=10_000.0),
            Node("C_LOCK", "c", 0.0, 0.0, demand=20.0, ready_time=150.0, due_time=10_000.0),
            Node("C_PLANNED_OPEN", "c", 0.0, 0.0, demand=40.0, ready_time=1_000.0, due_time=10_000.0),
            Node("C_OPEN", "c", 0.0, 0.0, demand=30.0, due_time=10_000.0),
        ]
    )
    changed_demands = {
        "C_DONE": 110.0,
        "C_LOCK": 120.0,
        "C_PLANNED_OPEN": 140.0,
        "C_OPEN": 130.0,
    }
    events = [
        _event(
            f"{index}-{label}-{event_type}",
            event_type,
            customer_id,
            old_demand,
            0.0 if event_type == "cancel" else changed_demands[customer_id],
        )
        for index, (label, customer_id, old_demand) in enumerate(
            (
                ("done", "C_DONE", 10.0),
                ("locked", "C_LOCK", 20.0),
                ("planned-open", "C_PLANNED_OPEN", 40.0),
                ("open", "C_OPEN", 30.0),
            ),
            start=1,
        )
    ]
    previous_plan_ids = {"C_DONE", "C_LOCK", "C_PLANNED_OPEN"}
    stage_zero_plan = Solution(
        routes=[
            Route(
                "CV_PREVIOUS",
                "cv",
                "D0",
                ["D0", "C_DONE", "C_LOCK", "C_PLANNED_OPEN", "D0"],
            )
        ]
    )
    stage_one_plan = Solution(
        routes=[Route("CV_AFTER", "cv", "D0", ["D0", "C_LOCK", "C_PLANNED_OPEN", "C_OPEN", "D0"])]
    )
    contexts: list[RollingPolicyContext] = []

    def policy(context: RollingPolicyContext) -> RollingPolicyDecision:
        contexts.append(context)
        if context.stage_index == 0:
            return RollingPolicyDecision(
                plan_now_ids=set(previous_plan_ids),
                initial_plan=stage_zero_plan,
                stage_eval_budget=0,
                stage_max_runtime_seconds=2.0,
            )
        if context.stage_index == 1:
            return RollingPolicyDecision(
                plan_now_ids=set(context.active_ids),
                initial_plan=stage_one_plan,
                stage_eval_budget=0,
                stage_max_runtime_seconds=2.0,
            )
        raise RuntimeError(f"unexpected rolling stage {context.stage_index}")

    bundle_dir = root / "bundle"
    _write_truth_bundle(bundle_dir, instance, events)
    report = run_rolling_reoptimization(
        bundle_dir,
        output_json_path=root / "output" / "report.json",
        seed=1,
        eval_budget=0,
        max_runtime_seconds=2.0,
        stage_eval_budget=0,
        stage_max_runtime_seconds=2.0,
        params=RollingParameters(delta_t_seconds=100.0, q_bar=8, stages=2),
        policy_callback=policy,
    )
    return LifecycleRollingEvidence(event_type, report, tuple(contexts))


def _write_truth_bundle(path: Path, instance: Instance, events: list[DynamicEvent]) -> None:
    dynamic_module._write_dynamic_bundle(
        path,
        instance,
        _flat_carbon_profile(),
        {
            "source": "dynamic_truth_test",
            "num_cv": 4 if instance.num_cv is None else int(instance.num_cv),
            "num_ev": 4 if instance.num_ev is None else int(instance.num_ev),
        },
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


@pytest.mark.parametrize("policy_mode", ["normal", "random", "model", "exception_fallback"])
def test_every_dynamic_policy_branch_avoids_the_legacy_alns_entrypoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy_mode: str,
) -> None:
    instance = _zero_distance_instance(
        [
            Node("D0", "d", 0.0, 0.0, due_time=86_400.0, station_chargers=2),
            Node("C1", "c", 0.0, 0.0, demand=1.0, ready_time=150.0, due_time=10_000.0),
        ]
    )
    events = [_event("change-c1", "demand_change", "C1", 1.0, 2.0)]
    bundle_dir = tmp_path / policy_mode / "bundle"
    _write_truth_bundle(bundle_dir, instance, events)

    def legacy_tripwire(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("legacy ALNS entrypoint was executed")

    # The attribute exists before the fix and is deliberately allowed to be
    # absent after it.  A successful real rolling run proves the bound legacy
    # function was not used, rather than merely checking an import name.
    monkeypatch.setattr(dynamic_module, "run_alns_wouda", legacy_tripwire, raising=False)

    policy = None
    if policy_mode == "random":
        def random_policy(context: RollingPolicyContext) -> RollingPolicyDecision:
            chosen = set(sorted(context.active_ids)[::2]) or set(context.active_ids)
            return RollingPolicyDecision(plan_now_ids=chosen, metadata={"selector": "forced_random_probe"})

        policy = random_policy
    elif policy_mode == "model":
        def model_policy(context: RollingPolicyContext) -> RollingPolicyDecision:
            return RollingPolicyDecision(plan_now_ids=set(context.active_ids), metadata={"selector": "forced_model_probe"})

        policy = model_policy
    elif policy_mode == "exception_fallback":
        failure_count = 0

        def broken_model_policy(_context: RollingPolicyContext) -> RollingPolicyDecision:
            nonlocal failure_count
            failure_count += 1
            if failure_count == 1:
                raise RuntimeError("forced model failure")
            return RollingPolicyDecision(metadata={"selector": "recovered_model_probe"})

        policy = broken_model_policy

    report = run_rolling_reoptimization(
        bundle_dir,
        output_json_path=tmp_path / policy_mode / "report.json",
        seed=7,
        eval_budget=0,
        max_runtime_seconds=2.0,
        stage_eval_budget=0,
        stage_max_runtime_seconds=2.0,
        params=RollingParameters(delta_t_seconds=100.0, q_bar=8, stages=2),
        policy_callback=policy,
    )

    assert "gate" not in report
    assert report["dynamic_solver_backend"] == "setp_solver.algorithms.resetp_alns"
    assert report["static_control_backend"] == "setp_solver.algorithms.resetp_alns"
    expected_fallbacks = 1 if policy_mode == "exception_fallback" else 0
    assert report["policy_fallback_count"] == expected_fallbacks
