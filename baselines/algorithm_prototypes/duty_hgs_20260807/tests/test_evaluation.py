"""v1 2026-08-07: exact and incrementally cached Duty evaluation tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from duty_hgs.charging import ChargingRepairPolicy, repair_changed_duties
from duty_hgs.evaluation import (
    DutyIncrementalEvaluator,
    DutyFullEvaluator,
    _assert_no_hidden_repair,
    _measure_violations,
    assert_evaluations_equivalent,
)
from duty_hgs.feedback import RelocateCustomerMove
from duty_hgs.model import DutyIndividual, DutyTrip, PhysicalVehicleDuty
from setp_solver.check import BATTERY, FLEET_SIZE, TIME_WINDOW, Violation
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.search.multitrip_schedule import (
    DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    prepare_multitrip_solution,
    route_timing,
)
from setp_solver.solution import Route, Solution


def test_full_evaluator_preserves_explicit_physical_assignment(evaluated_fixture) -> None:
    individual, evaluator = evaluated_fixture
    result = evaluator.evaluate(individual)

    assert result.prepared_solution == individual.to_solution()
    assert result.source == "full"
    assert set(result.participation_margin) == set(evaluator.context.independent_profit)
    assert all(abs(value) <= 1.0e-7 for value in result.participation_margin.values())


def test_valid_first_and_between_trip_depot_charges_survive_duty_round_trip() -> None:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=100_000.0),
        Node(
            "C1", "c", 0.0, 0.0,
            demand=10.0, ready_time=1_000.0, due_time=4_000.0,
            service_time=100.0,
        ),
        Node(
            "C2", "c", 0.0, 0.0,
            demand=10.0, ready_time=6_000.0, due_time=9_000.0,
            service_time=100.0,
        ),
    ]
    matrix = [
        [0.0 if left == right else 1_000.0 for right in range(len(nodes))]
        for left in range(len(nodes))
    ]
    instance = Instance(nodes, matrix, num_cv=0, num_ev=2)
    routes = [
        Route("EV_A", "ev", "D0", ["D0", "C1", "D0"]),
        Route("EV_B", "ev", "D0", ["D0", "C2", "D0"]),
    ]
    probe_prices = PriceParameters(
        B_battery_kwh=280.0,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
    )
    drive_energy = route_timing(routes[0], instance, probe_prices).drive_energy_kwh
    prices = PriceParameters(
        B_battery_kwh=drive_energy * 1.5,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
    )
    prepared, _ = prepare_multitrip_solution(
        Solution(routes=routes),
        instance,
        prices,
        depot_charge_window_mode=DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    )

    decoded = DutyIndividual.from_solution(prepared).to_solution()
    repeated, _ = prepare_multitrip_solution(
        decoded,
        instance,
        prices,
        depot_charge_window_mode=DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    )

    _assert_no_hidden_repair(decoded, repeated)
    assert repeated == prepared
    assert {action.vehicle_id for action in repeated.charging_actions} == {
        "EV_D0_1#T1",
        "EV_D0_1#T2",
    }


def test_incremental_cache_is_scope_checked_and_full_truth_equivalent(evaluated_fixture) -> None:
    individual, full = evaluated_fixture
    base = full.evaluate(individual)
    move = RelocateCustomerMove(
        action_id="real-china81-content-change",
        source_duty_id="EV_D_beijing_1",
        source_trip_index=1,
        customer_id="C006",
        target_duty_id="CV_D_beijing_1",
        target_trip_index=1,
        target_position=0,
        predicted_remaining_overflow_kg=0.0,
        predicted_relief_kg=0.0,
    )
    changed_duty_ids = {"EV_D_beijing_1", "CV_D_beijing_1"}
    candidate = repair_changed_duties(
        individual,
        move.apply(individual),
        changed_duty_ids=changed_duty_ids,
        context=full.context,
        policy=ChargingRepairPolicy(
            strategy="integrated",
            carbon_weight=1.0,
            depot_charge_window_mode=full.context.depot_charge_window_mode,
            charge_timing_policy="cost_plus_carbon",
            charge_amount_strategy="just_enough",
            public_station_candidate_mode="parallel",
            carbon_profiles_by_day_offset=None,
        ),
    )

    incremental = DutyIncrementalEvaluator(full)
    incremental.seed(individual)
    cached = incremental.evaluate_after_change(
        individual,
        candidate,
        changed_duty_ids=changed_duty_ids,
    )
    truth = full.evaluate(candidate)

    assert_evaluations_equivalent(cached, truth)
    assert cached.source == "incremental_verified"
    assert cached.accounting["recomputed_duties"] == 2
    assert cached.accounting["reused_duties"] == len(individual.duties) - 2
    assert cached.prepared_solution != base.prepared_solution
    assert cached.total_cost != base.total_cost
    assert cached.breakdown["cost_carbon"] != base.breakdown["cost_carbon"]

    incremental.seed(individual)
    with pytest.raises(ValueError, match="changed duty scope"):
        incremental.evaluate_after_change(
            individual,
            candidate,
            changed_duty_ids=set(),
        )


def test_incremental_cost_changes_remain_equal_to_full_truth(
    feedback_fixture,
) -> None:
    individual, full = feedback_fixture
    move = RelocateCustomerMove(
        action_id="technical-cost-change",
        source_duty_id="CV_D0_1",
        source_trip_index=1,
        customer_id="C1",
        target_duty_id="CV_D0_2",
        target_trip_index=1,
        target_position=0,
        predicted_remaining_overflow_kg=0.0,
        predicted_relief_kg=2.0,
    )
    candidate = move.apply(individual)
    incremental = DutyIncrementalEvaluator(full)
    incremental.seed(individual)

    cached = incremental.evaluate_after_change(
        individual,
        candidate,
        changed_duty_ids={"CV_D0_1", "CV_D0_2"},
    )
    truth = full.evaluate(candidate)

    assert_evaluations_equivalent(cached, truth)
    assert cached.total_cost != full.evaluate(individual).total_cost


def test_incremental_truth_sentinel_can_be_explicitly_disabled(
    feedback_fixture,
) -> None:
    individual, full = feedback_fixture
    context = replace(
        full.context,
        incremental_full_truth_sentinel_enabled=False,
    )
    evaluator = DutyFullEvaluator(context)
    move = RelocateCustomerMove(
        action_id="technical-sentinel-off",
        source_duty_id="CV_D0_1",
        source_trip_index=1,
        customer_id="C1",
        target_duty_id="CV_D0_2",
        target_trip_index=1,
        target_position=0,
        predicted_remaining_overflow_kg=0.0,
        predicted_relief_kg=2.0,
    )
    candidate = move.apply(individual)
    incremental = DutyIncrementalEvaluator(evaluator)
    incremental.seed(individual)

    cached = incremental.evaluate_after_change(
        individual,
        candidate,
        changed_duty_ids={"CV_D0_1", "CV_D0_2"},
    )
    truth = evaluator.evaluate(candidate)

    assert_evaluations_equivalent(cached, truth)
    assert cached.source == "incremental_unverified"
    assert cached.accounting["sentinel_evaluations"] == 0
    assert evaluator.sentinel_calls == 0


def test_native_violation_magnitudes_are_not_reduced_to_counts(
    feedback_fixture,
) -> None:
    individual, evaluator = feedback_fixture
    violations = (
        Violation(
            TIME_WINDOW,
            "CV_D0_1#T1",
            "C1",
            "late by 12.500 s (due l=10.000, start=22.500)",
        ),
        Violation(
            BATTERY,
            "EV_D0_1#T1",
            "D0->C1",
            "battery after arc is -3.250000 kWh < 0",
        ),
        Violation(
            FLEET_SIZE,
            "",
            "cv",
            "CV physical vehicles 5 exceed available fuel vehicles 2",
        ),
    )

    magnitudes = _measure_violations(
        violations,
        individual.to_solution(),
        evaluator.context.bundle,
        {"D0": 0.0},
    )

    assert magnitudes == (12.5, 3.25, 3.0)


def test_customer_added_to_ev_rebuilds_battery_ledger_before_full_evaluation(
    evaluated_fixture,
) -> None:
    individual, full = evaluated_fixture
    move = RelocateCustomerMove(
        action_id="add-customer-to-ev-ledger-regression",
        source_duty_id="CV_D_beijing_1",
        source_trip_index=1,
        customer_id="C004",
        target_duty_id="EV_D_beijing_1",
        target_trip_index=1,
        target_position=0,
        predicted_remaining_overflow_kg=0.0,
        predicted_relief_kg=0.0,
    )
    raw_candidate = move.apply(individual)
    repaired = repair_changed_duties(
        individual,
        raw_candidate,
        changed_duty_ids={"CV_D_beijing_1", "EV_D_beijing_1"},
        context=full.context,
        policy=ChargingRepairPolicy(
            strategy="integrated",
            carbon_weight=1.0,
            depot_charge_window_mode=(
                full.context.depot_charge_window_mode
            ),
            charge_timing_policy="cost_plus_carbon",
            charge_amount_strategy="just_enough",
            public_station_candidate_mode="parallel",
            carbon_profiles_by_day_offset=None,
        ),
    )

    result = full.evaluate(repaired)

    assert result.prepared_solution == repaired.to_solution()
    assert any(
        violation.type == "CAPACITY" for violation in result.violations
    )
    assert all(
        "broken battery ledger" not in violation.detail
        for violation in result.violations
    )


def test_all_cv_candidate_uses_formal_fleet_cap(feedback_fixture) -> None:
    _, full = feedback_fixture
    candidate = DutyIndividual(
        duties=tuple(
            PhysicalVehicleDuty(
                physical_vehicle_id=f"CV_D0_{index}",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(DutyTrip(1, (customer,)),),
            )
            for index, customer in enumerate(("C1", "C2", "C3"), start=1)
        ),
        source="three-cv-formal-cap-regression",
    )

    result = full.evaluate(candidate)

    assert any("fleet" in violation.type.lower() for violation in result.violations)
