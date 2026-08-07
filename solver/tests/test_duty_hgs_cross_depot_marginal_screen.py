from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "baselines/algorithm_prototypes/duty_hgs_20260807/"
    "run_cross_depot_marginal_screen.py"
)
SPEC = importlib.util.spec_from_file_location("cross_depot_marginal_screen", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


DISTANCE = {
    ("D1", "A"): 10.0,
    ("A", "B"): 4.0,
    ("B", "D1"): 8.0,
    ("D1", "B"): 12.0,
    ("A", "D1"): 9.0,
    ("D2", "C"): 7.0,
    ("C", "D2"): 6.0,
    ("D2", "A"): 3.0,
    ("A", "C"): 2.0,
    ("C", "A"): 5.0,
    ("A", "D2"): 4.0,
    ("D1", "C"): 6.0,
    ("C", "B"): 3.0,
}


def _distance(left: str, right: str) -> float:
    return DISTANCE[(left, right)]


def test_route_marginal_formulas_use_adjacent_arcs() -> None:
    removal = MODULE._remove_saving("D1", ("A", "B"), 0, _distance)
    insertion = MODULE._insertion_delta("D2", ("C",), 0, "A", _distance)
    replacement = MODULE._replacement_delta(
        "D1", ("A", "B"), 0, "C", _distance
    )

    assert removal == 10.0 + 4.0 - 12.0
    assert insertion == 3.0 + 2.0 - 7.0
    assert replacement == 6.0 + 3.0 - 10.0 - 4.0
