#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (HERE, PROTOTYPE, REPO / "solver/src", REPO):
    sys.path.insert(0, str(path))

import run_pilot05_grand_coalition_recovery as runner


def test_recovery_budget_is_the_successful_e3_budget() -> None:
    assert runner.INSTANCE == "cn-prd-150c-01-V2-LOCATIONS"
    assert runner.SEED == 1
    assert runner.ITERATIONS == 100
    assert runner.ARCHIVE == 8


def test_mapping_initial_and_fleet_match_e3() -> None:
    bundle, _, info, context = runner.load_context()
    assert info["mapping_sha256"] == (
        "962c926f1d0b702f9b6a27d7b8e130691a86f2ba272f5c211d8b9abd57c0a8ab"
    )
    assert context["initial_sha256"] == (
        "a42ba4c3fb3a6a8a313e6d5ae9c1d4196cd1898550810a2633d344c18d3bed1a"
    )
    assert bundle.prices.cross_site_cost == 0.0


def test_reference_cost_uses_exactly_four_pilot04_singletons() -> None:
    assert runner.pilot04_singleton_cost() == 10927.074169457777


def test_trigger_requires_legality_saving_and_cross_service() -> None:
    assert runner.mechanism_triggered(True, 9.0, 10.0, 1)
    assert not runner.mechanism_triggered(False, 9.0, 10.0, 1)
    assert not runner.mechanism_triggered(True, 10.0, 10.0, 1)
    assert not runner.mechanism_triggered(True, 9.0, 10.0, 0)
