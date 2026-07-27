"""D6: pooling the seeds the protocol already pays for.

D5 showed the cross-run set partitioning fires 24 times out of 24, improving on
the best single run in its pool by a mean of 34.67 cost units.  Its net result
was still weak only because D5 split a fixed budget into k shorter runs, and the
quality lost to shorter runs ate most of what the SP won.

That loss is avoidable.  The sealed protocol already runs ten full-length seeds
per instance and reports best-of-ten.  Those runs are paid for either way, so
pooling their routes and solving one set partitioning costs no extra search --
only one MILP.  And because the incumbent's own routes are in the pool, the
result can never be worse than best-of-ten; it is a monotone free improvement.

The open question is size, not sign.  D5's pools came from short, unconverged
runs whose routes differ a lot.  Ten converged runs may produce near-duplicate
routes, which is exactly what killed D2's within-run pooling.  So this measures
it directly rather than extrapolating.

Phase 1 runs each (instance, seed) independently and saves its routes.
Phase 2 pools offline, which also gives the effect of k for free by pooling
subsets of the same saved runs.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
FOUNDATION = ROOT / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
INSTANCE_DIR = FOUNDATION / "sources/normalised_instances"
BKS_DIR = FOUNDATION / "sources/current_bks"
OUT = Path(__file__).resolve().parent
RUNS_DIR = OUT / "d6_runs"

from scipy.optimize import Bounds, LinearConstraint, milp  # noqa: E402

from pyvrp import read  # noqa: E402
from pyvrp._pyvrp import (  # noqa: E402
    RandomNumberGenerator,
    Route as NativeRoute,
    Solution as NativeSolution,
)
from pyvrp.GeneticAlgorithm import GeneticAlgorithm  # noqa: E402
from pyvrp.PenaltyManager import PenaltyManager  # noqa: E402
from pyvrp.Population import Population  # noqa: E402
from pyvrp.crossover import ordered_crossover, selective_route_exchange  # noqa: E402
from pyvrp.diversity import broken_pairs_distance  # noqa: E402
from pyvrp.search import LocalSearch, compute_neighbours  # noqa: E402
from pyvrp.solve import SolveParams  # noqa: E402
from pyvrp.stop import MaxIterations, MultipleCriteria, NoImprovement  # noqa: E402

ROUND_FUNC = "exact"
SCALE = 1000.0
ITERS = 16000
K_NOIMPROVE = 4000
SP_TIME = 120.0
EPS = 1.0e-6
INSTANCES = ["PR17B", "PR21B", "PR11B", "PR21A", "PR12B"]
SEEDS = tuple(range(1, 11))


def _build(data, rng, params, initial):
    ls = LocalSearch(data, rng, compute_neighbours(data, params.neighbourhood))
    for op in params.node_ops:
        if op.supports(data):
            ls.add_node_operator(op(data))
    for op in params.route_ops:
        if op.supports(data):
            ls.add_route_operator(op(data))
    pm = PenaltyManager.init_from(data, params.penalty)
    pop = Population(broken_pairs_distance, params.population)
    crossover = (
        selective_route_exchange if data.num_vehicles > 1 else ordered_crossover
    )
    return GeneticAlgorithm(
        data, pm, rng, pop, ls, crossover, initial, params.genetic
    ), pop, pm


def _cost(s) -> float:
    return float(sum(r.distance() for r in s.routes()))


def _phase1(args) -> dict[str, Any]:
    """One independent full-length run; saves its routes for offline pooling."""

    instance_id, seed = args
    target = RUNS_DIR / f"{instance_id}__s{seed}.json"
    if target.is_file():
        return json.loads(target.read_text())

    data = read(str(INSTANCE_DIR / f"{instance_id}.vrp"), round_func=ROUND_FUNC)
    params = SolveParams()
    started = perf_counter()
    rng = RandomNumberGenerator(seed=int(seed))
    initial = [
        NativeSolution.make_random(data, rng)
        for _ in range(params.population.min_pop_size)
    ]
    algo, pop, pm = _build(data, rng, params, initial)
    res = algo.run(
        MultipleCriteria([NoImprovement(K_NOIMPROVE), MaxIterations(ITERS)]),
        collect_stats=False,
        display=False,
    )

    routes: dict[str, float] = {}
    def add(sol):
        for r in sol.routes():
            key = f"{r.vehicle_type()}|" + ",".join(str(v) for v in r.visits())
            routes.setdefault(key, float(r.distance()))

    add(res.best)
    for member in pop:
        if member.is_feasible():
            add(member)

    record = {
        "instance_id": instance_id,
        "seed": seed,
        "iterations": int(res.num_iterations),
        "best_cost": _cost(res.best) / SCALE,
        "routes": routes,
        "cpu_seconds": round(perf_counter() - started, 1),
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record))
    return record


def _bks(instance_id: str) -> float | None:
    path = BKS_DIR / f"{instance_id}.sol"
    if not path.is_file():
        return None
    for line in path.read_text().splitlines():
        if line.lower().startswith("cost"):
            try:
                return float(line.split()[-1]) / SCALE
            except ValueError:
                return None
    return None


def _solve_sp(data, routes: dict[str, float], tl: float):
    recs = []
    for key, dist in routes.items():
        vt_str, visits_str = key.split("|", 1)
        visits = [int(v) for v in visits_str.split(",") if v]
        recs.append(((int(vt_str), tuple(visits)), dist))
    clients = list(range(data.num_depots, data.num_locations))
    idx = {c: i for i, c in enumerate(clients)}
    m = np.zeros((len(clients), len(recs)))
    for col, ((_, visits), _) in enumerate(recs):
        for v in visits:
            m[idx[v], col] = 1.0
    cons = [LinearConstraint(m, lb=np.ones(len(clients)), ub=np.ones(len(clients)))]
    for vt in range(data.num_vehicle_types):
        row = np.array([1.0 if k[0] == vt else 0.0 for k, _ in recs])
        cons.append(
            LinearConstraint(
                row, lb=-np.inf, ub=float(data.vehicle_type(vt).num_available)
            )
        )
    started = perf_counter()
    res = milp(
        c=np.array([c for _, c in recs]),
        integrality=np.ones(len(recs)),
        bounds=Bounds(np.zeros(len(recs)), np.ones(len(recs))),
        constraints=cons,
        options={"time_limit": float(tl)},
    )
    elapsed = perf_counter() - started
    if res.x is None:
        return None, len(recs), elapsed
    chosen = [recs[i] for i, v in enumerate(res.x) if v > 0.5]
    sol = NativeSolution(
        data, [NativeRoute(data, list(vis), vt) for (vt, vis), _ in chosen]
    )
    if not sol.is_feasible():
        return None, len(recs), elapsed
    return _cost(sol) / SCALE, len(recs), elapsed


def main() -> int:
    jobs = [(i, s) for i in INSTANCES for s in SEEDS]
    print(f"phase 1: {len(jobs)} independent full-length runs on 6 workers", flush=True)
    records: dict[str, list[dict]] = {i: [] for i in INSTANCES}
    with ProcessPoolExecutor(max_workers=6) as pool:
        for rec in pool.map(_phase1, jobs):
            records[rec["instance_id"]].append(rec)
            print(
                f"  {rec['instance_id']:<7} s{rec['seed']:<3} "
                f"best={rec['best_cost']:>10.3f} iters={rec['iterations']:>6} "
                f"routes={len(rec['routes']):>4} cpu={rec['cpu_seconds']:.0f}s",
                flush=True,
            )

    print("\nphase 2: offline pooling", flush=True)
    rows = []
    for instance_id in INSTANCES:
        data = read(
            str(INSTANCE_DIR / f"{instance_id}.vrp"), round_func=ROUND_FUNC
        )
        bks = _bks(instance_id)
        recs = sorted(records[instance_id], key=lambda r: r["seed"])
        for k in (2, 4, 6, 8, 10):
            subset = recs[:k]
            best_of_k = min(r["best_cost"] for r in subset)
            merged: dict[str, float] = {}
            for r in subset:
                for key, dist in r["routes"].items():
                    merged.setdefault(key, dist)
            sp_cost, columns, milp_s = _solve_sp(data, merged, SP_TIME)
            gain = (best_of_k - sp_cost) if sp_cost is not None else None
            rows.append(
                {
                    "instance_id": instance_id,
                    "k_seeds": k,
                    "best_of_k": best_of_k,
                    "sp_cost": sp_cost,
                    "gain_vs_best_of_k": gain,
                    "columns": columns,
                    "milp_seconds": round(milp_s, 2),
                    "bks": bks,
                    "best_of_k_error_pct": (best_of_k - bks) / bks * 100 if bks else None,
                    "sp_error_pct": (sp_cost - bks) / bks * 100
                    if (bks and sp_cost is not None)
                    else None,
                    "new_bks": bool(bks and sp_cost is not None and sp_cost < bks - EPS),
                }
            )
            print(
                f"  {instance_id:<7} k={k:<3} bestOf{k}={best_of_k:>10.3f} "
                f"SP={sp_cost if sp_cost is None else round(sp_cost, 3):>10} "
                f"gain={gain if gain is None else round(gain, 3):>8} "
                f"cols={columns:>5} milp={milp_s:>6.1f}s "
                f"vsBKS={rows[-1]['sp_error_pct'] if rows[-1]['sp_error_pct'] is None else round(rows[-1]['sp_error_pct'], 4)}"
                f"{'  *** NEW BKS ***' if rows[-1]['new_bks'] else ''}",
                flush=True,
            )

    with (OUT / "d6_raw_runs.csv").open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    at10 = [r for r in rows if r["k_seeds"] == 10 and r["gain_vs_best_of_k"] is not None]
    summary = {
        "schema": "resetp.public-algo-diag.d6.v1",
        "iterations_per_run": ITERS,
        "instances": INSTANCES,
        "seeds": list(SEEDS),
        "at_k10": {
            "instances": len(at10),
            "gains": {r["instance_id"]: round(r["gain_vs_best_of_k"], 3) for r in at10},
            "mean_gain": round(statistics.mean(r["gain_vs_best_of_k"] for r in at10), 3)
            if at10
            else None,
            "improved_count": sum(1 for r in at10 if r["gain_vs_best_of_k"] > EPS),
            "new_bks_count": sum(1 for r in at10 if r["new_bks"]),
            "errors_before": {r["instance_id"]: round(r["best_of_k_error_pct"], 4) for r in at10},
            "errors_after": {r["instance_id"]: round(r["sp_error_pct"], 4) for r in at10},
        },
        "note": "SP over the pool can never be worse than best-of-k: the incumbent's routes are in the pool",
    }
    (OUT / "d6_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
