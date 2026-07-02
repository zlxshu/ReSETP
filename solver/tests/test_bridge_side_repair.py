from __future__ import annotations

import random
import unittest

from setp_solver.check import check_solution
from setp_solver.search import candidates as candidate_module
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvalBudget, EvaluationContext

from baselines.e2_alns import bridge_fix_validation as bridge_probe


class BridgeSideRepairTest(unittest.TestCase):
    def test_strong_bridge_repair_produces_feasible_changed_platform_neighbor(self) -> None:
        bundle = load_search_bundle(bridge_probe.THREESHIFT_BUNDLE)
        prices = bridge_probe.make_probe_prices()
        context = EvaluationContext(
            bundle.instance,
            bundle.carbon_profile,
            prices=prices,
            budget=EvalBudget(limit=128, target=4),
        )
        platform = bridge_probe.load_platform_solution()
        combos = [(destroy, repair) for destroy in bridge_probe.DESTROY_OPS for repair in bridge_probe.REPAIR_OPS]
        rng = random.Random(1)

        outcome = None
        for trial in range(1, 5):
            destroy, repair = combos[(trial - 1) % len(combos)]
            outcome = candidate_module._apply_strong_alns_destroy_repair(platform, context, rng, destroy, repair)

        self.assertIsNotNone(outcome)
        self.assertEqual(destroy, "shaw_related_removal")
        self.assertEqual(repair, "greedy_insert_repair")
        self.assertTrue(outcome.produced)
        self.assertTrue(outcome.feasible)
        self.assertTrue(outcome.changed)
        self.assertEqual(check_solution(outcome.solution, bundle.instance, prices), [])
        self.assertGreaterEqual(len(outcome.solution.routes), 20)
        self.assertLessEqual(len(outcome.solution.routes), 40)


if __name__ == "__main__":
    unittest.main()
