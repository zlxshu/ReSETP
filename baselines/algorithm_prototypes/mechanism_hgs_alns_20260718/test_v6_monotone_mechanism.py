from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
for path in (REPO / "solver/src", HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from v6_monotone_mechanism_solver import (  # noqa: E402
    run_mechanism_alns_v6,
    run_mechanism_alns_v6_without_carbon,
    run_mechanism_alns_v6_without_joint,
)


ROOT = (
    REPO
    / "models/data_bundle/generated_instances/L-main_size_preserving_v2_archive_20260710"
)


def test_v6_is_monotone_and_budget_exact_on_binding_cases() -> None:
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
    for size in (20, 25, 50):
        bundle = ROOT / f"L-main-threeshift-{size}c-01"
        full = run_mechanism_alns_v6(
            bundle,
            seed=1,
            eval_budget=100,
            prices=prices,
        )
        without_carbon = run_mechanism_alns_v6_without_carbon(
            bundle,
            seed=1,
            eval_budget=100,
            prices=prices,
        )
        without_joint = run_mechanism_alns_v6_without_joint(
            bundle,
            seed=1,
            eval_budget=100,
            prices=prices,
        )
        assert full.evaluations == 100
        assert without_carbon.evaluations == 100
        assert without_joint.evaluations == 100
        assert full.feasible and without_carbon.feasible and without_joint.feasible
        assert full.best_cost < without_carbon.best_cost - 1.0e-9
        assert full.best_cost <= without_joint.best_cost + 1.0e-9
        assert (
            full.mechanism_activity["joint_activity"]["complete_evaluations"]
            == 0
        )
        assert (
            full.mechanism_activity["carbon_activity"]["complete_evaluations"]
            == 0
        )

