"""Incremental insertion of newly revealed orders into an exact dynamic cut.

The route skeleton is changed by the copied HGS local-search kernel.  Missing
required clients are inserted by its cached ``insertCost`` path before one
finite local-search descent.  Complete Duty evaluation remains the sole
acceptance authority.  Optional standby charging is planned on a separately
supplied public scenario; this module performs no file I/O and has no oracle
input.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from time import perf_counter

from setp_solver.solution import ChargingAction, physical_vehicle_id

from .charging import ChargingRepairPolicy, repair_changed_duties
from .contracts import CandidateStatus
from .education import evaluate_move
from .evaluation import DutyFullEvaluator, FullEvaluation
from .kernel_proposals import IndependentKernelDutyRouteProposalEngine
from .model import DutyIndividual
from .operators import DutySkeletonMove
from .proposals import MechanismProposalEngine


class DynamicInsertionFailure(RuntimeError):
    """The incremental kernel did not produce a complete feasible suffix."""


@dataclass(frozen=True)
class PublicStandbyScenario:
    """In-memory, public-only future scenario used by the P34 decision.

    The caller is responsible for constructing ``context`` and
    ``initial_future`` from the five files named by the public 08:00 manifest.
    Exact accepted names are recorded here so an event controller cannot pass
    an oracle artifact through a generic path parameter.
    """

    context: object
    initial_future: DutyIndividual
    source_artifacts: tuple[str, ...]
    decision_horizon_second: float

    def __post_init__(self) -> None:
        normalized = tuple(
            str(name).replace("\\", "/").lstrip("./")
            for name in self.source_artifacts
        )
        if not normalized:
            raise ValueError("standby scenario must identify its public inputs")
        allowed_exact = {
            "public/algorithm_visible_at_0800.json",
            "public/algorithm_scenario_trigger_batches.csv",
            "public/initial_orders_at_0800.csv",
            "public/order_attribute_prior.csv",
            "public/potential_pool.csv",
        }
        for name in normalized:
            allowed = name in allowed_exact or (
                name.startswith("public/algorithm_scenario_seed_")
                and name.endswith(".csv")
            )
            if not allowed:
                raise ValueError(
                    "standby scenario accepts only artifacts declared by the "
                    "public 08:00 manifest"
                )
        if "public/algorithm_visible_at_0800.json" not in normalized:
            raise ValueError("standby scenario is missing the public manifest")
        if not any(
            name.startswith("public/algorithm_scenario_seed_")
            for name in normalized
        ):
            raise ValueError("standby scenario is missing its independent sample")
        state = getattr(self.context, "dynamic_state", None)
        if state is None:
            raise ValueError("standby scenario requires an exact dynamic state")
        if float(self.decision_horizon_second) < float(
            state.cut.trigger_second
        ):
            raise ValueError("standby decision horizon precedes its trigger")
        object.__setattr__(self, "source_artifacts", normalized)


@dataclass(frozen=True)
class StandbyChargingDecision:
    """P34 choice for assets idle in the actually visible solution."""

    charging_actions: tuple[ChargingAction, ...]
    no_charge_selected: bool
    scenario_evaluation: FullEvaluation
    source_artifacts: tuple[str, ...]
    decision_horizon_second: float


@dataclass(frozen=True)
class DynamicInsertionAccounting:
    wall_seconds: float
    newly_revealed_count: int
    kernel_updates: int
    kernel_moves: int
    kernel_improving_moves: int
    changed_duty_count: int
    complete_evaluations: int
    charging_candidates_evaluated: int
    committed_sha256_before: str
    committed_sha256_after: str


@dataclass(frozen=True)
class DynamicInsertionResult:
    individual: DutyIndividual
    evaluation: FullEvaluation | None
    accounting: DynamicInsertionAccounting
    standby: StandbyChargingDecision | None = None


class DynamicInsertionOperator:
    """Insert one revealed batch and re-optimise only the editable suffix."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        random_seed: int = 1,
    ) -> None:
        self.enabled = bool(enabled)
        self.random_seed = int(random_seed)

    def apply(
        self,
        initial_future: DutyIndividual,
        *,
        evaluator: DutyFullEvaluator,
        charging_policy: ChargingRepairPolicy,
        newly_revealed_customer_ids: tuple[str, ...],
        standby_scenario: PublicStandbyScenario | None = None,
        current_evaluation: FullEvaluation | None = None,
    ) -> DynamicInsertionResult:
        """Return the no-op exactly when disabled, otherwise one sealed result."""

        started = perf_counter()
        before_sha = _committed_sha256(evaluator)
        if not self.enabled:
            return DynamicInsertionResult(
                individual=initial_future,
                evaluation=current_evaluation,
                accounting=DynamicInsertionAccounting(
                    wall_seconds=perf_counter() - started,
                    newly_revealed_count=0,
                    kernel_updates=0,
                    kernel_moves=0,
                    kernel_improving_moves=0,
                    changed_duty_count=0,
                    complete_evaluations=0,
                    charging_candidates_evaluated=0,
                    committed_sha256_before=before_sha,
                    committed_sha256_after=before_sha,
                ),
            )

        actual, accounting = self._apply_enabled(
            initial_future,
            evaluator=evaluator,
            charging_policy=charging_policy,
            newly_revealed_customer_ids=newly_revealed_customer_ids,
            stream_role="dynamic_revealed_insertion",
        )
        standby = None
        if standby_scenario is not None:
            scenario_evaluator = DutyFullEvaluator(standby_scenario.context)
            scenario_new = tuple(standby_scenario.initial_future.unserved_customers)
            scenario, _scenario_accounting = self._apply_enabled(
                standby_scenario.initial_future,
                evaluator=scenario_evaluator,
                charging_policy=charging_policy,
                newly_revealed_customer_ids=scenario_new,
                stream_role="p34_public_standby_scenario",
            )
            assert scenario.evaluation is not None
            idle_ev_ids = {
                duty.physical_vehicle_id
                for duty in actual.individual.duties
                if duty.vehicle_type == "ev" and not duty.trips
            }
            trigger = float(
                standby_scenario.context.dynamic_state.cut.trigger_second
            )
            horizon = float(standby_scenario.decision_horizon_second)
            actions = tuple(
                action
                for action in scenario.evaluation.prepared_solution.charging_actions
                if physical_vehicle_id(action.vehicle_id) in idle_ev_ids
                and trigger - 1.0e-9
                <= float(action.charge_start_second)
                <= horizon + 1.0e-9
            )
            standby = StandbyChargingDecision(
                charging_actions=actions,
                no_charge_selected=not actions,
                scenario_evaluation=scenario.evaluation,
                source_artifacts=standby_scenario.source_artifacts,
                decision_horizon_second=horizon,
            )
        return DynamicInsertionResult(
            individual=actual.individual,
            evaluation=actual.evaluation,
            accounting=DynamicInsertionAccounting(
                **{
                    **asdict(accounting),
                    "wall_seconds": perf_counter() - started,
                }
            ),
            standby=standby,
        )

    def _apply_enabled(
        self,
        initial_future: DutyIndividual,
        *,
        evaluator: DutyFullEvaluator,
        charging_policy: ChargingRepairPolicy,
        newly_revealed_customer_ids: tuple[str, ...],
        stream_role: str,
    ) -> tuple[DynamicInsertionResult, DynamicInsertionAccounting]:
        started = perf_counter()
        state = evaluator.context.dynamic_state
        if state is None:
            raise ValueError("dynamic insertion requires an exact dynamic state")
        revealed = tuple(dict.fromkeys(map(str, newly_revealed_customer_ids)))
        if len(revealed) != len(newly_revealed_customer_ids):
            raise ValueError("newly revealed customer ids must be unique")
        missing_from_unserved = set(revealed).difference(
            initial_future.unserved_customers
        )
        if missing_from_unserved:
            raise ValueError(
                "newly revealed customers must enter as explicit unserved ids: "
                + ", ".join(sorted(missing_from_unserved))
            )
        appearances = state.customer_appearance_second
        trigger = float(state.cut.trigger_second)
        if any(
            customer_id not in appearances
            or float(appearances[customer_id]) > trigger + 1.0e-9
            for customer_id in revealed
        ):
            raise ValueError("dynamic insertion received an unrevealed customer")

        before_calls = evaluator.full_calls
        before_sha = _committed_sha256(evaluator)
        engine = IndependentKernelDutyRouteProposalEngine(
            evaluator.context,
            initial_future,
            random_seed=self.random_seed,
            stream_role=stream_role,
            rebuilt_volume_capacity_enabled=(
                evaluator.context.rebuilt_route_constraints is not None
            ),
            rebuilt_shift_neighbours_only=(
                evaluator.context.rebuilt_route_constraints is not None
            ),
        )
        warm = engine.project(initial_future)
        inserted = engine.local_search.repair_required(
            warm,
            engine.penalty_manager.booster_cost_evaluator(),
        )
        insertion_statistics = engine.local_search.statistics

        def materialize(
            native_solution,
        ) -> tuple[DutyIndividual, int]:
            native_replacements = engine.decode_replacements(
                initial_future,
                native_solution,
            )
            if not native_replacements:
                return initial_future, 0
            move = DutySkeletonMove(
                action_id=(
                    "dynamic-insertion:"
                    + hashlib.sha256(
                        repr(native_replacements).encode()
                    ).hexdigest()[:16]
                ),
                channel="dynamic_revealed_insertion",
                replacements=native_replacements,
                dynamic_future_only=True,
            )
            raw = move.apply(initial_future)
            repaired = repair_changed_duties(
                initial_future,
                raw,
                changed_duty_ids=set(move.changed_duty_ids),
                context=evaluator.context,
                policy=charging_policy,
            )
            return repaired, len(move.changed_duty_ids)

        candidate, changed_duties = materialize(inserted)
        still_unserved = set(revealed).intersection(candidate.unserved_customers)
        if still_unserved:
            raise DynamicInsertionFailure(
                "incremental kernel did not insert revealed customers: "
                + ", ".join(sorted(still_unserved))
            )
        evaluation = evaluator.evaluate(candidate)
        if not evaluation.feasible:
            raise DynamicInsertionFailure(
                "inserted suffix failed complete evaluation: "
                + "; ".join(
                    f"{violation.type}:{violation.detail}"
                    for violation in evaluation.violations
                )
            )

        # One bounded descent is allowed after the mandatory insertion.  It is
        # retained only when the complete ruler accepts it; the insertion-only
        # witness remains the fail-safe candidate.
        improved = engine.local_search(
            inserted,
            engine.penalty_manager.booster_cost_evaluator(),
        )
        reoptimization_statistics = engine.local_search.statistics
        try:
            reoptimized, reoptimized_changed = materialize(improved)
            reoptimized_evaluation = evaluator.evaluate(reoptimized)
        except (TypeError, ValueError):
            reoptimized_evaluation = None
        if (
            reoptimized_evaluation is not None
            and reoptimized_evaluation.feasible
            and float(reoptimized_evaluation.total_cost)
            < float(evaluation.total_cost) - 1.0e-9
        ):
            candidate = reoptimized
            evaluation = reoptimized_evaluation
            changed_duties = reoptimized_changed

        candidate, evaluation, charging_evaluated = _refine_charging_once(
            candidate,
            evaluation,
            evaluator=evaluator,
            charging_policy=charging_policy,
        )
        after_sha = _committed_sha256(evaluator, evaluation=evaluation)
        if before_sha != after_sha:
            raise DynamicInsertionFailure("dynamic insertion changed committed history")
        accounting = DynamicInsertionAccounting(
            wall_seconds=perf_counter() - started,
            newly_revealed_count=len(revealed),
            kernel_updates=(
                int(insertion_statistics.num_updates)
                + int(reoptimization_statistics.num_updates)
            ),
            kernel_moves=(
                int(insertion_statistics.num_moves)
                + int(reoptimization_statistics.num_moves)
            ),
            kernel_improving_moves=(
                int(insertion_statistics.num_improving)
                + int(reoptimization_statistics.num_improving)
            ),
            changed_duty_count=changed_duties,
            complete_evaluations=evaluator.full_calls - before_calls,
            charging_candidates_evaluated=charging_evaluated,
            committed_sha256_before=before_sha,
            committed_sha256_after=after_sha,
        )
        return (
            DynamicInsertionResult(candidate, evaluation, accounting),
            accounting,
        )


