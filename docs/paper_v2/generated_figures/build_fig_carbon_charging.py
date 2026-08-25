# -*- coding: utf-8 -*-
"""Plot the input signals and current three-seed carbon-aware outcomes."""
import csv
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pubstyle import CN, CNs, TICK, RULE_HEAVY, RULE_LIGHT, MONEY, CARBON

HERE = Path(__file__).resolve().parent
REPORTS = HERE.parents[2] / "solver/reports/submission_fallback_20260824"
DATA_REPO = Path("/Volumes/移动硬盘（512G）/ReSETP")
CALENDAR = DATA_REPO / (
    "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/"
    "tariff_carbon_hourly_calendar.csv"
)

with CALENDAR.open(encoding="utf-8") as handle:
    hourly = [
        row for row in csv.DictReader(handle)
        if row["city"] == "beijing"
        and row["date"] == "2025-02-12"
        and int(row["minute_of_day"]) % 60 == 0
    ]
hs = np.arange(25)
carbon = np.array([float(row["carbon_factor_kgco2e_per_kwh"]) for row in hourly])
price = np.array([float(row["depot_energy_cny_per_kwh"]) for row in hourly])

packages = (
    "23_carbon_asap_cv7_ev13_seed1",
    "28_carbon_asap_cv7_ev13_seeds2_11",
    "27_carbon_aware_cv7_ev13_seeds1_2_11",
)
result_rows = []
for package in packages:
    with (REPORTS / package / "raw_runs.csv").open(encoding="utf-8") as handle:
        result_rows.extend(csv.DictReader(handle))

def metric(policy, field):
    return np.array([
        float(row[field]) for row in result_rows
        if row["charge_timing_policy"] == policy
    ])

asap_cost = metric("asap", "total_cost_cny")
aware_cost = metric("cost_plus_carbon", "total_cost_cny")
asap_emissions = metric("asap", "total_emissions_kg")
aware_emissions = metric("cost_plus_carbon", "total_emissions_kg")

fig = plt.figure(figsize=(5.8, 5.2))
axa = fig.add_axes([0.135, 0.64, 0.73, 0.245])
axb = fig.add_axes([0.12, 0.17, 0.34, 0.31])
axc = fig.add_axes([0.59, 0.17, 0.34, 0.31])

axa.step(hs, np.r_[price, price[-1]], where="post", color=MONEY,
         ls="--", lw=RULE_HEAVY)
axa.set_ylabel("电价（元/kWh）", fontproperties=CN, color=MONEY)
axa.set_xlim(-0.8, 24.5)
axa.set_xticks((0, 4, 8, 12, 16, 20, 24))
axa.set_ylim(0.45, 1.34)
axa.tick_params(labelbottom=False, labelsize=TICK)
a2 = axa.twinx()
a2.step(hs, np.r_[carbon, carbon[-1]], where="post", color=CARBON,
        lw=RULE_HEAVY)
a2.set_ylabel("碳强度（kgCO$_2$e/kWh）", fontproperties=CN, color=CARBON)
a2.set_ylim(0.10, 0.80)
a2.tick_params(labelsize=TICK)
axa.text(0.5, 1.13, "(a) 分时电价与时变碳强度输入",
         fontproperties=CN, transform=axa.transAxes, ha="center")

def paired_panel(ax, left, right, ylabel, title, annotation):
    means = (left.mean(), right.mean())
    ax.bar((0, 1), means, color=(MONEY, CARBON), width=0.62)
    for idx, values in enumerate((left, right)):
        offsets = np.linspace(-0.10, 0.10, len(values))
        ax.scatter(idx + offsets, values, s=18, facecolors="white",
                   edgecolors="#333333", linewidths=RULE_LIGHT, zorder=3)
    ax.set_xticks((0, 1), ("有空即充", "碳感知"), fontproperties=CNs)
    ax.set_ylabel(ylabel, fontproperties=CN)
    ax.set_title(title, fontproperties=CN, pad=8)
    ax.text(0.5, 0.92, annotation, transform=ax.transAxes,
            fontproperties=CNs, ha="center")
    ax.tick_params(labelsize=TICK)

paired_panel(axb, asap_cost, aware_cost, "单目标总账（元）",
             "(b) 完整重新优化成本", "均值 -3.50%")
paired_panel(axc, asap_emissions, aware_emissions, "总排放（kgCO$_2$e）",
             "(c) 完整重新优化排放", "均值 -19.72%")
for ax in (axa, a2, axb, axc):
    for spine in ax.spines.values():
        spine.set_linewidth(RULE_LIGHT)

out = HERE / "figure_3_carbon_tariff_charging.pdf"
fig.savefig(out, format="pdf", facecolor="white")
print("written:", out)
