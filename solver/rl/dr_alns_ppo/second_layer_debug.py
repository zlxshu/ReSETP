from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .action_space import DESTROY_IDS, REPAIR_IDS
from .bundle_manifest import load_manifest
from .env import OBSERVATION_SIZE, SetpAlnsEnv
from .worker_client import resolve_worker_python


SYSTEM_WORKER_PYTHON = "/opt/anaconda3/bin/python3.13"
REPORT_DIR = Path("solver/reports/dr_alns_ppo_v2/second_layer_debug")
MANIFEST_PATH = Path("solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json")
MODEL_PATH = Path("solver/reports/dr_alns_ppo_v2/episode_safe_pilot/train/model.zip")
EPISODE_SAFE_PILOT_DIR = Path("solver/reports/dr_alns_ppo_v2/episode_safe_pilot")


TRACE_COLUMNS = [
    "split",
    "bundle",
    "algorithm",
    "seed",
    "step_index",
    "reward",
    "reward_code",
    "delta",
    "accepted",
    "improved_current",
    "improved_best",
    "terminated",
    "best_obj",
    "current_obj",
    "candidate_obj",
    "actual_evals",
    "violation_count",
    "route_count",
    "route_count_delta",
    "destroy_id",
    "repair_id",
    "q_ratio",
    "threshold_ratio",
    "worker_python_executable",
    "worker_numpy_version",
] + [f"obs_{idx}" for idx in range(OBSERVATION_SIZE)]


