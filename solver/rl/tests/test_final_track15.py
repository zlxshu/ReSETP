from __future__ import annotations

import math

import pytest

from dr_alns_ppo.final_track15 import (
    Track15Halt,
    _enforce_resume_guard,
    baseline_health,
    summarize_final,
    summarize_track_a,
)


def test_baseline_health_requires_eval_change_improvement_and_feasibility() -> None:
    healthy = {
        "feasible": True,
        "violation_count": 0,
        "eval_ratio": 0.95,
        "returned_warm_start": False,
        "improvement_vs_warm_pct": 1.0,
    }

    assert baseline_health(healthy) == "HEALTHY"
    assert baseline_health({**healthy, "eval_ratio": 0.5}) == "UNHEALTHY_UNDER_EVAL"
    assert baseline_health({**healthy, "returned_warm_start": True}) == "UNHEALTHY_WARM_HASH"
    assert baseline_health({**healthy, "improvement_vs_warm_pct": 0.0}) == "UNHEALTHY_NO_IMPROVEMENT"
    assert baseline_health({**healthy, "violation_count": 1}) == "UNHEALTHY_VIOLATION"


def test_resume_guard_refuses_terminal_state() -> None:
    with pytest.raises(Track15Halt, match="refusing to resume"):
        _enforce_resume_guard({"final_status": "HALT_BASELINE_NOT_RUNNING"}, resume=True)

    _enforce_resume_guard({"final_status": "RUNNING"}, resume=True)
    _enforce_resume_guard({"final_status": "WIN_REAL"}, resume=False)


def test_track_a_verdicts_halt_win_and_margin_small() -> None:
    args = _Args()
    halted = summarize_track_a([_row("GA", "weak_baseline", 100.0, health="UNHEALTHY_WARM_HASH")], args)
    assert halted["verdict"] == "HALT_BASELINE_NOT_RUNNING"

    win_rows = [
        _row("plain_alns", "plain_alns", 100.0),
        _row("strong_method", "strong_method", 80.0),
        _row("GA", "weak_baseline", 100.0),
        _row("PSO", "weak_baseline", 100.0),
    ]
    assert summarize_track_a(win_rows, args)["verdict"] == "WIN_REAL"

    small_rows = [
        _row("plain_alns", "plain_alns", 100.0),
        _row("strong_method", "strong_method", 98.0),
        _row("GA", "weak_baseline", 100.0),
    ]
    assert summarize_track_a(small_rows, args)["verdict"] == "MARGIN_SMALL"


def test_final_summary_prioritizes_track_a_halt_and_win() -> None:
    assert summarize_final({"trackA": {"verdict": "WIN_REAL", "reason": "ok"}})["final_status"] == "WIN_REAL"
    assert (
        summarize_final({"trackA": {"verdict": "HALT_BASELINE_NOT_RUNNING", "reason": "bad"}})["final_status"]
        == "HALT_BASELINE_NOT_RUNNING"
    )
    assert summarize_final({"trackA": {"verdict": "MARGIN_SMALL", "reason": "short"}})["final_status"] == "MARGIN_SMALL"


class _Args:
    strong_plain_threshold_pct = 2.0
    weak_win_threshold_pct = 10.0


def _row(algorithm: str, role: str, cost: float, *, health: str = "HEALTHY") -> dict[str, object]:
    return {
        "bundle": "b",
        "seed": 1,
        "algorithm": algorithm,
        "role": role,
        "best_cost": cost,
        "health_status": health if role == "weak_baseline" else "NOT_BASELINE_GATE",
        "violation_count": 0,
        "feasible": True,
        "eval_ratio": 1.0,
        "improvement_vs_warm_pct": 1.0 if math.isfinite(cost) else 0.0,
    }
