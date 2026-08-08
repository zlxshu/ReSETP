"""Reproducible Duty-HGS initial-population construction.

PyVRP supplies only random route skeletons.  Physical-vehicle identity,
multi-trip reconstruction, charging, and complete feasibility remain in the
Duty layer.  The caller chooses the requested population size and attempt
budget; this module does not freeze either value.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from .charging import ChargingRepairPolicy, repair_changed_duties
from .evaluation import DutyFullEvaluator, FullEvaluation
from .model import DutyIndividual
from .pyvrp_proposals import PyVRPDutyRouteProposalEngine


@dataclass(frozen=True)
class InitialPopulationAttempt:
    random_seed: int
    status: str
    fingerprint: str | None
    feasible: bool | None
    violation_types: tuple[str, ...]
    error_type: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class InitialPopulationResult:
    candidates: tuple[DutyIndividual, ...]
    evaluations: tuple[FullEvaluation, ...]
    attempts: tuple[InitialPopulationAttempt, ...]
    requested_size: int
    actual_size: int
    attempts_exhausted: bool
    full_evaluation_count: int
    wall_seconds: float


def build_initial_population(
    initial: DutyIndividual,
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    route_engine: PyVRPDutyRouteProposalEngine,
    requested_size: int,
    random_seed: int,
    max_random_attempts: int,
) -> InitialPopulationResult:
    """Keep the registered solution and add fully evaluated random skeletons."""

    if requested_size < 1:
        raise ValueError("requested_size must be positive")
    if max_random_attempts < 0:
        raise ValueError("max_random_attempts cannot be negative")

    started = perf_counter()
    full_evaluation_count = 0
    full_evaluation_count += 1
    initial_evaluation = evaluator.evaluate(initial)
    candidates = [initial]
    evaluations = [initial_evaluation]
    seen = {initial.fingerprint}
    attempts: list[InitialPopulationAttempt] = []
    for offset in range(max_random_attempts):
        if len(candidates) >= requested_size:
            break
        seed = int(random_seed) + offset
        try:
            move = route_engine.random_skeleton_move(
                initial,
                random_seed=seed,
            )
            if move is None:
                attempts.append(
                    InitialPopulationAttempt(
                        random_seed=seed,
                        status="DUPLICATE_SKELETON",
                        fingerprint=initial.fingerprint,
                        feasible=initial_evaluation.feasible,
                        violation_types=tuple(
                            violation.type
                            for violation in initial_evaluation.violations
                        ),
                    )
                )
                continue
            candidate = move.apply(initial)
            candidate = repair_changed_duties(
                initial,
                candidate,
                changed_duty_ids=set(move.changed_duty_ids),
                context=evaluator.context,
                policy=charging_policy,
            )
            full_evaluation_count += 1
            evaluation = evaluator.evaluate(candidate)
        except (AssertionError, RuntimeError, TypeError, ValueError) as exc:
            attempts.append(
                InitialPopulationAttempt(
                    random_seed=seed,
                    status="REJECTED",
                    fingerprint=None,
                    feasible=None,
                    violation_types=(),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            )
            continue
        if candidate.fingerprint in seen:
            attempts.append(
                InitialPopulationAttempt(
                    random_seed=seed,
                    status="DUPLICATE_CANDIDATE",
                    fingerprint=candidate.fingerprint,
                    feasible=evaluation.feasible,
                    violation_types=tuple(
                        violation.type for violation in evaluation.violations
                    ),
                )
            )
            continue
        seen.add(candidate.fingerprint)
        candidates.append(candidate)
        evaluations.append(evaluation)
        attempts.append(
            InitialPopulationAttempt(
                random_seed=seed,
                status="ADMITTED",
                fingerprint=candidate.fingerprint,
                feasible=evaluation.feasible,
                violation_types=tuple(
                    violation.type for violation in evaluation.violations
                ),
            )
        )

    return InitialPopulationResult(
        candidates=tuple(candidates),
        evaluations=tuple(evaluations),
        attempts=tuple(attempts),
        requested_size=int(requested_size),
        actual_size=len(candidates),
        attempts_exhausted=(
            len(candidates) < requested_size
            and len(attempts) >= max_random_attempts
        ),
        full_evaluation_count=full_evaluation_count,
        wall_seconds=perf_counter() - started,
    )
