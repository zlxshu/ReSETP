from __future__ import annotations

from dataclasses import replace

from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.solution import Route, Solution


def test_e5_time_value_is_zero_by_default_and_isolated_when_enabled() -> None:
    instance = Instance(
        nodes=[
            Node("D", "d", 0.0, 0.0),
            Node("C", "c", 1.0, 0.0, demand=1.0),
        ],
        distance_matrix=[[0.0, 90_000.0], [90_000.0, 0.0]],
    )
    solution = Solution(routes=[Route("CV1", "cv", "D", ["D", "C", "D"])])
    default = evaluate(solution, instance, [], DEFAULT_PRICES)
    sensitivity = evaluate(
        solution,
        instance,
        [],
        replace(DEFAULT_PRICES, route_time_cost_per_hour=75.0),
    )
    assert default["cost_time"] == 0.0
    assert sensitivity["route_time_hours"] == 2.0
    assert sensitivity["cost_time"] == 150.0
    assert sensitivity["total_cost"] - default["total_cost"] == 150.0
