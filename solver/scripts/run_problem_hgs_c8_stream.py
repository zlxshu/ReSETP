#!/usr/bin/env python3
"""Run the C8-1 minimum dynamic-stream wiring trial.

This is a technical chain check, not a performance experiment.  It loads the
selected unified target, keeps the target package read-only, and uses the
existing exact dynamic insertion operator on an in-memory stream overlay.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from dataclasses import asdict, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "solver/src"))
sys.path.insert(0, str(REPO_ROOT / "third_party/setp_hgs_kernel"))
sys.path.insert(0, str(REPO_ROOT / "solver/scripts"))

from run_problem_hgs_private_technical import (  # noqa: E402
    DEPOT_SEARCH_INSTANCE_ID,
    ENDOGENOUS_FLEET_PARAMETERS,
    _build_context,
    _policy,
)
from setp_solver.algorithms.problem_hgs.dynamic import (  # noqa: E402
    DutyDynamicState,
    future_individual_from_cut,
    prepare_dynamic_candidate,
)
from setp_solver.algorithms.problem_hgs.dynamic_insertion import (  # noqa: E402
    DynamicInsertionFailure,
    DynamicInsertionOperator,
    INSERTED_AND_FULL_EVALUATION_FEASIBLE,
)
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    DutyEvaluationContext,
    DutyFullEvaluator,
)
from setp_solver.algorithms.problem_hgs.model import DutyIndividual  # noqa: E402
from setp_solver.c8_dynamic_stream import (  # noqa: E402
    C8_BASE_INSTANCE_ID,
    C8DynamicEvent,
    C8DynamicStream,
    C8TriggerBatch,
    c8_generation_rules,
    load_c8_stream,
    overlay_c8_bundle,
    package_content_sha256,
    package_file_hashes,
    served_customer_ids,
    subset_c8_bundle,
    extend_route_contract,
)
from setp_solver.search.dynamic_multitrip_schedule import (  # noqa: E402
    DynamicAssetState,
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
)
from setp_solver.solution import ChargingAction, Route, Solution  # noqa: E402


REPORT_DEFAULT = REPO_ROOT / "solver/reports/c8_stream_20260816"
REPORT_DONE_STATUS = "C8_OUTSOURCE_DONE"
REPORT_HALT_STATUS = "C8_OUTSOURCE_HALT"
TARGET_DIR = (
    REPO_ROOT
    / "data/ChinaInstances/china81_final_suite_v2_20260815/instances"
    / C8_BASE_INSTANCE_ID
)
PROTECTED = (
    REPO_ROOT / "solver/src/setp_solver/cost.py",
    REPO_ROOT / "solver/src/setp_solver/check.py",
    REPO_ROOT / "solver/src/setp_solver/search/evaluation.py",
)


class C8RunFailure(RuntimeError):
    """A dynamic chain failure that must be reported without a conclusion."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _select_routes(solution: Solution, route_ids: set[str]) -> Solution:
    routes = [route for route in solution.routes if route.vehicle_id in route_ids]
    selected_ids = {route.vehicle_id for route in routes}
    actions = [
        action
        for action in solution.charging_actions
        if action.vehicle_id in selected_ids
    ]
    return Solution(routes=routes, charging_actions=actions)


def _advance_prior_history(state: DutyDynamicState) -> Solution:
    prior = state.prior_committed_solution or Solution()
    current_ids = {
        *state.cut.completed_route_ids,
        *state.cut.in_progress_route_ids,
    }
    current = _select_routes(state.source_solution, current_ids)
    routes = {route.vehicle_id: route for route in prior.routes}
    for route in current.routes:
        previous = routes.get(route.vehicle_id)
        if previous is not None and previous != route:
            raise C8RunFailure("committed route history changed between triggers")
        routes[route.vehicle_id] = route
    actions: dict[tuple[object, ...], ChargingAction] = {}
    for action in (*prior.charging_actions, *state.cut.locked_charging_actions):
        if action.vehicle_id not in routes:
            continue
        key = (
            action.vehicle_id,
            action.station_id,
            float(action.charge_start_second),
            float(action.energy_kwh),
        )
        previous = actions.get(key)
        if previous is not None and previous != action:
            raise C8RunFailure("committed charging history changed between triggers")
        actions[key] = action
    return Solution(
        routes=[routes[key] for key in sorted(routes)],
        charging_actions=[actions[key] for key in sorted(actions, key=str)],
    )


def _full_asset_registry(
    initial: DutyIndividual,
    cut: Any,
    bundle: Any,
) -> MappingProxyType:
    assets = dict(cut.asset_states)
    for duty in initial.duties:
        if duty.physical_vehicle_id in assets:
            continue
        assets[duty.physical_vehicle_id] = DynamicAssetState(
            physical_vehicle_id=duty.physical_vehicle_id,
            vehicle_type=duty.vehicle_type,
            home_depot_id=duty.home_depot_id,
            available_second=float(cut.trigger_second),
            remaining_battery_kwh=(
                float(bundle.prices.initial_ev_battery_kwh)
                if duty.vehicle_type == "ev"
                else 0.0
            ),
            next_trip_index=1,
        )
    return MappingProxyType(assets)


