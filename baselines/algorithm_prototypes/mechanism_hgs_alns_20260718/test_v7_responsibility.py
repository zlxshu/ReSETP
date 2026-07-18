"""Focused tests for the v7 multi-depot responsibility decoder."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from prototype import independent_cost, run_pure_alns
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from v7_responsibility_solver import (
    run_mechanism_alns_v7,
    run_mechanism_alns_v7_without_responsibility,
)


ROOT = Path(__file__).resolve().parents[3]
MULTIDEPOT = (
    ROOT
    / "models/data_bundle/generated_instances"
    / "L-main_mixed23_archive_20260709"
)
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)


@pytest.mark.parametrize(
    ("size", "seed"),
    ((25, 3), (50, 1), (75, 2)),
)
def test_responsibility_binding_cases_improve_without_budget_theft(
    size: int,
    seed: int,
) -> None:
    bundle = MULTIDEPOT / f"L-main-multidepot-{size}c-01"
    full = run_mechanism_alns_v7(
        bundle,
        seed=seed,
        eval_budget=100,
        prices=PRICES,
    )
    ablation = run_mechanism_alns_v7_without_responsibility(
        bundle,
        seed=seed,
        eval_budget=100,
        prices=PRICES,
    )
    current = run_pure_alns(
        bundle,
        seed=seed,
        eval_budget=100,
        prices=PRICES,
    )
    activity = full.mechanism_activity["responsibility_activity"]

    assert full.evaluations == ablation.evaluations == current.evaluations == 100
    assert activity["complete_route_search_evaluations"] == 0
    assert activity["exact_decoder_updates"] >= 1
    assert activity["improvements"] >= 1
    assert activity["accepted_moves"]
    assert full.best_cost < ablation.best_cost - 1.0e-9
    assert full.best_cost < current.best_cost - 1.0e-9
    assert independent_cost(bundle, full.best_solution, PRICES) == pytest.approx(
        full.best_cost,
        abs=1.0e-7,
    )
    assert not check_solution(full.best_solution, load_instance(bundle), PRICES)


def load_instance(bundle: Path):
    """Keep the test assertion readable without sharing mutable bundles."""

    from setp_solver.search.bundle import load_search_bundle

    return load_search_bundle(bundle).instance
