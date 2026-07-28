from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from .action_space import (
    BLOCK_ACTION_NVECS,
    BLOCK_CANDIDATE_ACTION_NVECS,
    BLOCK_DESTROY_IDS,
    BLOCK_EXPLORATION_RATIOS,
    BLOCK_Q_RATIOS,
    BLOCK_REPAIR_IDS,
    BLOCK_SEARCH_CONTROL_CHOICES,
    BLOCK_THRESHOLD_RATIOS,
    block_action_nvecs,
)
from .async_block_policy import BlockActorCritic, make_block_actor_critic, save_async_block_policy
from .block_env import BlockAlnsEnv
from .bundle_manifest import load_manifest, validate_curriculum_manifest


SYSTEM_WORKER_PYTHON = os.environ.get("SETP_WORKER_PYTHON", "/opt/anaconda3/bin/python3.13")
SYSTEM_WORKER_NUMPY = "2.3.5"
REPORT_ROOT_FRAGMENT = "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot"
TRACK23_STAGE_C_TRAIN_FRAGMENT = "solver/reports/dr_alns_ppo_v3/final_track23/stage_c_train24"
CURRICULUM_PHASES = ("route", "energy", "carbon", "dynamic")


@dataclass(frozen=True)
class AsyncEpisodeTask:
    episode_index: int
    bundle: str
    seed: int
    eval_budget: int
    block_size: int
    policy_version: int
    deterministic: bool
    curriculum_phase: str
    policy_payload: dict[str, Any]
    meta_mode: bool = False
    candidate_generator_mode: bool = False
    search_control_mode: bool = False


def run_actor_episode(task: AsyncEpisodeTask) -> dict[str, Any]:
    start = time.monotonic()
    torch.manual_seed(int(task.seed))
    np.random.seed(int(task.seed) % (2**32 - 1))
    model = BlockActorCritic(
        obs_dim=int(task.policy_payload["obs_dim"]),
        action_nvec=tuple(int(v) for v in task.policy_payload["action_nvec"]),
        hidden_size=int(task.policy_payload["hidden_size"]),
    )
    model.load_state_dict(task.policy_payload["state_dict"])
    model.eval()
    env = BlockAlnsEnv(
        task.bundle,
        seed=int(task.seed),
        eval_budget=int(task.eval_budget),
        block_size=int(task.block_size),
        curriculum_phase=str(task.curriculum_phase),
        meta_mode=bool(task.meta_mode),
        candidate_generator_mode=bool(task.candidate_generator_mode),
        search_control_mode=bool(task.search_control_mode),
    )
    observations: list[list[float]] = []
    actions: list[list[int]] = []
    rewards: list[float] = []
    values: list[float] = []
    log_probs: list[float] = []
    entropies: list[float] = []
    action_masks: list[list[list[bool]]] = []
    infos: list[dict[str, Any]] = []
    try:
        obs, reset_info = env.reset(seed=int(task.seed))
        current_mask = reset_info.get("action_mask")
        terminated = False
        truncated = False
        while not (terminated or truncated):
            decision = model.act(obs, deterministic=bool(task.deterministic), masks=current_mask)
            action = np.asarray(decision["action"], dtype=np.int64)
            next_obs, reward, terminated, truncated, info = env.step(action)
            observations.append(np.asarray(obs, dtype=np.float32).tolist())
            actions.append(action.astype(int).tolist())
            action_masks.append(_mask_to_lists(current_mask))
            rewards.append(float(reward))
            values.append(float(decision["value"]))
            log_probs.append(float(decision["log_prob"]))
            entropies.append(float(decision["entropy"]))
            infos.append(info)
            obs = next_obs
            current_mask = info.get("action_mask")
        final_info = infos[-1] if infos else dict(env.last_response or {})
    finally:
        env.close()
    trace = dict((final_info.get("trace", {}) if isinstance(final_info, dict) else {}) or {})
    wall_time = time.monotonic() - start
    return {
        "episode_index": int(task.episode_index),
        "bundle": task.bundle,
        "seed": int(task.seed),
        "policy_version": int(task.policy_version),
        "curriculum_phase": str(task.curriculum_phase),
        "meta_mode": bool(task.meta_mode),
        "candidate_generator_mode": bool(task.candidate_generator_mode),
        "search_control_mode": bool(task.search_control_mode),
        "block_size": int(task.block_size),
        "eval_budget": int(task.eval_budget),
        "observations": observations,
        "actions": actions,
        "action_masks": action_masks,
        "rewards": rewards,
        "values": values,
        "old_log_probs": log_probs,
        "entropies": entropies,
        "block_steps": len(rewards),
        "reward_sum": float(sum(rewards)),
        "reward_finite": bool(all(math.isfinite(float(value)) for value in rewards)),
        "best_obj": float(final_info.get("best_obj", 0.0)),
        "actual_evals": int(final_info.get("actual_evals", 0)),
        "candidate_scores": int(final_info.get("candidate_scores", 0)),
        "repair_delta_count": int(final_info.get("repair_delta_count", 0)),
        "violation_count": int(final_info.get("violation_count", 1)),
        "feasible": int(final_info.get("violation_count", 1)) == 0,
        "worker_python_executable": str(trace.get("worker_python_executable", "")),
        "worker_python_version": str(trace.get("worker_python_version", "")),
        "worker_numpy_version": str(trace.get("worker_numpy_version", "")),
        "wall_time_seconds": float(wall_time),
        "pid": int(os.getpid()),
    }


def make_policy_payload(model: BlockActorCritic) -> dict[str, Any]:
    return {
        "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
        "obs_dim": int(model.obs_dim),
        "action_nvec": tuple(int(v) for v in model.action_nvec),
        "hidden_size": int(model.hidden_size),
    }


