"""Small bounded local search used after ALNS destroy/repair."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
import os
import time

from ..check import check_solution
from ..instance_loader import Instance
from ..solution import ChargingAction, Route, Solution
from .charging import repair_route_charging
from .evaluation import EvaluationContext, fairness_context_for_solution, score_reference


@dataclass(frozen=True)
class RvndResult:
    solution: Solution | None
    call_count: int
    improve_count: int
    moves_used: int
    time_seconds: float
    route_count_delta: int


def improve_solution_locally(
    solution: Solution,
    context: EvaluationContext,
    *,
    max_passes: int = 1,
    max_neighbors: int = 24,
) -> Solution:
    """Run a bounded 2-opt/Or-opt/relocate improvement pass."""

    if os.environ.get("SETP_ALNS_CRUSH_LOCAL_SEARCH", "1").lower() in {"0", "false", "no"}:
        return solution
    best = solution
    best_score = score_reference(best, context)
    for _ in range(max(1, int(max_passes))):
        improved = False
        for candidate in _neighborhood(best, context, max_neighbors=max_neighbors):
            score = score_reference(candidate, context)
            if score < best_score - 1e-9:
                best = candidate
                best_score = score
                improved = True
                break
        if not improved:
            break
    return best


def rvnd_swapstar_intensify(
    solution: Solution,
    context: EvaluationContext,
    *,
    max_moves: int = 120,
) -> RvndResult:
    """Run a bounded inter-route intensification pass for diagnostics."""

    started = time.perf_counter()
    before_routes = len(solution.routes)
    best = solution
    best_score = score_reference(best, context)
    moves_used = 0
    improve_count = 0
    neighborhoods = (
        lambda item: _relocate_neighbors(item, context),
        lambda item: _swapstar_lite_neighbors(item, context),
        lambda item: _two_opt_star_neighbors(item, context),
    )
    for neighborhood in neighborhoods:
        improved = True
        while improved and moves_used < max_moves:
            improved = False
            for candidate in neighborhood(best):
                moves_used += 1
                score = score_reference(candidate, context)
                if score < best_score - 1e-9:
                    best = candidate
                    best_score = score
                    improve_count += 1
                    improved = True
                    break
                if moves_used >= max_moves:
                    break
    return RvndResult(
        solution=best,
        call_count=1,
        improve_count=improve_count,
        moves_used=moves_used,
        time_seconds=max(0.0, time.perf_counter() - started),
        route_count_delta=len(best.routes) - before_routes,
    )


def _neighborhood(solution: Solution, context: EvaluationContext, *, max_neighbors: int) -> Iterator[Solution]:
    produced = 0
    for candidate in _two_opt_neighbors(solution, context):
        yield candidate
        produced += 1
        if produced >= max_neighbors:
            return
    for candidate in _or_opt_neighbors(solution, context):
        yield candidate
        produced += 1
        if produced >= max_neighbors:
            return
    for candidate in _relocate_neighbors(solution, context):
        yield candidate
        produced += 1
        if produced >= max_neighbors:
            return


def _two_opt_neighbors(solution: Solution, context: EvaluationContext) -> Iterator[Solution]:
    for route_idx, route in enumerate(solution.routes):
        customers = _route_customers(route, context.instance)
        if len(customers) < 3:
            continue
        for left in range(len(customers) - 1):
            for right in range(left + 1, len(customers)):
                changed = list(customers)
                changed[left : right + 1] = reversed(changed[left : right + 1])
                candidate = _candidate_with_route_customers(solution, context, {route_idx: changed})
                if candidate is not None:
                    yield candidate


def _or_opt_neighbors(solution: Solution, context: EvaluationContext) -> Iterator[Solution]:
    for route_idx, route in enumerate(solution.routes):
        customers = _route_customers(route, context.instance)
        if len(customers) < 3:
            continue
        for src_pos, customer_id in enumerate(customers):
            remaining = [item for pos, item in enumerate(customers) if pos != src_pos]
            for dst_pos in range(len(remaining) + 1):
                if dst_pos == src_pos:
                    continue
                changed = list(remaining)
                changed.insert(dst_pos, customer_id)
                candidate = _candidate_with_route_customers(solution, context, {route_idx: changed})
                if candidate is not None:
                    yield candidate


def _relocate_neighbors(solution: Solution, context: EvaluationContext) -> Iterator[Solution]:
    for src_idx, src_route in enumerate(solution.routes):
        src_customers = _route_customers(src_route, context.instance)
        if len(src_customers) < 2:
            continue
        for dst_idx, dst_route in enumerate(solution.routes):
            if src_idx == dst_idx:
                continue
            dst_customers = _route_customers(dst_route, context.instance)
            for src_pos, customer_id in enumerate(src_customers):
                new_src = [item for pos, item in enumerate(src_customers) if pos != src_pos]
                for dst_pos in range(len(dst_customers) + 1):
                    new_dst = list(dst_customers)
                    new_dst.insert(dst_pos, customer_id)
                    candidate = _candidate_with_route_customers(solution, context, {src_idx: new_src, dst_idx: new_dst})
                    if candidate is not None:
                        yield candidate


def _swapstar_lite_neighbors(solution: Solution, context: EvaluationContext) -> Iterator[Solution]:
    for left_idx, left_route in enumerate(solution.routes):
        left_customers = _route_customers(left_route, context.instance)
        if not left_customers:
            continue
        for right_idx in range(left_idx + 1, len(solution.routes)):
            right_route = solution.routes[right_idx]
            right_customers = _route_customers(right_route, context.instance)
            if not right_customers:
                continue
            for left_pos, left_customer in enumerate(left_customers):
                for right_pos, right_customer in enumerate(right_customers):
                    new_left = list(left_customers)
                    new_right = list(right_customers)
                    new_left[left_pos] = right_customer
                    new_right[right_pos] = left_customer
                    candidate = _candidate_with_route_customers(
                        solution,
                        context,
                        {left_idx: new_left, right_idx: new_right},
                    )
                    if candidate is not None:
                        yield candidate


def _two_opt_star_neighbors(solution: Solution, context: EvaluationContext) -> Iterator[Solution]:
    for left_idx, left_route in enumerate(solution.routes):
        left_customers = _route_customers(left_route, context.instance)
        if len(left_customers) < 2:
            continue
        for right_idx in range(left_idx + 1, len(solution.routes)):
            right_route = solution.routes[right_idx]
            right_customers = _route_customers(right_route, context.instance)
            if len(right_customers) < 2:
                continue
            for left_cut in range(1, len(left_customers)):
                for right_cut in range(1, len(right_customers)):
                    new_left = [*left_customers[:left_cut], *right_customers[right_cut:]]
                    new_right = [*right_customers[:right_cut], *left_customers[left_cut:]]
                    if not new_left or not new_right:
                        continue
                    candidate = _candidate_with_route_customers(
                        solution,
                        context,
                        {left_idx: new_left, right_idx: new_right},
                    )
                    if candidate is not None:
                        yield candidate


def _candidate_with_route_customers(
    solution: Solution,
    context: EvaluationContext,
    route_customers: dict[int, list[str]],
) -> Solution | None:
    routes = list(solution.routes)
    changed_vehicle_ids = {routes[idx].vehicle_id for idx in route_customers}
    actions = [action for action in solution.charging_actions if action.vehicle_id not in changed_vehicle_ids]
    new_actions: list[ChargingAction] = []
    for route_idx, customers in route_customers.items():
        route = routes[route_idx]
        clean_route = replace(route, node_sequence=[route.home_depot_id, *customers, route.home_depot_id])
        if route.vehicle_type.lower() == "ev":
            try:
                clean_route, route_actions = repair_route_charging(
                    clean_route,
                    context.instance,
                    context.carbon_profile,
                    context.prices,
                )
            except ValueError:
                return None
            new_actions.extend(route_actions)
        routes[route_idx] = clean_route
    candidate = Solution(routes=routes, charging_actions=[*actions, *new_actions], cross_site_services=solution.cross_site_services)
    violations = check_solution(
        candidate,
        context.instance,
        context.prices,
        fairness_context=fairness_context_for_solution(candidate, context),
        fairness_enabled=context.fairness_enabled,
    )
    return None if violations else candidate


def _route_customers(route: Route, instance: Instance) -> list[str]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    return [
        node_id
        for node_id in route.node_sequence
        if node_lookup.get(node_id) is not None and node_lookup[node_id].node_type.lower() == "c"
    ]
