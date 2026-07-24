"""Problem-specific destroy plans for the China81 HGS--RR candidate.

These pure functions only select what must be rebuilt.  They do not score,
repair, or accept a candidate, so no search result can be produced by this
module alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import random

from setp_solver.instance_loader import Instance
from setp_solver.solution import Route, Solution


class OperatorKind(str, Enum):
    CROSS_DEPOT_ROUTE_REASSIGNMENT = "cross_depot_route_reassignment"
    BIDIRECTIONAL_CROSS_DEPOT_SEGMENT = (
        "bidirectional_cross_depot_segment"
    )
    VEHICLE_TYPE_FLIP = "vehicle_type_flip"
    CHARGE_DEPARTURE_RETIMING = "charge_departure_retiming"
    TIME_WINDOW_PRESSURE_STRING = "time_window_pressure_string"
    DYNAMIC_UNEXECUTED_TAIL = "dynamic_unexecuted_tail"


@dataclass(frozen=True)
class DestroyPlan:
    kind: OperatorKind
    route_indices: tuple[int, ...]
    removed_customer_ids: tuple[str, ...]
    target_depot_ids: tuple[str, ...] = ()
    target_vehicle_types: tuple[str, ...] = ()
    preserved_customer_ids: tuple[str, ...] = ()
    reason: str = ""


def cross_depot_route_reassignment_plan(
    solution: Solution,
    *,
    route_index: int,
    depot_ids: tuple[str, ...],
) -> DestroyPlan:
    route = _route_at(solution, route_index)
    targets = tuple(
        depot_id
        for depot_id in depot_ids
        if depot_id != route.home_depot_id
    )
    if not targets:
        raise ValueError(
            "cross-depot reassignment requires another depot"
        )
    customers = _route_customers(route)
    if not customers:
        raise ValueError("cannot reassign an empty route")
    return DestroyPlan(
        kind=OperatorKind.CROSS_DEPOT_ROUTE_REASSIGNMENT,
        route_indices=(route_index,),
        removed_customer_ids=customers,
        target_depot_ids=targets,
        target_vehicle_types=("cv", "ev"),
        reason=(
            "rebuild the whole route under another depot, finite fleet, "
            "vehicle type, charging, tariff, carbon, and diesel mapping"
        ),
    )


def bidirectional_cross_depot_segment_plan(
    solution: Solution,
    *,
    first_route_index: int,
    second_route_index: int,
    rng: random.Random,
    max_segment_length: int = 4,
) -> DestroyPlan:
    first = _route_at(solution, first_route_index)
    second = _route_at(solution, second_route_index)
    if first.home_depot_id == second.home_depot_id:
        raise ValueError(
            "bidirectional exchange requires different home depots"
        )
    first_segment = _sample_segment(
        _route_customers(first),
        rng,
        max_segment_length=max_segment_length,
    )
    second_segment = _sample_segment(
        _route_customers(second),
        rng,
        max_segment_length=max_segment_length,
    )
    return DestroyPlan(
        kind=OperatorKind.BIDIRECTIONAL_CROSS_DEPOT_SEGMENT,
        route_indices=(first_route_index, second_route_index),
        removed_customer_ids=tuple(
            [*first_segment, *second_segment]
        ),
        target_depot_ids=(
            first.home_depot_id,
            second.home_depot_id,
        ),
        target_vehicle_types=("cv", "ev"),
        reason=(
            "exchange customer strings across depots and jointly rebuild "
            "route, vehicle, charging, and time decisions"
        ),
    )


def vehicle_type_flip_plan(
    solution: Solution,
    *,
    route_index: int,
) -> DestroyPlan:
    route = _route_at(solution, route_index)
    current = route.vehicle_type.strip().lower()
    if current not in {"cv", "ev"}:
        raise ValueError(
            f"unsupported vehicle type for flip: {route.vehicle_type!r}"
        )
    return DestroyPlan(
        kind=OperatorKind.VEHICLE_TYPE_FLIP,
        route_indices=(route_index,),
        removed_customer_ids=_route_customers(route),
        target_depot_ids=(route.home_depot_id,),
        target_vehicle_types=(
            ("ev",) if current == "cv" else ("cv",)
        ),
        reason=(
            "re-evaluate fixed cost, finite fleet, fuel or charging, "
            "time-varying price, and carbon under the opposite type"
        ),
    )


def charge_departure_retiming_plan(
    solution: Solution,
    *,
    route_index: int,
) -> DestroyPlan:
    route = _route_at(solution, route_index)
    if route.vehicle_type.strip().lower() != "ev":
        raise ValueError(
            "charge/departure retiming only applies to an EV route"
        )
    return DestroyPlan(
        kind=OperatorKind.CHARGE_DEPARTURE_RETIMING,
        route_indices=(route_index,),
        removed_customer_ids=(),
        target_depot_ids=(route.home_depot_id,),
        target_vehicle_types=("ev",),
        preserved_customer_ids=_route_customers(route),
        reason=(
            "keep customers but rebuild charge location, amount, start "
            "time, and departure time against half-hour price and carbon"
        ),
    )


def time_window_pressure_string_plan(
    solution: Solution,
    instance: Instance,
    *,
    radius: int = 1,
) -> DestroyPlan:
    if radius < 0:
        raise ValueError("time-window radius must be non-negative")
    node_by_id = {node.node_id: node for node in instance.nodes}
    candidates: list[tuple[float, int, int]] = []
    for route_index, route in enumerate(solution.routes):
        customers = _route_customers(route)
        for position, customer_id in enumerate(customers):
            node = node_by_id.get(customer_id)
            if node is None:
                raise ValueError(
                    f"customer {customer_id!r} missing from instance"
                )
            width = float(node.due_time) - float(node.ready_time)
            candidates.append((width, route_index, position))
    if not candidates:
        raise ValueError("solution has no customer to stress")
    _, route_index, position = min(candidates)
    customers = _route_customers(solution.routes[route_index])
    left = max(0, position - radius)
    right = min(len(customers), position + radius + 1)
    return DestroyPlan(
        kind=OperatorKind.TIME_WINDOW_PRESSURE_STRING,
        route_indices=(route_index,),
        removed_customer_ids=customers[left:right],
        target_vehicle_types=("cv", "ev"),
        reason=(
            "remove the narrowest-window customer and adjacent string, "
            "then rebuild across depots, types, and charge schedules"
        ),
    )


def dynamic_unexecuted_tail_plan(
    solution: Solution,
    *,
    route_index: int,
    executed_customer_ids: frozenset[str],
) -> DestroyPlan:
    route = _route_at(solution, route_index)
    customers = _route_customers(route)
    split = 0
    while (
        split < len(customers)
        and customers[split] in executed_customer_ids
    ):
        split += 1
    if any(
        customer_id in executed_customer_ids
        for customer_id in customers[split:]
    ):
        raise ValueError(
            "executed customers must form a frozen route prefix"
        )
    movable = customers[split:]
    if not movable:
        raise ValueError("route has no unexecuted tail to rebuild")
    return DestroyPlan(
        kind=OperatorKind.DYNAMIC_UNEXECUTED_TAIL,
        route_indices=(route_index,),
        removed_customer_ids=movable,
        target_depot_ids=(route.home_depot_id,),
        target_vehicle_types=("cv", "ev"),
        preserved_customer_ids=customers[:split],
        reason=(
            "preserve executed facts and rebuild only the unexecuted tail "
            "from inherited vehicle time, load, location, and battery"
        ),
    )


def _route_at(solution: Solution, route_index: int) -> Route:
    try:
        return solution.routes[int(route_index)]
    except IndexError as exc:
        raise ValueError(
            f"route index out of range: {route_index}"
        ) from exc


def _route_customers(route: Route) -> tuple[str, ...]:
    return tuple(route.node_sequence[1:-1])


def _sample_segment(
    customers: tuple[str, ...],
    rng: random.Random,
    *,
    max_segment_length: int,
) -> tuple[str, ...]:
    if not customers:
        raise ValueError("cannot sample an empty route segment")
    if max_segment_length < 1:
        raise ValueError("max segment length must be positive")
    length = rng.randint(
        1,
        min(int(max_segment_length), len(customers)),
    )
    start = rng.randint(0, len(customers) - length)
    return customers[start : start + length]
