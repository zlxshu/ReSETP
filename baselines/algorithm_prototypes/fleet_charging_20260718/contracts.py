"""Model-neutral contracts and accounting for the EA-001 micro probes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ProbeCounters:
    """Counters that must never be merged into one ambiguous evaluation count."""

    complete_candidate_evaluations: int = 0
    screen_evaluations: int = 0
    route_oracle_calls: int = 0
    oracle_cache_hits: int = 0
    reference_evaluations: int = 0


class CompleteEvaluationBudget:
    """Pre-reserved complete-candidate budget with a hard pre-call stop."""

    def __init__(self, limit: int, counters: ProbeCounters):
        if limit < 0:
            raise ValueError("budget limit must be non-negative")
        self.limit = limit
        self.counters = counters

    @property
    def remaining(self) -> int:
        return self.limit - self.counters.complete_candidate_evaluations

    def reserve(self) -> bool:
        """Reserve one complete evaluation before candidate generation/scoring."""

        if self.remaining <= 0:
            return False
        self.counters.complete_candidate_evaluations += 1
        return True


@dataclass(frozen=True)
class FixedRouteChargingRequest:
    """A model-neutral fixed-route charging request.

    Values use abstract time and abstract energy units. No CNY objective,
    Chinese physical parameter, formal SOC curve, or cross-trip semantics is
    embedded here.
    """

    instance: dict[str, Any]
    route: tuple[int, ...]
    initial_energy: float
    request_id: str


@dataclass(frozen=True)
class ChargingOracleResult:
    objective: float
    stops: tuple[tuple[int, float | None], ...]
    backend: str
    feasible: bool


class ChargingOracle(Protocol):
    def solve(
        self,
        request: FixedRouteChargingRequest,
        counters: ProbeCounters,
    ) -> ChargingOracleResult:
        """Solve one request and update only oracle-specific counters."""


def _interpolate(xs: list[float], ys: list[float], x: float) -> float:
    if x < xs[0] or x > xs[-1]:
        raise ValueError(f"value {x} lies outside charging curve")
    if x == xs[-1]:
        return ys[-1]
    for idx in range(len(xs) - 1):
        if xs[idx] <= x <= xs[idx + 1]:
            width = xs[idx + 1] - xs[idx]
            if width == 0:
                raise ValueError("charging curve has duplicate energy breakpoints")
            ratio = (x - xs[idx]) / width
            return ys[idx] + ratio * (ys[idx + 1] - ys[idx])
    raise AssertionError("unreachable interpolation branch")


def cumulative_charge_time(
    breakpoint_energy: list[float],
    breakpoint_time: list[float],
    energy: float,
) -> float:
    """Return cumulative charging time at an abstract energy level."""

    if len(breakpoint_energy) != len(breakpoint_time) or len(breakpoint_energy) < 2:
        raise ValueError("charging curve must have matching breakpoint arrays")
    if any(b <= a for a, b in zip(breakpoint_energy, breakpoint_energy[1:])):
        raise ValueError("charging energy breakpoints must be strictly increasing")
    if any(b < a for a, b in zip(breakpoint_time, breakpoint_time[1:])):
        raise ValueError("cumulative charging time must be non-decreasing")
    return _interpolate(breakpoint_energy, breakpoint_time, energy)


@dataclass(frozen=True)
class ReplayResult:
    feasible: bool
    objective: float
    final_energy: float
    min_energy: float


def independently_replay_charging_result(
    request: FixedRouteChargingRequest,
    result: ChargingOracleResult,
    tolerance: float = 1e-9,
) -> ReplayResult:
    """Replay an oracle result without importing or calling its implementation."""

    instance = request.instance
    energy = request.initial_energy
    elapsed = 0.0
    min_energy = energy
    station_types = {row["node_id"]: row["cs_type"] for row in instance["css"]}
    curves = {
        row["cs_type"]: (row["charge"], row["time"])
        for row in instance["breakpoints_by_type"]
    }
    stops = result.stops
    if not stops or stops[0][0] != request.route[0] or stops[-1][0] != request.route[-1]:
        return ReplayResult(False, float("inf"), energy, min_energy)

    for idx, (node, charge_amount) in enumerate(stops):
        if charge_amount is not None:
            if node not in station_types or charge_amount < -tolerance:
                return ReplayResult(False, float("inf"), energy, min_energy)
            target = energy + charge_amount
            if target > instance["max_q"] + tolerance:
                return ReplayResult(False, float("inf"), energy, min_energy)
            curve_energy, curve_time = curves[station_types[node]]
            elapsed += cumulative_charge_time(curve_energy, curve_time, target)
            elapsed -= cumulative_charge_time(curve_energy, curve_time, energy)
            energy = target
        elapsed += instance.get("process_times", [0.0] * len(instance["time_matrix"]))[node]
        if idx + 1 == len(stops):
            continue
        nxt = stops[idx + 1][0]
        energy -= instance["energy_matrix"][node][nxt]
        elapsed += instance["time_matrix"][node][nxt]
        min_energy = min(min_energy, energy)
        if energy < -tolerance:
            return ReplayResult(False, float("inf"), energy, min_energy)

    feasible = elapsed <= instance.get("t_max", float("inf")) + tolerance
    objective = elapsed if feasible else float("inf")
    return ReplayResult(feasible, objective, energy, min_energy)
