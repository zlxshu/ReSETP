from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from contextual_expert_solver import (  # noqa: E402
    ContextualExpertConfig,
    ExactMechanismExpertController,
    run_contextual_expert_alns,
)
from contextual_expert_fixtures import (  # noqa: E402
    PLATEAU_BUNDLE,
    PRICES_280,
    RESPONSIBILITY_BUNDLE,
    all_cv_plateau,
    plateau_solution,
    responsibility_binding_solution,
    responsibility_nonbinding_solution,
)
from setp_solver.algorithms.resetp_alns.support.mechanism_prescription import (  # noqa: E402
    CARBON_TIME,
    FLEET_CHARGE,
    RESPONSIBILITY,
    MechanismPrescriptionController,
    PrescriptionControllerConfig,
    assess_static_mechanisms,
)
from setp_solver.instance_loader import Instance, Node  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    Route,
    Solution,
)


def test_cheap_signals_have_mechanism_specific_binding() -> None:
    instance = _toy_instance()
    context = SimpleNamespace(
        instance=instance,
        carbon_profile=[
            {"actual_gco2_per_kwh": 10.0},
            {"actual_gco2_per_kwh": 20.0},
            {"actual_gco2_per_kwh": 30.0},
            {"actual_gco2_per_kwh": 100.0},
        ],
        prices=DEFAULT_PRICES,
        customer_home_depot={"C1": "D1"},
        allow_cross_depot=True,
    )
    solution = Solution(
        routes=[Route("CV1", "cv", "D1", ["D1", "C1", "D1"])],
        charging_actions=[
            ChargingAction(
                "CV1",
                "D1",
                1.0,
                1.0,
                3 * 1800.0,
            )
        ],
    )
    signals = {
        signal.mechanism_id: signal
        for signal in assess_static_mechanisms(solution, context)
    }
    assert signals[RESPONSIBILITY].eligible
    assert signals[FLEET_CHARGE].eligible
    assert signals[CARBON_TIME].eligible
    assert signals[RESPONSIBILITY].pressure == pytest.approx(1.0)
    assert signals[FLEET_CHARGE].pressure == pytest.approx(1.0)
    assert signals[CARBON_TIME].pressure == pytest.approx(1.0)


def test_controller_uses_pressure_then_fixed_mechanism_order() -> None:
    instance = _toy_instance()
    context = SimpleNamespace(
        instance=instance,
        carbon_profile=[
            {"actual_gco2_per_kwh": 10.0},
            {"actual_gco2_per_kwh": 20.0},
            {"actual_gco2_per_kwh": 30.0},
            {"actual_gco2_per_kwh": 100.0},
        ],
        prices=DEFAULT_PRICES,
        customer_home_depot={"C1": "D1"},
        allow_cross_depot=True,
    )
    solution = Solution(
        routes=[Route("CV1", "cv", "D1", ["D1", "C1", "D1"])],
        charging_actions=[
            ChargingAction(
                "CV1",
                "D1",
                1.0,
                1.0,
                3 * 1800.0,
            )
        ],
    )
    controller = MechanismPrescriptionController(
        PrescriptionControllerConfig(
            assessment_interval=1,
            per_mechanism_cooldown=3,
        )
    )
    selected = []
    for eval_count in range(3):
        prescription = controller.choose(
            solution,
            context,
            eval_count=eval_count,
            move_count=eval_count + 1,
            moves_since_best_improvement=eval_count,
        )
        assert prescription is not None
        selected.append(prescription.mechanism_id)
        controller.record_no_candidate(
            prescription,
            activity={"test_only": True},
        )
    assert selected == [RESPONSIBILITY, FLEET_CHARGE, CARBON_TIME]


