from __future__ import annotations

import math
import tempfile
import unittest
import csv
from pathlib import Path
from unittest import mock

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
        stage_a = probe.select_instances("threeshift_stability_100_200")
        self.assertEqual(len(stage_a), 9)
        self.assertEqual(stage_a[0], ("threeshift", "e2-threeshift-100c-01", 100))
        self.assertEqual(stage_a[-1], ("threeshift", "e2-threeshift-200c-03", 200))
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
        self.assertIn("THREESHIFT_MIXED_GENERALIZES", probe.STAGEA_VERDICTS)

    def test_stageA_gate_requires_mixed_zero_violation_and_nonworse_cost_carbon(self) -> None:
        passing = {
            "status": "OK",
            "violation_count": 0,
            "ev_route_share": 0.30,
            "cost_gap_pct_vs_baseline": 0.0,
            "E_total_gap_pct_vs_baseline": -0.1,
        }
        failing = passing | {"ev_route_share": 0.29}

        self.assertTrue(probe.stageA_passes(passing))
        self.assertFalse(probe.stageA_passes(failing))

        decision = probe.stageA_decision({"phase0_ok": True}, [passing, failing])
        self.assertEqual(decision["verdict"], "THREESHIFT_MIXED_N1_ONLY")
        decision = probe.stageA_decision({"phase0_ok": True}, [passing, passing])
        self.assertEqual(decision["verdict"], "THREESHIFT_MIXED_GENERALIZES")

    def test_stageB_selects_anchor_150_and_passed_100_200_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stage_dir = Path(tmp)
            rows = [
                {"category": "threeshift", "instance": "e2-threeshift-100c-01", "size": 100, "status": "OK", "violation_count": 0, "ev_route_share": 0.26, "cost_gap_pct_vs_baseline": -1, "E_total_gap_pct_vs_baseline": -1},
                {"category": "threeshift", "instance": "e2-threeshift-100c-02", "size": 100, "status": "OK", "violation_count": 0, "ev_route_share": 0.31, "cost_gap_pct_vs_baseline": -1, "E_total_gap_pct_vs_baseline": -1},
                {"category": "threeshift", "instance": "e2-threeshift-150c-01", "size": 150, "status": "OK", "violation_count": 0, "ev_route_share": 0.20, "cost_gap_pct_vs_baseline": 1, "E_total_gap_pct_vs_baseline": 1},
                {"category": "threeshift", "instance": "e2-threeshift-200c-01", "size": 200, "status": "OK", "violation_count": 0, "ev_route_share": 0.40, "cost_gap_pct_vs_baseline": -1, "E_total_gap_pct_vs_baseline": -1},
            ]
            with (stage_dir / "ev_maximal_280_rows.csv").open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

            selected = probe.stageB_construction_rows(stage_dir)

        self.assertEqual([row["instance"] for row in selected], ["e2-threeshift-100c-02", "e2-threeshift-150c-01", "e2-threeshift-200c-01"])
        self.assertEqual(probe.stageB_runtime_cap(100), 900.0)
        self.assertEqual(probe.stageB_runtime_cap(150), 1800.0)
        self.assertEqual(probe.stageB_runtime_cap(200), 2700.0)

    def test_stageB_decision_requires_every_reported_baseline(self) -> None:
        rows = [{
            "gate_status": "OK",
            "violation_count": 0,
            "python": probe.GOLD_PYTHON,
            "numpy": probe.GOLD_NUMPY,
            "algorithm": "alns_e2_carbon",
            "ev_route_share": 0.50,
        }]
        pairs = []
        for baseline in ("LNS", "GA", "PSO"):
            pairs.extend({"right_algorithm": baseline, "gap_pct_left_minus_right": -10.0} for _ in range(6))
        pairs.extend({"right_algorithm": "VNS", "gap_pct_left_minus_right": 1.0} for _ in range(6))

        decision = probe.stageB_decision(
            {"phase0_ok": True},
            rows,
            pairs,
            pairs_ablation=[],
            expected_rows=1,
        )

        self.assertEqual(decision["verdict"], "MECHANISM_BUT_TIE")
        self.assertIn("VNS", decision["plain"])

    def test_retry_failures_reruns_runtime_under_eval_even_when_gate_status_ok(self) -> None:
        task = {"stage": "stageB", "instance": "e2-threeshift-100c-02", "seed": 1, "algorithm": "GA"}
        stale_row = task | {"status": "HALT_RUNTIME_UNDER_EVAL", "gate_status": "OK"}
        rerun_row = task | {"status": "OK", "gate_status": "OK"}

        with tempfile.TemporaryDirectory() as tmp:
            raw_path = Path(tmp) / "raw_runs.csv"
            with raw_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(stale_row))
                writer.writeheader()
                writer.writerow(stale_row)

            with mock.patch.object(probe, "run_search_task", return_value=rerun_row) as runner:
                rows = probe.run_search_tasks([task], workers=1, incremental_csv=raw_path, retry_failures=True)

        runner.assert_called_once_with(task)
        self.assertEqual(rows[0]["status"], "OK")
        self.assertNotEqual(rows[0].get("queue_action"), "SKIPPED_EXISTING")

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
