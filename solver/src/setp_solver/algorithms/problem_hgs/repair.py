"""Regret-2 customer repair for Duty crossover."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace

from .charging import ChargingRepairPolicy
from .contracts import (
    CandidateOutcome,
    CandidateStatus,
    SearchAccounting,
    TrajectoryRow,
)
from .education import _trajectory_row, evaluate_move
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
    trajectory_sink: Callable[[tuple[TrajectoryRow, ...]], None] | None = None,
    stop_requested: Callable[[], bool] | None = None,
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
        if stop_requested is not None and stop_requested():
            break
        by_customer: dict[str, list[tuple[CandidateOutcome, int]]] = {}
        round_rows: list[TrajectoryRow] = []
        incremental = DutyIncrementalEvaluator(evaluator)
        accounting.record_cache_seed(incremental.seed(current))
        for customer in current.unserved_customers:
            if stop_requested is not None and stop_requested():
                return current, current_evaluation, tuple(rows)
            moves = _insertion_moves(current, customer)
            ranked: list[tuple[CandidateOutcome, int]] = []
            for move in moves:
                if stop_requested is not None and stop_requested():
                    return current, current_evaluation, tuple(rows)
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
        if chosen_outcome is None:
            break
        accounting.repair_calls += 1
        accounting.record_acceptance(chosen_outcome.channel)
        current = chosen_outcome.candidate
        current_evaluation = chosen_outcome.evaluation
    return current, current_evaluation, tuple(rows)


def insertion_moves(
    individual: DutyIndividual,
    customer_id: str,
) -> tuple[InsertUnservedMove, ...]:
    """Expose the existing exact insertion neighbourhood for warm starts."""

    return _insertion_moves(individual, customer_id)


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
