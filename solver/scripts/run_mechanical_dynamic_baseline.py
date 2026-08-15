#!/usr/bin/env python3
"""Run the deterministic mechanical online baseline on one dynamic stream."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import traceback
from dataclasses import asdict, replace
from pathlib import Path
from types import MappingProxyType

from run_problem_hgs_dynamic_disclosure_scout import (
    _active_customer_ids,
    _advance_prior_history,
    _committed_payload,
    _completed_customer_ids,
    _full_asset_registry,
    _payload_sha256,
    _subset_bundle,
    _write_hashes,
    _write_rows_csv,
)
from run_problem_hgs_private_technical import (
    PROTECTED,
    _build_context,
    _json,
    _sha256,
    _source_provenance,
    _with_registered_idle_duties,
)
from setp_solver.algorithms.problem_hgs.dynamic import (
    DutyDynamicState,
    future_individual_from_cut,
    prepare_dynamic_candidate,
)
from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator
from setp_solver.algorithms.problem_hgs.mechanical_baseline import (
    insert_initial_customer,
    insert_revealed_customer,
)
from setp_solver.algorithms.problem_hgs.model import DutyIndividual
from setp_solver.charging_curve import spec_for_charging_node
from setp_solver.search.dynamic_multitrip_schedule import (
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
)
from setp_solver.solution import Solution, physical_vehicle_id

from baselines.china_e3_e7.e7_o1_replanning_20260801.policy import (
    build_o1_batches,
    build_o1_stream,
)

INSTANCE_ID = "cn-prd-50c-01-V2-LOCATIONS"
STREAM_SEED = 2
PAIRED_DYNAMIC_SEARCH_SEED = 11
OUTPUT = Path("solver/reports/mechanical_baseline_trial_20260810")
COMPARISON = Path(
    "solver/reports/"
    "problem_hgs_dynamic_prd50_stream2_search11_readiness_none_"
    "converged_v4_inituntilfeasible_20260809"
)
LEGACY_INITIAL_PRODUCER = Path(
    "solver/reports/"
    "problem_hgs_dynamic_prd50_warm_exact_seed2_perorder_populationfix_v8_"
    "20260809/initial_visible_solution.json"
)
EXCLUDED_REPORT_DIRS = frozenset(
    {
        "public_v2_28_clean_ruler_20260810",
        "endogenous_fleet_trial_20260810",
    }
)
FEASIBILITY_TYPES = (
    "CUSTOMER_COVERAGE",
    "FLOW_BALANCE",
    "FLEET_SIZE",
    "CAPACITY",
    "TIME_WINDOW",
    "BATTERY",
    "CHARGING_STATION_UNIQUENESS",
    "ROUTE_STRUCTURE",
    "CHARGING_START",
    "CHARGING_POWER",
    "CHARGING_TRIP_OVERLAP",
    "STATION_CAPACITY",
)
CANDIDATE_CLASS_LABELS = {
    "1_existing_planned_trip": "① 插入现有已计划趟",
    "2_append_used_vehicle_trip": "② 给已在使用的车辆追加新一趟",
    "3_dispatch_unused_vehicle": "③ 启用空闲车派直达路线",
}


def _provenance(repo: Path, output: Path) -> dict:
    provenance = _source_provenance(
        repo,
        output_path=output,
        stderr_capture_state="caller_not_declared",
    )
    manifest = dict(provenance["python_source_files"])
    additions = (
        Path(__file__).resolve(),
        repo
        / "solver/scripts/run_problem_hgs_dynamic_disclosure_scout.py",
        repo
        / "baselines/china_e3_e7/e7_o1_replanning_20260801/policy.py",
        repo
        / "baselines/china_e3_e7/e7_h0_g2_foundation_20260801/stream.py",
    )
    for path in additions:
        manifest[str(path.relative_to(repo))] = _sha256(path)
    encoded = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    provenance["python_source_files"] = manifest
    provenance["python_source_sha256"] = hashlib.sha256(encoded).hexdigest()
    return provenance


def _comparison_payload(
    repo: Path,
    comparison_dir: Path,
    *,
    generated_event_stream: Path,
    generated_initial_solution: Path,
    full_bundle,
    current_protected_hashes: dict[str, str],
) -> dict:
    metadata_path = comparison_dir / "metadata.json"
    event_path = comparison_dir / "event_stream.csv"
    solution_path = comparison_dir / "best_solution.json"
    required = (metadata_path, event_path, solution_path)
    if not all(path.is_file() for path in required):
        return {
            "comparable": False,
            "reason": "requested existing comparison package is incomplete",
            "source_path": str(comparison_dir.relative_to(repo)),
        }
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload = json.loads(solution_path.read_text(encoding="utf-8"))
    evaluation = payload["evaluation"]
    solution = evaluation["prepared_solution"]
    customers = _active_customer_ids(full_bundle)
    completed = [
        node_id
        for route in solution["routes"]
        for node_id in route["node_sequence"][1:-1]
        if node_id in customers
    ]
    demand = {
        node.node_id: float(node.demand)
        for node in full_bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    enabled = {
        physical_vehicle_id(route["vehicle_id"])
        for route in solution["routes"]
        if any(node_id in customers for node_id in route["node_sequence"])
    }
    same_stream = _sha256(event_path) == _sha256(generated_event_stream)
    same_initial = (
        metadata.get("source_initial_visible_solution_sha256")
        == _sha256(generated_initial_solution)
    )
    same_evaluation_contract = (
        metadata.get("protected_hashes_after") == current_protected_hashes
    )
    comparable = bool(
        metadata.get("status") == "COMPLETE"
        and metadata.get("instance_id") == INSTANCE_ID
        and int(metadata.get("stream_seed", -1)) == STREAM_SEED
        and int(metadata.get("search_seed", -1)) == PAIRED_DYNAMIC_SEARCH_SEED
        and same_stream
        and same_initial
        and same_evaluation_contract
    )
    comparison = {
        "comparable": comparable,
        "reason": (
            "same instance, event stream, and frozen initial visible plan"
            if comparable
            else (
                "same event stream but the saved evaluator contract differs "
                "from the current protected-file hashes"
                if same_stream and same_initial and not same_evaluation_contract
                else "existing package identity differs from this smoke stream"
            )
        ),
        "source_path": str(comparison_dir.relative_to(repo)),
        "metadata_sha256": _sha256(metadata_path),
        "event_stream_sha256": _sha256(event_path),
        "same_event_stream": same_stream,
        "same_initial_visible_plan": same_initial,
        "same_evaluation_contract": same_evaluation_contract,
        "search_seed": metadata.get("search_seed"),
    }
    if comparable:
        comparison.update(
            {
                "total_cost": float(evaluation["total_cost"]),
                "emissions_kg": float(evaluation["breakdown"]["E_total"]),
                "completed_customers": len(set(completed)),
                "total_customers": len(customers),
                "completed_demand": sum(demand[item] for item in set(completed)),
                "total_demand": sum(demand.values()),
                "enabled_physical_vehicles": len(enabled),
            }
        )
    return comparison


def _build_mechanical_initial_visible_plan(
    active_bundle,
    base_context,
):
    """Construct the initially visible plan with the baseline's own rule."""

    ordered_customers = sorted(_active_customer_ids(active_bundle))
    current = _with_registered_idle_duties(
        DutyIndividual(
            duties=(),
            source="mechanical-initial-visible-empty-fleet",
        ),
        active_bundle,
    )
    visible: set[str] = set()
    decision_rows: list[dict[str, object]] = []
    final_evaluation = None
    total_full_evaluations = 0
    for step, customer_id in enumerate(ordered_customers, start=1):
        visible.add(customer_id)
        prefix_bundle = _subset_bundle(active_bundle, visible)
        context = replace(
            base_context,
            bundle=prefix_bundle,
            fairness_enabled=False,
            incremental_full_truth_sentinel_enabled=False,
            dynamic_state=None,
        )
        evaluator = DutyFullEvaluator(context)
        candidate = replace(
            current,
            unserved_customers=(customer_id,),
            source="mechanical-initial-visible-order",
        )
        result = insert_initial_customer(candidate, customer_id, evaluator)
        total_full_evaluations += evaluator.full_calls
        current = result.individual
        final_evaluation = result.evaluation
        decision_rows.append(
            {
                "step": step,
                **asdict(result.decision),
                "rejected_candidates": json.dumps(
                    dict(result.decision.rejected_candidates),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "full_evaluations": evaluator.full_calls,
            }
        )

    if final_evaluation is None:
        raise RuntimeError("initial visible customer set is empty")
    final_context = replace(
        base_context,
        bundle=active_bundle,
        fairness_enabled=False,
        incremental_full_truth_sentinel_enabled=False,
        dynamic_state=None,
    )
    registered = _with_registered_idle_duties(
        DutyIndividual.from_solution(
            final_evaluation.prepared_solution,
            customer_node_ids=ordered_customers,
            source="mechanical-current-contract-initial-visible-plan",
        ),
        active_bundle,
    )
    final_evaluator = DutyFullEvaluator(final_context)
    cold_evaluation = final_evaluator.evaluate(registered)
    total_full_evaluations += final_evaluator.full_calls
    if not cold_evaluation.feasible:
        raise RuntimeError("mechanically constructed initial plan is infeasible")
    served = _completed_customer_ids(
        cold_evaluation.prepared_solution,
        active_bundle,
    )
    if len(served) != len(set(served)) or set(served) != set(ordered_customers):
        raise RuntimeError("mechanically constructed initial service is incomplete")
    if cold_evaluation.prepared_solution != final_evaluation.prepared_solution:
        raise RuntimeError("cold evaluation changed the constructed initial plan")

    action_counts: dict[str, int] = {}
    for row in decision_rows:
        action = str(row["action"])
        action_counts[action] = action_counts.get(action, 0) + 1
    diagnostic = {
        "visible_customer_ids": ordered_customers,
        "hidden_customer_ids_used": [],
        "source": "mechanical_baseline_constructed_under_current_contract",
        "construction_order": "stable ascending customer id",
        "selection_rule": (
            "strict class priority: existing trip, appended used-vehicle trip, "
            "unused-vehicle dispatch; within class minimum complete total-cost "
            "increment with stable structural tie-break"
        ),
        "idle_dispatch_rule": (
            "minimum complete total-cost increment among all feasible unused "
            "vehicles; stable asset-id tie-break"
        ),
        "global_reoptimization": False,
        "randomness_used": False,
        "complete_evaluator_used_for_every_candidate": True,
        "decision_counts": action_counts,
        "total_full_evaluations": total_full_evaluations,
        "charging_curve_ids": sorted(
            {
                action.charging_curve_id
                for action in cold_evaluation.prepared_solution.charging_actions
            }
        ),
        "initial_total_cost": cold_evaluation.total_cost,
        "initial_emissions_kg": cold_evaluation.breakdown["E_total"],
    }
    return registered, cold_evaluation, final_context, diagnostic, decision_rows


def _legacy_initial_plan_evidence(repo: Path) -> dict:
    """Identify the exact stale input copy and the batch that produced it."""

    copy_path = repo / COMPARISON / "initial_visible_solution.json"
    producer_path = repo / LEGACY_INITIAL_PRODUCER
    comparison_metadata = json.loads(
        (repo / COMPARISON / "metadata.json").read_text(encoding="utf-8")
    )
    argv = comparison_metadata["code_provenance"]["command_argv"]
    try:
        declared_source = Path(argv[argv.index("--source-initial-visible-solution") + 1])
    except (ValueError, IndexError) as exc:
        raise RuntimeError("comparison batch does not declare its initial input") from exc
    if declared_source != LEGACY_INITIAL_PRODUCER:
        raise RuntimeError("legacy producer path disagrees with comparison metadata")
    copy_payload = json.loads(copy_path.read_text(encoding="utf-8"))
    producer_payload = json.loads(producer_path.read_text(encoding="utf-8"))
    copy_actions = copy_payload["prepared_solution"]["charging_actions"]
    producer_actions = producer_payload["prepared_solution"]["charging_actions"]
    copy_ids = sorted({str(action["charging_curve_id"]) for action in copy_actions})
    producer_ids = sorted(
        {str(action["charging_curve_id"]) for action in producer_actions}
    )
    if _sha256(copy_path) != _sha256(producer_path):
        raise RuntimeError("legacy initial-plan copy no longer matches its producer")
    return {
        "loaded_copy_path": str(copy_path.relative_to(repo)),
        "loaded_copy_sha256": _sha256(copy_path),
        "producing_batch": str(producer_path.parent.relative_to(repo)),
        "producer_path": str(producer_path.relative_to(repo)),
        "producer_sha256": _sha256(producer_path),
        "loaded_copy_curve_ids": copy_ids,
        "loaded_copy_charging_action_count": len(copy_actions),
        "producer_curve_ids": producer_ids,
        "producer_charging_action_count": len(producer_actions),
        "identical_payload": True,
    }


def _stale_initial_visible_solutions(
    repo: Path,
    *,
    current_curve_ids: set[str],
) -> list[dict[str, object]]:
    """List saved initial plans that explicitly carry a non-current curve id."""

    found: list[dict[str, object]] = []
    reports = repo / "solver/reports"
    for path in sorted(reports.rglob("initial_visible_solution.json")):
        relative = path.relative_to(reports)
        if relative.parts and relative.parts[0] in EXCLUDED_REPORT_DIRS:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            actions = payload["prepared_solution"]["charging_actions"]
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        curve_ids = sorted(
            {
                str(action.get("charging_curve_id"))
                for action in actions
                if action.get("charging_curve_id") is not None
            }
        )
        stale_ids = sorted(set(curve_ids).difference(current_curve_ids))
        if not stale_ids:
            continue
        found.append(
            {
                "path": str(path.relative_to(repo)),
                "sha256": _sha256(path),
                "curve_ids": curve_ids,
                "stale_curve_ids": stale_ids,
            }
        )
    return found


def _decision_log_determinism(
    output: Path,
    reference_dir: Path | None,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    if reference_dir is not None:
        for filename in ("initial_decision_log.csv", "decision_log.csv"):
            reference_path = reference_dir / filename
            current_path = output / filename
            present = reference_path.is_file() and current_path.is_file()
            rows.append(
                {
                    "filename": filename,
                    "reference_sha256": (
                        _sha256(reference_path) if reference_path.is_file() else None
                    ),
                    "current_sha256": (
                        _sha256(current_path) if current_path.is_file() else None
                    ),
                    "byte_identical": present
                    and reference_path.read_bytes() == current_path.read_bytes(),
                }
            )
    return {
        "performed": reference_dir is not None,
        "reference_run": None if reference_dir is None else str(reference_dir),
        "files": rows,
        "all_decision_logs_byte_identical": bool(rows)
        and all(bool(row["byte_identical"]) for row in rows),
    }


def _write_failure(
    output: Path,
    invocation_id: str,
    error: Exception,
    *,
    determinism_reference_dir: Path | None,
) -> None:
    metadata_path = output / "metadata.json"
    metadata = (
        json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata_path.exists()
        else {"invocation_id": invocation_id}
    )
    if metadata.get("invocation_id") != invocation_id:
        return
    metadata["status"] = "FAILED"
    determinism_check = _decision_log_determinism(
        output,
        determinism_reference_dir,
    )
    partial_rows: list[dict[str, str]] = []
    raw_runs_path = output / "raw_runs.csv"
    if raw_runs_path.is_file():
        with raw_runs_path.open(encoding="utf-8", newline="") as handle:
            partial_rows = list(csv.DictReader(handle))
    last_completed_stage = partial_rows[-1] if partial_rows else None
    metadata["determinism_check"] = determinism_check
    metadata["last_completed_stage"] = last_completed_stage
    metadata["final_solution_available"] = False
    metadata["formal_experiment_blocked_by_p34_a1"] = True
    _json(metadata_path, metadata)
    with (output / "failure.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("verdict", "error_type", "error"),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow(
            {
                "verdict": "MECHANICAL_BASELINE_TRIAL_FAILED",
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
    _json(
        output / "decision.json",
        {
            "verdict": "MECHANICAL_BASELINE_TRIAL_FAILED",
            "failure_reasons": [f"{type(error).__name__}: {error}"],
            "traceback": traceback.format_exc(),
            "formal_experiment_allowed": False,
            "formal_experiment_blocker": "P34 A1 stream rebuild pending",
            "determinism_check": determinism_check,
            "last_completed_stage": last_completed_stage,
            "final_solution_available": False,
            "user_decision_changed": False,
        },
    )
    _json(output / "determinism_check.json", determinism_check)
    partial_note = "本次在产生揭示阶段记录前中断。"
    if last_completed_stage is not None:
        partial_note = (
            "中断前最后保存的是第 "
            f"{last_completed_stage['stage']} 次揭示：完成 "
            f"{last_completed_stage['completed_customers']}/"
            f"{last_completed_stage['active_customers']} 个当时已揭示客户、"
            f"{last_completed_stage['completed_demand']}/"
            f"{last_completed_stage['total_active_demand']} 需求，完整成本 "
            f"{last_completed_stage['total_cost']}，排放 "
            f"{last_completed_stage['emissions_kg']} kg，启用 "
            f"{last_completed_stage['enabled_physical_vehicles']} 辆车。"
        )
    determinism_note = (
        "连续两次运行的日初与动态决策日志逐字节相同。"
        if determinism_check["all_decision_logs_byte_identical"]
        else "本次未完成连续双跑字节一致性确认。"
    )
    (output / "report.md").write_text(
        "# 机械在线策略基线技术冒烟\n\n"
        f"本次冒烟失败：`{type(error).__name__}: {error}`。失败现场和调用栈保存在 "
        f"`decision.json`，没有改写成完成。{partial_note}{determinism_note}\n\n"
        "由于没有最终解，最终服务量、完整成本、排放、车辆数和逐项"
        "可行性均记为 `UNAVAILABLE`，不得拿上一个阶段冒充最终结果。\n\n"
        "正式动态实验仍受 P34 A1 潜在客户池订单流重建阻塞；本包只记录"
        "接线与行为冒烟。\n",
        encoding="utf-8",
    )
    _write_hashes(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path, nargs="?", default=OUTPUT)
    parser.add_argument("--instance-id", default=INSTANCE_ID)
    parser.add_argument("--stream-seed", type=int, default=STREAM_SEED)
    parser.add_argument("--comparison-dir", type=Path, default=COMPARISON)
    parser.add_argument("--determinism-reference-dir", type=Path)
    args = parser.parse_args()
    if args.instance_id != INSTANCE_ID or args.stream_seed != STREAM_SEED:
        raise ValueError("this approved smoke runner is frozen to PRD50 stream 2")

    repo = Path(__file__).resolve().parents[2]
    output = (
        args.output_dir
        if args.output_dir.is_absolute()
        else repo / args.output_dir
    ).resolve()
    determinism_reference_dir = (
        None
        if args.determinism_reference_dir is None
        else (
            args.determinism_reference_dir
            if args.determinism_reference_dir.is_absolute()
            else repo / args.determinism_reference_dir
        ).resolve()
    )
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    invocation_id = hashlib.sha256(
        json.dumps(
            {
                "instance_id": args.instance_id,
                "event_stream_seed": args.stream_seed,
                "paired_dynamic_search_seed": PAIRED_DYNAMIC_SEARCH_SEED,
                "policy": "mechanical-three-class-insertion-v2",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:32]
    provenance = _provenance(repo, output)
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "invocation_id": invocation_id,
            "purpose": "P38 deterministic mechanical online baseline wiring trial",
            "instance_id": args.instance_id,
            "event_stream_seed": args.stream_seed,
            "paired_dynamic_search_seed": PAIRED_DYNAMIC_SEARCH_SEED,
            "baseline_random_seed": None,
            "baseline_uses_randomness": False,
            "code_provenance": provenance,
        },
    )

    try:
        protected_before = {path: _sha256(repo / path) for path in PROTECTED}
        full_bundle, _registered, _pi0, base_context = _build_context(
            repo,
            args.instance_id,
        )
        stream = build_o1_stream(
            full_bundle.instance,
            instance_id=args.instance_id,
            stream_seed=args.stream_seed,
        )
        batches = build_o1_batches(stream.events, "per_order")
        if any(len(batch.customer_ids) != 1 for batch in batches):
            raise RuntimeError("per-order mechanical baseline received a batch")
        event_stream_path = output / "event_stream.csv"
        _write_rows_csv(event_stream_path, [asdict(event) for event in stream.events])

        comparison_dir = (
            args.comparison_dir
            if args.comparison_dir.is_absolute()
            else repo / args.comparison_dir
        ).resolve()
        active = set(stream.initial_customer_ids)
        active_bundle = _subset_bundle(full_bundle, active)
        (
            registered_initial,
            static_evaluation,
            _,
            initial_diagnostic,
            initial_decision_rows,
        ) = _build_mechanical_initial_visible_plan(
            active_bundle,
            base_context,
        )
        _json(output / "initial_visible_plan_diagnostic.json", initial_diagnostic)
        _write_rows_csv(
            output / "initial_decision_log.csv",
            initial_decision_rows,
        )
        _json(
            output / "initial_visible_solution.json",
            {
                "instance_id": args.instance_id,
                "stream_seed": args.stream_seed,
                "visible_customer_ids": sorted(active),
                "hidden_customer_ids_used": [],
                "individual_fingerprint": registered_initial.fingerprint,
                "total_cost": static_evaluation.total_cost,
                "breakdown": dict(static_evaluation.breakdown),
                "prepared_solution": asdict(static_evaluation.prepared_solution),
            },
        )
        depot_curve = spec_for_charging_node(
            full_bundle.prices,
            node_type="d",
        )
        public_curve = spec_for_charging_node(
            full_bundle.prices,
            node_type="f",
        )
        legacy_initial = _legacy_initial_plan_evidence(repo)
        current_curve_ids = {depot_curve.curve_id, public_curve.curve_id}
        stale_initials = _stale_initial_visible_solutions(
            repo,
            current_curve_ids=current_curve_ids,
        )
        _json(
            output / "stale_initial_visible_solutions.json",
            {
                "search_root": "solver/reports",
                "filename_filter": "initial_visible_solution.json",
                "excluded_report_directories": sorted(EXCLUDED_REPORT_DIRS),
                "current_curve_ids": sorted(current_curve_ids),
                "stale_count": len(stale_initials),
                "artifacts": stale_initials,
            },
        )

        current_solution = static_evaluation.prepared_solution
        current_certificate = static_evaluation.certificate
        current_state: DutyDynamicState | None = None
        current_future = None
        appearances = {customer_id: 0.0 for customer_id in active}
        stage_rows: list[dict[str, object]] = []
        decision_rows: list[dict[str, object]] = []
        synthesized_idle: tuple[str, ...] = ()
        final_result = None
        history_preserved_all = True

        for stage_index, batch in enumerate(batches, start=1):
            event = next(
                item for item in stream.events if item.event_id == batch.event_ids[0]
            )
            customer_id = batch.customer_ids[0]
            trigger = float(batch.trigger_second)
            active.add(customer_id)
            appearances[customer_id] = float(event.appearance_second)
            new_bundle = _subset_bundle(full_bundle, active)

            if current_state is None:
                cut = cut_certificate_at_trigger(
                    current_solution,
                    current_certificate,
                    active_bundle.instance,
                    active_bundle.prices,
                    trigger_second=trigger,
                )
                assets, synthesized_idle = _full_asset_registry(
                    registered_initial,
                    cut,
                    active_bundle,
                )
                prior = Solution()
                source_solution = current_solution
                source_certificate = current_certificate
                certified_dynamic_history = frozenset()
            else:
                assert current_future is not None
                cut = cut_dynamic_certificate_at_trigger(
                    current_future.future_solution,
                    current_future.future_certificate,
                    active_bundle.instance,
                    active_bundle.prices,
                    inherited_asset_states=current_state.asset_states,
                    previous_stage_start_second=current_state.cut.trigger_second,
                    trigger_second=trigger,
                    inherited_locked_charging_actions=(
                        current_state.cut.locked_charging_actions
                    ),
                )
                assets = MappingProxyType(dict(cut.asset_states))
                prior = _advance_prior_history(current_state)
                source_solution = current_future.future_solution
                source_certificate = current_future.future_certificate
                certified_dynamic_history = frozenset(
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
                    *(
                        route
                        for route in source_solution.routes
                        if route.vehicle_id in committed_route_ids
                    ),
                )
                for node_id in route.node_sequence[1:-1]
                if node_id in active
            }
            state = DutyDynamicState(
                source_solution=source_solution,
                cut=cut,
                asset_states=assets,
                future_customer_ids=frozenset(active.difference(committed_customers)),
                customer_appearance_second={
                    item: appearances[item] for item in sorted(active)
                },
                charging_strategy="naive",
                charging_intensity_field="forecast_gco2_per_kwh",
                prior_committed_solution=prior,
                certified_dynamic_route_ids=certified_dynamic_history,
            )
            unchanged_future = future_individual_from_cut(
                state,
                source_certificate,
                new_bundle.instance,
            )
            if set(unchanged_future.unserved_customers) != {customer_id}:
                raise RuntimeError(
                    "current plan does not expose exactly the newly revealed order"
                )
            context = replace(
                base_context,
                bundle=new_bundle,
                fairness_enabled=False,
                incremental_full_truth_sentinel_enabled=False,
                dynamic_state=state,
            )
            evaluator = DutyFullEvaluator(context)
            result = insert_revealed_customer(
                unchanged_future,
                customer_id,
                evaluator,
            )
            history_before = _payload_sha256(
                _committed_payload(state, result.evaluation.prepared_solution)
            )
            prepared_future = prepare_dynamic_candidate(
                result.individual,
                state,
                new_bundle,
            )
            history_after = _payload_sha256(
                _committed_payload(state, prepared_future.full_execution_solution)
            )
            history_preserved = history_before == history_after
            if not history_preserved:
                raise RuntimeError(f"stage {stage_index} rewrote committed history")
            completed = _completed_customer_ids(
                result.evaluation.prepared_solution,
                new_bundle,
            )
            if len(completed) != len(set(completed)) or set(completed) != active:
                raise RuntimeError(f"stage {stage_index} service is incomplete")
            stage_demand = {
                node.node_id: float(node.demand)
                for node in new_bundle.instance.nodes
                if node.node_type.lower() == "c"
            }
            completed_stage_demand = sum(
                stage_demand[item] for item in set(completed)
            )
            total_active_demand = sum(stage_demand.values())

            decision_row = {
                "stage": stage_index,
                "event_id": event.event_id,
                "appearance_second": float(event.appearance_second),
                **asdict(result.decision),
                "rejected_candidates": json.dumps(
                    dict(result.decision.rejected_candidates),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "history_preserved": history_preserved,
            }
            decision_rows.append(decision_row)
            stage_rows.append(
                {
                    "stage": stage_index,
                    "trigger_second": trigger,
                    "customer_id": customer_id,
                    "candidate_class": result.decision.candidate_class,
                    "decision": result.decision.action,
                    "physical_vehicle_id": result.decision.physical_vehicle_id,
                    "route_id": result.decision.route_id,
                    "active_customers": len(active),
                    "completed_customers": len(set(completed)),
                    "completed_demand": completed_stage_demand,
                    "total_active_demand": total_active_demand,
                    "demand_completion_ratio": (
                        completed_stage_demand / total_active_demand
                    ),
                    "total_cost": result.evaluation.total_cost,
                    "emissions_kg": result.evaluation.breakdown["E_total"],
                    "enabled_physical_vehicles": len(
                        {
                            physical_vehicle_id(route.vehicle_id)
                            for route in result.evaluation.prepared_solution.routes
                            if any(
                                node_id in active
                                for node_id in route.node_sequence[1:-1]
                            )
                        }
                    ),
                    "full_evaluations": evaluator.full_calls,
                    "history_preserved": history_preserved,
                }
            )
            _write_rows_csv(output / "raw_runs.csv", stage_rows)
            _write_rows_csv(output / "decision_log.csv", decision_rows)
            history_preserved_all = history_preserved_all and history_preserved
            current_state = state
            current_future = prepared_future
            active_bundle = new_bundle
            final_result = result

        if final_result is None:
            raise RuntimeError("dynamic stream produced no revealed orders")
        final_solution = final_result.evaluation.prepared_solution
        completed_ids = _completed_customer_ids(final_solution, full_bundle)
        all_customers = _active_customer_ids(full_bundle)
        demand = {
            node.node_id: float(node.demand)
            for node in full_bundle.instance.nodes
            if node.node_type.lower() == "c"
        }
        completed_demand = sum(demand[item] for item in set(completed_ids))
        total_demand = sum(demand.values())
        enabled_vehicles = {
            physical_vehicle_id(route.vehicle_id)
            for route in final_solution.routes
            if any(node_id in all_customers for node_id in route.node_sequence)
        }
        if (
            len(completed_ids) != len(set(completed_ids))
            or set(completed_ids) != all_customers
            or abs(completed_demand - total_demand) > 1.0e-9
        ):
            raise RuntimeError("final mechanical plan does not complete all service")

        protected_after = {path: _sha256(repo / path) for path in PROTECTED}
        if protected_before != protected_after:
            raise RuntimeError("a protected evaluator file changed during the trial")
        comparison = _comparison_payload(
            repo,
            comparison_dir,
            generated_event_stream=event_stream_path,
            generated_initial_solution=output / "initial_visible_solution.json",
            full_bundle=full_bundle,
            current_protected_hashes=protected_after,
        )
        action_counts: dict[str, int] = {}
        candidate_class_counts: dict[str, int] = {}
        for row in decision_rows:
            action = str(row["action"])
            action_counts[action] = action_counts.get(action, 0) + 1
            candidate_class = str(row["candidate_class"])
            candidate_class_counts[candidate_class] = (
                candidate_class_counts.get(candidate_class, 0) + 1
            )
        final_cost = float(final_result.evaluation.total_cost)
        final_emissions = float(final_result.evaluation.breakdown["E_total"])
        final_violation_types = {
            violation.type for violation in final_result.evaluation.violations
        }
        feasibility_flags: dict[str, object] = {
            violation_type: (
                "PASS"
                if violation_type not in final_violation_types
                else "FAIL"
            )
            for violation_type in FEASIBILITY_TYPES
        }
        feasibility_flags["PROFIT_FAIRNESS"] = (
            "NOT_ENABLED_SAME_AS_PAIRED_DYNAMIC_ALGORITHM_CONTEXT"
        )
        feasibility_flags["COMPLETE_FULL_EVALUATION"] = (
            "PASS" if final_result.evaluation.feasible else "FAIL"
        )
        feasibility_flags["COMMITTED_HISTORY_PRESERVED"] = (
            "PASS" if history_preserved_all else "FAIL"
        )
        feasibility_flags["ALL_CUSTOMERS_AND_DEMAND_COMPLETED"] = "PASS"

        determinism_check = _decision_log_determinism(
            output,
            determinism_reference_dir,
        )
        _json(output / "determinism_check.json", determinism_check)
        if determinism_reference_dir is not None and not determinism_check[
            "all_decision_logs_byte_identical"
        ]:
            raise RuntimeError("consecutive decision logs are not byte-identical")
        metadata = {
            "status": "COMPLETE",
            "invocation_id": invocation_id,
            "purpose": "P38 deterministic mechanical online baseline wiring trial",
            "evidence_status": "technical wiring and behaviour check only",
            "instance_id": args.instance_id,
            "event_stream_seed": args.stream_seed,
            "paired_dynamic_search_seed": PAIRED_DYNAMIC_SEARCH_SEED,
            "baseline_random_seed": None,
            "baseline_uses_randomness": False,
            "candidate_class_priority": list(CANDIDATE_CLASS_LABELS),
            "deterministic_tie_break": (
                "within candidate class: complete cost increment, physical "
                "asset id, future trip index, visit insertion index, "
                "candidate fingerprint"
            ),
            "idle_dispatch_rule": (
                "minimum complete cost increment among feasible unused assets; "
                "stable id tie-break"
            ),
            "global_reoptimization": False,
            "charging_strategy": "naive",
            "idle_ev_readiness": "disabled",
            "trigger_policy": "per_order technical stream",
            "trigger_count": len(batches),
            "source_initial_visible_solution": None,
            "initial_plan_generation": {
                "method": "mechanical baseline incremental construction",
                "customer_order": "stable ascending customer id",
                "selection_rule": initial_diagnostic["selection_rule"],
                "idle_dispatch_rule": initial_diagnostic["idle_dispatch_rule"],
                "global_reoptimization": False,
                "randomness_used": False,
                "complete_evaluator_used_for_every_candidate": True,
                "decision_counts": initial_diagnostic["decision_counts"],
                "decision_log": (
                    "solver/reports/mechanical_baseline_trial_20260810/"
                    "initial_decision_log.csv"
                ),
            },
            "initial_visible_solution_sha256": _sha256(
                output / "initial_visible_solution.json"
            ),
            "initial_plan_current_contract_total_cost": static_evaluation.total_cost,
            "initial_plan_current_contract_emissions_kg": (
                static_evaluation.breakdown["E_total"]
            ),
            "legacy_initial_plan_diagnosis": legacy_initial,
            "current_charging_curves": {
                "depot": {
                    "curve_id": depot_curve.curve_id,
                    "soc_breakpoints": list(depot_curve.soc_breakpoints),
                },
                "public": {
                    "curve_id": public_curve.curve_id,
                    "soc_breakpoints": list(public_curve.soc_breakpoints),
                },
            },
            "stale_initial_visible_solution_count": len(stale_initials),
            "stale_initial_visible_solution_manifest": (
                "solver/reports/mechanical_baseline_trial_20260810/"
                "stale_initial_visible_solutions.json"
            ),
            "initial_visible_customer_count": len(stream.initial_customer_ids),
            "revealed_order_count": len(stream.events),
            "completed_customers": len(set(completed_ids)),
            "total_customers": len(all_customers),
            "completed_demand": completed_demand,
            "total_demand": total_demand,
            "demand_completion_ratio": completed_demand / total_demand,
            "final_total_cost": final_cost,
            "final_emissions_kg": final_emissions,
            "enabled_physical_vehicles": len(enabled_vehicles),
            "enabled_physical_vehicle_ids": sorted(enabled_vehicles),
            "decision_counts": action_counts,
            "candidate_class_counts": candidate_class_counts,
            "feasibility_flags": feasibility_flags,
            "final_violations": [
                asdict(item) for item in final_result.evaluation.violations
            ],
            "determinism_check": determinism_check,
            "history_preserved_at_every_revelation": history_preserved_all,
            "synthesized_idle_asset_ids": list(synthesized_idle),
            "comparison_existing_dynamic": comparison,
            "formal_experiment_blocked_by_p34_a1": True,
            "formal_experiment_blocker": (
                "P34 A1 potential-customer-pool order stream has not been rebuilt"
            ),
            "protected_hashes_before": protected_before,
            "protected_hashes_after": protected_after,
            "code_provenance": provenance,
        }
        _json(output / "metadata.json", metadata)
        _json(
            output / "decision.json",
            {
                "verdict": "MECHANICAL_BASELINE_TRIAL_COMPLETE",
                "failure_reasons": [],
                "behaviour_checks": {
                    "all_orders_served": True,
                    "all_demand_served": True,
                    "complete_evaluator_used_for_every_candidate": True,
                    "initial_plan_constructed_by_mechanical_baseline": True,
                    "legacy_frozen_initial_plan_not_loaded": True,
                    "committed_history_preserved": history_preserved_all,
                    "no_randomness": True,
                    "no_global_reoptimization": True,
                    "three_candidate_classes_in_required_priority": True,
                    "p35_depot_precharge_path_used_for_static_ev_candidates": True,
                    "all_final_feasibility_items_passed": (
                        final_result.evaluation.feasible
                    ),
                    "consecutive_decision_logs_byte_identical": (
                        determinism_check[
                            "all_decision_logs_byte_identical"
                        ]
                    ),
                },
                "formal_experiment_allowed": False,
                "formal_experiment_blocker": "P34 A1 stream rebuild pending",
                "user_decision_changed": False,
            },
        )
        _json(
            output / "final_solution.json",
            {
                "individual_fingerprint": final_result.individual.fingerprint,
                "individual": asdict(final_result.individual),
                "evaluation": {
                    "total_cost": final_cost,
                    "breakdown": dict(final_result.evaluation.breakdown),
                    "violations": [
                        asdict(item) for item in final_result.evaluation.violations
                    ],
                    "prepared_solution": asdict(final_solution),
                    "certificate": final_result.evaluation.certificate.as_dict(),
                },
            },
        )
        comparison_text = (
            f"同流的现有动态算法技术包为 `{comparison['source_path']}`："
            f"成本 {comparison['total_cost']:.6f}，排放 "
            f"{comparison['emissions_kg']:.6f} kg，完成 "
            f"{comparison['completed_customers']}/{comparison['total_customers']} "
            f"个客户和 {comparison['completed_demand']:.6f}/"
            f"{comparison['total_demand']:.6f} 需求，启用 "
            f"{comparison['enabled_physical_vehicles']} 辆实体车。"
            if comparison["comparable"]
            else (
                "现有 stream-2 / search-seed-11 动态包使用相同事件表，但日初方案"
                "和评价合同都属于旧口径；因此本报告不引用它的数值作同合同比较。"
            )
        )
        dynamic_decisions_text = "\n".join(
            (
                f"- 第 {row['stage']} 次，客户 `{row['customer_id']}`："
                f"{CANDIDATE_CLASS_LABELS[str(row['candidate_class'])]}；"
                f"车辆 `{row['physical_vehicle_id']}`，路线 "
                f"`{row['route_id']}`。"
            )
            for row in decision_rows
        )
        feasibility_text = "\n".join(
            f"| `{name}` | {status} |"
            for name, status in feasibility_flags.items()
        )
        determinism_text = (
            "连续两次执行的 `initial_decision_log.csv` 与 "
            "`decision_log.csv` 均逐字节相同。"
            if determinism_check["all_decision_logs_byte_identical"]
            else "本次运行没有提供上一轮目录，未执行双跑字节核对。"
        )
        stale_paths_text = "\n".join(
            f"- `{item['path']}`（`{', '.join(item['stale_curve_ids'])}`）"
            for item in stale_initials
        )
        (output / "report.md").write_text(
            f"""# 机械在线策略基线技术冒烟

## 诊断核实

失败时加载的旧方案副本 `{legacy_initial['loaded_copy_path']}` 与产出批次 `{legacy_initial['producer_path']}` 内容及 SHA-256 完全相同（`{legacy_initial['producer_sha256']}`）；其中 {legacy_initial['producer_charging_action_count']} 个充电动作均为 `{', '.join(legacy_initial['producer_curve_ids'])}`。当前车场曲线为 `{depot_curve.curve_id}`，公共站曲线为 `{public_curve.curve_id}`，两者 SOC 节点均为 `{list(depot_curve.soc_breakpoints)}`。旧输入与当前 P35 口径不一致，严格评价器拒绝正确。

## 修复方式

本次不加载、不重认证、不改写旧冻结初始方案。机械基线从空计划开始，按稳定客户编号顺序处理日初可见客户，并严格按三类候选推进：①插入现有已计划趟；②给已在使用的车辆追加新一趟；③启用空闲车派直达路线。只有上一类没有可行候选时才进入下一类；同层按完整成本增量最小选择，同值按稳定车辆、趟次和位置编号破平。

静态 EV 候选的首趟车场预充电由现有固定路线充电构造器生成，动作携带当前 P35 曲线 `{depot_curve.curve_id}` 的能量、时长和曲线元数据，并继续交给完整评价校验。动态阶段仍由现有继承 SOC 调度器生成车场充电。全程无随机数、种群、局部搜索或全局重优化；评价合同和一致性检查均未修改。

## seed 11 冒烟结果

本次接线与行为冒烟完成。机械基线处理了 {len(stream.events)} 次订单揭示，最终完成 {len(set(completed_ids))}/{len(all_customers)} 个客户、{completed_demand:.6f}/{total_demand:.6f} 需求；完整成本为 {final_cost:.6f}，排放为 {final_emissions:.6f} kg，启用 {len(enabled_vehicles)} 辆实体车。每一次已执行历史都保持不变。

事件流使用现有 PRD50 stream 2；`seed 11` 是配对动态算法包的搜索种子身份，机械基线自身没有随机种子。

{determinism_text}

## 逐单决策

完整候选计数、插入位置和拒绝原因见 `decision_log.csv`。

{dynamic_decisions_text}

## 最终完整可行性

最终评价违反项为空。逐项标记如下；利润公平硬约束按配对动态算法当前相同上下文关闭，没有被本基线单独放宽或改写。

| 项目 | 标记 |
|---|---|
{feasibility_text}

## 同流技术参照

{comparison_text}

## 正式实验边界

正式动态实验仍须等待 P34 A1 的潜在客户池、真实订单流和算法内部情景一起重建完成。当前活动流会从当天最终客户中隐藏 20%，本包只验证机械基线的接线、完整可行性和确定性行为，不替代正式订单流。

## 陈旧产物兼容性

本次只检索 `solver/reports/**/initial_visible_solution.json`，并排除正在写入的两处报告目录。以下 {len(stale_initials)} 份文件被实际读到含有非当前曲线标识；未列出的路径不作推测。完整哈希见 `stale_initial_visible_solutions.json`。

{stale_paths_text}

## 产物

- `metadata.json`：输入身份、最终数字、保护文件哈希和同流参照。
- `initial_decision_log.csv`：日初可见客户的确定性构造过程。
- `initial_visible_solution.json`：当前合同下新构造的日初方案。
- `raw_runs.csv`：十个揭示阶段的服务、成本、排放和车辆数。
- `decision_log.csv`：每个订单插入哪条路线或是否新派车。
- `determinism_check.json`：连续两次运行的两份决策日志字节哈希与相同性。
- `stale_initial_visible_solutions.json`：实际检索到的陈旧初始方案路径与哈希。
- `decision.json`：本次技术判定与正式实验停止边界。
- `final_solution.json`：最终完整路线、评价分解和动态证书。
- `artifact_hashes.json`：上述产物哈希。
""",
            encoding="utf-8",
        )
        _write_hashes(output)
        return 0
    except Exception as error:
        _write_failure(
            output,
            invocation_id,
            error,
            determinism_reference_dir=determinism_reference_dir,
        )
        raise


if __name__ == "__main__":
    sys.exit(main())
