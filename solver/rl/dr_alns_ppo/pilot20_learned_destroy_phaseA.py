from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
try:
    import torch
    from torch import nn
except ModuleNotFoundError:  # pragma: no cover - solver-only venvs can still import parser/helpers.
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]

from .action_space import (
    ALPHA_UCB_CHOICE,
    BLOCK_DESTROY_IDS,
    BLOCK_EXPLORATION_RATIOS,
    BLOCK_Q_RATIOS,
    BLOCK_REPAIR_IDS,
    BLOCK_THRESHOLD_RATIOS,
    DESTROY_IDS,
    REPAIR_IDS,
)
from .learned_destroy import (
    customer_arrays,
    decode_learned_destroy_action,
    global_observation_from_response,
    learned_destroy_reward,
)
try:
    from .learned_destroy_policy import LearnedDestroyActorCritic, make_learned_destroy_actor_critic, save_learned_destroy_policy
except ModuleNotFoundError:  # pragma: no cover - solver-only venvs can still import parser/helpers.
    LearnedDestroyActorCritic = Any  # type: ignore[misc,assignment]
    make_learned_destroy_actor_critic = None  # type: ignore[assignment]
    save_learned_destroy_policy = None  # type: ignore[assignment]
from .schemas import BlockDecodedAction
from .worker_client import WorkerClient


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot20_learned_destroy_phaseA")
DEFAULT_WORKER = Path(r"C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe")
REQUIRED_WORKER_NUMPY = "2.3.5"
DEFAULT_TRAIN_BUNDLES = (
    "models/data_bundle/generated_instances/E-UK25_02__curric_d2_s3_seed2_24h",
    "models/data_bundle/generated_instances/E-UK25_03__curric_d2_s3_seed3_24h",
    "models/data_bundle/generated_instances/E-UK25_04__curric_d2_s3_seed4_24h",
    "models/data_bundle/generated_instances/E-UK25_05__curric_d2_s3_seed5_24h",
    "models/data_bundle/generated_instances/E-UK25_06__curric_d2_s3_seed6_24h",
    "models/data_bundle/generated_instances/E-UK25_07__curric_d2_s3_seed7_24h",
    "models/data_bundle/generated_instances/E-UK50_01__curric_d2_s3_seed1_24h",
    "models/data_bundle/generated_instances/E-UK50_02__curric_d2_s3_seed2_24h",
    "models/data_bundle/generated_instances/E-UK50_03__curric_d2_s3_seed3_24h",
)
DEFAULT_HELD_OUT_BUNDLES = (
    "models/data_bundle/generated_instances/E-UK25_08__curric_d2_s3_seed8_24h",
    "models/data_bundle/generated_instances/E-UK25_09__curric_d2_s3_seed9_24h",
    "models/data_bundle/generated_instances/E-UK50_04__curric_d2_s3_seed4_24h",
)


@dataclass(frozen=True)
class PhaseAEpisode:
    algorithm: str
    bundle: str
    seed: int
    eval_budget: int
    best_obj: float
    current_obj: float
    actual_evals: int
    candidate_scores: int
    repair_delta_count: int
    violation_count: int
    feasible: bool
    wall_time_seconds: float
    steps: int
    rewards: list[float]
    values: list[float]
    old_log_probs: list[float]
    global_obs: list[list[float]]
    customer_features: list[list[list[float]]]
    customer_masks: list[list[bool]]
    repair_actions: list[int]
    q_actions: list[int]
    threshold_actions: list[int]
    selected_indices: list[list[int]]
    selected_counts: list[int]
    trace: dict[str, Any]


