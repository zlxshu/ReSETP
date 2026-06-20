from __future__ import annotations

import unittest
from unittest.mock import patch

from setp_solver.check import check_solution
from setp_solver.instance_loader import Instance, Node
from setp_solver.search.alns_wouda import AlnsState, SearchPolicy, regret2_insert_repair, route_elimination_removal
from setp_solver.search.alns_crush import (
    cost_breakdown_row,
    low_utilization_route_elimination_probe,
)
from setp_solver.search.candidates import _apply_dr_destroy_repair, _path_repair_delta_score
from setp_solver.search.evaluation import EvaluationContext, model_cost, score_reference
from setp_solver.search.feasible_repair import _delta_score
from setp_solver.search.local_search import improve_solution_locally
from setp_solver.solution import Route, Solution


def _mergeable_instance() -> Instance:
    return Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, demand=0.0, due_time=100_000.0),
            Node("C1", "c", 0.0, 0.0, demand=100.0, due_time=100_000.0),
            Node("C2", "c", 0.0, 0.0, demand=100.0, due_time=100_000.0),
        ],
        distance_matrix=[
            [0.0, 1.0, 1.0],
            [1.0, 0.0, 1.0],
            [1.0, 1.0, 0.0],
        ],
    )


def _two_opt_instance() -> Instance:
    return Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, demand=0.0, due_time=100_000.0),
            Node("C1", "c", 0.0, 0.0, demand=10.0, due_time=100_000.0),
            Node("C2", "c", 0.0, 0.0, demand=10.0, due_time=100_000.0),
            Node("C3", "c", 0.0, 0.0, demand=10.0, due_time=100_000.0),
        ],
        distance_matrix=[
            [0.0, 1.0, 100.0, 1.0],
            [1.0, 0.0, 1.0, 100.0],
            [100.0, 1.0, 0.0, 1.0],
            [1.0, 100.0, 1.0, 0.0],
        ],
    )


class AlnsCrushTests(unittest.TestCase):
    def test_route_repair_delta_scores_new_route_fixed_cost(self) -> None:
        instance = _mergeable_instance()
        route = Route("CV_NEW", "cv", "D0", ["D0", "C1", "D0"])
        context = EvaluationContext(instance, [])

        with patch.dict("os.environ", {"SETP_ALNS_CRUSH_TRUE_REPAIR": "1"}):
            self.assertGreater(_path_repair_delta_score(route, context), 79.0)
            self.assertGreater(_delta_score(Solution(routes=[route]), route, [], context), 79.0)

    def test_cost_breakdown_row_reports_fixed_cost_share(self) -> None:
        instance = _mergeable_instance()
        solution = Solution(
            routes=[
                Route("CV1", "cv", "D0", ["D0", "C1", "D0"]),
                Route("CV2", "cv", "D0", ["D0", "C2", "D0"]),
            ]
        )

        row = cost_breakdown_row("toy", "warm", 1, solution, instance, [])

        self.assertEqual(row["route_count"], 2)
        self.assertEqual(row["violation_count"], 0)
        self.assertGreater(row["cost_fix"], row["cost_km"])
        self.assertAlmostEqual(row["cost_fix_share_pct"], row["cost_fix"] / row["total_cost"] * 100.0)

    def test_low_utilization_route_probe_merges_route_only_when_feasible_and_cheaper(self) -> None:
        instance = _mergeable_instance()
        solution = Solution(
            routes=[
                Route("CV1", "cv", "D0", ["D0", "C1", "D0"]),
                Route("CV2", "cv", "D0", ["D0", "C2", "D0"]),
            ]
        )

        result = low_utilization_route_elimination_probe(solution, instance, [])

        self.assertTrue(result.improved)
        self.assertLess(result.best_route_count, result.original_route_count)
        self.assertLess(result.best_cost, result.original_cost)
        self.assertEqual(check_solution(result.best_solution, instance), [])

    def test_wouda_route_elimination_destroy_repairs_without_new_route(self) -> None:
        import numpy as np

        instance = _mergeable_instance()
        solution = Solution(
            routes=[
                Route("CV1", "cv", "D0", ["D0", "C1", "D0"]),
                Route("CV2", "cv", "D0", ["D0", "C2", "D0"]),
            ]
        )
        context = EvaluationContext(instance, [])
        state = AlnsState(
            solution,
            context,
            objective_value=score_reference(solution, context),
            policy=SearchPolicy(require_charging_signal=False),
        )

        destroyed = route_elimination_removal(state, np.random.default_rng(1))
        repaired = regret2_insert_repair(destroyed, np.random.default_rng(2))

        self.assertEqual(len(destroyed.solution.routes), 1)
        self.assertTrue(destroyed.removed_customers)
        self.assertEqual(len(repaired.solution.routes), 1)
        self.assertFalse(repaired.removed_customers)
        self.assertLess(model_cost(repaired.solution, context), model_cost(solution, context))
        self.assertEqual(check_solution(repaired.solution, instance), [])

    def test_dr_route_elimination_accepts_only_route_and_cost_drop(self) -> None:
        import random

        instance = _mergeable_instance()
        solution = Solution(
            routes=[
                Route("CV1", "cv", "D0", ["D0", "C1", "D0"]),
                Route("CV2", "cv", "D0", ["D0", "C2", "D0"]),
            ]
        )
        context = EvaluationContext(instance, [])

        outcome = _apply_dr_destroy_repair(solution, context, random.Random(1), "route_elimination")

        self.assertTrue(outcome.feasible)
        self.assertTrue(outcome.changed)
        self.assertEqual(outcome.metadata["route_count_delta"], -1)
        self.assertLess(len(outcome.solution.routes), len(solution.routes))
        self.assertLess(model_cost(outcome.solution, context), model_cost(solution, context))
        self.assertEqual(check_solution(outcome.solution, instance), [])

    def test_local_search_accepts_feasible_two_opt_improvement(self) -> None:
        instance = _two_opt_instance()
        context = EvaluationContext(instance, [])
        solution = Solution(routes=[Route("CV1", "cv", "D0", ["D0", "C1", "C3", "C2", "D0"])])

        with patch.dict("os.environ", {"SETP_ALNS_CRUSH_LOCAL_SEARCH": "1"}):
            improved = improve_solution_locally(solution, context)

        self.assertEqual(check_solution(improved, instance), [])
        self.assertLess(model_cost(improved, context), model_cost(solution, context))
        self.assertEqual(improved.routes[0].node_sequence, ["D0", "C1", "C2", "C3", "D0"])


if __name__ == "__main__":
    unittest.main()
