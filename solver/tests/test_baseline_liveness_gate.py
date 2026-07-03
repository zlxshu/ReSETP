from __future__ import annotations

import unittest

from setp_solver.search import metaheuristic_baselines as mb


class BaselineLivenessGateTest(unittest.TestCase):
    def test_operator_channel_classification(self) -> None:
        self.assertEqual(mb._operator_channel("shared_warm_start"), "shared_warm_start")
        self.assertEqual(mb._operator_channel("reference_flip_closure"), "reference_flip_closure")
        self.assertEqual(mb._operator_channel("common_flip_preprocess"), "common_flip_preprocess")
        self.assertEqual(mb._operator_channel("lns_vehicle_type_mutation"), "flip_operator")
        self.assertEqual(mb._operator_channel("lns_random_customer_removal_greedy_insert_repair"), "native_lns_random_customer_removal_greedy_insert_repair")

    def test_channel_lift_stats_split_common_native_and_flip(self) -> None:
        history = [
            {"operator": "shared_warm_start", "channel": "shared_warm_start", "best_cost": 100.0},
            {"operator": "common_flip_preprocess", "channel": "common_flip_preprocess", "best_cost_before": 100.0, "best_cost": 80.0},
            {"operator": "lns_vehicle_type_mutation", "channel": "flip_operator", "best_cost_before": 80.0, "best_cost": 70.0},
            {"operator": "lns_shaw_related_removal_regret2_insert_repair", "channel": "native_lns_shaw_related_removal_regret2_insert_repair", "best_cost_before": 70.0, "best_cost": 60.0},
        ]

        stats = mb._channel_lift_stats(history)

        self.assertEqual(stats["common_lift"], 20.0)
        self.assertEqual(stats["flip_lift"], 10.0)
        self.assertEqual(stats["native_lift"], 10.0)
        self.assertEqual(stats["common_best_updates"], 1)
        self.assertEqual(stats["flip_best_updates"], 1)
        self.assertEqual(stats["native_best_updates"], 1)

    def test_channel_lift_stats_ignore_reference_flip_closure(self) -> None:
        history = [
            {"operator": "shared_warm_start", "channel": "shared_warm_start", "best_cost": 100.0},
            {
                "operator": "reference_flip_closure",
                "channel": "reference_flip_closure",
                "best_cost": 100.0,
                "reference_cost": 80.0,
                "reference_lift": 20.0,
                "is_reference": True,
            },
        ]

        stats = mb._channel_lift_stats(history)

        self.assertEqual(stats["common_lift"], 0.0)
        self.assertEqual(stats["flip_lift"], 0.0)
        self.assertEqual(stats["native_lift"], 0.0)
        self.assertEqual(stats["common_best_updates"], 0)
        self.assertEqual(stats["flip_best_updates"], 0)
        self.assertEqual(stats["native_best_updates"], 0)


if __name__ == "__main__":
    unittest.main()
