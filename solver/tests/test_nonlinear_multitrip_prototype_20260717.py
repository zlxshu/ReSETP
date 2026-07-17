from __future__ import annotations

import pytest

from baselines.e4_e5.nonlinear_charging_replay_20260717 import (
    ChargingCurveError,
    scale_normalized_curve,
)
from baselines.e4_e5.nonlinear_multitrip_prototype_20260717 import (
    inverse_cumulative_time_seconds,
    minimum_departure_energies_kwh,
    pack_trip_chain,
    reachable_energy_kwh,
)


def constant_curve():
    return scale_normalized_curve(
        capacity_kwh=280.0,
        soc_breakpoints=(0.0, 1.0),
        relative_powers=(1.0,),
        reference_power_kw=22.0,
    )


def stress_curve():
    return scale_normalized_curve(
        capacity_kwh=10.0,
        soc_breakpoints=(0.0, 0.8, 0.9, 1.0),
        relative_powers=(1.0, 0.5, 0.25),
        reference_power_kw=2.0,
    )


def test_inverse_round_trip_closes_at_breakpoints_and_interior_points() -> None:
    curve = stress_curve()
    for energy in (0.0, 1.25, 8.0, 8.5, 9.0, 9.75, 10.0):
        assert inverse_cumulative_time_seconds(
            curve, curve.cumulative_time_seconds(energy)
        ) == pytest.approx(energy)


def test_reachable_energy_respects_nonlinear_tail_and_capacity() -> None:
    curve = stress_curve()
    assert reachable_energy_kwh(curve, 0.0, 3600.0) == pytest.approx(2.0)
    assert reachable_energy_kwh(curve, 8.0, 3600.0) == pytest.approx(9.0)
    assert reachable_energy_kwh(curve, 9.0, 7200.0) == pytest.approx(10.0)


def test_backward_recursion_degenerates_to_linear_gap_capacity() -> None:
    required = minimum_departure_energies_kwh(
        constant_curve(),
        drive_energies_kwh=(50.0, 50.0),
        gap_seconds=(3600.0,),
    )
    assert required == pytest.approx((78.0, 50.0))
    packed = pack_trip_chain(constant_curve(), (50.0, 50.0), (3600.0,))
    assert packed[0].return_energy_kwh == pytest.approx(28.0)
    assert packed[0].charge_energy_kwh == pytest.approx(22.0)
    assert packed[0].charge_duration_seconds == pytest.approx(3600.0)


def test_backward_recursion_matches_dense_initial_energy_feasibility_scan() -> None:
    curve = stress_curve()
    drives = (3.0, 4.0, 3.0)
    gaps = (1800.0, 3600.0)
    exact = minimum_departure_energies_kwh(curve, drives, gaps)[0]

    dense_best = None
    step = 0.001
    candidate = drives[0]
    while candidate <= curve.capacity_kwh + 1e-12:
        battery = candidate
        feasible = True
        for index, drive in enumerate(drives):
            battery -= drive
            if battery < -1e-12:
                feasible = False
                break
            if index < len(gaps):
                battery = reachable_energy_kwh(curve, max(0.0, battery), gaps[index])
        if feasible:
            dense_best = candidate
            break
        candidate += step
    assert dense_best is not None
    assert exact <= dense_best + step
    assert exact >= dense_best - step


def test_infeasible_chain_is_not_repaired_by_exceeding_capacity() -> None:
    with pytest.raises(ChargingCurveError, match="exceeds battery capacity"):
        minimum_departure_energies_kwh(
            stress_curve(),
            drive_energies_kwh=(8.0, 8.0),
            gap_seconds=(0.0,),
        )
