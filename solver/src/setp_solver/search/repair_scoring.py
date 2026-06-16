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

from ..cost import evaluate
from ..solution import ChargingAction, Route, Solution
from .evaluation import BIG_M, EvaluationContext, _prices_with_carbon_weight


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

    prices = _prices_with_carbon_weight(context.prices, context.carbon_weight)
    route_actions = [action for action in actions if getattr(action, "vehicle_id", route.vehicle_id) == route.vehicle_id]
    return float(
        evaluate(
            Solution(routes=[route], charging_actions=list(route_actions)),
            context.instance,
            context.carbon_profile,
            prices,
            carbon_quota_kg=0.0,
        )["total_cost"]
    )


def _route_distance_delta(route: Route, context: EvaluationContext, *, base_route: Route | None = None) -> float:
    def distance(item: Route) -> float:
        return sum(float(context.instance.distance(a, b)) for a, b in zip(item.node_sequence, item.node_sequence[1:]))

    return distance(route) - (0.0 if base_route is None else distance(base_route))
