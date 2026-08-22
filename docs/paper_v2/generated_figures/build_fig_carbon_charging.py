# -*- coding: utf-8 -*-
"""图5 电网碳强度、分时电价与充电时刻——用户 2026-08-20 认可的"第一次改良"形态。
数据源：generated_figures/data/figure3_hourly_source.csv（统一算例逐小时实测）。
出图为矢量 PDF，供 paper_main.tex 直接 \\includegraphics。
"""
import csv, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pubstyle import CN, CNs, TICK, RULE_HEAVY, RULE_LIGHT, MONEY, CARBON, GREY, DARK

HERE = os.path.dirname(os.path.abspath(__file__))
SONG = "/System/Library/Fonts/Supplemental/Songti.ttc"





XL = (-0.8, 24.5)

rows   = list(csv.DictReader(open(os.path.join(HERE, "data", "figure3_hourly_source.csv"), encoding="utf-8")))
h, hs  = np.arange(24), np.arange(25)
carbon = np.array([float(x["碳强度_kgCO2e每kWh"]) for x in rows])
price  = np.array([float(x["场内电价_元每kWh"]) for x in rows])
asap   = np.array([float(x["ASAP充电量_kWh"]) for x in rows])
aware  = np.array([float(x["碳感知充电量_kWh"]) for x in rows])

fig = plt.figure(figsize=(5.8, 5.4))
axa = fig.add_axes([0.135, 0.640, 0.73, 0.245])
axb = fig.add_axes([0.135, 0.215, 0.73, 0.330])

# (a) 两个信号方向相反
axa.axvspan(0, 7, color=MONEY, alpha=0.08); axa.axvspan(23, 24, color=MONEY, alpha=0.08)
axa.step(hs, np.r_[price, price[-1]], where="post", color=MONEY, ls="--", lw=RULE_HEAVY)
axa.set_ylabel("电价（元/kWh）", fontproperties=CN, color=MONEY)
axa.set_xlim(*XL); axa.set_xticks([0, 4, 8, 12, 16, 20, 24])
axa.set_ylim(0.45, 1.34); axa.tick_params(labelbottom=False, labelsize=TICK)
a2 = axa.twinx()
a2.step(hs, np.r_[carbon, carbon[-1]], where="post", color=CARBON, lw=RULE_HEAVY)
a2.set_ylabel("碳强度（kgCO$_2$e/kWh）", fontproperties=CN, color=CARBON)
a2.set_xlim(*XL); a2.set_ylim(0.10, 0.80); a2.tick_params(labelsize=TICK)
axa.text(3.5, 0.50, "谷段电价", fontproperties=CNs, color=MONEY, ha="center")
a2.annotate("碳强度最高 0.644", xy=(1.6, 0.642), xytext=(5.0, 0.745), fontproperties=CNs,
            color=CARBON, arrowprops=dict(arrowstyle="->", color=CARBON, lw=.8))
a2.annotate("最低 0.154", xy=(13.4, 0.158), xytext=(16.5, 0.235), fontproperties=CNs,
            color=CARBON, arrowprops=dict(arrowstyle="->", color=CARBON, lw=.8))
axa.text(0.5, 1.13, "(a)　电价最低的时段恰好碳强度最高，两个信号方向相反",
         fontproperties=CN, transform=axa.transAxes, ha="center")

# (b) 同样的电量，两种规则放在不同时刻；灰线为碳强度参照
b2 = axb.twinx()
b2.step(hs, np.r_[carbon, carbon[-1]], where="post", color=GREY, lw=RULE_HEAVY, zorder=0)
b2.set_ylim(0.05, 1.55); b2.set_yticks([]); b2.set_xlim(*XL)
w = 0.40
axb.bar(h - w/2, asap,  width=w, facecolor="white", edgecolor=MONEY, lw=RULE_HEAVY, hatch="////",
        label="有空即充", zorder=3)
axb.bar(h + w/2, aware, width=w, color=CARBON, alpha=.90, label="碳感知择时", zorder=3)
axb.set_xlim(*XL); axb.set_xticks([0, 4, 8, 12, 16, 20, 24]); axb.set_ylim(0, 178)
axb.tick_params(labelsize=TICK)
axb.set_xlabel("时刻（h）", fontproperties=CN, labelpad=1.5)
axb.set_ylabel("充电量（kWh）", fontproperties=CN)
axb.annotate("", xy=(12.3, 150), xytext=(0.9, 116), zorder=4,
             arrowprops=dict(arrowstyle="-|>", color="#3A3A3A", lw=RULE_HEAVY,
                             connectionstyle="arc3,rad=-0.22"))
axb.text(6.2, 163, "103.9 kWh 由最脏时段移至最干净时段",
         fontproperties=CNs, ha="center", color="#333333", zorder=4)
axb.text(0.5, 1.055, "(b)　同样充 189.3 kWh，两种规则把它放在完全不同的时刻",
         fontproperties=CN, transform=axb.transAxes, ha="center")
lg = axb.legend(prop=CNs, loc="upper right", framealpha=1, edgecolor="#CCCCCC", borderpad=.4)
lg.get_frame().set_linewidth(RULE_LIGHT)

fig.text(0.5, 0.105, "结果：充电排放 89.0 → 30.0 kgCO$_2$e，降 66.4%；电费 +26.5 元",
         fontproperties=CN, ha="center")

for ax in (axa, a2, axb, b2):
    for sp in ax.spines.values():
        sp.set_linewidth(RULE_LIGHT)

out = os.path.join(HERE, "figure_3_carbon_tariff_charging.pdf")
fig.savefig(out, format="pdf", facecolor="white")
print("written:", out)
