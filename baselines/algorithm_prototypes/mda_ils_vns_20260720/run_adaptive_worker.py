#!/usr/bin/env python3
"""Run one frozen MDA-ILS-VNS adaptive-control arm."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
from pathlib import Path

import pyvrp
from pyvrp import (
    IteratedLocalSearch,
    PenaltyManager,
    RandomNumberGenerator,
    Solution,
)
from pyvrp.stop import MaxIterations, MaxRuntime

from adaptive_ils import (
    ADAPTIVE_ARMS,
    AdaptiveIteratedLocalSearch,
    AdaptiveSearch,
)
from run_worker import EXPECTED_PYVRP, route_payload
from selective_route_vns import (
    CONFIGS,
    SelectiveRouteVNS,
    build_node_search,
    build_route_search,
    solve_params,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", choices=sorted(ADAPTIVE_ARMS), required=True)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    stop = parser.add_mutually_exclusive_group(required=True)
    stop.add_argument("--runtime", type=float)
    stop.add_argument("--iterations", type=int)
    parser.add_argument(
        "--collect-stats",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    installed = importlib.metadata.version("pyvrp")
    if installed != EXPECTED_PYVRP:
        raise RuntimeError(f"expected PyVRP {EXPECTED_PYVRP}, found {installed}")
    if args.runtime is not None and args.runtime <= 0:
        raise ValueError("runtime must be positive")
    if args.iterations is not None and args.iterations <= 0:
        raise ValueError("iterations must be positive")

    arm = ADAPTIVE_ARMS[args.config]
    mother_config = CONFIGS["swapstar_best"]
    params = solve_params(mother_config)
    data = pyvrp.read(args.instance, round_func="exact")
    rng = RandomNumberGenerator(seed=args.seed)
    penalties = PenaltyManager.init_from(data, params.penalty)
    record_search = SelectiveRouteVNS(
        build_node_search(data, rng, params),
        build_route_search(
            data,
            rng,
            params,
            mother_config.route_operators,
        ),
    )
    initial = record_search(
        Solution.make_random(data, rng),
        penalties.max_cost_evaluator(),
        exhaustive=True,
    )

    if args.config == "foundation":
        runner = IteratedLocalSearch(
            data,
            penalties,
            rng,
            record_search,
            initial,
            params.ils,
        )
        adaptive_search = None
    else:
        adaptive_search = AdaptiveSearch(
            data,
            rng,
            params,
            record_search,
            arm,
            runtime_budget=args.runtime,
            iteration_budget=args.iterations,
        )
        runner = AdaptiveIteratedLocalSearch(
            data,
            penalties,
            adaptive_search,
            initial,
            params.ils,
            adaptive_acceptance=arm.adaptive_acceptance,
        )

    stop = (
        MaxRuntime(args.runtime)
        if args.runtime is not None
        else MaxIterations(args.iterations)
    )
    result = runner.run(
        stop,
        collect_stats=args.collect_stats,
        display=False,
        display_interval=params.display_interval,
    )
    output = {
        "schema": "resetp.mda-ils-vns-adaptive-worker.v1",
        "working_name": "MDA-ILS-VNS",
        "config": args.config,
        "adaptive_arm": asdict(arm),
        "mother_config": asdict(mother_config),
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
        "search_diagnostics": (
            record_search.diagnostics()
            if adaptive_search is None
            else adaptive_search.diagnostics()
        ),
        "runner_diagnostics": (
            {"adaptive_acceptance": False, "acceptance": None}
            if adaptive_search is None
            else runner.diagnostics()
        ),
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
