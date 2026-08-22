#!/usr/bin/env python3
"""Run the approved bounded DSS step-1 L0/L1 technical question set."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import subprocess
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from run_integrated_private_component_scout import _run_arm
from run_problem_hgs_private_technical import (
    PROTECTED,
    _build_context,
    _policy,
    _prepare_population,
    _sha256,
)
from setp_solver.algorithms.problem_hgs.evaluation import (
    DutyFullEvaluator,
    evaluation_context_sha256,
)
from setp_solver.algorithms.problem_hgs.schedule_capture import (
    ScheduleCaptureRecord,
    schedule_capture_sink,
)
from setp_solver.algorithms.problem_hgs.schedule_oracle import (
    OracleStatus,
    ScheduleCoordinator,
    ScheduleOracleContext,
    SingleDutyScheduleOracle,
    build_capacity_calendar,
    capacity_calendar_fingerprint,
)


INSTANCE_ID = "cn-prd-50c-01-V2-LOCATIONS"
SEEDS = (1, 2, 11)
ITERATIONS = 3
MAX_RUNTIME_SECONDS = 10.0


def _json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
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


def _run_test(repo: Path, node_id: str) -> dict[str, Any]:
    command = (
        sys.executable,
        "-m",
        "pytest",
        "-q",
        f"solver/tests/test_problem_hgs_schedule_oracle.py::{node_id}",
    )
    completed = subprocess.run(
        command,
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "node_id": node_id,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _odds(alive: int, dead: int) -> float | None:
    if dead == 0:
        return None
    return float(alive) / float(dead)


def _ratio(left: float | None, right: float | None) -> float | None:
    if left is None or right is None or right == 0.0:
        return None
    return float(left) / float(right)


def _summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"samples": 0, "p50": None, "p95": None, "p99": None, "max": None}
    ordered = sorted(float(value) for value in values)

    def percentile(probability: float) -> float:
        index = int(math.ceil(probability * len(ordered))) - 1
        return ordered[max(0, min(len(ordered) - 1, index))]

    return {
        "samples": len(ordered),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": ordered[-1],
    }


def _legacy_l0(repo: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = (
        repo
        / "solver/reports/carpet_sweep_20260810/private_space/death_reasons.csv"
    )
    with source.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    sources = {}
    for seed in SEEDS:
        root = repo / f"solver/reports/problem_hgs_serial_finalonly_prd50_seed{seed}_20260810"
        sources[str(seed)] = {
            str(path.relative_to(repo)): _sha256(path)
            for path in (
                root / "metadata.json",
                root / "raw_runs.csv",
                root / "best_solutions.json",
                root / "artifact_hashes.json",
            )
        }
    return rows, {
        "identity": "L0_HISTORICAL_AGGREGATE_ONLY",
        "source_death_reasons_csv": str(source.relative_to(repo)),
        "source_death_reasons_sha256": _sha256(source),
        "source_packages": sources,
        "total_aggregate_deaths": sum(int(row["count"]) for row in rows),
        "claim_boundary": (
            "18 aggregate buckets only; not the original 313 per-candidate snapshots"
        ),
    }


def _case_payload(
    *,
    case_id: str,
    seed: int,
    record: ScheduleCaptureRecord,
    schedule_context: ScheduleOracleContext,
    protected_hashes: dict[str, str],
) -> dict[str, Any]:
    unchanged = tuple(
        duty
        for duty in record.raw_candidate.duties
        if duty.physical_vehicle_id not in record.changed_duty_ids
    )
    unchanged_solution = record.raw_candidate.__class__(
        duties=unchanged,
        source="dss-l1-unchanged-calendar",
    ).to_solution()
    calendar = build_capacity_calendar(
        unchanged_solution,
        schedule_context.instance,
        schedule_context.prices,
    )
    return {
        "case_id": case_id,
        "level": "L1_SAME_CONFIGURATION_NEW_CAPTURE",
        "seed": seed,
        "iteration": record.iteration,
        "action_id": record.action_id,
        "channel": record.channel,
        "instance_id": INSTANCE_ID,
        "evaluation_context_sha256": evaluation_context_sha256(record.context),
        "schedule_contract_sha256": schedule_context.schedule_contract_sha256,
        "reference_fingerprint": record.reference.fingerprint,
        "raw_candidate_fingerprint": record.raw_candidate.fingerprint,
        "changed_duty_ids": sorted(record.changed_duty_ids),
        "unchanged_capacity_calendar_fingerprint": capacity_calendar_fingerprint(calendar),
        "a0_status": record.a0_status,
        "a0_error_type": record.a0_error_type,
        "a0_error": record.a0_error,
        "protected_hashes": protected_hashes,
        "reference": asdict(record.reference),
        "raw_candidate": asdict(record.raw_candidate),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    started = perf_counter()
    test_nodes = (
        "test_capacity_calendar_matches_checker_randomized_multisolution",
        "test_every_terminal_label_is_differentially_priced_and_mismatch_rejected",
        "test_minimum_counterexample_reordering_and_charge_clock_remove_diesel",
        "test_oracle_three_states_cache_identity_and_accounting",
    )
    test_results = [_run_test(repo, node_id) for node_id in test_nodes]
    if any(row["returncode"] != 0 for row in test_results):
        raise RuntimeError("DSS step-1 regression tests did not all pass")

    l0_rows, l0_manifest = _legacy_l0(repo)
    l1_payloads = []
    l1_rows = []
    raw_seed_rows = []
    cold_samples: list[float] = []
    hot_samples: list[float] = []
    end_to_end_samples: list[float] = []
    projected_search_wall = 0.0
    total_actual_iterations = 0

    for seed in SEEDS:
        bundle, initial, _pi0, context = _build_context(repo, INSTANCE_ID)
        preparation_evaluator = DutyFullEvaluator(context)
        policy = _policy(preparation_evaluator)
        candidates, _initial_evaluation, *_ = _prepare_population(
            initial,
            preparation_evaluator,
            policy,
        )
        captured: list[ScheduleCaptureRecord] = []
        with schedule_capture_sink(captured.append):
            result, private_accounting, _arm_initial = _run_arm(
                initial_candidates=candidates,
                context=context,
                iterations=ITERATIONS,
                max_runtime_seconds=MAX_RUNTIME_SECONDS,
                include_mechanisms=True,
                include_charging_candidates=True,
                seed=seed,
            )
        actual_iterations = int(result.accounting.iterations)
        total_actual_iterations += actual_iterations
        schedule_context = ScheduleOracleContext.from_evaluation_context(context)
        oracle = SingleDutyScheduleOracle(schedule_context)
        coordinator = ScheduleCoordinator(schedule_context, oracle)
        status_counts = Counter()
        a0_counts = Counter(record.a0_status for record in captured)
        seed_first_call_wall = 0.0
        seed_end_to_end_wall = 0.0
        for index, record in enumerate(captured, start=1):
            case_id = f"L1-S{seed:02d}-{index:05d}"
            payload = _case_payload(
                case_id=case_id,
                seed=seed,
                record=record,
                schedule_context=schedule_context,
                protected_hashes=protected_before,
            )
            candidate_by_id = {
                duty.physical_vehicle_id: duty
                for duty in record.raw_candidate.duties
            }
            first_results = []
            hot_results = []
            for duty_id in sorted(record.changed_duty_ids):
                first = oracle.solve(candidate_by_id[duty_id])
                first_results.append(first)
                seed_first_call_wall += float(first.wall_seconds)
                if not first.cache_hit:
                    cold_samples.append(float(first.wall_seconds))
                hot = oracle.solve(candidate_by_id[duty_id])
                hot_results.append(hot)
                hot_samples.append(float(hot.wall_seconds))
            coordinated = coordinator.coordinate(
                record.reference,
                record.raw_candidate,
                changed_duty_ids=record.changed_duty_ids,
            )
            end_to_end_samples.append(float(coordinated.wall_seconds))
            seed_end_to_end_wall += float(coordinated.wall_seconds)
            status_counts[coordinated.status.value] += 1
            payload["oracle"] = {
                "status": coordinated.status.value,
                "failure_reason": coordinated.failure_reason,
                "frontier_size": len(coordinated.frontier),
                "wall_seconds_end_to_end": coordinated.wall_seconds,
                "coordinator_accounting": dict(coordinated.accounting),
                "single_duty_first_calls": [
                    {
                        "status": item.status.value,
                        "failure_reason": item.failure_reason,
                        "frontier_size": len(item.frontier),
                        "cache_hit": item.cache_hit,
                        "wall_seconds": item.wall_seconds,
                        "accounting": dict(item.accounting),
                    }
                    for item in first_results
                ],
                "single_duty_hot_calls": [
                    {
                        "status": item.status.value,
                        "cache_hit": item.cache_hit,
                        "wall_seconds": item.wall_seconds,
                    }
                    for item in hot_results
                ],
            }
            l1_payloads.append(payload)
            l1_rows.append(
                {
                    "case_id": case_id,
                    "seed": seed,
                    "iteration": record.iteration,
                    "channel": record.channel,
                    "action_id": record.action_id,
                    "changed_duty_count": len(record.changed_duty_ids),
                    "reference_fingerprint": record.reference.fingerprint,
                    "raw_candidate_fingerprint": record.raw_candidate.fingerprint,
                    "a0_status": record.a0_status,
                    "a0_error_type": record.a0_error_type,
                    "a0_error": record.a0_error,
                    "oracle_status": coordinated.status.value,
                    "oracle_failure_reason": coordinated.failure_reason,
                    "oracle_frontier_size": len(coordinated.frontier),
                    "oracle_end_to_end_wall_seconds": coordinated.wall_seconds,
                    "oracle_first_call_wall_seconds": sum(
                        item.wall_seconds for item in first_results
                    ),
                    "oracle_first_call_cache_misses": sum(
                        not item.cache_hit for item in first_results
                    ),
                    "oracle_hot_call_wall_seconds": sum(
                        item.wall_seconds for item in hot_results
                    ),
                }
            )
        projected_search_wall += seed_first_call_wall + seed_end_to_end_wall
        raw_seed_rows.append(
            {
                "instance_id": INSTANCE_ID,
                "seed": seed,
                "requested_iterations": ITERATIONS,
                "actual_iterations": actual_iterations,
                "search_runtime_seconds": result.accounting.elapsed_seconds,
                "captured_cases": len(captured),
                "a0_schedule_alive": a0_counts["FEASIBLE"],
                "a0_schedule_dead": a0_counts["INFEASIBLE"],
                "oracle_schedule_alive": status_counts[OracleStatus.FEASIBLE.value],
                "oracle_schedule_dead": status_counts[OracleStatus.INFEASIBLE.value],
                "oracle_search_exhausted": status_counts[OracleStatus.SEARCH_EXHAUSTED.value],
                "oracle_first_call_wall_seconds_total": seed_first_call_wall,
                "oracle_end_to_end_wall_seconds_total": seed_end_to_end_wall,
                "a0_rejection_count_reported_by_search": private_accounting.rejected_candidates,
            }
        )

    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    if protected_before != protected_after:
        raise RuntimeError("protected files changed during DSS step-1 run")

    with (output / "l0_historical.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(l0_rows[0]))
        writer.writeheader()
        writer.writerows(l0_rows)
    with (output / "l1_cases.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(l1_rows[0]))
        writer.writeheader()
        writer.writerows(l1_rows)
    (output / "l1_cases.jsonl").write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
            for row in l1_payloads
        ),
        encoding="utf-8",
    )
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(raw_seed_rows[0]))
        writer.writeheader()
        writer.writerows(raw_seed_rows)

    total_cases = len(l1_rows)
    a0_alive = sum(row["a0_status"] == "FEASIBLE" for row in l1_rows)
    a0_dead = total_cases - a0_alive
    oracle_alive = sum(row["oracle_status"] == "FEASIBLE" for row in l1_rows)
    oracle_infeasible = sum(row["oracle_status"] == "INFEASIBLE" for row in l1_rows)
    oracle_exhausted = total_cases - oracle_alive - oracle_infeasible
    oracle_not_alive = total_cases - oracle_alive
    a0_rate = a0_alive / total_cases if total_cases else 0.0
    oracle_rate = oracle_alive / total_cases if total_cases else 0.0
    a0_odds = _odds(a0_alive, a0_dead)
    oracle_odds = _odds(oracle_alive, oracle_not_alive)
    metrics = {
        "paired_cases": total_cases,
        "a0": {
            "schedule_alive": a0_alive,
            "schedule_dead": a0_dead,
            "survival_rate": a0_rate,
            "survival_odds": a0_odds,
        },
        "oracle": {
            "schedule_alive": oracle_alive,
            "schedule_infeasible": oracle_infeasible,
            "search_exhausted": oracle_exhausted,
            "not_alive_total": oracle_not_alive,
            "survival_rate": oracle_rate,
            "survival_odds": oracle_odds,
        },
        "oracle_over_a0": {
            "survival_rate_ratio": _ratio(oracle_rate, a0_rate),
            "survival_odds_ratio": _ratio(oracle_odds, a0_odds),
        },
        "timing_seconds": {
            "single_duty_cold_cache": _summary(cold_samples),
            "single_duty_hot_cache": _summary(hot_samples),
            "coordinator_end_to_end_after_frontier_cache": _summary(
                end_to_end_samples
            ),
            "projected_search_wall_total": projected_search_wall,
            "actual_generations": total_actual_iterations,
            "projected_seconds_per_generation": (
                projected_search_wall / total_actual_iterations
                if total_actual_iterations
                else None
            ),
            "warning_line_seconds_per_generation": 0.10,
        },
    }
    metadata = {
        "status": "COMPLETE",
        "evidence_level": "TECHNICAL_STEP1_PROTOTYPE",
        "formal_experiment": False,
        "instance_id": INSTANCE_ID,
        "seeds": list(SEEDS),
        "requested_iterations_per_seed": ITERATIONS,
        "max_runtime_seconds_per_seed": MAX_RUNTIME_SECONDS,
        "l0": l0_manifest,
        "l1_identity": "same current configuration new capture; not original 313",
        "metrics": metrics,
        "regression_tests": test_results,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
        "code_identity": {
            "git_head": _git(repo, "rev-parse", "HEAD"),
            "git_status": _git(repo, "status", "--porcelain"),
            "python_executable": sys.executable,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "command": list(sys.argv),
        },
        "elapsed_wall_seconds": perf_counter() - started,
    }
    _json(output / "metadata.json", metadata)
    _json(
        output / "decision.json",
        {
            "verdict": "COUNTS_ONLY_NO_PASS_FAIL",
            "user_threshold_applied": False,
            "a0_oracle_metrics": metrics,
            "protected_files_unchanged": True,
            "china81_modified": False,
        },
    )
    cold = metrics["timing_seconds"]["single_duty_cold_cache"]
    hot = metrics["timing_seconds"]["single_duty_hot_cache"]
    per_generation = metrics["timing_seconds"]["projected_seconds_per_generation"]
    rate_ratio = metrics["oracle_over_a0"]["survival_rate_ratio"]
    odds_ratio = metrics["oracle_over_a0"]["survival_odds_ratio"]
    report = f"""# DSS v2 第 1 步：单车 Oracle 原型与首批考题

