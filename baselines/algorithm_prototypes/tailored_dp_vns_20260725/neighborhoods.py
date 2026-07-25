"""Systematic route neighbourhoods for the tailored DP-VNS redesign."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from setp_solver.solution import Route, Solution
from setp_solver.algorithms.resetp_alns.operators.strong_bridge import (
    solution_signature_hash,
)


NEIGHBORHOOD_ORDER = (
    "relocate",
    "swap",
    "two_opt",
    "two_opt_star",
    "block_rebuild",
)


@dataclass(frozen=True)
class SkeletonCandidate:
    neighborhood: str
    skeleton: Solution
    proxy_delta: float
    detail: str


def generate_ranked_candidates(
    solution: Solution,
    bundle: Any,
    *,
    neighborhood: str,
    limit: int,
) -> tuple[SkeletonCandidate, ...]:
    """Generate a deterministic, result-blind shortlist for one neighbourhood."""

    if neighborhood not in NEIGHBORHOOD_ORDER:
        raise ValueError(f"unknown neighbourhood {neighborhood!r}")
    if limit < 1:
        raise ValueError("candidate limit must be positive")

    customer_ids = frozenset(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    )
    routes = _customer_routes(solution, customer_ids)
    before = _proxy_distance(routes, bundle)
    generator = {
        "relocate": _relocate_candidates,
        "swap": _swap_candidates,
        "two_opt": _two_opt_candidates,
        "two_opt_star": _two_opt_star_candidates,
        "block_rebuild": _block_rebuild_candidates,
    }[neighborhood]

    unique: dict[str, SkeletonCandidate] = {}
    for changed_routes, detail in generator(routes):
        normalized = _drop_empty_routes(changed_routes)
        if not normalized:
            continue
        skeleton = Solution(routes=normalized)
        signature = solution_signature_hash(skeleton)
        if signature == solution_signature_hash(Solution(routes=routes)):
            continue
        proxy_delta = _proxy_distance(normalized, bundle) - before
        candidate = SkeletonCandidate(
            neighborhood=neighborhood,
            skeleton=skeleton,
            proxy_delta=float(proxy_delta),
            detail=detail,
        )
        incumbent = unique.get(signature)
        if incumbent is None or (
            candidate.proxy_delta,
            candidate.detail,
        ) < (
            incumbent.proxy_delta,
            incumbent.detail,
        ):
            unique[signature] = candidate

    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (
                item.proxy_delta,
                item.detail,
                solution_signature_hash(item.skeleton),
            ),
        )[:limit]
    )


def customer_multiset(solution: Solution, bundle: Any) -> tuple[str, ...]:
    customer_ids = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    return tuple(
        sorted(
            node_id
            for route in solution.routes
            for node_id in route.node_sequence
            if node_id in customer_ids
        )
    )


def _customer_routes(
    solution: Solution,
    customer_ids: frozenset[str],
) -> list[Route]:
    routes: list[Route] = []
    for route in solution.routes:
        customers = [
            node_id
            for node_id in route.node_sequence
            if node_id in customer_ids
        ]
        if not customers:
            continue
        routes.append(_route_with_customers(route, customers))
    return routes


def _route_with_customers(route: Route, customers: Iterable[str]) -> Route:
    sequence = tuple(customers)
    return Route(
        vehicle_id=route.vehicle_id,
        vehicle_type=route.vehicle_type,
        home_depot_id=route.home_depot_id,
        node_sequence=[
            route.home_depot_id,
            *sequence,
            route.home_depot_id,
        ],
    )


def _copy_routes(routes: list[Route]) -> list[Route]:
    return [
        _route_with_customers(route, route.node_sequence[1:-1])
        for route in routes
    ]


def _drop_empty_routes(routes: list[Route]) -> list[Route]:
    return [
        route
        for route in routes
        if len(route.node_sequence) > 2
    ]


def _proxy_distance(routes: list[Route], bundle: Any) -> float:
    return sum(
        float(bundle.instance.distance(left, right))
        for route in routes
        for left, right in zip(
            route.node_sequence[:-1],
            route.node_sequence[1:],
        )
    )


def _relocate_candidates(
    routes: list[Route],
) -> Iterable[tuple[list[Route], str]]:
    for source_index, source in enumerate(routes):
        source_customers = list(source.node_sequence[1:-1])
        for source_position, customer in enumerate(source_customers):
            for target_index, target in enumerate(routes):
                target_customers = list(target.node_sequence[1:-1])
                for target_position in range(len(target_customers) + 1):
                    if source_index == target_index and target_position in {
                        source_position,
                        source_position + 1,
                    }:
                        continue
                    changed = _copy_routes(routes)
                    changed_source = list(
                        changed[source_index].node_sequence[1:-1]
                    )
                    moved = changed_source.pop(source_position)
                    if source_index == target_index:
                        adjusted = target_position
                        if target_position > source_position:
                            adjusted -= 1
                        changed_source.insert(adjusted, moved)
                        changed[source_index] = _route_with_customers(
                            changed[source_index],
                            changed_source,
                        )
                    else:
                        changed_target = list(
                            changed[target_index].node_sequence[1:-1]
                        )
                        changed_target.insert(target_position, moved)
                        changed[source_index] = _route_with_customers(
                            changed[source_index],
                            changed_source,
                        )
                        changed[target_index] = _route_with_customers(
                            changed[target_index],
                            changed_target,
                        )
                    yield (
                        changed,
                        (
                            f"customer={customer};source={source_index}:"
                            f"{source_position};target={target_index}:"
                            f"{target_position}"
                        ),
                    )


def _swap_candidates(
    routes: list[Route],
) -> Iterable[tuple[list[Route], str]]:
    positions = [
        (route_index, position, customer)
        for route_index, route in enumerate(routes)
        for position, customer in enumerate(route.node_sequence[1:-1])
    ]
    for left_index, left in enumerate(positions):
        for right in positions[left_index + 1 :]:
            left_route, left_position, left_customer = left
            right_route, right_position, right_customer = right
            changed = _copy_routes(routes)
            left_customers = list(changed[left_route].node_sequence[1:-1])
            right_customers = list(changed[right_route].node_sequence[1:-1])
            if left_route == right_route:
                left_customers[left_position], left_customers[right_position] = (
                    left_customers[right_position],
                    left_customers[left_position],
                )
                changed[left_route] = _route_with_customers(
                    changed[left_route],
                    left_customers,
                )
            else:
                left_customers[left_position] = right_customer
                right_customers[right_position] = left_customer
                changed[left_route] = _route_with_customers(
                    changed[left_route],
                    left_customers,
                )
                changed[right_route] = _route_with_customers(
                    changed[right_route],
                    right_customers,
                )
            yield (
                changed,
                (
                    f"left={left_route}:{left_position}:{left_customer};"
                    f"right={right_route}:{right_position}:{right_customer}"
                ),
            )


def _two_opt_candidates(
    routes: list[Route],
) -> Iterable[tuple[list[Route], str]]:
    for route_index, route in enumerate(routes):
        customers = list(route.node_sequence[1:-1])
        for start in range(len(customers) - 1):
            for stop in range(start + 2, len(customers) + 1):
                changed = _copy_routes(routes)
                updated = (
                    customers[:start]
                    + list(reversed(customers[start:stop]))
                    + customers[stop:]
                )
                changed[route_index] = _route_with_customers(
                    changed[route_index],
                    updated,
                )
                yield (
                    changed,
                    f"route={route_index};segment={start}:{stop}",
                )


def _two_opt_star_candidates(
    routes: list[Route],
) -> Iterable[tuple[list[Route], str]]:
    for left_index, left in enumerate(routes):
        left_customers = list(left.node_sequence[1:-1])
        for right_index in range(left_index + 1, len(routes)):
            right = routes[right_index]
            right_customers = list(right.node_sequence[1:-1])
            for left_cut in range(1, len(left_customers) + 1):
                for right_cut in range(1, len(right_customers) + 1):
                    new_left = (
                        left_customers[:left_cut]
                        + right_customers[right_cut:]
                    )
                    new_right = (
                        right_customers[:right_cut]
                        + left_customers[left_cut:]
                    )
                    if not new_left or not new_right:
                        continue
                    changed = _copy_routes(routes)
                    changed[left_index] = _route_with_customers(
                        changed[left_index],
                        new_left,
                    )
                    changed[right_index] = _route_with_customers(
                        changed[right_index],
                        new_right,
                    )
                    yield (
                        changed,
                        (
                            f"left={left_index}:{left_cut};"
                            f"right={right_index}:{right_cut}"
                        ),
                    )


def _block_rebuild_candidates(
    routes: list[Route],
) -> Iterable[tuple[list[Route], str]]:
    for source_index, source in enumerate(routes):
        source_customers = list(source.node_sequence[1:-1])
        max_width = min(6, len(source_customers))
        for width in range(2, max_width + 1):
            for start in range(len(source_customers) - width + 1):
                block = source_customers[start : start + width]
                remaining = (
                    source_customers[:start]
                    + source_customers[start + width :]
                )
                for target_index, target in enumerate(routes):
                    target_customers = list(target.node_sequence[1:-1])
                    if target_index == source_index:
                        target_customers = remaining
                    for target_position in range(len(target_customers) + 1):
                        for reverse in (False, True):
                            inserted = (
                                list(reversed(block))
                                if reverse
                                else list(block)
                            )
                            rebuilt = (
                                target_customers[:target_position]
                                + inserted
                                + target_customers[target_position:]
                            )
                            if (
                                target_index == source_index
                                and rebuilt == source_customers
                            ):
                                continue
                            changed = _copy_routes(routes)
                            changed[source_index] = _route_with_customers(
                                changed[source_index],
                                remaining,
                            )
                            changed[target_index] = _route_with_customers(
                                changed[target_index],
                                rebuilt,
                            )
                            yield (
                                changed,
                                (
                                    f"source={source_index}:{start}:{width};"
                                    f"target={target_index}:{target_position};"
                                    f"reverse={int(reverse)}"
                                ),
                            )

