import math

from dr_alns_ppo.final_track18 import _dynamic_health_status, _summarize_headroom


def test_dynamic_health_requires_positive_evaluations_and_feasibility():
    status = _dynamic_health_status(
        gate="",
        dynamic_feasible=True,
        static_feasible=True,
        stage_all_feasible=True,
        all_assertions_pass=True,
        information_cost=12.0,
        actual_evals=100,
    )
    assert status == "HEALTHY"

    status = _dynamic_health_status(
        gate="",
        dynamic_feasible=True,
        static_feasible=True,
        stage_all_feasible=True,
        all_assertions_pass=True,
        information_cost=12.0,
        actual_evals=0,
    )
    assert status == "UNHEALTHY_NO_EVALUATIONS"


def test_headroom_verdict_thresholds():
    rows = [
        {"bundle": "b1", "seed": 1, "scale": "25", "health_status": "HEALTHY", "information_cost_pct": 6.0},
        {"bundle": "b1", "seed": 2, "scale": "25", "health_status": "HEALTHY", "information_cost_pct": 4.0},
    ]
    summary = _summarize_headroom(rows, planned=[("b1", 1), ("b1", 2)], partial=False, reason="")
    assert summary["verdict"] == "HEADROOM_REAL"
    assert math.isclose(summary["mean_information_cost_pct"], 5.0)

    thin_rows = [
        {"bundle": "b1", "seed": 1, "scale": "25", "health_status": "HEALTHY", "information_cost_pct": 3.0},
        {"bundle": "b1", "seed": 2, "scale": "25", "health_status": "HEALTHY", "information_cost_pct": 3.0},
    ]
    thin = _summarize_headroom(thin_rows, planned=[("b1", 1), ("b1", 2)], partial=False, reason="")
    assert thin["verdict"] == "THIN_HEADROOM"

    flat_rows = [
        {"bundle": "b1", "seed": 1, "scale": "25", "health_status": "HEALTHY", "information_cost_pct": 1.0},
        {"bundle": "b1", "seed": 2, "scale": "25", "health_status": "HEALTHY", "information_cost_pct": 1.0},
    ]
    flat = _summarize_headroom(flat_rows, planned=[("b1", 1), ("b1", 2)], partial=False, reason="")
    assert flat["verdict"] == "HALT_NO_ANTICIPATION_HEADROOM"
