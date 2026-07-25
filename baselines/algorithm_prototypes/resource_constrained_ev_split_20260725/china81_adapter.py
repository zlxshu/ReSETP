"""China81 adapter for the resource-constrained EV-aware Split."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from typing import Any

from decoder_cache import RouteLocalDecoderCache
from fleet_assignment_dp import (
    NoFeasibleAssignmentError,
    _charger_slot_keys,
    _station_charger_caps,
    build_route_assignment_options,
)
from reference_decoder import RouteAssignment
from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging,
)
from setp_solver.china81_completion import (
    _single_route_cost,
    annotate_cross_site_services,
    exact_china81_score,
)
from setp_solver.solution import ChargingAction, Route, Solution
from split_core import (
    SegmentChoice,
    SplitResult,
    solve_resource_constrained_split,
)


@dataclass(frozen=True)
class China81SplitResult:
    solution: Solution
    objective: float
    split: SplitResult
    generated_segment_count: int
    generated_option_count: int
    incumbent_option_count: int
    non_incumbent_option_count: int
    route_local_sum: float
    exact_minus_route_local: float


def decode_customer_order(
    order: tuple[str, ...],
    bundle: Any,
    *,
    incumbent: Solution | None = None,
    max_labels_per_position: int = 50_000,
    max_generated_labels: int = 500_000,
) -> China81SplitResult:
    """Jointly split one order and assign depot, type, and charging."""

    _validate_order(order, bundle)
    depots = tuple(sorted(bundle.fleet_caps_by_depot))
    dimension = {
        (depot_id, vehicle_type): 2 * depot_index + type_index
        for depot_index, depot_id in enumerate(depots)
        for type_index, vehicle_type in enumerate(("cv", "ev"))
    }
    fleet_caps = tuple(
        int(bundle.fleet_caps_by_depot[depot_id][f"num_{vehicle_type}"])
        for depot_id in depots
        for vehicle_type in ("cv", "ev")
    )
    cache = RouteLocalDecoderCache()
    choices: dict[int, list[SegmentChoice]] = {}
    incumbent_count = 0
    if incumbent is not None:
        incumbent_count = _inject_incumbent_choices(
            choices,
            order,
            incumbent,
            bundle,
            dimension,
        )

    node_by_id = {node.node_id: node for node in bundle.instance.nodes}
    fallback_capacity = float(bundle.prices.Q_capacity)
    max_capacity = max(
        float(
            bundle.instance.payload_capacity_kg(
                vehicle_type,
                fallback=fallback_capacity,
            )
        )
        for vehicle_type in ("cv", "ev")
    )
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
                        vehicle_id="RC-SPLIT-SEGMENT",
                        vehicle_type="cv",
                        home_depot_id=placeholder_depot,
                        node_sequence=[
                            placeholder_depot,
                            *customers,
                            placeholder_depot,
                        ],
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
                options = ()
            if not options:
                continue
            generated_segments += 1
            for option in options:
                assignment = option.assignment
                delta = [0 for _ in fleet_caps]
                delta[
                    dimension[
                        (
                            assignment.home_depot_id,
                            assignment.vehicle_type,
                        )
                    ]
                ] = 1
                choices.setdefault(start, []).append(
                    SegmentChoice(
                        start=start,
                        end=end,
                        cost=float(option.route_local_cost),
                        fleet_delta=tuple(delta),
                        charger_delta=tuple(
                            (station, day, slot, 1)
                            for station, day, slot in (
                                option.charger_slot_keys
                            )
                        ),
                        payload={
                            "kind": "generated",
                            "customers": customers,
                            "assignment": assignment,
                        },
                        source="generated",
                    )
                )
                generated_options += 1

    frozen_choices = {
        start: _deduplicate_choices(rows)
        for start, rows in choices.items()
    }
    split = solve_resource_constrained_split(
        len(order),
        frozen_choices,
        fleet_caps=fleet_caps,
        charger_caps=_station_charger_caps(bundle),
        max_labels_per_position=max_labels_per_position,
        max_generated_labels=max_generated_labels,
    )
    solution = _materialize(split.choices, bundle)
    objective, _, violations = exact_china81_score(solution, bundle)
    if violations:
        details = "; ".join(
            f"{row.type}:{row.location}:{row.detail}"
            for row in violations[:6]
        )
        raise RuntimeError(
            "resource-constrained split materialized an infeasible "
            f"solution: {details}"
        )
    route_local_sum = float(
        sum(choice.cost for choice in split.choices)
    )
    return China81SplitResult(
        solution=solution,
        objective=float(objective),
        split=split,
        generated_segment_count=generated_segments,
        generated_option_count=generated_options,
        incumbent_option_count=incumbent_count,
        non_incumbent_option_count=sum(
            choice.source != "incumbent"
            for rows in frozen_choices.values()
            for choice in rows
        ),
        route_local_sum=route_local_sum,
        exact_minus_route_local=float(objective - route_local_sum),
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


def _inject_incumbent_choices(
    choices: dict[int, list[SegmentChoice]],
    order: tuple[str, ...],
    incumbent: Solution,
    bundle: Any,
    dimension: dict[tuple[str, str], int],
) -> int:
    node_type = {
        node.node_id: node.node_type.lower()
        for node in bundle.instance.nodes
    }
    actions_by_vehicle: dict[str, list[ChargingAction]] = {}
    for action in incumbent.charging_actions:
        actions_by_vehicle.setdefault(action.vehicle_id, []).append(action)
    position = 0
    count = 0
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
            raise ValueError(
                "incumbent routes are not contiguous in the supplied order"
            )
        actions = tuple(actions_by_vehicle.get(route.vehicle_id, ()))
        vehicle_type = route.vehicle_type.strip().lower()
        delta = [0 for _ in dimension]
        delta[dimension[(route.home_depot_id, vehicle_type)]] = 1
        choices.setdefault(position, []).append(
            SegmentChoice(
                start=position,
                end=end,
                cost=float(_single_route_cost(route, actions, bundle)),
                fleet_delta=tuple(delta),
                charger_delta=tuple(
                    (station, day, slot, 1)
                    for station, day, slot in _charger_slot_keys(
                        list(actions),
                        bundle,
                    )
                ),
                payload={
                    "kind": "incumbent",
                    "route": route,
                    "actions": actions,
                },
                source="incumbent",
            )
        )
        position = end
        count += 1
    if position != len(order):
        raise ValueError("incumbent does not cover the supplied order")
    return count


def _deduplicate_choices(
    rows: list[SegmentChoice],
) -> tuple[SegmentChoice, ...]:
    unique: dict[tuple[Any, ...], SegmentChoice] = {}
    for choice in rows:
        payload = choice.payload
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
            choice.start,
            choice.end,
            choice.fleet_delta,
            choice.charger_delta,
            detail,
        )
        current = unique.get(key)
        if current is None or choice.cost < current.cost:
            unique[key] = choice
    return tuple(
        sorted(
            unique.values(),
            key=lambda choice: (
                choice.end,
                choice.cost,
                choice.source,
                repr(choice.payload),
            ),
        )
    )


def _materialize(
    choices: tuple[SegmentChoice, ...],
    bundle: Any,
) -> Solution:
    counters: Counter[tuple[str, str]] = Counter()
    routes: list[Route] = []
    actions: list[ChargingAction] = []
    for choice in choices:
        payload = choice.payload
        if payload["kind"] == "incumbent":
            source_route: Route = payload["route"]
            depot_id = source_route.home_depot_id
            vehicle_type = source_route.vehicle_type.strip().lower()
            counters[(depot_id, vehicle_type)] += 1
            vehicle_id = (
                f"RC-{depot_id}-{vehicle_type.upper()}-"
                f"{counters[(depot_id, vehicle_type)]:03d}"
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
        vehicle_id = (
            f"RC-{depot_id}-{vehicle_type.upper()}-"
            f"{counters[(depot_id, vehicle_type)]:03d}"
        )
        route = Route(
            vehicle_id=vehicle_id,
            vehicle_type=vehicle_type,
            home_depot_id=depot_id,
            node_sequence=[
                depot_id,
                *payload["customers"],
                depot_id,
            ],
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


def _validate_order(order: tuple[str, ...], bundle: Any) -> None:
    customers = tuple(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    )
    if len(order) != len(customers):
        raise ValueError("customer order length mismatch")
    if set(order) != set(customers) or len(set(order)) != len(order):
        raise ValueError("customer order must contain every customer once")
