#!/usr/bin/env python3
"""生成论文图 5「单位碳价扫描曲线」（figure_5_carbon_price_sweep）。

回答的问题：碳价定在哪一档，企业才会真的为减排改充电时刻、并因此多付电费？

数据源
  solver/reports/charge_timing_sweep_v2_20260906/summary.json（碳价密扫总表），
  只用日历 `original`（北京现行分时电价时段）。密扫本身没有跑任何路线搜索：
  它取 solver/reports/grid2x2_v2_20260905/beijing/P=0.2 里 MT-HGS 与 MTC-HGS
  两臂各 10 次的既有路线（共 20 组），路线固定不动，只在每个碳价档位下按四种
  充电择时策略重排充电时刻并精确评价。基准策略是 `asap`＝有可用时段即充电。

  三条曲线/参考线的字段（全部 `contrasts_vs_asap`，即「该策略 − asap」的解间均值）：
    实线＋圆点   cells['T=original/P=<档>']['cost_plus_carbon']['E_total']['mean']
    水平虚线     cells['T=original/P=<任一档>']['carbon_min']['E_total']['mean']
    水平点线     cells['T=original/P=0.0']['cost_plus_carbon']['E_total']['mean']
    右轴阶梯     cells['T=original/P=<档>']['carbon_deviation']['n_deviating']

  两条水平参考线之所以是「水平的」，各有一条实测断言撑着，脚本里再核一遍（见 SELF-CHECK）：
    * `carbon_min` 只看碳强度、不看碳价，它的时刻在所有碳价下逐位相同；
    * 碳价为 0 时碳项从目标函数里消失，`cost_plus_carbon` 与只按电价择时的
      `cost_min` 逐位相同——所以 0.0 那一档既是曲线的起点，也就是「只按电价择时」的水平。

画风（与 solver/scripts/generate_carbon_charging_figure.py 完全同一套常量）
  纯黑白灰、无彩色；宋体走中文、Times 走数字；画布宽度锁死在版心宽度 501.06 pt 上，
  与图 3 通栏同宽。

横轴 0–2.0 元/kgCO2e 线性。密扫里还有 3.0 那一档，**不画在主轴上**（用户 2026-09-06 令），
它的数值由脚本打印、写进正文。

用法（仓库根目录）：
    export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src:solver/scripts'
    .public-hgs-venv/bin/python3 solver/scripts/generate_carbon_price_sweep_figure.py
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from fontTools.ttLib import TTCollection
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.transforms import Bbox

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SWEEP = REPO / "solver/reports/charge_timing_sweep_v2_20260906/summary.json"
OUT = REPO / "docs/paper_v2/generated_figures/figure_5_carbon_price_sweep.pdf"

CALENDAR = "original"
BASELINE_LABEL = "有可用时段即充电"      # asap，图 3 与表 10–13 统一用词
CURVE_LABEL = "考虑时变碳强度"          # cost_plus_carbon，同上
CARBON_ONLY_LABEL = "只按碳强度择时"     # carbon_min（用户 2026-09-06 定的标签）
PRICE_ONLY_LABEL = "只按电价择时"        # cost_min＝碳价为 0 时的 cost_plus_carbon
DEVIATION_LABEL = "为减排多付电费的路线组数"

# 主轴只画到这里；3.0 那一档留给正文报数（用户 2026-09-06 令）。
X_MAX = 2.0
# 两条竖虚线：现行全国碳市场价与本文基准碳价。
MARKERS = ((0.07502, "现行"), (0.20, "基准"))

# 门槛带：固定区间（用户 2026-09-06 令），不再取 load_series() 算出的
# 「最终平台起点」，而是首次有路线为减排多付电费的碳价（0.5）到第一个长平台
# 开始的碳价（0.8）。load_series() 里的 onset/settle 仍照算、照打（main() 正文
# 报数要用），只是不再喂给这条带子与它的图例文字。
BAND = (0.5, 0.8)

# ---- 画风常量：逐条抄自 generate_carbon_charging_figure.py，不得各画各的 ----
TARGET_WIDTH_PT = 501.056875
PALETTE = {"ink": "#000000", "gray": "#666666", "light_gray": "#D9D9D9"}
# 门槛带底色。区间固定为 0.5--0.8（见上方 BAND），只占横轴一成半，比先前
# 数据定出来的 0.5--1.9（七成宽）窄很多；颜色仍沿用 #F2F2F2（比 light_gray
# 浅得多），与其余同风格图表一致，不因区间变窄而改深。
BAND_GRAY = "#F2F2F2"
AXIS_WIDTH_PT = 0.468
CURVE_WIDTH_PT = 0.62
TEXT_SIZE_PT = 8.0
LEGEND_SIZE_PT = 6.8
ANNOT_SIZE_PT = 7.0
MARKER_SIZE_PT = 1.9

_FONT_TMP = tempfile.TemporaryDirectory(prefix="resetp_sweep_fig_font_")


def _songti_regular() -> Path:
    """取 Songti.ttc 中的常规字面；matplotlib 默认会选到 Black 字面。"""
    source = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    target = Path(_FONT_TMP.name) / "songti_sc_regular.ttf"
    for font in TTCollection(source).fonts:
        names = {r.toUnicode() for r in font["name"].names if r.nameID == 6}
        if "STSongti-SC-Regular" in names:
            font.save(target)
            return target
    raise RuntimeError("Songti SC Regular face not found in system Songti.ttc")


CN = font_manager.FontProperties(fname=_songti_regular(), size=TEXT_SIZE_PT)
CN_LEGEND = CN.copy()
CN_LEGEND.set_size(LEGEND_SIZE_PT)
CN_ANNOT = CN.copy()
CN_ANNOT.set_size(ANNOT_SIZE_PT)

plt.rcParams.update(
    {
        "font.family": "Times New Roman",
        "font.size": TEXT_SIZE_PT,
        "axes.linewidth": AXIS_WIDTH_PT,
        "lines.linewidth": CURVE_WIDTH_PT,
        "xtick.major.width": AXIS_WIDTH_PT,
        "ytick.major.width": AXIS_WIDTH_PT,
        "axes.unicode_minus": False,
        "pdf.fonttype": 42,
        "savefig.dpi": 300,
    }
)


# --------------------------------------------------------------------------
# 取数与自检
# --------------------------------------------------------------------------
def load_series(summary_path: Path) -> dict:
    """读密扫总表，抽出本图要画的四组数，并做五条自检。

    自检全部是**逐位**比较：这些量在数学上就该相等，允许公差等于放弃检查。
    """
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    cells = data["cells"]

    # 自检 1、2：总表自己的两条断言字段必须为 0（碳成本恒等式、碳价为 0 时两策略同一）。
    assert data["carbon_identity_max_abs_deviation"] == 0.0, (
        "carbon_identity_max_abs_deviation != 0，碳成本恒等式未逐位成立"
    )
    zero_dev = data["zero_price_cost_plus_carbon_vs_cost_min_max_abs_deviation"]
    assert zero_dev == 0.0, (
        f"碳价为 0 时 cost_plus_carbon 与 cost_min 不逐位相同（max|diff|={zero_dev}），"
        "「只按电价择时」这条水平线的依据不成立"
    )

    labels = [
        label
        for label in data["carbon_prices"]
        if f"T={CALENDAR}/P={label}" in cells and float(label) <= X_MAX
    ]
    labels.sort(key=float)
    assert labels and labels[0] == "0.0", f"最低档不是 0.0：{labels[:3]}"

    xs = [float(label) for label in labels]
    curve = [
        cells[f"T={CALENDAR}/P={label}"]["contrasts_vs_asap"]["cost_plus_carbon"][
            "E_total"
        ]["mean"]
        for label in labels
    ]
    n_dev = [
        cells[f"T={CALENDAR}/P={label}"]["carbon_deviation"]["n_deviating"]
        for label in labels
    ]

    # 自检 3：右轴分母必须在所有档位上恒定，否则 0–N 这根阶梯线的量纲在图里悄悄变了。
    denominators = {
        cells[f"T={CALENDAR}/P={label}"]["carbon_deviation"]["n_comparable"]
        for label in data["carbon_prices"]
        if f"T={CALENDAR}/P={label}" in cells
    }
    assert len(denominators) == 1, f"右轴分母在各碳价下不一致：{sorted(denominators)}"
    denominator = denominators.pop()

    # 自检 4：carbon_min 的 ΔE 在所有碳价下逐位相同，才能画成一条水平线。
    carbon_only_values = {
        cells[f"T={CALENDAR}/P={label}"]["contrasts_vs_asap"]["carbon_min"]["E_total"][
            "mean"
        ]
        for label in data["carbon_prices"]
        if f"T={CALENDAR}/P={label}" in cells
    }
    assert len(carbon_only_values) == 1, (
        f"carbon_min 的 ΔE 随碳价变化：{sorted(carbon_only_values)}，不能画成水平线"
    )
    carbon_only = carbon_only_values.pop()

    # 自检 5：曲线在 0.0 档必须逐位等于 cost_min（＝只按电价择时）的 ΔE。
    price_only = cells[f"T={CALENDAR}/P=0.0"]["contrasts_vs_asap"]["cost_min"][
        "E_total"
    ]["mean"]
    assert curve[0] == price_only, (
        f"0.0 档曲线值 {curve[0]!r} 不等于 cost_min 的 {price_only!r}"
    )

    # ---- 门槛带：完全由数据定，不写死 ----
    all_labels = sorted(
        (
            label
            for label in data["carbon_prices"]
            if f"T={CALENDAR}/P={label}" in cells
        ),
        key=float,
    )
    all_dev = [
        cells[f"T={CALENDAR}/P={label}"]["carbon_deviation"]["n_deviating"]
        for label in all_labels
    ]
    onset = next(
        (float(label) for label, k in zip(all_labels, all_dev) if k > 0), None
    )
    final = all_dev[-1]
    settle_index = len(all_dev) - 1
    while settle_index > 0 and all_dev[settle_index - 1] == final:
        settle_index -= 1
    settle = float(all_labels[settle_index])

    plateaus: list[tuple[str, str, int]] = []
    for label, k in zip(all_labels, all_dev):
        if plateaus and plateaus[-1][2] == k:
            plateaus[-1] = (plateaus[-1][0], label, k)
        else:
            plateaus.append((label, label, k))

    return {
        "labels": labels,
        "x": xs,
        "curve": curve,
        "n_deviating": n_dev,
        "denominator": denominator,
        "carbon_only": carbon_only,
        "price_only": price_only,
        "onset": onset,
        "settle": settle,
        "plateaus": plateaus,
        "all_labels": all_labels,
        "all_dev": all_dev,
        "cells": cells,
        "wall_clock_seconds": data["wall_clock_seconds"],
    }


# --------------------------------------------------------------------------
# 画图
# --------------------------------------------------------------------------
def build_figure(series: dict):
    # 高度 3.5 in：宽度被版心锁死在 501.06 pt（6.96 in），3.0 in 时坐标区只剩 ~150 pt 高，
    # 0.5--0.8 之间那三级台阶（−8.57 / −8.93 / −9.12）在纵向只差 3 pt，看不出是台阶。
    figure, ax = plt.subplots(figsize=(6.9, 3.5))
    figure.subplots_adjust(left=0.072, right=0.918, bottom=0.132, top=0.972)

    ink = PALETTE["ink"]
    gray = PALETTE["gray"]

    # 门槛带压在最底层（固定区间，见模块常量 BAND）
    ax.axvspan(
        BAND[0],
        min(BAND[1], X_MAX),
        facecolor=BAND_GRAY,
        edgecolor="none",
        zorder=0,
    )

    # 两条竖虚线
    for x, _text in MARKERS:
        ax.axvline(
            x,
            color=gray,
            linestyle=(0, (3, 2)),
            linewidth=AXIS_WIDTH_PT,
            zorder=1,
        )

    # 两条水平参考线（左轴口径）
    ax.axhline(
        series["carbon_only"],
        color=ink,
        linestyle=(0, (4, 2.4)),
        linewidth=CURVE_WIDTH_PT,
        zorder=2,
    )
    ax.axhline(
        series["price_only"],
        color=gray,
        linestyle=(0, (1, 1.6)),
        linewidth=CURVE_WIDTH_PT,
        zorder=2,
    )

    # 主曲线
    ax.plot(
        series["x"],
        series["curve"],
        color=ink,
        linestyle="-",
        linewidth=CURVE_WIDTH_PT,
        marker="o",
        markersize=MARKER_SIZE_PT,
        markerfacecolor=ink,
        markeredgecolor=ink,
        zorder=4,
    )

    ax.set_xlim(-0.045, X_MAX + 0.045)
    ax.set_xticks([round(0.2 * i, 1) for i in range(11)])
    ax.set_xlabel("单位碳价（元/kgCO$_2$e）", fontproperties=CN, labelpad=2.0)
    ax.set_ylabel("$\\Delta$碳排量（kgCO$_2$e）", fontproperties=CN, labelpad=2.0)
    ax.set_ylim(-13.2, -2.2)
    ax.set_yticks([-12, -10, -8, -6, -4])
    ax.tick_params(axis="both", labelsize=TEXT_SIZE_PT, pad=1.8)
    for side in ("top",):
        ax.spines[side].set_visible(False)

    # 右轴：阶梯线
    ax2 = ax.twinx()
    ax2.step(
        series["x"],
        series["n_deviating"],
        where="post",
        color=gray,
        linewidth=CURVE_WIDTH_PT * 1.35,
        zorder=3,
    )
    ceiling = series["denominator"]
    ax2.set_ylim(-0.55, ceiling + 0.55)
    ax2.set_yticks([0, 5, 10, 15, ceiling])
    ax2.set_ylabel(DEVIATION_LABEL + "（组）", fontproperties=CN, labelpad=3.0)
    ax2.tick_params(axis="y", labelsize=TEXT_SIZE_PT, pad=1.8)
    ax2.spines["top"].set_visible(False)

    # 竖线标注：两条线只差 0.125 元，横排两字会贴到一起，改竖排
    for x, text in MARKERS:
        ax.annotate(
            text,
            xy=(x, -2.95),
            xytext=(2.2, 0),
            textcoords="offset points",
            rotation=90,
            ha="left",
            va="top",
            fontproperties=CN_ANNOT,
            color=gray,
            zorder=5,
        )

    handles = [
        Line2D(
            [], [], color=ink, linestyle="-", linewidth=CURVE_WIDTH_PT,
            marker="o", markersize=MARKER_SIZE_PT,
            markerfacecolor=ink, markeredgecolor=ink,
            label=CURVE_LABEL,
        ),
        Line2D(
            [], [], color=ink, linestyle=(0, (4, 2.4)),
            linewidth=CURVE_WIDTH_PT, label=CARBON_ONLY_LABEL,
        ),
        Line2D(
            [], [], color=gray, linestyle=(0, (1, 1.6)),
            linewidth=CURVE_WIDTH_PT, label=PRICE_ONLY_LABEL,
        ),
        Line2D(
            [], [], color=gray, linestyle="-", linewidth=CURVE_WIDTH_PT * 1.35,
            label=DEVIATION_LABEL + "（右轴）",
        ),
    ]
    # 带子是固定区间（见模块常量 BAND），标签里的数字由它生成，不手写。
    handles.append(
        Patch(
            facecolor=BAND_GRAY,
            edgecolor="none",
            label=f"门槛带 {BAND[0]:g}–{BAND[1]:g}",
        )
    )
    legend = ax.legend(
        handles=handles,
        loc="upper right",
        bbox_to_anchor=(0.999, 0.998),
        ncol=2,
        prop=CN_LEGEND,
        frameon=True,
        framealpha=1.0,
        facecolor="white",
        edgecolor="none",
        borderpad=0.35,
        handlelength=2.4,
        handletextpad=0.45,
        columnspacing=1.1,
        labelspacing=0.32,
        borderaxespad=0.0,
    )
    legend.set_zorder(6)
    return figure, ax, ax2, legend


def _save_at_target_width(figure, out_path: Path, pad_in: float = 0.05):
    """按内容紧边界裁剪，宽度锁死在版心宽度上并让内容居中（抄自图 3 的生成器）。"""
    figure.canvas.draw()
    tight = figure.get_tightbbox(figure.canvas.get_renderer())
    target_in = TARGET_WIDTH_PT / 72.0
    if tight.width > target_in:
        raise RuntimeError(
            f"内容宽度 {tight.width * 72:.2f} pt 已超过版心宽度 {TARGET_WIDTH_PT:.2f} pt"
        )
    centre = 0.5 * (tight.x0 + tight.x1)
    box = Bbox(
        [
            [centre - target_in / 2, tight.y0 - pad_in],
            [centre + target_in / 2, tight.y1 + pad_in],
        ]
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out_path, format="pdf", bbox_inches=box, pad_inches=0,
                   facecolor="white")
    png_path = out_path.with_suffix(".png")
    figure.savefig(png_path, format="png", bbox_inches=box, pad_inches=0,
                   facecolor="white", dpi=300)
    return TARGET_WIDTH_PT, box.height * 72, png_path


def _overlap_report(figure, legend, ax, series) -> None:
    """打印图例外框与曲线、阶梯线的最小间距，替代肉眼估计。"""
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    box = legend.get_window_extent(renderer)
    inv = ax.transData.inverted()
    (x0, y0), (x1, y1) = inv.transform([[box.x0, box.y0], [box.x1, box.y1]])
    print(
        f"  图例数据坐标范围 x∈[{x0:.3f}, {x1:.3f}]，左轴 y∈[{y0:.2f}, {y1:.2f}]"
    )
    inside = [
        (x, y)
        for x, y in zip(series["x"], series["curve"])
        if x0 <= x <= x1 and y0 <= y <= y1
    ]
    print(f"  落在图例框内的曲线点：{len(inside)} 个"
          + ("（⚠ 遮住曲线了）" if inside else "（未遮曲线）"))
    print(f"  图例底沿 {y0:.2f} 与「只按电价择时」水平线 {series['price_only']:.2f} 的"
          f"间距：{y0 - series['price_only']:.2f} kgCO2e")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summary", type=Path, default=DEFAULT_SWEEP)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    series = load_series(args.summary)
    print(f"数据源 {args.summary.relative_to(REPO)}（密扫墙钟 "
          f"{series['wall_clock_seconds']:.1f} 秒），日历 {CALENDAR}")
    print("五条自检全部通过（碳成本恒等式、0 档两策略同一、右轴分母恒定、"
          "carbon_min 水平、0 档曲线＝只按电价择时）")
    print(f"  右轴分母 n_comparable = {series['denominator']}（所有碳价档恒定）")
    print(f"  只按碳强度择时 ΔE = {series['carbon_only']:.4f} kgCO2e（水平虚线）")
    print(f"  只按电价择时   ΔE = {series['price_only']:.4f} kgCO2e（水平点线＝0.0 档）")
    print("  n_deviating 平台（起档–止档：值）：")
    for lo, hi, k in series["plateaus"]:
        print(f"    {lo:>7} – {hi:<7}: {k}")
    print(f"  门槛带：首个 n_deviating>0 在 {series['onset']}，"
          f"到达并保持终值 {series['all_dev'][-1]} 在 {series['settle']}")
    beyond = [lab for lab in series["all_labels"] if float(lab) > X_MAX]
    for lab in beyond:
        cell = series["cells"][f"T={CALENDAR}/P={lab}"]
        block = cell["contrasts_vs_asap"]["cost_plus_carbon"]
        print(
            f"  主轴外档位 P={lab}（正文报数）："
            f"Δ碳排量 {block['E_total']['mean']:.4f}、"
            f"Δ充电成本 {block['cost_elec']['mean']:.4f}、"
            f"Δ总成本 {block['total_cost']['mean']:.4f}、"
            f"n_deviating {cell['carbon_deviation']['n_deviating']}"
        )

    figure, ax, ax2, legend = build_figure(series)
    _overlap_report(figure, legend, ax, series)
    width_pt, height_pt, png_path = _save_at_target_width(figure, args.out)
    print(f"\nwrote {args.out.relative_to(REPO)}")
    print(f"wrote {png_path.relative_to(REPO)}")
    print(f"画布 {width_pt:.2f} × {height_pt:.2f} pt")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
