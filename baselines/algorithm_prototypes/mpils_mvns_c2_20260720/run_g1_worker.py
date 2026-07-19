#!/usr/bin/env python3
"""Run one frozen arm of the MPILS-MVNS-C2 G1 B-group gate."""

from __future__ import annotations

import argparse
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
from pyvrp.stop import MaxRuntime

from c2_core import (
    BoundedCrossDepotSegmentOperator,
    C2EventController,
    MechanismContext,
    ReplacementSearchMethod,
)
from event_driven_ils import EventDrivenIteratedLocalSearch


EXPECTED_PYVRP = "0.13.4"
ALGORITHMS = ("mother", "mpils_mvns_c2")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--algorithm", choices=ALGORITHMS, required=True)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--runtime", type=float, required=True)
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
    if args.runtime <= 0:
        raise ValueError("runtime must be positive")

    data = pyvrp.read(args.instance, round_func="exact")
    params = SolveParams()
    mother_rng = RandomNumberGenerator(seed=args.seed)
    native_search = build_local_search(data, mother_rng, params)
    penalties = PenaltyManager.init_from(data, params.penalty)
    initial = native_search(
        Solution.make_random(data, mother_rng),
        penalties.max_cost_evaluator(),
        exhaustive=True,
    )

    controller: C2EventController | None = None
    replacement: ReplacementSearchMethod | None = None
    if args.algorithm == "mother":
        runner: Any = IteratedLocalSearch(
            data,
            penalties,
            mother_rng,
            native_search,
            initial,
            params.ils,
        )
    else:
        expert_rng = RandomNumberGenerator(seed=args.seed + 1_000_003)
        zero_search = build_local_search(
            data,
            expert_rng,
            params,
            perturbation=PerturbationParams(0, 0),
        )
        operator = BoundedCrossDepotSegmentOperator(
            data,
            seed=args.seed + 2_000_003,
            max_source_segments=64,
            max_positions_per_source=6,
            max_route_evaluations=48,
            max_full_evaluations=12,
        )
        replacement = ReplacementSearchMethod(
            native_search,
            zero_search,
            operator,
        )
        controller = C2EventController(
            MechanismContext.from_public_v13(data),
            allow_replacement=True,
            trigger_after=1666,
            cooldown=1666,
            target_edge_distance=(0.15, 0.35),
            elite_limit=8,
        )
        runner = EventDrivenIteratedLocalSearch(
            data,
            penalties,
            mother_rng,
            replacement,
            initial,
            params.ils,
            event_hooks=controller,
        )

    result = runner.run(
        MaxRuntime(args.runtime),
        collect_stats=False,
        display=False,
        display_interval=params.display_interval,
    )
    output = {
        "schema": "resetp.mpils-mvns-c2-g1-worker.v1",
        "algorithm": args.algorithm,
        "working_name": (
            "MPILS-MVNS-C2"
            if args.algorithm == "mpils_mvns_c2"
            else "PyVRP-0.13.4-ILS"
        ),
        "pyvrp_version": installed,
        "instance": args.instance.name,
        "instance_sha256": hashlib.sha256(
            args.instance.read_bytes()
        ).hexdigest(),
        "round_func": "exact",
        "seed": args.seed,
        "requested_runtime_seconds": args.runtime,
        "iterations_completed": int(result.num_iterations),
        "runtime_seconds": float(result.runtime),
        "cost": int(result.cost()),
        "distance": int(result.best.distance()),
        "duration": int(result.best.duration()),
        "complete": bool(result.best.is_complete()),
        "feasible": bool(result.best.is_feasible()),
        "num_clients": int(result.best.num_clients()),
        "num_routes": int(result.best.num_routes()),
        "routes": [
            route_payload(route) for route in result.best.routes()
        ],
        "mother_rng_state": [
            int(value) for value in mother_rng.state()
        ],
        "event_diagnostics": (
            controller.diagnostics()
            if controller is not None
            else None
        ),
        "search_diagnostics": (
            replacement.diagnostics()
            if replacement is not None
            else None
        ),
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
