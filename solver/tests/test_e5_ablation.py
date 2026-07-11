from __future__ import annotations

from pathlib import Path
import unittest

from setp_solver.check import check_solution
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.search.charging import (
    _fixed_charge_latest,
    replay_fixed_route_charging,
    solve_charging_fixed_route,
    solve_charging_naive,
)
from setp_solver.search.e5_ablation import run_e5_charging_ablation, run_ev_adoption_diagnostic
from setp_solver.solution import Route, Solution


REPO_ROOT = Path(__file__).resolve().parents[2]
Q1_BUNDLE_DIR = REPO_ROOT / "models" / "data_bundle" / "generated_instances" / "E-UK100_01__d2_s3_seed1_24h_20251113"
REAL_BUDGET_REPORT = REPO_ROOT / "solver" / "reports" / "e5_100-01_24h_20251113_seed1_real_budget.json"


def _fixed_charge_instance() -> Instance:
    return Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, demand=0.0, ready_time=0.0, due_time=20_000.0, service_time=0.0),
            Node("C1", "c", 10_000.0, 0.0, demand=100.0, ready_time=0.0, due_time=20_000.0, service_time=0.0),
        ],
        distance_matrix=[
            [0.0, 10_000.0],
            [10_000.0, 0.0],
        ],
    )


def _profile() -> list[dict[str, float]]:
    return [
        {"time_index": idx, "horizon_second_start": float(idx * 1800), "actual_gco2_per_kwh": gamma}
        for idx, gamma in enumerate([300.0, 200.0, 50.0, 100.0, 150.0, 180.0])
    ]


class E5ChargingAblationTests(unittest.TestCase):
    def test_fixed_charge_latest_protects_all_downstream_time_windows(self) -> None:
        nodes = [
            Node("F0", "f", 0.0, 0.0, ready_time=0.0, due_time=20_000.0, service_time=0.0, charge_power_kw=60.0),
            Node("C1", "c", 1_000.0, 0.0, ready_time=0.0, due_time=10_000.0, service_time=100.0),
            Node("C2", "c", 2_000.0, 0.0, ready_time=0.0, due_time=5_000.0, service_time=0.0),
        ]
        instance = Instance(
            nodes=nodes,
            distance_matrix=[[0.0, 1_000.0, 2_000.0], [1_000.0, 0.0, 1_000.0], [2_000.0, 1_000.0, 0.0]],
        )
        latest = _fixed_charge_latest(
            0,
            ["F0", "C1", "C2"],
            {node.node_id: node for node in nodes},
            instance,
            PriceParameters(),
            occupancy_sec=600.0,
        )

        # 5000 due - 40 travel C1->C2 - 100 service C1 - 40 travel
        # F0->C1 - 600 charging = 4220 seconds.
        self.assertAlmostEqual(latest, 4_220.0)

    # v2026-06-12: S0 return-charge ablation must isolate timing, not energy.
    def test_naive_starts_at_return_while_aware_uses_greenest_overnight_slot(self) -> None:
        route = Route("EV1", "ev", "D0", ["D0", "C1", "D0"])
        instance = _fixed_charge_instance()
        prices = PriceParameters()

        aware = solve_charging_fixed_route(route, instance, _profile(), prices, strategy="aware")
        naive = solve_charging_naive(route, instance, _profile(), prices)

        self.assertEqual(len(aware), 1)
        self.assertEqual(len(naive), 1)
        self.assertAlmostEqual(aware[0].energy_kwh, naive[0].energy_kwh, delta=1e-9)
        self.assertEqual(naive[0].charge_start_second, 800.0)
        self.assertEqual(aware[0].charge_start_second, 3600.0)

    # v2026-06-12: fixed-route replay strips old actions but must preserve all route node sequences.
    def test_fixed_route_replay_preserves_routes_and_feasibility_for_both_strategies(self) -> None:
        solution = Solution(routes=[Route("EV1", "ev", "D0", ["D0", "C1", "D0"])])
        instance = _fixed_charge_instance()

        aware = replay_fixed_route_charging(solution, instance, _profile(), strategy="aware")
        naive = replay_fixed_route_charging(solution, instance, _profile(), strategy="naive")

        self.assertEqual([route.node_sequence for route in aware.routes], [["D0", "C1", "D0"]])
        self.assertEqual([route.node_sequence for route in naive.routes], [["D0", "C1", "D0"]])
        self.assertEqual(check_solution(aware, instance), [])
        self.assertEqual(check_solution(naive, instance), [])

    # v2026-06-12: S0 report is the E5 figure source: 48 slots per policy and strong return-charge delta.
    def test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables(self) -> None:
        report = run_e5_charging_ablation(Q1_BUNDLE_DIR, REAL_BUDGET_REPORT)

        self.assertEqual(report["slot_count"], 48)
        self.assertEqual(len(report["carbon_aware"]["slot_y_skt"]), 48)
        self.assertEqual(len(report["naive_return_charge"]["slot_y_skt"]), 48)
        self.assertTrue(report["carbon_aware"]["feasible"])
        self.assertTrue(report["naive_return_charge"]["feasible"])
        self.assertGreater(report["delta_intensity_gco2_per_kwh_naive_minus_aware"], 20.0)
        self.assertGreater(report["delta_carbon_kg_naive_minus_aware"], 0.0)

    # v2026-06-12: R2 must explain remaining CV routes with explicit flip economics and swap counts.
    def test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts(self) -> None:
        diagnostic = run_ev_adoption_diagnostic(Q1_BUNDLE_DIR, REAL_BUDGET_REPORT)

        self.assertEqual([row["sample"] for row in diagnostic["cv_route_flips"]], ["short", "mid", "long"])
        self.assertEqual(len(diagnostic["cv_route_flips"]), 3)
        for row in diagnostic["cv_route_flips"]:
            self.assertIn("route_id", row)
            self.assertIn("feasible", row)
            self.assertIn("cost_delta", row)
            self.assertIn("total_cost", row["cost_delta"])
            self.assertIn("battery_trajectory", row)
            self.assertIn("station_insertion_diagnostics", row)
            self.assertIn(
                row["root_cause"],
                {"station_too_few_or_far", "time_window_too_tight", "repair_logic_defect", "flip_feasible"},
            )
            self.assertNotEqual(row["root_cause"], "repair_logic_defect")
        self.assertEqual(diagnostic["vehicle_type_swap_counts"]["raw_outcome_order"], ["BEST", "BETTER", "ACCEPT", "REJECT"])
        self.assertGreater(diagnostic["vehicle_type_swap_counts"]["attempts"], 0)


if __name__ == "__main__":
    unittest.main()
