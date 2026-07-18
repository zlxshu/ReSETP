from __future__ import annotations

import copy

import pytest

from baselines.e7_dynamic import e7_timing_clean_rerun_20260717 as rerun


def _payload(elapsed: float) -> dict[str, object]:
    return {
        "execution_status": "PASS",
        "rows": [{"stage": 1, "elapsed_seconds": elapsed}],
    }


def _fixture() -> tuple[
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
    list[dict[str, object]],
]:
    payloads: dict[str, dict[str, object]] = {}
    historical: dict[str, dict[str, object]] = {}
    contaminated: list[dict[str, object]] = []
    for index, task_id in enumerate(sorted(rerun.PARENT_CONTAMINATED)):
        historical[task_id] = _payload(20_000.0 + index * 100.0)
        payloads[task_id] = _payload(20_200.0 + index * 100.0)
        contaminated.append({"task_id": task_id, "stage": 1, "lineage": "parent"})
    for index, task_id in enumerate(sorted(rerun.CHILD_CONTAMINATED)):
        historical[task_id] = _payload(25_000.0 + index * 100.0)
        payloads[task_id] = _payload(19_000.0 + index * 100.0)
        contaminated.append({"task_id": task_id, "stage": 1, "lineage": "child"})
    return payloads, historical, contaminated


def test_paired_timing_acceptance_passes_two_declared_modes() -> None:
    payloads, historical, contaminated = _fixture()
    result = rerun.paired_timing_acceptance(
        payloads, historical, contaminated, rerun.EXPECTED_PAUSE_SECONDS
    )
    assert result["status"] == "PASS_PAIRED_TIMING_ACCEPTANCE_V2"
    assert result["parent_task_count"] == 4
    assert result["child_task_count"] == 5
    assert all(row["accepted"] for row in result["tasks"])


def test_parent_reproduction_outside_five_percent_halts() -> None:
    payloads, historical, contaminated = _fixture()
    task_id = sorted(rerun.PARENT_CONTAMINATED)[0]
    payloads[task_id] = _payload(22_000.0)
    with pytest.raises(rerun.RerunContractError, match="parent relative timing"):
        rerun.paired_timing_acceptance(
            payloads, historical, contaminated, rerun.EXPECTED_PAUSE_SECONDS
        )


def test_child_without_positive_removed_time_halts() -> None:
    payloads, historical, contaminated = _fixture()
    task_id = sorted(rerun.CHILD_CONTAMINATED)[0]
    payloads[task_id] = copy.deepcopy(historical[task_id])
    with pytest.raises(rerun.RerunContractError, match="positive time"):
        rerun.paired_timing_acceptance(
            payloads, historical, contaminated, rerun.EXPECTED_PAUSE_SECONDS
        )


def test_child_shift_outside_pause_anchored_cluster_halts() -> None:
    payloads, historical, contaminated = _fixture()
    task_id = sorted(rerun.CHILD_CONTAMINATED)[0]
    payloads[task_id] = _payload(15_000.0)
    with pytest.raises(rerun.RerunContractError, match="deviates from child median"):
        rerun.paired_timing_acceptance(
            payloads, historical, contaminated, rerun.EXPECTED_PAUSE_SECONDS
        )


def test_stage_elapsed_requires_one_positive_row() -> None:
    with pytest.raises(rerun.RerunContractError, match="exactly one"):
        rerun.stage_elapsed({"rows": []}, 1)
    with pytest.raises(rerun.RerunContractError, match="must be positive"):
        rerun.stage_elapsed({"rows": [{"stage": 1, "elapsed_seconds": 0.0}]}, 1)