class LearnedDestroySession:
    def __init__(self, bundle: str, *, seed: int, eval_budget: int, max_customers: int) -> None:
        self.bundle = str(bundle)
        self.seed = int(seed)
        self.eval_budget = int(eval_budget)
        self.max_customers = int(max_customers)
        self.client = WorkerClient(self.bundle, seed=self.seed, max_evals=self.eval_budget)
        self.response: dict[str, Any] | None = None
        self.initial_obj: float | None = None

    def reset(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
        self.response = _checked(self.client.reset())
        self.initial_obj = float(self.response.get("best_obj", 0.0))
        return self._state_arrays(self.response)

    def step(self, raw_action: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str], float, bool, dict[str, Any]]:
        if self.response is None:
            raise RuntimeError("session must be reset before step")
        _features, _mask, customer_ids = customer_arrays(self.response.get("customer_features", {}), max_customers=self.max_customers)
        decoded = decode_learned_destroy_action(raw_action, customer_ids=customer_ids, block_size=1)
        response = _checked(self.client.block_step(decoded))
        self.response = response
        terminated = int(response.get("actual_evals", 0)) >= self.eval_budget
        reward = learned_destroy_reward(
            response,
            initial_obj=self.initial_obj,
            eval_budget=self.eval_budget,
            terminated=terminated,
        )
        obs, features, mask, ids = self._state_arrays(response)
        return obs, features, mask, ids, reward, terminated, response

    def close(self) -> None:
        self.client.close()

    def _state_arrays(self, response: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
        obs = global_observation_from_response(
            response,
            eval_budget=self.eval_budget,
            bundle_dir=self.bundle,
            curriculum_phase="route",
        )
        features, mask, customer_ids = customer_arrays(response.get("customer_features", {}), max_customers=self.max_customers)
        return obs, features, mask, customer_ids


def run_learned_episode(
    model: LearnedDestroyActorCritic,
    bundle: str,
    *,
    seed: int,
    eval_budget: int,
    max_customers: int,
    deterministic: bool,
) -> PhaseAEpisode:
    started = time.monotonic()
    session = LearnedDestroySession(bundle, seed=int(seed), eval_budget=int(eval_budget), max_customers=int(max_customers))
    global_obs_rows: list[list[float]] = []
    customer_feature_rows: list[list[list[float]]] = []
    customer_mask_rows: list[list[bool]] = []
    repair_actions: list[int] = []
    q_actions: list[int] = []
    threshold_actions: list[int] = []
    selected_indices_rows: list[list[int]] = []
    selected_counts: list[int] = []
    rewards: list[float] = []
    values: list[float] = []
    old_log_probs: list[float] = []
    final_response: dict[str, Any] = {}
    try:
        obs, features, mask, _customer_ids = session.reset()
        terminated = False
        while not terminated:
            decision = model.act(obs, features, mask, deterministic=bool(deterministic))
            selected = _pad_selected(decision["selected_indices"], int(max_customers))
            global_obs_rows.append(np.asarray(obs, dtype=np.float32).tolist())
            customer_feature_rows.append(np.asarray(features, dtype=np.float32).tolist())
            customer_mask_rows.append(np.asarray(mask, dtype=bool).tolist())
            repair_actions.append(int(decision["repair_idx"]))
            q_actions.append(int(decision["q_idx"]))
            threshold_actions.append(int(decision["threshold_idx"]))
            selected_indices_rows.append(selected)
            selected_counts.append(int(decision["selected_count"]))
            values.append(float(decision["value"]))
            old_log_probs.append(float(decision["log_prob"]))
            raw = {
                "repair_idx": int(decision["repair_idx"]),
                "q_idx": int(decision["q_idx"]),
                "threshold_idx": int(decision["threshold_idx"]),
                "selected_indices": selected,
                "selected_count": int(decision["selected_count"]),
            }
            obs, features, mask, _customer_ids, reward, terminated, final_response = session.step(raw)
            rewards.append(float(reward))
    finally:
        session.close()
    return _episode_from_response(
        "learned_destroy",
        bundle,
        seed=seed,
        eval_budget=eval_budget,
        started=started,
        response=final_response,
        rewards=rewards,
        values=values,
        old_log_probs=old_log_probs,
        global_obs=global_obs_rows,
        customer_features=customer_feature_rows,
        customer_masks=customer_mask_rows,
        repair_actions=repair_actions,
        q_actions=q_actions,
        threshold_actions=threshold_actions,
        selected_indices=selected_indices_rows,
        selected_counts=selected_counts,
    )


def run_operator_select_episode(bundle: str, *, seed: int, eval_budget: int) -> dict[str, Any]:
    alpha_d = BLOCK_DESTROY_IDS.index(ALPHA_UCB_CHOICE)
    alpha_r = BLOCK_REPAIR_IDS.index(ALPHA_UCB_CHOICE)
    q_idx = BLOCK_Q_RATIOS.index(0.40)
    threshold_idx = BLOCK_THRESHOLD_RATIOS.index(0.0025)
    exploration_idx = BLOCK_EXPLORATION_RATIOS.index(0.15)
    action = BlockDecodedAction(
        destroy_id=ALPHA_UCB_CHOICE,
        repair_id=ALPHA_UCB_CHOICE,
        q_ratio=0.40,
        threshold_ratio=0.0025,
        exploration_ratio=0.15,
        block_size=1,
        raw=(alpha_d, alpha_r, q_idx, threshold_idx, exploration_idx),
    )
    return _run_block_baseline("operator_select", bundle, seed=seed, eval_budget=eval_budget, action_factory=lambda _rng: action)


def run_random_episode(bundle: str, *, seed: int, eval_budget: int) -> dict[str, Any]:
    def action_factory(rng: np.random.Generator) -> BlockDecodedAction:
        d_idx = int(rng.integers(0, len(DESTROY_IDS)))
        r_idx = int(rng.integers(0, len(REPAIR_IDS)))
        q_idx = int(rng.integers(0, len(BLOCK_Q_RATIOS)))
        threshold_idx = int(rng.integers(0, len(BLOCK_THRESHOLD_RATIOS)))
        exploration_idx = 0
        return BlockDecodedAction(
            destroy_id=DESTROY_IDS[d_idx],
            repair_id=REPAIR_IDS[r_idx],
            q_ratio=float(BLOCK_Q_RATIOS[q_idx]),
            threshold_ratio=float(BLOCK_THRESHOLD_RATIOS[threshold_idx]),
            exploration_ratio=0.0,
            block_size=1,
            raw=(d_idx, r_idx, q_idx, threshold_idx, exploration_idx),
        )

    return _run_block_baseline("random_operator", bundle, seed=seed, eval_budget=eval_budget, action_factory=action_factory)


def collect_training_episode(
    model: LearnedDestroyActorCritic,
    train_bundles: list[str],
    *,
    episode_index: int,
    base_seed: int,
    eval_budget: int,
    max_customers: int,
) -> PhaseAEpisode:
    bundle = train_bundles[int(episode_index) % len(train_bundles)]
    seed = int(base_seed) + int(episode_index)
    return run_learned_episode(
        model,
        bundle,
        seed=seed,
        eval_budget=int(eval_budget),
        max_customers=int(max_customers),
        deterministic=False,
    )


def flatten_learned_episodes(
    episodes: list[PhaseAEpisode],
    *,
    gamma: float,
    gae_lambda: float,
) -> dict[str, torch.Tensor]:
    _require_torch_available()
    global_obs: list[list[float]] = []
    customer_features: list[list[list[float]]] = []
    customer_masks: list[list[bool]] = []
    repair_actions: list[int] = []
    q_actions: list[int] = []
    threshold_actions: list[int] = []
    selected_indices: list[list[int]] = []
    selected_counts: list[int] = []
    old_log_probs: list[float] = []
    old_values: list[float] = []
    advantages: list[float] = []
    returns: list[float] = []
    for episode in episodes:
        ep_adv, ep_returns = compute_episode_advantages(episode.rewards, episode.values, gamma=gamma, gae_lambda=gae_lambda)
        global_obs.extend(episode.global_obs)
        customer_features.extend(episode.customer_features)
        customer_masks.extend(episode.customer_masks)
        repair_actions.extend(episode.repair_actions)
        q_actions.extend(episode.q_actions)
        threshold_actions.extend(episode.threshold_actions)
        selected_indices.extend(episode.selected_indices)
        selected_counts.extend(episode.selected_counts)
        old_log_probs.extend(episode.old_log_probs)
        old_values.extend(episode.values)
        advantages.extend(ep_adv)
        returns.extend(ep_returns)
    if not global_obs:
        raise ValueError("no learned-destroy rollout steps")
    adv_tensor = torch.as_tensor(advantages, dtype=torch.float32)
    adv_std = adv_tensor.std(unbiased=False)
    adv_tensor = (adv_tensor - adv_tensor.mean()) / (adv_std + 1e-8) if float(adv_std) > 1e-8 else adv_tensor - adv_tensor.mean()
    return {
        "global_obs": torch.as_tensor(global_obs, dtype=torch.float32),
        "customer_features": torch.as_tensor(customer_features, dtype=torch.float32),
        "customer_masks": torch.as_tensor(customer_masks, dtype=torch.bool),
        "repair_actions": torch.as_tensor(repair_actions, dtype=torch.long),
        "q_actions": torch.as_tensor(q_actions, dtype=torch.long),
        "threshold_actions": torch.as_tensor(threshold_actions, dtype=torch.long),
        "selected_indices": torch.as_tensor(selected_indices, dtype=torch.long),
        "selected_counts": torch.as_tensor(selected_counts, dtype=torch.long),
        "old_log_probs": torch.as_tensor(old_log_probs, dtype=torch.float32),
        "old_values": torch.as_tensor(old_values, dtype=torch.float32),
        "advantages": adv_tensor,
        "returns": torch.as_tensor(returns, dtype=torch.float32),
    }


def ppo_update_learned(
    model: LearnedDestroyActorCritic,
    optimizer: torch.optim.Optimizer,
    batch: dict[str, torch.Tensor],
    *,
    epochs: int,
    minibatch_size: int,
    clip_range: float,
    value_coef: float,
    entropy_coef: float,
    max_grad_norm: float,
) -> dict[str, float]:
    _require_torch_available()
    sample_count = int(batch["global_obs"].shape[0])
    metrics: list[dict[str, float]] = []
    for _epoch in range(int(epochs)):
        permutation = torch.randperm(sample_count)
        for start in range(0, sample_count, int(minibatch_size)):
            idx = permutation[start : start + int(minibatch_size)]
            log_probs, entropies, values = model.evaluate_actions(
                batch["global_obs"][idx],
                batch["customer_features"][idx],
                batch["customer_masks"][idx],
                batch["repair_actions"][idx],
                batch["q_actions"][idx],
                batch["threshold_actions"][idx],
                batch["selected_indices"][idx],
                batch["selected_counts"][idx],
            )
            old_log_probs = batch["old_log_probs"][idx]
            advantages = batch["advantages"][idx]
            returns = batch["returns"][idx]
            ratio = torch.exp(log_probs - old_log_probs)
            unclipped = ratio * advantages
            clipped = torch.clamp(ratio, 1.0 - float(clip_range), 1.0 + float(clip_range)) * advantages
            policy_loss = -torch.minimum(unclipped, clipped).mean()
            value_loss = nn.functional.mse_loss(values, returns)
            entropy = entropies.mean()
            loss = policy_loss + float(value_coef) * value_loss - float(entropy_coef) * entropy
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), float(max_grad_norm))
            optimizer.step()
            with torch.no_grad():
                approx_kl = (old_log_probs - log_probs).mean().abs()
                clip_fraction = ((ratio - 1.0).abs() > float(clip_range)).float().mean()
            metrics.append(
                {
                    "policy_loss": float(policy_loss.detach()),
                    "value_loss": float(value_loss.detach()),
                    "entropy": float(entropy.detach()),
                    "approx_kl": float(approx_kl.detach()),
                    "clip_fraction": float(clip_fraction.detach()),
                }
            )
    return _mean_metrics(metrics)


