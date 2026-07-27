"""A3: dual-guided column generation over a cross-run route pool.

Frozen by `PREREGISTRATION.md` before any run.  Read that file first; this
script only implements it.

Why this and not more restarts: D6 measured that random restarts saturate at
k~8 -- k=8 and k=10 gave bit-identical set-partitioning results on all five
instances while the pool kept growing by 25-155 distinct routes per extra run.
New columns keep arriving; none of them are the columns the partition needs.
The classical answer to "which column is missing" is the one with negative
reduced cost under the current LP duals, and HGS has no reason to produce such a
route on its own: it optimises true cost inside one basin, and the useful column
is individually mediocre but valuable in combination.

Feasibility safety: in these instances the distance and duration matrices are
equal, but PyVRP stores them separately, and feasibility (time windows, maximum
route duration, capacity) is evaluated on duration.  So the guided instance
replaces only the distance matrix; every route found there is feasible in the
true instance, and is re-priced with true distances before entering the pool.
No reported cost ever comes from guided distances.
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
D6_RUNS = ROOT / "baselines/algorithm_prototypes/boundary_probe_20260726/d6_runs"

from scipy.optimize import Bounds, LinearConstraint, linprog, milp  # noqa: E402

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

# --- frozen settings (PREREGISTRATION.md sec. 5) ---
ROUND_FUNC = "exact"
SCALE = 1000.0
ITERS = 16_000
K_NOIMPROVE = 4_000
SEED_RUNS = 6            # independent runs seeding the initial pool
GUIDED_ROUNDS = 4        # dual-guided rounds; 6 + 4 = 10 x ITERS, matching A1/A2
LP_TIME = 120.0
MILP_TIME = 120.0
EPS = 1.0e-6
INSTANCES = ["PR17B", "PR21B", "PR11B", "PR21A", "PR12B"]


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


def _key(vehicle_type: int, visits) -> str:
    return f"{vehicle_type}|" + ",".join(str(v) for v in visits)


def _parse(key: str) -> tuple[int, tuple[int, ...]]:
    vt, visits = key.split("|", 1)
    return int(vt), tuple(int(v) for v in visits.split(",") if v)


def _true_cost(true_data, key: str) -> float:
    vt, visits = _parse(key)
    return float(NativeRoute(true_data, list(visits), vt).distance())


def _columns(pool: dict[str, float]):
    return [(_parse(k), c) for k, c in pool.items()]


def _matrix(data, recs):
    clients = list(range(data.num_depots, data.num_locations))
    idx = {c: i for i, c in enumerate(clients)}
    m = np.zeros((len(clients), len(recs)))
    for col, ((_, visits), _) in enumerate(recs):
        for v in visits:
            m[idx[v], col] = 1.0
    return m, clients


def _vehicle_rows(data, recs):
    rows, ubs = [], []
    for vt in range(data.num_vehicle_types):
        rows.append([1.0 if k[0] == vt else 0.0 for k, _ in recs])
        ubs.append(float(data.vehicle_type(vt).num_available))
    return np.array(rows), np.array(ubs)


def _lp_duals(data, pool):
    """LP relaxation of the set partitioning; returns duals per client."""

    recs = _columns(pool)
    m, clients = _matrix(data, recs)
    vrows, vubs = _vehicle_rows(data, recs)
    costs = np.array([c for _, c in recs])
    res = linprog(
        c=costs,
        A_eq=m,
        b_eq=np.ones(len(clients)),
        A_ub=vrows,
        b_ub=vubs,
        bounds=(0.0, 1.0),
        method="highs",
        options={"time_limit": LP_TIME},
    )
    if not res.success or res.eqlin is None:
        return None, None
    duals = np.asarray(res.eqlin.marginals, dtype=float)
    return dict(zip(clients, duals)), float(res.fun)


def _solve_sp(data, pool, tl):
    recs = _columns(pool)
    m, clients = _matrix(data, recs)
    vrows, vubs = _vehicle_rows(data, recs)
    cons = [LinearConstraint(m, lb=np.ones(len(clients)), ub=np.ones(len(clients)))]
    for row, ub in zip(vrows, vubs):
        cons.append(LinearConstraint(row, lb=-np.inf, ub=ub))
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
        return None, None, len(recs), elapsed
    chosen = [recs[i] for i, v in enumerate(res.x) if v > 0.5]
    sol = NativeSolution(
        data, [NativeRoute(data, list(vis), vt) for (vt, vis), _ in chosen]
    )
    if not sol.is_feasible():
        return None, None, len(recs), elapsed
    keys = [_key(vt, vis) for (vt, vis), _ in chosen]
    cost = float(sum(r.distance() for r in sol.routes())) / SCALE
    return cost, keys, len(recs), elapsed


def _guided_instance(data, duals):
    """Re-price arcs by the duals; feasibility data is left untouched."""

    profiles = []
    clipped = 0
    for p in range(data.num_profiles):
        dm = np.array(data.distance_matrix(p), dtype=np.int64)
        pi = np.zeros(data.num_locations, dtype=float)
        for node, value in duals.items():
            pi[node] = value
        adj = dm.astype(float) - 0.5 * (pi[:, None] + pi[None, :])
        clipped += int((adj < 0).sum())
        guided = np.maximum(adj, 0.0).round().astype(np.int64)
        # PyVRP requires zero diagonals; the dual shift can lift them off zero
        np.fill_diagonal(guided, 0)
        profiles.append(guided)
    return data.replace(distance_matrices=profiles), clipped


def _harvest(true_data, pool, solutions) -> int:
    """Add routes to the pool, always priced with true distances."""

    added = 0
    for sol in solutions:
        for r in sol.routes():
            k = _key(r.vehicle_type(), tuple(r.visits()))
            if k not in pool:
                pool[k] = _true_cost(true_data, k)
                added += 1
    return added


def _run_hgs(data, params, seed, iters):
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
    return res.best, pop, int(res.num_iterations)


def _bks(instance_id):
    path = BKS_DIR / f"{instance_id}.sol"
    for line in path.read_text().splitlines():
        if line.lower().startswith("cost"):
            return float(line.split()[-1]) / SCALE
    return None


def _run_instance(instance_id: str) -> dict[str, Any]:
    true_data = read(
        str(INSTANCE_DIR / f"{instance_id}.vrp"), round_func=ROUND_FUNC
    )
    params = SolveParams()
    started = perf_counter()
    log: list[dict[str, Any]] = []

    # --- seed pool: reuse the first SEED_RUNS independent runs from D6 ---
    pool: dict[str, float] = {}
    seed_best = []
    for seed in range(1, SEED_RUNS + 1):
        rec = json.loads(
            (D6_RUNS / f"{instance_id}__s{seed}.json").read_text(encoding="utf-8")
        )
        seed_best.append(rec["best_cost"])
        for k in rec["routes"]:
            pool.setdefault(k, _true_cost(true_data, k))
    pool_after_seeds = len(pool)

    cost, keys, cols, milp_s = _solve_sp(true_data, pool, MILP_TIME)
    log.append(
        {"phase": "seed_pool", "runs": SEED_RUNS, "columns": cols,
         "sp_cost": cost, "milp_seconds": round(milp_s, 2)}
    )

    guided_keys_seen: set[str] = set()
    for rnd in range(GUIDED_ROUNDS):
        duals, lp_obj = _lp_duals(true_data, pool)
        if duals is None:
            log.append({"phase": f"guided{rnd}", "error": "LP_FAILED"})
            break
        guided, clipped = _guided_instance(true_data, duals)
        gseed = 900_000 + rnd * 13 + 1
        gbest, gpop, giters = _run_hgs(guided, params, gseed, ITERS)

        before = len(pool)
        fresh = [x for x in gpop if x.is_feasible()] + [gbest]
        # every route is re-priced with true distances inside _harvest
        added = _harvest(true_data, pool, fresh)
        for sol in fresh:
            for r in sol.routes():
                guided_keys_seen.add(_key(r.vehicle_type(), tuple(r.visits())))

        cost, keys, cols, milp_s = _solve_sp(true_data, pool, MILP_TIME)
        log.append(
            {
                "phase": f"guided{rnd}",
                "lp_objective": round(lp_obj / SCALE, 4) if lp_obj else None,
                "arcs_clipped_to_zero": clipped,
                "guided_iterations": giters,
                "pool_before": before,
                "new_columns": added,
                "columns": cols,
                "sp_cost": cost,
                "milp_seconds": round(milp_s, 2),
            }
        )

    bks = _bks(instance_id)
    final_keys = set(keys or [])
    # a3 credit: did the final partition select a column only guided rounds made?
    a2_keys: set[str] = set()
    for seed in range(1, 11):
        rec = json.loads(
            (D6_RUNS / f"{instance_id}__s{seed}.json").read_text(encoding="utf-8")
        )
        a2_keys |= set(rec["routes"])
    guided_only_selected = sorted(final_keys & (guided_keys_seen - a2_keys))

    return {
        "instance_id": instance_id,
        "a3_cost": cost,
        "bks": bks,
        "a3_error_pct": (cost - bks) / bks * 100 if (bks and cost) else None,
        "seed_runs_best": min(seed_best),
        "pool_after_seeds": pool_after_seeds,
        "pool_final": len(pool),
        "guided_only_columns_selected": len(guided_only_selected),
        "guided_only_examples": guided_only_selected[:3],
        "total_iterations": (SEED_RUNS + GUIDED_ROUNDS) * ITERS,
        "cpu_seconds": round(perf_counter() - started, 1),
        "log": log,
    }


def main() -> int:
    print(f"A3 on {len(INSTANCES)} instances, "
          f"{SEED_RUNS} seed runs + {GUIDED_ROUNDS} guided rounds", flush=True)
    rows = []
    with ProcessPoolExecutor(max_workers=5) as pool:
        for row in pool.map(_run_instance, INSTANCES):
            rows.append(row)
            print(
                f"  {row['instance_id']:<7} A3={row['a3_cost']:>10.3f} "
                f"vsBKS={row['a3_error_pct']:+.4f}% "
                f"pool {row['pool_after_seeds']}->{row['pool_final']} "
                f"guidedColsSelected={row['guided_only_columns_selected']} "
                f"cpu={row['cpu_seconds']:.0f}s",
                flush=True,
            )
    (OUT / "a3_results.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    flat = [{k: v for k, v in r.items() if k not in ("log", "guided_only_examples")}
            for r in rows]
    with (OUT / "a3_raw_runs.csv").open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=list(flat[0].keys()))
        w.writeheader()
        w.writerows(flat)
    print()
    print(json.dumps({"mean_error_pct": round(
        statistics.mean(r["a3_error_pct"] for r in rows), 4)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
