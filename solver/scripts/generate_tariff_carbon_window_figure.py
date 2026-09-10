#!/usr/bin/env python3
"""图：分时电价、电网碳强度与补电窗口的时段关系（4.4.2，2026-09-06 第四版＝条件图）。

只画**条件**，不画结果：电价的谷与碳强度的峰重叠在同一段夜里；碳强度最低点落在下午班的灰带里；
首趟前补电窗口横跨整夜、压在最脏的一段上。"谁在何时充了多少"由表 11 的起充时刻列承担（用户 2026-09-06 定：
图讲形状与相对位置，表讲四方案×三窗口的账，文字做推理）。第三版的充电电量柱已撤（杂且只画得下两种安排）。

体裁：两格并排（左格碳强度、右格电价），用虚线标出作业班次边界；三个补电窗口以横括号标在格顶：
  首趟出车前（前一日 19:00 下午班结束→当日 07:30＝开工 08:00 − 一次补电）、午休（11:00–13:00）、趟间（13:00–19:00，无余量）；
图例在每格左上角、竖排、无框；横轴自前一日 12:00 至当日 24:00，00:00 处灰虚线为日期变更线。
数据：日历 beijing 2025-02-12；班次 shift_contract.json。
用法（须用仓库 venv）：.public-hgs-venv/bin/python3 solver/scripts/generate_tariff_carbon_window_figure.py [--out PDF]
"""

from __future__ import annotations

import argparse
import csv
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

REPO = Path(__file__).resolve().parents[2]
CAL = REPO / "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv"
SHIFT = REPO / "data/ChinaInstances/china81_final_suite_v2_20260815/instances/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/shift_contract.json"
OUT = REPO / "docs/paper_v2/generated_figures/figure_4_tariff_carbon_windows.pdf"

X0, X1 = -12.0, 24.0  # 横轴：前一日 12:00 → 当日 24:00（小时，负数为前一日）
WINDOWS = [  # (标签, 起, 止) 小时
    ("首趟出车前", -5.0, 7.5),
    ("午休", 11.0, 13.0),
    ("趟间", 13.0, 19.0),
]
BRACKET_FRAC = 0.80   # 括号所在高度（轴分数）
BAND_TOP_FRAC = 0.72  # 灰带顶（轴分数），压在括号之下
TEXT_PT = 8.0
BAND_COLOR = "#EFEFEF"
_FONT_TMP = tempfile.TemporaryDirectory(prefix="resetp_window_fig_font_")


def _songti_regular() -> Path:
    source = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    target = Path(_FONT_TMP.name) / "songti_sc_regular.ttf"
    for font in TTCollection(source).fonts:
        names = {r.toUnicode() for r in font["name"].names if r.nameID == 6}
        if "STSongti-SC-Regular" in names:
            font.save(target)
            return target
    raise RuntimeError("Songti SC Regular face not found")


def load_calendar():
    rows = [r for r in csv.DictReader(open(CAL, encoding="utf-8")) if r["city"] == "beijing" and r["date"] == "2025-02-12"]
    rows.sort(key=lambda r: int(r["minute_of_day"]))
    assert len(rows) == 48
    return [float(r["depot_energy_cny_per_kwh"]) for r in rows], [float(r["carbon_factor_kgco2e_per_kwh"]) for r in rows]


def step_xy(values):
    xs, ys = [], []
    for h2 in range(int(X0 * 2), int(X1 * 2)):
        xs += [h2 / 2, (h2 + 1) / 2]
        ys += [values[h2 % 48], values[h2 % 48]]
    return xs, ys


def draw_panel(ax, values, ylabel, ymax, ytick_step, shifts):
    for day in (-24.0, 0.0):
        for name in ("AM", "PM"):
            a = day + shifts[name]["start_minute"] / 60
            b = day + shifts[name]["end_minute"] / 60
            if b > X0 and a < X1:
                ax.axvspan(max(a, X0), min(b, X1), ymin=0, ymax=BAND_TOP_FRAC,
                           color=BAND_COLOR, linewidth=0, zorder=0)
    ax.axvline(0.0, color="#808080", linewidth=0.5, linestyle=(0, (3, 2)), zorder=1)
    xs, ys = step_xy(values)
    ax.plot(xs, ys, color="black", linewidth=0.8, zorder=2)
    ax.set_xlim(X0 - 0.5, X1 + 0.5)
    ax.set_ylim(0, ymax)
    ticks = [-12, -8, -4, 0, 4, 8, 12, 16, 20, 24]
    ax.set_xticks(ticks)
    ax.set_xticklabels(["24" if t == 24 else f"{t % 24:02d}" for t in ticks], fontsize=TEXT_PT)
    yt = [round(i * ytick_step, 2) for i in range(int(ymax / ytick_step) + 1) if i * ytick_step <= ymax + 1e-9]
    ax.set_yticks(yt)
    ax.set_yticklabels([f"{v:.1f}" for v in yt], fontsize=TEXT_PT)
    ax.set_ylabel(ylabel, fontsize=TEXT_PT)
    ax.set_xlabel("时刻（横轴左段为前一日）", fontsize=TEXT_PT)
    ax.tick_params(direction="out", length=2.5, width=0.5, pad=2)
    for s in ax.spines.values():
        s.set_linewidth(0.5)
    y = BRACKET_FRAC * ymax
    tick = 0.025 * ymax
    for label, a, b in WINDOWS:
        ax.plot([a, a, b, b], [y - tick, y, y, y - tick], color="black", linewidth=0.6, zorder=3)
        ax.text((a + b) / 2, y + 0.008 * ymax, label, ha="center", va="center", fontsize=TEXT_PT - 1)
    handles = [Patch(facecolor=BAND_COLOR, edgecolor="#808080", linewidth=0.5, label="作业班次"),
               Line2D([0], [0], color="black", linewidth=0.6, label="补电窗口")]
    ax.legend(handles=handles, loc="upper left", frameon=False, fontsize=TEXT_PT - 1.2,
              handlelength=1.6, borderaxespad=0.4, labelspacing=0.3)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    font_path = _songti_regular()
    font_manager.fontManager.addfont(str(font_path))
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font_path)).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    price, carbon = load_calendar()
    shifts = json.load(open(SHIFT))["shifts"]
    fig, (left, right) = plt.subplots(1, 2, figsize=(6.9, 2.6))
    draw_panel(left, carbon, "电网碳强度\n(kgCO$_2$e/kWh)", 0.9, 0.2, shifts)
    draw_panel(right, price, "分时电价\n(元/kWh)", 1.6, 0.2, shifts)
    left.set_title("(a) 电网碳强度与补电窗口", fontsize=TEXT_PT, y=-0.42)
    right.set_title("(b) 分时电价与补电窗口", fontsize=TEXT_PT, y=-0.42)
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.30, top=0.97, wspace=0.32)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    fig.savefig(args.out.with_suffix(".png"), dpi=200)
    print(f"已写出 {args.out} 与 .png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
