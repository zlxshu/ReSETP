#!/usr/bin/env python3
"""Redraw figure3 (carbon) and figure4 (convergence, broken axis) in Chinese.

Pure presentation from sealed CSVs; no data change, no optimization.
"""
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({
    "font.family": ["Songti SC", "Times New Roman"],
    "font.size": 9,
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
    "HGS-F": dict(color="#1f77b4", linestyle="-"),
    "HGS-E": dict(color="#d62728", linestyle="--"),
    "HGS-M": dict(color="#2ca02c", linestyle=":"),
    "MV-HGS-SP": dict(color="#9467bd", linestyle="-."),
}

# ---------- Figure 4: broken-axis convergence ----------
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

fig = plt.figure(figsize=(4.6, 3.2))
gs = fig.add_gridspec(2, 1, height_ratios=[1, 4], hspace=0.06)
ax_top = fig.add_subplot(gs[0])
ax_bot = fig.add_subplot(gs[1], sharex=ax_top)

for name in ALGOS:
    pts = curves[name]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    # extend each curve horizontally to its own end (step-post best-so-far)
    for ax in (ax_top, ax_bot):
        ax.step(xs, ys, where="post", label=name, **STYLES[name])

ax_top.set_ylim(2510, 2620)
ax_top.set_yticks([2550, 2600])
ax_bot.set_ylim(2345, 2500)
ax_bot.set_yticks([2350, 2400, 2450, 2500])
xmax = max(p[0] for pts in curves.values() for p in pts) * 1.04
for ax in (ax_top, ax_bot):
    ax.set_xlim(0, xmax)
    ax.grid(False)

# broken-axis cosmetics
ax_top.spines["bottom"].set_visible(False)
ax_bot.spines["top"].set_visible(False)
ax_top.tick_params(labelbottom=False, bottom=False)
d = 0.012
kw = dict(transform=ax_top.transAxes, color="k", clip_on=False, linewidth=0.6)
ax_top.plot((-d, +d), (-d * 4, +d * 4), **kw)
ax_top.plot((1 - d, 1 + d), (-d * 4, +d * 4), **kw)
kw = dict(transform=ax_bot.transAxes, color="k", clip_on=False, linewidth=0.6)
ax_bot.plot((-d, +d), (1 - d, 1 + d), **kw)
ax_bot.plot((1 - d, 1 + d), (1 - d, 1 + d), **kw)

ax_bot.legend(loc="upper right", fontsize=8, frameon=True, edgecolor="0.4",
              handlelength=2.4)
ax_bot.set_xlabel("时间(min)")
fig.supylabel("成本(元)", fontsize=9, x=0.02)
fig.savefig(OUT / "figure4_convergence_v5.pdf", bbox_inches="tight")
fig.savefig(OUT / "figure4_convergence_v5.png", dpi=300, bbox_inches="tight")
plt.close(fig)

# ---------- Figure 3: carbon intensity, urban-agglomeration legend ----------
REGION_LABEL = {
    "Beijing": "京津冀(北京电网)",
    "Guangdong": "珠三角(广东电网)",
    "Chongqing": "成渝(重庆电网)",
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
fig, ax = plt.subplots(figsize=(4.6, 2.9))
for reg in ["Beijing", "Guangdong", "Chongqing"]:
    pts = sorted(series[reg])
    ax.plot([p[0] for p in pts], [p[1] for p in pts],
            label=REGION_LABEL[reg], **R_STYLE[reg])
ax.set_xlim(0, 24)
ax.set_xticks(range(0, 25, 4))
ax.set_xlabel("时刻(h)")
ax.set_ylabel("碳强度(gCO$_2$/kWh)")
ax.grid(False)
ax.legend(loc="upper right", fontsize=8, frameon=True, edgecolor="0.4")
fig.savefig(OUT / "figure3_carbon_profile_v5.pdf", bbox_inches="tight")
fig.savefig(OUT / "figure3_carbon_profile_v5.png", dpi=300, bbox_inches="tight")
plt.close(fig)
print("done: v5 figures written")
