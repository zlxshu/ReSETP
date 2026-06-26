"""Feasibility-preserving insertion repair shared by ALNS adapters."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from ..check import check_solution
from ..cost import _arc_loads, ev_arc_energy_kwh, evaluate, route_node_schedule
from ..instance_loader import Instance, Node
from ..solution import ChargingAction, Route, Solution
from .charging import repair_route_charging
from .evaluation import BIG_M, EvaluationContext, fairness_context_for_solution, record_repair_delta
from .fleet import normalize_solution_vehicle_trips
from .repair_scoring import route_model_cost_delta
from .timing import timed_section


MAX_ROUTE_CANDIDATES = 4
MAX_POSITIONS_PER_ROUTE = 2
MAX_EXISTING_EV_ROUTE_CANDIDATES = 1


@dataclass(frozen=True)
class InsertionOption:
    score: float
    solution: Solution
    route_idx: int | None
    position: int | None
    vehicle_type: str
    opened_new_route: bool = False


def enumerate_feasible_insertions(
    solution: Solution,
    customer_id: str,
    context: EvaluationContext,
    policy: Any,
    *,
    max_route_candidates: int = MAX_ROUTE_CANDIDATES,
    max_positions_per_route: int = MAX_POSITIONS_PER_ROUTE,
    allow_new_route: bool = True,
) -> list[InsertionOption]:
    """Return route-local feasible insertions for one missing customer.

    The returned candidates may still miss other pending customers during a
    multi-customer repair. They are therefore route-local feasible, and the
    caller must run one final full-solution feasibility check after all pending
    customers are inserted.
    """

    options: list[InsertionOption] = []
    route_items = _ranked_routes(solution.routes, customer_id, context.instance, max_route_candidates)
    ev_route_candidates = 0
    for route_idx, route in route_items:
        if route.vehicle_type.lower() == "ev":
            if ev_route_candidates >= MAX_EXISTING_EV_ROUTE_CANDIDATES:
                continue
            ev_route_candidates += 1
        customers = route_customers(route, context.instance)
        positions = _ranked_positions(route, customer_id, context.instance, max_positions_per_route)
        for insert_at in positions:
            candidate_customers = [*customers[:insert_at], customer_id, *customers[insert_at:]]
            built = _solution_with_route_customers(solution, route_idx, route, candidate_customers, context, policy)
            if built is None:
                continue
            candidate, candidate_route, route_actions = built
            base_actions = [action for action in solution.charging_actions if action.vehicle_id == route.vehicle_id]
            score = _delta_score(candidate, candidate_route, route_actions, context, base_route=route, base_actions=base_actions)
            options.append(
                InsertionOption(
                    score=score,
                    solution=candidate,
                    route_idx=route_idx,
                    position=insert_at,
                    vehicle_type=candidate_route.vehicle_type.lower(),
                )
            )

    if allow_new_route:
        options.extend(_new_route_options(solution, customer_id, context, policy))
    return sorted(options, key=lambda item: (item.score, item.opened_new_route, item.vehicle_type, _solution_key(item.solution)))


def repair_removed_customers(
    partial_solution: Solution,
    removed_customers: list[str],
    context: EvaluationContext,
    policy: Any,
    *,
    mode: str,
    allow_new_route: bool = True,
) -> Solution | None:
    pending = list(dict.fromkeys(removed_customers))
    current = partial_solution
    while pending:
        scored: list[tuple[float, float, str, Solution]] = []
        for customer_id in pending:
            options = enumerate_feasible_insertions(current, customer_id, context, policy, allow_new_route=allow_new_route)
            if not options:
                continue
            best = options[0]
            ordered = [option.score for option in options]
            if mode == "regret3":
                comparison = ordered[2] if len(ordered) > 2 else ordered[-1]
                primary = -(comparison - best.score)
            elif mode == "regret2":
                comparison = ordered[1] if len(ordered) > 1 else ordered[0]
                primary = -(comparison - best.score)
            elif mode == "greedy":
                primary = best.score
            else:
                raise ValueError(f"unknown feasible repair mode: {mode}")
            scored.append((primary, best.score, customer_id, best.solution))
        if not scored:
            return None
        _, _, customer_id, current = min(scored, key=lambda item: (item[0], item[1], item[2]))
        pending.remove(customer_id)
    if _is_full_solution_feasible(current, context, policy):
        return _normalize_for_policy(current, context, policy)
    fallback = _all_cv_fallback(current, context, policy)
    if fallback is not None and _is_full_solution_feasible(fallback, context, policy):
        return _normalize_for_policy(fallback, context, policy)
    return None


def route_customers(route: Route, instance: Instance) -> list[str]:
    if not _structure_cache_enabled():
        node_lookup = {node.node_id: node for node in instance.nodes}
        return [
            node_id
            for node_id in route.node_sequence
            if node_lookup.get(node_id) is not None and node_lookup[node_id].node_type.lower() == "c"
        ]
    cache = _instance_cache(instance, "_setp_route_customer_cache")
    key = _route_key(route)
    cached = cache.get(key)
    if cached is not None:
        return list(cached)
    node_lookup = _node_lookup(instance)
    customers = tuple(
        node_id
        for node_id in route.node_sequence
        if node_lookup.get(node_id) is not None and node_lookup[node_id].node_type.lower() == "c"
    )
    if len(cache) > 100_000:
        cache.clear()
    cache[key] = customers
    return list(customers)


def nearest_depot_id(customer_id: str, instance: Instance) -> str:
    if not _structure_cache_enabled():
        customer = next(node for node in instance.nodes if node.node_id == customer_id)
        depots = _depots(instance)
        return min(depots, key=lambda depot: (instance.distance(depot.node_id, customer.node_id), depot.node_id)).node_id
    cache = _instance_cache(instance, "_setp_nearest_depot_cache")
    if customer_id in cache:
        return str(cache[customer_id])
    depots = _depots(instance)
    nearest = min(depots, key=lambda depot: (instance.distance(depot.node_id, customer_id), depot.node_id)).node_id
    cache[customer_id] = nearest
    return str(nearest)


def route_distance(route: Route, instance: Instance) -> float:
    if not _structure_cache_enabled():
        return sum(float(instance.distance(a, b)) for a, b in zip(route.node_sequence, route.node_sequence[1:]))
    cache = _instance_cache(instance, "_setp_route_distance_cache")
    key = _route_key(route)
    cached = cache.get(key)
    if cached is not None:
        return float(cached)
    distance = sum(float(instance.distance(a, b)) for a, b in zip(route.node_sequence, route.node_sequence[1:]))
    if len(cache) > 100_000:
        cache.clear()
    cache[key] = distance
    return float(distance)


def _ranked_routes(routes: list[Route], customer_id: str, instance: Instance, limit: int) -> list[tuple[int, Route]]:
    scored = []
    for idx, route in enumerate(routes):
        customers = route_customers(route, instance)
        if not customers:
            continue
        anchors = customers or route.node_sequence
        proximity = min(float(instance.distance(customer_id, node_id)) for node_id in anchors)
        scored.append((proximity, idx, route))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [(idx, route) for _, idx, route in scored[: max(1, int(limit))]]


def _ranked_positions(route: Route, customer_id: str, instance: Instance, limit: int) -> list[int]:
    customers = route_customers(route, instance)
    scored: list[tuple[float, int]] = []
    clean = [route.home_depot_id, *customers, route.home_depot_id]
    for customer_pos in range(len(customers) + 1):
        prev_node = clean[customer_pos]
        next_node = clean[customer_pos + 1]
        delta = float(instance.distance(prev_node, customer_id)) + float(instance.distance(customer_id, next_node)) - float(instance.distance(prev_node, next_node))
        scored.append((delta, customer_pos))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [pos for _, pos in scored[: max(1, int(limit))]]


def _solution_with_route_customers(
    solution: Solution,
    route_idx: int,
    route: Route,
    customers: list[str],
    context: EvaluationContext,
    policy: Any,
) -> tuple[Solution, Route, list[ChargingAction]] | None:
    vehicle_type = route.vehicle_type.lower()
    clean_route = Route(route.vehicle_id, vehicle_type, route.home_depot_id, [route.home_depot_id, *customers, route.home_depot_id])
    actions = [action for action in solution.charging_actions if action.vehicle_id != route.vehicle_id]
    route_actions: list[ChargingAction] = []
    if vehicle_type == "ev":
        repaired = _repair_ev_route_cached(clean_route, context)
        if repaired is None:
            return None
        clean_route, route_actions = repaired
        if bool(getattr(policy, "require_charging_signal", False)) and not route_actions:
            return None
    if not _route_locally_feasible(clean_route, route_actions, context):
        return None
    routes = list(solution.routes)
    routes[route_idx] = clean_route
    return Solution(routes=routes, charging_actions=[*actions, *route_actions], cross_site_services=solution.cross_site_services), clean_route, route_actions


def _new_route_options(solution: Solution, customer_id: str, context: EvaluationContext, policy: Any) -> list[InsertionOption]:
    options: list[InsertionOption] = []
    depot_id = nearest_depot_id(customer_id, context.instance)
    cv_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv")
    ev_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev")
    if cv_count < int(getattr(policy, "max_cv", 10**9)):
        vehicle_id = _next_vehicle_id(solution.routes, "CV")
        route = Route(vehicle_id, "cv", depot_id, [depot_id, customer_id, depot_id])
        record_repair_delta(context)
        if _route_locally_feasible(route, [], context):
            candidate = Solution(routes=[*solution.routes, route], charging_actions=list(solution.charging_actions), cross_site_services=solution.cross_site_services)
            options.append(InsertionOption(route_model_cost_delta(route, [], context), candidate, None, None, "cv", opened_new_route=True))
    if ev_count < int(getattr(policy, "max_ev", 10**9)):
        vehicle_id = _next_vehicle_id(solution.routes, "EV")
        route = Route(vehicle_id, "ev", depot_id, [depot_id, customer_id, depot_id])
        repaired_payload = _repair_ev_route_cached(route, context)
        repaired, actions = repaired_payload if repaired_payload is not None else (None, [])
        record_repair_delta(context)
        if repaired is not None and (not bool(getattr(policy, "require_charging_signal", False)) or actions) and _route_locally_feasible(repaired, actions, context):
            candidate = Solution(routes=[*solution.routes, repaired], charging_actions=[*solution.charging_actions, *actions], cross_site_services=solution.cross_site_services)
            options.append(InsertionOption(route_model_cost_delta(repaired, actions, context), candidate, None, None, "ev", opened_new_route=True))
    return options


def _route_locally_feasible(route: Route, actions: list[ChargingAction], context: EvaluationContext) -> bool:
    if not _structure_cache_enabled():
        return _route_locally_feasible_uncached(route, actions, context)
    cache = _instance_cache(context.instance, "_setp_local_feasible_cache")
    key = (_route_key(route), _action_key(actions))
    cached = cache.get(key)
    if cached is not None:
        return bool(cached)
    feasible = _route_locally_feasible_uncached(route, actions, context)
    if len(cache) > 200_000:
        cache.clear()
    cache[key] = bool(feasible)
    return bool(feasible)


def _route_locally_feasible_uncached(route: Route, actions: list[ChargingAction], context: EvaluationContext) -> bool:
    node_lookup = _node_lookup(context.instance)
    if not route.node_sequence or route.node_sequence[0] != route.home_depot_id or route.node_sequence[-1] != route.home_depot_id:
        return False
    if route.home_depot_id not in node_lookup or node_lookup[route.home_depot_id].node_type.lower() != "d":
        return False
    if any(node_id not in node_lookup for node_id in route.node_sequence):
        return False
    loads = _arc_loads(route.node_sequence, node_lookup)
    if any(load < -1e-9 or load > _price(context.prices, "Q_capacity") + 1e-9 for load in loads):
        return False
    for row in route_node_schedule(route, context.instance, context.prices, charging_actions=actions):
        if row.t_start > float(node_lookup[row.node_id].due_time) + 1e-9:
            return False
    if route.vehicle_type.lower() != "ev":
        return True
    return _ev_battery_locally_feasible(route, actions, context, node_lookup, loads)


def _ev_battery_locally_feasible(
    route: Route,
    actions: list[ChargingAction],
    context: EvaluationContext,
    node_lookup: dict[str, Node],
    loads: list[float],
) -> bool:
    battery = _price(context.prices, "initial_ev_battery_kwh")
    cap = _price(context.prices, "B_battery_kwh")
    charging_by_node: dict[str, float] = {}
    for action in actions:
        if action.vehicle_id == route.vehicle_id:
            charging_by_node[action.station_id] = charging_by_node.get(action.station_id, 0.0) + float(action.energy_kwh)
    start_node = route.node_sequence[0]
    if node_lookup[start_node].node_type.lower() == "d":
        battery += charging_by_node.get(start_node, 0.0)
    if battery > cap + 1e-9:
        return False
    for (from_node, to_node), load in zip(zip(route.node_sequence, route.node_sequence[1:]), loads):
        battery -= ev_arc_energy_kwh(context.instance.distance(from_node, to_node), load, context.prices)
        if battery < -1e-9:
            return False
        if node_lookup[to_node].node_type.lower() == "f":
            battery += charging_by_node.get(to_node, 0.0)
            if battery > cap + 1e-9:
                return False
    return True


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def _is_full_solution_feasible(solution: Solution, context: EvaluationContext, policy: Any) -> bool:
    if bool(getattr(policy, "require_charging_signal", False)) and not any(float(action.energy_kwh) > 1e-9 for action in solution.charging_actions):
        return False
    try:
        solution = _normalize_for_policy(solution, context, policy)
    except ValueError:
        return False
    with timed_section(context, "repair_full_check"):
        return not check_solution(
            solution,
            context.instance,
            context.prices,
            fairness_context=fairness_context_for_solution(solution, context),
            fairness_enabled=context.fairness_enabled,
        )


def _all_cv_fallback(solution: Solution, context: EvaluationContext, policy: Any) -> Solution | None:
    if bool(getattr(policy, "require_charging_signal", False)):
        return None
    routes = [
        Route(_next_vehicle_id([], f"CV_REPAIR_{idx}_"), "cv", route.home_depot_id, [route.home_depot_id, *route_customers(route, context.instance), route.home_depot_id])
        for idx, route in enumerate(solution.routes, start=1)
        if route_customers(route, context.instance)
    ]
    fallback = Solution(routes=routes, charging_actions=[], cross_site_services=solution.cross_site_services)
    return fallback


def _normalize_for_policy(solution: Solution, context: EvaluationContext, policy: Any) -> Solution:
    return normalize_solution_vehicle_trips(
        solution,
        context.instance,
        max_cv=int(getattr(policy, "max_cv", getattr(context.instance, "num_cv", 10**9) or 10**9)),
        max_ev=int(getattr(policy, "max_ev", getattr(context.instance, "num_ev", 10**9) or 10**9)),
    )


def _delta_score(
    solution: Solution,
    route: Route,
    route_actions: list[ChargingAction],
    context: EvaluationContext,
    *,
    base_route: Route | None = None,
    base_actions: list[ChargingAction] | None = None,
) -> float:
    record_repair_delta(context)
    score = route_model_cost_delta(route, route_actions, context, base_route=base_route, base_actions=base_actions)
    if score >= BIG_M:
        return _solution_cost(solution, context)
    return score


def _solution_cost(solution: Solution, context: EvaluationContext) -> float:
    try:
        with timed_section(context, "repair_fallback_solution_cost"):
            return float(evaluate(solution, context.instance, context.carbon_profile, context.prices, carbon_quota_kg=context.carbon_quota_kg)["total_cost"])
    except Exception:
        return BIG_M


def _solution_key(solution: Solution) -> tuple[Any, ...]:
    return tuple((route.vehicle_type.lower(), route.home_depot_id, tuple(route.node_sequence)) for route in solution.routes)


def _depots(instance: Instance) -> list[Node]:
    if not _structure_cache_enabled():
        return sorted((node for node in instance.nodes if node.node_type.lower() == "d"), key=lambda node: node.node_id)
    cache = _instance_cache(instance, "_setp_depot_cache")
    if "depots" not in cache:
        cache["depots"] = tuple(sorted((node for node in instance.nodes if node.node_type.lower() == "d"), key=lambda node: node.node_id))
    return list(cache["depots"])


def _node_lookup(instance: Instance) -> dict[str, Node]:
    if not _structure_cache_enabled():
        return {node.node_id: node for node in instance.nodes}
    cache = _instance_cache(instance, "_setp_node_lookup_cache")
    if "lookup" not in cache:
        cache["lookup"] = {node.node_id: node for node in instance.nodes}
    return cache["lookup"]


def _instance_cache(instance: Instance, name: str) -> dict[Any, Any]:
    cached = getattr(instance, name, None)
    if cached is None:
        cached = {}
        object.__setattr__(instance, name, cached)
    return cached


def _route_key(route: Route) -> tuple[str, str, str, tuple[str, ...]]:
    key = (str(route.vehicle_id), route.vehicle_type.lower(), str(route.home_depot_id), tuple(str(node_id) for node_id in route.node_sequence))
    return key


def _action_key(actions: list[ChargingAction]) -> tuple[tuple[str, str, float, float, float], ...]:
    return tuple(
        sorted(
            (
                str(action.vehicle_id),
                str(action.station_id),
                round(float(action.energy_kwh), 9),
                round(float(action.occupancy_minutes), 9),
                round(float(action.charge_start_second), 9),
            )
            for action in actions
        )
    )


def _repair_ev_route_cached(route: Route, context: EvaluationContext) -> tuple[Route, list[ChargingAction]] | None:
    if not _structure_cache_enabled():
        try:
            repaired, actions = repair_route_charging(route, context.instance, context.carbon_profile, context.prices)
        except ValueError:
            return None
        return repaired, list(actions)
    cache = _instance_cache(context.instance, "_setp_ev_repair_cache")
    key = _route_key(route)
    if key in cache:
        cached = cache[key]
        if cached is None:
            return None
        repaired, actions = cached
        return repaired, list(actions)
    try:
        repaired, actions = repair_route_charging(route, context.instance, context.carbon_profile, context.prices)
    except ValueError:
        cache[key] = None
        return None
    if len(cache) > 200_000:
        cache.clear()
    cache[key] = (repaired, tuple(actions))
    return repaired, list(actions)


def _structure_cache_enabled() -> bool:
    return os.environ.get("SETP_ALNS_CRUSH_REPAIR_STRUCTURE_CACHE", "0").lower() not in {"0", "false", "no"}


def _next_vehicle_id(routes: list[Route], prefix: str) -> str:
    used = {route.vehicle_id for route in routes}
    idx = 1
    candidate = f"{prefix}{idx}"
    while candidate in used:
        idx += 1
        candidate = f"{prefix}{idx}"
    return candidate
