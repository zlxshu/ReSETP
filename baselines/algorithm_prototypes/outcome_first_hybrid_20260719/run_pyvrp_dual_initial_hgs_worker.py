#!/usr/bin/env python3
"""Run PyVRP HGS with both the common and ALNS-produced initial solution."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

from pyvrp import Solution
from pyvrp.GeneticAlgorithm import GeneticAlgorithm
from pyvrp.PenaltyManager import PenaltyManager
from pyvrp.Population import Population
from pyvrp._pyvrp import RandomNumberGenerator
from pyvrp.crossover import selective_route_exchange
from pyvrp.diversity import broken_pairs_distance
from pyvrp.search import (
    NODE_OPERATORS,
    ROUTE_OPERATORS,
    LocalSearch,
    compute_neighbours,
)
from pyvrp.solve import SolveParams
from pyvrp.stop import MaxRuntime


REPO = Path(__file__).resolve().parents[3]
BASE_WORKER_PATH = (
    REPO
    / "baselines/algorithm_prototypes/algo_reset_20260719/"
    "run_pyvrp_route_core_worker.py"
)
SPEC = importlib.util.spec_from_file_location(
    "pyvrp_single_initial_worker_helpers",
    BASE_WORKER_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {BASE_WORKER_PATH}")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--scale", type=int, default=1000)
    parser.add_argument("--fixed-cost", type=int, required=True)
    parser.add_argument("--common-initial-routes", type=Path, required=True)
    parser.add_argument("--alns-initial-routes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if importlib.metadata.version("pyvrp") != "0.12.2":
        raise RuntimeError("dual-initial worker is frozen for PyVRP 0.12.2")
    model = BASE.build_model(args.bundle, args.scale, args.fixed_cost)
    data = model.data()
    common_routes = _read_routes(args.common_initial_routes)
    alns_routes = _read_routes(args.alns_initial_routes)
    common = Solution(data, common_routes)
    alns = Solution(data, alns_routes)
    if not common.is_feasible() or not alns.is_feasible():
        raise RuntimeError("both initial solutions must be feasible")

    params = SolveParams()
    rng = RandomNumberGenerator(seed=args.seed)
    neighbours = compute_neighbours(data, params.neighbourhood)
    local_search = LocalSearch(data, rng, neighbours)
    for operator in params.node_ops or NODE_OPERATORS:
        if operator.supports(data):
            local_search.add_node_operator(operator(data))
    for operator in params.route_ops or ROUTE_OPERATORS:
        if operator.supports(data):
            local_search.add_route_operator(operator(data))
    penalty_manager = PenaltyManager.init_from(data, params.penalty)
    population = Population(broken_pairs_distance, params.population)
    initial_solutions = [common, alns]
    initial_solutions.extend(
        Solution.make_random(data, rng)
        for _ in range(
            max(0, params.population.min_pop_size - len(initial_solutions))
        )
    )
    algorithm = GeneticAlgorithm(
        data,
        penalty_manager,
        rng,
        population,
        local_search,
        selective_route_exchange,
        initial_solutions,
        params.genetic,
    )
    started = time.perf_counter()
    result = algorithm.run(
        MaxRuntime(args.seconds),
        collect_stats=True,
        display=False,
        display_interval=params.display_interval,
    )
    payload = {
        "pyvrp_version": importlib.metadata.version("pyvrp"),
        "seed": args.seed,
        "time_limit_seconds": args.seconds,
        "elapsed_seconds": time.perf_counter() - started,
        "feasible": bool(result.best.is_feasible()),
        "scaled_cost": (
            int(result.cost())
            if math.isfinite(float(result.cost()))
            else None
        ),
        "routes": BASE.routes_from(result.best),
        "initial_route_counts": {
            "common": len(common_routes),
            "project_alns": len(alns_routes),
        },
        "initial_solution_count": len(initial_solutions),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0 if payload["feasible"] else 1


def _read_routes(path: Path) -> list[list[int]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        [int(value) for value in route]
        for route in payload["routes"]
    ]


if __name__ == "__main__":
    raise SystemExit(main())