def run_phase_a(args: argparse.Namespace) -> int:
    _require_torch_available()
    worker_python = _ensure_worker_env(args.worker_python)
    output_dir = Path(args.output_dir)
    _require_report_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    train_bundles, held_bundles = _load_or_default_manifest(args.manifest)
    model = make_learned_destroy_actor_critic(seed=int(args.seed), hidden_size=int(args.hidden_size))
    optimizer = torch.optim.Adam(model.parameters(), lr=float(args.learning_rate))
    config = vars(args).copy()
    config["train_bundles"] = train_bundles
    config["held_out_bundles"] = held_bundles
    config["required_worker_python"] = worker_python
    config["required_worker_numpy"] = REQUIRED_WORKER_NUMPY
    _write_json(output_dir / "pilot20_phaseA_config.json", config)

    training_episodes: list[PhaseAEpisode] = []
    update_rows: list[dict[str, Any]] = []
    for episode_index in range(int(args.train_episodes)):
        episode = collect_training_episode(
            model,
            train_bundles,
            episode_index=episode_index,
            base_seed=int(args.seed),
            eval_budget=int(args.eval_budget),
            max_customers=int(args.max_customers),
        )
        training_episodes.append(episode)
        if (episode_index + 1) % int(args.rollout_min_episodes) == 0:
            batch = flatten_learned_episodes(
                training_episodes[-int(args.rollout_min_episodes) :],
                gamma=float(args.gamma),
                gae_lambda=float(args.gae_lambda),
            )
            metrics = ppo_update_learned(
                model,
                optimizer,
                batch,
                epochs=int(args.ppo_epochs),
                minibatch_size=int(args.minibatch_size),
                clip_range=float(args.clip_range),
                value_coef=float(args.value_coef),
                entropy_coef=float(args.entropy_coef),
                max_grad_norm=float(args.max_grad_norm),
            )
            update_rows.append({"update_index": len(update_rows), "episode_index": episode_index, **metrics})
            _write_csv(output_dir / "pilot20_update_log.csv", update_rows)

    model_path = output_dir / "learned_destroy_phaseA_model.pt"
    save_learned_destroy_policy(
        model_path,
        model,
        metadata={"train_episodes": int(args.train_episodes), "eval_budget": int(args.eval_budget)},
    )
    held_seeds = _parse_int_list(args.heldout_seeds)
    rows: list[dict[str, Any]] = []
    for bundle in held_bundles:
        for seed in held_seeds:
            learned = run_learned_episode(
                model,
                bundle,
                seed=int(seed),
                eval_budget=int(args.eval_budget),
                max_customers=int(args.max_customers),
                deterministic=True,
            )
            rows.append(_episode_row(learned))
            if not bool(args.skip_baselines):
                rows.append(run_operator_select_episode(bundle, seed=int(seed), eval_budget=int(args.eval_budget)))
                rows.append(run_random_episode(bundle, seed=int(seed), eval_budget=int(args.eval_budget)))
            _write_csv(output_dir / "pilot20_phaseA_rows.csv", rows)

    verdict = _verdict(rows)
    report = {
        "schema_version": "pilot20-learned-destroy-phaseA.v1",
        "model_path": str(model_path),
        "verdict": verdict,
        "config": config,
        "update_rows": update_rows,
        "rows": rows,
    }
    _write_json(output_dir / "pilot20_phaseA_report.json", report)
    _write_report_md(output_dir / "pilot20_phaseA_report.md", report)
    _write_csv(output_dir / "pilot20_training_episode_log.csv", [_episode_row(ep) for ep in training_episodes])
    return 0 if verdict["status"] in {"PASS_LEARNED_DESTROY", "WEAK_LEARNED_DESTROY"} else 2


