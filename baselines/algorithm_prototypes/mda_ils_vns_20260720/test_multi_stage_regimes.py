"""Focused tests for the frozen MPD-ILS-VNS regimes."""

import unittest

from multi_stage_regimes import (
    ARMS,
    EXPERTS,
    FAST,
    WIDE,
    query_public_experts,
)
from racing_configs import FOUNDATION, RACE_CONFIGS


class MultiStageRegimesTest(unittest.TestCase):
    def test_fast_and_wide_match_frozen_sources(self) -> None:
        self.assertEqual(FAST, FOUNDATION)
        race = RACE_CONFIGS["race_08"]
        self.assertEqual(
            (
                WIDE.route_operators,
                WIDE.weight_wait_time,
                WIDE.weight_time_warp,
                WIDE.num_neighbours,
                WIDE.symmetric_neighbours,
                WIDE.history_length,
                WIDE.min_perturbations,
                WIDE.max_perturbations,
            ),
            (
                race.route_operators,
                race.weight_wait_time,
                race.weight_time_warp,
                race.num_neighbours,
                race.symmetric_neighbours,
                race.history_length,
                race.min_perturbations,
                race.max_perturbations,
            ),
        )

    def test_phase_boundaries_are_monotone_and_complete(self) -> None:
        for phases in ARMS.values():
            boundaries = [phase.cumulative_fraction for phase in phases]
            self.assertEqual(boundaries, sorted(boundaries))
            self.assertEqual(boundaries[-1], 1.0)

    def test_public_experts_are_queried_not_disabled(self) -> None:
        ledger = query_public_experts(2)
        self.assertEqual(
            {row["expert"] for row in ledger},
            set(EXPERTS),
        )
        self.assertTrue(all(row["queried"] for row in ledger))
        self.assertTrue(all(not row["applicable"] for row in ledger))
        self.assertTrue(all(row["action_count"] == 0 for row in ledger))


if __name__ == "__main__":
    unittest.main()
