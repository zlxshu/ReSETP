from __future__ import annotations

import random
import unittest

from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.solution import Route, Solution


def _tiny_instance() -> Instance:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=10_000.0),
        Node("C1", "c", 1.0, 0.0, demand=10.0, due_time=10_000.0),
        Node("C2", "c", 2.0, 0.0, demand=10.0, due_time=10_000.0),
        Node("F1", "f", 1.0, 1.0, due_time=10_000.0),
    ]
    matrix = [
        [0.0, 1000.0, 2000.0, 1000.0],
        [1000.0, 0.0, 1000.0, 1000.0],
        [2000.0, 1000.0, 0.0, 1200.0],
        [1000.0, 1000.0, 1200.0, 0.0],
    ]
    return Instance(nodes=nodes, distance_matrix=matrix, num_cv=3, num_ev=3)


class OrderDecoderTests(unittest.TestCase):
    def test_solution_order_ignores_depot_and_station_nodes(self) -> None:
        from setp_solver.search.order_decoder import solution_order

        solution = Solution(routes=[Route("EV1#T1", "ev", "D0", ["D0", "C2", "F1", "C1", "D0"])])

        self.assertEqual(solution_order(solution, _tiny_instance()), ["C2", "C1"])

    def test_route_type_hints_follow_route_vehicle_type(self) -> None:
        from setp_solver.search.order_decoder import route_type_hints

        solution = Solution(
            routes=[
                Route("EV1#T1", "ev", "D0", ["D0", "C1", "D0"]),
                Route("CV1#T1", "cv", "D0", ["D0", "C2", "D0"]),
            ]
        )

        hints = route_type_hints(solution, _tiny_instance())

        self.assertGreater(hints["C1"], 0.5)
        self.assertLess(hints["C2"], 0.5)

    def test_append_customer_prefers_existing_route_when_fixed_cost_dominates(self) -> None:
        from setp_solver.search.order_decoder import OrderDecodeContext, append_customer_to_cached_plan

        context = OrderDecodeContext(_tiny_instance(), DEFAULT_PRICES, [], random.Random(1))
        plans = {"D0": [["C1"]]}

        append_customer_to_cached_plan("C2", plans, context)

        self.assertEqual(plans, {"D0": [["C1", "C2"]]})

    def test_order_to_solution_returns_complete_checked_solution(self) -> None:
        from setp_solver.check import check_solution
        from setp_solver.search.order_decoder import OrderDecodeContext, order_to_solution, solution_order

        context = OrderDecodeContext(_tiny_instance(), DEFAULT_PRICES, [], random.Random(2))
        decoded = order_to_solution(["C2"], context, type_hints={"C1": 0.05, "C2": 0.05})

        self.assertEqual(sorted(solution_order(decoded, context.instance)), ["C1", "C2"])
        self.assertFalse(check_solution(decoded, context.instance, context.prices))


if __name__ == "__main__":
    unittest.main()
