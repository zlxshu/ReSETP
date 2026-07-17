"""Pure nonlinear-charging replay primitives.

The module is deliberately isolated from the route-search implementation.  It
does not read experiment outputs and does not mutate routes.  Its only purpose
is to recompute charging duration, slot energy, and carbon/electricity totals
for a frozen charging action under a validated piecewise-linear time curve.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Sequence


class ChargingCurveError(ValueError):
    """Raised when a curve or replay request violates the mathematical contract."""


@dataclass(frozen=True)
class ChargePhase:
    relative_start_seconds: float
    relative_end_seconds: float
    power_kw: float

    @property
    def energy_kwh(self) -> float:
        return self.power_kw * (
            self.relative_end_seconds - self.relative_start_seconds
        ) / 3600.0


@dataclass(frozen=True)
class PiecewiseChargingCurve:
    """SOC-energy breakpoints and cumulative charging time.

    `energy_breakpoints_kwh[i]` and `cumulative_seconds[i]` describe the time
    required to charge from empty to that energy.  Each segment has constant
    power; powers must be positive and non-increasing as energy rises.
    """

    energy_breakpoints_kwh: tuple[float, ...]
    cumulative_seconds: tuple[float, ...]

    def __post_init__(self) -> None:
        energies = self.energy_breakpoints_kwh
        times = self.cumulative_seconds
        if len(energies) != len(times) or len(energies) < 2:
            raise ChargingCurveError("curve requires matching breakpoint arrays")
        if any(not isfinite(value) for value in (*energies, *times)):
            raise ChargingCurveError("curve values must be finite")
        if energies[0] != 0.0 or times[0] != 0.0:
            raise ChargingCurveError("curve must start at zero energy and time")
        if any(right <= left for left, right in zip(energies, energies[1:])):
            raise ChargingCurveError("energy breakpoints must be strictly increasing")
        if any(right <= left for left, right in zip(times, times[1:])):
            raise ChargingCurveError("cumulative times must be strictly increasing")
        powers = self.segment_powers_kw
        if any(power <= 0.0 or not isfinite(power) for power in powers):
            raise ChargingCurveError("segment powers must be finite and positive")
        tolerance = 1e-12
        if any(right > left + tolerance for left, right in zip(powers, powers[1:])):
            raise ChargingCurveError("segment powers must be non-increasing")

    @property
    def capacity_kwh(self) -> float:
        return self.energy_breakpoints_kwh[-1]

    @property
    def segment_powers_kw(self) -> tuple[float, ...]:
        return tuple(
            3600.0 * (energy_right - energy_left) / (time_right - time_left)
            for energy_left, energy_right, time_left, time_right in zip(
                self.energy_breakpoints_kwh,
                self.energy_breakpoints_kwh[1:],
                self.cumulative_seconds,
                self.cumulative_seconds[1:],
            )
        )

    def cumulative_time_seconds(self, energy_kwh: float) -> float:
        if not isfinite(energy_kwh) or not 0.0 <= energy_kwh <= self.capacity_kwh:
            raise ChargingCurveError("energy lies outside the charging curve")
        for index, (left, right) in enumerate(
            zip(self.energy_breakpoints_kwh, self.energy_breakpoints_kwh[1:])
        ):
            if energy_kwh <= right:
                return self.cumulative_seconds[index] + 3600.0 * (
                    energy_kwh - left
                ) / self.segment_powers_kw[index]
        return self.cumulative_seconds[-1]

    def duration_seconds(self, start_energy_kwh: float, end_energy_kwh: float) -> float:
        _validate_energy_interval(self, start_energy_kwh, end_energy_kwh)
        return self.cumulative_time_seconds(end_energy_kwh) - self.cumulative_time_seconds(
            start_energy_kwh
        )

    def phases(
        self, start_energy_kwh: float, end_energy_kwh: float
    ) -> tuple[ChargePhase, ...]:
        _validate_energy_interval(self, start_energy_kwh, end_energy_kwh)
        origin = self.cumulative_time_seconds(start_energy_kwh)
        phases: list[ChargePhase] = []
        for index, (left, right) in enumerate(
            zip(self.energy_breakpoints_kwh, self.energy_breakpoints_kwh[1:])
        ):
            phase_left = max(start_energy_kwh, left)
            phase_right = min(end_energy_kwh, right)
            if phase_right <= phase_left:
                continue
            relative_start = self.cumulative_time_seconds(phase_left) - origin
            relative_end = self.cumulative_time_seconds(phase_right) - origin
            phases.append(
                ChargePhase(relative_start, relative_end, self.segment_powers_kw[index])
            )
        if not phases:
            raise ChargingCurveError("positive charging interval produced no phases")
        return tuple(phases)


def _validate_energy_interval(
    curve: PiecewiseChargingCurve, start_energy_kwh: float, end_energy_kwh: float
) -> None:
    if not all(isfinite(value) for value in (start_energy_kwh, end_energy_kwh)):
        raise ChargingCurveError("charge energies must be finite")
    if not 0.0 <= start_energy_kwh < end_energy_kwh <= curve.capacity_kwh:
        raise ChargingCurveError("require 0 <= start < end <= capacity")


def _validate_slot_boundaries(slot_boundaries_seconds: Sequence[float]) -> None:
    if len(slot_boundaries_seconds) < 2:
        raise ChargingCurveError("at least one time slot is required")
    if any(not isfinite(value) for value in slot_boundaries_seconds):
        raise ChargingCurveError("slot boundaries must be finite")
    if any(
        right <= left
        for left, right in zip(slot_boundaries_seconds, slot_boundaries_seconds[1:])
    ):
        raise ChargingCurveError("slot boundaries must be strictly increasing")


def slot_energy_kwh(
    curve: PiecewiseChargingCurve,
    *,
    start_energy_kwh: float,
    end_energy_kwh: float,
    charging_start_seconds: float,
    slot_boundaries_seconds: Sequence[float],
) -> tuple[float, ...]:
    """Integrate piecewise charging power over external time slots exactly."""

    if not isfinite(charging_start_seconds):
        raise ChargingCurveError("charging start must be finite")
    _validate_slot_boundaries(slot_boundaries_seconds)
    phases = curve.phases(start_energy_kwh, end_energy_kwh)
    output: list[float] = []
    for slot_start, slot_end in zip(
        slot_boundaries_seconds, slot_boundaries_seconds[1:]
    ):
        energy = 0.0
        for phase in phases:
            absolute_start = charging_start_seconds + phase.relative_start_seconds
            absolute_end = charging_start_seconds + phase.relative_end_seconds
            overlap = max(0.0, min(slot_end, absolute_end) - max(slot_start, absolute_start))
            energy += phase.power_kw * overlap / 3600.0
        output.append(energy)
    expected = end_energy_kwh - start_energy_kwh
    if not _close(sum(output), expected, tolerance=1e-9):
        raise ChargingCurveError(
            "time slots do not fully cover the charging action or energy did not close"
        )
    return tuple(output)


def candidate_start_times(
    curve: PiecewiseChargingCurve,
    *,
    start_energy_kwh: float,
    end_energy_kwh: float,
    earliest_start_seconds: float,
    latest_finish_seconds: float,
    slot_boundaries_seconds: Sequence[float],
) -> tuple[float, ...]:
    """Enumerate all breakpoints of a stepwise price/carbon objective."""

    _validate_slot_boundaries(slot_boundaries_seconds)
    duration = curve.duration_seconds(start_energy_kwh, end_energy_kwh)
    latest_start = latest_finish_seconds - duration
    if not all(
        isfinite(value)
        for value in (earliest_start_seconds, latest_finish_seconds, latest_start)
    ):
        raise ChargingCurveError("charging window bounds must be finite")
    if latest_start < earliest_start_seconds - 1e-9:
        return ()
    phase_boundaries = {0.0, duration}
    for phase in curve.phases(start_energy_kwh, end_energy_kwh):
        phase_boundaries.add(phase.relative_start_seconds)
        phase_boundaries.add(phase.relative_end_seconds)
    candidates = {earliest_start_seconds, latest_start}
    for grid_boundary in slot_boundaries_seconds:
        for phase_boundary in phase_boundaries:
            candidate = grid_boundary - phase_boundary
            if earliest_start_seconds - 1e-9 <= candidate <= latest_start + 1e-9:
                candidates.add(min(max(candidate, earliest_start_seconds), latest_start))
    return tuple(sorted(candidates))


def weighted_slot_total(
    energy_kwh: Sequence[float], weights_per_kwh: Sequence[float]
) -> float:
    if len(energy_kwh) != len(weights_per_kwh):
        raise ChargingCurveError("slot energy and weight lengths differ")
    if any(not isfinite(value) for value in (*energy_kwh, *weights_per_kwh)):
        raise ChargingCurveError("slot energy and weights must be finite")
    return sum(energy * weight for energy, weight in zip(energy_kwh, weights_per_kwh, strict=True))


def best_start_by_weight(
    curve: PiecewiseChargingCurve,
    *,
    start_energy_kwh: float,
    end_energy_kwh: float,
    earliest_start_seconds: float,
    latest_finish_seconds: float,
    slot_boundaries_seconds: Sequence[float],
    weights_per_kwh: Sequence[float],
) -> tuple[float, float, tuple[float, ...]]:
    starts = candidate_start_times(
        curve,
        start_energy_kwh=start_energy_kwh,
        end_energy_kwh=end_energy_kwh,
        earliest_start_seconds=earliest_start_seconds,
        latest_finish_seconds=latest_finish_seconds,
        slot_boundaries_seconds=slot_boundaries_seconds,
    )
    if not starts:
        raise ChargingCurveError("charging window has no feasible start")
    if len(weights_per_kwh) != len(slot_boundaries_seconds) - 1:
        raise ChargingCurveError("weight count differs from the time-slot count")
    evaluated: list[tuple[float, float, tuple[float, ...]]] = []
    for start in starts:
        energy = slot_energy_kwh(
            curve,
            start_energy_kwh=start_energy_kwh,
            end_energy_kwh=end_energy_kwh,
            charging_start_seconds=start,
            slot_boundaries_seconds=slot_boundaries_seconds,
        )
        evaluated.append((weighted_slot_total(energy, weights_per_kwh), start, energy))
    objective, start, energy = min(evaluated, key=lambda row: (row[0], row[1]))
    return start, objective, energy


def _close(left: float, right: float, *, tolerance: float) -> bool:
    return abs(left - right) <= tolerance * max(1.0, abs(left), abs(right))


def half_hour_boundaries(*, days: int = 1) -> tuple[float, ...]:
    if days <= 0:
        raise ChargingCurveError("days must be positive")
    return tuple(float(index * 1800) for index in range(days * 48 + 1))


def scale_normalized_curve(
    *,
    capacity_kwh: float,
    soc_breakpoints: Iterable[float],
    relative_powers: Iterable[float],
    reference_power_kw: float,
) -> PiecewiseChargingCurve:
    """Build a clearly labelled shape-stress curve from normalized inputs."""

    soc = tuple(float(value) for value in soc_breakpoints)
    relative = tuple(float(value) for value in relative_powers)
    if not isfinite(capacity_kwh) or capacity_kwh <= 0.0:
        raise ChargingCurveError("capacity must be finite and positive")
    if not isfinite(reference_power_kw) or reference_power_kw <= 0.0:
        raise ChargingCurveError("reference power must be finite and positive")
    if len(soc) != len(relative) + 1 or soc[0] != 0.0 or soc[-1] != 1.0:
        raise ChargingCurveError("SOC breakpoints must span 0..1 and match powers")
    if any(right <= left for left, right in zip(soc, soc[1:])):
        raise ChargingCurveError("SOC breakpoints must be strictly increasing")
    energies = tuple(value * capacity_kwh for value in soc)
    times = [0.0]
    for left, right, factor in zip(energies, energies[1:], relative):
        if not isfinite(factor) or factor <= 0.0:
            raise ChargingCurveError("relative powers must be finite and positive")
        times.append(times[-1] + 3600.0 * (right - left) / (reference_power_kw * factor))
    return PiecewiseChargingCurve(energies, tuple(times))
