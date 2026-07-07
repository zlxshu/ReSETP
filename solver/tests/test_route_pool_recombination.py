from __future__ import annotations

import unittest

from setp_solver.solution import ChargingAction, Route, Solution


class RoutePoolRecombinationTests(unittest.TestCase):
    def test_route_key_includes_sequence_vehicle_type_and_charging_skeleton(self) -> None:
        from setp_solver.search.route_pool import canonical_route_key

        route = Route("EV1#T1", "ev", "D0", ["D0", "C1", "F1", "C2", "D0"])
        actions = [ChargingAction("EV1#T1", "F1", 10.0, 5.0, 100.0)]

        key = canonical_route_key(route, actions)

        self.assertIn(("C1", "C2"), key)
        self.assertIn("ev", key)
        self.assertIn(("F1",), key)

    def test_duplicate_route_keeps_lower_score_record(self) -> None:
        from setp_solver.search.route_pool import RoutePool

        route = Route("CV1#T1", "cv", "D0", ["D0", "C1", "C2", "D0"])
        pool = RoutePool(max_routes=10)
        pool.record_route(route, [], score=20.0)
        pool.record_route(route, [], score=10.0)

        self.assertEqual(len(pool.records), 1)
        self.assertEqual(next(iter(pool.records.values())).score, 10.0)

    def test_recombine_returns_none_when_customers_cannot_be_covered(self) -> None:
        from setp_solver.search.route_pool import RoutePool

        pool = RoutePool(max_routes=10)
        pool.record_route(Route("CV1#T1", "cv", "D0", ["D0", "C1", "D0"]), [], score=10.0)

        self.assertIsNone(pool.recombine({"C1", "C2"}))

    def test_recombine_reassigns_vehicle_ids_and_actions(self) -> None:
        from setp_solver.search.route_pool import RoutePool

        pool = RoutePool(max_routes=10)
        pool.record_route(Route("EV9#T1", "ev", "D0", ["D0", "C1", "F1", "D0"]), [ChargingAction("EV9#T1", "F1", 1.0, 1.0, 1.0)], score=10.0)
        pool.record_route(Route("CV9#T1", "cv", "D0", ["D0", "C2", "D0"]), [], score=10.0)

        solution = pool.recombine({"C1", "C2"})

        self.assertIsNotNone(solution)
        assert solution is not None
        self.assertEqual(len(solution.routes), 2)
        self.assertEqual(len({route.vehicle_id for route in solution.routes}), 2)
        self.assertEqual(solution.charging_actions[0].vehicle_id, next(route.vehicle_id for route in solution.routes if route.vehicle_type == "ev"))


if __name__ == "__main__":
    unittest.main()
