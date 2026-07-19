"""Zero-search contract tests for mechanism-priced pair resplitting."""

from __future__ import annotations

import ast
import copy
from dataclasses import replace
import math
import os
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (REPO / "solver/src", REPO / "models/src", HERE, LEGACY, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mechanism_priced_pair_resplit_fixtures import (  # noqa: E402
    binding_fixture,
    joint_station_conflict_fixture,
    nonbinding_fixture,
)
from mechanism_priced_pair_resplit_oracle import (  # noqa: E402
    exhaustive_fixture_oracle,
)
from mechanism_priced_pair_resplit_solver import (  # noqa: E402
    DISTANCE_ARM,
    MECHANISM_ARM,
    PairResplitConfig,
    _bounded_cut_positions,
    _bounded_starts,
    _candidate_invariants,
    _validated_config,
    joint_completion_probe,
    joint_feasibility_probe,
    prepare_pair_resplit,
    run_pair_resplit_arm,
    verify_pair_resplit_result,
    verify_prepared_pool,
)
from setp_solver.solution import Route  # noqa: E402


class PairResplitPreflightTests(unittest.TestCase):
    """Checks that do not execute the candidate solver's behaviour arms."""

    def test_binding_fixture_has_real_ranking_headroom(self) -> None:
        fixture = binding_fixture()
        oracle = exhaustive_fixture_oracle(fixture)
        self.assertGreaterEqual(len(oracle.records), 6)
        self.assertIsNotNone(oracle.global_best)
        self.assertIsNotNone(oracle.best_distance_top4)
        self.assertIsNotNone(oracle.best_mechanism_top4)
        assert oracle.global_best is not None
        assert oracle.best_mechanism_top4 is not None
        self.assertNotIn(oracle.global_best, oracle.distance_order[:4])
        self.assertIn(oracle.global_best, oracle.mechanism_order[:4])
        self.assertEqual(
            oracle.global_best.left_customers,
            fixture.expected_mechanism_left,
        )
        self.assertEqual(
            oracle.global_best.right_customers,
            fixture.expected_mechanism_right,
        )
        self.assertEqual(oracle.best_mechanism_top4, oracle.global_best)
        self.assertTrue(
            all(math.isfinite(record.mechanism_score) for record in oracle.records)
        )

    def test_nonbinding_fixture_has_no_better_cut(self) -> None:
        fixture = nonbinding_fixture()
        oracle = exhaustive_fixture_oracle(fixture)
        self.assertEqual(len(oracle.records), 1)
        assert oracle.global_best is not None
        from setp_solver.search.evaluation import model_cost

        self.assertGreater(
            oracle.global_best.complete_cost,
            model_cost(fixture.source, fixture.context),
        )

    def test_joint_public_station_conflict_is_real_and_attached(self) -> None:
        fixture = joint_station_conflict_fixture()
        left = joint_completion_probe(fixture.left_only, fixture.context)
        right = joint_completion_probe(fixture.right_only, fixture.context)
        joint = joint_completion_probe(fixture.joint, fixture.context)
        self.assertTrue(left["feasible"])
        self.assertTrue(right["feasible"])
        self.assertFalse(joint["feasible"])
        self.assertEqual(joint["violation_types"], ["STATION_CAPACITY"])
        self.assertEqual(
            joint["completion_activity"]["charge_actions_selected"],
            2,
        )
        self.assertGreaterEqual(
            joint["completion_activity"]["generated_charge_starts"],
            2,
        )
        self.assertEqual(
            joint["completion_activity"]["retained_charge_starts"],
            2,
        )
        self.assertGreaterEqual(
            joint["completion_activity"]["local_start_evaluations"],
            2,
        )
        widened_nodes = [
            replace(node, due_time=3_600.0)
            if node.node_id == "F1"
            else node
            for node in fixture.context.instance.nodes
        ]
        widened_context = replace(
            fixture.context,
            instance=replace(
                fixture.context.instance,
                nodes=widened_nodes,
            ),
        )
        resolvable = joint_completion_probe(
            fixture.joint,
            widened_context,
        )
        self.assertTrue(resolvable["feasible"])
        self.assertNotEqual(
            resolvable["input_solution_sha256"],
            resolvable["output_solution_sha256"],
        )
        self.assertEqual(
            len(
                {
                    action["charge_start_second"]
                    for action in resolvable["output_charging_actions"]
                }
            ),
            2,
        )
        route_ids = {route.vehicle_id for route in fixture.joint.routes}
        self.assertTrue(
            all(
                action.vehicle_id in route_ids
                and action.station_id in next(
                    route.node_sequence
                    for route in fixture.joint.routes
                    if route.vehicle_id == action.vehicle_id
                )
                for action in fixture.joint.charging_actions
            )
        )

    def test_boolean_and_over_cap_values_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _validated_config(
                replace(PairResplitConfig(), max_exact_candidates=True)
            )
        with self.assertRaises(ValueError):
            _validated_config(
                replace(PairResplitConfig(), max_exact_candidates=5)
            )
        with self.assertRaises(ValueError):
            _validated_config(
                replace(PairResplitConfig(), max_joint_checks=10)
            )

    def test_bounded_cut_and_start_selection_is_deterministic(self) -> None:
        self.assertEqual(
            _bounded_cut_positions(40, 16),
            _bounded_cut_positions(40, 16),
        )
        self.assertEqual(len(_bounded_cut_positions(40, 16)), 16)
        starts = tuple(float(index * 1_800) for index in range(48))
        selected = _bounded_starts(starts, current=18_000.0, limit=16)
        self.assertEqual(selected, _bounded_starts(starts, current=18_000.0, limit=16))
        self.assertLessEqual(len(selected), 16)
        self.assertIn(0.0, selected)
        self.assertIn(starts[-1], selected)
        self.assertIn(18_000.0, selected)

    def test_solver_source_has_no_route_search_import(self) -> None:
        tree = ast.parse(
            (HERE / "mechanism_priced_pair_resplit_solver.py").read_text(
                encoding="utf-8"
            )
        )
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertNotIn("prototype", imported_modules)
        self.assertFalse(
            any(
                module is not None
                and (
                    module.endswith(".winner")
                    or "hgs" in module.lower()
                    or module.endswith("search.candidates")
                )
                for module in imported_modules
            )
        )
        forbidden_calls = {
            "run_pure_alns",
            "run_mechanism_alns",
            "score_search_candidate",
            "solve_hgs",
            "winner",
        }
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        }
        called_names.update(
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        )
        self.assertTrue(forbidden_calls.isdisjoint(called_names))


