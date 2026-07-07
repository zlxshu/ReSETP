from __future__ import annotations

import unittest
from pathlib import Path

from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/verify_20251113"


class FleetChargeCorepairTests(unittest.TestCase):
    def test_corepair_flag_is_mutually_exclusive_with_global_repack(self) -> None:
        from setp_solver.search.winner_operators import (
            FLEET_CHARGE_COREPAIR_FLAG,
            GLOBAL_ORDER_REPACK_FLAG,
            structural_component_from_flags,
        )

        flags = {GLOBAL_ORDER_REPACK_FLAG: "1", FLEET_CHARGE_COREPAIR_FLAG: "1"}

        with self.assertRaisesRegex(ValueError, "HALT_CONFIG_CONFLICT_STRUCTURAL_FLAGS"):
            structural_component_from_flags(flags)

    def test_flip_candidates_never_return_infeasible_solution(self) -> None:
        from setp_solver.check import check_solution
        from setp_solver.prices import DEFAULT_PRICES
        from setp_solver.search.evaluation import EvaluationContext
        from setp_solver.search.fleet_charge_corepair import propose_fleet_charge_corepair

        bundle = load_search_bundle(VERIFY_BUNDLE)
        solution = make_shared_initial_solution(bundle)
        context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=DEFAULT_PRICES)

        outcome = propose_fleet_charge_corepair(solution, context, max_attempts=8)

        self.assertGreaterEqual(outcome.attempts, 1)
        self.assertGreaterEqual(outcome.feasible, 0)
        if outcome.solution is not None:
            self.assertFalse(check_solution(outcome.solution, bundle.instance, DEFAULT_PRICES))
            self.assertIn(outcome.source_route_type, {"cv", "ev"})
            self.assertIn(outcome.target_route_type, {"cv", "ev"})


if __name__ == "__main__":
    unittest.main()
