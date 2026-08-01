#!/usr/bin/env python3
"""Diagnose Qiu's hybrid trigger with every revealed order accepted as one batch."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Iterable, Mapping, Sequence


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for entry in (ROOT, ROOT / "solver/src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from baselines.china_e3_e7.e3_scattered_ownership_20260801.shared_runtime import (
    load_bundle,
)
from baselines.china_e3_e7.e7_trigger_policies_20260801 import run_pilot as pilot
from baselines.china_e3_e7.e7_trigger_policies_20260801.dynamic_adapter import (
    PlanAttempt,
    accept_new_orders_as_full_batch,
)
from baselines.china_e3_e7.e7_trigger_policies_20260801.trigger_policies import (
    HYBRID_500KG_OR_30_MINUTES,
    DynamicOrder,
    DynamicStream,
    build_qiu_scaled_stream,
    build_trigger_batches,
    dynamic_stream_sha256,
)
from baselines.e7_dynamic import e7_full_mechanism_probe_20260714 as probe
from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance
from setp_solver.search.bundle import SearchBundle
from setp_solver.search.dynamic_multitrip_schedule import (
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
    validate_dynamic_multitrip_certificate,
)
from setp_solver.search.evaluation import score_reference
from setp_solver.solution import Route, Solution, physical_vehicle_id


SEEDS = tuple(range(1, 11))
OUTPUT_NAME = "qiu_accept_all_50c_seeds1to10_eval8_diagnostic_20260801"


def route_plan_signature(
    routes: Iterable[Route], instance: Instance
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Identify a route plan by physical vehicle and ordered customer visits."""

    customer_ids = {
        node.node_id for node in instance.nodes if node.node_type.lower() == "c"
    }
    rows = []
    for route in routes:
        visits = tuple(node_id for node_id in route.node_sequence if node_id in customer_ids)
        if visits:
            rows.append(
                (physical_vehicle_id(route.vehicle_id), route.vehicle_type.lower(), visits)
            )
    return tuple(sorted(rows))


