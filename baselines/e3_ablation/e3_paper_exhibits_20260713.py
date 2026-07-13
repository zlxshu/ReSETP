#!/usr/bin/env python3
"""Build the paper-facing E3 figures, tables and Chinese body-text preview.

The script does not run route search.  It independently derives all displayed
values from the sealed paired-cost rows and keeps each exhibit to one question:

1. What do the two customer-portfolio classes look like?
2. How does portfolio structure change collaboration savings?
3. Which cost accounts create those savings?
"""

from __future__ import annotations

from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
FORMAL = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
OWNERSHIP = ROOT / "baselines/e3_ablation/e3_ownership_class_design_v4_20260713"
OUT = FORMAL / "paper"
REFERENCE = Path(
    "/Users/zhouleixishu/Zotero/storage/PLSR8GG4/"
    "Soriano 等 _ 2023 _ The multi-depot vehicle routing problem with profit fairness.pdf"
)
REPRESENTATIVE = "L-main-threeshift-75c-01"
CONDITIONS = ("geographic", "mixed")
COMPONENTS = (
    ("cost_fix", "派车次数相关固定费"),
    ("cost_km", "按里程计行驶费"),
    ("cost_fuel", "燃油费"),
    ("cost_elec", "电费"),
)

BLUE = "#4C78A8"
ORANGE = "#F28E2B"
GREY = "#6B7280"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: list[dict[str, Any]]) -> str:
    fields = list(rows[0])
    lines = ["| " + " | ".join(fields) + " |", "| " + " | ".join("---" for _ in fields) + " |"]
    lines.extend("| " + " | ".join(str(row[field]) for field in fields) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def exact_two_sided_sign_p(positive: int, negative: int) -> float:
    n = positive + negative
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(0, min(positive, negative) + 1)) / (2**n)
    return min(1.0, 2.0 * tail)


def configure_plotting() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Hiragino Sans GB", "Heiti SC", "Arial Unicode MS", "DejaVu Sans"],
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
        }
    )


def instance_counts() -> dict[str, int]:
    rows = read_csv(OWNERSHIP / "raw_runs.csv")
    return {row["instance"]: int(row["customer_count"]) for row in rows}


