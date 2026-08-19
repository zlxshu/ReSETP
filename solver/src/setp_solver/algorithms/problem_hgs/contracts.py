"""Typed search outcomes and transparent accounting.

v1 2026-08-07: separate candidate construction failures, complete-model
rejections, accepted moves, evaluation kinds, and wall-clock observation.
These are records, not scientific gates.

v2 2026-08-07: record genuine no-op actions separately from interface failures.

v3 2026-08-07: disclose cache construction and candidate assembly work instead
of allowing an "incremental" label to hide full preparation overhead.

v4 2026-08-10: aggregate the observed effect of each accepted serial action on
complete cost, carbon cost, emissions, EV assignment, and participation margin.
These are causal diagnostics of executed moves, not extra objectives or gates.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from .model import DutyIndividual

if TYPE_CHECKING:
    from .evaluation import FullEvaluation


CHARGING_ENERGY_GAP = "CHARGING_ENERGY_GAP"
CHARGING_WINDOW_GAP = "CHARGING_WINDOW_GAP"


class CandidateStatus(StrEnum):
    EVALUATED = "EVALUATED"
    NO_CHANGE = "NO_CHANGE"
    REJECTED_INTERFACE = "REJECTED_INTERFACE"
    REJECTED_CHARGING = "REJECTED_CHARGING"
    REJECTED_LOCK = "REJECTED_LOCK"
    REJECTED_REGISTRY = "REJECTED_REGISTRY"
    REPAIR_INCOMPLETE = "REPAIR_INCOMPLETE"
    SENTINEL_MISMATCH = "SENTINEL_MISMATCH"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NO_FEASIBLE_SOLUTION = "NO_FEASIBLE_SOLUTION"


class ChargingCandidateStatus(StrEnum):
    """Charging-subproblem state, separate from complete feasibility."""

    READY = "READY"
    BEST_EFFORT = "BEST_EFFORT"
    REJECTED_INTERFACE = "REJECTED_INTERFACE"
    REJECTED_CHARGING = "REJECTED_CHARGING"


@dataclass(frozen=True)
class ChargingGap:
    """Unscaled native-unit charging deficit kept as two independent terms."""

    missing_energy_kwh: float = 0.0
    window_shortage_seconds: float = 0.0

    def __post_init__(self) -> None:
        energy = float(self.missing_energy_kwh)
        window = float(self.window_shortage_seconds)
        if not math.isfinite(energy) or energy < 0.0:
            raise ValueError("charging missing energy must be finite and nonnegative")
        if not math.isfinite(window) or window < 0.0:
            raise ValueError("charging window shortage must be finite and nonnegative")
        object.__setattr__(self, "missing_energy_kwh", energy)
        object.__setattr__(self, "window_shortage_seconds", window)

    @property
    def active(self) -> bool:
        return bool(
            self.missing_energy_kwh > 0.0
            or self.window_shortage_seconds > 0.0
        )

    @property
    def values(self) -> tuple[float, float]:
        return self.missing_energy_kwh, self.window_shortage_seconds


@dataclass(frozen=True)
class ChargingClockWitness:
    """One independently replayable S1-clock row used to derive a gap."""

    duty_id: str
    route_id: str
    trip_index: int
    window_mode: str
    departure_second: float
    return_second: float
    available_window_seconds: float
    required_window_seconds: float
    energy_before_window_kwh: float
    reachable_energy_kwh: float
    required_departure_energy_kwh: float


@dataclass(frozen=True)
class ChargingGapDutyIndividual(DutyIndividual):
    """A structurally intact Duty candidate carrying a charging sidecar."""

    charging_candidate_status: ChargingCandidateStatus = (
        ChargingCandidateStatus.BEST_EFFORT
    )
    charging_gap: ChargingGap = field(default_factory=ChargingGap)
    charging_rejection_reason: str | None = None
    affected_duty_ids: tuple[str, ...] = ()
    charging_clock_witnesses: tuple[ChargingClockWitness, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        status = ChargingCandidateStatus(self.charging_candidate_status)
        affected = tuple(sorted(str(value) for value in self.affected_duty_ids))
        witnesses = tuple(self.charging_clock_witnesses)
        if status != ChargingCandidateStatus.BEST_EFFORT:
            raise ValueError("a charging-gap Duty must be BEST_EFFORT")
        if not self.charging_gap.active:
            raise ValueError("BEST_EFFORT requires a nonzero charging gap")
        if not affected:
            raise ValueError("BEST_EFFORT requires at least one affected duty")
        if not witnesses:
            raise ValueError("BEST_EFFORT requires an S1 clock witness")
        object.__setattr__(self, "charging_candidate_status", status)
        object.__setattr__(self, "affected_duty_ids", affected)
        object.__setattr__(self, "charging_clock_witnesses", witnesses)


@dataclass(frozen=True)
class ChargingRepairOutcome:
    """Typed repair return that never fabricates an unsafe candidate."""

    status: ChargingCandidateStatus
    candidate: DutyIndividual | None
    gap: ChargingGap = field(default_factory=ChargingGap)
    reason_code: str | None = None
    affected_duty_ids: tuple[str, ...] = ()
    clock_witnesses: tuple[ChargingClockWitness, ...] = ()
    error: Exception | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        status = ChargingCandidateStatus(self.status)
        affected = tuple(sorted(str(value) for value in self.affected_duty_ids))
        witnesses = tuple(self.clock_witnesses)
        if status == ChargingCandidateStatus.READY:
            if self.candidate is None or self.gap.active:
                raise ValueError("READY requires a candidate and a zero gap")
        elif status == ChargingCandidateStatus.BEST_EFFORT:
            if self.candidate is None or not self.gap.active or not witnesses:
                raise ValueError(
                    "BEST_EFFORT requires a candidate, nonzero gap, and clock witness"
                )
        elif self.candidate is not None:
            raise ValueError("a rejected charging outcome cannot carry a candidate")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "affected_duty_ids", affected)
        object.__setattr__(self, "clock_witnesses", witnesses)

    @property
    def fingerprint(self) -> str | None:
        return None if self.candidate is None else self.candidate.fingerprint


@dataclass(frozen=True)
class CandidateOutcome:
    action_id: str
    channel: str
    status: CandidateStatus
    changed_duty_ids: frozenset[str]
    candidate: DutyIndividual | None = None
    evaluation: FullEvaluation | None = None
    error_type: str | None = None
    error: str | None = None
    charging_rejection_reason: str | None = None
    wall_seconds: float = 0.0
    work_accounting: Mapping[str, int] = field(default_factory=dict)
    charging_candidate_status: ChargingCandidateStatus | None = None
    charging_gap: ChargingGap | None = None
    charging_clock_witnesses: tuple[ChargingClockWitness, ...] = ()

    def __post_init__(self) -> None:
        evaluation = self.evaluation
        candidate = self.candidate
        status = self.charging_candidate_status
        gap = self.charging_gap
        witnesses = tuple(self.charging_clock_witnesses)
        if evaluation is not None:
            status = status or getattr(
                evaluation,
                "charging_candidate_status",
                None,
            )
            gap = gap or getattr(evaluation, "charging_gap", None)
            witnesses = witnesses or tuple(
                getattr(evaluation, "charging_clock_witnesses", ())
            )
        if isinstance(candidate, ChargingGapDutyIndividual):
            status = status or candidate.charging_candidate_status
            gap = gap or candidate.charging_gap
            witnesses = witnesses or candidate.charging_clock_witnesses
        if status is not None:
            status = ChargingCandidateStatus(status)
        object.__setattr__(self, "charging_candidate_status", status)
        object.__setattr__(self, "charging_gap", gap)
        object.__setattr__(self, "charging_clock_witnesses", witnesses)

    @property
    def evaluated(self) -> bool:
        return self.status == CandidateStatus.EVALUATED

    @property
    def no_change(self) -> bool:
        return self.status == CandidateStatus.NO_CHANGE


@dataclass
class SearchAccounting:
    """Counts observed work without declaring any result successful."""

    proposed_actions: Counter[str] = field(default_factory=Counter)
    evaluated_actions: Counter[str] = field(default_factory=Counter)
    accepted_actions: Counter[str] = field(default_factory=Counter)
    accepted_cost_reduction: Counter[str] = field(default_factory=Counter)
    accepted_carbon_cost_reduction: Counter[str] = field(default_factory=Counter)
    accepted_emissions_reduction: Counter[str] = field(default_factory=Counter)
    accepted_ev_customer_delta: Counter[str] = field(default_factory=Counter)
    accepted_minimum_margin_delta: Counter[str] = field(default_factory=Counter)
    rejected_actions: Counter[str] = field(default_factory=Counter)
    charging_rejection_reasons: Counter[str] = field(default_factory=Counter)
    charging_candidate_statuses: Counter[str] = field(default_factory=Counter)
    charging_gap_ledger: list[dict[str, Any]] = field(default_factory=list)
    charging_gap_a2_evaluations: int = 0
    charging_gap_a2_violation_counts: Counter[str] = field(
        default_factory=Counter
    )
    no_change_actions: Counter[str] = field(default_factory=Counter)
    full_evaluations: int = 0
    initialization_full_evaluations: int = 0
    incremental_evaluations: int = 0
    sentinel_evaluations: int = 0
    cache_seedings: int = 0
    duty_slice_preparations: int = 0
    candidate_assemblies: int = 0
    crossover_calls: int = 0
    crossover_actions: Counter[str] = field(default_factory=Counter)
    crossover_work_units: Counter[str] = field(default_factory=Counter)
    route_layer_proposed: int = 0
    route_layer_decoded: int = 0
    route_layer_entered_evaluation: int = 0
    route_layer_accepted: int = 0
    route_layer_decode_wall_seconds: float = 0.0
    route_layer_gap_counts: Counter[str] = field(default_factory=Counter)
    repair_calls: int = 0
    outer_refinement_calls: int = 0
    education_rounds: int = 0
    education_depth_cap_triggers: int = 0
    education_depth_cap_triggers_while_improving: int = 0
    education_cache_hits: int = 0
    education_cache_misses: int = 0
    truth_shortlist_batches: int = 0
    truth_shortlist_exact_evaluations: int = 0
    truth_shortlist_accepted: int = 0
    truth_reselections: int = 0
    truth_reselection_reasons: Counter[str] = field(default_factory=Counter)
    truth_winner_proxy_ranks: Counter[int] = field(default_factory=Counter)
    charging_repair_cache_hits: int = 0
    charging_repair_cache_misses: int = 0
    population_admission_attempts: int = 0
    population_admissions: int = 0
    restarts: int = 0
    wall_seconds: float = 0.0
    run_wall_seconds: float = 0.0
    initialization_wall_seconds: float = 0.0
    schedule_oracle_calls: int = 0
    schedule_oracle_cache_hits: int = 0
    schedule_oracle_cache_misses: int = 0
    schedule_oracle_statuses: Counter[str] = field(default_factory=Counter)
    schedule_oracle_failure_reasons: Counter[str] = field(default_factory=Counter)
    schedule_oracle_wall_seconds_samples: list[float] = field(default_factory=list)
    schedule_oracle_cache_hit_wall_seconds_samples: list[float] = field(default_factory=list)
    schedule_oracle_cache_miss_wall_seconds_samples: list[float] = field(default_factory=list)
    schedule_oracle_event_counts: list[int] = field(default_factory=list)
    schedule_oracle_labels_generated: int = 0
    schedule_oracle_labels_pruned: int = 0
    schedule_oracle_slot_pricing_calls: int = 0
    schedule_oracle_curve_transitions: int = 0
    schedule_oracle_pricing_mismatches: int = 0
    schedule_oracle_frontier_sizes: list[int] = field(default_factory=list)
    schedule_oracle_frontier_cache_bytes: int = 0
    scheduled_changed_duty_counts: Counter[int] = field(default_factory=Counter)
    schedule_coordinator_calls: int = 0
    schedule_coordinator_cache_hits: int = 0
    schedule_coordinator_cache_misses: int = 0
    schedule_coordinator_combinations_attempted: int = 0
    schedule_coordinator_capacity_prunes: int = 0
    schedule_coordinator_full_candidates: int = 0
    schedule_coordinator_statuses: Counter[str] = field(default_factory=Counter)
    schedule_coordinator_wall_seconds_samples: list[float] = field(default_factory=list)
    schedule_rescued_candidates_by_channel: Counter[str] = field(default_factory=Counter)
    schedule_rejected_candidates_by_channel_and_status: Counter[str] = field(default_factory=Counter)
    penalty_manager: Any | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def record_outcome(self, outcome: CandidateOutcome) -> None:
        self.proposed_actions[outcome.channel] += 1
        self.wall_seconds += float(outcome.wall_seconds)
        self._record_work(outcome.work_accounting)
        if outcome.charging_candidate_status is not None:
            self.charging_candidate_statuses[
                outcome.charging_candidate_status.value
            ] += 1
        if outcome.charging_gap is not None and outcome.charging_gap.active:
            self.charging_gap_ledger.append(
                {
                    "action_id": str(outcome.action_id),
                    "channel": str(outcome.channel),
                    "candidate_status": (
                        None
                        if outcome.charging_candidate_status is None
                        else outcome.charging_candidate_status.value
                    ),
                    "complete_feasible": (
                        None
                        if outcome.evaluation is None
                        else bool(outcome.evaluation.feasible)
                    ),
                    "candidate_fingerprint": (
                        None
                        if outcome.candidate is None
                        else outcome.candidate.fingerprint
                    ),
                    "missing_energy_kwh": float(
                        outcome.charging_gap.missing_energy_kwh
                    ),
                    "window_shortage_seconds": float(
                        outcome.charging_gap.window_shortage_seconds
                    ),
                    "charging_rejection_reason": (
                        outcome.charging_rejection_reason
                        or getattr(
                            outcome.evaluation,
                            "charging_rejection_reason",
                            None,
                        )
                    ),
                }
            )
            if outcome.evaluation is not None:
                gap_types = Counter(
                    violation.type
                    for violation in outcome.evaluation.violations
                    if violation.type
                    in {CHARGING_ENERGY_GAP, CHARGING_WINDOW_GAP}
                )
                if gap_types:
                    self.charging_gap_a2_evaluations += 1
                    self.charging_gap_a2_violation_counts.update(gap_types)
        if outcome.evaluated:
            self.evaluated_actions[outcome.channel] += 1
            if outcome.evaluation is not None:
                self._record_work(outcome.evaluation.accounting)
        elif outcome.no_change:
            self.no_change_actions[outcome.channel] += 1
        else:
            self.rejected_actions[
                f"{outcome.channel}:{outcome.status.value}"
            ] += 1
            if outcome.status == CandidateStatus.REJECTED_CHARGING:
                reason = (
                    "CHARGING_REPAIR_OTHER"
                    if outcome.charging_rejection_reason is None
                    else str(outcome.charging_rejection_reason)
                )
                self.charging_rejection_reasons[
                    f"{outcome.channel}:{reason}"
                ] += 1

    def record_acceptance(self, channel: str) -> None:
        self.accepted_actions[channel] += 1

    def record_truth_shortlist_batch(self, exact_evaluations: int) -> None:
        self.truth_shortlist_batches += 1
        self.truth_shortlist_exact_evaluations += int(exact_evaluations)

    def record_truth_shortlist_acceptance(
        self,
        *,
        proxy_rank: int,
        reselection_reason: str | None,
    ) -> None:
        self.truth_shortlist_accepted += 1
        self.truth_winner_proxy_ranks[int(proxy_rank)] += 1
        if reselection_reason is not None:
            self.truth_reselections += 1
            self.truth_reselection_reasons[str(reselection_reason)] += 1

    def record_accepted_effect(
        self,
        channel: str,
        before: DutyIndividual,
        before_evaluation: FullEvaluation,
        after: DutyIndividual,
        after_evaluation: FullEvaluation,
    ) -> None:
        """Summarise what one accepted action actually changed."""

        self.accepted_cost_reduction[channel] += float(
            before_evaluation.total_cost
        ) - float(after_evaluation.total_cost)
        self._record_breakdown_reduction(
            self.accepted_carbon_cost_reduction,
            channel,
            before_evaluation,
            after_evaluation,
            "cost_carbon",
        )
        self._record_breakdown_reduction(
            self.accepted_emissions_reduction,
            channel,
            before_evaluation,
            after_evaluation,
            "E_total",
        )
        self.accepted_ev_customer_delta[channel] += (
            _ev_customer_count(after) - _ev_customer_count(before)
        )
        if (
            before_evaluation.participation_margin
            and after_evaluation.participation_margin
        ):
            self.accepted_minimum_margin_delta[channel] += (
                min(
                    float(value)
                    for value in after_evaluation.participation_margin.values()
                )
                - min(
                    float(value)
                    for value in before_evaluation.participation_margin.values()
                )
            )

    @staticmethod
    def _record_breakdown_reduction(
        target: Counter[str],
        channel: str,
        before: FullEvaluation,
        after: FullEvaluation,
        key: str,
    ) -> None:
        if key in before.breakdown and key in after.breakdown:
            target[channel] += float(before.breakdown[key]) - float(
                after.breakdown[key]
            )

    def record_cache_seed(self, duty_slice_count: int) -> None:
        count = int(duty_slice_count)
        if count > 0:
            self.cache_seedings += 1
            self.duty_slice_preparations += count

    def record_education_depth_cap(self, *, still_improving: bool) -> None:
        """Record that a child stopped because its education cap was reached."""

        self.education_depth_cap_triggers += 1
        if still_improving:
            self.education_depth_cap_triggers_while_improving += 1

    def record_population_admission(self, *, inserted: bool) -> None:
        """Record retention without recounting the candidate's evaluation work."""

        self.population_admission_attempts += 1
        if inserted:
            self.population_admissions += 1
            self.record_acceptance("hgs_population")

    def record_schedule_oracle_result(self, result: Any) -> None:
        """Merge one prototype Oracle call without turning it into a gate."""

        self.schedule_oracle_calls += 1
        elapsed = float(result.wall_seconds)
        self.schedule_oracle_wall_seconds_samples.append(elapsed)
        if bool(result.cache_hit):
            self.schedule_oracle_cache_hits += 1
            self.schedule_oracle_cache_hit_wall_seconds_samples.append(elapsed)
        else:
            self.schedule_oracle_cache_misses += 1
            self.schedule_oracle_cache_miss_wall_seconds_samples.append(elapsed)
        status = str(getattr(result.status, "value", result.status))
        self.schedule_oracle_statuses[status] += 1
        if result.failure_reason:
            self.schedule_oracle_failure_reasons[str(result.failure_reason)] += 1
        accounting = dict(result.accounting)
        self.schedule_oracle_event_counts.append(
            int(accounting.get("schedule_oracle_event_count", 0))
        )
        self.schedule_oracle_labels_generated += int(
            accounting.get("schedule_oracle_labels_generated", 0)
        )
        self.schedule_oracle_labels_pruned += int(
            accounting.get("schedule_oracle_labels_pruned", 0)
        )
        self.schedule_oracle_slot_pricing_calls += int(
            accounting.get("schedule_oracle_slot_pricing_calls", 0)
        )
        self.schedule_oracle_curve_transitions += int(
            accounting.get("schedule_oracle_curve_transitions", 0)
        )
        self.schedule_oracle_pricing_mismatches += int(
            accounting.get("schedule_oracle_pricing_mismatches", 0)
        )
        self.schedule_oracle_frontier_sizes.append(len(result.frontier))

    def record_schedule_coordinator_result(
        self,
        result: Any,
        *,
        changed_duty_count: int,
    ) -> None:
        self.schedule_coordinator_calls += 1
        self.schedule_coordinator_wall_seconds_samples.append(
            float(result.wall_seconds)
        )
        self.scheduled_changed_duty_counts[int(changed_duty_count)] += 1
        status = str(getattr(result.status, "value", result.status))
        self.schedule_coordinator_statuses[status] += 1
        accounting = dict(result.accounting)
        self.schedule_coordinator_combinations_attempted += int(
            accounting.get("schedule_coordinator_combinations_attempted", 0)
        )
        self.schedule_coordinator_capacity_prunes += int(
            accounting.get("schedule_coordinator_capacity_prunes", 0)
        )
        self.schedule_coordinator_full_candidates += int(
            accounting.get("schedule_coordinator_full_candidates", 0)
        )

    def record_crossover(self, action: str, work_units: int) -> None:
        work = int(work_units)
        if work < 1:
            raise ValueError("crossover work units must be positive")
        self.crossover_actions[str(action)] += 1
        self.crossover_work_units[str(action)] += work

    def record_route_layer_decode(self, outcome: Any) -> None:
        """Record raw Split decoding separately from full evaluation."""

        self.route_layer_proposed += 1
        self.route_layer_decode_wall_seconds += float(
            getattr(outcome, "wall_seconds", 0.0)
        )
        if getattr(outcome, "candidate", None) is not None:
            self.route_layer_decoded += 1
        for gap in getattr(outcome, "gaps", ()):
            kind = getattr(gap, "kind", "UNKNOWN")
            self.route_layer_gap_counts[str(getattr(kind, "value", kind))] += 1

    def record_route_layer_evaluation(self) -> None:
        self.route_layer_entered_evaluation += 1

    def record_route_layer_acceptance(self) -> None:
        self.route_layer_accepted += 1

    def _record_work(self, accounting: Mapping[str, int]) -> None:
        self.full_evaluations += int(accounting.get("full_evaluations", 0))
        self.incremental_evaluations += int(
            accounting.get("incremental_evaluations", 0)
        )
        self.sentinel_evaluations += int(
            accounting.get("sentinel_evaluations", 0)
        )
        self.cache_seedings += int(accounting.get("cache_seedings", 0))
        self.duty_slice_preparations += int(
            accounting.get("duty_slice_preparations", 0)
        )
        self.candidate_assemblies += int(
            accounting.get("candidate_assemblies", 0)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposed_actions": dict(sorted(self.proposed_actions.items())),
            "evaluated_actions": dict(sorted(self.evaluated_actions.items())),
            "accepted_actions": dict(sorted(self.accepted_actions.items())),
            "accepted_cost_reduction": dict(
                sorted(self.accepted_cost_reduction.items())
            ),
            "accepted_carbon_cost_reduction": dict(
                sorted(self.accepted_carbon_cost_reduction.items())
            ),
            "accepted_emissions_reduction": dict(
                sorted(self.accepted_emissions_reduction.items())
            ),
            "accepted_ev_customer_delta": dict(
                sorted(self.accepted_ev_customer_delta.items())
            ),
            "accepted_minimum_margin_delta": dict(
                sorted(self.accepted_minimum_margin_delta.items())
            ),
            "rejected_actions": dict(sorted(self.rejected_actions.items())),
            "charging_rejection_reasons": dict(
                sorted(self.charging_rejection_reasons.items())
            ),
            "charging_candidate_statuses": dict(
                sorted(self.charging_candidate_statuses.items())
            ),
            "charging_gap_ledger": list(self.charging_gap_ledger),
            "charging_gap_a2_evaluations": int(
                self.charging_gap_a2_evaluations
            ),
            "charging_gap_a2_violation_counts": dict(
                sorted(self.charging_gap_a2_violation_counts.items())
            ),
            "no_change_actions": dict(sorted(self.no_change_actions.items())),
            "full_evaluations": int(self.full_evaluations),
            "initialization_full_evaluations": int(
                self.initialization_full_evaluations
            ),
            "incremental_evaluations": int(self.incremental_evaluations),
            "sentinel_evaluations": int(self.sentinel_evaluations),
            "actual_full_model_evaluations": int(
                self.full_evaluations + self.sentinel_evaluations
            ),
            "cache_seedings": int(self.cache_seedings),
            "duty_slice_preparations": int(
                self.duty_slice_preparations
            ),
            "candidate_assemblies": int(self.candidate_assemblies),
            "crossover_calls": int(self.crossover_calls),
            "crossover_actions": dict(sorted(self.crossover_actions.items())),
            "crossover_work_units": dict(
                sorted(self.crossover_work_units.items())
            ),
            "route_layer_proposed": int(self.route_layer_proposed),
            "route_layer_decoded": int(self.route_layer_decoded),
            "route_layer_entered_evaluation": int(
                self.route_layer_entered_evaluation
            ),
            "route_layer_accepted": int(self.route_layer_accepted),
            "route_layer_decode_wall_seconds": float(
                self.route_layer_decode_wall_seconds
            ),
            "route_layer_gap_counts": dict(
                sorted(self.route_layer_gap_counts.items())
            ),
            "repair_calls": int(self.repair_calls),
            "outer_refinement_calls": int(self.outer_refinement_calls),
            "education_rounds": int(self.education_rounds),
            "education_depth_cap_triggers": int(
                self.education_depth_cap_triggers
            ),
            "education_depth_cap_triggers_while_improving": int(
                self.education_depth_cap_triggers_while_improving
            ),
            "education_cache_hits": int(self.education_cache_hits),
            "education_cache_misses": int(self.education_cache_misses),
            "charging_repair_cache_hits": int(
                self.charging_repair_cache_hits
            ),
            "charging_repair_cache_misses": int(
                self.charging_repair_cache_misses
            ),
            "population_admission_attempts": int(
                self.population_admission_attempts
            ),
            "population_admissions": int(self.population_admissions),
            "restarts": int(self.restarts),
            "wall_seconds": float(self.wall_seconds),
            "run_wall_seconds": float(self.run_wall_seconds),
            "initialization_wall_seconds": float(
                self.initialization_wall_seconds
            ),
            "total_algorithm_wall_seconds": float(
                self.initialization_wall_seconds + self.run_wall_seconds
            ),
            "schedule_oracle_calls": int(self.schedule_oracle_calls),
            "schedule_oracle_cache_hits": int(self.schedule_oracle_cache_hits),
            "schedule_oracle_cache_misses": int(self.schedule_oracle_cache_misses),
            "schedule_oracle_statuses": dict(sorted(self.schedule_oracle_statuses.items())),
            "schedule_oracle_failure_reasons": dict(
                sorted(self.schedule_oracle_failure_reasons.items())
            ),
            "schedule_oracle_wall_seconds": _sample_summary(
                self.schedule_oracle_wall_seconds_samples
            ),
            "schedule_oracle_cache_hit_wall_seconds": _sample_summary(
                self.schedule_oracle_cache_hit_wall_seconds_samples
            ),
            "schedule_oracle_cache_miss_wall_seconds": _sample_summary(
                self.schedule_oracle_cache_miss_wall_seconds_samples
            ),
            "schedule_oracle_event_counts": _sample_summary(
                self.schedule_oracle_event_counts
            ),
            "schedule_oracle_labels_generated": int(
                self.schedule_oracle_labels_generated
            ),
            "schedule_oracle_labels_pruned": int(
                self.schedule_oracle_labels_pruned
            ),
            "schedule_oracle_slot_pricing_calls": int(
                self.schedule_oracle_slot_pricing_calls
            ),
            "schedule_oracle_curve_transitions": int(
                self.schedule_oracle_curve_transitions
            ),
            "schedule_oracle_pricing_mismatches": int(
                self.schedule_oracle_pricing_mismatches
            ),
            "schedule_oracle_frontier_sizes": _sample_summary(
                self.schedule_oracle_frontier_sizes
            ),
            "schedule_oracle_frontier_cache_bytes": int(
                self.schedule_oracle_frontier_cache_bytes
            ),
            "scheduled_changed_duty_counts": {
                str(key): int(value)
                for key, value in sorted(self.scheduled_changed_duty_counts.items())
            },
            "schedule_coordinator_calls": int(self.schedule_coordinator_calls),
            "schedule_coordinator_cache_hits": int(
                self.schedule_coordinator_cache_hits
            ),
            "schedule_coordinator_cache_misses": int(
                self.schedule_coordinator_cache_misses
            ),
            "schedule_coordinator_combinations_attempted": int(
                self.schedule_coordinator_combinations_attempted
            ),
            "schedule_coordinator_capacity_prunes": int(
                self.schedule_coordinator_capacity_prunes
            ),
            "schedule_coordinator_full_candidates": int(
                self.schedule_coordinator_full_candidates
            ),
            "schedule_coordinator_statuses": dict(
                sorted(self.schedule_coordinator_statuses.items())
            ),
            "schedule_coordinator_wall_seconds": _sample_summary(
                self.schedule_coordinator_wall_seconds_samples
            ),
            "schedule_rescued_candidates_by_channel": dict(
                sorted(self.schedule_rescued_candidates_by_channel.items())
            ),
            "schedule_rejected_candidates_by_channel_and_status": dict(
                sorted(
                    self.schedule_rejected_candidates_by_channel_and_status.items()
                )
            ),
            "penalty_adaptation": (
                None
                if self.penalty_manager is None
                else self.penalty_manager.telemetry()
            ),
        }


