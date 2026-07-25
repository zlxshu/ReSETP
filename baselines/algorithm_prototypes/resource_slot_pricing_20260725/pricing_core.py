"""Resource-aware bidirectional route pricing on a frozen sparse graph."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Iterable

from common import set_single_thread_environment
from decoder_cache import RouteLocalDecoderCache
from fleet_assignment_dp import (
    NoFeasibleAssignmentError,
    _station_charger_caps,
    build_route_assignment_options,
)
from lp_duals import LpDualResult, solve_pool_lp_duals
from mip_core import RouteColumn
from pair_core import build_parent_route_pool, customers_in_route, fleet_dimension
from pyvrp_adapter import _proxy_arc_cost
from setp_solver.solution import Route, Solution


TOL = 1.0e-7


@dataclass(frozen=True)
class PricedLabel:
    sequence: tuple[str, ...]
    depot_id: str
    vehicle_type: str
    cost: float
    reduced_cost: float
    charger_slots: tuple[tuple[str, int, int], ...]
    assignment: Any
    direction: str


@dataclass(frozen=True)
class PricingResult:
    columns: tuple[RouteColumn, ...]
    extensions: int
    complete_labels: int
    negative_routes: int
    changed_adjacency_routes: int
    resource_rank_changed_routes: int
    lp_primal_residual: float
    lp_stationarity_residual: float
    positive_resource_prices: int


def fleet_caps(bundle: Any) -> tuple[int, ...]:
    return tuple(
        int(bundle.fleet_caps_by_depot[depot][f"num_{vehicle_type}"])
        for depot in sorted(bundle.fleet_caps_by_depot)
        for vehicle_type in ("cv", "ev")
    )


def solve_initial_master(
    parents: tuple[Solution, ...],
    bundle: Any,
) -> tuple[tuple[str, ...], tuple[RouteColumn, ...], LpDualResult]:
    customers, columns = build_parent_route_pool(parents, bundle)
    duals = solve_pool_lp_duals(
        customers,
        columns,
        fleet_caps=fleet_caps(bundle),
        charger_caps=_station_charger_caps(bundle),
    )
    return customers, columns, duals


def _resource_prices(
    duals: LpDualResult,
) -> tuple[dict[int, float], dict[tuple[str, int, int], float]]:
    fleets: dict[int, float] = {}
    slots: dict[tuple[str, int, int], float] = {}
    for row in duals.resources:
        if row.key[0] == "fleet":
            fleets[int(row.key[1])] = float(row.scarcity)
        else:
            slots[(str(row.key[1]), int(row.key[2]), int(row.key[3]))] = float(
                row.scarcity
            )
    return fleets, slots


def _label_for_sequence(
    sequence: tuple[str, ...],
    bundle: Any,
    *,
    depot_id: str,
    vehicle_type: str,
    customer_duals: dict[str, float],
    fleet_price: float,
    slot_prices: dict[tuple[str, int, int], float],
    lane: str,
    cache: RouteLocalDecoderCache,
    direction: str,
) -> PricedLabel | None:
    skeleton = Solution(
        routes=[
            Route(
                "RSP-LABEL",
                vehicle_type,
                depot_id,
                [depot_id, *sequence, depot_id],
            )
        ]
    )
    try:
        options = build_route_assignment_options(
            skeleton,
            bundle,
            allowed_depots_by_route={0: frozenset({depot_id})},
            allowed_types_by_route={0: frozenset({vehicle_type})},
            route_local_cache=cache,
            dynamic_state_hash="STATIC",
        )[0]
    except (KeyError, NoFeasibleAssignmentError):
        return None
    labels = []
    for option in options:
        slot_penalty = sum(
            slot_prices.get(key, 0.0) for key in option.charger_slot_keys
        )
        resource_penalty = (
            fleet_price + slot_penalty if lane == "RESOURCE-SLOT" else 0.0
        )
        reduced = (
            float(option.route_local_cost)
            - sum(customer_duals[item] for item in sequence)
            + resource_penalty
        )
        labels.append(
            PricedLabel(
                sequence=sequence,
                depot_id=depot_id,
                vehicle_type=vehicle_type,
                cost=float(option.route_local_cost),
                reduced_cost=float(reduced),
                charger_slots=tuple(option.charger_slot_keys),
                assignment=option.assignment,
                direction=direction,
            )
        )
    return min(
        labels,
        key=lambda item: (
            item.reduced_cost,
            item.cost,
            item.charger_slots,
            repr(item.assignment),
        ),
    )


def dominates(left: PricedLabel, right: PricedLabel) -> bool:
    """Safe same-state dominance used by the frozen label buckets."""

    return bool(
        left.sequence[-1:] == right.sequence[-1:]
        and frozenset(left.sequence) == frozenset(right.sequence)
        and left.depot_id == right.depot_id
        and left.vehicle_type == right.vehicle_type
        and left.cost <= right.cost + TOL
        and left.reduced_cost <= right.reduced_cost + TOL
        and set(left.charger_slots).issubset(right.charger_slots)
    )


def merge_labels(
    forward: PricedLabel,
    backward: PricedLabel,
) -> tuple[str, ...] | None:
    if (
        forward.depot_id != backward.depot_id
        or forward.vehicle_type != backward.vehicle_type
        or set(forward.sequence) & set(backward.sequence)
    ):
        return None
    return (*forward.sequence, *backward.sequence)


def _old_adjacencies(parents: tuple[Solution, ...], bundle: Any) -> set[tuple[str, str]]:
    return {
        pair
        for parent in parents
        for route in parent.routes
        for pair in zip(
            customers_in_route(route, bundle),
            customers_in_route(route, bundle)[1:],
        )
    }


def _sparse_arcs(
    customers: tuple[str, ...],
    old_arcs: set[tuple[str, str]],
    bundle: Any,
    *,
    depot_id: str,
    vehicle_type: str,
    customer_duals: dict[str, float],
) -> dict[str, frozenset[str]]:
    vehicle = bundle.instance.vehicle_profile(vehicle_type)
    load = 0.5 * float(vehicle.payload_capacity_kg)
    result = {}
    for left in customers:
        ranked = []
        for right in customers:
            if left == right:
                continue
            kwargs = (
                {"fueling_depot_id": depot_id}
                if vehicle_type == "cv"
                else {"charging_depot_id": depot_id, "time_varying": True}
            )
            try:
                cost = float(
                    _proxy_arc_cost(
                        bundle,
                        left,
                        right,
                        load,
                        vehicle_type=vehicle_type,
                        **kwargs,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
            ranked.append((cost - customer_duals[right], right))
        new = {right for _, right in sorted(ranked)[:6]}
        inherited = {right for source, right in old_arcs if source == left}
        result[left] = frozenset(new | inherited)
    return result


def _expand_half(
    members: tuple[str, ...],
    bundle: Any,
    *,
    depot_id: str,
    vehicle_type: str,
    customer_duals: dict[str, float],
    fleet_price: float,
    slot_prices: dict[tuple[str, int, int], float],
    lane: str,
    cache: RouteLocalDecoderCache,
    arcs: dict[str, frozenset[str]],
    prepend: bool,
    max_extensions: int,
    deadline: float,
) -> tuple[tuple[PricedLabel, ...], int]:
    direction = "backward" if prepend else "forward"
    frontier = []
    extensions = 0
    for customer in members:
        label = _label_for_sequence(
            (customer,),
            bundle,
            depot_id=depot_id,
            vehicle_type=vehicle_type,
            customer_duals=customer_duals,
            fleet_price=fleet_price,
            slot_prices=slot_prices,
            lane=lane,
            cache=cache,
            direction=direction,
        )
        if label is not None:
            frontier.append(label)
    while frontier and len(frontier[0].sequence) < len(members):
        candidates = []
        for label in frontier:
            remaining = set(members) - set(label.sequence)
            for customer in sorted(remaining):
                if extensions >= max_extensions:
                    return tuple(frontier), extensions
                if time.perf_counter() > deadline:
                    raise TimeoutError("registered 60-second safety limit reached")
                if prepend:
                    if label.sequence[0] not in arcs.get(customer, frozenset()):
                        continue
                    sequence = (customer, *label.sequence)
                else:
                    if customer not in arcs.get(label.sequence[-1], frozenset()):
                        continue
                    sequence = (*label.sequence, customer)
                extensions += 1
                candidate = _label_for_sequence(
                    sequence,
                    bundle,
                    depot_id=depot_id,
                    vehicle_type=vehicle_type,
                    customer_duals=customer_duals,
                    fleet_price=fleet_price,
                    slot_prices=slot_prices,
                    lane=lane,
                    cache=cache,
                    direction=direction,
                )
                if candidate is not None:
                    candidates.append(candidate)
        if not candidates:
            break
        buckets: dict[tuple[frozenset[str], str], PricedLabel] = {}
        for candidate in sorted(
            candidates,
            key=lambda item: (
                item.reduced_cost,
                item.cost,
                item.sequence,
            ),
        ):
            endpoint = candidate.sequence[0] if prepend else candidate.sequence[-1]
            key = (frozenset(candidate.sequence), endpoint)
            current = buckets.get(key)
            if current is None or dominates(candidate, current):
                buckets[key] = candidate
        frontier = sorted(
            buckets.values(),
            key=lambda item: (item.reduced_cost, item.cost, item.sequence),
        )[:64]
    return tuple(frontier), extensions


def _column_key(column: RouteColumn) -> tuple[Any, ...]:
    assignment = column.payload["assignment"]
    return (
        column.customers,
        assignment.home_depot_id,
        assignment.vehicle_type,
        assignment.charge_strategy,
        float(assignment.carbon_weight),
        column.charger_use,
    )


def generate_priced_routes(
    start: Solution,
    parents: tuple[Solution, ...],
    bundle: Any,
    *,
    lane: str,
    max_extensions: int,
    max_routes: int,
    wall_seconds: float,
    dry_run: bool = False,
) -> PricingResult:
    if lane not in {"LOCAL", "RESOURCE-SLOT"}:
        raise ValueError(f"unsupported lane: {lane}")
    set_single_thread_environment()
    _, parent_columns, duals = solve_initial_master(parents, bundle)
    customer_duals = dict(duals.customer_marginals)
    fleet_prices, slot_prices = _resource_prices(duals)
    dimension = fleet_dimension(bundle)
    old_arcs = _old_adjacencies(parents, bundle)
    cache = RouteLocalDecoderCache()
    deadline = time.perf_counter() + float(wall_seconds)
    extensions = 0
    complete = []
    for route in start.routes:
        members = customers_in_route(route, bundle)
        if len(members) < 2:
            continue
        split = max(1, len(members) // 2)
        forward_members = members[:split]
        backward_members = members[split:]
        if not backward_members:
            backward_members = members[-1:]
            forward_members = members[:-1]
        depot_id = route.home_depot_id
        vehicle_type = route.vehicle_type.lower()
        arcs = _sparse_arcs(
            members,
            old_arcs,
            bundle,
            depot_id=depot_id,
            vehicle_type=vehicle_type,
            customer_duals=customer_duals,
        )
        fleet_index = dimension[(depot_id, vehicle_type)]
        remaining = max_extensions - extensions
        if remaining < 1:
            break
        forward, used = _expand_half(
            forward_members,
            bundle,
            depot_id=depot_id,
            vehicle_type=vehicle_type,
            customer_duals=customer_duals,
            fleet_price=fleet_prices.get(fleet_index, 0.0),
            slot_prices=slot_prices,
            lane=lane,
            cache=cache,
            arcs=arcs,
            prepend=False,
            max_extensions=max(1, remaining // 2),
            deadline=deadline,
        )
        extensions += used
        remaining = max_extensions - extensions
        if remaining < 1:
            break
        backward, used = _expand_half(
            backward_members,
            bundle,
            depot_id=depot_id,
            vehicle_type=vehicle_type,
            customer_duals=customer_duals,
            fleet_price=fleet_prices.get(fleet_index, 0.0),
            slot_prices=slot_prices,
            lane=lane,
            cache=cache,
            arcs=arcs,
            prepend=True,
            max_extensions=remaining,
            deadline=deadline,
        )
        extensions += used
        for left in forward:
            for right in backward:
                sequence = merge_labels(left, right)
                if sequence is None:
                    continue
                if right.sequence[0] not in arcs.get(
                    left.sequence[-1], frozenset()
                ):
                    continue
                merged = _label_for_sequence(
                    sequence,
                    bundle,
                    depot_id=depot_id,
                    vehicle_type=vehicle_type,
                    customer_duals=customer_duals,
                    fleet_price=fleet_prices.get(fleet_index, 0.0),
                    slot_prices=slot_prices,
                    lane=lane,
                    cache=cache,
                    direction="merged",
                )
                if merged is not None:
                    complete.append((members, merged))
        if dry_run and complete:
            break
    rows = []
    local_rank = sorted(
        complete,
        key=lambda item: (
            item[1].cost - sum(customer_duals[c] for c in item[1].sequence),
            item[1].sequence,
        ),
    )
    local_positions = {
        item[1].sequence: index for index, item in enumerate(local_rank)
    }
    resource_rank = sorted(
        complete,
        key=lambda item: (item[1].reduced_cost, item[1].sequence),
    )
    resource_positions = {
        item[1].sequence: index for index, item in enumerate(resource_rank)
    }
    for original, label in resource_rank:
        if label.reduced_cost >= -TOL:
            continue
        adjacency = set(zip(label.sequence, label.sequence[1:]))
        if not adjacency - old_arcs:
            continue
        delta = [0 for _ in dimension]
        delta[
            dimension[(label.assignment.home_depot_id, label.assignment.vehicle_type)]
        ] = 1
        rows.append(
            RouteColumn(
                customers=label.sequence,
                cost=label.cost,
                fleet_delta=tuple(delta),
                charger_use=tuple(
                    (station, day, slot, 1)
                    for station, day, slot in label.charger_slots
                ),
                payload={
                    "kind": "generated",
                    "assignment": label.assignment,
                    "reduced_cost": label.reduced_cost,
                    "changed_adjacencies": sorted(adjacency - old_arcs),
                    "resource_rank_changed": (
                        local_positions.get(label.sequence)
                        != resource_positions.get(label.sequence)
                    ),
                    "original_order": original,
                },
                source=f"resource_slot_pricing_{lane.lower()}",
            )
        )
    unique = {}
    for column in rows:
        current = unique.get(_column_key(column))
        if current is None or column.cost < current.cost:
            unique[_column_key(column)] = column
    selected = tuple(
        sorted(
            unique.values(),
            key=lambda column: (
                float(column.payload["reduced_cost"]),
                column.cost,
                column.customers,
            ),
        )[:max_routes]
    )
    return PricingResult(
        columns=selected,
        extensions=extensions,
        complete_labels=len(complete),
        negative_routes=len(selected),
        changed_adjacency_routes=sum(
            bool(column.payload["changed_adjacencies"]) for column in selected
        ),
        resource_rank_changed_routes=sum(
            bool(column.payload["resource_rank_changed"]) for column in selected
        ),
        lp_primal_residual=duals.primal_residual,
        lp_stationarity_residual=duals.stationarity_residual,
        positive_resource_prices=sum(row.scarcity > 0.0 for row in duals.resources),
    )
