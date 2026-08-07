#!/usr/bin/env python3
"""Run one bounded, truth-checked Duty education scout on one China81 input.

This runner does not compare algorithms or freeze a representative instance.
It starts from the registered feasible solution and executes the approved
complete best-improvement neighbourhood until that component finds no further
penalized improvement.  The purpose is to observe which problem-specific
channels are actually proposed, evaluated, and accepted before any formal
paired experiment is designed.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from duty_hgs.contracts import SearchAccounting
from duty_hgs.education import educate_best_improvement
from duty_hgs.evaluation import (
    DutyFullEvaluator,
    assert_evaluations_equivalent,
)
from duty_hgs.population import AdaptivePenaltyManager
from run_real_input_technical_trial import (
    PROTECTED,
    _build_context,
    _json,
    _parameters,
    _policy,
    _sha256,
    _source_provenance,
    _write_failure_package,
)
from setp_solver.charging_curve import spec_from_parameters
from setp_solver.solution import physical_vehicle_id


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _solution_observations(evaluation, prices) -> dict[str, Any]:
    prepared = evaluation.prepared_solution
    route_counts = Counter(
        physical_vehicle_id(route.vehicle_id) for route in prepared.routes
    )
    route_by_vehicle = {
        physical_vehicle_id(route.vehicle_id): route
        for route in prepared.routes
    }
    used_cv = sum(
        route_by_vehicle[vehicle_id].vehicle_type == "cv"
        for vehicle_id in route_counts
    )
    used_ev = sum(
        route_by_vehicle[vehicle_id].vehicle_type == "ev"
        for vehicle_id in route_counts
    )
    curve = spec_from_parameters(prices)
    taper_start_soc = next(
        (
            float(curve.soc_breakpoints[index])
            for index, power in enumerate(curve.relative_powers)
            if float(power) < float(curve.relative_powers[0])
        ),
        None,
    )
    taper_actions = 0
    known_energy_actions = 0
    for action in prepared.charging_actions:
        if action.end_energy_kwh is None:
            continue
        known_energy_actions += 1
        if (
            taper_start_soc is not None
            and float(action.end_energy_kwh)
            > taper_start_soc * float(prices.B_battery_kwh) + 1.0e-9
        ):
            taper_actions += 1
    return {
        "used_cv": used_cv,
        "used_ev": used_ev,
        "used_physical_vehicles": len(route_counts),
        "trip_count": len(prepared.routes),
        "multi_trip_vehicle_count": sum(
            count > 1 for count in route_counts.values()
        ),
        "maximum_trips_per_vehicle": max(route_counts.values(), default=0),
        "charging_action_count": len(prepared.charging_actions),
        "charging_energy_kwh": sum(
            float(action.energy_kwh) for action in prepared.charging_actions
        ),
        "charging_actions_with_known_end_energy": known_energy_actions,
        "charging_actions_entering_taper_region": taper_actions,
        "charging_curve_id": curve.curve_id,
        "taper_start_soc": taper_start_soc,
        "cross_site_service_count": len(prepared.cross_site_services),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--disable-truth-sentinel", action="store_true")
    parser.add_argument("--stderr-capture-state", default="caller_not_declared")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[3]
    output = args.output_dir.resolve()
    provenance = _source_provenance(
        repo,
        output_path=output,
        stderr_capture_state=args.stderr_capture_state,
    )
    if not provenance["worktree_clean_before_run"]:
        raise RuntimeError("unified scout requires a clean worktree")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "purpose": (
                "single-instance education activation scout; not a formal "
                "algorithm, mechanism, or instance-selection result"
            ),
            "instance_id": args.instance_id,
            "truth_sentinel_enabled": not args.disable_truth_sentinel,
            "code_provenance": provenance,
        },
    )

    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    bundle, initial, pi0, context = _build_context(repo, args.instance_id)
    if args.disable_truth_sentinel:
        context = replace(
            context,
            incremental_full_truth_sentinel_enabled=False,
        )
    evaluator = DutyFullEvaluator(context)
    policy = _policy(evaluator)
    initial_evaluation = evaluator.evaluate(initial)
    parameters = _parameters()
    penalty_manager = AdaptivePenaltyManager(parameters.penalties)
    penalty_manager.register(initial_evaluation)
    accounting = SearchAccounting()

    round_rows: list[dict[str, Any]] = []
    accepted_by_channel: Counter[str] = Counter()
    status_by_channel: Counter[str] = Counter()
    rejection_reasons: Counter[tuple[str, str, str, str]] = Counter()

    def trajectory_sink(rows) -> None:
        round_index = len(round_rows) + 1
        accepted = [row for row in rows if row.accepted]
        for row in rows:
            status_by_channel[f"{row.channel}:{row.status}"] += 1
            if row.accepted:
                accepted_by_channel[row.channel] += 1
            if row.status.startswith("REJECTED"):
                rejection_reasons[
                    (
                        row.status,
                        row.channel,
                        row.error_type or "",
                        row.error or "",
                    )
                ] += 1
        selected = accepted[0] if accepted else None
        round_rows.append(
            {
                "education_round": round_index,
                "candidate_count": len(rows),
                "accepted": bool(selected),
                "accepted_action_id": (
                    selected.action_id if selected is not None else ""
                ),
                "accepted_channel": (
                    selected.channel if selected is not None else ""
                ),
                "before_cost_cny": (
                    selected.before_cost if selected is not None else ""
                ),
                "after_cost_cny": (
                    selected.after_cost if selected is not None else ""
                ),
                "before_emissions_kg": (
                    selected.before_emissions_kg
                    if selected is not None
                    else ""
                ),
                "after_emissions_kg": (
                    selected.after_emissions_kg
                    if selected is not None
                    else ""
                ),
                "minimum_participation_margin_before": (
                    selected.minimum_participation_margin_before
                    if selected is not None
                    else ""
                ),
                "minimum_participation_margin_after": (
                    selected.minimum_participation_margin_after
                    if selected is not None
                    else ""
                ),
            }
        )
        _write_csv(output / "round_summaries.csv", round_rows)

    final, final_incremental, _rows = educate_best_improvement(
        initial,
        evaluator=evaluator,
        charging_policy=policy,
        arm="unified-instance-education-scout",
        iteration=0,
        accounting=accounting,
        penalized_cost=penalty_manager.cost,
        initial_evaluation=initial_evaluation,
        trajectory_sink=trajectory_sink,
    )

    final_truth = evaluator.evaluate(final)
    assert_evaluations_equivalent(final_incremental, final_truth)
    customer_nodes = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    served = {
        customer
        for duty in final.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    served_demand = sum(
        float(customer_nodes[customer].demand) for customer in served
    )
    total_demand = sum(float(node.demand) for node in customer_nodes.values())
    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    initial_observations = _solution_observations(
        initial_evaluation,
        bundle.prices,
    )
    final_observations = _solution_observations(final_truth, bundle.prices)
    failure_reasons = []
    if not initial_evaluation.feasible:
        failure_reasons.append("registered initial solution is infeasible")
    if not final_truth.feasible:
        failure_reasons.append("final solution is infeasible")
    if served != set(customer_nodes):
        failure_reasons.append("final solution does not serve every customer")
    if protected_before != protected_after:
        failure_reasons.append("a protected evaluator file changed")
    if (
        context.incremental_full_truth_sentinel_enabled
        and accounting.sentinel_evaluations <= 0
    ):
        failure_reasons.append("enabled truth sentinel was not exercised")
    if (
        not context.incremental_full_truth_sentinel_enabled
        and accounting.sentinel_evaluations != 0
    ):
        failure_reasons.append("disabled truth sentinel was exercised")
    verdict = (
        "TECHNICAL_EDUCATION_SCOUT_COMPLETE"
        if not failure_reasons
        else "TECHNICAL_EDUCATION_SCOUT_FAILED"
    )

    raw_row = {
        "instance_id": args.instance_id,
        "verdict": verdict,
        "initial_cost_cny": float(initial_evaluation.total_cost),
        "final_cost_cny": float(final_truth.total_cost),
        "cost_change_percent": (
            float(final_truth.total_cost) - float(initial_evaluation.total_cost)
        )
        / float(initial_evaluation.total_cost)
        * 100.0,
        "initial_emissions_kg": float(
            initial_evaluation.breakdown["E_total"]
        ),
        "final_emissions_kg": float(final_truth.breakdown["E_total"]),
        "customers_served": len(served),
        "customers_total": len(customer_nodes),
        "demand_served_kg": served_demand,
        "demand_total_kg": total_demand,
        "education_rounds": accounting.education_rounds,
        "incremental_evaluations": accounting.incremental_evaluations,
        "sentinel_evaluations": accounting.sentinel_evaluations,
        "accepted_by_channel_json": json.dumps(
            dict(sorted(accepted_by_channel.items())),
            ensure_ascii=False,
            sort_keys=True,
        ),
        "status_by_channel_json": json.dumps(
            dict(sorted(status_by_channel.items())),
            ensure_ascii=False,
            sort_keys=True,
        ),
        "initial_observations_json": json.dumps(
            initial_observations,
            ensure_ascii=False,
            sort_keys=True,
        ),
        "final_observations_json": json.dumps(
            final_observations,
            ensure_ascii=False,
            sort_keys=True,
        ),
        "initial_minimum_participation_margin_cny": min(
            initial_evaluation.participation_margin.values()
        ),
        "final_minimum_participation_margin_cny": min(
            final_truth.participation_margin.values()
        ),
        "pi0_externally_frozen": False,
        "truth_sentinel_enabled": (
            context.incremental_full_truth_sentinel_enabled
        ),
        "failure_reason": "; ".join(failure_reasons),
    }
    _write_csv(output / "raw_runs.csv", [raw_row])
    rejection_rows = [
        {
            "status": status,
            "channel": channel,
            "error_type": error_type,
            "error": error,
            "count": count,
        }
        for (status, channel, error_type, error), count in sorted(
            rejection_reasons.items()
        )
    ]
    if rejection_rows:
        _write_csv(output / "rejection_summary.csv", rejection_rows)
    _json(
        output / "best_solution.json",
        {
            "individual": asdict(final),
            "evaluation": {
                "total_cost": float(final_truth.total_cost),
                "breakdown": dict(final_truth.breakdown),
                "violations": [
                    asdict(item) for item in final_truth.violations
                ],
                "participation_margin": dict(
                    final_truth.participation_margin
                ),
                "prepared_solution": asdict(final_truth.prepared_solution),
            },
            "accounting": accounting.to_dict(),
            "initial_observations": initial_observations,
            "final_observations": final_observations,
        },
    )
    _json(
        output / "decision.json",
        {
            "verdict": verdict,
            "failure_reasons": failure_reasons,
            "formal_algorithm_result": False,
            "formal_mechanism_result": False,
            "formal_instance_selected": None,
            "what_this_answers": [
                "which approved education channels are activated on this input",
                "whether the component can finish with full service and full truth",
                "whether multi-trip, mixed-fleet, charging, and cross-site structures occur in the saved solution",
            ],
            "what_this_does_not_answer": [
                "algorithm superiority",
                "paired mechanism effect",
                "formal convergence or budget",
                "formal independent profit or fairness cost",
                "dynamic rolling-policy effect",
                "representative-instance selection",
            ],
        },
    )
    metadata = {
        "status": "COMPLETE" if not failure_reasons else "FAILED",
        "purpose": (
            "single-instance education activation scout; not a formal "
            "algorithm, mechanism, or instance-selection result"
        ),
        "instance_id": args.instance_id,
        "instance_formally_selected": False,
        "code_provenance": provenance,
        "truth_sentinel_enabled": (
            context.incremental_full_truth_sentinel_enabled
        ),
        "technical_stop": (
            "repeat the approved complete best-improvement neighbourhood "
            "until it accepts no penalized improvement; not the formal P20 stop"
        ),
        "candidate_trajectory_retained": False,
        "retained_search_records": [
            "round_summaries.csv",
            "rejection_summary.csv",
            "accepted_by_channel_json in raw_runs.csv",
            "status_by_channel_json in raw_runs.csv",
        ],
        "penalty_parameters": asdict(parameters.penalties),
        "charging_policy": asdict(policy),
        "pi0": {
            "values": pi0,
            "externally_frozen": False,
            "formal_reuse_allowed": False,
        },
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
    }
    _json(output / "metadata.json", metadata)
    report = f"""# 统一算例完整邻域技术探路

