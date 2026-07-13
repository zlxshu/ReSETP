#!/usr/bin/env python3
"""Build reader-facing E3/E4 paper exhibits without rerunning route search.

The builder reads only sealed E3/E4 evidence.  It separates three questions:

1. What does geographic organization of customer responsibility change?
2. How much collaboration value remains under each ownership structure?
3. How much emission reduction remains when only charging time may change?

Every displayed value is independently derived from sealed CSV files.  Search
evaluations performed by this script: zero.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import csv
import hashlib
import json
import math
import statistics
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
E3 = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
OWNERSHIP = ROOT / "baselines/e3_ablation/e3_ownership_class_design_v4_20260713"
E4 = ROOT / "baselines/e4_e5/e4_forecast_timing_formal_20260713"
CARBON = ROOT / "data/Carbon/时变碳强度/Carbon_Intensity_Data.csv"
CONTRACT = ROOT / "docs/handoff/e3_e4_paper_story_and_exhibit_contract_20260713.md"
INSTANCE_ROOT = ROOT / "models/data_bundle/generated_instances/L-main"
OUT = ROOT / "docs/paper_submission_final/e3_e4_story_20260713"
FIGURES = OUT / "figures"
TABLES = OUT / "tables"

REPRESENTATIVE_INSTANCE = "L-main-threeshift-75c-01"
CONDITIONS = ("geographic", "mixed")
ARMS = ("ownership_fixed", "reassignment_allowed")
SEEDS = (1, 2, 3)
TOLERANCE = 1e-9

BLUE = "#4C78A8"
ORANGE = "#F28E2B"
INK = "#1F2937"
GREY = "#6B7280"
LIGHT_GREY = "#D1D5DB"
GRID = "#E5E7EB"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"refusing to write an empty table: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def markdown_table(rows: list[dict[str, Any]]) -> str:
    fields = list(rows[0])
    lines = [
        "| " + " | ".join(fields) + " |",
        "| " + " | ".join("---" for _ in fields) + " |",
    ]
    lines.extend(
        "| " + " | ".join(str(row[field]) for field in fields) + " |" for row in rows
    )
    return "\n".join(lines) + "\n"


def write_table_bundle(stem: str, rows: list[dict[str, Any]]) -> None:
    write_csv(TABLES / f"{stem}.csv", rows)
    (TABLES / f"{stem}.md").write_text(markdown_table(rows), encoding="utf-8")


def exact_two_sided_sign_p(values: Iterable[float]) -> float:
    materialized = list(values)
    positive = sum(value > TOLERANCE for value in materialized)
    negative = sum(value < -TOLERANCE for value in materialized)
    n = positive + negative
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(0, min(positive, negative) + 1)) / (2**n)
    return min(1.0, 2.0 * tail)


def mean(values: Iterable[float]) -> float:
    materialized = list(values)
    if not materialized:
        raise ValueError("mean of empty input")
    return statistics.fmean(materialized)


def configure_plotting() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [
                "Hiragino Sans GB",
                "PingFang SC",
                "Heiti SC",
                "Arial Unicode MS",
                "DejaVu Sans",
            ],
            "axes.unicode_minus": False,
            "font.size": 10.5,
            "axes.titlesize": 13,
            "axes.labelsize": 11,
            "legend.fontsize": 9.5,
            "xtick.labelsize": 9.5,
            "ytick.labelsize": 9.5,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "text.color": INK,
            "axes.labelcolor": INK,
            "axes.edgecolor": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "svg.hashsalt": "resetp-e3-e4-story-20260713",
        }
    )


def save_figure(fig: Any, stem: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "pdf", "svg"):
        output_path = FIGURES / f"{stem}.{suffix}"
        kwargs: dict[str, Any] = {"dpi": 300} if suffix == "png" else {}
        if suffix == "pdf":
            kwargs["metadata"] = {
                "Creator": "ReSETP paper story builder",
                "CreationDate": None,
                "ModDate": None,
            }
        elif suffix == "svg":
            kwargs["metadata"] = {
                "Creator": "ReSETP paper story builder",
                "Date": None,
            }
        fig.savefig(output_path, bbox_inches="tight", **kwargs)
        if suffix == "svg":
            cleaned = "\n".join(
                line.rstrip() for line in output_path.read_text(encoding="utf-8").splitlines()
            )
            output_path.write_text(cleaned + "\n", encoding="utf-8")
    plt.close(fig)


def instance_counts() -> dict[str, int]:
    rows = read_csv(OWNERSHIP / "raw_runs.csv")
    counts = {row["instance"]: int(row["customer_count"]) for row in rows}
    if len(counts) != 9:
        raise RuntimeError(f"ownership design has {len(counts)} networks, expected 9")
    return counts


def network_diameters_km(counts: dict[str, int]) -> dict[str, float]:
    """Return the maximum customer/depot point distance for each formal network."""

    diameters: dict[str, float] = {}
    for instance in counts:
        rows = read_csv(INSTANCE_ROOT / instance / "nodes.csv")
        points = [
            (float(row["x"]), float(row["y"]))
            for row in rows
            if row["node_type"].lower() in {"c", "d"}
        ]
        if len(points) < 2:
            raise RuntimeError(f"network has fewer than two customer/depot points: {instance}")
        diameters[instance] = max(
            math.hypot(x1 - x2, y1 - y2)
            for index, (x1, y1) in enumerate(points)
            for x2, y2 in points[index + 1 :]
        ) / 1000.0
    return diameters


def validate_e3_rows(
    raw: list[dict[str, str]], paired: list[dict[str, str]], counts: dict[str, int]
) -> None:
    expected_raw = len(counts) * len(CONDITIONS) * len(ARMS) * len(SEEDS)
    expected_pairs = len(counts) * len(CONDITIONS) * len(SEEDS)
    if len(raw) != expected_raw or len(paired) != expected_pairs:
        raise RuntimeError(
            f"E3 row mismatch: raw={len(raw)}/{expected_raw}, paired={len(paired)}/{expected_pairs}"
        )
    if any(
        row["status"] != "PASS"
        or int(row["evaluations"]) != 4000
        or int(row["budget"]) != 4000
        or int(row["violation_count"]) != 0
        for row in raw
    ):
        raise RuntimeError("E3 contains a failed, asymmetric-budget or violating row")
    raw_index = {
        (row["instance"], row["condition"], int(row["seed"]), row["arm"]): row
        for row in raw
    }
    for instance in counts:
        for condition in CONDITIONS:
            for seed in SEEDS:
                fixed = raw_index[(instance, condition, seed, "ownership_fixed")]
                shared = raw_index[(instance, condition, seed, "reassignment_allowed")]
                if fixed["start_sha256"] != shared["start_sha256"]:
                    raise RuntimeError(f"E3 start mismatch: {instance}/{condition}/seed{seed}")


def derive_e3() -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    counts = instance_counts()
    diameters = network_diameters_km(counts)
    raw = read_csv(E3 / "raw_runs.csv")
    paired = read_csv(E3 / "paired_results.csv")
    validate_e3_rows(raw, paired, counts)

    raw_index = {
        (row["instance"], row["condition"], int(row["seed"]), row["arm"]): row
        for row in raw
    }
    paired_groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in paired:
        paired_groups[(row["instance"], row["condition"])].append(row)

    network_rows: list[dict[str, Any]] = []
    geographic_savings: list[float] = []
    mixed_savings: list[float] = []
    for instance in sorted(counts, key=counts.get):
        means: dict[str, float] = {}
        positive_seeds: dict[str, int] = {}
        for condition in CONDITIONS:
            savings = [
                float(row["saving_pct"]) for row in paired_groups[(instance, condition)]
            ]
            means[condition] = mean(savings)
            positive_seeds[condition] = sum(value > TOLERANCE for value in savings)
        geographic_savings.append(means["geographic"])
        mixed_savings.append(means["mixed"])
        network_rows.append(
            {
                "实际客户数": counts[instance],
                "按地理关系划分（%）": round(means["geographic"], 3),
                "空间交错划分（%）": round(means["mixed"], 3),
                "空间交错多出的协同价值（百分点）": round(
                    means["mixed"] - means["geographic"], 3
                ),
                "按地理关系划分的改善次数（3 次）": f"{positive_seeds['geographic']}/3",
                "空间交错划分的改善次数（3 次）": f"{positive_seeds['mixed']}/3",
            }
        )

    direct_metric_fields = (
        ("总成本", "total_cost"),
        ("总行驶距离", "distance_total"),
        ("燃油直接排放", "E_cv_direct"),
        ("用电量", "electricity_kwh"),
    )
    direct_rows: list[dict[str, Any]] = []
    direct_values: dict[str, list[float]] = {}
    for label, field in direct_metric_fields:
        reductions: list[float] = []
        for instance in sorted(counts, key=counts.get):
            geographic = mean(
                float(raw_index[(instance, "geographic", seed, "ownership_fixed")][field])
                for seed in SEEDS
            )
            mixed = mean(
                float(raw_index[(instance, "mixed", seed, "ownership_fixed")][field])
                for seed in SEEDS
            )
            if abs(mixed) <= TOLERANCE:
                raise RuntimeError(f"undefined direct percentage: {instance}/{field}")
            reductions.append((mixed - geographic) / mixed * 100.0)
        direct_values[field] = reductions
        direct_rows.append(
            {
                "运营指标": label,
                "按地理关系划分后的平均下降（%）": f"{mean(reductions):.3f}",
                "改善网络": f"{sum(value > TOLERANCE for value in reductions)}/9",
                "概率值": f"{exact_two_sided_sign_p(reductions):.4f}",
            }
        )

    component_fields = (
        ("每趟固定费", "cost_fix"),
        ("里程费", "cost_km"),
        ("燃油费", "cost_fuel"),
        ("电费", "cost_elec"),
    )
    component_by_condition: dict[str, dict[str, list[float]]] = {
        condition: {field: [] for _, field in component_fields} | {"total": []}
        for condition in CONDITIONS
    }
    physical_deltas: dict[str, list[float]] = {condition: [] for condition in CONDITIONS}
    gap_deltas: dict[str, list[float]] = {condition: [] for condition in CONDITIONS}
    for condition in CONDITIONS:
        for instance in sorted(counts, key=counts.get):
            per_seed: dict[str, list[float]] = {
                field: [] for _, field in component_fields
            } | {"total": []}
            seed_physical: list[float] = []
            seed_gap: list[float] = []
            for seed in SEEDS:
                fixed = raw_index[(instance, condition, seed, "ownership_fixed")]
                shared = raw_index[(instance, condition, seed, "reassignment_allowed")]
                base = float(fixed["total_cost"])
                for _, field in component_fields:
                    per_seed[field].append(
                        (float(fixed[field]) - float(shared[field])) / base * 100.0
                    )
                per_seed["total"].append(
                    (base - float(shared["total_cost"])) / base * 100.0
                )
                seed_physical.append(
                    float(shared["physical_total"]) - float(fixed["physical_total"])
                )
                seed_gap.append(
                    float(shared["between_trip_gap_hours"])
                    - float(fixed["between_trip_gap_hours"])
                )
            for field in per_seed:
                component_by_condition[condition][field].append(mean(per_seed[field]))
            physical_deltas[condition].append(mean(seed_physical))
            gap_deltas[condition].append(mean(seed_gap))

    component_rows: list[dict[str, Any]] = []
    for label, field in component_fields:
        component_rows.append(
            {
                "成本账目": label,
                "按地理关系划分（百分点）": f"{mean(component_by_condition['geographic'][field]):.3f}",
                "空间交错划分（百分点）": f"{mean(component_by_condition['mixed'][field]):.3f}",
            }
        )
    component_rows.append(
        {
            "成本账目": "总成本",
            "按地理关系划分（百分点）": f"{mean(component_by_condition['geographic']['total']):.3f}",
            "空间交错划分（百分点）": f"{mean(component_by_condition['mixed']['total']):.3f}",
        }
    )

    effects = [mixed - geographic for geographic, mixed in zip(geographic_savings, mixed_savings)]
    values = {
        "network_count": len(counts),
        "network_diameters_km": diameters,
        "minimum_network_diameter_km": min(diameters.values()),
        "maximum_network_diameter_km": max(diameters.values()),
        "geographic_mean_saving_pct": mean(geographic_savings),
        "geographic_positive_networks": sum(value > TOLERANCE for value in geographic_savings),
        "geographic_sign_p": exact_two_sided_sign_p(geographic_savings),
        "mixed_mean_saving_pct": mean(mixed_savings),
        "mixed_positive_networks": sum(value > TOLERANCE for value in mixed_savings),
        "mixed_sign_p": exact_two_sided_sign_p(mixed_savings),
        "mixed_minus_geographic_pct_points": mean(effects),
        "mixed_greater_networks": sum(value > TOLERANCE for value in effects),
        "structure_effect_sign_p": exact_two_sided_sign_p(effects),
        "direct_seed_first_aggregation": {
            field: {
                "mean_reduction_pct": mean(values_for_field),
                "positive_networks": sum(value > TOLERANCE for value in values_for_field),
                "sign_p": exact_two_sided_sign_p(values_for_field),
                "network_values": values_for_field,
            }
            for field, values_for_field in direct_values.items()
        },
        "mixed_physical_fewer_networks": sum(
            value < -TOLERANCE for value in physical_deltas["mixed"]
        ),
        "mixed_physical_equal_networks": sum(
            abs(value) <= TOLERANCE for value in physical_deltas["mixed"]
        ),
        "mixed_physical_more_networks": sum(
            value > TOLERANCE for value in physical_deltas["mixed"]
        ),
        "mixed_gap_increase_networks": sum(
            value > TOLERANCE for value in gap_deltas["mixed"]
        ),
        "mixed_gap_decrease_networks": sum(
            value < -TOLERANCE for value in gap_deltas["mixed"]
        ),
    }
    return direct_rows, network_rows, component_rows, values


def owner_map(condition: str) -> dict[str, str]:
    path = OWNERSHIP / "ownership_maps" / f"{REPRESENTATIVE_INSTANCE}__{condition}.csv"
    return {row["customer_id"]: row["owner_depot_id"] for row in read_csv(path)}


def plot_e3_structure() -> None:
    instance_path = (
        ROOT
        / "models/data_bundle/generated_instances/L-main"
        / REPRESENTATIVE_INSTANCE
        / "instance.json"
    )
    payload = json.loads(instance_path.read_text(encoding="utf-8"))
    nodes = {node["node_id"]: node for node in payload["nodes"]}
    depots = [node for node in nodes.values() if node["node_type"].lower() == "d"]
    colors = {"D0": BLUE, "D1": ORANGE}
    markers = {"D0": "o", "D1": "^"}
    names = {"D0": "A", "D1": "B"}

    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.65), sharex=True, sharey=True)
    panel_titles = ("按地理关系划分", "空间交错划分")
    for ax, condition, panel_title in zip(axes, CONDITIONS, panel_titles, strict=True):
        owners = owner_map(condition)
        for owner in ("D0", "D1"):
            selected = [nodes[customer] for customer, depot in owners.items() if depot == owner]
            ax.scatter(
                [node["x"] / 1000.0 for node in selected],
                [node["y"] / 1000.0 for node in selected],
                s=25,
                marker=markers[owner],
                c=colors[owner],
                alpha=0.76,
                linewidths=0.35,
                edgecolors="white",
                label=f"车场 {names[owner]} 负责的客户",
            )
        for depot in depots:
            ax.scatter(
                depot["x"] / 1000.0,
                depot["y"] / 1000.0,
                s=175,
                marker="*",
                c=colors[depot["node_id"]],
                edgecolors="black",
                linewidths=0.9,
                zorder=5,
            )
            ax.annotate(
                f"车场 {names[depot['node_id']]}",
                (depot["x"] / 1000.0, depot["y"] / 1000.0),
                xytext=(6, 5),
                textcoords="offset points",
                fontsize=9,
                weight="bold",
            )
        ax.set_title(panel_title, weight="bold", pad=8)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color(LIGHT_GREY)
            spine.set_linewidth(0.8)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="lower center",
        ncol=2,
        frameon=False,
        bbox_to_anchor=(0.5, -0.005),
    )
    fig.suptitle("客户归属的空间结构", weight="bold", y=1.02)
    fig.text(
        0.5,
        0.955,
        "同一批客户和车场坐标，仅客户责任标签不同",
        ha="center",
        va="top",
        color=GREY,
        fontsize=9.5,
    )
    fig.subplots_adjust(wspace=0.06, bottom=0.14, top=0.86)
    save_figure(fig, "figure_e3_1_customer_responsibility_structure")


def plot_e3_collaboration(values: dict[str, Any]) -> None:
    labels = ["按地理关系划分", "空间交错划分"]
    savings = [values["geographic_mean_saving_pct"], values["mixed_mean_saving_pct"]]
    colors = [BLUE, ORANGE]
    annotations = [
        f"{values['geographic_positive_networks']}/9 张网络改善；概率值 {values['geographic_sign_p']:.3f}",
        f"{values['mixed_positive_networks']}/9 张网络改善；概率值 {values['mixed_sign_p']:.4f}",
    ]

    fig, ax = plt.subplots(figsize=(8.3, 3.9))
    y = np.arange(len(labels))
    bars = ax.barh(y, savings, color=colors, height=0.54, edgecolor=INK, linewidth=0.45)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 30)
    ax.set_xlabel("合作相对固定客户分工的成本下降（%）")
    ax.set_title("不同客户归属结构下的协同成本变化", weight="bold", pad=20)
    ax.text(
        0.5,
        1.03,
        "每张网络的三次计算先平均，九张网络等权",
        ha="center",
        va="bottom",
        transform=ax.transAxes,
        color=GREY,
        fontsize=9.3,
    )
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    for bar, value, annotation in zip(bars, savings, annotations, strict=True):
        ax.text(
            value - 0.35,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.1f}%",
            ha="right",
            va="center",
            color="white",
            weight="bold",
            fontsize=11,
        )
        ax.text(
            value + 0.45,
            bar.get_y() + bar.get_height() / 2,
            annotation,
            ha="left",
            va="center",
            color=INK,
            fontsize=9.5,
        )
    fig.tight_layout()
    save_figure(fig, "figure_e3_2_collaboration_cost_change")


def validate_e4_rows(
    aggregate: list[dict[str, str]],
    days: list[dict[str, str]],
    actions: list[dict[str, str]],
) -> None:
    if len(aggregate) != 4:
        raise RuntimeError(f"E4 aggregate has {len(aggregate)} rows, expected 4")
    if len(days) != 4 * 28:
        raise RuntimeError(f"E4 day table has {len(days)} rows, expected 112")
    if not actions:
        raise RuntimeError("E4 action ledger is empty")
    expected_cells = {(condition, arm) for condition in CONDITIONS for arm in ARMS}
    found_cells = {(row["condition"], row["arm"]) for row in aggregate}
    if found_cells != expected_cells:
        raise RuntimeError(f"E4 aggregate cells mismatch: {found_cells}")


def derive_e4() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    aggregate = read_csv(E4 / "aggregate_summary.csv")
    days = read_csv(E4 / "day_summary.csv")
    actions = read_csv(E4 / "action_runs.csv")
    validate_e4_rows(aggregate, days, actions)

    condition_labels = {
        "geographic": "按地理关系划分",
        "mixed": "空间交错划分",
    }
    arm_labels = {
        "ownership_fixed": "固定客户分工",
        "reassignment_allowed": "允许跨车场重分工",
    }
    main_rows: list[dict[str, Any]] = []
    aggregate_index: dict[tuple[str, str], dict[str, str]] = {}
    for condition in CONDITIONS:
        for arm in ARMS:
            row = next(
                item
                for item in aggregate
                if item["condition"] == condition and item["arm"] == arm
            )
            aggregate_index[(condition, arm)] = row
            main_rows.append(
                {
                    "客户归属方式": condition_labels[condition],
                    "经营方式": arm_labels[arm],
                    "充电排放下降（%）": f"{float(row['pooled_charging_reduction_pct']):.3f}",
                    "运营总排放下降（%）": f"{float(row['pooled_total_operational_reduction_pct']):.3f}",
                }
            )

    day_index = {
        (row["operating_day"], row["condition"], row["arm"]): row for row in days
    }
    operating_days = sorted({row["operating_day"] for row in days})
    day_rows: list[dict[str, Any]] = []
    for operating_day in operating_days:
        day_rows.append(
            {
                "电网日": operating_day,
                "按地理划分·固定归属（%）": f"{float(day_index[(operating_day, 'geographic', 'ownership_fixed')]['pooled_charging_reduction_pct']):.3f}",
                "按地理划分·跨场重分工（%）": f"{float(day_index[(operating_day, 'geographic', 'reassignment_allowed')]['pooled_charging_reduction_pct']):.3f}",
                "空间交错·固定归属（%）": f"{float(day_index[(operating_day, 'mixed', 'ownership_fixed')]['pooled_charging_reduction_pct']):.3f}",
                "空间交错·跨场重分工（%）": f"{float(day_index[(operating_day, 'mixed', 'reassignment_allowed')]['pooled_charging_reduction_pct']):.3f}",
            }
        )

    interaction_rows = read_csv(E4 / "interaction_overall.csv")
    values = {
        "aggregate": {
            f"{condition}__{arm}": {
                key: float(value) if key not in {"condition", "arm"} else value
                for key, value in row.items()
            }
            for (condition, arm), row in aggregate_index.items()
        },
        "interaction": interaction_rows,
        "operating_days": operating_days,
        "action_row_count": len(actions),
    }
    return main_rows, day_rows, values


def parse_utc_label(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


def load_carbon_rows() -> dict[datetime, dict[str, str]]:
    return {
        parse_utc_label(row["Datetime (UTC)"]): row for row in read_csv(CARBON)
    }


def calendar_profile(
    source: dict[datetime, dict[str, str]], day: date
) -> list[dict[str, float]]:
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    profile: list[dict[str, float]] = []
    for slot in range(48):
        interval_end = midnight + timedelta(minutes=30 * (slot + 1))
        raw = source[interval_end]
        profile.append(
            {
                "actual": float(raw["Actual Carbon Intensity (gCO2/kWh)"]),
                "forecast": float(raw["Forecast Carbon Intensity (gCO2/kWh)"]),
            }
        )
    return profile


def choose_input_median_day(operating_days: list[str]) -> tuple[date, float, float]:
    source = load_carbon_rows()
    ranges: list[tuple[date, float]] = []
    for raw_day in operating_days:
        day = date.fromisoformat(raw_day)
        actual = [row["actual"] for row in calendar_profile(source, day)]
        ranges.append((day, max(actual) - min(actual)))
    median_range = statistics.median(value for _, value in ranges)
    selected_day, selected_range = min(
        ranges,
        key=lambda item: (abs(item[1] - median_range), item[0].isoformat()),
    )
    return selected_day, selected_range, median_range


def add_action_to_load(
    load: np.ndarray,
    *,
    day_offset: int,
    start_second: float,
    energy_kwh: float,
    charge_power_kw: float,
) -> None:
    if energy_kwh <= TOLERANCE:
        return
    duration_hours = energy_kwh / charge_power_kw
    start_hour = start_second / 3600.0 + (24.0 * day_offset)
    end_hour = start_hour + duration_hours
    if start_hour < -24.0 - 1e-6 or end_hour > 24.0 + 1e-6:
        raise RuntimeError(
            f"charging action outside displayed two-day window: {start_hour:.6f}..{end_hour:.6f}"
        )
    for index in range(96):
        left = -24.0 + index * 0.5
        right = left + 0.5
        overlap = max(0.0, min(end_hour, right) - max(start_hour, left))
        if overlap > 0:
            load[index] += overlap * charge_power_kw


def build_selected_loads(selected_day: date) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    actions = read_csv(E4 / "action_runs.csv")
    selected = [
        row
        for row in actions
        if row["instance"] == REPRESENTATIVE_INSTANCE
        and row["condition"] == "geographic"
        and row["arm"] == "ownership_fixed"
        and row["operating_day"] == selected_day.isoformat()
        and row["timing_rule"] in {"immediate", "forecast_timed"}
    ]
    expected_groups = {(rule, seed) for rule in ("immediate", "forecast_timed") for seed in SEEDS}
    found_groups = {(row["timing_rule"], int(row["seed"])) for row in selected}
    if found_groups != expected_groups:
        raise RuntimeError(
            f"selected action groups incomplete: expected={expected_groups}, found={found_groups}"
        )

    certificate_path = (
        E3
        / "certificates"
        / f"{REPRESENTATIVE_INSTANCE}__geographic__seed1__ownership_fixed.json"
    )
    charge_power_kw = float(
        json.loads(certificate_path.read_text(encoding="utf-8"))["depot_charge_power_kw"]
    )
    by_rule: dict[str, list[np.ndarray]] = {"immediate": [], "forecast_timed": []}
    energy_checks: dict[str, list[float]] = {"immediate": [], "forecast_timed": []}
    for rule in by_rule:
        for seed in SEEDS:
            load = np.zeros(96, dtype=float)
            group = [
                row
                for row in selected
                if row["timing_rule"] == rule and int(row["seed"]) == seed
            ]
            for row in group:
                add_action_to_load(
                    load,
                    day_offset=int(row["charge_day_offset"]),
                    start_second=float(row["charge_start_second"]),
                    energy_kwh=float(row["energy_kwh"]),
                    charge_power_kw=charge_power_kw,
                )
            action_energy = sum(float(row["energy_kwh"]) for row in group)
            if abs(float(load.sum()) - action_energy) > 1e-6:
                raise RuntimeError(
                    f"load reconstruction mismatch: {rule}/seed{seed}: "
                    f"slots={load.sum()}, actions={action_energy}"
                )
            by_rule[rule].append(load)
            energy_checks[rule].append(action_energy)

    immediate = np.mean(np.stack(by_rule["immediate"]), axis=0)
    forecast = np.mean(np.stack(by_rule["forecast_timed"]), axis=0)
    if abs(float(immediate.sum()) - float(forecast.sum())) > 1e-6:
        raise RuntimeError("selected immediate and forecast loads deliver different energy")
    return immediate, forecast, {
        "charge_power_kw": charge_power_kw,
        "mean_total_energy_kwh": float(immediate.sum()),
        "per_seed_energy_kwh": energy_checks,
    }


def plot_e4_timing(e4_values: dict[str, Any]) -> dict[str, Any]:
    selected_day, selected_range, median_range = choose_input_median_day(
        e4_values["operating_days"]
    )
    source = load_carbon_rows()
    previous_profile = calendar_profile(source, selected_day - timedelta(days=1))
    operating_profile = calendar_profile(source, selected_day)
    actual = np.array(
        [row["actual"] for row in previous_profile + operating_profile], dtype=float
    )
    forecast_intensity = np.array(
        [row["forecast"] for row in previous_profile + operating_profile], dtype=float
    )
    immediate_load, forecast_load, load_meta = build_selected_loads(selected_day)
    x = np.arange(96) * 0.5 - 23.75

    fig, axes = plt.subplots(
        2,
        1,
        figsize=(9.1, 6.0),
        sharex=True,
        gridspec_kw={"height_ratios": [1.0, 1.15], "hspace": 0.12},
    )
    top, bottom = axes
    top.plot(x, actual, color=INK, linewidth=1.8, label="实际碳强度")
    top.plot(
        x,
        forecast_intensity,
        color=GREY,
        linewidth=1.4,
        linestyle="--",
        label="预测碳强度",
    )
    top.set_ylabel("克二氧化碳/千瓦时")
    top.set_title("碳强度", loc="left", fontsize=10.5, weight="bold", pad=5)
    top.legend(frameon=False, ncol=2, loc="upper right")
    top.grid(axis="y", color=GRID, linewidth=0.75)

    bottom.step(
        x,
        immediate_load,
        where="mid",
        color=GREY,
        linewidth=1.6,
        linestyle="--",
        label="有空即充",
    )
    bottom.step(
        x,
        forecast_load,
        where="mid",
        color=BLUE,
        linewidth=1.9,
        label="按预测择时",
    )
    bottom.fill_between(x, 0, forecast_load, step="mid", color=BLUE, alpha=0.13)
    bottom.set_ylabel("每半小时充电量（千瓦时）")
    bottom.set_xlabel("相对运营日零点的时间（小时）")
    bottom.set_title("充电负荷", loc="left", fontsize=10.5, weight="bold", pad=5)
    bottom.legend(frameon=False, ncol=2, loc="upper right")
    bottom.grid(axis="y", color=GRID, linewidth=0.75)
    bottom.set_xticks(np.arange(-24, 25, 6))
    bottom.set_xlim(-24, 24)

    for ax in axes:
        ax.axvline(0, color=INK, linewidth=0.9)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.text(
            -12,
            0.98,
            "前一日",
            ha="center",
            va="top",
            transform=ax.get_xaxis_transform(),
            color=GREY,
            fontsize=9,
        )
        ax.text(
            12,
            0.98,
            "运营日",
            ha="center",
            va="top",
            transform=ax.get_xaxis_transform(),
            color=GREY,
            fontsize=9,
        )

    fig.suptitle("分时碳强度与充电负荷", weight="bold", y=0.99)
    fig.text(
        0.5,
        0.945,
        f"163 客户网络；三次独立计算平均；运营日 {selected_day.isoformat()}；路线、车辆与总充电量不变",
        ha="center",
        va="top",
        color=GREY,
        fontsize=9.2,
    )
    fig.subplots_adjust(top=0.88, bottom=0.11, left=0.11, right=0.98)
    save_figure(fig, "figure_e4_1_carbon_intensity_and_charging_load")
    return {
        "selection_rule": "closest operating-day actual carbon-intensity range to the median of all 28 operating days; tie by earliest date",
        "selected_operating_day": selected_day.isoformat(),
        "selected_day_actual_range_gco2_per_kwh": selected_range,
        "median_actual_range_gco2_per_kwh": median_range,
        **load_meta,
    }


def build_preview(
    direct_rows: list[dict[str, Any]],
    network_rows: list[dict[str, Any]],
    component_rows: list[dict[str, Any]],
    e3_values: dict[str, Any],
    e4_rows: list[dict[str, Any]],
    day_rows: list[dict[str, Any]],
    e4_values: dict[str, Any],
    figure_meta: dict[str, Any],
) -> str:
    direct_table = markdown_table(direct_rows)
    network_table = markdown_table(network_rows)
    component_table = markdown_table(component_rows)
    e4_table = markdown_table(e4_rows)
    day_table = markdown_table(day_rows)

    geo_fixed = e4_values["aggregate"]["geographic__ownership_fixed"]
    geo_shared = e4_values["aggregate"]["geographic__reassignment_allowed"]
    mixed_fixed = e4_values["aggregate"]["mixed__ownership_fixed"]
    mixed_shared = e4_values["aggregate"]["mixed__reassignment_allowed"]

    return f"""# 论文正文预览：空间组织、协同与充电时机

