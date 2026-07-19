"""Focused tests for the frozen parameter race."""

import unittest

from racing_configs import FOUNDATION, RACE_CONFIGS
from selective_route_vns import CONFIGS


class RacingConfigsTest(unittest.TestCase):
    def test_exact_configuration_count_and_names(self) -> None:
        self.assertEqual(len(RACE_CONFIGS), 17)
        self.assertEqual(
            set(RACE_CONFIGS) - {"foundation"},
            {f"race_{index:02d}" for index in range(1, 17)},
        )

    def test_foundation_matches_validated_configuration(self) -> None:
        validated = CONFIGS["swapstar_best"]
        self.assertEqual(
            FOUNDATION.route_operators,
            validated.route_operators,
        )
        self.assertEqual(
            (
                FOUNDATION.weight_wait_time,
                FOUNDATION.weight_time_warp,
                FOUNDATION.num_neighbours,
                FOUNDATION.symmetric_neighbours,
                FOUNDATION.num_iters_no_improvement,
                FOUNDATION.history_length,
                FOUNDATION.min_perturbations,
                FOUNDATION.max_perturbations,
            ),
            (
                validated.weight_wait_time,
                validated.weight_time_warp,
                validated.num_neighbours,
                validated.symmetric_neighbours,
                validated.num_iters_no_improvement,
                validated.history_length,
                validated.min_perturbations,
                validated.max_perturbations,
            ),
        )

    def test_all_race_payloads_are_unique_and_bounded(self) -> None:
        payloads = set()
        for name, config in RACE_CONFIGS.items():
            if name == "foundation":
                continue
            payload = (
                config.num_neighbours,
                config.weight_wait_time,
                config.weight_time_warp,
                config.symmetric_neighbours,
                config.history_length,
                config.min_perturbations,
                config.max_perturbations,
            )
            self.assertNotIn(payload, payloads)
            payloads.add(payload)
            self.assertIn(config.num_neighbours, {20, 35, 50, 65, 80})
            self.assertIn(
                config.weight_wait_time,
                {0.0, 0.2, 0.5, 1.0},
            )
            self.assertIn(
                config.weight_time_warp,
                {0.5, 1.0, 2.0, 4.0},
            )
            self.assertIn(config.history_length, {100, 300, 600, 1200})
            self.assertIn(config.min_perturbations, {1, 3, 5})
            self.assertIn(config.max_perturbations, {15, 25, 35, 40})


if __name__ == "__main__":
    unittest.main()
