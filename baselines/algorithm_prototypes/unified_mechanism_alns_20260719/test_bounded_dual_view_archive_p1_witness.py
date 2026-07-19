"""Zero-scoring regression tests for the P1 solution witness recorder."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import bounded_dual_view_archive_solver as solver  # noqa: E402
import run_bounded_dual_view_archive_p1_training_gate as gate  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)


def _solution() -> Solution:
    return Solution(
        routes=[
            Route("EV1", "ev", "D0", ["D0", "C1", "D0"]),
            Route("CV1", "cv", "D1", ["D1", "C2", "D1"]),
        ],
        charging_actions=[
            ChargingAction("EV1", "S1", 1.0, 2.0, 3.0, 0),
            ChargingAction("EV1", "S2", 4.0, 5.0, 6.0, 0),
        ],
        cross_site_services=[
            CrossSiteService("C1", "D0"),
            CrossSiteService("C2", "D1"),
        ],
    )


class P1WitnessRecorderTest(unittest.TestCase):
    def test_reordered_semantic_equal_solutions_are_kept_separately(
        self,
    ) -> None:
        original = _solution()
        reordered = Solution(
            routes=list(reversed(original.routes)),
            charging_actions=list(reversed(original.charging_actions)),
            cross_site_services=list(reversed(original.cross_site_services)),
        )
        self.assertEqual(
            solver._exact_solution_hash(original),
            solver._exact_solution_hash(reordered),
        )

        witnesses: dict[str, object] = {}
        gate._add_witness(witnesses, original, {"kind": "original"})
        gate._add_witness(witnesses, reordered, {"kind": "reordered"})

        self.assertEqual(len(witnesses), 2)
        semantic_hashes = {
            row["semantic_exact_sha256"] for row in witnesses.values()
        }
        self.assertEqual(len(semantic_hashes), 1)

    def test_identical_snapshot_merges_uses(self) -> None:
        solution = _solution()
        witnesses: dict[str, object] = {}
        gate._add_witness(witnesses, solution, {"kind": "first"})
        gate._add_witness(witnesses, solution, {"kind": "second"})

        self.assertEqual(len(witnesses), 1)
        row = next(iter(witnesses.values()))
        self.assertEqual(
            row["uses"],
            [{"kind": "first"}, {"kind": "second"}],
        )

    def test_small_float_change_changes_full_content_hash(self) -> None:
        original = _solution()
        changed_actions = list(original.charging_actions)
        changed_actions[0] = replace(
            changed_actions[0],
            charge_start_second=(
                changed_actions[0].charge_start_second + 1.0e-12
            ),
        )
        changed = replace(original, charging_actions=changed_actions)

        witnesses: dict[str, object] = {}
        gate._add_witness(witnesses, original, {"kind": "original"})
        gate._add_witness(witnesses, changed, {"kind": "changed"})

        self.assertEqual(len(witnesses), 2)
        hashes = {
            row["full_content_sha256"] for row in witnesses.values()
        }
        self.assertEqual(len(hashes), 2)


if __name__ == "__main__":
    unittest.main()
