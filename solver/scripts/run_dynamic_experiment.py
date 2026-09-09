#!/usr/bin/env python3
"""Run the paper's one-repeat mixed-event dynamic comparison.

The rolling and sequential-insertion arms share one initial plan, one event
stream, and one evaluator.  The full-information solve remains a reference.
There are no exposed seeds, time limits, iteration limits, hashes, or
run-identity sidecars.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping, Protocol, Sequence


SCRIPT_PATH = Path(__file__).resolve()
SOLVER_ROOT = SCRIPT_PATH.parents[1]
SRC_ROOT = SOLVER_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from setp_solver.c8_dynamic_stream import (  # noqa: E402
    C8Protocol,
    active_customers_after_events,
)


CONTRACT_ID = "PAPER_MIXED_DYNAMIC_COMPARISON"
ARM_DYNAMIC = "rolling_reoptimization"
ARM_MECHANICAL = "sequential_insertion"
ARM_STATIC = "full_information_reference"
REFERENCE_ROLE = "reference"


@dataclass(frozen=True)
class ExperimentOrder:
    event_id: str
    customer_id: str
    appearance_second: float
    demand_kg: float
    x: float
    y: float
    initially_visible: bool = False
    event_type: str = "add"
    old_demand_kg: float = 0.0
    old_ready_second: float = 0.0
    old_due_second: float = 0.0
    new_ready_second: float = 0.0
    new_due_second: float = 0.0

    @property
    def trigger_demand_kg(self) -> float:
        return float(self.demand_kg) if self.event_type == "add" else 0.0


@dataclass(frozen=True)
class TriggerBatch:
    batch_index: int
    trigger_second: float
    cause: str
    event_ids: tuple[str, ...]
    customer_ids: tuple[str, ...]
    demand_kg: float


@dataclass(frozen=True)
class SharedEventStream:
    policy_id: str
    events: tuple[ExperimentOrder, ...]
    batches: tuple[TriggerBatch, ...]


@dataclass(frozen=True)
class Evaluation:
    total_cost: float
    total_emissions_kg: float
    customers_served: int
    demand_served_kg: float
    enabled_vehicles: int
    full_evaluation_feasible: bool = True
    details: Mapping[str, Any] = field(default_factory=dict)


class ExperimentBackend(Protocol):
    evaluator_identity: str

    def initial_plan(self, problem: Any) -> Any: ...

    def rolling_reoptimize(
        self,
        problem: Any,
        current: Any,
        active_customer_ids: Sequence[str],
        event_ids: Sequence[str],
        trigger_second: float,
    ) -> tuple[Any, str]: ...

    def mechanical_dispatch(
        self,
        problem: Any,
        current: Any,
        active_customer_ids: Sequence[str],
        event_ids: Sequence[str],
        trigger_second: float,
    ) -> tuple[Any, str]: ...

    def full_information_static(
        self,
        problem: Any,
        final_customer_ids: Sequence[str],
    ) -> Any: ...

    def evaluate(self, problem: Any, state: Any) -> Evaluation: ...

    def active_totals(
        self,
        problem: Any,
        active_customer_ids: Sequence[str],
        applied_event_ids: Sequence[str],
    ) -> tuple[int, float]: ...


def construct_shared_event_stream(
    events: Sequence[ExperimentOrder],
    protocol: C8Protocol = C8Protocol(),
    batches: Sequence[Any] | None = None,
) -> SharedEventStream:
    """Construct the common stream once; supplied paper batches pass through."""

    dynamic = tuple(event for event in events if not event.initially_visible)
    if batches is None:
        built = _build_batches(dynamic, protocol)
    else:
        built = tuple(
            TriggerBatch(
                batch_index=int(batch.batch_index),
                trigger_second=float(batch.trigger_second),
                cause=str(batch.cause),
                event_ids=tuple(batch.event_ids),
                customer_ids=tuple(batch.customer_ids),
                demand_kg=float(batch.demand_kg),
            )
            for batch in batches
        )
    return SharedEventStream(protocol.policy_id, dynamic, built)


def _build_batches(
    events: Sequence[ExperimentOrder],
    protocol: C8Protocol,
) -> tuple[TriggerBatch, ...]:
    ordered = sorted(events, key=lambda event: (event.appearance_second, event.event_id))
    pending: list[ExperimentOrder] = []
    result: list[TriggerBatch] = []
    deadline = float(protocol.reception_start_second + protocol.trigger_interval_second)

    def flush(trigger_second: float, cause: str) -> None:
        nonlocal pending
        if not pending:
            return
        result.append(
            TriggerBatch(
                len(result) + 1,
                float(trigger_second),
                cause,
                tuple(event.event_id for event in pending),
                tuple(event.customer_id for event in pending),
                sum(event.trigger_demand_kg for event in pending),
            )
        )
        pending = []

    for event in ordered:
        while deadline < event.appearance_second:
            flush(deadline, "maximum_wait")
            deadline = min(
                deadline + float(protocol.trigger_interval_second),
                float(protocol.reception_end_second),
            )
        pending.append(event)
        if sum(item.trigger_demand_kg for item in pending) >= (
            protocol.trigger_demand_threshold_kg
        ):
            flush(event.appearance_second, "demand_threshold")
            deadline = min(
                event.appearance_second + float(protocol.trigger_interval_second),
                float(protocol.reception_end_second),
            )
    flush(
        min(deadline, float(protocol.reception_end_second)),
        "window_end" if deadline >= protocol.reception_end_second else "maximum_wait",
    )
    return tuple(result)


def _apply_events(
    initial_customer_ids: Iterable[str],
    events: Sequence[ExperimentOrder],
) -> frozenset[str]:
    return active_customers_after_events(initial_customer_ids, events)


def run_paired_pipeline(
    *,
    problem: Any,
    backend: ExperimentBackend,
) -> dict[str, Any]:
    """Run one paper-required repetition without a user-selected random seed."""

    batches = getattr(getattr(problem, "c8_stream", None), "trigger_batches", None)
    stream = construct_shared_event_stream(
        problem.dynamic_orders,
        batches=batches,
    )
    event_by_id = {event.event_id: event for event in stream.events}
    initial_customer_ids = tuple(order.customer_id for order in problem.initial_orders)
    initial_started = perf_counter()
    initial = backend.initial_plan(problem)
    initial_seconds = perf_counter() - initial_started
    states = {ARM_DYNAMIC: initial, ARM_MECHANICAL: initial}
    applied: list[str] = []
    event_rows: list[dict[str, Any]] = []

    for batch in stream.batches:
        applied.extend(batch.event_ids)
        applied_events = tuple(event_by_id[event_id] for event_id in applied)
        active = tuple(sorted(_apply_events(initial_customer_ids, applied_events)))
        for arm in (ARM_DYNAMIC, ARM_MECHANICAL):
            started = perf_counter()
            if arm == ARM_DYNAMIC:
                state, detail = backend.rolling_reoptimize(
                    problem,
                    states[arm],
                    active,
                    batch.event_ids,
                    batch.trigger_second,
                )
            else:
                state, detail = backend.mechanical_dispatch(
                    problem,
                    states[arm],
                    active,
                    batch.event_ids,
                    batch.trigger_second,
                )
            states[arm] = state
            elapsed = perf_counter() - started
            evaluation = backend.evaluate(problem, state)
            customer_total, demand_total = backend.active_totals(
                problem,
                active,
                applied,
            )
            batch_events = [event_by_id[event_id] for event_id in batch.event_ids]
            event_rows.append(
                {
                    "instance_id": problem.instance_id,
                    "arm": arm,
                    "batch_index": batch.batch_index,
                    "trigger_second": batch.trigger_second,
                    "trigger_cause": batch.cause,
                    "event_ids": "|".join(batch.event_ids),
                    "event_types": "|".join(event.event_type for event in batch_events),
                    "customer_ids": "|".join(batch.customer_ids),
                    "active_customer_ids": "|".join(active),
                    "decision_detail": detail,
                    "actual_wall_clock_seconds": elapsed,
                    "total_cost": evaluation.total_cost,
                    "total_emissions_kg": evaluation.total_emissions_kg,
                    "customers_served": evaluation.customers_served,
                    "customers_total": customer_total,
                    "demand_served_kg": evaluation.demand_served_kg,
                    "demand_total_kg": demand_total,
                    "enabled_vehicles": evaluation.enabled_vehicles,
                    "full_evaluation_feasible": evaluation.full_evaluation_feasible,
                    **dict(evaluation.details),
                }
            )
            print(
                f"PROGRESS batch={batch.batch_index} arm={arm} "
                f"served={evaluation.customers_served}/{customer_total} "
                f"cost={evaluation.total_cost:.2f} "
                f"feasible={evaluation.full_evaluation_feasible} "
                f"wall={elapsed:.0f}s",
                file=sys.stderr,
                flush=True,
            )

    final_events = tuple(event_by_id[event_id] for event_id in applied)
    final_customer_ids = tuple(
        sorted(_apply_events(initial_customer_ids, final_events))
    )
    static_started = perf_counter()
    static_state = backend.full_information_static(problem, final_customer_ids)
    static_seconds = perf_counter() - static_started
    states[ARM_STATIC] = static_state

    raw_rows: list[dict[str, Any]] = []
    for arm, state in states.items():
        evaluation = backend.evaluate(problem, state)
        customer_total, demand_total = backend.active_totals(
            problem,
            final_customer_ids,
            applied,
        )
        raw_rows.append(
            {
                "instance_id": problem.instance_id,
                "arm": arm,
                "role": REFERENCE_ROLE if arm == ARM_STATIC else "online_comparison",
                "run_status": "completed",
                "actual_wall_clock_seconds": (
                    static_seconds if arm == ARM_STATIC else sum(
                        float(row["actual_wall_clock_seconds"])
                        for row in event_rows
                        if row["arm"] == arm
                    )
                ),
                "shared_initial_plan_seconds": initial_seconds,
                "total_cost": evaluation.total_cost,
                "total_emissions_kg": evaluation.total_emissions_kg,
                "customers_served": evaluation.customers_served,
                "customers_total": customer_total,
                "demand_served_kg": evaluation.demand_served_kg,
                "demand_total_kg": demand_total,
                "enabled_vehicles": evaluation.enabled_vehicles,
                "full_evaluation_feasible": evaluation.full_evaluation_feasible,
                **dict(evaluation.details),
            }
        )

    rows_by_arm = {row["arm"]: row for row in raw_rows}
    dynamic = rows_by_arm[ARM_DYNAMIC]
    mechanical = rows_by_arm[ARM_MECHANICAL]
    same_service = (
        dynamic["customers_served"] == mechanical["customers_served"]
        and abs(dynamic["demand_served_kg"] - mechanical["demand_served_kg"]) <= 1e-6
    )
    paired_row = {
        "instance_id": problem.instance_id,
        "sequential_insertion_cost": mechanical["total_cost"],
        "rolling_reoptimization_cost": dynamic["total_cost"],
        "rolling_minus_sequential_cost": (
            dynamic["total_cost"] - mechanical["total_cost"]
        ),
        "sequential_insertion_emissions_kg": mechanical["total_emissions_kg"],
        "rolling_reoptimization_emissions_kg": dynamic["total_emissions_kg"],
        "same_service": same_service,
    }
    return {
        "shared_stream": stream,
        "raw_rows": tuple(raw_rows),
        "event_rows": tuple(event_rows),
        "paired_rows": (paired_row,),
        "backend_options": _backend_options(backend),
    }


def _backend_options(backend: ExperimentBackend) -> dict[str, Any]:
    """Record the rolling-arm switches actually in force for this run."""

    return {
        name: getattr(backend, name, None)
        for name in (
            "prefilter_ineligible_assets",
            "partial_fallback",
            "insertion_candidate_budget",
            "stage_cycle_cap",
            "reference_cycle_cap",
        )
    }


@dataclass(frozen=True)
class ToyVehicle:
    vehicle_id: str
    capacity_kg: float
    fixed_cost: float
    distance_cost_per_unit: float
    emissions_kg_per_unit: float
    max_trips: int = 2


@dataclass(frozen=True)
class ToyProblem:
    instance_id: str
    vehicles: tuple[ToyVehicle, ...]
    initial_orders: tuple[ExperimentOrder, ...]
    dynamic_orders: tuple[ExperimentOrder, ...]

    @property
    def event_by_id(self) -> Mapping[str, ExperimentOrder]:
        return {event.event_id: event for event in self.dynamic_orders}

    def demand_by_customer(self, event_ids: Sequence[str]) -> dict[str, float]:
        demand = {order.customer_id: order.demand_kg for order in self.initial_orders}
        for event_id in event_ids:
            event = self.event_by_id[event_id]
            if event.event_type == "add":
                demand[event.customer_id] = event.demand_kg
            elif event.event_type == "cancel":
                demand.pop(event.customer_id, None)
            elif event.event_type == "demand_change":
                demand[event.customer_id] = event.demand_kg
        return demand

    def coordinates(self) -> Mapping[str, tuple[float, float]]:
        return {
            order.customer_id: (order.x, order.y)
            for order in (*self.initial_orders, *self.dynamic_orders)
        }


@dataclass(frozen=True)
class ToyState:
    trips_by_vehicle: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]
    applied_event_ids: tuple[str, ...] = ()

    def trips(self, vehicle_id: str) -> tuple[tuple[str, ...], ...]:
        return dict(self.trips_by_vehicle).get(vehicle_id, ())


def _state_from_mapping(
    mapping: Mapping[str, Sequence[Sequence[str]]],
    *,
    applied_event_ids: Sequence[str] = (),
) -> ToyState:
    return ToyState(
        tuple(
            (vehicle_id, tuple(tuple(trip) for trip in trips))
            for vehicle_id, trips in sorted(mapping.items())
        ),
        tuple(applied_event_ids),
    )


class ToyBackend:
    evaluator_identity = "toy-euclidean"

    def initial_plan(self, problem: ToyProblem) -> ToyState:
        return self._global_optimum(
            problem,
            tuple(order.customer_id for order in problem.initial_orders),
            (),
        )

    def rolling_reoptimize(
        self,
        problem: ToyProblem,
        current: ToyState,
        active_customer_ids: Sequence[str],
        event_ids: Sequence[str],
        trigger_second: float,
    ) -> tuple[ToyState, str]:
        del trigger_second
        applied = (*current.applied_event_ids, *event_ids)
        return (
            self._global_optimum(problem, active_customer_ids, applied),
            "global_reoptimization_over_active_orders",
        )

    def mechanical_dispatch(
        self,
        problem: ToyProblem,
        current: ToyState,
        active_customer_ids: Sequence[str],
        event_ids: Sequence[str],
        trigger_second: float,
    ) -> tuple[ToyState, str]:
        del active_customer_ids, trigger_second
        applied = (*current.applied_event_ids, *event_ids)
        mapping = {
            vehicle_id: [list(trip) for trip in trips]
            for vehicle_id, trips in current.trips_by_vehicle
        }
        for event_id in event_ids:
            event = problem.event_by_id[event_id]
            if event.event_type == "cancel":
                mapping = {
                    vehicle_id: [
                        [customer for customer in trip if customer != event.customer_id]
                        for trip in trips
                    ]
                    for vehicle_id, trips in mapping.items()
                }
        state = _state_from_mapping(mapping, applied_event_ids=applied)
        details: list[str] = []
        for event_id in event_ids:
            event = problem.event_by_id[event_id]
            if event.event_type != "add":
                details.append(f"{event.customer_id}:{event.event_type}")
                continue
            state, candidate_class = self._insert(problem, state, event.customer_id)
            details.append(f"{event.customer_id}:{candidate_class}")
        return state, ";".join(details)

    def full_information_static(
        self,
        problem: ToyProblem,
        final_customer_ids: Sequence[str],
    ) -> ToyState:
        event_ids = tuple(event.event_id for event in problem.dynamic_orders)
        return self._global_optimum(problem, final_customer_ids, event_ids)

    def active_totals(
        self,
        problem: ToyProblem,
        active_customer_ids: Sequence[str],
        applied_event_ids: Sequence[str],
    ) -> tuple[int, float]:
        demand = problem.demand_by_customer(applied_event_ids)
        return len(active_customer_ids), sum(demand[item] for item in active_customer_ids)

    def evaluate(self, problem: ToyProblem, state: ToyState) -> Evaluation:
        demand = problem.demand_by_customer(state.applied_event_ids)
        vehicles = {vehicle.vehicle_id: vehicle for vehicle in problem.vehicles}
        total_cost = 0.0
        emissions = 0.0
        served: set[str] = set()
        enabled = 0
        for vehicle_id, trips in state.trips_by_vehicle:
            if not any(trips):
                continue
            vehicle = vehicles[vehicle_id]
            enabled += 1
            total_cost += vehicle.fixed_cost
            for trip in trips:
                distance = self._route_distance(problem, trip)
                total_cost += distance * vehicle.distance_cost_per_unit
                emissions += distance * vehicle.emissions_kg_per_unit
                served.update(trip)
        return Evaluation(
            total_cost,
            emissions,
            len(served),
            sum(demand[item] for item in served),
            enabled,
        )

    def _insert(
        self,
        problem: ToyProblem,
        state: ToyState,
        customer_id: str,
    ) -> tuple[ToyState, str]:
        demand = problem.demand_by_customer(state.applied_event_ids)
        vehicles = {vehicle.vehicle_id: vehicle for vehicle in problem.vehicles}
        mapping = {
            vehicle_id: [list(trip) for trip in trips]
            for vehicle_id, trips in state.trips_by_vehicle
        }
        candidates: list[tuple[float, str, ToyState]] = []
        for vehicle_id, trips in mapping.items():
            vehicle = vehicles[vehicle_id]
            for trip_index, trip in enumerate(trips):
                if sum(demand[item] for item in trip) + demand[customer_id] > vehicle.capacity_kg:
                    continue
                for position in range(len(trip) + 1):
                    candidate = {key: [list(row) for row in value] for key, value in mapping.items()}
                    candidate[vehicle_id][trip_index].insert(position, customer_id)
                    state_candidate = _state_from_mapping(
                        candidate,
                        applied_event_ids=state.applied_event_ids,
                    )
                    candidates.append(
                        (self.evaluate(problem, state_candidate).total_cost, "existing_trip", state_candidate)
                    )
        if candidates:
            selected = min(candidates, key=lambda item: item[0])
            return selected[2], selected[1]
        for vehicle_id, trips in mapping.items():
            vehicle = vehicles[vehicle_id]
            if trips and len(trips) < vehicle.max_trips and demand[customer_id] <= vehicle.capacity_kg:
                candidate = {key: [list(row) for row in value] for key, value in mapping.items()}
                candidate[vehicle_id].append([customer_id])
                return (
                    _state_from_mapping(candidate, applied_event_ids=state.applied_event_ids),
                    "new_trip_on_used_vehicle",
                )
        for vehicle in problem.vehicles:
            if mapping.get(vehicle.vehicle_id) or demand[customer_id] > vehicle.capacity_kg:
                continue
            candidate = {key: [list(row) for row in value] for key, value in mapping.items()}
            candidate[vehicle.vehicle_id] = [[customer_id]]
            return (
                _state_from_mapping(candidate, applied_event_ids=state.applied_event_ids),
                "unused_vehicle",
            )
        raise RuntimeError(f"no insertion for {customer_id}")

    def _global_optimum(
        self,
        problem: ToyProblem,
        customer_ids: Sequence[str],
        event_ids: Sequence[str],
    ) -> ToyState:
        customers = tuple(customer_ids)
        if not customers:
            return _state_from_mapping({}, applied_event_ids=event_ids)
        demand = problem.demand_by_customer(event_ids)
        best: tuple[float, ToyState] | None = None
        vehicle_ids = tuple(vehicle.vehicle_id for vehicle in problem.vehicles)
        for assignment in itertools.product(vehicle_ids, repeat=len(customers)):
            mapping = {vehicle_id: [[]] for vehicle_id in vehicle_ids}
            for customer_id, vehicle_id in zip(customers, assignment, strict=True):
                mapping[vehicle_id][0].append(customer_id)
            if any(
                sum(demand[item] for item in mapping[vehicle.vehicle_id][0])
                > vehicle.capacity_kg
                for vehicle in problem.vehicles
            ):
                continue
            state = _state_from_mapping(mapping, applied_event_ids=event_ids)
            score = self.evaluate(problem, state).total_cost
            if best is None or score < best[0]:
                best = (score, state)
        if best is None:
            raise RuntimeError("toy problem has no feasible assignment")
        return best[1]

    @staticmethod
    def _route_distance(problem: ToyProblem, trip: Sequence[str]) -> float:
        coordinates = problem.coordinates()
        points = [(0.0, 0.0), *(coordinates[item] for item in trip), (0.0, 0.0)]
        return sum(
            ((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5
            for left, right in zip(points, points[1:])
        )


def _synthetic_problem() -> ToyProblem:
    start = C8Protocol().reception_start_second
    initial = (
        ExperimentOrder("initial-A", "A", 0.0, 1.0, 1.0, 0.0, True, "initial"),
        ExperimentOrder("initial-B", "B", 0.0, 1.0, 2.0, 0.0, True, "initial"),
    )
    events = (
        ExperimentOrder("event-C", "C", start + 60.0, 1.0, 3.0, 0.0),
        ExperimentOrder("event-B", "B", start + 120.0, 0.0, 2.0, 0.0, event_type="cancel"),
        ExperimentOrder("event-D", "D", start + 180.0, 1.0, 4.0, 0.0),
    )
    vehicles = (
        ToyVehicle("V1", 3.0, 1.0, 1.0, 0.1),
        ToyVehicle("V2", 3.0, 1.0, 1.0, 0.1),
    )
    return ToyProblem("synthetic-mixed-events", vehicles, initial, events)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = tuple(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_output_package(output_dir: Path, results: Mapping[str, Any]) -> bool:
    output_dir.mkdir(parents=True, exist_ok=False)
    raw_rows = tuple(results["raw_rows"])
    event_rows = tuple(results["event_rows"])
    paired_rows = tuple(results["paired_rows"])
    _write_csv(output_dir / "raw_runs.csv", raw_rows)
    _write_csv(output_dir / "dynamic_events.csv", event_rows)
    _write_csv(output_dir / "paired_results.csv", paired_rows)
    accepted = all(
        row["run_status"] == "completed"
        and bool(row["full_evaluation_feasible"])
        and int(row["customers_served"]) == int(row["customers_total"])
        and abs(float(row["demand_served_kg"]) - float(row["demand_total_kg"])) <= 1e-6
        for row in raw_rows
    )
    metadata = {
        "contract_id": CONTRACT_ID,
        "repetition_count": 1,
        "event_source": "paper mixed-event table",
        "stop_rule": "20,000 consecutive non-improving iterations; no restart",
        "arms": [ARM_STATIC, ARM_MECHANICAL, ARM_DYNAMIC],
        "backend_options": dict(results.get("backend_options", {})),
    }
    decision = {
        "accepted": accepted,
        "status": "completed" if accepted else "failed",
        "service_checked": True,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(
        "\n".join(
            (
                "# 动态需求实验",
                "",
                "本次按论文混合事件表运行一次，比较完全信息参考、顺序插入和滚动重优化。",
                f"服务量与可行性检查：{'通过' if accepted else '未通过'}。",
                "详细数值见 raw_runs.csv、dynamic_events.csv 和 paired_results.csv。",
                "",
            )
        ),
        encoding="utf-8",
    )
    return accepted


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--data-repo-root", type=Path)
    parser.add_argument(
        "--dynamic-stream-dir",
        type=Path,
        default=Path(
            "data/dynamic_streams/"
            "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd_mixed_events"
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--carbon-price",
        type=float,
        default=None,
        help="carbon price in CNY/kg; default keeps the China81 constant",
    )
    parser.add_argument(
        "--prefilter-ineligible-assets",
        action="store_true",
        help=(
            "skip trips whose load already rules out a revealed order before "
            "any complete evaluation; default off keeps the old search"
        ),
    )
    parser.add_argument(
        "--partial-fallback",
        action="store_true",
        help=(
            "when the rolling insertion fails, serve the placeable part of "
            "the batch instead of deferring all of it; default off"
        ),
    )
    parser.add_argument(
        "--insertion-candidate-budget",
        type=int,
        default=None,
        help=(
            "maximum complete candidate evaluations per rolling batch; "
            "default unlimited. Deterministic, unlike a wall-clock cap"
        ),
    )
    parser.add_argument(
        "--stage-cycle-cap",
        type=int,
        default=None,
        help=(
            "stop each rolling-arm Problem-HGS stage after this many total "
            "cycles even while it is still improving; default unlimited "
            "(patience only). Deterministic, unlike a wall-clock budget. "
            "Does not touch the initial plan or the static reference"
        ),
    )
    parser.add_argument(
        "--reference-cycle-cap",
        type=int,
        default=None,
        help=(
            "the same total-cycle cap for the initial plan and the "
            "full-information static reference; default unlimited. Separate "
            "from --stage-cycle-cap on purpose: capping the reference moves "
            "the yardstick the rolling arm is measured against"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.dry_run:
        problem = _synthetic_problem()
        backend: ExperimentBackend = ToyBackend()
    else:
        from setp_solver.main3b_backend import (  # noqa: PLC0415
            ProductionBackend,
            build_production_problem,
        )

        repo = (
            SOLVER_ROOT.parent
            if args.data_repo_root is None
            else args.data_repo_root.resolve()
        )
        stream = (
            args.dynamic_stream_dir
            if args.dynamic_stream_dir.is_absolute()
            else repo / args.dynamic_stream_dir
        )
        problem = build_production_problem(
            repo,
            stream,
            carbon_price_cny_per_kg=args.carbon_price,
        )
        backend = ProductionBackend(
            prefilter_ineligible_assets=bool(args.prefilter_ineligible_assets),
            partial_fallback=bool(args.partial_fallback),
            insertion_candidate_budget=args.insertion_candidate_budget,
            stage_cycle_cap=args.stage_cycle_cap,
            reference_cycle_cap=args.reference_cycle_cap,
        )
    results = run_paired_pipeline(problem=problem, backend=backend)
    accepted = write_output_package(args.output_dir, results)
    print(
        json.dumps(
            {
                "status": "completed" if accepted else "failed",
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
        )
    )
    return 0 if accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
