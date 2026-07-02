from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search import metaheuristic_baselines as mb

from baselines.e2_alns import native_channel_autopsy as autopsy


class NativeChannelAutopsyTest(unittest.TestCase):
    def test_static_fact_checks_pass(self) -> None:
        checks = autopsy.static_fact_checks()

        self.assertEqual(set(checks), {
            "A1_baseline_forces_true_repair_zero",
            "A2_route_scoring_downgrades_to_distance",
            "A3_e2_alns_uses_true_repair_one",
            "A4_decode_fallback_to_all_cv_on_violations",
            "A5_route_plan_feasible_uses_cv_temp_route",
        })
        self.assertTrue(all(row["pass"] for row in checks.values()))

    def test_probe_price_override_does_not_mutate_default(self) -> None:
        prices = autopsy.make_probe_prices()

        self.assertAlmostEqual(float(prices.B_battery_kwh), 280.0)
        self.assertAlmostEqual(float(prices.carbon_price), autopsy.CARBON_PRICE)
        self.assertAlmostEqual(float(DEFAULT_PRICES.B_battery_kwh), 80.0)

    def test_instrumentation_restores_metaheuristic_functions(self) -> None:
        originals = (
            mb._SearchSession.score,
            mb._order_to_solution,
            mb._decode_order_like_random_key,
            mb._all_cv_solution_for_session,
            mb._baseline_fast_repair_flags,
        )
        tracer = autopsy.NativeProbeTracer(
            run_id="unit",
            phase="B0",
            algorithm="LNS",
            condition="unit",
            seed=1,
            candidate_rows=[],
            decode_rows=[],
            trajectory_rows=[],
            order_stack=[],
        )

        with autopsy.instrument_baseline(tracer, force_true_repair_one=True):
            self.assertIsNot(mb._order_to_solution, originals[1])
            self.assertIsNot(mb._baseline_fast_repair_flags, originals[4])

        self.assertIs(mb._SearchSession.score, originals[0])
        self.assertIs(mb._order_to_solution, originals[1])
        self.assertIs(mb._decode_order_like_random_key, originals[2])
        self.assertIs(mb._all_cv_solution_for_session, originals[3])
        self.assertIs(mb._baseline_fast_repair_flags, originals[4])

    def test_artifact_hashes_exclude_appledouble_and_caches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            report = root / "report.md"
            (out / "raw_runs.csv").write_text("a\n1\n", encoding="utf-8")
            (out / "._raw_runs.csv").write_text("bad", encoding="utf-8")
            (out / "__pycache__").mkdir()
            (out / "__pycache__" / "x.pyc").write_bytes(b"bad")
            (out / ".pytest_cache").mkdir()
            (out / ".pytest_cache" / "x").write_text("bad", encoding="utf-8")
            (out / "artifact_hashes.json").write_text("old", encoding="utf-8")
            report.write_text("# report\n", encoding="utf-8")

            hashes = autopsy.artifact_hashes(out, report)

        paths = [row["path"] for row in hashes["files"]]
        self.assertTrue(any(str(path).endswith("raw_runs.csv") for path in paths))
        self.assertTrue(any(str(path).endswith("report.md") for path in paths))
        self.assertFalse(any("._" in str(path) for path in paths))
        self.assertFalse(any("__pycache__" in str(path) for path in paths))
        self.assertFalse(any(".pytest_cache" in str(path) for path in paths))
        self.assertFalse(any(str(path).endswith("artifact_hashes.json") for path in paths))


if __name__ == "__main__":
    unittest.main()