def _active_demand(bundle: Any, customer_ids: Iterable[str]) -> float:
    wanted = {str(customer_id) for customer_id in customer_ids}
    return sum(
        float(node.demand)
        for node in bundle.instance.nodes
        if node.node_id in wanted
    )


def _emissions(evaluation: Any) -> float | None:
    for key in ("E_total", "emissions_kg", "total_emissions_kg"):
        if key in evaluation.breakdown:
            return float(evaluation.breakdown[key])
    return None


def _default_off_identity(
    initial: DutyIndividual,
    evaluator: DutyFullEvaluator,
    policy: Any,
    evaluation: Any,
) -> dict[str, Any]:
    no_op = DynamicInsertionOperator(enabled=False, random_seed=0).apply(
        initial,
        evaluator=evaluator,
        charging_policy=policy,
        newly_revealed_customer_ids=(),
        current_evaluation=evaluation,
    )
    first_prepared_sha = _canonical_sha(asdict(evaluation.prepared_solution))
    second_prepared_sha = _canonical_sha(asdict(no_op.evaluation.prepared_solution)) if no_op.evaluation else None
    return {
        "dynamic_enabled_default": False,
        "operator_returned_same_individual_object": no_op.individual is initial,
        "operator_returned_same_evaluation_object": no_op.evaluation is evaluation,
        "individual_fingerprint_before": initial.fingerprint,
        "individual_fingerprint_after": no_op.individual.fingerprint,
        "prepared_solution_sha256_before": first_prepared_sha,
        "prepared_solution_sha256_after": second_prepared_sha,
        "committed_sha256_before": no_op.accounting.committed_sha256_before,
        "committed_sha256_after": no_op.accounting.committed_sha256_after,
        "zero_newly_revealed_count": no_op.accounting.newly_revealed_count == 0,
        "bytewise_identity_claim": (
            no_op.individual is initial
            and no_op.evaluation is evaluation
            and first_prepared_sha == second_prepared_sha
            and no_op.accounting.committed_sha256_before
            == no_op.accounting.committed_sha256_after
        ),
    }


