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
from dataclasses import dataclass, field

from setp_hgs_kernel.ExternalPopulation import (
    EvaluatedSolution,
)
from setp_hgs_kernel.GeneticAlgorithm import GeneticAlgorithmParams
from setp_hgs_kernel.IntegratedGeneticAlgorithm import (
    IntegratedGeneticAlgorithm,
    IntegratedProblemAdapter,
)
from setp_hgs_kernel.solve import SolveParams
from setp_hgs_kernel._setp_hgs_kernel import (
    PopulationParams as KernelPopulationParams,
)

from .charging import (
    ChargingFeasibilityPrescreen,
    ChargingRepairPolicy,
    charging_rejection_reason,
    repair_changed_duties,
)
from .bi_objective_population import (
    SINGLE_OBJECTIVE,
    BiObjectiveArchive,
    BiObjectiveExternalPopulation,
    ObjectiveValues,
    make_private_population,
    validate_population_objective_mode,
)
from .contracts import (
    CandidateOutcome,
    CandidateStatus,
    SearchAccounting,
    TrajectoryRow,
)
from .crossover import (
    DutyCrossoverResult,
    trip_assignment_exchange_candidates,
)
from .education import _trajectory_row, educate_best_improvement
from .evaluation import DutyFullEvaluator, FullEvaluation
from .fleet_registry import assert_fleet_activation_allowed
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
    objective_mode: str
    charging_prescreen: ChargingFeasibilityPrescreen | None

    def bi_objective_archive(self) -> BiObjectiveArchive | None:
        if not isinstance(self.population, BiObjectiveExternalPopulation):
            return None
        return self.population.archive()


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
    objective_mode: str = SINGLE_OBJECTIVE,
    charging_prescreen_enabled: bool = False,
    charging_prescreen_audit_limit: int = 0,
    cross_depot_enabled: bool = True,
    multi_trip_enabled: bool = True,
    type_exchange_enabled: bool = True,
) -> IntegratedPrivateHGSBundle:
    """Build the shared HGS loop over complete private-problem candidates."""

    if not initial_candidates:
        raise ValueError("integrated private HGS requires initial candidates")
    if stagnation_patience < 1:
        raise ValueError("stagnation patience must be positive")
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

    objective_mode = validate_population_objective_mode(objective_mode)
    copied_parameters = SolveParams()
    complete_penalties = AdaptivePenaltyManager(penalty_parameters)
    accounting = PrivateIntegratedAccounting()
    charging_prescreen = (
        ChargingFeasibilityPrescreen(
            evaluator.context,
            charging_policy,
            audit_limit=int(charging_prescreen_audit_limit),
        )
        if charging_prescreen_enabled
        else None
    )
    schedule_coordinator = None
    if schedule_cross_repair_fallback or schedule_all_changed_move_evaluation:
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
    rng = _DutyRngAdapter(route_engine.rng)
    customer_coordinates = {
        node.node_id: (float(node.x), float(node.y))
        for node in evaluator.context.bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    customer_home_depot_by_id = (
        None
        if cross_depot_enabled
        else {
            customer: duty.home_depot_id
            for duty in template.duties
            for trip in duty.trips
            for customer in trip.customer_ids
        }
    )
    customer_vehicle_type_by_id = (
        None
        if type_exchange_enabled
        else {
            customer: duty.vehicle_type
            for duty in template.duties
            for trip in duty.trips
            for customer in trip.customer_ids
        }
    )
    if proposal_engine is None:
        mechanism_engine = MechanismProposalEngine(
            evaluator.context,
            charging_policy,
            include_charging_candidates=include_charging_candidates,
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
                enabled=fleet_activation_enabled,
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

        def reject(error: Exception) -> None:
            message = str(error).lower()
            status = (
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
                    charging_rejection_reason(error)
                    if status == CandidateStatus.REJECTED_CHARGING
                    else None
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
                multi_trip_enabled=multi_trip_enabled,
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
                assert_fleet_activation_allowed(
                    first.solution,
                    crossed.child,
                    enabled=fleet_activation_enabled,
                )
                completed = repair_changed_duties(
                    first.solution,
                    crossed.child,
                    changed_duty_ids=set(crossed.changed_duty_ids),
                    context=evaluator.context,
                    policy=charging_policy,
                )
            except (TypeError, ValueError) as error:
                rescued = None
                if schedule_cross_repair_fallback:
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
            if evaluated is None and schedule_cross_repair_fallback:
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
        if trajectory_sink is not None:
            emit(
                _trajectory_row(
                    iteration=accounting.crossover_calls,
                    phase="crossover",
                    arm=arm,
                    before=first.solution,
                    before_evaluation=first.evaluation.full,
                    outcome=constructed,
                    accepted=False,
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
                float(copied_parameters.penalty.repair_booster)
                * violation_cost
            )

        individual, full, _rows = educate_best_improvement(
            candidate.solution,
            evaluator=evaluator,
            charging_policy=charging_policy,
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
                include_whole_duty_type_exchange
            ),
            trajectory_sink=trajectory_sink,
            proposal_engine=engine,
            stop_requested=stop_requested,
            selection_policy="first",
            schedule_coordinator=(
                schedule_coordinator
                if schedule_all_changed_move_evaluation
                else None
            ),
            fleet_activation_enabled=fleet_activation_enabled,
            charging_prescreen=charging_prescreen,
            record_trajectory=trajectory_sink is not None,
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
            engine=route_stage_engine,
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
            engine=route_stage_engine,
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
        if mechanism_stage_engine is None or not candidate.evaluation.feasible:
            return candidate
        return _educate(
            candidate,
            repair=False,
            engine=mechanism_stage_engine,
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
    population = make_private_population(
        broken_pairs_distance,
        objective_mode=objective_mode,
        is_feasible=adapter.is_feasible,
        objectives=lambda evaluation: ObjectiveValues(
            total_cost=float(evaluation.full.total_cost),
            total_emissions_kg=float(evaluation.full.breakdown["E_total"]),
        ),
        penalised_cost=adapter.penalised_cost,
        fingerprint=adapter.fingerprint,
        params=kernel_population_parameters,
    )
    algorithm = IntegratedGeneticAlgorithm(
        route_engine.data,
        route_engine.penalty_manager,
        rng,
        population,
        route_engine.local_search,
        None,
        initial_candidates,
        adapter,
        GeneticAlgorithmParams(
            repair_probability=(
                copied_parameters.genetic.repair_probability
            ),
            num_iters_no_improvement=int(stagnation_patience),
        ),
    )
    return IntegratedPrivateHGSBundle(
        algorithm,
        accounting,
        population,
        objective_mode,
        charging_prescreen,
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
