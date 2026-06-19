from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from dr_alns_ppo.async_block_policy import (
    AsyncBlockPolicy,
    make_block_actor_critic,
    load_async_block_policy,
    save_async_block_policy,
)
from dr_alns_ppo.evaluate_policy import _evaluate_one_task
from dr_alns_ppo.train_async_block_ppo import (
    AsyncEpisodeTask,
    compute_episode_advantages,
    filter_on_policy_episodes,
    flatten_episodes,
    ppo_update,
    run_actor_episode,
    _checked_output_dir,
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


def test_async_actor_returns_complete_tiny_trajectory(monkeypatch: pytest.MonkeyPatch) -> None:
    system_python = Path("/opt/anaconda3/bin/python3.13")
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
        policy_payload={
            "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
            "obs_dim": model.obs_dim,
            "action_nvec": model.action_nvec,
            "hidden_size": model.hidden_size,
        },
    )

    episode = run_actor_episode(task)

    assert episode["episode_index"] == 0
    assert episode["actual_evals"] == 8
    assert episode["violation_count"] == 0
    assert episode["block_steps"] >= 1
    assert len(episode["observations"]) == episode["block_steps"]
    assert len(episode["actions"]) == episode["block_steps"]
    assert episode["worker_python_executable"]


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
    }

    batch = flatten_episodes([episode], gamma=0.99, gae_lambda=0.95)
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
    )

    assert set(metrics) == {"policy_loss", "value_loss", "entropy", "approx_kl", "clip_fraction"}
    assert metrics["entropy"] > 0.0


def test_compute_episode_advantages_returns_same_length() -> None:
    advantages, returns = compute_episode_advantages([1.0, 2.0], [0.5, 0.25], gamma=0.99, gae_lambda=0.95)

    assert len(advantages) == 2
    assert len(returns) == 2
    assert returns[-1] == pytest.approx(2.0)


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
