#!/usr/bin/env python3
"""Run one frozen MPD-ILS-VNS dual-regime arm."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time
from typing import Any

import pyvrp
from pyvrp import (
    IteratedLocalSearch,
    PenaltyManager,
    RandomNumberGenerator,
    Solution,
)
from pyvrp.stop import MaxIterations, MaxRuntime

from multi_stage_regimes import (
    ARMS,
    EXPERTS,
    REGIMES,
    query_public_experts,
)
from selective_route_vns import (
    SelectiveRouteVNS,
    build_node_search,
    build_route_search,
    solve_params,
)


EXPECTED_PYVRP = "0.13.4"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=sorted(ARMS), required=True)
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


def build_search(
    data: pyvrp.ProblemData,
    rng: RandomNumberGenerator,
    regime: str,
) -> tuple[SelectiveRouteVNS, Any]:
    config = REGIMES[regime]
    params = solve_params(config)
    node_search = build_node_search(data, rng, params)
    route_search = build_route_search(
        data,
        rng,
        params,
        config.route_operators,
    )
    return SelectiveRouteVNS(node_search, route_search), params


def main() -> int:
    args = parse_args()
    installed = importlib.metadata.version("pyvrp")
    if installed != EXPECTED_PYVRP:
        raise RuntimeError(f"expected PyVRP {EXPECTED_PYVRP}, found {installed}")
    if args.iterations is not None and args.arm != "foundation":
        raise ValueError("fixed iterations are reserved for foundation equivalence")

    data = pyvrp.read(args.instance, round_func="exact")
    rng = RandomNumberGenerator(seed=args.seed)
    penalty_params = solve_params(REGIMES["foundation"]).penalty
    penalties = PenaltyManager.init_from(data, penalty_params)
    phases = ARMS[args.arm]
    phase_outputs: list[dict[str, Any]] = []
    expert_ledger: list[dict[str, Any]] = []
    best_solution: Solution | None = None
    best_cost: int | None = None
    total_iterations = 0

    algorithm_started = time.perf_counter()
    for phase_index, phase in enumerate(phases, start=1):
        phase_started = time.perf_counter()
        search, params = build_search(data, rng, phase.regime)
        if best_solution is None:
            best_solution = search(
                Solution.make_random(data, rng),
                penalties.max_cost_evaluator(),
                exhaustive=True,
            )

        runner = IteratedLocalSearch(
            data,
            penalties,
            rng,
            search,
            best_solution,
            params.ils,
        )
        if args.runtime is not None:
            boundary = args.runtime * phase.cumulative_fraction
            remaining = boundary - (time.perf_counter() - algorithm_started)
            if remaining <= 0:
                raise RuntimeError(f"phase {phase_index} has no charged runtime left")
            stop = MaxRuntime(remaining)
        else:
            stop = MaxIterations(args.iterations)

        result = runner.run(stop, collect_stats=False, display=False)
        total_iterations += int(result.num_iterations)
        phase_cost = int(result.cost())
        if best_cost is None or phase_cost < best_cost:
            best_cost = phase_cost
            best_solution = result.best
        expert_ledger.extend(query_public_experts(phase_index))
        phase_outputs.append(
            {
                "phase_index": phase_index,
                "regime": phase.regime,
                "cumulative_fraction": phase.cumulative_fraction,
                "iterations": int(result.num_iterations),
                "solver_runtime_seconds": float(result.runtime),
                "charged_elapsed_seconds": (time.perf_counter() - algorithm_started),
                "phase_wall_seconds": (time.perf_counter() - phase_started),
                "best_cost_after_phase": int(best_cost),
                "phase_result_cost": phase_cost,
                "search_diagnostics": search.diagnostics(),
            }
        )

    if best_solution is None or best_cost is None:
        raise RuntimeError("no phase result")

    output = {
        "schema": "resetp.mpd-ils-vns-dual-regime-worker.v1",
        "working_name": "MPD-ILS-VNS",
        "arm": args.arm,
        "arm_payload": [asdict(phase) for phase in phases],
        "regime_payloads": {name: asdict(config) for name, config in REGIMES.items()},
        "pyvrp_version": installed,
        "instance": args.instance.name,
        "instance_sha256": hashlib.sha256(args.instance.read_bytes()).hexdigest(),
        "round_func": "exact",
        "seed": args.seed,
        "requested_runtime_seconds": args.runtime,
        "requested_iterations": args.iterations,
        "iterations_completed": total_iterations,
        "runtime_seconds": time.perf_counter() - algorithm_started,
        "cost": best_cost,
        "distance": int(best_solution.distance()),
        "duration": int(best_solution.duration()),
        "complete": bool(best_solution.is_complete()),
        "feasible": bool(best_solution.is_feasible()),
        "num_clients": int(best_solution.num_clients()),
        "num_routes": int(best_solution.num_routes()),
        "routes": [route_payload(route) for route in best_solution.routes()],
        "rng_state": [int(value) for value in rng.state()],
        "phase_outputs": phase_outputs,
        "mechanism_experts_expected": list(EXPERTS),
        "mechanism_expert_ledger": expert_ledger,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
