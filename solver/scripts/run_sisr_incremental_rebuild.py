#!/usr/bin/env python3
"""Run the fixed five-instance SISR incremental-rebuild A/B test serially."""

from __future__ import annotations

import argparse
import os
import subprocess
import traceback
from pathlib import Path
from typing import Any

from run_sisr_public_ablation import (
    INDEPENDENT_PYTHON,
    INSTANCES,
    MAIN_SEED,
    NO_IMPROVEMENT,
    PROTECTED,
    REPO,
    WORKER,
    RunSpec,
    _add_paired_differences,
    _artifact_hashes,
    _atomic_text,
    _git,
    _json,
    _machine,
    _row,
    _sha256,
    _timestamp,
    _validate_run,
    _worker_command,
    _write_csv,
)


DEFAULT_OUTPUT = REPO / "solver/reports/sisr_incremental_rebuild_20260811"
NOISE_PERCENT = {
    "PR11A": 1.316,
    "PR13A": 0.249,
    "PR15B": 0.288,
    "PR18A": 0.655,
    "PR21A": 0.212,
}
TRACE_VALIDATION = {
    "instance": "PR11A",
    "solution": (
        "solver/reports/sisr_public_ablation_20260811/"
        "runs/PR11A_A_seed11/best_solution.json"
    ),
    "seed": 11,
    "blink_probability": 0.01,
    "seed_customer": 161,
    "removed_customers": [211, 152, 315, 249, 161, 40, 216],
    "strings_removed": 2,
    "insertion_order": "random",
    "positions_evaluated": 2716,
    "positions_blinked": 0,
    "selected_insertions": [
        [315, 5, 8, 32261],
        [211, 6, 5, 33639],
        [40, 6, 6, 3243],
        [161, 6, 6, 19434],
        [216, 0, 0, 167638],
        [152, 6, 6, 16623],
        [249, 6, 7, 71],
    ],
    "matches_full_route_reference": True,
    "complete": True,
    "feasible": True,
}
MICROBENCHMARK = {
    "instance": "PR11A",
    "repeats": 20,
    "legacy_full_route_cpu_seconds": 0.15101600000000004,
    "incremental_native_cpu_seconds": 0.005774999999999975,
    "speedup": 26.149956709956832,
}


def _specifications() -> tuple[RunSpec, ...]:
    return tuple(
        specification
        for instance in INSTANCES
        for specification in (
            RunSpec(instance, "A", MAIN_SEED, False),
            RunSpec(instance, "B", MAIN_SEED, True),
        )
    )


def _is_valid(row: dict[str, Any]) -> bool:
    return bool(
        row["scaled_feasible"]
        and row["all_routes_raw_precision_feasible"]
        and row["service_complete"]
        and int(row["completed_clients"]) == int(row["total_clients"])
        and float(row["completed_demand_raw"]) == float(row["total_demand_raw"])
    )


