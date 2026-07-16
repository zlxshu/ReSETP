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
from scipy.stats import friedmanchisquare, wilcoxon
from statsmodels.stats.multitest import multipletests
from fontTools.ttLib import TTCollection

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/paper_submission_final/e2_e3_preview_20260714"
FIG, TAB = OUT / "figures", OUT / "tables"
MAIN = ROOT / "docs/paper_submission_final"
MAIN_FIG, MAIN_TAB = MAIN / "generated_figures", MAIN / "generated_tables"
E2 = ROOT / "baselines/e2_alns/e2_final_10seed_20260711/formal"
E2_CURVES = ROOT / "baselines/e2_alns/e2_final_10seed_20260711/figures/f2_convergence_curves.csv"
E3 = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
E3_DESIGN = ROOT / "baselines/e3_ablation/e3_ownership_class_design_v4_20260713"
REPRESENTATIVE = "L-main-threeshift-75c-01"

NAMES = {
    "staged_hybrid_carbon_aware": "TVCI-ALNS", "GA": "GA", "PSO": "PSO",
    "VNS": "VNS", "ACO": "ACO", "GA-VNS": "GA-VNS",
    "LNS": "LNS", "GWO": "GWO", "IWD": "IWD",
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
        # Chen et al. (2025, SETP) uses Times for Latin/numerals and Song for Chinese.
        # Matplotlib falls through this family list glyph by glyph.
        "font.family": ["Times New Roman", "Songti SC"],
        "font.size": 6.62, "axes.labelsize": 6.62, "axes.titlesize": 6.62,
        "xtick.labelsize": 6.62, "ytick.labelsize": 6.62, "legend.fontsize": 6.3,
        "axes.unicode_minus": False, "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "pdf.fonttype": 42, "ps.fonttype": 42,
    })


