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

"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from time import perf_counter

from setp_solver.check import PROFIT_FAIRNESS

from .charging import ChargingRepairPolicy
from .contracts import (
    CandidateStatus,
    SearchAccounting,
    TrajectoryRow,
)
from .evaluation import DutyFullEvaluator, FullEvaluation
from .execution_identity import EffectiveExecutionBundle
from .integrated_private import build_integrated_private_hgs
from .kernel_proposals import IndependentKernelDutyRouteProposalEngine
from .model import DutyIndividual
from .population import (
    EvaluatedDutyCandidate,
    PenaltyParameters,
    PopulationParameters,
)
from .proposals import (
    DutyProposalEngine,
)


SINGLE_OBJECTIVE = "single_objective"


@dataclass(frozen=True)
class ProblemHGSSearchParameters:
    random_seed: int
    population: PopulationParameters
    penalties: PenaltyParameters
    stagnation_patience: int = 500
    crossover_mode: str = "fast_only"
    include_whole_duty_type_exchange: bool = True
    objective_mode: str = SINGLE_OBJECTIVE
    education_depth_limit: int | None = None

    def __post_init__(self) -> None:
        if self.stagnation_patience < 1:
            raise ValueError("stagnation patience must be positive")
        if self.crossover_mode not in {"fast_only", "hybrid"}:
            raise ValueError("crossover mode must be fast_only or hybrid")
        if self.education_depth_limit is not None and self.education_depth_limit < 1:
            raise ValueError("education depth limit must be positive")
        if self.objective_mode != SINGLE_OBJECTIVE:
            raise ValueError("only single-objective population mode is supported")


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
    has_feasible: bool = False
    best_feasible_raw_cost: float | None = None
    current_solution_raw_cost: float | None = None
    current_solution_penalized_cost: float | None = None
    physical_feasible: bool | None = None
    fairness_feasible: bool | None = None
    violation_counts: tuple[tuple[str, int], ...] = ()
    violation_magnitudes: tuple[tuple[str, float], ...] = ()
    penalty_coefficients: tuple[tuple[str, float], ...] = ()
    outer_repair_calls: int = 0
    outer_refinement_calls: int = 0


@dataclass(frozen=True)
class ProblemHGSRunResult:
    best: DutyIndividual
    best_evaluation: FullEvaluation
    iterations: int
    accounting: SearchAccounting
    trajectory: tuple[TrajectoryRow, ...]
    provenance: ProblemHGSRunProvenance
    effective_execution: EffectiveExecutionBundle
    termination_status: str
    termination_error_type: str | None = None
    termination_error: str | None = None
    objective_mode: str = SINGLE_OBJECTIVE
    charging_prescreen_accounting: dict[str, object] | None = None


@dataclass(frozen=True)
class ProblemHGSRunProvenance:
    """Inputs that identify one run without claiming a scientific result."""

    arm: str
    instance_id: str
    random_seed: int
    evaluation_context_sha256: str
    effective_execution_schema: str
    effective_algorithm_configuration: dict[str, object] | None
    effective_runtime_identity: dict[str, object]
    search_configuration_sha256: str | None
    initial_population_source_id: str
    initial_population_sha256: str
    independent_profit_source_id: str
    independent_profit_sha256: str
    independent_profit_externally_frozen: bool
    fairness_enabled: bool
    fairness_theta: float | None
    incremental_full_truth_sentinel_enabled: bool
    trajectory_sink_enabled: bool
    trajectory_retained_in_memory: bool
    initialization_full_evaluation_count: int
    initialization_wall_seconds: float
    route_engine_source_id: str
    route_engine_runtime_sha256: str
    route_stage_source_id: str
    route_stage_runtime_sha256: str
    mechanism_stage_source_id: str | None
    mechanism_stage_runtime_sha256: str | None
    route_layer_crossover_enabled: bool = False
    education_depth_limit: int | None = None


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


