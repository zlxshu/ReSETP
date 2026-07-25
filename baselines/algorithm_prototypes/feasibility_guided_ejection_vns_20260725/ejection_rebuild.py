"""Resource-guided contiguous-block ejection and beam reconstruction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from decoder_cache import RouteLocalDecoderCache
from feasible_moves import FeasibleMove, joint_feasibility_proxy
from setp_solver.algorithms.resetp_alns.operators.strong_bridge import (
    solution_signature_hash,
)
from setp_solver.solution import Route, Solution

from baselines.algorithm_prototypes.tailored_dp_vns_20260725.neighborhoods import (
    _customer_routes,
    _drop_empty_routes,
    _proxy_distance,
    _route_with_customers,
    customer_multiset,
)


@dataclass(frozen=True)
class RebuildStats:
    blocks_considered: int
    partial_structures_inspected: int
    partial_structures_feasible: int
    completed_structures: int


@dataclass(frozen=True)
class _BeamState:
    routes: tuple[Route, ...]
    route_local_cost: float
    detail: str


def generate_ejection_rebuild_moves(
    solution: Solution,
    bundle: Any,
    *,
    route_local_cache: RouteLocalDecoderCache,
    block_widths: tuple[int, ...] = (2, 3, 4),
    block_seed_limit: int = 8,
    beam_width: int = 8,
    nearest_anchor_count: int = 24,
    feasible_limit: int = 12,
) -> tuple[tuple[FeasibleMove, ...], RebuildStats]:
    """Eject contiguous blocks and reinsert customers one-by-one.

    Insertion positions are generated around fixed nearest-customer anchors,
    then every retained partial state must pass the route/joint-resource
    feasibility proxy before it can occupy the beam.
    """

    customer_ids = frozenset(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    )
    routes = _customer_routes(solution, customer_ids)
    baseline_customers = customer_multiset(solution, bundle)
    initial_signature = solution_signature_hash(Solution(routes=routes))
    blocks = _rank_blocks(
        routes,
        bundle,
        block_widths=block_widths,
    )[:block_seed_limit]
    completed: dict[str, FeasibleMove] = {}
    partial_inspected = 0
    partial_feasible = 0

    for source_index, start, width, saving in blocks:
        source_customers = list(routes[source_index].node_sequence[1:-1])
        block = tuple(source_customers[start : start + width])
        remaining = (
            source_customers[:start]
            + source_customers[start + width :]
        )
        base_routes = list(routes)
        base_routes[source_index] = _route_with_customers(
            base_routes[source_index],
            remaining,
        )
        base_routes = _drop_empty_routes(base_routes)
        for order_label, insertion_order in (
            ("forward", block),
            ("reverse", tuple(reversed(block))),
        ):
            try:
                base_cost, _ = joint_feasibility_proxy(
                    Solution(routes=base_routes),
                    bundle,
                    route_local_cache=route_local_cache,
                )
            except (KeyError, RuntimeError, TypeError, ValueError):
                continue
            beam = (
                _BeamState(
                    routes=tuple(base_routes),
                    route_local_cost=base_cost,
                    detail=(
                        f"source={source_index};start={start};width={width};"
                        f"order={order_label};saving={saving:.12f}"
                    ),
                ),
            )
            for customer in insertion_order:
                next_states: dict[str, _BeamState] = {}
                for state in beam:
                    for candidate_routes, insertion_detail in (
                        _granular_insertions(
                            state.routes,
                            customer,
                            bundle,
                            nearest_anchor_count=nearest_anchor_count,
                        )
                    ):
                        partial_inspected += 1
                        skeleton = Solution(routes=list(candidate_routes))
                        try:
                            local_cost, _ = joint_feasibility_proxy(
                                skeleton,
                                bundle,
                                route_local_cache=route_local_cache,
                            )
                        except (
                            KeyError,
                            RuntimeError,
                            TypeError,
                            ValueError,
                        ):
                            continue
                        partial_feasible += 1
                        signature = solution_signature_hash(skeleton)
                        candidate = _BeamState(
                            routes=tuple(candidate_routes),
                            route_local_cost=local_cost,
                            detail=(
                                f"{state.detail};insert={customer}:"
                                f"{insertion_detail}"
                            ),
                        )
                        previous = next_states.get(signature)
                        if previous is None or (
                            candidate.route_local_cost,
                            candidate.detail,
                        ) < (
                            previous.route_local_cost,
                            previous.detail,
                        ):
                            next_states[signature] = candidate
                beam = tuple(
                    sorted(
                        next_states.values(),
                        key=lambda item: (
                            item.route_local_cost,
                            item.detail,
                        ),
                    )[:beam_width]
                )
                if not beam:
                    break
            for state in beam:
                skeleton = Solution(routes=list(state.routes))
                signature = solution_signature_hash(skeleton)
                if signature == initial_signature:
                    continue
                if customer_multiset(skeleton, bundle) != baseline_customers:
                    continue
                distance_delta = (
                    _proxy_distance(list(state.routes), bundle)
                    - _proxy_distance(routes, bundle)
                )
                move = FeasibleMove(
                    neighborhood="ejection_rebuild",
                    skeleton=skeleton,
                    route_local_cost=state.route_local_cost,
                    distance_delta=float(distance_delta),
                    detail=state.detail,
                    assignment_candidate_count=1,
                )
                previous = completed.get(signature)
                if previous is None or (
                    move.route_local_cost,
                    move.distance_delta,
                    move.detail,
                ) < (
                    previous.route_local_cost,
                    previous.distance_delta,
                    previous.detail,
                ):
                    completed[signature] = move

    selected = tuple(
        sorted(
            completed.values(),
            key=lambda item: (
                item.route_local_cost,
                item.distance_delta,
                item.detail,
                solution_signature_hash(item.skeleton),
            ),
        )[:feasible_limit]
    )
    return (
        selected,
        RebuildStats(
            blocks_considered=len(blocks),
            partial_structures_inspected=partial_inspected,
            partial_structures_feasible=partial_feasible,
            completed_structures=len(completed),
        ),
    )


def _rank_blocks(
    routes: list[Route],
    bundle: Any,
    *,
    block_widths: tuple[int, ...],
) -> list[tuple[int, int, int, float]]:
    ranked: list[tuple[float, int, int, int]] = []
    for route_index, route in enumerate(routes):
        customers = list(route.node_sequence[1:-1])
        before = _route_distance(route, bundle)
        for width in block_widths:
            if width > len(customers):
                continue
            for start in range(len(customers) - width + 1):
                remaining = customers[:start] + customers[start + width :]
                after_route = _route_with_customers(route, remaining)
                saving = before - _route_distance(after_route, bundle)
                ranked.append((-saving, route_index, start, width))
    return [
        (route_index, start, width, -negative_saving)
        for negative_saving, route_index, start, width in sorted(ranked)
    ]


def _granular_insertions(
    routes: tuple[Route, ...],
    customer: str,
    bundle: Any,
    *,
    nearest_anchor_count: int,
) -> list[tuple[tuple[Route, ...], str]]:
    anchors = sorted(
        (
            float(bundle.instance.distance(customer, other)),
            other,
        )
        for route in routes
        for other in route.node_sequence[1:-1]
        if other != customer
    )[:nearest_anchor_count]
    anchor_ids = {node_id for _, node_id in anchors}
    proposals: dict[
        tuple[int, int],
        tuple[float, int, int],
    ] = {}
    for route_index, route in enumerate(routes):
        customers = list(route.node_sequence[1:-1])
        positions = {0, len(customers)}
        for position, node_id in enumerate(customers):
            if node_id in anchor_ids:
                positions.add(position)
                positions.add(position + 1)
        for position in positions:
            left = route.home_depot_id if position == 0 else customers[position - 1]
            right = (
                route.home_depot_id
                if position == len(customers)
                else customers[position]
            )
            delta = (
                float(bundle.instance.distance(left, customer))
                + float(bundle.instance.distance(customer, right))
                - float(bundle.instance.distance(left, right))
            )
            proposals[(route_index, position)] = (
                delta,
                route_index,
                position,
            )
    output: list[tuple[tuple[Route, ...], str]] = []
    for _, route_index, position in sorted(proposals.values()):
        changed = list(routes)
        customers = list(changed[route_index].node_sequence[1:-1])
        customers.insert(position, customer)
        changed[route_index] = _route_with_customers(
            changed[route_index],
            customers,
        )
        output.append(
            (
                tuple(changed),
                f"route={route_index};position={position}",
            )
        )
    return output


def _route_distance(route: Route, bundle: Any) -> float:
    return sum(
        float(bundle.instance.distance(left, right))
        for left, right in zip(
            route.node_sequence[:-1],
            route.node_sequence[1:],
        )
    )

