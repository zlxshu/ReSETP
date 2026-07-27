"""D9 phase 1 only: 64,000-iteration runs on the two assault instances.

D8b showed that feeding iterations collapses the large-band error: at 20,000
iterations x 10 seeds, PR24A sits 0.84% and PR16B 0.83% above the 2013 BKS,
down from 2.16%/2.26% in the sealed table.  These two are the assault points:
if the 2013 large-instance BKS is itself around 1% from optimum, 64,000
iterations may cross it.  PR16A/PR20A stay at 20k for now (1.16%/1.32%).

Phase 2 (pooling + sparse set partitioning) runs separately in the morning via
the d8b solver, with the min(best-of-k, MILP incumbent) safeguard: D8b proved
a time-limited MILP on a 5,000-column pool can return an incumbent worse than
best-of-k, so the monotone claim only holds with the explicit min.

Each run also saves the best solution's route keys so tomorrow's cross-run
consensus diagnostic (candidate-alpha kill test) is free.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]
FOUNDATION = ROOT / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
INSTANCE_DIR = FOUNDATION / "sources/normalised_instances"
OUT = Path(__file__).resolve().parent
RUNS_DIR = OUT / "d9_runs"

from pyvrp import read
from pyvrp._pyvrp import RandomNumberGenerator, Solution as NativeSolution
from pyvrp.GeneticAlgorithm import GeneticAlgorithm
from pyvrp.PenaltyManager import PenaltyManager
from pyvrp.Population import Population
from pyvrp.crossover import ordered_crossover, selective_route_exchange
from pyvrp.diversity import broken_pairs_distance
from pyvrp.search import LocalSearch, compute_neighbours
from pyvrp.solve import SolveParams
from pyvrp.stop import MaxIterations, MultipleCriteria, NoImprovement

ROUND_FUNC = "exact"
SCALE = 1000.0
ITERS = 64_000
K_NOIMPROVE = 16_000        # same 0.25 patience ratio as D6/D8
INSTANCES = ["PR24A", "PR16B"]
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
    ), pop


def _key(route) -> str:
    return f"{route.vehicle_type()}|" + ",".join(str(v) for v in route.visits())


def _run(args):
    instance_id, seed = args
    target = RUNS_DIR / f"{instance_id}__s{seed}.json"
    if target.is_file():
        return json.loads(target.read_text(encoding="utf-8"))

    data = read(str(INSTANCE_DIR / f"{instance_id}.vrp"), round_func=ROUND_FUNC)
    params = SolveParams()
    started = perf_counter()
    rng = RandomNumberGenerator(seed=int(seed))
    initial = [
        NativeSolution.make_random(data, rng)
        for _ in range(params.population.min_pop_size)
    ]
    algo, pop = _build(data, rng, params, initial)
    res = algo.run(
        MultipleCriteria([NoImprovement(K_NOIMPROVE), MaxIterations(ITERS)]),
        collect_stats=False,
        display=False,
    )

    routes: dict[str, float] = {}
    def add(sol):
        for r in sol.routes():
            routes.setdefault(_key(r), float(r.distance()))

    add(res.best)
    for member in pop:
        if member.is_feasible():
            add(member)

    record = {
        "instance_id": instance_id,
        "seed": seed,
        "iterations": int(res.num_iterations),
        "best_cost": float(sum(r.distance() for r in res.best.routes())) / SCALE,
        "best_routes": [_key(r) for r in res.best.routes()],
        "routes": routes,
        "cpu_seconds": round(perf_counter() - started, 1),
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record))
    return record


def main() -> int:
    jobs = [(i, s) for i in INSTANCES for s in SEEDS]
    print(f"D9 phase 1: {len(jobs)} runs x {ITERS} iterations, 6 workers", flush=True)
    with ProcessPoolExecutor(max_workers=6) as pool:
        for rec in pool.map(_run, jobs):
            print(
                f"  {rec['instance_id']:<7} s{rec['seed']:<3} "
                f"best={rec['best_cost']:>10.3f} iters={rec['iterations']:>6} "
                f"routes={len(rec['routes']):>4} cpu={rec['cpu_seconds']:.0f}s",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