def filter_on_policy_episodes(
    episodes: list[dict[str, Any]],
    *,
    current_policy_version: int,
    max_policy_lag: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    for episode in episodes:
        lag = int(current_policy_version) - int(episode["policy_version"])
        if lag <= int(max_policy_lag):
            accepted.append(episode)
        else:
            stale.append(episode)
    return accepted, stale


def _training_action_nvecs(candidate_generator_mode: bool, search_control_mode: bool = False) -> tuple[int, ...]:
    return block_action_nvecs(
        candidate_generator_mode=bool(candidate_generator_mode),
        search_control_mode=bool(search_control_mode),
    )


def _episode_action_nvecs(episodes: list[dict[str, Any]]) -> tuple[int, ...]:
    for episode in episodes:
        if bool(episode.get("candidate_generator_mode", False)) or bool(episode.get("search_control_mode", False)):
            return _training_action_nvecs(
                bool(episode.get("candidate_generator_mode", False)),
                bool(episode.get("search_control_mode", False)),
            )
        for action in episode.get("actions", []) or []:
            if len(action) == len(BLOCK_CANDIDATE_ACTION_NVECS):
                return tuple(BLOCK_CANDIDATE_ACTION_NVECS)
            if len(action) == len(BLOCK_ACTION_NVECS):
                return tuple(BLOCK_ACTION_NVECS)
    return tuple(BLOCK_ACTION_NVECS)


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


def flatten_episodes(
    episodes: list[dict[str, Any]],
    *,
    gamma: float,
    gae_lambda: float,
    shared_baseline_by_bundle: bool = False,
    advantage_clip_range: float | None = None,
) -> dict[str, Any]:
    action_nvecs = _episode_action_nvecs(episodes)
    obs: list[list[float]] = []
    actions: list[list[int]] = []
    action_masks: list[list[list[bool]]] = [[] for _ in action_nvecs]
    old_log_probs: list[float] = []
    old_values: list[float] = []
    advantages: list[float] = []
    returns: list[float] = []
    per_episode: list[tuple[dict[str, Any], list[float], list[float]]] = []
    for episode in episodes:
        ep_adv, ep_returns = compute_episode_advantages(
            [float(v) for v in episode["rewards"]],
            [float(v) for v in episode["values"]],
            gamma=gamma,
            gae_lambda=gae_lambda,
        )
        per_episode.append((episode, ep_adv, ep_returns))

    shared_group_count = 0
    shared_skipped_group_count = 0
    if shared_baseline_by_bundle:
        bundle_returns: dict[str, list[float]] = {}
        for episode, _ep_adv, ep_returns in per_episode:
            bundle = str(episode.get("bundle", ""))
            if ep_returns:
                bundle_returns.setdefault(bundle, []).append(float(sum(ep_returns)))
        bundle_means = {
            bundle: float(sum(values) / len(values))
            for bundle, values in bundle_returns.items()
            if len(values) >= 2
        }
        shared_group_count = len(bundle_means)
        shared_skipped_group_count = sum(1 for values in bundle_returns.values() if len(values) < 2)
        for idx, (episode, ep_adv, ep_returns) in enumerate(per_episode):
            baseline = bundle_means.get(str(episode.get("bundle", "")))
            if baseline is None:
                continue
            ep_returns = [float(value) - baseline for value in ep_returns]
            ep_adv = [float(ret) - float(value) for ret, value in zip(ep_returns, episode["values"])]
            per_episode[idx] = (episode, ep_adv, ep_returns)

    for episode, ep_adv, ep_returns in per_episode:
        obs.extend(episode["observations"])
        actions.extend(episode["actions"])
        episode_masks = episode.get("action_masks")
        if not episode_masks:
            episode_masks = [_all_true_mask(action_nvecs=action_nvecs) for _ in episode["actions"]]
        for mask in episode_masks:
            normalized = _mask_to_lists(mask, action_nvecs=action_nvecs)
            for head_idx, head_mask in enumerate(normalized):
                action_masks[head_idx].append([bool(value) for value in head_mask])
        old_log_probs.extend(float(v) for v in episode["old_log_probs"])
        old_values.extend(float(v) for v in episode["values"])
        advantages.extend(ep_adv)
        returns.extend(ep_returns)
    if not obs:
        raise ValueError("no valid rollout steps to flatten")
    adv_tensor = torch.as_tensor(advantages, dtype=torch.float32)
    adv_std = adv_tensor.std(unbiased=False)
    if float(adv_std) > 1e-8:
        adv_tensor = (adv_tensor - adv_tensor.mean()) / (adv_std + 1e-8)
    else:
        adv_tensor = adv_tensor - adv_tensor.mean()
    if advantage_clip_range is not None and float(advantage_clip_range) > 0.0:
        adv_tensor = torch.clamp(adv_tensor, -float(advantage_clip_range), float(advantage_clip_range))
    return {
        "obs": torch.as_tensor(obs, dtype=torch.float32),
        "actions": torch.as_tensor(actions, dtype=torch.long),
        "action_masks": [torch.as_tensor(mask, dtype=torch.bool) for mask in action_masks],
        "old_log_probs": torch.as_tensor(old_log_probs, dtype=torch.float32),
        "old_values": torch.as_tensor(old_values, dtype=torch.float32),
        "advantages": adv_tensor,
        "returns": torch.as_tensor(returns, dtype=torch.float32),
        "shared_baseline_group_count": torch.as_tensor(shared_group_count, dtype=torch.long),
        "shared_baseline_skipped_group_count": torch.as_tensor(shared_skipped_group_count, dtype=torch.long),
    }


def _resolve_device(device_name: str) -> torch.device:
    requested = str(device_name).strip().lower()
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("--device cuda requested, but torch.cuda.is_available() is False")
    if requested not in {"cpu", "cuda"}:
        raise ValueError(f"unsupported device: {device_name}")
    return torch.device(requested)


def _batch_to_device(batch: dict[str, Any], device: torch.device) -> dict[str, Any]:
    moved: dict[str, Any] = {}
    for key, value in batch.items():
        if isinstance(value, torch.Tensor):
            moved[key] = value.to(device)
        elif isinstance(value, list):
            moved[key] = [item.to(device) if isinstance(item, torch.Tensor) else item for item in value]
        else:
            moved[key] = value
    return moved


def ppo_update(
    model: BlockActorCritic,
    optimizer: torch.optim.Optimizer,
    batch: dict[str, Any],
    *,
    epochs: int,
    minibatch_size: int,
    clip_range: float,
    value_coef: float,
    entropy_coef: float,
    max_grad_norm: float,
    value_clip_range: float | None = None,
    target_kl: float = 0.0,
) -> dict[str, float]:
    sample_count = int(batch["obs"].shape[0])
    losses: list[dict[str, float]] = []
    target_kl_hit = False
    target_kl_value = float("nan")
    for _epoch in range(int(epochs)):
        permutation = torch.randperm(sample_count, device=batch["obs"].device)
        for start in range(0, sample_count, int(minibatch_size)):
            indices = permutation[start : start + int(minibatch_size)]
            masks = [mask[indices] for mask in batch.get("action_masks", [])]
            log_probs, entropies, values = model.evaluate_actions(
                batch["obs"][indices],
                batch["actions"][indices],
                masks=masks or None,
            )
            old_log_probs = batch["old_log_probs"][indices]
            old_values = batch.get("old_values")
            old_values_mb = old_values[indices] if old_values is not None else None
            advantages = batch["advantages"][indices]
            returns = batch["returns"][indices]
            ratio = torch.exp(log_probs - old_log_probs)
            unclipped = ratio * advantages
            clipped = torch.clamp(ratio, 1.0 - float(clip_range), 1.0 + float(clip_range)) * advantages
            policy_loss = -torch.minimum(unclipped, clipped).mean()
            value_loss_unclipped = nn.functional.mse_loss(values, returns)
            if value_clip_range is not None and old_values_mb is not None and float(value_clip_range) > 0.0:
                clipped_values = old_values_mb + torch.clamp(values - old_values_mb, -float(value_clip_range), float(value_clip_range))
                value_loss_clipped = nn.functional.mse_loss(clipped_values, returns)
                value_loss = torch.maximum(value_loss_unclipped, value_loss_clipped)
            else:
                value_loss = value_loss_unclipped
            entropy = entropies.mean()
            loss = policy_loss + float(value_coef) * value_loss - float(entropy_coef) * entropy
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), float(max_grad_norm))
            optimizer.step()
            with torch.no_grad():
                approx_kl = (old_log_probs - log_probs).mean().abs()
                clip_fraction = ((ratio - 1.0).abs() > float(clip_range)).float().mean()
            target_kl_value = float(approx_kl.detach())
            losses.append(
                {
                    "policy_loss": float(policy_loss.detach()),
                    "value_loss": float(value_loss.detach()),
                    "entropy": float(entropy.detach()),
                    "approx_kl": float(approx_kl.detach()),
                    "clip_fraction": float(clip_fraction.detach()),
                }
            )
            if float(target_kl) > 0.0 and target_kl_value > float(target_kl):
                target_kl_hit = True
                break
        if target_kl_hit:
            break
    metrics = _mean_metrics(losses)
    metrics["target_kl_hit"] = float(int(target_kl_hit))
    metrics["target_kl_value"] = target_kl_value
    return metrics


