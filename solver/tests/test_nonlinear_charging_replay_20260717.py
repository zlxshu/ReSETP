from __future__ import annotations

import math

import pytest

from baselines.e4_e5.nonlinear_charging_replay_20260717 import (
    ChargingCurveError,
    PiecewiseChargingCurve,
    best_start_by_weight,
    candidate_start_times,
    half_hour_boundaries,
    scale_normalized_curve,
    slot_energy_kwh,
)


def curve() -> PiecewiseChargingCurve:
    return scale_normalized_curve(
        capacity_kwh=80.0,
        soc_breakpoints=(0.0, 0.8, 0.9, 1.0),
        relative_powers=(1.0, 0.5, 0.25),
        reference_power_kw=60.0,
    )


def test_curve_powers_time_and_constant_power_degeneracy() -> None:
    test_curve = curve()
    assert test_curve.segment_powers_kw == pytest.approx((60.0, 30.0, 15.0))
    assert test_curve.cumulative_seconds == pytest.approx((0.0, 3840.0, 4800.0, 6720.0))
    assert test_curve.duration_seconds(20.0, 60.0) == pytest.approx(3600.0 * 40.0 / 60.0)
    assert test_curve.duration_seconds(63.0, 80.0) == pytest.approx(2940.0)
    phases = test_curve.phases(63.0, 80.0)
    assert sum(phase.energy_kwh for phase in phases) == pytest.approx(17.0)
    assert phases[-1].relative_end_seconds == pytest.approx(2940.0)


def test_curve_rejects_increasing_power_and_invalid_intervals() -> None:
    with pytest.raises(ChargingCurveError, match="non-increasing"):
        PiecewiseChargingCurve((0.0, 40.0, 80.0), (0.0, 3600.0, 5400.0))
    with pytest.raises(ChargingCurveError, match="require 0 <= start"):
        curve().duration_seconds(70.0, 60.0)


def test_slot_integration_closes_energy_across_phase_and_grid_boundaries() -> None:
    test_curve = curve()
    boundaries = half_hour_boundaries(days=1)
    energy = slot_energy_kwh(
        test_curve,
        start_energy_kwh=63.0,
        end_energy_kwh=80.0,
        charging_start_seconds=20.0 * 3600.0 + 17.0 * 60.0,
        slot_boundaries_seconds=boundaries,
    )
    assert sum(energy) == pytest.approx(17.0, abs=1e-10)
    assert len([value for value in energy if value > 0.0]) >= 2
    with pytest.raises(ChargingCurveError, match="fully cover"):
        slot_energy_kwh(
            test_curve,
            start_energy_kwh=63.0,
            end_energy_kwh=80.0,
            charging_start_seconds=23.5 * 3600.0,
            slot_boundaries_seconds=boundaries,
        )


def test_candidate_set_contains_dense_grid_optimum_for_stepwise_weights() -> None:
    test_curve = curve()
    boundaries = half_hour_boundaries(days=1)
    weights = tuple(0.8 if 32 <= slot < 40 else 0.2 for slot in range(48))
    earliest = 14.0 * 3600.0
    latest_finish = 23.0 * 3600.0
    exact_start, exact_objective, exact_energy = best_start_by_weight(
        test_curve,
        start_energy_kwh=63.0,
        end_energy_kwh=80.0,
        earliest_start_seconds=earliest,
        latest_finish_seconds=latest_finish,
        slot_boundaries_seconds=boundaries,
        weights_per_kwh=weights,
    )
    candidates = candidate_start_times(
        test_curve,
        start_energy_kwh=63.0,
        end_energy_kwh=80.0,
        earliest_start_seconds=earliest,
        latest_finish_seconds=latest_finish,
        slot_boundaries_seconds=boundaries,
    )
    assert exact_start in candidates
    assert sum(exact_energy) == pytest.approx(17.0)

    dense_best = math.inf
    start = earliest
    latest_start = latest_finish - test_curve.duration_seconds(63.0, 80.0)
    while start <= latest_start + 1e-9:
        energy = slot_energy_kwh(
            test_curve,
            start_energy_kwh=63.0,
            end_energy_kwh=80.0,
            charging_start_seconds=start,
            slot_boundaries_seconds=boundaries,
        )
        dense_best = min(dense_best, sum(value * weight for value, weight in zip(energy, weights, strict=True)))
        start += 1.0
    assert exact_objective <= dense_best + 1e-10


def test_infeasible_window_returns_no_candidate() -> None:
    test_curve = curve()
    assert candidate_start_times(
        test_curve,
        start_energy_kwh=63.0,
        end_energy_kwh=80.0,
        earliest_start_seconds=1000.0,
        latest_finish_seconds=2000.0,
        slot_boundaries_seconds=half_hour_boundaries(),
    ) == ()
