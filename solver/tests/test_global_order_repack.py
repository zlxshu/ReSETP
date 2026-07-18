from __future__ import annotations

import random
import unittest
from pathlib import Path

from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/verify_20251113"


class GlobalOrderRepackTests(unittest.TestCase):
    def test_order_perturbations_are_complete_and_labeled(self) -> None:
        from setp_solver.search.global_order_repack import order_perturbations
        from setp_solver.search.order_decoder import solution_order

        bundle = load_search_bundle(VERIFY_BUNDLE)
        solution = make_shared_initial_solution(bundle)
        base_order = solution_order(solution, bundle.instance)

        rows = order_perturbations(base_order, bundle.instance, random.Random(7))

        labels = {row.label for row in rows}
        self.assertEqual(labels, {"current_order", "two_opt_order", "double_bridge_order", "depot_group_shuffle_order"})
        self.assertTrue(all(sorted(row.order) == sorted(base_order) for row in rows))

    def test_global_repack_flag_is_mutually_exclusive_with_other_structural_flags(self) -> None:
        from setp_solver.search.winner_operators import (
            GLOBAL_ORDER_REPACK_FLAG,
            ROUTE_POOL_RECOMBINATION_FLAG,
            structural_component_from_flags,
        )

        flags = {GLOBAL_ORDER_REPACK_FLAG: "1", ROUTE_POOL_RECOMBINATION_FLAG: "1"}

        with self.assertRaisesRegex(ValueError, "HALT_CONFIG_CONFLICT_STRUCTURAL_FLAGS"):
            structural_component_from_flags(flags)

    def test_global_repack_due_uses_stagnation_or_late_stage_periodic_trigger(self) -> None:
        import setp_solver.search.winner_operators as winner_ops

        self.assertTrue(
            winner_ops._structural_component_due(  # noqa: SLF001
                "global_order_repack",
                moves=100,
                moves_since_best_improvement=winner_ops._structural_rescue_interval(4000),
                target=4000,
            )
        )
        interval = winner_ops._structural_rescue_interval(4000)  # noqa: SLF001
        late = winner_ops._structural_late_stage_start(4000)  # noqa: SLF001
        periodic_late_move = late + ((interval - (late % interval)) % interval)
        self.assertTrue(
            winner_ops._structural_component_due(  # noqa: SLF001
                "global_order_repack",
                moves=periodic_late_move,
                moves_since_best_improvement=0,
                target=4000,
            )
        )
        self.assertFalse(
            winner_ops._structural_component_due(  # noqa: SLF001
                "route_pool",
                moves=100,
                moves_since_best_improvement=winner_ops._structural_rescue_interval(4000),
                target=4000,
            )
        )

    def test_global_repack_candidate_uses_existing_referee(self) -> None:
        from setp_solver.check import check_solution
        from setp_solver.prices import DEFAULT_PRICES
        from setp_solver.search.evaluation import EvaluationContext, model_cost
        from setp_solver.algorithms.resetp_alns.support.global_order_repack import (
            propose_global_order_repack,
        )

        bundle = load_search_bundle(VERIFY_BUNDLE)
        solution = make_shared_initial_solution(bundle)
        context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=DEFAULT_PRICES)

        outcome = propose_global_order_repack(
            solution,
            solution,
            context,
            random.Random(11),
            current_objective=model_cost(solution, context),
        )

        self.assertGreaterEqual(outcome.attempts, 1)
        if outcome.solution is not None:
            self.assertFalse(check_solution(outcome.solution, bundle.instance, DEFAULT_PRICES))
            self.assertIsInstance(outcome.trace_rows, list)
            self.assertIsNotNone(outcome.objective)


if __name__ == "__main__":
    unittest.main()
