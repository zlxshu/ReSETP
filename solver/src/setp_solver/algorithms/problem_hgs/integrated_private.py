"""The common HGS control loop specialised to complete Duty individuals.

The private search never ranks a projected native route.  Crossover, charging
completion, local education, population survival, parent selection, and repair
all see the same complete-model cost and feasibility scale.  The copied native
route kernel remains one proposal provider inside Duty education; it is not a
second genetic algorithm or an alternative acceptance authority.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from setp_hgs_kernel.solve import SolveParams
from setp_hgs_kernel._setp_hgs_kernel import (
    PopulationParams as KernelPopulationParams,
)

from .external_population import EvaluatedSolution, ExternalPopulation
from .integrated_genetic_algorithm import (
    IntegratedGeneticAlgorithm,
    IntegratedProblemAdapter,
)
from .patched_genetic_algorithm import GeneticAlgorithmParams
from .charging import (
    ChargingFeasibilityPrescreen,
    ChargingRepairCache,
    ChargingRepairPolicy,
    charging_rejection_reason,
    repair_changed_duties,
    repair_changed_duties_outcome,
)
from .contracts import (
    CandidateOutcome,
    CandidateStatus,
    ChargingCandidateStatus,
    ChargingRepairOutcome,
    SearchAccounting,
    TrajectoryRow,
)
from .crossover import (
    DutyCrossoverResult,
    trip_assignment_exchange_candidates,
)
from .education import _trajectory_row, educate_best_improvement
from .evaluation import (
    DutyFullEvaluator,
    FullEvaluation,
    assert_candidate_routes_single_shift,
)
from .execution_identity import (
    EffectiveExecutionBundle,
    build_effective_execution_bundle,
)
from .fleet_registry import assert_fleet_activation_allowed
from .hybrid_decoder import (
    HybridDecodeGap,
    HybridDecodeStatus,
    HybridDecoderSpec,
    HybridGapKind,
    customer_home_depot_hints,
    customer_physical_slot_hints,
    decode_customer_order,
    route_layer_order_from_parents,
)
from .kernel_proposals import IndependentKernelDutyRouteProposalEngine
from .model import DutyIndividual
from .population import (
    AdaptivePenaltyManager,
    PenaltyParameters,
    PopulationParameters,
    broken_pairs_distance,
)
from .schedule_capture import emit_schedule_capture
from .schedule_oracle import (
    OracleStatus,
    ScheduleCoordinator,
    ScheduleOracleContext,
)
from .proposals import (
    DEFAULT_SERIAL_PROPOSAL_SOURCE_ID,
    DutyProposalEngine,
    MechanismProposalEngine,
    SequentialProposalEngine,
)


@dataclass(frozen=True)
class PrivateIntegratedEvaluation:
    """Exact evaluation paired with the complete candidate that produced it."""

    individual: DutyIndividual
    full: FullEvaluation

    def __post_init__(self) -> None:
        if self.full.individual_fingerprint != self.individual.fingerprint:
            raise ValueError("private evaluation belongs to another individual")

    @property
    def feasible(self) -> bool:
        return self.full.feasible


@dataclass
class PrivateIntegratedAccounting:
    decoded_candidates: int = 0
    rejected_candidates: int = 0
    crossover_calls: int = 0
    crossover_noops: int = 0
    mechanism_calls: int = 0
    mechanism_improvements: int = 0
    repair_calls: int = 0
    repair_improvements: int = 0
    rejection_reasons: Counter[str] = field(default_factory=Counter)
    mechanism: SearchAccounting = field(default_factory=SearchAccounting)


@dataclass(frozen=True)
class IntegratedPrivateHGSBundle:
    algorithm: IntegratedGeneticAlgorithm[
        DutyIndividual,
        PrivateIntegratedEvaluation,
    ]
    accounting: PrivateIntegratedAccounting
    population: object
    charging_prescreen: ChargingFeasibilityPrescreen | None
    charging_repair_cache: ChargingRepairCache
    complete_penalty_manager: AdaptivePenaltyManager
    effective_execution: EffectiveExecutionBundle

class _DutyRngAdapter:
    """Expose the copied kernel RNG through the tiny API Duty crossover needs."""

    def __init__(self, kernel_rng) -> None:
        self._kernel_rng = kernel_rng

    def randint(self, high: int) -> int:
        return int(self._kernel_rng.randint(int(high)))

    def randrange(self, stop: int) -> int:
        return self.randint(stop)

    def rand(self) -> float:
        return float(self._kernel_rng.rand())


def build_integrated_private_hgs(
    initial_candidates: tuple[DutyIndividual, ...],
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    route_engine: IndependentKernelDutyRouteProposalEngine,
    penalty_parameters: PenaltyParameters,
    stagnation_patience: int,
    include_mechanism_refinement: bool = True,
    include_whole_duty_type_exchange: bool = True,
    include_charging_candidates: bool = True,
    stop_requested: Callable[[], bool] | None = None,
    population_parameters: PopulationParameters | None = None,
    proposal_engine: DutyProposalEngine | None = None,
    initial_evaluations: tuple[FullEvaluation, ...] | None = None,
    trajectory_sink: Callable[[tuple[TrajectoryRow, ...]], None] | None = None,
    arm: str = "integrated_private_hgs",
    schedule_cross_repair_fallback: bool = False,
    schedule_all_changed_move_evaluation: bool = False,
    fleet_activation_enabled: bool = True,
    objective_mode: str = "single_objective",
    charging_prescreen_enabled: bool = False,
    charging_prescreen_audit_limit: int = 0,
    cross_depot_enabled: bool = True,
    multi_trip_enabled: bool = True,
    type_exchange_enabled: bool = True,
    route_layer_crossover_enabled: bool = False,
    education_depth_limit: int | None = None,
) -> IntegratedPrivateHGSBundle:
    """Build the shared HGS loop over complete private-problem candidates."""

    if not initial_candidates:
        raise ValueError("integrated private HGS requires initial candidates")
    if stagnation_patience < 1:
        raise ValueError("stagnation patience must be positive")
    if education_depth_limit is not None and education_depth_limit < 1:
        raise ValueError("education depth limit must be positive")
    if any(candidate.unserved_customers for candidate in initial_candidates):
        raise ValueError(
            "integrated private HGS requires complete initial candidates"
        )
    template = initial_candidates[0]
    if any(
        _fleet_identity(candidate) != _fleet_identity(template)
        for candidate in initial_candidates
    ):
        raise ValueError("initial candidates use different physical fleets")
    if initial_evaluations is not None:
        if len(initial_evaluations) != len(initial_candidates):
            raise ValueError(
                "initial evaluations must match initial candidates"
            )
        for candidate, full in zip(
            initial_candidates,
            initial_evaluations,
            strict=True,
        ):
            if full.individual_fingerprint != candidate.fingerprint:
                raise ValueError(
                    "an initial evaluation belongs to another candidate"
                )
            if full.evaluation_context_sha256 != evaluator.context_sha256:
                raise ValueError(
                    "an initial evaluation belongs to another context"
                )

    if objective_mode != "single_objective":
        raise ValueError("only single-objective population mode is supported")
    copied_parameters = SolveParams()
    complete_penalties = AdaptivePenaltyManager(penalty_parameters)
    accounting = PrivateIntegratedAccounting()
    search_charging_policy = (
        charging_policy
        if (
            getattr(evaluator.context, "dynamic_state", None) is not None
            or charging_policy.charging_gap_enabled
        )
        else replace(charging_policy, charging_gap_enabled=True)
    )
    if proposal_engine is None:
        mechanism_engine = MechanismProposalEngine(
            evaluator.context,
            search_charging_policy,
            include_charging_candidates=include_charging_candidates,
            cross_depot_enabled=cross_depot_enabled,
            multi_trip_enabled=multi_trip_enabled,
            type_exchange_enabled=type_exchange_enabled,
        )
        route_stage_engine: DutyProposalEngine = SequentialProposalEngine(
            providers=(route_engine,),
            source_id=f"{DEFAULT_SERIAL_PROPOSAL_SOURCE_ID}:route",
        )
        mechanism_stage_engine: DutyProposalEngine | None = (
            SequentialProposalEngine(
                providers=(mechanism_engine,),
                source_id=f"{DEFAULT_SERIAL_PROPOSAL_SOURCE_ID}:mechanism",
            )
            if include_mechanism_refinement
            else None
        )
    else:
        route_stage_engine = proposal_engine
        mechanism_stage_engine = None
    kernel_population_parameters = (
        copied_parameters.population
        if population_parameters is None
        else KernelPopulationParams(
            min_pop_size=population_parameters.min_pop_size,
            generation_size=population_parameters.generation_size,
            num_elite=population_parameters.num_elite,
            num_close=population_parameters.num_close,
            lb_diversity=population_parameters.lb_diversity,
            ub_diversity=population_parameters.ub_diversity,
        )
    )
    effective_execution = build_effective_execution_bundle(
        policy=search_charging_policy,
        route_engine=route_engine,
        route_stage_engine=route_stage_engine,
        mechanism_stage_engine=mechanism_stage_engine,
        context=evaluator.context,
        population_parameters=kernel_population_parameters,
        penalty_parameters=penalty_parameters,
        repair_probability=copied_parameters.genetic.repair_probability,
        repair_booster=copied_parameters.penalty.repair_booster,
        num_iters_no_improvement=stagnation_patience,
        live_switches={
            "include_mechanism_refinement": bool(include_mechanism_refinement),
            "include_whole_duty_type_exchange": bool(
                include_whole_duty_type_exchange
            ),
            "include_charging_candidates": bool(include_charging_candidates),
            "schedule_cross_repair_fallback": bool(
                schedule_cross_repair_fallback
            ),
            "schedule_all_changed_move_evaluation": bool(
                schedule_all_changed_move_evaluation
            ),
            "fleet_activation_enabled": bool(fleet_activation_enabled),
            "objective_mode": str(objective_mode),
            "charging_prescreen_enabled": bool(charging_prescreen_enabled),
            "charging_prescreen_audit_limit": int(
                charging_prescreen_audit_limit
            ),
            "cross_depot_enabled": bool(cross_depot_enabled),
            "multi_trip_enabled": bool(multi_trip_enabled),
            "type_exchange_enabled": bool(type_exchange_enabled),
            "route_layer_crossover_enabled": bool(
                route_layer_crossover_enabled
            ),
            "education_depth_limit": education_depth_limit,
        },
    )
    charging_repair_cache = ChargingRepairCache(
        evaluator.context,
        effective_execution.effective_charging_policy,
    )
    charging_prescreen = (
        ChargingFeasibilityPrescreen(
            evaluator.context,
            replace(
                effective_execution.effective_charging_policy,
                frvcpy_enabled=False,
                charging_gap_enabled=False,
            ),
            audit_limit=effective_execution.charging_prescreen_audit_limit,
        )
        if effective_execution.charging_prescreen_enabled
        else None
    )
    schedule_coordinator = None
    if (
        effective_execution.schedule_cross_repair_fallback
        or effective_execution.schedule_all_changed_move_evaluation
    ):
        schedule_coordinator = ScheduleCoordinator(
            ScheduleOracleContext.from_evaluation_context(evaluator.context),
            result_sink=accounting.mechanism.record_schedule_oracle_result,
        )
    education_cache: dict[
        tuple[bool, str, str, tuple[tuple[str, float], ...]],
        EvaluatedSolution[
            DutyIndividual,
            PrivateIntegratedEvaluation,
        ],
    ] = {}
    rng = _DutyRngAdapter(effective_execution.route_engine.rng)
    customer_coordinates = {
        node.node_id: (float(node.x), float(node.y))
        for node in evaluator.context.bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    customer_home_depot_by_id = (
        None
        if effective_execution.cross_depot_enabled
        else {
            customer: duty.home_depot_id
            for duty in template.duties
            for trip in duty.trips
            for customer in trip.customer_ids
        }
    )
    customer_vehicle_type_by_id = (
        None
        if effective_execution.type_exchange_enabled
        else {
            customer: duty.vehicle_type
            for duty in template.duties
            for trip in duty.trips
            for customer in trip.customer_ids
        }
    )
    route_layer_spec = None
    if effective_execution.route_layer_crossover_enabled:
        route_contract = getattr(
            evaluator.context,
            "rebuilt_route_constraints",
            None,
        )
        route_layer_spec = HybridDecoderSpec(
            bundle=evaluator.context.bundle,
            instance=evaluator.context.bundle.instance,
            prices=evaluator.context.bundle.prices,
            fleet_caps_by_depot=evaluator.context.bundle.fleet_caps_by_depot,
            customer_home_depot_by_id=evaluator.context.bundle.customer_home_depot,
            customer_shift_by_id=(
                {}
                if route_contract is None
                else route_contract.customer_shift_by_id
            ),
            customer_volume_m3_by_id=(
                {}
                if route_contract is None
                else route_contract.customer_volume_m3_by_id
            ),
            shift_window_second_by_id=(
                {}
                if route_contract is None
                else route_contract.shift_window_second_by_id
            ),
            vehicle_volume_capacity_m3=(
                float("inf")
                if route_contract is None
                else float(route_contract.vehicle_volume_capacity_m3)
            ),
        )
    initial_evaluation_by_fingerprint = dict(
        ()
        if initial_evaluations is None
        else (
            (candidate.fingerprint, full)
            for candidate, full in zip(
                initial_candidates,
                initial_evaluations,
                strict=True,
            )
        )
    )

    def emit(row: TrajectoryRow) -> None:
        if trajectory_sink is not None:
            trajectory_sink((row,))

    def evaluate(
        individual: DutyIndividual,
    ) -> EvaluatedSolution[
        DutyIndividual,
        PrivateIntegratedEvaluation,
    ] | None:
        try:
            assert_candidate_routes_single_shift(
                individual,
                getattr(
                    evaluator.context,
                    "rebuilt_route_constraints",
                    None,
                ),
            )
        except ValueError as error:
            accounting.rejected_candidates += 1
            accounting.rejection_reasons[
                f"{type(error).__name__}: {error}"
            ] += 1
            return None
        if individual.unserved_customers:
            accounting.rejected_candidates += 1
            accounting.rejection_reasons["incomplete customer service"] += 1
            return None
        full = initial_evaluation_by_fingerprint.get(individual.fingerprint)
        if full is None:
            try:
                full = evaluator.evaluate(individual)
            except (TypeError, ValueError) as error:
                accounting.rejected_candidates += 1
                reason = f"{type(error).__name__}: {error}"
                accounting.rejection_reasons[reason] += 1
                return None
        accounting.decoded_candidates += 1
        return EvaluatedSolution(
            individual,
            PrivateIntegratedEvaluation(individual, full),
        )

    def coordinate_candidate(
        reference: DutyIndividual,
        raw_candidate: DutyIndividual,
        changed_duty_ids: frozenset[str],
        *,
        channel: str,
    ) -> EvaluatedSolution[
        DutyIndividual,
        PrivateIntegratedEvaluation,
    ] | None:
        if schedule_coordinator is None:
            return None
        try:
            assert_fleet_activation_allowed(
                reference,
                raw_candidate,
                enabled=effective_execution.fleet_activation_enabled,
            )
        except ValueError:
            return None
        coordinated = schedule_coordinator.coordinate(
            reference,
            raw_candidate,
            changed_duty_ids=changed_duty_ids,
        )
        accounting.mechanism.record_schedule_coordinator_result(
            coordinated,
            changed_duty_count=len(changed_duty_ids),
        )
        if coordinated.status != OracleStatus.FEASIBLE:
            accounting.mechanism.schedule_rejected_candidates_by_channel_and_status[
                f"{channel}:{coordinated.status.value}"
            ] += 1
            return None
        evaluated = tuple(
            item
            for scheduled in coordinated.frontier
            if (item := evaluate(scheduled)) is not None
        )
        if not evaluated:
            accounting.mechanism.schedule_rejected_candidates_by_channel_and_status[
                f"{channel}:FULL_EVALUATION_REJECTED"
            ] += 1
            return None
        return min(
            evaluated,
            key=lambda item: (
                float(complete_penalties.cost(item.evaluation.full)),
                item.solution.fingerprint,
            ),
        )

    def repair_search_candidate(
        reference: DutyIndividual,
        raw_candidate: DutyIndividual,
        changed_duty_ids: frozenset[str],
    ) -> ChargingRepairOutcome:
        """Use P81 gap retention only where its static semantics are defined."""

        if getattr(evaluator.context, "dynamic_state", None) is None:
            return repair_changed_duties_outcome(
                reference,
                raw_candidate,
                changed_duty_ids=set(changed_duty_ids),
                context=evaluator.context,
                policy=effective_execution.effective_charging_policy,
                cache=charging_repair_cache,
            )
        completed = repair_changed_duties(
            reference,
            raw_candidate,
            changed_duty_ids=set(changed_duty_ids),
            context=evaluator.context,
            policy=effective_execution.effective_charging_policy,
            cache=charging_repair_cache,
        )
        return ChargingRepairOutcome(
            status=ChargingCandidateStatus.READY,
            candidate=completed,
            affected_duty_ids=tuple(sorted(changed_duty_ids)),
        )

    def breed(
        parents: tuple[
            EvaluatedSolution[
                DutyIndividual,
                PrivateIntegratedEvaluation,
            ],
            EvaluatedSolution[
                DutyIndividual,
                PrivateIntegratedEvaluation,
            ],
        ],
    ) -> EvaluatedSolution[
        DutyIndividual,
        PrivateIntegratedEvaluation,
    ] | None:
        accounting.crossover_calls += 1
        accounting.mechanism.crossover_calls += 1
        first, second = parents

        if effective_execution.route_layer_crossover_enabled:
            route_action_id = f"route-layer-ox-{accounting.crossover_calls}"

            def record_route_layer_outcome(
                outcome: CandidateOutcome,
                *,
                accepted: bool = False,
            ) -> None:
                accounting.mechanism.record_outcome(outcome)
                if trajectory_sink is not None:
                    emit(
                        _trajectory_row(
                            iteration=accounting.crossover_calls,
                            phase="crossover",
                            arm=arm,
                            before=first.solution,
                            before_evaluation=first.evaluation.full,
                            outcome=outcome,
                            accepted=accepted,
                        )
                    )

            try:
                assert route_layer_spec is not None
                customer_order_child, type_hints = route_layer_order_from_parents(
                    first.solution,
                    second.solution,
                    rng,
                )
                depot_hints = customer_home_depot_hints(first.solution)
                physical_slot_hints = customer_physical_slot_hints(first.solution)
                child_spec = replace(
                    route_layer_spec,
                    customer_home_depot_by_id=depot_hints,
                )
                decoded = decode_customer_order(
                    customer_order_child,
                    spec=child_spec,
                    vehicle_type_hints=type_hints,
                    physical_slot_hints=physical_slot_hints,
                    source="hybrid_route_layer_split",
                )
                accounting.mechanism.record_route_layer_decode(decoded)
            except (TypeError, ValueError) as error:
                accounting.rejected_candidates += 1
                accounting.rejection_reasons[
                    f"{type(error).__name__}: {error}"
                ] += 1
                record_route_layer_outcome(
                    CandidateOutcome(
                        action_id=route_action_id,
                        channel="route_layer_crossover",
                        status=CandidateStatus.REJECTED_INTERFACE,
                        changed_duty_ids=frozenset(),
                        error_type=type(error).__name__,
                        error=str(error),
                    )
                )
                accounting.crossover_noops += 1
                return first

            structural_gaps = tuple(
                gap
                for gap in decoded.gaps
                if gap.kind
                in {HybridGapKind.FLEET_SLOT, HybridGapKind.INTERFACE}
            )
            if decoded.candidate is None or structural_gaps:
                gap_text = "; ".join(
                    f"{getattr(gap.kind, 'value', gap.kind)}: {gap.detail}"
                    for gap in decoded.gaps
                )
                gap_kind = (
                    structural_gaps[0].kind
                    if structural_gaps
                    else HybridGapKind.INTERFACE
                )
                status = (
                    CandidateStatus.REJECTED_REGISTRY
                    if gap_kind == HybridGapKind.FLEET_SLOT
                    else CandidateStatus.REJECTED_INTERFACE
                )
                accounting.rejected_candidates += 1
                accounting.rejection_reasons[
                    f"route-layer decode: {gap_text or decoded.status.value}"
                ] += 1
                record_route_layer_outcome(
                    CandidateOutcome(
                        action_id=route_action_id,
                        channel="route_layer_crossover",
                        status=status,
                        changed_duty_ids=decoded.changed_duty_ids,
                        candidate=decoded.candidate,
                        error_type="HybridDecodeGap",
                        error=gap_text or decoded.status.value,
                        wall_seconds=decoded.wall_seconds,
                    )
                )
                accounting.crossover_noops += 1
                return first

            raw_candidate = decoded.candidate
            assert raw_candidate is not None
            changed_duty_ids = frozenset(
                duty.physical_vehicle_id
                for duty in (*first.solution.duties, *raw_candidate.duties)
                if duty.trips or duty.locked_charging_trip_indices
            )
            try:
                assert_candidate_routes_single_shift(
                    raw_candidate,
                    getattr(
                        evaluator.context,
                        "rebuilt_route_constraints",
                        None,
                    ),
                )
                assert_fleet_activation_allowed(
                    first.solution,
                    raw_candidate,
                    enabled=effective_execution.fleet_activation_enabled,
                )
                charging_outcome = repair_search_candidate(
                    first.solution,
                    raw_candidate,
                    changed_duty_ids,
                )
            except (TypeError, ValueError) as error:
                message = str(error).lower()
                status = (
                    CandidateStatus.REJECTED_CHARGING
                    if any(
                        token in message
                        for token in ("charg", "battery", "energy", "soc")
                    )
                    else CandidateStatus.REJECTED_INTERFACE
                )
                accounting.rejected_candidates += 1
                accounting.rejection_reasons[
                    f"{type(error).__name__}: {error}"
                ] += 1
                record_route_layer_outcome(
                    CandidateOutcome(
                        action_id=route_action_id,
                        channel="route_layer_crossover",
                        status=status,
                        changed_duty_ids=changed_duty_ids,
                        candidate=raw_candidate,
                        error_type=type(error).__name__,
                        error=str(error),
                        charging_rejection_reason=(
                            charging_rejection_reason(error)
                            if status == CandidateStatus.REJECTED_CHARGING
                            else None
                        ),
                        wall_seconds=decoded.wall_seconds,
                    )
                )
                accounting.crossover_noops += 1
                return first

            if charging_outcome.candidate is None:
                error = charging_outcome.error or ValueError(
                    charging_outcome.reason_code
                    or charging_outcome.status.value
                )
                status = (
                    CandidateStatus.REJECTED_INTERFACE
                    if charging_outcome.status
                    == ChargingCandidateStatus.REJECTED_INTERFACE
                    else CandidateStatus.REJECTED_CHARGING
                )
                accounting.rejected_candidates += 1
                accounting.rejection_reasons[
                    f"{type(error).__name__}: {error}"
                ] += 1
                record_route_layer_outcome(
                    CandidateOutcome(
                        action_id=route_action_id,
                        channel="route_layer_crossover",
                        status=status,
                        changed_duty_ids=changed_duty_ids,
                        error_type=type(error).__name__,
                        error=str(error),
                        charging_rejection_reason=(
                            charging_outcome.reason_code
                        ),
                        wall_seconds=decoded.wall_seconds,
                        charging_candidate_status=(
                            charging_outcome.status
                        ),
                        charging_gap=charging_outcome.gap,
                        charging_clock_witnesses=(
                            charging_outcome.clock_witnesses
                        ),
                    )
                )
                accounting.crossover_noops += 1
                return first
            completed = charging_outcome.candidate

            evaluated = evaluate(completed)
            if evaluated is None:
                accounting.rejected_candidates += 1
                accounting.rejection_reasons[
                    "route-layer full evaluation rejected candidate"
                ] += 1
                record_route_layer_outcome(
                    CandidateOutcome(
                        action_id=route_action_id,
                        channel="route_layer_crossover",
                        status=CandidateStatus.REJECTED_INTERFACE,
                        changed_duty_ids=changed_duty_ids,
                        candidate=completed,
                        error_type="FULL_EVALUATION_REJECTED",
                        error="route-layer candidate did not reach a complete evaluation",
                        wall_seconds=decoded.wall_seconds,
                    )
                )
                accounting.crossover_noops += 1
                return first

            accounting.mechanism.record_route_layer_evaluation()
            accounting.mechanism.record_crossover("ROUTE_LAYER_OX", 1)
            constructed = CandidateOutcome(
                action_id=route_action_id,
                channel="route_layer_crossover",
                status=CandidateStatus.EVALUATED,
                changed_duty_ids=changed_duty_ids,
                candidate=evaluated.solution,
                evaluation=evaluated.evaluation.full,
                wall_seconds=decoded.wall_seconds,
            )
            before_penalized = float(
                complete_penalties.cost(first.evaluation.full)
            )
            after_penalized = float(
                complete_penalties.cost(evaluated.evaluation.full)
            )
            accepted = bool(
                evaluated.evaluation.full.feasible
                and after_penalized < before_penalized - 1.0e-9
            )
            if accepted:
                accounting.mechanism.record_route_layer_acceptance()
                accounting.mechanism.record_acceptance(
                    "route_layer_crossover"
                )
                accounting.mechanism.record_accepted_effect(
                    "route_layer_crossover",
                    first.solution,
                    first.evaluation.full,
                    evaluated.solution,
                    evaluated.evaluation.full,
                )
            record_route_layer_outcome(constructed, accepted=accepted)
            return evaluated

        def reject(
            error: Exception,
            *,
            forced_status: CandidateStatus | None = None,
            charging_outcome: ChargingRepairOutcome | None = None,
        ) -> None:
            message = str(error).lower()
            status = forced_status or (
                CandidateStatus.REJECTED_CHARGING
                if any(
                    token in message
                    for token in ("charg", "battery", "energy", "soc")
                )
                else CandidateStatus.REJECTED_LOCK
                if "lock" in message
                else CandidateStatus.REJECTED_REGISTRY
                if "fleet" in message or "registry" in message
                else CandidateStatus.REJECTED_INTERFACE
            )
            outcome = CandidateOutcome(
                action_id="trip-assignment",
                channel="duty_crossover",
                status=status,
                changed_duty_ids=frozenset(),
                error_type=type(error).__name__,
                error=str(error),
                charging_rejection_reason=(
                    charging_outcome.reason_code
                    if charging_outcome is not None
                    else charging_rejection_reason(error)
                    if status == CandidateStatus.REJECTED_CHARGING
                    else None
                ),
                charging_candidate_status=(
                    None
                    if charging_outcome is None
                    else charging_outcome.status
                ),
                charging_gap=(
                    None
                    if charging_outcome is None
                    else charging_outcome.gap
                ),
                charging_clock_witnesses=(
                    ()
                    if charging_outcome is None
                    else charging_outcome.clock_witnesses
                ),
            )
            accounting.mechanism.record_outcome(outcome)
            if trajectory_sink is not None:
                emit(
                    _trajectory_row(
                        iteration=accounting.crossover_calls,
                        phase="crossover",
                        arm=arm,
                        before=first.solution,
                        before_evaluation=first.evaluation.full,
                        outcome=outcome,
                        accepted=False,
                    )
                )

        try:
            crossed_candidates = trip_assignment_exchange_candidates(
                (first.solution, second.solution),
                rng,
                customer_coordinates,
                customer_home_depot_by_id=customer_home_depot_by_id,
                customer_vehicle_type_by_id=customer_vehicle_type_by_id,
                multi_trip_enabled=effective_execution.multi_trip_enabled,
            )
        except ValueError as error:
            if str(error) != "trip assignment found no compatible movable trip":
                accounting.rejected_candidates += 1
                accounting.rejection_reasons[
                    f"{type(error).__name__}: {error}"
                ] += 1
                reject(error)
                return None
            # A one-parent or lock-saturated population can still be educated.
            # Keeping the exact evaluated parent avoids inventing a route proxy.
            accounting.crossover_noops += 1
            unavailable = CandidateOutcome(
                action_id="trip-assignment-unavailable",
                channel="duty_crossover",
                status=CandidateStatus.NO_CHANGE,
                changed_duty_ids=frozenset(),
                candidate=first.solution,
                evaluation=first.evaluation.full,
                error=str(error),
            )
            accounting.mechanism.record_outcome(unavailable)
            if trajectory_sink is not None:
                emit(
                    _trajectory_row(
                        iteration=accounting.crossover_calls,
                        phase="crossover",
                        arm=arm,
                        before=first.solution,
                        before_evaluation=first.evaluation.full,
                        outcome=unavailable,
                        accepted=False,
                    )
                )
            return first
        viable: list[
            tuple[
                float,
                str,
                DutyCrossoverResult,
                EvaluatedSolution[
                    DutyIndividual,
                    PrivateIntegratedEvaluation,
                ],
            ]
        ] = []
        for crossed in crossed_candidates:
            if crossed.unserved_customers:
                accounting.rejected_candidates += 1
                error = ValueError(
                    "crossover produced incomplete customer service"
                )
                accounting.rejection_reasons[str(error)] += 1
                reject(error)
                continue
            try:
                assert_candidate_routes_single_shift(
                    crossed.child,
                    getattr(
                        evaluator.context,
                        "rebuilt_route_constraints",
                        None,
                    ),
                )
                assert_fleet_activation_allowed(
                    first.solution,
                    crossed.child,
                    enabled=effective_execution.fleet_activation_enabled,
                )
                charging_outcome = repair_search_candidate(
                    first.solution,
                    crossed.child,
                    crossed.changed_duty_ids,
                )
            except (TypeError, ValueError) as error:
                rescued = None
                if effective_execution.schedule_cross_repair_fallback:
                    rescued = coordinate_candidate(
                        first.solution,
                        crossed.child,
                        crossed.changed_duty_ids,
                        channel="duty_crossover",
                    )
                if rescued is not None:
                    accounting.mechanism.schedule_rescued_candidates_by_channel[
                        "duty_crossover"
                    ] += 1
                    viable.append(
                        (
                            float(
                                complete_penalties.cost(
                                    rescued.evaluation.full
                                )
                            ),
                            rescued.solution.fingerprint,
                            crossed,
                            rescued,
                        )
                    )
                    continue
                accounting.rejected_candidates += 1
                accounting.rejection_reasons[
                    f"{type(error).__name__}: {error}"
                ] += 1
                if any(
                    token in str(error).lower()
                    for token in ("charg", "battery", "energy", "soc")
                ):
                    emit_schedule_capture(
                        channel="duty_crossover",
                        action_id="trip-assignment",
                        iteration=accounting.crossover_calls,
                        reference=first.solution,
                        raw_candidate=crossed.child,
                        changed_duty_ids=frozenset(
                            crossed.changed_duty_ids
                        ),
                        context=evaluator.context,
                        a0_status="INFEASIBLE",
                        error=error,
                    )
                reject(error)
                continue
            if charging_outcome.candidate is None:
                error = charging_outcome.error or ValueError(
                    charging_outcome.reason_code
                    or charging_outcome.status.value
                )
                rescued = None
                if effective_execution.schedule_cross_repair_fallback:
                    rescued = coordinate_candidate(
                        first.solution,
                        crossed.child,
                        crossed.changed_duty_ids,
                        channel="duty_crossover",
                    )
                if rescued is not None:
                    accounting.mechanism.schedule_rescued_candidates_by_channel[
                        "duty_crossover"
                    ] += 1
                    viable.append(
                        (
                            float(
                                complete_penalties.cost(
                                    rescued.evaluation.full
                                )
                            ),
                            rescued.solution.fingerprint,
                            crossed,
                            rescued,
                        )
                    )
                    continue
                accounting.rejected_candidates += 1
                accounting.rejection_reasons[
                    f"{type(error).__name__}: {error}"
                ] += 1
                reject(
                    error,
                    forced_status=(
                        CandidateStatus.REJECTED_INTERFACE
                        if charging_outcome.status
                        == ChargingCandidateStatus.REJECTED_INTERFACE
                        else CandidateStatus.REJECTED_CHARGING
                    ),
                    charging_outcome=charging_outcome,
                )
                continue
            completed = charging_outcome.candidate
            emit_schedule_capture(
                channel="crossover",
                action_id="trip-assignment",
                iteration=accounting.crossover_calls,
                reference=first.solution,
                raw_candidate=crossed.child,
                changed_duty_ids=frozenset(crossed.changed_duty_ids),
                context=evaluator.context,
                a0_status="FEASIBLE",
                error=None,
            )
            evaluated = evaluate(completed)
            if (
                evaluated is None
                and effective_execution.schedule_cross_repair_fallback
            ):
                evaluated = coordinate_candidate(
                    first.solution,
                    crossed.child,
                    crossed.changed_duty_ids,
                    channel="duty_crossover",
                )
                if evaluated is not None:
                    accounting.mechanism.schedule_rescued_candidates_by_channel[
                        "duty_crossover"
                    ] += 1
            if evaluated is None:
                continue
            viable.append(
                (
                    float(complete_penalties.cost(evaluated.evaluation.full)),
                    evaluated.solution.fingerprint,
                    crossed,
                    evaluated,
                )
            )
        if not viable:
            accounting.crossover_noops += 1
            return first
        _cost, _fingerprint, crossed, evaluated = min(
            viable,
            key=lambda item: (item[0], item[1]),
        )
        before_penalized = float(
            complete_penalties.cost(first.evaluation.full)
        )
        after_penalized = float(
            complete_penalties.cost(evaluated.evaluation.full)
        )
        accepted = bool(
            evaluated.evaluation.full.feasible
            and after_penalized < before_penalized - 1.0e-9
        )
        accounting.mechanism.record_crossover(
            "TRIP_ASSIGNMENT",
            sum(
                candidate.deterministic_work_units
                for candidate in crossed_candidates
            ),
        )
        constructed = CandidateOutcome(
            action_id="trip-assignment",
            channel="duty_crossover",
            status=CandidateStatus.EVALUATED,
            changed_duty_ids=crossed.changed_duty_ids,
            candidate=evaluated.solution,
            evaluation=evaluated.evaluation.full,
        )
        accounting.mechanism.record_outcome(constructed)
        if accepted:
            accounting.mechanism.record_acceptance("duty_crossover")
            accounting.mechanism.record_accepted_effect(
                "duty_crossover",
                first.solution,
                first.evaluation.full,
                evaluated.solution,
                evaluated.evaluation.full,
            )
        if trajectory_sink is not None:
            emit(
                _trajectory_row(
                    iteration=accounting.crossover_calls,
                    phase="crossover",
                    arm=arm,
                    before=first.solution,
                    before_evaluation=first.evaluation.full,
                    outcome=constructed,
                    accepted=accepted,
                )
            )
        return evaluated

    def _educate(
        candidate: EvaluatedSolution[
            DutyIndividual,
            PrivateIntegratedEvaluation,
        ],
        *,
        repair: bool,
        engine: DutyProposalEngine,
    ) -> EvaluatedSolution[
        DutyIndividual,
        PrivateIntegratedEvaluation,
    ]:
        cache_key = (
            bool(repair),
            engine.identity_sha256,
            candidate.solution.fingerprint,
            tuple(sorted(complete_penalties.penalties.items())),
        )
        cached = education_cache.get(cache_key)
        if cached is not None:
            accounting.mechanism.education_cache_hits += 1
            return cached
        accounting.mechanism.education_cache_misses += 1
        accounting.mechanism_calls += 1
        if repair:
            accounting.repair_calls += 1

        def search_cost(full: FullEvaluation) -> float:
            ordinary = float(complete_penalties.cost(full))
            if not repair:
                return ordinary
            violation_cost = ordinary - float(full.total_cost)
            return float(full.total_cost) + (
                float(effective_execution.repair_booster)
                * violation_cost
            )

        individual, full, _rows = educate_best_improvement(
            candidate.solution,
            evaluator=evaluator,
            charging_policy=effective_execution.effective_charging_policy,
            arm=(
                f"{arm}_repair"
                if repair
                else arm
            ),
            iteration=accounting.mechanism_calls,
            accounting=accounting.mechanism,
            penalized_cost=search_cost,
            initial_evaluation=candidate.evaluation.full,
            include_whole_duty_type_exchange=(
                effective_execution.include_whole_duty_type_exchange
            ),
            trajectory_sink=trajectory_sink,
            proposal_engine=engine,
            stop_requested=stop_requested,
            selection_policy="first",
            schedule_coordinator=(
                schedule_coordinator
                if effective_execution.schedule_all_changed_move_evaluation
                else None
            ),
            fleet_activation_enabled=effective_execution.fleet_activation_enabled,
            charging_prescreen=charging_prescreen,
            charging_repair_cache=charging_repair_cache,
            record_trajectory=trajectory_sink is not None,
            max_education_rounds=effective_execution.education_depth_limit,
        )
        if individual.fingerprint == candidate.solution.fingerprint:
            result = candidate
        else:
            accounting.mechanism_improvements += 1
            if repair:
                accounting.repair_improvements += 1
            result = EvaluatedSolution(
                individual,
                PrivateIntegratedEvaluation(individual, full),
            )
        if stop_requested is None or not stop_requested():
            education_cache[cache_key] = result
        return result

    def refine(
        candidate: EvaluatedSolution[
            DutyIndividual,
            PrivateIntegratedEvaluation,
        ],
    ) -> tuple[
        EvaluatedSolution[
            DutyIndividual,
            PrivateIntegratedEvaluation,
        ],
        ...,
    ]:
        refined = _educate(
            candidate,
            repair=False,
            engine=effective_execution.route_stage_engine,
        )
        if refined.solution.fingerprint == candidate.solution.fingerprint:
            return (candidate,)
        return (refined,)

    def repair(
        candidate: EvaluatedSolution[
            DutyIndividual,
            PrivateIntegratedEvaluation,
        ],
    ) -> EvaluatedSolution[
        DutyIndividual,
        PrivateIntegratedEvaluation,
    ]:
        repaired = _educate(
            candidate,
            repair=True,
            engine=effective_execution.route_stage_engine,
        )
        return repaired

    def finalise(
        candidate: EvaluatedSolution[
            DutyIndividual,
            PrivateIntegratedEvaluation,
        ],
    ) -> EvaluatedSolution[
        DutyIndividual,
        PrivateIntegratedEvaluation,
    ]:
        if (
            effective_execution.mechanism_stage_engine is None
            or not candidate.evaluation.feasible
        ):
            return candidate
        return _educate(
            candidate,
            repair=False,
            engine=effective_execution.mechanism_stage_engine,
        )

    def register(evaluation: PrivateIntegratedEvaluation) -> None:
        complete_penalties.register(evaluation.full)

    adapter = IntegratedProblemAdapter(
        evaluate=evaluate,
        refine=refine,
        is_feasible=lambda evaluation: evaluation.feasible,
        objective=lambda evaluation: float(evaluation.full.total_cost),
        penalised_cost=lambda evaluation: complete_penalties.cost(
            evaluation.full
        ),
        register=register,
        fingerprint=lambda individual: individual.fingerprint,
        breed=breed,
        repair=repair,
        finalise=finalise,
    )
    population = ExternalPopulation(
        broken_pairs_distance,
        is_feasible=adapter.is_feasible,
        penalised_cost=adapter.penalised_cost,
        fingerprint=adapter.fingerprint,
        params=kernel_population_parameters,
    )
    algorithm = IntegratedGeneticAlgorithm(
        effective_execution.route_engine.data,
        effective_execution.route_engine.penalty_manager,
        rng,
        population,
        effective_execution.route_engine.local_search,
        None,
        initial_candidates,
        adapter,
        GeneticAlgorithmParams(
            repair_probability=(
                effective_execution.repair_probability
            ),
            num_iters_no_improvement=(
                effective_execution.num_iters_no_improvement
            ),
        ),
    )
    return IntegratedPrivateHGSBundle(
        algorithm=algorithm,
        accounting=accounting,
        population=population,
        charging_prescreen=charging_prescreen,
        charging_repair_cache=charging_repair_cache,
        complete_penalty_manager=complete_penalties,
        effective_execution=effective_execution,
    )


def _fleet_identity(individual: DutyIndividual) -> tuple[
    tuple[str, str, str],
    ...,
]:
    return tuple(
        (
            duty.physical_vehicle_id,
            duty.vehicle_type,
            duty.home_depot_id,
        )
        for duty in individual.duties
    )