def compute_episode_advantages(
    rewards: list[float],
    values: list[float],
    *,
    gamma: float,
    gae_lambda: float,
) -> tuple[list[float], list[float]]:
    if len(rewards) != len(values):
        raise ValueError("rewards and values length mismatch")
    advantages = [0.0 for _ in rewards]
    last_gae = 0.0
    next_value = 0.0
    for idx in reversed(range(len(rewards))):
        nonterminal = 0.0 if idx == len(rewards) - 1 else 1.0
        delta = float(rewards[idx]) + float(gamma) * next_value * nonterminal - float(values[idx])
        last_gae = delta + float(gamma) * float(gae_lambda) * nonterminal * last_gae
        advantages[idx] = last_gae
        next_value = float(values[idx])
    returns = [float(advantage + value) for advantage, value in zip(advantages, values)]
    return advantages, returns


def _require_torch_available() -> None:
    if torch is None or nn is None or make_learned_destroy_actor_critic is None or save_learned_destroy_policy is None:
        raise RuntimeError(
            "Pilot20 learned-destroy training requires torch. Use "
            "C:\\Users\\zlxshu\\.venvs\\resetp-ppo-cu124-py312\\Scripts\\python.exe for the runner "
            "and keep SETP_WORKER_PYTHON pointed at the py313 solver worker."
        )


