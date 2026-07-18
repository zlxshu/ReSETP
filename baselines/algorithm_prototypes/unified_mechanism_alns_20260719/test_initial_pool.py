from __future__ import annotations

from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (REPO / "solver/src", REPO / "models/src", HERE, LEGACY, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from initial_pool import (  # noqa: E402
    POOL_SIZE,
    build_and_score_initial_pool,
    build_blueprints,
    edge_distance,
    solution_signature_hash,
)
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import CrossSiteService, Solution  # noqa: E402
from terminal_completion import apply_terminal_completion  # noqa: E402


VERIFY = REPO / "models/data_bundle/generated_instances/verify_20251113"


class InitialPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_search_bundle(VERIFY)
        cls.first = build_and_score_initial_pool(
            VERIFY,
            seed=1,
            archive_capacity=6,
        )

    def test_frozen_menu_and_budget_close_exactly(self) -> None:
        blueprints = build_blueprints(self.bundle, seed=1)
        self.assertEqual(len(blueprints), POOL_SIZE)
        self.assertEqual(self.first.anchor.label, "default_regret2")
        self.assertEqual(self.first.candidate_evaluations, POOL_SIZE - 1)
        self.assertEqual(self.first.reference_replays, 1)
        self.assertEqual(
            self.first.score_counts["candidate_channel:initial_pool_choice"],
            POOL_SIZE - 1,
        )

    def test_every_start_is_complete_feasible_and_pool_is_diverse(self) -> None:
        self.assertEqual(len(self.first.entries), POOL_SIZE)
        self.assertTrue(all(item.feasible for item in self.first.entries))
        self.assertTrue(all(item.violation_count == 0 for item in self.first.entries))
        self.assertGreaterEqual(
            len({item.route_signature for item in self.first.entries}),
            6,
        )
        self.assertGreaterEqual(
            len({item.family for item in self.first.archive}),
            2,
        )

    def test_fixed_seed_is_bitwise_deterministic(self) -> None:
        second = build_and_score_initial_pool(
            VERIFY,
            seed=1,
            archive_capacity=6,
        )
        self.assertEqual(
            [item.full_signature for item in self.first.entries],
            [item.full_signature for item in second.entries],
        )
        self.assertEqual(
            [item.raw_cost for item in self.first.entries],
            [item.raw_cost for item in second.entries],
        )
        self.assertEqual(
            [item.label for item in self.first.archive],
            [item.label for item in second.archive],
        )

    def test_distance_and_signature_cover_full_solution_identity(self) -> None:
        left = self.first.entries[0].solution
        right = self.first.entries[1].solution
        self.assertGreaterEqual(edge_distance(left, right, self.bundle.instance), 0.0)
        self.assertLessEqual(edge_distance(left, right, self.bundle.instance), 1.0)
        changed = Solution(
            routes=list(left.routes),
            charging_actions=list(left.charging_actions),
            cross_site_services=[
                *left.cross_site_services,
                CrossSiteService("synthetic-customer", "synthetic-depot"),
            ],
        )
        self.assertNotEqual(
            solution_signature_hash(left),
            solution_signature_hash(changed),
        )

    def test_common_terminal_completion_is_monotone_for_both_arms(self) -> None:
        anchor = apply_terminal_completion(VERIFY, self.first.anchor.solution)
        winner = apply_terminal_completion(VERIFY, self.first.best.solution)
        self.assertTrue(anchor.feasible)
        self.assertTrue(winner.feasible)
        self.assertLessEqual(anchor.cost, anchor.source_cost + 1.0e-9)
        self.assertLessEqual(winner.cost, winner.source_cost + 1.0e-9)
        self.assertEqual(
            anchor.activity["complete_route_search_evaluations"],
            0,
        )
        self.assertEqual(
            winner.activity["complete_route_search_evaluations"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
