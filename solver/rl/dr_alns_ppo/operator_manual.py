from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any

import numpy as np

from setp_solver.check import (
    _charging_index as _check_charging_index,
    _check_battery,
    _check_capacity,
    _check_charging_start_and_power,
    _check_route_flow,
    _check_time_windows,
    _route_nodes_valid as _check_route_nodes_valid,
)
from setp_solver.search.charging import repair_route_charging
from setp_solver.search.evaluation import EvaluationContext, record_repair_delta
from setp_solver.solution import ChargingAction, Route, Solution


_NODE_LOOKUP_CACHE: dict[int, dict[str, Any]] = {}
_CUSTOMER_IDS_CACHE: dict[int, list[str]] = {}
_CUSTOMER_ID_SET_CACHE: dict[int, set[str]] = {}
_DEPOTS_CACHE: dict[int, list[Any]] = {}


@dataclass
class RouletteStats:
    weights: dict[str, float]
    scores: dict[str, float]
    uses: dict[str, int]
    lambda_decay: float = 0.8

    @classmethod
    def create(cls, operator_ids: list[str]) -> "RouletteStats":
        return cls(
            weights={operator_id: 1.0 for operator_id in operator_ids},
            scores={operator_id: 0.0 for operator_id in operator_ids},
            uses={operator_id: 0 for operator_id in operator_ids},
        )

    def record(self, operator_id: str, reward_code: str) -> None:
        if operator_id not in self.weights:
            self.weights[operator_id] = 1.0
            self.scores[operator_id] = 0.0
            self.uses[operator_id] = 0
        reward = {
            "global_best": 6.0,
            "current_improved": 3.0,
            "accepted_worse": 1.0,
        }.get(reward_code, 0.0)
        self.scores[operator_id] += reward
        self.uses[operator_id] += 1

    def update_segment(self) -> None:
        for operator_id, weight in list(self.weights.items()):
            uses = int(self.uses.get(operator_id, 0))
            if uses > 0:
                mean_score = float(self.scores.get(operator_id, 0.0)) / uses
                self.weights[operator_id] = (
                    float(self.lambda_decay) * float(weight)
                    + (1.0 - float(self.lambda_decay)) * mean_score
                )
            self.scores[operator_id] = 0.0
            self.uses[operator_id] = 0


def removal_count(customer_count: int, q_ratio: float) -> int:
    if int(customer_count) <= 0:
        return 0
    q = min(0.40, max(0.10, float(q_ratio)))
    return max(1, int(math.ceil(q * int(customer_count))))


def sa_accept(delta: float, temperature: float, random_value: float) -> bool:
    if float(delta) <= 0.0:
        return True
    if float(temperature) <= 0.0:
        return False
    return float(random_value) < math.exp(-float(delta) / float(temperature))


def relatedness(left: Any, right: Any, same_route: bool, weights: tuple[float, float, float, float]) -> float:
    w1, w2, w3, w4 = weights
    distance = math.hypot(float(left.x) - float(right.x), float(left.y) - float(right.y))
    time_window = abs(float(left.ready_time) - float(right.ready_time)) + abs(float(left.due_time) - float(right.due_time))
    demand = abs(float(left.demand) - float(right.demand))
    route_penalty = 0.0 if same_route else 1.0
    return float(w1) * distance + float(w2) * time_window + float(w3) * demand + float(w4) * route_penalty


def apply_destroy(solution, context, rng, destroy_id: str, q_ratio: float):
    """Return `(partial_solution, removed_customer_ids, trace)` for D1-D5."""

    customers = _served_customer_ids(solution, context.instance)
    q = removal_count(len(customers), q_ratio)
    if q == 0:
        return solution, [], {"destroy_id": destroy_id, "removed_count": 0, "q": 0}

    if destroy_id == "D1":
        removed = _rng_sample(rng, customers, q)
    elif destroy_id == "D2":
        removed = _worst_removal_ids(solution, context, customers, q)
    elif destroy_id == "D3":
        removed = _shaw_removal_ids(solution, context.instance, rng, customers, q)
    elif destroy_id == "D4":
        removed = _route_removal_ids(solution, context.instance, rng)
    elif destroy_id == "D5":
        removed = _segment_removal_ids(solution, context.instance, rng, q)
    else:
        raise ValueError(f"unknown destroy_id: {destroy_id}")

    partial = _solution_without_customers(solution, set(removed), context)
    trace = {
        "destroy_id": destroy_id,
        "q": q,
        "removed_count": len(removed),
        "removed_customer_ids": list(removed),
    }
    return partial, list(removed), trace


