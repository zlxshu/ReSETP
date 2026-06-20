from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path

import numpy as np

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.alns_crush import INSTANCE_DIRS
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.metaheuristic_baselines import BASELINE_ALGORITHMS, run_metaheuristic_baseline


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTANCE = REPO_ROOT / INSTANCE_DIRS["100-01-24h"]
SYSTEM_PYTHON = "/opt/anaconda3/bin/python3.13"
SYSTEM_NUMPY = "2.3.5"


class MetaheuristicBaselineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_search_bundle(INSTANCE)
        cls.warm = make_shared_initial_solution(cls.bundle)

    def test_gold_environment(self) -> None:
        self.assertEqual(str(Path(sys.executable)), SYSTEM_PYTHON)
        self.assertEqual(np.__version__, SYSTEM_NUMPY)

    def test_all_baselines_quick_budget(self) -> None:
        for algorithm in BASELINE_ALGORITHMS:
            with self.subTest(algorithm=algorithm):
                result = run_metaheuristic_baseline(
                    algorithm,
                    INSTANCE,
                    seed=1,
                    eval_budget=8,
                    max_runtime_seconds=120.0,
                    initial_solution=self.warm,
                )
                self.assertEqual(result.status, "OK")
                self.assertEqual(result.evals, 8)
                self.assertTrue(result.feasible)
                self.assertEqual(result.violation_count, 0)
                self.assertIsNotNone(result.best_solution)
                assert result.best_solution is not None
                self.assertEqual(check_solution(result.best_solution, self.bundle.instance, DEFAULT_PRICES), [])
                cost = evaluate(result.best_solution, self.bundle.instance, self.bundle.carbon_profile, DEFAULT_PRICES)["total_cost"]
                self.assertTrue(math.isfinite(float(cost)))

    @unittest.skipUnless(os.environ.get("SETP_RUN_SLOW_BASELINES") == "1", "set SETP_RUN_SLOW_BASELINES=1 to run 16000-eval baseline checks")
    def test_all_baselines_slow_full_budget(self) -> None:
        for algorithm in BASELINE_ALGORITHMS:
            with self.subTest(algorithm=algorithm):
                result = run_metaheuristic_baseline(
                    algorithm,
                    INSTANCE,
                    seed=1,
                    eval_budget=16_000,
                    max_runtime_seconds=900.0,
                    initial_solution=self.warm,
                )
                self.assertEqual(result.status, "OK")
                self.assertEqual(result.evals, 16_000)
                self.assertTrue(result.feasible)
                self.assertEqual(result.violation_count, 0)
                self.assertIsNotNone(result.best_solution)


if __name__ == "__main__":
    unittest.main()
