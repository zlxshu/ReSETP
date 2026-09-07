"""Exact-asset multi-trip scheduling for one certificate-driven dynamic cut.

The static E3 scheduler creates a fresh fleet from route rows.  That is useful
before a day starts, but it is the wrong contract after vehicles have already
left the depots.  This module is deliberately separate: it cuts one sealed
multi-trip certificate at an absolute trigger time, carries forward the exact
physical vehicles and EV battery ledger, and schedules only the supplied open
routes on those assets.

This is a feasibility witness, not a route search and not a proof of the
minimum fleet size.  Public-station charging is intentionally outside this P1
gate.  The old static preparation path is not modified.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

from ..charging_curve import (
    L100_CONTROL,
    ChargingCurveError,
    PiecewiseChargingCurve,
    curve_for_charging_node,
)
from ..cost import (
    _arc_loads,
    _price,
    best_charging_action_start,
    charging_action_slot_breakdown,
    charging_curve_for_action,
    ev_instance_arc_energy_kwh,
)
from ..instance_loader import Instance, Node, RoadProfileMatrices
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import (
    ChargingAction,
    Route,
    Solution,
    physical_vehicle_id,
    route_trip_vehicle_id,
)
from .certificate_execution import (
    COMPLETED,
    IN_PROGRESS,
    NOT_STARTED,
    _replay_trip,
    build_certificate_execution_ledger,
)
from .multitrip_schedule import (
    CHARGE_MODE_ON_DEMAND,
    MultiTripCertificate,
    ScheduledTrip,
    route_timing,
)

DYNAMIC_CONTRACT_ID = "E7_DYNAMIC_MULTITRIP_V1"
_TOL = 1e-6
_DAY_SECONDS = 86_400.0
_MAX_ASSIGNMENT_STATES = 100_000


@dataclass(frozen=True)
class DynamicAssetState:
    """One frozen physical vehicle at its next legal release boundary."""

    physical_vehicle_id: str
    vehicle_type: str
    home_depot_id: str
    available_second: float
    remaining_battery_kwh: float
    next_trip_index: int
    position_node_id: str | None = None
    remaining_load_kg: float = 0.0
    continuation_route_id: str | None = None
    in_progress_route_id: str | None = None
    continuation_trip_index: int | None = None
    executed_prefix: tuple[str, ...] = ()
    frozen_arcs: tuple[tuple[str, str], ...] = ()
    locked_arc: tuple[str, str] | None = None
    editable_suffix: tuple[str, ...] = ()
    trigger_position_node_id: str | None = None
    release_node_id: str | None = None
    virtual_origin_node_id: str | None = None
    trigger_time: float | None = None
    trigger_arc_progress: float | None = None
    trigger_remaining_load_kg: float | None = None
    trigger_remaining_battery_kwh: float | None = None

    def __post_init__(self) -> None:
        # Battery energy inherited across stage cuts accumulates float dust;
        # an exactly-empty battery can land a few 1e-15 below zero and the
        # charging curve's domain check is exact. Dust is snapped to zero,
        # real negative energy still fails loudly.
        for field_name in ("remaining_battery_kwh", "trigger_remaining_battery_kwh"):
            value = getattr(self, field_name)
            if value is not None and -_TOL < float(value) < 0.0:
                object.__setattr__(self, field_name, 0.0)


@dataclass(frozen=True)
class CertificateCut:
    """Immutable partition and asset ledger at one absolute trigger time."""

    trigger_second: float
    completed_route_ids: tuple[str, ...]
    in_progress_route_ids: tuple[str, ...]
    editable_route_ids: tuple[str, ...]
    locked_charging_actions: tuple[ChargingAction, ...]
    asset_states: Mapping[str, DynamicAssetState]
    frozen_arc_prefix_by_route_id: Mapping[
        str, tuple[tuple[str, str], ...]
    ] = field(default_factory=lambda: MappingProxyType({}))
    unexecuted_arc_suffix_by_route_id: Mapping[
        str, tuple[tuple[str, str], ...]
    ] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class _RouteProfile:
    route: Route
    preferred_departure_second: float
    latest_departure_second: float
    drive_energy_kwh: float
    public_charge_energy_kwh: float = 0.0
    required_departure_battery_kwh: float | None = None
    public_charging_actions: tuple[ChargingAction, ...] = ()


@dataclass
class _WorkingAsset:
    state: DynamicAssetState
    available_second: float
    battery_kwh: float
    next_trip_index: int


@dataclass(frozen=True)
class _Assignment:
    route: Route
    physical_vehicle_id: str
    trip_index: int
    departure_second: float
    return_second: float
    drive_energy_kwh: float
    departure_battery_kwh: float | None = None
    return_battery_kwh: float | None = None
    public_charging_actions: tuple[ChargingAction, ...] = ()


def cut_certificate_at_trigger(
    solution: Solution,
    certificate: MultiTripCertificate,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    trigger_second: float,
) -> CertificateCut:
    """Cut a sealed static certificate without inventing a new clock.

    A trip is editable only when it has not departed.  A charge whose absolute
    start is at or before the trigger is also frozen.  If such a charge is still
    running, the asset is released at its certified end with the full charged
    energy; this avoids both double charging and treating the vehicle as free
    during an action that has already begun.
    """

    trigger = float(trigger_second)
    if not _finite(trigger):
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: trigger time is not finite")
    ledger = build_certificate_execution_ledger(solution, certificate, instance, prices)
    route_by_id = {route.vehicle_id: route for route in solution.routes}
    trip_by_id = {trip.route_id: trip for trip in certificate.trips}

    completed: list[str] = []
    in_progress: list[str] = []
    editable: list[str] = []
    for route_id, execution in ledger.routes.items():
        state = execution.state_at(trigger)
        if state == COMPLETED:
            completed.append(route_id)
        elif state == IN_PROGRESS:
            in_progress.append(route_id)
        elif state == NOT_STARTED:
            editable.append(route_id)
        else:  # pragma: no cover - Literal guard
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: unknown execution state {state!r}")

    actions_by_asset: dict[str, list[tuple[float, float, ChargingAction]]] = {}
    actions_by_route: dict[str, list[ChargingAction]] = {}
    route_to_asset = {
        route_id: execution.physical_vehicle_id
        for route_id, execution in ledger.routes.items()
    }
    locked_actions: list[ChargingAction] = []
    for action in solution.charging_actions:
        actions_by_route.setdefault(action.vehicle_id, []).append(action)
        try:
            asset_id = route_to_asset[action.vehicle_id]
        except KeyError as exc:
            raise ValueError(
                f"{DYNAMIC_CONTRACT_ID}: charging action is detached from {action.vehicle_id}"
            ) from exc
        start = _absolute_charge_start(action)
        end = start + float(action.occupancy_minutes) * 60.0
        actions_by_asset.setdefault(asset_id, []).append((start, end, action))
        if start <= trigger:
            locked_actions.append(action)

    battery_cap = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    initial_battery = (
        _price(prices, "initial_ev_battery_kwh")
        if certificate.initial_battery_kwh is None
        else float(certificate.initial_battery_kwh)
    )
    states: dict[str, DynamicAssetState] = {}
    frozen_arcs: dict[str, tuple[tuple[str, str], ...]] = {}
    unexecuted_arcs: dict[str, tuple[tuple[str, str], ...]] = {}
    for route_id, route in route_by_id.items():
        arcs = tuple(zip(route.node_sequence, route.node_sequence[1:]))
        if route_id in completed:
            frozen_arcs[route_id] = arcs
            unexecuted_arcs[route_id] = ()
        elif route_id in editable:
            frozen_arcs[route_id] = ()
            unexecuted_arcs[route_id] = arcs
    for asset_id, asset in ledger.assets.items():
        chain = [ledger.routes[route_id] for route_id in asset.route_ids]
        started = [trip for trip in chain if trip.state_at(trigger) != NOT_STARTED]
        running = [trip for trip in chain if trip.state_at(trigger) == IN_PROGRESS]
        if running:
            execution = running[0]
            live_state, frozen, unexecuted = _in_progress_asset_state(
                route_by_id[execution.route_id],
                trip_by_id[execution.route_id],
                execution,
                instance,
                prices,
                actions_by_route.get(execution.route_id, ()),
                trigger,
            )
            states[asset_id] = live_state
            frozen_arcs[execution.route_id] = frozen
            unexecuted_arcs[execution.route_id] = unexecuted
            continue
        available = trigger

        if asset.vehicle_type == "ev":
            battery = initial_battery - sum(trip.drive_energy_kwh for trip in started)
            for start, end, action in actions_by_asset.get(asset_id, []):
                if start <= trigger:
                    battery += float(action.energy_kwh)
                    if end > trigger:
                        available = max(available, end)
            if battery < -_TOL or battery > battery_cap + _TOL:
                raise ValueError(
                    f"{DYNAMIC_CONTRACT_ID}: {asset_id} battery {battery:.9f} is outside capacity"
                )
            battery = min(battery_cap, max(0.0, battery))
            trigger_battery = battery
            for start, end, action in actions_by_asset.get(asset_id, []):
                if start <= trigger < end:
                    trigger_battery = _battery_during_actions(
                        battery - float(action.energy_kwh),
                        (action,),
                        trigger,
                        instance,
                        prices,
                    )
                    break
        else:
            battery = 0.0
            trigger_battery = 0.0

        next_index = max((trip.trip_index for trip in started), default=0) + 1
        states[asset_id] = DynamicAssetState(
            physical_vehicle_id=asset_id,
            vehicle_type=asset.vehicle_type,
            home_depot_id=asset.home_depot_id,
            available_second=float(available),
            remaining_battery_kwh=float(battery),
            next_trip_index=int(next_index),
            position_node_id=asset.home_depot_id,
            remaining_load_kg=0.0,
            trigger_position_node_id=asset.home_depot_id,
            release_node_id=asset.home_depot_id,
            trigger_time=trigger,
            trigger_remaining_load_kg=0.0,
            trigger_remaining_battery_kwh=float(trigger_battery),
        )

    locked_actions.sort(
        key=lambda action: (
            _absolute_charge_start(action),
            action.vehicle_id,
            action.station_id,
        )
    )
    return CertificateCut(
        trigger_second=trigger,
        completed_route_ids=tuple(sorted(completed)),
        in_progress_route_ids=tuple(sorted(in_progress)),
        editable_route_ids=tuple(sorted(editable)),
        locked_charging_actions=tuple(locked_actions),
        asset_states=MappingProxyType(dict(states)),
        frozen_arc_prefix_by_route_id=MappingProxyType(dict(frozen_arcs)),
        unexecuted_arc_suffix_by_route_id=MappingProxyType(
            dict(unexecuted_arcs)
        ),
    )


def cut_dynamic_certificate_at_trigger(
    solution: Solution,
    certificate: MultiTripCertificate,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    inherited_asset_states: Mapping[str, DynamicAssetState],
    previous_stage_start_second: float,
    trigger_second: float,
    inherited_locked_charging_actions: Sequence[ChargingAction] = (),
) -> CertificateCut:
    """Cut a previously prepared dynamic continuation for the next stage.

    Unlike the first static cut, the dynamic certificate may start at trip 2
    or later and may use only part of the inherited fleet.  The caller must
    therefore provide the complete previous asset map.  Assets unused in the
    preceding continuation remain present instead of silently disappearing.
    """

    previous_stage_start = float(previous_stage_start_second)
    trigger = float(trigger_second)
    if not _finite(previous_stage_start) or not _finite(trigger):
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: dynamic cut time is not finite")
    if trigger < previous_stage_start - _TOL:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: next trigger precedes the previous stage")
    same_stage = abs(trigger - previous_stage_start) <= _TOL

    validate_dynamic_multitrip_certificate(
        solution,
        certificate,
        instance,
        prices,
        asset_states=inherited_asset_states,
        stage_start_second=previous_stage_start,
        locked_charging_actions=inherited_locked_charging_actions,
    )
    battery_cap = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    inherited = _validate_asset_states(inherited_asset_states, battery_cap)
    trip_by_id = {trip.route_id: trip for trip in certificate.trips}
    route_by_id = {route.vehicle_id: route for route in solution.routes}

    completed: list[str] = []
    in_progress: list[str] = []
    editable: list[str] = []
    for trip in certificate.trips:
        execution_state = _trip_state(trip, trigger)
        inherited_state = inherited.get(trip.physical_vehicle_id)
        tracked_route_id = (
            inherited_state.continuation_route_id
            if inherited_state is not None
            else None
        ) or (
            inherited_state.in_progress_route_id
            if inherited_state is not None
            else None
        )
        carried_in_progress = (
            inherited_state is not None
            and tracked_route_id == trip.route_id
            and (
                same_stage
                or trigger < float(inherited_state.available_second) - _TOL
                or execution_state == NOT_STARTED
            )
        )
        if carried_in_progress:
            in_progress.append(trip.route_id)
        elif execution_state == COMPLETED:
            completed.append(trip.route_id)
        elif execution_state == IN_PROGRESS:
            in_progress.append(trip.route_id)
        else:
            editable.append(trip.route_id)

    actions_by_asset: dict[str, list[tuple[float, float, ChargingAction]]] = {}
    actions_by_route: dict[str, list[ChargingAction]] = {}
    newly_locked: list[ChargingAction] = []
    for action in solution.charging_actions:
        trip = trip_by_id[action.vehicle_id]
        actions_by_route.setdefault(action.vehicle_id, []).append(action)
        start = _absolute_charge_start(action)
        end = start + float(action.occupancy_minutes) * 60.0
        actions_by_asset.setdefault(trip.physical_vehicle_id, []).append((start, end, action))
        if start <= trigger:
            newly_locked.append(action)

    states: dict[str, DynamicAssetState] = {}
    frozen_arcs: dict[str, tuple[tuple[str, str], ...]] = {}
    unexecuted_arcs: dict[str, tuple[tuple[str, str], ...]] = {}
    for route_id, route in route_by_id.items():
        arcs = tuple(zip(route.node_sequence, route.node_sequence[1:]))
        if route_id in completed:
            frozen_arcs[route_id] = arcs
            unexecuted_arcs[route_id] = ()
        elif route_id in editable:
            frozen_arcs[route_id] = ()
            unexecuted_arcs[route_id] = arcs
    for asset_id, state in inherited.items():
        chain = [trip for trip in certificate.trips if trip.physical_vehicle_id == asset_id]
        tracked_route_id = state.continuation_route_id or state.in_progress_route_id
        tracked_not_started = (
            tracked_route_id in trip_by_id
            and _trip_state(trip_by_id[str(tracked_route_id)], trigger)
            == NOT_STARTED
        )
        if tracked_route_id is not None and (
            same_stage
            or trigger < float(state.available_second) - _TOL
            or tracked_not_started
        ):
            if same_stage:
                carried = state
            elif trigger < float(state.available_second) - _TOL:
                carried = _carry_unreleased_state(state, trigger)
            else:
                carried = replace(
                    state,
                    trigger_position_node_id=(
                        state.release_node_id or state.position_node_id
                    ),
                    trigger_time=float(trigger),
                    trigger_arc_progress=None,
                    trigger_remaining_load_kg=float(state.remaining_load_kg),
                    trigger_remaining_battery_kwh=float(
                        state.remaining_battery_kwh
                    ),
                )
            states[asset_id] = carried
            route_id = str(tracked_route_id)
            if route_id in route_by_id:
                frozen_arcs[route_id] = tuple(state.frozen_arcs)
                route = route_by_id[route_id]
                unexecuted_arcs[route_id] = tuple(
                    zip(route.node_sequence, route.node_sequence[1:])
                )
            continue
        started = [trip for trip in chain if _trip_state(trip, trigger) != NOT_STARTED]
        running = [trip for trip in chain if _trip_state(trip, trigger) == IN_PROGRESS]
        if running:
            trip = running[0]
            route = route_by_id[trip.route_id]
            inherits_physical_state = (
                tracked_route_id == trip.route_id
                and bool(route.node_sequence)
                and route.node_sequence[0] == state.virtual_origin_node_id
            )
            execution = _replay_trip(
                route,
                trip,
                instance,
                prices,
                actions_by_route.get(trip.route_id, []),
            )
            live_state, frozen, unexecuted = _in_progress_asset_state(
                route,
                trip,
                execution,
                instance,
                prices,
                actions_by_route.get(trip.route_id, ()),
                trigger,
                inherited_remaining_load_kg=(
                    state.remaining_load_kg
                    if inherits_physical_state
                    else None
                ),
                inherited_battery_kwh=(
                    state.remaining_battery_kwh
                    if inherits_physical_state
                    and state.vehicle_type == "ev"
                    else None
                ),
            )
            states[asset_id] = live_state
            frozen_arcs[trip.route_id] = frozen
            unexecuted_arcs[trip.route_id] = unexecuted
            continue
        available = max(trigger, float(state.available_second))

        if state.vehicle_type == "ev":
            battery = float(state.remaining_battery_kwh)
            battery -= sum(
                float(trip.start_battery_kwh or 0.0) - float(trip.end_battery_kwh or 0.0)
                for trip in started
            )
            for start, end, action in actions_by_asset.get(asset_id, []):
                if start <= trigger:
                    battery += float(action.energy_kwh)
                    if end > trigger:
                        available = max(available, end)
            if battery < -_TOL or battery > battery_cap + _TOL:
                raise ValueError(
                    f"{DYNAMIC_CONTRACT_ID}: {asset_id} continued battery {battery:.9f} is outside capacity"
                )
            battery = min(battery_cap, max(0.0, battery))
            trigger_battery = battery
            for start, end, action in actions_by_asset.get(asset_id, []):
                if start <= trigger < end:
                    trigger_battery = _battery_during_actions(
                        battery - float(action.energy_kwh),
                        (action,),
                        trigger,
                        instance,
                        prices,
                    )
                    break
        else:
            battery = 0.0
            trigger_battery = 0.0

        next_index = max(
            int(state.next_trip_index),
            max((int(trip.trip_index) + 1 for trip in started), default=int(state.next_trip_index)),
        )
        states[asset_id] = DynamicAssetState(
            physical_vehicle_id=asset_id,
            vehicle_type=state.vehicle_type,
            home_depot_id=state.home_depot_id,
            available_second=float(available),
            remaining_battery_kwh=float(battery),
            next_trip_index=next_index,
            position_node_id=state.home_depot_id,
            remaining_load_kg=0.0,
            trigger_position_node_id=state.home_depot_id,
            release_node_id=state.home_depot_id,
            trigger_time=trigger,
            trigger_remaining_load_kg=0.0,
            trigger_remaining_battery_kwh=float(trigger_battery),
        )

    locked = _deduplicated_actions(
        [*inherited_locked_charging_actions, *newly_locked]
    )
    return CertificateCut(
        trigger_second=trigger,
        completed_route_ids=tuple(sorted(completed)),
        in_progress_route_ids=tuple(sorted(in_progress)),
        editable_route_ids=tuple(sorted(editable)),
        locked_charging_actions=tuple(locked),
        asset_states=MappingProxyType(dict(states)),
        frozen_arc_prefix_by_route_id=MappingProxyType(dict(frozen_arcs)),
        unexecuted_arc_suffix_by_route_id=MappingProxyType(
            dict(unexecuted_arcs)
        ),
    )


def prepare_dynamic_multitrip_solution(
    solution: Solution,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    asset_states: Mapping[str, DynamicAssetState],
    stage_start_second: float,
    locked_charging_actions: Sequence[ChargingAction] = (),
    ordered_route_ids: Sequence[str] = (),
    minimum_departure_second_by_route: Mapping[str, float] | None = None,
) -> tuple[Solution, MultiTripCertificate]:
    """Schedule open routes on the exact inherited assets.

    The input is an *open-route fragment*: callers must remove locked trips and
    already-started charging actions first.  Route ids are replaced by the
    inherited physical id and the next legal trip number.  No new physical id
    can be created.
    """

    stage_start = float(stage_start_second)
    if not _finite(stage_start):
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: stage start is not finite")
    if solution.routes and not asset_states:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: open routes have no inherited assets")
    if len({route.vehicle_id for route in solution.routes}) != len(solution.routes):
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: open route ids are not unique")
    route_by_id = {route.vehicle_id: route for route in solution.routes}
    virtual_state_by_node = {
        state.virtual_origin_node_id: state
        for state in asset_states.values()
        if state.virtual_origin_node_id is not None
    }
    open_routes = [
        route
        for route in solution.routes
        if route.node_sequence and route.node_sequence[0] != route.home_depot_id
    ]
    if any(route.node_sequence[0] not in virtual_state_by_node for route in open_routes):
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: open route has no inherited virtual origin")
    if len({route.node_sequence[0] for route in open_routes}) != len(open_routes):
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: a virtual origin is used more than once")
    node_types = {
        node.node_id: node.node_type.lower() for node in instance.nodes
    }
    public_actions_by_route: dict[str, list[ChargingAction]] = {}
    for action in solution.charging_actions:
        route = route_by_id.get(action.vehicle_id)
        if route is None:
            raise ValueError(
                f"{DYNAMIC_CONTRACT_ID}: open public charge is detached from a route"
            )
        if (
            node_types.get(action.station_id) != "f"
            or action.station_id not in route.node_sequence
        ):
            raise ValueError(
                f"{DYNAMIC_CONTRACT_ID}: open charging actions must be public "
                "stations visited by their route"
            )
        if int(action.charge_day_offset) != 0:
            raise ValueError(
                f"{DYNAMIC_CONTRACT_ID}: dynamic public charging must use day 0"
            )
        public_actions_by_route.setdefault(action.vehicle_id, []).append(action)
    route_ids = tuple(route.vehicle_id for route in solution.routes)
    ordered_ids = tuple(str(route_id) for route_id in ordered_route_ids)
    if ordered_ids and (
        len(ordered_ids) != len(set(ordered_ids))
        or set(ordered_ids) != set(route_ids)
    ):
        raise ValueError(
            f"{DYNAMIC_CONTRACT_ID}: ordered route ids must match open routes"
        )
    predecessor = {
        route_id: ordered_ids[index - 1]
        for index, route_id in enumerate(ordered_ids)
        if index > 0
    }

    power = _price(prices, "depot_charge_power_kw")
    battery_cap = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    if power <= 0.0:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: depot charge power must be positive")
    try:
        charging_curve = curve_for_charging_node(
            prices,
            node_type="d",
            capacity_kwh=battery_cap,
            reference_power_kw=power,
        )
    except ChargingCurveError as exc:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {exc}") from exc

    normalized_states = _validate_asset_states(asset_states, battery_cap)
    working = {
        asset_id: _WorkingAsset(
            state=state,
            available_second=float(state.available_second),
            battery_kwh=float(state.remaining_battery_kwh),
            next_trip_index=int(state.next_trip_index),
        )
        for asset_id, state in normalized_states.items()
    }
    profiles = [
        _route_profile_cached(
            route,
            instance,
            prices,
            public_charging_actions=tuple(
                public_actions_by_route.get(route.vehicle_id, ())
            ),
            minimum_departure_second=(
                None
                if minimum_departure_second_by_route is None
                else minimum_departure_second_by_route.get(route.vehicle_id)
            ),
            allowed_open_start_node_ids=frozenset(virtual_state_by_node),
            inherited_load_kg=(
                virtual_state_by_node[route.node_sequence[0]].remaining_load_kg
                if route.node_sequence[0] in virtual_state_by_node
                else None
            ),
        )
        for route in solution.routes
    ]
    profiles.sort(
        key=lambda item: (
            item.latest_departure_second,
            item.preferred_departure_second,
            item.route.vehicle_id,
        )
    )

    explored = 0
    last_failure = "no complete exact-asset assignment"

    def assign(
        remaining: list[_RouteProfile],
        current_assets: dict[str, _WorkingAsset],
        current_assignments: list[_Assignment],
    ) -> tuple[Solution, MultiTripCertificate] | None:
        nonlocal explored, last_failure
        explored += 1
        if explored > _MAX_ASSIGNMENT_STATES:
            last_failure = f"assignment backtracking exceeded {_MAX_ASSIGNMENT_STATES} states"
            return None
        if not remaining:
            try:
                prepared, certificate = _close_dynamic_battery_ledger(
                    current_assignments,
                    solution,
                    normalized_states,
                    instance,
                    prices,
                    stage_start,
                )
                validate_dynamic_multitrip_certificate(
                    prepared,
                    certificate,
                    instance,
                    prices,
                    asset_states=normalized_states,
                    stage_start_second=stage_start,
                    locked_charging_actions=locked_charging_actions,
                )
                return prepared, certificate
            except ValueError as exc:
                last_failure = str(exc)
                return None

        ranked: list[
            tuple[
                int,
                float,
                float,
                str,
                int,
                list[
                    tuple[
                        float,
                        float,
                        str,
                        float | None,
                        float | None,
                        tuple[ChargingAction, ...],
                    ]
                ],
            ]
        ] = []
        remaining_ids = {profile.route.vehicle_id for profile in remaining}
        eligible_indices = [
            index
            for index, profile in enumerate(remaining)
            if predecessor.get(profile.route.vehicle_id) not in remaining_ids
        ]
        for index in eligible_indices:
            profile = remaining[index]
            candidates = _dynamic_assignment_candidates(
                profile,
                current_assets,
                instance,
                prices,
                stage_start,
                charging_curve,
            )
            if not candidates:
                last_failure = (
                    f"no inherited asset can serve open route {profile.route.vehicle_id}"
                )
                return None
            ranked.append(
                (
                    len(candidates),
                    profile.latest_departure_second,
                    profile.preferred_departure_second,
                    profile.route.vehicle_id,
                    index,
                    candidates,
                )
            )

        # Reserve scarce vehicles for the routes that have the fewest legal
        # choices.  The earlier greedy version could spend the only suitable
        # EV on a flexible route and falsely declare a later route infeasible.
        _, _, _, _, selected_index, candidates = min(ranked)
        profile = remaining[selected_index]
        next_remaining = [
            item for index, item in enumerate(remaining) if index != selected_index
        ]
        seen_equivalent_assets: set[tuple[object, ...]] = set()
        for (
            returned,
            departure,
            asset_id,
            departure_battery,
            return_battery,
            public_actions,
        ) in candidates:
            asset = current_assets[asset_id]
            equivalence = (
                asset.state.vehicle_type,
                asset.state.home_depot_id,
                round(float(asset.available_second), 6),
                round(float(asset.battery_kwh), 6),
                int(asset.next_trip_index),
            )
            if equivalence in seen_equivalent_assets:
                continue
            seen_equivalent_assets.add(equivalence)
            next_assets = {
                key: _WorkingAsset(
                    state=value.state,
                    available_second=float(value.available_second),
                    battery_kwh=float(value.battery_kwh),
                    next_trip_index=int(value.next_trip_index),
                )
                for key, value in current_assets.items()
            }
            selected_asset = next_assets[asset_id]
            assignment = _Assignment(
                route=profile.route,
                physical_vehicle_id=asset_id,
                trip_index=selected_asset.next_trip_index,
                departure_second=float(departure),
                return_second=float(returned),
                drive_energy_kwh=float(profile.drive_energy_kwh),
                departure_battery_kwh=departure_battery,
                return_battery_kwh=return_battery,
                public_charging_actions=public_actions,
            )
            selected_asset.available_second = float(returned)
            selected_asset.next_trip_index += 1
            if profile.route.vehicle_type.lower() == "ev":
                selected_asset.battery_kwh = float(return_battery or 0.0)
            result = assign(
                next_remaining,
                next_assets,
                [*current_assignments, assignment],
            )
            if result is not None:
                return result
        return None

    result = assign(profiles, working, [])
    if result is None:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {last_failure}")
    return result


def reschedule_dynamic_charging(
    solution: Solution,
    certificate: MultiTripCertificate,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    asset_states: Mapping[str, DynamicAssetState],
    stage_start_second: float,
    locked_charging_actions: Sequence[ChargingAction] = (),
    strategy: str,
    intensity_field: str = "forecast_gco2_per_kwh",
) -> tuple[Solution, MultiTripCertificate, dict[str, float | int]]:
    """Move not-yet-started dynamic depot charging inside its legal gaps.

    The static timing helper cannot be used after a rolling-horizon cut because
    its first open trip is not necessarily the first trip of the operating day.
    Here the first legal charging instant is the later of the stage trigger and
    the inherited physical vehicle release.  Route, vehicle, customer, energy,
    and departure decisions remain fixed; only charging start times move.

    The returned certificate is updated together with the solution so that the
    next dynamic cut reads the same charging clock that was actually released.
    """

    if strategy not in {"aware", "naive"}:
        raise ValueError(f"unknown dynamic charging strategy {strategy!r}")
    stage_start = float(stage_start_second)
    validate_dynamic_multitrip_certificate(
        solution,
        certificate,
        instance,
        prices,
        asset_states=asset_states,
        stage_start_second=stage_start,
        locked_charging_actions=locked_charging_actions,
    )

    normalized_states = _validate_asset_states(
        asset_states,
        instance.battery_capacity_kwh(
            fallback=_price(prices, "B_battery_kwh"),
        ),
    )
    home_by_route = {
        trip.route_id: trip.home_depot_id for trip in certificate.trips
    }
    actions_by_route: dict[str, list[ChargingAction]] = {}
    for action in solution.charging_actions:
        if action.station_id == home_by_route.get(action.vehicle_id):
            actions_by_route.setdefault(action.vehicle_id, []).append(action)

    replacement_actions: dict[str, ChargingAction] = {}
    replacement_trips: dict[str, ScheduledTrip] = {}
    moved_action_count = 0
    moved_energy_kwh = 0.0
    eligible_action_count = 0
    eligible_energy_kwh = 0.0
    actions_at_earliest_count = 0
    maximum_shift_seconds = 0.0

    by_asset: dict[str, list[ScheduledTrip]] = {}
    for trip in certificate.trips:
        by_asset.setdefault(trip.physical_vehicle_id, []).append(trip)
    for asset_id, chain in sorted(by_asset.items()):
        state = normalized_states[asset_id]
        ordered = sorted(chain, key=lambda item: item.trip_index)
        boundary = max(stage_start, float(state.available_second))
        for position, trip in enumerate(ordered):
            actions = actions_by_route.get(trip.route_id, [])
            if actions:
                action = actions[0]
                if int(action.charge_day_offset) != 0:
                    raise ValueError(
                        f"{DYNAMIC_CONTRACT_ID}: dynamic charge uses a day offset"
                    )
                duration = float(action.occupancy_minutes) * 60.0
                earliest = boundary
                latest = float(trip.departure_second) - duration
                if latest < earliest - _TOL:
                    raise ValueError(
                        f"{DYNAMIC_CONTRACT_ID}: no legal dynamic charging gap for {trip.route_id}"
                    )
                selected = (
                    earliest
                    if strategy == "naive"
                    else best_charging_action_start(
                        action,
                        earliest_start_second=earliest,
                        latest_start_second=latest,
                        instance=instance,
                        carbon_profile=carbon_profile,
                        prices=prices,
                        intensity_field=intensity_field,
                    )
                )
                replacement_actions[trip.route_id] = replace(
                    action,
                    charge_start_second=float(selected),
                )
                eligible_action_count += 1
                eligible_energy_kwh += float(action.energy_kwh)
                if abs(float(selected) - float(earliest)) <= _TOL:
                    actions_at_earliest_count += 1
                shift = abs(float(selected) - float(action.charge_start_second))
                if shift > _TOL:
                    moved_action_count += 1
                    moved_energy_kwh += float(action.energy_kwh)
                    maximum_shift_seconds = max(maximum_shift_seconds, shift)
                if position > 0:
                    previous = replacement_trips.get(
                        ordered[position - 1].route_id,
                        ordered[position - 1],
                    )
                    replacement_trips[previous.route_id] = replace(
                        previous,
                        charge_start_second=float(selected),
                        recharge_end_second=float(selected) + duration,
                    )
            boundary = float(trip.return_second)

    timed_solution = replace(
        solution,
        charging_actions=[
            (
                replacement_actions.get(action.vehicle_id, action)
                if action.station_id == home_by_route.get(action.vehicle_id)
                else action
            )
            for action in solution.charging_actions
        ],
    )
    timed_certificate = replace(
        certificate,
        trips=tuple(
            replacement_trips.get(trip.route_id, trip)
            for trip in certificate.trips
        ),
    )
    validate_dynamic_multitrip_certificate(
        timed_solution,
        timed_certificate,
        instance,
        prices,
        asset_states=asset_states,
        stage_start_second=stage_start,
        locked_charging_actions=locked_charging_actions,
    )
    return (
        timed_solution,
        timed_certificate,
        {
            "eligible_action_count": eligible_action_count,
            "eligible_energy_kwh": eligible_energy_kwh,
            "actions_at_earliest_count": actions_at_earliest_count,
            "moved_action_count": moved_action_count,
            "moved_energy_kwh": moved_energy_kwh,
            "maximum_shift_seconds": maximum_shift_seconds,
        },
    )


def _dynamic_assignment_candidates(
    profile: _RouteProfile,
    working: Mapping[str, _WorkingAsset],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    stage_start: float,
    charging_curve: PiecewiseChargingCurve,
) -> list[
    tuple[
        float,
        float,
        str,
        float | None,
        float | None,
        tuple[ChargingAction, ...],
    ]
]:
    route = profile.route
    candidates: list[
        tuple[
            float,
            float,
            str,
            float | None,
            float | None,
            tuple[ChargingAction, ...],
        ]
    ] = []
    for asset_id, asset in working.items():
        state = asset.state
        open_start = route.node_sequence[0] != route.home_depot_id
        if (
            state.vehicle_type != route.vehicle_type.lower()
            or state.home_depot_id != route.home_depot_id
            or (
                open_start
                and state.virtual_origin_node_id != route.node_sequence[0]
            )
        ):
            continue
        boundary = max(stage_start, asset.available_second)
        if route.vehicle_type.lower() == "ev":
            required_departure = (
                float(profile.required_departure_battery_kwh)
                if profile.required_departure_battery_kwh is not None
                else float(profile.drive_energy_kwh)
            )
            available_seconds = max(
                0.0,
                profile.latest_departure_second - boundary,
            )
            possible_battery = (
                asset.battery_kwh
                if open_start
                else charging_curve.reachable_energy_kwh(
                    asset.battery_kwh,
                    available_seconds,
                )
            )
            if possible_battery + _TOL < required_departure:
                continue
            needed = max(0.0, required_departure - asset.battery_kwh)
            energy_ready = boundary + (
                charging_curve.duration_seconds(
                    asset.battery_kwh,
                    asset.battery_kwh + needed,
                )
                if needed > _TOL and not open_start
                else 0.0
            )
            departure = max(profile.preferred_departure_second, energy_ready)
            departure_battery = asset.battery_kwh + needed
            return_battery = (
                departure_battery
                + float(profile.public_charge_energy_kwh)
                - float(profile.drive_energy_kwh)
            )
            if return_battery < -_TOL:
                continue
        else:
            departure = max(profile.preferred_departure_second, boundary)
            departure_battery = None
            return_battery = None
        if departure > profile.latest_departure_second + _TOL:
            continue
        try:
            if profile.public_charging_actions:
                timing = route_timing(
                    route,
                    instance,
                    prices,
                    charging_actions=list(profile.public_charging_actions),
                    forced_departure_second=float(departure),
                )
                returned = float(timing.return_second)
                if (
                    timing.required_departure_battery_kwh is None
                    or abs(
                        float(timing.required_departure_battery_kwh)
                        - float(departure_battery or 0.0)
                    )
                    > _TOL
                ):
                    continue
            else:
                returned = _return_at_departure(
                    route, instance, prices, departure
                )
        except ValueError:
            continue
        candidates.append(
            (
                float(returned),
                float(departure),
                asset_id,
                (
                    None
                    if departure_battery is None
                    else float(departure_battery)
                ),
                None if return_battery is None else float(return_battery),
                profile.public_charging_actions,
            )
        )
    return sorted(candidates, key=lambda item: (item[0], item[1], item[2]))


def validate_dynamic_multitrip_certificate(
    solution: Solution,
    certificate: MultiTripCertificate,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    asset_states: Mapping[str, DynamicAssetState],
    stage_start_second: float,
    locked_charging_actions: Sequence[ChargingAction] = (),
) -> None:
    """Validate the dynamic continuation contract against inherited assets."""

    stage_start = float(stage_start_second)
    battery_cap = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    power = _price(prices, "depot_charge_power_kw")
    try:
        charging_curve = curve_for_charging_node(
            prices,
            node_type="d",
            capacity_kwh=battery_cap,
            reference_power_kw=power,
        )
    except ChargingCurveError as exc:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {exc}") from exc
    states = _validate_asset_states(asset_states, battery_cap)
    if certificate.contract_id != DYNAMIC_CONTRACT_ID or certificate.status != "PASS":
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: unknown or failed certificate")
    if certificate.recharge_mode != CHARGE_MODE_ON_DEMAND:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: unsupported recharge mode")
    if certificate.first_trip_charge_day_offset != 0:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: dynamic charging cannot use a pre-horizon day")
    if abs(float(certificate.depot_charge_power_kw) - power) > _TOL:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: depot charge power disagrees with prices")
    if certificate.charging_curve_id != charging_curve.curve_id:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: certificate curve id disagrees with prices")
    physical_identity_required = (
        instance.vehicle_parameters is not None
        or charging_curve.curve_id != L100_CONTROL.curve_id
        or certificate.battery_capacity_kwh is not None
    )
    if physical_identity_required:
        if (
            certificate.battery_capacity_kwh is None
            or abs(
                float(certificate.battery_capacity_kwh)
                - charging_curve.capacity_kwh
            )
            > _TOL
        ):
            raise ValueError(
                f"{DYNAMIC_CONTRACT_ID}: certificate battery capacity "
                "disagrees"
            )
    route_by_id = {route.vehicle_id: route for route in solution.routes}
    trip_by_id = {trip.route_id: trip for trip in certificate.trips}
    if len(route_by_id) != len(solution.routes) or len(trip_by_id) != len(certificate.trips):
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: duplicate route or trip id")
    if set(route_by_id) != set(trip_by_id):
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: certificate does not cover every open route")

    actions_by_route: dict[str, list[ChargingAction]] = {}
    for action in solution.charging_actions:
        if action.vehicle_id not in route_by_id:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: detached charge for {action.vehicle_id}")
        if int(action.charge_day_offset) != 0:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: dynamic charge uses a day offset")
        actions_by_route.setdefault(action.vehicle_id, []).append(action)
    for action in locked_charging_actions:
        if physical_vehicle_id(action.vehicle_id) not in states:
            raise ValueError(
                f"{DYNAMIC_CONTRACT_ID}: locked charge belongs to an unknown asset {action.vehicle_id}"
            )

    by_asset: dict[str, list[ScheduledTrip]] = {}
    for trip in certificate.trips:
        if trip.physical_vehicle_id not in states:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: invented asset {trip.physical_vehicle_id}")
        by_asset.setdefault(trip.physical_vehicle_id, []).append(trip)

    used_counts = {"cv": 0, "ev": 0}
    for asset_id, chain in by_asset.items():
        state = states[asset_id]
        used_counts[state.vehicle_type] += 1
        ordered = sorted(chain, key=lambda item: item.trip_index)
        expected_indices = list(range(state.next_trip_index, state.next_trip_index + len(ordered)))
        if [trip.trip_index for trip in ordered] != expected_indices:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {asset_id} has a broken continuation index")
        boundary = max(stage_start, float(state.available_second))
        battery = float(state.remaining_battery_kwh)
        for position, trip in enumerate(ordered):
            route = route_by_id[trip.route_id]
            if trip.route_id != route_trip_vehicle_id(asset_id, trip.trip_index):
                raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {trip.route_id} is not bound to {asset_id}")
            if (
                trip.vehicle_type != state.vehicle_type
                or route.vehicle_type.lower() != state.vehicle_type
                or trip.home_depot_id != state.home_depot_id
                or route.home_depot_id != state.home_depot_id
            ):
                raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {asset_id} changes type or home depot")
            if float(trip.departure_second) < boundary - _TOL:
                raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {trip.route_id} departs before asset release")
            actions = actions_by_route.get(trip.route_id, [])
            depot_actions = [
                action
                for action in actions
                if action.station_id == state.home_depot_id
            ]
            public_actions = [
                action
                for action in actions
                if action.station_id != state.home_depot_id
            ]
            if len(depot_actions) > 1:
                raise ValueError(
                    f"{DYNAMIC_CONTRACT_ID}: one trip has multiple depot charges"
                )
            is_open_start = route.node_sequence[0] != route.home_depot_id
            if is_open_start and actions:
                raise ValueError(
                    f"{DYNAMIC_CONTRACT_ID}: an open continuation cannot start a new charge"
                )
            returned = (
                _return_at_departure(
                    route,
                    instance,
                    prices,
                    float(trip.departure_second),
                )
                if is_open_start
                else route_timing(
                    route,
                    instance,
                    prices,
                    charging_actions=actions,
                    forced_departure_second=float(trip.departure_second),
                ).return_second
            )
            if abs(returned - float(trip.return_second)) > _TOL:
                raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {trip.route_id} return clock drifted")
            profile = _route_profile_cached(
                route,
                instance,
                prices,
                public_charging_actions=tuple(public_actions),
                allowed_open_start_node_ids=frozenset(
                    item.virtual_origin_node_id
                    for item in states.values()
                    if item.virtual_origin_node_id is not None
                ),
                inherited_load_kg=next(
                    (
                        item.remaining_load_kg
                        for item in states.values()
                        if item.virtual_origin_node_id
                        == route.node_sequence[0]
                    ),
                    None,
                ),
            )

            if state.vehicle_type == "cv":
                if actions or any(
                    value is not None
                    for value in (
                        trip.start_battery_kwh,
                        trip.end_battery_kwh,
                        trip.charge_start_second,
                        trip.charge_energy_kwh,
                    )
                ):
                    raise ValueError(f"{DYNAMIC_CONTRACT_ID}: CV trip has an EV ledger")
            else:
                charge_energy = 0.0
                charge_start = None
                charge_end = None
                if depot_actions:
                    action = depot_actions[0]
                    charge_energy = float(action.energy_kwh)
                    charge_start = float(action.charge_start_second)
                    charge_end = charge_start + float(action.occupancy_minutes) * 60.0
                    if charge_energy <= _TOL:
                        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: zero-energy charge is recorded")
                    curve_state = charging_curve_for_action(
                        action,
                        instance,
                        prices,
                    )
                    if curve_state is None:
                        if charging_curve.curve_id != L100_CONTROL.curve_id:
                            raise ValueError(
                                f"{DYNAMIC_CONTRACT_ID}: nonlinear charge "
                                "is missing curve metadata"
                            )
                        if (
                            abs(
                                float(action.occupancy_minutes) * 60.0
                                - charging_curve.duration_seconds(
                                    battery,
                                    battery + charge_energy,
                                )
                            )
                            > _TOL
                        ):
                            raise ValueError(
                                f"{DYNAMIC_CONTRACT_ID}: charge duration "
                                "disagrees with energy"
                            )
                    else:
                        _, action_start_energy, action_end_energy = curve_state
                        if abs(action_start_energy - battery) > _TOL:
                            raise ValueError(
                                f"{DYNAMIC_CONTRACT_ID}: charge start "
                                "battery does not close"
                            )
                        if (
                            abs(
                                action_end_energy
                                - (battery + charge_energy)
                            )
                            > _TOL
                        ):
                            raise ValueError(
                                f"{DYNAMIC_CONTRACT_ID}: charge end "
                                "battery does not close"
                            )
                    if charge_start < boundary - _TOL or charge_end > float(trip.departure_second) + _TOL:
                        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: charge falls outside the legal gap")
                start_battery = battery + charge_energy
                timing = (
                    None
                    if is_open_start
                    else route_timing(
                        route,
                        instance,
                        prices,
                        charging_actions=actions,
                        forced_departure_second=float(trip.departure_second),
                    )
                )
                if (
                    timing is not None
                    and timing.required_departure_battery_kwh is not None
                    and abs(
                        start_battery
                        - float(timing.required_departure_battery_kwh)
                    )
                    > _TOL
                ):
                    raise ValueError(
                        f"{DYNAMIC_CONTRACT_ID}: {trip.route_id} public-charge "
                        "departure battery drifted"
                    )
                end_battery = (
                    start_battery
                    + float(
                        0.0
                        if timing is None
                        else timing.public_charge_energy_kwh
                    )
                    - profile.drive_energy_kwh
                )
                if start_battery > battery_cap + _TOL or end_battery < -_TOL:
                    raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {asset_id} battery leaves its bounds")
                if abs(float(trip.start_battery_kwh or 0.0) - start_battery) > _TOL:
                    raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {trip.route_id} start battery does not close")
                if abs(float(trip.end_battery_kwh or 0.0) - end_battery) > _TOL:
                    raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {trip.route_id} end battery does not close")
                if (
                    abs(
                        float(trip.in_route_charge_energy_kwh)
                        - float(
                            0.0
                            if timing is None
                            else timing.public_charge_energy_kwh
                        )
                    )
                    > _TOL
                ):
                    raise ValueError(
                        f"{DYNAMIC_CONTRACT_ID}: {trip.route_id} public-charge "
                        "energy does not close"
                    )
                expected_fixed_departure = (
                    start_battery if public_actions else None
                )
                if expected_fixed_departure is None:
                    if trip.fixed_departure_battery_kwh is not None:
                        raise ValueError(
                            f"{DYNAMIC_CONTRACT_ID}: {trip.route_id} has a stale "
                            "fixed departure battery"
                        )
                elif (
                    trip.fixed_departure_battery_kwh is None
                    or abs(
                        float(trip.fixed_departure_battery_kwh)
                        - expected_fixed_departure
                    )
                    > _TOL
                ):
                    raise ValueError(
                        f"{DYNAMIC_CONTRACT_ID}: {trip.route_id} fixed public "
                        "departure battery does not close"
                    )
                battery = end_battery

                if position > 0:
                    previous = ordered[position - 1]
                    expected_energy = charge_energy if charge_energy > _TOL else None
                    if expected_energy is None:
                        if previous.charge_energy_kwh is not None or previous.charge_start_second is not None:
                            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: stale between-trip charge ledger")
                        if abs(float(previous.recharge_end_second) - float(previous.return_second)) > _TOL:
                            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: stale recharge end clock")
                    else:
                        if abs(float(previous.charge_energy_kwh or 0.0) - expected_energy) > _TOL:
                            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: between-trip energy does not close")
                        if abs(float(previous.charge_start_second or 0.0) - float(charge_start)) > _TOL:
                            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: between-trip start does not close")
                        if abs(float(previous.recharge_end_second) - float(charge_end)) > _TOL:
                            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: between-trip end does not close")
            boundary = float(trip.return_second)

        last = ordered[-1]
        if last.charge_energy_kwh is not None or last.charge_start_second is not None:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: last dynamic trip has an unused future charge")
        if abs(float(last.recharge_end_second) - float(last.return_second)) > _TOL:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: last recharge clock exceeds its trip")

    expected_counts = {key: int(value) for key, value in certificate.vehicle_counts.items()}
    if expected_counts != used_counts:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: vehicle counts do not match used inherited assets")
    if instance.num_cv is not None and used_counts["cv"] > int(instance.num_cv):
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: CV cap exceeded")
    if instance.num_ev is not None and used_counts["ev"] > int(instance.num_ev):
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: EV cap exceeded")
    _validate_depot_charger_capacity(
        instance,
        [*locked_charging_actions, *solution.charging_actions],
        prices,
    )


def _close_dynamic_battery_ledger(
    assignments: list[_Assignment],
    source_solution: Solution,
    asset_states: Mapping[str, DynamicAssetState],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    stage_start: float,
) -> tuple[Solution, MultiTripCertificate]:
    power = _price(prices, "depot_charge_power_kw")
    battery_cap = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    try:
        charging_curve = curve_for_charging_node(
            prices,
            node_type="d",
            capacity_kwh=battery_cap,
            reference_power_kw=power,
        )
    except ChargingCurveError as exc:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {exc}") from exc
    by_asset: dict[str, list[_Assignment]] = {}
    for assignment in assignments:
        by_asset.setdefault(assignment.physical_vehicle_id, []).append(assignment)

    routes: list[Route] = []
    actions: list[ChargingAction] = []
    trips: list[ScheduledTrip] = []
    for asset_id, chain in sorted(by_asset.items()):
        state = asset_states[asset_id]
        ordered = sorted(chain, key=lambda item: item.trip_index)
        if state.vehicle_type == "cv":
            for item in ordered:
                route_id = route_trip_vehicle_id(asset_id, item.trip_index)
                routes.append(replace(item.route, vehicle_id=route_id))
                trips.append(
                    ScheduledTrip(
                        route_id,
                        asset_id,
                        item.trip_index,
                        "cv",
                        state.home_depot_id,
                        item.departure_second,
                        item.return_second,
                        item.return_second,
                        None,
                        None,
                    )
                )
            continue

        battery = float(state.remaining_battery_kwh)
        boundary = max(stage_start, float(state.available_second))
        chain_trips: list[ScheduledTrip] = []
        for item in ordered:
            if (
                item.departure_battery_kwh is None
                or item.return_battery_kwh is None
            ):
                raise ValueError(
                    f"{DYNAMIC_CONTRACT_ID}: {asset_id} EV assignment has no "
                    "battery ledger"
                )
            target_battery = float(item.departure_battery_kwh)
            needed = max(0.0, target_battery - battery)
            if battery + needed > battery_cap + _TOL:
                raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {asset_id} cannot store the required energy")
            duration = (
                charging_curve.duration_seconds(battery, target_battery)
                if needed > _TOL
                else 0.0
            )
            charge_start = item.departure_second - duration
            if charge_start < boundary - _TOL:
                raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {asset_id} cannot charge before its next trip")
            route_id = route_trip_vehicle_id(asset_id, item.trip_index)
            if needed > _TOL:
                actions.append(
                    ChargingAction(
                        vehicle_id=route_id,
                        station_id=state.home_depot_id,
                        energy_kwh=needed,
                        occupancy_minutes=duration / 60.0,
                        charge_start_second=charge_start,
                        charge_day_offset=0,
                        start_energy_kwh=battery,
                        end_energy_kwh=target_battery,
                        charging_curve_id=charging_curve.curve_id,
                    )
                )
                if chain_trips:
                    previous = chain_trips[-1]
                    chain_trips[-1] = replace(
                        previous,
                        charge_start_second=charge_start,
                        charge_energy_kwh=needed,
                        recharge_end_second=item.departure_second,
                    )
            public_actions = tuple(
                replace(action, vehicle_id=route_id)
                for action in item.public_charging_actions
            )
            actions.extend(public_actions)
            start_battery = target_battery
            public_energy = sum(
                float(action.energy_kwh) for action in public_actions
            )
            end_battery = (
                start_battery + public_energy - item.drive_energy_kwh
            )
            if abs(end_battery - float(item.return_battery_kwh)) > _TOL:
                raise ValueError(
                    f"{DYNAMIC_CONTRACT_ID}: {asset_id} public charging ledger "
                    "changed after assignment"
                )
            chain_trips.append(
                ScheduledTrip(
                    route_id,
                    asset_id,
                    item.trip_index,
                    "ev",
                    state.home_depot_id,
                    item.departure_second,
                    item.return_second,
                    item.return_second,
                    start_battery,
                    end_battery,
                    in_route_charge_energy_kwh=public_energy,
                    fixed_departure_battery_kwh=(
                        start_battery if public_actions else None
                    ),
                )
            )
            routes.append(replace(item.route, vehicle_id=route_id))
            battery = end_battery
            boundary = item.return_second
        trips.extend(chain_trips)

    served_customers = {
        node_id
        for route in routes
        for node_id in route.node_sequence
        if node_id in instance.node_index
        and instance.nodes[instance.node_index[node_id]].node_type.lower() == "c"
    }
    prepared = Solution(
        routes=sorted(routes, key=lambda route: route.vehicle_id),
        charging_actions=sorted(
            actions,
            key=lambda action: (action.vehicle_id, float(action.charge_start_second)),
        ),
        cross_site_services=[
            item for item in source_solution.cross_site_services if item.customer_id in served_customers
        ],
    )
    counts = {
        "cv": sum(asset_states[asset_id].vehicle_type == "cv" for asset_id in by_asset),
        "ev": sum(asset_states[asset_id].vehicle_type == "ev" for asset_id in by_asset),
    }
    certificate = MultiTripCertificate(
        contract_id=DYNAMIC_CONTRACT_ID,
        status="PASS",
        vehicle_counts=counts,
        trips=tuple(sorted(trips, key=lambda trip: trip.route_id)),
        recharge_mode=CHARGE_MODE_ON_DEMAND,
        depot_charge_power_kw=power,
        first_trip_charge_day_offset=0,
        charging_curve_id=charging_curve.curve_id,
        battery_capacity_kwh=battery_cap,
    )
    return prepared, certificate


def _validate_asset_states(
    asset_states: Mapping[str, DynamicAssetState],
    battery_cap: float,
) -> dict[str, DynamicAssetState]:
    normalized: dict[str, DynamicAssetState] = {}
    for key, state in asset_states.items():
        if key != state.physical_vehicle_id:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: asset-state key does not match its physical id")
        vehicle_type = state.vehicle_type.lower()
        if vehicle_type not in {"cv", "ev"}:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: unknown vehicle type {state.vehicle_type!r}")
        if not _finite(state.available_second) or not _finite(state.remaining_battery_kwh):
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {key} has a non-finite state")
        try:
            next_index_number = float(state.next_trip_index)
            next_index = int(state.next_trip_index)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {key} has an invalid next trip index") from exc
        if not _finite(next_index_number) or next_index_number != float(next_index) or next_index < 1:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {key} has an invalid next trip index")
        battery = float(state.remaining_battery_kwh)
        if vehicle_type == "ev" and (battery < -_TOL or battery > battery_cap + _TOL):
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: {key} battery is outside capacity")
        if vehicle_type == "cv" and abs(battery) > _TOL:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: CV asset {key} carries a battery state")
        normalized[key] = replace(state, vehicle_type=vehicle_type)
    return normalized


def instance_with_inherited_virtual_origins(
    instance: Instance,
    asset_states: Mapping[str, DynamicAssetState],
) -> Instance:
    """Add immutable zero-offset copies of legal continuation nodes."""

    existing = instance.node_lookup
    additions = [
        state
        for state in asset_states.values()
        if state.virtual_origin_node_id is not None
        and state.virtual_origin_node_id not in existing
    ]
    if not additions:
        return instance
    max_due = max(float(node.due_time) for node in instance.nodes)
    source_id_by_new: dict[str, str] = {}
    extra_nodes: list[Node] = []
    for state in additions:
        source_id = str(state.release_node_id)
        if source_id not in existing:
            raise ValueError(
                f"{DYNAMIC_CONTRACT_ID}: virtual origin has unknown release node {source_id}"
            )
        virtual_id = str(state.virtual_origin_node_id)
        if virtual_id in source_id_by_new:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: duplicate virtual origin {virtual_id}")
        source = existing[source_id]
        source_id_by_new[virtual_id] = source_id
        extra_nodes.append(
            Node(
                virtual_id,
                "v",
                float(source.x),
                float(source.y),
                ready_time=0.0,
                due_time=max(max_due, float(state.available_second)),
                city=source.city,
            )
        )

    nodes = [*instance.nodes, *extra_nodes]
    base_ids = [node.node_id for node in instance.nodes]
    all_ids = [node.node_id for node in nodes]
    base_index = {node_id: index for index, node_id in enumerate(base_ids)}

    def source_index(node_id: str) -> int:
        return base_index[source_id_by_new.get(node_id, node_id)]

    distance = [
        [
            float(instance.distance_matrix[source_index(left)][source_index(right)])
            for right in all_ids
        ]
        for left in all_ids
    ]
    road_profiles = None
    if instance.road_profiles is not None:
        road_profiles = {
            profile: RoadProfileMatrices(
                distance_m=tuple(
                    tuple(matrices.distance_m[source_index(left)][source_index(right)] for right in all_ids)
                    for left in all_ids
                ),
                duration_s=tuple(
                    tuple(matrices.duration_s[source_index(left)][source_index(right)] for right in all_ids)
                    for left in all_ids
                ),
                sum_v2d_m3_s2=tuple(
                    tuple(matrices.sum_v2d_m3_s2[source_index(left)][source_index(right)] for right in all_ids)
                    for left in all_ids
                ),
            )
            for profile, matrices in instance.road_profiles.items()
        }
    return replace(
        instance,
        nodes=nodes,
        distance_matrix=distance,
        road_profiles=road_profiles,
    )


def _in_progress_asset_state(
    route: Route,
    trip: ScheduledTrip,
    execution: Any,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    actions: Sequence[ChargingAction],
    trigger: float,
    *,
    inherited_remaining_load_kg: float | None = None,
    inherited_battery_kwh: float | None = None,
) -> tuple[
    DynamicAssetState,
    tuple[tuple[str, str], ...],
    tuple[tuple[str, str], ...],
]:
    """Replay one active trip to its next legal dvrpsim release boundary."""

    node_lookup = instance.node_lookup
    sequence = tuple(route.node_sequence)
    arcs = tuple(zip(sequence, sequence[1:]))
    planned_loads = _arc_loads(list(sequence), node_lookup)
    remaining_load = (
        float(planned_loads[0])
        if inherited_remaining_load_kg is None and planned_loads
        else float(inherited_remaining_load_kg or 0.0)
    )
    loads: list[float] = []
    load_cursor = remaining_load
    for to_id in sequence[1:]:
        loads.append(load_cursor)
        target = node_lookup[to_id]
        if target.node_type == "c":
            load_cursor -= float(target.demand)
    if load_cursor < -_TOL:
        raise ValueError(
            f"{DYNAMIC_CONTRACT_ID}: inherited load cannot serve its active route"
        )
    battery = (
        float(
            trip.start_battery_kwh
            if inherited_battery_kwh is None
            else inherited_battery_kwh
        )
        if route.vehicle_type == "ev"
        else 0.0
    )
    if (
        route.vehicle_type == "ev"
        and inherited_battery_kwh is not None
        and abs(float(trip.start_battery_kwh or 0.0) - battery) > _TOL
    ):
        raise ValueError(
            f"{DYNAMIC_CONTRACT_ID}: inherited battery disagrees with continuation"
        )
    public_actions: dict[str, list[ChargingAction]] = {}
    for action in actions:
        node = node_lookup.get(action.station_id)
        if node is not None and node.node_type == "f":
            public_actions.setdefault(action.station_id, []).append(action)
    for station_actions in public_actions.values():
        station_actions.sort(key=lambda item: float(item.charge_start_second))

    for arc_index, target_event in enumerate(execution.nodes[1:]):
        source_event = execution.nodes[arc_index]
        from_id, to_id = arcs[arc_index]
        arc_energy = 0.0
        if route.vehicle_type == "ev":
            arc_energy = ev_instance_arc_energy_kwh(
                instance,
                from_id,
                to_id,
                loads[arc_index],
                prices,
            )
        if trigger < float(target_event.arrival_second) - _TOL:
            duration = float(target_event.arrival_second) - float(
                source_event.departure_second
            )
            progress = (
                1.0
                if duration <= _TOL
                else min(
                    1.0,
                    max(
                        0.0,
                        (trigger - float(source_event.departure_second))
                        / duration,
                    ),
                )
            )
            return _continued_state(
                route,
                trip,
                trigger,
                release_node_id=to_id,
                release_second=float(target_event.arrival_second),
                executed_prefix=sequence[: arc_index + 1],
                editable_suffix=sequence[arc_index + 1 : -1],
                locked_arc=(from_id, to_id),
                trigger_position=f"{from_id}->{to_id}@{progress:.9f}",
                progress=progress,
                trigger_load=remaining_load,
                release_load=remaining_load,
                trigger_battery=battery - arc_energy * progress,
                release_battery=battery - arc_energy,
                frozen_arcs=arcs[: arc_index + 1],
                unexecuted_arcs=arcs[arc_index + 1 :],
            )

        battery -= arc_energy
        frozen_count = arc_index + 1
        target = node_lookup[to_id]
        if trigger < float(target_event.service_start_second) - _TOL:
            return _continued_state(
                route,
                trip,
                trigger,
                release_node_id=to_id,
                release_second=trigger,
                executed_prefix=sequence[: arc_index + 1],
                editable_suffix=sequence[arc_index + 1 : -1],
                locked_arc=None,
                trigger_position=to_id,
                progress=None,
                trigger_load=remaining_load,
                release_load=remaining_load,
                trigger_battery=battery,
                release_battery=battery,
                frozen_arcs=arcs[:frozen_count],
                unexecuted_arcs=arcs[frozen_count:],
            )

        station_actions = public_actions.get(to_id, [])
        release_battery = battery + sum(
            float(action.energy_kwh) for action in station_actions
        )
        if trigger < float(target_event.departure_second) - _TOL:
            trigger_battery = _battery_during_actions(
                battery,
                station_actions,
                trigger,
                instance,
                prices,
            )
            release_load = remaining_load
            if target.node_type == "c":
                release_load -= float(target.demand)
            return _continued_state(
                route,
                trip,
                trigger,
                release_node_id=to_id,
                release_second=float(target_event.departure_second),
                executed_prefix=sequence[: arc_index + 2],
                editable_suffix=sequence[arc_index + 2 : -1],
                locked_arc=None,
                trigger_position=to_id,
                progress=None,
                trigger_load=release_load,
                release_load=release_load,
                trigger_battery=trigger_battery,
                release_battery=release_battery,
                frozen_arcs=arcs[:frozen_count],
                unexecuted_arcs=arcs[frozen_count:],
            )
        battery = release_battery
        if target.node_type == "c":
            remaining_load -= float(target.demand)

    raise ValueError(f"{DYNAMIC_CONTRACT_ID}: active route has no live boundary")


def _continued_state(
    route: Route,
    trip: ScheduledTrip,
    trigger: float,
    *,
    release_node_id: str,
    release_second: float,
    executed_prefix: tuple[str, ...],
    editable_suffix: tuple[str, ...],
    locked_arc: tuple[str, str] | None,
    trigger_position: str,
    progress: float | None,
    trigger_load: float,
    release_load: float,
    trigger_battery: float,
    release_battery: float,
    frozen_arcs: tuple[tuple[str, str], ...],
    unexecuted_arcs: tuple[tuple[str, str], ...],
) -> tuple[DynamicAssetState, tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    continuation = release_node_id != route.home_depot_id or bool(editable_suffix)
    virtual_id = (
        f"__VIRTUAL_ORIGIN__{trip.physical_vehicle_id}__T{trip.trip_index}"
        f"__S{int(round(trigger * 1_000_000.0))}"
        if continuation
        else None
    )
    state = DynamicAssetState(
        physical_vehicle_id=trip.physical_vehicle_id,
        vehicle_type=route.vehicle_type,
        home_depot_id=route.home_depot_id,
        available_second=float(release_second),
        remaining_battery_kwh=float(release_battery),
        next_trip_index=(int(trip.trip_index) if continuation else int(trip.trip_index) + 1),
        position_node_id=virtual_id or trigger_position,
        remaining_load_kg=float(release_load),
        continuation_route_id=(route.vehicle_id if continuation else None),
        in_progress_route_id=route.vehicle_id,
        continuation_trip_index=(int(trip.trip_index) if continuation else None),
        executed_prefix=tuple(executed_prefix),
        frozen_arcs=tuple(frozen_arcs),
        locked_arc=locked_arc,
        editable_suffix=tuple(editable_suffix),
        trigger_position_node_id=trigger_position,
        release_node_id=release_node_id,
        virtual_origin_node_id=virtual_id,
        trigger_time=float(trigger),
        trigger_arc_progress=progress,
        trigger_remaining_load_kg=float(trigger_load),
        trigger_remaining_battery_kwh=float(trigger_battery),
    )
    return state, tuple(frozen_arcs), tuple(unexecuted_arcs)


def _carry_unreleased_state(
    state: DynamicAssetState,
    trigger: float,
) -> DynamicAssetState:
    """Advance evidence inside an already locked boundary without releasing it."""

    previous_trigger = state.trigger_time
    if previous_trigger is None or trigger < float(previous_trigger) - _TOL:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: unreleased state has no valid trigger clock")
    release = float(state.available_second)
    if trigger >= release - _TOL:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: released state cannot be carried")
    progress = state.trigger_arc_progress
    trigger_battery = float(
        state.trigger_remaining_battery_kwh
        if state.trigger_remaining_battery_kwh is not None
        else state.remaining_battery_kwh
    )
    position = state.trigger_position_node_id
    if state.locked_arc is not None and progress is not None:
        remaining_fraction = 1.0 - float(progress)
        remaining_seconds = release - float(previous_trigger)
        if remaining_fraction <= _TOL or remaining_seconds <= _TOL:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: locked arc has no remaining extent")
        full_duration = remaining_seconds / remaining_fraction
        progress = min(
            1.0,
            float(progress) + (trigger - float(previous_trigger)) / full_duration,
        )
        elapsed_fraction = (trigger - float(previous_trigger)) / remaining_seconds
        trigger_battery += (
            float(state.remaining_battery_kwh) - trigger_battery
        ) * elapsed_fraction
        position = (
            f"{state.locked_arc[0]}->{state.locked_arc[1]}@{progress:.9f}"
        )
    return replace(
        state,
        trigger_position_node_id=position,
        trigger_time=float(trigger),
        trigger_arc_progress=progress,
        trigger_remaining_load_kg=float(state.remaining_load_kg),
        trigger_remaining_battery_kwh=float(trigger_battery),
    )


def _battery_during_actions(
    inherited: float,
    actions: Sequence[ChargingAction],
    trigger: float,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
) -> float:
    battery = float(inherited)
    for action in actions:
        start = _absolute_charge_start(action)
        end = start + float(action.occupancy_minutes) * 60.0
        if trigger <= start:
            break
        if trigger >= end - _TOL:
            battery += float(action.energy_kwh)
            continue
        curve_state = charging_curve_for_action(action, instance, prices)
        if curve_state is None:
            fraction = (trigger - start) / max(_TOL, end - start)
            return battery + float(action.energy_kwh) * fraction
        curve, start_energy, _ = curve_state
        return curve.reachable_energy_kwh(start_energy, trigger - start)
    return battery


_ROUTE_PROFILE_CACHE_REFS: tuple[object, object] | None = None
_ROUTE_PROFILE_CACHE: dict[tuple, tuple[bool, object]] = {}


def _route_profile_cached(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    *,
    public_charging_actions: tuple[ChargingAction, ...] = (),
    minimum_departure_second: float | None = None,
    allowed_open_start_node_ids: frozenset[str] = frozenset(),
    inherited_load_kg: float | None = None,
) -> _RouteProfile:
    """Memoize `_route_profile`; identical inputs return the frozen profile.

    The strong references pin the active instance/prices objects so their
    ids cannot be reused by other objects while the cache is keyed on them;
    swapping either object clears the cache.
    """

    global _ROUTE_PROFILE_CACHE_REFS
    if _ROUTE_PROFILE_CACHE_REFS is None or (
        _ROUTE_PROFILE_CACHE_REFS[0] is not instance
        or _ROUTE_PROFILE_CACHE_REFS[1] is not prices
    ):
        _ROUTE_PROFILE_CACHE.clear()
        _ROUTE_PROFILE_CACHE_REFS = (instance, prices)
    key = (
        route.vehicle_id,
        route.vehicle_type,
        route.home_depot_id,
        tuple(route.node_sequence),
        public_charging_actions,
        minimum_departure_second,
        allowed_open_start_node_ids,
        inherited_load_kg,
    )
    hit = _ROUTE_PROFILE_CACHE.get(key)
    if hit is not None:
        ok, value = hit
        if ok:
            return value  # type: ignore[return-value]
        raise ValueError(value)
    if len(_ROUTE_PROFILE_CACHE) >= 65536:
        _ROUTE_PROFILE_CACHE.clear()
    try:
        profile = _route_profile(
            route,
            instance,
            prices,
            public_charging_actions=public_charging_actions,
            minimum_departure_second=minimum_departure_second,
            allowed_open_start_node_ids=allowed_open_start_node_ids,
            inherited_load_kg=inherited_load_kg,
        )
    except ValueError as exc:
        _ROUTE_PROFILE_CACHE[key] = (False, str(exc))
        raise
    _ROUTE_PROFILE_CACHE[key] = (True, profile)
    return profile


def _route_profile(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    *,
    public_charging_actions: tuple[ChargingAction, ...] = (),
    minimum_departure_second: float | None = None,
    allowed_open_start_node_ids: frozenset[str] = frozenset(),
    inherited_load_kg: float | None = None,
) -> _RouteProfile:
    if route.vehicle_type.lower() not in {"cv", "ev"}:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: route {route.vehicle_id} has an unknown vehicle type")
    if len(route.node_sequence) < 2:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: route {route.vehicle_id} has no trip")
    if (
        route.node_sequence[-1] != route.home_depot_id
        or (
            route.node_sequence[0] != route.home_depot_id
            and route.node_sequence[0] not in allowed_open_start_node_ids
        )
    ):
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: route {route.vehicle_id} is not depot closed")
    nodes = instance.node_lookup
    unknown = [node_id for node_id in route.node_sequence if node_id not in nodes]
    if unknown:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: route {route.vehicle_id} has unknown nodes {unknown}")
    public_station_ids = {
        node_id
        for node_id in route.node_sequence
        if nodes[node_id].node_type.lower() == "f"
    }
    action_station_ids = {
        action.station_id for action in public_charging_actions
    }
    if public_station_ids != action_station_ids:
        raise ValueError(
            f"{DYNAMIC_CONTRACT_ID}: every dynamic public-station visit must "
            "have a charging action and vice versa"
        )
    planned_demand = sum(
        float(nodes[node_id].demand)
        for node_id in route.node_sequence
        if nodes[node_id].node_type.lower() == "c"
    )
    capacity = instance.payload_capacity_kg(
        route.vehicle_type,
        fallback=_price(prices, "Q_capacity"),
    )
    load = planned_demand if inherited_load_kg is None else float(inherited_load_kg)
    if load > capacity + _TOL:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: route {route.vehicle_id} exceeds capacity")
    if planned_demand > load + _TOL:
        raise ValueError(
            f"{DYNAMIC_CONTRACT_ID}: route {route.vehicle_id} exceeds inherited load"
        )
    speed = _price(prices, "v_speed_ms")
    if speed <= 0.0:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: vehicle speed must be positive")

    origin = nodes[route.node_sequence[0]]
    elapsed = float(origin.service_time)
    departure_floor = float(origin.ready_time) + float(origin.service_time)
    if minimum_departure_second is not None:
        requested_floor = float(minimum_departure_second)
        if not _finite(requested_floor):
            raise ValueError(
                f"{DYNAMIC_CONTRACT_ID}: route {route.vehicle_id} has a "
                "non-finite minimum departure"
            )
        departure_floor = max(departure_floor, requested_floor)
    departure_candidates = [departure_floor]
    for from_id, to_id in zip(route.node_sequence, route.node_sequence[1:]):
        _, travel, _ = instance.arc_metrics(
            from_id,
            to_id,
            route.vehicle_type,
            fallback_speed_mps=speed,
        )
        elapsed += travel
        departure_candidates.append(float(nodes[to_id].ready_time) - elapsed)
        elapsed += float(nodes[to_id].service_time)
    preferred = max(departure_candidates)

    latest_start = float(nodes[route.node_sequence[-1]].due_time)
    for index in range(len(route.node_sequence) - 2, -1, -1):
        node = nodes[route.node_sequence[index]]
        next_id = route.node_sequence[index + 1]
        _, travel, _ = instance.arc_metrics(
            route.node_sequence[index],
            next_id,
            route.vehicle_type,
            fallback_speed_mps=speed,
        )
        latest_start = min(float(node.due_time), latest_start - float(node.service_time) - travel)
    latest = latest_start + float(origin.service_time)
    if latest < departure_floor - _TOL:
        raise ValueError(f"{DYNAMIC_CONTRACT_ID}: route {route.vehicle_id} has no feasible clock")
    preferred = min(preferred, latest)

    loads: list[float] = []
    load_cursor = load
    for to_id in route.node_sequence[1:]:
        loads.append(load_cursor)
        if nodes[to_id].node_type.lower() == "c":
            load_cursor -= float(nodes[to_id].demand)
    energy = 0.0
    if route.vehicle_type.lower() == "ev":
        energy = sum(
            ev_instance_arc_energy_kwh(
                instance,
                from_id,
                to_id,
                loads[index],
                prices,
            )
            for index, (from_id, to_id) in enumerate(
                zip(route.node_sequence, route.node_sequence[1:])
            )
        )
        battery_cap = instance.battery_capacity_kwh(
            fallback=_price(prices, "B_battery_kwh"),
        )
        if not public_charging_actions and energy > battery_cap + _TOL:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: route {route.vehicle_id} exceeds one battery")
    public_energy = 0.0
    required_departure = None
    if public_charging_actions:
        timing = route_timing(
            route,
            instance,
            prices,
            charging_actions=list(public_charging_actions),
            minimum_departure_second=minimum_departure_second,
        )
        energy = float(timing.drive_energy_kwh)
        public_energy = float(timing.public_charge_energy_kwh)
        required_departure = timing.required_departure_battery_kwh
        preferred = max(float(preferred), float(timing.earliest_departure_second))
        route_timing(
            route,
            instance,
            prices,
            charging_actions=list(public_charging_actions),
            forced_departure_second=float(preferred),
        )
    else:
        _return_at_departure(route, instance, prices, preferred)
    return _RouteProfile(
        route,
        float(preferred),
        float(latest),
        float(energy),
        float(public_energy),
        (
            None
            if required_departure is None
            else float(required_departure)
        ),
        tuple(public_charging_actions),
    )


def _return_at_departure(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    departure_second: float,
) -> float:
    nodes = instance.node_lookup
    speed = _price(prices, "v_speed_ms")
    clock = float(departure_second)
    for from_id, to_id in zip(route.node_sequence, route.node_sequence[1:]):
        _, travel, _ = instance.arc_metrics(
            from_id,
            to_id,
            route.vehicle_type,
            fallback_speed_mps=speed,
        )
        arrival = clock + travel
        node = nodes[to_id]
        service_start = max(arrival, float(node.ready_time))
        if service_start > float(node.due_time) + _TOL:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: route {route.vehicle_id} misses {to_id}")
        clock = service_start + float(node.service_time)
    return float(clock)


def _absolute_charge_start(action: ChargingAction) -> float:
    return float(action.charge_start_second) + int(action.charge_day_offset) * _DAY_SECONDS


def _trip_state(trip: ScheduledTrip, second: float) -> str:
    if float(second) < float(trip.departure_second):
        return NOT_STARTED
    if float(second) < float(trip.return_second):
        return IN_PROGRESS
    return COMPLETED


def _deduplicated_actions(actions: Sequence[ChargingAction]) -> list[ChargingAction]:
    result: list[ChargingAction] = []
    seen: set[tuple[object, ...]] = set()
    for action in actions:
        key = (
            action.vehicle_id,
            action.station_id,
            float(action.energy_kwh),
            float(action.occupancy_minutes),
            float(action.charge_start_second),
            int(action.charge_day_offset),
            (
                None
                if action.start_energy_kwh is None
                else float(action.start_energy_kwh)
            ),
            (
                None
                if action.end_energy_kwh is None
                else float(action.end_energy_kwh)
            ),
            action.charging_curve_id,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(action)
    result.sort(
        key=lambda action: (
            int(action.charge_day_offset),
            float(action.charge_start_second),
            action.station_id,
            action.vehicle_id,
        )
    )
    return result


def _validate_depot_charger_capacity(
    instance: Instance,
    actions: Sequence[ChargingAction],
    prices: PriceParameters | dict[str, float] | Any,
) -> None:
    """Apply the same 48-slot charger-capacity contract as the paper checker."""

    nodes = instance.node_lookup
    customer_count = sum(node.node_type.lower() == "c" for node in instance.nodes)
    occupied: dict[tuple[str, int, int], set[str]] = {}
    for action in _deduplicated_actions(actions):
        if action.station_id not in nodes:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: charge uses unknown station {action.station_id}")
        station = nodes[action.station_id]
        if station.node_type.lower() not in {"d", "f"}:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: charge uses a non-station node")
        if not all(
            _finite(value)
            for value in (
                action.energy_kwh,
                action.occupancy_minutes,
                action.charge_start_second,
            )
        ):
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: charge has a non-finite field")
        if float(action.energy_kwh) < -_TOL or float(action.occupancy_minutes) < -_TOL:
            raise ValueError(f"{DYNAMIC_CONTRACT_ID}: charge has a negative field")
        if float(action.energy_kwh) <= _TOL:
            continue
        for slot in charging_action_slot_breakdown(
            action,
            instance,
            prices,
            n_slots=48,
            cyclic=True,
        ):
            key = (
                action.station_id,
                int(action.charge_day_offset),
                int(slot.slot_index),
            )
            occupied.setdefault(key, set()).add(physical_vehicle_id(action.vehicle_id))

    for (station_id, day_offset, slot_index), asset_ids in sorted(occupied.items()):
        station = nodes[station_id]
        raw_capacity = station.station_chargers
        if raw_capacity is not None:
            capacity = max(0, int(raw_capacity))
        elif station.node_type.lower() == "d":
            capacity = max(1, customer_count)
        else:
            capacity = 1
        if len(asset_ids) > capacity:
            raise ValueError(
                f"{DYNAMIC_CONTRACT_ID}: charger capacity exceeded at {station_id}, "
                f"day={day_offset}, slot={slot_index}; occupied={len(asset_ids)}, C_s={capacity}"
            )


def _finite(value: object) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and abs(number) != float("inf")