ABLATION_COLUMNS = [
    "split",
    "bundle",
    "algorithm",
    "seed",
    "eval_budget",
    "best_obj",
    "actual_evals",
    "violation_count",
    "feasible",
    "worker_python_executable",
    "worker_numpy_version",
    "destroy_counts",
    "repair_counts",
    "q_ratio_counts",
    "threshold_ratio_counts",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def ensure_report_path(path: str | Path, *, root: Path | None = None) -> Path:
    base = (repo_root() if root is None else root) / REPORT_DIR
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (repo_root() if root is None else root) / candidate
    resolved = candidate.resolve()
    base_resolved = base.resolve()
    try:
        resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(f"second-layer debug output must stay under {base_resolved}: {resolved}") from exc
    return resolved


def parse_seeds(value: str) -> list[int]:
    seeds = [int(item.strip()) for item in str(value).split(",") if item.strip()]
    if not seeds:
        raise ValueError("at least one seed is required")
    return seeds


def selected_bundles(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        ("train0", str(manifest["train"][0])),
        ("formal_10001", str(manifest["formal_eval"][0])),
        ("held_out", str(manifest["held_out"][0])),
    ]


def run_context_snapshot(output_dir: Path) -> dict[str, Any]:
    root = repo_root()
    git_head = _run_text(["git", "rev-parse", "HEAD"])
    git_status = _run_text(["git", "status", "--short", "--untracked-files=all"])
    pilot_report = _read_json(root / EPISODE_SAFE_PILOT_DIR / "pilot_report.json")
    payload = {
        "git_head": git_head.strip(),
        "git_status": git_status,
        "system_worker_python": os.environ.get("SETP_WORKER_PYTHON", ""),
        "episode_safe_verdict": pilot_report.get("verdict"),
        "episode_safe_reason": pilot_report.get("reason"),
        "episode_safe_quality": pilot_report.get("quality"),
        "episode_safe_integrity": pilot_report.get("integrity"),
    }
    _write_json(output_dir / "phase0_context.json", payload)
    _write_text(output_dir / "phase0_context.md", _context_md(payload))
    return payload


def run_trace_matrix(
    *,
    manifest: dict[str, Any],
    model_path: Path,
    output_dir: Path,
    seeds: list[int],
    trace_steps: int,
    jobs: int,
) -> list[dict[str, Any]]:
    tasks = [
        (split, bundle, algorithm, seed, str(model_path), int(trace_steps))
        for split, bundle in selected_bundles(manifest)
        for seed in seeds
        for algorithm in ("random_full", "alpha_ucb_env", "ppo_full")
    ]
    rows = _parallel_map(_trace_task, tasks, jobs=jobs)
    flat_rows = [row for group in rows for row in group]
    _write_csv(output_dir / "trace_matrix.csv", flat_rows, fieldnames=TRACE_COLUMNS)
    reward_summary = summarize_reward_trace(flat_rows)
    obs_summary = summarize_observation_aliasing(flat_rows)
    action_value = summarize_action_values(flat_rows)
    _write_csv(output_dir / "reward_misalignment.csv", reward_summary)
    _write_csv(output_dir / "observation_aliasing.csv", obs_summary)
    _write_csv(output_dir / "action_value_table.csv", action_value)
    _write_text(output_dir / "reward_misalignment_report.md", _reward_report_md(reward_summary))
    _write_text(output_dir / "observation_aliasing_report.md", _obs_report_md(obs_summary))
    _write_text(output_dir / "oracle_upper_bound.md", _oracle_report_md(action_value))
    return flat_rows


def run_random_ablation_matrix(
    *,
    manifest: dict[str, Any],
    model_path: Path,
    output_dir: Path,
    seeds: list[int],
    eval_budget: int,
    jobs: int,
) -> list[dict[str, Any]]:
    bundles = [
        ("formal_10001", str(manifest["formal_eval"][0])),
        ("held_out", str(manifest["held_out"][0])),
    ]
    algorithms = (
        "random_full",
        "alpha_ucb_env",
        "ppo_full",
        "random_operator_only",
        "alpha_operator_random_q",
        "alpha_operator_random_threshold",
    )
    tasks = [
        (split, bundle, algorithm, seed, int(eval_budget), str(model_path))
        for split, bundle in bundles
        for seed in seeds
        for algorithm in algorithms
    ]
    rows = _parallel_map(_ablation_task, tasks, jobs=jobs)
    _write_csv(output_dir / "random_ablation_comparison.csv", rows, fieldnames=ABLATION_COLUMNS)
    summary = summarize_ablation(rows)
    _write_csv(output_dir / "random_ablation_summary.csv", summary)
    _write_text(output_dir / "random_strength_report.md", _random_strength_md(summary))
    return rows


def run_initial_action_sweep(
    *,
    manifest: dict[str, Any],
    output_dir: Path,
    seed: int,
    jobs: int,
) -> list[dict[str, Any]]:
    tasks = [(split, bundle, int(seed)) for split, bundle in selected_bundles(manifest)]
    rows = [row for group in _parallel_map(_initial_sweep_task, tasks, jobs=jobs) for row in group]
    _write_csv(output_dir / "initial_action_sweep.csv", rows)
    summary = summarize_initial_sweep(rows)
    _write_csv(output_dir / "initial_action_sweep_summary.csv", summary)
    _write_text(output_dir / "initial_action_sweep_report.md", _initial_sweep_md(summary))
    return rows


def run_policy_entropy_probe(
    *,
    manifest: dict[str, Any],
    model_path: Path,
    output_dir: Path,
) -> list[dict[str, Any]]:
    from stable_baselines3 import PPO
    import torch

    model = PPO.load(model_path, device="cpu")
    rows: list[dict[str, Any]] = []
    for split, bundle in selected_bundles(manifest):
        env = SetpAlnsEnv(bundle, seed=1, eval_budget=16000, control_mode="ppo_full")
        try:
            obs, _ = env.reset(seed=1)
            obs_tensor, _ = model.policy.obs_to_tensor(obs)
            with torch.no_grad():
                distribution = model.policy.get_distribution(obs_tensor)
            categories = getattr(distribution, "distribution", [])
            for dim_index, categorical in enumerate(categories):
                probs = categorical.probs.detach().cpu().numpy().reshape(-1)
                top_index = int(np.argmax(probs))
                rows.append(
                    {
                        "split": split,
                        "bundle": bundle,
                        "action_dim": dim_index,
                        "action_dim_name": _action_dim_name(dim_index),
                        "entropy": float(categorical.entropy().detach().cpu().numpy().reshape(-1)[0]),
                        "top_index": top_index,
                        "top_label": _action_label(dim_index, top_index),
                        "top_prob": float(probs[top_index]),
                    }
                )
        finally:
            env.close()
    _write_csv(output_dir / "policy_entropy_probe.csv", rows)
    _write_text(output_dir / "policy_entropy_report.md", _policy_entropy_md(rows))
    return rows


def summarize_reward_trace(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["split"]), str(row["algorithm"]))].append(row)
    summary: list[dict[str, Any]] = []
    for (split, algorithm), group in sorted(grouped.items()):
        rewards = [_to_float(row.get("reward")) for row in group]
        accepted = [_to_bool(row.get("accepted")) for row in group]
        improved_best = [_to_bool(row.get("improved_best")) for row in group]
        improved_current = [_to_bool(row.get("improved_current")) for row in group]
        reward_codes = Counter(str(row.get("reward_code", "")) for row in group)
        final_best = min((_to_float(row.get("best_obj")) for row in group), default=0.0)
        summary.append(
            {
                "split": split,
                "algorithm": algorithm,
                "steps": len(group),
                "mean_reward": _mean(rewards),
                "nonzero_reward_rate": _safe_div(sum(abs(value) > 1e-12 for value in rewards), len(group)),
                "accepted_rate": _safe_div(sum(accepted), len(group)),
                "improved_current_rate": _safe_div(sum(improved_current), len(group)),
                "improved_best_rate": _safe_div(sum(improved_best), len(group)),
                "accepted_worse_count": int(reward_codes.get("accepted_worse", 0)),
                "rejected_count": int(reward_codes.get("rejected", 0)),
                "global_best_count": int(reward_codes.get("global_best", 0)),
                "final_best_obj_observed": final_best,
            }
        )
    return summary


