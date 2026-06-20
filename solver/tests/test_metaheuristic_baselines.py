from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.alns_crush import INSTANCE_DIRS
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.metaheuristic_baseline_runner import run_all, run_profile
from setp_solver.search.metaheuristic_baselines import BASELINE_ALGORITHMS, run_metaheuristic_baseline


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTANCE = REPO_ROOT / INSTANCE_DIRS["100-01-24h"]
SYSTEM_PYTHON = os.environ.get("SETP_WORKER_PYTHON", "/opt/anaconda3/bin/python3.13")
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

    def test_runner_writes_profile_and_convergence_outputs(self) -> None:
        old_workers = os.environ.get("SETP_META_PARALLEL_WORKERS")
        os.environ["SETP_META_PARALLEL_WORKERS"] = "1"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                profile = run_profile(
                    REPO_ROOT,
                    out / "profile",
                    instance="100-01-24h",
                    seed=1,
                    eval_budget=2,
                    max_runtime_seconds=120.0,
                    algorithms=["GA"],
                )
                self.assertEqual(profile["gate"], "PROFILE_COMPLETE")
                self.assertTrue((out / "profile" / "profile_report.md").exists())
                self.assertTrue((out / "profile" / "profile_timings.csv").exists())

                run = run_all(
                    REPO_ROOT,
                    out / "formal",
                    instances=["100-01-24h"],
                    seeds=[1],
                    eval_budget=2,
                    max_runtime_seconds=120.0,
                    algorithms=["GA"],
                )
                self.assertEqual(run["gate"], "OK")
                self.assertTrue((out / "formal" / "convergence_curves.csv").exists())
                self.assertTrue((out / "formal" / "comparison_table.csv").exists())
        finally:
            if old_workers is None:
                os.environ.pop("SETP_META_PARALLEL_WORKERS", None)
            else:
                os.environ["SETP_META_PARALLEL_WORKERS"] = old_workers

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
