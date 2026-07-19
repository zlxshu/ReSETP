#!/usr/bin/env python3
"""Run the PyVRP ILS mother or the full MPILS-MVNS candidate.

Both arms use the same PyVRP 0.13.4 construction path, penalty manager,
operators, seed, and stopping criterion.  The full arm replaces only the
``SearchMethod`` passed to ILS.  There is deliberately no mechanism-disable
argument: mechanisms are always consulted and may only skip when the original
instance lacks their semantics.
"""

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

from mpils_mvns_search import MechanismContext, MPILSMVNSSearch


EXPECTED_PYVRP = "0.13.4"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--algorithm",
        choices=("mother", "mpils_mvns"),
        required=True,
    )
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


def solve_arm(
    data: pyvrp.ProblemData,
    *,
    algorithm: str,
    seed: int,
    runtime: float,
) -> tuple[Any, dict[str, Any] | None]:
    params = SolveParams()
    rng = RandomNumberGenerator(seed=seed)
    base_search = build_local_search(data, rng, params)
    penalties = PenaltyManager.init_from(data, params.penalty)
    random_solution = Solution.make_random(data, rng)
    initial = base_search(
        random_solution,
        penalties.max_cost_evaluator(),
        exhaustive=True,
    )

    diagnostics: dict[str, Any] | None = None
    search_method: Any = base_search
    wrapped: MPILSMVNSSearch | None = None
    if algorithm == "mpils_mvns":
        expert_rng = RandomNumberGenerator(seed=seed + 1_000_003)
        expert_search = build_local_search(
            data,
            expert_rng,
            params,
            perturbation=PerturbationParams(0, 0),
        )
        wrapped = MPILSMVNSSearch(
            base_search,
            expert_search,
            data=data,
            context=MechanismContext.from_public_v13(data),
            initial_solution=initial,
        )
        search_method = wrapped

    algorithm_runner = IteratedLocalSearch(
        data,
        penalties,
        rng,
        search_method,
        initial,
        params.ils,
    )
    result = algorithm_runner.run(
        MaxRuntime(runtime),
        collect_stats=True,
        display=False,
        display_interval=params.display_interval,
    )
    if wrapped is not None:
        diagnostics = wrapped.diagnostics()
    return result, diagnostics


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
    result, diagnostics = solve_arm(
        data,
        algorithm=args.algorithm,
        seed=args.seed,
        runtime=args.runtime,
    )
    payload = {
        "schema": "resetp.mpils-mvns-worker.v1",
        "algorithm": args.algorithm,
        "working_name": (
            "MPILS-MVNS" if args.algorithm == "mpils_mvns"
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
        "complete": bool(result.best.is_complete()),
        "feasible": bool(result.best.is_feasible()),
        "distance": int(result.best.distance()),
        "duration": int(result.best.duration()),
        "num_clients": int(result.best.num_clients()),
        "num_routes": int(result.best.num_routes()),
        "routes": [
            route_payload(route) for route in result.best.routes()
        ],
        "mechanism_diagnostics": diagnostics,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
