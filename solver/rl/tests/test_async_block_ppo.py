from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
import torch

from dr_alns_ppo.async_block_policy import (
    AsyncBlockPolicy,
    _apply_action_masks,
    make_block_actor_critic,
    load_async_block_policy,
    save_async_block_policy,
)
from dr_alns_ppo.action_space import ALPHA_UCB_CHOICE, BLOCK_ACTION_NVECS, BLOCK_DESTROY_IDS, BLOCK_Q_RATIOS, BLOCK_REPAIR_IDS
from dr_alns_ppo.block_env import BlockAlnsEnv
from dr_alns_ppo.evaluate_policy import _evaluate_one_task
from dr_alns_ppo.train_async_block_ppo import (
    AsyncEpisodeTask,
    compute_episode_advantages,
    filter_on_policy_episodes,
    flatten_episodes,
    parse_args,
    ppo_update,
    run_actor_episode,
    _batch_to_device,
    _checked_output_dir,
    _cpu_probe_row,
    _expected_episode_steps,
    _phase_can_advance,
    _save_periodic_checkpoint,
)


FIXTURE_DIR = "models/data_bundle/generated_instances/verify_20251113"


def test_async_block_policy_predict_supports_multidiscrete_actions(tmp_path: Path) -> None:
    model = make_block_actor_critic(seed=1)
    path = tmp_path / "async_block_ppo_model.pt"
    save_async_block_policy(path, model, metadata={"policy_version": 3})

    policy = load_async_block_policy(path)
    action, state = policy.predict(np.zeros(19, dtype=np.float32), deterministic=True)

    assert state is None
    assert action.shape == (5,)
    assert action.dtype == np.int64
    assert policy.metadata["policy_version"] == 3


def test_action_masks_zero_invalid_policy_probability() -> None:
    model = make_block_actor_critic(seed=1)
    obs = torch.zeros((1, 19), dtype=torch.float32)
    masks = [[True for _ in range(n)] for n in BLOCK_ACTION_NVECS]
    masks[0][0] = False

    dists, _values = model.distributions(obs, masks=masks)

    assert dists[0].probs[0, 0].item() == pytest.approx(0.0)


def test_action_masks_none_matches_all_true_logits() -> None:
    model = make_block_actor_critic(seed=1)
    obs = torch.zeros((2, 19), dtype=torch.float32)
    all_true = [torch.ones((2, n), dtype=torch.bool) for n in BLOCK_ACTION_NVECS]

    logits_without, values_without = model.forward(obs)
    logits_with, values_with = model.forward(obs, masks=all_true)

    assert torch.allclose(values_without, values_with)
    for left, right in zip(logits_without, logits_with):
        assert torch.allclose(left, right)


def test_apply_action_masks_falls_back_when_head_is_all_false() -> None:
    logits = [torch.zeros((1, 3), dtype=torch.float32)]
    masked = _apply_action_masks(logits, [torch.zeros((1, 3), dtype=torch.bool)])

    assert masked[0][0, 0].item() == pytest.approx(0.0)
    assert masked[0][0, 1].item() < -1e8


def test_async_actor_returns_complete_tiny_trajectory(monkeypatch: pytest.MonkeyPatch) -> None:
    system_python = Path(os.environ.get("SETP_WORKER_PYTHON", "/opt/anaconda3/bin/python3.13"))
    if not system_python.exists():
        pytest.skip("system worker Python is not available")
    monkeypatch.setenv("SETP_WORKER_PYTHON", str(system_python))
    model = make_block_actor_critic(seed=1)
    task = AsyncEpisodeTask(
        episode_index=0,
        bundle=FIXTURE_DIR,
        seed=1,
        eval_budget=8,
        block_size=4,
        policy_version=0,
        deterministic=True,
        curriculum_phase="route",
        policy_payload={
            "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
            "obs_dim": model.obs_dim,
            "action_nvec": model.action_nvec,
            "hidden_size": model.hidden_size,
        },
    )

    episode = run_actor_episode(task)
    repeat = run_actor_episode(task)

    assert episode["episode_index"] == 0
    assert episode["actual_evals"] == 8
    assert episode["violation_count"] == 0
    assert episode["block_steps"] >= 1
    assert len(episode["observations"]) == episode["block_steps"]
    assert len(episode["actions"]) == episode["block_steps"]
    assert episode["worker_python_executable"]
    assert repeat["actions"] == episode["actions"]
    assert repeat["rewards"] == episode["rewards"]
    assert repeat["best_obj"] == episode["best_obj"]


