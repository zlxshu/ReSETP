"""Mechanism-first ALNS development candidate.

Negative v2/v3 ablations showed that the official HGS-CVRP projection did not
add value on the rich ReSETP development instances.  This candidate keeps the
official HGS as an external control and concentrates the new algorithm on
model-specific decisions:

1. ALNS improves customer grouping and route order.
2. A cross-depot responsibility expert tests free reinsertion moves.
3. A joint fleet/charging decoder selects the complete CV/EV route pattern in
   one shot, using route-local proxy costs and only one complete candidate
   evaluation.

This is isolated development code and does not alter the formal solver.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations, product
from pathlib import Path
import time
from typing import Any, Iterable

from prototype import (
    ArmResult,
    cross_depot_swapstar_intensify,
    independent_cost,
    run_pure_alns,
)
from setp_solver.algorithms.resetp_alns.runtime.budgeted_scoring import (
    score_search_candidate,
)
from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging,
)
from setp_solver.algorithms.resetp_alns.support.fleet import (
    normalize_solution_vehicle_trips,
)
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import ChargingAction, Route, Solution


@dataclass(frozen=True)
class RouteVariant:
    route: Route
    actions: tuple[ChargingAction, ...]
    proxy_cost: float
    vehicle_type: str


def _customer_only_sequence(route: Route, instance: Any) -> list[str]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    customers = [
        node_id
        for node_id in route.node_sequence
        if node_lookup.get(node_id) is not None
        and node_lookup[node_id].node_type.lower() == "c"
    ]
    return [route.home_depot_id, *customers, route.home_depot_id]


def _proxy_cost(
    route: Route,
    actions: tuple[ChargingAction, ...],
    *,
    instance: Any,
    carbon_profile: list[dict[str, Any]],
    prices: Any,
) -> float:
    return float(
        evaluate(
            Solution(routes=[route], charging_actions=list(actions)),
            instance,
            carbon_profile,
            prices,
        )["total_cost"]
    )


def _route_variants(
    route: Route,
    *,
    current_actions: tuple[ChargingAction, ...],
    instance: Any,
    carbon_profile: list[dict[str, Any]],
    prices: Any,
) -> dict[str, RouteVariant]:
    variants: dict[str, RouteVariant] = {}
    current_type = route.vehicle_type.lower()
    current = RouteVariant(
        route=route,
        actions=current_actions,
        proxy_cost=_proxy_cost(
            route,
            current_actions,
            instance=instance,
            carbon_profile=carbon_profile,
            prices=prices,
        ),
        vehicle_type=current_type,
    )
    variants[current_type] = current
    sequence = _customer_only_sequence(route, instance)
    if current_type != "cv":
        cv_route = Route(
            vehicle_id=route.vehicle_id,
            vehicle_type="cv",
            home_depot_id=route.home_depot_id,
            node_sequence=sequence,
        )
        variants["cv"] = RouteVariant(
            route=cv_route,
            actions=(),
            proxy_cost=_proxy_cost(
                cv_route,
                (),
                instance=instance,
                carbon_profile=carbon_profile,
                prices=prices,
            ),
            vehicle_type="cv",
        )
    if current_type != "ev":
        ev_route = Route(
            vehicle_id=route.vehicle_id,
            vehicle_type="ev",
            home_depot_id=route.home_depot_id,
            node_sequence=sequence,
        )
        try:
            repaired, actions = repair_route_charging(
                ev_route,
                instance,
                carbon_profile,
                prices,
            )
        except ValueError:
            pass
        else:
            variants["ev"] = RouteVariant(
                route=repaired,
                actions=tuple(actions),
                proxy_cost=_proxy_cost(
                    repaired,
                    tuple(actions),
                    instance=instance,
                    carbon_profile=carbon_profile,
                    prices=prices,
                ),
                vehicle_type="ev",
            )
    return variants


def _pattern_candidates(
    variants: list[dict[str, RouteVariant]],
    current_pattern: tuple[str, ...],
) -> Iterable[tuple[str, ...]]:
    choices = [tuple(sorted(route_variants)) for route_variants in variants]
    count = len(choices)
    if count <= 16:
        yield from product(*choices)
        return

    # Large formal instances must not enumerate 2^n patterns.  Keep the
    # current pattern, the route-wise cheapest pattern, and bounded one/two
    # route changes.  This branch is not reached by the current small gate.
    seen: set[tuple[str, ...]] = set()

    def emit(pattern: tuple[str, ...]) -> Iterable[tuple[str, ...]]:
        if pattern not in seen:
            seen.add(pattern)
            yield pattern

    yield from emit(current_pattern)
    cheapest = tuple(
        min(route_variants.values(), key=lambda item: item.proxy_cost).vehicle_type
        for route_variants in variants
    )
    yield from emit(cheapest)
    indices = range(count)
    for width in (1, 2):
        for selected in combinations(indices, width):
            changed = list(current_pattern)
            valid = True
            for index in selected:
                alternatives = [
                    choice for choice in choices[index] if choice != changed[index]
                ]
                if not alternatives:
                    valid = False
                    break
                changed[index] = alternatives[0]
            if valid:
                yield from emit(tuple(changed))
            if len(seen) >= 4096:
                return


def _assemble_pattern(
    variants: list[dict[str, RouteVariant]],
    pattern: tuple[str, ...],
    *,
    parent: Solution,
    instance: Any,
) -> Solution | None:
    routes: list[Route] = []
    actions: list[ChargingAction] = []
    for index, vehicle_type in enumerate(pattern):
        variant = variants[index][vehicle_type]
        vehicle_id = f"{vehicle_type.upper()}JOINT_{index + 1}"
        routes.append(replace(variant.route, vehicle_id=vehicle_id))
        actions.extend(
            replace(action, vehicle_id=vehicle_id)
            for action in variant.actions
        )
    candidate = Solution(
        routes=routes,
        charging_actions=actions,
        cross_site_services=list(parent.cross_site_services),
    )
    try:
        return normalize_solution_vehicle_trips(candidate, instance)
    except ValueError:
        return None


def joint_fleet_charge_decode(
    solution: Solution,
    context: EvaluationContext,
    *,
    incumbent_objective: float,
) -> tuple[Solution, float, dict[str, Any]]:
    """Choose the complete route-type pattern before one full evaluation."""

    route_variants: list[dict[str, RouteVariant]] = []
    current_pattern: list[str] = []
    route_proxy_evaluations = 0
    for route in solution.routes:
        current_actions = tuple(
            action
            for action in solution.charging_actions
            if action.vehicle_id == route.vehicle_id
        )
        variants = _route_variants(
            route,
            current_actions=current_actions,
            instance=context.instance,
            carbon_profile=context.carbon_profile,
            prices=context.prices,
        )
        route_variants.append(variants)
        current_pattern.append(route.vehicle_type.lower())
        route_proxy_evaluations += len(variants)

    current_tuple = tuple(current_pattern)
    current_proxy = sum(
        route_variants[index][vehicle_type].proxy_cost
        for index, vehicle_type in enumerate(current_tuple)
    )
    feasible_patterns = 0
    patterns_considered = 0
    best_pattern = current_tuple
    best_proxy = current_proxy
    best_candidate = solution
    for pattern in _pattern_candidates(route_variants, current_tuple):
        patterns_considered += 1
        proxy = sum(
            route_variants[index][vehicle_type].proxy_cost
            for index, vehicle_type in enumerate(pattern)
        )
        if proxy >= best_proxy - 1.0e-9 and pattern != current_tuple:
            continue
        candidate = _assemble_pattern(
            route_variants,
            pattern,
            parent=solution,
            instance=context.instance,
        )
        if candidate is None or check_solution(
            candidate,
            context.instance,
            context.prices,
        ):
            continue
        feasible_patterns += 1
        if proxy < best_proxy - 1.0e-9:
            best_pattern = pattern
            best_proxy = float(proxy)
            best_candidate = candidate

    activity: dict[str, Any] = {
        "route_proxy_evaluations": route_proxy_evaluations,
        "patterns_considered": patterns_considered,
        "feasible_improving_patterns": feasible_patterns,
        "current_pattern": list(current_tuple),
        "selected_pattern": list(best_pattern),
        "current_proxy_cost": float(current_proxy),
        "selected_proxy_cost": float(best_proxy),
        "complete_evaluations": 0,
        "improvements": 0,
    }
    if best_pattern == current_tuple:
        return solution, float(incumbent_objective), activity
    candidate, objective = score_search_candidate(
        best_candidate,
        context,
        channel="joint_fleet_charge_pattern_decoder",
    )
    activity["complete_evaluations"] = 1
    if objective < incumbent_objective - 1.0e-9:
        activity["improvements"] = 1
        return candidate, float(objective), activity
    return solution, float(incumbent_objective), activity


def _run_mechanism_alns_v4(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any,
    depot_room: int,
    use_depot_expert: bool,
    use_joint_decoder: bool,
    algorithm_label: str,
) -> ArmResult:
    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    warm = make_shared_initial_solution(bundle, prices=prices)
    warm_cost = independent_cost(bundle_dir, warm, prices)
    total = max(0, int(eval_budget))
    if total == 0:
        return ArmResult(
            algorithm=algorithm_label,
            best_solution=warm,
            best_cost=warm_cost,
            evaluations=0,
            elapsed_seconds=time.perf_counter() - started,
            route_count=len(warm.routes),
            feasible=not check_solution(warm, bundle.instance, prices),
            mechanism_activity={},
        )
    joint_room = 1 if use_joint_decoder else 0
    reserved_depot = min(total - joint_room, max(0, int(depot_room)))
    base_room = max(0, total - reserved_depot - joint_room)
    base = run_pure_alns(
        bundle_dir,
        seed=seed,
        eval_budget=base_room,
        prices=prices,
        initial_solution=warm,
    )
    solution = base.best_solution
    objective = float(base.best_cost)

    depot_limit = reserved_depot if use_depot_expert else 0
    depot_budget = EvalBudget(limit=depot_limit, target=depot_limit)
    depot_context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=depot_budget,
    )
    if use_depot_expert:
        solution, objective, depot_activity = cross_depot_swapstar_intensify(
            solution,
            depot_context,
            incumbent_objective=objective,
            max_evaluations=depot_limit,
        )
    else:
        depot_activity = {
            "development_ablation": "cross_depot_expert_removed",
            "cross_depot_evaluations": 0,
            "cross_depot_accepted_moves": 0,
        }
    depot_filler = reserved_depot - depot_budget.count
    if depot_filler:
        continuation = run_pure_alns(
            bundle_dir,
            seed=seed + 8_888_881,
            eval_budget=depot_filler,
            prices=prices,
            initial_solution=solution,
        )
        if continuation.best_cost < objective - 1.0e-9:
            solution = continuation.best_solution
            objective = float(continuation.best_cost)
    post_depot_cost = float(objective)

    joint_budget = EvalBudget(limit=joint_room, target=joint_room)
    joint_context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=joint_budget,
    )
    if use_joint_decoder:
        solution, objective, joint_activity = joint_fleet_charge_decode(
            solution,
            joint_context,
            incumbent_objective=objective,
        )
    else:
        joint_activity = {
            "development_ablation": "joint_fleet_charge_decoder_removed",
            "complete_evaluations": 0,
            "improvements": 0,
        }
    joint_filler = joint_room - joint_budget.count
    if joint_filler:
        continuation = run_pure_alns(
            bundle_dir,
            seed=seed + 9_999_991,
            eval_budget=joint_filler,
            prices=prices,
            initial_solution=solution,
        )
        if continuation.best_cost < objective - 1.0e-9:
            solution = continuation.best_solution
            objective = float(continuation.best_cost)
    evaluations = (
        base.evaluations
        + depot_budget.count
        + depot_filler
        + joint_budget.count
        + joint_filler
    )
    return ArmResult(
        algorithm=algorithm_label,
        best_solution=solution,
        best_cost=float(objective),
        evaluations=evaluations,
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(solution.routes),
        feasible=not check_solution(solution, bundle.instance, prices),
        mechanism_activity={
            "warm_cost": float(warm_cost),
            "base_alns_cost": float(base.best_cost),
            "post_depot_cost": post_depot_cost,
            "final_cost": float(objective),
            "base_alns_evaluations": base.evaluations,
            "depot_complete_evaluations": depot_budget.count,
            "depot_filler_alns_evaluations": depot_filler,
            "joint_complete_evaluations": joint_budget.count,
            "joint_filler_alns_evaluations": joint_filler,
            "depot_activity": depot_activity,
            "joint_activity": joint_activity,
        },
    )


def run_mechanism_alns_v4(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    depot_room: int = 2,
) -> ArmResult:
    """Run ALNS plus both model-specific experts."""

    return _run_mechanism_alns_v4(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        depot_room=depot_room,
        use_depot_expert=True,
        use_joint_decoder=True,
        algorithm_label="mechanism_alns_v4",
    )


def run_mechanism_alns_v4_without_depot(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    depot_room: int = 2,
) -> ArmResult:
    """Development ablation without the cross-depot expert."""

    return _run_mechanism_alns_v4(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        depot_room=depot_room,
        use_depot_expert=False,
        use_joint_decoder=True,
        algorithm_label="mechanism_alns_v4_without_depot_ablation",
    )


def run_mechanism_alns_v4_without_joint(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    depot_room: int = 2,
) -> ArmResult:
    """Development ablation without the joint fleet/charging decoder."""

    return _run_mechanism_alns_v4(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        depot_room=depot_room,
        use_depot_expert=True,
        use_joint_decoder=False,
        algorithm_label="mechanism_alns_v4_without_joint_ablation",
    )
