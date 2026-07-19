#!/usr/bin/env python3
"""Run one frozen arm from the MDA-ILS-VNS parameter race."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any

import pyvrp
from pyvrp import (
    IteratedLocalSearch,
    PenaltyManager,
    RandomNumberGenerator,
    Solution,
)
from pyvrp.stop import MaxIterations, MaxRuntime

from racing_configs import RACE_CONFIGS
from selective_route_vns import (
    SelectiveRouteVNS,
    build_node_search,
    build_route_search,
    solve_params,
)


EXPECTED_PYVRP = "0.13.4"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        choices=sorted(RACE_CONFIGS),
        required=True,
    )
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    stop = parser.add_mutually_exclusive_group(required=True)
    stop.add_argument("--runtime", type=float)
    stop.add_argument("--iterations", type=int)
    return parser.parse_args()


def route_payload(route: pyvrp.Route) -> dict[str, Any]:
    return {
        "vehicle_type": int(route.vehicle_type()),
        "start_depot": int(route.start_depot()),
        "end_depot": int(route.end_depot()),
        "visits": [int(client) for client in route.visits()],
        "distance": int(route.distance()),
        "duration": int(route.duration()),
        "feasible": bool(route.is_feasible()),
    }


def main() -> int:
    args = parse_args()
    installed = importlib.metadata.version("pyvrp")
    if installed != EXPECTED_PYVRP:
        raise RuntimeError(f"expected PyVRP {EXPECTED_PYVRP}, found {installed}")

    config = RACE_CONFIGS[args.config]
    params = solve_params(config)
    data = pyvrp.read(args.instance, round_func="exact")
    rng = RandomNumberGenerator(seed=args.seed)
    node_search = build_node_search(data, rng, params)
    route_search = build_route_search(
        data,
        rng,
        params,
        config.route_operators,
    )
    search = SelectiveRouteVNS(node_search, route_search)
    penalties = PenaltyManager.init_from(data, params.penalty)
    initial = search(
        Solution.make_random(data, rng),
        penalties.max_cost_evaluator(),
        exhaustive=True,
    )
    runner = IteratedLocalSearch(
        data,
        penalties,
        rng,
        search,
        initial,
        params.ils,
    )
    stop = (
        MaxRuntime(args.runtime)
        if args.runtime is not None
        else MaxIterations(args.iterations)
    )
    result = runner.run(stop, collect_stats=False, display=False)
    output = {
        "schema": "resetp.mda-ils-vns-parameter-race-worker.v1",
        "working_name": "MDA-ILS-VNS",
        "config": args.config,
        "config_payload": asdict(config),
        "pyvrp_version": installed,
        "instance": args.instance.name,
        "instance_sha256": hashlib.sha256(args.instance.read_bytes()).hexdigest(),
        "round_func": "exact",
        "seed": args.seed,
        "requested_runtime_seconds": args.runtime,
        "requested_iterations": args.iterations,
        "iterations_completed": int(result.num_iterations),
        "runtime_seconds": float(result.runtime),
        "cost": int(result.cost()),
        "distance": int(result.best.distance()),
        "duration": int(result.best.duration()),
        "complete": bool(result.best.is_complete()),
        "feasible": bool(result.best.is_feasible()),
        "num_clients": int(result.best.num_clients()),
        "num_routes": int(result.best.num_routes()),
        "routes": [route_payload(route) for route in result.best.routes()],
        "rng_state": [int(value) for value in rng.state()],
        "search_diagnostics": search.diagnostics(),
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
