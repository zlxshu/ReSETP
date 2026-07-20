"""Exact set-partitioning recombination of genuine-HGS mechanism elites."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

import numpy as np

from epochal_hgs import HgsExactEpoch, _run_exact_epoch
from pyvrp_adapter import build_pyvrp_problem
from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import (
    China81CompletionResult,
    _single_route_cost,
    annotate_cross_site_services,
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.solution import ChargingAction, Route, Solution


try:
    from scipy.optimize import Bounds, LinearConstraint, milp
except ModuleNotFoundError:
    system_site = Path("/opt/anaconda3/lib/python3.13/site-packages")
    if system_site.exists():
        sys.path.append(str(system_site))
    from scipy.optimize import Bounds, LinearConstraint, milp


@dataclass(frozen=True)
class RoutePoolRecord:
    route: Route
    actions: tuple[ChargingAction, ...]
    customers: tuple[str, ...]
    route_cost: float
    source_view: str
    source_rank: int


@dataclass(frozen=True)
class HgsRoutePoolRun:
    solution: Solution
    completion: China81CompletionResult
    parent_completion: China81CompletionResult
    view_epochs: dict[str, HgsExactEpoch]
    elapsed_seconds: float
    stats: dict[str, Any]


def run_hgs_route_pool_recombination(
    bundle: China81Bundle,
    common_initial_solution: Solution,
    *,
    seed: int,
    hgs_seconds_per_view: float,
    exact_elites_per_view: int = 8,
    max_archive_candidates_per_view: int = 24,
    sp_time_limit_seconds: float = 5.0,
) -> HgsRoutePoolRun:
    """Generate mechanism-diverse HGS elites and recombine their routes."""

    if hgs_seconds_per_view <= 0.0 or sp_time_limit_seconds <= 0.0:
        raise ValueError("HGS and set-partitioning times must be positive")
    if exact_elites_per_view < 1:
        raise ValueError("exact_elites_per_view must be positive")
    started = perf_counter()
    modes = ("cv_only", "naive_ev", "mechanism_ev")
    view_epochs: dict[str, HgsExactEpoch] = {}
    for mode in modes:
        problem = build_pyvrp_problem(
            bundle,
            route_proxy_mode=mode,
        )
        view_epochs[mode] = _run_exact_epoch(
            bundle,
            problem,
            common_initial_solution,
            seed=int(seed),
            runtime_seconds=float(hgs_seconds_per_view),
            warm_elites=(),
            exact_elite_count=int(exact_elites_per_view),
            max_archive_candidates=int(
                max_archive_candidates_per_view
            ),
        )
    parent_completions = [
        completion
        for epoch in view_epochs.values()
        for completion in epoch.elite_completions
    ]
    parent_completion = min(
        parent_completions,
        key=lambda item: item.objective,
    )
    records = _route_pool_records(bundle, view_epochs)
    recombined, sp_stats = _solve_set_partitioning(
        bundle,
        records,
        time_limit_seconds=sp_time_limit_seconds,
    )
    if recombined is None:
        completion = parent_completion
        selected_source = "best_exact_hgs_parent"
    else:
        recombined_completion = complete_china81_route_skeleton(
            recombined,
            bundle,
        )
        if (
            recombined_completion.objective
            < parent_completion.objective - 1.0e-9
        ):
            completion = recombined_completion
            selected_source = "set_partitioning_recombination"
        else:
            completion = parent_completion
            selected_source = "best_exact_hgs_parent"
        sp_stats["recombined_exact_objective"] = float(
            recombined_completion.objective
        )
    elapsed = perf_counter() - started
    return HgsRoutePoolRun(
        solution=completion.solution,
        completion=completion,
        parent_completion=parent_completion,
        view_epochs=view_epochs,
        elapsed_seconds=elapsed,
        stats={
            "algorithm": "MV-HGS-SP",
            "algorithm_name_en": (
                "Multi-View Hybrid Genetic Search with Exact Route-Pool "
                "Recombination"
            ),
            "algorithm_name_zh": (
                "多视角混合遗传搜索—精确路线池重组算法"
            ),
            "story": (
                "three genuine HGS populations generate complementary "
                "routes; the full nonlinear ReSETP model selects elites; an "
                "exact set-partitioning layer recombines routes across views"
            ),
            "seed": int(seed),
            "hgs_seconds_per_view": float(hgs_seconds_per_view),
            "view_count": len(modes),
            "exact_elites_per_view": int(exact_elites_per_view),
            "archive_candidates_per_view": int(
                max_archive_candidates_per_view
            ),
            "parent_solution_count": len(parent_completions),
            "route_pool_size": len(records),
            "best_parent_objective": float(
                parent_completion.objective
            ),
            "selected_source": selected_source,
            "final_objective": float(completion.objective),
            "strict_recombination_improvement": bool(
                completion.objective
                < parent_completion.objective - 1.0e-9
            ),
            "improvement_over_best_parent": float(
                parent_completion.objective - completion.objective
            ),
            "set_partitioning": sp_stats,
            "measured_elapsed_seconds": elapsed,
        },
    )


def _route_pool_records(
    bundle: China81Bundle,
    view_epochs: dict[str, HgsExactEpoch],
) -> tuple[RoutePoolRecord, ...]:
    unique: dict[tuple[Any, ...], RoutePoolRecord] = {}
    customer_ids = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    for mode, epoch in view_epochs.items():
        for rank, completion in enumerate(epoch.elite_completions):
            actions_by_vehicle: dict[str, list[ChargingAction]] = {}
            for action in completion.solution.charging_actions:
                actions_by_vehicle.setdefault(
                    action.vehicle_id,
                    [],
                ).append(action)
            for route in completion.solution.routes:
                customers = tuple(
                    node_id
                    for node_id in route.node_sequence
                    if node_id in customer_ids
                )
                if not customers:
                    continue
                actions = tuple(
                    actions_by_vehicle.get(route.vehicle_id, ())
                )
                key = (
                    route.vehicle_type.lower(),
                    route.home_depot_id,
                    customers,
                    tuple(
                        (
                            action.station_id,
                            round(float(action.energy_kwh), 9),
                            round(
                                float(action.charge_start_second),
                                9,
                            ),
                            action.charging_curve_id,
                        )
                        for action in actions
                    ),
                )
                record = RoutePoolRecord(
                    route=route,
                    actions=actions,
                    customers=customers,
                    route_cost=_single_route_cost(
                        route,
                        actions,
                        bundle,
                    ),
                    source_view=mode,
                    source_rank=rank,
                )
                previous = unique.get(key)
                if (
                    previous is None
                    or record.route_cost < previous.route_cost
                ):
                    unique[key] = record
    return tuple(unique.values())


def _solve_set_partitioning(
    bundle: China81Bundle,
    records: tuple[RoutePoolRecord, ...],
    *,
    time_limit_seconds: float,
) -> tuple[Solution | None, dict[str, Any]]:
    customers = tuple(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    )
    customer_index = {
        customer_id: index
        for index, customer_id in enumerate(customers)
    }
    matrix = np.zeros((len(customers), len(records)), dtype=float)
    for column, record in enumerate(records):
        for customer_id in record.customers:
            matrix[customer_index[customer_id], column] = 1.0
    costs = np.array(
        [record.route_cost for record in records],
        dtype=float,
    )
    constraints: list[LinearConstraint] = [
        LinearConstraint(
            matrix,
            lb=np.ones(len(customers)),
            ub=np.ones(len(customers)),
        )
    ]
    for vehicle_type, limit in (
        ("cv", bundle.instance.num_cv),
        ("ev", bundle.instance.num_ev),
    ):
        if limit is None:
            continue
        row = np.array(
            [
                1.0
                if record.route.vehicle_type.lower() == vehicle_type
                else 0.0
                for record in records
            ]
        )
        constraints.append(
            LinearConstraint(
                row,
                lb=-np.inf,
                ub=float(limit),
            )
        )
    result = milp(
        c=costs,
        integrality=np.ones(len(records)),
        bounds=Bounds(
            np.zeros(len(records)),
            np.ones(len(records)),
        ),
        constraints=constraints,
        options={"time_limit": float(time_limit_seconds)},
    )
    stats: dict[str, Any] = {
        "solver": "scipy.optimize.milp/HiGHS",
        "success": bool(result.success),
        "status": int(result.status),
        "message": str(result.message),
        "objective": (
            None if result.fun is None else float(result.fun)
        ),
        "mip_gap": (
            None
            if getattr(result, "mip_gap", None) is None
            else float(result.mip_gap)
        ),
        "selected_route_count": 0,
        "independent_violation_count": None,
    }
    if result.x is None:
        return None, stats
    selected = [
        records[index]
        for index, value in enumerate(result.x)
        if value > 0.5
    ]
    stats["selected_route_count"] = len(selected)
    routes: list[Route] = []
    actions: list[ChargingAction] = []
    for index, record in enumerate(selected, start=1):
        vehicle_id = (
            f"SP-{record.route.vehicle_type.upper()}-{index:04d}"
        )
        route = replace(record.route, vehicle_id=vehicle_id)
        routes.append(route)
        actions.extend(
            replace(action, vehicle_id=vehicle_id)
            for action in record.actions
        )
    solution = annotate_cross_site_services(
        Solution(routes=routes, charging_actions=actions),
        bundle.customer_home_depot,
    )
    _, _, violations = exact_china81_score(solution, bundle)
    stats["independent_violation_count"] = len(violations)
    if violations:
        return None, stats
    return solution, stats
