from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

import numpy as np

from setp_solver.china81 import load_china81_bundle
from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters, UK_2025_PRICES
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.evaluation import BIG_M, EvaluationContext, penalized_obj
from setp_solver.search.fairness import build_concatenated_independent_seed
from setp_solver.solution import ChargingAction, Route, Solution


REPO_ROOT = Path(__file__).resolve().parents[2]


def _instance() -> Instance:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=10_000.0),
        Node("D1", "d", 5000.0, 0.0, due_time=10_000.0),
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
        UK_2025_PRICES,
        revenue_per_kg=0.2,
        vehicle_fixed_cost=10.0,
        c_km=1.0,
        cross_site_cost=5.0,
        diesel_price=0.0,
        carbon_price=0.0,
    )


def _write_minimal_bundle(root: str) -> Path:
    bundle_dir = Path(root) / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "instance.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {"node_id": "D0", "node_type": "d", "x": 0.0, "y": 0.0, "due_time": 10000.0},
                    {"node_id": "D1", "node_type": "d", "x": 1000.0, "y": 0.0, "due_time": 10000.0},
                    {"node_id": "C0", "node_type": "c", "x": 10.0, "y": 0.0, "demand": 100.0, "due_time": 10000.0},
                    {"node_id": "C1", "node_type": "c", "x": 990.0, "y": 0.0, "demand": 200.0, "due_time": 10000.0},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    np.save(
        bundle_dir / "distance_matrix.npy",
        np.array(
            [
                [0.0, 1000.0, 10.0, 990.0],
                [1000.0, 0.0, 990.0, 10.0],
                [10.0, 990.0, 0.0, 980.0],
                [990.0, 10.0, 980.0, 0.0],
            ],
            dtype=float,
        ),
    )
    (bundle_dir / "carbon_profile.csv").write_text(
        "time_index,datetime_utc,actual_gco2_per_kwh,forecast_gco2_per_kwh,index_label,index_code,horizon_second_start\n"
        "0,2025-11-13T00:00:00Z,50,50,low,1,0\n",
        encoding="utf-8",
    )
    return bundle_dir


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

        self.assertEqual(profits[depot].cost_fixed, 390.0)
        self.assertEqual(exact["cost_fix"], 390.0)

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
            UK_2025_PRICES,
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

    def test_route_time_cost_matches_exact_total_and_profit_margin(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, due_time=20_000.0),
                Node("F0", "f", 1.0, 0.0, due_time=20_000.0),
                Node("C0", "c", 2.0, 0.0, demand=100.0, due_time=20_000.0),
            ],
            distance_matrix=[
                [0.0, 30_000.0, 30_000.0],
                [30_000.0, 0.0, 30_000.0],
                [30_000.0, 30_000.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[
                Route("EV0#T1", "ev", "D0", ["D0", "F0", "C0", "D0"]),
                Route("EV0#T2", "ev", "D0", ["D0", "D0"]),
            ],
            charging_actions=[
                ChargingAction("EV0#T1", "F0", 1.0, 30.0, 0.0),
                ChargingAction("EV0#T2", "D0", 1.0, 60.0, 0.0),
            ],
        )
        base_prices = replace(
            UK_2025_PRICES,
            revenue_per_kg=1.0,
            vehicle_fixed_cost=0.0,
            c_km=0.0,
            electricity_price=0.0,
            station_electricity_price=0.0,
            depot_electricity_price=0.0,
            occupancy_fee=0.0,
            cross_site_cost=0.0,
            carbon_price=0.0,
            route_time_cost_per_hour=0.0,
        )
        priced = replace(base_prices, route_time_cost_per_hour=75.0)
        profile = [{"horizon_second_start": 0.0, "actual_gco2_per_kwh": 0.0}]

        old = calculate_depot_profits(
            solution,
            instance,
            profile,
            base_prices,
            customer_home_depot={"C0": "D0"},
        )["D0"]
        new = calculate_depot_profits(
            solution,
            instance,
            profile,
            priced,
            customer_home_depot={"C0": "D0"},
        )["D0"]
        exact = evaluate(solution, instance, profile, priced)

        self.assertEqual(old.cost_time, 0.0)
        self.assertEqual(old.profit, 100.0)
        self.assertAlmostEqual(new.cost_time, 112.5, places=12)
        self.assertAlmostEqual(new.profit, -12.5, places=12)
        self.assertAlmostEqual(old.profit - 100.0, 0.0, places=12)
        self.assertAlmostEqual(new.profit - 100.0, -112.5, places=12)
        self.assertAlmostEqual(new.cost_time, exact["cost_time"], places=12)
        self.assertAlmostEqual(new.cost_total, exact["total_cost"], places=12)

    def test_old_profit_omits_nonzero_route_time_cost(self) -> None:
        instance = _instance()
        solution = _solution()
        profile = [
            {"horizon_second_start": 0.0, "actual_gco2_per_kwh": 0.0}
        ]
        prices = replace(_prices(), route_time_cost_per_hour=75.0)
        current = calculate_depot_profits(
            solution,
            instance,
            profile,
            prices,
            customer_home_depot={"C1": "D0", "C2": "D0"},
        )["D0"]
        old_path = Path(
            "/tmp/resetp-costfix-20260812.wxMhZT/solver/src/"
            "setp_solver/profit.py"
        )
        old_name = "setp_solver._costfix_old_profit"
        old_module = types.ModuleType(old_name)
        old_module.__file__ = str(old_path)
        old_module.__package__ = "setp_solver"
        sys.modules[old_name] = old_module
        try:
            exec(compile(old_path.read_text(), str(old_path), "exec"), old_module.__dict__)
            old = old_module.calculate_depot_profits(
                solution,
                instance,
                profile,
                prices,
                customer_home_depot={"C1": "D0", "C2": "D0"},
            )["D0"]
        finally:
            sys.modules.pop(old_name, None)

        self.assertGreater(current.cost_time, 0.0)
        self.assertAlmostEqual(old.profit - current.profit, current.cost_time)

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
        self.assertAlmostEqual(row.cost_transship, 5.0, places=6)
        self.assertAlmostEqual(row.cost_total, 19.0, places=6)
        self.assertAlmostEqual(row.profit, 41.0, places=6)
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
            independent_profit={"D0": 42.0},
            fairness_theta=1.0,
            customer_home_depot={"C1": "D0", "C2": "D1"},
        )

        self.assertAlmostEqual(penalized_obj(solution, context_off), base_cost, places=6)
        self.assertAlmostEqual(penalized_obj(solution, context_on_pass), base_cost, places=6)
        self.assertGreaterEqual(penalized_obj(solution, context_on_fail), base_cost + BIG_M)

    def test_route_time_cost_propagates_into_fairness_penalty(self) -> None:
        instance = _instance()
        solution = _solution()
        carbon_profile = [{"horizon_second_start": 0.0, "actual_gco2_per_kwh": 50.0}]
        old_prices = _prices()
        new_prices = replace(old_prices, route_time_cost_per_hour=75.0)
        common_context = {
            "fairness_enabled": True,
            "independent_profit": {"D0": 40.0},
            "fairness_theta": 1.0,
            "customer_home_depot": {"C1": "D0", "C2": "D1"},
        }
        old_context = EvaluationContext(
            instance,
            carbon_profile,
            prices=old_prices,
            **common_context,
        )
        new_context = EvaluationContext(
            instance,
            carbon_profile,
            prices=new_prices,
            **common_context,
        )

        old_profit = calculate_depot_profits(
            solution,
            instance,
            carbon_profile,
            old_prices,
            customer_home_depot=common_context["customer_home_depot"],
        )["D0"].profit
        new_profit = calculate_depot_profits(
            solution,
            instance,
            carbon_profile,
            new_prices,
            customer_home_depot=common_context["customer_home_depot"],
        )["D0"].profit
        old_cost = evaluate(solution, instance, carbon_profile, old_prices)["total_cost"]
        new_cost = evaluate(solution, instance, carbon_profile, new_prices)["total_cost"]

        self.assertEqual(old_profit, 41.0)
        self.assertAlmostEqual(new_profit, 37.66666666666667, places=12)
        self.assertAlmostEqual(penalized_obj(solution, old_context), old_cost, places=12)
        self.assertAlmostEqual(
            penalized_obj(solution, new_context),
            new_cost + BIG_M,
            places=6,
        )
        self.assertEqual(new_context.score_breakdowns[id(solution)]["violation_count"], 1)

    # v2026-06-12: X0 proves the independent-depot concatenation is a valid
    # theta=1 cooperative seed when all revenue/cost allocation is identical.
    def test_concatenated_independent_seed_has_unit_profit_ratios(self) -> None:
        prices = replace(
            UK_2025_PRICES,
            revenue_per_kg=1.0,
            vehicle_fixed_cost=0.0,
            c_km=0.0,
            diesel_price=0.0,
            carbon_price=0.0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = _write_minimal_bundle(tmp)
            pi_report_path = bundle_dir / "pi_d0.json"
            pi_report_path.write_text(
                json.dumps(
                    {
                        "independent_profit": {"D0": 100.0, "D1": 200.0},
                        "depots": {
                            "D0": {
                                "metrics": {"total_cost": 0.0},
                                "best_solution": {
                                    "routes": [
                                        {
                                            "vehicle_id": "CV0",
                                            "vehicle_type": "cv",
                                            "home_depot_id": "D0",
                                            "node_sequence": ["D0", "C0", "D0"],
                                        }
                                    ],
                                    "charging_actions": [],
                                },
                            },
                            "D1": {
                                "metrics": {"total_cost": 0.0},
                                "best_solution": {
                                    "routes": [
                                        {
                                            "vehicle_id": "CV1",
                                            "vehicle_type": "cv",
                                            "home_depot_id": "D1",
                                            "node_sequence": ["D1", "C1", "D1"],
                                        }
                                    ],
                                    "charging_actions": [],
                                },
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = build_concatenated_independent_seed(bundle_dir, pi_report_path, prices=prices)

        self.assertTrue(report["feasible"])
        self.assertAlmostEqual(report["profit_ratio"]["D0"], 1.0, places=6)
        self.assertAlmostEqual(report["profit_ratio"]["D1"], 1.0, places=6)
        self.assertAlmostEqual(report["total_cost_abs_error_from_source_sum"], 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
