from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.evaluation import BIG_M, EvaluationContext, penalized_obj
from setp_solver.search.fairness import build_concatenated_independent_seed
from setp_solver.solution import Route, Solution


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
    return PriceParameters(
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

    # v2026-06-12: X0 proves the independent-depot concatenation is a valid
    # theta=1 cooperative seed when all revenue/cost allocation is identical.
    def test_concatenated_independent_seed_has_unit_profit_ratios(self) -> None:
        prices = PriceParameters(
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
