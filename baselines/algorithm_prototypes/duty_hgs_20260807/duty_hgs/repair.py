"""Regret-2 customer repair for selective Duty crossover.

v1 2026-08-07: remove no customers silently.  Every missing customer remains
explicit until a complete-evaluated insertion is chosen; failed insertions are
kept as typed records rather than crashes.

v2 2026-08-07: reuse one immutable incremental cache for all insertion
candidates compared against the same partially repaired child.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from .charging import ChargingRepairPolicy
from .contracts import (
    CandidateOutcome,
    CandidateStatus,
    SearchAccounting,
    TrajectoryRow,
)
from .education import (
    DutySentinelMismatch,
    _trajectory_row,
    evaluate_move,
)
from .evaluation import (
    DutyFullEvaluator,
    DutyIncrementalEvaluator,
    FullEvaluation,
)
from .model import DutyIndividual
from .operators import InsertUnservedMove


def regret2_repair(
    individual: DutyIndividual,
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    arm: str,
    iteration: int,
    accounting: SearchAccounting,
    penalized_cost: Callable[[FullEvaluation], float],
    initial_evaluation: FullEvaluation | None = None,
) -> tuple[DutyIndividual, FullEvaluation, tuple[TrajectoryRow, ...]]:
    """Insert missing customers by lexicographic complete-model regret-2."""

    current = individual
    if initial_evaluation is None:
        current_evaluation = evaluator.evaluate(current)
        accounting.full_evaluations += 1
    else:
        if initial_evaluation.individual_fingerprint != current.fingerprint:
            raise ValueError(
                "repair received an evaluation for another individual"
            )
        current_evaluation = initial_evaluation
    rows: list[TrajectoryRow] = []
    while current.unserved_customers:
        by_customer: dict[str, list[CandidateOutcome]] = {}
        all_outcomes: list[CandidateOutcome] = []
        incremental = DutyIncrementalEvaluator(evaluator)
        accounting.record_cache_seed(incremental.seed(current))
        for customer in current.unserved_customers:
            moves = _insertion_moves(current, customer)
            outcomes = [
                evaluate_move(
                    current,
                    move,
                    evaluator=evaluator,
                    charging_policy=charging_policy,
                    incremental_evaluator=incremental,
                )
                for move in moves
            ]
            for outcome in outcomes:
                accounting.record_outcome(outcome)
            all_outcomes.extend(outcomes)
            by_customer[customer] = [
                outcome
                for outcome in outcomes
                if outcome.evaluated
                and outcome.candidate is not None
                and outcome.evaluation is not None
            ]

        choices: list[tuple[float, str, CandidateOutcome]] = []
        for customer, outcomes in by_customer.items():
            if not outcomes:
                continue
            ordered = sorted(
                outcomes,
                key=lambda outcome: _repair_key(outcome, penalized_cost),
            )
            best = ordered[0]
            if len(ordered) == 1:
                regret = math.inf
            else:
                regret = float(
                    penalized_cost(ordered[1].evaluation)
                    - penalized_cost(ordered[0].evaluation)
                )
            choices.append((regret, customer, best))
        chosen = max(
            choices,
            key=lambda item: (item[0], item[1]),
            default=None,
        )
        chosen_outcome = None if chosen is None else chosen[2]
        for outcome in all_outcomes:
            rows.append(
                _trajectory_row(
                    iteration=iteration,
                    phase="regret2_repair",
                    arm=arm,
                    before=current,
                    before_evaluation=current_evaluation,
                    outcome=outcome,
                    accepted=outcome is chosen_outcome,
                )
            )
        if any(
            outcome.status == CandidateStatus.SENTINEL_MISMATCH
            for outcome in all_outcomes
        ):
            raise DutySentinelMismatch(tuple(rows))
        if chosen_outcome is None:
            break
        accounting.repair_calls += 1
        accounting.record_acceptance(chosen_outcome.channel)
        current = chosen_outcome.candidate
        current_evaluation = chosen_outcome.evaluation
    return current, current_evaluation, tuple(rows)


def _insertion_moves(
    individual: DutyIndividual,
    customer_id: str,
) -> tuple[InsertUnservedMove, ...]:
    moves: list[InsertUnservedMove] = []
    for duty in individual.duties:
        for trip in duty.trips:
            if trip.trip_index in duty.locked_charging_trip_indices:
                continue
            for position in range(
                len(trip.locked_customer_prefix),
                len(trip.customer_ids) + 1,
            ):
                moves.append(
                    InsertUnservedMove(
                        action_id=(
                            f"regret-insert:{customer_id}->"
                            f"{duty.physical_vehicle_id}"
                            f"#T{trip.trip_index}@{position}"
                        ),
                        channel="regret_insert",
                        customer_id=customer_id,
                        target_duty_id=duty.physical_vehicle_id,
                        target_trip_index=trip.trip_index,
                        target_position=position,
                    )
                )
        moves.append(
            InsertUnservedMove(
                action_id=(
                    f"regret-new-trip:{customer_id}->"
                    f"{duty.physical_vehicle_id}"
                ),
                channel="regret_insert_new_trip",
                customer_id=customer_id,
                target_duty_id=duty.physical_vehicle_id,
                target_trip_index=None,
                target_position=0,
            )
        )
    return tuple(moves)


def _repair_key(
    outcome: CandidateOutcome,
    penalized_cost: Callable[[FullEvaluation], float],
) -> tuple[float, str]:
    if outcome.evaluation is None:
        return (math.inf, outcome.action_id)
    return (
        float(penalized_cost(outcome.evaluation)),
        outcome.action_id,
    )
