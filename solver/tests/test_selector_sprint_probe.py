from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from setp_solver.search.winner_operators import (
    BALANCED_SELECTOR_FLAG,
    EPS_DECAY_SELECTOR_FLAG,
    SOFTMAX_SELECTOR_FLAG,
    THOMPSON_SELECTOR_FLAG,
)


class SelectorSprintProbeTests(unittest.TestCase):
    def test_4000_stage_single_instance_seed_generates_six_profiles(self) -> None:
        from baselines.e2_alns import selector_sprint_probe as probe

        hard_subset = [{"category": "vanilla", "instance": "e2-vanilla-10c-01"}]
        with tempfile.TemporaryDirectory() as tmp:
            tasks = probe.build_stage_tasks(
                Path(tmp),
                hard_subset,
                seeds=[1],
                budget=4000,
                selector_profiles=list(probe.SELECTOR_PROFILES),
            )

        self.assertEqual(
            [task["profile"] for task in tasks],
            [
                "A0_MAIN_LOCAL_SEARCH",
                "A4_BALANCED_SELECTOR_LOCAL_SEARCH",
                "A5_EPS_DECAY_SELECTOR_LOCAL_SEARCH",
                "A6_THOMPSON_SELECTOR_LOCAL_SEARCH",
                "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH",
                "LNS_REFERENCE",
            ],
        )
        self.assertTrue(all(task["eval_budget"] == 4000 for task in tasks))

    def test_next_stage_only_generates_survivor_selector_and_same_budget_lns(self) -> None:
        from baselines.e2_alns import selector_sprint_probe as probe

        hard_subset = [{"category": "vanilla", "instance": "e2-vanilla-10c-01"}]
        with tempfile.TemporaryDirectory() as tmp:
            tasks = probe.build_stage_tasks(
                Path(tmp),
                hard_subset,
                seeds=[2],
                budget=8000,
                selector_profiles=["A5_EPS_DECAY_SELECTOR_LOCAL_SEARCH"],
            )

        self.assertEqual(
            [task["profile"] for task in tasks],
            ["A0_MAIN_LOCAL_SEARCH", "A5_EPS_DECAY_SELECTOR_LOCAL_SEARCH", "LNS_REFERENCE"],
        )
        self.assertTrue(all(task["eval_budget"] == 8000 for task in tasks))
        self.assertEqual(tasks[-1]["algorithm"], "LNS")

    def test_profile_flags_select_exactly_one_selector_variant(self) -> None:
        from baselines.e2_alns import selector_sprint_probe as probe

        a5 = probe.profile_flags("A5_EPS_DECAY_SELECTOR_LOCAL_SEARCH")
        a6 = probe.profile_flags("A6_THOMPSON_SELECTOR_LOCAL_SEARCH")
        a7 = probe.profile_flags("A7_SOFTMAX_SELECTOR_LOCAL_SEARCH")

        self.assertEqual(a5[EPS_DECAY_SELECTOR_FLAG], "1")
        self.assertEqual(a5[BALANCED_SELECTOR_FLAG], "0")
        self.assertEqual(a6[THOMPSON_SELECTOR_FLAG], "1")
        self.assertEqual(a6[EPS_DECAY_SELECTOR_FLAG], "0")
        self.assertEqual(a7[SOFTMAX_SELECTOR_FLAG], "1")
        self.assertEqual(a7[THOMPSON_SELECTOR_FLAG], "0")
        self.assertEqual(a7["SETP_ALNS_CRUSH_LOCAL_SEARCH"], "1")

    def test_sprint_verdict_distinguishes_budget_depth(self) -> None:
        from baselines.e2_alns import selector_sprint_probe as probe

        self.assertEqual(probe.sprint_verdict([]), "SELECTOR_SPRINT_NO_BRANCH_SUPPORTED")
        self.assertEqual(
            probe.sprint_verdict([{"budget": 4000, "profile": "A5", "pass_gate": True}]),
            "SELECTOR_SPRINT_4000_ONLY",
        )
        self.assertEqual(
            probe.sprint_verdict(
                [
                    {"budget": 4000, "profile": "A5", "pass_gate": True},
                    {"budget": 8000, "profile": "A5", "pass_gate": True},
                ]
            ),
            "SELECTOR_SPRINT_8000_SUPPORTED",
        )
        self.assertEqual(
            probe.sprint_verdict(
                [
                    {"budget": 4000, "profile": "A5", "pass_gate": True},
                    {"budget": 8000, "profile": "A5", "pass_gate": True},
                    {"budget": 16000, "profile": "A5", "pass_gate": True},
                ]
            ),
            "SELECTOR_SPRINT_16000_SUPPORTED",
        )
        self.assertEqual(
            probe.sprint_verdict([{"budget": 4000, "profile": "A5", "pass_gate": False}], halt=True),
            "HALT_SELECTOR_SPRINT",
        )

    def test_artifact_hash_excludes_sidecars_caches_and_tasks(self) -> None:
        from baselines.e2_alns import selector_sprint_probe as probe
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

            probe.write_hashes(root)
            payload = fc.read_json(root / "artifact_hashes.json")

        self.assertEqual(list(payload["files"]), ["keep.txt"])


if __name__ == "__main__":
    unittest.main()
