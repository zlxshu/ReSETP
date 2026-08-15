from __future__ import annotations

from dataclasses import replace
import math
from types import SimpleNamespace
import unittest

import numpy as np

from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES, UK_2025_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvaluationContext, score_reference
from setp_solver.search.winner_operators import WinnerOperatorAction, WinnerOperatorSet, apply_winner_action, e2_alns_throughput_flags

from baselines.e2_alns import ev_heavy_findability_gate as gate
from baselines.e2_alns import ev_heavy_regime_decision_probe as regime


class EvHeavyFindabilityGateTest(unittest.TestCase):
    def test_neutral_seed_does_not_load_ev_maximal_solution(self) -> None:
        bundle = load_search_bundle(regime.bundle_path("vanilla", "e2-vanilla-10c-01"))
        prices = replace(UK_2025_PRICES, B_battery_kwh=280.0, carbon_price=gate.CARBON_PRICE)

        _solution, source = gate.neutral_seed(bundle, prices)

        self.assertEqual(source, "rebuilt_make_shared_initial_solution")
        self.assertNotIn("ev_maximal", source)
        self.assertAlmostEqual(float(DEFAULT_PRICES.B_battery_kwh), 80.0)

    def test_markdown_report_path_is_rejected(self) -> None:
        self.assertIsNone(gate.report_path_from_args(SimpleNamespace(report_path="")))
        with self.assertRaises(ValueError):
            gate.report_path_from_args(SimpleNamespace(report_path="baselines/e2_alns/no_report.md"))

    def test_search_row_has_required_diagnostic_fields(self) -> None:
        task = {
            "stage": "neutral-search-gate",
            "repo_root": str(gate.REPO_ROOT),
            "output_dir": "",
            "category": "vanilla",
            "instance": "e2-vanilla-10c-01",
            "size": 10,
            "seed": 1,
            "algorithm": "PSO",
            "battery_kwh": 280.0,
            "bundle_dir": str(regime.bundle_path("vanilla", "e2-vanilla-10c-01").relative_to(gate.REPO_ROOT)),
            "eval_budget": 2,
            "runtime_cap_seconds": 30.0,
            "comparison_mode": "wallclock",
            "seed_mode": "neutral",
            "checkpoint_path": "",
        }

        row = gate.run_search_task(task)

        required = {
            "initial_cost",
            "best_cost",
            "gap_vs_initial_pct",
            "gap_to_ev_maximal_pct",
            "initial_ev_share",
            "best_ev_share",
            "returned_initial_signature",
            "best_improvement_count",
            "first_improvement_eval",
            "actual_evals",
            "elapsed_seconds",
            "operator_counts",
            "history_json",
            "seed_source",
        }
        self.assertTrue(required.issubset(row))
        self.assertEqual(row["seed_source"], "rebuilt_make_shared_initial_solution")
        self.assertEqual(row["seed_mode"], "neutral")
        self.assertTrue(math.isfinite(float(row["initial_cost"])))
        self.assertGreaterEqual(int(row["actual_evals"]), 0)

    def test_ev_swap_audit_emits_failure_bucket_and_cost_delta(self) -> None:
        rows = gate.ev_swap_audit_instance("vanilla", "e2-vanilla-10c-01", 10, 280.0)

        self.assertGreater(len(rows), 0)
        self.assertTrue(all("failure_reason" in row for row in rows))
        self.assertTrue(all("cost_delta" in row for row in rows))
        self.assertTrue(all("cost_delta_pct" in row for row in rows))
        self.assertTrue(set(row["failure_reason"] for row in rows))

    def test_decision_prefers_search_cannot_use_ev_path_when_audit_has_path_but_search_does_not(self) -> None:
        phase0 = {"phase0_ok": True}
        rows = [
            {
                "algorithm": "alns_e2_carbon",
                "gate_status": "OK",
                "closed_gap_fraction": 0.0,
                "ev_share_gain": 0.0,
                "gap_vs_initial_pct": 0.0,
                "returned_initial_signature": True,
            }
        ]
        audit = [{"accepted": True, "failure_reason": "ACCEPTED"}]

        decision = gate.findability_decision(phase0, rows, audit, expected_rows=1)

        self.assertEqual(decision["verdict"], "HALT_SEARCH_CANNOT_USE_EV_PATH")

    def test_decision_detects_alns_find_signal(self) -> None:
        phase0 = {"phase0_ok": True}
        rows = [
            {
                "algorithm": "alns_e2_carbon",
                "gate_status": "OK",
                "closed_gap_fraction": 0.25,
                "ev_share_gain": 0.10,
                "gap_vs_initial_pct": -2.0,
                "returned_initial_signature": False,
            }
        ]

        decision = gate.findability_decision(phase0, rows, [], expected_rows=1)

        self.assertEqual(decision["verdict"], "PASS_ALNS_FIND_SIGNAL")

    def test_winner_vehicle_type_swap_uses_instance_fleet_caps(self) -> None:
        bundle = load_search_bundle(regime.bundle_path("threeshift", "e2-threeshift-150c-01"))
        prices = replace(UK_2025_PRICES, B_battery_kwh=280.0, carbon_price=gate.CARBON_PRICE)
        neutral, _source = gate.neutral_seed(bundle, prices)
        context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices, repair_delta_mode="fast")
        initial_obj = score_reference(neutral, context)

        result = apply_winner_action(
            neutral,
            WinnerOperatorAction("vehicle_type_swap", "greedy_insert_repair", (5, 0, -1, -1)),
            context,
            rng=np.random.default_rng(1),
            operator_set=WinnerOperatorSet.create(carbon_aware=False),
            current_obj=initial_obj,
            variant_flags=e2_alns_throughput_flags(),
        )

        self.assertTrue(result["trace"]["changed"])
        self.assertLess(result["candidate_obj"], initial_obj)
        self.assertFalse(check_solution(result["candidate_solution"], bundle.instance, prices))


if __name__ == "__main__":
    unittest.main()
