"""Wiring tests for the optional frvcpy fixed-route charging layer."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import (  # noqa: E402
    _build_context,
    _policy,
)
import setp_solver.algorithms.problem_hgs.charging as charging_module  # noqa: E402
from setp_solver.algorithms.problem_hgs.charging import (  # noqa: E402
    _repair_one_ev_duty,
    repair_changed_duties,
)
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    DutyFullEvaluator,
)
from setp_solver.algorithms.problem_hgs.model import (  # noqa: E402
    DutyTrip,
    PhysicalVehicleDuty,
)
from setp_solver.china81 import ENDOGENOUS_FLEET_PARAMETERS  # noqa: E402
from setp_solver.instance_loader import Instance, Node  # noqa: E402


INSTANCE_ID = "cn-prd-50c-01-V3-TWO-SHIFT-GZ-FS"


@pytest.fixture(scope="module")
def rebuilt_context():
    repo = Path(__file__).parents[2]
    return _build_context(
        repo,
        INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
        depot_charging_scenario_name="60kw",
    )


def _move_one_cv_duty_to_idle_ev(initial):
    source_id = "CV_D_guangzhou_4"
    target_id = "EV_D_guangzhou_1"
    duties = {duty.physical_vehicle_id: duty for duty in initial.duties}
    source = duties[source_id]
    target = duties[target_id]
    assert len(source.trips) == 1
    assert not target.trips
    replacements = {
        source_id: replace(source, trips=(), charging_sessions=()),
        target_id: replace(
            target,
            trips=source.trips,
            charging_sessions=(),
        ),
    }
    candidate = replace(
        initial,
        duties=tuple(
            replacements.get(duty.physical_vehicle_id, duty)
            for duty in initial.duties
        ),
    )
    return candidate, {source_id, target_id}, target_id


def test_default_off_does_not_enter_frvcpy_branch(
    rebuilt_context,
    monkeypatch,
) -> None:
    _bundle, initial, _neutral, context = rebuilt_context
    evaluator = DutyFullEvaluator(context)
    candidate, changed, _target_id = _move_one_cv_duty_to_idle_ev(initial)
    implicit = _policy(evaluator)
    explicit = replace(implicit, frvcpy_enabled=False)

    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("default-off repair called frvcpy")

    monkeypatch.setattr(
        charging_module,
        "solve_fixed_route_charging",
        unexpected_call,
    )
    implicit_result = repair_changed_duties(
        initial,
        candidate,
        changed_duty_ids=changed,
        context=context,
        policy=implicit,
    )
    explicit_result = repair_changed_duties(
        initial,
        candidate,
        changed_duty_ids=changed,
        context=context,
        policy=explicit,
    )

    assert implicit.frvcpy_enabled is False
    assert implicit_result == explicit_result


def _long_route_context(rebuilt_context):
    bundle, _initial, _neutral, _context = rebuilt_context
    identifiers = ("D", "C1", "C2", "F")
    distances = [[400_000.0] * 4 for _ in range(4)]
    for index in range(4):
        distances[index][index] = 0.0
    arcs = {
        ("D", "C1"): 100_000.0,
        ("C1", "C2"): 100_000.0,
        ("C2", "D"): 100_000.0,
        ("C1", "F"): 10_000.0,
        ("F", "C2"): 90_000.0,
        ("D", "F"): 110_000.0,
        ("F", "D"): 90_000.0,
        ("C2", "F"): 90_000.0,
        ("F", "C1"): 10_000.0,
        ("C1", "D"): 100_000.0,
        ("C2", "C1"): 100_000.0,
        ("D", "C2"): 100_000.0,
    }
    for (left, right), distance in arcs.items():
        distances[identifiers.index(left)][identifiers.index(right)] = distance
    nodes = [
        Node(
            "D",
            "d",
            0.0,
            0.0,
            ready_time=0.0,
            due_time=1_000_000.0,
            charge_power_kw=60.0,
            city="guangzhou",
        ),
        Node(
            "C1",
            "c",
            0.0,
            0.0,
            ready_time=50_000.0,
            due_time=900_000.0,
            city="guangzhou",
        ),
        Node(
            "C2",
            "c",
            0.0,
            0.0,
            ready_time=0.0,
            due_time=900_000.0,
            city="guangzhou",
        ),
        Node(
            "F",
            "f",
            0.0,
            0.0,
            ready_time=0.0,
            due_time=900_000.0,
            charge_power_kw=60.0,
            city="guangzhou",
        ),
    ]
    return SimpleNamespace(
        bundle=SimpleNamespace(
            instance=Instance(nodes=nodes, distance_matrix=distances),
            prices=bundle.prices,
            time_profile=bundle.time_profile,
        ),
        depot_charge_window_mode="same_day_predeparture",
    )


def test_enabled_switch_changes_fixed_route_charge_amounts(
    rebuilt_context,
) -> None:
    _bundle, _initial, _neutral, real_context = rebuilt_context
    context = _long_route_context(rebuilt_context)
    duty = PhysicalVehicleDuty(
        "EV_D",
        "ev",
        "D",
        trips=(DutyTrip(1, ("C1", "C2")),),
    )
    policy = _policy(DutyFullEvaluator(real_context))

    existing = _repair_one_ev_duty(
        duty,
        duty,
        context=context,
        policy=policy,
    )
    frvcpy = _repair_one_ev_duty(
        duty,
        duty,
        context=context,
        policy=replace(policy, frvcpy_enabled=True),
    )
    existing_by_station = {
        session.station_id: session for session in existing.charging_sessions
    }
    frvcpy_by_station = {
        session.station_id: session for session in frvcpy.charging_sessions
    }

    assert existing.trips[0].effective_route_visits == ("C1", "F", "C2")
    assert frvcpy.trips[0].effective_route_visits == ("C1", "F", "C2")
    assert existing_by_station["D"].energy_kwh == pytest.approx(77.28)
    assert frvcpy_by_station["D"].energy_kwh == pytest.approx(65.688)
    assert frvcpy_by_station["F"].energy_kwh > existing_by_station["F"].energy_kwh
    assert frvcpy.charging_sessions != existing.charging_sessions


def test_enabled_repair_passes_complete_truth_ruler(rebuilt_context) -> None:
    bundle, initial, _neutral, context = rebuilt_context
    evaluator = DutyFullEvaluator(context)
    candidate, changed, target_id = _move_one_cv_duty_to_idle_ev(initial)
    repaired = repair_changed_duties(
        initial,
        candidate,
        changed_duty_ids=changed,
        context=context,
        policy=replace(_policy(evaluator), frvcpy_enabled=True),
    )
    evaluation = evaluator.evaluate(repaired)
    customers = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    served = {
        node_id
        for route in evaluation.prepared_solution.routes
        for node_id in route.node_sequence[1:-1]
        if node_id in customers
    }
    target = next(
        duty
        for duty in repaired.duties
        if duty.physical_vehicle_id == target_id
    )

    assert target.charging_sessions
    assert evaluation.feasible
    assert not evaluation.violations
    assert served == set(customers)
    assert sum(customers[item].demand for item in served) == pytest.approx(
        sum(node.demand for node in customers.values())
    )
