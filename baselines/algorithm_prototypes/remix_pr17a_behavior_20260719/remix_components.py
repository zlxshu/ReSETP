"""Bounded components used by the ReMIX PR17A behaviour gate.

The implementation is intentionally diagnostic.  It demonstrates that
multiple search components can exchange complete PyVRP solutions without
claiming that the fixed micro-budgets are good performance settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import pyvrp
from pyvrp import PenaltyManager, RandomNumberGenerator, Route, Solution
from pyvrp.search import (
    NODE_OPERATORS,
    ROUTE_OPERATORS,
    LocalSearch,
    NeighbourhoodParams,
    PerturbationManager,
    compute_neighbours,
)


@dataclass
class ComponentCounters:
    island_solve_calls: int = 0
    island_ils_iterations: int = 0
    route_exchange_calls: int = 0
    route_exchange_candidate_checks: int = 0
    route_exchange_donor_routes_used: int = 0
    destroy_repair_calls: int = 0
    destroy_repair_route_checks: int = 0
    destroy_repair_insertion_checks: int = 0
    local_search_calls: int = 0
    route_pool_calls: int = 0
    route_pool_candidate_routes: int = 0

    @property
    def enhancement_calls(self) -> int:
        return (
            self.island_solve_calls
            + self.route_exchange_calls
            + self.destroy_repair_calls
            + self.local_search_calls
            + self.route_pool_calls
        )


@dataclass(frozen=True)
class LineagedSolution:
    source_id: str
    solution: Solution
    lineage: tuple[str, ...]


def solution_is_usable(solution: Solution) -> bool:
    return (
        solution.is_complete()
        and solution.is_feasible()
        and solution.num_missing_clients() == 0
    )


def canonical_routes(solution: Solution) -> list[dict[str, Any]]:
    records = [
        {
            "vehicle_type": route.vehicle_type(),
            "start_depot": route.start_depot(),
            "end_depot": route.end_depot(),
            "visits": list(route.visits()),
            "distance": route.distance(),
            "duration": route.duration(),
            "feasible": route.is_feasible(),
        }
        for route in solution.routes()
    ]
    return sorted(
        records,
        key=lambda record: (
            record["vehicle_type"],
            tuple(record["visits"]),
        ),
    )


def _vehicle_counts(routes: Iterable[Route]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for route in routes:
        vehicle_type = route.vehicle_type()
        counts[vehicle_type] = counts.get(vehicle_type, 0) + 1
    return counts


def _within_vehicle_limits(
    data: pyvrp.ProblemData,
    routes: Iterable[Route],
) -> bool:
    return all(
        count <= data.vehicle_type(vehicle_type).num_available
        for vehicle_type, count in _vehicle_counts(routes).items()
    )


def _route_edges(route: Route) -> set[tuple[int, int]]:
    visits = list(route.visits())
    path = [route.start_depot(), *visits, route.end_depot()]
    return {
        (min(left, right), max(left, right))
        for left, right in zip(path, path[1:], strict=False)
    }


def _overlay_route(
    data: pyvrp.ProblemData,
    base: Solution,
    donor: Route,
) -> Solution | None:
    donor_clients = set(donor.visits())
    routes: list[Route] = []
    for route in base.routes():
        remaining = [
            client
            for client in route.visits()
            if client not in donor_clients
        ]
        if remaining:
            candidate = Route(
                data,
                remaining,
                route.vehicle_type(),
            )
            if not candidate.is_feasible():
                return None
            routes.append(candidate)

    routes.append(
        Route(data, list(donor.visits()), donor.vehicle_type())
    )
    if not _within_vehicle_limits(data, routes):
        return None

    try:
        solution = Solution(data, routes)
    except RuntimeError:
        return None
    return solution if solution_is_usable(solution) else None


def multi_parent_route_exchange(
    data: pyvrp.ProblemData,
    base: LineagedSolution,
    donors: list[LineagedSolution],
    counters: ComponentCounters,
) -> tuple[LineagedSolution, dict[str, Any]]:
    """Overlays one novel feasible route from each donor onto the base."""
    counters.route_exchange_calls += 1
    current = base.solution
    used_sources: list[str] = []
    used_routes: list[list[int]] = []

    for donor_solution in donors:
        current_edges = set().union(
            *(_route_edges(route) for route in current.routes())
        )
        ranked = sorted(
            donor_solution.solution.routes(),
            key=lambda route: (
                -len(_route_edges(route) - current_edges),
                route.distance(),
                route.vehicle_type(),
                tuple(route.visits()),
            ),
        )
        for donor_route in ranked:
            counters.route_exchange_candidate_checks += 1
            candidate = _overlay_route(data, current, donor_route)
            if candidate is None or candidate == current:
                continue
            current = candidate
            used_sources.append(donor_solution.source_id)
            used_routes.append(list(donor_route.visits()))
            counters.route_exchange_donor_routes_used += 1
            break

    lineage = (
        *base.lineage,
        *(f"donor:{source}" for source in used_sources),
        "route_exchange",
    )
    output = LineagedSolution(
        source_id=f"{base.source_id}+x{counters.route_exchange_calls}",
        solution=current,
        lineage=lineage,
    )
    return output, {
        "stage": "route_exchange",
        "input_source": base.source_id,
        "donor_sources": [donor.source_id for donor in donors],
        "used_sources": used_sources,
        "used_routes": used_routes,
        "output_source": output.source_id,
        "complete": current.is_complete(),
        "feasible": current.is_feasible(),
        "distance": current.distance(),
    }


def _segment_rank(
    data: pyvrp.ProblemData,
    route: Route,
    start: int,
) -> tuple[int, int, int, int, int]:
    visits = list(route.visits())
    segment = visits[start : start + 2]
    vehicle_type = data.vehicle_type(route.vehicle_type())
    profile = vehicle_type.profile
    distances = data.distance_matrix(profile)
    depot = route.start_depot()

    affinity_gain = 0
    window_width = 0
    for client in segment:
        nearest_other = min(
            int(distances[other, client])
            for other in range(data.num_depots)
            if other != depot
        )
        affinity_gain += int(distances[depot, client]) - nearest_other
        location = data.location(client)
        window_width += int(location.tw_late - location.tw_early)

    return (
        affinity_gain,
        -window_width,
        route.distance(),
        -route.vehicle_type(),
        -start,
    )


def _insertion_options(
    data: pyvrp.ProblemData,
    routes: list[Route],
    client: int,
    counters: ComponentCounters,
) -> list[tuple[tuple[int, int, int, int, int], int, int, Route]]:
    options: list[
        tuple[tuple[int, int, int, int, int], int, int, Route]
    ] = []
    for route_idx, route in enumerate(routes):
        visits = list(route.visits())
        vehicle_type = data.vehicle_type(route.vehicle_type())
        distances = data.distance_matrix(vehicle_type.profile)
        depot_affinity = int(distances[route.start_depot(), client])
        for position in range(len(visits) + 1):
            counters.destroy_repair_insertion_checks += 1
            candidate = Route(
                data,
                [*visits[:position], client, *visits[position:]],
                route.vehicle_type(),
            )
            if not candidate.is_feasible():
                continue
            delta = candidate.distance() - route.distance()
            score = (
                delta,
                depot_affinity,
                route.vehicle_type(),
                route_idx,
                position,
            )
            options.append((score, route_idx, position, candidate))

    counts = _vehicle_counts(routes)
    for vehicle_type in range(data.num_vehicle_types):
        spec = data.vehicle_type(vehicle_type)
        if counts.get(vehicle_type, 0) >= spec.num_available:
            continue
        counters.destroy_repair_insertion_checks += 1
        candidate = Route(data, [client], vehicle_type)
        if not candidate.is_feasible():
            continue
        distances = data.distance_matrix(spec.profile)
        depot_affinity = int(distances[spec.start_depot, client])
        score = (
            candidate.distance(),
            depot_affinity,
            vehicle_type,
            len(routes),
            0,
        )
        options.append((score, len(routes), 0, candidate))

    return sorted(options, key=lambda item: item[0])


def mechanism_destroy_repair(
    data: pyvrp.ProblemData,
    input_solution: LineagedSolution,
    counters: ComponentCounters,
) -> tuple[LineagedSolution, dict[str, Any]]:
    """Removes one high-tension two-client segment and regret-reinserts it."""
    counters.destroy_repair_calls += 1
    segment_candidates: list[
        tuple[tuple[int, int, int, int, int], int, int]
    ] = []
    original_routes = list(input_solution.solution.routes())
    for route_idx, route in enumerate(original_routes):
        for start in range(max(0, len(route.visits()) - 1)):
            segment_candidates.append(
                (_segment_rank(data, route, start), route_idx, start)
            )
    if not segment_candidates:
        raise RuntimeError("no two-client segment available for destroy-repair")

    _, route_idx, start = max(segment_candidates, key=lambda item: item[0])
    source_route = original_routes[route_idx]
    source_visits = list(source_route.visits())
    removed = source_visits[start : start + 2]
    remaining = source_visits[:start] + source_visits[start + 2 :]

    routes: list[Route] = []
    for idx, route in enumerate(original_routes):
        if idx != route_idx:
            routes.append(
                Route(data, list(route.visits()), route.vehicle_type())
            )
            continue
        if remaining:
            shortened = Route(data, remaining, route.vehicle_type())
            counters.destroy_repair_route_checks += 1
            if not shortened.is_feasible():
                raise RuntimeError("destroyed route became infeasible")
            routes.append(shortened)

    pending = list(removed)
    insertions: list[dict[str, Any]] = []
    while pending:
        choices: list[
            tuple[int, int, tuple[int, int, int, int, int], int, Route]
        ] = []
        for client in pending:
            options = _insertion_options(data, routes, client, counters)
            if not options:
                raise RuntimeError(f"no feasible repair option for client {client}")
            best_score, best_route_idx, _, best_route = options[0]
            second_delta = (
                options[1][0][0]
                if len(options) > 1
                else best_score[0] + 10**12
            )
            regret = second_delta - best_score[0]
            choices.append(
                (
                    regret,
                    -client,
                    best_score,
                    best_route_idx,
                    best_route,
                )
            )

        _, neg_client, score, target_idx, candidate_route = max(
            choices,
            key=lambda item: (item[0], item[1]),
        )
        client = -neg_client
        if target_idx == len(routes):
            routes.append(candidate_route)
        else:
            routes[target_idx] = candidate_route
        pending.remove(client)
        insertions.append(
            {
                "client": client,
                "target_vehicle_type": candidate_route.vehicle_type(),
                "target_depot": candidate_route.start_depot(),
                "distance_delta": score[0],
            }
        )

    if not _within_vehicle_limits(data, routes):
        raise RuntimeError("repair exceeded vehicle availability")
    repaired = Solution(data, routes)
    if not solution_is_usable(repaired):
        raise RuntimeError("repair did not return a complete feasible solution")

    output = LineagedSolution(
        source_id=(
            f"{input_solution.source_id}+dr{counters.destroy_repair_calls}"
        ),
        solution=repaired,
        lineage=(*input_solution.lineage, "destroy_repair"),
    )
    return output, {
        "stage": "destroy_repair",
        "input_source": input_solution.source_id,
        "output_source": output.source_id,
        "removed_segment": removed,
        "insertions": insertions,
        "complete": repaired.is_complete(),
        "feasible": repaired.is_feasible(),
        "distance": repaired.distance(),
    }


def local_search_refine(
    data: pyvrp.ProblemData,
    input_solution: LineagedSolution,
    *,
    seed: int,
    counters: ComponentCounters,
) -> tuple[LineagedSolution, dict[str, Any]]:
    counters.local_search_calls += 1
    rng = RandomNumberGenerator(seed=seed)
    neighbours = compute_neighbours(data, NeighbourhoodParams())
    search = LocalSearch(data, rng, neighbours, PerturbationManager())
    for operator in NODE_OPERATORS:
        if operator.supports(data):
            search.add_node_operator(operator(data))
    for operator in ROUTE_OPERATORS:
        if operator.supports(data):
            search.add_route_operator(operator(data))

    penalties = PenaltyManager.init_from(data)
    candidate = search(
        input_solution.solution,
        penalties.max_cost_evaluator(),
        exhaustive=True,
    )
    accepted = solution_is_usable(candidate)
    result = candidate if accepted else input_solution.solution
    output = LineagedSolution(
        source_id=f"{input_solution.source_id}+ls{counters.local_search_calls}",
        solution=result,
        lineage=(*input_solution.lineage, "local_search"),
    )
    return output, {
        "stage": "local_search",
        "input_source": input_solution.source_id,
        "output_source": output.source_id,
        "candidate_accepted": accepted,
        "input_distance": input_solution.solution.distance(),
        "output_distance": result.distance(),
        "complete": result.is_complete(),
        "feasible": result.is_feasible(),
    }


def assert_unique_complete_coverage(
    data: pyvrp.ProblemData,
    solution: Solution,
) -> None:
    observed = [
        client
        for route in solution.routes()
        for client in route.visits()
    ]
    expected = set(range(data.num_depots, data.num_locations))
    if len(observed) != len(set(observed)):
        raise ValueError("solution contains duplicate clients")
    if set(observed) != expected:
        raise ValueError("solution does not cover the required client set")
    if not solution_is_usable(solution):
        raise ValueError("solution is not complete and feasible")
