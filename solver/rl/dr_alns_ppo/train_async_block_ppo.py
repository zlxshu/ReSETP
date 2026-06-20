from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import math
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from .async_block_policy import BlockActorCritic, make_block_actor_critic, save_async_block_policy
from .block_env import BlockAlnsEnv
from .bundle_manifest import load_manifest


SYSTEM_WORKER_PYTHON = os.environ.get("SETP_WORKER_PYTHON", "/opt/anaconda3/bin/python3.13")
SYSTEM_WORKER_NUMPY = "2.3.5"
REPORT_ROOT_FRAGMENT = "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot"


@dataclass(frozen=True)
class AsyncEpisodeTask:
    episode_index: int
    bundle: str
    seed: int
    eval_budget: int
    block_size: int
    policy_version: int
    deterministic: bool
    policy_payload: dict[str, Any]


def run_actor_episode(task: AsyncEpisodeTask) -> dict[str, Any]:
    start = time.monotonic()
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
    )
    observations: list[list[float]] = []
    actions: list[list[int]] = []
    rewards: list[float] = []
    values: list[float] = []
    log_probs: list[float] = []
    entropies: list[float] = []
    infos: list[dict[str, Any]] = []
    try:
        obs, _info = env.reset(seed=int(task.seed))
        terminated = False
        truncated = False
        while not (terminated or truncated):
            decision = model.act(obs, deterministic=bool(task.deterministic))
            action = np.asarray(decision["action"], dtype=np.int64)
            next_obs, reward, terminated, truncated, info = env.step(action)
            observations.append(np.asarray(obs, dtype=np.float32).tolist())
            actions.append(action.astype(int).tolist())
            rewards.append(float(reward))
            values.append(float(decision["value"]))
            log_probs.append(float(decision["log_prob"]))
            entropies.append(float(decision["entropy"]))
            infos.append(info)
            obs = next_obs
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
        "block_size": int(task.block_size),
        "eval_budget": int(task.eval_budget),
        "observations": observations,
        "actions": actions,
        "rewards": rewards,
        "values": values,
        "old_log_probs": log_probs,
        "entropies": entropies,
        "block_steps": len(rewards),
        "reward_sum": float(sum(rewards)),
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
) -> dict[str, torch.Tensor]:
    obs: list[list[float]] = []
    actions: list[list[int]] = []
    old_log_probs: list[float] = []
    advantages: list[float] = []
    returns: list[float] = []
    for episode in episodes:
        ep_adv, ep_returns = compute_episode_advantages(
            [float(v) for v in episode["rewards"]],
            [float(v) for v in episode["values"]],
            gamma=gamma,
            gae_lambda=gae_lambda,
        )
        obs.extend(episode["observations"])
        actions.extend(episode["actions"])
        old_log_probs.extend(float(v) for v in episode["old_log_probs"])
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
    return {
        "obs": torch.as_tensor(obs, dtype=torch.float32),
        "actions": torch.as_tensor(actions, dtype=torch.long),
        "old_log_probs": torch.as_tensor(old_log_probs, dtype=torch.float32),
        "advantages": adv_tensor,
        "returns": torch.as_tensor(returns, dtype=torch.float32),
    }


