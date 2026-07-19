"""Regression tests for the passive mechanism-aware elite archive."""

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
from mechanism_elite_solver import (  # noqa: E402
    MechanismEliteConfig,
    run_mechanism_elite_alns,
)
from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    WinnerKernelConfig,
    run_winner_kernel,
)
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from v7_responsibility_solver import run_mechanism_alns_v7  # noqa: E402


FIXTURE = REPO / "models/data_bundle/generated_instances/verify_20251113"
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)


def _scalar_history(rows):
    return [
        {
            key: row[key]
            for key in ("eval", "best_cost", "best_obj", "operator")
        }
        for row in rows
    ]


def _stable_counts(result):
    return {
        key: value
        for key, value in result["operator_counts"].items()
        if key not in {
            "timing",
            "candidate_trace",
            "final_rng_state",
        }
    }


class MechanismEliteSolverTest(unittest.TestCase):
    def test_capture_switch_does_not_change_main_search(self) -> None:
        common = {
            "seed": 1,
            "eval_budget": 7,
            "max_runtime_seconds": 3600.0,
            "require_charging_signal": False,
        }
        plain = run_winner_kernel(
            FIXTURE,
            config=WinnerKernelConfig(
                **common,
                capture_best_solutions=False,
            ),
            prices=PRICES,
        )
        captured = run_winner_kernel(
            FIXTURE,
            config=WinnerKernelConfig(
                **common,
                capture_best_solutions=True,
            ),
            prices=PRICES,
        )
        self.assertEqual(plain["evaluations"], captured["evaluations"])
        self.assertEqual(plain["best_cost"], captured["best_cost"])
        self.assertEqual(
            solution_signature_hash(plain["best_solution"]),
            solution_signature_hash(captured["best_solution"]),
        )
        self.assertEqual(
            _scalar_history(plain["history"]),
            _scalar_history(captured["history"]),
        )
        self.assertEqual(_stable_counts(plain), _stable_counts(captured))
        self.assertTrue(
            all(
                "solution_snapshot" in row
                for row in captured["history"]
            )
        )
        self.assertTrue(
            all(
                "solution_snapshot" not in row
                for row in plain["history"]
            )
        )

    def test_archive_is_monotone_and_does_not_change_raw_trajectory(self) -> None:
        disabled = run_mechanism_elite_alns(
            FIXTURE,
            seed=1,
            config=MechanismEliteConfig(
                total_eval_budget=7,
                enable_archive=False,
            ),
            prices=PRICES,
        )
        enabled = run_mechanism_elite_alns(
            FIXTURE,
            seed=1,
            config=MechanismEliteConfig(
                total_eval_budget=7,
                enable_archive=True,
            ),
            prices=PRICES,
        )
        self.assertEqual(disabled.evaluations, 7)
        self.assertEqual(enabled.evaluations, 7)
        for field in (
            "main_search_final_signature",
            "main_search_history_fingerprint",
            "main_search_operator_fingerprint",
            "main_search_final_rng_fingerprint",
        ):
            self.assertEqual(
                disabled.mechanism_activity[field],
                enabled.mechanism_activity[field],
            )
        self.assertLessEqual(
            enabled.best_cost,
            disabled.best_cost + 1.0e-9,
        )

    def test_archive_disabled_matches_current_v7(self) -> None:
        disabled = run_mechanism_elite_alns(
            FIXTURE,
            seed=1,
            config=MechanismEliteConfig(
                total_eval_budget=20,
                enable_archive=False,
            ),
            prices=PRICES,
        )
        v7 = run_mechanism_alns_v7(
            FIXTURE,
            seed=1,
            eval_budget=20,
            prices=PRICES,
        )
        self.assertAlmostEqual(disabled.best_cost, v7.best_cost, places=7)
        self.assertEqual(
            solution_signature_hash(disabled.best_solution),
            solution_signature_hash(v7.best_solution),
        )


if __name__ == "__main__":
    unittest.main()
