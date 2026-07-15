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

E7_NETWORK_LABELS = {"N114": "50客户", "N221": "100客户", "N322": "150客户"}
E7_CONDITION_LABELS = {"geographic": "地理聚集", "historical_mixed": "空间交错"}
E7_ARM_LABELS = {
    "full": "完整机制",
    "no_cooperation": "禁合作",
    "no_participation": "无参与底线",
    "simple_insertion": "顺序插单",
}
E7_COMPARISONS = (
    (
        "禁合作",
        "full_minus_no_cooperation_net_profit",
        "full_minus_no_cooperation_revenue",
        "full_minus_no_cooperation_cost",
        "full_minus_no_cooperation_completed_customer_count",
        "full_minus_no_cooperation_completed_demand",
    ),
    (
        "无参与底线",
        "full_minus_no_participation_net_profit",
        "full_minus_no_participation_revenue",
        "full_minus_no_participation_system_cost",
        "full_minus_no_participation_completed_customer_count",
        "full_minus_no_participation_completed_demand",
    ),
    (
        "顺序插单",
        "full_minus_simple_insertion_net_profit",
        "full_minus_simple_insertion_revenue",
        "full_minus_simple_insertion_cost",
        "full_minus_simple_insertion_completed_customer_count",
        "full_minus_simple_insertion_completed_demand",
    ),
)


