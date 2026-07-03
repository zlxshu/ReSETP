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

    def test_g4_decision_halts_on_completed_instance_below_two_percent(self) -> None:
        rows = []
        category, instance = closure.G4_INSTANCES[0]
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
                    "best_cost": 103.0,
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

        self.assertEqual(decision["verdict"], "HALT_G4_SUSPECT")
        self.assertEqual(decision["hard_direction_violation_count"], 1)

    def test_g4_decision_halts_on_lns_liveness_failure(self) -> None:
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
                        "best_cost": 99.0,
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
        liveness_rows = [
            {
                "scope": "run",
                "algorithm": "LNS",
                "seed": 1,
                "run_id": "lns-low-route-diversity",
                "verdict": "BASELINE_LIVENESS_FAIL",
                "flags": "LOW_ROUTE_COUNT_DIVERSITY",
            }
        ]

        decision = closure.decide_phase_c(rows, liveness_rows)

        self.assertEqual(decision["verdict"], "HALT_G4_SUSPECT")
        self.assertEqual(decision["liveness_suspect_count"], 1)

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

    def test_carbon_diagnostic_under_eval_is_nonblocking_partial(self) -> None:
        rows = [
            {
                "phase": "A1_CARBON_WALLCLOCK_DIAGNOSTIC",
                "scenario_type": "formal_goeke80",
                "run_id": "carbon-wallclock-partial",
                "gate_status": "OK",
                "failure_reason": "Equal-wallclock diagnostic stopped at 5575/16000 evaluations.",
                "actual_evals": 5575,
                "eval_budget": 16000,
                "eval_closure_required": False,
            },
        ]

        blockers = closure.incomplete_rows(rows)

        self.assertEqual(blockers, [])

    def test_phase_a_decision_locks_throughput_and_ignores_carbon_gate_rows(self) -> None:
        rows = [
            {
                "phase": "A1_CARBON_GATE",
                "scenario_type": "formal_goeke80",
                "run_id": "superseded-carbon-under-eval",
                "algorithm": "alns_e2_carbon",
                "seed": 1,
                "gate_status": "HALT_RUNTIME_UNDER_EVAL",
                "actual_evals": 5575,
                "eval_budget": 16000,
            }
        ]
        for seed in (1, 2, 3):
            rows.append(
                {
                    "phase": "A2_COMPONENT_ABLATION",
                    "scenario_type": "formal_goeke80",
                    "run_id": f"base-{seed}",
                    "algorithm": "alns_e2_throughput",
                    "components": "",
                    "seed": seed,
                    "gate_status": "OK",
                    "actual_evals": 16000,
                    "eval_budget": 16000,
                    "best_cost": 100.0,
                }
            )
            rows.append(
                {
                    "phase": "A2_COMPONENT_ABLATION",
                    "scenario_type": "formal_goeke80",
                    "run_id": f"local-search-{seed}",
                    "algorithm": "alns_component_LOCAL_SEARCH",
                    "components": "LOCAL_SEARCH",
                    "seed": seed,
                    "gate_status": "OK",
                    "actual_evals": 16000,
                    "eval_budget": 16000,
                    "best_cost": 99.0,
                }
            )

        decision = closure.decide_phase_a(rows)

        self.assertEqual(decision["verdict"], "ALNS_GATE_READY")
        self.assertEqual(decision["t3_main_variant"], "alns_e2_throughput")
        self.assertEqual(decision["t3_main_profile"]["base_variant"], "alns_e2_throughput")
        self.assertEqual(decision["selected_components"], ["LOCAL_SEARCH"])

    def test_phase_a_schedules_progressive_component_stack_retest(self) -> None:
        rows = []
        for seed in (1, 2, 3):
            rows.extend(
                [
                    {
                        "phase": "A2_COMPONENT_ABLATION",
                        "algorithm": "alns_e2_throughput",
                        "components": "",
                        "seed": seed,
                        "gate_status": "OK",
                        "actual_evals": 16000,
                        "eval_budget": 16000,
                        "best_cost": 100.0,
                    },
                    {
                        "phase": "A2_COMPONENT_ABLATION",
                        "algorithm": "alns_component_LOCAL_SEARCH",
                        "components": "LOCAL_SEARCH",
                        "seed": seed,
                        "gate_status": "OK",
                        "actual_evals": 16000,
                        "eval_budget": 16000,
                        "best_cost": 99.0,
                    },
                    {
                        "phase": "A2_COMPONENT_ABLATION",
                        "algorithm": "alns_component_ROUTE_ELIMINATION",
                        "components": "ROUTE_ELIMINATION",
                        "seed": seed,
                        "gate_status": "OK",
                        "actual_evals": 16000,
                        "eval_budget": 16000,
                        "best_cost": 98.0,
                    },
                ]
            )

        decision = closure.decide_phase_a(rows)

        self.assertEqual(decision["stack_retest_tasks"], ["ROUTE_ELIMINATION", "LOCAL_SEARCH"])

    def test_final_decision_continues_after_throughput_phase_a_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase_a = root / "phase_a_alns_gate"
            phase_a.mkdir(parents=True)
            (phase_a / "decision.json").write_text(
                '{"verdict":"ALNS_GATE_READY","t3_main_profile":{"base_variant":"alns_e2_throughput","selected_components":[]}}',
                encoding="utf-8",
            )

            decision = closure.final_decision(root)

        self.assertEqual(decision["blocked_phase"], "phase_b")
        self.assertEqual(decision["final_material_verdict"], "MISSING")
        self.assertEqual(decision["t3_main_profile"]["base_variant"], "alns_e2_throughput")


if __name__ == "__main__":
    unittest.main()
