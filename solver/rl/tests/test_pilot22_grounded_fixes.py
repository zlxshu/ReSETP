from __future__ import annotations

from pathlib import Path

import pytest

from dr_alns_ppo.learned_destroy import learned_destroy_reward
from dr_alns_ppo.pilot20_learned_destroy_phaseA import PhaseAEpisode
from dr_alns_ppo.pilot22_grounded_fixes import (
    DEFAULT_OUTPUT_DIR,
    HALT_LEARNER_NO_VALIDATION_GAIN,
    HALT_POLICY_UNSTABLE,
    Pilot22Halt,
    flatten_pomo_shared_baseline,
    parse_args,
    summarize_stage_b,
    _enforce_resume_guard,
)


def test_learned_destroy_reward_uses_cao_discrete_5_3_1_0() -> None:
    assert learned_destroy_reward({"improved_best": True, "accepted": True, "actual_evals": 4}, initial_obj=100.0, eval_budget=4, terminated=False) == 5.0
    assert learned_destroy_reward({"improved_current": True, "accepted": True, "actual_evals": 4}, initial_obj=100.0, eval_budget=4, terminated=False) == 3.0
    assert learned_destroy_reward({"accepted": True, "actual_evals": 4}, initial_obj=100.0, eval_budget=4, terminated=False) == 1.0
    assert learned_destroy_reward({"accepted": False, "actual_evals": 4}, initial_obj=100.0, eval_budget=4, terminated=False) == 0.0
    assert learned_destroy_reward({"accepted": False, "actual_evals": 2}, initial_obj=100.0, eval_budget=4, terminated=True) == -2.0


def test_pomo_shared_baseline_advantages_are_group_centered() -> None:
    torch = pytest.importorskip("torch")
    group = [
        _episode([5.0, 5.0], seed=1),
        _episode([3.0, 3.0], seed=2),
    ]

    batch = flatten_pomo_shared_baseline([group])

    assert batch["global_obs"].shape[0] == 4
    assert torch.isclose(batch["advantages"].mean(), torch.tensor(0.0), atol=1e-6)
    assert set(batch) >= {"advantages", "returns", "old_log_probs", "selected_indices"}


def test_stage_b_gate_uses_validation_cost_not_entropy_drop(tmp_path: Path) -> None:
    update_rows = [
        {"policy_loss": 0.1, "value_loss": 1.0, "entropy": 1.0, "approx_kl": 0.01},
        {"policy_loss": 0.1, "value_loss": 1.0, "entropy": 5.0, "approx_kl": 0.01},
    ]
    validation_rows = [
        {"tag": "initial", "validation_mean_obj": 100.0, "validation_zero_violations": True},
        {"tag": "final", "validation_mean_obj": 96.0, "validation_gain_pct_vs_initial": 4.0, "validation_zero_violations": True},
    ]

    summary = summarize_stage_b(update_rows, [], validation_rows, tmp_path / "model.pt", threshold_pct=3.0)

    assert summary["gate_status"] == "G1_PASS"
    assert summary["entropy_last"] > summary["entropy_first"]


def test_stage_b_gate_halts_without_validation_gain(tmp_path: Path) -> None:
    update_rows = [{"policy_loss": 0.1, "value_loss": 1.0, "entropy": 2.0, "approx_kl": 0.01}]
    validation_rows = [
        {"tag": "initial", "validation_mean_obj": 100.0, "validation_zero_violations": True},
        {"tag": "final", "validation_mean_obj": 100.1, "validation_gain_pct_vs_initial": -0.1, "validation_zero_violations": True},
    ]

    summary = summarize_stage_b(update_rows, [], validation_rows, tmp_path / "model.pt", threshold_pct=3.0)

    assert summary["gate_status"] == HALT_LEARNER_NO_VALIDATION_GAIN


def test_stage_b_gate_halts_on_unstable_kl_even_with_prior_gain(tmp_path: Path) -> None:
    update_rows = [
        {"policy_loss": 0.1, "value_loss": 1.0, "entropy": 2.0, "approx_kl": 0.01},
        {"policy_loss": 0.1, "value_loss": 1.0, "entropy": 2.5, "approx_kl": 0.40},
    ]
    validation_rows = [
        {"tag": "initial", "validation_mean_obj": 100.0, "validation_zero_violations": True},
        {"tag": "best", "validation_mean_obj": 88.0, "validation_gain_pct_vs_initial": 12.0, "validation_zero_violations": True},
        {"tag": "final", "validation_mean_obj": 97.5, "validation_gain_pct_vs_initial": 2.5, "validation_zero_violations": True},
    ]

    summary = summarize_stage_b(update_rows, [], validation_rows, tmp_path / "model.pt", threshold_pct=3.0)

    assert summary["gate_status"] == HALT_POLICY_UNSTABLE


def test_resume_guard_blocks_halted_state() -> None:
    with pytest.raises(Pilot22Halt, match="HALT_RESUME_GUARD"):
        _enforce_resume_guard({"final_status": "HALT_LEARNER_FLAT"}, resume=True, force_exploratory=False)

    _enforce_resume_guard({"final_status": "HALT_LEARNER_FLAT"}, resume=True, force_exploratory=True)
    _enforce_resume_guard({"final_status": "HALT_LEARNER_FLAT"}, resume=False, force_exploratory=False)
    _enforce_resume_guard({"final_status": "HALT_WALL_CLOCK"}, resume=True, force_exploratory=False)


def test_parser_defaults_to_pilot22_report_dir() -> None:
    args = parse_args(["run"])

    assert args.output_dir == str(DEFAULT_OUTPUT_DIR)
    assert args.pomo_rollouts == 4
    assert args.validation_gain_threshold == 3.0


def _episode(rewards: list[float], *, seed: int) -> PhaseAEpisode:
    step_count = len(rewards)
    return PhaseAEpisode(
        algorithm="learned_destroy",
        bundle="bundle",
        seed=seed,
        eval_budget=step_count,
        best_obj=100.0,
        current_obj=100.0,
        actual_evals=step_count,
        candidate_scores=step_count,
        repair_delta_count=0,
        violation_count=0,
        feasible=True,
        wall_time_seconds=0.0,
        steps=step_count,
        rewards=rewards,
        values=[0.0 for _ in rewards],
        old_log_probs=[0.0 for _ in rewards],
        global_obs=[[0.0] * 24 for _ in rewards],
        customer_features=[[[0.0] * 18, [1.0] * 18] for _ in rewards],
        customer_masks=[[True, True] for _ in rewards],
        repair_actions=[0 for _ in rewards],
        q_actions=[0 for _ in rewards],
        threshold_actions=[0 for _ in rewards],
        selected_indices=[[0, 0] for _ in rewards],
        selected_counts=[1 for _ in rewards],
        trace={},
    )
