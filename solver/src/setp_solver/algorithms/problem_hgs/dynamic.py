"""Exact dynamic-state adapter for future-only Duty candidates.

Completed and in-progress trips remain outside the search individual.  Each
future duty is scheduled against exactly one inherited physical asset, then all
assets are validated together before the full execution history is scored.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from setp_solver.china81 import China81Bundle
from setp_solver.instance_loader import Instance
from setp_solver.search.dynamic_multitrip_schedule import (
    CertificateCut,
    DynamicAssetState,
    prepare_dynamic_multitrip_solution,
    reschedule_dynamic_charging,
    validate_dynamic_multitrip_certificate,
)
from setp_solver.search.multitrip_schedule import MultiTripCertificate
from setp_solver.solution import ChargingAction, Route, Solution, physical_vehicle_id

from .model import DutyIndividual, DutyTrip, PhysicalVehicleDuty
from .model import DutyChargingSession


@dataclass(frozen=True)
class DutyDynamicState:
    """External execution state that no genetic candidate may rewrite."""

    source_solution: Solution
    cut: CertificateCut
    asset_states: Mapping[str, DynamicAssetState]
    future_customer_ids: frozenset[str]
    customer_appearance_second: Mapping[str, float]
    charging_strategy: str
    charging_intensity_field: str
    prior_committed_solution: Solution | None = None
    certified_dynamic_route_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "future_customer_ids",
            frozenset(self.future_customer_ids),
        )
        appearances = {
            str(customer_id): float(second)
            for customer_id, second in self.customer_appearance_second.items()
        }
        if any(
            not math.isfinite(second)
            for second in appearances.values()
        ):
            raise ValueError("customer appearance times must be finite")
        object.__setattr__(
            self,
            "customer_appearance_second",
            MappingProxyType(appearances),
        )
        prior = self.prior_committed_solution or Solution()
        object.__setattr__(self, "prior_committed_solution", prior)
        object.__setattr__(
            self,
            "certified_dynamic_route_ids",
            frozenset(str(route_id) for route_id in self.certified_dynamic_route_ids),
        )
        prior_route_ids = {route.vehicle_id for route in prior.routes}
        committed_route_ids = {
            *self.cut.completed_route_ids,
            *self.cut.in_progress_route_ids,
        }
        if not self.certified_dynamic_route_ids.issubset(
            prior_route_ids.union(committed_route_ids)
        ):
            raise ValueError(
                "certified dynamic history must be present in committed routes"
            )
        if self.charging_strategy not in {"aware", "naive"}:
            raise ValueError("dynamic charging strategy must be aware or naive")
        if not self.charging_intensity_field:
            raise ValueError("dynamic charging intensity field cannot be empty")
        source_route_ids = {route.vehicle_id for route in self.source_solution.routes}
        prior_route_ids = {route.vehicle_id for route in prior.routes}
        if source_route_ids.intersection(prior_route_ids):
            raise ValueError(
                "dynamic source routes overlap earlier committed history"
            )
        if any(
            action.vehicle_id not in prior_route_ids
            for action in prior.charging_actions
        ):
            raise ValueError(
                "earlier committed charging is detached from its route"
            )
        partition = {
            *self.cut.completed_route_ids,
            *self.cut.in_progress_route_ids,
            *self.cut.editable_route_ids,
        }
        if source_route_ids != partition:
            raise ValueError("dynamic cut does not partition the source routes")
        if not set(self.cut.asset_states).issubset(self.asset_states):
            raise ValueError("full dynamic asset registry omits a cut asset")
        for asset_id, cut_state in self.cut.asset_states.items():
            if self.asset_states[asset_id] != cut_state:
                raise ValueError("full asset registry changed a cut asset state")


@dataclass(frozen=True)
class PreparedDynamicCandidate:
    """Future certificate plus the full execution plan used for truth scoring."""

    future_solution: Solution
    future_certificate: MultiTripCertificate
    full_execution_solution: Solution


def future_individual_from_cut(
    state: DutyDynamicState,
    source_certificate: MultiTripCertificate,
    instance: Instance,
) -> DutyIndividual:
    """Build one future-only individual while registering every inherited asset."""

    route_by_id = {
        route.vehicle_id: route for route in state.source_solution.routes
    }
    trip_by_id = {
        trip.route_id: trip for trip in source_certificate.trips
    }
    if set(route_by_id) != set(trip_by_id):
        raise ValueError("source certificate does not cover every source route")

    editable_by_asset: dict[str, list[tuple[int, Route]]] = {}
    for route_id in state.cut.editable_route_ids:
        trip = trip_by_id[route_id]
        editable_by_asset.setdefault(trip.physical_vehicle_id, []).append(
            (int(trip.trip_index), route_by_id[route_id])
        )
    node_types = {
        node.node_id: node.node_type.lower() for node in instance.nodes
    }
    actions_by_route: dict[str, list[ChargingAction]] = {}
    for action in state.source_solution.charging_actions:
        if (
            action.vehicle_id in state.cut.editable_route_ids
            and node_types.get(action.station_id) == "f"
            and float(action.charge_start_second)
            > float(state.cut.trigger_second) + 1.0e-9
        ):
            actions_by_route.setdefault(action.vehicle_id, []).append(action)

    committed_route_ids = {
        *state.cut.completed_route_ids,
        *state.cut.in_progress_route_ids,
    }
    committed_assets = {
        trip_by_id[route_id].physical_vehicle_id
        for route_id in committed_route_ids
    }
    committed_assets.update(
        physical_vehicle_id(action.vehicle_id)
        for action in state.cut.locked_charging_actions
    )
    customer_ids = {
        node.node_id
        for node in instance.nodes
        if node.node_type.lower() == "c"
    }
    _validate_customer_visibility(state, customer_ids)

    duties: list[PhysicalVehicleDuty] = []
    represented: set[str] = set()
    for asset_id, asset in sorted(state.asset_states.items()):
        trips: list[DutyTrip] = []
        sessions: list[DutyChargingSession] = []
        for future_index, (_, route) in enumerate(
            sorted(editable_by_asset.get(asset_id, ())),
            start=1,
        ):
            visits = tuple(route.node_sequence[1:-1])
            customers = tuple(
                node_id for node_id in visits if node_id in customer_ids
            )
            represented.update(customers)
            trips.append(
                DutyTrip(
                    trip_index=future_index,
                    customer_ids=customers,
                    route_visits=visits,
                )
            )
            sessions.extend(
                DutyChargingSession(
                    trip_index=future_index,
                    station_id=action.station_id,
                    energy_kwh=float(action.energy_kwh),
                    occupancy_minutes=float(action.occupancy_minutes),
                    charge_start_second=float(action.charge_start_second),
                    charge_day_offset=int(action.charge_day_offset),
                    start_energy_kwh=action.start_energy_kwh,
                    end_energy_kwh=action.end_energy_kwh,
                    charging_curve_id=action.charging_curve_id,
                )
                for action in actions_by_route.get(route.vehicle_id, ())
            )
        duties.append(
            PhysicalVehicleDuty(
                physical_vehicle_id=asset_id,
                vehicle_type=asset.vehicle_type,
                home_depot_id=asset.home_depot_id,
                trips=tuple(trips),
                charging_sessions=tuple(sessions),
                has_dynamic_commitment=asset_id in committed_assets,
            )
        )

    if not represented.issubset(state.future_customer_ids):
        raise ValueError("editable source routes contain a non-future customer")
    return DutyIndividual(
        duties=tuple(duties),
        unserved_customers=tuple(
            sorted(state.future_customer_ids.difference(represented))
        ),
        source="dynamic-future-from-certified-cut",
    )


def _validate_customer_visibility(
    state: DutyDynamicState,
    active_customer_ids: set[str],
) -> None:
    appearances = dict(state.customer_appearance_second)
    if set(appearances) != active_customer_ids:
        raise ValueError(
            "customer appearance registry must cover every currently active "
            "customer exactly once"
        )
    hidden = sorted(
        customer_id
        for customer_id, second in appearances.items()
        if float(second) > float(state.cut.trigger_second) + 1.0e-9
    )
    if hidden:
        raise ValueError(
            "dynamic state exposes customers before their appearance time: "
            + ", ".join(hidden)
        )


def prepare_dynamic_candidate(
    individual: DutyIndividual,
    state: DutyDynamicState,
    bundle: China81Bundle,
    *,
    minimum_departure_second_by_customer_id: Mapping[str, float] | None = None,
    shift_id_by_customer_id: Mapping[str, str] | None = None,
) -> PreparedDynamicCandidate:
    """Schedule exact Duty assignments and merge them with immutable history."""

    duties = {
        duty.physical_vehicle_id: duty for duty in individual.duties
    }
    if set(duties) != set(state.asset_states):
        raise ValueError("dynamic candidate changed the physical asset registry")
    for asset_id, asset in state.asset_states.items():
        duty = duties[asset_id]
        if (
            duty.vehicle_type != asset.vehicle_type
            or duty.home_depot_id != asset.home_depot_id
        ):
            raise ValueError("dynamic candidate changed asset type or home depot")
        if any(session.locked for session in duty.charging_sessions):
            raise ValueError("future Duty cannot carry a second locked charge")

    partial_solutions: list[Solution] = []
    partial_certificates: list[MultiTripCertificate] = []
    for asset_id, duty in sorted(duties.items()):
        if not duty.trips:
            continue
        open_routes = [
            Route(
                vehicle_id=f"open-{asset_id}-{position}",
                vehicle_type=duty.vehicle_type,
                home_depot_id=duty.home_depot_id,
                node_sequence=[
                    duty.home_depot_id,
                    *trip.effective_route_visits,
                    duty.home_depot_id,
                ],
            )
            for position, trip in enumerate(duty.trips, start=1)
        ]
        open_route_id_by_trip = {
            trip.trip_index: open_routes[position].vehicle_id
            for position, trip in enumerate(duty.trips)
        }
        minimum_departure_second_by_route: dict[str, float] = {}
        if minimum_departure_second_by_customer_id is not None:
            for route in open_routes:
                customer_ids = tuple(
                    node_id
                    for node_id in route.node_sequence[1:-1]
                    if node_id in minimum_departure_second_by_customer_id
                )
                shifts = (
                    {
                        str(shift_id_by_customer_id[node_id])
                        for node_id in customer_ids
                    }
                    if shift_id_by_customer_id is not None
                    else set()
                )
                floors = {
                    float(minimum_departure_second_by_customer_id[node_id])
                    for node_id in customer_ids
                }
                one_shift = (
                    len(shifts) == 1
                    if shift_id_by_customer_id is not None
                    else len(floors) == 1
                )
                if one_shift:
                    if len(floors) != 1:
                        raise ValueError(
                            "one shift maps to inconsistent departure floors"
                        )
                    minimum_departure_second_by_route[route.vehicle_id] = next(
                        iter(floors)
                    )
        node_types = {
            node.node_id: node.node_type.lower()
            for node in bundle.instance.nodes
        }
        public_actions = [
            ChargingAction(
                vehicle_id=open_route_id_by_trip[session.trip_index],
                station_id=session.station_id,
                energy_kwh=float(session.energy_kwh),
                occupancy_minutes=float(session.occupancy_minutes),
                charge_start_second=float(session.charge_start_second),
                charge_day_offset=int(session.charge_day_offset),
                start_energy_kwh=session.start_energy_kwh,
                end_energy_kwh=session.end_energy_kwh,
                charging_curve_id=session.charging_curve_id,
            )
            for session in duty.charging_sessions
            if node_types.get(session.station_id) == "f"
        ]
        locked = tuple(
            action
            for action in state.cut.locked_charging_actions
            if physical_vehicle_id(action.vehicle_id) == asset_id
        )
        prepared, certificate = prepare_dynamic_multitrip_solution(
            Solution(routes=open_routes, charging_actions=public_actions),
            bundle.instance,
            bundle.prices,
            asset_states={asset_id: state.asset_states[asset_id]},
            stage_start_second=state.cut.trigger_second,
            locked_charging_actions=locked,
            ordered_route_ids=tuple(route.vehicle_id for route in open_routes),
            minimum_departure_second_by_route=(
                minimum_departure_second_by_route
            ),
        )
        _assert_exact_duty_schedule(duty, prepared)
        partial_solutions.append(prepared)
        partial_certificates.append(certificate)

    future, certificate = _combine_dynamic_parts(
        partial_solutions,
        partial_certificates,
        state,
        bundle,
    )
    future, certificate, _ = reschedule_dynamic_charging(
        future,
        certificate,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        asset_states=state.asset_states,
        stage_start_second=state.cut.trigger_second,
        locked_charging_actions=state.cut.locked_charging_actions,
        strategy=state.charging_strategy,
        intensity_field=state.charging_intensity_field,
    )
    full = _merge_execution_history(state, future)
    return PreparedDynamicCandidate(future, certificate, full)


def _combine_dynamic_parts(
    solutions: list[Solution],
    certificates: list[MultiTripCertificate],
    state: DutyDynamicState,
    bundle: China81Bundle,
) -> tuple[Solution, MultiTripCertificate]:
    if not certificates:
        return prepare_dynamic_multitrip_solution(
            Solution(),
            bundle.instance,
            bundle.prices,
            asset_states=state.asset_states,
            stage_start_second=state.cut.trigger_second,
            locked_charging_actions=state.cut.locked_charging_actions,
        )
    future = Solution(
        routes=sorted(
            [route for solution in solutions for route in solution.routes],
            key=lambda route: route.vehicle_id,
        ),
        charging_actions=sorted(
            [
                action
                for solution in solutions
                for action in solution.charging_actions
            ],
            key=lambda action: (
                action.vehicle_id,
                float(action.charge_start_second),
            ),
        ),
    )
    trips = tuple(
        sorted(
            [trip for item in certificates for trip in item.trips],
            key=lambda trip: trip.route_id,
        )
    )
    counts = {
        vehicle_type: len(
            {
                trip.physical_vehicle_id
                for trip in trips
                if trip.vehicle_type == vehicle_type
            }
        )
        for vehicle_type in ("cv", "ev")
    }
    certificate = replace(
        certificates[0],
        vehicle_counts=counts,
        trips=trips,
    )
    validate_dynamic_multitrip_certificate(
        future,
        certificate,
        bundle.instance,
        bundle.prices,
        asset_states=state.asset_states,
        stage_start_second=state.cut.trigger_second,
        locked_charging_actions=state.cut.locked_charging_actions,
    )
    return future, certificate


def _assert_exact_duty_schedule(
    duty: PhysicalVehicleDuty,
    prepared: Solution,
) -> None:
    if {
        physical_vehicle_id(route.vehicle_id) for route in prepared.routes
    } != {duty.physical_vehicle_id}:
        raise ValueError("dynamic scheduler changed the Duty asset assignment")
    ordered = sorted(
        prepared.routes,
        key=lambda route: int(route.vehicle_id.rsplit("#T", 1)[1]),
    )
    expected = [
        (
            duty.vehicle_type,
            duty.home_depot_id,
            (
                duty.home_depot_id,
                *trip.effective_route_visits,
                duty.home_depot_id,
            ),
        )
        for trip in duty.trips
    ]
    observed = [
        (
            route.vehicle_type,
            route.home_depot_id,
            tuple(route.node_sequence),
        )
        for route in ordered
    ]
    if observed != expected:
        raise ValueError("dynamic scheduler changed the Duty task chain")


def _merge_execution_history(
    state: DutyDynamicState,
    future: Solution,
) -> Solution:
    source_routes = {
        route.vehicle_id: route for route in state.source_solution.routes
    }
    prior = state.prior_committed_solution or Solution()
    routes = {route.vehicle_id: route for route in prior.routes}
    current_committed = {
        route_id: source_routes[route_id]
        for route_id in (
            *state.cut.completed_route_ids,
            *state.cut.in_progress_route_ids,
        )
    }
    for route_id, route in current_committed.items():
        previous = routes.get(route_id)
        if previous is not None and previous != route:
            raise ValueError("dynamic cut rewrote earlier committed history")
        routes[route_id] = route
    for route in future.routes:
        previous = routes.get(route.vehicle_id)
        if previous is not None and previous != route:
            raise ValueError("dynamic future rewrote an executed route")
        routes[route.vehicle_id] = route

    actions: dict[tuple[object, ...], ChargingAction] = {}
    for action in (
        *prior.charging_actions,
        *state.cut.locked_charging_actions,
        *future.charging_actions,
    ):
        key = _action_key(action)
        previous = actions.get(key)
        if previous is not None and previous != action:
            raise ValueError("dynamic charging action key collision")
        actions[key] = action

    for action in actions.values():
        if action.vehicle_id in routes:
            continue
        source = source_routes.get(action.vehicle_id)
        if source is None:
            raise ValueError("locked charge is detached from its source route")
        routes[action.vehicle_id] = replace(
            source,
            node_sequence=[source.home_depot_id, source.home_depot_id],
        )
    return Solution(
        routes=[routes[key] for key in sorted(routes)],
        charging_actions=[actions[key] for key in sorted(actions, key=str)],
    )


def _action_key(action: ChargingAction) -> tuple[object, ...]:
    return (
        action.vehicle_id,
        action.station_id,
        float(action.energy_kwh),
        float(action.occupancy_minutes),
        float(action.charge_start_second),
        int(action.charge_day_offset),
        action.start_energy_kwh,
        action.end_energy_kwh,
        action.charging_curve_id,
    )
