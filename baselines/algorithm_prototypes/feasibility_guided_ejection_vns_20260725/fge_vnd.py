"""Best-improvement VND over jointly feasible local and ejection moves."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from contracts import (
    AlgorithmArm,
    CandidateSource,
    CompleteEvaluationLedger,
)
from decoder_cache import RouteLocalDecoderCache
from ejection_rebuild import generate_ejection_rebuild_moves
from evaluation import BudgetedCompleteEvaluator, ScoredCandidate
from feasible_moves import (
    LOCAL_NEIGHBORHOODS,
    NEIGHBORHOOD_ORDER,
    collect_feasible_moves,
    iter_raw_local_moves,
)
from fleet_assignment_dp import decode_assignment_shortlist
from setp_solver.algorithms.resetp_alns.operators.strong_bridge import (
    solution_signature_hash,
)
from setp_solver.solution import Solution

from baselines.algorithm_prototypes.tailored_dp_vns_20260725.neighborhoods import (
    customer_multiset,
)


@dataclass(frozen=True)
class FgeConfig:
    complete_evaluation_limit: int = 120
    inspection_limit_per_local_neighborhood: int = 512
    feasible_structures_per_neighborhood: int = 12
    assignment_candidates_per_structure: int = 2
    assignment_beam_per_state: int = 2
    block_seed_limit: int = 8
    rebuild_beam_width: int = 8
    nearest_anchor_count: int = 24
    improvement_tolerance: float = 1.0e-9


@dataclass(frozen=True)
class FgeRunResult:
    best_solution: Solution
    best_objective: float
    ledger: CompleteEvaluationLedger
    elapsed_seconds: float
    trace: tuple[dict[str, Any], ...]
    neighborhood_stats: dict[str, dict[str, int | bool]]
    improvements_by_neighborhood: dict[str, int]
    accepted_path: tuple[dict[str, Any], ...]
    route_local_cache_stats: dict[str, int | float]
    incomplete_candidate_evaluations: int
    stop_reason: str


def run_fge_vnd(
    bundle: Any,
    initial_solution: Solution,
    *,
    initial_objective: float,
    config: FgeConfig | None = None,
) -> FgeRunResult:
    if config is None:
        config = FgeConfig()
    started = perf_counter()
    baseline_customers = customer_multiset(initial_solution, bundle)
    ledger = CompleteEvaluationLedger(
        arm=AlgorithmArm.RUIN_RECREATE,
        limit=config.complete_evaluation_limit,
    )
    evaluator = BudgetedCompleteEvaluator(bundle=bundle, ledger=ledger)
    cache = RouteLocalDecoderCache()
    incumbent = initial_solution
    incumbent_objective = float(initial_objective)
    seen: set[str] = {solution_signature_hash(initial_solution)}
    trace: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    stats = {
        name: {
            "raw_generated": 0,
            "raw_inspected": 0,
            "feasible_structures": 0,
            "infeasible_structures": 0,
            "full_evaluations": 0,
            "visited": False,
        }
        for name in NEIGHBORHOOD_ORDER
    }
    improvements = {name: 0 for name in NEIGHBORHOOD_ORDER}
    neighborhood_index = 0
    pass_index = 1
    stop_reason = "LOCAL_OPTIMUM"
    incomplete_candidate_evaluations = 0

    while neighborhood_index < len(NEIGHBORHOOD_ORDER) and ledger.remaining:
        neighborhood = NEIGHBORHOOD_ORDER[neighborhood_index]
        stats[neighborhood]["visited"] = True
        if neighborhood in LOCAL_NEIGHBORHOODS:
            collection = collect_feasible_moves(
                iter_raw_local_moves(
                    incumbent,
                    bundle,
                    neighborhood=neighborhood,
                    candidate_pool_limit=(
                        config.inspection_limit_per_local_neighborhood
                    ),
                ),
                bundle,
                baseline_customers=baseline_customers,
                route_local_cache=cache,
                inspection_limit=(
                    config.inspection_limit_per_local_neighborhood
                ),
                feasible_limit=config.feasible_structures_per_neighborhood,
            )
            moves = collection.moves
            stats[neighborhood]["raw_generated"] += (
                collection.raw_generated
            )
            stats[neighborhood]["raw_inspected"] += (
                collection.raw_inspected
            )
            stats[neighborhood]["feasible_structures"] += len(moves)
            stats[neighborhood]["infeasible_structures"] += (
                collection.infeasible_structures
            )
        else:
            moves, rebuild = generate_ejection_rebuild_moves(
                incumbent,
                bundle,
                route_local_cache=cache,
                block_seed_limit=config.block_seed_limit,
                beam_width=config.rebuild_beam_width,
                nearest_anchor_count=config.nearest_anchor_count,
                feasible_limit=config.feasible_structures_per_neighborhood,
            )
            stats[neighborhood]["raw_generated"] += (
                rebuild.partial_structures_inspected
            )
            stats[neighborhood]["raw_inspected"] += (
                rebuild.partial_structures_inspected
            )
            stats[neighborhood]["feasible_structures"] += len(moves)
            stats[neighborhood]["infeasible_structures"] += (
                rebuild.partial_structures_inspected
                - rebuild.partial_structures_feasible
            )

        best: ScoredCandidate | None = None
        best_detail: dict[str, Any] | None = None
        for rank, move in enumerate(moves, start=1):
            if not ledger.remaining:
                stop_reason = "COMPLETE_EVALUATION_LIMIT"
                break
            signature = solution_signature_hash(move.skeleton)
            if signature in seen:
                continue
            seen.add(signature)
            if customer_multiset(move.skeleton, bundle) != baseline_customers:
                raise RuntimeError(
                    f"{neighborhood} changed the customer multiset"
                )
            before = ledger.consumed
            result = decode_assignment_shortlist(
                move.skeleton,
                bundle,
                evaluator=evaluator,
                source=CandidateSource.RUIN_RECREATE,
                beam_per_state=config.assignment_beam_per_state,
                max_candidates=min(
                    config.assignment_candidates_per_structure,
                    ledger.remaining,
                ),
                source_metadata={
                    "algorithm": "FEASIBILITY-GUIDED-EJECTION-VNS",
                    "pass_index": pass_index,
                    "neighborhood": neighborhood,
                    "feasible_rank": rank,
                    "route_local_cost": move.route_local_cost,
                    "distance_delta": move.distance_delta,
                    "detail": move.detail,
                },
                route_local_cache=cache,
                dynamic_state_hash="STATIC",
            )
            used = ledger.consumed - before
            stats[neighborhood]["full_evaluations"] += used
            if result.decoded_count != used:
                incomplete_candidate_evaluations += abs(
                    result.decoded_count - used
                )
            selected = (
                None
                if result.selected is None
                else result.selected.scored
            )
            improved = bool(
                selected is not None
                and selected.feasible
                and selected.objective
                < incumbent_objective - config.improvement_tolerance
            )
            trace.append(
                {
                    "pass_index": pass_index,
                    "neighborhood": neighborhood,
                    "feasible_rank": rank,
                    "structural_signature": signature,
                    "route_local_cost": move.route_local_cost,
                    "distance_delta": move.distance_delta,
                    "detail": move.detail,
                    "evaluations_before": before,
                    "evaluations_after": ledger.consumed,
                    "decoded_count": result.decoded_count,
                    "selected_objective": (
                        None if selected is None else selected.objective
                    ),
                    "improved_incumbent": improved,
                }
            )
            if improved and (
                best is None or selected.objective < best.objective
            ):
                best = selected
                best_detail = {
                    "pass_index": pass_index,
                    "neighborhood": neighborhood,
                    "feasible_rank": rank,
                    "objective_before": incumbent_objective,
                    "objective_after": selected.objective,
                    "detail": move.detail,
                }
        if best is not None:
            incumbent = best.solution
            incumbent_objective = best.objective
            improvements[neighborhood] += 1
            accepted.append(dict(best_detail or {}))
            neighborhood_index = 0
            pass_index += 1
        else:
            neighborhood_index += 1

    if not ledger.remaining:
        stop_reason = "COMPLETE_EVALUATION_LIMIT"
    return FgeRunResult(
        best_solution=incumbent,
        best_objective=incumbent_objective,
        ledger=ledger,
        elapsed_seconds=perf_counter() - started,
        trace=tuple(trace),
        neighborhood_stats=stats,
        improvements_by_neighborhood=improvements,
        accepted_path=tuple(accepted),
        route_local_cache_stats=cache.as_dict(),
        incomplete_candidate_evaluations=incomplete_candidate_evaluations,
        stop_reason=stop_reason,
    )
