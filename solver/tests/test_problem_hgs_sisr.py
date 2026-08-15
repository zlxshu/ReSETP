from __future__ import annotations

import numpy as np
from setp_hgs_kernel import (
    CostEvaluator,
    ProblemData,
    RandomNumberGenerator,
    Route,
    Solution,
)
from setp_hgs_kernel._setp_hgs_kernel import Client, Depot, VehicleType
from setp_hgs_kernel.stop import MaxIterations

from setp_solver.algorithms.problem_hgs.public_search import (
    build_integrated_public_hgs,
)
from setp_solver.algorithms.problem_hgs.sisr import (
    _MutableRoute,
    _adjacent_string_removal,
    _customer_adjacency,
    _greedy_insertion_with_blinks,
    _ordered_removed_customers,
    SISRAccounting,
    SISRParameters,
    sisr_ruin_recreate,
)


def _data() -> ProblemData:
    points = [
        (0, 0),
        (20, 0),
        (1, 1),
        (2, 1),
        (3, 1),
        (4, 1),
        (16, 1),
        (17, 1),
        (18, 1),
        (19, 1),
    ]
    matrix = np.zeros((len(points), len(points)), dtype=np.int64)
    for first, one in enumerate(points):
        for second, other in enumerate(points):
            matrix[first, second] = round(
                ((one[0] - other[0]) ** 2 + (one[1] - other[1]) ** 2) ** 0.5 * 10
            )
    return ProblemData(
        [
            Client(*point, delivery=[1], tw_early=0, tw_late=10_000)
            for point in points[2:]
        ],
        [Depot(*points[0]), Depot(*points[1])],
        [
            VehicleType(3, [8], 0, 0),
            VehicleType(3, [8], 1, 1),
        ],
        [matrix],
        [matrix],
    )


def _solution(data: ProblemData) -> Solution:
    return Solution(
        data,
        [
            Route(data, [2, 3], 0),
            Route(data, [4, 5], 0),
            Route(data, [6, 7], 1),
            Route(data, [8, 9], 1),
        ],
    )


def _legacy_full_route_recreate_trace(
    data: ProblemData,
    routes: list[_MutableRoute],
    removed: list[int],
    cost_evaluator: CostEvaluator,
    rng: RandomNumberGenerator,
    parameters: SISRParameters,
    *,
    human_blink_policy: bool,
) -> tuple[tuple[int, int, int, int], ...]:
    """Reference the pre-incremental candidate evaluation in test code only."""

    active = [
        _MutableRoute(route.vehicle_type, list(route.visits))
        for route in routes
        if route.visits
    ]
    _order_name, customers = _ordered_removed_customers(data, removed, rng)
    trace: list[tuple[int, int, int, int]] = []
    for customer in customers:
        candidates: list[tuple[int, int, int]] = []
        for route_index, route in enumerate(active):
            original = Route(data, route.visits, route.vehicle_type)
            original_cost = int(
                cost_evaluator.penalised_cost(Solution(data, [original]))
            )
            for position in range(len(route.visits) + 1):
                visits = list(route.visits)
                visits.insert(position, customer)
                candidate = Route(data, visits, route.vehicle_type)
                if not candidate.is_feasible():
                    continue
                candidates.append(
                    (
                        int(cost_evaluator.penalised_cost(Solution(data, [candidate])))
                        - original_cost,
                        route_index,
                        position,
                    )
                )

        selected: tuple[int, int, int] | None = None
        if human_blink_policy:
            for candidate in candidates:
                if selected is not None and candidate[0] >= selected[0]:
                    continue
                if float(rng.rand()) < parameters.blink_probability:
                    continue
                selected = candidate
        else:
            for candidate in sorted(candidates):
                if float(rng.rand()) < parameters.blink_probability:
                    continue
                selected = candidate
                break

        if selected is None:
            used = [0] * data.num_vehicle_types
            for route in active:
                used[route.vehicle_type] += 1
            new_routes: list[tuple[int, int]] = []
            for vehicle_type, specification in enumerate(data.vehicle_types()):
                if used[vehicle_type] >= int(specification.num_available):
                    continue
                candidate = Route(data, [customer], vehicle_type)
                if candidate.is_feasible():
                    new_routes.append(
                        (
                            int(
                                cost_evaluator.penalised_cost(
                                    Solution(data, [candidate])
                                )
                            ),
                            vehicle_type,
                        )
                    )
            if not new_routes:
                raise AssertionError("test fixture reconstruction failed")
            delta_cost, vehicle_type = min(new_routes)
            active.append(_MutableRoute(vehicle_type, [customer]))
            trace.append((customer, len(active) - 1, 0, delta_cost))
            continue
        delta_cost, route_index, position = selected
        active[route_index].visits.insert(position, customer)
        trace.append((customer, route_index, position, delta_cost))
    return tuple(trace)


def test_sisr_recreates_every_removed_customer_feasibly() -> None:
    data = _data()
    solution = _solution(data)
    accounting = SISRAccounting()
    result = sisr_ruin_recreate(
        data,
        solution,
        CostEvaluator([100], 100, 100),
        RandomNumberGenerator(seed=11),
        accounting,
    )

    assert result.removed_customers
    assert result.strings_removed >= 1
    assert not result.reconstruction_failed
    assert result.solution.is_complete()
    assert result.solution.is_feasible()
    assert sorted(
        customer for route in result.solution.routes() for customer in route.visits()
    ) == list(range(data.num_depots, data.num_locations))
    assert accounting.calls == 1
    assert accounting.completed_calls == 1
    assert accounting.complete_outputs == 1
    assert accounting.feasible_outputs == 1


