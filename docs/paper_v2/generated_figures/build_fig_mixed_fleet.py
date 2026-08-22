# -*- coding: utf-8 -*-
"""图4 不同碳价下混合车队的车型构成——不同碳价情景下的车型构成。
现状：仓库内没有"不同碳价下重新优化后实际派遣车型数量"的扫描结果。
本图台阶位置取自固定职责逐车换型成本交点 0.296/1.706/1.969 元/kg（真实计算，非本图口径），
曲线本身为示意，待正式扫描实验回填后替换。横轴上限 2.1 与表9 碳价扫描最高点一致。
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pubstyle import CN, CNs, TICK, RULE_HEAVY, RULE_LIGHT, MONEY, CARBON, GREY, DARK

HERE = os.path.dirname(os.path.abspath(__file__))
SONG = "/System/Library/Fonts/Supplemental/Songti.ttc"





FLIPS = [0.296, 1.706, 1.969]          # 固定职责换型成本交点（真实计算）
NOW   = 0.075                          # 现行碳价
TOTAL = 9                              # 代表解实体车总数
XMAX  = 2.1

# 示意台阶：现行价下全为燃油车，交点处逐辆翻转
edges = [0.0] + FLIPS + [XMAX]
ev    = [0, 1, 2, 3]                   # 每段的电动车数（示意）
cv    = [TOTAL - e for e in ev]

fig = plt.figure(figsize=(5.8, 3.6))
ax  = fig.add_axes([0.135, 0.275, 0.73, 0.520])

def stair(vals, color, ls, label):
    xs, ys = [], []
    for i, v in enumerate(vals):
        xs += [edges[i], edges[i+1]]; ys += [v, v]
    ax.plot(xs, ys, color=color, ls=ls, lw=RULE_HEAVY, label=label, solid_capstyle="butt")
    for i in range(1, len(vals)):
        ax.plot([edges[i], edges[i]], [vals[i-1], vals[i]], color=color, ls=ls, lw=RULE_HEAVY, alpha=.55)

stair(cv, MONEY, "--", "燃油车")
stair(ev, CARBON, "-",  "电动车")

for f in FLIPS:
    ax.axvline(f, color=GREY, lw=.8, ls=(0, (4, 3)), zorder=0)
    ax.text(f, TOTAL + 0.40, f"{f:g}", fontproperties=CNs, color=GREY, ha="center")
ax.axvline(NOW, color="#555555", lw=RULE_HEAVY)
ax.text(NOW + 0.05, 5.0, "现行碳价 0.075", fontproperties=CNs, color="#555555", rotation=90, va="center")

ax.set_xlim(0, XMAX); ax.set_ylim(0, TOTAL + 1.1)
ax.set_yticks(range(0, TOTAL + 1, 3))
ax.set_xlabel("单位碳价（元/kgCO$_2$e）", fontproperties=CN, labelpad=2)
ax.set_ylabel("车辆数（辆）", fontproperties=CN)
ax.tick_params(labelsize=TICK)
ax.text(0.5, 1.10, "现行碳价下车队仍为全燃油；碳价抬升后电动车逐辆进入",
        fontproperties=CN, transform=ax.transAxes, ha="center")
lg = ax.legend(prop=CNs, loc="center left", bbox_to_anchor=(0.30, 0.50), framealpha=1,
               edgecolor="#CCCCCC", borderpad=.4)
lg.get_frame().set_linewidth(RULE_LIGHT)
for sp in ax.spines.values(): sp.set_linewidth(RULE_LIGHT)



out = os.path.join(HERE, "figure_4_mixed_fleet.pdf")
fig.savefig(out, format="pdf", facecolor="white"); print("written:", out)
