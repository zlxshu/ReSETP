#!/usr/bin/env python3
"""生成论文 4.4.3 的分类表（`tab:policy-classes`，碳减排措施分类与实测设定）。

## 这张表是什么

4.4.3 正文把推动配送车队降本减排的措施分成三类（价格信号协调 / 碳定价 /
车队经济性），并从每类里取代表性措施做实测。本表把"分类—措施—作用的决策维度—
代表研究或政策—本文实测设定"五列摆成一张三线表，让读者在看表
\\ref{tab:fleet-levels} 的成绩之前先知道每一行测的是什么、设定从哪来。

## 每一格的出处（不手抄，全部从仓库产物读出）

- **谷段时段**：从各份日历 CSV 的 `city=beijing` 行按 `minute_of_day` 聚合而来，
  不抄任何 README 或正文里的时段文字。三份日历分别是
  `china81_runtime_parameter_authority_v4_20260723`（北京现行时段）、
  `china81_cf_calendar_midday_valley_v1_20260904`（谷段设在午间）、
  `china81_cf_calendar_midday_discount_v1_20260904`（午间按谷价补贴）。
  注意补贴日历里 12:00--15:00 的 `tariff_period` 标的是 `valley_subsidised`
  而不是 `valley`，所以时段是按**电度价等于谷价**这个条件判定的，不按标签判定。
- **谷价数值**：同上，取 `depot_energy_cny_per_kwh` 的最小值。
- **购置补贴额**：从两份落盘产物的 `evaluation.breakdown.cost_fix_ev_premium`
  除以 `n_veh_ev` 得每辆每日溢价，基准
  （`grid2x2_v3_20260906/beijing/P=0.2/MTC-HGS/run_01`）与补贴情形
  （`policy_combos_20260907/subsidy_alone/run_01`）之差即补贴额。
- **碳价档位与配额**：从表 13 的生成器 `build_policy_table.py` 的 `ROWS` 读出，
  与表 13 逐字一致（碳价档位从 `new_dir` 末段 `P=x` 解析，配额从批次
  joblist 的 `--carbon-quota-kg` 读出）。
- **引用键**：`ref:hebei-tou` / `ref:wu2022` / `ref:23` / `ref:qiu2024` /
  `ref:lijin2014` / `ref:wilson2026` / `ref:mee2025`，已与
  `docs/paper_v2/paper_main.tex` 的 `\\bibitem` 逐个核对存在。

## 版式

三线表（只有 \\toprule / 表头下 \\midrule / \\bottomrule），无表注；
第一列"类别"用 \\multirow 竖向合并跨 ≥2 行的类别，只跨 1 行的类别写纯文本
（\\multirow 会给单元格定死高度，两行内容放进去就是 Overfull \\vbox——
这条坑与 `build_policy_table.py` 同源）。文字列用 tabularx 的 X 列自动分宽。

用法：python3 solver/scripts/build_policy_class_table.py [--out TEX]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "docs/paper_v2/generated_tables/policy_class_table.tex"

CAL_CURRENT = "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
CAL_MIDDAY = "data/ChinaInstances/china81_cf_calendar_midday_valley_v1_20260904"
CAL_DISCOUNT = "data/ChinaInstances/china81_cf_calendar_midday_discount_v1_20260904"

BASELINE_SOL = "solver/reports/grid2x2_v3_20260906/beijing/P=0.2/MTC-HGS/run_01/best_solution.json"
SUBSIDY_SOL = "solver/reports/policy_combos_20260907/subsidy_alone/run_01/best_solution.json"
QUOTA_JOBLIST = "solver/reports/policy_combos_20260907/joblist_acceptance.txt"
QUOTA_ROW_DIR = "solver/reports/policy_combos_20260907/quota200"

CITY = "beijing"
SLOT_MINUTES = 30


def rel(path: Path) -> str:
    """仓库内的路径报相对路径，仓库外（如 --out 指到别处）原样报绝对路径。"""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------- 日历读数


def read_valley_windows(cal_dir: str) -> tuple[list[tuple[int, int]], float, dict]:
    """返回 (谷价时段列表[(起分, 止分)], 谷价 元/kWh, 诊断信息)。

    时段按「车场电度价 == 该日历北京行里的最小电度价」判定，不按 `tariff_period`
    标签判定——补贴日历里午间 6 个槽的标签是 `valley_subsidised`，按标签筛会漏。
    28 个日期逐日同构，这里对 `minute_of_day` 去重后合并连续槽。
    """
    path = REPO_ROOT / cal_dir / "tariff_carbon_hourly_calendar.csv"
    prices: dict[int, set[float]] = {}
    labels: dict[float, set[str]] = {}
    labelled_valley: set[int] = set()   # tariff_period 恰为 "valley" 的槽
    dates: set[str] = set()
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            if row["city"] != CITY:
                continue
            dates.add(row["date"])
            minute = int(row["minute_of_day"])
            price = float(row["depot_energy_cny_per_kwh"])
            prices.setdefault(minute, set()).add(price)
            labels.setdefault(price, set()).add(row["tariff_period"])
            if row["tariff_period"] == "valley":
                labelled_valley.add(minute)
    if not prices:
        raise RuntimeError(f"{path}: 没有 city={CITY} 的行")
    multi = {m: v for m, v in prices.items() if len(v) > 1}
    if multi:
        raise RuntimeError(f"{path}: 同一 minute_of_day 在 28 个日期里价格不一致：{sorted(multi)[:5]}")
    flat = {m: next(iter(v)) for m, v in prices.items()}
    valley_price = min(flat.values())
    minutes = sorted(m for m, p in flat.items() if p == valley_price)
    windows: list[tuple[int, int]] = []
    start = prev = None
    for m in minutes:
        if start is None:
            start = prev = m
            continue
        if m - prev == SLOT_MINUTES:
            prev = m
            continue
        windows.append((start, prev + SLOT_MINUTES))
        start = prev = m
    if start is not None:
        windows.append((start, prev + SLOT_MINUTES))
    diag = {
        "path": str(path.relative_to(REPO_ROOT)),
        "dates": len(dates),
        "slots": len(flat),
        "prices": sorted(set(flat.values())),
        "valley_labels": sorted(labels[valley_price]),
        # 两种口径要分开，不能混用：
        #   valley_hours       = 电度价等于谷价的小时数（"哪些槽按谷价计费"）；
        #   structural_hours   = tariff_period 标为 valley 的小时数（"时段结构里的谷段"）。
        # 补贴日历里 12:00--15:00 按谷价计费但标签是 valley_subsidised，两者相差 3 h
        # （11.0 vs 8.0）。比"时段结构有没有变"要用后者，比"哪些时段便宜"要用前者。
        "valley_hours": len(minutes) * SLOT_MINUTES / 60.0,
        "structural_hours": len(labelled_valley) * SLOT_MINUTES / 60.0,
    }
    return windows, valley_price, diag


def fmt_windows(windows: list[tuple[int, int]]) -> str:
    def hhmm(m: int) -> str:
        return f"{m // 60:02d}:{m % 60:02d}"

    return "、".join(f"{hhmm(a)}--{hhmm(b)}" for a, b in windows)


# ---------------------------------------------------------------- 产物读数


def daily_ev_premium(sol_rel: str) -> tuple[float, dict]:
    """从落盘产物读出每辆电动车的日固定溢价（cost_fix_ev_premium / n_veh_ev）。"""
    path = REPO_ROOT / sol_rel
    bd = json.loads(path.read_text())["evaluation"]["breakdown"]
    n_ev = int(bd["n_veh_ev"])
    if n_ev <= 0:
        raise RuntimeError(f"{sol_rel}: n_veh_ev={n_ev}，无法反推每辆日溢价")
    premium = float(bd["cost_fix_ev_premium"]) / n_ev
    return premium, {"path": sol_rel, "n_veh_ev": n_ev,
                     "cost_fix_ev_premium": float(bd["cost_fix_ev_premium"]),
                     "premium_per_ev_per_day": premium}


def carbon_prices_from_table13() -> tuple[list[float], list[str]]:
    """从表 13 生成器的 ROWS 里取"碳定价—单位碳价"三行的碳价档位。

    与表 13 同一来源，避免两张表写出不同的档位。0.075 那一档目录名是
    `P=0.07502`（现行全国碳市场价 75.02 元/tCO2 折算），表里按正文口径写 0.075。
    """
    sys.path.insert(0, str(REPO_ROOT / "solver/scripts"))
    import build_policy_table as bpt  # noqa: E402

    prices: list[float] = []
    notes: list[str] = []
    for row in bpt.ROWS:
        if row["category"] != bpt.CAT_CARBON_PRICING:
            continue
        m = re.search(r"P=([0-9.]+)", row["new_dir"])
        if m:
            prices.append(float(m.group(1)))
            notes.append(f"{row['new_dir']} → 碳价 {m.group(1)}")
        elif "quota" in row["new_dir"]:
            notes.append(f"{row['new_dir']} → 碳配额行（碳价档位不由此行提供）")
        else:
            raise RuntimeError(f"碳定价行 {row['new_dir']} 既不含 P=x 也不是配额行，无法解析")
    if not prices:
        raise RuntimeError("表 13 的 ROWS 里没解析出任何碳价档位")
    return sorted(prices), notes


def carbon_quota_kg() -> tuple[float, str]:
    """从批次 joblist 读出配额行实际传入的 --carbon-quota-kg。"""
    text = (REPO_ROOT / QUOTA_JOBLIST).read_text()
    hits = set()
    for line in text.splitlines():
        if QUOTA_ROW_DIR.split("solver/reports/")[-1] not in line:
            continue
        m = re.search(r"--carbon-quota-kg\s+([0-9.]+)", line)
        if m:
            hits.add(float(m.group(1)))
    if len(hits) != 1:
        raise RuntimeError(f"{QUOTA_JOBLIST}: quota200 行解析出的 --carbon-quota-kg 不唯一：{hits}")
    value = hits.pop()
    return value, f"{QUOTA_JOBLIST} 里 quota200 各次运算均为 --carbon-quota-kg {value:g}"


# ---------------------------------------------------------------- 组表


# 类别标签一律**顶对齐**放在该类第一行（\makecell[t]），不用 \multirow：
# 本表各行高度极不均匀（首行 4 行文字、末行 3 行），\multirow 按均高居中会把
# "车队经济性"压到上一行"碳配额与交易"旁边，读者会误以为它管着两行。
# 顶对齐后规则唯一——标签与它所辖第一行的首行文字齐平。
CAT_PRICE_SIGNAL = r"\makecell[t]{价格信号\\协调}"
CAT_CARBON_PRICING = r"\makecell[t]{碳定价}"
CAT_FLEET_ECON = r"\makecell[t]{车队\\经济性}"


def fmt_price_list(prices: list[float]) -> str:
    """0.07502 按正文口径写 0.075，其余按最短小数写。"""
    out = []
    for p in prices:
        if abs(p - 0.07502) < 1e-6:
            out.append("0.075")          # 正文口径：现行全国碳市场价按 0.075 元/kgCO2 报
        elif p == int(p):
            out.append(f"{p:.1f}")       # 1 → "1.0"，与正文"碳价升至1.0"一致
        else:
            out.append(f"{p:g}")
    return "、".join(out)


def build_table() -> tuple[str, list[str]]:
    report: list[str] = []

    cur_win, cur_price, cur_diag = read_valley_windows(CAL_CURRENT)
    mid_win, mid_price, mid_diag = read_valley_windows(CAL_MIDDAY)
    dis_win, dis_price, dis_diag = read_valley_windows(CAL_DISCOUNT)
    for name, diag, win, price in (
        ("北京现行时段", cur_diag, cur_win, cur_price),
        ("谷段设在午间", mid_diag, mid_win, mid_price),
        ("午间按谷价补贴", dis_diag, dis_win, dis_price),
    ):
        report.append(
            f"日历 {name}：{diag['path']}\n"
            f"        日期数={diag['dates']} 槽数={diag['slots']} 电度价档={diag['prices']}\n"
            f"        谷价={price:.8f} 元/kWh 按谷价计费的时段={fmt_windows(win)} "
            f"（合计 {diag['valley_hours']:.1f} h，tariff_period 标签={diag['valley_labels']}）\n"
            f"        其中 tariff_period 标为 valley 的结构谷段合计 "
            f"{diag['structural_hours']:.1f} h"
        )

    base_premium, base_diag = daily_ev_premium(BASELINE_SOL)
    sub_premium, sub_diag = daily_ev_premium(SUBSIDY_SOL)
    subsidy = base_premium - sub_premium
    report.append(
        f"购置补贴：基准 {base_diag['path']} → 每辆每日溢价 {base_premium:.2f} 元"
        f"（{base_diag['cost_fix_ev_premium']:.2f}/{base_diag['n_veh_ev']}）\n"
        f"        补贴情形 {sub_diag['path']} → 每辆每日溢价 {sub_premium:.2f} 元"
        f"（{sub_diag['cost_fix_ev_premium']:.2f}/{sub_diag['n_veh_ev']}）\n"
        f"        补贴额 = {base_premium:.2f} − {sub_premium:.2f} = {subsidy:.2f} 元/日"
    )

    prices, price_notes = carbon_prices_from_table13()
    report.append("单位碳价档位（取自 build_policy_table.ROWS）：\n        " + "\n        ".join(price_notes))
    quota, quota_note = carbon_quota_kg()
    report.append(f"碳配额：{quota_note}")

    # ---- 各行的"本文实测设定"文本，全部由上面读出的数字拼成
    # 行①比的是"时段结构重排"，两份日历的谷段都只用 valley 这一个标签，
    # 所以用结构口径（tariff_period == "valley"）比总时长；若某份日历的谷价槽
    # 还带别的标签（例如补贴日历的 valley_subsidised），说明它不是纯重排，
    # 不能进这句比较，直接报错。
    for nm, dg in (("北京现行时段", cur_diag), ("谷段设在午间", mid_diag)):
        if dg["valley_labels"] != ["valley"]:
            raise RuntimeError(
                f"{nm} 日历的谷价槽标签为 {dg['valley_labels']}，不是纯时段重排，"
                f"不能用于行①的谷段总时长比较")
    cur_hours = cur_diag["structural_hours"]
    mid_hours = mid_diag["structural_hours"]
    # "谷段总时长不变"这句只在两份日历的谷段小时数真的相等时才写，不凭印象断言。
    same_len = "，谷段总时长不变" if abs(cur_hours - mid_hours) < 1e-9 else (
        f"，谷段总时长由{cur_hours:g} h变为{mid_hours:g} h")
    set_midday = (
        f"谷段改设于{fmt_windows(mid_win)}"
        f"（现行为{fmt_windows(cur_win)}）{same_len}"
    )
    set_discount = (
        f"时段结构不变，{fmt_windows([w for w in dis_win if w not in cur_win])}"
        f"按谷价{dis_price:.3f}元/kWh计费"
    )
    set_price = f"{fmt_price_list(prices)}元/kgCO$_2$，其中0.075为现行全国碳市场价\\cite{{ref:mee2025}}"
    set_quota = f"配额{quota:g} kgCO$_2$"
    set_subsidy = (
        f"按购置价差全额补贴，电动车日固定溢价由{base_premium:g}元降至{sub_premium:g}元，"
        f"即{subsidy:g}元/日"
    )

    # 每行：(类别标签或 None, 是否为该类首行, 措施, 决策维度, 代表研究或政策, 实测设定)
    rows = [
        (CAT_PRICE_SIGNAL, True, "充换电设施分时时段划分（谷段设在午间）", "充电时刻",
         r"河北南网分时电价\cite{ref:hebei-tou}", set_midday),
        (None, False, "午间充电按谷价补贴", "充电时刻",
         r"Wu等\cite{ref:wu2022}", set_discount),
        (CAT_CARBON_PRICING, True, "单位碳价", "车型与充电时刻",
         r"陈婉茹等\cite{ref:23}、Qiu等\cite{ref:qiu2024}", set_price),
        (None, False, "碳配额与交易", "车型",
         r"李进等\cite{ref:lijin2014}", set_quota),
        (CAT_FLEET_ECON, True, "购置补贴", "车型",
         r"Wilson等\cite{ref:wilson2026}", set_subsidy),
    ]

    lines: list[str] = []
    lines.append(r"\begin{table}[H]")
    lines.append(r"  \centering")
    lines.append(r"  \caption{碳减排措施分类与实测设定}")
    lines.append(r"  \label{tab:policy-classes}")
    lines.append(r"  \footnotesize")
    lines.append(r"  \setlength{\tabcolsep}{3pt}")
    lines.append(
        r"  \begin{tabularx}{\textwidth}{"
        r">{\centering\arraybackslash}p{38pt}"
        r">{\RaggedRight\arraybackslash}X"
        r">{\centering\arraybackslash}p{50pt}"
        r">{\RaggedRight\arraybackslash}X"
        r">{\RaggedRight\arraybackslash}X}"
    )
    lines.append(r"    \toprule")
    lines.append(r"    类别 & 措施 & 作用的决策维度 & 代表研究或政策 & 本文实测设定\\")
    lines.append(r"    \midrule")
    first_group = True
    for cat, is_group_head, measure, dim, source, setting in rows:
        if is_group_head and not first_group:
            # booktabs 的 \addlinespace 只加竖直空隙、不画线，三线表照旧成立；
            # 类别之间留一点空隙，读者一眼能看出哪几行属于同一类。
            lines.append(r"    \addlinespace[2pt]")
        if is_group_head:
            first_group = False
        cat_cell = cat if cat is not None else ""
        lines.append("    " + " & ".join([cat_cell, measure, dim, source, setting]) + r"\\")
    lines.append(r"    \bottomrule")
    lines.append(r"  \end{tabularx}")
    lines.append(r"\end{table}")
    return "\n".join(lines) + "\n", report


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 4.4.3 的碳减排措施分类表")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"输出 tex 路径（默认 {DEFAULT_OUT.relative_to(REPO_ROOT)}）")
    args = ap.parse_args()
    tex, report = build_table()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(tex)
    print("# 逐格取数报告", file=sys.stderr)
    for line in report:
        print(line, file=sys.stderr)
    print(f"\n已写出 {rel(args.out)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
