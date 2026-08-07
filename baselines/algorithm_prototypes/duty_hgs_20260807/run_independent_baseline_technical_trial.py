#!/usr/bin/env python3
"""Run a bounded real-input trial of the independent-depot Pi0 wiring."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
import sys
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

from duty_hgs.evaluation import DutyFullEvaluator
from duty_hgs.independent import (
    independent_bundle,
    independent_context,
    independent_individual,
)
from duty_hgs.runner import (
    FrozenPopulationIdentity,
    population_sha256,
    run_duty_hgs,
)
from run_real_input_technical_trial import (
    _build_context,
    _parameters,
    _policy,
    _prepare_population,
)
from setp_solver.profit import calculate_depot_profits

INSTANCE_ID = "cn-jjj-50c-01-V2-LOCATIONS"
PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _run_depot(bundle, full_individual, depot_id: str, iterations: int):
    subbundle = independent_bundle(bundle, depot_id)
    initial = independent_individual(full_individual, bundle, depot_id)
    context = independent_context(
        subbundle,
        depot_id,
        truth_sentinel_enabled=True,
    )
    evaluator = DutyFullEvaluator(context)
    policy = _policy(evaluator)
    parameters = _parameters()
    candidates, initial_evaluation, _reverse, attempts, selected = (
        _prepare_population(
            initial,
            evaluator,
            policy,
            parameters,
            require_distinct_selection=False,
        )
    )
    identity = FrozenPopulationIdentity(
        source_id=f"technical-independent-two-parent:{depot_id}",
        value_sha256=population_sha256(candidates),
    )
    result = run_duty_hgs(
        candidates,
        evaluator=evaluator,
        charging_policy=policy,
        parameters=parameters,
        initial_population_identity=identity,
        stop=lambda state: state.iterations >= iterations,
        arm=f"technical-independent-baseline:{depot_id}",
    )
    profits = calculate_depot_profits(
        result.best_evaluation.prepared_solution,
        subbundle.instance,
        subbundle.time_profile,
        subbundle.prices,
        customer_home_depot=dict(subbundle.customer_home_depot),
        carbon_quota_kg=0.0,
    )
    customer_nodes = {
        node.node_id: node
        for node in subbundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    served = {
        customer
        for duty in result.best.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    served_demand = sum(float(customer_nodes[item].demand) for item in served)
    total_demand = sum(float(node.demand) for node in customer_nodes.values())
    failure_reasons = []
    if not initial_evaluation.feasible:
        failure_reasons.append("independent initial solution is infeasible")
    if result.termination_status != "STOPPED_BY_CALLER":
        failure_reasons.append(
            f"unexpected termination {result.termination_status}"
        )
    if not result.best_evaluation.feasible:
        failure_reasons.append("independent best solution is infeasible")
    if served != set(customer_nodes):
        failure_reasons.append("independent best does not serve every customer")
    if result.provenance.fairness_enabled:
        failure_reasons.append("fairness remained enabled in Pi0 search")
    if result.accounting.sentinel_evaluations <= 0:
        failure_reasons.append("truth sentinel was not exercised")
    if float(profits[depot_id].profit) <= 0.0:
        failure_reasons.append("independent profit is not positive")
    return {
        "instance_id": bundle.instance_id,
        "depot_id": depot_id,
        "customer_count": len(customer_nodes),
        "served_customer_count": len(served),
        "total_demand_kg": total_demand,
        "served_demand_kg": served_demand,
        "requested_iterations": iterations,
        "completed_iterations": result.iterations,
        "termination_status": result.termination_status,
        "initial_cost_cny": float(initial_evaluation.total_cost),
        "best_cost_cny": float(result.best_evaluation.total_cost),
        "best_system_emissions_kg": float(
            result.best_evaluation.breakdown["E_total"]
        ),
        "independent_profit_cny": float(profits[depot_id].profit),
        "best_violation_count": len(result.best_evaluation.violations),
        "fairness_enabled": result.provenance.fairness_enabled,
        "truth_sentinel_evaluations": (
            result.accounting.sentinel_evaluations
        ),
        "full_evaluations": result.accounting.full_evaluations,
        "incremental_evaluations": result.accounting.incremental_evaluations,
        "actual_full_model_evaluations": (
            result.accounting.full_evaluations
            + result.accounting.sentinel_evaluations
        ),
        "generated_second_parent_attempts": len(attempts),
        "technical_parent_selection_distinct": selected["distinct"],
        "search_wall_seconds": result.accounting.run_wall_seconds,
        "provenance_json": json.dumps(
            asdict(result.provenance),
            ensure_ascii=False,
            sort_keys=True,
        ),
        "status": (
            "TECHNICAL_PI0_WIRING_PASS"
            if not failure_reasons
            else "TECHNICAL_PI0_WIRING_FAILED"
        ),
        "failure_reason": "; ".join(failure_reasons),
    }


def _report(
    rows: list[dict[str, Any]],
    instance_id: str,
    expected_depot_count: int,
) -> str:
    passed = [
        row for row in rows if row["status"] == "TECHNICAL_PI0_WIRING_PASS"
    ]
    details = "\n".join(_report_row(row) for row in rows)
    return f"""# 单车场独立经营基准技术试跑

