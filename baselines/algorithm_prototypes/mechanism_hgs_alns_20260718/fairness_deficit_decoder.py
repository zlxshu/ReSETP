"""Profit-floor repair born from the depot-participation mechanism.

The decoder is used only when a profit guarantee is active.  It does not add a
generic cost operator.  Instead it:

1. measures each depot's normalized shortfall from its independent profit;
2. ranks cross-depot handovers by whether customer demand/revenue flows toward
   a shortfall depot;
3. checks the real ReSETP route and profit ledgers;
4. first removes the shortfall, then chooses the cheapest repaired solution.

The ordinary ALNS complete-search budget is untouched.  Route rebuilds and
profit-ledger evaluations are reported separately and the decoder accepts only
lexicographic improvements in ``(total shortfall, system cost)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from setp_solver.algorithms.resetp_alns.operators.local_search import (
    _candidate_with_route_customers,
)
from setp_solver.check import (
    PROFIT_FAIRNESS,
    FairnessContext,
    check_solution,
)
from setp_solver.cost import evaluate
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import Solution
from v7_responsibility_solver import (
    ResponsibilityMove,
    _ranked_responsibility_moves,
    annotate_cross_site_services,
)


TOL = 1.0e-9


@dataclass(frozen=True)
class FairnessState:
    """Auditable profit-floor state for one complete solution."""

    solution: Solution
    system_cost: float
    depot_profit: dict[str, float]
    profit_ratio: dict[str, float]
    normalized_shortfall: dict[str, float]
    total_shortfall: float
    minimum_profit_ratio: float
    fairness_satisfied: bool


def evaluate_fairness_state(
    solution: Solution,
    context: EvaluationContext,
    *,
    owners: dict[str, str],
    independent_profit: dict[str, float],
    theta: float,
) -> FairnessState:
    """Recompute cost and depot participation from the frozen model ledgers."""

    annotated = annotate_cross_site_services(solution, owners)
    profits = calculate_depot_profits(
        annotated,
        context.instance,
        context.carbon_profile,
        context.prices,
        customer_home_depot=owners,
        carbon_quota_kg=context.carbon_quota_kg,
    )
    depot_profit = {
        depot_id: float(profits[depot_id].profit)
        for depot_id in sorted(independent_profit)
    }
    ratios = {
        depot_id: (
            depot_profit[depot_id] / float(independent_profit[depot_id])
        )
        for depot_id in sorted(independent_profit)
    }
    shortfall = {
        depot_id: max(0.0, float(theta) - ratio)
        for depot_id, ratio in ratios.items()
    }
    total_shortfall = float(sum(shortfall.values()))
    system_cost = float(
        evaluate(
            annotated,
            context.instance,
            context.carbon_profile,
            context.prices,
            carbon_quota_kg=context.carbon_quota_kg,
        )["total_cost"]
    )
    return FairnessState(
        solution=annotated,
        system_cost=system_cost,
        depot_profit=depot_profit,
        profit_ratio=ratios,
        normalized_shortfall=shortfall,
        total_shortfall=total_shortfall,
        minimum_profit_ratio=min(ratios.values()),
        fairness_satisfied=total_shortfall <= TOL,
    )


def _customer_demand(context: EvaluationContext, customer_id: str) -> float:
    return float(context.instance.nodes[context.instance.node_index[customer_id]].demand)


def _fairness_proxy(
    move: ResponsibilityMove,
    solution: Solution,
    context: EvaluationContext,
    shortfall: dict[str, float],
) -> float:
    """Negative is promising: it pushes demand toward shortfall depots."""

    left_depot = solution.routes[move.left_route_index].home_depot_id
    right_depot = solution.routes[move.right_route_index].home_depot_id
    if move.kind == "handover":
        customer_id = move.moved_customers[0]
        demand = _customer_demand(context, customer_id)
        return demand * (
            float(shortfall.get(left_depot, 0.0))
            - float(shortfall.get(right_depot, 0.0))
        )
    left_customer, right_customer = move.moved_customers
    left_demand = _customer_demand(context, left_customer)
    right_demand = _customer_demand(context, right_customer)
    left_weight = float(shortfall.get(left_depot, 0.0))
    right_weight = float(shortfall.get(right_depot, 0.0))
    return (
        left_weight * (left_demand - right_demand)
        + right_weight * (right_demand - left_demand)
    )


def _relaxed_context(context: EvaluationContext) -> EvaluationContext:
    """Build candidates without rejecting the partial repair too early."""

    return EvaluationContext(
        context.instance,
        context.carbon_profile,
        prices=context.prices,
        carbon_quota_kg=context.carbon_quota_kg,
        carbon_weight=context.carbon_weight,
        budget=EvalBudget(limit=0, target=0),
        fairness_enabled=False,
        independent_profit=None,
        fairness_theta=None,
        customer_home_depot=context.customer_home_depot,
        allow_cross_depot=True,
        repair_delta_mode=context.repair_delta_mode,
    )


def profit_floor_repair_decode(
    solution: Solution,
    context: EvaluationContext,
    *,
    owners: dict[str, str],
    independent_profit: dict[str, float],
    theta: float,
    max_rounds: int = 3,
    max_profit_ledger_evaluations_per_round: int = 256,
    top_insertions: int = 3,
) -> tuple[FairnessState, dict[str, Any]]:
    """Repair a binding profit floor with deficit-directed depot handovers."""

    if not independent_profit:
        raise ValueError("independent_profit must be non-empty")
    if any(float(value) <= 0.0 for value in independent_profit.values()):
        raise ValueError("all independent profits must be strictly positive")
    if not 0.0 < float(theta) <= 1.0 + TOL:
        raise ValueError("theta must lie in (0, 1]")

    current = evaluate_fairness_state(
        solution,
        context,
        owners=owners,
        independent_profit=independent_profit,
        theta=theta,
    )
    initial = current
    relaxed = _relaxed_context(context)
    activity: dict[str, Any] = {
        "theta": float(theta),
        "initial_total_shortfall": float(initial.total_shortfall),
        "initial_minimum_profit_ratio": float(
            initial.minimum_profit_ratio
        ),
        "initial_system_cost": float(initial.system_cost),
        "proxy_moves_considered": 0,
        "route_rebuild_checks": 0,
        "profit_ledger_evaluations": 0,
        "complete_route_search_evaluations": 0,
        "accepted_moves": [],
        "exact_decoder_updates": 0,
    }
    if current.fairness_satisfied:
        fairness_context = FairnessContext(
            depot_profit=dict(current.depot_profit),
            independent_profit=dict(independent_profit),
            theta=float(theta),
        )
        violations = check_solution(
            current.solution,
            context.instance,
            context.prices,
            fairness_context=fairness_context,
            fairness_enabled=True,
        )
        fairness_violations = [
            violation
            for violation in violations
            if violation.type == PROFIT_FAIRNESS
        ]
        activity["stop_reason"] = "profit_floor_already_satisfied"
        activity["final_total_shortfall"] = 0.0
        activity["final_minimum_profit_ratio"] = float(
            current.minimum_profit_ratio
        )
        activity["final_system_cost"] = float(current.system_cost)
        activity["fairness_satisfied"] = not fairness_violations
        activity["fairness_violation_count"] = len(
            fairness_violations
        )
        activity["independent_final_replays"] = 1
        activity["cost_premium_percent"] = 0.0
        return current, activity

    for round_index in range(max(0, int(max_rounds))):
        moves = _ranked_responsibility_moves(
            current.solution,
            relaxed,
            owners,
            top_insertions=top_insertions,
        )
        moves.sort(
            key=lambda move: (
                _fairness_proxy(
                    move,
                    current.solution,
                    context,
                    current.normalized_shortfall,
                ),
                move.proxy_delta,
                move.kind,
                move.left_route_index,
                move.right_route_index,
                move.moved_customers,
            )
        )
        activity["proxy_moves_considered"] += len(moves)
        if not moves:
            activity["stop_reason"] = "no_cross_depot_repair_move"
            break
        selected: tuple[FairnessState, ResponsibilityMove] | None = None
        limit = max(0, int(max_profit_ledger_evaluations_per_round))
        for move in moves[:limit]:
            candidate = _candidate_with_route_customers(
                current.solution,
                relaxed,
                {
                    move.left_route_index: list(move.left_customers),
                    move.right_route_index: list(move.right_customers),
                },
            )
            activity["route_rebuild_checks"] += 1
            if candidate is None:
                continue
            candidate_state = evaluate_fairness_state(
                candidate,
                context,
                owners=owners,
                independent_profit=independent_profit,
                theta=theta,
            )
            activity["profit_ledger_evaluations"] += 1
            if (
                candidate_state.total_shortfall,
                candidate_state.system_cost,
            ) >= (
                current.total_shortfall - TOL,
                current.system_cost - TOL,
            ):
                continue
            if selected is None or (
                candidate_state.total_shortfall,
                candidate_state.system_cost,
            ) < (
                selected[0].total_shortfall,
                selected[0].system_cost,
            ):
                selected = (candidate_state, move)
        if selected is None:
            activity["stop_reason"] = "no_shortfall_reducing_candidate"
            break
        next_state, move = selected
        activity["accepted_moves"].append(
            {
                "round": round_index + 1,
                "kind": move.kind,
                "route_indices": [
                    move.left_route_index,
                    move.right_route_index,
                ],
                "moved_customers": list(move.moved_customers),
                "shortfall_before": float(current.total_shortfall),
                "shortfall_after": float(next_state.total_shortfall),
                "minimum_ratio_before": float(
                    current.minimum_profit_ratio
                ),
                "minimum_ratio_after": float(
                    next_state.minimum_profit_ratio
                ),
                "system_cost_delta": float(
                    next_state.system_cost - current.system_cost
                ),
            }
        )
        activity["exact_decoder_updates"] += 1
        current = next_state
        if current.fairness_satisfied:
            activity["stop_reason"] = "profit_floor_repaired"
            break
    else:
        activity["stop_reason"] = "round_limit_reached"

    fairness_context = FairnessContext(
        depot_profit=dict(current.depot_profit),
        independent_profit=dict(independent_profit),
        theta=float(theta),
    )
    violations = check_solution(
        current.solution,
        context.instance,
        context.prices,
        fairness_context=fairness_context,
        fairness_enabled=True,
    )
    fairness_violations = [
        violation
        for violation in violations
        if violation.type == PROFIT_FAIRNESS
    ]
    activity["final_total_shortfall"] = float(current.total_shortfall)
    activity["final_minimum_profit_ratio"] = float(
        current.minimum_profit_ratio
    )
    activity["final_system_cost"] = float(current.system_cost)
    activity["fairness_satisfied"] = bool(
        current.fairness_satisfied and not fairness_violations
    )
    activity["fairness_violation_count"] = len(fairness_violations)
    activity["independent_final_replays"] = 1
    activity["cost_premium_percent"] = (
        100.0 * (current.system_cost / initial.system_cost - 1.0)
        if initial.system_cost > 0.0
        else 0.0
    )
    return current, activity
