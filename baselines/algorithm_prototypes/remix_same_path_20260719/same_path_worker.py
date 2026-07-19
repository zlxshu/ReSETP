#!/usr/bin/env python3
"""Run one isolated arm of the ReMIX disabled-path equivalence gate."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pyvrp

from remix_shell import ReMixConfig, ReMixCounters, solve_mother, solve_remix


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("mother", "hybrid_disabled", "hybrid_zero_budget"),
        required=True,
    )
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    instance_bytes = args.instance.read_bytes()
    data = pyvrp.read(args.instance, round_func="exact")
    if args.mode == "mother":
        result = solve_mother(
            data,
            seed=args.seed,
            iterations=args.iterations,
        )
        counters = ReMixCounters()
    else:
        config = ReMixConfig(
            enabled=args.mode == "hybrid_zero_budget",
            component_budget=0,
        )
        result, counters = solve_remix(
            data,
            seed=args.seed,
            iterations=args.iterations,
            config=config,
        )

    route_records = [
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
    trace = [asdict(datum) for datum in result.stats]
    deterministic_payload = {
        "cost": result.cost(),
        "distance": result.best.distance(),
        "duration": result.best.duration(),
        "feasible": result.is_feasible(),
        "complete": result.best.is_complete(),
        "num_routes": result.best.num_routes(),
        "num_clients": result.best.num_clients(),
        "num_iterations": result.num_iterations,
        "routes": route_records,
        "iteration_trace": trace,
    }
    output = {
        "mode": args.mode,
        "seed": args.seed,
        "requested_iterations": args.iterations,
        "instance": args.instance.name,
        "instance_sha256": hashlib.sha256(instance_bytes).hexdigest(),
        "pyvrp_version": version("pyvrp"),
        "runtime_s_non_comparable": result.runtime,
        "component_counters": {
            **asdict(counters),
            "total_component_calls": counters.total_component_calls,
        },
        "deterministic_payload": deterministic_payload,
        "deterministic_signature_sha256": canonical_sha256(
            deterministic_payload
        ),
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

