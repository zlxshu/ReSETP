"""Resource-aware Split intensification for China81 route skeletons.

The population engine supplies a strong customer order.  This decoder relaxes
the existing route boundaries and uses dynamic programming to decide where
routes should end and which depot should own each segment.  Segment prices are
the cheapest feasible CV or nonlinear-charged EV realization under the real
project evaluator.  A final shared completion and full check protect global
station capacity and exact accounting.

The design follows the giant-tour/Split line (Prins 2004; Vidal et al. 2012)
but the segment labels are specific to the ReSETP mechanisms.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging,
)
from setp_solver.check import CUSTOMER_COVERAGE, check_solution
from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import (
    China81CompletionResult,
    annotate_cross_site_services,
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.cost import evaluate
from setp_solver.solution import ChargingAction, Route, Solution


TOL = 1.0e-9


@dataclass(frozen=True)
class SegmentLabel:
    depot_id: str
    customers: tuple[str, ...]
    vehicle_type: str
    route_cost: float
    charging_action_count: int


@dataclass(frozen=True)
class MechanismSplitResult:
    solution: Solution
    completion: China81CompletionResult
    objective: float
    improved: bool
    activity: dict[str, Any]


def mechanism_resource_split(
    incumbent: Solution,
    bundle: China81Bundle,
    *,
    max_route_orders: int = 8,
) -> MechanismSplitResult:
    """Re-split elite route orders with exact mechanism-aware segment labels."""

    incumbent_completion = complete_china81_route_skeleton(
        incumbent,
        bundle,
    )
    incumbent_obj = incumbent_completion.objective
    orders = _candidate_giant_orders(
        incumbent_completion.solution,
        bundle,
        max_orders=max_route_orders,
    )
    depots = [
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
    ]
    demand = {
        node.node_id: float(node.demand)
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    cv_capacity = float(
        bundle.instance.vehicle_profile("cv").payload_capacity_kg
    )
    segment_cache: dict[
        tuple[str, tuple[str, ...]],
        SegmentLabel | None,
    ] = {}
    segment_evaluations = 0
    feasible_segment_count = 0
    decoded_order_count = 0
    globally_infeasible_decodes = 0
    best_completion = incumbent_completion
    best_order_index: int | None = None
    best_labels: tuple[SegmentLabel, ...] = ()

    for order_index, order in enumerate(orders):
        count = len(order)
        best_cost = [math.inf] * (count + 1)
        predecessor: list[
            tuple[int, SegmentLabel] | None
        ] = [None] * (count + 1)
        best_cost[0] = 0.0
        for start in range(count):
            if not math.isfinite(best_cost[start]):
                continue
            load = 0.0
            for end in range(start + 1, count + 1):
                load += demand[order[end - 1]]
                if load > cv_capacity + TOL:
                    break
                customers = tuple(order[start:end])
                for depot_id in depots:
                    key = (depot_id, customers)
                    if key not in segment_cache:
                        label, evaluations = _best_segment_label(
                            depot_id,
                            customers,
                            bundle,
                        )
                        segment_cache[key] = label
                        segment_evaluations += evaluations
                        feasible_segment_count += int(label is not None)
                    label = segment_cache[key]
                    if label is None:
                        continue
                    candidate_cost = best_cost[start] + label.route_cost
                    if candidate_cost < best_cost[end] - TOL:
                        best_cost[end] = candidate_cost
                        predecessor[end] = (start, label)
        if predecessor[count] is None:
            continue
        labels = _restore_labels(predecessor, count)
        decoded_order_count += 1
        skeleton = Solution(
            routes=[
                Route(
                    vehicle_id=f"SPLIT-{index + 1:04d}",
                    vehicle_type="cv",
                    home_depot_id=label.depot_id,
                    node_sequence=[
                        label.depot_id,
                        *label.customers,
                        label.depot_id,
                    ],
                )
                for index, label in enumerate(labels)
            ]
        )
        try:
            completion = complete_china81_route_skeleton(
                skeleton,
                bundle,
            )
        except ValueError:
            globally_infeasible_decodes += 1
            continue
        if completion.objective < best_completion.objective - TOL:
            best_completion = completion
            best_order_index = order_index
            best_labels = labels

    objective, _, violations = exact_china81_score(
        best_completion.solution,
        bundle,
    )
    if violations:
        raise RuntimeError(
            "mechanism Split returned an infeasible incumbent"
        )
    if objective > incumbent_obj + TOL:
        raise RuntimeError(
            "mechanism Split violated the monotone incumbent contract"
        )
    improved = objective < incumbent_obj - TOL
    return MechanismSplitResult(
        solution=best_completion.solution,
        completion=best_completion,
        objective=float(objective),
        improved=improved,
        activity={
            "schema_version": "resetp.china81-mechanism-split.v1",
            "source": (
                "Prins 2004 giant-tour Split; Vidal et al. 2012 HGS "
                "resource-aware decoding; ReSETP exact segment labels"
            ),
            "incumbent_objective": float(incumbent_obj),
            "final_objective": float(objective),
            "improvement": float(incumbent_obj - objective),
            "improved": improved,
            "route_order_candidates": len(orders),
            "decoded_route_orders": decoded_order_count,
            "best_route_order_index": best_order_index,
            "segment_cache_entries": len(segment_cache),
            "segment_variant_evaluations": segment_evaluations,
            "feasible_segment_count": feasible_segment_count,
            "globally_infeasible_decodes": globally_infeasible_decodes,
            "selected_route_count": len(best_completion.solution.routes),
            "selected_segment_labels": [
                {
                    "depot_id": label.depot_id,
                    "customers": list(label.customers),
                    "vehicle_type": label.vehicle_type,
                    "route_cost": label.route_cost,
                    "charging_action_count": (
                        label.charging_action_count
                    ),
                }
                for label in best_labels
            ],
        },
    )


def _best_segment_label(
    depot_id: str,
    customers: tuple[str, ...],
    bundle: China81Bundle,
) -> tuple[SegmentLabel | None, int]:
    """Return the cheapest route-local CV/EV realization for one segment."""

    route_id = "SEGMENT"
    candidates: list[
        tuple[str, Route, tuple[ChargingAction, ...]]
    ] = [
        (
            "cv",
            Route(
                route_id,
                "cv",
                depot_id,
                [depot_id, *customers, depot_id],
            ),
            (),
        )
    ]
    base_ev = Route(
        route_id,
        "ev",
        depot_id,
        [depot_id, *customers, depot_id],
    )
    for label, strategy, carbon_weight in (
        ("ev_integrated", "integrated", 1.0),
        ("ev_low_carbon", "legacy", 1.0),
        ("ev_immediate", "integrated", 0.0),
    ):
        try:
            route, actions = repair_route_charging(
                base_ev,
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
                strategy=strategy,
                carbon_weight=carbon_weight,
            )
        except (TypeError, ValueError):
            continue
        candidates.append((label, route, tuple(actions)))

    feasible: list[SegmentLabel] = []
    for label, route, actions in candidates:
        partial = annotate_cross_site_services(
            Solution(
                routes=[route],
                charging_actions=list(actions),
            ),
            bundle.customer_home_depot,
        )
        violations = [
            violation
            for violation in check_solution(
                partial,
                bundle.instance,
                bundle.prices,
            )
            if violation.type != CUSTOMER_COVERAGE
        ]
        if violations:
            continue
        route_cost = float(
            evaluate(
                partial,
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
            )["total_cost"]
        )
        feasible.append(
            SegmentLabel(
                depot_id=depot_id,
                customers=customers,
                vehicle_type=(
                    "cv"
                    if label == "cv"
                    else "ev"
                ),
                route_cost=route_cost,
                charging_action_count=len(actions),
            )
        )
    if not feasible:
        return None, len(candidates)
    return (
        min(
            feasible,
            key=lambda item: (
                item.route_cost,
                item.vehicle_type,
                item.depot_id,
            ),
        ),
        len(candidates),
    )


def _candidate_giant_orders(
    solution: Solution,
    bundle: China81Bundle,
    *,
    max_orders: int,
) -> tuple[tuple[str, ...], ...]:
    node_lookup = {
        node.node_id: node
        for node in bundle.instance.nodes
    }
    route_customers = [
        tuple(
            node_id
            for node_id in route.node_sequence
            if node_id in node_lookup
            and node_lookup[node_id].node_type.lower() == "c"
        )
        for route in solution.routes
    ]
    route_customers = [
        customers
        for customers in route_customers
        if customers
    ]
    route_lists: list[list[tuple[str, ...]]] = [
        list(route_customers),
        list(reversed(route_customers)),
        sorted(route_customers),
    ]
    for offset in range(1, len(route_customers)):
        route_lists.append(
            [
                *route_customers[offset:],
                *route_customers[:offset],
            ]
        )
    orders: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for routes in route_lists:
        order = tuple(
            customer
            for route in routes
            for customer in route
        )
        if order and order not in seen:
            seen.add(order)
            orders.append(order)
        if len(orders) >= max(1, int(max_orders)):
            break
    return tuple(orders)


def _restore_labels(
    predecessor: list[tuple[int, SegmentLabel] | None],
    count: int,
) -> tuple[SegmentLabel, ...]:
    labels: list[SegmentLabel] = []
    cursor = count
    while cursor > 0:
        prior = predecessor[cursor]
        if prior is None:
            raise RuntimeError("mechanism Split predecessor chain broke")
        start, label = prior
        labels.append(label)
        cursor = start
    labels.reverse()
    return tuple(labels)
