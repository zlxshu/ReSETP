"""D1: is the set-partitioning step actually contributing anything?

The frozen public-benchmark engine is: mother HGS, harvest elites into a route
pool, then up to four epochs of [solve SP over the pool -> warm-restart HGS].
The published table credits the fusion, but the recorded columns never say
whether the SP step succeeded, whether its solution ever beat the incumbent, or
whether that improvement survived.  If the MILP fails or is never better, the
gain is coming from warm restarts alone -- which would make the "fusion" a
label rather than a mechanism.

This runs a faithful instrumented copy of the engine (identical constants, RNG
streams and stopping rules) plus a control arm with the SP step disabled.
Everything else is byte-identical between arms, and the SP call consumes no
RNG, so the arms are directly comparable.

Recorded per epoch: pool size, MILP success, how many columns it selected, the
SP solution cost against the incumbent, and which source owns the incumbent at
every point.  The final attribution says whether the answer came from the
mother run, from an SP solve, or from a warm-restarted HGS epoch.
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

from pyvrp import ProblemData, read  # noqa: E402
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
from pyvrp.stop import MaxRuntime, MultipleCriteria, NoImprovement  # noqa: E402

# Frozen constants, copied verbatim from run_p1_formal_public.py.
ROUND_FUNC = "exact"
SCALE = 1000.0
K_MOTHER = 4000
CAP_MOTHER = 240.0
K_EPOCH = 2000
CAP_EPOCH = 60.0
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


def _solution_cost(solution) -> float:
    return float(sum(route.distance() for route in solution.routes()))


def _solution_key(solution):
    return tuple(
        sorted(
            (route.vehicle_type(), tuple(route.visits()))
            for route in solution.routes()
        )
    )


def _harvest_elites(population, penalty_manager, best):
    cost_evaluator = penalty_manager.cost_evaluator()
    feasible = [item for item in population if item.is_feasible()]
    feasible.append(best)
    unique = {}
    for native in feasible:
        unique.setdefault(_solution_key(native), native)
    return sorted(unique.values(), key=cost_evaluator.cost)[:ELITE_COUNT]


def _pool_add(pool, solutions) -> None:
    for solution in solutions:
        for route in solution.routes():
            pool.setdefault(
                (route.vehicle_type(), tuple(route.visits())),
                float(route.distance()),
            )


def _pool_coverage(data, pool) -> dict[str, Any]:
    """Can the capped pool cover every client at all?"""

    records = sorted(pool.items(), key=lambda item: item[1])[:POOL_CAP]
    clients = set(range(data.num_depots, data.num_locations))
    covered_capped = set()
    for (_, visits), _ in records:
        covered_capped.update(visits)
    covered_full = set()
    for (_, visits) in pool:
        covered_full.update(visits)
    return {
        "pool_total": len(pool),
        "pool_capped": len(records),
        "clients": len(clients),
        "clients_covered_by_capped_pool": len(covered_capped & clients),
        "clients_covered_by_full_pool": len(covered_full & clients),
        "capped_pool_can_cover_all": len(covered_capped & clients) == len(clients),
        "full_pool_can_cover_all": len(covered_full & clients) == len(clients),
        "mean_route_len_capped": round(
            float(np.mean([len(v) for (_, v), _ in records])), 3
        )
        if records
        else None,
        "mean_route_len_full": round(
            float(np.mean([len(v) for (_, v) in pool])), 3
        )
        if pool
        else None,
    }


def _solve_sp(data, pool, time_limit):
    records = sorted(pool.items(), key=lambda item: item[1])[:POOL_CAP]
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
    stats = {
        "milp_success": bool(result.success),
        "milp_status": int(getattr(result, "status", -1)),
        "pool_size": len(records),
        "selected": 0,
        "infeasible_solution": False,
    }
    if result.x is None:
        return None, stats
    chosen = [records[i] for i, value in enumerate(result.x) if value > 0.5]
    stats["selected"] = len(chosen)
    routes = [NativeRoute(data, list(visits), vt) for (vt, visits), _ in chosen]
    solution = NativeSolution(data, routes)
    if not solution.is_feasible():
        stats["infeasible_solution"] = True
        return None, stats
    return solution, stats


def _run_unit(args) -> dict[str, Any]:
    instance_id, seed, sp_enabled = args
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
    stop = MultipleCriteria([NoImprovement(K_MOTHER), MaxRuntime(CAP_MOTHER)])
    result = algorithm.run(stop, collect_stats=False, display=False)
    mother_cpu = perf_counter() - started
    mother_cost = _solution_cost(result.best) / SCALE
    mother_iterations = int(result.num_iterations)

    global_best_raw = mother_cost * SCALE
    best_solution = result.best
    best_source = "mother"
    pool: dict = {}
    elites = _harvest_elites(population, penalty_manager, result.best)
    _pool_add(pool, elites)

    epoch_log: list[dict[str, Any]] = []
    sp_improvements = 0
    epoch_improvements = 0
    stall = 0
    epochs_run = 0

    for epoch_index in range(MAX_EPOCHS):
        improved = False
        coverage = _pool_coverage(data, pool)
        if sp_enabled:
            sp_started = perf_counter()
            sp_solution, sp_stats = _solve_sp(data, pool, SP_TIME)
            sp_seconds = perf_counter() - sp_started
        else:
            sp_solution, sp_stats, sp_seconds = None, {"milp_success": None}, 0.0

        sp_cost = None
        sp_beat_incumbent = False
        if sp_solution is not None:
            sp_cost_raw = _solution_cost(sp_solution)
            sp_cost = sp_cost_raw / SCALE
            if sp_cost_raw < global_best_raw - EPS:
                global_best_raw = sp_cost_raw
                best_solution = sp_solution
                best_source = f"sp_epoch{epoch_index}"
                improved = True
                sp_beat_incumbent = True
                sp_improvements += 1

        warm = [best_solution, *elites]
        unique_warm = {}
        for native in warm:
            unique_warm.setdefault(_solution_key(native), native)
        warm_list = list(unique_warm.values())
        epoch_rng = RandomNumberGenerator(seed=int(seed) + 1009 * (epoch_index + 1))
        random_fill = [
            NativeSolution.make_random(data, epoch_rng)
            for _ in range(max(0, params.population.min_pop_size - len(warm_list)))
        ]
        algorithm, population, penalty_manager = _build_algorithm(
            data, epoch_rng, params, [*warm_list, *random_fill]
        )
        epoch_stop = MultipleCriteria([NoImprovement(K_EPOCH), MaxRuntime(CAP_EPOCH)])
        epoch_result = algorithm.run(epoch_stop, collect_stats=False, display=False)
        epoch_cost_raw = _solution_cost(epoch_result.best)
        epoch_beat = False
        if epoch_cost_raw < global_best_raw - EPS:
            global_best_raw = epoch_cost_raw
            best_solution = epoch_result.best
            best_source = f"hgs_epoch{epoch_index}"
            improved = True
            epoch_beat = True
            epoch_improvements += 1
        elites = _harvest_elites(population, penalty_manager, epoch_result.best)
        _pool_add(pool, elites)
        epochs_run += 1

        epoch_log.append(
            {
                "epoch": epoch_index,
                **coverage,
                **sp_stats,
                "sp_seconds": round(sp_seconds, 3),
                "sp_cost": sp_cost,
                "sp_beat_incumbent": sp_beat_incumbent,
                "epoch_cost": epoch_cost_raw / SCALE,
                "epoch_beat_incumbent": epoch_beat,
                "incumbent_after": global_best_raw / SCALE,
                "incumbent_source_after": best_source,
            }
        )
        stall = 0 if improved else stall + 1
        if stall >= STALL_EPOCHS:
            break

    hybrid_cpu = perf_counter() - started
    hybrid_cost = global_best_raw / SCALE
    return {
        "instance_id": instance_id,
        "seed": seed,
        "arm": "sp_on" if sp_enabled else "sp_off",
        "n_clients": data.num_clients,
        "mother_cost": mother_cost,
        "mother_iterations": mother_iterations,
        "mother_cpu_seconds": round(mother_cpu, 2),
        "final_cost": hybrid_cost,
        "final_source": best_source,
        "improvement_percent": 100.0 * (mother_cost - hybrid_cost) / mother_cost,
        "epochs_run": epochs_run,
        "sp_improvements": sp_improvements,
        "epoch_improvements": epoch_improvements,
        "total_cpu_seconds": round(hybrid_cpu, 2),
        "epoch_log": epoch_log,
    }


def main() -> int:
    instances = ["PR16A", "PR16B", "PR20A", "PR24A", "PR17B", "PR21B"]
    seed = 1
    jobs = [(i, seed, True) for i in instances] + [
        (i, seed, False) for i in instances
    ]
    print(f"running {len(jobs)} units on 6 workers", flush=True)
    rows = []
    with ProcessPoolExecutor(max_workers=6) as pool:
        for row in pool.map(_run_unit, jobs):
            rows.append(row)
            print(
                f"  {row['instance_id']:<7} {row['arm']:<7} "
                f"mother={row['mother_cost']:>10.3f} final={row['final_cost']:>10.3f} "
                f"imp={row['improvement_percent']:>+6.3f}% "
                f"src={row['final_source']:<14} "
                f"spWins={row['sp_improvements']} hgsWins={row['epoch_improvements']} "
                f"cpu={row['total_cpu_seconds']:.0f}s",
                flush=True,
            )

    (OUT / "d1_epoch_logs.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    flat = [{k: v for k, v in r.items() if k != "epoch_log"} for r in rows]
    with (OUT / "d1_raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(flat[0].keys()))
        writer.writeheader()
        writer.writerows(flat)
    return 0


if __name__ == "__main__":
    sys.exit(main())
