"""Spawn-safe worker entry points for the frozen JRC exact neighborhood."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from .common import (
    PACKAGE,
    exact_replay,
    load_bundle,
    load_solution,
    read_json,
    set_single_thread_environment,
    solution_payload,
    verify_registration,
)
from .exact_neighborhood import (
    adjacency_change_count,
    choose_neighborhood,
    materialize_candidate,
    resource_change_count,
    solve_exact_neighborhood,
)


EXPECTED_MODULE = (
    "baselines.algorithm_prototypes."
    "joint_route_charge_exact_neighborhood_20260725.worker_entry"
)


def worker_identity(_: int) -> dict[str, Any]:
    set_single_thread_environment()
    module = importlib.import_module(EXPECTED_MODULE)
    return {
        "module": module.__name__,
        "file": str(Path(module.__file__).resolve()),
        "expected_file": str(Path(__file__).resolve()),
    }


def _start_solution(task: dict[str, Any], bundle: Any) -> Any:
    if task["arm"] == "AB_HGS_EXACT_NH":
        payload = read_json(PACKAGE.parents[2] / task["hgs_witness"])[
            "MV-HGS-SP"
        ]
        return load_solution(payload)

    from setp_solver.china81_completion import (
        complete_china81_route_skeleton,
    )

    payload = read_json(
        PACKAGE.parents[2] / task["construction_witness"]
    )
    skeleton = load_solution(
        {
            "routes": payload["routes"],
            "charging_actions": [],
            "cross_site_services": [],
        }
    )
    return complete_china81_route_skeleton(skeleton, bundle).solution


def inspect_task(task: dict[str, Any]) -> dict[str, Any]:
    """Load and replay a real start without objective neighborhood search."""

    set_single_thread_environment()
    verify_registration()
    bundle = load_bundle(task["instance_id"])
    start = _start_solution(task, bundle)
    start_cost = exact_replay(start, bundle, f"{task['task_id']} start")
    if task["arm"] == "AB_HGS_EXACT_NH":
        expected = float(task["hgs_expected_cost"])
        if abs(start_cost - expected) > 1.0e-6:
            raise RuntimeError(
                f"sealed HGS replay drift: {start_cost} != {expected}"
            )
    spec = choose_neighborhood(start, bundle)
    return {
        "task_id": task["task_id"],
        "instance_id": task["instance_id"],
        "arm": task["arm"],
        "start_cost": start_cost,
        "selected_customers": list(spec.selected_customers),
        "selected_customer_count": len(spec.selected_customers),
        "route_indices": list(spec.route_indices),
        "old_pair_cost": spec.old_pair_cost,
    }


def run_task(task: dict[str, Any]) -> dict[str, Any]:
    set_single_thread_environment()
    registration = verify_registration()
    bundle = load_bundle(task["instance_id"])
    start = _start_solution(task, bundle)
    start_cost = exact_replay(start, bundle, f"{task['task_id']} start")
    if task["arm"] == "AB_HGS_EXACT_NH":
        expected = float(task["hgs_expected_cost"])
        if abs(start_cost - expected) > 1.0e-6:
            raise RuntimeError(
                f"sealed HGS replay drift: {start_cost} != {expected}"
            )
    spec = choose_neighborhood(start, bundle)
    limits = registration["limits"]
    if len(spec.selected_customers) != int(limits["selected_customers"]):
        raise RuntimeError("frozen neighborhood size drift")
    result = solve_exact_neighborhood(
        spec,
        bundle,
        time_limit_seconds=float(limits["time_limit_seconds"]),
    )
    candidate = materialize_candidate(start, spec, result, bundle)
    final_cost = exact_replay(
        candidate,
        bundle,
        f"{task['task_id']} candidate",
    )
    predicted = start_cost - spec.old_pair_cost + result.objective
    if abs(final_cost - predicted) > 1.0e-6:
        raise RuntimeError(
            f"route/whole-solution closure failed: {final_cost} != {predicted}"
        )
    improvement = start_cost - final_cost
    return {
        "task_id": task["task_id"],
        "instance_id": task["instance_id"],
        "arm": task["arm"],
        "hgs_seed": task["hgs_seed"],
        "start_cost": start_cost,
        "final_cost": final_cost,
        "improvement": improvement,
        "improvement_pct": 100.0 * improvement / start_cost,
        "strict_improvement": improvement > 1.0e-9,
        "optimality_proven": result.optimality_proven,
        "complete_candidate_scores": 1,
        "elapsed_seconds": result.elapsed_seconds,
        "selected_customer_count": len(spec.selected_customers),
        "selected_customers": list(spec.selected_customers),
        "route_indices": list(spec.route_indices),
        "permutation_count": result.permutation_count,
        "split_count": result.split_count,
        "lower_bound_pruned": result.lower_bound_pruned,
        "exact_pair_count": result.exact_pair_count,
        "route_option_requests": result.route_option_requests,
        "route_option_cache_entries": result.route_option_cache_entries,
        "adjacency_change_count": adjacency_change_count(
            start, candidate, bundle
        ),
        "resource_change_count": resource_change_count(
            start, candidate, bundle
        ),
        "solution": solution_payload(candidate),
    }
