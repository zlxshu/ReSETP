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

    def test_repair_route_ranking_reuses_precomputed_proximity(self) -> None:
        import setp_solver.algorithms.resetp_alns.operators.feasible_repair as repair

        bundle = load_search_bundle(VERIFY_BUNDLE)
        start = make_shared_initial_solution(bundle, prices=DEFAULT_PRICES)
        customer_id = next(node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c")
        customers = {idx: repair.route_customers(route, bundle.instance) for idx, route in enumerate(start.routes)}
        proximity = {
            (customer_id, idx): min(repair._distance(bundle.instance, customer_id, node_id) for node_id in route_customers)
            for idx, route_customers in customers.items()
            if route_customers
        }

        with patch.object(repair, "_distance", side_effect=AssertionError("proximity cache was ignored")):
            ranked = repair._ranked_routes(start.routes, customer_id, bundle.instance, 4, customers, proximity)

        self.assertTrue(ranked)

    def test_repair_cache_flag_is_read_once_from_the_instance(self) -> None:
        import setp_solver.algorithms.resetp_alns.operators.feasible_repair as repair

        bundle = load_search_bundle(VERIFY_BUNDLE)
        object.__setattr__(bundle.instance, "_setp_repair_structure_cache_enabled", True)

        with patch.object(repair.os.environ, "get", side_effect=AssertionError("environment was reread")):
            self.assertTrue(repair._structure_cache_enabled(bundle.instance))

    def test_repair_fast_distance_is_exactly_the_instance_distance(self) -> None:
        import setp_solver.algorithms.resetp_alns.operators.feasible_repair as repair

        bundle = load_search_bundle(VERIFY_BUNDLE)
        left = bundle.instance.nodes[0].node_id
        right = bundle.instance.nodes[-1].node_id

        self.assertEqual(repair._distance(bundle.instance, left, right), bundle.instance.distance(left, right))

    def test_lazy_insertion_sort_matches_the_original_full_tie_break(self) -> None:
        import setp_solver.algorithms.resetp_alns.operators.feasible_repair as repair

        bundle = load_search_bundle(VERIFY_BUNDLE)
        start = make_shared_initial_solution(bundle, prices=DEFAULT_PRICES)
        context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=DEFAULT_PRICES)
        customer_id = next(node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c")
        options = repair.enumerate_feasible_insertions(
            start,
            customer_id,
            context,
            type("Policy", (), {"max_cv": 100, "max_ev": 100, "require_charging_signal": False})(),
        )
        expected = sorted(
            reversed(options),
            key=lambda item: (item.score, item.opened_new_route, item.vehicle_type, repair._solution_key(item.solution)),
        )

        actual = repair._sort_insertion_options(list(reversed(options)))

        self.assertEqual([repair._solution_key(item.solution) for item in actual], [repair._solution_key(item.solution) for item in expected])

    def test_chain_selector_preserves_accepted_move_continuity_without_twenty_point_lock(self) -> None:
        from setp_solver.algorithms.resetp_alns.kernel.alns_core import _make_operator_selector

        selector = _make_operator_selector(2, 2, selector_kind="chain_ucb")

        self.assertEqual(selector.scores, [4.0, 3.0, 2.0, 0.05])

    def test_chain_selector_resets_only_at_completed_400_move_phases(self) -> None:
        from setp_solver.algorithms.resetp_alns.kernel.winner import (
            WinnerKernelConfig,
            _chain_acceptance_config,
            _chain_phase_progress,
            _should_reset_chain_selector,
        )

        self.assertFalse(_should_reset_chain_selector("chain_ucb", 0))
        self.assertFalse(_should_reset_chain_selector("chain_ucb", 399))
        self.assertTrue(_should_reset_chain_selector("chain_ucb", 400))
        self.assertFalse(_should_reset_chain_selector("alpha_ucb", 400))
        self.assertEqual(_chain_acceptance_config("chain_ucb", WinnerKernelConfig(eval_budget=4000)).eval_budget, 400)
        self.assertEqual(_chain_acceptance_config("alpha_ucb", WinnerKernelConfig(eval_budget=4000)).eval_budget, 4000)
        self.assertEqual(_chain_phase_progress("chain_ucb", 1, 4000), 1 / 400)
        self.assertEqual(_chain_phase_progress("chain_ucb", 400, 4000), 1.0)
        self.assertEqual(_chain_phase_progress("chain_ucb", 401, 4000), 1 / 400)
        self.assertEqual(_chain_phase_progress("alpha_ucb", 400, 4000), 0.1)

    def test_vehicle_type_closure_does_not_accept_a_worse_flip(self) -> None:
        from setp_solver.algorithms.resetp_alns.kernel.winner import _accept_winner_candidate

        always_accept = lambda *_args: True

        self.assertFalse(_accept_winner_candidate("vehicle_type_swap", True, 101.0, 100.0, always_accept, None, None, None, None))
        self.assertTrue(_accept_winner_candidate("random_customer_removal", True, 101.0, 100.0, always_accept, None, None, None, None))

    def test_staged_chain_splits_but_never_increases_the_evaluation_budget(self) -> None:
        from setp_solver.algorithms.resetp_alns.kernel.winner import _staged_chain_budgets, _staged_chain_plan

        self.assertEqual(_staged_chain_budgets(4000), (400, 3200, 400))
        self.assertEqual(_staged_chain_budgets(800), (400, 0, 400))
        self.assertEqual(_staged_chain_budgets(401), (400, 0, 1))
        self.assertEqual(_staged_chain_budgets(400), (400, 0, 0))
        self.assertEqual(sum(_staged_chain_budgets(16000)), 16000)
        self.assertEqual(_staged_chain_plan(4000, 2), ((400, 1600, 1600, 400), frozenset({1, 2})))
        self.assertEqual(sum(_staged_chain_plan(4000, 2)[0]), 4000)

    def test_staged_chain_runs_regular_bridge_regular_under_one_total_budget(self) -> None:
        import setp_solver.algorithms.resetp_alns.kernel.winner as winner
        from setp_solver.algorithms.resetp_alns.kernel.alns_core import AlnsRunResult

        bundle = load_search_bundle(VERIFY_BUNDLE)
        start = make_shared_initial_solution(bundle, prices=DEFAULT_PRICES)
        phase_results = [
            AlnsRunResult(start, start, 10.0, 9.0, 400, True),
            AlnsRunResult(start, start, 9.0, 5.0, 200, True),
            AlnsRunResult(start, start, 5.0, 6.0, 400, True),
        ]

        with patch.object(winner, "_run_winner_kernel_loop", side_effect=phase_results) as phase_run:
            result = winner.run_staged_chain_alns(
                start,
                bundle.instance,
                bundle.carbon_profile,
                config=winner.WinnerKernelConfig(seed=7, eval_budget=1000, max_runtime_seconds=30.0),
                prices=DEFAULT_PRICES,
            )

        self.assertEqual([call.kwargs["config"].eval_budget for call in phase_run.call_args_list], [400, 200, 400])
        self.assertEqual(
            [call.kwargs["variant_flags"][winner.STRONG_BRIDGE_BACKEND_FLAG] for call in phase_run.call_args_list],
            ["0", "1", "0"],
        )
        self.assertEqual(result.evaluations, 1000)
        self.assertEqual(result.best_obj, 5.0)
        self.assertEqual(result.operator_counts["staged_chain"]["best_phase"], 2)
        self.assertEqual(len(result.operator_counts["staged_chain"]["phase_operator_counts"]), 3)

    def test_restarted_staged_chain_splits_only_the_strong_middle_budget(self) -> None:
        import setp_solver.algorithms.resetp_alns.kernel.winner as winner
        from setp_solver.algorithms.resetp_alns.kernel.alns_core import AlnsRunResult

        bundle = load_search_bundle(VERIFY_BUNDLE)
        start = make_shared_initial_solution(bundle, prices=DEFAULT_PRICES)
        phase_results = [
            AlnsRunResult(start, start, 10.0, 9.0, 400, True),
            AlnsRunResult(start, start, 9.0, 7.0, 100, True),
            AlnsRunResult(start, start, 7.0, 5.0, 100, True),
            AlnsRunResult(start, start, 5.0, 6.0, 400, True),
        ]

        with patch.object(winner, "_run_winner_kernel_loop", side_effect=phase_results) as phase_run:
            result = winner.run_staged_chain_alns(
                start,
                bundle.instance,
                bundle.carbon_profile,
                config=winner.WinnerKernelConfig(seed=7, eval_budget=1000, max_runtime_seconds=30.0),
                prices=DEFAULT_PRICES,
                middle_restarts=2,
            )

        self.assertEqual([call.kwargs["config"].eval_budget for call in phase_run.call_args_list], [400, 100, 100, 400])
        self.assertEqual(
            [call.kwargs["variant_flags"][winner.STRONG_BRIDGE_BACKEND_FLAG] for call in phase_run.call_args_list],
            ["0", "1", "1", "0"],
        )
        self.assertEqual(result.evaluations, 1000)
        self.assertEqual(result.best_obj, 5.0)
        self.assertEqual(result.operator_counts["staged_chain"]["middle_restarts"], 2)
        self.assertEqual(result.operator_counts["staged_chain"]["strong_phase_indexes"], [1, 2])

    def test_staged_chain_forwards_e1_vehicle_policy_to_every_phase(self) -> None:
        import setp_solver.algorithms.resetp_alns.kernel.winner as winner
        from setp_solver.algorithms.resetp_alns.kernel.alns_core import AlnsRunResult, SearchPolicy

        bundle = load_search_bundle(VERIFY_BUNDLE)
        start = make_shared_initial_solution(bundle, prices=DEFAULT_PRICES)
        policy = SearchPolicy(require_charging_signal=False, max_cv=10, max_ev=0)
        phase_results = [
            AlnsRunResult(start, start, 10.0, 9.0, 400, True),
            AlnsRunResult(start, start, 9.0, 8.0, 200, True),
            AlnsRunResult(start, start, 8.0, 7.0, 400, True),
        ]

        with patch.object(winner, "_run_winner_kernel_loop", side_effect=phase_results) as phase_run:
            winner.run_staged_chain_alns(
                start,
                bundle.instance,
                bundle.carbon_profile,
                config=winner.WinnerKernelConfig(seed=7, eval_budget=1000, max_runtime_seconds=30.0),
                prices=DEFAULT_PRICES,
                policy=policy,
            )

        self.assertEqual([call.kwargs["policy"] for call in phase_run.call_args_list], [policy, policy, policy])

    def test_staged_chain_forwards_e3_context_to_every_phase(self) -> None:
        import setp_solver.algorithms.resetp_alns.kernel.winner as winner
        from setp_solver.algorithms.resetp_alns.kernel.alns_core import AlnsRunResult

        bundle = load_search_bundle(VERIFY_BUNDLE)
        start = make_shared_initial_solution(bundle, prices=DEFAULT_PRICES)
        phase_results = [
            AlnsRunResult(start, start, 10.0, 9.0, 400, True),
            AlnsRunResult(start, start, 9.0, 8.0, 200, True),
            AlnsRunResult(start, start, 8.0, 7.0, 400, True),
        ]
        owners = {node.node_id: "D0" for node in bundle.instance.nodes if node.node_type.lower() == "c"}

        with patch.object(winner, "_run_winner_kernel_loop", side_effect=phase_results) as phase_run:
            winner.run_staged_chain_alns(
                start,
                bundle.instance,
                bundle.carbon_profile,
                config=winner.WinnerKernelConfig(seed=7, eval_budget=1000, max_runtime_seconds=30.0),
                prices=DEFAULT_PRICES,
                carbon_weight=0.5,
                carbon_quota_kg=123.0,
                fairness_enabled=True,
                independent_profit={"D0": 10.0},
                fairness_theta=1.0,
                customer_home_depot=owners,
            )

        for call in phase_run.call_args_list:
            self.assertEqual(call.kwargs["carbon_weight"], 0.5)
            self.assertEqual(call.kwargs["carbon_quota_kg"], 123.0)
            self.assertTrue(call.kwargs["fairness_enabled"])
            self.assertEqual(call.kwargs["independent_profit"], {"D0": 10.0})
            self.assertEqual(call.kwargs["customer_home_depot"], owners)

    def test_e3_cross_site_accounting_is_rebuilt_from_route_assignments(self) -> None:
        import setp_solver.algorithms.resetp_alns.kernel.winner as winner
        from setp_solver.search.evaluation import EvaluationContext
        from setp_solver.solution import Route, Solution

        bundle = load_search_bundle(VERIFY_BUNDLE)
        customer = next(node for node in bundle.instance.nodes if node.node_type.lower() == "c")
        depots = [node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "d"]
        self.assertGreaterEqual(len(depots), 2)
        serving = depots[1]
        solution = Solution(routes=[Route("CV1", "cv", serving, [serving, customer.node_id, serving])])
        context = EvaluationContext(
            bundle.instance,
            bundle.carbon_profile,
            prices=DEFAULT_PRICES,
            customer_home_depot={customer.node_id: depots[0]},
        )

        annotated = winner._annotate_cross_site_services(solution, context)

        self.assertEqual(len(annotated.cross_site_services), 1)
        self.assertEqual(annotated.cross_site_services[0].customer_id, customer.node_id)
        self.assertEqual(annotated.cross_site_services[0].served_by_depot_id, serving)

    def test_staged_hybrid_has_a_distinct_public_identity_and_price_override(self) -> None:
        from setp_solver.algorithms.resetp_alns.kernel.winner import (
            WinnerKernelConfig,
            run_staged_alns_lns_hybrid,
        )

        bundle = load_search_bundle(VERIFY_BUNDLE)
        start = make_shared_initial_solution(bundle, prices=DEFAULT_PRICES)
        prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0)

        result = run_staged_alns_lns_hybrid(
            bundle.bundle_dir,
            config=WinnerKernelConfig(
                seed=1,
                eval_budget=2,
                max_runtime_seconds=30.0,
                carbon_aware_operators=True,
                carbon_operator_bias=1.0,
            ),
            initial_solution=start,
            prices=prices,
        )

        self.assertEqual(result["algorithm"], "staged ALNS-LNS hybrid")
        self.assertEqual(result["variant"], "staged_alns_lns_hybrid")
        self.assertEqual(result["evaluations"], 2)
        self.assertEqual(result["battery_kwh"], 280.0)
        self.assertTrue(result["carbon_aware_operators"])

    def test_restarted_staged_hybrid_uses_two_middle_basins_without_overwriting_incumbent(self) -> None:
        import setp_solver.algorithms.resetp_alns.kernel.winner as winner

        sentinel = {"variant": "restarted_staged_alns_lns_hybrid"}
        with patch.object(winner, "_run_staged_hybrid_entry", return_value=sentinel) as entry:
            result = winner.run_restarted_staged_alns_lns_hybrid(VERIFY_BUNDLE)

        self.assertIs(result, sentinel)
        self.assertEqual(entry.call_args.kwargs["middle_restarts"], 2)
        self.assertEqual(entry.call_args.kwargs["variant"], "restarted_staged_alns_lns_hybrid")
        self.assertEqual(entry.call_args.kwargs["algorithm"], "restarted staged ALNS-LNS hybrid")

    def test_true_lns_middle_hybrid_preserves_one_total_budget(self) -> None:
        import setp_solver.algorithms.resetp_alns.kernel.winner as winner
        import setp_solver.search.metaheuristic_baselines as baselines
        from setp_solver.search.evaluation import EvaluationContext, model_cost

        bundle = load_search_bundle(VERIFY_BUNDLE)
        start = make_shared_initial_solution(bundle, prices=DEFAULT_PRICES)
        cost = model_cost(start, EvaluationContext(bundle.instance, bundle.carbon_profile, prices=DEFAULT_PRICES))
        alns_result = {
            "best_solution": start,
            "best_cost": cost,
            "evaluations": 400,
            "history": [],
            "operator_counts": {},
        }
        middle_result = baselines.BaselineRunResult(
            algorithm="LNS",
            source="test",
            feasible=True,
            status="OK",
            evals=200,
            elapsed_seconds=0.0,
            best_cost=cost,
            best_penalized_obj=cost,
            best_solution=start,
        )

        with patch.object(winner, "run_staged_alns_lns_hybrid", side_effect=[alns_result, alns_result]) as alns, patch.object(
            baselines, "run_metaheuristic_baseline", return_value=middle_result
        ) as lns:
            result = winner.run_true_lns_middle_alns_hybrid(
                bundle.bundle_dir,
                config=winner.WinnerKernelConfig(seed=3, eval_budget=1000, max_runtime_seconds=30.0),
                initial_solution=start,
                prices=DEFAULT_PRICES,
            )

        self.assertEqual(result["evaluations"], 1000)
        self.assertEqual(result["operator_counts"]["true_lns_middle"]["budgets"], [400, 200, 400])
        self.assertEqual([call.kwargs["config"].eval_budget for call in alns.call_args_list], [400, 400])
        self.assertEqual(lns.call_args.kwargs["eval_budget"], 200)
        self.assertTrue(lns.call_args.kwargs["common_flip_preprocess"])

    def test_stability_gate_builds_exactly_thirty_frozen_tasks(self) -> None:
        from baselines.e2_alns.m1_staged_hybrid_stability_gate import build_tasks

        tasks = build_tasks(
            instances=(
                "L-main-threeshift-100c-01",
                "L-main-threeshift-150c-01",
                "L-main-threeshift-200c-01",
            ),
            seeds=(1, 2, 3, 4, 5),
        )

        self.assertEqual(len(tasks), 30)
        self.assertEqual({task.algorithm for task in tasks}, {"staged ALNS-LNS hybrid", "LNS"})
        self.assertEqual({task.seed for task in tasks}, {1, 2, 3, 4, 5})

    def test_staged_carbon_schedule_has_clean_aware_and_naive_variants(self) -> None:
        from setp_solver.algorithms.resetp_alns.kernel.winner import (
            WinnerKernelConfig,
            run_staged_carbon_schedule_pair,
        )

        bundle = load_search_bundle(VERIFY_BUNDLE)
        start = make_shared_initial_solution(bundle, prices=DEFAULT_PRICES)
        config = WinnerKernelConfig(seed=1, eval_budget=2, max_runtime_seconds=30.0)

        aware = run_staged_carbon_schedule_pair(
            bundle.bundle_dir,
            config=config,
            initial_solution=start,
            prices=DEFAULT_PRICES,
        )
        naive = aware["charging_ablation_result"]

        self.assertTrue(aware["carbon_aware_operators"])
        self.assertFalse(naive["carbon_aware_operators"])
        self.assertFalse(aware["legacy_carbon_search_operators"])
        self.assertEqual(aware["evaluations"], naive["evaluations"])
        self.assertEqual(
            [(route.vehicle_type, route.node_sequence) for route in aware["best_solution"].routes],
            [(route.vehicle_type, route.node_sequence) for route in naive["best_solution"].routes],
        )

if __name__ == "__main__":
    unittest.main()
