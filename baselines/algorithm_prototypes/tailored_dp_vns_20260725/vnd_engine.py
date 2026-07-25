"""Deterministic variable-neighbourhood descent with the full ReSETP decoder."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from setp_solver.solution import Solution
from setp_solver.algorithms.resetp_alns.operators.strong_bridge import (
    solution_signature_hash,
)

from contracts import (
    AlgorithmArm,
    CandidateSource,
    CompleteEvaluationLedger,
)
from decoder_cache import RouteLocalDecoderCache
from evaluation import BudgetedCompleteEvaluator, ScoredCandidate
from fleet_assignment_dp import (
    NoFeasibleAssignmentError,
    decode_assignment_shortlist,
)

from neighborhoods import (
    NEIGHBORHOOD_ORDER,
    customer_multiset,
    generate_ranked_candidates,
)


@dataclass(frozen=True)
class VndConfig:
    complete_evaluation_limit: int = 96
    structural_candidates_per_neighborhood: int = 10
    assignment_candidates_per_skeleton: int = 2
    assignment_beam_per_state: int = 2
    improvement_tolerance: float = 1.0e-9

    def __post_init__(self) -> None:
        if self.complete_evaluation_limit < 1:
            raise ValueError("complete evaluation limit must be positive")
        if self.structural_candidates_per_neighborhood < 1:
            raise ValueError("structural shortlist must be positive")
        if self.assignment_candidates_per_skeleton < 1:
            raise ValueError("assignment shortlist must be positive")
        if self.assignment_beam_per_state < 1:
            raise ValueError("assignment beam must be positive")
        if self.improvement_tolerance < 0.0:
            raise ValueError("improvement tolerance must be non-negative")


@dataclass(frozen=True)
class VndTraceRow:
    pass_index: int
    neighborhood: str
    structural_rank: int
    structural_signature: str
    proxy_delta: float
    detail: str
    evaluations_before: int
    evaluations_after: int
    decoded_count: int
    feasible_count: int
    selected_objective: float | None
    improved_incumbent: bool
    failure: str | None


@dataclass(frozen=True)
class VndRunResult:
    best_solution: Solution
    best_objective: float
    ledger: CompleteEvaluationLedger
    trace: tuple[VndTraceRow, ...]
    elapsed_seconds: float
    generated_by_neighborhood: dict[str, int]
    evaluated_by_neighborhood: dict[str, int]
    improvements_by_neighborhood: dict[str, int]
    decode_failures_by_neighborhood: dict[str, int]
    accepted_path: tuple[dict[str, Any], ...]
    stop_reason: str
    route_local_cache_stats: dict[str, int | float]


def run_tailored_dp_vnd(
    bundle: Any,
    initial_solution: Solution,
    *,
    initial_objective: float,
    config: VndConfig = VndConfig(),
) -> VndRunResult:
    """Run a systematic best-improvement VND from one complete solution."""

    started = perf_counter()
    baseline_customers = customer_multiset(initial_solution, bundle)
    ledger = CompleteEvaluationLedger(
        arm=AlgorithmArm.RUIN_RECREATE,
        limit=config.complete_evaluation_limit,
    )
    evaluator = BudgetedCompleteEvaluator(bundle=bundle, ledger=ledger)
    route_local_cache = RouteLocalDecoderCache()
    incumbent_solution = initial_solution
    incumbent_objective = float(initial_objective)
    trace: list[VndTraceRow] = []
    accepted_path: list[dict[str, Any]] = []
    generated = {name: 0 for name in NEIGHBORHOOD_ORDER}
    evaluated = {name: 0 for name in NEIGHBORHOOD_ORDER}
    improvements = {name: 0 for name in NEIGHBORHOOD_ORDER}
    failures = {name: 0 for name in NEIGHBORHOOD_ORDER}
    seen_structures: set[str] = {
        solution_signature_hash(incumbent_solution),
    }
    neighborhood_index = 0
    pass_index = 1
    stop_reason = "LOCAL_OPTIMUM"

    while neighborhood_index < len(NEIGHBORHOOD_ORDER) and ledger.remaining > 0:
        neighborhood = NEIGHBORHOOD_ORDER[neighborhood_index]
        candidates = generate_ranked_candidates(
            incumbent_solution,
            bundle,
            neighborhood=neighborhood,
            limit=config.structural_candidates_per_neighborhood,
        )
        generated[neighborhood] += len(candidates)
        best_candidate: ScoredCandidate | None = None
        best_candidate_detail: dict[str, Any] | None = None

        for structural_rank, candidate in enumerate(candidates, start=1):
            if ledger.remaining <= 0:
                stop_reason = "COMPLETE_EVALUATION_LIMIT"
                break
            structural_signature = solution_signature_hash(candidate.skeleton)
            if structural_signature in seen_structures:
                continue
            seen_structures.add(structural_signature)
            if customer_multiset(candidate.skeleton, bundle) != baseline_customers:
                raise RuntimeError(
                    f"{neighborhood} changed the customer multiset"
                )
            before = ledger.consumed
            failure: str | None = None
            selected: ScoredCandidate | None = None
            decoded_count = 0
            feasible_count = 0
            try:
                result = decode_assignment_shortlist(
                    candidate.skeleton,
                    bundle,
                    evaluator=evaluator,
                    source=CandidateSource.RUIN_RECREATE,
                    beam_per_state=config.assignment_beam_per_state,
                    max_candidates=min(
                        config.assignment_candidates_per_skeleton,
                        ledger.remaining,
                    ),
                    source_metadata={
                        "algorithm": "TAILORED-DP-VNS",
                        "neighborhood": neighborhood,
                        "structural_rank": structural_rank,
                        "proxy_delta": candidate.proxy_delta,
                        "detail": candidate.detail,
                        "pass_index": pass_index,
                    },
                    route_local_cache=route_local_cache,
                    dynamic_state_hash="STATIC",
                )
                decoded_count = result.decoded_count
                feasible_count = len(result.decoded)
                selected = (
                    None
                    if result.selected is None
                    else result.selected.scored
                )
            except (
                KeyError,
                NoFeasibleAssignmentError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as exc:
                failure = f"{type(exc).__name__}:{exc}"
                failures[neighborhood] += 1

            after = ledger.consumed
            evaluated[neighborhood] += after - before
            improved = bool(
                selected is not None
                and selected.feasible
                and (
                    selected.objective
                    < incumbent_objective - config.improvement_tolerance
                )
            )
            trace.append(
                VndTraceRow(
                    pass_index=pass_index,
                    neighborhood=neighborhood,
                    structural_rank=structural_rank,
                    structural_signature=structural_signature,
                    proxy_delta=candidate.proxy_delta,
                    detail=candidate.detail,
                    evaluations_before=before,
                    evaluations_after=after,
                    decoded_count=decoded_count,
                    feasible_count=feasible_count,
                    selected_objective=(
                        None if selected is None else selected.objective
                    ),
                    improved_incumbent=improved,
                    failure=failure,
                )
            )
            if improved and (
                best_candidate is None
                or selected.objective < best_candidate.objective
            ):
                best_candidate = selected
                best_candidate_detail = {
                    "pass_index": pass_index,
                    "neighborhood": neighborhood,
                    "structural_rank": structural_rank,
                    "proxy_delta": candidate.proxy_delta,
                    "detail": candidate.detail,
                    "objective_before": incumbent_objective,
                    "objective_after": selected.objective,
                    "complete_evaluation_index": selected.record.index,
                }

        if best_candidate is not None:
            incumbent_solution = best_candidate.solution
            incumbent_objective = best_candidate.objective
            improvements[neighborhood] += 1
            accepted_path.append(dict(best_candidate_detail or {}))
            neighborhood_index = 0
            pass_index += 1
            continue
        neighborhood_index += 1

    if ledger.remaining <= 0:
        stop_reason = "COMPLETE_EVALUATION_LIMIT"
    return VndRunResult(
        best_solution=incumbent_solution,
        best_objective=incumbent_objective,
        ledger=ledger,
        trace=tuple(trace),
        elapsed_seconds=perf_counter() - started,
        generated_by_neighborhood=generated,
        evaluated_by_neighborhood=evaluated,
        improvements_by_neighborhood=improvements,
        decode_failures_by_neighborhood=failures,
        accepted_path=tuple(accepted_path),
        stop_reason=stop_reason,
        route_local_cache_stats=route_local_cache.as_dict(),
    )