def apply_repair(partial_solution, removed_customer_ids, context, repair_id: str):
    """Return `(candidate_solution, trace)` for R1-R3 using incremental scoring."""

    pending = list(dict.fromkeys(str(customer_id) for customer_id in removed_customer_ids))
    routes = list(partial_solution.routes)
    insertion_trace: list[dict[str, Any]] = []

    while pending:
        choices: list[_RepairChoice] = []
        for customer_id in pending:
            options = _insertion_options(routes, customer_id, context)
            if not options:
                continue
            if repair_id == "R1":
                choices.append(_RepairChoice(options[0].score, options[0].score, customer_id, options[0]))
            elif repair_id == "R2":
                regret = _regret_score([option.score for option in options], rank=2)
                choices.append(_RepairChoice(-regret, options[0].score, customer_id, options[0]))
            elif repair_id == "R3":
                regret = _regret_score([option.score for option in options], rank=3)
                choices.append(_RepairChoice(-regret, options[0].score, customer_id, options[0]))
            else:
                raise ValueError(f"unknown repair_id: {repair_id}")
        if not choices:
            raise ValueError(f"repair {repair_id} has no feasible insertion for pending customers: {pending}")
        selected = min(choices, key=lambda item: (item.primary, item.best_score, item.customer_id))
        routes = selected.option.routes
        pending.remove(selected.customer_id)
        insertion_trace.append(
            {
                "customer_id": selected.customer_id,
                "score": selected.best_score,
                "route_index": selected.option.route_index,
                "insert_at": selected.option.insert_at,
                "vehicle_type": selected.option.route.vehicle_type,
            }
        )

    candidate = _solution_from_routes(routes, context)
    if candidate is None:
        raise ValueError(f"repair {repair_id} produced an EV route that cannot be charging-repaired")
    trace = {
        "repair_id": repair_id,
        "inserted_count": len(list(dict.fromkeys(removed_customer_ids))),
        "insertions": insertion_trace,
        "repair_delta_count": int(context.score_counts.get("repair_delta", 0)),
    }
    return candidate, trace


@dataclass(frozen=True)
class _InsertionOption:
    score: float
    routes: list[Route]
    route_index: int
    insert_at: int
    route: Route


@dataclass(frozen=True)
class _RepairChoice:
    primary: float
    best_score: float
    customer_id: str
    option: _InsertionOption


def _rng_index(rng: Any, size: int) -> int:
    if size <= 0:
        raise ValueError("cannot choose from an empty sequence")
    if hasattr(rng, "integers"):
        return int(rng.integers(0, size))
    if hasattr(rng, "randrange"):
        return int(rng.randrange(size))
    return int(np.random.default_rng().integers(0, size))


def _rng_sample(rng: Any, values: list[str], k: int) -> list[str]:
    k = min(int(k), len(values))
    if k <= 0:
        return []
    if hasattr(rng, "choice") and not hasattr(rng, "sample"):
        indices = rng.choice(len(values), size=k, replace=False)
        return [values[int(idx)] for idx in np.atleast_1d(indices)]
    if hasattr(rng, "sample"):
        return list(rng.sample(values, k=k))
    indices = np.random.default_rng().choice(len(values), size=k, replace=False)
    return [values[int(idx)] for idx in np.atleast_1d(indices)]


def _node_lookup(instance: Any) -> dict[str, Any]:
    cache_key = id(instance)
    lookup = _NODE_LOOKUP_CACHE.get(cache_key)
    if lookup is None:
        lookup = {node.node_id: node for node in instance.nodes}
        _NODE_LOOKUP_CACHE[cache_key] = lookup
    return lookup


