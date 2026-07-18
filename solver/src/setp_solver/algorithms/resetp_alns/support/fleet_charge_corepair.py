"""Diagnostic fleet/charging co-repair helpers for ALNS structural probes."""

from __future__ import annotations

from dataclasses import dataclass
import math

from setp_solver.check import check_solution
from setp_solver.solution import Route, Solution
from setp_solver.algorithms.resetp_alns.support.charging import repair_route_charging
from setp_solver.search.evaluation import EvaluationContext
from setp_solver.algorithms.resetp_alns.runtime.budgeted_scoring import (
    SearchBudgetExhausted,
    score_search_candidate,
)
from setp_solver.algorithms.resetp_alns.support.fleet import normalize_solution_vehicle_trips


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
    objective: float | None
    evaluations_used: int


def propose_fleet_charge_corepair(
    solution: Solution,
    context: EvaluationContext,
    *,
    max_attempts: int = 16,
    current_objective: float,
) -> FleetChargeOutcome:
    current_cost = float(current_objective)
    current_metrics: dict[str, float] = {}
    best_candidate: Solution | None = None
    best_cost = current_cost
    best_index = -1
    best_source = ""
    best_target = ""
    attempts = 0
    feasible = 0
    trace_rows: list[dict[str, object]] = []
    evaluations_before = int(context.budget.count) if context.budget is not None else int(
        context.score_counts.get("candidate", 0)
    )
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
                try:
                    candidate, candidate_cost = score_search_candidate(
                        candidate,
                        context,
                        channel="fleet_charge_corepair",
                    )
                except SearchBudgetExhausted:
                    break
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
        used = _evaluations_used(context, evaluations_before)
        return FleetChargeOutcome(
            None, attempts, feasible, False, False, "", "", 0.0, 0.0, 0.0, 0.0,
            -1, trace_rows, None, used
        )
    best_metrics: dict[str, float] = {}
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
        best_cost,
        _evaluations_used(context, evaluations_before),
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


def _evaluations_used(context: EvaluationContext, before: int) -> int:
    after = int(context.budget.count) if context.budget is not None else int(
        context.score_counts.get("candidate", 0)
    )
    return max(0, after - before)


def _metric_delta(candidate: dict[str, float], source: dict[str, float], key: str) -> float:
    if key not in candidate or key not in source:
        return 0.0
    return float(candidate[key]) - float(source[key])
