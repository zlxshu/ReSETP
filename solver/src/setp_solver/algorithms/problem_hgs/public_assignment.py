"""Customer-level cross-depot assignment improvement for public MDVRPTW.

This is the project-owned assignment-improvement step.  It follows the
customer reinsertion idea in Vidal et al. (2013): one customer is removed and
tested at every position of routes belonging to another depot.  This differs
from the closed historical whole-route relabelling attempt because customer
sequences and route composition are allowed to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from setp_hgs_kernel import CostEvaluator, ProblemData, Solution
from setp_hgs_kernel.search._search import Node as SearchNode
from setp_hgs_kernel.search._search import insert_cost

from .dcrex import RouteGene
from .public import (
    _PublicInsertionWorkspace,
    _public_route_penalised_cost,
    _solution_from_genes,
    _solution_genes,
)


@dataclass(frozen=True)
class CustomerAssignmentMove:
    customer: int
    source_depot: int
    target_depot: int
    source_route_index: int
    target_route_index: int
    target_position: int
    cost_delta: int
    cost_after: int


@dataclass(frozen=True)
class CustomerAssignmentResult:
    solution: Solution
    before_cost: int
    after_cost: int
    candidate_evaluations: int
    changed_customer_assignments: int
    runtime_seconds: float
    moves: tuple[CustomerAssignmentMove, ...]


def improve_customer_depot_assignment(
    data: ProblemData,
    solution: Solution,
    cost_evaluator: CostEvaluator,
) -> CustomerAssignmentResult:
    """Apply feasible best-improving customer moves across depots.

    Each accepted move strictly lowers the integer route cost, so the search
    terminates without an iteration threshold.  It does not create routes or
    change vehicle types; it only moves a customer into an existing route at
    another depot and removes an emptied source route.
    """

    if not solution.is_complete() or not solution.is_feasible():
        raise ValueError(
            "customer assignment improvement requires a complete feasible solution"
        )

    started = perf_counter()
    routes = _solution_genes(solution)
    expected_customers = _customer_set(routes)
    original_assignment = _customer_depot_assignment(routes)
    before_cost = int(cost_evaluator.cost(solution))
    current_cost = before_cost
    candidate_evaluations = 0
    accepted: list[CustomerAssignmentMove] = []

    while True:
        workspace = _PublicInsertionWorkspace(data, cost_evaluator)
        workspace.reset(routes)
        route_costs = tuple(workspace.current_costs)
        best_key = None
        best_routes = None
        best_move = None
        try:
            for source_index, source in enumerate(routes):
                for source_position, customer in enumerate(
                    source.customer_ids
                ):
                    source_customers = (
                        source.customer_ids[:source_position]
                        + source.customer_ids[source_position + 1 :]
                    )
                    source_replacement = RouteGene(
                        source.route_id,
                        source_customers,
                        source.start_depot,
                        source.end_depot,
                        source.vehicle_type,
                    )
                    if source_customers:
                        source_feasible, source_cost = (
                            _public_route_penalised_cost(
                                data,
                                source_replacement,
                                cost_evaluator,
                            )
                        )
                        if not source_feasible:
                            continue
                    else:
                        source_cost = 0

                    inserted = SearchNode(int(customer))
                    for target_index, target in enumerate(routes):
                        if (
                            target_index == source_index
                            or target.start_depot == source.start_depot
                        ):
                            continue
                        target_route = workspace.routes[target_index]
                        for target_position in range(
                            len(target.customer_ids) + 1
                        ):
                            candidate_evaluations += 1
                            insertion_delta = int(
                                insert_cost(
                                    inserted,
                                    target_route[target_position],
                                    data,
                                    cost_evaluator,
                                )
                            )
                            unpenalised_delta = int(
                                insert_cost(
                                    inserted,
                                    target_route[target_position],
                                    data,
                                    workspace.zero_penalty_evaluator,
                                )
                            )
                            target_penalty = (
                                workspace.current_costs[target_index]
                                - workspace.current_unpenalised_costs[
                                    target_index
                                ]
                                + insertion_delta
                                - unpenalised_delta
                            )
                            if target_penalty != 0:
                                continue
                            delta = int(
                                source_cost
                                - route_costs[source_index]
                                + insertion_delta
                            )
                            if delta >= 0:
                                continue
                            key = (
                                delta,
                                int(customer),
                                source_index,
                                target_index,
                                target_position,
                            )
                            if best_key is not None and key >= best_key:
                                continue

                            target_customers = list(target.customer_ids)
                            target_customers.insert(
                                target_position,
                                customer,
                            )
                            target_replacement = RouteGene(
                                target.route_id,
                                tuple(target_customers),
                                target.start_depot,
                                target.end_depot,
                                target.vehicle_type,
                            )
                            updated = list(routes)
                            updated[source_index] = source_replacement
                            updated[target_index] = target_replacement
                            updated = [
                                route
                                for route in updated
                                if route.customer_ids
                            ]
                            best_key = key
                            best_routes = tuple(updated)
                            best_move = CustomerAssignmentMove(
                                customer=int(customer),
                                source_depot=int(source.start_depot),
                                target_depot=int(target.start_depot),
                                source_route_index=source_index,
                                target_route_index=target_index,
                                target_position=target_position,
                                cost_delta=delta,
                                cost_after=current_cost + delta,
                            )
        finally:
            workspace.close()

        if best_routes is None or best_move is None:
            break
        routes = best_routes
        current_cost += int(best_move.cost_delta)
        accepted.append(best_move)

    improved = _solution_from_genes(data, routes)
    if (
        not improved.is_complete()
        or not improved.is_feasible()
        or _customer_set(routes) != expected_customers
    ):
        raise AssertionError(
            "customer assignment improvement changed service or feasibility"
        )
    after_cost = int(cost_evaluator.cost(improved))
    if after_cost != current_cost:
        raise AssertionError(
            "customer assignment route deltas do not match full solution cost"
        )
    if accepted and after_cost >= before_cost:
        raise AssertionError("accepted customer assignment moves did not improve")
    if not accepted and after_cost != before_cost:
        raise AssertionError("no-op customer assignment changed the solution cost")

    final_assignment = _customer_depot_assignment(routes)
    changed = sum(
        original_assignment[customer] != final_assignment[customer]
        for customer in expected_customers
    )
    return CustomerAssignmentResult(
        solution=improved,
        before_cost=before_cost,
        after_cost=after_cost,
        candidate_evaluations=candidate_evaluations,
        changed_customer_assignments=changed,
        runtime_seconds=perf_counter() - started,
        moves=tuple(accepted),
    )


def _customer_set(routes: tuple[RouteGene, ...]) -> frozenset[int]:
    customers = [
        int(customer)
        for route in routes
        for customer in route.customer_ids
    ]
    if len(customers) != len(set(customers)):
        raise ValueError("customer assignment input contains duplicate customers")
    return frozenset(customers)


def _customer_depot_assignment(
    routes: tuple[RouteGene, ...],
) -> dict[int, int]:
    return {
        int(customer): int(route.start_depot)
        for route in routes
        for customer in route.customer_ids
    }
