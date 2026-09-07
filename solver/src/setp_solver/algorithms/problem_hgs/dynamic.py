"""Exact dynamic-state adapter for future-only Duty candidates.

Completed and in-progress trips remain outside the search individual.  Each
future duty is scheduled against exactly one inherited physical asset, then all
assets are validated together before the full execution history is scored.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from setp_solver.check import DynamicCheckContext, DynamicVehicleState
from setp_solver.china81 import China81Bundle
from setp_solver.instance_loader import Instance
from setp_solver.search.dynamic_multitrip_schedule import (
    CertificateCut,
    DynamicAssetState,
    instance_with_inherited_virtual_origins,
    prepare_dynamic_multitrip_solution,
    reschedule_dynamic_charging,
    validate_dynamic_multitrip_certificate,
)
from setp_solver.search.multitrip_schedule import MultiTripCertificate
from setp_solver.solution import ChargingAction, Route, Solution, physical_vehicle_id

from .model import DutyIndividual, DutyTrip, PhysicalVehicleDuty
from .model import DutyChargingSession


@dataclass(frozen=True)
class DynamicPrefixAccountingCorrection:
    """Cumulative load-sensitive correction for one executed route prefix."""

    home_depot_id: str
    fuel_liters: float = 0.0
    fuel_cost: float = 0.0
    cv_emissions_kg: float = 0.0
    ev_drive_kwh: float = 0.0


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
    inherited_evaluation_instance: Instance | None = None
    source_full_execution_solution: Solution | None = None
    prior_committed_solution: Solution | None = None
    certified_dynamic_route_ids: frozenset[str] = frozenset()
    prior_prefix_accounting_by_route_id: Mapping[
        str, DynamicPrefixAccountingCorrection
    ] = field(default_factory=lambda: MappingProxyType({}))

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
        prefix_accounting = {
            str(route_id): correction
            for route_id, correction in self.prior_prefix_accounting_by_route_id.items()
        }
        if any(
            not correction.home_depot_id
            or any(
                not math.isfinite(float(value))
                for value in (
                    correction.fuel_liters,
                    correction.fuel_cost,
                    correction.cv_emissions_kg,
                    correction.ev_drive_kwh,
                )
            )
            for correction in prefix_accounting.values()
        ):
            raise ValueError("dynamic prefix accounting is incomplete or non-finite")
        object.__setattr__(
            self,
            "prior_prefix_accounting_by_route_id",
            MappingProxyType(prefix_accounting),
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
        full_source = self.source_full_execution_solution or self.source_solution
        object.__setattr__(self, "source_full_execution_solution", full_source)
        full_source_routes = {
            route.vehicle_id: route for route in full_source.routes
        }
        if not source_route_ids.issubset(full_source_routes):
            raise ValueError(
                "full execution source omits a currently planned route"
            )
        source_routes = {
            route.vehicle_id: route for route in self.source_solution.routes
        }
        if any(
            full_source_routes[route_id].vehicle_type
            != source_routes[route_id].vehicle_type
            or full_source_routes[route_id].home_depot_id
            != source_routes[route_id].home_depot_id
            for route_id in source_route_ids
        ):
            raise ValueError(
                "full execution source changed a current route identity"
            )
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
    evaluation_instance: Instance
    future_check_instance: Instance
    future_check_context: DynamicCheckContext
    frozen_prefixes: Mapping[str, tuple[str, ...]]


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
            (
                action.vehicle_id in state.cut.editable_route_ids
                or any(
                    getattr(asset, "continuation_route_id", None)
                    == action.vehicle_id
                    for asset in state.asset_states.values()
                )
            )
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
        continuation_route_id = getattr(
            asset,
            "continuation_route_id",
            None,
        )
        rows: list[tuple[int, tuple[str, ...], str]] = []
        editable_suffix = tuple(getattr(asset, "editable_suffix", ()))
        if continuation_route_id is not None:
            rows.append(
                (
                    int(getattr(asset, "continuation_trip_index", 0) or 0),
                    editable_suffix,
                    str(continuation_route_id),
                )
            )
        rows.extend(
            (
                int(trip_index),
                tuple(route.node_sequence[1:-1]),
                route.vehicle_id,
            )
            for trip_index, route in sorted(
                editable_by_asset.get(asset_id, ())
            )
        )
        for future_index, (_, visits, source_route_id) in enumerate(
            rows,
            start=1,
        ):
            customers = tuple(
                node_id for node_id in visits if node_id in customer_ids
            )
            # A customer cancelled after the previous stage vanishes from the
            # stage instance; a legal cancellation skips that stop, so the
            # visit sequence must drop nodes the stage no longer knows.
            visible_visits = tuple(
                node_id for node_id in visits if node_id in node_types
            )
            represented.update(customers)
            trips.append(
                DutyTrip(
                    trip_index=future_index,
                    customer_ids=customers,
                    route_visits=visible_visits,
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
                for action in actions_by_route.get(source_route_id, ())
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


_EVAL_INSTANCE_CACHE: dict[tuple[int, int, float], "Instance"] = {}


def _stage_evaluation_instance(bundle, state):
    """Build the virtual-origin evaluation instance once per stage.

    Both inputs are stage constants; rebuilding (and re-validating the full
    road matrices) per candidate was measured at hours per batch under the
    official stopping rule.
    """
    key = (id(bundle.instance), id(state), float(state.cut.trigger_second))
    hit = _EVAL_INSTANCE_CACHE.get(key)
    if hit is not None:
        return hit
    built = instance_with_inherited_virtual_origins(
        _carry_forward_virtual_origins(
            bundle.instance,
            state.inherited_evaluation_instance,
        ),
        state.asset_states,
    )
    if len(_EVAL_INSTANCE_CACHE) >= 8:
        _EVAL_INSTANCE_CACHE.clear()
    _EVAL_INSTANCE_CACHE[key] = built
    return built


def prepare_dynamic_candidate(
    individual: DutyIndividual,
    state: DutyDynamicState,
    bundle: China81Bundle,
    *,
    minimum_departure_second_by_customer_id: Mapping[str, float] | None = None,
    shift_id_by_customer_id: Mapping[str, str] | None = None,
) -> PreparedDynamicCandidate:
    """Schedule exact Duty assignments and merge them with immutable history."""

    evaluation_instance = _stage_evaluation_instance(bundle, state)
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
        asset = state.asset_states[asset_id]
        continuation_route_id = getattr(
            asset,
            "continuation_route_id",
            None,
        )
        continuation_origin = _continuation_origin(asset)
        schedule_duty = duty
        if not schedule_duty.trips and continuation_route_id is not None:
            schedule_duty = replace(
                schedule_duty,
                trips=(DutyTrip(trip_index=1, customer_ids=()),),
            )
        if not schedule_duty.trips:
            continue
        open_routes = [
            Route(
                vehicle_id=f"open-{asset_id}-{position}",
                vehicle_type=duty.vehicle_type,
                home_depot_id=duty.home_depot_id,
                node_sequence=[
                    (
                        continuation_origin
                        if position == 1
                        and continuation_route_id is not None
                        and continuation_origin is not None
                        else duty.home_depot_id
                    ),
                    *trip.effective_route_visits,
                    duty.home_depot_id,
                ],
            )
            for position, trip in enumerate(schedule_duty.trips, start=1)
        ]
        open_route_id_by_trip = {
            trip.trip_index: open_routes[position].vehicle_id
            for position, trip in enumerate(schedule_duty.trips)
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
            for session in schedule_duty.charging_sessions
            if node_types.get(session.station_id) == "f"
        ]
        locked = tuple(
            action
            for action in state.cut.locked_charging_actions
            if physical_vehicle_id(action.vehicle_id) == asset_id
        )
        prepared, certificate = prepare_dynamic_multitrip_solution(
            Solution(routes=open_routes, charging_actions=public_actions),
            evaluation_instance,
            bundle.prices,
            asset_states={asset_id: state.asset_states[asset_id]},
            stage_start_second=state.cut.trigger_second,
            locked_charging_actions=locked,
            ordered_route_ids=tuple(route.vehicle_id for route in open_routes),
            minimum_departure_second_by_route=(
                minimum_departure_second_by_route
            ),
        )
        _assert_exact_duty_schedule(schedule_duty, prepared, asset)
        partial_solutions.append(prepared)
        partial_certificates.append(certificate)

    future, certificate = _combine_dynamic_parts(
        partial_solutions,
        partial_certificates,
        state,
        bundle,
        evaluation_instance,
    )
    future, certificate, _ = reschedule_dynamic_charging(
        future,
        certificate,
        evaluation_instance,
        bundle.time_profile,
        bundle.prices,
        asset_states=state.asset_states,
        stage_start_second=state.cut.trigger_second,
        locked_charging_actions=state.cut.locked_charging_actions,
        strategy=state.charging_strategy,
        intensity_field=state.charging_intensity_field,
    )
    full = _merge_execution_history(state, future)
    future_check_context = _future_check_context(
        state,
        certificate,
    )
    frozen_prefixes = MappingProxyType(
        {
            str(asset.continuation_route_id): full_executed_prefix(
                next(
                    route
                    for route in (
                        state.source_full_execution_solution
                        or state.source_solution
                    ).routes
                    if route.vehicle_id == str(asset.continuation_route_id)
                ),
                tuple(asset.executed_prefix),
            )
            for asset in state.asset_states.values()
            if getattr(asset, "continuation_route_id", None) is not None
            and tuple(getattr(asset, "executed_prefix", ()))
        }
    )
    return PreparedDynamicCandidate(
        future_solution=future,
        future_certificate=certificate,
        full_execution_solution=full,
        evaluation_instance=evaluation_instance,
        future_check_instance=_future_check_instance(
            evaluation_instance,
            state.future_customer_ids,
            future,
            future_check_context,
        ),
        future_check_context=future_check_context,
        frozen_prefixes=frozen_prefixes,
    )


def _combine_dynamic_parts(
    solutions: list[Solution],
    certificates: list[MultiTripCertificate],
    state: DutyDynamicState,
    bundle: China81Bundle,
    evaluation_instance: Instance,
) -> tuple[Solution, MultiTripCertificate]:
    if not certificates:
        return prepare_dynamic_multitrip_solution(
            Solution(),
            evaluation_instance,
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
        evaluation_instance,
        bundle.prices,
        asset_states=state.asset_states,
        stage_start_second=state.cut.trigger_second,
        locked_charging_actions=state.cut.locked_charging_actions,
    )
    return future, certificate


def _assert_exact_duty_schedule(
    duty: PhysicalVehicleDuty,
    prepared: Solution,
    asset: DynamicAssetState,
) -> None:
    if {
        physical_vehicle_id(route.vehicle_id) for route in prepared.routes
    } != {duty.physical_vehicle_id}:
        raise ValueError("dynamic scheduler changed the Duty asset assignment")
    ordered = sorted(
        prepared.routes,
        key=lambda route: int(route.vehicle_id.rsplit("#T", 1)[1]),
    )
    continuation_origin = _continuation_origin(asset)
    has_continuation = getattr(asset, "continuation_route_id", None) is not None
    expected = []
    for position, trip in enumerate(duty.trips):
        origin = (
            continuation_origin
            if position == 0
            and has_continuation
            and continuation_origin is not None
            else duty.home_depot_id
        )
        expected.append(
            (
                duty.vehicle_type,
                duty.home_depot_id,
                (
                    origin,
                    *trip.effective_route_visits,
                    duty.home_depot_id,
                ),
            )
        )
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
        route.vehicle_id: route
        for route in (
            state.source_full_execution_solution or state.source_solution
        ).routes
    }
    prior = state.prior_committed_solution or Solution()
    routes = {route.vehicle_id: route for route in prior.routes}
    sealed_in_progress_route_ids = {
        str(asset.in_progress_route_id)
        for asset in state.asset_states.values()
        if getattr(asset, "in_progress_route_id", None) is not None
        and getattr(asset, "continuation_route_id", None) is None
        and not tuple(getattr(asset, "editable_suffix", ()))
    }
    current_committed = {
        route_id: source_routes[route_id]
        for route_id in {
            *state.cut.completed_route_ids,
            *sealed_in_progress_route_ids,
        }
    }
    for route_id, route in current_committed.items():
        previous = routes.get(route_id)
        if previous is not None and previous != route:
            raise ValueError("dynamic cut rewrote earlier committed history")
        routes[route_id] = route
    continuation_by_route_id = {
        str(asset.continuation_route_id): asset
        for asset in state.asset_states.values()
        if getattr(asset, "continuation_route_id", None) is not None
    }
    future_by_id = {route.vehicle_id: route for route in future.routes}
    for route_id in state.cut.in_progress_route_ids:
        source = source_routes[route_id]
        asset = continuation_by_route_id.get(route_id)
        continuation = future_by_id.get(route_id)
        if continuation is None:
            if asset is not None and tuple(
                getattr(asset, "editable_suffix", ())
            ):
                raise ValueError(
                    "dynamic continuation lost a non-empty editable suffix"
                )
            routes[route_id] = source
            continue
        if asset is None:
            raise ValueError("dynamic future has no inherited continuation state")
        prefix = tuple(getattr(asset, "executed_prefix", ()))
        origin = _continuation_origin(asset)
        if not prefix or origin is None:
            raise ValueError("dynamic continuation has no executed-prefix witness")
        if continuation.node_sequence[0] != origin:
            raise ValueError("dynamic continuation changed its virtual origin")
        sequence = [*full_executed_prefix(source, prefix)]
        if sequence[-1] != origin:
            sequence.append(origin)
        sequence.extend(continuation.node_sequence[1:])
        routes[route_id] = replace(source, node_sequence=sequence)

    for route in future.routes:
        if route.vehicle_id in continuation_by_route_id:
            continue
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


def _continuation_origin(asset: DynamicAssetState) -> str | None:
    return (
        getattr(asset, "virtual_origin_node_id", None)
        or getattr(asset, "position_node_id", None)
    )


def full_executed_prefix(
    source_route: Route,
    executed_prefix: tuple[str, ...],
) -> tuple[str, ...]:
    """Recover immutable earlier history before a repeatedly cut prefix."""

    if not executed_prefix:
        return ()
    sequence = tuple(source_route.node_sequence)
    width = len(executed_prefix)
    if sequence[:width] == executed_prefix:
        return executed_prefix
    positions = [
        index
        for index in range(len(sequence) - width + 1)
        if sequence[index : index + width] == executed_prefix
    ]
    if len(positions) != 1:
        raise ValueError(
            "dynamic continuation cannot locate its unique executed prefix"
        )
    return (*sequence[: positions[0]], *executed_prefix)


def _carry_forward_virtual_origins(
    current: Instance,
    inherited: Instance | None,
) -> Instance:
    """Recreate prior virtual nodes from the current physical road truth."""

    if inherited is None:
        return current
    current_ids = {node.node_id for node in current.nodes}
    inherited_nodes = inherited.node_lookup
    inherited_real_ids = {
        node_id
        for node_id, node in inherited_nodes.items()
        if node.node_type.lower() != "v" and node_id in current_ids
    }
    virtual_ids = sorted(
        node_id
        for node_id, node in inherited_nodes.items()
        if node.node_type.lower() == "v" and node_id not in current_ids
    )
    if not virtual_ids:
        return current
    proxy_states: dict[str, DynamicAssetState] = {}
    for position, virtual_id in enumerate(virtual_ids, start=1):
        virtual = inherited_nodes[virtual_id]
        candidates = [
            node_id
            for node_id in inherited_real_ids
            if _same_inherited_road_identity(
                inherited,
                virtual_id,
                node_id,
                inherited_real_ids,
            )
            and float(inherited_nodes[node_id].x) == float(virtual.x)
            and float(inherited_nodes[node_id].y) == float(virtual.y)
        ]
        if len(candidates) != 1:
            raise ValueError(
                "prior virtual origin has no unique physical release node: "
                f"{virtual_id} -> {sorted(candidates)}"
            )
        release_id = candidates[0]
        proxy_states[virtual_id] = DynamicAssetState(
            physical_vehicle_id=f"CV_VIRTUAL_CARRY_{position}",
            vehicle_type="cv",
            home_depot_id=release_id,
            available_second=float(virtual.ready_time),
            remaining_battery_kwh=0.0,
            next_trip_index=1,
            release_node_id=release_id,
            virtual_origin_node_id=virtual_id,
        )
    return instance_with_inherited_virtual_origins(current, proxy_states)


def _same_inherited_road_identity(
    instance: Instance,
    left_id: str,
    right_id: str,
    comparison_ids: set[str],
) -> bool:
    left = instance.node_index[left_id]
    right = instance.node_index[right_id]
    indices = [instance.node_index[node_id] for node_id in comparison_ids]
    if any(
        float(instance.distance_matrix[left][index])
        != float(instance.distance_matrix[right][index])
        or float(instance.distance_matrix[index][left])
        != float(instance.distance_matrix[index][right])
        for index in indices
    ):
        return False
    if instance.road_profiles is None:
        return True
    for matrices in instance.road_profiles.values():
        for matrix in (
            matrices.distance_m,
            matrices.duration_s,
            matrices.sum_v2d_m3_s2,
        ):
            if any(
                float(matrix[left][index]) != float(matrix[right][index])
                or float(matrix[index][left]) != float(matrix[index][right])
                for index in indices
            ):
                return False
    return True


def _future_check_context(
    state: DutyDynamicState,
    certificate: MultiTripCertificate,
) -> DynamicCheckContext:
    trips_by_asset_and_index = {
        (trip.physical_vehicle_id, int(trip.trip_index)): trip
        for trip in certificate.trips
    }
    vehicle_states: dict[str, DynamicVehicleState] = {}
    for asset_id, asset in state.asset_states.items():
        continuation_index = getattr(asset, "continuation_trip_index", None)
        origin = _continuation_origin(asset)
        if continuation_index is None or origin is None:
            continue
        trip = trips_by_asset_and_index.get(
            (asset_id, int(continuation_index))
        )
        if trip is None:
            continue
        vehicle_states[trip.route_id] = DynamicVehicleState(
            vehicle_id=trip.route_id,
            position_node_id=origin,
            current_time=float(asset.available_second),
            remaining_load_kg=float(
                getattr(asset, "remaining_load_kg", 0.0)
            ),
            remaining_battery_kwh=float(asset.remaining_battery_kwh),
        )
    return DynamicCheckContext(
        vehicle_states=vehicle_states,
        reserved_charging_actions=tuple(state.cut.locked_charging_actions),
        allow_open_start=True,
    )


def _future_check_instance(
    instance: Instance,
    future_customer_ids: frozenset[str],
    future_solution: Solution,
    dynamic_context: DynamicCheckContext,
) -> Instance:
    """Expose future service with open-route ready times on a relative clock."""

    ready_offset: dict[str, float] = {}
    for route in future_solution.routes:
        inherited = dynamic_context.vehicle_states.get(route.vehicle_id)
        if inherited is None:
            continue
        for node_id in route.node_sequence[1:-1]:
            previous = ready_offset.get(node_id)
            offset = float(inherited.current_time)
            if previous is not None and not math.isclose(
                previous,
                offset,
                rel_tol=0.0,
                abs_tol=1.0e-9,
            ):
                raise ValueError(
                    "one future node is assigned to incompatible open clocks"
                )
            ready_offset[node_id] = offset
    nodes = [
        (
            replace(node, node_type="executed")
            if node.node_type.lower() == "c"
            and node.node_id not in future_customer_ids
            else (
                replace(
                    node,
                    ready_time=max(
                        0.0,
                        float(node.ready_time)
                        - float(ready_offset[node.node_id]),
                    ),
                )
                if node.node_id in ready_offset
                else node
            )
        )
        for node in instance.nodes
    ]
    return replace(instance, nodes=nodes)


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
