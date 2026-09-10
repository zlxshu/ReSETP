#!/usr/bin/env python3
"""生成论文表13（`tab:fleet-levels`，不同碳减排政策下的配送方案对比）。

只读各批次落盘产物的 `best_solution.json`，不手抄任何数字、不跑任何搜索。

## 口径

- 每行＝该情形若干次运算里**总成本最低**那一次的方案（与 4.3 节
  "取其最优配送方案"及 `build_grid2x2_table.py` 的口径一致），
  **例外：燃油/电动列见下面 2026-09-07 的口径变更**，
  数字从 `evaluation.breakdown` 读出：
  `cost_fix / cost_km / cost_elec / cost_fuel / cost_carbon / total_cost / E_total`
  与车队 `n_veh_cv` / `n_veh_ev`
  （**注意实测字段名是 `n_veh_cv`/`n_veh_ev`，不是任务口径里写的 `n_cv`/`n_ev`**，
  已用 `lever_subsidy_20260904/premium=76/MTC-HGS/run_02/best_solution.json`
  核对过实际路径：`evaluation.breakdown.{cost_fix,cost_km,cost_elec,cost_fuel,
  cost_carbon,total_cost,E_total,n_veh_cv,n_veh_ev}`）。
- **「燃油/电动（辆）」列的口径变更（2026-09-07 Claude 定）**：由"总成本最低那一次
  的车队构型"改为"多次运算中出现最多的车队构型"（**众数**）。
  众数按 `(n_veh_cv, n_veh_ev)` **整对**统计，不对两个分量各取众数——分开取会
  拼出一个没有任何一次运算真正跑出来的构型。并列（两个及以上构型出现次数相同）
  时，取**这些并列构型各自所属那几次运算的 `total_cost` 均值更低**的那一个。
  本列之外的所有列（成本分项/总成本/碳排量/Δ 两列）口径不变，仍由 `ROW_STATISTIC`
  决定（当前为 `mean`，即该情形目录下全部产物的算术均值）。
- **数据源切换（2026-09-07）**：购置补贴、午间充电按谷价补贴、碳配额与交易三行
  改指向 `solver/reports/policy_combos_20260907/{subsidy_alone,green_window,quota200}`
  ——这三批是在现行代码、`--first-trip-window prev_return` 下重跑的，与表内其余行
  口径一致；旧目录（`lever_subsidy_20260904/premium=76`、`lever_v2_20260906/green_window`、
  `lever_ctd_20260906/Q=200`）是旧首趟前补电窗口口径的产物，已不再引用。
- 三线表（只有 \toprule / 表头下 \midrule / \bottomrule，行组之间不再加横线）。
  第一列"类别"用 \multirow 竖向合并同类行；类别名 2026-09-08 起改用文献综述的
  原文一级用词（见 docs/handoff/policy_instrument_taxonomy_from_reviews_20260908.md），
  顺序＝基准 → 碳规制政策 → 购置端财政激励 → 需求响应政策 → 本文方案
  （2026-09-09 用户定：与分类图 figure_policy_taxonomy.tikz 的类别顺序一致）；
  `Δ` 两列相对基准行。
- 加粗：总成本列最小值、碳排量列最小值各一个（全部已输出行参与比较，含基准行），
  其余列不加粗。
- **单行运算次数限定（2026-09-08 用户定）**：ROWS 每行可选带 `runs=(...)` 字段，
  只列出该字段时，才只取该情形目录下这几个 run 子目录（如 `run_01`）的
  `best_solution.json` 参与聚合，其余 run 目录忽略；不带该字段的行不受影响，仍取
  目录下全部产物。**当前没有任何一行带该字段**——曾经带它的"谷段设在午间＋购置补贴"
  行已随三行两两组合一起移出本表（2026-09-08 晚），机制保留备用。
- **表的行清单（2026-09-08 晚用户定）**：基准 ＋ 7 个单一措施 ＋ 本文方案，共 9 行。
  三行两两组合（午谷＋碳价1.0、午谷＋购置补贴、午谷＋补贴24＋碳价1.2）移出表，
  只在正文里作组合方案的设计路径叙述。
- 对尚不存在（或没有任何 `best_solution.json`）的目录，脚本打印"缺失"并跳过该行，
  不报错退出，方便先用已跑出来的目录试跑。
- `CARBON_ROWS_FROM_POOL`（模块级开关，默认 `True`）：碳价类的五行（基准0.20、
  现行0.075、0.60、1.5、2.0，即 `new_dir` 落在
  `solver/reports/carbon_price_sweep_v2_20260906/` 下的行）不再各自只在自己
  的 `P=x` 目录里挑 best-of-3，而是把该目录下全部 66 个 `best_solution.json`
  合成一个方案池，对每一行的目标碳价重新核算总成本后取池内最低者：
  非碳成本＝该方案自身 `total_cost − cost_carbon`（`cost_fix/cost_km/cost_elec/
  cost_fuel` 不变），碳成本＝目标碳价 × 该方案自身 `E_total`，总成本＝非碳成本
  ＋新碳成本；目标碳价从行的 `new_dir` 末尾 `P=x` 解析。这样每行报的是"66个已跑
  方案在该碳价下重新核算后表现最好的那个"，胜出方案可能来自另一个碳价目录。
  设为 `False` 时退回旧口径（每行只在自己目录里按 best-of-3 取值，碳成本/总成本
  用该方案自己落盘的数字，不重算）。此开关只影响这五行，其余行（车队/补贴/配额
  交易/充电时机）不受影响。
- `--fallback-old`：本表五个新批次情形（premium50/premium0/lunch1114/green_window/
  midday_valley）目前只在 `solver/reports/lever_v2_20260906/` 下建了目录、还没有实际
  求解产物（2026-09-06 当次任务只准备批次、不启动求解）。传这个开关时，找不到新目录产物
  会退回旧目录（`lever_subsidy_20260904/premium=50|0`、
  `lever_workwindow_20260904/lunch1114`、`lever_green_window_20260904`、
  `ideal_construction_20260904/P=0.2/MTC-HGS`）——**旧目录是旧停机规则的产物，
  不能和新规则的其余行并排下结论，只用于试跑验证生成器本身能不能工作**。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "docs/paper_v2/generated_tables/policy_table.tex"

BREAKDOWN_KEYS = (
    "cost_fix", "cost_km", "cost_elec", "cost_fuel", "cost_carbon",
    "total_cost", "E_total", "n_veh_cv", "n_veh_ev",
)

# True：碳价类五行（基准0.20/现行0.075/0.60/1.5/2.0）从 CARBON_SWEEP_POOL_DIR 下
# 全部 best_solution.json 组成的方案池里，按该行目标碳价重新核算总成本后取最低者；
# False：退回旧口径，每行只在自己的目录里按 ROW_STATISTIC 取值（碳成本/总成本用
# 该方案自己落盘的数字，不重算）。见文件头 docstring。
# 2026-09-06 改口径：碳价类行不再走方案池，各自在自己目录里取均值，故置 False。
CARBON_ROWS_FROM_POOL = False
CARBON_SWEEP_POOL_DIR = "solver/reports/carbon_price_sweep_v2_20260906"

# ROW_STATISTIC：每行的成本分项/总成本/碳排量口径。
#   "mean" —— 该情形目录下全部 best_solution.json 的算术均值（2026-09-06 起默认）；
#             「燃油/电动（辆）」列不参与取均值，恒取该组内出现次数最多的构型
#             （众数，2026-09-07 起；此前是总成本最低那次的构型）。
#   "best" —— 旧口径，该情形若干次运算里 total_cost 最低的那一次（4.3 节"取其最优
#             配送方案"口径），与 build_grid2x2_table.py 一致。
ROW_STATISTIC = "mean"

# COMPACT_COST_COLUMNS（2026-09-09 用户定「字号与前文各表一致」后加的开关）
#   True  —— 把「启动成本/行驶成本/充电成本/油耗成本/碳成本」五列并成
#            「运营成本（元）＝总成本−碳成本」与「碳成本（元）」两列，全表 9 列。
#   False —— 旧的 12 列版本。
# 为什么必须并列：用户要求字号从 \scriptsize 改成与前文一致的 \small（\setptabsetup）。
# 实测（最小骨架，本表 9 行原样，类别列 40pt）：\small×12 列 Overfull \hbox 61.95pt，
# 即使把 tabcolsep 压到 0pt 仍差 28.95pt，靠调列距救不回来；并成 9 列后 \small
# ＋tabcolsep 1.5pt 为 0 Overfull。
# **Δ 两列不能删**：generate_policy_scatter_figure.py 会把每个点的 Δ 格成字符串后与本表
# 的 Δ 两列逐字比对，删掉这两列等于把那张图的自检悄悄废掉。
COMPACT_COST_COLUMNS = True

# 每行配置：
#   category = 表格第一列"类别"的 LaTeX 文本（同一 category 的连续行由 \multirow 合并）
#   label   = 表格第二列"情形"的 LaTeX 文本（长名字已手写 \makecell[l]{...} 折行）
#   group   = 'baseline' | 'single' | 'combo'（仅用于打印报告，三线表不再据此加 \midrule）
#   new_dir = 本批（新停机规则）数据源目录，相对仓库根
#   old_dir = 旧停机规则的替身目录（--fallback-old 时才会用），没有替身写 None
# 行序＝2026-09-09 用户定的类别顺序：基准 → 碳规制政策 → 购置端财政激励 → 需求响应政策 → 本文方案
# （与分类图 figure_policy_taxonomy.tikz 的类别顺序一致）
CAT_BASELINE = "基准"
CAT_PRICE_SIGNAL = "需求响应政策"
CAT_CARBON_PRICING = "碳规制政策"
CAT_FLEET_ECON = "购置端财政激励"
CAT_COMBO = "本文方案"

# \multirow 不会自动换行，跨 ≥2 行的类别在这里手写折行（每行 ≤4 个汉字，
# 与第一列的固定宽度匹配）；只跨 1 行的类别不套 \multirow，
# 否则 \multirow 的固定高度会把该行撑出 Overfull \vbox。
# **折行用 \shortstack，不用 \makecell**（2026-09-09 改字号时实测）：字号从 \scriptsize
# 提到 \small 后，\multirow{2}{*}{\makecell{...}} 会报 Overfull \vbox 1.34pt——\makecell
# 按 \arraystretch（\setptabsetup 设 0.95）算高度，与 \multirow 定死的格高对不上。
# 同时第一列宽度由 34pt 加到 40pt：\small 下 4 个汉字要 36.1pt，34pt 会 Overfull \hbox 2.13pt。
CAT_WRAP = {
    CAT_PRICE_SIGNAL: r"\shortstack{需求响应\\政策}",
    CAT_CARBON_PRICING: r"\shortstack{碳规制\\政策}",
    CAT_FLEET_ECON: r"\shortstack{购置端\\财政激励}",
}

ROWS = [
    dict(category=CAT_BASELINE,
         label=r"\makecell[l]{基准（北京现行时段，\\碳价0.20）}", group="baseline",
         new_dir="solver/reports/grid2x2_v3_20260906/beijing/P=0.2/MTC-HGS", old_dir=None),
    # ---- 碳规制政策
    dict(category=CAT_CARBON_PRICING,
         label="碳价降至现行0.075", group="single",
         new_dir="solver/reports/carbon_price_sweep_v3_20260906/P=0.07502", old_dir=None),
    dict(category=CAT_CARBON_PRICING,
         label="碳价升至1.0", group="single",
         new_dir="solver/reports/grid2x2_v3_20260906/beijing/P=1.0/MTC-HGS", old_dir=None),
    dict(category=CAT_CARBON_PRICING,
         label="碳价升至1.5", group="single",
         new_dir="solver/reports/carbon_price_sweep_v3_20260906/P=1.5", old_dir=None),
    dict(category=CAT_CARBON_PRICING,
         label=r"\makecell[l]{碳配额与交易\\（配额200 kg）}", group="single",
         new_dir="solver/reports/policy_combos_20260907/quota200", old_dir=None),
    # ---- 购置端财政激励
    dict(category=CAT_FLEET_ECON,
         label=r"\makecell[l]{购置补贴\\（折24元/日）}", group="single",
         new_dir="solver/reports/policy_combos_20260907/subsidy_alone", old_dir=None),
    # ---- 需求响应政策
    dict(category=CAT_PRICE_SIGNAL,
         label=r"\makecell[l]{充换电设施\\谷段设在午间}", group="single",
         new_dir="solver/reports/grid2x2_v3_20260906/midday/P=0.2/MTC-HGS", old_dir=None),
    dict(category=CAT_PRICE_SIGNAL,
         label=r"\makecell[l]{午间充电\\按谷价补贴}", group="single",
         new_dir="solver/reports/policy_combos_20260907/green_window", old_dir=None),
    # ---- 本文方案（2026-09-08 用户定，21:50/23:40）
    # 组合＝充换电设施谷段设在午间 ＋ 按全生命周期购置价差补贴（46.97 元/日，
    # 长江证券 100 kWh 轻卡初购溢价 6.50 万 ＋ 一次换电池 5.90 万 ＝ 12.40 万，
    # 8 年×330 日）＋ 单位碳价 1.2 元/kgCO2。目录 run_01–10 全部 10 次，不设 runs 过滤。
    # 已核：10 次 cost_carbon/E_total 逐次 ≡ 1.200000，车队 0/6×10。
    # 2026-09-08 起，两两组合三行（午谷＋碳价1.0、午谷＋购置补贴、午谷＋补贴24＋碳价1.2）
    # 移出本表，只作正文里的设计路径叙述，不再各占一行。
    dict(category=CAT_COMBO,
         label=r"\makecell[l]{谷段设在午间＋全生命周期\\价差补贴＋碳价升至1.2}", group="combo",
         new_dir="solver/reports/policy_combos_20260907/midday_subsidy47_P1.2", old_dir=None),
]


def find_solutions(base: Path) -> list[Path]:
    if not base.exists():
        return []
    return sorted(base.rglob("best_solution.json"))


def load_breakdown(path: Path) -> dict:
    data = json.loads(path.read_text())
    bd = data["evaluation"]["breakdown"]
    missing = [k for k in BREAKDOWN_KEYS if k not in bd]
    if missing:
        raise KeyError(f"{path}: breakdown 缺字段 {missing}")
    return bd


# 参与取均值/标准差的字段：车队构成（n_veh_cv/n_veh_ev）不取均值，取众数构型，
# 故排除在外。
MEAN_KEYS = tuple(k for k in BREAKDOWN_KEYS if k not in ("n_veh_cv", "n_veh_ev"))


def modal_fleet(bds: list[dict]) -> tuple[tuple[int, int], dict]:
    """返回 ((n_veh_cv, n_veh_ev) 众数构型, 众数统计明细)。

    众数按整对统计（不对两个分量各取众数）；并列时取并列构型各自所属那几次运算的
    total_cost 均值更低者。明细里带每个构型的出现次数与成本均值，供报告打印。
    """
    groups: dict[tuple[int, int], list[float]] = {}
    for bd in bds:
        key = (int(bd["n_veh_cv"]), int(bd["n_veh_ev"]))
        groups.setdefault(key, []).append(float(bd["total_cost"]))
    stats = {
        key: {"count": len(costs), "mean_cost": sum(costs) / len(costs)}
        for key, costs in groups.items()
    }
    # 先按出现次数降序，次数并列时按该构型的总成本均值升序。
    winner = min(stats.items(), key=lambda kv: (-kv[1]["count"], kv[1]["mean_cost"]))[0]
    top = max(item["count"] for item in stats.values())
    tied = sorted(k for k, v in stats.items() if v["count"] == top)
    return winner, {"stats": stats, "tied": tied, "top_count": top}


def aggregate_breakdown(paths: list[Path]) -> dict:
    """按 ROW_STATISTIC 聚合该情形目录下全部 best_solution.json。

    返回的 dict 键与 BREAKDOWN_KEYS 一致（可直接喂给下游取数/算 Δ 的代码），
    另加：
      __n__     = 参与聚合的产物数
      __sd__    = {key: 总体标准差}（仅 "mean" 模式非零；只用于打印，不进表）
      __fleet__ = 众数统计明细（只用于打印，不进表）
    "燃油/电动（辆）"（n_veh_cv/n_veh_ev）恒取该组内出现次数最多的构型（众数），
    "best" 与 "mean" 两种模式下都一样。
    """
    bds = [load_breakdown(p) for p in paths]
    n = len(bds)
    (mode_cv, mode_ev), fleet_note = modal_fleet(bds)

    if ROW_STATISTIC == "best":
        best_idx = min(range(n), key=lambda i: bds[i]["total_cost"])
        agg = dict(bds[best_idx])
        agg["n_veh_cv"] = mode_cv
        agg["n_veh_ev"] = mode_ev
        return {
            **agg, "__n__": n, "__sd__": {k: 0.0 for k in MEAN_KEYS},
            "__fleet__": fleet_note,
        }

    if ROW_STATISTIC != "mean":
        raise ValueError(f"未知 ROW_STATISTIC={ROW_STATISTIC!r}，只接受 'mean'/'best'")

    agg: dict = {"n_veh_cv": mode_cv, "n_veh_ev": mode_ev}
    sd: dict = {}
    for k in MEAN_KEYS:
        vals = [bd[k] for bd in bds]
        agg[k] = sum(vals) / n
        sd[k] = statistics.pstdev(vals) if n > 1 else 0.0
    agg["__n__"] = n
    agg["__sd__"] = sd
    agg["__fleet__"] = fleet_note
    return agg


def is_carbon_price_row(row: dict) -> bool:
    """判断该行是否属于碳价类五行（new_dir 落在碳价 sweep 池目录下）。"""
    return row["new_dir"].startswith(CARBON_SWEEP_POOL_DIR + "/")


def parse_price_from_dir(dir_rel: str) -> float:
    """从 '.../P=0.07502' 这样的目录名末段解析出目标碳价。"""
    name = dir_rel.rstrip("/").rsplit("/", 1)[-1]
    if not name.startswith("P="):
        raise ValueError(f"目录名不是 P=x 格式，无法解析目标碳价：{dir_rel}")
    return float(name[2:])


def load_carbon_sweep_pool() -> list[tuple[Path, dict]]:
    """加载碳价 sweep 池目录下全部 best_solution.json 的 (路径, breakdown)。"""
    base = REPO_ROOT / CARBON_SWEEP_POOL_DIR
    return [(p, load_breakdown(p)) for p in find_solutions(base)]


def resolve_carbon_price_row_from_pool(
    row: dict, pool: list[tuple[Path, dict]]
) -> tuple[str, list[Path], dict] | None:
    """碳价类行的池化重算：目标碳价下，池内每个方案的非碳成本不变、碳成本按
    目标碳价 × 自身 E_total 重算，取重算后总成本最低者。返回 (数据来源说明,
    选中路径, 重算后的 breakdown)；池为空返回 None。"""
    if not pool:
        return None
    target_price = parse_price_from_dir(row["new_dir"])
    best = None  # (new_total, path, new_bd)
    for p, bd in pool:
        noncarbon = bd["total_cost"] - bd["cost_carbon"]
        new_carbon = target_price * bd["E_total"]
        new_total = noncarbon + new_carbon
        if best is None or new_total < best[0]:
            new_bd = dict(bd)
            new_bd["cost_carbon"] = new_carbon
            new_bd["total_cost"] = new_total
            best = (new_total, p, new_bd)
    _, best_path, new_bd = best
    rel_origin = best_path.relative_to(REPO_ROOT).parent
    source_note = (
        f"碳价重算池 {CARBON_SWEEP_POOL_DIR}/（{len(pool)} 个产物，"
        f"目标碳价={target_price}），胜出方案原属 {rel_origin}"
    )
    new_bd = dict(new_bd)
    new_bd["__n__"] = 1
    new_bd["__sd__"] = {k: 0.0 for k in MEAN_KEYS}
    new_bd["__fleet__"] = {
        "stats": {
            (int(new_bd["n_veh_cv"]), int(new_bd["n_veh_ev"])): {
                "count": 1, "mean_cost": float(new_bd["total_cost"]),
            }
        },
        "tied": [(int(new_bd["n_veh_cv"]), int(new_bd["n_veh_ev"]))],
        "top_count": 1,
    }
    return source_note, [best_path], new_bd


def resolve_row(row: dict, fallback_old: bool) -> tuple[str, list[Path], dict] | None:
    """返回 (数据来源说明, 参与聚合的 best_solution.json 路径列表, 聚合后 breakdown)；
    找不到数据返回 None。聚合口径见 aggregate_breakdown / 模块级 ROW_STATISTIC。"""
    new_base = REPO_ROOT / row["new_dir"]
    paths = find_solutions(new_base)
    runs_filter = row.get("runs")
    if runs_filter:
        paths = [p for p in paths if p.parent.name in runs_filter]
        source_note = (
            f"新目录 {row['new_dir']}（限定 runs={list(runs_filter)}，{len(paths)} 个产物）"
        )
    else:
        source_note = f"新目录 {row['new_dir']}（{len(paths)} 个产物）"
    if not paths and fallback_old and row["old_dir"]:
        old_base = REPO_ROOT / row["old_dir"]
        old_paths = find_solutions(old_base)
        if old_paths:
            paths = old_paths
            source_note = f"回退旧目录 {row['old_dir']}（{len(paths)} 个产物，旧停机规则）"
    if not paths:
        return None
    agg = aggregate_breakdown(paths)
    return source_note, paths, agg


def fmt_num(x: float) -> str:
    v = round(x, 2)
    if v == 0:
        v = 0.0
    s = f"{abs(v):.2f}"
    return f"$-${s}" if v < 0 else s


def fmt_delta(x: float | None) -> str:
    if x is None:
        return ""
    v = round(x, 2)
    if v == 0:
        v = 0.0
    s = f"{abs(v):.2f}"
    if v < 0:
        return f"$-${s}"
    if v > 0:
        return f"$+${s}"
    return s


def indent_label(label: str) -> str:
    r"""把"情形"列的文本整体缩进一个 \quad，做出"类别（一级）—情形（二级）"的视觉层次。

    2026-09-09 用户："表 12 的类别/情形要有视觉层次，学别人处理一级二级表格"。
    目标期刊两篇母版（陈婉茹等 2023 表 8--11、陈雨蝶等 2025 表 10--13）里没有
    带类别列的行分组表——它们的一级/二级层次一律做在**表头跨列**上（陈婉茹表 10
    的"碳限额 CE=150 千克 / 450 千克"各跨 5 列、陈雨蝶表 10 的四种速度函数各跨 2 列，
    下加 \cmidrule），或者干脆把情形转置成列。可迁移的行内手法只有陈婉茹表 9 的
    "整行加粗标出选中构型"。因此本表不另造母版里没有的"整行 \multicolumn 小标题带"，
    只在现有结构里做最小改动：**类别名加粗 ＋ 情形名缩进**。

    `\makecell[l]{A\\B}` 形式的多行标签要每一行都缩进，只缩第一行会让第二行顶格，
    反而更乱。
    """
    marker = r"\makecell[l]{"
    if label.startswith(marker):
        inner = label[len(marker):-1]
        inner = r"\quad " + inner.replace(r"\\", r"\\\quad ")
        return marker + inner + "}"
    return r"\quad " + label


def build_table(fallback_old: bool) -> tuple[str, list[str]]:
    """返回 (tex 片段, 逐行报告字符串列表)。"""
    resolved: list[tuple[dict, str, list[Path], dict] | None] = []
    report_lines: list[str] = []
    baseline_bd: dict | None = None

    carbon_pool: list[tuple[Path, dict]] | None = None
    if CARBON_ROWS_FROM_POOL and any(is_carbon_price_row(row) for row in ROWS):
        carbon_pool = load_carbon_sweep_pool()

    for row in ROWS:
        if CARBON_ROWS_FROM_POOL and is_carbon_price_row(row):
            result = resolve_carbon_price_row_from_pool(row, carbon_pool or [])
        else:
            result = resolve_row(row, fallback_old)
        if result is None:
            report_lines.append(f"缺失：{row['group']:8s} {row['new_dir']} —— 跳过该行")
            resolved.append(None)
            continue
        source_note, paths, bd = result
        resolved.append((row, source_note, paths, bd))
        n = bd.get("__n__", len(paths))
        sd = bd.get("__sd__", {})
        if len(paths) == 1:
            picked_note = f"选中={paths[0].relative_to(REPO_ROOT)}"
        else:
            picked_note = f"聚合={n}个: " + ", ".join(
                sorted(str(p.relative_to(REPO_ROOT).parent) for p in paths)
            )
        report_lines.append(
            f"取用：{row['group']:8s} label={row['label'][:20]!r:22s} "
            f"来源={source_note} 统计口径={ROW_STATISTIC} n={n} {picked_note}\n"
            f"        total_cost: mean={bd['total_cost']:.2f} sd={sd.get('total_cost', 0.0):.2f} | "
            f"E_total: mean={bd['E_total']:.2f} sd={sd.get('E_total', 0.0):.2f} | "
            f"cost_carbon: mean={bd['cost_carbon']:.2f} sd={sd.get('cost_carbon', 0.0):.2f} | "
            f"车队(众数)={int(bd['n_veh_cv'])}/{int(bd['n_veh_ev'])}"
            + (
                "\n        车队构型计数: "
                + ", ".join(
                    f"{cv}/{ev}×{item['count']}(均值{item['mean_cost']:.2f})"
                    for (cv, ev), item in sorted(
                        bd.get("__fleet__", {}).get("stats", {}).items(),
                        key=lambda kv: (-kv[1]["count"], kv[1]["mean_cost"]),
                    )
                )
                + (
                    "  ← 出现次数并列，已按成本均值择低"
                    if len(bd.get("__fleet__", {}).get("tied", [])) > 1 else ""
                )
            )
        )
        if row["group"] == "baseline":
            baseline_bd = bd

    if baseline_bd is None:
        report_lines.append("警告：基准行缺失，所有 Δ 列留空。")

    emitted = [e for e in resolved if e is not None]

    # \multirow 跨行数：按已输出行里连续相同 category 分段统计（跳过的行不计）。
    span_start: list[int | None] = [None] * len(emitted)   # 该行是本段首行时记段长，否则 None
    i = 0
    while i < len(emitted):
        cat = emitted[i][0]["category"]
        j = i
        while j < len(emitted) and emitted[j][0]["category"] == cat:
            j += 1
        span_start[i] = j - i
        i = j

    lines = []
    lines.append(r"\begin{table}[!htbp]")
    lines.append(r"  \centering")
    lines.append(r"  \caption{既有方案与本文方案在本文算例上的实测结果}")
    lines.append(r"  \label{tab:fleet-levels}")
    # 字号与前文各表一致：\setptabsetup（paper_main.tex 第 62 行）＝\small＋arraystretch 0.95
    # ＋tabcolsep 2.2pt。本表列多，tabcolsep 覆盖为 1.5pt（见 COMPACT_COST_COLUMNS 注释）。
    lines.append(r"  \setptabsetup")
    lines.append(r"  \setlength{\tabcolsep}{1.5pt}")
    # 第一列固定宽度：\multirow 的内容不参与列宽计算，若留作 l 列会压到"情形"列上。
    # 列数：类别（p）＋情形（l）＋若干居中数字列。
    # 紧凑版数字列 7＝燃油/电动、运营成本、碳成本、总成本、碳排量、Δ总成本、Δ碳排量；
    # 旧版 10＝燃油/电动、启动/行驶/充电/油耗/碳成本、总成本、碳排量、Δ 两列。
    n_num_cols = 7 if COMPACT_COST_COLUMNS else 10
    lines.append(
        r"  \begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}"
        r">{\centering\arraybackslash}p{40pt}l" + "c" * n_num_cols + r"@{}}"
    )
    lines.append(r"    \toprule")
    if COMPACT_COST_COLUMNS:
        lines.append(
            r"    类别 & 情形 & \makecell{燃油/电动\\（辆）} & "
            r"\makecell{运营成本\\（元）} & \makecell{碳成本\\（元）} & "
            r"\makecell{总成本\\（元）} & \makecell{碳排量\\（kgCO$_2$）} & "
            r"\makecell{$\Delta$总成本\\（元）} & \makecell{$\Delta$碳排量\\（kgCO$_2$）}\\"
        )
    else:
        lines.append(
            r"    类别 & 情形 & \makecell{燃油/电动\\（辆）} & \makecell{启动成本\\（元）} & "
            r"\makecell{行驶成本\\（元）} & \makecell{充电成本\\（元）} & "
            r"\makecell{油耗成本\\（元）} & \makecell{碳成本\\（元）} & "
            r"\makecell{总成本\\（元）} & \makecell{碳排量\\（kgCO$_2$）} & "
            r"\makecell{$\Delta$总成本\\（元）} & \makecell{$\Delta$碳排量\\（kgCO$_2$）}\\"
        )
    lines.append(r"    \midrule")

    for idx, (row, _source_note, _paths, bd) in enumerate(emitted):
        fleet = f"{int(bd['n_veh_cv'])}/{int(bd['n_veh_ev'])}"
        if row["group"] == "baseline" or baseline_bd is None:
            d_cost = ""
            d_carbon = ""
        else:
            d_cost = fmt_delta(bd["total_cost"] - baseline_bd["total_cost"])
            d_carbon = fmt_delta(bd["E_total"] - baseline_bd["E_total"])

        cell_total = fmt_num(bd["total_cost"])
        cell_carbon = fmt_num(bd["E_total"])

        span = span_start[idx]
        # 一级（类别）与二级（情形）靠缩进区分，见 indent_label 的说明。
        cat_text = CAT_WRAP.get(row["category"], row["category"])
        if span is None:
            cat_cell = ""
        elif span == 1:
            # 只跨 1 行：用折行文本但不套 \multirow —— \multirow 会给单元格定死
            # 高度，两行内容放进去就是 Overfull \vbox。
            cat_cell = cat_text
        else:
            cat_cell = r"\multirow{%d}{*}{%s}" % (span, cat_text)

        if COMPACT_COST_COLUMNS:
            # 运营成本＝总成本−碳成本＝cost_fix+cost_km+cost_elec+cost_fuel
            # （已对全部行核过：两种算法逐位相符，差 <1e-9）。
            operating = bd["total_cost"] - bd["cost_carbon"]
            parts_sum = (
                bd["cost_fix"] + bd["cost_km"] + bd["cost_elec"] + bd["cost_fuel"]
            )
            if abs(operating - parts_sum) > 1e-6:
                raise ValueError(
                    f"运营成本两种算法不符：总成本−碳成本={operating!r}，"
                    f"四项分项和={parts_sum!r}（行 {row['new_dir']}）"
                )
            cells = [
                cat_cell,
                indent_label(row["label"]),
                fleet,
                fmt_num(operating),
                fmt_num(bd["cost_carbon"]),
                cell_total,
                cell_carbon,
                d_cost,
                d_carbon,
            ]
        else:
            cells = [
                cat_cell,
                indent_label(row["label"]),
                fleet,
                fmt_num(bd["cost_fix"]),
                fmt_num(bd["cost_km"]),
                fmt_num(bd["cost_elec"]),
                fmt_num(bd["cost_fuel"]),
                fmt_num(bd["cost_carbon"]),
                cell_total,
                cell_carbon,
                d_cost,
                d_carbon,
            ]
        lines.append("    " + " & ".join(cells) + r"\\")

    lines.append(r"    \bottomrule")
    lines.append(r"  \end{tabular*}")
    lines.append(r"\end{table}")
    return "\n".join(lines) + "\n", report_lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fallback-old", action="store_true",
                     help="新目录（lever_v2_20260906 等）没有产物时回退旧停机规则目录，仅供试跑生成器用")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                     help=f"输出 tex 路径（默认 {DEFAULT_OUT.relative_to(REPO_ROOT)}）")
    args = ap.parse_args()

    tex, report_lines = build_table(args.fallback_old)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(tex)

    print(
        f"# 逐行取数报告（fallback_old={args.fallback_old}, "
        f"ROW_STATISTIC={ROW_STATISTIC!r}, "
        f"CARBON_ROWS_FROM_POOL={CARBON_ROWS_FROM_POOL}）",
        file=sys.stderr,
    )
    for line in report_lines:
        print(line, file=sys.stderr)
    print(f"\n已写出 {args.out.relative_to(REPO_ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