## 结论

`{instance_id}` 已按车场串行试跑，预期 {expected_depot_count} 个车场，实际尝试 {len(rows)} 个，其中 {len(passed)} 个通过单车场求解、利润计算、完整检查和逐候选真值哨兵。{details}

本轮只检查接线，不冻结正式单干利润。一个循环不是用户批准的正式收敛停止方法；这里的利润数字不能进入公平实验或论文。正式 Pi0 仍须每个车场按同一收敛口径跑 10 个种子，取最好利润后冻结。

## 交付前九条自检

1. 每个事实是否有出处？——逐车场数字在同包 `raw_runs.csv`，来源和哈希在 `metadata.json`。
2. 有没有把建议或担忧写成已决或状态？——没有；正式 Pi0 和最终算例均未替用户确定。
3. 是否超出任务范围？——没有；只做已授权的单干基准接线技术试跑。
4. 是否碰受保护文件？——没有；运行前后哈希保存在 `metadata.json` 并核对一致。
5. 待决事项是否给了选项和代价？——本轮不新增待决事项。
6. 是否使用自造词或内部任务号？——没有。
7. 失败、跳过、超时和异常是否保留？——每个车场都有状态和失败原因，本轮无静默删除。
8. 四件套是否齐全？——`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`report.md` 齐全。
9. 交接记录是否同步？——本包复核后同步 `HANDOFF.md` 和 `docs/handoff/memory/MEMORY.md`。
"""


def _report_row(row: dict[str, Any]) -> str:
    if row["status"] != "TECHNICAL_PI0_WIRING_PASS":
        return (
            f"- {row['depot_id']}：试跑失败，已保留错误："
            f"{row['failure_reason']}"
        )
    return (
        f"- {row['depot_id']}：服务 {row['served_customer_count']}/"
        f"{row['customer_count']} 个客户，需求量 "
        f"{float(row['served_demand_kg']):.3f}/"
        f"{float(row['total_demand_kg']):.3f} 千克，违规 "
        f"{row['best_violation_count']}，试算利润 "
        f"{float(row['independent_profit_cny']):.6f} 元。"
    )


def _failure_row(instance_id: str, depot_id: str, exc: Exception):
    return {
        "instance_id": instance_id,
        "depot_id": depot_id,
        "status": "TECHNICAL_PI0_WIRING_FAILED",
        "failure_reason": f"{type(exc).__name__}: {exc}",
        "traceback": "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance-id", default=INSTANCE_ID)
    parser.add_argument("--iterations", type=int, default=1)
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("technical iterations must be positive")
    repo = Path(__file__).resolve().parents[3]
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    if _git(repo, "status", "--porcelain"):
        raise RuntimeError("technical Pi0 trial requires a clean worktree")
    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    output.mkdir(parents=True)
    source = Path(__file__).resolve()
    metadata_path = output / "metadata.json"
    metadata = {
        "schema": "resetp.duty-hgs-independent-baseline-trial.v2",
        "purpose": "bounded wiring trial; not a formal Pi0 result",
        "git_head": _git(repo, "rev-parse", "HEAD"),
        "git_branch": _git(repo, "branch", "--show-current"),
        "worktree_clean_before_run": True,
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "runner_path": str(source.relative_to(repo)),
        "runner_sha256": _sha256(source),
        "instance_id": args.instance_id,
        "requested_iterations": args.iterations,
        "serial_depot_execution": True,
        "formal_convergence_stop_used": False,
        "formal_pi0_frozen": False,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": None,
        "recorded_depot_rows": 0,
        "passed_depot_rows": 0,
        "first_failure": None,
    }
    _json(metadata_path, metadata)
    bundle, full_individual, _technical_pi0, _context = _build_context(
        repo,
        args.instance_id,
    )
    depot_ids = sorted(bundle.fleet_caps_by_depot)
    expected_depot_count = len(depot_ids)
    metadata["expected_depot_rows"] = expected_depot_count
    metadata["attempted_depot_rows"] = 0
    metadata["unattempted_depot_rows"] = expected_depot_count
    _json(metadata_path, metadata)
    rows: list[dict[str, Any]] = []
    for depot_id in depot_ids:
        try:
            row = _run_depot(
                bundle,
                full_individual,
                depot_id,
                args.iterations,
            )
        except Exception as exc:  # preserve the first failing depot in-package
            row = _failure_row(args.instance_id, depot_id, exc)
            metadata["first_failure"] = row["failure_reason"]
            rows.append(row)
            _write_csv(output / "raw_runs.csv", rows)
            metadata["attempted_depot_rows"] = len(rows)
            metadata["unattempted_depot_rows"] = (
                expected_depot_count - len(rows)
            )
            _json(metadata_path, metadata)
            break
        rows.append(row)
        _write_csv(output / "raw_runs.csv", rows)
        metadata["recorded_depot_rows"] = len(rows)
        metadata["attempted_depot_rows"] = len(rows)
        metadata["unattempted_depot_rows"] = (
            expected_depot_count - len(rows)
        )
        metadata["passed_depot_rows"] = sum(
            row["status"] == "TECHNICAL_PI0_WIRING_PASS" for row in rows
        )
        _json(metadata_path, metadata)
    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    metadata["protected_hashes_after"] = protected_after
    metadata["recorded_depot_rows"] = len(rows)
    metadata["attempted_depot_rows"] = len(rows)
    metadata["unattempted_depot_rows"] = (
        expected_depot_count - len(rows)
    )
    metadata["passed_depot_rows"] = sum(
        row["status"] == "TECHNICAL_PI0_WIRING_PASS" for row in rows
    )
    _json(metadata_path, metadata)
    passed = [
        row for row in rows if row["status"] == "TECHNICAL_PI0_WIRING_PASS"
    ]
    _json(
        output / "decision.json",
        {
            "verdict": (
                "TECHNICAL_PI0_WIRING_COMPLETE"
                if len(passed) == expected_depot_count
                and protected_before == protected_after
                else "TECHNICAL_PI0_WIRING_FAILED"
            ),
            "expected_depot_count": expected_depot_count,
            "attempted_depot_count": len(rows),
            "unattempted_depot_count": expected_depot_count - len(rows),
            "passed_count": len(passed),
            "failed_count": len(rows) - len(passed),
            "formal_pi0_result": False,
            "formal_experiment_result": False,
            "final_instance_selected": None,
        },
    )
    (output / "report.md").write_text(
        _report(rows, args.instance_id, expected_depot_count),
        encoding="utf-8",
    )
    hashes = {
        path.name: _sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _json(output / "artifact_hashes.json", hashes)
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    print(
        json.dumps(
            {
                "output": str(output),
                "passed": len(passed),
                "depots": len(rows),
            },
            ensure_ascii=False,
        )
    )
    return (
        0
        if len(passed) == expected_depot_count
        and protected_before == protected_after
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
