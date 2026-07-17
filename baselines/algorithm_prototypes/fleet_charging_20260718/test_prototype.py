"""Unit tests for the isolated FC-C02 and FC-C05 prototypes."""

from __future__ import annotations

import unittest

from contracts import (
    CompleteEvaluationBudget,
    ProbeCounters,
    cumulative_charge_time,
    independently_replay_charging_result,
)
from frvcpy_adapter import (
    CachingChargingOracle,
    FrvcpyOracleAdapter,
    build_fc_c02_abstract_micro_request,
)
from vmr_nl import (
    VMRNLSelector,
    abstract_probe_score,
    build_fc_c05_manual_candidates,
    independently_select_manual_reference,
)


class FleetChargingPrototypeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = build_fc_c02_abstract_micro_request()

    def test_nonlinear_curve_interpolation(self) -> None:
        energy = [0.0, 6.0, 10.0]
        time = [0.0, 1.0, 3.0]
        self.assertAlmostEqual(cumulative_charge_time(energy, time, 3.0), 0.5)
        self.assertAlmostEqual(cumulative_charge_time(energy, time, 8.0), 2.0)

    def test_fc_c02_independent_replay(self) -> None:
        counters = ProbeCounters()
        result = FrvcpyOracleAdapter().solve(self.request, counters)
        replay = independently_replay_charging_result(self.request, result)
        counters.reference_evaluations += 1
        self.assertTrue(result.feasible)
        self.assertTrue(replay.feasible)
        self.assertAlmostEqual(result.objective, 4.0)
        self.assertAlmostEqual(replay.objective, result.objective)
        self.assertIn((2, 6.0), result.stops)
        self.assertEqual(counters.route_oracle_calls, 1)
        self.assertEqual(counters.reference_evaluations, 1)

    def test_fc_c02_budget_zero_one_two_five(self) -> None:
        for limit in (0, 1, 2, 5):
            counters = ProbeCounters()
            budget = CompleteEvaluationBudget(limit, counters)
            oracle = CachingChargingOracle(FrvcpyOracleAdapter())
            completed = 0
            while budget.reserve():
                result = oracle.solve(self.request, counters)
                replay = independently_replay_charging_result(self.request, result)
                counters.reference_evaluations += 1
                self.assertTrue(replay.feasible)
                self.assertAlmostEqual(replay.objective, result.objective)
                completed += 1
            self.assertEqual(completed, limit)
            self.assertEqual(counters.complete_candidate_evaluations, limit)
            self.assertLessEqual(counters.complete_candidate_evaluations, limit)
            self.assertEqual(counters.route_oracle_calls, 0 if limit == 0 else 1)
            self.assertEqual(counters.oracle_cache_hits, max(0, limit - 1))

    def test_fc_c05_budget_and_activity(self) -> None:
        candidates = build_fc_c05_manual_candidates(self.request)
        for limit in (0, 1, 2, 5):
            counters = ProbeCounters()
            budget = CompleteEvaluationBudget(limit, counters)
            selector = VMRNLSelector(
                CachingChargingOracle(FrvcpyOracleAdapter()),
                abstract_probe_score,
            )
            result = selector.select(candidates, budget, counters, top_b=5)
            self.assertLessEqual(counters.complete_candidate_evaluations, limit)
            self.assertEqual(counters.complete_candidate_evaluations, limit)
            if limit == 0:
                self.assertIsNone(result.selected)
                self.assertEqual(counters.screen_evaluations, 0)
                continue
            self.assertEqual(result.selected.candidate.candidate_id, "M1")
            self.assertAlmostEqual(result.selected.score, 5.0)
            expected_id, expected_regret = independently_select_manual_reference(
                candidates,
                oracle_objective=4.0,
                evaluated_candidate_ids={
                    item.candidate.candidate_id for item in result.evaluated
                },
            )
            counters.reference_evaluations += 1
            self.assertEqual(result.selected.candidate.candidate_id, expected_id)
            self.assertEqual(result.regret, expected_regret)
            self.assertEqual(result.active, limit >= 2)

    def test_formal_objective_is_injected(self) -> None:
        candidate = build_fc_c05_manual_candidates(self.request)[1]
        custom_selector = VMRNLSelector(
            CachingChargingOracle(FrvcpyOracleAdapter()),
            lambda item, _: -item.abstract_base_score,
        )
        counters = ProbeCounters()
        result = custom_selector.select(
            (candidate,),
            CompleteEvaluationBudget(1, counters),
            counters,
            top_b=1,
        )
        self.assertEqual(result.selected.score, -7.0)


if __name__ == "__main__":
    unittest.main()
