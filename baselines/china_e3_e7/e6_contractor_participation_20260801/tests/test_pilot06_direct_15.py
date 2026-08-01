#!/usr/bin/env python3
from __future__ import annotations

import inspect
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (HERE, PROTOTYPE, REPO / "solver/src", REPO):
    sys.path.insert(0, str(path))

import run_pilot06_direct_15 as runner
from e6_methods import subset_bundle
from setp_solver.china81_completion import exact_china81_score


def test_fixed_contract() -> None:
    assert runner.INSTANCE == "cn-prd-150c-01-V2-LOCATIONS"
    assert (runner.SEED, runner.ITERATIONS, runner.ARCHIVE) == (1, 100, 8)
    assert runner.SP_SECONDS == 5.0
    assert runner.THETA_STEP == 0.05
    assert runner.REVENUE_ASSIGNMENT == "REVENUE_TO_SERVING_CONTRACTOR"
    assert runner.MULTI_MEMBER_INITIAL_UNION == "union"
    assert runner.MULTI_MEMBER_INITIAL_COMMON == "common"
    assert (
        inspect.signature(runner.run)
        .parameters["multi_member_initial"]
        .default
        == runner.MULTI_MEMBER_INITIAL_UNION
    )


def test_mapping_fleet_and_cross_site_cost_match_approved_input() -> None:
    bundle, info = runner.load_base()
    assert info["mapping_sha256"] == (
        "962c926f1d0b702f9b6a27d7b8e130691a86f2ba272f5c211d8b9abd57c0a8ab"
    )
    assert bundle.prices.cross_site_cost == 0.0


def test_singleton_union_is_a_legal_coalition_incumbent() -> None:
    base, _ = runner.load_base()
    members = tuple(sorted(base.fleet_caps_by_depot))[:2]
    singleton_solutions = {
        member: runner.e3.base.build_common_initial(subset_bundle(base, (member,)))[0]
        for member in members
    }
    bundle = subset_bundle(base, members)
    union = runner.union_singleton_solutions(bundle, singleton_solutions, members)
    _, _, violations = exact_china81_score(union, bundle)
    assert not violations
    assert len({route.vehicle_id for route in union.routes}) == len(union.routes)


def test_common_mode_builds_a_legal_initial_for_every_multi_member_coalition() -> None:
    base, _ = runner.load_base()
    members = tuple(sorted(base.fleet_caps_by_depot))
    for group in runner.coalitions(members):
        if len(group) == 1:
            continue
        bundle = subset_bundle(base, group)
        initial, source = runner.build_multi_member_initial(
            bundle,
            {},
            group,
            runner.MULTI_MEMBER_INITIAL_COMMON,
        )
        _, _, violations = exact_china81_score(initial, bundle)
        assert source == "COALITION_COMMON_INITIAL"
        assert not violations


def test_theta_grid_and_independent_shapley() -> None:
    assert len(runner.theta_values()) == 21
    assert runner.theta_values()[0] == 0.0
    assert runner.theta_values()[-1] == 1.0
    members = ("A", "B")
    values = {("A",): 2.0, ("B",): 3.0, ("A", "B"): 7.0}
    assert runner.permutation_shapley(values, members) == {"A": 3.0, "B": 4.0}
