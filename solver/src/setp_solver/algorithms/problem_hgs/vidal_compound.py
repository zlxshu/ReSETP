"""Implicit customer, depot, finite-slot, type, and rotation education.

Vidal et al. (2014), Proposition 1--2 and Eqs. (11)--(13), evaluate depot,
vehicle type, and route rotation jointly with a customer sequence.  Their
paper assumes an unlimited fleet and omits time windows.  This implementation
keeps the same joint-evaluation idea but expands the actual finite vehicle
inventory into slots and evaluates every rotated sequence with the copied
kernel's time-window and capacity resources.

This is intentionally separate from ``public_assignment.py``.  That historical
operator required an immediately improving cross-depot insertion under the
current vehicle types.  The customer compound step below instead tests the
blind spot left by native local search: a relocation that is not improving
under the current types and route cuts, but becomes improving when the two
affected routes are jointly re-cut and assigned to the residual finite fleet.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import numpy as np
from scipy.optimize import linear_sum_assignment
from setp_hgs_kernel import CostEvaluator, ProblemData, Route, Solution
from setp_hgs_kernel._setp_hgs_kernel import best_route_rotation
from setp_hgs_kernel.search._search import Node as SearchNode
from setp_hgs_kernel.search._search import remove_cost, insert_cost

from .public import _PublicInsertionWorkspace, _solution_genes


@dataclass(frozen=True)
class VidalCompoundResult:
    solution: Solution
    before_cost: int
    after_cost: int
    route_slot_evaluations: int
    rotations_evaluated: int
    assignments_changed: int
    rotations_changed: int
    cache_hits: int
    cache_misses: int
    runtime_seconds: float


@dataclass(frozen=True)
class VidalCustomerCompoundResult:
    solution: Solution
    before_cost: int
    after_cost: int
    candidate_evaluations: int
    joint_evaluations: int
    accepted_moves: int
    joint_only_accepted_moves: int
    route_slot_evaluations: int
    rotations_evaluated: int
    cache_hits: int
    cache_misses: int
    runtime_seconds: float


def improve_implicit_assignment_rotation(
    data: ProblemData,
    solution: Solution,
    cost_evaluator: CostEvaluator,
    rotation_cache: dict[
        tuple[tuple[int, ...], int],
        tuple[int, int, tuple[int, ...]] | None,
    ]
    | None = None,
) -> VidalCompoundResult:
    """Jointly choose finite vehicle slots and cyclic route rotations."""

    if not solution.is_complete():
        raise ValueError("compound evaluation requires complete service")
    started = perf_counter()
    routes = tuple(solution.routes())
    before_cost = int(cost_evaluator.penalised_cost(solution))
    if not routes:
        return VidalCompoundResult(
            solution,
            before_cost,
            before_cost,
            0,
            0,
            0,
            0,
            0,
            0,
            perf_counter() - started,
        )
    if any(route.num_trips() != 1 for route in routes):
        raise ValueError("public compound evaluation expects one trip per route")

    slots = tuple(
        vehicle_type
        for vehicle_type, specification in enumerate(data.vehicle_types())
        for _copy in range(int(specification.num_available))
    )
    unique_vehicle_types = tuple(dict.fromkeys(slots))
    if len(routes) > len(slots):
        raise ValueError("solution uses more routes than finite vehicle slots")

    infinity = np.iinfo(np.int64).max // 16
    matrix = np.full((len(routes), len(slots)), infinity, dtype=np.int64)
    choices: dict[tuple[int, int], tuple[int, ...]] = {}
    rotations_evaluated = 0
    cache_hits = 0
    cache_misses = 0
    for route_index, route in enumerate(routes):
        sequence = tuple(int(client) for client in route.visits())
        best_by_vehicle_type = {}
        for vehicle_type in unique_vehicle_types:
            best, evaluated, hit = _best_rotation(
                data,
                sequence,
                int(vehicle_type),
                rotation_cache,
            )
            rotations_evaluated += evaluated
            cache_hits += int(hit)
            cache_misses += int(not hit)
            best_by_vehicle_type[vehicle_type] = best
        for slot_index, vehicle_type in enumerate(slots):
            best = best_by_vehicle_type[vehicle_type]
            if best is not None:
                matrix[route_index, slot_index] = int(best[0])
                choices[(route_index, slot_index)] = best[2]

    route_rows, slot_columns = linear_sum_assignment(matrix)
    if len(route_rows) != len(routes):
        raise AssertionError("finite-slot assignment did not cover every route")
    if any(matrix[row, column] >= infinity for row, column in zip(
        route_rows,
        slot_columns,
        strict=True,
    )):
        return VidalCompoundResult(
            solution,
            before_cost,
            before_cost,
            len(routes) * len(slots),
            rotations_evaluated,
            0,
            0,
            cache_hits,
            cache_misses,
            perf_counter() - started,
        )

    selected = sorted(zip(route_rows, slot_columns, strict=True))
    changed_assignment = 0
    changed_rotation = 0
    rebuilt_routes = []
    for route_index, slot_index in selected:
        original = routes[int(route_index)]
        vehicle_type = int(slots[int(slot_index)])
        sequence = choices[(int(route_index), int(slot_index))]
        changed_assignment += int(vehicle_type != int(original.vehicle_type()))
        changed_rotation += int(sequence != tuple(original.visits()))
        rebuilt_routes.append(Route(data, list(sequence), vehicle_type))
    rebuilt = Solution(data, rebuilt_routes)
    after_cost = int(cost_evaluator.penalised_cost(rebuilt))
    if (
        not rebuilt.is_complete()
        or not rebuilt.is_feasible()
        or after_cost >= before_cost
    ):
        rebuilt = solution
        after_cost = before_cost
        changed_assignment = 0
        changed_rotation = 0
    return VidalCompoundResult(
        rebuilt,
        before_cost,
        after_cost,
        len(routes) * len(slots),
        rotations_evaluated,
        changed_assignment,
        changed_rotation,
        cache_hits,
        cache_misses,
        perf_counter() - started,
    )


def improve_implicit_customer_relocation(
    data: ProblemData,
    solution: Solution,
    cost_evaluator: CostEvaluator,
    neighbours: list[list[int]],
    rotation_cache: dict[
        tuple[tuple[int, ...], int],
        tuple[int, int, tuple[int, ...]] | None,
    ]
    | None = None,
) -> VidalCustomerCompoundResult:
    """Apply one joint customer, finite-slot, and rotation improvement.

    Candidate relocations use the copied HGS granular neighbourhood: customer
    ``u`` is inserted immediately after a neighbouring customer ``v`` on a
    different route. Native-improving relocations are left to the copied local
    search. For the remaining blind-spot candidates, the two affected
    sequences are evaluated against the residual finite vehicle inventory and
    every cyclic route cut. A restricted improvement is then rebuilt and the
    existing global finite-slot assignment gives the exact accepted solution.

    Fixing all unaffected routes can miss an improvement that needs a longer
    vehicle-slot reassignment chain, but cannot accept a worsening move.
    """

    if not solution.is_complete() or not solution.is_feasible():
        raise ValueError(
            "customer compound evaluation requires a complete feasible solution"
        )
    routes = tuple(solution.routes())
    if any(route.num_trips() != 1 for route in routes):
        raise ValueError("public customer compound expects one trip per route")

    started = perf_counter()
    before_cost = int(cost_evaluator.cost(solution))
    location = {
        int(customer): (route_index, position)
        for route_index, route in enumerate(routes)
        for position, customer in enumerate(route.visits())
    }
    vehicle_limits = tuple(
        int(specification.num_available)
        for specification in data.vehicle_types()
    )
    route_costs = tuple(
        _route_cost(route, data, int(route.vehicle_type()))
        for route in routes
    )
    workspace = _PublicInsertionWorkspace(data, cost_evaluator)
    workspace.reset(_solution_genes(solution))

    candidate_evaluations = 0
    joint_evaluations = 0
    route_slot_evaluations = 0
    rotations_evaluated = 0
    cache_hits = 0
    cache_misses = 0
    candidate_rotation_cache: dict[
        tuple[tuple[int, ...], int],
        tuple[int, int, tuple[int, ...]] | None,
    ] = {}
    try:
        screened_candidates = []
        for source_index, source in enumerate(routes):
            source_sequence = tuple(int(item) for item in source.visits())
            for source_position, customer in enumerate(source_sequence):
                for neighbour in neighbours[int(customer)]:
                    target_location = location.get(int(neighbour))
                    if target_location is None:
                        continue
                    target_index, target_position = target_location
                    if target_index == source_index:
                        continue
                    candidate_evaluations += 1

                    fixed_delta = int(
                        remove_cost(
                            workspace.routes[source_index][source_position + 1],
                            data,
                            cost_evaluator,
                        )
                        + insert_cost(
                            SearchNode(int(customer)),
                            workspace.routes[target_index][target_position + 1],
                            data,
                            cost_evaluator,
                        )
                    )
                    if fixed_delta < 0:
                        continue
                    screened_candidates.append(
                        (
                            fixed_delta,
                            source_index,
                            source_position,
                            int(customer),
                            target_index,
                            target_position,
                        )
                    )

        screened_candidates.sort(key=lambda candidate: candidate[0])
        for (
            _fixed_delta,
            source_index,
            source_position,
            customer,
            target_index,
            target_position,
        ) in screened_candidates:
            joint_evaluations += 1
            source_sequence = tuple(
                int(item) for item in routes[source_index].visits()
            )
            target_sequence = list(map(int, routes[target_index].visits()))
            target_sequence.insert(target_position + 1, customer)
            reduced_source = (
                source_sequence[:source_position]
                + source_sequence[source_position + 1 :]
            )
            affected_sequences = (
                (
                    (source_index, reduced_source)
                    if reduced_source
                    else None
                ),
                (target_index, tuple(target_sequence)),
            )
            active_sequences = tuple(
                item for item in affected_sequences if item is not None
            )

            used_by_unaffected = [0] * data.num_vehicle_types
            for route_index, route in enumerate(routes):
                if route_index in {source_index, target_index}:
                    continue
                used_by_unaffected[int(route.vehicle_type())] += 1
            residual = tuple(
                limit - used
                for limit, used in zip(
                    vehicle_limits,
                    used_by_unaffected,
                    strict=True,
                )
            )
            if any(item < 0 for item in residual):
                raise AssertionError(
                    "input solution exceeds the finite vehicle inventory"
                )

            option_rows = []
            for _route_index, sequence in active_sequences:
                row = []
                for vehicle_type, available in enumerate(residual):
                    if available <= 0:
                        continue
                    best, evaluated, hit = _best_rotation(
                        data,
                        sequence,
                        vehicle_type,
                        candidate_rotation_cache,
                    )
                    rotations_evaluated += evaluated
                    cache_hits += int(hit)
                    cache_misses += int(not hit)
                    route_slot_evaluations += 1
                    if best is not None:
                        row.append((vehicle_type, best))
                if not row:
                    break
                option_rows.append(tuple(row))
            if len(option_rows) != len(active_sequences):
                continue

            restricted = _best_residual_assignment(
                active_sequences,
                tuple(option_rows),
                residual,
            )
            if restricted is None:
                continue
            restricted_cost, selected = restricted
            original_affected_cost = (
                route_costs[source_index] + route_costs[target_index]
            )
            if restricted_cost >= original_affected_cost:
                continue

            replacements = {
                route_index: Route(
                    data,
                    list(sequence),
                    int(vehicle_type),
                )
                for route_index, (vehicle_type, sequence) in selected.items()
            }
            rebuilt_routes = []
            for route_index, route in enumerate(routes):
                if route_index == source_index and not reduced_source:
                    continue
                rebuilt_routes.append(replacements.get(route_index, route))
            restricted_solution = Solution(data, rebuilt_routes)
            exact = improve_implicit_assignment_rotation(
                data,
                restricted_solution,
                cost_evaluator,
                rotation_cache,
            )
            route_slot_evaluations += exact.route_slot_evaluations
            rotations_evaluated += exact.rotations_evaluated
            cache_hits += exact.cache_hits
            cache_misses += exact.cache_misses
            if (
                exact.solution.is_complete()
                and exact.solution.is_feasible()
                and exact.after_cost < before_cost
            ):
                return VidalCustomerCompoundResult(
                    exact.solution,
                    before_cost,
                    exact.after_cost,
                    candidate_evaluations,
                    joint_evaluations,
                    1,
                    1,
                    route_slot_evaluations,
                    rotations_evaluated,
                    cache_hits,
                    cache_misses,
                    perf_counter() - started,
                )
    finally:
        workspace.close()

    return VidalCustomerCompoundResult(
        solution,
        before_cost,
        before_cost,
        candidate_evaluations,
        joint_evaluations,
        0,
        0,
        route_slot_evaluations,
        rotations_evaluated,
        cache_hits,
        cache_misses,
        perf_counter() - started,
    )


def _best_rotation(
    data: ProblemData,
    sequence: tuple[int, ...],
    vehicle_type: int,
    rotation_cache: dict[
        tuple[tuple[int, ...], int],
        tuple[int, int, tuple[int, ...]] | None,
    ]
    | None,
) -> tuple[tuple[int, int, tuple[int, ...]] | None, int, bool]:
    cache_key = (sequence, int(vehicle_type))
    if rotation_cache is not None and cache_key in rotation_cache:
        return rotation_cache[cache_key], 0, True

    compiled = best_route_rotation(
        data,
        list(sequence),
        int(vehicle_type),
    )
    best = (
        None
        if compiled is None
        else (int(compiled[0]), int(compiled[1]), tuple(compiled[2]))
    )
    if rotation_cache is not None:
        rotation_cache[cache_key] = best
    return best, len(sequence), False


def _best_residual_assignment(
    active_sequences: tuple[tuple[int, tuple[int, ...]], ...],
    option_rows: tuple[
        tuple[tuple[int, tuple[int, int, tuple[int, ...]]], ...],
        ...,
    ],
    residual: tuple[int, ...],
) -> tuple[int, dict[int, tuple[int, tuple[int, ...]]]] | None:
    best = None
    if len(active_sequences) == 1:
        route_index, _sequence = active_sequences[0]
        for vehicle_type, option in option_rows[0]:
            key = (int(option[0]), int(vehicle_type), option[2])
            if best is None or key < best[0]:
                best = (
                    key,
                    {route_index: (int(vehicle_type), option[2])},
                )
    elif len(active_sequences) == 2:
        first_index, _first_sequence = active_sequences[0]
        second_index, _second_sequence = active_sequences[1]
        for first_type, first in option_rows[0]:
            for second_type, second in option_rows[1]:
                if (
                    first_type == second_type
                    and residual[first_type] < 2
                ):
                    continue
                key = (
                    int(first[0]) + int(second[0]),
                    int(first_type),
                    int(second_type),
                    first[2],
                    second[2],
                )
                if best is None or key < best[0]:
                    best = (
                        key,
                        {
                            first_index: (int(first_type), first[2]),
                            second_index: (int(second_type), second[2]),
                        },
                    )
    else:
        raise AssertionError("customer relocation changes one or two routes")

    if best is None:
        return None
    return int(best[0][0]), best[1]


def _rotations(sequence: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    if len(sequence) <= 1:
        return (sequence,)
    return tuple(
        sequence[offset:] + sequence[:offset]
        for offset in range(len(sequence))
    )


def _route_cost(route: Route, data: ProblemData, vehicle_type: int) -> int:
    specification = data.vehicle_type(int(vehicle_type))
    return int(
        int(specification.fixed_cost)
        + int(route.distance_cost())
        + int(route.duration_cost())
        + int(specification.unit_overtime_cost) * int(route.overtime())
        - int(route.prizes())
    )