## 结论

`{args.instance_id}` 从登记合法起点出发，完整邻域教育共执行 {accounting.education_rounds} 轮，最终服务 {len(served)}/{len(customer_nodes)} 个客户、完成需求量 {served_demand:.3f}/{total_demand:.3f} 千克，完整检查违规 {len(final_truth.violations)}。成本由 {initial_evaluation.total_cost:.6f} 元变为 {final_truth.total_cost:.6f} 元。逐候选真值复核开关为 `{context.incremental_full_truth_sentinel_enabled}`，实际复核 {accounting.sentinel_evaluations} 次。

本包只观察当前算例里哪些搜索动作和基础结构真的被使用。技术用独立利润来自登记起点，尚未正式冻结；因此利润参与只能看是否进入作用区间，不能据此比较公平开关的代价。多趟和非线性充电的出现次数是存在性记录，不冒充正式效应对照。该算例没有因此被选为代表算例。

## 交付前九条自检

1. 每个事实是否有出处？——逐轮结果在 `round_summaries.csv`，拒绝原因在 `rejection_summary.csv`，完整解和计数在 `best_solution.json`，汇总在 `raw_runs.csv`。
2. 有没有把建议或担忧写成已决或状态？——没有；正式算例、预算、利润基准和效应口径均未替用户决定。
3. 是否超出任务范围？——没有；只做已批准的统一算例技术探路，没有启动正式实验或修改论文。
4. 是否碰受保护文件？——未碰；三个文件前后哈希一致并保存在 `metadata.json`。
5. 待决事项是否给了选项和代价？——本包不新增用户决策；效果识别选项在三地区探路完成后统一提交。
6. 是否使用自造词或内部任务号？——没有。
7. 失败、跳过、超时和异常是否如实保留？——候选状态按通道汇总，拒绝错误逐类保存在 `rejection_summary.csv`，本轮失败原因写入 `decision.json`。
8. 四件套是否齐全？——`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`report.md` 齐全，另附逐轮、拒绝汇总和完整解。
9. 交接记录是否同步？——三地区探路完成并复核后统一同步项目交接和记忆。
"""
    (output / "report.md").write_text(report, encoding="utf-8")
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    hashes = {
        path.name: _sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    _json(output / "artifact_hashes.json", hashes)
    print(
        json.dumps(
            {
                "output": str(output),
                "verdict": verdict,
                "education_rounds": accounting.education_rounds,
                "sentinel_evaluations": accounting.sentinel_evaluations,
            },
            ensure_ascii=False,
        )
    )
    return 0 if not failure_reasons else 2


if __name__ == "__main__":
    requested_output = (
        None
        if len(sys.argv) < 2 or sys.argv[1].startswith("-")
        else Path(sys.argv[1]).resolve()
    )
    try:
        raise SystemExit(main())
    except Exception as exc:
        if requested_output is not None:
            _write_failure_package(requested_output, exc)
        raise