def _ensure_worker_env(worker_python: str | Path | None = None) -> str:
    required = Path(worker_python or DEFAULT_WORKER).resolve()
    if not required.exists():
        raise RuntimeError(f"HALT_WORKER_INTEGRITY: required py313 worker does not exist: {required}")
    configured = os.environ.get("SETP_WORKER_PYTHON", "").strip()
    if configured:
        resolved = Path(configured).resolve()
        if resolved != required:
            raise RuntimeError(
                f"HALT_WORKER_INTEGRITY: SETP_WORKER_PYTHON must be {required}, got {resolved}"
            )
    else:
        os.environ["SETP_WORKER_PYTHON"] = str(required)
    return str(required)


def _run_block_baseline(
    algorithm: str,
    bundle: str,
    *,
    seed: int,
    eval_budget: int,
    action_factory: Any,
) -> dict[str, Any]:
    started = time.monotonic()
    rng = np.random.default_rng(int(seed))
    client = WorkerClient(bundle, seed=int(seed), max_evals=int(eval_budget))
    response: dict[str, Any] = {}
    steps = 0
    try:
        response = _checked(client.reset())
        while int(response.get("actual_evals", 0)) < int(eval_budget):
            response = _checked(client.block_step(action_factory(rng)))
            steps += 1
    finally:
        client.close()
    trace = dict((response.get("trace", {}) if isinstance(response, dict) else {}) or {})
    return {
        "algorithm": algorithm,
        "bundle": bundle,
        "scale": _scale_label(bundle),
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "best_obj": float(response.get("best_obj", 0.0)),
        "current_obj": float(response.get("current_obj", 0.0)),
        "actual_evals": int(response.get("actual_evals", 0)),
        "candidate_scores": int(response.get("candidate_scores", 0)),
        "repair_delta_count": int(response.get("repair_delta_count", 0)),
        "violation_count": int(response.get("violation_count", 1)),
        "feasible": int(response.get("violation_count", 1)) == 0,
        "wall_time_seconds": float(time.monotonic() - started),
        "steps": int(steps),
        "worker_python_executable": str(trace.get("worker_python_executable", "")),
        "worker_numpy_version": str(trace.get("worker_numpy_version", "")),
        "worker_integrity_ok": _worker_integrity_ok(trace),
    }


