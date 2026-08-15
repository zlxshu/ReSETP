"""Runnable isolated Problem-HGS search.

v1 2026-08-07: join the independently implemented HGS population/control
backbone with the prototype duty exchange, regret repair, charging-safe best-improvement
education, complete truth sentinels, and transparent trajectory accounting.
The caller supplies every numerical parameter and the stopping policy.

v2 2026-08-07: reuse the repair phase's verified evaluation when education
starts, so the same child is not fully evaluated twice without disclosure.

v3 2026-08-07: carry the whole-duty EV/CV exchange switch in the hashed run
configuration and pass it unchanged into education for paired ablation.

v4 2026-08-08: record and use the system proposal-engine identity so a strong
route kernel and the problem-mechanism channels cannot be silently confused.

v5 2026-08-08: replace the prototype random duty block with complete
multi-parent DCREX and its five learned insertion actions.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Callable
from dataclasses import asdict, dataclass
from time import perf_counter

from setp_hgs_kernel.HGSControl import HGSControl, HGSControlState

from .bi_objective_population import (
    SINGLE_OBJECTIVE,
    BiObjectiveArchive,
    validate_population_objective_mode,
)
from .charging import ChargingRepairPolicy, repair_changed_duties
from .contracts import (
    CandidateOutcome,
    CandidateStatus,
    SearchAccounting,
    TrajectoryRow,
)
from .crossover import (
    dcrex_duty_exchange,
    trip_assignment_exchange,
)
from .crossover_control import (
    CrossoverAction,
    RuntimeAwareCrossoverController,
)
from .dcrex import DISCOUNT_FACTOR, DCREXController, percentage_reward
from .education import (
    DutySentinelMismatch,
    _trajectory_row,
    educate_best_improvement,
)
from .evaluation import DutyFullEvaluator, FullEvaluation
from .integrated_private import build_integrated_private_hgs
from .kernel_proposals import IndependentKernelDutyRouteProposalEngine
from .model import DutyIndividual
from .population import (
    AdaptivePenaltyManager,
    DutyPopulation,
    EvaluatedDutyCandidate,
    PenaltyParameters,
    PopulationParameters,
)
from .proposals import (
    DEFAULT_SERIAL_PROPOSAL_SOURCE_ID,
    DutyProposalEngine,
    LegacyCompleteProposalEngine,
    MechanismProposalEngine,
    SequentialProposalEngine,
    proposal_elite_route,
    proposal_final_stages,
    proposal_post_mechanism_route,
    proposal_stages,
)
from .repair import dcrex_repair


@dataclass(frozen=True)
class ProblemHGSSearchParameters:
    random_seed: int
    population: PopulationParameters
    penalties: PenaltyParameters
    stagnation_patience: int = 500
    crossover_mode: str = "fast_only"
    include_whole_duty_type_exchange: bool = True
    dcrex_discount_factor: float = DISCOUNT_FACTOR
    objective_mode: str = SINGLE_OBJECTIVE

    def __post_init__(self) -> None:
        if self.stagnation_patience < 1:
            raise ValueError("stagnation patience must be positive")
        if self.crossover_mode not in {"fast_only", "hybrid"}:
            raise ValueError("crossover mode must be fast_only or hybrid")
        if not 0.0 < float(self.dcrex_discount_factor) <= 1.0:
            raise ValueError("DCREX discount factor must be in (0, 1]")
        validate_population_objective_mode(self.objective_mode)


@dataclass(frozen=True)
class PrivateAblationTreatment:
    """The only component switches allowed to differ inside one paired run."""

    schedule_cross_repair_fallback: bool = False
    schedule_all_changed_move_evaluation: bool = False
    fleet_activation_enabled: bool = False

    def __post_init__(self) -> None:
        if (
            self.schedule_all_changed_move_evaluation
            and not self.schedule_cross_repair_fallback
        ):
            raise ValueError("all-move DSS requires crossover DSS fallback")
        if self.fleet_activation_enabled and not (
            self.schedule_all_changed_move_evaluation
        ):
            raise ValueError("endogenous fleet treatment requires all-move DSS")


@dataclass(frozen=True)
class FrozenPopulationIdentity:
    """Reproducible identity of the supplied initial population."""

    source_id: str
    value_sha256: str

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("initial population source_id cannot be empty")
        if len(self.value_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.value_sha256.lower()
        ):
            raise ValueError(
                "initial population value_sha256 must be a SHA-256 hex digest"
            )


@dataclass(frozen=True)
class ProblemHGSSearchState:
    iterations: int
    iterations_without_improvement: int
    best_cost: float | None
    elapsed_seconds: float
    full_evaluations: int
    incremental_evaluations: int
    sentinel_evaluations: int
    actual_full_model_evaluations: int
    duty_slice_preparations: int
    candidate_assemblies: int


@dataclass(frozen=True)
class BiObjectiveSolutionRecord:
    """One saved Pareto point with its complete evaluation and certificate."""

    individual: DutyIndividual
    evaluation: FullEvaluation
    total_cost: float
    total_emissions_kg: float

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready point, including the full solution certificate."""

        return {
            "individual_fingerprint": self.individual.fingerprint,
            "objectives": {
                "Z1_total_cost": float(self.total_cost),
                "Z2_total_emissions_kg": float(self.total_emissions_kg),
                "E_cv_direct": float(
                    self.evaluation.breakdown["E_cv_direct"]
                ),
                "E_ev_indirect": float(
                    self.evaluation.breakdown["E_ev_indirect"]
                ),
            },
            "individual": asdict(self.individual),
            "prepared_solution": asdict(self.evaluation.prepared_solution),
            "solution_certificate": self.evaluation.certificate.as_dict(),
            "evaluation": {
                "total_cost": float(self.evaluation.total_cost),
                "breakdown": dict(self.evaluation.breakdown),
                "feasible": bool(self.evaluation.feasible),
                "violations": [
                    asdict(violation)
                    for violation in self.evaluation.violations
                ],
                "violation_magnitudes": [
                    float(value)
                    for value in self.evaluation.violation_magnitudes
                ],
                "depot_profit": dict(self.evaluation.depot_profit),
                "participation_margin": dict(
                    self.evaluation.participation_margin
                ),
                "evaluation_context_sha256": (
                    self.evaluation.evaluation_context_sha256
                ),
                "source": self.evaluation.source,
                "accounting": dict(self.evaluation.accounting),
            },
        }


