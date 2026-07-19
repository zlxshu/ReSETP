#!/usr/bin/env python3
"""Run one isolated arm of the MPILS-MVNS-C2 G0 gate."""

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
    SolveParams,
)
from pyvrp.search import (
    LocalSearch,
    PerturbationManager,
    PerturbationParams,
    compute_neighbours,
)
from pyvrp.stop import MaxIterations

from c2_core import C2EventController, MechanismContext
from event_driven_ils import EventDrivenIteratedLocalSearch


EXPECTED_PYVRP = "0.13.4"
MODES = ("official", "clone_native", "clone_hooks")


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
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--iterations", type=int, required=True)
    parser.add_argument(
        "--collect-stats",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return parser.parse_args()


def build_local_search(
    data: pyvrp.ProblemData,
    rng: RandomNumberGenerator,
    params: SolveParams,
    *,
    perturbation: PerturbationParams | None = None,
) -> LocalSearch:
    neighbours = compute_neighbours(data, params.neighbourhood)
    manager = PerturbationManager(
        params.perturbation if perturbation is None else perturbation
    )
    search = LocalSearch(data, rng, neighbours, manager)
    for node_operator in params.node_ops:
        if node_operator.supports(data):
            search.add_node_operator(node_operator(data))
    for route_operator in params.route_ops:
        if route_operator.supports(data):
            search.add_route_operator(route_operator(data))
    return search


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
        raise RuntimeError(
            f"expected PyVRP {EXPECTED_PYVRP}, found {installed}"
        )
    if args.iterations <= 0:
        raise ValueError("iterations must be positive")

    data = pyvrp.read(args.instance, round_func="exact")
    params = SolveParams()
    rng = RandomNumberGenerator(seed=args.seed)
    base_search = build_local_search(data, rng, params)
    penalties = PenaltyManager.init_from(data, params.penalty)
    initial = base_search(
        Solution.make_random(data, rng),
        penalties.max_cost_evaluator(),
        exhaustive=True,
    )

    controller = None
    if args.mode == "official":
        runner = IteratedLocalSearch(
            data,
            penalties,
            rng,
            base_search,
            initial,
            params.ils,
        )
    else:
        if args.mode == "clone_hooks":
            controller = C2EventController(
                MechanismContext.from_public_v13(data),
                allow_replacement=False,
            )
        runner = EventDrivenIteratedLocalSearch(
            data,
            penalties,
            rng,
            base_search,
            initial,
            params.ils,
            event_hooks=controller,
        )

    result = runner.run(
        MaxIterations(args.iterations),
        collect_stats=args.collect_stats,
        display=False,
        display_interval=params.display_interval,
    )
    trace = (
        [asdict(datum) for datum in result.stats]
        if args.collect_stats
        else []
    )
    deterministic_payload = {
        "cost": result.cost(),
        "distance": int(result.best.distance()),
        "duration": int(result.best.duration()),
        "feasible": bool(result.best.is_feasible()),
        "complete": bool(result.best.is_complete()),
        "num_routes": int(result.best.num_routes()),
        "num_clients": int(result.best.num_clients()),
        "num_iterations": int(result.num_iterations),
        "routes": [
            route_payload(route) for route in result.best.routes()
        ],
        "iteration_trace": trace,
        "mother_rng_state": [int(value) for value in rng.state()],
    }
    output = {
        "schema": "resetp.mpils-mvns-c2-g0-worker.v1",
        "mode": args.mode,
        "seed": args.seed,
        "requested_iterations": args.iterations,
        "collect_stats": args.collect_stats,
        "instance": args.instance.name,
        "instance_sha256": hashlib.sha256(
            args.instance.read_bytes()
        ).hexdigest(),
        "pyvrp_version": installed,
        "runtime_main_loop_seconds": float(result.runtime),
        "deterministic_payload": deterministic_payload,
        "deterministic_signature_sha256": canonical_sha256(
            deterministic_payload
        ),
        "event_diagnostics": (
            controller.diagnostics()
            if controller is not None
            else None
        ),
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

