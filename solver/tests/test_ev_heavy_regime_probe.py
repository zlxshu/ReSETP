from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from setp_solver.prices import DEFAULT_PRICES

from baselines.e2_alns import ev_heavy_regime_decision_probe as probe


class EvHeavyRegimeProbeTest(unittest.TestCase):
    def test_select_instances_and_seed_parsing(self) -> None:
        reps = probe.select_instances("representative_big")
        self.assertEqual(len(reps), 5)
        self.assertIn(("vanilla", "e2-vanilla-150c-01", 150), reps)

        gradient = probe.select_instances("gradient01_75_200")
        self.assertEqual(len(gradient), 12)
        self.assertTrue(all(size >= 75 for _, _, size in gradient))
        self.assertEqual(probe.parse_seeds("1-3"), [1, 2, 3])
        self.assertEqual(probe.parse_seeds("1,3"), [1, 3])

    def test_failure_classification(self) -> None:
        self.assertEqual(probe.classify_exception(ValueError("Fixed route segment requires 120 kWh > B=80")), "RANGE_BATTERY_80KWH")
        self.assertEqual(probe.classify_exception(ValueError("No feasible depot charging window")), "CHARGING_TIME_WINDOW_DETOUR")
        self.assertEqual(probe.classify_exception(ValueError("No charging stations available")), "STATION_OR_DEPOT_CAPACITY")

    def test_wilcoxon_fallback_shape_and_verdict_whitelists(self) -> None:
        stats = probe.wilcoxon_or_sign([-1.0, -2.0, 0.0, 3.0])
        self.assertIn(stats["method"], {"scipy_wilcoxon_less", "sign_test_less"})
        self.assertTrue(math.isfinite(float(stats["p_value_less"])))

        self.assertIn("X_SEARCH_MISSED_FEASIBLE_EV", probe.STAGE0_VERDICTS)
        self.assertIn("A_EV_RETAINED_BUT_ALNS_TIES", probe.STAGE1_VERDICTS)
        self.assertIn("B_MODERN_REGIME_WORKS", probe.STAGE2_VERDICTS)

    def test_stage0_instance_constructs_checked_rows_without_polluting_default_prices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = probe.stage0_instance("vanilla", "e2-vanilla-150c-01", 150, 80.0, Path(tmp))

        baseline = result["baseline_row"]
        ev_row = result["ev_row"]
        self.assertEqual(baseline["status"], "OK")
        self.assertEqual(ev_row["status"], "OK")
        self.assertEqual(ev_row["violation_count"], 0)
        self.assertGreaterEqual(ev_row["attempted_conversions"], ev_row["accepted_conversions"])
        self.assertIn(ev_row["instance_verdict"], probe.STAGE0_VERDICTS)
        self.assertAlmostEqual(float(DEFAULT_PRICES.B_battery_kwh), 80.0)

    def test_headroom_audit_has_expected_fields(self) -> None:
        rows = probe.headroom_audit([("vanilla", "e2-vanilla-150c-01", 150)], 280.0)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["instance"], "e2-vanilla-150c-01")
        self.assertGreater(row["num_ev"], 0)
        self.assertGreater(row["demand_route_lower_bound"], 0)
        self.assertIn("headroom_ge_20pct_two_trip", row)

    def test_formal_10001_winner_anchor_is_recorded_exactly(self) -> None:
        report = probe.REPO_ROOT / "solver/reports/formal_winner_20260619/final_report.md"
        text = report.read_text(encoding="utf-8")
        self.assertIn("4878.331796187524", text)


if __name__ == "__main__":
    unittest.main()
