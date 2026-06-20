from __future__ import annotations

import unittest
from pathlib import Path

from setp_solver.search.winner_restoration import (
    RESTORATION_DIR,
    classify_regression,
    static_recipe_audit,
    _load_json,
    _solution_from_dict,
)


class WinnerRestorationTests(unittest.TestCase):
    def test_gold_solution_json_loads_as_solution(self) -> None:
        path = Path("solver/reports/alns_crush_v2/task3/solutions/100-01-24h_winner_kernel_only_ALNS-Wouda_seed2.json")

        solution = _solution_from_dict(_load_json(path))

        self.assertEqual(len(solution.routes), 32)
        self.assertEqual(len(solution.charging_actions), 22)

    def test_classifier_detects_route_count_cost_fix_dominance(self) -> None:
        rows = [
            {
                "total_delta": 160.0,
                "route_count_delta": 2,
                "cost_fix_delta": 160.0,
                "cost_km_delta": 0.0,
                "cv_routes_delta": 0,
                "ev_routes_delta": 0,
                "charging_actions_delta": 0,
            }
            for _ in range(10)
        ]

        result = classify_regression(rows, {"mismatches": []})

        self.assertEqual(result["classification"], "route_count_cost_fix_dominant")
        self.assertGreaterEqual(result["cost_fix_explained_share"], 1.0)

    def test_classifier_detects_cost_km_dominance(self) -> None:
        rows = [
            {
                "total_delta": 100.0,
                "route_count_delta": 0,
                "cost_fix_delta": 0.0,
                "cost_km_delta": 80.0,
                "cv_routes_delta": 0,
                "ev_routes_delta": 0,
                "charging_actions_delta": 0,
            }
            for _ in range(10)
        ]

        result = classify_regression(rows, {"mismatches": []})

        self.assertEqual(result["classification"], "cost_km_dominant")

    def test_classifier_detects_vehicle_mix_dominance(self) -> None:
        rows = [
            {
                "total_delta": 100.0,
                "route_count_delta": 0,
                "cost_fix_delta": 0.0,
                "cost_km_delta": 0.0,
                "cv_routes_delta": 2,
                "ev_routes_delta": -2,
                "charging_actions_delta": 0,
            }
            for _ in range(10)
        ]

        result = classify_regression(rows, {"mismatches": []})

        self.assertEqual(result["classification"], "vehicle_mix_dominant")

    def test_classifier_falls_back_to_mixed(self) -> None:
        rows = [
            {
                "total_delta": 100.0,
                "route_count_delta": 0,
                "cost_fix_delta": 10.0,
                "cost_km_delta": 10.0,
                "cv_routes_delta": 0,
                "ev_routes_delta": 0,
                "charging_actions_delta": 0,
            }
            for _ in range(10)
        ]

        result = classify_regression(rows, {"mismatches": []})

        self.assertEqual(result["classification"], "mixed_or_unclear")

    def test_restoration_report_root_is_isolated(self) -> None:
        self.assertEqual(str(RESTORATION_DIR), "solver/reports/dr_alns_ppo_v2/restoration")

    def test_static_recipe_audit_has_expected_public_base(self) -> None:
        audit = static_recipe_audit()

        self.assertEqual(audit["operator_base_id"], "winner_kernel_v1")
        self.assertEqual(audit["destroy_ops"], [
            "random_customer_removal",
            "worst_customer_removal",
            "shaw_related_removal",
            "whole_route_removal",
            "route_segment_removal",
            "vehicle_type_swap",
        ])
        self.assertEqual(audit["repair_ops"], ["greedy_insert_repair", "regret2_insert_repair", "regret3_insert_repair"])

    def test_runner_does_not_call_formal_e1_e7(self) -> None:
        source = Path("solver/src/setp_solver/search/winner_restoration.py").read_text(encoding="utf-8")

        self.assertNotIn("formal_runner", source)
        self.assertNotIn("run_e1", source.lower())
        self.assertNotIn("run_e7", source.lower())


if __name__ == "__main__":
    unittest.main()
