from __future__ import annotations

import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from setp_solver.algorithms.resetp_alns.support.construction import build_initial_solution
from setp_solver.algorithms.resetp_alns.support.fleet import infer_fleet_limits
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerKernelConfig,
    _run_winner_kernel_loop,
    e2_alns_throughput_flags,
)
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import _apply_path_operator_outcome, make_shared_initial_solution
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.search.instance_registry import instance_abs_dir


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/verify_20251113"


class M1JointRepackFleetHeadroomTests(unittest.TestCase):
    def test_verdict_requires_joint_gain_across_every_scale(self) -> None:
        from baselines.e2_alns.m1_joint_repack_fleet_headroom import classify_headroom

        strong = [
            {
                "scale": scale,
                "algorithm": algorithm,
                "clean": True,
                "joint_beyond_separate": 1.0,
            }
            for scale in ("small", "medium", "large")
            for algorithm in ("ALNS_T3", "LNS", "SA")
        ]
        partial = [dict(row, joint_beyond_separate=0.0) for row in strong]
        partial[0]["joint_beyond_separate"] = 1.0

        self.assertEqual(classify_headroom(strong), "JOINT_REPACK_FLEET_HEADROOM_STRONG")
        self.assertEqual(classify_headroom(partial), "JOINT_REPACK_FLEET_HEADROOM_PARTIAL")
        self.assertEqual(classify_headroom([]), "JOINT_REPACK_FLEET_HEADROOM_NOT_FOUND")

    def test_fleet_closure_is_feasible_and_never_worse(self) -> None:
        from baselines.e2_alns.m1_joint_repack_fleet_headroom import greedy_fleet_closure

        bundle = load_search_bundle(VERIFY_BUNDLE)
        start = make_shared_initial_solution(bundle, prices=DEFAULT_PRICES)
        context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=DEFAULT_PRICES)
        before = model_cost(start, context)

        outcome = greedy_fleet_closure(start, context)

        self.assertFalse(check_solution(outcome.solution, bundle.instance, DEFAULT_PRICES))
        self.assertLessEqual(outcome.cost, before + 1e-9)
        self.assertEqual(outcome.accepted_flips, len(outcome.trace_rows))

    def test_repack_candidates_keep_all_customers_and_include_current_order(self) -> None:
        from baselines.e2_alns.m1_joint_repack_fleet_headroom import repack_candidates

        bundle = load_search_bundle(VERIFY_BUNDLE)
        start = make_shared_initial_solution(bundle, prices=DEFAULT_PRICES)
        context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=DEFAULT_PRICES)

        rows = repack_candidates(start, context, random.Random(7), trials=2)

        self.assertEqual(len(rows), 8)
        self.assertEqual(sum(row.label.endswith("current_order") for row in rows), 2)
        expected = {
            node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"
        }
        for row in rows:
            actual = {
                node_id
                for route in row.solution.routes
                for node_id in route.node_sequence
                if node_id in expected
            }
            self.assertEqual(actual, expected)

    def test_vehicle_flip_is_a_safe_noop_when_instance_has_no_ev_fleet(self) -> None:
        bundle = load_search_bundle(instance_abs_dir(REPO_ROOT, "L-main-threeshift-15c-01"))
        prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
        start = build_initial_solution(
            bundle.instance,
            bundle.carbon_profile,
            prices,
            fleet_limits=infer_fleet_limits(bundle.bundle_dir),
            introduce_ev=False,
            require_charging_signal=False,
        )
        context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)

        outcome = _apply_path_operator_outcome(start, context, random.Random(0), "vehicle_type_flip")

        self.assertFalse(outcome.changed)
        self.assertFalse(outcome.feasible)
        self.assertIn("operator_returned_none", outcome.detail)

    def test_t3_reports_full_solution_scores_hidden_inside_local_search(self) -> None:
        bundle = load_search_bundle(VERIFY_BUNDLE)
        start = make_shared_initial_solution(bundle, prices=DEFAULT_PRICES)
        flags = e2_alns_throughput_flags()
        flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"] = "1"

        run = _run_winner_kernel_loop(
            start,
            bundle.instance,
            bundle.carbon_profile,
            config=WinnerKernelConfig(seed=1, eval_budget=12, max_runtime_seconds=30.0),
            prices=DEFAULT_PRICES,
            variant_flags=flags,
        )

        counts = run.operator_counts["score_counts"]
        self.assertGreater(counts["local_search_neighbor"], 0)
        self.assertGreater(counts["local_search_full_solution"], counts["local_search_neighbor"])
        self.assertEqual(run.evaluations, run.candidate_scores)

    def test_scan_rebuild_cannot_push_loop_past_exact_budget(self) -> None:
        bundle = load_search_bundle(instance_abs_dir(REPO_ROOT, "L-main-threeshift-50c-01"))
        prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
        start = build_initial_solution(
            bundle.instance,
            bundle.carbon_profile,
            prices,
            fleet_limits=infer_fleet_limits(bundle.bundle_dir),
            introduce_ev=False,
            require_charging_signal=False,
        )
        flags = e2_alns_throughput_flags()
        flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"] = "0"

        run = _run_winner_kernel_loop(
            start,
            bundle.instance,
            bundle.carbon_profile,
            config=WinnerKernelConfig(seed=3, eval_budget=100, max_runtime_seconds=30.0),
            prices=prices,
            variant_flags=flags,
        )

        self.assertEqual(run.evaluations, 100)

    def test_hash_targets_exclude_appledouble_and_task_state(self) -> None:
        from baselines.e2_alns.m1_joint_repack_fleet_headroom import evidence_files

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "keep.csv").write_text("x\n", encoding="utf-8")
            (root / "._keep.csv").write_text("sidecar", encoding="utf-8")
            (root / ".tasks").mkdir()
            (root / ".tasks" / "one.json").write_text("{}", encoding="utf-8")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "x.pyc").write_bytes(b"cache")

            self.assertEqual(evidence_files(root), [root / "keep.csv"])

    def test_budget_verdict_requires_hidden_full_solution_scores(self) -> None:
        from baselines.e2_alns.m1_local_search_budget_probe import classify_budget

        rows = [
            {"profile": "CURRENT_T3", "clean": True, "hidden_full_solution_scores": 24},
            {"profile": "NO_LOCAL_SEARCH", "clean": True, "hidden_full_solution_scores": 0},
        ]

        self.assertEqual(classify_budget(rows), "LOCAL_SEARCH_BUDGET_UNDERCOUNT_CONFIRMED")
        self.assertEqual(classify_budget(rows[1:]), "LOCAL_SEARCH_BUDGET_UNDERCOUNT_NOT_SHOWN")

    def test_vehicle_swap_ranking_does_not_call_full_solution_evaluator(self) -> None:
        import setp_solver.algorithms.resetp_alns.kernel.alns_core as core

        bundle = load_search_bundle(VERIFY_BUNDLE)
        start = make_shared_initial_solution(bundle, prices=DEFAULT_PRICES)
        context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=DEFAULT_PRICES)
        state = core.AlnsState(
            start,
            context,
            policy=core.SearchPolicy(max_cv=100, max_ev=100),
        )

        with patch.object(core, "evaluate", wraps=core.evaluate) as full_evaluate:
            core.vehicle_type_swap(state, np.random.default_rng(3))

        self.assertEqual(full_evaluate.call_count, 0)

    def test_vehicle_swap_has_only_one_legal_repair_pair_for_every_selector(self) -> None:
        from setp_solver.algorithms.resetp_alns.kernel.winner import (
            WinnerOperatorSet,
            _selector_coupling_contract,
        )

        operators = WinnerOperatorSet.create()
        coupling = _selector_coupling_contract(operators)
        vehicle_index = [name for name, _fn in operators.destroy_ops].index("vehicle_type_swap")

        self.assertEqual(int(coupling[vehicle_index].sum()), 1)

    def test_fair_selector_gate_requires_cost_and_runtime_improvement(self) -> None:
        from baselines.e2_alns.m1_fair_selector_probe import classify_selector

        supported = [
            {
                "softmax_minus_default": -10.0 if index < 6 else 1.0,
                "softmax_runtime_minus_default": -0.1,
                "clean": True,
            }
            for index in range(9)
        ]
        slower = [dict(row, softmax_runtime_minus_default=0.1) for row in supported]

        self.assertEqual(classify_selector(supported), "FAIR_SOFTMAX_400_SUPPORTED")
        self.assertEqual(classify_selector(slower), "FAIR_SOFTMAX_400_NOT_SUPPORTED")

    def test_repair_route_ranking_reuses_precomputed_route_customers(self) -> None:
        import setp_solver.algorithms.resetp_alns.operators.feasible_repair as repair

        bundle = load_search_bundle(VERIFY_BUNDLE)
        start = make_shared_initial_solution(bundle, prices=DEFAULT_PRICES)
        customer_id = next(node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c")
        cached = {idx: repair.route_customers(route, bundle.instance) for idx, route in enumerate(start.routes)}

        with patch.object(repair, "route_customers", side_effect=AssertionError("cache was ignored")):
            ranked = repair._ranked_routes(start.routes, customer_id, bundle.instance, 4, cached)

        self.assertTrue(ranked)

    def test_repair_cache_flag_is_read_once_from_the_instance(self) -> None:
        import setp_solver.algorithms.resetp_alns.operators.feasible_repair as repair

        bundle = load_search_bundle(VERIFY_BUNDLE)
        object.__setattr__(bundle.instance, "_setp_repair_structure_cache_enabled", True)

        with patch.object(repair.os.environ, "get", side_effect=AssertionError("environment was reread")):
            self.assertTrue(repair._structure_cache_enabled(bundle.instance))

    def test_chain_selector_preserves_accepted_move_continuity_without_twenty_point_lock(self) -> None:
        from setp_solver.algorithms.resetp_alns.kernel.alns_core import _make_operator_selector

        selector = _make_operator_selector(2, 2, selector_kind="chain_ucb")

        self.assertEqual(selector.scores, [4.0, 3.0, 2.0, 0.05])

if __name__ == "__main__":
    unittest.main()
