"""Runnable isolated Duty-HGS search.

v1 2026-08-07: join the independently implemented HGS population/control
backbone with whole-duty SREX, regret repair, charging-safe best-improvement
education, complete truth sentinels, and transparent trajectory accounting.
The caller supplies every numerical parameter and the stopping policy.

v2 2026-08-07: reuse the repair phase's verified evaluation when education
starts, so the same child is not fully evaluated twice without disclosure.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Callable
from dataclasses import asdict, dataclass
from time import perf_counter

from .charging import ChargingRepairPolicy, repair_changed_duties
from .contracts import (
    CandidateOutcome,
    CandidateStatus,
    SearchAccounting,
    TrajectoryRow,
)
from .crossover import selective_duty_exchange
from .education import (
    DutySentinelMismatch,
    _trajectory_row,
    educate_best_improvement,
)
from .evaluation import DutyFullEvaluator, FullEvaluation
from .model import DutyIndividual
from .population import (
    AdaptivePenaltyManager,
    DutyPopulation,
    EvaluatedDutyCandidate,
    PenaltyParameters,
    PopulationParameters,
)
from .repair import regret2_repair


@dataclass(frozen=True)
class DutyHGSSearchParameters:
    random_seed: int
    population: PopulationParameters
    penalties: PenaltyParameters
    restart_after_iterations_without_improvement: int

    def __post_init__(self) -> None:
        if self.restart_after_iterations_without_improvement < 1:
            raise ValueError("restart interval must be positive")


@dataclass(frozen=True)
class FrozenPopulationIdentity:
    """Reproducible identity of the supplied initial population."""

    source_id: str
    value_sha256: str

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("initial population source_id cannot be empty")
        if len(self.value_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.value_sha256.lower()
        ):
            raise ValueError(
                "initial population value_sha256 must be a SHA-256 hex digest"
            )


@dataclass(frozen=True)
class DutyHGSSearchState:
    iterations: int
    iterations_without_improvement: int
    best_cost: float | None
    full_evaluations: int
    incremental_evaluations: int
    sentinel_evaluations: int
    actual_full_model_evaluations: int
    duty_slice_preparations: int
    candidate_assemblies: int


@dataclass(frozen=True)
class DutyHGSRunResult:
    best: DutyIndividual
    best_evaluation: FullEvaluation
    iterations: int
    accounting: SearchAccounting
    trajectory: tuple[TrajectoryRow, ...]
    provenance: DutyHGSRunProvenance
    termination_status: str
    termination_error_type: str | None = None
    termination_error: str | None = None


@dataclass(frozen=True)
class DutyHGSRunProvenance:
    """Inputs that identify one run without claiming a scientific result."""

    arm: str
    instance_id: str
    random_seed: int
    search_configuration_sha256: str
    initial_population_source_id: str
    initial_population_sha256: str
    independent_profit_source_id: str
    independent_profit_sha256: str
    independent_profit_externally_frozen: bool
    incremental_full_truth_sentinel_enabled: bool


def run_duty_hgs(
    initial_candidates: tuple[DutyIndividual, ...],
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    parameters: DutyHGSSearchParameters,
    initial_population_identity: FrozenPopulationIdentity,
    stop: Callable[[DutyHGSSearchState], bool],
    arm: str,
) -> DutyHGSRunResult:
    """Run Duty-HGS until the external, user-approved stop callable fires."""

    started = perf_counter()
    if not initial_candidates:
        raise ValueError("Duty-HGS requires at least one initial candidate")
    if initial_population_identity.value_sha256.lower() != population_sha256(
        initial_candidates
    ):
        raise ValueError(
            "initial candidates disagree with their frozen population identity"
        )
    provenance = DutyHGSRunProvenance(
        arm=str(arm),
        instance_id=str(evaluator.context.bundle.instance_id),
        random_seed=int(parameters.random_seed),
        search_configuration_sha256=search_configuration_sha256(
            parameters,
            charging_policy,
            arm=arm,
        ),
        initial_population_source_id=initial_population_identity.source_id,
        initial_population_sha256=initial_population_identity.value_sha256.lower(),
        independent_profit_source_id=(
            evaluator.context.independent_profit_identity.source_id
        ),
        independent_profit_sha256=(
            evaluator.context.independent_profit_identity.value_sha256.lower()
        ),
        independent_profit_externally_frozen=(
            evaluator.context.independent_profit_identity.externally_frozen
        ),
        incremental_full_truth_sentinel_enabled=True,
    )
    rng = random.Random(int(parameters.random_seed))
    accounting = SearchAccounting()
    penalty_manager = AdaptivePenaltyManager(parameters.penalties)
    population = DutyPopulation(parameters.population, penalty_manager)
    initial_records = []
    for candidate in initial_candidates:
        evaluation = evaluator.evaluate(candidate)
        accounting.full_evaluations += 1
        initial_records.append(population.add(candidate, evaluation).candidate)
    best = population.best_feasible() or population.best_penalized()
    if best is None:
        raise AssertionError("non-empty initial population was not retained")

    trajectory: list[TrajectoryRow] = []
    iterations = 0
    no_improvement = 0
    while not stop(
        DutyHGSSearchState(
            iterations=iterations,
            iterations_without_improvement=no_improvement,
            best_cost=(
                float(best.evaluation.total_cost)
                if best.evaluation.feasible
                else None
            ),
            full_evaluations=accounting.full_evaluations,
            incremental_evaluations=accounting.incremental_evaluations,
            sentinel_evaluations=accounting.sentinel_evaluations,
            actual_full_model_evaluations=(
                accounting.full_evaluations + accounting.sentinel_evaluations
            ),
            duty_slice_preparations=accounting.duty_slice_preparations,
            candidate_assemblies=accounting.candidate_assemblies,
        )
    ):
        if (
            no_improvement
            >= parameters.restart_after_iterations_without_improvement
        ):
            population.clear()
            for record in (*initial_records, best):
                population.add(record.individual, record.evaluation)
            restarted = CandidateOutcome(
                action_id="population-restart",
                channel="hgs_control",
                status=CandidateStatus.RESTARTED,
                changed_duty_ids=frozenset(),
                candidate=best.individual,
                evaluation=best.evaluation,
            )
            trajectory.append(
                _trajectory_row(
                    iteration=iterations,
                    phase="control",
                    arm=arm,
                    before=best.individual,
                    before_evaluation=best.evaluation,
                    outcome=restarted,
                    accepted=True,
                )
            )
            no_improvement = 0
            accounting.restarts += 1

        left, right = population.select(rng)
        accounting.crossover_calls += 1
        try:
            crossed = selective_duty_exchange(
                (left.individual, right.individual),
                rng,
            )
        except (TypeError, ValueError) as exc:
            rejected = CandidateOutcome(
                action_id="selective-duty-exchange",
                channel="duty_crossover",
                status=_crossover_rejection_status(exc),
                changed_duty_ids=frozenset(),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            accounting.record_outcome(rejected)
            trajectory.append(
                _trajectory_row(
                    iteration=iterations,
                    phase="crossover",
                    arm=arm,
                    before=right.individual,
                    before_evaluation=right.evaluation,
                    outcome=rejected,
                    accepted=False,
                )
            )
            iterations += 1
            no_improvement += 1
            continue
        try:
            child = repair_changed_duties(
                right.individual,
                crossed.child,
                changed_duty_ids=set(crossed.changed_duty_ids),
                context=evaluator.context,
                policy=charging_policy,
            )
        except (TypeError, ValueError) as exc:
            rejected = CandidateOutcome(
                action_id="selective-duty-exchange",
                channel="duty_crossover",
                status=CandidateStatus.REJECTED_CHARGING,
                changed_duty_ids=crossed.changed_duty_ids,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            accounting.record_outcome(rejected)
            trajectory.append(
                _trajectory_row(
                    iteration=iterations,
                    phase="crossover",
                    arm=arm,
                    before=right.individual,
                    before_evaluation=right.evaluation,
                    outcome=rejected,
                    accepted=False,
                )
            )
            iterations += 1
            no_improvement += 1
            continue

        try:
            child_evaluation = evaluator.evaluate(child)
        except (TypeError, ValueError) as exc:
            rejected = CandidateOutcome(
                action_id="selective-duty-exchange",
                channel="duty_crossover",
                status=CandidateStatus.REJECTED_INTERFACE,
                changed_duty_ids=crossed.changed_duty_ids,
                candidate=child,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            accounting.record_outcome(rejected)
            trajectory.append(
                _trajectory_row(
                    iteration=iterations,
                    phase="crossover",
                    arm=arm,
                    before=right.individual,
                    before_evaluation=right.evaluation,
                    outcome=rejected,
                    accepted=False,
                )
            )
            iterations += 1
            no_improvement += 1
            continue
        constructed = CandidateOutcome(
            action_id="selective-duty-exchange",
            channel="duty_crossover",
            status=CandidateStatus.EVALUATED,
            changed_duty_ids=crossed.changed_duty_ids,
            candidate=child,
            evaluation=child_evaluation,
        )
        accounting.record_outcome(constructed)
        trajectory.append(
            _trajectory_row(
                iteration=iterations,
                phase="crossover",
                arm=arm,
                before=right.individual,
                before_evaluation=right.evaluation,
                outcome=constructed,
                accepted=False,
            )
        )
        try:
            repaired, repaired_evaluation, repair_rows = regret2_repair(
                child,
                evaluator=evaluator,
                charging_policy=charging_policy,
                arm=arm,
                iteration=iterations,
                accounting=accounting,
                penalized_cost=penalty_manager.cost,
                initial_evaluation=child_evaluation,
            )
        except DutySentinelMismatch as exc:
            trajectory.extend(exc.rows)
            return _finish_result(
                best,
                iterations,
                accounting,
                trajectory,
                started,
                provenance,
                status=CandidateStatus.SENTINEL_MISMATCH.value,
                error=exc,
            )
        except (AssertionError, RuntimeError, TypeError, ValueError) as exc:
            failed = CandidateOutcome(
                action_id="regret2-repair",
                channel="regret_insert",
                status=CandidateStatus.INTERNAL_ERROR,
                changed_duty_ids=frozenset(
                    duty.physical_vehicle_id for duty in child.duties
                ),
                candidate=child,
                evaluation=child_evaluation,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            accounting.record_outcome(failed)
            trajectory.append(
                _trajectory_row(
                    iteration=iterations,
                    phase="regret2_repair",
                    arm=arm,
                    before=child,
                    before_evaluation=child_evaluation,
                    outcome=failed,
                    accepted=False,
                )
            )
            return _finish_result(
                best,
                iterations,
                accounting,
                trajectory,
                started,
                provenance,
                status=CandidateStatus.INTERNAL_ERROR.value,
                error=exc,
            )
        trajectory.extend(repair_rows)
        if repaired.unserved_customers:
            incomplete = CandidateOutcome(
                action_id="regret2-repair-incomplete",
                channel="regret_insert",
                status=CandidateStatus.REPAIR_INCOMPLETE,
                changed_duty_ids=frozenset(
                    duty.physical_vehicle_id for duty in repaired.duties
                ),
                candidate=repaired,
                evaluation=repaired_evaluation,
                error=(
                    "unserved customers remain: "
                    + ", ".join(repaired.unserved_customers)
                ),
            )
            accounting.record_outcome(incomplete)
            trajectory.append(
                _trajectory_row(
                    iteration=iterations,
                    phase="regret2_repair",
                    arm=arm,
                    before=child,
                    before_evaluation=child_evaluation,
                    outcome=incomplete,
                    accepted=False,
                )
            )
            iterations += 1
            no_improvement += 1
            continue
        try:
            educated, educated_evaluation, education_rows = (
                educate_best_improvement(
                    repaired,
                    evaluator=evaluator,
                    charging_policy=charging_policy,
                    arm=arm,
                    iteration=iterations,
                    accounting=accounting,
                    penalized_cost=penalty_manager.cost,
                    initial_evaluation=repaired_evaluation,
                )
            )
        except DutySentinelMismatch as exc:
            trajectory.extend(exc.rows)
            return _finish_result(
                best,
                iterations,
                accounting,
                trajectory,
                started,
                provenance,
                status=CandidateStatus.SENTINEL_MISMATCH.value,
                error=exc,
            )
        except (AssertionError, RuntimeError, TypeError, ValueError) as exc:
            failed = CandidateOutcome(
                action_id="best-improvement-education",
                channel="education",
                status=CandidateStatus.INTERNAL_ERROR,
                changed_duty_ids=frozenset(
                    duty.physical_vehicle_id for duty in repaired.duties
                ),
                candidate=repaired,
                evaluation=repaired_evaluation,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            accounting.record_outcome(failed)
            trajectory.append(
                _trajectory_row(
                    iteration=iterations,
                    phase="education",
                    arm=arm,
                    before=repaired,
                    before_evaluation=repaired_evaluation,
                    outcome=failed,
                    accepted=False,
                )
            )
            return _finish_result(
                best,
                iterations,
                accounting,
                trajectory,
                started,
                provenance,
                status=CandidateStatus.INTERNAL_ERROR.value,
                error=exc,
            )
        trajectory.extend(education_rows)
        admission = population.add(educated, educated_evaluation)
        accounting.record_population_admission(inserted=admission.inserted)
        admitted = CandidateOutcome(
            action_id="population-admission",
            channel="hgs_population",
            status=CandidateStatus.EVALUATED,
            changed_duty_ids=frozenset(
                duty.physical_vehicle_id for duty in educated.duties
            ),
            candidate=educated,
            evaluation=educated_evaluation,
        )
        trajectory.append(
            _trajectory_row(
                iteration=iterations,
                phase="population",
                arm=arm,
                before=repaired,
                before_evaluation=repaired_evaluation,
                outcome=admitted,
                accepted=admission.inserted,
            )
        )
        candidate_best = population.best_feasible() or population.best_penalized()
        if candidate_best is not None and _incumbent_key(
            candidate_best,
            penalty_manager,
        ) < _incumbent_key(best, penalty_manager):
            best = candidate_best
            no_improvement = 0
        else:
            no_improvement += 1
        iterations += 1

    termination_status = (
        "STOPPED_BY_CALLER"
        if best.evaluation.feasible
        else CandidateStatus.NO_FEASIBLE_SOLUTION.value
    )
    return _finish_result(
        best,
        iterations,
        accounting,
        trajectory,
        started,
        provenance,
        status=termination_status,
    )


def _incumbent_key(
    candidate: EvaluatedDutyCandidate,
    penalty_manager: AdaptivePenaltyManager,
) -> tuple[int, float, str]:
    if candidate.evaluation.feasible:
        return (
            0,
            float(candidate.evaluation.total_cost),
            candidate.individual.fingerprint,
        )
    return (
        1,
        float(penalty_manager.cost(candidate.evaluation)),
        candidate.individual.fingerprint,
    )


def _crossover_rejection_status(error: Exception) -> CandidateStatus:
    message = str(error).lower()
    if "fleet" in message or "registry" in message:
        return CandidateStatus.REJECTED_REGISTRY
    if "lock" in message:
        return CandidateStatus.REJECTED_LOCK
    return CandidateStatus.REJECTED_INTERFACE


def population_sha256(candidates: tuple[DutyIndividual, ...]) -> str:
    payload = [
        {
            "fingerprint": candidate.fingerprint,
            "source": candidate.source,
        }
        for candidate in candidates
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def search_configuration_sha256(
    parameters: DutyHGSSearchParameters,
    charging_policy: ChargingRepairPolicy,
    *,
    arm: str,
) -> str:
    """Hash only the runner, charging-policy, and arm configuration."""

    payload = {
        "arm": str(arm),
        "parameters": asdict(parameters),
        "charging_policy": asdict(charging_policy),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finish_result(
    best,
    iterations: int,
    accounting: SearchAccounting,
    trajectory: list[TrajectoryRow],
    started: float,
    provenance: DutyHGSRunProvenance,
    *,
    status: str,
    error: Exception | None = None,
) -> DutyHGSRunResult:
    accounting.run_wall_seconds = perf_counter() - started
    return DutyHGSRunResult(
        best=best.individual,
        best_evaluation=best.evaluation,
        iterations=iterations,
        accounting=accounting,
        trajectory=tuple(trajectory),
        provenance=provenance,
        termination_status=status,
        termination_error_type=(None if error is None else type(error).__name__),
        termination_error=None if error is None else str(error),
    )
