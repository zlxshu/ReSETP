from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import SearchBundle
from setp_solver.search import metaheuristic_baselines as mb
from setp_solver.solution import Route, Solution


def _two_customer_bundle() -> SearchBundle:
    nodes = [
        Node("D0", "d", 0.0, 0.0, demand=0.0, ready_time=0.0, due_time=100_000.0, service_time=0.0),
        Node("C1", "c", 1000.0, 100.0, demand=10.0, ready_time=0.0, due_time=100_000.0, service_time=0.0),
        Node("C2", "c", 1100.0, 0.0, demand=10.0, ready_time=0.0, due_time=100_000.0, service_time=0.0),
    ]
    matrix = [
        [0.0, 1004.987562112089, 1100.0],
        [1004.987562112089, 0.0, 141.4213562373095],
        [1100.0, 141.4213562373095, 0.0],
    ]
    return SearchBundle(
        bundle_dir=Path("."),
        instance=Instance(nodes=nodes, distance_matrix=matrix, num_cv=3, num_ev=0),
        carbon_profile=[],
    )


class BaselineStartPointReferenceTest(unittest.TestCase):
    def test_reference_flip_closure_does_not_mutate_current_or_best(self) -> None:
        bundle = _two_customer_bundle()
        warm = Solution(
            routes=[Route("CV1#T1", "cv", "D0", ["D0", "C1", "C2", "D0"])],
            charging_actions=[],
            cross_site_services=[],
        )

        def fake_closure(solution: Solution, session: mb._SearchSession) -> dict[str, object]:
            return {
                "solution": solution,
                "cost": session.best.cost - 5.0,
                "attempts": 7,
                "accepted_flips": 1,
            }

        with patch.object(mb, "_deterministic_common_flip_closure", side_effect=fake_closure):
            session = mb._SearchSession(
                "GA",
                bundle,
                1,
                8,
                120.0,
                warm,
                prices=DEFAULT_PRICES,
                common_flip_preprocess=True,
            )

        self.assertEqual(session.current.signature, mb.solution_signature_hash(warm))
        self.assertEqual(session.best.signature, mb.solution_signature_hash(warm))
        self.assertEqual(session.common_preprocess_cost, None)
        self.assertEqual(session.common_preprocess_attempts, 0)
        self.assertEqual(session.common_preprocess_accepted_flips, 0)
        self.assertEqual(session.reference_flip_closure_attempts, 7)
        self.assertEqual(session.reference_flip_closure_accepted_flips, 1)
        self.assertAlmostEqual(session.reference_flip_closure_lift, 5.0)
        self.assertEqual(session.history[-1]["channel"], "reference_flip_closure")
        self.assertTrue(session.history[-1]["is_reference"])

        result = session.finalize({"test": "reference"})
        self.assertEqual(result.common_lift, 0.0)
        self.assertEqual(result.common_best_updates, 0)
        self.assertEqual(result.reference_flip_closure_attempts, 7)
        self.assertAlmostEqual(result.reference_flip_closure_lift, 5.0)


if __name__ == "__main__":
    unittest.main()
