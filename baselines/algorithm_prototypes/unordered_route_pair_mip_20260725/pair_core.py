#!/usr/bin/env python3
"""Generate and materialize exact unordered route-pair neighborhoods."""

from __future__ import annotations

from collections import Counter
from typing import Any

from china81_columns import (
    _deduplicate,
    _incumbent_columns,
    customer_order,
    materialize_columns,
)
from decoder_cache import RouteLocalDecoderCache
from fleet_assignment_dp import (
    NoFeasibleAssignmentError,
    _charger_slot_keys,
    _station_charger_caps,
    build_route_assignment_options,
)
from mip_core import RouteColumn
from pair_mip import PairMipResult, solve_pair_columns
from setp_solver.china81_completion import annotate_cross_site_services
from setp_solver.solution import ChargingAction, Route, Solution


def optimize_route_pair(
    solution: Solution,
    route_indices: tuple[int, int],
    bundle: Any,
    *,
    cache: RouteLocalDecoderCache,
    time_limit_seconds: float,
    max_columns: int,
) -> tuple[Solution, PairMipResult, dict[str, int | float]]:
    first, second = route_indices
    if first >= second:
        raise ValueError("route pair indices must be increasing")
    if second >= len(solution.routes):
        raise IndexError("route pair index out of range")
    dimension = fleet_dimension(bundle)
    pair_routes = (solution.routes[first], solution.routes[second])
    actions_by_vehicle = _actions_by_vehicle(solution)
    pair_actions = tuple(
        action
        for route in pair_routes
        for action in actions_by_vehicle[route.vehicle_id]
    )
    pair_solution = Solution(
        routes=list(pair_routes),
        charging_actions=list(pair_actions),
    )
    route_customers = tuple(customers_in_route(route, bundle) for route in pair_routes)
    if any(not customers for customers in route_customers):
        raise ValueError("route pair contains an empty route")
    customers = tuple(customer for route in route_customers for customer in route)
    if len(customers) != len(set(customers)):
        raise ValueError("route pair repeats a customer")

    rows = list(
        _incumbent_columns(
            customers,
            pair_solution,
            bundle,
            dimension,
        )
    )
    fallback_count = len(rows)
    fallback_objective = sum(column.cost for column in rows)
    orders = (
        customers,
        (*route_customers[1], *route_customers[0]),
    )
    generated_segments = 0
    generated_options = 0
    for order in dict.fromkeys(orders):
        generated, segment_count, option_count = _segment_columns(
            order,
            bundle,
            dimension,
            cache,
        )
        rows.extend(generated)
        generated_segments += segment_count
        generated_options += option_count
    columns = _deduplicate(rows)
    if len(columns) > max_columns:
        raise RuntimeError(
            f"route-pair column cap exceeded: {len(columns)}>{max_columns}"
        )

    residual_fleet, residual_slots = residual_capacities(
        solution,
        route_indices,
        bundle,
        columns,
    )
    result = solve_pair_columns(
        tuple(sorted(customers)),
        columns,
        residual_fleet_caps=residual_fleet,
        residual_charger_caps=residual_slots,
        time_limit_seconds=time_limit_seconds,
    )
    if not result.selected:
        raise RuntimeError(
            f"route-pair MIP returned no valid incumbent: "
            f"{result.status_class}: {result.message}"
        )
    candidate = replace_route_pair(
        solution,
        route_indices,
        result.selected,
        bundle,
    )
    return (
        candidate,
        result,
        {
            "fallback_columns": fallback_count,
            "fallback_objective": fallback_objective,
            "generated_segments": generated_segments,
            "generated_options_before_dedup": generated_options,
            "columns_after_dedup": len(columns),
            "selected_routes": len(result.selected),
        },
    )


def fleet_dimension(bundle: Any) -> dict[tuple[str, str], int]:
    depots = tuple(sorted(bundle.fleet_caps_by_depot))
    return {
        (depot_id, vehicle_type): 2 * depot_index + type_index
        for depot_index, depot_id in enumerate(depots)
        for type_index, vehicle_type in enumerate(("cv", "ev"))
    }


def build_parent_route_pool(
    parents: tuple[Solution, ...],
    bundle: Any,
) -> tuple[tuple[str, ...], tuple[RouteColumn, ...]]:
    """Build a global pool containing only complete parent routes."""
    if not parents:
        raise ValueError("at least one parent is required")
    dimension = fleet_dimension(bundle)
    orders = tuple(customer_order(parent, bundle) for parent in parents)
    customer_set = set(orders[0])
    if any(
        len(order) != len(customer_set) or set(order) != customer_set
        for order in orders
    ):
        raise ValueError("parents do not cover the same customer set")
    rows: list[RouteColumn] = []
    for parent, order in zip(parents, orders, strict=True):
        rows.extend(_incumbent_columns(order, parent, bundle, dimension))
    return tuple(sorted(customer_set)), _deduplicate(rows)


def customers_in_route(route: Route, bundle: Any) -> tuple[str, ...]:
    node_type = {node.node_id: node.node_type.lower() for node in bundle.instance.nodes}
    return tuple(
        node_id for node_id in route.node_sequence if node_type.get(node_id) == "c"
    )


