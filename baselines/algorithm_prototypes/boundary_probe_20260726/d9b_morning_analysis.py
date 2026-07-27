"""D9b: morning analysis over the overnight deep runs.

Two independent readouts on d9_runs (PR24A, PR16B x 10 seeds x 64,000 iters):

1.  Pooled set partitioning with the min(best-of-k, MILP incumbent) safeguard
    that D8b showed is mandatory on large pools, sparse matrix, gap disclosed.
    This is the gamma arm's final number and the new-BKS check.

2.  The candidate-alpha kill test: edge-agreement statistics across the ten
    saved best solutions per instance.  An edge here is an ordered pair of
    consecutive stops within a route (depot ends included, direction kept,
    since these matrices are symmetric the direction hardly matters but keeping
    it is conservative).  If a large share of edges appears in >=8/10 solutions,
    consensus contraction has raw material; if agreement is low, alpha dies
    before a line of it is implemented.

Read-only over saved runs; the only compute is two MILPs.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
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
RUNS = OUT / "d9_runs"

SCALE = 1000.0
SP_TIME = 600.0
EPS = 1.0e-6
INSTANCES = ["PR24A", "PR16B"]


def bks(instance_id):
    for line in (BKS_DIR / f"{instance_id}.sol").read_text().splitlines():
        if line.lower().startswith("cost"):
            return float(line.split()[-1]) / SCALE
    return None


def load_runs(instance_id):
    recs = []
    for s in range(1, 11):
        f = RUNS / f"{instance_id}__s{s}.json"
        if f.is_file():
            recs.append(json.loads(f.read_text(encoding="utf-8")))
    return sorted(recs, key=lambda r: r["seed"])


def solve_sp(data, routes, tl):
    recs = []
    for key, dist in routes.items():
        vt, visits = key.split("|", 1)
        recs.append(((int(vt), tuple(int(v) for v in visits.split(",") if v)), dist))
    clients = list(range(data.num_depots, data.num_locations))
    idx = {c: i for i, c in enumerate(clients)}
    r_, c_ = [], []
    for col, ((_, visits), _) in enumerate(recs):
        for v in visits:
            r_.append(idx[v]); c_.append(col)
    cover = csc_matrix((np.ones(len(r_)), (r_, c_)), shape=(len(clients), len(recs)))
    vr, vc = [], []
    for col, ((vt, _), _) in enumerate(recs):
        vr.append(vt); vc.append(col)
    veh = csc_matrix((np.ones(len(vr)), (vr, vc)),
                     shape=(data.num_vehicle_types, len(recs)))
    veh_ub = np.array([float(data.vehicle_type(t).num_available)
                       for t in range(data.num_vehicle_types)])
    cons = [
        LinearConstraint(cover, lb=np.ones(len(clients)), ub=np.ones(len(clients))),
        LinearConstraint(veh, lb=-np.inf * np.ones(len(veh_ub)), ub=veh_ub),
    ]
    t0 = perf_counter()
    res = milp(c=np.array([c for _, c in recs]), integrality=np.ones(len(recs)),
               bounds=Bounds(np.zeros(len(recs)), np.ones(len(recs))),
               constraints=cons, options={"time_limit": float(tl)})
    el = perf_counter() - t0
    info = {"columns": len(recs), "milp_seconds": round(el, 1),
            "hit_limit": el >= tl - 1.0, "mip_gap": getattr(res, "mip_gap", None)}
    if res.x is None:
        return None, info
    chosen = [recs[i] for i, v in enumerate(res.x) if v > 0.5]
    sol = NativeSolution(data, [NativeRoute(data, list(vis), vt)
                                for (vt, vis), _ in chosen])
    if not sol.is_feasible():
        return None, info
    return float(sum(r.distance() for r in sol.routes())) / SCALE, info


def edges_of(best_routes, depot_token="D"):
    """Ordered consecutive pairs inside each best-solution route, depots kept."""
    edges = set()
    for key in best_routes:
        _, visits = key.split("|", 1)
        seq = [int(v) for v in visits.split(",") if v]
        # depot endpoints unknown from the key; use client-client edges only,
        # which is conservative for contraction (chains never touch depots).
        for a, b in zip(seq, seq[1:]):
            edges.add((a, b))
    return edges


def main():
    out = {}
    for inst in INSTANCES:
        data = read(str(INSTANCE_DIR / f"{inst}.vrp"), round_func="exact")
        b = bks(inst)
        recs = load_runs(inst)
        if not recs:
            print(f"{inst}: no runs yet"); continue
        best_of = min(r["best_cost"] for r in recs)

        # --- gamma: pooled SP with min() safeguard ---
        merged = {}
        for r in recs:
            for k, c in r["routes"].items():
                merged.setdefault(k, c)
        sp_cost, info = solve_sp(data, merged, SP_TIME)
        final = min(best_of, sp_cost) if sp_cost is not None else best_of
        new_bks = final < b - EPS

        # --- alpha kill test: edge agreement across ten best solutions ---
        counters = Counter()
        n_sol = 0
        for r in recs:
            if "best_routes" not in r:
                continue
            n_sol += 1
            for e in edges_of(r["best_routes"]):
                counters[e] += 1
        per_edge = list(counters.values())
        total_edges_union = len(per_edge)
        # edges in the BEST solution and their agreement across the other runs
        best_rec = min(recs, key=lambda r: r["best_cost"])
        best_edges = edges_of(best_rec.get("best_routes", []))
        agree8 = sum(1 for e in best_edges if counters[e] >= 8)
        agree9 = sum(1 for e in best_edges if counters[e] >= 9)
        agree10 = sum(1 for e in best_edges if counters[e] >= 10)

        row = {
            "best_of_10": best_of,
            "sp_cost": sp_cost, **info,
            "final": final, "bks": b,
            "final_error_pct": round((final - b) / b * 100, 4),
            "new_bks": bool(new_bks),
            "solutions_with_saved_routes": n_sol,
            "union_edges": total_edges_union,
            "best_solution_edges": len(best_edges),
            "best_edges_in_ge8_of_10": agree8,
            "best_edges_in_ge9_of_10": agree9,
            "best_edges_in_all_10": agree10,
            "agree8_pct_of_best": round(agree8 / len(best_edges) * 100, 2) if best_edges else None,
            "mean_iterations": int(statistics.mean(r["iterations"] for r in recs)),
        }
        out[inst] = row
        print(f"=== {inst} ===")
        print(f"  best-of-10 = {best_of:.3f}   SP = {sp_cost}   final = {final:.3f}"
              f"   BKS = {b:.3f}   误差 {row['final_error_pct']}%"
              f"{'   *** NEW BKS ***' if new_bks else ''}")
        print(f"  MILP: {info['columns']} 列, {info['milp_seconds']}s, gap={info['mip_gap']}")
        print(f"  α kill-test: 最好解 {len(best_edges)} 条边中, ≥8/10 一致 {agree8}"
              f" ({row['agree8_pct_of_best']}%), ≥9 {agree9}, 全10 {agree10}")

    Path(OUT / "d9b_summary.json").write_text(
        json.dumps({"schema": "resetp.public-algo-diag.d9b.v1", **out},
                   indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nsaved d9b_summary.json")


if __name__ == "__main__":
    main()
