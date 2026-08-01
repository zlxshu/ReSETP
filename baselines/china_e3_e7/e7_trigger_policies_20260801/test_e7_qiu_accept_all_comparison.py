from __future__ import annotations

from baselines.china_e3_e7.e7_trigger_policies_20260801.run_qiu_accept_all_comparison import (
    comparison_rows,
)
from baselines.china_e3_e7.e7_trigger_policies_20260801.trigger_policies import (
    FIXED_30_MINUTES,
    HYBRID_500KG_OR_30_MINUTES,
    PER_ORDER,
)


def _row(seed: int, policy: str, cost: float, distance: float) -> dict[str, object]:
    return {
        "stream_seed": seed,
        "policy": policy,
        "status": "PASS_ACCEPT_ALL",
        "final_delivery_cost_cny": cost,
        "distance_total_m": distance,
        "actual_vehicle_count": 4,
        "newly_used_vehicle_count": 2,
        "scheduled_trigger_count": 5,
        "actual_route_adjustment_count": 4,
        "total_emissions_kg": 20.0,
        "wall_seconds": 1.5,
    }


def test_pairwise_rows_keep_signed_differences_for_all_three_pairs() -> None:
    rows = [
        _row(1, PER_ORDER, 100.0, 1_000.0),
        _row(1, FIXED_30_MINUTES, 120.0, 1_200.0),
        _row(1, HYBRID_500KG_OR_30_MINUTES, 90.0, 900.0),
    ]

    compared = comparison_rows(rows)
    by_pair = {(row["left_policy"], row["right_policy"]): row for row in compared}

    assert len(compared) == 3
    hybrid_fixed = by_pair[(HYBRID_500KG_OR_30_MINUTES, FIXED_30_MINUTES)]
    assert hybrid_fixed["cost_delta_cny"] == -30.0
    assert hybrid_fixed["cost_delta_pct"] == -25.0
    assert hybrid_fixed["distance_delta_m"] == -300.0
    assert hybrid_fixed["left_cost_outcome"] == "win"


def test_pairwise_rows_are_withheld_if_any_policy_is_not_legal() -> None:
    rows = [
        _row(1, PER_ORDER, 100.0, 1_000.0),
        _row(1, FIXED_30_MINUTES, 120.0, 1_200.0),
        {**_row(1, HYBRID_500KG_OR_30_MINUTES, 90.0, 900.0), "status": "HALT_STAGE_FAILURE"},
    ]

    assert comparison_rows(rows) == []
