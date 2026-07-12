from __future__ import annotations

import unittest

from setp_solver.algorithms.resetp_alns.kernel.winner import _with_tvci_metadata
from setp_solver.algorithms.resetp_alns.naming import (
    TVCI_ALNS_DISPLAY_NAME,
    TVCI_ALNS_ID,
    TVCI_ALNS_NAME_EN,
    TVCI_ALNS_NAME_ZH,
)


class TvciAlnsNamingTests(unittest.TestCase):
    def test_public_name_constants_are_stable(self) -> None:
        self.assertEqual(TVCI_ALNS_ID, "TVCI-ALNS")
        self.assertEqual(TVCI_ALNS_NAME_EN, "Time-Varying Carbon-Intensity-Guided ALNS")
        self.assertEqual(TVCI_ALNS_NAME_ZH, "时变碳强度引导的自适应大邻域搜索")
        self.assertIn(TVCI_ALNS_ID, TVCI_ALNS_DISPLAY_NAME)

    def test_new_name_keeps_legacy_id_for_traceability(self) -> None:
        aware = _with_tvci_metadata({"variant": "staged_hybrid_carbon_schedule_aware"})
        naive = _with_tvci_metadata({"variant": "staged_hybrid_carbon_schedule_naive"}, charging_strategy="naive")
        self.assertEqual(aware["algorithm"], "TVCI-ALNS")
        self.assertEqual(aware["algorithm_legacy_id"], "staged_hybrid_carbon_aware")
        self.assertEqual(naive["algorithm"], "TVCI-ALNS-NAIVE")
        self.assertEqual(naive["algorithm_legacy_id"], "staged_hybrid_carbon_schedule_naive")


if __name__ == "__main__":
    unittest.main()
