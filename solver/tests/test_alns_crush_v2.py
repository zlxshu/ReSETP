from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from setp_solver.search.alns_crush_v2 import (
    _fair_sa_reference,
    _wilcoxon_vs_fair_sa,
    fair_sa_gap,
    sa_config_diff_from_manifests,
)
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.winner_operators import (
    WinnerKernelConfig,
    _make_winner_acceptance_criterion,
    e2_alns_scan_bridge_flags,
    e2_alns_sa_acceptance_flags,
    e2_alns_throughput_flags,
    e2_alns_variant_flags,
    operator_base_id,
    run_e2_alns_sa_acceptance,
    run_e2_alns_scan_bridge,
    scan_all_cv_solution,
    winner_operator_module,
    winner_variant_flags,
    write_winner_manifest,
)


class AlnsCrushV2Tests(unittest.TestCase):
    def test_alns_crush_v2_sa_config_diff_detects_budget_mismatch(self) -> None:
        diff = sa_config_diff_from_manifests(
            {"eval_budget": 16_000, "max_runtime_seconds": 900},
            {"eval_budget": 4_000, "max_runtime_seconds": 600},
        )

        self.assertTrue(diff["phase2_sa_weaker_by_config"])
        self.assertEqual(diff["eval_budget_delta"], -12_000)
        self.assertEqual(diff["max_runtime_delta_seconds"], -300.0)

    def test_winner_operator_manifest_has_stable_public_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_winner_manifest(tmp)
            manifest = json.loads(Path(path).read_text(encoding="utf-8"))

        self.assertEqual(manifest["winner_operator_module"], winner_operator_module)
        self.assertEqual(manifest["operator_base_id"], operator_base_id)
        self.assertEqual(
            manifest["public_api"],
            [
                "WinnerKernelConfig",
                "WinnerOperatorAction",
                "WinnerOperatorSet",
                "apply_winner_action",
                "decode_winner_action",
                "e2_alns_sa_acceptance_flags",
                "e2_alns_scan_bridge_flags",
                "e2_alns_throughput_flags",
                "e2_alns_variant_flags",
                "run_e2_alns_sa_acceptance",
                "run_e2_alns_scan_bridge",
                "run_e2_alns_carbon",
                "run_e2_alns_throughput",
                "run_staged_alns_lns_hybrid",
                "run_staged_carbon_aware_hybrid",
                "run_staged_carbon_schedule_pair",
                "run_tvci_alns",
                "run_tvci_carbon_schedule_pair",
                "scan_all_cv_solution",
                "winner_variant_flags",
                "run_e2_alns_final",
                "run_winner_kernel",
                "run_winner_kernel_plus_route_elimination",
                "write_winner_manifest",
            ],
        )
        self.assertEqual(manifest["e2_alns_flags"], e2_alns_variant_flags())
        self.assertEqual(manifest["e2_alns_scan_bridge_flags"], e2_alns_scan_bridge_flags())
        self.assertEqual(manifest["e2_alns_sa_acceptance_flags"]["autofit"], e2_alns_sa_acceptance_flags(mode="autofit"))
        self.assertEqual(manifest["e2_alns_sa_acceptance_flags"]["lns_cooling"], e2_alns_sa_acceptance_flags(mode="lns_cooling"))
        self.assertEqual(manifest["e2_alns_throughput_flags"], e2_alns_throughput_flags())
        self.assertIn("Does not change cost.py/check.py/evaluation.py model semantics.", manifest["semantic_guards"])

    def test_winner_variant_flags_disable_harmful_prompt1_addons(self) -> None:
        default_flags = winner_variant_flags()
        route_elim_flags = winner_variant_flags(include_route_elimination=True)

        self.assertEqual(default_flags["SETP_ALNS_CRUSH_TRUE_REPAIR"], "0")
        self.assertEqual(default_flags["SETP_ALNS_CRUSH_TRUE_ACCEPTANCE"], "0")
        self.assertEqual(default_flags["SETP_ALNS_CRUSH_SA_ACCEPTANCE"], "0")
        self.assertEqual(default_flags["SETP_ALNS_CRUSH_SA_MODE"], "off")
        self.assertEqual(default_flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"], "0")
        self.assertEqual(default_flags["SETP_ALNS_CRUSH_ADAPTIVE_Q"], "0")
        self.assertEqual(default_flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"], "0")
        self.assertEqual(default_flags["SETP_ALNS_CRUSH_SCAN_RESTART"], "0")
        self.assertEqual(default_flags["SETP_ALNS_CRUSH_SCAN_REBUILD"], "0")
        self.assertEqual(default_flags["SETP_ALNS_CRUSH_ROUTE_COST_CACHE"], "0")
        self.assertEqual(default_flags["SETP_ALNS_CRUSH_REPAIR_STRUCTURE_CACHE"], "0")
        self.assertEqual(default_flags["SETP_ALNS_CRUSH_TIMING_LEDGER"], "0")
        self.assertEqual(route_elim_flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"], "1")
        self.assertEqual(WinnerKernelConfig().include_route_elimination, False)

    def test_e2_alns_variant_flags_are_explicit_not_legacy_default(self) -> None:
        flags = e2_alns_variant_flags()

        self.assertEqual(flags["SETP_ALNS_CRUSH_TRUE_REPAIR"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_TRUE_ACCEPTANCE"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SA_ACCEPTANCE"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SA_MODE"], "off")
        self.assertEqual(flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_ADAPTIVE_Q"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SCAN_RESTART"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SCAN_REBUILD"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_ROUTE_COST_CACHE"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_REPAIR_STRUCTURE_CACHE"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_TIMING_LEDGER"], "0")
        self.assertNotEqual(flags, winner_variant_flags())

    def test_e2_scan_bridge_flags_are_explicit_experimental_flags(self) -> None:
        flags = e2_alns_scan_bridge_flags()

        self.assertEqual(flags["SETP_ALNS_CRUSH_TRUE_REPAIR"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_ADAPTIVE_Q"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SCAN_RESTART"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SCAN_REBUILD"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_TRUE_ACCEPTANCE"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SA_ACCEPTANCE"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SA_MODE"], "off")
        self.assertEqual(flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_ROUTE_COST_CACHE"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_REPAIR_STRUCTURE_CACHE"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_TIMING_LEDGER"], "0")

    def test_e2_sa_acceptance_flags_are_explicit_experimental_flags(self) -> None:
        flags = e2_alns_sa_acceptance_flags(mode="autofit")

        self.assertEqual(flags["SETP_ALNS_CRUSH_TRUE_REPAIR"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_ADAPTIVE_Q"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SCAN_RESTART"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SCAN_REBUILD"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_TRUE_ACCEPTANCE"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SA_ACCEPTANCE"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SA_MODE"], "autofit")
        self.assertEqual(e2_alns_sa_acceptance_flags(mode="lns_cooling")["SETP_ALNS_CRUSH_SA_MODE"], "lns_cooling")

    def test_e2_throughput_flags_are_explicit_experimental_flags(self) -> None:
        flags = e2_alns_throughput_flags()

        self.assertEqual(flags["SETP_ALNS_CRUSH_TRUE_REPAIR"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_ADAPTIVE_Q"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SCAN_RESTART"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SCAN_REBUILD"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SA_ACCEPTANCE"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_SA_MODE"], "lns_cooling")
        self.assertEqual(flags["SETP_ALNS_CRUSH_ROUTE_COST_CACHE"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_REPAIR_STRUCTURE_CACHE"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_TIMING_LEDGER"], "1")

    def test_winner_acceptance_builder_keeps_default_hillclimbing_and_sa_opt_in(self) -> None:
        root = Path(__file__).resolve().parents[2]
        bundle = load_search_bundle(root / "models/data_bundle/generated_instances/e2_benchmark/vanilla/e2-vanilla-10c-01")
        from setp_solver.search.construction import build_initial_solution
        from setp_solver.search.evaluation import EvaluationContext, score_reference
        from setp_solver.search.alns_wouda import AlnsState

        solution = build_initial_solution(bundle.instance, bundle.carbon_profile)
        context = EvaluationContext(bundle.instance, bundle.carbon_profile)
        state = AlnsState(solution, context, objective_value=score_reference(solution, context))

        default_acceptance = _make_winner_acceptance_criterion(state, config=WinnerKernelConfig(eval_budget=100), flags=winner_variant_flags())
        sa_acceptance = _make_winner_acceptance_criterion(
            state,
            config=WinnerKernelConfig(eval_budget=100, max_runtime_seconds=10.0),
            flags=e2_alns_sa_acceptance_flags(mode="autofit"),
        )

        self.assertEqual(type(default_acceptance).__name__, "HillClimbing")
        self.assertEqual(type(sa_acceptance).__name__, "SimulatedAnnealing")

    def test_scan_construction_returns_zero_violation_all_cv_solution(self) -> None:
        root = Path(__file__).resolve().parents[2]
        bundle = load_search_bundle(root / "models/data_bundle/generated_instances/e2_benchmark/vanilla/e2-vanilla-10c-01")

        solution = scan_all_cv_solution(bundle.instance, offset=0)

        self.assertTrue(solution.routes)
        self.assertTrue(all(route.vehicle_type.lower() == "cv" for route in solution.routes))
        self.assertEqual(check_solution(solution, bundle.instance, DEFAULT_PRICES), [])

    def test_e2_scan_bridge_same_seed_small_budget_is_deterministic(self) -> None:
        root = Path(__file__).resolve().parents[2]
        bundle_dir = root / "models/data_bundle/generated_instances/e2_benchmark/vanilla/e2-vanilla-10c-01"
        config = WinnerKernelConfig(seed=7, eval_budget=16, max_runtime_seconds=120.0)

        first = run_e2_alns_scan_bridge(bundle_dir, config=config)
        second = run_e2_alns_scan_bridge(bundle_dir, config=config)

        self.assertEqual(first["violation_count"], 0)
        self.assertEqual(second["violation_count"], 0)
        self.assertAlmostEqual(first["best_cost"], second["best_cost"])
        self.assertEqual(first["evaluations"], second["evaluations"])

    def test_e2_sa_acceptance_same_seed_small_budget_is_deterministic(self) -> None:
        root = Path(__file__).resolve().parents[2]
        bundle_dir = root / "models/data_bundle/generated_instances/e2_benchmark/vanilla/e2-vanilla-10c-01"
        config = WinnerKernelConfig(seed=7, eval_budget=16, max_runtime_seconds=120.0)

        first = run_e2_alns_sa_acceptance(bundle_dir, config=config, mode="autofit")
        second = run_e2_alns_sa_acceptance(bundle_dir, config=config, mode="autofit")

        self.assertEqual(first["violation_count"], 0)
        self.assertEqual(second["violation_count"], 0)
        self.assertAlmostEqual(first["best_cost"], second["best_cost"])
        self.assertEqual(first["evaluations"], second["evaluations"])
        self.assertTrue(first["history"])

    def test_v2_summary_uses_fair_sa_not_phase2_sa_denominator(self) -> None:
        fair_summary = [
            {
                "variant": "fair_sa",
                "instance": "toy",
                "algorithm": "scikit-opt-SA",
                "n": 2,
                "mean_total_cost": 100.0,
                "median_total_cost": 100.0,
                "best_total_cost": 90.0,
                "std_total_cost": 14.1421356237,
                "mean_route_count": 1.0,
                "median_route_count": 1.0,
                "zero_violation_count": 2,
            }
        ]
        fair_rows = [
            {"instance": "toy", "algorithm": "scikit-opt-SA", "seed": 1, "total_cost": 90.0},
            {"instance": "toy", "algorithm": "scikit-opt-SA", "seed": 2, "total_cost": 110.0},
        ]
        reference = _fair_sa_reference(fair_summary, fair_rows, eval_budget=16_000, max_runtime_seconds=900.0)
        candidate_rows = [
            {"variant": "winner_kernel_only", "instance": "toy", "algorithm": "ALNS-Wouda", "seed": 1, "total_cost": 89.0},
            {"variant": "winner_kernel_only", "instance": "toy", "algorithm": "ALNS-Wouda", "seed": 2, "total_cost": 109.0},
        ]

        wilcoxon = _wilcoxon_vs_fair_sa(candidate_rows, reference)[0]
        gap = fair_sa_gap(candidate_rows[0], reference)

        self.assertEqual(wilcoxon["baseline"], "fair_scikit-opt-SA_paired_seed")
        self.assertEqual(wilcoxon["wins_alg_lower"], 2)
        self.assertEqual(wilcoxon["n_pairs"], 2)
        self.assertAlmostEqual(wilcoxon["mean_diff_alg_minus_fair_sa"], -1.0)
        self.assertAlmostEqual(gap, -11.0)


if __name__ == "__main__":
    unittest.main()