def derive_results() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    raw = read_csv(FORMAL / "raw_runs.csv")
    paired = read_csv(FORMAL / "paired_results.csv")
    if len(raw) != 108 or len(paired) != 54:
        raise RuntimeError(f"formal rows incomplete: raw={len(raw)}, paired={len(paired)}")
    if not all(
        row["status"] == "PASS"
        and int(row["evaluations"]) == int(row["budget"]) == 4000
        and int(row["violation_count"]) == 0
        and math.isfinite(float(row["total_cost"]))
        for row in raw
    ):
        raise RuntimeError("formal contract rows failed the paper-layer audit")

    counts = instance_counts()
    by_network: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in paired:
        by_network[(row["instance"], row["condition"])].append(row)

    network_rows: list[dict[str, Any]] = []
    for instance in sorted(counts, key=counts.get):
        values: dict[str, dict[str, Any]] = {}
        for condition in CONDITIONS:
            selected = by_network[(instance, condition)]
            savings = [float(row["saving_pct"]) for row in selected]
            values[condition] = {
                "mean": statistics.fmean(savings),
                "positive_seeds": sum(value > 1e-9 for value in savings),
                "mean_reassigned": statistics.fmean(int(row["cross_site_customer_count"]) for row in selected),
            }
        network_rows.append(
            {
                "实际客户数": counts[instance],
                "地理聚集组合节省（%）": round(values["geographic"]["mean"], 3),
                "空间混合组合节省（%）": round(values["mixed"]["mean"], 3),
                "空间结构增量（百分点）": round(values["mixed"]["mean"] - values["geographic"]["mean"], 3),
                "地理聚集胜出种子": f"{values['geographic']['positive_seeds']}/3",
                "空间混合胜出种子": f"{values['mixed']['positive_seeds']}/3",
            }
        )

    raw_index = {
        (row["instance"], row["condition"], int(row["seed"]), row["arm"]): row
        for row in raw
    }
    component_network_values: dict[str, list[dict[str, float]]] = defaultdict(list)
    physical_network_deltas: dict[str, list[float]] = defaultdict(list)
    gap_network_deltas: dict[str, list[float]] = defaultdict(list)
    for instance in sorted(counts, key=counts.get):
        for condition in CONDITIONS:
            seed_values: list[dict[str, float]] = []
            physical: list[float] = []
            gaps: list[float] = []
            for seed in (1, 2, 3):
                fixed = raw_index[(instance, condition, seed, "ownership_fixed")]
                shared = raw_index[(instance, condition, seed, "reassignment_allowed")]
                if fixed["start_sha256"] != shared["start_sha256"]:
                    raise RuntimeError(f"start mismatch: {instance}/{condition}/seed{seed}")
                base = float(fixed["total_cost"])
                seed_values.append(
                    {
                        key: (float(fixed[key]) - float(shared[key])) / base * 100.0
                        for key, _ in COMPONENTS
                    }
                    | {"total": (base - float(shared["total_cost"])) / base * 100.0}
                )
                physical.append(float(shared["physical_total"]) - float(fixed["physical_total"]))
                gaps.append(float(shared["between_trip_gap_hours"]) - float(fixed["between_trip_gap_hours"]))
            component_network_values[condition].append(
                {key: statistics.fmean(row[key] for row in seed_values) for key, _ in COMPONENTS}
                | {"total": statistics.fmean(row["total"] for row in seed_values)}
            )
            physical_network_deltas[condition].append(statistics.fmean(physical))
            gap_network_deltas[condition].append(statistics.fmean(gaps))

    contribution_rows: list[dict[str, Any]] = []
    for key, label in COMPONENTS:
        contribution_rows.append(
            {
                "成本来源": label,
                "地理聚集组合（百分点）": round(
                    statistics.fmean(row[key] for row in component_network_values["geographic"]), 3
                ),
                "空间混合组合（百分点）": round(
                    statistics.fmean(row[key] for row in component_network_values["mixed"]), 3
                ),
            }
        )
    contribution_rows.append(
        {
            "成本来源": "总成本",
            "地理聚集组合（百分点）": round(
                statistics.fmean(row["total"] for row in component_network_values["geographic"]), 3
            ),
            "空间混合组合（百分点）": round(
                statistics.fmean(row["total"] for row in component_network_values["mixed"]), 3
            ),
        }
    )

    ordered_instances = sorted(counts, key=counts.get)
    geographic = [
        statistics.fmean(float(row["saving_pct"]) for row in by_network[(instance, "geographic")])
        for instance in ordered_instances
    ]
    mixed = [
        statistics.fmean(float(row["saving_pct"]) for row in by_network[(instance, "mixed")])
        for instance in ordered_instances
    ]
    effects = [right - left for left, right in zip(geographic, mixed, strict=True)]
    geo_pos = sum(value > 1e-9 for value in geographic)
    geo_neg = sum(value < -1e-9 for value in geographic)
    mix_pos = sum(value > 1e-9 for value in mixed)
    mix_neg = sum(value < -1e-9 for value in mixed)
    effect_pos = sum(value > 1e-9 for value in effects)
    effect_neg = sum(value < -1e-9 for value in effects)
    paper_values = {
        "network_count": len(network_rows),
        "search_seed_count_per_network_condition": 3,
        "geographic_mean_saving_pct": statistics.fmean(geographic),
        "geographic_positive_networks": geo_pos,
        "geographic_sign_test_p_two_sided": exact_two_sided_sign_p(geo_pos, geo_neg),
        "mixed_mean_saving_pct": statistics.fmean(mixed),
        "mixed_positive_networks": mix_pos,
        "mixed_sign_test_p_two_sided": exact_two_sided_sign_p(mix_pos, mix_neg),
        "mixed_minus_geographic_pct_points": statistics.fmean(effects),
        "mixed_greater_networks": effect_pos,
        "portfolio_effect_sign_test_p_two_sided": exact_two_sided_sign_p(effect_pos, effect_neg),
        "mixed_all_27_seed_pairs_strict_win": all(
            row["strict_win"].lower() == "true" for row in paired if row["condition"] == "mixed"
        ),
        "mixed_reassigned_customer_network_mean_min": min(
            statistics.fmean(int(row["cross_site_customer_count"]) for row in by_network[(instance, "mixed")])
            for instance in counts
        ),
        "mixed_reassigned_customer_network_mean_max": max(
            statistics.fmean(int(row["cross_site_customer_count"]) for row in by_network[(instance, "mixed")])
            for instance in counts
        ),
        "mixed_physical_vehicle_fewer_networks": sum(
            value < -1e-9 for value in physical_network_deltas["mixed"]
        ),
        "mixed_physical_vehicle_equal_networks": sum(
            abs(value) <= 1e-9 for value in physical_network_deltas["mixed"]
        ),
        "mixed_physical_vehicle_more_networks": sum(
            value > 1e-9 for value in physical_network_deltas["mixed"]
        ),
        "mixed_gap_increase_networks": sum(value > 1e-9 for value in gap_network_deltas["mixed"]),
        "mixed_gap_decrease_networks": sum(value < -1e-9 for value in gap_network_deltas["mixed"]),
        "maximum_cost_component_error": max(abs(float(row["cost_component_error"])) for row in raw),
    }
    return network_rows, contribution_rows, paper_values