def _signature_sha256(signature: Any) -> str:
    return hashlib.sha256(
        json.dumps(signature, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _failure_text(exc: Exception) -> str:
    return str(exc) if isinstance(exc, RuntimeError) else f"{type(exc).__name__}: {exc}"


def _event_rows(
    stream: DynamicStream,
    batches: Sequence[Any],
    statuses: Mapping[str, str],
    policy: str,
) -> list[dict[str, Any]]:
    assignment = {
        event_id: (batch.batch_index, batch.trigger_second, batch.cause)
        for batch in batches
        for event_id in batch.event_ids
    }
    rows = []
    for event in stream.events:
        solver_event = asdict(event.as_solver_event())
        batch_index, trigger_second, trigger_cause = assignment[event.event_id]
        rows.append(
            {
                "stream_seed": stream.stream_seed,
                "policy": policy,
                "stream_sha256": dynamic_stream_sha256(stream),
                "batch_index": batch_index,
                "trigger_second": trigger_second,
                "trigger_cause": trigger_cause,
                "outcome": statuses.get(event.event_id, "not_attempted"),
                **solver_event,
            }
        )
    return rows


def _not_attempted_rows(
    stream_seed: int,
    policy: str,
    batches: Sequence[Any],
    start_index: int,
    reason: str,
) -> list[dict[str, Any]]:
    rows = []
    for batch in batches[start_index:]:
        addition_ids = tuple(
            customer_id
            for customer_id, event_type in zip(batch.customer_ids, batch.event_types)
            if event_type == "add"
        )
        rows.append({
            "stream_seed": stream_seed,
            "policy": policy,
            "stage": batch.batch_index,
            "status": "NOT_ATTEMPTED_AFTER_FAILURE",
            "legal": "NA",
            "trigger_second": batch.trigger_second,
            "trigger_cause": batch.cause,
            "event_ids": "|".join(batch.event_ids),
            "addition_ids": "|".join(addition_ids),
            "addition_count": len(addition_ids),
            "accepted_addition_count": 0,
            "failure_reason": reason,
            "search_called": False,
            "stage_evaluation_budget": 0,
            "route_plan_changed": "NA",
            "before_route_signature_sha256": "NA",
            "after_route_signature_sha256": "NA",
            "newly_used_vehicle_count": 0,
            "newly_used_vehicle_ids": "",
        })
    return rows


def _run_seed(
    bundle: Any,
    sources: Mapping[str, Any],
    stream_seed: int,
    policy: str = HYBRID_500KG_OR_30_MINUTES,
) -> tuple[
    dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]
]:
    started = time.perf_counter()
    stream = build_qiu_scaled_stream(
        bundle.instance, instance_id=pilot.INSTANCE_ID, stream_seed=stream_seed
    )
    batches = build_trigger_batches(stream.events, policy)
    events_by_id = {event.event_id: event for event in stream.events}
    addition_ids = {
        event.customer_id for event in stream.events if isinstance(event, DynamicOrder)
    }
    statuses: dict[str, str] = {}
    stage_rows: list[dict[str, Any]] = []
    accepted_additions: set[str] = set()
    new_vehicle_ids: set[str] = set()
    adjustment_count = 0
    failure_stage: int | str = ""
    failure_reason = ""
    attempted_stages = 0
    requested_evaluations = 0

    try:
        current_instance, current_plan, current_certificate, _ = pilot._initial_plan(
            bundle, stream
        )
        inherited_states = None
        inherited_locked = ()
        previous_trigger = None
        committed_routes: dict[str, Route] = {}
        committed_actions: dict[tuple[Any, ...], Any] = {}
        committed_customers: set[str] = set()
        route_history = {route.vehicle_id: route for route in current_plan.routes}
        used_vehicles = {
            physical_vehicle_id(route.vehicle_id) for route in current_plan.routes
        }

        for offset, batch in enumerate(batches):
            stage_index = batch.batch_index
            attempted_stages += 1
            batch_events = [events_by_id[event_id] for event_id in batch.event_ids]
            additions = [event for event in batch_events if isinstance(event, DynamicOrder)]
            updates = [event for event in batch_events if not isinstance(event, DynamicOrder)]
            addition_batch_ids = tuple(sorted(event.customer_id for event in additions))
            attempt: dict[str, Any] = {
                "search_called": False,
                "wall_seconds": 0.0,
                "failure_reason": "",
            }
            stage_started = time.perf_counter()

            try:
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
                        asset_states=pilot._full_assets(
                            cut.asset_states, bundle, batch.trigger_second
                        ),
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
                    committed_customers.update(
                        probe.base.p2.route_customers(route, current_instance)
                    )
                for action in cut.locked_charging_actions:
                    committed_actions.setdefault(probe.base.action_key(action), action)

                open_routes = probe.base.gate._cut_routes(
                    current_plan, cut.editable_route_ids
                )
                before_signature = route_plan_signature(open_routes, current_instance)
                owners = dict(bundle.customer_home_depot)

                def planner(
                    selected: tuple[str, ...], _assets: Mapping[str, Any]
                ) -> PlanAttempt:
                    try:
                        construction = probe.base.gate.build_open_stage(
                            open_routes,
                            current_instance,
                            [event.as_solver_event() for event in (*updates, *additions)],
                            batch.trigger_second,
                            committed_customers,
                            owners,
                            bundle.prices,
                            stage_index=stage_index,
                            isolate_changed_customers=True,
                        )
                        attempt["search_called"] = True
                        result = probe.base.search_stage(
                            construction,
                            sources,
                            cut,
                            owners,
                            committed_customers,
                            trigger=batch.trigger_second,
                            seed=1000 + stream_seed,
                            evaluations=pilot.STAGE_EVALUATIONS,
                            allow_cross_depot=True,
                            stage_new_customer_ids=selected,
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
                        return PlanAttempt(
                            True,
                            payload=(construction, result),
                            delivery_cost=float(result["future_cost"]),
                        )
                    except (probe.base.NoExecutableContinuation, ValueError) as exc:
                        attempt["failure_reason"] = f"{type(exc).__name__}: {exc}"
                        return PlanAttempt(False, reason=attempt["failure_reason"])

                admission = accept_new_orders_as_full_batch(
                    addition_batch_ids, cut.asset_states, planner
                )
                construction, result = admission.plan_payload
                future_ids = pilot._customer_ids(
                    result["solution"], construction.effective_instance
                )
                active_ids = {
                    node.node_id
                    for node in construction.effective_instance.nodes
                    if node.node_type.lower() == "c"
                }
                if (
                    len(future_ids) != len(set(future_ids))
                    or committed_customers & set(future_ids)
                    or committed_customers | set(future_ids) != active_ids
                ):
                    raise RuntimeError("customer ledger failed after full-batch planning")

                running = probe._merge_execution_plan(
                    committed_routes, committed_actions, result["solution"], route_history
                )
                current_used = {
                    physical_vehicle_id(route.vehicle_id) for route in running.routes
                }
                newly_used = current_used - used_vehicles
                used_vehicles |= current_used
                new_vehicle_ids |= newly_used
                after_signature = route_plan_signature(
                    result["solution"].routes, construction.effective_instance
                )
                route_changed = before_signature != after_signature
                adjustment_count += int(route_changed)
                accepted_additions.update(addition_batch_ids)
                for event in additions:
                    statuses[event.event_id] = "accepted"
                for event in updates:
                    statuses[event.event_id] = (
                        "applied"
                        if event.event_id in construction.applied_event_ids
                        else "ignored_already_locked"
                    )
                requested_evaluations += (
                    pilot.STAGE_EVALUATIONS if attempt["search_called"] else 0
                )

                stage_rows.append(
                    {
                        "stream_seed": stream_seed,
                        "policy": policy,
                        "stage": stage_index,
                        "status": "PASS_FULL_BATCH",
                        "legal": True,
                        "trigger_second": batch.trigger_second,
                        "trigger_cause": batch.cause,
                        "event_ids": "|".join(batch.event_ids),
                        "addition_ids": "|".join(addition_batch_ids),
                        "addition_count": len(addition_batch_ids),
                        "accepted_addition_count": len(addition_batch_ids),
                        "failure_reason": "",
                        "search_called": attempt["search_called"],
                        "stage_evaluation_budget": (
                            pilot.STAGE_EVALUATIONS if attempt["search_called"] else 0
                        ),
                        "route_plan_changed": route_changed,
                        "before_route_signature_sha256": _signature_sha256(
                            before_signature
                        ),
                        "after_route_signature_sha256": _signature_sha256(
                            after_signature
                        ),
                        "newly_used_vehicle_count": len(newly_used),
                        "newly_used_vehicle_ids": "|".join(sorted(newly_used)),
                        "wall_seconds": time.perf_counter() - stage_started,
                    }
                )
                inherited_states = cut.asset_states
                inherited_locked = cut.locked_charging_actions
                previous_trigger = batch.trigger_second
                current_plan = result["solution"]
                current_certificate = result["certificate"]
                current_instance = construction.effective_instance
                route_history.update(
                    {route.vehicle_id: route for route in current_plan.routes}
                )
            except Exception as exc:
                if attempt["search_called"]:
                    requested_evaluations += pilot.STAGE_EVALUATIONS
                failure_stage = stage_index
                failure_reason = attempt["failure_reason"] or _failure_text(exc)
                stage_rows.append(
                    {
                        "stream_seed": stream_seed,
                        "policy": policy,
                        "stage": stage_index,
                        "status": "HALT_FULL_BATCH",
                        "legal": False,
                        "trigger_second": batch.trigger_second,
                        "trigger_cause": batch.cause,
                        "event_ids": "|".join(batch.event_ids),
                        "addition_ids": "|".join(addition_batch_ids),
                        "addition_count": len(addition_batch_ids),
                        "accepted_addition_count": 0,
                        "failure_reason": failure_reason,
                        "search_called": attempt["search_called"],
                        "stage_evaluation_budget": (
                            pilot.STAGE_EVALUATIONS if attempt["search_called"] else 0
                        ),
                        "route_plan_changed": "NA",
                        "before_route_signature_sha256": "NA",
                        "after_route_signature_sha256": "NA",
                        "newly_used_vehicle_count": 0,
                        "newly_used_vehicle_ids": "",
                        "wall_seconds": time.perf_counter() - stage_started,
                    }
                )
                for event in batch_events:
                    statuses[event.event_id] = "not_applied_stage_failed"
                for later in batches[offset + 1 :]:
                    for event_id in later.event_ids:
                        statuses[event_id] = "not_attempted_after_prior_failure"
                stage_rows.extend(
                    _not_attempted_rows(
                        stream_seed, policy, batches, offset + 1, failure_reason
                    )
                )
                break

        if not failure_reason:
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
            final_metrics = evaluate(
                final, current_instance, bundle.time_profile, bundle.prices
            )
            final_cost: float | str = float(final_metrics["total_cost"])
            final_distance: float | str = float(final_metrics["distance_total"])
            final_emissions: float | str = float(final_metrics["E_total"])
            final_vehicles = {
                physical_vehicle_id(route.vehicle_id) for route in final.routes
            }
            actual_vehicle_count: int | str = len(final_vehicles)
            actual_cv_count: int | str = len(
                {vehicle_id for vehicle_id in final_vehicles if vehicle_id.startswith("CV_")}
            )
            actual_ev_count: int | str = len(
                {vehicle_id for vehicle_id in final_vehicles if vehicle_id.startswith("EV_")}
            )
            status = "PASS_ACCEPT_ALL" if accepted_additions == addition_ids else "HALT_LEDGER"
            if status != "PASS_ACCEPT_ALL":
                failure_reason = "not all generated additions reached the accepted ledger"
        else:
            final_cost = "NA"
            final_distance = "NA"
            final_emissions = "NA"
            actual_vehicle_count = "NA"
            actual_cv_count = "NA"
            actual_ev_count = "NA"
            status = "HALT_STAGE_FAILURE"
    except Exception as exc:
        status = "HALT_INITIAL_OR_RUNTIME_FAILURE"
        failure_reason = _failure_text(exc)
        failure_stage = failure_stage or 0
        for event in stream.events:
            statuses.setdefault(event.event_id, "not_attempted_initial_or_runtime_failure")
        if not stage_rows:
            stage_rows.extend(
                _not_attempted_rows(stream_seed, policy, batches, 0, failure_reason)
            )
        final_cost = "NA"
        final_distance = "NA"
        final_emissions = "NA"
        actual_vehicle_count = "NA"
        actual_cv_count = "NA"
        actual_ev_count = "NA"

    summary = {
        "stream_seed": stream_seed,
        "policy": policy,
        "stream_sha256": dynamic_stream_sha256(stream),
        "status": status,
        "legal_full_stream": status == "PASS_ACCEPT_ALL",
        "generated_addition_count": len(addition_ids),
        "accepted_addition_count": len(accepted_additions),
        "dynamic_addition_completion_rate_pct": (
            100.0 * len(accepted_additions) / len(addition_ids)
            if addition_ids
            else 100.0
        ),
        "accepted_addition_ids": "|".join(sorted(accepted_additions)),
        "scheduled_trigger_count": len(batches),
        "attempted_trigger_count": attempted_stages,
        "actual_route_adjustment_count": adjustment_count,
        "newly_used_vehicle_count": len(new_vehicle_ids),
        "newly_used_vehicle_ids": "|".join(sorted(new_vehicle_ids)),
        "requested_search_evaluations": requested_evaluations,
        "final_delivery_cost_cny": final_cost,
        "distance_total_m": final_distance,
        "total_emissions_kg": final_emissions,
        "actual_vehicle_count": actual_vehicle_count,
        "actual_cv_count": actual_cv_count,
        "actual_ev_count": actual_ev_count,
        "failure_stage": failure_stage,
        "failure_reason": failure_reason,
        "wall_seconds": time.perf_counter() - started,
    }
    return summary, stage_rows, _event_rows(stream, batches, statuses, policy)


def _report(rows: Sequence[Mapping[str, Any]]) -> str:
    passed = sum(row["status"] == "PASS_ACCEPT_ALL" for row in rows)
    lines = [
        "# E7 邱式整批接收低成本诊断",
        "",
        f"结果：10个固定事件流中 {passed} 个完整跑通，{len(rows) - passed} 个在整批接收时停止。",
        "本诊断只运行累计500kg即提前、否则最多等待30分钟、10:00收尾的组合触发。",
        "每批新单全部接收一次，不枚举接单子集、不主动经济拒单、不顺延。",
        "完成率只用动态新增订单计算：已接收新增订单数 ÷ 10，不把日初客户混入分母。",
        "实际改路线次数按批次计算：比较触发前尚可编辑的后续路线与重排后的后续路线；",
        "路线用“实体车辆编号＋有序客户序列”识别，忽略车场、充电站和行程编号。两者不同才记1次。",
        "",
        "| 流种子 | 状态 | 接收新单 | 实际新增车辆 | 触发/实际改路线 | 失败阶段 | 失败原文 |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        reason = str(row["failure_reason"]).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {row['stream_seed']} | {row['status']} | "
            f"{row['accepted_addition_count']}/{row['generated_addition_count']} | "
            f"{row['newly_used_vehicle_count']} | "
            f"{row['scheduled_trigger_count']}/{row['actual_route_adjustment_count']} | "
            f"{row['failure_stage'] or '-'} | {reason or '-'} |"
        )
    lines.extend(
        [
            "",
            "`stage_runs.csv`逐批保留是否合法、失败原文、实际新增车辆和路线签名变化；",
            "`event_stream.csv`保留每个固定事件的完整字段、所属批次和处理结果。",
            "",
            "8次完整评价只是既有低成本排障预算，不是正式实验预算，也不构成机制有效性结论。",
            "本目录不比较其他触发规则、不包含全知静态参照、不修改参数、算例或车队上限。",
        ]
    )
    return "\n".join(lines) + "\n"


def run(out: Path) -> None:
    if out.exists():
        raise RuntimeError(f"refusing to overwrite {out}")
    out.mkdir(parents=True)
    started = time.perf_counter()
    bundle = load_bundle(pilot.INSTANCE_ID)
    pilot._FULL_INSTANCE = bundle.instance
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
    try:
        probe.base.gate._instance_after_events = pilot._exact_instance_after_events
        probe.base.apply_winner_action = compatible_action
        for stream_seed in SEEDS:
            summary, stages, events = _run_seed(bundle, sources, stream_seed)
            summaries.append(summary)
            stage_rows.extend(stages)
            event_rows.extend(events)
    finally:
        probe.base.gate._instance_after_events = original_applier
        probe.base.apply_winner_action = original_action

    verdict = (
        "PASS_E7_QIU_ACCEPT_ALL_10_OF_10_DIAGNOSTIC"
        if all(row["status"] == "PASS_ACCEPT_ALL" for row in summaries)
        else "HALT_E7_QIU_ACCEPT_ALL_DIAGNOSTIC_FAILURES_RETAINED"
    )
    metadata = {
        "schema": "resetp.e7.qiu-accept-all-diagnostic.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "instance_id": pilot.INSTANCE_ID,
        "stream_seeds": list(SEEDS),
        "policy": HYBRID_500KG_OR_30_MINUTES,
        "admission_rule": "accept_every_addition_in_each_trigger_batch",
        "deferral": False,
        "economic_rejection": False,
        "stage_evaluations": pilot.STAGE_EVALUATIONS,
        "stage_budget_role": "diagnostic_only_not_formal",
        "completion_rate_definition": (
            "accepted dynamic additions divided by 10 generated dynamic additions; "
            "initial customers are excluded"
        ),
        "actual_route_adjustment_definition": (
            "count one stage when the pre-trigger editable future-route signature differs "
            "from the post-stage future-route signature; signature is physical vehicle id "
            "plus ordered customer visits and ignores depots, charging stations, and trip ids"
        ),
        "stream_sha256_by_seed": {
            str(row["stream_seed"]): row["stream_sha256"] for row in summaries
        },
        "source_sha256": {
            path.name: pilot._sha256(path)
            for path in (
                Path(__file__),
                HERE / "dynamic_adapter.py",
                HERE / "trigger_policies.py",
                HERE / "run_pilot.py",
            )
        },
        "wall_seconds": time.perf_counter() - started,
    }
    decision = {
        "verdict": verdict,
        "formal_result": False,
        "effect_comparison": False,
        "all_failures_retained": True,
        "all_event_streams_retained": True,
        "no_seed_or_parameter_change": True,
        "no_fleet_expansion": True,
        "no_subset_enumeration": True,
        "no_economic_rejection": True,
        "no_deferral": True,
        "full_information_static_reference_run": False,
        "other_trigger_policies_run": False,
        "passed_stream_count": sum(
            row["status"] == "PASS_ACCEPT_ALL" for row in summaries
        ),
        "stream_count": len(summaries),
    }
    pilot._write_json(out / "metadata.json", metadata)
    pilot._write_csv(out / "raw_runs.csv", summaries)
    pilot._write_csv(out / "stage_runs.csv", stage_rows)
    pilot._write_csv(out / "event_stream.csv", event_rows)
    pilot._write_json(out / "decision.json", decision)
    (out / "report.md").write_text(_report(summaries), encoding="utf-8")
    artifacts = {
        path.name: pilot._sha256(path)
        for path in sorted(out.iterdir())
        if path.is_file()
        and not path.name.startswith("._")
        and path.name != "artifact_hashes.json"
    }
    pilot._write_json(out / "artifact_hashes.json", artifacts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=HERE / OUTPUT_NAME)
    args = parser.parse_args()
    run(args.output.resolve())


if __name__ == "__main__":
    main()
