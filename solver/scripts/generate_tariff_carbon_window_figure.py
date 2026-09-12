#!/usr/bin/env python3
"""分时电价、电网碳强度与作业班次的时段关系。

灰带表示作业班次。
实际可充电时段由车辆返回及下一行程出发时刻确定，起止结果在正文说明。
数据：日历 beijing 2025-02-12；班次 shift_contract.json。曲线与原图一致。
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
from matplotlib.patches import Patch

REPO = Path(__file__).resolve().parents[2]
CAL = REPO / "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv"
SHIFT = REPO / "data/ChinaInstances/china81_final_suite_v2_20260815/instances/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/shift_contract.json"
OUT = REPO / "docs/paper_v2/generated_figures/figure_4_tariff_carbon_windows.pdf"
FONT_DIR = Path("/Applications/Microsoft Word.app/Contents/Resources/DFonts")

X0, X1 = -12.0, 24.0  # 横轴：前一日 12:00 → 当日 24:00（小时，负数为前一日）
BAND_TOP_FRAC = 0.72
# 源图按约 0.945 倍缩放到版心，8.5 pt 落版后约为 8 pt，
# 统一为比 9 pt 图题小一号的图内字号。
TEXT_PT = 8.5
BAND_COLOR = "#EFEFEF"
_FONT_TMP = tempfile.TemporaryDirectory(prefix="resetp_window_fig_font_")


def _simsun_regular() -> Path:
    source = FONT_DIR / "Simsun.ttc"
    target = Path(_FONT_TMP.name) / "simsun_regular.ttf"
    for font in TTCollection(source).fonts:
        names = {r.toUnicode() for r in font["name"].names if r.nameID == 6}
        if "SimSun" in names:
            font.save(target)
            return target
    raise RuntimeError("SimSun face not found")


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
                ax.axvspan(max(a, X0), min(b, X1), ymin=0, ymax=BAND_TOP_FRAC, color=BAND_COLOR, linewidth=0, zorder=0)
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
    handles = [
        Patch(facecolor=BAND_COLOR, edgecolor="#808080", linewidth=0.5, label="作业班次"),
    ]
    ax.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(0.008, 0.992),
        ncol=1,
        frameon=False,
        fontsize=TEXT_PT,
        handlelength=1.0,
        handletextpad=0.3,
        labelspacing=0.08,
        borderpad=0.0,
        borderaxespad=0.0,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    font_path = _simsun_regular()
    font_manager.fontManager.addfont(str(font_path))
    cn_name = font_manager.FontProperties(fname=str(font_path)).get_name()
    math_rm = font_manager.FontProperties(fname=FONT_DIR / "times.ttf").get_fontconfig_pattern()
    math_it = font_manager.FontProperties(fname=FONT_DIR / "timesi.ttf").get_fontconfig_pattern()
    math_bf = font_manager.FontProperties(fname=FONT_DIR / "timesbd.ttf").get_fontconfig_pattern()
    plt.rcParams.update(
        {
            "font.family": ["Times New Roman", cn_name],
            "font.size": TEXT_PT,
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
            "mathtext.fontset": "custom",
            "mathtext.rm": math_rm,
            "mathtext.it": math_it,
            "mathtext.bf": math_bf,
        }
    )
    price, carbon = load_calendar()
    shifts = json.load(open(SHIFT))["shifts"]
    fig, (left, right) = plt.subplots(1, 2, figsize=(6.9, 1.8))
    draw_panel(left, carbon, "电网碳强度\n(kgCO$_2$/kWh)", 0.9, 0.2, shifts)
    draw_panel(right, price, "分时电价\n(元/kWh)", 1.6, 0.2, shifts)
    left.set_title("(a) 电网碳强度", fontsize=TEXT_PT, y=-0.63)
    right.set_title("(b) 分时电价", fontsize=TEXT_PT, y=-0.63)
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.38, top=0.97, wspace=0.32)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    fig.savefig(args.out.with_suffix(".png"), dpi=200)
    print(f"已写出 {args.out} 与 .png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
