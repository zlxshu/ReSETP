import numpy as np

from dr_alns_ppo.block_env import BlockAlnsEnv
from dr_alns_ppo.env import SetpAlnsEnv


FIXTURE_DIR = "models/data_bundle/generated_instances/verify_20251113"


def test_env_reset_and_step_return_expected_shapes_and_eval_count() -> None:
    env = SetpAlnsEnv(FIXTURE_DIR, seed=1, eval_budget=5, base_temperature=100.0)
    try:
        obs, info = env.reset()
        next_obs, reward, terminated, truncated, step_info = env.step([0, 1, 3, 50])
    finally:
        env.close()

    assert obs.shape == (11,)
    assert next_obs.shape == (11,)
    assert obs.dtype == np.float32
    assert next_obs.dtype == np.float32
    assert info["actual_evals"] == 0
    assert step_info["actual_evals"] == 1
    assert step_info["candidate_scores"] == 1
    assert step_info["trace"]["operator_base_id"] == "winner_kernel_v1"
    assert list(env.action_space.nvec) == [6, 3, 10, 100]
    assert reward >= 0.0
    assert terminated is False
    assert truncated is False


def test_env_operator_only_accepts_two_component_actions_with_same_obs_shape() -> None:
    env = SetpAlnsEnv(FIXTURE_DIR, seed=1, eval_budget=5, base_temperature=100.0, control_mode="operator_only")
    try:
        obs, info = env.reset()
        next_obs, reward, terminated, truncated, step_info = env.step([5, 2])
    finally:
        env.close()

    assert obs.shape == (11,)
    assert next_obs.shape == (11,)
    assert list(env.action_space.nvec) == [6, 3]
    assert info["actual_evals"] == 0
    assert step_info["actual_evals"] == 1
    assert step_info["trace"]["control_mode"] == "operator_only"
    assert step_info["trace"]["threshold"] == 0.0
    assert reward >= 0.0
    assert terminated is False
    assert truncated is False


def test_env_reduced_full_accepts_coarse_four_component_actions() -> None:
    env = SetpAlnsEnv(FIXTURE_DIR, seed=1, eval_budget=5, base_temperature=100.0, control_mode="reduced_full")
    try:
        obs, info = env.reset()
        next_obs, reward, terminated, truncated, step_info = env.step([5, 1, 2, 2])
    finally:
        env.close()

    assert obs.shape == (11,)
    assert next_obs.shape == (11,)
    assert list(env.action_space.nvec) == [6, 3, 3, 3]
    assert info["actual_evals"] == 0
    assert step_info["actual_evals"] == 1
    assert step_info["trace"]["control_mode"] == "reduced_full"
    assert step_info["trace"]["q_ratio"] == 0.40
    assert step_info["trace"]["threshold_ratio"] == 0.02
    assert reward >= 0.0
    assert terminated is False
    assert truncated is False


def test_block_env_step_advances_multiple_candidate_evals() -> None:
    env = BlockAlnsEnv(FIXTURE_DIR, seed=1, eval_budget=20, block_size=4)
    try:
        obs, info = env.reset()
        next_obs, reward, terminated, truncated, step_info = env.step([0, 0, 0, 0, 0])
    finally:
        env.close()

    assert obs.shape == (19,)
    assert next_obs.shape == (19,)
    assert obs.dtype == np.float32
    assert next_obs.dtype == np.float32
    assert info["actual_evals"] == 0
    assert step_info["actual_evals"] >= 1
    assert step_info["trace"]["op"] == "block_step"
    assert step_info["trace"]["block_iterations"] >= 1
    assert step_info["trace"]["block_iterations"] <= 4
    assert list(env.action_space.nvec) == [6 + 1, 3 + 1, 5, 4, 4]
    assert np.isfinite(reward)
    assert terminated is False
    assert truncated is False
