from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from dr_alns_ppo.learned_destroy import (
    LEARNED_CUSTOMER_FEATURE_DIM,
    customer_arrays,
    customer_feature_payload,
    decode_learned_destroy_action,
    global_observation_from_response,
)
from dr_alns_ppo.pilot20_learned_destroy_phaseA import (
    compute_episode_advantages,
    flatten_learned_episodes,
    parse_args,
    ppo_update_learned,
)
from dr_alns_ppo.schemas import LearnedDestroyDecodedAction
from dr_alns_ppo.worker_client import WorkerClient
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.construction import build_initial_solution


FIXTURE_DIR = "models/data_bundle/generated_instances/verify_20251113"
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_customer_feature_payload_is_finite_and_masks_current_solution_customers() -> None:
    bundle = load_search_bundle(REPO_ROOT / FIXTURE_DIR)
    solution = build_initial_solution(bundle.instance, bundle.carbon_profile, introduce_ev=False)

    payload = customer_feature_payload(solution, bundle.instance, bundle.carbon_profile)

    assert payload.feature_names
    assert len(payload.feature_names) == LEARNED_CUSTOMER_FEATURE_DIM
    assert len(payload.customer_ids) == len(payload.features) == len(payload.mask)
    assert any(payload.mask)
    assert np.asarray(payload.features, dtype=np.float32).shape[1] == LEARNED_CUSTOMER_FEATURE_DIM
    assert np.all(np.isfinite(np.asarray(payload.features, dtype=np.float32)))


def test_decode_learned_destroy_action_requires_fresh_single_step_features() -> None:
    with pytest.raises(ValueError, match="block_size=1"):
        decode_learned_destroy_action(
            {"repair_idx": 0, "q_idx": 0, "threshold_idx": 0, "selected_indices": [0], "selected_count": 1},
            customer_ids=["C1"],
            block_size=2,
        )

    decoded = decode_learned_destroy_action(
        {"repair_idx": 0, "q_idx": 0, "threshold_idx": 0, "selected_indices": [0], "selected_count": 1},
        customer_ids=["C1"],
        block_size=1,
    )

    assert decoded.control_mode == "learned_destroy"
    assert decoded.remove_customer_ids == ("C1",)


def test_learned_destroy_policy_samples_and_evaluates_pointer_actions() -> None:
    torch = pytest.importorskip("torch")
    from dr_alns_ppo.learned_destroy_policy import make_learned_destroy_actor_critic

    model = make_learned_destroy_actor_critic(seed=1, hidden_size=32)
    obs = np.zeros((24,), dtype=np.float32)
    features = np.zeros((8, LEARNED_CUSTOMER_FEATURE_DIM), dtype=np.float32)
    features[:, 0] = np.linspace(0.0, 1.0, 8)
    mask = np.array([True, True, True, True, False, False, False, False])

    decision = model.act(obs, features, mask, deterministic=False)
    selected = np.zeros((1, 8), dtype=np.int64)
    selected[0, : decision["selected_count"]] = decision["selected_indices"][: decision["selected_count"]]
    log_probs, entropies, values = model.evaluate_actions(
        torch.as_tensor(obs).unsqueeze(0),
        torch.as_tensor(features).unsqueeze(0),
        torch.as_tensor(mask).unsqueeze(0),
        torch.as_tensor([decision["repair_idx"]]),
        torch.as_tensor([decision["q_idx"]]),
        torch.as_tensor([decision["threshold_idx"]]),
        torch.as_tensor(selected),
        torch.as_tensor([decision["selected_count"]]),
    )

    assert decision["selected_count"] >= 1
    assert all(mask[idx] for idx in decision["selected_indices"][: decision["selected_count"]])
    assert torch.isfinite(log_probs).all()
    assert torch.isfinite(entropies).all()
    assert torch.isfinite(values).all()


def test_flatten_and_ppo_update_learned_batch() -> None:
    torch = pytest.importorskip("torch")
    from dr_alns_ppo.learned_destroy_policy import make_learned_destroy_actor_critic

    model = make_learned_destroy_actor_critic(seed=1, hidden_size=32)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    features = np.zeros((4, LEARNED_CUSTOMER_FEATURE_DIM), dtype=np.float32).tolist()
    episode = type(
        "Episode",
        (),
        {
            "rewards": [0.1, 0.2],
            "values": [0.0, 0.0],
            "old_log_probs": [-1.0, -1.1],
            "global_obs": [[0.0] * 24, [0.1] * 24],
            "customer_features": [features, features],
            "customer_masks": [[True, True, False, False], [True, True, False, False]],
            "repair_actions": [0, 1],
            "q_actions": [0, 0],
            "threshold_actions": [0, 1],
            "selected_indices": [[0, 0, 0, 0], [1, 0, 0, 0]],
            "selected_counts": [1, 1],
        },
    )()

    advantages, returns = compute_episode_advantages([0.1, 0.2], [0.0, 0.0], gamma=0.99, gae_lambda=0.95)
    batch = flatten_learned_episodes([episode], gamma=0.99, gae_lambda=0.95)
    metrics = ppo_update_learned(
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

    assert len(advantages) == len(returns) == 2
    assert batch["global_obs"].shape == (2, 24)
    assert set(metrics) == {"approx_kl", "clip_fraction", "entropy", "policy_loss", "value_loss"}


def test_worker_learned_destroy_branch_returns_customer_features(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SETP_WORKER_PYTHON", sys.executable)
    client = WorkerClient(FIXTURE_DIR, seed=1, max_evals=3)
    try:
        reset = client.reset()
        features, mask, customer_ids = customer_arrays(reset["customer_features"], max_customers=64)
        selected_idx = int(np.flatnonzero(mask)[0])
        response = client.block_step(
            LearnedDestroyDecodedAction(
                repair_id="greedy_insert_repair",
                q_ratio=0.10,
                threshold_ratio=0.0025,
                block_size=1,
                remove_customer_ids=(customer_ids[selected_idx],),
                raw=(0, selected_idx),
            )
        )
    finally:
        client.close()

    assert features.shape[1] == LEARNED_CUSTOMER_FEATURE_DIM
    assert response["ok"] is True
    assert response["actual_evals"] >= 1
    assert response["trace"]["control_mode"] == "learned_destroy"
    assert response["trace"]["destroy_id"] == "learned_customer_removal"
    assert response["customer_features"]["customer_ids"]
    obs = global_observation_from_response(response, eval_budget=3, bundle_dir=FIXTURE_DIR)
    assert obs.shape == (24,)
    assert np.all(np.isfinite(obs))


def test_pilot20_parser_defaults_to_phaseA_report_dir() -> None:
    args = parse_args([])

    assert "pilot20_learned_destroy_phaseA" in args.output_dir
    assert args.eval_budget == 80
