#!/usr/bin/env python3
"""生成论文 4.4.3 第一部分的总表（`tab:policy-survey`，既有减排方案及本文实测参数）。

2026-09-09 用户定的 4.4.3 三部分结构里，第一部分要回答"别人是否碰到同类/相似问题、
怎么解决"，**只列本文实测过的方案**（未实测的措施一律不进表）。

## 2026-09-09 晚精简为三列（用户原话："表 11 只要类型、方案、本文实测参数加引用，
## 简单不占版面"）

原来的六列（类别 / 方案 / 代表研究或政策 / 研究情境 / 报告的效果 / 本文实测设定）
整整占掉一个版面（编译核对：旧版表 11 独占正文第 19 页）。现在只留三列：

    类别 | 方案（文献引用直接挂在方案名上）| 本文实测参数

"代表研究或政策"列并入"方案"列的 `\\cite`；"研究情境"与"报告的效果"两列删除——这两列
的内容在 4.4.3 正文第一段已用一两句话交代，不必在表里重复一遍。
**`ROWS` 里的 `context` / `effect` 两个字段保留但不再输出**，因为它们逐字对应下面
docstring 里那批页码级取证，删掉等于把取证结果一并丢掉；要恢复六列版只需把这两个
键重新接回 `build_table()`。

"本文实测参数"列只写参数本身（碳价三档、配额 200 kg、补贴 24 元/日、谷段 1—6 时与
12—15 时、午间谷价 0.563 元/kWh），不再写"其余参数不变""从固定成本中扣除"之类的
口径说明——那些也在正文里。

## 这张表里没有任何求解器数字

三列全是文献内容与实验设定的文字，**不读 `best_solution.json`、不聚合、不算均值**。
实测出来的成绩在表 `tab:fleet-levels`（`build_policy_table.py`）里，两张表的类别用词
必须逐字一致（碳规制政策 / 购置端财政激励 / 需求响应政策），否则读者没法把两张表对起来。

## 每一格的出处（页码只写在这里，不进表）

**取证工具与自检**：陈婉茹 2023 / Qiu 2024 / Wilson 2026 / Wu 2022 用 `pdftotext` 抽本地
Zotero PDF，抽取前先用文中已知高频词自检（陈婉茹 2023 全文"碳交易"63 次命中，非扫描件）。
**李进和张江华 2014 的 PDF 抽取器不可用**（全文"碳交易"0 命中，而标题里就有这个词），
改用 `pdftoppm -r 140` 渲染第 1 页 PNG 目视核对——缺失证据不等于证据缺失。

### 行 1　碳税／单位碳价
- 陈婉茹等 2023, 系统工程理论与实践 43(11): 3320--3335（Zotero `NKRC4JZU`）
  - 研究情境：p.3320 摘要——"基于限额碳交易机制, 考虑由传统燃油车和电动车构成的混合动力
    车队, 研究多配送中心车辆路径-速度联合优化问题"
  - 报告的效果：p.3332 §5.2.1 逐字——"碳排放量随着单位碳价的增长呈'阶梯式'下降…只有当
    单位碳价超过一定临界值时, 电动车置换带来的油耗成本和碳交易成本的降幅才会大于固定成本
    和电耗成本的增幅"；p.3333 图 4(a)——单位碳价 0→2.2 元/kg 时燃油车占比 95.83%→83.33%
- Qiu 等 2024, IJPR 62(16): 5720--5736（Zotero `QLD6M6FA`）
  - 研究情境：p.5720 摘要——同时使用内燃机车与电动车的车队管理，考察碳限额/碳税/碳交易/
    碳抵消四类规制
  - 报告的效果：p.5731 §5.2.3 逐字——"When the CT rate is lower than 0.1 yuan/kg, there is
    no notable change in CEs. For CT rates between 0.1 yuan/kg and 1 yuan/kg, CEs are
    significantly reduced by 85.79%, while the cost increases by 5.58%. When the CT rate is
    between 2 yuan/kg and 5 yuan/kg, CEs drop to zero"

### 行 2　限额碳交易／碳配额
- 李进和张江华 2014, 系统工程理论与实践 34(7): 1779--1787（Zotero `5EI8GKNS`）
  - 研究情境与效果：p.1779 摘要（**渲染目视**）——"针对碳排放交易机制下的物流配送路径问题,
    引入考虑车辆装载重和速度的碳排放度量方法, 以 TSP 为基本参考模型…说明碳排放交易机制下的
    路径安排策略能够有效减少碳排放"
- 陈婉茹等 2023（同上）
  - 报告的效果：p.3332 逐字——"不同碳限额下求解得到的方案碳排量几乎相同, 这是因为碳限额与
    决策变量在模型中没有直接的关系, 理论上该值的变化不会改变最佳配送路径"；p.3333 逐字——
    "政府实行限额碳交易政策只能初步推进新能源车辆在物流配送中的使用"

### 行 3　购置补贴
- Hardman 等 2017, RSER 80: 1100--1111
  - **Zotero 库里没有这一篇**（`zotero_search_items` 查 "Hardman" 零命中），Crossref 无摘要
    字段，出版商正文付费墙。摘要**逐字取自 RePEc 书目页**
    （ideas.repec.org/a/eee/rensus/v80y2017icp1100-1111.html）＝【已核摘要】，**不是原文页码**。
  - 研究情境（摘要）：全球插电式电动车市场购置端财政激励效果的系统性文献综述；文中记录的
    激励额度约 2500--20000 美元/辆
  - 报告的效果（摘要逐字）："Incentives should be applied when someone is buying a PEV, not
    afterwards… VAT and purchase tax exemptions for PEVs are most effective… the premature
    removal of incentives could negatively affect PEVs"
  - 四类激励的原文分类见 `docs/handoff/policy_instrument_taxonomy_from_reviews_20260908.md`
    §S2，那是**机构报告版 UCD-ITS-RR-17-24 §1.2 pp.3--4** 的页码，**期刊版对应页未核**。
- Wilson 等 2026, PLOS Complex Systems 3(2): e0000092（Zotero `HRACHIV5`）
  - 研究情境：p.1 摘要与 §3——供应链货运重型电动车（HGEV）的双目标绿色车辆路径方法，同时
    纳入碳税、排放交易与 HGEV 购置补贴三类政策
  - **该文未报告实测减排效果**：§5 讨论 p.18--19 与 §6 结论 p.19 自述仍是 theoretical
    framework，只用沃尔玛安大略东部供应网的小算例演示可解性。可引的是参数与定性判断：
    §5 p.18 逐字 "the price differential between a CFV and the equivalent HGEV ranges from
    \\$75,000 to \\$250,000, which… may be made up for in many areas with strong subsidy
    incentives"；Table 4 p.18 "Suggested range of values for Sk: \\$5,000 USD to \\$300,000 USD"；
    补贴 Sk 从购置成本 Ak 中扣除（式 3.4），只含资本性支出类补贴。
    表内该格因此如实写"未报告实测减排效果"，不编造数字。

### 行 4　分时电价谷段设在午间
- 河北省发展和改革委员会《关于进一步完善河北南网工商业及其他用户分时电价政策的通知》
  冀发改能价〔2022〕1364 号
  - **一次源未取到**（省政府信息公开页不可达、地市转发页正文为图片、PDF 直链 404）。时段
    数字来自两家行业媒体的逐字转述，并与仓库官方电价快照对该文号与浮动比例的引用互核，
    取证过程见 `docs/handoff/hebei_tou_provenance_20260904.md`＝【已核二手】。
  - 适用对象（研究情境列）：河北南网工商业及其他用户
  - 规定内容（报告的效果列）：冬季（12、1、2 月）与其他季节（3--5、9--11 月）低谷时段均为
    "1—6 时、12—15 时"，午间进入低谷；全国已有 13 个省区在午间光伏大发时段执行低谷或深谷电价
  - 政策文件不报告成本或排放的实测效果，该列写的是文件规定的内容，不是测得的效应。

### 行 5　午间充电按谷价补贴
- Wu, Yücel, Zhou 2022, M&SOM 24(5): 2481--2499（Zotero `ZX8ZR82C`；本地 PDF 是出版商网页
  打印版，只含摘要页，**正文页码未核**）
  - 研究情境（摘要）：公用事业公司经营充电站的智能充电业务模式，机制设计问题，采用美国最大
    电力市场的实际用电与发电数据
  - 报告的效果（摘要逐字）："we find that cost and emissions savings from smart charging are
    approximately 20% and 15%, respectively, during a typical summer month"

## "本文实测设定"列的出处（全部来自实际跑过的命令行，不是文字描述）

- 碳价三档：`carbon_price_sweep_v3_20260906/P=0.07502`、`grid2x2_v3_20260906/beijing/P=1.0`、
  `carbon_price_sweep_v3_20260906/P=1.5`
- 碳配额：`policy_combos_20260907/quota200`，命令行 `--carbon-quota-kg 200`，碳价 0.2；
  碳成本按式 (5) `p^c(E_total − Ebar)` 结算，超额买入与结余卖出同价
- 购置补贴：`policy_combos_20260907/subsidy_alone`，命令行 `--ev-daily-premium 76`
  （默认溢价 100 元/日，减 24 即补贴 24 元/(辆·日)，直接进 `cost_fix`；已核 2 燃油＋4 电动的
  `cost_fix`＝2×170＋4×(270−24)＝1324.00 与落盘逐位相同）
- 谷段设在午间：`grid2x2_v3_20260906/midday/P=0.2`，日历
  `data/ChinaInstances/china81_cf_calendar_midday_valley_v1_20260904`（只挪时段结构，
  日均未加权电价与原日历逐位相等）
- 午间充电按谷价补贴：`policy_combos_20260907/green_window`，日历
  `data/ChinaInstances/china81_cf_calendar_midday_discount_v1_20260904`
  （12:00--15:00 六个半小时槽电度价压到谷价 0.56328575 元/kWh，差价由财政补足）

## 版式

`\\setptabsetup`（`paper_main.tex` 第 62 行的宏，内含 `\\small`，与前文各表一致）。
三列改用**普通 `tabular` ＋ 固定 `p{}` 宽度**，不再用 `tabularx`／`\\hsize` 加权：只剩
三列时按内容定宽比按比例分宽更好看，也不必再和 `X` 列的宽度分配打架。
列宽 58pt / 132pt / 224pt（＋6 个 `\\tabcolsep` 2.2pt），合计约 427pt，窄于版心
468.2pt（A4 210mm 减左右各 22.5mm），表居中排。目标期刊两篇母版（陈婉茹等 2023
表 8--11、陈雨蝶等 2025 表 10--13）的表都窄于版心并居中，不是一律拉满。

类别列用 `\\multirow` 竖向合并，**只跨 1 行的类别不套 `\\multirow`**——`\\multirow`
会把单元格高度定死（这条是 `build_policy_table.py` 踩出来的，原样沿用）。

**折行必须用 `\\shortstack`，不能用 `\\makecell`**：`\\multirow{2}{*}{\\makecell{...}}`
每次编译都报 `Overfull \\vbox (1.34pt too high)`——`\\makecell` 内部按 `\\arraystretch`
（`\\setptabsetup` 设为 0.95）算高度，与 `\\multirow` 定死的格高对不上；换成
`\\shortstack` 后 0 Overfull。类别列宽 ≥40pt（`\\small` 下 4 个汉字要 36.1pt）。

浮动体用 `[!htbp]`，不用 `[H]`（2026-09-09 版面审计：22 处 `[H]` 逼出 1.59 页空白）。

用法（仓库根，普通 python3 即可，不依赖 venv）::

    python3 solver/scripts/build_policy_survey_table.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "docs/paper_v2/generated_tables/policy_survey_table.tex"

# 类别用词与 build_policy_table.py 的 CAT_* 逐字一致，两张表才对得起来。
CAT_CARBON = "碳规制政策"
CAT_FLEET = "购置端财政激励"
CAT_DR = "需求响应政策"

# 类别名一律单行排，不折行（2026-09-09 精简为三列后改）：三列版每行只有一行文字，
# 而两行的 \shortstack 会垂直居中、把上面那行挤到相邻行的行距里去——首版三列表编译出来
# "购置端/财政激励"的第一行正好压在"限额碳交易"那一行上。类别列因此加宽到 72pt，
# 容得下最长的"购置端财政激励"（7 个 \small 汉字约 66pt）。
# 表 12（build_policy_table.py）的行高有两行文字，那里的 \shortstack 折行仍然成立，不动它。
CAT_WRAP: dict[str, str] = {}

# 每行的键：
#   category —— 第 1 列"类别"（同一类别的连续行由 \multirow 合并）
#   measure  —— 第 2 列"方案"，文献引用用 \cite 直接挂在方案名后面
#   ours     —— 第 3 列"本文实测参数"，只写参数本身
#   context / effect —— **不再输出**，保留是因为它们逐字对应 docstring 里的页码级取证
#                       （2026-09-09 精简为三列时保留，见 docstring 开头一节）
#   source   —— **不再输出**，其内容已并入 measure 的 \cite
# 每一格的页码级出处见本文件 docstring，表内不写页码。
ROWS = [
    dict(
        category=CAT_CARBON,
        measure=r"碳税（单位碳价）\cite{ref:23,ref:qiu2024}",
        source=r"陈婉茹等\cite{ref:23}；Qiu等\cite{ref:qiu2024}",
        context=(
            "多配送中心油电混合车队的路径与速度联合优化；"
            "油电混合车队在碳限额、碳税、限额碳交易与碳抵消四类规制下的路径优化"
        ),
        effect=(
            "碳排量随单位碳价的提高呈阶梯式下降，"
            "单位碳价越过临界值后电动车置换燃油车；"
            "碳价低于0.1元/kg时碳排量无明显变化，"
            "0.1--1元/kg区间碳排量下降85.79\\%而成本上升5.58\\%，"
            "2--5元/kg时碳排量降为零"
        ),
        ours="单位碳价取0.075、1.0与1.5元/kgCO$_2$e",
    ),
    dict(
        category=CAT_CARBON,
        measure=r"限额碳交易（碳配额）\cite{ref:lijin2014,ref:23}",
        source=r"李进和张江华\cite{ref:lijin2014}；陈婉茹等\cite{ref:23}",
        context=(
            "碳排放交易机制下以旅行商问题为参考模型的物流配送路径；"
            "多配送中心油电混合车队的路径与速度联合优化"
        ),
        effect=(
            "碳排放交易机制下的路径安排策略能够有效减少碳排放；"
            "碳限额与决策变量没有直接关系，不同配额下方案的碳排量几乎相同，"
            "只改变碳交易成本"
        ),
        ours="免费碳配额200 kgCO$_2$e",
    ),
    dict(
        category=CAT_FLEET,
        measure=r"购置补贴\cite{ref:hardman2017,ref:wilson2026}",
        source=r"Hardman等\cite{ref:hardman2017}；Wilson等\cite{ref:wilson2026}",
        context=(
            "全球插电式电动车市场购置端财政激励效果的文献综述；"
            "货运重型电动车的双目标绿色车辆路径方法与各国补贴额度调查"
        ),
        effect=(
            "激励在购置时点给予最为有效，增值税与购置税减免效果最好，"
            "购后返款与所得税抵免较弱，过早取消会产生负面影响；"
            "后者未报告实测减排效果，给出每辆车补贴取值区间0.5万--30万美元"
        ),
        ours=r"购置价差补贴，折24元/(辆$\cdot$日)",
    ),
    dict(
        category=CAT_DR,
        measure=r"分时电价谷段设在午间\cite{ref:hebei-tou}",
        source=r"河北南网分时电价\cite{ref:hebei-tou}",
        context=(
            "河北南网工商业及其他用户；"
            "全国已有13个省区在午间光伏大发时段执行低谷或深谷电价"
        ),
        effect=(
            "冬季与春秋季的低谷时段定为1—6时与12—15时，午间进入低谷"
        ),
        ours="低谷时段设为1—6时与12—15时",
    ),
    dict(
        category=CAT_DR,
        measure=r"午间充电按谷价补贴\cite{ref:wu2022}",
        source=r"Wu等\cite{ref:wu2022}",
        context=(
            "公用事业公司经营充电站的智能充电业务模式，"
            "采用美国最大电力市场的实际用电与发电数据"
        ),
        effect=(
            "智能充电在典型夏季月份使成本与排放分别下降约20\\%与15\\%"
        ),
        ours="12—15时按谷价0.563元/kWh计费",
    ),
]


def multirow_spans(rows: list[dict]) -> list[int | None]:
    """连续相同 category 的分段：段首行记段长，段内其余行记 None。"""
    spans: list[int | None] = [None] * len(rows)
    i = 0
    while i < len(rows):
        j = i
        while j < len(rows) and rows[j]["category"] == rows[i]["category"]:
            j += 1
        spans[i] = j - i
        i = j
    return spans


def build_table() -> str:
    spans = multirow_spans(ROWS)
    lines: list[str] = []
    lines.append(r"\begin{table}[!htbp]")
    lines.append(r"  \centering")
    lines.append(r"  \caption{既有减排方案及本文实测参数}")
    lines.append(r"  \label{tab:policy-survey}")
    lines.append(r"  \setptabsetup")
    # 三列固定宽度（\multirow 的内容不参与列宽计算，类别列若留作自动列会被压到隔壁列上）。
    # 72+122+200＝394pt，加 6 个 \tabcolsep 2.2pt 共约 407pt，窄于版心 468.2pt，居中排。
    lines.append(
        r"  \begin{tabular}{"
        r">{\centering\arraybackslash}p{72pt}"
        r">{\raggedright\arraybackslash}p{122pt}"
        r">{\raggedright\arraybackslash}p{200pt}}"
    )
    lines.append(r"    \toprule")
    lines.append(r"    类别 & 方案 & 本文实测参数\\")
    lines.append(r"    \midrule")
    for idx, row in enumerate(ROWS):
        span = spans[idx]
        if span is None:
            cat_cell = ""
        elif span == 1:
            cat_cell = CAT_WRAP.get(row["category"], row["category"])
        else:
            cat_cell = r"\multirow{%d}{*}{%s}" % (
                span, CAT_WRAP.get(row["category"], row["category"])
            )
        cells = [cat_cell, row["measure"], row["ours"]]
        lines.append("    " + " & ".join(cells) + r"\\")
    lines.append(r"    \bottomrule")
    lines.append(r"  \end{tabular}")
    lines.append(r"\end{table}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 4.4.3 第一部分的既有减排方案总表")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_table())
    print(f"已写出 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
