from __future__ import annotations

import csv
from pathlib import Path

import pytest

from dr_alns_ppo.pilot23_stabilize import (
    HALT_TEST_SET_OVERLAP,
    PASS_CKPT_STATUS,
    STAGEB_REQUIRED_STATUS,
    WEAK_CKPT_STATUS,
    Pilot23Halt,
    best_validation_metadata,
    independent_test_overlap,
    linear_annealed_lr,
    parse_args,
    ppo_update_learned_stable,
    select_pilot22_peak_checkpoint,
    summarize_stage_a,
    summarize_stage_b,
    _enforce_resume_guard,
)


def test_selects_pilot22_peak_checkpoint_from_validation_csv(tmp_path: Path) -> None:
    validation_rows = tmp_path / "pilot22_validation_rows.csv"
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()
    _write_rows(
        validation_rows,
        [
            {"tag": "update_0120", "update_index": 119, "validation_gain_pct_vs_initial": 8.2, "validation_mean_obj": 777.1, "validation_zero_violations": True},
            {"tag": "update_0130", "update_index": 129, "validation_gain_pct_vs_initial": 11.5067, "validation_mean_obj": 749.2, "validation_zero_violations": True},
        ],
    )
    (checkpoint_dir / "pilot22_learned_destroy_update_0130.pt").write_bytes(b"ckpt")
    args = parse_args(["run", "--pilot22-validation-rows", str(validation_rows), "--pilot22-checkpoint-dir", str(checkpoint_dir)])

    peak = select_pilot22_peak_checkpoint(args)

    assert peak["tag"] == "update_0130"
    assert peak["checkpoint_path"].endswith("pilot22_learned_destroy_update_0130.pt")
    assert peak["validation_gain_pct_vs_initial"] == pytest.approx(11.5067)


def test_stage_a_gate_pass_requires_five_pct_all_scales_and_baselines() -> None:
    rows = _comparison_rows(learned_25=94.0, learned_50=93.0, operator=100.0, random_obj=102.0, worst=101.0)

    summary = summarize_stage_a(rows, pass_threshold=5.0, train_threshold=2.0)

    assert summary["gate_status"] == PASS_CKPT_STATUS
    assert summary["avg_vs_operator"] >= 5.0
    assert summary["preserves_plus_10"] is False


def test_stage_a_gate_routes_lt_two_to_stage_b_and_middle_to_weak() -> None:
    lt_two = summarize_stage_a(_comparison_rows(learned_25=99.0, learned_50=99.0, operator=100.0, random_obj=102.0, worst=101.0), pass_threshold=5.0, train_threshold=2.0)
    middle = summarize_stage_a(_comparison_rows(learned_25=97.0, learned_50=97.0, operator=100.0, random_obj=102.0, worst=101.0), pass_threshold=5.0, train_threshold=2.0)

    assert lt_two["gate_status"] == STAGEB_REQUIRED_STATUS
    assert middle["gate_status"] == WEAK_CKPT_STATUS


def test_independent_test_overlap_detects_pilot22_and_pilot23_overlap(tmp_path: Path) -> None:
    train_rows = tmp_path / "train.csv"
    validation_detail = tmp_path / "validation.csv"
    _write_rows(train_rows, [{"bundle": "bundle_train"}])
    _write_rows(validation_detail, [{"bundle": "bundle_validation"}])
    args = parse_args(
        [
            "run",
            "--test-bundles",
            "bundle_validation,bundle_test",
            "--stage-b-train-bundles",
            "bundle_train",
            "--validation-bundles",
            "bundle_val23",
            "--pilot22-training-rows",
            str(train_rows),
            "--pilot22-validation-detail-rows",
            str(validation_detail),
        ]
    )

    result = independent_test_overlap(args)

    assert result["overlap"] is True
    assert result["overlaps"]["pilot22_validation"] == ["bundle_validation"]


