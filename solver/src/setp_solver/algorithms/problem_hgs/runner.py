"""Runnable isolated Problem-HGS search.

v1 2026-08-07: join the independently implemented HGS population/control
backbone with the prototype duty exchange, regret repair, charging-safe
best-improvement education, and transparent trajectory accounting.
The caller supplies every numerical parameter and the stopping policy.

v2 2026-08-07: reuse the repair phase's verified evaluation when education
starts, so the same child is not fully evaluated twice without disclosure.

v3 2026-08-07: pass the whole-duty EV/CV exchange switch unchanged into
education for paired ablation.

"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

from setp_solver.check import PROFIT_FAIRNESS

from .charging import ChargingRepairPolicy
from .contracts import (
    CandidateStatus,
    SearchAccounting,
    TrajectoryRow,
)
from .evaluation import DutyFullEvaluator, FullEvaluation
from .execution_settings import ExecutionSettings
from .integrated_private import build_integrated_private_hgs
from .kernel_proposals import IndependentKernelDutyRouteProposalEngine
from .model import DutyIndividual
from .population import (
    PopulationParameters,
)


SINGLE_OBJECTIVE = "single_objective"


@dataclass(frozen=True)
class ProblemHGSSearchParameters:
    population: PopulationParameters
    stagnation_patience: int = 20_000
    include_whole_duty_type_exchange: bool = True
    objective_mode: str = SINGLE_OBJECTIVE
    education_depth_limit: int | None = None

    def __post_init__(self) -> None:
        if self.stagnation_patience < 1:
            raise ValueError("stagnation patience must be positive")
        if self.education_depth_limit is not None and self.education_depth_limit < 1:
            raise ValueError("education depth limit must be positive")
        if self.objective_mode != SINGLE_OBJECTIVE:
            raise ValueError("only single-objective population mode is supported")


@dataclass(frozen=True)
class PrivateAblationTreatment:
    """The only component switches allowed to differ inside one paired run."""

    schedule_all_changed_move_evaluation: bool = False
    fleet_activation_enabled: bool = False

    def __post_init__(self) -> None:
        if self.fleet_activation_enabled and not (
            self.schedule_all_changed_move_evaluation
        ):
            raise ValueError("endogenous fleet treatment requires all-move DSS")


@dataclass(frozen=True)
class ProblemHGSSearchState:
    iterations: int
    iterations_without_improvement: int
    best_cost: float | None
    elapsed_seconds: float
    full_evaluations: int
    incremental_evaluations: int
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
    outer_repair_calls: int = 0
    outer_refinement_calls: int = 0


@dataclass(frozen=True)
class ProblemHGSRunResult:
    best: DutyIndividual
    best_evaluation: FullEvaluation
    iterations: int
    accounting: SearchAccounting
    trajectory: tuple[TrajectoryRow, ...]
    effective_execution: ExecutionSettings
    termination_status: str
    termination_error_type: str | None = None
    termination_error: str | None = None
    objective_mode: str = SINGLE_OBJECTIVE
    charging_prescreen_accounting: dict[str, object] | None = None

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
    stop: Callable[[ProblemHGSSearchState], bool],
    arm: str,
    route_engine: IndependentKernelDutyRouteProposalEngine,
    trajectory_sink: Callable[[tuple[TrajectoryRow, ...]], None] | None = None,
    retain_trajectory: bool = True,
    initial_evaluations: tuple[FullEvaluation, ...] | None = None,
    initialization_full_evaluation_count: int | None = None,
    initialization_wall_seconds: float = 0.0,
    treatment: PrivateAblationTreatment | None = None,
    charging_prescreen_enabled: bool = False,
    cross_depot_enabled: bool = True,
    multi_trip_enabled: bool = True,
    type_exchange_enabled: bool = True,
    include_mechanism_refinement: bool = True,
    include_charging_candidates: bool = True,
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
    if initial_evaluations is None:
        initial_evaluations = tuple(
            evaluator.evaluate(candidate) for candidate in initial_candidates
        )
        initialization_full_evaluation_count = len(initial_evaluations)
    elif initialization_full_evaluation_count is None:
        initialization_full_evaluation_count = len(initial_evaluations)

    trajectory_enabled = trajectory_sink is not None or retain_trajectory
    trajectory = _TrajectoryRecorder(
        trajectory_sink,
        retain=retain_trajectory,
    )
    full_calls_before = evaluator.full_calls
    iterations = 0
    no_improvement = 0
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
            for violation, magnitude, axis in zip(
                exact.violations,
                exact.violation_magnitudes,
                exact.violation_axes,
                strict=True,
            ):
                counts[violation.type] += 1
                magnitudes[axis] += float(magnitude)
        has_feasible = bool(exact is not None and exact.feasible)
        best_feasible_raw_cost = (
            float(exact.total_cost) if has_feasible else None
        )
        penalty_manager = live.penalty_manager
        full_evaluations = int(initialization_full_evaluation_count) + (
            evaluator.full_calls - full_calls_before
        )
        return ProblemHGSSearchState(
            iterations=iterations,
            iterations_without_improvement=no_improvement,
            best_cost=best_feasible_raw_cost,
            elapsed_seconds=(
                float(initialization_wall_seconds) + perf_counter() - started
            ),
            full_evaluations=full_evaluations,
            incremental_evaluations=live.incremental_evaluations,
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
                    0 if current < previous_best else no_improvement + 1
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
        include_mechanism_refinement=include_mechanism_refinement,
        include_whole_duty_type_exchange=(
            parameters.include_whole_duty_type_exchange
        ),
        include_charging_candidates=include_charging_candidates,
        stop_requested=lambda: stop(current_state()),
        population_parameters=parameters.population,
        initial_evaluations=initial_evaluations,
        trajectory_sink=(trajectory.emit_many if trajectory_enabled else None),
        arm=arm,
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
        cross_depot_enabled=cross_depot_enabled,
        multi_trip_enabled=multi_trip_enabled,
        type_exchange_enabled=type_exchange_enabled,
        education_depth_limit=parameters.education_depth_limit,
    )
    accounting = bundle.accounting.mechanism
    accounting.penalty_manager = bundle.complete_penalty_manager
    effective_execution = bundle.effective_execution
    _record_integrated_population_admissions(
        bundle.population,
        accounting,
        initial_candidate_count=len(initial_candidates),
    )
    result = bundle.algorithm.run(_IntegratedStop())
    accounting.restarts = result.accounting.restarts
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
    accounting.charging_repair_cache_hits = int(
        bundle.charging_repair_cache.hits
    )
    accounting.charging_repair_cache_misses = int(
        bundle.charging_repair_cache.misses
    )
    return _finish_result(
        result.best.solution,
        evaluator,
        result.accounting.iterations,
        accounting,
        trajectory.retained,
        started,
        effective_execution,
        status="STOPPED_BY_CALLER",
        objective_mode=parameters.objective_mode,
        charging_prescreen_accounting=(
            None
            if bundle.charging_prescreen is None
            else bundle.charging_prescreen.statistics()
        ),
    )


def _finish_result(
    best: DutyIndividual,
    evaluator: DutyFullEvaluator,
    iterations: int,
    accounting: SearchAccounting,
    trajectory: list[TrajectoryRow],
    started: float,
    effective_execution: ExecutionSettings,
    *,
    status: str,
    error: Exception | None = None,
    objective_mode: str = SINGLE_OBJECTIVE,
    charging_prescreen_accounting: dict[str, object] | None = None,
) -> ProblemHGSRunResult:
    final_evaluation = evaluator.evaluate(best)
    accounting.full_evaluations += 1
    accounting.run_wall_seconds = perf_counter() - started
    return ProblemHGSRunResult(
        best=best,
        best_evaluation=final_evaluation,
        iterations=iterations,
        accounting=accounting,
        trajectory=tuple(trajectory),
        effective_execution=effective_execution,
        termination_status=(
            CandidateStatus.NO_FEASIBLE_SOLUTION.value
            if not final_evaluation.feasible
            else status
        ),
        termination_error_type=(None if error is None else type(error).__name__),
        termination_error=None if error is None else str(error),
        objective_mode=objective_mode,
        charging_prescreen_accounting=charging_prescreen_accounting,
    )