def residual_capacities(
    solution: Solution,
    excluded: tuple[int, int],
    bundle: Any,
    columns: tuple[RouteColumn, ...],
) -> tuple[tuple[int, ...], dict[tuple[str, int, int], int]]:
    dimension = fleet_dimension(bundle)
    total_fleet = [0 for _ in dimension]
    for (depot_id, vehicle_type), index in dimension.items():
        total_fleet[index] = int(
            bundle.fleet_caps_by_depot[depot_id][f"num_{vehicle_type}"]
        )
    excluded_set = set(excluded)
    for index, route in enumerate(solution.routes):
        if index in excluded_set:
            continue
        key = (route.home_depot_id, route.vehicle_type.lower())
        total_fleet[dimension[key]] -= 1
    if any(value < 0 for value in total_fleet):
        raise RuntimeError("untouched routes exceed fleet capacity")

    station_caps = _station_charger_caps(bundle)
    used_slots: Counter[tuple[str, int, int]] = Counter()
    actions_by_vehicle = _actions_by_vehicle(solution)
    for index, route in enumerate(solution.routes):
        if index in excluded_set:
            continue
        used_slots.update(
            _charger_slot_keys(
                list(actions_by_vehicle[route.vehicle_id]),
                bundle,
            )
        )
    requested_slots = {
        (station, day, slot)
        for column in columns
        for station, day, slot, _ in column.charger_use
    }
    residual_slots = {
        key: int(station_caps.get(key[0], 1)) - used_slots[key]
        for key in requested_slots
    }
    if any(value < 0 for value in residual_slots.values()):
        raise RuntimeError("untouched routes exceed charger capacity")
    return tuple(total_fleet), residual_slots


def replace_route_pair(
    solution: Solution,
    route_indices: tuple[int, int],
    selected: tuple[RouteColumn, ...],
    bundle: Any,
) -> Solution:
    replacement = materialize_columns(selected, bundle)
    excluded = set(route_indices)
    removed_vehicle_ids = {solution.routes[index].vehicle_id for index in route_indices}
    untouched_routes = [
        route for index, route in enumerate(solution.routes) if index not in excluded
    ]
    untouched_actions = [
        action
        for action in solution.charging_actions
        if action.vehicle_id not in removed_vehicle_ids
    ]
    return annotate_cross_site_services(
        Solution(
            routes=[*untouched_routes, *replacement.routes],
            charging_actions=[
                *untouched_actions,
                *replacement.charging_actions,
            ],
        ),
        bundle.customer_home_depot,
    )


def _segment_columns(
    order: tuple[str, ...],
    bundle: Any,
    dimension: dict[tuple[str, str], int],
    cache: RouteLocalDecoderCache,
) -> tuple[list[RouteColumn], int, int]:
    node_by_id = {node.node_id: node for node in bundle.instance.nodes}
    depots = tuple(sorted(bundle.fleet_caps_by_depot))
    max_capacity = max(
        float(
            bundle.instance.payload_capacity_kg(
                vehicle_type,
                fallback=float(bundle.prices.Q_capacity),
            )
        )
        for vehicle_type in ("cv", "ev")
    )
    rows: list[RouteColumn] = []
    segment_count = 0
    option_count = 0
    for start in range(len(order)):
        demand = 0.0
        for end in range(start + 1, len(order) + 1):
            demand += float(node_by_id[order[end - 1]].demand)
            if demand > max_capacity + 1.0e-9:
                break
            customers = order[start:end]
            skeleton = Solution(
                routes=[
                    Route(
                        "PAIR-SEGMENT",
                        "cv",
                        depots[0],
                        [depots[0], *customers, depots[0]],
                    )
                ]
            )
            try:
                options = build_route_assignment_options(
                    skeleton,
                    bundle,
                    route_local_cache=cache,
                    dynamic_state_hash="STATIC",
                ).get(0, ())
            except NoFeasibleAssignmentError:
                continue
            if options:
                segment_count += 1
            for option in options:
                assignment = option.assignment
                delta = [0 for _ in dimension]
                delta[
                    dimension[
                        (
                            assignment.home_depot_id,
                            assignment.vehicle_type,
                        )
                    ]
                ] = 1
                rows.append(
                    RouteColumn(
                        customers=customers,
                        cost=float(option.route_local_cost),
                        fleet_delta=tuple(delta),
                        charger_use=tuple(
                            (station, day, slot, 1)
                            for station, day, slot in (option.charger_slot_keys)
                        ),
                        payload={
                            "kind": "generated",
                            "assignment": assignment,
                        },
                        source="unordered_pair_segment",
                    )
                )
                option_count += 1
    return rows, segment_count, option_count


def _actions_by_vehicle(
    solution: Solution,
) -> dict[str, tuple[ChargingAction, ...]]:
    return {
        route.vehicle_id: tuple(
            action
            for action in solution.charging_actions
            if action.vehicle_id == route.vehicle_id
        )
        for route in solution.routes
    }
