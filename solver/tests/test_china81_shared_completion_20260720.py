from __future__ import annotations

from pathlib import Path

from setp_solver.algorithms.resetp_alns.support.construction import (
    build_initial_solution,
)
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import (
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.cost import route_departure_second
from setp_solver.solution import Route, Solution


ROOT = Path(__file__).resolve().parents[2]
INSTANCE_ID = "cn-jjj-10c-01-V2-LOCATIONS"


def _fixture():
    bundle = load_china81_bundle(ROOT, INSTANCE_ID)
    skeleton = build_initial_solution(
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        introduce_ev=False,
        require_charging_signal=False,
    )
    return bundle, skeleton


def test_shared_completion_is_feasible_monotone_and_complete() -> None:
    bundle, skeleton = _fixture()
    baseline, _, violations = exact_china81_score(skeleton, bundle)
    assert not violations

    result = complete_china81_route_skeleton(skeleton, bundle)

    final, breakdown, violations = exact_china81_score(
        result.solution,
        bundle,
    )
    assert not violations
    assert final == result.objective
    assert final <= baseline + 1.0e-9
    assert breakdown == result.breakdown
    assert result.activity["baseline_all_cv_cost"] == baseline
    assert result.activity["variant_count"] > 0
    assert result.activity["mechanism_experts_queried"] == [
        "vehicle_type_and_nonlinear_charging",
        "time_varying_electricity_and_carbon",
        "multi_depot_responsibility_accounting",
    ]
    routes = {
        route.vehicle_id: route
        for route in result.solution.routes
    }
    for action in result.solution.charging_actions:
        end = (
            float(action.charge_start_second)
            + float(action.occupancy_minutes) * 60.0
        )
        assert action.charge_day_offset == 0
        assert 0.0 <= action.charge_start_second < 86_400.0
        assert end <= route_departure_second(
            routes[action.vehicle_id],
            bundle.instance,
            bundle.prices,
        ) + 1.0e-9


def test_shared_completion_is_deterministic() -> None:
    bundle, skeleton = _fixture()

    left = complete_china81_route_skeleton(skeleton, bundle)
    right = complete_china81_route_skeleton(skeleton, bundle)

    assert left.solution == right.solution
    assert left.objective == right.objective
    assert left.activity == right.activity


def test_shared_completion_enforces_depot_vehicle_type_caps() -> None:
    bundle = load_china81_bundle(ROOT, INSTANCE_ID)
    customer_groups = [
        ["C004", "C006"],
        ["C002", "C001", "C009"],
        ["C005", "C010", "C007", "C003", "C008"],
    ]
    skeleton = Solution(
        routes=[
            Route(
                vehicle_id=f"R{index}",
                vehicle_type="cv",
                home_depot_id="D_beijing",
                node_sequence=[
                    "D_beijing",
                    *customers,
                    "D_beijing",
                ],
            )
            for index, customers in enumerate(
                customer_groups,
                start=1,
            )
        ]
    )

    result = complete_china81_route_skeleton(skeleton, bundle)
    _, _, violations = exact_china81_score(
        result.solution,
        bundle,
    )

    assert not violations
    assert sum(
        route.vehicle_type == "cv"
        for route in result.solution.routes
    ) == 2
    assert sum(
        route.vehicle_type == "ev"
        for route in result.solution.routes
    ) == 1
    assert result.activity["mandatory_fleet_assignment_count"] == 1
