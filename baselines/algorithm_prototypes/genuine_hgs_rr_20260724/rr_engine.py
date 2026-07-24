"""Independent mechanism-aware ruin-and-recreate arm (algorithm B)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import random
from time import perf_counter
from typing import Any

from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import annotate_cross_site_services
from setp_solver.solution import Route, Solution
from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging,
)
from setp_solver.algorithms.resetp_alns.operators.strong_bridge import (
    solution_signature_hash,
)

from contracts import CandidateSource, CompleteEvaluationLedger
from decoder_cache import RouteLocalDecoderCache
from evaluation import BudgetedCompleteEvaluator
from fleet_assignment_dp import (
    NoFeasibleAssignmentError,
    decode_assignment_shortlist,
)
from operator_plans import (
    DestroyPlan,
    OperatorKind,
    bidirectional_cross_depot_segment_plan,
    charge_departure_retiming_plan,
    cross_depot_route_reassignment_plan,
    time_window_pressure_string_plan,
    vehicle_type_flip_plan,
)
from operator_effects import OperatorEffect, verify_operator_effect
from recreate import (
    NoReconstructionInsertionError,
    recreate_removed_customers,
    remove_customers_from_skeleton,
)


@dataclass(frozen=True)
class RrConfig:
    assignment_beam_per_state: int = 2
    assignment_shortlist_size: int = 3
    max_segment_length: int = 4
    time_window_candidate_pool: int = 8
    cross_depot_pair_pool: int = 12
    start_worsening_fraction: float = 0.01
    start_acceptance_probability: float = 0.50
    end_worsening_fraction: float = 0.001
    end_acceptance_probability: float = 0.01
    wallclock_safety_seconds: float = 600.0

    def __post_init__(self) -> None:
        if self.assignment_beam_per_state < 1:
            raise ValueError("assignment DP beam must be positive")
        if self.assignment_shortlist_size < 1:
            raise ValueError("assignment shortlist must be positive")
        if self.max_segment_length < 1:
            raise ValueError("segment length must be positive")
        if self.time_window_candidate_pool < 1 or self.cross_depot_pair_pool < 1:
            raise ValueError("result-blind candidate pools must be positive")
        for value in (
            self.start_acceptance_probability,
            self.end_acceptance_probability,
        ):
            if not 0.0 < value < 1.0:
                raise ValueError("acceptance probabilities must be in (0, 1)")
        if (
            self.start_worsening_fraction <= 0.0
            or self.end_worsening_fraction <= 0.0
            or self.wallclock_safety_seconds <= 0.0
        ):
            raise ValueError("worsening fractions and safety cap must be positive")


@dataclass(frozen=True)
class RrTraceRow:
    iteration: int
    operator: str
    evaluations_before: int
    evaluations_after: int
    candidate_signature: str | None
    candidate_objective: float | None
    candidate_feasible: bool
    operator_effect_passed: bool
    accepted: bool
    improved_best: bool
    current_objective: float
    best_objective: float
    temperature: float
    detail: str


@dataclass(frozen=True)
class RrRunResult:
    best_solution: Solution
    best_objective: float
    current_solution: Solution
    current_objective: float
    best_generated_solution: Solution | None
    best_generated_objective: float | None
    best_generated_record_index: int | None
    trace: tuple[RrTraceRow, ...]
    elapsed_seconds: float
    stop_reason: str
    operator_attempts: dict[str, int]
    operator_accepted: dict[str, int]
    operator_best_improvements: dict[str, int]
    route_local_cache_stats: dict[str, int | float]


@dataclass(frozen=True)
class _CandidateProposal:
    solution: Solution
    objective: float
    record_index: int
    effect: OperatorEffect


def run_mechanism_aware_rr(
    bundle: China81Bundle,
    initial_solution: Solution,
    *,
    initial_objective: float,
    seed: int,
    ledger: CompleteEvaluationLedger,
    config: RrConfig = RrConfig(),
    max_additional_evaluations: int | None = None,
    route_local_cache: RouteLocalDecoderCache | None = None,
) -> RrRunResult:
    """Run independent B without any HGS population, crossover, or MIP."""

    if not math.isfinite(float(initial_objective)):
        raise ValueError("initial objective must be finite")
    additional_limit = (
        ledger.remaining
        if max_additional_evaluations is None
        else int(max_additional_evaluations)
    )
    if additional_limit < 1:
        raise ValueError("RR phase requires a positive evaluation allowance")
    phase_start = ledger.consumed
    phase_stop = min(
        ledger.limit,
        phase_start + additional_limit,
    )
    rng = random.Random(int(seed))
    evaluator = BudgetedCompleteEvaluator(
        bundle=bundle,
        ledger=ledger,
    )
    local_cache = (
        route_local_cache if route_local_cache is not None else RouteLocalDecoderCache()
    )
    current = initial_solution
    current_objective = float(initial_objective)
    best = initial_solution
    best_objective = float(initial_objective)
    best_generated_solution: Solution | None = None
    best_generated_objective: float | None = None
    best_generated_record_index: int | None = None
    trace: list[RrTraceRow] = []
    attempts: dict[str, int] = {}
    accepted_counts: dict[str, int] = {}
    improvement_counts: dict[str, int] = {}
    started = perf_counter()
    iteration = 0
    operator_order = (
        OperatorKind.TIME_WINDOW_PRESSURE_STRING,
        OperatorKind.BIDIRECTIONAL_CROSS_DEPOT_SEGMENT,
        OperatorKind.CROSS_DEPOT_ROUTE_REASSIGNMENT,
        OperatorKind.VEHICLE_TYPE_FLIP,
        OperatorKind.CHARGE_DEPARTURE_RETIMING,
    )
    stop_reason = "COMPLETE_EVALUATION_BUDGET"
    while ledger.remaining > 0 and ledger.consumed < phase_stop:
        if perf_counter() - started >= config.wallclock_safety_seconds:
            stop_reason = "WALLCLOCK_SAFETY_CAP"
            break
        iteration += 1
        before = ledger.consumed
        temperature = _temperature(
            initial_objective=float(initial_objective),
            consumed=ledger.consumed - phase_start,
            limit=max(1, phase_stop - phase_start),
            config=config,
        )
        candidate = None
        skipped_nonapplicable: list[str] = []
        start_index = (iteration - 1 + int(seed)) % len(operator_order)
        for offset in range(len(operator_order)):
            operator = operator_order[(start_index + offset) % len(operator_order)]
            operator_name = operator.value
            attempts[operator_name] = attempts.get(operator_name, 0) + 1
            attempt_before = ledger.consumed
            candidate = _propose_candidate(
                current,
                bundle,
                operator=operator,
                rng=rng,
                evaluator=evaluator,
                config=config,
                iteration=iteration,
                evaluation_allowance=(phase_stop - ledger.consumed),
                route_local_cache=local_cache,
            )
            if candidate is not None:
                break
            skipped_nonapplicable.append(operator_name)
            if ledger.consumed > attempt_before:
                break
        if candidate is None:
            trace.append(
                RrTraceRow(
                    iteration=iteration,
                    operator=operator_name,
                    evaluations_before=before,
                    evaluations_after=ledger.consumed,
                    candidate_signature=None,
                    candidate_objective=None,
                    candidate_feasible=False,
                    operator_effect_passed=False,
                    accepted=False,
                    improved_best=False,
                    current_objective=current_objective,
                    best_objective=best_objective,
                    temperature=temperature,
                    detail=(
                        "no_feasible_candidate;attempted="
                        + ",".join(skipped_nonapplicable)
                    ),
                )
            )
            if ledger.consumed == before:
                stop_reason = "NO_APPLICABLE_OPERATOR"
                break
            continue
        candidate_solution = candidate.solution
        candidate_objective = candidate.objective
        delta = candidate_objective - current_objective
        accepted = candidate.effect.passed and _accept_candidate(
            delta=delta,
            temperature=temperature,
            rng=rng,
        )
        improved_best = (
            candidate.effect.passed and candidate_objective < best_objective - 1.0e-9
        )
        if accepted and (
            best_generated_objective is None
            or candidate_objective < best_generated_objective - 1.0e-9
        ):
            best_generated_solution = candidate_solution
            best_generated_objective = candidate_objective
            best_generated_record_index = candidate.record_index
        if accepted:
            current = candidate_solution
            current_objective = candidate_objective
            accepted_counts[operator_name] = accepted_counts.get(operator_name, 0) + 1
        if improved_best:
            best = candidate_solution
            best_objective = candidate_objective
            improvement_counts[operator_name] = (
                improvement_counts.get(operator_name, 0) + 1
            )
        trace.append(
            RrTraceRow(
                iteration=iteration,
                operator=operator_name,
                evaluations_before=before,
                evaluations_after=ledger.consumed,
                candidate_signature=solution_signature_hash(candidate_solution),
                candidate_objective=candidate_objective,
                candidate_feasible=True,
                operator_effect_passed=candidate.effect.passed,
                accepted=accepted,
                improved_best=improved_best,
                current_objective=current_objective,
                best_objective=best_objective,
                temperature=temperature,
                detail=(
                    candidate.effect.detail
                    + ";"
                    + (
                        "improving"
                        if delta < -1.0e-9
                        else ("equal" if abs(delta) <= 1.0e-9 else "worsening")
                    )
                    + (
                        ""
                        if not skipped_nonapplicable
                        else (
                            ";skipped_nonapplicable=" + ",".join(skipped_nonapplicable)
                        )
                    )
                ),
            )
        )
    if (
        stop_reason == "COMPLETE_EVALUATION_BUDGET"
        and phase_stop < ledger.limit
        and ledger.consumed >= phase_stop
    ):
        stop_reason = "PHASE_EVALUATION_ALLOWANCE"
    return RrRunResult(
        best_solution=best,
        best_objective=best_objective,
        current_solution=current,
        current_objective=current_objective,
        best_generated_solution=best_generated_solution,
        best_generated_objective=best_generated_objective,
        best_generated_record_index=best_generated_record_index,
        trace=tuple(trace),
        elapsed_seconds=perf_counter() - started,
        stop_reason=stop_reason,
        operator_attempts=attempts,
        operator_accepted=accepted_counts,
        operator_best_improvements=improvement_counts,
        route_local_cache_stats=local_cache.as_dict(),
    )


def _propose_candidate(
    current: Solution,
    bundle: China81Bundle,
    *,
    operator: OperatorKind,
    rng: random.Random,
    evaluator: BudgetedCompleteEvaluator,
    config: RrConfig,
    iteration: int,
    evaluation_allowance: int,
    route_local_cache: RouteLocalDecoderCache,
) -> _CandidateProposal | None:
    if evaluation_allowance < 1:
        return None
    plan = _select_plan(
        current,
        bundle,
        operator=operator,
        rng=rng,
        max_segment_length=config.max_segment_length,
        time_window_candidate_pool=config.time_window_candidate_pool,
        cross_depot_pair_pool=config.cross_depot_pair_pool,
    )
    if plan is None:
        return None
    customer_ids = frozenset(
        node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"
    )
    metadata = {
        "rr_iteration": iteration,
        "rr_operator": operator.value,
        "rr_reason": plan.reason,
        "removed_customer_count": len(plan.removed_customer_ids),
    }
    if operator in {
        OperatorKind.VEHICLE_TYPE_FLIP,
        OperatorKind.CHARGE_DEPARTURE_RETIMING,
    }:
        result = _decode_assignment_only_plan(
            current,
            plan,
            bundle,
            evaluator=evaluator,
            rng=rng,
            metadata=metadata,
        )
        if result is None or not result.feasible:
            return None
        effect = verify_operator_effect(
            current,
            result.solution,
            plan,
            customer_ids=customer_ids,
        )
        return _CandidateProposal(
            solution=result.solution,
            objective=result.objective,
            record_index=result.record.index,
            effect=effect,
        )

    allowed_depots_by_route: (
        dict[
            int,
            frozenset[str],
        ]
        | None
    ) = None
    if operator == OperatorKind.CROSS_DEPOT_ROUTE_REASSIGNMENT:
        recreated_skeleton = _whole_route_reassignment_skeleton(
            current,
            plan,
            customer_ids=customer_ids,
        )
        allowed_depots_by_route = {
            plan.route_indices[0]: frozenset(plan.target_depot_ids)
        }
    elif operator == OperatorKind.BIDIRECTIONAL_CROSS_DEPOT_SEGMENT:
        recreated_skeleton = _bidirectional_exchange_skeleton(
            current,
            plan,
            customer_ids=customer_ids,
        )
        allowed_depots_by_route = {
            route_index: frozenset({current.routes[route_index].home_depot_id})
            for route_index in plan.route_indices
        }
    else:
        partial = remove_customers_from_skeleton(
            current,
            plan.removed_customer_ids,
            known_customer_ids=customer_ids,
        )
        try:
            recreated = recreate_removed_customers(
                partial,
                plan.removed_customer_ids,
                bundle,
                rng=rng,
            )
        except NoReconstructionInsertionError:
            return None
        recreated_skeleton = recreated.skeleton

    shortlist_size = min(
        config.assignment_shortlist_size,
        evaluator.ledger.remaining,
        evaluation_allowance,
    )
    if shortlist_size < 1:
        return None
    try:
        result = decode_assignment_shortlist(
            recreated_skeleton,
            bundle,
            evaluator=evaluator,
            source=CandidateSource.RUIN_RECREATE,
            beam_per_state=config.assignment_beam_per_state,
            max_candidates=shortlist_size,
            source_metadata={
                **metadata,
                "recreate_step_count": (
                    len(recreated.steps)
                    if operator == OperatorKind.TIME_WINDOW_PRESSURE_STRING
                    else 0
                ),
                "opened_route_count": (
                    recreated.opened_route_count
                    if operator == OperatorKind.TIME_WINDOW_PRESSURE_STRING
                    else 0
                ),
            },
            allowed_depots_by_route=allowed_depots_by_route,
            route_local_cache=route_local_cache,
            dynamic_state_hash="STATIC",
        )
    except NoFeasibleAssignmentError:
        return None
    if not result.decoded:
        return None
    checked = [
        (
            decoded,
            verify_operator_effect(
                current,
                decoded.scored.solution,
                plan,
                customer_ids=customer_ids,
            ),
        )
        for decoded in result.decoded
    ]
    passing = [pair for pair in checked if pair[1].passed]
    decoded, effect = min(
        passing or checked,
        key=lambda pair: pair[0].scored.objective,
    )
    return _CandidateProposal(
        solution=decoded.scored.solution,
        objective=decoded.scored.objective,
        record_index=decoded.scored.record.index,
        effect=effect,
    )


def _select_plan(
    solution: Solution,
    bundle: China81Bundle,
    *,
    operator: OperatorKind,
    rng: random.Random,
    max_segment_length: int,
    time_window_candidate_pool: int,
    cross_depot_pair_pool: int,
) -> DestroyPlan | None:
    if not solution.routes:
        return None
    customer_ids = frozenset(
        node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"
    )
    if operator == OperatorKind.TIME_WINDOW_PRESSURE_STRING:
        return time_window_pressure_string_plan(
            solution,
            bundle.instance,
            radius=1,
            rng=rng,
            candidate_pool_size=time_window_candidate_pool,
            prices=bundle.prices,
        )
    if operator == OperatorKind.CROSS_DEPOT_ROUTE_REASSIGNMENT:
        route_index = rng.randrange(len(solution.routes))
        current_depot = solution.routes[route_index].home_depot_id
        targets = tuple(
            depot_id
            for depot_id in sorted(bundle.fleet_caps_by_depot)
            if depot_id != current_depot
        )
        if not targets:
            return None
        target_depot = targets[rng.randrange(len(targets))]
        return cross_depot_route_reassignment_plan(
            solution,
            route_index=route_index,
            depot_ids=(current_depot, target_depot),
            customer_ids=customer_ids,
        )
    if operator == OperatorKind.BIDIRECTIONAL_CROSS_DEPOT_SEGMENT:
        pairs = _related_cross_depot_pairs(
            solution,
            bundle,
            customer_ids=customer_ids,
            limit=cross_depot_pair_pool,
        )
        if not pairs:
            return None
        left, right = pairs[rng.randrange(len(pairs))]
        return bidirectional_cross_depot_segment_plan(
            solution,
            first_route_index=left,
            second_route_index=right,
            rng=rng,
            customer_ids=customer_ids,
            max_segment_length=max_segment_length,
        )
    if operator == OperatorKind.VEHICLE_TYPE_FLIP:
        usage = Counter(
            (
                route.home_depot_id,
                route.vehicle_type.strip().lower(),
            )
            for route in solution.routes
        )
        eligible: list[int] = []
        for route_index, route in enumerate(solution.routes):
            current_type = route.vehicle_type.strip().lower()
            target_type = "ev" if current_type == "cv" else "cv"
            try:
                target_cap = int(
                    bundle.fleet_caps_by_depot[route.home_depot_id][
                        f"num_{target_type}"
                    ]
                )
            except KeyError as exc:
                raise ValueError(
                    "vehicle flip lacks a finite target fleet cap for "
                    f"{route.home_depot_id}:{target_type}"
                ) from exc
            if usage[(route.home_depot_id, target_type)] < target_cap:
                eligible.append(route_index)
        if not eligible:
            return None
        return vehicle_type_flip_plan(
            solution,
            route_index=eligible[rng.randrange(len(eligible))],
            customer_ids=customer_ids,
        )
    if operator == OperatorKind.CHARGE_DEPARTURE_RETIMING:
        action_vehicle_ids = {action.vehicle_id for action in solution.charging_actions}
        ev_routes = [
            index
            for index, route in enumerate(solution.routes)
            if route.vehicle_type.strip().lower() == "ev"
            and route.vehicle_id in action_vehicle_ids
        ]
        if not ev_routes:
            return None
        return charge_departure_retiming_plan(
            solution,
            route_index=ev_routes[rng.randrange(len(ev_routes))],
            customer_ids=customer_ids,
        )
    raise ValueError(f"unsupported RR operator {operator.value}")


def _decode_assignment_only_plan(
    current: Solution,
    plan: DestroyPlan,
    bundle: China81Bundle,
    *,
    evaluator: BudgetedCompleteEvaluator,
    rng: random.Random,
    metadata: dict[str, Any],
):
    route_index = plan.route_indices[0]
    route = current.routes[route_index]
    node_type = {node.node_id: node.node_type.lower() for node in bundle.instance.nodes}
    customers = [
        node_id for node_id in route.node_sequence if node_type.get(node_id) == "c"
    ]
    charge_strategy = "integrated"
    carbon_weight = 1.0
    if plan.kind == OperatorKind.VEHICLE_TYPE_FLIP:
        vehicle_type = plan.target_vehicle_types[0]
    elif plan.kind == OperatorKind.CHARGE_DEPARTURE_RETIMING:
        registered_choices = (
            ("integrated", 0.0),
            ("legacy", 1.0),
        )
        first = rng.randrange(len(registered_choices))
        choices = (
            registered_choices[first],
            registered_choices[1 - first],
        )
        vehicle_type = "ev"
    else:
        raise ValueError(f"assignment-only decoder cannot apply {plan.kind.value}")
    if evaluator.ledger.remaining < 1:
        return None
    rebuilt = Route(
        vehicle_id=route.vehicle_id,
        vehicle_type=vehicle_type,
        home_depot_id=route.home_depot_id,
        node_sequence=[
            route.home_depot_id,
            *customers,
            route.home_depot_id,
        ],
    )
    target_actions = []
    try:
        if vehicle_type == "ev":
            if plan.kind == OperatorKind.CHARGE_DEPARTURE_RETIMING:
                old_signature = _charging_action_signature(
                    [
                        action
                        for action in current.charging_actions
                        if action.vehicle_id == route.vehicle_id
                    ]
                )
                changed = None
                for selected_strategy, selected_weight in choices:
                    try:
                        repaired, actions = repair_route_charging(
                            rebuilt,
                            bundle.instance,
                            bundle.time_profile,
                            bundle.prices,
                            strategy=selected_strategy,
                            carbon_weight=float(selected_weight),
                            depot_charge_window_mode="same_day_predeparture",
                        )
                    except (KeyError, RuntimeError, TypeError, ValueError):
                        continue
                    if _charging_action_signature(actions) == old_signature:
                        continue
                    changed = (
                        repaired,
                        actions,
                        selected_strategy,
                        selected_weight,
                    )
                    break
                if changed is None:
                    return None
                (
                    rebuilt,
                    target_actions,
                    charge_strategy,
                    carbon_weight,
                ) = changed
            else:
                rebuilt, target_actions = repair_route_charging(
                    rebuilt,
                    bundle.instance,
                    bundle.time_profile,
                    bundle.prices,
                    strategy=charge_strategy,
                    carbon_weight=float(carbon_weight),
                    depot_charge_window_mode="same_day_predeparture",
                )
        routes = list(current.routes)
        routes[route_index] = rebuilt
        candidate = annotate_cross_site_services(
            Solution(
                routes=routes,
                charging_actions=[
                    action
                    for action in current.charging_actions
                    if action.vehicle_id != route.vehicle_id
                ]
                + list(target_actions),
            ),
            bundle.customer_home_depot,
        )
        return evaluator.score(
            candidate,
            source=CandidateSource.RUIN_RECREATE,
            metadata={
                **metadata,
                "assignment_only_target_route": route_index,
                "target_vehicle_type": vehicle_type,
                "target_charge_strategy": (
                    charge_strategy if vehicle_type == "ev" else "not_applicable"
                ),
                "target_carbon_weight": (
                    float(carbon_weight) if vehicle_type == "ev" else 0.0
                ),
                "unselected_routes_preserved": True,
            },
        )
    except (KeyError, RuntimeError, TypeError, ValueError):
        return None


def _charging_action_signature(actions) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        sorted(
            (
                action.station_id,
                round(float(action.energy_kwh), 9),
                round(float(action.occupancy_minutes), 9),
                round(float(action.charge_start_second), 9),
                int(action.charge_day_offset),
                (
                    ""
                    if action.start_energy_kwh is None
                    else f"{float(action.start_energy_kwh):.9f}"
                ),
                (
                    ""
                    if action.end_energy_kwh is None
                    else f"{float(action.end_energy_kwh):.9f}"
                ),
                str(action.charging_curve_id or ""),
            )
            for action in actions
        )
    )


def _related_cross_depot_pairs(
    solution: Solution,
    bundle: China81Bundle,
    *,
    customer_ids: frozenset[str],
    limit: int,
) -> tuple[tuple[int, int], ...]:
    """Keep a small nearest-route pool instead of enumerating every pair."""

    if limit < 1:
        raise ValueError("cross-depot pair pool must be positive")
    customer_sequences = [
        tuple(node_id for node_id in route.node_sequence if node_id in customer_ids)
        for route in solution.routes
    ]
    scored: list[tuple[float, int, int]] = []
    for left, left_route in enumerate(solution.routes):
        if not customer_sequences[left]:
            continue
        for right in range(left + 1, len(solution.routes)):
            right_route = solution.routes[right]
            if (
                left_route.home_depot_id == right_route.home_depot_id
                or not customer_sequences[right]
            ):
                continue
            relatedness = min(
                float(bundle.instance.distance(first, second))
                + float(bundle.instance.distance(second, first))
                for first in customer_sequences[left]
                for second in customer_sequences[right]
            )
            scored.append((relatedness, left, right))
    return tuple(
        (left, right) for _, left, right in sorted(scored)[: min(limit, len(scored))]
    )


def _whole_route_reassignment_skeleton(
    current: Solution,
    plan: DestroyPlan,
    *,
    customer_ids: frozenset[str],
) -> Solution:
    route_index = plan.route_indices[0]
    target_depot = plan.target_depot_ids[0]
    routes = _pure_customer_routes(current, customer_ids)
    route = routes[route_index]
    routes[route_index] = Route(
        vehicle_id=route.vehicle_id,
        vehicle_type=route.vehicle_type,
        home_depot_id=target_depot,
        node_sequence=[
            target_depot,
            *route.node_sequence[1:-1],
            target_depot,
        ],
    )
    return Solution(routes=routes)


def _bidirectional_exchange_skeleton(
    current: Solution,
    plan: DestroyPlan,
    *,
    customer_ids: frozenset[str],
) -> Solution:
    if len(plan.source_customer_groups) != 2:
        raise ValueError("bidirectional exchange requires two source strings")
    first_index, second_index = plan.route_indices
    first_group, second_group = plan.source_customer_groups
    routes = _pure_customer_routes(current, customer_ids)
    first = routes[first_index]
    second = routes[second_index]
    first_customers = _replace_contiguous_group(
        tuple(first.node_sequence[1:-1]),
        first_group,
        second_group,
    )
    second_customers = _replace_contiguous_group(
        tuple(second.node_sequence[1:-1]),
        second_group,
        first_group,
    )
    routes[first_index] = Route(
        vehicle_id=first.vehicle_id,
        vehicle_type=first.vehicle_type,
        home_depot_id=first.home_depot_id,
        node_sequence=[
            first.home_depot_id,
            *first_customers,
            first.home_depot_id,
        ],
    )
    routes[second_index] = Route(
        vehicle_id=second.vehicle_id,
        vehicle_type=second.vehicle_type,
        home_depot_id=second.home_depot_id,
        node_sequence=[
            second.home_depot_id,
            *second_customers,
            second.home_depot_id,
        ],
    )
    return Solution(routes=routes)


def _pure_customer_routes(
    solution: Solution,
    customer_ids: frozenset[str],
) -> list[Route]:
    return [
        Route(
            vehicle_id=route.vehicle_id,
            vehicle_type=route.vehicle_type,
            home_depot_id=route.home_depot_id,
            node_sequence=[
                route.home_depot_id,
                *[
                    node_id
                    for node_id in route.node_sequence
                    if node_id in customer_ids
                ],
                route.home_depot_id,
            ],
        )
        for route in solution.routes
    ]


def _replace_contiguous_group(
    customers: tuple[str, ...],
    old_group: tuple[str, ...],
    new_group: tuple[str, ...],
) -> tuple[str, ...]:
    if not old_group:
        raise ValueError("cannot exchange an empty customer group")
    width = len(old_group)
    matches = [
        start
        for start in range(len(customers) - width + 1)
        if customers[start : start + width] == old_group
    ]
    if len(matches) != 1:
        raise ValueError("selected customer group is not uniquely contiguous")
    start = matches[0]
    return (
        *customers[:start],
        *new_group,
        *customers[start + width :],
    )


def _temperature(
    *,
    initial_objective: float,
    consumed: int,
    limit: int,
    config: RrConfig,
) -> float:
    start = -(config.start_worsening_fraction * initial_objective) / math.log(
        config.start_acceptance_probability
    )
    end = -(config.end_worsening_fraction * initial_objective) / math.log(
        config.end_acceptance_probability
    )
    if limit <= 1:
        return max(end, 1.0e-12)
    progress = min(1.0, max(0.0, consumed / (limit - 1)))
    return max(
        1.0e-12,
        start * (end / start) ** progress,
    )


def _accept_candidate(
    *,
    delta: float,
    temperature: float,
    rng: random.Random,
) -> bool:
    if delta <= 1.0e-9:
        return True
    probability = math.exp(-delta / max(temperature, 1.0e-12))
    return rng.random() < probability
