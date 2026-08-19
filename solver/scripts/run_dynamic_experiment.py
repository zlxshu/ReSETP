#!/usr/bin/env python3
"""Build a paired dynamic-experiment package without changing the event stream.

The production contract has two online arms: rolling re-optimization and the
P38 mechanical policy.  A full-information static result is written only as a
reference.  ``--dry-run`` uses a tiny in-memory problem and never reads a
China81 instance or an existing report directory.

Formal execution is deliberately fail-closed in this file until the P34 A1
stream bundle is connected and the user chooses how an order with no feasible
mechanical candidate is accounted for.  The dry-run exercises the same shared
stream, pairing checks, arm interfaces, evaluator, and output writer.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping, Protocol, Sequence


SCRIPT_PATH = Path(__file__).resolve()
SOLVER_ROOT = SCRIPT_PATH.parents[1]
SRC_ROOT = SOLVER_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from experiment_acceptance import (  # noqa: E402
    RunAcceptance,
    assess_run,
    finalize_five_file_package,
    package_exit_code,
    row_is_accepted,
)

from setp_solver.potential_pool_dynamic import (  # noqa: E402
    QIU_TRIGGER_PROTOCOL,
    TriggerBatch,
    TriggerEvent,
    TriggerProtocol,
    build_trigger_batches,
)


CONTRACT_ID = "MAIN3_PAIRED_DYNAMIC_EXPERIMENT_V1"
ARM_DYNAMIC = "rolling_dynamic"
ARM_MECHANICAL = "mechanical_online_p38"
ARM_STATIC = "full_information_static_reference"
REFERENCE_ROLE = "reference_only_not_fair_comparator"


@dataclass(frozen=True)
class DualShiftTriggerProtocol:
    """MAIN-3b's frozen two-shift trigger contract."""

    policy_id: str = "Q569_4_T30_DUALSHIFT"
    interval_seconds: float = 30.0 * 60.0
    demand_threshold_kg: float = 569.4
    reception_windows: tuple[tuple[float, float], ...] = (
        (8.0 * 60.0 * 60.0, 11.0 * 60.0 * 60.0),
        (13.0 * 60.0 * 60.0, 19.0 * 60.0 * 60.0),
    )
    source: str = (
        "MAIN-3b frozen calibration: k=2.0 times the reused ten-order "
        "mean demand 284.7 kg; 30-minute maximum wait; two legal shifts"
    )


Q569_4_T30_DUALSHIFT = DualShiftTriggerProtocol()

RAW_RUN_FIELDS = (
    "instance_id",
    "seed",
    "arm",
    "role",
    "run_status",
    "event_stream_sha256",
    "evaluator_identity",
    "wall_clock_budget_seconds_per_decision",
    "scheduled_decision_count",
    "actual_wall_clock_seconds",
    "total_cost",
    "total_emissions_kg",
    "full_evaluation_feasible",
    "customers_served",
    "customers_total",
    "demand_served_kg",
    "demand_total_kg",
    "enabled_vehicles",
    "unserved_customer_ids",
    "outsourced_customer_ids",
    "eligible_for_dynamic_benefit",
    "defer_triggered",
    "defer_count",
    "cross_depot_served_count",
    "cross_depot_served_ratio",
    "fairness_status",
    "ev_route_count",
    "cv_route_count",
    "charging_action_count",
    "acceptance_passed",
    "acceptance_verdict",
    "acceptance_failure_reasons",
)

EVENT_LOG_FIELDS = (
    "instance_id",
    "seed",
    "arm",
    "batch_index",
    "trigger_second",
    "trigger_cause",
    "event_ids",
    "customer_ids",
    "visible_customer_ids",
    "information_sha256",
    "event_stream_sha256",
    "allowed_wall_clock_seconds",
    "actual_wall_clock_seconds",
    "decision_status",
    "decision_detail",
    "total_cost",
    "total_emissions_kg",
    "customers_served",
    "customers_revealed",
    "demand_served_kg",
    "demand_revealed_kg",
    "unserved_customer_ids",
    "outsourced_customer_ids",
    "cumulative_total_cost_cny",
    "cumulative_emissions_kg",
    "cumulative_customers_served",
    "cumulative_demand_served_kg",
    "two_arm_pairing_benefit_cny",
    "two_arm_pairing_reportable",
    "defer_triggered",
    "defer_count",
    "defer_customer_ids",
    "fallback_diagnostics_json",
    "cross_depot_served_count",
    "cross_depot_served_ratio",
    "cross_depot_cases_json",
    "enterprise_profit_json",
    "participation_margin_json",
    "fairness_status",
    "ev_route_count",
    "cv_route_count",
    "charging_action_count",
    "charging_times_json",
    "charging_emissions_kg",
    "committed_history_sha256",
    "committed_history_preserved",
)

FLEET_USAGE_FIELDS = (
    "instance_id",
    "seed",
    "arm",
    "batch_index",
    "vehicle_id",
    "vehicle_type",
    "home_depot_id",
    "status",
    "trip_count",
    "assigned_customer_count",
    "assigned_demand_kg",
    "remaining_capacity_kg",
    "departure_second",
    "return_second",
    "soc_kwh",
    "soc_fraction",
)

PAIRED_RESULT_FIELDS = (
    "instance_id",
    "seed",
    "event_stream_sha256",
    "mechanical_realized_cost",
    "dynamic_realized_cost",
    "dynamic_benefit_cny",
    "mechanical_emissions_kg",
    "dynamic_emissions_kg",
    "emissions_difference_kg",
    "same_customers_served",
    "same_demand_served",
    "benefit_is_reportable",
    "static_reference_cost",
    "static_reference_role",
    "information_sha256_by_batch",
    "defer_triggered_dynamic",
    "defer_triggered_mechanical",
    "defer_count_dynamic",
    "defer_count_mechanical",
)


class PendingUserDecisionError(RuntimeError):
    """Raised before a formal run when its accounting rule is unresolved."""


@dataclass(frozen=True)
class ExperimentOrder:
    event_id: str
    customer_id: str
    appearance_second: float
    demand_kg: float
    x: float
    y: float
    initially_visible: bool = False


@dataclass(frozen=True)
class SharedEventStream:
    policy_id: str
    events: tuple[ExperimentOrder, ...]
    batches: tuple[TriggerBatch, ...]
    sha256: str


@dataclass(frozen=True)
class ToyVehicle:
    vehicle_id: str
    capacity_kg: float
    fixed_cost: float
    distance_cost_per_unit: float
    emissions_kg_per_unit: float
    max_trips: int = 2
    vehicle_type: str = "CV"
    home_depot_id: str = "D"


@dataclass(frozen=True)
class ToyProblem:
    instance_id: str
    vehicles: tuple[ToyVehicle, ...]
    initial_orders: tuple[ExperimentOrder, ...]
    dynamic_orders: tuple[ExperimentOrder, ...]

    @property
    def orders(self) -> tuple[ExperimentOrder, ...]:
        return self.initial_orders + self.dynamic_orders

    @property
    def order_by_id(self) -> Mapping[str, ExperimentOrder]:
        return {order.customer_id: order for order in self.orders}


@dataclass(frozen=True)
class ToyState:
    """Trips are stored as ``(vehicle_id, ((customer_id, ...), ...))``."""

    trips_by_vehicle: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]
    unserved_customer_ids: tuple[str, ...] = ()
    outsourced_customer_ids: tuple[str, ...] = ()

    def trips(self, vehicle_id: str) -> tuple[tuple[str, ...], ...]:
        return dict(self.trips_by_vehicle).get(vehicle_id, ())


@dataclass(frozen=True)
class Evaluation:
    total_cost: float
    total_emissions_kg: float
    customers_served: int
    demand_served_kg: float
    enabled_vehicles: int
    full_evaluation_feasible: bool = True
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MechanicalStep:
    state: ToyState
    candidate_class: str
    detail: str


@dataclass(frozen=True)
class ArmOutcome:
    arm: str
    state: ToyState
    evaluation: Evaluation
    actual_wall_clock_seconds: float
    event_rows: tuple[dict[str, Any], ...]
    fleet_rows: tuple[dict[str, Any], ...]
    run_status: str