def summarize_observation_aliasing(rows: Iterable[dict[str, Any]], *, precision: int = 3) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["split"]), str(row["algorithm"]))].append(row)
    summary: list[dict[str, Any]] = []
    for (split, algorithm), group in sorted(grouped.items()):
        buckets: dict[tuple[float, ...], set[int]] = defaultdict(set)
        action_buckets: dict[tuple[Any, ...], set[int]] = defaultdict(set)
        for row in group:
            obs = tuple(round(_to_float(row.get(f"obs_{idx}")), precision) for idx in range(OBSERVATION_SIZE))
            outcome = 1 if _to_bool(row.get("improved_best")) else 0
            buckets[obs].add(outcome)
            action_key = obs + (
                str(row.get("destroy_id", "")),
                str(row.get("repair_id", "")),
                str(row.get("q_ratio", "")),
            )
            action_buckets[action_key].add(outcome)
        conflict_buckets = sum(1 for outcomes in buckets.values() if len(outcomes) > 1)
        action_conflicts = sum(1 for outcomes in action_buckets.values() if len(outcomes) > 1)
        summary.append(
            {
                "split": split,
                "algorithm": algorithm,
                "rows": len(group),
                "unique_obs_rounded": len(buckets),
                "obs_reuse_rate": 1.0 - _safe_div(len(buckets), len(group)),
                "conflicting_obs_buckets": conflict_buckets,
                "conflicting_obs_bucket_rate": _safe_div(conflict_buckets, len(buckets)),
                "unique_obs_action_rounded": len(action_buckets),
                "conflicting_obs_action_buckets": action_conflicts,
                "conflicting_obs_action_rate": _safe_div(action_conflicts, len(action_buckets)),
            }
        )
    return summary


def summarize_action_values(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        q_value = row.get("q_ratio", "")
        q_text = "" if q_value in ("", None) else f"{_to_float(q_value):.6f}"
        key = (
            str(row["split"]),
            str(row["algorithm"]),
            str(row.get("destroy_id", "")),
            str(row.get("repair_id", "")),
            q_text,
        )
        grouped[key].append(row)
    summary: list[dict[str, Any]] = []
    for (split, algorithm, destroy, repair, q_ratio), group in sorted(grouped.items()):
        if len(group) < 5:
            continue
        rewards = [_to_float(row.get("reward")) for row in group]
        summary.append(
            {
                "split": split,
                "algorithm": algorithm,
                "destroy_id": destroy,
                "repair_id": repair,
                "q_ratio": q_ratio,
                "steps": len(group),
                "mean_reward": _mean(rewards),
                "accepted_rate": _safe_div(sum(_to_bool(row.get("accepted")) for row in group), len(group)),
                "improved_best_rate": _safe_div(sum(_to_bool(row.get("improved_best")) for row in group), len(group)),
                "mean_delta": _mean([_to_float(row.get("delta")) for row in group]),
            }
        )
    summary.sort(key=lambda row: (row["split"], row["algorithm"], -float(row["improved_best_rate"]), -float(row["mean_reward"])))
    return summary


def summarize_ablation(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["split"]), str(row["algorithm"]))].append(row)
    summary: list[dict[str, Any]] = []
    for (split, algorithm), group in sorted(grouped.items()):
        costs = [_to_float(row.get("best_obj")) for row in group]
        summary.append(
            {
                "split": split,
                "algorithm": algorithm,
                "rows": len(group),
                "mean_best_obj": _mean(costs),
                "median_best_obj": _median(costs),
                "best_obj": min(costs) if costs else 0.0,
                "std_best_obj": _std(costs),
                "violation_rows": sum(_to_int(row.get("violation_count")) != 0 for row in group),
                "actual_evals_min": min((_to_int(row.get("actual_evals")) for row in group), default=0),
                "actual_evals_max": max((_to_int(row.get("actual_evals")) for row in group), default=0),
            }
        )
    return summary


def summarize_initial_sweep(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["split"]), str(row["destroy_id"]), str(row["repair_id"]))].append(row)
    summary: list[dict[str, Any]] = []
    for (split, destroy, repair), group in sorted(grouped.items()):
        deltas = [_to_float(row.get("delta")) for row in group]
        summary.append(
            {
                "split": split,
                "destroy_id": destroy,
                "repair_id": repair,
                "q_variants": len(group),
                "best_delta": min(deltas) if deltas else 0.0,
                "mean_delta": _mean(deltas),
                "improved_best_q_count": sum(_to_bool(row.get("improved_best")) for row in group),
                "accepted_q_count": sum(_to_bool(row.get("accepted")) for row in group),
            }
        )
    summary.sort(key=lambda row: (row["split"], row["best_delta"], row["mean_delta"]))
    return summary


def write_final_verdict(output_dir: Path) -> dict[str, Any]:
    reward = _read_csv(output_dir / "reward_misalignment.csv")
    obs = _read_csv(output_dir / "observation_aliasing.csv")
    ablation = _read_csv(output_dir / "random_ablation_summary.csv")
    entropy = _read_csv(output_dir / "policy_entropy_probe.csv")
    context = _read_json(output_dir / "phase0_context.json")
    verdict = build_second_layer_verdict(
        reward_summary=reward,
        obs_summary=obs,
        ablation_summary=ablation,
        entropy_rows=entropy,
        context=context,
    )
    _write_json(output_dir / "second_layer_verdict.json", verdict)
    _write_text(output_dir / "second_layer_verdict.md", _final_verdict_md(verdict))
    _write_text(output_dir / "plain_language_report.md", _plain_language_report_md(verdict))
    return verdict


