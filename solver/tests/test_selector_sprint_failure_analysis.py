from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class SelectorSprintFailureAnalysisTests(unittest.TestCase):
    def test_gap_summary_groups_by_budget_family_and_size(self) -> None:
        from baselines.e2_alns import selector_sprint_failure_analysis as analysis

        rows = [
            {"budget": "16000", "profile": "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH", "category": "threeshift", "instance": "e2-threeshift-100c-01", "seed": "1", "best_cost": "102.0", "status": "OK"},
            {"budget": "16000", "profile": "LNS_REFERENCE", "category": "threeshift", "instance": "e2-threeshift-100c-01", "seed": "1", "best_cost": "100.0", "status": "OK"},
            {"budget": "16000", "profile": "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH", "category": "threeshift", "instance": "e2-threeshift-200c-01", "seed": "1", "best_cost": "98.0", "status": "OK"},
            {"budget": "16000", "profile": "LNS_REFERENCE", "category": "threeshift", "instance": "e2-threeshift-200c-01", "seed": "1", "best_cost": "100.0", "status": "OK"},
        ]

        summary = analysis.gap_by_family_size_budget(rows, profiles=["A7_SOFTMAX_SELECTOR_LOCAL_SEARCH"])

        by_key = {(row["budget"], row["profile"], row["family"], row["size"]): row for row in summary}
        self.assertLess(float(by_key[("16000", "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH", "threeshift", "100c")]["mean_gap_vs_lns"]), 0.0)
        self.assertGreater(float(by_key[("16000", "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH", "threeshift", "200c")]["mean_gap_vs_lns"]), 0.0)

    def test_precheck_supports_route_fixed_residual_with_scale_pattern(self) -> None:
        from baselines.e2_alns import selector_sprint_failure_analysis as analysis

        decomposition_rows = [
            {"budget": "16000", "profile": "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH", "category": "threeshift", "instance": "e2-threeshift-100c-01", "seed": "1", "route_count_delta_vs_lns": "1", "cost_fix_delta_vs_lns": "80"},
            {"budget": "16000", "profile": "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH", "category": "threeshift", "instance": "e2-threeshift-100c-02", "seed": "1", "route_count_delta_vs_lns": "1", "cost_fix_delta_vs_lns": "80"},
            {"budget": "16000", "profile": "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH", "category": "threeshift", "instance": "e2-threeshift-200c-01", "seed": "1", "route_count_delta_vs_lns": "0", "cost_fix_delta_vs_lns": "0"},
        ]
        gap_rows = [
            {"budget": "16000", "profile": "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH", "family": "threeshift", "size": "100c", "mean_gap_vs_lns": "-0.02", "rows": "2"},
            {"budget": "16000", "profile": "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH", "family": "threeshift", "size": "200c", "mean_gap_vs_lns": "0.01", "rows": "1"},
        ]

        decision = analysis.build_decision(
            metadata={"schema": "test"},
            gap_rows=gap_rows,
            route_fixed_rows=analysis.route_fixed_gap_by_family_size_budget(decomposition_rows),
            missing=[],
            protected_diff="",
        )

        self.assertEqual(decision["verdict"], "STRUCTURAL_RESCUE_PRECHECK_SUPPORTED")
        self.assertFalse(decision["halt"])

    def test_hash_excludes_sidecars_caches_and_tasks(self) -> None:
        from baselines.e2_alns import selector_sprint_failure_analysis as analysis
        from baselines.e2_alns import e2_final_closure as fc

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "keep.txt").write_text("keep", encoding="utf-8")
            (root / "._sidecar").write_text("sidecar", encoding="utf-8")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "x.pyc").write_text("cache", encoding="utf-8")
            (root / ".pytest_cache").mkdir()
            (root / ".pytest_cache" / "x").write_text("cache", encoding="utf-8")
            (root / ".tasks").mkdir()
            (root / ".tasks" / "row.json").write_text("{}", encoding="utf-8")

            analysis.write_hashes(root)
            payload = fc.read_json(root / "artifact_hashes.json")

        self.assertEqual(list(payload["files"]), ["keep.txt"])


if __name__ == "__main__":
    unittest.main()
