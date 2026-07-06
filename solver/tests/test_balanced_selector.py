from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from setp_solver.search.alns_wouda import _make_operator_selector
from setp_solver.search.resetp_alns import AlphaUCB, BalancedAlphaUCB
from setp_solver.search.winner_operators import (
    BALANCED_SELECTOR_FLAG,
    STRONG_BRIDGE_BACKEND_FLAG,
    WinnerKernelConfig,
    _run_winner_variant,
    e2_alns_throughput_flags,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/verify_20251113"


class BalancedSelectorTests(unittest.TestCase):
    def test_make_operator_selector_returns_legacy_alpha_ucb_by_default(self) -> None:
        selector = _make_operator_selector(2, 2)

        self.assertIsInstance(selector, AlphaUCB)
        self.assertNotIsInstance(selector, BalancedAlphaUCB)

    def test_balanced_selector_warmup_covers_every_pair_ten_times(self) -> None:
        selector = BalancedAlphaUCB([20.0, 8.0, 2.0, 0.05], alpha=0.08, num_destroy=2, num_repair=2, warmup_per_pair=10, epsilon=0.0)
        rng = np.random.default_rng(7)
        counts: dict[tuple[int, int], int] = {}

        for _ in range(40):
            pair = selector(rng, None, None)
            counts[pair] = counts.get(pair, 0) + 1
            selector.update(None, pair[0], pair[1], 3)

        self.assertEqual(counts, {(0, 0): 10, (0, 1): 10, (1, 0): 10, (1, 1): 10})

    def test_balanced_selector_epsilon_respects_coupling_and_seed_determinism(self) -> None:
        coupling = np.array([[True, False], [True, True]])
        first = BalancedAlphaUCB([20.0, 8.0, 2.0, 0.05], alpha=0.08, num_destroy=2, num_repair=2, op_coupling=coupling, warmup_per_pair=0, epsilon=1.0)
        second = BalancedAlphaUCB([20.0, 8.0, 2.0, 0.05], alpha=0.08, num_destroy=2, num_repair=2, op_coupling=coupling, warmup_per_pair=0, epsilon=1.0)
        rng_a = np.random.default_rng(99)
        rng_b = np.random.default_rng(99)

        seq_a = [first(rng_a, None, None) for _ in range(20)]
        seq_b = [second(rng_b, None, None) for _ in range(20)]

        self.assertEqual(seq_a, seq_b)
        self.assertNotIn((0, 1), seq_a)

    def test_balanced_flag_defaults_off_and_does_not_enable_backend_or_local_search_by_itself(self) -> None:
        flags = e2_alns_throughput_flags()

        self.assertEqual(flags[BALANCED_SELECTOR_FLAG], "0")
        self.assertEqual(flags[STRONG_BRIDGE_BACKEND_FLAG], "0")

    def test_balanced_selector_trace_changes_pair_distribution_without_backend_flag(self) -> None:
        flags = e2_alns_throughput_flags()
        flags[BALANCED_SELECTOR_FLAG] = "1"
        flags["SETP_ALNS_CRUSH_TRACE_DIAGNOSTIC"] = "1"
        flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"] = "1"

        with patch.dict(os.environ, {}, clear=False):
            result = _run_winner_variant(
                VERIFY_BUNDLE,
                config=WinnerKernelConfig(
                    seed=11,
                    eval_budget=24,
                    max_runtime_seconds=120.0,
                ),
                initial_solution=None,
                variant_flags=flags,
                variant_id="unit_balanced_selector",
            )

        traces = result["operator_counts"]["candidate_trace"]
        self.assertTrue(traces)
        self.assertEqual(result["flags"][BALANCED_SELECTOR_FLAG], "1")
        self.assertEqual(result["flags"][STRONG_BRIDGE_BACKEND_FLAG], "0")
        self.assertTrue(all(row["candidate_backend"] == "winner_operator_set" for row in traces))

    def test_probe_profiles_are_a0_a4_and_lns_reference(self) -> None:
        from baselines.e2_alns import balanced_selector_probe as probe

        with tempfile.TemporaryDirectory() as tmp:
            tasks = probe.build_probe_tasks(
                Path(tmp),
                [{"category": "vanilla", "instance": "e2-vanilla-10c-01"}],
                seeds=[1],
                eval_budget=4000,
                runtime_cap_seconds=900.0,
            )

        self.assertEqual(
            [task["profile"] for task in tasks],
            ["A0_MAIN_LOCAL_SEARCH", "A4_BALANCED_SELECTOR_LOCAL_SEARCH", "LNS_TRACE_REFERENCE"],
        )
        self.assertEqual(probe.profile_flags("A4_BALANCED_SELECTOR_LOCAL_SEARCH")[BALANCED_SELECTOR_FLAG], "1")
        self.assertEqual(probe.profile_flags("A4_BALANCED_SELECTOR_LOCAL_SEARCH")["SETP_ALNS_CRUSH_LOCAL_SEARCH"], "1")
        self.assertEqual(probe.profile_flags("A4_BALANCED_SELECTOR_LOCAL_SEARCH")[STRONG_BRIDGE_BACKEND_FLAG], "0")


if __name__ == "__main__":
    unittest.main()
