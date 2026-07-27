"""D8b: phase 2 only, with a sparse constraint matrix.

D8's phase 1 is already on disk (40 runs).  Its phase 2 was building the set
partitioning constraint matrix as a dense numpy array: about 960 rows by 5000
columns, where each column carries roughly 12 non-zeros.  That is 1.25% density,
so HiGHS was handed a matrix that is 99% zeros and spent its time accordingly.
This rebuilds the same model with scipy.sparse and reports the MILP gap honestly
instead of calling a time-limited solve "exact".

Nothing about the mechanism changes: same pooled columns, same constraints, same
monotone-safety argument (the incumbent's own columns are in the pool).
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_matrix

from pyvrp import read
from pyvrp._pyvrp import Route as NativeRoute, Solution as NativeSolution

ROOT = Path(__file__).resolve().parents[3]
FOUNDATION = ROOT / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
INSTANCE_DIR = FOUNDATION / "sources/normalised_instances"
BKS_DIR = FOUNDATION / "sources/current_bks"
OUT = Path(__file__).resolve().parent
RUNS = OUT / "d8_runs"

SCALE = 1000.0
SP_TIME = 300.0
EPS = 1.0e-6
INSTANCES = ["PR16A", "PR16B", "PR20A", "PR24A"]
SEEDS = range(1, 11)


def bks(instance_id):
    for line in (BKS_DIR / f"{instance_id}.sol").read_text().splitlines():
        if line.lower().startswith("cost"):
            return float(line.split()[-1]) / SCALE
    return None


def solve(data, routes: dict[str, float], tl: float):
    recs = []
    for key, dist in routes.items():
        vt, visits = key.split("|", 1)
        recs.append(((int(vt), tuple(int(v) for v in visits.split(",") if v)), dist))

    clients = list(range(data.num_depots, data.num_locations))
    idx = {c: i for i, c in enumerate(clients)}

    rows, cols = [], []
    for col, ((_, visits), _) in enumerate(recs):
        for v in visits:
            rows.append(idx[v])
            cols.append(col)
    cover = csc_matrix(
        (np.ones(len(rows)), (rows, cols)), shape=(len(clients), len(recs))
    )

    vrows, vcols = [], []
    for col, ((vt, _), _) in enumerate(recs):
        vrows.append(vt)
        vcols.append(col)
    veh = csc_matrix(
        (np.ones(len(vrows)), (vrows, vcols)),
        shape=(data.num_vehicle_types, len(recs)),
    )
    veh_ub = np.array(
        [float(data.vehicle_type(vt).num_available)
         for vt in range(data.num_vehicle_types)]
    )

    cons = [
        LinearConstraint(cover, lb=np.ones(len(clients)), ub=np.ones(len(clients))),
        LinearConstraint(veh, lb=-np.inf * np.ones(len(veh_ub)), ub=veh_ub),
    ]
    started = perf_counter()
    res = milp(
        c=np.array([c for _, c in recs]),
        integrality=np.ones(len(recs)),
        bounds=Bounds(np.zeros(len(recs)), np.ones(len(recs))),
        constraints=cons,
        options={"time_limit": float(tl)},
    )
    elapsed = perf_counter() - started
    info = {
        "columns": len(recs),
        "nonzeros": len(rows),
        "density_pct": round(len(rows) / (len(clients) * len(recs)) * 100, 4),
        "milp_seconds": round(elapsed, 2),
        "status": int(getattr(res, "status", -1)),
        "message": str(getattr(res, "message", ""))[:120],
        "mip_gap": getattr(res, "mip_gap", None),
        "hit_time_limit": elapsed >= tl - 1.0,
    }
    if res.x is None:
        return None, info
    chosen = [recs[i] for i, v in enumerate(res.x) if v > 0.5]
    sol = NativeSolution(
        data, [NativeRoute(data, list(vis), vt) for (vt, vis), _ in chosen]
    )
    if not sol.is_feasible():
        info["infeasible_partition"] = True
        return None, info
    return float(sum(r.distance() for r in sol.routes())) / SCALE, info


def main():
    rows = []
    for inst in INSTANCES:
        data = read(str(INSTANCE_DIR / f"{inst}.vrp"), round_func="exact")
        b = bks(inst)
        recs = []
        for s in SEEDS:
            f = RUNS / f"{inst}__s{s}.json"
            if f.is_file():
                recs.append(json.loads(f.read_text(encoding="utf-8")))
        recs.sort(key=lambda r: r["seed"])
        best_of = min(r["best_cost"] for r in recs)
        merged = {}
        for r in recs:
            for k, c in r["routes"].items():
                merged.setdefault(k, c)
        cost, info = solve(data, merged, SP_TIME)
        gain = (best_of - cost) if cost is not None else None
        row = {
            "instance_id": inst, "k_seeds": len(recs),
            "best_of_k": best_of, "sp_cost": cost,
            "gain_vs_best_of_k": gain, "bks": b,
            "best_of_k_error_pct": (best_of - b) / b * 100,
            "sp_error_pct": (cost - b) / b * 100 if cost is not None else None,
            "new_bks": bool(cost is not None and cost < b - EPS),
            **info,
        }
        rows.append(row)
        print(
            f"  {inst:<7} bestOf{len(recs)}={best_of:>10.3f} "
            f"SP={cost if cost is None else round(cost, 3):>10} "
            f"gain={gain if gain is None else round(gain, 3):>8} "
            f"cols={info['columns']:>5} nz={info['nonzeros']:>6} "
            f"dens={info['density_pct']}% milp={info['milp_seconds']:>6.1f}s "
            f"limit={info['hit_time_limit']} "
            f"vsBKS={row['sp_error_pct'] if row['sp_error_pct'] is None else round(row['sp_error_pct'], 4)}"
            f"{'  *** NEW BKS ***' if row['new_bks'] else ''}",
            flush=True,
        )

    with (OUT / "d8b_raw_runs.csv").open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    ok = [r for r in rows if r["gain_vs_best_of_k"] is not None]
    (OUT / "d8b_summary.json").write_text(json.dumps({
        "schema": "resetp.public-algo-diag.d8b.v1",
        "note": "sparse constraint matrix; MILP gap and time-limit status disclosed",
        "iterations_per_run": 20000, "instances": INSTANCES, "seeds": list(SEEDS),
        "improved_count": sum(1 for r in ok if r["gain_vs_best_of_k"] > EPS),
        "new_bks_count": sum(1 for r in rows if r["new_bks"]),
        "mean_gain": round(statistics.mean(r["gain_vs_best_of_k"] for r in ok), 3) if ok else None,
        "errors_before": {r["instance_id"]: round(r["best_of_k_error_pct"], 4) for r in rows},
        "errors_after": {r["instance_id"]: (round(r["sp_error_pct"], 4) if r["sp_error_pct"] is not None else None) for r in rows},
        "any_hit_time_limit": any(r["hit_time_limit"] for r in rows),
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print()
    print(json.dumps({"new_bks": sum(1 for r in rows if r["new_bks"]),
                      "improved": sum(1 for r in ok if r["gain_vs_best_of_k"] > EPS)}, indent=2))


if __name__ == "__main__":
    main()
