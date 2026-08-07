"""Full-model Duty evaluation and a truth-checked incremental cache.

v1 2026-08-07: preserve explicit physical-vehicle assignments, reuse the
frozen checker/cost/profit semantics, and keep a full recomputation sentinel
enabled while the incremental path is under construction.

v2 2026-08-07: remove the candidate-dependent all-CV fleet relaxation, make
the carbon and depot-window semantics explicit inputs, and account for direct,
incremental, and sentinel evaluations separately.

v3 2026-08-07: expose the evaluated individual fingerprint and count duty
slice preparation/candidate assembly separately from full truth evaluation.

v4 2026-08-07: compare explicit charging decisions with the evaluator's
existing numerical equivalence tolerance so IEEE-754 round-off is not
misreported as a hidden repair; identities and material changes remain exact.

v5 2026-08-07: evaluate rolling-horizon candidates through the certified
exact-asset dynamic adapter and score the merged full-day execution history.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from setp_solver.check import (
    BATTERY,
    CAPACITY,
    FLEET_SIZE,
    PROFIT_FAIRNESS,
    TIME_WINDOW,
    FairnessContext,
    Violation,
    check_solution,
)
from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import (
    _depot_fleet_violations,
    annotate_cross_site_services,
)
from setp_solver.cost import evaluate
from setp_solver.profit import calculate_depot_profits, depot_profit_values
from setp_solver.search.multitrip_schedule import (
    MultiTripCertificate,
    prepare_multitrip_solution,
)
from setp_solver.solution import ChargingAction, Route, Solution

from .dynamic import DutyDynamicState, prepare_dynamic_candidate
from .model import DutyIndividual, PhysicalVehicleDuty

_EQUIVALENCE_ABS_TOL = 1.0e-9
_EQUIVALENCE_REL_TOL = 1.0e-12


@dataclass(frozen=True)
class FrozenMappingIdentity:
    """Content identity for an externally supplied mapping such as Pi0."""

    source_id: str
    value_sha256: str
    externally_frozen: bool

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("mapping source_id cannot be empty")
        if len(self.value_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.value_sha256.lower()
        ):
            raise ValueError("mapping value_sha256 must be a SHA-256 hex digest")


@dataclass(frozen=True)
class DutyEvaluationContext:
    """All external facts required by one full Duty evaluation."""

    bundle: China81Bundle
    independent_profit: Mapping[str, float]
    independent_profit_identity: FrozenMappingIdentity
    prior_profit: Mapping[str, float]
    theta: float
    carbon_quota_kg: float
    depot_charge_window_mode: str
    fairness_enabled: bool = True
    incremental_full_truth_sentinel_enabled: bool = True
    dynamic_state: DutyDynamicState | None = None

    def __post_init__(self) -> None:
        depots = {
            node.node_id
            for node in self.bundle.instance.nodes
            if node.node_type.lower() == "d"
        }
        if set(self.independent_profit) != depots:
            raise ValueError(
                "independent_profit must cover every depot exactly once"
            )
        if set(self.prior_profit) != depots:
            raise ValueError("prior_profit must cover every depot exactly once")
        if any(
            not math.isfinite(float(value)) or float(value) <= 0.0
            for value in self.independent_profit.values()
        ):
            raise ValueError("independent_profit values must be finite and positive")
        if self.independent_profit_identity.value_sha256.lower() != mapping_sha256(
            self.independent_profit
        ):
            raise ValueError(
                "independent_profit content disagrees with its frozen identity"
            )
        if (
            self.bundle.formal_search_allowed
            and not self.independent_profit_identity.externally_frozen
        ):
            raise ValueError(
                "formal search requires an externally frozen Pi0 identity"
            )
        if any(
            not math.isfinite(float(value))
            for value in self.prior_profit.values()
        ):
            raise ValueError("prior_profit values must be finite")
        if not math.isfinite(float(self.theta)):
            raise ValueError("theta must be finite")
        if not math.isfinite(float(self.carbon_quota_kg)) and not math.isinf(
            float(self.carbon_quota_kg)
        ):
            raise ValueError("carbon_quota_kg must be finite or infinite")
        if self.dynamic_state is not None:
            _validate_dynamic_state_customers(
                self.dynamic_state,
                self.bundle,
            )


@dataclass(frozen=True)
class FullEvaluation:
    """One transparent complete evaluation returned to Duty-HGS."""

    total_cost: float
    breakdown: Mapping[str, float]
    violations: tuple[Violation, ...]
    violation_magnitudes: tuple[float, ...]
    depot_profit: Mapping[str, float]
    participation_margin: Mapping[str, float]
    prepared_solution: Solution
    certificate: MultiTripCertificate
    individual_fingerprint: str
    source: str
    accounting: Mapping[str, int]

    @property
    def feasible(self) -> bool:
        return not self.violations


@dataclass(frozen=True)
class _DutySlice:
    fingerprint: str
    prepared_solution: Solution
    zero_quota_breakdown: Mapping[str, float]


def mapping_sha256(values: Mapping[str, float]) -> str:
    payload = [
        [str(key), float(value).hex()]
        for key, value in sorted(values.items())
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_dynamic_state_customers(
    state: DutyDynamicState,
    bundle: China81Bundle,
) -> None:
    all_customers = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    appearances = dict(state.customer_appearance_second)
    if set(appearances) != all_customers:
        raise ValueError(
            "dynamic appearance registry must cover every active customer"
        )
    if any(
        float(second) > float(state.cut.trigger_second) + 1.0e-9
        for second in appearances.values()
    ):
        raise ValueError(
            "dynamic evaluation cannot see a customer before its appearance"
        )
    committed_route_ids = {
        *state.cut.completed_route_ids,
        *state.cut.in_progress_route_ids,
    }
    committed_customers = {
        node_id
        for route in state.source_solution.routes
        if route.vehicle_id in committed_route_ids
        for node_id in route.node_sequence[1:-1]
        if node_id in all_customers
    }
    expected_future = all_customers.difference(committed_customers)
    if set(state.future_customer_ids) != expected_future:
        raise ValueError(
            "dynamic future customers must be exactly the customers outside "
            "the committed execution history"
        )


class DutyFullEvaluator:
    """Evaluate a Duty individual without allowing hidden vehicle repacking."""

    def __init__(self, context: DutyEvaluationContext):
        self.context = context
        self.full_calls = 0
        self.sentinel_calls = 0
        self.slice_preparation_calls = 0
        self.candidate_assembly_calls = 0

    def evaluate(self, individual: DutyIndividual) -> FullEvaluation:
        return self._evaluate_full(individual, source="full")

    def _evaluate_full(
        self,
        individual: DutyIndividual,
        *,
        source: str,
    ) -> FullEvaluation:
        self._validate_customer_partition(individual)
        dynamic_state = self.context.dynamic_state
        if dynamic_state is None:
            decoded = individual.to_solution()
            prepared, certificate = prepare_multitrip_solution(
                decoded,
                self.context.bundle.instance,
                self.context.bundle.prices,
                depot_charge_window_mode=self.context.depot_charge_window_mode,
            )
            _assert_no_hidden_repair(decoded, prepared)
        else:
            dynamic = prepare_dynamic_candidate(
                individual,
                dynamic_state,
                self.context.bundle,
            )
            prepared = dynamic.full_execution_solution
            certificate = dynamic.future_certificate
        annotated = annotate_cross_site_services(
            prepared,
            self.context.bundle.customer_home_depot,
        )
        self.full_calls += 1
        sentinel = int(source == "sentinel")
        self.sentinel_calls += sentinel
        return self._evaluate_prepared(
            annotated,
            certificate,
            individual_fingerprint=individual.fingerprint,
            source=source,
            accounting={
                "full_evaluations": 1 - sentinel,
                "incremental_evaluations": 0,
                "sentinel_evaluations": sentinel,
            },
        )

    def prepare_duty_slice(self, duty: PhysicalVehicleDuty) -> _DutySlice:
        if self.context.dynamic_state is not None:
            raise ValueError(
                "dynamic candidates require complete exact-asset evaluation"
            )
        individual = DutyIndividual(duties=(duty,), source="incremental-slice")
        decoded = individual.to_solution()
        prepared, _ = prepare_multitrip_solution(
            decoded,
            self.context.bundle.instance,
            self.context.bundle.prices,
            depot_charge_window_mode=self.context.depot_charge_window_mode,
        )
        _assert_no_hidden_repair(decoded, prepared)
        annotated = annotate_cross_site_services(
            prepared,
            self.context.bundle.customer_home_depot,
        )
        breakdown = evaluate(
            annotated,
            self.context.bundle.instance,
            self.context.bundle.time_profile,
            self.context.bundle.prices,
            carbon_quota_kg=0.0,
        )
        self.slice_preparation_calls += 1
        return _DutySlice(
            fingerprint=_duty_fingerprint(duty),
            prepared_solution=annotated,
            zero_quota_breakdown=breakdown,
        )

    def _evaluate_prepared(
        self,
        prepared: Solution,
        certificate: MultiTripCertificate,
        *,
        individual_fingerprint: str,
        source: str,
        accounting: Mapping[str, int],
        breakdown: Mapping[str, float] | None = None,
    ) -> FullEvaluation:
        bundle = self.context.bundle
        profit_breakdowns = calculate_depot_profits(
            prepared,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
            customer_home_depot=dict(bundle.customer_home_depot),
            prior_profit=dict(self.context.prior_profit),
            carbon_quota_kg=float(self.context.carbon_quota_kg),
        )
        profits = depot_profit_values(profit_breakdowns)
        fairness_context = FairnessContext(
            depot_profit=profits,
            independent_profit=dict(self.context.independent_profit),
            theta=float(self.context.theta),
        )
        violations = check_solution(
            prepared,
            bundle.instance,
            bundle.prices,
            fairness_context=fairness_context,
            fairness_enabled=bool(self.context.fairness_enabled),
        )
        violations.extend(
            _depot_fleet_violations(
                prepared,
                bundle,
                all_cv_reference=False,
            )
        )
        exact_breakdown = dict(
            breakdown
            if breakdown is not None
            else evaluate(
                prepared,
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
                carbon_quota_kg=float(self.context.carbon_quota_kg),
            )
        )
        margins = {
            depot_id: float(profits.get(depot_id, 0.0))
            - float(self.context.theta) * float(baseline)
            for depot_id, baseline in self.context.independent_profit.items()
        }
        violation_magnitudes = _measure_violations(
            tuple(violations),
            prepared,
            bundle,
            margins,
        )
        return FullEvaluation(
            total_cost=float(exact_breakdown["total_cost"]),
            breakdown=exact_breakdown,
            violations=tuple(violations),
            violation_magnitudes=violation_magnitudes,
            depot_profit=profits,
            participation_margin=margins,
            prepared_solution=prepared,
            certificate=certificate,
            individual_fingerprint=individual_fingerprint,
            source=source,
            accounting=dict(accounting),
        )

    def _validate_customer_partition(self, individual: DutyIndividual) -> None:
        dynamic_state = self.context.dynamic_state
        expected = (
            {
                node.node_id
                for node in self.context.bundle.instance.nodes
                if node.node_type.lower() == "c"
            }
            if dynamic_state is None
            else set(dynamic_state.future_customer_ids)
        )
        served = {
            customer
            for duty in individual.duties
            for trip in duty.trips
            for customer in trip.customer_ids
        }
        represented = served.union(individual.unserved_customers)
        if represented != expected:
            missing = sorted(expected.difference(represented))
            extra = sorted(represented.difference(expected))
            raise ValueError(
                "Duty customer partition disagrees with the instance: "
                f"missing={missing}, extra={extra}"
            )


class DutyIncrementalEvaluator:
    """Cache unchanged duty preparation/cost, then verify against full truth."""

    def __init__(self, full_evaluator: DutyFullEvaluator):
        self.full_evaluator = full_evaluator
        self._individual_fingerprint: str | None = None
        self._slices: dict[str, _DutySlice] = {}

    def seed(self, individual: DutyIndividual) -> int:
        self.full_evaluator._validate_customer_partition(individual)
        if self.full_evaluator.context.dynamic_state is not None:
            self._slices = {}
            self._individual_fingerprint = individual.fingerprint
            return 0
        self._slices = {
            duty.physical_vehicle_id: self.full_evaluator.prepare_duty_slice(duty)
            for duty in individual.duties
        }
        self._individual_fingerprint = individual.fingerprint
        return len(self._slices)

    def evaluate_after_change(
        self,
        previous: DutyIndividual,
        candidate: DutyIndividual,
        *,
        changed_duty_ids: set[str],
        commit: bool = False,
    ) -> FullEvaluation:
        if self._individual_fingerprint != previous.fingerprint:
            raise ValueError("incremental cache is not seeded for previous individual")
        actual_changed = _changed_duty_ids(previous, candidate)
        if set(changed_duty_ids) != actual_changed:
            raise ValueError(
                "changed duty scope is incomplete or over-declared: "
                f"actual={sorted(actual_changed)}, declared={sorted(changed_duty_ids)}"
            )
        self.full_evaluator._validate_customer_partition(candidate)
        if self.full_evaluator.context.dynamic_state is not None:
            result = self.full_evaluator._evaluate_full(
                candidate,
                source="dynamic-full",
            )
            if commit:
                self._individual_fingerprint = candidate.fingerprint
            return result
        next_slices: dict[str, _DutySlice] = {}
        recomputed = 0
        reused = 0
        for duty in candidate.duties:
            cached = self._slices.get(duty.physical_vehicle_id)
            fingerprint = _duty_fingerprint(duty)
            if (
                duty.physical_vehicle_id not in actual_changed
                and cached is not None
                and cached.fingerprint == fingerprint
            ):
                next_slices[duty.physical_vehicle_id] = cached
                reused += 1
            else:
                next_slices[duty.physical_vehicle_id] = (
                    self.full_evaluator.prepare_duty_slice(duty)
                )
                recomputed += 1

        combined = _combine_slices(next_slices)
        self.full_evaluator.candidate_assembly_calls += 1
        combined, certificate = prepare_multitrip_solution(
            combined,
            self.full_evaluator.context.bundle.instance,
            self.full_evaluator.context.bundle.prices,
            depot_charge_window_mode=(
                self.full_evaluator.context.depot_charge_window_mode
            ),
        )
        _assert_no_hidden_repair(_combine_slices(next_slices), combined)
        combined = annotate_cross_site_services(
            combined,
            self.full_evaluator.context.bundle.customer_home_depot,
        )
        breakdown = _aggregate_breakdowns(
            next_slices,
            self.full_evaluator.context,
        )
        sentinel_enabled = bool(
            self.full_evaluator.context.incremental_full_truth_sentinel_enabled
        )
        incremental = self.full_evaluator._evaluate_prepared(
            combined,
            certificate,
            individual_fingerprint=candidate.fingerprint,
            source=(
                "incremental_verified"
                if sentinel_enabled
                else "incremental_unverified"
            ),
            accounting={
                "full_evaluations": 0,
                "incremental_evaluations": 1,
                "sentinel_evaluations": int(sentinel_enabled),
                "candidate_assemblies": 1,
                "duty_slice_preparations": recomputed,
                "recomputed_duties": recomputed,
                "reused_duties": reused,
            },
            breakdown=breakdown,
        )

        if sentinel_enabled:
            truth = self.full_evaluator._evaluate_full(
                candidate,
                source="sentinel",
            )
            assert_evaluations_equivalent(incremental, truth)
        if commit:
            self._slices = next_slices
            self._individual_fingerprint = candidate.fingerprint
        return incremental


def assert_evaluations_equivalent(
    left: FullEvaluation,
    right: FullEvaluation,
) -> None:
    """Raise when an incremental result differs from full recomputation."""

    _assert_numeric_mapping_equal("breakdown", left.breakdown, right.breakdown)
    _assert_numeric_mapping_equal(
        "depot_profit",
        left.depot_profit,
        right.depot_profit,
    )
    _assert_numeric_mapping_equal(
        "participation_margin",
        left.participation_margin,
        right.participation_margin,
    )
    if _violation_keys(left.violations) != _violation_keys(right.violations):
        raise AssertionError("incremental violations differ from full truth")
    if left.violation_magnitudes != right.violation_magnitudes:
        raise AssertionError(
            "incremental violation magnitudes differ from full truth"
        )
    if left.prepared_solution != right.prepared_solution:
        raise AssertionError("incremental prepared solution differs from full truth")
    if left.certificate != right.certificate:
        raise AssertionError("incremental certificate differs from full truth")


def _measure_violations(
    violations: tuple[Violation, ...],
    prepared: Solution,
    bundle: China81Bundle,
    participation_margin: Mapping[str, float],
) -> tuple[float, ...]:
    """Return native-unit magnitudes where the model exposes them exactly."""

    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    route_by_id = {route.vehicle_id: route for route in prepared.routes}
    measured: list[float] = []
    for violation in violations:
        magnitude = 1.0
        if violation.type == CAPACITY and violation.vehicle_id in route_by_id:
            route = route_by_id[violation.vehicle_id]
            demand = sum(
                float(node_lookup[node_id].demand)
                for node_id in route.node_sequence
                if node_lookup[node_id].node_type.lower() == "c"
            )
            capacity = bundle.instance.payload_capacity_kg(
                route.vehicle_type,
                fallback=float(bundle.prices.Q_capacity),
            )
            overload = max(0.0, demand - capacity)
            if overload > 0.0:
                magnitude = overload
        elif violation.type == PROFIT_FAIRNESS:
            deficit = max(
                0.0,
                -float(participation_margin.get(violation.location, 0.0)),
            )
            if deficit > 0.0:
                magnitude = deficit
        elif violation.type == TIME_WINDOW:
            late_seconds = _time_window_magnitude(violation.detail)
            if late_seconds is not None:
                magnitude = late_seconds
        elif violation.type == BATTERY:
            battery_gap = _battery_magnitude(violation.detail)
            if battery_gap is not None:
                magnitude = battery_gap
        elif violation.type == FLEET_SIZE:
            fleet_overage = _fleet_magnitude(violation.detail)
            if fleet_overage is not None:
                magnitude = fleet_overage
        measured.append(float(magnitude))
    return tuple(measured)


_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def _time_window_magnitude(detail: str) -> float | None:
    match = re.search(rf"late by\s+({_NUMBER})\s+s", detail)
    if match is None:
        return None
    return max(0.0, float(match.group(1)))


def _battery_magnitude(detail: str) -> float | None:
    below_zero = re.search(
        rf"battery after arc is\s+({_NUMBER})\s+kWh\s+<\s+0",
        detail,
    )
    if below_zero is not None:
        return max(0.0, -float(below_zero.group(1)))

    above_cap = re.search(
        rf"is\s+({_NUMBER})\s+kWh\s+>\s+B=({_NUMBER})",
        detail,
    )
    if above_cap is not None:
        return max(
            0.0,
            float(above_cap.group(1)) - float(above_cap.group(2)),
        )

    mismatch = re.search(
        rf"energy\s+({_NUMBER})\s+does not match.*?({_NUMBER})",
        detail,
    )
    if mismatch is not None:
        return abs(float(mismatch.group(1)) - float(mismatch.group(2)))
    return None


def _fleet_magnitude(detail: str) -> float | None:
    counts = [int(value) for value in re.findall(r"\b\d+\b", detail)]
    if len(counts) < 2:
        return None
    return float(max(0, counts[0] - counts[1]))


def _assert_no_hidden_repair(before: Solution, after: Solution) -> None:
    if _route_keys(before.routes) != _route_keys(after.routes):
        raise ValueError(
            "multi-trip preparation changed the explicit vehicle-to-trip mapping"
        )
    if not _actions_equivalent(
        before.charging_actions,
        after.charging_actions,
    ):
        raise ValueError(
            "multi-trip preparation changed an explicit charging decision"
        )


def _route_keys(routes: list[Route]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        sorted(
            (
                route.vehicle_id,
                route.vehicle_type.lower(),
                route.home_depot_id,
                tuple(route.node_sequence),
            )
            for route in routes
        )
    )


def _actions_equivalent(
    before: list[ChargingAction],
    after: list[ChargingAction],
) -> bool:
    left = sorted(before, key=_action_sort_key)
    right = sorted(after, key=_action_sort_key)
    if len(left) != len(right):
        return False
    for earlier, later in zip(left, right, strict=True):
        if (
            earlier.vehicle_id != later.vehicle_id
            or earlier.station_id != later.station_id
            or int(earlier.charge_day_offset) != int(later.charge_day_offset)
            or earlier.charging_curve_id != later.charging_curve_id
        ):
            return False
        if not all(
            _float_equivalent(left_value, right_value)
            for left_value, right_value in (
                (earlier.energy_kwh, later.energy_kwh),
                (earlier.occupancy_minutes, later.occupancy_minutes),
                (earlier.charge_start_second, later.charge_start_second),
            )
        ):
            return False
        if not _optional_float_equivalent(
            earlier.start_energy_kwh,
            later.start_energy_kwh,
        ) or not _optional_float_equivalent(
            earlier.end_energy_kwh,
            later.end_energy_kwh,
        ):
            return False
    return True


def _action_sort_key(action: ChargingAction) -> tuple[object, ...]:
    return (
        action.vehicle_id,
        action.station_id,
        int(action.charge_day_offset),
        "" if action.charging_curve_id is None else action.charging_curve_id,
        float(action.charge_start_second),
        float(action.energy_kwh),
        float(action.occupancy_minutes),
        float("-inf")
        if action.start_energy_kwh is None
        else float(action.start_energy_kwh),
        float("-inf")
        if action.end_energy_kwh is None
        else float(action.end_energy_kwh),
    )


def _float_equivalent(left: float, right: float) -> bool:
    return math.isclose(
        float(left),
        float(right),
        rel_tol=_EQUIVALENCE_REL_TOL,
        abs_tol=_EQUIVALENCE_ABS_TOL,
    )


def _optional_float_equivalent(
    left: float | None,
    right: float | None,
) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return _float_equivalent(left, right)


def _duty_fingerprint(duty: PhysicalVehicleDuty) -> str:
    return DutyIndividual(duties=(duty,), source="fingerprint").fingerprint


def _changed_duty_ids(
    previous: DutyIndividual,
    candidate: DutyIndividual,
) -> set[str]:
    left = {
        duty.physical_vehicle_id: _duty_fingerprint(duty)
        for duty in previous.duties
    }
    right = {
        duty.physical_vehicle_id: _duty_fingerprint(duty)
        for duty in candidate.duties
    }
    return {
        duty_id
        for duty_id in set(left).union(right)
        if left.get(duty_id) != right.get(duty_id)
    }


def _combine_slices(slices: Mapping[str, _DutySlice]) -> Solution:
    routes = [
        route
        for duty_id in sorted(slices)
        for route in slices[duty_id].prepared_solution.routes
    ]
    actions = [
        action
        for duty_id in sorted(slices)
        for action in slices[duty_id].prepared_solution.charging_actions
    ]
    actions.sort(
        key=lambda action: (
            action.vehicle_id,
            action.station_id,
            float(action.charge_start_second),
            float(action.energy_kwh),
        )
    )
    return Solution(routes=routes, charging_actions=actions)


def _aggregate_breakdowns(
    slices: Mapping[str, _DutySlice],
    context: DutyEvaluationContext,
) -> dict[str, float]:
    rows = [item.zero_quota_breakdown for item in slices.values()]
    if not rows:
        raise ValueError("incremental evaluation requires at least one duty")
    keys = set(rows[0])
    if any(set(row) != keys for row in rows[1:]):
        raise AssertionError("duty cost breakdown schemas differ")
    excluded = {"total_cost", "cost_carbon", "carbon_quota_kg"}
    out = {
        key: sum(float(row[key]) for row in rows)
        for key in sorted(keys.difference(excluded))
    }
    quota = float(context.carbon_quota_kg)
    out["cost_carbon"] = (
        0.0
        if math.isinf(quota)
        else (out["E_total"] - quota)
        * _price(context.bundle.prices, "carbon_price")
    )
    out["carbon_quota_kg"] = quota
    out["total_cost"] = sum(
        out[key]
        for key in (
            "cost_fix",
            "cost_km",
            "cost_fuel",
            "cost_elec",
            "cost_occ",
            "cost_time",
            "cost_transship",
            "cost_carbon",
        )
    )
    return out


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def _assert_numeric_mapping_equal(
    label: str,
    left: Mapping[str, float],
    right: Mapping[str, float],
) -> None:
    if set(left) != set(right):
        raise AssertionError(f"{label} keys differ")
    for key in left:
        if not math.isclose(
            float(left[key]),
            float(right[key]),
            rel_tol=_EQUIVALENCE_REL_TOL,
            abs_tol=_EQUIVALENCE_ABS_TOL,
        ):
            raise AssertionError(
                f"{label}[{key}] differs: {left[key]} != {right[key]}"
            )


def _violation_keys(
    violations: tuple[Violation, ...],
) -> tuple[tuple[str, str, str, str, str], ...]:
    return tuple(
        sorted(
            (
                violation.type,
                violation.vehicle_id,
                violation.location,
                violation.detail,
                violation.severity,
            )
            for violation in violations
        )
    )
