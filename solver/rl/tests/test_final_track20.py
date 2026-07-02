import math

from dr_alns_ppo.final_track20 import _summarize_action_sanity


def _row(seed: int, myopic: float, heuristic: float, *, health_status: str = "HEALTHY"):
    return {
        "bundle": "b",
        "seed": seed,
        "health_status": health_status,
        "myopic_information_cost": myopic,
        "heuristic_information_cost": heuristic,
    }


def test_track20_summary_detects_consistent_headroom_reduction():
    rows = [_row(seed, 100.0, 90.0) for seed in range(1, 21)]
    summary = _summarize_action_sanity(rows, planned_count=20, partial=False, reason="")

    assert summary["verdict"] == "HEURISTIC_MOVES_HEADROOM"
    assert math.isclose(summary["mean_information_cost_reduction_pct_of_myopic"], 10.0)
    assert summary["wins"] == 20


def test_track20_summary_flat_when_reduction_is_too_small():
    rows = [_row(seed, 100.0, 99.0) for seed in range(1, 21)]
    summary = _summarize_action_sanity(rows, planned_count=20, partial=False, reason="")

    assert summary["verdict"] == "HEURISTIC_FLAT"


def test_track20_summary_halts_on_unhealthy_heuristic_row():
    rows = [_row(1, 100.0, 90.0), _row(2, 100.0, 90.0, health_status="UNHEALTHY_DYNAMIC_FINAL")]
    summary = _summarize_action_sanity(rows, planned_count=2, partial=False, reason="")

    assert summary["verdict"] == "HALT_HEURISTIC_HEALTH"
    assert summary["health_failure_count"] == 1