def _event_rows_for_stage(
    *,
    batch: C8TriggerBatch,
    events_by_id: dict[str, C8DynamicEvent],
    result: Any,
    bundle: Any,
    active: set[str],
    inserted: bool,
    failure_reason: str = "",
    outsourced_customer_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    evaluation = result.evaluation if result is not None else None
    served = served_customer_ids(evaluation.prepared_solution, bundle) if evaluation else frozenset()
    outsourced = {str(customer_id) for customer_id in outsourced_customer_ids}
    batch_served = sorted(
        served.intersection(batch.customer_ids).difference(outsourced)
    )
    batch_demand = _active_demand(bundle, batch_served)
    completed = sorted(served.intersection(active))
    completed_demand = _active_demand(bundle, completed)
    internal_total_cost = float(evaluation.total_cost) if evaluation else None
    internal_emissions = _emissions(evaluation) if evaluation else None
    outsourcing_demand = sum(
        float(events_by_id[event_id].demand_kg)
        for event_id in batch.event_ids
        if events_by_id[event_id].customer_id in outsourced
    )
    status = (
        result.status
        if result is not None
        else (
            INSERTED_AND_FULL_EVALUATION_FEASIBLE
            if inserted
            else "NOT_INSERTED_DIAGNOSTIC_ONLY"
        )
    )
    resolved_failure_reason = (
        failure_reason
        or (result.failure_reason if result is not None else "")
    )
    diagnostics_ref = (
        f"candidate_diagnostics.json#trigger_batch_index={batch.batch_index}"
        if result is not None
        else ""
    )
    has_outsourcing = bool(outsourced)
    external_cost = "UNKNOWN (待用户定价)" if has_outsourcing else 0.0
    total_cost = (
        "UNKNOWN (待用户定价)" if has_outsourcing else internal_total_cost
    )
    emissions = (
        "UNKNOWN (外包排放未建模)" if has_outsourcing else internal_emissions
    )
    return [
        {
            "event_id": events_by_id[event_id].event_id,
            "customer_id": events_by_id[event_id].customer_id,
            "event_type": events_by_id[event_id].event_type,
            "trigger_batch_index": batch.batch_index,
            "trigger_second": batch.trigger_second,
            "trigger_cause": batch.cause,
            "revealed_service_customer_ids": ";".join(batch_served),
            "revealed_service_customer_count": len(batch_served),
            "revealed_service_demand_kg": batch_demand,
            "insertion_result": status,
            "outsourcing_customer_ids": ";".join(sorted(outsourced)),
            "outsourcing_customer_count": len(outsourced),
            "outsourcing_demand_kg": outsourcing_demand,
            "outsourcing_cost": external_cost,
            "failure_reason": resolved_failure_reason,
            "metric_scope": (
                "post_trigger_internal_solution_excluding_unpriced_outsourcing"
                if has_outsourcing
                else "post_trigger_full_active_solution"
            ),
            "post_trigger_internal_total_cost": internal_total_cost,
            "post_trigger_internal_emissions_kg": internal_emissions,
            "post_trigger_total_cost": total_cost,
            "post_trigger_emissions_kg": emissions,
            "post_trigger_total_cost_including_outsourcing": total_cost,
            "post_trigger_emissions_kg_including_outsourcing": emissions,
            "post_trigger_completed_customer_count": len(completed),
            "post_trigger_completed_demand_kg": completed_demand,
            "active_customer_count": len(active),
            "candidate_attempt_count": (
                result.accounting.candidate_attempt_count
                if result is not None
                else 0
            ),
            "candidate_feasible_count": (
                result.accounting.candidate_feasible_count
                if result is not None
                else 0
            ),
            "candidate_failure_reason_count": (
                len(result.accounting.candidate_failure_reasons)
                if result is not None
                else 0
            ),
            "candidate_diagnostics_ref": diagnostics_ref,
        }
        for event_id in batch.event_ids
    ]


def _candidate_diagnostic_payload(
    batch_index: int,
    result: Any,
) -> dict[str, Any]:
    return {
        "trigger_batch_index": batch_index,
        "status": result.status,
        "failure_reason": result.failure_reason,
        "candidate_attempt_count": result.accounting.candidate_attempt_count,
        "candidate_feasible_count": result.accounting.candidate_feasible_count,
        "candidate_failure_reason_count": len(
            result.accounting.candidate_failure_reasons
        ),
        "candidates": [
            asdict(item) for item in result.accounting.candidate_diagnostics
        ],
    }


def _run_chain(repo: Path, report: Path, stream: C8DynamicStream | None) -> dict[str, Any]:
    if stream is not None and stream.base_instance_id != C8_BASE_INSTANCE_ID:
        raise C8RunFailure("stream is not based on the selected unified instance")
    source_hashes_before = package_file_hashes(TARGET_DIR)
    source_hash_before = package_content_sha256(source_hashes_before)
    protected_before = {str(path.relative_to(repo)): _sha256_file(path) for path in PROTECTED}

    bundle, initial, _pi0, base_context = _build_context(
        repo,
        C8_BASE_INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )
    base_context = replace(
        base_context,
        fairness_enabled=False,
        incremental_full_truth_sentinel_enabled=False,
        dynamic_state=None,
    )
    evaluator = DutyFullEvaluator(base_context)
    static_evaluation = evaluator.evaluate(initial)
    if not static_evaluation.feasible:
        raise C8RunFailure(
            "unified target static witness is not feasible: "
            + "; ".join(str(v.detail) for v in static_evaluation.violations)
        )
    policy = _policy(evaluator)
    default_off = _default_off_identity(initial, evaluator, policy, static_evaluation)
    if not default_off["bytewise_identity_claim"]:
        raise C8RunFailure("default-off dynamic operator is not an exact no-op")

    if stream is None:
        active = {
            node.node_id
            for node in bundle.instance.nodes
            if node.node_type.lower() == "c"
        }
        completed = served_customer_ids(static_evaluation.prepared_solution, bundle)
        payload = {
            "status": REPORT_DONE_STATUS,
            "mode": "default_off_only",
            "default_off_identity": default_off,
            "static_customer_count": len(active),
            "static_completed_customer_count": len(completed),
            "static_completed_demand_kg": _active_demand(bundle, completed),
            "source_instance_sha256_before": source_hash_before,
            "source_instance_sha256_after": package_content_sha256(package_file_hashes(TARGET_DIR)),
            "protected_hashes_before": protected_before,
            "formal_performance_conclusion": False,
        }
        _json(report / "default_off_identity.json", default_off)
        _json(
            report / "decision.json",
            {
                "user_decision": "C8-1 independent stream is optional and disabled by default",
                "dynamic_stream_argument": None,
                "performance_conclusion": "NONE",
            },
        )
        _json(
            report / "metadata.json",
            {
                "schema": "resetp.c8-outsourcing-run-report.v1",
                "mode": "default_off_only",
                "source_instance_file_hashes": source_hashes_before,
                "protected_file_hashes": protected_before,
                "algorithm_performance_claim": False,
            },
        )
        (report / "report.md").write_text(
            "\n".join(
                [
                    REPORT_DONE_STATUS,
                    "",
                    "`FACT` 未指定动态流时，runner 保持动态关闭并返回原静态对象。",
                    "`FACT` 个体指纹、完整解哈希和已提交历史哈希逐位一致，见 `default_off_identity.json`。",
                    "`FACT` 统一算例和受保护文件前后哈希一致。",
                    "`INFERENCE` 本包只验证默认关闭接线，不形成算法性能结论。",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        _json(report / "done.json", payload)
        artifact_hashes = {
            path.name: _sha256_file(path)
            for path in sorted(report.iterdir())
            if path.is_file() and path.name != "artifact_hashes.json"
        }
        _json(report / "artifact_hashes.json", artifact_hashes)
        return payload

    if any(event.event_type != "new_customer" for event in stream.events):
        raise C8RunFailure(
            "minimum C8 insertion trial only accepts new_customer events; "
            "cancel/reduction enum remains declared but has no invented policy"
        )
    if not all(event.trigger_serviceable for event in stream.events):
        raise C8RunFailure("stream contains an order without trigger-time service opportunity")

    full_bundle = overlay_c8_bundle(bundle, stream)
    static_customer_ids = {
        node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"
    }
    active = set(static_customer_ids)
    events_by_id = {event.event_id: event for event in stream.events}
    current_solution = static_evaluation.prepared_solution
    current_certificate = static_evaluation.certificate
    current_state: DutyDynamicState | None = None
    current_future: Any | None = None
    stage_rows: list[dict[str, Any]] = []
    reveal_rows: list[dict[str, Any]] = []
    candidate_diagnostic_rows: list[dict[str, Any]] = []
    appearance_registry = {
        customer_id: 0.0 for customer_id in static_customer_ids
    }
    final_evaluation: Any | None = None
    final_bundle: Any | None = None
    final_state: DutyDynamicState | None = None
    outsourced_customer_ids: set[str] = set()

    for batch in stream.trigger_batches:
        batch_events = [events_by_id[event_id] for event_id in batch.event_ids]
        active.update(event.customer_id for event in batch_events)
        appearance_registry.update(
            {
                event.customer_id: float(event.appearance_second)
                for event in batch_events
            }
        )
        active_for_optimization = active.difference(outsourced_customer_ids)
        active_bundle = subset_c8_bundle(full_bundle, active_for_optimization)
        if base_context.rebuilt_route_constraints is None:
            raise C8RunFailure("unified target has no route contract to extend")
        route_contract = extend_route_contract(
            base_context.rebuilt_route_constraints,
            stream,
            active_for_optimization,
        )
        if current_state is None:
            cut = cut_certificate_at_trigger(
                current_solution,
                current_certificate,
                active_bundle.instance,
                active_bundle.prices,
                trigger_second=batch.trigger_second,
            )
            assets = _full_asset_registry(initial, cut, active_bundle)
            prior = Solution()
            source_solution = current_solution
            source_certificate = current_certificate
            certified_history = frozenset()
        else:
            if current_future is None:
                raise C8RunFailure("dynamic continuation is missing before next trigger")
            cut = cut_dynamic_certificate_at_trigger(
                current_future.future_solution,
                current_future.future_certificate,
                active_bundle.instance,
                active_bundle.prices,
                inherited_asset_states=current_state.asset_states,
                previous_stage_start_second=current_state.cut.trigger_second,
                trigger_second=batch.trigger_second,
                inherited_locked_charging_actions=current_state.cut.locked_charging_actions,
            )
            assets = MappingProxyType(dict(cut.asset_states))
            prior = _advance_prior_history(current_state)
            source_solution = current_future.future_solution
            source_certificate = current_future.future_certificate
            certified_history = frozenset(
                {
                    *current_state.certified_dynamic_route_ids,
                    *cut.completed_route_ids,
                    *cut.in_progress_route_ids,
                }
            )
        committed_route_ids = {
            *cut.completed_route_ids,
            *cut.in_progress_route_ids,
        }
        committed_customers = {
            node_id
            for route in (
                *prior.routes,
                *(route for route in source_solution.routes if route.vehicle_id in committed_route_ids),
            )
            for node_id in route.node_sequence[1:-1]
            if node_id in active_for_optimization
        }
        state = DutyDynamicState(
            source_solution=source_solution,
            cut=cut,
            asset_states=assets,
            future_customer_ids=frozenset(
                active_for_optimization.difference(committed_customers)
            ),
            customer_appearance_second={
                customer_id: second
                for customer_id, second in appearance_registry.items()
                if customer_id in active_for_optimization
            },
            charging_strategy="aware",
            charging_intensity_field="forecast_gco2_per_kwh",
            prior_committed_solution=prior,
            certified_dynamic_route_ids=certified_history,
        )
        initial_future = future_individual_from_cut(
            state,
            source_certificate,
            active_bundle.instance,
        )
        context = replace(
            base_context,
            bundle=active_bundle,
            rebuilt_route_constraints=route_contract,
            fairness_enabled=False,
            incremental_full_truth_sentinel_enabled=False,
            dynamic_state=state,
        )
        dynamic_evaluator = DutyFullEvaluator(context)
        dynamic_policy = _policy(dynamic_evaluator)
        revealed = tuple(event.customer_id for event in batch_events)
        insertion = DynamicInsertionOperator(
            enabled=True,
            random_seed=int(stream.seed) + int(batch.batch_index),
        )
        try:
            result = insertion.apply(
                initial_future,
                evaluator=dynamic_evaluator,
                charging_policy=dynamic_policy,
                newly_revealed_customer_ids=revealed,
                current_evaluation=(final_evaluation or static_evaluation),
            )
        except (DynamicInsertionFailure, TypeError, ValueError) as error:
            failure = f"{type(error).__name__}: {error}"
            reveal_rows.extend(
                _event_rows_for_stage(
                    batch=batch,
                    events_by_id=events_by_id,
                    result=None,
                    bundle=active_bundle,
                    active=active,
                    inserted=False,
                    failure_reason=failure,
                )
            )
            _write_csv(report / "raw_runs.csv", stage_rows)
            _write_csv(report / "reveal_results.csv", reveal_rows)
            _json(
                report / "failure_diagnostic.json",
                {
                    "batch_index": batch.batch_index,
                    "trigger_second": batch.trigger_second,
                    "trigger_cause": batch.cause,
                    "event_ids": list(batch.event_ids),
                    "customer_ids": list(batch.customer_ids),
                    "active_customer_count": len(active),
                    "active_customer_ids": sorted(active),
                    "error": failure,
                    "completed_stage_count": len(stage_rows),
                },
            )
            raise C8RunFailure(f"batch {batch.batch_index} insertion failed: {failure}") from error
        if result.status != INSERTED_AND_FULL_EVALUATION_FEASIBLE:
            failed_ids = set(result.outsourced_customer_ids) or set(revealed)
            if not failed_ids.issubset(set(revealed)):
                raise C8RunFailure(
                    f"batch {batch.batch_index} returned an outsourcing id outside its reveal"
                )
            outsourced_customer_ids.update(failed_ids)
            for customer_id in failed_ids:
                appearance_registry.pop(customer_id, None)
            reveal_rows.extend(
                _event_rows_for_stage(
                    batch=batch,
                    events_by_id=events_by_id,
                    result=result,
                    bundle=active_bundle,
                    active=active,
                    inserted=False,
                    outsourced_customer_ids=failed_ids,
                )
            )
            failed_evaluation = result.evaluation
            failed_served = (
                served_customer_ids(
                    failed_evaluation.prepared_solution,
                    active_bundle,
                )
                if failed_evaluation is not None
                else frozenset()
            )
            failed_completed = failed_served.intersection(active)
            failed_outsourcing_demand = sum(
                float(event.demand_kg)
                for event in batch_events
                if event.customer_id in failed_ids
            )
            failed_internal_cost = (
                float(failed_evaluation.total_cost)
                if failed_evaluation is not None
                else None
            )
            failed_internal_emissions = (
                _emissions(failed_evaluation)
                if failed_evaluation is not None
                else None
            )
            candidate_diagnostic_rows.append(
                _candidate_diagnostic_payload(batch.batch_index, result)
            )
            stage_rows.append(
                {
                    "trigger_batch_index": batch.batch_index,
                    "trigger_second": batch.trigger_second,
                    "trigger_cause": batch.cause,
                    "revealed_customer_ids": ";".join(revealed),
                    "revealed_demand_kg": batch.demand_kg,
                    "revealed_service_customer_count": 0,
                    "revealed_service_demand_kg": 0.0,
                    "active_customer_count": len(active),
                    "completed_customer_count": len(failed_completed),
                    "completed_demand_kg": _active_demand(
                        active_bundle,
                        failed_completed,
                    ),
                    "total_cost": "UNKNOWN (待用户定价)",
                    "emissions_kg": "UNKNOWN (外包排放未建模)",
                    "internal_total_cost_before_outsourcing": failed_internal_cost,
                    "internal_emissions_kg_before_outsourcing": failed_internal_emissions,
                    "insertion_result": result.status,
                    "outsourcing_customer_ids": ";".join(sorted(failed_ids)),
                    "outsourcing_customer_count": len(failed_ids),
                    "outsourcing_demand_kg": failed_outsourcing_demand,
                    "outsourcing_cost": "UNKNOWN (待用户定价)",
                    "failure_reason": result.failure_reason,
                    "metric_scope": (
                        "post_trigger_internal_solution_excluding_unpriced_outsourcing"
                    ),
                    "total_cost_including_outsourcing": "UNKNOWN (待用户定价)",
                    "emissions_kg_including_outsourcing": (
                        "UNKNOWN (外包排放未建模)"
                    ),
                    "committed_history_preserved": (
                        result.accounting.committed_sha256_before
                        == result.accounting.committed_sha256_after
                    ),
                    "committed_sha256_before": result.accounting.committed_sha256_before,
                    "committed_sha256_after": result.accounting.committed_sha256_after,
                    "kernel_moves": result.accounting.kernel_moves,
                    "complete_evaluations": result.accounting.complete_evaluations,
                    "candidate_attempt_count": result.accounting.candidate_attempt_count,
                    "candidate_feasible_count": result.accounting.candidate_feasible_count,
                    "candidate_failure_reason_count": len(
                        result.accounting.candidate_failure_reasons
                    ),
                    "candidate_diagnostics_ref": (
                        "candidate_diagnostics.json#trigger_batch_index="
                        + str(batch.batch_index)
                    ),
                }
            )
            _write_csv(report / "raw_runs.csv", stage_rows)
            _write_csv(report / "reveal_results.csv", reveal_rows)
            _json(
                report / "candidate_diagnostics.json",
                {
                    "schema": "resetp.c8-candidate-diagnostics.v1",
                    "batches": candidate_diagnostic_rows,
                },
            )
            continue
        if result.evaluation is None or not result.evaluation.feasible:
            raise C8RunFailure(f"batch {batch.batch_index} has no feasible full evaluation")
        served = served_customer_ids(result.evaluation.prepared_solution, active_bundle)
        if not set(revealed).issubset(served):
            raise C8RunFailure(f"batch {batch.batch_index} revealed order remains unserved")
        prepared_future = prepare_dynamic_candidate(
            result.individual,
            state,
            active_bundle,
            minimum_departure_second_by_customer_id={
                customer_id: float(route_contract.shift_window_second_by_id[shift][0])
                for customer_id, shift in route_contract.customer_shift_by_id.items()
            },
            shift_id_by_customer_id=route_contract.customer_shift_by_id,
        )
        reveal_rows.extend(
            _event_rows_for_stage(
                batch=batch,
                events_by_id=events_by_id,
                result=result,
                bundle=active_bundle,
                active=active,
                inserted=True,
            )
        )
        candidate_diagnostic_rows.append(
            _candidate_diagnostic_payload(batch.batch_index, result)
        )
        completed = served_customer_ids(result.evaluation.prepared_solution, active_bundle)
        stage_rows.append(
            {
                "trigger_batch_index": batch.batch_index,
                "trigger_second": batch.trigger_second,
                "trigger_cause": batch.cause,
                "revealed_customer_ids": ";".join(revealed),
                "revealed_demand_kg": batch.demand_kg,
                "revealed_service_customer_count": len(set(revealed).intersection(completed)),
                "revealed_service_demand_kg": _active_demand(active_bundle, set(revealed).intersection(completed)),
                "active_customer_count": len(active),
                "completed_customer_count": len(completed),
                "completed_demand_kg": _active_demand(active_bundle, completed),
                "total_cost": float(result.evaluation.total_cost),
                "emissions_kg": _emissions(result.evaluation),
                "internal_total_cost_before_outsourcing": float(result.evaluation.total_cost),
                "internal_emissions_kg_before_outsourcing": _emissions(result.evaluation),
                "insertion_result": result.status,
                "outsourcing_customer_ids": "",
                "outsourcing_customer_count": 0,
                "outsourcing_demand_kg": 0.0,
                "outsourcing_cost": 0.0,
                "failure_reason": "",
                "metric_scope": "post_trigger_full_active_solution",
                "total_cost_including_outsourcing": float(result.evaluation.total_cost),
                "emissions_kg_including_outsourcing": _emissions(result.evaluation),
                "committed_history_preserved": (
                    result.accounting.committed_sha256_before
                    == result.accounting.committed_sha256_after
                ),
                "committed_sha256_before": result.accounting.committed_sha256_before,
                "committed_sha256_after": result.accounting.committed_sha256_after,
                "kernel_moves": result.accounting.kernel_moves,
                "complete_evaluations": result.accounting.complete_evaluations,
                "candidate_attempt_count": result.accounting.candidate_attempt_count,
                "candidate_feasible_count": result.accounting.candidate_feasible_count,
                "candidate_failure_reason_count": len(
                    result.accounting.candidate_failure_reasons
                ),
                "candidate_diagnostics_ref": (
                    "candidate_diagnostics.json#trigger_batch_index="
                    + str(batch.batch_index)
                ),
            }
        )
        _write_csv(report / "raw_runs.csv", stage_rows)
        _write_csv(report / "reveal_results.csv", reveal_rows)
        _json(
            report / "candidate_diagnostics.json",
            {
                "schema": "resetp.c8-candidate-diagnostics.v1",
                "batches": candidate_diagnostic_rows,
            },
        )
        current_state = state
        current_future = prepared_future
        current_solution = prepared_future.future_solution
        current_certificate = prepared_future.future_certificate
        final_evaluation = result.evaluation
        final_bundle = active_bundle
        final_state = state

    if final_evaluation is None or final_bundle is None or final_state is None:
        raise C8RunFailure("stream has no trigger batch")
    expected_active = static_customer_ids.union(stream.dynamic_customer_ids)
    if active != expected_active:
        raise C8RunFailure("not all ten dynamic customers reached the active set")
    final_served = served_customer_ids(final_evaluation.prepared_solution, final_bundle)
    final_optimised = expected_active.difference(outsourced_customer_ids)
    if final_served != final_optimised:
        raise C8RunFailure(
            "final non-outsourced active set is not fully served by the complete evaluation"
        )
    final_outsourcing_demand = sum(
        float(event.demand_kg)
        for event in stream.events
        if event.customer_id in outsourced_customer_ids
    )
    final_internal_cost = float(final_evaluation.total_cost)
    final_internal_emissions = _emissions(final_evaluation)
    final_total_cost = (
        "UNKNOWN (待用户定价)"
        if outsourced_customer_ids
        else final_internal_cost
    )
    final_emissions = (
        "UNKNOWN (外包排放未建模)"
        if outsourced_customer_ids
        else final_internal_emissions
    )

    source_hashes_after = package_file_hashes(TARGET_DIR)
    source_hash_after = package_content_sha256(source_hashes_after)
    protected_after = {str(path.relative_to(repo)): _sha256_file(path) for path in PROTECTED}
    if source_hash_before != source_hash_after or source_hashes_before != source_hashes_after:
        raise C8RunFailure("unified target package changed during C8 run")
    if protected_before != protected_after:
        raise C8RunFailure("protected evaluator file hash changed during C8 run")

    _write_csv(report / "raw_runs.csv", stage_rows)
    _write_csv(report / "reveal_results.csv", reveal_rows)
    _json(
        report / "candidate_diagnostics.json",
        {
            "schema": "resetp.c8-candidate-diagnostics.v1",
            "batches": candidate_diagnostic_rows,
        },
    )
    shutil.copyfile(
        stream.stream_directory / "serviceability_check.csv",
        report / "serviceability_check.csv",
    )
    _json(report / "default_off_identity.json", default_off)
    _json(
        report / "decision.json",
        {
            "user_decision": "C8-2 keeps the stream immutable; outsourcing price remains user-reserved",
            "base_instance_id": C8_BASE_INSTANCE_ID,
            "protocol_transfer": c8_generation_rules(stream.protocol)["protocol_transfer"],
            "event_types_declared": list(stream.protocol.event_types),
            "minimum_trial_event_type": "new_customer",
            "cancel_and_reduction_policy": "UNKNOWN_NOT_INVENTED_FOR_THIS_MINIMUM_TRIAL",
            "performance_conclusion": "NONE",
        },
    )
    payload = {
        "status": REPORT_DONE_STATUS,
        "mode": "independent_stream_minimum_wiring_trial",
        "base_instance_id": C8_BASE_INSTANCE_ID,
        "stream_content_sha256": stream.stream_content_sha256,
        "stream_directory": str(stream.stream_directory),
        "trigger_batch_count": len(stream.trigger_batches),
        "dynamic_customer_count": len(stream.events),
        "static_customer_count": len(static_customer_ids),
        "final_active_customer_count": len(expected_active),
        "final_completed_customer_count": len(final_served),
        "final_completed_demand_kg": _active_demand(full_bundle, final_served),
        "final_outsourcing_customer_count": len(outsourced_customer_ids),
        "final_outsourcing_demand_kg": final_outsourcing_demand,
        "final_outsourcing_cost": (
            "UNKNOWN (待用户定价)" if outsourced_customer_ids else 0.0
        ),
        "final_internal_total_cost": final_internal_cost,
        "final_internal_emissions_kg": final_internal_emissions,
        "final_total_cost": final_total_cost,
        "final_emissions_kg": final_emissions,
        "source_instance_sha256_before": source_hash_before,
        "source_instance_sha256_after": source_hash_after,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
        "default_off_identity": default_off,
        "formal_performance_conclusion": False,
        "trial_scope": "reveal-trigger-insert-complete-evaluation only",
    }
    _json(report / "done.json", payload)
    _json(
        report / "metadata.json",
        {
            "schema": "resetp.c8-outsourcing-run-report.v1",
            "command_scope": "C8-2",
            "source_instance_file_hashes": source_hashes_before,
            "protected_file_hashes": protected_before,
            "stream_metadata_path": str(stream.stream_directory / "metadata.json"),
            "rules": c8_generation_rules(stream.protocol),
            "stage_count": len(stage_rows),
            "algorithm_performance_claim": False,
        },
    )
    report_text = [
        REPORT_DONE_STATUS,
        "",
        "`FACT` 第二问答案：没试全。原插入链先只调用一次 `repair_required` 并物化一个内核结果；完整评价在逐车候选枚举之前就因一条路线无可行时钟抛错。证据见 `solver/src/setp_solver/algorithms/problem_hgs/dynamic_insertion.py:444-471`、`solver/src/setp_solver/algorithms/problem_hgs/dynamic.py:283-371`、`solver/src/setp_solver/search/dynamic_multitrip_schedule.py:443-457,813-900,1510`。",
        "`INFERENCE` 因此批 5 原现场属于过早失败；本次修复先完成原生单候选，再逐一尝试每个实体车、每个可编辑既有趟位置和新趟，只有穷尽后才记外包。每个候选的编号和失败原因保存在 `candidate_diagnostics.json`，五批表通过 `candidate_diagnostics_ref` 指向对应批次。",
        "`FACT` 本次使用的统一算例是 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd`；",
        f"统一算例包前后内容哈希均为 `{source_hash_before}`，未改动算例本体。",
        f"`FACT` 独立流包含 {len(stream.events)} 个动态客户，触发 {len(stream.trigger_batches)} 批；最终活动客户 {len(expected_active)}，完成服务 {len(final_served)}，外包 {len(outsourced_customer_ids)} 个、需求量 {final_outsourcing_demand:.6f} kg。",
        "`FACT` 最小链已完成：订单揭示 → 协议触发 → 动态插入 → 完整评价；每批结果见 `raw_runs.csv`，逐单字段见 `reveal_results.csv`。",
        "`FACT` 5.3 动态表已增加 `outsourcing_customer_count`、`outsourcing_demand_kg`、`failure_reason`；外包批次的 `total_cost` 和 `outsourcing_cost` 写为 `UNKNOWN (待用户定价)`，数量仍为数值。",
        "`FACT` 默认关闭 no-op 的个体指纹、完整解哈希和已提交历史哈希相同，见 `default_off_identity.json`。",
        "`FACT` 每个动态订单的触发后直接服务机会见 `serviceability_check.csv`；本次生成规则只因可服务性重抽，不看成本或搜索结果。",
        "`INFERENCE` 本包证明的是接线与评价链贯通，不支持任何算法性能、成本改善或排放改善结论。",
        "`UNKNOWN` 取消配送和需求减少的具体运行策略未在本次最小试跑中发明；协议枚举已登记，后续若接入需另行定义并核验。",
        "",
        "协议移植：500 kg、30 min、08:00–10:00来自邱论文 p.59 表 5.6，产物已标明为协议移植，不是本算例调参。",
    ]
    (report / "report.md").write_text("\n".join(report_text) + "\n", encoding="utf-8")
    artifact_hashes = {
        path.name: _sha256_file(path)
        for path in sorted(report.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    _json(report / "artifact_hashes.json", artifact_hashes)
    return payload


def _write_halt(
    report: Path,
    error: BaseException,
    *,
    stream: C8DynamicStream | None = None,
) -> None:
    report.mkdir(parents=True, exist_ok=True)
    message = f"{type(error).__name__}: {error}"
    source_hashes = package_file_hashes(TARGET_DIR)
    source_hash = package_content_sha256(source_hashes)
    protected_hashes = {
        str(path.relative_to(REPO_ROOT)): _sha256_file(path)
        for path in PROTECTED
    }
    if stream is not None and stream.stream_directory is not None:
        shutil.copyfile(
            stream.stream_directory / "serviceability_check.csv",
            report / "serviceability_check.csv",
        )
    stage_count = 0
    if (report / "raw_runs.csv").is_file():
        with (report / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
            stage_count = sum(1 for _ in csv.DictReader(handle))
    payload = {
        "status": REPORT_HALT_STATUS,
        "error": message,
        "base_instance_id": C8_BASE_INSTANCE_ID,
        "stream_directory": (
            None if stream is None or stream.stream_directory is None
            else str(stream.stream_directory)
        ),
        "stream_content_sha256": None if stream is None else stream.stream_content_sha256,
        "completed_stage_count": stage_count,
        "source_instance_sha256": source_hash,
        "protected_file_hashes": protected_hashes,
        "formal_performance_conclusion": False,
    }
    (report / "report.md").write_text(
        "\n".join(
            [
                REPORT_HALT_STATUS,
                "",
                "`HALT` 最小动态链没有完成全流贯通：" + message,
                f"`FACT` 已完成的触发批次数：{stage_count}；失败现场见 `failure_diagnostic.json` 和 `reveal_results.csv`。",
                "`FACT` 逐单理论服务机会见 `serviceability_check.csv`；这张表不等于插入器已经找到可行路线。",
                "`INFERENCE` 当前阻断位于动态续接的精确时钟/候选构造，不足以归因于动态订单机制本身。",
                "`UNKNOWN` 剩余批次的插入、完整评价、成本与排放保持 UNKNOWN；本报告不下算法性能结论。",
                "协议移植：500 kg、30 min、08:00–10:00来自邱论文 p.59 表 5.6，已登记为协议移植。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _json(report / "done.json", payload)
    _json(
        report / "decision.json",
        {
            "user_decision": "C8-2 keeps the stream immutable; outsourcing price remains user-reserved",
            "protocol_transfer": "Qiu Yingying thesis p.59 table 5.6",
            "performance_conclusion": "NONE",
            "halt_reason": message,
        },
    )
    _json(
        report / "metadata.json",
        {
            "schema": "resetp.c8-outsourcing-run-report.v1",
            "status": REPORT_HALT_STATUS,
            "source_instance_file_hashes": source_hashes,
            "protected_file_hashes": protected_hashes,
            "stage_count_written": stage_count,
            "stream_metadata_path": (
                None
                if stream is None or stream.stream_directory is None
                else str(stream.stream_directory / "metadata.json")
            ),
            "algorithm_performance_claim": False,
        },
    )
    artifact_hashes = {
        path.name: _sha256_file(path)
        for path in sorted(report.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    _json(report / "artifact_hashes.json", artifact_hashes)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument("--dynamic-stream", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=REPORT_DEFAULT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo = args.repo.resolve()
    report = args.report
    if not report.is_absolute():
        report = repo / report
    if report.exists() and any(report.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite existing C8 report directory: {report}"
        )
    report.mkdir(parents=True, exist_ok=True)
    stream = None
    if args.dynamic_stream is not None:
        stream_path = args.dynamic_stream
        if not stream_path.is_absolute():
            stream_path = repo / stream_path
        stream = load_c8_stream(stream_path)
    try:
        payload = _run_chain(repo, report, stream)
    except (
        ArithmeticError,
        LookupError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as error:
        _write_halt(report, error, stream=stream)
        print(f"{REPORT_HALT_STATUS}: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
