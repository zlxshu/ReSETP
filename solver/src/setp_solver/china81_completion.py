"""Shared China81 route-skeleton completion and exact scoring.

Every algorithm arm may propose customer groups and visit order, but no arm is
allowed to use a cheaper physical model.  This module converts the common
route skeleton into a feasible all-CV reference, then greedily tests EV and
nonlinear charging variants under the same project evaluator and checker.

The decoder is deliberately monotone: a variant is accepted only when the
complete solution remains feasible and its exact model cost strictly falls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging,
)
from setp_solver.check import Violation, check_solution
from setp_solver.china81 import China81Bundle
from setp_solver.cost import evaluate
from setp_solver.solution import (
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)


TOL = 1.0e-9


@dataclass(frozen=True)
class RouteCompletionVariant:
    """One feasible fixed-customer route type/charging proposal."""

    route_index: int
    label: str
    route: Route
    actions: tuple[ChargingAction, ...]
    route_cost: float
    saving_from_cv: float


@dataclass(frozen=True)
class China81CompletionResult:
    """Completed solution plus a transparent mechanism ledger."""

    solution: Solution
    objective: float
    breakdown: dict[str, float]
    activity: dict[str, Any]


def annotate_cross_site_services(
    solution: Solution,
    customer_home_depot: dict[str, str] | Any,
) -> Solution:
    """Rebuild cross-site records from route ownership."""

    services = [
        CrossSiteService(
            customer_id=node_id,
            served_by_depot_id=route.home_depot_id,
        )
        for route in solution.routes
        for node_id in route.node_sequence[1:-1]
        if customer_home_depot.get(node_id) is not None
        and customer_home_depot[node_id] != route.home_depot_id
    ]
    return Solution(
        routes=list(solution.routes),
        charging_actions=list(solution.charging_actions),
        cross_site_services=services,
    )


def exact_china81_score(
    solution: Solution,
    bundle: China81Bundle,
) -> tuple[float, dict[str, float], list[Violation]]:
    """Return the exact full-model objective and violations."""

    annotated = annotate_cross_site_services(
        solution,
        bundle.customer_home_depot,
    )
    violations = check_solution(
        annotated,
        bundle.instance,
        bundle.prices,
    )
    breakdown = evaluate(
        annotated,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    return float(breakdown["total_cost"]), breakdown, violations


def complete_china81_route_skeleton(
    skeleton: Solution,
    bundle: China81Bundle,
) -> China81CompletionResult:
    """Complete one route skeleton with a common monotone physics decoder.

    The input contributes only customer grouping, visit order, and home depot.
    The common decoder first builds a feasible all-CV solution, then tests
    integrated, low-carbon, and immediate-timing EV variants.  Every accepted
    change is replayed through the complete checker and evaluator.
    """

    baseline = _canonical_all_cv_solution(skeleton, bundle)
    baseline_obj, baseline_breakdown, baseline_violations = exact_china81_score(
        baseline,
        bundle,
    )
    if baseline_violations:
        raise ValueError(
            "China81 route skeleton has no feasible all-CV completion: "
            + _violation_summary(baseline_violations)
        )

    all_variants: list[RouteCompletionVariant] = []
    generation_failures: list[dict[str, Any]] = []
    for route_index, route in enumerate(baseline.routes):
        cv_cost = _single_route_cost(route, (), bundle)
        for label, strategy, carbon_weight in (
            ("ev_integrated", "integrated", 1.0),
            ("ev_low_carbon", "legacy", 1.0),
            ("ev_immediate", "integrated", 0.0),
        ):
            ev_route = Route(
                vehicle_id=route.vehicle_id,
                vehicle_type="ev",
                home_depot_id=route.home_depot_id,
                node_sequence=list(route.node_sequence),
            )
            try:
                repaired, actions = repair_route_charging(
                    ev_route,
                    bundle.instance,
                    bundle.time_profile,
                    bundle.prices,
                    strategy=strategy,
                    carbon_weight=carbon_weight,
                    depot_charge_window_mode="same_day_predeparture",
                )
                route_cost = _single_route_cost(
                    repaired,
                    tuple(actions),
                    bundle,
                )
            except (TypeError, ValueError) as exc:
                generation_failures.append(
                    {
                        "route_index": route_index,
                        "label": label,
                        "reason": str(exc),
                    }
                )
                continue
            all_variants.append(
                RouteCompletionVariant(
                    route_index=route_index,
                    label=label,
                    route=repaired,
                    actions=tuple(actions),
                    route_cost=route_cost,
                    saving_from_cv=float(cv_cost - route_cost),
                )
            )

    ranked = sorted(
        all_variants,
        key=lambda item: (
            -item.saving_from_cv,
            item.route_index,
            item.route_cost,
            item.label,
        ),
    )
    current = baseline
    current_obj = baseline_obj
    accepted_route_indices: set[int] = set()
    attempted = 0
    rejected_infeasible = 0
    rejected_non_improving = 0
    accepted: list[dict[str, Any]] = []
    for variant in ranked:
        if variant.route_index in accepted_route_indices:
            continue
        attempted += 1
        candidate = _replace_route_variant(
            current,
            route_index=variant.route_index,
            route=variant.route,
            actions=variant.actions,
            customer_home_depot=bundle.customer_home_depot,
        )
        candidate_obj, _, candidate_violations = exact_china81_score(
            candidate,
            bundle,
        )
        if candidate_violations:
            rejected_infeasible += 1
            continue
        if candidate_obj >= current_obj - TOL:
            rejected_non_improving += 1
            continue
        accepted.append(
            {
                "route_index": variant.route_index,
                "label": variant.label,
                "before_cost": float(current_obj),
                "after_cost": float(candidate_obj),
                "improvement": float(current_obj - candidate_obj),
                "charging_action_count": len(variant.actions),
            }
        )
        current = candidate
        current_obj = candidate_obj
        accepted_route_indices.add(variant.route_index)

    final_obj, final_breakdown, final_violations = exact_china81_score(
        current,
        bundle,
    )
    if final_violations:
        raise RuntimeError(
            "shared China81 completion returned an infeasible solution: "
            + _violation_summary(final_violations)
        )
    if final_obj > baseline_obj + TOL:
        raise RuntimeError(
            "shared China81 completion violated its monotone contract"
        )

    activity: dict[str, Any] = {
        "schema_version": "resetp.china81-shared-completion.v1",
        "baseline_all_cv_cost": float(baseline_obj),
        "final_cost": float(final_obj),
        "strict_improvement": bool(final_obj < baseline_obj - TOL),
        "improvement": float(baseline_obj - final_obj),
        "route_count": len(current.routes),
        "ev_route_count": sum(
            route.vehicle_type.lower() == "ev"
            for route in current.routes
        ),
        "charging_action_count": len(current.charging_actions),
        "cross_site_service_count": len(current.cross_site_services),
        "mechanism_experts_queried": [
            "vehicle_type_and_nonlinear_charging",
            "time_varying_electricity_and_carbon",
            "multi_depot_responsibility_accounting",
        ],
        "variant_count": len(all_variants),
        "variant_attempts": attempted,
        "variant_generation_failures": generation_failures,
        "rejected_infeasible": rejected_infeasible,
        "rejected_non_improving": rejected_non_improving,
        "accepted_variants": accepted,
        "baseline_breakdown": baseline_breakdown,
        "final_breakdown": final_breakdown,
    }
    return China81CompletionResult(
        solution=current,
        objective=float(final_obj),
        breakdown=final_breakdown,
        activity=activity,
    )


def _canonical_all_cv_solution(
    skeleton: Solution,
    bundle: China81Bundle,
) -> Solution:
    node_lookup = {
        node.node_id: node
        for node in bundle.instance.nodes
    }
    depots = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
    }
    routes: list[Route] = []
    for route_index, route in enumerate(skeleton.routes):
        if route.home_depot_id not in depots:
            raise ValueError(
                f"route {route_index} has unknown home depot "
                f"{route.home_depot_id!r}"
            )
        customers = [
            node_id
            for node_id in route.node_sequence
            if node_id in node_lookup
            and node_lookup[node_id].node_type.lower() == "c"
        ]
        if not customers:
            continue
        routes.append(
            Route(
                vehicle_id=f"CH81-{len(routes) + 1:04d}",
                vehicle_type="cv",
                home_depot_id=route.home_depot_id,
                node_sequence=[
                    route.home_depot_id,
                    *customers,
                    route.home_depot_id,
                ],
            )
        )
    return annotate_cross_site_services(
        Solution(routes=routes),
        bundle.customer_home_depot,
    )


def _single_route_cost(
    route: Route,
    actions: tuple[ChargingAction, ...],
    bundle: China81Bundle,
) -> float:
    partial = annotate_cross_site_services(
        Solution(
            routes=[route],
            charging_actions=list(actions),
        ),
        bundle.customer_home_depot,
    )
    return float(
        evaluate(
            partial,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
        )["total_cost"]
    )


def _replace_route_variant(
    solution: Solution,
    *,
    route_index: int,
    route: Route,
    actions: tuple[ChargingAction, ...],
    customer_home_depot: dict[str, str] | Any,
) -> Solution:
    old_vehicle_id = solution.routes[route_index].vehicle_id
    routes = list(solution.routes)
    routes[route_index] = route
    kept_actions = [
        action
        for action in solution.charging_actions
        if action.vehicle_id != old_vehicle_id
    ]
    candidate = Solution(
        routes=routes,
        charging_actions=[*kept_actions, *actions],
    )
    return annotate_cross_site_services(candidate, customer_home_depot)


def _violation_summary(violations: list[Violation]) -> str:
    return "; ".join(
        f"{item.type}:{item.vehicle_id}:{item.location}:{item.detail}"
        for item in violations[:8]
    )
