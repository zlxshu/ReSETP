from __future__ import annotations

import numpy as np
from setp_hgs_kernel import (
    CostEvaluator,
    ProblemData,
    Route,
    Solution,
    solve,
)
from setp_hgs_kernel._setp_hgs_kernel import Client, Depot, VehicleType
from setp_hgs_kernel.stop import MaxIterations
from setp_hgs_kernel.search import compute_neighbours
from setp_hgs_kernel.search.neighbourhood import NeighbourhoodParams
from setp_hgs_kernel._setp_hgs_kernel import best_route_rotation
from setp_solver.algorithms.problem_hgs.public_search import (
    build_integrated_public_hgs,
)
from setp_solver.algorithms.problem_hgs.vidal_compound import (
    _route_cost,
    improve_implicit_assignment_rotation,
    improve_implicit_customer_relocation,
)


def _data() -> ProblemData:
    clients = [
        Client(1, 0, delivery=[1], tw_early=0, tw_late=100),
        Client(9, 0, delivery=[1], tw_early=0, tw_late=100),
    ]
    depots = [Depot(0, 0), Depot(10, 0)]
    distance = np.array(
        [
            [0, 10, 1, 9],
            [10, 0, 9, 1],
            [1, 9, 0, 8],
            [9, 1, 8, 0],
        ],
        dtype=np.int64,
    )
    return ProblemData(
        clients,
        depots,
        [
            VehicleType(1, [2], 0, 0),
            VehicleType(1, [2], 1, 1),
        ],
        [distance],
        [distance],
    )


def _customer_joint_case() -> tuple[ProblemData, Solution]:
    points = [
        (0, 0),
        (20, 0),
        (10, -4),
        (12, -7),
        (2, -5),
        (11, -7),
        (16, -2),
        (1, -6),
    ]
    distance = np.zeros((len(points), len(points)), dtype=np.int64)
    for first, one in enumerate(points):
        for second, other in enumerate(points):
            distance[first, second] = round(
                ((one[0] - other[0]) ** 2 + (one[1] - other[1]) ** 2)
                ** 0.5
                * 10
            )
    data = ProblemData(
        [
            Client(*point, delivery=[1], tw_early=0, tw_late=10_000)
            for point in points[2:]
        ],
        [Depot(*points[0]), Depot(*points[1])],
        [
            VehicleType(1, [6], 0, 0),
            VehicleType(1, [6], 1, 1),
        ],
        [distance],
        [distance],
    )
    return data, Solution(
        data,
        [Route(data, [2], 0), Route(data, [3, 4, 7, 5, 6], 1)],
    )


def test_compound_step_jointly_reassigns_finite_depot_slots() -> None:
    data = _data()
    # Each one-customer route deliberately uses the far-away depot slot.
    solution = Solution(
        data,
        [Route(data, [2], 1), Route(data, [3], 0)],
    )
    evaluator = CostEvaluator([100], 100, 100)

    result = improve_implicit_assignment_rotation(data, solution, evaluator)

    assert result.after_cost < result.before_cost
    assert result.assignments_changed == 2
    assert result.solution.is_feasible()
    assert {
        (route.vehicle_type(), tuple(route.visits()))
        for route in result.solution.routes()
    } == {(0, (2,)), (1, (3,))}


def test_compound_rotation_cache_preserves_the_exact_result() -> None:
    data = _data()
    solution = Solution(
        data,
        [Route(data, [2], 1), Route(data, [3], 0)],
    )
    evaluator = CostEvaluator([100], 100, 100)
    cache = {}

    first = improve_implicit_assignment_rotation(
        data,
        solution,
        evaluator,
        cache,
    )
    second = improve_implicit_assignment_rotation(
        data,
        solution,
        evaluator,
        cache,
    )

    assert second.solution == first.solution
    assert second.after_cost == first.after_cost
    assert first.cache_misses > 0
    assert second.cache_hits == first.cache_misses
    assert second.rotations_evaluated == 0


def test_compiled_rotation_matches_complete_route_truth() -> None:
    data = _data()
    sequence = (2, 3)

    for vehicle_type in range(data.num_vehicle_types):
        expected = None
        for offset in range(len(sequence)):
            rotated = sequence[offset:] + sequence[:offset]
            route = Route(data, list(rotated), vehicle_type)
            if not route.is_feasible():
                continue
            key = (
                _route_cost(route, data, vehicle_type),
                offset,
                rotated,
            )
            if expected is None or key < expected:
                expected = key

        actual = best_route_rotation(
            data,
            list(sequence),
            vehicle_type,
        )
        actual = (
            None
            if actual is None
            else (int(actual[0]), int(actual[1]), tuple(actual[2]))
        )
        assert actual == expected


