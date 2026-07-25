"""China81 bindings for the dual-guided route-order candidate."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from china81_columns import _incumbent_columns, customer_order
from decoder_cache import RouteLocalDecoderCache
from fleet_assignment_dp import _station_charger_caps
from limited_displacement import (
    OrderCandidate,
    generate_limited_displacement_orders,
    is_material_order_and_membership_change,
)
from lp_duals import LpDualResult, rank_route_pairs, solve_pool_lp_duals
from pair_core import build_parent_route_pool, customers_in_route, fleet_dimension
from pyvrp_adapter import _proxy_arc_cost
from setp_solver.solution import Route, Solution


def fleet_caps(bundle: Any) -> tuple[int, ...]:
    return tuple(
        int(bundle.fleet_caps_by_depot[depot][f"num_{vehicle_type}"])
        for depot in sorted(bundle.fleet_caps_by_depot)
        for vehicle_type in ("cv", "ev")
    )


def route_signature(route: Route, bundle: Any) -> tuple[Any, ...]:
    return (
        route.home_depot_id,
        route.vehicle_type.lower(),
        customers_in_route(route, bundle),
    )


def select_route_pairs(
    start: Solution,
    parents: tuple[Solution, ...],
    bundle: Any,
) -> tuple[
    tuple[tuple[int, int, float], ...],
    LpDualResult,
    tuple[Any, ...],
]:
    customers, columns = build_parent_route_pool(parents, bundle)
    duals = solve_pool_lp_duals(
        customers,
        columns,
        fleet_caps=fleet_caps(bundle),
        charger_caps=_station_charger_caps(bundle),
    )
    order = customer_order(start, bundle)
    start_columns = _incumbent_columns(
        order,
        start,
        bundle,
        fleet_dimension(bundle),
    )
    signatures = tuple(route_signature(route, bundle) for route in start.routes)
    ranked = rank_route_pairs(
        start_columns,
        signatures,
        duals,
        limit=2,
    )
    return ranked, duals, columns


def generate_pair_candidates(
    start: Solution,
    pair: tuple[int, int],
    bundle: Any,
    *,
    k: int,
    top_per_direction: int,
    state_limit: int,
) -> tuple[tuple[OrderCandidate, ...], int]:
    first_index, second_index = pair
    first_route = start.routes[first_index]
    second_route = start.routes[second_index]
    original_first = customers_in_route(first_route, bundle)
    original_second = customers_in_route(second_route, bundle)
    node_by_id = {node.node_id: node for node in bundle.instance.nodes}
    demands = {
        customer: float(node_by_id[customer].demand)
        for customer in (*original_first, *original_second)
    }
    ready = {
        customer: float(node_by_id[customer].ready_time)
        for customer in demands
    }
    due = {
        customer: float(node_by_id[customer].due_time)
        for customer in demands
    }
    service = {
        customer: float(node_by_id[customer].service_time)
        for customer in demands
    }
    max_payload = max(
        float(
            bundle.instance.payload_capacity_kg(
                vehicle_type,
                fallback=float(bundle.prices.Q_capacity),
            )
        )
        for vehicle_type in ("cv", "ev")
    )
    total_states = 0
    candidates: list[OrderCandidate] = []
    route_specs = (first_route, second_route)
    directions = (
        (*original_first, *original_second),
        (*original_second, *original_first),
    )
    for direction, order in enumerate(directions):
        remaining = state_limit - total_states
        if remaining < 1:
            raise RuntimeError(
                f"DP state cap exceeded: {total_states}>{state_limit}"
            )

        def arc_cost(left: str, right: str, phase: int) -> float:
            route = route_specs[phase]
            vehicle_type = route.vehicle_type.lower()
            vehicle = bundle.instance.vehicle_profile(vehicle_type)
            load = 0.5 * float(vehicle.payload_capacity_kg)
            kwargs = (
                {"fueling_depot_id": route.home_depot_id}
                if vehicle_type == "cv"
                else {
                    "charging_depot_id": route.home_depot_id,
                    "time_varying": True,
                }
            )
            return float(
                _proxy_arc_cost(
                    bundle,
                    left,
                    right,
                    load,
                    vehicle_type=vehicle_type,
                    **kwargs,
                )
            )

        def travel_time(left: str, right: str, phase: int) -> float:
            route = route_specs[phase]
            _, duration, _ = bundle.instance.arc_metrics(
                left,
                right,
                route.vehicle_type.lower(),
                fallback_speed_mps=float(bundle.prices.v_speed_ms),
            )
            return float(duration)

        generated, expanded = generate_limited_displacement_orders(
            order,
            direction=direction,
            k=k,
            top_n=top_per_direction,
            state_limit=remaining,
            demands=demands,
            max_payload=max_payload,
            ready=ready,
            due=due,
            service=service,
            first_depot=first_route.home_depot_id,
            second_depot=second_route.home_depot_id,
            arc_cost=arc_cost,
            travel_time=travel_time,
        )
        total_states += expanded
        candidates.extend(
            item
            for item in generated
            if is_material_order_and_membership_change(
                item,
                original_first,
                original_second,
            )
        )
    unique: dict[tuple[tuple[str, ...], tuple[str, ...]], OrderCandidate] = {}
    for item in sorted(
        candidates,
        key=lambda row: (
            row.direction,
            row.proxy_cost,
            row.first,
            row.second,
        ),
    ):
        unique.setdefault((item.first, item.second), item)
    selected: list[OrderCandidate] = []
    for direction in (0, 1):
        selected.extend(
            [
                item
                for item in unique.values()
                if item.direction == direction
            ][:top_per_direction]
        )
    return tuple(selected), total_states


def replace_pair_skeleton(
    solution: Solution,
    pair: tuple[int, int],
    candidate: OrderCandidate,
) -> Solution:
    """Replace only route customer order/membership; common completion follows."""

    replacements = {
        pair[0]: candidate.first,
        pair[1]: candidate.second,
    }
    routes: list[Route] = []
    for index, route in enumerate(solution.routes):
        customers = replacements.get(index)
        if customers is None:
            routes.append(route)
            continue
        routes.append(
            Route(
                vehicle_id=route.vehicle_id,
                vehicle_type=route.vehicle_type,
                home_depot_id=route.home_depot_id,
                node_sequence=[
                    route.home_depot_id,
                    *customers,
                    route.home_depot_id,
                ],
            )
        )
    return Solution(routes=routes)


def candidate_trace_row(
    pair: tuple[int, int],
    pressure: float,
    candidate: OrderCandidate,
) -> dict[str, Any]:
    return {
        "route_first": pair[0],
        "route_second": pair[1],
        "pressure": float(pressure),
        **asdict(candidate),
    }

