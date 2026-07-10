"""Dynamic event and rolling-reoptimization helpers.

v2026-06-12: W2b replaces the earlier static-solution stage split with an
event-triggered rolling loop. Events use the same rich TSV shape as the Python
generator when available; otherwise add events are synthesized from sibling
generated bundles so new customers have real coordinates and time windows.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path
import random
import time
from typing import Any, Callable

import numpy as np

from ..check import ROUTE_STRUCTURE, DynamicCheckContext, Violation, check_solution
from ..cost import _arc_loads, ev_arc_energy_kwh, evaluate, route_node_schedule
from ..instance_loader import Instance, Node
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import ChargingAction, Route, Solution, physical_vehicle_id, route_trip_vehicle_id
from ..algorithms.resetp_alns import WinnerKernelConfig, run_resetp_alns
from .bundle import load_search_bundle
from .charging import repair_route_charging
from .construction import build_initial_solution


@dataclass(frozen=True)
class DynamicEvent:
    event_id: str
    event_type: str
    t_appear: float
    customer_id: str
    old_demand: float
    new_demand: float
    x: float = 0.0
    y: float = 0.0
    delta_demand: float = 0.0
    old_ready_time: float = 0.0
    old_due_time: float = 0.0
    new_ready_time: float = 0.0
    new_due_time: float = 0.0
    time_window_action: str = "none"
    demand_source: str = "existing_customer"
    time_window_source: str = "existing_customer"
    donor_instance_id: str = ""
    donor_customer_id: str = ""
    source: str = "synthetic_overlay"
    seed: int = 0


@dataclass(frozen=True)
class RollingParameters:
    add_ratio: float = 0.10
    cancel_ratio: float = 0.05
    demand_change_ratio: float = 0.10
    delta_t_seconds: float = 10_800.0
    q_bar: int = 8
    stages: int = 4


@dataclass(frozen=True)
class StagePlanResult:
    solution: Solution
    instance: Instance
    evaluations: int
    feasible: bool
    violations: list[Any]
    backend: str


@dataclass(frozen=True)
class LockedRouteSnapshot:
    """The immutable, already-promised part of one physical vehicle route."""

    route: Route
    charging_actions: tuple[ChargingAction, ...]
    locked_customer_ids: tuple[str, ...]
    covered_customer_ids: tuple[str, ...]
    state: dict[str, Any]


@dataclass(frozen=True)
class DeferEligibilityResult:
    mandatory_ids: set[str]
    defer_eligible_ids: set[str]
    reasons: dict[str, str]
    proxy_notes: dict[str, str]


@dataclass(frozen=True)
class RollingPolicyContext:
    stage_index: int
    trigger_time: float
    stage_events: list[DynamicEvent]
    all_events: list[DynamicEvent]
    settings: RollingParameters
    base_instance: Instance
    effective_instance: Instance
    active_ids: set[str]
    served_customers: set[str]
    previous_plan: Solution | None
    previous_instance: Instance | None
    pending_customer_ids: set[str] = field(default_factory=set)
    mandatory_customer_ids: set[str] = field(default_factory=set)
    committed_customer_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class RollingPolicyDecision:
    active_ids: set[str] | None = None
    plan_now_ids: set[str] | None = None
    defer_ids: set[str] | None = None
    mandatory_ids: set[str] | None = None
    initial_plan: Solution | None = None
    stage_eval_budget: int | None = None
    stage_max_runtime_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


RollingPolicyCallback = Callable[[RollingPolicyContext], RollingPolicyDecision | dict[str, Any] | None]
INDEPENDENT_ALNS_BACKEND = "setp_solver.algorithms.resetp_alns"


def myopic_rolling_policy(context: RollingPolicyContext) -> RollingPolicyDecision:
    _ = context
    return RollingPolicyDecision(metadata={"action": "myopic"})


def load_or_generate_dynamic_events(
    bundle_dir: str | Path,
    *,
    seed: int = 1,
    params: RollingParameters | None = None,
) -> list[DynamicEvent]:
    """Read bundle events or synthesize the E7 default event stream."""

    path = Path(bundle_dir) / "dynamic_events.tsv"
    if path.exists():
        return _read_dynamic_events(path)
    bundle = load_search_bundle(bundle_dir)
    donors = _sibling_add_donors(Path(bundle_dir), bundle.instance)
    if not donors:
        raise RuntimeError("HALT_FOR_USER: E7 add-event synthesis needs sibling donor customers with real coordinates")
    return generate_dynamic_events(bundle.instance, seed=seed, params=params or RollingParameters(), add_donors=donors)


def generate_dynamic_events(
    instance: Instance,
    *,
    seed: int = 1,
    params: RollingParameters | None = None,
    add_donors: list[Node] | None = None,
) -> list[DynamicEvent]:
    """Generate add/cancel/demand-change events from W2 E7 defaults."""

    settings = params or RollingParameters()
    rng = random.Random(seed)
    customers = sorted((node for node in instance.nodes if node.node_type.lower() == "c"), key=lambda node: node.node_id)
    if not customers:
        return []
    n = len(customers)
    counts = {
        "add": max(1, round(n * settings.add_ratio)),
        "cancel": max(1, round(n * settings.cancel_ratio)),
        "demand_change": max(1, round(n * settings.demand_change_ratio)),
    }
    selected = customers[:]
    rng.shuffle(selected)
    donors = add_donors or selected
    events: list[DynamicEvent] = []
    horizon = settings.delta_t_seconds * max(1, settings.stages)
    cursor = 0
    for event_type, count in counts.items():
        for _ in range(count):
            base = selected[cursor % len(selected)]
            cursor += 1
            old = float(base.demand)
            t_appear = rng.uniform(0.05 * horizon, 0.95 * horizon)
            x = float(base.x)
            y = float(base.y)
            old_ready = float(base.ready_time)
            old_due = float(base.due_time)
            new_ready = old_ready
            new_due = old_due
            demand_source = "existing_customer"
            time_window_source = "existing_customer"
            donor_customer_id = ""
            customer_id = base.node_id
            if event_type == "add":
                donor = donors[(len(events) + seed) % len(donors)]
                customer_id = f"N{len(events) + 1}"
                x = float(donor.x)
                y = float(donor.y)
                old = 0.0
                old_ready = float(donor.ready_time)
                old_due = float(donor.due_time)
                new_ready, new_due = _feasible_event_window(instance, x, y, t_appear, old_ready, old_due)
                new = max(1.0, float(donor.demand))
                demand_source = "donor_inherited"
                time_window_source = "donor_inherited"
                donor_customer_id = donor.node_id
            elif event_type == "cancel":
                new = 0.0
            else:
                new = old * rng.uniform(0.85, 1.15)
            events.append(
                DynamicEvent(
                    event_id=str(len(events) + 1),
                    event_type=event_type,
                    t_appear=float(t_appear),
                    customer_id=customer_id,
                    old_demand=float(old),
                    new_demand=float(new),
                    x=x,
                    y=y,
                    delta_demand=float(new - old),
                    old_ready_time=old_ready,
                    old_due_time=old_due,
                    new_ready_time=new_ready,
                    new_due_time=new_due,
                    demand_source=demand_source,
                    time_window_source=time_window_source,
                    donor_customer_id=donor_customer_id,
                    source="synthetic_overlay",
                    seed=int(seed),
                )
            )
    return sorted(events, key=lambda event: (event.t_appear, event.event_id))


def run_rolling_reoptimization(
    bundle_dir: str | Path,
    *,
    output_json_path: str | Path | None = None,
    seed: int = 1,
    eval_budget: int = 2000,
    max_runtime_seconds: float = 180.0,
    stage_eval_budget: int = 8000,
    stage_max_runtime_seconds: float = 120.0,
    params: RollingParameters | None = None,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    policy_callback: RollingPolicyCallback | None = None,
) -> dict[str, Any]:
    """Run the E7 rolling loop with qbar/delta-t triggers and static control."""

    settings = params or RollingParameters()
    bundle = load_search_bundle(bundle_dir)
    events = load_or_generate_dynamic_events(bundle_dir, seed=seed, params=settings)
    batches = _build_trigger_batches(events, settings)
    started = time.perf_counter()
    work_root = (
        Path(output_json_path).parent / "e7_stage_bundles"
        if output_json_path is not None
        else Path(bundle.bundle_dir) / ".e7_stage_bundles"
    )

    rows: list[dict[str, Any]] = []
    assertions: list[dict[str, Any]] = []
    cumulative_cost = 0.0
    cumulative_carbon = 0.0
    previous_end_cost = 0.0
    previous_end_carbon = 0.0
    total_evaluations = 0
    previous_plan: Solution | None = None
    previous_instance = bundle.instance
    served_customers: set[str] = set()
    committed_routes: list[Route] = []
    committed_actions: list[ChargingAction] = []
    reserved_charging_actions: list[ChargingAction] = []
    reserved_charging_keys: set[tuple[Any, ...]] = set()
    committed_node_state: dict[str, Node] = {}
    locked_node_state: dict[str, Node] = {}
    locked_route_snapshots: dict[str, LockedRouteSnapshot] = {}
    frozen_sequences: dict[str, list[str]] = {}
    stage_plan_customer_ids: dict[str, list[str]] = {}
    policy_trace: list[dict[str, Any]] = []
    policy_fallbacks: list[dict[str, Any]] = []
    pending_deferred_ids: set[str] = set()
    pending_defer_age: dict[str, int] = {}
    in_progress_vehicle_deadlines: dict[str, float] = {}

    for stage_index, batch in enumerate(batches):
        trigger = float(batch["trigger_time"])
        stage_events = list(batch["events"])
        for action in _charging_actions_started_by(previous_plan, trigger):
            key = _charging_action_key(action)
            if key not in reserved_charging_keys:
                reserved_charging_keys.add(key)
                reserved_charging_actions.append(action)
        for vehicle_id, deadline in _in_progress_physical_vehicle_deadlines(
            previous_plan,
            previous_instance,
            trigger_time=trigger,
            prices=prices,
        ).items():
            in_progress_vehicle_deadlines[vehicle_id] = max(
                float(deadline),
                float(in_progress_vehicle_deadlines.get(vehicle_id, 0.0)),
            )
        in_progress_vehicle_deadlines = {
            vehicle_id: deadline
            for vehicle_id, deadline in in_progress_vehicle_deadlines.items()
            if float(deadline) > trigger + 1e-9
        }
        initial_cost = cumulative_cost
        initial_carbon = cumulative_carbon
        conservation_ok = abs(initial_cost - previous_end_cost) <= 1e-6 and abs(initial_carbon - previous_end_carbon) <= 1e-6

        newly_committed = _commit_executed_customers(previous_plan, previous_instance, trigger, served_customers)
        if newly_committed:
            chunk = _solution_for_committed_customers(
                previous_plan,
                previous_instance,
                bundle.carbon_profile,
                newly_committed,
                prefix=f"S{stage_index}_",
                prices=prices,
            )
            chunk_violations = check_solution(chunk, _subinstance_for_customers(previous_instance, newly_committed), prices)
            if chunk_violations:
                payload = _halt_payload(
                    "setp-dynamic-rolling.v3",
                    "HALT_E7_COMMIT_CHUNK_CHECK",
                    bundle_dir,
                    seed,
                    eval_budget,
                    max_runtime_seconds,
                    stage_eval_budget,
                    stage_max_runtime_seconds,
                    settings,
                    events,
                    rows,
                    assertions,
                    total_evaluations,
                    started,
                    dynamic_chunk_failure_payload(int(stage_index), chunk_violations),
                )
                if output_json_path is not None:
                    path = Path(output_json_path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
                return payload
            chunk_metrics = evaluate(chunk, previous_instance, bundle.carbon_profile, prices)
            cumulative_cost += float(chunk_metrics["total_cost"])
            cumulative_carbon += float(chunk_metrics["E_total"])
            committed_routes.extend(chunk.routes)
            committed_actions.extend(chunk.charging_actions)
            served_customers.update(newly_committed)
            # Freeze each newly committed customer's demand/time-window at the
            # value the committed route was planned and costed against. Without
            # this, final_instance rebuilds from bundle.instance and reverts any
            # demand_change/time_window_change applied before service, so the
            # frozen route is validated against the original (higher) demand and
            # spuriously violates CAPACITY/BATTERY (Bug B).
            prev_lookup = {node.node_id: node for node in previous_instance.nodes}
            for customer_id in newly_committed:
                frozen = prev_lookup.get(customer_id)
                if frozen is not None:
                    committed_node_state[customer_id] = frozen
            pending_deferred_ids.difference_update(newly_committed)
            for customer_id in newly_committed:
                pending_defer_age.pop(customer_id, None)

        stage_cost = cumulative_cost - initial_cost
        stage_carbon = cumulative_carbon - initial_carbon
        next_trigger = (
            float(batches[stage_index + 1]["trigger_time"])
            if stage_index + 1 < len(batches)
            else float(trigger + settings.delta_t_seconds)
        )
        committed_not_completed = _committed_not_completed_customers(
            previous_plan,
            previous_instance,
            trigger_time=trigger,
            commitment_deadline=next_trigger,
            already_served=served_customers,
        )
        if committed_not_completed:
            previous_lookup = {node.node_id: node for node in previous_instance.nodes}
            for customer_id in committed_not_completed:
                frozen = previous_lookup.get(customer_id)
                if frozen is not None:
                    locked_node_state[customer_id] = frozen
            for snapshot in _locked_route_snapshots(
                previous_plan,
                previous_instance,
                committed_not_completed,
                served_customers,
                trigger_time=trigger,
                prices=prices,
            ):
                locked_route_snapshots[snapshot.route.vehicle_id] = snapshot
        effective_instance = _instance_after_events(
            bundle.instance,
            events,
            trigger,
            served_customers | committed_not_completed,
        )
        legal_unserved_ids = _legal_unserved_customer_ids(effective_instance, served_customers)
        pending_deferred_ids.intersection_update(legal_unserved_ids)
        for customer_id in list(pending_defer_age):
            if customer_id not in pending_deferred_ids:
                pending_defer_age.pop(customer_id, None)
        pending_count_before = len(pending_deferred_ids)
        pending_ids_before = sorted(pending_deferred_ids)
        active_ids = (
            set(_active_customer_ids(effective_instance, served_customers))
            - set(committed_not_completed)
        ) | set(pending_deferred_ids)
        defer_guard = _classify_defer_eligibility(
            effective_instance,
            active_ids,
            trigger_time=trigger,
            next_trigger_time=next_trigger,
            pending_customer_ids=pending_deferred_ids,
            pending_age_by_customer=pending_defer_age,
            prices=prices,
        )
        mandatory_customer_ids: set[str] = set(defer_guard.mandatory_ids)
        try:
            policy_decision = _policy_decision_for_stage(
                policy_callback,
                stage_index=stage_index,
                trigger=trigger,
                stage_events=stage_events,
                events=events,
                settings=settings,
                base_instance=bundle.instance,
                effective_instance=effective_instance,
                active_ids=active_ids,
                mandatory_customer_ids=mandatory_customer_ids,
                pending_customer_ids=pending_deferred_ids,
                served_customers=served_customers,
                committed_customer_ids=committed_not_completed,
                previous_plan=previous_plan,
                previous_instance=previous_instance,
            )
        except Exception as exc:
            if policy_callback is None:
                raise
            fallback = {
                "stage": int(stage_index),
                "trigger_time": float(trigger),
                "failed_policy": getattr(policy_callback, "__name__", policy_callback.__class__.__name__),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "fallback": "plan_all_with_independent_alns",
            }
            policy_fallbacks.append(fallback)
            policy_decision = RollingPolicyDecision(
                plan_now_ids=set(active_ids),
                mandatory_ids=set(mandatory_customer_ids),
                metadata={"action": "independent_safe_fallback", **fallback},
            )
        stage_active_ids = set(active_ids if policy_decision.plan_now_ids is None else policy_decision.plan_now_ids)
        stage_initial_plan = previous_plan if policy_decision.initial_plan is None else policy_decision.initial_plan
        stage_budget = int(stage_eval_budget if policy_decision.stage_eval_budget is None else policy_decision.stage_eval_budget)
        stage_runtime = float(
            stage_max_runtime_seconds
            if policy_decision.stage_max_runtime_seconds is None
            else policy_decision.stage_max_runtime_seconds
        )
        deferred_ids = sorted(
            set(active_ids) - set(stage_active_ids)
            if policy_decision.defer_ids is None
            else set(policy_decision.defer_ids)
        )
        lifecycle_violation_count = 0
        first_lifecycle_violation = ""
        current_reserved_physical_vehicle_ids = set(in_progress_vehicle_deadlines) | {
            physical_vehicle_id(snapshot.route.vehicle_id)
            for snapshot in locked_route_snapshots.values()
        }
        stage_plan = _run_stage_plan(
            bundle,
            effective_instance,
            stage_active_ids,
            work_root / f"stage_{stage_index:03d}",
            seed=seed + stage_index,
            stage_eval_budget=stage_budget,
            stage_max_runtime_seconds=stage_runtime,
            prices=prices,
            initial_plan=stage_initial_plan,
            reserved_charging_actions=reserved_charging_actions,
            reserved_physical_vehicle_ids=current_reserved_physical_vehicle_ids,
            stage_start_time=trigger,
        )
        total_evaluations += stage_plan.evaluations
        if stage_plan.violations:
            failure = dynamic_stage_failure_payload(int(stage_index), stage_plan.violations)
            failure["reserved_physical_vehicle_ids"] = sorted(current_reserved_physical_vehicle_ids)
            payload = _halt_payload(
                "setp-dynamic-rolling.v3",
                "HALT_E7_STAGE_CHECK",
                bundle_dir,
                seed,
                eval_budget,
                max_runtime_seconds,
                stage_eval_budget,
                stage_max_runtime_seconds,
                settings,
                events,
                rows,
                assertions,
                total_evaluations,
                started,
                failure,
            )
            if output_json_path is not None:
                path = Path(output_json_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            return payload
        stage_solution = stage_plan.solution
        planned_customer_ids = _solution_customer_ids(stage_solution, effective_instance)
        pending_deferred_ids.update(deferred_ids)
        pending_deferred_ids.difference_update(planned_customer_ids)
        pending_deferred_ids.difference_update(served_customers)
        pending_deferred_ids.intersection_update(legal_unserved_ids)
        for customer_id in list(pending_defer_age):
            if customer_id not in pending_deferred_ids:
                pending_defer_age.pop(customer_id, None)
        for customer_id in pending_deferred_ids:
            pending_defer_age[customer_id] = int(pending_defer_age.get(customer_id, 0)) + 1
        pending_count_after = len(pending_deferred_ids)
        pending_ids_after = sorted(pending_deferred_ids)
        if policy_callback is not None:
            policy_trace.append(
                {
                    "stage": int(stage_index),
                    "trigger_time": float(trigger),
                    "policy": getattr(policy_callback, "__name__", policy_callback.__class__.__name__),
                    "active_count_before": len(active_ids),
                    "active_count_after": len(stage_active_ids),
                    "deferred_count": len(deferred_ids),
                    "deferred_ids": deferred_ids,
                    "plan_now_count": len(stage_active_ids),
                    "defer_count": len(deferred_ids),
                    "mandatory_count": len(policy_decision.mandatory_ids or set()),
                    "committed_count": len(served_customers),
                    "lifecycle_violation_count": int(lifecycle_violation_count),
                    "first_lifecycle_violation": first_lifecycle_violation,
                    "defer_guard_reasons": dict(defer_guard.reasons),
                    "defer_guard_proxy_notes": dict(defer_guard.proxy_notes),
                    "pending_count_before": int(pending_count_before),
                    "pending_ids_before": pending_ids_before,
                    "new_deferred_count": len(deferred_ids),
                    "pending_count_after": int(pending_count_after),
                    "pending_ids_after": pending_ids_after,
                    "stage_eval_budget": int(stage_budget),
                    "stage_max_runtime_seconds": float(stage_runtime),
                    "metadata": dict(policy_decision.metadata),
                }
            )
        previous_plan = stage_solution
        previous_instance = effective_instance
        current_frozen = _frozen_route_sequences_from_routes(committed_routes)
        frozen_ok = all(current_frozen.get(route_id) == seq for route_id, seq in frozen_sequences.items())
        frozen_sequences = current_frozen
        previous_end_cost = cumulative_cost
        previous_end_carbon = cumulative_carbon
        stage_plan_customer_ids[str(stage_index)] = sorted(_solution_customer_ids(stage_solution, effective_instance))
        assertions.append(
            {
                "stage": stage_index,
                "conservation_ok": conservation_ok,
                "frozen_paths_ok": frozen_ok,
                "initial_cost": initial_cost,
                "previous_end_cost": previous_end_cost,
            }
        )
        rows.append(
            {
                "stage": stage_index,
                "trigger_time": _format_hour(trigger),
                "trigger_reason": batch["trigger_reason"],
                "event_counts": _event_count_string(stage_events),
                "active_customer_count": len(active_ids),
                "planned_customer_count": len(stage_active_ids),
                "deferred_customer_count": max(0, len(active_ids) - len(stage_active_ids)),
                "plan_now_count": len(stage_active_ids),
                "defer_count": len(deferred_ids),
                "mandatory_count": len(policy_decision.mandatory_ids or set()),
                "lifecycle_violation_count": int(lifecycle_violation_count),
                "first_lifecycle_violation": first_lifecycle_violation,
                "defer_guard_mandatory_count": len(defer_guard.mandatory_ids),
                "pending_count_before": int(pending_count_before),
                "pending_count_after": int(pending_count_after),
                "new_deferred_count": len(deferred_ids),
                "newly_revealed_customer_count": sum(1 for event in stage_events if str(event.event_type).lower() == "add"),
                "committed_customer_count": len(served_customers),
                "stage_eval_budget_used": int(stage_budget),
                "frozen_routes": len(current_frozen),
                "stage_route_count": len(stage_solution.routes),
                "solver_backend": stage_plan.backend,
                "reserved_physical_vehicle_ids": sorted(current_reserved_physical_vehicle_ids),
                "stage_ev_route_count": sum(1 for route in stage_solution.routes if str(route.vehicle_type).lower() == "ev"),
                "stage_charging_action_count": len(stage_solution.charging_actions),
                "stage_cost": stage_cost,
                "cumulative_cost": cumulative_cost,
                "cumulative_carbon_kg": cumulative_carbon,
                "min_fairness_ratio": "off",
                "feasible": bool(stage_plan.feasible and conservation_ok and frozen_ok),
            }
        )

    final_trigger = max((float(event.t_appear) for event in events), default=0.0)
    for action in _charging_actions_started_by(previous_plan, final_trigger):
        key = _charging_action_key(action)
        if key not in reserved_charging_keys:
            reserved_charging_keys.add(key)
            reserved_charging_actions.append(action)
    frozen_final_nodes = {**committed_node_state, **locked_node_state}
    locked_customer_ids = set(locked_node_state)
    final_instance = _instance_after_events(
        bundle.instance,
        events,
        final_trigger,
        served_customers | locked_customer_ids,
        frozen_final_nodes,
    )
    pending_deferred_ids.intersection_update(_legal_unserved_customer_ids(final_instance, served_customers))
    remaining = set(_active_customer_ids(final_instance, served_customers)) | set(pending_deferred_ids)
    final_repair_customer_count = 0
    final_repair_customer_ids: list[str] = []
    final_repair_evaluations = 0
    final_repair_violation_count = 0
    # Finalisation is deliberately not an optimisation stage.  Earlier code
    # sent every unfinished customer through _run_stage_plan here, which
    # silently changed promised vehicles and order.  Reuse the last open plan
    # and immutable route snapshots; an actually unplanned customer is a hard
    # failure rather than permission to manufacture a new depot route.
    locked_routes = [snapshot.route for snapshot in locked_route_snapshots.values()]
    locked_actions = [action for snapshot in locked_route_snapshots.values() for action in snapshot.charging_actions]
    locked_covered_ids = {
        customer_id
        for snapshot in locked_route_snapshots.values()
        for customer_id in snapshot.covered_customer_ids
    }
    residual_committed = _solution_for_customer_subset(
        Solution(routes=committed_routes, charging_actions=committed_actions),
        final_instance,
        bundle.carbon_profile,
        served_customers - locked_covered_ids,
        prefix="FINAL_EXEC_",
        prices=prices,
    )
    open_plan = previous_plan or Solution()
    dynamic_solution = _merge_final_plans(
        locked_routes,
        locked_actions,
        residual_committed,
        open_plan,
        final_instance,
        forbidden_open_customer_ids=locked_customer_ids | served_customers,
    )
    planned_final_ids = _solution_customer_ids(dynamic_solution, final_instance)
    missing_final_ids = remaining - planned_final_ids
    if missing_final_ids:
        failure = {
            "first_bad_stage": "final",
            "unplanned_customer_ids": sorted(missing_final_ids),
            "detail": "finalisation does not re-run the solver; customers were left without a valid rolling-stage plan",
            "policy_trace": policy_trace,
        }
        payload = _halt_payload(
            "setp-dynamic-rolling.v3",
            "HALT_E7_FINAL_PLAN_INCOMPLETE",
            bundle_dir,
            seed,
            eval_budget,
            max_runtime_seconds,
            stage_eval_budget,
            stage_max_runtime_seconds,
            settings,
            events,
            rows,
            assertions,
            total_evaluations,
            started,
            failure,
        )
        if output_json_path is not None:
            path = Path(output_json_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    final_bundle_dir = work_root / "full_information_static"
    _write_dynamic_bundle(final_bundle_dir, final_instance, bundle.carbon_profile, {"source": "e7_full_information_static"})
    static_run = run_resetp_alns(
        final_bundle_dir,
        config=WinnerKernelConfig(
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            require_charging_signal=False,
            carbon_aware_operators=False,
        ),
        prices=prices,
    )
    total_evaluations += int(static_run["evaluations"])
    dynamic_metrics = evaluate(dynamic_solution, final_instance, bundle.carbon_profile, prices)
    static_metrics = evaluate(static_run["best_solution"], final_instance, bundle.carbon_profile, prices)
    dynamic_violations = check_solution(dynamic_solution, final_instance, prices)
    static_violations = check_solution(static_run["best_solution"], final_instance, prices)
    dynamic_feasible = not dynamic_violations
    static_feasible = bool(static_run["feasible"] and not static_violations)
    rows.append(
        {
            "stage": "dynamic_vs_static",
            "trigger_time": "",
            "trigger_reason": "summary",
            "event_counts": _event_count_string(events),
            "frozen_routes": len(committed_routes),
            "stage_cost": float(dynamic_metrics["total_cost"]) - float(static_metrics["total_cost"]),
            "cumulative_cost": float(dynamic_metrics["total_cost"]),
            "cumulative_carbon_kg": float(dynamic_metrics["E_total"]),
            "min_fairness_ratio": "off",
            "feasible": bool(dynamic_feasible and static_feasible),
        }
    )

    elapsed_seconds = time.perf_counter() - started
    payload = {
        "schema_version": "setp-dynamic-rolling.v2",
        "build_note": "v2026-06-12: W2b true rolling reoptimization with qbar/delta-t triggers and full-information static control.",
        "bundle_dir": str(Path(bundle_dir)),
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "stage_eval_budget": int(stage_eval_budget),
        "stage_max_runtime_seconds": float(stage_max_runtime_seconds),
        "evaluations": int(total_evaluations),
        "actual_evals": int(total_evaluations),
        "elapsed_seconds": elapsed_seconds,
        "parameters": asdict(settings),
        "trigger_count": len(batches),
        "event_count": len(events),
        "events": [asdict(event) for event in events],
        "stage_plan_customer_ids": stage_plan_customer_ids,
        "stage_rows": rows,
        "assertions": assertions,
        "all_assertions_pass": all(row["conservation_ok"] and row["frozen_paths_ok"] for row in assertions),
        "policy_trace": policy_trace,
        "policy_fallback_count": len(policy_fallbacks),
        "policy_fallbacks": policy_fallbacks,
        "dynamic_solver_backend": INDEPENDENT_ALNS_BACKEND,
        "static_control_backend": INDEPENDENT_ALNS_BACKEND,
        "final_repair_customer_count": int(final_repair_customer_count),
        "final_repair_customer_ids": final_repair_customer_ids,
        "final_repair_evaluations": int(final_repair_evaluations),
        "final_repair_violation_count": int(final_repair_violation_count),
        "locked_route_snapshots": [
            {
                "vehicle_id": snapshot.route.vehicle_id,
                "vehicle_type": snapshot.route.vehicle_type,
                "home_depot_id": snapshot.route.home_depot_id,
                "fixed_customer_order": list(snapshot.locked_customer_ids),
                "covered_customer_order": list(snapshot.covered_customer_ids),
                "route_sequence": list(snapshot.route.node_sequence),
                "state": dict(snapshot.state),
                "charging_actions": [asdict(action) for action in snapshot.charging_actions],
            }
            for snapshot in locked_route_snapshots.values()
        ],
        "dynamic_final_routes": [
            {
                "vehicle_id": route.vehicle_id,
                "vehicle_type": route.vehicle_type,
                "home_depot_id": route.home_depot_id,
                "node_sequence": list(route.node_sequence),
            }
            for route in dynamic_solution.routes
        ],
        "dynamic_final_control": {
            "scorer": "setp_solver.cost.evaluate",
            "total_cost": float(dynamic_metrics["total_cost"]),
            "total_carbon_kg": float(dynamic_metrics["E_total"]),
            "feasible": dynamic_feasible,
            "violations": violation_dicts(dynamic_violations),
        },
        "static_revealed_control": {
            "scorer": "setp_solver.cost.evaluate",
            "total_cost": float(static_metrics["total_cost"]),
            "total_carbon_kg": float(static_metrics["E_total"]),
            "feasible": static_feasible,
            "violations": violation_dicts(static_violations),
        },
        "information_cost": float(dynamic_metrics["total_cost"]) - float(static_metrics["total_cost"]),
    }
    final_failure = dynamic_final_failure_payload(dynamic_violations, static_violations, float(payload["information_cost"]))
    if final_failure:
        payload.update(final_failure)
    if output_json_path is not None:
        path = Path(output_json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def write_t9_dynamic_csv(report: dict[str, Any], csv_path: str | Path) -> None:
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(report["stage_rows"])
    fields = [
        "stage",
        "trigger_time",
        "trigger_reason",
        "event_counts",
        "frozen_routes",
        "stage_cost",
        "cumulative_cost",
        "cumulative_carbon_kg",
        "min_fairness_ratio",
        "feasible",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def dynamic_stage_failure_payload(stage_index: int, violations: list[Any]) -> dict[str, Any]:
    return {
        "gate": "HALT_E7_STAGE_CHECK",
        "first_bad_stage": int(stage_index),
        "violations": violation_dicts(violations),
    }


def dynamic_stage_failure_payload_for_test(stage_index: int, violations: list[Any]) -> dict[str, Any]:
    return dynamic_stage_failure_payload(stage_index, violations)


def dynamic_chunk_failure_payload(stage_index: int | str, violations: list[Any]) -> dict[str, Any]:
    return {
        "first_bad_stage": stage_index,
        "violations": violation_dicts(violations),
    }


def dynamic_final_failure_payload(dynamic_violations: list[Any], static_violations: list[Any], information_cost: float) -> dict[str, Any]:
    if dynamic_violations:
        return {
            "gate": "HALT_E7_FINAL_CHECK",
            "first_bad_stage": "dynamic_vs_static",
            "violations": violation_dicts(dynamic_violations),
        }
    if static_violations:
        return {
            "gate": "HALT_E7_STATIC_CHECK",
            "first_bad_stage": "dynamic_vs_static",
            "violations": violation_dicts(static_violations),
        }
    if float(information_cost) < -1e-6:
        return {
            "gate": "HALT_E7_NEGATIVE_INFORMATION_COST",
            "first_bad_stage": "dynamic_vs_static",
            "violations": [
                {
                    "constraint_type": "INFORMATION_COST",
                    "route_id": "",
                    "nodes": "",
                    "detail": f"information_cost {float(information_cost):.6f} < 0",
                    "severity": "hard",
                }
            ],
        }
    return {}


def dynamic_final_failure_payload_for_test(dynamic_violations: list[Any], static_violations: list[Any], information_cost: float) -> dict[str, Any]:
    return dynamic_final_failure_payload(dynamic_violations, static_violations, information_cost)


def violation_dicts(violations: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for violation in violations:
        constraint_type = getattr(violation, "type", "")
        route_id = getattr(violation, "vehicle_id", "")
        nodes = getattr(violation, "location", "")
        rows.append(
            {
                "constraint_type": constraint_type,
                "route_id": route_id,
                "nodes": nodes,
                "detail": getattr(violation, "detail", ""),
                "severity": getattr(violation, "severity", "hard"),
            }
        )
    return rows


def _halt_payload(
    schema_version: str,
    gate: str,
    bundle_dir: str | Path,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    stage_eval_budget: int,
    stage_max_runtime_seconds: float,
    settings: RollingParameters,
    events: list[DynamicEvent],
    rows: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    evaluations: int,
    started: float,
    failure: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "build_note": "v2026-06-13: R2 dynamic rolling halt with first failing stage violation details.",
        "gate": gate,
        "bundle_dir": str(Path(bundle_dir)),
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "stage_eval_budget": int(stage_eval_budget),
        "stage_max_runtime_seconds": float(stage_max_runtime_seconds),
        "evaluations": int(evaluations),
        "actual_evals": int(evaluations),
        "elapsed_seconds": time.perf_counter() - started,
        "parameters": asdict(settings),
        "trigger_count": len(rows),
        "event_count": len(events),
        "events": [asdict(event) for event in events],
        "stage_rows": rows,
        "assertions": assertions,
        "all_assertions_pass": False,
        **failure,
    }


def _read_dynamic_events(path: Path) -> list[DynamicEvent]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return [
            DynamicEvent(
                event_id=str(row.get("event_id", idx)),
                event_type=str(row["event_type"]),
                t_appear=float(row["t_appear"]),
                customer_id=str(row["customer_id"]),
                old_demand=float(row.get("old_demand", 0.0) or 0.0),
                new_demand=float(row.get("new_demand", 0.0) or 0.0),
                x=float(row.get("x", 0.0) or 0.0),
                y=float(row.get("y", 0.0) or 0.0),
                delta_demand=float(row.get("delta_demand", 0.0) or 0.0),
                old_ready_time=float(row.get("old_ready_time", 0.0) or 0.0),
                old_due_time=float(row.get("old_due_time", row.get("new_due_time", 0.0)) or 0.0),
                new_ready_time=float(row.get("new_ready_time", row.get("old_ready_time", 0.0)) or 0.0),
                new_due_time=float(row.get("new_due_time", row.get("old_due_time", 0.0)) or 0.0),
                time_window_action=str(row.get("time_window_action", "none") or "none"),
                demand_source=str(row.get("demand_source", "existing_customer") or "existing_customer"),
                time_window_source=str(row.get("time_window_source", "existing_customer") or "existing_customer"),
                donor_instance_id=str(row.get("donor_instance_id", "") or ""),
                donor_customer_id=str(row.get("donor_customer_id", "") or ""),
                source=str(row.get("source", "synthetic_overlay") or "synthetic_overlay"),
                seed=int(float(row.get("seed", 0) or 0)),
            )
            for idx, row in enumerate(reader, start=1)
        ]


def _build_trigger_batches(events: list[DynamicEvent], params: RollingParameters) -> list[dict[str, Any]]:
    sorted_events = sorted(events, key=lambda event: (float(event.t_appear), str(event.event_id)))
    batches: list[dict[str, Any]] = [{"stage": 0, "trigger_time": 0.0, "trigger_reason": "initial", "events": []}]
    cursor = 0
    last_trigger = 0.0
    stage = 1
    while cursor < len(sorted_events):
        deadline = last_trigger + float(params.delta_t_seconds)
        batch: list[DynamicEvent] = []
        while cursor < len(sorted_events) and float(sorted_events[cursor].t_appear) <= deadline:
            batch.append(sorted_events[cursor])
            cursor += 1
            if len(batch) >= int(params.q_bar):
                trigger_time = float(batch[-1].t_appear)
                batches.append({"stage": stage, "trigger_time": trigger_time, "trigger_reason": "q_bar", "events": batch})
                last_trigger = trigger_time
                stage += 1
                break
        else:
            if batch:
                batches.append({"stage": stage, "trigger_time": deadline, "trigger_reason": "delta_t", "events": batch})
                stage += 1
            last_trigger = deadline
            continue
        continue
    return batches


def _active_customer_ids_after_events(
    instance: Instance,
    events: list[DynamicEvent],
    trigger_time: float,
    already_served: set[str],
) -> set[str]:
    return _active_customer_ids(_instance_after_events(instance, events, trigger_time, already_served), already_served)


def _active_customer_ids(instance: Instance, already_served: set[str]) -> set[str]:
    return _legal_unserved_customer_ids(instance, already_served)


def _legal_unserved_customer_ids(instance: Instance, already_served: set[str]) -> set[str]:
    return {
        node.node_id
        for node in instance.nodes
        if node.node_type.lower() == "c" and node.node_id not in already_served and float(node.demand) > 1e-9
    }


def _instance_after_events(
    instance: Instance,
    events: list[DynamicEvent],
    trigger_time: float,
    already_served: set[str],
    frozen_nodes: dict[str, Node] | None = None,
) -> Instance:
    nodes_by_id = {node.node_id: node for node in instance.nodes}
    removed: set[str] = set()
    for event in sorted(events, key=lambda item: (float(item.t_appear), str(item.event_id))):
        if float(event.t_appear) > float(trigger_time) + 1e-9:
            continue
        event_type = event.event_type.lower()
        if event_type == "add":
            nodes_by_id[event.customer_id] = Node(
                node_id=event.customer_id,
                node_type="c",
                x=float(event.x),
                y=float(event.y),
                demand=float(event.new_demand),
                ready_time=float(event.new_ready_time),
                due_time=float(event.new_due_time),
                service_time=_default_customer_service_time(instance),
            )
            removed.discard(event.customer_id)
        elif event_type == "cancel":
            if event.customer_id not in already_served:
                removed.add(event.customer_id)
        elif event_type in {"demand_change", "change"}:
            node = nodes_by_id.get(event.customer_id)
            if node is not None and event.customer_id not in already_served:
                nodes_by_id[event.customer_id] = replace(node, demand=float(event.new_demand))
        elif event_type == "time_window_change":
            node = nodes_by_id.get(event.customer_id)
            if node is not None and event.customer_id not in already_served:
                nodes_by_id[event.customer_id] = replace(node, ready_time=float(event.new_ready_time), due_time=float(event.new_due_time))
    nodes = [node for node in nodes_by_id.values() if node.node_id not in removed]
    if frozen_nodes:
        # Served customers keep the demand/time-window the committed route was
        # planned against, overriding any later reversion to the original value.
        nodes = [frozen_nodes.get(node.node_id, node) for node in nodes]
    return _rebuild_instance_matrix(instance, nodes)


def _policy_decision_for_stage(
    policy_callback: RollingPolicyCallback | None,
    *,
    stage_index: int,
    trigger: float,
    stage_events: list[DynamicEvent],
    events: list[DynamicEvent],
    settings: RollingParameters,
    base_instance: Instance,
    effective_instance: Instance,
    active_ids: set[str],
    served_customers: set[str],
    committed_customer_ids: set[str] | None = None,
    previous_plan: Solution | None,
    previous_instance: Instance | None,
    pending_customer_ids: set[str] | None = None,
    mandatory_customer_ids: set[str] | None = None,
) -> RollingPolicyDecision:
    if policy_callback is None:
        return RollingPolicyDecision(mandatory_ids=set(mandatory_customer_ids or set()))
    active = {str(customer_id) for customer_id in active_ids}
    mandatory = {str(customer_id) for customer_id in (mandatory_customer_ids or set())}
    committed = {str(customer_id) for customer_id in (committed_customer_ids or set())}
    context = RollingPolicyContext(
        stage_index=int(stage_index),
        trigger_time=float(trigger),
        stage_events=list(stage_events),
        all_events=list(events),
        settings=settings,
        base_instance=base_instance,
        effective_instance=effective_instance,
        active_ids=set(active),
        pending_customer_ids=set(pending_customer_ids or set()),
        mandatory_customer_ids=set(mandatory),
        committed_customer_ids=set(committed),
        served_customers=set(served_customers),
        previous_plan=previous_plan,
        previous_instance=previous_instance,
    )
    decision = _coerce_policy_decision(policy_callback(context))
    return _normalize_policy_decision(decision, active, mandatory, committed | set(served_customers))


def _normalize_policy_decision(
    decision: RollingPolicyDecision,
    active_ids: set[str],
    mandatory_customer_ids: set[str],
    committed_customer_ids: set[str],
) -> RollingPolicyDecision:
    active = {str(customer_id) for customer_id in active_ids}
    committed = {str(customer_id) for customer_id in committed_customer_ids}
    mandatory = {str(customer_id) for customer_id in mandatory_customer_ids}
    if decision.mandatory_ids is not None:
        mandatory |= {str(customer_id) for customer_id in decision.mandatory_ids}
    legacy_active = _optional_id_set(decision.active_ids)
    plan_now = _optional_id_set(decision.plan_now_ids)
    defer = _optional_id_set(decision.defer_ids)
    if legacy_active is not None and plan_now is None and defer is None:
        plan_now = set(legacy_active)
    elif plan_now is None and defer is not None:
        plan_now = active - defer
    elif plan_now is None:
        plan_now = None
    if defer is None and plan_now is not None:
        defer = active - plan_now

    referenced = set()
    for ids in (legacy_active, plan_now, defer, mandatory):
        if ids is not None:
            referenced.update(ids)
    committed_references = referenced & committed
    if committed_references:
        raise ValueError(f"rolling policy referenced already committed customers: {sorted(committed_references)}")
    unknown = referenced - active
    if unknown:
        raise ValueError(f"rolling policy selected customers not active in this stage: {sorted(unknown)}")
    if plan_now is not None and defer is not None and plan_now & defer:
        raise ValueError(f"rolling policy lifecycle overlap between plan_now and defer: {sorted(plan_now & defer)}")
    if mandatory - active:
        raise ValueError(f"rolling policy mandatory customers not active in this stage: {sorted(mandatory - active)}")
    effective_plan_now = active if plan_now is None else plan_now
    deferred_mandatory = mandatory - effective_plan_now
    if deferred_mandatory:
        raise ValueError(f"rolling policy may not defer mandatory customers: {sorted(deferred_mandatory)}")
    if active and plan_now is not None and not plan_now:
        raise ValueError("rolling policy may not defer every active customer in a non-empty stage")
    return RollingPolicyDecision(
        active_ids=set(effective_plan_now) if (plan_now is not None or legacy_active is not None) else None,
        plan_now_ids=set(plan_now) if plan_now is not None else None,
        defer_ids=set(defer) if defer is not None else None,
        mandatory_ids=set(mandatory),
        initial_plan=decision.initial_plan,
        stage_eval_budget=decision.stage_eval_budget,
        stage_max_runtime_seconds=decision.stage_max_runtime_seconds,
        metadata=dict(decision.metadata),
    )


def _optional_id_set(ids: set[str] | list[str] | tuple[str, ...] | None) -> set[str] | None:
    if ids is None:
        return None
    return {str(customer_id) for customer_id in ids}


def _coerce_policy_decision(raw: RollingPolicyDecision | dict[str, Any] | None) -> RollingPolicyDecision:
    if raw is None:
        return RollingPolicyDecision()
    if isinstance(raw, RollingPolicyDecision):
        return raw
    if isinstance(raw, dict):
        active_ids = raw.get("active_ids", raw.get("active_customer_ids"))
        plan_now_ids = raw.get("plan_now_ids", raw.get("plan_now_customer_ids"))
        defer_ids = raw.get("defer_ids", raw.get("deferred_customer_ids"))
        mandatory_ids = raw.get("mandatory_ids", raw.get("mandatory_customer_ids"))
        metadata = dict(raw.get("metadata") or {})
        for key in ("action", "deferred_ids", "reserve_capacity_fraction", "preposition_depot_id"):
            if key in raw and key not in metadata:
                metadata[key] = raw[key]
        budget = raw.get("stage_eval_budget")
        runtime = raw.get("stage_max_runtime_seconds")
        return RollingPolicyDecision(
            active_ids={str(customer_id) for customer_id in active_ids} if active_ids is not None else None,
            plan_now_ids={str(customer_id) for customer_id in plan_now_ids} if plan_now_ids is not None else None,
            defer_ids={str(customer_id) for customer_id in defer_ids} if defer_ids is not None else None,
            mandatory_ids={str(customer_id) for customer_id in mandatory_ids} if mandatory_ids is not None else None,
            initial_plan=raw.get("initial_plan"),
            stage_eval_budget=int(budget) if budget is not None else None,
            stage_max_runtime_seconds=float(runtime) if runtime is not None else None,
            metadata=metadata,
        )
    raise TypeError(f"rolling policy returned unsupported decision type: {type(raw).__name__}")


def _run_stage_plan(
    bundle: Any,
    instance: Instance,
    active_ids: set[str],
    stage_bundle_dir: Path,
    *,
    seed: int,
    stage_eval_budget: int,
    stage_max_runtime_seconds: float,
    prices: PriceParameters | dict[str, float] | Any,
    initial_plan: Solution | None,
    reserved_charging_actions: list[ChargingAction] | tuple[ChargingAction, ...] = (),
    reserved_physical_vehicle_ids: set[str] | None = None,
    stage_start_time: float = 0.0,
) -> StagePlanResult:
    if not active_ids:
        empty = Solution()
        return StagePlanResult(
            empty,
            _subinstance_for_customers(instance, active_ids),
            0,
            True,
            [],
            INDEPENDENT_ALNS_BACKEND,
        )
    stage_instance = _instance_with_stage_clock(
        _subinstance_for_customers(instance, active_ids),
        stage_start_time,
    )
    stage_instance = _instance_with_available_fleet(
        stage_instance,
        reserved_physical_vehicle_ids or set(),
    )
    _write_dynamic_bundle(stage_bundle_dir, stage_instance, bundle.carbon_profile, {"source": "e7_stage_reoptimization"})
    initial_solution = (
        _filter_initial_plan(initial_plan, stage_instance, active_ids, prices=prices)
        if initial_plan is not None
        else None
    )
    if initial_solution is None:
        try:
            initial_solution = build_initial_solution(
                stage_instance,
                bundle.carbon_profile,
                prices,
                introduce_ev=False,
                require_charging_signal=False,
            )
        except ValueError as exc:
            violations = _diagnose_stage_construction_failure(stage_instance, active_ids, prices)
            if not violations:
                violations = [Violation(ROUTE_STRUCTURE, "", "stage_construction", str(exc))]
            return StagePlanResult(
                Solution(),
                stage_instance,
                0,
                False,
                violations,
                INDEPENDENT_ALNS_BACKEND,
            )
    run = run_resetp_alns(
        stage_bundle_dir,
        config=WinnerKernelConfig(
            seed=seed,
            eval_budget=stage_eval_budget,
            max_runtime_seconds=stage_max_runtime_seconds,
            require_charging_signal=False,
            carbon_aware_operators=False,
        ),
        initial_solution=initial_solution,
        prices=prices,
    )
    stage_solution = _remap_reserved_stage_vehicles(
        run["best_solution"],
        instance,
        reserved_physical_vehicle_ids or set(),
    )
    violations = check_solution(
        stage_solution,
        stage_instance,
        prices,
        dynamic_context=DynamicCheckContext(
            reserved_charging_actions=tuple(reserved_charging_actions),
            reserved_physical_vehicle_ids=tuple(sorted(reserved_physical_vehicle_ids or set())),
        ),
    )
    feasible = bool(run["feasible"] and not violations)
    return StagePlanResult(
        stage_solution,
        stage_instance,
        int(run["evaluations"]),
        feasible,
        violations,
        INDEPENDENT_ALNS_BACKEND,
    )


def _instance_with_stage_clock(instance: Instance, stage_start_time: float) -> Instance:
    start = float(stage_start_time)
    if start <= 0.0:
        return instance
    nodes = [
        replace(node, ready_time=max(float(node.ready_time), start))
        if node.node_type.lower() == "d"
        else node
        for node in instance.nodes
    ]
    return Instance(
        nodes=nodes,
        distance_matrix=[list(row) for row in instance.distance_matrix],
        diesel_l_per_meter=instance.diesel_l_per_meter,
        ev_kwh_per_meter=instance.ev_kwh_per_meter,
        unit_distance_cost_per_meter=instance.unit_distance_cost_per_meter,
        num_cv=instance.num_cv,
        num_ev=instance.num_ev,
    )


def _instance_with_available_fleet(
    instance: Instance,
    reserved_physical_vehicle_ids: set[str],
) -> Instance:
    reserved_cv = sum(1 for vehicle_id in reserved_physical_vehicle_ids if str(vehicle_id).upper().startswith("CV"))
    reserved_ev = sum(1 for vehicle_id in reserved_physical_vehicle_ids if str(vehicle_id).upper().startswith("EV"))
    available_cv = None if instance.num_cv is None else max(0, int(instance.num_cv) - reserved_cv)
    available_ev = None if instance.num_ev is None else max(0, int(instance.num_ev) - reserved_ev)
    return Instance(
        nodes=list(instance.nodes),
        distance_matrix=[list(row) for row in instance.distance_matrix],
        diesel_l_per_meter=instance.diesel_l_per_meter,
        ev_kwh_per_meter=instance.ev_kwh_per_meter,
        unit_distance_cost_per_meter=instance.unit_distance_cost_per_meter,
        num_cv=available_cv,
        num_ev=available_ev,
    )


def _diagnose_stage_construction_failure(
    instance: Instance,
    active_ids: set[str],
    prices: PriceParameters | dict[str, float] | Any,
) -> list[Violation]:
    depots = [node.node_id for node in instance.nodes if node.node_type.lower() == "d"]
    if not depots:
        return [Violation(ROUTE_STRUCTURE, "", "stage_construction", "stage instance has no depot")]
    violations: list[Violation] = []
    for index, customer_id in enumerate(sorted(active_ids), start=1):
        customer_instance = _subinstance_for_customers(instance, {customer_id})
        depot_id = depots[0]
        probe = Solution(
            routes=[Route(f"CV_DIAG{index}#T1", "cv", depot_id, [depot_id, customer_id, depot_id])]
        )
        violations.extend(check_solution(probe, customer_instance, prices))
    return violations


def _subinstance_for_customers(instance: Instance, customer_ids: set[str]) -> Instance:
    keep_ids = {
        node.node_id
        for node in instance.nodes
        if node.node_type.lower() in {"d", "f"} or (node.node_type.lower() == "c" and node.node_id in customer_ids)
    }
    return _rebuild_instance_matrix(instance, [node for node in instance.nodes if node.node_id in keep_ids])


def _remap_reserved_stage_vehicles(
    solution: Solution,
    instance: Instance,
    reserved_physical_vehicle_ids: set[str],
) -> Solution:
    """Keep a rolling-stage plan off vehicles whose promised route is frozen."""

    if not reserved_physical_vehicle_ids:
        return solution
    used = {
        physical_vehicle_id(route.vehicle_id)
        for route in solution.routes
        if physical_vehicle_id(route.vehicle_id) not in reserved_physical_vehicle_ids
    } | set(reserved_physical_vehicle_ids)
    vehicle_map: dict[str, str] = {}
    routes: list[Route] = []
    for route in solution.routes:
        old_physical = physical_vehicle_id(route.vehicle_id)
        if old_physical not in reserved_physical_vehicle_ids:
            routes.append(route)
            continue
        prefix = "EV" if route.vehicle_type.lower() == "ev" else "CV"
        declared_limit = instance.num_ev if prefix == "EV" else instance.num_cv
        limit = int(declared_limit) if declared_limit is not None else max(1, len(solution.routes) + len(reserved_physical_vehicle_ids))
        replacement = next(
            (f"{prefix}{index}" for index in range(1, limit + 1) if f"{prefix}{index}" not in used),
            None,
        )
        if replacement is None:
            # Leave the collision visible to the normal structure/fleet checks;
            # never invent a vehicle beyond the declared fleet.
            routes.append(route)
            continue
        used.add(replacement)
        trip_index = 1
        if "#T" in route.vehicle_id:
            try:
                trip_index = int(route.vehicle_id.rsplit("#T", 1)[1])
            except ValueError:
                trip_index = 1
        new_vehicle_id = route_trip_vehicle_id(replacement, trip_index)
        vehicle_map[route.vehicle_id] = new_vehicle_id
        routes.append(replace(route, vehicle_id=new_vehicle_id))
    actions = [
        replace(action, vehicle_id=vehicle_map.get(action.vehicle_id, action.vehicle_id))
        for action in solution.charging_actions
    ]
    return Solution(
        routes=routes,
        charging_actions=actions,
        cross_site_services=list(solution.cross_site_services),
    )


def _write_dynamic_bundle(path: Path, instance: Instance, carbon_profile: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    effective_metadata = dict(metadata)
    if instance.num_cv is not None:
        effective_metadata.setdefault("num_cv", int(instance.num_cv))
    if instance.num_ev is not None:
        effective_metadata.setdefault("num_ev", int(instance.num_ev))
    payload = {
        "scenario_id": path.name,
        "seed": 0,
        "nodes": [_node_payload(node) for node in instance.nodes],
        "distance_unit": "meter",
        "time_unit": "second",
        "demand_unit": "kg",
        "metadata": effective_metadata,
    }
    (path / "instance.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    np.save(path / "distance_matrix.npy", np.asarray(instance.distance_matrix, dtype=float))
    _write_carbon_profile(path / "carbon_profile.csv", carbon_profile)


def _write_carbon_profile(path: Path, carbon_profile: list[dict[str, Any]]) -> None:
    if not carbon_profile:
        raise ValueError("carbon_profile is required")
    fields = list(carbon_profile[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(carbon_profile)


def _node_payload(node: Node) -> dict[str, Any]:
    data = asdict(node)
    if data.get("charge_power_kw") is None:
        data.pop("charge_power_kw", None)
    if data.get("station_chargers") is None:
        data.pop("station_chargers", None)
    return data


def _filter_initial_plan(
    plan: Solution | None,
    instance: Instance,
    active_ids: set[str],
    *,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> Solution | None:
    if plan is None:
        return None
    node_ids = {node.node_id for node in instance.nodes}
    routes: list[Route] = []
    vehicle_map: dict[str, str] = {}
    for route in plan.routes:
        customers = [node_id for node_id in route.node_sequence if node_id in active_ids]
        if not customers or route.home_depot_id not in node_ids:
            continue
        seq = [route.home_depot_id, *customers, route.home_depot_id]
        if all(node_id in node_ids for node_id in seq):
            vehicle_id = route.vehicle_id
            vehicle_map[route.vehicle_id] = vehicle_id
            routes.append(Route(vehicle_id, route.vehicle_type, route.home_depot_id, seq))
    if not routes:
        return None
    actions = [
        replace(action, vehicle_id=vehicle_map[action.vehicle_id])
        for action in plan.charging_actions
        if action.vehicle_id in vehicle_map and action.station_id in node_ids
    ]
    candidate = Solution(routes=routes, charging_actions=actions)
    return candidate if not check_solution(candidate, instance, prices) else None


def _commit_executed_customers(plan: Solution | None, instance: Instance, trigger_time: float, already_served: set[str]) -> set[str]:
    if plan is None:
        return set()
    served: set[str] = set()
    node_lookup = {node.node_id: node for node in instance.nodes}
    for route in plan.routes:
        try:
            schedule = route_node_schedule(route, instance)
        except Exception:
            continue
        for row in schedule:
            node = node_lookup.get(row.node_id)
            if node is None or node.node_type.lower() != "c" or row.node_id in already_served:
                continue
            if float(row.t_start) <= float(trigger_time) + 1e-9:
                served.add(row.node_id)
    return served


def _committed_not_completed_customers(
    plan: Solution | None,
    instance: Instance,
    *,
    trigger_time: float,
    commitment_deadline: float,
    already_served: set[str],
) -> set[str]:
    if plan is None:
        return set()
    node_lookup = {node.node_id: node for node in instance.nodes}
    committed: set[str] = set()
    for route in plan.routes:
        try:
            schedule = route_node_schedule(route, instance)
        except Exception:
            continue
        for row in schedule:
            node = node_lookup.get(row.node_id)
            if node is None or node.node_type.lower() != "c" or row.node_id in already_served:
                continue
            if float(trigger_time) < float(row.t_start) <= float(commitment_deadline) + 1e-9:
                committed.add(row.node_id)
    return committed


def _charging_actions_started_by(plan: Solution | None, trigger_time: float) -> list[ChargingAction]:
    if plan is None:
        return []
    return [
        action
        for action in plan.charging_actions
        if float(action.charge_start_second) <= float(trigger_time) + 1e-9
    ]


def _in_progress_physical_vehicle_deadlines(
    plan: Solution | None,
    instance: Instance,
    *,
    trigger_time: float,
    prices: PriceParameters | dict[str, float] | Any,
) -> dict[str, float]:
    if plan is None:
        return {}
    deadlines: dict[str, float] = {}
    for route in plan.routes:
        try:
            schedule = route_node_schedule(
                route,
                instance,
                prices,
                charging_actions=plan.charging_actions,
            )
        except Exception:
            continue
        if not schedule:
            continue
        route_start = float(schedule[0].t_depart)
        route_end = float(schedule[-1].t_arrive)
        if route_start <= float(trigger_time) + 1e-9 < route_end - 1e-9:
            physical_id = physical_vehicle_id(route.vehicle_id)
            deadlines[physical_id] = max(route_end, deadlines.get(physical_id, 0.0))
    return deadlines


def _charging_action_key(action: ChargingAction) -> tuple[Any, ...]:
    return (
        str(action.vehicle_id),
        str(action.station_id),
        round(float(action.charge_start_second), 9),
        round(float(action.occupancy_minutes), 9),
        round(float(action.energy_kwh), 9),
    )


def _locked_route_snapshots(
    plan: Solution | None,
    instance: Instance,
    locked_customer_ids: set[str],
    served_customer_ids: set[str],
    *,
    trigger_time: float,
    prices: PriceParameters | dict[str, float] | Any,
) -> list[LockedRouteSnapshot]:
    """Freeze promised customers without turning finalisation into a new solve."""

    if plan is None or not locked_customer_ids:
        return []
    node_lookup = {node.node_id: node for node in instance.nodes}
    snapshots: list[LockedRouteSnapshot] = []
    for route in plan.routes:
        locked_positions = [
            index
            for index, node_id in enumerate(route.node_sequence)
            if node_id in locked_customer_ids
        ]
        if not locked_positions:
            continue
        last_locked_index = max(locked_positions)
        keep_customers = locked_customer_ids | served_customer_ids
        sequence = [
            node_id
            for node_id in route.node_sequence[: last_locked_index + 1]
            if node_lookup[node_id].node_type.lower() != "c" or node_id in keep_customers
        ]
        if not sequence or sequence[0] != route.home_depot_id:
            sequence.insert(0, route.home_depot_id)
        if sequence[-1] != route.home_depot_id:
            sequence.append(route.home_depot_id)
        frozen_route = Route(route.vehicle_id, route.vehicle_type, route.home_depot_id, sequence)
        schedule = route_node_schedule(route, instance, prices, charging_actions=plan.charging_actions)
        locked_order = tuple(
            node_id
            for node_id in route.node_sequence
            if node_id in locked_customer_ids
        )
        covered_order = tuple(
            node_id
            for node_id in sequence
            if node_lookup[node_id].node_type.lower() == "c"
        )
        final_locked_time = max(
            row.t_depart for row in schedule if row.node_id in locked_customer_ids
        )
        actions = tuple(
            action
            for action in plan.charging_actions
            if action.vehicle_id == route.vehicle_id
            and action.station_id in sequence
            and float(action.charge_start_second) <= float(final_locked_time) + 1e-9
        )
        snapshots.append(
            LockedRouteSnapshot(
                route=frozen_route,
                charging_actions=actions,
                locked_customer_ids=locked_order,
                covered_customer_ids=covered_order,
                state=_vehicle_state_at_time(
                    route,
                    instance,
                    plan.charging_actions,
                    trigger_time=trigger_time,
                    prices=prices,
                ),
            )
        )
    return snapshots


def _vehicle_state_at_time(
    route: Route,
    instance: Instance,
    charging_actions: list[ChargingAction],
    *,
    trigger_time: float,
    prices: PriceParameters | dict[str, float] | Any,
) -> dict[str, Any]:
    """Return an audit state that distinguishes waiting at a node from travel."""

    schedule = route_node_schedule(route, instance, prices, charging_actions=charging_actions)
    node_lookup = {node.node_id: node for node in instance.nodes}
    location: dict[str, Any] = {
        "location_kind": "node",
        "position_node_id": route.node_sequence[0],
        "next_node_id": None,
        "arc_progress": 0.0,
    }
    for index, row in enumerate(schedule):
        if float(row.t_arrive) - 1e-9 <= trigger_time <= float(row.t_depart) + 1e-9:
            location.update(position_node_id=row.node_id, next_node_id=None, arc_progress=0.0)
            break
        if index + 1 < len(schedule) and float(row.t_depart) < trigger_time < float(schedule[index + 1].t_arrive):
            duration = float(schedule[index + 1].t_arrive) - float(row.t_depart)
            progress = (trigger_time - float(row.t_depart)) / duration if duration > 0.0 else 1.0
            location.update(
                location_kind="arc",
                position_node_id=row.node_id,
                next_node_id=schedule[index + 1].node_id,
                arc_progress=max(0.0, min(1.0, progress)),
            )
            break
        if trigger_time > float(row.t_depart):
            location.update(position_node_id=row.node_id, next_node_id=None, arc_progress=0.0)

    remaining_load = sum(
        float(node_lookup[row.node_id].demand)
        for row in schedule
        if node_lookup[row.node_id].node_type.lower() == "c" and float(row.t_start) > trigger_time + 1e-9
    )
    remaining_battery = 0.0
    if route.vehicle_type.lower() == "ev":
        remaining_battery = _price(prices, "initial_ev_battery_kwh")
        loads = _arc_loads(route.node_sequence, node_lookup)
        for index, (from_id, to_id) in enumerate(zip(route.node_sequence, route.node_sequence[1:])):
            depart = float(schedule[index].t_depart)
            arrive = float(schedule[index + 1].t_arrive)
            if trigger_time <= depart:
                fraction = 0.0
            elif trigger_time >= arrive or arrive <= depart:
                fraction = 1.0
            else:
                fraction = (trigger_time - depart) / (arrive - depart)
            remaining_battery -= fraction * ev_arc_energy_kwh(instance.distance(from_id, to_id), loads[index], prices)
        for action in charging_actions:
            if action.vehicle_id != route.vehicle_id:
                continue
            start = float(action.charge_start_second)
            end = start + float(action.occupancy_minutes) * 60.0
            if trigger_time <= start:
                fraction = 0.0
            elif trigger_time >= end or end <= start:
                fraction = 1.0
            else:
                fraction = (trigger_time - start) / (end - start)
            remaining_battery += fraction * float(action.energy_kwh)
        remaining_battery = min(_price(prices, "B_battery_kwh"), remaining_battery)
    ongoing = [
        asdict(action)
        for action in charging_actions
        if action.vehicle_id == route.vehicle_id
        and float(action.charge_start_second) <= trigger_time
        < float(action.charge_start_second) + float(action.occupancy_minutes) * 60.0
    ]
    return {
        "vehicle_id": route.vehicle_id,
        "vehicle_type": route.vehicle_type,
        "home_depot_id": route.home_depot_id,
        "current_time": float(trigger_time),
        "remaining_load_kg": float(remaining_load),
        "remaining_battery_kwh": float(remaining_battery),
        "ongoing_charging_actions": ongoing,
        **location,
    }


def _merge_final_plans(
    locked_routes: list[Route],
    locked_actions: list[ChargingAction],
    executed_plan: Solution,
    open_plan: Solution,
    instance: Instance,
    *,
    forbidden_open_customer_ids: set[str],
) -> Solution:
    """Assemble the execution ledger without running or repairing a solver."""

    node_lookup = {node.node_id: node for node in instance.nodes}
    open_routes: list[Route] = []
    open_vehicle_ids: set[str] = set()
    for route in open_plan.routes:
        sequence = [
            node_id
            for node_id in route.node_sequence
            if node_id in node_lookup
            and not (
                node_lookup[node_id].node_type.lower() == "c"
                and node_id in forbidden_open_customer_ids
            )
        ]
        customer_ids = [node_id for node_id in sequence if node_lookup[node_id].node_type.lower() == "c"]
        if not customer_ids:
            continue
        if sequence[0] != route.home_depot_id:
            sequence.insert(0, route.home_depot_id)
        if sequence[-1] != route.home_depot_id:
            sequence.append(route.home_depot_id)
        open_routes.append(Route(route.vehicle_id, route.vehicle_type, route.home_depot_id, sequence))
        open_vehicle_ids.add(route.vehicle_id)
    open_actions = [
        action
        for action in open_plan.charging_actions
        if action.vehicle_id in open_vehicle_ids
        and any(action.station_id in route.node_sequence for route in open_routes if route.vehicle_id == action.vehicle_id)
    ]
    actions: list[ChargingAction] = []
    seen_actions: set[tuple[Any, ...]] = set()
    for action in [*locked_actions, *executed_plan.charging_actions, *open_actions]:
        key = _charging_action_key(action)
        if key not in seen_actions:
            seen_actions.add(key)
            actions.append(action)
    return Solution(
        routes=[*locked_routes, *executed_plan.routes, *open_routes],
        charging_actions=actions,
        cross_site_services=[*executed_plan.cross_site_services, *open_plan.cross_site_services],
    )


def _solution_for_committed_customers(
    plan: Solution | None,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    customer_ids: set[str],
    *,
    prefix: str,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> Solution:
    _ = carbon_profile, prices
    if plan is None or not customer_ids:
        return Solution()
    node_lookup = {node.node_id: node for node in instance.nodes}
    routes: list[Route] = []
    vehicle_map: dict[str, str] = {}
    kept_nodes_by_vehicle: dict[str, set[str]] = {}
    for route in plan.routes:
        committed_positions = [idx for idx, node_id in enumerate(route.node_sequence) if node_id in customer_ids and node_id in node_lookup]
        if not committed_positions or route.home_depot_id not in node_lookup:
            continue
        last_committed_idx = max(committed_positions)
        sequence: list[str] = []
        for node_id in route.node_sequence[: last_committed_idx + 1]:
            node = node_lookup.get(node_id)
            if node is None:
                continue
            if node.node_type.lower() == "c" and node_id not in customer_ids:
                continue
            sequence.append(node_id)
        if not sequence or sequence[0] != route.home_depot_id:
            sequence.insert(0, route.home_depot_id)
        if sequence[-1] != route.home_depot_id:
            sequence.append(route.home_depot_id)
        vehicle_id = f"{prefix}{len(routes) + 1}_{route.vehicle_id}"
        vehicle_map[route.vehicle_id] = vehicle_id
        kept_nodes_by_vehicle[route.vehicle_id] = set(sequence)
        routes.append(Route(vehicle_id, route.vehicle_type.lower(), route.home_depot_id, sequence))
    actions = [
        replace(action, vehicle_id=vehicle_map[action.vehicle_id])
        for action in plan.charging_actions
        if action.vehicle_id in vehicle_map and action.station_id in kept_nodes_by_vehicle.get(action.vehicle_id, set())
    ]
    return Solution(routes=routes, charging_actions=actions)


def _solution_for_customer_subset(
    plan: Solution | None,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    customer_ids: set[str],
    *,
    prefix: str,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> Solution:
    if plan is None or not customer_ids:
        return Solution()
    node_lookup = {node.node_id: node for node in instance.nodes}
    routes: list[Route] = []
    actions: list[ChargingAction] = []
    for route in plan.routes:
        customers = [node_id for node_id in route.node_sequence if node_id in customer_ids and node_id in node_lookup]
        if not customers:
            continue
        if route.home_depot_id not in node_lookup:
            continue
        for group in _capacity_feasible_groups(customers, node_lookup, prices):
            vehicle_id = f"{prefix}{len(routes) + 1}_{route.vehicle_id}"
            base_route = Route(vehicle_id, route.vehicle_type.lower(), route.home_depot_id, [route.home_depot_id, *group, route.home_depot_id])
            if base_route.vehicle_type == "ev":
                repaired_route, route_actions = repair_route_charging(base_route, instance, carbon_profile, prices)
                routes.append(repaired_route)
                actions.extend(route_actions)
            else:
                routes.append(base_route)
    return Solution(routes=routes, charging_actions=actions)


def _capacity_feasible_groups(
    customer_ids: list[str],
    node_lookup: dict[str, Node],
    prices: PriceParameters | dict[str, float] | Any,
) -> list[list[str]]:
    capacity = _price(prices, "Q_capacity")
    groups: list[list[str]] = []
    current: list[str] = []
    current_load = 0.0
    for customer_id in customer_ids:
        demand = float(node_lookup[customer_id].demand)
        if current and current_load + demand > capacity + 1e-9:
            groups.append(current)
            current = []
            current_load = 0.0
        current.append(customer_id)
        current_load += demand
    if current:
        groups.append(current)
    return groups


def _classify_defer_eligibility(
    instance: Instance,
    active_ids: set[str],
    *,
    trigger_time: float,
    next_trigger_time: float,
    pending_customer_ids: set[str] | None = None,
    pending_age_by_customer: dict[str, int] | None = None,
    max_pending_stages: int = 2,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> DeferEligibilityResult:
    node_lookup = {node.node_id: node for node in instance.nodes}
    mandatory: set[str] = set()
    reasons: dict[str, str] = {}
    pending = {str(customer_id) for customer_id in (pending_customer_ids or set())}
    ages = {str(customer_id): int(age) for customer_id, age in (pending_age_by_customer or {}).items()}
    capacity = _price(prices, "Q_capacity")
    for customer_id in sorted(str(customer_id) for customer_id in active_ids):
        node = node_lookup.get(customer_id)
        if node is None or node.node_type.lower() != "c":
            continue
        reason = ""
        if float(node.demand) > capacity + 1e-9:
            reason = "capacity_upper_bound_infeasible"
        elif float(node.due_time) <= float(next_trigger_time) + 1e-9:
            reason = "due_before_next_stage"
        elif not _direct_depot_service_feasible(instance, node, float(trigger_time), prices):
            reason = "direct_depot_infeasible_now"
        elif customer_id in pending and ages.get(customer_id, 0) >= int(max_pending_stages):
            reason = "pending_age_limit"
        if reason:
            mandatory.add(customer_id)
            reasons[customer_id] = reason
    active = {str(customer_id) for customer_id in active_ids}
    return DeferEligibilityResult(
        mandatory_ids=mandatory,
        defer_eligible_ids=active - mandatory,
        reasons=reasons,
        proxy_notes={"ev_soc": "proxy_not_real_soc_guard"},
    )


def _direct_depot_service_feasible(
    instance: Instance,
    customer: Node,
    trigger_time: float,
    prices: PriceParameters | dict[str, float] | Any,
) -> bool:
    depots = [node for node in instance.nodes if node.node_type.lower() == "d"]
    if not depots:
        return False
    speed = max(1e-9, _price(prices, "v_speed_ms"))
    for depot in depots:
        try:
            out = instance.distance(depot.node_id, customer.node_id) / speed
            back = instance.distance(customer.node_id, depot.node_id) / speed
        except KeyError:
            continue
        service_start = max(float(trigger_time) + out, float(customer.ready_time))
        service_depart = service_start + float(customer.service_time)
        return_time = service_depart + back
        if service_start <= float(customer.due_time) + 1e-9 and return_time <= float(depot.due_time) + 1e-9:
            return True
    return False


def _solution_customer_ids(solution: Solution, instance: Instance) -> set[str]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    return {
        node_id
        for route in solution.routes
        for node_id in route.node_sequence
        if node_lookup.get(node_id) is not None and node_lookup[node_id].node_type.lower() == "c"
    }


def _frozen_route_sequences_from_routes(routes: list[Route]) -> dict[str, list[str]]:
    return {route.vehicle_id: list(route.node_sequence) for route in routes}


def _rebuild_instance_matrix(source: Instance, nodes: list[Node]) -> Instance:
    source_index = source.node_index
    matrix: list[list[float]] = []
    for from_node in nodes:
        row: list[float] = []
        for to_node in nodes:
            if from_node.node_id in source_index and to_node.node_id in source_index:
                row.append(float(source.distance(from_node.node_id, to_node.node_id)))
            else:
                row.append(float(((from_node.x - to_node.x) ** 2 + (from_node.y - to_node.y) ** 2) ** 0.5))
        matrix.append(row)
    return Instance(
        nodes=nodes,
        distance_matrix=matrix,
        diesel_l_per_meter=source.diesel_l_per_meter,
        ev_kwh_per_meter=source.ev_kwh_per_meter,
        unit_distance_cost_per_meter=source.unit_distance_cost_per_meter,
        num_cv=source.num_cv,
        num_ev=source.num_ev,
    )


def _default_customer_service_time(instance: Instance) -> float:
    values = [float(node.service_time) for node in instance.nodes if node.node_type.lower() == "c"]
    return sum(values) / len(values) if values else 0.0


def _feasible_event_window(
    instance: Instance,
    x: float,
    y: float,
    t_appear: float,
    preferred_ready: float,
    preferred_due: float,
) -> tuple[float, float]:
    """Keep donor coordinates but validate inherited time-window fields.

    v2026-06-12: W2b add events preserve donor geography, while ready/due are
    clamped to a direct depot-customer-depot service window in the current
    scenario so synthetic requests can enter the rolling optimizer.
    """

    depots = [node for node in instance.nodes if node.node_type.lower() == "d"]
    service = _default_customer_service_time(instance)
    speed = float(getattr(DEFAULT_PRICES, "v_speed_ms"))
    best: tuple[float, float] | None = None
    for depot in depots:
        distance = float(((float(depot.x) - float(x)) ** 2 + (float(depot.y) - float(y)) ** 2) ** 0.5)
        travel = distance / speed
        earliest = max(float(t_appear), float(depot.ready_time) + travel)
        latest = float(depot.due_time) - service - travel
        if latest + 1e-9 < earliest:
            continue
        width = max(0.0, min(float(preferred_due), latest) - max(float(preferred_ready), earliest))
        candidate = (width, earliest, latest)
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        horizon = max((float(depot.due_time) for depot in depots), default=max(float(preferred_due), float(t_appear) + 1.0))
        ready = min(float(t_appear), max(0.0, horizon - service))
        return ready, max(ready, horizon)
    _, earliest, latest = best
    ready = max(float(t_appear), min(max(float(preferred_ready), earliest), latest))
    due = max(ready, min(max(float(preferred_due), ready), latest))
    return ready, due


def _sibling_add_donors(bundle_dir: Path, instance: Instance) -> list[Node]:
    current_xy = {(round(node.x, 3), round(node.y, 3)) for node in instance.nodes if node.node_type.lower() == "c"}
    donors: list[Node] = []
    parent = bundle_dir.parent
    if not parent.exists():
        return donors
    for candidate in sorted(parent.iterdir()):
        if candidate == bundle_dir or not (candidate / "instance.json").exists():
            continue
        try:
            sibling = load_search_bundle(candidate).instance
        except Exception:
            continue
        for node in sibling.nodes:
            if node.node_type.lower() != "c":
                continue
            key = (round(node.x, 3), round(node.y, 3))
            if key in current_xy:
                continue
            donors.append(node)
            if len(donors) >= 200:
                return donors
    return donors


def _event_count_string(events: list[DynamicEvent]) -> str:
    counts = {"add": 0, "cancel": 0, "change": 0}
    for event in events:
        if event.event_type == "add":
            counts["add"] += 1
        elif event.event_type == "cancel":
            counts["cancel"] += 1
        else:
            counts["change"] += 1
    return f"{counts['add']}/{counts['cancel']}/{counts['change']}"


def _format_hour(second: float) -> str:
    hour = int(second // 3600)
    minute = int((second % 3600) // 60)
    return f"{hour:02d}:{minute:02d}"


def _price(prices: PriceParameters | dict[str, float] | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))
