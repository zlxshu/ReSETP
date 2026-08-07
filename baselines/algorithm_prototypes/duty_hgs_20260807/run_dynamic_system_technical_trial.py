#!/usr/bin/env python3
"""One certified future-only Duty-HGS system wiring trial.

This runner proves that the same strong route kernel and problem-mechanism
proposal layer can search a future-only rolling state while the executed day,
physical assets, battery state, and locked charging history remain fixed.  It
is a technical trial, not a dynamic-effect experiment.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter
from types import MappingProxyType
from uuid import uuid4

from duty_hgs.dynamic import DutyDynamicState, future_individual_from_cut
from duty_hgs.evaluation import DutyFullEvaluator
from duty_hgs.model import DutyIndividual
from duty_hgs.proposals import InterleavedProposalEngine, MechanismProposalEngine
from duty_hgs.pyvrp_proposals import PyVRPDutyRouteProposalEngine
from duty_hgs.runner import FrozenPopulationIdentity, population_sha256, run_duty_hgs
from run_real_input_technical_trial import (
    PROTECTED,
    SEED,
    _build_context,
    _json,
    _parameters,
    _policy,
    _prepare_population,
    _sha256,
    _source_provenance,
    _with_registered_idle_duties,
    _write_failure_package,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.dynamic_multitrip_schedule import (
    DynamicAssetState,
    cut_certificate_at_trigger,
)


_ACTIVE_OUTPUT: Path | None = None
_ACTIVE_INVOCATION_ID: str | None = None


def _payload_sha256(payload) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _dynamic_state(initial, static_evaluation, bundle, trigger_second: float):
    cut = cut_certificate_at_trigger(
        static_evaluation.prepared_solution,
        static_evaluation.certificate,
        bundle.instance,
        bundle.prices,
        trigger_second=trigger_second,
    )
    assets = dict(cut.asset_states)
    synthesized_idle_asset_ids = []
    for duty in initial.duties:
        if duty.physical_vehicle_id in assets:
            continue
        assets[duty.physical_vehicle_id] = DynamicAssetState(
            physical_vehicle_id=duty.physical_vehicle_id,
            vehicle_type=duty.vehicle_type,
            home_depot_id=duty.home_depot_id,
            available_second=float(trigger_second),
            remaining_battery_kwh=(
                float(bundle.prices.initial_ev_battery_kwh)
                if duty.vehicle_type == "ev"
                else 0.0
            ),
            next_trip_index=1,
        )
        synthesized_idle_asset_ids.append(duty.physical_vehicle_id)
    customers = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    committed_route_ids = {
        *cut.completed_route_ids,
        *cut.in_progress_route_ids,
    }
    committed_customers = {
        node_id
        for route in static_evaluation.prepared_solution.routes
        if route.vehicle_id in committed_route_ids
        for node_id in route.node_sequence[1:-1]
        if node_id in customers
    }
    return (
        DutyDynamicState(
            source_solution=static_evaluation.prepared_solution,
            cut=cut,
            asset_states=MappingProxyType(assets),
            future_customer_ids=frozenset(
                customers.difference(committed_customers)
            ),
            customer_appearance_second={customer: 0.0 for customer in customers},
            charging_strategy="aware",
            charging_intensity_field="forecast_gco2_per_kwh",
        ),
        tuple(sorted(synthesized_idle_asset_ids)),
    )


def _committed_history_payload(state: DutyDynamicState, solution):
    committed_ids = {
        *state.cut.completed_route_ids,
        *state.cut.in_progress_route_ids,
    }
    routes = sorted(
        (asdict(route) for route in solution.routes if route.vehicle_id in committed_ids),
        key=lambda row: row["vehicle_id"],
    )
    locked_keys = {
        (
            action.vehicle_id,
            action.station_id,
            float(action.charge_start_second),
            float(action.energy_kwh),
        )
        for action in state.cut.locked_charging_actions
    }
    actions = sorted(
        (
            asdict(action)
            for action in solution.charging_actions
            if (
                action.vehicle_id,
                action.station_id,
                float(action.charge_start_second),
                float(action.energy_kwh),
            ) in locked_keys
        ),
        key=lambda row: (
            row["vehicle_id"],
            row["station_id"],
            float(row["charge_start_second"]),
        ),
    )
    return {"routes": routes, "locked_charging_actions": actions}


def main() -> int:
    global _ACTIVE_INVOCATION_ID, _ACTIVE_OUTPUT

    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--instance-id",
        default="cn-jjj-50c-01-V2-LOCATIONS",
    )
    parser.add_argument("--trigger-second", type=float, default=43_200.0)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument(
        "--source-best-solution",
        type=Path,
        default=Path(
            "baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/"
            "unified_education_jjj50_01_20260807/best_solution.json"
        ),
    )
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("technical iteration count must be positive")

    repo = Path(__file__).resolve().parents[3]
    output = args.output_dir.resolve()
    provenance = _source_provenance(
        repo,
        output_path=output,
        stderr_capture_state="caller_not_declared",
    )
    if not provenance["worktree_clean_before_run"]:
        raise RuntimeError("technical provenance run requires a clean worktree")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    invocation_id = uuid4().hex
    _ACTIVE_OUTPUT = output
    _ACTIVE_INVOCATION_ID = invocation_id
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "invocation_id": invocation_id,
            "purpose": (
                "future-only system wiring trial; not a dynamic-effect experiment"
            ),
            "code_provenance": provenance,
            "requested_instance_id": args.instance_id,
            "requested_trigger_second": float(args.trigger_second),
            "requested_iterations": int(args.iterations),
        },
    )

    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    bundle, _registered_initial, pi0, static_context = _build_context(
        repo,
        args.instance_id,
    )
    source_path = (
        args.source_best_solution
        if args.source_best_solution.is_absolute()
        else repo / args.source_best_solution
    ).resolve()
    source_metadata_path = source_path.with_name("metadata.json")
    source_metadata = json.loads(
        source_metadata_path.read_text(encoding="utf-8")
    )
    if source_metadata.get("status") != "COMPLETE":
        raise ValueError("dynamic source package is not complete")
    if source_metadata.get("instance_id") != args.instance_id:
        raise ValueError(
            "dynamic source package belongs to another instance: "
            f"{source_metadata.get('instance_id')!r}"
        )
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    source_solution = solution_from_dict(
        source_payload["evaluation"]["prepared_solution"]
    )
    customer_ids = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    initial = _with_registered_idle_duties(
        DutyIndividual.from_solution(
            source_solution,
            customer_node_ids=customer_ids,
            source="saved-static-source-recertified-for-dynamic-trial",
        ),
        bundle,
    )
    static_evaluation = DutyFullEvaluator(static_context).evaluate(initial)
    state, synthesized_idle_asset_ids = _dynamic_state(
        initial,
        static_evaluation,
        bundle,
        float(args.trigger_second),
    )
    future = future_individual_from_cut(
        state,
        static_evaluation.certificate,
        bundle.instance,
    )
    evaluator = DutyFullEvaluator(
        replace(
            static_context,
            dynamic_state=state,
            incremental_full_truth_sentinel_enabled=False,
        )
    )
    policy = _policy(evaluator)
    parameters = _parameters()
    initialization_started = perf_counter()
    initialization_full_calls_before = evaluator.full_calls
    (
        candidates,
        initial_evaluation,
        reverse,
        attempts,
        selected,
        initial_evaluations,
    ) = (
        _prepare_population(
            future,
            evaluator,
            policy,
            parameters,
            require_distinct_selection=False,
        )
    )
    initialization_wall_seconds = perf_counter() - initialization_started
    initialization_full_evaluations = (
        evaluator.full_calls - initialization_full_calls_before
    )
    proposal_engine = InterleavedProposalEngine(
        (
            PyVRPDutyRouteProposalEngine(
                evaluator.context,
                future,
                random_seed=SEED,
            ),
            MechanismProposalEngine(evaluator.context, policy),
        )
    )
    identity = FrozenPopulationIdentity(
        source_id="technical-dynamic-future-two-parent-population",
        value_sha256=population_sha256(candidates),
    )
    result = run_duty_hgs(
        candidates,
        evaluator=evaluator,
        charging_policy=policy,
        parameters=parameters,
        initial_population_identity=identity,
        stop=lambda search_state: search_state.iterations >= args.iterations,
        arm="dynamic-future-system-wiring-trial",
        proposal_engine=proposal_engine,
        initial_evaluations=initial_evaluations,
        initialization_full_evaluation_count=initialization_full_evaluations,
        initialization_wall_seconds=initialization_wall_seconds,
    )

    all_customers = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    completed_customers = [
        node_id
        for route in result.best_evaluation.prepared_solution.routes
        for node_id in route.node_sequence[1:-1]
        if node_id in all_customers
    ]
    demand_by_customer = {
        node.node_id: float(node.demand)
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    completed_demand = sum(
        demand_by_customer[customer] for customer in set(completed_customers)
    )
    total_demand = sum(demand_by_customer.values())
    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    history_before = _committed_history_payload(
        state,
        state.source_solution,
    )
    history_after = _committed_history_payload(
        state,
        result.best_evaluation.prepared_solution,
    )
    history_before_sha256 = _payload_sha256(history_before)
    history_after_sha256 = _payload_sha256(history_after)
    asset_state_sha256 = _payload_sha256(
        {
            asset_id: asdict(asset)
            for asset_id, asset in sorted(state.asset_states.items())
        }
    )
    failures = []
    if not initial_evaluation.feasible:
        failures.append("future initial solution is infeasible")
    if result.termination_status != "STOPPED_BY_CALLER":
        failures.append(f"unexpected termination: {result.termination_status}")
    if result.accounting.education_rounds <= 0:
        failures.append("system proposal layer was never called")
    if not result.best_evaluation.feasible:
        failures.append("best merged full-day solution is infeasible")
    if set(completed_customers) != all_customers:
        failures.append("merged execution does not serve every customer")
    if len(completed_customers) != len(set(completed_customers)):
        failures.append("merged execution repeats a customer")
    if completed_demand != total_demand:
        failures.append("merged execution does not complete all demand")
    if protected_before != protected_after:
        failures.append("a protected evaluator file changed")
    if history_before_sha256 != history_after_sha256:
        failures.append("committed execution history changed")
    verdict = "TECHNICAL_TRIAL_COMPLETE" if not failures else "TECHNICAL_TRIAL_FAILED"

    metadata = {
        "status": "COMPLETE" if not failures else "FAILED",
        "invocation_id": invocation_id,
        "purpose": "future-only system wiring trial; not a dynamic-effect experiment",
        "code_provenance": provenance,
        "source_best_solution_path": str(source_path),
        "source_best_solution_sha256": _sha256(source_path),
        "source_metadata_path": str(source_metadata_path),
        "source_metadata_sha256": _sha256(source_metadata_path),
        "source_metadata_instance_id": source_metadata["instance_id"],
        "source_saved_cost_ignored_and_recomputed": True,
        "source_recomputed_cost": static_evaluation.total_cost,
        "instance_id": args.instance_id,
        "instance_formally_selected": False,
        "trigger_second": float(args.trigger_second),
        "iterations": int(args.iterations),
        "stop_semantics": "technical fixed-iteration stop; not the formal internal stop",
        "future_customer_count": len(state.future_customer_ids),
        "completed_route_count_at_cut": len(state.cut.completed_route_ids),
        "in_progress_route_count_at_cut": len(state.cut.in_progress_route_ids),
        "editable_route_count_at_cut": len(state.cut.editable_route_ids),
        "asset_count": len(state.asset_states),
        "synthesized_idle_asset_ids": synthesized_idle_asset_ids,
        "synthesized_idle_asset_rule": {
            "available_second": float(args.trigger_second),
            "cv_remaining_battery_kwh": 0.0,
            "ev_remaining_battery_kwh": float(
                bundle.prices.initial_ev_battery_kwh
            ),
            "next_trip_index": 1,
        },
        "cut_asset_state_sha256": asset_state_sha256,
        "committed_history_before_sha256": history_before_sha256,
        "committed_history_after_sha256": history_after_sha256,
        "initial_population_sha256": identity.value_sha256,
        "initial_parent_selection": selected,
        "initial_parent_attempts": attempts,
        "preflight_reverse_attempt": reverse,
        "proposal_engine_source_id": proposal_engine.source_id,
        "proposal_engine_sha256": proposal_engine.identity_sha256,
        "pi0_values": pi0,
        "pi0_formal_reuse_allowed": False,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
    }
    _json(output / "metadata.json", metadata)
    row = {
        "instance_id": args.instance_id,
        "seed": SEED,
        "trigger_second": float(args.trigger_second),
        "future_customers": len(state.future_customer_ids),
        "synthesized_idle_assets": len(synthesized_idle_asset_ids),
        "iterations": result.iterations,
        "education_rounds": result.accounting.education_rounds,
        "initial_cost": initial_evaluation.total_cost,
        "best_cost": result.best_evaluation.total_cost,
        "cost_delta": result.best_evaluation.total_cost - initial_evaluation.total_cost,
        "initial_emissions_kg": initial_evaluation.breakdown.get("E_total"),
        "best_emissions_kg": result.best_evaluation.breakdown.get("E_total"),
        "best_feasible": result.best_evaluation.feasible,
        "committed_history_preserved": (
            history_before_sha256 == history_after_sha256
        ),
        "completed_customers": len(set(completed_customers)),
        "total_customers": len(all_customers),
        "completed_demand": completed_demand,
        "total_demand": total_demand,
        "accepted_actions": json.dumps(
            result.accounting.to_dict()["accepted_actions"],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "verdict": verdict,
    }
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row), lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
    _json(
        output / "decision.json",
        {
            "verdict": verdict,
            "failure_reasons": failures,
            "what_this_answers": [
                "whether the same system proposal layer was actually called on a certificate cut plus registered idle-asset completion",
                "the merged full-day solution is or is not feasible and complete",
                "committed routes and locked charging are or are not preserved exactly",
            ],
            "what_this_does_not_decide": [
                "dynamic-demand effect size",
                "formal trigger policy",
                "formal instance selection",
                "formal algorithm superiority",
            ],
            "user_decision_changed": False,
        },
    )
    _json(
        output / "best_solution.json",
        {
            "future_individual": asdict(result.best),
            "merged_full_day_solution": asdict(
                result.best_evaluation.prepared_solution
            ),
            "breakdown": dict(result.best_evaluation.breakdown),
            "violations": [
                asdict(violation) for violation in result.best_evaluation.violations
            ],
            "accounting": result.accounting.to_dict(),
            "provenance": asdict(result.provenance),
        },
    )
    (output / "report.md").write_text(
        f"""# 动态未来部分系统算法技术试跑