def _record_integrated_population_admissions(
    population,
    accounting: SearchAccounting,
    *,
    initial_candidate_count: int,
) -> None:
    """Count the standard population's existing admissions without changing it."""

    original_add = population.add
    initial_additions_remaining = int(initial_candidate_count)

    def add(candidate):
        nonlocal initial_additions_remaining
        retained = original_add(candidate)
        if initial_additions_remaining > 0:
            initial_additions_remaining -= 1
        else:
            accounting.record_population_admission(inserted=bool(retained))
        return retained

    population.add = add


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
    route_layer_crossover_enabled: bool = False,
    include_mechanism_refinement: bool = True,
    include_charging_candidates: bool = True,
    expected_search_configuration_sha256: str | None = None,
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

    trajectory_enabled = trajectory_sink is not None or retain_trajectory
    trajectory = _TrajectoryRecorder(
        trajectory_sink,
        retain=retain_trajectory,
    )
    full_calls_before = evaluator.full_calls
    sentinel_calls_before = evaluator.sentinel_calls
    iterations = 0
    no_improvement = 1
    previous_best: float | None = None
    accounting: SearchAccounting | None = None
    bundle = None

    def current_state() -> ProblemHGSSearchState:
        live = accounting or SearchAccounting()
        exact = (
            None
            if bundle is None or bundle.algorithm.best_so_far is None
            else bundle.algorithm.best_so_far.evaluation.full
        )
        counts: Counter[str] = Counter()
        magnitudes: Counter[str] = Counter()
        if exact is not None:
            for violation, magnitude in zip(
                exact.violations,
                exact.violation_magnitudes,
                strict=True,
            ):
                counts[violation.type] += 1
                magnitudes[violation.type] += float(magnitude)
        has_feasible = bool(exact is not None and exact.feasible)
        best_feasible_raw_cost = (
            float(exact.total_cost) if has_feasible else None
        )
        penalty_manager = live.penalty_manager
        full_evaluations = int(initialization_full_evaluation_count) + (
            evaluator.full_calls - full_calls_before
        )
        sentinel_evaluations = evaluator.sentinel_calls - sentinel_calls_before
        return ProblemHGSSearchState(
            iterations=iterations,
            iterations_without_improvement=no_improvement,
            best_cost=best_feasible_raw_cost,
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
            has_feasible=has_feasible,
            best_feasible_raw_cost=best_feasible_raw_cost,
            current_solution_raw_cost=(
                None if exact is None else float(exact.total_cost)
            ),
            current_solution_penalized_cost=(
                None
                if exact is None or penalty_manager is None
                else float(penalty_manager.cost(exact))
            ),
            physical_feasible=(
                None
                if exact is None
                else not any(
                    item.type != PROFIT_FAIRNESS
                    for item in exact.violations
                )
            ),
            fairness_feasible=(
                None
                if exact is None
                else not any(
                    item.type == PROFIT_FAIRNESS
                    for item in exact.violations
                )
            ),
            violation_counts=tuple(sorted(counts.items())),
            violation_magnitudes=tuple(sorted(magnitudes.items())),
            penalty_coefficients=(
                ()
                if penalty_manager is None
                else tuple(sorted(penalty_manager.penalties.items()))
            ),
            outer_repair_calls=(
                0 if bundle is None else bundle.accounting.repair_calls
            ),
            outer_refinement_calls=(
                0 if bundle is None else bundle.accounting.mechanism_calls
            ),
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
        include_mechanism_refinement=include_mechanism_refinement,
        include_whole_duty_type_exchange=(
            parameters.include_whole_duty_type_exchange
        ),
        include_charging_candidates=include_charging_candidates,
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
        route_layer_crossover_enabled=route_layer_crossover_enabled,
        education_depth_limit=parameters.education_depth_limit,
    )
    accounting = bundle.accounting.mechanism
    accounting.penalty_manager = bundle.complete_penalty_manager
    effective_execution = bundle.effective_execution
    actual_search_configuration_sha256 = (
        search_configuration_sha256(effective_execution)
        if effective_execution.formal_identity_eligible
        else None
    )
    if expected_search_configuration_sha256 is not None and (
        actual_search_configuration_sha256 != expected_search_configuration_sha256
    ):
        raise ValueError(
            "effective Problem-HGS search configuration does not match the "
            "expected formal profile"
        )
    effective_algorithm_configuration = (
        _primitive_snapshot(effective_execution.algorithm_configuration_payload())
        if effective_execution.formal_identity_eligible
        else None
    )
    provenance = ProblemHGSRunProvenance(
        arm=str(arm),
        instance_id=str(evaluator.context.bundle.instance_id),
        random_seed=int(parameters.random_seed),
        evaluation_context_sha256=str(evaluator.context_sha256),
        effective_execution_schema=effective_execution.schema_version,
        effective_algorithm_configuration=effective_algorithm_configuration,
        effective_runtime_identity=_primitive_snapshot(
            effective_execution.runtime_identity_payload()
        ),
        search_configuration_sha256=actual_search_configuration_sha256,
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
        fairness_enabled=effective_execution.fairness_enabled,
        fairness_theta=effective_execution.fairness_theta,
        incremental_full_truth_sentinel_enabled=(
            effective_execution.incremental_full_truth_sentinel_enabled
        ),
        trajectory_sink_enabled=trajectory_sink is not None,
        trajectory_retained_in_memory=retain_trajectory,
        initialization_full_evaluation_count=int(
            initialization_full_evaluation_count
        ),
        initialization_wall_seconds=float(initialization_wall_seconds),
        route_engine_source_id=effective_execution.route_engine_source_id,
        route_engine_runtime_sha256=(
            effective_execution.route_engine_runtime_sha256
        ),
        route_stage_source_id=effective_execution.route_stage_source_id,
        route_stage_runtime_sha256=(
            effective_execution.route_stage_runtime_sha256
        ),
        mechanism_stage_source_id=(
            effective_execution.mechanism_stage_source_id
        ),
        mechanism_stage_runtime_sha256=(
            effective_execution.mechanism_stage_runtime_sha256
        ),
        route_layer_crossover_enabled=(
            effective_execution.route_layer_crossover_enabled
        ),
        education_depth_limit=effective_execution.education_depth_limit,
    )
    _record_integrated_population_admissions(
        bundle.population,
        accounting,
        initial_candidate_count=len(initial_candidates),
    )
    result = bundle.algorithm.run(_IntegratedStop())
    iterations = result.accounting.iterations
    accounting.repair_calls += int(bundle.accounting.repair_calls)
    accounting.outer_refinement_calls += int(
        bundle.accounting.mechanism_calls
    )
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
    accounting.charging_repair_cache_hits = int(
        bundle.charging_repair_cache.hits
    )
    accounting.charging_repair_cache_misses = int(
        bundle.charging_repair_cache.misses
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
    return _finish_result(
        best,
        evaluator,
        iterations,
        accounting,
        trajectory.retained,
        started,
        provenance,
        effective_execution,
        status=status,
        objective_mode=parameters.objective_mode,
        charging_prescreen_accounting=(
            None
            if bundle.charging_prescreen is None
            else bundle.charging_prescreen.statistics()
        ),
    )


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


def _primitive_snapshot(payload: dict[str, object]) -> dict[str, object]:
    return json.loads(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def search_configuration_sha256(
    effective_execution: EffectiveExecutionBundle,
) -> str:
    """Hash the stable primitive configuration that actually executes."""

    if not effective_execution.formal_identity_eligible:
        raise ValueError("execution bundle has no approved formal configuration")
    payload = effective_execution.algorithm_configuration_payload()
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finish_result(
    best,
    evaluator: DutyFullEvaluator,
    iterations: int,
    accounting: SearchAccounting,
    trajectory: list[TrajectoryRow],
    started: float,
    provenance: ProblemHGSRunProvenance,
    effective_execution: EffectiveExecutionBundle,
    *,
    status: str,
    error: Exception | None = None,
    objective_mode: str = SINGLE_OBJECTIVE,
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
        effective_execution=effective_execution,
        termination_status=status,
        termination_error_type=(None if error is None else type(error).__name__),
        termination_error=None if error is None else str(error),
        objective_mode=objective_mode,
        charging_prescreen_accounting=charging_prescreen_accounting,
    )
