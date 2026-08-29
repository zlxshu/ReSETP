# -*- coding: utf-8 -*-
"""Plot the three saved formal trajectories against actual wall-clock time."""
import csv
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pubstyle import CN, CNs, TICK, RULE_HEAVY, RULE_LIGHT


HERE = Path(__file__).resolve().parent
RUN_ROOT = (
    HERE.parents[2]
    / "solver/reports/paper_submission_preview_20260828/representative_full"
)
SEEDS = (1, 2, 11)
LINE_STYLES = ("-", "--", "-.")
MARKERS = ("o", "s", "^")


def read_trace(seed: int) -> tuple[list[float], list[float]]:
    path = RUN_ROOT / f"seed_{seed}" / "convergence.csv"
    points: list[tuple[float, float]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["has_feasible"] != "True":
                continue
            points.append(
                (float(row["wall_seconds"]), float(row["best_feasible_raw_cost"]))
            )
    if not points:
        raise ValueError(f"no feasible convergence rows: {path}")
    points.sort()
    return [point[0] for point in points], [point[1] for point in points]


fig = plt.figure(figsize=(5.4, 3.15))
ax = fig.add_axes([0.16, 0.22, 0.79, 0.67])

for seed, linestyle, marker in zip(SEEDS, LINE_STYLES, MARKERS):
    wall_seconds, incumbents = read_trace(seed)
    ax.step(
        wall_seconds,
        incumbents,
        where="post",
        color="black",
        linestyle=linestyle,
        linewidth=RULE_HEAVY,
        marker=marker,
        markersize=3.4,
        markerfacecolor="white",
        markeredgecolor="black",
        label=f"种子 {seed}",
    )

ax.set_xlabel("实际运行时间（s）", fontproperties=CN)
ax.set_ylabel("当前最好可行目标值（元）", fontproperties=CN)
ax.set_xlim(left=0.0, right=610.0)
ax.tick_params(labelsize=TICK)
ax.legend(prop=CNs, frameon=False, loc="lower left")
for spine in ax.spines.values():
    spine.set_linewidth(RULE_LIGHT)

out = HERE / "figure_2_algorithm_convergence_preview.pdf"
fig.savefig(out, format="pdf", facecolor="white")
print("written:", out)
