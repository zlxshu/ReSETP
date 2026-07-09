from __future__ import annotations

from dataclasses import replace
import math
import os
import random
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import setp_solver.search.candidates as candidate_ops
import setp_solver.search.winner_operators as winner_ops
from setp_solver.algorithms.resetp_alns.kernel import winner as winner_impl
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.e2_alns_throughput import _task, _timeout_row, _write_checkpoint, run_smoke
from setp_solver.search.repair_scoring import route_model_cost
from setp_solver.search.evaluation import EvaluationContext
from setp_solver.search.winner_operators import (
    WinnerKernelConfig,
    run_e2_alns_carbon,
    e2_alns_throughput_flags,
    run_e2_alns_throughput,
    winner_variant_flags,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SMALL_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/e2_benchmark/vanilla/e2-vanilla-10c-01"
VERIFY_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/verify_20251113"


class E2AlnsThroughputTest(unittest.TestCase):
    def test_legacy_flags_keep_throughput_diagnostics_off(self) -> None:
        flags = winner_variant_flags()

        self.assertEqual(flags["SETP_ALNS_CRUSH_ROUTE_COST_CACHE"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_TIMING_LEDGER"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_RELAXED_ROUTE_COMPRESSION"], "0")

        throughput = e2_alns_throughput_flags()
        self.assertEqual(throughput["SETP_ALNS_CRUSH_SA_MODE"], "lns_cooling")
        self.assertEqual(throughput["SETP_ALNS_CRUSH_ROUTE_COST_CACHE"], "1")
        self.assertEqual(throughput["SETP_ALNS_CRUSH_REPAIR_STRUCTURE_CACHE"], "1")
        self.assertEqual(throughput["SETP_ALNS_CRUSH_TIMING_LEDGER"], "1")
        self.assertEqual(throughput["SETP_ALNS_CRUSH_RELAXED_ROUTE_COMPRESSION"], "0")

    def test_relaxed_route_compression_component_sets_explicit_flags(self) -> None:
        from baselines.e2_alns.e2_final_closure import flags_for_profile

        flags, carbon_bias = flags_for_profile("alns_e2_throughput", ["RELAXED_ROUTE_COMPRESSION"])

        self.assertEqual(carbon_bias, 0.0)
        self.assertEqual(flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"], "1")
        self.assertEqual(flags["SETP_ALNS_CRUSH_RELAXED_ROUTE_COMPRESSION"], "1")

    def test_route_elimination_default_rejects_same_route_count_candidate(self) -> None:
        bundle = load_search_bundle(VERIFY_BUNDLE)
        solution = make_shared_initial_solution(bundle)
        context = EvaluationContext(bundle.instance, bundle.carbon_profile)
        current_obj = float(evaluate(solution, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)["total_cost"])
        candidate_solution = replace(solution, routes=list(reversed(solution.routes)))

        def fake_destroy(state: winner_ops.AlnsState, rng: object, **kwargs: object) -> winner_ops.AlnsState:
            return replace(state, removed_customers=("C1",), source_solution=state.solution, allow_new_route_repair=False)

        def fake_repair(state: winner_ops.AlnsState, rng: object, **kwargs: object) -> winner_ops.AlnsState:
            return winner_ops.AlnsState(
                candidate_solution,
                state.context,
                objective_value=state.objective() - 1.0,
                policy=state.policy,
            )

        operator_set = winner_ops.WinnerOperatorSet(
            destroy_ops=(("route_elimination_removal", fake_destroy),),
            repair_ops=(("fake_repair", fake_repair),),
            include_route_elimination=True,
        )
        flags = e2_alns_throughput_flags()
        flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"] = "1"

        result = winner_ops.apply_winner_action(
            solution,
            winner_ops.WinnerOperatorAction("route_elimination_removal", "fake_repair"),
            context,
            operator_set=operator_set,
            current_obj=current_obj,
            variant_flags=flags,
        )

        self.assertIs(result["candidate_state"].solution, solution)
        self.assertFalse(result["changed"])

    def test_relaxed_route_compression_accepts_lower_cost_same_route_count_candidate(self) -> None:
        bundle = load_search_bundle(VERIFY_BUNDLE)
        solution = make_shared_initial_solution(bundle)
        context = EvaluationContext(bundle.instance, bundle.carbon_profile)
        current_obj = float(evaluate(solution, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)["total_cost"])
        candidate_solution = replace(solution, routes=list(reversed(solution.routes)))

        def fake_destroy(state: winner_ops.AlnsState, rng: object, **kwargs: object) -> winner_ops.AlnsState:
            return replace(state, removed_customers=("C1",), source_solution=state.solution, allow_new_route_repair=False)

        def fake_repair(state: winner_ops.AlnsState, rng: object, **kwargs: object) -> winner_ops.AlnsState:
            return winner_ops.AlnsState(
                candidate_solution,
                state.context,
                objective_value=state.objective() - 1.0,
                policy=state.policy,
            )

        operator_set = winner_ops.WinnerOperatorSet(
            destroy_ops=(("route_elimination_removal", fake_destroy),),
            repair_ops=(("fake_repair", fake_repair),),
            include_route_elimination=True,
        )
        flags = e2_alns_throughput_flags()
        flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"] = "1"
        flags["SETP_ALNS_CRUSH_RELAXED_ROUTE_COMPRESSION"] = "1"

        result = winner_ops.apply_winner_action(
            solution,
            winner_ops.WinnerOperatorAction("route_elimination_removal", "fake_repair"),
            context,
            operator_set=operator_set,
            current_obj=current_obj,
            variant_flags=flags,
        )

        self.assertIs(result["candidate_state"].solution, candidate_solution)
        self.assertTrue(result["changed"])

    def test_relaxed_route_compression_rejects_infeasible_candidate(self) -> None:
        bundle = load_search_bundle(VERIFY_BUNDLE)
        solution = make_shared_initial_solution(bundle)
        context = EvaluationContext(bundle.instance, bundle.carbon_profile)
        current_obj = float(evaluate(solution, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)["total_cost"])
        infeasible_solution = replace(solution, routes=solution.routes[:-1])

        def fake_destroy(state: winner_ops.AlnsState, rng: object, **kwargs: object) -> winner_ops.AlnsState:
            return replace(state, removed_customers=("C1",), source_solution=state.solution, allow_new_route_repair=False)

        def fake_repair(state: winner_ops.AlnsState, rng: object, **kwargs: object) -> winner_ops.AlnsState:
            return winner_ops.AlnsState(
                infeasible_solution,
                state.context,
                objective_value=state.objective() - 1.0,
                policy=state.policy,
            )

        operator_set = winner_ops.WinnerOperatorSet(
            destroy_ops=(("route_elimination_removal", fake_destroy),),
            repair_ops=(("fake_repair", fake_repair),),
            include_route_elimination=True,
        )
        flags = e2_alns_throughput_flags()
        flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"] = "1"
        flags["SETP_ALNS_CRUSH_RELAXED_ROUTE_COMPRESSION"] = "1"

        result = winner_ops.apply_winner_action(
            solution,
            winner_ops.WinnerOperatorAction("route_elimination_removal", "fake_repair"),
            context,
            operator_set=operator_set,
            current_obj=current_obj,
            variant_flags=flags,
        )

        self.assertIs(result["candidate_state"].solution, solution)
        self.assertFalse(result["changed"])

    def test_candidate_route_elimination_relaxed_gate_accepts_cost_drop_without_route_drop(self) -> None:
        bundle = load_search_bundle(VERIFY_BUNDLE)
        solution = make_shared_initial_solution(bundle)
        candidate_solution = replace(solution, routes=list(reversed(solution.routes)))
        context = EvaluationContext(bundle.instance, bundle.carbon_profile)

        with patch.object(candidate_ops, "_regret_reinsert_removed", return_value=candidate_solution), patch.object(
            candidate_ops,
            "model_cost",
            side_effect=lambda item, _context: 9.0 if item is candidate_solution else 10.0,
        ), patch.object(
            candidate_ops,
            "solution_signature_hash",
            side_effect=lambda item: "candidate" if item is candidate_solution else "source",
        ):
            with patch.dict(os.environ, {"SETP_ALNS_CRUSH_RELAXED_ROUTE_COMPRESSION": "0"}):
                strict = candidate_ops._apply_dr_route_elimination(solution, context, random.Random(1))
            with patch.dict(os.environ, {"SETP_ALNS_CRUSH_RELAXED_ROUTE_COMPRESSION": "1"}):
                relaxed = candidate_ops._apply_dr_route_elimination(solution, context, random.Random(1))

        self.assertIs(strict.solution, solution)
        self.assertFalse(strict.changed)
        self.assertIs(relaxed.solution, candidate_solution)
        self.assertTrue(relaxed.changed)

    def test_route_cost_cache_matches_uncached_route_cost(self) -> None:
        bundle = load_search_bundle(VERIFY_BUNDLE)
        solution = make_shared_initial_solution(bundle)
        route = solution.routes[0]
        context = EvaluationContext(bundle.instance, bundle.carbon_profile)
        old = os.environ.get("SETP_ALNS_CRUSH_ROUTE_COST_CACHE")
        try:
            os.environ["SETP_ALNS_CRUSH_ROUTE_COST_CACHE"] = "0"
            uncached = route_model_cost(route, solution.charging_actions, context)
            os.environ["SETP_ALNS_CRUSH_ROUTE_COST_CACHE"] = "1"
            cached = route_model_cost(route, solution.charging_actions, context)
            cached_again = route_model_cost(route, solution.charging_actions, context)
        finally:
            if old is None:
                os.environ.pop("SETP_ALNS_CRUSH_ROUTE_COST_CACHE", None)
            else:
                os.environ["SETP_ALNS_CRUSH_ROUTE_COST_CACHE"] = old

        self.assertAlmostEqual(uncached, cached)
        self.assertAlmostEqual(cached, cached_again)

    def test_timeout_row_returns_finite_checkpoint_incumbent(self) -> None:
        bundle = load_search_bundle(VERIFY_BUNDLE)
        warm = make_shared_initial_solution(bundle)
        warm_cost = float(evaluate(warm, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)["total_cost"])
        with tempfile.TemporaryDirectory() as tmp:
            task = _task(REPO_ROOT, Path(tmp), "vanilla", "e2-vanilla-10c-01", "LNS", 1, 32, 0.001)
            task["bundle_dir"] = str(VERIFY_BUNDLE.relative_to(REPO_ROOT))
            task["category"] = "fixture"
            task["instance"] = "verify_20251113"
            _write_checkpoint(Path(task["checkpoint_path"]), warm, best_cost=warm_cost, best_obj=warm_cost, eval_count=0, elapsed_seconds=0.0, operator="shared_warm_start")
            row = _timeout_row(task, elapsed=1.0, stdout="", stderr="")

        self.assertEqual(row["status"], "HALT_HARD_TIMEOUT_WITH_INCUMBENT")
        self.assertTrue(math.isfinite(float(row["best_cost"])))
        self.assertEqual(row["violation_count"], 0)

    def test_e2_alns_throughput_same_seed_small_budget_is_deterministic(self) -> None:
        config = WinnerKernelConfig(seed=11, eval_budget=16, max_runtime_seconds=120.0)

        first = run_e2_alns_throughput(VERIFY_BUNDLE, config=config)
        second = run_e2_alns_throughput(VERIFY_BUNDLE, config=config)

        self.assertEqual(first["violation_count"], 0)
        self.assertEqual(second["violation_count"], 0)
        self.assertAlmostEqual(first["best_cost"], second["best_cost"])
        self.assertEqual(first["evaluations"], second["evaluations"])
        self.assertTrue(first["timings"])

    def test_e2_alns_throughput_default_prices_match_explicit_default(self) -> None:
        config = WinnerKernelConfig(seed=12, eval_budget=4, max_runtime_seconds=120.0)

        implicit = run_e2_alns_throughput(VERIFY_BUNDLE, config=config)
        explicit = run_e2_alns_throughput(VERIFY_BUNDLE, config=config, prices=DEFAULT_PRICES)

        self.assertEqual(implicit["violation_count"], explicit["violation_count"])
        self.assertEqual(implicit["evaluations"], explicit["evaluations"])
        self.assertAlmostEqual(implicit["best_cost"], explicit["best_cost"])

    def test_e2_alns_throughput_prices_override_reaches_search_context(self) -> None:
        override = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
        captured_batteries: list[float] = []
        real_context = winner_impl.EvaluationContext

        def recording_context(*args: object, **kwargs: object) -> EvaluationContext:
            context = real_context(*args, **kwargs)
            captured_batteries.append(float(getattr(context.prices, "B_battery_kwh")))
            return context

        # Patch the independent algorithm module (shim re-exports only).
        with patch.object(winner_impl, "EvaluationContext", side_effect=recording_context):
            result = winner_ops.run_e2_alns_throughput(
                VERIFY_BUNDLE,
                config=WinnerKernelConfig(seed=13, eval_budget=2, max_runtime_seconds=120.0),
                prices=override,
            )

        self.assertEqual(result["violation_count"], 0)
        self.assertTrue(captured_batteries)
        self.assertEqual(set(captured_batteries), {280.0})

    def test_carbon_operator_registry_is_isolated_from_default_winner(self) -> None:
        default_ops = winner_ops.WinnerOperatorSet.create()
        carbon_ops = winner_ops.WinnerOperatorSet.create(carbon_aware=True, carbon_bias_weight=1.0)
        ablation_ops = winner_ops.WinnerOperatorSet.create(carbon_aware=True, carbon_bias_weight=0.0)

        default_destroy = [name for name, _ in default_ops.destroy_ops]
        default_repair = [name for name, _ in default_ops.repair_ops]
        carbon_destroy = [name for name, _ in carbon_ops.destroy_ops]
        carbon_repair = [name for name, _ in carbon_ops.repair_ops]

        self.assertEqual(
            default_destroy,
            [
                "random_customer_removal",
                "worst_customer_removal",
                "shaw_related_removal",
                "whole_route_removal",
                "route_segment_removal",
                "vehicle_type_swap",
            ],
        )
        self.assertEqual(default_repair, ["greedy_insert_repair", "regret2_insert_repair", "regret3_insert_repair"])
        self.assertIn("worst_carbon_removal", carbon_destroy)
        self.assertIn("carbon_related_removal", carbon_destroy)
        self.assertIn("low_carbon_charging_repair", carbon_repair)
        self.assertEqual([name for name, _ in ablation_ops.destroy_ops], carbon_destroy)
        self.assertEqual([name for name, _ in ablation_ops.repair_ops], carbon_repair)
        self.assertEqual(default_ops.carbon_bias_weight, 0.0)
        self.assertEqual(carbon_ops.carbon_bias_weight, 1.0)
        self.assertEqual(ablation_ops.carbon_bias_weight, 0.0)

    def test_run_e2_alns_carbon_uses_carbon_variant_without_changing_default(self) -> None:
        config = WinnerKernelConfig(seed=14, eval_budget=4, max_runtime_seconds=120.0)

        carbon = run_e2_alns_carbon(VERIFY_BUNDLE, config=config, carbon_bias_weight=1.0)
        ablation = run_e2_alns_carbon(VERIFY_BUNDLE, config=config, carbon_bias_weight=0.0, variant_id="alns_e2_carbon_ablation")
        default = run_e2_alns_throughput(VERIFY_BUNDLE, config=config)

        self.assertEqual(carbon["variant"], "alns_e2_carbon")
        self.assertEqual(ablation["variant"], "alns_e2_carbon_ablation")
        self.assertEqual(default["variant"], "e2_alns_throughput")
        self.assertEqual(carbon["violation_count"], 0)
        self.assertEqual(ablation["violation_count"], 0)
        self.assertIn("worst_carbon_removal", carbon["operator_counts"]["destroy"])
        self.assertNotIn("worst_carbon_removal", default["operator_counts"]["destroy"])

    def test_runner_smoke_outputs_finite_zero_violation_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_smoke(REPO_ROOT, Path(tmp))

        # v2026-06-26: physical-vehicle multi-trip semantics make the E2-10c
        # smoke feasible again under hard num_cv/num_ev caps.
        self.assertEqual(result["gate"], "SMOKE_OK")
        self.assertGreater(result["rows"], 0)


if __name__ == "__main__":
    unittest.main()
