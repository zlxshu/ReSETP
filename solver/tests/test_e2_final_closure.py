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

    def test_g5_tier_manifests_follow_20260704_scope(self) -> None:
        tier1 = closure.instance_manifest_for_tier("Tier1")
        tier2 = closure.instance_manifest_for_tier("Tier2")
        tier3 = closure.instance_manifest_for_tier("Tier3")

        self.assertEqual(len(tier1), 23)
        self.assertEqual(len(tier2), 29)
        self.assertEqual(len(tier3), 69)
        self.assertTrue({instance for _, instance in closure.G4_INSTANCES}.issubset({row["instance"] for row in tier2}))
        self.assertTrue(all(str(row["instance"]).endswith(("-01", "-02", "-03")) for row in tier3))

    def test_phase_e_carbon_tier_manifests_are_ev_structure_focused(self) -> None:
        tier1 = closure.phase_e_carbon_manifest("Tier1")
        tier2 = closure.phase_e_carbon_manifest("Tier2")
        tier3 = closure.phase_e_carbon_manifest("Tier3")

        self.assertEqual([row["instance"] for row in tier1], ["e2-threeshift-150c-02", "e2-threeshift-200c-02", "e2-threeshift-200c-03"])
        self.assertEqual(len(tier2), 5)
        self.assertEqual(len(tier3), 6)
        self.assertIn("e2-threeshift-100c-02", {row["instance"] for row in tier3})

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

    def test_g4_record_decision_reclassifies_size_dependent_profile(self) -> None:
        old_decision = {
            "verdict": "HALT_G4_SUSPECT",
            "halt_reason": "G4_DIRECTION_RULE_FAILED",
            "nonnegative_gap_instances": 5,
            "pooled_gap_fraction": 0.02085891464891202,
            "documented_exception_count": 2,
            "documented_instance_exceptions": [{"instance": "e2-threeshift-100c-01"}],
        }

        record = closure.g4_record_decision(old_decision, [{"instance": "e2-threeshift-100c-01", "gap_fraction": -0.0217}])

        self.assertEqual(record["verdict"], "HEALTH_PASS_WITH_SIZE_DEPENDENT_PROFILE")
        self.assertEqual(record["original_verdict"], "HALT_G4_SUSPECT")
        self.assertEqual(record["nonnegative_gap_instances"], 5)
        self.assertFalse(record["algorithm_win_loss_claim"])
        self.assertIn("user 2026-07-04 option 2", record["authorization"])

    def test_final_decision_allows_health_pass_after_carbon_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase_a = root / "phase_a_alns_gate"
            phase_b = root / "phase_b_g3_baseline_health"
            phase_c = root / "phase_c_g4_stability"
            phase_e = root / "phase_e_carbon_operator_diagnostic"
            phase_a.mkdir(parents=True)
            phase_b.mkdir(parents=True)
            phase_c.mkdir(parents=True)
            phase_e.mkdir(parents=True)
            (phase_a / "decision.json").write_text(
                '{"verdict":"ALNS_GATE_READY","t3_main_profile":{"base_variant":"alns_e2_throughput","selected_components":["LOCAL_SEARCH"]}}',
                encoding="utf-8",
            )
            (phase_b / "decision.json").write_text(
                '{"verdict":"G3_BASELINE_SET_READY","t3_baseline_set":["GA","LNS"]}',
                encoding="utf-8",
            )
            (phase_c / "decision.json").write_text(
                '{"verdict":"HEALTH_PASS_WITH_SIZE_DEPENDENT_PROFILE","original_verdict":"HALT_G4_SUSPECT","documented_instance_exceptions":[{"instance":"e2-threeshift-100c-01"}]}',
                encoding="utf-8",
            )
            (phase_e / "decision.json").write_text(
                '{"verdict":"CARBON_OPS_WEAK"}',
                encoding="utf-8",
            )

            decision = closure.final_decision(root)

        self.assertEqual(decision["blocked_phase"], "")
        self.assertEqual(decision["phase_verdicts"]["phase_c"], "HEALTH_PASS_WITH_SIZE_DEPENDENT_PROFILE")
        self.assertEqual(decision["phase_c_original_verdict"], "HALT_G4_SUSPECT")
        self.assertEqual(decision["g4_exception_count"], 1)
        self.assertEqual(decision["carbon_diagnostic_verdict"], "CARBON_OPS_WEAK")

    def test_final_decision_blocks_health_pass_until_carbon_diagnostic_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for phase_name, payload in {
                "phase_a_alns_gate": '{"verdict":"ALNS_GATE_READY","t3_main_profile":{"base_variant":"alns_e2_throughput","selected_components":["LOCAL_SEARCH"]}}',
                "phase_b_g3_baseline_health": '{"verdict":"G3_BASELINE_SET_READY","t3_baseline_set":["GA","LNS"]}',
                "phase_c_g4_stability": '{"verdict":"HEALTH_PASS_WITH_SIZE_DEPENDENT_PROFILE"}',
            }.items():
                phase_dir = root / phase_name
                phase_dir.mkdir(parents=True)
                (phase_dir / "decision.json").write_text(payload, encoding="utf-8")

            decision = closure.final_decision(root)

        self.assertEqual(decision["blocked_phase"], "phase_e_carbon")
        self.assertEqual(decision["final_material_verdict"], "CARBON_DIAGNOSTIC_REQUIRED_BEFORE_G5")

    def test_phase_e_carbon_supported_and_dominant_verdicts(self) -> None:
        supported = closure.decide_phase_e_carbon(self._carbon_rows(cost_delta=0.5, carbon_delta=-1.0))
        dominant = closure.decide_phase_e_carbon(self._carbon_rows(cost_delta=-0.1, carbon_delta=-1.0))

        self.assertEqual(supported["verdict"], "CARBON_OPS_INNOVATION_SUPPORTED")
        self.assertEqual(dominant["verdict"], "CARBON_OPS_DOMINANT")
        self.assertEqual(supported["tier1_instance_count"], 3)

    def test_phase_e_carbon_weak_when_cost_premium_exceeds_one_percent(self) -> None:
        decision = closure.decide_phase_e_carbon(self._carbon_rows(cost_delta=1.5, carbon_delta=-1.0))

        self.assertEqual(decision["verdict"], "CARBON_OPS_WEAK")

    def test_phase_e_timing_ledger_hotspots_extracts_seed1_200c03(self) -> None:
        rows = [
            {
                "phase": "E_CARBON_TIER1",
                "instance": "e2-threeshift-200c-03",
                "algorithm": "alns_e2_carbon",
                "seed": 1,
                "operator_counts_json": '{"timing":{"carbon_operator":{"seconds":12.0,"count":3}}}',
            },
            {
                "phase": "E_CARBON_TIER1",
                "instance": "e2-threeshift-200c-03",
                "algorithm": "alns_e2_carbon",
                "seed": 2,
                "operator_counts_json": '{"timing":{"ignored":{"seconds":99.0,"count":1}}}',
            },
        ]

        hotspots = closure.timing_ledger_hotspots(rows)

        self.assertEqual(len(hotspots), 1)
        self.assertEqual(hotspots[0]["label"], "carbon_operator")
        self.assertEqual(hotspots[0]["seconds"], 12.0)

    def test_t3_material_includes_std_and_runtime_fields(self) -> None:
        rows = [
            {
                "category": "threeshift",
                "instance": "e2-threeshift-100c-01",
                "display_algorithm": "ALNS",
                "best_cost": 100.0,
                "actual_evals": 16000,
                "elapsed_seconds": 10.0,
                "evals_per_second": 1600.0,
                "gate_status": "OK",
            },
            {
                "category": "threeshift",
                "instance": "e2-threeshift-100c-01",
                "display_algorithm": "ALNS",
                "best_cost": 104.0,
                "actual_evals": 16000,
                "elapsed_seconds": 20.0,
                "evals_per_second": 800.0,
                "gate_status": "OK",
            },
        ]

        material = closure.t3_table_material(rows, [])

        self.assertAlmostEqual(material[0]["std_best_cost"], 2.8284271247461903)
        self.assertEqual(material[0]["mean_actual_evals"], 16000)
        self.assertEqual(material[0]["mean_elapsed_seconds"], 15.0)

    def test_size_bucket_summary_groups_alns_against_baselines(self) -> None:
        rows = [
            {"category": "threeshift", "instance": "e2-threeshift-100c-01", "algorithm": "t3_main_alns", "display_algorithm": "ALNS", "seed": 1, "best_cost": 90.0, "gate_status": "OK"},
            {"category": "threeshift", "instance": "e2-threeshift-100c-01", "algorithm": "LNS", "display_algorithm": "LNS", "seed": 1, "best_cost": 100.0, "gate_status": "OK"},
        ]

        summary = closure.size_bucket_summary(rows, ["LNS"])

        self.assertEqual(summary[0]["size_bucket"], "100c")
        self.assertEqual(summary[0]["baseline"], "LNS")
        self.assertAlmostEqual(summary[0]["mean_gap_fraction"], 0.1)

    def test_phase_d_identity_clusters_classify_partial_freeze_shapes(self) -> None:
        rows = [
            {"category": "multidepot", "instance": "e2-multidepot-10c-01", "algorithm": "GA", "seed": 1, "gate_status": "OK", "actual_evals": 16000, "eval_budget": 16000, "best_cost": 371.0, "best_signature": "frontier", "native_best_updates": 1},
            {"category": "multidepot", "instance": "e2-multidepot-10c-01", "algorithm": "LNS", "seed": 2, "gate_status": "OK", "actual_evals": 16000, "eval_budget": 16000, "best_cost": 371.0, "best_signature": "frontier", "native_best_updates": 3},
            {"category": "multidepot", "instance": "e2-multidepot-10c-01", "algorithm": "GA", "seed": 2, "gate_status": "OK", "actual_evals": 16000, "eval_budget": 16000, "best_cost": 387.0, "best_signature": "secondary", "native_best_updates": 4},
            {"category": "multidepot", "instance": "e2-multidepot-10c-01", "algorithm": "t3_main_alns", "seed": 1, "gate_status": "OK", "actual_evals": 16000, "eval_budget": 16000, "best_cost": 387.0, "best_signature": "secondary", "native_best_updates": 5},
            {"category": "multidepot", "instance": "e2-multidepot-100c-01", "algorithm": "t3_main_alns", "seed": 1, "gate_status": "OK", "actual_evals": 16000, "eval_budget": 16000, "best_cost": 2467.0, "best_signature": "real-frontier", "native_best_updates": 10},
            {"category": "multidepot", "instance": "e2-multidepot-100c-01", "algorithm": "GA", "seed": 1, "gate_status": "OK", "actual_evals": 16000, "eval_budget": 16000, "best_cost": 2894.0, "best_signature": "shared-stall", "native_best_updates": 2},
            {"category": "multidepot", "instance": "e2-multidepot-100c-01", "algorithm": "PSO", "seed": 3, "gate_status": "OK", "actual_evals": 16000, "eval_budget": 16000, "best_cost": 2894.0, "best_signature": "shared-stall", "native_best_updates": 3},
        ]

        clusters = closure.phase_d_identity_clusters(rows, ["GA", "LNS", "PSO"], expected_seeds=[1, 2, 3])
        classes = {row["best_signature"]: row["identity_cluster_class"] for row in clusters}
        decision = closure.decide_phase_d(rows, [], ["GA", "LNS", "PSO"], tier="Tier1", expected_seeds=[1, 2, 3])

        self.assertEqual(classes["frontier"], "NATURAL_CONVERGENCE")
        self.assertEqual(classes["secondary"], "SECONDARY_ATTRACTOR")
        self.assertEqual(classes["shared-stall"], "SHARED_STALL")
        self.assertEqual(decision["verdict"], "T3_COLLECTION_PARTIAL")
        self.assertEqual(decision["identity_halt_count"], 0)
        self.assertGreater(decision["missing_material_rows"], 0)

    def test_phase_d_identity_cluster_halts_on_zero_native_update(self) -> None:
        rows = [
            {"category": "multidepot", "instance": "e2-multidepot-10c-01", "algorithm": "GA", "seed": 1, "gate_status": "OK", "actual_evals": 16000, "eval_budget": 16000, "best_cost": 371.0, "best_signature": "same", "native_best_updates": 0},
            {"category": "multidepot", "instance": "e2-multidepot-10c-01", "algorithm": "LNS", "seed": 2, "gate_status": "OK", "actual_evals": 16000, "eval_budget": 16000, "best_cost": 371.0, "best_signature": "same", "native_best_updates": 1},
        ]

        decision = closure.decide_phase_d(rows, [], ["GA", "LNS"], tier="Tier1", expected_seeds=[1, 2, 3])

        self.assertEqual(decision["verdict"], "HALT_T3_HOMOGENIZATION")
        self.assertEqual(decision["identity_halt_count"], 1)

    def test_phase_d_identity_cluster_halts_on_full_nonfrontier_expected_matrix(self) -> None:
        rows = [
            {"category": "multidepot", "instance": "e2-multidepot-10c-01", "algorithm": "DIAGNOSTIC_FRONTIER", "seed": 1, "gate_status": "OK", "actual_evals": 16000, "eval_budget": 16000, "best_cost": 90.0, "best_signature": "frontier", "native_best_updates": 1},
        ]
        for algorithm in ("t3_main_alns", "GA"):
            for seed in (1, 2):
                rows.append(
                    {
                        "category": "multidepot",
                        "instance": "e2-multidepot-10c-01",
                        "algorithm": algorithm,
                        "seed": seed,
                        "gate_status": "OK",
                        "actual_evals": 16000,
                        "eval_budget": 16000,
                        "best_cost": 100.0,
                        "best_signature": "full-stall",
                        "native_best_updates": 1,
                    }
                )

        decision = closure.decide_phase_d(rows, [], ["GA"], tier="Tier1", expected_seeds=[1, 2])

        self.assertEqual(decision["verdict"], "HALT_T3_HOMOGENIZATION")
        self.assertEqual(decision["identity_halt_sample"][0]["identity_cluster_reason"], "FULL_EXPECTED_MATRIX_NONFRONTIER_IDENTITY")

    def test_t3_material_includes_identity_cluster_fields_and_shared_stall_source(self) -> None:
        rows = [
            {"category": "multidepot", "instance": "e2-multidepot-100c-01", "algorithm": "t3_main_alns", "display_algorithm": "ALNS", "seed": 1, "gate_status": "OK", "actual_evals": 16000, "eval_budget": 16000, "best_cost": 2467.0, "best_signature": "frontier", "native_best_updates": 10},
            {"category": "multidepot", "instance": "e2-multidepot-100c-01", "algorithm": "GA", "display_algorithm": "GA", "seed": 1, "gate_status": "OK", "actual_evals": 16000, "eval_budget": 16000, "best_cost": 2894.0, "best_signature": "shared-stall", "native_best_updates": 2},
            {"category": "multidepot", "instance": "e2-multidepot-100c-01", "algorithm": "PSO", "display_algorithm": "PSO", "seed": 3, "gate_status": "OK", "actual_evals": 16000, "eval_budget": 16000, "best_cost": 2894.0, "best_signature": "shared-stall", "native_best_updates": 3},
        ]
        clusters = closure.phase_d_identity_clusters(rows, ["GA", "PSO"], expected_seeds=[1, 2, 3])
        material = closure.t3_table_material(closure.annotate_phase_d_identity_clusters(rows, clusters), [])
        ga_row = next(row for row in material if row["display_algorithm"] == "GA")

        self.assertEqual(ga_row["identity_cluster_class"], "SHARED_STALL")
        self.assertEqual(ga_row["identity_cluster_source"], "phase_d_g5_t3_material/identity_clusters.csv;raw_runs.csv")

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
    def _carbon_rows(cost_delta: float, carbon_delta: float) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        tier1 = {"e2-threeshift-150c-02", "e2-threeshift-200c-02", "e2-threeshift-200c-03"}
        for instance in tier1:
            for seed in (1, 2, 3):
                rows.append(
                    {
                        "category": "threeshift",
                        "instance": instance,
                        "algorithm": "alns_e2_carbon_ablation",
                        "seed": seed,
                        "gate_status": "OK",
                        "best_cost": 100.0,
                        "E_total": 1000.0,
                        "cost_carbon": 50.0,
                    }
                )
                rows.append(
                    {
                        "category": "threeshift",
                        "instance": instance,
                        "algorithm": "alns_e2_carbon",
                        "seed": seed,
                        "gate_status": "OK",
                        "best_cost": 100.0 + cost_delta,
                        "E_total": 1000.0 + carbon_delta,
                        "cost_carbon": 50.0 + carbon_delta,
                    }
                )
                rows.append(
                    {
                        "category": "threeshift",
                        "instance": instance,
                        "algorithm": "t3_main_alns",
                        "seed": seed,
                        "gate_status": "OK",
                        "best_cost": 99.0,
                        "E_total": 990.0,
                        "cost_carbon": 49.5,
                    }
                )
        return rows

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
