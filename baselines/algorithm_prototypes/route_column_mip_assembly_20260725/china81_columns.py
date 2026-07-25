"""Create and materialize capacity-aware China81 route columns."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Any

from decoder_cache import RouteLocalDecoderCache
from fleet_assignment_dp import (
    NoFeasibleAssignmentError,
    _charger_slot_keys,
    _station_charger_caps,
    build_route_assignment_options,
)
from mip_core import MipAssemblyResult, RouteColumn, solve_route_columns
from reference_decoder import RouteAssignment
from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging,
)
from setp_solver.china81_completion import (
    _single_route_cost,
    annotate_cross_site_services,
)
from setp_solver.solution import ChargingAction, Route, Solution


def assemble_customer_order(
    order: tuple[str, ...],
    bundle: Any,
    incumbent: Solution,
    *,
    time_limit_seconds: float,
) -> tuple[Solution, MipAssemblyResult, dict[str, int]]:
    columns, stats = generate_route_columns(
        order,
        bundle,
        incumbent,
    )
    depots = tuple(sorted(bundle.fleet_caps_by_depot))
    fleet_caps = tuple(
        int(bundle.fleet_caps_by_depot[depot_id][f"num_{vehicle_type}"])
        for depot_id in depots
        for vehicle_type in ("cv", "ev")
    )
    result = solve_route_columns(
        order,
        columns,
        fleet_caps=fleet_caps,
        charger_caps=_station_charger_caps(bundle),
        time_limit_seconds=time_limit_seconds,
    )
    if not result.selected:
        raise RuntimeError(
            f"route-column MIP has no accepted incumbent: "
            f"{result.status_class}: {result.message}"
        )
    return materialize_columns(result.selected, bundle), result, stats


def generate_route_columns(
    order: tuple[str, ...],
    bundle: Any,
    incumbent: Solution,
) -> tuple[tuple[RouteColumn, ...], dict[str, int]]:
    _validate_order(order, bundle)
    depots = tuple(sorted(bundle.fleet_caps_by_depot))
    dimension = {
        (depot_id, vehicle_type): 2 * depot_index + type_index
        for depot_index, depot_id in enumerate(depots)
        for type_index, vehicle_type in enumerate(("cv", "ev"))
    }
    fleet_dimension = len(dimension)
    rows: list[RouteColumn] = []
    rows.extend(
        _incumbent_columns(
            order,
            incumbent,
            bundle,
            dimension,
        )
    )
    incumbent_count = len(rows)

    node_by_id = {node.node_id: node for node in bundle.instance.nodes}
    max_capacity = max(
        float(
            bundle.instance.payload_capacity_kg(
                vehicle_type,
                fallback=float(bundle.prices.Q_capacity),
            )
        )
        for vehicle_type in ("cv", "ev")
    )
    cache = RouteLocalDecoderCache()
    generated_segments = 0
    generated_options = 0
    placeholder_depot = depots[0]
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
                        "COLUMN-SEGMENT",
                        "cv",
                        placeholder_depot,
                        [placeholder_depot, *customers, placeholder_depot],
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
                generated_segments += 1
            for option in options:
                assignment = option.assignment
                delta = [0 for _ in range(fleet_dimension)]
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
                            for station, day, slot in (
                                option.charger_slot_keys
                            )
                        ),
                        payload={
                            "kind": "generated",
                            "assignment": assignment,
                        },
                        source="generated_segment",
                    )
                )
                generated_options += 1
    columns = _deduplicate(rows)
    return columns, {
        "incumbent_columns": incumbent_count,
        "generated_segments": generated_segments,
        "generated_options_before_dedup": generated_options,
        "columns_after_dedup": len(columns),
        "non_incumbent_columns": sum(
            column.source != "incumbent" for column in columns
        ),
    }


def materialize_columns(
    columns: tuple[RouteColumn, ...],
    bundle: Any,
) -> Solution:
    counters: Counter[tuple[str, str]] = Counter()
    routes: list[Route] = []
    actions: list[ChargingAction] = []
    for column in columns:
        payload = column.payload
        if payload["kind"] == "incumbent":
            source_route: Route = payload["route"]
            depot_id = source_route.home_depot_id
            vehicle_type = source_route.vehicle_type.lower()
            counters[(depot_id, vehicle_type)] += 1
            vehicle_id = _vehicle_id(
                depot_id,
                vehicle_type,
                counters[(depot_id, vehicle_type)],
            )
            routes.append(replace(source_route, vehicle_id=vehicle_id))
            actions.extend(
                replace(action, vehicle_id=vehicle_id)
                for action in payload["actions"]
            )
            continue
        assignment: RouteAssignment = payload["assignment"]
        depot_id = assignment.home_depot_id
        vehicle_type = assignment.vehicle_type
        counters[(depot_id, vehicle_type)] += 1
        vehicle_id = _vehicle_id(
            depot_id,
            vehicle_type,
            counters[(depot_id, vehicle_type)],
        )
        route = Route(
            vehicle_id,
            vehicle_type,
            depot_id,
            [depot_id, *column.customers, depot_id],
        )
        if vehicle_type == "ev":
            route, route_actions = repair_route_charging(
                route,
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
                strategy=assignment.charge_strategy,
                carbon_weight=float(assignment.carbon_weight),
                depot_charge_window_mode="same_day_predeparture",
            )
            actions.extend(route_actions)
        routes.append(route)
    return annotate_cross_site_services(
        Solution(routes=routes, charging_actions=actions),
        bundle.customer_home_depot,
    )


def customer_order(solution: Solution, bundle: Any) -> tuple[str, ...]:
    node_type = {
        node.node_id: node.node_type.lower()
        for node in bundle.instance.nodes
    }
    return tuple(
        node_id
        for route in solution.routes
        for node_id in route.node_sequence
        if node_type.get(node_id) == "c"
    )


def _incumbent_columns(
    order: tuple[str, ...],
    incumbent: Solution,
    bundle: Any,
    dimension: dict[tuple[str, str], int],
) -> tuple[RouteColumn, ...]:
    node_type = {
        node.node_id: node.node_type.lower()
        for node in bundle.instance.nodes
    }
    actions_by_vehicle: dict[str, tuple[ChargingAction, ...]] = {
        route.vehicle_id: tuple(
            action
            for action in incumbent.charging_actions
            if action.vehicle_id == route.vehicle_id
        )
        for route in incumbent.routes
    }
    position = 0
    rows: list[RouteColumn] = []
    for route in incumbent.routes:
        customers = tuple(
            node_id
            for node_id in route.node_sequence
            if node_type.get(node_id) == "c"
        )
        if not customers:
            continue
        end = position + len(customers)
        if order[position:end] != customers:
            raise ValueError("incumbent is not contiguous in supplied order")
        vehicle_type = route.vehicle_type.lower()
        delta = [0 for _ in dimension]
        delta[dimension[(route.home_depot_id, vehicle_type)]] = 1
        route_actions = actions_by_vehicle[route.vehicle_id]
        rows.append(
            RouteColumn(
                customers=customers,
                cost=float(
                    _single_route_cost(
                        route,
                        route_actions,
                        bundle,
                    )
                ),
                fleet_delta=tuple(delta),
                charger_use=tuple(
                    (station, day, slot, 1)
                    for station, day, slot in _charger_slot_keys(
                        list(route_actions),
                        bundle,
                    )
                ),
                payload={
                    "kind": "incumbent",
                    "route": route,
                    "actions": route_actions,
                },
                source="incumbent",
            )
        )
        position = end
    if position != len(order):
        raise ValueError("incumbent does not cover supplied order")
    return tuple(rows)


def _deduplicate(rows: list[RouteColumn]) -> tuple[RouteColumn, ...]:
    unique: dict[tuple[Any, ...], RouteColumn] = {}
    for column in rows:
        payload = column.payload
        if payload["kind"] == "generated":
            assignment: RouteAssignment = payload["assignment"]
            detail = (
                assignment.home_depot_id,
                assignment.vehicle_type,
                assignment.charge_strategy,
                assignment.carbon_weight,
            )
        else:
            route: Route = payload["route"]
            detail = (
                route.home_depot_id,
                route.vehicle_type,
                tuple(route.node_sequence),
                tuple(payload["actions"]),
            )
        key = (
            column.customers,
            column.fleet_delta,
            column.charger_use,
            detail,
        )
        current = unique.get(key)
        if current is None or column.cost < current.cost:
            unique[key] = column
    return tuple(
        sorted(
            unique.values(),
            key=lambda column: (
                column.customers,
                column.cost,
                column.source,
                repr(column.payload),
            ),
        )
    )


def _validate_order(order: tuple[str, ...], bundle: Any) -> None:
    customers = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    if len(order) != len(customers) or set(order) != customers:
        raise ValueError("order must contain every customer exactly once")


def _vehicle_id(depot: str, vehicle_type: str, index: int) -> str:
    return f"RCMIP-{depot}-{vehicle_type.upper()}-{index:03d}"
