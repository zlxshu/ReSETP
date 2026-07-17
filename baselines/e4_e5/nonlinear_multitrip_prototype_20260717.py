"""Pure prototype for exact nonlinear multi-trip battery packing.

This module is deliberately not imported by the frozen solver.  It validates
the backward recursion that will replace linear gap-capacity arithmetic after
E7 is closed and the shared kernel is released for modification.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

from baselines.e4_e5.nonlinear_charging_replay_20260717 import (
    ChargingCurveError,
    PiecewiseChargingCurve,
)


@dataclass(frozen=True)
class PackedTrip:
    trip_index: int
    departure_energy_kwh: float
    drive_energy_kwh: float
    return_energy_kwh: float
    charge_energy_kwh: float
    charge_duration_seconds: float


def inverse_cumulative_time_seconds(
    curve: PiecewiseChargingCurve, cumulative_seconds: float
) -> float:
    """Return xi^-1(t) exactly on the piecewise-linear curve."""

    value = float(cumulative_seconds)
    if not isfinite(value) or value < 0.0 or value > curve.cumulative_seconds[-1]:
        raise ChargingCurveError("cumulative time lies outside the charging curve")
    for index, right in enumerate(curve.cumulative_seconds[1:]):
        if value <= right:
            left_time = curve.cumulative_seconds[index]
            left_energy = curve.energy_breakpoints_kwh[index]
            return left_energy + (value - left_time) * curve.segment_powers_kw[index] / 3600.0
    return curve.capacity_kwh


def reachable_energy_kwh(
    curve: PiecewiseChargingCurve, start_energy_kwh: float, available_seconds: float
) -> float:
    """Maximum energy reachable after charging continuously for a fixed gap."""

    gap = float(available_seconds)
    if not isfinite(gap) or gap < 0.0:
        raise ChargingCurveError("available charging time must be finite and non-negative")
    origin = curve.cumulative_time_seconds(float(start_energy_kwh))
    finish = min(curve.cumulative_seconds[-1], origin + gap)
    return inverse_cumulative_time_seconds(curve, finish)


def minimum_energy_before_gap_kwh(
    curve: PiecewiseChargingCurve, target_energy_kwh: float, available_seconds: float
) -> float:
    """Least pre-gap energy from which the target is reachable within the gap."""

    target_time = curve.cumulative_time_seconds(float(target_energy_kwh))
    gap = float(available_seconds)
    if not isfinite(gap) or gap < 0.0:
        raise ChargingCurveError("available charging time must be finite and non-negative")
    return inverse_cumulative_time_seconds(curve, max(0.0, target_time - gap))


def minimum_departure_energies_kwh(
    curve: PiecewiseChargingCurve,
    drive_energies_kwh: Sequence[float],
    gap_seconds: Sequence[float],
) -> tuple[float, ...]:
    """Exact backward packing for one physical vehicle's ordered trip chain."""

    drives = tuple(float(value) for value in drive_energies_kwh)
    gaps = tuple(float(value) for value in gap_seconds)
    if not drives or len(gaps) != len(drives) - 1:
        raise ChargingCurveError("a trip chain requires m drives and m-1 charging gaps")
    if any(not isfinite(value) or value < 0.0 for value in drives):
        raise ChargingCurveError("drive energies must be finite and non-negative")
    if any(not isfinite(value) or value < 0.0 for value in gaps):
        raise ChargingCurveError("charging gaps must be finite and non-negative")
    required = [0.0] * len(drives)
    required[-1] = drives[-1]
    for index in range(len(drives) - 2, -1, -1):
        residual = minimum_energy_before_gap_kwh(
            curve, required[index + 1], gaps[index]
        )
        required[index] = drives[index] + residual
        if required[index] > curve.capacity_kwh + 1e-9:
            raise ChargingCurveError("nonlinear trip chain exceeds battery capacity")
    if any(value > curve.capacity_kwh + 1e-9 for value in required):
        raise ChargingCurveError("nonlinear trip chain exceeds battery capacity")
    return tuple(required)


def pack_trip_chain(
    curve: PiecewiseChargingCurve,
    drive_energies_kwh: Sequence[float],
    gap_seconds: Sequence[float],
) -> tuple[PackedTrip, ...]:
    """Materialize the minimum-energy chain and its exact gap charges."""

    required = minimum_departure_energies_kwh(curve, drive_energies_kwh, gap_seconds)
    drives = tuple(float(value) for value in drive_energies_kwh)
    rows: list[PackedTrip] = []
    for index, (departure, drive) in enumerate(zip(required, drives, strict=True)):
        returned = departure - drive
        charge = 0.0
        duration = 0.0
        if index < len(drives) - 1:
            charge = max(0.0, required[index + 1] - returned)
            if charge > 0.0:
                duration = curve.duration_seconds(returned, required[index + 1])
                if duration > float(gap_seconds[index]) + 1e-8:
                    raise ChargingCurveError("backward packing produced an infeasible gap")
        rows.append(PackedTrip(index + 1, departure, drive, returned, charge, duration))
    return tuple(rows)