def _episode_from_response(
    algorithm: str,
    bundle: str,
    *,
    seed: int,
    eval_budget: int,
    started: float,
    response: dict[str, Any],
    rewards: list[float],
    values: list[float],
    old_log_probs: list[float],
    global_obs: list[list[float]],
    customer_features: list[list[list[float]]],
    customer_masks: list[list[bool]],
    repair_actions: list[int],
    q_actions: list[int],
    threshold_actions: list[int],
    selected_indices: list[list[int]],
    selected_counts: list[int],
) -> PhaseAEpisode:
    trace = dict((response.get("trace", {}) if isinstance(response, dict) else {}) or {})
    return PhaseAEpisode(
        algorithm=algorithm,
        bundle=str(bundle),
        seed=int(seed),
        eval_budget=int(eval_budget),
        best_obj=float(response.get("best_obj", 0.0)),
        current_obj=float(response.get("current_obj", 0.0)),
        actual_evals=int(response.get("actual_evals", 0)),
        candidate_scores=int(response.get("candidate_scores", 0)),
        repair_delta_count=int(response.get("repair_delta_count", 0)),
        violation_count=int(response.get("violation_count", 1)),
        feasible=int(response.get("violation_count", 1)) == 0,
        wall_time_seconds=float(time.monotonic() - started),
        steps=len(rewards),
        rewards=list(rewards),
        values=list(values),
        old_log_probs=list(old_log_probs),
        global_obs=list(global_obs),
        customer_features=list(customer_features),
        customer_masks=list(customer_masks),
        repair_actions=list(repair_actions),
        q_actions=list(q_actions),
        threshold_actions=list(threshold_actions),
        selected_indices=list(selected_indices),
        selected_counts=list(selected_counts),
        trace=trace,
    )


