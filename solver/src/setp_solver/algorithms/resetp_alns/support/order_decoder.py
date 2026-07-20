"""Shared customer-order decoder used by LNS and ALNS diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Any

from setp_solver.check import check_solution
from setp_solver.cost import route_node_schedule
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES, PriceParameters
from setp_solver.solution import ChargingAction, Route, Solution
from setp_solver.algorithms.resetp_alns.support.charging import repair_route_charging
from setp_solver.algorithms.resetp_alns.support.fleet import normalize_solution_vehicle_trips


@dataclass
class OrderDecodeCache:
    decode_cache: dict[tuple[tuple[str, ...], tuple[tuple[str, float], ...], float], Solution] = field(default_factory=dict)
    route_feasible_cache: dict[tuple[str, tuple[str, ...]], bool] = field(default_factory=dict)
    route_distance_cache: dict[tuple[str, tuple[str, ...]], float] = field(default_factory=dict)


@dataclass
class OrderDecodeContext:
    instance: Instance
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES
    carbon_profile: list[dict[str, Any]] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)
    cache: OrderDecodeCache = field(default_factory=OrderDecodeCache)
    customer_ids: list[str] | None = None
    node_lookup: dict[str, Node] | None = None
    depots: list[Node] | None = None
    depots_by_customer: dict[str, tuple[str, ...]] | None = None

    def __post_init__(self) -> None:
        if self.node_lookup is None:
            self.node_lookup = {node.node_id: node for node in self.instance.nodes}
        if self.customer_ids is None:
            self.customer_ids = [node.node_id for node in self.instance.nodes if node.node_type.lower() == "c"]
        if self.depots is None:
            self.depots = sorted((node for node in self.instance.nodes if node.node_type.lower() == "d"), key=lambda node: node.node_id)
        if self.depots_by_customer is None:
            depots = self.depots or []
            self.depots_by_customer = {
                customer_id: tuple(
                    depot.node_id
                    for depot in sorted(
                        depots,
                        key=lambda depot, cid=customer_id: (float(self.instance.distance(depot.node_id, cid)), depot.node_id),
                    )
                )
                for customer_id in self.customer_ids
            }

    @property
    def customer_set(self) -> set[str]:
        return set(self.customer_ids or [])


def solution_order(solution: Solution, instance: Instance) -> list[str]:
    order: list[str] = []
    for route in solution.routes:
        order.extend(route_customers(route, instance))
    return order


def route_type_hints(solution: Solution, instance: Instance) -> dict[str, float]:
    hints: dict[str, float] = {}
    for route in solution.routes:
        value = 0.95 if route.vehicle_type.lower() == "ev" else 0.05
        for customer_id in route_customers(route, instance):
            hints[customer_id] = value
    return hints


def exploratory_type_hints(order: list[str], context: OrderDecodeContext, index: int = 0) -> dict[str, float]:
    probabilities = (0.05, 0.35, 0.65, 0.85, 1.0)
    probability = probabilities[int(index) % len(probabilities)]
    return {customer_id: 0.95 if context.rng.random() < probability else 0.05 for customer_id in order}


def mutated_type_hints(
    base: dict[str, float],
    order: list[str],
    context: OrderDecodeContext,
    *,
    flip_probability: float = 0.12,
    force_ev: bool = False,
) -> dict[str, float]:
    hints = {customer_id: float(base.get(customer_id, 0.05)) for customer_id in order}
    changed = False
    for customer_id in order:
        if context.rng.random() < float(flip_probability):
            hints[customer_id] = 0.05 if hints.get(customer_id, 0.05) >= 0.5 else 0.95
            changed = True
    if force_ev and order and (not changed or max(hints.values(), default=0.05) < 0.5):
        sample_size = max(1, min(len(order), len(order) // 3 or 1))
        for customer_id in context.rng.sample(order, sample_size):
            hints[customer_id] = 0.95
    return hints


def order_to_solution(
    order: list[str],
    context: OrderDecodeContext,
    *,
    current_solution: Solution | None = None,
    type_hints: dict[str, float] | None = None,
    ev_threshold: float = 0.82,
) -> Solution:
    ordered = complete_order(order, context)
    hints = type_hints or (route_type_hints(current_solution, context.instance) if current_solution is not None else {})
    type_key = tuple((customer_id, float(hints.get(customer_id, 0.05))) for customer_id in ordered)
    cache_key = (tuple(ordered), type_key, float(ev_threshold))
    cached = context.cache.decode_cache.get(cache_key)
    if cached is not None:
        return cached
    decoded = decode_order_like_random_key(ordered, context, dict(type_key), ev_threshold=float(ev_threshold))
    if len(context.cache.decode_cache) > 2048:
        context.cache.decode_cache.clear()
    context.cache.decode_cache[cache_key] = decoded
    return decoded


def complete_order(order: list[str], context: OrderDecodeContext) -> list[str]:
    seen: set[str] = set()
    customer_set = context.customer_set
    complete = [customer_id for customer_id in order if customer_id in customer_set and not (customer_id in seen or seen.add(customer_id))]
    missing = [customer_id for customer_id in (context.customer_ids or []) if customer_id not in seen]
    return [*complete, *missing]


def decode_order_like_random_key(
    ordered: list[str],
    context: OrderDecodeContext,
    type_keys: dict[str, float],
    *,
    ev_threshold: float,
) -> Solution:
    depots = context.depots or []
    plans: dict[str, list[list[str]]] = {depot.node_id: [] for depot in depots}
    for customer_id in ordered:
        append_customer_to_cached_plan(customer_id, plans, context)

    routes: list[Route] = []
    actions: list[ChargingAction] = []
    next_cv = 1
    next_ev = 1
    for depot_id, depot_plans in sorted(plans.items()):
        for customer_ids in depot_plans:
            avg_type_key = sum(type_keys.get(customer_id, 0.0) for customer_id in customer_ids) / max(1, len(customer_ids))
            if avg_type_key >= ev_threshold:
                route = Route(f"EV{next_ev}", "ev", depot_id, [depot_id, *customer_ids, depot_id])
                try:
                    repaired, route_actions = repair_route_charging(route, context.instance, context.carbon_profile, context.prices)
                    candidate = normalize_solution(Solution(routes=[*routes, repaired], charging_actions=[*actions, *route_actions]), context)
                    if not check_solution(candidate, context.instance, context.prices):
                        routes = list(candidate.routes)
                        actions = list(candidate.charging_actions)
                        next_ev += 1
                        continue
                except ValueError:
                    pass
            routes.append(Route(f"CV{next_cv}", "cv", depot_id, [depot_id, *customer_ids, depot_id]))
            next_cv += 1

    solution = normalize_solution(Solution(routes=routes, charging_actions=actions), context)
    if check_solution(solution, context.instance, context.prices):
        return all_cv_solution_for_order(ordered, context)
    return solution


def append_customer_to_cached_plan(customer_id: str, plans: dict[str, list[list[str]]], context: OrderDecodeContext) -> None:
    best_key: tuple[float, str, int, int] | None = None
    best_target: tuple[str, int | None] | None = None
    c_km = _price(context.prices, "c_km")
    fixed_cost = _price(context.prices, "vehicle_fixed_cost")
    depot_choices = (context.depots_by_customer or {}).get(customer_id, ())
    for depot_id in depot_choices:
        depot_plans = plans.setdefault(depot_id, [])
        for idx, customer_ids in enumerate(depot_plans):
            candidate = (*customer_ids, customer_id)
            if route_customer_plan_feasible_cached(depot_id, candidate, context):
                old_distance = route_distance_cached(depot_id, tuple(customer_ids), context)
                new_distance = route_distance_cached(depot_id, candidate, context)
                marginal_cost = ((new_distance - old_distance) / 1000.0) * c_km
                key = (marginal_cost, depot_id, 0, idx)
                if best_key is None or key < best_key:
                    best_key = key
                    best_target = (depot_id, idx)
        single = (customer_id,)
        if route_customer_plan_feasible_cached(depot_id, single, context):
            new_route_cost = (route_distance_cached(depot_id, single, context) / 1000.0) * c_km + fixed_cost
            key = (new_route_cost, depot_id, 1, 0)
            if best_key is None or key < best_key:
                best_key = key
                best_target = (depot_id, None)
    if best_target is None:
        depot_id = depot_choices[0] if depot_choices else next(iter(plans))
        plans.setdefault(depot_id, []).append([customer_id])
        return
    depot_id, route_idx = best_target
    if route_idx is None:
        plans.setdefault(depot_id, []).append([customer_id])
    else:
        plans[depot_id][route_idx].append(customer_id)


def route_customer_plan_feasible_cached(depot_id: str, customer_ids: tuple[str, ...], context: OrderDecodeContext) -> bool:
    key = (depot_id, customer_ids)
    cached = context.cache.route_feasible_cache.get(key)
    if cached is not None:
        return cached
    node_lookup = context.node_lookup or {}
    cv_capacity = context.instance.payload_capacity_kg(
        "cv",
        fallback=_price(context.prices, "Q_capacity"),
    )
    feasible = (
        sum(
            float(node_lookup[customer_id].demand)
            for customer_id in customer_ids
        )
        <= cv_capacity + 1e-9
    )
    if feasible:
        route = Route("TMP", "cv", depot_id, [depot_id, *customer_ids, depot_id])
        for row in route_node_schedule(route, context.instance, context.prices):
            if row.t_start > float(node_lookup[row.node_id].due_time) + 1e-9:
                feasible = False
                break
    if len(context.cache.route_feasible_cache) > 100_000:
        context.cache.route_feasible_cache.clear()
    context.cache.route_feasible_cache[key] = feasible
    return feasible


def route_distance_cached(depot_id: str, customer_ids: tuple[str, ...], context: OrderDecodeContext) -> float:
    key = (depot_id, customer_ids)
    cached = context.cache.route_distance_cache.get(key)
    if cached is not None:
        return cached
    sequence = (depot_id, *customer_ids, depot_id)
    index = context.instance.node_index
    distance = sum(float(context.instance.distance_matrix[index[a]][index[b]]) for a, b in zip(sequence, sequence[1:]))
    if len(context.cache.route_distance_cache) > 100_000:
        context.cache.route_distance_cache.clear()
    context.cache.route_distance_cache[key] = distance
    return distance


def all_cv_solution_for_order(ordered: list[str], context: OrderDecodeContext) -> Solution:
    depots = context.depots or []
    plans: dict[str, list[list[str]]] = {depot.node_id: [] for depot in depots}
    for customer_id in ordered:
        append_customer_to_cached_plan(customer_id, plans, context)
    routes: list[Route] = []
    idx = 1
    for depot_id, depot_plans in sorted(plans.items()):
        for customer_ids in depot_plans:
            routes.append(Route(f"CV{idx}", "cv", depot_id, [depot_id, *customer_ids, depot_id]))
            idx += 1
    return normalize_solution(Solution(routes=routes), context)


def normalize_solution(solution: Solution, context: OrderDecodeContext) -> Solution:
    try:
        return normalize_solution_vehicle_trips(solution, context.instance)
    except ValueError:
        return solution


def route_customers(route: Route, instance: Instance) -> list[str]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    return [
        node_id
        for node_id in route.node_sequence
        if node_lookup.get(node_id) is not None and node_lookup[node_id].node_type.lower() == "c"
    ]


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))
