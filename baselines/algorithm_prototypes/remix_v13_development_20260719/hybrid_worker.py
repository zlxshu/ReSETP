#!/usr/bin/env python3
"""Run the fixed ReMIX candidate inside one end-to-end time budget."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pyvrp
from pyvrp import Route, Solution


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BEHAVIOUR = (
    REPO
    / "baselines/algorithm_prototypes/"
    "remix_pr17a_behavior_20260719"
)
sys.path.insert(0, str(BEHAVIOUR))

from remix_components import (  # noqa: E402
    ComponentCounters,
    LineagedSolution,
    assert_unique_complete_coverage,
    canonical_routes,
    local_search_refine,
    mechanism_destroy_repair,
    multi_parent_route_exchange,
)


CORE_WORKER = HERE / "core_worker.py"
ROUTE_POOL_WORKER = HERE / "route_pool_milp.py"
HGS_PYTHON = REPO / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
ILS_PYTHON = REPO / "build/python_envs/pyvrp-0.13.4/bin/python"
SCIPY_PYTHON = Path("/opt/anaconda3/bin/python")
MAX_CYCLES = 5
HGS_FEASIBILITY_CAP_SECONDS = 2.0
FINAL_RESERVE_SECONDS = 1.2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--runtime", type=float, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    return parser.parse_args()


def run_core(
    python: Path,
    *,
    core: str,
    instance: Path,
    seed: int,
    runtime: float,
    first_feasible: bool = False,
) -> dict[str, Any]:
    command = [
        str(python),
        str(CORE_WORKER),
        "--core",
        core,
        "--instance",
        str(instance),
        "--seed",
        str(seed),
        "--runtime",
        f"{runtime:.6f}",
    ]
    if first_feasible:
        command.append("--first-feasible")
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{core} supplier failed: {completed.stdout} {completed.stderr}"
        )
    return json.loads(completed.stdout)


def rebuild(
    data: pyvrp.ProblemData,
    payload: dict[str, Any],
    source_id: str,
) -> LineagedSolution:
    solution = Solution(
        data,
        [
            Route(
                data,
                record["visits"],
                int(record["vehicle_type"]),
            )
            for record in payload["routes"]
        ],
    )
    assert_unique_complete_coverage(data, solution)
    if solution.distance() != int(payload["distance"]):
        raise ValueError(f"{source_id}: cross-version distance changed")
    return LineagedSolution(
        source_id=source_id,
        solution=solution,
        lineage=(f"core:{source_id}",),
    )


def run_route_pool(
    data: pyvrp.ProblemData,
    elite: list[LineagedSolution],
    *,
    scratch: Path,
    time_limit_seconds: float,
    counters: ComponentCounters,
) -> tuple[LineagedSolution, dict[str, Any]]:
    counters.route_pool_calls += 1
    records = []
    for item in elite:
        for route in item.solution.routes():
            records.append(
                {
                    "source": item.source_id,
                    "vehicle_type": route.vehicle_type(),
                    "visits": list(route.visits()),
                    "distance": route.distance(),
                }
            )
    counters.route_pool_candidate_routes += len(records)
    payload = {
        "clients": list(range(data.num_depots, data.num_locations)),
        "vehicle_limits": {
            str(vehicle_type): data.vehicle_type(
                vehicle_type
            ).num_available
            for vehicle_type in range(data.num_vehicle_types)
        },
        "routes": records,
        "time_limit_seconds": time_limit_seconds,
    }
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
            f"route pool failed: {completed.stdout} {completed.stderr}"
        )
    result = json.loads(output_path.read_text(encoding="utf-8"))
    selected = [records[idx] for idx in result["selected_indices"]]
    solution = Solution(
        data,
        [
            Route(
                data,
                record["visits"],
                int(record["vehicle_type"]),
            )
            for record in selected
        ],
    )
    assert_unique_complete_coverage(data, solution)
    output = LineagedSolution(
        source_id="route_pool",
        solution=solution,
        lineage=(
            *tuple(result["selected_sources"]),
            "route_pool_milp",
        ),
    )
    return output, {
        **result,
        "distance": solution.distance(),
        "complete": solution.is_complete(),
        "feasible": solution.is_feasible(),
    }


def main() -> int:
    args = parse_args()
    if args.runtime <= FINAL_RESERVE_SECONDS + 0.5:
        raise ValueError("hybrid runtime is too small for the fixed pipeline")
    args.scratch.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    deadline = started + args.runtime
    data = pyvrp.read(args.instance, round_func="exact")
    counters = ComponentCounters()
    trace: list[dict[str, Any]] = []

    hgs_budget = min(
        HGS_FEASIBILITY_CAP_SECONDS,
        max(0.1, deadline - time.perf_counter() - FINAL_RESERVE_SECONDS),
    )
    hgs_payload = run_core(
        HGS_PYTHON,
        core="hgs",
        instance=args.instance,
        seed=args.seed,
        runtime=hgs_budget,
        first_feasible=True,
    )
    if not hgs_payload["complete"] or not hgs_payload["feasible"]:
        raise RuntimeError("HGS did not supply a feasible solution")
    hgs = rebuild(data, hgs_payload, "hgs")
    counters.island_solve_calls += 1
    trace.append(
        {
            "stage": "core_supply",
            "source": "hgs",
            "distance": hgs.solution.distance(),
            "runtime_seconds": hgs_payload["runtime_seconds"],
            "iterations": hgs_payload["iterations_completed"],
        }
    )

    ils_budget = max(
        0.1,
        deadline - time.perf_counter() - FINAL_RESERVE_SECONDS,
    )
    ils_payload = run_core(
        ILS_PYTHON,
        core="ils",
        instance=args.instance,
        seed=args.seed,
        runtime=ils_budget,
    )
    if not ils_payload["complete"] or not ils_payload["feasible"]:
        raise RuntimeError("ILS did not supply a feasible solution")
    ils = rebuild(data, ils_payload, "ils")
    counters.island_solve_calls += 1
    trace.append(
        {
            "stage": "core_supply",
            "source": "ils",
            "distance": ils.solution.distance(),
            "runtime_seconds": ils_payload["runtime_seconds"],
            "iterations": ils_payload["iterations_completed"],
        }
    )

    elite: list[LineagedSolution] = [hgs, ils]
    descendants: list[LineagedSolution] = []
    cycle = 0
    while (
        cycle < MAX_CYCLES
        and deadline - time.perf_counter() > 0.45
    ):
        cycle += 1
        base = min(
            elite,
            key=lambda item: (
                item.solution.distance(),
                item.source_id,
            ),
        )
        donors = [
            item
            for item in [hgs, ils, *descendants[-1:]]
            if item.source_id != base.source_id
        ][:2]
        exchanged, event = multi_parent_route_exchange(
            data,
            base,
            donors,
            counters,
        )
        event["cycle"] = cycle
        trace.append(event)
        rebuilt, event = mechanism_destroy_repair(
            data,
            exchanged,
            counters,
        )
        event["cycle"] = cycle
        trace.append(event)
        refined, event = local_search_refine(
            data,
            rebuilt,
            seed=10_000 + cycle,
            counters=counters,
        )
        event["cycle"] = cycle
        trace.append(event)
        assert_unique_complete_coverage(data, refined.solution)
        descendants.append(refined)
        elite.append(refined)

    remaining = max(0.05, deadline - time.perf_counter() - 0.05)
    pool, pool_event = run_route_pool(
        data,
        elite,
        scratch=args.scratch,
        time_limit_seconds=remaining,
        counters=counters,
    )
    trace.append({"stage": "route_pool", **pool_event})
    candidates = [*elite, pool]
    best = min(
        candidates,
        key=lambda item: (
            item.solution.distance(),
            item.source_id,
        ),
    )
    elapsed = time.perf_counter() - started
    payload = {
        "schema": "resetp.remix-v13-hybrid.v1",
        "core": "remix",
        "pyvrp_version": version("pyvrp"),
        "instance": args.instance.name,
        "instance_sha256": hashlib.sha256(
            args.instance.read_bytes()
        ).hexdigest(),
        "round_func": "exact",
        "seed": args.seed,
        "requested_runtime_seconds": args.runtime,
        "end_to_end_runtime_seconds": elapsed,
        "complete": best.solution.is_complete(),
        "feasible": best.solution.is_feasible(),
        "distance": best.solution.distance(),
        "duration": best.solution.duration(),
        "num_clients": best.solution.num_clients(),
        "num_routes": best.solution.num_routes(),
        "best_source": best.source_id,
        "best_lineage": list(best.lineage),
        "routes": canonical_routes(best.solution),
        "component_counters": {
            **asdict(counters),
            "enhancement_calls": counters.enhancement_calls,
            "cycles_completed": cycle,
        },
        "core_suppliers": {
            "hgs": hgs_payload,
            "ils": ils_payload,
        },
        "route_pool": pool_event,
        "trace": trace,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
