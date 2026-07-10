from __future__ import annotations

import builtins
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

from setp_solver.search.alns_crush import INSTANCE_DIRS
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.winner_operators import WinnerKernelConfig, run_winner_kernel


REPO_ROOT = Path(__file__).resolve().parents[2]


class _State:
    def __init__(self, objective: float) -> None:
        self._objective = float(objective)

    def objective(self) -> float:
        return self._objective


class ResetpAlnsIndependenceTest(unittest.TestCase):
    def test_resetp_alns_acceptance_and_selector_semantics(self) -> None:
        from setp_solver.search.resetp_alns import (
            AlphaUCB,
            HillClimbing,
            Outcome,
            RecordToRecordTravel,
            SimulatedAnnealing,
        )

        rng = np.random.default_rng(1)
        best = _State(90.0)
        current = _State(100.0)

        hill = HillClimbing()
        self.assertTrue(hill(rng, best, current, _State(99.0)))
        self.assertTrue(hill(rng, best, current, _State(100.0)))
        self.assertFalse(hill(rng, best, current, _State(101.0)))

        rrt = RecordToRecordTravel(10.0, 0.0, 5.0, method="linear", cmp_best=False)
        self.assertTrue(rrt(rng, best, current, _State(109.0)))
        self.assertFalse(rrt(rng, best, current, _State(106.0)))
        self.assertEqual(rrt.method, "linear")

        sa = SimulatedAnnealing(10.0, 1.0, 0.5, method="exponential")
        self.assertTrue(sa(rng, best, current, _State(99.0)))
        self.assertEqual(sa.method, "exponential")

        selector = AlphaUCB([20.0, 8.0, 2.0, 0.05], alpha=0.08, num_destroy=2, num_repair=2)
        self.assertEqual(selector(rng, best, current), (0, 0))
        selector.update(_State(99.0), 0, 0, Outcome.BEST)
        self.assertEqual(selector(rng, best, current), (0, 0))

    def test_main_alns_paths_have_no_n_wouda_runtime_imports(self) -> None:
        pattern = re.compile(r"from alns|import alns|ALNS-7\\.0\\.0@N-Wouda|_ensure_local_alns_on_path")
        for rel in [
            "solver/src/setp_solver/search/alns_wouda.py",
            "solver/src/setp_solver/search/winner_operators.py",
            "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
            "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
        ]:
            with self.subTest(path=rel):
                text = (REPO_ROOT / rel).read_text(encoding="utf-8")
                # Match real third-party imports only (not alns_core / alns_wouda identifiers).
                strict = re.compile(r"(from alns(?:\.|\s)|import alns(?:\.|\s|$)|ALNS-7\.0\.0@N-Wouda|_ensure_local_alns_on_path)")
                self.assertIsNone(strict.search(text))

    def test_winner_kernel_runs_when_external_alns_import_is_blocked(self) -> None:
        original_import = builtins.__import__
        for key in list(sys.modules):
            if key == "alns" or key.startswith("alns."):
                sys.modules.pop(key, None)

        def guarded_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "alns" or name.startswith("alns."):
                raise AssertionError(f"external N-Wouda ALNS import attempted: {name}")
            return original_import(name, *args, **kwargs)

        bundle = REPO_ROOT / INSTANCE_DIRS["L-main-threeshift-10c-01"]
        config = WinnerKernelConfig(seed=1, eval_budget=4, max_runtime_seconds=120.0)
        with mock.patch.object(builtins, "__import__", side_effect=guarded_import):
            result = run_winner_kernel(bundle, config=config)

        self.assertTrue(result["feasible"])
        self.assertEqual(result["violation_count"], 0)
        self.assertGreaterEqual(result["evaluations"], 4)

    def test_dr_entry_calls_the_lazy_candidate_runner_once(self) -> None:
        from setp_solver.algorithms.resetp_alns.kernel import winner

        bundle_dir = REPO_ROOT / INSTANCE_DIRS["L-main-threeshift-10c-01"]
        warm = make_shared_initial_solution(load_search_bundle(bundle_dir))
        calls: list[tuple[str, Path]] = []

        def fake_runner(algorithm: str, selected_bundle: Path, **kwargs: object) -> SimpleNamespace:
            _ = kwargs
            calls.append((algorithm, Path(selected_bundle)))
            return SimpleNamespace(best_solution=warm, evals=4)

        config = WinnerKernelConfig(algorithm="DR-ALNS", seed=1, eval_budget=4, max_runtime_seconds=120.0)
        with mock.patch.object(winner, "_lazy_run_candidate", return_value=fake_runner):
            result = run_winner_kernel(bundle_dir, config=config, initial_solution=warm)

        self.assertTrue(result["feasible"])
        self.assertEqual(calls, [("DR-ALNS", bundle_dir)])
