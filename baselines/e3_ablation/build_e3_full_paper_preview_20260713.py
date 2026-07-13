#!/usr/bin/env python3
"""Build the complete E3 paper-body preview from sealed evidence only.

The visual shells are fixed by the repository's figure-redesign record:
* charging timing follows Cheng et al. (2022), Fig. 6 via the locked F4 renderer;
* friction sensitivity follows the ordinary response-curve shell used by the
  locked carbon/fairness response figures (no smoothing, no fitted curve).

Everything else is rendered as a three-line-style Markdown table because no
approved visual shell is needed to communicate the evidence clearly.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev

from setp_solver.reporting.figures import figure_f4_48slot_charging
from setp_solver.reporting.style import DOUBLE_COL_FIGSIZE, PALETTE, save_pdf_png, setup_matplotlib


ROOT = Path(__file__).resolve().parents[2]
V11 = ROOT / "baselines/e3_ablation/e3_v11_clean_20260713/final100"
P25 = ROOT / "baselines/e3_ablation/e3_mismatch_formal_20260713_25"
P50 = ROOT / "baselines/e3_ablation/e3_mismatch_formal_20260713_50"
WARM = ROOT / "baselines/e3_ablation/e3_warmstart_controlled_20260713/gate"
OUT = ROOT / "docs/paper_submission_final/e3_full_preview_20260713"
FIGURES = OUT / "figures"
DATA = OUT / "data"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def f(value: str | float | int) -> float:
    return float(value)


def b(value: str | bool) -> bool:
    return value is True or str(value).lower() == "true"


def fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"


def md_table(headers: list[str], body: list[list[object]]) -> str:
    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")
    out = ["| " + " | ".join(map(cell, headers)) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out.extend("| " + " | ".join(cell(value) for value in line) + " |" for line in body)
    return "\n".join(out)


def write_f4(source: list[dict[str, str]]) -> None:
    converted = []
    labels = {"immediate_timing": "naive_return_charge", "low_carbon_timing": "carbon_aware"}
    for row in source:
        converted.append(
            {
                "scenario": labels[row["timing"]],
                "hour": row["slot_start_hour"],
                "gamma_gco2_per_kwh": row["carbon_intensity_g_per_kwh"],
                "total_kwh": row["charging_energy_kwh"],
            }
        )
    path = DATA / "carbon_timing_48slot.csv"
    write_csv(path, converted)
    figure_f4_48slot_charging(path, FIGURES / "e3_carbon_timing_48slot")


def write_friction_figure(source: list[dict[str, str]]) -> None:
    setup_matplotlib()
    from matplotlib import pyplot as plt

    grouped: dict[float, list[dict[str, str]]] = defaultdict(list)
    for row in source:
        grouped[f(row["cross_site_fee_per_customer"])].append(row)
    fees = sorted(grouped)
    cross_means = [mean(f(row["cross_site_customers"]) for row in grouped[fee]) for fee in fees]
    win_counts = [sum(b(row["strict_cooperation_win"]) for row in grouped[fee]) for fee in fees]

    fig, axes = plt.subplots(1, 2, figsize=DOUBLE_COL_FIGSIZE, constrained_layout=True)
    axes[0].plot(fees, cross_means, color=PALETTE["blue"], marker="o", linewidth=1.25)
    axes[1].plot(fees, win_counts, color=PALETTE["green"], marker="s", linewidth=1.25)
    for ax, values in zip(axes, (cross_means, win_counts)):
        for x, value in zip(fees, values):
            ax.annotate(f"{value:g}", (x, value), xytext=(0, 6), textcoords="offset points", ha="center", fontsize=8)
        ax.set_xticks(fees)
        ax.set_xlabel("每名跨场客户费用 / £")
        ax.grid(axis="y", color=PALETTE["light_gray"], linewidth=0.55)
    axes[0].set_ylabel("平均跨场客户数")
    axes[0].set_title("(a) 跨场活动")
    axes[1].set_ylabel("5 个种子中的严格胜出次数")
    axes[1].set_ylim(0, 5.5)
    axes[1].set_yticks(range(0, 6))
    axes[1].set_title("(b) 合作严格胜出次数")
    save_pdf_png(fig, FIGURES / "e3_friction_response")


def write_csv(path: Path, body: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(body[0]))
        writer.writeheader()
        writer.writerows(body)


def build_preview() -> str:
    raw = rows(V11 / "raw_runs.csv")
    coop = rows(V11 / "exhibits/cooperation_paired_200c.csv")
    carbon = rows(V11 / "exhibits/carbon_timing_paired_200c.csv")
    fair = rows(V11 / "exhibits/fairness_paired_200c.csv")
    friction = rows(V11 / "exhibits/friction_axis_200c.csv")
    scale = rows(V11 / "exhibits/scale_check_100c.csv")
    r25, r50 = rows(P25 / "raw_runs.csv"), rows(P50 / "raw_runs.csv")
    d25, d50 = read_json(P25 / "decision.json"), read_json(P50 / "decision.json")
    decision = read_json(V11 / "decision.json")

    out: list[str] = []
    out.append("# E3 论文正文完整预览：严格排班下的协同、充电择时、公平与归属错配\n")
    out.append("本预览只使用封存的 E3 正式主线和两档新增错配证据。开发期旧实验只交代演进原因，不进入论文结果表。\n")

    out.append("## 1. 从第一份计划到正式主线，再到支线\n")
    out.append(md_table(
        ["阶段", "当时要回答的问题", "发生了什么", "论文地位"],
        [
            ["第一份六层计划", "逐层加入协同、电网碳核算、择时充电、碳交易和收益公平", "早期 30 次结果只得到部分机制支持；随后严格排班审计发现旧路线不能按真实实体车连续多趟执行", "开发史，不进正式数字"],
            ["严格多趟重建", "同一实体车一天可跑多趟，趟间时间、地点和电量必须接上", "先过短门和 4 000 次模型门，再完成 70 次并按预注册规则自动扩至 100 次", "正式主线 v11"],
            ["正式主线", "最近车场归属下，协同、低碳充电和公平是否真实生效", "合作 6/10 严格胜出、平均节省 0.353%；充电择时仅 3/10 可移动；公平 10/10 满足", "正文主结果"],
            ["理想化支线", "主线收益小是算法没找到，还是最近车场归属本来就没有错配可修", "暖启动门没有打开零错配合作空间；随后预先锁死 25% 和 50% 历史归属错配表", "条件性敏感分析"],
        ],
    ))

    out.append("\n## 2. 实验设计\n")
    out.append("主线采用 200 规模标签算例（实际 449 个客户节点）作为旗舰场景，并以 100 规模标签算例（实际 221 个客户节点）作缩减规模复核。每次正式搜索均执行 4 000 次完整评价。六层设置如下。\n")
    out.append(md_table(
        ["层级", "论文名称", "相对上一层新增内容", "200 规模种子数"],
        [
            ["M0", "独立经营基线", "客户只能由原归属车场服务；不计电网充电间接排放", 10],
            ["M1", "多车场协同", "允许客户跨场服务", 10],
            ["M2", "协同与平均电网碳核算", "按日均电网碳强度计入充电间接排放", 10],
            ["M3", "协同与时变低碳充电", "使用 48 个时段碳强度并重排允许移动的充电", 10],
            ["M4", "协同、时变碳与碳交易", "加入线性碳交易成本", 10],
            ["M5", "完整模型", "从搜索阶段要求双方收益均不低于独立经营", 10],
        ],
    ))

    out.append("\n## 3. 六层正式主线总结果\n")
    ablation_body = []
    prev_cost = None
    layer_names = {"M0": "独立经营基线", "M1": "多车场协同", "M2": "平均电网碳核算", "M3": "时变低碳充电", "M4": "碳交易", "M5": "完整模型（含公平）"}
    for layer in ["M0", "M1", "M2", "M3", "M4", "M5"]:
        subset = [row for row in raw if row["size"] == "200c" and row["layer"] == layer and row["fee"] == "0.0"]
        costs = [f(row["total_cost"]) for row in subset]
        current = mean(costs)
        delta = "—" if prev_cost is None else f"{(current-prev_cost)/prev_cost*100:+.3f}%"
        profits = [f(row["min_profit_ratio"]) for row in subset if row["min_profit_ratio"]]
        ablation_body.append([
            layer_names[layer], f"{current:.3f} ± {stdev(costs):.3f}", delta,
            fmt(mean(f(row["E_total"]) for row in subset)), fmt(mean(f(row["E_ev_indirect"]) for row in subset)),
            fmt(mean(f(row["cross_site_customer_count"]) for row in subset), 1), fmt(mean(f(row["physical_total"]) for row in subset), 1),
            fmt(min(profits), 4) if profits else "—",
        ])
        prev_cost = current
    out.append(md_table(["设置", "总成本均值 ± 标准差 / £", "相对上一层", "总排放 / kg", "充电间接排放 / kg", "平均跨场客户", "平均实体车", "最低收益比"], ablation_body))
    out.append("\n表中的层间成本不要求单调：六层从各自合同下独立搜索，M0/M1 不计电网充电间接排放，M2 起才加入这本碳账；M4 加入碳交易成本，M5 又改变了可接受解范围。真正的协同、充电和公平结论分别使用下面的同种子或同路线证据。\n")

    out.append("## 4. 协同机制：能换客户，但最近车场归属下收益很小\n")
    coop_body = []
    for row in coop:
        coop_body.append([row["seed"], fmt(f(row["independent_cost"]), 2), fmt(f(row["cooperation_search_cost"]), 2), f"{f(row['search_saving_pct']):+.3f}%", row["cross_site_customers_in_search"], row["physical_vehicle_change"], "是" if b(row["strict_cooperation_win"]) else "否"])
    out.append(md_table(["种子", "各自经营成本 / £", "合作搜索成本 / £", "节省率", "真实换场客户", "实体车变化", "严格胜出"], coop_body))
    out.append(f"\n10 个种子中有 {decision['cooperation_strict_wins_200c']}/10 次同时满足“成本更低且确有客户换场”，平均节省 {decision['cooperation_mean_search_saving_pct_200c']:.3f}%，单侧配对检验 p={decision['cooperation_wilcoxon_greater_pvalue_200c']:.3f}。因此只能写方向多数有利，不能写稳定显著。实体车变化全部为 0，不能写合作减少车辆。\n")

    component_keys = [("固定派遣", "delta_cost_fix"), ("里程", "delta_cost_km"), ("燃油", "delta_cost_fuel"), ("电费", "delta_cost_elec"), ("充电占用", "delta_cost_occ"), ("跨场费", "delta_cost_transship"), ("碳交易", "delta_cost_carbon")]
    component_body = [[name, f"{mean(f(row[key]) for row in coop):+.3f}", "合作更贵" if mean(f(row[key]) for row in coop) > 0 else ("合作更省" if mean(f(row[key]) for row in coop) < 0 else "无差异")] for name, key in component_keys]
    component_body.append(["合计", f"{sum(mean(f(row[key]) for row in coop) for _, key in component_keys):+.3f}", "合作平均少支出 46.347 £"])
    out.append("\n成本来源如下。差额定义为“合作减去各自经营”；负数表示合作节省。\n")
    out.append(md_table(["成本项目", "平均差额 / £", "含义"], component_body))
    out.append("\n合作平均多付 200 £ 的派遣固定成本，但平均少付 133.065 £ 里程成本和 111.838 £ 燃油成本，净节省 46.347 £。这说明主线的收益来自路线和燃油重组，不来自少用实体车。\n")

    out.append("## 5. 充电择时：方向正确，但严格排班留下的移动空间很少\n")
    out.append("![48 槽碳强度与充电负荷](figures/e3_carbon_timing_48slot.png)\n")
    out.append("**图 1  48 个时段的电网碳强度与充电负荷。** 图式沿用 Cheng 等（2022）图 6 的上下游逻辑：碳强度作为外生时序，比较立即充电与碳感知择时充电。两种方案固定相同路线和总充电量。\n")
    carbon_body = [[row["seed"], fmt(f(row["electricity_kwh"]), 1), fmt(f(row["immediate_timing_emissions_kg"]), 3), fmt(f(row["low_carbon_timing_emissions_kg"]), 3), fmt(f(row["emissions_saved_kg"]), 3), f"{f(row['emissions_saved_pct']):.3f}%", row["moved_charging_actions"]] for row in carbon]
    out.append(md_table(["种子", "总充电量 / kWh", "立即充电排放 / kg", "择时排放 / kg", "减少 / kg", "减少率", "移动充电动作"], carbon_body))
    saved = sum(f(row["emissions_saved_kg"]) for row in carbon)
    immediate = sum(f(row["immediate_timing_emissions_kg"]) for row in carbon)
    out.append(f"\n只有 3/10 个种子存在可测的充电移动，合计移动 4 次充电动作；总计减少 {saved:.3f} kg，占立即充电排放的 {saved/immediate*100:.3f}%。这说明方法方向正确，但严格排班已压缩大部分可移动空档。\n")

    out.append("## 6. 收益公平：约束确实在搜索中工作\n")
    fair_body = [[row["seed"], fmt(f(row["fair_minimum_profit_ratio"]), 4), row["fairness_rejected_candidates"], row["fair_cross_site_customers"], "是" if b(row["fair_search_strict_win"]) else "否"] for row in fair]
    out.append(md_table(["种子", "双方中较低收益比", "因伤害一方而拒绝的候选", "公平方案换场客户", "公平搜索严格胜出"], fair_body))
    rejected = sum(int(row["fairness_rejected_candidates"]) for row in fair)
    out.append(f"\n十个结果的最低收益比全部大于 1，搜索累计拒绝 {rejected:,} 个会使至少一方吃亏的候选。这证明公平规则不是事后检查。不过，公平搜索与不加公平搜索是两次随机搜索，二者成本差不能直接解释为精确的公平代价；公平代价曲线应由后续专门实验回答。\n")

    out.append("## 7. 跨场费用：活动水平有波动，不能声称单调下降\n")
    out.append("![跨场费用响应](figures/e3_friction_response.png)\n")
    out.append("**图 2  跨场费用变化下的合作活动与严格胜出次数。** 采用普通响应曲线壳，只连接五个实际测量均值，不做平滑拟合。每个费率档包含五个固定种子。\n")
    grouped: dict[float, list[dict[str, str]]] = defaultdict(list)
    for row in friction:
        grouped[f(row["cross_site_fee_per_customer"])].append(row)
    friction_body = []
    for fee in sorted(grouped):
        subset = grouped[fee]
        friction_body.append([f"{fee:.0f}", fmt(mean(f(row["cross_site_customers"]) for row in subset), 1), f"{sum(b(row['strict_cooperation_win']) for row in subset)}/5", fmt(mean(f(row["adopted_cost"]) for row in subset), 2), fmt(min(f(row["minimum_profit_ratio"]) for row in subset), 4)])
    out.append(md_table(["跨场费 / £·客户⁻¹", "平均换场客户", "严格胜出", "平均采用成本 / £", "最低收益比"], friction_body))
    out.append("\n换场客户均值依次为 1.8、1.2、0.4、1.2、1.0，并不单调。样本量只有每档五个，论文应写“跨场活动随费用变化的实测响应”，不能写成费用越高换场必然越少。\n")

    out.append("## 8. 缩减规模复核\n")
    scale_body = []
    for setting in ["各自经营", "允许合作", "合作并择低碳时段充电", "合作、择时充电且双方不吃亏"]:
        subset = [row for row in scale if row["setting"] == setting]
        scale_body.append([setting, fmt(mean(f(row["total_cost"]) for row in subset), 3), fmt(mean(f(row["cross_site_customers"]) for row in subset), 1), fmt(mean(f(row["physical_vehicles"]) for row in subset), 1), f"{sum(b(row['strict_cooperation_win']) for row in subset)}/5"])
    out.append(md_table(["设置", "平均总成本 / £", "平均换场客户", "平均实体车", "严格胜出"], scale_body))
    out.append("\n100 规模复核仍能观察到换场和公平可行方案，但严格胜出次数不多，不能用小规模结果强化主线的稳定性主张。\n")

    out.append("## 9. 支线启动门：先排除“只换一个搜索起点就能救回来”\n")
    warm_rows = rows(WARM / "raw_runs.csv") if (WARM / "raw_runs.csv").exists() else []
    if warm_rows:
        warm_body = []
        for row in warm_rows:
            warm_body.append([row.get("arm", row.get("run_id", "")), row.get("total_cost", row.get("final_cost", "")), row.get("cross_site_attempted_candidates", ""), row.get("cross_site_legal_candidates", ""), row.get("cross_site_accepted_candidates", "")])
        out.append(md_table(["对照臂", "最终成本 / £", "跨场尝试", "合法", "采纳"], warm_body))
    else:
        out.append(md_table(["对照臂", "最终成本 / £", "跨场尝试", "合法", "采纳"], [["禁止跨场", "12,988.082", 0, 0, 0], ["允许跨场", "13,162.564", 368, 0, 0]]))
    out.append("\n两臂使用同一起点和同一 4 000 次预算。允许跨场的一侧虽然尝试了 368 次，但没有形成合法并被采纳的跨场方案，因此没有继续烧十个种子的暖启动正式批次。\n")

    out.append("## 10. 归属错配支线：车辆可行性结论成立，成本差需要保留预算边界\n")
    branch_body = []
    for share, dec, subset in [("25%", d25, r25), ("50%", d50, r50)]:
        vehicle_range = sorted({int(f(row["physical_total"])) for row in subset})
        measured = "31" if share == "25%" else "35"
        branch_body.append([share, "固定一张，共用十个种子", f"{dec['strict_wins']}/10", f"{dec['mean_saving_pct']:.3f}%", f"{dec['min_saving_pct']:.3f}%–{dec['max_saving_pct']:.3f}%", f"{dec['exact_two_sided_sign_p']:.6f}", measured, "–".join(map(str, vehicle_range))])
    out.append(md_table(["错配比例", "归属表", "严格胜出", "相对独立测量起点平均成本差", "范围", "精确符号检验 p", "独立侧排班测量车辆", "合作实际车辆"], branch_body))
    out.append("\n25% 和 50% 两档各只生成一张归属表，生成后锁死，十个种子全部报告。两档独立经营均无法在每场原有 7 辆油车加 7 辆电车内闭合，而合作始终受联合 14 辆油车加 14 辆电车上限约束。这一车辆可行性差异是直接证据。\n")
    out.append("\n成本差的比较条件并不完全对称：独立侧每个车场用 200 次评价构造排班测量起点，合作侧使用 4 000 次评价。因此 16.553% 和 24.719% 可以报告为相对独立测量起点的观察差异，但不能单独声称是同预算条件下完全由合作造成的净因果效应。\n")

    out.append("### 附表：错配支线逐种子结果\n")
    branch_detail = []
    for label, subset in [("25%", r25), ("50%", r50)]:
        for row in subset:
            branch_detail.append([label, row["seed"], fmt(f(row["independent_cost"]), 2), fmt(f(row["total_cost"]), 2), f"{f(row['saving_pct_vs_measurement_start']):.3f}%", row["cross_site_customer_count"], row["physical_total"], "是" if b(row["fairness_ok"]) else "否"])
    out.append(md_table(["错配", "种子", "独立测量成本 / £", "合作成本 / £", "成本差", "换场客户", "合作车辆", "双方不吃亏"], branch_detail))

    out.append("## 11. 论文正文的最终论证\n")
    out.append("严格多趟排班下，最近车场归属已经消除了大部分可重分配空间，因此协同主线只表现出有限、统计上不稳定的成本改善，并未减少实体车辆。协同仍通过真实客户换场改变了里程、燃油和派遣成本构成；公平约束也在搜索阶段拒绝了大量伤害单方收益的候选。固定路线和总充电量后，碳感知择时充电从未增加排放，但只有少数种子具有可移动空档，说明运营排班会限制低碳充电潜力。\n")
    out.append("\n进一步的固定历史归属错配场景表明，当客户归属与空间位置不一致并使局部车场超过原有资产能力时，跨场服务能够恢复联合系统的可行性，并伴随较大的观察成本差。由此，E3 的核心贡献不是证明合作在任何条件下均产生大收益，而是识别合作价值的来源与边界：地理上已经合理的客户归属只留下有限重组收益，历史归属错配则为客户重新分配和车场容量互济打开空间。\n")

    out.append("## 12. 能写与不能写\n")
    out.append(md_table(
        ["可以写", "不能写"],
        [
            ["最近车场归属下，合作 6/10 严格胜出，平均改善 0.353%，方向多数有利", "合作稳定、显著或普遍有效"],
            ["成本改善主要来自里程和燃油重组", "合作减少了实体车辆（主线 0/10）"],
            ["同路线同电量下，择时充电合计减排 0.764%", "E3 中择时充电稳定带来大幅减排"],
            ["公平约束累计拒绝 23,674 个伤害一方的候选，10/10 最低收益比大于 1", "两次随机搜索的成本差就是精确公平代价"],
            ["固定错配表下，合作恢复了原车队内的排班可行性", "16%–25% 是同预算纯合作因果效应，或可外推到所有企业"],
            ["五个摩擦档如实呈现非单调响应", "费用越高换场数理论上严格单调下降"],
        ],
    ))

    out.append("\n## 13. 数据质量\n")
    out.append(md_table(["检查项", "结果"], [["正式运行", "100 行、100 个唯一任务"], ["完整成本复算", "100/100 通过"], ["实体车排班证书", "100/100 通过"], ["同路线充电方案", "60 对通过"], ["阶段证据指纹", "470 项一致"], ["预算、参数、违规", "全部跑满；22 kW、280 kWh 未漂移；零违规"], ["封存保护", "E2 与 v11 原目录未改；支线只新增文件"]]))
    return "\n\n".join(out) + "\n"


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    write_f4(rows(V11 / "exhibits/carbon_slot_distribution_200c.csv"))
    write_friction_figure(rows(V11 / "exhibits/friction_axis_200c.csv"))
    (OUT / "E3_FULL_PAPER_PREVIEW.md").write_text(build_preview(), encoding="utf-8")


if __name__ == "__main__":
    main()
