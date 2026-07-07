from __future__ import annotations

import random
import unittest

from setp_solver.solution import ChargingAction, Route, Solution


class EliteArchiveRestartTests(unittest.TestCase):
    def test_archive_rejects_near_duplicate_solution(self) -> None:
        from setp_solver.search.elite_archive import EliteArchive

        solution = Solution(routes=[Route("CV1#T1", "cv", "D0", ["D0", "C1", "D0"])])
        archive = EliteArchive(max_size=4, diversity_min=0.10)

        self.assertTrue(archive.maybe_add(solution, objective=10.0))
        self.assertFalse(archive.maybe_add(solution, objective=9.0))
        self.assertEqual(len(archive.items), 1)

    def test_archive_keeps_best_diverse_items_under_limit(self) -> None:
        from setp_solver.search.elite_archive import EliteArchive

        archive = EliteArchive(max_size=2, diversity_min=0.10)
        archive.maybe_add(Solution(routes=[Route("CV1#T1", "cv", "D0", ["D0", "C1", "D0"])]), objective=30.0)
        archive.maybe_add(Solution(routes=[Route("CV2#T1", "cv", "D0", ["D0", "C2", "D0"])]), objective=10.0)
        archive.maybe_add(Solution(routes=[Route("EV1#T1", "ev", "D0", ["D0", "C3", "D0"])]), objective=20.0)

        self.assertEqual(len(archive.items), 2)
        self.assertEqual([item.objective for item in archive.items], [10.0, 20.0])

    def test_restart_proposal_is_solution_not_best_override(self) -> None:
        from setp_solver.search.elite_archive import EliteArchive

        archive = EliteArchive(max_size=4, diversity_min=0.10)
        archive.maybe_add(
            Solution(
                routes=[Route("EV1#T1", "ev", "D0", ["D0", "C1", "D0"])],
                charging_actions=[ChargingAction("EV1#T1", "D0", 1.0, 1.0, 1.0)],
            ),
            objective=10.0,
        )

        proposal = archive.propose_restart(random.Random(1))

        self.assertIsInstance(proposal, Solution)
        self.assertIsNot(proposal, archive.items[0].solution)


if __name__ == "__main__":
    unittest.main()
