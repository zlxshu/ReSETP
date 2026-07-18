"""Route-breeding HGS--ALNS development candidate.

The official HGS-CVRP projection is too weak as a complete ReSETP solution:
it does not model heterogeneous vehicles, charging, carbon, or cooperation.
This module therefore uses the unmodified official engine only as a route
breeder.  Its native routes compete with routes from an ALNS-educated
solution in an exact-cover route pool.  Only complete, independently checked
ReSETP solutions consume the shared evaluation budget.

The module is isolated development code and is not imported by the formal
solver.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from pathlib import Path
import random
import time
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from official_hgs_resetp_adapter import (
    HGSAdapterConfig,
    OfficialHGSLibrary,
    official_hgs_order,
)
from prototype import ArmResult, independent_cost, run_pure_alns
from setp_solver.algorithms.resetp_alns.runtime.budgeted_scoring import (
    score_search_candidate,
)
from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging,
)
from setp_solver.algorithms.resetp_alns.support.fleet import (
    normalize_solution_vehicle_trips,
)
from setp_solver.check import CUSTOMER_COVERAGE, check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import ChargingAction, Route, Solution
from v2_solver import _apply_mechanism_experts


@dataclass(frozen=True)
class RouteColumn:
    key: tuple[Any, ...]
    route: Route
    actions: tuple[ChargingAction, ...]
    customers: frozenset[str]
    proxy_cost: float
    source: str


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def _customer_ids(route: Route, instance: Any) -> tuple[str, ...]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    return tuple(
        node_id
        for node_id in route.node_sequence
        if node_lookup.get(node_id) is not None
        and node_lookup[node_id].node_type.lower() == "c"
    )


def _column_key(
    route: Route,
    actions: tuple[ChargingAction, ...],
    instance: Any,
) -> tuple[Any, ...]:
    action_key = tuple(
        sorted(
            (
                action.station_id,
                round(float(action.energy_kwh), 9),
                round(float(action.occupancy_minutes), 9),
                round(float(action.charge_start_second), 6),
                int(action.charge_day_offset),
            )
            for action in actions
        )
    )
    return (
        route.home_depot_id,
        route.vehicle_type.lower(),
        _customer_ids(route, instance),
        tuple(
            node_id
            for node_id in route.node_sequence
            if node_id not in {route.home_depot_id}
        ),
        action_key,
    )


def _route_proxy_cost(
    route: Route,
    actions: tuple[ChargingAction, ...],
    *,
    instance: Any,
    carbon_profile: list[dict[str, Any]],
    prices: Any,
) -> float:
    return float(
        evaluate(
            Solution(routes=[route], charging_actions=list(actions)),
            instance,
            carbon_profile,
            prices,
        )["total_cost"]
    )


def _add_column(
    columns: dict[tuple[Any, ...], RouteColumn],
    *,
    route: Route,
    actions: tuple[ChargingAction, ...],
    source: str,
    instance: Any,
    carbon_profile: list[dict[str, Any]],
    prices: Any,
) -> bool:
    customers = frozenset(_customer_ids(route, instance))
    if not customers:
        return False
    route_violations = [
        violation
        for violation in check_solution(
            Solution(routes=[route], charging_actions=list(actions)),
            instance,
            prices,
        )
        if violation.type != CUSTOMER_COVERAGE
    ]
    if route_violations:
        return False
    key = _column_key(route, actions, instance)
    if key in columns:
        return False
    columns[key] = RouteColumn(
        key=key,
        route=route,
        actions=actions,
        customers=customers,
        proxy_cost=_route_proxy_cost(
            route,
            actions,
            instance=instance,
            carbon_profile=carbon_profile,
            prices=prices,
        ),
        source=source,
    )
    return True


def _base_columns(
    solution: Solution,
    *,
    instance: Any,
    carbon_profile: list[dict[str, Any]],
    prices: Any,
) -> dict[tuple[Any, ...], RouteColumn]:
    columns: dict[tuple[Any, ...], RouteColumn] = {}
    for route in solution.routes:
        actions = tuple(
            action
            for action in solution.charging_actions
            if action.vehicle_id == route.vehicle_id
        )
        _add_column(
            columns,
            route=route,
            actions=actions,
            source="alns_parent",
            instance=instance,
            carbon_profile=carbon_profile,
            prices=prices,
        )
    return columns


def _hgs_route_columns(
    *,
    solution: Solution,
    instance: Any,
    carbon_profile: list[dict[str, Any]],
    prices: Any,
    seed: int,
    native_generations: int,
) -> tuple[list[RouteColumn], dict[str, Any]]:
    engine = OfficialHGSLibrary()
    raw_columns: dict[tuple[Any, ...], RouteColumn] = {}
    native_calls = 0
    native_cpu = 0.0
    native_wall = 0.0
    native_routes = 0
    rejected_ev_repairs = 0
    for generation in range(max(1, int(native_generations))):
        result = official_hgs_order(
            instance=instance,
            initial_solution=solution,
            capacity=_price(prices, "Q_capacity"),
            speed_m_per_second=_price(prices, "v_speed_ms"),
            config=HGSAdapterConfig(
                seed=int(seed) * 1_000_003 + generation,
                no_improvement_iterations=100,
            ),
            library=engine,
        )
        native_calls += int(result.native_calls)
        native_cpu += float(result.native_cpu_seconds)
        native_wall += float(result.wall_seconds)
        for depot_id, routes in sorted(result.routes_by_depot.items()):
            for route_index, customers in enumerate(routes):
                native_routes += 1
                cv_route = Route(
                    vehicle_id=f"CVHGS_{generation}_{depot_id}_{route_index}",
                    vehicle_type="cv",
                    home_depot_id=depot_id,
                    node_sequence=[depot_id, *customers, depot_id],
                )
                _add_column(
                    raw_columns,
                    route=cv_route,
                    actions=(),
                    source="official_hgs_cv_route",
                    instance=instance,
                    carbon_profile=carbon_profile,
                    prices=prices,
                )
                ev_route = replace(
                    cv_route,
                    vehicle_id=f"EVHGS_{generation}_{depot_id}_{route_index}",
                    vehicle_type="ev",
                )
                try:
                    repaired, route_actions = repair_route_charging(
                        ev_route,
                        instance,
                        carbon_profile,
                        prices,
                    )
                except ValueError:
                    rejected_ev_repairs += 1
                    continue
                _add_column(
                    raw_columns,
                    route=repaired,
                    actions=tuple(route_actions),
                    source="official_hgs_ev_route",
                    instance=instance,
                    carbon_profile=carbon_profile,
                    prices=prices,
                )
    return list(raw_columns.values()), {
        "official_hgs_native_calls": native_calls,
        "official_hgs_native_cpu_milliseconds": round(1_000.0 * native_cpu, 6),
        "official_hgs_wall_milliseconds": round(1_000.0 * native_wall, 6),
        "official_hgs_native_routes": native_routes,
        "official_hgs_unique_route_columns": len(raw_columns),
        "official_hgs_rejected_ev_repairs": rejected_ev_repairs,
    }


def _assemble_cover(
    selected: list[RouteColumn],
    *,
    parent: Solution,
    instance: Any,
) -> Solution | None:
    routes: list[Route] = []
    actions: list[ChargingAction] = []
    for index, column in enumerate(selected):
        vehicle_type = column.route.vehicle_type.lower()
        vehicle_id = f"{vehicle_type.upper()}POOL_{index + 1}"
        routes.append(replace(column.route, vehicle_id=vehicle_id))
        actions.extend(
            replace(action, vehicle_id=vehicle_id)
            for action in column.actions
        )
    served = {
        customer_id
        for column in selected
        for customer_id in column.customers
    }
    services = [
        service
        for service in parent.cross_site_services
        if service.customer_id in served
    ]
    candidate = Solution(
        routes=routes,
        charging_actions=actions,
        cross_site_services=services,
    )
    try:
        candidate = normalize_solution_vehicle_trips(candidate, instance)
    except ValueError:
        return None
    return candidate


def _cover_signature(columns: list[RouteColumn]) -> tuple[tuple[Any, ...], ...]:
    return tuple(sorted((column.key for column in columns), key=repr))


def _route_pool_recombine(
    *,
    parent: Solution,
    parent_objective: float,
    context: EvaluationContext,
    hgs_columns: list[RouteColumn],
    max_proxy_covers: int = 256,
) -> tuple[Solution, float, dict[str, Any]]:
    base = _base_columns(
        parent,
        instance=context.instance,
        carbon_profile=context.carbon_profile,
        prices=context.prices,
    )
    base_keys = set(base)
    columns = dict(base)
    hgs_new_columns = 0
    for column in hgs_columns:
        if column.key not in columns:
            columns[column.key] = column
            hgs_new_columns += 1
    records = list(columns.values())
    customers = sorted(
        node.node_id
        for node in context.instance.nodes
        if node.node_type.lower() == "c"
    )
    customer_index = {customer_id: index for index, customer_id in enumerate(customers)}
    cover = np.zeros((len(customers), len(records)), dtype=float)
    for column_index, column in enumerate(records):
        for customer_id in column.customers:
            if customer_id in customer_index:
                cover[customer_index[customer_id], column_index] = 1.0
    proxy = np.array(
        [
            float(column.proxy_cost) + 1.0e-10 * index
            for index, column in enumerate(records)
        ],
        dtype=float,
    )
    rows = [cover]
    lower = [np.ones(len(customers), dtype=float)]
    upper = [np.ones(len(customers), dtype=float)]
    base_signature = _cover_signature(list(base.values()))
    best_solution = parent
    best_objective = float(parent_objective)
    activity: dict[str, Any] = {
        "route_pool_columns": len(records),
        "route_pool_parent_columns": len(base),
        "route_pool_new_hgs_columns": hgs_new_columns,
        "route_pool_proxy_covers": 0,
        "route_pool_duplicate_covers": 0,
        "route_pool_infeasible_covers": 0,
        "route_pool_infeasible_examples": [],
        "route_pool_full_evaluations": 0,
        "route_pool_improvements": 0,
        "accepted_hgs_routes": 0,
    }
    target = (
        int(context.budget.target_count)
        if context.budget is not None
        else 0
    )
    for _ in range(max(1, int(max_proxy_covers))):
        if context.budget is not None and context.budget.count >= target:
            break
        matrix = np.vstack(rows)
        constraint = LinearConstraint(
            matrix,
            np.concatenate(lower),
            np.concatenate(upper),
        )
        result = milp(
            c=proxy,
            integrality=np.ones(len(records), dtype=int),
            bounds=Bounds(
                np.zeros(len(records), dtype=float),
                np.ones(len(records), dtype=float),
            ),
            constraints=constraint,
            options={"time_limit": 0.5, "mip_rel_gap": 0.0},
        )
        if not bool(result.success) or result.x is None:
            break
        selected_indices = [
            index for index, value in enumerate(result.x) if value > 0.5
        ]
        if not selected_indices:
            break
        selected = [records[index] for index in selected_indices]
        activity["route_pool_proxy_covers"] += 1
        no_good = np.zeros(len(records), dtype=float)
        no_good[selected_indices] = 1.0
        rows.append(no_good.reshape(1, -1))
        lower.append(np.array([-math.inf], dtype=float))
        upper.append(np.array([len(selected_indices) - 1.0], dtype=float))
        signature = _cover_signature(selected)
        if signature == base_signature:
            activity["route_pool_duplicate_covers"] += 1
            continue
        candidate = _assemble_cover(
            selected,
            parent=parent,
            instance=context.instance,
        )
        violations = (
            []
            if candidate is not None
            else ["assembly_failed"]
        )
        if candidate is not None:
            violations = check_solution(
                candidate,
                context.instance,
                context.prices,
            )
        if candidate is None or violations:
            activity["route_pool_infeasible_covers"] += 1
            if len(activity["route_pool_infeasible_examples"]) < 3:
                activity["route_pool_infeasible_examples"].append(
                    str(
                        violations[0]
                        if violations
                        else "unknown_infeasibility"
                    )
                )
            continue
        candidate, objective = score_search_candidate(
            candidate,
            context,
            channel="official_hgs_route_pool_recombination",
        )
        activity["route_pool_full_evaluations"] += 1
        if objective < best_objective - 1.0e-9:
            best_solution = candidate
            best_objective = float(objective)
            activity["route_pool_improvements"] += 1
            activity["accepted_hgs_routes"] = sum(
                column.key not in base_keys for column in selected
            )
    return best_solution, best_objective, activity


def _run_v3(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any,
    hgs_share: float,
    mechanism_share: float,
    use_hgs_route_breeding: bool,
    use_mechanism_experts: bool,
    algorithm_label: str,
) -> ArmResult:
    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    warm = make_shared_initial_solution(bundle, prices=prices)
    warm_cost = independent_cost(bundle_dir, warm, prices)
    total = max(0, int(eval_budget))
    if total == 0:
        return ArmResult(
            algorithm=algorithm_label,
            best_solution=warm,
            best_cost=warm_cost,
            evaluations=0,
            elapsed_seconds=time.perf_counter() - started,
            route_count=len(warm.routes),
            feasible=not check_solution(warm, bundle.instance, prices),
            mechanism_activity={},
        )
    route_pool_room = max(
        1, int(round(total * max(0.0, float(hgs_share))))
    )
    mechanism_room = max(
        1, int(round(total * max(0.0, float(mechanism_share))))
    )
    if route_pool_room + mechanism_room > total:
        mechanism_room = max(0, total - route_pool_room)
    education_room = max(0, total - route_pool_room - mechanism_room)
    educated = run_pure_alns(
        bundle_dir,
        seed=seed,
        eval_budget=education_room,
        prices=prices,
        initial_solution=warm,
    )
    solution = educated.best_solution
    objective = float(educated.best_cost)

    expert_limit = mechanism_room if use_mechanism_experts else 0
    expert_budget = EvalBudget(limit=expert_limit, target=expert_limit)
    expert_context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=expert_budget,
    )
    if use_mechanism_experts:
        solution, objective, expert_activity = _apply_mechanism_experts(
            solution=solution,
            objective=objective,
            context=expert_context,
        )
    else:
        expert_activity = {
            "development_ablation": "mechanism_experts_removed",
            "depot_expert_improvements": 0,
            "fleet_charge_expert_improvements": 0,
        }
    expert_filler = mechanism_room - expert_budget.count
    expert_filler_activity: dict[str, Any] = {}
    if expert_filler:
        continuation = run_pure_alns(
            bundle_dir,
            seed=seed + 9_999_991,
            eval_budget=expert_filler,
            prices=prices,
            initial_solution=solution,
        )
        expert_filler_activity = dict(continuation.mechanism_activity)
        if continuation.best_cost < objective - 1.0e-9:
            solution = continuation.best_solution
            objective = float(continuation.best_cost)
    post_expert_cost = float(objective)

    native_activity: dict[str, Any] = {
        "development_ablation": "official_hgs_route_breeding_removed",
        "official_hgs_native_calls": 0,
    }
    hgs_columns: list[RouteColumn] = []
    if use_hgs_route_breeding:
        hgs_columns, native_activity = _hgs_route_columns(
            solution=solution,
            instance=bundle.instance,
            carbon_profile=bundle.carbon_profile,
            prices=prices,
            seed=seed,
            native_generations=max(1, route_pool_room),
        )
    pool_budget = EvalBudget(limit=route_pool_room, target=route_pool_room)
    pool_context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=pool_budget,
    )
    pool_activity: dict[str, Any] = {}
    if use_hgs_route_breeding:
        solution, objective, pool_activity = _route_pool_recombine(
            parent=solution,
            parent_objective=objective,
            context=pool_context,
            hgs_columns=hgs_columns,
        )
    pool_filler = route_pool_room - pool_budget.count
    pool_filler_activity: dict[str, Any] = {}
    if pool_filler:
        continuation = run_pure_alns(
            bundle_dir,
            seed=seed + 7_777_771,
            eval_budget=pool_filler,
            prices=prices,
            initial_solution=solution,
        )
        pool_filler_activity = dict(continuation.mechanism_activity)
        if continuation.best_cost < objective - 1.0e-9:
            solution = continuation.best_solution
            objective = float(continuation.best_cost)
    pool_cost = float(objective)

    evaluations = (
        educated.evaluations
        + pool_budget.count
        + pool_filler
        + expert_budget.count
        + expert_filler
    )
    return ArmResult(
        algorithm=algorithm_label,
        best_solution=solution,
        best_cost=float(objective),
        evaluations=evaluations,
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(solution.routes),
        feasible=not check_solution(solution, bundle.instance, prices),
        mechanism_activity={
            "warm_cost": float(warm_cost),
            "educated_cost": float(educated.best_cost),
            "post_expert_cost": post_expert_cost,
            "post_route_pool_cost": pool_cost,
            "final_cost": float(objective),
            "development_use_hgs_route_breeding": bool(
                use_hgs_route_breeding
            ),
            "development_use_mechanism_experts": bool(
                use_mechanism_experts
            ),
            "alns_education_evaluations": educated.evaluations,
            "route_pool_evaluations": pool_budget.count,
            "route_pool_filler_alns_evaluations": pool_filler,
            "expert_evaluations": expert_budget.count,
            "expert_filler_alns_evaluations": expert_filler,
            "official_hgs_activity": native_activity,
            "route_pool_activity": pool_activity,
            "expert_activity": expert_activity,
            "route_pool_filler_activity": pool_filler_activity,
            "expert_filler_activity": expert_filler_activity,
        },
    )


def run_mechanism_hgs_alns_v3(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    hgs_share: float = 0.02,
    mechanism_share: float = 0.12,
) -> ArmResult:
    """Run the full official-route-breeding HGS--ALNS candidate."""

    return _run_v3(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        hgs_share=hgs_share,
        mechanism_share=mechanism_share,
        use_hgs_route_breeding=True,
        use_mechanism_experts=True,
        algorithm_label="mechanism_hgs_alns_v3_route_breeding",
    )


def run_mechanism_hgs_alns_v3_without_hgs(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    hgs_share: float = 0.02,
    mechanism_share: float = 0.12,
) -> ArmResult:
    """Development ablation that removes official-HGS route breeding."""

    return _run_v3(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        hgs_share=hgs_share,
        mechanism_share=mechanism_share,
        use_hgs_route_breeding=False,
        use_mechanism_experts=True,
        algorithm_label="mechanism_hgs_alns_v3_without_hgs_ablation",
    )


def run_mechanism_hgs_alns_v3_without_experts(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    hgs_share: float = 0.02,
    mechanism_share: float = 0.12,
) -> ArmResult:
    """Development ablation that removes mechanism-specific experts."""

    return _run_v3(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        hgs_share=hgs_share,
        mechanism_share=mechanism_share,
        use_hgs_route_breeding=True,
        use_mechanism_experts=False,
        algorithm_label="mechanism_hgs_alns_v3_without_experts_ablation",
    )
