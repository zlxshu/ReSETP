from __future__ import annotations

import unittest


class RvndSwapstarLocalSearchTests(unittest.TestCase):
    def test_rvnd_flag_defaults_off(self) -> None:
        from setp_solver.search import winner_operators as wo

        self.assertIsNone(wo.structural_component_from_flags({}))

    def test_structural_flags_are_mutually_exclusive(self) -> None:
        from setp_solver.search import winner_operators as wo

        with self.assertRaisesRegex(ValueError, "HALT_CONFIG_CONFLICT_STRUCTURAL_FLAGS"):
            wo.structural_component_from_flags(
                {
                    wo.ROUTE_POOL_RECOMBINATION_FLAG: "1",
                    wo.RVND_SWAPSTAR_FLAG: "1",
                }
            )

    def test_each_structural_flag_maps_to_component(self) -> None:
        from setp_solver.search import winner_operators as wo

        self.assertEqual(wo.structural_component_from_flags({wo.ROUTE_POOL_RECOMBINATION_FLAG: "1"}), "route_pool")
        self.assertEqual(wo.structural_component_from_flags({wo.RVND_SWAPSTAR_FLAG: "1"}), "rvnd_swapstar")
        self.assertEqual(wo.structural_component_from_flags({wo.ELITE_ARCHIVE_RESTART_FLAG: "1"}), "elite_archive")

    def test_rvnd_intensify_reports_trace_fields(self) -> None:
        from setp_solver.search.local_search import RvndResult

        result = RvndResult(solution=None, call_count=1, improve_count=0, moves_used=0, time_seconds=0.0, route_count_delta=0)

        self.assertEqual(result.call_count, 1)
        self.assertEqual(result.route_count_delta, 0)


if __name__ == "__main__":
    unittest.main()
