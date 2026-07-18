"""Regression tests for the mechanism-balanced softmax ALNS candidate."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (REPO / "solver/src", REPO / "models/src", HERE, LEGACY, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from initial_pool import solution_signature_hash  # noqa: E402
from prototype import independent_cost  # noqa: E402
from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    SELECTOR_FLAGS,
    SOFTMAX_SELECTOR_FLAG,
)
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from softmax_mechanism_solver import (  # noqa: E402
    SoftmaxMechanismConfig,
    run_softmax_mechanism_alns,
)
from v7_responsibility_solver import run_mechanism_alns_v7  # noqa: E402


FIXTURE = REPO / "models/data_bundle/generated_instances/verify_20251113"
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)


class SoftmaxMechanismSolverTest(unittest.TestCase):
    def test_small_complete_candidate_budgets_close_exactly(self) -> None:
        for budget in (0, 1, 2, 5):
            with self.subTest(budget=budget):
                result = run_softmax_mechanism_alns(
                    FIXTURE,
                    seed=1,
                    config=SoftmaxMechanismConfig(
                        total_eval_budget=budget,
                    ),
                    prices=PRICES,
                )
                activity = result.mechanism_activity
                self.assertEqual(result.evaluations, budget)
                self.assertEqual(
                    activity["complete_search_candidate_evaluations"],
                    budget,
                )
                self.assertEqual(activity["alns_actual_moves"], budget)
                self.assertEqual(
                    sum(
                        activity["destroy_selection_counts"].values()
                    ),
                    budget,
                )
                self.assertTrue(result.feasible)
                self.assertAlmostEqual(
                    result.best_cost,
                    independent_cost(
                        FIXTURE,
                        result.best_solution,
                        PRICES,
                    ),
                    places=7,
                )

    def test_default_control_is_exact_current_v7(self) -> None:
        control = run_softmax_mechanism_alns(
            FIXTURE,
            seed=1,
            config=SoftmaxMechanismConfig(
                total_eval_budget=20,
                enable_softmax=False,
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
        self.assertEqual(
            control.mechanism_activity["enabled_selector_flags"],
            [],
        )

    def test_candidate_enables_only_softmax_selector(self) -> None:
        candidate = run_softmax_mechanism_alns(
            FIXTURE,
            seed=1,
            config=SoftmaxMechanismConfig(
                total_eval_budget=7,
                enable_softmax=True,
            ),
            prices=PRICES,
        )
        activity = candidate.mechanism_activity
        self.assertEqual(
            activity["enabled_selector_flags"],
            [SOFTMAX_SELECTOR_FLAG],
        )
        flags = activity["all_variant_flags"]
        for selector_flag in SELECTOR_FLAGS:
            self.assertEqual(
                flags[selector_flag],
                "1" if selector_flag == SOFTMAX_SELECTOR_FLAG else "0",
            )
        self.assertEqual(activity["search_restart_count"], 0)
        self.assertEqual(activity["hgs_calls"], 0)
        self.assertEqual(activity["alns_actual_moves"], 7)

    def test_split_selector_stream_is_reproducible(self) -> None:
        config = SoftmaxMechanismConfig(
            total_eval_budget=20,
            enable_softmax=True,
            split_selector_rng=True,
        )
        first = run_softmax_mechanism_alns(
            FIXTURE,
            seed=3,
            config=config,
            prices=PRICES,
        )
        second = run_softmax_mechanism_alns(
            FIXTURE,
            seed=3,
            config=config,
            prices=PRICES,
        )
        self.assertEqual(first.best_cost, second.best_cost)
        self.assertEqual(
            solution_signature_hash(first.best_solution),
            solution_signature_hash(second.best_solution),
        )
        for field in (
            "main_search_history_fingerprint",
            "destroy_selection_counts",
            "repair_selection_counts",
            "selector_diagnostics",
        ):
            self.assertEqual(
                first.mechanism_activity[field],
                second.mechanism_activity[field],
            )


if __name__ == "__main__":
    unittest.main()
