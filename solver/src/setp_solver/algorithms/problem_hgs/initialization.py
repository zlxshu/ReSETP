"""Problem-HGS initial-population construction.

IndependentKernel supplies only random route skeletons.  Physical-vehicle identity,
multi-trip reconstruction, charging, and complete feasibility remain in the
Duty layer.  The caller chooses the requested population size and attempt
budget; this module does not freeze either value.
"""

from __future__ import annotations

from random import SystemRandom
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import perf_counter

from .charging import (
    ChargingRepairPolicy,
    charging_rejection_reason,
    repair_changed_duties,
    repair_changed_duties_outcome,
)
from .evaluation import (
    DutyFullEvaluator,
    FullEvaluation,
    assert_candidate_routes_single_shift,
)
from .fleet_registry import assert_fleet_activation_allowed
from .model import DutyIndividual
from .kernel_proposals import IndependentKernelDutyRouteProposalEngine
from .contracts import (
    CandidateStatus,
    ChargingCandidateStatus,
    ChargingRepairOutcome,
    SearchAccounting,
)
from .education import evaluate_move
from .repair import insertion_moves, regret2_repair
from .operators import (
    ExchangeUnservedMove,
    RelocateMove,
    ReverseSegmentMove,
    WholeDutyTypeExchangeMove,
)


@dataclass(frozen=True)
class InitialPopulationAttempt:
    draw_index: int | None
    status: str
    fingerprint: str | None
    feasible: bool | None
    violation_types: tuple[str, ...]
    error_type: str | None = None
    error: str | None = None
    wall_seconds: float = 0.0
    source: str = "random"
    action_id: str | None = None
    contract_type: str | None = None


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
    # downstream ExternalPopulation applies the copied HGS duplicate semantics.
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


def generate_witness_perturbation_moves(
    witness: DutyIndividual,
    *,
    customer_shift_by_id: Mapping[str, str],
) -> tuple[object, ...]:
    """Generate only the approved witness-seed perturbation actions.

    The actions are existing duty operators.  This function only restricts
    their construction to the C0 witness path: within-trip reorder, same-shift
    cross-vehicle relocation, and whole-duty EV/CV task-chain exchange.  The
    common candidate contract remains in ``build_initial_population``.
    """

    def trip_shift(trip) -> str | None:
        shifts = {
            str(customer_shift_by_id[customer])
            for customer in trip.customer_ids
            if customer in customer_shift_by_id
        }
        return next(iter(shifts)) if len(shifts) == 1 else None

    trip_rows = [
        (duty, trip, trip_shift(trip))
        for duty in witness.duties
        for trip in duty.trips
    ]
    moves: list[object] = []
    for duty, trip, shift_id in trip_rows:
        if shift_id is None or trip.locked_customer_prefix:
            continue
        if trip.trip_index in duty.locked_charging_trip_indices:
            continue
        for start in range(len(trip.customer_ids) - 1):
            for stop in range(start + 2, len(trip.customer_ids) + 1):
                moves.append(
                    ReverseSegmentMove(
                        action_id=(
                            f"witness-reorder:{duty.physical_vehicle_id}"
                            f"#T{trip.trip_index}@{start}:{stop}"
                        ),
                        channel="witness_perturbation_reorder",
                        duty_id=duty.physical_vehicle_id,
                        trip_index=trip.trip_index,
                        start=start,
                        stop=stop,
                    )
                )

    for source_duty, source_trip, source_shift in trip_rows:
        if source_shift is None or source_trip.locked_customer_prefix:
            continue
        if source_trip.trip_index in source_duty.locked_charging_trip_indices:
            continue
        for target_duty, target_trip, target_shift in trip_rows:
            if source_duty.physical_vehicle_id == target_duty.physical_vehicle_id:
                continue
            if source_shift != target_shift or target_shift is None:
                continue
            if target_trip.locked_customer_prefix:
                continue
            if target_trip.trip_index in target_duty.locked_charging_trip_indices:
                continue
            for customer in source_trip.customer_ids:
                for position in range(
                    len(target_trip.locked_customer_prefix),
                    len(target_trip.customer_ids) + 1,
                ):
                    moves.append(
                        RelocateMove(
                            action_id=(
                                f"witness-relocate:{source_duty.physical_vehicle_id}"
                                f"#T{source_trip.trip_index}:{customer}->"
                                f"{target_duty.physical_vehicle_id}"
                                f"#T{target_trip.trip_index}@{position}"
                            ),
                            channel="witness_perturbation_relocate",
                            source_duty_id=source_duty.physical_vehicle_id,
                            source_trip_index=source_trip.trip_index,
                            customer_id=customer,
                            target_duty_id=target_duty.physical_vehicle_id,
                            target_trip_index=target_trip.trip_index,
                            target_position=position,
                        )
                    )

    for left_index, left in enumerate(witness.duties):
        for right in witness.duties[left_index + 1 :]:
            if left.home_depot_id != right.home_depot_id:
                continue
            if {left.vehicle_type, right.vehicle_type} != {"ev", "cv"}:
                continue
            if left.locked_charging_trip_indices or right.locked_charging_trip_indices:
                continue
            if any(
                trip.locked_customer_prefix
                for duty in (left, right)
                for trip in duty.trips
            ):
                continue
            left_chain = tuple(tuple(trip.customer_ids) for trip in left.trips)
            right_chain = tuple(tuple(trip.customer_ids) for trip in right.trips)
            if left_chain == right_chain:
                continue
            moves.append(
                WholeDutyTypeExchangeMove(
                    action_id=(
                        f"witness-type-flip:{left.physical_vehicle_id}<->"
                        f"{right.physical_vehicle_id}"
                    ),
                    channel="witness_perturbation_type_exchange",
                    left_duty_id=left.physical_vehicle_id,
                    right_duty_id=right.physical_vehicle_id,
                )
            )

    SystemRandom().shuffle(moves)
    return tuple(moves)


