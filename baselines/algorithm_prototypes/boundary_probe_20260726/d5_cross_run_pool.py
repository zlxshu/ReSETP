"""D5: does assembling routes across independent runs beat one long run?

Everything closed so far says the same thing: within a single run, nothing beats
spending the budget on HGS iterations.  This probe attacks the one thing that
statement does not cover -- assembly *across* runs.

Why more iterations cannot capture this: a single HGS run converges into one
basin, so the routes that would combine into a better solution may only exist in
a different run's basin.  P4 already sprinted with a larger budget and different
seeds and produced zero new BKS, so more iteration demonstrably does not reach
it.

How this differs from D2, which is closed: D2 enriched the pool from one run's
population, and those routes are near-duplicates (40 solutions yielded 38
distinct routes on PR17B).  Pooling across independent seeds draws routes from
different basins, which is a structural difference rather than a rename.

Arms share an identical total iteration budget:

  single    one run of TOTAL iterations
  pool4     four independent runs of TOTAL/4, union of routes, exact SP
  pool8     eight independent runs of TOTAL/8, union of routes, exact SP

The MILP time is extra and is reported separately; it is not hidden inside the
iteration parity claim.
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
# Small band only: this is where new BKS is reachable (PR17B already matches
# BKS, PR21B is 0.01% off).  The sealed engine needed ~16,000 iterations to get
# there, so a 6,200-iteration budget would test pooling far away from the
# frontier and answer the wrong question.
TOTAL_ITERS = 16000
K_NOIMPROVE = 4000
SP_TIME = 60.0
EPS = 1.0e-6


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


def _one_run(data, params, seed, iters):
    """One independent HGS run; returns (best, population, penalty manager)."""

    rng = RandomNumberGenerator(seed=int(seed))
    initial = [
        NativeSolution.make_random(data, rng)
        for _ in range(params.population.min_pop_size)
    ]
    algo, pop, pm = _build(data, rng, params, initial)
    res = algo.run(
        MultipleCriteria([NoImprovement(K_NOIMPROVE), MaxIterations(iters)]),
        collect_stats=False,
        display=False,
    )
    return res.best, pop, pm, int(res.num_iterations)


def _pool_from(pool, solutions) -> None:
    for s in solutions:
        for r in s.routes():
            pool.setdefault(
                (r.vehicle_type(), tuple(r.visits())), float(r.distance())
            )


def _solve_sp(data, pool, incumbent, tl):
    """Exact set partitioning over the whole pool.

    The incumbent's own routes are always present, so a feasible partition
    always exists and the MILP can never come back empty for want of coverage.
    """

    _pool_from(pool, [incumbent])
    recs = list(pool.items())
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
    stats = {"columns": len(recs), "milp_seconds": round(elapsed, 2),
             "milp_success": bool(res.success), "selected": 0}
    if res.x is None:
        return None, stats
    chosen = [recs[i] for i, v in enumerate(res.x) if v > 0.5]
    stats["selected"] = len(chosen)
    sol = NativeSolution(
        data, [NativeRoute(data, list(vis), vt) for (vt, vis), _ in chosen]
    )
    return (sol if sol.is_feasible() else None), stats


def _bks(instance_id: str) -> float | None:
    path = BKS_DIR / f"{instance_id}.sol"
    if not path.is_file():
        return None
    for line in path.read_text().splitlines():
        if line.lower().startswith("cost"):
            try:
                # BKS files store the scaled integer objective, e.g. 4771155
                return float(line.split()[-1]) / SCALE
            except ValueError:
                return None
    return None


def _run(args) -> dict[str, Any]:
    instance_id, seed, arm = args
    data = read(str(INSTANCE_DIR / f"{instance_id}.vrp"), round_func=ROUND_FUNC)
    params = SolveParams()
    started = perf_counter()

    k = {"single": 1, "pool4": 4, "pool8": 8}[arm]
    per_run = TOTAL_ITERS // k
    pool: dict = {}
    best, best_raw, iters_total = None, float("inf"), 0
    run_costs = []
    for j in range(k):
        sub_seed = int(seed) * 100_003 + j * 7919
        sol, pop, pm, iters = _one_run(data, params, sub_seed, per_run)
        iters_total += iters
        run_costs.append(_cost(sol) / SCALE)
        _pool_from(pool, [x for x in pop if x.is_feasible()])
        _pool_from(pool, [sol])
        if _cost(sol) < best_raw:
            best, best_raw = sol, _cost(sol)

    sp_stats: dict[str, Any] = {}
    sp_cost = None
    if k > 1:
        sp_sol, sp_stats = _solve_sp(data, pool, best, SP_TIME)
        if sp_sol is not None:
            sp_cost = _cost(sp_sol) / SCALE
            if _cost(sp_sol) < best_raw - EPS:
                best, best_raw = sp_sol, _cost(sp_sol)

    bks = _bks(instance_id)
    final = best_raw / SCALE
    return {
        "instance_id": instance_id,
        "seed": seed,
        "arm": arm,
        "runs": k,
        "iters_per_run": per_run,
        "iters_total": iters_total,
        "best_single_run_cost": min(run_costs),
        "final_cost": final,
        "sp_cost": sp_cost,
        "sp_improved": bool(sp_cost is not None and sp_cost < min(run_costs) - EPS),
        "pool_columns": sp_stats.get("columns", len(pool)),
        "milp_seconds": sp_stats.get("milp_seconds", 0.0),
        "bks": bks,
        "error_vs_bks_pct": (final - bks) / bks * 100 if bks else None,
        "cpu_seconds": round(perf_counter() - started, 1),
    }


def main() -> int:
    instances = ["PR17B", "PR21B", "PR11B", "PR21A"]
    arms = ["single", "pool4", "pool8"]
    seeds = (1, 2, 3)
    jobs = [(i, s, a) for s in seeds for a in arms for i in instances]
    print(f"running {len(jobs)} units on 6 workers", flush=True)
    rows = []
    with ProcessPoolExecutor(max_workers=6) as pool:
        for row in pool.map(_run, jobs):
            rows.append(row)
            err = (
                f"{row['error_vs_bks_pct']:+.4f}%"
                if row["error_vs_bks_pct"] is not None
                else "n/a"
            )
            print(
                f"  s{row['seed']} {row['instance_id']:<7} {row['arm']:<7} "
                f"cost={row['final_cost']:>10.3f} vsBKS={err:>10} "
                f"bestRun={row['best_single_run_cost']:>10.3f} "
                f"cols={row['pool_columns']:>5} milp={row['milp_seconds']:>5.1f}s "
                f"cpu={row['cpu_seconds']:.0f}s",
                flush=True,
            )

    with (OUT / "d5_raw_runs.csv").open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    from collections import defaultdict

    paired = defaultdict(dict)
    for r in rows:
        paired[(r["instance_id"], r["seed"])][r["arm"]] = r["final_cost"]

    summary: dict[str, Any] = {"schema": "resetp.public-algo-diag.d5.v1",
                               "total_iterations": TOTAL_ITERS, "seeds": list(seeds)}
    for arm in ("pool4", "pool8"):
        d = [
            v[arm] - v["single"]
            for v in paired.values()
            if arm in v and "single" in v
        ]
        summary[arm] = {
            "paired_units": len(d),
            "wins_vs_single": sum(1 for x in d if x < -EPS),
            "losses_vs_single": sum(1 for x in d if x > EPS),
            "mean_delta": round(statistics.mean(d), 4) if d else None,
            "median_delta": round(statistics.median(d), 4) if d else None,
        }
    (OUT / "d5_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
