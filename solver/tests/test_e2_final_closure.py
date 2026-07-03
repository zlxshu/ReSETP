from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from baselines.e2_alns import e2_final_closure as closure
from setp_solver.prices import DEFAULT_PRICES


class E2FinalClosureTest(unittest.TestCase):
    def test_tier1_manifest_has_expected_23_minus_01_instances(self) -> None:
        manifest = closure.tier1_instance_manifest()

        self.assertEqual(len(manifest), 23)
        self.assertTrue(all(str(row["instance"]).endswith("-01") for row in manifest))
        self.assertEqual({row["category"] for row in manifest}, {"multidepot", "threeshift", "vanilla"})

    def test_formal_phases_use_default_prices_and_diagnostic_is_in_memory_only(self) -> None:
        formal = closure.prices_for_scenario("formal_goeke80")
        diagnostic = closure.prices_for_scenario("diagnostic_280_override")

        self.assertIs(formal, DEFAULT_PRICES)
        self.assertIsNone(closure.price_override_payload("formal_goeke80"))
        self.assertEqual(float(diagnostic.B_battery_kwh), 280.0)
        self.assertEqual(float(diagnostic.carbon_price), 0.05034)
        self.assertEqual(float(DEFAULT_PRICES.B_battery_kwh), 80.0)

    def test_component_profile_flags_open_only_requested_switches(self) -> None:
        flags, carbon_bias = closure.flags_for_profile(
            "alns_e2_throughput",
            ["LOCAL_SEARCH", "ROUTE_ELIMINATION", "RRT_TRUE_ACCEPTANCE"],
        )

        self.assertEqual(carbon_bias, 0.0)
        self.assertEqual(flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_TRUE_ACCEPTANCE"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SA_ACCEPTANCE"], "0")

    def test_carbon_profile_flags_keep_carbon_operator_bias_explicit(self) -> None:
        flags, carbon_bias = closure.flags_for_profile("alns_e2_carbon", [])

        self.assertEqual(carbon_bias, 1.0)
        self.assertEqual(flags["SETP_ALNS_CARBON_OPERATORS"], "1")
        self.assertEqual(flags["SETP_ALNS_CARBON_OPERATOR_BIAS"], "1.0")

    def test_g4_direction_rule_requires_majority_pooled_and_no_big_single_loss(self) -> None:
        rows = []
        for idx, (category, instance) in enumerate(closure.G4_INSTANCES):
            for seed in (1, 2, 3):
                rows.append(
                    {
                        "category": category,
                        "instance": instance,
                        "algorithm": "t3_main_alns",
                        "seed": seed,
                        "gate_status": "OK",
                        "actual_evals": 16000,
                        "eval_budget": 16000,
                        "best_cost": 98.0 if idx < 6 else 101.0,
                    }
                )
                rows.append(
                    {
                        "category": category,
                        "instance": instance,
                        "algorithm": "LNS",
                        "seed": seed,
                        "gate_status": "OK",
                        "actual_evals": 16000,
                        "eval_budget": 16000,
                        "best_cost": 100.0,
                    }
                )

        decision = closure.decide_phase_c(rows)

        self.assertEqual(decision["verdict"], "G4_STABILITY_PASS")
        self.assertEqual(decision["nonnegative_gap_instances"], 6)

    def test_artifact_hashes_exclude_appledouble_caches_and_hash_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "keep.txt").write_text("ok", encoding="utf-8")
            (root / "._bad").write_text("bad", encoding="utf-8")
            (root / "artifact_hashes.json").write_text("old", encoding="utf-8")
            cache = root / "__pycache__"
            cache.mkdir()
            (cache / "x.pyc").write_bytes(b"x")

            hashes = closure.artifact_hashes(root)

        paths = [row["path"] for row in hashes["files"]]
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].endswith("keep.txt"))

    def test_phase_a_formal_under_eval_blocks_before_diagnostic(self) -> None:
        rows = [
            {
                "phase": "A1_CARBON_GATE",
                "scenario_type": "formal_goeke80",
                "run_id": "formal-under-eval",
                "gate_status": "HALT_RUNTIME_UNDER_EVAL",
                "failure_reason": "Stopped at 5575/16000 evaluations.",
                "actual_evals": 5575,
                "eval_budget": 16000,
            },
            {
                "phase": "A1_CARBON_GATE",
                "scenario_type": "diagnostic_280_override",
                "run_id": "diagnostic-under-eval",
                "gate_status": "HALT_RUNTIME_UNDER_EVAL",
                "failure_reason": "Diagnostic arm should not define the formal blocker.",
                "actual_evals": 5575,
                "eval_budget": 16000,
            },
        ]

        blockers = closure.phase_a_formal_blockers(rows)

        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]["run_id"], "formal-under-eval")

    def test_final_decision_surfaces_phase_a_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase_a = root / "phase_a_alns_gate"
            phase_a.mkdir(parents=True)
            (phase_a / "decision.json").write_text('{"verdict":"ALNS_GATE_BLOCKED"}', encoding="utf-8")

            decision = closure.final_decision(root)

        self.assertEqual(decision["blocked_phase"], "phase_a")
        self.assertEqual(decision["final_material_verdict"], "ALNS_GATE_BLOCKED")


if __name__ == "__main__":
    unittest.main()
