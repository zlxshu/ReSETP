"""Isolated fixed-route nonlinear-charging prototype.

This module is deliberately independent of the formal ReSETP solver.  It has
no project-model defaults: every route, charging curve, signal profile,
candidate action, objective coefficient, and numerical tolerance is supplied
explicitly by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product
from math import isfinite
from typing import Iterable, Sequence


class PrototypeContractError(ValueError):
    """Raised when an isolated micro-case violates its explicit contract."""


@dataclass(frozen=True)
class PiecewiseLinearCurve:
    """Energy breakpoints and cumulative charging seconds from empty."""

    energy_kwh: tuple[float, ...]
    cumulative_seconds: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.energy_kwh) != len(self.cumulative_seconds) or len(self.energy_kwh) < 2:
            raise PrototypeContractError("curve arrays must have equal length >= 2")
        if self.energy_kwh[0] != 0.0 or self.cumulative_seconds[0] != 0.0:
            raise PrototypeContractError("curve must start at (0 kWh, 0 s)")
        if any(not isfinite(value) for value in (*self.energy_kwh, *self.cumulative_seconds)):
            raise PrototypeContractError("curve values must be finite")
        if any(
            right <= left
            for left, right in zip(
                self.energy_kwh[:-1], self.energy_kwh[1:], strict=True
            )
        ):
            raise PrototypeContractError("energy breakpoints must increase")
        if any(
            right <= left
            for left, right in zip(
                self.cumulative_seconds[:-1],
                self.cumulative_seconds[1:],
                strict=True,
            )
        ):
            raise PrototypeContractError("cumulative charging seconds must increase")
        if any(power <= 0.0 for power in self.segment_power_kw):
            raise PrototypeContractError("all segment powers must be positive")

    @property
    def capacity_kwh(self) -> float:
        return self.energy_kwh[-1]

    @property
    def segment_power_kw(self) -> tuple[float, ...]:
        return tuple(
            3600.0 * (right_e - left_e) / (right_t - left_t)
            for left_e, right_e, left_t, right_t in zip(
                self.energy_kwh[:-1],
                self.energy_kwh[1:],
                self.cumulative_seconds[:-1],
                self.cumulative_seconds[1:],
                strict=True,
            )
        )

    def cumulative_time(self, energy_kwh: float) -> float:
        energy = float(energy_kwh)
        if not isfinite(energy) or not 0.0 <= energy <= self.capacity_kwh:
            raise PrototypeContractError("energy outside charging curve")
        for index, right in enumerate(self.energy_kwh[1:]):
            if energy <= right:
                return self.cumulative_seconds[index] + 3600.0 * (
                    energy - self.energy_kwh[index]
                ) / self.segment_power_kw[index]
        return self.cumulative_seconds[-1]

    def duration(self, start_kwh: float, end_kwh: float) -> float:
        if not 0.0 <= start_kwh <= end_kwh <= self.capacity_kwh:
            raise PrototypeContractError("require 0 <= start <= end <= capacity")
        return self.cumulative_time(end_kwh) - self.cumulative_time(start_kwh)

    def phases(
        self, start_kwh: float, end_kwh: float
    ) -> tuple[tuple[float, float, float], ...]:
        """Return relative (start_s, finish_s, power_kW) charge phases."""

        if end_kwh == start_kwh:
            return ()
        origin = self.cumulative_time(start_kwh)
        phases: list[tuple[float, float, float]] = []
        for index, (left, right) in enumerate(
            zip(self.energy_kwh[:-1], self.energy_kwh[1:], strict=True)
        ):
            phase_left = max(left, start_kwh)
            phase_right = min(right, end_kwh)
            if phase_right <= phase_left:
                continue
            phases.append(
                (
                    self.cumulative_time(phase_left) - origin,
                    self.cumulative_time(phase_right) - origin,
                    self.segment_power_kw[index],
                )
            )
        return tuple(phases)


@dataclass(frozen=True)
class TimeSignals:
    boundaries_seconds: tuple[float, ...]
    price_per_kwh: tuple[float, ...]
    carbon_per_kwh: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.boundaries_seconds) < 2:
            raise PrototypeContractError("at least one signal slot is required")
        slot_count = len(self.boundaries_seconds) - 1
        if len(self.price_per_kwh) != slot_count or len(self.carbon_per_kwh) != slot_count:
            raise PrototypeContractError("signal lengths must match slot count")
        if any(not isfinite(value) for value in self.boundaries_seconds):
            raise PrototypeContractError("signal boundaries must be finite")
        if any(
            right <= left
            for left, right in zip(
                self.boundaries_seconds[:-1],
                self.boundaries_seconds[1:],
                strict=True,
            )
        ):
            raise PrototypeContractError("signal boundaries must increase")
        if any(
            not isfinite(value) or value < 0.0
            for value in (*self.price_per_kwh, *self.carbon_per_kwh)
        ):
            raise PrototypeContractError("signals must be finite and nonnegative")


@dataclass(frozen=True)
class ObjectiveCoefficients:
    price: float
    carbon: float

    def __post_init__(self) -> None:
        if not isfinite(self.price) or not isfinite(self.carbon):
            raise PrototypeContractError("objective coefficients must be finite")
        if self.price < 0.0 or self.carbon < 0.0:
            raise PrototypeContractError("objective coefficients must be nonnegative")


@dataclass(frozen=True)
class ChargeAction:
    target_soc_kwh: float
    wait_seconds: float

    def __post_init__(self) -> None:
        if not isfinite(self.target_soc_kwh) or not isfinite(self.wait_seconds):
            raise PrototypeContractError("charge action values must be finite")
        if self.wait_seconds < 0.0:
            raise PrototypeContractError("charge wait must be nonnegative")


@dataclass(frozen=True)
class ChargeOpportunity:
    latest_finish_seconds: float
    actions: tuple[ChargeAction, ...]

    def __post_init__(self) -> None:
        if not isfinite(self.latest_finish_seconds):
            raise PrototypeContractError("charge deadline must be finite")
        if not self.actions:
            raise PrototypeContractError("charge opportunity needs explicit actions")


@dataclass(frozen=True)
class RouteLeg:
    name: str
    travel_seconds: float
    drive_energy_kwh: float
    service_window: tuple[float, float]
    service_seconds: float
    charge_after_service: ChargeOpportunity | None

    def __post_init__(self) -> None:
        values = (
            self.travel_seconds,
            self.drive_energy_kwh,
            *self.service_window,
            self.service_seconds,
        )
        if any(not isfinite(value) for value in values):
            raise PrototypeContractError("route-leg values must be finite")
        if self.travel_seconds < 0.0 or self.drive_energy_kwh < 0.0 or self.service_seconds < 0.0:
            raise PrototypeContractError("time and energy values must be nonnegative")
        if self.service_window[1] < self.service_window[0]:
            raise PrototypeContractError("service window is reversed")


@dataclass(frozen=True)
class FixedRouteCase:
    case_id: str
    initial_time_seconds: float
    initial_soc_kwh: float
    terminal_min_soc_kwh: float
    curve: PiecewiseLinearCurve
    signals: TimeSignals
    objective: ObjectiveCoefficients
    legs: tuple[RouteLeg, ...]
    comparison_tolerance: float

    def __post_init__(self) -> None:
        if not self.legs:
            raise PrototypeContractError("fixed route must contain at least one leg")
        values = (
            self.initial_time_seconds,
            self.initial_soc_kwh,
            self.terminal_min_soc_kwh,
            self.comparison_tolerance,
        )
        if any(not isfinite(value) for value in values):
            raise PrototypeContractError("case values must be finite")
        if not 0.0 <= self.terminal_min_soc_kwh <= self.initial_soc_kwh <= self.curve.capacity_kwh:
            raise PrototypeContractError("initial/terminal SOC outside curve")
        if self.comparison_tolerance <= 0.0:
            raise PrototypeContractError("comparison tolerance must be positive")

    @property
    def opportunities(self) -> tuple[ChargeOpportunity, ...]:
        return tuple(
            leg.charge_after_service
            for leg in self.legs
            if leg.charge_after_service is not None
        )


@dataclass(frozen=True)
class ChargeTrace:
    opportunity_index: int
    start_time_seconds: float
    finish_time_seconds: float
    start_soc_kwh: float
    end_soc_kwh: float
    duration_seconds: float
    slot_energy_kwh: tuple[float, ...]
    price_cost: float
    carbon_amount: float


@dataclass(frozen=True)
class PlanResult:
    plan_index: int
    actions: tuple[ChargeAction, ...]
    feasible: bool
    failure_reason: str | None
    finish_time_seconds: float
    terminal_soc_kwh: float
    total_charge_kwh: float
    price_cost: float
    carbon_amount: float
    objective_value: float
    charge_traces: tuple[ChargeTrace, ...]


@dataclass(frozen=True)
class OracleResult:
    algorithm: str
    budget: int | None
    status: str
    candidates_generated: int
    complete_evaluations: int
    feasible_evaluations: int
    label_expansions: int
    dominance_prunes: int
    best: PlanResult | None


def _slot_energy(
    curve: PiecewiseLinearCurve,
    signals: TimeSignals,
    *,
    start_soc_kwh: float,
    end_soc_kwh: float,
    charging_start_seconds: float,
    tolerance: float,
) -> tuple[float, ...]:
    output = [0.0] * (len(signals.boundaries_seconds) - 1)
    for relative_start, relative_finish, power_kw in curve.phases(
        start_soc_kwh, end_soc_kwh
    ):
        absolute_start = charging_start_seconds + relative_start
        absolute_finish = charging_start_seconds + relative_finish
        for slot_index, (slot_start, slot_finish) in enumerate(
            zip(
                signals.boundaries_seconds[:-1],
                signals.boundaries_seconds[1:],
                strict=True,
            )
        ):
            overlap = max(
                0.0,
                min(slot_finish, absolute_finish) - max(slot_start, absolute_start),
            )
            output[slot_index] += power_kw * overlap / 3600.0
    expected = end_soc_kwh - start_soc_kwh
    if abs(sum(output) - expected) > tolerance * max(1.0, expected):
        raise PrototypeContractError("signal slots do not cover the complete charge")
    return tuple(output)


def _trace_charge(
    case: FixedRouteCase,
    *,
    opportunity_index: int,
    current_time_seconds: float,
    current_soc_kwh: float,
    action: ChargeAction,
    latest_finish_seconds: float,
) -> ChargeTrace | None:
    if action.target_soc_kwh < current_soc_kwh - case.comparison_tolerance:
        return None
    if action.target_soc_kwh > case.curve.capacity_kwh + case.comparison_tolerance:
        return None
    start_time = current_time_seconds + action.wait_seconds
    duration = case.curve.duration(current_soc_kwh, action.target_soc_kwh)
    finish_time = start_time + duration
    if finish_time > latest_finish_seconds + case.comparison_tolerance:
        return None
    slot_energy = _slot_energy(
        case.curve,
        case.signals,
        start_soc_kwh=current_soc_kwh,
        end_soc_kwh=action.target_soc_kwh,
        charging_start_seconds=start_time,
        tolerance=case.comparison_tolerance,
    )
    price = sum(
        energy * signal
        for energy, signal in zip(
            slot_energy, case.signals.price_per_kwh, strict=True
        )
    )
    carbon = sum(
        energy * signal
        for energy, signal in zip(
            slot_energy, case.signals.carbon_per_kwh, strict=True
        )
    )
    return ChargeTrace(
        opportunity_index=opportunity_index,
        start_time_seconds=start_time,
        finish_time_seconds=finish_time,
        start_soc_kwh=current_soc_kwh,
        end_soc_kwh=action.target_soc_kwh,
        duration_seconds=duration,
        slot_energy_kwh=slot_energy,
        price_cost=price,
        carbon_amount=carbon,
    )


def enumerate_action_plans(case: FixedRouteCase) -> Iterable[tuple[ChargeAction, ...]]:
    """Yield deterministic lexicographic plans supplied by the micro-case."""

    yield from product(*(opportunity.actions for opportunity in case.opportunities))


def replay_plan(
    case: FixedRouteCase,
    actions: Sequence[ChargeAction],
    *,
    plan_index: int,
) -> PlanResult:
    """Full independent replay used by the exhaustive micro-route oracle."""

    if len(actions) != len(case.opportunities):
        raise PrototypeContractError("action count does not match charge opportunities")
    time_seconds = case.initial_time_seconds
    soc_kwh = case.initial_soc_kwh
    opportunity_index = 0
    traces: list[ChargeTrace] = []
    failure_reason: str | None = None
    for leg in case.legs:
        time_seconds += leg.travel_seconds
        soc_kwh -= leg.drive_energy_kwh
        if soc_kwh < -case.comparison_tolerance:
            failure_reason = f"negative_soc_after_{leg.name}"
            break
        service_start = max(time_seconds, leg.service_window[0])
        if service_start > leg.service_window[1] + case.comparison_tolerance:
            failure_reason = f"late_service_at_{leg.name}"
            break
        time_seconds = service_start + leg.service_seconds
        if leg.charge_after_service is not None:
            action = actions[opportunity_index]
            trace = _trace_charge(
                case,
                opportunity_index=opportunity_index,
                current_time_seconds=time_seconds,
                current_soc_kwh=soc_kwh,
                action=action,
                latest_finish_seconds=leg.charge_after_service.latest_finish_seconds,
            )
            opportunity_index += 1
            if trace is None:
                failure_reason = f"invalid_charge_after_{leg.name}"
                break
            traces.append(trace)
            time_seconds = trace.finish_time_seconds
            soc_kwh = trace.end_soc_kwh
    if failure_reason is None and soc_kwh < case.terminal_min_soc_kwh - case.comparison_tolerance:
        failure_reason = "terminal_soc_below_minimum"
    price = sum(trace.price_cost for trace in traces)
    carbon = sum(trace.carbon_amount for trace in traces)
    total_charge = sum(trace.end_soc_kwh - trace.start_soc_kwh for trace in traces)
    objective = case.objective.price * price + case.objective.carbon * carbon
    return PlanResult(
        plan_index=plan_index,
        actions=tuple(actions),
        feasible=failure_reason is None,
        failure_reason=failure_reason,
        finish_time_seconds=time_seconds,
        terminal_soc_kwh=soc_kwh,
        total_charge_kwh=total_charge,
        price_cost=price,
        carbon_amount=carbon,
        objective_value=objective,
        charge_traces=tuple(traces),
    )


def _better(left: PlanResult, right: PlanResult | None, tolerance: float) -> bool:
    if right is None:
        return True
    if left.objective_value < right.objective_value - tolerance:
        return True
    if abs(left.objective_value - right.objective_value) <= tolerance:
        return left.plan_index < right.plan_index
    return False


def exhaustive_oracle(case: FixedRouteCase, *, budget: int | None) -> OracleResult:
    """Hand-auditable Cartesian-product oracle for tiny routes."""

    if budget is not None and budget < 0:
        raise PrototypeContractError("budget must be nonnegative or None")
    best: PlanResult | None = None
    generated = complete = feasible = 0
    for plan_index, actions in enumerate(enumerate_action_plans(case)):
        if budget is not None and complete >= budget:
            break
        generated += 1
        result = replay_plan(case, actions, plan_index=plan_index)
        complete += 1
        if result.feasible:
            feasible += 1
            if _better(result, best, case.comparison_tolerance):
                best = result
    return OracleResult(
        algorithm="exhaustive",
        budget=budget,
        status="BUDGET_ZERO_NO_EVALUATION" if budget == 0 else ("FEASIBLE" if best else "NO_FEASIBLE_PLAN"),
        candidates_generated=generated,
        complete_evaluations=complete,
        feasible_evaluations=feasible,
        label_expansions=0,
        dominance_prunes=0,
        best=best,
    )


@dataclass(frozen=True)
class _Label:
    leg_index: int
    opportunity_index: int
    time_seconds: float
    soc_kwh: float
    price_cost: float
    carbon_amount: float
    actions: tuple[ChargeAction, ...]
    traces: tuple[ChargeTrace, ...]

    def objective(self, coefficients: ObjectiveCoefficients) -> float:
        return coefficients.price * self.price_cost + coefficients.carbon * self.carbon_amount


def _advance_leg_without_charge(
    case: FixedRouteCase, label: _Label, leg: RouteLeg
) -> tuple[_Label | None, str | None]:
    time_seconds = label.time_seconds + leg.travel_seconds
    soc_kwh = label.soc_kwh - leg.drive_energy_kwh
    if soc_kwh < -case.comparison_tolerance:
        return None, f"negative_soc_after_{leg.name}"
    service_start = max(time_seconds, leg.service_window[0])
    if service_start > leg.service_window[1] + case.comparison_tolerance:
        return None, f"late_service_at_{leg.name}"
    return (
        replace(
            label,
            leg_index=label.leg_index + 1,
            time_seconds=service_start + leg.service_seconds,
            soc_kwh=soc_kwh,
        ),
        None,
    )


def _extend_charge(
    case: FixedRouteCase,
    label: _Label,
    opportunity: ChargeOpportunity,
    action: ChargeAction,
) -> _Label | None:
    trace = _trace_charge(
        case,
        opportunity_index=label.opportunity_index,
        current_time_seconds=label.time_seconds,
        current_soc_kwh=label.soc_kwh,
        action=action,
        latest_finish_seconds=opportunity.latest_finish_seconds,
    )
    if trace is None:
        return None
    return replace(
        label,
        opportunity_index=label.opportunity_index + 1,
        time_seconds=trace.finish_time_seconds,
        soc_kwh=trace.end_soc_kwh,
        price_cost=label.price_cost + trace.price_cost,
        carbon_amount=label.carbon_amount + trace.carbon_amount,
        actions=(*label.actions, action),
        traces=(*label.traces, trace),
    )


def _dominates(case: FixedRouteCase, left: _Label, right: _Label) -> bool:
    tolerance = case.comparison_tolerance
    same_stage = (
        left.leg_index == right.leg_index
        and left.opportunity_index == right.opportunity_index
    )
    weak = (
        left.time_seconds <= right.time_seconds + tolerance
        and left.soc_kwh >= right.soc_kwh - tolerance
        and left.objective(case.objective) <= right.objective(case.objective) + tolerance
    )
    strict = (
        left.time_seconds < right.time_seconds - tolerance
        or left.soc_kwh > right.soc_kwh + tolerance
        or left.objective(case.objective) < right.objective(case.objective) - tolerance
    )
    return same_stage and weak and strict


def label_oracle(
    case: FixedRouteCase,
    *,
    budget: int | None,
    dominance: bool,
) -> OracleResult:
    """Forward fixed-route label enumeration with optional safe dominance.

    For finite budgets dominance is intentionally disabled by contract so the
    same deterministic complete-plan prefix can be compared with exhaustive
    enumeration.  Unlimited runs may enable dominance as a separate activity
    test.
    """

    if budget is not None and budget < 0:
        raise PrototypeContractError("budget must be nonnegative or None")
    if budget is not None and dominance:
        raise PrototypeContractError("finite-budget prefix comparison forbids dominance")
    if budget == 0:
        return OracleResult(
            algorithm="label",
            budget=0,
            status="BUDGET_ZERO_NO_EVALUATION",
            candidates_generated=0,
            complete_evaluations=0,
            feasible_evaluations=0,
            label_expansions=0,
            dominance_prunes=0,
            best=None,
        )

    labels = [
        _Label(
            leg_index=0,
            opportunity_index=0,
            time_seconds=case.initial_time_seconds,
            soc_kwh=case.initial_soc_kwh,
            price_cost=0.0,
            carbon_amount=0.0,
            actions=(),
            traces=(),
        )
    ]
    expansions = prunes = 0
    for leg in case.legs:
        after_leg: list[_Label] = []
        for label in labels:
            advanced, _ = _advance_leg_without_charge(case, label, leg)
            expansions += 1
            if advanced is None:
                continue
            if leg.charge_after_service is None:
                after_leg.append(advanced)
                continue
            for action in leg.charge_after_service.actions:
                expanded = _extend_charge(case, advanced, leg.charge_after_service, action)
                expansions += 1
                if expanded is None:
                    continue
                if dominance:
                    if any(_dominates(case, incumbent, expanded) for incumbent in after_leg):
                        prunes += 1
                        continue
                    retained: list[_Label] = []
                    for incumbent in after_leg:
                        if _dominates(case, expanded, incumbent):
                            prunes += 1
                        else:
                            retained.append(incumbent)
                    after_leg = retained
                after_leg.append(expanded)
        labels = after_leg

    indexed: list[tuple[int, _Label]] = []
    plan_to_index = {
        tuple(plan): index for index, plan in enumerate(enumerate_action_plans(case))
    }
    for label in labels:
        indexed.append((plan_to_index[label.actions], label))
    indexed.sort(key=lambda item: item[0])

    best: PlanResult | None = None
    complete = feasible = generated = 0
    for plan_index, label in indexed:
        if budget is not None and complete >= budget:
            break
        generated += 1
        complete += 1
        failure = None
        if label.soc_kwh < case.terminal_min_soc_kwh - case.comparison_tolerance:
            failure = "terminal_soc_below_minimum"
        result = PlanResult(
            plan_index=plan_index,
            actions=label.actions,
            feasible=failure is None,
            failure_reason=failure,
            finish_time_seconds=label.time_seconds,
            terminal_soc_kwh=label.soc_kwh,
            total_charge_kwh=sum(
                trace.end_soc_kwh - trace.start_soc_kwh for trace in label.traces
            ),
            price_cost=label.price_cost,
            carbon_amount=label.carbon_amount,
            objective_value=label.objective(case.objective),
            charge_traces=label.traces,
        )
        if result.feasible:
            feasible += 1
            if _better(result, best, case.comparison_tolerance):
                best = result
    return OracleResult(
        algorithm="label",
        budget=budget,
        status="FEASIBLE" if best else "NO_FEASIBLE_PLAN",
        candidates_generated=generated,
        complete_evaluations=complete,
        feasible_evaluations=feasible,
        label_expansions=expansions,
        dominance_prunes=prunes,
        best=best,
    )


def plan_fingerprint(result: PlanResult | None, *, digits: int) -> tuple | None:
    """Normalized full-state tuple used for pointwise oracle comparisons."""

    if result is None:
        return None
    def rounded(value: float) -> float:
        return round(value, digits)
    return (
        result.plan_index,
        tuple((rounded(action.target_soc_kwh), rounded(action.wait_seconds)) for action in result.actions),
        result.feasible,
        result.failure_reason,
        rounded(result.finish_time_seconds),
        rounded(result.terminal_soc_kwh),
        rounded(result.total_charge_kwh),
        rounded(result.price_cost),
        rounded(result.carbon_amount),
        rounded(result.objective_value),
        tuple(
            (
                trace.opportunity_index,
                rounded(trace.start_time_seconds),
                rounded(trace.finish_time_seconds),
                rounded(trace.start_soc_kwh),
                rounded(trace.end_soc_kwh),
                rounded(trace.duration_seconds),
                tuple(rounded(value) for value in trace.slot_energy_kwh),
                rounded(trace.price_cost),
                rounded(trace.carbon_amount),
            )
            for trace in result.charge_traces
        ),
    )