本包是技术原型证据，不是正式论文实验。L0 只引用 2026-08-10 的 18 个聚合桶（合计 {l0_manifest['total_aggregate_deaths']}），没有把它写成原 313 条逐候选重放；L1 是当前同款配置、PRD50、seed 1/2/11、每个种子最多 {ITERATIONS} 代且 10 秒的新捕获配对集。

L1 共捕获 {total_cases} 个 raw candidate。A0 排程存活 {a0_alive}、死亡 {a0_dead}，存活率 {a0_rate:.12f}，存活赔率 {a0_odds!r}；Oracle 存活 {oracle_alive}、完整判不可行 {oracle_infeasible}、SEARCH_EXHAUSTED {oracle_exhausted}，存活率 {oracle_rate:.12f}，存活赔率 {oracle_odds!r}。Oracle/A0 的存活率比为 {rate_ratio!r}，存活赔率比为 {odds_ratio!r}。这里没有套用数值门槛，也没有下 PASS/FAIL 结论。

冷缓存、热缓存和协调端到端原始逐项时间均在 `l1_cases.csv`；完整 raw candidate、A0 错误和 Oracle 记账在 `l1_cases.jsonl`。容量日历随机等价测试、终止标签差分核验、最小反例和三态/缓存测试的原始 pytest 输出保存在 `metadata.json`。

## 末尾回答
1. 两条强制核验：容量逐键等价测试与终止标签电费/排放/占用差分测试均通过。
2. 最小反例：无 Oracle 的 A0 路径不可达；重排趟序并移动充电窗口后 Oracle 可达，且柴油车由使用变为空闲。
3. L1：A0 死亡/存活={a0_dead}/{a0_alive}，Oracle 不存活/存活={oracle_not_alive}/{oracle_alive}；存活率比={rate_ratio!r}，存活赔率比={odds_ratio!r}。
4. 单车冷缓存 p50={cold['p50']!r}s、热缓存 p50={hot['p50']!r}s；投影端到端={per_generation!r}s/代，{'超过' if per_generation is not None and per_generation > 0.10 else '未超过'} 0.10 秒/代预警线。
"""
    (output / "report.md").write_text(report, encoding="utf-8")
    _json(
        output / "artifact_hashes.json",
        {
            path.name: _sha256(path)
            for path in sorted(output.iterdir())
            if path.is_file() and path.name != "artifact_hashes.json"
        },
    )
    print(json.dumps({"output": str(output), "metrics": metrics}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
