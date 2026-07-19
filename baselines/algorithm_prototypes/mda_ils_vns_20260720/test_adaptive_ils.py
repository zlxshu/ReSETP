"""Focused tests for the isolated MDA-ILS-VNS adaptive layer."""

import unittest

from adaptive_ils import (
    STRENGTH_LEVELS,
    AdaptiveAcceptance,
    nearest_strength,
    structural_distance_from_neighbours,
    updated_strength,
)


class AdaptiveILSTest(unittest.TestCase):
    def test_structural_distance_identical_is_zero(self) -> None:
        neighbours = [None, None, (0, 3), (2, 4), (3, 1)]
        self.assertEqual(
            structural_distance_from_neighbours(
                neighbours,
                neighbours,
                2,
            ),
            0,
        )

    def test_structural_distance_counts_edge_and_depot_touch(self) -> None:
        reference = [None, None, (0, 3), (2, 4), (3, 1)]
        candidate = [None, None, (0, 4), (1, 2), (2, 3)]
        self.assertEqual(
            structural_distance_from_neighbours(
                reference,
                candidate,
                2,
            ),
            2,
        )

    def test_strength_update_moves_and_clips(self) -> None:
        self.assertLess(updated_strength(20, 10, 20), 20)
        self.assertGreater(updated_strength(20, 20, 10), 20)
        self.assertEqual(
            updated_strength(40, 30, 0),
            STRENGTH_LEVELS[-1],
        )
        self.assertEqual(
            updated_strength(4, 1, 1000),
            STRENGTH_LEVELS[0],
        )

    def test_nearest_strength_breaks_tie_downward(self) -> None:
        self.assertEqual(nearest_strength(10), 8)
        self.assertEqual(nearest_strength(18), 16)

    def test_acceptance_always_accepts_improvement(self) -> None:
        acceptance = AdaptiveAcceptance(initial_cost=100)
        self.assertTrue(acceptance.accept(99, 100, 1.0))

    def test_acceptance_updates_block_baseline(self) -> None:
        acceptance = AdaptiveAcceptance(initial_cost=100, block_size=3)
        acceptance.accept(120, 100, 0.0)
        acceptance.accept(110, 100, 0.0)
        acceptance.accept(115, 100, 0.0)
        self.assertEqual(
            acceptance.diagnostics()["previous_block_best"],
            110,
        )


if __name__ == "__main__":
    unittest.main()
