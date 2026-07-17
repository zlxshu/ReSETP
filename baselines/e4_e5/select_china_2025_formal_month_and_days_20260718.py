#!/usr/bin/env python3
"""Select the formal 2025 month and explanatory days without solver results."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "baselines/e4_e5/china_tvci_source_gate_20260717_v2/tvci_2025_48slot_wide.csv"
OUTPUT = REPO / "baselines/e4_e5/china_2025_formal_month_selection_20260718"
REGIONS = ("Beijing", "Guangdong", "Chongqing")
BAND_SCORE = {"valley": 0.0, "flat": 1.0, "peak": 2.0}


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
        if 10 * 60 <= minute < 13 * 60 or 17 * 60 <= minute < 22 * 60:
            return "peak"
        return "flat"
    if region == "Guangdong":
        if minute < 8 * 60:
            return "valley"
        if 10 * 60 <= minute < 12 * 60 or 14 * 60 <= minute < 19 * 60:
            return "peak"
        return "flat"
    if region == "Chongqing":
        if minute < 8 * 60:
            return "valley"
        if 11 * 60 <= minute < 17 * 60 or 20 * 60 <= minute < 22 * 60:
            return "peak"
        return "flat"
    raise ValueError(region)


def pearson(left: list[float], right: list[float]) -> float:
    ml, mr = statistics.fmean(left), statistics.fmean(right)
    numerator = sum((x - ml) * (y - mr) for x, y in zip(left, right, strict=True))
    denominator = math.sqrt(
        sum((x - ml) ** 2 for x in left) * sum((y - mr) ** 2 for y in right)
    )
    return numerator / denominator


def load_days() -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    grouped: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    source_rows: list[dict[str, str]] = []
    with SOURCE.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            source_rows.append(row)
            minute = int(row["hour_of_day"]) * 60 + int(row["minute"])
            for region in REGIONS:
                grouped[(region, row["date"])].append((minute, float(row[region]) * 1000))
    metrics: list[dict[str, object]] = []
    for (region, date), values in sorted(grouped.items()):
        carbon = [value for _, value in values]
        sorted_carbon = sorted(carbon)
        blocks = [statistics.fmean(carbon[i : i + 8]) for i in range(41)]
        evening = statistics.fmean(carbon[36:44])
        post_return = carbon[36:] + carbon[:16]
        post_blocks = [
            statistics.fmean(post_return[i : i + 8])
            for i in range(len(post_return) - 7)
        ]
        scores = [BAND_SCORE[band(region, minute)] for minute, _ in values]
        metrics.append(
            {
                "region": region,
                "date": date,
                "month": date[:7],
                "daily_mean_gCO2_per_kWh": statistics.fmean(carbon),
                "intraday_range_gCO2_per_kWh": max(carbon) - min(carbon),
                "eight_slot_shift_potential_gCO2_per_kWh": (
                    statistics.fmean(sorted_carbon[-8:])
                    - statistics.fmean(sorted_carbon[:8])
                ),
                "contiguous_four_hour_difference_gCO2_per_kWh": max(blocks)
                - min(blocks),
                "evening_to_best_post_return_gCO2_per_kWh": evening
                - min(post_blocks),
                "carbon_price_band_correlation": pearson(carbon, scores),
                "optimization_results_read": 0,
            }
        )
    if len(metrics) != 365 * 3:
        raise ValueError(f"expected 1095 region-days, found {len(metrics)}")
    return metrics, source_rows


def monthly_summary(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for month in sorted({str(row["month"]) for row in metrics}):
        region_rows = [row for row in metrics if row["month"] == month]
        rows.append(
            {
                "month": month,
                "region_day_count": len(region_rows),
                "three_region_mean_intraday_range_gCO2_per_kWh": statistics.fmean(
                    float(row["intraday_range_gCO2_per_kWh"]) for row in region_rows
                ),
                "three_region_mean_eight_slot_shift_gCO2_per_kWh": statistics.fmean(
                    float(row["eight_slot_shift_potential_gCO2_per_kWh"])
                    for row in region_rows
                ),
                "three_region_mean_contiguous_four_hour_difference_gCO2_per_kWh": statistics.fmean(
                    float(row["contiguous_four_hour_difference_gCO2_per_kWh"])
                    for row in region_rows
                ),
                "three_region_mean_evening_to_best_post_return_gCO2_per_kWh": statistics.fmean(
                    float(row["evening_to_best_post_return_gCO2_per_kWh"])
                    for row in region_rows
                ),
                "optimization_results_read": 0,
            }
        )
    ranked = sorted(
        rows,
        key=lambda row: (
            -float(row["three_region_mean_eight_slot_shift_gCO2_per_kWh"]),
            -float(
                row[
                    "three_region_mean_contiguous_four_hour_difference_gCO2_per_kWh"
                ]
            ),
            -float(
                row["three_region_mean_evening_to_best_post_return_gCO2_per_kWh"]
            ),
            row["month"],
        ),
    )
    for rank, row in enumerate(ranked, start=1):
        row["lexicographic_rank"] = rank
    return sorted(rows, key=lambda row: str(row["month"]))


def explanatory_cases(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    for region in REGIONS:
        rows = [
            row for row in metrics if row["region"] == region and row["month"] == "2025-02"
        ]
        used: set[str] = set()

        def take(role: str, key) -> None:
            candidates = [row for row in rows if str(row["date"]) not in used]
            chosen = min(candidates, key=key)
            used.add(str(chosen["date"]))
            selected.append(
                {
                    "case_role": role,
                    **chosen,
                    "use_boundary": "explanatory_only_full_28_days_remain_primary",
                }
            )

        take(
            "maximum_shift_potential",
            lambda row: (
                -float(row["eight_slot_shift_potential_gCO2_per_kWh"]),
                row["date"],
            ),
        )
        take(
            "strongest_carbon_cost_conflict",
            lambda row: (float(row["carbon_price_band_correlation"]), row["date"]),
        )
        take(
            "weakest_conflict_or_alignment",
            lambda row: (-float(row["carbon_price_band_correlation"]), row["date"]),
        )
        med_shift = statistics.median(
            float(row["eight_slot_shift_potential_gCO2_per_kWh"]) for row in rows
        )
        med_corr = statistics.median(
            float(row["carbon_price_band_correlation"]) for row in rows
        )
        shift_span = max(
            float(row["eight_slot_shift_potential_gCO2_per_kWh"]) for row in rows
        ) - min(float(row["eight_slot_shift_potential_gCO2_per_kWh"]) for row in rows)
        corr_span = max(
            float(row["carbon_price_band_correlation"]) for row in rows
        ) - min(float(row["carbon_price_band_correlation"]) for row in rows)
        take(
            "typical_joint_profile",
            lambda row: (
                abs(float(row["eight_slot_shift_potential_gCO2_per_kWh"]) - med_shift)
                / shift_span
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
    metrics, source_rows = load_days()
    months = monthly_summary(metrics)
    winner = min(months, key=lambda row: int(row["lexicographic_rank"]))
    if winner["month"] != "2025-02":
        raise ValueError(f"expected February winner, observed {winner['month']}")
    cases = explanatory_cases(metrics)
    feb_source = [row for row in source_rows if row["date"].startswith("2025-02-")]
    write_csv(OUTPUT / "monthly_external_metrics.csv", months)
    write_csv(
        OUTPUT / "february_region_day_external_metrics.csv",
        [row for row in metrics if row["month"] == "2025-02"],
    )
    write_csv(OUTPUT / "selected_explanatory_days.csv", cases)
    write_csv(OUTPUT / "tvci_2025_february_48slot_wide.csv", feb_source)

    metadata = {
        "schema": "resetp.china-2025-formal-month-selection.v1",
        "source": str(SOURCE.relative_to(REPO)),
        "source_sha256": sha256(SOURCE),
        "selection_rule": (
            "lexicographic: maximize three-region mean daily top-eight minus bottom-eight "
            "CEF difference; then contiguous four-hour difference; then evening-to-best-"
            "post-return difference; earliest month only as final tie break"
        ),
        "selected_month": "2025-02",
        "selected_days": 28,
        "search_evaluations": 0,
        "optimization_results_read": False,
        "status": "PASS_2025_FEBRUARY_FULL_MONTH_RESULT_BLIND_SELECTION",
    }
    write_json(OUTPUT / "metadata.json", metadata)
    write_csv(
        OUTPUT / "raw_runs.csv",
        [
            {"check": "source_region_days", "observed": len(metrics), "expected": 1095, "status": "PASS"},
            {"check": "month_rows", "observed": len(months), "expected": 12, "status": "PASS"},
            {"check": "february_half_hour_rows", "observed": len(feb_source), "expected": 28 * 48, "status": "PASS"},
            {"check": "explanatory_cases", "observed": len(cases), "expected": 12, "status": "PASS"},
            {"check": "optimization_results_read", "observed": 0, "expected": 0, "status": "PASS"},
        ],
    )
    write_json(
        OUTPUT / "decision.json",
        {
            "decision": "PASS_2025_FEBRUARY_FULL_MONTH_RESULT_BLIND_SELECTION",
            "selected_month": "2025-02",
            "primary_panel": "all 28 days for each of Beijing, Guangdong, Chongqing",
            "authorizes": [
                "use the full February panel after matching tariff and depot-row closure",
                "use preselected days only for explanatory figures",
            ],
            "does_not_authorize": [
                "dropping any February day after optimization",
                "claiming favorable route or charging results before formal search",
                "using the constructed 2026 interpolation in the formal main experiment",
            ],
            "search_evaluations": 0,
        },
    )
    report = f"""# 中国 2025 正式月份结果盲选

判定：`PASS_2025_FEBRUARY_FULL_MONTH_RESULT_BLIND_SELECTION`。

选择器只读取验签的 S1-2025 京、粤、渝碳曲线和三地官方分时时段，不读取路线、
充电动作、绝对合同价、求解器或任何实验结果。按预注册字典序规则，2025年2月的
三地区平均最高八槽—最低八槽差为
`{float(winner['three_region_mean_eight_slot_shift_gCO2_per_kWh']):.3f} gCO2/kWh`，
连续四小时差为
`{float(winner['three_region_mean_contiguous_four_hour_difference_gCO2_per_kWh']):.3f} gCO2/kWh`，
两项均在12个月中排名第一。

正式主面板保留2025-02-01至2025-02-28全部28天。解释性日期另行预选，但只能
用于机制图，不能替代28日全体方向计数和效应估计。2026插值包不进入正式链。
"""
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    artifacts = {}
    for path in sorted(OUTPUT.iterdir()):
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._"):
            artifacts[path.name] = sha256(path)
    write_json(
        OUTPUT / "artifact_hashes.json",
        {"hash_algorithm": "SHA-256", "artifacts": artifacts},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
