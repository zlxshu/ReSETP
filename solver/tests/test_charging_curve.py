from __future__ import annotations

import pytest

from baselines.e4_e5.nonlinear_charging_replay_20260717 import (
    best_start_by_weight as replay_best_start_by_weight,
)
from baselines.e4_e5.nonlinear_charging_replay_20260717 import (
    scale_normalized_curve as replay_scale_normalized_curve,
)
from baselines.e4_e5.nonlinear_charging_replay_20260717 import (
    slot_energy_kwh as replay_slot_energy_kwh,
)
from setp_solver.charging_curve import (
    L100_CONTROL,
    NL80_STRESS,
    NL90_MILD,
    ChargingCurveError,
    best_start_by_weight,
    half_hour_boundaries,
    minimum_departure_energies_kwh,
    pack_trip_chain,
    slot_energy_kwh,
)


@pytest.mark.parametrize("spec", [L100_CONTROL, NL90_MILD, NL80_STRESS])
def test_inverse_closes_at_breakpoints_and_interior_points(spec) -> None:
    curve = spec.scale(capacity_kwh=280.0, reference_power_kw=22.0)
    points = list(curve.energy_breakpoints_kwh)
    points.extend(
        (left + right) / 2
        for left, right in zip(
            curve.energy_breakpoints_kwh,
            curve.energy_breakpoints_kwh[1:],
        )
    )
    for energy in points:
        cumulative = curve.cumulative_time_seconds(energy)
        assert curve.inverse_cumulative_time_seconds(cumulative) == pytest.approx(
            energy
        )


def test_l100_control_degenerates_to_constant_power_exactly() -> None:
    curve = L100_CONTROL.scale(capacity_kwh=280.0, reference_power_kw=22.0)
    for start, end in ((0.0, 22.0), (17.0, 93.0), (250.0, 280.0)):
        assert curve.duration_seconds(start, end) == pytest.approx(
            (end - start) / 22.0 * 3600.0
        )
    assert curve.reachable_energy_kwh(17.0, 3600.0) == pytest.approx(39.0)
    required = minimum_departure_energies_kwh(
        curve, (50.0, 50.0), (3600.0,)
    )
    assert required == pytest.approx((78.0, 50.0))


def test_nonlinear_backward_recursion_matches_dense_scan() -> None:
    curve = NL80_STRESS.scale(
        capacity_kwh=10.0, reference_power_kw=2.0
    )
    drives = (3.0, 4.0, 3.0)
    gaps = (1800.0, 3600.0)
    exact = minimum_departure_energies_kwh(curve, drives, gaps)[0]
    step = 0.001
    candidate = drives[0]
    dense_best = None
    while candidate <= curve.capacity_kwh + 1e-12:
        battery = candidate
        feasible = True
        for index, drive in enumerate(drives):
            battery -= drive
            if battery < -1e-12:
                feasible = False
                break
            if index < len(gaps):
                battery = curve.reachable_energy_kwh(
                    max(0.0, battery), gaps[index]
                )
        if feasible:
            dense_best = candidate
            break
        candidate += step
    assert dense_best is not None
    assert dense_best - step <= exact <= dense_best + step


def test_pack_trip_chain_uses_exact_nonlinear_duration() -> None:
    curve = NL90_MILD.scale(
        capacity_kwh=100.0, reference_power_kw=20.0
    )
    packed = pack_trip_chain(curve, (40.0, 25.0), (3600.0,))
    assert packed[0].charge_duration_seconds <= 3600.0 + 1e-8
    assert packed[0].charge_duration_seconds == pytest.approx(
        curve.duration_seconds(
            packed[0].return_energy_kwh,
            packed[1].departure_energy_kwh,
        )
    )


@pytest.mark.parametrize("spec", [L100_CONTROL, NL90_MILD, NL80_STRESS])
def test_production_kernel_matches_frozen_replay(spec) -> None:
    capacity = 280.0
    power = 22.0
    curve = spec.scale(
        capacity_kwh=capacity, reference_power_kw=power
    )
    replay = replay_scale_normalized_curve(
        capacity_kwh=capacity,
        soc_breakpoints=spec.soc_breakpoints,
        relative_powers=spec.relative_powers,
        reference_power_kw=power,
    )
    assert curve.energy_breakpoints_kwh == pytest.approx(
        replay.energy_breakpoints_kwh
    )
    assert curve.cumulative_seconds == pytest.approx(
        replay.cumulative_seconds
    )

    start = 0.71 * capacity
    end = 0.98 * capacity
    boundaries = half_hour_boundaries(days=2)
    charge_start = 12_345.0
    production_energy = slot_energy_kwh(
        curve,
        start_energy_kwh=start,
        end_energy_kwh=end,
        charging_start_seconds=charge_start,
        slot_boundaries_seconds=boundaries,
    )
    replay_energy = replay_slot_energy_kwh(
        replay,
        start_energy_kwh=start,
        end_energy_kwh=end,
        charging_start_seconds=charge_start,
        slot_boundaries_seconds=boundaries,
    )
    assert production_energy == pytest.approx(replay_energy)

    weights = tuple(0.5 + (index % 7) * 0.1 for index in range(96))
    production_best = best_start_by_weight(
        curve,
        start_energy_kwh=start,
        end_energy_kwh=end,
        earliest_start_seconds=0.0,
        latest_finish_seconds=86_400.0,
        slot_boundaries_seconds=boundaries,
        weights_per_kwh=weights,
    )
    replay_best = replay_best_start_by_weight(
        replay,
        start_energy_kwh=start,
        end_energy_kwh=end,
        earliest_start_seconds=0.0,
        latest_finish_seconds=86_400.0,
        slot_boundaries_seconds=boundaries,
        weights_per_kwh=weights,
    )
    assert production_best[0] == pytest.approx(replay_best[0])
    assert production_best[1] == pytest.approx(replay_best[1])
    assert production_best[2] == pytest.approx(replay_best[2])


def test_invalid_curve_requests_fail_closed() -> None:
    curve = NL80_STRESS.scale(
        capacity_kwh=10.0, reference_power_kw=2.0
    )
    with pytest.raises(ChargingCurveError):
        curve.duration_seconds(9.0, 8.0)
    with pytest.raises(ChargingCurveError):
        curve.inverse_cumulative_time_seconds(
            curve.cumulative_seconds[-1] + 1.0
        )
    with pytest.raises(ChargingCurveError):
        minimum_departure_energies_kwh(curve, (8.0, 8.0), (0.0,))
