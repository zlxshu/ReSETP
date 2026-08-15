"""Exact-event static duty scheduling prototype for DSS v2 step 1.

The module deliberately stays outside crossover and education.  It builds a
formal ``ScheduledDuty`` frontier for a fixed structural duty, verifies every
terminal label against the protected cost implementation, and exposes the
checker-equivalent capacity calendar used by the prototype coordinator.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from time import perf_counter
from typing import Any

from setp_solver.charging_action import _curve_aware_action
from setp_solver.charging_curve import (
    PiecewiseChargingCurve,
    curve_for_charging_node,
)
from setp_solver.cost import (
    CARBON_SLOT_SECONDS,
    GCO2_PER_KGCO2,
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    carbon_profile_row_for_slot,
    ev_instance_arc_energy_kwh,
    time_profile_rows_for_node,
)
from setp_solver.cost import _charging_occupancy_cost
from setp_solver.instance_loader import Instance, Node
from setp_solver.search.multitrip_schedule import route_timing
from setp_solver.solution import ChargingAction, Route, Solution
from setp_solver.station_copies import physical_station_id

from .evaluation import DutyEvaluationContext, evaluation_context_sha256
from .model import (
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
    ScheduleAccountingVector,
    ScheduledChargingSession,
    ScheduledDuty,
    ScheduledSOCPoint,
    ScheduledTripWitness,
    duty_trip_route_signature,
)


SCHEDULE_SCHEMA_VERSION = "DSS_STEP1_SCHEDULE_V1"
EVENT_CONSTRUCTION_VERSION = "FINITE_PWL_VERTEX_EVENTS_V1"
CAPACITY_SEMANTICS_VERSION = "CHECK_PY_583_644_20260810"
DOMINANCE_VERSION = "TIME_SOC_COMPONENTS_OCCUPANCY_SUBSET_V1"
ORACLE_MODE = "STATIC_EXACT_NO_RESOURCE_LIMITS"
_TOL = 1.0e-7


class OracleStatus(StrEnum):
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    SEARCH_EXHAUSTED = "SEARCH_EXHAUSTED"


@dataclass(frozen=True)
class CapacityCalendarEntry:
    capacity: int
    occupied_action_vehicle_ids: frozenset[str]

    @property
    def remaining(self) -> int:
        return int(self.capacity) - len(self.occupied_action_vehicle_ids)


@dataclass(frozen=True)
class ScheduleOracleResult:
    status: OracleStatus
    frontier: tuple[ScheduledDuty, ...]
    failure_reason: str | None
    failure_certificate: Mapping[str, Any]
    accounting: Mapping[str, Any]
    cache_hit: bool
    wall_seconds: float


@dataclass(frozen=True)
class ScheduleCoordinatorResult:
    status: OracleStatus
    frontier: tuple[DutyIndividual, ...]
    failure_reason: str | None
    accounting: Mapping[str, Any]
    wall_seconds: float


@dataclass(frozen=True)
class _StationContext:
    node: Node
    physical_station_id: str
    curve: PiecewiseChargingCurve
    price_by_slot: tuple[float, ...]
    emissions_kg_per_kwh_by_slot: tuple[float, ...]
    capacity: int


@dataclass(frozen=True)
class ScheduleOracleContext:
    instance: Instance
    prices: Any
    time_profile: list[dict[str, Any]]
    node_by_id: Mapping[str, Node]
    stations: Mapping[str, _StationContext]
    evaluation_context_sha256: str
    schedule_contract_sha256: str
    depot_charge_window_mode: str

    @classmethod
    def from_evaluation_context(
        cls,
        context: DutyEvaluationContext,
    ) -> "ScheduleOracleContext":
        return cls.compile(
            instance=context.bundle.instance,
            prices=context.bundle.prices,
            time_profile=context.bundle.time_profile,
            evaluation_sha256=evaluation_context_sha256(context),
            depot_charge_window_mode=context.depot_charge_window_mode,
        )

    @classmethod
    def compile(
        cls,
        *,
        instance: Instance,
        prices: Any,
        time_profile: list[dict[str, Any]],
        evaluation_sha256: str,
        depot_charge_window_mode: str,
    ) -> "ScheduleOracleContext":
        node_by_id = {node.node_id: node for node in instance.nodes}
        customer_count = sum(
            node.node_type.lower() == "c" for node in instance.nodes
        )
        battery = instance.battery_capacity_kwh(
            fallback=_price(prices, "B_battery_kwh")
        )
        stations: dict[str, _StationContext] = {}
        for node in instance.nodes:
            node_type = node.node_type.lower()
            if node_type not in {"d", "f"}:
                continue
            reference_power = (
                _price(prices, "depot_charge_power_kw")
                if node_type == "d"
                else float(node.charge_power_kw or 0.0)
            )
            curve = curve_for_charging_node(
                prices,
                node_type=node_type,
                capacity_kwh=battery,
                reference_power_kw=reference_power,
            )
            rows = time_profile_rows_for_node(
                instance,
                node.node_id,
                time_profile,
            )
            if not rows:
                raise ValueError("schedule Oracle requires a non-empty time profile")
            resolved = tuple(
                carbon_profile_row_for_slot(rows, index)
                for index in range(len(rows))
            )
            price_field = (
                "depot_energy_cny_per_kwh"
                if node_type == "d"
                else "public_total_cny_per_kwh"
            )
            complete_prices = all(price_field in row for row in resolved)
            fallback_price = (
                _price(prices, "depot_electricity_price")
                if node_type == "d"
                else _price(prices, "station_electricity_price")
            )
            prices_by_slot = tuple(
                float(row[price_field]) if complete_prices else fallback_price
                for row in resolved
            )
            emissions_by_slot = tuple(
                float(row["actual_gco2_per_kwh"]) / GCO2_PER_KGCO2
                for row in resolved
            )
            stations[node.node_id] = _StationContext(
                node=node,
                physical_station_id=physical_station_id(node),
                curve=curve,
                price_by_slot=prices_by_slot,
                emissions_kg_per_kwh_by_slot=emissions_by_slot,
                capacity=_station_capacity(node, customer_count),
            )
        contract_payload = {
            "schema": SCHEDULE_SCHEMA_VERSION,
            "event_construction": EVENT_CONSTRUCTION_VERSION,
            "capacity_semantics": CAPACITY_SEMANTICS_VERSION,
            "dominance": DOMINANCE_VERSION,
            "oracle_mode": ORACLE_MODE,
            "slot_seconds": CARBON_SLOT_SECONDS.hex(),
            "float_identity": "float.hex",
            "physical_tolerance": _TOL.hex(),
            "resource_limits": None,
            "evaluation_context_sha256": str(evaluation_sha256),
            "depot_charge_window_mode": str(depot_charge_window_mode),
            "stations": [
                {
                    "node_id": node_id,
                    "physical_station_id": station.physical_station_id,
                    "curve_id": station.curve.curve_id,
                    "curve_physical_sha256": (
                        station.curve.physical_parameter_sha256
                    ),
                    "profile_slots": len(station.price_by_slot),
                    "capacity": station.capacity,
                }
                for node_id, station in sorted(stations.items())
            ],
        }
        encoded = json.dumps(
            contract_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(
            instance=instance,
            prices=prices,
            time_profile=time_profile,
            node_by_id=node_by_id,
            stations=stations,
            evaluation_context_sha256=str(evaluation_sha256),
            schedule_contract_sha256=hashlib.sha256(encoded).hexdigest(),
            depot_charge_window_mode=str(depot_charge_window_mode),
        )


@dataclass(frozen=True)
class _RoutePlan:
    trip: DutyTrip
    route: Route
    arc_travel_seconds: tuple[float, ...]
    arc_energy_kwh: tuple[float, ...]
    latest_departure_by_position: tuple[float, ...]
    drive_energy_kwh: float
    route_time_cost: float


@dataclass(frozen=True)
class _Label:
    progress: int
    time_second: float
    soc_kwh: float | None
    accounting: ScheduleAccountingVector
    occupancy: frozenset[tuple[str, int, int, str]]
    trip_witnesses: tuple[ScheduledTripWitness, ...] = ()
    soc_points: tuple[ScheduledSOCPoint, ...] = ()
    charging_sessions: tuple[ScheduledChargingSession, ...] = ()


@dataclass
class _Counters:
    event_count: int = 0
    labels_generated: int = 0
    labels_pruned: int = 0
    slot_pricing_calls: int = 0
    curve_transitions: int = 0
    pricing_mismatches: int = 0
    constraint_rejections: Counter[str] = field(default_factory=Counter)
    last_reachable_progress: int = 0


class SingleDutyScheduleOracle:
    """Generate the complete conservative frontier for one static duty."""

    def __init__(self, context: ScheduleOracleContext):
        self.context = context
        self._cache: dict[tuple[str, ...], ScheduleOracleResult] = {}

    def solve(self, duty: PhysicalVehicleDuty) -> ScheduleOracleResult:
        started = perf_counter()
        lock_payload = [
            asdict(session)
            for session in duty.charging_sessions
            if session.locked
        ]
        lock_sha = hashlib.sha256(
            json.dumps(
                _float_hex_identity(lock_payload),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        initial_soc = (
            0.0
            if duty.vehicle_type == "cv"
            else _price(self.context.prices, "initial_ev_battery_kwh")
        )
        initial_sha = hashlib.sha256(
            json.dumps(
                {
                    "home": duty.home_depot_id,
                    "initial_soc_hex": float(initial_soc).hex(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        key = (
            duty.structure_fingerprint,
            initial_sha,
            lock_sha,
            self.context.evaluation_context_sha256,
            self.context.schedule_contract_sha256,
            ORACLE_MODE,
        )
        cached = self._cache.get(key)
        if cached is not None:
            elapsed = perf_counter() - started
            return replace(cached, cache_hit=True, wall_seconds=elapsed)
        result = self._solve_uncached(duty)
        elapsed = perf_counter() - started
        result = replace(result, cache_hit=False, wall_seconds=elapsed)
        self._cache[key] = result
        return result

    def _solve_uncached(
        self,
        duty: PhysicalVehicleDuty,
    ) -> ScheduleOracleResult:
        counters = _Counters()
        if self.context.depot_charge_window_mode != "same_day_predeparture":
            return self._exhausted(
                "UNSUPPORTED_DEPOT_WINDOW_MODE",
                counters,
                "step-1 prototype currently implements same-day static clocks",
            )
        if duty.has_dynamic_commitment or any(
            session.locked for session in duty.charging_sessions
        ):
            return self._exhausted(
                "LOCK_CONFLICT",
                counters,
                "step-1 static Oracle does not rewrite committed history",
            )
        if not duty.trips:
            return ScheduleOracleResult(
                status=OracleStatus.FEASIBLE,
                frontier=(),
                failure_reason=None,
                failure_certificate={},
                accounting=_accounting_payload(counters, frontier_size=0),
                cache_hit=False,
                wall_seconds=0.0,
            )
        try:
            plans = tuple(self._compile_route(duty, trip) for trip in duty.trips)
        except (KeyError, TypeError, ValueError) as exc:
            return self._exhausted(
                "EVENT_LIMIT",
                counters,
                f"event construction failed: {type(exc).__name__}: {exc}",
            )
        initial_soc = (
            None
            if duty.vehicle_type == "cv"
            else _price(self.context.prices, "initial_ev_battery_kwh")
        )
        labels = [
            _Label(
                progress=0,
                time_second=0.0,
                soc_kwh=initial_soc,
                accounting=ScheduleAccountingVector(),
                occupancy=frozenset(),
            )
        ]
        for plan in plans:
            expanded: list[_Label] = []
            for label in labels:
                expanded.extend(
                    self._extend_trip(duty, plan, label, plans, counters)
                )
            counters.labels_generated += len(expanded)
            if not expanded:
                certificate = {
                    "last_reachable_progress": counters.last_reachable_progress,
                    "constraint_rejections": dict(
                        sorted(counters.constraint_rejections.items())
                    ),
                    "event_count": counters.event_count,
                    "labels_generated": counters.labels_generated,
                    "labels_pruned": counters.labels_pruned,
                }
                return ScheduleOracleResult(
                    status=OracleStatus.INFEASIBLE,
                    frontier=(),
                    failure_reason="NO_TIME_WINDOW_OR_SOC_PATH",
                    failure_certificate=certificate,
                    accounting=_accounting_payload(counters, frontier_size=0),
                    cache_hit=False,
                    wall_seconds=0.0,
                )
            labels = _prune_labels(expanded, counters)
            counters.last_reachable_progress = int(plan.trip.trip_index)

        schedules: list[ScheduledDuty] = []
        for label in _prune_labels(labels, counters):
            schedule = ScheduledDuty(
                physical_vehicle_id=duty.physical_vehicle_id,
                vehicle_type=duty.vehicle_type,
                home_depot_id=duty.home_depot_id,
                trip_witnesses=label.trip_witnesses,
                soc_points=label.soc_points,
                charging_sessions=label.charging_sessions,
                occupancy_signature=tuple(sorted(label.occupancy)),
                local_accounting_vector=label.accounting,
                schedule_contract_sha256=(
                    self.context.schedule_contract_sha256
                ),
            )
            if self._terminal_pricing_matches(duty, schedule, counters):
                schedules.append(schedule)
        schedules = _prune_schedules(schedules, counters)
        if not schedules:
            return ScheduleOracleResult(
                status=OracleStatus.INFEASIBLE,
                frontier=(),
                failure_reason=(
                    "CURVE_MISMATCH"
                    if counters.pricing_mismatches
                    else "NO_TERMINAL_LABEL"
                ),
                failure_certificate={
                    "last_reachable_progress": counters.last_reachable_progress,
                    "pricing_mismatches": counters.pricing_mismatches,
                    "constraint_rejections": dict(
                        sorted(counters.constraint_rejections.items())
                    ),
                },
                accounting=_accounting_payload(counters, frontier_size=0),
                cache_hit=False,
                wall_seconds=0.0,
            )
        schedules.sort(key=lambda item: item.schedule_fingerprint)
        return ScheduleOracleResult(
            status=OracleStatus.FEASIBLE,
            frontier=tuple(schedules),
            failure_reason=None,
            failure_certificate={},
            accounting=_accounting_payload(
                counters,
                frontier_size=len(schedules),
            ),
            cache_hit=False,
            wall_seconds=0.0,
        )

    def _exhausted(
        self,
        reason: str,
        counters: _Counters,
        detail: str,
    ) -> ScheduleOracleResult:
        return ScheduleOracleResult(
            status=OracleStatus.SEARCH_EXHAUSTED,
            frontier=(),
            failure_reason=reason,
            failure_certificate={"detail": detail},
            accounting=_accounting_payload(counters, frontier_size=0),
            cache_hit=False,
            wall_seconds=0.0,
        )

    def _compile_route(
        self,
        duty: PhysicalVehicleDuty,
        trip: DutyTrip,
    ) -> _RoutePlan:
        route = Route(
            vehicle_id=duty.route_id(trip.trip_index),
            vehicle_type=duty.vehicle_type,
            home_depot_id=duty.home_depot_id,
            node_sequence=[
                duty.home_depot_id,
                *trip.effective_route_visits,
                duty.home_depot_id,
            ],
        )
        nodes = self.context.node_by_id
        loads = _arc_loads(route.node_sequence, nodes)
        travel: list[float] = []
        energies: list[float] = []
        for index, (left, right) in enumerate(
            zip(route.node_sequence, route.node_sequence[1:])
        ):
            _, seconds, _ = self.context.instance.arc_metrics(
                left,
                right,
                duty.vehicle_type,
                fallback_speed_mps=_price(self.context.prices, "v_speed_ms"),
            )
            travel.append(float(seconds))
            energies.append(
                0.0
                if duty.vehicle_type == "cv"
                else ev_instance_arc_energy_kwh(
                    self.context.instance,
                    left,
                    right,
                    loads[index],
                    self.context.prices,
                )
            )
        latest_depart = _latest_departures(
            route.node_sequence,
            travel,
            nodes,
        )
        route_time_cost = (
            sum(travel)
            / 3600.0
            * _optional_price(self.context.prices, "route_time_cost_per_hour")
        )
        return _RoutePlan(
            trip=trip,
            route=route,
            arc_travel_seconds=tuple(travel),
            arc_energy_kwh=tuple(energies),
            latest_departure_by_position=latest_depart,
            drive_energy_kwh=sum(energies),
            route_time_cost=route_time_cost,
        )

    def _extend_trip(
        self,
        duty: PhysicalVehicleDuty,
        plan: _RoutePlan,
        label: _Label,
        plans: Sequence[_RoutePlan],
        counters: _Counters,
    ) -> list[_Label]:
        if duty.vehicle_type == "cv":
            return self._execute_route(
                duty,
                plan,
                label,
                departure_second=max(
                    float(label.time_second),
                    float(self.context.node_by_id[duty.home_depot_id].ready_time),
                ),
                departure_soc=None,
                added_session=None,
                added_points=(),
                added_accounting=ScheduleAccountingVector(),
                added_occupancy=frozenset(),
                counters=counters,
            )

        assert label.soc_kwh is not None
        depot = self.context.stations[duty.home_depot_id]
        earliest = 0.0 if plan.trip.trip_index == 1 else float(label.time_second)
        latest_departure = float(plan.latest_departure_by_position[0])
        first_public_prefix = 0.0
        for position, energy in enumerate(plan.arc_energy_kwh, start=1):
            first_public_prefix += float(energy)
            node_id = plan.route.node_sequence[position]
            if self.context.node_by_id[node_id].node_type.lower() == "f":
                break
        else:
            first_public_prefix = float(plan.drive_energy_kwh)
        future_needs = [
            sum(item.arc_energy_kwh)
            for item in plans[int(plan.trip.trip_index) - 1 :]
        ]
        options = self._charge_options(
            duty=duty,
            trip_index=int(plan.trip.trip_index),
            station=depot,
            start_soc=float(label.soc_kwh),
            minimum_departure_soc=float(first_public_prefix),
            future_needs=future_needs,
            earliest_start=earliest,
            latest_end=latest_departure,
            relation=(
                "BEFORE_FIRST"
                if int(plan.trip.trip_index) == 1
                else "BETWEEN_TRIPS"
            ),
            counters=counters,
        )
        out: list[_Label] = []
        for end_time, end_soc, session, vector, occupancy, points in options:
            depart = max(
                float(end_time),
                float(self.context.node_by_id[duty.home_depot_id].ready_time),
            )
            out.extend(
                self._execute_route(
                    duty,
                    plan,
                    label,
                    departure_second=depart,
                    departure_soc=end_soc,
                    added_session=session,
                    added_points=points,
                    added_accounting=vector,
                    added_occupancy=occupancy,
                    counters=counters,
                )
            )
        return out

    def _charge_options(
        self,
        *,
        duty: PhysicalVehicleDuty,
        trip_index: int,
        station: _StationContext,
        start_soc: float,
        minimum_departure_soc: float,
        future_needs: Sequence[float],
        earliest_start: float,
        latest_end: float,
        relation: str,
        counters: _Counters,
    ) -> list[
        tuple[
            float,
            float,
            ScheduledChargingSession | None,
            ScheduleAccountingVector,
            frozenset[tuple[str, int, int, str]],
            tuple[ScheduledSOCPoint, ...],
        ]
    ]:
        if start_soc > station.curve.capacity_kwh + _TOL:
            counters.constraint_rejections["SOC_DEFICIT"] += 1
            return []
        targets = _energy_targets(
            station.curve,
            start_soc=start_soc,
            minimum_soc=minimum_departure_soc,
            future_needs=future_needs,
            earliest_start=earliest_start,
            latest_end=latest_end,
        )
        counters.event_count += len(targets)
        out = []
        if start_soc + _TOL >= minimum_departure_soc:
            out.append(
                (
                    float(earliest_start),
                    float(start_soc),
                    None,
                    ScheduleAccountingVector(),
                    frozenset(),
                    (),
                )
            )
        for target in targets:
            if target <= start_soc + _TOL or target + _TOL < minimum_departure_soc:
                continue
            action = _curve_aware_action(
                vehicle_id=duty.route_id(trip_index),
                station_id=station.node.node_id,
                start_energy_kwh=start_soc,
                energy_kwh=target - start_soc,
                reference_power_kw=(
                    _price(self.context.prices, "depot_charge_power_kw")
                    if station.node.node_type.lower() == "d"
                    else float(station.node.charge_power_kw or 0.0)
                ),
                prices=self.context.prices,
                instance=self.context.instance,
            )
            duration = float(action.occupancy_minutes) * 60.0
            latest_start = float(latest_end) - duration
            if latest_start < earliest_start - _TOL:
                counters.constraint_rejections["NO_TIME_WINDOW"] += 1
                continue
            starts = _charge_start_events(
                station.curve,
                start_soc,
                target,
                earliest_start,
                latest_start,
            )
            counters.event_count += len(starts)
            for start in starts:
                shifted = replace(
                    action,
                    charge_start_second=float(start),
                    charge_day_offset=(
                        -1
                        if relation == "BEFORE_FIRST"
                        and self.context.depot_charge_window_mode
                        in {"prev_night", "full_gap"}
                        else 0
                    ),
                )
                vector, slots = self._precompiled_charge_accounting(
                    shifted,
                    station,
                    counters,
                )
                if relation == "BEFORE_FIRST":
                    after_trip = None
                    before_trip = 1
                    route_trip = None
                elif relation == "BETWEEN_TRIPS":
                    after_trip = trip_index - 1
                    before_trip = trip_index
                    route_trip = None
                else:
                    after_trip = None
                    before_trip = None
                    route_trip = trip_index
                session = ScheduledChargingSession(
                    relation=relation,
                    after_trip_index=after_trip,
                    before_trip_index=before_trip,
                    route_trip_index=route_trip,
                    station_id=station.node.node_id,
                    physical_station_id=station.physical_station_id,
                    charge_start_second=float(start),
                    charge_end_second=float(start) + duration,
                    charge_day_offset=int(shifted.charge_day_offset),
                    start_energy_kwh=start_soc,
                    end_energy_kwh=target,
                    energy_kwh=target - start_soc,
                    occupancy_minutes=float(shifted.occupancy_minutes),
                    charging_curve_id=str(shifted.charging_curve_id),
                    locked=False,
                )
                points = _charging_soc_points(
                    station.curve,
                    session,
                    trip_index=trip_index,
                    starting_index=0,
                )
                out.append(
                    (
                        float(start) + duration,
                        target,
                        session,
                        vector,
                        slots,
                        points,
                    )
                )
                counters.curve_transitions += len(points)
        return _prune_charge_options(out, counters)

    def _execute_route(
        self,
        duty: PhysicalVehicleDuty,
        plan: _RoutePlan,
        base: _Label,
        *,
        departure_second: float,
        departure_soc: float | None,
        added_session: ScheduledChargingSession | None,
        added_points: tuple[ScheduledSOCPoint, ...],
        added_accounting: ScheduleAccountingVector,
        added_occupancy: frozenset[tuple[str, int, int, str]],
        counters: _Counters,
    ) -> list[_Label]:
        if departure_second > plan.latest_departure_by_position[0] + _TOL:
            counters.constraint_rejections["NO_TIME_WINDOW"] += 1
            return []
        points = list(base.soc_points)
        for point in added_points:
            points.append(replace(point, event_index=len(points)))
        sessions = list(base.charging_sessions)
        if added_session is not None:
            sessions.append(added_session)
        accounting = _add_vectors(base.accounting, added_accounting)
        accounting = _add_vectors(
            accounting,
            ScheduleAccountingVector(route_time_cost=plan.route_time_cost),
        )
        occupancy = frozenset((*base.occupancy, *added_occupancy))
        if departure_soc is not None:
            points.append(
                ScheduledSOCPoint(
                    event_index=len(points),
                    event_kind="TRIP_DEPARTURE",
                    trip_index=int(plan.trip.trip_index),
                    node_id=duty.home_depot_id,
                    event_second=float(departure_second),
                    soc_before_kwh=float(departure_soc),
                    soc_after_kwh=float(departure_soc),
                )
            )
        states = [
            (
                float(departure_second),
                departure_soc,
                accounting,
                occupancy,
                tuple(points),
                tuple(sessions),
            )
        ]
        for arc_index, (left, right) in enumerate(
            zip(plan.route.node_sequence, plan.route.node_sequence[1:])
        ):
            advanced = []
            node = self.context.node_by_id[right]
            for (
                current_time,
                current_soc,
                current_vector,
                current_occupancy,
                current_points,
                current_sessions,
            ) in states:
                arrive = current_time + plan.arc_travel_seconds[arc_index]
                service_start = max(arrive, float(node.ready_time))
                if service_start > float(node.due_time) + 1.0e-6:
                    counters.constraint_rejections["NO_TIME_WINDOW"] += 1
                    continue
                next_soc = current_soc
                next_points = list(current_points)
                if current_soc is not None:
                    next_soc = current_soc - plan.arc_energy_kwh[arc_index]
                    if next_soc < -_TOL:
                        counters.constraint_rejections["SOC_DEFICIT"] += 1
                        continue
                    next_soc = max(0.0, next_soc)
                    next_points.append(
                        ScheduledSOCPoint(
                            event_index=len(next_points),
                            event_kind="DRIVE",
                            trip_index=int(plan.trip.trip_index),
                            node_id=right,
                            event_second=float(arrive),
                            soc_before_kwh=float(current_soc),
                            soc_after_kwh=float(next_soc),
                        )
                    )
                base_depart = service_start + float(node.service_time)
                if (
                    current_soc is None
                    or node.node_type.lower() != "f"
                    or arc_index == len(plan.arc_energy_kwh) - 1
                ):
                    advanced.append(
                        (
                            base_depart,
                            next_soc,
                            current_vector,
                            current_occupancy,
                            tuple(next_points),
                            current_sessions,
                        )
                    )
                    continue
                station = self.context.stations[right]
                minimum = sum(plan.arc_energy_kwh[arc_index + 1 :])
                charge_options = self._charge_options(
                    duty=duty,
                    trip_index=int(plan.trip.trip_index),
                    station=station,
                    start_soc=float(next_soc),
                    minimum_departure_soc=float(minimum),
                    future_needs=(minimum,),
                    earliest_start=base_depart,
                    latest_end=float(
                        plan.latest_departure_by_position[arc_index + 1]
                    ),
                    relation="EN_ROUTE",
                    counters=counters,
                )
                for end_time, end_soc, session, vector, slots, charge_points in charge_options:
                    public_points = list(next_points)
                    for point in charge_points:
                        public_points.append(
                            replace(point, event_index=len(public_points))
                        )
                    public_sessions = list(current_sessions)
                    if session is not None:
                        public_sessions.append(session)
                    advanced.append(
                        (
                            end_time,
                            end_soc,
                            _add_vectors(current_vector, vector),
                            frozenset((*current_occupancy, *slots)),
                            tuple(public_points),
                            tuple(public_sessions),
                        )
                    )
            states = _prune_route_states(advanced, counters)
            if not states:
                return []

        out: list[_Label] = []
        trip_session_start = len(base.charging_sessions)
        for end_time, end_soc, vector, occ, route_points, all_sessions in states:
            trip_actions = [
                _session_action(session, duty)
                for session in all_sessions[trip_session_start:]
                if session.legacy_trip_index == int(plan.trip.trip_index)
            ]
            try:
                truth = route_timing(
                    plan.route,
                    self.context.instance,
                    self.context.prices,
                    charging_actions=trip_actions,
                    validate_battery=True,
                    forced_departure_second=float(departure_second),
                )
            except (TypeError, ValueError):
                counters.constraint_rejections["REPLAY_MISMATCH"] += 1
                continue
            if abs(float(truth.return_second) - float(end_time)) > 1.0e-6:
                counters.constraint_rejections["REPLAY_MISMATCH"] += 1
                continue
            witness = ScheduledTripWitness(
                trip_index=int(plan.trip.trip_index),
                route_signature=duty_trip_route_signature(plan.trip),
                departure_second=float(departure_second),
                return_second=float(end_time),
                start_soc_kwh=departure_soc,
                end_soc_kwh=end_soc,
            )
            out.append(
                _Label(
                    progress=int(plan.trip.trip_index),
                    time_second=float(end_time),
                    soc_kwh=end_soc,
                    accounting=vector,
                    occupancy=occ,
                    trip_witnesses=(*base.trip_witnesses, witness),
                    soc_points=route_points,
                    charging_sessions=all_sessions,
                )
            )
        return out

    def _precompiled_charge_accounting(
        self,
        action: ChargingAction,
        station: _StationContext,
        counters: _Counters,
    ) -> tuple[
        ScheduleAccountingVector,
        frozenset[tuple[str, int, int, str]],
    ]:
        rows = _independent_slot_energy_rows(
            station.curve,
            start_energy=float(action.start_energy_kwh),
            end_energy=float(action.end_energy_kwh),
            start_second=float(action.charge_start_second),
        )
        counters.slot_pricing_calls += 1
        electricity = 0.0
        emissions = 0.0
        occupancy = set()
        for absolute_slot, energy in rows:
            slot = int(absolute_slot) % len(station.price_by_slot)
            electricity += energy * station.price_by_slot[slot]
            emissions += energy * station.emissions_kg_per_kwh_by_slot[slot]
            occupancy.add(
                (
                    station.physical_station_id,
                    int(action.charge_day_offset),
                    slot,
                    action.vehicle_id,
                )
            )
        occupancy_cost = (
            0.0
            if station.node.node_type.lower() == "d"
            else float(action.occupancy_minutes)
            * _price(self.context.prices, "occupancy_fee")
        )
        return (
            ScheduleAccountingVector(
                electricity_cost=electricity,
                emissions_kg=emissions,
                occupancy_cost=occupancy_cost,
            ),
            frozenset(occupancy),
        )

    def _terminal_pricing_matches(
        self,
        duty: PhysicalVehicleDuty,
        schedule: ScheduledDuty,
        counters: _Counters,
    ) -> bool:
        projected = replace(duty, schedule=schedule, charging_sessions=())
        solution = DutyIndividual(
            duties=(projected,),
            source="schedule-oracle-terminal-pricing-check",
        ).to_solution()
        truth_electricity = sum(
            charging_action_electricity_cost(
                action,
                self.context.instance,
                self.context.time_profile,
                self.context.prices,
            )
            for action in solution.charging_actions
        )
        truth_emissions = sum(
            charging_action_emissions_kg(
                action,
                self.context.instance,
                self.context.time_profile,
                self.context.prices,
            )
            for action in solution.charging_actions
        )
        truth_occupancy = _charging_occupancy_cost(
            solution,
            dict(self.context.node_by_id),
            self.context.prices,
        )
        vector = schedule.local_accounting_vector
        matches = (
            math.isclose(
                float(vector.electricity_cost),
                float(truth_electricity),
                rel_tol=1.0e-12,
                abs_tol=1.0e-9,
            )
            and math.isclose(
                float(vector.emissions_kg),
                float(truth_emissions),
                rel_tol=1.0e-12,
                abs_tol=1.0e-9,
            )
            and math.isclose(
                float(vector.occupancy_cost),
                float(truth_occupancy),
                rel_tol=1.0e-12,
                abs_tol=1.0e-9,
            )
        )
        if not matches:
            counters.pricing_mismatches += 1
            counters.constraint_rejections["CURVE_MISMATCH"] += 1
        return matches


class ScheduleCoordinator:
    """Combine exact single-duty frontiers under checker-identical capacity."""

    def __init__(
        self,
        context: ScheduleOracleContext,
        oracle: SingleDutyScheduleOracle | None = None,
        result_sink: Callable[[ScheduleOracleResult], None] | None = None,
    ):
        self.context = context
        self.oracle = oracle or SingleDutyScheduleOracle(context)
        self.result_sink = result_sink
        self._cache: dict[tuple[str, ...], ScheduleCoordinatorResult] = {}

    def coordinate(
        self,
        reference: DutyIndividual,
        candidate: DutyIndividual,
        *,
        changed_duty_ids: Iterable[str],
    ) -> ScheduleCoordinatorResult:
        started = perf_counter()
        changed = frozenset(str(item) for item in changed_duty_ids)
        candidate_by_id = {
            duty.physical_vehicle_id: duty for duty in candidate.duties
        }
        unknown = changed.difference(candidate_by_id)
        if unknown:
            return ScheduleCoordinatorResult(
                status=OracleStatus.SEARCH_EXHAUSTED,
                frontier=(),
                failure_reason=f"unknown changed duties: {sorted(unknown)}",
                accounting={},
                wall_seconds=perf_counter() - started,
            )
        unchanged = tuple(
            duty
            for duty in candidate.duties
            if duty.physical_vehicle_id not in changed
        )
        unchanged_solution = DutyIndividual(
            duties=unchanged,
            source="schedule-coordinator-unchanged-calendar",
        ).to_solution()
        calendar = build_capacity_calendar(
            unchanged_solution,
            self.context.instance,
            self.context.prices,
        )
        calendar_sha = capacity_calendar_fingerprint(calendar)
        oracle_rows: list[tuple[PhysicalVehicleDuty, ScheduleOracleResult]] = []
        for duty_id in sorted(changed):
            duty = candidate_by_id[duty_id]
            result = self.oracle.solve(duty)
            if self.result_sink is not None:
                self.result_sink(result)
            if result.status != OracleStatus.FEASIBLE:
                return ScheduleCoordinatorResult(
                    status=result.status,
                    frontier=(),
                    failure_reason=result.failure_reason,
                    accounting={
                        "schedule_oracle_status": result.status.value,
                        "schedule_oracle_accounting": dict(result.accounting),
                    },
                    wall_seconds=perf_counter() - started,
                )
            oracle_rows.append((duty, result))
        frontier_identities = []
        for duty, result in oracle_rows:
            encoded = "".join(
                schedule.schedule_fingerprint
                for schedule in result.frontier
            ).encode("ascii")
            frontier_identities.extend(
                (
                    duty.physical_vehicle_id,
                    duty.structure_fingerprint,
                    hashlib.sha256(encoded).hexdigest(),
                )
            )
        cache_key = (
            *frontier_identities,
            calendar_sha,
            self.context.evaluation_context_sha256,
            self.context.schedule_contract_sha256,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return replace(cached, wall_seconds=perf_counter() - started)
        ordered = sorted(
            oracle_rows,
            key=lambda row: (
                len(row[1].frontier) if row[0].trips else 1,
                row[0].physical_vehicle_id,
            ),
        )
        attempted = 0
        capacity_prunes = 0
        combined: list[DutyIndividual] = []

        def visit(
            position: int,
            selected: dict[str, ScheduledDuty | None],
            occupied: dict[tuple[str, int, int], set[str]],
        ) -> None:
            nonlocal attempted, capacity_prunes
            if position == len(ordered):
                attempted += 1
                duties = []
                for duty in candidate.duties:
                    if duty.physical_vehicle_id not in selected:
                        duties.append(duty)
                        continue
                    schedule = selected[duty.physical_vehicle_id]
                    duties.append(
                        replace(
                            duty,
                            schedule=schedule,
                            charging_sessions=(),
                        )
                    )
                combined.append(
                    replace(candidate, duties=tuple(duties))
                )
                return
            duty, result = ordered[position]
            schedules: tuple[ScheduledDuty | None, ...] = (
                result.frontier if duty.trips else (None,)
            )
            for schedule in schedules:
                copied = {key: set(value) for key, value in occupied.items()}
                feasible = True
                if schedule is not None:
                    for station_id, day, slot, action_vehicle_id in schedule.occupancy_signature:
                        key = (station_id, int(day), int(slot))
                        copied.setdefault(key, set()).add(action_vehicle_id)
                        entry = calendar.get(key)
                        capacity = (
                            entry.capacity
                            if entry is not None
                            else _physical_station_capacity(
                                self.context,
                                station_id,
                            )
                        )
                        if len(copied[key]) > capacity:
                            feasible = False
                            capacity_prunes += 1
                            break
                if not feasible:
                    continue
                selected[duty.physical_vehicle_id] = schedule
                visit(position + 1, selected, copied)
                selected.pop(duty.physical_vehicle_id, None)

        occupied = {
            key: set(entry.occupied_action_vehicle_ids)
            for key, entry in calendar.items()
        }
        visit(0, {}, occupied)
        frontier = _prune_individual_schedules(combined)
        status = OracleStatus.FEASIBLE if frontier else OracleStatus.INFEASIBLE
        result = ScheduleCoordinatorResult(
            status=status,
            frontier=frontier,
            failure_reason=(
                None if frontier else "INFEASIBLE_SHARED_CAPACITY"
            ),
            accounting={
                "schedule_coordinator_combinations_attempted": attempted,
                "schedule_coordinator_capacity_prunes": capacity_prunes,
                "schedule_coordinator_full_candidates": len(combined),
                "changed_duty_count": len(changed),
                "unchanged_capacity_calendar_fingerprint": calendar_sha,
            },
            wall_seconds=perf_counter() - started,
        )
        self._cache[cache_key] = result
        return result


def build_capacity_calendar(
    solution: Solution,
    instance: Instance,
    prices: Any,
    *,
    reserved_charging_actions: Iterable[ChargingAction] = (),
) -> dict[tuple[str, int, int], CapacityCalendarEntry]:
    """Mirror ``check.py:_check_station_capacity`` without touching it."""

    node_lookup = {node.node_id: node for node in instance.nodes}
    customer_count = sum(
        node.node_type.lower() == "c" for node in instance.nodes
    )
    occupied: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    from setp_solver.cost import charging_action_slot_breakdown

    for action in (*solution.charging_actions, *tuple(reserved_charging_actions)):
        node = node_lookup.get(action.station_id)
        if node is None or node.node_type.lower() not in {"d", "f"}:
            continue
        slots = charging_action_slot_breakdown(
            action,
            instance,
            prices,
            n_slots=48,
            cyclic=True,
        )
        station_id = physical_station_id(node)
        for slot in slots:
            occupied[
                (
                    station_id,
                    int(action.charge_day_offset),
                    int(slot.slot_index),
                )
            ].add(action.vehicle_id)
    return {
        key: CapacityCalendarEntry(
            capacity=_station_capacity(node_lookup[key[0]], customer_count),
            occupied_action_vehicle_ids=frozenset(vehicle_ids),
        )
        for key, vehicle_ids in sorted(occupied.items())
    }


def capacity_calendar_fingerprint(
    calendar: Mapping[tuple[str, int, int], CapacityCalendarEntry],
) -> str:
    payload = [
        {
            "key": [station, day, slot],
            "capacity": entry.capacity,
            "occupied": sorted(entry.occupied_action_vehicle_ids),
        }
        for (station, day, slot), entry in sorted(calendar.items())
    ]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _station_capacity(node: Node, customer_count: int) -> int:
    raw = node.station_chargers
    if raw is not None:
        return max(0, int(raw))
    if node.node_type.lower() == "d":
        return max(1, int(customer_count))
    if node.node_type.lower() == "f":
        return 1
    return 0


def _physical_station_capacity(
    context: ScheduleOracleContext,
    station_id: str,
) -> int:
    matches = {
        station.capacity
        for station in context.stations.values()
        if station.physical_station_id == station_id
    }
    if len(matches) != 1:
        raise ValueError(
            f"physical station {station_id!r} has inconsistent capacity identity"
        )
    return next(iter(matches))


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def _optional_price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices.get(name, 0.0))
    return float(getattr(prices, name, 0.0))


def _float_hex_identity(value: Any) -> Any:
    if isinstance(value, float):
        return {"float_hex": value.hex()}
    if isinstance(value, dict):
        return {
            str(key): _float_hex_identity(item)
            for key, item in sorted(value.items(), key=lambda row: str(row[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_float_hex_identity(item) for item in value]
    return value


def _arc_loads(
    node_sequence: Sequence[str],
    nodes: Mapping[str, Node],
) -> tuple[float, ...]:
    loads = [0.0] * (len(node_sequence) - 1)
    remaining = 0.0
    for index in range(len(node_sequence) - 1, 0, -1):
        node = nodes[node_sequence[index]]
        if node.node_type.lower() == "c":
            remaining += float(node.demand)
        loads[index - 1] = remaining
    return tuple(loads)


def _latest_departures(
    node_sequence: Sequence[str],
    travel: Sequence[float],
    nodes: Mapping[str, Node],
) -> tuple[float, ...]:
    latest = [0.0] * len(node_sequence)
    latest[-1] = float(nodes[node_sequence[-1]].due_time)
    for index in range(len(node_sequence) - 2, -1, -1):
        node = nodes[node_sequence[index]]
        latest[index] = min(
            float(node.due_time),
            latest[index + 1]
            - float(travel[index])
            - float(node.service_time),
        )
    return tuple(
        value + float(nodes[node_sequence[index]].service_time)
        for index, value in enumerate(latest)
    )


def _energy_targets(
    curve: PiecewiseChargingCurve,
    *,
    start_soc: float,
    minimum_soc: float,
    future_needs: Sequence[float],
    earliest_start: float,
    latest_end: float,
) -> tuple[float, ...]:
    values = {
        float(start_soc),
        min(curve.capacity_kwh, max(0.0, float(minimum_soc))),
        curve.capacity_kwh,
        *curve.energy_breakpoints_kwh,
    }
    cumulative = 0.0
    for need in future_needs:
        cumulative += max(0.0, float(need))
        values.add(min(curve.capacity_kwh, max(start_soc, cumulative)))
        values.add(
            min(curve.capacity_kwh, max(start_soc, start_soc + cumulative))
        )
    max_duration = max(0.0, float(latest_end) - float(earliest_start))
    origin = curve.cumulative_time_seconds(
        min(curve.capacity_kwh, max(0.0, float(start_soc)))
    )
    first = math.floor(float(earliest_start) / CARBON_SLOT_SECONDS) - 1
    last = math.ceil(float(latest_end) / CARBON_SLOT_SECONDS) + 1
    for slot in range(first, last + 1):
        boundary = float(slot) * CARBON_SLOT_SECONDS
        elapsed = boundary - float(earliest_start)
        if -_TOL <= elapsed <= max_duration + _TOL:
            cumulative_time = min(
                curve.cumulative_seconds[-1],
                max(0.0, origin + max(0.0, elapsed)),
            )
            values.add(curve.inverse_cumulative_time_seconds(cumulative_time))
    return tuple(
        sorted(
            value
            for value in values
            if start_soc - _TOL <= value <= curve.capacity_kwh + _TOL
        )
    )


def _charge_start_events(
    curve: PiecewiseChargingCurve,
    start_soc: float,
    end_soc: float,
    earliest: float,
    latest: float,
) -> tuple[float, ...]:
    duration = curve.duration_seconds(start_soc, end_soc)
    phase_boundaries = {0.0, duration}
    for phase in curve.phases(start_soc, end_soc):
        phase_boundaries.add(float(phase.relative_start_seconds))
        phase_boundaries.add(float(phase.relative_end_seconds))
    values = {float(earliest), float(latest)}
    first = math.floor(float(earliest) / CARBON_SLOT_SECONDS) - 1
    last = math.ceil((float(latest) + duration) / CARBON_SLOT_SECONDS) + 1
    for index in range(first, last + 1):
        boundary = float(index) * CARBON_SLOT_SECONDS
        for phase in phase_boundaries:
            candidate = boundary - phase
            if earliest - _TOL <= candidate <= latest + _TOL:
                values.add(min(float(latest), max(float(earliest), candidate)))
    return tuple(sorted(values))


def _independent_slot_energy_rows(
    curve: PiecewiseChargingCurve,
    *,
    start_energy: float,
    end_energy: float,
    start_second: float,
) -> tuple[tuple[int, float], ...]:
    duration = curve.duration_seconds(start_energy, end_energy)
    if duration <= _TOL:
        return ()
    end_second = float(start_second) + duration
    first = math.floor(float(start_second) / CARBON_SLOT_SECONDS)
    final = math.ceil(end_second / CARBON_SLOT_SECONDS)
    origin = curve.cumulative_time_seconds(start_energy)

    def energy_at(second: float) -> float:
        elapsed = min(duration, max(0.0, second - float(start_second)))
        return curve.inverse_cumulative_time_seconds(origin + elapsed)

    rows = []
    for absolute_slot in range(first, final):
        left = max(float(start_second), absolute_slot * CARBON_SLOT_SECONDS)
        right = min(end_second, (absolute_slot + 1) * CARBON_SLOT_SECONDS)
        if right <= left + 1.0e-12:
            continue
        rows.append((absolute_slot, energy_at(right) - energy_at(left)))
    if abs(sum(energy for _, energy in rows) - (end_energy - start_energy)) > 1.0e-7:
        raise ValueError("precompiled charging slot energy does not close")
    return tuple(rows)


def _charging_soc_points(
    curve: PiecewiseChargingCurve,
    session: ScheduledChargingSession,
    *,
    trip_index: int,
    starting_index: int,
) -> tuple[ScheduledSOCPoint, ...]:
    points = []
    energy = float(session.start_energy_kwh)
    for offset, phase in enumerate(
        curve.phases(
            session.start_energy_kwh,
            session.end_energy_kwh,
        )
    ):
        next_energy = energy + phase.energy_kwh
        points.append(
            ScheduledSOCPoint(
                event_index=starting_index + offset,
                event_kind="CHARGE_PHASE",
                trip_index=trip_index,
                node_id=session.station_id,
                event_second=(
                    float(session.charge_start_second)
                    + float(phase.relative_end_seconds)
                ),
                soc_before_kwh=energy,
                soc_after_kwh=next_energy,
            )
        )
        energy = next_energy
    return tuple(points)


def _session_action(
    session: ScheduledChargingSession,
    duty: PhysicalVehicleDuty,
) -> ChargingAction:
    return ChargingAction(
        vehicle_id=duty.route_id(session.legacy_trip_index),
        station_id=session.station_id,
        energy_kwh=float(session.energy_kwh),
        occupancy_minutes=float(session.occupancy_minutes),
        charge_start_second=float(session.charge_start_second),
        charge_day_offset=int(session.charge_day_offset),
        start_energy_kwh=float(session.start_energy_kwh),
        end_energy_kwh=float(session.end_energy_kwh),
        charging_curve_id=session.charging_curve_id,
    )


def _add_vectors(
    left: ScheduleAccountingVector,
    right: ScheduleAccountingVector,
) -> ScheduleAccountingVector:
    return ScheduleAccountingVector(
        electricity_cost=float(left.electricity_cost)
        + float(right.electricity_cost),
        emissions_kg=float(left.emissions_kg) + float(right.emissions_kg),
        occupancy_cost=float(left.occupancy_cost)
        + float(right.occupancy_cost),
        route_time_cost=float(left.route_time_cost)
        + float(right.route_time_cost),
    )


def _dominates(left: _Label, right: _Label) -> bool:
    if left.progress != right.progress:
        return False
    if float(left.time_second) > float(right.time_second) + _TOL:
        return False
    if (left.soc_kwh is None) != (right.soc_kwh is None):
        return False
    if left.soc_kwh is not None and right.soc_kwh is not None:
        if float(left.soc_kwh) + _TOL < float(right.soc_kwh):
            return False
    left_components = left.accounting.dominance_components
    right_components = right.accounting.dominance_components
    if any(a > b + _TOL for a, b in zip(left_components, right_components)):
        return False
    if not left.occupancy.issubset(right.occupancy):
        return False
    return (
        float(left.time_second) < float(right.time_second) - _TOL
        or (
            left.soc_kwh is not None
            and right.soc_kwh is not None
            and float(left.soc_kwh) > float(right.soc_kwh) + _TOL
        )
        or any(
            a < b - _TOL for a, b in zip(left_components, right_components)
        )
        or left.occupancy < right.occupancy
    )


def _prune_labels(labels: Sequence[_Label], counters: _Counters) -> list[_Label]:
    # Different occupancy signatures are deliberately incomparable here.
    # The approved rule would also allow a strict-subset signature to dominate,
    # but declining that optional prune is conservative and avoids a quadratic
    # all-signature scan without deleting any globally combinable schedule.
    groups: dict[
        tuple[int, frozenset[tuple[str, int, int, str]]],
        list[_Label],
    ] = defaultdict(list)
    for label in labels:
        groups[(label.progress, label.occupancy)].append(label)
    kept: list[_Label] = []
    for group_key in sorted(
        groups,
        key=lambda item: (item[0], tuple(sorted(item[1]))),
    ):
        ordered = sorted(
            groups[group_key],
            key=lambda item: (
                float(item.time_second),
                -(float(item.soc_kwh) if item.soc_kwh is not None else 0.0),
                item.accounting.dominance_components,
            ),
        )
        local: list[_Label] = []
        for candidate in ordered:
            if any(_dominates(other, candidate) for other in local):
                counters.labels_pruned += 1
                continue
            survivors = [
                other for other in local if not _dominates(candidate, other)
            ]
            counters.labels_pruned += len(local) - len(survivors)
            survivors.append(candidate)
            local = survivors
        kept.extend(local)
    return kept


def _prune_route_states(states, counters: _Counters):
    labels = [
        _Label(
            progress=0,
            time_second=row[0],
            soc_kwh=row[1],
            accounting=row[2],
            occupancy=row[3],
            soc_points=row[4],
            charging_sessions=row[5],
        )
        for row in states
    ]
    pruned = _prune_labels(labels, counters)
    return [
        (
            item.time_second,
            item.soc_kwh,
            item.accounting,
            item.occupancy,
            item.soc_points,
            item.charging_sessions,
        )
        for item in pruned
    ]


def _prune_charge_options(options, counters: _Counters):
    labels = [
        _Label(
            progress=0,
            time_second=row[0],
            soc_kwh=row[1],
            accounting=row[3],
            occupancy=row[4],
            soc_points=row[5],
            charging_sessions=(() if row[2] is None else (row[2],)),
        )
        for row in options
    ]
    pruned = _prune_labels(labels, counters)
    out = []
    for item in pruned:
        session = item.charging_sessions[0] if item.charging_sessions else None
        out.append(
            (
                item.time_second,
                item.soc_kwh,
                session,
                item.accounting,
                item.occupancy,
                item.soc_points,
            )
        )
    return out


def _prune_schedules(
    schedules: Sequence[ScheduledDuty],
    counters: _Counters,
) -> list[ScheduledDuty]:
    labels = [
        _Label(
            progress=len(schedule.trip_witnesses),
            time_second=(
                schedule.trip_witnesses[-1].return_second
                if schedule.trip_witnesses
                else 0.0
            ),
            soc_kwh=(
                schedule.trip_witnesses[-1].end_soc_kwh
                if schedule.trip_witnesses
                else None
            ),
            accounting=schedule.local_accounting_vector,
            occupancy=frozenset(schedule.occupancy_signature),
        )
        for schedule in schedules
    ]
    kept = _prune_labels(labels, counters)
    kept_keys = {
        (
            item.time_second,
            item.soc_kwh,
            item.accounting,
            item.occupancy,
        )
        for item in kept
    }
    return [
        schedule
        for schedule, label in zip(schedules, labels, strict=True)
        if (
            label.time_second,
            label.soc_kwh,
            label.accounting,
            label.occupancy,
        )
        in kept_keys
    ]


def _prune_individual_schedules(
    individuals: Sequence[DutyIndividual],
) -> tuple[DutyIndividual, ...]:
    rows = []
    for individual in individuals:
        cost = 0.0
        emissions = 0.0
        occupancy = set()
        for duty in individual.duties:
            if duty.schedule is None:
                continue
            vector = duty.schedule.local_accounting_vector
            cost += (
                float(vector.electricity_cost)
                + float(vector.occupancy_cost)
                + float(vector.route_time_cost)
            )
            emissions += float(vector.emissions_kg)
            occupancy.update(duty.schedule.occupancy_signature)
        rows.append((individual, cost, emissions, frozenset(occupancy)))
    groups: dict[frozenset, list[tuple]] = defaultdict(list)
    for row in rows:
        groups[row[3]].append(row)
    kept = []
    for occupancy in sorted(groups, key=lambda item: tuple(sorted(item))):
        local = []
        for row in sorted(groups[occupancy], key=lambda item: (item[1], item[2])):
            if any(
                other[1] <= row[1] + _TOL
                and other[2] <= row[2] + _TOL
                and (
                    other[1] < row[1] - _TOL
                    or other[2] < row[2] - _TOL
                )
                for other in local
            ):
                continue
            local = [
                other
                for other in local
                if not (
                    row[1] <= other[1] + _TOL
                    and row[2] <= other[2] + _TOL
                    and (
                        row[1] < other[1] - _TOL
                        or row[2] < other[2] - _TOL
                    )
                )
            ]
            local.append(row)
        kept.extend(row[0] for row in local)
    return tuple(sorted(kept, key=lambda item: item.fingerprint))


def _accounting_payload(
    counters: _Counters,
    *,
    frontier_size: int,
) -> dict[str, Any]:
    return {
        "schedule_oracle_event_count": counters.event_count,
        "schedule_oracle_labels_generated": counters.labels_generated,
        "schedule_oracle_labels_pruned": counters.labels_pruned,
        "schedule_oracle_slot_pricing_calls": counters.slot_pricing_calls,
        "schedule_oracle_curve_transitions": counters.curve_transitions,
        "schedule_oracle_pricing_mismatches": counters.pricing_mismatches,
        "schedule_oracle_frontier_size": int(frontier_size),
        "schedule_oracle_constraint_rejections": dict(
            sorted(counters.constraint_rejections.items())
        ),
    }
