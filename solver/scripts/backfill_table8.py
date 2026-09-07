#!/usr/bin/env python3
"""Summarise the Table 8 delivery batch and emit the LaTeX rows.

Reads ``solver/reports/ablation_formal_10x_20260902/<arm>/run_*`` (natural
stop, cold start) and prints, per arm: best / mean / Gap(mean vs best) of the
total cost, mean emissions, the best solution's fleet and emissions, the
charging-energy-weighted grid intensity of the best solution, and the mean
wall time.  Rows are written to ``docs/paper_v2/generated_tables/table8_rows.tex``.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import os
BATCH = ROOT / os.environ.get("TABLE8_BATCH", "solver/reports/ablation_formal_10x_20260902")
OUT = ROOT / "docs/paper_v2/generated_tables/table8_rows.tex"
ARMS = ("M-HGS", "MT-HGS", "MTC-HGS")


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


def main() -> int:
    rows = []
    summary = {}
    for arm in ARMS:
        runs = []
        for run_dir in sorted(BATCH.glob(f"{arm}/run_*/")):
            raw = run_dir / "raw_runs.csv"
            if not raw.exists():
                print(f"{arm}/{run_dir.name}: not finished", file=sys.stderr)
                continue
            record = next(iter(csv.DictReader(raw.open(encoding="utf-8"))))
            if record["verdict"] != "RUN_COMPLETE":
                print(f"{arm}/{run_dir.name}: verdict {record['verdict']}", file=sys.stderr)
                continue
            if record.get("warm_started_from_solution"):
                raise SystemExit(f"{arm}/{run_dir.name} was warm-started; refusing")
            breakdown = _find(json.load((run_dir / "best_solution.json").open()), "breakdown")
            runs.append(
                {
                    "run": run_dir.name,
                    "cost": float(record["best_cost"]),
                    "emissions": float(breakdown["E_total"]),
                    "ev": int(breakdown["n_veh_ev"]),
                    "cv": int(breakdown["n_veh_cv"]),
                    "elec_kwh": float(breakdown["electricity_kwh"]),
                    "ev_indirect": float(breakdown["E_ev_indirect"]),
                    "wall_min": float(record["run_wall_seconds"]) / 60.0,
                    "iterations": int(record["iterations"]),
                    "served": f"{record['customers_served']}/{record['customers_total']}",
                }
            )
        if not runs:
            continue
        best = min(runs, key=lambda item: item["cost"])
        costs = [item["cost"] for item in runs]
        mean_cost = statistics.mean(costs)
        gap = 100.0 * (mean_cost / best["cost"] - 1.0)
        mean_emissions = statistics.mean(item["emissions"] for item in runs)
        intensity = (
            1000.0 * best["ev_indirect"] / best["elec_kwh"] if best["elec_kwh"] > 0 else None
        )
        summary[arm] = dict(
            n=len(runs), best=best, mean_cost=mean_cost, gap=gap,
            mean_emissions=mean_emissions, intensity=intensity,
            mean_wall=statistics.mean(item["wall_min"] for item in runs),
            mean_iterations=statistics.mean(item["iterations"] for item in runs),
            worst=max(costs), served=sorted({item["served"] for item in runs}),
        )
        rows.append(
            f"    {arm} & {best['cost']:.2f} & {mean_cost:.2f} & {gap:.2f} & "
            f"{best['emissions']:.2f} & {mean_emissions:.2f}\\\\"
        )
    for arm, item in summary.items():
        best = item["best"]
        print(
            f"{arm}: n={item['n']} best={best['cost']:.2f} ({best['run']}, "
            f"{best['cv']}CV/{best['ev']}EV, E={best['emissions']:.2f} kg, "
            f"grid={item['intensity'] and round(item['intensity'], 1)} g/kWh) "
            f"mean={item['mean_cost']:.2f} worst={item['worst']:.2f} gap={item['gap']:.2f}% "
            f"meanE={item['mean_emissions']:.2f} kg wall={item['mean_wall']:.1f} min "
            f"iters={item['mean_iterations']:.0f} served={item['served']}"
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"rows -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
