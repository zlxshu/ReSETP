"""Production wiring for the MAIN-3b paired dynamic experiment.

This module deliberately contains adapters, not a new routing method.  The
static and rolling arms enter the existing private Problem-HGS runner; the
mechanical arm enters the existing three-class insertion baseline.  Exact
dynamic cuts, complete evaluation, and the fleet ledger remain owned by the
existing Problem-HGS components.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_ROOT = _REPO_ROOT / "scripts"
if str(_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_ROOT))

from experiment_acceptance import (  # noqa: E402
    NORMAL_PROBLEM_HGS_TERMINATIONS,
)
from run_problem_hgs_private_technical import (  # noqa: E402
    DEPOT_SEARCH_INSTANCE_ID,
    ENDOGENOUS_FLEET_PARAMETERS,
    _build_context,
    _parameters,
    _policy,
)
from setp_solver.algorithms.problem_hgs.initialization import (  # noqa: E402
    build_initial_population,
)
from setp_solver.algorithms.problem_hgs.dynamic import (  # noqa: E402
    DutyDynamicState,
    PreparedDynamicCandidate,
    full_executed_prefix,
    future_individual_from_cut,
    prepare_dynamic_candidate,
)
from setp_solver.algorithms.problem_hgs.dynamic_insertion import (  # noqa: E402
    DynamicInsertionFailure,
    DynamicInsertionOperator,
    INSERTED_AND_FULL_EVALUATION_FEASIBLE,
)
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    DutyEvaluationContext,
    DutyFullEvaluator,
    FullEvaluation,
)
from setp_solver.algorithms.problem_hgs.kernel_proposals import (  # noqa: E402
    IndependentKernelDutyRouteProposalEngine,
)
from setp_solver.algorithms.problem_hgs.mechanical_baseline import (  # noqa: E402
    MechanicalInsertionFailure,
    insert_initial_customer,
    insert_revealed_customer,
)
from setp_solver.algorithms.problem_hgs.model import (  # noqa: E402
    DutyIndividual,
)
from setp_solver.algorithms.problem_hgs.runner import (  # noqa: E402
    ProblemHGSSearchState,
    run_integrated_problem_hgs,
)
from setp_solver.c8_dynamic_stream import (  # noqa: E402
    C8_BASE_INSTANCE_ID,
    C8DynamicEvent,
    C8DynamicStream,
    active_customers_after_events,
    extend_route_contract,
    load_c8_stream,
    overlay_c8_bundle,
    subset_c8_bundle,
)
from setp_solver.search.dynamic_multitrip_schedule import (  # noqa: E402
    DynamicAssetState,
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
)
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    Route,
    Solution,
    physical_vehicle_id,
)


_DAY_SECONDS = 86_400.0
_TOL = 1.0e-9


class ProductionBackendHalt(RuntimeError):
    """An existing component could not satisfy the declared backend contract."""


@dataclass(frozen=True)
class ProductionEvaluation:
    """Harness-shaped view of one already-computed full evaluation."""

    total_cost: float
    total_emissions_kg: float
    customers_served: int
    demand_served_kg: float
    enabled_vehicles: int
    full_evaluation_feasible: bool
    details: Mapping[str, Any] = MappingProxyType({})


@dataclass(frozen=True)
class ProductionOrder:
    """The small information object consumed by the generic harness."""

    event_id: str
    customer_id: str
    appearance_second: float
    demand_kg: float
    x: float
    y: float
    initially_visible: bool = False
    event_type: str = "add"
    old_demand_kg: float = 0.0
    old_ready_second: float = 0.0
    old_due_second: float = 0.0
    new_ready_second: float = 0.0
    new_due_second: float = 0.0

    @property
    def trigger_demand_kg(self) -> float:
        return float(self.demand_kg) if self.event_type == "add" else 0.0


@dataclass(frozen=True)
class ProductionDynamicProblem:
    """Read-only unified target plus the in-memory C8 overlay."""

    instance_id: str
    repo: Path
    base_bundle: Any
    full_bundle: Any
    base_initial: DutyIndividual
    base_context: DutyEvaluationContext
    c8_stream: C8DynamicStream
    initial_orders: tuple[ProductionOrder, ...]
    dynamic_orders: tuple[ProductionOrder, ...]

    @property
    def orders(self) -> tuple[ProductionOrder, ...]:
        return self.initial_orders + self.dynamic_orders

    @property
    def order_by_id(self) -> Mapping[str, ProductionOrder]:
        return {order.customer_id: order for order in self.orders}

    @property
    def static_customer_ids(self) -> frozenset[str]:
        return frozenset(order.customer_id for order in self.initial_orders)

    @property
    def dynamic_customer_ids(self) -> frozenset[str]:
        return self.c8_stream.added_customer_ids

    @property
    def event_by_id(self) -> Mapping[str, C8DynamicEvent]:
        return MappingProxyType(
            {event.event_id: event for event in self.c8_stream.events}
        )

    @property
    def final_customer_ids(self) -> frozenset[str]:
        return active_customers_after_events(
            self.static_customer_ids,
            self.c8_stream.events,
        )

    @property
    def appearance_by_customer(self) -> Mapping[str, float]:
        appearances = {
            order.customer_id: 0.0 for order in self.initial_orders
        }
        appearances.update(
            {
                event.customer_id: float(event.appearance_second)
                for event in self.c8_stream.events
                if event.event_type == "add"
            }
        )
        return MappingProxyType(appearances)


@dataclass(frozen=True)
class ProductionState:
    """A public harness state and a private continuation checkpoint.

    ``evaluation`` is the one complete evaluation exposed to the harness.
    ``planning_future`` is separate because a deferred order is intentionally
    absent from the last successful continuation and must be retried later.
    """

    individual: DutyIndividual
    evaluation: FullEvaluation
    bundle: Any
    context: DutyEvaluationContext
    active_customer_ids: frozenset[str]
    dynamic_state: DutyDynamicState | None
    stage_index: int
    base_individual: DutyIndividual
    static_solution: Solution
    static_certificate: Any
    planning_dynamic_state: DutyDynamicState | None = None
    planning_future: PreparedDynamicCandidate | None = None
    planning_evaluation: FullEvaluation | None = None
    planning_individual: DutyIndividual | None = None
    planning_active_customer_ids: frozenset[str] = frozenset()
    planning_trigger_second: float | None = None
    deferred_customer_ids: tuple[str, ...] = ()
    timing_by_route: Mapping[str, Any] = MappingProxyType({})
    route_change_evidence: Mapping[str, Any] = MappingProxyType({})
    diagnostics: tuple[Mapping[str, Any], ...] = ()
    outsourced_customer_ids: tuple[str, ...] = ()
    mechanical_insertion_wall_seconds: float = 0.0
    applied_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "active_customer_ids",
            frozenset(self.active_customer_ids),
        )
        object.__setattr__(
            self,
            "planning_active_customer_ids",
            frozenset(self.planning_active_customer_ids),
        )
        object.__setattr__(
            self,
            "deferred_customer_ids",
            tuple(dict.fromkeys(map(str, self.deferred_customer_ids))),
        )
        object.__setattr__(
            self,
            "timing_by_route",
            MappingProxyType(dict(self.timing_by_route)),
        )
        object.__setattr__(
            self,
            "route_change_evidence",
            MappingProxyType(dict(self.route_change_evidence)),
        )
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(
            self,
            "applied_event_ids",
            tuple(dict.fromkeys(map(str, self.applied_event_ids))),
        )
        if self.mechanical_insertion_wall_seconds < 0.0:
            raise ValueError("mechanical insertion time must be non-negative")

    @property
    def unserved_customer_ids(self) -> tuple[str, ...]:
        return tuple(self.individual.unserved_customers)


@dataclass(frozen=True)
class _StageFrame:
    active_customer_ids: frozenset[str]
    trigger_second: float
    bundle: Any
    context: DutyEvaluationContext
    evaluator: DutyFullEvaluator
    dynamic_state: DutyDynamicState
    initial_future: DutyIndividual
    source_solution: Solution
    source_certificate: Any
    timing_by_route: Mapping[str, Any]
    applied_event_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProductionBackend:
    """Adapter implementing the seven-method experiment backend contract."""

    evaluator_identity = "Problem-HGS-DutyFullEvaluator-v2026-08-16"

    def initial_plan(
        self,
        problem: ProductionDynamicProblem,
    ) -> ProductionState:
        context = _static_context(problem.base_context, problem.base_bundle)
        candidate, evaluation, _ = self._run_hgs(
            problem.base_initial,
            context,
            arm="initial_plan",
            stage_index=0,
        )
        static_solution = evaluation.prepared_solution
        static_certificate = evaluation.certificate
        static_ids = problem.static_customer_ids
        return ProductionState(
            individual=candidate,
            evaluation=evaluation,
            bundle=problem.base_bundle,
            context=context,
            active_customer_ids=static_ids,
            dynamic_state=None,
            stage_index=0,
            base_individual=problem.base_initial,
            static_solution=static_solution,
            static_certificate=static_certificate,
            planning_individual=problem.base_initial,
            planning_active_customer_ids=static_ids,
            timing_by_route=_timing_map(static_certificate),
        )

    def rolling_reoptimize(
        self,
        problem: ProductionDynamicProblem,
        current: ProductionState,
        active_customer_ids: Sequence[str],
        event_ids: Sequence[str],
        trigger_second: float,
    ) -> tuple[ProductionState, str]:
        active = frozenset(map(str, active_customer_ids))
        _validate_active(problem, active)
        applied = tuple(
            dict.fromkeys((*current.applied_event_ids, *map(str, event_ids)))
        )
        frame = self._build_stage(
            problem,
            current,
            active,
            float(trigger_second),
            applied,
        )
        stage_evaluation = frame.evaluator.evaluate(frame.initial_future)
        pending = tuple(frame.initial_future.unserved_customers)
        if not pending:
            next_state = _successful_state(
                current,
                frame,
                frame.initial_future,
                stage_evaluation,
                active_customer_ids=active,
                stage_index=current.stage_index + 1,
                diagnostics={
                    "arm": "rolling_dynamic",
                    "kind": "attribute_or_cancellation_update",
                },
            )
            return next_state, "rolling_attribute_or_cancellation_update"
        # 2026-08-31: frvcpy 关闭，与静态正式配置对齐（剖析实证：逐候选整建实例=43分钟/教育轮）。

        policy = _policy(frame.evaluator, frvcpy_enabled=False)
        try:
            insertion = DynamicInsertionOperator(
                enabled=True,
            ).apply(
                frame.initial_future,
                evaluator=frame.evaluator,
                charging_policy=policy,
                newly_revealed_customer_ids=pending,
                current_evaluation=stage_evaluation,
            )
        except (DynamicInsertionFailure, TypeError, ValueError) as error:
            insertion = self._rolling_mechanical_fallback(frame, pending)
            if insertion is None:
                deferred = _deferred_state(
                    current,
                    frame,
                    stage_evaluation,
                    active_customer_ids=active,
                    deferred_customer_ids=tuple(
                        dict.fromkeys((*current.deferred_customer_ids, *pending))
                    ),
                    stage_index=current.stage_index + 1,
                    diagnostic={
                        "arm": "rolling_dynamic",
                        "kind": "dynamic_insertion_exception",
                        "error": f"{type(error).__name__}: {error}",
                    },
                )
                return deferred, "rolling_defer_dynamic_insertion_exception"

        if (
            insertion.status != INSERTED_AND_FULL_EVALUATION_FEASIBLE
            or insertion.evaluation is None
        ):
            fallback = self._rolling_mechanical_fallback(frame, pending)
            if fallback is not None:
                insertion = fallback
        if (
            insertion.status != INSERTED_AND_FULL_EVALUATION_FEASIBLE
            or insertion.evaluation is None
        ):
            diagnostic = {
                "arm": "rolling_dynamic",
                "kind": "dynamic_insertion_no_feasible_candidate",
                "status": insertion.status,
                "failure_reason": insertion.failure_reason,
                "candidate_diagnostics": [
                    {
                        "candidate_id": item.candidate_id,
                        "scope": item.scope,
                        "status": item.status,
                        "failure_reason": item.failure_reason,
                    }
                    for item in insertion.accounting.candidate_diagnostics
                ],
            }
            return (
                _deferred_state(
                    current,
                    frame,
                    stage_evaluation,
                    active_customer_ids=active,
                    deferred_customer_ids=tuple(
                        dict.fromkeys((*current.deferred_customer_ids, *pending))
                    ),
                    stage_index=current.stage_index + 1,
                    diagnostic=diagnostic,
                ),
                "rolling_defer_no_feasible_candidate",
            )

        candidate, evaluation, run_result = self._run_hgs(
            insertion.individual,
            frame.context,
            arm="rolling_dynamic",
            stage_index=current.stage_index + 1,
        )
        if not evaluation.feasible:
            candidate = insertion.individual
            evaluation = insertion.evaluation
        next_state = _successful_state(
            current,
            frame,
            candidate,
            evaluation,
            active_customer_ids=active,
            stage_index=current.stage_index + 1,
            diagnostics={
                "arm": "rolling_dynamic",
                "kind": "problem_hgs_stage",
                "iterations": int(run_result.iterations),
                "termination_status": run_result.termination_status,
                "dynamic_insertion_candidate_count": int(
                    insertion.accounting.candidate_attempt_count
                ),
            },
        )
        return next_state, "rolling_dynamic_insertion_then_problem_hgs"

    def _rolling_mechanical_fallback(self, frame, pending):
        """Serve late arrivals with the three-class mechanical insertion.

        The kernel insertion only searches inherited assets, so a late order
        that needs a fresh vehicle finds no candidate there (observed: 68/68
        candidates infeasible while the mechanical dispatch class succeeded).
        Falling back keeps the rolling arm's insertion toolset a superset of
        the sequential arm's."""
        from types import SimpleNamespace

        individual = frame.initial_future
        evaluation = None
        for customer_id in pending:
            try:
                result = insert_revealed_customer(
                    individual,
                    customer_id,
                    frame.evaluator,
                )
            except (MechanicalInsertionFailure, TypeError, ValueError):
                return None
            individual = result.individual
            evaluation = result.evaluation
        if evaluation is None or not evaluation.feasible:
            return None
        return SimpleNamespace(
            individual=individual,
            evaluation=evaluation,
            accounting=SimpleNamespace(
                candidate_attempt_count=len(tuple(pending))
            ),
            status=INSERTED_AND_FULL_EVALUATION_FEASIBLE,
        )

    def mechanical_dispatch(
        self,
        problem: ProductionDynamicProblem,
        current: ProductionState,
        active_customer_ids: Sequence[str],
        event_ids: Sequence[str],
        trigger_second: float,
    ) -> tuple[ProductionState, str]:
        active_all = frozenset(map(str, active_customer_ids))
        _validate_active(problem, active_all)
        applied = tuple(
            dict.fromkeys((*current.applied_event_ids, *map(str, event_ids)))
        )
        new_ids = tuple(
            problem.event_by_id[event_id].customer_id
            for event_id in event_ids
            if problem.event_by_id[event_id].event_type == "add"
        )
        queue = tuple(
            dict.fromkeys((*current.deferred_customer_ids, *new_ids))
        )
        work = current
        detail_rows: list[str] = []
        for customer_id in queue:
            if customer_id in work.planning_active_customer_ids:
                continue
            attempt_active = frozenset(
                {*work.planning_active_customer_ids, customer_id}
            )
            frame = self._build_stage(
                problem,
                work,
                attempt_active,
                float(trigger_second),
                applied,
            )
            stage_evaluation = frame.evaluator.evaluate(frame.initial_future)
            insertion_started = _now()
            try:
                result = insert_revealed_customer(
                    frame.initial_future,
                    customer_id,
                    frame.evaluator,
                )
            except MechanicalInsertionFailure as error:
                insertion_elapsed = _now() - insertion_started
                detail_rows.append(f"{customer_id}:defer")
                work = _deferred_state(
                    work,
                    frame,
                    stage_evaluation,
                    active_customer_ids=attempt_active,
                    deferred_customer_ids=tuple(
                        dict.fromkeys((*work.deferred_customer_ids, customer_id))
                    ),
                    stage_index=work.stage_index,
                    diagnostic={
                        "arm": "mechanical_online_p38",
                        "kind": "mechanical_no_feasible_candidate",
                        "customer_id": customer_id,
                        "class_diagnostics": error.class_diagnostics,
                        "rejected_candidates": [
                            [key, int(value)]
                            for key, value in error.rejected_candidates
                        ],
                    },
                )
                work = replace(
                    work,
                    mechanical_insertion_wall_seconds=(
                        work.mechanical_insertion_wall_seconds
                        + insertion_elapsed
                    ),
                )
                continue
            except (TypeError, ValueError) as error:
                raise ProductionBackendHalt(
                    "mechanical baseline cannot consume the dynamic cut for "
                    f"{customer_id}: {type(error).__name__}: {error}"
                ) from error

            insertion_elapsed = _now() - insertion_started
            work = _successful_state(
                work,
                frame,
                result.individual,
                result.evaluation,
                active_customer_ids=attempt_active,
                stage_index=work.stage_index,
                diagnostics={
                    "arm": "mechanical_online_p38",
                    "kind": "mechanical_insertion",
                    "customer_id": customer_id,
                    "candidate_class": result.decision.candidate_class,
                    "rejected_candidates": [
                        [key, int(value)]
                        for key, value in result.decision.rejected_candidates
                    ],
                },
            )
            work = replace(
                work,
                mechanical_insertion_wall_seconds=(
                    work.mechanical_insertion_wall_seconds
                    + insertion_elapsed
                ),
            )
            detail_rows.append(
                f"{customer_id}:{result.decision.candidate_class}"
            )

        report_frame = self._build_stage(
            problem,
            work,
            active_all,
            float(trigger_second),
            applied,
        )
        report_evaluation = report_frame.evaluator.evaluate(
            report_frame.initial_future
        )
        diagnostic = {
            "arm": "mechanical_online_p38",
            "kind": "batch_summary",
            "decisions": list(detail_rows),
        }
        if report_frame.initial_future.unserved_customers or not report_evaluation.feasible:
            report = _deferred_state(
                work,
                report_frame,
                report_evaluation,
                active_customer_ids=active_all,
                deferred_customer_ids=work.deferred_customer_ids,
                stage_index=current.stage_index + 1,
                diagnostic=diagnostic,
                route_change_evidence=work.route_change_evidence,
            )
        else:
            report = _successful_state(
                work,
                report_frame,
                report_frame.initial_future,
                report_evaluation,
                active_customer_ids=active_all,
                stage_index=current.stage_index + 1,
                diagnostics=diagnostic,
            )
        return report, ";".join(detail_rows)

    def full_information_static(
        self,
        problem: ProductionDynamicProblem,
        all_customer_ids: Sequence[str],
    ) -> ProductionState:
        final_ids = frozenset(map(str, all_customer_ids))
        applied = tuple(event.event_id for event in problem.c8_stream.events)
        final_bundle = subset_c8_bundle(
            problem.full_bundle,
            final_ids,
            problem.c8_stream.events,
        )
        added = problem.dynamic_customer_ids
        base_ids = final_ids.difference(added)
        base_bundle = subset_c8_bundle(
            problem.full_bundle,
            base_ids,
            problem.c8_stream.events,
        )
        base_context = _static_context(
            _context_with_bundle(problem.base_context, base_bundle, problem),
            base_bundle,
        )
        base_initial = _without_customers(
            problem.base_initial,
            problem.static_customer_ids.difference(base_ids),
        )
        base_evaluation = DutyFullEvaluator(base_context).evaluate(base_initial)
        if not base_evaluation.feasible:
            raise ProductionBackendHalt(
                "full-information reference start is infeasible before insertion"
            )
        base = ProductionState(
            individual=base_initial,
            evaluation=base_evaluation,
            bundle=base_bundle,
            context=base_context,
            active_customer_ids=base_ids,
            dynamic_state=None,
            stage_index=0,
            base_individual=base_initial,
            static_solution=base_evaluation.prepared_solution,
            static_certificate=base_evaluation.certificate,
            planning_individual=base_initial,
            planning_active_customer_ids=base_ids,
            timing_by_route=_timing_map(base_evaluation.certificate),
            applied_event_ids=applied,
        )
        current = base.individual
        active = set(base_ids)
        dynamic_ids = [
            str(customer_id)
            for customer_id in all_customer_ids
            if str(customer_id) in problem.dynamic_customer_ids
        ]
        diagnostics: list[Mapping[str, Any]] = []
        for customer_id in dynamic_ids:
            active.add(customer_id)
            bundle = subset_c8_bundle(
                problem.full_bundle,
                active,
                problem.c8_stream.events,
            )
            context = _static_context(
                _context_with_bundle(problem.base_context, bundle, problem),
                bundle,
            )
            candidate = replace(
                current,
                unserved_customers=(customer_id,),
                source="full-information-static-preinsert",
            )
            evaluator = DutyFullEvaluator(context)
            try:
                inserted = insert_initial_customer(candidate, customer_id, evaluator)
            except (TypeError, ValueError, RuntimeError) as error:
                remaining = tuple(dynamic_ids[dynamic_ids.index(customer_id) :])
                incomplete = replace(
                    current,
                    unserved_customers=remaining,
                    source="full-information-static-defer",
                )
                last_evaluation = evaluator.evaluate(incomplete)
                diagnostics.append(
                    {
                        "arm": "full_information_static_reference",
                        "kind": "static_preinsert_failure",
                        "customer_id": customer_id,
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
                return ProductionState(
                    individual=incomplete,
                    evaluation=last_evaluation,
                    bundle=bundle,
                    context=context,
                    active_customer_ids=frozenset(active),
                    dynamic_state=None,
                    stage_index=len(dynamic_ids),
                    base_individual=problem.base_initial,
                    static_solution=base.static_solution,
                    static_certificate=base.static_certificate,
                    planning_active_customer_ids=frozenset(active - set(remaining)),
                    deferred_customer_ids=remaining,
                    timing_by_route=_timing_map(last_evaluation.certificate),
                    diagnostics=tuple(diagnostics),
                    applied_event_ids=applied,
                )
            current = inserted.individual

        context = _static_context(
            _context_with_bundle(problem.base_context, final_bundle, problem),
            final_bundle,
        )
        candidate, evaluation, run_result = self._run_hgs(
            current,
            context,
            arm="full_information_static_reference",
            stage_index=len(dynamic_ids),
        )
        return ProductionState(
            individual=candidate,
            evaluation=evaluation,
            bundle=final_bundle,
            context=context,
            active_customer_ids=final_ids,
            dynamic_state=None,
            stage_index=len(dynamic_ids),
            base_individual=problem.base_initial,
            static_solution=base.static_solution,
            static_certificate=base.static_certificate,
            planning_individual=candidate,
            planning_active_customer_ids=final_ids,
            timing_by_route=_timing_map(evaluation.certificate),
            diagnostics=(
                *diagnostics,
                {
                    "arm": "full_information_static_reference",
                    "kind": "problem_hgs_stage",
                    "termination_status": run_result.termination_status,
                },
            ),
            applied_event_ids=applied,
        )

    def evaluate(
        self,
        problem: ProductionDynamicProblem,
        state: ProductionState,
    ) -> Any:
        """Expose the already-computed DutyFullEvaluator result."""

        full = state.evaluation
        bundle = state.bundle
        served = _served_customers(full.prepared_solution, bundle)
        active = {
            node.node_id
            for node in bundle.instance.nodes
            if node.node_type.lower() == "c"
        }
        demand = {
            node.node_id: float(node.demand)
            for node in bundle.instance.nodes
            if node.node_type.lower() == "c"
        }
        enabled = {
            physical_vehicle_id(route.vehicle_id)
            for route in full.prepared_solution.routes
        }
        details = _details(
            state,
            full,
            bundle,
            served,
            active,
            demand,
            dynamic_customer_ids=problem.dynamic_customer_ids,
        )
        return ProductionEvaluation(
            total_cost=float(full.total_cost),
            total_emissions_kg=float(full.breakdown.get("E_total", 0.0)),
            customers_served=len(served),
            demand_served_kg=sum(demand[item] for item in served),
            enabled_vehicles=len(enabled),
            full_evaluation_feasible=bool(full.feasible),
            details=details,
        )

    def active_totals(
        self,
        problem: ProductionDynamicProblem,
        active_customer_ids: Sequence[str],
        applied_event_ids: Sequence[str],
    ) -> tuple[int, float]:
        events = tuple(
            problem.event_by_id[event_id] for event_id in applied_event_ids
        )
        bundle = subset_c8_bundle(
            problem.full_bundle,
            active_customer_ids,
            events,
        )
        customers = [
            node
            for node in bundle.instance.nodes
            if node.node_type.lower() == "c"
        ]
        return len(customers), sum(float(node.demand) for node in customers)

    def fleet_snapshot(
        self,
        problem: ProductionDynamicProblem,
        state: ProductionState,
    ) -> list[dict[str, Any]]:
        del problem
        full = state.evaluation
        bundle = state.bundle
        routes_by_asset: dict[str, list[Route]] = {}
        for route in full.prepared_solution.routes:
            routes_by_asset.setdefault(
                physical_vehicle_id(route.vehicle_id), []
            ).append(route)
        timings = dict(state.timing_by_route)
        timings.update(_timing_map(full.certificate))
        battery_capacity = float(
            bundle.instance.battery_capacity_kwh(
                fallback=float(getattr(bundle.prices, "B_battery_kwh", 0.0))
            )
        )
        rows: list[dict[str, Any]] = []
        for duty in state.base_individual.duties:
            asset_id = duty.physical_vehicle_id
            routes = routes_by_asset.get(asset_id, [])
            customers = [
                customer_id
                for route in routes
                for customer_id in route.node_sequence[1:-1]
            ]
            demand = sum(
                float(
                    bundle.instance.nodes[bundle.instance.node_index[customer_id]].demand
                )
                for customer_id in customers
                if customer_id in bundle.instance.node_index
            )
            trip_times = [
                timings[route.vehicle_id]
                for route in routes
                if route.vehicle_id in timings
            ]
            departure = (
                min(float(item.departure_second) for item in trip_times)
                if trip_times
                else ""
            )
            returned = (
                max(float(item.return_second) for item in trip_times)
                if trip_times
                else ""
            )
            asset_state = (
                None
                if state.dynamic_state is None
                else state.dynamic_state.asset_states.get(asset_id)
            )
            soc = (
                ""
                if asset_state is None or duty.vehicle_type != "ev"
                else float(asset_state.remaining_battery_kwh)
            )
            soc_fraction = (
                ""
                if soc == "" or battery_capacity <= 0.0
                else float(soc) / battery_capacity
            )
            capacity = _payload_capacity(bundle, duty.vehicle_type)
            rows.append(
                {
                    "vehicle_id": asset_id,
                    "vehicle_type": duty.vehicle_type,
                    "home_depot_id": duty.home_depot_id,
                    "status": "used" if routes else "idle",
                    "trip_count": len(routes),
                    "assigned_customer_count": len(customers),
                    "assigned_demand_kg": demand,
                    "remaining_capacity_kg": (
                        "" if capacity is None else max(0.0, capacity - demand)
                    ),
                    "departure_second": departure,
                    "return_second": returned,
                    "soc_kwh": soc,
                    "soc_fraction": soc_fraction,
                }
            )
        return rows

    def _build_stage(
        self,
        problem: ProductionDynamicProblem,
        previous: ProductionState,
        active_customer_ids: frozenset[str],
        trigger_second: float,
        applied_event_ids: Sequence[str],
    ) -> _StageFrame:
        if not problem.base_context.rebuilt_route_constraints:
            raise ProductionBackendHalt(
                "unified target has no rebuilt route contract; dynamic cut "
                "cannot freeze shift-aware execution"
            )
        applied_events = tuple(
            problem.event_by_id[event_id] for event_id in applied_event_ids
        )
        bundle = subset_c8_bundle(
            problem.full_bundle,
            active_customer_ids,
            applied_events,
        )
        route_contract = extend_route_contract(
            problem.base_context.rebuilt_route_constraints,
            problem.c8_stream,
            active_customer_ids,
        )
        if previous.planning_future is None:
            source_solution = previous.static_solution
            source_certificate = previous.static_certificate
            cut = cut_certificate_at_trigger(
                source_solution,
                source_certificate,
                bundle.instance,
                bundle.prices,
                trigger_second=float(trigger_second),
            )
            assets = _full_asset_registry(
                previous.base_individual,
                cut,
                bundle,
            )
            prior = Solution()
            certified_history = frozenset()
            timing = _timing_map(source_certificate)
            inherited_evaluation_instance = None
            source_full_execution_solution = None
            prior_prefix_accounting = MappingProxyType({})
        else:
            if previous.planning_dynamic_state is None:
                raise ProductionBackendHalt(
                    "dynamic continuation has a future solution but no "
                    "dynamic asset state"
                )
            cut_source_solution = previous.planning_future.future_solution
            source_certificate = previous.planning_future.future_certificate
            cut = cut_dynamic_certificate_at_trigger(
                cut_source_solution,
                source_certificate,
                previous.planning_future.evaluation_instance,
                bundle.prices,
                inherited_asset_states=previous.planning_dynamic_state.asset_states,
                previous_stage_start_second=float(
                    previous.planning_dynamic_state.cut.trigger_second
                ),
                trigger_second=float(trigger_second),
                inherited_locked_charging_actions=(
                    previous.planning_dynamic_state.cut.locked_charging_actions
                ),
            )
            source_solution = cut_source_solution
            source_full_execution_solution = (
                previous.planning_future.full_execution_solution
            )
            inherited_evaluation_instance = (
                previous.planning_future.evaluation_instance
            )
            if previous.planning_evaluation is None:
                raise ProductionBackendHalt(
                    "dynamic continuation has a future solution but no "
                    "matching complete evaluation"
                )
            prior_prefix_accounting = (
                previous.planning_evaluation.dynamic_prefix_accounting_by_route_id
            )
            assets = MappingProxyType(dict(cut.asset_states))
            prior = _advance_prior_history(
                previous.planning_dynamic_state,
                active_customer_ids,
            )
            certified_history = frozenset(
                {
                    *previous.planning_dynamic_state.certified_dynamic_route_ids,
                    *cut.completed_route_ids,
                    *(
                        str(asset.in_progress_route_id)
                        for asset in cut.asset_states.values()
                        if getattr(asset, "in_progress_route_id", None) is not None
                        and getattr(asset, "continuation_route_id", None) is None
                        and not tuple(getattr(asset, "editable_suffix", ()))
                    ),
                }
            )
            timing = dict(previous.timing_by_route)
            timing.update(_timing_map(source_certificate))

        committed_route_ids = set(cut.completed_route_ids)
        history_customer_solution = (
            source_full_execution_solution or source_solution
        )
        executed_prefix_customers = _executed_history_customers(
            cut,
            history_customer_solution,
            active_customer_ids,
        )
        committed_customers = {
            customer_id
            for route in (
                *prior.routes,
                *(
                    route
                    for route in history_customer_solution.routes
                    if route.vehicle_id in committed_route_ids
                ),
            )
            for customer_id in route.node_sequence[1:-1]
            if customer_id in active_customer_ids
        }.union(executed_prefix_customers)
        dynamic_state = DutyDynamicState(
            source_solution=source_solution,
            cut=cut,
            asset_states=assets,
            future_customer_ids=frozenset(
                active_customer_ids.difference(committed_customers)
            ),
            customer_appearance_second={
                customer_id: problem.appearance_by_customer[customer_id]
                for customer_id in active_customer_ids
            },
            charging_strategy="aware",
            charging_intensity_field="forecast_gco2_per_kwh",
            inherited_evaluation_instance=inherited_evaluation_instance,
            source_full_execution_solution=source_full_execution_solution,
            prior_committed_solution=prior,
            certified_dynamic_route_ids=certified_history,
            prior_prefix_accounting_by_route_id=prior_prefix_accounting,
        )
        initial_future = future_individual_from_cut(
            dynamic_state,
            source_certificate,
            bundle.instance,
        )
        context = replace(
            problem.base_context,
            bundle=bundle,
            rebuilt_route_constraints=route_contract,
            fairness_enabled=False,
            dynamic_state=dynamic_state,
        )
        return _StageFrame(
            active_customer_ids=active_customer_ids,
            trigger_second=float(trigger_second),
            bundle=bundle,
            context=context,
            evaluator=DutyFullEvaluator(context),
            dynamic_state=dynamic_state,
            initial_future=initial_future,
            source_solution=source_solution,
            source_certificate=source_certificate,
            timing_by_route=MappingProxyType(dict(timing)),
            applied_event_ids=tuple(applied_event_ids),
        )

    def _run_hgs(
        self,
        candidate: DutyIndividual,
        context: DutyEvaluationContext,
        *,
        arm: str,
        stage_index: int,
    ) -> tuple[DutyIndividual, FullEvaluation, Any]:
        if candidate.unserved_customers:
            raise ProductionBackendHalt(
                "Problem-HGS received an incomplete candidate in "
                f"{arm}: {candidate.unserved_customers}"
            )
        evaluator = DutyFullEvaluator(context)
        init_started = _now()
        initial_evaluation = evaluator.evaluate(candidate)
        initialization_wall = _now() - init_started
        if not initial_evaluation.feasible:
            raise ProductionBackendHalt(
                f"complete candidate rejected before Problem-HGS in {arm}: "
                + "; ".join(item.detail for item in initial_evaluation.violations)
            )
        route_engine = IndependentKernelDutyRouteProposalEngine(
            context,
            candidate,
            stream_role=f"main3b_{arm}_{stage_index}",
            depot_assignment_operator_enabled=True,
            rebuilt_volume_capacity_enabled=(
                context.rebuilt_route_constraints is not None
            ),
            rebuilt_shift_neighbours_only=(
                context.rebuilt_route_constraints is not None
            ),
            shift_aware_ev_unit_cost_enabled=(
                context.rebuilt_route_constraints is not None
            ),
        )
        # 2026-08-31: four identical clones in a four-seat population made
        # SREX a permanent no-op and the stage search relied on educating the
        # same solution (measured: 6.5 core-hours with zero visible progress
        # on the full-information solve).  Adopt the validated static formal
        # recipe instead: the incumbent plan is the witness, perturbations
        # plus the standard copied-HGS population fill the remaining seats.
        parameters = _parameters(population_mode="copied_hgs_defaults")
        built = build_initial_population(
            candidate,
            evaluator=evaluator,
            charging_policy=_policy(evaluator, frvcpy_enabled=False),
            route_engine=route_engine,
            requested_size=parameters.population.min_pop_size,
            max_random_attempts=None,
            initialization_method="random",
            include_reference_candidate=True,
            require_complete_feasible=False,
            stop_requested=lambda: False,
            witness_seed=(
                candidate if not candidate.unserved_customers else None
            ),
        )
        _telemetry_last = [_now()]

        def _stage_stop(state):
            if _now() - _telemetry_last[0] >= 60.0:
                _telemetry_last[0] = _now()
                print(
                    f"STAGE {arm}#{stage_index} cycle={state.iterations} "
                    f"best={state.best_cost} "
                    f"noimp={state.iterations_without_improvement}",
                    file=sys.stderr,
                    flush=True,
                )
            return (
                state.iterations_without_improvement
                >= parameters.stagnation_patience
            )

        result = run_integrated_problem_hgs(
            tuple(built.candidates),
            evaluator=evaluator,
            charging_policy=_policy(evaluator, frvcpy_enabled=False),
            parameters=parameters,
            stop=_stage_stop,
            initial_evaluations=tuple(built.evaluations),
            initialization_full_evaluation_count=built.full_evaluation_count,
            arm=arm,
            route_engine=route_engine,
            initialization_wall_seconds=(
                initialization_wall + built.wall_seconds
            ),
            cross_depot_enabled=True,
            multi_trip_enabled=True,
            type_exchange_enabled=True,
            # 2026-08-31: same channel cut as the static formal entry --
            # 85% of incremental evaluations for 1 accept; the carbon
            # mechanism acts through the charge-timing policy.
            include_charging_candidates=False,
        )
        _require_normal_hgs_termination(result, arm=arm)
        return result.best, result.best_evaluation, result


def _require_normal_hgs_termination(result: Any, *, arm: str) -> None:
    """Turn a returned abnormal solver result into a carrier-level HALT."""

    status = getattr(result, "termination_status", None)
    if status in NORMAL_PROBLEM_HGS_TERMINATIONS:
        return
    error_type = getattr(result, "termination_error_type", None)
    error = getattr(result, "termination_error", None)
    detail = ": ".join(
        str(item) for item in (error_type, error) if item not in (None, "")
    )
    suffix = f" ({detail})" if detail else ""
    raise ProductionBackendHalt(
        f"Problem-HGS ended abnormally in {arm}: {status!r}{suffix}"
    )


def build_production_problem(
    repo: Path,
    stream_directory: Path,
    *,
    carbon_price_cny_per_kg: float | None = None,
) -> ProductionDynamicProblem:
    """Load the selected target and overlay the existing ten-event stream."""

    stream = load_c8_stream(
        stream_directory,
        expected_base_instance_id=C8_BASE_INSTANCE_ID,
    )
    bundle, initial, _pi0, context = _build_context(
        repo,
        DEPOT_SEARCH_INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )
    if carbon_price_cny_per_kg is not None:
        bundle = replace(
            bundle,
            prices=replace(
                bundle.prices,
                carbon_price=float(carbon_price_cny_per_kg),
            ),
            carbon_price_cny_per_kg=float(carbon_price_cny_per_kg),
        )
        context = replace(context, bundle=bundle)
    base_context = replace(
        context,
        fairness_enabled=False,
        dynamic_state=None,
    )
    full_bundle = overlay_c8_bundle(bundle, stream)
    initial_orders = tuple(
        ProductionOrder(
            event_id=f"initial::{node.node_id}",
            customer_id=node.node_id,
            appearance_second=0.0,
            demand_kg=float(node.demand),
            x=float(node.x),
            y=float(node.y),
            initially_visible=True,
            event_type="initial",
        )
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    )
    dynamic_orders = tuple(
        ProductionOrder(
            event_id=event.event_id,
            customer_id=event.customer_id,
            appearance_second=float(event.appearance_second),
            demand_kg=float(event.new_demand_kg),
            x=float(event.longitude),
            y=float(event.latitude),
            initially_visible=False,
            event_type=event.event_type,
            old_demand_kg=float(event.old_demand_kg),
            old_ready_second=float(event.old_ready_second),
            old_due_second=float(event.old_due_second),
            new_ready_second=float(event.new_ready_second),
            new_due_second=float(event.new_due_second),
        )
        for event in stream.events
    )
    return ProductionDynamicProblem(
        instance_id=DEPOT_SEARCH_INSTANCE_ID,
        repo=repo,
        base_bundle=bundle,
        full_bundle=full_bundle,
        base_initial=initial,
        base_context=base_context,
        c8_stream=stream,
        initial_orders=initial_orders,
        dynamic_orders=dynamic_orders,
    )


def _without_customers(
    individual: DutyIndividual,
    removed_customer_ids: Iterable[str],
) -> DutyIndividual:
    """Remove cancelled customers from an all-information starting plan."""

    removed = set(map(str, removed_customer_ids))
    duties = []
    for duty in individual.duties:
        trips = []
        index_map: dict[int, int] = {}
        for trip in duty.trips:
            customers = tuple(
                item for item in trip.customer_ids if item not in removed
            )
            visits = tuple(
                item for item in trip.effective_route_visits if item not in removed
            )
            if not customers:
                continue
            new_index = len(trips) + 1
            index_map[int(trip.trip_index)] = new_index
            trips.append(
                replace(
                    trip,
                    trip_index=new_index,
                    customer_ids=customers,
                    locked_customer_prefix=tuple(
                        item
                        for item in trip.locked_customer_prefix
                        if item not in removed
                    ),
                    route_visits=visits,
                )
            )
        sessions = tuple(
            replace(session, trip_index=index_map[int(session.trip_index)])
            for session in duty.charging_sessions
            if int(session.trip_index) in index_map
        )
        duties.append(
            replace(
                duty,
                trips=tuple(trips),
                charging_sessions=sessions,
                schedule=None,
            )
        )
    return replace(
        individual,
        duties=tuple(duties),
        unserved_customers=tuple(
            item for item in individual.unserved_customers if item not in removed
        ),
        source="paper-full-information-start",
    )


def _static_context(context: DutyEvaluationContext, bundle: Any) -> DutyEvaluationContext:
    return replace(
        context,
        bundle=bundle,
        dynamic_state=None,
        fairness_enabled=False,
    )


def _context_with_bundle(
    context: DutyEvaluationContext,
    bundle: Any,
    problem: ProductionDynamicProblem,
) -> DutyEvaluationContext:
    if context.rebuilt_route_constraints is None:
        raise ProductionBackendHalt("missing rebuilt route contract")
    contract = extend_route_contract(
        context.rebuilt_route_constraints,
        problem.c8_stream,
        {
            node.node_id
            for node in bundle.instance.nodes
            if node.node_type.lower() == "c"
        },
    )
    return replace(context, bundle=bundle, rebuilt_route_constraints=contract)


def _successful_state(
    previous: ProductionState,
    frame: _StageFrame,
    candidate: DutyIndividual,
    evaluation: FullEvaluation,
    *,
    active_customer_ids: frozenset[str],
    stage_index: int,
    diagnostics: Mapping[str, Any],
) -> ProductionState:
    if not evaluation.feasible or candidate.unserved_customers:
        raise ProductionBackendHalt(
            "successful dynamic adapter result is not a complete feasible "
            "candidate"
        )
    try:
        prepared = prepare_dynamic_candidate(
            candidate,
            frame.dynamic_state,
            frame.bundle,
            minimum_departure_second_by_customer_id=(
                {
                    customer_id: float(start)
                    for customer_id, start in _minimum_departures(frame.context).items()
                }
            ),
            shift_id_by_customer_id=(
                None
                if frame.context.rebuilt_route_constraints is None
                else frame.context.rebuilt_route_constraints.customer_shift_by_id
            ),
        )
    except (TypeError, ValueError) as error:
        raise ProductionBackendHalt(
            "existing exact dynamic scheduler could not materialize the "
            f"Problem-HGS candidate: {type(error).__name__}: {error}"
        ) from error
    timing = dict(previous.timing_by_route)
    timing.update(frame.timing_by_route)
    timing.update(_timing_map(prepared.future_certificate))
    deferred = tuple(
        item
        for item in previous.deferred_customer_ids
        if item not in active_customer_ids
    )
    route_change_evidence = _dynamic_route_change_evidence(
        frame.initial_future,
        candidate,
        frame,
    )
    return ProductionState(
        individual=candidate,
        evaluation=evaluation,
        bundle=frame.bundle,
        context=frame.context,
        active_customer_ids=active_customer_ids,
        dynamic_state=frame.dynamic_state,
        stage_index=stage_index,
        base_individual=previous.base_individual,
        static_solution=previous.static_solution,
        static_certificate=previous.static_certificate,
        planning_dynamic_state=frame.dynamic_state,
        planning_future=prepared,
        planning_evaluation=evaluation,
        planning_individual=candidate,
        planning_active_customer_ids=active_customer_ids,
        planning_trigger_second=frame.trigger_second,
        deferred_customer_ids=deferred,
        timing_by_route=timing,
        route_change_evidence=route_change_evidence,
        diagnostics=(*previous.diagnostics, dict(diagnostics)),
        mechanical_insertion_wall_seconds=(
            previous.mechanical_insertion_wall_seconds
        ),
        applied_event_ids=frame.applied_event_ids,
    )


def _deferred_state(
    previous: ProductionState,
    frame: _StageFrame,
    evaluation: FullEvaluation,
    *,
    active_customer_ids: frozenset[str],
    deferred_customer_ids: Sequence[str],
    stage_index: int,
    diagnostic: Mapping[str, Any],
    route_change_evidence: Mapping[str, Any] | None = None,
) -> ProductionState:
    timing = dict(previous.timing_by_route)
    timing.update(frame.timing_by_route)
    return ProductionState(
        individual=frame.initial_future,
        evaluation=evaluation,
        bundle=frame.bundle,
        context=frame.context,
        active_customer_ids=active_customer_ids,
        dynamic_state=frame.dynamic_state,
        stage_index=stage_index,
        base_individual=previous.base_individual,
        static_solution=previous.static_solution,
        static_certificate=previous.static_certificate,
        planning_dynamic_state=previous.planning_dynamic_state,
        planning_future=previous.planning_future,
        planning_evaluation=previous.planning_evaluation,
        planning_individual=previous.planning_individual,
        planning_active_customer_ids=previous.planning_active_customer_ids,
        planning_trigger_second=previous.planning_trigger_second,
        deferred_customer_ids=tuple(dict.fromkeys(map(str, deferred_customer_ids))),
        timing_by_route=timing,
        route_change_evidence=(
            _dynamic_route_change_evidence(
                frame.initial_future,
                frame.initial_future,
                frame,
            )
            if route_change_evidence is None
            else route_change_evidence
        ),
        diagnostics=(*previous.diagnostics, dict(diagnostic)),
        mechanical_insertion_wall_seconds=(
            previous.mechanical_insertion_wall_seconds
        ),
        applied_event_ids=frame.applied_event_ids,
    )


def _full_asset_registry(
    initial: DutyIndividual,
    cut: Any,
    bundle: Any,
) -> Mapping[str, DynamicAssetState]:
    assets = dict(cut.asset_states)
    for duty in initial.duties:
        if duty.physical_vehicle_id in assets:
            continue
        assets[duty.physical_vehicle_id] = DynamicAssetState(
            physical_vehicle_id=duty.physical_vehicle_id,
            vehicle_type=duty.vehicle_type,
            home_depot_id=duty.home_depot_id,
            available_second=float(cut.trigger_second),
            remaining_battery_kwh=(
                float(bundle.prices.initial_ev_battery_kwh)
                if duty.vehicle_type == "ev"
                else 0.0
            ),
            next_trip_index=1,
        )
    return MappingProxyType(assets)


def _executed_history_customers(
    cut: Any,
    full_source: Solution,
    active_customer_ids: frozenset[str],
) -> set[str]:
    """Recover earlier prefixes when a continuation is cut more than once."""

    route_by_id = {route.vehicle_id: route for route in full_source.routes}
    committed: set[str] = set()
    for asset in cut.asset_states.values():
        prefix = tuple(getattr(asset, "executed_prefix", ()))
        route_id = (
            getattr(asset, "continuation_route_id", None)
            or getattr(asset, "in_progress_route_id", None)
        )
        if prefix and route_id is None:
            candidates = [
                candidate
                for candidate in cut.in_progress_route_ids
                if physical_vehicle_id(candidate)
                == str(asset.physical_vehicle_id)
            ]
            if len(candidates) > 1:
                raise ProductionBackendHalt(
                    "dynamic asset has multiple in-progress source routes"
                )
            if candidates:
                route_id = candidates[0]
        executed = prefix
        if prefix and route_id in route_by_id:
            try:
                executed = full_executed_prefix(
                    route_by_id[str(route_id)],
                    prefix,
                )
            except ValueError as error:
                raise ProductionBackendHalt(
                    "dynamic continuation cannot locate its unique prior prefix"
                ) from error
        committed.update(
            str(node_id)
            for node_id in executed
            if str(node_id) in active_customer_ids
        )
    return committed


def _advance_prior_history(
    state: DutyDynamicState,
    active_customer_ids: frozenset[str] | set[str],
) -> Solution:
    prior = state.prior_committed_solution or Solution()
    # 合法取消＝跳过未执行的站：已承诺历史里被取消的客户必须同步剔除，
    # 否则每个候选重建的世界都与旧对照本不一致而被整臂拒绝。
    # 被取消客户＝上一批活跃（出现在旧状态的出现时刻表）但本批不再活跃。
    cancelled_ids = {
        str(customer_id)
        for customer_id in state.customer_appearance_second
        if str(customer_id) not in active_customer_ids
    }

    def trim(route: Route) -> Route:
        if not cancelled_ids or not any(
            node_id in cancelled_ids for node_id in route.node_sequence
        ):
            return route
        return Route(
            vehicle_id=route.vehicle_id,
            vehicle_type=route.vehicle_type,
            home_depot_id=route.home_depot_id,
            node_sequence=[
                node_id
                for node_id in route.node_sequence
                if node_id not in cancelled_ids
            ],
        )

    committed_ids = {
        *state.cut.completed_route_ids,
        *(
            str(asset.in_progress_route_id)
            for asset in state.asset_states.values()
            if getattr(asset, "in_progress_route_id", None) is not None
            and getattr(asset, "continuation_route_id", None) is None
            and not tuple(getattr(asset, "editable_suffix", ()))
        ),
    }
    routes = {route.vehicle_id: trim(route) for route in prior.routes}
    history_source = (
        state.source_full_execution_solution or state.source_solution
    )
    for route in history_source.routes:
        if route.vehicle_id not in committed_ids:
            continue
        route = trim(route)
        old = routes.get(route.vehicle_id)
        if old is not None and old != route:
            raise ProductionBackendHalt("committed route history changed between cuts")
        routes[route.vehicle_id] = route
    actions: dict[tuple[Any, ...], ChargingAction] = {}
    for action in (*prior.charging_actions, *state.cut.locked_charging_actions):
        if action.vehicle_id not in routes:
            continue
        key = (
            action.vehicle_id,
            action.station_id,
            float(action.charge_start_second),
            float(action.energy_kwh),
        )
        old = actions.get(key)
        if old is not None and old != action:
            raise ProductionBackendHalt("committed charging history changed")
        actions[key] = action
    return Solution(
        routes=[routes[key] for key in sorted(routes)],
        charging_actions=[actions[key] for key in sorted(actions, key=str)],
    )


def _served_customers(solution: Solution, bundle: Any) -> frozenset[str]:
    customer_ids = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    return frozenset(
        node_id
        for route in solution.routes
        for node_id in route.node_sequence[1:-1]
        if node_id in customer_ids
    )


def _dynamic_route_change_evidence(
    before: DutyIndividual,
    after: DutyIndividual,
    frame: _StageFrame,
) -> Mapping[str, Any]:
    """Count route edits without turning the statistic into a search rule."""

    old_customers = {
        customer_id
        for duty in before.duties
        for trip in duty.trips
        for customer_id in trip.customer_ids
    }
    before_arcs = _old_customer_arcs(before, old_customers)
    after_arcs = _old_customer_arcs(after, old_customers)
    removed_arcs = tuple(sorted(before_arcs.difference(after_arcs)))
    before_assignment = _customer_vehicle_assignment(before, old_customers)
    after_assignment = _customer_vehicle_assignment(after, old_customers)
    changed_customers = tuple(
        sorted(
            customer_id
            for customer_id in old_customers
            if before_assignment.get(customer_id)
            != after_assignment.get(customer_id)
        )
    )
    changed_vehicles = tuple(
        sorted(
            {
                vehicle_id
                for customer_id in changed_customers
                for vehicle_id in (
                    before_assignment.get(customer_id),
                    after_assignment.get(customer_id),
                )
                if vehicle_id is not None
            }
        )
    )
    cut = frame.dynamic_state.cut
    states = [
        asdict(state)
        for _, state in sorted(cut.asset_states.items())
        if getattr(state, "continuation_route_id", None) is not None
    ]
    frozen_prefixes = {
        str(route_id): [list(arc) for arc in arcs]
        for route_id, arcs in sorted(
            getattr(cut, "frozen_arc_prefix_by_route_id", {}).items()
        )
        if arcs
    }
    return MappingProxyType(
        {
            "route_snapshot_before_json": _route_snapshot_json(
                before,
                frame,
                new_customer_ids=before.unserved_customers,
            ),
            "route_snapshot_after_json": _route_snapshot_json(
                after,
                frame,
                new_customer_ids=before.unserved_customers,
            ),
            "old_unexecuted_arc_count_before": len(before_arcs),
            "changed_old_old_unexecuted_arc_count": len(removed_arcs),
            "changed_old_old_unexecuted_arc_ids_json": json.dumps(
                [list(arc) for arc in removed_arcs],
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            ),
            "old_customer_count": len(old_customers),
            "old_customers_changed_vehicle_count": len(changed_customers),
            "old_customers_changed_vehicle_ids_json": json.dumps(
                list(changed_customers),
                ensure_ascii=False,
                allow_nan=False,
            ),
            "vehicles_with_old_customer_changes_count": len(changed_vehicles),
            "vehicles_with_old_customer_changes_ids_json": json.dumps(
                list(changed_vehicles),
                ensure_ascii=False,
                allow_nan=False,
            ),
            "dynamic_vehicle_states_json": json.dumps(
                states,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            ),
            "frozen_prefixes_json": json.dumps(
                frozen_prefixes,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            ),
        }
    )


def _old_customer_arcs(
    individual: DutyIndividual,
    old_customers: set[str],
) -> set[tuple[str, str]]:
    return {
        (left, right)
        for duty in individual.duties
        for trip in duty.trips
        for left, right in zip(
            trip.effective_route_visits,
            trip.effective_route_visits[1:],
        )
        if left in old_customers and right in old_customers
    }


def _customer_vehicle_assignment(
    individual: DutyIndividual,
    customer_ids: set[str],
) -> dict[str, str]:
    return {
        customer_id: duty.physical_vehicle_id
        for duty in individual.duties
        for trip in duty.trips
        for customer_id in trip.customer_ids
        if customer_id in customer_ids
    }


def _route_snapshot_json(
    individual: DutyIndividual,
    frame: _StageFrame,
    *,
    new_customer_ids: Sequence[str],
) -> str:
    cut = frame.dynamic_state.cut
    frozen_by_route = getattr(cut, "frozen_arc_prefix_by_route_id", {})
    frozen_by_asset: dict[str, list[tuple[str, str]]] = {}
    for route_id, arcs in frozen_by_route.items():
        frozen_by_asset.setdefault(physical_vehicle_id(str(route_id)), []).extend(
            (str(left), str(right)) for left, right in arcs
        )
    new_ids = set(map(str, new_customer_ids))
    routes: list[dict[str, Any]] = []
    represented_assets: set[str] = set()
    for duty in individual.duties:
        asset_state = cut.asset_states.get(duty.physical_vehicle_id)
        virtual_origin = (
            None
            if asset_state is None
            else getattr(asset_state, "virtual_origin_node_id", None)
        )
        for position, trip in enumerate(duty.trips):
            visits = list(map(str, trip.effective_route_visits))
            start = duty.home_depot_id
            virtual_ids: list[str] = []
            if position == 0 and virtual_origin:
                start = str(virtual_origin)
                virtual_ids.append(start)
            if visits and visits[0] == start:
                sequence = [*visits, duty.home_depot_id]
            else:
                sequence = [start, *visits, duty.home_depot_id]
            unexecuted_arcs = [
                [left, right]
                for left, right in zip(sequence, sequence[1:])
            ]
            frozen_arcs = (
                frozen_by_asset.get(duty.physical_vehicle_id, [])
                if position == 0
                else []
            )
            routes.append(
                {
                    "physical_vehicle_id": duty.physical_vehicle_id,
                    "route_id": duty.route_id(trip.trip_index),
                    "node_sequence": sequence,
                    "frozen_arcs": [list(arc) for arc in frozen_arcs],
                    "unexecuted_arcs": unexecuted_arcs,
                    "virtual_origin_node_ids": virtual_ids,
                    "new_customer_ids": [
                        node_id for node_id in sequence if node_id in new_ids
                    ],
                }
            )
            represented_assets.add(duty.physical_vehicle_id)
    for asset_id, arcs in sorted(frozen_by_asset.items()):
        if asset_id in represented_assets:
            continue
        asset_state = cut.asset_states.get(asset_id)
        virtual_origin = (
            None
            if asset_state is None
            else getattr(asset_state, "virtual_origin_node_id", None)
        )
        home_depot = (
            None
            if asset_state is None
            else asset_state.home_depot_id
        )
        continuation_sequence = (
            [str(virtual_origin), str(home_depot)]
            if virtual_origin and home_depot
            else []
        )
        routes.append(
            {
                "physical_vehicle_id": asset_id,
                "route_id": (
                    getattr(asset_state, "continuation_route_id", None)
                    or "frozen-prefix-only"
                ),
                "node_sequence": continuation_sequence,
                "frozen_arcs": [list(arc) for arc in arcs],
                "unexecuted_arcs": (
                    [continuation_sequence]
                    if continuation_sequence
                    else []
                ),
                "virtual_origin_node_ids": (
                    [str(virtual_origin)] if virtual_origin else []
                ),
                "new_customer_ids": [],
            }
        )
    coordinates = {
        str(node.node_id): [float(node.x), float(node.y)]
        for node in frame.bundle.instance.nodes
    }
    for state in cut.asset_states.values():
        virtual_id = getattr(state, "virtual_origin_node_id", None)
        release_id = getattr(state, "release_node_id", None)
        if virtual_id and release_id in coordinates:
            coordinates[str(virtual_id)] = list(coordinates[str(release_id)])
    return json.dumps(
        {
            "routes": routes,
            "coordinates": coordinates,
        },
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )


def _details(
    state: ProductionState,
    evaluation: FullEvaluation,
    bundle: Any,
    served: frozenset[str],
    active: set[str],
    demand: Mapping[str, float],
    *,
    dynamic_customer_ids: frozenset[str],
) -> Mapping[str, Any]:
    route_by_customer: dict[str, Route] = {}
    for route in evaluation.prepared_solution.routes:
        for customer_id in route.node_sequence[1:-1]:
            route_by_customer[customer_id] = route
    all_cross_cases = []
    revealed_dynamic_ids = set(active).intersection(dynamic_customer_ids)
    served_dynamic_ids = served.intersection(revealed_dynamic_ids)
    for customer_id in sorted(served_dynamic_ids):
        route = route_by_customer.get(customer_id)
        original = bundle.customer_home_depot.get(customer_id)
        if route is None or original is None:
            continue
        if str(route.home_depot_id) != str(original):
            all_cross_cases.append(
                {
                    "customer_id": customer_id,
                    "original_depot_id": str(original),
                    "serving_depot_id": str(route.home_depot_id),
                    "vehicle_id": physical_vehicle_id(route.vehicle_id),
                    "route_id": route.vehicle_id,
                    "demand_kg": float(demand.get(customer_id, 0.0)),
                }
            )
    cross_cases = all_cross_cases[:5]
    route_types = {
        physical_vehicle_id(route.vehicle_id): str(route.vehicle_type).lower()
        for route in evaluation.prepared_solution.routes
    }
    charge_times = [
        {
            "vehicle_id": action.vehicle_id,
            "station_id": action.station_id,
            "charge_start_second": float(action.charge_start_second),
            "charge_day_offset": int(action.charge_day_offset),
            "energy_kwh": float(action.energy_kwh),
        }
        for action in evaluation.prepared_solution.charging_actions
    ]
    fallback_rows = list(state.diagnostics)
    return {
        "cumulative_total_cost_cny": float(evaluation.total_cost),
        "cumulative_emissions_kg": float(
            evaluation.breakdown.get("E_total", 0.0)
        ),
        "cumulative_customers_served": len(served.intersection(active)),
        "cumulative_demand_served_kg": sum(
            float(demand[item]) for item in served.intersection(active)
        ),
        "defer_triggered": bool(state.deferred_customer_ids),
        "defer_count": len(state.deferred_customer_ids),
        "defer_customer_ids": "|".join(state.deferred_customer_ids),
        "fallback_diagnostics_json": json.dumps(
            fallback_rows,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        ),
        "cross_depot_served_count": len(all_cross_cases),
        "cross_depot_served_ratio": (
            len(all_cross_cases) / len(revealed_dynamic_ids)
            if revealed_dynamic_ids
            else 0.0
        ),
        "cross_depot_cases_json": json.dumps(
            cross_cases,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        ),
        "enterprise_profit_json": json.dumps(
            dict(evaluation.depot_profit),
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        ),
        "participation_margin_json": json.dumps(
            dict(evaluation.participation_margin),
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        ),
        "fairness_status": (
            "WIRED"
            if state.context.fairness_enabled
            else "NOT_WIRED_FAIRNESS_NOT_IN_DYNAMIC_DECISION"
        ),
        "ev_route_count": sum(value == "ev" for value in route_types.values()),
        "cv_route_count": sum(value == "cv" for value in route_types.values()),
        "charging_action_count": len(charge_times),
        "charging_times_json": json.dumps(
            charge_times,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        ),
        "charging_emissions_kg": float(
            evaluation.breakdown.get("E_ev_indirect", 0.0)
        ),
        "total_distance_km": float(
            evaluation.breakdown.get("distance_total", 0.0)
        )
        / 1_000.0,
        "fuel_direct_emissions_kg": float(
            evaluation.breakdown.get("E_cv_direct", 0.0)
        ),
        "charging_indirect_emissions_kg": float(
            evaluation.breakdown.get("E_ev_indirect", 0.0)
        ),
        "candidate_stage_count": len(state.diagnostics),
        "actual_hgs_call_count": sum(
            row.get("kind") == "problem_hgs_stage"
            for row in state.diagnostics
        ),
        "mechanical_insertion_count": sum(
            row.get("kind") == "mechanical_insertion"
            for row in state.diagnostics
        ),
        "mechanical_insertion_actual_wall_clock_seconds": float(
            state.mechanical_insertion_wall_seconds
        ),
        **dict(state.route_change_evidence),
    }


def _timing_map(certificate: Any) -> dict[str, Any]:
    return {
        trip.route_id: trip
        for trip in getattr(certificate, "trips", ())
    }


def _minimum_departures(context: DutyEvaluationContext) -> Mapping[str, float]:
    contract = context.rebuilt_route_constraints
    if contract is None:
        return {}
    return {
        customer_id: float(contract.shift_window_second_by_id[shift_id][0])
        for customer_id, shift_id in contract.customer_shift_by_id.items()
    }


def _payload_capacity(bundle: Any, vehicle_type: str) -> float | None:
    parameters = bundle.instance.vehicle_parameters
    if parameters is None:
        return None
    profile = parameters.get(str(vehicle_type).lower())
    if profile is None:
        return None
    value = getattr(profile, "payload_capacity_kg", None)
    return None if value is None else float(value)


def _validate_active(
    problem: ProductionDynamicProblem,
    active_customer_ids: Iterable[str],
) -> None:
    active = set(map(str, active_customer_ids))
    known = set(problem.static_customer_ids).union(problem.dynamic_customer_ids)
    if not active.issubset(known):
        raise ProductionBackendHalt(
            "dynamic information contains an unknown customer: "
            + ", ".join(sorted(active.difference(known)))
        )


def _now() -> float:
    from time import perf_counter

    return perf_counter()