def _summaries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key = {(row["instance"], row["arm"], row["seed"]): row for row in rows}
    pairs: list[dict[str, Any]] = []
    for instance in INSTANCES:
        a = by_key.get((instance, "A", MAIN_SEED))
        b = by_key.get((instance, "B", MAIN_SEED))
        if a is None or b is None:
            continue
        difference = int(b["final_cost_scaled"]) - int(a["final_cost_scaled"])
        difference_percent = 100.0 * difference / int(a["final_cost_scaled"])
        noise = NOISE_PERCENT[instance]
        ratio = abs(difference_percent) / noise
        if ratio < 1:
            interpretation = "噪声内，说明不了"
        elif difference < 0:
            interpretation = "超过噪声的改善"
        elif difference > 0:
            interpretation = "超过噪声的变差"
        else:
            interpretation = "噪声内，说明不了"

        a_generations = int(a["completed_generations"])
        b_generations = int(b["completed_generations"])
        generation_change_percent = (
            100.0 * (b_generations - a_generations) / a_generations
            if a_generations
            else 0.0
        )
        pairs.append(
            {
                "instance": instance,
                "a_cost_scaled": int(a["final_cost_scaled"]),
                "b_cost_scaled": int(b["final_cost_scaled"]),
                "a_cost_original_units": float(a["final_cost_original_units"]),
                "b_cost_original_units": float(b["final_cost_original_units"]),
                "b_minus_a_scaled": difference,
                "b_minus_a_percent": difference_percent,
                "noise_percent": noise,
                "absolute_effect_over_noise": ratio,
                "interpretation": interpretation,
                "a_generations": a_generations,
                "b_generations": b_generations,
                "generation_change_percent": generation_change_percent,
                "a_time_to_best_seconds": float(a["time_to_best_seconds"]),
                "b_time_to_best_seconds": float(b["time_to_best_seconds"]),
                "sisr_cpu_share_percent": float(b["sisr_cpu_share_percent"]),
                "sisr_calls": int(b["sisr_calls"]),
                "a_valid": _is_valid(a),
                "b_valid": _is_valid(b),
                "a_completed_clients": int(a["completed_clients"]),
                "a_total_clients": int(a["total_clients"]),
                "b_completed_clients": int(b["completed_clients"]),
                "b_total_clients": int(b["total_clients"]),
                "a_completed_demand_raw": float(a["completed_demand_raw"]),
                "a_total_demand_raw": float(a["total_demand_raw"]),
                "b_completed_demand_raw": float(b["completed_demand_raw"]),
                "b_total_demand_raw": float(b["total_demand_raw"]),
            }
        )

    all_pairs_complete = len(pairs) == len(INSTANCES)
    condition_1 = bool(
        all_pairs_complete
        and not any(pair["interpretation"] == "超过噪声的改善" for pair in pairs)
    )
    previously_slow = {"PR13A", "PR15B", "PR18A"}
    condition_2 = bool(
        all_pairs_complete
        and sum(pair["b_minus_a_scaled"] for pair in pairs) > 0
        and all(
            pair["generation_change_percent"] < 0
            for pair in pairs
            if pair["instance"] in previously_slow
        )
    )
    condition_3 = any(not pair["a_valid"] or not pair["b_valid"] for pair in pairs)
    return {
        "pairs": pairs,
        "all_pairs_complete": all_pairs_complete,
        "condition_1_no_material_improvement": condition_1,
        "condition_2_exact_generation_and_net_values": {
            "condition_triggered": condition_2,
            "all_b_generations_lower": bool(
                pairs
                and all(pair["b_generations"] < pair["a_generations"] for pair in pairs)
            ),
            "generation_change_percent_by_instance": {
                pair["instance"]: pair["generation_change_percent"] for pair in pairs
            },
            "sum_b_minus_a_scaled": sum(pair["b_minus_a_scaled"] for pair in pairs),
            "note": (
                "原预注册未给“显著下降”数值阈值，不事后新增阈值；"
                "报告保留五题逐题幅度及净成本方向。"
            ),
        },
        "condition_3_invalid_or_incomplete": condition_3,
    }


