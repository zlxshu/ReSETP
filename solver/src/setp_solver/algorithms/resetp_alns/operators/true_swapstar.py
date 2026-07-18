"""Budgeted true SWAP* local-search component.

The neighbourhood follows Vidal (2022): two clients on different routes are
removed, then each is freely reinserted into the other route.  The top-three
insertion idea and the 0.05 route-angle overlap default are independently
reimplemented from the public HGS/PyVRP descriptions; no external source code
is copied.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Mapping

from setp_solver.algorithms.resetp_alns.operators.local_search import (
    _candidate_with_route_customers,
    _route_customers,
)
from setp_solver.algorithms.resetp_alns.runtime.budgeted_scoring import (
    SearchBudgetExhausted,
    can_score_search_candidate,
    score_search_candidate,
)
from setp_solver.search.evaluation import EvaluationContext
from setp_solver.solution import Solution


TOL = 1e-9


@dataclass(frozen=True)
class TrueSwapStarConfig:
    """Frozen development parameters backed by Vidal/PyVRP."""

    overlap_tolerance: float = 0.05
    top_insertions: int = 3
    max_runtime_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.overlap_tolerance <= 1.0:
            raise ValueError("overlap_tolerance must be in [0, 1]")
        if self.top_insertions <= 0:
            raise ValueError("top_insertions must be positive")
        if self.max_runtime_seconds <= 0:
            raise ValueError("max_runtime_seconds must be positive")


@dataclass(frozen=True)
class TrueSwapStarMove:
    """One free-reinsertion exchange proposal."""

    left_route_idx: int
    right_route_idx: int
    left_customer: str
    right_customer: str
    left_insert_idx: int
    right_insert_idx: int
    distance_delta: float


@dataclass(frozen=True)
class TrueSwapStarResult:
    """Auditable outcome of one bounded SWAP* intensification."""

    solution: Solution
    objective: float
    evaluations_used: int
    proxy_moves_considered: int
    feasibility_checks: int
    feasible_candidates: int
    accepted_moves: tuple[TrueSwapStarMove, ...]
    elapsed_seconds: float
    stop_reason: str


def true_swapstar_intensify(
    solution: Solution,
    context: EvaluationContext,
    *,
    incumbent_objective: float,
    max_evaluations: int,
    config: TrueSwapStarConfig = TrueSwapStarConfig(),
) -> TrueSwapStarResult:
    """Apply improving true-SWAP* moves within an exact complete-score budget."""

    if max_evaluations < 0:
        raise ValueError("max_evaluations must be non-negative")
    started = time.perf_counter()
    best = solution
    best_objective = float(incumbent_objective)
    evaluations_used = 0
    proxy_moves_considered = 0
    feasibility_checks = 0
    feasible_candidates = 0
    accepted_moves: list[TrueSwapStarMove] = []
    stop_reason = "evaluation_limit_reached"

    if max_evaluations == 0:
        return TrueSwapStarResult(
            solution=best,
            objective=best_objective,
            evaluations_used=0,
            proxy_moves_considered=0,
            feasibility_checks=0,
            feasible_candidates=0,
            accepted_moves=(),
            elapsed_seconds=max(0.0, time.perf_counter() - started),
            stop_reason="zero_evaluation_budget",
        )

    while evaluations_used < max_evaluations:
        if time.perf_counter() - started >= config.max_runtime_seconds:
            stop_reason = "runtime_limit_reached"
            break
        moves = _ranked_true_swapstar_moves(best, context, config=config)
        proxy_moves_considered += len(moves)
        if not moves:
            stop_reason = "no_negative_proxy_move"
            break

        improved = False
        for move in moves:
            if time.perf_counter() - started >= config.max_runtime_seconds:
                stop_reason = "runtime_limit_reached"
                break
            candidate = _apply_move(best, context, move)
            feasibility_checks += 1
            if candidate is None:
                continue
            feasible_candidates += 1
            if not can_score_search_candidate(context):
                stop_reason = "shared_budget_exhausted"
                break
            try:
                prepared, objective = score_search_candidate(
                    candidate,
                    context,
                    channel="true_swapstar",
                )
            except SearchBudgetExhausted:
                stop_reason = "shared_budget_exhausted"
                break
            evaluations_used += 1
            if objective < best_objective - TOL:
                best = prepared
                best_objective = float(objective)
                accepted_moves.append(move)
                improved = True
                break
            if evaluations_used >= max_evaluations:
                stop_reason = "evaluation_limit_reached"
                break

        if stop_reason in {"runtime_limit_reached", "shared_budget_exhausted"}:
            break
        if evaluations_used >= max_evaluations:
            stop_reason = "evaluation_limit_reached"
            break
        if not improved:
            stop_reason = "no_improving_full_candidate"
            break

    return TrueSwapStarResult(
        solution=best,
        objective=best_objective,
        evaluations_used=evaluations_used,
        proxy_moves_considered=proxy_moves_considered,
        feasibility_checks=feasibility_checks,
        feasible_candidates=feasible_candidates,
        accepted_moves=tuple(accepted_moves),
        elapsed_seconds=max(0.0, time.perf_counter() - started),
        stop_reason=stop_reason,
    )


def _ranked_true_swapstar_moves(
    solution: Solution,
    context: EvaluationContext,
    *,
    config: TrueSwapStarConfig,
) -> list[TrueSwapStarMove]:
    instance = context.instance
    node_lookup = {node.node_id: node for node in instance.nodes}
    customers_by_route = [
        _route_customers(route, instance) for route in solution.routes
    ]
    global_centroid = _global_customer_centroid(instance)
    capacity = _capacity(context)
    route_loads = [
        sum(float(node_lookup[node_id].demand) for node_id in customers)
        for customers in customers_by_route
    ]
    route_distances = [
        _route_distance(route.home_depot_id, customers, instance)
        for route, customers in zip(solution.routes, customers_by_route)
    ]
    moves: list[TrueSwapStarMove] = []

    for left_idx, left_route in enumerate(solution.routes):
        left_customers = customers_by_route[left_idx]
        if not left_customers:
            continue
        for right_idx in range(left_idx + 1, len(solution.routes)):
            right_route = solution.routes[right_idx]
            right_customers = customers_by_route[right_idx]
            if not right_customers:
                continue
            if (
                left_route.home_depot_id != right_route.home_depot_id
                or left_route.vehicle_type.lower()
                != right_route.vehicle_type.lower()
            ):
                continue
            if not _routes_overlap(
                left_customers,
                right_customers,
                node_lookup,
                global_centroid,
                tolerance=config.overlap_tolerance,
            ):
                continue

            for left_pos, left_customer in enumerate(left_customers):
                left_node = node_lookup[left_customer]
                stripped_left = [
                    item
                    for pos, item in enumerate(left_customers)
                    if pos != left_pos
                ]
                stripped_left_distance = _route_distance(
                    left_route.home_depot_id,
                    stripped_left,
                    instance,
                )
                for right_pos, right_customer in enumerate(right_customers):
                    right_node = node_lookup[right_customer]
                    if (
                        route_loads[left_idx]
                        - float(left_node.demand)
                        + float(right_node.demand)
                        > capacity + TOL
                        or route_loads[right_idx]
                        - float(right_node.demand)
                        + float(left_node.demand)
                        > capacity + TOL
                    ):
                        continue
                    stripped_right = [
                        item
                        for pos, item in enumerate(right_customers)
                        if pos != right_pos
                    ]
                    stripped_right_distance = _route_distance(
                        right_route.home_depot_id,
                        stripped_right,
                        instance,
                    )
                    left_insertions = _top_insertion_positions(
                        left_route.home_depot_id,
                        stripped_left,
                        right_customer,
                        instance,
                        count=config.top_insertions,
                    )
                    right_insertions = _top_insertion_positions(
                        right_route.home_depot_id,
                        stripped_right,
                        left_customer,
                        instance,
                        count=config.top_insertions,
                    )
                    for left_insert_idx, left_delta in left_insertions:
                        for right_insert_idx, right_delta in right_insertions:
                            distance_delta = (
                                stripped_left_distance
                                + left_delta
                                + stripped_right_distance
                                + right_delta
                                - route_distances[left_idx]
                                - route_distances[right_idx]
                            )
                            if distance_delta >= -TOL:
                                continue
                            moves.append(
                                TrueSwapStarMove(
                                    left_route_idx=left_idx,
                                    right_route_idx=right_idx,
                                    left_customer=left_customer,
                                    right_customer=right_customer,
                                    left_insert_idx=left_insert_idx,
                                    right_insert_idx=right_insert_idx,
                                    distance_delta=float(distance_delta),
                                )
                            )

    return sorted(
        moves,
        key=lambda move: (
            move.distance_delta,
            move.left_route_idx,
            move.right_route_idx,
            move.left_customer,
            move.right_customer,
            move.left_insert_idx,
            move.right_insert_idx,
        ),
    )


def _apply_move(
    solution: Solution,
    context: EvaluationContext,
    move: TrueSwapStarMove,
) -> Solution | None:
    left_route = solution.routes[move.left_route_idx]
    right_route = solution.routes[move.right_route_idx]
    left_customers = _route_customers(left_route, context.instance)
    right_customers = _route_customers(right_route, context.instance)
    if (
        move.left_customer not in left_customers
        or move.right_customer not in right_customers
    ):
        return None
    new_left = [
        customer
        for customer in left_customers
        if customer != move.left_customer
    ]
    new_right = [
        customer
        for customer in right_customers
        if customer != move.right_customer
    ]
    if not 0 <= move.left_insert_idx <= len(new_left):
        return None
    if not 0 <= move.right_insert_idx <= len(new_right):
        return None
    new_left.insert(move.left_insert_idx, move.right_customer)
    new_right.insert(move.right_insert_idx, move.left_customer)
    return _candidate_with_route_customers(
        solution,
        context,
        {
            move.left_route_idx: new_left,
            move.right_route_idx: new_right,
        },
    )


def _top_insertion_positions(
    home_depot_id: str,
    customers: list[str],
    customer_id: str,
    instance: Any,
    *,
    count: int,
) -> list[tuple[int, float]]:
    positions: list[tuple[float, int]] = []
    for insert_idx in range(len(customers) + 1):
        previous = (
            home_depot_id if insert_idx == 0 else customers[insert_idx - 1]
        )
        following = (
            home_depot_id if insert_idx == len(customers) else customers[insert_idx]
        )
        delta = (
            float(instance.distance(previous, customer_id))
            + float(instance.distance(customer_id, following))
            - float(instance.distance(previous, following))
        )
        positions.append((delta, insert_idx))
    return [
        (insert_idx, float(delta))
        for delta, insert_idx in sorted(positions, key=lambda item: (item[0], item[1]))[
            :count
        ]
    ]


def _route_distance(
    home_depot_id: str,
    customers: list[str],
    instance: Any,
) -> float:
    sequence = [home_depot_id, *customers, home_depot_id]
    return sum(
        float(instance.distance(left, right))
        for left, right in zip(sequence, sequence[1:])
    )


def _global_customer_centroid(instance: Any) -> tuple[float, float]:
    customers = [
        node for node in instance.nodes if str(node.node_type).lower() == "c"
    ]
    if not customers:
        return (0.0, 0.0)
    return (
        sum(float(node.x) for node in customers) / len(customers),
        sum(float(node.y) for node in customers) / len(customers),
    )


def _routes_overlap(
    left_customers: list[str],
    right_customers: list[str],
    node_lookup: Mapping[str, Any],
    global_centroid: tuple[float, float],
    *,
    tolerance: float,
) -> bool:
    if tolerance >= 1.0:
        return True

    def angle(customers: list[str]) -> float:
        x = sum(float(node_lookup[item].x) for item in customers) / len(customers)
        y = sum(float(node_lookup[item].y) for item in customers) / len(customers)
        return math.atan2(y - global_centroid[1], x - global_centroid[0])

    difference = abs(angle(left_customers) - angle(right_customers))
    tau = 2.0 * math.pi
    return (
        difference <= tolerance * tau
        or difference >= (1.0 - tolerance) * tau
    )


def _capacity(context: EvaluationContext) -> float:
    prices = context.prices
    if isinstance(prices, Mapping):
        return float(prices.get("Q_capacity", math.inf))
    return float(getattr(prices, "Q_capacity", math.inf))
