from __future__ import annotations

from pathlib import Path

import pytest

from dr_alns_ppo.learned_destroy import learned_destroy_reward
from dr_alns_ppo.pilot20_learned_destroy_phaseA import DEFAULT_WORKER
from dr_alns_ppo.pilot21_learned_destroy_big import (
    DEFAULT_OUTPUT_DIR,
    parse_args,
    summarize_stage0,
    summarize_stage1,
    _write_big_report,
)
from dr_alns_ppo.worker_client import WorkerClient


FIXTURE_DIR = "models/data_bundle/generated_instances/verify_20251113"


def test_best_of_k_destroy_worker_evaluates_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    if not DEFAULT_WORKER.exists():
        pytest.skip("py313 solver worker is not available")
    monkeypatch.setenv("SETP_WORKER_PYTHON", str(DEFAULT_WORKER))
    client = WorkerClient(FIXTURE_DIR, seed=1, max_evals=5)
    try:
        reset = client.reset()
        response = client.best_of_k_destroy(
            {
                "candidate_k": 3,
                "destroy_ids": ["random_customer_removal"],
                "repair_id": "regret2_insert_repair",
                "q_ratio": 0.10,
                "threshold_ratio": 0.0025,
            }
        )
    finally:
        client.close()

    assert reset["ok"] is True
    assert response["ok"] is True
    assert response["trace"]["op"] == "best_of_k_destroy"
    assert response["trace"]["control_mode"] == "best_of_k_destroy"
    assert 1 <= response["trace"]["candidate_k_evaluated"] <= 3
    assert response["trace"]["actual_evals_added"] >= response["trace"]["candidate_k_evaluated"]
    assert response["actual_evals"] <= 5
    assert response["candidate_scores"] == response["actual_evals"]
    assert response["trace"]["worker_numpy_version"] == "2.3.5"


def test_learned_destroy_reward_penalizes_worse_current_candidate() -> None:
    response = {
        "best_obj": 100.0,
        "actual_evals": 1,
        "trace": {
            "block_start_best_obj": 100.0,
            "block_end_best_obj": 100.0,
            "block_start_current_obj": 100.0,
            "block_end_current_obj": 105.0,
            "block_accepted_count": 1,
            "block_rejected_count": 0,
            "candidate_violation_count": 0,
        },
    }

    reward = learned_destroy_reward(response, initial_obj=100.0, eval_budget=4, terminated=False)

    assert reward < 0.0


def test_stage0_gate_halts_without_destroy_headroom() -> None:
    rows = [
        _stage0_row("operator_select", 100.0),
        _stage0_row("worst_removal_fixed", 101.0),
        _stage0_row("best_of_k_destroy", 100.0),
    ]

    summary = summarize_stage0(rows)

    assert summary["gate_status"] == "HALT_NO_DESTROY_HEADROOM"
    assert summary["worker_integrity_ok"] is True


def test_stage1_gate_detects_flat_learner(tmp_path: Path) -> None:
    update_rows = [
        {"policy_loss": 0.1, "value_loss": 1.0, "entropy": 1.0, "approx_kl": 0.01},
        {"policy_loss": 0.1, "value_loss": 1.0, "entropy": 1.1, "approx_kl": 0.01},
    ]
    episode_rows = [{"reward_sum": 0.0}, {"reward_sum": 0.0}, {"reward_sum": 0.0}]

    summary = summarize_stage1(update_rows, episode_rows, tmp_path / "model.pt")

    assert summary["gate_status"] == "HALT_LEARNER_FLAT"


def test_parser_defaults_to_pilot21_report_dir() -> None:
    args = parse_args(["run"])

    assert args.output_dir == str(DEFAULT_OUTPUT_DIR)
    assert "resetp-solver-py313" in args.worker_python
    assert args.stage1_train_episodes == 1000


def test_big_report_is_written_for_halt(tmp_path: Path) -> None:
    report = tmp_path / "pilot21_big_report.md"
    _write_big_report(
        report,
        {
            "final_status": "HALT_NO_DESTROY_HEADROOM",
            "final_reason": "No scale had destroy headroom",
            "completed_stage": "stage0",
            "wall_time_seconds": 12.5,
            "stage0": {"gate_reason": "No scale had destroy headroom"},
        },
    )

    text = report.read_text(encoding="utf-8")
    assert "Final verdict: `HALT_NO_DESTROY_HEADROOM`" in text
    assert "Q1" in text
    assert "Q2" in text


def _stage0_row(algorithm: str, best_obj: float) -> dict[str, object]:
    return {
        "algorithm": algorithm,
        "bundle": "models/data_bundle/generated_instances/E-UK25_02__curric_d2_s0_seed3_24h",
        "scale": "25c",
        "seed": 1,
        "best_obj": best_obj,
        "worker_integrity_ok": True,
    }
