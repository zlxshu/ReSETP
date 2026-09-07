from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from setp_solver.china81 import load_china81_bundle
from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.evaluation import BIG_M, EvaluationContext, penalized_obj
from setp_solver.solution import Route, Solution
from solver.tests.china_test_prices import CHINA_TEST_PRICES


REPO_ROOT = Path(__file__).resolve().parents[2]


def _instance() -> Instance:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=10_000.0, city="beijing"),
        Node("D1", "d", 5000.0, 0.0, due_time=10_000.0, city="beijing"),
        Node("C1", "c", 1000.0, 0.0, demand=100.0, due_time=10_000.0),
        Node("C2", "c", 2000.0, 0.0, demand=200.0, due_time=10_000.0),
    ]
    matrix = [
        [0.0, 5000.0, 1000.0, 2000.0],
        [5000.0, 0.0, 4000.0, 3000.0],
        [1000.0, 4000.0, 0.0, 1000.0],
        [2000.0, 3000.0, 1000.0, 0.0],
    ]
    return Instance(nodes=nodes, distance_matrix=matrix)


def _solution() -> Solution:
    return Solution(routes=[Route("CV1", "cv", "D0", ["D0", "C1", "C2", "D0"])])


def _prices() -> PriceParameters:
    return replace(
        CHINA_TEST_PRICES,
        revenue_per_kg=0.2,
        vehicle_fixed_cost=10.0,
        c_km=1.0,
        diesel_price=0.0,
        diesel_price_by_city=(),
        carbon_price=0.0,
    )