@dataclass(frozen=True)
class ProblemHGSRunResult:
    best: DutyIndividual
    best_evaluation: FullEvaluation
    iterations: int
    accounting: SearchAccounting
    trajectory: tuple[TrajectoryRow, ...]
    provenance: ProblemHGSRunProvenance
    termination_status: str
    termination_error_type: str | None = None
    termination_error: str | None = None
    objective_mode: str = SINGLE_OBJECTIVE
    non_dominated_set: tuple[BiObjectiveSolutionRecord, ...] = ()
    cost_priority_point: BiObjectiveSolutionRecord | None = None
    emissions_priority_point: BiObjectiveSolutionRecord | None = None
    charging_prescreen_accounting: dict[str, object] | None = None


@dataclass(frozen=True)
class ProblemHGSRunProvenance:
    """Inputs that identify one run without claiming a scientific result."""

    arm: str
    instance_id: str
    random_seed: int
    search_configuration_sha256: str
    initial_population_source_id: str
    initial_population_sha256: str
    independent_profit_source_id: str
    independent_profit_sha256: str
    independent_profit_externally_frozen: bool
    fairness_enabled: bool
    fairness_theta: float
    incremental_full_truth_sentinel_enabled: bool
    trajectory_sink_enabled: bool
    trajectory_retained_in_memory: bool
    proposal_engine_source_id: str
    proposal_engine_sha256: str


class _TrajectoryRecorder:
    """Optionally stream trajectory batches without retaining the full run."""

    def __init__(
        self,
        sink: Callable[[tuple[TrajectoryRow, ...]], None] | None,
        *,
        retain: bool,
    ) -> None:
        self._sink = sink
        self._retain = bool(retain)
        self.retained: list[TrajectoryRow] = []

    def emit(self, row: TrajectoryRow) -> None:
        self.emit_many((row,))

    def emit_many(self, rows) -> None:
        batch = tuple(rows)
        if not batch:
            return
        if self._sink is not None:
            self._sink(batch)
        if self._retain:
            self.retained.extend(batch)


