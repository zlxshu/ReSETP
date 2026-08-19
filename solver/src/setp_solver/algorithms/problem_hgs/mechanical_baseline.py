"""Deterministic cheapest-feasible-insertion baseline for dynamic orders.

The baseline deliberately has no population, random generator, local search,
or route-wide optimisation.  One newly revealed customer is handled by three
ordered candidate classes: insertion into an already planned trip, a new trip
appended to an already used physical vehicle, then a one-customer direct trip
on a previously unused vehicle.  Complete-cost increment selects within each
class; stable structural identifiers break ties.

Every candidate is judged by :class:`DutyFullEvaluator`, so time windows,
capacity, battery/charging, finite fleet, and immutable execution history use
the same contract as the dynamic Problem-HGS path.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

from setp_solver.check import CUSTOMER_COVERAGE
from setp_solver.search.charging import solve_charging_fixed_route
from setp_solver.solution import ChargingAction, Route, physical_vehicle_id

from .evaluation import DutyFullEvaluator, FullEvaluation
from .model import (
    DutyChargingSession,
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
    assert_locks_preserved,
)

_TOL = 1.0e-9


@dataclass(frozen=True)
class MechanicalInsertionDecision:
    """Auditable record of one revealed-order decision."""

    customer_id: str
    candidate_class: str
    action: str
    physical_vehicle_id: str
    route_id: str
    future_trip_index: int
    visit_insertion_index: int
    inserted_after: str
    inserted_before: str
    base_total_cost: float
    resulting_total_cost: float
    incremental_total_cost: float
    insertion_positions_checked: int
    feasible_insertion_positions: int
    used_vehicles_checked: int
    feasible_appended_trips: int
    idle_vehicles_checked: int
    feasible_idle_dispatches: int
    rejected_candidates: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class MechanicalInsertionResult:
    """Selected future plan and its complete dynamic evaluation."""

    individual: DutyIndividual
    evaluation: FullEvaluation
    decision: MechanicalInsertionDecision


class MechanicalInsertionFailure(RuntimeError):
    """Structured no-candidate diagnosis for the defer policy."""

    def __init__(
        self,
        customer_id: str,
        *,
        class_diagnostics: dict[str, dict[str, object]],
        rejected_candidates: tuple[tuple[str, int], ...],
    ) -> None:
        self.customer_id = str(customer_id)
        self.class_diagnostics = {
            str(key): dict(value)
            for key, value in class_diagnostics.items()
        }
        self.rejected_candidates = tuple(
            (str(key), int(value))
            for key, value in rejected_candidates
        )
        super().__init__(
            "no existing insertion, used-vehicle appended trip, or unused-vehicle "
            "direct dispatch is fully feasible for "
            f"{self.customer_id}; "
            + ", ".join(
                f"{key}={value}"
                for key, value in self.rejected_candidates
            )
        )


@dataclass(frozen=True)
class _FeasibleCandidate:
    individual: DutyIndividual
    evaluation: FullEvaluation
    physical_vehicle_id: str
    future_trip_index: int
    visit_insertion_index: int
    inserted_after: str
    inserted_before: str


_EXISTING_TRIP_CLASS = "1_existing_planned_trip"
_APPENDED_TRIP_CLASS = "2_append_used_vehicle_trip"
_IDLE_DISPATCH_CLASS = "3_dispatch_unused_vehicle"


def insert_revealed_customer(
    current: DutyIndividual,
    customer_id: str,
    evaluator: DutyFullEvaluator,
) -> MechanicalInsertionResult:
    """Apply exactly one deterministic mechanical online decision.

    Candidate classes have strict priority.  Within each class, complete
    total-cost increment selects the candidate and stable structural
    identifiers resolve exact ties.
    """

    dynamic_state = evaluator.context.dynamic_state
    if dynamic_state is None:
        raise ValueError("mechanical online insertion requires a dynamic state")
    return _insert_one_customer(
        current,
        customer_id,
        evaluator,
        require_idle_at_dynamic_cut=True,
    )


def insert_initial_customer(
    current: DutyIndividual,
    customer_id: str,
    evaluator: DutyFullEvaluator,
) -> MechanicalInsertionResult:
    """Insert one initially visible customer under the same baseline rule.

    The initial visible set has no executed history or arrival sequence.  Its
    caller supplies a stable customer order and a static full evaluator; all
    registered empty duties are therefore available for direct dispatch.
    """

    if evaluator.context.dynamic_state is not None:
        raise ValueError("mechanical initial insertion requires a static context")
    return _insert_one_customer(
        current,
        customer_id,
        evaluator,
        require_idle_at_dynamic_cut=False,
    )


def _insert_one_customer(
    current: DutyIndividual,
    customer_id: str,
    evaluator: DutyFullEvaluator,
    *,
    require_idle_at_dynamic_cut: bool,
) -> MechanicalInsertionResult:
    customer_id = str(customer_id)
    if tuple(current.unserved_customers).count(customer_id) != 1:
        raise ValueError("revealed customer must occur once in unserved_customers")
    if set(current.unserved_customers) != {customer_id}:
        raise ValueError(
            "mechanical online insertion consumes exactly one revealed order"
        )

    base_evaluation = evaluator.evaluate(current)
    unexpected_base_violations = [
        violation
        for violation in base_evaluation.violations
        if not (
            violation.type == CUSTOMER_COVERAGE
            and violation.location == customer_id
            and "not served" in violation.detail
        )
    ]
    expected_unserved_markers = [
        violation
        for violation in base_evaluation.violations
        if violation.type == CUSTOMER_COVERAGE
        and violation.location == customer_id
        and "not served" in violation.detail
    ]
    if unexpected_base_violations or len(expected_unserved_markers) != 1:
        details = "; ".join(
            f"{item.type}:{item.location}:{item.detail}"
            for item in base_evaluation.violations
        )
        raise ValueError(
            "the unchanged current plan has violations beyond the one newly "
            f"unserved order: {details or 'missing coverage marker'}"
        )

    rejected: Counter[str] = Counter()
    insertion_positions_checked = 0
    feasible_insertions: list[_FeasibleCandidate] = []
    for duty_index, duty in enumerate(current.duties):
        for trip_index, trip in enumerate(duty.trips):
            visits = trip.effective_route_visits
            for visit_index in range(len(visits) + 1):
                customer_position = sum(
                    node_id in trip.customer_ids
                    for node_id in visits[:visit_index]
                )
                if customer_position < len(trip.locked_customer_prefix):
                    continue
                insertion_positions_checked += 1
                candidate = _insert_into_trip(
                    current,
                    duty_index=duty_index,
                    trip_index=trip_index,
                    visit_index=visit_index,
                    customer_position=customer_position,
                    customer_id=customer_id,
                )
                evaluated = _evaluate_candidate(
                    current,
                    candidate,
                    evaluator,
                    base_evaluation,
                    changed_asset_id=duty.physical_vehicle_id,
                    rejected=rejected,
                )
                if evaluated is None:
                    continue
                candidate, evaluation = evaluated
                route_id = _route_containing_customer(evaluation, customer_id)
                feasible_insertions.append(
                    _FeasibleCandidate(
                        individual=candidate,
                        evaluation=evaluation,
                        physical_vehicle_id=duty.physical_vehicle_id,
                        future_trip_index=int(trip.trip_index),
                        visit_insertion_index=visit_index,
                        inserted_after=(
                            duty.home_depot_id
                            if visit_index == 0
                            else visits[visit_index - 1]
                        ),
                        inserted_before=(
                            duty.home_depot_id
                            if visit_index == len(visits)
                            else visits[visit_index]
                        ),
                    )
                )
                if physical_vehicle_id(route_id) != duty.physical_vehicle_id:
                    raise AssertionError("complete evaluation moved the new order")

    if feasible_insertions:
        selected = min(
            feasible_insertions,
            key=lambda item: (
                item.evaluation.total_cost - base_evaluation.total_cost,
                item.physical_vehicle_id,
                item.future_trip_index,
                item.visit_insertion_index,
                item.individual.fingerprint,
            ),
        )
        return _result(
            customer_id,
            _EXISTING_TRIP_CLASS,
            "insert_existing_route",
            selected,
            base_evaluation,
            insertion_positions_checked,
            len(feasible_insertions),
            used_vehicles_checked=0,
            feasible_appended_trips=0,
            idle_vehicles_checked=0,
            feasible_idle_dispatches=0,
            rejected=rejected,
        )

    used_vehicles_checked = 0
    feasible_appended: list[_FeasibleCandidate] = []
    for duty_index, duty in sorted(
        enumerate(current.duties),
        key=lambda item: item[1].physical_vehicle_id,
    ):
        if not (duty.trips or duty.has_dynamic_commitment):
            continue
        used_vehicles_checked += 1
        candidate = _append_direct_trip(
            current,
            duty_index=duty_index,
            customer_id=customer_id,
        )
        evaluated = _evaluate_candidate(
            current,
            candidate,
            evaluator,
            base_evaluation,
            changed_asset_id=duty.physical_vehicle_id,
            rejected=rejected,
        )
        if evaluated is None:
            continue
        candidate, evaluation = evaluated
        route_id = _route_containing_customer(evaluation, customer_id)
        appended_trip_index = len(duty.trips) + 1
        feasible_appended.append(
            _FeasibleCandidate(
                individual=candidate,
                evaluation=evaluation,
                physical_vehicle_id=duty.physical_vehicle_id,
                future_trip_index=appended_trip_index,
                visit_insertion_index=0,
                inserted_after=duty.home_depot_id,
                inserted_before=duty.home_depot_id,
            )
        )
        if physical_vehicle_id(route_id) != duty.physical_vehicle_id:
            raise AssertionError("complete evaluation moved the appended order")

    if feasible_appended:
        selected = min(feasible_appended, key=_candidate_selection_key)
        return _result(
            customer_id,
            _APPENDED_TRIP_CLASS,
            "append_used_vehicle_trip",
            selected,
            base_evaluation,
            insertion_positions_checked,
            feasible_insertion_positions=0,
            used_vehicles_checked=used_vehicles_checked,
            feasible_appended_trips=len(feasible_appended),
            idle_vehicles_checked=0,
            feasible_idle_dispatches=0,
            rejected=rejected,
        )

    idle_vehicles_checked = 0
    feasible_idle: list[_FeasibleCandidate] = []
    for duty_index, duty in sorted(
        enumerate(current.duties),
        key=lambda item: item[1].physical_vehicle_id,
    ):
        if duty.trips or duty.has_dynamic_commitment or (
            require_idle_at_dynamic_cut
            and not _asset_is_idle_now(duty, evaluator)
        ):
            continue
        idle_vehicles_checked += 1
        candidate = _dispatch_direct(
            current,
            duty_index=duty_index,
            customer_id=customer_id,
        )
        evaluated = _evaluate_candidate(
            current,
            candidate,
            evaluator,
            base_evaluation,
            changed_asset_id=duty.physical_vehicle_id,
            rejected=rejected,
        )
        if evaluated is None:
            continue
        candidate, evaluation = evaluated
        route_id = _route_containing_customer(evaluation, customer_id)
        feasible_idle.append(
            _FeasibleCandidate(
                individual=candidate,
                evaluation=evaluation,
                physical_vehicle_id=duty.physical_vehicle_id,
                future_trip_index=1,
                visit_insertion_index=0,
                inserted_after=duty.home_depot_id,
                inserted_before=duty.home_depot_id,
            )
        )
        if physical_vehicle_id(route_id) != duty.physical_vehicle_id:
            raise AssertionError("complete evaluation moved the dispatched order")

    if feasible_idle:
        selected = min(feasible_idle, key=_candidate_selection_key)
        return _result(
            customer_id,
            _IDLE_DISPATCH_CLASS,
            "dispatch_idle_vehicle",
            selected,
            base_evaluation,
            insertion_positions_checked,
            feasible_insertion_positions=0,
            used_vehicles_checked=used_vehicles_checked,
            feasible_appended_trips=0,
            idle_vehicles_checked=idle_vehicles_checked,
            feasible_idle_dispatches=len(feasible_idle),
            rejected=rejected,
        )

    raise MechanicalInsertionFailure(
        customer_id,
        class_diagnostics={
            _EXISTING_TRIP_CLASS: {
                "candidates_checked": insertion_positions_checked,
                "feasible_candidates": len(feasible_insertions),
                "failure_scope": "complete_evaluation_or_history_check",
            },
            _APPENDED_TRIP_CLASS: {
                "candidates_checked": used_vehicles_checked,
                "feasible_candidates": len(feasible_appended),
                "failure_scope": "complete_evaluation_or_history_check",
            },
            _IDLE_DISPATCH_CLASS: {
                "candidates_checked": idle_vehicles_checked,
                "feasible_candidates": len(feasible_idle),
                "failure_scope": "complete_evaluation_or_history_check",
            },
        },
        rejected_candidates=tuple(sorted(rejected.items())),
    )


def _candidate_selection_key(
    item: _FeasibleCandidate,
) -> tuple[object, ...]:
    return (
        item.evaluation.total_cost,
        item.physical_vehicle_id,
        item.future_trip_index,
        item.visit_insertion_index,
        item.individual.fingerprint,
    )


def _insert_into_trip(
    current: DutyIndividual,
    *,
    duty_index: int,
    trip_index: int,
    visit_index: int,
    customer_position: int,
    customer_id: str,
) -> DutyIndividual:
    duty = current.duties[duty_index]
    trip = duty.trips[trip_index]
    customers = list(trip.customer_ids)
    customers.insert(customer_position, customer_id)
    visits = list(trip.effective_route_visits)
    visits.insert(visit_index, customer_id)
    changed_trip = replace(
        trip,
        customer_ids=tuple(customers),
        route_visits=tuple(visits),
    )
    trips = list(duty.trips)
    trips[trip_index] = changed_trip
    duties = list(current.duties)
    duties[duty_index] = replace(duty, trips=tuple(trips))
    return replace(
        current,
        duties=tuple(duties),
        unserved_customers=tuple(
            item for item in current.unserved_customers if item != customer_id
        ),
        source="mechanical-cheapest-feasible-insertion",
    )


def _dispatch_direct(
    current: DutyIndividual,
    *,
    duty_index: int,
    customer_id: str,
) -> DutyIndividual:
    duty = current.duties[duty_index]
    if duty.trips or duty.has_dynamic_commitment:
        raise ValueError("unused-vehicle dispatch requires an unused duty")
    duties = list(current.duties)
    duties[duty_index] = replace(
        duty,
        trips=(DutyTrip(trip_index=1, customer_ids=(customer_id,)),),
    )
    return replace(
        current,
        duties=tuple(duties),
        unserved_customers=tuple(
            item for item in current.unserved_customers if item != customer_id
        ),
        source="mechanical-first-feasible-idle-dispatch",
    )


def _append_direct_trip(
    current: DutyIndividual,
    *,
    duty_index: int,
    customer_id: str,
) -> DutyIndividual:
    duty = current.duties[duty_index]
    if not (duty.trips or duty.has_dynamic_commitment):
        raise ValueError("appended trip requires an already used vehicle")
    trip_index = len(duty.trips) + 1
    duties = list(current.duties)
    duties[duty_index] = replace(
        duty,
        trips=(
            *duty.trips,
            DutyTrip(trip_index=trip_index, customer_ids=(customer_id,)),
        ),
    )
    return replace(
        current,
        duties=tuple(duties),
        unserved_customers=tuple(
            item for item in current.unserved_customers if item != customer_id
        ),
        source="mechanical-append-used-vehicle-trip",
    )


def _asset_is_idle_now(
    duty: PhysicalVehicleDuty,
    evaluator: DutyFullEvaluator,
) -> bool:
    state = evaluator.context.dynamic_state
    assert state is not None
    asset = state.asset_states[duty.physical_vehicle_id]
    return float(asset.available_second) <= float(state.cut.trigger_second) + _TOL


def _evaluate_candidate(
    reference: DutyIndividual,
    candidate: DutyIndividual,
    evaluator: DutyFullEvaluator,
    reference_evaluation: FullEvaluation,
    *,
    changed_asset_id: str,
    rejected: Counter[str],
) -> tuple[DutyIndividual, FullEvaluation] | None:
    try:
        candidate = _with_current_first_trip_depot_charge(
            candidate,
            changed_asset_id=changed_asset_id,
            evaluator=evaluator,
        )
        assert_locks_preserved(reference, candidate)
        evaluation = evaluator.evaluate(candidate)
        if candidate.unserved_customers:
            rejected["unserved_customer"] += 1
            return None
        if not evaluation.feasible:
            for violation in evaluation.violations:
                rejected[f"violation:{violation.type}"] += 1
            return None
        _assert_unaffected_execution_preserved(
            reference_evaluation,
            evaluation,
            changed_asset_id=changed_asset_id,
        )
        return candidate, evaluation
    except (ArithmeticError, RuntimeError, ValueError) as exc:
        rejected[f"error:{type(exc).__name__}"] += 1
        rejected[
            f"error_detail:{type(exc).__name__}:{str(exc)}"
        ] += 1
        return None


def _with_current_first_trip_depot_charge(
    candidate: DutyIndividual,
    *,
    changed_asset_id: str,
    evaluator: DutyFullEvaluator,
) -> DutyIndividual:
    """Rebuild one static EV's T1 depot precharge through the P35 path.

    Dynamic preparation derives depot charging from inherited asset SOC.  A
    static initial-battery action must therefore be attached only to static
    candidates.  The shared fixed-route builder supplies the current curve
    metadata, duration, energy and certified depot start time.
    """

    if evaluator.context.dynamic_state is not None:
        return candidate
    matching = [
        (index, duty)
        for index, duty in enumerate(candidate.duties)
        if duty.physical_vehicle_id == changed_asset_id
    ]
    if len(matching) != 1:
        raise ValueError("changed asset must occur exactly once in candidate")
    duty_index, duty = matching[0]
    if duty.vehicle_type != "ev" or not duty.trips:
        return candidate
    if any(
        session.trip_index == 1
        and session.station_id == duty.home_depot_id
        and session.locked
        for session in duty.charging_sessions
    ):
        return candidate

    first_trip = duty.trips[0]
    route = Route(
        vehicle_id=duty.route_id(first_trip.trip_index),
        vehicle_type=duty.vehicle_type,
        home_depot_id=duty.home_depot_id,
        node_sequence=[
            duty.home_depot_id,
            *first_trip.effective_route_visits,
            duty.home_depot_id,
        ],
    )
    actions = solve_charging_fixed_route(
        route,
        evaluator.context.bundle.instance,
        evaluator.context.bundle.time_profile,
        evaluator.context.bundle.prices,
        strategy="naive",
        depot_charge_window_mode=evaluator.context.depot_charge_window_mode,
        carbon_profiles_by_day_offset=None,
    )
    depot_actions = [
        action for action in actions if action.station_id == duty.home_depot_id
    ]
    if len(depot_actions) > 1:
        raise ValueError("first EV trip produced multiple depot precharges")
    preserved = tuple(
        session
        for session in duty.charging_sessions
        if not (
            session.trip_index == 1
            and session.station_id == duty.home_depot_id
        )
    )
    rebuilt = tuple(
        DutyChargingSession(
            trip_index=1,
            station_id=action.station_id,
            energy_kwh=float(action.energy_kwh),
            occupancy_minutes=float(action.occupancy_minutes),
            charge_start_second=float(action.charge_start_second),
            charge_day_offset=int(action.charge_day_offset),
            start_energy_kwh=action.start_energy_kwh,
            end_energy_kwh=action.end_energy_kwh,
            charging_curve_id=action.charging_curve_id,
        )
        for action in depot_actions
    )
    duties = list(candidate.duties)
    duties[duty_index] = replace(
        duty,
        charging_sessions=tuple(
            sorted(
                (*preserved, *rebuilt),
                key=lambda session: (
                    int(session.trip_index),
                    session.station_id,
                    float(session.charge_start_second),
                    float(session.energy_kwh),
                ),
            )
        ),
    )
    return replace(candidate, duties=tuple(duties))


def _assert_unaffected_execution_preserved(
    before: FullEvaluation,
    after: FullEvaluation,
    *,
    changed_asset_id: str,
) -> None:
    before_trips = tuple(
        sorted(
            (
                trip
                for trip in before.certificate.trips
                if trip.physical_vehicle_id != changed_asset_id
            ),
            key=lambda trip: trip.route_id,
        )
    )
    after_trips = tuple(
        sorted(
            (
                trip
                for trip in after.certificate.trips
                if trip.physical_vehicle_id != changed_asset_id
            ),
            key=lambda trip: trip.route_id,
        )
    )
    if before_trips != after_trips:
        raise ValueError("candidate changed another asset's planned timing")

    before_routes = _unaffected_routes(
        before.prepared_solution.routes,
        changed_asset_id,
    )
    after_routes = _unaffected_routes(
        after.prepared_solution.routes,
        changed_asset_id,
    )
    if before_routes != after_routes:
        raise ValueError("candidate changed another asset's planned route")

    before_actions = _unaffected_actions(
        before.prepared_solution.charging_actions,
        changed_asset_id,
    )
    after_actions = _unaffected_actions(
        after.prepared_solution.charging_actions,
        changed_asset_id,
    )
    if before_actions != after_actions:
        raise ValueError("candidate changed another asset's charging plan")


def _unaffected_routes(
    routes: list[Route],
    changed_asset_id: str,
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        sorted(
            (
                route.vehicle_id,
                route.vehicle_type,
                route.home_depot_id,
                tuple(route.node_sequence),
            )
            for route in routes
            if physical_vehicle_id(route.vehicle_id) != changed_asset_id
        )
    )


def _unaffected_actions(
    actions: list[ChargingAction],
    changed_asset_id: str,
) -> tuple[ChargingAction, ...]:
    return tuple(
        sorted(
            (
                action
                for action in actions
                if physical_vehicle_id(action.vehicle_id) != changed_asset_id
            ),
            key=lambda action: (
                action.vehicle_id,
                action.station_id,
                float(action.charge_start_second),
                float(action.energy_kwh),
            ),
        )
    )


def _route_containing_customer(
    evaluation: FullEvaluation,
    customer_id: str,
) -> str:
    route_ids = [
        route.vehicle_id
        for route in evaluation.prepared_solution.routes
        if customer_id in route.node_sequence[1:-1]
    ]
    if len(route_ids) != 1:
        raise AssertionError("revealed customer must occur on exactly one route")
    return route_ids[0]


def _result(
    customer_id: str,
    candidate_class: str,
    action: str,
    selected: _FeasibleCandidate,
    base_evaluation: FullEvaluation,
    insertion_positions_checked: int,
    feasible_insertion_positions: int,
    used_vehicles_checked: int,
    feasible_appended_trips: int,
    idle_vehicles_checked: int,
    feasible_idle_dispatches: int,
    rejected: Counter[str],
) -> MechanicalInsertionResult:
    route_id = _route_containing_customer(selected.evaluation, customer_id)
    decision = MechanicalInsertionDecision(
        customer_id=customer_id,
        candidate_class=candidate_class,
        action=action,
        physical_vehicle_id=selected.physical_vehicle_id,
        route_id=route_id,
        future_trip_index=selected.future_trip_index,
        visit_insertion_index=selected.visit_insertion_index,
        inserted_after=selected.inserted_after,
        inserted_before=selected.inserted_before,
        base_total_cost=float(base_evaluation.total_cost),
        resulting_total_cost=float(selected.evaluation.total_cost),
        incremental_total_cost=(
            float(selected.evaluation.total_cost)
            - float(base_evaluation.total_cost)
        ),
        insertion_positions_checked=insertion_positions_checked,
        feasible_insertion_positions=feasible_insertion_positions,
        used_vehicles_checked=used_vehicles_checked,
        feasible_appended_trips=feasible_appended_trips,
        idle_vehicles_checked=idle_vehicles_checked,
        feasible_idle_dispatches=feasible_idle_dispatches,
        rejected_candidates=tuple(sorted(rejected.items())),
    )
    return MechanicalInsertionResult(
        individual=selected.individual,
        evaluation=selected.evaluation,
        decision=decision,
    )
