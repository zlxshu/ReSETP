from __future__ import annotations

from types import SimpleNamespace

import run_corrected_china81_d6_staged_portfolio as runner


def _stage(
    *,
    unique: int = 40,
    quality: int = 12,
    diversity: int = 12,
    snapshots: int = 20,
    references: int = 800,
) -> SimpleNamespace:
    return SimpleNamespace(
        stats={
            "historical_population_archive_enabled": True,
            "historical_population_snapshot_count": snapshots,
            "historical_population_candidate_references": references,
            "archive_unique_native_candidates": unique,
            "archive_candidate_limit": 24,
            "archive_quality_selected_count": quality,
            "archive_diversity_selected_count": diversity,
        }
    )


def _run(*, replacement: SimpleNamespace | None = None) -> SimpleNamespace:
    stages = [_stage() for _ in range(6)]
    if replacement is not None:
        stages[1] = replacement
    return SimpleNamespace(
        stages={
            "cv_only": (stages[0], stages[1]),
            "naive_ev": (stages[2], stages[3]),
            "mechanism_ev": (stages[4], stages[5]),
        }
    )


def test_small_archive_passes_when_every_available_candidate_is_selected():
    result = runner._history_integrity(
        _run(
            replacement=_stage(
                unique=20,
                quality=20,
                diversity=0,
            )
        )
    )

    assert result["snapshot_gate"]
    assert result["archive_use_gate"]
    assert result["snapshot_count"] == 120
    assert result["capacity_exhausted_stage_count"] == 1
    assert result["stage_rows"][1]["selection_complete"]
    assert result["stage_rows"][1][
        "diversity_requirement_satisfied"
    ]


def test_small_archive_fails_when_an_available_candidate_is_dropped():
    result = runner._history_integrity(
        _run(
            replacement=_stage(
                unique=20,
                quality=19,
                diversity=0,
            )
        )
    )

    assert not result["archive_use_gate"]
    assert not result["stage_rows"][1]["selection_complete"]


def test_full_archive_still_requires_a_diversity_remainder():
    result = runner._history_integrity(
        _run(
            replacement=_stage(
                unique=40,
                quality=24,
                diversity=0,
            )
        )
    )

    assert not result["archive_use_gate"]
    assert not result["stage_rows"][1][
        "diversity_requirement_satisfied"
    ]


def test_snapshot_count_gate_remains_exact():
    result = runner._history_integrity(
        _run(
            replacement=_stage(
                snapshots=19,
            )
        )
    )

    assert not result["snapshot_gate"]
    assert result["snapshot_count"] == 119
