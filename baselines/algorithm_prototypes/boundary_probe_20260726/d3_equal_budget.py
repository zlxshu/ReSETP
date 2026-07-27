"""D3: does the mother survive an equal-budget comparison?

The sealed P1 table reports MV-HGS-SP beating the PyVRP-HGS mother 264/16/0,
but its own `cpu_ratio` column is 1.47-2.00: the hybrid ran 1.5-2x longer than
the baseline it beat.  That is the first thing a referee asks of any hybrid, so
it has to be settled before deciding what to build.

Three arms per instance, paired by seed and by total iteration budget:

  hybrid        mother(3000 iters) + 4 epochs x 800 iters = 6200 iterations
  mother_equal  a single HGS run with the same 6200-iteration budget
  mother_short  a single HGS run with 3000 iterations, i.e. the arm the sealed
                table actually compared against

Iteration-based stopping makes the arms exactly comparable and removes the
wall-clock noise that confounded D1.  CPU is still recorded, because equal
iterations is not equal CPU: the hybrid pays extra for the MILP and for
rebuilding the population each epoch, and that has to be disclosed either way.
"""

from __future__ import annotations

import csv
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
FOUNDATION = ROOT / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
INSTANCE_DIR = FOUNDATION / "sources/normalised_instances"
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
K_MOTHER = 4000
K_EPOCH = 2000
ITER_MOTHER = 3000
ITER_EPOCH = 800
MAX_EPOCHS = 4
STALL_EPOCHS = 2
ELITE_COUNT = 8
POOL_CAP = 600
SP_TIME = 10.0
EPS = 1.0e-6
TOTAL_ITERS = ITER_MOTHER + MAX_EPOCHS * ITER_EPOCH  # 6200


def _build(data, rng, params, initial):
    neighbours = compute_neighbours(data, params.neighbourhood)
    ls = LocalSearch(data, rng, neighbours)
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
    algo = GeneticAlgorithm(
        data, pm, rng, pop, ls, crossover, initial, params.genetic
    )
    return algo, pop, pm


def _cost(s) -> float:
    return float(sum(r.distance() for r in s.routes()))


def _key(s):
    return tuple(
        sorted((r.vehicle_type(), tuple(r.visits())) for r in s.routes())
    )


def _harvest(pop, pm, best):
    ce = pm.cost_evaluator()
    feasible = [x for x in pop if x.is_feasible()]
    feasible.append(best)
    uniq = {}
    for s in feasible:
        uniq.setdefault(_key(s), s)
    return sorted(uniq.values(), key=ce.cost)[:ELITE_COUNT]


def _pool_add(pool, sols) -> None:
    for s in sols:
        for r in s.routes():
            pool.setdefault(
                (r.vehicle_type(), tuple(r.visits())), float(r.distance())
            )


def _solve_sp(data, pool, tl):
    recs = sorted(pool.items(), key=lambda i: i[1])[:POOL_CAP]
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
    res = milp(
        c=np.array([c for _, c in recs]),
        integrality=np.ones(len(recs)),
        bounds=Bounds(np.zeros(len(recs)), np.ones(len(recs))),
        constraints=cons,
        options={"time_limit": float(tl)},
    )
    if res.x is None:
        return None
    chosen = [recs[i] for i, v in enumerate(res.x) if v > 0.5]
    sol = NativeSolution(
        data, [NativeRoute(data, list(vis), vt) for (vt, vis), _ in chosen]
    )
    return sol if sol.is_feasible() else None


def _run(args) -> dict[str, Any]:
    instance_id, seed, arm = args
    data = read(str(INSTANCE_DIR / f"{instance_id}.vrp"), round_func=ROUND_FUNC)
    params = SolveParams()
    rng = RandomNumberGenerator(seed=int(seed))
    started = perf_counter()
    initial = [
        NativeSolution.make_random(data, rng)
        for _ in range(params.population.min_pop_size)
    ]

    if arm in {"mother_equal", "mother_short"}:
        budget = TOTAL_ITERS if arm == "mother_equal" else ITER_MOTHER
        algo, _pop, _pm = _build(data, rng, params, initial)
        res = algo.run(
            MultipleCriteria([NoImprovement(K_MOTHER), MaxIterations(budget)]),
            collect_stats=False,
            display=False,
        )
        return {
            "instance_id": instance_id,
            "seed": seed,
            "arm": arm,
            "n_clients": data.num_clients,
            "iterations_budget": budget,
            "iterations_run": int(res.num_iterations),
            "final_cost": _cost(res.best) / SCALE,
            "final_source": "mother",
            "cpu_seconds": round(perf_counter() - started, 1),
        }

    algo, pop, pm = _build(data, rng, params, initial)
    res = algo.run(
        MultipleCriteria([NoImprovement(K_MOTHER), MaxIterations(ITER_MOTHER)]),
        collect_stats=False,
        display=False,
    )
    best, best_raw = res.best, _cost(res.best)
    source = "mother"
    iters = int(res.num_iterations)
    pool: dict = {}
    elites = _harvest(pop, pm, res.best)
    _pool_add(pool, elites)
    stall = 0
    for e in range(MAX_EPOCHS):
        improved = False
        sp = _solve_sp(data, pool, SP_TIME)
        if sp is not None and _cost(sp) < best_raw - EPS:
            best, best_raw, source, improved = sp, _cost(sp), f"sp{e}", True
        warm = {}
        for s in [best, *elites]:
            warm.setdefault(_key(s), s)
        wl = list(warm.values())
        erng = RandomNumberGenerator(seed=int(seed) + 1009 * (e + 1))
        fill = [
            NativeSolution.make_random(data, erng)
            for _ in range(max(0, params.population.min_pop_size - len(wl)))
        ]
        algo, pop, pm = _build(data, erng, params, [*wl, *fill])
        er = algo.run(
            MultipleCriteria([NoImprovement(K_EPOCH), MaxIterations(ITER_EPOCH)]),
            collect_stats=False,
            display=False,
        )
        iters += int(er.num_iterations)
        if _cost(er.best) < best_raw - EPS:
            best, best_raw, source, improved = er.best, _cost(er.best), f"hgs{e}", True
        elites = _harvest(pop, pm, er.best)
        _pool_add(pool, elites)
        stall = 0 if improved else stall + 1
        if stall >= STALL_EPOCHS:
            break

    return {
        "instance_id": instance_id,
        "seed": seed,
        "arm": arm,
        "n_clients": data.num_clients,
        "iterations_budget": TOTAL_ITERS,
        "iterations_run": iters,
        "final_cost": best_raw / SCALE,
        "final_source": source,
        "cpu_seconds": round(perf_counter() - started, 1),
    }


def main() -> int:
    instances = ["PR16A", "PR16B", "PR20A", "PR24A", "PR17B", "PR21B"]
    arms = ["hybrid", "mother_equal", "mother_short"]
    jobs = [(i, 1, a) for a in arms for i in instances]
    print(f"running {len(jobs)} units on 6 workers", flush=True)
    rows = []
    with ProcessPoolExecutor(max_workers=6) as pool:
        for row in pool.map(_run, jobs):
            rows.append(row)
            print(
                f"  {row['instance_id']:<7} {row['arm']:<13} "
                f"iters={row['iterations_run']:>5}/{row['iterations_budget']:<5} "
                f"cost={row['final_cost']:>10.3f} src={row['final_source']:<7} "
                f"cpu={row['cpu_seconds']:.0f}s",
                flush=True,
            )
    with (OUT / "d3_raw_runs.csv").open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    (OUT / "d3_raw_runs.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
