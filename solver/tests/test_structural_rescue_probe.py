from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class StructuralRescueProbeTests(unittest.TestCase):
    def test_4000_stage_single_instance_seed_generates_six_profiles(self) -> None:
        from baselines.e2_alns import structural_rescue_probe as probe

        hard_subset = [{"category": "vanilla", "instance": "e2-vanilla-10c-01"}]
        with tempfile.TemporaryDirectory() as tmp:
            tasks = probe.build_stage_tasks(
                Path(tmp),
                hard_subset,
                seeds=[1],
                budget=4000,
                structural_profiles=list(probe.STRUCTURAL_PROFILES),
            )

        self.assertEqual(
            [task["profile"] for task in tasks],
            [
                "A0_MAIN_LOCAL_SEARCH",
                "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH",
                "A8_ROUTE_POOL_RECOMBINATION",
                "A9_RVND_SWAPSTAR_LOCAL_SEARCH",
                "A10_ELITE_ARCHIVE_RESTART",
                "LNS_REFERENCE",
            ],
        )

    def test_next_stage_only_generates_survivor_structural_profiles(self) -> None:
        from baselines.e2_alns import structural_rescue_probe as probe

        hard_subset = [{"category": "vanilla", "instance": "e2-vanilla-10c-01"}]
        with tempfile.TemporaryDirectory() as tmp:
            tasks = probe.build_stage_tasks(
                Path(tmp),
                hard_subset,
                seeds=[2],
                budget=8000,
                structural_profiles=["A8_ROUTE_POOL_RECOMBINATION"],
            )

        self.assertEqual(
            [task["profile"] for task in tasks],
            ["A0_MAIN_LOCAL_SEARCH", "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH", "A8_ROUTE_POOL_RECOMBINATION", "LNS_REFERENCE"],
        )
        self.assertTrue(all(task["eval_budget"] == 8000 for task in tasks))

    def test_structural_verdicts_distinguish_depth(self) -> None:
        from baselines.e2_alns import structural_rescue_probe as probe

        self.assertEqual(probe.structural_verdict([]), "STRUCTURAL_RESCUE_ALL_FAILED")
        self.assertEqual(probe.structural_verdict([{"budget": 4000, "pass_gate": False}]), "STRUCTURAL_RESCUE_ALL_FAILED")
        self.assertEqual(probe.structural_verdict([{"budget": 8000, "pass_gate": True}]), "STRUCTURAL_RESCUE_8000_SUPPORTED")
        self.assertEqual(probe.structural_verdict([{"budget": 16000, "pass_gate": True}]), "STRUCTURAL_RESCUE_16000_SUPPORTED")
        self.assertEqual(probe.structural_verdict([], halt=True), "HALT_STRUCTURAL_RESCUE")

    def test_artifact_hash_excludes_sidecars_caches_and_tasks(self) -> None:
        from baselines.e2_alns import e2_final_closure as fc
        from baselines.e2_alns import structural_rescue_probe as probe

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
