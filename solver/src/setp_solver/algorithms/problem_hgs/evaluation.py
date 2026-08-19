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

v6 2026-08-08: allow the caller to defer the full-truth sentinel until an
action is selected.  The incremental result is unchanged; selected actions,
population entries, and final solutions can still be verified by cold truth.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from setp_solver.check import (
    BATTERY,
    CAPACITY,
    FLEET_SIZE,
    PROFIT_FAIRNESS,
    TIME_WINDOW,
    DynamicCheckContext,
    FairnessContext,
    Violation,
    check_solution,
)
from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import (
    _depot_fleet_violations,
    annotate_cross_site_services,
)
from setp_solver.cost import (
    _arc_loads,
    _evaluate_route,
    diesel_price_for_route,
    evaluate,
)
from setp_solver.instance_loader import Instance
from setp_solver.mapping_identity import mapping_sha256
from setp_solver.profit import calculate_depot_profits, depot_profit_values
from setp_solver.search.multitrip_schedule import (
    MultiTripCertificate,
    prepare_multitrip_solution,
)
from setp_solver.solution import (
    ChargingAction,
    Route,
    Solution,
    physical_vehicle_id,
)

from .contracts import (
    CHARGING_ENERGY_GAP,
    CHARGING_WINDOW_GAP,
    ChargingCandidateStatus,
    ChargingClockWitness,
    ChargingGap,
    ChargingGapDutyIndividual,
)
from .dynamic import (
    DutyDynamicState,
    DynamicPrefixAccountingCorrection,
    full_executed_prefix,
    prepare_dynamic_candidate,
)
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
class RebuiltRouteConstraintContract:
    """Candidate-level two-shift and volume contract for the rebuilt instance."""

    source_id: str
    customer_shift_by_id: Mapping[str, str]
    customer_volume_m3_by_id: Mapping[str, float]
    shift_window_second_by_id: Mapping[str, tuple[float, float]]
    vehicle_volume_capacity_m3: float

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("rebuilt route constraint source_id cannot be empty")
        if set(self.customer_shift_by_id) != set(self.customer_volume_m3_by_id):
            raise ValueError("rebuilt shift and volume customer identities differ")
        if not self.customer_shift_by_id:
            raise ValueError("rebuilt route constraint has no customers")
        if set(self.customer_shift_by_id.values()) != set(
            self.shift_window_second_by_id
        ):
            raise ValueError("rebuilt route constraint shift windows are incomplete")
        if any(
            not math.isfinite(float(volume)) or float(volume) < 0.0
            for volume in self.customer_volume_m3_by_id.values()
        ):
            raise ValueError("rebuilt customer volumes must be finite and nonnegative")
        for start, end in self.shift_window_second_by_id.values():
            if (
                not math.isfinite(float(start))
                or not math.isfinite(float(end))
                or float(end) <= float(start)
            ):
                raise ValueError("rebuilt shift window is invalid")
        if (
            not math.isfinite(float(self.vehicle_volume_capacity_m3))
            or float(self.vehicle_volume_capacity_m3) <= 0.0
        ):
            raise ValueError("rebuilt vehicle volume capacity must be positive")


def assert_candidate_routes_single_shift(
    individual: DutyIndividual,
    contract: RebuiltRouteConstraintContract | None,
) -> None:
    """Reject a materialized Duty trip that crosses registered shifts."""

    if contract is None:
        return
    for duty in individual.duties:
        for trip in duty.trips:
            shifts = set()
            for customer_id in trip.customer_ids:
                try:
                    shifts.add(
                        str(contract.customer_shift_by_id[customer_id])
                    )
                except KeyError as exc:
                    raise ValueError(
                        "candidate route references a customer outside the "
                        f"rebuilt shift contract: {customer_id}"
                    ) from exc
            if len(shifts) > 1:
                raise ValueError(
                    f"rebuilt route {duty.route_id(trip.trip_index)} mixes "
                    "customer shifts: "
                    + ", ".join(sorted(shifts))
                )


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
    ev_daily_fixed_premium_cny: float = 0.0
    rebuilt_route_constraints: RebuiltRouteConstraintContract | None = None
    shift_aware_departure_enabled: bool = False

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
            self.fairness_enabled
            and self.bundle.formal_search_allowed
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
        if (
            not math.isfinite(float(self.ev_daily_fixed_premium_cny))
            or float(self.ev_daily_fixed_premium_cny) < 0.0
        ):
            raise ValueError("EV daily fixed premium must be finite and nonnegative")
        if self.rebuilt_route_constraints is not None:
            customers = {
                node.node_id
                for node in self.bundle.instance.nodes
                if node.node_type.lower() == "c"
            }
            if set(self.rebuilt_route_constraints.customer_shift_by_id) != customers:
                raise ValueError(
                    "rebuilt route constraint must cover every active customer"
                )
        if (
            self.shift_aware_departure_enabled
            and self.rebuilt_route_constraints is None
        ):
            raise ValueError(
                "shift-aware departure requires rebuilt route constraints"
            )
        if self.dynamic_state is not None:
            _validate_dynamic_state_customers(
                self.dynamic_state,
                self.bundle,
            )


