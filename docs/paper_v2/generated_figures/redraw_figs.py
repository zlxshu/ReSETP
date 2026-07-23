#!/usr/bin/env python3
"""Redraw figure3 and figure4 in the final Chinese presentation style.

Pure presentation from sealed CSVs; no data change, no optimization.
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({
    # Journal contract: English letters/digits use Times New Roman, while
    # Chinese glyphs fall back to Songti SC.
    "font.family": ["Times New Roman", "Songti SC"],
    "font.size": 9,
    "mathtext.fontset": "custom",
    "mathtext.rm": "Times New Roman",
    "mathtext.it": "Times New Roman:italic",
    "mathtext.bf": "Times New Roman:bold",
    # Publisher-safe embedded TrueType outlines; avoid Matplotlib Type-3 text.
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "axes.linewidth": 0.6,
    "lines.linewidth": 0.9,
    "xtick.direction": "in",
    "ytick.direction": "in",
})

ROOT = Path("/Volumes/移动硬盘（512G）/ReSETP")
ART = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts"
OUT = Path(__file__).parent

ALGOS = ["HGS-F", "HGS-E", "HGS-M", "MV-HGS-SP"]
STYLES = {
    # Chen et al. (2025), Fig. 4 shell: thin colour lines with distinct
    # line styles and the proposed method in red dash-dot.
    "HGS-F": dict(color="#7b2cbf", linestyle="-"),
    "HGS-E": dict(color="#2ca02c", linestyle="--"),
    # A darker blue and a deliberately coarse round-dot pattern keep HGS-M
    # distinct from the proposed method's dash-dot line in monochrome print.
    # The pattern is coarser and thicker than Matplotlib's default dotted line
    # so it remains visible at final journal size.
    "HGS-M": dict(color="#0057a6", linestyle=(0, (1.1, 1.55)),
                  dash_capstyle="round"),
    "MV-HGS-SP": dict(color="#d62728", linestyle="-."),
}

# ---------- Figure 4: incumbent trajectory on sealed wall-clock time ----------
curves = defaultdict(list)
with (ART / "figure4_convergence_v4.csv").open() as f:
    for r in csv.DictReader(f):
        if r["selected_for_figure4"] != "True":
            continue
        curves[r["algorithm_label"]].append(
            (float(r["elapsed_minutes"]), float(r["cost_cny"]))
        )
for k in curves:
    curves[k].sort()

# extend each curve to its own true run-end time (CPU from sealed table6 csv)
sel_seed = {}
with (ART / "figure4_convergence_v4.csv").open() as f:
    for r in csv.DictReader(f):
        if r["selected_for_figure4"] == "True":
            sel_seed[r["algorithm_label"]] = r["seed"]
cpu_end = {}
with (ART / "table6_representative_v4.csv").open() as f:
    for r in csv.DictReader(f):
        for name in ALGOS:
            if r["seed"] == sel_seed[name]:
                cpu_end[name] = float(r[f"{name}_cpu_minutes"])
for name in ALGOS:
    last_cost = curves[name][-1][1]
    curves[name].append((cpu_end[name], last_cost))

fig, ax = plt.subplots(figsize=(4.30, 2.80))
fig.subplots_adjust(left=0.14, right=0.98, bottom=0.18, top=0.98)
xmax_data = max(p[0] for pts in curves.values() for p in pts)
xmax = xmax_data * 1.08
for name in ALGOS:
    pts = curves[name]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    style = dict(STYLES[name])
    if name == "MV-HGS-SP":
        style.update(linewidth=1.00, alpha=1.0, zorder=5)
    elif name == "HGS-M":
        style.update(linewidth=1.02, alpha=1.0, zorder=4)
    else:
        style.update(linewidth=0.78, alpha=0.96, zorder=3)
    # Chen et al. (2025, Fig. 4) joins recorded incumbent observations with
    # thin lines.  We follow that shell while retaining the sealed timestamps
    # and costs exactly; no smoothing or interpolation points are introduced.
    ax.plot(xs, ys, label=name, **style)

# Leave a small optical margin before time zero, as in the Chen et al. shell,
# without changing any timestamp, tick value, or result.
xpad = xmax_data * 0.025
tick_step = 0.1 if xmax <= 0.8 else 0.2
tick_stop = math.floor(xmax / tick_step) * tick_step
ax.set_xticks([i * tick_step for i in range(round(tick_stop / tick_step) + 1)])
ax.set_xlim(-xpad, xmax)
ax.set_ylim(2345, 2620)
ax.set_yticks([2350, 2400, 2450, 2500, 2550, 2600])
ax.set_xlabel("时间(min)")
ax.set_ylabel("成本(元)")
ax.grid(False)
ax.legend(loc="upper right", fontsize=6.9, frameon=False,
          handlelength=2.25, handletextpad=0.55, labelspacing=0.28,
          borderaxespad=0.55)

fig.savefig(OUT / "figure4_convergence_v12.pdf", bbox_inches="tight", pad_inches=0.02)
fig.savefig(OUT / "figure4_convergence_v12.png", dpi=300, bbox_inches="tight", pad_inches=0.02)
plt.close(fig)

# ---------- Figure 3: carbon intensity, urban-agglomeration legend ----------
REGION_LABEL = {
    "Beijing": "京津冀",
    "Guangdong": "珠三角",
    "Chongqing": "成渝",
}
R_STYLE = {
    "Beijing": dict(color="#1f77b4", linestyle="-"),
    "Guangdong": dict(color="#d62728", linestyle="--"),
    "Chongqing": dict(color="#2ca02c", linestyle=":"),
}
series = defaultdict(list)
with (ART / "figure3_carbon_profile_v4.csv").open() as f:
    for r in csv.DictReader(f):
        series[r["region"]].append(
            (float(r["time_hour"]), float(r["carbon_intensity_gCO2_per_kWh"]))
        )
fig, ax = plt.subplots(figsize=(4.30, 2.80))
fig.subplots_adjust(left=0.14, right=0.98, bottom=0.18, top=0.98)
for reg in ["Beijing", "Guangdong", "Chongqing"]:
    pts = sorted(series[reg])
    ax.plot([p[0] for p in pts], [p[1] for p in pts],
            label=REGION_LABEL[reg], **R_STYLE[reg])
ax.set_xlim(0, 24)
ax.set_xticks(range(0, 25, 4))
all_y = [value for pts in series.values() for _, value in pts]
ax.set_ylim(0, max(all_y) * 1.05)
ax.set_xlabel("时刻(h)")
ax.set_ylabel("碳强度(g CO₂/kWh)")
ax.grid(False)
ax.legend(loc="lower left", fontsize=6.9, frameon=False,
          handlelength=2.15, handletextpad=0.55, labelspacing=0.28,
          borderaxespad=0.55)
fig.savefig(OUT / "figure3_carbon_profile_v12.pdf", bbox_inches="tight", pad_inches=0.02)
fig.savefig(OUT / "figure3_carbon_profile_v12.png", dpi=300, bbox_inches="tight", pad_inches=0.02)
plt.close(fig)
print("done: v12 figures written")