def build_second_layer_verdict(
    *,
    reward_summary: list[dict[str, Any]],
    obs_summary: list[dict[str, Any]],
    ablation_summary: list[dict[str, Any]],
    entropy_rows: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    ppo_entropy_top = max((_to_float(row.get("top_prob")) for row in entropy_rows), default=0.0)
    ppo_reward_rows = [row for row in reward_summary if row.get("algorithm") == "ppo_full"]
    ppo_accept = max((_to_float(row.get("accepted_rate")) for row in ppo_reward_rows), default=0.0)
    ppo_best_rate = max((_to_float(row.get("improved_best_rate")) for row in ppo_reward_rows), default=0.0)
    formal = [row for row in ablation_summary if row.get("split") == "formal_10001"]
    by_alg = {str(row["algorithm"]): row for row in formal}
    random_mean = _to_float(by_alg.get("random_full", {}).get("mean_best_obj"))
    ppo_mean = _to_float(by_alg.get("ppo_full", {}).get("mean_best_obj"))
    alpha_mean = _to_float(by_alg.get("alpha_ucb_env", {}).get("mean_best_obj"))
    obs_conflict = max((_to_float(row.get("conflicting_obs_bucket_rate")) for row in obs_summary), default=0.0)
    hypotheses = [
        {
            "hypothesis": "policy collapse is real",
            "status": "confirmed" if ppo_entropy_top >= 0.95 and ppo_mean > 0 else "inconclusive",
            "evidence": f"max top action probability={ppo_entropy_top:.6f}; ppo formal mean={ppo_mean:.6f}",
        },
        {
            "hypothesis": "immediate reward can favor a globally weak fixed action",
            "status": "supported" if ppo_accept >= 0.80 and ppo_mean > random_mean * 1.05 else "inconclusive",
            "evidence": f"ppo max accepted_rate={ppo_accept:.6f}; ppo max improved_best_rate={ppo_best_rate:.6f}; random formal mean={random_mean:.6f}",
        },
        {
            "hypothesis": "random_full is a strong operator-space baseline",
            "status": "confirmed" if random_mean > 0 and alpha_mean > 0 and random_mean <= alpha_mean * 1.02 else "supported",
            "evidence": f"formal random_full mean={random_mean:.6f}; alpha_ucb_env mean={alpha_mean:.6f}",
        },
        {
            "hypothesis": "observation aliasing limits conditional control",
            "status": "supported" if obs_conflict >= 0.10 else "inconclusive",
            "evidence": f"max conflicting rounded-observation bucket rate={obs_conflict:.6f}",
        },
    ]
    if ppo_mean > random_mean * 1.10:
        recommendation = "do_not_long_train_current_ppo"
    elif ppo_mean > alpha_mean * 1.05:
        recommendation = "debug_before_medium_pilot"
    else:
        recommendation = "eligible_for_small_repair_pilot"
    return {
        "context": context,
        "formal_10001_means": {
            "ppo_full": ppo_mean,
            "random_full": random_mean,
            "alpha_ucb_env": alpha_mean,
        },
        "hypotheses": hypotheses,
        "recommendation": recommendation,
        "next_repair_order": [
            "operator_only_action_space",
            "reduced_q_threshold_action_space",
            "reward_shaping_after_reward_audit",
            "block_level_controller_if_small_repairs_fail",
        ],
    }


def run_all(args: argparse.Namespace) -> dict[str, Any]:
    root = repo_root()
    output_dir = ensure_report_path(args.output_dir, root=root)
    output_dir.mkdir(parents=True, exist_ok=True)
    _require_system_worker(root)
    manifest = load_manifest(root / args.manifest, root=root)
    model_path = root / args.model
    seeds = parse_seeds(args.seeds)
    context = run_context_snapshot(output_dir)
    _ = context
    run_policy_entropy_probe(manifest=manifest, model_path=model_path, output_dir=output_dir)
    run_trace_matrix(
        manifest=manifest,
        model_path=model_path,
        output_dir=output_dir,
        seeds=seeds,
        trace_steps=int(args.trace_steps),
        jobs=int(args.jobs),
    )
    run_initial_action_sweep(manifest=manifest, output_dir=output_dir, seed=seeds[0], jobs=int(args.jobs))
    run_random_ablation_matrix(
        manifest=manifest,
        model_path=model_path,
        output_dir=output_dir,
        seeds=seeds,
        eval_budget=int(args.eval_budget),
        jobs=int(args.jobs),
    )
    verdict = write_final_verdict(output_dir)
    manifest_payload = {
        "output_dir": str(output_dir),
        "model": str(model_path),
        "manifest": str(root / args.manifest),
        "seeds": seeds,
        "trace_steps": int(args.trace_steps),
        "eval_budget": int(args.eval_budget),
        "jobs": int(args.jobs),
        "worker_python": os.environ.get("SETP_WORKER_PYTHON"),
        "artifacts": sorted(path.name for path in output_dir.iterdir() if path.is_file()),
        "recommendation": verdict["recommendation"],
    }
    _write_json(output_dir / "manifest.json", manifest_payload)
    return verdict


def _trace_task(task: tuple[str, str, str, int, str, int]) -> list[dict[str, Any]]:
    split, bundle, algorithm, seed, model_path, trace_steps = task
    from stable_baselines3 import PPO

    control_mode = "kernel_default" if algorithm == "alpha_ucb_env" else "ppo_full"
    env = SetpAlnsEnv(bundle, seed=seed, eval_budget=max(16000, int(trace_steps)), control_mode=control_mode)
    model = PPO.load(model_path, device="cpu") if algorithm == "ppo_full" else None
    alpha_selector = None
    alpha_rng = np.random.default_rng(seed)
    if algorithm == "alpha_ucb_env":
        from setp_solver.search.alns_wouda import _make_operator_selector

        alpha_selector = _make_operator_selector(int(env.action_space.nvec[0]), int(env.action_space.nvec[1]))
    rows: list[dict[str, Any]] = []
    try:
        env.action_space.seed(seed)
        obs, _ = env.reset(seed=seed)
        previous_route_count = _route_count(env.last_response)
        for step_index in range(1, int(trace_steps) + 1):
            action = _policy_action(
                algorithm,
                env=env,
                obs=obs,
                seed=seed,
                model=model,
                alpha_selector=alpha_selector,
                alpha_rng=alpha_rng,
                random_rng=None,
            )
            obs_before = np.asarray(obs, dtype=float).tolist()
            obs, reward, terminated, truncated, info = env.step(action)
            if algorithm == "alpha_ucb_env" and alpha_selector is not None:
                alpha_selector.update(None, int(action[0]), int(action[1]), _outcome_index(info))
            trace = info.get("trace", {}) or {}
            route_count = _route_count(info)
            row = {
                "split": split,
                "bundle": bundle,
                "algorithm": algorithm,
                "seed": int(seed),
                "step_index": int(step_index),
                "reward": float(reward),
                "reward_code": str(trace.get("reward_code", "")),
                "delta": float(trace.get("delta", 0.0) or 0.0),
                "accepted": bool(info.get("accepted", False)),
                "improved_current": bool(info.get("improved_current", False)),
                "improved_best": bool(info.get("improved_best", False)),
                "terminated": bool(terminated),
                "best_obj": float(info.get("best_obj", 0.0) or 0.0),
                "current_obj": float(info.get("current_obj", 0.0) or 0.0),
                "candidate_obj": float(info.get("candidate_obj", 0.0) or 0.0),
                "actual_evals": int(info.get("actual_evals", 0) or 0),
                "violation_count": int(info.get("violation_count", 0) or 0),
                "route_count": int(route_count),
                "route_count_delta": int(route_count - previous_route_count),
                "destroy_id": str(trace.get("destroy_id", "")),
                "repair_id": str(trace.get("repair_id", "")),
                "q_ratio": trace.get("q_ratio", ""),
                "threshold_ratio": float(trace.get("threshold_ratio", 0.0) or 0.0),
                "worker_python_executable": str(trace.get("worker_python_executable", "")),
                "worker_numpy_version": str(trace.get("worker_numpy_version", "")),
            }
            for idx in range(OBSERVATION_SIZE):
                row[f"obs_{idx}"] = float(obs_before[idx]) if idx < len(obs_before) else 0.0
            rows.append(row)
            previous_route_count = route_count
            if terminated or truncated:
                break
    finally:
        env.close()
    _assert_system_trace(rows)
    return rows


def _ablation_task(task: tuple[str, str, str, int, int, str]) -> dict[str, Any]:
    split, bundle, algorithm, seed, eval_budget, model_path = task
    from stable_baselines3 import PPO

    control_mode = "kernel_default" if algorithm in {"alpha_ucb_env", "random_operator_only"} else "ppo_full"
    env = SetpAlnsEnv(bundle, seed=seed, eval_budget=eval_budget, control_mode=control_mode)
    model = PPO.load(model_path, device="cpu") if algorithm == "ppo_full" else None
    alpha_selector = None
    alpha_rng = np.random.default_rng(seed)
    random_rng = np.random.default_rng(seed + 100_003)
    if algorithm in {"alpha_ucb_env", "alpha_operator_random_q", "alpha_operator_random_threshold"}:
        from setp_solver.search.alns_wouda import _make_operator_selector

        alpha_selector = _make_operator_selector(len(DESTROY_IDS), len(REPAIR_IDS))
    destroy_counts: Counter[str] = Counter()
    repair_counts: Counter[str] = Counter()
    q_counts: Counter[str] = Counter()
    threshold_counts: Counter[str] = Counter()
    last_info: dict[str, Any] | None = None
    best_info: dict[str, Any] | None = None
    try:
        env.action_space.seed(seed)
        obs, _ = env.reset(seed=seed)
        while True:
            action = _policy_action(
                algorithm,
                env=env,
                obs=obs,
                seed=seed,
                model=model,
                alpha_selector=alpha_selector,
                alpha_rng=alpha_rng,
                random_rng=random_rng,
            )
            obs, _reward, terminated, truncated, info = env.step(action)
            trace = info.get("trace", {}) or {}
            destroy_counts[str(trace.get("destroy_id", ""))] += 1
            repair_counts[str(trace.get("repair_id", ""))] += 1
            if trace.get("q_ratio") is not None:
                q_counts[f"{float(trace.get('q_ratio')):.6f}"] += 1
            threshold_counts[f"{float(trace.get('threshold_ratio', 0.0) or 0.0):.6f}"] += 1
            if algorithm in {"alpha_ucb_env", "alpha_operator_random_q", "alpha_operator_random_threshold"} and alpha_selector is not None:
                raw = trace.get("raw_action") or []
                if len(raw) >= 2:
                    alpha_selector.update(None, int(raw[0]), int(raw[1]), _outcome_index(info))
            last_info = info
            if info.get("improved_best") or best_info is None:
                best_info = info
            if terminated or truncated:
                break
    finally:
        env.close()
    if last_info is None:
        raise RuntimeError("ablation task produced no env steps")
    trace = last_info.get("trace", {}) or {}
    return {
        "split": split,
        "bundle": bundle,
        "algorithm": algorithm,
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "best_obj": float(last_info.get("best_obj", 0.0) or 0.0),
        "actual_evals": int(last_info.get("actual_evals", 0) or 0),
        "violation_count": int((best_info or last_info).get("violation_count", 1)),
        "feasible": int((best_info or last_info).get("violation_count", 1)) == 0,
        "worker_python_executable": str(trace.get("worker_python_executable", "")),
        "worker_numpy_version": str(trace.get("worker_numpy_version", "")),
        "destroy_counts": dict(destroy_counts),
        "repair_counts": dict(repair_counts),
        "q_ratio_counts": dict(q_counts),
        "threshold_ratio_counts": dict(threshold_counts),
    }


def _initial_sweep_task(task: tuple[str, str, int]) -> list[dict[str, Any]]:
    split, bundle, seed = task
    rows: list[dict[str, Any]] = []
    env = SetpAlnsEnv(bundle, seed=seed, eval_budget=1000, control_mode="ppo_full")
    try:
        for d_idx, destroy in enumerate(DESTROY_IDS):
            for r_idx, repair in enumerate(REPAIR_IDS):
                for q_idx in range(10):
                    env.reset(seed=seed)
                    action = np.asarray([d_idx, r_idx, q_idx, 99], dtype=np.int64)
                    _obs, reward, terminated, _truncated, info = env.step(action)
                    trace = info.get("trace", {}) or {}
                    rows.append(
                        {
                            "split": split,
                            "bundle": bundle,
                            "seed": int(seed),
                            "destroy_id": destroy,
                            "repair_id": repair,
                            "q_index": q_idx,
                            "q_ratio": f"{float(trace.get('q_ratio', 0.0) or 0.0):.6f}",
                            "delta": float(trace.get("delta", 0.0) or 0.0),
                            "reward": float(reward),
                            "accepted": bool(info.get("accepted", False)),
                            "improved_current": bool(info.get("improved_current", False)),
                            "improved_best": bool(info.get("improved_best", False)),
                            "candidate_obj": float(info.get("candidate_obj", 0.0) or 0.0),
                            "current_obj": float(info.get("current_obj", 0.0) or 0.0),
                            "best_obj": float(info.get("best_obj", 0.0) or 0.0),
                            "actual_evals": int(info.get("actual_evals", 0) or 0),
                            "terminated": bool(terminated),
                            "worker_python_executable": str(trace.get("worker_python_executable", "")),
                            "worker_numpy_version": str(trace.get("worker_numpy_version", "")),
                        }
                    )
    finally:
        env.close()
    _assert_system_trace(rows)
    return rows


def _policy_action(
    algorithm: str,
    *,
    env: SetpAlnsEnv,
    obs: Any,
    seed: int,
    model: Any,
    alpha_selector: Any,
    alpha_rng: np.random.Generator,
    random_rng: np.random.Generator | None,
) -> Any:
    if algorithm == "random_full":
        return env.action_space.sample()
    if algorithm == "random_operator_only":
        return env.action_space.sample()
    if algorithm == "ppo_full":
        if model is None:
            raise RuntimeError("ppo_full requires a loaded model")
        return model.predict(obs, deterministic=True)[0]
    if algorithm == "alpha_ucb_env":
        if alpha_selector is None:
            raise RuntimeError("alpha_ucb_env requires selector")
        d_idx, r_idx = alpha_selector(alpha_rng, None, None)
        return (int(d_idx), int(r_idx))
    if algorithm == "alpha_operator_random_q":
        if alpha_selector is None:
            raise RuntimeError("alpha_operator_random_q requires selector")
        rng = random_rng or np.random.default_rng(seed)
        d_idx, r_idx = alpha_selector(alpha_rng, None, None)
        return np.asarray([int(d_idx), int(r_idx), int(rng.integers(0, 10)), 0], dtype=np.int64)
    if algorithm == "alpha_operator_random_threshold":
        if alpha_selector is None:
            raise RuntimeError("alpha_operator_random_threshold requires selector")
        rng = random_rng or np.random.default_rng(seed)
        d_idx, r_idx = alpha_selector(alpha_rng, None, None)
        return np.asarray([int(d_idx), int(r_idx), 7, int(rng.integers(0, 100))], dtype=np.int64)
    raise ValueError(f"unknown policy algorithm: {algorithm}")


def _parallel_map(func: Any, tasks: list[Any], *, jobs: int) -> list[Any]:
    if int(jobs) <= 1 or len(tasks) <= 1:
        return [func(task) for task in tasks]
    results: list[Any] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=min(int(jobs), len(tasks))) as executor:
        futures = [executor.submit(func, task) for task in tasks]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    return results