def _refine_charging_once(
    incumbent: DutyIndividual,
    incumbent_evaluation: FullEvaluation,
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
) -> tuple[DutyIndividual, FullEvaluation, int]:
    """Compare no-change with every P34 route/time/amount/site candidate once."""

    engine = MechanismProposalEngine(
        evaluator.context,
        charging_policy,
        include_charging_candidates=True,
        include_non_charging_candidates=False,
    )
    best = incumbent
    best_evaluation = incumbent_evaluation
    evaluated = 0
    for move in engine.propose(
        incumbent,
        incumbent_evaluation,
        evaluator.context.bundle.instance,
        include_whole_duty_type_exchange=False,
    ):
        outcome = evaluate_move(
            incumbent,
            move,
            evaluator=evaluator,
            charging_policy=charging_policy,
            verify_full_truth=False,
            penalized_cost=lambda result: float(result.total_cost),
        )
        if outcome.status != CandidateStatus.EVALUATED:
            continue
        assert outcome.candidate is not None and outcome.evaluation is not None
        evaluated += 1
        if (
            outcome.evaluation.feasible
            and float(outcome.evaluation.total_cost)
            < float(best_evaluation.total_cost) - 1.0e-9
        ):
            best = outcome.candidate
            best_evaluation = outcome.evaluation
    return best, best_evaluation, evaluated


