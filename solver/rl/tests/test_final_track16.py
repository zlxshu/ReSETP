from __future__ import annotations

import math

import pytest

from dr_alns_ppo.final_track16 import (
    Track16Halt,
    _baseline_failure_diagnosis,
    _enforce_resume_guard,
    baseline_health,
    choose_main_method,
    summarize_final,
)


def test_baseline_health_requires_budget_hash_diversity_update_improvement_and_feasibility() -> None:
    healthy = {
        "feasible": True,
        "violation_count": 0,
        "eval_ratio": 0.95,
        "returned_warm_start": False,
        "unique_solution_count": 4,
        "best_update_count": 2,
        "improvement_vs_warm_pct": 1.0,
    }

    assert baseline_health(healthy) == "HEALTHY"
    assert baseline_health({**healthy, "eval_ratio": 0.5}) == "UNHEALTHY_UNDER_EVAL"
    assert baseline_health({**healthy, "returned_warm_start": True}) == "UNHEALTHY_WARM_HASH"
    assert baseline_health({**healthy, "unique_solution_count": 1}) == "UNHEALTHY_NO_DIVERSITY"
    assert baseline_health({**healthy, "best_update_count": 0}) == "UNHEALTHY_NO_BEST_UPDATE"
    assert baseline_health({**healthy, "improvement_vs_warm_pct": 0.0}) == "UNHEALTHY_NO_IMPROVEMENT"
    assert baseline_health({**healthy, "violation_count": 1}) == "UNHEALTHY_VIOLATION"


def test_baseline_failure_diagnosis_distinguishes_decode_collapse_from_no_improvement() -> None:
    collapsed = {"health_status": "UNHEALTHY_WARM_HASH", "returned_warm_start": True, "unique_solution_count": 1}
    diverse_no_best = {"health_status": "UNHEALTHY_WARM_HASH", "returned_warm_start": True, "unique_solution_count": 5}
    no_update = {"health_status": "UNHEALTHY_NO_BEST_UPDATE", "returned_warm_start": False, "best_update_count": 0}

    assert _baseline_failure_diagnosis(collapsed) == "decoded_solution_hash_collapsed_to_warm_start"
    assert _baseline_failure_diagnosis(diverse_no_best) == "candidate_hashes_varied_but_global_best_never_improved"
    assert _baseline_failure_diagnosis(no_update) == "score_ran_but_best_update_count_is_zero"


def test_choose_main_method_uses_lowest_feasible_mean_cost() -> None:
    rows = [
        _method("plain_alns", 100.0),
        _method("plain_alns", 102.0),
        _method("winner_kernel", 99.0),
        _method("winner_kernel", 101.0),
        _method("winner_kernel_local_search", 95.0),
        _method("winner_kernel_local_search", 96.0),
        {**_method("bad", 80.0), "feasible": False},
    ]

    assert choose_main_method(rows, default="winner_kernel") == "winner_kernel_local_search"


def test_resume_guard_refuses_terminal_state_only_on_resume() -> None:
    with pytest.raises(Track16Halt, match="refusing to resume"):
        _enforce_resume_guard({"final_status": "HALT_BASELINE_NOT_RUNNING"}, resume=True)

    _enforce_resume_guard({"final_status": "HALT_BASELINE_NOT_RUNNING"}, resume=False)
    _enforce_resume_guard({"final_status": "RUNNING"}, resume=True)


def test_final_summary_prioritizes_halts_then_fair_verdict() -> None:
    assert (
        summarize_final({"baseline_health": {"verdict": "HALT_BASELINE_NOT_RUNNING", "reason": "bad"}})["final_status"]
        == "HALT_BASELINE_NOT_RUNNING"
    )
    assert (
        summarize_final({"method_ablation": {"verdict": "HALT_MAIN_NOT_STRONG", "reason": "weak"}})["final_status"]
        == "HALT_MAIN_NOT_STRONG"
    )
    assert summarize_final({"fair_comparison": {"verdict": "WIN_REAL", "reason": "ok"}})["final_status"] == "WIN_REAL"
    assert summarize_final({"fair_comparison": {"verdict": "MARGIN_SMALL", "reason": "small"}})["final_status"] == "MARGIN_SMALL"


def _method(name: str, cost: float) -> dict[str, object]:
    return {
        "algorithm": name,
        "role": "method",
        "best_cost": cost,
        "feasible": math.isfinite(cost),
    }
