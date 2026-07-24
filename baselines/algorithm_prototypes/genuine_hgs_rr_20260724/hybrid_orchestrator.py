"""Auditable A, B, and genuinely cooperative A+B orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import math
from time import perf_counter
from typing import Any

from setp_solver.china81 import China81Bundle
from setp_solver.solution import Solution
from setp_solver.algorithms.resetp_alns.operators.strong_bridge import (
    solution_signature_hash,
)

from contracts import (
    AlgorithmArm,
    CandidateSource,
    CompleteEvaluationLedger,
    HybridLineageLedger,
    TransferDirection,
)
from decoder_cache import RouteLocalDecoderCache
from evaluation import BudgetedCompleteEvaluator, ScoredCandidate
from fleet_assignment_dp import decode_assignment_shortlist
from hgs_generator import HgsGeneratedArchive, generate_hgs_archive
from rr_engine import RrConfig, RrRunResult, run_mechanism_aware_rr


@dataclass(frozen=True)
class ArmBudgetPlan:
    total: int
    initial_evaluations: int
    hgs_epoch_evaluations: tuple[int, ...]
    rr_phase_evaluations: tuple[int, ...]

    def __post_init__(self) -> None:
        parts = (
            self.initial_evaluations
            + sum(self.hgs_epoch_evaluations)
            + sum(self.rr_phase_evaluations)
        )
        if self.total < 1 or parts != self.total:
            raise ValueError(f"budget plan does not close: {parts}!={self.total}")
        if self.initial_evaluations != 1:
            raise ValueError("every arm must count the shared initial solution once")
        if any(
            item < 1
            for item in (
                *self.hgs_epoch_evaluations,
                *self.rr_phase_evaluations,
            )
        ):
            raise ValueError("all active phases require positive budget")


def make_arm_budget_plan(
    arm: AlgorithmArm,
    total: int,
    *,
    cooperative_hgs_fraction: float = 0.60,
) -> ArmBudgetPlan:
    """Create the frozen complete-evaluation allocation.

    The initial complete solution consumes one evaluation in every arm.  The
    cooperative arm then alternates three HGS epochs and two RR phases.
    """

    total = int(total)
    if total < 6:
        raise ValueError("at least six complete evaluations are required")
    remaining = total - 1
    if arm == AlgorithmArm.HGS:
        return ArmBudgetPlan(
            total=total,
            initial_evaluations=1,
            hgs_epoch_evaluations=_split_integer(
                remaining,
                3,
            ),
            rr_phase_evaluations=(),
        )
    if arm == AlgorithmArm.RUIN_RECREATE:
        return ArmBudgetPlan(
            total=total,
            initial_evaluations=1,
            hgs_epoch_evaluations=(),
            rr_phase_evaluations=(remaining,),
        )
    if arm != AlgorithmArm.COOPERATIVE:
        raise ValueError(f"unsupported arm {arm.value}")
    if not 0.0 < cooperative_hgs_fraction < 1.0:
        raise ValueError("cooperative HGS fraction must be in (0, 1)")
    hgs_total = int(round(total * cooperative_hgs_fraction))
    hgs_total = min(remaining - 2, max(3, hgs_total))
    rr_total = remaining - hgs_total
    return ArmBudgetPlan(
        total=total,
        initial_evaluations=1,
        hgs_epoch_evaluations=_split_integer(hgs_total, 3),
        rr_phase_evaluations=_split_integer(rr_total, 2),
    )


@dataclass(frozen=True)
class CooperativeConfig:
    complete_evaluation_budget: int
    hgs_iterations_for_a: int
    hgs_wallclock_safety_seconds_per_mode: float
    route_proxy_modes: tuple[str, ...] = (
        "cv_only",
        "naive_ev",
        "mechanism_ev",
    )
    cooperative_hgs_fraction: float = 0.60
    hgs_archive_candidates_per_mode: int = 24
    assignment_beam_per_state: int = 2
    assignment_shortlist_per_skeleton: int = 3
    max_hgs_padding_fraction: float = 0.05
    rr: RrConfig = RrConfig()

    def __post_init__(self) -> None:
        if self.complete_evaluation_budget < 6:
            raise ValueError("complete evaluation budget is too small")
        if self.hgs_iterations_for_a < 3:
            raise ValueError("A requires at least three HGS iterations")
        if self.hgs_wallclock_safety_seconds_per_mode <= 0.0:
            raise ValueError("HGS safety cap must be positive")
        if not self.route_proxy_modes:
            raise ValueError("at least one HGS proxy mode is required")
        if len(set(self.route_proxy_modes)) != len(self.route_proxy_modes):
            raise ValueError("HGS proxy modes must be unique")
        if self.hgs_archive_candidates_per_mode < 1:
            raise ValueError("HGS archive size must be positive")
        if (
            self.assignment_beam_per_state < 1
            or self.assignment_shortlist_per_skeleton < 1
        ):
            raise ValueError("assignment decoder limits must be positive")
        if not 0.0 <= self.max_hgs_padding_fraction <= 1.0:
            raise ValueError("HGS padding fraction must be in [0, 1]")


@dataclass(frozen=True)
class HgsEpochResult:
    epoch: int
    best_generated: ScoredCandidate
    best_novel_generated: ScoredCandidate | None
    archives: tuple[HgsGeneratedArchive, ...]
    evaluated_candidates: int
    feasible_candidates: int
    unique_candidate_signatures: int
    duplicate_evaluations: int
    padding_rechecks: int
    elapsed_seconds: float
    decode_failures: tuple[str, ...]


@dataclass(frozen=True)
class ArmRunResult:
    arm: AlgorithmArm
    best_solution: Solution
    best_objective: float
    best_record_index: int
    ledger: CompleteEvaluationLedger
    budget_plan: ArmBudgetPlan
    hgs_epochs: tuple[HgsEpochResult, ...]
    rr_phases: tuple[RrRunResult, ...]
    lineage: HybridLineageLedger | None
    route_local_cache_stats: dict[str, int | float]
    elapsed_seconds: float
    stop_reason: str


def run_hgs_arm(
    bundle: China81Bundle,
    initial_solution: Solution,
    *,
    seed: int,
    config: CooperativeConfig,
) -> ArmRunResult:
    """Run algorithm A under the shared complete-evaluation budget."""

    started = perf_counter()
    plan = make_arm_budget_plan(
        AlgorithmArm.HGS,
        config.complete_evaluation_budget,
        cooperative_hgs_fraction=config.cooperative_hgs_fraction,
    )
    ledger = CompleteEvaluationLedger(
        arm=AlgorithmArm.HGS,
        limit=plan.total,
    )
    route_local_cache = RouteLocalDecoderCache()
    incumbent = _score_initial(bundle, initial_solution, ledger)
    hgs_iterations = _split_integer(
        config.hgs_iterations_for_a,
        len(plan.hgs_epoch_evaluations),
    )
    epochs: list[HgsEpochResult] = []
    for epoch, (evaluation_allowance, iteration_allowance) in enumerate(
        zip(plan.hgs_epoch_evaluations, hgs_iterations),
        start=1,
    ):
        result = _run_hgs_epoch(
            bundle,
            warm_solutions=(incumbent.solution,),
            seed=_derived_seed(seed, "A_HGS", epoch),
            epoch=epoch,
            iteration_allowance=iteration_allowance,
            evaluation_allowance=evaluation_allowance,
            ledger=ledger,
            candidate_source=CandidateSource.HGS_ARCHIVE,
            config=config,
            route_local_cache=route_local_cache,
        )
        epochs.append(result)
        if result.best_generated.objective < incumbent.objective:
            incumbent = result.best_generated
    ledger.assert_exactly_closed()
    return ArmRunResult(
        arm=AlgorithmArm.HGS,
        best_solution=incumbent.solution,
        best_objective=incumbent.objective,
        best_record_index=incumbent.record.index,
        ledger=ledger,
        budget_plan=plan,
        hgs_epochs=tuple(epochs),
        rr_phases=(),
        lineage=None,
        route_local_cache_stats=route_local_cache.as_dict(),
        elapsed_seconds=perf_counter() - started,
        stop_reason="COMPLETE_EVALUATION_BUDGET",
    )


def run_rr_arm(
    bundle: China81Bundle,
    initial_solution: Solution,
    *,
    seed: int,
    config: CooperativeConfig,
) -> ArmRunResult:
    """Run independent mechanism-aware algorithm B."""

    started = perf_counter()
    plan = make_arm_budget_plan(
        AlgorithmArm.RUIN_RECREATE,
        config.complete_evaluation_budget,
        cooperative_hgs_fraction=config.cooperative_hgs_fraction,
    )
    ledger = CompleteEvaluationLedger(
        arm=AlgorithmArm.RUIN_RECREATE,
        limit=plan.total,
    )
    route_local_cache = RouteLocalDecoderCache()
    initial = _score_initial(bundle, initial_solution, ledger)
    rr = run_mechanism_aware_rr(
        bundle,
        initial.solution,
        initial_objective=initial.objective,
        seed=_derived_seed(seed, "B_RR", 1),
        ledger=ledger,
        config=config.rr,
        max_additional_evaluations=plan.rr_phase_evaluations[0],
        route_local_cache=route_local_cache,
    )
    if ledger.consumed != ledger.limit:
        raise RuntimeError(
            "B stopped before closing the complete-evaluation budget: "
            f"{ledger.consumed}/{ledger.limit}:{rr.stop_reason}"
        )
    ledger.assert_exactly_closed()
    best_record = _record_for_solution(
        ledger,
        rr.best_solution,
        rr.best_objective,
    )
    return ArmRunResult(
        arm=AlgorithmArm.RUIN_RECREATE,
        best_solution=rr.best_solution,
        best_objective=rr.best_objective,
        best_record_index=best_record.index,
        ledger=ledger,
        budget_plan=plan,
        hgs_epochs=(),
        rr_phases=(rr,),
        lineage=None,
        route_local_cache_stats=route_local_cache.as_dict(),
        elapsed_seconds=perf_counter() - started,
        stop_reason=rr.stop_reason,
    )


def run_cooperative_arm(
    bundle: China81Bundle,
    initial_solution: Solution,
    *,
    seed: int,
    config: CooperativeConfig,
) -> ArmRunResult:
    """Run the HGS -> RR -> HGS -> RR -> HGS cooperative arm."""

    started = perf_counter()
    plan = make_arm_budget_plan(
        AlgorithmArm.COOPERATIVE,
        config.complete_evaluation_budget,
        cooperative_hgs_fraction=config.cooperative_hgs_fraction,
    )
    ledger = CompleteEvaluationLedger(
        arm=AlgorithmArm.COOPERATIVE,
        limit=plan.total,
    )
    route_local_cache = RouteLocalDecoderCache()
    lineage = HybridLineageLedger()
    incumbent = _score_initial(bundle, initial_solution, ledger)
    cooperative_iterations = max(
        3,
        int(round(config.hgs_iterations_for_a * config.cooperative_hgs_fraction)),
    )
    hgs_iterations = _split_integer(
        cooperative_iterations,
        len(plan.hgs_epoch_evaluations),
    )
    hgs_epochs: list[HgsEpochResult] = []
    rr_phases: list[RrRunResult] = []
    warm_solutions: tuple[Solution, ...] = (incumbent.solution,)
    pending_rr_injection: (
        tuple[
            Solution,
            float,
            int,
        ]
        | None
    ) = None

    for epoch in range(1, 4):
        hgs = _run_hgs_epoch(
            bundle,
            warm_solutions=warm_solutions,
            seed=_derived_seed(seed, "AB_HGS", epoch),
            epoch=epoch,
            iteration_allowance=hgs_iterations[epoch - 1],
            evaluation_allowance=plan.hgs_epoch_evaluations[epoch - 1],
            ledger=ledger,
            candidate_source=(
                CandidateSource.HGS_ARCHIVE
                if epoch == 1
                else CandidateSource.HGS_DESCENDANT
            ),
            config=config,
            route_local_cache=route_local_cache,
        )
        hgs_epochs.append(hgs)
        hgs_candidate = hgs.best_novel_generated
        if hgs_candidate is None:
            raise RuntimeError(f"HGS epoch {epoch} produced no novel complete solution")
        if (
            pending_rr_injection is not None
            and hgs_candidate.record.source == CandidateSource.HGS_DESCENDANT
        ):
            injected_solution, injected_objective, _ = pending_rr_injection
            injected_signature = solution_signature_hash(injected_solution)
            descendant_signature = solution_signature_hash(hgs_candidate.solution)
            if (
                descendant_signature != injected_signature
                and hgs_candidate.objective < injected_objective - 1.0e-9
            ):
                lineage.add_hgs_descendant(
                    epoch=epoch,
                    injected_rr_signature=injected_signature,
                    descendant_signature=descendant_signature,
                    injected_objective=injected_objective,
                    descendant_objective=hgs_candidate.objective,
                    complete_evaluation_index=(hgs_candidate.record.index),
                )
        if hgs_candidate.objective < incumbent.objective:
            incumbent = hgs_candidate
        pending_rr_injection = None
        if epoch == 3:
            break

        rr_allowance = plan.rr_phase_evaluations[epoch - 1]
        hgs_signature = solution_signature_hash(hgs_candidate.solution)
        warm_parent_signature = solution_signature_hash(warm_solutions[0])
        lineage.add_transfer(
            direction=TransferDirection.HGS_TO_RR,
            parent_signature=warm_parent_signature,
            child_signature=hgs_signature,
            parent_objective=(
                _objective_for_signature(
                    ledger,
                    warm_parent_signature,
                )
                or incumbent.objective
            ),
            child_objective=hgs_candidate.objective,
            complete_evaluation_index=hgs_candidate.record.index,
            accepted_into_next_hgs_epoch=False,
            next_hgs_epoch=None,
        )
        rr = run_mechanism_aware_rr(
            bundle,
            hgs_candidate.solution,
            initial_objective=hgs_candidate.objective,
            seed=_derived_seed(seed, "AB_RR", epoch),
            ledger=ledger,
            config=config.rr,
            max_additional_evaluations=rr_allowance,
            route_local_cache=route_local_cache,
        )
        rr_phases.append(rr)
        if rr.best_objective < incumbent.objective:
            record = _record_for_solution(
                ledger,
                rr.best_solution,
                rr.best_objective,
            )
            incumbent = ScoredCandidate(
                solution=rr.best_solution,
                objective=rr.best_objective,
                breakdown={},
                violations=(),
                record=record,
            )
        injection = _accepted_rr_injection(rr)
        if injection is None:
            warm_solutions = _unique_solutions(
                (incumbent.solution, hgs_candidate.solution)
            )
            continue
        injected_solution, injected_objective, injected_index = injection
        injected_signature = solution_signature_hash(injected_solution)
        lineage.add_transfer(
            direction=TransferDirection.RR_TO_HGS,
            parent_signature=hgs_signature,
            child_signature=injected_signature,
            parent_objective=hgs_candidate.objective,
            child_objective=injected_objective,
            complete_evaluation_index=injected_index,
            accepted_into_next_hgs_epoch=True,
            next_hgs_epoch=epoch + 1,
        )
        pending_rr_injection = injection
        warm_solutions = _unique_solutions(
            (
                injected_solution,
                incumbent.solution,
                hgs_candidate.solution,
            )
        )

    ledger.assert_exactly_closed()
    lineage.assert_genuine_cooperation()
    return ArmRunResult(
        arm=AlgorithmArm.COOPERATIVE,
        best_solution=incumbent.solution,
        best_objective=incumbent.objective,
        best_record_index=incumbent.record.index,
        ledger=ledger,
        budget_plan=plan,
        hgs_epochs=tuple(hgs_epochs),
        rr_phases=tuple(rr_phases),
        lineage=lineage,
        route_local_cache_stats=route_local_cache.as_dict(),
        elapsed_seconds=perf_counter() - started,
        stop_reason="PASS_GENUINE_BIDIRECTIONAL_COOPERATION",
    )


def _run_hgs_epoch(
    bundle: China81Bundle,
    *,
    warm_solutions: tuple[Solution, ...],
    seed: int,
    epoch: int,
    iteration_allowance: int,
    evaluation_allowance: int,
    ledger: CompleteEvaluationLedger,
    candidate_source: CandidateSource,
    config: CooperativeConfig,
    route_local_cache: RouteLocalDecoderCache,
) -> HgsEpochResult:
    started = perf_counter()
    phase_start = ledger.consumed
    phase_stop = phase_start + int(evaluation_allowance)
    if phase_stop > ledger.limit:
        raise RuntimeError("HGS phase exceeds ledger budget")
    mode_iterations = _split_integer(
        int(iteration_allowance),
        len(config.route_proxy_modes),
    )
    archives = tuple(
        generate_hgs_archive(
            bundle,
            warm_solutions,
            seed=_derived_seed(seed, mode, mode_index),
            max_iterations=mode_iterations[mode_index - 1],
            wallclock_safety_seconds=(config.hgs_wallclock_safety_seconds_per_mode),
            route_proxy_mode=mode,
            max_archive_candidates=(config.hgs_archive_candidates_per_mode),
        )
        for mode_index, mode in enumerate(
            config.route_proxy_modes,
            start=1,
        )
    )
    candidates = _round_robin_archive_candidates(archives)
    feasible: list[ScoredCandidate] = []
    decode_failures: list[str] = []
    for archive, candidate in candidates:
        if ledger.consumed >= phase_stop:
            break
        try:
            decoded = decode_assignment_shortlist(
                candidate.skeleton,
                bundle,
                evaluator=BudgetedCompleteEvaluator(
                    bundle=bundle,
                    ledger=ledger,
                ),
                source=candidate_source,
                beam_per_state=config.assignment_beam_per_state,
                max_candidates=min(
                    config.assignment_shortlist_per_skeleton,
                    phase_stop - ledger.consumed,
                ),
                source_metadata={
                    "hgs_epoch": epoch,
                    "route_proxy_mode": archive.route_proxy_mode,
                    "hgs_seed": archive.seed,
                    "proxy_rank": candidate.proxy_rank,
                    "proxy_cost": candidate.proxy_cost,
                    "warm_signatures": list(archive.warm_signatures),
                },
                route_local_cache=route_local_cache,
                dynamic_state_hash="STATIC",
            )
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            decode_failures.append(
                f"{archive.route_proxy_mode}:{candidate.proxy_rank}:{exc}"
            )
            continue
        feasible.extend(item.scored for item in decoded.decoded)
    padding_rechecks = 0
    if ledger.consumed < phase_stop:
        if not feasible:
            raise RuntimeError("HGS epoch produced no completely feasible candidate")
        padding_limit = int(
            math.floor(evaluation_allowance * config.max_hgs_padding_fraction)
        )
        missing = phase_stop - ledger.consumed
        if missing > padding_limit:
            raise RuntimeError(
                "HGS archive could not close its budget without "
                f"excessive duplicate rechecks: {missing}>{padding_limit}"
            )
        best = min(feasible, key=lambda item: item.objective)
        evaluator = BudgetedCompleteEvaluator(
            bundle=bundle,
            ledger=ledger,
        )
        while ledger.consumed < phase_stop:
            duplicate = evaluator.score(
                best.solution,
                source=candidate_source,
                metadata={
                    "hgs_epoch": epoch,
                    "budget_padding_recheck": True,
                },
            )
            if duplicate.feasible:
                feasible.append(duplicate)
            padding_rechecks += 1
    if ledger.consumed != phase_stop:
        raise RuntimeError(f"HGS phase budget mismatch {ledger.consumed}!={phase_stop}")
    best_generated = min(
        feasible,
        key=lambda item: (
            item.objective,
            item.record.index,
        ),
    )
    warm_signatures = {solution_signature_hash(solution) for solution in warm_solutions}
    novel = [
        item
        for item in feasible
        if solution_signature_hash(item.solution) not in warm_signatures
    ]
    best_novel_generated = (
        min(
            novel,
            key=lambda item: (
                item.objective,
                item.record.index,
            ),
        )
        if novel
        else None
    )
    phase_records = ledger.records[phase_start:phase_stop]
    return HgsEpochResult(
        epoch=epoch,
        best_generated=best_generated,
        best_novel_generated=best_novel_generated,
        archives=archives,
        evaluated_candidates=evaluation_allowance,
        feasible_candidates=len(feasible),
        unique_candidate_signatures=len({record.signature for record in phase_records}),
        duplicate_evaluations=sum(
            record.duplicate_of_index is not None for record in phase_records
        ),
        padding_rechecks=padding_rechecks,
        elapsed_seconds=perf_counter() - started,
        decode_failures=tuple(decode_failures),
    )


def _score_initial(
    bundle: China81Bundle,
    initial_solution: Solution,
    ledger: CompleteEvaluationLedger,
) -> ScoredCandidate:
    initial = BudgetedCompleteEvaluator(
        bundle=bundle,
        ledger=ledger,
    ).score(
        initial_solution,
        source=CandidateSource.SHARED_INITIAL,
        metadata={"shared_initial": True},
    )
    if not initial.feasible:
        raise RuntimeError("shared initial solution is not fully feasible")
    return initial


def _accepted_rr_injection(
    result: RrRunResult,
) -> tuple[Solution, float, int] | None:
    if (
        result.best_generated_solution is None
        or result.best_generated_objective is None
        or result.best_generated_record_index is None
    ):
        return None
    return (
        result.best_generated_solution,
        result.best_generated_objective,
        result.best_generated_record_index,
    )


def _record_for_solution(
    ledger: CompleteEvaluationLedger,
    solution: Solution,
    objective: float,
):
    signature = solution_signature_hash(solution)
    matches = [
        record
        for record in ledger.records
        if (
            record.signature == signature
            and record.feasible
            and record.objective is not None
            and abs(record.objective - objective) <= 1.0e-6
        )
    ]
    if not matches:
        raise RuntimeError("best solution has no matching complete-evaluation record")
    return matches[-1]


def _objective_for_signature(
    ledger: CompleteEvaluationLedger,
    signature: str,
) -> float | None:
    values = [
        float(record.objective)
        for record in ledger.records
        if (
            record.signature == signature
            and record.feasible
            and record.objective is not None
        )
    ]
    return min(values) if values else None


def _unique_solutions(
    solutions: tuple[Solution, ...],
) -> tuple[Solution, ...]:
    unique: dict[str, Solution] = {}
    for solution in solutions:
        unique.setdefault(
            solution_signature_hash(solution),
            solution,
        )
    return tuple(unique.values())


def _round_robin_archive_candidates(
    archives: tuple[HgsGeneratedArchive, ...],
) -> tuple[tuple[HgsGeneratedArchive, Any], ...]:
    rows: list[tuple[HgsGeneratedArchive, Any]] = []
    max_length = max(len(archive.candidates) for archive in archives)
    for rank in range(max_length):
        for archive in archives:
            if rank < len(archive.candidates):
                rows.append((archive, archive.candidates[rank]))
    return tuple(rows)


def _split_integer(total: int, parts: int) -> tuple[int, ...]:
    total = int(total)
    parts = int(parts)
    if parts < 1 or total < parts:
        raise ValueError(f"cannot split {total} into {parts} positive parts")
    quotient, remainder = divmod(total, parts)
    return tuple(quotient + (1 if index < remainder else 0) for index in range(parts))


def _derived_seed(seed: int, label: str, index: int) -> int:
    value = int(seed) & 0x7FFFFFFF
    for character in f"{label}:{index}":
        value = (value * 1_103_515_245 + ord(character) + 12_345) & 0x7FFFFFFF
    return max(1, value)
