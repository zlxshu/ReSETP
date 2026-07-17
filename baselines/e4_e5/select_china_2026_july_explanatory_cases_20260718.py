#!/usr/bin/env python3
"""Select result-blind explanatory days from the full July 2026 CEF panel.

The selector reads only the constructed CEF panel and frozen policy time bands.
It does not read absolute tariff rows, routes, charging actions, solver outputs,
or experiment results. All 31 days remain in the formal panel; selected days
are for explanatory figures only.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE_DIR = REPO / "baselines/e4_e5/china_tvci_2026_interpolated_july_panel_20260718"
SOURCE = SOURCE_DIR / "tvci_2026_july_full_month_48slot_wide.csv"
OUTPUT = REPO / "baselines/e4_e5/china_2026_july_explanatory_cases_20260718"
REGIONS = ("Beijing", "Guangdong", "Chongqing")
BAND_SCORE = {"valley": 0.0, "flat": 1.0, "peak": 2.0, "sharp_peak": 3.0}
POLICY_URLS = {
    "Beijing": "https://fgw.beijing.gov.cn/fgwzwgk/2024zcwj/bwgfxwj/202308/t20230821_3718725.htm",
    "Guangdong": "https://fgw.sz.gov.cn/zwgk/qt/tzgg/content/post_9493596.html",
    "Chongqing": "https://fzggw.cq.gov.cn/zwgk/zfxxgkml/zcwj/xzgfxwj/sfzggwxzgfxwj/202112/t20211209_10119678_wap.html",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def band(region: str, minute: int) -> str:
    if region == "Beijing":
        if minute >= 23 * 60 or minute < 7 * 60:
            return "valley"
        if 11 * 60 <= minute < 13 * 60 or 16 * 60 <= minute < 17 * 60:
            return "sharp_peak"
        if 10 * 60 <= minute < 13 * 60 or 17 * 60 <= minute < 22 * 60:
            return "peak"
        return "flat"
    if region == "Guangdong":
        if minute < 8 * 60:
            return "valley"
        if 11 * 60 <= minute < 12 * 60 or 15 * 60 <= minute < 17 * 60:
            return "sharp_peak"
        if 10 * 60 <= minute < 12 * 60 or 14 * 60 <= minute < 19 * 60:
            return "peak"
        return "flat"
    if region == "Chongqing":
        if minute < 8 * 60:
            return "valley"
        if 12 * 60 <= minute < 14 * 60:
            return "sharp_peak"
        if 11 * 60 <= minute < 17 * 60 or 20 * 60 <= minute < 22 * 60:
            return "peak"
        return "flat"
    raise ValueError(region)


def pearson(left: list[float], right: list[float]) -> float:
    mean_left = statistics.fmean(left)
    mean_right = statistics.fmean(right)
    numerator = sum(
        (x - mean_left) * (y - mean_right) for x, y in zip(left, right, strict=True)
    )
    denominator = math.sqrt(
        sum((x - mean_left) ** 2 for x in left)
        * sum((y - mean_right) ** 2 for y in right)
    )
    if denominator == 0:
        raise ValueError("zero variance in correlation input")
    return numerator / denominator


def load_metrics() -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    with SOURCE.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            minute = int(row["hour_of_day"]) * 60 + int(row["minute"])
            for region in REGIONS:
                grouped[(region, row["date"])].append((minute, float(row[region])))
    if len(grouped) != len(REGIONS) * 31:
        raise ValueError(f"expected 93 region-days, found {len(grouped)}")

    metrics: list[dict[str, object]] = []
    for (region, date), values in sorted(grouped.items()):
        if len(values) != 48:
            raise ValueError(f"{region} {date} has {len(values)} slots")
        carbon = [value for _, value in values]
        price_scores = [BAND_SCORE[band(region, minute)] for minute, _ in values]
        sorted_carbon = sorted(carbon)
        low_eight = statistics.fmean(sorted_carbon[:8])
        high_eight = statistics.fmean(sorted_carbon[-8:])
        metrics.append(
            {
                "region": region,
                "date": date,
                "daily_mean_gCO2_per_kWh": statistics.fmean(carbon),
                "intraday_range_gCO2_per_kWh": max(carbon) - min(carbon),
                "eight_slot_shift_potential_gCO2_per_kWh": high_eight - low_eight,
                "carbon_price_band_correlation": pearson(carbon, price_scores),
                "optimization_results_read": 0,
            }
        )
    return metrics


def choose_cases(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    for region in REGIONS:
        rows = [row for row in metrics if row["region"] == region]
        used: set[str] = set()

        def take(case: str, key) -> None:
            candidates = [row for row in rows if row["date"] not in used]
            chosen = min(candidates, key=key)
            used.add(str(chosen["date"]))
            selected.append(
                {
                    "region": region,
                    "case_role": case,
                    **chosen,
                    "formal_panel_membership": "retained_1_of_31",
                    "use_boundary": "explanatory_figure_only_not_primary_estimate",
                }
            )

        take(
            "least_conflicted_profile",
            lambda row: (
                -float(row["carbon_price_band_correlation"]),
                -float(row["eight_slot_shift_potential_gCO2_per_kWh"]),
                row["date"],
            ),
        )
        take(
            "strongest_carbon_cost_conflict",
            lambda row: (
                float(row["carbon_price_band_correlation"]),
                -float(row["eight_slot_shift_potential_gCO2_per_kWh"]),
                row["date"],
            ),
        )
        take(
            "maximum_intraday_flexibility",
            lambda row: (
                -float(row["eight_slot_shift_potential_gCO2_per_kWh"]),
                row["date"],
            ),
        )
        med_range = statistics.median(
            float(row["intraday_range_gCO2_per_kWh"]) for row in rows
        )
        med_corr = statistics.median(
            float(row["carbon_price_band_correlation"]) for row in rows
        )
        range_span = max(
            float(row["intraday_range_gCO2_per_kWh"]) for row in rows
        ) - min(float(row["intraday_range_gCO2_per_kWh"]) for row in rows)
        corr_span = max(
            float(row["carbon_price_band_correlation"]) for row in rows
        ) - min(float(row["carbon_price_band_correlation"]) for row in rows)
        take(
            "typical_joint_profile",
            lambda row: (
                abs(float(row["intraday_range_gCO2_per_kWh"]) - med_range)
                / range_span
                + abs(float(row["carbon_price_band_correlation"]) - med_corr)
                / corr_span,
                row["date"],
            ),
        )
    return selected


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    metrics = load_metrics()
    cases = choose_cases(metrics)
    if len(cases) != 12:
        raise ValueError(f"expected 12 explanatory cases, found {len(cases)}")
    write_csv(OUTPUT / "all_region_day_external_metrics.csv", metrics)
    write_csv(OUTPUT / "selected_explanatory_cases.csv", cases)

    metadata = {
        "schema": "resetp.china-2026-july-explanatory-cases.v1",
        "carbon_source": str(SOURCE.relative_to(REPO)),
        "carbon_source_sha256": sha256(SOURCE),
        "policy_urls": POLICY_URLS,
        "price_representation": "ordinal tariff bands only; no depot contract row used",
        "formal_panel_days_per_region": 31,
        "selected_cases_per_region": 4,
        "selection_roles": [
            "least_conflicted_profile",
            "strongest_carbon_cost_conflict",
            "maximum_intraday_flexibility",
            "typical_joint_profile",
        ],
        "search_evaluations": 0,
        "optimization_results_read": False,
        "status": "ARCHIVE_2026_EXPLANATORY_METHOD_ONLY",
    }
    write_json(OUTPUT / "metadata.json", metadata)
    write_csv(
        OUTPUT / "raw_runs.csv",
        [
            {"check": "region_days", "observed": len(metrics), "expected": 93, "status": "PASS"},
            {"check": "cases", "observed": len(cases), "expected": 12, "status": "PASS"},
            {"check": "optimization_results_read", "observed": 0, "expected": 0, "status": "PASS"},
        ],
    )
    write_json(
        OUTPUT / "decision.json",
        {
            "decision": "ARCHIVE_2026_EXPLANATORY_METHOD_ONLY",
            "authorizes": [
                "audit the archived explanatory-case selection method",
            ],
            "does_not_authorize": [
                "use in formal China E1-E7 figures, estimates, or manifests",
                "using four cases as the primary effect estimate",
                "dropping weak or adverse days from the 31-day panel",
                "claiming a favorable optimization outcome before formal search",
            ],
            "search_evaluations": 0,
        },
    )

    lines = [
        "# 中国 2026 年 7 月解释性案例盲选",
        "",
        "判定：`ARCHIVE_2026_EXPLANATORY_METHOD_ONLY`。",
        "",
        "本选择只读取 2026 插值碳曲线和三地官方分时时段，不读取绝对合同价、",
        "路线、充电动作、求解器或实验结果。用户已裁决正式链回退到原始2025数据，",
        "因此本包只保留为方法档案，禁止进入正式图表、估计或manifest。",
        "",
        "| 区域 | 冲突最弱日 | 冲突最强日 | 最大灵活性日 | 典型日 |",
        "|---|---|---|---|---|",
    ]
    by_region_role = {
        (str(row["region"]), str(row["case_role"])): str(row["date"]) for row in cases
    }
    for region in REGIONS:
        lines.append(
            f"| {region} | "
            f"{by_region_role[(region, 'least_conflicted_profile')]} | "
            f"{by_region_role[(region, 'strongest_carbon_cost_conflict')]} | "
            f"{by_region_role[(region, 'maximum_intraday_flexibility')]} | "
            f"{by_region_role[(region, 'typical_joint_profile')]} |"
        )
    lines.extend(
        [
            "",
            "93个区域—日的碳强度与电价档位相关系数均为负，因此不存在可诚实",
            "标为“双赢”的日期。表中前两列改为冲突最弱和冲突最强；它们只描述",
            "外生相关方向，不保证路线优化一定改善。“最大灵活性”按一天内最高",
            "八槽与最低八槽的均值差选择。",
            "",
        ]
    )
    (OUTPUT / "report.md").write_text("\n".join(lines), encoding="utf-8")

    artifacts = {}
    for path in sorted(OUTPUT.iterdir()):
        if path.is_file() and path.name != "artifact_hashes.json":
            artifacts[path.name] = sha256(path)
    write_json(
        OUTPUT / "artifact_hashes.json",
        {"hash_algorithm": "SHA-256", "artifacts": artifacts},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