def test_customer_move_is_accepted_only_after_joint_slot_evaluation() -> None:
    data, solution = _customer_joint_case()
    evaluator = CostEvaluator([1_000], 1_000, 1_000)

    route_only = improve_implicit_assignment_rotation(
        data,
        solution,
        evaluator,
    )
    customer = improve_implicit_customer_relocation(
        data,
        solution,
        evaluator,
        compute_neighbours(
            data,
            NeighbourhoodParams(num_neighbours=5),
        ),
    )

    assert route_only.after_cost == route_only.before_cost == 654
    assert customer.after_cost == 650
    assert customer.joint_only_accepted_moves == 1
    assert customer.solution.is_complete()
    assert customer.solution.is_feasible()
    assert {
        (route.vehicle_type(), tuple(route.visits()))
        for route in customer.solution.routes()
    } == {(1, (2, 3)), (0, (4, 7, 5, 6))}


def test_customer_joint_refinement_returns_one_serially_improved_child() -> None:
    data, solution = _customer_joint_case()
    bundle = build_integrated_public_hgs(
        data,
        seed=3,
        enable_vidal_compound=True,
        enable_customer_relocation=True,
    )
    evaluated = bundle.algorithm._adapter.evaluate(solution)
    assert evaluated is not None

    children = bundle.algorithm._adapter.refine(evaluated)

    assert len(children) == 1
    assert children[0].evaluation.objective < evaluated.evaluation.objective
    assert children[0].solution != evaluated.solution


def test_compound_refinement_does_not_consume_the_main_hgs_random_stream(
) -> None:
    data = _data()
    enabled = build_integrated_public_hgs(
        data,
        seed=3,
        enable_vidal_compound=True,
    )
    disabled = build_integrated_public_hgs(
        data,
        seed=3,
        enable_vidal_compound=False,
    )
    solution = Solution(
        data,
        [Route(data, [2], 1), Route(data, [3], 0)],
    )
    evaluated = enabled.algorithm._adapter.evaluate(solution)
    assert evaluated is not None

    enabled.algorithm._adapter.refine(evaluated)

    assert enabled.algorithm._rng.rand() == disabled.algorithm._rng.rand()


def test_compound_step_runs_inside_the_common_hgs_loop() -> None:
    bundle = build_integrated_public_hgs(
        _data(),
        seed=3,
        enable_vidal_compound=True,
    )

    result = bundle.algorithm.run(MaxIterations(3))

    assert result.accounting.iterations == 3
    assert result.accounting.evaluated > 0
    assert result.best.solution.is_complete()
    assert result.best.evaluation.feasible
    assert bundle.vidal_accounting.calls > 0


def test_common_loop_returns_only_the_serially_improved_child() -> None:
    data = _data()
    bundle = build_integrated_public_hgs(
        data,
        seed=3,
        enable_vidal_compound=True,
    )
    native = Solution(
        data,
        [Route(data, [2], 1), Route(data, [3], 0)],
    )

    evaluated = bundle.algorithm._adapter.evaluate(native)
    assert evaluated is not None
    children = bundle.algorithm._adapter.refine(evaluated)

    assert len(children) == 1
    assert children[0].evaluation.objective < evaluated.evaluation.objective
    assert children[0].solution != native


def test_compound_can_be_reserved_for_new_objective_incumbents() -> None:
    data = _data()
    bundle = build_integrated_public_hgs(
        data,
        seed=3,
        enable_vidal_compound=True,
        refinement_scope="new_incumbent",
    )
    native = Solution(
        data,
        [Route(data, [2], 1), Route(data, [3], 0)],
    )
    evaluated = bundle.algorithm._adapter.evaluate(native)
    assert evaluated is not None

    first = bundle.algorithm._adapter.refine(evaluated)
    calls_after_first = bundle.vidal_accounting.calls
    second = bundle.algorithm._adapter.refine(evaluated)

    assert len(first) == 1
    assert second == (evaluated,)
    assert bundle.vidal_accounting.calls == calls_after_first


def test_common_loop_matches_copied_hgs_when_compound_is_disabled() -> None:
    data = _data()
    baseline = solve(
        data,
        MaxIterations(50),
        seed=7,
        collect_stats=False,
        display=False,
    )
    bundle = build_integrated_public_hgs(
        data,
        seed=7,
        enable_vidal_compound=False,
    )

    integrated = bundle.algorithm.run(MaxIterations(50))

    assert integrated.best.evaluation.objective == baseline.cost()
    assert integrated.best.solution == baseline.best