def _customer_ids(instance: Any) -> list[str]:
    cache_key = id(instance)
    customer_ids = _CUSTOMER_IDS_CACHE.get(cache_key)
    if customer_ids is None:
        customer_ids = [node.node_id for node in instance.nodes if node.node_type.lower() == "c"]
        _CUSTOMER_IDS_CACHE[cache_key] = customer_ids
    return customer_ids


def _customer_id_set(instance: Any) -> set[str]:
    cache_key = id(instance)
    customer_ids = _CUSTOMER_ID_SET_CACHE.get(cache_key)
    if customer_ids is None:
        customer_ids = set(_customer_ids(instance))
        _CUSTOMER_ID_SET_CACHE[cache_key] = customer_ids
    return customer_ids


def _depots(instance: Any) -> list[Any]:
    cache_key = id(instance)
    depots = _DEPOTS_CACHE.get(cache_key)
    if depots is None:
        depots = [node for node in instance.nodes if node.node_type.lower() == "d"]
        _DEPOTS_CACHE[cache_key] = depots
    return depots


def _route_customer_ids(route: Route, instance: Any) -> list[str]:
    customer_ids = _customer_id_set(instance)
    return [node_id for node_id in route.node_sequence if node_id in customer_ids]


def _served_customer_ids(solution: Solution, instance: Any) -> list[str]:
    return [customer_id for route in solution.routes for customer_id in _route_customer_ids(route, instance)]


def _customer_route(solution: Solution, instance: Any, customer_id: str) -> Route | None:
    for route in solution.routes:
        if customer_id in _route_customer_ids(route, instance):
            return route
    return None


def _worst_removal_ids(solution: Solution, context: EvaluationContext, customers: list[str], q: int) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for customer_id in customers:
        saving = _single_customer_removal_saving(solution, context.instance, customer_id, context.prices)
        ranked.append((float(saving), customer_id))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [customer_id for _, customer_id in ranked[:q]]


def _single_customer_removal_saving(solution: Solution, instance: Any, customer_id: str, prices: Any) -> float:
    route = _customer_route(solution, instance, customer_id)
    if route is None:
        return 0.0
    customers = _route_customer_ids(route, instance)
    if customer_id not in customers:
        return 0.0
    current_distance = _route_sequence_distance(route.node_sequence, instance)
    remaining = [item for item in customers if item != customer_id]
    if remaining:
        new_sequence = [route.home_depot_id, *remaining, route.home_depot_id]
        fixed_saving = 0.0
    else:
        new_sequence = []
        fixed_saving = _price(prices, "vehicle_fixed_cost")
    distance_saving = current_distance - _route_sequence_distance(new_sequence, instance)
    return distance_saving + fixed_saving


def _shaw_removal_ids(solution: Solution, instance: Any, rng: Any, customers: list[str], q: int) -> list[str]:
    lookup = _node_lookup(instance)
    seed = customers[_rng_index(rng, len(customers))]
    seed_route = _customer_route(solution, instance, seed)
    ranked = []
    for customer_id in customers:
        if customer_id == seed:
            continue
        route = _customer_route(solution, instance, customer_id)
        score = relatedness(
            lookup[seed],
            lookup[customer_id],
            same_route=seed_route is not None and route is not None and seed_route.vehicle_id == route.vehicle_id,
            weights=(1.0, 0.01, 1.0, 100.0),
        )
        ranked.append((score, customer_id))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [seed, *[customer_id for _, customer_id in ranked[: max(0, q - 1)]]]


def _route_removal_ids(solution: Solution, instance: Any, rng: Any) -> list[str]:
    _ = rng
    routes = [route for route in solution.routes if _route_customer_ids(route, instance)]
    if not routes:
        return []
    ranked = sorted(
        routes,
        key=lambda route: (
            -_route_sequence_distance(route.node_sequence, instance),
            route.vehicle_id,
        ),
    )
    pool = ranked[: max(1, math.ceil(len(ranked) / 2))]
    route = min(
        pool or ranked[:1],
        key=lambda item: (
            len(_route_customer_ids(item, instance)),
            _route_sequence_distance(item.node_sequence, instance),
            item.vehicle_id,
        ),
    )
    return _route_customer_ids(route, instance)


