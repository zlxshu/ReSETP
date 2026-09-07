#!/usr/bin/env python3
"""Summarise the carbon-price and fleet-mix trial batch (scheme A3).

Prints, per axis level, the best run's cost components (启动/行驶/充电/油耗/碳),
emissions, fleet and total, plus mean/worst totals over runs and wall time.
Usage: python3 solver/scripts/summarize_private_axes.py [BATCH_DIR]
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BATCH = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "solver/reports/private_axes_trial_20260903"


def _find(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = _find(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find(value, key)
            if found is not None:
                return found
    return None


def _level_key(name: str):
    try:
        return (0, float(name))
    except ValueError:
        return (1, name)


for axis in ("carbon", "mix"):
    axis_dir = BATCH / axis
    if not axis_dir.exists():
        continue
    print(f"== {axis}")
    for level_dir in sorted((d for d in axis_dir.iterdir() if d.is_dir()), key=lambda d: _level_key(d.name)):
        runs = []
        for run_dir in sorted(level_dir.glob("run_*/")):
            raw = run_dir / "raw_runs.csv"
            if not raw.exists():
                continue
            record = next(iter(csv.DictReader(raw.open(encoding="utf-8"))))
            breakdown = _find(json.load((run_dir / "best_solution.json").open()), "breakdown")
            runs.append((float(record["best_cost"]), breakdown, float(record["run_wall_seconds"]) / 60, record["verdict"], record["customers_served"]))
        if not runs:
            print(f"  {level_dir.name}: (no finished run)")
            continue
        best = min(runs, key=lambda item: item[0])
        b = best[1]
        totals = [item[0] for item in runs]
        print(
            f"  {level_dir.name}: n={len(runs)} best={best[0]:.2f} mean={statistics.mean(totals):.2f} worst={max(totals):.2f} "
            f"| EV={b['n_veh_ev']} CV={b['n_veh_cv']} 启动={b['cost_fix']:.2f} 行驶={b['cost_km']:.2f} 充电={b['cost_elec']:.2f} "
            f"油耗={b['cost_fuel']:.2f} 碳={b['cost_carbon']:.2f} 排放={b['E_total']:.2f} | wall={statistics.mean(r[2] for r in runs):.1f}min "
            f"verdicts={sorted({r[3] for r in runs})} served={sorted({r[4] for r in runs})}"
        )
