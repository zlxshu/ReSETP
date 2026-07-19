from __future__ import annotations

import unittest

import numpy as np

from adaptive_elite_alns_worker import _insertion_options


class RepairForensicsTest(unittest.TestCase):
    def test_proxy_can_prefer_new_route_when_fixed_cost_would_reverse_choice(
        self,
    ) -> None:
        distances = np.asarray(
            [
                [0, 10, 1],
                [10, 0, 100],
                [1, 100, 0],
            ],
            dtype=np.int64,
        )
        options = _insertion_options(
            2,
            [[1]],
            demands=np.asarray([0, 1, 1], dtype=np.int64),
            capacity=10,
            max_routes=2,
            distances=distances,
            reference_edges=frozenset(),
            mode="cost",
            allow_new_route=True,
        )
        best = options[0]
        self.assertEqual(best[3:], (1, 0))
        new_route_distance_delta = best[1]
        existing_route_distance_delta = min(
            option[1] for option in options if option[3] == 0
        )
        fixed_vehicle_cost = 1000
        self.assertLess(
            new_route_distance_delta,
            existing_route_distance_delta,
        )
        self.assertGreater(
            new_route_distance_delta + fixed_vehicle_cost,
            existing_route_distance_delta,
        )

    def test_proxy_emits_insertions_without_time_window_information(
        self,
    ) -> None:
        distances = np.asarray(
            [
                [0, 5, 5],
                [5, 0, 5],
                [5, 5, 0],
            ],
            dtype=np.int64,
        )
        options = _insertion_options(
            2,
            [[1]],
            demands=np.asarray([0, 1, 1], dtype=np.int64),
            capacity=10,
            max_routes=1,
            distances=distances,
            reference_edges=frozenset(),
            mode="cost",
            allow_new_route=False,
        )
        # A hypothetical customer 2 with a due time below five cannot be
        # reached from the depot, yet the helper has no time-window input and
        # still proposes both insertion positions.
        self.assertEqual(len(options), 2)


if __name__ == "__main__":
    unittest.main()
