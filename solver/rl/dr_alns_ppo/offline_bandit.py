from __future__ import annotations

import argparse
import concurrent.futures
import csv
import itertools
import json
import math
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from .action_space import (
    BLOCK_ACTION_NVECS,
    BLOCK_DESTROY_IDS,
    BLOCK_EXPLORATION_RATIOS,
    BLOCK_Q_RATIOS,
    BLOCK_REPAIR_IDS,
    BLOCK_THRESHOLD_RATIOS,
)
from .async_block_policy import BlockActorCritic, make_block_actor_critic, save_async_block_policy
from .block_env import BLOCK_OBSERVATION_SIZE, BlockAlnsEnv
from .bundle_manifest import load_manifest
from .evaluate_policy import evaluate as evaluate_policy
from .train_async_block_ppo import SYSTEM_WORKER_NUMPY, SYSTEM_WORKER_PYTHON


REPORT_ROOT_FRAGMENT = "solver/reports/dr_alns_ppo_v3_block_dr_alns/offline_bandit"
DEFAULT_SYSTEM_WORKER = SYSTEM_WORKER_PYTHON
MIN_UNIQUE_FULL_ACTIONS = 150
MIN_BLOCK_ROWS = 4000


@dataclass(frozen=True)
class TraceEpisodeTask:
    episode_index: int
    bundle: str
    seed: int
    policy: str
    eval_budget: int
    block_size: int


def run_trace_episode(task: TraceEpisodeTask) -> dict[str, Any]:
    start = time.monotonic()
    env = BlockAlnsEnv(
        task.bundle,
        seed=int(task.seed),
        eval_budget=int(task.eval_budget),
        block_size=int(task.block_size),
    )
    rows: list[dict[str, Any]] = []
    try:
        obs, info = env.reset(seed=int(task.seed))
        rng = np.random.default_rng(int(task.seed) + 1009 * int(task.episode_index))
        terminated = False
        truncated = False
        step_index = 0
        while not (terminated or truncated):
            action = _sample_collection_action(
                task.policy,
                rng=rng,
                episode_index=int(task.episode_index),
                step_index=step_index,
            )
            actual_before = int(info.get("actual_evals", 0))
            next_obs, reward, terminated, truncated, info = env.step(action)
            rows.append(
                _block_row(
                    task,
                    step_index=step_index,
                    observation=np.asarray(obs, dtype=np.float32),
                    action=np.asarray(action, dtype=np.int64),
                    reward=float(reward),
                    info=info,
                    actual_evals_before=actual_before,
                )
            )
            obs = next_obs
            step_index += 1
        final_info = dict(env.last_response or info)
    finally:
        env.close()
    return {
        "episode_index": int(task.episode_index),
        "bundle": task.bundle,
        "seed": int(task.seed),
        "policy": task.policy,
        "eval_budget": int(task.eval_budget),
        "block_size": int(task.block_size),
        "block_rows": rows,
        "block_steps": len(rows),
        "best_obj": float(final_info.get("best_obj", 0.0)),
        "actual_evals": int(final_info.get("actual_evals", 0)),
        "violation_count": int(final_info.get("violation_count", 1)),
        "wall_time_seconds": float(time.monotonic() - start),
        "worker_python_executable": str(((final_info.get("trace", {}) or {}).get("worker_python_executable", ""))),
        "worker_python_version": str(((final_info.get("trace", {}) or {}).get("worker_python_version", ""))),
        "worker_numpy_version": str(((final_info.get("trace", {}) or {}).get("worker_numpy_version", ""))),
        "pid": int(os.getpid()),
    }


