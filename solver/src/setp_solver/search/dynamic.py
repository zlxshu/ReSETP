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

from ..check import check_solution
from ..cost import evaluate, route_node_schedule
from ..instance_loader import Instance, Node
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import ChargingAction, Route, Solution
from .alns_wouda import run_alns_wouda
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


@dataclass(frozen=True)
class RollingPolicyDecision:
    active_ids: set[str] | None = None
    initial_plan: Solution | None = None
    stage_eval_budget: int | None = None
    stage_max_runtime_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


RollingPolicyCallback = Callable[[RollingPolicyContext], RollingPolicyDecision | dict[str, Any] | None]


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
    committed_node_state: dict[str, Node] = {}
    frozen_sequences: dict[str, list[str]] = {}
    stage_plan_customer_ids: dict[str, list[str]] = {}
    policy_trace: list[dict[str, Any]] = []
    pending_deferred_ids: set[str] = set()

    for stage_index, batch in enumerate(batches):
        trigger = float(batch["trigger_time"])
        stage_events = list(batch["events"])
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

        stage_cost = cumulative_cost - initial_cost
        stage_carbon = cumulative_carbon - initial_carbon
        effective_instance = _instance_after_events(bundle.instance, events, trigger, served_customers)
        legal_unserved_ids = _legal_unserved_customer_ids(effective_instance, served_customers)
        pending_deferred_ids.intersection_update(legal_unserved_ids)
        pending_count_before = len(pending_deferred_ids)
        pending_ids_before = sorted(pending_deferred_ids)
        active_ids = set(_active_customer_ids(effective_instance, served_customers)) | set(pending_deferred_ids)
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
            pending_customer_ids=pending_deferred_ids,
            served_customers=served_customers,
            previous_plan=previous_plan,
            previous_instance=previous_instance,
        )
        stage_active_ids = set(active_ids if policy_decision.active_ids is None else policy_decision.active_ids)
        stage_initial_plan = previous_plan if policy_decision.initial_plan is None else policy_decision.initial_plan
        stage_budget = int(stage_eval_budget if policy_decision.stage_eval_budget is None else policy_decision.stage_eval_budget)
        stage_runtime = float(
            stage_max_runtime_seconds
            if policy_decision.stage_max_runtime_seconds is None
            else policy_decision.stage_max_runtime_seconds
        )
        deferred_ids = sorted(set(active_ids) - set(stage_active_ids))
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
        )
        total_evaluations += stage_plan.evaluations
        if stage_plan.violations:
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
                dynamic_stage_failure_payload(int(stage_index), stage_plan.violations),
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
                "pending_count_before": int(pending_count_before),
                "pending_count_after": int(pending_count_after),
                "new_deferred_count": len(deferred_ids),
                "newly_revealed_customer_count": sum(1 for event in stage_events if str(event.event_type).lower() == "add"),
                "committed_customer_count": len(served_customers),
                "stage_eval_budget_used": int(stage_budget),
                "frozen_routes": len(current_frozen),
                "stage_route_count": len(stage_solution.routes),
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
    final_instance = _instance_after_events(bundle.instance, events, final_trigger, served_customers, committed_node_state)
    pending_deferred_ids.intersection_update(_legal_unserved_customer_ids(final_instance, served_customers))
    remaining = set(_active_customer_ids(final_instance, served_customers)) | set(pending_deferred_ids)
    final_repair_customer_count = 0
    final_repair_evaluations = 0
    final_repair_violation_count = 0
    if remaining:
        final_repair_customer_count = len(remaining)
        final_repair = _run_stage_plan(
            bundle,
            final_instance,
            remaining,
            work_root / "final_repair",
            seed=seed + len(batches),
            stage_eval_budget=stage_eval_budget,
            stage_max_runtime_seconds=stage_max_runtime_seconds,
            prices=prices,
            initial_plan=previous_plan,
        )
        total_evaluations += final_repair.evaluations
        final_repair_evaluations = int(final_repair.evaluations)
        final_repair_violations = list(final_repair.violations)
        if not final_repair_violations:
            final_repair_violations = check_solution(
                final_repair.solution,
                _subinstance_for_customers(final_instance, remaining),
                prices,
            )
        final_repair_violation_count = len(final_repair_violations)
        if final_repair_violations:
            failure = dynamic_chunk_failure_payload("final_repair", final_repair_violations)
            failure.update(
                {
                    "final_repair_customer_count": int(final_repair_customer_count),
                    "final_repair_evaluations": int(final_repair_evaluations),
                    "final_repair_violation_count": int(final_repair_violation_count),
                    "policy_trace": policy_trace,
                }
            )
            payload = _halt_payload(
                "setp-dynamic-rolling.v3",
                "HALT_E7_FINAL_REPAIR_CHECK",
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
        committed_routes.extend(final_repair.solution.routes)
        committed_actions.extend(final_repair.solution.charging_actions)
        pending_deferred_ids.difference_update(_solution_customer_ids(final_repair.solution, final_instance))
    dynamic_solution = Solution(routes=committed_routes, charging_actions=committed_actions)

    final_bundle_dir = work_root / "full_information_static"
    _write_dynamic_bundle(final_bundle_dir, final_instance, bundle.carbon_profile, {"source": "e7_full_information_static"})
    static_run = run_alns_wouda(
        final_bundle_dir,
        iterations=None,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
    )
    total_evaluations += int(static_run.evaluations)
    dynamic_metrics = evaluate(dynamic_solution, final_instance, bundle.carbon_profile, prices)
    static_metrics = evaluate(static_run.best_solution, final_instance, bundle.carbon_profile, prices)
    dynamic_violations = check_solution(dynamic_solution, final_instance, prices)
    static_violations = check_solution(static_run.best_solution, final_instance, prices)
    dynamic_feasible = not dynamic_violations
    static_feasible = bool(static_run.feasible and not static_violations)
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
        "final_repair_customer_count": int(final_repair_customer_count),
        "final_repair_evaluations": int(final_repair_evaluations),
        "final_repair_violation_count": int(final_repair_violation_count),
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
    previous_plan: Solution | None,
    previous_instance: Instance | None,
    pending_customer_ids: set[str] | None = None,
) -> RollingPolicyDecision:
    if policy_callback is None:
        return RollingPolicyDecision()
    context = RollingPolicyContext(
        stage_index=int(stage_index),
        trigger_time=float(trigger),
        stage_events=list(stage_events),
        all_events=list(events),
        settings=settings,
        base_instance=base_instance,
        effective_instance=effective_instance,
        active_ids=set(active_ids),
        pending_customer_ids=set(pending_customer_ids or set()),
        served_customers=set(served_customers),
        previous_plan=previous_plan,
        previous_instance=previous_instance,
    )
    decision = _coerce_policy_decision(policy_callback(context))
    if decision.active_ids is None:
        return decision
    chosen = {str(customer_id) for customer_id in decision.active_ids}
    unknown = chosen - set(active_ids)
    if unknown:
        raise ValueError(f"rolling policy selected customers not active in this stage: {sorted(unknown)}")
    if active_ids and not chosen:
        raise ValueError("rolling policy may not defer every active customer in a non-empty stage")
    return RollingPolicyDecision(
        active_ids=chosen,
        initial_plan=decision.initial_plan,
        stage_eval_budget=decision.stage_eval_budget,
        stage_max_runtime_seconds=decision.stage_max_runtime_seconds,
        metadata=dict(decision.metadata),
    )


