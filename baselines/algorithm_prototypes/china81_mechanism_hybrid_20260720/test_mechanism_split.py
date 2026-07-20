from __future__ import annotations

from pathlib import Path

from mechanism_split import mechanism_resource_split
from setp_solver.algorithms.resetp_alns.support.construction import (
    build_initial_solution,
)
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import (
    complete_china81_route_skeleton,
    exact_china81_score,
)


ROOT = Path(__file__).resolve().parents[3]


def test_mechanism_split_is_feasible_and_monotone() -> None:
    bundle = load_china81_bundle(
        ROOT,
        "cn-jjj-10c-01-V2-LOCATIONS",
    )
    skeleton = build_initial_solution(
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        introduce_ev=False,
        require_charging_signal=False,
    )
    incumbent = complete_china81_route_skeleton(
        skeleton,
        bundle,
    )

    split = mechanism_resource_split(
        incumbent.solution,
        bundle,
        max_route_orders=4,
    )

    objective, _, violations = exact_china81_score(
        split.solution,
        bundle,
    )
    assert not violations
    assert objective == split.objective
    assert objective <= incumbent.objective + 1.0e-9
    assert split.activity["segment_variant_evaluations"] > 0
    assert split.activity["decoded_route_orders"] > 0