def run_audit_existing(args: argparse.Namespace) -> int:
    output_dir = _checked_output_dir(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = {
        "async_self_check_episode_log": Path(
            "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/self_check/async_episode_log.csv"
        ),
        "full_gate_comparison_strict": Path(
            "solver/reports/dr_alns_ppo_v3_block_dr_alns/full_gate_10001/comparison_strict.csv"
        ),
    }
    audit: dict[str, Any] = {
        "status": "EXISTING_REPORTS_NOT_BLOCK_TRAINING_DATA",
        "reason": "Existing artifacts are episode/run summaries and do not contain per-block observation/action/outcome rows.",
        "sources": {},
    }
    for name, path in sources.items():
        rows = _read_csv(path) if path.exists() else []
        audit["sources"][name] = {
            "path": str(path),
            "exists": path.exists(),
            "row_count": len(rows),
            "columns": list(rows[0].keys()) if rows else [],
            "usable_as_training_rows": False,
        }
    _write_json(output_dir / "existing_trace_audit.json", audit)
    _write_existing_audit_md(output_dir / "existing_trace_audit.md", audit)
    return 0


def run_collect(args: argparse.Namespace) -> int:
    output_dir = _checked_output_dir(Path(args.output_dir))
    dataset_dir = output_dir / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    _require_system_worker(args.required_worker_python)
    manifest = load_manifest(args.manifest)
    bundles = _selected_bundles(manifest, args.split)
    policies = _parse_csv_list(args.policies)
    tasks: list[TraceEpisodeTask] = []
    episode_index = 0
    for policy in policies:
        if policy not in {"random_block", "alpha_ucb_block", "stratified_random"}:
            raise ValueError(f"unknown collection policy: {policy}")
        for repeat in range(int(args.episodes_per_policy)):
            for bundle in bundles:
                tasks.append(
                    TraceEpisodeTask(
                        episode_index=episode_index,
                        bundle=bundle,
                        seed=int(args.seed) + 1000 * repeat + episode_index,
                        policy=policy,
                        eval_budget=int(args.eval_budget),
                        block_size=int(args.block_size),
                    )
                )
                episode_index += 1
    start = time.monotonic()
    rows, episodes = _execute_trace_tasks(tasks, jobs=int(args.jobs), partial_path=dataset_dir / "block_trace_rows.partial.csv")
    supplement_tasks: list[TraceEpisodeTask] = []
    coverage = summarize_action_coverage(rows)
    while (
        not bool(args.disable_auto_supplement)
        and not coverage["pass_minimum_coverage"]
        and len(supplement_tasks) < int(args.max_supplement_episodes)
    ):
        remaining = int(args.max_supplement_episodes) - len(supplement_tasks)
        chunk_count = min(int(args.supplement_chunk_size), remaining)
        chunk: list[TraceEpisodeTask] = []
        for _ in range(chunk_count):
            bundle = bundles[episode_index % len(bundles)]
            task = TraceEpisodeTask(
                episode_index=episode_index,
                bundle=bundle,
                seed=int(args.seed) + 100000 + episode_index,
                policy=str(args.supplement_policy),
                eval_budget=int(args.eval_budget),
                block_size=int(args.block_size),
            )
            chunk.append(task)
            supplement_tasks.append(task)
            episode_index += 1
        new_rows, new_episodes = _execute_trace_tasks(
            chunk,
            jobs=int(args.jobs),
            partial_path=dataset_dir / "block_trace_rows.partial.csv",
            existing_rows=rows,
        )
        rows.extend(new_rows)
        episodes.extend(new_episodes)
        coverage = summarize_action_coverage(rows)
    rows.sort(key=lambda row: (row["episode_index"], row["block_step_index"]))
    episodes.sort(key=lambda row: row["episode_index"])
    _write_csv(dataset_dir / "block_trace_rows.csv", rows, fieldnames=_trace_fieldnames())
    _write_csv(dataset_dir / "episode_summary.csv", episodes, fieldnames=_episode_summary_fieldnames())
    coverage = summarize_action_coverage(rows)
    stats = summarize_dataset(rows, episodes, coverage=coverage, elapsed_seconds=time.monotonic() - start, args=args)
    _write_csv(dataset_dir / "action_coverage.csv", _coverage_rows(coverage))
    _write_json(dataset_dir / "dataset_stats.json", stats)
    _write_json(dataset_dir / "collection_manifest.json", _collection_manifest(args, tasks, supplement_tasks, stats))
    _write_dataset_report(dataset_dir / "dataset_report.md", stats)
    return 0 if stats["integrity"]["pass_collection_integrity"] else 2


def _execute_trace_tasks(
    tasks: list[TraceEpisodeTask],
    *,
    jobs: int,
    partial_path: Path,
    existing_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    episodes: list[dict[str, Any]] = []
    if int(jobs) > 1 and len(tasks) > 1:
        with concurrent.futures.ProcessPoolExecutor(max_workers=min(int(jobs), len(tasks))) as executor:
            futures = [executor.submit(run_trace_episode, task) for task in tasks]
            for future in concurrent.futures.as_completed(futures):
                episode = future.result()
                episodes.append(_episode_summary_row(episode))
                rows.extend(episode["block_rows"])
                _write_csv(partial_path, list(existing_rows or []) + rows, fieldnames=_trace_fieldnames())
    else:
        for task in tasks:
            episode = run_trace_episode(task)
            episodes.append(_episode_summary_row(episode))
            rows.extend(episode["block_rows"])
            _write_csv(partial_path, list(existing_rows or []) + rows, fieldnames=_trace_fieldnames())
    return rows, episodes


def run_train(args: argparse.Namespace) -> int:
    output_dir = _checked_output_dir(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_csv(args.dataset)
    coverage = summarize_action_coverage(rows)
    stats = summarize_dataset(rows, [], coverage=coverage, elapsed_seconds=0.0, args=args)
    if not bool(args.allow_insufficient_coverage) and not stats["coverage"]["pass_minimum_coverage"]:
        _write_json(output_dir / "offline_training_halt.json", stats)
        _write_training_halt_md(output_dir / "offline_training_report.md", stats)
        return 2
    obs, actions, rewards, weights = _training_arrays(rows)
    model = make_block_actor_critic(seed=int(args.seed), hidden_size=int(args.hidden_size))
    curve = train_advantage_weighted_bc(
        model,
        obs=obs,
        actions=actions,
        rewards=rewards,
        weights=weights,
        seed=int(args.seed),
        epochs=int(args.epochs),
        batch_size=int(args.batch_size),
        learning_rate=float(args.learning_rate),
        entropy_coef=float(args.entropy_coef),
        value_coef=float(args.value_coef),
    )
    model_path = output_dir / "offline_policy.pt"
    metadata = {
        "format": "offline_contextual_bandit_awbc.v1",
        "dataset": str(args.dataset),
        "row_count": len(rows),
        "coverage": stats["coverage"],
        "seed": int(args.seed),
        "epochs": int(args.epochs),
        "training_objective": "advantage-weighted behavioral cloning with progress-bucket reward baseline",
    }
    save_async_block_policy(model_path, model, metadata=metadata)
    _write_csv(output_dir / "training_curve.csv", curve, fieldnames=_curve_fieldnames())
    _write_policy_entropy(output_dir / "policy_entropy.csv", model, obs)
    _write_json(output_dir / "offline_training_summary.json", {"model_path": str(model_path), **metadata})
    _write_training_report(output_dir / "offline_training_report.md", metadata, curve)
    return 0


def run_evaluate(args: argparse.Namespace) -> int:
    output_dir = _checked_output_dir(Path(args.output_dir))
    eval_dir = output_dir / "eval_10001"
    eval_dir.mkdir(parents=True, exist_ok=True)
    _require_system_worker(args.required_worker_python)
    ns = argparse.Namespace(
        manifest=args.manifest,
        model=args.model,
        algorithms="ppo_block,random_block,alpha_ucb_block,official_winner_kernel",
        split="formal_eval",
        bundle_filter=args.bundle_filter,
        eval_budget=int(args.eval_budget),
        seeds=args.seeds,
        output_dir=str(eval_dir),
        base_temperature=100.0,
        block_size=int(args.block_size),
        stochastic_ppo=bool(args.stochastic_policy),
        official_max_runtime_seconds=float(args.official_max_runtime_seconds),
        jobs=int(args.jobs),
        resume_comparison=args.resume_comparison,
        rerun_underbudget=bool(args.rerun_underbudget),
    )
    rows = evaluate_policy(ns)
    _write_json(eval_dir / "evaluation_manifest.json", {"rows": len(rows), "args": vars(ns)})
    return 0


def run_report(args: argparse.Namespace) -> int:
    output_dir = _checked_output_dir(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_stats_path = Path(args.dataset_stats)
    comparison_path = Path(args.comparison)
    dataset_stats = json.loads(dataset_stats_path.read_text(encoding="utf-8")) if dataset_stats_path.exists() else {}
    comparison_rows = _read_csv(comparison_path) if comparison_path.exists() else []
    verdict = verdict_from_comparison(comparison_rows)
    report = {
        "dataset_stats_path": str(dataset_stats_path),
        "comparison_path": str(comparison_path),
        "dataset": dataset_stats,
        "comparison": summarize_comparison(comparison_rows),
        "verdict": verdict,
    }
    _write_json(output_dir / "offline_bandit_report.json", report)
    _write_offline_bandit_md(output_dir / "offline_bandit_report.md", report)
    if verdict["status"] == "PROMISING":
        _write_machine_transfer_checklist(output_dir / "machine_transfer_checklist.md")
    return 0 if verdict["status"] in {"PROMISING", "WEAK"} else 2


def summarize_action_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    action_cols = ["action_destroy", "action_repair", "action_q", "action_threshold", "action_exploration"]
    full_actions = {tuple(int(float(row[col])) for col in action_cols) for row in rows}
    marginal = {
        col: sorted({int(float(row[col])) for row in rows})
        for col in action_cols
    }
    expected = {
        "action_destroy": int(BLOCK_ACTION_NVECS[0]),
        "action_repair": int(BLOCK_ACTION_NVECS[1]),
        "action_q": int(BLOCK_ACTION_NVECS[2]),
        "action_threshold": int(BLOCK_ACTION_NVECS[3]),
        "action_exploration": int(BLOCK_ACTION_NVECS[4]),
    }
    pass_marginal = all(len(marginal[col]) >= expected[col] for col in action_cols)
    pass_unique = len(full_actions) >= MIN_UNIQUE_FULL_ACTIONS
    pass_rows = len(rows) >= MIN_BLOCK_ROWS
    return {
        "row_count": len(rows),
        "unique_full_actions": len(full_actions),
        "minimum_unique_full_actions": MIN_UNIQUE_FULL_ACTIONS,
        "minimum_block_rows": MIN_BLOCK_ROWS,
        "marginal_coverage": {col: len(values) for col, values in marginal.items()},
        "marginal_values": marginal,
        "expected_marginal_coverage": expected,
        "pass_marginal_coverage": pass_marginal,
        "pass_unique_full_actions": pass_unique,
        "pass_minimum_rows": pass_rows,
        "pass_minimum_coverage": bool(pass_marginal and pass_unique and pass_rows),
    }


def summarize_dataset(
    rows: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    *,
    coverage: dict[str, Any],
    elapsed_seconds: float,
    args: argparse.Namespace,
) -> dict[str, Any]:
    worker_ok = all(str(row.get("worker_python_executable", "")) == str(getattr(args, "required_worker_python", DEFAULT_SYSTEM_WORKER)) for row in rows)
    numpy_ok = all(str(row.get("worker_numpy_version", "")) == SYSTEM_WORKER_NUMPY for row in rows)
    zero_violations = all(int(float(row.get("violation_count", 1))) == 0 for row in rows)
    evals_positive = all(int(float(row.get("actual_evals_after", 0))) > int(float(row.get("actual_evals_before", -1))) for row in rows)
    return {
        "row_count": len(rows),
        "episode_count": len(episodes),
        "elapsed_seconds": float(elapsed_seconds),
        "block_size": int(getattr(args, "block_size", 128)),
        "eval_budget": int(getattr(args, "eval_budget", 16000)),
        "coverage": coverage,
        "integrity": {
            "system_worker": worker_ok,
            "numpy_ok": numpy_ok,
            "zero_violations": zero_violations,
            "evals_progress": evals_positive,
            "pass_collection_integrity": bool(rows and worker_ok and numpy_ok and zero_violations and evals_positive),
        },
    }


def train_advantage_weighted_bc(
    model: BlockActorCritic,
    *,
    obs: np.ndarray,
    actions: np.ndarray,
    rewards: np.ndarray,
    weights: np.ndarray,
    seed: int,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    entropy_coef: float,
    value_coef: float,
) -> list[dict[str, Any]]:
    torch.manual_seed(int(seed))
    rng = np.random.default_rng(int(seed))
    optimizer = torch.optim.Adam(model.parameters(), lr=float(learning_rate))
    obs_tensor = torch.as_tensor(obs, dtype=torch.float32)
    action_tensor = torch.as_tensor(actions, dtype=torch.long)
    reward_tensor = torch.as_tensor(rewards, dtype=torch.float32)
    weight_tensor = torch.as_tensor(weights, dtype=torch.float32)
    n = int(obs_tensor.shape[0])
    curve: list[dict[str, Any]] = []
    for epoch in range(int(epochs)):
        order = rng.permutation(n)
        losses: list[float] = []
        entropies: list[float] = []
        ce_values: list[float] = []
        value_losses: list[float] = []
        for start in range(0, n, int(batch_size)):
            idx = torch.as_tensor(order[start : start + int(batch_size)], dtype=torch.long)
            logits, values = model(obs_tensor[idx])
            ce_parts = []
            entropy_parts = []
            for head_idx, logit in enumerate(logits):
                ce_parts.append(nn.functional.cross_entropy(logit, action_tensor[idx, head_idx], reduction="none"))
                probs = torch.softmax(logit, dim=-1)
                entropy_parts.append(-(probs * torch.log_softmax(logit, dim=-1)).sum(dim=-1))
            ce = torch.stack(ce_parts, dim=-1).sum(dim=-1)
            entropy = torch.stack(entropy_parts, dim=-1).sum(dim=-1).mean()
            value_loss = nn.functional.mse_loss(values, reward_tensor[idx])
            loss = (ce * weight_tensor[idx]).mean() + float(value_coef) * value_loss - float(entropy_coef) * entropy
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(float(loss.detach()))
            ce_values.append(float((ce * weight_tensor[idx]).mean().detach()))
            entropies.append(float(entropy.detach()))
            value_losses.append(float(value_loss.detach()))
        curve.append(
            {
                "epoch": epoch + 1,
                "loss": _mean(losses),
                "weighted_ce": _mean(ce_values),
                "value_loss": _mean(value_losses),
                "entropy": _mean(entropies),
                "mean_sample_weight": float(np.mean(weights)),
                "max_sample_weight": float(np.max(weights)),
            }
        )
    return curve


def verdict_from_comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"status": "HALT_INTEGRITY", "reason": "comparison.csv is missing or empty"}
    integrity = comparison_integrity(rows)
    if not integrity["pass"]:
        return {"status": "HALT_INTEGRITY", "reason": integrity["reason"], "integrity": integrity}
    summary = summarize_comparison(rows)
    ppo = summary.get("ppo_block")
    random = summary.get("random_block")
    alpha = summary.get("alpha_ucb_block")
    if not ppo or not random or not alpha:
        return {"status": "HALT_INTEGRITY", "reason": "comparison must include ppo_block, random_block, and alpha_ucb_block"}
    wins_vs_random = paired_wins(rows, "ppo_block", "random_block")
    ppo_mean = float(ppo["mean_best_obj"])
    random_mean = float(random["mean_best_obj"])
    alpha_mean = float(alpha["mean_best_obj"])
    promising = ppo_mean <= random_mean and wins_vs_random >= 6 and ppo_mean <= alpha_mean * 1.01
    return {
        "status": "PROMISING" if promising else "WEAK",
        "ppo_mean": ppo_mean,
        "random_block_mean": random_mean,
        "alpha_ucb_block_mean": alpha_mean,
        "wins_vs_random_block": wins_vs_random,
        "rule": "PROMISING iff ppo_block mean <= random_block mean, wins >= 6/10, and ppo_block mean <= alpha_ucb_block mean * 1.01",
        "integrity": integrity,
    }


def comparison_integrity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if any(int(float(row.get("violation_count", 1))) != 0 for row in rows):
        return {"pass": False, "reason": "nonzero violations in comparison rows"}
    if any(str(row.get("worker_python_executable", "")) not in {"", DEFAULT_SYSTEM_WORKER} for row in rows):
        return {"pass": False, "reason": "comparison rows include non-system worker"}
    budgets = {int(float(row.get("eval_budget", 0))) for row in rows}
    if any(int(float(row.get("actual_evals", 0))) != int(float(row.get("eval_budget", 0))) for row in rows):
        return {"pass": False, "reason": "actual_evals differs from eval_budget"}
    return {"pass": True, "reason": "zero violations, budget matched, system worker rows", "eval_budgets": sorted(budgets)}


def summarize_comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("algorithm", "")), []).append(float(row.get("best_obj", 0.0)))
    summary: dict[str, Any] = {}
    for algorithm, values in grouped.items():
        summary[algorithm] = {
            "n": len(values),
            "mean_best_obj": _mean(values),
            "median_best_obj": float(statistics.median(values)),
            "best_obj": float(min(values)),
            "std_best_obj": float(statistics.pstdev(values)) if len(values) > 1 else 0.0,
        }
    return summary


def paired_wins(rows: list[dict[str, Any]], left_algorithm: str, right_algorithm: str) -> int:
    by_key: dict[tuple[str, int], dict[str, float]] = {}
    for row in rows:
        key = (str(row.get("bundle", "")), int(float(row.get("seed", 0))))
        by_key.setdefault(key, {})[str(row.get("algorithm", ""))] = float(row.get("best_obj", 0.0))
    wins = 0
    for values in by_key.values():
        if left_algorithm in values and right_algorithm in values and values[left_algorithm] <= values[right_algorithm]:
            wins += 1
    return wins


def _sample_collection_action(policy: str, *, rng: np.random.Generator, episode_index: int, step_index: int) -> np.ndarray:
    if policy == "alpha_ucb_block":
        return np.asarray(
            [
                BLOCK_DESTROY_IDS.index("alpha_ucb"),
                BLOCK_REPAIR_IDS.index("alpha_ucb"),
                1,
                0,
                0,
            ],
            dtype=np.int64,
        )
    if policy == "stratified_random":
        full_space = list(itertools.product(*(range(int(n)) for n in BLOCK_ACTION_NVECS)))
        idx = (int(episode_index) * 997 + int(step_index)) % len(full_space)
        return np.asarray(full_space[idx], dtype=np.int64)
    if policy == "random_block":
        return np.asarray([rng.integers(0, int(n)) for n in BLOCK_ACTION_NVECS], dtype=np.int64)
    raise ValueError(f"unknown policy: {policy}")


def _block_row(
    task: TraceEpisodeTask,
    *,
    step_index: int,
    observation: np.ndarray,
    action: np.ndarray,
    reward: float,
    info: dict[str, Any],
    actual_evals_before: int,
) -> dict[str, Any]:
    trace = dict((info.get("trace", {}) if isinstance(info, dict) else {}) or {})
    row: dict[str, Any] = {
        "episode_index": int(task.episode_index),
        "bundle": task.bundle,
        "seed": int(task.seed),
        "collection_policy": task.policy,
        "block_step_index": int(step_index),
        "eval_budget": int(task.eval_budget),
        "block_size": int(task.block_size),
        "action_destroy": int(action[0]),
        "action_repair": int(action[1]),
        "action_q": int(action[2]),
        "action_threshold": int(action[3]),
        "action_exploration": int(action[4]),
        "decoded_destroy_id": _safe_index(BLOCK_DESTROY_IDS, int(action[0])),
        "decoded_repair_id": _safe_index(BLOCK_REPAIR_IDS, int(action[1])),
        "decoded_q_ratio": float(_safe_index(BLOCK_Q_RATIOS, int(action[2]), 0.0)),
        "decoded_threshold_ratio": float(_safe_index(BLOCK_THRESHOLD_RATIOS, int(action[3]), 0.0)),
        "decoded_exploration_ratio": float(_safe_index(BLOCK_EXPLORATION_RATIOS, int(action[4]), 0.0)),
        "reward": float(reward),
        "block_best_delta": float(trace.get("block_best_delta", 0.0) or 0.0),
        "block_current_delta": float(trace.get("block_current_delta", 0.0) or 0.0),
        "block_best_route_delta": int(float(trace.get("block_best_route_delta", 0.0) or 0.0)),
        "block_current_route_delta": int(float(trace.get("block_current_route_delta", 0.0) or 0.0)),
        "block_accepted_count": int(float(trace.get("block_accepted_count", 0.0) or 0.0)),
        "block_rejected_count": int(float(trace.get("block_rejected_count", 0.0) or 0.0)),
        "block_improved_current_count": int(float(trace.get("block_improved_current_count", 0.0) or 0.0)),
        "block_improved_best_count": int(float(trace.get("block_improved_best_count", 0.0) or 0.0)),
        "block_iterations": int(float(trace.get("block_iterations", 0.0) or 0.0)),
        "actual_evals_before": int(actual_evals_before),
        "actual_evals_after": int(info.get("actual_evals", 0)),
        "best_obj": float(info.get("best_obj", 0.0)),
        "current_obj": float(info.get("current_obj", 0.0)),
        "violation_count": int(info.get("violation_count", 1)),
        "worker_python_executable": str(trace.get("worker_python_executable", "")),
        "worker_python_version": str(trace.get("worker_python_version", "")),
        "worker_numpy_version": str(trace.get("worker_numpy_version", "")),
    }
    for idx in range(BLOCK_OBSERVATION_SIZE):
        row[f"obs_{idx:02d}"] = float(observation[idx])
    return row


def _training_arrays(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    obs = np.asarray([[float(row[f"obs_{idx:02d}"]) for idx in range(BLOCK_OBSERVATION_SIZE)] for row in rows], dtype=np.float32)
    actions = np.asarray(
        [
            [
                int(float(row["action_destroy"])),
                int(float(row["action_repair"])),
                int(float(row["action_q"])),
                int(float(row["action_threshold"])),
                int(float(row["action_exploration"])),
            ]
            for row in rows
        ],
        dtype=np.int64,
    )
    rewards = np.asarray([float(row["reward"]) for row in rows], dtype=np.float32)
    progress = np.asarray([float(row.get("obs_01", 0.0)) for row in rows], dtype=np.float32)
    weights = _advantage_weights(rewards, progress)
    return obs, actions, rewards, weights


def _advantage_weights(rewards: np.ndarray, progress: np.ndarray) -> np.ndarray:
    buckets = np.clip(np.floor(progress * 10.0).astype(int), 0, 9)
    baseline = np.zeros_like(rewards, dtype=np.float32)
    for bucket in range(10):
        mask = buckets == bucket
        if np.any(mask):
            baseline[mask] = float(np.median(rewards[mask]))
    positive = np.maximum(rewards - baseline, 0.0)
    scale = float(np.percentile(positive[positive > 0], 95)) if np.any(positive > 0) else 1.0
    scale = max(scale, 1e-6)
    weights = 0.25 + 4.75 * np.clip(positive / scale, 0.0, 1.0)
    return weights.astype(np.float32)


def _write_policy_entropy(path: Path, model: BlockActorCritic, obs: np.ndarray) -> None:
    with torch.no_grad():
        dists, _values = model.distributions(torch.as_tensor(obs[: min(len(obs), 2048)], dtype=torch.float32))
        rows = []
        for idx, dist in enumerate(dists):
            entropy = dist.entropy().mean().item()
            max_entropy = math.log(float(BLOCK_ACTION_NVECS[idx]))
            rows.append(
                {
                    "head_index": idx,
                    "action_count": int(BLOCK_ACTION_NVECS[idx]),
                    "mean_entropy": float(entropy),
                    "max_entropy": float(max_entropy),
                    "entropy_ratio": float(entropy / max(max_entropy, 1e-9)),
                }
            )
    _write_csv(path, rows, fieldnames=["head_index", "action_count", "mean_entropy", "max_entropy", "entropy_ratio"])


def _selected_bundles(manifest: dict[str, Any], split: str) -> list[str]:
    if split == "train":
        return list(manifest["train"])
    if split == "held_out":
        return list(manifest["held_out"])
    if split == "formal_eval":
        return list(manifest["formal_eval"])
    raise ValueError(f"unsupported split for offline bandit collection: {split}")


def _parse_csv_list(value: str) -> list[str]:
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _safe_index(values: tuple[Any, ...], index: int, default: Any = "") -> Any:
    if 0 <= int(index) < len(values):
        return values[int(index)]
    return default


def _episode_summary_row(episode: dict[str, Any]) -> dict[str, Any]:
    return {
        "episode_index": int(episode["episode_index"]),
        "bundle": episode["bundle"],
        "seed": int(episode["seed"]),
        "policy": episode["policy"],
        "eval_budget": int(episode["eval_budget"]),
        "block_size": int(episode["block_size"]),
        "block_steps": int(episode["block_steps"]),
        "best_obj": float(episode["best_obj"]),
        "actual_evals": int(episode["actual_evals"]),
        "violation_count": int(episode["violation_count"]),
        "wall_time_seconds": float(episode["wall_time_seconds"]),
        "worker_python_executable": episode["worker_python_executable"],
        "worker_python_version": episode["worker_python_version"],
        "worker_numpy_version": episode["worker_numpy_version"],
        "pid": int(episode["pid"]),
    }


def _coverage_rows(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key, count in coverage["marginal_coverage"].items():
        rows.append(
            {
                "coverage_type": key,
                "observed": int(count),
                "expected": int(coverage["expected_marginal_coverage"][key]),
                "pass": int(int(count) >= int(coverage["expected_marginal_coverage"][key])),
            }
        )
    rows.append(
        {
            "coverage_type": "unique_full_actions",
            "observed": int(coverage["unique_full_actions"]),
            "expected": int(coverage["minimum_unique_full_actions"]),
            "pass": int(bool(coverage["pass_unique_full_actions"])),
        }
    )
    rows.append(
        {
            "coverage_type": "block_rows",
            "observed": int(coverage["row_count"]),
            "expected": int(coverage["minimum_block_rows"]),
            "pass": int(bool(coverage["pass_minimum_rows"])),
        }
    )
    return rows


def _collection_manifest(
    args: argparse.Namespace,
    tasks: list[TraceEpisodeTask],
    supplement_tasks: list[TraceEpisodeTask],
    stats: dict[str, Any],
) -> dict[str, Any]:
    return {
        "command": "collect",
        "args": vars(args),
        "initial_task_count": len(tasks),
        "supplement_task_count": len(supplement_tasks),
        "stats": stats,
        "policy": "Rows are real block-level transitions; existing episode/run reports are not treated as training rows.",
    }


def _checked_output_dir(path: Path) -> Path:
    text = str(path)
    if REPORT_ROOT_FRAGMENT not in text:
        raise ValueError(f"offline bandit reports must stay under {REPORT_ROOT_FRAGMENT}: {path}")
    return path


def _require_system_worker(required: str) -> None:
    configured = os.environ.get("SETP_WORKER_PYTHON", "")
    if configured != required:
        raise RuntimeError(f"SETP_WORKER_PYTHON must be {required}, got {configured!r}")


def _read_csv(path: str | Path) -> list[dict[str, Any]]:
    value = Path(path)
    if not value.exists():
        return []
    with value.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], *, fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fieldnames or (list(rows[0].keys()) if rows else [])
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not fields:
            return
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_existing_audit_md(path: Path, audit: dict[str, Any]) -> None:
    lines = [
        "# Existing Trace Audit",
        "",
        f"Status: `{audit['status']}`.",
        "",
        audit["reason"],
        "",
        "| source | exists | rows | usable as block training rows |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, source in audit["sources"].items():
        lines.append(f"| {name} | {source['exists']} | {source['row_count']} | {source['usable_as_training_rows']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_dataset_report(path: Path, stats: dict[str, Any]) -> None:
    coverage = stats["coverage"]
    integrity = stats["integrity"]
    lines = [
        "# Offline Bandit Dataset",
        "",
        f"Rows: {stats['row_count']}. Episodes: {stats['episode_count']}.",
        f"Coverage pass: `{coverage['pass_minimum_coverage']}`. Unique full actions: {coverage['unique_full_actions']}.",
        f"Integrity pass: `{integrity['pass_collection_integrity']}`.",
        "",
        "This is block-level training data. Earlier full-gate and async-pilot reports remain provenance only.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_training_halt_md(path: Path, stats: dict[str, Any]) -> None:
    lines = [
        "# Offline Bandit Training Halted",
        "",
        "Training did not run because the block dataset failed the minimum coverage gate.",
        "",
        f"Rows: {stats['coverage']['row_count']} / {stats['coverage']['minimum_block_rows']}.",
        f"Unique full actions: {stats['coverage']['unique_full_actions']} / {stats['coverage']['minimum_unique_full_actions']}.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_training_report(path: Path, metadata: dict[str, Any], curve: list[dict[str, Any]]) -> None:
    last = curve[-1] if curve else {}
    lines = [
        "# Offline Bandit Training",
        "",
        "Model: advantage-weighted behavioral cloning over real block transitions.",
        "",
        f"Rows: {metadata['row_count']}.",
        f"Model path: `{metadata.get('model_path', 'offline_policy.pt')}`.",
        f"Final weighted CE: {float(last.get('weighted_ce', 0.0)):.6f}.",
        f"Final entropy: {float(last.get('entropy', 0.0)):.6f}.",
        "",
        "This is not a performance verdict. Use the 100-01 comparison report for that.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_offline_bandit_md(path: Path, report: dict[str, Any]) -> None:
    verdict = report["verdict"]
    comparison = report.get("comparison", {})
    lines = [
        "# Offline Bandit Block DR-ALNS Report",
        "",
        f"Verdict: `{verdict['status']}`.",
        "",
    ]
    if comparison:
        lines.extend(["| algorithm | n | mean £ | median £ | best £ | std £ |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
        for algorithm, row in sorted(comparison.items()):
            lines.append(
                f"| {algorithm} | {row['n']} | {row['mean_best_obj']:.6f} | {row['median_best_obj']:.6f} | {row['best_obj']:.6f} | {row['std_best_obj']:.6f} |"
            )
    lines.extend(
        [
            "",
            "Plain-language reading:",
            _plain_verdict(verdict),
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _plain_verdict(verdict: dict[str, Any]) -> str:
    status = verdict.get("status")
    if status == "PROMISING":
        return "The offline policy beat the strong random-block baseline and stayed close to AlphaUCB. It is worth moving to a stronger machine for online warm-start training."
    if status == "WEAK":
        return "The offline policy did not clear the strong random-block baseline. This is evidence against spending more local online-training time on the current PPO formulation."
    return f"Integrity gate failed: {verdict.get('reason', 'unknown reason')}."


def _write_machine_transfer_checklist(path: Path) -> None:
    lines = [
        "# Machine Transfer Checklist",
        "",
        "Before training on the CUDA/16-thread machine, reproduce the deterministic solver anchor first: 100-01 winner kernel mean about 4878, seed2 about 4779, zero violations.",
        "",
        "Use Python 3.13 with NumPy 2.3.5 for solver workers, set `SETP_WORKER_PYTHON` to that absolute interpreter, and keep the RL venv only for torch/SB3/gymnasium.",
        "",
        "Move the generated instances, block traces, `offline_policy.pt`, async block lane code, and report manifests together. Treat the offline policy as warm-start weights, not as a final paper-grade DRL result.",
        "",
        "Throughput target on the new machine: busy ratio above 0.60 and 72000 block steps in hours rather than days. If the deterministic anchor drifts, align Python/NumPy/BLAS before any training.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _trace_fieldnames() -> list[str]:
    base = [
        "episode_index",
        "bundle",
        "seed",
        "collection_policy",
        "block_step_index",
        "eval_budget",
        "block_size",
        "action_destroy",
        "action_repair",
        "action_q",
        "action_threshold",
        "action_exploration",
        "decoded_destroy_id",
        "decoded_repair_id",
        "decoded_q_ratio",
        "decoded_threshold_ratio",
        "decoded_exploration_ratio",
        "reward",
        "block_best_delta",
        "block_current_delta",
        "block_best_route_delta",
        "block_current_route_delta",
        "block_accepted_count",
        "block_rejected_count",
        "block_improved_current_count",
        "block_improved_best_count",
        "block_iterations",
        "actual_evals_before",
        "actual_evals_after",
        "best_obj",
        "current_obj",
        "violation_count",
        "worker_python_executable",
        "worker_python_version",
        "worker_numpy_version",
    ]
    return base + [f"obs_{idx:02d}" for idx in range(BLOCK_OBSERVATION_SIZE)]


def _episode_summary_fieldnames() -> list[str]:
    return [
        "episode_index",
        "bundle",
        "seed",
        "policy",
        "eval_budget",
        "block_size",
        "block_steps",
        "best_obj",
        "actual_evals",
        "violation_count",
        "wall_time_seconds",
        "worker_python_executable",
        "worker_python_version",
        "worker_numpy_version",
        "pid",
    ]


def _curve_fieldnames() -> list[str]:
    return ["epoch", "loss", "weighted_ce", "value_loss", "entropy", "mean_sample_weight", "max_sample_weight"]


def _mean(values: list[float] | np.ndarray) -> float:
    if len(values) == 0:
        return 0.0
    return float(sum(float(v) for v in values) / len(values))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline contextual-bandit lane for block DR-ALNS.")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit-existing")
    audit.add_argument("--output-dir", default=f"{REPORT_ROOT_FRAGMENT}/audit")

    collect = sub.add_parser("collect")
    collect.add_argument("--manifest", default="solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json")
    collect.add_argument("--split", choices=("train", "held_out", "formal_eval"), default="train")
    collect.add_argument("--output-dir", default=f"{REPORT_ROOT_FRAGMENT}")
    collect.add_argument("--policies", default="random_block,alpha_ucb_block,stratified_random")
    collect.add_argument("--episodes-per-policy", type=int, default=1)
    collect.add_argument("--seed", type=int, default=1)
    collect.add_argument("--eval-budget", type=int, default=16000)
    collect.add_argument("--block-size", type=int, default=128)
    collect.add_argument("--jobs", type=int, default=6)
    collect.add_argument("--required-worker-python", default=DEFAULT_SYSTEM_WORKER)
    collect.add_argument("--disable-auto-supplement", action="store_true")
    collect.add_argument("--supplement-policy", choices=("random_block", "stratified_random"), default="stratified_random")
    collect.add_argument("--supplement-chunk-size", type=int, default=6)
    collect.add_argument("--max-supplement-episodes", type=int, default=64)

    train = sub.add_parser("train")
    train.add_argument("--dataset", default=f"{REPORT_ROOT_FRAGMENT}/dataset/block_trace_rows.csv")
    train.add_argument("--output-dir", default=f"{REPORT_ROOT_FRAGMENT}/train")
    train.add_argument("--seed", type=int, default=1)
    train.add_argument("--hidden-size", type=int, default=128)
    train.add_argument("--epochs", type=int, default=80)
    train.add_argument("--batch-size", type=int, default=256)
    train.add_argument("--learning-rate", type=float, default=3e-4)
    train.add_argument("--entropy-coef", type=float, default=0.005)
    train.add_argument("--value-coef", type=float, default=0.05)
    train.add_argument("--allow-insufficient-coverage", action="store_true")

    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--manifest", default="solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json")
    evaluate.add_argument("--model", default=f"{REPORT_ROOT_FRAGMENT}/train/offline_policy.pt")
    evaluate.add_argument("--output-dir", default=f"{REPORT_ROOT_FRAGMENT}")
    evaluate.add_argument("--bundle-filter", default="E-UK100_01")
    evaluate.add_argument("--eval-budget", type=int, default=16000)
    evaluate.add_argument("--block-size", type=int, default=128)
    evaluate.add_argument("--seeds", default="1,2,3,4,5,6,7,8,9,10")
    evaluate.add_argument("--jobs", type=int, default=6)
    evaluate.add_argument("--official-max-runtime-seconds", type=float, default=900.0)
    evaluate.add_argument("--required-worker-python", default=DEFAULT_SYSTEM_WORKER)
    evaluate.add_argument("--resume-comparison")
    evaluate.add_argument("--rerun-underbudget", action="store_true")
    evaluate.add_argument("--stochastic-policy", action="store_true")

    report = sub.add_parser("report")
    report.add_argument("--output-dir", default=f"{REPORT_ROOT_FRAGMENT}")
    report.add_argument("--dataset-stats", default=f"{REPORT_ROOT_FRAGMENT}/dataset/dataset_stats.json")
    report.add_argument("--comparison", default=f"{REPORT_ROOT_FRAGMENT}/eval_10001/comparison.csv")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "audit-existing":
        return run_audit_existing(args)
    if args.command == "collect":
        return run_collect(args)
    if args.command == "train":
        return run_train(args)
    if args.command == "evaluate":
        return run_evaluate(args)
    if args.command == "report":
        return run_report(args)
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