@unittest.skipUnless(
    os.environ.get("RESETP_PAIR_RESPLIT_ONE_SHOT") == "1",
    "frozen behaviour tests may run only inside the one-shot gate",
)
class PairResplitFrozenBehaviourTests(unittest.TestCase):
    """Run only inside the post-commit, one-shot behaviour-gate wrapper."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.binding = binding_fixture()
        cls.oracle = exhaustive_fixture_oracle(cls.binding)
        cls.prepared = prepare_pair_resplit(
            cls.binding.source,
            cls.binding.context,
        )

    def test_common_pool_matches_independent_exhaustive_oracle(self) -> None:
        oracle_boundaries = {
            (record.left_customers, record.right_customers)
            for record in self.oracle.records
        }
        solver_boundaries = {
            (candidate.left_customers, candidate.right_customers)
            for candidate in self.prepared.candidates
        }
        self.assertEqual(solver_boundaries, oracle_boundaries)
        self.assertEqual(len(self.prepared.candidates), len(self.oracle.records))
        oracle_scores = {
            (record.left_customers, record.right_customers): (
                record.distance_score,
                record.mechanism_score,
            )
            for record in self.oracle.records
        }
        for candidate in self.prepared.candidates:
            distance, mechanism = oracle_scores[
                (candidate.left_customers, candidate.right_customers)
            ]
            self.assertAlmostEqual(candidate.distance_score, distance, places=7)
            self.assertAlmostEqual(
                candidate.mechanism_score,
                mechanism,
                places=7,
            )
        verify_prepared_pool(self.prepared)

    def test_exact_caps_zero_one_two_four_close_without_target_plus_one(self) -> None:
        for cap in (0, 1, 2, 4):
            with self.subTest(cap=cap):
                result = run_pair_resplit_arm(
                    self.prepared,
                    arm=MECHANISM_ARM,
                    exact_candidate_capacity=cap,
                )
                self.assertEqual(
                    result.activity["exact_candidates_completed"],
                    cap,
                )
                self.assertLessEqual(
                    result.activity["joint_complete_replays"],
                    cap * 4,
                )
                self.assertEqual(
                    result.activity["complete_route_search_evaluations"],
                    0,
                )
                if cap == 0:
                    self.assertFalse(result.changed)
                else:
                    self.assertTrue(result.changed)
                verify_pair_resplit_result(result, self.prepared)

    def test_binding_mechanism_arm_strictly_wins_distance_arm(self) -> None:
        mechanism = run_pair_resplit_arm(
            self.prepared,
            arm=MECHANISM_ARM,
        )
        distance = run_pair_resplit_arm(
            self.prepared,
            arm=DISTANCE_ARM,
        )
        self.assertTrue(mechanism.changed)
        self.assertFalse(distance.changed)
        self.assertLess(mechanism.cost, distance.cost)
        self.assertLess(mechanism.cost, mechanism.source_cost)
        self.assertLess(mechanism.cost, mechanism.counterfactual_cost)
        self.assertEqual(
            mechanism.activity["candidate_set_sha256"],
            distance.activity["candidate_set_sha256"],
        )
        self.assertEqual(
            mechanism.activity["complete_route_search_evaluations"],
            0,
        )
        self.assertEqual(
            distance.activity["complete_route_search_evaluations"],
            0,
        )
        expected = self.oracle.global_best
        assert expected is not None
        self.assertAlmostEqual(mechanism.cost, expected.complete_cost, places=7)
        verify_pair_resplit_result(mechanism, self.prepared)
        verify_pair_resplit_result(distance, self.prepared)

    def test_nonbinding_fixture_is_exact_noop_for_both_arms(self) -> None:
        fixture = nonbinding_fixture()
        prepared = prepare_pair_resplit(fixture.source, fixture.context)
        for arm in (MECHANISM_ARM, DISTANCE_ARM):
            with self.subTest(arm=arm):
                result = run_pair_resplit_arm(prepared, arm=arm)
                self.assertFalse(result.changed)
                self.assertEqual(result.solution, fixture.source)
                self.assertEqual(result.activity["accepted_moves"], 0)
                verify_pair_resplit_result(result, prepared)

    def test_integrity_tampering_is_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            verify_prepared_pool(
                replace(
                    self.prepared,
                    candidate_set_sha256="0" * 64,
                )
            )
        forged_activity = dict(self.prepared.preparation_activity)
        forged_activity["common_candidates"] = True
        with self.assertRaises((RuntimeError, ValueError)):
            verify_prepared_pool(
                replace(
                    self.prepared,
                    preparation_activity=forged_activity,
                )
            )
        with self.assertRaises(RuntimeError):
            verify_prepared_pool(
                replace(
                    self.prepared,
                    counterfactual=replace(
                        self.prepared.counterfactual,
                        record_sha256="f" * 64,
                    ),
                )
            )
        changed_context = copy.deepcopy(self.prepared.context)
        changed_context.carbon_weight = 2.0
        with self.assertRaises(RuntimeError):
            verify_prepared_pool(
                replace(self.prepared, context=changed_context)
            )
        mechanism = run_pair_resplit_arm(
            self.prepared,
            arm=MECHANISM_ARM,
        )
        forged_completion = copy.deepcopy(mechanism.activity)
        forged_completion["records"][0]["completion"][
            "joint_complete_replays"
        ] += 1
        with self.assertRaises(RuntimeError):
            verify_pair_resplit_result(
                replace(mechanism, activity=forged_completion),
                self.prepared,
            )
        with self.assertRaises(RuntimeError):
            verify_pair_resplit_result(
                replace(mechanism, result_sha256="0" * 64),
                self.prepared,
            )
        forged_replay_cost = copy.deepcopy(mechanism.activity)
        replay_cost_changed = False
        for candidate_record in forged_replay_cost["records"]:
            for pattern_record in candidate_record["completion"]["records"]:
                if pattern_record["feasible"]:
                    pattern_record["complete_cost"] += 1.0
                    replay_cost_changed = True
                    break
            if replay_cost_changed:
                break
        self.assertTrue(replay_cost_changed)
        with self.assertRaises(RuntimeError):
            verify_pair_resplit_result(
                replace(mechanism, activity=forged_replay_cost),
                self.prepared,
            )

    def test_duplicate_lost_customer_and_nonpair_drift_are_detected(self) -> None:
        mechanism = run_pair_resplit_arm(
            self.prepared,
            arm=MECHANISM_ARM,
        )
        first = mechanism.solution.routes[0]
        lost = replace(
            mechanism.solution,
            routes=[
                replace(first, node_sequence=first.node_sequence[:-2] + [first.node_sequence[-1]]),
                *mechanism.solution.routes[1:],
            ],
        )
        lost_probe = joint_feasibility_probe(lost, self.prepared.context)
        self.assertFalse(lost_probe["feasible"])
        self.assertIn("CUSTOMER_COVERAGE", lost_probe["violation_types"])
        duplicate = replace(
            mechanism.solution,
            routes=[
                replace(
                    first,
                    node_sequence=(
                        first.node_sequence[:-1]
                        + [first.node_sequence[1], first.node_sequence[-1]]
                    ),
                ),
                *mechanism.solution.routes[1:],
            ],
        )
        duplicate_probe = joint_feasibility_probe(
            duplicate,
            self.prepared.context,
        )
        self.assertFalse(duplicate_probe["feasible"])
        self.assertIn(
            "CUSTOMER_COVERAGE",
            duplicate_probe["violation_types"],
        )

        base = replace(
            self.prepared.counterfactual.solution,
            routes=[
                *self.prepared.counterfactual.solution.routes,
                Route("CV_SENTINEL#T1", "cv", "D0", ["D0", "D0"]),
            ],
        )
        drifted = replace(
            base,
            routes=[
                *base.routes[:-1],
                replace(base.routes[-1], home_depot_id="D1", node_sequence=["D1", "D1"]),
            ],
        )
        candidate = self.prepared.candidates[0]
        invariants = _candidate_invariants(
            base,
            drifted,
            candidate,
            self.prepared.context,
        )
        self.assertFalse(invariants["nonpair_routes_unchanged"])


if __name__ == "__main__":
    unittest.main()
