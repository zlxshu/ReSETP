"""Route-local repair scoring helpers.

Repair operators score incomplete, intermediate solutions while customers are
still being reinserted. Full-solution check penalties would therefore punish
missing customers that are expected to be restored later. These helpers keep
the score local to the affected route while using the same model cost evaluator
as complete candidates.
"""

from __future__ import annotations

import os
from typing import Any

from setp_solver.cost import evaluate
from setp_solver.solution import ChargingAction, Route, Solution
from setp_solver.search.evaluation import BIG_M, EvaluationContext, _prices_with_carbon_weight
from setp_solver.algorithms.resetp_alns.support.timing import timed_section


def route_model_cost_delta(
    route: Route,
    actions: list[ChargingAction] | list[Any],
    context: EvaluationContext,
    *,
    base_route: Route | None = None,
    base_actions: list[ChargingAction] | list[Any] | None = None,
) -> float:
    """Return marginal model cost for replacing ``base_route`` with ``route``."""

    if os.environ.get("SETP_ALNS_CRUSH_TRUE_REPAIR", "1").lower() in {"0", "false", "no"}:
        return _route_distance_delta(route, context, base_route=base_route)
    try:
        new_score = route_model_cost(route, actions, context)
        old_score = 0.0 if base_route is None else route_model_cost(base_route, base_actions or [], context)
        return float(new_score - old_score)
    except Exception:
        return BIG_M


def route_model_cost(route: Route, actions: list[ChargingAction] | list[Any], context: EvaluationContext) -> float:
    """Evaluate one route with quota-neutral carbon cost.

    ``carbon_quota_kg`` is forced to zero because quotas are whole-solution
    constants. Including the global quota in a one-route delta would create a
    spurious fixed offset unrelated to the insertion decision.
    """

    route_actions = [action for action in actions if getattr(action, "vehicle_id", route.vehicle_id) == route.vehicle_id]
    cache_key = _route_cost_cache_key(route, route_actions)
    cache = _route_cost_cache(context)
    if cache is not None and cache_key in cache:
        return float(cache[cache_key])
    prices = _prices_with_carbon_weight(context.prices, context.carbon_weight)
    with timed_section(context, "route_model_cost"):
        cost = float(
            evaluate(
                Solution(routes=[route], charging_actions=list(route_actions)),
                context.instance,
                context.carbon_profile,
                prices,
                carbon_quota_kg=0.0,
            )["total_cost"]
        )
    if cache is not None:
        if len(cache) > 50_000:
            cache.clear()
        cache[cache_key] = cost
    return cost


def _route_cost_cache(context: EvaluationContext) -> dict[Any, float] | None:
    if os.environ.get("SETP_ALNS_CRUSH_ROUTE_COST_CACHE", "0").lower() in {"0", "false", "no"}:
        return None
    cache = getattr(context, "_route_model_cost_cache", None)
    if cache is None:
        cache = {}
        setattr(context, "_route_model_cost_cache", cache)
    return cache


def _route_cost_cache_key(route: Route, actions: list[ChargingAction] | list[Any]) -> tuple[Any, ...]:
    action_key = tuple(
        sorted(
            (
                str(getattr(action, "vehicle_id", "")),
                str(getattr(action, "station_id", "")),
                round(float(getattr(action, "energy_kwh", 0.0)), 9),
                round(float(getattr(action, "occupancy_minutes", 0.0)), 9),
                round(float(getattr(action, "charge_start_second", 0.0)), 9),
            )
            for action in actions
        )
    )
    return (
        str(route.vehicle_id),
        route.vehicle_type.lower(),
        str(route.home_depot_id),
        tuple(str(node_id) for node_id in route.node_sequence),
        action_key,
    )


def _route_distance_delta(route: Route, context: EvaluationContext, *, base_route: Route | None = None) -> float:
    def distance(item: Route) -> float:
        return sum(float(context.instance.distance(a, b)) for a, b in zip(item.node_sequence, item.node_sequence[1:]))

    return distance(route) - (0.0 if base_route is None else distance(base_route))
