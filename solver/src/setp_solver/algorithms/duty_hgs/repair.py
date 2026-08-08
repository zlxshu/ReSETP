"""Regret-2 customer repair for selective Duty crossover.

v1 2026-08-07: remove no customers silently.  Every missing customer remains
explicit until a complete-evaluated insertion is chosen; failed insertions are
kept as typed records rather than crashes.

v2 2026-08-07: reuse one immutable incremental cache for all insertion
candidates compared against the same partially repaired child.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import replace

from .charging import ChargingRepairPolicy
from .contracts import (
    CandidateOutcome,
    CandidateStatus,
    SearchAccounting,
    TrajectoryRow,
)
from .dcrex import InsertionOperator
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


def dcrex_repair(
    individual: DutyIndividual,
    *,
    insertion_operator: InsertionOperator,
    rng: random.Random,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    arm: str,
    iteration: int,
    accounting: SearchAccounting,
    penalized_cost: Callable[[FullEvaluation], float],
    initial_evaluation: FullEvaluation | None = None,
    trajectory_sink: Callable[[tuple[TrajectoryRow, ...]], None] | None = None,
) -> tuple[DutyIndividual, FullEvaluation, tuple[TrajectoryRow, ...]]:
    """Repair a DCREX child using the selected literature insertion action."""

    operator = InsertionOperator(insertion_operator)
    current = individual
    if initial_evaluation is None:
        current_evaluation = evaluator.evaluate(current)
        accounting.full_evaluations += 1
    else:
        if initial_evaluation.individual_fingerprint != current.fingerprint:
            raise ValueError("DCREX repair received another individual's evaluation")
        current_evaluation = initial_evaluation
    rows: list[TrajectoryRow] = []
    insertion_order = list(current.unserved_customers)
    rng.shuffle(insertion_order)

    while current.unserved_customers:
        incremental = DutyIncrementalEvaluator(evaluator)
        accounting.record_cache_seed(incremental.seed(current))
        round_rows: list[TrajectoryRow] = []
        records: list[
            tuple[str, InsertUnservedMove, CandidateOutcome, int]
        ] = []
        sentinel_mismatch = False
        customers = (
            [customer for customer in insertion_order if customer in current.unserved_customers]
            if operator in {InsertionOperator.FBI, InsertionOperator.IBI}
            else list(current.unserved_customers)
        )
        if operator == InsertionOperator.RI:
            customers = list(current.unserved_customers)
            rng.shuffle(customers)

        for customer in customers:
            moves = list(_insertion_moves(current, customer))
            if operator in {
                InsertionOperator.IBI,
                InsertionOperator.IRI,
                InsertionOperator.RI,
            }:
                moves = [move for move in moves if move.target_trip_index is not None]
            if operator == InsertionOperator.RI:
                rng.shuffle(moves)
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
                        phase=f"dcrex_{operator.value.lower()}_repair",
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
                    and outcome.candidate is not None
                    and outcome.evaluation is not None
                ):
                    records.append((customer, move, outcome, len(round_rows) - 1))
                if operator == InsertionOperator.RI and records:
                    break
            if operator in {
                InsertionOperator.FBI,
                InsertionOperator.IBI,
                InsertionOperator.RI,
            }:
                break

        chosen = _choose_dcrex_insertion(
            records,
            operator=operator,
            penalized_cost=penalized_cost,
        )
        if chosen is not None:
            round_rows[chosen[3]] = replace(
                round_rows[chosen[3]],
                accepted=True,
            )
        if trajectory_sink is None:
            rows.extend(round_rows)
        else:
            trajectory_sink(tuple(round_rows))
        if sentinel_mismatch:
            raise DutySentinelMismatch(tuple(rows))
        if chosen is None:
            break
        outcome = chosen[2]
        accounting.repair_calls += 1
        accounting.record_acceptance(outcome.channel)
        current = outcome.candidate
        current_evaluation = outcome.evaluation

    return current, current_evaluation, tuple(rows)


def _choose_dcrex_insertion(
    records: list[tuple[str, InsertUnservedMove, CandidateOutcome, int]],
    *,
    operator: InsertionOperator,
    penalized_cost: Callable[[FullEvaluation], float],
) -> tuple[str, InsertUnservedMove, CandidateOutcome, int] | None:
    if not records:
        return None
    if operator == InsertionOperator.RI:
        return records[0]

    def raw_cost(record) -> tuple[float, str]:
        outcome = record[2]
        return float(outcome.evaluation.total_cost), outcome.action_id

    def penalty_cost(record) -> tuple[float, str]:
        outcome = record[2]
        return float(penalized_cost(outcome.evaluation)), outcome.action_id

    if operator in {InsertionOperator.FBI, InsertionOperator.IBI}:
        customer = records[0][0]
        options = [record for record in records if record[0] == customer]
        if operator == InsertionOperator.FBI:
            feasible_existing = [
                record
                for record in options
                if record[1].target_trip_index is not None
                and record[2].evaluation.feasible
            ]
            if feasible_existing:
                return min(feasible_existing, key=raw_cost)
            new_trip = [
                record for record in options if record[1].target_trip_index is None
            ]
            feasible_new = [
                record for record in new_trip if record[2].evaluation.feasible
            ]
            return min(feasible_new or new_trip, key=penalty_cost, default=None)
        return min(options, key=penalty_cost)

    feasible_only = operator == InsertionOperator.FRI
    candidates = []
    for customer in dict.fromkeys(record[0] for record in records):
        customer_records = [record for record in records if record[0] == customer]
        if feasible_only:
            customer_records = [
                record for record in customer_records if record[2].evaluation.feasible
            ]
        grouped: dict[tuple[str, int | None], list] = {}
        for record in customer_records:
            move = record[1]
            grouped.setdefault(
                (move.target_duty_id, move.target_trip_index),
                [],
            ).append(record)
        key = raw_cost if feasible_only else penalty_cost
        best_by_route = [min(group, key=key) for group in grouped.values()]
        best_by_route.sort(key=key)
        if not best_by_route and feasible_only:
            new_trip = [
                record
                for record in records
                if record[0] == customer and record[1].target_trip_index is None
            ]
            if new_trip:
                best_by_route = [min(new_trip, key=penalty_cost)]
        if not best_by_route:
            continue
        best_value = key(best_by_route[0])[0]
        regret = (
            key(best_by_route[1])[0] - best_value
            if len(best_by_route) > 1
            else math.inf
        )
        candidates.append((regret, customer, best_by_route[0]))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


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
    trajectory_sink: Callable[[tuple[TrajectoryRow, ...]], None] | None = None,
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
        by_customer: dict[str, list[tuple[CandidateOutcome, int]]] = {}
        round_rows: list[TrajectoryRow] = []
        sentinel_mismatch = False
        incremental = DutyIncrementalEvaluator(evaluator)
        accounting.record_cache_seed(incremental.seed(current))
        for customer in current.unserved_customers:
            moves = _insertion_moves(current, customer)
            ranked: list[tuple[CandidateOutcome, int]] = []
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
                        phase="regret2_repair",
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
                    and outcome.candidate is not None
                    and outcome.evaluation is not None
                ):
                    ranked.append((outcome, len(round_rows) - 1))
                    ranked.sort(
                        key=lambda item: _repair_key(item[0], penalized_cost)
                    )
                    del ranked[2:]
            by_customer[customer] = ranked

        choices: list[tuple[float, str, CandidateOutcome, int]] = []
        for customer, outcomes in by_customer.items():
            if not outcomes:
                continue
            best, best_row_index = outcomes[0]
            if len(outcomes) == 1:
                regret = math.inf
            else:
                regret = float(
                    penalized_cost(outcomes[1][0].evaluation)
                    - penalized_cost(outcomes[0][0].evaluation)
                )
            choices.append((regret, customer, best, best_row_index))
        chosen = max(
            choices,
            key=lambda item: (item[0], item[1]),
            default=None,
        )
        chosen_outcome = None if chosen is None else chosen[2]
        if chosen is not None:
            chosen_row_index = chosen[3]
            round_rows[chosen_row_index] = replace(
                round_rows[chosen_row_index],
                accepted=True,
            )
        if trajectory_sink is None:
            rows.extend(round_rows)
        else:
            trajectory_sink(tuple(round_rows))
        if sentinel_mismatch:
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
