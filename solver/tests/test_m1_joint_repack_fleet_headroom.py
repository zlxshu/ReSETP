from __future__ import annotations

import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from setp_solver.algorithms.resetp_alns.support.construction import build_initial_solution
from setp_solver.algorithms.resetp_alns.support.fleet import infer_fleet_limits
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


if __name__ == "__main__":
    unittest.main()
