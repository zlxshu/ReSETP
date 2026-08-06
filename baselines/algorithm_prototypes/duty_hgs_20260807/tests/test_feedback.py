"""v1 2026-08-07: addressable pressure and ranking-curve truth test."""

from __future__ import annotations

from duty_hgs.charging import ChargingRepairPolicy
from duty_hgs.feedback import (
    build_capacity_relocates,
    pressure_signals_from_evaluation,
    run_feedback_truth_probe,
)


def test_capacity_pressure_points_to_real_duty_and_move(feedback_fixture) -> None:
    overloaded, evaluator = feedback_fixture
    result = evaluator.evaluate(overloaded)
    signals = pressure_signals_from_evaluation(result)
    capacity = next(signal for signal in signals if signal.resource == "CAPACITY")

    assert capacity.duty_id == "CV_D0_1"
    assert capacity.magnitude == 2.0
    moves = build_capacity_relocates(
        overloaded,
        capacity,
        evaluator.context.bundle.instance,
        evaluator.context.bundle.prices,
    )
    assert moves
    assert all(move.source_duty_id == capacity.duty_id for move in moves)

    probe = run_feedback_truth_probe(
        overloaded,
        evaluator,
        capacity,
        random_seed=17,
        charging_policy=ChargingRepairPolicy(
            strategy="integrated",
            carbon_weight=1.0,
            depot_charge_window_mode=(
                evaluator.context.depot_charge_window_mode
            ),
            charge_timing_policy="cost_plus_carbon",
            charge_amount_strategy="just_enough",
            public_station_candidate_mode="parallel",
            carbon_profiles_by_day_offset=None,
        ),
    )
    assert probe.records
    assert sorted(row.truth_rank for row in probe.records) == list(
        range(1, len(probe.records) + 1)
    )
    assert len(probe.pressure_curve) == len(probe.records)
    assert len(probe.random_curve) == len(probe.records)
    assert probe.threshold_or_pass_label is None
