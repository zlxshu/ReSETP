"""G0 accounting boundary for complete-solution ALNS scores.

Search candidates, non-search references, and route-level repair deltas are
separate channels.  Candidate capacity is checked before the legacy scorer is
entered, so the lower ``EvalBudget.record`` guard can never create target+1.
"""

from __future__ import annotations

from typing import Any

from setp_solver.solution import Solution
from setp_solver.search.evaluation import EvaluationContext


class SearchBudgetExhausted(RuntimeError):
    """Raised before a complete candidate scorer would exceed its target."""


def remaining_search_evaluations(context: EvaluationContext) -> int:
    budget = context.budget
    if budget is None:
        return 2**63 - 1
    return max(0, int(budget.target_count) - int(budget.count))


def can_score_search_candidate(context: EvaluationContext) -> bool:
    return remaining_search_evaluations(context) > 0


def score_search_candidate(
    solution: Solution,
    context: EvaluationContext,
    *,
    channel: str,
) -> tuple[Solution, float]:
    """Score exactly one search-selectable complete solution."""

    if not channel.strip():
        raise ValueError("search candidate channel must be non-empty")
    if not can_score_search_candidate(context):
        raise SearchBudgetExhausted(
            f"candidate budget exhausted before channel={channel!r}: "
            f"count={getattr(context.budget, 'count', 0)} "
            f"target={getattr(context.budget, 'target_count', 0)}"
        )
    key = f"candidate_channel:{channel}"
    context.score_counts[key] = int(context.score_counts.get(key, 0)) + 1
    from setp_solver.search.e3_multitrip_runtime import prepare_and_score_candidate

    prepared, objective = prepare_and_score_candidate(solution, context)
    return prepared, float(objective)


def score_reference_solution(
    solution: Solution,
    context: EvaluationContext,
    *,
    phase: str,
) -> tuple[Solution, float]:
    """Recompute a non-search reference and record its phase."""

    _record_reference(context, phase)
    from setp_solver.search.e3_multitrip_runtime import prepare_and_score_reference

    prepared, objective = prepare_and_score_reference(solution, context)
    return prepared, float(objective)


def reference_model_cost(
    solution: Solution,
    context: EvaluationContext,
    *,
    phase: str,
) -> float:
    """Return unpenalized model cost through an explicit reference channel."""

    _record_reference(context, phase)
    from setp_solver.search.e3_multitrip_runtime import prepared_model_cost

    _, value = prepared_model_cost(solution, context)
    return float(value)


def cached_or_reference_model_cost(
    solution: Solution,
    context: EvaluationContext,
    *,
    phase: str,
) -> float:
    """Reuse an existing raw cost, otherwise perform a visible reference."""

    cached: dict[str, Any] = context.score_breakdowns.get(id(solution), {})
    if "raw_cost" in cached:
        context.score_counts["reference_cache_hit"] = int(
            context.score_counts.get("reference_cache_hit", 0)
        ) + 1
        cache_key = f"reference_cache_hit:{phase}"
        context.score_counts[cache_key] = int(context.score_counts.get(cache_key, 0)) + 1
        return float(cached["raw_cost"])
    return reference_model_cost(solution, context, phase=phase)


def _record_reference(context: EvaluationContext, phase: str) -> None:
    if not phase.strip():
        raise ValueError("reference phase must be non-empty")
    context.score_counts["reference"] = int(context.score_counts.get("reference", 0)) + 1
    key = f"reference_phase:{phase}"
    context.score_counts[key] = int(context.score_counts.get(key, 0)) + 1
