from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class GlobalRepackFleetChargeProbeTests(unittest.TestCase):
    def test_4000_stage_single_instance_seed_generates_five_profiles(self) -> None:
        from baselines.e2_alns import global_repack_fleet_charge_probe as probe

        hard_subset = [{"category": "vanilla", "instance": "e2-vanilla-10c-01"}]
        with tempfile.TemporaryDirectory() as tmp:
            tasks = probe.build_stage_tasks(
                Path(tmp),
                hard_subset,
                seeds=[1],
                budget=4000,
                repair_profiles=list(probe.REPAIR_PROFILES),
            )

        self.assertEqual(
            [task["profile"] for task in tasks],
            [
                "A0_MAIN_LOCAL_SEARCH",
                "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH",
                "A11_GLOBAL_ORDER_REPACK",
                "A12_FLEET_CHARGE_COREPAIR",
                "LNS_REFERENCE",
            ],
        )

    def test_profile_flags_select_exactly_one_structural_repair(self) -> None:
        from baselines.e2_alns import global_repack_fleet_charge_probe as probe
        from setp_solver.search.winner_operators import (
            FLEET_CHARGE_COREPAIR_FLAG,
            GLOBAL_ORDER_REPACK_FLAG,
            SOFTMAX_SELECTOR_FLAG,
        )

        a11 = probe.profile_flags("A11_GLOBAL_ORDER_REPACK")
        a12 = probe.profile_flags("A12_FLEET_CHARGE_COREPAIR")

        self.assertEqual(a11[GLOBAL_ORDER_REPACK_FLAG], "1")
        self.assertEqual(a11[FLEET_CHARGE_COREPAIR_FLAG], "0")
        self.assertEqual(a12[FLEET_CHARGE_COREPAIR_FLAG], "1")
        self.assertEqual(a12[GLOBAL_ORDER_REPACK_FLAG], "0")
        self.assertEqual(a11[SOFTMAX_SELECTOR_FLAG], "1")
        self.assertEqual(a12["SETP_ALNS_CRUSH_LOCAL_SEARCH"], "1")

    def test_probe_verdicts_distinguish_budget_depth(self) -> None:
        from baselines.e2_alns import global_repack_fleet_charge_probe as probe

        self.assertEqual(probe.probe_verdict([]), "GLOBAL_REPACK_FLEET_CHARGE_NO_BRANCH_SUPPORTED")
        self.assertEqual(
            probe.probe_verdict([{"budget": 4000, "pass_gate": True}]),
            "GLOBAL_REPACK_FLEET_CHARGE_4000_ONLY",
        )
        self.assertEqual(
            probe.probe_verdict([{"budget": 8000, "pass_gate": True}]),
            "GLOBAL_REPACK_FLEET_CHARGE_8000_SUPPORTED",
        )
        self.assertEqual(
            probe.probe_verdict([{"budget": 16000, "pass_gate": True}]),
            "GLOBAL_REPACK_FLEET_CHARGE_16000_SUPPORTED",
        )
        self.assertEqual(probe.probe_verdict([], halt=True), "HALT_GLOBAL_REPACK_FLEET_CHARGE")

    def test_artifact_hash_excludes_sidecars_caches_and_tasks(self) -> None:
        from baselines.e2_alns import e2_final_closure as fc
        from baselines.e2_alns import global_repack_fleet_charge_probe as probe

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