def run_integrated_problem_hgs(
    initial_candidates: tuple[DutyIndividual, ...],
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    parameters: ProblemHGSSearchParameters,
    initial_population_identity: FrozenPopulationIdentity,
    stop: Callable[[ProblemHGSSearchState], bool],
    arm: str,
    route_engine: IndependentKernelDutyRouteProposalEngine,
    trajectory_sink: Callable[[tuple[TrajectoryRow, ...]], None] | None = None,
    retain_trajectory: bool = True,
    proposal_engine: DutyProposalEngine | None = None,
    initial_evaluations: tuple[FullEvaluation, ...] | None = None,
    initialization_full_evaluation_count: int | None = None,
    initialization_wall_seconds: float = 0.0,
    treatment: PrivateAblationTreatment | None = None,
    charging_prescreen_enabled: bool = False,
    charging_prescreen_audit_limit: int = 0,
    cross_depot_enabled: bool = True,
    multi_trip_enabled: bool = True,
    type_exchange_enabled: bool = True,
) -> ProblemHGSRunResult:
    """Run the common HGS control flow over complete Duty candidates."""

    started = perf_counter()
    if not initial_candidates:
        raise ValueError("Problem-HGS requires at least one initial candidate")
    if any(candidate.unserved_customers for candidate in initial_candidates):
        raise ValueError(
            "integrated Problem-HGS cannot seed incomplete customer service"
        )
    if float(initialization_wall_seconds) < 0.0:
        raise ValueError("initialization wall time cannot be negative")
    if initial_population_identity.value_sha256.lower() != population_sha256(
        initial_candidates
    ):
        raise ValueError(
            "initial candidates disagree with their frozen population identity"
        )
    if initial_evaluations is None:
        initial_evaluations = tuple(
            evaluator.evaluate(candidate) for candidate in initial_candidates
        )
        initialization_full_evaluation_count = len(initial_evaluations)
    elif initialization_full_evaluation_count is None:
        initialization_full_evaluation_count = len(initial_evaluations)
    if initialization_full_evaluation_count < len(initial_evaluations):
        raise ValueError(
            "initialization evaluation count cannot be below retained evaluations"
        )

    active_proposal_engine = proposal_engine or SequentialProposalEngine(
        (route_engine, MechanismProposalEngine(evaluator.context, charging_policy)),
        source_id=DEFAULT_SERIAL_PROPOSAL_SOURCE_ID,
    )
    trajectory_enabled = trajectory_sink is not None or retain_trajectory
    trajectory = _TrajectoryRecorder(
        trajectory_sink,
        retain=retain_trajectory,
    )
    provenance = ProblemHGSRunProvenance(
        arm=str(arm),
        instance_id=str(evaluator.context.bundle.instance_id),
        random_seed=int(parameters.random_seed),
        search_configuration_sha256=search_configuration_sha256(
            parameters,
            charging_policy,
            arm=arm,
            proposal_engine=active_proposal_engine,
            treatment=treatment,
        ),
        initial_population_source_id=initial_population_identity.source_id,
        initial_population_sha256=(
            initial_population_identity.value_sha256.lower()
        ),
        independent_profit_source_id=(
            evaluator.context.independent_profit_identity.source_id
        ),
        independent_profit_sha256=(
            evaluator.context.independent_profit_identity.value_sha256.lower()
        ),
        independent_profit_externally_frozen=(
            evaluator.context.independent_profit_identity.externally_frozen
        ),
        fairness_enabled=bool(evaluator.context.fairness_enabled),
        fairness_theta=float(evaluator.context.theta),
        incremental_full_truth_sentinel_enabled=(
            evaluator.context.incremental_full_truth_sentinel_enabled
        ),
        trajectory_sink_enabled=trajectory_sink is not None,
        trajectory_retained_in_memory=retain_trajectory,
        proposal_engine_source_id=active_proposal_engine.source_id,
        proposal_engine_sha256=active_proposal_engine.identity_sha256,
    )
    full_calls_before = evaluator.full_calls
    sentinel_calls_before = evaluator.sentinel_calls
    iterations = 0
    no_improvement = 1
    previous_best: float | None = None
    accounting: SearchAccounting | None = None

    def current_state() -> ProblemHGSSearchState:
        live = accounting or SearchAccounting()
        full_evaluations = int(initialization_full_evaluation_count) + (
            evaluator.full_calls - full_calls_before
        )
        sentinel_evaluations = evaluator.sentinel_calls - sentinel_calls_before
        return ProblemHGSSearchState(
            iterations=iterations,
            iterations_without_improvement=no_improvement,
            best_cost=previous_best,
            elapsed_seconds=(
                float(initialization_wall_seconds) + perf_counter() - started
            ),
            full_evaluations=full_evaluations,
            incremental_evaluations=live.incremental_evaluations,
            sentinel_evaluations=sentinel_evaluations,
            actual_full_model_evaluations=(
                full_evaluations + sentinel_evaluations
            ),
            duty_slice_preparations=live.duty_slice_preparations,
            candidate_assemblies=live.candidate_assemblies,
        )

    class _IntegratedStop:
        def __init__(self) -> None:
            self._iteration_was_started = False

        def __call__(self, best_cost: float) -> bool:
            nonlocal iterations, no_improvement, previous_best
            if self._iteration_was_started:
                iterations += 1
            current = float(best_cost)
            if previous_best is not None:
                no_improvement = (
                    1 if current < previous_best else no_improvement + 1
                )
            previous_best = current
            if stop(current_state()):
                return True
            self._iteration_was_started = True
            return False

    bundle = build_integrated_private_hgs(
        initial_candidates,
        evaluator=evaluator,
        charging_policy=charging_policy,
        route_engine=route_engine,
        penalty_parameters=parameters.penalties,
        stagnation_patience=parameters.stagnation_patience,
        include_whole_duty_type_exchange=(
            parameters.include_whole_duty_type_exchange
        ),
        stop_requested=lambda: stop(current_state()),
        population_parameters=parameters.population,
        proposal_engine=proposal_engine,
        initial_evaluations=initial_evaluations,
        trajectory_sink=(trajectory.emit_many if trajectory_enabled else None),
        arm=arm,
        schedule_cross_repair_fallback=(
            False
            if treatment is None
            else treatment.schedule_cross_repair_fallback
        ),
        schedule_all_changed_move_evaluation=(
            False
            if treatment is None
            else treatment.schedule_all_changed_move_evaluation
        ),
        fleet_activation_enabled=(
            True if treatment is None else treatment.fleet_activation_enabled
        ),
        objective_mode=parameters.objective_mode,
        charging_prescreen_enabled=charging_prescreen_enabled,
        charging_prescreen_audit_limit=charging_prescreen_audit_limit,
        cross_depot_enabled=cross_depot_enabled,
        multi_trip_enabled=multi_trip_enabled,
        type_exchange_enabled=type_exchange_enabled,
    )
    accounting = bundle.accounting.mechanism
    result = bundle.algorithm.run(_IntegratedStop())
    iterations = result.accounting.iterations
    accounting.initialization_wall_seconds = float(
        initialization_wall_seconds
    )
    accounting.initialization_full_evaluations = int(
        initialization_full_evaluation_count
    )
    accounting.full_evaluations = int(
        initialization_full_evaluation_count
    ) + (evaluator.full_calls - full_calls_before)
    accounting.sentinel_evaluations = (
        evaluator.sentinel_calls - sentinel_calls_before
    )
    best = EvaluatedDutyCandidate(
        result.best.solution,
        result.best.evaluation.full,
    )
    status = (
        CandidateStatus.NO_FEASIBLE_SOLUTION.value
        if not best.evaluation.feasible
        else "STOPPED_BY_CALLER"
    )
    archive = bundle.bi_objective_archive()
    (
        non_dominated_set,
        cost_priority_point,
        emissions_priority_point,
    ) = _bi_objective_result(archive)
    return _finish_result(
        best,
        evaluator,
        iterations,
        accounting,
        trajectory.retained,
        started,
        provenance,
        status=status,
        objective_mode=parameters.objective_mode,
        non_dominated_set=non_dominated_set,
        cost_priority_point=cost_priority_point,
        emissions_priority_point=emissions_priority_point,
        charging_prescreen_accounting=(
            None
            if bundle.charging_prescreen is None
            else bundle.charging_prescreen.statistics()
        ),
    )


