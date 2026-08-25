# -*- coding: utf-8 -*-
"""Plot the three-seed private ablation outcomes from the current formal runs."""
import csv
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pubstyle import CN, CNs, TICK, RULE_HEAVY, RULE_LIGHT, MONEY, CARBON, GREY

HERE = Path(__file__).resolve().parent
REPORTS = HERE.parents[2] / "solver/reports/submission_fallback_20260824"
PACKAGES = (
    "03_private_ablation_formal_seed1",
    "03_private_ablation_formal_seed2",
    "03_private_ablation_formal_seed11",
)
ARMS = ("A0", "A1", "A2")

values = {arm: [] for arm in ARMS}
for package in PACKAGES:
    with (REPORTS / package / "raw_runs.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            values[row["arm"]].append(float(row["total_cost"]))

baseline = np.array(values["A0"])
deltas = {arm: np.array(values[arm]) - baseline for arm in ARMS}
x = np.arange(len(ARMS))

fig = plt.figure(figsize=(5.8, 3.3))
ax = fig.add_axes([0.155, 0.235, 0.78, 0.56])
colors = (GREY, CARBON, MONEY)
for index, seed in enumerate((1, 2, 11)):
    y = np.array([deltas[arm][index] for arm in ARMS])
    ax.plot(x, y, color=colors[index], marker="o", lw=RULE_HEAVY,
            ms=4.0, label=f"种子 {seed}")

ax.axhline(0.0, color="#555555", lw=RULE_LIGHT)
ax.set_xlim(-0.35, 2.35)
ax.set_ylim(-0.10, 0.10)
ax.set_xticks(x, ("A0 路线基线", "A1 结构机制", "A2 完整串行"), fontproperties=CNs)
ax.set_yticks((-0.10, -0.05, 0.00, 0.05, 0.10))
ax.set_ylabel("相对 A0 的目标变化（元）", fontproperties=CN)
ax.tick_params(labelsize=TICK)
ax.text(0.5, 1.10, "三种子消融终值：三条实验臂完全重合",
        fontproperties=CN, transform=ax.transAxes, ha="center")
ax.text(1.0, 0.035, "三臂均为 3033.206 元", fontproperties=CNs,
        ha="center", color="#333333")
legend = ax.legend(prop=CNs, loc="lower center", ncol=3,
                   framealpha=1, edgecolor="#CCCCCC")
legend.get_frame().set_linewidth(RULE_LIGHT)
for spine in ax.spines.values():
    spine.set_linewidth(RULE_LIGHT)

out = HERE / "figure_2_algorithm_convergence.pdf"
fig.savefig(out, format="pdf", facecolor="white")
print("written:", out)
