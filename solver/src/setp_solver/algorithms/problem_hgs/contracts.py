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
from typing import Any

from .evaluation import FullEvaluation
from .model import DutyIndividual


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
    RESTARTED = "RESTARTED"


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
    repair_calls: int = 0
    education_rounds: int = 0
    education_cache_hits: int = 0
    education_cache_misses: int = 0
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

    def record_outcome(self, outcome: CandidateOutcome) -> None:
        self.proposed_actions[outcome.channel] += 1
        self.wall_seconds += float(outcome.wall_seconds)
        self._record_work(outcome.work_accounting)
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
            "repair_calls": int(self.repair_calls),
            "education_rounds": int(self.education_rounds),
            "education_cache_hits": int(self.education_cache_hits),
            "education_cache_misses": int(self.education_cache_misses),
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