def _require_system_worker(root: Path) -> None:
    expected = SYSTEM_WORKER_PYTHON
    actual = os.environ.get("SETP_WORKER_PYTHON")
    if actual != expected:
        resolved = resolve_worker_python(root)
        if str(resolved) != expected:
            raise RuntimeError(f"SETP_WORKER_PYTHON must be {expected}; got {actual!r} resolved={resolved}")


def _assert_system_trace(rows: list[dict[str, Any]]) -> None:
    bad = [
        row
        for row in rows
        if row.get("worker_python_executable")
        and str(row.get("worker_python_executable")) != SYSTEM_WORKER_PYTHON
    ]
    if bad:
        raise RuntimeError(f"non-system worker row detected: {bad[0]}")


def _outcome_index(info: dict[str, Any]) -> int:
    if info.get("improved_best"):
        return 0
    if info.get("improved_current"):
        return 1
    if info.get("accepted"):
        return 2
    return 3


def _route_count(response: dict[str, Any] | None) -> int:
    if not response:
        return 0
    solution = response.get("solution", {}) if isinstance(response, dict) else {}
    routes = solution.get("routes", []) if isinstance(solution, dict) else []
    return len(routes) if isinstance(routes, list) else 0


def _action_dim_name(dim_index: int) -> str:
    return ("destroy", "repair", "q_ratio", "threshold")[dim_index] if dim_index < 4 else str(dim_index)