def _segment_removal_ids(solution: Solution, instance: Any, rng: Any, q: int) -> list[str]:
    routes = [route for route in solution.routes if _route_customer_ids(route, instance)]
    if not routes:
        return []
    eligible = [route for route in routes if len(_route_customer_ids(route, instance)) >= q]
    route_pool = eligible or routes
    route = route_pool[_rng_index(rng, len(route_pool))]
    customers = _route_customer_ids(route, instance)
    length = min(q, len(customers))
    max_start = max(0, len(customers) - length)
    start = _rng_index(rng, max_start + 1)
    return customers[start : start + length]


def _solution_without_customers(solution: Solution, removed: set[str], context: EvaluationContext) -> Solution:
    routes: list[Route] = []
    for route in solution.routes:
        customers = [customer_id for customer_id in _route_customer_ids(route, context.instance) if customer_id not in removed]
        if not customers:
            continue
        routes.append(_route_with_customers(route, customers))
    rebuilt = _solution_from_routes(routes, context)
    if rebuilt is None:
        return Solution(routes=routes)
    kept = _served_customer_ids(rebuilt, context.instance)
    cross_site = [
        item
        for item in getattr(solution, "cross_site_services", [])
        if getattr(item, "customer_id", None) in kept
    ]
    return replace(rebuilt, cross_site_services=cross_site)


def _route_with_customers(route: Route, customers: list[str]) -> Route:
    return Route(route.vehicle_id, route.vehicle_type.lower(), route.home_depot_id, [route.home_depot_id, *customers, route.home_depot_id])


def _solution_from_routes(routes: list[Route], context: EvaluationContext) -> Solution | None:
    rebuilt_routes: list[Route] = []
    actions: list[ChargingAction] = []
    used_ids: dict[str, int] = {}
    for idx, route in enumerate(routes):
        customers = _route_customer_ids(route, context.instance)
        if not customers:
            continue
        vehicle_id = _unique_vehicle_id(route.vehicle_id, used_ids, idx)
        clean = Route(vehicle_id, route.vehicle_type.lower(), route.home_depot_id, [route.home_depot_id, *customers, route.home_depot_id])
        if clean.vehicle_type == "ev":
            try:
                repaired, route_actions = repair_route_charging(clean, context.instance, context.carbon_profile, context.prices)
            except ValueError:
                return None
            rebuilt_routes.append(repaired)
            actions.extend(route_actions)
        else:
            rebuilt_routes.append(clean)
    return Solution(routes=rebuilt_routes, charging_actions=actions)


def _unique_vehicle_id(vehicle_id: str, used_ids: dict[str, int], idx: int) -> str:
    if vehicle_id not in used_ids:
        used_ids[vehicle_id] = 1
        return vehicle_id
    used_ids[vehicle_id] += 1
    return f"{vehicle_id}_{idx + 1}_{used_ids[vehicle_id]}"


def _insertion_options(routes: list[Route], customer_id: str, context: EvaluationContext) -> list[_InsertionOption]:
    options: list[_InsertionOption] = []
    for route_idx, route in _ranked_route_candidates(routes, customer_id, context, limit=1):
        customers = _route_customer_ids(route, context.instance)
        for insert_at in _ranked_insert_positions(route, customer_id, context, limit=1):
            candidate_customers = [*customers[:insert_at], customer_id, *customers[insert_at:]]
            candidate_route = _candidate_route(route, candidate_customers, context)
            if candidate_route is None:
                continue
            candidate_routes = list(routes)
            candidate_routes[route_idx] = candidate_route
            score = _repair_delta_score(candidate_route, context, base_route=route)
            options.append(_InsertionOption(score, candidate_routes, route_idx, insert_at, candidate_route))

    depots = _depots(context.instance)
    nearest = _nearest_depot(customer_id, context.instance, depots).node_id
    for vehicle_type in ("cv", "ev"):
        vehicle_id = _next_vehicle_id(routes, vehicle_type.upper())
        base = Route(vehicle_id, vehicle_type, nearest, [nearest, customer_id, nearest])
        candidate_route = _candidate_route(base, [customer_id], context)
        if candidate_route is None:
            continue
        candidate_routes = [*routes, candidate_route]
        score = _repair_delta_score(candidate_route, context, base_route=None)
        options.append(_InsertionOption(score, candidate_routes, len(routes), 0, candidate_route))

    return sorted(options, key=lambda item: (item.score, item.route.vehicle_id, item.insert_at))


