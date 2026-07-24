"""Fast result-blind customer reconstruction for mechanism-aware RR."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any

from setp_solver.china81 import China81Bundle
from setp_solver.solution import Route, Solution


@dataclass(frozen=True)
class RecreateStep:
    customer_id: str
    route_index: int
    position: int
    opened_new_route: bool
    best_delta: float
    regret: float


@dataclass(frozen=True)
class RecreateResult:
    skeleton: Solution
    steps: tuple[RecreateStep, ...]
    removed_count: int
    opened_route_count: int


def remove_customers_from_skeleton(
    solution: Solution,
    customer_ids: tuple[str, ...],
    *,
    known_customer_ids: frozenset[str],
) -> Solution:
    """Remove customers and all charging actions from a route skeleton."""

    removed = set(customer_ids)
    routes: list[Route] = []
    for route_index, route in enumerate(solution.routes):
        customers = [
            node_id
            for node_id in route.node_sequence
            if (node_id in known_customer_ids and node_id not in removed)
        ]
        if not customers:
            continue
        routes.append(
            Route(
                vehicle_id=f"RR-SKEL-{route_index:03d}",
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


def recreate_removed_customers(
    partial: Solution,
    removed_customer_ids: tuple[str, ...],
    bundle: China81Bundle,
    *,
    rng: random.Random,
) -> RecreateResult:
    """Regret-2 reconstruction over all routes and both depots.

    The method uses distance, time-window pressure, capacity lower bounds, and
    depot ownership only for cheap ranking.  It does not decide vehicle type
    or charging; the finite-fleet assignment DP and complete evaluator do that
    after reconstruction.
    """

    pending = list(dict.fromkeys(removed_customer_ids))
    if not pending:
        return RecreateResult(
            skeleton=partial,
            steps=(),
            removed_count=0,
            opened_route_count=0,
        )
    node_by_id = {node.node_id: node for node in bundle.instance.nodes}
    depots = tuple(sorted(bundle.fleet_caps_by_depot))
    if len(depots) < 2:
        raise ValueError("mechanism-aware reconstruction requires two depots")
    max_payload = max(
        _profile_payload_capacity(bundle, vehicle_type) for vehicle_type in ("cv", "ev")
    )
    max_routes = sum(
        int(caps["num_cv"]) + int(caps["num_ev"])
        for caps in bundle.fleet_caps_by_depot.values()
    )
    current = partial
    steps: list[RecreateStep] = []
    while pending:
        customer_options: list[tuple[float, float, str, list[_Insertion]]] = []
        for customer_id in pending:
            if customer_id not in node_by_id:
                raise ValueError(f"removed customer {customer_id!r} is unknown")
            options = _enumerate_insertions(
                current,
                customer_id,
                bundle,
                depots=depots,
                max_payload=max_payload,
                max_routes=max_routes,
                node_by_id=node_by_id,
            )
            if not options:
                raise ValueError(f"no reconstruction insertion for {customer_id}")
            options.sort(key=lambda item: item.sort_key)
            best = options[0].score
            second = options[1].score if len(options) > 1 else best
            regret = second - best
            customer_options.append((-regret, best, customer_id, options))
        _, _, customer_id, options = min(
            customer_options,
            key=lambda item: (
                item[0],
                item[1],
                item[2],
            ),
        )
        tied = [
            option
            for option in options
            if abs(option.score - options[0].score) <= 1.0e-12
        ]
        selected = tied[rng.randrange(len(tied))] if len(tied) > 1 else options[0]
        current = selected.solution
        second_score = options[1].score if len(options) > 1 else selected.score
        steps.append(
            RecreateStep(
                customer_id=customer_id,
                route_index=selected.route_index,
                position=selected.position,
                opened_new_route=selected.opened_new_route,
                best_delta=selected.score,
                regret=second_score - selected.score,
            )
        )
        pending.remove(customer_id)
    return RecreateResult(
        skeleton=current,
        steps=tuple(steps),
        removed_count=len(removed_customer_ids),
        opened_route_count=sum(step.opened_new_route for step in steps),
    )


@dataclass(frozen=True)
class _Insertion:
    score: float
    solution: Solution
    route_index: int
    position: int
    opened_new_route: bool
    depot_id: str

    @property
    def sort_key(self) -> tuple[Any, ...]:
        route = self.solution.routes[self.route_index]
        return (
            self.score,
            self.opened_new_route,
            self.depot_id,
            tuple(route.node_sequence),
        )


def _enumerate_insertions(
    solution: Solution,
    customer_id: str,
    bundle: China81Bundle,
    *,
    depots: tuple[str, ...],
    max_payload: float,
    max_routes: int,
    node_by_id: dict[str, Any],
) -> list[_Insertion]:
    options: list[_Insertion] = []
    for route_index, route in enumerate(solution.routes):
        customers = list(route.node_sequence[1:-1])
        route_demand = sum(float(node_by_id[customer].demand) for customer in customers)
        demand = float(node_by_id[customer_id].demand)
        if route_demand + demand > max_payload + 1.0e-9:
            continue
        for position in _candidate_positions(
            route,
            customer_id,
            bundle,
        ):
            sequence = [
                *customers[:position],
                customer_id,
                *customers[position:],
            ]
            candidate = _replace_route_customers(
                solution,
                route_index,
                route.home_depot_id,
                sequence,
            )
            score = _insertion_score(
                route,
                customer_id,
                position,
                bundle,
                node_by_id=node_by_id,
            )
            options.append(
                _Insertion(
                    score=score,
                    solution=candidate,
                    route_index=route_index,
                    position=position,
                    opened_new_route=False,
                    depot_id=route.home_depot_id,
                )
            )
    if len(solution.routes) < max_routes:
        owner = bundle.customer_home_depot.get(customer_id)
        for depot_id in depots:
            route = Route(
                vehicle_id=f"RR-NEW-{len(solution.routes):03d}",
                vehicle_type="cv",
                home_depot_id=depot_id,
                node_sequence=[
                    depot_id,
                    customer_id,
                    depot_id,
                ],
            )
            candidate = Solution(
                routes=[*solution.routes, route],
            )
            depot_bias = 0.0 if depot_id == owner else 1.0e-6
            score = (
                _distance(bundle, depot_id, customer_id)
                + _distance(bundle, customer_id, depot_id)
                + depot_bias
            )
            options.append(
                _Insertion(
                    score=score,
                    solution=candidate,
                    route_index=len(solution.routes),
                    position=0,
                    opened_new_route=True,
                    depot_id=depot_id,
                )
            )
    return options


def _candidate_positions(
    route: Route,
    customer_id: str,
    bundle: China81Bundle,
    *,
    limit: int = 8,
) -> tuple[int, ...]:
    customers = list(route.node_sequence[1:-1])
    scored: list[tuple[float, int]] = []
    for position in range(len(customers) + 1):
        left = route.home_depot_id if position == 0 else customers[position - 1]
        right = (
            route.home_depot_id if position == len(customers) else customers[position]
        )
        delta = (
            _distance(bundle, left, customer_id)
            + _distance(bundle, customer_id, right)
            - _distance(bundle, left, right)
        )
        scored.append((delta, position))
    return tuple(position for _, position in sorted(scored)[: max(1, int(limit))])


def _insertion_score(
    route: Route,
    customer_id: str,
    position: int,
    bundle: China81Bundle,
    *,
    node_by_id: dict[str, Any],
) -> float:
    customers = list(route.node_sequence[1:-1])
    left = route.home_depot_id if position == 0 else customers[position - 1]
    right = route.home_depot_id if position == len(customers) else customers[position]
    distance_delta = (
        _distance(bundle, left, customer_id)
        + _distance(bundle, customer_id, right)
        - _distance(bundle, left, right)
    )
    customer = node_by_id[customer_id]
    window_width = max(
        1.0,
        float(customer.due_time) - float(customer.ready_time),
    )
    time_pressure = 1.0 / window_width
    owner = bundle.customer_home_depot.get(customer_id)
    cross_site_tiebreak = 0.0 if owner == route.home_depot_id else 1.0e-6
    score = distance_delta + time_pressure + cross_site_tiebreak
    if not math.isfinite(score):
        raise ValueError("non-finite reconstruction score")
    return float(score)


def _replace_route_customers(
    solution: Solution,
    route_index: int,
    depot_id: str,
    customers: list[str],
) -> Solution:
    routes = list(solution.routes)
    old = routes[route_index]
    routes[route_index] = Route(
        vehicle_id=old.vehicle_id,
        vehicle_type=old.vehicle_type,
        home_depot_id=depot_id,
        node_sequence=[depot_id, *customers, depot_id],
    )
    return Solution(routes=routes)


def _distance(
    bundle: China81Bundle,
    left: str,
    right: str,
) -> float:
    return float(bundle.instance.distance(left, right))


def _profile_payload_capacity(
    bundle: China81Bundle,
    vehicle_type: str,
) -> float:
    profile = bundle.instance.vehicle_profile(vehicle_type)
    if profile is None:
        raise ValueError(
            "mechanism-aware reconstruction requires explicit China81 "
            f"vehicle parameters for {vehicle_type!r}"
        )
    capacity = float(profile.payload_capacity_kg)
    if not math.isfinite(capacity) or capacity <= 0.0:
        raise ValueError(f"invalid payload capacity for {vehicle_type!r}: {capacity}")
    return capacity
