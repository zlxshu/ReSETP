from __future__ import annotations

from types import SimpleNamespace

import pytest

from baselines.china_e3_e7.e4_joint_routing_20260801.joint_soc_wrapper import (
    COST_ONLY,
    _select_cost_only_scored,
    _select_pure_carbon_scored,
    complete_route_skeleton,
    register_objective,
    route_pool_hooks,
    score_fixed_solution,
)
from baselines.china_e3_e7.e4_joint_routing_20260801.run_probe import (
    initial_skeleton,
    load_bundle,
)


def test_real_50c_completion_enforces_daily_soc_cycle() -> None:
    bundle = load_bundle()
    register_objective(bundle, COST_ONLY)
    completion = complete_route_skeleton(initial_skeleton(bundle), bundle)
    score = score_fixed_solution(completion.solution, bundle, validate_full=True)

    assert not score.violations
    assert len(score.terminal_charges) <= int(score.breakdown["n_veh_ev"])
    assert all(float(row["minimum_soc"]) >= 0.20 - 1e-9 for row in score.soc_rows)
    assert all(float(row["maximum_soc"]) <= 0.80 + 1e-9 for row in score.soc_rows)
    assert all(
        float(row["final_soc_after_terminal_charge"]) >= 0.60 - 1e-9
        for row in score.soc_rows
    )


def test_original_fleet_caps_and_no_vehicle_ratio() -> None:
    bundle = load_bundle()
    register_objective(bundle, COST_ONLY)
    solution = complete_route_skeleton(initial_skeleton(bundle), bundle).solution

    for depot_id, caps in bundle.fleet_caps_by_depot.items():
        for vehicle_type in ("cv", "ev"):
            used = sum(
                route.home_depot_id == depot_id
                and route.vehicle_type.lower() == vehicle_type
                for route in solution.routes
            )
            assert used <= int(caps[f"num_{vehicle_type}"])


def test_cost_only_tie_break_does_not_read_carbon() -> None:
    low_carbon_long_detour = SimpleNamespace(
        total_incremental_cost=10.0,
        timing=SimpleNamespace(carbon_kg=1.0, start_second=100.0),
        option=SimpleNamespace(detour_m=50.0, station_id="A"),
    )
    high_carbon_short_detour = SimpleNamespace(
        total_incremental_cost=10.0,
        timing=SimpleNamespace(carbon_kg=9.0, start_second=200.0),
        option=SimpleNamespace(detour_m=10.0, station_id="B"),
    )

    selected = _select_cost_only_scored(
        [low_carbon_long_detour, high_carbon_short_detour]
    )
    assert selected is high_carbon_short_detour

    low_carbon_long_detour.timing.carbon_kg = 99.0
    high_carbon_short_detour.timing.carbon_kg = 0.1
    assert (
        _select_cost_only_scored(
            [low_carbon_long_detour, high_carbon_short_detour]
        )
        is high_carbon_short_detour
    )


def test_pure_carbon_choice_does_not_read_cost() -> None:
    cheap_dirty = SimpleNamespace(
        total_incremental_cost=1.0,
        timing=SimpleNamespace(carbon_kg=9.0, start_second=100.0),
        option=SimpleNamespace(detour_m=10.0, station_id="A"),
    )
    expensive_clean = SimpleNamespace(
        total_incremental_cost=99.0,
        timing=SimpleNamespace(carbon_kg=1.0, start_second=200.0),
        option=SimpleNamespace(detour_m=50.0, station_id="B"),
    )

    selected = _select_pure_carbon_scored([cheap_dirty, expensive_clean])
    assert selected is expensive_clean

    cheap_dirty.total_incremental_cost = 0.01
    expensive_clean.total_incremental_cost = 999.0
    assert _select_pure_carbon_scored([cheap_dirty, expensive_clean]) is expensive_clean


def test_route_pool_hooks_restore_original_functions() -> None:
    import epochal_hgs
    import route_pool_sp

    originals = (
        epochal_hgs.complete_china81_route_skeleton,
        route_pool_sp.complete_china81_route_skeleton,
        route_pool_sp.exact_china81_score,
        route_pool_sp._single_route_cost,
    )
    with route_pool_hooks():
        assert epochal_hgs.complete_china81_route_skeleton is complete_route_skeleton
        assert route_pool_sp.complete_china81_route_skeleton is complete_route_skeleton
    with pytest.raises(RuntimeError, match="probe failure"):
        with route_pool_hooks():
            raise RuntimeError("probe failure")
    assert (
        epochal_hgs.complete_china81_route_skeleton,
        route_pool_sp.complete_china81_route_skeleton,
        route_pool_sp.exact_china81_score,
        route_pool_sp._single_route_cost,
    ) == originals
