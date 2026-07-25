"""Tests for honest Chen-style trajectory construction and release."""

from __future__ import annotations

from types import SimpleNamespace

from baselines.e2_final_campaign_20260720.corrected_china81_rerun_20260723 import (
    run_corrected_s3_trajectories as trajectories,
)


def _patch_scoring(monkeypatch) -> None:
    monkeypatch.setattr(
        trajectories,
        "solution_from_payload",
        lambda payload: payload,
    )
    monkeypatch.setattr(
        trajectories,
        "complete_china81_route_skeleton",
        lambda payload, _bundle: SimpleNamespace(solution=payload),
    )
    monkeypatch.setattr(
        trajectories,
        "exact_china81_score",
        lambda payload, _bundle: (
            float(payload["cost"]),
            {},
            [],
        ),
    )


def test_curve_finishes_at_the_sealed_solution(monkeypatch) -> None:
    _patch_scoring(monkeypatch)
    curve, audit = trajectories.offline_points(
        [
            {
                "elapsed_seconds": 1.0,
                "source": "snapshot",
                "skeleton": {"cost": 90.0},
            }
        ],
        object(),
        100.0,
        2.0,
        80.0,
    )
    assert [row["cost"] for row in curve] == [
        100.0,
        90.0,
        80.0,
    ]
    assert curve[-1]["source"] == "sealed_final_solution"
    assert audit["historical_better_than_sealed"] is False
    assert audit["final_point_is_sealed"] is True
    assert audit["strict_decrease_count"] == 2


def test_curve_halts_when_retrospective_point_beats_sealed(
    monkeypatch,
) -> None:
    _patch_scoring(monkeypatch)
    curve, audit = trajectories.offline_points(
        [
            {
                "elapsed_seconds": 1.0,
                "source": "snapshot",
                "skeleton": {"cost": 70.0},
            }
        ],
        object(),
        100.0,
        2.0,
        80.0,
    )
    assert curve[-1]["cost"] == 70.0
    assert audit["historical_better_than_sealed"] is True
    assert audit["final_point_is_sealed"] is False


def test_shape_gate_requires_dense_genuine_decline() -> None:
    rows = [
        {
            "algorithm": "MV-HGS-SP",
            "curve_point_count": 8,
            "strict_decrease_count": 6,
            "elapsed_non_decreasing": True,
            "cost_monotone_non_increasing": True,
            "final_point_is_sealed": True,
            "historical_better_than_sealed": False,
        }
    ]
    checks = trajectories.trajectory_shape_checks(
        rows,
        minimum_points=8,
        minimum_decreases=6,
    )
    assert all(checks["MV-HGS-SP"].values())
    rows[0]["strict_decrease_count"] = 5
    checks = trajectories.trajectory_shape_checks(
        rows,
        minimum_points=8,
        minimum_decreases=6,
    )
    assert checks["MV-HGS-SP"][
        "strict_decrease_count_pass"
    ] is False