def test_zero_blink_probability_never_skips_a_position() -> None:
    data = _data()
    accounting = SISRAccounting()
    result = sisr_ruin_recreate(
        data,
        _solution(data),
        CostEvaluator([100], 100, 100),
        RandomNumberGenerator(seed=7),
        accounting,
        SISRParameters(blink_probability=0.0),
    )

    assert not result.reconstruction_failed
    assert accounting.insertion_positions_evaluated > 0
    assert accounting.insertion_positions_blinked == 0


def test_static_adjacency_is_cached_and_preserves_distance_order() -> None:
    data = _data()
    first = _customer_adjacency(data)
    second = _customer_adjacency(data)

    assert first is second
    customers = list(range(data.num_depots, data.num_locations))
    distance = data.distance_matrix(0)
    for row, customer in enumerate(customers):
        assert first[row].tolist() == sorted(
            customers,
            key=lambda other: (int(distance[customer, other]), other),
        )


def test_incremental_trace_matches_full_route_with_same_blink_policy() -> None:
    data = _data()
    solution = _solution(data)
    parameters = SISRParameters(blink_probability=0.35)
    destroy_rng = RandomNumberGenerator(seed=11)
    routes, _seed, removed, _strings = _adjacent_string_removal(
        data,
        solution,
        destroy_rng,
        parameters,
    )
    rng_state = destroy_rng.state()
    cost_evaluator = CostEvaluator([100], 100, 100)

    expected = _legacy_full_route_recreate_trace(
        data,
        routes,
        removed,
        cost_evaluator,
        RandomNumberGenerator(rng_state),
        parameters,
        human_blink_policy=True,
    )
    rebuilt, _order, actual = _greedy_insertion_with_blinks(
        data,
        routes,
        removed,
        cost_evaluator,
        RandomNumberGenerator(rng_state),
        parameters,
        SISRAccounting(),
    )

    assert rebuilt is not None
    assert actual == expected


def test_incremental_trace_matches_legacy_when_blinks_are_disabled() -> None:
    data = _data()
    parameters = SISRParameters(blink_probability=0.0)
    destroy_rng = RandomNumberGenerator(seed=7)
    routes, _seed, removed, _strings = _adjacent_string_removal(
        data,
        _solution(data),
        destroy_rng,
        parameters,
    )
    rng_state = destroy_rng.state()
    cost_evaluator = CostEvaluator([100], 100, 100)

    legacy = _legacy_full_route_recreate_trace(
        data,
        routes,
        removed,
        cost_evaluator,
        RandomNumberGenerator(rng_state),
        parameters,
        human_blink_policy=False,
    )
    rebuilt, _order, incremental = _greedy_insertion_with_blinks(
        data,
        routes,
        removed,
        cost_evaluator,
        RandomNumberGenerator(rng_state),
        parameters,
        SISRAccounting(),
    )

    assert rebuilt is not None
    assert incremental == legacy


def test_blink_policy_alone_can_change_the_selected_trace() -> None:
    data = _data()
    cost_evaluator = CostEvaluator([100], 100, 100)
    parameters = SISRParameters(blink_probability=0.5)
    difference_found = False
    for seed in range(1, 40):
        destroy_rng = RandomNumberGenerator(seed=seed)
        routes, _seed, removed, _strings = _adjacent_string_removal(
            data,
            _solution(data),
            destroy_rng,
            parameters,
        )
        rng_state = destroy_rng.state()
        legacy = _legacy_full_route_recreate_trace(
            data,
            routes,
            removed,
            cost_evaluator,
            RandomNumberGenerator(rng_state),
            parameters,
            human_blink_policy=False,
        )
        human = _legacy_full_route_recreate_trace(
            data,
            routes,
            removed,
            cost_evaluator,
            RandomNumberGenerator(rng_state),
            parameters,
            human_blink_policy=True,
        )
        if legacy != human:
            difference_found = True
            break

    assert difference_found


def test_sisr_default_off_preserves_the_integrated_run() -> None:
    data = _data()
    implicit_default = build_integrated_public_hgs(
        data,
        seed=3,
        enable_vidal_compound=False,
    )
    explicit_off = build_integrated_public_hgs(
        data,
        seed=3,
        enable_vidal_compound=False,
        enable_sisr=False,
    )

    first = implicit_default.algorithm.run(MaxIterations(5))
    second = explicit_off.algorithm.run(MaxIterations(5))

    assert first.best.evaluation.objective == second.best.evaluation.objective
    assert first.best.solution == second.best.solution
    assert {
        key: value
        for key, value in vars(first.accounting).items()
        if key != "elapsed_seconds"
    } == {
        key: value
        for key, value in vars(second.accounting).items()
        if key != "elapsed_seconds"
    }
    assert implicit_default.sisr_accounting.calls == 0
    assert explicit_off.sisr_accounting.calls == 0


def test_enabled_sisr_is_called_after_education() -> None:
    bundle = build_integrated_public_hgs(
        _data(),
        seed=11,
        enable_vidal_compound=False,
        enable_sisr=True,
    )

    result = bundle.algorithm.run(MaxIterations(3))

    assert result.accounting.iterations == 3
    assert bundle.sisr_accounting.calls >= 3
    assert bundle.sisr_accounting.completed_calls >= 1
    assert result.best.solution.is_complete()
    assert result.best.solution.is_feasible()
