#!/usr/bin/env python3
"""Run one frozen MDA-ILS-VNS late-stage route-VNS arm."""

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

from run_worker import EXPECTED_PYVRP, route_payload
from scheduled_route_vns import LATE_STAGE_ARMS, ScheduledRouteVNS
from selective_route_vns import (
    CONFIGS,
    SelectiveRouteVNS,
    build_node_search,
    build_route_search,
    solve_params,
)

SCHEDULED_RNG_SALT = 0x5A17C3D1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", choices=sorted(LATE_STAGE_ARMS), required=True)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    stop = parser.add_mutually_exclusive_group(required=True)
    stop.add_argument("--runtime", type=float)
    stop.add_argument("--iterations", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    installed = importlib.metadata.version("pyvrp")
    if installed != EXPECTED_PYVRP:
        raise RuntimeError(f"expected PyVRP {EXPECTED_PYVRP}, found {installed}")
    arm = LATE_STAGE_ARMS[args.config]
    config = CONFIGS["swapstar_best"]
    params = solve_params(config)
    data = pyvrp.read(args.instance, round_func="exact")
    rng = RandomNumberGenerator(seed=args.seed)
    penalties = PenaltyManager.init_from(data, params.penalty)
    node_search = build_node_search(data, rng, params)
    record_route_search = build_route_search(
        data,
        rng,
        params,
        config.route_operators,
    )
    if record_route_search is None:
        raise RuntimeError("SwapStar route search was not built")
    scheduled_rng = None
    if arm.period is None:
        search = SelectiveRouteVNS(node_search, record_route_search)
    else:
        scheduled_rng = RandomNumberGenerator(seed=args.seed ^ SCHEDULED_RNG_SALT)
        scheduled_route_search = build_route_search(
            data,
            scheduled_rng,
            params,
            config.route_operators,
        )
        if scheduled_route_search is None:
            raise RuntimeError("scheduled SwapStar search was not built")
        search = ScheduledRouteVNS(
            node_search,
            record_route_search,
            scheduled_route_search,
            arm,
            runtime_budget=args.runtime,
            iteration_budget=args.iterations,
        )
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
        "schema": "resetp.mda-ils-vns-late-stage-worker.v1",
        "working_name": "MDA-ILS-VNS",
        "config": args.config,
        "late_stage_arm": asdict(arm),
        "mother_config": asdict(config),
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
        "scheduled_rng_state": (
            None
            if scheduled_rng is None
            else [int(value) for value in scheduled_rng.state()]
        ),
        "search_diagnostics": search.diagnostics(),
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