def test_filter_on_policy_episodes_rejects_excessive_policy_lag() -> None:
    episodes = [{"policy_version": 4}, {"policy_version": 3}, {"policy_version": 1}]

    accepted, stale = filter_on_policy_episodes(episodes, current_policy_version=4, max_policy_lag=1)

    assert accepted == [{"policy_version": 4}, {"policy_version": 3}]
    assert stale == [{"policy_version": 1}]


def test_ppo_update_uses_old_log_probs_and_returns_metrics() -> None:
    model = make_block_actor_critic(seed=1)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    episode = {
        "observations": [[0.0] * 19, [0.1] * 19],
        "actions": [[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]],
        "rewards": [0.1, 0.2],
        "values": [0.0, 0.0],
        "old_log_probs": [-1.0, -1.1],
        "bundle": "A",
    }

    batch = flatten_episodes([episode], gamma=0.99, gae_lambda=0.95, advantage_clip_range=0.5)
    assert float(batch["advantages"].abs().max()) <= 0.5
    metrics = ppo_update(
        model,
        optimizer,
        batch,
        epochs=1,
        minibatch_size=2,
        clip_range=0.2,
        value_coef=0.5,
        entropy_coef=0.01,
        max_grad_norm=0.5,
        value_clip_range=0.1,
    )

    assert set(metrics) == {"policy_loss", "value_loss", "entropy", "approx_kl", "clip_fraction"}
    assert metrics["entropy"] > 0.0


def test_shared_baseline_subtracts_bundle_mean_before_normalization() -> None:
    episodes = []
    for bundle, reward in (("A", 1.0), ("A", 3.0), ("B", 10.0), ("B", 14.0)):
        episodes.append(
            {
                "observations": [[0.0] * 19],
                "actions": [[0, 0, 0, 0, 0]],
                "rewards": [reward],
                "values": [0.0],
                "old_log_probs": [-1.0],
                "bundle": bundle,
            }
        )

    batch = flatten_episodes(episodes, gamma=1.0, gae_lambda=1.0, shared_baseline_by_bundle=True)

    assert batch["returns"].tolist() == pytest.approx([-1.0, 1.0, -2.0, 2.0])
    assert int(batch["shared_baseline_group_count"]) == 2
    assert int(batch["shared_baseline_skipped_group_count"]) == 0


def test_batch_to_device_moves_tensor_lists() -> None:
    batch = {
        "obs": torch.zeros((1, 19), dtype=torch.float32),
        "action_masks": [torch.ones((1, n), dtype=torch.bool) for n in BLOCK_ACTION_NVECS],
        "label": "kept",
    }
    moved = _batch_to_device(batch, torch.device("cpu"))

    assert moved["obs"].device.type == "cpu"
    assert all(mask.device.type == "cpu" for mask in moved["action_masks"])
    assert moved["label"] == "kept"


def test_compute_episode_advantages_returns_same_length() -> None:
    advantages, returns = compute_episode_advantages([1.0, 2.0], [0.5, 0.25], gamma=0.99, gae_lambda=0.95)

    assert len(advantages) == 2
    assert len(returns) == 2
    assert returns[-1] == pytest.approx(2.0)


def test_periodic_checkpoint_helper_saves_only_on_due_update(tmp_path: Path) -> None:
    model = make_block_actor_critic(seed=1)

    skipped = _save_periodic_checkpoint(
        tmp_path,
        model,
        update_index=0,
        checkpoint_every_updates=2,
        metadata={"policy_version": 1},
    )
    saved = _save_periodic_checkpoint(
        tmp_path,
        model,
        update_index=1,
        checkpoint_every_updates=2,
        metadata={"policy_version": 2},
    )

    assert skipped == ""
    assert saved.endswith("checkpoints/async_block_ppo_update_0002.pt")
    assert Path(saved).exists()
    assert load_async_block_policy(saved).metadata["checkpoint_update_count"] == 2


def test_train_parser_exposes_checkpoint_interval() -> None:
    args = parse_args(["train", "--output-dir", "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/x"])

    assert args.checkpoint_every_updates == 10


def test_train_parser_exposes_meta_mode() -> None:
    args = parse_args(["train", "--meta-mode", "--output-dir", "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/x"])

    assert args.meta_mode is True


def test_expected_episode_steps_rounds_up_budget_blocks() -> None:
    assert _expected_episode_steps(16000, 128) == 125
    assert _expected_episode_steps(9, 4) == 3
    assert _expected_episode_steps(0, 4) == 1


def test_cpu_probe_row_includes_system_memory_fields() -> None:
    row = _cpu_probe_row(0.0)

    assert "system_memory_used_mb" in row
    assert "system_memory_available_mb" in row
    assert "system_memory_percent" in row
    assert float(row["system_memory_percent"]) >= 0.0


