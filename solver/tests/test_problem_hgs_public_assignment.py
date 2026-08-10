"""Customer-level cross-depot assignment improvement tests."""

from setp_hgs_kernel import CostEvaluator, Model, Route, Solution
from setp_solver.algorithms.problem_hgs.public_assignment import (
    improve_customer_depot_assignment,
)


def test_customer_assignment_repairs_crossed_depot_customers() -> None:
    model = Model()
    depot_left = model.add_depot(0, 0)
    depot_right = model.add_depot(100, 0)
    clients = [
        model.add_client(10, 0, delivery=1),
        model.add_client(20, 0, delivery=1),
        model.add_client(90, 0, delivery=1),
        model.add_client(95, 0, delivery=1),
    ]
    locations = [depot_left, depot_right, *clients]
    for left in locations:
        for right in locations:
            distance = int(abs(left.x - right.x))
            model.add_edge(left, right, distance, distance)
    model.add_vehicle_type(
        num_available=1,
        capacity=10,
        start_depot=depot_left,
        end_depot=depot_left,
    )
    model.add_vehicle_type(
        num_available=1,
        capacity=10,
        start_depot=depot_right,
        end_depot=depot_right,
    )
    data = model.data()
    crossed = Solution(
        data,
        [
            Route(data, [2, 4], 0),
            Route(data, [5, 3], 1),
        ],
    )
    evaluator = CostEvaluator([0], 0, 0)

    result = improve_customer_depot_assignment(
        data,
        crossed,
        evaluator,
    )

    assert result.before_cost == 340
    assert result.after_cost == 60
    assert result.changed_customer_assignments == 2
    assert len(result.moves) == 2
    assert result.candidate_evaluations > 0
    assert result.solution.is_complete()
    assert result.solution.is_feasible()
    assert {
        (route.start_depot(), frozenset(route.visits()))
        for route in result.solution.routes()
    } == {(0, frozenset({2, 3})), (1, frozenset({4, 5}))}
