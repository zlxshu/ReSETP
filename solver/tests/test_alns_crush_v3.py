from __future__ import annotations

import unittest

from setp_solver.search.alns_crush_v3 import (
    capacity_route_lower_bound,
    customer_shift_map,
    first_fit_decreasing_bin_count,
)


class AlnsCrushV3Tests(unittest.TestCase):
    def test_capacity_route_lower_bound_ceil_total_demand(self) -> None:
        self.assertEqual(capacity_route_lower_bound([600.0, 700.0, 701.0], 1000.0), 3)
        self.assertEqual(capacity_route_lower_bound([400.0, 600.0], 1000.0), 1)

    def test_first_fit_decreasing_bin_count_reports_capacity_only_diagnostic(self) -> None:
        result = first_fit_decreasing_bin_count([800.0, 700.0, 600.0, 300.0, 200.0], 1000.0)

        self.assertEqual(result["bin_count"], 3)
        self.assertAlmostEqual(result["total_demand"], 2600.0)
        self.assertAlmostEqual(result["total_slack"], 400.0)

    def test_customer_shift_map_uses_manifest_shift_seconds(self) -> None:
        manifest = {
            "kept_customers": [
                {"new_node_id": "C001", "shift_seconds": 0.0},
                {"new_node_id": "C101", "shift_seconds": 32400.0},
                {"new_node_id": "C201", "shift_seconds": 64800.0},
            ]
        }

        self.assertEqual(customer_shift_map(manifest), {"C001": 0, "C101": 1, "C201": 2})


if __name__ == "__main__":
    unittest.main()
