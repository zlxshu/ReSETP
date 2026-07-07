"""Diagnostic fleet/charging co-repair helpers for ALNS structural probes."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math

from ..check import check_solution
from ..cost import evaluate
from ..solution import Route, Solution
from .charging import repair_route_charging
from .evaluation import EvaluationContext, model_cost
from .fleet import normalize_solution_vehicle_trips


@dataclass(frozen=True)
class FleetChargeOutcome:
    solution: Solution | None
    attempts: int
    feasible: int
    accepted: bool
    best_improved: bool
    source_route_type: str
    target_route_type: str
    fuel_delta: float
    electric_delta: float
    carbon_delta: float
    fixed_delta: float
    route_index: int
    trace_rows: list[dict[str, object]]


def propose_fleet_charge_corepair(
    solution: Solution,
    context: EvaluationContext,
    *,
    max_attempts: int = 16,
) -> FleetChargeOutcome:
    current_cost = _feasible_model_cost(solution, context)
    current_metrics = evaluate(solution, context.instance, context.carbon_profile, context.prices) if math.isfinite(current_cost) else {}
    best_candidate: Solution | None = None
    best_cost = current_cost
    best_index = -1
    best_source = ""
    best_target = ""
    attempts = 0
    feasible = 0
    trace_rows: list[dict[str, object]] = []
    for idx, route in enumerate(solution.routes):
        if attempts >= max_attempts:
            break
        attempts += 1
        candidate = flip_route_type_candidate(solution, idx, context)
        candidate_cost = math.inf
        metrics: dict[str, float] = {}
        if candidate is not None:
            violations = check_solution(candidate, context.instance, context.prices)
            if not violations:
                feasible += 1
                candidate_cost = _feasible_model_cost(candidate, context)
                metrics = evaluate(candidate, context.instance, context.carbon_profile, context.prices)
        improved = candidate is not None and candidate_cost < best_cost - 1e-9
        target_type = "ev" if route.vehicle_type.lower() == "cv" else "cv"
        trace_rows.append(
            {
                "route_index": idx,
                "source_route_type": route.vehicle_type.lower(),
                "target_route_type": target_type,
                "feasible": candidate is not None and math.isfinite(candidate_cost),
                "candidate_cost": candidate_cost if math.isfinite(candidate_cost) else "UNKNOWN",
                "fuel_delta": _metric_delta(metrics, current_metrics, "cost_fuel"),
                "electric_delta": _metric_delta(metrics, current_metrics, "cost_elec"),
                "carbon_delta": _metric_delta(metrics, current_metrics, "cost_carbon"),
                "fixed_delta": _metric_delta(metrics, current_metrics, "cost_fix"),
            }
        )
        if improved and candidate is not None:
            best_candidate = candidate
            best_cost = candidate_cost
            best_index = idx
            best_source = route.vehicle_type.lower()
            best_target = target_type
    if best_candidate is None:
        return FleetChargeOutcome(None, attempts, feasible, False, False, "", "", 0.0, 0.0, 0.0, 0.0, -1, trace_rows)
    best_metrics = evaluate(best_candidate, context.instance, context.carbon_profile, context.prices)
    return FleetChargeOutcome(
        best_candidate,
        attempts,
        feasible,
        True,
        best_cost < current_cost - 1e-9,
        best_source,
        best_target,
        _metric_delta(best_metrics, current_metrics, "cost_fuel"),
        _metric_delta(best_metrics, current_metrics, "cost_elec"),
        _metric_delta(best_metrics, current_metrics, "cost_carbon"),
        _metric_delta(best_metrics, current_metrics, "cost_fix"),
        best_index,
        trace_rows,
    )


def flip_route_type_candidate(solution: Solution, idx: int, context: EvaluationContext) -> Solution | None:
    if idx < 0 or idx >= len(solution.routes):
        return None
    routes = list(solution.routes)
    route = routes[idx]
    source_type = route.vehicle_type.lower()
    target_type = "ev" if source_type == "cv" else "cv"
    new_route = Route(
        vehicle_id=f"{target_type.upper()}COREPAIR_{idx + 1}",
        vehicle_type=target_type,
        home_depot_id=route.home_depot_id,
        node_sequence=list(route.node_sequence),
    )
    actions = [action for action in solution.charging_actions if action.vehicle_id != route.vehicle_id]
    if target_type == "ev":
        try:
            new_route, route_actions = repair_route_charging(new_route, context.instance, context.carbon_profile, context.prices)
        except ValueError:
            return None
        actions.extend(route_actions)
    routes[idx] = new_route
    candidate = Solution(routes=routes, charging_actions=actions, cross_site_services=solution.cross_site_services)
    try:
        candidate = normalize_solution_vehicle_trips(candidate, context.instance)
    except ValueError:
        pass
    if check_solution(candidate, context.instance, context.prices):
        return None
    return candidate


def _feasible_model_cost(solution: Solution, context: EvaluationContext) -> float:
    if check_solution(solution, context.instance, context.prices):
        return math.inf
    return float(model_cost(solution, context))


def _metric_delta(candidate: dict[str, float], source: dict[str, float], key: str) -> float:
    if key not in candidate or key not in source:
        return 0.0
    return float(candidate[key]) - float(source[key])
