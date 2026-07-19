#!/usr/bin/env python3
"""Emit one tiny PyVRP 0.12.2 HGS supplier solution."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import pyvrp
from pyvrp.stop import FirstFeasible, MaxRuntime, MultipleCriteria


EXPECTED_VERSION = "0.12.2"
MAX_RUNTIME_SECONDS = 5.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    version = importlib.metadata.version("pyvrp")
    if version != EXPECTED_VERSION:
        raise RuntimeError(
            f"expected PyVRP {EXPECTED_VERSION}, found {version}"
        )
    data = pyvrp.read(args.instance, round_func="exact")
    result = pyvrp.solve(
        data,
        stop=MultipleCriteria(
            [FirstFeasible(), MaxRuntime(MAX_RUNTIME_SECONDS)]
        ),
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
        "schema": "resetp.remix-hgs-supplier-bridge.v1",
        "instance": args.instance.name,
        "instance_sha256": hashlib.sha256(
            args.instance.read_bytes()
        ).hexdigest(),
        "pyvrp_version": version,
        "round_func": "exact",
        "seed": args.seed,
        "stop_rule": "first_feasible_or_5_seconds",
        "max_runtime_seconds": MAX_RUNTIME_SECONDS,
        "iterations_completed": result.num_iterations,
        "complete": result.best.is_complete(),
        "feasible": result.best.is_feasible(),
        "distance": result.best.distance(),
        "duration": result.best.duration(),
        "num_clients": result.best.num_clients(),
        "num_routes": result.best.num_routes(),
        "routes": routes,
        "runtime_s_non_comparable": result.runtime,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
