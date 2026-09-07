#!/usr/bin/env python3
"""图：单位碳价对车队构成、碳排量与首趟前补电时刻的作用（4.4.3，2026-09-07）。

用户 2026-09-07 对旧图 6 的意见："信息太小……总的来看就是三个阶梯……没看出翻转"。
旧图画的是方案池最优（严格但只有两级跳，且 6 辆车的算例本就只有两三级台阶），并且没有充电时刻这一层。
本图改画**各碳价档实际求得的方案**（每档 3 次运算的均值），沿用陈婉茹 2023 图 4(a)"车队构成随碳价跳变、标出跳变点"
的推理，不抄其环形皮囊：
  (a) 左格：堆叠柱＝派遣燃油车数（白底黑边）与电动车数（实心黑），折线＝碳排量（右轴）；
  (b) 右格：折线＝首趟出车前补电落在谷段（23:00–07:00）的电量占比（左轴，%），折线＝总成本（右轴，元）。
方案池给出的两个车队翻转碳价（1.24、1.52）在正文引用，不在图上加竖线（用户 2026-09-05 令撤竖虚线）。
数据：solver/reports/carbon_price_sweep_v3_20260906/P=*/run_*/best_solution.json（22 档 × 3 次）。
画风：黑白灰、Songti、通栏宽版心；横轴等距分类刻度只标 0、0.075、0.5、1.0、1.5、2.0。
用法（须用仓库 venv）：.public-hgs-venv/bin/python3 solver/scripts/generate_carbon_price_response_figure.py [--out PDF]
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics as st
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
SWEEP = REPO / "solver/reports/carbon_price_sweep_v3_20260906"
OUT = REPO / "docs/paper_v2/generated_figures/figure_6_carbon_price_response.pdf"
DAY = 86400.0
TEXT_PT = 8.0
_FONT_TMP = tempfile.TemporaryDirectory(prefix="resetp_cp_fig_font_")


def _songti_regular() -> Path:
    source = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    target = Path(_FONT_TMP.name) / "songti_sc_regular.ttf"
    for font in TTCollection(source).fonts:
        names = {r.toUnicode() for r in font["name"].names if r.nameID == 6}
        if "STSongti-SC-Regular" in names:
            font.save(target)
            return target
    raise RuntimeError("Songti SC Regular face not found")


def first_trip_valley_share(sol: dict) -> float:
    first_kwh = 0.0
    valley_kwh = 0.0
    for duty in sol["individual"]["duties"]:
        for c in duty["charging_sessions"]:
            if c["trip_index"] != 1:
                continue
            h = c["charge_start_second"] / 3600.0
            off = c["charge_day_offset"]
            first_kwh += c["energy_kwh"]
            if (off == 0 and h < 7.0) or (off == -1 and h >= 23.0):
                valley_kwh += c["energy_kwh"]
    return valley_kwh / first_kwh if first_kwh > 0 else float("nan")


def load_levels() -> list[dict]:
    levels = []
    for d in sorted(glob.glob(str(SWEEP / "P=*")), key=lambda x: float(x.split("P=")[1])):
        price = float(d.split("P=")[1])
        runs = []
        for p in sorted(glob.glob(d + "/run_*/best_solution.json")):
            sol = json.load(open(p))
            b = sol["evaluation"]["breakdown"]
            runs.append(dict(ev=b["n_veh_ev"], cv=b["n_veh_cv"], E=b["E_total"], cost=b["total_cost"],
                             valley=first_trip_valley_share(sol)))
        if not runs:
            continue
        levels.append(dict(price=price, n=len(runs),
                           ev=st.mean(r["ev"] for r in runs), cv=st.mean(r["cv"] for r in runs),
                           E=st.mean(r["E"] for r in runs), cost=st.mean(r["cost"] for r in runs),
                           valley=100 * st.mean(r["valley"] for r in runs)))
    return levels


def tick_label(price: float) -> str:
    if abs(price - 0.07502) < 1e-6:
        return "\n0.075"
    if price in (0.0, 0.5, 1.0, 1.5, 2.0):
        return f"{price:g}"
    return ""


def style_axes(ax):
    ax.tick_params(direction="out", length=2.5, width=0.5, pad=2, labelsize=TEXT_PT)
    for s in ax.spines.values():
        s.set_linewidth(0.5)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    font_path = _songti_regular()
    font_manager.fontManager.addfont(str(font_path))
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font_path)).get_name()
    plt.rcParams["axes.unicode_minus"] = False

    levels = load_levels()
    xs = list(range(len(levels)))
    labels = [tick_label(l["price"]) for l in levels]
    for l in levels:
        print(f"P={l['price']:<7} n={l['n']} 电动车 {l['ev']:.2f} 燃油车 {l['cv']:.2f} 排放 {l['E']:.1f} 成本 {l['cost']:.1f} 首趟前谷段占比 {l['valley']:.0f}%")

    fig, (left, right) = plt.subplots(1, 2, figsize=(6.9, 2.7))
    # (a) 车队构成堆叠柱 + 碳排量
    cv = [l["cv"] for l in levels]
    ev = [l["ev"] for l in levels]
    left.bar(xs, ev, width=0.7, facecolor="black", edgecolor="none", label="电动车", zorder=2)
    left.bar(xs, cv, width=0.7, bottom=ev, facecolor="white", edgecolor="black", linewidth=0.5, label="燃油车", zorder=2)
    left.set_ylim(0, 8)
    left.set_yticks(range(0, 9, 2))
    left.set_ylabel("派遣车辆数（辆）", fontsize=TEXT_PT)
    left.set_xticks(xs)
    left.set_xticklabels(labels)
    left.set_xlabel("单位碳价（元/kgCO$_2$e）", fontsize=TEXT_PT)
    style_axes(left)
    em = left.twinx()
    em.plot(xs, [l["E"] for l in levels], color="black", linewidth=0.8, marker="o", markersize=2.5,
            markerfacecolor="white", markeredgewidth=0.6, zorder=3, label="碳排量")
    em.set_ylim(0, 300)
    em.set_yticks(range(0, 301, 50))
    em.set_ylabel("碳排量（kgCO$_2$e）", fontsize=TEXT_PT)
    style_axes(em)
    handles = [Patch(facecolor="black", label="电动车"), Patch(facecolor="white", edgecolor="black", linewidth=0.5, label="燃油车"),
               Line2D([0], [0], color="black", linewidth=0.8, marker="o", markersize=2.5, markerfacecolor="white", label="碳排量")]
    em.legend(handles=handles, loc="upper right", frameon=False, fontsize=TEXT_PT - 1.2, handlelength=1.6, labelspacing=0.3, borderaxespad=0.4)
    # (b) 只画一条线：首趟出车前补电落在谷段的电量占比（用户 2026-09-07："b 图连图例都没有，不知道怎么看"→ 去掉总成本线，单量单轴，不需要图例）
    right.plot(xs, [l["valley"] for l in levels], color="black", linewidth=0.8, marker="s", markersize=2.5,
               markerfacecolor="black", zorder=3)
    right.set_ylim(0, 110)
    right.set_yticks(range(0, 101, 20))
    right.set_ylabel("首趟前补电落在谷段的电量占比（%）", fontsize=TEXT_PT)
    right.set_xticks(xs)
    right.set_xticklabels(labels)
    right.set_xlabel("单位碳价（元/kgCO$_2$e）", fontsize=TEXT_PT)
    style_axes(right)
    left.set_title("(a) 车队构成与碳排量", fontsize=TEXT_PT, y=-0.40)
    right.set_title("(b) 首趟前补电落在谷段的电量占比", fontsize=TEXT_PT, y=-0.40)
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.29, top=0.97, wspace=0.45)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    fig.savefig(args.out.with_suffix(".png"), dpi=200)
    print(f"已写出 {args.out} 与 .png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
