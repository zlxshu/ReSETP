"""Reproducible Problem-HGS initial-population construction.

IndependentKernel supplies only random route skeletons.  Physical-vehicle identity,
multi-trip reconstruction, charging, and complete feasibility remain in the
Duty layer.  The caller chooses the requested population size and attempt
budget; this module does not freeze either value.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

from .charging import ChargingRepairPolicy, repair_changed_duties
from .evaluation import DutyFullEvaluator, FullEvaluation
from .fleet_registry import assert_fleet_activation_allowed
from .model import DutyIndividual
from .kernel_proposals import IndependentKernelDutyRouteProposalEngine
from .contracts import CandidateStatus, SearchAccounting
from .education import evaluate_move
from .repair import insertion_moves, regret2_repair
from .operators import ExchangeUnservedMove


@dataclass(frozen=True)
class InitialPopulationAttempt:
    random_seed: int
    status: str
    fingerprint: str | None
    feasible: bool | None
    violation_types: tuple[str, ...]
    error_type: str | None = None
    error: str | None = None
    wall_seconds: float = 0.0


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


@dataclass(frozen=True)
class DynamicWarmStartAttempt:
    action_id: str
    status: str
    fingerprint: str | None
    feasible: bool | None
    violation_types: tuple[str, ...]
    error_type: str | None = None
    error: str | None = None
    wall_seconds: float = 0.0


@dataclass(frozen=True)
class DynamicWarmStartResult:
    candidates: tuple[DutyIndividual, ...]
    evaluations: tuple[FullEvaluation, ...]
    attempts: tuple[DynamicWarmStartAttempt, ...]
    requested_size: int
    actual_size: int
    attempts_exhausted: bool
    full_evaluation_count: int
    wall_seconds: float


def build_dynamic_warm_start_population(
    initial: DutyIndividual,
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    penalized_cost: Callable[[FullEvaluation], float],
    requested_size: int,
    stop_requested: Callable[[], bool] | None = None,
) -> DynamicWarmStartResult:
    """Seed a disclosure stage by exact insertion into the current plan.

    The current future plan stays as one population member.  One standard
    regret-2 repair supplies a complete warm start, then each alternative first
    insertion is repaired through the same complete-model chain.  This reuses
    the already implemented repair neighbourhood; it adds no new scientific
    threshold or surrogate acceptance rule.
    """

    if requested_size < 1:
        raise ValueError("requested_size must be positive")

    started = perf_counter()
    full_calls_before = evaluator.full_calls
    initial_evaluation = evaluator.evaluate(initial)
    candidates = [initial]
    evaluations = [initial_evaluation]
    # Dynamic warm-start repair is a problem-specific candidate generator,
    # not the HGS survivor store. Keep exploring distinct repairs here; the
    # downstream DutyPopulation applies the copied HGS duplicate semantics.
    seen = {initial.fingerprint}
    attempts: list[DynamicWarmStartAttempt] = []

    def stopped() -> bool:
        return bool(stop_requested is not None and stop_requested())

    def has_complete_feasible() -> bool:
        return any(
            evaluation.feasible and not candidate.unserved_customers
            for candidate, evaluation in zip(
                candidates,
                evaluations,
                strict=True,
            )
        )

    def population_ready() -> bool:
        return len(candidates) >= requested_size and has_complete_feasible()

    def admit(
        action_id: str,
        candidate: DutyIndividual,
        evaluation: FullEvaluation,
        attempt_started: float,
    ) -> None:
        if candidate.unserved_customers:
            attempts.append(
                DynamicWarmStartAttempt(
                    action_id=action_id,
                    status="REPAIR_INCOMPLETE",
                    fingerprint=candidate.fingerprint,
                    feasible=evaluation.feasible,
                    violation_types=tuple(
                        violation.type for violation in evaluation.violations
                    ),
                    error="unserved customers remain: "
                    + ", ".join(candidate.unserved_customers),
                    wall_seconds=perf_counter() - attempt_started,
                )
            )
            return
        if candidate.fingerprint in seen:
            attempts.append(
                DynamicWarmStartAttempt(
                    action_id=action_id,
                    status="DUPLICATE_CANDIDATE",
                    fingerprint=candidate.fingerprint,
                    feasible=evaluation.feasible,
                    violation_types=tuple(
                        violation.type for violation in evaluation.violations
                    ),
                    wall_seconds=perf_counter() - attempt_started,
                )
            )
            return
        seen.add(candidate.fingerprint)
        candidates.append(candidate)
        evaluations.append(evaluation)
        attempts.append(
            DynamicWarmStartAttempt(
                action_id=action_id,
                status="ADMITTED",
                fingerprint=candidate.fingerprint,
                feasible=evaluation.feasible,
                violation_types=tuple(
                    violation.type for violation in evaluation.violations
                ),
                wall_seconds=perf_counter() - attempt_started,
            )
        )

    if initial.unserved_customers and not stopped():
        attempt_started = perf_counter()
        accounting = SearchAccounting()
        try:
            repaired, repaired_evaluation, _ = regret2_repair(
                initial,
                evaluator=evaluator,
                charging_policy=charging_policy,
                arm="dynamic-warm-start-regret2",
                iteration=0,
                accounting=accounting,
                penalized_cost=penalized_cost,
                initial_evaluation=initial_evaluation,
                trajectory_sink=lambda _rows: None,
                stop_requested=stop_requested,
            )
        except (AssertionError, RuntimeError, TypeError, ValueError) as exc:
            attempts.append(
                DynamicWarmStartAttempt(
                    action_id="regret2-baseline",
                    status="REJECTED",
                    fingerprint=None,
                    feasible=None,
                    violation_types=(),
                    error_type=type(exc).__name__,
                    error=str(exc),
                    wall_seconds=perf_counter() - attempt_started,
                )
            )
        else:
            admit(
                "regret2-baseline",
                repaired,
                repaired_evaluation,
                attempt_started,
            )

    moves = [
        move
        for customer_id in initial.unserved_customers
        for move in insertion_moves(initial, customer_id)
    ]
    for move in moves:
        if population_ready() or stopped():
            break
        attempt_started = perf_counter()
        outcome = evaluate_move(
            initial,
            move,
            evaluator=evaluator,
            charging_policy=charging_policy,
        )
        if (
            outcome.status != CandidateStatus.EVALUATED
            or outcome.candidate is None
            or outcome.evaluation is None
        ):
            attempts.append(
                DynamicWarmStartAttempt(
                    action_id=move.action_id,
                    status=outcome.status.value,
                    fingerprint=None,
                    feasible=None,
                    violation_types=(),
                    error_type=outcome.error_type,
                    error=outcome.error,
                    wall_seconds=perf_counter() - attempt_started,
                )
            )
            continue
        candidate = outcome.candidate
        evaluation = outcome.evaluation
        if candidate.unserved_customers and not stopped():
            accounting = SearchAccounting()
            try:
                candidate, evaluation, _ = regret2_repair(
                    candidate,
                    evaluator=evaluator,
                    charging_policy=charging_policy,
                    arm="dynamic-warm-start-alternative",
                    iteration=0,
                    accounting=accounting,
                    penalized_cost=penalized_cost,
                    initial_evaluation=evaluation,
                    trajectory_sink=lambda _rows: None,
                    stop_requested=stop_requested,
                )
            except (AssertionError, RuntimeError, TypeError, ValueError) as exc:
                attempts.append(
                    DynamicWarmStartAttempt(
                        action_id=move.action_id,
                        status="REJECTED",
                        fingerprint=None,
                        feasible=None,
                        violation_types=(),
                        error_type=type(exc).__name__,
                        error=str(exc),
                        wall_seconds=perf_counter() - attempt_started,
                    )
                )
                continue
        admit(move.action_id, candidate, evaluation, attempt_started)

    ejection_moves = [
        ExchangeUnservedMove(
            action_id=(
                f"eject-insert:{unserved}<->{served}@"
                f"{duty.physical_vehicle_id}#T{trip.trip_index}"
            ),
            channel="dynamic_ejection_repair",
            duty_id=duty.physical_vehicle_id,
            trip_index=trip.trip_index,
            served_customer_id=served,
            unserved_customer_id=unserved,
        )
        for unserved in initial.unserved_customers
        for duty in initial.duties
        for trip in duty.trips
        if trip.trip_index not in duty.locked_charging_trip_indices
        for served in trip.customer_ids[len(trip.locked_customer_prefix) :]
    ]
    for move in ejection_moves:
        if population_ready() or stopped():
            break
        attempt_started = perf_counter()
        outcome = evaluate_move(
            initial,
            move,
            evaluator=evaluator,
            charging_policy=charging_policy,
        )
        if (
            outcome.status != CandidateStatus.EVALUATED
            or outcome.candidate is None
            or outcome.evaluation is None
        ):
            attempts.append(
                DynamicWarmStartAttempt(
                    action_id=move.action_id,
                    status=outcome.status.value,
                    fingerprint=None,
                    feasible=None,
                    violation_types=(),
                    error_type=outcome.error_type,
                    error=outcome.error,
                    wall_seconds=perf_counter() - attempt_started,
                )
            )
            continue
        candidate = outcome.candidate
        evaluation = outcome.evaluation
        accounting = SearchAccounting()
        try:
            candidate, evaluation, _ = regret2_repair(
                candidate,
                evaluator=evaluator,
                charging_policy=charging_policy,
                arm="dynamic-warm-start-ejection",
                iteration=0,
                accounting=accounting,
                penalized_cost=penalized_cost,
                initial_evaluation=evaluation,
                trajectory_sink=lambda _rows: None,
                stop_requested=stop_requested,
            )
        except (AssertionError, RuntimeError, TypeError, ValueError) as exc:
            attempts.append(
                DynamicWarmStartAttempt(
                    action_id=move.action_id,
                    status="REJECTED",
                    fingerprint=None,
                    feasible=None,
                    violation_types=(),
                    error_type=type(exc).__name__,
                    error=str(exc),
                    wall_seconds=perf_counter() - attempt_started,
                )
            )
            continue
        admit(move.action_id, candidate, evaluation, attempt_started)

    if len(candidates) > requested_size:
        retained = list(zip(candidates, evaluations, strict=True))[:requested_size]
        if not any(
            evaluation.feasible and not candidate.unserved_customers
            for candidate, evaluation in retained
        ):
            first_feasible = next(
                (
                    (candidate, evaluation)
                    for candidate, evaluation in zip(
                        candidates[requested_size:],
                        evaluations[requested_size:],
                        strict=True,
                    )
                    if evaluation.feasible and not candidate.unserved_customers
                ),
                None,
            )
            if first_feasible is not None:
                retained[-1] = first_feasible
        candidates = [candidate for candidate, _ in retained]
        evaluations = [evaluation for _, evaluation in retained]

    return DynamicWarmStartResult(
        candidates=tuple(candidates),
        evaluations=tuple(evaluations),
        attempts=tuple(attempts),
        requested_size=int(requested_size),
        actual_size=len(candidates),
        attempts_exhausted=(not population_ready() and not stopped()),
        full_evaluation_count=evaluator.full_calls - full_calls_before,
        wall_seconds=perf_counter() - started,
    )


def build_initial_population(
    initial: DutyIndividual,
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    route_engine: IndependentKernelDutyRouteProposalEngine,
    requested_size: int,
    random_seed: int,
    max_random_attempts: int | None,
    require_complete_feasible: bool = False,
    stop_requested: Callable[[], bool] | None = None,
    fleet_activation_enabled: bool = True,
) -> InitialPopulationResult:
    """Keep the registered solution and add fully evaluated random skeletons.

    Dynamic disclosure may start from an incomplete future plan.  In that
    setting, filling the nominal population is not enough: at least one member
    must cover every revealed customer and pass the complete evaluator before
    HGS can start.  Candidate storage remains bounded by ``requested_size``;
    later trials only replace the last stored member when they provide the
    first complete feasible seed.
    """

    if requested_size < 1:
        raise ValueError("requested_size must be positive")
    if max_random_attempts is not None and max_random_attempts < 0:
        raise ValueError("max_random_attempts cannot be negative")
    if max_random_attempts is None and stop_requested is None:
        raise ValueError("unbounded population construction needs a stop callback")

    started = perf_counter()
    full_evaluation_count = 0
    full_evaluation_count += 1
    initial_evaluation = evaluator.evaluate(initial)
    candidates = [initial]
    evaluations = [initial_evaluation]
    attempts: list[InitialPopulationAttempt] = []
    offset = 0

    def stopped() -> bool:
        return bool(stop_requested is not None and stop_requested())

    def has_complete_feasible() -> bool:
        return any(
            evaluation.feasible and not candidate.unserved_customers
            for candidate, evaluation in zip(
                candidates,
                evaluations,
                strict=True,
            )
        )

    def population_ready() -> bool:
        return len(candidates) >= requested_size and (
            not require_complete_feasible or has_complete_feasible()
        )

    while not population_ready():
        if stopped():
            break
        if max_random_attempts is not None and offset >= max_random_attempts:
            break
        seed = int(random_seed) + offset
        offset += 1
        attempt_started = perf_counter()
        try:
            move = route_engine.random_skeleton_move(
                initial,
                random_seed=seed,
            )
            if move is None:
                if len(candidates) < requested_size:
                    candidates.append(initial)
                    evaluations.append(initial_evaluation)
                attempts.append(
                    InitialPopulationAttempt(
                        random_seed=seed,
                        status="ADMITTED_DUPLICATE_SKELETON",
                        fingerprint=initial.fingerprint,
                        feasible=initial_evaluation.feasible,
                        violation_types=tuple(
                            violation.type
                            for violation in initial_evaluation.violations
                        ),
                        wall_seconds=perf_counter() - attempt_started,
                    )
                )
                continue
            candidate = move.apply(initial)
            assert_fleet_activation_allowed(
                initial,
                candidate,
                enabled=fleet_activation_enabled,
            )
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
                    wall_seconds=perf_counter() - attempt_started,
                )
            )
            continue
        if len(candidates) < requested_size:
            candidates.append(candidate)
            evaluations.append(evaluation)
        elif (
            require_complete_feasible
            and not has_complete_feasible()
            and evaluation.feasible
            and not candidate.unserved_customers
        ):
            candidates[-1] = candidate
            evaluations[-1] = evaluation
        attempts.append(
            InitialPopulationAttempt(
                random_seed=seed,
                status="ADMITTED",
                fingerprint=candidate.fingerprint,
                feasible=evaluation.feasible,
                violation_types=tuple(
                    violation.type for violation in evaluation.violations
                ),
                wall_seconds=perf_counter() - attempt_started,
            )
        )

    return InitialPopulationResult(
        candidates=tuple(candidates),
        evaluations=tuple(evaluations),
        attempts=tuple(attempts),
        requested_size=int(requested_size),
        actual_size=len(candidates),
        attempts_exhausted=(not population_ready() and not stopped()),
        full_evaluation_count=full_evaluation_count,
        wall_seconds=perf_counter() - started,
    )