def _coerce_policy_decision(raw: RollingPolicyDecision | dict[str, Any] | None) -> RollingPolicyDecision:
    if raw is None:
        return RollingPolicyDecision()
    if isinstance(raw, RollingPolicyDecision):
        return raw
    if isinstance(raw, dict):
        active_ids = raw.get("active_ids", raw.get("active_customer_ids"))
        metadata = dict(raw.get("metadata") or {})
        for key in ("action", "deferred_ids", "reserve_capacity_fraction", "preposition_depot_id"):
            if key in raw and key not in metadata:
                metadata[key] = raw[key]
        budget = raw.get("stage_eval_budget")
        runtime = raw.get("stage_max_runtime_seconds")
        return RollingPolicyDecision(
            active_ids={str(customer_id) for customer_id in active_ids} if active_ids is not None else None,
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
) -> StagePlanResult:
    if not active_ids:
        empty = Solution()
        return StagePlanResult(empty, _subinstance_for_customers(instance, active_ids), 0, True, [])
    stage_instance = _subinstance_for_customers(instance, active_ids)
    _write_dynamic_bundle(stage_bundle_dir, stage_instance, bundle.carbon_profile, {"source": "e7_stage_reoptimization"})
    initial_solution = _filter_initial_plan(initial_plan, stage_instance, active_ids) if initial_plan is not None else None
    if initial_solution is None:
        initial_solution = build_initial_solution(stage_instance, bundle.carbon_profile, prices, introduce_ev=False, require_charging_signal=False)
    run = run_alns_wouda(
        stage_bundle_dir,
        iterations=None,
        seed=seed,
        eval_budget=stage_eval_budget,
        max_runtime_seconds=stage_max_runtime_seconds,
        initial_solution=initial_solution,
    )
    violations = check_solution(run.best_solution, stage_instance, prices)
    feasible = bool(run.feasible and not violations)
    return StagePlanResult(run.best_solution, stage_instance, int(run.evaluations), feasible, violations)


def _subinstance_for_customers(instance: Instance, customer_ids: set[str]) -> Instance:
    keep_ids = {
        node.node_id
        for node in instance.nodes
        if node.node_type.lower() in {"d", "f"} or (node.node_type.lower() == "c" and node.node_id in customer_ids)
    }
    return _rebuild_instance_matrix(instance, [node for node in instance.nodes if node.node_id in keep_ids])


def _write_dynamic_bundle(path: Path, instance: Instance, carbon_profile: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    payload = {
        "scenario_id": path.name,
        "seed": 0,
        "nodes": [_node_payload(node) for node in instance.nodes],
        "distance_unit": "meter",
        "time_unit": "second",
        "demand_unit": "kg",
        "metadata": metadata,
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


def _filter_initial_plan(plan: Solution | None, instance: Instance, active_ids: set[str]) -> Solution | None:
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
            vehicle_id = f"R{len(routes) + 1}_{route.vehicle_id}"
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
    return candidate if not check_solution(candidate, instance) else None


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