def test_ppo_update_stops_on_target_kl() -> None:
    torch = pytest.importorskip("torch")

    class DummyModel(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.weight = torch.nn.Parameter(torch.tensor(0.0))

        def evaluate_actions(self, global_obs, customer_features, customer_masks, repair_actions, q_actions, threshold_actions, selected_indices, selected_counts):
            count = int(global_obs.shape[0])
            log_probs = torch.ones(count) + self.weight * 0.0
            entropies = torch.ones(count) + self.weight * 0.0
            values = torch.zeros(count) + self.weight
            return log_probs, entropies, values

    model = DummyModel()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    batch = {
        "global_obs": torch.zeros((4, 2)),
        "customer_features": torch.zeros((4, 2, 2)),
        "customer_masks": torch.ones((4, 2), dtype=torch.bool),
        "repair_actions": torch.zeros(4, dtype=torch.long),
        "q_actions": torch.zeros(4, dtype=torch.long),
        "threshold_actions": torch.zeros(4, dtype=torch.long),
        "selected_indices": torch.zeros((4, 2), dtype=torch.long),
        "selected_counts": torch.ones(4, dtype=torch.long),
        "old_log_probs": torch.zeros(4),
        "advantages": torch.ones(4),
        "returns": torch.zeros(4),
    }

    metrics = ppo_update_learned_stable(
        model,
        optimizer,
        batch,
        epochs=3,
        minibatch_size=2,
        clip_range=0.1,
        value_coef=0.5,
        entropy_coef=0.01,
        max_grad_norm=0.5,
        target_kl=0.08,
    )

    assert metrics["kl_early_stop"] is True
    assert metrics["minibatch_count"] == 1
    assert metrics["approx_kl"] > 0.08


def test_lr_annealing_is_monotone_and_hits_endpoints() -> None:
    values = [linear_annealed_lr(initial_lr=1e-4, final_lr=1e-5, update_index=i, total_updates=4) for i in range(4)]

    assert values[0] == pytest.approx(1e-4)
    assert values[-1] == pytest.approx(1e-5)
    assert values == sorted(values, reverse=True)


def test_stage_b_gate_requires_stable_best_validation_and_kl(tmp_path: Path) -> None:
    stable = summarize_stage_b(
        [{"policy_loss": 0.1, "value_loss": 1.0, "entropy": 2.0, "approx_kl": 0.02}],
        [
            {"tag": "initial", "validation_mean_obj": 100.0, "validation_zero_violations": True},
            {"tag": "update_0010", "validation_mean_obj": 94.0, "validation_gain_pct_vs_initial": 6.0, "validation_zero_violations": True},
            {"tag": "final", "validation_mean_obj": 93.0, "validation_gain_pct_vs_initial": 7.0, "validation_zero_violations": True},
        ],
        tmp_path / "best.pt",
        threshold_pct=5.0,
        rollback_tolerance_pct=3.0,
        kl_ok_threshold=0.30,
        recent_count=2,
    )
    unstable = summarize_stage_b(
        [{"policy_loss": 0.1, "value_loss": 1.0, "entropy": 2.0, "approx_kl": 0.40}],
        [
            {"tag": "initial", "validation_mean_obj": 100.0, "validation_zero_violations": True},
            {"tag": "update_0010", "validation_mean_obj": 88.0, "validation_gain_pct_vs_initial": 12.0, "validation_zero_violations": True},
            {"tag": "final", "validation_mean_obj": 98.0, "validation_gain_pct_vs_initial": 2.0, "validation_zero_violations": True},
        ],
        tmp_path / "best.pt",
        threshold_pct=5.0,
        rollback_tolerance_pct=3.0,
        kl_ok_threshold=0.30,
        recent_count=2,
    )

    assert stable["gate_status"] == "G1_PASS"
    assert unstable["gate_status"] == "HALT_POLICY_UNSTABLE_V2"


def test_best_validation_metadata_points_to_selected_validation() -> None:
    metadata = best_validation_metadata(
        {"tag": "update_0130", "validation_mean_obj": 749.2, "validation_gain_pct_vs_initial": 11.5, "validation_zero_violations": True},
        update_index=129,
        group_index=32,
        reason="validation_mean_obj_improved",
    )

    assert metadata["tag"] == "update_0130"
    assert metadata["update_index"] == 129
    assert metadata["validation_gain_pct_vs_initial"] == pytest.approx(11.5)
    assert metadata["reason"] == "validation_mean_obj_improved"


def test_resume_guard_blocks_conclusive_state_but_allows_operational_resume() -> None:
    with pytest.raises(Pilot23Halt, match="HALT_RESUME_GUARD"):
        _enforce_resume_guard({"final_status": "HALT_POLICY_UNSTABLE_V2"}, resume=True)

    _enforce_resume_guard({"final_status": "HALT_WALL_CLOCK"}, resume=True)
    _enforce_resume_guard({"final_status": "HALT_POLICY_UNSTABLE_V2"}, resume=False)


def _comparison_rows(*, learned_25: float, learned_50: float, operator: float, random_obj: float, worst: float) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for bundle, scale, learned in (("bundle25", "25c", learned_25), ("bundle50", "50c", learned_50)):
        for algorithm, value in (
            ("learned_destroy", learned),
            ("operator_select", operator),
            ("random_operator", random_obj),
            ("worst_removal_fixed", worst),
        ):
            rows.append(
                {
                    "algorithm": algorithm,
                    "bundle": bundle,
                    "scale": scale,
                    "seed": 1,
                    "best_obj": value,
                    "violation_count": 0,
                    "worker_integrity_ok": True,
                }
            )
    return rows


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
