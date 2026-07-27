"""D4: multi-seed confirmation of the equal-budget verdict.

D3 ran one seed and found the hybrid 0.0963% worse than an equal-iteration
mother, split 2/4.  The per-instance deltas there (+40.9, +17.8, -81.0, +56.0,
-4.2, +27.8) are the same size as the seed-to-seed variation already observed
(PR16A came out 14437.743 in D1 and 14427.883 in D2), so one seed cannot
separate "the hybrid is worse" from "the hybrid is a wash".

Either reading kills the sealed claim of +1.24% over the mother, but they are
different sentences and the report should carry whichever the evidence
supports.  This adds seeds 2-5 on the same six instances for the two arms that
matter; `mother_short` is not repeated because its only job was to reproduce
the sealed comparison, which D3 already did.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from d3_equal_budget import _run  # noqa: E402

OUT = Path(__file__).resolve().parent
INSTANCES = ["PR16A", "PR16B", "PR20A", "PR24A", "PR17B", "PR21B"]
SEEDS = (2, 3, 4, 5)
ARMS = ("hybrid", "mother_equal")


def main() -> int:
    jobs = [(i, s, a) for s in SEEDS for a in ARMS for i in INSTANCES]
    print(f"running {len(jobs)} units on 6 workers", flush=True)
    rows = []
    with ProcessPoolExecutor(max_workers=6) as pool:
        for row in pool.map(_run, jobs):
            rows.append(row)
            print(
                f"  s{row['seed']} {row['instance_id']:<7} {row['arm']:<13} "
                f"cost={row['final_cost']:>10.3f} src={row['final_source']:<7} "
                f"cpu={row['cpu_seconds']:.0f}s",
                flush=True,
            )

    with (OUT / "d4_raw_runs.csv").open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # merge D3 seed 1 for the two arms, so the verdict covers seeds 1-5
    d3 = [
        r
        for r in csv.DictReader((OUT / "d3_raw_runs.csv").open(encoding="utf-8"))
        if r["arm"] in ARMS
    ]
    merged = [
        {"instance_id": r["instance_id"], "seed": int(r["seed"]),
         "arm": r["arm"], "final_cost": float(r["final_cost"])}
        for r in d3
    ] + [
        {"instance_id": r["instance_id"], "seed": int(r["seed"]),
         "arm": r["arm"], "final_cost": float(r["final_cost"])}
        for r in rows
    ]

    paired: dict[tuple[str, int], dict[str, float]] = {}
    for r in merged:
        paired.setdefault((r["instance_id"], r["seed"]), {})[r["arm"]] = r["final_cost"]

    deltas, wins, losses, ties = [], 0, 0, 0
    per_instance: dict[str, list[float]] = {}
    for (inst, _seed), arms in sorted(paired.items()):
        if len(arms) != 2:
            continue
        d = arms["hybrid"] - arms["mother_equal"]
        deltas.append(d)
        per_instance.setdefault(inst, []).append(d)
        if d < -1e-9:
            wins += 1
        elif d > 1e-9:
            losses += 1
        else:
            ties += 1

    tot_h = sum(a["hybrid"] for a in paired.values() if len(a) == 2)
    tot_m = sum(a["mother_equal"] for a in paired.values() if len(a) == 2)

    print()
    print(f"{'题':<8}{'配对数':>6}{'均值Δ':>12}{'中位Δ':>12}   hybrid胜/负")
    for inst in INSTANCES:
        ds = per_instance.get(inst, [])
        if not ds:
            continue
        print(
            f"{inst:<8}{len(ds):>6}{statistics.mean(ds):>+12.3f}"
            f"{statistics.median(ds):>+12.3f}   "
            f"{sum(1 for d in ds if d < -1e-9)}/{sum(1 for d in ds if d > 1e-9)}"
        )

    summary = {
        "schema": "resetp.public-algo-diag.d4.v1",
        "arms": list(ARMS),
        "seeds": [1, *SEEDS],
        "instances": INSTANCES,
        "paired_units": len(deltas),
        "hybrid_wins": wins,
        "hybrid_losses": losses,
        "hybrid_ties": ties,
        "mean_delta_cost": round(statistics.mean(deltas), 4),
        "median_delta_cost": round(statistics.median(deltas), 4),
        "stdev_delta_cost": round(statistics.stdev(deltas), 4)
        if len(deltas) > 1
        else None,
        "aggregate_hybrid_total": round(tot_h, 3),
        "aggregate_mother_equal_total": round(tot_m, 3),
        "aggregate_hybrid_vs_mother_pct": round((tot_h - tot_m) / tot_m * 100, 4),
        "interpretation_rule": (
            "positive delta means the hybrid is more expensive; a win/loss split "
            "near even with an aggregate inside seed noise supports 'no evidence "
            "of benefit' rather than 'the hybrid is worse'"
        ),
    }
    (OUT / "d4_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
