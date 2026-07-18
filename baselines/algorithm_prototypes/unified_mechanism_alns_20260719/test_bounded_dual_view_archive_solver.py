"""Regression tests for the bounded, non-feedback terminal archive."""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import bounded_dual_view_archive_solver as solver  # noqa: E402
from contextual_expert_fixtures import (  # noqa: E402
    PLATEAU_BUNDLE,
    PRICES_280,
    all_cv_plateau,
)
from fast_mechanism_completion import (  # noqa: E402
    apply_fast_route_local_completion,
)
from initial_pool import solution_signature_hash  # noqa: E402
from prototype import independent_cost  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import Solution  # noqa: E402


FIXTURE = (
    REPO
    / "models/data_bundle/generated_instances/verify_20251113"
)
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)


class BoundedDualViewArchiveSolverTest(unittest.TestCase):
    def test_exact_hash_distinguishes_rounded_signature_collision(self) -> None:
        original = all_cv_plateau()
        fast = apply_fast_route_local_completion(
            original,
            load_search_bundle(PLATEAU_BUNDLE),
            prices=PRICES_280,
        ).solution
        self.assertTrue(fast.charging_actions)
        changed_actions = list(fast.charging_actions)
        changed_actions[0] = replace(
            changed_actions[0],
            charge_start_second=(
                float(changed_actions[0].charge_start_second) + 1.0e-8
            ),
        )
        changed = Solution(
            routes=list(fast.routes),
            charging_actions=changed_actions,
            cross_site_services=list(fast.cross_site_services),
        )
        self.assertEqual(
            solution_signature_hash(fast),
            solution_signature_hash(changed),
        )
        self.assertNotEqual(
            solver._exact_solution_hash(fast),
            solver._exact_solution_hash(changed),
        )

    def test_even_sampling_is_bounded_and_result_blind(self) -> None:
        rows = [
            {"history_index": index, "raw_cost": 1000.0 - index}
            for index in range(30)
        ]
        sampled = solver._evenly_spaced(rows, solver.PRESCORE_CAPACITY)
        self.assertEqual(len(sampled), solver.PRESCORE_CAPACITY)
        self.assertEqual(sampled[0]["history_index"], 0)
        self.assertEqual(sampled[-1]["history_index"], 29)
        self.assertEqual(
            len({row["history_index"] for row in sampled}),
            solver.PRESCORE_CAPACITY,
        )

    def test_fast_completion_closes_and_is_idempotent(self) -> None:
        bundle = load_search_bundle(PLATEAU_BUNDLE)
        source = all_cv_plateau()
        source_cost = independent_cost(
            PLATEAU_BUNDLE,
            source,
            PRICES_280,
        )
        first = apply_fast_route_local_completion(
            source,
            bundle,
            prices=PRICES_280,
        )
        first_cost = independent_cost(
            PLATEAU_BUNDLE,
            first.solution,
            PRICES_280,
        )
        expected = (
            source_cost
            + float(first.activity["projected_objective_delta"])
        )
        self.assertAlmostEqual(first_cost, expected, places=7)
        self.assertTrue(first.changed)

        second = apply_fast_route_local_completion(
            first.solution,
            bundle,
            prices=PRICES_280,
        )
        second_cost = independent_cost(
            PLATEAU_BUNDLE,
            second.solution,
            PRICES_280,
        )
        self.assertFalse(second.changed)
        self.assertEqual(
            solver._exact_solution_hash(first.solution),
            solver._exact_solution_hash(second.solution),
        )
        self.assertAlmostEqual(first_cost, second_cost, places=7)

    def test_zero_budget_starts_no_archive_completion(self) -> None:
        result = solver.run_bounded_dual_view_archive_alns(
            FIXTURE,
            seed=1,
            config=solver.BoundedDualViewArchiveConfig(
                total_eval_budget=0,
                enable_archive=True,
            ),
            prices=PRICES,
        )
        activity = result.mechanism_activity
        self.assertEqual(result.evaluations, 0)
        self.assertTrue(activity["zero_budget_no_mechanism_completion"])
        self.assertEqual(activity["prescore_candidate_count"], 0)
        self.assertEqual(activity["archive_entry_count"], 0)
        self.assertEqual(activity["mechanism_candidate_evaluations"], 0)

    def test_archive_is_bounded_and_cannot_lose_to_ordinary_branch(self) -> None:
        control = solver.run_bounded_dual_view_archive_alns(
            FIXTURE,
            seed=1,
            config=solver.BoundedDualViewArchiveConfig(
                total_eval_budget=5,
                enable_archive=False,
            ),
            prices=PRICES,
        )
        candidate = solver.run_bounded_dual_view_archive_alns(
            FIXTURE,
            seed=1,
            config=solver.BoundedDualViewArchiveConfig(
                total_eval_budget=5,
                enable_archive=True,
            ),
            prices=PRICES,
        )
        left = control.mechanism_activity
        right = candidate.mechanism_activity
        for key in (
            "raw_search_cost",
            "raw_search_exact_signature",
            "raw_search_skeleton_signature",
            "main_search_history_fingerprint",
            "main_search_operator_fingerprint",
            "main_rng_final_state_sha256",
            "selector_rng_final_state_sha256",
        ):
            self.assertEqual(left[key], right[key])
        self.assertEqual(candidate.evaluations, 5)
        self.assertEqual(right["candidate_scores"], 5)
        self.assertEqual(right["actual_moves"], 5)
        self.assertEqual(right["mechanism_candidate_evaluations"], 0)
        self.assertLessEqual(
            right["archive_entry_count"],
            solver.ARCHIVE_CAPACITY,
        )
        self.assertLessEqual(
            right["prescore_candidate_count"],
            solver.PRESCORE_CAPACITY,
        )
        self.assertTrue(right["ordinary_final_forced"])
        self.assertLessEqual(
            candidate.best_cost,
            right["ordinary_final_completed_cost"] + 1.0e-9,
        )
        self.assertEqual(
            len(
                {
                    row["skeleton_signature"]
                    for row in right["archive_entries"]
                }
            ),
            right["archive_entry_count"],
        )
        self.assertTrue(
            all(
                "raw_solution_snapshot" in row
                and "completed_solution_snapshot" in row
                for row in right["archive_entries"]
            )
        )
        self.assertEqual(
            asdict(candidate.best_solution),
            next(
                row["completed_solution_snapshot"]
                for row in right["archive_entries"]
                if row["completed_exact_signature"]
                == solver._exact_solution_hash(candidate.best_solution)
            ),
        )


if __name__ == "__main__":
    unittest.main()
