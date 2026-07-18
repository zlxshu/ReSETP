"""Preserve official HGS route membership instead of flattening it to one order.

The historical neutral adapter flattens every native HGS route and sends the
result through a sequential order decoder.  This diagnostic bridge keeps each
native route boundary.  If a native capacity route is not time-window
feasible, only the customer order inside that same boundary is rebuilt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from official_hgs_resetp_adapter import HGSOrderResult
from setp_solver.algorithms.resetp_alns.support.fleet import (
    infer_fleet_limits,
    normalize_solution_vehicle_trips,
)
from setp_solver.check import check_solution
from setp_solver.cost import route_node_schedule
from setp_solver.instance_loader import Instance
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.solution import Route, Solution
from v7_responsibility_solver import annotate_cross_site_services


def decode_hgs_routes_preserving_boundaries(
    result: HGSOrderResult,
    *,
    bundle_dir: str | Path,
    instance: Instance,
    owners: dict[str, str],
    prices: Any = DEFAULT_PRICES,
) -> tuple[Solution, dict[str, Any]]:
    """Return a checked all-CV solution with native HGS route sets preserved."""

    routes: list[Route] = []
    repaired_route_count = 0
    original_order_feasible_count = 0
    route_sets: list[tuple[str, tuple[str, ...]]] = []
    for depot_id in sorted(result.routes_by_depot):
        for customer_tuple in result.routes_by_depot[depot_id]:
            customers = list(customer_tuple)
            route_sets.append((depot_id, tuple(sorted(customers))))
            if _route_order_feasible(
                depot_id,
                customers,
                instance,
                prices,
            ):
                ordered = customers
                original_order_feasible_count += 1
            else:
                ordered = _repair_fixed_route_order(
                    depot_id,
                    customers,
                    instance,
                    prices,
                )
                repaired_route_count += 1
            routes.append(
                Route(
                    vehicle_id=f"CV{len(routes) + 1}",
                    vehicle_type="cv",
                    home_depot_id=depot_id,
                    node_sequence=[depot_id, *ordered, depot_id],
                )
            )

    solution = annotate_cross_site_services(Solution(routes=routes), owners)
    limits = infer_fleet_limits(bundle_dir)
    solution = normalize_solution_vehicle_trips(
        solution,
        instance,
        max_cv=limits.cv,
        max_ev=limits.ev,
    )
    solution = annotate_cross_site_services(solution, owners)
    violations = check_solution(solution, instance, prices)
    if violations:
        raise ValueError(
            f"lossless HGS route bridge is infeasible: {violations[:8]}"
        )
    customer_set = {
        node.node_id
        for node in instance.nodes
        if node.node_type.lower() == "c"
    }
    visits = [
        node_id
        for route in solution.routes
        for node_id in route.node_sequence
        if node_id in customer_set
    ]
    if len(visits) != len(customer_set) or set(visits) != customer_set:
        raise ValueError("lossless HGS bridge changed customer coverage")
    return solution, {
        "native_route_count": len(routes),
        "native_route_sets": route_sets,
        "original_order_feasible_count": original_order_feasible_count,
        "repaired_route_count": repaired_route_count,
        "route_boundaries_preserved": True,
    }


def _repair_fixed_route_order(
    depot_id: str,
    customers: list[str],
    instance: Instance,
    prices: Any,
) -> list[str]:
    lookup = {node.node_id: node for node in instance.nodes}
    deterministic_orders = [
        sorted(
            customers,
            key=lambda customer_id: (
                float(lookup[customer_id].due_time),
                float(lookup[customer_id].ready_time),
                customer_id,
            ),
        ),
        sorted(
            customers,
            key=lambda customer_id: (
                float(lookup[customer_id].ready_time),
                float(lookup[customer_id].due_time),
                customer_id,
            ),
        ),
        list(reversed(customers)),
    ]
    for order in deterministic_orders:
        if _route_order_feasible(depot_id, order, instance, prices):
            return order

    unassigned = sorted(
        customers,
        key=lambda customer_id: (
            float(lookup[customer_id].ready_time),
            float(lookup[customer_id].due_time),
            customer_id,
        ),
    )
    plan: list[str] = []
    while unassigned:
        candidates: list[tuple[float, str, int]] = []
        for customer_id in unassigned:
            options: list[tuple[float, int]] = []
            old_distance = _route_distance(depot_id, plan, instance)
            for position in range(len(plan) + 1):
                changed = list(plan)
                changed.insert(position, customer_id)
                if not _route_order_feasible(
                    depot_id,
                    changed,
                    instance,
                    prices,
                ):
                    continue
                delta = (
                    _route_distance(depot_id, changed, instance)
                    - old_distance
                )
                options.append((float(delta), position))
            if not options:
                continue
            options.sort()
            second = options[min(1, len(options) - 1)][0]
            regret = second - options[0][0]
            candidates.append((-float(regret), customer_id, options[0][1]))
        if not candidates:
            raise ValueError(
                "native HGS route set has no fixed-boundary feasible ordering"
            )
        _, customer_id, position = min(candidates)
        plan.insert(position, customer_id)
        unassigned.remove(customer_id)
    if not _route_order_feasible(depot_id, plan, instance, prices):
        raise ValueError("fixed-boundary HGS route repair did not close")
    return plan


def _route_order_feasible(
    depot_id: str,
    customers: list[str],
    instance: Instance,
    prices: Any,
) -> bool:
    lookup = {node.node_id: node for node in instance.nodes}
    if (
        sum(float(lookup[item].demand) for item in customers)
        > _price(prices, "Q_capacity") + 1.0e-9
    ):
        return False
    route = Route(
        "CV_HGS_CHECK",
        "cv",
        depot_id,
        [depot_id, *customers, depot_id],
    )
    return all(
        row.t_start <= float(lookup[row.node_id].due_time) + 1.0e-9
        for row in route_node_schedule(route, instance, prices)
    )


def _route_distance(
    depot_id: str,
    customers: list[str],
    instance: Instance,
) -> float:
    sequence = [depot_id, *customers, depot_id]
    return sum(
        float(instance.distance(left, right))
        for left, right in zip(sequence, sequence[1:])
    )


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))
