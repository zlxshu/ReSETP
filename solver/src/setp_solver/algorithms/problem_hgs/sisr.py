"""SISR adjacent-string ruin and incremental recreate for public routing.

The operator follows Christiaens and Vanden Berghe (2020), Sections 5.2--5.3:
adjacent strings are removed from distinct routes and absent customers are
recreated by greedy insertion with blinks.  The public MDVRPTW adaptation keeps
the current finite vehicle inventory and only considers route-feasible
insertions.  It does not implement SISR's simulated-annealing acceptance rule;
the surrounding HGS population remains responsible for acceptance and survival.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from time import perf_counter, process_time

import numpy as np
from setp_hgs_kernel import (
    CostEvaluator,
    ProblemData,
    RandomNumberGenerator,
    Route,
    Solution,
)
from setp_hgs_kernel.repair import sisr_repair


@dataclass(frozen=True)
class SISRParameters:
    """Published SISR R- and R+ parameters used in the ablation."""

    average_removed_customers: float = 10.0
    maximum_string_length: float = 10.0
    blink_probability: float = 0.01

    def __post_init__(self) -> None:
        if self.average_removed_customers <= 0:
            raise ValueError("average removed customers must be positive")
        if self.maximum_string_length < 1:
            raise ValueError("maximum string length must be at least one")
        if not 0 <= self.blink_probability < 1:
            raise ValueError("blink probability must be in [0, 1)")


@dataclass
class SISRAccounting:
    calls: int = 0
    completed_calls: int = 0
    reconstruction_failures: int = 0
    strings_removed: int = 0
    customers_removed: int = 0
    insertion_positions_evaluated: int = 0
    insertion_positions_blinked: int = 0
    new_routes_created: int = 0
    random_order_calls: int = 0
    demand_order_calls: int = 0
    far_order_calls: int = 0
    close_order_calls: int = 0
    complete_outputs: int = 0
    feasible_outputs: int = 0
    wall_seconds: float = 0.0
    cpu_seconds: float = 0.0


@dataclass(frozen=True)
class SISRResult:
    solution: Solution
    seed_customer: int | None
    removed_customers: tuple[int, ...]
    strings_removed: int
    insertion_order: str | None
    reconstruction_failed: bool
    selected_insertions: tuple[tuple[int, int, int, int], ...]


@dataclass
class _MutableRoute:
    vehicle_type: int
    visits: list[int]


_ADJACENCY_CACHE: dict[
    tuple[int, int],
    tuple[ProblemData, np.ndarray],
] = {}


def _uniform_floor(
    rng: RandomNumberGenerator,
    lower: float,
    upper: float,
) -> int:
    """Return floor(U(lower, upper)) for the half-open uniform interval."""

    if upper <= lower:
        return int(math.floor(lower))
    return int(math.floor(lower + float(rng.rand()) * (upper - lower)))


def _customer_adjacency(
    data: ProblemData,
    profile: int = 0,
) -> np.ndarray:
    """Return the static all-customer distance order for one data/profile."""

    key = (id(data), int(profile))
    cached = _ADJACENCY_CACHE.get(key)
    if cached is not None and cached[0] is data:
        return cached[1]

    customers = np.arange(
        data.num_depots,
        data.num_locations,
        dtype=np.int64,
    )
    distance = np.asarray(data.distance_matrix(profile))
    customer_distances = distance[np.ix_(customers, customers)]
    # ``customers`` is ascending, so stable sorting also preserves the old
    # customer-id tie break used by ``sorted((distance, customer))``.
    order = np.argsort(customer_distances, axis=1, kind="stable")
    adjacency = customers[order]
    _ADJACENCY_CACHE[key] = (data, adjacency)
    return adjacency


def _shuffle(
    values: list[int],
    rng: RandomNumberGenerator,
) -> None:
    for right in range(len(values) - 1, 0, -1):
        left = int(rng.randint(right + 1))
        values[right], values[left] = values[left], values[right]


def _adjacent_string_removal(
    data: ProblemData,
    solution: Solution,
    rng: RandomNumberGenerator,
    parameters: SISRParameters,
) -> tuple[list[_MutableRoute], int | None, list[int], int]:
    routes = [
        _MutableRoute(
            int(route.vehicle_type()),
            [int(customer) for customer in route.visits()],
        )
        for route in solution.routes()
        if route.visits()
    ]
    customers = sorted(customer for route in routes for customer in route.visits)
    if not routes or not customers:
        return routes, None, [], 0

    average_route_cardinality = len(customers) / len(routes)
    solution_maximum_string = min(
        float(parameters.maximum_string_length),
        average_route_cardinality,
    )
    maximum_strings = max(
        1.0,
        4.0
        * float(parameters.average_removed_customers)
        / (1.0 + solution_maximum_string)
        - 1.0,
    )
    strings_to_remove = min(
        len(routes),
        _uniform_floor(rng, 1.0, maximum_strings + 1.0),
    )
    seed_customer = customers[int(rng.randint(len(customers)))]
    adjacency = _customer_adjacency(data)[seed_customer - data.num_depots]
    customer_route = {
        customer: route_index
        for route_index, route in enumerate(routes)
        for customer in route.visits
    }

    ruined_routes: set[int] = set()
    removed: list[int] = []
    for adjacent_customer_value in adjacency:
        adjacent_customer = int(adjacent_customer_value)
        route_index = customer_route.get(adjacent_customer)
        if route_index is None:
            continue
        if route_index in ruined_routes:
            continue
        route = routes[route_index]
        anchor_position = route.visits.index(adjacent_customer)
        route_maximum_string = min(
            float(len(route.visits)),
            solution_maximum_string,
        )
        string_length = _uniform_floor(
            rng,
            1.0,
            route_maximum_string + 1.0,
        )
        string_length = max(1, min(string_length, len(route.visits)))
        first_start = max(0, anchor_position - string_length + 1)
        last_start = min(anchor_position, len(route.visits) - string_length)
        start = first_start + int(rng.randint(last_start - first_start + 1))
        removed.extend(route.visits[start : start + string_length])
        del route.visits[start : start + string_length]
        ruined_routes.add(route_index)
        if len(ruined_routes) >= strings_to_remove:
            break

    return routes, seed_customer, removed, len(ruined_routes)


def _depot_distance(
    data: ProblemData,
    customer: int,
) -> int:
    distance = data.distance_matrix(0)
    return min(int(distance[depot, customer]) for depot in range(data.num_depots))


def _ordered_removed_customers(
    data: ProblemData,
    removed: list[int],
    rng: RandomNumberGenerator,
) -> tuple[str, list[int]]:
    # Original SISR weights: Random, Demand, Far, Close = 4, 4, 2, 1.
    draw = int(rng.randint(11))
    ordered = list(removed)
    if draw < 4:
        name = "random"
        _shuffle(ordered, rng)
    elif draw < 8:
        name = "demand"
        ordered.sort(
            key=lambda customer: (
                -sum(int(value) for value in data.location(customer).delivery),
                customer,
            )
        )
    elif draw < 10:
        name = "far"
        ordered.sort(
            key=lambda customer: (
                -_depot_distance(data, customer),
                customer,
            )
        )
    else:
        name = "close"
        ordered.sort(
            key=lambda customer: (
                _depot_distance(data, customer),
                customer,
            )
        )
    return name, ordered


def _greedy_insertion_with_blinks(
    data: ProblemData,
    routes: list[_MutableRoute],
    removed: list[int],
    cost_evaluator: CostEvaluator,
    rng: RandomNumberGenerator,
    parameters: SISRParameters,
    accounting: SISRAccounting,
) -> tuple[
    list[Route] | None,
    str,
    tuple[tuple[int, int, int, int], ...],
]:
    order_name, customers = _ordered_removed_customers(data, removed, rng)
    setattr(
        accounting,
        f"{order_name}_order_calls",
        getattr(accounting, f"{order_name}_order_calls") + 1,
    )
    active = [
        Route(data, route.visits, route.vehicle_type)
        for route in routes
        if route.visits
    ]
    repaired = sisr_repair(
        active,
        customers,
        data,
        cost_evaluator,
        rng,
        parameters.blink_probability,
    )
    accounting.insertion_positions_evaluated += int(repaired.positions_evaluated)
    accounting.insertion_positions_blinked += int(repaired.positions_blinked)
    accounting.new_routes_created += int(repaired.new_routes_created)
    selected_insertions = tuple(
        (
            int(insertion.client),
            int(insertion.route_index),
            int(insertion.position),
            int(insertion.delta_cost),
        )
        for insertion in repaired.selected_insertions
    )
    return (
        list(repaired.routes) if repaired.reconstructed else None,
        order_name,
        selected_insertions,
    )


def sisr_ruin_recreate(
    data: ProblemData,
    solution: Solution,
    cost_evaluator: CostEvaluator,
    rng: RandomNumberGenerator,
    accounting: SISRAccounting,
    parameters: SISRParameters = SISRParameters(),
) -> SISRResult:
    """Apply exactly one adjacent-string ruin and greedy recreate move."""

    wall_started = perf_counter()
    cpu_started = process_time()
    accounting.calls += 1
    try:
        routes, seed, removed, strings_removed = _adjacent_string_removal(
            data,
            solution,
            rng,
            parameters,
        )
        accounting.strings_removed += strings_removed
        accounting.customers_removed += len(removed)
        if not removed:
            accounting.reconstruction_failures += 1
            return SISRResult(
                solution,
                seed,
                (),
                strings_removed,
                None,
                True,
                (),
            )

        rebuilt_routes, order_name, selected_insertions = _greedy_insertion_with_blinks(
            data,
            routes,
            removed,
            cost_evaluator,
            rng,
            parameters,
            accounting,
        )
        if rebuilt_routes is None:
            accounting.reconstruction_failures += 1
            return SISRResult(
                solution,
                seed,
                tuple(removed),
                strings_removed,
                order_name,
                True,
                selected_insertions,
            )

        rebuilt = Solution(
            data,
            rebuilt_routes,
        )
        if not rebuilt.is_complete():
            accounting.reconstruction_failures += 1
            return SISRResult(
                solution,
                seed,
                tuple(removed),
                strings_removed,
                order_name,
                True,
                selected_insertions,
            )

        accounting.completed_calls += 1
        accounting.complete_outputs += int(rebuilt.is_complete())
        accounting.feasible_outputs += int(rebuilt.is_feasible())
        return SISRResult(
            rebuilt,
            seed,
            tuple(removed),
            strings_removed,
            order_name,
            False,
            selected_insertions,
        )
    finally:
        accounting.wall_seconds += perf_counter() - wall_started
        accounting.cpu_seconds += process_time() - cpu_started
