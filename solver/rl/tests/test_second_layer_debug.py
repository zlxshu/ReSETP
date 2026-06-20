from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from dr_alns_ppo import second_layer_debug as dbg


def test_second_layer_output_path_guard() -> None:
    allowed = dbg.ensure_report_path(dbg.REPORT_DIR / "probe.csv")
    assert allowed.as_posix().endswith("solver/reports/dr_alns_ppo_v2/second_layer_debug/probe.csv")

    with pytest.raises(ValueError, match="second-layer debug output"):
        dbg.ensure_report_path("solver/reports/dr_alns_ppo_v2/outside_second_layer/probe.csv")


def test_observation_aliasing_detects_conflicting_reused_observation() -> None:
    rows = []
    base = {f"obs_{idx}": 0.0 for idx in range(dbg.OBSERVATION_SIZE)}
    for outcome in (False, True):
        row = {
            **base,
            "split": "formal_10001",
            "algorithm": "random_full",
            "destroy_id": "random_customer_removal",
            "repair_id": "regret2_insert_repair",
            "q_ratio": "0.100000",
            "improved_best": outcome,
        }
        rows.append(row)

    summary = dbg.summarize_observation_aliasing(rows)

    assert summary[0]["unique_obs_rounded"] == 1
    assert summary[0]["conflicting_obs_buckets"] == 1
    assert summary[0]["conflicting_obs_bucket_rate"] == pytest.approx(1.0)


def test_reward_summary_exposes_high_acceptance_low_best_improvement() -> None:
    rows = [
        {
            "split": "formal_10001",
            "algorithm": "ppo_full",
            "reward": 0.25,
            "accepted": True,
            "improved_current": True,
            "improved_best": False,
            "reward_code": "current_improved",
            "best_obj": 6000.0,
        }
        for _ in range(10)
    ]

    summary = dbg.summarize_reward_trace(rows)[0]

    assert summary["accepted_rate"] == pytest.approx(1.0)
    assert summary["improved_best_rate"] == pytest.approx(0.0)
    assert summary["mean_reward"] > 0.0


def test_second_layer_verdict_halts_current_ppo_when_random_is_much_better() -> None:
    verdict = dbg.build_second_layer_verdict(
        reward_summary=[
            {"algorithm": "ppo_full", "accepted_rate": "1.0", "improved_best_rate": "0.01"},
        ],
        obs_summary=[
            {"conflicting_obs_bucket_rate": "0.25"},
        ],
        ablation_summary=[
            {"split": "formal_10001", "algorithm": "ppo_full", "mean_best_obj": "6100"},
            {"split": "formal_10001", "algorithm": "random_full", "mean_best_obj": "4800"},
            {"split": "formal_10001", "algorithm": "alpha_ucb_env", "mean_best_obj": "4900"},
        ],
        entropy_rows=[
            {"top_prob": "0.999"},
        ],
        context={},
    )

    assert verdict["recommendation"] == "do_not_long_train_current_ppo"
    assert any(item["status"] == "confirmed" for item in verdict["hypotheses"])


def test_second_layer_runner_has_no_formal_experiment_calls() -> None:
    source = inspect.getsource(dbg)

    assert "formal_runner" not in source
    assert re.search(r"run_e[1-7]", source) is None
