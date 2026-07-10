"""Private strong-bridge helpers for independent ReSETP ALNS.

Copied from search.candidates for algorithm package isolation.
Baselines continue to use search.candidates; this copy is for ReSETP ALNS only.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import math
import random
from typing import Any

from setp_solver.check import check_solution
from setp_solver.instance_loader import Instance
from setp_solver.solution import ChargingAction, Route, Solution
from setp_solver.search.evaluation import EvaluationContext

from setp_solver.algorithms.resetp_alns.operators.feasible_repair import repair_removed_customers


@dataclass(frozen=True)
class _OperatorOutcome:
    solution: Solution
    produced: bool
    feasible: bool
    changed: bool
    violation_count: int = 0
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _ThinPolicy:
    require_charging_signal: bool = False
    max_cv: int = 10**9
    max_ev: int = 10**9

def _apply_strong_alns_destroy_repair(
    solution: Solution,
    context: EvaluationContext,
    rng: random.Random,
    destroy_operator: str,
    repair_operator: str,
) -> _OperatorOutcome:
    removed = _strong_destroy_customer_ids(solution, context, rng, destroy_operator)
    if not removed:
        return _OperatorOutcome(solution, produced=False, feasible=False, changed=False, detail="destroy_selected_no_customers", metadata={"removed_count": 0})
    partial_routes = _routes_without_customers(solution.routes, set(removed), context.instance)
    mode = {"greedy_insert_repair": "greedy", "regret2_insert_repair": "regret2", "regret3_insert_repair": "regret3"}[repair_operator]
    policy = _bridge_policy_for_context(context)
    repaired = repair_removed_customers(Solution(routes=partial_routes, charging_actions=_actions_for_routes(solution, partial_routes)), list(removed), context, policy, mode=mode)
    if repaired is None:
        return _OperatorOutcome(solution, produced=True, feasible=False, changed=False, detail="strong_repair_failed", metadata={"removed_count": len(removed)})
    violations = check_solution(repaired, context.instance, context.prices)
    changed = solution_signature_hash(repaired) != solution_signature_hash(solution)
    return _OperatorOutcome(
        repaired if not violations else solution,
        produced=True,
        feasible=not violations,
        changed=changed and not violations,
        violation_count=len(violations),
        metadata={"removed_count": len(removed)},
    )

def _bridge_policy_for_context(context: EvaluationContext) -> _ThinPolicy:
    return _ThinPolicy(
        require_charging_signal=False,
        max_cv=_bridge_instance_limit(context.instance, "num_cv"),
        max_ev=_bridge_instance_limit(context.instance, "num_ev"),
    )

def _bridge_instance_limit(instance: Instance, attr: str) -> int:
    value = getattr(instance, attr, None)
    if value is None:
        return 10**9
    return int(float(value))

def _strong_destroy_customer_ids(
    solution: Solution,
    context: EvaluationContext,
    rng: random.Random,
    destroy_operator: str,
) -> list[str]:
    customers = [customer_id for _, customer_id in _customer_positions(solution, context.instance)]
    if not customers:
        return []
    remove_count = _fractional_remove_count(len(customers), rng)
    if destroy_operator == "random_customer_removal":
        return rng.sample(customers, k=min(remove_count, len(customers)))
    if destroy_operator == "worst_customer_removal":
        ranked = sorted(
            ((_customer_distance_contribution(solution, context.instance, customer_id), customer_id) for customer_id in customers),
            reverse=True,
        )
        return [customer_id for _, customer_id in ranked[:remove_count]]
    if destroy_operator == "shaw_related_removal":
        seed_customer = rng.choice(customers)
        related = sorted(
            ((_path_relatedness(solution, context.instance, seed_customer, customer_id), customer_id) for customer_id in customers if customer_id != seed_customer),
            key=lambda item: (item[0], item[1]),
        )
        return [seed_customer, *[customer_id for _, customer_id in related[: max(0, remove_count - 1)]]]
    if destroy_operator == "whole_route_removal":
        routes = [route for route in solution.routes if _route_customers(route, context.instance)]
        if not routes:
            return []
        route = max(routes, key=lambda item: _route_sequence_distance(item.node_sequence, context.instance))
        return _route_customers(route, context.instance)
    if destroy_operator == "route_segment_removal":
        routes = [route for route in solution.routes if _route_customers(route, context.instance)]
        if not routes:
            return []
        route = rng.choice(routes)
        route_customers = _route_customers(route, context.instance)
        start = rng.randrange(len(route_customers))
        return route_customers[start : start + min(remove_count, len(route_customers) - start)]
    raise ValueError(f"unknown strong ALNS destroy operator {destroy_operator}")

def _fractional_remove_count(customer_count: int, rng: random.Random) -> int:
    low = min(customer_count, max(2, math.ceil(0.10 * customer_count)))
    high = min(customer_count, max(low, math.ceil(0.40 * customer_count)))
    high = min(high, 12)
    low = min(low, high)
    return rng.randint(low, high)

def _path_relatedness(solution: Solution, instance: Instance, seed_customer: str, customer_id: str) -> float:
    node_lookup = {node.node_id: node for node in instance.nodes}
    seed = node_lookup[seed_customer]
    customer = node_lookup[customer_id]
    route_of = {
        node_id: route_idx
        for route_idx, route in enumerate(solution.routes)
        for node_id in _route_customers(route, instance)
    }
    return (
        float(instance.distance(seed_customer, customer_id))
        + abs(float(seed.ready_time) - float(customer.ready_time)) * 0.1
        + abs(float(seed.due_time) - float(customer.due_time)) * 0.05
        + abs(float(seed.demand) - float(customer.demand)) * 10.0
        + (0.0 if route_of.get(seed_customer) == route_of.get(customer_id) else 10_000.0)
    )

def _actions_for_routes(solution: Solution, routes: list[Route]) -> list[ChargingAction]:
    vehicle_ids = {route.vehicle_id for route in routes}
    route_nodes = {node_id for route in routes for node_id in route.node_sequence}
    return [action for action in solution.charging_actions if action.vehicle_id in vehicle_ids and action.station_id in route_nodes]

def _routes_without_customers(routes: list[Route], customer_ids: set[str], instance: Instance) -> list[Route]:
    kept: list[Route] = []
    for route in routes:
        customers = [customer_id for customer_id in _route_customers(route, instance) if customer_id not in customer_ids]
        if customers:
            kept.append(_route_with_customers(route, customers))
    return kept

def _route_sequence_distance(sequence: list[str], instance: Instance) -> float:
    index = instance.node_index
    return sum(float(instance.distance_matrix[index[a]][index[b]]) for a, b in zip(sequence, sequence[1:]))

def _customer_distance_contribution(solution: Solution, instance: Instance, customer_id: str) -> float:
    for route in solution.routes:
        seq = list(route.node_sequence)
        for idx, node_id in enumerate(seq[1:-1], start=1):
            if node_id != customer_id:
                continue
            return instance.distance(seq[idx - 1], node_id) + instance.distance(node_id, seq[idx + 1]) - instance.distance(seq[idx - 1], seq[idx + 1])
    return 0.0

def solution_signature(solution: Solution) -> dict[str, Any]:
    # v2026-06-12: W1c anti-collapse signatures must be deterministic and
    # JSON-native so the same-route/same-charge check cannot fail before gating.
    return {
        "routes": sorted(
            (
                route.vehicle_type.lower(),
                route.home_depot_id,
                tuple(route.node_sequence),
            )
            for route in solution.routes
        ),
        "charging_actions": sorted(
            (
                action.vehicle_id,
                action.station_id,
                round(float(action.charge_start_second), 6),
                round(float(action.energy_kwh), 9),
                round(float(action.occupancy_minutes), 9),
            )
            for action in solution.charging_actions
        ),
    }

def solution_signature_hash(solution: Solution) -> str:
    payload = json.dumps(solution_signature(solution), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def _route_customers(route: Route, instance: Instance) -> list[str]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    return [node_id for node_id in route.node_sequence if node_lookup.get(node_id) and node_lookup[node_id].node_type.lower() == "c"]

def _route_with_customers(route: Route, customers: list[str]) -> Route:
    return replace(route, node_sequence=[route.home_depot_id, *customers, route.home_depot_id])

def _customer_positions(solution: Solution, instance: Instance) -> list[tuple[int, str]]:
    return [
        (idx, customer_id)
        for idx, route in enumerate(solution.routes)
        for customer_id in _route_customers(route, instance)
    ]
