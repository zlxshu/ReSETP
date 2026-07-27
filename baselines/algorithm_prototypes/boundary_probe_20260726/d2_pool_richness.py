"""D2: does the recombination step improve when the pool is not starved?

D1 showed the set-partitioning step is not broken -- it is starved.  Across the
four epochs the distinct-route pool reaches only 183-817 columns on 960-client
instances and 38 columns on a converged 360-client instance, because it is fed
from eight elites of a population that has largely converged, so the harvested
routes are near-duplicates.  When the pool finally does exceed the 600 cap, the
cheapest-600 rule drops the expensive routes that cover remote clients and the
partition becomes infeasible, so the step silently contributes nothing.

Three arms, identical in everything else:

  base       frozen behaviour: eight elites, cheapest-600 cap
  safecap    same harvest, but the incumbent's own routes are always retained
             so the partition can never become infeasible
  richpool   safecap plus harvesting every feasible member of the population
             rather than the top eight

Stopping is iteration-based here, not wall-clock, so the arms are exactly
paired for a given seed and any difference is the mechanism rather than machine
load.  The frozen wall-clock engine is what final confirmation must use; this is
a development probe.
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
ITER_MOTHER = 3000          # replaces the 240 s wall-clock cap, for pairing
ITER_EPOCH = 800            # replaces the 60 s epoch cap
MAX_EPOCHS = 4
STALL_EPOCHS = 2
ELITE_COUNT = 8
POOL_CAP = 600
SP_TIME = 10.0
EPS = 1.0e-6


def _build_algorithm(data, rng, params, initial):
    neighbours = compute_neighbours(data, params.neighbourhood)
    local_search = LocalSearch(data, rng, neighbours)
    for node_op in params.node_ops:
        if node_op.supports(data):
            local_search.add_node_operator(node_op(data))
    for route_op in params.route_ops:
        if route_op.supports(data):
            local_search.add_route_operator(route_op(data))
    penalty_manager = PenaltyManager.init_from(data, params.penalty)
    population = Population(broken_pairs_distance, params.population)
    crossover = (
        selective_route_exchange if data.num_vehicles > 1 else ordered_crossover
    )
    algorithm = GeneticAlgorithm(
        data, penalty_manager, rng, population, local_search, crossover,
        initial, params.genetic,
    )
    return algorithm, population, penalty_manager


def _cost(solution) -> float:
    return float(sum(route.distance() for route in solution.routes()))


def _key(solution):
    return tuple(
        sorted(
            (route.vehicle_type(), tuple(route.visits()))
            for route in solution.routes()
        )
    )


def _harvest(population, penalty_manager, best, harvest_all: bool):
    cost_evaluator = penalty_manager.cost_evaluator()
    feasible = [item for item in population if item.is_feasible()]
    feasible.append(best)
    unique = {}
    for native in feasible:
        unique.setdefault(_key(native), native)
    ranked = sorted(unique.values(), key=cost_evaluator.cost)
    return ranked if harvest_all else ranked[:ELITE_COUNT]


def _pool_add(pool, solutions) -> None:
    for solution in solutions:
        for route in solution.routes():
            pool.setdefault(
                (route.vehicle_type(), tuple(route.visits())),
                float(route.distance()),
            )


def _select_columns(pool, incumbent, safe_cap: bool):
    """Choose at most POOL_CAP columns for the MILP.

    The frozen rule keeps the cheapest POOL_CAP routes, which can drop the
    expensive routes that cover remote clients and leave no feasible partition
    at all.  The safe rule reserves seats for the incumbent's own routes first,
    so a feasible partition always exists, then fills the rest by cost.
    """

    ranked = sorted(pool.items(), key=lambda item: item[1])
    if not safe_cap:
        return ranked[:POOL_CAP]
    keep_keys = {
        (route.vehicle_type(), tuple(route.visits()))
        for route in incumbent.routes()
    }
    reserved = [item for item in ranked if item[0] in keep_keys]
    others = [item for item in ranked if item[0] not in keep_keys]
    room = max(0, POOL_CAP - len(reserved))
    return reserved + others[:room]


def _solve_sp(data, records, time_limit):
    clients = list(range(data.num_depots, data.num_locations))
    client_index = {client: index for index, client in enumerate(clients)}
    matrix = np.zeros((len(clients), len(records)), dtype=float)
    for column, ((_, visits), _) in enumerate(records):
        for visit in visits:
            matrix[client_index[visit], column] = 1.0
    costs = np.array([cost for _, cost in records], dtype=float)
    constraints = [
        LinearConstraint(matrix, lb=np.ones(len(clients)), ub=np.ones(len(clients)))
    ]
    for vt in range(data.num_vehicle_types):
        limit = data.vehicle_type(vt).num_available
        row = np.array([1.0 if key[0] == vt else 0.0 for key, _ in records])
        constraints.append(LinearConstraint(row, lb=-np.inf, ub=float(limit)))
    result = milp(
        c=costs,
        integrality=np.ones(len(records)),
        bounds=Bounds(np.zeros(len(records)), np.ones(len(records))),
        constraints=constraints,
        options={"time_limit": float(time_limit)},
    )
    stats = {"milp_success": bool(result.success), "columns": len(records), "selected": 0}
    if result.x is None:
        return None, stats
    chosen = [records[i] for i, v in enumerate(result.x) if v > 0.5]
    stats["selected"] = len(chosen)
    solution = NativeSolution(
        data, [NativeRoute(data, list(visits), vt) for (vt, visits), _ in chosen]
    )
    if not solution.is_feasible():
        return None, stats
    return solution, stats


def _run_unit(args) -> dict[str, Any]:
    instance_id, seed, arm = args
    harvest_all = arm == "richpool"
    safe_cap = arm in {"safecap", "richpool"}

    data = read(str(INSTANCE_DIR / f"{instance_id}.vrp"), round_func=ROUND_FUNC)
    params = SolveParams()
    rng = RandomNumberGenerator(seed=int(seed))
    started = perf_counter()

    initial = [
        NativeSolution.make_random(data, rng)
        for _ in range(params.population.min_pop_size)
    ]
    algorithm, population, penalty_manager = _build_algorithm(
        data, rng, params, initial
    )
    result = algorithm.run(
        MultipleCriteria([NoImprovement(K_MOTHER), MaxIterations(ITER_MOTHER)]),
        collect_stats=False,
        display=False,
    )
    mother_cost = _cost(result.best) / SCALE
    best_solution, global_best_raw = result.best, mother_cost * SCALE
    best_source = "mother"

    pool: dict = {}
    harvested = _harvest(population, penalty_manager, result.best, harvest_all)
    _pool_add(pool, harvested)

    epoch_log, sp_wins, hgs_wins = [], 0, 0
    stall = epochs_run = 0
    for epoch_index in range(MAX_EPOCHS):
        improved = False
        records = _select_columns(pool, best_solution, safe_cap)
        sp_solution, sp_stats = _solve_sp(data, records, SP_TIME)
        sp_cost = None
        if sp_solution is not None:
            raw = _cost(sp_solution)
            sp_cost = raw / SCALE
            if raw < global_best_raw - EPS:
                global_best_raw, best_solution = raw, sp_solution
                best_source, improved = f"sp_epoch{epoch_index}", True
                sp_wins += 1

        warm = [best_solution, *harvested[:ELITE_COUNT]]
        unique_warm = {}
        for native in warm:
            unique_warm.setdefault(_key(native), native)
        warm_list = list(unique_warm.values())
        epoch_rng = RandomNumberGenerator(seed=int(seed) + 1009 * (epoch_index + 1))
        random_fill = [
            NativeSolution.make_random(data, epoch_rng)
            for _ in range(max(0, params.population.min_pop_size - len(warm_list)))
        ]
        algorithm, population, penalty_manager = _build_algorithm(
            data, epoch_rng, params, [*warm_list, *random_fill]
        )
        epoch_result = algorithm.run(
            MultipleCriteria([NoImprovement(K_EPOCH), MaxIterations(ITER_EPOCH)]),
            collect_stats=False,
            display=False,
        )
        raw = _cost(epoch_result.best)
        if raw < global_best_raw - EPS:
            global_best_raw, best_solution = raw, epoch_result.best
            best_source, improved = f"hgs_epoch{epoch_index}", True
            hgs_wins += 1
        harvested = _harvest(
            population, penalty_manager, epoch_result.best, harvest_all
        )
        _pool_add(pool, harvested)
        epochs_run += 1
        epoch_log.append(
            {
                "epoch": epoch_index,
                "pool_total": len(pool),
                **sp_stats,
                "sp_cost": sp_cost,
                "epoch_cost": raw / SCALE,
                "incumbent_after": global_best_raw / SCALE,
                "source_after": best_source,
            }
        )
        stall = 0 if improved else stall + 1
        if stall >= STALL_EPOCHS:
            break

    return {
        "instance_id": instance_id,
        "seed": seed,
        "arm": arm,
        "n_clients": data.num_clients,
        "mother_cost": mother_cost,
        "final_cost": global_best_raw / SCALE,
        "final_source": best_source,
        "improvement_percent": 100.0 * (mother_cost - global_best_raw / SCALE) / mother_cost,
        "final_pool_size": len(pool),
        "sp_wins": sp_wins,
        "hgs_wins": hgs_wins,
        "epochs_run": epochs_run,
        "cpu_seconds": round(perf_counter() - started, 1),
        "epoch_log": epoch_log,
    }


def main() -> int:
    instances = ["PR16A", "PR16B", "PR20A", "PR24A", "PR17B", "PR21B"]
    arms = ["base", "safecap", "richpool"]
    jobs = [(i, 1, a) for a in arms for i in instances]
    print(f"running {len(jobs)} units on 6 workers", flush=True)
    rows = []
    with ProcessPoolExecutor(max_workers=6) as pool:
        for row in pool.map(_run_unit, jobs):
            rows.append(row)
            print(
                f"  {row['instance_id']:<7} {row['arm']:<9} "
                f"mother={row['mother_cost']:>10.3f} final={row['final_cost']:>10.3f} "
                f"imp={row['improvement_percent']:>+6.3f}% pool={row['final_pool_size']:>5} "
                f"src={row['final_source']:<13} sp={row['sp_wins']} hgs={row['hgs_wins']} "
                f"cpu={row['cpu_seconds']:.0f}s",
                flush=True,
            )
    (OUT / "d2_epoch_logs.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    flat = [{k: v for k, v in r.items() if k != "epoch_log"} for r in rows]
    with (OUT / "d2_raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(flat[0].keys()))
        writer.writeheader()
        writer.writerows(flat)
    return 0


if __name__ == "__main__":
    sys.exit(main())
