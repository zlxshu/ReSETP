from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from setp_solver.search.alns_wouda import _make_operator_selector
from setp_solver.search.resetp_alns import (
    AlphaUCB,
    BalancedAlphaUCB,
    EpsilonDecayAlphaUCB,
    MinimumCoverageAlphaUCB,
    SoftmaxAlphaUCB,
    ThompsonPairSelector,
)
from setp_solver.search.winner_operators import (
    BALANCED_SELECTOR_FLAG,
    EPS_DECAY_SELECTOR_FLAG,
    MINIMUM_COVERAGE_SELECTOR_FLAG,
    SOFTMAX_SELECTOR_FLAG,
    STRONG_BRIDGE_BACKEND_FLAG,
    THOMPSON_SELECTOR_FLAG,
    TRACE_DIAGNOSTIC_FLAG,
    WinnerKernelConfig,
    _run_winner_variant,
    _selector_kind_from_flags,
    e2_alns_throughput_flags,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/verify_20251113"


class SelectorSprintSelectorTests(unittest.TestCase):
    def test_make_operator_selector_keeps_legacy_alpha_ucb_by_default(self) -> None:
        first = _make_operator_selector(2, 2)
        second = _make_operator_selector(2, 2)
        rng_a = np.random.default_rng(123)
        rng_b = np.random.default_rng(123)

        self.assertIsInstance(first, AlphaUCB)
        self.assertNotIsInstance(first, BalancedAlphaUCB)
        self.assertEqual(first(rng_a, None, None), second(rng_b, None, None))

    def test_selector_flags_are_mutually_exclusive(self) -> None:
        flags = e2_alns_throughput_flags()
        flags[BALANCED_SELECTOR_FLAG] = "1"
        flags[EPS_DECAY_SELECTOR_FLAG] = "1"

        with self.assertRaisesRegex(ValueError, "HALT_CONFIG_CONFLICT_SELECTOR_FLAGS"):
            _selector_kind_from_flags(flags)

    def test_minimum_coverage_flag_selects_the_new_diagnostic_scheduler(self) -> None:
        flags = e2_alns_throughput_flags()
        flags[MINIMUM_COVERAGE_SELECTOR_FLAG] = "1"

        self.assertEqual(_selector_kind_from_flags(flags), "minimum_coverage")

    def test_epsilon_decay_selector_warmup_and_decay_are_deterministic(self) -> None:
        selector = EpsilonDecayAlphaUCB(
            [20.0, 8.0, 2.0, 0.05],
            alpha=0.08,
            num_destroy=2,
            num_repair=2,
            warmup_per_pair=2,
            epsilon_start=0.15,
            epsilon_end=0.02,
            target_iterations=10,
        )
        rng = np.random.default_rng(7)
        counts: dict[tuple[int, int], int] = {}

        for _ in range(8):
            pair = selector(rng, None, None)
            counts[pair] = counts.get(pair, 0) + 1
            selector.update(None, pair[0], pair[1], 3)

        self.assertEqual(counts, {(0, 0): 2, (0, 1): 2, (1, 0): 2, (1, 1): 2})
        self.assertAlmostEqual(selector.current_epsilon, 0.046)
        self.assertEqual(selector.last_selection_info()["selector_type"], "epsilon_decay")
        self.assertIn(selector.last_selection_info()["selector_phase"], {"warmup", "explore", "exploit"})

    def test_minimum_coverage_skips_duplicate_couplings_and_refreshes_starved_families(self) -> None:
        coupling = np.array([[True, True], [True, True], [True, False]])
        selector = MinimumCoverageAlphaUCB(
            [20.0, 8.0, 2.0, 0.05],
            alpha=0.08,
            num_destroy=3,
            num_repair=2,
            op_coupling=coupling,
            protected_destroy_indices=(1, 2),
            warmup_per_pair=1,
            max_family_gap=3,
        )
        rng = np.random.default_rng(17)
        picks = []
        for _ in range(12):
            pair = selector(rng, None, None)
            picks.append(pair)
            selector.update(None, pair[0], pair[1], 3)

        self.assertEqual(picks[:5], [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0)])
        self.assertNotIn((2, 1), picks)
        for destroy_idx in (1, 2):
            selected_at = [idx for idx, pair in enumerate(picks) if pair[0] == destroy_idx]
            self.assertGreaterEqual(len(selected_at), 2)
        self.assertEqual(selector.last_selection_info()["selector_type"], "minimum_coverage")

    def test_thompson_selector_respects_coupling_and_updates_success_failure(self) -> None:
        coupling = np.array([[True, False], [True, True]])
        selector = ThompsonPairSelector(2, 2, op_coupling=coupling, warmup_per_pair=1)
        rng = np.random.default_rng(99)

        warmup_pairs = []
        for _ in range(3):
            pair = selector(rng, None, None)
            warmup_pairs.append(pair)
            selector.update(None, pair[0], pair[1], 2)
        self.assertEqual(warmup_pairs, [(0, 0), (1, 0), (1, 1)])
        self.assertNotIn((0, 1), warmup_pairs)

        selector.update(None, 0, 0, 0)
        selector.update(None, 1, 0, 3)

        self.assertEqual(selector.alpha_beta_for_pair(0, 0), (2.0, 2.0))
        self.assertEqual(selector.alpha_beta_for_pair(1, 0), (1.0, 3.0))

        first = [selector(rng, None, None) for _ in range(5)]
        other = ThompsonPairSelector(2, 2, op_coupling=coupling, warmup_per_pair=1)
        rng_other = np.random.default_rng(99)
        for _ in range(3):
            pair = other(rng_other, None, None)
            other.update(None, pair[0], pair[1], 2)
        other.update(None, 0, 0, 0)
        other.update(None, 1, 0, 3)
        second = [other(rng_other, None, None) for _ in range(5)]
        self.assertEqual(first, second)

    def test_softmax_selector_respects_coupling_and_reports_probability(self) -> None:
        coupling = np.array([[True, False], [True, True]])
        selector = SoftmaxAlphaUCB(
            [20.0, 8.0, 2.0, 0.05],
            alpha=0.08,
            num_destroy=2,
            num_repair=2,
            op_coupling=coupling,
            temperature_start=1.0,
            temperature_end=0.1,
            target_iterations=10,
        )
        rng = np.random.default_rng(1234)

        picks = [selector(rng, None, None) for _ in range(20)]

        self.assertNotIn((0, 1), picks)
        info = selector.last_selection_info()
        self.assertEqual(info["selector_type"], "softmax")
        self.assertGreaterEqual(info["selector_probability"], 0.0)
        self.assertLessEqual(info["selector_probability"], 1.0)
        self.assertAlmostEqual(info["selector_temperature"], 1.0)

    def test_selector_diagnostics_are_scalar_and_do_not_dump_value_matrix(self) -> None:
        selector = _make_operator_selector(2, 2, selector_kind="softmax", target_iterations=20)
        pair = selector(np.random.default_rng(5), None, None)
        info = selector.last_selection_info()

        self.assertEqual(set(info), {
            "selector_type",
            "selector_phase",
            "selector_iter",
            "selector_pair_times",
            "selector_value",
            "selector_sample",
            "selector_probability",
            "selector_epsilon",
            "selector_temperature",
        })
        self.assertIsInstance(info["selector_value"], float)
        self.assertIsInstance(info["selector_pair_times"], int)
        self.assertIn(pair, {(0, 0), (0, 1), (1, 0), (1, 1)})

    def test_diagnostic_trace_includes_selector_info_without_backend_change(self) -> None:
        flags = e2_alns_throughput_flags()
        flags[TRACE_DIAGNOSTIC_FLAG] = "1"
        flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"] = "1"
        flags[EPS_DECAY_SELECTOR_FLAG] = "1"

        result = _run_winner_variant(
            VERIFY_BUNDLE,
            config=WinnerKernelConfig(seed=13, eval_budget=16, max_runtime_seconds=120.0),
            initial_solution=None,
            variant_flags=flags,
            variant_id="unit_eps_decay_selector",
        )

        traces = result["operator_counts"]["candidate_trace"]
        self.assertTrue(traces)
        self.assertEqual(result["flags"][STRONG_BRIDGE_BACKEND_FLAG], "0")
        self.assertEqual(traces[0]["selector_type"], "epsilon_decay")
        self.assertIn("selector_epsilon", traces[0])
        self.assertIn("selector_pair_times", traces[0])
        self.assertTrue(all(row["candidate_backend"] == "winner_operator_set" for row in traces))


if __name__ == "__main__":
    unittest.main()
