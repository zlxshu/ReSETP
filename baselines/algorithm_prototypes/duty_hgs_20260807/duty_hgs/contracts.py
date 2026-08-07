"""Typed search outcomes and transparent accounting.

v1 2026-08-07: separate candidate construction failures, complete-model
rejections, accepted moves, evaluation kinds, and wall-clock observation.
These are records, not scientific gates.

v2 2026-08-07: record genuine no-op actions separately from interface failures.

v3 2026-08-07: disclose cache construction and candidate assembly work instead
of allowing an "incremental" label to hide full preparation overhead.
"""

from __future__ import annotations

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
    rejected_actions: Counter[str] = field(default_factory=Counter)
    no_change_actions: Counter[str] = field(default_factory=Counter)
    full_evaluations: int = 0
    incremental_evaluations: int = 0
    sentinel_evaluations: int = 0
    cache_seedings: int = 0
    duty_slice_preparations: int = 0
    candidate_assemblies: int = 0
    crossover_calls: int = 0
    repair_calls: int = 0
    education_rounds: int = 0
    population_admission_attempts: int = 0
    population_admissions: int = 0
    restarts: int = 0
    wall_seconds: float = 0.0
    run_wall_seconds: float = 0.0

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

    def record_acceptance(self, channel: str) -> None:
        self.accepted_actions[channel] += 1

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
            "rejected_actions": dict(sorted(self.rejected_actions.items())),
            "no_change_actions": dict(sorted(self.no_change_actions.items())),
            "full_evaluations": int(self.full_evaluations),
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
            "repair_calls": int(self.repair_calls),
            "education_rounds": int(self.education_rounds),
            "population_admission_attempts": int(
                self.population_admission_attempts
            ),
            "population_admissions": int(self.population_admissions),
            "restarts": int(self.restarts),
            "wall_seconds": float(self.wall_seconds),
            "run_wall_seconds": float(self.run_wall_seconds),
        }


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
    minimum_participation_margin_before: float | None
    minimum_participation_margin_after: float | None
    error_type: str | None = None
    error: str | None = None
