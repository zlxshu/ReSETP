from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from baselines.e2_alns import selector_pathology_audit as audit


class SelectorPathologyAuditTests(unittest.TestCase):
    def test_pair_usage_aggregates_attempts_rates_and_route_delta(self) -> None:
        rows = [
            {
                "profile": "A0_MAIN_LOCAL_SEARCH",
                "destroy_id": "random_customer_removal",
                "repair_id": "greedy_insert_repair",
                "accepted": "True",
                "best_improved": "True",
                "revert_reason": "candidate_usable",
                "candidate_route_count_delta": "-1",
            },
            {
                "profile": "A0_MAIN_LOCAL_SEARCH",
                "destroy_id": "random_customer_removal",
                "repair_id": "greedy_insert_repair",
                "accepted": "False",
                "best_improved": "False",
                "revert_reason": "unchanged",
                "candidate_route_count_delta": "1",
            },
            {
                "profile": "A3_BACKEND_LOCAL_SEARCH",
                "destroy_id": "shaw_related_removal",
                "repair_id": "regret3_insert_repair",
                "accepted": "True",
                "best_improved": "False",
                "revert_reason": "candidate_usable",
                "candidate_route_count_delta": "UNKNOWN",
            },
        ]

        usage = audit.selector_pair_usage(rows)

        a0 = next(row for row in usage if row["profile"] == "A0_MAIN_LOCAL_SEARCH")
        self.assertEqual(a0["pair"], "random_customer_removal+greedy_insert_repair")
        self.assertEqual(a0["attempts"], 2)
        self.assertEqual(a0["accepted_count"], 1)
        self.assertEqual(a0["best_improved_count"], 1)
        self.assertEqual(a0["unchanged_count"], 1)
        self.assertEqual(a0["accepted_rate"], 0.5)
        self.assertEqual(a0["best_improved_rate"], 0.5)
        self.assertEqual(a0["unchanged_rate"], 0.5)
        self.assertEqual(a0["mean_candidate_route_count_delta"], 0.0)

        a3 = next(row for row in usage if row["profile"] == "A3_BACKEND_LOCAL_SEARCH")
        self.assertEqual(a3["mean_candidate_route_count_delta"], "UNKNOWN")

    def test_entropy_summary_reports_top_shares_and_starvation(self) -> None:
        usage = [
            {"profile": "A0_MAIN_LOCAL_SEARCH", "pair": "a+x", "attempts": 80, "best_improved_count": 8},
            {"profile": "A0_MAIN_LOCAL_SEARCH", "pair": "b+y", "attempts": 20, "best_improved_count": 2},
            {"profile": "A0_MAIN_LOCAL_SEARCH", "pair": "c+z", "attempts": 0, "best_improved_count": 0},
        ]

        summary = audit.selector_entropy_by_profile(usage, expected_pair_count_by_profile={"A0_MAIN_LOCAL_SEARCH": 3}, starvation_share=0.01)
        row = summary[0]

        self.assertEqual(row["total_attempts"], 100)
        self.assertAlmostEqual(row["top1_pair_share"], 0.8)
        self.assertAlmostEqual(row["top2_pair_share"], 1.0)
        self.assertEqual(row["starving_pair_count"], 1)
        self.assertAlmostEqual(row["best_improved_top1_share"], 0.8)
        self.assertGreater(row["pair_entropy"], 0.0)
        self.assertLess(row["normalized_pair_entropy"], 1.0)

    def test_lns_distribution_filters_strong_bridge_only(self) -> None:
        lns_rows = [
            {"trace_path": "strong_bridge", "destroy": "random_customer_removal", "repair": "greedy_insert_repair", "best_improved": "True"},
            {"trace_path": "fallback_relocate", "destroy": "random_customer_removal", "repair": "greedy_insert_repair", "best_improved": "True"},
            {"trace_path": "strong_bridge", "destroy": "shaw_related_removal", "repair": "regret2_insert_repair", "best_improved": "False"},
        ]

        rows = audit.lns_strong_bridge_pair_usage(lns_rows)

        self.assertEqual(sum(row["attempts"] for row in rows), 2)
        self.assertEqual({row["profile"] for row in rows}, {"LNS_STRONG_BRIDGE"})
        self.assertEqual(sum(row["best_improved_count"] for row in rows), 1)

    def test_selector_value_bound_shows_reward_gap_dominates_exploration(self) -> None:
        bounds = audit.selector_value_bounds(iterations=[100, 1000, 4000, 16000], alpha=0.08)

        self.assertEqual([row["iteration"] for row in bounds], [100, 1000, 4000, 16000])
        self.assertTrue(all(row["untried_pair_value"] < 8.0 for row in bounds))
        self.assertTrue(all(row["reward8_dominates_untried"] for row in bounds))
        self.assertTrue(all(row["reward20_dominates_untried"] for row in bounds))

    def test_decision_gate_distinguishes_supported_and_not_supported(self) -> None:
        supported = audit.build_decision(
            metadata={"head": "abc"},
            entropy_rows=[
                {"profile": "A0_MAIN_LOCAL_SEARCH", "normalized_pair_entropy": 0.55, "top1_pair_share": 0.50, "top2_pair_share": 0.75},
                {"profile": "A3_BACKEND_LOCAL_SEARCH", "normalized_pair_entropy": 0.61, "top1_pair_share": 0.46, "top2_pair_share": 0.69},
                {"profile": "LNS_STRONG_BRIDGE", "normalized_pair_entropy": 0.98, "top1_pair_share": 0.15, "top2_pair_share": 0.29},
            ],
            usage_rows=[
                {"profile": "A0_MAIN_LOCAL_SEARCH", "best_improved_count": 100, "best_improved_top3_member": True},
                {"profile": "A0_MAIN_LOCAL_SEARCH", "best_improved_count": 10, "best_improved_top3_member": False},
                {"profile": "A3_BACKEND_LOCAL_SEARCH", "best_improved_count": 140, "best_improved_top3_member": True},
                {"profile": "A3_BACKEND_LOCAL_SEARCH", "best_improved_count": 10, "best_improved_top3_member": False},
            ],
            value_bounds=[
                {"reward8_dominates_untried": True, "reward20_dominates_untried": True},
                {"reward8_dominates_untried": True, "reward20_dominates_untried": True},
            ],
            protected=[],
            missing=[],
        )
        self.assertEqual(supported["verdict"], "SELECTOR_PATHOLOGY_SUPPORTED")

        not_supported = audit.build_decision(
            metadata={"head": "abc"},
            entropy_rows=[
                {"profile": "A0_MAIN_LOCAL_SEARCH", "normalized_pair_entropy": 0.90, "top1_pair_share": 0.20, "top2_pair_share": 0.40},
                {"profile": "A3_BACKEND_LOCAL_SEARCH", "normalized_pair_entropy": 0.91, "top1_pair_share": 0.19, "top2_pair_share": 0.39},
                {"profile": "LNS_STRONG_BRIDGE", "normalized_pair_entropy": 0.92, "top1_pair_share": 0.18, "top2_pair_share": 0.37},
            ],
            usage_rows=[],
            value_bounds=[{"reward8_dominates_untried": True}],
            protected=[],
            missing=[],
        )
        self.assertEqual(not_supported["verdict"], "SELECTOR_PATHOLOGY_NOT_SUPPORTED")

    def test_decision_gate_halts_on_missing_or_protected_diff(self) -> None:
        decision = audit.build_decision(
            metadata={"head": "abc"},
            entropy_rows=[],
            usage_rows=[],
            value_bounds=[],
            protected=["solver/src/setp_solver/cost.py"],
            missing=["alns_candidate_trace.csv"],
        )

        self.assertEqual(decision["verdict"], "HALT_SELECTOR_PATHOLOGY_AUDIT")
        self.assertTrue(decision["halt"])

    def test_hashes_exclude_sidecars_caches_and_tasks(self) -> None:
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

            audit.write_hashes(root)
            hashes = json.loads((root / "artifact_hashes.json").read_text(encoding="utf-8"))

        self.assertEqual(sorted(hashes["files"]), ["keep.txt"])


if __name__ == "__main__":
    unittest.main()
