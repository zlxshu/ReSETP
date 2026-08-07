"""Best-improvement Duty education under the complete evaluation chain.

v1 2026-08-07: evaluate every generated action, rebuild affected nonlinear
charging ledgers, verify incremental results against full truth, and accept only
the best complete-model legal improvement in each education round.

v2 2026-08-07: distinguish a deterministic no-op from an interface rejection.

v3 2026-08-07: seed one immutable incremental cache per education round and
reuse an already verified input evaluation supplied by the repair phase.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, replace
from time import perf_counter

from .charging import ChargingRepairPolicy, repair_changed_duties
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
from .model import DutyIndividual, assert_locks_preserved
from .operators import DutyMove, generate_problem_moves


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
) -> CandidateOutcome:
    """Return a typed candidate outcome; truth-sentinel failures still raise."""

    started = perf_counter()
    try:
        raw = move.apply(current)
        assert_locks_preserved(current, raw)
    except (TypeError, ValueError) as exc:
        return _rejection(
            move,
            CandidateStatus.REJECTED_LOCK
            if "locked" in str(exc).lower()
            else CandidateStatus.REJECTED_INTERFACE,
            exc,
            started,
        )
    try:
        candidate = repair_changed_duties(
            current,
            raw,
            changed_duty_ids=set(move.changed_duty_ids),
            context=evaluator.context,
            policy=charging_policy,
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
) -> tuple[DutyIndividual, FullEvaluation, tuple[TrajectoryRow, ...]]:
    """Run best-improvement under the population's current penalty scale."""

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
        accounting.education_rounds += 1
        moves = generate_problem_moves(
            current,
            current_evaluation,
            evaluator.context.bundle.instance,
        )
        incremental = DutyIncrementalEvaluator(evaluator)
        accounting.record_cache_seed(incremental.seed(current))
        round_rows: list[TrajectoryRow] = []
        best = None
        best_key = None
        best_row_index = None
        sentinel_mismatch = False
        for move in moves:
            outcome = evaluate_move(
                current,
                move,
                evaluator=evaluator,
                charging_policy=charging_policy,
                incremental_evaluator=incremental,
            )
            accounting.record_outcome(outcome)
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
                    best_row_index = len(round_rows) - 1
        accepted = bool(
            best is not None
            and float(penalized_cost(best.evaluation))
            < float(penalized_cost(current_evaluation))
        )
        if accepted and best_row_index is not None:
            round_rows[best_row_index] = replace(
                round_rows[best_row_index],
                accepted=True,
            )
        if trajectory_sink is None:
            rows.extend(round_rows)
        else:
            trajectory_sink(tuple(round_rows))
        if sentinel_mismatch:
            raise DutySentinelMismatch(tuple(rows))
        if not accepted or best is None:
            break
        accounting.record_acceptance(best.channel)
        current = best.candidate
        current_evaluation = best.evaluation
    return current, current_evaluation, tuple(rows)


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
        wall_seconds=perf_counter() - started,
    )


def _metric(evaluation: FullEvaluation, key: str) -> float | None:
    value = evaluation.breakdown.get(key)
    return None if value is None else float(value)


def _minimum_margin(evaluation: FullEvaluation) -> float | None:
    if not evaluation.participation_margin:
        return None
    return min(float(value) for value in evaluation.participation_margin.values())
