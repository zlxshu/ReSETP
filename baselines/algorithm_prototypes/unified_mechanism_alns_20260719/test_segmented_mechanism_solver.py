"""Tests for the score-per-use segmented mechanism ALNS."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (REPO / "solver/src", REPO / "models/src", HERE, LEGACY, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from initial_pool import solution_signature_hash  # noqa: E402
from segmented_mechanism_solver import (  # noqa: E402
    SegmentedMechanismConfig,
    run_segmented_mechanism_alns,
)
from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    AVERAGED_SEGMENTED_ROULETTE_FLAG,
)
from setp_solver.algorithms.resetp_alns.runtime.select import (  # noqa: E402
    AveragedSegmentedRouletteWheel,
)
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from v7_responsibility_solver import run_mechanism_alns_v7  # noqa: E402


FIXTURE = REPO / "models/data_bundle/generated_instances/verify_20251113"
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)


class AveragedSegmentedRouletteTest(unittest.TestCase):
    def test_segment_update_uses_average_reward_not_total_reward(self) -> None:
        selector = AveragedSegmentedRouletteWheel(
            scores=[20.0, 8.0, 2.0, 0.05],
            reaction=1.0,
            segment_length=4,
            num_destroy=2,
            num_repair=1,
        )
        for _ in range(3):
            selector.update(None, 0, 0, 0)
        selector.update(None, 1, 0, 1)
        selector(np.random.default_rng(1), None, None)
        np.testing.assert_allclose(
            selector.destroy_weights,
            np.array([20.0, 8.0]),
        )
        self.assertEqual(selector.completed_segments, 1)


class SegmentedMechanismSolverTest(unittest.TestCase):
    def test_small_budgets_close(self) -> None:
        for budget in (0, 1, 2, 5):
            with self.subTest(budget=budget):
                result = run_segmented_mechanism_alns(
                    FIXTURE,
                    seed=1,
                    config=SegmentedMechanismConfig(
                        total_eval_budget=budget,
                        segment_length=2,
                    ),
                    prices=PRICES,
                )
                activity = result.mechanism_activity
                self.assertEqual(result.evaluations, budget)
                self.assertEqual(activity["candidate_scores"], budget)
                self.assertEqual(activity["actual_moves"], budget)
                self.assertEqual(
                    sum(
                        activity["destroy_selection_counts"].values()
                    ),
                    budget,
                )
                self.assertTrue(result.feasible)

    def test_disabled_control_matches_current_v7(self) -> None:
        control = run_segmented_mechanism_alns(
            FIXTURE,
            seed=1,
            config=SegmentedMechanismConfig(
                total_eval_budget=20,
                enable_segmented_roulette=False,
            ),
            prices=PRICES,
        )
        v7 = run_mechanism_alns_v7(
            FIXTURE,
            seed=1,
            eval_budget=20,
            prices=PRICES,
        )
        self.assertAlmostEqual(control.best_cost, v7.best_cost, places=7)
        self.assertEqual(
            solution_signature_hash(control.best_solution),
            solution_signature_hash(v7.best_solution),
        )

    def test_candidate_enables_only_the_segmented_selector(self) -> None:
        candidate = run_segmented_mechanism_alns(
            FIXTURE,
            seed=2,
            config=SegmentedMechanismConfig(
                total_eval_budget=7,
                segment_length=3,
            ),
            prices=PRICES,
        )
        activity = candidate.mechanism_activity
        self.assertEqual(
            activity["enabled_selector_flags"],
            [AVERAGED_SEGMENTED_ROULETTE_FLAG],
        )
        self.assertEqual(
            activity["selector_diagnostics"]["completed_segments"],
            2,
        )
        self.assertEqual(activity["search_restart_count"], 0)
        self.assertEqual(activity["hgs_calls"], 0)


if __name__ == "__main__":
    unittest.main()
