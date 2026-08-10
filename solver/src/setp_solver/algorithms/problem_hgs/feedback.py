"""Addressable pressure signals and a threshold-free feedback truth probe.

v1 2026-08-07: map complete-model violations to concrete Duty objects, build
capacity-relocate candidates, and retain the full pressure/random/truth ranking
curves without manufacturing a pass threshold.

v2 2026-08-07: make customer moves invalidate stale route visits and reject
changes to trips whose executed charging decision is locked.

v3 2026-08-07: route pressure candidates through the same charging repair,
incremental evaluation, and full-truth sentinel used by the main search.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Any

from setp_solver.check import CAPACITY
from setp_solver.instance_loader import Instance

from .charging import ChargingRepairPolicy
from .education import evaluate_move
from .evaluation import DutyFullEvaluator, FullEvaluation
from .model import DutyIndividual, DutyTrip, PhysicalVehicleDuty
from .operators import RelocateMove


@dataclass(frozen=True)
class PressureSignal:
    signal_id: str
    resource: str
    scope: str
    duty_id: str | None
    trip_index: int | None
    object_id: str
    detail: str
    magnitude: float
    actionable: bool


@dataclass(frozen=True)
class RelocateCustomerMove:
    action_id: str
    source_duty_id: str
    source_trip_index: int
    customer_id: str
    target_duty_id: str
    target_trip_index: int
    target_position: int
    predicted_remaining_overflow_kg: float
    predicted_relief_kg: float

    @property
    def channel(self) -> str:
        return "pressure_capacity"

    @property
    def changed_duty_ids(self) -> frozenset[str]:
        return frozenset({self.source_duty_id, self.target_duty_id})

    def apply(self, individual: DutyIndividual) -> DutyIndividual:
        return RelocateMove(
            action_id=self.action_id,
            channel=self.channel,
            source_duty_id=self.source_duty_id,
            source_trip_index=self.source_trip_index,
            customer_id=self.customer_id,
            target_duty_id=self.target_duty_id,
            target_trip_index=self.target_trip_index,
            target_position=self.target_position,
        ).apply(individual)


@dataclass(frozen=True)
class FeedbackProbeRecord:
    action_id: str
    pressure_rank: int
    random_rank: int
    truth_rank: int
    status: str
    violation_count: int | None
    total_cost: float | None
    error: str | None = None


@dataclass(frozen=True)
class FeedbackCurvePoint:
    step: int
    action_id: str
    best_violation_count: int | None
    best_total_cost: float | None


@dataclass(frozen=True)
class FeedbackTruthProbe:
    signal: PressureSignal
    records: tuple[FeedbackProbeRecord, ...]
    pressure_curve: tuple[FeedbackCurvePoint, ...]
    random_curve: tuple[FeedbackCurvePoint, ...]
    truth_curve: tuple[FeedbackCurvePoint, ...]
    threshold_or_pass_label: str | None = None


def pressure_signals_from_evaluation(
    evaluation: FullEvaluation,
) -> tuple[PressureSignal, ...]:
    """Return one independently addressable signal per full-model violation."""

    signals: list[PressureSignal] = []
    for index, (violation, magnitude) in enumerate(
        zip(
            evaluation.violations,
            evaluation.violation_magnitudes,
            strict=True,
        ),
        start=1,
    ):
        duty_id: str | None = None
        trip_index: int | None = None
        if violation.vehicle_id:
            duty_id, trip_index = _try_parse_route_id(violation.vehicle_id)
        scope = "trip" if duty_id is not None else "depot_or_global"
        signals.append(
            PressureSignal(
                signal_id=f"{violation.type}:{index}",
                resource=violation.type,
                scope=scope,
                duty_id=duty_id,
                trip_index=trip_index,
                object_id=violation.location,
                detail=violation.detail,
                magnitude=float(magnitude),
                actionable=(
                    violation.type == CAPACITY
                    and duty_id is not None
                    and trip_index is not None
                ),
            )
        )
    return tuple(signals)


def build_capacity_relocates(
    individual: DutyIndividual,
    signal: PressureSignal,
    instance: Instance,
    prices: Any,
) -> tuple[RelocateCustomerMove, ...]:
    """Build real customer moves from one capacity violation, without weights."""

    if (
        signal.resource != CAPACITY
        or signal.duty_id is None
        or signal.trip_index is None
    ):
        raise ValueError("capacity relocates require an addressable capacity signal")
    source_duty = _find_duty(individual, signal.duty_id)
    source_trip = _find_trip(individual, signal.duty_id, signal.trip_index)
    node_lookup = {node.node_id: node for node in instance.nodes}
    source_capacity = instance.payload_capacity_kg(
        source_duty.vehicle_type,
        fallback=_price(prices, "Q_capacity"),
    )
    source_load = _trip_demand(source_trip, node_lookup)
    baseline_overflow = max(0.0, source_load - source_capacity)
    moves: list[RelocateCustomerMove] = []
    movable = source_trip.customer_ids[len(source_trip.locked_customer_prefix) :]
    for customer_id in movable:
        demand = float(node_lookup[customer_id].demand)
        source_after = max(
            0.0,
            source_load - demand - source_capacity,
        )
        for target_duty in individual.duties:
            target_capacity = instance.payload_capacity_kg(
                target_duty.vehicle_type,
                fallback=_price(prices, "Q_capacity"),
            )
            for target_trip in target_duty.trips:
                if (
                    target_duty.physical_vehicle_id == signal.duty_id
                    and target_trip.trip_index == signal.trip_index
                ):
                    continue
                target_load = _trip_demand(target_trip, node_lookup)
                target_after = max(
                    0.0,
                    target_load + demand - target_capacity,
                )
                remaining = source_after + target_after
                relief = baseline_overflow - remaining
                for position in range(
                    len(target_trip.locked_customer_prefix),
                    len(target_trip.customer_ids) + 1,
                ):
                    action_id = (
                        f"relocate:{signal.duty_id}#T{signal.trip_index}:"
                        f"{customer_id}->{target_duty.physical_vehicle_id}"
                        f"#T{target_trip.trip_index}@{position}"
                    )
                    moves.append(
                        RelocateCustomerMove(
                            action_id=action_id,
                            source_duty_id=signal.duty_id,
                            source_trip_index=signal.trip_index,
                            customer_id=customer_id,
                            target_duty_id=target_duty.physical_vehicle_id,
                            target_trip_index=target_trip.trip_index,
                            target_position=position,
                            predicted_remaining_overflow_kg=remaining,
                            predicted_relief_kg=relief,
                        )
                    )
    moves.sort(
        key=lambda move: (
            move.predicted_remaining_overflow_kg,
            -move.predicted_relief_kg,
            move.customer_id,
            move.target_duty_id,
            move.target_trip_index,
            move.target_position,
        )
    )
    return tuple(moves)


def run_feedback_truth_probe(
    individual: DutyIndividual,
    evaluator: DutyFullEvaluator,
    signal: PressureSignal,
    *,
    random_seed: int,
    charging_policy: ChargingRepairPolicy,
) -> FeedbackTruthProbe:
    """Evaluate the same actions in pressure, random, and full-truth order."""

    moves = build_capacity_relocates(
        individual,
        signal,
        evaluator.context.bundle.instance,
        evaluator.context.bundle.prices,
    )
    if not moves:
        raise ValueError("addressable pressure produced no real candidate move")
    random_order = list(range(len(moves)))
    random.Random(int(random_seed)).shuffle(random_order)
    random_rank = {
        moves[index].action_id: rank
        for rank, index in enumerate(random_order, start=1)
    }
    records: list[FeedbackProbeRecord] = []
    for pressure_rank, move in enumerate(moves, start=1):
        outcome = evaluate_move(
            individual,
            move,
            evaluator=evaluator,
            charging_policy=charging_policy,
        )
        if not outcome.evaluated or outcome.evaluation is None:
            records.append(
                FeedbackProbeRecord(
                    action_id=move.action_id,
                    pressure_rank=pressure_rank,
                    random_rank=random_rank[move.action_id],
                    truth_rank=0,
                    status=outcome.status.value,
                    violation_count=None,
                    total_cost=None,
                    error=outcome.error,
                )
            )
            continue
        evaluation = outcome.evaluation
        records.append(
            FeedbackProbeRecord(
                action_id=move.action_id,
                pressure_rank=pressure_rank,
                random_rank=random_rank[move.action_id],
                truth_rank=0,
                status="EVALUATED",
                violation_count=len(evaluation.violations),
                total_cost=float(evaluation.total_cost),
            )
        )
    truth_order = sorted(range(len(records)), key=lambda index: _truth_key(records[index]))
    truth_rank = {
        records[index].action_id: rank
        for rank, index in enumerate(truth_order, start=1)
    }
    ranked = tuple(
        replace(record, truth_rank=truth_rank[record.action_id])
        for record in records
    )
    return FeedbackTruthProbe(
        signal=signal,
        records=ranked,
        pressure_curve=_curve(ranked, "pressure_rank"),
        random_curve=_curve(ranked, "random_rank"),
        truth_curve=_curve(ranked, "truth_rank"),
        threshold_or_pass_label=None,
    )


def _curve(
    records: tuple[FeedbackProbeRecord, ...],
    rank_field: str,
) -> tuple[FeedbackCurvePoint, ...]:
    ordered = sorted(records, key=lambda row: int(getattr(row, rank_field)))
    best: FeedbackProbeRecord | None = None
    points: list[FeedbackCurvePoint] = []
    for step, row in enumerate(ordered, start=1):
        if best is None or _truth_key(row) < _truth_key(best):
            best = row
        points.append(
            FeedbackCurvePoint(
                step=step,
                action_id=row.action_id,
                best_violation_count=best.violation_count,
                best_total_cost=best.total_cost,
            )
        )
    return tuple(points)


def _truth_key(record: FeedbackProbeRecord) -> tuple[object, ...]:
    if record.status != "EVALUATED":
        return (1, math_inf(), math_inf(), record.action_id)
    return (
        0,
        int(record.violation_count or 0),
        float(record.total_cost or 0.0),
        record.action_id,
    )


def _find_duty(
    individual: DutyIndividual,
    duty_id: str,
) -> PhysicalVehicleDuty:
    try:
        return next(
            duty
            for duty in individual.duties
            if duty.physical_vehicle_id == duty_id
        )
    except StopIteration as exc:
        raise ValueError(f"unknown duty {duty_id!r}") from exc


def _find_trip(
    individual: DutyIndividual,
    duty_id: str,
    trip_index: int,
) -> DutyTrip:
    duty = _find_duty(individual, duty_id)
    try:
        return next(
            trip
            for trip in duty.trips
            if trip.trip_index == int(trip_index)
        )
    except StopIteration as exc:
        raise ValueError(
            f"unknown duty trip {duty_id!r}#T{trip_index}"
        ) from exc


def _try_parse_route_id(route_id: str) -> tuple[str | None, int | None]:
    if route_id.count("#T") != 1:
        return None, None
    duty_id, raw_trip = route_id.rsplit("#T", 1)
    if not duty_id.startswith(("CV_", "EV_")):
        return None, None
    try:
        trip_index = int(raw_trip)
    except ValueError:
        return None, None
    return duty_id, trip_index


def _trip_demand(trip: DutyTrip, node_lookup: dict[str, Any]) -> float:
    return sum(float(node_lookup[customer].demand) for customer in trip.customer_ids)


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def math_inf() -> float:
    return float("inf")
