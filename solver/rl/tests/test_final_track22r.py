from __future__ import annotations

import pytest

from dr_alns_ppo import track22_endgame as track22


def _stage2_row(
    algorithm: str,
    *,
    scale: str = "25c",
    best_obj: float = 100.0,
    actual_evals: int = 2000,
    wall_time_seconds: float = 60.0,
    budget_status: str = "OK",
    probe_mode: str = "equal_steps_oracle",
) -> dict[str, object]:
    return {
        "algorithm": algorithm,
        "bundle": f"models/data_bundle/generated_instances/E-UK{scale[:-1]}_11",
        "scale": scale,
        "seed": 1201,
        "best_obj": best_obj,
        "actual_evals": actual_evals,
        "wall_time_seconds": wall_time_seconds,
        "worker_integrity_ok": True,
        "violation_count": 0,
        "budget_status": budget_status,
        "probe_mode": probe_mode,
    }


def _carbon_row(
    *,
    scale: str = "25c",
    carbon_cost_share_pct: float = 1.0,
    improvement_pct: float = 0.0,
    candidate_evaluate_count: int = 200,
    best_aware_cost: float = 99.0,
    naive_cost: float = 100.0,
    budget_status: str = "OK",
) -> dict[str, object]:
    return {
        "bundle": f"models/data_bundle/generated_instances/E-UK{scale[:-1]}_11",
        "scale": scale,
        "seed": 2901,
        "diagnostic_role": "default_winner_route_replay",
        "improvement_pct": improvement_pct,
        "candidate_evaluate_count": candidate_evaluate_count,
        "budget_status": budget_status,
        "carbon_cost_share_pct": carbon_cost_share_pct,
        "best_aware_cost": best_aware_cost,
        "naive_cost": naive_cost,
        "aware_violation_count": 0,
        "naive_violation_count": 0,
        "best_aware_violation_count": 0,
    }


def test_stage2_budget_status_marks_underpowered_rows() -> None:
    row = track22.annotate_stage2_budget(
        {
            "scale": "25c",
            "actual_evals": 80,
            "wall_time_seconds": 2.0,
            "probe_mode": "equal_steps_oracle",
        }
    )

    assert row["budget_status"] == track22.UNDERPOWERED
    assert float(row["eval_floor_ratio"]) < 1.0
    assert float(row["wall_floor_ratio"]) < 1.0


def test_stage2_verdict_refuses_underpowered_equal_step_rows() -> None:
    rows = [
        _stage2_row("operator_select", best_obj=100.0),
        _stage2_row("best_of_k_destroy", best_obj=97.0, budget_status=track22.UNDERPOWERED),
        _stage2_row("worst_removal_fixed", best_obj=101.0),
    ]

    with pytest.raises(track22.Track22Halt, match=track22.UNDERPOWERED):
        track22.summarize_stage2_destroy(rows)


def test_stage2_equal_eval_rows_are_reference_only() -> None:
    rows = [
        _stage2_row("operator_select", best_obj=100.0),
        _stage2_row("best_of_k_destroy", best_obj=100.5),
        _stage2_row("worst_removal_fixed", best_obj=101.0),
        _stage2_row(
            "best_of_k_destroy",
            best_obj=80.0,
            probe_mode="equal_eval_reference",
            actual_evals=80,
            wall_time_seconds=2.0,
            budget_status=track22.UNDERPOWERED,
        ),
    ]

    summary = track22.summarize_stage2_destroy(rows)

    assert summary["status"] == track22.NO_DESTROY_LEVERAGE_CLEAN
    assert summary["equal_eval_reference"]["row_count"] == 1


def test_carbon_summary_prioritizes_default_ceiling_before_improvement() -> None:
    rows = [
        _carbon_row(scale="25c", carbon_cost_share_pct=0.2, improvement_pct=5.0),
        _carbon_row(scale="50c", carbon_cost_share_pct=0.4, improvement_pct=5.0),
    ]

    summary = track22.summarize_carbon_rows(rows)

    assert summary["status"] == track22.CARBON_CEILING_TOO_SMALL_DEFAULT
    assert summary["default_carbon_ceiling_pct"] == pytest.approx(0.4)


def test_carbon_summary_refuses_aware_worse_than_naive() -> None:
    rows = [
        _carbon_row(
            carbon_cost_share_pct=2.0,
            best_aware_cost=101.0,
            naive_cost=100.0,
            improvement_pct=-1.0,
        )
    ]

    with pytest.raises(track22.Track22Halt, match="aware.*naive"):
        track22.summarize_carbon_rows(rows)


def test_ev_heavy_fleet_limits_keep_cv_available() -> None:
    limits = track22.ev_heavy_fleet_limits_for_counts(num_cv=5, num_ev=5, customer_count=25)

    assert limits.cv > 0
    assert limits.ev > 5
    assert "diagnostic" in limits.source


def test_best_of_k_equal_step_worker_cap_is_not_tight_budget() -> None:
    cap = track22.stage2_best_of_k_worker_eval_cap(step_count=2000, candidate_k=4)

    assert cap > 12010
    assert cap >= 100000


def test_track22r_default_25c_steps_clear_wall_clock_guard_band() -> None:
    args = track22.parse_args(["run"])

    assert args.stage2_25c_steps >= 4000
