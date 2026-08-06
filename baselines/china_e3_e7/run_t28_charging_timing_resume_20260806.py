#!/usr/bin/env python3
"""Resume T28 in bounded batches while preserving the accepted T26 rows."""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from time import perf_counter, sleep
import traceback
from typing import Any


REPO = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_t21_charging_timing_three_arms_20260805 as base  # noqa: E402


BOOL_RUN_FIELDS = {
    "paper_claim_allowed",
    "iteration_limit_applied",
    "route_pool_mip_extended",
    "unit_succeeded",
    "improvement_at_any_view_limit",
    "improvement_at_total_iteration_limit",
}
BOOL_MIP_FIELDS = {
    "mip_invoked",
    "time_limit_reached",
    "finished_before_time_limit",
    "incumbent_available",
    "optimality_proven",
    "extended",
    "extension_supported",
    "incumbent_trace_supported",
}
CHECKPOINTS = (2_000, 20_000, 100_000)
CONCURRENCY_CONTRACT = "T31_20260806_WORKERS3_BATCH5_SWAP_GUARD"
SWAP_GROWTH_GUARD_MB = 700.0
SWAP_RECHECK_SECONDS = 30.0


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def swap_used_mb() -> float:
    completed = subprocess.run(
        ["/usr/sbin/sysctl", "-n", "vm.swapusage"],
        check=True,
        capture_output=True,
        text=True,
    )
    match = re.search(r"used\s*=\s*([0-9.]+)([MGT])", completed.stdout)
    if match is None:
        raise RuntimeError(
            f"cannot parse vm.swapusage output: {completed.stdout!r}"
        )
    value = float(match.group(1))
    unit = match.group(2)
    return value * {"M": 1.0, "G": 1024.0, "T": 1024.0 * 1024.0}[unit]


def wait_for_swap_to_stop_growing(
    *,
    batch_start_mb: float,
    batch_end_mb: float,
) -> dict[str, Any]:
    growth_mb = batch_end_mb - batch_start_mb
    record: dict[str, Any] = {
        "guard_growth_threshold_mb": SWAP_GROWTH_GUARD_MB,
        "batch_growth_mb": growth_mb,
        "guard_condition_growth_exceeded": growth_mb > SWAP_GROWTH_GUARD_MB,
        "waited": False,
        "samples_mb": [batch_end_mb],
        "sample_interval_seconds": SWAP_RECHECK_SECONDS,
    }
    if growth_mb <= SWAP_GROWTH_GUARD_MB:
        record["release_reason"] = "BATCH_SWAP_GROWTH_NOT_OVER_700_MB"
        return record

    sleep(SWAP_RECHECK_SECONDS)
    current = swap_used_mb()
    record["samples_mb"].append(current)
    if current <= batch_end_mb:
        record["release_reason"] = "SWAP_NOT_STILL_GROWING_AFTER_BATCH"
        return record

    record["waited"] = True
    previous = current
    while True:
        print(
            "SWAP_GUARD_WAIT "
            + json.dumps(record, ensure_ascii=False, sort_keys=True),
            flush=True,
        )
        sleep(SWAP_RECHECK_SECONDS)
        current = swap_used_mb()
        record["samples_mb"].append(current)
        if current <= previous:
            record["release_reason"] = "SWAP_STOPPED_GROWING"
            return record
        previous = current


def read_csv(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or ()), list(reader)


def decode_run(row: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(row)
    for field in BOOL_RUN_FIELDS:
        if field in decoded:
            decoded[field] = parse_bool(decoded[field])
    for field, value in list(decoded.items()):
        if field.endswith("_json") and value not in (None, ""):
            decoded[field] = json.loads(str(value))
    return decoded


def decode_mip(row: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(row)
    for field in BOOL_MIP_FIELDS:
        if field in decoded and decoded[field] not in (None, ""):
            decoded[field] = parse_bool(decoded[field])
    return decoded


def load_existing_results(
    output: Path,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, str]]]:
    original_fields, original_rows = read_csv(output / "raw_runs.csv")
    runs = [decode_run(row) for row in original_rows]
    _, improvement_rows = read_csv(output / "improvement_trace.csv")
    _, slot_rows = read_csv(output / "slot_distribution.csv")
    _, mip_rows = read_csv(output / "mip_timing_audit.csv")
    witnesses_payload = json.loads(
        (output / "solution_witnesses.json").read_text(encoding="utf-8")
    )
    failures_payload = json.loads(
        (output / "failed_units.json").read_text(encoding="utf-8")
    )

    improvements_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in improvement_rows:
        improvements_by_task[str(row["task_id"])].append(dict(row))
    slots_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in slot_rows:
        slots_by_task[str(row["task_id"])].append(dict(row))
    mip_by_task = {
        str(row["task_id"]): decode_mip(row) for row in mip_rows
    }
    witness_by_task = {
        str(item["task"]["task_id"]): item
        for item in witnesses_payload["witnesses"]
    }
    failure_by_task = {
        str(item["task"]["task_id"]): item
        for item in failures_payload["failures"]
    }
    results = []
    for run in runs:
        task_id = str(run["task_id"])
        results.append(
            {
                "run": run,
                "improvements": improvements_by_task.get(task_id, []),
                "slots": slots_by_task.get(task_id, []),
                "mip": mip_by_task.get(task_id),
                "witness": witness_by_task[task_id],
                "failure": failure_by_task.get(task_id),
            }
        )
    return results, original_fields, original_rows


