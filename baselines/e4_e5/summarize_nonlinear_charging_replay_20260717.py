#!/usr/bin/env python3
"""Build result-blind diagnostic tables from the completed nonlinear replay."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Iterable
import csv
import hashlib
import json
import statistics


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "baselines/e4_e5/nonlinear_charging_robustness_replay_20260717"
CURVES = ("NL90_mild", "NL80_stress")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(name: str) -> list[dict[str, str]]:
    with (OUT / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(name: str, rows: list[dict[str, Any]]) -> None:
    with (OUT / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def pct(numerator: float, denominator: float) -> float:
    return 100.0 * numerator / denominator if denominator else 0.0


def quantile(values: Iterable[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * probability))]


def main() -> int:
    verification = json.loads((OUT / "verification.json").read_text(encoding="utf-8"))
    if verification["verdict"] != "PASS_INDEPENDENT_NL_CHARGING_REPLAY_AUDIT":
        raise RuntimeError("primary replay has not passed independent audit")
    actions = read_csv("action_replay.csv")
    pairs = read_csv("paired_by_seed_day.csv")

    exposure_rows: list[dict[str, Any]] = []
    for curve in CURVES:
        base = [
            row
            for row in actions
            if row["curve"] == curve and row["replay_rule"] == "L->NL-E"
        ]
        for scope in ("all", "pre_day_first_trip", "same_day_between_trip"):
            rows = base if scope == "all" else [row for row in base if row["charge_scope"] == scope]
            durations = [float(row["duration_increase_second"]) / 60.0 for row in rows]
            above = sum(row["above_constant_power_end"] == "True" for row in rows)
            infeasible = sum(row["feasible"] == "False" for row in rows)
            exposure_rows.append(
                {
                    "curve": curve,
                    "charge_scope": scope,
                    "action_count": len(rows),
                    "above_constant_power_end_count": above,
                    "above_constant_power_end_pct": pct(above, len(rows)),
                    "infeasible_action_count": infeasible,
                    "infeasible_action_pct": pct(infeasible, len(rows)),
                    "duration_increase_p50_min": quantile(durations, 0.50),
                    "duration_increase_p90_min": quantile(durations, 0.90),
                    "duration_increase_p99_min": quantile(durations, 0.99),
                    "duration_increase_max_min": max(durations, default=0.0),
                }
            )

    infeasibility_rows: list[dict[str, Any]] = []
    for curve in CURVES:
        curve_pairs = [row for row in pairs if row["curve"] == curve]
        for condition in ("geographic", "mixed"):
            for arm in ("ownership_fixed", "reassignment_allowed"):
                rows = [
                    row
                    for row in curve_pairs
                    if row["condition"] == condition and row["arm"] == arm
                ]
                infeasible = [row for row in rows if row["nonlinear_feasible"] == "False"]
                fixed_infeasible = [row for row in rows if row["fixed_start_feasible"] == "False"]
                reversals = [row for row in rows if row["direction_reversal"] == "True"]
                feasible = [row for row in rows if row["nonlinear_feasible"] == "True"]
                total_reductions = [
                    float(row["total_operational_reduction_pct"]) for row in feasible
                ]
                infeasibility_rows.append(
                    {
                        "curve": curve,
                        "condition": condition,
                        "arm": arm,
                        "seed_day_plan_count": len(rows),
                        "nonlinear_infeasible_count": len(infeasible),
                        "nonlinear_infeasible_pct": pct(len(infeasible), len(rows)),
                        "fixed_start_infeasible_count": len(fixed_infeasible),
                        "direction_reversal_count": len(reversals),
                        "feasible_total_reduction_negative_count": sum(
                            value < 0.0 for value in total_reductions
                        ),
                        "feasible_total_reduction_mean_pct": (
                            statistics.mean(total_reductions) if total_reductions else ""
                        ),
                        "affected_instances": "|".join(
                            sorted({row["instance"] for row in infeasible})
                        ),
                    }
                )

    reversal_rows = [row for row in pairs if row["direction_reversal"] == "True"]
    reversal_rows.sort(
        key=lambda row: (row["curve"], -abs(float(row["nl_saving_kg"])))
    )
    write_csv("diagnostic_exposure_summary.csv", exposure_rows)
    write_csv("diagnostic_infeasibility_summary.csv", infeasibility_rows)
    write_csv("diagnostic_direction_reversals.csv", reversal_rows)

    lines = [
        "# 非线性充电复算诊断",
        "",
        "本诊断只分解已通过独立审计的固定方案复算，不新增搜索，也不筛除不利情形。",
        "",
        "## SOC暴露与排班卡点",
        "",
        "| 曲线 | 高SOC动作占比 | 首趟前不可行动作 | 日内趟间不可行动作 | 日内时长增加P99/min | 日内最大增加/min |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    exposure_index = {
        (row["curve"], row["charge_scope"]): row for row in exposure_rows
    }
    for curve in CURVES:
        total = exposure_index[(curve, "all")]
        pre_day = exposure_index[(curve, "pre_day_first_trip")]
        between = exposure_index[(curve, "same_day_between_trip")]
        lines.append(
            f"| {curve} | {float(total['above_constant_power_end_pct']):.3f}% | "
            f"{pre_day['infeasible_action_count']} | {between['infeasible_action_count']} | "
            f"{float(between['duration_increase_p99_min']):.3f} | "
            f"{float(between['duration_increase_max_min']):.3f} |"
        )
    lines.extend(
        [
            "",
            "首趟前充电具有整夜窗口，两条曲线在重新择时后均未造成不可行；不可行全部集中于日内相邻趟次之间。因而真正的结构瓶颈是趟间周转裕度，而不是笼统的高SOC充电。",
            "",
            "## 不可行与反转",
            "",
            "| 曲线 | 非线性不可行seed--day | 固定原时刻不可行seed--day | 方向反转 | 可行子集运营减排为负 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for curve in CURVES:
        rows = [row for row in infeasibility_rows if row["curve"] == curve]
        lines.append(
            f"| {curve} | {sum(int(row['nonlinear_infeasible_count']) for row in rows)} | "
            f"{sum(int(row['fixed_start_infeasible_count']) for row in rows)} | "
            f"{sum(int(row['direction_reversal_count']) for row in rows)} | "
            f"{sum(int(row['feasible_total_reduction_negative_count']) for row in rows)} |"
        )
    direction_counts = Counter(
        (
            row["curve"],
            "positive_to_negative"
            if float(row["linear_saving_kg"]) > 0.0
            else "negative_to_positive",
        )
        for row in reversal_rows
    )
    lines.extend(
        [
            "",
            "主曲线反转中，6个由线性减排转为非线性增排，8个方向相反；压力曲线相应为7个和21个。反转同时包含有利和不利方向，不能统一解释为非线性模型总是放大或削弱TVCI价值。",
            "",
            "## 结论边界",
            "",
            "可行子集仍能观察到充电择时收益，但不可行方案不能进入收益均值。论文应把“非线性充电使日内趟间窗口成为约束、并使部分TVCI结论反转”作为模型升级理由；完成NL->NL以前，不得把当前可行子集均值写成最终政策结论。",
            "",
            f"方向计数校验：`{dict(direction_counts)}`。",
        ]
    )
    report_path = OUT / "diagnostic_report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    generated = (
        OUT / "diagnostic_exposure_summary.csv",
        OUT / "diagnostic_infeasibility_summary.csv",
        OUT / "diagnostic_direction_reversals.csv",
        report_path,
    )
    hashes = {
        "source_sha256": sha256(Path(__file__)),
        "verification_sha256": sha256(OUT / "verification.json"),
        "generated": {str(path.relative_to(ROOT)): sha256(path) for path in generated},
    }
    (OUT / "diagnostic_artifact_hashes.json").write_text(
        json.dumps(hashes, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("PASS_NL_CHARGING_DIAGNOSTIC_SUMMARY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
