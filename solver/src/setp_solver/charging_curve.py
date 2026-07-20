"""Single mathematical kernel for piecewise nonlinear EV charging.

The functions in this module are pure: they do not read instances, mutate
routes, or choose an experiment arm.  Search, accounting, validation, and
dynamic execution must build the same :class:`PiecewiseChargingCurve` and call
this module instead of reimplementing ``energy / power`` arithmetic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from typing import Iterable, Sequence


class ChargingCurveError(ValueError):
    """Raised when a charging curve or request violates the physical contract."""


@dataclass(frozen=True)
class ChargingCurveSpec:
    """Normalized SOC breakpoints and relative segment powers."""

    curve_id: str
    soc_breakpoints: tuple[float, ...]
    relative_powers: tuple[float, ...]

    def __post_init__(self) -> None:
        curve_id = str(self.curve_id).strip()
        soc = tuple(float(value) for value in self.soc_breakpoints)
        powers = tuple(float(value) for value in self.relative_powers)
        if not curve_id:
            raise ChargingCurveError("curve_id must be non-empty")
        if len(soc) != len(powers) + 1:
            raise ChargingCurveError("SOC breakpoints must match relative powers")
        if len(soc) < 2 or soc[0] != 0.0 or soc[-1] != 1.0:
            raise ChargingCurveError("SOC breakpoints must span exactly 0..1")
        if any(not isfinite(value) for value in (*soc, *powers)):
            raise ChargingCurveError("curve specification values must be finite")
        if any(right <= left for left, right in zip(soc, soc[1:])):
            raise ChargingCurveError("SOC breakpoints must be strictly increasing")
        if any(power <= 0.0 for power in powers):
            raise ChargingCurveError("relative powers must be positive")
        if any(
            right > left + 1e-12
            for left, right in zip(powers, powers[1:])
        ):
            raise ChargingCurveError("relative powers must be non-increasing")
        object.__setattr__(self, "curve_id", curve_id)
        object.__setattr__(self, "soc_breakpoints", soc)
        object.__setattr__(self, "relative_powers", powers)

    @property
    def parameter_sha256(self) -> str:
        payload = json.dumps(
            asdict(self),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(payload).hexdigest()

    def scale(
        self, *, capacity_kwh: float, reference_power_kw: float
    ) -> PiecewiseChargingCurve:
        return PiecewiseChargingCurve.from_spec(
            self,
            capacity_kwh=capacity_kwh,
            reference_power_kw=reference_power_kw,
        )


L100_CONTROL = ChargingCurveSpec("L100_control", (0.0, 1.0), (1.0,))
NL90_MILD = ChargingCurveSpec("NL90_mild", (0.0, 0.9, 1.0), (1.0, 0.5))
NL80_STRESS = ChargingCurveSpec(
    "NL80_stress",
    (0.0, 0.8, 0.9, 1.0),
    (1.0, 0.5, 0.25),
)

CURVE_SPECS: dict[str, ChargingCurveSpec] = {
    spec.curve_id: spec for spec in (L100_CONTROL, NL90_MILD, NL80_STRESS)
}


def spec_from_parameters(parameters: object) -> ChargingCurveSpec:
    """Read one explicit normalized curve from shared parameters.

    There is deliberately no implicit linear fallback.  Any code creating new
    evidence must carry all three curve fields, including the L100 control.
    """

    names = (
        "charging_curve_id",
        "charging_soc_breakpoints",
        "charging_relative_powers",
    )
    if isinstance(parameters, Mapping):
        missing = [name for name in names if name not in parameters]
        if missing:
            raise ChargingCurveError(
                "charging parameters are missing explicit fields: "
                + ", ".join(missing)
            )
        curve_id = parameters[names[0]]
        soc = parameters[names[1]]
        powers = parameters[names[2]]
    else:
        missing = [name for name in names if not hasattr(parameters, name)]
        if missing:
            raise ChargingCurveError(
                "charging parameters are missing explicit fields: "
                + ", ".join(missing)
            )
        curve_id = getattr(parameters, names[0])
        soc = getattr(parameters, names[1])
        powers = getattr(parameters, names[2])
    if isinstance(soc, (str, bytes)) or isinstance(powers, (str, bytes)):
        raise ChargingCurveError("charging curve arrays must be numeric sequences")
    spec = ChargingCurveSpec(
        str(curve_id),
        tuple(float(value) for value in soc),  # type: ignore[arg-type]
        tuple(float(value) for value in powers),  # type: ignore[arg-type]
    )
    registered = CURVE_SPECS.get(spec.curve_id)
    if registered is not None and spec.parameter_sha256 != registered.parameter_sha256:
        raise ChargingCurveError(
            f"registered curve {spec.curve_id} disagrees with its frozen parameters"
        )
    return spec


def curve_from_parameters(
    parameters: object,
    *,
    capacity_kwh: float,
    reference_power_kw: float,
) -> PiecewiseChargingCurve:
    """Scale the explicit curve carried by the shared parameter object."""

    return spec_from_parameters(parameters).scale(
        capacity_kwh=capacity_kwh,
        reference_power_kw=reference_power_kw,
    )


@dataclass(frozen=True)
class ChargePhase:
    relative_start_seconds: float
    relative_end_seconds: float
    power_kw: float

    @property
    def energy_kwh(self) -> float:
        return (
            self.power_kw
            * (self.relative_end_seconds - self.relative_start_seconds)
            / 3600.0
        )


@dataclass(frozen=True)
class PiecewiseChargingCurve:
    """A scaled charging curve expressed in energy and cumulative time."""

    curve_id: str
    parameter_sha256: str
    energy_breakpoints_kwh: tuple[float, ...]
    cumulative_seconds: tuple[float, ...]

    def __post_init__(self) -> None:
        energies = tuple(float(value) for value in self.energy_breakpoints_kwh)
        times = tuple(float(value) for value in self.cumulative_seconds)
        if len(energies) != len(times) or len(energies) < 2:
            raise ChargingCurveError("curve requires matching breakpoint arrays")
        if any(not isfinite(value) for value in (*energies, *times)):
            raise ChargingCurveError("curve values must be finite")
        if energies[0] != 0.0 or times[0] != 0.0:
            raise ChargingCurveError("curve must start at zero energy and time")
        if any(
            right <= left
            for left, right in zip(energies, energies[1:])
        ):
            raise ChargingCurveError("energy breakpoints must be strictly increasing")
        if any(
            right <= left for left, right in zip(times, times[1:])
        ):
            raise ChargingCurveError("cumulative times must be strictly increasing")
        powers = tuple(
            3600.0 * (energy_right - energy_left) / (time_right - time_left)
            for energy_left, energy_right, time_left, time_right in zip(
                energies[:-1],
                energies[1:],
                times[:-1],
                times[1:],
                strict=True,
            )
        )
        if any(power <= 0.0 or not isfinite(power) for power in powers):
            raise ChargingCurveError("segment powers must be finite and positive")
        if any(
            right > left + 1e-12
            for left, right in zip(powers, powers[1:])
        ):
            raise ChargingCurveError("segment powers must be non-increasing")
        object.__setattr__(self, "energy_breakpoints_kwh", energies)
        object.__setattr__(self, "cumulative_seconds", times)

    @classmethod
    def from_spec(
        cls,
        spec: ChargingCurveSpec,
        *,
        capacity_kwh: float,
        reference_power_kw: float,
    ) -> PiecewiseChargingCurve:
        capacity = float(capacity_kwh)
        power = float(reference_power_kw)
        if not isfinite(capacity) or capacity <= 0.0:
            raise ChargingCurveError("capacity must be finite and positive")
        if not isfinite(power) or power <= 0.0:
            raise ChargingCurveError("reference power must be finite and positive")
        energies = tuple(value * capacity for value in spec.soc_breakpoints)
        times = [0.0]
        for left, right, factor in zip(
            energies[:-1],
            energies[1:],
            spec.relative_powers,
            strict=True,
        ):
            times.append(times[-1] + 3600.0 * (right - left) / (power * factor))
        return cls(
            curve_id=spec.curve_id,
            parameter_sha256=spec.parameter_sha256,
            energy_breakpoints_kwh=energies,
            cumulative_seconds=tuple(times),
        )

    @property
    def capacity_kwh(self) -> float:
        return self.energy_breakpoints_kwh[-1]

    @property
    def physical_parameter_sha256(self) -> str:
        """Hash the normalized curve together with its physical scaling."""

        payload = json.dumps(
            {
                "curve_parameter_sha256": self.parameter_sha256,
                "energy_breakpoints_kwh": self.energy_breakpoints_kwh,
                "cumulative_seconds": self.cumulative_seconds,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(payload).hexdigest()

    @property
    def segment_powers_kw(self) -> tuple[float, ...]:
        return tuple(
            3600.0 * (energy_right - energy_left) / (time_right - time_left)
            for energy_left, energy_right, time_left, time_right in zip(
                self.energy_breakpoints_kwh[:-1],
                self.energy_breakpoints_kwh[1:],
                self.cumulative_seconds[:-1],
                self.cumulative_seconds[1:],
                strict=True,
            )
        )

    def cumulative_time_seconds(self, energy_kwh: float) -> float:
        energy = float(energy_kwh)
        if not isfinite(energy) or not 0.0 <= energy <= self.capacity_kwh:
            raise ChargingCurveError("energy lies outside the charging curve")
        for index, right in enumerate(self.energy_breakpoints_kwh[1:]):
            if energy <= right:
                left = self.energy_breakpoints_kwh[index]
                return (
                    self.cumulative_seconds[index]
                    + 3600.0 * (energy - left) / self.segment_powers_kw[index]
                )
        return self.cumulative_seconds[-1]

    def inverse_cumulative_time_seconds(self, cumulative_seconds: float) -> float:
        value = float(cumulative_seconds)
        if (
            not isfinite(value)
            or value < 0.0
            or value > self.cumulative_seconds[-1]
        ):
            raise ChargingCurveError(
                "cumulative time lies outside the charging curve"
            )
        for index, right in enumerate(self.cumulative_seconds[1:]):
            if value <= right:
                left_time = self.cumulative_seconds[index]
                left_energy = self.energy_breakpoints_kwh[index]
                return (
                    left_energy
                    + (value - left_time)
                    * self.segment_powers_kw[index]
                    / 3600.0
                )
        return self.capacity_kwh

    def duration_seconds(
        self, start_energy_kwh: float, end_energy_kwh: float
    ) -> float:
        _validate_energy_interval(self, start_energy_kwh, end_energy_kwh)
        return self.cumulative_time_seconds(
            end_energy_kwh
        ) - self.cumulative_time_seconds(start_energy_kwh)

    def reachable_energy_kwh(
        self, start_energy_kwh: float, available_seconds: float
    ) -> float:
        gap = _nonnegative_finite(
            available_seconds, "available charging time"
        )
        origin = self.cumulative_time_seconds(float(start_energy_kwh))
        return self.inverse_cumulative_time_seconds(
            min(self.cumulative_seconds[-1], origin + gap)
        )

    def minimum_energy_before_gap_kwh(
        self, target_energy_kwh: float, available_seconds: float
    ) -> float:
        gap = _nonnegative_finite(
            available_seconds, "available charging time"
        )
        target_time = self.cumulative_time_seconds(float(target_energy_kwh))
        return self.inverse_cumulative_time_seconds(max(0.0, target_time - gap))

    def phases(
        self, start_energy_kwh: float, end_energy_kwh: float
    ) -> tuple[ChargePhase, ...]:
        _validate_energy_interval(self, start_energy_kwh, end_energy_kwh)
        origin = self.cumulative_time_seconds(start_energy_kwh)
        phases: list[ChargePhase] = []
        for index, (left, right) in enumerate(
            zip(
                self.energy_breakpoints_kwh,
                self.energy_breakpoints_kwh[1:],
            )
        ):
            phase_left = max(float(start_energy_kwh), left)
            phase_right = min(float(end_energy_kwh), right)
            if phase_right <= phase_left:
                continue
            phases.append(
                ChargePhase(
                    self.cumulative_time_seconds(phase_left) - origin,
                    self.cumulative_time_seconds(phase_right) - origin,
                    self.segment_powers_kw[index],
                )
            )
        if not phases:
            raise ChargingCurveError(
                "positive charging interval produced no phases"
            )
        return tuple(phases)


@dataclass(frozen=True)
class PackedTrip:
    trip_index: int
    departure_energy_kwh: float
    drive_energy_kwh: float
    return_energy_kwh: float
    charge_energy_kwh: float
    charge_duration_seconds: float


def minimum_departure_energies_kwh(
    curve: PiecewiseChargingCurve,
    drive_energies_kwh: Sequence[float],
    gap_seconds: Sequence[float],
) -> tuple[float, ...]:
    drives = tuple(float(value) for value in drive_energies_kwh)
    gaps = tuple(float(value) for value in gap_seconds)
    if not drives or len(gaps) != len(drives) - 1:
        raise ChargingCurveError(
            "a trip chain requires m drives and m-1 charging gaps"
        )
    if any(not isfinite(value) or value < 0.0 for value in drives):
        raise ChargingCurveError("drive energies must be finite and non-negative")
    if any(not isfinite(value) or value < 0.0 for value in gaps):
        raise ChargingCurveError("charging gaps must be finite and non-negative")
    required = [0.0] * len(drives)
    required[-1] = drives[-1]
    for index in range(len(drives) - 2, -1, -1):
        residual = curve.minimum_energy_before_gap_kwh(
            required[index + 1], gaps[index]
        )
        required[index] = drives[index] + residual
        if required[index] > curve.capacity_kwh + 1e-9:
            raise ChargingCurveError(
                "nonlinear trip chain exceeds battery capacity"
            )
    return tuple(required)


def pack_trip_chain(
    curve: PiecewiseChargingCurve,
    drive_energies_kwh: Sequence[float],
    gap_seconds: Sequence[float],
) -> tuple[PackedTrip, ...]:
    required = minimum_departure_energies_kwh(
        curve, drive_energies_kwh, gap_seconds
    )
    drives = tuple(float(value) for value in drive_energies_kwh)
    rows: list[PackedTrip] = []
    for index, (departure, drive) in enumerate(
        zip(required, drives, strict=True)
    ):
        returned = departure - drive
        charge = 0.0
        duration = 0.0
        if index < len(drives) - 1:
            charge = max(0.0, required[index + 1] - returned)
            if charge > 0.0:
                duration = curve.duration_seconds(
                    returned, required[index + 1]
                )
                if duration > float(gap_seconds[index]) + 1e-8:
                    raise ChargingCurveError(
                        "backward packing produced an infeasible gap"
                    )
        rows.append(
            PackedTrip(
                index + 1,
                departure,
                drive,
                returned,
                charge,
                duration,
            )
        )
    return tuple(rows)


def slot_energy_kwh(
    curve: PiecewiseChargingCurve,
    *,
    start_energy_kwh: float,
    end_energy_kwh: float,
    charging_start_seconds: float,
    slot_boundaries_seconds: Sequence[float],
) -> tuple[float, ...]:
    start_time = float(charging_start_seconds)
    if not isfinite(start_time):
        raise ChargingCurveError("charging start must be finite")
    _validate_slot_boundaries(slot_boundaries_seconds)
    output: list[float] = []
    for slot_start, slot_end in zip(
        slot_boundaries_seconds, slot_boundaries_seconds[1:]
    ):
        energy = 0.0
        for phase in curve.phases(start_energy_kwh, end_energy_kwh):
            absolute_start = start_time + phase.relative_start_seconds
            absolute_end = start_time + phase.relative_end_seconds
            overlap = max(
                0.0,
                min(float(slot_end), absolute_end)
                - max(float(slot_start), absolute_start),
            )
            energy += phase.power_kw * overlap / 3600.0
        output.append(energy)
    expected = float(end_energy_kwh) - float(start_energy_kwh)
    if not _close(sum(output), expected, tolerance=1e-9):
        raise ChargingCurveError(
            "time slots do not fully cover the charging action"
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
    _validate_slot_boundaries(slot_boundaries_seconds)
    duration = curve.duration_seconds(start_energy_kwh, end_energy_kwh)
    earliest = float(earliest_start_seconds)
    latest_start = float(latest_finish_seconds) - duration
    if not all(isfinite(value) for value in (earliest, latest_start)):
        raise ChargingCurveError("charging window bounds must be finite")
    if latest_start < earliest - 1e-9:
        return ()
    phase_boundaries = {0.0, duration}
    for phase in curve.phases(start_energy_kwh, end_energy_kwh):
        phase_boundaries.add(phase.relative_start_seconds)
        phase_boundaries.add(phase.relative_end_seconds)
    candidates = {earliest, latest_start}
    for grid_boundary in slot_boundaries_seconds:
        for phase_boundary in phase_boundaries:
            candidate = float(grid_boundary) - phase_boundary
            if earliest - 1e-9 <= candidate <= latest_start + 1e-9:
                candidates.add(min(max(candidate, earliest), latest_start))
    return tuple(sorted(candidates))


def weighted_slot_total(
    energy_kwh: Sequence[float], weights_per_kwh: Sequence[float]
) -> float:
    if len(energy_kwh) != len(weights_per_kwh):
        raise ChargingCurveError("slot energy and weights lengths differ")
    values = tuple(float(value) for value in (*energy_kwh, *weights_per_kwh))
    if any(not isfinite(value) for value in values):
        raise ChargingCurveError("slot energy and weights must be finite")
    return sum(
        float(energy) * float(weight)
        for energy, weight in zip(
            energy_kwh, weights_per_kwh, strict=True
        )
    )


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
        raise ChargingCurveError(
            "weight count differs from the time-slot count"
        )
    evaluated = []
    for start in starts:
        energy = slot_energy_kwh(
            curve,
            start_energy_kwh=start_energy_kwh,
            end_energy_kwh=end_energy_kwh,
            charging_start_seconds=start,
            slot_boundaries_seconds=slot_boundaries_seconds,
        )
        evaluated.append(
            (weighted_slot_total(energy, weights_per_kwh), start, energy)
        )
    objective, start, energy = min(
        evaluated, key=lambda row: (row[0], row[1])
    )
    return start, objective, energy


def half_hour_boundaries(*, days: int = 1) -> tuple[float, ...]:
    if int(days) != days or days <= 0:
        raise ChargingCurveError("days must be a positive integer")
    return tuple(float(index * 1800) for index in range(int(days) * 48 + 1))


def curve_from_id(
    curve_id: str, *, capacity_kwh: float, reference_power_kw: float
) -> PiecewiseChargingCurve:
    try:
        spec = CURVE_SPECS[str(curve_id)]
    except KeyError as exc:
        raise ChargingCurveError(f"unknown charging curve: {curve_id}") from exc
    return spec.scale(
        capacity_kwh=capacity_kwh,
        reference_power_kw=reference_power_kw,
    )


def scale_normalized_curve(
    *,
    curve_id: str,
    capacity_kwh: float,
    soc_breakpoints: Iterable[float],
    relative_powers: Iterable[float],
    reference_power_kw: float,
) -> PiecewiseChargingCurve:
    return ChargingCurveSpec(
        curve_id,
        tuple(float(value) for value in soc_breakpoints),
        tuple(float(value) for value in relative_powers),
    ).scale(
        capacity_kwh=capacity_kwh,
        reference_power_kw=reference_power_kw,
    )


def _validate_energy_interval(
    curve: PiecewiseChargingCurve,
    start_energy_kwh: float,
    end_energy_kwh: float,
) -> None:
    start = float(start_energy_kwh)
    end = float(end_energy_kwh)
    if not all(isfinite(value) for value in (start, end)):
        raise ChargingCurveError("charge energies must be finite")
    if not 0.0 <= start < end <= curve.capacity_kwh:
        raise ChargingCurveError("require 0 <= start < end <= capacity")


def _validate_slot_boundaries(
    slot_boundaries_seconds: Sequence[float],
) -> None:
    boundaries = tuple(float(value) for value in slot_boundaries_seconds)
    if len(boundaries) < 2:
        raise ChargingCurveError("at least one time slot is required")
    if any(not isfinite(value) for value in boundaries):
        raise ChargingCurveError("slot boundaries must be finite")
    if any(
        right <= left
        for left, right in zip(boundaries, boundaries[1:])
    ):
        raise ChargingCurveError("slot boundaries must be strictly increasing")


def _nonnegative_finite(value: float, label: str) -> float:
    number = float(value)
    if not isfinite(number) or number < 0.0:
        raise ChargingCurveError(f"{label} must be finite and non-negative")
    return number


def _close(left: float, right: float, *, tolerance: float) -> bool:
    return abs(left - right) <= tolerance * max(1.0, abs(left), abs(right))
