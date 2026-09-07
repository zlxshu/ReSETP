"""The common HGS control loop over complete Duty individuals."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from setp_hgs_kernel.solve import SolveParams
from setp_hgs_kernel._setp_hgs_kernel import (
    PopulationParams as KernelPopulationParams,
)
from setp_hgs_kernel.crossover import ordered_crossover
from setp_hgs_kernel.crossover import selective_route_exchange

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
from .education import _trajectory_row, educate_best_improvement
from .evaluation import (
    DutyFullEvaluator,
    DutyIncrementalEvaluator,
    FullEvaluation,
    assert_candidate_routes_single_shift,
)
from .execution_settings import (
    ExecutionSettings,
    build_execution_settings,
)
from .fleet_registry import assert_fleet_activation_allowed
from .kernel_proposals import IndependentKernelDutyRouteProposalEngine
from .model import DutyIndividual, assert_locks_preserved
from .operators import DutySkeletonMove
from .population import (
    PopulationParameters,
    SelfAdaptivePenalty,
    broken_pairs_distance,
)
from .schedule_oracle import (
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
    complete_penalty_manager: SelfAdaptivePenalty
    effective_execution: ExecutionSettings

def build_integrated_private_hgs(
    initial_candidates: tuple[DutyIndividual, ...],
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    route_engine: IndependentKernelDutyRouteProposalEngine,
    include_mechanism_refinement: bool = True,
    include_whole_duty_type_exchange: bool = True,
    include_charging_candidates: bool = True,
    stop_requested: Callable[[], bool] | None = None,
    population_parameters: PopulationParameters | None = None,
    initial_evaluations: tuple[FullEvaluation, ...] | None = None,
    trajectory_sink: Callable[[tuple[TrajectoryRow, ...]], None] | None = None,
    arm: str = "integrated_private_hgs",
    schedule_all_changed_move_evaluation: bool = False,
    fleet_activation_enabled: bool = True,
    objective_mode: str = "single_objective",
    charging_prescreen_enabled: bool = False,
    cross_depot_enabled: bool = True,
    multi_trip_enabled: bool = True,
    type_exchange_enabled: bool = True,
    education_depth_limit: int | None = None,
    lazy_exact_evaluation: bool = False,
    allow_incomplete_initial: bool = False,
) -> IntegratedPrivateHGSBundle:
    """Build the shared HGS loop over complete private-problem candidates.

    ``allow_incomplete_initial`` (2026-09-03): the kernel-native search only
    borrows this bundle's exact machinery (penalty manager, education,
    charging cache) and seeds the kernel itself, so an idle reference (a
    written-down fleet the witness cannot seat) may stand in for complete
    initial candidates there.

    ``lazy_exact_evaluation`` (2026-09-03): a crossover child only goes through
    charging repair and the exact model when its kernel penalised cost is no
    worse than that of the worst member of the exact feasible subpopulation;
    a child above that line would be purged on admission anyway.  The line is
    read off the population, not set by hand.
    """

    if not initial_candidates:
        raise ValueError("integrated private HGS requires initial candidates")
    if len(initial_candidates) < SelfAdaptivePenalty.minimum_reference_size:
        raise ValueError("self-adaptive penalty requires four initial candidates")
    if education_depth_limit is not None and education_depth_limit < 1:
        raise ValueError("education depth limit must be positive")
    if not allow_incomplete_initial and any(
        candidate.unserved_customers for candidate in initial_candidates
    ):
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

    if objective_mode != "single_objective":
        raise ValueError("only single-objective population mode is supported")
    copied_parameters = SolveParams()
    complete_penalties = SelfAdaptivePenalty()
    accounting = PrivateIntegratedAccounting()
    mechanism_engine = MechanismProposalEngine(
        evaluator.context,
        charging_policy,
        include_charging_candidates=include_charging_candidates,
        # 2026-09-02: routing, multi-trip and cross-depot moves are the
        # kernel's job (reload depots, profiles, time warp).  The Python
        # relocate/swap/open-trip enumeration spent 596k exact evaluations for
        # 16% of the accepted improvement in e07; whole-duty type exchange and
        # whole-trip exchange, which the proxy cannot price, stay.
        include_structural_channels=False,
        cross_depot_enabled=cross_depot_enabled,
        multi_trip_enabled=multi_trip_enabled,
        type_exchange_enabled=type_exchange_enabled,
        stop_requested=stop_requested,
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
    if kernel_population_parameters.min_pop_size < SelfAdaptivePenalty.minimum_reference_size:
        raise ValueError("self-adaptive penalty requires min_pop_size >= 4")
    effective_execution = build_execution_settings(
        policy=charging_policy,
        route_engine=route_engine,
        route_stage_engine=route_stage_engine,
        mechanism_stage_engine=mechanism_stage_engine,
        repair_probability=copied_parameters.genetic.repair_probability,
        repair_booster=copied_parameters.penalty.repair_booster,
        num_iters_no_improvement=0,  # No-time HGS terminates without restart.
        include_whole_duty_type_exchange=include_whole_duty_type_exchange,
        include_charging_candidates=include_charging_candidates,
        schedule_all_changed_move_evaluation=(
            schedule_all_changed_move_evaluation
        ),
        fleet_activation_enabled=fleet_activation_enabled,
        charging_prescreen_enabled=charging_prescreen_enabled,
        education_depth_limit=education_depth_limit,
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
            ),
        )
        if effective_execution.charging_prescreen_enabled
        else None
    )
    schedule_coordinator = (
        ScheduleCoordinator(
            ScheduleOracleContext.from_evaluation_context(evaluator.context),
            result_sink=accounting.mechanism.record_schedule_oracle_result,
        )
        if effective_execution.schedule_all_changed_move_evaluation
        else None
    )
    education_cache: dict[
        tuple[bool, int, str, int],
        EvaluatedSolution[
            DutyIndividual,
            PrivateIntegratedEvaluation,
        ],
    ] = {}
    education_cache_revision = complete_penalties.revision
    rng = effective_execution.route_engine.rng
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

    child_incremental = DutyIncrementalEvaluator(evaluator)
    # Kernel projection of every exact member, by fingerprint (lazy gate).
    native_by_fingerprint: dict[str, object] = {}

    def lazy_line(engine) -> float | None:
        feasible = getattr(population, "_feasible", ())
        if len(feasible) < kernel_population_parameters.min_pop_size:
            return None
        cost_evaluator = engine.penalty_manager.cost_evaluator()
        worst = None
        for item in feasible:
            fingerprint = item.candidate.solution.fingerprint
            native = native_by_fingerprint.get(fingerprint)
            if native is None:
                native = engine.project(item.candidate.solution)
                native_by_fingerprint[fingerprint] = native
            value = float(cost_evaluator.penalised_cost(native))
            worst = value if worst is None else max(worst, value)
        return worst
    # Which duties the crossover touched, by child fingerprint; the mechanism
    # education only proposes moves on those duties (HGS "last modified"
    # rule), see educate_best_improvement.
    changed_by_child: dict[str, frozenset[str]] = {}

    def evaluate_child(
        parent: EvaluatedSolution[DutyIndividual, PrivateIntegratedEvaluation],
        completed: DutyIndividual,
        changed_duty_ids: frozenset[str],
    ) -> EvaluatedSolution[
        DutyIndividual,
        PrivateIntegratedEvaluation,
    ] | None:
        """Score a charging-complete child from its first parent's slices.

        2026-09-02 (D4): the child differs from ``parent`` only in
        ``changed_duty_ids``, so the per-vehicle slices of every other duty
        are reused; the complete path stays the fallback whenever the parent
        has no strict slices (admitted-infeasible member) or the incremental
        assembly refuses the candidate.
        """

        if evaluator.context.dynamic_state is None:
            try:
                assert_candidate_routes_single_shift(
                    completed,
                    evaluator.context.rebuilt_route_constraints,
                )
                if completed.unserved_customers:
                    raise ValueError("incomplete customer service")
                child_incremental.seed(parent.solution)
                full = child_incremental.evaluate_after_change(
                    parent.solution,
                    completed,
                    changed_duty_ids=set(changed_duty_ids),
                )
            except (TypeError, ValueError):
                full = None
            if full is not None:
                accounting.decoded_candidates += 1
                return EvaluatedSolution(
                    completed,
                    PrivateIntegratedEvaluation(completed, full),
                )
        return evaluate(completed)

    def repair_search_candidate(
        reference: DutyIndividual,
        raw_candidate: DutyIndividual,
        changed_duty_ids: frozenset[str],
    ) -> ChargingRepairOutcome:
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
        engine = effective_execution.route_engine
        cost_evaluator = engine.penalty_manager.cost_evaluator()
        native_parents = (
            engine.project(first.solution),
            engine.project(second.solution),
        )
        if engine.data.num_vehicles > 1:
            operator_name = "SREX"
            native_child = selective_route_exchange(
                native_parents,
                engine.data,
                cost_evaluator,
                engine.rng,
            )
        else:
            operator_name = "OX"
            native_child = ordered_crossover(
                native_parents,
                engine.data,
                cost_evaluator,
                engine.rng,
            )
        native_child = engine.local_search(native_child, cost_evaluator)
        # Upstream GeneticAlgorithm._improve_offspring registers every educated
        # child so the penalty manager keeps ~43% of children feasible; this
        # copy never did (2026-09-02), leaving the kernel penalties frozen at
        # their initial guess for the whole run.
        engine.penalty_manager.register(native_child)
        if (
            not native_child.is_feasible()
            and engine.rng.rand() < effective_execution.repair_probability
        ):
            native_child = engine.local_search(
                native_child,
                engine.penalty_manager.booster_cost_evaluator(),
            )
            if native_child.is_feasible():
                engine.penalty_manager.register(native_child)
        if lazy_exact_evaluation:
            line = lazy_line(engine)
            if line is not None and float(
                cost_evaluator.penalised_cost(native_child)
            ) > line:
                accounting.rejected_candidates += 1
                accounting.rejection_reasons[
                    "lazy: proxy cost above the exact feasible population"
                ] += 1
                accounting.mechanism.rejected_actions[
                    "route_kernel_crossover:LAZY_PROXY"
                ] += 1
                return None
        replacements = engine.decode_replacements(
            first.solution,
            native_child,
        )
        accounting.mechanism.record_crossover(operator_name, 1)
        action_id = (
            f"pyvrp-{operator_name.lower()}-{accounting.crossover_calls}"
        )
        channel = "route_kernel_crossover"

        def record(outcome: CandidateOutcome) -> None:
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

        if not replacements:
            accounting.crossover_noops += 1
            record(
                CandidateOutcome(
                    action_id=action_id,
                    channel=channel,
                    status=CandidateStatus.NO_CHANGE,
                    changed_duty_ids=frozenset(),
                    candidate=first.solution,
                    evaluation=first.evaluation.full,
                )
            )
            return first
        if not engine._mechanism_locks_preserved(first.solution, replacements):
            # A disabled mechanism (depot / vehicle-type / multi-trip lock) is
            # a hard contract of the arm, not a penalised constraint.
            accounting.rejected_candidates += 1
            accounting.rejection_reasons["crossover child breaks a mechanism lock"] += 1
            record(
                CandidateOutcome(
                    action_id=action_id,
                    channel=channel,
                    status=CandidateStatus.REJECTED_INTERFACE,
                    changed_duty_ids=frozenset(
                        duty_id for duty_id, _trips in replacements
                    ),
                    candidate=None,
                    error_type="MechanismLock",
                    error="crossover child breaks a disabled-mechanism lock",
                )
            )
            return None

        move = DutySkeletonMove(
            action_id=action_id,
            channel=channel,
            replacements=replacements,
            dynamic_future_only=evaluator.context.dynamic_state is not None,
        )
        raw_candidate = None
        try:
            raw_candidate = move.apply(first.solution)
            assert_locks_preserved(first.solution, raw_candidate)
            assert_candidate_routes_single_shift(
                raw_candidate,
                evaluator.context.rebuilt_route_constraints,
            )
            assert_fleet_activation_allowed(
                first.solution,
                raw_candidate,
                enabled=effective_execution.fleet_activation_enabled,
            )
        except (TypeError, ValueError) as error:
            accounting.rejected_candidates += 1
            accounting.rejection_reasons[
                f"{type(error).__name__}: {error}"
            ] += 1
            record(
                CandidateOutcome(
                    action_id=action_id,
                    channel=channel,
                    status=(
                        CandidateStatus.REJECTED_LOCK
                        if "lock" in str(error).lower()
                        else CandidateStatus.REJECTED_REGISTRY
                        if "fleet" in str(error).lower()
                        else CandidateStatus.REJECTED_INTERFACE
                    ),
                    changed_duty_ids=move.changed_duty_ids,
                    candidate=raw_candidate,
                    error_type=type(error).__name__,
                    error=str(error),
                )
            )
            return None

        if raw_candidate.unserved_customers:
            accounting.rejected_candidates += 1
            error = ValueError(
                "official crossover left incomplete customer service"
            )
            accounting.rejection_reasons[str(error)] += 1
            record(
                CandidateOutcome(
                    action_id=action_id,
                    channel=channel,
                    status=CandidateStatus.REPAIR_INCOMPLETE,
                    changed_duty_ids=move.changed_duty_ids,
                    candidate=raw_candidate,
                    error_type=type(error).__name__,
                    error=str(error),
                )
            )
            return None

        try:
            charging_outcome = repair_search_candidate(
                first.solution,
                raw_candidate,
                move.changed_duty_ids,
            )
        except (TypeError, ValueError) as error:
            accounting.rejected_candidates += 1
            accounting.rejection_reasons[
                f"{type(error).__name__}: {error}"
            ] += 1
            record(
                CandidateOutcome(
                    action_id=action_id,
                    channel=channel,
                    status=CandidateStatus.REJECTED_CHARGING,
                    changed_duty_ids=move.changed_duty_ids,
                    candidate=raw_candidate,
                    error_type=type(error).__name__,
                    error=str(error),
                    charging_rejection_reason=charging_rejection_reason(error),
                )
            )
            return None

        completed = charging_outcome.candidate
        if completed is None:
            error = charging_outcome.error or ValueError(
                charging_outcome.reason_code
                or charging_outcome.status.value
            )
            accounting.rejected_candidates += 1
            accounting.rejection_reasons[
                f"{type(error).__name__}: {error}"
            ] += 1
            record(
                CandidateOutcome(
                    action_id=action_id,
                    channel=channel,
                    status=(
                        CandidateStatus.REJECTED_INTERFACE
                        if charging_outcome.status
                        == ChargingCandidateStatus.REJECTED_INTERFACE
                        else CandidateStatus.REJECTED_CHARGING
                    ),
                    changed_duty_ids=move.changed_duty_ids,
                    candidate=raw_candidate,
                    error_type=type(error).__name__,
                    error=str(error),
                    charging_rejection_reason=charging_outcome.reason_code,
                    charging_candidate_status=charging_outcome.status,
                )
            )
            return None

        evaluated = evaluate_child(first, completed, move.changed_duty_ids)
        if evaluated is None:
            accounting.rejected_candidates += 1
            accounting.rejection_reasons[
                "official crossover full evaluation rejected candidate"
            ] += 1
            record(
                CandidateOutcome(
                    action_id=action_id,
                    channel=channel,
                    status=CandidateStatus.REJECTED_INTERFACE,
                    changed_duty_ids=move.changed_duty_ids,
                    candidate=completed,
                    error_type="FULL_EVALUATION_REJECTED",
                    error=(
                        "official crossover candidate did not reach "
                        "a complete evaluation"
                    ),
                )
            )
            return None

        record(
            CandidateOutcome(
                action_id=action_id,
                channel=channel,
                status=CandidateStatus.EVALUATED,
                changed_duty_ids=move.changed_duty_ids,
                candidate=evaluated.solution,
                evaluation=evaluated.evaluation.full,
            )
        )
        changed_by_child[evaluated.solution.fingerprint] = move.changed_duty_ids
        native_by_fingerprint[evaluated.solution.fingerprint] = native_child
        return evaluated

    def _educate(
        candidate: EvaluatedSolution[
            DutyIndividual,
            PrivateIntegratedEvaluation,
        ],
        *,
        repair: bool,
        engine: DutyProposalEngine,
        changed_duty_ids: frozenset[str] | None = None,
    ) -> EvaluatedSolution[
        DutyIndividual,
        PrivateIntegratedEvaluation,
    ]:
        nonlocal education_cache_revision
        if education_cache_revision != complete_penalties.revision:
            education_cache.clear()
            education_cache_revision = complete_penalties.revision
        cache_key = (
            bool(repair),
            id(engine),
            candidate.solution.fingerprint,
            complete_penalties.revision,
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
            changed_duty_ids=changed_duty_ids,
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
            changed_duty_ids=changed_by_child.pop(
                candidate.solution.fingerprint, None
            ),
        )

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
        if (
            effective_execution.mechanism_stage_engine is not None
            and repaired.evaluation.feasible
        ):
            repaired = _educate(
                repaired,
                repair=False,
                engine=effective_execution.mechanism_stage_engine,
            )
        return repaired

    adapter = IntegratedProblemAdapter(
        evaluate=evaluate,
        refine=refine,
        is_feasible=lambda evaluation: bool(evaluation.feasible),
        objective=lambda evaluation: float(evaluation.full.total_cost),
        penalised_cost=lambda evaluation: complete_penalties.cost(
            evaluation.full
        ),
        register=None,
        fingerprint=lambda individual: individual.fingerprint,
        minimum_initial_population_size=SelfAdaptivePenalty.minimum_reference_size,
        breed=breed,
        repair=repair,
    )
    population = ExternalPopulation(
        broken_pairs_distance,
        is_feasible=adapter.is_feasible,
        penalised_cost=adapter.penalised_cost,
        refresh_penalties=lambda evaluations: complete_penalties.update(
            tuple(evaluation.full for evaluation in evaluations)
        ),
        minimum_penalty_population_size=(
            SelfAdaptivePenalty.minimum_reference_size
        ),
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
