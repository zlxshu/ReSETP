"""Incremental insertion of newly revealed orders into an exact dynamic cut.

The route skeleton is changed by the copied HGS local-search kernel.  Missing
required clients are inserted by its cached ``insertCost`` path before one
finite local-search descent.  Complete Duty evaluation remains the sole
acceptance authority. This module performs no file I/O.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from time import perf_counter

from .charging import ChargingRepairPolicy, repair_changed_duties
from .contracts import CandidateStatus
from .education import evaluate_move
from .evaluation import DutyFullEvaluator, FullEvaluation
from .kernel_proposals import IndependentKernelDutyRouteProposalEngine
from .model import DutyIndividual
from .operators import DutySkeletonMove, InsertUnservedMove
from .proposals import MechanismProposalEngine


INSERTED_AND_FULL_EVALUATION_FEASIBLE = (
    "INSERTED_AND_FULL_EVALUATION_FEASIBLE"
)
NOT_INSERTED_TIME_INFEASIBLE = "NOT_INSERTED_TIME_INFEASIBLE"
NOT_INSERTED_CAPACITY = "NOT_INSERTED_CAPACITY"
NOT_INSERTED_ENERGY = "NOT_INSERTED_ENERGY"
NOT_INSERTED_CANDIDATE_EXHAUSTED = "NOT_INSERTED_CANDIDATE_EXHAUSTED"
NOT_INSERTED_SEARCH_EXHAUSTED = "NOT_INSERTED_SEARCH_EXHAUSTED"
INSERTION_DISABLED = "INSERTION_DISABLED"


class DynamicInsertionFailure(RuntimeError):
    """The incremental kernel did not produce a complete feasible suffix."""


@dataclass(frozen=True)
class DynamicInsertionAccounting:
    wall_seconds: float
    newly_revealed_count: int
    kernel_updates: int
    kernel_moves: int
    kernel_improving_moves: int
    changed_duty_count: int
    complete_evaluations: int
    charging_candidates_evaluated: int
    candidate_attempt_count: int = 0
    candidate_feasible_count: int = 0
    candidate_failure_reasons: tuple[str, ...] = ()
    candidate_diagnostics: tuple["DynamicInsertionAttempt", ...] = ()


@dataclass(frozen=True)
class DynamicInsertionAttempt:
    """One complete candidate attempt kept for a failed insertion diagnosis."""

    candidate_id: str
    scope: str
    status: str
    failure_reason: str = ""


@dataclass(frozen=True)
class DynamicInsertionResult:
    individual: DutyIndividual
    evaluation: FullEvaluation | None
    accounting: DynamicInsertionAccounting
    status: str = INSERTED_AND_FULL_EVALUATION_FEASIBLE
    failure_reason: str = ""
    outsourced_customer_ids: tuple[str, ...] = ()


class DynamicInsertionOperator:
    """Insert one revealed batch and re-optimise only the editable suffix."""

    def __init__(
        self,
        *,
        enabled: bool = False,
    ) -> None:
        self.enabled = bool(enabled)

    def apply(
        self,
        initial_future: DutyIndividual,
        *,
        evaluator: DutyFullEvaluator,
        charging_policy: ChargingRepairPolicy,
        newly_revealed_customer_ids: tuple[str, ...],
        current_evaluation: FullEvaluation | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> DynamicInsertionResult:
        """Return the no-op exactly when disabled, otherwise one sealed result."""

        started = perf_counter()
        if not self.enabled:
            return DynamicInsertionResult(
                individual=initial_future,
                evaluation=current_evaluation,
                accounting=DynamicInsertionAccounting(
                    wall_seconds=perf_counter() - started,
                    newly_revealed_count=0,
                    kernel_updates=0,
                    kernel_moves=0,
                    kernel_improving_moves=0,
                    changed_duty_count=0,
                    complete_evaluations=0,
                    charging_candidates_evaluated=0,
                ),
                status=INSERTION_DISABLED,
            )

        actual, accounting = self._apply_enabled(
            initial_future,
            evaluator=evaluator,
            charging_policy=charging_policy,
            newly_revealed_customer_ids=newly_revealed_customer_ids,
            stream_role="dynamic_revealed_insertion",
            current_evaluation=current_evaluation,
            stop_requested=stop_requested,
        )
        return DynamicInsertionResult(
            individual=actual.individual,
            evaluation=actual.evaluation,
            accounting=replace(
                accounting,
                wall_seconds=perf_counter() - started,
            ),
            status=actual.status,
            failure_reason=actual.failure_reason,
            outsourced_customer_ids=actual.outsourced_customer_ids,
        )

    def _apply_enabled(
        self,
        initial_future: DutyIndividual,
        *,
        evaluator: DutyFullEvaluator,
        charging_policy: ChargingRepairPolicy,
        newly_revealed_customer_ids: tuple[str, ...],
        stream_role: str,
        current_evaluation: FullEvaluation | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> tuple[DynamicInsertionResult, DynamicInsertionAccounting]:
        started = perf_counter()
        state = evaluator.context.dynamic_state
        if state is None:
            raise ValueError("dynamic insertion requires an exact dynamic state")
        revealed = tuple(dict.fromkeys(map(str, newly_revealed_customer_ids)))
        if len(revealed) != len(newly_revealed_customer_ids):
            raise ValueError("newly revealed customer ids must be unique")
        missing_from_unserved = set(revealed).difference(
            initial_future.unserved_customers
        )
        if missing_from_unserved:
            raise ValueError(
                "newly revealed customers must enter as explicit unserved ids: "
                + ", ".join(sorted(missing_from_unserved))
            )
        appearances = state.customer_appearance_second
        trigger = float(state.cut.trigger_second)
        if any(
            customer_id not in appearances
            or float(appearances[customer_id]) > trigger + 1.0e-9
            for customer_id in revealed
        ):
            raise ValueError("dynamic insertion received an unrevealed customer")

        before_calls = evaluator.full_calls
        committed_before = _committed_snapshot(evaluator)
        pending = tuple(
            dict.fromkeys(map(str, initial_future.unserved_customers))
        )
        diagnostics: list[DynamicInsertionAttempt] = []
        kernel_updates = 0
        kernel_moves = 0
        kernel_improving_moves = 0
        reoptimization_updates = 0
        reoptimization_moves = 0
        reoptimization_improving_moves = 0
        charging_evaluated = 0
        engine: IndependentKernelDutyRouteProposalEngine | None = None

        def record(
            candidate_id: str,
            scope: str,
            status: str,
            failure_reason: str = "",
        ) -> None:
            diagnostics.append(
                DynamicInsertionAttempt(
                    candidate_id=candidate_id,
                    scope=scope,
                    status=status,
                    failure_reason=failure_reason,
                )
            )

        def evaluate_candidate(
            candidate: DutyIndividual,
            *,
            candidate_id: str,
            scope: str,
            changed_duty_count: int,
        ) -> tuple[DutyIndividual, FullEvaluation, int] | None:
            if stop_requested is not None and stop_requested():
                return None
            still_unserved = set(pending).intersection(
                candidate.unserved_customers
            )
            if still_unserved:
                reason = (
                    "candidate did not insert required customers: "
                    + ", ".join(sorted(still_unserved))
                )
                record(
                    candidate_id,
                    scope,
                    _candidate_rejection_status(reason),
                    reason,
                )
                return None
            try:
                evaluation = evaluator.evaluate(candidate)
            except (TypeError, ValueError) as error:
                reason = f"{type(error).__name__}: {error}"
                record(
                    candidate_id,
                    scope,
                    _candidate_rejection_status(reason),
                    reason,
                )
                return None
            if not evaluation.feasible:
                reason = "; ".join(
                    f"{violation.type}:{violation.detail}"
                    for violation in evaluation.violations
                ) or "complete evaluation returned infeasible"
                record(
                    candidate_id,
                    scope,
                    _candidate_rejection_status(reason),
                    reason,
                )
                return None
            record(
                candidate_id,
                scope,
                INSERTED_AND_FULL_EVALUATION_FEASIBLE,
            )
            return candidate, evaluation, changed_duty_count

        def failure_result() -> tuple[DynamicInsertionResult, DynamicInsertionAccounting]:
            status = (
                NOT_INSERTED_SEARCH_EXHAUSTED
                if stop_requested is not None and stop_requested()
                else _insertion_failure_status(diagnostics)
            )
            reason = _insertion_failure_summary(status, diagnostics)
            accounting = DynamicInsertionAccounting(
                wall_seconds=perf_counter() - started,
                newly_revealed_count=len(revealed),
                kernel_updates=kernel_updates + reoptimization_updates,
                kernel_moves=kernel_moves + reoptimization_moves,
                kernel_improving_moves=(
                    kernel_improving_moves + reoptimization_improving_moves
                ),
                changed_duty_count=0,
                complete_evaluations=evaluator.full_calls - before_calls,
                charging_candidates_evaluated=charging_evaluated,
                candidate_attempt_count=len(diagnostics),
                candidate_feasible_count=sum(
                    item.status == INSERTED_AND_FULL_EVALUATION_FEASIBLE
                    for item in diagnostics
                ),
                candidate_failure_reasons=tuple(
                    item.failure_reason
                    for item in diagnostics
                    if item.failure_reason
                ),
                candidate_diagnostics=tuple(diagnostics),
            )
            return (
                DynamicInsertionResult(
                    individual=initial_future,
                    evaluation=current_evaluation,
                    accounting=accounting,
                    status=status,
                    failure_reason=reason,
                    outsourced_customer_ids=tuple(sorted(revealed)),
                ),
                accounting,
            )

        if stop_requested is not None and stop_requested():
            return failure_result()

        def materialize(
            native_solution,
        ) -> tuple[DutyIndividual, int]:
            assert engine is not None
            native_replacements = engine.decode_replacements(
                initial_future,
                native_solution,
            )
            if not native_replacements:
                return initial_future, 0
            move = DutySkeletonMove(
                action_id=(
                    "dynamic-insertion:"
                    + "+".join(
                        duty_id for duty_id, _trips in native_replacements
                    )
                ),
                channel="dynamic_revealed_insertion",
                replacements=native_replacements,
                dynamic_future_only=True,
            )
            raw = move.apply(initial_future)
            repaired = repair_changed_duties(
                initial_future,
                raw,
                changed_duty_ids=set(move.changed_duty_ids),
                context=evaluator.context,
                policy=charging_policy,
            )
            return repaired, len(move.changed_duty_ids)

        native_accepted: tuple[DutyIndividual, FullEvaluation, int] | None = None
        engine = IndependentKernelDutyRouteProposalEngine(
            evaluator.context,
            initial_future,
            stream_role=stream_role,
            rebuilt_volume_capacity_enabled=(
                evaluator.context.rebuilt_route_constraints is not None
            ),
            rebuilt_shift_neighbours_only=(
                evaluator.context.rebuilt_route_constraints is not None
            ),
        )
        warm = engine.project(initial_future)
        inserted = engine.local_search.repair_required(
            warm,
            engine.penalty_manager.booster_cost_evaluator(),
        )
        insertion_statistics = engine.local_search.statistics
        kernel_updates = int(insertion_statistics.num_updates)
        kernel_moves = int(insertion_statistics.num_moves)
        kernel_improving_moves = int(insertion_statistics.num_improving)
        candidate, changed_duty_count = materialize(inserted)
        native_accepted = evaluate_candidate(
            candidate,
            candidate_id="kernel-repair",
            scope="native_kernel_single_result",
            changed_duty_count=changed_duty_count,
        )

        accepted = native_accepted
        if accepted is None:
            for candidate, candidate_id, changed_duty_count in _direct_insertion_candidates(
                initial_future,
                pending,
            ):
                if stop_requested is not None and stop_requested():
                    break
                accepted = evaluate_candidate(
                    candidate,
                    candidate_id=candidate_id,
                    scope="exhaustive_direct_asset_trip_insertion",
                    changed_duty_count=changed_duty_count,
                )
                if accepted is not None:
                    break
        if accepted is None:
            return failure_result()

        candidate, evaluation, changed_duties = accepted

        # One bounded descent is allowed after the mandatory insertion.  It is
        # retained only when the complete ruler accepts it; the insertion-only
        # witness remains the fail-safe candidate.  The direct fallback has no
        # native solution to reoptimise, so it skips this optional step.
        if (
            native_accepted is not None
            and engine is not None
            and not (stop_requested is not None and stop_requested())
        ):
            improved = engine.local_search(
                inserted,
                engine.penalty_manager.booster_cost_evaluator(),
            )
            reoptimization_statistics = engine.local_search.statistics
            reoptimization_updates = int(reoptimization_statistics.num_updates)
            reoptimization_moves = int(reoptimization_statistics.num_moves)
            reoptimization_improving_moves = int(
                reoptimization_statistics.num_improving
            )
            try:
                reoptimized, reoptimized_changed = materialize(improved)
                reoptimized_evaluation = evaluator.evaluate(reoptimized)
            except (TypeError, ValueError):
                reoptimized_evaluation = None
            if (
                reoptimized_evaluation is not None
                and reoptimized_evaluation.feasible
                and float(reoptimized_evaluation.total_cost)
                < float(evaluation.total_cost) - 1.0e-9
            ):
                candidate = reoptimized
                evaluation = reoptimized_evaluation
                changed_duties = reoptimized_changed

        try:
            if not (stop_requested is not None and stop_requested()):
                candidate, evaluation, charging_evaluated = _refine_charging_once(
                    candidate,
                    evaluation,
                    evaluator=evaluator,
                    charging_policy=charging_policy,
                    stop_requested=stop_requested,
                )
        except (TypeError, ValueError) as error:
            # The insertion witness is already complete and feasible.  A
            # refinement failure is recorded, but it must not turn into a
            # false outsourcing event.
            reason = f"{type(error).__name__}: {error}"
            record(
                "charging-refinement",
                "optional_post_insertion_refinement",
                _candidate_rejection_status(reason),
                reason,
            )
            charging_evaluated = 0
        if committed_before != _committed_snapshot(
            evaluator,
            evaluation=evaluation,
        ):
            raise DynamicInsertionFailure("dynamic insertion changed committed history")
        accounting = DynamicInsertionAccounting(
            wall_seconds=perf_counter() - started,
            newly_revealed_count=len(revealed),
            kernel_updates=kernel_updates + reoptimization_updates,
            kernel_moves=kernel_moves + reoptimization_moves,
            kernel_improving_moves=(
                kernel_improving_moves + reoptimization_improving_moves
            ),
            changed_duty_count=changed_duties,
            complete_evaluations=evaluator.full_calls - before_calls,
            charging_candidates_evaluated=charging_evaluated,
            candidate_attempt_count=len(diagnostics),
            candidate_feasible_count=sum(
                item.status == INSERTED_AND_FULL_EVALUATION_FEASIBLE
                for item in diagnostics
            ),
            candidate_failure_reasons=tuple(
                item.failure_reason
                for item in diagnostics
                if item.failure_reason
            ),
            candidate_diagnostics=tuple(diagnostics),
        )
        return (
            DynamicInsertionResult(
                individual=candidate,
                evaluation=evaluation,
                accounting=accounting,
                status=INSERTED_AND_FULL_EVALUATION_FEASIBLE,
            ),
            accounting,
        )


def _direct_insertion_candidates(
    initial: DutyIndividual,
    customer_ids: tuple[str, ...],
):
    """Enumerate every unlocked asset/trip/position insertion deterministically.

    The native HGS repair returns one decoded solution.  This fallback is the
    explicit carrier audit: every currently registered physical asset is
    visited, then every editable existing trip position and one new trip are
    tried.  Multiple revealed customers are placed recursively, so a terminal
    candidate contains the whole batch rather than only its first order.
    """

    ordered_customers = tuple(dict.fromkeys(map(str, customer_ids)))
    seen: set[str] = set()

    def expand(
        current: DutyIndividual,
        customer_index: int,
        path: tuple[str, ...],
        changed_duty_ids: frozenset[str],
    ):
        if customer_index == len(ordered_customers):
            fingerprint = current.fingerprint
            if fingerprint in seen:
                return
            seen.add(fingerprint)
            candidate_id = "direct-" + "|".join(path)
            yield current, candidate_id, len(changed_duty_ids)
            return

        customer_id = ordered_customers[customer_index]
        for duty in sorted(
            current.duties,
            key=lambda item: item.physical_vehicle_id,
        ):
            for trip in duty.trips:
                if trip.trip_index in duty.locked_charging_trip_indices:
                    continue
                first_position = len(trip.locked_customer_prefix)
                for position in range(first_position, len(trip.customer_ids) + 1):
                    move = InsertUnservedMove(
                        action_id=(
                            f"{customer_id}:{duty.physical_vehicle_id}:"
                            f"trip-{trip.trip_index}:position-{position}"
                        ),
                        channel="dynamic_direct_insertion",
                        customer_id=customer_id,
                        target_duty_id=duty.physical_vehicle_id,
                        target_trip_index=trip.trip_index,
                        target_position=position,
                    )
                    candidate = _clear_dynamic_charging(
                        move.apply(current),
                        move.changed_duty_ids,
                    )
                    placement = (
                        f"{customer_id}@{duty.physical_vehicle_id}:"
                        f"trip-{trip.trip_index}:position-{position}"
                    )
                    yield from expand(
                        candidate,
                        customer_index + 1,
                        (*path, placement),
                        changed_duty_ids.union(move.changed_duty_ids),
                    )

            move = InsertUnservedMove(
                action_id=(
                    f"{customer_id}:{duty.physical_vehicle_id}:new-trip"
                ),
                channel="dynamic_direct_insertion",
                customer_id=customer_id,
                target_duty_id=duty.physical_vehicle_id,
                target_trip_index=None,
                target_position=0,
            )
            candidate = _clear_dynamic_charging(
                move.apply(current),
                move.changed_duty_ids,
            )
            placement = f"{customer_id}@{duty.physical_vehicle_id}:new-trip"
            yield from expand(
                candidate,
                customer_index + 1,
                (*path, placement),
                changed_duty_ids.union(move.changed_duty_ids),
            )

    yield from expand(initial, 0, (), frozenset())


def _clear_dynamic_charging(
    individual: DutyIndividual,
    changed_duty_ids: frozenset[str],
) -> DutyIndividual:
    """Invalidate only editable route schedules after a direct insertion."""

    changed = set(changed_duty_ids)
    duties = tuple(
        replace(
            duty,
            charging_sessions=tuple(
                session for session in duty.charging_sessions if session.locked
            ),
            schedule=None,
        )
        if duty.physical_vehicle_id in changed
        else duty
        for duty in individual.duties
    )
    return replace(
        individual,
        duties=duties,
        source="dynamic-direct-insertion",
    )


def _candidate_rejection_status(reason: str) -> str:
    text = str(reason).lower()
    if any(
        token in text
        for token in ("capacity", "payload", "volume", "demand")
    ):
        return "REJECTED_CAPACITY"
    if any(token in text for token in ("battery", "energy", "kwh", "soc")):
        return "REJECTED_ENERGY"
    if any(
        token in text
        for token in (
            "clock",
            "departure",
            "time window",
            "turnaround",
            "overlap",
            "schedule",
            "temporal",
        )
    ):
        return "REJECTED_TIME_INFEASIBLE"
    return "REJECTED_CANDIDATE"


def _insertion_failure_status(
    diagnostics: list[DynamicInsertionAttempt],
) -> str:
    reasons = [item for item in diagnostics if item.failure_reason]
    if reasons and all(
        item.status == "REJECTED_TIME_INFEASIBLE" for item in reasons
    ):
        return NOT_INSERTED_TIME_INFEASIBLE
    if reasons and all(item.status == "REJECTED_CAPACITY" for item in reasons):
        return NOT_INSERTED_CAPACITY
    if reasons and all(item.status == "REJECTED_ENERGY" for item in reasons):
        return NOT_INSERTED_ENERGY
    return NOT_INSERTED_CANDIDATE_EXHAUSTED


def _insertion_failure_summary(
    status: str,
    diagnostics: list[DynamicInsertionAttempt],
) -> str:
    if status == NOT_INSERTED_SEARCH_EXHAUSTED:
        return (
            f"{status}; stopped after {len(diagnostics)} complete candidates"
        )
    status_counts: dict[str, int] = {}
    for item in diagnostics:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1
    counts = ", ".join(
        f"{key}={status_counts[key]}"
        for key in sorted(status_counts)
    )
    return (
        f"{status}; exhausted {len(diagnostics)} candidates"
        + (f" ({counts})" if counts else "")
        + "; see candidate_diagnostics.json for each failure reason"
    )


def _refine_charging_once(
    incumbent: DutyIndividual,
    incumbent_evaluation: FullEvaluation,
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    stop_requested: Callable[[], bool] | None = None,
) -> tuple[DutyIndividual, FullEvaluation, int]:
    """Compare no-change with every P34 route/time/amount/site candidate once."""

    engine = MechanismProposalEngine(
        evaluator.context,
        charging_policy,
        include_charging_candidates=True,
        include_non_charging_candidates=False,
        stop_requested=stop_requested,
    )
    best = incumbent
    best_evaluation = incumbent_evaluation
    evaluated = 0
    for move in engine.propose(
        incumbent,
        incumbent_evaluation,
        evaluator.context.bundle.instance,
        include_whole_duty_type_exchange=False,
    ):
        if stop_requested is not None and stop_requested():
            break
        outcome = evaluate_move(
            incumbent,
            move,
            evaluator=evaluator,
            charging_policy=charging_policy,
            penalized_cost=lambda result: float(result.total_cost),
        )
        if outcome.status != CandidateStatus.EVALUATED:
            continue
        assert outcome.candidate is not None and outcome.evaluation is not None
        evaluated += 1
        if (
            outcome.evaluation.feasible
            and float(outcome.evaluation.total_cost)
            < float(best_evaluation.total_cost) - 1.0e-9
        ):
            best = outcome.candidate
            best_evaluation = outcome.evaluation
    return best, best_evaluation, evaluated


def _committed_snapshot(
    evaluator: DutyFullEvaluator,
    *,
    evaluation: FullEvaluation | None = None,
) -> tuple[object, ...]:
    state = evaluator.context.dynamic_state
    if state is None:
        return ()
    committed_ids = {
        *state.cut.completed_route_ids,
        *(route.vehicle_id for route in state.prior_committed_solution.routes),
    }
    locked_action_keys = {
        (
            action.vehicle_id,
            action.station_id,
            float(action.charge_start_second),
            float(action.energy_kwh),
        )
        for action in (
            *state.prior_committed_solution.charging_actions,
            *state.cut.locked_charging_actions,
        )
    }
    routes_by_id = {}
    if evaluation is None:
        routes_by_id.update(
            (route.vehicle_id, route)
            for route in state.prior_committed_solution.routes
        )
        history_source = (
            state.source_full_execution_solution or state.source_solution
        )
        routes_by_id.update(
            (route.vehicle_id, route)
            for route in history_source.routes
            if route.vehicle_id in state.cut.completed_route_ids
        )
        source_actions = (
            *state.prior_committed_solution.charging_actions,
            *state.cut.locked_charging_actions,
        )
    else:
        routes_by_id.update(
            (route.vehicle_id, route)
            for route in evaluation.prepared_solution.routes
            if route.vehicle_id in committed_ids
        )
        source_actions = tuple(
            action
            for action in evaluation.prepared_solution.charging_actions
            if action.vehicle_id in committed_ids
            or (
                action.vehicle_id,
                action.station_id,
                float(action.charge_start_second),
                float(action.energy_kwh),
            )
            in locked_action_keys
        )
    return (
        tuple(sorted(routes_by_id.items())),
        tuple(sorted(source_actions, key=lambda action: (
            action.vehicle_id,
            action.charge_day_offset,
            action.charge_start_second,
            action.station_id,
        ))),
        tuple(sorted(state.cut.frozen_arc_prefix_by_route_id.items())),
        tuple(
            (
                asset_id,
                asset.trigger_position_node_id,
                asset.trigger_time,
                asset.trigger_remaining_load_kg,
                asset.trigger_remaining_battery_kwh,
                asset.locked_arc,
                asset.executed_prefix,
            )
            for asset_id, asset in sorted(state.cut.asset_states.items())
            if asset.continuation_route_id is not None
        ),
    )