def _run_retired_problem_hgs(
    initial_candidates: tuple[DutyIndividual, ...],
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    parameters: ProblemHGSSearchParameters,
    initial_population_identity: FrozenPopulationIdentity,
    stop: Callable[[ProblemHGSSearchState], bool],
    arm: str,
    trajectory_sink: Callable[[tuple[TrajectoryRow, ...]], None] | None = None,
    retain_trajectory: bool = True,
    proposal_engine: DutyProposalEngine | None = None,
    initial_evaluations: tuple[FullEvaluation, ...] | None = None,
    initialization_full_evaluation_count: int | None = None,
    initialization_wall_seconds: float = 0.0,
) -> ProblemHGSRunResult:
    """Retained 2026-08-09 DCREX outer loop; not an exported/default runner."""

    started = perf_counter()
    if not initial_candidates:
        raise ValueError("Problem-HGS requires at least one initial candidate")
    if float(initialization_wall_seconds) < 0.0:
        raise ValueError("initialization wall time cannot be negative")
    if initial_population_identity.value_sha256.lower() != population_sha256(
        initial_candidates
    ):
        raise ValueError(
            "initial candidates disagree with their frozen population identity"
        )
    active_proposal_engine = proposal_engine or LegacyCompleteProposalEngine()
    trajectory = _TrajectoryRecorder(
        trajectory_sink,
        retain=retain_trajectory,
    )
    provenance = ProblemHGSRunProvenance(
        arm=str(arm),
        instance_id=str(evaluator.context.bundle.instance_id),
        random_seed=int(parameters.random_seed),
        search_configuration_sha256=search_configuration_sha256(
            parameters,
            charging_policy,
            arm=arm,
            proposal_engine=active_proposal_engine,
        ),
        initial_population_source_id=initial_population_identity.source_id,
        initial_population_sha256=initial_population_identity.value_sha256.lower(),
        independent_profit_source_id=(
            evaluator.context.independent_profit_identity.source_id
        ),
        independent_profit_sha256=(
            evaluator.context.independent_profit_identity.value_sha256.lower()
        ),
        independent_profit_externally_frozen=(
            evaluator.context.independent_profit_identity.externally_frozen
        ),
        fairness_enabled=bool(evaluator.context.fairness_enabled),
        fairness_theta=float(evaluator.context.theta),
        incremental_full_truth_sentinel_enabled=(
            evaluator.context.incremental_full_truth_sentinel_enabled
        ),
        trajectory_sink_enabled=trajectory_sink is not None,
        trajectory_retained_in_memory=retain_trajectory,
        proposal_engine_source_id=active_proposal_engine.source_id,
        proposal_engine_sha256=active_proposal_engine.identity_sha256,
    )
    rng = random.Random(int(parameters.random_seed))
    dcrex_controller = DCREXController(
        gamma=float(parameters.dcrex_discount_factor)
    )
    crossover_controller = RuntimeAwareCrossoverController(
        gamma=float(parameters.dcrex_discount_factor)
    )
    customer_coordinates = {
        node.node_id: (float(node.x), float(node.y))
        for node in evaluator.context.bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    accounting = SearchAccounting()
    accounting.initialization_wall_seconds = float(
        initialization_wall_seconds
    )
    penalty_manager = AdaptivePenaltyManager(parameters.penalties)
    population = DutyPopulation(parameters.population, penalty_manager)
    if initial_evaluations is not None:
        if len(initial_evaluations) != len(initial_candidates):
            raise ValueError(
                "initial evaluations must match the initial candidate count"
            )
        for candidate, evaluation in zip(
            initial_candidates,
            initial_evaluations,
            strict=True,
        ):
            if evaluation.individual_fingerprint != candidate.fingerprint:
                raise ValueError(
                    "an initial evaluation belongs to another candidate"
                )
            if evaluation.evaluation_context_sha256 != evaluator.context_sha256:
                raise ValueError(
                    "an initial evaluation belongs to another evaluator context"
                )
            if evaluation.source == "incremental_unverified":
                raise ValueError(
                    "an unverified incremental evaluation cannot seed the population"
                )
        evaluated_initial = zip(
            initial_candidates,
            initial_evaluations,
            strict=True,
        )
        counted = (
            len(initial_evaluations)
            if initialization_full_evaluation_count is None
            else int(initialization_full_evaluation_count)
        )
        if counted < len(initial_evaluations):
            raise ValueError(
                "initialization evaluation count cannot be below retained evaluations"
            )
        accounting.full_evaluations += counted
        accounting.initialization_full_evaluations += counted
    else:
        evaluated_rows = []
        for candidate in initial_candidates:
            evaluation = evaluator.evaluate(candidate)
            accounting.full_evaluations += 1
            accounting.initialization_full_evaluations += 1
            evaluated_rows.append((candidate, evaluation))
        evaluated_initial = iter(evaluated_rows)
    for candidate, evaluation in evaluated_initial:
        population.add(candidate, evaluation)
    best = population.best_feasible() or population.best_penalized()
    if best is None:
        raise AssertionError("non-empty initial population was not retained")
    # The copied HGS population remains a pure route-search stream.  Expensive
    # problem mechanisms refine a copy of each new route incumbent and cannot
    # replace or degrade the population member that triggered them.
    route_incumbent: EvaluatedDutyCandidate | None = None

    iterations = 0
    no_improvement = 0
    termination_status = "STOPPED_BY_CALLER"

    def current_state() -> ProblemHGSSearchState:
        return ProblemHGSSearchState(
            iterations=iterations,
            iterations_without_improvement=no_improvement,
            best_cost=(
                float(best.evaluation.total_cost)
                if best.evaluation.feasible
                else None
            ),
            elapsed_seconds=(
                float(initialization_wall_seconds)
                + perf_counter()
                - started
            ),
            full_evaluations=accounting.full_evaluations,
            incremental_evaluations=accounting.incremental_evaluations,
            sentinel_evaluations=accounting.sentinel_evaluations,
            actual_full_model_evaluations=(
                accounting.full_evaluations + accounting.sentinel_evaluations
            ),
            duty_slice_preparations=accounting.duty_slice_preparations,
            candidate_assemblies=accounting.candidate_assemblies,
        )

    def should_stop_control(state: HGSControlState) -> bool:
        nonlocal iterations, no_improvement, termination_status
        iterations = int(state.iterations)
        no_improvement = int(state.iterations_without_improvement)
        if no_improvement > parameters.stagnation_patience:
            termination_status = "CONVERGED_NO_IMPROVEMENT"
            return True
        return bool(stop(current_state()))

    control = HGSControl(
        should_stop=should_stop_control,
        best_value=lambda: _incumbent_key(best, penalty_manager),
        restart_after_iterations_without_improvement=None,
        initial_iterations_without_improvement=0,
    )
    for control_iteration in control.iterations():

        parent_records = population.members()
        accounting.crossover_calls += 1
        crossover_action = (
            CrossoverAction.FAST
            if parameters.crossover_mode == "fast_only"
            else crossover_controller.select(rng)
        )
        pipeline_started = perf_counter()
        try:
            if crossover_action == CrossoverAction.FAST:
                selected = population.select(rng)
                try:
                    trip_assignment = trip_assignment_exchange(
                        (selected[0].individual, selected[1].individual),
                        rng,
                        customer_coordinates,
                    )
                except ValueError as exc:
                    if str(exc) != (
                        "trip assignment found no compatible movable trip"
                    ):
                        raise
                    unavailable = CandidateOutcome(
                        action_id="trip-assignment-unavailable",
                        channel="duty_crossover_availability",
                        status=CandidateStatus.NO_CHANGE,
                        changed_duty_ids=frozenset(),
                        error=str(exc),
                    )
                    accounting.record_outcome(unavailable)
                    trajectory.emit(
                        _trajectory_row(
                            iteration=iterations,
                            phase="crossover",
                            arm=arm,
                            before=selected[0].individual,
                            before_evaluation=selected[0].evaluation,
                            outcome=unavailable,
                            accepted=False,
                        )
                    )
                    if parameters.crossover_mode == "fast_only":
                        crossover_controller.update(
                            crossover_action,
                            0.0,
                            perf_counter() - pipeline_started,
                        )
                        control_iteration.improved = False
                        continue
                    crossover_action = CrossoverAction.DCREX
            if crossover_action == CrossoverAction.FAST:
                main_record = selected[0]
                child = repair_changed_duties(
                    selected[0].individual,
                    trip_assignment.child,
                    changed_duty_ids=set(
                        trip_assignment.changed_duty_ids
                    ),
                    context=evaluator.context,
                    policy=charging_policy,
                )
                child_evaluation = evaluator.evaluate(child)
                accounting.full_evaluations += 1
                changed_duty_ids = trip_assignment.changed_duty_ids
                insertion_operator = None
                diversity_level = None
                deterministic_work_units = (
                    trip_assignment.deterministic_work_units
                )
                crossover_action_label = "TRIP_ASSIGNMENT"
                crossover_action_id = "trip-assignment"
            else:
                crossed = dcrex_duty_exchange(
                    tuple(record.individual for record in parent_records),
                    rng,
                    dcrex_controller,
                )
                main_record = next(
                    record
                    for record in parent_records
                    if record.individual.fingerprint
                    == crossed.main_parent.fingerprint
                )
                child = repair_changed_duties(
                    crossed.main_parent,
                    crossed.child,
                    changed_duty_ids=set(crossed.changed_duty_ids),
                    context=evaluator.context,
                    policy=charging_policy,
                )
                child_evaluation = evaluator.evaluate(child)
                accounting.full_evaluations += 1
                changed_duty_ids = crossed.changed_duty_ids
                insertion_operator = crossed.dcrex.insertion_operator
                diversity_level = crossed.dcrex.diversity_level
                deterministic_work_units = 1
                crossover_action_label = "DCREX"
                crossover_action_id = (
                    f"dcrex:L{diversity_level}:"
                    f"{insertion_operator.value}"
                )
        except (TypeError, ValueError) as exc:
            accounting.record_crossover(
                (
                    "TRIP_ASSIGNMENT"
                    if crossover_action == CrossoverAction.FAST
                    else "DCREX"
                ),
                1,
            )
            crossover_controller.update(
                crossover_action,
                0.0,
                perf_counter() - pipeline_started,
            )
            rejected = CandidateOutcome(
                action_id=crossover_action.value.lower(),
                channel="duty_crossover",
                status=_crossover_rejection_status(exc),
                changed_duty_ids=frozenset(),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            accounting.record_outcome(rejected)
            trajectory.emit(
                _trajectory_row(
                    iteration=iterations,
                    phase="crossover",
                    arm=arm,
                    before=best.individual,
                    before_evaluation=best.evaluation,
                    outcome=rejected,
                    accepted=False,
                )
            )
            control_iteration.improved = False
            continue
        accounting.record_crossover(
            crossover_action_label,
            deterministic_work_units,
        )
        constructed = CandidateOutcome(
            action_id=crossover_action_id,
            channel="duty_crossover",
            status=CandidateStatus.EVALUATED,
            changed_duty_ids=changed_duty_ids,
            candidate=child,
            evaluation=child_evaluation,
        )
        accounting.record_outcome(constructed)
        trajectory.emit(
            _trajectory_row(
                iteration=iterations,
                phase="crossover",
                arm=arm,
                before=main_record.individual,
                before_evaluation=main_record.evaluation,
                outcome=constructed,
                accepted=False,
            )
        )
        if insertion_operator is None:
            repaired = child
            repaired_evaluation = child_evaluation
            repair_rows = ()
        else:
            try:
                repaired, repaired_evaluation, repair_rows = dcrex_repair(
                    child,
                    insertion_operator=insertion_operator,
                    rng=rng,
                    evaluator=evaluator,
                    charging_policy=charging_policy,
                    arm=arm,
                    iteration=iterations,
                    accounting=accounting,
                    penalized_cost=penalty_manager.cost,
                    initial_evaluation=child_evaluation,
                    trajectory_sink=trajectory.emit_many,
                )
            except DutySentinelMismatch as exc:
                trajectory.emit_many(exc.rows)
                return _finish_result(
                    best,
                    evaluator,
                    iterations,
                    accounting,
                    trajectory.retained,
                    started,
                    provenance,
                    status=CandidateStatus.SENTINEL_MISMATCH.value,
                    error=exc,
                )
            except (AssertionError, RuntimeError, TypeError, ValueError) as exc:
                failed = CandidateOutcome(
                    action_id=(
                        f"{crossover_action.value.lower()}-"
                        f"{insertion_operator.value}-repair"
                    ),
                    channel="dcrex_insert",
                    status=CandidateStatus.INTERNAL_ERROR,
                    changed_duty_ids=frozenset(
                        duty.physical_vehicle_id for duty in child.duties
                    ),
                    candidate=child,
                    evaluation=child_evaluation,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                accounting.record_outcome(failed)
                trajectory.emit(
                    _trajectory_row(
                        iteration=iterations,
                        phase="dcrex_repair",
                        arm=arm,
                        before=child,
                        before_evaluation=child_evaluation,
                        outcome=failed,
                        accepted=False,
                    )
                )
                return _finish_result(
                    best,
                    evaluator,
                    iterations,
                    accounting,
                    trajectory.retained,
                    started,
                    provenance,
                    status=CandidateStatus.INTERNAL_ERROR.value,
                    error=exc,
                )
        trajectory.emit_many(repair_rows)
        if repaired.unserved_customers:
            repair_operator_label = (
                "none"
                if insertion_operator is None
                else insertion_operator.value
            )
            crossover_controller.update(
                crossover_action,
                0.0,
                perf_counter() - pipeline_started,
            )
            if insertion_operator is not None:
                dcrex_controller.update_insertion(insertion_operator, 0.0)
            if diversity_level is not None:
                dcrex_controller.update_diversity(diversity_level, 0.0)
            incomplete = CandidateOutcome(
                action_id=(
                    f"{crossover_action.value.lower()}-"
                    f"{repair_operator_label}-"
                    "repair-incomplete"
                ),
                channel="dcrex_insert",
                status=CandidateStatus.REPAIR_INCOMPLETE,
                changed_duty_ids=frozenset(
                    duty.physical_vehicle_id for duty in repaired.duties
                ),
                candidate=repaired,
                evaluation=repaired_evaluation,
                error=(
                    "unserved customers remain: "
                    + ", ".join(repaired.unserved_customers)
                ),
            )
            accounting.record_outcome(incomplete)
            trajectory.emit(
                _trajectory_row(
                    iteration=iterations,
                    phase="dcrex_repair",
                    arm=arm,
                    before=child,
                    before_evaluation=child_evaluation,
                    outcome=incomplete,
                    accepted=False,
                )
            )
            control_iteration.improved = False
            continue
        direct_reward = percentage_reward(
            penalty_manager.cost(main_record.evaluation),
            penalty_manager.cost(repaired_evaluation),
        )
        if diversity_level is not None:
            dcrex_controller.update_diversity(
                diversity_level,
                direct_reward,
            )
        if insertion_operator is not None:
            dcrex_controller.update_insertion(
                insertion_operator,
                direct_reward,
            )
        crossover_controller.update(
            crossover_action,
            direct_reward,
            perf_counter() - pipeline_started,
        )
        try:
            educated = repaired
            educated_evaluation = repaired_evaluation
            stages = proposal_stages(active_proposal_engine)
            route_stage = stages[0]
            elite_route_stage = proposal_elite_route(
                active_proposal_engine
            )
            post_mechanism_route_stage = proposal_post_mechanism_route(
                active_proposal_engine
            )
            mechanism_stages = stages[1:]
            educated, educated_evaluation, education_rows = (
                educate_best_improvement(
                    educated,
                    evaluator=evaluator,
                    charging_policy=charging_policy,
                    arm=arm,
                    iteration=iterations,
                    accounting=accounting,
                    penalized_cost=penalty_manager.cost,
                    initial_evaluation=educated_evaluation,
                    trajectory_sink=trajectory.emit_many,
                    include_whole_duty_type_exchange=(
                        parameters.include_whole_duty_type_exchange
                    ),
                    proposal_engine=route_stage,
                    stop_requested=lambda: stop(current_state()),
                )
            )
        except DutySentinelMismatch as exc:
            trajectory.emit_many(exc.rows)
            return _finish_result(
                best,
                evaluator,
                iterations,
                accounting,
                trajectory.retained,
                started,
                provenance,
                status=CandidateStatus.SENTINEL_MISMATCH.value,
                error=exc,
            )
        except (AssertionError, RuntimeError, TypeError, ValueError) as exc:
            failed = CandidateOutcome(
                action_id="best-improvement-education",
                channel="education",
                status=CandidateStatus.INTERNAL_ERROR,
                changed_duty_ids=frozenset(
                    duty.physical_vehicle_id for duty in repaired.duties
                ),
                candidate=repaired,
                evaluation=repaired_evaluation,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            accounting.record_outcome(failed)
            trajectory.emit(
                _trajectory_row(
                    iteration=iterations,
                    phase="education",
                    arm=arm,
                    before=repaired,
                    before_evaluation=repaired_evaluation,
                    outcome=failed,
                    accepted=False,
                )
            )
            return _finish_result(
                best,
                evaluator,
                iterations,
                accounting,
                trajectory.retained,
                started,
                provenance,
                status=CandidateStatus.INTERNAL_ERROR.value,
                error=exc,
            )
        trajectory.emit_many(education_rows)
        admission = population.add(educated, educated_evaluation)
        accounting.record_population_admission(inserted=admission.inserted)
        admitted = CandidateOutcome(
            action_id="population-admission",
            channel="hgs_population",
            status=CandidateStatus.EVALUATED,
            changed_duty_ids=frozenset(
                duty.physical_vehicle_id for duty in educated.duties
            ),
            candidate=educated,
            evaluation=educated_evaluation,
        )
        trajectory.emit(
            _trajectory_row(
                iteration=iterations,
                phase="population",
                arm=arm,
                before=repaired,
                before_evaluation=repaired_evaluation,
                outcome=admitted,
                accepted=admission.inserted,
            )
        )
        penalty_manager.register(educated_evaluation)
        candidate_best = population.best_feasible() or population.best_penalized()
        route_improved = bool(
            candidate_best is not None
            and (
                route_incumbent is None
                or _incumbent_key(candidate_best, penalty_manager)
                < _incumbent_key(route_incumbent, penalty_manager)
            )
        )
        overall_improved = False
        if candidate_best is not None and _incumbent_key(
            candidate_best,
            penalty_manager,
        ) < _incumbent_key(best, penalty_manager):
            best = candidate_best
            overall_improved = True

        if route_improved and candidate_best is not None:
            route_incumbent = candidate_best
            refined = candidate_best.individual
            refined_evaluation = candidate_best.evaluation
            try:
                refinement_rows_buffer: list[TrajectoryRow] = []
                if elite_route_stage is not None:
                    refined, refined_evaluation, elite_rows = (
                        educate_best_improvement(
                            refined,
                            evaluator=evaluator,
                            charging_policy=charging_policy,
                            arm=arm,
                            iteration=iterations,
                            accounting=accounting,
                            penalized_cost=penalty_manager.cost,
                            initial_evaluation=refined_evaluation,
                            trajectory_sink=trajectory.emit_many,
                            include_whole_duty_type_exchange=(
                                parameters.include_whole_duty_type_exchange
                            ),
                            proposal_engine=elite_route_stage,
                            stop_requested=lambda: stop(current_state()),
                        )
                    )
                    refinement_rows_buffer.extend(elite_rows)
                    route_refined_record = EvaluatedDutyCandidate(
                        refined,
                        refined_evaluation,
                    )
                    route_incumbent = route_refined_record
                    if refined.fingerprint != candidate_best.individual.fingerprint:
                        elite_admission = population.add(
                            refined,
                            refined_evaluation,
                        )
                        accounting.record_population_admission(
                            inserted=elite_admission.inserted
                        )
                        penalty_manager.register(refined_evaluation)
                        trajectory.emit(
                            _trajectory_row(
                                iteration=iterations,
                                phase="elite_population",
                                arm=arm,
                                before=candidate_best.individual,
                                before_evaluation=candidate_best.evaluation,
                                outcome=CandidateOutcome(
                                    action_id="elite-route-population-admission",
                                    channel="hgs_population",
                                    status=CandidateStatus.EVALUATED,
                                    changed_duty_ids=frozenset(
                                        duty.physical_vehicle_id
                                        for duty in refined.duties
                                    ),
                                    candidate=refined,
                                    evaluation=refined_evaluation,
                                ),
                                accepted=elite_admission.inserted,
                            )
                        )
                    if _incumbent_key(
                        route_refined_record,
                        penalty_manager,
                    ) < _incumbent_key(best, penalty_manager):
                        best = route_refined_record
                        overall_improved = True
                for mechanism_stage in mechanism_stages:
                    before_mechanism_fingerprint = refined.fingerprint
                    refined, refined_evaluation, mechanism_rows = (
                        educate_best_improvement(
                            refined,
                            evaluator=evaluator,
                            charging_policy=charging_policy,
                            arm=arm,
                            iteration=iterations,
                            accounting=accounting,
                            penalized_cost=penalty_manager.cost,
                            initial_evaluation=refined_evaluation,
                            trajectory_sink=trajectory.emit_many,
                            include_whole_duty_type_exchange=(
                                parameters.include_whole_duty_type_exchange
                            ),
                            proposal_engine=mechanism_stage,
                            stop_requested=lambda: stop(current_state()),
                        )
                    )
                    refinement_rows_buffer.extend(mechanism_rows)
                    if (
                        refined.fingerprint
                        != before_mechanism_fingerprint
                        and post_mechanism_route_stage is not None
                    ):
                        refined, refined_evaluation, restart_rows = (
                            educate_best_improvement(
                                refined,
                                evaluator=evaluator,
                                charging_policy=charging_policy,
                                arm=arm,
                                iteration=iterations,
                                accounting=accounting,
                                penalized_cost=penalty_manager.cost,
                                initial_evaluation=refined_evaluation,
                                trajectory_sink=trajectory.emit_many,
                                include_whole_duty_type_exchange=(
                                    parameters.include_whole_duty_type_exchange
                                ),
                                proposal_engine=(
                                    post_mechanism_route_stage
                                ),
                                stop_requested=lambda: stop(current_state()),
                            )
                        )
                        refinement_rows_buffer.extend(restart_rows)
                trajectory.emit_many(tuple(refinement_rows_buffer))
            except DutySentinelMismatch as exc:
                trajectory.emit_many(exc.rows)
                return _finish_result(
                    best,
                    evaluator,
                    iterations,
                    accounting,
                    trajectory.retained,
                    started,
                    provenance,
                    status=CandidateStatus.SENTINEL_MISMATCH.value,
                    error=exc,
                )
            except (AssertionError, RuntimeError, TypeError, ValueError) as exc:
                failed = CandidateOutcome(
                    action_id="incumbent-intensification",
                    channel="education",
                    status=CandidateStatus.INTERNAL_ERROR,
                    changed_duty_ids=frozenset(
                        duty.physical_vehicle_id for duty in refined.duties
                    ),
                    candidate=refined,
                    evaluation=refined_evaluation,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                accounting.record_outcome(failed)
                trajectory.emit(
                    _trajectory_row(
                        iteration=iterations,
                        phase="incumbent_intensification",
                        arm=arm,
                        before=route_incumbent.individual,
                        before_evaluation=route_incumbent.evaluation,
                        outcome=failed,
                        accepted=False,
                    )
                )
                return _finish_result(
                    best,
                    evaluator,
                    iterations,
                    accounting,
                    trajectory.retained,
                    started,
                    provenance,
                    status=CandidateStatus.INTERNAL_ERROR.value,
                    error=exc,
                )
            refined_record = EvaluatedDutyCandidate(refined, refined_evaluation)
            if _incumbent_key(
                refined_record,
                penalty_manager,
            ) < _incumbent_key(best, penalty_manager):
                best = refined_record
                overall_improved = True

        control_iteration.improved = bool(route_improved or overall_improved)

    iterations = int(control.state.iterations)
    no_improvement = int(control.state.iterations_without_improvement)

    final_mechanism_stages = proposal_final_stages(active_proposal_engine)
    if final_mechanism_stages and not stop(current_state()):
        refined = best.individual
        refined_evaluation = best.evaluation
        post_mechanism_route_stage = proposal_post_mechanism_route(
            active_proposal_engine
        )
        try:
            for mechanism_stage in final_mechanism_stages:
                before_mechanism_fingerprint = refined.fingerprint
                refined, refined_evaluation, _ = educate_best_improvement(
                    refined,
                    evaluator=evaluator,
                    charging_policy=charging_policy,
                    arm=arm,
                    iteration=iterations,
                    accounting=accounting,
                    penalized_cost=penalty_manager.cost,
                    initial_evaluation=refined_evaluation,
                    trajectory_sink=trajectory.emit_many,
                    include_whole_duty_type_exchange=(
                        parameters.include_whole_duty_type_exchange
                    ),
                    proposal_engine=mechanism_stage,
                    stop_requested=lambda: stop(current_state()),
                )
                if (
                    refined.fingerprint != before_mechanism_fingerprint
                    and post_mechanism_route_stage is not None
                ):
                    refined, refined_evaluation, _ = educate_best_improvement(
                        refined,
                        evaluator=evaluator,
                        charging_policy=charging_policy,
                        arm=arm,
                        iteration=iterations,
                        accounting=accounting,
                        penalized_cost=penalty_manager.cost,
                        initial_evaluation=refined_evaluation,
                        trajectory_sink=trajectory.emit_many,
                        include_whole_duty_type_exchange=(
                            parameters.include_whole_duty_type_exchange
                        ),
                        proposal_engine=post_mechanism_route_stage,
                        stop_requested=lambda: stop(current_state()),
                    )
        except DutySentinelMismatch as exc:
            trajectory.emit_many(exc.rows)
            return _finish_result(
                best,
                evaluator,
                iterations,
                accounting,
                trajectory.retained,
                started,
                provenance,
                status=CandidateStatus.SENTINEL_MISMATCH.value,
                error=exc,
            )
        except (AssertionError, RuntimeError, TypeError, ValueError) as exc:
            failed = CandidateOutcome(
                action_id="final-incumbent-intensification",
                channel="education",
                status=CandidateStatus.INTERNAL_ERROR,
                changed_duty_ids=frozenset(
                    duty.physical_vehicle_id for duty in refined.duties
                ),
                candidate=refined,
                evaluation=refined_evaluation,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            accounting.record_outcome(failed)
            trajectory.emit(
                _trajectory_row(
                    iteration=iterations,
                    phase="final_incumbent_intensification",
                    arm=arm,
                    before=best.individual,
                    before_evaluation=best.evaluation,
                    outcome=failed,
                    accepted=False,
                )
            )
            return _finish_result(
                best,
                evaluator,
                iterations,
                accounting,
                trajectory.retained,
                started,
                provenance,
                status=CandidateStatus.INTERNAL_ERROR.value,
                error=exc,
            )
        refined_record = EvaluatedDutyCandidate(refined, refined_evaluation)
        if _incumbent_key(refined_record, penalty_manager) < _incumbent_key(
            best,
            penalty_manager,
        ):
            best = refined_record

    if not best.evaluation.feasible:
        termination_status = CandidateStatus.NO_FEASIBLE_SOLUTION.value
    return _finish_result(
        best,
        evaluator,
        iterations,
        accounting,
        trajectory.retained,
        started,
        provenance,
        status=termination_status,
    )


def _incumbent_key(
    candidate: EvaluatedDutyCandidate,
    penalty_manager: AdaptivePenaltyManager,
) -> tuple[int, float, str]:
    if candidate.evaluation.feasible:
        return (
            0,
            float(candidate.evaluation.total_cost),
            candidate.individual.fingerprint,
        )
    return (
        1,
        float(penalty_manager.cost(candidate.evaluation)),
        candidate.individual.fingerprint,
    )


def _crossover_rejection_status(error: Exception) -> CandidateStatus:
    message = str(error).lower()
    if "charging" in message:
        return CandidateStatus.REJECTED_CHARGING
    if "fleet" in message or "registry" in message:
        return CandidateStatus.REJECTED_REGISTRY
    if "lock" in message:
        return CandidateStatus.REJECTED_LOCK
    return CandidateStatus.REJECTED_INTERFACE


def population_sha256(candidates: tuple[DutyIndividual, ...]) -> str:
    payload = [
        {
            "fingerprint": candidate.fingerprint,
            "source": candidate.source,
        }
        for candidate in candidates
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def search_configuration_sha256(
    parameters: ProblemHGSSearchParameters,
    charging_policy: ChargingRepairPolicy,
    *,
    arm: str,
    proposal_engine: DutyProposalEngine | None = None,
    treatment: PrivateAblationTreatment | None = None,
) -> str:
    """Hash only the runner, charging-policy, and arm configuration."""

    active_proposal_engine = proposal_engine or LegacyCompleteProposalEngine()
    parameter_payload = asdict(parameters)
    if parameters.objective_mode == SINGLE_OBJECTIVE:
        # Preserve every pre-P39 single-objective configuration digest.
        parameter_payload.pop("objective_mode")
    payload = {
        "arm": str(arm),
        "parameters": parameter_payload,
        "charging_policy": asdict(charging_policy),
        "proposal_engine": {
            "source_id": active_proposal_engine.source_id,
            "identity_sha256": active_proposal_engine.identity_sha256,
        },
    }
    if treatment is not None:
        payload["private_ablation_treatment"] = asdict(treatment)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bi_objective_result(
    archive: BiObjectiveArchive | None,
) -> tuple[
    tuple[BiObjectiveSolutionRecord, ...],
    BiObjectiveSolutionRecord | None,
    BiObjectiveSolutionRecord | None,
]:
    if archive is None:
        return (), None, None
    records = tuple(
        BiObjectiveSolutionRecord(
            individual=entry.candidate.solution,
            evaluation=entry.candidate.evaluation.full,
            total_cost=float(entry.objectives.total_cost),
            total_emissions_kg=float(entry.objectives.total_emissions_kg),
        )
        for entry in archive.entries
    )
    by_fingerprint = {
        record.individual.fingerprint: record for record in records
    }
    cost_priority = (
        None
        if archive.cost_priority is None
        else by_fingerprint[archive.cost_priority.fingerprint]
    )
    emissions_priority = (
        None
        if archive.emissions_priority is None
        else by_fingerprint[archive.emissions_priority.fingerprint]
    )
    return records, cost_priority, emissions_priority


def _finish_result(
    best,
    evaluator: DutyFullEvaluator,
    iterations: int,
    accounting: SearchAccounting,
    trajectory: list[TrajectoryRow],
    started: float,
    provenance: ProblemHGSRunProvenance,
    *,
    status: str,
    error: Exception | None = None,
    objective_mode: str = SINGLE_OBJECTIVE,
    non_dominated_set: tuple[BiObjectiveSolutionRecord, ...] = (),
    cost_priority_point: BiObjectiveSolutionRecord | None = None,
    emissions_priority_point: BiObjectiveSolutionRecord | None = None,
    charging_prescreen_accounting: dict[str, object] | None = None,
) -> ProblemHGSRunResult:
    final_evaluation = evaluator.evaluate(best.individual)
    accounting.full_evaluations += 1
    best = EvaluatedDutyCandidate(best.individual, final_evaluation)
    accounting.run_wall_seconds = perf_counter() - started
    return ProblemHGSRunResult(
        best=best.individual,
        best_evaluation=best.evaluation,
        iterations=iterations,
        accounting=accounting,
        trajectory=tuple(trajectory),
        provenance=provenance,
        termination_status=status,
        termination_error_type=(None if error is None else type(error).__name__),
        termination_error=None if error is None else str(error),
        objective_mode=objective_mode,
        non_dominated_set=non_dominated_set,
        cost_priority_point=cost_priority_point,
        emissions_priority_point=emissions_priority_point,
        charging_prescreen_accounting=charging_prescreen_accounting,
    )