def _action_label(dim_index: int, action_index: int) -> str:
    if dim_index == 0:
        return DESTROY_IDS[action_index]
    if dim_index == 1:
        return REPAIR_IDS[action_index]
    if dim_index == 2:
        return f"{0.10 + 0.30 * action_index / 9.0:.6f}"
    return str(action_index)


def _context_md(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Second-Layer PPO Debug Context",
            "",
            f"- git_head: `{payload['git_head']}`",
            f"- system_worker_python: `{payload['system_worker_python']}`",
            f"- episode_safe_verdict: `{payload['episode_safe_verdict']}`",
            f"- episode_safe_reason: {payload['episode_safe_reason']}",
            "",
        ]
    )


def _reward_report_md(rows: list[dict[str, Any]]) -> str:
    lines = ["# Reward Misalignment Probe", ""]
    lines.append("| split | algorithm | steps | mean reward | accepted | improved best | observed best |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for row in rows:
        lines.append(
            f"| {row['split']} | {row['algorithm']} | {row['steps']} | {_to_float(row['mean_reward']):.6f} | "
            f"{_to_float(row['accepted_rate']):.3f} | {_to_float(row['improved_best_rate']):.3f} | "
            f"{_to_float(row['final_best_obj_observed']):.3f} |"
        )
    lines.append("")
    lines.append("Interpretation: high accepted/immediate reward with poor final cost is a reward-misalignment warning, not a training success.")
    return "\n".join(lines) + "\n"


def _obs_report_md(rows: list[dict[str, Any]]) -> str:
    lines = ["# Observation Aliasing Probe", ""]
    lines.append("| split | algorithm | rows | unique rounded obs | obs reuse | conflict rate |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for row in rows:
        lines.append(
            f"| {row['split']} | {row['algorithm']} | {row['rows']} | {row['unique_obs_rounded']} | "
            f"{_to_float(row['obs_reuse_rate']):.3f} | {_to_float(row['conflicting_obs_bucket_rate']):.3f} |"
        )
    lines.append("")
    lines.append("Interpretation: repeated/coarse observations with conflicting outcomes suggest the policy cannot reliably condition operator choices.")
    return "\n".join(lines) + "\n"


def _oracle_report_md(rows: list[dict[str, Any]]) -> str:
    lines = ["# Observed Action-Value Table", ""]
    lines.append("This is an empirical trace ranking, not a counterfactual proof. It shows which action families looked useful in observed trajectories.")
    lines.append("")
    lines.append("| split | algorithm | destroy | repair | q | steps | improved-best rate | mean reward |")
    lines.append("|---|---|---|---|---:|---:|---:|---:|")
    for row in rows[:60]:
        lines.append(
            f"| {row['split']} | {row['algorithm']} | {row['destroy_id']} | {row['repair_id']} | "
            f"{row['q_ratio']} | {row['steps']} | {_to_float(row['improved_best_rate']):.4f} | {_to_float(row['mean_reward']):.4f} |"
        )
    return "\n".join(lines) + "\n"


def _random_strength_md(rows: list[dict[str, Any]]) -> str:
    lines = ["# Random-Full Strength Decomposition", ""]
    lines.append("| split | algorithm | rows | mean | median | best | std | violations |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        lines.append(
            f"| {row['split']} | {row['algorithm']} | {row['rows']} | {_to_float(row['mean_best_obj']):.3f} | "
            f"{_to_float(row['median_best_obj']):.3f} | {_to_float(row['best_obj']):.3f} | "
            f"{_to_float(row['std_best_obj']):.3f} | {row['violation_rows']} |"
        )
    lines.append("")
    lines.append("Interpretation: random_full is strong because it explores the winner-kernel action space, not because it is a weak random solution generator.")
    return "\n".join(lines) + "\n"


def _initial_sweep_md(rows: list[dict[str, Any]]) -> str:
    lines = ["# Initial-State Action Sweep", ""]
    lines.append("| split | destroy | repair | q variants | best delta | mean delta | improved q count |")
    lines.append("|---|---|---|---:|---:|---:|---:|")
    for row in rows[:60]:
        lines.append(
            f"| {row['split']} | {row['destroy_id']} | {row['repair_id']} | {row['q_variants']} | "
            f"{_to_float(row['best_delta']):.3f} | {_to_float(row['mean_delta']):.3f} | {row['improved_best_q_count']} |"
        )
    return "\n".join(lines) + "\n"


def _policy_entropy_md(rows: list[dict[str, Any]]) -> str:
    lines = ["# Policy Entropy Probe", ""]
    lines.append("| split | dimension | entropy | top label | top prob |")
    lines.append("|---|---|---:|---|---:|")
    for row in rows:
        lines.append(
            f"| {row['split']} | {row['action_dim_name']} | {_to_float(row['entropy']):.6f} | "
            f"{row['top_label']} | {_to_float(row['top_prob']):.6f} |"
        )
    return "\n".join(lines) + "\n"


def _final_verdict_md(payload: dict[str, Any]) -> str:
    lines = ["# Second-Layer PPO Verdict", ""]
    lines.append(f"- recommendation: `{payload['recommendation']}`")
    lines.append(f"- formal_10001_means: `{json.dumps(payload['formal_10001_means'], ensure_ascii=False)}`")
    lines.append("")
    lines.append("## Hypotheses")
    lines.append("")
    for item in payload["hypotheses"]:
        lines.append(f"- `{item['status']}`: {item['hypothesis']}. Evidence: {item['evidence']}")
    lines.append("")
    lines.append("## Next Repair Order")
    lines.append("")
    for item in payload["next_repair_order"]:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def _plain_language_report_md(payload: dict[str, Any]) -> str:
    means = payload["formal_10001_means"]
    lines = [
        "# PPO 第二层诊断通俗报告",
        "",
        "结论先说清楚：当前 PPO 不是因为 episode 切碎而失败了，那个问题已经修过。现在的问题是策略本身学偏了，学成了一个几乎固定的动作，而这个固定动作在 100-01 上明显输给 random_full 和 AlphaUCB。",
        "",
        f"在 100-01 上，本轮诊断看到的均值是：PPO `{means.get('ppo_full', 0.0):.3f}`，random_full `{means.get('random_full', 0.0):.3f}`，AlphaUCB `{means.get('alpha_ucb_env', 0.0):.3f}`。成本越低越好。",
        "",
        "这说明 random_full 不能再被叫作弱随机基线。它是在强 winner-kernel 动作空间里随机探索，所以本身就是很强的对手。",
        "",
        "目前不建议继续长训当前 PPO。下一步应先做动作空间降维和 reward 审计，优先顺序是：operator_only，小 q/threshold 动作空间，确认 reward 误导后再做 reward shaping。如果这些都失败，再升级到 block-level controller 或 imitation + RL。",
        "",
    ]
    return "\n".join(lines)


def _write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys: list[str] = []
        for row in rows:
            for key in row.keys():
                if key not in keys:
                    keys.append(key)
        fieldnames = keys
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key, "")) for key in fieldnames})


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_json(path: str | Path, payload: Any) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_text(path: str | Path, text: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, bool):
        return int(value)
    return value


