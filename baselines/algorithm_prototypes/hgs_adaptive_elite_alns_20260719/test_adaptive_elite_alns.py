from __future__ import annotations

import unittest

import numpy as np

from adaptive_elite_alns_worker import (
    customer_neighbours,
    edge_signature,
    partition_is_complete,
    regret_repair,
)


class AdaptiveEliteALNSTest(unittest.TestCase):
    def test_edge_signature_is_orientation_neutral(self) -> None:
        self.assertEqual(
            edge_signature([[1, 2, 3], [4, 5]]),
            edge_signature([[3, 2, 1], [5, 4]]),
        )

    def test_customer_neighbours_include_depot(self) -> None:
        neighbours = customer_neighbours([[1, 2], [3]])
        self.assertEqual(neighbours[1], frozenset((0, 2)))
        self.assertEqual(neighbours[2], frozenset((1, 0)))
        self.assertEqual(neighbours[3], frozenset((0,)))

    def test_regret_repair_preserves_partition_and_capacity(self) -> None:
        distances = np.asarray(
            [
                [0, 2, 4, 6, 8, 10],
                [2, 0, 2, 4, 6, 8],
                [4, 2, 0, 2, 4, 6],
                [6, 4, 2, 0, 2, 4],
                [8, 6, 4, 2, 0, 2],
                [10, 8, 6, 4, 2, 0],
            ],
            dtype=np.int64,
        )
        demands = np.asarray([0, 1, 1, 1, 1, 1], dtype=np.int64)
        repaired = regret_repair(
            [[1, 2], [5]],
            [3, 4],
            demands=demands,
            capacity=3,
            max_routes=3,
            distances=distances,
            reference_edges=edge_signature([[1, 2, 3], [4, 5]]),
            mode="elite",
            allow_new_route=True,
        )
        self.assertTrue(partition_is_complete(repaired, 5))
        self.assertTrue(
            all(sum(demands[customer] for customer in route) <= 3 for route in repaired)
        )

    def test_route_elimination_repair_can_forbid_new_route(self) -> None:
        distances = np.ones((5, 5), dtype=np.int64)
        np.fill_diagonal(distances, 0)
        demands = np.asarray([0, 1, 1, 1, 1], dtype=np.int64)
        repaired = regret_repair(
            [[1, 2]],
            [3, 4],
            demands=demands,
            capacity=4,
            max_routes=4,
            distances=distances,
            reference_edges=edge_signature([[1, 2, 3, 4]]),
            mode="cost",
            allow_new_route=False,
        )
        self.assertEqual(len(repaired), 1)
        self.assertTrue(partition_is_complete(repaired, 4))


if __name__ == "__main__":
    unittest.main()
