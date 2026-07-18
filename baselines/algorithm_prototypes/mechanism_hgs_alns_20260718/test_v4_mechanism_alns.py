from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import pytest


REPO = Path(__file__).resolve().parents[3]
SOLVER_SRC = REPO / "solver/src"
HERE = Path(__file__).resolve().parent
REFERENCE_ALNS = REPO / "Reference Algorithm" / "ALNS-7.0.0@N-Wouda"
for path in (SOLVER_SRC, HERE, REFERENCE_ALNS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from v4_mechanism_alns_solver import (  # noqa: E402
    run_mechanism_alns_v4,
    run_mechanism_alns_v4_without_joint,
)


BUNDLE = (
    REPO
    / "models/data_bundle/generated_instances/L-main_size_preserving_v2_archive_20260710"
    / "L-main-threeshift-25c-01"
)
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)


@pytest.mark.parametrize("budget", [0, 1, 2, 5])
def test_v4_exact_budget_and_feasibility(budget: int) -> None:
    result = run_mechanism_alns_v4(
        BUNDLE,
        seed=1,
        eval_budget=budget,
        prices=PRICES,
    )
    bundle = load_search_bundle(BUNDLE)
    assert result.evaluations == budget
    assert result.feasible
    assert not check_solution(result.best_solution, bundle.instance, PRICES)


def test_joint_decoder_uses_one_complete_evaluation_and_improves() -> None:
    full = run_mechanism_alns_v4(
        BUNDLE,
        seed=1,
        eval_budget=100,
        prices=PRICES,
    )
    ablation = run_mechanism_alns_v4_without_joint(
        BUNDLE,
        seed=1,
        eval_budget=100,
        prices=PRICES,
    )
    activity = full.mechanism_activity["joint_activity"]
    assert activity["complete_evaluations"] == 1
    assert activity["route_proxy_evaluations"] > 0
    assert activity["improvements"] == 1
    assert full.best_cost < ablation.best_cost - 1.0e-9