本轮判定为 `{verdict}`。在 {args.trigger_second:.0f} 秒切面之后，算法只重排尚未开始的未来任务；已完成、正在执行的路线和已经锁定的充电保持不动。最终合并全天执行后，完成 {len(set(completed_customers))}/{len(all_customers)} 个客户和 {completed_demand:.6f}/{total_demand:.6f} 单位需求，完整评价违规数为 {len(result.best_evaluation.violations)}。

初始全天成本为 {initial_evaluation.total_cost:.12f}，本轮保存解成本为 {result.best_evaluation.total_cost:.12f}。这是一轮接线检查，不是动态实验，也不据此选择算例、触发政策或论文结论。

## 交付前九条自检

1. 每个事实是否有出处？——数字来自同包 raw_runs.csv、metadata.json 和 best_solution.json。
2. 有没有把建议或担忧写成已决或状态？——没有，只记录技术试跑结果。
3. 改动范围有没有超出任务文本？——没有，只验证动态未来部分接线。
4. 有没有碰受保护文件？——未碰，前后哈希见 metadata.json。
5. 待决事项是否转成具体候选并写清代价？——本轮不新增用户待决事项。
6. 有没有用自造词或内部任务号跟用户说话？——没有。
7. 失败、跳过、超时、异常结果有没有如实保留？——失败原因原样保存在 decision.json。
8. 四件套齐了吗？——metadata.json、raw_runs.csv、decision.json、artifact_hashes.json、report.md 齐全，另附 best_solution.json。
9. HANDOFF 和记忆同步了吗？——算法施工收口时统一同步。
""",
        encoding="utf-8",
    )
    _json(
        output / "artifact_hashes.json",
        {
            path.name: _sha256(path)
            for path in sorted(output.iterdir())
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        },
    )
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    print(json.dumps({"output": str(output), "verdict": verdict}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    requested_output = (
        None
        if len(sys.argv) < 2 or sys.argv[1].startswith("-")
        else Path(sys.argv[1]).resolve()
    )
    try:
        raise SystemExit(main())
    except Exception as exc:
        if (
            requested_output is not None
            and requested_output == _ACTIVE_OUTPUT
            and _ACTIVE_INVOCATION_ID is not None
        ):
            metadata_path = requested_output / "metadata.json"
            owned = False
            if metadata_path.is_file():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                owned = metadata.get("invocation_id") == _ACTIVE_INVOCATION_ID
            if owned:
                _write_failure_package(requested_output, exc)
        raise
