"""Shared search evaluation shell over cost.py and check.py.

v2026-06-11: Implements the algorithm-facing objective required by
paper_main.tex lines 541-545: every candidate is scored by the same cost
evaluator and hard-constraint checker. Use ``penalized_obj`` inside all search
operators; feasible solutions keep exactly the model objective.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from ..check import FairnessContext, check_solution
from ..cost import evaluate
from ..instance_loader import Instance
from ..prices import DEFAULT_PRICES, PriceParameters
from ..profit import calculate_depot_profits, depot_profit_values
from ..solution import Solution


# v2026-06-11: much larger than any expected GBP route bill in generated tests.
BIG_M = 1_000_000_000.0


@dataclass
class EvalBudget:
    limit: int
    count: int = 0
    target: int | None = None

    def record(self) -> None:
        self.count += 1
        if self.count > self.limit:
            raise RuntimeError(f"EvalBudget exhausted: {self.count} > {self.limit}")

    @property
    def target_count(self) -> int:
        return self.limit if self.target is None else int(self.target)

    @property
    def reached_target(self) -> bool:
        return self.count >= self.target_count


@dataclass
class EvaluationContext:
    instance: Instance
    carbon_profile: list[dict[str, Any]]
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES
    carbon_quota_kg: float = 0.0
    carbon_weight: float = 1.0
    budget: EvalBudget | None = None
    # v2026-06-12: V2 profit fairness is opt-in; defaults preserve the frozen
    # no-fairness search semantics used by prior E5/T0/T1 gates.
    fairness_enabled: bool = False
    independent_profit: dict[str, float] | None = None
    fairness_theta: float | None = None
    customer_home_depot: dict[str, str] | None = None
    repair_delta_mode: str = "fast"
    score_counts: dict[str, int] = field(default_factory=dict)
    score_breakdowns: dict[int, dict[str, Any]] = field(default_factory=dict)


def score_candidate(solution: Solution, context: EvaluationContext, *, label: str = "candidate") -> float:
    """Score one complete candidate solution submitted to search selection."""

    if label != "candidate":
        raise ValueError("score_candidate only accounts complete candidate evaluations; use record_repair_delta for repair-internal scoring")
    context.score_counts["candidate"] = int(context.score_counts.get("candidate", 0)) + 1
    return penalized_obj(solution, context)


def score_reference(solution: Solution, context: EvaluationContext) -> float:
    """Score a reference solution without consuming the search eval budget."""

    return _penalized_obj(solution, context, record_budget=False)


def record_repair_delta(context: EvaluationContext, *, count: int = 1) -> None:
    """Record repair-internal delta scoring that is not a full eval."""

    context.score_counts["repair_delta"] = int(context.score_counts.get("repair_delta", 0)) + int(count)


def penalized_obj(solution: Solution, context: EvaluationContext) -> float:
    """Return model cost plus ``BIG_M`` per hard violation."""

    return _penalized_obj(solution, context, record_budget=True)


def _penalized_obj(solution: Solution, context: EvaluationContext, *, record_budget: bool) -> float:
    if record_budget and context.budget is not None:
        context.budget.record()
    prices = _prices_with_carbon_weight(context.prices, context.carbon_weight)
    cost = evaluate(
        solution,
        context.instance,
        context.carbon_profile,
        prices,
        carbon_quota_kg=context.carbon_quota_kg,
    )["total_cost"]
    fairness_context = fairness_context_for_solution(solution, context, prices=prices)
    violations = check_solution(
        solution,
        context.instance,
        prices,
        fairness_context=fairness_context,
        fairness_enabled=context.fairness_enabled,
    )
    penalty = BIG_M * len(violations)
    objective = float(cost) + penalty
    context.score_breakdowns[id(solution)] = {
        "raw_cost": float(cost),
        "objective": float(objective),
        "penalty": float(penalty),
        "violation_count": int(len(violations)),
        "feasible": len(violations) == 0,
    }
    return objective


def model_cost(solution: Solution, context: EvaluationContext) -> float:
    """Return the unpenalized cost under the current search context."""

    prices = _prices_with_carbon_weight(context.prices, context.carbon_weight)
    return float(
        evaluate(
            solution,
            context.instance,
            context.carbon_profile,
            prices,
            carbon_quota_kg=context.carbon_quota_kg,
        )["total_cost"]
    )


def fairness_context_for_solution(
    solution: Solution,
    context: EvaluationContext,
    *,
    prices: PriceParameters | dict[str, float] | Any | None = None,
) -> FairnessContext | None:
    """Build the optional checker context from a candidate solution."""

    if not context.fairness_enabled:
        return None
    if context.independent_profit is None:
        return None
    effective_prices = prices if prices is not None else _prices_with_carbon_weight(context.prices, context.carbon_weight)
    theta = (
        float(context.fairness_theta)
        if context.fairness_theta is not None
        else float(getattr(effective_prices, "fairness_theta", 1.0) if not isinstance(effective_prices, dict) else effective_prices.get("fairness_theta", 1.0))
    )
    breakdowns = calculate_depot_profits(
        solution,
        context.instance,
        context.carbon_profile,
        effective_prices,
        customer_home_depot=context.customer_home_depot,
        carbon_quota_kg=context.carbon_quota_kg,
    )
    return FairnessContext(
        depot_profit=depot_profit_values(breakdowns),
        independent_profit=dict(context.independent_profit),
        theta=theta,
    )


def _prices_with_carbon_weight(prices: PriceParameters | dict[str, float] | Any, weight: float) -> PriceParameters | dict[str, float] | Any:
    if abs(float(weight) - 1.0) <= 1e-12:
        return prices
    if isinstance(prices, PriceParameters):
        return replace(prices, carbon_price=prices.carbon_price * float(weight))
    if isinstance(prices, dict):
        out = dict(prices)
        out["carbon_price"] = float(out["carbon_price"]) * float(weight)
        return out
    return replace(prices, carbon_price=float(getattr(prices, "carbon_price")) * float(weight))
