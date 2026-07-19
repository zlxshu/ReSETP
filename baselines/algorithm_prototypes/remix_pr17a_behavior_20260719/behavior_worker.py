#!/usr/bin/env python3
"""Runs one isolated arm of the ReMIX PR17A behaviour gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pyvrp
from pyvrp import Route, Solution
from pyvrp.stop import MaxIterations

from remix_components import (
    ComponentCounters,
    LineagedSolution,
    assert_unique_complete_coverage,
    canonical_routes,
    local_search_refine,
    mechanism_destroy_repair,
    multi_parent_route_exchange,
)


HERE = Path(__file__).resolve().parent
ROUTE_POOL_WORKER = HERE / "route_pool_milp.py"
SCIPY_PYTHON = Path("/opt/anaconda3/bin/python")
ISLAND_SEEDS = (1, 1001, 2001)
ISLAND_ITERATIONS = 2


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--budget", type=int, choices=(0, 1, 2, 5))
    parser.add_argument("--mother", action="store_true")
    parser.add_argument("--scratch", type=Path, required=True)
    return parser.parse_args()


def solve_mother(
    data: pyvrp.ProblemData,
    *,
    seed: int,
) -> pyvrp.Result:
    return pyvrp.solve(
        data,
        stop=MaxIterations(ISLAND_ITERATIONS),
        seed=seed,
        collect_stats=True,
        display=False,
    )


def route_pool_payload(
    data: pyvrp.ProblemData,
    elite: list[LineagedSolution],
) -> dict[str, Any]:
    routes = []
    for item in elite:
        for route in item.solution.routes():
            routes.append(
                {
                    "source": item.source_id,
                    "lineage": list(item.lineage),
                    "vehicle_type": route.vehicle_type(),
                    "visits": list(route.visits()),
                    "distance": route.distance(),
                }
            )
    return {
        "clients": list(range(data.num_depots, data.num_locations)),
        "vehicle_limits": {
            str(vehicle_type): data.vehicle_type(
                vehicle_type
            ).num_available
            for vehicle_type in range(data.num_vehicle_types)
        },
        "routes": routes,
    }


def exact_route_pool(
    data: pyvrp.ProblemData,
    elite: list[LineagedSolution],
    counters: ComponentCounters,
    scratch: Path,
) -> tuple[LineagedSolution, dict[str, Any]]:
    counters.route_pool_calls += 1
    payload = route_pool_payload(data, elite)
    counters.route_pool_candidate_routes += len(payload["routes"])
    input_path = scratch / "route_pool_input.json"
    output_path = scratch / "route_pool_output.json"
    input_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            str(SCIPY_PYTHON),
            str(ROUTE_POOL_WORKER),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "route-pool MILP failed: "
            f"stdout={completed.stdout} stderr={completed.stderr}"
        )
    result = json.loads(output_path.read_text(encoding="utf-8"))
    selected_routes = [
        payload["routes"][idx]
        for idx in result["selected_indices"]
    ]
    solution = Solution(
        data,
        [
            Route(
                data,
                record["visits"],
                int(record["vehicle_type"]),
            )
            for record in selected_routes
        ],
    )
    assert_unique_complete_coverage(data, solution)
    selected_sources = tuple(result["selected_sources"])
    input_sources = sorted(
        {str(record["source"]) for record in payload["routes"]}
    )
    output = LineagedSolution(
        source_id="route_pool",
        solution=solution,
        lineage=(*selected_sources, "elite_pool", "route_pool_milp"),
    )
    return output, {
        "stage": "route_pool_milp",
        **result,
        "input_sources": input_sources,
        "complete": solution.is_complete(),
        "feasible": solution.is_feasible(),
        "distance": solution.distance(),
    }


def run_hybrid(
    data: pyvrp.ProblemData,
    *,
    budget: int,
    scratch: Path,
) -> tuple[LineagedSolution, ComponentCounters, list[dict[str, Any]], dict[str, Any]]:
    counters = ComponentCounters()
    trace: list[dict[str, Any]] = []
    islands: list[LineagedSolution] = []
    for idx, seed in enumerate(ISLAND_SEEDS):
        result = solve_mother(data, seed=seed)
        counters.island_solve_calls += 1
        counters.island_ils_iterations += ISLAND_ITERATIONS
        assert_unique_complete_coverage(data, result.best)
        item = LineagedSolution(
            source_id=f"island_{idx}",
            solution=result.best,
            lineage=(f"island:{idx}",),
        )
        islands.append(item)
        trace.append(
            {
                "stage": "island_ils",
                "source": item.source_id,
                "seed": seed,
                "iterations": ISLAND_ITERATIONS,
                "distance": result.best.distance(),
                "complete": result.best.is_complete(),
                "feasible": result.best.is_feasible(),
            }
        )

    elite = list(islands)
    descendants: list[LineagedSolution] = []
    for cycle in range(budget):
        base = descendants[-1] if descendants else islands[cycle % 3]
        donor_order = [
            islands[(cycle + 1) % 3],
            islands[(cycle + 2) % 3],
        ]
        exchanged, event = multi_parent_route_exchange(
            data,
            base,
            donor_order,
            counters,
        )
        event["cycle"] = cycle + 1
        trace.append(event)

        rebuilt, event = mechanism_destroy_repair(
            data,
            exchanged,
            counters,
        )
        event["cycle"] = cycle + 1
        trace.append(event)

        refined, event = local_search_refine(
            data,
            rebuilt,
            seed=10_000 + cycle,
            counters=counters,
        )
        event["cycle"] = cycle + 1
        trace.append(event)
        assert_unique_complete_coverage(data, refined.solution)
        descendants.append(refined)
        elite.append(refined)
        trace.append(
            {
                "stage": "elite_pool_ingest",
                "cycle": cycle + 1,
                "source": refined.source_id,
                "lineage": list(refined.lineage),
                "distance": refined.solution.distance(),
            }
        )

    pool_solution, pool_event = exact_route_pool(
        data,
        elite,
        counters,
        scratch,
    )
    trace.append(pool_event)
    candidates = [*elite, pool_solution]
    best = min(
        candidates,
        key=lambda item: (
            item.solution.distance(),
            item.source_id,
        ),
    )
    return best, counters, trace, pool_event


def solution_payload(solution: Solution) -> dict[str, Any]:
    routes = canonical_routes(solution)
    return {
        "cost": (
            solution.distance_cost()
            + solution.duration_cost()
            + solution.fixed_vehicle_cost()
        ),
        "distance": solution.distance(),
        "duration": solution.duration(),
        "feasible": solution.is_feasible(),
        "complete": solution.is_complete(),
        "num_routes": solution.num_routes(),
        "num_clients": solution.num_clients(),
        "routes": routes,
    }


def main() -> int:
    args = parse_args()
    if not args.mother and args.budget is None:
        raise ValueError("--budget is required unless --mother is used")
    args.scratch.mkdir(parents=True, exist_ok=True)
    data = pyvrp.read(args.instance, round_func="exact")
    if args.mother or args.budget == 0:
        result = solve_mother(data, seed=args.seed)
        best = LineagedSolution(
            source_id="mother",
            solution=result.best,
            lineage=("mother_ils",),
        )
        counters = ComponentCounters()
        trace = []
        pool_event = {}
        runtime = result.runtime
        requested_budget = 0
    else:
        best, counters, trace, pool_event = run_hybrid(
            data,
            budget=int(args.budget),
            scratch=args.scratch,
        )
        runtime = None
        requested_budget = int(args.budget)

    assert_unique_complete_coverage(data, best.solution)
    payload = solution_payload(best.solution)
    output = {
        "mode": "mother" if args.mother else f"budget_{requested_budget}",
        "requested_budget": requested_budget,
        "instance": args.instance.name,
        "instance_sha256": hashlib.sha256(args.instance.read_bytes()).hexdigest(),
        "pyvrp_version": version("pyvrp"),
        "island_seeds": list(ISLAND_SEEDS),
        "island_iterations": ISLAND_ITERATIONS,
        "best_source": best.source_id,
        "best_lineage": list(best.lineage),
        "component_counters": {
            **asdict(counters),
            "enhancement_calls": counters.enhancement_calls,
        },
        "trace": trace,
        "route_pool": pool_event,
        "deterministic_payload": payload,
        "deterministic_signature_sha256": canonical_sha256(payload),
        "runtime_s_non_comparable": runtime,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
