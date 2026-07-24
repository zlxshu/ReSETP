#!/usr/bin/env python3
"""Build the V7 E2 publication tables and figures from sealed evidence only."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


REPO = Path(__file__).resolve().parents[2]
CAMPAIGN_NAME = os.environ.get(
    "RESET_D6_CAMPAIGN_NAME",
    "corrected_china81_rerun_v7_small_archive_ledger_20260724",
)
EXPECTED_CAMPAIGN = (
    "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
if CAMPAIGN_NAME != EXPECTED_CAMPAIGN:
    raise RuntimeError(f"unsupported S5 campaign: {CAMPAIGN_NAME!r}")
CAMPAIGN = (
    REPO / "baselines/e2_final_campaign_20260720" / CAMPAIGN_NAME
)
FULL = CAMPAIGN / "full_gate"
REPLAY = CAMPAIGN / "full_witness_replay"
STRENGTH = CAMPAIGN / "result_strength_gate"
S3 = CAMPAIGN / "s3_trajectory_gate"
S4 = CAMPAIGN / "table4_gate"
PROTOCOL = CAMPAIGN / "s5_artifact_protocol_preregistration_v1.json"
P1 = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "mv_hgs_sp_final/p1_formal_gate"
)
RUNTIME = (
    REPO
    / "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v4_20260723"
)
OUT = CAMPAIGN / "artifacts"
ARMS = ("HGS-F", "HGS-E", "HGS-M", "MV-HGS-SP")
SINGLE_VIEWS = ARMS[:-1]
REGIONS = ("jjj", "prd", "cy")
REGION_NAMES = {
    "jjj": "京津冀",
    "prd": "珠三角",
    "cy": "成渝",
}
TIERS = (10, 15, 20, 25, 50, 75, 100, 150, 200)
BANDS = {
    "小规模": (10, 15, 20),
    "中规模": (25, 50, 75),
    "大规模": (100, 150, 200),
}
EPS = 1.0e-9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def verify_manifest(root: Path) -> None:
    payload = read_json(root / "artifact_hashes.json")
    artifacts = payload.get("artifacts")
    paths_are_repo_relative = False
    if not isinstance(artifacts, dict) or not artifacts:
        artifacts = payload.get("files")
        paths_are_repo_relative = True
    if not isinstance(artifacts, dict) or not artifacts:
        raise RuntimeError(f"empty artifact manifest: {root}")
    for relative, expected in artifacts.items():
        path = (REPO if paths_are_repo_relative else root) / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"artifact hash drift: {path}")


def require_verdict(
    root: Path,
    expected: str,
    *,
    decision_key: str = "verdict",
) -> dict[str, Any]:
    decision = read_json(root / "decision.json")
    if decision.get(decision_key) != expected:
        raise RuntimeError(
            f"{root}: {decision_key}={decision.get(decision_key)!r}, "
            f"expected {expected!r}"
        )
    verify_manifest(root)
    return decision


def configure_fonts() -> None:
    plt.rcParams.update(
        {
            "font.family": ["Times New Roman", "Songti SC"],
            "font.size": 8.0,
            "axes.labelsize": 8.0,
            "xtick.labelsize": 7.2,
            "ytick.labelsize": 7.2,
            "legend.fontsize": 6.8,
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def near(left: float, right: float, tolerance: float = EPS) -> bool:
    return math.isclose(
        float(left),
        float(right),
        rel_tol=0.0,
        abs_tol=tolerance,
    )


def tex_number(value: float, places: int, bold: bool = False) -> str:
    text = f"{float(value):.{places}f}"
    return rf"\textbf{{{text}}}" if bold else text


def public_benchmark_rows() -> list[dict[str, Any]]:
    decision = read_json(P1 / "decision.json")
    if (
        decision.get("decision") != "P1_FORMAL_PUBLIC_COMPLETE"
        or len(decision.get("table5", [])) != 28
    ):
        raise RuntimeError("sealed public P1 decision is incomplete")
    verify_manifest(P1)
    runs = read_csv(P1 / "raw_runs.csv")
    output: list[dict[str, Any]] = []
    for source in decision["table5"]:
        instance = str(source["instance"])
        matching = [row for row in runs if row["instance_id"] == instance]
        if len(matching) != 10:
            raise RuntimeError(f"{instance}: public P1 seed count is not 10")
        bks = float(source["bks"])
        output.append(
            {
                "instances": instance,
                "n": int(source["n"]),
                "BKS": bks,
                "VCGP_Best": float(source["vcgp_error_pct"]),
                "MDFIHA_Best": float(source["mdfiha_error_pct"]),
                "MDFIHA-ETGA_Best": float(source["etga_error_pct"]),
                "PyVRP-HGS_Best": float(source["mother_error_pct"]),
                "PyVRP-HGS_avg": 100.0
                * (
                    statistics.fmean(
                        float(row["mother_cost"]) for row in matching
                    )
                    - bks
                )
                / bks,
                "MV-HGS-SP_Best": float(source["hybrid_error_pct"]),
                "MV-HGS-SP_avg": 100.0
                * (
                    statistics.fmean(
                        float(row["hybrid_cost"]) for row in matching
                    )
                    - bks
                )
                / bks,
            }
        )
    averages = {"instances": "Avg", "n": "", "BKS": ""}
    for field in (
        "VCGP_Best",
        "MDFIHA_Best",
        "MDFIHA-ETGA_Best",
        "PyVRP-HGS_Best",
        "PyVRP-HGS_avg",
        "MV-HGS-SP_Best",
        "MV-HGS-SP_avg",
    ):
        averages[field] = statistics.fmean(
            float(row[field]) for row in output
        )
    output.append(averages)
    return output


def tex_public_benchmark(rows: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}cccccc@{\hspace{8pt}}cc@{\hspace{8pt}}cc@{}}",
        r"\toprule",
        r"\multirow{2}{*}{instances} & \multirow{2}{*}{$n$} & \multirow{2}{*}{BKS} & \multicolumn{1}{c}{VCGP} & \multicolumn{1}{c}{MDFIHA} & \multicolumn{1}{c}{MDFIHA-ETGA} & \multicolumn{2}{c}{PyVRP-HGS} & \multicolumn{2}{c}{MV-HGS-SP}\\",
        r"\cmidrule(lr){4-4}\cmidrule(lr){5-5}\cmidrule(lr){6-6}\cmidrule(lr){7-8}\cmidrule(lr){9-10}",
        r" & & & Best. & Best. & Best. & Best. & avg. & Best. & avg.\\",
        r"\midrule",
    ]
    best_fields = (
        "VCGP_Best",
        "MDFIHA_Best",
        "MDFIHA-ETGA_Best",
        "PyVRP-HGS_Best",
        "MV-HGS-SP_Best",
    )
    for row in rows:
        minimum = min(float(row[field]) for field in best_fields)
        cells = [
            str(row["instances"]),
            "--" if row["n"] == "" else str(int(row["n"])),
            "--" if row["BKS"] == "" else f"{float(row['BKS']):.3f}",
        ]
        for field in (
            "VCGP_Best",
            "MDFIHA_Best",
            "MDFIHA-ETGA_Best",
            "PyVRP-HGS_Best",
            "PyVRP-HGS_avg",
            "MV-HGS-SP_Best",
            "MV-HGS-SP_avg",
        ):
            cells.append(
                tex_number(
                    float(row[field]),
                    2,
                    bold=(
                        field in best_fields
                        and near(float(row[field]), minimum)
                    ),
                )
            )
        lines.append(" & ".join(cells) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular*}"])
    return "\n".join(lines) + "\n"


def iteration_case_rows() -> list[dict[str, Any]]:
    source = read_csv(S3 / "raw_runs.csv")
    if (
        len(source) != 10
        or {int(row["seed"]) for row in source} != set(range(1, 11))
        or any(row["status"] != "PASS" for row in source)
    ):
        raise RuntimeError("S3 publication matrix is not ten PASS seeds")
    by_seed = {int(row["seed"]): row for row in source}
    rows: list[dict[str, Any]] = []
    for seed in range(1, 11):
        row: dict[str, Any] = {"seed_or_stat": str(seed)}
        for arm in ARMS:
            row[f"{arm}_cost_cny"] = float(
                by_seed[seed][f"{arm}_cost"]
            )
            row[f"{arm}_cpu_min"] = (
                float(by_seed[seed][f"{arm}_cpu_seconds"]) / 60.0
            )
        rows.append(row)
    seed_rows = list(rows)
    for label, reducer in (
        ("Min", min),
        ("Avg", statistics.fmean),
        ("Max", max),
    ):
        row = {"seed_or_stat": label}
        for arm in ARMS:
            for metric in ("cost_cny", "cpu_min"):
                row[f"{arm}_{metric}"] = reducer(
                    float(item[f"{arm}_{metric}"])
                    for item in seed_rows
                )
        rows.append(row)
    return rows


def tex_iteration_case(rows: list[dict[str, Any]]) -> str:
    seed_rows = [
        row for row in rows if str(row["seed_or_stat"]).isdigit()
    ]
    minima = {
        f"{arm}_{metric}": min(
            float(row[f"{arm}_{metric}"]) for row in seed_rows
        )
        for arm in ARMS
        for metric in ("cost_cny", "cpu_min")
    }
    lines = [
        r"\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}ccccccccc@{}}",
        r"\toprule",
        r"\multirow{2}{*}{序号} & \multicolumn{2}{c}{HGS-F} & \multicolumn{2}{c}{HGS-E} & \multicolumn{2}{c}{HGS-M} & \multicolumn{2}{c}{MV-HGS-SP}\\",
        r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}\cmidrule(lr){6-7}\cmidrule(lr){8-9}",
        r" & 值 & CPU & 值 & CPU & 值 & CPU & 值 & CPU\\",
        r"\midrule",
    ]
    for row in rows:
        is_seed = str(row["seed_or_stat"]).isdigit()
        cells = [str(row["seed_or_stat"])]
        for arm in ARMS:
            for metric in ("cost_cny", "cpu_min"):
                value = float(row[f"{arm}_{metric}"])
                cells.append(
                    tex_number(
                        value,
                        2,
                        bold=(
                            is_seed
                            and near(
                                value,
                                minima[f"{arm}_{metric}"],
                            )
                        ),
                    )
                )
        lines.append(" & ".join(cells) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular*}"])
    return "\n".join(lines) + "\n"


def instance_statistics(
    rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    by_instance: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_instance.setdefault(row["instance_id"], []).append(row)
    if len(by_instance) != 81:
        raise RuntimeError("formal matrix does not contain 81 instances")
    output: list[dict[str, Any]] = []
    for instance_id, items in sorted(by_instance.items()):
        if (
            len(items) != 5
            or {int(row["seed"]) for row in items} != set(range(1, 6))
        ):
            raise RuntimeError(f"{instance_id}: not five fixed seeds")
        record: dict[str, Any] = {
            "instance_id": instance_id,
            "region": items[0]["region"],
            "tier": int(items[0]["tier"]),
        }
        for arm in ARMS:
            values = [float(row[f"{arm}_cost"]) for row in items]
            record[f"{arm}_Best"] = min(values)
            record[f"{arm}_avg"] = statistics.fmean(values)
        output.append(record)
    return output


def aggregate_row(
    label: str,
    region: str,
    tier_label: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    if not items:
        raise RuntimeError(f"empty China81 aggregate: {label}")
    row: dict[str, Any] = {
        "group_id": label,
        "region": region,
        "tier_or_band": tier_label,
        "instance_count": len(items),
    }
    for arm in ARMS:
        row[f"{arm}_Best"] = statistics.fmean(
            float(item[f"{arm}_Best"]) for item in items
        )
        row[f"{arm}_avg"] = statistics.fmean(
            float(item[f"{arm}_avg"]) for item in items
        )
    return row


def china81_summary_rows(
    instance_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    exact: list[dict[str, Any]] = []
    compact: list[dict[str, Any]] = []
    for region in REGIONS:
        region_items = [
            row for row in instance_rows if row["region"] == region
        ]
        for tier in TIERS:
            items = [
                row for row in region_items if int(row["tier"]) == tier
            ]
            if len(items) != 3:
                raise RuntimeError(f"{region}/{tier}: expected 3 instances")
            exact.append(
                aggregate_row(
                    f"{region}-{tier}",
                    REGION_NAMES[region],
                    str(tier),
                    items,
                )
            )
        for band, tiers in BANDS.items():
            items = [
                row for row in region_items if int(row["tier"]) in tiers
            ]
            if len(items) != 9:
                raise RuntimeError(f"{region}/{band}: expected 9 instances")
            compact.append(
                aggregate_row(
                    f"{region}-{band}",
                    REGION_NAMES[region],
                    band,
                    items,
                )
            )
    overall = aggregate_row(
        "overall",
        "总体",
        "全部9层",
        instance_rows,
    )
    exact.append(overall)
    compact.append(overall)
    return compact, exact


def tex_summary(
    rows: list[dict[str, Any]],
    *,
    exact: bool,
) -> str:
    lines = [
        r"\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}cccccccccc@{}}",
        r"\toprule",
        r"\multirow{2}{*}{城市群} & \multirow{2}{*}{规模层} & \multicolumn{2}{c}{HGS-F} & \multicolumn{2}{c}{HGS-E} & \multicolumn{2}{c}{HGS-M} & \multicolumn{2}{c}{MV-HGS-SP}\\",
        r"\cmidrule(lr){3-4}\cmidrule(lr){5-6}\cmidrule(lr){7-8}\cmidrule(lr){9-10}",
        r" & & Best. & avg. & Best. & avg. & Best. & avg. & Best. & avg.\\",
        r"\midrule",
    ]
    region_span = 9 if exact else 3
    region_seen: dict[str, int] = {}
    for row in rows:
        best_minimum = min(float(row[f"{arm}_Best"]) for arm in ARMS)
        avg_minimum = min(float(row[f"{arm}_avg"]) for arm in ARMS)
        region = str(row["region"])
        if region == "总体":
            region_cell = "总体"
        elif region_seen.get(region, 0) == 0:
            region_cell = rf"\multirow{{{region_span}}}{{*}}{{{region}}}"
        else:
            region_cell = ""
        region_seen[region] = region_seen.get(region, 0) + 1
        cells = [region_cell, str(row["tier_or_band"])]
        for arm in ARMS:
            best = float(row[f"{arm}_Best"])
            average = float(row[f"{arm}_avg"])
            cells.extend(
                [
                    tex_number(best, 2, bold=near(best, best_minimum)),
                    tex_number(
                        average,
                        2,
                        bold=near(average, avg_minimum),
                    ),
                ]
            )
        lines.append(" & ".join(cells) + r" \\")
        if (
            region != "总体"
            and region_seen[region] == region_span
            and region != REGION_NAMES[REGIONS[-1]]
        ):
            lines.append(r"\addlinespace[1pt]")
    lines.extend([r"\bottomrule", r"\end{tabular*}"])
    return "\n".join(lines) + "\n"


def numeric_route_path(
    path_text: str,
    customer_count: int,
    depot_ids: list[str],
) -> str:
    if path_text in {"mean", "total"}:
        return {"mean": "均值", "total": "合计"}[path_text]
    stripped = path_text.strip().strip("[]")
    tokens = [token.strip() for token in stripped.split(",") if token.strip()]
    depot_number = {
        depot_id: customer_count + index
        for index, depot_id in enumerate(sorted(depot_ids), start=1)
    }
    converted: list[int] = []
    for token in tokens:
        if token in depot_number:
            converted.append(depot_number[token])
        elif token.startswith("C") and token[1:].isdigit():
            value = int(token[1:])
            if not 1 <= value <= customer_count:
                raise RuntimeError(f"customer outside case range: {token}")
            converted.append(value)
        else:
            raise RuntimeError(f"unrecognized route token: {token}")
    if len(converted) < 2 or converted[0] != converted[-1]:
        raise RuntimeError(f"route does not return to its depot: {path_text}")
    return "[" + ", ".join(str(value) for value in converted) + "]"


def route_detail_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = read_csv(S4 / "route_details.csv")
    detail = [row for row in source if row["route_index"].isdigit()]
    if not detail:
        raise RuntimeError("S4 route table has no route rows")
    customer_ids = {
        int(token[1:])
        for row in detail
        for token in row["path"].strip("[]").split(", ")
        if token.startswith("C") and token[1:].isdigit()
    }
    customer_count = max(customer_ids)
    if customer_ids != set(range(1, customer_count + 1)):
        raise RuntimeError("S4 route table does not cover customers 1--n")
    depot_ids = sorted({row["home_depot_id"] for row in detail})
    if len(depot_ids) != 2:
        raise RuntimeError("S4 route table does not contain two depots")
    output: list[dict[str, Any]] = []
    for row in source:
        is_mean = row["route_index"] == "mean"
        is_total = row["route_index"] == "total"
        output.append(
            {
                "路径": numeric_route_path(
                    row["path"],
                    customer_count,
                    depot_ids,
                ),
                "距离_km": float(row["distance_km"]),
                "成本_CNY": float(row["cost_cny"]),
                "时间_h": float(row["time_h"]),
                "油耗_L": float(row["fuel_l"]),
                "电耗_kWh": float(row["electricity_kwh"]),
                "碳排放_kg": float(row["emissions_kg"]),
                "num": (
                    "-"
                    if is_mean
                    else str(int(round(float(row["on_time_customer_count"]))))
                ),
                "装载率_pct": (
                    "-"
                    if is_total or row["load_rate_pct"] == ""
                    else f"{float(row['load_rate_pct']):.2f}"
                ),
            }
        )
    return output, {
        "customer_count": customer_count,
        "depot_number_map": {
            depot_id: customer_count + index
            for index, depot_id in enumerate(depot_ids, start=1)
        },
    }


def tex_route_detail(rows: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}lcccccccc@{}}",
        r"\toprule",
        r"路径 & 距离/km & 成本/元 & 时间/h & 油耗/L & 电耗/kWh & 碳排放/kg & num & 装载率/\%\\",
        r"\midrule",
    ]
    for row in rows:
        cells = [
            str(row["路径"]).replace("[", "{[}").replace("]", "{]}"),
            f"{float(row['距离_km']):.3f}",
            f"{float(row['成本_CNY']):.3f}",
            f"{float(row['时间_h']):.3f}",
            f"{float(row['油耗_L']):.3f}",
            f"{float(row['电耗_kWh']):.3f}",
            f"{float(row['碳排放_kg']):.3f}",
            str(row["num"]),
            str(row["装载率_pct"]),
        ]
        lines.append(" & ".join(cells) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular*}"])
    return "\n".join(lines) + "\n"


def setup_axes(ax: Any) -> None:
    ax.grid(False)
    ax.tick_params(direction="in", width=0.55, length=2.8)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.55)


def plot_carbon_profile() -> dict[str, Any]:
    source = [
        row
        for row in read_csv(RUNTIME / "tariff_carbon_48slot_calendar.csv")
        if row["date"] == "2025-02-12"
    ]
    selections = (
        ("beijing", "京津冀", "#4D4D4D", "-", "o"),
        ("guangzhou", "珠三角", "#D95F02", "--", "^"),
        ("chongqing", "成渝", "#1B9E77", "-.", "s"),
    )
    curve_rows: list[dict[str, Any]] = []
    fig, ax = plt.subplots(figsize=(4.30, 2.80))
    for city, label, color, style, marker in selections:
        rows = sorted(
            (row for row in source if row["city"] == city),
            key=lambda row: int(row["half_hour_slot"]),
        )
        if len(rows) != 48:
            raise RuntimeError(f"{city}: expected 48 half-hour rows")
        x = [float(row["minute_of_day"]) / 60.0 for row in rows]
        y = [
            1000.0 * float(row["carbon_factor_kgco2e_per_kwh"])
            for row in rows
        ]
        ax.plot(
            x,
            y,
            color=color,
            linestyle=style,
            linewidth=0.78,
            marker=marker,
            markersize=2.4,
            markevery=6,
            markerfacecolor="white",
            markeredgewidth=0.55,
            label=label,
        )
        curve_rows.extend(
            {
                "city_group": label,
                "representative_city": city,
                "date": row["date"],
                "half_hour_slot": int(row["half_hour_slot"]),
                "time_h": float(row["minute_of_day"]) / 60.0,
                "carbon_intensity_gco2_per_kwh": 1000.0
                * float(row["carbon_factor_kgco2e_per_kwh"]),
                "carbon_source_column": row["carbon_source_column"],
            }
            for row in rows
        )
    ax.set_xlabel("时刻(h)")
    ax.set_ylabel("碳强度(gCO₂/kWh)")
    ax.legend(
        loc="lower left",
        frameon=False,
        fontsize=6.6,
        handlelength=2.2,
        handletextpad=0.45,
        labelspacing=0.22,
        borderaxespad=0.35,
    )
    setup_axes(ax)
    ax.margins(x=0.025, y=0.06)
    fig.tight_layout(pad=0.55)
    fig.savefig(OUT / "figure3_carbon_profile.pdf")
    fig.savefig(OUT / "figure3_carbon_profile.png", dpi=300)
    plt.close(fig)
    write_csv(OUT / "figure3_carbon_profile.csv", curve_rows)
    return {
        "rows": len(curve_rows),
        "date": "2025-02-12",
        "legend_location": "lower left",
        "legend_frame": False,
        "labels": [item[1] for item in selections],
    }


def deterministic_legend_corner(
    curves: dict[str, tuple[list[float], list[float]]],
    x_limits: tuple[float, float],
    y_limits: tuple[float, float],
) -> str:
    boxes = {
        "upper right": (0.61, 0.99, 0.69, 0.99),
        "upper left": (0.01, 0.39, 0.69, 0.99),
        "lower left": (0.01, 0.39, 0.01, 0.31),
        "lower right": (0.61, 0.99, 0.01, 0.31),
    }
    x_span = x_limits[1] - x_limits[0]
    y_span = y_limits[1] - y_limits[0]
    scores: dict[str, int] = {corner: 0 for corner in boxes}
    for x_values, y_values in curves.values():
        for x_value, y_value in zip(x_values, y_values, strict=True):
            xn = (x_value - x_limits[0]) / x_span
            yn = (y_value - y_limits[0]) / y_span
            for corner, (x0, x1, y0, y1) in boxes.items():
                if x0 <= xn <= x1 and y0 <= yn <= y1:
                    scores[corner] += 1
    priority = {
        "upper right": 0,
        "upper left": 1,
        "lower left": 2,
        "lower right": 3,
    }
    return min(scores, key=lambda corner: (scores[corner], priority[corner]))


def padded_limits(values: Iterable[float]) -> tuple[float, float]:
    data = [float(value) for value in values]
    minimum = min(data)
    maximum = max(data)
    span = maximum - minimum
    if span <= 0.0:
        span = max(abs(maximum), 1.0)
    margin = 0.03 * span
    return minimum - margin, maximum + margin


def plot_iteration_figure() -> dict[str, Any]:
    rows = read_csv(S3 / "curve_data.csv")
    if {row["algorithm"] for row in rows} != set(ARMS):
        raise RuntimeError("Figure 4 does not contain the four fixed methods")
    s3_rows = {
        int(row["seed"]): row for row in read_csv(S3 / "raw_runs.csv")
    }
    styles = {
        "HGS-F": ("#4D4D4D", "-", "o", 0.72, 2),
        "HGS-E": ("#E69F00", "--", "^", 0.76, 3),
        "HGS-M": ("#6A3D9A", ":", "s", 0.86, 4),
        "MV-HGS-SP": ("#C51B7D", "-.", "D", 0.96, 5),
    }
    curves: dict[str, tuple[list[float], list[float]]] = {}
    plotted_rows: list[dict[str, Any]] = []
    for arm in ARMS:
        arm_rows = sorted(
            (row for row in rows if row["algorithm"] == arm),
            key=lambda row: int(row["sequence"]),
        )
        if len(arm_rows) < 2:
            raise RuntimeError(f"{arm}: too few genuine observations")
        seeds = {int(row["seed"]) for row in arm_rows}
        if len(seeds) != 1:
            raise RuntimeError(f"{arm}: curve mixes seeds")
        seed = next(iter(seeds))
        x = [float(row["elapsed_minutes"]) for row in arm_rows]
        y = [float(row["cost_cny"]) for row in arm_rows]
        if (
            any(x[index] < x[index - 1] - EPS for index in range(1, len(x)))
            or any(y[index] > y[index - 1] + EPS for index in range(1, len(y)))
            or any(
                row["observed_online"].lower() != "true"
                or row["interpolated_or_smoothed"].lower() != "false"
                for row in arm_rows
            )
            or not near(y[-1], float(s3_rows[seed][f"{arm}_cost"]))
        ):
            raise RuntimeError(f"{arm}: curve protocol check failed")
        curves[arm] = (x, y)
        plotted_rows.extend(
            {
                "algorithm": arm,
                "seed": seed,
                "sequence": int(row["sequence"]),
                "elapsed_minutes": float(row["elapsed_minutes"]),
                "cost_cny": float(row["cost_cny"]),
                "observed_online": True,
                "interpolated_or_smoothed": False,
            }
            for row in arm_rows
        )
    x_limits = padded_limits(
        value for x_values, _ in curves.values() for value in x_values
    )
    y_limits = padded_limits(
        value for _, y_values in curves.values() for value in y_values
    )
    legend_corner = deterministic_legend_corner(
        curves,
        x_limits,
        y_limits,
    )
    fig, ax = plt.subplots(figsize=(3.55, 3.10))
    for arm in ARMS:
        x, y = curves[arm]
        color, linestyle, marker, width, zorder = styles[arm]
        ax.plot(
            x,
            y,
            color=color,
            linestyle=linestyle,
            linewidth=width,
            marker=marker,
            markersize=2.5,
            markevery=max(1, len(x) // 7),
            markerfacecolor="white",
            markeredgewidth=0.55,
            label=arm,
            zorder=zorder,
        )
    ax.set_xlim(*x_limits)
    ax.set_ylim(*y_limits)
    ax.set_xlabel("时间(min)")
    ax.set_ylabel("成本(元)")
    ax.legend(
        loc=legend_corner,
        frameon=False,
        fontsize=6.6,
        handlelength=2.35,
        handletextpad=0.45,
        labelspacing=0.22,
        borderaxespad=0.35,
    )
    setup_axes(ax)
    fig.tight_layout(pad=0.62)
    fig.savefig(OUT / "figure4_iteration.pdf")
    fig.savefig(OUT / "figure4_iteration.png", dpi=300)
    plt.close(fig)
    write_csv(OUT / "figure4_iteration.csv", plotted_rows)
    return {
        "rows": len(plotted_rows),
        "algorithms": list(ARMS),
        "x_limits": list(x_limits),
        "y_limits": list(y_limits),
        "axis_margin_fraction": 0.03,
        "legend_location": legend_corner,
        "legend_selection": "deterministic minimum point overlap",
        "broken_axis": False,
        "smoothing_or_interpolation": False,
        "x_label": "时间(min)",
        "y_label": "成本(元)",
    }


def validate_upstream() -> dict[str, Any]:
    protocol = read_json(PROTOCOL)
    if (
        protocol.get("status") != "FROZEN_BEFORE_FORMAL_V7_RESULTS"
        or protocol.get("operation")
        != "ZERO_SEARCH_SEALED_ARTIFACT_MATERIALIZATION"
        or protocol.get("search_evaluations") != 0
    ):
        raise RuntimeError("S5 protocol is not the frozen zero-search contract")
    full = require_verdict(
        FULL,
        "PASS_D6_CORRECTED_CHINA81_E2_STAGED_V7_SMALL_ARCHIVE_LEDGER",
    )
    replay = require_verdict(
        REPLAY,
        "PASS_D6_STAGED_FULL_WITNESS_REPLAY",
    )
    strength = require_verdict(
        STRENGTH,
        "PASS_E2_STAGED_PORTFOLIO_PAPER_STRENGTH",
    )
    s3 = require_verdict(
        S3,
        "PASS_S3_STAGED_GENUINE_ITERATION_CURVES",
    )
    s4 = require_verdict(
        S4,
        "PASS_D6_CORRECTED_S4_ROUTE_DETAIL",
    )
    if (
        not bool(strength.get("paper_strength_pass"))
        or not bool(s3.get("trajectory_gate_pass"))
        or int(replay.get("solution_count", -1)) != 1620
    ):
        raise RuntimeError("upstream decision is internally inconsistent")
    runtime = require_verdict(
        RUNTIME,
        "PASS_CITY_DATE_SLOT_PARAMETER_AUTHORITY",
    )
    if runtime.get("scenario_date") != "2025-02-12":
        raise RuntimeError("runtime authority date is not 2025-02-12")
    return {
        "protocol": protocol,
        "full": full,
        "replay": replay,
        "strength": strength,
        "s3": s3,
        "s4": s4,
        "runtime": runtime,
    }


def main() -> int:
    upstream = validate_upstream()
    OUT.mkdir(parents=True, exist_ok=True)
    configure_fonts()
    full_rows = read_csv(FULL / "raw_runs.csv")
    if (
        len(full_rows) != 405
        or len(
            {
                (row["instance_id"], int(row["seed"]))
                for row in full_rows
            }
        )
        != 405
        or any(row["status"] != "PASS" for row in full_rows)
    ):
        raise RuntimeError("formal E2 matrix is not 405 unique PASS tasks")

    public_rows = public_benchmark_rows()
    iteration_rows = iteration_case_rows()
    instance_rows = instance_statistics(full_rows)
    compact_rows, exact_rows = china81_summary_rows(instance_rows)
    route_rows, route_context = route_detail_rows()

    write_csv(OUT / "table_public_benchmark.csv", public_rows)
    write_csv(OUT / "table_iteration_case.csv", iteration_rows)
    write_csv(OUT / "table_china81_summary_compact.csv", compact_rows)
    write_csv(OUT / "table_china81_exact_layers.csv", exact_rows)
    write_csv(OUT / "table_route_details.csv", route_rows)
    (OUT / "table_public_benchmark.tex").write_text(
        tex_public_benchmark(public_rows),
        encoding="utf-8",
    )
    (OUT / "table_iteration_case.tex").write_text(
        tex_iteration_case(iteration_rows),
        encoding="utf-8",
    )
    (OUT / "table_china81_summary_compact.tex").write_text(
        tex_summary(compact_rows, exact=False),
        encoding="utf-8",
    )
    (OUT / "table_china81_exact_layers.tex").write_text(
        tex_summary(exact_rows, exact=True),
        encoding="utf-8",
    )
    (OUT / "table_route_details.tex").write_text(
        tex_route_detail(route_rows),
        encoding="utf-8",
    )
    figure3 = plot_carbon_profile()
    figure4 = plot_iteration_figure()
    table_notes = {
        "official_macro": "\\tabnote{注：...}",
        "public_benchmark": (
            "表中数值为相对BKS的误差百分比；文献列取原论文报告的"
            "最好值；PyVRP-HGS与MV-HGS-SP为同机、相同时间上限、"
            "种子1--10的结果。"
        ),
        "iteration_case": (
            f"迭代展示算例为{upstream['s3']['selected_instance_id']}；"
            "值为总成本(元)，CPU为实际运行时间(min)；黑体仅标出"
            "各算法10次运行中相应列的最小值。该算例只展示搜索过程，"
            "不作为81个算例的统计代表。"
        ),
        "china81_summary": (
            "成本单位为元；每个算例使用固定种子1--5。Best.为同一"
            "算例5次运行的最低成本，avg.为5次运行平均成本；层内先"
            "按算例计算，再等权汇总。每行Best.和avg.分别以黑体标出"
            "最小值；全部405个任务及1620个解均须通过独立复算。"
        ),
        "route_detail": (
            "路径中的客户编号为1--"
            f"{route_context['customer_count']}；车场编号映射为"
            f"{route_context['depot_number_map']}。逐路线数据由同一"
            "完整解重新计算，覆盖性只在整解层面核验。"
        ),
    }
    write_json(OUT / "table_notes.json", table_notes)

    decision = {
        "schema": "resetp.e2-staged-v7-s5-artifacts.decision.v1",
        "verdict": "PASS_E2_STAGED_V7_S5_ARTIFACTS",
        "search_executions": 0,
        "formal_rows": len(full_rows),
        "replayed_solutions": upstream["replay"]["solution_count"],
        "public_rows": len(public_rows),
        "iteration_rows": len(iteration_rows),
        "compact_summary_rows": len(compact_rows),
        "exact_layer_rows": len(exact_rows),
        "route_rows": len(route_rows),
        "figure3": figure3,
        "figure4": figure4,
        "publisher_table_note_macro": "tabnote",
        "claim_boundary": (
            "Zero-search materialization from sealed E2 evidence. "
            "No score, selected seed, statistical unit or curve point "
            "was changed."
        ),
    }
    write_json(OUT / "decision.json", decision)
    source_paths = (
        PROTOCOL,
        FULL / "raw_runs.csv",
        FULL / "decision.json",
        REPLAY / "raw_runs.csv",
        REPLAY / "decision.json",
        STRENGTH / "decision.json",
        STRENGTH / "result_summary.json",
        S3 / "raw_runs.csv",
        S3 / "curve_data.csv",
        S3 / "decision.json",
        S4 / "route_details.csv",
        S4 / "decision.json",
        P1 / "raw_runs.csv",
        P1 / "decision.json",
        RUNTIME / "tariff_carbon_48slot_calendar.csv",
        RUNTIME / "decision.json",
        Path(__file__).resolve(),
    )
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.e2-staged-v7-s5-artifacts.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "campaign_name": CAMPAIGN_NAME,
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in source_paths
            },
            "format_authority": {
                "publisher_class": "docs/paper_v2/setp-new.cls",
                "table_note_macro": "tabnote",
                "table_style": "Chinese three-line table",
                "figure_style": (
                    "publisher first; Chen 2025 where publisher is silent"
                ),
            },
        },
    )
    (OUT / "report.md").write_text(
        "# V7 E2 S5 publication artifacts\n\n"
        f"Decision: `{decision['verdict']}`.\n\n"
        "All tables and figures were generated without search from the "
        "sealed formal, independent replay, strength, S3 and S4 records. "
        "Figure 4 uses only genuine online complete-model observations, "
        "ordinary straight segments, a single continuous coordinate system "
        "and fixed data-wide margins. Table fragments use full-width "
        "three-line layouts; notes are supplied separately for the official "
        "`\\tabnote` macro in the publisher class.\n",
        encoding="utf-8",
    )
    for path in OUT.rglob("._*"):
        if path.is_file():
            path.unlink()
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "done.json",
                "._*",
                "__pycache__",
                "*.tmp",
            ],
            "artifacts": artifacts,
        },
    )
    write_json(
        OUT / "done.json",
        {
            "schema": "resetp.e2-staged-v7-s5-artifacts-done.v1",
            "verdict": decision["verdict"],
            "decision_sha256": sha256(OUT / "decision.json"),
            "figure3_sha256": sha256(OUT / "figure3_carbon_profile.pdf"),
            "figure4_sha256": sha256(OUT / "figure4_iteration.pdf"),
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