def _episode_row(episode: PhaseAEpisode) -> dict[str, Any]:
    return {
        "algorithm": episode.algorithm,
        "bundle": episode.bundle,
        "scale": _scale_label(episode.bundle),
        "seed": int(episode.seed),
        "eval_budget": int(episode.eval_budget),
        "best_obj": float(episode.best_obj),
        "current_obj": float(episode.current_obj),
        "actual_evals": int(episode.actual_evals),
        "candidate_scores": int(episode.candidate_scores),
        "repair_delta_count": int(episode.repair_delta_count),
        "violation_count": int(episode.violation_count),
        "feasible": bool(episode.feasible),
        "wall_time_seconds": float(episode.wall_time_seconds),
        "steps": int(episode.steps),
        "reward_sum": float(sum(episode.rewards)),
        "worker_python_executable": str(episode.trace.get("worker_python_executable", "")),
        "worker_numpy_version": str(episode.trace.get("worker_numpy_version", "")),
        "worker_integrity_ok": _worker_integrity_ok(episode.trace),
    }


def _verdict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    learned = [row for row in rows if row.get("algorithm") == "learned_destroy"]
    operator = [row for row in rows if row.get("algorithm") == "operator_select"]
    random_rows = [row for row in rows if row.get("algorithm") == "random_operator"]
    operator_by_key = {(row["bundle"], int(row["seed"])): row for row in operator}
    random_by_key = {(row["bundle"], int(row["seed"])): row for row in random_rows}
    improvements: list[float] = []
    random_improvements: list[float] = []
    by_scale: dict[str, list[float]] = {}
    for row in learned:
        key = (row["bundle"], int(row["seed"]))
        base = operator_by_key.get(key)
        if base is not None and float(base["best_obj"]) > 0:
            value = (float(base["best_obj"]) - float(row["best_obj"])) / max(abs(float(base["best_obj"])), 1.0) * 100.0
            improvements.append(value)
            by_scale.setdefault(str(row["scale"]), []).append(value)
        random_base = random_by_key.get(key)
        if random_base is not None and float(random_base["best_obj"]) > 0:
            random_improvements.append(
                (float(random_base["best_obj"]) - float(row["best_obj"])) / max(abs(float(random_base["best_obj"])), 1.0) * 100.0
            )
    avg = _mean(improvements)
    min_scale = min((_mean(values) for values in by_scale.values()), default=math.nan)
    avg_vs_random = _mean(random_improvements)
    zero_violations = all(int(row.get("violation_count", 1)) == 0 for row in learned)
    worker_integrity_ok = all(bool(row.get("worker_integrity_ok", False)) for row in rows)
    if not worker_integrity_ok:
        status = "HALT_WORKER_INTEGRITY"
    elif zero_violations and avg >= 2.0 and min_scale >= 0.0 and (not random_improvements or avg_vs_random > 0.0):
        status = "PASS_LEARNED_DESTROY"
    elif zero_violations and avg >= 0.0 and min_scale >= 0.0:
        status = "WEAK_LEARNED_DESTROY"
    else:
        status = "HALT_LEARNED_DESTROY"
    return {
        "status": status,
        "heldout_avg_improvement_pct_vs_operator_select": float(avg),
        "min_scale_improvement_pct_vs_operator_select": float(min_scale) if math.isfinite(min_scale) else None,
        "heldout_avg_improvement_pct_vs_random": float(avg_vs_random) if math.isfinite(avg_vs_random) else None,
        "zero_violation_learned": bool(zero_violations),
        "worker_integrity_ok": bool(worker_integrity_ok),
        "required_worker_python": str(DEFAULT_WORKER),
        "required_worker_numpy": REQUIRED_WORKER_NUMPY,
        "scale_improvement_pct": {scale: _mean(values) for scale, values in sorted(by_scale.items())},
        "rule": "PASS if held-out avg >= 2%, every scale >= 0%, learned beats random on average, learned has zero violations, and all rows use the py313/NumPy 2.3.5 worker; WEAK if 0-2%; otherwise HALT.",
    }


def _load_or_default_manifest(path_text: str | None) -> tuple[list[str], list[str]]:
    if path_text:
        payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
        return [str(value) for value in payload["train"]], [str(value) for value in payload["held_out"]]
    return list(DEFAULT_TRAIN_BUNDLES), list(DEFAULT_HELD_OUT_BUNDLES)