class ExperimentBackend(Protocol):
    """Production and dry-run backends must obey this common arm contract."""

    evaluator_identity: str

    def initial_plan(self, problem: Any, deadline_seconds: float) -> Any: ...

    def rolling_reoptimize(
        self,
        problem: Any,
        current: Any,
        visible_customer_ids: Sequence[str],
        deadline_seconds: float,
    ) -> tuple[Any, str]: ...

    def mechanical_dispatch(
        self,
        problem: Any,
        current: Any,
        newly_revealed_customer_ids: Sequence[str],
        deadline_seconds: float,
    ) -> tuple[Any, str]: ...

    def full_information_static(
        self,
        problem: Any,
        all_customer_ids: Sequence[str],
        deadline_seconds: float,
    ) -> Any: ...

    def evaluate(self, problem: Any, state: Any) -> Evaluation: ...

    def fleet_snapshot(self, problem: Any, state: Any) -> list[dict[str, Any]]: ...


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def construct_shared_event_stream(
    events: Sequence[ExperimentOrder],
    protocol: TriggerProtocol | DualShiftTriggerProtocol = QIU_TRIGGER_PROTOCOL,
) -> SharedEventStream:
    """Build one immutable trigger stream for reuse by every online arm.

    The default branch intentionally calls the old builder with the old
    protocol object.  The new dual-shift contract is the only branch that
    partitions the input into two legal reception windows.
    """

    dynamic_events = tuple(order for order in events if not order.initially_visible)
    trigger_events = tuple(
        TriggerEvent(
            event_id=order.event_id,
            customer_id=order.customer_id,
            appearance_second=float(order.appearance_second),
            demand_kg=float(order.demand_kg),
        )
        for order in dynamic_events
    )
    batches = _build_protocol_batches(trigger_events, protocol)
    payload = {
        "policy_id": protocol.policy_id,
        "protocol": _protocol_payload(protocol),
        "events": [asdict(order) for order in dynamic_events],
        "batches": [asdict(batch) for batch in batches],
    }
    return SharedEventStream(
        policy_id=protocol.policy_id,
        events=dynamic_events,
        batches=batches,
        sha256=_canonical_sha256(payload),
    )


def _protocol_payload(
    protocol: TriggerProtocol | DualShiftTriggerProtocol,
) -> dict[str, Any]:
    return asdict(protocol)


def _build_protocol_batches(
    events: Sequence[TriggerEvent],
    protocol: TriggerProtocol | DualShiftTriggerProtocol,
) -> tuple[TriggerBatch, ...]:
    if protocol is QIU_TRIGGER_PROTOCOL or isinstance(protocol, TriggerProtocol):
        return build_trigger_batches(events, protocol)
    if not isinstance(protocol, DualShiftTriggerProtocol):
        raise TypeError(f"unsupported trigger protocol: {type(protocol).__name__}")

    batches: list[TriggerBatch] = []
    for window_start, window_end in protocol.reception_windows:
        window_events = [
            event
            for event in events
            if float(window_start)
            <= float(event.appearance_second)
            < float(window_end)
        ]
        outside = [
            event
            for event in events
            if not (
                float(window_start)
                <= float(event.appearance_second)
                < float(window_end)
            )
        ]
        # An event in the lunch interval is not silently moved to either
        # shift.  It is an invalid input for this contract.
        if outside and any(
            float(window_start) <= float(event.appearance_second) < float(window_end)
            for event in outside
        ):
            raise ValueError("dual-shift trigger event falls outside its window")
        if not window_events:
            continue
        local_protocol = TriggerProtocol(
            policy_id=protocol.policy_id,
            interval_seconds=protocol.interval_seconds,
            demand_threshold_kg=protocol.demand_threshold_kg,
            reception_start_second=window_start,
            reception_end_second=window_end,
            source=protocol.source,
        )
        batches.extend(build_trigger_batches(window_events, local_protocol))

    consumed = {
        event_id
        for batch in batches
        for event_id in batch.event_ids
    }
    expected = {event.event_id for event in events}
    if consumed != expected:
        missing = sorted(expected.difference(consumed))
        raise ValueError(
            "dual-shift trigger event falls in the lunch interval or outside "
            f"the registered windows: {missing}"
        )
    return tuple(
        TriggerBatch(
            policy_id=protocol.policy_id,
            batch_index=index,
            trigger_second=batch.trigger_second,
            cause=batch.cause,
            event_ids=batch.event_ids,
            customer_ids=batch.customer_ids,
            demand_kg=batch.demand_kg,
        )
        for index, batch in enumerate(
            sorted(batches, key=lambda item: (item.trigger_second, item.batch_index)),
            start=1,
        )
    )


def _state_from_mapping(
    mapping: Mapping[str, Sequence[Sequence[str]]],
    *,
    unserved: Sequence[str] = (),
    outsourced: Sequence[str] = (),
) -> ToyState:
    return ToyState(
        trips_by_vehicle=tuple(
            (vehicle_id, tuple(tuple(trip) for trip in trips))
            for vehicle_id, trips in sorted(mapping.items())
        ),
        unserved_customer_ids=tuple(sorted(unserved)),
        outsourced_customer_ids=tuple(sorted(outsourced)),
    )