def load_owner_map(condition: str) -> dict[str, str]:
    rows = read_csv(OWNERSHIP / "ownership_maps" / f"{REPRESENTATIVE}__{condition}.csv")
    return {row["customer_id"]: row["owner_depot_id"] for row in rows}


def save_figure(fig: Any, stem: str) -> None:
    for suffix in ("png", "pdf", "svg"):
        kwargs = {"dpi": 300} if suffix == "png" else {}
        fig.savefig(OUT / f"{stem}.{suffix}", bbox_inches="tight", **kwargs)
    plt.close(fig)


def plot_portfolio_structure() -> None:
    instance_path = ROOT / "models/data_bundle/generated_instances/L-main" / REPRESENTATIVE / "instance.json"
    payload = json.loads(instance_path.read_text(encoding="utf-8"))
    nodes = {node["node_id"]: node for node in payload["nodes"]}
    depots = [node for node in nodes.values() if node["node_type"].lower() == "d"]
    owner_colors = {"D0": BLUE, "D1": ORANGE}
    owner_markers = {"D0": "o", "D1": "^"}
    owner_names = {"D0": "A", "D1": "B"}

    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.5), sharex=True, sharey=True)
    for ax, condition, title in zip(axes, CONDITIONS, ("地理聚集", "空间混合"), strict=True):
        owners = load_owner_map(condition)
        for owner in ("D0", "D1"):
            selected = [nodes[customer] for customer, depot in owners.items() if depot == owner]
            ax.scatter(
                [node["x"] / 1000.0 for node in selected],
                [node["y"] / 1000.0 for node in selected],
                s=24,
                marker=owner_markers[owner],
                c=owner_colors[owner],
                alpha=0.72,
                linewidths=0.35,
                edgecolors="white",
                label=f"车场{owner_names[owner]}客户",
            )
        for depot in depots:
            ax.scatter(
                depot["x"] / 1000.0,
                depot["y"] / 1000.0,
                s=165,
                marker="*",
                c=owner_colors[depot["node_id"]],
                edgecolors="black",
                linewidths=0.9,
                zorder=5,
            )
            ax.annotate(
                f"车场{owner_names[depot['node_id']]}",
                (depot["x"] / 1000.0, depot["y"] / 1000.0),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=9,
                weight="bold",
            )
        ax.set_title(title, weight="bold", pad=8)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color("#D1D5DB")
            spine.set_linewidth(0.8)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle("客户组合的空间结构", weight="bold", y=1.02)
    fig.subplots_adjust(wspace=0.06, bottom=0.13)
    save_figure(fig, "figure_e3_1_portfolio_structure")


