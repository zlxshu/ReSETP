#!/usr/bin/env python3
"""Time-limited MIP route-pool recombination of genuine-HGS elites."""

from __future__ import annotations

import math
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
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
    hgs_seconds_per_view: float | None,
    exact_elites_per_view: int = 8,
    max_archive_candidates_per_view: int | Mapping[str, int] = 24,
    sp_time_limit_seconds: float = 5.0,
    hard_home_depot_lock: bool = False,
    max_hgs_iterations_per_view: int | None = None,
    wallclock_safety_seconds_per_view: float | None = None,
    exact_checkpoint_interval_iterations: (
        int | Mapping[str, int | None] | None
    ) = None,
    preserve_base_pool_recombination: bool = False,
) -> HgsRoutePoolRun:
    """Generate mechanism-diverse HGS elites and recombine their routes."""

    modes = ("cv_only", "naive_ev", "mechanism_ev")
    if isinstance(max_archive_candidates_per_view, Mapping):
        if set(max_archive_candidates_per_view) != set(modes):
            raise ValueError(
                "archive-candidate mapping must cover exactly the three "
                "registered views"
            )
        archive_limits = {
            mode: int(max_archive_candidates_per_view[mode])
            for mode in modes
        }
    else:
        archive_limits = {
            mode: int(max_archive_candidates_per_view)
            for mode in modes
        }
    if isinstance(exact_checkpoint_interval_iterations, Mapping):
        if set(exact_checkpoint_interval_iterations) != set(modes):
            raise ValueError(
                "checkpoint-interval mapping must cover exactly the three "
                "registered views"
            )
        checkpoint_intervals = {
            mode: (
                None
                if exact_checkpoint_interval_iterations[mode] is None
                else int(exact_checkpoint_interval_iterations[mode])
            )
            for mode in modes
        }
    else:
        checkpoint_intervals = {
            mode: (
                None
                if exact_checkpoint_interval_iterations is None
                else int(exact_checkpoint_interval_iterations)
            )
            for mode in modes
        }
    if sp_time_limit_seconds <= 0.0:
        raise ValueError("MIP route-pool time limit must be positive")
    if max_hgs_iterations_per_view is None:
        if hgs_seconds_per_view is None or hgs_seconds_per_view <= 0.0:
            raise ValueError("legacy HGS runtime must be positive")
    elif (
        wallclock_safety_seconds_per_view is None
        or wallclock_safety_seconds_per_view <= 0.0
    ):
        raise ValueError(
            "deterministic HGS mode requires a wallclock safety cap"
        )
    if exact_elites_per_view < 1:
        raise ValueError("exact_elites_per_view must be positive")
    if any(
        limit < int(exact_elites_per_view)
        for limit in archive_limits.values()
    ):
        raise ValueError(
            "each archive-candidate limit must cover the exact elites"
        )
    if any(
        interval is not None and interval <= 0
        for interval in checkpoint_intervals.values()
    ):
        raise ValueError("checkpoint intervals must be positive")
    started = perf_counter()
    view_epochs: dict[str, HgsExactEpoch] = {}
    for mode in modes:
        problem = build_pyvrp_problem(
            bundle,
            route_proxy_mode=mode,
            hard_home_depot_lock=hard_home_depot_lock,
        )
        view_epochs[mode] = _run_exact_epoch(
            bundle,
            problem,
            common_initial_solution,
            seed=int(seed),
            runtime_seconds=(
                None
                if hgs_seconds_per_view is None
                else float(hgs_seconds_per_view)
            ),
            warm_elites=(),
            exact_elite_count=int(exact_elites_per_view),
            max_archive_candidates=archive_limits[mode],
            max_hgs_iterations=max_hgs_iterations_per_view,
            wallclock_safety_seconds=(
                wallclock_safety_seconds_per_view
            ),
            exact_checkpoint_interval_iterations=checkpoint_intervals[
                mode
            ],
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
    base_recombined_completion: China81CompletionResult | None = None
    base_sp_stats: dict[str, Any] | None = None
    if preserve_base_pool_recombination:
        base_records = _route_pool_records(
            bundle,
            view_epochs,
            hard_home_depot_lock=hard_home_depot_lock,
            use_base_archive=True,
        )
        base_recombined, base_sp_stats = _solve_set_partitioning(
            bundle,
            base_records,
            time_limit_seconds=sp_time_limit_seconds,
            hard_home_depot_lock=hard_home_depot_lock,
        )
        if base_recombined is not None:
            base_recombined_completion = _accepted_mip_completion(
                base_recombined,
                bundle,
                base_sp_stats,
            )
    records = _route_pool_records(
        bundle,
        view_epochs,
        hard_home_depot_lock=hard_home_depot_lock,
    )
    recombined, sp_stats = _solve_set_partitioning(
        bundle,
        records,
        time_limit_seconds=sp_time_limit_seconds,
        hard_home_depot_lock=hard_home_depot_lock,
    )
    if recombined is None and base_recombined_completion is None:
        parent_objective, _, parent_violations = exact_china81_score(
            parent_completion.solution,
            bundle,
        )
        if parent_violations:
            raise ValueError(
                "best exact HGS parent failed final independent recheck"
            )
        completion = complete_china81_route_skeleton(
            parent_completion.solution,
            bundle,
        )
        selected_source = "best_exact_hgs_parent"
        sp_stats["fallback_parent_independent_objective"] = float(
            parent_objective
        )
        sp_stats["fallback_parent_independent_violation_count"] = 0
    else:
        candidates: list[
            tuple[str, China81CompletionResult]
        ] = [("best_exact_hgs_parent", parent_completion)]
        if base_recombined_completion is not None:
            candidates.append(
                (
                    "base_pool_time_limited_mip_recombination",
                    base_recombined_completion,
                )
            )
        if recombined is not None:
            recombined_completion = _accepted_mip_completion(
                recombined,
                bundle,
                sp_stats,
            )
            candidates.append(
                (
                    "history_expanded_time_limited_mip_recombination",
                    recombined_completion,
                )
            )
            sp_stats["recombined_exact_objective"] = float(
                recombined_completion.objective
            )
        selected_source, completion = min(
            candidates,
            key=lambda item: item[1].objective,
        )
    elapsed = perf_counter() - started
    epoch_attempts = sum(
        int(epoch.stats["complete_candidate_evaluation_attempts"])
        for epoch in view_epochs.values()
    )
    total_complete_attempts = epoch_attempts + 2
    expected_complete_attempts = (
        sum(archive_limits[mode] + 2 for mode in modes) + 2
    )
    if any(
        interval is not None
        for interval in checkpoint_intervals.values()
    ):
        if max_hgs_iterations_per_view is None:
            raise ValueError(
                "exact checkpoints require an HGS iteration budget"
            )
        expected_complete_attempts += sum(
            0
            if checkpoint_intervals[mode] is None
            else (
                int(max_hgs_iterations_per_view)
                // int(checkpoint_intervals[mode])
            )
            for mode in modes
        )
    if preserve_base_pool_recombination:
        total_complete_attempts += 2
        expected_complete_attempts += 2
    safety_triggered = any(
        bool(epoch.stats["wallclock_safety_triggered"])
        for epoch in view_epochs.values()
    )
    evaluation_trace: list[dict[str, Any]] = []
    for mode in modes:
        for item in view_epochs[
            mode
        ].stats["complete_candidate_evaluation_trace"]:
            evaluation_trace.append(
                {
                    "evaluation_index": len(evaluation_trace) + 1,
                    "view": mode,
                    **item,
                }
            )
    for source in (
        "route_pool_candidate_or_parent",
        "final_independent_certificate",
    ):
        evaluation_trace.append(
            {
                "evaluation_index": len(evaluation_trace) + 1,
                "view": "route_pool",
                "source": source,
                "iteration": None,
                "complete_objective": float(completion.objective),
                "status": "PASS",
            }
        )
    if len(evaluation_trace) != total_complete_attempts:
        raise RuntimeError(
            "combined complete-candidate trace does not match the frozen "
            "evaluation-attempt counter"
        )
    incumbent = math.inf
    last_strict_improvement_evaluation = 0
    for item in evaluation_trace:
        objective = item["complete_objective"]
        if (
            objective is not None
            and float(objective) < incumbent - 1.0e-9
        ):
            incumbent = float(objective)
            last_strict_improvement_evaluation = int(
                item["evaluation_index"]
            )
    return HgsRoutePoolRun(
        solution=completion.solution,
        completion=completion,
        parent_completion=parent_completion,
        view_epochs=view_epochs,
        elapsed_seconds=elapsed,
        stats={
            "algorithm": "MV-HGS-SP",
            "algorithm_name_en": (
                "Multi-View Hybrid Genetic Search with Time-Limited MIP "
                "Route-Pool "
                "Recombination"
            ),
            "algorithm_name_zh": (
                "多视角混合遗传搜索—限时MIP路线池重组算法"
            ),
            "story": (
                "three genuine HGS populations generate complementary "
                "routes; the full nonlinear ReSETP model selects elites; an "
                "audited time-limited MIP layer recombines routes across views"
            ),
            "seed": int(seed),
            "hgs_seconds_per_view": (
                None
                if hgs_seconds_per_view is None
                else float(hgs_seconds_per_view)
            ),
            "max_hgs_iterations_per_view": (
                None
                if max_hgs_iterations_per_view is None
                else int(max_hgs_iterations_per_view)
            ),
            "wallclock_safety_seconds_per_view": (
                None
                if wallclock_safety_seconds_per_view is None
                else float(wallclock_safety_seconds_per_view)
            ),
            "wallclock_safety_triggered": safety_triggered,
            "primary_budget_unit": (
                "complete_candidate_evaluation_attempt"
            ),
            "complete_candidate_evaluation_attempts": (
                total_complete_attempts
            ),
            "complete_candidate_budget_expected": (
                expected_complete_attempts
            ),
            "complete_candidate_budget_exactly_consumed": (
                total_complete_attempts == expected_complete_attempts
            ),
            "complete_candidate_evaluation_trace": evaluation_trace,
            "last_strict_improvement_evaluation": (
                last_strict_improvement_evaluation
            ),
            "last_strict_improvement_fraction": (
                last_strict_improvement_evaluation
                / total_complete_attempts
            ),
            "view_count": len(modes),
            "exact_elites_per_view": int(exact_elites_per_view),
            "archive_candidates_per_view": archive_limits,
            "exact_checkpoint_interval_iterations": (
                checkpoint_intervals
            ),
            "exact_checkpoint_attempts_by_view": {
                mode: int(
                    epoch.stats["exact_checkpoint_attempts"]
                )
                for mode, epoch in view_epochs.items()
            },
            "preserve_base_pool_recombination": bool(
                preserve_base_pool_recombination
            ),
            "base_route_pool_mip": base_sp_stats,
            "parent_solution_count": len(parent_completions),
            "route_pool_candidate_solution_count": sum(
                len(
                    epoch.archive_completions
                    if epoch.archive_completions
                    else epoch.elite_completions
                )
                for epoch in view_epochs.values()
            ),
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
            "route_pool_mip": sp_stats,
            "set_partitioning": {
                **sp_stats,
                "legacy_key_name_only": True,
            },
            "hard_home_depot_lock": bool(hard_home_depot_lock),
            "measured_elapsed_seconds": elapsed,
        },
    )


def _route_pool_records(
    bundle: China81Bundle,
    view_epochs: dict[str, HgsExactEpoch],
    *,
    hard_home_depot_lock: bool = False,
    use_base_archive: bool = False,
) -> tuple[RoutePoolRecord, ...]:
    unique: dict[tuple[Any, ...], RoutePoolRecord] = {}
    customer_ids = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    for mode, epoch in view_epochs.items():
        if use_base_archive and epoch.base_archive_completions:
            route_pool_completions = (
                epoch.base_archive_completions
            )
        else:
            route_pool_completions = (
                epoch.archive_completions
                if epoch.archive_completions
                else epoch.elite_completions
            )
        for rank, completion in enumerate(route_pool_completions):
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
                if hard_home_depot_lock and any(
                    bundle.customer_home_depot[customer_id]
                    != route.home_depot_id
                    for customer_id in customers
                ):
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


def _accepted_mip_completion(
    solution: Solution,
    bundle: China81Bundle,
    mip_stats: dict[str, Any],
) -> China81CompletionResult:
    """Retain an independently checked MIP incumbent without re-decoding it."""

    annotated = annotate_cross_site_services(
        solution,
        bundle.customer_home_depot,
    )
    objective, breakdown, violations = exact_china81_score(
        annotated,
        bundle,
    )
    if violations:
        raise ValueError(
            "accepted route-pool incumbent failed complete-model recheck"
        )
    mip_objective = mip_stats.get("objective")
    if (
        mip_objective is None
        or not math.isclose(
            float(mip_objective),
            float(objective),
            rel_tol=1.0e-9,
            abs_tol=1.0e-6,
        )
    ):
        raise ValueError(
            "route-pool incumbent objective does not close under the "
            "complete model: "
            f"mip={mip_objective!r}, exact={objective!r}"
        )
    return China81CompletionResult(
        solution=annotated,
        objective=float(objective),
        breakdown=breakdown,
        activity={
            "schema_version": (
                "resetp.china81-accepted-mip-completion.v1"
            ),
            "source": "time_limited_mip_route_pool_incumbent",
            "route_count": len(annotated.routes),
            "ev_route_count": sum(
                route.vehicle_type.lower() == "ev"
                for route in annotated.routes
            ),
            "charging_action_count": len(
                annotated.charging_actions
            ),
            "mip_status_class": mip_stats.get("status_class"),
            "mip_objective": float(mip_objective),
            "mip_dual_bound": mip_stats.get("dual_bound"),
            "mip_gap": mip_stats.get("mip_gap"),
            "complete_model_recheck": "PASS",
        },
    )


def _solve_set_partitioning(
    bundle: China81Bundle,
    records: tuple[RoutePoolRecord, ...],
    *,
    time_limit_seconds: float,
    hard_home_depot_lock: bool = False,
) -> tuple[Solution | None, dict[str, Any]]:
    if time_limit_seconds <= 0.0:
        raise ValueError("MIP route-pool time limit must be positive")
    if hard_home_depot_lock:
        records = tuple(
            record
            for record in records
            if all(
                bundle.customer_home_depot[customer_id]
                == record.route.home_depot_id
                for customer_id in record.customers
            )
        )
    customers = tuple(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    )
    customer_index = {
        customer_id: index
        for index, customer_id in enumerate(customers)
    }
    if not records:
        return None, {
            "solver": "scipy.optimize.milp/HiGHS",
            "component": "time-limited MIP route-pool recombination",
            "success": False,
            "status": None,
            "status_class": "NO_COLUMNS",
            "message": "route pool is empty after mechanism filtering",
            "incumbent_available": False,
            "objective": None,
            "dual_bound": None,
            "mip_gap": None,
            "mip_node_count": None,
            "time_limit_seconds": float(time_limit_seconds),
            "optimality_proven": False,
            "selected_route_count": 0,
            "independent_violation_count": None,
            "independent_complete_candidate_evaluation_attempts": 0,
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
    for depot_id, caps in sorted(bundle.fleet_caps_by_depot.items()):
        for vehicle_type in ("cv", "ev"):
            row = np.array(
                [
                    1.0
                    if (
                        record.route.vehicle_type.lower() == vehicle_type
                        and record.route.home_depot_id == depot_id
                    )
                    else 0.0
                    for record in records
                ]
            )
            constraints.append(
                LinearConstraint(
                    row,
                    lb=-np.inf,
                    ub=float(caps[f"num_{vehicle_type}"]),
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
        "component": "time-limited MIP route-pool recombination",
        "success": bool(result.success),
        "status": int(result.status),
        "status_class": (
            "OPTIMAL"
            if bool(result.success) and int(result.status) == 0
            else (
                "LIMIT_WITH_INCUMBENT"
                if result.x is not None
                else "NO_INCUMBENT"
            )
        ),
        "message": str(result.message),
        "incumbent_available": result.x is not None,
        "objective": (
            None if result.fun is None else float(result.fun)
        ),
        "dual_bound": (
            None
            if getattr(result, "mip_dual_bound", None) is None
            else float(result.mip_dual_bound)
        ),
        "mip_gap": (
            None
            if getattr(result, "mip_gap", None) is None
            else float(result.mip_gap)
        ),
        "mip_node_count": (
            None
            if getattr(result, "mip_node_count", None) is None
            else int(result.mip_node_count)
        ),
        "time_limit_seconds": float(time_limit_seconds),
        "optimality_proven": bool(
            result.success and int(result.status) == 0
        ),
        "incumbent_vector_integral": None,
        "incumbent_cover_exact": None,
        "selected_route_count": 0,
        "independent_violation_count": None,
        "independent_complete_candidate_evaluation_attempts": 0,
    }
    if result.x is None:
        return None, stats
    vector = np.asarray(result.x, dtype=float)
    integral = bool(
        np.all(
            np.isclose(
                vector,
                np.rint(vector),
                rtol=0.0,
                atol=1e-7,
            )
        )
    )
    stats["incumbent_vector_integral"] = integral
    if not integral:
        stats["status_class"] = "REJECTED_NONINTEGRAL_INCUMBENT"
        return None, stats
    selected_vector = np.rint(vector)
    cover_exact = bool(
        np.allclose(
            matrix @ selected_vector,
            np.ones(len(customers)),
            rtol=0.0,
            atol=1e-7,
        )
    )
    stats["incumbent_cover_exact"] = cover_exact
    if not cover_exact:
        stats["status_class"] = "REJECTED_INEXACT_COVER"
        return None, stats
    selected = [
        records[index]
        for index, value in enumerate(selected_vector)
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
    exact_objective, _, violations = exact_china81_score(
        solution,
        bundle,
    )
    stats["independent_complete_candidate_evaluation_attempts"] = 1
    stats["independent_violation_count"] = len(violations)
    stats["independent_exact_objective"] = float(exact_objective)
    stats["objective_closes_under_complete_model"] = bool(
        stats["objective"] is not None
        and math.isclose(
            float(stats["objective"]),
            float(exact_objective),
            rel_tol=1.0e-9,
            abs_tol=1.0e-6,
        )
    )
    if violations:
        stats["status_class"] = "REJECTED_COMPLETE_MODEL_VIOLATIONS"
        return None, stats
    if not stats["objective_closes_under_complete_model"]:
        stats["status_class"] = "REJECTED_OBJECTIVE_MISMATCH"
        return None, stats
    return solution, stats