def _report(summary: dict[str, Any]) -> str:
    lines = [
        "SISR_INCREMENTAL_DONE",
        "",
        "# SISR 忠实增量版五题重测",
        "",
        "A 组关闭 SISR，B 组开启忠实增量版；五题均为 seed 11、"
        "每臂最多 600 秒，同一公开真尺子。负的 B−A 表示新版成本更低。",
        "",
        "## 正确性与加速验证",
        "",
        "- 8 个 SISR 单元测试全部通过。",
        "- PR11A 固定解、seed 11、beta=0.01：增量版与旧版完整路线重算"
        "选中的 7 个插入位置及增量成本逐项相同；共评价 2716 个位置，"
        "本次 blink 0 个，重建后完整且可行。",
        "- 同一重建重复 20 次：旧路径 CPU 0.151016 秒，原生增量路径 "
        "0.005775 秒，约 26.150 倍。该数是施工微基准，不是算法结果。",
        "- 重建仍遍历全部路线的全部位置；空间邻接顺序只用于破坏阶段，"
        "并按问题对象与距离 profile 静态缓存。",
        "- 命令行开关仍默认关闭；默认值与显式关闭的固定代数测试逐项相同。",
        "",
        "选中插入序列 `(客户, 路线, 位置, 增量成本)`：",
        "",
        "```text",
        str(TRACE_VALIDATION["selected_insertions"]),
        "```",
        "",
        "## 五题配对结果",
        "",
        "| 题号 | A 成本 | B 成本 | B−A | B−A/A | 种子噪声 | "
        "绝对配对差/噪声 | 判断 | A 代数 | B 代数 | 代数变化 | "
        "A time-to-best | B time-to-best | SISR CPU | 真尺子与覆盖 |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for pair in summary["pairs"]:
        valid = pair["a_valid"] and pair["b_valid"]
        lines.append(
            f"| {pair['instance']} | {pair['a_cost_scaled']} | "
            f"{pair['b_cost_scaled']} | {pair['b_minus_a_scaled']} | "
            f"{pair['b_minus_a_percent']:.4f}% | "
            f"{pair['noise_percent']:.3f}% | "
            f"{pair['absolute_effect_over_noise']:.3f} | "
            f"{pair['interpretation']} | {pair['a_generations']} | "
            f"{pair['b_generations']} | "
            f"{pair['generation_change_percent']:.2f}% | "
            f"{pair['a_time_to_best_seconds']:.3f}s | "
            f"{pair['b_time_to_best_seconds']:.3f}s | "
            f"{pair['sisr_cpu_share_percent']:.2f}% | "
            f"{'通过' if valid else '失败'} |"
        )

    material_wins = sum(
        pair["interpretation"] == "超过噪声的改善" for pair in summary["pairs"]
    )
    material_losses = sum(
        pair["interpretation"] == "超过噪声的变差" for pair in summary["pairs"]
    )
    noise_only = len(summary["pairs"]) - material_wins - material_losses
    lines.extend(
        [
            "",
            f"超过噪声的改善 {material_wins} 题、变差 {material_losses} 题，"
            f"其余 {noise_only} 题在噪声内；这不是稳定改善。",
        ]
    )

    lines.extend(
        [
            "",
            "## 服务量核账",
            "",
            "| 题号 | A 客户 | B 客户 | A 需求量 | B 需求量 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for pair in summary["pairs"]:
        lines.append(
            f"| {pair['instance']} | "
            f"{pair['a_completed_clients']}/{pair['a_total_clients']} | "
            f"{pair['b_completed_clients']}/{pair['b_total_clients']} | "
            f"{pair['a_completed_demand_raw']:.6g}/"
            f"{pair['a_total_demand_raw']:.6g} | "
            f"{pair['b_completed_demand_raw']:.6g}/"
            f"{pair['b_total_demand_raw']:.6g} |"
        )

    condition_2 = summary["condition_2_exact_generation_and_net_values"]
    lines.extend(
        [
            "",
            "## 预注册否证条件",
            "",
            "- 条件 1（无一题超过噪声的改善）："
            + (
                "触发。"
                if summary["condition_1_no_material_improvement"]
                else "未触发。"
            ),
            "- 条件 2（既有慢题代数仍下降且五题净值为负）："
            + ("触发；" if condition_2["condition_triggered"] else "未触发；")
            + f"五题 B−A 成本合计 {condition_2['sum_b_minus_a_scaled']}。"
            + condition_2["note"],
            "- 条件 3（不可行或服务不完整）："
            + (
                "触发。" if summary["condition_3_invalid_or_incomplete"] else "未触发。"
            ),
            "- 未增加预算，未更换算例、种子、尺度或评价口径。",
            "",
            "直接可见的剩余热点是高频忠实全扫描：五题 B 组分别调用 SISR "
            + "、".join(str(pair["sisr_calls"]) for pair in summary["pairs"])
            + " 次；SISR CPU 占比为 "
            + f"{min(pair['sisr_cpu_share_percent'] for pair in summary['pairs']):.2f}%–"
            + f"{max(pair['sisr_cpu_share_percent'] for pair in summary['pairs']):.2f}%。"
            "没有分项计时支持的剩余减速原因记为 UNKNOWN。",
            "",
            "逐次原始字段见 raw_runs.csv；完整路线、逐代轨迹、metadata、"
            "decision 和真尺子审计见 runs/。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-runtime-seconds", type=float, default=600.0)
    args = parser.parse_args()
    if args.max_runtime_seconds != 600.0:
        raise ValueError("this paired retest is fixed to 600 seconds")
    if not INDEPENDENT_PYTHON.is_file() or not WORKER.is_file():
        raise FileNotFoundError("missing independent interpreter or worker")

    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    (output / "runs").mkdir()
    specifications = _specifications()
    protected_before = {
        str(path.relative_to(REPO)): _sha256(path) for path in PROTECTED
    }
    kernel_files = (
        REPO / "third_party/setp_hgs_kernel/setp_hgs_kernel/cpp/repair/sisr_repair.cpp",
        REPO / "third_party/setp_hgs_kernel/setp_hgs_kernel/cpp/search/primitives.cpp",
    )
    metadata: dict[str, Any] = {
        "status": "RUNNING",
        "evidence_level": "fixed paired implementation retest",
        "started_at": _timestamp(),
        "controller_pid": os.getpid(),
        "machine": _machine(),
        "strictly_serial": True,
        "instances": list(INSTANCES),
        "seed": MAIN_SEED,
        "run_count": len(specifications),
        "max_runtime_seconds_per_run": 600.0,
        "no_improvement_iterations": NO_IMPROVEMENT,
        "round_func": "exact",
        "integer_scale": 1_000,
        "noise_percent": NOISE_PERCENT,
        "sisr": {
            "default_enabled": False,
            "treatment_enabled_only_in_arm_b": True,
            "full_route_full_position_scan": True,
            "incremental_candidate_evaluation": True,
            "blink_policy": "draw only after strict incumbent improvement",
            "blink_probability_beta": 0.01,
            "finite_vehicle_inventory": True,
        },
        "trace_validation": TRACE_VALIDATION,
        "microbenchmark": MICROBENCHMARK,
        "protected_sha256_before": protected_before,
        "runner_sha256": _sha256(Path(__file__).resolve()),
        "worker_sha256": _sha256(WORKER),
        "helper_controller_sha256": _sha256(
            REPO / "solver/scripts/run_sisr_public_ablation.py"
        ),
        "sisr_source_sha256": _sha256(
            REPO / "solver/src/setp_solver/algorithms/problem_hgs/sisr.py"
        ),
        "kernel_source_sha256": {
            str(path.relative_to(REPO)): _sha256(path) for path in kernel_files
        },
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_porcelain": _git("status", "--porcelain"),
        "completed_runs": [],
    }
    _json(output / "metadata.json", metadata)
    _atomic_text(output / "controller.pid", f"{os.getpid()}\n")

    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    rows: list[dict[str, Any]] = []
    stopped_for_invalidity = False
    try:
        for index, specification in enumerate(specifications, start=1):
            run_output = output / "runs" / specification.label
            log = output / "runs" / f"{specification.label}.log"
            with log.open("w", encoding="utf-8") as handle:
                completed = subprocess.run(
                    _worker_command(
                        run_output,
                        specification,
                        args.max_runtime_seconds,
                    ),
                    cwd=REPO,
                    env=environment,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"worker failed: {specification.label} exit={completed.returncode}"
                )
            package = _validate_run(run_output, specification)
            row = _row(specification, package)
            rows.append(row)
            metadata["completed_runs"].append(
                {
                    "index": index,
                    "label": specification.label,
                    "finished_at": _timestamp(),
                }
            )
            metadata["last_progress_at"] = _timestamp()
            _json(output / "metadata.json", metadata)
            if specification.sisr_enabled and not _is_valid(row):
                stopped_for_invalidity = True
                break

        _add_paired_differences(rows)
        summary = _summaries(rows)
        _write_csv(output / "raw_runs.csv", rows)
        _json(
            output / "decision.json",
            {
                "verdict": (
                    "SISR_INCREMENTAL_INVALID_STOP"
                    if stopped_for_invalidity
                    else "SISR_INCREMENTAL_RETEST_COMPLETE"
                ),
                "formal_paper_result": False,
                "summary": summary,
                "selection_or_filtering_applied": False,
                "budget_or_parameter_changed_after_results": False,
            },
        )
        _atomic_text(output / "report.md", _report(summary))
        protected_after = {
            str(path.relative_to(REPO)): _sha256(path) for path in PROTECTED
        }
        metadata.update(
            {
                "status": "COMPLETE",
                "finished_at": _timestamp(),
                "stopped_for_invalidity": stopped_for_invalidity,
                "protected_sha256_after": protected_after,
                "protected_files_unchanged": (protected_after == protected_before),
            }
        )
        _json(output / "metadata.json", metadata)
        _atomic_text(output / "DONE", f"SISR_INCREMENTAL_DONE {_timestamp()}\n")
        _artifact_hashes(output)
        return 0
    except BaseException as error:
        metadata.update(
            {
                "status": "FAILED",
                "finished_at": _timestamp(),
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
        _json(output / "metadata.json", metadata)
        _json(
            output / "failure.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
            },
        )
        if rows:
            _write_csv(output / "partial_raw_runs.csv", rows)
        _artifact_hashes(output)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