@dataclass(frozen=True)
class FullEvaluation:
    """One transparent complete evaluation returned to Problem-HGS."""

    total_cost: float
    breakdown: Mapping[str, float]
    violations: tuple[Violation, ...]
    violation_magnitudes: tuple[float, ...]
    depot_profit: Mapping[str, float]
    participation_margin: Mapping[str, float]
    prepared_solution: Solution
    certificate: MultiTripCertificate
    individual_fingerprint: str
    evaluation_context_sha256: str
    source: str
    accounting: Mapping[str, int]
    charging_candidate_status: ChargingCandidateStatus = (
        ChargingCandidateStatus.READY
    )
    charging_gap: ChargingGap = ChargingGap()
    charging_rejection_reason: str | None = None
    charging_affected_duty_ids: tuple[str, ...] = ()
    charging_clock_witnesses: tuple[ChargingClockWitness, ...] = ()
    dynamic_prefix_accounting_by_route_id: Mapping[
        str, DynamicPrefixAccountingCorrection
    ] = field(default_factory=dict)

    @property
    def feasible(self) -> bool:
        return not self.violations


@dataclass(frozen=True)
class _DutySlice:
    fingerprint: str
    prepared_solution: Solution
    zero_quota_breakdown: Mapping[str, float]


@dataclass(frozen=True)
class _DynamicPrefixAccountingTotals:
    fuel_liters: float = 0.0
    fuel_cost: float = 0.0
    cv_emissions_kg: float = 0.0
    ev_drive_kwh: float = 0.0
    fuel_cost_by_depot: tuple[tuple[str, float], ...] = ()
    cv_emissions_by_depot: tuple[tuple[str, float], ...] = ()


def _remove_certified_dynamic_battery_duplicates(
    violations: list[Violation],
    certified_future_route_ids: set[str],
) -> list[Violation]:
    """Keep static findings except duplicate battery checks on certified routes."""

    return [
        violation
        for violation in violations
        if not (
            violation.type == BATTERY
            and violation.vehicle_id in certified_future_route_ids
        )
    ]


