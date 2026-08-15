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
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping, Protocol, Sequence


SCRIPT_PATH = Path(__file__).resolve()
SOLVER_ROOT = SCRIPT_PATH.parents[1]
SRC_ROOT = SOLVER_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from setp_solver.potential_pool_dynamic import (  # noqa: E402
    QIU_TRIGGER_PROTOCOL,
    TriggerBatch,
    TriggerEvent,
    build_trigger_batches,
)


CONTRACT_ID = "MAIN3_PAIRED_DYNAMIC_EXPERIMENT_V1"
ARM_DYNAMIC = "rolling_dynamic"
ARM_MECHANICAL = "mechanical_online_p38"
ARM_STATIC = "full_information_static_reference"
REFERENCE_ROLE = "reference_only_not_fair_comparator"

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
    "customers_served",
    "customers_total",
    "demand_served_kg",
    "demand_total_kg",
    "enabled_vehicles",
    "unserved_customer_ids",
    "outsourced_customer_ids",
    "eligible_for_dynamic_benefit",
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
) -> SharedEventStream:
    """Build P10 rule-E batches once for reuse by every online arm."""

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
    batches = build_trigger_batches(trigger_events, QIU_TRIGGER_PROTOCOL)
    payload = {
        "policy_id": QIU_TRIGGER_PROTOCOL.policy_id,
        "protocol": asdict(QIU_TRIGGER_PROTOCOL),
        "events": [asdict(order) for order in dynamic_events],
        "batches": [asdict(batch) for batch in batches],
    }
    return SharedEventStream(
        policy_id=QIU_TRIGGER_PROTOCOL.policy_id,
        events=dynamic_events,
        batches=batches,
        sha256=_canonical_sha256(payload),
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
    }


def run_paired_pipeline(
    *,
    problem: ToyProblem,
    seeds: Sequence[int],
    wall_clock_seconds: float,
    backend: ExperimentBackend,
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
        shared_stream = construct_shared_event_stream(problem.orders)
        shared_streams[int(seed)] = shared_stream
        stream_payloads[int(seed)] = {
            "contract_id": CONTRACT_ID,
            "instance_id": problem.instance_id,
            "seed": int(seed),
            "event_stream_sha256": shared_stream.sha256,
            "policy_id": shared_stream.policy_id,
            "protocol": asdict(QIU_TRIGGER_PROTOCOL),
            "events": [asdict(order) for order in shared_stream.events],
            "batches": [asdict(batch) for batch in shared_stream.batches],
        }
        initial_state = backend.initial_plan(problem, wall_clock_seconds)
        dynamic = _run_online_arm(
            problem=problem,
            seed=int(seed),
            arm=ARM_DYNAMIC,
            initial_state=initial_state,
            shared_stream=shared_stream,
            backend=backend,
            wall_clock_seconds=wall_clock_seconds,
        )
        mechanical = _run_online_arm(
            problem=problem,
            seed=int(seed),
            arm=ARM_MECHANICAL,
            initial_state=initial_state,
            shared_stream=shared_stream,
            backend=backend,
            wall_clock_seconds=wall_clock_seconds,
        )
        static_started = perf_counter()
        static_state = backend.full_information_static(
            problem,
            all_customer_ids,
            wall_clock_seconds * len(shared_stream.batches),
        )
        static_elapsed = perf_counter() - static_started
        static = ArmOutcome(
            arm=ARM_STATIC,
            state=static_state,
            evaluation=backend.evaluate(problem, static_state),
            actual_wall_clock_seconds=static_elapsed,
            event_rows=(),
            fleet_rows=(),
            run_status="completed",
        )
        for outcome, role in (
            (dynamic, "online_comparator_arm"),
            (mechanical, "online_comparator_arm"),
            (static, REFERENCE_ROLE),
        ):
            raw_rows.append(
                _raw_row(
                    problem=problem,
                    seed=int(seed),
                    outcome=outcome,
                    shared_stream=shared_stream,
                    backend=backend,
                    wall_clock_seconds=wall_clock_seconds,
                    role=role,
                )
            )
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
            mechanical.run_status == "completed"
            and dynamic.run_status == "completed"
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
            }
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
) -> None:
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
    _write_json(
        output_dir / "metadata.json",
        {
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
    )
    _write_json(
        output_dir / "decision.json",
        {
            "status": "DRY_RUN_ONLY" if dry_run else "UNREVIEWED_FORMAL_OUTPUT",
            "dynamic_benefit_formula": (
                "mechanical_realized_cost - dynamic_realized_cost"
            ),
            "static_reference_is_comparator": False,
            "formal_infeasible_candidate_policy": "PENDING_USER_DECISION",
        },
    )
    (output_dir / "report.md").write_text(
        "# Dynamic experiment package\n\n"
        + (
            "This is a synthetic dry run. It is not formal experiment evidence.\n"
            if dry_run
            else "Formal run package.\n"
        ),
        encoding="utf-8",
    )
    hash_targets = sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.name != "artifact_hashes.json"
    )
    _write_json(
        output_dir / "artifact_hashes.json",
        {
            str(path.relative_to(output_dir)): _file_sha256(path)
            for path in hash_targets
        },
    )


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


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance-id")
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
    if args.infeasible_policy == "third_party_outsourcing":
        if args.outsourcing_cost_file is None:
            raise PendingUserDecisionError(
                "formal execution blocked: no approved outsourcing cost source"
            )
    raise RuntimeError(
        "formal execution is not enabled in this design-only task: connect the "
        "approved P34 A1 event bundle and production Problem-HGS backend first"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.dry_run:
        _formal_preflight(args)
    problem = _synthetic_problem()
    results = run_paired_pipeline(
        problem=problem,
        seeds=args.seeds,
        wall_clock_seconds=float(args.wall_clock_seconds),
        backend=ToyBackend(),
    )
    write_output_package(
        output_dir=args.output_dir,
        results=results,
        seeds=args.seeds,
        wall_clock_seconds=float(args.wall_clock_seconds),
        dry_run=True,
    )
    print(
        json.dumps(
            {
                "status": "DRY_RUN_COMPLETED",
                "output_dir": str(args.output_dir),
                "event_stream_sha256": results["shared_stream"].sha256,
                "paired_rows": len(results["paired_rows"]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