def save(fig: plt.Figure, stem: str) -> None:
    for folder in (FIG, MAIN_FIG):
        folder.mkdir(parents=True, exist_ok=True)
        fig.savefig(folder / f"{stem}.pdf", bbox_inches="tight")
        fig.savefig(folder / f"{stem}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def write_tex(name: str, lines: list[str]) -> None:
    for folder in (TAB, MAIN_TAB):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def network_level_tests() -> pd.DataFrame:
    """Use nine networks and only implementation-validated baselines."""
    detail = pd.read_csv(E2 / "table_algorithm_by_instance.csv")
    pivot = detail.pivot(index="instance", columns="algorithm", values="avg_cost")
    primary = "staged_hybrid_carbon_aware"
    rows: list[dict[str, float | str]] = []
    raw_p: list[float] = []
    # The sealed IWD rows come from the legacy simplified adaptation.  A later
    # formula-faithful repair failed its pre-registered fidelity gate and was
    # therefore not allowed to overwrite the formal matrix.  The sealed rows
    # remain untouched, but IWD is excluded from submission tables and from the
    # confirmatory family because it is not an implementation-valid comparator.
    for baseline in ["GA", "PSO", "VNS", "ACO", "GA-VNS", "LNS", "GWO"]:
        gain = (pivot[baseline] - pivot[primary]) / pivot[baseline] * 100.0
        nonzero = gain[np.abs(gain) > 1e-12]
        result = wilcoxon(nonzero, alternative="two-sided", method="exact")
        raw_p.append(float(result.pvalue))
        rows.append({
            "baseline": baseline,
            "networks": int(len(gain)),
            "mean_gain_pct": float(gain.mean()),
            "median_gain_pct": float(gain.median()),
            "wilcoxon_w": float(result.statistic),
            "p_raw": float(result.pvalue),
        })
    for row, value in zip(rows, multipletests(raw_p, method="holm")[1], strict=True):
        row["p_holm"] = float(value)
    tests = pd.DataFrame(rows)
    audit = OUT / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    tests.to_csv(audit / "e2_network_level_tests.csv", index=False)
    return tests


def write_e2_tables_legacy() -> None:
    TAB.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(E2 / "algorithm_summary.csv").sort_values("mean_rank_by_instance_avg")
    pair = pd.read_csv(E2 / "paired_wilcoxon.csv").set_index("baseline")
    lines = [r"\begin{tabular}{lrrrrr}", r"\toprule",
             r"算法 & 综合成本 & 平均名次 & 最优次数 & 平均耗时/s & 相对改进/\% \\",
             r"\midrule"]
    for row in df.itertuples(index=False):
        gain = "---" if row.algorithm == "staged_hybrid_carbon_aware" else f"{pair.loc[row.algorithm, 'mean_gain_pct']:.2f}"
        lines.append(f"{NAMES[row.algorithm]} & {row.sum_of_instance_avg_costs:,.1f} & "
                     f"{mean_rank.loc[row.algorithm]:.2f} & {int(best_count.loc[row.algorithm])} & "
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


def write_e2_tables() -> None:
    df = pd.read_csv(E2 / "algorithm_summary.csv")
    df = df[df.algorithm != "IWD"].sort_values("mean_rank_by_instance_avg")
    detail = pd.read_csv(E2 / "table_algorithm_by_instance.csv")
    detail = detail[detail.algorithm != "IWD"].copy()
    best_by_network = detail.groupby("instance")["avg_cost"].transform("min")
    detail["relative_gap_pct"] = (detail["avg_cost"] / best_by_network - 1.0) * 100.0
    detail["cost_cv_pct"] = 100.0 * detail["std_cost"] / detail["avg_cost"]
    detail["valid_rank"] = detail.groupby("instance")["avg_cost"].rank(method="average")
    mean_gap = detail.groupby("algorithm")["relative_gap_pct"].mean()
    mean_cv = detail.groupby("algorithm")["cost_cv_pct"].mean()
    mean_rank = detail.groupby("algorithm")["valid_rank"].mean()
    best_count = (
        detail.assign(is_best=detail["valid_rank"].eq(1.0))
        .groupby("algorithm")["is_best"]
        .sum()
    )
    lines = [r"\begin{tabular*}{0.92\linewidth}{@{\extracolsep{\fill}}lrrrrr@{}}", r"\toprule",
             r"算法 & 平均相对偏差/\% & 变异系数/\% & 平均名次 & 最优网络数 & 平均耗时/s \\",
             r"\midrule"]
    for row in df.itertuples(index=False):
        lines.append(f"{NAMES[row.algorithm]} & {mean_gap.loc[row.algorithm]:.2f} & "
                     f"{mean_cv.loc[row.algorithm]:.2f} & {row.mean_rank_by_instance_avg:.2f} & "
                     f"{int(row.best_instance_avg_count)} & "
                     f"{row.mean_runtime_seconds:.1f}" + r" \\")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_tex("e2_algorithm_summary.tex", lines)

    tests = network_level_tests()
    lines = [r"\begin{tabular*}{0.84\linewidth}{@{\extracolsep{\fill}}lrrrr@{}}", r"\toprule",
             r"对比算法 & 平均降幅/\% & 中位降幅/\% & $W$ & $p_{\rm Holm}$ \\",
             r"\midrule"]
    for row in tests.itertuples(index=False):
        p_text = f"{row.p_holm:.3f}"
        if row.p_holm < 0.05:
            p_text = rf"\textbf{{{p_text}}}"
        lines.append(f"{NAMES[row.baseline]} & {row.mean_gain_pct:.2f} & "
                     f"{row.median_gain_pct:.2f} & {row.wilcoxon_w:.0f} & {p_text}" + r" \\")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_tex("e2_pairwise_tests.tex", lines)

    counts = pd.read_csv(E3 / "portfolio_effect_summary.csv")[["instance", "customer_count"]]
    detail = detail.merge(counts, on="instance", validate="many_to_one")
    pivot = detail.pivot(index="customer_count", columns="algorithm", values="avg_cost").sort_index()
    table_parts = [
        ("e2_network_costs_a.tex", ["staged_hybrid_carbon_aware", "GA", "PSO", "VNS", "ACO"]),
        ("e2_network_costs_b.tex", ["staged_hybrid_carbon_aware", "GA-VNS", "LNS", "GWO"]),
    ]
    for name, algorithms in table_parts:
        numeric_columns = "r" * len(algorithms)
        lines = [rf"\begin{{tabular*}}{{0.92\linewidth}}{{@{{\extracolsep{{\fill}}}}l{numeric_columns}@{{}}}}", r"\toprule",
                 "客户数 & " + " & ".join(NAMES[a] for a in algorithms) + r" \\", r"\midrule"]
        for customer_count, row in pivot.iterrows():
            lines.append(f"{int(customer_count)} & " +
                         " & ".join(f"{row[a]:,.1f}" for a in algorithms) + r" \\")
        lines += [r"\bottomrule", r"\end{tabular*}"]
        write_tex(name, lines)

    matrix = detail.pivot(index="instance", columns="algorithm", values="avg_cost")
    stat, p_value = friedmanchisquare(*(matrix[column] for column in matrix.columns))
    audit = OUT / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "e2_friedman_test.json").write_text(
        json.dumps({"statistic": float(stat), "p_value": float(p_value),
                    "networks": 9, "algorithms": 8,
                    "excluded_from_inference": ["IWD"]}, indent=2) + "\n",
        encoding="utf-8")


def plot_convergence() -> None:
    df = pd.read_csv(E2_CURVES)
    part = df[df.instance == "L-main-threeshift-100c-01"]
    fig, ax = plt.subplots(figsize=(5.15, 3.00))
    # Chen et al. (2025), Fig. 4 supplies the overall grammar: a small set of
    # thin curves, no grid and a compact in-figure legend.  Keep only the four
    # competitive algorithms in the figure; submission tables include all
    # eight implementation-valid algorithms, while sealed IWD rows stay only
    # in the repository evidence.
    styles = [
        ("staged_hybrid_carbon_aware", "TVCI-ALNS", "#111111", "-", "o"),
        ("LNS", "LNS", "#4D4D4D", "--", "s"),
        ("GA-VNS", "GA-VNS", "#777777", "-.", "^"),
        ("VNS", "VNS", "#999999", ":", "D"),
    ]
    for algorithm, label, color, linestyle, marker in styles:
        curve = part[part.algorithm == algorithm].sort_values("eval")
        ax.plot(curve["eval"], curve["median_best_cost"], color=color,
                linestyle=linestyle, linewidth=0.62, drawstyle="steps-post",
                marker=marker, markevery=8, markersize=2.0,
                markerfacecolor="white", markeredgewidth=0.42, label=label)
    ax.set_xlabel("评价次数")
    ax.set_ylabel("最好成本/£")
    # The formal budget ends at 4000 evaluations.  Extending the visible axis
    # slightly past the data creates an honest blank band at the upper-right,
    # so the in-figure legend does not cover any trajectory.
    ax.set_xlim(0, 4400)
    ax.set_ylim(5200, 8600)
    ax.set_xticks([0, 1000, 2000, 3000, 4000])
    legend = ax.legend(loc="upper right", ncol=2, frameon=True, fancybox=False,
                       edgecolor="#777777", framealpha=1.0, borderpad=0.18,
                       columnspacing=0.62, handletextpad=0.28,
                       handlelength=1.70, fontsize=5.8)
    legend.get_frame().set_linewidth(0.35)
    ax.tick_params(direction="out", length=2.0, width=0.468)
    for spine in ax.spines.values():
        spine.set_linewidth(0.468)
    fig.subplots_adjust(left=0.12, right=0.985, bottom=0.17, top=0.975)
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
    # side-by-side class maps, marker/color-coded partners and titles above each
    # panel.  The manuscript-wide legend rule keeps the compact legend inside
    # the upper-right corner, with extra coordinate range reserved above the
    # customer cloud so it does not cover observations.
    fig, axes = plt.subplots(1, 2, figsize=(4.92, 2.30), sharex=True, sharey=True)
    all_x = [node["x"] for node in nodes.values()]
    all_y = [node["y"] for node in nodes.values()]
    x_span = max(all_x) - min(all_x)
    y_span = max(all_y) - min(all_y)
    for ax, condition, panel_label in zip(axes, ["geographic", "mixed"],
                                    ["地理聚集", "空间交错"], strict=True):
        owners = load_owners(condition)
        for owner, marker, color, name in [
            ("D0", "+", "#222222", "车场 A"), ("D1", "x", "#777777", "车场 B")
        ]:
            selected = [nodes[c] for c, d in owners.items() if d == owner]
            ax.scatter([n["x"] for n in selected], [n["y"] for n in selected], s=12,
                       marker=marker, color=color, linewidths=0.55,
                       label=f"{name}  {len(selected)}")
        for depot, marker, color in zip(sorted(depots, key=lambda x: x["node_id"]),
                                        ["+", "x"], ["#111111", "#777777"], strict=True):
            ax.scatter(depot["x"], depot["y"], s=70, marker=marker, color=color,
                       linewidths=1.05, zorder=5)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlim(min(all_x) - 0.05 * x_span, max(all_x) + 0.05 * x_span)
        ax.set_ylim(min(all_y) - 0.04 * y_span, max(all_y) + 0.22 * y_span)
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(panel_label, pad=1.5)
        legend = ax.legend(loc="upper right", ncol=1, frameon=True,
                           fancybox=False, edgecolor="#777777", framealpha=1.0,
                           borderpad=0.18, labelspacing=0.18,
                           handletextpad=0.25, handlelength=1.1, fontsize=6.0)
        legend.get_frame().set_linewidth(0.35)
        for spine in ax.spines.values():
            spine.set_visible(False)
    fig.subplots_adjust(wspace=0.08, bottom=0.05, top=0.94)
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


def write_e3_tables_legacy() -> None:
    values = json.loads((ROOT / "docs/paper_submission_final/e3_e4_story_20260713/paper_values.json").read_text(encoding="utf-8"))
    direct = values["e3"]["direct_seed_first_aggregation"]
    rows = [("总成本", direct["total_cost"]), ("行驶距离", direct["distance_total"]),
            ("燃油车直接排放", direct["E_cv_direct"]), ("电动车用电量", direct["electricity_kwh"])]
    lines = [r"\begin{tabular*}{0.84\linewidth}{@{\extracolsep{\fill}}lrrr@{}}", r"\toprule",
             r"指标 & 平均降幅/\% & 改善网络数 & 双侧$p$值 \\", r"\midrule"]
    for name, row in rows:
        lines.append(f"{name} & {row['mean_reduction_pct']:.2f} & {row['positive_networks']}/9 & {row['sign_p']:.4f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    (TAB / "e3_geographic_effect.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    source = pd.read_csv(E3 / "paper/table_e3_1_cost_sources.csv")
    lines = [r"\begin{tabular*}{0.84\linewidth}{@{\extracolsep{\fill}}lrr@{}}", r"\toprule",
             r"成本来源 & 地理聚集/百分点 & 空间交错/百分点 \\", r"\midrule"]
    for row in source.itertuples(index=False):
        lines.append(f"{row[0]} & {float(row[1]):.3f} & {float(row[2]):.3f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    (TAB / "e3_cost_sources.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    network = pd.read_csv(E3 / "portfolio_effect_summary.csv").sort_values("customer_count")
    lines = [r"\begin{tabular}{rrrr}", r"\toprule",
             r"客户数 & 地理聚集/\% & 空间交错/\% & 差值/百分点 \\", r"\midrule"]
    for row in network.itertuples(index=False):
        lines.append(f"{int(row.customer_count)} & {row.geographic_mean_saving_pct:.3f} & "
                     f"{row.mixed_mean_saving_pct:.3f} & {row.mixed_minus_geographic_pct_points:.3f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TAB / "e3_network_results.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_e3_tables() -> None:
    values = json.loads(
        (ROOT / "docs/paper_submission_final/e3_e4_story_20260713/paper_values.json")
        .read_text(encoding="utf-8")
    )
    direct = values["e3"]["direct_seed_first_aggregation"]
    rows = [
        ("总成本", direct["total_cost"]),
        ("行驶距离", direct["distance_total"]),
        ("燃油车直接排放", direct["E_cv_direct"]),
        ("电动车用电量", direct["electricity_kwh"]),
    ]
    lines = [r"\begin{tabular*}{0.84\linewidth}{@{\extracolsep{\fill}}lrrr@{}}", r"\toprule",
             r"指标 & 平均降幅/\% & 中位降幅/\% & 变化范围/\% \\", r"\midrule"]
    for name, row in rows:
        observations = np.asarray(row["network_values"], dtype=float)
        lines.append(
            f"{name} & {row['mean_reduction_pct']:.2f} & "
            f"{np.median(observations):.2f} & "
            f"{observations.min():.2f}--{observations.max():.2f}" + r" \\"
        )
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_tex("e3_geographic_effect.tex", lines)

    source = pd.read_csv(E3 / "paper/table_e3_1_cost_sources.csv")
    lines = [r"\begin{tabular*}{0.84\linewidth}{@{\extracolsep{\fill}}lrr@{}}", r"\toprule",
             r"成本来源 & 地理聚集/百分点 & 空间交错/百分点 \\", r"\midrule"]
    for row in source.itertuples(index=False):
        lines.append(f"{row[0]} & {float(row[1]):.3f} & {float(row[2]):.3f}" + r" \\")
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_tex("e3_cost_sources.tex", lines)

    network = pd.read_csv(E3 / "portfolio_effect_summary.csv").sort_values("customer_count")
    lines = [r"\begin{tabular*}{0.84\linewidth}{@{\extracolsep{\fill}}lrrr@{}}", r"\toprule",
             r"客户数 & 地理聚集/\% & 空间交错/\% & 差值/百分点 \\", r"\midrule"]
    for row in network.itertuples(index=False):
        lines.append(
            f"{int(row.customer_count)} & {row.geographic_mean_saving_pct:.3f} & "
            f"{row.mixed_mean_saving_pct:.3f} & "
            f"{row.mixed_minus_geographic_pct_points:.3f}" + r" \\"
        )
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_tex("e3_network_results.tex", lines)

    diameters = values["e3"]["network_diameters_km"]
    lines = [r"\begin{tabular*}{0.84\linewidth}{@{\extracolsep{\fill}}lrrr@{}}", r"\toprule",
             r"网络 & 客户数 & 车场数 & 最大点间距离/km \\", r"\midrule"]
    for row in network.itertuples(index=False):
        lines.append(
            f"N{int(row.customer_count)} & {int(row.customer_count)} & 2 & "
            f"{float(diameters[row.instance]):.1f}" + r" \\"
        )
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_tex("e2_e3_instances.tex", lines)


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
