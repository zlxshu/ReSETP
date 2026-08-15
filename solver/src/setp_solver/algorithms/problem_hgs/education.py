"""Best-improvement Duty education under the complete evaluation chain.

v1 2026-08-07: evaluate every generated action, rebuild affected nonlinear
charging ledgers, verify incremental results against full truth, and accept only
the best complete-model legal improvement in each education round.

v2 2026-08-07: distinguish a deterministic no-op from an interface rejection.

v3 2026-08-07: seed one immutable incremental cache per education round and
reuse an already verified input evaluation supplied by the repair phase.

v4 2026-08-07: expose the approved whole-duty type-exchange switch so its
contribution can be measured without changing any other search setting.

v5 2026-08-08: accept an explicit system proposal engine.  The engine orders
candidate actions only; charging repair and complete-model evaluation remain
the sole construction and acceptance path.

v6 2026-08-08: cold-replay only the selected improving action during search;
tests may still request a sentinel for every candidate through ``evaluate_move``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, replace
from itertools import chain
from time import perf_counter

from .charging import (
    ChargingFeasibilityPrescreen,
    ChargingRepairCache,
    ChargingRepairPolicy,
    charging_rejection_reason,
    repair_changed_duties,
)
from .contracts import (
    CandidateOutcome,
    CandidateStatus,
    SearchAccounting,
    TrajectoryRow,
)
from .evaluation import (
    DutyFullEvaluator,
    DutyIncrementalEvaluator,
    FullEvaluation,
)
from .fleet_registry import assert_fleet_activation_allowed
from .model import DutyIndividual, assert_locks_preserved
from .operators import DutyMove
from .proposals import DutyProposalEngine, LegacyCompleteProposalEngine
from .schedule_capture import emit_schedule_capture
from .schedule_oracle import OracleStatus, ScheduleCoordinator


# The complete evaluator combines many floating-point cost components.  The
# rest of the solver already uses 1e-9 as its numerical improvement tolerance;
# accepting changes below that scale can make equivalent charging schedules
# alternate forever.
IMPROVEMENT_TOLERANCE = 1e-9


class DutySentinelMismatch(RuntimeError):
    """Carry completed trace rows when incremental truth equality fails."""

    def __init__(self, rows: tuple[TrajectoryRow, ...]):
        super().__init__("incremental evaluation differs from full truth")
        self.rows = rows


def evaluate_move(
    current: DutyIndividual,
    move: DutyMove,
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    incremental_evaluator: DutyIncrementalEvaluator | None = None,
    charging_repair_cache: ChargingRepairCache | None = None,
    verify_full_truth: bool | None = None,
    penalized_cost: Callable[[FullEvaluation], float] | None = None,
    schedule_capture_iteration: int | None = None,
    schedule_coordinator: ScheduleCoordinator | None = None,
    schedule_accounting: SearchAccounting | None = None,
    fleet_activation_enabled: bool = True,
    charging_prescreen: ChargingFeasibilityPrescreen | None = None,
) -> CandidateOutcome:
    """Return a typed candidate outcome; truth-sentinel failures still raise."""

    started = perf_counter()
    raw = None
    try:
        raw = move.apply(current)
        assert_locks_preserved(current, raw)
        assert_fleet_activation_allowed(
            current,
            raw,
            enabled=fleet_activation_enabled,
        )
    except (TypeError, ValueError) as exc:
        if raw is not None:
            emit_schedule_capture(
                channel=move.channel,
                action_id=move.action_id,
                iteration=schedule_capture_iteration,
                reference=current,
                raw_candidate=raw,
                changed_duty_ids=move.changed_duty_ids,
                context=evaluator.context,
                a0_status="INFEASIBLE",
                error=exc,
            )
        return _rejection(
            move,
            CandidateStatus.REJECTED_LOCK
            if "locked" in str(exc).lower()
            else CandidateStatus.REJECTED_REGISTRY
            if "fleet" in str(exc).lower()
            or "empty duty" in str(exc).lower()
            else CandidateStatus.REJECTED_INTERFACE,
            exc,
            started,
        )
    emit_schedule_capture(
        channel=move.channel,
        action_id=move.action_id,
        iteration=schedule_capture_iteration,
        reference=current,
        raw_candidate=raw,
        changed_duty_ids=move.changed_duty_ids,
        context=evaluator.context,
        a0_status="FEASIBLE",
        error=None,
    )
    if schedule_coordinator is not None:
        coordinated = schedule_coordinator.coordinate(
            current,
            raw,
            changed_duty_ids=move.changed_duty_ids,
        )
        if schedule_accounting is not None:
            schedule_accounting.record_schedule_coordinator_result(
                coordinated,
                changed_duty_count=len(move.changed_duty_ids),
            )
        if coordinated.status != OracleStatus.FEASIBLE:
            if schedule_accounting is not None:
                schedule_accounting.schedule_rejected_candidates_by_channel_and_status[
                    f"{move.channel}:{coordinated.status.value}"
                ] += 1
            return CandidateOutcome(
                action_id=move.action_id,
                channel=move.channel,
                status=CandidateStatus.REJECTED_CHARGING,
                changed_duty_ids=move.changed_duty_ids,
                error_type="ScheduleCoordinatorResult",
                error=(
                    f"{coordinated.status.value}: "
                    f"{coordinated.failure_reason or 'no schedule frontier'}"
                ),
                charging_rejection_reason=charging_rejection_reason(
                    ValueError(
                        f"{coordinated.status.value}: "
                        f"{coordinated.failure_reason or 'no schedule frontier'}"
                    )
                ),
                wall_seconds=perf_counter() - started,
            )
        evaluated = []
        for scheduled in coordinated.frontier:
            try:
                full = evaluator.evaluate(scheduled)
            except (TypeError, ValueError):
                continue
            evaluated.append((scheduled, full))
        if not evaluated:
            return CandidateOutcome(
                action_id=move.action_id,
                channel=move.channel,
                status=CandidateStatus.REJECTED_INTERFACE,
                changed_duty_ids=move.changed_duty_ids,
                error_type="ScheduleFrontierEvaluationError",
                error="no coordinated schedule passed complete evaluation",
                wall_seconds=perf_counter() - started,
            )
        objective = penalized_cost or (lambda full: float(full.total_cost))
        candidate, result = min(
            evaluated,
            key=lambda item: (
                float(objective(item[1])),
                item[0].fingerprint,
            ),
        )
        if candidate.fingerprint == current.fingerprint:
            return CandidateOutcome(
                action_id=move.action_id,
                channel=move.channel,
                status=CandidateStatus.NO_CHANGE,
                changed_duty_ids=frozenset(),
                candidate=current,
                wall_seconds=perf_counter() - started,
            )
        return CandidateOutcome(
            action_id=move.action_id,
            channel=move.channel,
            status=CandidateStatus.EVALUATED,
            changed_duty_ids=move.changed_duty_ids,
            candidate=candidate,
            evaluation=result,
            wall_seconds=perf_counter() - started,
        )
    preserved_charging_ids = frozenset(
        getattr(move, "explicit_charging_duty_ids", ())
    )
    if charging_prescreen is not None:
        failure = charging_prescreen.screen(
            current,
            raw,
            changed_duty_ids=move.changed_duty_ids,
            channel=move.channel,
            preserve_explicit_charging_duty_ids=preserved_charging_ids,
        )
        if failure is not None:
            return _rejection(
                move,
                CandidateStatus.REJECTED_CHARGING,
                failure,
                started,
            )
    try:
        candidate = repair_changed_duties(
            current,
            raw,
            changed_duty_ids=set(move.changed_duty_ids),
            context=evaluator.context,
            policy=charging_policy,
            cache=charging_repair_cache,
            preserve_explicit_charging_duty_ids=set(preserved_charging_ids),
        )
    except (TypeError, ValueError) as exc:
        return _rejection(
            move,
            CandidateStatus.REJECTED_CHARGING,
            exc,
            started,
        )
    if candidate.fingerprint == current.fingerprint:
        return CandidateOutcome(
            action_id=move.action_id,
            channel=move.channel,
            status=CandidateStatus.NO_CHANGE,
            changed_duty_ids=frozenset(),
            candidate=current,
            wall_seconds=perf_counter() - started,
        )
    try:
        incremental = incremental_evaluator
        local_seed_count = 0
        if incremental is None:
            incremental = DutyIncrementalEvaluator(evaluator)
            local_seed_count = incremental.seed(current)
        result = incremental.evaluate_after_change(
            current,
            candidate,
            changed_duty_ids=set(move.changed_duty_ids),
            verify_full_truth=verify_full_truth,
        )
        if local_seed_count:
            result = replace(
                result,
                accounting={
                    **result.accounting,
                    "cache_seedings": 1,
                    "duty_slice_preparations": (
                        int(result.accounting.get(
                            "duty_slice_preparations", 0
                        ))
                        + local_seed_count
                    ),
                },
            )
    except AssertionError as exc:
        return CandidateOutcome(
            action_id=move.action_id,
            channel=move.channel,
            status=CandidateStatus.SENTINEL_MISMATCH,
            changed_duty_ids=move.changed_duty_ids,
            error_type=type(exc).__name__,
            error=str(exc),
            wall_seconds=perf_counter() - started,
            work_accounting={
                "full_evaluations": 0,
                "incremental_evaluations": 1,
                "sentinel_evaluations": 1,
                "cache_seedings": int(local_seed_count > 0),
                "duty_slice_preparations": (
                    len(move.changed_duty_ids) + local_seed_count
                ),
                "candidate_assemblies": 1,
            },
        )
    except (TypeError, ValueError) as exc:
        return _rejection(
            move,
            CandidateStatus.REJECTED_INTERFACE,
            exc,
            started,
        )
    return CandidateOutcome(
        action_id=move.action_id,
        channel=move.channel,
        status=CandidateStatus.EVALUATED,
        changed_duty_ids=move.changed_duty_ids,
        candidate=candidate,
        evaluation=result,
        wall_seconds=perf_counter() - started,
    )


def educate_best_improvement(
    individual: DutyIndividual,
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    arm: str,
    iteration: int,
    accounting: SearchAccounting,
    penalized_cost: Callable[[FullEvaluation], float],
    initial_evaluation: FullEvaluation | None = None,
    trajectory_sink: Callable[[tuple[TrajectoryRow, ...]], None] | None = None,
    include_whole_duty_type_exchange: bool = True,
    proposal_engine: DutyProposalEngine | None = None,
    stop_requested: Callable[[], bool] | None = None,
    selection_policy: str = "best",
    schedule_coordinator: ScheduleCoordinator | None = None,
    fleet_activation_enabled: bool = True,
    charging_prescreen: ChargingFeasibilityPrescreen | None = None,
    record_trajectory: bool = True,
) -> tuple[DutyIndividual, FullEvaluation, tuple[TrajectoryRow, ...]]:
    """Run complete-cost best or first improvement education."""

    if selection_policy not in {"best", "first"}:
        raise ValueError("selection policy must be best or first")

    current = individual
    if initial_evaluation is None:
        current_evaluation = evaluator.evaluate(current)
        accounting.full_evaluations += 1
    else:
        if initial_evaluation.individual_fingerprint != current.fingerprint:
            raise ValueError(
                "education received an evaluation for another individual"
            )
        current_evaluation = initial_evaluation
    rows: list[TrajectoryRow] = []
    while True:
        if stop_requested is not None and stop_requested():
            return current, current_evaluation, tuple(rows)
        accounting.education_rounds += 1
        engine = proposal_engine or LegacyCompleteProposalEngine()
        proposed = iter(
            engine.propose(
                current,
                current_evaluation,
                evaluator.context.bundle.instance,
                include_whole_duty_type_exchange=(
                    include_whole_duty_type_exchange
                ),
            )
        )
        try:
            first_move = next(proposed)
        except StopIteration:
            return current, current_evaluation, tuple(rows)
        moves = chain((first_move,), proposed)
        incremental = DutyIncrementalEvaluator(evaluator)
        accounting.record_cache_seed(incremental.seed(current))
        charging_repair_cache = ChargingRepairCache(
            evaluator.context,
            charging_policy,
        )
        round_rows: list[TrajectoryRow] = []
        best = None
        best_key = None
        best_row_index = None
        sentinel_mismatch = False
        for move in moves:
            if stop_requested is not None and stop_requested():
                if record_trajectory:
                    if trajectory_sink is None:
                        rows.extend(round_rows)
                    else:
                        trajectory_sink(tuple(round_rows))
                return current, current_evaluation, tuple(rows)
            outcome = evaluate_move(
                current,
                move,
                evaluator=evaluator,
                charging_policy=charging_policy,
                incremental_evaluator=incremental,
                charging_repair_cache=charging_repair_cache,
                verify_full_truth=False,
                penalized_cost=penalized_cost,
                schedule_capture_iteration=iteration,
                schedule_coordinator=schedule_coordinator,
                schedule_accounting=accounting,
                fleet_activation_enabled=fleet_activation_enabled,
                charging_prescreen=charging_prescreen,
            )
            accounting.record_outcome(outcome)
            if record_trajectory:
                round_rows.append(
                    _trajectory_row(
                        iteration=iteration,
                        phase="education",
                        arm=arm,
                        before=current,
                        before_evaluation=current_evaluation,
                        outcome=outcome,
                        accepted=False,
                    )
                )
            sentinel_mismatch = bool(
                sentinel_mismatch
                or outcome.status == CandidateStatus.SENTINEL_MISMATCH
            )
            if (
                outcome.evaluated
                and outcome.evaluation is not None
                and outcome.candidate is not None
            ):
                candidate_key = (
                    float(penalized_cost(outcome.evaluation)),
                    outcome.action_id,
                )
                if best_key is None or candidate_key < best_key:
                    best = outcome
                    best_key = candidate_key
                    best_row_index = (
                        len(round_rows) - 1 if record_trajectory else None
                    )
                if (
                    selection_policy == "first"
                    and _meaningfully_better(
                        candidate_key[0],
                        float(penalized_cost(current_evaluation)),
                    )
                ):
                    break
        accepted = bool(
            best is not None
            and _meaningfully_better(
                float(penalized_cost(best.evaluation)),
                float(penalized_cost(current_evaluation)),
            )
        )
        if (
            accepted
            and best is not None
            and evaluator.context.incremental_full_truth_sentinel_enabled
            and evaluator.context.dynamic_state is None
        ):
            try:
                truth = incremental.verify_against_full_truth(
                    best.candidate,
                    best.evaluation,
                )
            except AssertionError as exc:
                if best_row_index is not None:
                    round_rows[best_row_index] = replace(
                        round_rows[best_row_index],
                        status=CandidateStatus.SENTINEL_MISMATCH.value,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                sentinel_mismatch = True
            else:
                accounting.sentinel_evaluations += 1
                best = replace(best, evaluation=truth)
        if accepted and not sentinel_mismatch and best_row_index is not None:
            round_rows[best_row_index] = replace(
                round_rows[best_row_index],
                accepted=True,
            )
        if record_trajectory:
            if trajectory_sink is None:
                rows.extend(round_rows)
            else:
                trajectory_sink(tuple(round_rows))
        if sentinel_mismatch:
            raise DutySentinelMismatch(tuple(rows))
        if not accepted or best is None:
            break
        accounting.record_acceptance(best.channel)
        accounting.record_accepted_effect(
            best.channel,
            current,
            current_evaluation,
            best.candidate,
            best.evaluation,
        )
        current = best.candidate
        current_evaluation = best.evaluation
    return current, current_evaluation, tuple(rows)


def _meaningfully_better(candidate: float, incumbent: float) -> bool:
    """Reject IEEE-754 noise while preserving every material improvement."""

    return float(candidate) < float(incumbent) - IMPROVEMENT_TOLERANCE


def trajectory_dicts(
    rows: tuple[TrajectoryRow, ...],
) -> list[dict[str, object]]:
    return [asdict(row) for row in rows]




def _trajectory_row(
    *,
    iteration: int,
    phase: str,
    arm: str,
    before: DutyIndividual,
    before_evaluation: FullEvaluation,
    outcome: CandidateOutcome,
    accepted: bool,
) -> TrajectoryRow:
    after = outcome.evaluation
    return TrajectoryRow(
        iteration=int(iteration),
        phase=phase,
        arm=arm,
        action_id=outcome.action_id,
        channel=outcome.channel,
        status=outcome.status.value,
        accepted=bool(accepted),
        before_fingerprint=before.fingerprint,
        after_fingerprint=(
            None if outcome.candidate is None else outcome.candidate.fingerprint
        ),
        before_cost=float(before_evaluation.total_cost),
        after_cost=None if after is None else float(after.total_cost),
        before_violations=len(before_evaluation.violations),
        after_violations=None if after is None else len(after.violations),
        before_carbon_cost=_metric(before_evaluation, "cost_carbon"),
        after_carbon_cost=None if after is None else _metric(after, "cost_carbon"),
        before_emissions_kg=_metric(before_evaluation, "E_total"),
        after_emissions_kg=None if after is None else _metric(after, "E_total"),
        participation_margin_before=tuple(
            sorted(
                (str(key), float(value))
                for key, value in before_evaluation.participation_margin.items()
            )
        ),
        participation_margin_after=(
            None
            if after is None
            else tuple(
                sorted(
                    (str(key), float(value))
                    for key, value in after.participation_margin.items()
                )
            )
        ),
        minimum_participation_margin_before=_minimum_margin(
            before_evaluation
        ),
        minimum_participation_margin_after=(
            None if after is None else _minimum_margin(after)
        ),
        error_type=outcome.error_type,
        error=outcome.error,
    )


def _rejection(
    move: DutyMove,
    status: CandidateStatus,
    error: Exception,
    started: float,
) -> CandidateOutcome:
    return CandidateOutcome(
        action_id=move.action_id,
        channel=move.channel,
        status=status,
        changed_duty_ids=move.changed_duty_ids,
        error_type=type(error).__name__,
        error=str(error),
        charging_rejection_reason=(
            charging_rejection_reason(error)
            if status == CandidateStatus.REJECTED_CHARGING
            else None
        ),
        wall_seconds=perf_counter() - started,
    )


def _metric(evaluation: FullEvaluation, key: str) -> float | None:
    value = evaluation.breakdown.get(key)
    return None if value is None else float(value)


def _minimum_margin(evaluation: FullEvaluation) -> float | None:
    if not evaluation.participation_margin:
        return None
    return min(float(value) for value in evaluation.participation_margin.values())
