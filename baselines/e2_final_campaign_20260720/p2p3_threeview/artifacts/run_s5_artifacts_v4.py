#!/usr/bin/env python3
"""S5-REV-V4: deterministic presentation rebuild over sealed E2 evidence.

This script does not run a solver. It preserves every v3 artifact and the v3
hash manifest, reads the sealed P1--S4 ledgers plus the approved S3 trajectory
materialization, and writes suffixed v4 tables and figures.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import run_s5_artifacts_v3 as v3  # noqa: E402


ROOT = v3.ROOT
OUT = v3.OUT
V2 = v3.v2
P1 = V2.P1
P1_DECISION = V2.P1_DECISION
S2 = V2.S2
S3 = V2.S3
S4 = V2.S4
S4_ROUTE_DETAILS_V2 = V2.S4_ROUTE_DETAILS_V2
S2_DECISION_V2 = V2.S2_DECISION_V2
S3_TRAJ = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/s3_traj_v4"
CARBON_DIR = ROOT / "baselines/e4_e5/china_2025_formal_month_selection_20260718"
CARBON_SOURCE = CARBON_DIR / "tvci_2025_february_48slot_wide.csv"
CARBON_SELECTED_DAYS = CARBON_DIR / "selected_explanatory_days.csv"
CARBON_DECISION = CARBON_DIR / "decision.json"
CARBON_METADATA = CARBON_DIR / "metadata.json"
CARBON_MANIFEST = CARBON_DIR / "artifact_hashes.json"
VISUAL_CONTRACT = V2.VISUAL_CONTRACT
PAPER_ARMS = V2.PAPER_ARMS
ENGINE_ORDER = (
    ("cv_only", "HGS-F", "#1F77B4", "-"),
    ("naive_ev", "HGS-E", "#D55E00", "--"),
    ("mechanism_ev", "HGS-M", "#2CA02C", ":"),
    ("MV-HGS-SP", "MV-HGS-SP", "#9467BD", "-."),
)
TABLE5_ERROR_FIELDS = tuple(v3.TABLE5_ERROR_FIELDS)
APPLEDOUBLE_FLAG = V2.APPLEDOUBLE_FLAG
EPS = 1.0e-12


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _require_pass(path: Path, expected: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("decision") != expected:
        raise RuntimeError(
            f"{path} decision is {payload.get('decision')!r}, expected {expected}"
        )
    return payload


def _near(left: float, right: float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=1.0e-12, abs_tol=1.0e-9)


def _tex_number(value: float, places: int, bold: bool = False) -> str:
    rendered = f"{float(value):.{places}f}"
    return rf"\textbf{{{rendered}}}" if bold else rendered


def _preserve_v3_manifest() -> Path:
    current = OUT / "artifact_hashes.json"
    archive = OUT / "artifact_hashes_v3.json"
    if not current.is_file():
        raise RuntimeError("canonical v3 artifact_hashes.json is missing")
    if not archive.exists():
        shutil.copyfile(current, archive)
    if _sha256(archive) != _sha256(current):
        raise RuntimeError("artifact_hashes_v3.json does not preserve artifact_hashes.json")
    return archive


def _clean_output_appledouble() -> int:
    sidecars = [path for path in OUT.rglob("._*") if path.is_file()]
    for path in sidecars:
        path.unlink()
    return len(sidecars)


def _table5_v4() -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
    dict[str, Any],
]:
    source_rows, _, audit = v3._build_table5_v3()
    fields = ["instances", "n", "BKS", *TABLE5_ERROR_FIELDS]
    output_rows: list[dict[str, Any]] = []
    for source in source_rows:
        row: dict[str, Any] = {
            "instances": source["instance"],
            "n": source["n"],
            "BKS": (
                ""
                if source["BKS"] in ("", None)
                else f"{float(source['BKS']):.3f}"
            ),
        }
        for field in TABLE5_ERROR_FIELDS:
            row[field] = f"{float(source[field]):.2f}"
        output_rows.append(row)
    return source_rows, output_rows, fields, audit


def _tex_table5_v4(source_rows: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{tabular}{@{}lllrrrrrrr@{}}",
        r"\toprule",
        r"instances & $n$ & BKS & VCGP & MDFIHA & MDFIHA-ETGA & \multicolumn{2}{c}{PyVRP-HGS} & \multicolumn{2}{c}{MV-HGS-SP}\\",
        r" &  &  & Best. & Best. & Best. & Best. & avg. & Best. & avg.\\",
        r"\midrule",
    ]
    for source in source_rows:
        values = [float(source[field]) for field in TABLE5_ERROR_FIELDS]
        minimum = min(values)
        metric_cells = [
            _tex_number(value, 2, bold=_near(value, minimum))
            for value in values
        ]
        if source["instance"] == "Avg":
            prefix = ["Avg", "--", "--"]
        else:
            prefix = [
                str(source["instance"]),
                str(int(source["n"])),
                f"{float(source['BKS']):.3f}",
            ]
        lines.append(" & ".join([*prefix, *metric_cells]) + r" \\")
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"% All algorithm entries are BKS-relative errors in percent; the minimum error in each row is bold.",
    ])
    return "\n".join(lines) + "\n"


def _table6_v4(
    s3_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    source_rows, _ = V2._table6_v2(s3_rows)
    fields = ["seed"]
    for arm in PAPER_ARMS:
        fields.extend([f"{arm}_cost", f"{arm}_cpu_minutes", f"{arm}_status"])
    output_rows: list[dict[str, Any]] = []
    for source in source_rows:
        row: dict[str, Any] = {"seed": source["seed"]}
        for arm in PAPER_ARMS:
            cost = float(source[f"{arm}_cost"])
            cpu_seconds = float(source[f"{arm}_cpu_seconds"])
            row[f"{arm}_cost"] = f"{cost:.3f}"
            row[f"{arm}_cpu_minutes"] = f"{cpu_seconds / 60.0:.2f}"
            row[f"{arm}_status"] = source[f"{arm}_status"]
        output_rows.append(row)
    return source_rows, output_rows, fields


def _tex_table6_v4(source_rows: list[dict[str, Any]]) -> str:
    cost_min = {
        arm: min(float(row[f"{arm}_cost"]) for row in source_rows)
        for arm in PAPER_ARMS
    }
    cpu_min = {
        arm: min(float(row[f"{arm}_cpu_seconds"]) / 60.0 for row in source_rows)
        for arm in PAPER_ARMS
    }
    lines = [
        r"\begin{tabular}{@{}lrrrrrrrr@{}}",
        r"\toprule",
        r"种子/统计量 & \multicolumn{2}{c}{HGS-F} & \multicolumn{2}{c}{HGS-E} & \multicolumn{2}{c}{HGS-M} & \multicolumn{2}{c}{MV-HGS-SP}\\",
        r" & 值 & CPU & 值 & CPU & 值 & CPU & 值 & CPU\\",
        r"\midrule",
    ]
    for source in source_rows:
        cells = [str(source["seed"])]
        for arm in PAPER_ARMS:
            cost = float(source[f"{arm}_cost"])
            cpu_minutes = float(source[f"{arm}_cpu_seconds"]) / 60.0
            cells.extend([
                _tex_number(cost, 3, bold=_near(cost, cost_min[arm])),
                _tex_number(cpu_minutes, 2, bold=_near(cpu_minutes, cpu_min[arm])),
            ])
        lines.append(" & ".join(cells) + r" \\")
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"% 值为成本（元），CPU单位为min；各算法的值列和CPU列分别按列加粗最小值。",
    ])
    return "\n".join(lines) + "\n"


def _route_to_bracket(path_text: str) -> str:
    if path_text in {"均值", "合计"}:
        return path_text
    tokens = path_text.split(">")
    converted: list[str] = []
    for token in tokens:
        if token == "D_guangzhou":
            converted.append("51")
        elif token == "D_shenzhen":
            converted.append("52")
        elif token.startswith("C") and token[1:].isdigit():
            customer = int(token[1:])
            if not 1 <= customer <= 50:
                raise RuntimeError(f"customer token outside C001--C050: {token}")
            converted.append(str(customer))
        else:
            raise RuntimeError(f"unexpected route token: {token}")
    if len(converted) < 2 or converted[0] != converted[-1]:
        raise RuntimeError(f"route does not return to its depot: {path_text}")
    return "[" + ", ".join(converted) + "]"


def _table4_v4() -> tuple[list[dict[str, str]], list[str], dict[str, Any]]:
    source_path = OUT / "table4_route_details_v3.csv"
    if not source_path.is_file():
        raise RuntimeError("table4_route_details_v3.csv is missing")
    source_rows = _read_csv(source_path)
    if sum(row["路径"] == "均值" for row in source_rows) != 1:
        raise RuntimeError("table4 source must contain one 均值 row")
    if sum(row["路径"] == "合计" for row in source_rows) != 1:
        raise RuntimeError("table4 source must contain one 合计 row")

    rows: list[dict[str, str]] = []
    customers: list[int] = []
    changes: list[dict[str, str]] = []
    num_field = "num" if "num" in source_rows[0] else "num(满足时窗客户数)"
    for source in source_rows:
        row = dict(source)
        if source["路径"] not in {"均值", "合计"}:
            row["路径"] = _route_to_bracket(source["路径"])
            tokens = row["路径"].strip("[]").split(", ")
            customers.extend(int(token) for token in tokens[1:-1] if int(token) <= 50)
            changes.append({"row": source["vehicle_id"], "field": "路径"})
        if source["路径"] == "均值":
            row[num_field] = "-"
            changes.append({"row": "均值", "field": "num"})
        if source["路径"] == "合计":
            row["装载率(%)"] = "-"
            changes.append({"row": "合计", "field": "装载率(%)"})
        rows.append(row)

    expected = list(range(1, 51))
    if sorted(customers) != expected:
        raise RuntimeError(
            f"route customer coverage after index conversion is not 1--50: {customers}"
        )
    fields = list(source_rows[0].keys())
    if num_field not in fields or "装载率(%)" not in fields:
        raise RuntimeError("table4 source does not contain the expected num/load fields")
    return rows, fields, {
        "source": str(source_path.relative_to(ROOT)),
        "route_count": len(source_rows) - 2,
        "customer_coverage": "1--50 exactly once",
        "mean_num": "-",
        "num_field": num_field,
        "total_load_rate": "-",
        "changed_fields": changes,
        "source_total_load_rate": next(
            row["装载率(%)"] for row in source_rows if row["路径"] == "合计"
        ),
    }


def _tex_table4_v4(rows: list[dict[str, str]]) -> str:
    numeric_fields = [
        "距离(km)", "成本(元)", "时间(h)", "油耗(L)",
        "电耗(kWh)", "碳排放(kg)",
    ]
    lines = [
        r"\begin{tabular}{@{}lrrrrrrrr@{}}",
        r"\toprule",
        r"路径 & 距离/km & 成本/元 & 时间/h & 油耗/L & 电耗/kWh & 碳排放/kg & num & 装载率/\%\\",
        r"\midrule",
    ]
    num_field = "num" if "num" in rows[0] else "num(满足时窗客户数)"
    for row in rows:
        cells = [row["路径"]]
        cells.extend(f"{float(row[field]):.3f}" for field in numeric_fields)
        cells.append("-" if row[num_field] == "-" else f"{float(row[num_field]):.0f}")
        cells.append(
            "-" if row["装载率(%)"] == "-"
            else f"{float(row['装载率(%)']):.2f}"
        )
        lines.append(" & ".join(cells) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(lines) + "\n"


def _summary_v4() -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    _, values, context = V2._load_s2_records()
    instance_stats = V2._instance_statistics(context["tiers"], values)
    rows, fields = V2._summary_rows(instance_stats)
    return rows, fields, {
        "source": "S2 full_gate raw_runs.csv",
        "rows": len(rows),
        "registered_exception_id": V2.S2_EXCEPTION_ID,
    }


def _tex_summary_v4(rows: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{tabular}{@{}llrrrrrrrr@{}}",
        r"\toprule",
        r"城市群 & 规模层 & \multicolumn{2}{c}{HGS-F} & \multicolumn{2}{c}{HGS-E} & \multicolumn{2}{c}{HGS-M} & \multicolumn{2}{c}{MV-HGS-SP}\\",
        r" &  & Best. & avg. & Best. & avg. & Best. & avg. & Best. & avg.\\",
        r"\midrule",
    ]
    for row in rows:
        bests = [float(row[f"{arm}_Best"]) for arm in PAPER_ARMS]
        avgs = [float(row[f"{arm}_avg"]) for arm in PAPER_ARMS]
        best_min = min(bests)
        avg_min = min(avgs)
        cells = [str(row["city_group"]), str(row["tiers"])]
        for best, avg in zip(bests, avgs, strict=True):
            cells.extend([
                _tex_number(best, 2, bold=_near(best, best_min)),
                _tex_number(avg, 2, bold=_near(avg, avg_min)),
            ])
        lines.append(" & ".join(cells) + r" \\")
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"% Best. and avg. minima are bolded independently by row; values are costs in yuan.",
    ])
    return "\n".join(lines) + "\n"


def _font_setup() -> None:
    plt.rcParams.update({
        "font.family": ["Times New Roman", "Songti SC"],
        "font.size": 8.0,
        "axes.labelsize": 8.0,
        "xtick.labelsize": 7.2,
        "ytick.labelsize": 7.2,
        "legend.fontsize": 7.0,
        "axes.unicode_minus": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def _figure3_v4() -> dict[str, Any]:
    selected_rows = _read_csv(CARBON_SELECTED_DAYS)
    selected = {
        row["region"]: row["date"]
        for row in selected_rows
        if row["case_role"] == "typical_joint_profile"
    }
    expected = {
        "Beijing": "2025-02-20",
        "Guangdong": "2025-02-16",
        "Chongqing": "2025-02-24",
    }
    if selected != expected:
        raise RuntimeError(f"unexpected registered typical days: {selected}")

    source_rows = _read_csv(CARBON_SOURCE)
    output_rows: list[dict[str, Any]] = []
    styles = [
        ("Beijing", "#1F77B4", "-"),
        ("Guangdong", "#D55E00", "--"),
        ("Chongqing", "#2CA02C", ":"),
    ]
    _font_setup()
    fig, ax = plt.subplots(figsize=(4.30, 2.80))
    for region, color, linestyle in styles:
        date = selected[region]
        matches = [row for row in source_rows if row["date"] == date]
        if len(matches) != 48:
            raise RuntimeError(f"{region}/{date} has {len(matches)} half-hour rows, expected 48")
        times: list[float] = []
        values: list[float] = []
        for item in matches:
            time_hour = float(item["hour_of_day"]) + float(item["minute"]) / 60.0
            value = float(item[region]) * 1000.0
            times.append(time_hour)
            values.append(value)
            output_rows.append({
                "region": region,
                "date": date,
                "half_hour_slot": item["half_hour_slot"],
                "time_hour": f"{time_hour:.2f}",
                "raw_source_value": item[region],
                "carbon_intensity_gCO2_per_kWh": f"{value:.6f}",
            })
        ax.plot(
            times, values, color=color, linestyle=linestyle,
            linewidth=0.62, label=region,
        )
    ax.set_xlim(0.0, 24.0)
    ax.set_xticks([0, 4, 8, 12, 16, 20, 24])
    ax.set_xlabel("Time of day (h)")
    ax.set_ylabel("Carbon intensity (gCO$_2$/kWh)")
    ax.grid(False)
    ax.legend(
        loc="upper right", frameon=True, fancybox=False,
        edgecolor="#777777", framealpha=1.0, borderpad=0.2,
        handlelength=1.7,
    )
    ax.tick_params(direction="out", length=2.0, width=0.468)
    for spine in ax.spines.values():
        spine.set_linewidth(0.468)
    fig.subplots_adjust(left=0.15, right=0.985, bottom=0.18, top=0.975)
    fig.savefig(OUT / "figure3_carbon_profile_v4.pdf", bbox_inches="tight")
    fig.savefig(OUT / "figure3_carbon_profile_v4.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    fields = [
        "region", "date", "half_hour_slot", "time_hour",
        "raw_source_value", "carbon_intensity_gCO2_per_kWh",
    ]
    _write_csv(OUT / "figure3_carbon_profile_v4.csv", output_rows, fields)
    return {
        "source": str(CARBON_SOURCE.relative_to(ROOT)),
        "registered_days": selected,
        "rows": len(output_rows),
        "rows_per_region": {region: 48 for region, _, _ in styles},
        "unit_conversion": "raw CSV values multiplied by 1000 to report gCO2/kWh",
    }


def _figure4_v4(curve_decision: dict[str, Any]) -> dict[str, Any]:
    curve_rows = _read_csv(S3_TRAJ / "curve_data_v4.csv")
    selected_seeds = {
        str(arm): int(seed)
        for arm, seed in curve_decision["selected_seeds"].items()
    }
    selected_rows: dict[str, list[dict[str, str]]] = {}
    for engine, label, _, _ in ENGINE_ORDER:
        rows = [
            row for row in curve_rows
            if row["algorithm"] == engine
            and int(row["seed"]) == selected_seeds[engine]
            and row["selected_for_figure4"].lower() == "true"
        ]
        if not rows:
            raise RuntimeError(f"missing selected Figure 4 curve for {engine}")
        rows.sort(key=lambda row: (float(row["elapsed_seconds"]), int(row["snapshot_order"])))
        times = [float(row["elapsed_seconds"]) for row in rows]
        costs = [float(row["cost_cny"]) for row in rows]
        if any(times[i] < times[i - 1] - EPS for i in range(1, len(times))):
            raise RuntimeError(f"Figure 4 time is not monotone for {engine}")
        if any(costs[i] > costs[i - 1] + EPS for i in range(1, len(costs))):
            raise RuntimeError(f"Figure 4 curve is not best-so-far for {engine}")
        materialized = S3_TRAJ / "materialized_trajectories_v2" / (
            f"{engine}_seed{selected_seeds[engine]}.json"
        )
        payload = json.loads(materialized.read_text(encoding="utf-8"))
        for row in rows:
            row["sealed_final_cost"] = f"{float(payload['sealed_final_cost']):.15f}"
            row["curve_best_below_final"] = str(bool(payload["curve_best_below_final"]))
            row["algorithm_label"] = label
        selected_rows[engine] = rows

    _font_setup()
    fig, ax = plt.subplots(figsize=(4.30, 2.80))
    all_times: list[float] = []
    all_costs: list[float] = []
    for engine, label, color, linestyle in ENGINE_ORDER:
        rows = selected_rows[engine]
        times = [float(row["elapsed_minutes"]) for row in rows]
        costs = [float(row["cost_cny"]) for row in rows]
        all_times.extend(times)
        all_costs.extend(costs)
        ax.plot(
            times, costs, color=color, linestyle=linestyle,
            linewidth=0.62, label=label,
        )
    if not all_times or not all_costs:
        raise RuntimeError("Figure 4 has no finite selected curve values")
    x_max = max(all_times)
    y_min = min(all_costs)
    y_max = max(all_costs)
    y_margin = max((y_max - y_min) * 0.05, 1.0)
    ax.set_xlim(0.0, max(x_max * 1.02, 0.1))
    ax.set_ylim(y_min - y_margin, y_max + y_margin)
    ax.set_xlabel("Time (min)")
    ax.set_ylabel("Cost (CNY)")
    ax.grid(False)
    ax.legend(
        loc="upper right", frameon=True, fancybox=False,
        edgecolor="#777777", framealpha=1.0, borderpad=0.2,
        handlelength=1.7,
    )
    ax.tick_params(direction="out", length=2.0, width=0.468)
    for spine in ax.spines.values():
        spine.set_linewidth(0.468)
    fig.subplots_adjust(left=0.14, right=0.985, bottom=0.18, top=0.975)
    fig.savefig(OUT / "figure4_convergence_v4.pdf", bbox_inches="tight")
    fig.savefig(OUT / "figure4_convergence_v4.png", dpi=300, bbox_inches="tight")
    plt.close(fig)

    fields = [
        "algorithm", "algorithm_label", "seed", "selected_for_figure4",
        "elapsed_seconds", "elapsed_minutes", "cost_cny", "source",
        "snapshot_order", "sealed_final_cost", "curve_best_below_final",
    ]
    output_rows = [
        {field: row[field] for field in fields}
        for engine in selected_rows
        for row in selected_rows[engine]
    ]
    _write_csv(OUT / "figure4_convergence_v4.csv", output_rows, fields)
    return {
        "source": str((S3_TRAJ / "curve_data_v4.csv").relative_to(ROOT)),
        "selected_seeds": selected_seeds,
        "curve_rows": len(output_rows),
        "definition": curve_decision["curve_definition"],
        "lower_historical_observation": {
            "arm": "mechanism_ev",
            "seed": 10,
            "cost": 2364.589958517462,
            "sealed_table_cost": 2365.8780971446868,
        },
    }


def _hash_paths(
    v3_manifest: Path,
    task_card: Path,
    monitor: Path,
    script: Path,
    decision: Path,
    metadata: Path,
    report: Path,
) -> list[Path]:
    output_names = [
        "table4_route_details_v4.csv",
        "table4_route_details_v4.tex",
        "table5_public_v4.csv",
        "table5_public_v4.tex",
        "table6_representative_v4.csv",
        "table6_representative_v4.tex",
        "china81_summary_v4.csv",
        "china81_summary_v4.tex",
        "china81_pairwise_tests_v4.csv",
        "figure3_carbon_profile_v4.csv",
        "figure3_carbon_profile_v4.pdf",
        "figure3_carbon_profile_v4.png",
        "figure4_convergence_v4.csv",
        "figure4_convergence_v4.pdf",
        "figure4_convergence_v4.png",
    ]
    inputs = [
        OUT / "decision_v3.json",
        OUT / "metadata_v3.json",
        OUT / "report_v3.md",
        OUT / "run_s5_artifacts_v3.py",
        V2.S1 / "decision.json",
        S2_DECISION_V2,
        S2 / "raw_runs.csv",
        S3 / "decision.json",
        S3 / "raw_runs.csv",
        V2.S4_DECISION_V2,
        S4_ROUTE_DETAILS_V2,
        P1 / "raw_runs.csv",
        P1_DECISION,
        VISUAL_CONTRACT,
        S3_TRAJ / "decision.json",
        S3_TRAJ / "decision_v2.json",
        S3_TRAJ / "metadata_v2.json",
        S3_TRAJ / "offline_recheck_v2.json",
        S3_TRAJ / "curve_data_v4.csv",
        S3_TRAJ / "artifact_hashes_v2.json",
        CARBON_SOURCE,
        CARBON_SELECTED_DAYS,
        CARBON_DECISION,
        CARBON_METADATA,
        CARBON_MANIFEST,
    ]
    candidates = [v3_manifest, task_card, monitor, script, decision, metadata, report]
    candidates.extend(OUT / name for name in output_names)
    candidates.extend(inputs)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return [
        path for path in unique
        if path.is_file()
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    ]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    decision_path = OUT / "decision_v4.json"
    metadata_path = OUT / "metadata_v4.json"
    report_path = OUT / "report_v4.md"
    done_path = OUT / "done_v4.json"
    task_card = OUT / "task_card_v4.md"
    monitor = OUT / "monitor_v5.json"
    script_path = Path(__file__).resolve()
    try:
        v3_manifest = _preserve_v3_manifest()
        V2._require_pass(OUT / "decision_v3.json", "PASS_S5_ARTIFACTS")
        V2._require_pass(V2.S1 / "decision.json", "PASS_S1_THREEVIEW_PREFLIGHT")
        V2._require_pass(S3 / "decision.json", "PASS_S3_REPRESENTATIVE")
        V2._require_pass(V2.S4_DECISION_V2, "PASS_S4_ROUTE_DETAIL")
        V2._require_pass(P1_DECISION, "P1_FORMAL_PUBLIC_COMPLETE")
        s2_decision = json.loads(S2_DECISION_V2.read_text(encoding="utf-8"))
        if s2_decision.get("decision") != "PASS_S2_FULL_THREEVIEW_WITH_REGISTERED_INFEASIBLE_UNIT":
            raise RuntimeError(f"unexpected S2 v2 decision: {s2_decision.get('decision')!r}")
        curve_decision = _require_pass(
            S3_TRAJ / "decision_v2.json",
            "PASS_S3_TRAJ_CURVE_UNDER_REGISTERED_DEFINITION",
        )
        if curve_decision.get("final_cost_exact_matches") != 40:
            raise RuntimeError("S3 trajectory v2 does not attest 40/40 exact final costs")

        s3_rows = V2._read_csv(S3 / "raw_runs.csv")
        if len(s3_rows) != 40:
            raise RuntimeError(f"sealed S3 raw has {len(s3_rows)} rows, expected 40")
        table5_source, table5, table5_fields, table5_audit = _table5_v4()
        table6_source, table6, table6_fields = _table6_v4(s3_rows)
        table4, table4_fields, table4_audit = _table4_v4()
        summary, summary_fields, summary_audit = _summary_v4()
        pairwise_source = OUT / "china81_pairwise_tests_v3.csv"
        if not pairwise_source.is_file():
            raise RuntimeError("china81_pairwise_tests_v3.csv is missing")
        shutil.copyfile(pairwise_source, OUT / "china81_pairwise_tests_v4.csv")

        V2._write_csv(OUT / "table5_public_v4.csv", table5, table5_fields)
        V2._write_csv(OUT / "table6_representative_v4.csv", table6, table6_fields)
        V2._write_csv(OUT / "table4_route_details_v4.csv", table4, table4_fields)
        V2._write_csv(OUT / "china81_summary_v4.csv", summary, summary_fields)
        (OUT / "table5_public_v4.tex").write_text(
            _tex_table5_v4(table5_source), encoding="utf-8"
        )
        (OUT / "table6_representative_v4.tex").write_text(
            _tex_table6_v4(table6_source), encoding="utf-8"
        )
        (OUT / "table4_route_details_v4.tex").write_text(
            _tex_table4_v4(table4), encoding="utf-8"
        )
        (OUT / "china81_summary_v4.tex").write_text(
            _tex_summary_v4(summary), encoding="utf-8"
        )
        figure3_audit = _figure3_v4()
        figure4_audit = _figure4_v4(curve_decision)

        removed = _clean_output_appledouble()
        flags = [APPLEDOUBLE_FLAG] if removed else []
        decision = {
            "schema_version": "resetp.e2-final-campaign.s5-artifacts.v4",
            "decision": "PASS_S5_ARTIFACTS_V4",
            "revision": "S5-REV-V4",
            "curve_approval_register_id": "S3-TRAJ-CURVE-DEF-001",
            "source_decision_v3": "decision_v3.json",
            "source_s3_trajectory_decision": "representative_gate/s3_traj_v4/decision_v2.json",
            "v3_outputs_preserved": True,
            "data_values_changed": False,
            "presentation_only": True,
            "observation_layer_only": True,
            "table5_rows": len(table5),
            "table6_rows": len(table6),
            "table4_rows": len(table4),
            "china81_summary_rows": len(summary),
            "figure3_rows": figure3_audit["rows"],
            "figure4_rows": figure4_audit["curve_rows"],
            "table5_audit": table5_audit,
            "table4_audit": table4_audit,
            "summary_audit": summary_audit,
            "figure3_audit": figure3_audit,
            "figure4_audit": figure4_audit,
            "s3_final_cost_exact_matches": 40,
            "s3_complete_solution_violations": 0,
            "s3_table_costs_unchanged": True,
            "s2_registered_exception_id": V2.S2_EXCEPTION_ID,
            "claim_boundary": "S5 v4 is presentation and registered observation materialization only; it authorizes no new superiority, equal-compute, or algorithm claim.",
            "integrity_flags": flags,
        }
        _write_json(decision_path, decision)
        metadata = {
            "schema_version": "resetp.e2-final-campaign.s5-artifacts-metadata.v4",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "command": " ".join([sys.executable, *sys.argv]),
            "git_head": V2._git_head(),
            "branch": "codex/reporting-pipeline",
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "source_sha256": {
                "v3_manifest": _sha256(v3_manifest),
                "v3_decision": _sha256(OUT / "decision_v3.json"),
                "s2_raw": _sha256(S2 / "raw_runs.csv"),
                "s3_raw": _sha256(S3 / "raw_runs.csv"),
                "s4_route_details_v2": _sha256(S4_ROUTE_DETAILS_V2),
                "p1_raw": _sha256(P1 / "raw_runs.csv"),
                "p1_decision": _sha256(P1_DECISION),
                "s3_curve_v2_decision": _sha256(S3_TRAJ / "decision_v2.json"),
                "s3_curve_data": _sha256(S3_TRAJ / "curve_data_v4.csv"),
                "carbon_source": _sha256(CARBON_SOURCE),
                "visual_contract": _sha256(VISUAL_CONTRACT),
            },
            "table5_display": "BKS-relative errors formatted to two decimal places; row-wise minimum bold.",
            "table6_display": "sealed final costs in yuan; CPU converted from seconds to minutes; cost and CPU minima bold independently by column.",
            "table4_display": "customer/depot paths converted to bracketed indices; mean num and total load rate are dashes.",
            "figure3_display": figure3_audit,
            "figure4_display": figure4_audit,
            "s2_registered_exception_id": V2.S2_EXCEPTION_ID,
            "integrity_flags": flags,
        }
        _write_json(metadata_path, metadata)
        report = (
            "# S5-REV-V4 unified artifacts\n\n"
            "Decision: PASS_S5_ARTIFACTS_V4.\n\n"
            "This is a deterministic presentation and registered-observation "
            "rebuild. It does not run a solver and does not modify any sealed "
            "raw ledger, witness, evaluator, cost model, statistical input, or "
            "main TeX. All v3 files and the v3 hash manifest are preserved.\n\n"
            "## Table repairs\n\n"
            "Table 5 uses the requested instances header, two-line Best./avg. "
            "headers, BKS-relative error percentages formatted to two decimals, "
            "and row-wise minimum-error bolding. Its source values remain the "
            "P1 decision and raw ledger values.\n\n"
            "Table 6 keeps the sealed S3 returned costs, converts CPU from "
            "seconds to minutes, uses the second header row 值 and CPU, and "
            "bolds the minimum value and minimum CPU independently within each "
            "algorithm column across the ten seeds and Min/Avg/Max rows.\n\n"
            "The route table converts C001--C050 to 1--50, Guangzhou to 51, "
            "and Shenzhen to 52 in bracketed paths. The route audit covers each "
            "customer exactly once. The mean num and total load-rate cells are "
            "dashes; all other source values are retained.\n\n"
            "The China81 summary retains the registered S2 exception "
            f"{V2.S2_EXCEPTION_ID} and independently bolds Best. and avg. "
            "row minima. Its CSV retains source precision; the TeX display is "
            "formatted to two decimals.\n\n"
            "## Figures\n\n"
            "Figure 3 is generated from the sealed February 2025 48-slot CSV "
            "for the three registered typical profiles: Beijing 2025-02-20, "
            "Guangdong 2025-02-16, and Chongqing 2025-02-24. The source values "
            "are converted to gCO2/kWh by multiplying by 1000.\n\n"
            "Figure 4 uses the approved S3-TRAJ-CURVE-DEF-001 definition: "
            "historical snapshot skeletons are completed and scored offline "
            "with the full model, and the plotted quantity is the monotone "
            "best-so-far. It uses the pre-registered average-nearest seeds "
            f"{figure4_audit['selected_seeds']}. The 40/40 sealed final costs "
            "match exactly and the table costs are unchanged. The trajectory "
            "data retains the registered HGS-M/seed10 observation "
            "2364.589958517462 versus its sealed table cost 2365.8780971446868; "
            "that historical value is trajectory-only and is never substituted "
            "into Table 6/Table 8 or any summary.\n\n"
            "The S2 HGS-E infeasible unit remains disclosed under the registered "
            "statistical rule; no failed unit was rerun or resampled. This "
            "revision therefore changes presentation and the explicitly "
            "approved observation definition only.\n"
        )
        report_path.write_text(report, encoding="utf-8")

        removed_after = _clean_output_appledouble()
        if removed_after:
            flags = list(dict.fromkeys([*flags, APPLEDOUBLE_FLAG]))
            decision["integrity_flags"] = flags
            metadata["integrity_flags"] = flags
            _write_json(decision_path, decision)
            _write_json(metadata_path, metadata)
            report_path.write_text(
                report_path.read_text(encoding="utf-8")
                + f"\nIntegrity flag: {APPLEDOUBLE_FLAG}; AppleDouble sidecars were removed before hash refresh.\n",
                encoding="utf-8",
            )

        paths = _hash_paths(
            v3_manifest, task_card, monitor, script_path,
            decision_path, metadata_path, report_path,
        )
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise RuntimeError(f"missing v4 hash inputs: {missing}")
        _write_json(OUT / "artifact_hashes_v4.json", {
            "schema_version": "resetp.artifact-hashes.s5-v4",
            "algorithm": "sha256",
            "source_manifest_v3": "artifact_hashes_v3.json",
            "approval_register_id": "S3-TRAJ-CURVE-DEF-001",
            "appledouble_excluded": True,
            "integrity_flags": flags,
            "files": {
                str(path.relative_to(ROOT)): _sha256(path)
                for path in paths
                if not path.name.startswith("._")
            },
        })
        _write_json(done_path, {
            "decision": "PASS_S5_ARTIFACTS_V4",
            "revision": "S5-REV-V4",
            "artifact_hashes": "artifact_hashes_v4.json",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        _write_json(decision_path, {
            "schema_version": "resetp.e2-final-campaign.s5-artifacts.v4",
            "decision": "HALT_S5_V4_INPUT_OR_RENDER_GATE",
            "revision": "S5-REV-V4",
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
        print(f"[S5 v4] HALT_S5_V4_INPUT_OR_RENDER_GATE: {exc}", file=sys.stderr, flush=True)
        return 2
    print("[S5 v4] PASS_S5_ARTIFACTS_V4", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