def canonical_rows(
    rows: list[dict[str, Any]], fields: list[str]
) -> str:
    payload = [
        {field: row.get(field, "") for field in fields}
        for row in sorted(rows, key=lambda item: str(item["task_id"]))
    ]
    return base.canonical_sha256(payload)


def verify_retained_rows(
    output: Path,
    fields: list[str],
    expected_hash: str,
    keys: set[tuple[str, str, int]],
    *,
    label: str,
) -> None:
    _, rows = read_csv(output / "raw_runs.csv")
    retained = [
        row
        for row in rows
        if (
            str(row["instance_id"]),
            str(row["arm"]),
            int(row["seed"]),
        )
        in keys
    ]
    if len(retained) != len(keys):
        raise RuntimeError(f"a retained {label} unit disappeared")
    observed = canonical_rows(retained, fields)
    if observed != expected_hash:
        raise RuntimeError(f"a retained {label} raw row changed")


def encoded_keys(keys: set[tuple[str, str, int]]) -> list[dict[str, Any]]:
    return [
        {"instance_id": instance_id, "arm": arm, "seed": seed}
        for instance_id, arm, seed in sorted(keys)
    ]


def decoded_keys(items: list[dict[str, Any]]) -> set[tuple[str, str, int]]:
    return {
        (str(item["instance_id"]), str(item["arm"]), int(item["seed"]))
        for item in items
    }


def captured_future_failure(
    spec: dict[str, Any],
    state_dir: Path,
    exc: BaseException,
) -> dict[str, Any]:
    return base.failure_result(
        spec,
        execution_mode="full",
        state=base.read_unit_state(state_dir, spec),
        exception_type=type(exc).__name__,
        exception_message=str(exc),
        traceback_text=traceback.format_exc(),
    )