def _ranked_route_candidates(routes: list[Route], customer_id: str, context: EvaluationContext, *, limit: int) -> list[tuple[int, Route]]:
    scored: list[tuple[float, int, Route]] = []
    for route_idx, route in enumerate(routes):
        customers = _route_customer_ids(route, context.instance)
        if not customers:
            continue
        proximity = min(float(context.instance.distance(customer_id, node_id)) for node_id in customers)
        scored.append((proximity, route_idx, route))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [(route_idx, route) for _, route_idx, route in scored[: max(1, int(limit))]]


def _ranked_insert_positions(route: Route, customer_id: str, context: EvaluationContext, *, limit: int) -> list[int]:
    customers = _route_customer_ids(route, context.instance)
    clean = [route.home_depot_id, *customers, route.home_depot_id]
    scored: list[tuple[float, int]] = []
    for insert_at in range(len(customers) + 1):
        prev_node = clean[insert_at]
        next_node = clean[insert_at + 1]
        delta = (
            float(context.instance.distance(prev_node, customer_id))
            + float(context.instance.distance(customer_id, next_node))
            - float(context.instance.distance(prev_node, next_node))
        )
        scored.append((delta, insert_at))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [insert_at for _, insert_at in scored[: max(1, int(limit))]]


def _candidate_route(route: Route, customers: list[str], context: EvaluationContext) -> Route | None:
    base = _route_with_customers(route, customers)
    actions: list[ChargingAction] = []
    if base.vehicle_type == "ev":
        try:
            base, actions = repair_route_charging(base, context.instance, context.carbon_profile, context.prices)
        except ValueError:
            return None
    if not _is_route_candidate_feasible(base, actions, context):
        return None
    return base


def _is_route_candidate_feasible(route: Route, actions: list[ChargingAction], context: EvaluationContext) -> bool:
    node_lookup = _node_lookup(context.instance)
    if not _check_route_nodes_valid(route, node_lookup):
        return False
    violations = []
    violations.extend(_check_route_flow(route, node_lookup))
    violations.extend(_check_capacity(route, node_lookup, context.prices))
    violations.extend(_check_time_windows(route, context.instance, node_lookup, actions, context.prices))
    if route.vehicle_type.lower() == "ev":
        charging_by_vehicle_node = _check_charging_index(actions)
        violations.extend(_check_charging_start_and_power(route, context.instance, node_lookup, actions, context.prices))
        violations.extend(_check_battery(route, context.instance, node_lookup, charging_by_vehicle_node, context.prices))
    return not violations


def _repair_delta_score(route: Route, context: EvaluationContext, *, base_route: Route | None) -> float:
    record_repair_delta(context)
    try:
        new_score = _route_sequence_distance(route.node_sequence, context.instance)
        old_score = 0.0 if base_route is None else _route_sequence_distance(base_route.node_sequence, context.instance)
        fixed_cost = 0.0 if base_route is not None else _price(context.prices, "vehicle_fixed_cost")
        return float(new_score - old_score + fixed_cost)
    except Exception:
        return 1_000_000_000.0


def _regret_score(scores: list[float], *, rank: int) -> float:
    best = float(scores[0])
    if len(scores) >= rank:
        return float(scores[rank - 1]) - best
    if len(scores) >= 2:
        return float(scores[1]) - best
    return 0.0


def _nearest_depot(customer_id: str, instance: Any, depots: list[Any] | None = None) -> Any:
    lookup = _node_lookup(instance)
    customer = lookup[customer_id]
    depot_options = depots if depots is not None else _depots(instance)
    return min(depot_options, key=lambda depot: (instance.distance(depot.node_id, customer.node_id), depot.node_id))


def _next_vehicle_id(routes: list[Route], prefix: str) -> str:
    used = {route.vehicle_id for route in routes}
    idx = 1
    while f"{prefix}{idx}" in used:
        idx += 1
    return f"{prefix}{idx}"


def _route_sequence_distance(sequence: list[str], instance: Any) -> float:
    return sum(instance.distance(left, right) for left, right in zip(sequence, sequence[1:]))


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))
