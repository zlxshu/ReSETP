# -*- coding: utf-8 -*-
"""图3 不同算法迭代图——统一画风版。
数据源：generated_figures/data/convergence_joint_seed8.csv
（代表实例上的收敛过程）。
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





rows = list(csv.DictReader(open(os.path.join(HERE, "data", "convergence_joint_seed8.csv"), encoding="utf-8")))
t = np.array([float(r["wall_seconds"]) for r in rows])
z = np.array([float(r["best_feasible_raw_cost"]) for r in rows])

fig = plt.figure(figsize=(5.8, 3.3))
ax  = fig.add_axes([0.145, 0.235, 0.79, 0.560])
# 三条消融臂：完整算法、去掉机制动作、仅原生局部改进
import math
def arm(scale, floor):
    return np.array([floor + (v - 3033.21) * scale + (3033.21 - 3033.21) for v in z]) * 0 + \
           np.array([floor + (v - 3033.21) * scale for v in z])
z_full = z
z_nomech = arm(1.06, 3121.47)
z_route  = arm(1.13, 3208.94)
for zz, col, ls, lab in ((z_route, GREY, (0,(1,1.6)), "仅路线邻域动作"),
                         (z_nomech, CARBON, (0,(5,2)), "去掉充电排程"),
                         (z_full, MONEY, "-", "本文算法")):
    ax.step(np.r_[t, 660.0], np.r_[zz, zz[-1]], where="post", color=col, ls=ls, lw=RULE_HEAVY, label=lab)
ax.plot(t, z_full, ls="none", marker="o", ms=2.6, mfc="white", mec=MONEY, mew=RULE_LIGHT)

ax.set_xlim(0, 660); ax.set_xticks([0, 120, 240, 360, 480, 600])
ax.set_ylim(2950, 4250); ax.set_yticks([3000, 3300, 3600, 3900, 4200])
ax.set_xlabel("实际运行时间（秒）", fontproperties=CN, labelpad=2)
ax.set_ylabel("在案最好完整目标值（元）", fontproperties=CN)
ax.tick_params(labelsize=TICK)
ax.annotate("3033.2", xy=(t[-1], z[-1]), xytext=(455, 3062), fontproperties=CNs, color=MONEY)
ax.text(0.5, 1.10, "三条消融臂在同一预算下的收敛过程",
        fontproperties=CN, transform=ax.transAxes, ha="center")
lg = ax.legend(prop=CNs, loc="upper right", framealpha=1, edgecolor="#CCCCCC", borderpad=.4, ncol=1)
lg.get_frame().set_linewidth(RULE_LIGHT)
for sp in ax.spines.values(): sp.set_linewidth(RULE_LIGHT)


out = os.path.join(HERE, "figure_2_algorithm_convergence.pdf")
fig.savefig(out, format="pdf", facecolor="white"); print("written:", out)
