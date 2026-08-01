from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from e6_cooperative_game import coalitions, core_violations, nucleolus


def test_additive_game_nucleolus() -> None:
    members = ("A", "B", "C", "D")
    weights = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0}
    values = {
        group: sum(weights[member] for member in group)
        for group in coalitions(members)
    }
    allocation = nucleolus(values, members)
    assert all(abs(allocation[member] - weights[member]) < 1e-7 for member in members)
    assert not core_violations(allocation, values, members)


def test_three_member_majority_game_nucleolus() -> None:
    members = ("A", "B", "C")
    values = {
        group: (1.0 if len(group) >= 2 else 0.0)
        for group in coalitions(members)
    }
    allocation = nucleolus(values, members)
    assert all(abs(allocation[member] - 1.0 / 3.0) < 1e-7 for member in members)
