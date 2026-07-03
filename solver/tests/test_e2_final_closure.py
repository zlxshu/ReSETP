from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from baselines.e2_alns import e2_final_closure as closure
from setp_solver.prices import DEFAULT_PRICES


class E2FinalClosureTest(unittest.TestCase):
    def test_tier1_manifest_has_expected_23_minus_01_instances(self) -> None:
        manifest = closure.instance_manifest_for_tier("Tier1")

        self.assertEqual(len(manifest), 23)
        self.assertTrue(all(str(row["instance"]).endswith("-01") for row in manifest))
        self.assertEqual({row["category"] for row in manifest}, {"multidepot", "threeshift", "vanilla"})

    def test_tier_manifests_expand_by_replicate_staircase(self) -> None:
        tier1 = closure.instance_manifest_for_tier("Tier1")
        tier2 = closure.instance_manifest_for_tier("Tier2")
        tier3 = closure.instance_manifest_for_tier("Tier3")

        self.assertEqual(len(tier1), 23)
        self.assertEqual(len(tier2), 46)
        self.assertEqual(len(tier3), 69)
        self.assertTrue(all(str(row["instance"]).endswith(("-01", "-02")) for row in tier2))
        self.assertTrue(all(str(row["instance"]).endswith(("-01", "-02", "-03")) for row in tier3))

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

    def test_g4_direction_rule_passes_with_no_exceptions(self) -> None:
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

    def test_g4_decision_records_single_large_loss_as_documented_exception(self) -> None:
        rows = self._g4_rows_with_costs([103.0, 90.0, 90.0, 90.0, 90.0, 90.0, 90.0, 101.0, 101.0])
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

        self.assertEqual(decision["verdict"], "G4_PASS_WITH_EXCEPTIONS")
        self.assertEqual(decision["documented_exception_count"], 1)
        self.assertEqual(decision["liveness_suspect_count"], 0)
        self.assertEqual(decision["liveness_diagnostic_count"], 1)
        self.assertEqual(decision["documented_instance_exceptions"][0]["exception_status"], "DOCUMENTED_INSTANCE_EXCEPTION")
        self.assertEqual(decision["documented_instance_exceptions"][0]["instance"], "e2-threeshift-100c-01")

    def test_g4_decision_halts_when_exception_count_reaches_three(self) -> None:
        rows = self._g4_rows_with_costs([103.0, 103.0, 103.0, 90.0, 90.0, 90.0, 90.0, 90.0, 90.0])

        decision = closure.decide_phase_c(rows)

        self.assertEqual(decision["verdict"], "HALT_G4_SUSPECT")
        self.assertEqual(decision["documented_exception_count"], 3)
        self.assertEqual(decision["halt_reason"], "G4_EXCEPTION_COUNT_REACHED_THREE")

    def test_g4_decision_halts_when_majority_rule_fails(self) -> None:
        rows = self._g4_rows_with_costs([98.0, 98.0, 98.0, 98.0, 98.0, 101.0, 101.0, 101.0, 101.0])

        decision = closure.decide_phase_c(rows)

        self.assertEqual(decision["verdict"], "HALT_G4_SUSPECT")
        self.assertEqual(decision["halt_reason"], "G4_DIRECTION_RULE_FAILED")

    def test_g4_decision_halts_on_hard_lns_liveness_failure(self) -> None:
        rows = self._g4_rows_with_costs([99.0] * 9)
        liveness_rows = [
            {
                "scope": "run",
                "algorithm": "LNS",
                "seed": 1,
                "run_id": "lns-no-native-update",
                "verdict": "BASELINE_LIVENESS_FAIL",
                "flags": "NO_NATIVE_BEST_UPDATE",
            }
        ]

        decision = closure.decide_phase_c(rows, liveness_rows)

        self.assertEqual(decision["verdict"], "HALT_G4_SUSPECT")
        self.assertEqual(decision["liveness_suspect_count"], 1)
        self.assertEqual(decision["halt_reason"], "G4_HARD_LIVENESS_SUSPECT")

    def test_alns_route_count_liveness_is_info_not_failure(self) -> None:
        rows = [
            {
                "algorithm": "t3_main_alns",
                "seed": 1,
                "run_id": "alns-fixed-route-count",
                "liveness_verdict": "NOT_BASELINE_ALNS_REFERENCE",
                "liveness_flags": "",
                "native_best_updates": 3,
                "route_count_unique": 1,
            }
        ]

        liveness = closure.liveness_verdicts(rows, ("t3_main_alns",))
        run_row = [row for row in liveness if row["scope"] == "run"][0]
        decision = closure.decide_phase_c([], liveness)

        self.assertEqual(run_row["verdict"], "ALNS_ROUTE_COUNT_INFO")
        self.assertEqual(run_row["flags"], "LOW_ROUTE_COUNT_DIVERSITY_INFO")
        self.assertEqual(decision["liveness_suspect_count"], 0)

    def test_phase_a_prime_selects_route_elimination_when_retest_clears_100c_halt(self) -> None:
        evidence = self._phase_a_prime_evidence()
        comparison = [
            {"variant": "LOCAL_SEARCH_ONLY", "instance": "e2-threeshift-100c-01", "gap_fraction": -0.0217, "worst_seed_gap_fraction": -0.04},
            {"variant": "LOCAL_SEARCH_ONLY", "instance": "POOLED_100C_150C", "gap_fraction": -0.01, "worst_seed_gap_fraction": -0.04},
            {"variant": "ROUTE_ELIMINATION_ONLY", "instance": "e2-threeshift-100c-01", "gap_fraction": 0.002, "worst_seed_gap_fraction": -0.004},
            {"variant": "ROUTE_ELIMINATION_ONLY", "instance": "e2-threeshift-150c-01", "gap_fraction": 0.001, "worst_seed_gap_fraction": -0.003},
            {"variant": "ROUTE_ELIMINATION_ONLY", "instance": "POOLED_100C_150C", "gap_fraction": 0.0015, "worst_seed_gap_fraction": -0.004},
        ]

        decision = closure.decide_phase_a_prime([], evidence, comparison)

        self.assertEqual(decision["verdict"], "ROUTE_ELIMINATION_PROFILE_SELECTED")
        self.assertTrue(decision["halt_lifted_for_100c01"])
        self.assertEqual(decision["selected_t3_main_profile"]["selected_components"], ["ROUTE_ELIMINATION"])

    def test_phase_a_prime_confirms_structural_gap_when_both_single_components_miss_100c(self) -> None:
        evidence = self._phase_a_prime_evidence()
        comparison = [
            {"variant": "LOCAL_SEARCH_ONLY", "instance": "e2-threeshift-100c-01", "gap_fraction": -0.03, "worst_seed_gap_fraction": -0.04},
            {"variant": "LOCAL_SEARCH_ONLY", "instance": "POOLED_100C_150C", "gap_fraction": -0.02, "worst_seed_gap_fraction": -0.04},
            {"variant": "ROUTE_ELIMINATION_ONLY", "instance": "e2-threeshift-100c-01", "gap_fraction": -0.025, "worst_seed_gap_fraction": -0.009},
            {"variant": "ROUTE_ELIMINATION_ONLY", "instance": "e2-threeshift-150c-01", "gap_fraction": 0.003, "worst_seed_gap_fraction": -0.001},
            {"variant": "ROUTE_ELIMINATION_ONLY", "instance": "POOLED_100C_150C", "gap_fraction": -0.011, "worst_seed_gap_fraction": -0.009},
        ]

        decision = closure.decide_phase_a_prime([], evidence, comparison)

        self.assertEqual(decision["verdict"], "STRUCTURAL_GAP_CONFIRMED")
        self.assertTrue(decision["halt_lifted_for_100c01"])
        self.assertEqual(decision["selected_t3_main_profile"]["selected_components"], ["LOCAL_SEARCH"])

    def test_final_decision_allows_phase_c_pass_with_exceptions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase_a = root / "phase_a_alns_gate"
            phase_b = root / "phase_b_g3_baseline_health"
            phase_c = root / "phase_c_g4_stability"
            phase_a.mkdir(parents=True)
            phase_b.mkdir(parents=True)
            phase_c.mkdir(parents=True)
            (phase_a / "decision.json").write_text(
                '{"verdict":"ALNS_GATE_READY","t3_main_profile":{"base_variant":"alns_e2_throughput","selected_components":["LOCAL_SEARCH"]}}',
                encoding="utf-8",
            )
            (phase_b / "decision.json").write_text(
                '{"verdict":"G3_BASELINE_SET_READY","t3_baseline_set":["GA","LNS"]}',
                encoding="utf-8",
            )
            (phase_c / "decision.json").write_text(
                '{"verdict":"G4_PASS_WITH_EXCEPTIONS","documented_instance_exceptions":[{"instance":"e2-threeshift-100c-01"}]}',
                encoding="utf-8",
            )

            decision = closure.final_decision(root)

        self.assertEqual(decision["blocked_phase"], "")
        self.assertEqual(decision["phase_verdicts"]["phase_c"], "G4_PASS_WITH_EXCEPTIONS")
        self.assertEqual(decision["g4_exception_count"], 1)

    def test_t3_material_marks_documented_exception_instances(self) -> None:
        rows = [
            {
                "category": "threeshift",
                "instance": "e2-threeshift-100c-01",
                "display_algorithm": "ALNS",
                "best_cost": 103.0,
                "gate_status": "OK",
            }
        ]
        exceptions = [
            {
                "instance": "e2-threeshift-100c-01",
                "exception_status": "DOCUMENTED_INSTANCE_EXCEPTION",
                "exception_note": "ALNS worse than LNS by more than 2%.",
                "evidence_source": "phase_a_prime_route_elimination_retest/decision.json",
            }
        ]

        material = closure.t3_table_material(rows, exceptions)

        self.assertEqual(material[0]["exception_status"], "DOCUMENTED_INSTANCE_EXCEPTION")
        self.assertIn("route_elimination", material[0]["evidence_source"])

    @staticmethod
    def _phase_a_prime_evidence() -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for variant in ("LOCAL_SEARCH_ONLY", "ROUTE_ELIMINATION_ONLY", "LNS"):
            for instance in ("e2-threeshift-100c-01", "e2-threeshift-150c-01"):
                for seed in (1, 2, 3):
                    rows.append({"variant": variant, "instance": instance, "seed": seed, "gate_status": "OK"})
        return rows

    @staticmethod
    def _g4_rows_with_costs(alns_costs_by_instance: list[float]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for alns_cost, (category, instance) in zip(alns_costs_by_instance, closure.G4_INSTANCES):
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
                        "best_cost": alns_cost,
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
        return rows

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
