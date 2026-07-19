#!/usr/bin/env python3
"""Run one isolated HGS or ILS core under a wall-clock budget."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import pyvrp
from pyvrp.stop import FirstFeasible, MaxRuntime, MultipleCriteria


VERSIONS = {"hgs": "0.12.2", "ils": "0.13.4"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", choices=tuple(VERSIONS), required=True)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--runtime", type=float, required=True)
    parser.add_argument("--first-feasible", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    installed = importlib.metadata.version("pyvrp")
    expected = VERSIONS[args.core]
    if installed != expected:
        raise RuntimeError(
            f"{args.core} expected PyVRP {expected}, found {installed}"
        )
    if args.runtime <= 0:
        raise ValueError("runtime must be positive")
    data = pyvrp.read(args.instance, round_func="exact")
    stop = MaxRuntime(args.runtime)
    if args.first_feasible:
        stop = MultipleCriteria([FirstFeasible(), stop])
    result = pyvrp.solve(
        data,
        stop=stop,
        seed=args.seed,
        collect_stats=True,
        display=False,
    )
    routes = [
        {
            "vehicle_type": route.vehicle_type(),
            "start_depot": route.start_depot(),
            "end_depot": route.end_depot(),
            "visits": list(route.visits()),
            "distance": route.distance(),
            "duration": route.duration(),
            "feasible": route.is_feasible(),
        }
        for route in result.best.routes()
    ]
    payload = {
        "schema": "resetp.remix-v13-core.v1",
        "core": args.core,
        "pyvrp_version": installed,
        "instance": args.instance.name,
        "instance_sha256": hashlib.sha256(
            args.instance.read_bytes()
        ).hexdigest(),
        "round_func": "exact",
        "seed": args.seed,
        "requested_runtime_seconds": args.runtime,
        "stop_at_first_feasible": args.first_feasible,
        "iterations_completed": result.num_iterations,
        "runtime_seconds": result.runtime,
        "complete": result.best.is_complete(),
        "feasible": result.best.is_feasible(),
        "distance": result.best.distance(),
        "duration": result.best.duration(),
        "num_clients": result.best.num_clients(),
        "num_routes": result.best.num_routes(),
        "routes": routes,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
