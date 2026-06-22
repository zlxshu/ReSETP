from __future__ import annotations

import math
import os
import tempfile
import unittest
from pathlib import Path

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.e2_alns_throughput import _task, _timeout_row, _write_checkpoint, run_smoke
from setp_solver.search.repair_scoring import route_model_cost
from setp_solver.search.evaluation import EvaluationContext
from setp_solver.search.winner_operators import (
    WinnerKernelConfig,
    e2_alns_throughput_flags,
    run_e2_alns_throughput,
    winner_variant_flags,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SMALL_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/e2_benchmark/vanilla/e2-vanilla-10c-01"


class E2AlnsThroughputTest(unittest.TestCase):
    def test_legacy_flags_keep_throughput_diagnostics_off(self) -> None:
        flags = winner_variant_flags()

        self.assertEqual(flags["SETP_ALNS_CRUSH_ROUTE_COST_CACHE"], "0")
        self.assertEqual(flags["SETP_ALNS_CRUSH_TIMING_LEDGER"], "0")

        throughput = e2_alns_throughput_flags()
        self.assertEqual(throughput["SETP_ALNS_CRUSH_SA_MODE"], "lns_cooling")
        self.assertEqual(throughput["SETP_ALNS_CRUSH_ROUTE_COST_CACHE"], "1")
        self.assertEqual(throughput["SETP_ALNS_CRUSH_REPAIR_STRUCTURE_CACHE"], "1")
        self.assertEqual(throughput["SETP_ALNS_CRUSH_TIMING_LEDGER"], "1")

    def test_route_cost_cache_matches_uncached_route_cost(self) -> None:
        bundle = load_search_bundle(SMALL_BUNDLE)
        solution = make_shared_initial_solution(bundle)
        route = solution.routes[0]
        context = EvaluationContext(bundle.instance, bundle.carbon_profile)
        old = os.environ.get("SETP_ALNS_CRUSH_ROUTE_COST_CACHE")
        try:
            os.environ["SETP_ALNS_CRUSH_ROUTE_COST_CACHE"] = "0"
            uncached = route_model_cost(route, solution.charging_actions, context)
            os.environ["SETP_ALNS_CRUSH_ROUTE_COST_CACHE"] = "1"
            cached = route_model_cost(route, solution.charging_actions, context)
            cached_again = route_model_cost(route, solution.charging_actions, context)
        finally:
            if old is None:
                os.environ.pop("SETP_ALNS_CRUSH_ROUTE_COST_CACHE", None)
            else:
                os.environ["SETP_ALNS_CRUSH_ROUTE_COST_CACHE"] = old

        self.assertAlmostEqual(uncached, cached)
        self.assertAlmostEqual(cached, cached_again)

    def test_timeout_row_returns_finite_checkpoint_incumbent(self) -> None:
        bundle = load_search_bundle(SMALL_BUNDLE)
        warm = make_shared_initial_solution(bundle)
        warm_cost = float(evaluate(warm, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)["total_cost"])
        with tempfile.TemporaryDirectory() as tmp:
            task = _task(REPO_ROOT, Path(tmp), "vanilla", "e2-vanilla-10c-01", "LNS", 1, 32, 0.001)
            _write_checkpoint(Path(task["checkpoint_path"]), warm, best_cost=warm_cost, best_obj=warm_cost, eval_count=0, elapsed_seconds=0.0, operator="shared_warm_start")
            row = _timeout_row(task, elapsed=1.0, stdout="", stderr="")

        self.assertEqual(row["status"], "HALT_HARD_TIMEOUT_WITH_INCUMBENT")
        self.assertTrue(math.isfinite(float(row["best_cost"])))
        self.assertEqual(row["violation_count"], 0)

    def test_e2_alns_throughput_same_seed_small_budget_is_deterministic(self) -> None:
        config = WinnerKernelConfig(seed=11, eval_budget=16, max_runtime_seconds=120.0)

        first = run_e2_alns_throughput(SMALL_BUNDLE, config=config)
        second = run_e2_alns_throughput(SMALL_BUNDLE, config=config)

        self.assertEqual(first["violation_count"], 0)
        self.assertEqual(second["violation_count"], 0)
        self.assertAlmostEqual(first["best_cost"], second["best_cost"])
        self.assertEqual(first["evaluations"], second["evaluations"])
        self.assertTrue(first["timings"])

    def test_runner_smoke_outputs_finite_zero_violation_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_smoke(REPO_ROOT, Path(tmp))

        self.assertEqual(result["gate"], "SMOKE_OK")


if __name__ == "__main__":
    unittest.main()