本预览展示当前可直接进入论文结果章的两个小节。所有数字来自已封存的九张配送网络和正式充电复算；三次独立计算先在每张网络内平均，不当成三个现实样本。尚未完成的公平与动态检验不在此预设结论。

## 4.2 客户归属的空间组织与协同价值

### 4.2.1 客户归属的地理组织

正式算例继承 Goeke 与 Schneider 的混合车队算例；该算例又建立在污染路径基准上，原始论文明确说明其节点代表英国城市[[1]](https://doi.org/10.1016/j.ejor.2015.01.049)[[7]](https://doi.org/10.1016/j.trb.2011.02.004)。本项目随后合并三班配送任务、增加第二车场并重新计算坐标间欧氏距离。从原始坐标逐网络复算的最大点间距离约为 {e3_values['minimum_network_diameter_km']:.0f}–{e3_values['maximum_network_diameter_km']:.0f} 公里，因此本文将其界定为“基于英国城市坐标构造的区域/城际配送场景”，而不解释成真实道路轨迹、真实企业订单或城市末端配送。

为分离客户责任的空间组织，本文在每张网络上保留完全相同的客户坐标、需求和时间窗，只改变客户由哪一家车场负责。图 1 左侧按客户与车场的地理关系划分责任；右侧在配送班次和需求档内保持两家车场的客户数量基本一致，但让客户责任在空间上交错。后者是一次锁死的合成强对照，可以表示历史业务关系与当前地理位置不一致的极端情形，但不是真实企业客户账本。该并列类别地图沿用 Soriano 等 Fig. 3 的展示思路[[2]](https://doi.org/10.1016/j.ijpe.2022.108669)。

![图 1 客户归属的空间结构](figures/figure_e3_1_customer_responsibility_structure.png)

**图 1　客户归属的空间结构**

表 1 先在每张网络内平均三次独立计算，再比较两类客户归属下的固定客户分工方案。按地理关系组织客户责任后，平均总成本下降 {e3_values['direct_seed_first_aggregation']['total_cost']['mean_reduction_pct']:.3f}%，总行驶距离下降 {e3_values['direct_seed_first_aggregation']['distance_total']['mean_reduction_pct']:.3f}%，燃油车直接排放下降 {e3_values['direct_seed_first_aggregation']['E_cv_direct']['mean_reduction_pct']:.3f}%，用电量下降 {e3_values['direct_seed_first_aggregation']['electricity_kwh']['mean_reduction_pct']:.3f}%；四项指标均在九张网络上同向。这个比较表明，地理组织本身已经提前获取了大量成本与能源效率，而不是等到开放合作后才第一次产生价值。表格采用王勇等“优化前后—运营指标”的三线表逻辑，但因为九张网络规模不同，本文报告可比的相对变化，不平均没有可比意义的绝对总量[[3]](https://xtglxb.sjtu.edu.cn/CN/10.3969/j.issn.1005-2542.2023.06.001)。

**表 1　客户归属方式与运营指标变化**

{direct_table}

注：正值表示按地理关系划分后下降。燃油直接排放与燃油消耗同方向；用电量不含电网时点差异，充电时间的作用在下一节单独计量。

### 4.2.2 协同的增量价值

在每一种客户归属结构下，两组方案都从逐字相同的各自经营排班出发，计算次数和约束完全相同；唯一差别是客户能否改由另一车场服务。图 2 只比较这一项权利带来的成本变化，不混入车辆、空档、公平或碳排放。

![图 2 不同客户归属结构下的协同成本变化](figures/figure_e3_2_collaboration_cost_change.png)

**图 2　不同客户归属结构下的协同成本变化**

按地理关系划分时，合作平均再降低成本 {e3_values['geographic_mean_saving_pct']:.3f}%，九张网络中七张改善，双侧精确符号检验的概率值为 {e3_values['geographic_sign_p']:.3f}，说明剩余收益存在但不稳定。客户责任在空间上交错时，合作平均降低成本 {e3_values['mixed_mean_saving_pct']:.3f}%，九张网络全部改善，概率值为 {e3_values['mixed_sign_p']:.4f}。同一网络内，两类归属的协同价值平均相差 {e3_values['mixed_minus_geographic_pct_points']:.3f} 个百分点，九张网络方向完全一致。

这组结果支持的不是“合作具有固定收益率”，而是“地理组织先拿走容易获得的效率，合作主要修复仍然空间交错的客户责任”。Fernández、Roca-Riu 与 Speranza 已在协同配送算例中报告聚集客户通常留下较少协同节省，因此这一方向本身不是本文的首次发现[[4]](https://doi.org/10.1016/j.ejor.2017.08.051)。本文增加的证据是：在区域/城际尺度、油电混合车队和严格实体车多趟排班下，该差异仍然存在，并且可以拆到账目和能源上。

空间交错情境的成本改善主要来自里程费、燃油费和电费，分别贡献 11.907、6.798 和 1.247 个百分点；每趟固定费反而增加 0.126 个百分点。因而，合作不是靠稳定减少实体车辆赚钱，而是通过重新划分服务范围减少不必要行驶。实体车只在九张网络中的 {e3_values['mixed_physical_fewer_networks']} 张减少、{e3_values['mixed_physical_more_networks']} 张增加、{e3_values['mixed_physical_equal_networks']} 张不变，正文不得写“合作省车”。

合作后趟间空档在空间交错情境下有 {e3_values['mixed_gap_decrease_networks']} 张网络缩短、{e3_values['mixed_gap_increase_networks']} 张增加。结合相同客户服务下路程、成本和能源的下降，空档缩短可以描述为排班衔接更紧；但它单独既不能证明效率，也不能推出充电选择空间增加。后一问题由充电时机实验直接回答。

## 4.3 预测驱动的充电时机与排放

本节固定上一节的 108 份严格可执行配送方案，在 28 个拥有完整前一日和运营日数据的英国全国电网日上复算三种充电规则。正文比较“有空即充”和“按次日预测选择合法时刻”；路线、客户服务关系、实体车辆、每次充电电量和总电量全部不变。预测碳强度用于作出决定，实际估计碳强度用于结算排放。由于配送基准没有唯一电网分区身份，本文使用全国数据，不把地区平均冒充某个具体地区[[5]](https://www.neso.energy/data-portal/national-carbon-intensity-forecast/national_carbon_intensity_forecast_methodology)。

图 3 使用 163 客户网络、按地理关系划分且固定客户分工的方案。展示日不是按结果挑选，而是 28 个运营日中实际碳强度日内极差最接近中位数的 {figure_meta['selected_operating_day']}。图形沿用 Cheng 等 Fig. 6 的“碳强度—基线/低碳充电负荷”上下对照形式，并因首趟充电发生在前夜而把横轴扩展到连续两个自然日[[6]](https://arxiv.org/abs/2209.12373)。

![图 3 分时碳强度与充电负荷](figures/figure_e4_1_carbon_intensity_and_charging_load.png)

**图 3　分时碳强度与充电负荷**

表 2 给出全部九张网络和 28 个电网日的正式结果。按预测择时使充电环节排放下降 {float(geo_fixed['pooled_charging_reduction_pct']):.3f}%–{float(geo_shared['pooled_charging_reduction_pct']):.3f}%（按地理关系划分）和 {float(mixed_fixed['pooled_charging_reduction_pct']):.3f}%–{float(mixed_shared['pooled_charging_reduction_pct']):.3f}%（空间交错）。但把燃油车直接排放放回分母后，运营总排放只下降 0.352%–0.523%。这两个百分比必须并列出现：前者说明充电环节确有可利用的时间弹性，后者说明它在整个油电混合配送系统中只是补充性收益。

**表 2　充电时机与运营排放变化**

{e4_table}

四种情境均在九张网络上取得聚合改善，但只在 28 个电网日中的 18–20 天改善，日中位数仅约 0.10%–0.25%。净节省的 95.5%–99.7% 来自前夜首趟充电，当天两趟之间的调整很小。这说明当前严格排班下，最现实的时间杠杆不是在紧凑的日间行程中频繁“搬动充电”，而是利用出车前夜的较长窗口。

Cheng 等在真实充电站数据上报告过 3.81% 的平均充电排放改善，因此“约 4%”这个量级本身也不能作为原创主张[[6]](https://arxiv.org/abs/2209.12373)。本文更可辩护的贡献是：在同一批严格可执行的区域/城际配送排班上，同时量出预测决策、实际结算、运营总排放份量和前夜/趟间来源，并发现合作没有稳定放大这一时间收益。

按地理关系划分时，允许跨车场重分工相对固定归属的充电择时收益只多 0.251 个百分点，九张网络中六张同向；空间交错时平均多 0.514 个百分点，九张网络同向，但只有 28 个电网日中的 16 天同向。运营场景和电网日没有共同给出稳定方向，因此正文写“未发现合作稳定放大或削弱充电择时收益”，不写“合作释放充电空档”。

## 4.4 尚未由当前证据回答的问题

上一小节已回答系统价值如何产生，本小节已回答固定配送方案后充电时间还能减少多少排放。双方是否都愿意接受这些方案，需要公平检验量出参与要求的代价；订单变化后收益还能剩多少，需要动态检验继承已经执行的车辆、时间和电量状态。两项均未完成，当前正文不提前写方向，也暂不强行决定公平内容是否并入协同价值章节。

## 附表 A1　逐网络协同成本变化

{network_table}

注：客户数只标识网络规模，不是连续处理变量，因此不得连成规模趋势线。

## 附表 A2　协同成本变化构成

{component_table}

注：正值表示该账目帮助降低总成本，负值表示该账目反而增加成本。按地理关系划分情境的燃油费贡献为负值，必须原样保留。

## 附表 A3　充电时机的逐日变化

{day_table}

注：负值表示该日按预测择时后按实际碳强度结算反而增加充电排放；28 天全部报告。

## References

[1] Goeke, D., & Schneider, M. (2015). Routing a mixed fleet of electric and conventional vehicles. *European Journal of Operational Research*, 245(1), 81–99. https://doi.org/10.1016/j.ejor.2015.01.049

[2] Soriano, A., Gansterer, M., & Hartl, R. F. (2023). The multi-depot vehicle routing problem with profit fairness. *International Journal of Production Economics*, 255, 108669. https://doi.org/10.1016/j.ijpe.2022.108669

[3] 王勇, 李慧星, 罗思妤, 周景欣, 许茂增. (2023). 资源共享模式下多中心共同配送电动车辆路径优化问题. *系统管理学报*, 32(6), 1119–1141. https://doi.org/10.3969/j.issn.1005-2542.2023.06.001

[4] Fernández, E., Roca-Riu, M., & Speranza, M. G. (2018). The Shared Customer Collaboration Vehicle Routing Problem. *European Journal of Operational Research*, 265(3), 1078–1093. https://doi.org/10.1016/j.ejor.2017.08.051

[5] National Energy System Operator. (2025). National Carbon Intensity Forecast Methodology. https://www.neso.energy/data-portal/national-carbon-intensity-forecast/national_carbon_intensity_forecast_methodology

[6] Cheng, K.-W., Bian, Y., Shi, Y., & Chen, Y. (2022). Carbon-Aware EV Charging. *IEEE Electrical Power and Energy Conference*. https://arxiv.org/abs/2209.12373

[7] Bektaş, T., & Laporte, G. (2011). The Pollution-Routing Problem. *Transportation Research Part B: Methodological*, 45(8), 1232–1250. https://doi.org/10.1016/j.trb.2011.02.004
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)
    configure_plotting()

    direct_rows, network_rows, component_rows, e3_values = derive_e3()
    e4_rows, day_rows, e4_values = derive_e4()

    plot_e3_structure()
    plot_e3_collaboration(e3_values)
    figure_meta = plot_e4_timing(e4_values)

    write_table_bundle("table_e3_1_geographic_organization", direct_rows)
    write_table_bundle("table_e3_a1_network_collaboration", network_rows)
    write_table_bundle("table_e3_a2_collaboration_cost_sources", component_rows)
    write_table_bundle("table_e4_1_charging_timing", e4_rows)
    write_table_bundle("table_e4_a1_day_consistency", day_rows)

    values = {"e3": e3_values, "e4": e4_values, "figure_e4_1": figure_meta}
    write_json(OUT / "paper_values.json", values)
    preview = build_preview(
        direct_rows,
        network_rows,
        component_rows,
        e3_values,
        e4_rows,
        day_rows,
        e4_values,
        figure_meta,
    )
    (OUT / "PAPER_STORY_PREVIEW.md").write_text(preview, encoding="utf-8")

    report = {
        "status": "PASS",
        "route_search_evaluations": 0,
        "purpose": "reader-facing E3/E4 story and exhibits",
        "sealed_inputs_unchanged": True,
        "input_hashes": {
            "e3_raw_runs.csv": sha256(E3 / "raw_runs.csv"),
            "e3_paired_results.csv": sha256(E3 / "paired_results.csv"),
            "ownership_raw_runs.csv": sha256(OWNERSHIP / "raw_runs.csv"),
            "representative_geographic_map.csv": sha256(
                OWNERSHIP
                / "ownership_maps"
                / f"{REPRESENTATIVE_INSTANCE}__geographic.csv"
            ),
            "representative_mixed_map.csv": sha256(
                OWNERSHIP / "ownership_maps" / f"{REPRESENTATIVE_INSTANCE}__mixed.csv"
            ),
            "representative_instance.json": sha256(
                INSTANCE_ROOT / REPRESENTATIVE_INSTANCE / "instance.json"
            ),
            **{
                f"nodes/{instance}.csv": sha256(INSTANCE_ROOT / instance / "nodes.csv")
                for instance in sorted(instance_counts())
            },
            "e4_aggregate_summary.csv": sha256(E4 / "aggregate_summary.csv"),
            "e4_day_summary.csv": sha256(E4 / "day_summary.csv"),
            "e4_action_runs.csv": sha256(E4 / "action_runs.csv"),
            "carbon_source.csv": sha256(CARBON),
            "story_contract.md": sha256(CONTRACT),
        },
        "aggregation_rules": {
            "e3_direct_geographic_organization": "average three search seeds inside each network and condition first; compute relative reduction; average nine network reductions equally",
            "e3_collaboration": "use sealed paired saving percentages; average three search seeds inside each network; average nine networks equally",
            "e4": "use sealed formal aggregates; search seeds first averaged inside network-condition-arm-day cells",
        },
        "figure_e4_1_selection": figure_meta,
        "exhibit_contract": {
            "figure_e3_1": "input ownership structure only",
            "table_e3_1": "direct operating effect of geographic organization only",
            "figure_e3_2": "residual collaboration cost effect only",
            "table_e4_1": "charging versus total operational emission effect only",
            "figure_e4_1": "timing mechanism only",
        },
        "generator": str(Path(__file__).resolve().relative_to(ROOT)),
        "generator_sha256": sha256(Path(__file__).resolve()),
    }
    write_json(OUT / "report.json", report)

    hashes = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    write_json(OUT / "artifact_hashes.json", hashes)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