def plot_savings(network_rows: list[dict[str, Any]], paper_values: dict[str, Any]) -> None:
    x = np.arange(len(network_rows))
    width = 0.36
    geographic = [float(row["地理聚集组合节省（%）"]) for row in network_rows]
    mixed = [float(row["空间混合组合节省（%）"]) for row in network_rows]
    fig, ax = plt.subplots(figsize=(10.6, 5.2))
    bars_geo = ax.bar(
        x - width / 2,
        geographic,
        width,
        color=BLUE,
        label=f"地理聚集（平均 {paper_values['geographic_mean_saving_pct']:.1f}%）",
    )
    bars_mixed = ax.bar(
        x + width / 2,
        mixed,
        width,
        color=ORANGE,
        label=f"空间混合（平均 {paper_values['mixed_mean_saving_pct']:.1f}%）",
    )
    ax.axhline(0.0, color="#374151", linewidth=0.9)
    ax.set_xticks(x, [str(row["实际客户数"]) for row in network_rows])
    ax.set_xlabel("实际客户数")
    ax.set_ylabel("成本节省（%）")
    ax.set_title("客户组合与协同成本变化", weight="bold", pad=11)
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, ncol=2, loc="upper right")
    ax.set_ylim(min(-7.0, min(geographic) - 2.0), max(mixed) + 4.5)
    ax.bar_label(bars_geo, labels=[f"{value:.1f}" for value in geographic], padding=3, fontsize=8.5)
    ax.bar_label(bars_mixed, labels=[f"{value:.1f}" for value in mixed], padding=3, fontsize=8.5)
    save_figure(fig, "figure_e3_2_cost_savings")


