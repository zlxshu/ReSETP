from __future__ import annotations

import json
from pathlib import Path

import pytest

from dr_alns_ppo.pilot25_endgame import (
    HALT_BOTH,
    HALT_NO_VALIDATION_GAIN,
    PARTIAL_WIN,
    PASS_DR,
    PASS_STAGE1,
    Pilot25Halt,
    choose_strategy,
    load_pilot25_manifest,
    summarize_stage1,
    summarize_stage2,
    _enforce_resume_guard,
)


def test_resume_guard_blocks_conclusive_state_but_allows_fresh() -> None:
    with pytest.raises(Pilot25Halt, match="refusing to resume"):
        _enforce_resume_guard({"final_status": PARTIAL_WIN}, resume=True)

    _enforce_resume_guard({"final_status": PARTIAL_WIN}, resume=False)
    _enforce_resume_guard({"final_status": "HALT_WALL_CLOCK"}, resume=True)


def test_load_pilot25_manifest_takes_disjoint_complete_subset(tmp_path: Path) -> None:
    rows = {
        "train": [_bundle_row(tmp_path, "train_a", "train", 1), _bundle_row(tmp_path, "train_b", "train", 2)],
        "val": [_bundle_row(tmp_path, "val_a", "val", 3)],
        "test": [_bundle_row(tmp_path, "test_a", "test", 4)],
    }
    source = {
        "schema_version": "pilot24-data-generalization.v1",
        "scale_customers": 25,
        "splits": rows,
        "seed_ranges": {"train": {"min": 1, "max": 2, "count": 2}, "val": {"min": 3, "max": 3, "count": 1}, "test": {"min": 4, "max": 4, "count": 1}},
        "overlap": {"seed_overlap": {}, "path_overlap": {}},
    }
    path = tmp_path / "source.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    manifest = load_pilot25_manifest(path, train_count=1, val_count=1, test_count=1)

    assert manifest["schema_version"] == "pilot25-endgame-data.v1"
    assert len(manifest["splits"]["train"]) == 1
    assert manifest["validation"]["complete"] is True
    assert manifest["validation"]["overlap"] is False


def test_choose_strategy_prefers_lowest_mean_cost() -> None:
    rows = [
        {"strategy": "naive", "best_cost": 100.0},
        {"strategy": "naive", "best_cost": 102.0},
        {"strategy": "aware", "best_cost": 95.0},
        {"strategy": "aware", "best_cost": 97.0},
    ]

    assert choose_strategy(rows, default="aware") == "aware"


def test_stage1_gate_uses_average_validation_gain_and_zero_violations() -> None:
    passed = summarize_stage1(
        [
            {"validation_gain_pct_vs_initial": 3.2, "validation_zero_violations": True},
            {"validation_gain_pct_vs_initial": 4.0, "validation_zero_violations": True},
        ],
        learned_strategy="aware",
        threshold_pct=3.0,
    )
    failed = summarize_stage1(
        [{"validation_gain_pct_vs_initial": 1.0, "validation_zero_violations": True}],
        learned_strategy="aware",
        threshold_pct=3.0,
    )

    assert passed["gate_status"] == PASS_STAGE1
    assert failed["gate_status"] == HALT_NO_VALIDATION_GAIN


def test_stage2_verdicts_distinguish_dr_breakthrough_partial_and_halt() -> None:
    pass_rows = _stage2_rows(dr_cost=94.0, plain_cost=100.0, strong_cost=80.0, weak_costs=[100.0, 102.0])
    partial_rows = _stage2_rows(dr_cost=99.0, plain_cost=100.0, strong_cost=80.0, weak_costs=[100.0, 102.0])
    halt_rows = _stage2_rows(dr_cost=99.0, plain_cost=100.0, strong_cost=98.0, weak_costs=[100.0, 102.0])

    assert summarize_stage2(pass_rows, {"gate_status": PASS_STAGE1}, dr_threshold=5.0, weak_threshold=10.0)["status"] == PASS_DR
    assert summarize_stage2(partial_rows, {"gate_status": HALT_NO_VALIDATION_GAIN}, dr_threshold=5.0, weak_threshold=10.0)["status"] == PARTIAL_WIN
    assert summarize_stage2(halt_rows, {"gate_status": HALT_NO_VALIDATION_GAIN}, dr_threshold=5.0, weak_threshold=10.0)["status"] == HALT_BOTH


def _bundle_row(tmp_path: Path, name: str, split: str, seed: int) -> dict[str, object]:
    bundle = tmp_path / name
    bundle.mkdir()
    for file_name in ("instance.json", "distance_matrix.npy", "carbon_profile.csv", "nodes.csv"):
        (bundle / file_name).write_text("placeholder\n", encoding="utf-8")
    (bundle / "scenario_manifest.json").write_text(
        json.dumps({"validation": {"passed": True, "customer_count": 25}}),
        encoding="utf-8",
    )
    return {"split": split, "path": str(bundle), "scenario_id": name, "base_id": "E-UK25_02", "seed": seed, "n_customers": 25, "validation_passed": True}


def _stage2_rows(*, dr_cost: float, plain_cost: float, strong_cost: float, weak_costs: list[float]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {"group": "A", "algorithm": "learned_destroy", "bundle": "b", "seed": 1, "best_cost": dr_cost, "violation_count": 0, "worker_integrity_ok": True},
        {"group": "A", "algorithm": "operator_select", "bundle": "b", "seed": 1, "best_cost": plain_cost, "violation_count": 0, "worker_integrity_ok": True},
        {"group": "A", "algorithm": "plain_alns", "bundle": "b", "seed": 1, "best_cost": plain_cost, "violation_count": 0, "worker_integrity_ok": True},
        {"group": "A", "algorithm": "random_operator", "bundle": "b", "seed": 1, "best_cost": plain_cost + 1.0, "violation_count": 0, "worker_integrity_ok": True},
        {"group": "A", "algorithm": "worst_removal_fixed", "bundle": "b", "seed": 1, "best_cost": plain_cost + 2.0, "violation_count": 0, "worker_integrity_ok": True},
        {"group": "B", "algorithm": "strong_alns", "bundle": "b", "seed": 1, "best_cost": strong_cost, "violation_count": 0, "worker_integrity_ok": True},
    ]
    for index, value in enumerate(weak_costs):
        rows.append({"group": "B", "algorithm": f"weak{index}", "bundle": "b", "seed": 1, "best_cost": value, "violation_count": 0, "worker_integrity_ok": True})
    return rows
