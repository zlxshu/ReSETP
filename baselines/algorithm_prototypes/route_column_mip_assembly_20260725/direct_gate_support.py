#!/usr/bin/env python3
"""Pool five sealed parents for the route-column direct headroom gate."""

from __future__ import annotations

from typing import Any

from china81_columns import (
    _deduplicate,
    _incumbent_columns,
    customer_order,
    generate_route_columns,
)
from mip_core import RouteColumn
from setp_solver.solution import Solution


def build_comparison_pools(
    parents: tuple[Solution, ...],
    bundle: Any,
) -> tuple[
    tuple[str, ...],
    tuple[RouteColumn, ...],
    tuple[RouteColumn, ...],
    dict[str, int],
]:
    """Build the parent-route-only pool and the re-split route pool."""
    if not parents:
        raise ValueError("at least one parent solution is required")
    depots = tuple(sorted(bundle.fleet_caps_by_depot))
    dimension = {
        (depot_id, vehicle_type): 2 * depot_index + type_index
        for depot_index, depot_id in enumerate(depots)
        for type_index, vehicle_type in enumerate(("cv", "ev"))
    }

    orders = tuple(customer_order(parent, bundle) for parent in parents)
    customer_set = set(orders[0])
    if len(customer_set) != len(orders[0]):
        raise ValueError("first parent repeats a customer")
    if any(
        len(order) != len(customer_set) or set(order) != customer_set
        for order in orders
    ):
        raise ValueError("parent solutions do not cover the same customers")

    old_rows: list[RouteColumn] = []
    generated_rows: list[RouteColumn] = []
    generated_options_before_dedup = 0
    for parent, order in zip(parents, orders, strict=True):
        old_rows.extend(_incumbent_columns(order, parent, bundle, dimension))
        generated, stats = generate_route_columns(order, bundle, parent)
        generated_rows.extend(
            column for column in generated if column.source != "incumbent"
        )
        generated_options_before_dedup += int(stats["generated_options_before_dedup"])

    old_pool = _deduplicate(old_rows)
    new_pool = _deduplicate([*old_pool, *generated_rows])
    old_boundaries = {column.customers for column in old_pool}
    return (
        tuple(sorted(customer_set)),
        old_pool,
        new_pool,
        {
            "parent_count": len(parents),
            "old_pool_columns": len(old_pool),
            "new_pool_columns": len(new_pool),
            "generated_options_before_dedup": (generated_options_before_dedup),
            "new_boundary_columns": sum(
                column.customers not in old_boundaries for column in new_pool
            ),
        },
    )


def selected_new_boundaries(
    selected: tuple[RouteColumn, ...],
    old_pool: tuple[RouteColumn, ...],
) -> tuple[tuple[str, ...], ...]:
    """Return selected customer boundaries absent from every parent route."""
    old_boundaries = {column.customers for column in old_pool}
    return tuple(
        column.customers
        for column in selected
        if column.customers not in old_boundaries
    )
