"""Safe charging reconstruction for changed physical-vehicle duties.

v1 2026-08-07: wrap the existing nonlinear route repair and multi-trip
certificate without changing either upstream module.  Every scientific choice
is an explicit input; identity, customer order, dynamic locks, and the final
battery ledger are checked after reconstruction.

v2 2026-08-07: use local pre-horizon time for a first depot charge and the
actual inter-trip gap for later depot charges in all registered window modes.

v3 2026-08-07: anchor every depot action to the preceding trip's actual end
energy before certificate validation.  Locked trips retain their complete
registered charging ledger; unlocked later trips may be repaired without
rewriting an earlier dynamic commitment.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging,
)
from setp_solver.charging_action import _curve_aware_action
from setp_solver.search.multitrip_schedule import (
    STATIC_PREHORIZON_SECONDS,
    prepare_multitrip_solution,
    route_timing,
    select_certified_depot_charge_start,
)
from setp_solver.solution import ChargingAction, Route, Solution, physical_vehicle_id

from .evaluation import DutyEvaluationContext
from .model import (
    DutyChargingSession,
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
    assert_locks_preserved,
)


@dataclass(frozen=True)
class ChargingRepairPolicy:
    """All externally selected charging semantics; no hidden defaults."""

    strategy: str
    carbon_weight: float
    depot_charge_window_mode: str
    charge_timing_policy: str
    charge_amount_strategy: str
    public_station_candidate_mode: str
    carbon_profiles_by_day_offset: Mapping[
        int, list[dict[str, Any]]
    ] | None


def repair_changed_duties(
    reference: DutyIndividual,
    candidate: DutyIndividual,
    *,
    changed_duty_ids: set[str],
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
) -> DutyIndividual:
    """Rebuild only changed EV ledgers and preserve every locked decision."""

    if policy.depot_charge_window_mode != context.depot_charge_window_mode:
        raise ValueError(
            "charging repair and full evaluation use different depot windows"
        )

    candidate_by_id = {
        duty.physical_vehicle_id: duty for duty in candidate.duties
    }
    reference_by_id = {
        duty.physical_vehicle_id: duty for duty in reference.duties
    }
    unknown = set(changed_duty_ids).difference(candidate_by_id)
    if unknown:
        raise ValueError(f"charging repair received unknown duties: {sorted(unknown)}")

    rebuilt: list[PhysicalVehicleDuty] = []
    for duty in candidate.duties:
        if duty.physical_vehicle_id not in changed_duty_ids:
            rebuilt.append(duty)
            continue
        if duty.vehicle_type == "cv":
            if duty.charging_sessions:
                raise ValueError("CV duty cannot retain charging sessions")
            rebuilt.append(duty)
            continue
        rebuilt.append(
            _repair_one_ev_duty(
                reference_by_id.get(duty.physical_vehicle_id, duty),
                duty,
                context=context,
                policy=policy,
            )
        )

    result = replace(candidate, duties=tuple(rebuilt))
    assert_locks_preserved(reference, result)
    return result


def _repair_one_ev_duty(
    reference: PhysicalVehicleDuty,
    duty: PhysicalVehicleDuty,
    *,
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
) -> PhysicalVehicleDuty:
    if not duty.trips:
        if duty.charging_sessions:
            raise ValueError("an idle EV duty cannot retain charging sessions")
        return duty

    bundle = context.bundle
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    reference_sessions_by_trip: dict[int, list[DutyChargingSession]] = {}
    for session in reference.charging_sessions:
        reference_sessions_by_trip.setdefault(
            int(session.trip_index), []
        ).append(session)
    locked_trip_indices = reference.locked_charging_trip_indices
    for trip_index in locked_trip_indices:
        sessions = reference_sessions_by_trip.get(trip_index, [])
        if any(not session.locked for session in sessions):
            raise ValueError(
                "one trip cannot mix locked and unlocked charging sessions"
            )

    routes: list[Route] = []
    actions: list[ChargingAction] = []
    # The single-route repair builds a provisional, same-day local action.
    # The physical-duty certificate below places and re-times that action in
    # the approved first-trip or inter-trip calendar window.
    route_repair_window_mode = "same_day_predeparture"
    for trip in duty.trips:
        temporary_id = duty.route_id(trip.trip_index)
        route = Route(
            vehicle_id=temporary_id,
            vehicle_type="ev",
            home_depot_id=duty.home_depot_id,
            node_sequence=[
                duty.home_depot_id,
                *trip.effective_route_visits,
                duty.home_depot_id,
            ],
        )
        if int(trip.trip_index) in locked_trip_indices:
            routes.append(route)
            actions.extend(
                _session_to_action(session, temporary_id)
                for session in reference_sessions_by_trip[trip.trip_index]
            )
            continue
        repaired_route, repaired_actions = repair_route_charging(
            route,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
            strategy=policy.strategy,
            carbon_weight=float(policy.carbon_weight),
            depot_charge_window_mode=route_repair_window_mode,
            charge_timing_policy=policy.charge_timing_policy,
            charge_amount_strategy=policy.charge_amount_strategy,
            carbon_profiles_by_day_offset=(
                policy.carbon_profiles_by_day_offset
            ),
            public_station_candidate_mode=(
                policy.public_station_candidate_mode
            ),
        )
        _assert_customer_order(
            trip.customer_ids,
            repaired_route,
            node_lookup,
        )
        routes.append(repaired_route)
        actions.extend(repaired_actions)

    anchored = _anchor_duty_depot_actions(
        routes,
        actions,
        locked_trip_indices=locked_trip_indices,
        context=context,
        policy=policy,
    )
    prepared, _certificate = prepare_multitrip_solution(
        Solution(routes=routes, charging_actions=anchored),
        bundle.instance,
        bundle.prices,
        depot_charge_window_mode=policy.depot_charge_window_mode,
    )
    physical_ids = {
        physical_vehicle_id(route.vehicle_id) for route in prepared.routes
    }
    if len(physical_ids) != 1:
        raise ValueError(
            "one Duty was split across physical vehicles during charging repair"
        )
    prepared_routes = sorted(
        prepared.routes,
        key=lambda route: int(route.vehicle_id.rsplit("#T", 1)[1]),
    )
    if len(prepared_routes) != len(duty.trips):
        raise ValueError("charging repair changed the number of duty trips")
    rebuilt_trips: list[DutyTrip] = []
    for expected, route in zip(duty.trips, prepared_routes, strict=True):
        trip_index = int(route.vehicle_id.rsplit("#T", 1)[1])
        if trip_index != int(expected.trip_index):
            raise ValueError("charging repair reordered the duty trip chain")
        customers = tuple(
            node_id
            for node_id in route.node_sequence[1:-1]
            if node_lookup[node_id].node_type.lower() == "c"
        )
        if customers != expected.customer_ids:
            raise ValueError("charging repair changed customer order")
        rebuilt_trips.append(
            DutyTrip(
                trip_index=trip_index,
                customer_ids=customers,
                locked_customer_prefix=expected.locked_customer_prefix,
                route_visits=tuple(route.node_sequence[1:-1]),
            )
        )

    rebuilt_sessions = tuple(
        sorted(
            (
                _action_to_session(action, reference)
                for action in prepared.charging_actions
            ),
            key=lambda session: (
                session.trip_index,
                session.station_id,
                session.charge_start_second,
                session.energy_kwh,
            ),
        )
    )
    _assert_locked_sessions_exact(reference, rebuilt_sessions)
    rebuilt = replace(
        duty,
        trips=tuple(rebuilt_trips),
        charging_sessions=rebuilt_sessions,
    )
    _verify_prepared_ledger(rebuilt, context)
    return rebuilt


def _anchor_duty_depot_actions(
    routes: list[Route],
    actions: list[ChargingAction],
    *,
    locked_trip_indices: frozenset[int],
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
) -> list[ChargingAction]:
    """Rebase provisional route actions onto one continuous vehicle ledger."""

    instance = context.bundle.instance
    prices = context.bundle.prices
    inherited = float(prices.initial_ev_battery_kwh)
    ordered_routes = sorted(
        routes,
        key=lambda route: int(route.vehicle_id.rsplit("#T", 1)[1]),
    )
    by_route: dict[str, list[ChargingAction]] = {
        route.vehicle_id: [
            action
            for action in actions
            if action.vehicle_id == route.vehicle_id
        ]
        for route in ordered_routes
    }
    anchored: list[ChargingAction] = []
    previous_end = inherited
    previous_return: float | None = None

    for position, route in enumerate(ordered_routes):
        trip_index = int(route.vehicle_id.rsplit("#T", 1)[1])
        route_actions = by_route[route.vehicle_id]
        depot_actions = [
            action
            for action in route_actions
            if action.station_id == route.home_depot_id
        ]
        public_actions = [
            action
            for action in route_actions
            if action.station_id != route.home_depot_id
        ]
        if len(depot_actions) > 1:
            raise ValueError("one duty trip has multiple depot charge actions")

        timing = route_timing(
            route,
            instance,
            prices,
            charging_actions=route_actions,
            validate_battery=False,
        )
        depot_action = depot_actions[0] if depot_actions else None
        if trip_index in locked_trip_indices:
            selected_depot = depot_action
            departure_energy = previous_end + sum(
                float(action.energy_kwh) for action in depot_actions
            )
        else:
            provisional_target = previous_end
            if depot_action is not None:
                provisional_target = float(
                    depot_action.end_energy_kwh
                    if depot_action.end_energy_kwh is not None
                    else inherited + float(depot_action.energy_kwh)
                )
            required_departure = timing.required_departure_battery_kwh
            if required_departure is not None:
                if previous_end > float(required_departure) + 1e-7:
                    raise ValueError(
                        "continuous duty energy exceeds the fixed public-charge "
                        "departure state"
                    )
                target = float(required_departure)
            else:
                minimum = max(
                    0.0,
                    float(timing.drive_energy_kwh)
                    - sum(float(action.energy_kwh) for action in public_actions),
                )
                target = max(previous_end, provisional_target, minimum)
            energy = max(0.0, target - previous_end)
            selected_depot = None
            if energy > 1e-9:
                selected_depot = _curve_aware_action(
                    vehicle_id=route.vehicle_id,
                    station_id=route.home_depot_id,
                    start_energy_kwh=previous_end,
                    energy_kwh=energy,
                    reference_power_kw=float(prices.depot_charge_power_kw),
                    prices=prices,
                    instance=instance,
                )
                duration = float(selected_depot.occupancy_minutes) * 60.0
                if position == 0:
                    if policy.depot_charge_window_mode == "same_day_predeparture":
                        earliest = 0.0
                        latest = float(timing.earliest_departure_second) - duration
                        mode = "same_day_predeparture"
                    else:
                        earliest = -STATIC_PREHORIZON_SECONDS
                        latest = -duration
                        mode = "prev_night"
                else:
                    if previous_return is None:
                        raise AssertionError("missing preceding trip return")
                    earliest = previous_return
                    latest = float(timing.earliest_departure_second) - duration
                    mode = "full_gap"
                start, offset = select_certified_depot_charge_start(
                    selected_depot,
                    earliest,
                    latest,
                    instance,
                    prices,
                    context.bundle.time_profile,
                    mode=mode,
                    strategy=policy.strategy,
                    carbon_weight=float(policy.carbon_weight),
                    charge_timing_policy=policy.charge_timing_policy,
                    carbon_profiles_by_day_offset=(
                        policy.carbon_profiles_by_day_offset
                    ),
                )
                selected_depot = replace(
                    selected_depot,
                    charge_start_second=float(start),
                    charge_day_offset=int(offset),
                )
            departure_energy = previous_end + energy

        if selected_depot is not None:
            anchored.append(selected_depot)
        anchored.extend(public_actions)
        previous_end = (
            departure_energy
            + sum(float(action.energy_kwh) for action in public_actions)
            - float(timing.drive_energy_kwh)
        )
        if previous_end < -1e-7:
            raise ValueError("continuous duty battery falls below zero")
        previous_return = float(timing.return_second)

    return anchored


def _verify_prepared_ledger(
    duty: PhysicalVehicleDuty,
    context: DutyEvaluationContext,
) -> None:
    solution = DutyIndividual(duties=(duty,), source="charging-ledger-check").to_solution()
    repeated, _ = prepare_multitrip_solution(
        solution,
        context.bundle.instance,
        context.bundle.prices,
        depot_charge_window_mode=context.depot_charge_window_mode,
    )
    if repeated != solution:
        raise ValueError("charging repair did not close under full ledger replay")


def _assert_customer_order(
    expected: tuple[str, ...],
    route: Route,
    node_lookup: Mapping[str, Any],
) -> None:
    actual = tuple(
        node_id
        for node_id in route.node_sequence
        if node_lookup[node_id].node_type.lower() == "c"
    )
    if actual != expected:
        raise ValueError("route charging repair changed customer order")


def _session_to_action(
    session: DutyChargingSession,
    vehicle_id: str,
) -> ChargingAction:
    return ChargingAction(
        vehicle_id=vehicle_id,
        station_id=session.station_id,
        energy_kwh=float(session.energy_kwh),
        occupancy_minutes=float(session.occupancy_minutes),
        charge_start_second=float(session.charge_start_second),
        charge_day_offset=int(session.charge_day_offset),
        start_energy_kwh=session.start_energy_kwh,
        end_energy_kwh=session.end_energy_kwh,
        charging_curve_id=session.charging_curve_id,
    )


def _action_to_session(
    action: ChargingAction,
    reference: PhysicalVehicleDuty,
) -> DutyChargingSession:
    trip_index = int(action.vehicle_id.rsplit("#T", 1)[1])
    key = _action_value_key(action, trip_index)
    locked = any(
        session.locked and _session_value_key(session) == key
        for session in reference.charging_sessions
    )
    return DutyChargingSession(
        trip_index=trip_index,
        station_id=action.station_id,
        energy_kwh=float(action.energy_kwh),
        occupancy_minutes=float(action.occupancy_minutes),
        charge_start_second=float(action.charge_start_second),
        charge_day_offset=int(action.charge_day_offset),
        start_energy_kwh=action.start_energy_kwh,
        end_energy_kwh=action.end_energy_kwh,
        charging_curve_id=action.charging_curve_id,
        locked=locked,
    )


def _assert_locked_sessions_exact(
    reference: PhysicalVehicleDuty,
    rebuilt: tuple[DutyChargingSession, ...],
) -> None:
    expected = {
        _session_value_key(session)
        for session in reference.charging_sessions
        if session.locked
    }
    actual = {
        _session_value_key(session)
        for session in rebuilt
        if session.locked
    }
    if actual != expected:
        raise ValueError("charging repair changed a locked charging session")


def _session_value_key(session: DutyChargingSession) -> tuple[object, ...]:
    return (
        int(session.trip_index),
        session.station_id,
        float(session.energy_kwh),
        float(session.occupancy_minutes),
        float(session.charge_start_second),
        int(session.charge_day_offset),
        session.start_energy_kwh,
        session.end_energy_kwh,
        session.charging_curve_id,
    )


def _action_value_key(
    action: ChargingAction,
    trip_index: int,
) -> tuple[object, ...]:
    return (
        int(trip_index),
        action.station_id,
        float(action.energy_kwh),
        float(action.occupancy_minutes),
        float(action.charge_start_second),
        int(action.charge_day_offset),
        action.start_energy_kwh,
        action.end_energy_kwh,
        action.charging_curve_id,
    )
