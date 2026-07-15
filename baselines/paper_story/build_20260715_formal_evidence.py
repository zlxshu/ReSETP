#!/usr/bin/env python3
"""Build manuscript exhibits from the sealed 2026-07-15 evidence packages."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "docs/paper_submission_final"
TABLES = MAIN / "generated_tables"
FIGURES = MAIN / "generated_figures"
E2B = ROOT / "baselines/e2_alns/e2b_component_ablation_formal_20260715"
E3 = ROOT / "baselines/e3_ablation/e3_medium_paired_cost_formal_20260715"
E6 = ROOT / "baselines/e6_fairness/e6_profit_guarantee_frontier_20260715"
E7_AUDIT = ROOT / "baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715"
E7_REPLAY = ROOT / "baselines/e7_dynamic/e7_multiday_zero_search_replay_20260715"


def write_table(name: str, lines: list[str]) -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_e2b() -> None:
    decision = json.loads((E2B / "decision.json").read_text(encoding="utf-8"))
    if decision.get("verdict") != "E2B_FORMAL_EVIDENCE_READY":
        raise RuntimeError("E2b formal evidence is not ready")
    summary = decision["arm_summary"]
    labels = {
        "A_continuous": "连续搜索",
        "B_staged": "分阶段搜索",
        "C_staged_cross": "分阶段+专用跨场算子",
        "D_full": "完整方案（再做充电择时）",
    }
    lines = [
        r"\begin{tabular*}{0.92\linewidth}{@{\extracolsep{\fill}}lrrrr@{}}",
        r"\toprule",
        r"方案 & 平均总成本 & 相对前档变化 & 电动车间接排放/kg & 可行单元 \\",
        r"\midrule",
    ]
    previous_cost: float | None = None
    for arm in ("A_continuous", "B_staged", "C_staged_cross", "D_full"):
        row = summary[arm]
        cost = float(row["mean_total_cost"])
        delta = "---" if previous_cost is None else f"{100.0 * (cost - previous_cost) / previous_cost:+.2f}\\%"
        lines.append(
            f"{labels[arm]} & {cost:.1f} & {delta} & "
            f"{float(row['mean_E_ev_indirect']):.2f} & "
            f"{int(row['valid_count'])}/{int(row['row_count'])} " + r"\\"
        )
        previous_cost = cost
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_table("e2b_component_ablation.tex", lines)


def build_e3() -> None:
    data = pd.read_csv(E3 / "trend_summary.csv")
    if len(data) != 9:
        raise RuntimeError("E3 trend table must contain nine networks")
    rows = [
        (
            "地理聚集",
            data["geographic_mismatch_index"].mean(),
            data["geographic_raw_saving_pct"].mean(),
        ),
        (
            "中等责任偏离",
            data["medium_mismatch_index"].mean(),
            data["medium_raw_saving_pct"].mean(),
        ),
        (
            "空间交错",
            data["mixed_mismatch_index"].mean(),
            data["mixed_raw_saving_pct"].mean(),
        ),
    ]
    lines = [
        r"\begin{tabular*}{0.76\linewidth}{@{\extracolsep{\fill}}lrr@{}}",
        r"\toprule",
        r"客户责任结构 & 平均责任偏离指数 & 平均协同节省/\% \\",
        r"\midrule",
    ]
    lines.extend(f"{label} & {mismatch:.3f} & {saving:.2f} " + r"\\" for label, mismatch, saving in rows)
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_table("e3_responsibility_gradient.tex", lines)


def build_e6() -> None:
    decision = json.loads((E6 / "decision.json").read_text(encoding="utf-8"))
    if decision.get("status") != "PASS_E6_PROFIT_GUARANTEE_FRONTIER":
        raise RuntimeError("E6 frontier evidence is not complete")
    data = pd.read_csv(E6 / "selected_frontier.csv")
    network = (
        data.groupby(["instance", "condition", "alpha"], as_index=False)
        .agg(
            cost_increment_pct=("cost_increment_pct", "mean"),
            minimum_profit_ratio=("selected_minimum_profit_ratio", "mean"),
        )
    )
    summary = (
        network.groupby(["condition", "alpha"], as_index=False)
        .agg(
            cost_increment_pct=("cost_increment_pct", "mean"),
            minimum_profit_ratio=("minimum_profit_ratio", "mean"),
        )
    )
    labels = {"geographic": "地理聚集", "mixed": "空间交错"}
    lines = [
        r"\begin{tabular*}{0.86\linewidth}{@{\extracolsep{\fill}}lrrr@{}}",
        r"\toprule",
        r"客户责任结构 & 保障推进比例 & 系统成本增幅/\% & 最低收益比 \\",
        r"\midrule",
    ]
    for condition in ("geographic", "mixed"):
        block = summary[summary["condition"] == condition]
        for row in block.itertuples(index=False):
            lines.append(
                f"{labels[condition]} & {float(row.alpha):.2f} & "
                f"{float(row.cost_increment_pct):.2f} & "
                f"{float(row.minimum_profit_ratio):.3f} " + r"\\"
            )
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_table("e6_profit_guarantee_frontier.tex", lines)

    FIGURES.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": ["Times New Roman", "Songti SC"],
            "font.size": 7,
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
        }
    )
    fig, ax = plt.subplots(figsize=(3.65, 2.25))
    styles = {
        "geographic": dict(color="#222222", marker="o", linestyle="-"),
        "mixed": dict(color="#777777", marker="s", linestyle="--"),
    }
    for condition in ("geographic", "mixed"):
        block = summary[summary["condition"] == condition]
        ax.plot(
            block["alpha"],
            block["cost_increment_pct"],
            linewidth=0.8,
            markersize=3.2,
            label=labels[condition],
            **styles[condition],
        )
    ax.set_xlabel("从无约束方案向双方参与底线推进的比例")
    ax.set_ylabel("系统成本增幅/%")
    ax.set_xticks([0.0, 0.25, 0.5, 0.75, 1.0])
    ax.legend(frameon=False)
    ax.tick_params(direction="out", length=2, width=0.5)
    for spine in ax.spines.values():
        spine.set_linewidth(0.5)
    fig.tight_layout()
    fig.savefig(FIGURES / "e6_profit_guarantee_frontier.pdf", bbox_inches="tight")
    fig.savefig(FIGURES / "e6_profit_guarantee_frontier.png", dpi=450, bbox_inches="tight")
    plt.close(fig)


def build_e7() -> None:
    decision = json.loads((E7_AUDIT / "decision.json").read_text(encoding="utf-8"))
    if decision.get("verdict") != "PASS_E7_MULTINETWORK_FORMAL_AND_REPLAY_INDEPENDENT_AUDIT":
        raise RuntimeError("E7 independent audit is not complete")
    paired = pd.read_csv(E7_AUDIT / "paired_summary.csv")
    replay = pd.read_csv(E7_REPLAY / "summary.csv")
    if len(paired) != 6 or len(replay) != 6:
        raise RuntimeError("E7 manuscript summaries must each contain six cells")
    networks = {"N114": "50客户", "N221": "100客户", "N322": "150客户"}
    conditions = {"geographic": "地理聚集", "historical_mixed": "空间交错"}

    lines = [
        r"\begin{tabular*}{0.98\linewidth}{@{\extracolsep{\fill}}llrrrrr@{}}",
        r"\toprule",
        r"网络 & 客户责任 & 四种可执行 & 配对/参与 & 完整-禁合作 & 完整-无底线 & 完整-顺序插单 \\",
        r"\midrule",
    ]
    for row in paired.itertuples(index=False):
        complete = int(row.paired_complete_stream_count)
        executable = "/".join(
            str(int(value))
            for value in (
                row.full_executable_stream_count,
                row.no_cooperation_executable_stream_count,
                row.no_participation_executable_stream_count,
                row.simple_insertion_executable_stream_count,
            )
        )
        lines.append(
            f"{networks[row.network]} & {conditions[row.condition]} & {executable} & "
            f"{complete}/5;{int(row.full_day_participation_floor_met_count)}/{complete} & "
            f"{float(row.full_minus_no_cooperation_net_profit_mean):+.1f} & "
            f"{float(row.full_minus_no_participation_net_profit_mean):+.1f} & "
            f"{float(row.full_minus_simple_insertion_net_profit_mean):+.1f} "
            + r"\\"
        )
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_table("e7_dynamic_policy_comparison.tex", lines)

    lines = [
        r"\begin{tabular*}{0.94\linewidth}{@{\extracolsep{\fill}}llrrrrr@{}}",
        r"\toprule",
        r"网络 & 客户责任 & 跨场流 & 超时阶段 & 完整/禁合作 & 完整/无底线 & 完整/顺序插单 \\",
        r"\midrule",
    ]
    for row in paired.itertuples(index=False):
        lines.append(
            f"{networks[row.network]} & {conditions[row.condition]} & "
            f"{int(row.full_streams_with_cross_site_service)}/{int(row.full_executable_stream_count)} & "
            f"{int(row.full_stage_deadline_miss_count)}/{int(row.full_deadline_comparable_stage_count)} & "
            f"{row.full_vs_no_cooperation_better_worse_tied} & "
            f"{row.full_vs_no_participation_better_worse_tied} & "
            f"{row.full_vs_simple_insertion_better_worse_tied} " + r"\\"
        )
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_table("e7_dynamic_mechanism_diagnostics.tex", lines)

    lines = [
        r"\begin{tabular*}{0.92\linewidth}{@{\extracolsep{\fill}}llrrrr@{}}",
        r"\toprule",
        r"网络 & 客户责任 & 充电排放降幅/\% & 总运营排放降幅/\% & 改善/变差/持平 & 配对数 \\",
        r"\midrule",
    ]
    for row in replay.itertuples(index=False):
        lines.append(
            f"{networks[row.network]} & {conditions[row.condition]} & "
            f"{float(row.pooled_charging_reduction_pct):.2f} & "
            f"{float(row.pooled_total_operational_reduction_pct):.2f} & "
            f"{int(row.improved)}/{int(row.worsened)}/{int(row.tied)} & "
            f"{int(row.stream_day_count)} " + r"\\"
        )
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_table("e7_dynamic_charging_replay.tex", lines)


def main() -> int:
    build_e2b()
    build_e3()
    build_e6()
    if (E7_AUDIT / "decision.json").is_file() and (
        E7_REPLAY / "decision.json"
    ).is_file():
        build_e7()
        print("built E2b/E3/E6/E7 manuscript exhibits")
    else:
        print("built E2b/E3/E6 manuscript exhibits; E7 evidence not sealed yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