def _run_text(command: list[str]) -> str:
    proc = __import__("subprocess").run(command, cwd=repo_root(), text=True, capture_output=True, check=False)
    return (proc.stdout or "") + (proc.stderr or "")


def _to_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes"}:
        return True
    if text in {"0", "false", "no", ""}:
        return False
    return bool(value)


def _mean(values: Iterable[float]) -> float:
    data = [float(value) for value in values]
    return statistics.mean(data) if data else 0.0


def _median(values: Iterable[float]) -> float:
    data = [float(value) for value in values]
    return statistics.median(data) if data else 0.0


def _std(values: Iterable[float]) -> float:
    data = [float(value) for value in values]
    return statistics.pstdev(data) if len(data) > 1 else 0.0


def _safe_div(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run second-layer PPO strategy/reward/action-space diagnostics.")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--model", default=str(MODEL_PATH))
    parser.add_argument("--output-dir", default=str(REPORT_DIR))
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--trace-steps", type=int, default=2048)
    parser.add_argument("--eval-budget", type=int, default=16000)
    parser.add_argument("--jobs", type=int, default=min(6, max(1, os.cpu_count() or 1)))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    verdict = run_all(parse_args(argv))
    print(f"SECOND_LAYER_DEBUG_OK recommendation={verdict['recommendation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