def _initialization_rejection_contract(error: Exception) -> str:
    """Name an existing rejection cause for per-candidate accounting only."""

    message = str(error).lower()
    if "initialization structure closure" in message:
        return "STRUCTURE_CLOSURE"
    if "no feasible depot charging window" in message:
        return "NO_FEASIBLE_DEPOT_CHARGING_WINDOW"
    if any(
        token in message
        for token in ("trip overlap", "turnaround", "charging overlap", "return")
    ):
        return "TRIP_OVERLAP_OR_RETURN_INTERVAL"
    if any(
        token in message
        for token in ("customer windows", "time window", "does not fit")
    ):
        return "CUSTOMER_TIME_WINDOW"
    if "departure" in message:
        return "NO_FEASIBLE_DEPARTURE"
    if any(token in message for token in ("single shift", "shift", "mixed shift")):
        return "SHIFT_HOMOGENEITY"
    if any(
        token in message
        for token in ("fleet", "physical vehicle", "registered", "activation")
    ):
        return "FLEET_IDENTITY"
    return charging_rejection_reason(error)


def _assert_initialization_structure_closure(
    initial: DutyIndividual,
    candidate: DutyIndividual,
    *,
    mechanism_enabled: Mapping[str, bool] | None,
) -> None:
    """Keep sleeping structural mechanisms closed during initialization."""

    if mechanism_enabled is None:
        return
    cross_depot_enabled = bool(mechanism_enabled.get("cross_depot", True))
    type_exchange_enabled = bool(mechanism_enabled.get("type_exchange", True))
    if cross_depot_enabled and type_exchange_enabled:
        return

    initial_structure = {
        customer: (duty.home_depot_id, duty.vehicle_type)
        for duty in initial.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    depot_changes: list[str] = []
    type_changes: list[str] = []
    for duty in candidate.duties:
        for trip in duty.trips:
            for customer in trip.customer_ids:
                original = initial_structure.get(customer)
                if original is None:
                    continue
                original_depot, original_type = original
                if not cross_depot_enabled and duty.home_depot_id != original_depot:
                    depot_changes.append(customer)
                if not type_exchange_enabled and duty.vehicle_type != original_type:
                    type_changes.append(customer)

    failures = []
    if depot_changes:
        failures.append("cross_depot:" + ",".join(sorted(set(depot_changes))))
    if type_changes:
        failures.append("type_exchange:" + ",".join(sorted(set(type_changes))))
    if failures:
        raise ValueError(
            "initialization structure closure failed: " + ";".join(failures)
        )


def build_initial_population(
    initial: DutyIndividual,
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    route_engine: IndependentKernelDutyRouteProposalEngine,
    requested_size: int,
    max_random_attempts: int | None,
    initialization_method: str = "random",
    include_reference_candidate: bool = True,
    require_complete_feasible: bool = False,
    stop_requested: Callable[[], bool] | None = None,
    fleet_activation_enabled: bool = True,
    witness_seed: DutyIndividual | None = None,
    mechanism_enabled: Mapping[str, bool] | None = None,
) -> InitialPopulationResult:
    """Build a population from an optional reference, then native constructors.

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
    if initialization_method not in {"random", "greedy_repair"}:
        raise ValueError("unsupported native initialization method")
    if max_random_attempts is None and stop_requested is None:
        raise ValueError("unbounded population construction needs a stop callback")

    if witness_seed is not None and not include_reference_candidate:
        raise ValueError("a witness seed must be included as a reference candidate")

    started = perf_counter()
    full_evaluation_count = 0
    assert_candidate_routes_single_shift(
        initial,
        getattr(evaluator.context, "rebuilt_route_constraints", None),
    )
    candidates: list[DutyIndividual] = []
    evaluations: list[FullEvaluation] = []
    initial_evaluation = None
    if include_reference_candidate:
        full_evaluation_count += 1
        initial_evaluation = evaluator.evaluate(initial)
        candidates.append(initial)
        evaluations.append(initial_evaluation)
    attempts: list[InitialPopulationAttempt] = []
    random_offset = 0
    perturbation_offset = 0

    if witness_seed is not None:
        assert initial_evaluation is not None
        attempts.append(
            InitialPopulationAttempt(
                draw_index=None,
                status="READY",
                fingerprint=initial.fingerprint,
                feasible=initial_evaluation.feasible,
                violation_types=tuple(
                    violation.type for violation in initial_evaluation.violations
                ),
                source="witness",
                action_id="witness-seed",
            )
        )
        contract = getattr(evaluator.context, "rebuilt_route_constraints", None)
        if contract is None:
            raise ValueError("witness perturbation needs the rebuilt shift contract")
        perturbation_moves = generate_witness_perturbation_moves(
            witness_seed,
            customer_shift_by_id=contract.customer_shift_by_id,
        )
    else:
        perturbation_moves = ()

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
        source = (
            "perturb"
            if perturbation_offset < len(perturbation_moves)
            else initialization_method
        )
        if source == "perturb":
            move = perturbation_moves[perturbation_offset]
            perturbation_offset += 1
            action_id = str(getattr(move, "action_id", "witness-perturbation"))
            reference = witness_seed or initial
        else:
            if max_random_attempts is not None and random_offset >= max_random_attempts:
                break
            draw_index = random_offset
            random_offset += 1
            action_id = None
            reference = initial
        if source == "perturb":
            draw_index = None
        attempt_started = perf_counter()
        candidate = None
        charging_outcome = None
        try:
            if source != "perturb":
                constructor = (
                    route_engine.greedy_repair_skeleton_move
                    if source == "greedy_repair"
                    else route_engine.random_skeleton_move
                )
                move = constructor(initial, draw_index=draw_index)
            if move is None:
                if not include_reference_candidate:
                    attempts.append(
                        InitialPopulationAttempt(
                            draw_index=draw_index,
                            status="REJECTED",
                            fingerprint=None,
                            feasible=None,
                            violation_types=(),
                            error=(
                                f"native {initialization_method} did not produce "
                                "a materializable Duty skeleton"
                            ),
                            wall_seconds=perf_counter() - attempt_started,
                            source=source,
                            action_id=action_id,
                            contract_type="NATIVE_SKELETON_MATERIALIZATION",
                        )
                    )
                    continue
                duplicate_evaluation = evaluator.evaluate(initial)
                full_evaluation_count += 1
                if len(candidates) < requested_size:
                    candidates.append(initial)
                    evaluations.append(duplicate_evaluation)
                attempts.append(
                    InitialPopulationAttempt(
                        draw_index=draw_index,
                        status="READY",
                        fingerprint=initial.fingerprint,
                        feasible=duplicate_evaluation.feasible,
                        violation_types=tuple(
                            violation.type
                            for violation in duplicate_evaluation.violations
                        ),
                        wall_seconds=perf_counter() - attempt_started,
                        source=source,
                        action_id=action_id,
                    )
                )
                continue
            candidate = move.apply(reference)
            _assert_initialization_structure_closure(
                initial,
                candidate,
                mechanism_enabled=mechanism_enabled,
            )
            assert_candidate_routes_single_shift(
                candidate,
                getattr(evaluator.context, "rebuilt_route_constraints", None),
            )
            assert_fleet_activation_allowed(
                initial,
                candidate,
                enabled=fleet_activation_enabled,
            )
            if (
                getattr(evaluator.context, "dynamic_state", None) is None
                and isinstance(charging_policy, ChargingRepairPolicy)
            ):
                charging_outcome = repair_changed_duties_outcome(
                    reference,
                    candidate,
                    changed_duty_ids=set(move.changed_duty_ids),
                    context=evaluator.context,
                    policy=charging_policy,
                )
            else:
                candidate = repair_changed_duties(
                    reference,
                    candidate,
                    changed_duty_ids=set(move.changed_duty_ids),
                    context=evaluator.context,
                    policy=charging_policy,
                )
                charging_outcome = ChargingRepairOutcome(
                    status=ChargingCandidateStatus.READY,
                    candidate=candidate,
                    affected_duty_ids=tuple(
                        sorted(move.changed_duty_ids)
                    ),
                )
            if charging_outcome.candidate is None:
                error = charging_outcome.error or ValueError(
                    charging_outcome.reason_code
                    or charging_outcome.status.value
                )
                attempts.append(
                    InitialPopulationAttempt(
                        draw_index=draw_index,
                        status=charging_outcome.status.value,
                        fingerprint=candidate.fingerprint,
                        feasible=None,
                        violation_types=(),
                        error_type=type(error).__name__,
                        error=str(error),
                        wall_seconds=perf_counter() - attempt_started,
                        source=source,
                        action_id=action_id,
                        contract_type="CHARGING_REPAIR",
                    )
                )
                continue
            candidate = charging_outcome.candidate
            full_evaluation_count += 1
            evaluation = evaluator.evaluate(candidate)
        except (AssertionError, RuntimeError, TypeError, ValueError) as exc:
            attempts.append(
                InitialPopulationAttempt(
                    draw_index=draw_index,
                    status="REJECTED",
                    fingerprint=(
                        None if candidate is None else candidate.fingerprint
                    ),
                    feasible=None,
                    violation_types=(),
                    error_type=type(exc).__name__,
                    error=str(exc),
                    wall_seconds=perf_counter() - attempt_started,
                    source=source,
                    action_id=action_id,
                    contract_type=_initialization_rejection_contract(exc),
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
                draw_index=draw_index,
                status=(
                    "READY"
                    if charging_outcome is None
                    else charging_outcome.status.value
                ),
                fingerprint=candidate.fingerprint,
                feasible=evaluation.feasible,
                violation_types=tuple(
                    violation.type for violation in evaluation.violations
                ),
                wall_seconds=perf_counter() - attempt_started,
                source=source,
                action_id=action_id,
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
