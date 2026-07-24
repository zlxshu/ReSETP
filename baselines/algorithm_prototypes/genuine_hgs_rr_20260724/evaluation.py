"""Single-entry complete evaluation for fair A/B/A+B budget accounting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from setp_solver.china81_completion import exact_china81_score
from setp_solver.solution import Solution
from setp_solver.algorithms.resetp_alns.operators.strong_bridge import (
    solution_signature_hash,
)

from contracts import (
    CandidateSource,
    CompleteEvaluationLedger,
    CompleteEvaluationRecord,
)


ScoreFunction = Callable[
    [Solution, Any],
    tuple[float, dict[str, float], list[Any]],
]


@dataclass(frozen=True)
class ScoredCandidate:
    solution: Solution
    objective: float
    breakdown: dict[str, float]
    violations: tuple[Any, ...]
    record: CompleteEvaluationRecord

    @property
    def feasible(self) -> bool:
        return not self.violations


class BudgetedCompleteEvaluator:
    """Route every complete candidate through one visible ledger entry."""

    def __init__(
        self,
        *,
        bundle: Any,
        ledger: CompleteEvaluationLedger,
        score_function: ScoreFunction = exact_china81_score,
    ) -> None:
        self.bundle = bundle
        self.ledger = ledger
        self.score_function = score_function

    def score(
        self,
        solution: Solution,
        *,
        source: CandidateSource,
        metadata: dict[str, Any] | None = None,
    ) -> ScoredCandidate:
        signature = solution_signature_hash(solution)
        objective, breakdown, violations = self.score_function(
            solution,
            self.bundle,
        )
        record = self.ledger.register(
            signature=signature,
            source=source,
            feasible=not violations,
            objective=float(objective),
            violation_count=len(violations),
            metadata=metadata,
        )
        return ScoredCandidate(
            solution=solution,
            objective=float(objective),
            breakdown=dict(breakdown),
            violations=tuple(violations),
            record=record,
        )