@pytest.mark.parametrize("budget", [0, 1, 2, 5])
def test_fleet_binding_budget_microgate_stays_in_one_loop(
    budget: int,
) -> None:
    binding = all_cv_plateau()
    result = run_contextual_expert_alns(
        PLATEAU_BUNDLE,
        seed=1,
        prices=PRICES_280,
        initial_solution=binding,
        config=ContextualExpertConfig(
            total_eval_budget=budget,
            apply_terminal_completion=False,
            assessment_interval=20,
            per_mechanism_cooldown=60,
            enabled_mechanisms=(FLEET_CHARGE,),
        ),
    )
    activity = result.mechanism_activity
    expected_mechanism = 0 if budget == 0 else 1
    assert result.evaluations == budget
    assert activity["search_loop_count"] == 1
    assert activity["search_restart_count"] == 0
    assert activity["mechanism_candidate_evaluations"] == expected_mechanism
    assert activity["generic_candidate_evaluations"] == (
        budget - expected_mechanism
    )
    assert (
        activity["mechanism_candidate_evaluations"]
        + activity["generic_candidate_evaluations"]
        == budget
    )
    mechanism = activity["mechanism_diagnostics"]
    if budget == 0:
        assert mechanism["attempts"][FLEET_CHARGE] == 0
    else:
        assert mechanism["attempts"][FLEET_CHARGE] == 1
        assert mechanism["changed"][FLEET_CHARGE] == 1
        assert mechanism["accepted"][FLEET_CHARGE] == 1
        assert mechanism["best_improved"][FLEET_CHARGE] == 1
        assert mechanism["scope_violations"][FLEET_CHARGE] == 0


def test_carbon_binding_builds_one_scoped_candidate() -> None:
    result = run_contextual_expert_alns(
        PLATEAU_BUNDLE,
        seed=1,
        prices=PRICES_280,
        initial_solution=plateau_solution(),
        config=ContextualExpertConfig(
            total_eval_budget=1,
            apply_terminal_completion=False,
            enabled_mechanisms=(CARBON_TIME,),
        ),
    )
    mechanism = result.mechanism_activity["mechanism_diagnostics"]
    assert mechanism["attempts"][CARBON_TIME] == 1
    assert mechanism["changed"][CARBON_TIME] == 1
    assert mechanism["accepted"][CARBON_TIME] == 1
    assert mechanism["scope_violations"][CARBON_TIME] == 0
    event = mechanism["events"][0]
    assert event["route_customer_order_changed"] is False
    assert event["vehicle_type_changed"] is False
    assert event["charging_changed"] is True
    assert event["evaluations_added"] == 1


def test_responsibility_binding_builds_one_scoped_candidate() -> None:
    binding = responsibility_binding_solution()
    result = run_contextual_expert_alns(
        RESPONSIBILITY_BUNDLE,
        seed=1,
        prices=PRICES_280,
        initial_solution=binding,
        config=ContextualExpertConfig(
            total_eval_budget=1,
            apply_terminal_completion=False,
            enabled_mechanisms=(RESPONSIBILITY,),
            responsibility_exact_candidates=1,
        ),
    )
    mechanism = result.mechanism_activity["mechanism_diagnostics"]
    assert mechanism["attempts"][RESPONSIBILITY] == 1
    assert mechanism["changed"][RESPONSIBILITY] == 1
    assert mechanism["accepted"][RESPONSIBILITY] == 1
    assert mechanism["scope_violations"][RESPONSIBILITY] == 0
    assert mechanism["events"][0]["responsibility_changed"] is True


def test_responsibility_nonbinding_attempt_is_not_charged() -> None:
    initial = responsibility_nonbinding_solution()
    result = run_contextual_expert_alns(
        RESPONSIBILITY_BUNDLE,
        seed=1,
        prices=PRICES_280,
        initial_solution=initial,
        config=ContextualExpertConfig(
            total_eval_budget=1,
            apply_terminal_completion=False,
            enabled_mechanisms=(RESPONSIBILITY,),
            responsibility_exact_candidates=1,
        ),
    )
    activity = result.mechanism_activity
    mechanism = activity["mechanism_diagnostics"]
    assert activity["mechanism_candidate_evaluations"] == 0
    assert activity["generic_candidate_evaluations"] == 1
    assert mechanism["complete_candidate_evaluations"][RESPONSIBILITY] == 0
    assert mechanism["accepted"][RESPONSIBILITY] == 0
def _toy_instance() -> Instance:
    nodes = [
        Node("D1", "d", 0.0, 0.0),
        Node("D2", "d", 10.0, 0.0),
        Node("C1", "c", 5.0, 0.0, demand=1.0),
    ]
    return Instance(
        nodes=nodes,
        distance_matrix=[
            [0.0, 10.0, 5.0],
            [10.0, 0.0, 5.0],
            [5.0, 5.0, 0.0],
        ],
        num_cv=2,
        num_ev=2,
    )