class ToyBackend:
    """Exact tiny backend used only by tests and ``--dry-run``."""

    evaluator_identity = "synthetic_euclidean_evaluator_v1"

    def initial_plan(self, problem: ToyProblem, deadline_seconds: float) -> ToyState:
        del deadline_seconds
        return self._global_optimum(
            problem,
            [order.customer_id for order in problem.initial_orders],
        )

    def rolling_reoptimize(
        self,
        problem: ToyProblem,
        current: ToyState,
        visible_customer_ids: Sequence[str],
        deadline_seconds: float,
    ) -> tuple[ToyState, str]:
        del current, deadline_seconds
        return (
            self._global_optimum(problem, visible_customer_ids),
            "global_reoptimization_over_visible_orders",
        )

    def mechanical_dispatch(
        self,
        problem: ToyProblem,
        current: ToyState,
        newly_revealed_customer_ids: Sequence[str],
        deadline_seconds: float,
    ) -> tuple[ToyState, str]:
        del deadline_seconds
        state = current
        decisions: list[str] = []
        for customer_id in newly_revealed_customer_ids:
            step = self.mechanical_insert_one(problem, state, customer_id)
            state = step.state
            decisions.append(f"{customer_id}:{step.candidate_class}")
        return state, ";".join(decisions)

    def full_information_static(
        self,
        problem: ToyProblem,
        all_customer_ids: Sequence[str],
        deadline_seconds: float,
    ) -> ToyState:
        del deadline_seconds
        return self._global_optimum(problem, all_customer_ids)

    def evaluate(self, problem: ToyProblem, state: ToyState) -> Evaluation:
        orders = problem.order_by_id
        vehicles = {vehicle.vehicle_id: vehicle for vehicle in problem.vehicles}
        total_cost = 0.0
        emissions = 0.0
        served: set[str] = set()
        enabled = 0
        for vehicle_id, trips in state.trips_by_vehicle:
            if not trips:
                continue
            vehicle = vehicles[vehicle_id]
            enabled += 1
            total_cost += vehicle.fixed_cost
            for trip in trips:
                trip_distance = self._route_distance(problem, trip)
                total_cost += trip_distance * vehicle.distance_cost_per_unit
                emissions += trip_distance * vehicle.emissions_kg_per_unit
                served.update(trip)
        return Evaluation(
            total_cost=total_cost,
            total_emissions_kg=emissions,
            customers_served=len(served),
            demand_served_kg=sum(orders[item].demand_kg for item in served),
            enabled_vehicles=enabled,
            full_evaluation_feasible=True,
        )

    def fleet_snapshot(
        self,
        problem: ToyProblem,
        state: ToyState,
    ) -> list[dict[str, Any]]:
        orders = problem.order_by_id
        rows: list[dict[str, Any]] = []
        for vehicle in problem.vehicles:
            trips = state.trips(vehicle.vehicle_id)
            assigned = [customer for trip in trips for customer in trip]
            assigned_demand = sum(orders[item].demand_kg for item in assigned)
            rows.append(
                {
                    "vehicle_id": vehicle.vehicle_id,
                    "vehicle_type": vehicle.vehicle_type,
                    "home_depot_id": vehicle.home_depot_id,
                    "status": "used" if trips else "idle",
                    "trip_count": len(trips),
                    "assigned_customer_count": len(assigned),
                    "assigned_demand_kg": assigned_demand,
                    "remaining_capacity_kg": sum(
                        vehicle.capacity_kg
                        - sum(orders[item].demand_kg for item in trip)
                        for trip in trips
                    ),
                    "departure_second": "",
                    "return_second": "",
                    "soc_kwh": "",
                    "soc_fraction": "",
                }
            )
        return rows

    def mechanical_insert_one(
        self,
        problem: ToyProblem,
        state: ToyState,
        customer_id: str,
    ) -> MechanicalStep:
        """Apply P38's strict three-class priority on the tiny problem."""

        orders = problem.order_by_id
        vehicles = {vehicle.vehicle_id: vehicle for vehicle in problem.vehicles}
        if customer_id not in orders:
            raise KeyError(customer_id)
        if any(
            customer_id in trip
            for _, trips in state.trips_by_vehicle
            for trip in trips
        ):
            raise ValueError(f"customer already served: {customer_id}")

        existing: list[tuple[float, str, ToyState]] = []
        mapping = {
            vehicle_id: [list(trip) for trip in trips]
            for vehicle_id, trips in state.trips_by_vehicle
        }
        base = self.evaluate(problem, state).total_cost
        for vehicle_id, trips in sorted(mapping.items()):
            vehicle = vehicles[vehicle_id]
            for trip_index, trip in enumerate(trips):
                load = sum(orders[item].demand_kg for item in trip)
                if load + orders[customer_id].demand_kg > vehicle.capacity_kg:
                    continue
                for position in range(len(trip) + 1):
                    candidate_mapping = {
                        key: [list(item) for item in value]
                        for key, value in mapping.items()
                    }
                    candidate_mapping[vehicle_id][trip_index].insert(
                        position, customer_id
                    )
                    candidate = _state_from_mapping(candidate_mapping)
                    increment = self.evaluate(problem, candidate).total_cost - base
                    existing.append(
                        (increment, f"{vehicle_id}:{trip_index}:{position}", candidate)
                    )
        if existing:
            selected = min(existing, key=lambda item: (item[0], item[1]))
            return MechanicalStep(
                selected[2], "1_existing_planned_trip", selected[1]
            )

        appended: list[tuple[float, str, ToyState]] = []
        for vehicle_id, trips in sorted(mapping.items()):
            vehicle = vehicles[vehicle_id]
            if not trips or len(trips) >= vehicle.max_trips:
                continue
            if orders[customer_id].demand_kg > vehicle.capacity_kg:
                continue
            candidate_mapping = {
                key: [list(item) for item in value]
                for key, value in mapping.items()
            }
            candidate_mapping[vehicle_id].append([customer_id])
            candidate = _state_from_mapping(candidate_mapping)
            increment = self.evaluate(problem, candidate).total_cost - base
            appended.append((increment, vehicle_id, candidate))
        if appended:
            selected = min(appended, key=lambda item: (item[0], item[1]))
            return MechanicalStep(
                selected[2], "2_append_used_vehicle_trip", selected[1]
            )

        idle: list[tuple[float, str, ToyState]] = []
        for vehicle in problem.vehicles:
            if mapping.get(vehicle.vehicle_id):
                continue
            if orders[customer_id].demand_kg > vehicle.capacity_kg:
                continue
            candidate_mapping = {
                key: [list(item) for item in value]
                for key, value in mapping.items()
            }
            candidate_mapping[vehicle.vehicle_id] = [[customer_id]]
            candidate = _state_from_mapping(candidate_mapping)
            increment = self.evaluate(problem, candidate).total_cost - base
            idle.append((increment, vehicle.vehicle_id, candidate))
        if idle:
            selected = min(idle, key=lambda item: (item[0], item[1]))
            return MechanicalStep(
                selected[2], "3_dispatch_unused_vehicle", selected[1]
            )

        return MechanicalStep(
            _state_from_mapping(
                mapping,
                unserved=state.unserved_customer_ids + (customer_id,),
            ),
            "no_feasible_candidate",
            customer_id,
        )

    def _global_optimum(
        self,
        problem: ToyProblem,
        customer_ids: Sequence[str],
    ) -> ToyState:
        customer_ids = tuple(customer_ids)
        if not customer_ids:
            return _state_from_mapping({})
        orders = problem.order_by_id
        slots = tuple(
            (vehicle.vehicle_id, trip_index)
            for vehicle in problem.vehicles
            for trip_index in range(vehicle.max_trips)
        )
        best: tuple[float, str, ToyState] | None = None
        vehicles = {vehicle.vehicle_id: vehicle for vehicle in problem.vehicles}
        for assignment in itertools.product(slots, repeat=len(customer_ids)):
            grouped: dict[tuple[str, int], list[str]] = {}
            for customer_id, slot in zip(customer_ids, assignment, strict=True):
                grouped.setdefault(slot, []).append(customer_id)
            if any(
                sum(orders[item].demand_kg for item in group)
                > vehicles[slot[0]].capacity_kg
                for slot, group in grouped.items()
            ):
                continue
            nonempty_indices: dict[str, set[int]] = {}
            for vehicle_id, trip_index in grouped:
                nonempty_indices.setdefault(vehicle_id, set()).add(trip_index)
            if any(
                indices != set(range(max(indices) + 1))
                for indices in nonempty_indices.values()
            ):
                continue
            trip_keys = sorted(grouped)
            permutations = [tuple(itertools.permutations(grouped[key])) for key in trip_keys]
            for selected_orders in itertools.product(*permutations):
                mapping: dict[str, list[list[str]]] = {}
                for (vehicle_id, _), trip in zip(
                    trip_keys, selected_orders, strict=True
                ):
                    mapping.setdefault(vehicle_id, []).append(list(trip))
                state = _state_from_mapping(mapping)
                evaluation = self.evaluate(problem, state)
                fingerprint = json.dumps(
                    state.trips_by_vehicle,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                candidate = (evaluation.total_cost, fingerprint, state)
                if best is None or candidate[:2] < best[:2]:
                    best = candidate
        if best is None:
            raise RuntimeError("tiny global optimizer found no feasible plan")
        return best[2]

    @staticmethod
    def _route_distance(
        problem: ToyProblem,
        trip: Sequence[str],
    ) -> float:
        orders = problem.order_by_id
        points = [(0.0, 0.0)] + [
            (orders[item].x, orders[item].y) for item in trip
        ] + [(0.0, 0.0)]
        return sum(
            math.hypot(right[0] - left[0], right[1] - left[1])
            for left, right in zip(points, points[1:])
        )


def _visible_information_hash(
    problem: ToyProblem,
    visible_customer_ids: Sequence[str],
    stream_sha256: str,
) -> str:
    lookup = problem.order_by_id
    return _canonical_sha256(
        {
            "stream_sha256": stream_sha256,
            "visible_orders": [
                asdict(lookup[customer_id]) for customer_id in visible_customer_ids
            ],
        }
    )


def _join(values: Iterable[str]) -> str:
    return "|".join(str(value) for value in values)


_DETAIL_EVENT_KEYS = (
    "cumulative_total_cost_cny",
    "cumulative_emissions_kg",
    "cumulative_customers_served",
    "cumulative_demand_served_kg",
    "defer_triggered",
    "defer_count",
    "defer_customer_ids",
    "fallback_diagnostics_json",
    "cross_depot_served_count",
    "cross_depot_served_ratio",
    "cross_depot_cases_json",
    "enterprise_profit_json",
    "participation_margin_json",
    "fairness_status",
    "ev_route_count",
    "cv_route_count",
    "charging_action_count",
    "charging_times_json",
    "charging_emissions_kg",
    "committed_history_sha256",
    "committed_history_preserved",
)


def _event_detail_fields(details: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: details.get(key, "")
        for key in _DETAIL_EVENT_KEYS
    } | {
        "two_arm_pairing_benefit_cny": "",
        "two_arm_pairing_reportable": "",
    }


def _run_online_arm(
    *,
    problem: ToyProblem,
    seed: int,
    arm: str,
    initial_state: ToyState,
    shared_stream: SharedEventStream,
    backend: ExperimentBackend,
    wall_clock_seconds: float,
) -> ArmOutcome:
    state = initial_state
    visible = [order.customer_id for order in problem.initial_orders]
    event_rows: list[dict[str, Any]] = []
    fleet_rows: list[dict[str, Any]] = []
    total_elapsed = 0.0
    status = "completed"
    lookup = problem.order_by_id
    for batch in shared_stream.batches:
        batch_customer_ids = list(batch.customer_ids)
        visible.extend(batch_customer_ids)
        started = perf_counter()
        if arm == ARM_DYNAMIC:
            state, detail = backend.rolling_reoptimize(
                problem, state, visible, wall_clock_seconds
            )
        elif arm == ARM_MECHANICAL:
            state, detail = backend.mechanical_dispatch(
                problem, state, batch_customer_ids, wall_clock_seconds
            )
        else:
            raise ValueError(f"unknown online arm: {arm}")
        elapsed = perf_counter() - started
        total_elapsed += elapsed
        evaluation = backend.evaluate(problem, state)
        revealed_demand = sum(lookup[item].demand_kg for item in visible)
        unserved = tuple(getattr(state, "unserved_customer_ids", ()))
        outsourced = tuple(getattr(state, "outsourced_customer_ids", ()))
        if unserved:
            status = "infeasible_candidate_policy_required"
        information_sha256 = _visible_information_hash(
            problem, visible, shared_stream.sha256
        )
        event_rows.append(
            {
                "instance_id": problem.instance_id,
                "seed": seed,
                "arm": arm,
                "batch_index": batch.batch_index,
                "trigger_second": batch.trigger_second,
                "trigger_cause": batch.cause,
                "event_ids": _join(batch.event_ids),
                "customer_ids": _join(batch.customer_ids),
                "visible_customer_ids": _join(visible),
                "information_sha256": information_sha256,
                "event_stream_sha256": shared_stream.sha256,
                "allowed_wall_clock_seconds": wall_clock_seconds,
                "actual_wall_clock_seconds": elapsed,
                "decision_status": status,
                "decision_detail": detail,
                "total_cost": evaluation.total_cost,
                "total_emissions_kg": evaluation.total_emissions_kg,
                "customers_served": evaluation.customers_served,
                "customers_revealed": len(visible),
                "demand_served_kg": evaluation.demand_served_kg,
                "demand_revealed_kg": revealed_demand,
                "unserved_customer_ids": _join(unserved),
                "outsourced_customer_ids": _join(outsourced),
                **_event_detail_fields(evaluation.details),
            }
        )
        for fleet_row in backend.fleet_snapshot(problem, state):
            fleet_rows.append(
                {
                    "instance_id": problem.instance_id,
                    "seed": seed,
                    "arm": arm,
                    "batch_index": batch.batch_index,
                    **fleet_row,
                }
            )
    return ArmOutcome(
        arm=arm,
        state=state,
        evaluation=backend.evaluate(problem, state),
        actual_wall_clock_seconds=total_elapsed,
        event_rows=tuple(event_rows),
        fleet_rows=tuple(fleet_rows),
        run_status=status,
    )


def _raw_row(
    *,
    problem: ToyProblem,
    seed: int,
    outcome: ArmOutcome,
    shared_stream: SharedEventStream,
    backend: ExperimentBackend,
    wall_clock_seconds: float,
    role: str,
) -> dict[str, Any]:
    all_orders = problem.orders
    unserved = tuple(getattr(outcome.state, "unserved_customer_ids", ()))
    outsourced = tuple(getattr(outcome.state, "outsourced_customer_ids", ()))
    return {
        "instance_id": problem.instance_id,
        "seed": seed,
        "arm": outcome.arm,
        "role": role,
        "run_status": outcome.run_status,
        "event_stream_sha256": shared_stream.sha256,
        "evaluator_identity": backend.evaluator_identity,
        "wall_clock_budget_seconds_per_decision": wall_clock_seconds,
        "scheduled_decision_count": len(shared_stream.batches),
        "actual_wall_clock_seconds": outcome.actual_wall_clock_seconds,
        "total_cost": outcome.evaluation.total_cost,
        "total_emissions_kg": outcome.evaluation.total_emissions_kg,
        "full_evaluation_feasible": outcome.evaluation.full_evaluation_feasible,
        "customers_served": outcome.evaluation.customers_served,
        "customers_total": len(all_orders),
        "demand_served_kg": outcome.evaluation.demand_served_kg,
        "demand_total_kg": sum(order.demand_kg for order in all_orders),
        "enabled_vehicles": outcome.evaluation.enabled_vehicles,
        "unserved_customer_ids": _join(unserved),
        "outsourced_customer_ids": _join(outsourced),
        "eligible_for_dynamic_benefit": (
            outcome.arm in (ARM_DYNAMIC, ARM_MECHANICAL)
            and outcome.run_status == "completed"
        ),
        "defer_triggered": outcome.evaluation.details.get(
            "defer_triggered", ""
        ),
        "defer_count": outcome.evaluation.details.get("defer_count", ""),
        "cross_depot_served_count": outcome.evaluation.details.get(
            "cross_depot_served_count", ""
        ),
        "cross_depot_served_ratio": outcome.evaluation.details.get(
            "cross_depot_served_ratio", ""
        ),
        "fairness_status": outcome.evaluation.details.get(
            "fairness_status", ""
        ),
        "ev_route_count": outcome.evaluation.details.get("ev_route_count", ""),
        "cv_route_count": outcome.evaluation.details.get("cv_route_count", ""),
        "charging_action_count": outcome.evaluation.details.get(
            "charging_action_count", ""
        ),
    }


def _assess_raw_row(row: Mapping[str, Any]) -> RunAcceptance:
    return assess_run(
        termination_ok=row.get("run_status") == "completed",
        feasible_ok=row.get("full_evaluation_feasible") is True,
        customers_complete=(
            row.get("customers_served") is not None
            and row.get("customers_served") == row.get("customers_total")
        ),
        demand_complete=(
            row.get("demand_served_kg") is not None
            and row.get("demand_served_kg") == row.get("demand_total_kg")
        ),
        success_verdict="DYNAMIC_ARM_COMPLETE",
        failure_verdict="DYNAMIC_ARM_FAILED",
    )


def _assess_results(
    results: Mapping[str, Any],
    *,
    audit_ok: bool = True,
    success_verdict: str,
    failure_verdict: str,
) -> RunAcceptance:
    rows = list(results["raw_rows"])
    accepted = [row for row in rows if row_is_accepted(row)]
    return assess_run(
        termination_ok=bool(rows) and len(accepted) == len(rows),
        feasible_ok=all(
            row.get("full_evaluation_feasible") is True for row in rows
        ),
        customers_complete=all(
            row.get("customers_served") == row.get("customers_total")
            for row in rows
        ),
        demand_complete=all(
            row.get("demand_served_kg") == row.get("demand_total_kg")
            for row in rows
        ),
        audit_ok=audit_ok,
        extra_failure_reasons=tuple(
            f"{row.get('instance_id')} seed={row.get('seed')} arm={row.get('arm')}: "
            f"{row.get('acceptance_failure_reasons')}"
            for row in rows
            if not row_is_accepted(row)
        ) + (() if rows else ("no raw run rows were produced",)),
        success_verdict=success_verdict,
        failure_verdict=failure_verdict,
    )


def run_paired_pipeline(
    *,
    problem: ToyProblem,
    seeds: Sequence[int],
    wall_clock_seconds: float,
    backend: ExperimentBackend,
    protocol: TriggerProtocol | DualShiftTriggerProtocol = QIU_TRIGGER_PROTOCOL,
) -> dict[str, Any]:
    """Run both online arms against one immutable stream per seed."""

    raw_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    fleet_rows: list[dict[str, Any]] = []
    paired_rows: list[dict[str, Any]] = []
    stream_payloads: dict[int, dict[str, Any]] = {}
    shared_streams: dict[int, SharedEventStream] = {}
    all_customer_ids = [order.customer_id for order in problem.orders]
    for seed in seeds:
        # A production problem factory supplies the instantiated orders for this
        # seed.  From this point onward the stream is constructed exactly once
        # and the same immutable object is passed to both online arms.
        shared_stream = construct_shared_event_stream(problem.orders, protocol)
        shared_streams[int(seed)] = shared_stream
        stream_payloads[int(seed)] = {
            "contract_id": CONTRACT_ID,
            "instance_id": problem.instance_id,
            "seed": int(seed),
            "event_stream_sha256": shared_stream.sha256,
            "policy_id": shared_stream.policy_id,
            "protocol": _protocol_payload(protocol),
            "events": [asdict(order) for order in shared_stream.events],
            "batches": [asdict(batch) for batch in shared_stream.batches],
        }
        active_backend = backend
        for method_name in ("for_seed", "with_stream"):
            method = getattr(active_backend, method_name, None)
            if method is None:
                continue
            active_backend = (
                method(int(seed))
                if method_name == "for_seed"
                else method(shared_stream)
            )
        initial_state = active_backend.initial_plan(problem, wall_clock_seconds)
        dynamic = _run_online_arm(
            problem=problem,
            seed=int(seed),
            arm=ARM_DYNAMIC,
            initial_state=initial_state,
            shared_stream=shared_stream,
            backend=active_backend,
            wall_clock_seconds=wall_clock_seconds,
        )
        mechanical = _run_online_arm(
            problem=problem,
            seed=int(seed),
            arm=ARM_MECHANICAL,
            initial_state=initial_state,
            shared_stream=shared_stream,
            backend=active_backend,
            wall_clock_seconds=wall_clock_seconds,
        )
        static_started = perf_counter()
        static_state = active_backend.full_information_static(
            problem,
            all_customer_ids,
            wall_clock_seconds * len(shared_stream.batches),
        )
        static_elapsed = perf_counter() - static_started
        static = ArmOutcome(
            arm=ARM_STATIC,
            state=static_state,
            evaluation=active_backend.evaluate(problem, static_state),
            actual_wall_clock_seconds=static_elapsed,
            event_rows=(),
            fleet_rows=(),
            run_status="completed",
        )
        outcome_rows: dict[str, dict[str, Any]] = {}
        for outcome, role in (
            (dynamic, "online_comparator_arm"),
            (mechanical, "online_comparator_arm"),
            (static, REFERENCE_ROLE),
        ):
            raw_row = _raw_row(
                problem=problem,
                seed=int(seed),
                outcome=outcome,
                shared_stream=shared_stream,
                backend=active_backend,
                wall_clock_seconds=wall_clock_seconds,
                role=role,
            )
            raw_row.update(_assess_raw_row(raw_row).row_fields())
            raw_rows.append(raw_row)
            outcome_rows[outcome.arm] = raw_row
            event_rows.extend(outcome.event_rows)
            fleet_rows.extend(outcome.fleet_rows)
        same_customers = (
            mechanical.evaluation.customers_served
            == dynamic.evaluation.customers_served
            == len(problem.orders)
        )
        total_demand = sum(order.demand_kg for order in problem.orders)
        same_demand = (
            mechanical.evaluation.demand_served_kg
            == dynamic.evaluation.demand_served_kg
            == total_demand
        )
        reportable = (
            row_is_accepted(outcome_rows[ARM_MECHANICAL])
            and row_is_accepted(outcome_rows[ARM_DYNAMIC])
            and same_customers
            and same_demand
        )
        paired_rows.append(
            {
                "instance_id": problem.instance_id,
                "seed": int(seed),
                "event_stream_sha256": shared_stream.sha256,
                "mechanical_realized_cost": mechanical.evaluation.total_cost,
                "dynamic_realized_cost": dynamic.evaluation.total_cost,
                "dynamic_benefit_cny": (
                    mechanical.evaluation.total_cost
                    - dynamic.evaluation.total_cost
                    if reportable
                    else ""
                ),
                "mechanical_emissions_kg": (
                    mechanical.evaluation.total_emissions_kg
                ),
                "dynamic_emissions_kg": dynamic.evaluation.total_emissions_kg,
                "emissions_difference_kg": (
                    mechanical.evaluation.total_emissions_kg
                    - dynamic.evaluation.total_emissions_kg
                    if reportable
                    else ""
                ),
                "same_customers_served": same_customers,
                "same_demand_served": same_demand,
                "benefit_is_reportable": reportable,
                "static_reference_cost": static.evaluation.total_cost,
                "static_reference_role": REFERENCE_ROLE,
                "information_sha256_by_batch": _join(
                    row["information_sha256"]
                    for row in dynamic.event_rows
                ),
                "defer_triggered_dynamic": dynamic.evaluation.details.get(
                    "defer_triggered", ""
                ),
                "defer_triggered_mechanical": mechanical.evaluation.details.get(
                    "defer_triggered", ""
                ),
                "defer_count_dynamic": dynamic.evaluation.details.get(
                    "defer_count", ""
                ),
                "defer_count_mechanical": mechanical.evaluation.details.get(
                    "defer_count", ""
                ),
            }
        )
        _attach_pairing_fields(
            dynamic.event_rows,
            mechanical.event_rows,
            final_pair_accepted=reportable,
        )
    return {
        "shared_stream": next(iter(shared_streams.values())),
        "shared_streams": shared_streams,
        "stream_payloads": stream_payloads,
        "raw_rows": raw_rows,
        "event_rows": event_rows,
        "fleet_rows": fleet_rows,
        "paired_rows": paired_rows,
    }


def _attach_pairing_fields(
    dynamic_rows: Sequence[dict[str, Any]],
    mechanical_rows: Sequence[dict[str, Any]],
    *,
    final_pair_accepted: bool,
) -> None:
    mechanical_by_batch = {
        int(row["batch_index"]): row for row in mechanical_rows
    }
    for row in dynamic_rows:
        peer = mechanical_by_batch.get(int(row["batch_index"]))
        if peer is None:
            continue
        same_service = (
            row["customers_served"] == peer["customers_served"]
            and abs(
                float(row["demand_served_kg"])
                - float(peer["demand_served_kg"])
            )
            <= 1.0e-9
        )
        reportable = bool(final_pair_accepted and same_service)
        row["two_arm_pairing_benefit_cny"] = (
            float(peer["total_cost"]) - float(row["total_cost"])
            if reportable
            else ""
        )
        row["two_arm_pairing_reportable"] = reportable
    dynamic_by_batch = {
        int(row["batch_index"]): row for row in dynamic_rows
    }
    for row in mechanical_rows:
        peer = dynamic_by_batch.get(int(row["batch_index"]))
        if peer is None:
            continue
        row["two_arm_pairing_benefit_cny"] = peer[
            "two_arm_pairing_benefit_cny"
        ]
        row["two_arm_pairing_reportable"] = peer[
            "two_arm_pairing_reportable"
        ]


def _write_csv(
    path: Path,
    fields: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_output_package(
    *,
    output_dir: Path,
    results: Mapping[str, Any],
    seeds: Sequence[int],
    wall_clock_seconds: float,
    dry_run: bool,
) -> RunAcceptance:
    output_dir.mkdir(parents=True, exist_ok=False)
    streams_dir = output_dir / "shared_event_streams"
    streams_dir.mkdir()
    _write_csv(output_dir / "raw_runs.csv", RAW_RUN_FIELDS, results["raw_rows"])
    _write_csv(
        output_dir / "per_reveal_events.csv",
        EVENT_LOG_FIELDS,
        results["event_rows"],
    )
    _write_csv(
        output_dir / "fleet_usage.csv",
        FLEET_USAGE_FIELDS,
        results["fleet_rows"],
    )
    _write_csv(
        output_dir / "paired_results.csv",
        PAIRED_RESULT_FIELDS,
        results["paired_rows"],
    )
    for seed, payload in sorted(results["stream_payloads"].items()):
        _write_json(streams_dir / f"seed_{seed}.json", payload)
    acceptance = _assess_results(
        results,
        success_verdict=(
            "DYNAMIC_DRY_RUN_COMPLETE" if dry_run else "DYNAMIC_RUN_COMPLETE"
        ),
        failure_verdict=(
            "DYNAMIC_DRY_RUN_FAILED" if dry_run else "DYNAMIC_RUN_FAILED"
        ),
    )
    report = (
        "# Dynamic experiment package\n\n"
        + (
            "This is a synthetic dry run. It is not formal experiment evidence.\n"
            if dry_run
            else "Formal run package.\n"
        )
    )
    if not acceptance.accepted:
        report += "\nFAILED: " + "; ".join(acceptance.failure_reasons) + "\n"
    finalize_five_file_package(
        output_dir,
        acceptance=acceptance,
        metadata={
            "contract_id": CONTRACT_ID,
            "run_class": "synthetic_dry_run" if dry_run else "formal",
            "seeds": list(seeds),
            "wall_clock_seconds_per_decision": wall_clock_seconds,
            "online_arms": [ARM_DYNAMIC, ARM_MECHANICAL],
            "static_reference": {
                "arm": ARM_STATIC,
                "role": REFERENCE_ROLE,
                "eligible_for_dynamic_benefit": False,
            },
            "event_stream_sha256": results["shared_stream"].sha256,
            "event_stream_sha256_by_seed": {
                str(seed): stream.sha256
                for seed, stream in sorted(results["shared_streams"].items())
            },
            "event_stream_constructed_once_per_seed": True,
            "infeasible_candidate_policy": (
                "not_exercised_by_synthetic_case" if dry_run else None
            ),
            "schemas": {
                "raw_runs.csv": list(RAW_RUN_FIELDS),
                "per_reveal_events.csv": list(EVENT_LOG_FIELDS),
                "fleet_usage.csv": list(FLEET_USAGE_FIELDS),
                "paired_results.csv": list(PAIRED_RESULT_FIELDS),
            },
        },
        decision={
            "status": "DRY_RUN_ONLY" if dry_run else "FORMAL_OUTPUT",
            "dynamic_benefit_formula": (
                "mechanical_realized_cost - dynamic_realized_cost"
            ),
            "static_reference_is_comparator": False,
            "formal_infeasible_candidate_policy": "PENDING_USER_DECISION",
        },
        report_text=report,
        complete_status="DRY_RUN_COMPLETED" if dry_run else "COMPLETED",
        failed_status="DRY_RUN_FAILED" if dry_run else "FAILED",
    )
    return acceptance


def _synthetic_problem() -> ToyProblem:
    start = QIU_TRIGGER_PROTOCOL.reception_start_second
    initial = (
        ExperimentOrder("I1", "I1", start, 1.0, 2.0, 0.0, True),
        ExperimentOrder("I2", "I2", start, 1.0, 0.0, 2.0, True),
    )
    dynamic = (
        ExperimentOrder("E1", "D1", start + 60.0, 1.0, 2.0, 2.0),
        ExperimentOrder("E2", "D2", start + 120.0, 1.0, 1.0, 1.0),
    )
    return ToyProblem(
        instance_id="synthetic-tiny-main3",
        vehicles=(
            ToyVehicle("CV_D_1", 2.0, 3.0, 1.0, 0.1),
            ToyVehicle("CV_D_2", 2.0, 3.0, 1.0, 0.1),
        ),
        initial_orders=initial,
        dynamic_orders=dynamic,
    )


def _write_main3b_package(
    *,
    output_dir: Path,
    results: Mapping[str, Any],
    problem: Any,
    protocol: TriggerProtocol | DualShiftTriggerProtocol,
    seeds: Sequence[int],
    wall_clock_seconds: float,
    repo: Path,
    source_hash_before: str,
    source_hash_after: str,
    protected_before: Mapping[str, str],
    protected_after: Mapping[str, str],
) -> RunAcceptance:
    output_dir.mkdir(parents=True, exist_ok=False)
    streams_dir = output_dir / "shared_event_streams"
    streams_dir.mkdir()
    _write_csv(output_dir / "raw_runs.csv", RAW_RUN_FIELDS, results["raw_rows"])
    _write_csv(
        output_dir / "per_reveal_events.csv",
        EVENT_LOG_FIELDS,
        results["event_rows"],
    )
    _write_csv(
        output_dir / "fleet_usage.csv",
        FLEET_USAGE_FIELDS,
        results["fleet_rows"],
    )
    _write_csv(
        output_dir / "paired_results.csv",
        PAIRED_RESULT_FIELDS,
        results["paired_rows"],
    )
    for seed, payload in sorted(results["stream_payloads"].items()):
        _write_json(streams_dir / f"seed_{seed}.json", payload)

    stream = results["shared_stream"]
    all_information_hashes = sorted(
        {
            row["information_sha256"]
            for row in results["event_rows"]
            if row.get("information_sha256")
        }
    )
    metadata = {
        "contract_id": CONTRACT_ID,
        "run_class": "main3b_small_wiring_trial",
        "instance_id": problem.instance_id,
        "seeds": list(seeds),
        "wall_clock_seconds_per_decision": wall_clock_seconds,
        "infeasible_candidate_policy": "defer",
        "online_arms": [ARM_DYNAMIC, ARM_MECHANICAL],
        "static_reference": {
            "arm": ARM_STATIC,
            "role": REFERENCE_ROLE,
            "eligible_for_dynamic_benefit": False,
        },
        "trigger_protocol": _protocol_payload(protocol),
        "event_stream_sha256": stream.sha256,
        "event_stream_sha256_by_seed": {
            str(seed): item.sha256
            for seed, item in sorted(results["shared_streams"].items())
        },
        "information_sha256_values": all_information_hashes,
        "source_instance_sha256_before": source_hash_before,
        "source_instance_sha256_after": source_hash_after,
        "protected_file_hashes_before": dict(protected_before),
        "protected_file_hashes_after": dict(protected_after),
        "source_stream_directory": str(problem.c8_stream.stream_directory),
        "event_stream_constructed_once_per_seed": True,
        "algorithm_performance_conclusion": False,
        "schemas": {
            "raw_runs.csv": list(RAW_RUN_FIELDS),
            "per_reveal_events.csv": list(EVENT_LOG_FIELDS),
            "fleet_usage.csv": list(FLEET_USAGE_FIELDS),
            "paired_results.csv": list(PAIRED_RESULT_FIELDS),
        },
    }
    acceptance = _assess_results(
        results,
        audit_ok=(
            source_hash_before == source_hash_after
            and dict(protected_before) == dict(protected_after)
        ),
        success_verdict="MAIN3B_DONE",
        failure_verdict="MAIN3B_FAILED",
    )
    decision = {
        "status": acceptance.verdict,
        "infeasible_candidate_policy": "defer",
        "static_reference_is_comparator": False,
        "dynamic_benefit_formula": (
            "mechanical_realized_cost - dynamic_realized_cost"
        ),
        "algorithm_performance_conclusion": "NONE",
        "fairness_in_dynamic_decision": "NOT_WIRED",
    }
    diff = _main3b_git_diff(repo)
    (output_dir / "main3b_incremental_git_diff.patch").write_text(
        diff,
        encoding="utf-8",
    )
    report = _main3b_report(
        results=results,
        problem=problem,
        protocol=protocol,
        source_hash_before=source_hash_before,
        source_hash_after=source_hash_after,
        protected_before=protected_before,
        protected_after=protected_after,
    )
    if not acceptance.accepted:
        report = report.replace("MAIN3B_DONE", "MAIN3B_FAILED", 1)
        report += (
            "\n`HALT` 验收未通过："
            + "; ".join(acceptance.failure_reasons)
            + "\n"
        )
    terminal_payload = {
        "status": acceptance.verdict,
        "instance_id": problem.instance_id,
        "event_stream_sha256": stream.sha256,
        "event_stream_sha256_by_seed": {
            str(seed): item.sha256
            for seed, item in sorted(results["shared_streams"].items())
        },
        "information_sha256_values": all_information_hashes,
        "paired_row_count": len(results["paired_rows"]),
        "per_reveal_row_count": len(results["event_rows"]),
        "static_eligible_for_dynamic_benefit": False,
        "infeasible_candidate_policy": "defer",
        "source_instance_sha256_before": source_hash_before,
        "source_instance_sha256_after": source_hash_after,
        "protected_file_hashes_before": dict(protected_before),
        "protected_file_hashes_after": dict(protected_after),
        "algorithm_performance_conclusion": False,
    }
    terminal_name = "done.json" if acceptance.accepted else "failure.json"
    _write_json(output_dir / terminal_name, terminal_payload)
    finalize_five_file_package(
        output_dir,
        acceptance=acceptance,
        metadata=metadata,
        decision=decision,
        report_text=report,
        complete_status="MAIN3B_DONE",
        failed_status="MAIN3B_FAILED",
    )
    return acceptance


def _write_main3b_halt_package(
    *,
    output_dir: Path,
    error: BaseException,
    repo: Path,
    protocol: TriggerProtocol | DualShiftTriggerProtocol,
    source_hash_before: str,
    source_hash_after: str,
    protected_before: Mapping[str, str],
    protected_after: Mapping[str, str],
) -> RunAcceptance:
    output_dir.mkdir(parents=True, exist_ok=False)
    _write_csv(output_dir / "raw_runs.csv", RAW_RUN_FIELDS, ())
    _write_csv(output_dir / "per_reveal_events.csv", EVENT_LOG_FIELDS, ())
    _write_csv(output_dir / "fleet_usage.csv", FLEET_USAGE_FIELDS, ())
    _write_csv(output_dir / "paired_results.csv", PAIRED_RESULT_FIELDS, ())
    message = f"{type(error).__name__}: {error}"
    acceptance = assess_run(
        termination_ok=False,
        feasible_ok=False,
        customers_complete=False,
        demand_complete=False,
        audit_ok=(
            source_hash_before == source_hash_after
            and dict(protected_before) == dict(protected_after)
        ),
        extra_failure_reasons=(message,),
        success_verdict="MAIN3B_DONE",
        failure_verdict="MAIN3B_HALT",
    )
    (output_dir / "main3b_incremental_git_diff.patch").write_text(
        _main3b_git_diff(repo),
        encoding="utf-8",
    )
    report = (
        "MAIN3B_HALT\n\n"
        f"`HALT` 生产后端接线未完成：{message}\n"
        "`FACT` 当前没有可交付的两臂配对结果；四件套中的结果表已保留为空表。\n"
        "`UNKNOWN` 逐次揭示、三交互和兜底触发情况尚未形成证据。\n"
        "`FACT` 本次没有算法性能结论。\n"
    )
    _write_json(
        output_dir / "failure.json",
        {
            "status": "MAIN3B_HALT",
            "error": message,
            "source_instance_sha256_before": source_hash_before,
            "source_instance_sha256_after": source_hash_after,
            "protected_file_hashes_before": dict(protected_before),
            "protected_file_hashes_after": dict(protected_after),
            "algorithm_performance_conclusion": False,
        },
    )
    finalize_five_file_package(
        output_dir,
        acceptance=acceptance,
        metadata={
            "contract_id": CONTRACT_ID,
            "run_class": "main3b_small_wiring_trial",
            "trigger_protocol": _protocol_payload(protocol),
            "infeasible_candidate_policy": "defer",
            "source_instance_sha256_before": source_hash_before,
            "source_instance_sha256_after": source_hash_after,
            "protected_file_hashes_before": dict(protected_before),
            "protected_file_hashes_after": dict(protected_after),
            "algorithm_performance_conclusion": False,
        },
        decision={
            "status": "MAIN3B_HALT",
            "infeasible_candidate_policy": "defer",
            "halt_reason": message,
            "algorithm_performance_conclusion": "NONE",
        },
        report_text=report,
        complete_status="MAIN3B_DONE",
        failed_status="MAIN3B_HALT",
    )
    return acceptance


def _write_artifact_hashes(output_dir: Path) -> None:
    targets = sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.name != "artifact_hashes.json"
    )
    _write_json(
        output_dir / "artifact_hashes.json",
        {
            str(path.relative_to(output_dir)): _file_sha256(path)
            for path in targets
        },
    )


def _main3b_git_diff(repo: Path) -> str:
    tracked = (
        "solver/scripts/run_dynamic_experiment.py",
        "solver/src/setp_solver/algorithms/problem_hgs/mechanical_baseline.py",
        "solver/src/setp_solver/algorithms/problem_hgs/dynamic_insertion.py",
    )
    new_files = (
        "solver/src/setp_solver/main3b_backend.py",
        "solver/tests/test_main3b_protocol.py",
    )
    chunks: list[str] = []
    tracked_result = subprocess.run(
        ["git", "diff", "--", *tracked],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    chunks.append(tracked_result.stdout)
    for relative in new_files:
        path = repo / relative
        result = subprocess.run(
            ["git", "diff", "--no-index", "--", "/dev/null", str(path)],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
        )
        chunks.append(result.stdout)
    return "\n".join(chunk for chunk in chunks if chunk)


def _main3b_report(
    *,
    results: Mapping[str, Any],
    problem: Any,
    protocol: TriggerProtocol | DualShiftTriggerProtocol,
    source_hash_before: str,
    source_hash_after: str,
    protected_before: Mapping[str, str],
    protected_after: Mapping[str, str],
) -> str:
    rows = results["event_rows"]
    final_rows = {
        arm: max(
            (row for row in rows if row["arm"] == arm),
            key=lambda row: int(row["batch_index"]),
            default=None,
        )
        for arm in (ARM_DYNAMIC, ARM_MECHANICAL)
    }
    dynamic_final = final_rows[ARM_DYNAMIC]
    mechanical_final = final_rows[ARM_MECHANICAL]
    defer_rows = [
        row
        for row in rows
        if str(row.get("defer_triggered", "")).lower() in {"true", "1"}
        or row.get("defer_count") not in ("", None, 0, "0")
    ]
    cross_cases = []
    if dynamic_final is not None:
        try:
            cross_cases = json.loads(dynamic_final["cross_depot_cases_json"])
        except (KeyError, TypeError, json.JSONDecodeError):
            cross_cases = []
    if dynamic_final is None or mechanical_final is None:
        pairing_text = "`UNKNOWN` 两臂没有完整逐批结果。"
    else:
        pairing_text = (
            "`FACT` 最后一批的滚动臂与机械臂累计成本分别为 "
            f"{dynamic_final['total_cost']} 与 {mechanical_final['total_cost']}；"
            f"逐批配对收益见 `per_reveal_events.csv` 的 "
            "`two_arm_pairing_benefit_cny`。"
        )

    if defer_rows:
        fallback_text = (
            f"`FACT` 本算例的 `defer` 触发了 {len(defer_rows)} 条阶段记录；"
            "触发批次、订单和三类候选失败原因保存在 "
            "`fallback_diagnostics_json`。"
        )
    else:
        fallback_text = (
            "`FACT` 本算例未出现无可行候选情形，`defer` 没有触发；"
            "因此没有三类候选失败批次。"
        )

    if cross_cases:
        case = cross_cases[0]
        collaboration_text = (
            f"`FACT` 动态臂最终有 {dynamic_final['cross_depot_served_count']} 个新揭示需求由非原车场吸收，"
            f"占已揭示新需求的比例为 {dynamic_final['cross_depot_served_ratio']}；例如订单 "
            f"{case['customer_id']} 的原车场是 {case['original_depot_id']}，"
            f"实际服务车场是 {case['serving_depot_id']}，车辆为 {case['vehicle_id']}。"
        )
    else:
        collaboration_text = (
            "`FACT` 本场景动态臂没有观测到非原车场吸收的新揭示需求；"
            "动态×协同的可观测数量为 0。"
        )

    fairness_text = (
        "`FACT` 每阶段企业收益和参与边际已写入逐次揭示表的 "
        "`enterprise_profit_json` 与 `participation_margin_json`。"
        " `FACT` 公平约束没有接入动态决策，字段明确标为 "
        "`NOT_WIRED_FAIRNESS_NOT_IN_DYNAMIC_DECISION`。"
    )

    carbon_text = "`UNKNOWN` 动态臂与机械臂的 EV/CV 分工和充电动作无法从逐阶段结果读取。"
    if dynamic_final is not None and mechanical_final is not None:
        if (
            int(dynamic_final.get("charging_action_count", 0) or 0) == 0
            and int(mechanical_final.get("charging_action_count", 0) or 0) == 0
        ):
            carbon_text = (
                "`FACT` 两臂最终阶段均没有充电动作；因此动态重规划是否改变充电时段碳强度在本场景退化，"
                "没有可见的充电交互。EV/CV 路线数仍保存在逐阶段字段中。"
            )
        else:
            stage_rows: dict[str, dict[str, Mapping[str, Any]]] = {}
            for row in rows:
                stage_rows.setdefault(str(row["batch_index"]), {})[
                    str(row["arm"])
                ] = row
            paired_stages = [
                (stage, item[ARM_DYNAMIC], item[ARM_MECHANICAL])
                for stage, item in sorted(
                    stage_rows.items(), key=lambda pair: int(pair[0])
                )
                if ARM_DYNAMIC in item and ARM_MECHANICAL in item
            ]
            route_counts_equal = all(
                (dynamic["ev_route_count"], dynamic["cv_route_count"])
                == (mechanical["ev_route_count"], mechanical["cv_route_count"])
                for _stage, dynamic, mechanical in paired_stages
            )
            route_summary = "; ".join(
                f"第{stage}批 {dynamic['ev_route_count']}/{dynamic['cv_route_count']}"
                for stage, dynamic, _mechanical in paired_stages
            )
            action_diff_batches = [
                stage
                for stage, dynamic, mechanical in paired_stages
                if dynamic["charging_action_count"]
                != mechanical["charging_action_count"]
            ]

            def _charging_start_seconds(row: Mapping[str, Any]) -> tuple[float, ...]:
                try:
                    actions = json.loads(row["charging_times_json"])
                except (KeyError, TypeError, json.JSONDecodeError):
                    return ()
                return tuple(
                    float(action["charge_start_second"])
                    for action in actions
                )

            start_diff_batches = [
                stage
                for stage, dynamic, mechanical in paired_stages
                if _charging_start_seconds(dynamic)
                != _charging_start_seconds(mechanical)
            ]
            division_text = (
                f"EV/CV 分工五批均相同（动态臂各批为 {route_summary}，格式为 EV/CV）；"
                if route_counts_equal
                else "EV/CV 分工在逐阶段表中存在差异；"
            )
            action_text = (
                "充电动作数在第"
                + "/".join(action_diff_batches)
                + "批不同；"
                if action_diff_batches
                else "充电动作数逐批相同；"
            )
            timing_text = (
                "充电开始时刻集合在第"
                + "/".join(start_diff_batches)
                + "批不同；"
                if start_diff_batches
                else "充电开始时刻集合逐批相同；"
            )
            carbon_text = (
                f"`FACT` {division_text}{action_text}{timing_text}"
                "动态臂与机械臂的充电排放也已逐阶段记录。"
                "`UNKNOWN` 当前评价器没有按单次充电动作拆开的时变碳强度字段，"
                "所以不能把排放差异归因于时段碳强度变化；本报告不把这些读数升级为性能结论。"
            )

    paired = results["paired_rows"]
    condition_lines = [
        "1. `FACT` 同事件流、同信息、同评价器、同单次时限的逐批配对字段已保存；"
        "是否出现滚动成本不低于机械臂，按 `paired_results.csv` 核对。",
        "2. `FACT` 客户数和需求量分别保存；若两臂服务量不同，配对收益字段不会被当作可报告收益。",
        "3. `FACT` 本合同没有第三方外包和自拟未服务罚值；若出现 defer，原因写入候选诊断，"
        "不以价格项掩盖。",
        "4. `FACT` 每阶段都有未服务字段和 committed history 哈希；冻结历史失败会直接 HALT。",
        "5. `FACT` 两臂共享同一 `event_stream_sha256` 和逐批 `information_sha256`；"
        "本小试不构造不同信息或不同评价器，因此该否定条件只完成合同核对，未作因果结论。",
    ]
    protected_equal = dict(protected_before) == dict(protected_after)
    source_equal = source_hash_before == source_hash_after
    return "\n".join(
        [
            "MAIN3B_DONE",
            "",
            "`FACT` 本轮完成了既有两臂的生产后端接线；没有新增路由、插入或评价算法。",
            f"`FACT` 触发合同为 `{protocol.policy_id}`，事件流哈希为 `{results['shared_stream'].sha256}`；"
            f"共有 {len(results['shared_stream'].batches)} 个触发批次。",
            "`FACT` 动态臂和机械臂使用同一事件流、同一逐批信息对象、同一 `DutyFullEvaluator` 和同一命令时限；"
            "全信息静态臂仅作参考，`eligible_for_dynamic_benefit=false`。",
            f"`FACT` 统一算例前后内容哈希一致：{source_equal}；"
            f"受保护三文件前后哈希一致：{protected_equal}。",
            "",
            "## 两臂配对收益与逐次揭示",
            "",
            pairing_text,
            "`FACT` 成本、排放、服务客户数、服务需求量和兜底字段已追加到 `per_reveal_events.csv`；"
            "最终汇总在 `paired_results.csv`。",
            "",
            "## 动态×协同",
            "",
            collaboration_text,
            "",
            "## 动态×公平",
            "",
            fairness_text,
            "",
            "## 动态×时变碳",
            "",
            carbon_text,
            "",
            "## 兜底 defer",
            "",
            fallback_text,
            "",
            "## 设计文档第四节的五条事前否定条件",
            "",
            *condition_lines,
            "",
            "`UNKNOWN` 这些小预算接线结果不支持算法性能、成本改善、排放改善或论文主张；"
            "它只证明当前生产链是否贯通，并把失败和交互诊断保存下来。",
            "",
            "交付物：`metadata.json`、`raw_runs.csv`、`per_reveal_events.csv`、"
            "`fleet_usage.csv`、`paired_results.csv`、`decision.json`、`done.json`、"
            "`artifact_hashes.json` 和 `main3b_incremental_git_diff.patch`。",
        ]
    ) + "\n"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance-id")
    parser.add_argument(
        "--dynamic-stream-dir",
        type=Path,
        default=Path(
            "data/dynamic_streams/"
            "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd_q500_t30_17ffb3f5d091"
        ),
    )
    parser.add_argument(
        "--trigger-protocol",
        choices=("qiu", "q569_4_t30_dualshift"),
        help=(
            "Formal runs use Q569_4_T30_DUALSHIFT when omitted; dry-run "
            "keeps the legacy QIU protocol."
        ),
    )
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--wall-clock-seconds", type=float, required=True)
    parser.add_argument(
        "--infeasible-policy",
        choices=("unserved_with_penalty", "third_party_outsourcing", "defer"),
        help="No default: this is pending user decision for formal execution.",
    )
    parser.add_argument("--unserved-penalty-cny", type=float)
    parser.add_argument("--outsourcing-cost-file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not math.isfinite(args.wall_clock_seconds) or args.wall_clock_seconds <= 0:
        parser.error("--wall-clock-seconds must be positive")
    if len(set(args.seeds)) != len(args.seeds):
        parser.error("--seeds must not contain duplicates")
    return args


def _formal_preflight(args: argparse.Namespace) -> None:
    if args.infeasible_policy is None:
        raise PendingUserDecisionError(
            "formal execution blocked: the no-feasible-candidate accounting "
            "policy is PENDING USER DECISION"
        )
    if args.infeasible_policy == "unserved_with_penalty":
        if args.unserved_penalty_cny is None:
            raise PendingUserDecisionError(
                "formal execution blocked: no approved unserved-order penalty"
            )
    if args.infeasible_policy != "defer":
        raise PendingUserDecisionError(
            "MAIN-3b only accepts the user-approved defer policy; no price or "
            "outsourcing rule is available in this contract"
        )
    if args.unserved_penalty_cny is not None or args.outsourcing_cost_file is not None:
        raise PendingUserDecisionError(
            "defer policy must not receive an unserved penalty or outsourcing price"
        )


def _selected_protocol(
    *,
    dry_run: bool,
    requested: str | None,
) -> TriggerProtocol | DualShiftTriggerProtocol:
    if dry_run:
        return QIU_TRIGGER_PROTOCOL if requested in (None, "qiu") else Q569_4_T30_DUALSHIFT
    return (
        QIU_TRIGGER_PROTOCOL
        if requested == "qiu"
        else Q569_4_T30_DUALSHIFT
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.dry_run:
        _formal_preflight(args)
    protocol = _selected_protocol(
        dry_run=bool(args.dry_run),
        requested=args.trigger_protocol,
    )
    if args.dry_run:
        problem = _synthetic_problem()
        results = run_paired_pipeline(
            problem=problem,
            seeds=args.seeds,
            wall_clock_seconds=float(args.wall_clock_seconds),
            backend=ToyBackend(),
            protocol=protocol,
        )
        acceptance = write_output_package(
            output_dir=args.output_dir,
            results=results,
            seeds=args.seeds,
            wall_clock_seconds=float(args.wall_clock_seconds),
            dry_run=True,
        )
        print(
            json.dumps(
                {
                    "status": (
                        "DRY_RUN_COMPLETED"
                        if acceptance.accepted
                        else "DRY_RUN_FAILED"
                    ),
                    "accepted": acceptance.accepted,
                    "output_dir": str(args.output_dir),
                    "event_stream_sha256": results["shared_stream"].sha256,
                    "paired_rows": len(results["paired_rows"]),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return package_exit_code(acceptance)

    from setp_solver.c8_dynamic_stream import (  # noqa: PLC0415
        package_content_sha256,
        package_file_hashes,
    )
    from setp_solver.main3b_backend import (  # noqa: PLC0415
        ProductionBackend,
        ProductionBackendHalt,
        build_production_problem,
    )

    repo = SOLVER_ROOT.parent
    problem = build_production_problem(
        repo,
        (repo / args.dynamic_stream_dir).resolve()
        if not args.dynamic_stream_dir.is_absolute()
        else args.dynamic_stream_dir,
    )
    target_dir = (
        repo
        / "data/ChinaInstances/china81_final_suite_v2_20260815/instances"
        / problem.instance_id
    )
    source_hashes_before = package_file_hashes(target_dir)
    source_hash_before = package_content_sha256(source_hashes_before)
    protected_paths = (
        repo / "solver/src/setp_solver/cost.py",
        repo / "solver/src/setp_solver/check.py",
        repo / "solver/src/setp_solver/search/evaluation.py",
    )
    protected_before = {
        str(path.relative_to(repo)): _file_sha256(path)
        for path in protected_paths
    }
    try:
        results = run_paired_pipeline(
            problem=problem,
            seeds=args.seeds,
            wall_clock_seconds=float(args.wall_clock_seconds),
            backend=ProductionBackend(),
            protocol=protocol,
        )
    except ProductionBackendHalt as error:
        source_hashes_after = package_file_hashes(target_dir)
        protected_after = {
            str(path.relative_to(repo)): _file_sha256(path)
            for path in protected_paths
        }
        acceptance = _write_main3b_halt_package(
            output_dir=args.output_dir,
            error=error,
            repo=repo,
            protocol=protocol,
            source_hash_before=source_hash_before,
            source_hash_after=package_content_sha256(source_hashes_after),
            protected_before=protected_before,
            protected_after=protected_after,
        )
        print(
            json.dumps(
                {
                    "status": "MAIN3B_HALT",
                    "output_dir": str(args.output_dir),
                    "error": f"{type(error).__name__}: {error}",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return package_exit_code(acceptance)
    source_hashes_after = package_file_hashes(target_dir)
    protected_after = {
        str(path.relative_to(repo)): _file_sha256(path)
        for path in protected_paths
    }
    acceptance = _write_main3b_package(
        output_dir=args.output_dir,
        results=results,
        problem=problem,
        protocol=protocol,
        seeds=args.seeds,
        wall_clock_seconds=float(args.wall_clock_seconds),
        repo=repo,
        source_hash_before=source_hash_before,
        source_hash_after=package_content_sha256(source_hashes_after),
        protected_before=protected_before,
        protected_after=protected_after,
    )
    print(
        json.dumps(
            {
                "status": acceptance.verdict,
                "accepted": acceptance.accepted,
                "output_dir": str(args.output_dir),
                "event_stream_sha256": results["shared_stream"].sha256,
                "paired_rows": len(results["paired_rows"]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return package_exit_code(acceptance)


if __name__ == "__main__":
    raise SystemExit(main())
