from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
from pyvrp import Solution
from pyvrp._pyvrp import RandomNumberGenerator

from safe_record_lns_worker import (
    BASE,
    SafeInsertionStats,
    is_record_improvement,
    route_is_feasible,
    safe_insertion_options,
    safe_regret_repair,
)


REPO = Path(__file__).resolve().parents[3]
BUNDLE = (
    REPO
    / "baselines/e2_alns/"
    "solomon_sintef_formal_bundles_20260717_v3/C105"
)
def _data():
    return BASE.build_model(BUNDLE, 1000, 10_000_000).data()


class SafeRecordLNSTest(unittest.TestCase):
    def test_record_gate_requires_current_and_global_improvement(self) -> None:
        self.assertTrue(is_record_improvement((9, 900), (10, 800), (10, 700)))
        self.assertFalse(is_record_improvement((10, 600), (10, 800), (9, 999)))
        self.assertFalse(is_record_improvement((10, 900), (10, 800), (10, 700)))

    def test_time_window_infeasible_positions_are_filtered(self) -> None:
        data = _data()
        demands = np.asarray(
            [0, *[int(client.delivery[0]) for client in data.clients()]],
            dtype=np.int64,
        )
        found = None
        for anchor in range(1, data.num_clients + 1):
            if not route_is_feasible(data, [anchor]):
                continue
            for customer in range(1, data.num_clients + 1):
                if customer == anchor:
                    continue
                stats = SafeInsertionStats()
                options = safe_insertion_options(
                    customer,
                    [[anchor]],
                    data=data,
                    demands=demands,
                    capacity=int(data.vehicle_type(0).capacity[0]),
                    max_routes=1,
                    reference_edges=frozenset(),
                    mode="cost",
                    allow_new_route=False,
                    stats=stats,
                )
                if not options and stats.time_window_filtered > 0:
                    found = (anchor, customer)
                    break
            if found:
                break
        self.assertIsNotNone(found)

    def test_existing_route_precedes_new_route_and_fixed_cost_is_charged(
        self,
    ) -> None:
        data = _data()
        demands = np.asarray(
            [0, *[int(client.delivery[0]) for client in data.clients()]],
            dtype=np.int64,
        )
        found = False
        for anchor in range(1, data.num_clients + 1):
            if not route_is_feasible(data, [anchor]):
                continue
            for customer in range(1, data.num_clients + 1):
                if customer == anchor:
                    continue
                stats = SafeInsertionStats()
                options = safe_insertion_options(
                    customer,
                    [[anchor]],
                    data=data,
                    demands=demands,
                    capacity=int(data.vehicle_type(0).capacity[0]),
                    max_routes=2,
                    reference_edges=frozenset(),
                    mode="cost",
                    allow_new_route=True,
                    stats=stats,
                )
                route_deltas = {option.route_delta for option in options}
                if route_deltas == {0, 1}:
                    self.assertEqual(options[0].route_delta, 0)
                    self.assertEqual(stats.new_route_options, 1)
                    self.assertEqual(
                        stats.fixed_cost_charged,
                        int(data.vehicle_type(0).fixed_cost),
                    )
                    found = True
                    break
            if found:
                break
        self.assertTrue(found)

    def test_repair_never_exceeds_route_cap(self) -> None:
        data = _data()
        demands = np.asarray(
            [0, *[int(client.delivery[0]) for client in data.clients()]],
            dtype=np.int64,
        )
        repaired = safe_regret_repair(
            [[1], [2]],
            [3],
            data=data,
            demands=demands,
            capacity=int(data.vehicle_type(0).capacity[0]),
            max_routes=2,
            reference_edges=frozenset(),
            mode="cost",
            allow_new_route=True,
            stats=SafeInsertionStats(),
        )
        self.assertTrue(repaired)
        self.assertLessEqual(len(repaired), 2)
        self.assertTrue(all(route_is_feasible(data, route) for route in repaired))

    def test_disabled_wrapper_returns_base_child_without_candidate_call(
        self,
    ) -> None:
        from safe_record_lns_worker import SafeRecordLNS

        data = _data()
        solution = Solution.make_random(
            data,
            RandomNumberGenerator(seed=1),
        )
        calls = {"candidate": 0}

        def base_search(value, _):
            return value

        def candidate_search(value, _):
            calls["candidate"] += 1
            return value

        wrapper = SafeRecordLNS(
            base_search,
            candidate_search,
            data=data,
            seed=1,
            enabled=False,
        )
        marker = object()
        self.assertIs(wrapper(solution, marker), solution)
        self.assertEqual(calls["candidate"], 0)

    def test_independent_candidate_rng_does_not_change_core_random_starts(
        self,
    ) -> None:
        data = _data()
        first_core = RandomNumberGenerator(seed=7)
        first = [
            Solution.make_random(data, first_core)
            for _ in range(4)
        ]

        second_core = RandomNumberGenerator(seed=7)
        _candidate_rng = RandomNumberGenerator(seed=7 + 104729)
        second = [
            Solution.make_random(data, second_core)
            for _ in range(4)
        ]
        first_routes = [BASE.routes_from(solution) for solution in first]
        second_routes = [BASE.routes_from(solution) for solution in second]
        self.assertEqual(first_routes, second_routes)


if __name__ == "__main__":
    unittest.main()
