#!/usr/bin/env python3
"""Build SETP-facing E2/E3 figures and tables from sealed evidence only."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
import pandas as pd
from fontTools.ttLib import TTCollection

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/paper_submission_final/e2_e3_preview_20260714"
FIG, TAB = OUT / "figures", OUT / "tables"
E2 = ROOT / "baselines/e2_alns/e2_final_10seed_20260711/formal"
E2_CURVES = ROOT / "baselines/e2_alns/e2_final_10seed_20260711/figures/f2_convergence_curves.csv"
E3 = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
E3_DESIGN = ROOT / "baselines/e3_ablation/e3_ownership_class_design_v4_20260713"
REPRESENTATIVE = "L-main-threeshift-75c-01"

NAMES = {
    "staged_hybrid_carbon_aware": "TVCI-ALNS", "GA": "遗传算法", "PSO": "粒子群算法",
    "VNS": "变邻域搜索", "ACO": "蚁群算法", "GA-VNS": "遗传-变邻域算法",
    "LNS": "大邻域搜索", "GWO": "灰狼算法", "IWD": "简化水滴算法",
}


def configure() -> None:
    # Matplotlib otherwise selects the first face (Black) in Apple's Songti TTC.
    # Extract the regular face to a temporary file so the published figure embeds
    # an actual Song regular font. The font file itself is never copied to the repo.
    songti_ttc = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    songti_regular = Path(tempfile.gettempdir()) / "resetp-songti-sc-regular.ttf"
    if songti_ttc.exists() and not songti_regular.exists():
        TTCollection(songti_ttc).fonts[6].save(songti_regular)
    if songti_regular.exists():
        font_manager.fontManager.addfont(songti_regular)
    plt.rcParams.update({
        # Chen et al. (2023, SETP) uses Times for Latin/numerals and Song for Chinese.
        # Matplotlib falls through this family list glyph by glyph.
        "font.family": ["Times New Roman", "Songti SC"],
        "font.size": 6.62, "axes.labelsize": 6.62, "axes.titlesize": 6.62,
        "xtick.labelsize": 6.62, "ytick.labelsize": 6.62, "legend.fontsize": 6.3,
        "axes.unicode_minus": False, "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "pdf.fonttype": 42, "ps.fonttype": 42,
    })


def save(fig: plt.Figure, stem: str) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(FIG / f"{stem}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def write_e2_tables() -> None:
    TAB.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(E2 / "algorithm_summary.csv").sort_values("mean_rank_by_instance_avg")
    pair = pd.read_csv(E2 / "paired_wilcoxon.csv").set_index("baseline")
    lines = [r"\begin{tabular}{lrrrrr}", r"\toprule",
             r"算法 & 综合成本 & 平均名次 & 最优次数 & 平均耗时/s & 相对改进/\% \\",
             r"\midrule"]
    for row in df.itertuples(index=False):
        gain = "---" if row.algorithm == "staged_hybrid_carbon_aware" else f"{pair.loc[row.algorithm, 'mean_gain_pct']:.2f}"
        lines.append(f"{NAMES[row.algorithm]} & {row.sum_of_instance_avg_costs:,.1f} & "
                     f"{row.mean_rank_by_instance_avg:.2f} & {int(row.best_instance_avg_count)} & "
                     f"{row.mean_runtime_seconds:.1f} & {gain} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TAB / "e2_algorithm_summary.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    df = pd.read_csv(E2 / "paired_wilcoxon.csv")
    lines = [r"\begin{tabular}{lrrrrr}", r"\toprule",
             r"对比算法 & 胜/平/负 & 平均改进/\% & 中位改进/\% & 校正后$p$值 & 结论 \\",
             r"\midrule"]
    for row in df.itertuples(index=False):
        conclusion = "显著" if row.wilcoxon_p_holm < 0.05 else "不显著"
        lines.append(f"{NAMES[row.baseline]} & {row.wins}/{row.ties}/{row.losses} & "
                     f"{row.mean_gain_pct:.2f} & {row.median_gain_pct:.2f} & "
                     f"{row.wilcoxon_p_holm:.3g} & {conclusion} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TAB / "e2_pairwise_tests.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot_convergence() -> None:
    df = pd.read_csv(E2_CURVES)
    part = df[(df.instance == "L-main-threeshift-100c-01") &
              (df.algorithm == "staged_hybrid_carbon_aware")].sort_values("eval")
    fig, ax = plt.subplots(figsize=(2.74, 2.10))
    ax.step(part["eval"], part["median_best_cost"], where="post", color="#006BAC", linewidth=0.612)
    ax.set_xlabel("评价次数")
    ax.set_ylabel("最好成本/£")
    ax.set_xlim(0, 4000)
    ax.set_xticks([0, 1000, 2000, 3000, 4000])
    ax.tick_params(direction="out", length=2.0, width=0.468)
    for spine in ax.spines.values():
        spine.set_linewidth(0.468)
    fig.subplots_adjust(left=0.19, right=0.97, bottom=0.20, top=0.97)
    save(fig, "e2_convergence")


def load_owners(condition: str) -> dict[str, str]:
    df = pd.read_csv(E3_DESIGN / "ownership_maps" / f"{REPRESENTATIVE}__{condition}.csv")
    return dict(zip(df.customer_id, df.owner_depot_id, strict=True))


def plot_structure() -> None:
    path = ROOT / "models/data_bundle/generated_instances/L-main" / REPRESENTATIVE / "instance.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = {node["node_id"]: node for node in payload["nodes"]}
    depots = [node for node in nodes.values() if node["node_type"].lower() == "d"]
    # Whole-figure grammar follows Soriano et al. (2023), Fig. 3: unframed
    # side-by-side class maps, marker/color-coded partners, titles above each
    # panel, and a count legend directly below each panel.
    fig, axes = plt.subplots(1, 2, figsize=(4.92, 2.30), sharex=True, sharey=True)
    for ax, condition, panel_label in zip(axes, ["geographic", "mixed"],
                                    ["地理聚集", "空间交错"], strict=True):
        owners = load_owners(condition)
        for owner, marker, color, name in [
            ("D0", "+", "#FF9999", "车场 A"), ("D1", "x", "#99CC99", "车场 B")
        ]:
            selected = [nodes[c] for c, d in owners.items() if d == owner]
            ax.scatter([n["x"] for n in selected], [n["y"] for n in selected], s=12,
                       marker=marker, color=color, linewidths=0.55,
                       label=f"{name}  {len(selected)}")
        for depot, marker, color in zip(sorted(depots, key=lambda x: x["node_id"]),
                                        ["+", "x"], ["#D7191C", "#1A9622"], strict=True):
            ax.scatter(depot["x"], depot["y"], s=70, marker=marker, color=color,
                       linewidths=1.05, zorder=5)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(panel_label, pad=1.5)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=2,
                  frameon=False, handletextpad=0.25, columnspacing=1.1)
        for spine in ax.spines.values():
            spine.set_visible(False)
    fig.subplots_adjust(wspace=0.08, bottom=0.18, top=0.94)
    save(fig, "e3_customer_structure")


def plot_e3_effect() -> None:
    df = pd.read_csv(E3 / "portfolio_effect_summary.csv").sort_values("customer_count")
    x = np.arange(len(df))
    width = 0.34
    fig, ax = plt.subplots(figsize=(3.65, 2.30))
    ax.bar(x - width / 2, df.geographic_mean_saving_pct, width=width, color="white",
           edgecolor="#262626", linewidth=0.35, hatch="////", label="地理聚集")
    ax.bar(x + width / 2, df.mixed_mean_saving_pct, width=width, color="#BFBFBF",
           edgecolor="#262626", linewidth=0.35, hatch="....", label="空间交错")
    ax.axhline(0, color="black", linewidth=0.45)
    ax.set_xticks(x, [str(int(value)) for value in df.customer_count])
    ax.set_xlabel("客户数")
    ax.set_ylabel("协同成本节省/%")
    ax.legend(loc="upper right", frameon=True, fancybox=False, edgecolor="#262626",
              framealpha=1.0, borderpad=0.25, handlelength=1.2)
    ax.tick_params(direction="out", length=2.0, width=0.468)
    for spine in ax.spines.values():
        spine.set_linewidth(0.468)
    fig.subplots_adjust(left=0.15, right=0.98, bottom=0.19, top=0.97)
    save(fig, "e3_structure_effect")


def write_e3_tables() -> None:
    values = json.loads((ROOT / "docs/paper_submission_final/e3_e4_story_20260713/paper_values.json").read_text(encoding="utf-8"))
    direct = values["e3"]["direct_seed_first_aggregation"]
    rows = [("总成本", direct["total_cost"]), ("行驶距离", direct["distance_total"]),
            ("燃油车直接排放", direct["E_cv_direct"]), ("电动车用电量", direct["electricity_kwh"])]
    lines = [r"\begin{tabular}{lrrr}", r"\toprule",
             r"指标 & 平均降幅/\% & 改善网络数 & 双侧$p$值 \\", r"\midrule"]
    for name, row in rows:
        lines.append(f"{name} & {row['mean_reduction_pct']:.2f} & {row['positive_networks']}/9 & {row['sign_p']:.4f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TAB / "e3_geographic_effect.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    source = pd.read_csv(E3 / "paper/table_e3_1_cost_sources.csv")
    lines = [r"\begin{tabular}{lrr}", r"\toprule",
             r"成本来源 & 地理聚集/百分点 & 空间交错/百分点 \\", r"\midrule"]
    for row in source.itertuples(index=False):
        lines.append(f"{row[0]} & {float(row[1]):.3f} & {float(row[2]):.3f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TAB / "e3_cost_sources.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    network = pd.read_csv(E3 / "portfolio_effect_summary.csv").sort_values("customer_count")
    lines = [r"\begin{tabular}{rrrr}", r"\toprule",
             r"客户数 & 地理聚集/\% & 空间交错/\% & 差值/百分点 \\", r"\midrule"]
    for row in network.itertuples(index=False):
        lines.append(f"{int(row.customer_count)} & {row.geographic_mean_saving_pct:.3f} & "
                     f"{row.mixed_mean_saving_pct:.3f} & {row.mixed_minus_geographic_pct_points:.3f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TAB / "e3_network_results.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    configure()
    write_e2_tables()
    plot_convergence()
    plot_structure()
    plot_e3_effect()
    write_e3_tables()
    print(f"built reader-facing E2/E3 exhibits in {OUT}")


if __name__ == "__main__":
    main()
