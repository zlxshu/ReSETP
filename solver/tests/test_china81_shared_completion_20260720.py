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


def test_shared_completion_is_deterministic() -> None:
    bundle, skeleton = _fixture()

    left = complete_china81_route_skeleton(skeleton, bundle)
    right = complete_china81_route_skeleton(skeleton, bundle)

    assert left.solution == right.solution
    assert left.objective == right.objective
    assert left.activity == right.activity
