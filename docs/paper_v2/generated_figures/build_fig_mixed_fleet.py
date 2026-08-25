# -*- coding: utf-8 -*-
"""Plot actual vehicle use in the current three-seed mixed-fleet experiment."""
import csv
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pubstyle import CN, CNs, TICK, RULE_LIGHT, MONEY, CARBON

HERE = Path(__file__).resolve().parent
REPORTS = HERE.parents[2] / "solver/reports/submission_fallback_20260824"
PACKAGES = (
    "29_mixed_fleet_cv18_cv13_seeds1_2_11",
    "30_mixed_fleet_cv7_cv2_seeds1_2_11",
)
ARMS = ("cv18_ev2", "cv13_ev7", "cv7_ev13", "cv2_ev18")
LABELS = ("18CV/2EV", "13CV/7EV", "7CV/13EV", "2CV/18EV")

rows = []
for package in PACKAGES:
    with (REPORTS / package / "raw_runs.csv").open(encoding="utf-8") as handle:
        rows.extend(csv.DictReader(handle))

cv = []
ev = []
for arm in ARMS:
    selected = [row for row in rows if row["arm"] == arm]
    cv.append(np.mean([float(row["used_cv_vehicles"]) for row in selected]))
    ev.append(np.mean([float(row["used_ev_vehicles"]) for row in selected]))

x = np.arange(len(ARMS))
fig = plt.figure(figsize=(5.8, 3.6))
ax = fig.add_axes([0.135, 0.255, 0.80, 0.56])
ax.bar(x, cv, color=MONEY, edgecolor="white", lw=RULE_LIGHT, label="实际燃油车")
ax.bar(x, ev, bottom=cv, color=CARBON, edgecolor="white", lw=RULE_LIGHT,
       label="实际电动车")
for idx, (left, right) in enumerate(zip(cv, ev)):
    ax.text(idx, left / 2, f"{left:.1f}", ha="center", va="center",
            fontproperties=CNs, color="white")
    ax.text(idx, left + right / 2, f"{right:.1f}", ha="center", va="center",
            fontproperties=CNs, color="white")

ax.set_xticks(x, LABELS, fontproperties=CNs)
ax.set_ylim(0, 12.5)
ax.set_ylabel("三种子平均实际派遣（辆）", fontproperties=CN)
ax.set_xlabel("可用燃油车/电动车名额", fontproperties=CN)
ax.tick_params(labelsize=TICK)
ax.text(0.5, 1.10, "不同可用名额下的算法内生车型选择",
        fontproperties=CN, transform=ax.transAxes, ha="center")
legend = ax.legend(prop=CNs, loc="upper left", framealpha=1,
                   edgecolor="#CCCCCC", ncol=2)
legend.get_frame().set_linewidth(RULE_LIGHT)
for spine in ax.spines.values():
    spine.set_linewidth(RULE_LIGHT)

out = HERE / "figure_4_mixed_fleet.pdf"
fig.savefig(out, format="pdf", facecolor="white")
print("written:", out)
