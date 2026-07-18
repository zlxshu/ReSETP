"""Unit and one-call integration tests for the dual-basin solver."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (REPO / "solver/src", REPO / "models/src", HERE, LEGACY, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import dual_basin_solver as solver  # noqa: E402
from fast_mechanism_completion import (  # noqa: E402
    apply_fast_route_local_completion,
)
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from terminal_completion import CompletionResult  # noqa: E402


FIXTURE = (
    REPO
    / "models/data_bundle/generated_instances/verify_20251113"
)
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)


class DualBasinSolverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_search_bundle(FIXTURE)
        cls.warm = solver.build_v7_warm(cls.bundle, prices=PRICES)
        cls.fast = apply_fast_route_local_completion(
            cls.warm,
            cls.bundle,
            prices=PRICES,
        ).solution

    def _fake_hgs(self, bundle, warm, **kwargs):
        return warm, {
            "official_commit": "mock",
            "native_calls": 0,
            "native_cpu_seconds": 0.0,
            "wall_seconds": 0.0,
        }

    def _fake_phase(
        self,
        bundle_dir,
        *,
        initial_solution,
        seed,
        eval_budget,
        prices,
        runtime_cap,
    ):
        cost = float(
            evaluate(
                initial_solution,
                self.bundle.instance,
                self.bundle.carbon_profile,
                prices,
            )["total_cost"]
        )
        return {
            "solution": initial_solution,
            "cost": cost,
            "activity": {
                "seed": int(seed),
                "eval_budget": int(eval_budget),
                "evaluations": int(eval_budget),
                "elapsed_seconds": 0.0,
                "history_length": 0,
                "operator_counts": {},
            },
        }

    def _completion(self, solution, prices) -> CompletionResult:
        source_cost = float(
            evaluate(
                solution,
                self.bundle.instance,
                self.bundle.carbon_profile,
                prices,
            )["total_cost"]
        )
        if solver.solution_signature_hash(solution) == solver.solution_signature_hash(
            self.warm
        ):
            completed = self.fast
        else:
            completed = solution
        completed_cost = float(
            evaluate(
                completed,
                self.bundle.instance,
                self.bundle.carbon_profile,
                prices,
            )["total_cost"]
        )
        return CompletionResult(
            solution=completed,
            cost=completed_cost,
            source_cost=source_cost,
            feasible=True,
            selected_branch="test",
            activity={},
        )

    def test_zero_budget_does_not_start_hgs(self) -> None:
        with patch.object(
            solver,
            "_build_hgs_raw",
            side_effect=AssertionError("HGS must not run at B=0"),
        ):
            result = solver.run_dual_basin_mechanism_alns(
                FIXTURE,
                seed=1,
                config=solver.DualBasinConfig(total_eval_budget=0),
                prices=PRICES,
            )
        self.assertEqual(result.evaluations, 0)
        self.assertTrue(result.feasible)
        self.assertEqual(
            result.mechanism_activity["hgs_native_calls"],
            0,
        )

    def test_small_and_main_budgets_close_when_mid_is_noop(self) -> None:
        def no_op_completion(bundle_dir, solution, *, prices):
            value = float(
                evaluate(
                    solution,
                    self.bundle.instance,
                    self.bundle.carbon_profile,
                    prices,
                )["total_cost"]
            )
            return CompletionResult(
                solution=solution,
                cost=value,
                source_cost=value,
                feasible=True,
                selected_branch="test_noop",
                activity={},
            )

        with (
            patch.object(solver, "_build_hgs_raw", self._fake_hgs),
            patch.object(solver, "_run_alns_phase", self._fake_phase),
            patch.object(
                solver,
                "apply_terminal_completion",
                no_op_completion,
            ),
        ):
            for budget in (1, 2, 3, 4, 7, 100):
                with self.subTest(budget=budget):
                    result = solver.run_dual_basin_mechanism_alns(
                        FIXTURE,
                        seed=1,
                        config=solver.DualBasinConfig(
                            total_eval_budget=budget
                        ),
                        prices=PRICES,
                    )
                    self.assertEqual(result.evaluations, budget)
                    self.assertEqual(
                        result.mechanism_activity[
                            "total_candidate_evaluations"
                        ],
                        budget,
                    )
                    self.assertTrue(result.feasible)
            main = solver.run_dual_basin_mechanism_alns(
                FIXTURE,
                seed=1,
                config=solver.DualBasinConfig(total_eval_budget=100),
                prices=PRICES,
            )
        self.assertEqual(
            [
                row["eval_budget"]
                for row in main.mechanism_activity["alns_phases"]
            ],
            [68, 31],
        )
        self.assertEqual(
            main.mechanism_activity["mid_candidate_evaluations"],
            0,
        )

    def test_changed_middle_is_charged_exactly_once(self) -> None:
        def changing_completion(bundle_dir, solution, *, prices):
            return self._completion(solution, prices)

        with (
            patch.object(solver, "_build_hgs_raw", self._fake_hgs),
            patch.object(solver, "_run_alns_phase", self._fake_phase),
            patch.object(
                solver,
                "apply_terminal_completion",
                changing_completion,
            ),
        ):
            result = solver.run_dual_basin_mechanism_alns(
                FIXTURE,
                seed=1,
                config=solver.DualBasinConfig(total_eval_budget=100),
                prices=PRICES,
            )
        self.assertEqual(result.evaluations, 100)
        self.assertEqual(
            [
                row["eval_budget"]
                for row in result.mechanism_activity["alns_phases"]
            ],
            [68, 30],
        )
        self.assertTrue(result.mechanism_activity["middle"]["changed"])
        self.assertEqual(
            result.mechanism_activity["mid_candidate_evaluations"],
            1,
        )

    def test_raw_selector_is_explicitly_labelled_ablation(self) -> None:
        with (
            patch.object(solver, "_build_hgs_raw", self._fake_hgs),
            patch.object(solver, "_run_alns_phase", self._fake_phase),
        ):
            result = solver.run_dual_basin_mechanism_alns(
                FIXTURE,
                seed=1,
                config=solver.DualBasinConfig(
                    total_eval_budget=2,
                    selector_mode=solver.SELECTOR_RAW,
                ),
                prices=PRICES,
            )
        self.assertEqual(result.algorithm, "raw_cost_dual_basin_ablation")
        self.assertEqual(result.evaluations, 2)

    def test_real_official_hgs_one_candidate_is_deterministic(self) -> None:
        first = solver.run_dual_basin_mechanism_alns(
            FIXTURE,
            seed=1,
            config=solver.DualBasinConfig(total_eval_budget=1),
            prices=PRICES,
        )
        second = solver.run_dual_basin_mechanism_alns(
            FIXTURE,
            seed=1,
            config=solver.DualBasinConfig(total_eval_budget=1),
            prices=PRICES,
        )
        self.assertEqual(first.evaluations, 1)
        self.assertEqual(first.best_cost, second.best_cost)
        self.assertEqual(
            solver.solution_signature_hash(first.best_solution),
            solver.solution_signature_hash(second.best_solution),
        )
        self.assertEqual(first.selected_basin, second.selected_basin)
        self.assertGreater(
            first.mechanism_activity["hgs_native"]["native_calls"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
