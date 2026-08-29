# -*- coding: utf-8 -*-
"""Plot one honest best-feasible trajectory from the saved private-instance run."""
import csv
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pubstyle import CN, CNs, TICK, RULE_HEAVY, RULE_LIGHT, DARK

HERE = Path(__file__).resolve().parent
TRACE = HERE.parents[2] / (
    "solver/reports/submission_fallback_20260824/"
    "04_private_ablation_trajectory_seed1/convergence.csv"
)

points = []
with TRACE.open(encoding="utf-8") as handle:
    for row in csv.DictReader(handle):
        if row["arm"] != "A2":
            continue
        for cost_key, violation_key in (
            ("before_cost", "before_violations"),
            ("after_cost", "after_violations"),
        ):
            if row[cost_key] and row[violation_key] and int(float(row[violation_key])) == 0:
                points.append((int(row["iteration"]), float(row[cost_key])))

points.sort()
iterations = np.array([item[0] for item in points], dtype=int)
incumbents = np.minimum.accumulate([item[1] for item in points])

# Retain only genuine incumbent changes plus the endpoints.  This keeps the
# vector PDF compact without interpolating or inventing intermediate values.
keep = np.r_[True, np.diff(incumbents) != 0]
keep[-1] = True
x = iterations[keep]
y = incumbents[keep]

fig = plt.figure(figsize=(5.4, 3.15))
ax = fig.add_axes([0.16, 0.22, 0.79, 0.67])
ax.step(x, y, where="post", color="black", lw=RULE_HEAVY,
        marker="o", markersize=3.5, markerfacecolor="white",
        markeredgecolor="black")
ax.set_xlabel("迭代次数", fontproperties=CN)
ax.set_ylabel("当前最好可行目标值（元）", fontproperties=CN)
ax.tick_params(labelsize=TICK)
margin = max(1.0, abs(float(y[0])) * 0.0005)
ax.set_ylim(float(y.min()) - margin, float(y.max()) + margin)
ax.text(0.5, 0.88, f"本次运行最好值 {y[-1]:.3f} 元",
        transform=ax.transAxes, ha="center", fontproperties=CNs,
        color=DARK)
for spine in ax.spines.values():
    spine.set_linewidth(RULE_LIGHT)

out = HERE / "figure_2_algorithm_convergence.pdf"
fig.savefig(out, format="pdf", facecolor="white")
print("written:", out)
