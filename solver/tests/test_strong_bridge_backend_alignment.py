from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.evaluation import EvaluationContext, score_reference
from setp_solver.search.winner_operators import (
    STRONG_BRIDGE_BACKEND_FLAG,
    TRACE_DIAGNOSTIC_FLAG,
    WinnerOperatorAction,
    WinnerKernelConfig,
    _derive_strong_bridge_rng,
    apply_winner_action,
    e2_alns_throughput_flags,
    run_e2_alns_throughput,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/verify_20251113"


class StrongBridgeBackendAlignmentTests(unittest.TestCase):
    def test_flag_defaults_off_and_legacy_trace_schema_stays_off(self) -> None:
        result = run_e2_alns_throughput(
            VERIFY_BUNDLE,
            config=WinnerKernelConfig(seed=11, eval_budget=4, max_runtime_seconds=120.0),
        )

        self.assertEqual(result["flags"][STRONG_BRIDGE_BACKEND_FLAG], "0")
        self.assertNotIn("candidate_trace", result["operator_counts"])
        self.assertNotIn("route_count", result["history"][0])

    def test_flag_enabled_uses_strong_bridge_backend_for_supported_pair(self) -> None:
        bundle = load_search_bundle(VERIFY_BUNDLE)
        solution = make_shared_initial_solution(bundle)
        context = EvaluationContext(bundle.instance, bundle.carbon_profile)
        objective = score_reference(solution, context)
        flags = e2_alns_throughput_flags()
        flags[TRACE_DIAGNOSTIC_FLAG] = "1"
        flags[STRONG_BRIDGE_BACKEND_FLAG] = "1"

        result = apply_winner_action(
            solution,
            WinnerOperatorAction("random_customer_removal", "greedy_insert_repair"),
            context,
            rng=np.random.default_rng(123),
            current_obj=objective,
            progress=0.25,
            variant_flags=flags,
        )

        trace = result["trace"]
        self.assertEqual(trace["candidate_backend"], "strong_bridge_backend")
        self.assertEqual(trace["strong_bridge_backend_destroy"], "random_customer_removal")
        self.assertEqual(trace["strong_bridge_backend_repair"], "greedy_insert_repair")
        self.assertIn("strong_bridge_backend_removed_count", trace)
        self.assertIn("strong_bridge_backend_detail", trace)
        self.assertGreaterEqual(result["actual_evals_added"], 1)

    def test_strong_bridge_backend_does_not_capture_non_supported_pair(self) -> None:
        bundle = load_search_bundle(VERIFY_BUNDLE)
        solution = make_shared_initial_solution(bundle)
        context = EvaluationContext(bundle.instance, bundle.carbon_profile)
        objective = score_reference(solution, context)
        flags = e2_alns_throughput_flags()
        flags[TRACE_DIAGNOSTIC_FLAG] = "1"
        flags[STRONG_BRIDGE_BACKEND_FLAG] = "1"

        result = apply_winner_action(
            solution,
            WinnerOperatorAction("route_segment_removal", "greedy_insert_repair"),
            context,
            rng=np.random.default_rng(123),
            current_obj=objective,
            progress=0.25,
            variant_flags=flags,
        )

        self.assertEqual(result["trace"]["candidate_backend"], "winner_operator_set")
        self.assertEqual(result["trace"]["strong_bridge_backend_removed_count"], "N/A")

    def test_np_rng_to_random_rng_derivation_is_deterministic(self) -> None:
        first = _derive_strong_bridge_rng(np.random.default_rng(77))
        second = _derive_strong_bridge_rng(np.random.default_rng(77))

        self.assertEqual(first.random(), second.random())
        self.assertEqual(first.randint(1, 1000), second.randint(1, 1000))

    def test_probe_task_contract_and_decision_gate(self) -> None:
        from baselines.e2_alns import strong_bridge_backend_probe as probe

        hard_subset = [{"category": "vanilla", "instance": "e2-vanilla-10c-01"}]
        with tempfile.TemporaryDirectory() as tmp:
            tasks = probe.build_probe_tasks(
                Path(tmp),
                hard_subset,
                seeds=[1],
                eval_budget=4000,
                runtime_cap_seconds=900.0,
            )
            decision = probe.build_decision(
                metadata={"head": "abc"},
                rows=[
                    {"status": "OK", "profile": "A0_TRACE"},
                    {"status": "OK", "profile": "A3_STRONG_BRIDGE_BACKEND"},
                    {"status": "OK", "profile": "LNS_TRACE_REFERENCE"},
                ],
                expected_rows=3,
                profile_summary=[
                    {"profile": "A0_TRACE", "mean_gap_vs_lns": -0.05, "unchanged_rate": 0.60, "best_improved_rate": 0.010},
                    {"profile": "A3_STRONG_BRIDGE_BACKEND", "mean_gap_vs_lns": -0.02, "unchanged_rate": 0.40, "best_improved_rate": 0.020},
                ],
                pair_comparison=[
                    {
                        "wins_vs_a0": 1,
                        "losses_vs_a0": 0,
                        "a3_mean_gap_vs_lns": -0.02,
                        "a0_mean_gap_vs_lns": -0.05,
                        "a3_unchanged_rate": 0.40,
                        "a0_unchanged_rate": 0.60,
                        "a3_best_improved_rate": 0.020,
                        "a0_best_improved_rate": 0.010,
                    }
                ],
            )

        self.assertEqual([task["profile"] for task in tasks], ["A0_TRACE", "A3_STRONG_BRIDGE_BACKEND", "LNS_TRACE_REFERENCE"])
        self.assertEqual(len(tasks), 3)
        self.assertTrue(decision["diagnostic_only"])
        self.assertFalse(decision["formal_t3"])
        self.assertFalse(decision["algorithm_win_loss_claim"])
        self.assertEqual(decision["verdict"], "A3_STRONG_BRIDGE_BACKEND_PROMISING")

    def test_probe_hashes_exclude_sidecars_and_task_dirs(self) -> None:
        from baselines.e2_alns import strong_bridge_backend_probe as probe

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "keep.txt").write_text("keep", encoding="utf-8")
            (root / "._keep.txt").write_text("sidecar", encoding="utf-8")
            (root / ".tasks").mkdir()
            (root / ".tasks/row.json").write_text("{}", encoding="utf-8")
            (root / "__pycache__").mkdir()
            (root / "__pycache__/x.pyc").write_text("cache", encoding="utf-8")
            (root / ".pytest_cache").mkdir()
            (root / ".pytest_cache/x").write_text("cache", encoding="utf-8")

            probe.write_hashes(root)
            hashes = json.loads((root / "artifact_hashes.json").read_text(encoding="utf-8"))

        self.assertEqual(sorted(hashes["files"]), ["keep.txt"])

    def test_lns_reference_cost_uses_candidate_improvement_not_only_previous_best(self) -> None:
        from baselines.e2_alns import strong_bridge_backend_probe as probe

        rows = [
            {"previous_best_obj": "100.0", "candidate_obj": "105.0"},
            {"previous_best_obj": "100.0", "candidate_obj": "90.0"},
        ]

        self.assertEqual(probe.best_lns_reference_cost(rows), 90.0)


if __name__ == "__main__":
    unittest.main()
