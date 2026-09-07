#!/usr/bin/env python3
"""图：各类代表措施的实测成绩横向对比（4.4.3，2026-09-07）。

## 这张图为哪句话服务

4.4.3 正文把三类单一措施（碳规制政策 / 购置端财政激励 / 需求响应政策）各挑代表
逐一实测，政策表已把 12 列数字摆全，但读者要在表里逐行找 7 个单一措施、跳过
基准与本文方案行才能比出"谁降本、谁减排、谁两头不讨好"。本图只留这 7 个单一
措施，把 Δ总成本与 Δ碳排量分两格并排画成横向柱状图，按三类分组、组间留空并在
轴下用横括号标类别名（2026-09-08 用户定：去掉图例），不画本文方案——本文方案
与单一措施的对照由散点图 `figure_policy_scatter.pdf` 承担。

## 数据从哪来（不另立口径）

直接复用表 13 的生成器 `build_policy_table.py`：行清单用它的 `ROWS`，取数用它的
`resolve_row` / `resolve_carbon_price_row_from_pool`，分支顺序与它的 `build_table()`
一致（与 `generate_policy_scatter_figure.py` 的 `load_points()` 同一套逻辑，
这里不重复自己写 find_solutions + aggregate_breakdown）。
只保留 `category` 不是"组合"、也不是"本文方案"（若未来 ROWS 加了这个类别）的行，
且排除 `group=="baseline"` 本身（基准只作 Δ 的参照系，不画成柱子——它的 Δ 恒为 0）。
Δ 相对 `group=="baseline"` 的行计算，与表 13 的 Δ 两列同义。

`--percent` 版把 Δ总成本 / Δ碳排量换成相对基准总成本 / 总排放的百分比
（分母＝基准行的 total_cost / E_total），其余口径不变。

## 画风

黑白灰、Songti、图例无框、8pt、通栏 6.9×2.7 英寸（与 `generate_policy_scatter_figure.py`
同一套字体抽取与配色纪律）。两格并排：(a) Δ总成本，(b) Δ碳排量；横轴 7 个措施
（两行简称标签），按类别分三组（碳规制政策 4、购置端财政激励 1、需求响应政策 2，
组序＝表 13 ROWS 的行序，2026-09-09 起与分类图一致），
组间留空、轴下方用横括号标类别名（画法照抄 `generate_tariff_carbon_window_figure.py`
的 `WINDOWS` 括号，只是挪到轴下方、用 blended transform 把 y 锚在 axes 分数坐标）。
柱子按类别三种灰度：需求响应政策＝白底黑边，碳规制政策＝浅灰，购置端财政激励＝深灰；
零线黑细线；柱顶标数值（8pt），负数标在柱下。同一措施在 (a) (b) 两格的横轴位置对齐。

用法（须用仓库 venv）：
  .public-hgs-venv/bin/python3 solver/scripts/generate_policy_bar_figure.py [--percent] [--out PDF]
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from fontTools.ttLib import TTCollection
from matplotlib import font_manager
from matplotlib.transforms import blended_transform_factory

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "solver/scripts"))
import build_policy_table as bpt  # noqa: E402

OUT = REPO / "docs/paper_v2/generated_figures/figure_policy_bars.pdf"
OUT_PCT = REPO / "docs/paper_v2/generated_figures/figure_policy_bars_percent.pdf"
TEXT_PT = 8.0
_FONT_TMP = tempfile.TemporaryDirectory(prefix="resetp_policy_bar_font_")

# 排除的类别：本文方案（bpt.CAT_COMBO 当前取值即"本文方案"）只出现在散点图上；
# 字面量 "组合" 是旧类别名，留着让改名前的调用也能被排掉。
EXCLUDED_CATEGORIES = {bpt.CAT_COMBO, "组合", "本文方案"}

# 两行简称标签：键＝表 13 ROWS 的 new_dir，与 generate_policy_scatter_figure.py
# 的 SHORT_BY_DIR 用同一批短名，这里只是排成两行给横轴用。
SHORT_LABEL_BY_DIR: dict[str, tuple[str, str]] = {
    "solver/reports/grid2x2_v3_20260906/midday/P=0.2/MTC-HGS": ("午间谷段", "谷段\n午间"),
    "solver/reports/policy_combos_20260907/green_window": ("午间谷价补贴", "谷价\n补贴"),
    "solver/reports/carbon_price_sweep_v3_20260906/P=0.07502": ("碳价0.075", "碳价\n0.075"),
    "solver/reports/grid2x2_v3_20260906/beijing/P=1.0/MTC-HGS": ("碳价1.0", "碳价\n1.0"),
    "solver/reports/carbon_price_sweep_v3_20260906/P=1.5": ("碳价1.5", "碳价\n1.5"),
    "solver/reports/policy_combos_20260907/quota200": ("碳配额200", "碳配额\n200"),
    "solver/reports/policy_combos_20260907/subsidy_alone": ("购置补贴", "购置\n补贴"),
}

# 类别 -> (facecolor, edgecolor, linewidth)：价格信号协调＝白底黑边，
# 碳定价＝浅灰，车队经济性＝深灰。
CATEGORY_STYLE: dict[str, tuple[str, str, float]] = {
    bpt.CAT_PRICE_SIGNAL: ("white", "black", 0.8),
    bpt.CAT_CARBON_PRICING: ("0.75", "black", 0.5),
    bpt.CAT_FLEET_ECON: ("0.35", "black", 0.5),
}

# 轴下横括号的类别标签：只跨 1 根柱子的类别，7 个字会压到邻组上，折成两行。
BRACKET_LABEL: dict[str, str] = {
    bpt.CAT_FLEET_ECON: "购置端\n财政激励",
}

BAR_WIDTH = 0.62
GROUP_GAP = 1.0  # 组间额外留空（单位＝柱位）


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _songti_regular() -> Path:
    source = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    target = Path(_FONT_TMP.name) / "songti_sc_regular.ttf"
    for font in TTCollection(source).fonts:
        names = {r.toUnicode() for r in font["name"].names if r.nameID == 6}
        if "STSongti-SC-Regular" in names:
            font.save(target)
            return target
    raise RuntimeError("Songti SC Regular face not found")


def load_bars() -> tuple[dict, list[dict]]:
    """按表 13 的口径取每一行；返回 (基准 breakdown, 7 个单一措施的点列表)。

    与 generate_policy_scatter_figure.py 的 load_points() 同一套分支逻辑
    （碳价池化开关当前为 False，两者当前等价于逐行 resolve_row）。
    """
    pool: list = []
    if bpt.CARBON_ROWS_FROM_POOL and any(bpt.is_carbon_price_row(r) for r in bpt.ROWS):
        pool = bpt.load_carbon_sweep_pool()

    baseline = None
    bars: list[dict] = []
    for row in bpt.ROWS:
        if bpt.CARBON_ROWS_FROM_POOL and bpt.is_carbon_price_row(row):
            result = bpt.resolve_carbon_price_row_from_pool(row, pool)
        else:
            result = bpt.resolve_row(row, False)
        if result is None:
            print(f"缺失：{row['new_dir']} —— 跳过该行", file=sys.stderr)
            continue
        _source, _paths, bd = result
        if row["group"] == "baseline":
            baseline = bd
            continue
        if row["category"] in EXCLUDED_CATEGORIES or row["group"] == "combo":
            continue
        short, label2 = SHORT_LABEL_BY_DIR.get(row["new_dir"], (row["new_dir"], row["new_dir"]))
        bars.append(dict(
            short=short, label2=label2, category=row["category"], new_dir=row["new_dir"],
            n=bd.get("__n__", 1), bd=bd,
        ))
    if baseline is None:
        raise RuntimeError("基准行缺失，Δ 无从算起")
    return baseline, bars


def style_axes(ax):
    ax.tick_params(direction="out", length=2.5, width=0.5, pad=2, labelsize=TEXT_PT)
    for s in ax.spines.values():
        s.set_linewidth(0.5)


def group_spans(bars: list[dict]) -> list[tuple[str, int, int]]:
    """按 bars 里连续相同 category 分段，返回 [(类别, 起下标, 止下标)]（左闭右开）。"""
    spans = []
    i = 0
    while i < len(bars):
        cat = bars[i]["category"]
        j = i
        while j < len(bars) and bars[j]["category"] == cat:
            j += 1
        spans.append((cat, i, j))
        i = j
    return spans


def bar_positions(bars: list[dict]) -> list[float]:
    """按类别分段留空的横轴柱位（组间加 GROUP_GAP，组内间距 1）。"""
    positions = []
    x = 0.0
    prev_cat = None
    for b in bars:
        if prev_cat is not None and b["category"] != prev_cat:
            x += GROUP_GAP
        positions.append(x)
        x += 1.0
        prev_cat = b["category"]
    return positions


def draw_bracket(ax, x0: float, x1: float, label: str, y_axes: float, tick_axes: float):
    """在轴下方（axes 分数坐标）画一个横括号并标类别名，画法照抄
    generate_tariff_carbon_window_figure.py 的 WINDOWS 括号，只是 x 用 data
    坐标、y 用 axes 分数坐标（blended transform），且挪到 0 以下。"""
    trans = blended_transform_factory(ax.transData, ax.transAxes)
    ax.plot([x0, x0, x1, x1], [y_axes + tick_axes, y_axes, y_axes, y_axes + tick_axes],
            color="black", linewidth=0.6, transform=trans, clip_on=False, zorder=3)
    ax.text((x0 + x1) / 2, y_axes - 0.02, label, ha="center", va="top",
             fontsize=TEXT_PT - 1, transform=trans, clip_on=False)


def draw_panel(ax, bars: list[dict], positions: list[float], values: list[float],
               ylabel: str, value_fmt):
    ymin, ymax = min(values + [0.0]), max(values + [0.0])
    span = ymax - ymin
    pad = max(0.12 * span, 1.0)
    ax.set_ylim(ymin - pad, ymax + pad)
    ax.axhline(0.0, color="black", linewidth=0.6, zorder=2)

    for pos, b, v in zip(positions, bars, values):
        fc, ec, lw = CATEGORY_STYLE[b["category"]]
        ax.bar(pos, v, width=BAR_WIDTH, facecolor=fc, edgecolor=ec, linewidth=lw, zorder=3)
        label_gap = 0.03 * (ymax - ymin + 2 * pad)
        if v >= 0:
            ax.text(pos, v + label_gap, value_fmt(v), ha="center", va="bottom",
                     fontsize=TEXT_PT - 1, zorder=4)
        else:
            ax.text(pos, v - label_gap, value_fmt(v), ha="center", va="top",
                     fontsize=TEXT_PT - 1, zorder=4)

    ax.set_xlim(min(positions) - 0.75, max(positions) + 0.75)
    ax.set_xticks(positions)
    ax.set_xticklabels([b["label2"] for b in bars], fontsize=TEXT_PT, linespacing=1.15)
    ax.set_ylabel(ylabel, fontsize=TEXT_PT)
    style_axes(ax)

    for cat, i, j in group_spans(bars):
        x0 = positions[i] - BAR_WIDTH / 2 - 0.18
        x1 = positions[j - 1] + BAR_WIDTH / 2 + 0.18
        draw_bracket(ax, x0, x1, BRACKET_LABEL.get(cat, cat),
                     y_axes=-0.30, tick_axes=0.035)


def fmt_value_abs(v: float) -> str:
    return f"{v:.2f}" if v >= 0 else f"-{abs(v):.2f}"


def fmt_value_pct(v: float) -> str:
    return f"{v:.2f}%" if v >= 0 else f"-{abs(v):.2f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--percent", action="store_true",
                    help="出相对基准总成本/总排放的百分比版（默认出绝对值版）")
    ap.add_argument("--out", type=Path, default=None,
                    help=f"输出 pdf 路径（默认绝对值版 {rel(OUT)}，百分比版 {rel(OUT_PCT)}）")
    args = ap.parse_args()

    out_path = args.out if args.out is not None else (OUT_PCT if args.percent else OUT)

    baseline, bars = load_bars()
    if len(bars) != 7:
        print(f"警告：单一措施行数={len(bars)}，预期 7 个（价格信号协调2/碳定价4/车队经济性1）",
              file=sys.stderr)

    dcosts = [b["bd"]["total_cost"] - baseline["total_cost"] for b in bars]
    dcarbons = [b["bd"]["E_total"] - baseline["E_total"] for b in bars]

    if args.percent:
        cost_vals = [d / baseline["total_cost"] * 100.0 for d in dcosts]
        carbon_vals = [d / baseline["E_total"] * 100.0 for d in dcarbons]
        value_fmt = fmt_value_pct
        cost_ylabel = "$\\Delta$总成本（%）"
        carbon_ylabel = "$\\Delta$碳排量（%）"
    else:
        cost_vals = dcosts
        carbon_vals = dcarbons
        value_fmt = fmt_value_abs
        cost_ylabel = "$\\Delta$总成本（元）"
        carbon_ylabel = "$\\Delta$碳排量（kgCO$_2$e）"

    print(f"# 各柱数值（percent={args.percent}）", file=sys.stderr)
    print(f"基准：total_cost={baseline['total_cost']:.2f} 元  "
          f"E_total={baseline['E_total']:.2f} kgCO2e", file=sys.stderr)
    for b, dc, dk, cv, kv in zip(bars, dcosts, dcarbons, cost_vals, carbon_vals):
        print(f"  {b['short']:<12s} 类别={b['category']:<8s} n={b['n']:<3d} "
              f"Δ总成本={dc:+9.2f}元  Δ碳排量={dk:+9.2f}kg  "
              f"→ 图值: 成本格={value_fmt(cv)}  碳排格={value_fmt(kv)}", file=sys.stderr)

    font_path = _songti_regular()
    font_manager.fontManager.addfont(str(font_path))
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font_path)).get_name()
    plt.rcParams["axes.unicode_minus"] = False

    positions = bar_positions(bars)

    fig, (ax_cost, ax_carbon) = plt.subplots(1, 2, figsize=(6.9, 2.7))
    draw_panel(ax_cost, bars, positions, cost_vals, cost_ylabel, value_fmt)
    draw_panel(ax_carbon, bars, positions, carbon_vals, carbon_ylabel, value_fmt)
    ax_cost.set_title("(a) $\\Delta$总成本", fontsize=TEXT_PT, y=-0.62)
    ax_carbon.set_title("(b) $\\Delta$碳排量", fontsize=TEXT_PT, y=-0.62)

    # 2026-09-08 用户定：去掉图例，类别只由轴下横括号标注（图例与括号重复标同一件事）。

    fig.subplots_adjust(left=0.085, right=0.99, bottom=0.38, top=0.96, wspace=0.30)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    fig.savefig(out_path.with_suffix(".png"), dpi=200)
    print(f"\n已写出 {rel(out_path)} 与同名 .png（6.9×2.7 英寸）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