def _parse_int_list(text: str) -> list[int]:
    values = [int(part.strip()) for part in str(text).split(",") if part.strip()]
    if not values:
        raise ValueError("seed list cannot be empty")
    return values


def _pad_selected(values: Any, width: int) -> list[int]:
    result = [0 for _ in range(int(width))]
    raw = [int(value) for value in np.asarray(values, dtype=np.int64).reshape(-1).tolist()]
    for idx, value in enumerate(raw[: int(width)]):
        result[idx] = int(value)
    return result


def _mean(values: list[float]) -> float:
    if not values:
        return math.nan
    return float(sum(float(value) for value in values) / len(values))


def _mean_metrics(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {"policy_loss": 0.0, "value_loss": 0.0, "entropy": 0.0, "approx_kl": 0.0, "clip_fraction": 0.0}
    keys = sorted(rows[0])
    return {key: _mean([float(row[key]) for row in rows]) for key in keys}


def _scale_label(bundle: str) -> str:
    text = str(bundle)
    for scale in (25, 50, 75, 100, 150, 200):
        if f"UK{scale}" in text or f"{scale}c" in text:
            return f"{scale}c"
    return "unknown"


def _worker_integrity_ok(trace: dict[str, Any]) -> bool:
    executable = str(trace.get("worker_python_executable", "") or "")
    numpy_version = str(trace.get("worker_numpy_version", "") or "")
    try:
        executable_ok = Path(executable).resolve() == DEFAULT_WORKER.resolve()
    except Exception:
        executable_ok = False
    return bool(executable_ok and numpy_version == REQUIRED_WORKER_NUMPY)


def _checked(response: dict[str, Any]) -> dict[str, Any]:
    if not response.get("ok", False):
        raise RuntimeError(f"worker returned error: {response}")
    return response


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    if not fieldnames:
        fieldnames = ["empty"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _write_report_md(path: Path, report: dict[str, Any]) -> None:
    verdict = report["verdict"]
    lines = [
        "# Pilot20 Learned-Destroy Phase A",
        "",
        f"Verdict: `{verdict['status']}`",
        "",
        f"Held-out avg vs operator-select: {verdict['heldout_avg_improvement_pct_vs_operator_select']:.3f}%",
        f"Min scale avg vs operator-select: {verdict['min_scale_improvement_pct_vs_operator_select']}",
        f"Held-out avg vs random: {verdict['heldout_avg_improvement_pct_vs_random']}",
        f"Zero violation learned: {verdict['zero_violation_learned']}",
        f"Worker integrity: {verdict['worker_integrity_ok']} ({verdict['required_worker_python']}, NumPy {verdict['required_worker_numpy']})",
        "",
        verdict["rule"],
        "",
        "Artifacts: `pilot20_phaseA_rows.csv`, `pilot20_update_log.csv`, `learned_destroy_phaseA_model.pt`.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _require_report_dir(path: Path) -> None:
    normalized = path.as_posix()
    if "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot" not in normalized:
        raise ValueError("Pilot20 outputs must stay under solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot20 learned-destroy Phase A probe")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--heldout-seeds", default="101,102")
    parser.add_argument("--train-episodes", type=int, default=8)
    parser.add_argument("--rollout-min-episodes", type=int, default=4)
    parser.add_argument("--eval-budget", type=int, default=80)
    parser.add_argument("--max-customers", type=int, default=64)
    parser.add_argument("--hidden-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--ppo-epochs", type=int, default=2)
    parser.add_argument("--minibatch-size", type=int, default=64)
    parser.add_argument("--gamma", type=float, default=0.99)
    parser.add_argument("--gae-lambda", type=float, default=0.95)
    parser.add_argument("--clip-range", type=float, default=0.2)
    parser.add_argument("--value-coef", type=float, default=0.5)
    parser.add_argument("--entropy-coef", type=float, default=0.01)
    parser.add_argument("--max-grad-norm", type=float, default=0.5)
    parser.add_argument("--skip-baselines", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run_phase_a(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
