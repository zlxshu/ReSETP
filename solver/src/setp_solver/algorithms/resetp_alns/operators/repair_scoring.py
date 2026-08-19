"""Route-local cost delta retained by frozen charging repair."""

from __future__ import annotations

from typing import Any

from setp_solver.cost import evaluate
from setp_solver.search.evaluation import EvaluationContext, _prices_with_carbon_weight
from setp_solver.solution import ChargingAction, Route, Solution


def route_model_cost_delta(
    route: Route,
    actions: list[ChargingAction] | list[Any],
    context: EvaluationContext,
    *,
    base_route: Route | None = None,
    base_actions: list[ChargingAction] | list[Any] | None = None,
) -> float:
    new_score = route_model_cost(route, actions, context)
    old_score = (
        0.0
        if base_route is None
        else route_model_cost(base_route, base_actions or [], context)
    )
    return float(new_score - old_score)


def route_model_cost(
    route: Route,
    actions: list[ChargingAction] | list[Any],
    context: EvaluationContext,
) -> float:
    route_actions = [
        action
        for action in actions
        if getattr(action, "vehicle_id", route.vehicle_id) == route.vehicle_id
    ]
    prices = _prices_with_carbon_weight(
        context.prices,
        context.carbon_weight,
    )
    return float(
        evaluate(
            Solution(routes=[route], charging_actions=list(route_actions)),
            context.instance,
            context.carbon_profile,
            prices,
            carbon_quota_kg=0.0,
        )["total_cost"]
    )