def _sample_summary(values: list[float] | list[int]) -> dict[str, float | int | None]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {
            "samples": 0,
            "p50": None,
            "p95": None,
            "p99": None,
            "max": None,
        }

    def percentile(probability: float) -> float:
        index = int(math.ceil(probability * len(ordered))) - 1
        return ordered[max(0, min(len(ordered) - 1, index))]

    return {
        "samples": len(ordered),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": ordered[-1],
    }


def _ev_customer_count(individual: DutyIndividual) -> int:
    return sum(
        len(trip.customer_ids)
        for duty in individual.duties
        if duty.vehicle_type == "ev"
        for trip in duty.trips
    )


@dataclass(frozen=True)
class TrajectoryRow:
    iteration: int
    phase: str
    arm: str
    action_id: str
    channel: str
    status: str
    accepted: bool
    before_fingerprint: str
    after_fingerprint: str | None
    before_cost: float | None
    after_cost: float | None
    before_violations: int | None
    after_violations: int | None
    before_carbon_cost: float | None
    after_carbon_cost: float | None
    before_emissions_kg: float | None
    after_emissions_kg: float | None
    participation_margin_before: tuple[tuple[str, float], ...]
    participation_margin_after: tuple[tuple[str, float], ...] | None
    minimum_participation_margin_before: float | None
    minimum_participation_margin_after: float | None
    error_type: str | None = None
    error: str | None = None