def _canonical_identity_value(value: Any) -> Any:
    """Convert an evaluation input into deterministic JSON identity data."""

    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        return {"float_hex": value.hex()}
    if isinstance(value, Path):
        return {"path": str(value)}
    if isinstance(value, Enum):
        return {
            "enum": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _canonical_identity_value(value.value),
        }
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "dataclass": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": {
                field.name: _canonical_identity_value(getattr(value, field.name))
                for field in fields(value)
            },
        }
    if isinstance(value, Mapping):
        rows = [
            (
                _canonical_identity_value(key),
                _canonical_identity_value(item),
            )
            for key, item in value.items()
        ]
        rows.sort(
            key=lambda row: json.dumps(
                row[0],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return {"mapping": rows}
    if isinstance(value, (set, frozenset)):
        rows = [_canonical_identity_value(item) for item in value]
        rows.sort(
            key=lambda row: json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return {"set": rows}
    if isinstance(value, (list, tuple)):
        return [_canonical_identity_value(item) for item in value]
    return {
        "object": f"{type(value).__module__}.{type(value).__qualname__}",
        "repr": repr(value),
    }


def evaluation_context_sha256(context: DutyEvaluationContext) -> str:
    """Bind cached evaluations to every input used by the full evaluator."""

    encoded = json.dumps(
        _canonical_identity_value(context),
        ensure_ascii=False,
        sort_keys=True,
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
    committed_route_ids = set(state.cut.completed_route_ids)
    committed_customers = {
        node_id
        for route in (
            *(state.prior_committed_solution or Solution()).routes,
            *(
                route
                for route in state.source_solution.routes
                if route.vehicle_id in committed_route_ids
            ),
        )
        for node_id in route.node_sequence[1:-1]
        if node_id in all_customers
    }
    committed_customers.update(
        node_id
        for asset in state.asset_states.values()
        for node_id in _asset_full_executed_prefix(state, asset)
        if node_id in all_customers
    )
    expected_future = all_customers.difference(committed_customers)
    if set(state.future_customer_ids) != expected_future:
        raise ValueError(
            "dynamic future customers must be exactly the customers outside "
            "the committed execution history"
        )


def _asset_full_executed_prefix(
    state: DutyDynamicState,
    asset: Any,
) -> tuple[str, ...]:
    prefix = tuple(getattr(asset, "executed_prefix", ()))
    route_id = getattr(asset, "continuation_route_id", None)
    if not prefix:
        return prefix
    if route_id is None:
        candidates = [
            candidate
            for candidate in state.cut.in_progress_route_ids
            if physical_vehicle_id(candidate)
            == str(asset.physical_vehicle_id)
        ]
        if len(candidates) > 1:
            raise ValueError(
                "dynamic asset has multiple in-progress source routes"
            )
        if not candidates:
            return prefix
        route_id = candidates[0]
    source_routes = {
        route.vehicle_id: route
        for route in (
            state.source_full_execution_solution or state.source_solution
        ).routes
    }
    try:
        source_route = source_routes[str(route_id)]
    except KeyError as exc:
        raise ValueError(
            "dynamic history omits an active continuation route"
        ) from exc
    return full_executed_prefix(source_route, prefix)


def _shift_minimum_departure_second_by_customer(
    context: DutyEvaluationContext,
) -> dict[str, float] | None:
    if not context.shift_aware_departure_enabled:
        return None
    contract = context.rebuilt_route_constraints
    if contract is None:
        raise ValueError("shift-aware departure has no shift contract")
    return {
        customer_id: float(
            contract.shift_window_second_by_id[str(shift_id)][0]
        )
        for customer_id, shift_id in contract.customer_shift_by_id.items()
    }


def _shift_minimum_departure_second_by_route(
    solution: Solution,
    context: DutyEvaluationContext,
) -> dict[str, float] | None:
    if not context.shift_aware_departure_enabled:
        return None
    contract = context.rebuilt_route_constraints
    if contract is None:
        raise ValueError("shift-aware departure has no shift contract")
    minimum_by_route: dict[str, float] = {}
    for route in solution.routes:
        shifts = {
            str(contract.customer_shift_by_id[node_id])
            for node_id in route.node_sequence[1:-1]
            if node_id in contract.customer_shift_by_id
        }
        if len(shifts) == 1:
            shift_id = next(iter(shifts))
            minimum_by_route[route.vehicle_id] = float(
                contract.shift_window_second_by_id[shift_id][0]
            )
    return minimum_by_route


def _charging_gap_certificate(
    individual: ChargingGapDutyIndividual,
    context: DutyEvaluationContext,
) -> MultiTripCertificate:
    """Materialise an explicit incomplete certificate without inventing a schedule."""

    counts = {
        vehicle_type: sum(
            1
            for duty in individual.duties
            if duty.trips and duty.vehicle_type == vehicle_type
        )
        for vehicle_type in ("cv", "ev")
    }
    return MultiTripCertificate(
        contract_id="SC3_CHARGING_GAP_BEST_EFFORT_V1",
        status=ChargingCandidateStatus.BEST_EFFORT.value,
        vehicle_counts=counts,
        trips=(),
        recharge_mode=context.depot_charge_window_mode,
        depot_charge_power_kw=float(
            context.bundle.prices.depot_charge_power_kw
        ),
    )


class DutyFullEvaluator:
    """Evaluate a Duty individual without allowing hidden vehicle repacking."""

    def __init__(self, context: DutyEvaluationContext):
        self.context = context
        self.context_sha256 = evaluation_context_sha256(context)
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
        gap_candidate = (
            individual
            if isinstance(individual, ChargingGapDutyIndividual)
            else None
        )
        dynamic_state = self.context.dynamic_state
        dynamic_prepared = None
        if dynamic_state is None:
            decoded = individual.to_solution()
            try:
                prepared, certificate = prepare_multitrip_solution(
                    decoded,
                    self.context.bundle.instance,
                    self.context.bundle.prices,
                    depot_charge_window_mode=(
                        self.context.depot_charge_window_mode
                    ),
                    minimum_departure_second_by_route=(
                        _shift_minimum_departure_second_by_route(
                            decoded,
                            self.context,
                        )
                    ),
                )
                _assert_no_hidden_repair(decoded, prepared)
            except (TypeError, ValueError):
                if gap_candidate is None:
                    raise
                prepared = decoded
                certificate = _charging_gap_certificate(
                    gap_candidate,
                    self.context,
                )
        else:
            if gap_candidate is not None:
                raise ValueError(
                    "SC3 BEST_EFFORT is not defined for a dynamic cut"
                )
            dynamic = prepare_dynamic_candidate(
                individual,
                dynamic_state,
                self.context.bundle,
                minimum_departure_second_by_customer_id=(
                    _shift_minimum_departure_second_by_customer(self.context)
                ),
                shift_id_by_customer_id=(
                    None
                    if self.context.rebuilt_route_constraints is None
                    else self.context.rebuilt_route_constraints.customer_shift_by_id
                ),
            )
            prepared = dynamic.full_execution_solution
            certificate = dynamic.future_certificate
            dynamic_prepared = dynamic
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
            charging_candidate_status=(
                ChargingCandidateStatus.READY
                if gap_candidate is None
                else gap_candidate.charging_candidate_status
            ),
            charging_gap=(
                ChargingGap()
                if gap_candidate is None
                else gap_candidate.charging_gap
            ),
            charging_rejection_reason=(
                None
                if gap_candidate is None
                else gap_candidate.charging_rejection_reason
            ),
            charging_affected_duty_ids=(
                ()
                if gap_candidate is None
                else gap_candidate.affected_duty_ids
            ),
            charging_clock_witnesses=(
                ()
                if gap_candidate is None
                else gap_candidate.charging_clock_witnesses
            ),
            evaluation_instance=(
                None
                if dynamic_prepared is None
                else dynamic_prepared.evaluation_instance
            ),
            dynamic_future_solution=(
                None
                if dynamic_prepared is None
                else dynamic_prepared.future_solution
            ),
            dynamic_future_check_instance=(
                None
                if dynamic_prepared is None
                else dynamic_prepared.future_check_instance
            ),
            dynamic_future_check_context=(
                None
                if dynamic_prepared is None
                else dynamic_prepared.future_check_context
            ),
            dynamic_frozen_prefixes=(
                None
                if dynamic_prepared is None
                else dynamic_prepared.frozen_prefixes
            ),
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
            minimum_departure_second_by_route=(
                _shift_minimum_departure_second_by_route(
                    decoded,
                    self.context,
                )
            ),
        )
        _assert_no_hidden_repair(decoded, prepared)
        annotated = annotate_cross_site_services(
            prepared,
            self.context.bundle.customer_home_depot,
        )
        breakdown = _evaluate_with_context_cost(
            annotated,
            self.context,
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
        charging_candidate_status: ChargingCandidateStatus = (
            ChargingCandidateStatus.READY
        ),
        charging_gap: ChargingGap = ChargingGap(),
        charging_rejection_reason: str | None = None,
        charging_affected_duty_ids: tuple[str, ...] = (),
        charging_clock_witnesses: tuple[ChargingClockWitness, ...] = (),
        evaluation_instance: Instance | None = None,
        dynamic_future_solution: Solution | None = None,
        dynamic_future_check_instance: Instance | None = None,
        dynamic_future_check_context: DynamicCheckContext | None = None,
        dynamic_frozen_prefixes: Mapping[str, tuple[str, ...]] | None = None,
    ) -> FullEvaluation:
        bundle = (
            self.context.bundle
            if evaluation_instance is None
            else replace(
                self.context.bundle,
                instance=evaluation_instance,
            )
        )
        prefix_accounting_by_route_id = (
            MappingProxyType({})
            if self.context.dynamic_state is None
            else _dynamic_prefix_accounting_by_route_id(
                prepared,
                self.context.dynamic_state,
                bundle,
            )
        )
        prefix_correction = _aggregate_dynamic_prefix_accounting(
            prefix_accounting_by_route_id
        )
        profit_breakdowns = calculate_depot_profits(
            prepared,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
            customer_home_depot=dict(bundle.customer_home_depot),
            prior_profit=dict(self.context.prior_profit),
            carbon_quota_kg=float(self.context.carbon_quota_kg),
        )
        profits = _correct_dynamic_depot_profits(
            depot_profit_values(profit_breakdowns),
            profit_breakdowns,
            prefix_correction,
            bundle,
            carbon_quota_kg=float(self.context.carbon_quota_kg),
        )
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
            dynamic_context=(
                None
                if not dynamic_frozen_prefixes
                else DynamicCheckContext(
                    frozen_prefixes=dict(dynamic_frozen_prefixes),
                )
            ),
        )
        if self.context.rebuilt_route_constraints is not None:
            violations.extend(
                _rebuilt_route_constraint_violations(
                    prepared,
                    certificate,
                    self.context.rebuilt_route_constraints,
                    allowed_unscheduled_route_ids=(
                        frozenset()
                        if self.context.dynamic_state is None
                        else frozenset(
                            {
                                *self.context.dynamic_state.cut.completed_route_ids,
                                *self.context.dynamic_state.cut.in_progress_route_ids,
                                *(
                                    route.vehicle_id
                                    for route in self.context.dynamic_state.prior_committed_solution.routes
                                ),
                            }
                        )
                    ),
                )
            )
        if self.context.dynamic_state is not None:
            # The merged full-day Solution is also passed through the static
            # checker, whose route-local battery ledger starts every EV at the
            # static initial battery.  A rolling continuation instead starts
            # at the inherited asset battery already closed by
            # validate_dynamic_multitrip_certificate().  Retain every other
            # static violation and every historical-route battery violation;
            # only the certified future-route duplicate battery verdict is
            # removed.
            certified_future_route_ids = {
                trip.route_id for trip in certificate.trips
            }
            violations = _remove_certified_dynamic_battery_duplicates(
                violations,
                certified_future_route_ids.union(
                    self.context.dynamic_state.certified_dynamic_route_ids
                ),
            )
            if (
                dynamic_future_solution is None
                or dynamic_future_check_instance is None
                or dynamic_future_check_context is None
            ):
                raise ValueError(
                    "dynamic evaluation is missing its inherited-state check"
                )
            violations.extend(
                check_solution(
                    dynamic_future_solution,
                    dynamic_future_check_instance,
                    bundle.prices,
                    fairness_enabled=False,
                    dynamic_context=dynamic_future_check_context,
                )
            )
        violations.extend(
            _depot_fleet_violations(
                prepared,
                bundle,
                all_cv_reference=False,
            )
        )
        gap_vehicle_id = (
            charging_affected_duty_ids[0]
            if charging_affected_duty_ids
            else ""
        )
        if charging_gap.missing_energy_kwh > 0.0:
            violations.append(
                Violation(
                    CHARGING_ENERGY_GAP,
                    gap_vehicle_id,
                    "charging_subproblem",
                    "missing energy "
                    f"{charging_gap.missing_energy_kwh:.17g} kWh",
                )
            )
        if charging_gap.window_shortage_seconds > 0.0:
            violations.append(
                Violation(
                    CHARGING_WINDOW_GAP,
                    gap_vehicle_id,
                    "charging_subproblem",
                    "feasible charging window short by "
                    f"{charging_gap.window_shortage_seconds:.17g} s",
                )
            )
        exact_breakdown = dict(
            breakdown
            if breakdown is not None
            else _evaluate_with_context_cost(
                prepared,
                self.context,
                carbon_quota_kg=float(self.context.carbon_quota_kg),
                bundle=bundle,
            )
        )
        exact_breakdown = _correct_dynamic_breakdown(
            exact_breakdown,
            prefix_correction,
            bundle,
            carbon_quota_kg=float(self.context.carbon_quota_kg),
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
            charging_gap=charging_gap,
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
            evaluation_context_sha256=self.context_sha256,
            source=source,
            accounting=dict(accounting),
            charging_candidate_status=ChargingCandidateStatus(
                charging_candidate_status
            ),
            charging_gap=charging_gap,
            charging_rejection_reason=charging_rejection_reason,
            charging_affected_duty_ids=tuple(charging_affected_duty_ids),
            charging_clock_witnesses=tuple(charging_clock_witnesses),
            dynamic_prefix_accounting_by_route_id=(
                prefix_accounting_by_route_id
            ),
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
        if isinstance(individual, ChargingGapDutyIndividual):
            self._slices = {}
            self._individual_fingerprint = individual.fingerprint
            return 0
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
        verify_full_truth: bool | None = None,
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
        if isinstance(
            previous,
            ChargingGapDutyIndividual,
        ) or isinstance(candidate, ChargingGapDutyIndividual):
            result = self.full_evaluator._evaluate_full(
                candidate,
                source="charging-gap-full",
            )
            if commit:
                self._slices = {}
                self._individual_fingerprint = candidate.fingerprint
            return result
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

        unprepared = _combine_slices(next_slices)
        self.full_evaluator.candidate_assembly_calls += 1
        combined, certificate = prepare_multitrip_solution(
            unprepared,
            self.full_evaluator.context.bundle.instance,
            self.full_evaluator.context.bundle.prices,
            depot_charge_window_mode=(
                self.full_evaluator.context.depot_charge_window_mode
            ),
            minimum_departure_second_by_route=(
                _shift_minimum_departure_second_by_route(
                    unprepared,
                    self.full_evaluator.context,
                )
            ),
        )
        _assert_no_hidden_repair(unprepared, combined)
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
            if verify_full_truth is None
            else verify_full_truth
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

    def verify_against_full_truth(
        self,
        candidate: DutyIndividual,
        incremental: FullEvaluation,
    ) -> FullEvaluation:
        """Cold-replay one selected incremental candidate and return truth."""

        if incremental.individual_fingerprint != candidate.fingerprint:
            raise ValueError("sentinel received another candidate evaluation")
        truth = self.full_evaluator._evaluate_full(
            candidate,
            source="sentinel",
        )
        assert_evaluations_equivalent(incremental, truth)
        return truth


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
    if left.charging_candidate_status != right.charging_candidate_status:
        raise AssertionError("incremental charging candidate status differs")
    if left.charging_gap != right.charging_gap:
        raise AssertionError("incremental charging gap differs")
    if left.charging_rejection_reason != right.charging_rejection_reason:
        raise AssertionError("incremental charging rejection reason differs")
    if left.charging_affected_duty_ids != right.charging_affected_duty_ids:
        raise AssertionError("incremental charging affected duties differ")
    if left.charging_clock_witnesses != right.charging_clock_witnesses:
        raise AssertionError("incremental charging clock witnesses differ")
    if (
        dict(left.dynamic_prefix_accounting_by_route_id)
        != dict(right.dynamic_prefix_accounting_by_route_id)
    ):
        raise AssertionError("dynamic prefix accounting differs from full truth")


def _dynamic_prefix_accounting_by_route_id(
    solution: Solution,
    state: DutyDynamicState,
    bundle: China81Bundle,
) -> Mapping[str, DynamicPrefixAccountingCorrection]:
    """Restore the certified load on arcs driven before reoptimization."""

    routes = {route.vehicle_id: route for route in solution.routes}
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    corrections = dict(state.prior_prefix_accounting_by_route_id)
    for route_id, correction in corrections.items():
        route = routes.get(route_id)
        if route is None or route.home_depot_id != correction.home_depot_id:
            raise ValueError(
                "dynamic prefix accounting is detached from execution history"
            )
    for asset in state.asset_states.values():
        route_id = getattr(asset, "continuation_route_id", None)
        virtual_id = getattr(asset, "virtual_origin_node_id", None)
        if route_id is None or virtual_id is None:
            continue
        try:
            route = routes[str(route_id)]
            virtual_index = route.node_sequence.index(str(virtual_id))
        except (KeyError, ValueError) as exc:
            raise ValueError(
                "dynamic accounting lost its inherited virtual origin"
            ) from exc
        if virtual_index < 1:
            raise ValueError("dynamic virtual origin has no executed prefix")
        candidate_loads = _arc_loads(route.node_sequence, nodes)
        candidate_load = float(candidate_loads[virtual_index - 1])
        inherited_load = float(getattr(asset, "remaining_load_kg", 0.0))
        prefix = route.node_sequence[: virtual_index + 1]
        candidate_energy = _prefix_energy_at_terminal_load(
            route,
            prefix,
            str(virtual_id),
            candidate_load,
            bundle,
        )
        inherited_energy = _prefix_energy_at_terminal_load(
            route,
            prefix,
            str(virtual_id),
            inherited_load,
            bundle,
        )
        prior = corrections.get(str(route_id))
        if prior is not None and prior.home_depot_id != route.home_depot_id:
            raise ValueError("dynamic prefix accounting changed home depot")
        if route.vehicle_type == "cv":
            fuel_delta = float(
                inherited_energy.fuel_liters
                - candidate_energy.fuel_liters
            )
            fuel_cost_delta = fuel_delta * diesel_price_for_route(
                route,
                bundle.instance,
                bundle.prices,
            )
            emissions_delta = fuel_delta * float(bundle.prices.diesel_ef)
            corrections[str(route_id)] = DynamicPrefixAccountingCorrection(
                home_depot_id=route.home_depot_id,
                fuel_liters=fuel_delta,
                fuel_cost=fuel_cost_delta,
                cv_emissions_kg=emissions_delta,
            )
        else:
            ev_delta = float(
                inherited_energy.ev_drive_kwh
                - candidate_energy.ev_drive_kwh
            )
            corrections[str(route_id)] = DynamicPrefixAccountingCorrection(
                home_depot_id=route.home_depot_id,
                ev_drive_kwh=ev_delta,
            )
    return MappingProxyType(dict(sorted(corrections.items())))


def _aggregate_dynamic_prefix_accounting(
    corrections: Mapping[str, DynamicPrefixAccountingCorrection],
) -> _DynamicPrefixAccountingTotals:
    fuel_by_depot: dict[str, float] = {}
    emissions_by_depot: dict[str, float] = {}
    for correction in corrections.values():
        depot_id = correction.home_depot_id
        fuel_by_depot[depot_id] = (
            fuel_by_depot.get(depot_id, 0.0) + float(correction.fuel_cost)
        )
        emissions_by_depot[depot_id] = (
            emissions_by_depot.get(depot_id, 0.0)
            + float(correction.cv_emissions_kg)
        )
    return _DynamicPrefixAccountingTotals(
        fuel_liters=sum(float(item.fuel_liters) for item in corrections.values()),
        fuel_cost=sum(float(item.fuel_cost) for item in corrections.values()),
        cv_emissions_kg=sum(
            float(item.cv_emissions_kg) for item in corrections.values()
        ),
        ev_drive_kwh=sum(
            float(item.ev_drive_kwh) for item in corrections.values()
        ),
        fuel_cost_by_depot=tuple(sorted(fuel_by_depot.items())),
        cv_emissions_by_depot=tuple(sorted(emissions_by_depot.items())),
    )


def _prefix_energy_at_terminal_load(
    route: Route,
    prefix: list[str],
    virtual_node_id: str,
    terminal_load_kg: float,
    bundle: China81Bundle,
):
    proxy_nodes = [
        (
            replace(
                node,
                node_type="c",
                demand=float(terminal_load_kg),
            )
            if node.node_id == virtual_node_id
            else node
        )
        for node in bundle.instance.nodes
    ]
    proxy_instance = replace(bundle.instance, nodes=proxy_nodes)
    return _evaluate_route(
        replace(route, node_sequence=list(prefix)),
        proxy_instance,
        {node.node_id: node for node in proxy_instance.nodes},
        bundle.prices,
    )


def _correct_dynamic_depot_profits(
    profits: Mapping[str, float],
    profit_breakdowns: Mapping[str, Any],
    correction: _DynamicPrefixAccountingTotals,
    bundle: China81Bundle,
    *,
    carbon_quota_kg: float,
) -> dict[str, float]:
    if _dynamic_correction_is_zero(correction):
        return {key: float(value) for key, value in profits.items()}
    fuel_cost = dict(correction.fuel_cost_by_depot)
    emissions_delta = dict(correction.cv_emissions_by_depot)
    corrected_emissions = {
        depot_id: float(row.emissions_kg)
        + float(emissions_delta.get(depot_id, 0.0))
        for depot_id, row in profit_breakdowns.items()
    }
    total_emissions = sum(corrected_emissions.values())
    if total_emissions < -1.0e-9:
        raise ValueError("dynamic prefix correction made emissions negative")
    total_carbon_cost = (
        0.0
        if math.isinf(float(carbon_quota_kg))
        else (total_emissions - float(carbon_quota_kg))
        * float(bundle.prices.carbon_price)
    )
    corrected: dict[str, float] = {}
    for depot_id, row in profit_breakdowns.items():
        new_carbon_cost = (
            0.0
            if total_emissions <= 1.0e-12
            else total_carbon_cost
            * corrected_emissions[depot_id]
            / total_emissions
        )
        corrected[depot_id] = (
            float(profits[depot_id])
            - float(fuel_cost.get(depot_id, 0.0))
            - (new_carbon_cost - float(row.cost_carbon))
        )
    return corrected


def _correct_dynamic_breakdown(
    breakdown: Mapping[str, float],
    correction: _DynamicPrefixAccountingTotals,
    bundle: China81Bundle,
    *,
    carbon_quota_kg: float,
) -> dict[str, float]:
    corrected = dict(breakdown)
    if _dynamic_correction_is_zero(correction):
        return corrected
    carbon_delta = (
        0.0
        if math.isinf(float(carbon_quota_kg))
        else float(correction.cv_emissions_kg)
        * float(bundle.prices.carbon_price)
    )
    corrected["fuel_liters"] += float(correction.fuel_liters)
    corrected["cost_fuel"] += float(correction.fuel_cost)
    corrected["E_cv_direct"] += float(correction.cv_emissions_kg)
    corrected["E_total"] += float(correction.cv_emissions_kg)
    corrected["ev_drive_kwh"] += float(correction.ev_drive_kwh)
    corrected["cost_carbon"] += carbon_delta
    corrected["total_cost"] += float(correction.fuel_cost) + carbon_delta
    corrected["dynamic_prefix_fuel_liters_correction"] = float(
        correction.fuel_liters
    )
    corrected["dynamic_prefix_ev_drive_kwh_correction"] = float(
        correction.ev_drive_kwh
    )
    return corrected


def _dynamic_correction_is_zero(
    correction: _DynamicPrefixAccountingTotals,
) -> bool:
    return all(
        abs(float(value)) <= 1.0e-15
        for value in (
            correction.fuel_liters,
            correction.fuel_cost,
            correction.cv_emissions_kg,
            correction.ev_drive_kwh,
        )
    )


def _measure_violations(
    violations: tuple[Violation, ...],
    prepared: Solution,
    bundle: China81Bundle,
    participation_margin: Mapping[str, float],
    *,
    charging_gap: ChargingGap = ChargingGap(),
) -> tuple[float, ...]:
    """Return native-unit magnitudes where the model exposes them exactly."""

    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    route_by_id = {route.vehicle_id: route for route in prepared.routes}
    measured: list[float] = []
    for violation in violations:
        magnitude = 1.0
        if violation.type == CAPACITY and violation.vehicle_id in route_by_id:
            volume_overload = _volume_capacity_magnitude(violation.detail)
            if volume_overload is not None:
                measured.append(volume_overload)
                continue
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
        elif violation.type == CHARGING_ENERGY_GAP:
            magnitude = float(charging_gap.missing_energy_kwh)
        elif violation.type == CHARGING_WINDOW_GAP:
            magnitude = float(charging_gap.window_shortage_seconds)
        measured.append(float(magnitude))
    return tuple(measured)


def _evaluate_with_context_cost(
    solution: Solution,
    context: DutyEvaluationContext,
    *,
    carbon_quota_kg: float,
    bundle: China81Bundle | None = None,
) -> dict[str, float]:
    """Evaluate every complete candidate with the bundle's exact costs."""

    active_bundle = context.bundle if bundle is None else bundle
    breakdown = dict(
        evaluate(
            solution,
            active_bundle.instance,
            active_bundle.time_profile,
            active_bundle.prices,
            carbon_quota_kg=carbon_quota_kg,
        )
    )
    if float(context.ev_daily_fixed_premium_cny) > 0.0:
        cv_fixed = active_bundle.instance.vehicle_fixed_cost_per_day(
            "cv",
            fallback=float(active_bundle.prices.vehicle_fixed_cost),
        )
        ev_fixed = active_bundle.instance.vehicle_fixed_cost_per_day(
            "ev",
            fallback=float(active_bundle.prices.vehicle_fixed_cost),
        )
        authority_premium = ev_fixed - cv_fixed
        configured_premium = float(context.ev_daily_fixed_premium_cny)
        if not math.isclose(
            authority_premium,
            configured_premium,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise ValueError(
                "configured EV daily fixed premium disagrees with vehicle authority"
            )
        breakdown["cost_fix_ev_premium"] = (
            float(breakdown["n_veh_ev"]) * authority_premium
        )
    return breakdown


def _rebuilt_route_constraint_violations(
    solution: Solution,
    certificate: MultiTripCertificate,
    contract: RebuiltRouteConstraintContract,
    *,
    allowed_unscheduled_route_ids: frozenset[str] = frozenset(),
) -> list[Violation]:
    """Return hard violations for every rebuilt-instance candidate route."""

    scheduled_by_route = {trip.route_id: trip for trip in certificate.trips}
    violations: list[Violation] = []
    for route in solution.routes:
        customers = tuple(
            node_id
            for node_id in route.node_sequence[1:-1]
            if node_id in contract.customer_shift_by_id
        )
        if not customers:
            continue
        shifts = {
            str(contract.customer_shift_by_id[customer_id])
            for customer_id in customers
        }
        if len(shifts) != 1:
            violations.append(
                Violation(
                    TIME_WINDOW,
                    route.vehicle_id,
                    route.home_depot_id,
                    "rebuilt route mixes customer shifts: "
                    + ", ".join(sorted(shifts)),
                )
            )
        volume = sum(
            float(contract.customer_volume_m3_by_id[customer_id])
            for customer_id in customers
        )
        capacity = float(contract.vehicle_volume_capacity_m3)
        if volume > capacity + 1.0e-9:
            violations.append(
                Violation(
                    CAPACITY,
                    route.vehicle_id,
                    route.home_depot_id,
                    f"route volume {volume:.12g} m3 > "
                    f"Q_volume={capacity:.12g} m3",
                )
            )
        if len(shifts) != 1:
            continue
        shift_id = next(iter(shifts))
        start, end = contract.shift_window_second_by_id[shift_id]
        scheduled = scheduled_by_route.get(route.vehicle_id)
        if scheduled is None:
            if route.vehicle_id in allowed_unscheduled_route_ids:
                continue
            violations.append(
                Violation(
                    TIME_WINDOW,
                    route.vehicle_id,
                    shift_id,
                    "rebuilt route has no scheduled-trip certificate",
                )
            )
            continue
        if float(scheduled.departure_second) < float(start) - 1.0e-6:
            early = float(start) - float(scheduled.departure_second)
            violations.append(
                Violation(
                    TIME_WINDOW,
                    route.vehicle_id,
                    shift_id,
                    f"departs before {shift_id} by {early:.12g} s",
                )
            )
        if float(scheduled.return_second) > float(end) + 1.0e-6:
            late = float(scheduled.return_second) - float(end)
            violations.append(
                Violation(
                    TIME_WINDOW,
                    route.vehicle_id,
                    shift_id,
                    f"returns after {shift_id} end; late by {late:.12g} s",
                )
            )
    return violations


def _volume_capacity_magnitude(detail: str) -> float | None:
    match = re.search(
        rf"route volume\s+({_NUMBER})\s+m3\s+>\s+Q_volume=({_NUMBER})\s+m3",
        detail,
    )
    if match is None:
        return None
    return max(0.0, float(match.group(1)) - float(match.group(2)))


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