def run_batch(
    specs: list[dict[str, Any]],
    *,
    workers: int,
    output: Path,
    existing_results: list[dict[str, Any]],
    original_fields: list[str],
    original_hash: str,
    original_keys: set[tuple[str, str, int]],
    correction_fields: list[str],
    correction_hash: str,
    correction_keys: set[tuple[str, str, int]],
) -> list[dict[str, Any]]:
    if len(specs) > base.MAX_BATCH_UNITS:
        raise ValueError(
            f"T28 batch exceeds the {base.MAX_BATCH_UNITS}-unit ceiling"
        )
    state_dir = output / "unit_states"
    configuration = {
        "iterations": base.DEFAULT_FULL_ITERATIONS,
        "checkpoints": base.REFERENCE_CHECKPOINTS,
        "archives": base.REFERENCE_ARCHIVES,
        "exact_elites": 8,
    }
    new_results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(
        max_workers=workers,
        max_tasks_per_child=1,
    ) as pool:
        futures = {
            pool.submit(
                base.run_one,
                spec,
                execution_mode="full",
                unit_state_dir=state_dir,
                **configuration,
            ): spec
            for spec in specs
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = captured_future_failure(spec, state_dir, exc)
            new_results.append(result)
            base.persist_batch_progress(
                output,
                [*existing_results, *new_results],
                expected_count=90,
            )
            verify_retained_rows(
                output,
                original_fields,
                original_hash,
                original_keys,
                label="pre-T28",
            )
            verify_retained_rows(
                output,
                correction_fields,
                correction_hash,
                correction_keys,
                label="pre-concurrency-correction",
            )
            print(
                f"DONE {result['run']['task_id']} "
                f"{result['run']['terminal_status']}",
                flush=True,
            )
    return sorted(new_results, key=lambda item: item["run"]["task_id"])


def objective_at(
    events: list[dict[str, Any]], checkpoint: int
) -> float | None:
    eligible = [
        event
        for event in events
        if int(event["global_iteration"]) <= checkpoint
    ]
    if not eligible:
        return None
    return float(
        max(eligible, key=lambda item: int(item["global_iteration"]))[
            "objective_after"
        ]
    )


def proxy_capture_rows(
    runs: list[dict[str, Any]], improvements: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in improvements:
        by_task[str(event["task_id"])].append(event)
    output = []
    for run in sorted(runs, key=lambda item: str(item["task_id"])):
        if not bool(run.get("unit_succeeded")):
            continue
        events = sorted(
            by_task[str(run["task_id"])],
            key=lambda item: int(item["global_iteration"]),
        )
        if not events:
            continue
        start = float(events[0]["objective_after"])
        final = float(events[-1]["objective_after"])
        span = start - final
        row: dict[str, Any] = {
            "task_id": run["task_id"],
            "instance_id": run["instance_id"],
            "region": run["region"],
            "arm": run["arm"],
            "seed": run["seed"],
            "first_finite_proxy_objective": start,
            "final_proxy_objective": final,
        }
        for checkpoint in CHECKPOINTS:
            value = objective_at(events, checkpoint)
            row[f"objective_at_{checkpoint}"] = value
            row[f"capture_pct_at_{checkpoint}"] = (
                None
                if value is None or span == 0.0
                else 100.0 * (start - value) / span
            )
        output.append(row)
    return output


def triple(values: list[float]) -> str:
    if not values:
        return "无"
    return (
        f"{min(values):.6f}/{base.numeric_median(values):.6f}/"
        f"{max(values):.6f}"
    )


def t28_contract_violations(
    runs: list[dict[str, Any]],
    improvements: list[dict[str, Any]],
    mips: list[dict[str, Any]],
    batch_summaries: list[dict[str, Any]],
    original_keys: set[tuple[str, str, int]],
) -> list[str]:
    violations: list[str] = []
    keys = [
        (str(row["instance_id"]), str(row["arm"]), int(row["seed"]))
        for row in runs
    ]
    if len(keys) != len(set(keys)):
        violations.append(
            f"duplicate unit keys: rows={len(keys)}, unique={len(set(keys))}"
        )
    new_runs = [row for row, key in zip(runs, keys) if key not in original_keys]
    if len(new_runs) != 82:
        violations.append(f"new T28 unit count={len(new_runs)}, expected=82")
    new_task_ids = {str(row["task_id"]) for row in new_runs}
    for row in new_runs:
        task_id = str(row["task_id"])
        if bool(row.get("unit_succeeded")):
            observed_window = float(row["no_improvement_window_seconds"])
            if observed_window != base.NO_IMPROVEMENT_SECONDS:
                violations.append(
                    f"{task_id} no_improvement_window_seconds="
                    f"{observed_window!r}, expected={base.NO_IMPROVEMENT_SECONDS!r}"
                )
            observed_mip = float(row["route_pool_mip_initial_limit_seconds"])
            if observed_mip != base.SP_TIME_LIMIT_SECONDS:
                violations.append(
                    f"{task_id} route_pool_mip_initial_limit_seconds="
                    f"{observed_mip!r}, expected={base.SP_TIME_LIMIT_SECONDS!r}"
                )
    for row in improvements:
        if str(row["task_id"]) not in new_task_ids:
            continue
        threshold = float(row["timer_reset_threshold_relative"])
        relative = float(row["improvement_relative"])
        reset = parse_bool(row["timer_reset"])
        expected_reset = relative >= base.MINIMUM_RELATIVE_IMPROVEMENT
        if threshold != base.MINIMUM_RELATIVE_IMPROVEMENT:
            violations.append(
                f"{row['task_id']} improvement {row['global_iteration']} "
                f"threshold={threshold!r}, expected="
                f"{base.MINIMUM_RELATIVE_IMPROVEMENT!r}"
            )
        if reset != expected_reset:
            violations.append(
                f"{row['task_id']} improvement {row['global_iteration']} "
                f"relative={relative!r}, timer_reset={reset!r}, "
                f"expected={expected_reset!r}"
            )
    mip_by_task = {
        str(row["task_id"]): row
        for row in mips
        if str(row["task_id"]) in new_task_ids
    }
    for row in new_runs:
        if not bool(row.get("unit_succeeded")):
            continue
        task_id = str(row["task_id"])
        mip = mip_by_task.get(task_id)
        if mip is None:
            violations.append(f"{task_id} has no MIP timing row")
        elif float(mip["initial_time_limit_seconds"]) != base.SP_TIME_LIMIT_SECONDS:
            violations.append(
                f"{task_id} MIP audit initial_time_limit_seconds="
                f"{mip['initial_time_limit_seconds']!r}, expected="
                f"{base.SP_TIME_LIMIT_SECONDS!r}"
            )
    for summary in batch_summaries:
        if summary.get("concurrency_contract") != CONCURRENCY_CONTRACT:
            continue
        if int(summary["unit_count"]) > base.MAX_BATCH_UNITS:
            violations.append(
                f"batch {summary['batch_index']} unit_count="
                f"{summary['unit_count']!r}, ceiling={base.MAX_BATCH_UNITS}"
            )
        if int(summary["unit_worker_count"]) > base.MAX_UNIT_WORKERS:
            violations.append(
                f"batch {summary['batch_index']} unit_worker_count="
                f"{summary['unit_worker_count']!r}, ceiling={base.MAX_UNIT_WORKERS}"
            )
        if int(summary["unit_worker_count"]) != base.MAX_UNIT_WORKERS:
            violations.append(
                f"batch {summary['batch_index']} configured workers="
                f"{summary['unit_worker_count']!r}, expected="
                f"{base.MAX_UNIT_WORKERS}"
            )
        if int(summary.get("actual_concurrent_unit_count", 0)) > int(
            summary["unit_count"]
        ):
            violations.append(
                f"batch {summary['batch_index']} actual concurrency exceeds "
                "its unit count"
            )
        for field in (
            "swap_used_mb_before",
            "swap_used_mb_after",
            "swap_used_mb_change",
        ):
            if field not in summary:
                violations.append(
                    f"batch {summary['batch_index']} missing {field}"
                )
    return violations


def build_report(
    *,
    status: str,
    runs: list[dict[str, Any]],
    improvements: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    mips: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    batch_summaries: list[dict[str, Any]],
    protected_unchanged: bool,
    contract_violations: list[str],
) -> str:
    successful = [row for row in runs if bool(row.get("unit_succeeded"))]
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in improvements:
        by_task[str(event["task_id"])].append(event)
    for events in by_task.values():
        events.sort(key=lambda item: int(item["global_iteration"]))
    capture = proxy_capture_rows(successful, improvements)

    lines = [
        "# T28 分批续跑报告",
        "",
        "## FACT",
        "",
        f"终态：`{status}`。材料化 {len(runs)}/90，成功 {len(successful)}，"
        f"失败 {len(failures)}；`paper_claim_allowed=false`。",
        "",
        "新续跑单元采用相对改善至少 1%、180 秒干等窗口、10 秒 MIP。"
        "本轮按 T31 固定配置 3 个单元 worker、每批最多 5 个单元；"
        "三个视角在单元内顺序执行。原 8 个 T26 单元保留其 600 秒/300 秒历史协议，"
        "并发更正前已完成单元不重跑。",
        "",
        "### 1. 逐单元停机读数",
        "",
        "| 单元 | 总迭代 | 最后一次 >=1% 改善全局迭代 | 总墙钟秒 | 停机触发原因 |",
        "|---|---:|---:|---:|---|",
    ]
    for run in sorted(runs, key=lambda item: str(item["task_id"])):
        if not bool(run.get("unit_succeeded")):
            lines.append(
                f"| `{run['task_id']}` | **⚠️未完成** | **⚠️未完成** | "
                f"{float(run.get('wall_seconds') or 0.0):.6f} | "
                f"**⚠️{run['terminal_status']}** |"
            )
            continue
        material = [
            event
            for event in by_task.get(str(run["task_id"]), [])
            if float(event["improvement_relative"])
            >= base.MINIMUM_RELATIVE_IMPROVEMENT
        ]
        last_material = max(
            (int(event["global_iteration"]) for event in material),
            default=0,
        )
        lines.append(
            f"| `{run['task_id']}` | {int(run['hgs_iterations_total'])} | "
            f"{last_material} | {float(run['wall_seconds']):.6f} | "
            f"{run['stop_trigger_reason']} |"
        )

    lines.extend(
        [
            "",
            "### 2. 代理目标在 2000 / 20000 / 100000 次的捕获",
            "",
            "捕获百分比按每单元首个有限代理目标到最终代理目标的跨度计算；"
            "表中为各算例各策略十种子的 min/median/max，不设置合格线。",
            "",
            "| 算例 | 策略 | 2000 捕获% | 20000 捕获% | 100000 捕获% |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for instance_id, _ in base.INSTANCES:
        for arm, _ in base.ARMS:
            group = [
                row
                for row in capture
                if row["instance_id"] == instance_id and row["arm"] == arm
            ]
            values = {
                checkpoint: [
                    float(row[f"capture_pct_at_{checkpoint}"])
                    for row in group
                    if row[f"capture_pct_at_{checkpoint}"] is not None
                ]
                for checkpoint in CHECKPOINTS
            }
            lines.append(
                f"| `{instance_id}` | {arm} | {triple(values[2000])} | "
                f"{triple(values[20000])} | {triple(values[100000])} |"
            )

    lines.extend(
        [
            "",
            "### 3. 最终完整评价目标值的三策略差异",
            "",
            "| 算例 | 策略 | n | 目标值 min/median/max |",
            "|---|---|---:|---:|",
        ]
    )
    index = {
        (str(row["instance_id"]), int(row["seed"]), str(row["arm"])): row
        for row in successful
    }
    for instance_id, _ in base.INSTANCES:
        for arm, _ in base.ARMS:
            values = [
                float(row["final_full_evaluation_objective"])
                for row in successful
                if row["instance_id"] == instance_id and row["arm"] == arm
            ]
            lines.append(
                f"| `{instance_id}` | {arm} | {len(values)} | {triple(values)} |"
            )
        lines.extend(["", f"`{instance_id}` 同种子策略差（后者减前者）：", ""])
        for left, right in (
            ("ASAP", "COST"),
            ("ASAP", "COST_CARBON"),
            ("COST", "COST_CARBON"),
        ):
            differences = []
            for seed in base.SEEDS:
                left_row = index.get((instance_id, seed, left))
                right_row = index.get((instance_id, seed, right))
                if left_row is not None and right_row is not None:
                    differences.append(
                        float(right_row["final_full_evaluation_objective"])
                        - float(left_row["final_full_evaluation_objective"])
                    )
            lines.append(
                f"- {right} - {left}: n={len(differences)}, "
                f"min/median/max={triple(differences)}。"
            )

    mip_elapsed = [float(row["actual_elapsed_seconds"]) for row in mips]
    mip_limited = sum(parse_bool(row["time_limit_reached"]) for row in mips)
    lines.extend(
        [
            "",
            "### 4. MIP 实耗与撞满比例",
            "",
            "实耗秒 min/median/p90/max = "
            f"{min(mip_elapsed, default=0.0):.6f}/"
            f"{base.numeric_median(mip_elapsed):.6f}/"
            f"{base.numeric_quantile(mip_elapsed, 0.90):.6f}/"
            f"{max(mip_elapsed, default=0.0):.6f}；撞满 {mip_limited}/{len(mips)} "
            f"({(100.0 * mip_limited / len(mips) if mips else 0.0):.3f}%)。",
            "",
            "按初始时限分列（实耗秒 min/median/p90/max；撞满数/总数）：",
            "",
        ]
    )
    for initial_limit in sorted(
        {float(row["initial_time_limit_seconds"]) for row in mips}
    ):
        group = [
            row
            for row in mips
            if float(row["initial_time_limit_seconds"]) == initial_limit
        ]
        elapsed = [float(row["actual_elapsed_seconds"]) for row in group]
        limited = sum(parse_bool(row["time_limit_reached"]) for row in group)
        lines.append(
            f"- 初始时限 {initial_limit:.0f} 秒："
            f"{min(elapsed):.6f}/{base.numeric_median(elapsed):.6f}/"
            f"{base.numeric_quantile(elapsed, 0.90):.6f}/{max(elapsed):.6f}；"
            f"撞满 {limited}/{len(group)}。"
        )
    lines.extend(
        [
            "",
            "### 5. 每 kWh 碳强度、48 槽分布与路线签名",
            "",
            "| 算例 | 策略 | n | kgCO2e/kWh | 48 槽平均电量向量 |",
            "|---|---|---:|---:|---|",
        ]
    )
    slot_vectors: dict[tuple[str, str], list[float]] = defaultdict(
        lambda: [0.0] * 48
    )
    slot_counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in successful:
        slot_counts[(str(row["region"]), str(row["arm"]))] += 1
    for row in slots:
        slot_vectors[(str(row["region"]), str(row["arm"]))][
            int(row["slot_index"])
        ] += float(row["charging_energy_kwh"])
    for instance_id, region in base.INSTANCES:
        for arm, _ in base.ARMS:
            group = [
                row
                for row in successful
                if row["instance_id"] == instance_id and row["arm"] == arm
            ]
            energy = sum(float(row["charging_energy_kwh"]) for row in group)
            emissions = sum(
                float(row["charging_emissions_kgco2e"]) for row in group
            )
            divisor = max(1, slot_counts[(region, arm)])
            vector = [value / divisor for value in slot_vectors[(region, arm)]]
            lines.append(
                f"| `{instance_id}` | {arm} | {len(group)} | "
                f"{(0.0 if energy == 0.0 else emissions / energy):.9f} | "
                "`" + ", ".join(f"{value:.6f}" for value in vector) + "` |"
            )
        identical = 0
        comparable = 0
        for seed in base.SEEDS:
            signatures = [
                index.get((instance_id, seed, arm), {}).get("route_signature")
                for arm, _ in base.ARMS
            ]
            if all(signatures):
                comparable += 1
                identical += len(set(signatures)) == 1
        lines.append(
            f"路线签名三策略相同：`{instance_id}` {identical}/{comparable}。"
        )

    lines.extend(
        [
            "",
            "### 6. 服务量红线、违反、闭合误差与失败清单",
            "",
            "| 单元 | 客户完成/要求 | 需求完成/要求 | 违反数 | 闭合误差 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in sorted(runs, key=lambda item: str(item["task_id"])):
        if not bool(row.get("unit_succeeded")):
            lines.append(
                f"| `{row['task_id']}` | **⚠️未评价** | **⚠️未评价** | "
                "**⚠️未评价** | **⚠️未评价** |"
            )
            continue
        service_ok = (
            int(row["completed_customer_count"])
            == int(row["required_customer_count"])
            and math.isclose(
                float(row["completed_demand"]),
                float(row["required_demand"]),
                rel_tol=0.0,
                abs_tol=1.0e-9,
            )
        )
        customer = f"{row['completed_customer_count']}/{row['required_customer_count']}"
        demand = f"{row['completed_demand']}/{row['required_demand']}"
        if not service_ok:
            customer = f"**⚠️{customer}**"
            demand = f"**⚠️{demand}**"
        violations = int(row["violation_count"])
        violation_text = str(violations) if violations == 0 else f"**⚠️{violations}**"
        lines.append(
            f"| `{row['task_id']}` | {customer} | {demand} | "
            f"{violation_text} | {float(row['closure_error']):.12g} |"
        )
    lines.extend(["", "失败单元：", ""])
    if failures:
        for failure in failures:
            lines.append(
                f"- `{failure['task']['task_id']}`: {failure['exception_type']}: "
                f"{failure['exception_message']}；最后阶段 "
                f"`{failure['failure_stage']}`。"
            )
    else:
        lines.append("无失败单元。")

    lines.extend(
        [
            "",
            "### 7. 分批墙钟与系统负载",
            "",
            "| 批次 | 单元数 | worker 配置 | 实际并发上限 | 完成 | 失败 | 批墙钟秒 | 单元墙钟中位秒 | 开始/结束 1 分钟负载 | 开始/结束交换区 MB | 交换区变化 MB | 等待恢复 |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|",
        ]
    )
    for item in batch_summaries:
        swap_before = item.get("swap_used_mb_before")
        swap_after = item.get("swap_used_mb_after")
        swap_change = item.get("swap_used_mb_change")
        swap_text = (
            "历史未记录"
            if swap_before is None or swap_after is None
            else f"{float(swap_before):.2f}/{float(swap_after):.2f}"
        )
        swap_change_text = (
            "历史未记录"
            if swap_change is None
            else f"{float(swap_change):.2f}"
        )
        guard = item.get("swap_guard") or {}
        lines.append(
            f"| {item['batch_index']} | {item['unit_count']} | "
            f"{item['unit_worker_count']} | "
            f"{item.get('actual_concurrent_unit_count', item['unit_count'])} | "
            f"{item['successful_count']} | {item['failed_count']} | "
            f"{item['batch_wall_seconds']:.6f} | "
            f"{item['unit_wall_seconds_median']:.6f} | "
            f"{float(item['load_average_before'][0]):.6f}/"
            f"{float(item['load_average_after'][0]):.6f} | "
            f"{swap_text} | {swap_change_text} | "
            f"{bool(guard.get('waited', False))} |"
        )
    lines.extend(["", "T28 合同校验：", ""])
    if contract_violations:
        for violation in contract_violations:
            lines.append(f"- **⚠️{violation}**")
    else:
        lines.append("无合同校验违反。")
    lines.extend(
        [
            "",
            "## INFERENCE",
            "",
            "无新增科学阈值或方向判定；以上均为探索批观察值。",
            "",
            "## DECISION",
            "",
            "`paper_claim_allowed=false`。",
            "",
            "## HALT_*",
            "",
            (f"`{status}`。" if status.startswith("HALT_") else "无。"),
            "",
            f"三个受保护文件开工/收工 SHA-256 一致：{protected_unchanged}。",
        ]
    )
    return "\n".join(lines) + "\n"


def finalize(
    output: Path,
    results: list[dict[str, Any]],
    batch_summaries: list[dict[str, Any]],
    protected_before: dict[str, str],
    original_keys: set[tuple[str, str, int]],
) -> str:
    runs, improvements, slots, mips, _, failures = base.collected_rows(results)
    successful = [row for row in runs if bool(row.get("unit_succeeded"))]
    protected_after = base.protected_hashes()
    protected_unchanged = protected_before == protected_after
    contract_violations = t28_contract_violations(
        runs,
        improvements,
        mips,
        batch_summaries,
        original_keys,
    )
    status = (
        "T28_EXPLORATORY_90_UNITS_COMPLETE"
        if (
            len(runs) == 90
            and len(successful) == 90
            and not failures
            and not contract_violations
        )
        else "HALT_T28_FULL_UNIT_FAILURES_OR_MISSING_RESULTS"
    )
    capture_rows = proxy_capture_rows(successful, improvements)
    capture_fields = [
        "task_id",
        "instance_id",
        "region",
        "arm",
        "seed",
        "first_finite_proxy_objective",
        "objective_at_2000",
        "capture_pct_at_2000",
        "objective_at_20000",
        "capture_pct_at_20000",
        "objective_at_100000",
        "capture_pct_at_100000",
        "final_proxy_objective",
    ]
    base.atomic_csv(
        output / "proxy_capture_checkpoints.csv",
        capture_rows,
        capture_fields,
    )
    base.atomic_json(output / "batch_summaries.json", batch_summaries)
    metadata = {
        "schema_version": base.SCHEMA,
        "status": status,
        "completed_at_utc": utc_now(),
        "paper_claim_allowed": False,
        "materialized_unit_count": len(runs),
        "successful_unit_count": len(successful),
        "failed_unit_count": len(failures),
        "minimum_relative_improvement": base.MINIMUM_RELATIVE_IMPROVEMENT,
        "no_improvement_seconds_per_view": base.NO_IMPROVEMENT_SECONDS,
        "mip_time_limit_seconds": base.SP_TIME_LIMIT_SECONDS,
        "max_unit_workers": base.MAX_UNIT_WORKERS,
        "max_batch_units": base.MAX_BATCH_UNITS,
        "protected_file_sha256_before_t28": protected_before,
        "protected_file_sha256_after_t28": protected_after,
        "protected_files_unchanged": protected_unchanged,
        "contract_violation_count": len(contract_violations),
        "contract_violations": contract_violations,
    }
    base.atomic_json(output / "metadata.json", metadata)
    base.atomic_json(
        output / "decision.json",
        {
            "schema_version": "resetp.t28-decision.v1",
            "status": status,
            "FACT": {
                "materialized_unit_count": len(runs),
                "successful_unit_count": len(successful),
                "failed_unit_count": len(failures),
                "batch_count": len(batch_summaries),
                "protected_files_unchanged": protected_unchanged,
                "contract_violation_count": len(contract_violations),
                "contract_violations": contract_violations,
            },
            "INFERENCE": "No additional threshold or result-direction decision was made.",
            "DECISION": "paper_claim_allowed=false",
            "HALT": status if status.startswith("HALT_") else None,
        },
    )
    base.atomic_text(
        output / "report.md",
        build_report(
            status=status,
            runs=runs,
            improvements=improvements,
            slots=slots,
            mips=mips,
            failures=failures,
            batch_summaries=batch_summaries,
            protected_unchanged=protected_unchanged,
            contract_violations=contract_violations,
        ),
    )
    done = {
        "schema_version": "resetp.t28-done.v1",
        "status": status,
        "completed_at_utc": utc_now(),
        "registered_unit_count": 90,
        "materialized_unit_count": len(runs),
        "successful_unit_count": len(successful),
        "failed_unit_count": len(failures),
        "paper_claim_allowed": False,
    }
    base.atomic_json(output / "done.json", done)
    base.atomic_json(output / "t28_done.json", done)
    base.atomic_json(
        output / "artifact_hashes.json",
        {
            "schema_version": "resetp.clean-artifact-hashes.v1",
            "excluded": ["._*", "__pycache__", ".pytest_cache"],
            "files": base.artifact_hashes(output),
        },
    )
    if not protected_unchanged:
        raise RuntimeError("protected-file hashes changed during T28")
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--smoke-checks", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=base.MAX_UNIT_WORKERS)
    parser.add_argument("--batch-size", type=int, default=base.MAX_BATCH_UNITS)
    args = parser.parse_args()
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise RuntimeError("PYTHONHASHSEED must equal 0")
    if not 1 <= args.workers <= base.MAX_UNIT_WORKERS:
        parser.error(f"workers must be in [1, {base.MAX_UNIT_WORKERS}]")
    if not 1 <= args.batch_size <= base.MAX_BATCH_UNITS:
        parser.error(f"batch size must be in [1, {base.MAX_BATCH_UNITS}]")
    smoke = json.loads(args.smoke_checks.read_text(encoding="utf-8"))
    if not bool(smoke.get("passed")):
        raise RuntimeError("T28 smoke did not pass; full resume is forbidden")

    output = args.output.resolve()
    existing, current_fields, current_rows = load_existing_results(output)
    current_keys = [
        (str(row["instance_id"]), str(row["arm"]), int(row["seed"]))
        for row in current_rows
    ]
    if len(current_keys) != len(set(current_keys)):
        raise RuntimeError(
            f"duplicate materialized unit keys: rows={len(current_keys)} "
            f"unique_keys={len(set(current_keys))}"
        )
    correction_path = output / "t28_concurrency_correction.json"
    if correction_path.exists():
        correction = json.loads(correction_path.read_text(encoding="utf-8"))
        correction_keys = decoded_keys(
            correction["retained_materialized_keys"]
        )
        correction_fields = [
            str(field) for field in correction["retained_raw_fields"]
        ]
        correction_hash = str(
            correction["retained_raw_rows_canonical_sha256"]
        )
        if int(correction["configured_unit_workers"]) != base.MAX_UNIT_WORKERS:
            raise RuntimeError("saved concurrency correction worker count drifted")
        if int(correction["max_batch_units"]) != base.MAX_BATCH_UNITS:
            raise RuntimeError("saved concurrency correction batch ceiling drifted")
    else:
        if len(current_rows) != 70:
            raise RuntimeError(
                "concurrency correction must start from the user-registered "
                f"70 materialized units, observed={len(current_rows)}"
            )
        correction_fields = current_fields
        correction_keys = set(current_keys)
        correction_hash = canonical_rows(current_rows, correction_fields)
        base.atomic_json(
            correction_path,
            {
                "schema_version": "resetp.t28-concurrency-correction.v1",
                "recorded_at_utc": utc_now(),
                "paper_claim_allowed": False,
                "materialized_unit_count_before_correction": len(current_rows),
                "retained_materialized_keys": encoded_keys(correction_keys),
                "retained_raw_fields": correction_fields,
                "retained_raw_rows_canonical_sha256": correction_hash,
                "configured_unit_workers": base.MAX_UNIT_WORKERS,
                "max_batch_units": base.MAX_BATCH_UNITS,
                "views_execute_sequentially_within_each_unit": True,
                "swap_growth_guard_mb": SWAP_GROWTH_GUARD_MB,
                "swap_growth_must_stop_before_next_batch": True,
            },
        )
    amendment_path = output / "t28_contract_amendment.json"
    if amendment_path.exists():
        amendment = json.loads(amendment_path.read_text(encoding="utf-8"))
        original_keys = decoded_keys(amendment["accepted_pre_t28_keys"])
        original_fields = [
            str(field) for field in amendment["accepted_pre_t28_raw_fields"]
        ]
        original_hash = str(
            amendment["accepted_pre_t28_raw_rows_canonical_sha256"]
        )
        protected_before = {
            str(path): str(digest)
            for path, digest in amendment[
                "protected_file_sha256_before_t28"
            ].items()
        }
    else:
        original_fields = current_fields
        original_keys = set(current_keys)
        if len(current_rows) != 8 or len(original_keys) != 8:
            raise RuntimeError(
                f"expected exactly 8 accepted rows before T28, got "
                f"rows={len(current_rows)} unique_keys={len(original_keys)}"
            )
        original_hash = canonical_rows(current_rows, original_fields)
        protected_before = base.protected_hashes()
        base.atomic_json(
            amendment_path,
            {
                "schema_version": "resetp.t28-contract-amendment.v1",
                "created_at_utc": utc_now(),
                "created_before_t28_resume_results": True,
                "paper_claim_allowed": False,
                "accepted_pre_t28_unit_count": 8,
                "accepted_pre_t28_keys": encoded_keys(original_keys),
                "accepted_pre_t28_raw_fields": original_fields,
                "accepted_pre_t28_raw_rows_canonical_sha256": original_hash,
                "remaining_unit_count_at_first_launch": 82,
                "minimum_relative_improvement": 0.01,
                "no_improvement_seconds_per_view": 180.0,
                "mip_time_limit_seconds": 10.0,
                "max_unit_workers": base.MAX_UNIT_WORKERS,
                "max_batch_units": base.MAX_BATCH_UNITS,
                "PYTHONHASHSEED": "0",
                "protected_file_sha256_before_t28": protected_before,
            },
        )
    if len(original_keys) != 8:
        raise RuntimeError(
            f"accepted pre-T28 key count={len(original_keys)}, expected=8"
        )
    verify_retained_rows(
        output,
        original_fields,
        original_hash,
        original_keys,
        label="pre-T28",
    )
    verify_retained_rows(
        output,
        correction_fields,
        correction_hash,
        correction_keys,
        label="pre-concurrency-correction",
    )
    materialized_keys = set(current_keys)
    remaining = [
        spec
        for spec in base.full_manifest()
        if (
            str(spec["instance_id"]),
            str(spec["arm"]),
            int(spec["seed"]),
        )
        not in materialized_keys
    ]
    if len(materialized_keys) + len(remaining) != 90:
        raise RuntimeError(
            f"manifest closure mismatch: materialized={len(materialized_keys)} "
            f"remaining={len(remaining)}"
        )

    results = list(existing)
    batch_summary_path = output / "batch_summaries.json"
    batch_summaries: list[dict[str, Any]] = (
        json.loads(batch_summary_path.read_text(encoding="utf-8"))
        if batch_summary_path.exists()
        else []
    )
    covered_task_ids = {
        str(task_id)
        for summary in batch_summaries
        for task_id in summary["task_ids"]
    }
    unaccounted_results = [
        item
        for item in results
        if (
            (
                str(item["run"]["instance_id"]),
                str(item["run"]["arm"]),
                int(item["run"]["seed"]),
            )
            not in correction_keys
            and str(item["run"]["task_id"]) not in covered_task_ids
        )
    ]
    if unaccounted_results:
        recovery_path = output / "t28_runtime_recovery.json"
        if not recovery_path.exists():
            raise RuntimeError(
                "materialized T28 units are missing batch accounting and "
                "no runtime-recovery record exists"
            )
        recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
        expected_recovered = set(
            recovery["facts"]["completed_units_in_interrupted_batch"]
        )
        observed_recovered = {
            str(item["run"]["task_id"]) for item in unaccounted_results
        }
        if observed_recovered != expected_recovered:
            raise RuntimeError(
                "runtime-recovery task ids do not match unaccounted rows: "
                f"expected={sorted(expected_recovered)!r}, "
                f"observed={sorted(observed_recovered)!r}"
            )
        batch_summaries.append(
            {
                "batch_index": len(batch_summaries) + 1,
                "started_at_unit_offset": sum(
                    int(item["unit_count"]) for item in batch_summaries
                ),
                "unit_count": len(unaccounted_results),
                "unit_worker_count": 3,
                "blas_threads_per_process": 1,
                "maximum_configured_compute_threads": 9,
                "max_tasks_per_child": None,
                "successful_count": sum(
                    bool(item["run"].get("unit_succeeded"))
                    for item in unaccounted_results
                ),
                "failed_count": sum(
                    bool(item["failure"]) for item in unaccounted_results
                ),
                "batch_wall_seconds": float(
                    recovery["facts"][
                        "interrupted_batch_elapsed_until_exit_seconds"
                    ]
                ),
                "unit_wall_seconds_median": base.numeric_median(
                    [
                        float(item["run"].get("wall_seconds") or 0.0)
                        for item in unaccounted_results
                    ]
                ),
                "load_average_before": recovery["facts"][
                    "interrupted_batch_load_average_before"
                ],
                "load_average_after": recovery["facts"][
                    "interrupted_batch_load_average_at_exit"
                ],
                "completed_at_utc": recovery["facts"][
                    "monitor_exit_snapshot"
                ]["checked_at_utc"],
                "task_ids": sorted(observed_recovered),
                "interrupted_before_batch_closure": True,
                "runtime_recovery_record": recovery_path.name,
            }
        )
        base.atomic_json(batch_summary_path, batch_summaries)
    resumed_unit_offset = 82 - len(remaining)
    for start in range(0, len(remaining), args.batch_size):
        specs = remaining[start : start + args.batch_size]
        batch_index = len(batch_summaries) + 1
        before_load = tuple(round(value, 6) for value in os.getloadavg())
        swap_before = swap_used_mb()
        batch_started = perf_counter()
        new_results = run_batch(
            specs,
            workers=args.workers,
            output=output,
            existing_results=results,
            original_fields=original_fields,
            original_hash=original_hash,
            original_keys=original_keys,
            correction_fields=correction_fields,
            correction_hash=correction_hash,
            correction_keys=correction_keys,
        )
        results.extend(new_results)
        elapsed = perf_counter() - batch_started
        walls = [
            float(item["run"].get("wall_seconds") or 0.0)
            for item in new_results
        ]
        swap_after = swap_used_mb()
        actual_concurrency = min(args.workers, len(specs))
        summary = {
            "concurrency_contract": CONCURRENCY_CONTRACT,
            "batch_index": batch_index,
            "started_at_unit_offset": resumed_unit_offset + start,
            "unit_count": len(specs),
            "unit_worker_count": args.workers,
            "actual_concurrent_unit_count": actual_concurrency,
            "blas_threads_per_process": 1,
            "maximum_configured_compute_threads": actual_concurrency,
            "views_execute_sequentially_within_each_unit": True,
            "max_tasks_per_child": 1,
            "successful_count": sum(
                bool(item["run"].get("unit_succeeded"))
                for item in new_results
            ),
            "failed_count": sum(bool(item["failure"]) for item in new_results),
            "batch_wall_seconds": elapsed,
            "unit_wall_seconds_median": base.numeric_median(walls),
            "load_average_before": list(before_load),
            "load_average_after": [
                round(value, 6) for value in os.getloadavg()
            ],
            "swap_used_mb_before": swap_before,
            "swap_used_mb_after": swap_after,
            "swap_used_mb_change": swap_after - swap_before,
            "completed_at_utc": utc_now(),
            "task_ids": [str(spec["task_id"]) for spec in specs],
        }
        batch_summaries.append(summary)
        base.atomic_json(output / "batch_summaries.json", batch_summaries)
        print(
            "BATCH_SUMMARY "
            + json.dumps(summary, ensure_ascii=False, sort_keys=True),
            flush=True,
        )
        is_final_batch = start + args.batch_size >= len(remaining)
        if is_final_batch:
            summary["swap_guard"] = {
                "waited": False,
                "release_reason": "NO_NEXT_BATCH",
                "batch_growth_mb": swap_after - swap_before,
                "guard_growth_threshold_mb": SWAP_GROWTH_GUARD_MB,
            }
        else:
            summary["swap_guard"] = wait_for_swap_to_stop_growing(
                batch_start_mb=swap_before,
                batch_end_mb=swap_after,
            )
        base.atomic_json(output / "batch_summaries.json", batch_summaries)
        print(
            "SWAP_GUARD_RESULT "
            + json.dumps(
                {
                    "batch_index": batch_index,
                    **summary["swap_guard"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )

    status = finalize(
        output,
        results,
        batch_summaries,
        protected_before,
        original_keys,
    )
    return 0 if status == "T28_EXPLORATORY_90_UNITS_COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
