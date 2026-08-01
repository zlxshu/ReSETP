#!/usr/bin/env python3
"""Run one approved 50-customer E7 trigger pilot stream."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for entry in (ROOT, ROOT / "solver/src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from baselines.china_e3_e7.e3_scattered_ownership_20260801.shared_runtime import (
    load_bundle,
)
from baselines.china_e3_e7.e7_trigger_policies_20260801.dynamic_adapter import (
    PlanAttempt,
    admit_new_orders_or_reject_individually,
    inject_full_fleet_asset_states,
)
from baselines.china_e3_e7.e7_trigger_policies_20260801.trigger_policies import (
    FIXED_30_MINUTES,
    HYBRID_500KG_OR_30_MINUTES,
    PER_ORDER,
    RECEPTION_END_SECOND,
    DynamicOrder,
    DynamicStream,
    TriggerBatch,
    build_qiu_scaled_stream,
    build_trigger_batches,
    dynamic_stream_sha256,
)
from baselines.china_instances.build_china81_finite_fleet_authority_v1_20260723 import (
    _pack_depot,
)
from baselines.e7_dynamic import e7_full_mechanism_probe_20260714 as probe
from setp_solver.check import check_solution
from setp_solver.china81_completion import complete_china81_route_skeleton
from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance, RoadProfileMatrices
from setp_solver.search.bundle import SearchBundle
from setp_solver.search.dynamic_multitrip_schedule import (
    CertificateCut,
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
    validate_dynamic_multitrip_certificate,
)
from setp_solver.search.evaluation import score_reference
from setp_solver.search.multitrip_schedule import (
    prepare_multitrip_solution,
    validate_multitrip_certificate,
)
from setp_solver.solution import Route, Solution, physical_vehicle_id


INSTANCE_ID = "cn-prd-50c-01-V2-LOCATIONS"
DEFAULT_STREAM_SEED = 1
REVENUE_PER_KG = 1.5
STAGE_EVALUATIONS = 8
POLICIES = (PER_ORDER, FIXED_30_MINUTES, HYBRID_500KG_OR_30_MINUTES)
_FULL_INSTANCE: Instance | None = None


def default_output(stream_seed: int) -> Path:
    return HERE / f"pilot_50c_seed{stream_seed}_eval8_v1_20260801"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row}) if rows else ["status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows or [{"status": "NO_ROWS"}])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _customer_ids(solution: Solution, instance: Instance) -> list[str]:
    nodes = {node.node_id: node for node in instance.nodes}
    return [
        node_id
        for route in solution.routes
        for node_id in route.node_sequence
        if node_id in nodes and nodes[node_id].node_type.lower() == "c"
    ]


def _subset_instance(source: Instance, nodes: list[Any]) -> Instance:
    if _FULL_INSTANCE is None:
        raise RuntimeError("full road authority is not bound")
    authority = _FULL_INSTANCE
    index = authority.node_index
    ids = [node.node_id for node in nodes]
    matrix = [[float(authority.distance(left, right)) for right in ids] for left in ids]
    profiles = None
    if authority.road_profiles is not None:
        profiles = {
            name: RoadProfileMatrices(
                distance_m=tuple(
                    tuple(float(values.distance_m[index[left]][index[right]]) for right in ids)
                    for left in ids
                ),
                duration_s=tuple(
                    tuple(float(values.duration_s[index[left]][index[right]]) for right in ids)
                    for left in ids
                ),
                sum_v2d_m3_s2=tuple(
                    tuple(float(values.sum_v2d_m3_s2[index[left]][index[right]]) for right in ids)
                    for left in ids
                ),
            )
            for name, values in authority.road_profiles.items()
        }
    return replace(source, nodes=nodes, distance_matrix=matrix, road_profiles=profiles)


def _exact_instance_after_events(
    source: Instance,
    events: list[Any],
    trigger_time: float,
    served: set[str],
    frozen_nodes: dict[str, Any] | None = None,
) -> Instance:
    if _FULL_INSTANCE is None:
        raise RuntimeError("full event authority is not bound")
    authority = {node.node_id: node for node in _FULL_INSTANCE.nodes}
    current = {node.node_id: node for node in source.nodes}
    removed: set[str] = set()
    for event in sorted(events, key=lambda item: (float(item.t_appear), str(item.event_id))):
        if float(event.t_appear) > float(trigger_time) + 1.0e-9:
            continue
        event_type = event.event_type.lower()
        if event_type == "add":
            original = authority[event.customer_id]
            current[event.customer_id] = replace(
                original,
                node_type="c",
                demand=float(event.new_demand),
                ready_time=float(event.new_ready_time),
                due_time=float(event.new_due_time),
                service_time=float(event.new_service_time),
            )
            removed.discard(event.customer_id)
        elif event_type == "cancel":
            if event.customer_id not in served:
                removed.add(event.customer_id)
        elif event_type in {"demand_change", "change"}:
            if event.customer_id in current and event.customer_id not in served:
                current[event.customer_id] = replace(
                    current[event.customer_id], demand=float(event.new_demand)
                )
        else:
            raise RuntimeError(f"unsupported E7 event {event.event_type}")
    nodes = [node for node in current.values() if node.node_id not in removed]
    if frozen_nodes:
        nodes = [frozen_nodes.get(node.node_id, node) for node in nodes]
    return _subset_instance(source, nodes)


def _initial_plan(bundle: Any, stream: DynamicStream) -> tuple[Instance, Solution, Any, dict[str, Any]]:
    withheld = {
        event.customer_id for event in stream.events if isinstance(event, DynamicOrder)
    }
    initial_instance = replace(
        bundle.instance,
        nodes=[
            replace(node, node_type="inactive", demand=0.0)
            if node.node_id in withheld
            else node
            for node in bundle.instance.nodes
        ],
    )
    initial_bundle = replace(
        bundle,
        instance=initial_instance,
        customer_home_depot={
            customer_id: depot
            for customer_id, depot in bundle.customer_home_depot.items()
            if customer_id not in withheld
        },
    )
    routes: list[Route] = []
    for depot_id in sorted(bundle.fleet_caps_by_depot):
        groups = _pack_depot(initial_bundle, depot_id)
        routes.extend(
            Route(
                f"INITIAL-{depot_id}-{index:02d}",
                "cv",
                depot_id,
                [depot_id, *customer_ids, depot_id],
            )
            for index, customer_ids in enumerate(groups, start=1)
        )
    completed = complete_china81_route_skeleton(Solution(routes=routes), initial_bundle)
    violations = check_solution(completed.solution, initial_instance, bundle.prices)
    if violations:
        raise RuntimeError(f"initial 40-customer plan is illegal: {violations[0]}")
    plan, certificate = prepare_multitrip_solution(
        completed.solution, initial_instance, bundle.prices
    )
    return initial_instance, plan, certificate, completed.activity


def _full_assets(existing: Mapping[str, Any], bundle: Any, trigger: float) -> Mapping[str, Any]:
    return inject_full_fleet_asset_states(
        existing,
        bundle.fleet_caps_by_depot,
        available_second=trigger,
        unused_ev_battery_kwh=float(bundle.prices.initial_ev_battery_kwh),
    )


def _stage_plan(
    *,
    bundle: Any,
    sources: Mapping[str, Any],
    current_plan: Solution,
    current_instance: Instance,
    cut: CertificateCut,
    committed_customers: set[str],
    batch: TriggerBatch,
    events_by_id: Mapping[str, Any],
    stage_index: int,
    stream_seed: int,
    attempt_rows: list[dict[str, Any]],
) -> tuple[Any, dict[str, str]]:
    batch_events = [events_by_id[event_id] for event_id in batch.event_ids]
    additions = [event for event in batch_events if isinstance(event, DynamicOrder)]
    updates = [event for event in batch_events if not isinstance(event, DynamicOrder)]
    demand = {event.customer_id: event.demand_kg for event in additions}
    owners = dict(bundle.customer_home_depot)
    open_routes = probe.base.gate._cut_routes(current_plan, cut.editable_route_ids)

    def planner(selected: tuple[str, ...], _assets: Mapping[str, Any]) -> PlanAttempt:
        selected_set = set(selected)
        chosen = [*updates, *(event for event in additions if event.customer_id in selected_set)]
        started = time.perf_counter()
        try:
            construction = probe.base.gate.build_open_stage(
                open_routes,
                current_instance,
                [event.as_solver_event() for event in chosen],
                batch.trigger_second,
                committed_customers,
                owners,
                bundle.prices,
                stage_index=stage_index,
                isolate_changed_customers=True,
            )
            result = probe.base.search_stage(
                construction,
                sources,
                cut,
                owners,
                committed_customers,
                trigger=batch.trigger_second,
                seed=1000 + stream_seed,
                evaluations=STAGE_EVALUATIONS,
                allow_cross_depot=True,
                stage_new_customer_ids=tuple(sorted(selected_set)),
            )
            validate_dynamic_multitrip_certificate(
                result["solution"],
                result["certificate"],
                construction.effective_instance,
                bundle.prices,
                asset_states=cut.asset_states,
                stage_start_second=batch.trigger_second,
                locked_charging_actions=cut.locked_charging_actions,
            )
            attempt = PlanAttempt(
                True,
                payload=(construction, result),
                delivery_cost=float(result["future_cost"]),
            )
        except (probe.base.NoExecutableContinuation, ValueError) as exc:
            attempt = PlanAttempt(False, reason=f"{type(exc).__name__}: {exc}")
        attempt_rows.append(
            {
                "stage": stage_index,
                "trigger_second": batch.trigger_second,
                "selected_additions": "|".join(sorted(selected_set)),
                "selected_count": len(selected_set),
                "feasible": attempt.feasible,
                "delivery_cost_cny": attempt.delivery_cost if attempt.feasible else "NA",
                "reason": attempt.reason,
                "evaluations": STAGE_EVALUATIONS,
                "wall_seconds": time.perf_counter() - started,
            }
        )
        return attempt

    admission = admit_new_orders_or_reject_individually(
        (),
        [event.customer_id for event in additions],
        demand,
        revenue_per_kg=REVENUE_PER_KG,
        full_asset_states=cut.asset_states,
        planner=planner,
    )
    construction, result = admission.plan_payload
    status = {
        event.event_id: (
            "accepted"
            if event.customer_id in admission.accepted_customer_ids
            else "rejected"
        )
        for event in additions
    }
    status.update(
        {
            event.event_id: (
                "applied"
                if event.event_id in construction.applied_event_ids
                else "ignored_already_locked"
            )
            for event in updates
        }
    )
    return (admission, construction, result), status


def _summary(
    arm: str,
    solution: Solution,
    instance: Instance,
    bundle: Any,
    rejected_ids: set[str],
    lost_revenue: float,
    wall_seconds: float,
    evaluations: int,
    trigger_count: int,
    violations: Sequence[Any],
    validation_method: str,
    validated_stage_count: int,
) -> dict[str, Any]:
    customers = _customer_ids(solution, instance)
    if len(customers) != len(set(customers)):
        raise RuntimeError(f"{arm} serves a customer more than once")
    active = {
        node.node_id for node in instance.nodes if node.node_type.lower() == "c"
    }
    if set(customers) != active:
        raise RuntimeError(f"{arm} customer ledger does not close")
    metrics = evaluate(solution, instance, bundle.time_profile, bundle.prices)
    vehicles = {physical_vehicle_id(route.vehicle_id) for route in solution.routes}
    requested = len(customers) + len(rejected_ids)
    return {
        "arm": arm,
        "status": "PASS" if not violations else "HALT_CHECK",
        "trigger_count": trigger_count,
        "completed_customer_count": len(customers),
        "rejected_customer_count": len(rejected_ids),
        "rejected_customer_ids": "|".join(sorted(rejected_ids)),
        "completion_rate_pct": 100.0 * len(customers) / requested if requested else 100.0,
        "rejected_revenue_cny": lost_revenue,
        "delivery_cost_cny": float(metrics["total_cost"]),
        "total_cost_with_lost_revenue_cny": float(metrics["total_cost"]) + lost_revenue,
        "actual_vehicle_count": len(vehicles),
        "actual_cv_count": len({item for item in vehicles if item.startswith("CV_")}),
        "actual_ev_count": len({item for item in vehicles if item.startswith("EV_")}),
        "route_count": len(solution.routes),
        "charging_action_count": len(solution.charging_actions),
        "legal": not violations,
        "violation_count": len(violations),
        "violation_types": "|".join(item.type for item in violations),
        "validation_method": validation_method,
        "validated_stage_count": validated_stage_count,
        "evaluation_count": evaluations,
        "wall_seconds": wall_seconds,
    }


def _run_dynamic(
    policy: str,
    bundle: Any,
    stream: DynamicStream,
    initial_instance: Instance,
    initial_plan: Solution,
    initial_certificate: Any,
    sources: Mapping[str, Any],
    stream_seed: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    started = time.perf_counter()
    current_plan = initial_plan
    current_certificate = initial_certificate
    current_instance = initial_instance
    inherited_states = None
    inherited_locked = ()
    previous_trigger = None
    committed_routes: dict[str, Route] = {}
    committed_actions: dict[tuple[Any, ...], Any] = {}
    committed_customers: set[str] = set()
    route_history = {route.vehicle_id: route for route in current_plan.routes}
    rejected_ids: set[str] = set()
    lost_revenue = 0.0
    evaluations = 0
    stage_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    attempt_rows: list[dict[str, Any]] = []
    events_by_id = {event.event_id: event for event in stream.events}
    batches = build_trigger_batches(stream.events, policy)

    for stage_index, batch in enumerate(batches, start=1):
        if previous_trigger is None:
            cut = cut_certificate_at_trigger(
                current_plan,
                current_certificate,
                current_instance,
                bundle.prices,
                trigger_second=batch.trigger_second,
            )
            cut = replace(
                cut,
                asset_states=_full_assets(cut.asset_states, bundle, batch.trigger_second),
            )
        else:
            cut = cut_dynamic_certificate_at_trigger(
                current_plan,
                current_certificate,
                current_instance,
                bundle.prices,
                inherited_asset_states=inherited_states,
                previous_stage_start_second=previous_trigger,
                trigger_second=batch.trigger_second,
                inherited_locked_charging_actions=inherited_locked,
            )
        locked_ids = (*cut.completed_route_ids, *cut.in_progress_route_ids)
        for route in probe.base.gate._cut_routes(current_plan, locked_ids):
            committed_routes.setdefault(route.vehicle_id, route)
            committed_customers.update(probe.base.p2.route_customers(route, current_instance))
        for action in cut.locked_charging_actions:
            committed_actions.setdefault(probe.base.action_key(action), action)

        (admission, construction, result), event_status = _stage_plan(
            bundle=bundle,
            sources=sources,
            current_plan=current_plan,
            current_instance=current_instance,
            cut=cut,
            committed_customers=committed_customers,
            batch=batch,
            events_by_id=events_by_id,
            stage_index=stage_index,
            stream_seed=stream_seed,
            attempt_rows=attempt_rows,
        )
        rejected_ids.update(admission.rejected_customer_ids)
        lost_revenue += admission.rejected_revenue
        evaluations += admission.planner_call_count * STAGE_EVALUATIONS
        future_ids = _customer_ids(result["solution"], construction.effective_instance)
        active = {
            node.node_id
            for node in construction.effective_instance.nodes
            if node.node_type.lower() == "c"
        }
        if (
            len(future_ids) != len(set(future_ids))
            or committed_customers & set(future_ids)
            or committed_customers | set(future_ids) != active
        ):
            raise RuntimeError(f"{policy} stage {stage_index} customer ledger failed")
        running = probe._merge_execution_plan(
            committed_routes, committed_actions, result["solution"], route_history
        )
        running_cost = float(
            evaluate(
                running,
                construction.effective_instance,
                bundle.time_profile,
                bundle.prices,
            )["total_cost"]
        )
        used = {physical_vehicle_id(route.vehicle_id) for route in running.routes}
        stage_rows.append(
            {
                "arm": policy,
                "stage": stage_index,
                "trigger_second": batch.trigger_second,
                "trigger_cause": batch.cause,
                "event_ids": "|".join(batch.event_ids),
                "accepted_additions": "|".join(admission.accepted_customer_ids),
                "rejected_additions": "|".join(admission.rejected_customer_ids),
                "stage_rejected_revenue_cny": admission.rejected_revenue,
                "cumulative_rejected_revenue_cny": lost_revenue,
                "delivery_cost_cny": running_cost,
                "total_cost_with_lost_revenue_cny": running_cost + lost_revenue,
                "actual_vehicle_count": len(used),
                "actual_cv_count": len({item for item in used if item.startswith("CV_")}),
                "actual_ev_count": len({item for item in used if item.startswith("EV_")}),
                "legal": True,
                "subset_count": admission.planner_call_count,
                "stage_evaluations": admission.planner_call_count * STAGE_EVALUATIONS,
                "optimal_tie_count": admission.optimal_tie_count,
            }
        )
        for event_id in batch.event_ids:
            event = events_by_id[event_id]
            event_rows.append(
                {
                    "arm": policy,
                    "stage": stage_index,
                    "trigger_second": batch.trigger_second,
                    "event_id": event_id,
                    "event_type": "add" if isinstance(event, DynamicOrder) else event.event_type,
                    "customer_id": event.customer_id,
                    "status": event_status[event_id],
                }
            )
        inherited_states = cut.asset_states
        inherited_locked = cut.locked_charging_actions
        previous_trigger = batch.trigger_second
        current_plan = result["solution"]
        current_certificate = result["certificate"]
        current_instance = construction.effective_instance
        route_history.update({route.vehicle_id: route for route in current_plan.routes})

    final = probe._merge_execution_plan(
        committed_routes, committed_actions, current_plan, route_history
    )
    validate_dynamic_multitrip_certificate(
        current_plan,
        current_certificate,
        current_instance,
        bundle.prices,
        asset_states=inherited_states,
        stage_start_second=previous_trigger,
        locked_charging_actions=inherited_locked,
    )
    summary = _summary(
        policy,
        final,
        current_instance,
        bundle,
        rejected_ids,
        lost_revenue,
        time.perf_counter() - started,
        evaluations,
        len(batches),
        (),
        "dynamic_certificate_chain",
        len(batches),
    )
    return summary, stage_rows, event_rows, attempt_rows


def _run_static(
    bundle: Any,
    stream: DynamicStream,
    initial_instance: Instance,
    initial_plan: Solution,
    sources: Mapping[str, Any],
    stream_seed: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    started = time.perf_counter()
    states = _full_assets({}, bundle, 0.0)
    cut = CertificateCut(0.0, "FULL_INFORMATION_STATIC", (), (), (), (), states)
    events = list(stream.events)
    additions = [event for event in events if isinstance(event, DynamicOrder)]
    updates = [event for event in events if not isinstance(event, DynamicOrder)]
    demand = {event.customer_id: event.demand_kg for event in additions}
    attempts: list[dict[str, Any]] = []

    def planner(selected: tuple[str, ...], _assets: Mapping[str, Any]) -> PlanAttempt:
        selected_set = set(selected)
        chosen = [*updates, *(event for event in additions if event.customer_id in selected_set)]
        attempt_started = time.perf_counter()
        try:
            construction = probe.base.gate.build_open_stage(
                initial_plan.routes,
                initial_instance,
                [event.as_solver_event() for event in chosen],
                RECEPTION_END_SECOND,
                set(),
                dict(bundle.customer_home_depot),
                bundle.prices,
                stage_index=0,
                isolate_changed_customers=True,
            )
            result = probe.base.search_stage(
                construction,
                sources,
                cut,
                dict(bundle.customer_home_depot),
                set(),
                trigger=0.0,
                seed=1000 + stream_seed,
                evaluations=STAGE_EVALUATIONS,
                allow_cross_depot=True,
                stage_new_customer_ids=tuple(sorted(selected_set)),
            )
            static_plan, static_certificate = prepare_multitrip_solution(
                result["search_structure"],
                construction.effective_instance,
                bundle.prices,
            )
            validate_multitrip_certificate(
                static_certificate, list(static_plan.routes), bundle.prices
            )
            violations = check_solution(
                static_plan, construction.effective_instance, bundle.prices
            )
            if violations:
                raise ValueError(f"static check: {violations[0]}")
            cost = float(
                evaluate(
                    static_plan,
                    construction.effective_instance,
                    bundle.time_profile,
                    bundle.prices,
                )["total_cost"]
            )
            attempt = PlanAttempt(
                True,
                payload=(construction, static_plan, static_certificate),
                delivery_cost=cost,
            )
        except (probe.base.NoExecutableContinuation, ValueError) as exc:
            attempt = PlanAttempt(False, reason=f"{type(exc).__name__}: {exc}")
        attempts.append(
            {
                "arm": "full_information_static_reference",
                "stage": 0,
                "trigger_second": 0.0,
                "selected_additions": "|".join(sorted(selected_set)),
                "selected_count": len(selected_set),
                "feasible": attempt.feasible,
                "delivery_cost_cny": attempt.delivery_cost if attempt.feasible else "NA",
                "reason": attempt.reason,
                "evaluations": STAGE_EVALUATIONS,
                "wall_seconds": time.perf_counter() - attempt_started,
            }
        )
        return attempt

    admission = admit_new_orders_or_reject_individually(
        (),
        [event.customer_id for event in additions],
        demand,
        revenue_per_kg=REVENUE_PER_KG,
        full_asset_states=states,
        planner=planner,
    )
    construction, static_plan, _ = admission.plan_payload
    static_violations = check_solution(
        static_plan, construction.effective_instance, bundle.prices
    )
    summary = _summary(
        "full_information_static_reference",
        static_plan,
        construction.effective_instance,
        bundle,
        set(admission.rejected_customer_ids),
        admission.rejected_revenue,
        time.perf_counter() - started,
        admission.planner_call_count * STAGE_EVALUATIONS,
        1,
        static_violations,
        "generic_check_solution",
        1,
    )
    return summary, [
        {
            "arm": "full_information_static_reference",
            "stage": 0,
            "trigger_second": 0.0,
            "trigger_cause": "all_events_known_before_dispatch",
            "event_ids": "|".join(event.event_id for event in events),
            "accepted_additions": "|".join(admission.accepted_customer_ids),
            "rejected_additions": "|".join(admission.rejected_customer_ids),
            "stage_rejected_revenue_cny": admission.rejected_revenue,
            "cumulative_rejected_revenue_cny": admission.rejected_revenue,
            "delivery_cost_cny": summary["delivery_cost_cny"],
            "total_cost_with_lost_revenue_cny": summary[
                "total_cost_with_lost_revenue_cny"
            ],
            "actual_vehicle_count": summary["actual_vehicle_count"],
            "actual_cv_count": summary["actual_cv_count"],
            "actual_ev_count": summary["actual_ev_count"],
            "legal": summary["legal"],
            "subset_count": admission.planner_call_count,
            "stage_evaluations": admission.planner_call_count * STAGE_EVALUATIONS,
            "optimal_tie_count": admission.optimal_tie_count,
        }
    ], attempts


def _first_trigger_fleet_rows(
    bundle: Any,
    stream: DynamicStream,
    initial_instance: Instance,
    initial_plan: Solution,
    initial_certificate: Any,
) -> tuple[list[dict[str, Any]], float]:
    first_trigger = build_trigger_batches(stream.events, PER_ORDER)[0].trigger_second
    cut = cut_certificate_at_trigger(
        initial_plan,
        initial_certificate,
        initial_instance,
        bundle.prices,
        trigger_second=first_trigger,
    )
    full = _full_assets(cut.asset_states, bundle, first_trigger)
    rows = [
        {
            "physical_vehicle_id": asset_id,
            "vehicle_type": state.vehicle_type,
            "home_depot_id": state.home_depot_id,
            "available_second": state.available_second,
            "remaining_battery_kwh": state.remaining_battery_kwh,
            "next_trip_index": state.next_trip_index,
            "used_by_initial_plan": asset_id in cut.asset_states,
            "injected_at_first_trigger": asset_id not in cut.asset_states,
        }
        for asset_id, state in sorted(full.items())
    ]
    return rows, first_trigger


def _report(
    rows: list[dict[str, Any]],
    stream_hash: str,
    verdict: str,
    *,
    stream_seed: int,
    addition_count: int,
    static_subset_count: int,
    stage_evaluations: int,
) -> str:
    lines = [
        "# E7 邱莹莹同比例事件低成本小试",
        "",
        f"判定：`{verdict}`。算例 {INSTANCE_ID}，订单流种子 {stream_seed}，"
        f"事件流 SHA-256 `{stream_hash}`。",
        "",
        "全信息一次性静态参照在发车前知道全天最终订单，采用邱莹莹式一次启发式排程；"
        "它不是数学最优或理论上界。三种动态方案看到信息后再重排。"
        f"全信息一次性静态参照也允许拒单，对 {addition_count} 个新订单的全部 "
        f"{static_subset_count} 种取舍逐一比较。每个候选均使用 "
        f"{stage_evaluations} 次完整评价，这是既有 E7 低成本探针的档位。",
        "",
        "| 方案 | 配送成本 | 拒单损失 | 总口径成本 | 完成率 | 用车(CV/EV) | 触发次数 | 合法 |",
        "|---|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['arm']} | {row['delivery_cost_cny']:.2f} | "
            f"{row['rejected_revenue_cny']:.2f} | "
            f"{row['total_cost_with_lost_revenue_cny']:.2f} | "
            f"{row['completion_rate_pct']:.2f}% | "
            f"{row['actual_cv_count']}/{row['actual_ev_count']} | "
            f"{row['trigger_count']} | {'是' if row['legal'] else '否'} |"
        )
    lines.extend(
        [
            "",
        "当批新增订单通过穷举全部子集选择，不按客户编号或输入先后逐单贪心。"
        "取消已经锁定的订单会在 event_outcomes.csv 记为 ignored_already_locked。",
        "",
        "全信息一次性静态参照使用通用完整检查器；动态方案使用每个重排阶段的绝对时钟证书，"
        "并在末阶段再做一次证书终验。",
        "",
        "本批是接线和效应小试，全部候选与不利结果保留；未据结果修改事件、预算或车队。",
        ]
    )
    return "\n".join(lines) + "\n"


def run(out: Path, *, stream_seed: int = DEFAULT_STREAM_SEED) -> None:
    if out.exists():
        raise RuntimeError(f"refusing to overwrite {out}")
    out.mkdir(parents=True)
    started = time.perf_counter()
    bundle = load_bundle(INSTANCE_ID)
    global _FULL_INSTANCE
    _FULL_INSTANCE = bundle.instance
    stream = build_qiu_scaled_stream(
        bundle.instance, instance_id=INSTANCE_ID, stream_seed=stream_seed
    )
    initial_instance, initial_plan, initial_certificate, initial_activity = _initial_plan(
        bundle, stream
    )
    fleet_rows, first_trigger = _first_trigger_fleet_rows(
        bundle, stream, initial_instance, initial_plan, initial_certificate
    )
    sources = {
        "bundle": SearchBundle(
            bundle_dir=out,
            instance=bundle.instance,
            carbon_profile=list(bundle.time_profile),
        ),
        "prices": bundle.prices,
    }
    original_applier = probe.base.gate._instance_after_events
    original_action = probe.base.apply_winner_action

    def compatible_action(solution: Solution, action: Any, context: Any, **kwargs: Any) -> Any:
        if kwargs.get("current_obj") is None:
            kwargs["current_obj"] = score_reference(solution, context)
        return original_action(solution, action, context, **kwargs)
    summaries: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    attempt_rows: list[dict[str, Any]] = []
    try:
        probe.base.gate._instance_after_events = _exact_instance_after_events
        probe.base.apply_winner_action = compatible_action
        static, static_stages, static_attempts = _run_static(
            bundle, stream, initial_instance, initial_plan, sources, stream_seed
        )
        summaries.append(static)
        stage_rows.extend(static_stages)
        attempt_rows.extend(static_attempts)
        for policy in POLICIES:
            summary, stages, events, attempts = _run_dynamic(
                policy,
                bundle,
                stream,
                initial_instance,
                initial_plan,
                initial_certificate,
                sources,
                stream_seed,
            )
            summaries.append(summary)
            stage_rows.extend(stages)
            event_rows.extend(events)
            attempt_rows.extend({"arm": policy, **row} for row in attempts)
    finally:
        probe.base.gate._instance_after_events = original_applier
        probe.base.apply_winner_action = original_action

    verdict = (
        f"PASS_E7_QIU_50C_SEED{stream_seed}_SYMMETRIC_PILOT"
        if all(row["legal"] for row in summaries)
        else f"HALT_E7_QIU_50C_SEED{stream_seed}_CHECK"
    )
    metadata = {
        "schema": "resetp.e7.qiu-trigger-pilot.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "instance_id": INSTANCE_ID,
        "stream_seed": stream_seed,
        "stream_sha256": dynamic_stream_sha256(stream),
        "initial_customer_count": len(stream.initial_customer_ids),
        "event_count": len(stream.events),
        "addition_count": sum(isinstance(event, DynamicOrder) for event in stream.events),
        "static_subset_candidate_count": len(static_attempts),
        "stage_evaluations_per_subset": STAGE_EVALUATIONS,
        "stage_budget_source": "existing E7 low-cost probe default",
        "revenue_per_kg_cny": REVENUE_PER_KG,
        "fleet_caps_by_depot": {
            depot: dict(values) for depot, values in bundle.fleet_caps_by_depot.items()
        },
        "first_trigger_second": first_trigger,
        "first_trigger_initial_ev_count": sum(
            row["vehicle_type"] == "ev" and row["used_by_initial_plan"]
            for row in fleet_rows
        ),
        "first_trigger_injected_ev_count": sum(
            row["vehicle_type"] == "ev" and row["injected_at_first_trigger"]
            for row in fleet_rows
        ),
        "first_trigger_injected_cv_count": sum(
            row["vehicle_type"] == "cv" and row["injected_at_first_trigger"]
            for row in fleet_rows
        ),
        "initial_completion_activity": initial_activity,
        "wall_seconds": time.perf_counter() - started,
    }
    decision = {
        "verdict": verdict,
        "formal_result": False,
        "all_candidates_retained": True,
        "same_event_stream": True,
        "same_stage_budget": True,
        "full_information_static_is_reference": True,
        "static_reference_validation_method": "generic_check_solution",
        "dynamic_validation_method": "dynamic_certificate_chain",
        "dynamic_stage_certificates_validated": all(
            row["validated_stage_count"] == row["trigger_count"]
            for row in summaries
            if row["arm"] != "full_information_static_reference"
        ),
        "no_fleet_expansion": True,
        "no_soft_windows_or_outsourcing": True,
        "summary_count": len(summaries),
    }
    _write_json(out / "metadata.json", metadata)
    _write_csv(out / "raw_runs.csv", summaries)
    _write_csv(out / "stage_runs.csv", stage_rows)
    _write_csv(out / "event_outcomes.csv", event_rows)
    _write_csv(out / "subset_attempts.csv", attempt_rows)
    _write_csv(out / "fleet_state_at_first_trigger.csv", fleet_rows)
    _write_json(out / "decision.json", decision)
    (out / "report.md").write_text(
        _report(
            summaries,
            metadata["stream_sha256"],
            verdict,
            stream_seed=stream_seed,
            addition_count=metadata["addition_count"],
            static_subset_count=metadata["static_subset_candidate_count"],
            stage_evaluations=metadata["stage_evaluations_per_subset"],
        ),
        encoding="utf-8",
    )
    artifacts = {
        path.name: _sha256(path)
        for path in sorted(out.iterdir())
        if path.is_file()
        and not path.name.startswith("._")
        and path.name != "artifact_hashes.json"
    }
    _write_json(out / "artifact_hashes.json", artifacts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stream-seed", type=int, default=DEFAULT_STREAM_SEED)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or default_output(args.stream_seed)
    run(output.resolve(), stream_seed=args.stream_seed)


if __name__ == "__main__":
    main()