def _committed_sha256(
    evaluator: DutyFullEvaluator,
    *,
    evaluation: FullEvaluation | None = None,
) -> str:
    state = evaluator.context.dynamic_state
    if state is None:
        return hashlib.sha256(b"static-no-commitment").hexdigest()
    committed_ids = {
        *state.cut.completed_route_ids,
        *state.cut.in_progress_route_ids,
        *(route.vehicle_id for route in state.prior_committed_solution.routes),
    }
    source = (
        evaluation.prepared_solution
        if evaluation is not None
        else state.prior_committed_solution
    )
    routes = []
    actions = []
    if evaluation is None:
        source_routes = (
            *state.prior_committed_solution.routes,
            *(
                route
                for route in state.source_solution.routes
                if route.vehicle_id in committed_ids
            ),
        )
        source_actions = (
            *state.prior_committed_solution.charging_actions,
            *state.cut.locked_charging_actions,
        )
    else:
        source_routes = tuple(
            route for route in source.routes if route.vehicle_id in committed_ids
        )
        source_actions = tuple(
            action
            for action in source.charging_actions
            if action.vehicle_id in committed_ids
        )
    routes.extend(asdict(route) for route in source_routes)
    actions.extend(asdict(action) for action in source_actions)
    payload = {
        "routes": sorted(routes, key=lambda row: row["vehicle_id"]),
        "charging_actions": sorted(
            actions,
            key=lambda row: (
                row["vehicle_id"],
                row["charge_day_offset"],
                row["charge_start_second"],
                row["station_id"],
            ),
        ),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