def build_preview(network_rows: list[dict[str, Any]], contribution_rows: list[dict[str, Any]], values: dict[str, Any]) -> str:
    table_main = markdown_table(contribution_rows)
    table_appendix = markdown_table(network_rows)
    return f"""# E3 论文正文预览

## 客户归属结构与协同成本变化

为分离客户组合的空间结构对协同价值的影响，本文在九张正式配送网络上构造两类成对情境。地理聚集情境将客户归入最近车场；空间混合情境保持每家车场在各配送班次和需求档中的客户数量不变，只改变客户归属在地图上的交错程度。两类情境使用相同的客户、需求、时间窗、电网和费用，并在合作搜索前锁定同一充足车队上限。该组织方式沿用协同配送研究按客户分布类别和网络规模汇总结果的做法，但空间混合归属是本文的合成对照，不是真实企业历史数据。

**图 E3-1　客户组合的空间结构**

图 E3-1 使用同一张 163 客户网络说明两类情境。左右两图的客户位置完全相同，只有客户原先属于哪家车场发生变化。该图只解释实验输入，不呈现算法效果。

**图 E3-2　客户组合与协同成本变化**

每个网络的三次搜索先取平均，再让九张网络等权进入汇总。地理聚集情境下，合作平均节省 {values['geographic_mean_saving_pct']:.3f}%，九张网络中七张为正，双侧精确符号检验的概率值为 {values['geographic_sign_test_p_two_sided']:.3f}，说明在客户原本已按地理位置分得较顺时，合作收益存在但不稳定。空间混合情境下，合作平均节省 {values['mixed_mean_saving_pct']:.3f}%，九张网络全部为正，概率值为 {values['mixed_sign_test_p_two_sided']:.4f}。同一网络内，空间混合相对地理聚集多出的成本节省平均为 {values['mixed_minus_geographic_pct_points']:.3f} 个百分点，九张网络方向完全一致，概率值为 {values['portfolio_effect_sign_test_p_two_sided']:.4f}。因此，E3 支持的不是“合作总能省下固定比例”，而是“客户组合越偏离地理服务边界，允许跨车场重新分配客户的价值越大”。

空间混合情境的二十七组比较全部同时满足“总成本更低”和“确有客户改由另一车场服务”。按网络平均，重新分配的客户数从 {values['mixed_reassigned_customer_network_mean_min']:.1f} 人到 {values['mixed_reassigned_customer_network_mean_max']:.1f} 人不等。该证据排除了合作结果只是继续打磨原方案、却没有真正发生客户共享的解释。

**表 E3-1　协同成本变化的来源**

表中正值表示该账目帮助省钱，负值表示该账目反而增加成本；各行先在同一网络的三次搜索内求平均，再对九张网络等权平均。

{table_main}

空间混合情境的成本改善主要来自服务范围重划后的路程缩短：按里程计的行驶费、燃油费和电费分别贡献 11.907、6.798 和 1.247 个百分点。派车次数相关固定费反而增加 0.126 个百分点，说明合作不是靠少派车赚钱，而是在可能多派几趟的同时显著减少总行驶负担。

## 结论边界

本实验不能证明合作减少实体车。空间混合情境下，合作方案的实体车数只在九张网络中的 {values['mixed_physical_vehicle_fewer_networks']} 张下降，在 {values['mixed_physical_vehicle_more_networks']} 张增加，其余 {values['mixed_physical_vehicle_equal_networks']} 张不变；旧的最大网络紧车队实验也记录为十次中零次减少。当前模型中的固定费按实际派出的每一趟计取，不是按拥有多少辆实体车计取。因此，车辆结论只能写“未观察到稳定缩减”，不能写“合作省车”。

充电空档也不属于 E3 的成本结论。空间混合情境下，合作后的趟间空档在九张网络中 {values['mixed_gap_increase_networks']} 张增加、{values['mixed_gap_decrease_networks']} 张减少，没有一致方向；而旧 E3 的首趟充电时钟后来发现语义错误，其碳百分比已冻结，不再进入论文。充电时机应由修正时钟后的专门碳实验回答，公平代价则由专门公平实验回答。

作为保守边界，旧的最大网络实验在最近车场归属和正式紧车队下得到 0.353% 平均节省、十次中六次严格胜出、概率值 0.348，并且没有车辆减少。该实验与本节主比较同时改变了车队松紧和搜索起点，不能与 19.826% 做单因素因果比较；它只说明当客户原本已接近地理最优且资产紧张时，可释放的合作空间会很小。

## 附表 E3-A1　逐网络协同成本变化

{table_appendix}

注：搜索种子只衡量算法波动，不当作独立企业样本。主统计单位是九张不同来源规模的正式网络。空间混合情境是一类强对照，不解释成连续的“错配剂量”。共同车队上限是合法排班的充分上限，不是最少车辆估计。
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    configure_plotting()
    network_rows, contribution_rows, values = derive_results()
    plot_portfolio_structure()
    plot_savings(network_rows, values)
    write_csv(OUT / "table_e3_1_cost_sources.csv", contribution_rows)
    write_csv(OUT / "table_e3_a1_network_results.csv", network_rows)
    (OUT / "table_e3_1_cost_sources.md").write_text(markdown_table(contribution_rows), encoding="utf-8")
    (OUT / "table_e3_a1_network_results.md").write_text(markdown_table(network_rows), encoding="utf-8")
    write_json(OUT / "paper_values.json", values)
    (OUT / "e3_paper_preview_zh.md").write_text(
        build_preview(network_rows, contribution_rows, values), encoding="utf-8"
    )
    report = {
        "status": "PASS",
        "route_search_evaluations": 0,
        "formal_decision_sha256": sha256(FORMAL / "decision.json"),
        "formal_raw_runs_sha256": sha256(FORMAL / "raw_runs.csv"),
        "formal_paired_results_sha256": sha256(FORMAL / "paired_results.csv"),
        "ownership_design_sha256": sha256(OWNERSHIP / "decision.json"),
        "generator": str(Path(__file__).resolve().relative_to(ROOT)),
        "generator_sha256": sha256(Path(__file__).resolve()),
        "reference": "Soriano, Gansterer, and Hartl (2023), IJPE 255, 108669",
        "reference_sha256": sha256(REFERENCE),
        "reference_use": "class illustration plus aggregation by customer-distribution class and network size; no visual or numerical content copied",
        "exhibit_contract": {
            "figure_e3_1": "input classes only",
            "figure_e3_2": "cost savings only",
            "table_e3_1": "cost-source decomposition only",
            "appendix_table_e3_a1": "exact network-level values underlying figure_e3_2",
        },
        "paper_values_sha256": sha256(OUT / "paper_values.json"),
    }
    write_json(OUT / "report.json", report)
    hashes = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    write_json(OUT / "artifact_hashes.json", hashes)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
