from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import pytest

from dr_alns_ppo.async_block_policy import AsyncBlockPolicy, load_async_block_policy
from dr_alns_ppo.offline_bandit import (
    DEFAULT_SYSTEM_WORKER,
    MIN_BLOCK_ROWS,
    MIN_UNIQUE_FULL_ACTIONS,
    _checked_output_dir,
    _trace_fieldnames,
    comparison_integrity,
    run_train,
    summarize_action_coverage,
    summarize_dataset,
    verdict_from_comparison,
)


def _fake_trace_row(index: int) -> dict[str, object]:
    action = (index % 7, index % 4, index % 5, index % 4, index % 4)
    row: dict[str, object] = {
        "episode_index": 0,
        "bundle": "bundle",
        "seed": 1,
        "collection_policy": "random_block",
        "block_step_index": index,
        "eval_budget": 16,
        "block_size": 4,
        "action_destroy": action[0],
        "action_repair": action[1],
        "action_q": action[2],
        "action_threshold": action[3],
        "action_exploration": action[4],
        "decoded_destroy_id": "d",
        "decoded_repair_id": "r",
        "decoded_q_ratio": 0.1,
        "decoded_threshold_ratio": 0.0,
        "decoded_exploration_ratio": 0.0,
        "reward": float(index % 3) - 0.5,
        "block_best_delta": -1.0 if index % 3 == 0 else 0.0,
        "block_current_delta": -1.0,
        "block_best_route_delta": 0,
        "block_current_route_delta": 0,
        "block_accepted_count": 1,
        "block_rejected_count": 0,
        "block_improved_current_count": 1,
        "block_improved_best_count": 1 if index % 3 == 0 else 0,
        "block_iterations": 4,
        "actual_evals_before": index,
        "actual_evals_after": index + 1,
        "best_obj": 100.0 - index,
        "current_obj": 100.0 - index,
        "violation_count": 0,
        "worker_python_executable": DEFAULT_SYSTEM_WORKER,
        "worker_python_version": "3.13.0",
        "worker_numpy_version": "2.3.5",
    }
    for obs_idx in range(19):
        row[f"obs_{obs_idx:02d}"] = float(obs_idx) / 100.0
    return row


def _write_trace_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_trace_fieldnames())
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_offline_bandit_reports_stay_under_offline_dir(tmp_path: Path) -> None:
    allowed = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/offline_bandit/train")
    assert _checked_output_dir(allowed) == allowed

    with pytest.raises(ValueError, match="offline bandit reports"):
        _checked_output_dir(tmp_path)


def test_action_coverage_gate_detects_insufficient_rows() -> None:
    rows = [_fake_trace_row(idx) for idx in range(20)]

    coverage = summarize_action_coverage(rows)

    assert coverage["row_count"] == 20
    assert coverage["minimum_block_rows"] == MIN_BLOCK_ROWS
    assert coverage["minimum_unique_full_actions"] == MIN_UNIQUE_FULL_ACTIONS
    assert coverage["pass_minimum_coverage"] is False


def test_dataset_integrity_rejects_non_system_worker() -> None:
    rows = [_fake_trace_row(0)]
    rows[0]["worker_python_executable"] = "/tmp/venv/bin/python"
    args = argparse.Namespace(required_worker_python=DEFAULT_SYSTEM_WORKER, block_size=4, eval_budget=16)

    stats = summarize_dataset(rows, [], coverage=summarize_action_coverage(rows), elapsed_seconds=0.0, args=args)

    assert stats["integrity"]["system_worker"] is False
    assert stats["integrity"]["pass_collection_integrity"] is False


def test_offline_train_writes_async_loadable_pt_model(tmp_path: Path) -> None:
    dataset = tmp_path / "block_trace_rows.csv"
    rows = [_fake_trace_row(idx) for idx in range(64)]
    _write_trace_csv(dataset, rows)
    output_dir = tmp_path / "solver/reports/dr_alns_ppo_v3_block_dr_alns/offline_bandit/test_train"
    args = argparse.Namespace(
        dataset=str(dataset),
        output_dir=str(output_dir),
        seed=1,
        hidden_size=16,
        epochs=1,
        batch_size=16,
        learning_rate=1e-3,
        entropy_coef=0.0,
        value_coef=0.0,
        allow_insufficient_coverage=True,
    )

    rc = run_train(args)
    policy = load_async_block_policy(output_dir / "offline_policy.pt")
    action, state = policy.predict(np.zeros(19, dtype=np.float32), deterministic=True)

    assert rc == 0
    assert isinstance(policy, AsyncBlockPolicy)
    assert state is None
    assert action.shape == (5,)


def test_verdict_cannot_be_promising_when_ppo_loses_to_random() -> None:
    rows = []
    for seed in range(1, 11):
        for algorithm, best in {
            "ppo_block": 110.0,
            "random_block": 100.0,
            "alpha_ucb_block": 105.0,
            "official_winner_kernel": 95.0,
        }.items():
            rows.append(
                {
                    "algorithm": algorithm,
                    "bundle": "100-01",
                    "seed": seed,
                    "eval_budget": 16000,
                    "actual_evals": 16000,
                    "best_obj": best,
                    "violation_count": 0,
                    "worker_python_executable": DEFAULT_SYSTEM_WORKER,
                }
            )

    verdict = verdict_from_comparison(rows)

    assert verdict["status"] == "WEAK"


def test_comparison_integrity_rejects_underbudget_rows() -> None:
    rows = [
        {
            "algorithm": "ppo_block",
            "bundle": "100-01",
            "seed": 1,
            "eval_budget": 16000,
            "actual_evals": 128,
            "best_obj": 1.0,
            "violation_count": 0,
            "worker_python_executable": DEFAULT_SYSTEM_WORKER,
        }
    ]

    integrity = comparison_integrity(rows)

    assert integrity["pass"] is False
    assert "actual_evals" in integrity["reason"]


def test_offline_bandit_runner_does_not_call_formal_e1_e7() -> None:
    source = Path("solver/rl/dr_alns_ppo/offline_bandit.py").read_text(encoding="utf-8")

    assert "formal_runner" not in source
    assert "run_e1" not in source.lower()
    assert "run_e7" not in source.lower()