def test_curriculum_reward_phases_use_available_signals() -> None:
    response = {
        "best_obj": 90.0,
        "current_obj": 95.0,
        "violation_count": 0,
        "solution": {"routes": [{"vehicle_id": "EV1"}], "charging_actions": [{"vehicle_id": "EV1"}]},
        "metrics": {"cost_carbon": 10.0, "E_total": 50.0, "electricity_kwh": 12.0},
        "trace": {
            "block_start_best_obj": 100.0,
            "block_end_best_obj": 90.0,
            "block_start_current_obj": 100.0,
            "block_end_current_obj": 95.0,
            "block_best_route_delta": -1,
            "block_improved_best_count": 1,
            "block_improved_current_count": 1,
            "block_iterations": 4,
            "block_requested_q_ratio": 0.16,
            "block_requested_threshold_ratio": 0.0025,
        },
    }
    env = BlockAlnsEnv.__new__(BlockAlnsEnv)
    env.initial_obj = 100.0
    env.curriculum_phase = "route"
    route_reward = env._reward(dict(response), terminated=False)
    env.curriculum_phase = "energy"
    energy_reward = env._reward(dict(response), terminated=False)
    env.curriculum_phase = "carbon"
    carbon_response = dict(response)
    carbon_reward = env._reward(carbon_response, terminated=False)

    assert energy_reward > route_reward
    assert carbon_reward != energy_reward
    assert carbon_response["reward_components"]["fallback"] == ""


def test_curriculum_phase_gate_requires_minimum_and_stability() -> None:
    episodes = [
        {"curriculum_phase": "route", "bundle": "A", "best_obj": 10.0, "violation_count": 0},
        {"curriculum_phase": "route", "bundle": "B", "best_obj": 11.0, "violation_count": 0},
        {"curriculum_phase": "route", "bundle": "A", "best_obj": 9.0, "violation_count": 0},
        {"curriculum_phase": "route", "bundle": "B", "best_obj": 10.0, "violation_count": 0},
    ]
    assert not _phase_can_advance(episodes[:3], "route", min_episodes=4)
    assert _phase_can_advance(episodes, "route", min_episodes=4)
    bad = episodes + [{"curriculum_phase": "route", "bundle": "A", "best_obj": 20.0, "violation_count": 1}]
    assert not _phase_can_advance(bad, "route", min_episodes=4)


def test_block_env_action_mask_uses_named_rules_and_keeps_fallbacks() -> None:
    env = BlockAlnsEnv.__new__(BlockAlnsEnv)
    env.eval_budget = 100
    response = {
        "actual_evals": 90,
        "solution": {"routes": [{"vehicle_id": "CV1"}, {"vehicle_id": "CV2"}]},
        "metrics": {"n_veh_cv": 2, "n_veh_ev": 0},
        "trace": {
            "block_end_best_route_count": 2,
            "capacity_route_lower_bound": 2,
            "block_best_route_delta": 0,
            "block_iterations": 10,
            "block_rejected_count": 10,
            "block_improved_best_count": 0,
            "block_improved_current_count": 0,
            "stagnation_steps": 50,
        },
    }

    mask = env._action_mask(response)

    assert mask[0][BLOCK_DESTROY_IDS.index("vehicle_type_swap")] is False
    assert mask[0][BLOCK_DESTROY_IDS.index("whole_route_removal")] is False
    assert mask[0][BLOCK_DESTROY_IDS.index("route_segment_removal")] is False
    assert mask[2][len(BLOCK_Q_RATIOS) - 1] is False
    assert all(any(head) for head in mask)


def test_block_env_meta_mode_forces_alpha_ucb_operator_heads() -> None:
    env = BlockAlnsEnv.__new__(BlockAlnsEnv)
    env.eval_budget = 100
    env.meta_mode = True
    response = {
        "actual_evals": 90,
        "solution": {"routes": [{"vehicle_id": "CV1"}, {"vehicle_id": "CV2"}]},
        "metrics": {"n_veh_cv": 2, "n_veh_ev": 0},
        "trace": {
            "block_end_best_route_count": 2,
            "capacity_route_lower_bound": 2,
            "block_best_route_delta": 0,
            "block_iterations": 10,
            "block_rejected_count": 10,
            "block_improved_best_count": 0,
            "block_improved_current_count": 0,
            "stagnation_steps": 50,
        },
    }

    mask = env._action_mask(response)
    destroy_alpha = BLOCK_DESTROY_IDS.index(ALPHA_UCB_CHOICE)
    repair_alpha = BLOCK_REPAIR_IDS.index(ALPHA_UCB_CHOICE)

    assert mask[0] == [idx == destroy_alpha for idx in range(len(BLOCK_DESTROY_IDS))]
    assert mask[1] == [idx == repair_alpha for idx in range(len(BLOCK_REPAIR_IDS))]
    assert mask[2] == [True for _ in range(BLOCK_ACTION_NVECS[2])]
    assert mask[3] == [True for _ in range(BLOCK_ACTION_NVECS[3])]
    assert mask[4] == [True for _ in range(BLOCK_ACTION_NVECS[4])]