class DepotProfitTests(unittest.TestCase):
    def test_multitrip_fixed_cost_is_allocated_once_per_physical_vehicle(self) -> None:
        solution = Solution(
            routes=[
                Route("CV1#T1", "cv", "D0", ["D0", "C1", "D0"]),
                Route("CV1#T2", "cv", "D0", ["D0", "C2", "D0"]),
            ]
        )

        profits = calculate_depot_profits(
            solution,
            _instance(),
            carbon_profile=[],
            prices=_prices(),
            customer_home_depot={"C1": "D0", "C2": "D0"},
        )

        self.assertEqual(profits["D0"].cost_fixed, 10.0)

    def test_profiled_cv_ev_fixed_costs_match_exact_total_once_per_vehicle(self) -> None:
        bundle = load_china81_bundle(
            REPO_ROOT,
            "cn-prd-10c-01-V2-LOCATIONS",
        )
        depot = next(
            node.node_id
            for node in bundle.instance.nodes
            if node.node_type.lower() == "d"
        )
        customers = [
            node.node_id
            for node in bundle.instance.nodes
            if node.node_type.lower() == "c"
        ]
        solution = Solution(
            routes=[
                Route("CV1", "cv", depot, [depot, customers[0], depot]),
                Route("EV1#T1", "ev", depot, [depot, customers[1], depot]),
                Route("EV1#T2", "ev", depot, [depot, customers[2], depot]),
            ]
        )
        prices = replace(bundle.prices, vehicle_fixed_cost=999.0)

        profits = calculate_depot_profits(
            solution,
            bundle.instance,
            bundle.time_profile,
            prices,
            customer_home_depot={customer: depot for customer in customers[:3]},
        )
        exact = evaluate(
            solution,
            bundle.instance,
            bundle.time_profile,
            prices,
        )

        self.assertEqual(profits[depot].cost_fixed, 440.0)
        self.assertEqual(exact["cost_fix"], 440.0)

    def test_city_diesel_prices_match_exact_route_origin_accounting(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, due_time=10_000.0, city="alpha"),
                Node("D1", "d", 10_000.0, 0.0, due_time=10_000.0, city="beta"),
                Node("C0", "c", 1_000.0, 0.0, demand=100.0, due_time=10_000.0, city="alpha"),
                Node("C1", "c", 9_000.0, 0.0, demand=100.0, due_time=10_000.0, city="beta"),
            ],
            distance_matrix=[
                [0.0, 10_000.0, 1_000.0, 9_000.0],
                [10_000.0, 0.0, 9_000.0, 1_000.0],
                [1_000.0, 9_000.0, 0.0, 8_000.0],
                [9_000.0, 1_000.0, 8_000.0, 0.0],
            ],
        )
        routes = [
            Route("CV0", "cv", "D0", ["D0", "C0", "D0"]),
            Route("CV1", "cv", "D1", ["D1", "C1", "D1"]),
        ]
        solution = Solution(routes=routes)
        prices = replace(
            CHINA_TEST_PRICES,
            diesel_price=100.0,
            diesel_price_by_city=(("alpha", 7.0), ("beta", 9.0)),
            carbon_price=0.0,
        )

        profits = calculate_depot_profits(
            solution,
            instance,
            [],
            prices,
            customer_home_depot={"C0": "D0", "C1": "D1"},
        )
        exact = evaluate(solution, instance, [], prices)

        for route in routes:
            route_exact = evaluate(Solution(routes=[route]), instance, [], prices)
            self.assertAlmostEqual(
                profits[route.home_depot_id].cost_fuel,
                route_exact["cost_fuel"],
                places=12,
            )
        self.assertAlmostEqual(
            sum(row.cost_fuel for row in profits.values()),
            exact["cost_fuel"],
            places=12,
        )

    # v2026-06-12: V2 hand-checks paper eq:profit and eq:depot_cost.
    def test_depot_profit_matches_manual_revenue_and_cost_allocation(self) -> None:
        profits = calculate_depot_profits(
            _solution(),
            _instance(),
            carbon_profile=[{"horizon_second_start": 0.0, "actual_gco2_per_kwh": 50.0}],
            prices=_prices(),
            customer_home_depot={"C1": "D0", "C2": "D1"},
        )

        row = profits["D0"]
        self.assertAlmostEqual(row.revenue, 60.0, places=6)
        self.assertAlmostEqual(row.cost_fixed, 10.0, places=6)
        self.assertAlmostEqual(row.cost_km, 4.0, places=6)
        self.assertAlmostEqual(row.cost_total, 14.0, places=6)
        self.assertAlmostEqual(row.profit, 46.0, places=6)
        self.assertEqual(row.customers_served, 2)
        self.assertAlmostEqual(profits["D1"].profit, 0.0, places=6)

    # v2026-06-12: V2 proves optional PROFIT_FAIRNESS reaches search scoring.
    def test_penalized_objective_applies_fairness_only_when_enabled(self) -> None:
        instance = _instance()
        solution = _solution()
        carbon_profile = [{"horizon_second_start": 0.0, "actual_gco2_per_kwh": 50.0}]
        base_cost = evaluate(solution, instance, carbon_profile, _prices())["total_cost"]
        context_off = EvaluationContext(instance, carbon_profile, prices=_prices())
        context_on_pass = EvaluationContext(
            instance,
            carbon_profile,
            prices=_prices(),
            fairness_enabled=True,
            independent_profit={"D0": 40.0},
            fairness_theta=1.0,
            customer_home_depot={"C1": "D0", "C2": "D1"},
        )
        context_on_fail = EvaluationContext(
            instance,
            carbon_profile,
            prices=_prices(),
            fairness_enabled=True,
            independent_profit={"D0": 47.0},
            fairness_theta=1.0,
            customer_home_depot={"C1": "D0", "C2": "D1"},
        )

        self.assertAlmostEqual(penalized_obj(solution, context_off), base_cost, places=6)
        self.assertAlmostEqual(penalized_obj(solution, context_on_pass), base_cost, places=6)
        self.assertGreaterEqual(penalized_obj(solution, context_on_fail), base_cost + BIG_M)


if __name__ == "__main__":
    unittest.main()