def write_table(name: str, lines: list[str]) -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def truthy(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def e7_cell_label(row: pd.Series) -> str:
    return (
        f"{E7_NETWORK_LABELS[str(row['network'])]}—"
        f"{E7_CONDITION_LABELS[str(row['condition'])]}—流{int(row['stream'])}"
    )


def e7_sign_counts(values: pd.Series, tolerance: float = 1e-6) -> tuple[int, int, int]:
    numeric = pd.to_numeric(values, errors="raise")
    return (
        int((numeric > tolerance).sum()),
        int((numeric < -tolerance).sum()),
        int((numeric.abs() <= tolerance).sum()),
    )


def render_e7_interpretation(
    pair_rows: pd.DataFrame,
    task_status: pd.DataFrame,
    paired_summary: pd.DataFrame,
    replay_summary: pd.DataFrame,
    decision: dict[str, object],
) -> str:
    """Render result-first E7 prose without smoothing failures or cell extrema."""
    if len(pair_rows) != 30 or len(task_status) != 120:
        raise RuntimeError("E7 narrative requires 30 stream pairs and 120 task statuses")
    if len(paired_summary) != 6 or len(replay_summary) != 6:
        raise RuntimeError("E7 narrative requires six dynamic and six replay cells")
    expected_pairs = {
        (network, condition, stream)
        for network in E7_NETWORK_LABELS
        for condition in E7_CONDITION_LABELS
        for stream in range(1, 6)
    }
    observed_pairs = {
        (str(row.network), str(row.condition), int(row.stream))
        for row in pair_rows.itertuples(index=False)
    }
    if observed_pairs != expected_pairs:
        raise RuntimeError("E7 narrative pair identities are incomplete or unexpected")
    observed_tasks = {
        (str(row.network), str(row.condition), int(row.stream), str(row.arm))
        for row in task_status.itertuples(index=False)
    }
    expected_tasks = {
        (*pair, arm) for pair in expected_pairs for arm in E7_ARM_LABELS
    }
    if observed_tasks != expected_tasks:
        raise RuntimeError("E7 narrative task identities are incomplete or unexpected")
    complete = pair_rows[pair_rows["all_four_arms_executable"].map(truthy)].copy()
    if complete.empty:
        raise RuntimeError("E7 narrative has no four-arm executable stream")
    if int(paired_summary["paired_complete_stream_count"].sum()) != len(complete):
        raise RuntimeError("E7 pair rows disagree with the six-cell complete-pair counts")

    failures = task_status[task_status["execution_status"] != "PASS"].copy()
    controlled = int(decision.get("controlled_arm_failure_count", -1))
    if controlled != len(failures):
        raise RuntimeError(
            "E7 controlled failure count disagrees with the task-status evidence"
        )
    failure_text = ""
    if controlled:
        identities = "、".join(
            f"{E7_NETWORK_LABELS[str(row.network)]}—"
            f"{E7_CONDITION_LABELS[str(row.condition)]}—流{int(row.stream)}—"
            f"{E7_ARM_LABELS[str(row.arm)]}"
            for row in failures.itertuples(index=False)
        )
        failure_text = (
            f"其中{controlled}个受控不可执行单元为{identities}；这些单元保留在"
            "可执行率中，不进入四臂成对均值。"
        )
    else:
        failure_text = "120个正式任务全部完成，未观察到受控不可执行单元。"

    deadline_misses = int(paired_summary["full_stage_deadline_miss_count"].sum())
    deadline_total = int(paired_summary["full_deadline_comparable_stage_count"].sum())
    maximum_elapsed = float(paired_summary["full_maximum_stage_elapsed_seconds"].max())
    if deadline_misses:
        timing_text = (
            f"完整机制有{deadline_misses}个阶段超过下一触发间隔，"
            f"可比较阶段共{deadline_total}个，最长阶段用时{maximum_elapsed:.1f} s；"
            "因此本批结果只能解释为批量滚动决策支持，不能改称实时求解。"
        )
    else:
        timing_text = (
            f"完整机制的{deadline_total}个可比较阶段均满足实时响应条件，"
            f"最长阶段用时{maximum_elapsed:.1f} s。"
        )
    cross_site = int(paired_summary["full_streams_with_cross_site_service"].sum())
    full_executable = int(paired_summary["full_executable_stream_count"].sum())
    floor_met = int(paired_summary["full_day_participation_floor_met_count"].sum())
    opening = (
        f"正式矩阵包含120个任务，形成{len(complete)}/30个四臂完整配对；完整机制在"
        f"{cross_site}/{full_executable}条可执行订单流中实际发生跨场服务，并在"
        f"{floor_met}/{len(complete)}个完整配对中满足全日参与底线。{failure_text}"
        f"{timing_text}"
    )

    comparison_paragraphs: list[str] = []
    for label, profit, revenue, cost, customers, demand in E7_COMPARISONS:
        for field in (profit, revenue, cost, customers, demand):
            complete[field] = pd.to_numeric(complete[field], errors="raise")
        better, worse, tied = e7_sign_counts(complete[profit])
        best = complete.loc[complete[profit].idxmax()]
        worst = complete.loc[complete[profit].idxmin()]
        comparison_paragraphs.append(
            f"在{len(complete)}个完整配对中，完整机制相对{label}的净收益差均值为"
            f"{complete[profit].mean():+.1f}，改善/变差/持平为"
            f"{better}/{worse}/{tied}；收入、成本、完成客户数和完成需求差均值分别为"
            f"{complete[revenue].mean():+.1f}、{complete[cost].mean():+.1f}、"
            f"{complete[customers].mean():+.2f}和{complete[demand].mean():+.1f}。"
            f"最有利单元是{e7_cell_label(best)}（{float(best[profit]):+.1f}），"
            f"最不利单元是{e7_cell_label(worst)}（{float(worst[profit]):+.1f}）。"
            "净收益差必须与服务收入和工作量差共同解释；这里报告的是观察到的全日结果，"
            "不把均值方向直接解释成单一机制的因果效应。"
        )

    replay = replay_summary.copy()
    for field in (
        "pooled_charging_reduction_pct",
        "pooled_total_operational_reduction_pct",
        "improved",
        "worsened",
        "tied",
        "stream_day_count",
    ):
        replay[field] = pd.to_numeric(replay[field], errors="raise")
    replay_count = int(replay["stream_day_count"].sum())
    improved = int(replay["improved"].sum())
    worsened = int(replay["worsened"].sum())
    tied = int(replay["tied"].sum())
    if replay_count != 840 or improved + worsened + tied != replay_count:
        raise RuntimeError("E7 replay narrative does not contain an exact 840-row partition")
    if not (replay["stream_day_count"] == 140).all():
        raise RuntimeError("E7 replay narrative does not contain 140 rows in every cell")
    charge_min = replay.loc[replay["pooled_charging_reduction_pct"].idxmin()]
    charge_max = replay.loc[replay["pooled_charging_reduction_pct"].idxmax()]
    replay_text = (
        f"28日电网数据零搜索重放形成{replay_count}组配对，改善/变差/持平为"
        f"{improved}/{worsened}/{tied}。六个网络—责任单元的充电排放降幅介于"
        f"{replay['pooled_charging_reduction_pct'].min():.2f}\\%和"
        f"{replay['pooled_charging_reduction_pct'].max():.2f}\\%之间，最低出现在"
        f"{E7_NETWORK_LABELS[str(charge_min['network'])]}—"
        f"{E7_CONDITION_LABELS[str(charge_min['condition'])]}，最高出现在"
        f"{E7_NETWORK_LABELS[str(charge_max['network'])]}—"
        f"{E7_CONDITION_LABELS[str(charge_max['condition'])]}；总运营排放降幅范围为"
        f"{replay['pooled_total_operational_reduction_pct'].min():.2f}\\%--"
        f"{replay['pooled_total_operational_reduction_pct'].max():.2f}\\%。"
        "该结果固定路径、车辆、服务客户和充电电量，只识别合法窗口内充电择时的增量作用，"
        "不构成路径—充电联合优化的证据。"
    )
    return "\n\n".join([opening, *comparison_paragraphs, replay_text]) + "\n"


def render_e7_conclusion(
    pair_rows: pd.DataFrame,
    paired_summary: pd.DataFrame,
    replay_summary: pd.DataFrame,
    decision: dict[str, object],
) -> str:
    complete = pair_rows[pair_rows["all_four_arms_executable"].map(truthy)].copy()
    controlled = int(decision.get("controlled_arm_failure_count", -1))
    misses = int(paired_summary["full_stage_deadline_miss_count"].sum())
    direction_parts: list[str] = []
    for label, profit, *_ in E7_COMPARISONS:
        complete[profit] = pd.to_numeric(complete[profit], errors="raise")
        better, worse, tied = e7_sign_counts(complete[profit])
        direction_parts.append(
            f"相对{label}净收益差均值为{complete[profit].mean():+.1f}"
            f"（{better}/{worse}/{tied}）"
        )
    replay = replay_summary.copy()
    replay["pooled_charging_reduction_pct"] = pd.to_numeric(
        replay["pooled_charging_reduction_pct"], errors="raise"
    )
    timing = (
        f"另有{misses}个阶段超过下一触发间隔，故只支持批量滚动决策解释"
        if misses
        else "全部可比较阶段均满足实时响应条件"
    )
    return (
        f"动态正式矩阵形成{len(complete)}/30个四臂完整配对，"
        + "，".join(direction_parts)
        + f"；保留{controlled}个受控不可执行单元，{timing}。"
        f"固定配送方案的28日电网日零搜索重放显示，六个单元的充电排放降幅为"
        f"{replay['pooled_charging_reduction_pct'].min():.2f}\\%--"
        f"{replay['pooled_charging_reduction_pct'].max():.2f}\\%。"
        "这些结果共同说明动态协同的收益、参与保障、可执行性、计算时限和充电减排"
        "必须分项判断，不能压缩成单一优化目标。\n"
    )


def render_e7_abstracts(
    pair_rows: pd.DataFrame,
    paired_summary: pd.DataFrame,
    replay_summary: pd.DataFrame,
    decision: dict[str, object],
) -> tuple[str, str]:
    """Render compact bilingual abstract evidence without selecting a favourable arm."""
    complete = pair_rows[pair_rows["all_four_arms_executable"].map(truthy)].copy()
    if complete.empty:
        raise RuntimeError("E7 abstract has no four-arm executable stream")
    if int(paired_summary["paired_complete_stream_count"].sum()) != len(complete):
        raise RuntimeError("E7 abstract complete-pair counts disagree")
    comparison_zh: list[str] = []
    comparison_en: list[str] = []
    en_labels = {
        "禁合作": "no cooperation",
        "无参与底线": "no participation floor",
        "顺序插单": "sequential insertion",
    }
    for label, profit, *_ in E7_COMPARISONS:
        complete[profit] = pd.to_numeric(complete[profit], errors="raise")
        better, worse, tied = e7_sign_counts(complete[profit])
        comparison_zh.append(
            f"{complete[profit].mean():+.1f}（{better}/{worse}/{tied}）"
        )
        comparison_en.append(
            f"{complete[profit].mean():+.1f} ({better}/{worse}/{tied}) versus "
            f"{en_labels[label]}"
        )
    controlled = int(decision.get("controlled_arm_failure_count", -1))
    if controlled < 0:
        raise RuntimeError("E7 abstract lacks the controlled-failure count")
    misses = int(paired_summary["full_stage_deadline_miss_count"].sum())
    comparable = int(paired_summary["full_deadline_comparable_stage_count"].sum())
    timing_zh = (
        f"完整机制有{misses}个阶段超过下一触发间隔，故仅支持批量滚动决策解释"
        if misses
        else f"完整机制的{comparable}个可比较阶段均满足实时响应条件"
    )
    timing_en = (
        f"{misses} complete-mechanism stages exceed the next-trigger interval, so the results support batch rolling decision support rather than real-time optimization"
        if misses
        else f"all {comparable} comparable complete-mechanism stages satisfy the real-time response condition"
    )
    replay = replay_summary.copy()
    replay["pooled_charging_reduction_pct"] = pd.to_numeric(
        replay["pooled_charging_reduction_pct"], errors="raise"
    )
    replay_count = int(pd.to_numeric(replay["stream_day_count"], errors="raise").sum())
    if replay_count != 840:
        raise RuntimeError("E7 abstract does not summarize exactly 840 replay pairs")
    low = float(replay["pooled_charging_reduction_pct"].min())
    high = float(replay["pooled_charging_reduction_pct"].max())
    zh = (
        f"动态正式矩阵形成{len(complete)}/30个四臂完整配对；完整机制相对禁合作、"
        f"无参与底线和顺序插单的全日净收益差均值及改善/变差/持平数分别为"
        f"{'、'.join(comparison_zh)}，并保留{controlled}个受控不可执行单元；"
        f"{timing_zh}。28日电网日零路径搜索重放显示，六个网络—责任单元的"
        f"充电排放降幅为{low:.2f}\\%--{high:.2f}\\%。"
    )
    en = (
        f"The formal dynamic matrix yields {len(complete)}/30 complete four-arm pairs. "
        "Mean full-day net-profit differences (better/worse/tied) for the complete mechanism are "
        f"{'; '.join(comparison_en)}, while {controlled} controlled non-executable task units are retained; "
        f"{timing_en}. A zero-route-search replay over 28 grid days gives charging-emission reductions "
        f"of {low:.2f}\\%--{high:.2f}\\% across the six network--responsibility cells."
    )
    return zh + "\n", en + "\n"


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
    pair_rows = pd.read_csv(E7_AUDIT / "raw_runs.csv")
    task_status = pd.read_csv(E7_AUDIT / "task_status.csv")
    replay = pd.read_csv(E7_REPLAY / "summary.csv")
    if len(paired) != 6 or len(replay) != 6:
        raise RuntimeError("E7 manuscript summaries must each contain six cells")
    networks = E7_NETWORK_LABELS
    conditions = E7_CONDITION_LABELS

    comparisons = (
        (
            "禁合作",
            "full_minus_no_cooperation_net_profit_mean",
            "full_minus_no_cooperation_revenue_mean",
            "full_minus_no_cooperation_cost_mean",
            "full_minus_no_cooperation_completed_customer_count_mean",
            "full_minus_no_cooperation_completed_demand_mean",
        ),
        (
            "无参与底线",
            "full_minus_no_participation_net_profit_mean",
            "full_minus_no_participation_revenue_mean",
            "full_minus_no_participation_system_cost_mean",
            "full_minus_no_participation_completed_customer_count_mean",
            "full_minus_no_participation_completed_demand_mean",
        ),
        (
            "顺序插单",
            "full_minus_simple_insertion_net_profit_mean",
            "full_minus_simple_insertion_revenue_mean",
            "full_minus_simple_insertion_cost_mean",
            "full_minus_simple_insertion_completed_customer_count_mean",
            "full_minus_simple_insertion_completed_demand_mean",
        ),
    )
    lines = [
        r"\begin{tabular*}{0.99\linewidth}{@{\extracolsep{\fill}}lllrrrrr@{}}",
        r"\toprule",
        r"网络 & 客户责任 & 完整机制相对 & $\Delta$净收益 & $\Delta$收入 & $\Delta$成本 & $\Delta$客户 & $\Delta$需求 \\",
        r"\midrule",
    ]
    for row in paired.itertuples(index=False):
        if int(row.paired_complete_stream_count) <= 0:
            raise RuntimeError(
                f"E7 cell has no four-arm executable stream: {row.network}/{row.condition}"
            )
        for label, profit, revenue, cost, customers, demand in comparisons:
            lines.append(
                f"{networks[row.network]} & {conditions[row.condition]} & {label} & "
                f"{float(getattr(row, profit)):+.1f} & "
                f"{float(getattr(row, revenue)):+.1f} & "
                f"{float(getattr(row, cost)):+.1f} & "
                f"{float(getattr(row, customers)):+.2f} & "
                f"{float(getattr(row, demand)):+.1f} " + r"\\"
            )
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_table("e7_dynamic_policy_comparison.tex", lines)

    lines = [
        r"\begin{tabular*}{0.99\linewidth}{@{\extracolsep{\fill}}llrrrrrrr@{}}",
        r"\toprule",
        r"网络 & 客户责任 & 四臂可执行 & 配对/参与 & 跨场流 & 超时阶段 & 完整/禁合作 & 完整/无底线 & 完整/顺序插单 \\",
        r"\midrule",
    ]
    for row in paired.itertuples(index=False):
        executable = "/".join(
            str(int(value))
            for value in (
                row.full_executable_stream_count,
                row.no_cooperation_executable_stream_count,
                row.no_participation_executable_stream_count,
                row.simple_insertion_executable_stream_count,
            )
        )
        complete = int(row.paired_complete_stream_count)
        lines.append(
            f"{networks[row.network]} & {conditions[row.condition]} & "
            f"{executable} & "
            f"{complete}/{int(row.full_day_participation_floor_met_count)} & "
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
    write_table(
        "e7_dynamic_interpretation.tex",
        render_e7_interpretation(pair_rows, task_status, paired, replay, decision).splitlines(),
    )
    write_table(
        "e7_dynamic_conclusion.tex",
        render_e7_conclusion(pair_rows, paired, replay, decision).splitlines(),
    )
    abstract_zh, abstract_en = render_e7_abstracts(pair_rows, paired, replay, decision)
    write_table("e7_dynamic_abstract_zh.tex", abstract_zh.splitlines())
    write_table("e7_dynamic_abstract_en.tex", abstract_en.splitlines())


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
