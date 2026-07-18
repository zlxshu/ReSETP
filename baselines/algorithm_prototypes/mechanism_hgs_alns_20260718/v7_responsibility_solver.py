"""Mechanism-first ALNS v7 with a multi-depot responsibility decoder.

The route search still receives the complete ALNS budget.  Afterwards three
monotone, separately accounted decoders are applied:

1. a bounded exact cross-depot responsibility neighbourhood;
2. the fixed-route fleet/charging decoder from v6;
3. the fixed-route time-varying-carbon charging decoder from v6.

The responsibility decoder is not a generic extra local search.  It considers
only handovers between routes owned by different depots.  Cheap distance and
ownership deltas rank candidate handovers; the affected routes are then
rebuilt, checked, and scored with the real ReSETP route costs.  It never accepts
a non-improving move and consumes no complete route-search evaluation.

This file is isolated development code.  It does not modify the formal solver
or any protected evaluator/checker file.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import time
from typing import Any, Iterable

from prototype import ArmResult, independent_cost, run_pure_alns
from setp_solver.algorithms.resetp_alns.operators.local_search import (
    _candidate_with_route_customers,
    _route_customers,
)
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES, PriceParameters
from setp_solver.profit import infer_customer_home_depots
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import CrossSiteService, Solution
from v5_carbon_retiming_solver import carbon_aware_depot_retime
from v6_monotone_mechanism_solver import exact_joint_fleet_charge_decode


TOL = 1.0e-9


@dataclass(frozen=True)
class ResponsibilityMove:
    """One cross-depot handover proposed by the cheap ranking layer."""

    kind: str
    left_route_index: int
    right_route_index: int
    left_customers: tuple[str, ...]
    right_customers: tuple[str, ...]
    moved_customers: tuple[str, ...]
    proxy_delta: float


def annotate_cross_site_services(
    solution: Solution,
    owners: dict[str, str],
) -> Solution:
    """Synchronize cross-depot service accounting after a route edit."""

    services = [
        CrossSiteService(
            customer_id=customer_id,
            served_by_depot_id=route.home_depot_id,
        )
        for route in solution.routes
        for customer_id in route.node_sequence[1:-1]
        if owners.get(customer_id) is not None
        and owners[customer_id] != route.home_depot_id
    ]
    return replace(solution, cross_site_services=services)


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def _effective_prices(context: EvaluationContext) -> Any:
    if abs(float(context.carbon_weight) - 1.0) <= 1.0e-12:
        return context.prices
    if isinstance(context.prices, PriceParameters):
        return replace(
            context.prices,
            carbon_price=(
                float(context.prices.carbon_price)
                * float(context.carbon_weight)
            ),
        )
    if isinstance(context.prices, dict):
        prices = dict(context.prices)
        prices["carbon_price"] = (
            float(prices["carbon_price"]) * float(context.carbon_weight)
        )
        return prices
    return replace(
        context.prices,
        carbon_price=(
            float(getattr(context.prices, "carbon_price"))
            * float(context.carbon_weight)
        ),
    )


def _route_distance(
    home_depot_id: str,
    customers: Iterable[str],
    context: EvaluationContext,
) -> float:
    sequence = [home_depot_id, *customers, home_depot_id]
    return sum(
        float(context.instance.distance(left, right))
        for left, right in zip(sequence, sequence[1:])
    )


def _cross_site_count(
    home_depot_id: str,
    customers: Iterable[str],
    owners: dict[str, str],
) -> int:
    return sum(
        owners.get(customer_id) is not None
        and owners[customer_id] != home_depot_id
        for customer_id in customers
    )


def _proxy_delta(
    solution: Solution,
    context: EvaluationContext,
    owners: dict[str, str],
    left_index: int,
    right_index: int,
    left_customers: list[str],
    right_customers: list[str],
) -> float:
    left_route = solution.routes[left_index]
    right_route = solution.routes[right_index]
    old_left = _route_customers(left_route, context.instance)
    old_right = _route_customers(right_route, context.instance)
    distance_delta = (
        _route_distance(
            left_route.home_depot_id,
            left_customers,
            context,
        )
        + _route_distance(
            right_route.home_depot_id,
            right_customers,
            context,
        )
        - _route_distance(left_route.home_depot_id, old_left, context)
        - _route_distance(right_route.home_depot_id, old_right, context)
    )
    ownership_delta = (
        _cross_site_count(
            left_route.home_depot_id,
            left_customers,
            owners,
        )
        + _cross_site_count(
            right_route.home_depot_id,
            right_customers,
            owners,
        )
        - _cross_site_count(left_route.home_depot_id, old_left, owners)
        - _cross_site_count(right_route.home_depot_id, old_right, owners)
    )
    return (
        distance_delta / 1_000.0 * _price(context.prices, "c_km")
        + ownership_delta * _price(context.prices, "cross_site_cost")
    )


def _best_insertion_positions(
    home_depot_id: str,
    customers: list[str],
    customer_id: str,
    context: EvaluationContext,
    *,
    count: int,
) -> list[int]:
    base = _route_distance(home_depot_id, customers, context)
    ranked: list[tuple[float, int]] = []
    for position in range(len(customers) + 1):
        candidate = list(customers)
        candidate.insert(position, customer_id)
        ranked.append(
            (
                _route_distance(home_depot_id, candidate, context) - base,
                position,
            )
        )
    return [
        position
        for _, position in sorted(ranked)[: max(1, int(count))]
    ]


def _ranked_responsibility_moves(
    solution: Solution,
    context: EvaluationContext,
    owners: dict[str, str],
    *,
    top_insertions: int,
) -> list[ResponsibilityMove]:
    """Enumerate reciprocal swaps and one-way handovers across depot borders."""

    route_customers = [
        _route_customers(route, context.instance) for route in solution.routes
    ]
    moves: dict[
        tuple[int, int, tuple[str, ...], tuple[str, ...]],
        ResponsibilityMove,
    ] = {}

    def record(
        *,
        kind: str,
        left_index: int,
        right_index: int,
        left: list[str],
        right: list[str],
        moved: tuple[str, ...],
    ) -> None:
        key = (left_index, right_index, tuple(left), tuple(right))
        proxy = _proxy_delta(
            solution,
            context,
            owners,
            left_index,
            right_index,
            left,
            right,
        )
        item = ResponsibilityMove(
            kind=kind,
            left_route_index=left_index,
            right_route_index=right_index,
            left_customers=tuple(left),
            right_customers=tuple(right),
            moved_customers=moved,
            proxy_delta=float(proxy),
        )
        prior = moves.get(key)
        if prior is None or item.proxy_delta < prior.proxy_delta:
            moves[key] = item

    for left_index, left_route in enumerate(solution.routes):
        left_customers = route_customers[left_index]
        if not left_customers:
            continue
        for right_index in range(left_index + 1, len(solution.routes)):
            right_route = solution.routes[right_index]
            if left_route.home_depot_id == right_route.home_depot_id:
                continue
            right_customers = route_customers[right_index]
            if not right_customers:
                continue

            for source_index, target_index in (
                (left_index, right_index),
                (right_index, left_index),
            ):
                target_route = solution.routes[target_index]
                source = route_customers[source_index]
                target = route_customers[target_index]
                if len(source) <= 1:
                    continue
                for source_position, customer_id in enumerate(source):
                    changed_source = [
                        item
                        for position, item in enumerate(source)
                        if position != source_position
                    ]
                    for target_position in _best_insertion_positions(
                        target_route.home_depot_id,
                        target,
                        customer_id,
                        context,
                        count=top_insertions,
                    ):
                        changed_target = list(target)
                        changed_target.insert(target_position, customer_id)
                        record(
                            kind="handover",
                            left_index=source_index,
                            right_index=target_index,
                            left=changed_source,
                            right=changed_target,
                            moved=(customer_id,),
                        )

            for left_position, left_customer in enumerate(left_customers):
                stripped_left = [
                    item
                    for position, item in enumerate(left_customers)
                    if position != left_position
                ]
                for right_position, right_customer in enumerate(
                    right_customers
                ):
                    stripped_right = [
                        item
                        for position, item in enumerate(right_customers)
                        if position != right_position
                    ]
                    left_positions = {
                        min(left_position, len(stripped_left)),
                        *_best_insertion_positions(
                            left_route.home_depot_id,
                            stripped_left,
                            right_customer,
                            context,
                            count=top_insertions,
                        ),
                    }
                    right_positions = {
                        min(right_position, len(stripped_right)),
                        *_best_insertion_positions(
                            right_route.home_depot_id,
                            stripped_right,
                            left_customer,
                            context,
                            count=top_insertions,
                        ),
                    }
                    for new_left_position in sorted(left_positions):
                        for new_right_position in sorted(right_positions):
                            changed_left = list(stripped_left)
                            changed_right = list(stripped_right)
                            changed_left.insert(
                                new_left_position,
                                right_customer,
                            )
                            changed_right.insert(
                                new_right_position,
                                left_customer,
                            )
                            record(
                                kind="reciprocal_exchange",
                                left_index=left_index,
                                right_index=right_index,
                                left=changed_left,
                                right=changed_right,
                                moved=(left_customer, right_customer),
                            )

    return sorted(
        moves.values(),
        key=lambda move: (
            move.proxy_delta,
            move.kind,
            move.left_route_index,
            move.right_route_index,
            move.moved_customers,
            move.left_customers,
            move.right_customers,
        ),
    )


def _local_exact_cost(
    solution: Solution,
    route_indices: tuple[int, int],
    context: EvaluationContext,
    owners: dict[str, str],
) -> float:
    routes = [solution.routes[index] for index in sorted(set(route_indices))]
    vehicle_ids = {route.vehicle_id for route in routes}
    actions = [
        action
        for action in solution.charging_actions
        if action.vehicle_id in vehicle_ids
    ]
    local = annotate_cross_site_services(
        Solution(routes=routes, charging_actions=actions),
        owners,
    )
    return float(
        evaluate(
            local,
            context.instance,
            context.carbon_profile,
            _effective_prices(context),
            carbon_quota_kg=0.0,
        )["total_cost"]
    )


def exact_cross_depot_responsibility_decode(
    solution: Solution,
    context: EvaluationContext,
    *,
    incumbent_objective: float,
    owners: dict[str, str],
    max_rounds: int = 3,
    max_exact_candidates_per_round: int = 64,
    top_insertions: int = 3,
) -> tuple[Solution, float, dict[str, Any]]:
    """Apply monotone cross-depot handovers using affected-route exact deltas."""

    best = annotate_cross_site_services(solution, owners)
    objective = float(incumbent_objective)
    activity: dict[str, Any] = {
        "proxy_moves_considered": 0,
        "local_exact_evaluations": 0,
        "complete_route_search_evaluations": 0,
        "full_feasibility_checks": 0,
        "accepted_moves": [],
        "exact_decoder_updates": 0,
        "improvements": 0,
    }
    for round_index in range(max(0, int(max_rounds))):
        ranked = _ranked_responsibility_moves(
            best,
            context,
            owners,
            top_insertions=top_insertions,
        )
        activity["proxy_moves_considered"] += len(ranked)
        if not ranked:
            activity["stop_reason"] = "no_cross_depot_move"
            break
        before_cost_cache: dict[tuple[int, int], float] = {}
        selected: tuple[ResponsibilityMove, Solution, float] | None = None
        for move in ranked[: max(0, int(max_exact_candidates_per_round))]:
            route_indices = (
                move.left_route_index,
                move.right_route_index,
            )
            before_local = before_cost_cache.get(route_indices)
            if before_local is None:
                before_local = _local_exact_cost(
                    best,
                    route_indices,
                    context,
                    owners,
                )
                before_cost_cache[route_indices] = before_local
                activity["local_exact_evaluations"] += 1
            candidate = _candidate_with_route_customers(
                best,
                context,
                {
                    move.left_route_index: list(move.left_customers),
                    move.right_route_index: list(move.right_customers),
                },
            )
            activity["full_feasibility_checks"] += 1
            if candidate is None:
                continue
            candidate = annotate_cross_site_services(candidate, owners)
            after_local = _local_exact_cost(
                candidate,
                route_indices,
                context,
                owners,
            )
            activity["local_exact_evaluations"] += 1
            exact_delta = float(after_local - before_local)
            if exact_delta >= -TOL:
                continue
            if selected is None or exact_delta < selected[2]:
                selected = (move, candidate, exact_delta)
        if selected is None:
            activity["stop_reason"] = "no_improving_exact_candidate"
            break
        move, candidate, exact_delta = selected
        best = candidate
        objective += exact_delta
        activity["accepted_moves"].append(
            {
                "round": round_index + 1,
                "kind": move.kind,
                "route_indices": [
                    move.left_route_index,
                    move.right_route_index,
                ],
                "moved_customers": list(move.moved_customers),
                "proxy_delta": float(move.proxy_delta),
                "exact_objective_delta": float(exact_delta),
            }
        )
        activity["exact_decoder_updates"] += 1
        activity["improvements"] += 1
    else:
        activity["stop_reason"] = "round_limit_reached"

    recomputed = float(
        evaluate(
            best,
            context.instance,
            context.carbon_profile,
            _effective_prices(context),
            carbon_quota_kg=context.carbon_quota_kg,
        )["total_cost"]
    )
    activity["independent_final_replays"] = 1
    activity["final_recomputed_cost"] = recomputed
    activity["objective_closure_error"] = abs(recomputed - objective)
    if abs(recomputed - objective) > 1.0e-7:
        raise RuntimeError(
            "responsibility exact-decoder objective mismatch: "
            f"{objective} != {recomputed}"
        )
    return best, recomputed, activity


def _run_v7(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any,
    use_responsibility_decoder: bool,
    use_joint_decoder: bool,
    use_carbon_decoder: bool,
    algorithm_label: str,
    customer_home_depot: dict[str, str] | None = None,
) -> ArmResult:
    started = time.perf_counter()
    total = max(0, int(eval_budget))
    base = run_pure_alns(
        bundle_dir,
        seed=seed,
        eval_budget=total,
        prices=prices,
    )
    bundle = load_search_bundle(bundle_dir)
    owners = (
        dict(customer_home_depot)
        if customer_home_depot is not None
        else infer_customer_home_depots(bundle.instance)
    )
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=EvalBudget(limit=0, target=0),
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    solution = annotate_cross_site_services(base.best_solution, owners)
    objective = independent_cost(bundle_dir, solution, prices)
    if total == 0:
        return ArmResult(
            algorithm=algorithm_label,
            best_solution=solution,
            best_cost=float(objective),
            evaluations=0,
            elapsed_seconds=time.perf_counter() - started,
            route_count=len(solution.routes),
            feasible=not check_solution(solution, bundle.instance, prices),
            mechanism_activity={
                "base_alns_activity": base.mechanism_activity,
                "stop_reason": "zero_budget",
            },
        )

    if use_responsibility_decoder:
        bypass_solution = solution
        bypass_objective = objective
        solution, objective, responsibility_activity = (
            exact_cross_depot_responsibility_decode(
                solution,
                context,
                incumbent_objective=objective,
                owners=owners,
            )
        )
    else:
        bypass_solution = solution
        bypass_objective = objective
        responsibility_activity = {
            "development_ablation": "responsibility_decoder_removed",
            "complete_route_search_evaluations": 0,
            "exact_decoder_updates": 0,
            "improvements": 0,
        }

    def apply_downstream(
        candidate_solution: Solution,
        candidate_objective: float,
    ) -> tuple[Solution, float, dict[str, Any], dict[str, Any]]:
        if use_joint_decoder:
            (
                candidate_solution,
                candidate_objective,
                candidate_joint_activity,
            ) = exact_joint_fleet_charge_decode(
                candidate_solution,
                context,
                incumbent_objective=candidate_objective,
            )
        else:
            candidate_joint_activity = {
                "development_ablation": "joint_decoder_removed",
                "complete_evaluations": 0,
                "exact_decoder_updates": 0,
                "improvements": 0,
            }
        if use_carbon_decoder:
            (
                candidate_solution,
                candidate_objective,
                candidate_carbon_activity,
            ) = carbon_aware_depot_retime(
                candidate_solution,
                context,
                incumbent_objective=candidate_objective,
                consume_complete_evaluation=False,
            )
        else:
            candidate_carbon_activity = {
                "development_ablation": "carbon_decoder_removed",
                "complete_evaluations": 0,
                "exact_decoder_updates": 0,
                "improvements": 0,
            }
        return (
            candidate_solution,
            candidate_objective,
            candidate_joint_activity,
            candidate_carbon_activity,
        )

    solution, objective, joint_activity, carbon_activity = apply_downstream(
        solution,
        objective,
    )
    responsibility_updates = int(
        responsibility_activity.get("exact_decoder_updates", 0)
    )
    if use_responsibility_decoder and responsibility_updates > 0:
        (
            bypass_solution,
            bypass_objective,
            bypass_joint_activity,
            bypass_carbon_activity,
        ) = apply_downstream(bypass_solution, bypass_objective)
        responsibility_activity["downstream_bypass_objective"] = float(
            bypass_objective
        )
        responsibility_activity["downstream_responsibility_objective"] = (
            float(objective)
        )
        if bypass_objective < objective - TOL:
            solution = bypass_solution
            objective = bypass_objective
            joint_activity = bypass_joint_activity
            carbon_activity = bypass_carbon_activity
            responsibility_activity["monotone_envelope_selected"] = (
                "bypass_responsibility"
            )
            responsibility_activity["net_final_improvements"] = 0
        else:
            responsibility_activity["monotone_envelope_selected"] = (
                "responsibility_branch"
            )
            responsibility_activity["net_final_improvements"] = int(
                objective < bypass_objective - TOL
            )
    else:
        responsibility_activity["monotone_envelope_selected"] = (
            "single_identical_branch"
        )
        responsibility_activity["net_final_improvements"] = 0

    recomputed = independent_cost(bundle_dir, solution, prices)
    violations = check_solution(solution, bundle.instance, prices)
    if abs(recomputed - objective) > 1.0e-7:
        raise RuntimeError(
            "v7 exact-decoder objective mismatch after independent replay: "
            f"{objective} != {recomputed}"
        )
    return ArmResult(
        algorithm=algorithm_label,
        best_solution=solution,
        best_cost=float(objective),
        evaluations=int(base.evaluations),
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(solution.routes),
        feasible=not violations,
        mechanism_activity={
            "base_alns_activity": base.mechanism_activity,
            "responsibility_activity": responsibility_activity,
            "joint_activity": joint_activity,
            "carbon_activity": carbon_activity,
            "independent_final_replays": 1,
            "final_recomputed_cost": float(recomputed),
        },
    )


def run_mechanism_alns_v7(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    customer_home_depot: dict[str, str] | None = None,
) -> ArmResult:
    return _run_v7(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        use_responsibility_decoder=True,
        use_joint_decoder=True,
        use_carbon_decoder=True,
        algorithm_label="mechanism_alns_v7",
        customer_home_depot=customer_home_depot,
    )


def run_mechanism_alns_v7_without_responsibility(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    customer_home_depot: dict[str, str] | None = None,
) -> ArmResult:
    return _run_v7(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        use_responsibility_decoder=False,
        use_joint_decoder=True,
        use_carbon_decoder=True,
        algorithm_label="mechanism_alns_v7_without_responsibility_ablation",
        customer_home_depot=customer_home_depot,
    )