def ppo_update(
    model: BlockActorCritic,
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
    sample_count = int(batch["obs"].shape[0])
    losses: list[dict[str, float]] = []
    for _epoch in range(int(epochs)):
        permutation = torch.randperm(sample_count)
        for start in range(0, sample_count, int(minibatch_size)):
            indices = permutation[start : start + int(minibatch_size)]
            log_probs, entropies, values = model.evaluate_actions(batch["obs"][indices], batch["actions"][indices])
            old_log_probs = batch["old_log_probs"][indices]
            advantages = batch["advantages"][indices]
            returns = batch["returns"][indices]
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
            losses.append(
                {
                    "policy_loss": float(policy_loss.detach()),
                    "value_loss": float(value_loss.detach()),
                    "entropy": float(entropy.detach()),
                    "approx_kl": float(approx_kl.detach()),
                    "clip_fraction": float(clip_fraction.detach()),
                }
            )
    return _mean_metrics(losses)


def run_self_check(args: argparse.Namespace) -> int:
    output_dir = _checked_output_dir(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    _require_system_worker(args.required_worker_python)
    manifest = load_manifest(args.manifest)
    bundles = list(manifest["train"])
    model = make_block_actor_critic(seed=int(args.seed), hidden_size=int(args.hidden_size))
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
        output_dir=output_dir,
    )
    elapsed = time.monotonic() - start
    _write_episode_log(output_dir / "async_episode_log.csv", episodes)
    throughput = _throughput_rows(episodes, elapsed=elapsed, num_actors=int(args.num_actors))
    _write_csv(output_dir / "worker_throughput.csv", throughput)
    verdict = _self_check_verdict(episodes, throughput[-1] if throughput else {}, args=args)
    _write_json(output_dir / "async_self_check.json", verdict)
    _write_self_check_md(output_dir / "async_self_check.md", verdict)
    return 0 if verdict["status"] == "PASS_ASYNC_SELF_CHECK" else 2


def run_train(args: argparse.Namespace) -> int:
    output_dir = _checked_output_dir(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    _require_system_worker(args.required_worker_python)
    manifest = load_manifest(args.manifest)
    bundles = list(manifest["train"])
    model = make_block_actor_critic(seed=int(args.seed), hidden_size=int(args.hidden_size))
    optimizer = torch.optim.Adam(model.parameters(), lr=float(args.learning_rate))
    config = vars(args).copy()
    config["train_bundles"] = bundles
    config["model_format"] = "dr_alns_async_block_ppo.v1"
    _write_json(output_dir / "async_training_config.json", config)

    episode_log_path = output_dir / "async_episode_log.csv"
    update_log_path = output_dir / "async_update_log.csv"
    entropy_log_path = output_dir / "policy_entropy.csv"
    throughput_path = output_dir / "worker_throughput.csv"
    cpu_probe_path = output_dir / "cpu_probe.csv"
    _write_episode_log(episode_log_path, [], mode="w")
    _write_csv(update_log_path, [], fieldnames=_update_fieldnames())
    _write_csv(entropy_log_path, [], fieldnames=["update_index", "policy_version", "entropy"])
    _write_csv(throughput_path, [], fieldnames=_throughput_fieldnames())
    _write_csv(cpu_probe_path, [], fieldnames=["elapsed_seconds", "active_worker_count", "total_worker_pcpu"])

    policy_version = 0
    update_index = 0
    episode_index = 0
    completed_episodes = 0
    valid_steps_total = 0
    stale_episodes_total = 0
    all_episodes: list[dict[str, Any]] = []
    rollout_buffer: list[dict[str, Any]] = []
    start_time = time.monotonic()
    next_cpu_probe = start_time

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
                policy_payload=make_policy_payload(model),
            )
            futures[executor.submit(run_actor_episode, task)] = task
            episode_index += 1

        for _ in range(int(args.num_actors)):
            submit_one()

        while valid_steps_total < int(args.timesteps):
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
                _append_csv(episode_log_path, [_episode_csv_row(episode, accepted_for_update=bool(accepted))])
                _append_csv(
                    throughput_path,
                    _throughput_rows(all_episodes, elapsed=time.monotonic() - start_time, num_actors=int(args.num_actors))[-1:],
                )
                if valid_steps_total < int(args.timesteps):
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
                    batch = flatten_episodes(
                        accepted,
                        gamma=float(args.gamma),
                        gae_lambda=float(args.gae_lambda),
                    )
                    metrics = ppo_update(
                        model,
                        optimizer,
                        batch,
                        epochs=int(args.epochs),
                        minibatch_size=int(args.minibatch_size),
                        clip_range=float(args.clip_range),
                        value_coef=float(args.value_coef),
                        entropy_coef=float(args.entropy_coef),
                        max_grad_norm=float(args.max_grad_norm),
                    )
                    update_row = {
                        "update_index": update_index,
                        "policy_version_before": policy_version,
                        "policy_version_after": policy_version + 1,
                        "valid_steps": int(batch["obs"].shape[0]),
                        "valid_episodes": len(accepted),
                        "stale_episodes": len(stale),
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
        "train_wall_time_seconds": time.monotonic() - start_time,
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
                policy_payload=make_policy_payload(model),
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


def _episode_csv_row(episode: dict[str, Any], *, accepted_for_update: bool) -> dict[str, Any]:
    return {
        "episode_index": int(episode["episode_index"]),
        "bundle": episode["bundle"],
        "seed": int(episode["seed"]),
        "policy_version": int(episode["policy_version"]),
        "accepted_for_update": int(bool(accepted_for_update)),
        "block_steps": int(episode["block_steps"]),
        "reward_sum": float(episode["reward_sum"]),
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
        proc = subprocess.run(
            ["ps", "-axo", "pcpu,command"],
            check=False,
            text=True,
            capture_output=True,
        )
        active = 0
        pcpu = 0.0
        for line in proc.stdout.splitlines():
            if "dr_alns_ppo.worker" not in line:
                continue
            parts = line.strip().split(None, 1)
            if not parts:
                continue
            active += 1
            pcpu += float(parts[0])
    except Exception:
        active = 0
        pcpu = 0.0
    return {
        "elapsed_seconds": time.monotonic() - start_time,
        "active_worker_count": active,
        "total_worker_pcpu": pcpu,
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
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _episode_fieldnames() -> list[str]:
    return [
        "episode_index",
        "bundle",
        "seed",
        "policy_version",
        "accepted_for_update",
        "block_steps",
        "reward_sum",
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


def _update_fieldnames() -> list[str]:
    return [
        "update_index",
        "policy_version_before",
        "policy_version_after",
        "valid_steps",
        "valid_episodes",
        "stale_episodes",
        "policy_loss",
        "value_loss",
        "entropy",
        "approx_kl",
        "clip_fraction",
    ]


def _checked_output_dir(path: Path) -> Path:
    text = path.as_posix()
    if REPORT_ROOT_FRAGMENT not in text:
        raise ValueError(f"async PPO reports must stay under {REPORT_ROOT_FRAGMENT}: {path}")
    return path


def _require_system_worker(required: str) -> None:
    configured = os.environ.get("SETP_WORKER_PYTHON", "")
    if configured != required:
        raise RuntimeError(f"SETP_WORKER_PYTHON must be {required}, got {configured!r}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Asynchronous block-level PPO trainer for DR-ALNS.")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("self-check", "train"):
        p = sub.add_parser(command)
        p.add_argument("--manifest", default="solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json")
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
            p.add_argument("--gamma", type=float, default=0.99)
            p.add_argument("--gae-lambda", type=float, default=0.95)
            p.add_argument("--clip-range", type=float, default=0.2)
            p.add_argument("--value-coef", type=float, default=0.5)
            p.add_argument("--entropy-coef", type=float, default=0.01)
            p.add_argument("--learning-rate", type=float, default=3e-4)
            p.add_argument("--epochs", type=int, default=4)
            p.add_argument("--minibatch-size", type=int, default=256)
            p.add_argument("--max-grad-norm", type=float, default=0.5)
            p.add_argument("--poll-seconds", type=float, default=5.0)
            p.add_argument("--cpu-sample-interval-seconds", type=float, default=60.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "self-check":
        return run_self_check(args)
    if args.command == "train":
        return run_train(args)
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