def test_async_actor_meta_mode_records_alpha_ucb_operator_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeEnv:
        def __init__(self, bundle, *, seed, eval_budget, block_size, curriculum_phase, meta_mode=False):
            self.meta_mode = meta_mode
            self.action_space = None
            self.last_response = {"best_obj": 1.0, "actual_evals": 0}

        def reset(self, *, seed=None):
            mask = [[True for _ in range(n)] for n in BLOCK_ACTION_NVECS]
            mask[0] = [idx == BLOCK_DESTROY_IDS.index(ALPHA_UCB_CHOICE) for idx in range(BLOCK_ACTION_NVECS[0])]
            mask[1] = [idx == BLOCK_REPAIR_IDS.index(ALPHA_UCB_CHOICE) for idx in range(BLOCK_ACTION_NVECS[1])]
            return np.zeros(19, dtype=np.float32), {"action_mask": mask}

        def step(self, action):
            self.last_response = {
                "best_obj": 1.0,
                "actual_evals": 4,
                "candidate_scores": 4,
                "repair_delta_count": 0,
                "violation_count": 0,
                "feasible": True,
                "trace": {
                    "worker_python_executable": "py",
                    "worker_python_version": "3.13",
                    "worker_numpy_version": "2.3.5",
                },
            }
            return np.zeros(19, dtype=np.float32), 0.0, True, False, self.last_response

        def close(self):
            pass

    monkeypatch.setattr("dr_alns_ppo.train_async_block_ppo.BlockAlnsEnv", FakeEnv)
    model = make_block_actor_critic(seed=1)
    task = AsyncEpisodeTask(
        episode_index=0,
        bundle=FIXTURE_DIR,
        seed=1,
        eval_budget=4,
        block_size=4,
        policy_version=0,
        deterministic=False,
        curriculum_phase="route",
        meta_mode=True,
        policy_payload={
            "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
            "obs_dim": model.obs_dim,
            "action_nvec": model.action_nvec,
            "hidden_size": model.hidden_size,
        },
    )

    episode = run_actor_episode(task)

    assert episode["actions"][0][0] == BLOCK_DESTROY_IDS.index(ALPHA_UCB_CHOICE)
    assert episode["actions"][0][1] == BLOCK_REPAIR_IDS.index(ALPHA_UCB_CHOICE)


def test_async_reports_stay_under_async_pilot_dir(tmp_path: Path) -> None:
    allowed = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/self_check")
    assert _checked_output_dir(allowed) == allowed

    with pytest.raises(ValueError, match="async PPO reports"):
        _checked_output_dir(tmp_path)


def test_evaluate_policy_loads_pt_async_block_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    model = make_block_actor_critic(seed=1)
    path = tmp_path / "model.pt"
    save_async_block_policy(path, model)

    seen: dict[str, object] = {}

    def fake_run_ppo_block_policy(model_obj, bundle_dir, *, seed, eval_budget, block_size, deterministic):
        seen["model_type"] = type(model_obj)
        return {
            "algorithm": "ppo_block",
            "bundle": bundle_dir,
            "seed": seed,
            "eval_budget": eval_budget,
            "best_obj": 1.0,
            "actual_evals": eval_budget,
            "candidate_scores": eval_budget,
            "repair_delta_count": 0,
            "operator_base_id": "winner_kernel_v1",
            "control_mode": "block_ppo",
            "violation_count": 0,
            "feasible": True,
            "solution_signature_hash": "x",
            "operator_counts": {},
            "destroy_counts": {},
            "repair_counts": {},
            "q_ratio_counts": {},
            "worker_python_executable": "/opt/anaconda3/bin/python3.13",
            "worker_python_version": "3.13.9",
            "worker_numpy_version": "2.3.5",
        }

    monkeypatch.setattr("dr_alns_ppo.evaluate_policy.run_ppo_block_policy", fake_run_ppo_block_policy)

    row = _evaluate_one_task(
        "ppo_block",
        FIXTURE_DIR,
        1,
        {
            "model_path": str(path),
            "eval_budget": 8,
            "base_temperature": 100.0,
            "deterministic": True,
            "official_max_runtime_seconds": 1.0,
            "block_size": 4,
        },
    )

    assert row["algorithm"] == "ppo_block"
    assert seen["model_type"] is AsyncBlockPolicy
