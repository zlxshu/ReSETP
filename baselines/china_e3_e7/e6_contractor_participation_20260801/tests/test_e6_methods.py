from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (HERE, PROTOTYPE, REPO / "solver/src", REPO):
    sys.path.insert(0, str(path))

from e6_methods import coalitions, core_allocation, core_violations, shapley, theta_grid


def test_four_member_additive_game() -> None:
    members = ("A", "B", "C", "D")
    weights = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0}
    values = {
        group: sum(weights[member] for member in group)
        for group in coalitions(members)
    }
    allocation = shapley(values, members)
    assert allocation == weights
    nonempty, witness = core_allocation(values, members)
    assert nonempty and witness is not None
    assert not core_violations(witness, values, members)


def test_theta_interfaces() -> None:
    assert len(coalitions(("A", "B", "C", "D"))) == 15
    assert theta_grid(0.05)[-1] == 1.0
    assert len(theta_grid(0.005)) == 201