def run_self_check(args: argparse.Namespace) -> int:
    output_dir = _checked_output_dir(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    _require_system_worker(args.required_worker_python)
    manifest = _load_manifest_for_args(args)
    bundles = list(manifest["train"])
    action_nvecs = _training_action_nvecs(bool(args.candidate_generator_mode), bool(args.search_control_mode))
    model = make_block_actor_critic(seed=int(args.seed), hidden_size=int(args.hidden_size), action_nvec=action_nvecs)
    start = time.monotonic()
    episodes = collect_episodes(
        model,
        bundles,
        base_seed=int(args.seed),
        eval_budget=int(args.eval_budget),
        block_size=int(args.block_size),
        num_actors=int(args.num_actors),
        episode_count=int(args.self_check_episodes),
        deterministic=False,
        meta_mode=bool(args.meta_mode),
        candidate_generator_mode=bool(args.candidate_generator_mode),
        search_control_mode=bool(args.search_control_mode),
        output_dir=output_dir,
    )
    elapsed = time.monotonic() - start
    _write_episode_log(output_dir / "async_episode_log.csv", episodes)
    throughput = _throughput_rows(episodes, elapsed=elapsed, num_actors=int(args.num_actors))
    _write_csv(output_dir / "worker_throughput.csv", throughput)
    cpu_probe = [_cpu_probe_row(start)]
    _write_csv(output_dir / "cpu_probe.csv", cpu_probe, fieldnames=_cpu_probe_fieldnames())
    verdict = _self_check_verdict(episodes, throughput[-1] if throughput else {}, args=args)
    verdict["cpu_probe"] = cpu_probe[-1]
    _write_json(output_dir / "async_self_check.json", verdict)
    _write_self_check_md(output_dir / "async_self_check.md", verdict)
    return 0 if verdict["status"] == "PASS_ASYNC_SELF_CHECK" else 2


def run_audit(args: argparse.Namespace) -> int:
    output_dir = _checked_output_dir(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    _require_system_worker(args.required_worker_python)
    manifest = _load_manifest_for_args(args)
    bundle = str((manifest["train"] or [args.bundle])[0])
    if args.bundle:
        bundle = str(args.bundle)

    env = BlockAlnsEnv(
        bundle,
        seed=int(args.seed),
        eval_budget=int(args.eval_budget),
        block_size=int(args.block_size),
        meta_mode=bool(args.meta_mode),
        candidate_generator_mode=bool(args.candidate_generator_mode),
        search_control_mode=bool(args.search_control_mode),
    )
    try:
        _obs, reset_info = env.reset(seed=int(args.seed))
        reset_response = dict(env.last_response or {})
        action_nvecs = _training_action_nvecs(bool(args.candidate_generator_mode), bool(args.search_control_mode))
        action = np.zeros(len(action_nvecs), dtype=np.int64)
        _next_obs, reward, terminated, truncated, step_response = env.step(action)
    finally:
        env.close()

    trace = dict((step_response.get("trace", {}) if isinstance(step_response, dict) else {}) or {})
    metrics = dict((step_response.get("metrics", {}) if isinstance(step_response, dict) else {}) or {})
    try:
        import psutil  # type: ignore

        psutil_version = str(psutil.__version__)
    except Exception as exc:  # pragma: no cover - depends on external env
        psutil_version = f"unavailable: {exc}"

    payload = {
        "bundle": bundle,
        "seed": int(args.seed),
        "eval_budget": int(args.eval_budget),
        "block_size": int(args.block_size),
        "candidate_generator_mode": bool(args.candidate_generator_mode),
        "search_control_mode": bool(args.search_control_mode),
        "block_action_nvecs": list(_training_action_nvecs(bool(args.candidate_generator_mode), bool(args.search_control_mode))),
        "block_destroy_ids": list(BLOCK_DESTROY_IDS),
        "block_repair_ids": list(BLOCK_REPAIR_IDS),
        "block_q_ratios": list(BLOCK_Q_RATIOS),
        "block_threshold_ratios": list(BLOCK_THRESHOLD_RATIOS),
        "block_exploration_ratios": list(BLOCK_EXPLORATION_RATIOS),
        "block_search_control_choices": list(BLOCK_SEARCH_CONTROL_CHOICES),
        "reset_info_keys": sorted(str(key) for key in reset_info.keys()),
        "reset_response_keys": sorted(str(key) for key in reset_response.keys()),
        "step_response_keys": sorted(str(key) for key in step_response.keys()),
        "metrics_keys": sorted(str(key) for key in metrics.keys()),
        "trace_keys": sorted(str(key) for key in trace.keys()),
        "worker_python_executable": str(trace.get("worker_python_executable", "")),
        "worker_python_version": str(trace.get("worker_python_version", "")),
        "worker_numpy_version": str(trace.get("worker_numpy_version", "")),
        "torch_version": str(torch.__version__),
        "torch_cuda_available": bool(torch.cuda.is_available()),
        "torch_cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
        "psutil_version": psutil_version,
        "sample_reward": float(reward),
        "sample_terminated": bool(terminated),
        "sample_truncated": bool(truncated),
        "sample_cpu_probe": _cpu_probe_row(time.monotonic()),
    }
    _write_json(output_dir / "audit.json", payload)
    _write_audit_md(output_dir / "audit.md", payload)
    return 0


def _parse_curriculum_schedule(text: str) -> list[str]:
    phases = [part.strip() for part in str(text).split(",") if part.strip()]
    if not phases:
        raise ValueError("curriculum schedule cannot be empty")
    unknown = [phase for phase in phases if phase not in CURRICULUM_PHASES]
    if unknown:
        raise ValueError(f"unknown curriculum phase(s): {unknown}")
    return phases


def _phase_values(text: str | None, schedule: list[str], default: float | None) -> list[float | None]:
    raw = "" if text is None else str(text).strip()
    if not raw:
        return [default for _ in schedule]
    values = [part.strip() for part in raw.split(",")]
    if len(values) != len(schedule):
        raise ValueError(f"phase override length {len(values)} must match schedule length {len(schedule)}")
    parsed: list[float | None] = []
    for value in values:
        parsed.append(default if value == "" else float(value))
    return parsed


def _phase_can_advance(episodes: list[dict[str, Any]], phase: str, *, min_episodes: int) -> bool:
    phase_episodes = [ep for ep in episodes if str(ep.get("curriculum_phase", "")) == phase]
    if len(phase_episodes) < int(min_episodes):
        return False
    recent = phase_episodes[-int(min_episodes) :]
    if any(int(ep.get("violation_count", 1)) != 0 for ep in recent):
        return False
    if any(not math.isfinite(float(ep.get("best_obj", math.inf))) for ep in recent):
        return False
    by_bundle: dict[str, list[dict[str, Any]]] = {}
    for episode in phase_episodes:
        by_bundle.setdefault(str(episode.get("bundle", "")), []).append(episode)
    for bundle_eps in by_bundle.values():
        if len(bundle_eps) < int(min_episodes) * 2:
            continue
        prev = [float(ep["best_obj"]) for ep in bundle_eps[-2 * int(min_episodes) : -int(min_episodes)]]
        curr = [float(ep["best_obj"]) for ep in bundle_eps[-int(min_episodes) :]]
        if statistics_median(curr) > statistics_median(prev) + max(1e-9, abs(statistics_median(prev)) * 1e-9):
            return False
    return True


def statistics_median(values: list[float]) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return math.inf
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def _all_true_mask(action_nvecs: tuple[int, ...] = tuple(BLOCK_ACTION_NVECS)) -> list[list[bool]]:
    return [[True for _ in range(int(n))] for n in action_nvecs]


def _mask_to_lists(mask: Any, action_nvecs: tuple[int, ...] | None = None) -> list[list[bool]]:
    expected_nvecs = tuple(action_nvecs or _mask_action_nvecs(mask))
    if mask is None:
        return _all_true_mask(action_nvecs=expected_nvecs)
    if len(mask) != len(expected_nvecs):
        raise ValueError(f"expected {len(expected_nvecs)} mask heads, got {len(mask)}")
    normalized: list[list[bool]] = []
    for head_idx, head in enumerate(mask):
        values = [bool(value) for value in list(head)]
        expected = int(expected_nvecs[head_idx])
        if len(values) != expected:
            raise ValueError(f"mask head {head_idx} expected length {expected}, got {len(values)}")
        if not any(values):
            values[0] = True
        normalized.append(values)
    return normalized


def _mask_action_nvecs(mask: Any) -> tuple[int, ...]:
    if mask is not None:
        candidates = (
            block_action_nvecs(candidate_generator_mode=True, search_control_mode=True),
            block_action_nvecs(candidate_generator_mode=False, search_control_mode=True),
            block_action_nvecs(candidate_generator_mode=True, search_control_mode=False),
            block_action_nvecs(candidate_generator_mode=False, search_control_mode=False),
        )
        for nvecs in candidates:
            if len(mask) != len(nvecs):
                continue
            try:
                if all(len(list(head)) == int(nvecs[idx]) for idx, head in enumerate(mask)):
                    return tuple(nvecs)
            except TypeError:
                continue
    return tuple(BLOCK_ACTION_NVECS)


def _mask_invalid_rates(episode: dict[str, Any]) -> dict[str, float]:
    masks = episode.get("action_masks") or []
    max_nvecs = block_action_nvecs(candidate_generator_mode=True, search_control_mode=True)
    totals = [0 for _ in max_nvecs]
    invalid = [0 for _ in max_nvecs]
    for raw_mask in masks:
        normalized = _mask_to_lists(raw_mask)
        for idx, head in enumerate(normalized):
            totals[idx] += len(head)
            invalid[idx] += sum(1 for value in head if not value)
    return {
        f"mask_invalid_rate_head_{idx}": (float(invalid[idx]) / float(totals[idx]) if totals[idx] else 0.0)
        for idx in range(len(max_nvecs))
    }


def _aggregate_mask_invalid_rates(episodes: list[dict[str, Any]]) -> dict[str, float]:
    max_nvecs = block_action_nvecs(candidate_generator_mode=True, search_control_mode=True)
    totals = [0.0 for _ in max_nvecs]
    for episode in episodes:
        rates = _mask_invalid_rates(episode)
        for idx in range(len(max_nvecs)):
            totals[idx] += float(rates[f"mask_invalid_rate_head_{idx}"])
    count = max(float(len(episodes)), 1.0)
    return {f"mask_invalid_rate_head_{idx}": totals[idx] / count for idx in range(len(max_nvecs))}


def _save_periodic_checkpoint(
    output_dir: Path,
    model: BlockActorCritic,
    *,
    update_index: int,
    checkpoint_every_updates: int,
    metadata: dict[str, Any],
) -> str:
    every = int(checkpoint_every_updates)
    update_count = int(update_index) + 1
    if every <= 0 or update_count % every != 0:
        return ""
    checkpoint_path = output_dir / "checkpoints" / f"async_block_ppo_update_{update_count:04d}.pt"
    payload = dict(metadata)
    payload["checkpoint_update_index"] = int(update_index)
    payload["checkpoint_update_count"] = int(update_count)
    save_async_block_policy(checkpoint_path, model, metadata=payload)
    return checkpoint_path.as_posix()


def _expected_episode_steps(eval_budget: int, block_size: int) -> int:
    return max(1, int(math.ceil(float(eval_budget) / max(float(block_size), 1.0))))


def _load_manifest_for_args(args: argparse.Namespace) -> dict[str, Any]:
    curriculum = bool(getattr(args, "curriculum", False))
    manifest = load_manifest(args.manifest, validate=not curriculum)
    if curriculum:
        validate_curriculum_manifest(manifest, root=Path.cwd())
    return manifest


def run_train(args: argparse.Namespace) -> int:
    output_dir = _checked_output_dir(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    _require_system_worker(args.required_worker_python)
    manifest = _load_manifest_for_args(args)
    bundles = list(manifest["train"])
    schedule = _parse_curriculum_schedule(args.curriculum_schedule)
    phase_learning_rates = _phase_values(args.phase_learning_rates, schedule, float(args.learning_rate))
    phase_entropy_coefs = _phase_values(args.phase_entropy_coefs, schedule, float(args.entropy_coef))
    phase_clip_ranges = _phase_values(args.phase_clip_ranges, schedule, float(args.clip_range))
    phase_value_clip_ranges = _phase_values(args.phase_value_clip_ranges, schedule, None)
    phase_advantage_clip_ranges = _phase_values(args.phase_advantage_clip_ranges, schedule, None)
    device = _resolve_device(args.device)
    action_nvecs = _training_action_nvecs(bool(args.candidate_generator_mode), bool(args.search_control_mode))
    model = make_block_actor_critic(seed=int(args.seed), hidden_size=int(args.hidden_size), action_nvec=action_nvecs).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=float(args.learning_rate))
    config = vars(args).copy()
    config["train_bundles"] = bundles
    config["model_format"] = "dr_alns_async_block_ppo.v1"
    config["parsed_curriculum_schedule"] = schedule
    config["resolved_device"] = str(device)
    config["action_nvecs"] = list(action_nvecs)
    config["shared_baseline_by_bundle"] = not bool(args.disable_shared_baseline)
    _write_json(output_dir / "async_training_config.json", config)

    episode_log_path = output_dir / "async_episode_log.csv"
    update_log_path = output_dir / "async_update_log.csv"
    entropy_log_path = output_dir / "policy_entropy.csv"
    throughput_path = output_dir / "worker_throughput.csv"
    cpu_probe_path = output_dir / "cpu_probe.csv"
    phase_transition_path = output_dir / "phase_transitions.csv"
    _write_episode_log(episode_log_path, [], mode="w")
    _write_csv(update_log_path, [], fieldnames=_update_fieldnames())
    _write_csv(entropy_log_path, [], fieldnames=["update_index", "policy_version", "entropy"])
    _write_csv(throughput_path, [], fieldnames=_throughput_fieldnames())
    _write_csv(cpu_probe_path, [], fieldnames=_cpu_probe_fieldnames())
    _write_csv(phase_transition_path, [], fieldnames=_phase_transition_fieldnames())

    policy_version = 0
    phase_index = 0
    update_index = 0
    episode_index = 0
    completed_episodes = 0
    valid_steps_total = 0
    stale_episodes_total = 0
    all_episodes: list[dict[str, Any]] = []
    rollout_buffer: list[dict[str, Any]] = []
    start_time = time.monotonic()
    stopped_by_max_train_seconds = False
    next_cpu_probe = start_time
    expected_episode_steps = _expected_episode_steps(int(args.eval_budget), int(args.block_size))

    with concurrent.futures.ProcessPoolExecutor(max_workers=int(args.num_actors)) as executor:
        futures: dict[concurrent.futures.Future, AsyncEpisodeTask] = {}

        def submit_one() -> None:
            nonlocal episode_index
            task = AsyncEpisodeTask(
                episode_index=episode_index,
                bundle=bundles[episode_index % len(bundles)],
                seed=int(args.seed) + episode_index,
                eval_budget=int(args.eval_budget),
                block_size=int(args.block_size),
                policy_version=policy_version,
                deterministic=False,
                curriculum_phase=schedule[phase_index],
                policy_payload=make_policy_payload(model),
                meta_mode=bool(args.meta_mode),
                candidate_generator_mode=bool(args.candidate_generator_mode),
                search_control_mode=bool(args.search_control_mode),
            )
            futures[executor.submit(run_actor_episode, task)] = task
            episode_index += 1

        initial_tasks = min(int(args.num_actors), max(1, int(math.ceil(int(args.timesteps) / expected_episode_steps))))
        for _ in range(initial_tasks):
            submit_one()

        while valid_steps_total < int(args.timesteps):
            if float(getattr(args, "max_train_seconds", 0.0) or 0.0) > 0.0:
                if time.monotonic() - start_time >= float(args.max_train_seconds):
                    stopped_by_max_train_seconds = True
                    break
            done, _pending = concurrent.futures.wait(
                list(futures),
                timeout=float(args.poll_seconds),
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            now = time.monotonic()
            if now >= next_cpu_probe:
                _append_csv(cpu_probe_path, [_cpu_probe_row(start_time)])
                next_cpu_probe = now + float(args.cpu_sample_interval_seconds)
            if not done:
                continue
            for future in done:
                _task = futures.pop(future)
                episode = future.result()
                completed_episodes += 1
                all_episodes.append(episode)
                accepted, stale = filter_on_policy_episodes(
                    [episode],
                    current_policy_version=policy_version,
                    max_policy_lag=int(args.max_policy_lag),
                )
                stale_episodes_total += len(stale)
                if accepted:
                    rollout_buffer.extend(accepted)
                    valid_steps_total += int(episode["block_steps"])
                    if phase_index < len(schedule) - 1 and _phase_can_advance(
                        [ep for ep in all_episodes if int(ep.get("policy_version", -1)) <= policy_version],
                        schedule[phase_index],
                        min_episodes=int(args.phase_min_episodes),
                    ):
                        previous = schedule[phase_index]
                        phase_index += 1
                        _append_csv(
                            phase_transition_path,
                            [
                                {
                                    "completed_episodes": completed_episodes,
                                    "valid_steps_total": valid_steps_total,
                                    "from_phase": previous,
                                    "to_phase": schedule[phase_index],
                                }
                            ],
                            fieldnames=_phase_transition_fieldnames(),
                        )
                _append_csv(episode_log_path, [_episode_csv_row(episode, accepted_for_update=bool(accepted))])
                _append_csv(
                    throughput_path,
                    _throughput_rows(all_episodes, elapsed=time.monotonic() - start_time, num_actors=int(args.num_actors))[-1:],
                )
                projected_steps = valid_steps_total + len(futures) * expected_episode_steps
                if valid_steps_total < int(args.timesteps) and projected_steps < int(args.timesteps):
                    submit_one()
            buffer_steps = sum(int(ep["block_steps"]) for ep in rollout_buffer)
            if buffer_steps >= int(args.rollout_min_steps) or len(rollout_buffer) >= int(args.rollout_min_episodes):
                accepted, stale = filter_on_policy_episodes(
                    rollout_buffer,
                    current_policy_version=policy_version,
                    max_policy_lag=int(args.max_policy_lag),
                )
                stale_episodes_total += len(stale)
                if accepted:
                    update_phase = str(accepted[-1].get("curriculum_phase", schedule[phase_index]))
                    update_phase_index = schedule.index(update_phase) if update_phase in schedule else phase_index
                    phase_lr = phase_learning_rates[update_phase_index]
                    phase_entropy = phase_entropy_coefs[update_phase_index]
                    phase_clip = phase_clip_ranges[update_phase_index]
                    for group in optimizer.param_groups:
                        group["lr"] = float(phase_lr if phase_lr is not None else args.learning_rate)
                    batch = flatten_episodes(
                        accepted,
                        gamma=float(args.gamma),
                        gae_lambda=float(args.gae_lambda),
                        shared_baseline_by_bundle=not bool(args.disable_shared_baseline),
                        advantage_clip_range=phase_advantage_clip_ranges[update_phase_index],
                    )
                    batch = _batch_to_device(batch, device)
                    metrics = ppo_update(
                        model,
                        optimizer,
                        batch,
                        epochs=int(args.epochs),
                        minibatch_size=int(args.minibatch_size),
                        clip_range=float(phase_clip if phase_clip is not None else args.clip_range),
                        value_coef=float(args.value_coef),
                        entropy_coef=float(phase_entropy if phase_entropy is not None else args.entropy_coef),
                        max_grad_norm=float(args.max_grad_norm),
                        value_clip_range=phase_value_clip_ranges[update_phase_index],
                        target_kl=float(args.target_kl),
                    )
                    checkpoint_path = _save_periodic_checkpoint(
                        output_dir,
                        model,
                        update_index=update_index,
                        checkpoint_every_updates=int(args.checkpoint_every_updates),
                        metadata={
                            "policy_version": policy_version + 1,
                            "update_index": update_index,
                            "completed_episodes": completed_episodes,
                            "valid_steps_total": valid_steps_total,
                            "curriculum_phase": update_phase,
                            "curriculum_schedule": schedule,
                            "device": str(device),
                            "shared_baseline_by_bundle": not bool(args.disable_shared_baseline),
                        },
                    )
                    update_row = {
                        "update_index": update_index,
                        "policy_version_before": policy_version,
                        "policy_version_after": policy_version + 1,
                        "curriculum_phase": update_phase,
                        "learning_rate": float(phase_lr if phase_lr is not None else args.learning_rate),
                        "entropy_coef": float(phase_entropy if phase_entropy is not None else args.entropy_coef),
                        "clip_range": float(phase_clip if phase_clip is not None else args.clip_range),
                        "device": str(device),
                        "valid_steps": int(batch["obs"].shape[0]),
                        "valid_episodes": len(accepted),
                        "stale_episodes": len(stale),
                        "shared_baseline_group_count": int(batch["shared_baseline_group_count"].detach().cpu().item()),
                        "shared_baseline_skipped_group_count": int(
                            batch["shared_baseline_skipped_group_count"].detach().cpu().item()
                        ),
                        "checkpoint_path": checkpoint_path,
                        **_aggregate_mask_invalid_rates(accepted),
                        **metrics,
                    }
                    _append_csv(update_log_path, [update_row], fieldnames=_update_fieldnames())
                    _append_csv(
                        entropy_log_path,
                        [
                            {
                                "update_index": update_index,
                                "policy_version": policy_version + 1,
                                "entropy": metrics.get("entropy", 0.0),
                            }
                        ],
                    )
                    policy_version += 1
                    update_index += 1
                rollout_buffer = []
        # Do not wait for extra episodes after the target; cancel not-yet-started futures.
        for future in futures:
            future.cancel()

    metadata = {
        "policy_version": policy_version,
        "completed_episodes": completed_episodes,
        "valid_steps_total": valid_steps_total,
        "stale_episodes_total": stale_episodes_total,
        "final_curriculum_phase": schedule[phase_index],
        "curriculum_schedule": schedule,
        "device": str(device),
        "shared_baseline_by_bundle": not bool(args.disable_shared_baseline),
        "checkpoint_every_updates": int(args.checkpoint_every_updates),
        "train_wall_time_seconds": time.monotonic() - start_time,
        "stopped_by_max_train_seconds": bool(stopped_by_max_train_seconds),
        "max_train_seconds": float(getattr(args, "max_train_seconds", 0.0) or 0.0),
    }
    save_async_block_policy(output_dir / "async_block_ppo_model.pt", model, metadata=metadata)
    _write_json(output_dir / "async_train_summary.json", metadata)
    _write_train_md(output_dir / "async_pilot_report.md", metadata)
    return 0


def collect_episodes(
    model: BlockActorCritic,
    bundles: list[str],
    *,
    base_seed: int,
    eval_budget: int,
    block_size: int,
    num_actors: int,
    episode_count: int,
    deterministic: bool,
    meta_mode: bool = False,
    candidate_generator_mode: bool = False,
    search_control_mode: bool = False,
    output_dir: Path | None = None,
) -> list[dict[str, Any]]:
    _ = output_dir
    episodes: list[dict[str, Any]] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=int(num_actors)) as executor:
        futures = []
        for episode_index in range(int(episode_count)):
            task = AsyncEpisodeTask(
                episode_index=episode_index,
                bundle=bundles[episode_index % len(bundles)],
                seed=int(base_seed) + episode_index,
                eval_budget=int(eval_budget),
                block_size=int(block_size),
                policy_version=0,
                deterministic=bool(deterministic),
                curriculum_phase="route",
                policy_payload=make_policy_payload(model),
                meta_mode=bool(meta_mode),
                candidate_generator_mode=bool(candidate_generator_mode),
                search_control_mode=bool(search_control_mode),
            )
            futures.append(executor.submit(run_actor_episode, task))
        for future in concurrent.futures.as_completed(futures):
            episodes.append(future.result())
    episodes.sort(key=lambda item: int(item["episode_index"]))
    return episodes


def _self_check_verdict(episodes: list[dict[str, Any]], throughput: dict[str, Any], *, args: argparse.Namespace) -> dict[str, Any]:
    completed = len(episodes)
    all_budget = all(int(ep["actual_evals"]) == int(args.eval_budget) for ep in episodes)
    zero_violations = all(int(ep["violation_count"]) == 0 for ep in episodes)
    system_worker = all(ep["worker_python_executable"] == args.required_worker_python for ep in episodes)
    numpy_ok = all(ep["worker_numpy_version"] == SYSTEM_WORKER_NUMPY for ep in episodes)
    busy_ratio = float(throughput.get("busy_ratio", 0.0) or 0.0)
    pass_gate = (
        completed >= int(args.self_check_episodes)
        and completed >= min(6, int(args.self_check_episodes))
        and all_budget
        and zero_violations
        and system_worker
        and numpy_ok
        and busy_ratio >= float(args.min_busy_ratio)
    )
    return {
        "status": "PASS_ASYNC_SELF_CHECK" if pass_gate else "HALT_ASYNC_SELF_CHECK",
        "completed_episodes": completed,
        "all_actual_evals_match_budget": all_budget,
        "zero_violations": zero_violations,
        "system_worker": system_worker,
        "numpy_ok": numpy_ok,
        "busy_ratio": busy_ratio,
        "min_busy_ratio": float(args.min_busy_ratio),
        "throughput": throughput,
    }


def _candidate_generator_indices(episode: dict[str, Any]) -> list[int]:
    indices: list[int] = []
    if not bool(episode.get("candidate_generator_mode", False)):
        return indices
    for action in episode.get("actions", []) or []:
        if len(action) > len(BLOCK_ACTION_NVECS):
            indices.append(int(action[len(BLOCK_ACTION_NVECS)]))
    return indices


def _candidate_generator_unique_count(episode: dict[str, Any]) -> int:
    return len(set(_candidate_generator_indices(episode)))


def _candidate_generator_nondefault_count(episode: dict[str, Any]) -> int:
    return sum(1 for idx in _candidate_generator_indices(episode) if idx != 0)


def _search_control_indices(episode: dict[str, Any]) -> list[int]:
    indices: list[int] = []
    if not bool(episode.get("search_control_mode", False)):
        return indices
    control_idx = len(BLOCK_ACTION_NVECS) + int(bool(episode.get("candidate_generator_mode", False)))
    for action in episode.get("actions", []) or []:
        if len(action) > control_idx:
            indices.append(int(action[control_idx]))
    return indices


def _search_control_unique_count(episode: dict[str, Any]) -> int:
    return len(set(_search_control_indices(episode)))


def _search_control_noncontinue_count(episode: dict[str, Any]) -> int:
    return sum(1 for idx in _search_control_indices(episode) if idx != 0)


def _episode_csv_row(episode: dict[str, Any], *, accepted_for_update: bool) -> dict[str, Any]:
    row = {
        "episode_index": int(episode["episode_index"]),
        "bundle": episode["bundle"],
        "seed": int(episode["seed"]),
        "policy_version": int(episode["policy_version"]),
        "curriculum_phase": str(episode.get("curriculum_phase", "route")),
        "meta_mode": int(bool(episode.get("meta_mode", False))),
        "candidate_generator_mode": int(bool(episode.get("candidate_generator_mode", False))),
        "search_control_mode": int(bool(episode.get("search_control_mode", False))),
        "accepted_for_update": int(bool(accepted_for_update)),
        "candidate_generator_unique_count": _candidate_generator_unique_count(episode),
        "candidate_generator_nondefault_count": _candidate_generator_nondefault_count(episode),
        "search_control_unique_count": _search_control_unique_count(episode),
        "search_control_noncontinue_count": _search_control_noncontinue_count(episode),
        "block_steps": int(episode["block_steps"]),
        "reward_sum": float(episode["reward_sum"]),
        "reward_finite": int(bool(episode.get("reward_finite", True))),
        "best_obj": float(episode["best_obj"]),
        "actual_evals": int(episode["actual_evals"]),
        "candidate_scores": int(episode["candidate_scores"]),
        "repair_delta_count": int(episode["repair_delta_count"]),
        "violation_count": int(episode["violation_count"]),
        "feasible": int(bool(episode["feasible"])),
        "wall_time_seconds": float(episode["wall_time_seconds"]),
        "worker_python_executable": episode["worker_python_executable"],
        "worker_python_version": episode["worker_python_version"],
        "worker_numpy_version": episode["worker_numpy_version"],
        "pid": int(episode["pid"]),
    }
    row.update(_mask_invalid_rates(episode))
    return row


def _write_episode_log(path: Path, episodes: list[dict[str, Any]], *, mode: str = "w") -> None:
    rows = [_episode_csv_row(ep, accepted_for_update=True) for ep in episodes]
    _write_csv(path, rows, fieldnames=_episode_fieldnames(), mode=mode)


def _throughput_rows(episodes: list[dict[str, Any]], *, elapsed: float, num_actors: int) -> list[dict[str, Any]]:
    if not episodes:
        return []
    busy = sum(float(ep["wall_time_seconds"]) for ep in episodes)
    block_steps = sum(int(ep["block_steps"]) for ep in episodes)
    elapsed = max(float(elapsed), 1e-9)
    capacity = max(float(num_actors) * elapsed, 1e-9)
    busy_ratio = min(1.0, busy / capacity)
    return [
        {
            "completed_episodes": len(episodes),
            "elapsed_seconds": elapsed,
            "num_actors": int(num_actors),
            "busy_time_seconds_sum": busy,
            "busy_ratio": busy_ratio,
            "idle_ratio": max(0.0, 1.0 - busy_ratio),
            "episodes_per_hour": 3600.0 * len(episodes) / elapsed,
            "block_steps_per_hour": 3600.0 * block_steps / elapsed,
            "worker_failure_count": 0,
        }
    ]


def _cpu_probe_row(start_time: float) -> dict[str, Any]:
    try:
        import psutil  # type: ignore

        active = 0
        pcpu = 0.0
        rss_bytes = 0
        for proc in psutil.process_iter(["cmdline", "cpu_percent", "memory_info"]):
            try:
                cmdline = " ".join(str(part) for part in (proc.info.get("cmdline") or []))
                if "dr_alns_ppo.worker" not in cmdline:
                    continue
                active += 1
                pcpu += float(proc.info.get("cpu_percent") or 0.0)
                memory_info = proc.info.get("memory_info")
                rss_bytes += int(getattr(memory_info, "rss", 0) or 0)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        vm = psutil.virtual_memory()
        system_total_bytes = int(getattr(vm, "total", 0) or 0)
        system_available_bytes = int(getattr(vm, "available", 0) or 0)
        system_used_bytes = int(getattr(vm, "used", 0) or 0)
        system_memory_percent = float(getattr(vm, "percent", 0.0) or 0.0)
        error = ""
    except Exception as exc:
        active = 0
        pcpu = 0.0
        rss_bytes = 0
        system_total_bytes = 0
        system_available_bytes = 0
        system_used_bytes = 0
        system_memory_percent = 0.0
        error = str(exc)
    return {
        "elapsed_seconds": time.monotonic() - start_time,
        "active_worker_count": active,
        "total_worker_pcpu": pcpu,
        "total_worker_rss_bytes": rss_bytes,
        "total_worker_rss_mb": float(rss_bytes) / (1024.0 * 1024.0),
        "system_memory_total_bytes": system_total_bytes,
        "system_memory_available_bytes": system_available_bytes,
        "system_memory_used_bytes": system_used_bytes,
        "system_memory_total_mb": float(system_total_bytes) / (1024.0 * 1024.0),
        "system_memory_available_mb": float(system_available_bytes) / (1024.0 * 1024.0),
        "system_memory_used_mb": float(system_used_bytes) / (1024.0 * 1024.0),
        "system_memory_percent": system_memory_percent,
        "probe_error": error,
    }


def _mean_metrics(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {key: 0.0 for key in ("policy_loss", "value_loss", "entropy", "approx_kl", "clip_fraction")}
    keys = rows[0].keys()
    return {key: float(sum(row[key] for row in rows) / len(rows)) for key in keys}


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    fieldnames: list[str] | None = None,
    mode: str = "w",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fieldnames or (list(rows[0].keys()) if rows else [])
    write_header = mode == "w" or not path.exists() or path.stat().st_size == 0
    with path.open(mode, newline="", encoding="utf-8") as handle:
        if not fields:
            return
        writer = csv.DictWriter(handle, fieldnames=fields)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def _append_csv(path: Path, rows: list[dict[str, Any]], *, fieldnames: list[str] | None = None) -> None:
    if not rows:
        return
    _write_csv(path, rows, fieldnames=fieldnames or list(rows[0].keys()), mode="a")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_self_check_md(path: Path, verdict: dict[str, Any]) -> None:
    lines = [
        "# Async Block PPO Self-Check",
        "",
        f"Status: `{verdict['status']}`.",
        "",
        f"Completed episodes: {verdict['completed_episodes']}.",
        f"All actual evals match budget: {verdict['all_actual_evals_match_budget']}.",
        f"Zero violations: {verdict['zero_violations']}.",
        f"System worker: {verdict['system_worker']}.",
        f"NumPy anchor: {verdict['numpy_ok']}.",
        f"Busy ratio: {verdict['busy_ratio']:.3f}.",
        f"Worker RSS MB: {float((verdict.get('cpu_probe') or {}).get('total_worker_rss_mb', 0.0)):.1f}.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_audit_md(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Async Block PPO Audit",
        "",
        f"Bundle: `{payload['bundle']}`.",
        f"Worker: `{payload['worker_python_executable']}`.",
        f"Worker NumPy: `{payload['worker_numpy_version']}`.",
        f"Torch: `{payload['torch_version']}`; CUDA available: `{payload['torch_cuda_available']}`; device: `{payload['torch_cuda_device']}`.",
        f"psutil: `{payload['psutil_version']}`.",
        "",
        "## Block Action Space",
        "",
        f"nvecs: `{payload['block_action_nvecs']}`",
        f"destroy: `{payload['block_destroy_ids']}`",
        f"repair: `{payload['block_repair_ids']}`",
        f"q ratios: `{payload['block_q_ratios']}`",
        f"threshold ratios: `{payload['block_threshold_ratios']}`",
        f"exploration ratios: `{payload['block_exploration_ratios']}`",
        "",
        "## Response Fields",
        "",
        f"top-level: `{payload['step_response_keys']}`",
        f"metrics: `{payload['metrics_keys']}`",
        f"trace: `{payload['trace_keys']}`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_train_md(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Async Block PPO Pilot",
        "",
        "Training completed. This is not a performance verdict until `evaluate_policy` writes the 100-01 comparison table.",
        "",
        f"Completed episodes: {summary['completed_episodes']}.",
        f"Valid block steps: {summary['valid_steps_total']}.",
        f"Stale episodes discarded: {summary['stale_episodes_total']}.",
        f"Final policy version: {summary['policy_version']}.",
        f"Device: `{summary.get('device', 'cpu')}`.",
        f"Shared baseline by bundle: `{summary.get('shared_baseline_by_bundle', False)}`.",
        "",
        "GPU use is limited to the main-process PPO model, batch tensors, and gradient updates; solver rollout remains CPU-bound.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _episode_fieldnames() -> list[str]:
    return [
        "episode_index",
        "bundle",
        "seed",
        "policy_version",
        "curriculum_phase",
        "meta_mode",
        "candidate_generator_mode",
        "search_control_mode",
        "accepted_for_update",
        "candidate_generator_unique_count",
        "candidate_generator_nondefault_count",
        "search_control_unique_count",
        "search_control_noncontinue_count",
        "block_steps",
        "reward_sum",
        "reward_finite",
        "best_obj",
        "actual_evals",
        "candidate_scores",
        "repair_delta_count",
        "violation_count",
        "feasible",
        "wall_time_seconds",
        "worker_python_executable",
        "worker_python_version",
        "worker_numpy_version",
        "pid",
        "mask_invalid_rate_head_0",
        "mask_invalid_rate_head_1",
        "mask_invalid_rate_head_2",
        "mask_invalid_rate_head_3",
        "mask_invalid_rate_head_4",
        "mask_invalid_rate_head_5",
        "mask_invalid_rate_head_6",
    ]


def _throughput_fieldnames() -> list[str]:
    return [
        "completed_episodes",
        "elapsed_seconds",
        "num_actors",
        "busy_time_seconds_sum",
        "busy_ratio",
        "idle_ratio",
        "episodes_per_hour",
        "block_steps_per_hour",
        "worker_failure_count",
    ]


def _cpu_probe_fieldnames() -> list[str]:
    return [
        "elapsed_seconds",
        "active_worker_count",
        "total_worker_pcpu",
        "total_worker_rss_bytes",
        "total_worker_rss_mb",
        "system_memory_total_bytes",
        "system_memory_available_bytes",
        "system_memory_used_bytes",
        "system_memory_total_mb",
        "system_memory_available_mb",
        "system_memory_used_mb",
        "system_memory_percent",
        "probe_error",
    ]


def _update_fieldnames() -> list[str]:
    return [
        "update_index",
        "policy_version_before",
        "policy_version_after",
        "curriculum_phase",
        "learning_rate",
        "entropy_coef",
        "clip_range",
        "device",
        "valid_steps",
        "valid_episodes",
        "stale_episodes",
        "shared_baseline_group_count",
        "shared_baseline_skipped_group_count",
        "checkpoint_path",
        "mask_invalid_rate_head_0",
        "mask_invalid_rate_head_1",
        "mask_invalid_rate_head_2",
        "mask_invalid_rate_head_3",
        "mask_invalid_rate_head_4",
        "mask_invalid_rate_head_5",
        "mask_invalid_rate_head_6",
        "policy_loss",
        "value_loss",
        "entropy",
        "approx_kl",
        "clip_fraction",
        "target_kl_hit",
        "target_kl_value",
    ]


def _phase_transition_fieldnames() -> list[str]:
    return [
        "completed_episodes",
        "valid_steps_total",
        "from_phase",
        "to_phase",
    ]


def _checked_output_dir(path: Path) -> Path:
    text = path.as_posix()
    allowed = (REPORT_ROOT_FRAGMENT, TRACK23_STAGE_C_TRAIN_FRAGMENT)
    if not any(fragment in text for fragment in allowed):
        raise ValueError(f"async PPO reports must stay under an allowed report dir {allowed}: {path}")
    return path


def _require_system_worker(required: str) -> None:
    configured = os.environ.get("SETP_WORKER_PYTHON", "")
    if configured != required:
        raise RuntimeError(f"SETP_WORKER_PYTHON must be {required}, got {configured!r}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Asynchronous block-level PPO trainer for DR-ALNS.")
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--manifest", default="solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json")
    audit.add_argument("--curriculum", action="store_true")
    audit.add_argument("--meta-mode", action="store_true")
    audit.add_argument("--candidate-generator-mode", action="store_true")
    audit.add_argument("--search-control-mode", action="store_true")
    audit.add_argument("--output-dir", default=f"{REPORT_ROOT_FRAGMENT}/audit")
    audit.add_argument("--bundle", default="")
    audit.add_argument("--seed", type=int, default=1)
    audit.add_argument("--eval-budget", type=int, default=16)
    audit.add_argument("--block-size", type=int, default=4)
    audit.add_argument("--required-worker-python", default=SYSTEM_WORKER_PYTHON)
    for command in ("self-check", "train"):
        p = sub.add_parser(command)
        p.add_argument("--manifest", default="solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json")
        p.add_argument("--curriculum", action="store_true")
        p.add_argument("--meta-mode", action="store_true")
        p.add_argument("--candidate-generator-mode", action="store_true")
        p.add_argument("--search-control-mode", action="store_true")
        p.add_argument("--output-dir", required=True)
        p.add_argument("--seed", type=int, default=1)
        p.add_argument("--eval-budget", type=int, default=16000)
        p.add_argument("--block-size", type=int, default=128)
        p.add_argument("--num-actors", type=int, default=6)
        p.add_argument("--hidden-size", type=int, default=128)
        p.add_argument("--required-worker-python", default=SYSTEM_WORKER_PYTHON)
        if command == "self-check":
            p.add_argument("--self-check-episodes", type=int, default=6)
            p.add_argument("--min-busy-ratio", type=float, default=0.60)
        else:
            p.add_argument("--timesteps", type=int, default=72000)
            p.add_argument("--rollout-min-steps", type=int, default=2048)
            p.add_argument("--rollout-min-episodes", type=int, default=12)
            p.add_argument("--max-policy-lag", type=int, default=1)
            p.add_argument("--curriculum-schedule", default="route,energy,carbon,dynamic")
            p.add_argument("--phase-min-episodes", type=int, default=4)
            p.add_argument("--phase-learning-rates", default="")
            p.add_argument("--phase-entropy-coefs", default="")
            p.add_argument("--phase-clip-ranges", default="")
            p.add_argument("--phase-value-clip-ranges", default="")
            p.add_argument("--phase-advantage-clip-ranges", default="")
            p.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
            p.add_argument("--disable-shared-baseline", action="store_true")
            p.add_argument("--gamma", type=float, default=0.99)
            p.add_argument("--gae-lambda", type=float, default=0.95)
            p.add_argument("--clip-range", type=float, default=0.2)
            p.add_argument("--value-coef", type=float, default=0.5)
            p.add_argument("--entropy-coef", type=float, default=0.01)
            p.add_argument("--learning-rate", type=float, default=3e-4)
            p.add_argument("--epochs", type=int, default=4)
            p.add_argument("--minibatch-size", type=int, default=256)
            p.add_argument("--max-grad-norm", type=float, default=0.5)
            p.add_argument("--target-kl", type=float, default=0.0)
            p.add_argument("--max-train-seconds", type=float, default=0.0)
            p.add_argument("--checkpoint-every-updates", type=int, default=10)
            p.add_argument("--poll-seconds", type=float, default=5.0)
            p.add_argument("--cpu-sample-interval-seconds", type=float, default=60.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "audit":
        return run_audit(args)
    if args.command == "self-check":
        return run_self_check(args)
    if args.command == "train":
        return run_train(args)
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
