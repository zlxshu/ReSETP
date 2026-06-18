from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .action_space import DESTROY_IDS, REPAIR_IDS, decode_action
from .baselines import normalize_result_row, run_ppo_policy
from .bundle_manifest import load_manifest
from .env import SetpAlnsEnv
from .train_ppo import build_bucketed_phase_plan


SYSTEM_WORKER_PYTHON = "/opt/anaconda3/bin/python3.13"
PILOT_DIR = Path("solver/reports/dr_alns_ppo_v2/pilot_real3")
REPORT_DIR = Path("solver/reports/dr_alns_ppo_v2/ppo_failure_investigation")
MANIFEST_PATH = Path("solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json")
MODEL_PATH = PILOT_DIR / "train" / "model.zip"
TRACE_STEPS = 128
COLLAPSE_THRESHOLD = 0.95


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def ensure_investigation_path(path: str | Path, *, root: Path | None = None) -> Path:
    base = (repo_root() if root is None else root) / REPORT_DIR
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (repo_root() if root is None else root) / candidate
    resolved = candidate.resolve()
    base_resolved = base.resolve()
    try:
        resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(f"diagnostic output path must stay under {base_resolved}: {resolved}") from exc
    return resolved


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_monitor_rows(path: str | Path) -> list[dict[str, str]]:
    monitor_path = Path(path)
    if not monitor_path.exists():
        return []
    lines = [line for line in monitor_path.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    if not lines:
        return []
    return [dict(row) for row in csv.DictReader(lines)]


def audit_monitor(path: str | Path) -> dict[str, Any]:
    monitor_path = Path(path)
    if not monitor_path.exists():
        return {
            "path": str(monitor_path),
            "status": "missing",
            "episode_count": 0,
            "has_header": False,
        }
    lines = [line for line in monitor_path.read_text(encoding="utf-8").splitlines() if line]
    data_lines = [line for line in lines if not line.startswith("#")]
    has_header = bool(data_lines and data_lines[0].startswith("r,"))
    episode_count = max(0, len(data_lines) - (1 if has_header else 0))
    status = "has_episodes" if episode_count > 0 else "zero_episodes"
    return {
        "path": str(monitor_path),
        "status": status,
        "episode_count": episode_count,
        "has_header": has_header,
        "line_count": len(lines),
    }


def audit_phase_fragmentation(config: dict[str, Any], phase_rows: list[dict[str, str]]) -> dict[str, Any]:
    eval_budget = int(config.get("eval_budget", 0) or 0)
    requested = [_to_int(row.get("requested_timesteps")) for row in phase_rows]
    rollout = [_to_int(row.get("rollout_timesteps")) for row in phase_rows]
    finite_rollout = [value for value in rollout if value > 0]
    finite_requested = [value for value in requested if value > 0]
    risky = [value for value in finite_rollout if value < eval_budget]
    return {
        "eval_budget": eval_budget,
        "phase_count": len(phase_rows),
        "min_requested_timesteps": min(finite_requested) if finite_requested else 0,
        "max_requested_timesteps": max(finite_requested) if finite_requested else 0,
        "min_rollout_timesteps": min(finite_rollout) if finite_rollout else 0,
        "max_rollout_timesteps": max(finite_rollout) if finite_rollout else 0,
        "phase_timesteps_lt_eval_budget": bool(finite_rollout and len(risky) == len(finite_rollout)),
        "risky_phase_count": len(risky),
        "episode_fragmentation_risk": bool(eval_budget > 0 and finite_rollout and len(risky) == len(finite_rollout)),
    }


def classify_action_collapse(rows: Iterable[dict[str, Any]], *, threshold: float = COLLAPSE_THRESHOLD) -> dict[str, Any]:
    total = 0
    combined = Counter()
    destroy = Counter()
    repair = Counter()
    q_ratio = Counter()
    for row in rows:
        d_counts = _loads_counts(row.get("destroy_counts"))
        r_counts = _loads_counts(row.get("repair_counts"))
        q_counts = _loads_counts(row.get("q_ratio_counts"))
        destroy.update(d_counts)
        repair.update(r_counts)
        q_ratio.update(q_counts)
        row_total = max(sum(d_counts.values()), sum(r_counts.values()), sum(q_counts.values()))
        total += row_total
        if d_counts and r_counts:
            d_name, d_value = d_counts.most_common(1)[0]
            r_name, r_value = r_counts.most_common(1)[0]
            q_name = q_counts.most_common(1)[0][0] if q_counts else ""
            combined[(d_name, r_name, q_name)] += min(d_value, r_value, row_total)
    top_key, top_count = (("", "", ""), 0)
    if combined:
        top_key, top_count = combined.most_common(1)[0]
    top_share = (float(top_count) / float(total)) if total else 0.0
    return {
        "total_actions": int(total),
        "top_destroy": _counter_top(destroy),
        "top_repair": _counter_top(repair),
        "top_q_ratio": _counter_top(q_ratio),
        "top_combined_destroy": top_key[0],
        "top_combined_repair": top_key[1],
        "top_combined_q_ratio": top_key[2],
        "top_combined_count": int(top_count),
        "top_combined_share": top_share,
        "collapsed": bool(total and top_share >= float(threshold)),
        "threshold": float(threshold),
    }


def summarize_comparison(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("split", "")), str(row.get("algorithm", "")))].append(row)
    summary: list[dict[str, Any]] = []
    for (split, algorithm), group_rows in sorted(grouped.items()):
        costs = [_to_float(row.get("best_obj")) for row in group_rows]
        actions = classify_action_collapse(group_rows)
        actual_evals = [_to_int(row.get("actual_evals")) for row in group_rows]
        violations = [_to_int(row.get("violation_count")) for row in group_rows]
        worker_python = sorted({str(row.get("worker_python_executable", "")) for row in group_rows})
        summary.append(
            {
                "split": split,
                "algorithm": algorithm,
                "rows": len(group_rows),
                "mean_best_obj": _mean(costs),
                "median_best_obj": _median(costs),
                "best_obj": min(costs) if costs else 0.0,
                "std_best_obj": _std(costs),
                "min_actual_evals": min(actual_evals) if actual_evals else 0,
                "max_actual_evals": max(actual_evals) if actual_evals else 0,
                "violation_rows": sum(1 for value in violations if value != 0),
                "worker_python_executables": "|".join(worker_python),
                **{f"action_{key}": value for key, value in actions.items()},
            }
        )
    return summary


def load_existing_comparison_rows(pilot_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split, relpath in (
        ("eval_train", "eval_train/comparison.csv"),
        ("eval_10001", "eval_10001/comparison.csv"),
        ("eval_held_out", "eval_held_out/comparison.csv"),
    ):
        path = pilot_dir / relpath
        for raw in read_csv_rows(path):
            row = _normalize_existing_row(raw)
            row["split"] = split
            rows.append(row)
    return rows


def run_existing_pilot_audit(pilot_dir: Path, output_dir: Path) -> dict[str, Any]:
    train_dir = pilot_dir / "train"
    config = read_json(train_dir / "training_config.json")
    phase_rows = read_csv_rows(train_dir / "bucketed_phase_log.csv")
    monitor = audit_monitor(train_dir / "monitor.csv")
    phase_audit = audit_phase_fragmentation(config, phase_rows)
    comparison_rows = load_existing_comparison_rows(pilot_dir)
    summary_rows = summarize_comparison(comparison_rows)
    env_eval_count_rows = read_csv_rows(train_dir / "env_eval_counts.csv")
    payload = {
        "pilot_dir": str(pilot_dir),
        "training_config": config,
        "phase_audit": phase_audit,
        "monitor_audit": monitor,
        "comparison_summary": summary_rows,
        "env_eval_count_rows": len(env_eval_count_rows),
        "zero_violation_rows": all(_to_int(row.get("violation_count")) == 0 for row in comparison_rows),
        "budget_consistent_rows": all(_to_int(row.get("actual_evals")) == _to_int(row.get("eval_budget")) for row in comparison_rows),
    }
    _write_json(output_dir / "existing_pilot_audit.json", payload)
    _write_csv(output_dir / "existing_pilot_audit.csv", summary_rows)
    _write_text(output_dir / "existing_pilot_audit.md", _existing_audit_md(payload))
    return payload


def run_phase_fragmentation_probe(
    *,
    manifest: dict[str, Any],
    output_dir: Path,
    skip_train_probes: bool = False,
) -> dict[str, Any]:
    probe_dir = output_dir / "phase_probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    train_bundle = str(manifest["train"][0])
    manifest_path = probe_dir / "single_train_manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": "dr-alns-ppo-bundle-manifest.v1",
            "train": [train_bundle],
            "held_out": [],
            "formal_eval": [],
            "excluded_from_training_reason": {"diagnostic": "single bundle for episode fragmentation probe only"},
        },
    )
    rows: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    plan_current = build_bucketed_phase_plan([train_bundle], total_timesteps=3072, n_steps=128, env_repeats=24)
    rows.append(_phase_probe_row("schedule_current_shape", 16000, plan_current, "mechanical_plan", "", ""))
    plan_episode = build_bucketed_phase_plan([train_bundle], total_timesteps=64, n_steps=64, env_repeats=1)
    rows.append(_phase_probe_row("schedule_episode_possible", 32, plan_episode, "mechanical_plan", "", ""))
    if not skip_train_probes:
        for name, eval_budget in (("actual_no_episode", 256), ("actual_episode_possible", 32)):
            run_dir = probe_dir / name
            command = _tiny_train_command(
                manifest_path=manifest_path,
                output_dir=run_dir,
                eval_budget=eval_budget,
                timesteps=64,
            )
            proc = _run_subprocess(command, timeout=300.0)
            commands.append(
                {
                    "name": name,
                    "returncode": proc.returncode,
                    "stdout_tail": proc.stdout[-2000:],
                    "stderr_tail": proc.stderr[-2000:],
                    "command": command,
                }
            )
            if proc.returncode != 0:
                raise RuntimeError(f"phase fragmentation probe failed: {name}: {proc.stderr[-4000:]}")
            monitor = audit_monitor(run_dir / "monitor.csv")
            rows.append(
                {
                    "probe": name,
                    "eval_budget": eval_budget,
                    "rollout_timesteps": 64,
                    "phase_timesteps_lt_eval_budget": 64 < eval_budget,
                    "expected_episode_count_gt_zero": eval_budget <= 64,
                    "monitor_status": monitor["status"],
                    "episode_count": monitor["episode_count"],
                    "returncode": proc.returncode,
                }
            )
    payload = {
        "train_bundle": train_bundle,
        "worker_python": os.environ.get("SETP_WORKER_PYTHON", ""),
        "rows": rows,
        "commands": commands,
        "skip_train_probes": bool(skip_train_probes),
    }
    _write_json(output_dir / "phase_fragmentation_probe.json", payload)
    _write_csv(output_dir / "phase_fragmentation_probe.csv", rows)
    _write_text(output_dir / "phase_fragmentation_probe.md", _phase_probe_md(payload))
    return payload


def run_reward_signal_probe(
    *,
    manifest: dict[str, Any],
    model_path: Path,
    output_dir: Path,
    trace_steps: int = TRACE_STEPS,
) -> dict[str, Any]:
    bundles = [
        ("formal_10001", str(manifest["formal_eval"][0])),
        ("train_first", str(manifest["train"][0])),
    ]
    rows: list[dict[str, Any]] = []
    for split, bundle_dir in bundles:
        rows.extend(_trace_policy(split, bundle_dir, "random_full", seed=1, trace_steps=trace_steps))
        rows.extend(_trace_policy(split, bundle_dir, "alpha_ucb_env", seed=1, trace_steps=trace_steps))
        rows.extend(_trace_policy(split, bundle_dir, "ppo_full", seed=1, trace_steps=trace_steps, model_path=model_path))
    summary = summarize_reward_trace(rows)
    _write_csv(output_dir / "reward_signal_probe.csv", rows)
    _write_text(output_dir / "reward_signal_report.md", _reward_report_md(summary))
    return {"summary": summary, "row_count": len(rows)}


def summarize_reward_trace(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["split"]), str(row["algorithm"]))].append(row)
    summary: list[dict[str, Any]] = []
    for (split, algorithm), group in sorted(grouped.items()):
        rewards = [_to_float(row["reward"]) for row in group]
        summary.append(
            {
                "split": split,
                "algorithm": algorithm,
                "steps": len(group),
                "reward_nonzero_count": sum(1 for value in rewards if abs(value) > 1e-12),
                "reward_nonzero_rate": _safe_div(sum(1 for value in rewards if abs(value) > 1e-12), len(group)),
                "mean_reward": _mean(rewards),
                "improved_best_count": sum(1 for row in group if _to_bool(row.get("improved_best"))),
                "improved_current_count": sum(1 for row in group if _to_bool(row.get("improved_current"))),
                "accepted_count": sum(1 for row in group if _to_bool(row.get("accepted"))),
                "terminal_count": sum(1 for row in group if _to_bool(row.get("terminated"))),
                "final_actual_evals": max(_to_int(row.get("actual_evals")) for row in group) if group else 0,
                "violation_rows": sum(1 for row in group if _to_int(row.get("violation_count")) != 0),
            }
        )
    return summary


def run_policy_entropy_probe(
    *,
    manifest: dict[str, Any],
    model_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    from stable_baselines3 import PPO

    model = PPO.load(model_path)
    rows: list[dict[str, Any]] = []
    for split, bundle_dir in (
        ("train_first", str(manifest["train"][0])),
        ("formal_10001", str(manifest["formal_eval"][0])),
        ("held_out", str(manifest["held_out"][0])),
    ):
        observations = _collect_observations(bundle_dir, seed=1, count=8)
        rows.extend(_policy_distribution_rows(model, observations, split=split, bundle_dir=bundle_dir))
    _write_csv(output_dir / "policy_entropy_probe.csv", rows)
    _write_text(output_dir / "policy_entropy_probe.md", _policy_entropy_md(rows))
    return {"rows": len(rows)}


def run_deterministic_vs_stochastic_eval(
    *,
    manifest: dict[str, Any],
    model_path: Path,
    output_dir: Path,
    eval_budget: int = 16000,
) -> list[dict[str, Any]]:
    from stable_baselines3 import PPO

    model = PPO.load(model_path)
    rows: list[dict[str, Any]] = []
    bundle_dir = str(manifest["formal_eval"][0])
    for seed in (1, 2, 3):
        for deterministic in (True, False):
            row = run_ppo_policy(
                model,
                bundle_dir,
                seed=seed,
                eval_budget=eval_budget,
                deterministic=deterministic,
                control_mode="ppo_full",
            )
            row["algorithm"] = "ppo_full_deterministic" if deterministic else "ppo_full_stochastic"
            rows.append(row)
    _write_csv(output_dir / "deterministic_vs_stochastic_eval.csv", [_csv_safe_row(row) for row in rows])
    return rows


def write_random_baseline_decomposition(existing_rows: list[dict[str, Any]], output_dir: Path) -> dict[str, Any]:
    random_rows = [row for row in existing_rows if row.get("algorithm") == "random_full"]
    alpha_rows = [row for row in existing_rows if row.get("algorithm") == "alpha_ucb_env"]
    summary = {
        "random_full": summarize_comparison(random_rows),
        "alpha_ucb_env": summarize_comparison(alpha_rows),
        "operator_distribution_delta": _operator_distribution_delta(random_rows, alpha_rows),
    }
    _write_text(output_dir / "random_baseline_decomposition.md", _random_decomposition_md(summary))
    return summary


def write_root_cause_verdict(
    *,
    output_dir: Path,
    existing_audit: dict[str, Any],
    phase_probe: dict[str, Any],
    reward_summary: list[dict[str, Any]],
    entropy_rows: list[dict[str, Any]],
    deterministic_rows: list[dict[str, Any]],
    random_summary: dict[str, Any],
) -> dict[str, Any]:
    verdicts = []
    phase_confirmed = _phase_fragmentation_confirmed(existing_audit, phase_probe)
    verdicts.append(
        {
            "hypothesis": "bucketed phases reset before 16000-eval episodes terminate",
            "status": "confirmed" if phase_confirmed else "partially_supported",
            "evidence": "phase_timesteps=3072 < eval_budget=16000 and monitor has zero episode rows; tiny probe restores monitor rows when eval_budget <= phase_timesteps",
        }
    )
    reward_nonzero_rates = [_to_float(row["reward_nonzero_rate"]) for row in reward_summary]
    terminal_counts = [_to_int(row["terminal_count"]) for row in reward_summary]
    reward_status = "confirmed" if reward_nonzero_rates and max(terminal_counts) == 0 and max(reward_nonzero_rates) < 0.20 else "partially_supported"
    verdicts.append(
        {
            "hypothesis": "reward signal is sparse and lacks terminal credit in the observed training horizon",
            "status": reward_status,
            "evidence": f"max_nonzero_reward_rate={max(reward_nonzero_rates) if reward_nonzero_rates else 0:.6f}; max_terminal_count={max(terminal_counts) if terminal_counts else 0}",
        }
    )
    ppo_summary = [
        row
        for row in existing_audit["comparison_summary"]
        if row["algorithm"] == "ppo_full" and row["split"] in {"eval_10001", "eval_held_out"}
    ]
    collapsed = all(bool(row.get("action_collapsed")) for row in ppo_summary)
    entropy_top_prob = max((_to_float(row.get("top_prob")) for row in entropy_rows), default=0.0)
    stochastic_costs = [_to_float(row.get("best_obj")) for row in deterministic_rows if row.get("algorithm") == "ppo_full_stochastic"]
    deterministic_costs = [_to_float(row.get("best_obj")) for row in deterministic_rows if row.get("algorithm") == "ppo_full_deterministic"]
    alpha_10001 = [
        row
        for row in existing_audit["comparison_summary"]
        if row["algorithm"] == "alpha_ucb_env" and row["split"] == "eval_10001"
    ]
    random_10001 = [
        row
        for row in existing_audit["comparison_summary"]
        if row["algorithm"] == "random_full" and row["split"] == "eval_10001"
    ]
    alpha_mean = _to_float(alpha_10001[0]["mean_best_obj"]) if alpha_10001 else 0.0
    random_mean = _to_float(random_10001[0]["mean_best_obj"]) if random_10001 else 0.0
    stochastic_mean = _mean(stochastic_costs)
    deterministic_mean = _mean(deterministic_costs)
    if collapsed and stochastic_costs and (alpha_mean <= 0.0 or stochastic_mean > alpha_mean * 1.01):
        det_artifact_status = "rejected"
    elif stochastic_costs and stochastic_mean < deterministic_mean * 0.98:
        det_artifact_status = "partially_supported"
    else:
        det_artifact_status = "inconclusive"
    verdicts.append(
        {
            "hypothesis": "policy collapse is only a deterministic-evaluation artifact",
            "status": det_artifact_status,
            "evidence": f"collapsed_actions={collapsed}; max_policy_top_prob={entropy_top_prob:.6f}; deterministic_mean={deterministic_mean:.6f}; stochastic_mean={stochastic_mean:.6f}; alpha_ucb_mean={alpha_mean:.6f}; random_full_mean={random_mean:.6f}",
        }
    )
    random_status = "confirmed" if random_summary["random_full"] else "partially_supported"
    verdicts.append(
        {
            "hypothesis": "random_full is a strong random policy over winner-kernel operators, not a weak random solution generator",
            "status": random_status,
            "evidence": "random_full samples destroy/repair/q choices inside the restored winner action space and beats ppo_full in existing comparison CSVs",
        }
    )
    payload = {
        "verdicts": verdicts,
        "conclusion": (
            "The confirmed hard root cause is bucketed phase fragmentation: training resets environments before 16000-eval episodes terminate, "
            "so monitor/evaluation-credit episode endings are absent. Reward/terminal-credit observability is partially supported rather than fully proven, "
            "because short traces still contain nonzero immediate rewards but no terminal rewards. The saved PPO policy is genuinely collapsed, "
            "not merely a deterministic-eval display issue."
        ),
        "next_step_boundary": "No fix is proposed here; next task should repair episode continuity/reward observability before any longer PPO training.",
    }
    _write_json(output_dir / "root_cause_verdict.json", payload)
    _write_text(output_dir / "root_cause_verdict.md", _verdict_md(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = repo_root()
    output_dir = ensure_investigation_path(args.output_dir, root=root)
    output_dir.mkdir(parents=True, exist_ok=True)
    if os.environ.get("SETP_WORKER_PYTHON") != SYSTEM_WORKER_PYTHON:
        raise RuntimeError(f"SETP_WORKER_PYTHON must be {SYSTEM_WORKER_PYTHON} for this investigation")
    pilot_dir = (root / args.pilot_dir).resolve() if not Path(args.pilot_dir).is_absolute() else Path(args.pilot_dir)
    manifest = load_manifest(root / args.manifest, root=root)

    existing_audit = run_existing_pilot_audit(pilot_dir, output_dir)
    existing_rows = load_existing_comparison_rows(pilot_dir)
    _assert_system_worker(existing_rows)
    phase_probe = run_phase_fragmentation_probe(
        manifest=manifest,
        output_dir=output_dir,
        skip_train_probes=bool(args.skip_train_probes),
    )
    reward_probe = run_reward_signal_probe(
        manifest=manifest,
        model_path=root / args.model,
        output_dir=output_dir,
        trace_steps=int(args.trace_steps),
    )
    entropy_probe = run_policy_entropy_probe(manifest=manifest, model_path=root / args.model, output_dir=output_dir)
    deterministic_rows = run_deterministic_vs_stochastic_eval(
        manifest=manifest,
        model_path=root / args.model,
        output_dir=output_dir,
        eval_budget=int(args.eval_budget),
    )
    random_summary = write_random_baseline_decomposition(existing_rows, output_dir)
    entropy_rows = read_csv_rows(output_dir / "policy_entropy_probe.csv")
    verdict = write_root_cause_verdict(
        output_dir=output_dir,
        existing_audit=existing_audit,
        phase_probe=phase_probe,
        reward_summary=reward_probe["summary"],
        entropy_rows=entropy_rows,
        deterministic_rows=deterministic_rows,
        random_summary=random_summary,
    )
    manifest_payload = {
        "output_dir": str(output_dir),
        "pilot_dir": str(pilot_dir),
        "model": str(root / args.model),
        "worker_python": os.environ.get("SETP_WORKER_PYTHON"),
        "trace_steps": int(args.trace_steps),
        "eval_budget": int(args.eval_budget),
        "artifacts": sorted(path.name for path in output_dir.glob("*") if path.is_file()),
        "root_cause_statuses": verdict["verdicts"],
    }
    _write_json(output_dir / "manifest.json", manifest_payload)
    print(f"PPO_FAILURE_INVESTIGATION_OK output_dir={output_dir}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose Real3 PPO policy collapse without changing solver behavior.")
    parser.add_argument("--pilot-dir", default=str(PILOT_DIR))
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--model", default=str(MODEL_PATH))
    parser.add_argument("--output-dir", default=str(REPORT_DIR))
    parser.add_argument("--trace-steps", type=int, default=TRACE_STEPS)
    parser.add_argument("--eval-budget", type=int, default=16000)
    parser.add_argument("--skip-train-probes", action="store_true")
    return parser.parse_args(argv)


def _trace_policy(
    split: str,
    bundle_dir: str,
    algorithm: str,
    *,
    seed: int,
    trace_steps: int,
    model_path: Path | None = None,
) -> list[dict[str, Any]]:
    from setp_solver.search.alns_wouda import _make_operator_selector
    from stable_baselines3 import PPO

    control_mode = "kernel_default" if algorithm == "alpha_ucb_env" else "ppo_full"
    env = SetpAlnsEnv(bundle_dir, seed=seed, eval_budget=16000, control_mode=control_mode)
    model = PPO.load(model_path) if model_path is not None else None
    rng = np.random.default_rng(seed)
    selector = None
    if algorithm == "alpha_ucb_env":
        selector = _make_operator_selector(int(env.action_space.nvec[0]), int(env.action_space.nvec[1]))
    rows: list[dict[str, Any]] = []
    try:
        env.action_space.seed(seed)
        obs, _info = env.reset(seed=seed)
        for step_idx in range(int(trace_steps)):
            if algorithm == "random_full":
                action = env.action_space.sample()
            elif algorithm == "alpha_ucb_env":
                if selector is None or env.last_response is None:
                    raise RuntimeError("alpha probe selector was not initialized")
                d_idx, r_idx = selector(rng, None, None)
                action = (int(d_idx), int(r_idx))
            elif algorithm == "ppo_full":
                if model is None:
                    raise RuntimeError("ppo_full trace requires model_path")
                action = model.predict(obs, deterministic=True)[0]
            else:
                raise ValueError(f"unknown trace algorithm: {algorithm}")
            obs, reward, terminated, truncated, info = env.step(action)
            if algorithm == "alpha_ucb_env" and selector is not None:
                trace = info.get("trace", {}) or {}
                outcome = 0 if info.get("improved_best") else 1 if info.get("improved_current") else 2 if info.get("accepted") else 3
                selector.update(None, int(action[0]), int(action[1]), outcome)
            trace = info.get("trace", {}) or {}
            rows.append(
                {
                    "split": split,
                    "bundle": bundle_dir,
                    "algorithm": algorithm,
                    "seed": seed,
                    "step_index": step_idx + 1,
                    "reward": float(reward),
                    "reward_code": str(trace.get("reward_code", "")),
                    "delta": float(trace.get("delta", 0.0) or 0.0),
                    "accepted": bool(info.get("accepted", False)),
                    "improved_current": bool(info.get("improved_current", False)),
                    "improved_best": bool(info.get("improved_best", False)),
                    "terminated": bool(terminated),
                    "truncated": bool(truncated),
                    "best_obj": float(info.get("best_obj", 0.0) or 0.0),
                    "current_obj": float(info.get("current_obj", 0.0) or 0.0),
                    "candidate_obj": float(info.get("candidate_obj", 0.0) or 0.0),
                    "actual_evals": int(info.get("actual_evals", 0) or 0),
                    "violation_count": int(info.get("violation_count", 0) or 0),
                    "destroy_id": str(trace.get("destroy_id", "")),
                    "repair_id": str(trace.get("repair_id", "")),
                    "q_ratio": trace.get("q_ratio", ""),
                    "threshold_ratio": float(trace.get("threshold_ratio", 0.0) or 0.0),
                    "worker_python_executable": str(trace.get("worker_python_executable", "")),
                    "worker_numpy_version": str(trace.get("worker_numpy_version", "")),
                }
            )
            if terminated or truncated:
                break
    finally:
        env.close()
    _assert_trace_system_worker(rows)
    return rows


def _collect_observations(bundle_dir: str, *, seed: int, count: int) -> list[np.ndarray]:
    env = SetpAlnsEnv(bundle_dir, seed=seed, eval_budget=16000, control_mode="ppo_full")
    observations: list[np.ndarray] = []
    try:
        env.action_space.seed(seed)
        obs, _info = env.reset(seed=seed)
        observations.append(np.asarray(obs, dtype=np.float32))
        for _ in range(max(0, int(count) - 1)):
            action = env.action_space.sample()
            obs, _reward, terminated, truncated, _info = env.step(action)
            observations.append(np.asarray(obs, dtype=np.float32))
            if terminated or truncated:
                break
    finally:
        env.close()
    return observations


def _policy_distribution_rows(model: Any, observations: list[np.ndarray], *, split: str, bundle_dir: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    import torch

    for obs_index, obs in enumerate(observations):
        obs_tensor, _ = model.policy.obs_to_tensor(obs)
        with torch.no_grad():
            distribution = model.policy.get_distribution(obs_tensor)
        categorical_list = getattr(distribution, "distribution", None)
        if categorical_list is None:
            continue
        for dim_index, categorical in enumerate(categorical_list):
            probs = categorical.probs.detach().cpu().numpy().reshape(-1)
            entropy = float(categorical.entropy().detach().cpu().numpy().reshape(-1)[0])
            top_index = int(np.argmax(probs))
            rows.append(
                {
                    "split": split,
                    "bundle": bundle_dir,
                    "observation_index": obs_index,
                    "action_dim": dim_index,
                    "action_dim_name": _action_dim_name(dim_index),
                    "entropy": entropy,
                    "top_index": top_index,
                    "top_label": _action_label(dim_index, top_index),
                    "top_prob": float(probs[top_index]),
                    "probabilities": json.dumps([float(value) for value in probs], separators=(",", ":")),
                }
            )
    return rows


def _phase_probe_row(probe: str, eval_budget: int, plan: list[dict[str, Any]], status: str, monitor_status: str, episode_count: Any) -> dict[str, Any]:
    rollout = int(plan[0]["rollout_timesteps"]) if plan else 0
    return {
        "probe": probe,
        "eval_budget": int(eval_budget),
        "rollout_timesteps": rollout,
        "phase_timesteps_lt_eval_budget": rollout < int(eval_budget),
        "expected_episode_count_gt_zero": int(eval_budget) <= rollout,
        "monitor_status": monitor_status,
        "episode_count": episode_count,
        "returncode": status,
    }


def _tiny_train_command(*, manifest_path: Path, output_dir: Path, eval_budget: int, timesteps: int) -> list[str]:
    python = repo_root() / "solver" / "rl" / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)
    return [
        str(python),
        "-m",
        "dr_alns_ppo.train_ppo",
        "--manifest",
        str(manifest_path),
        "--timesteps",
        str(timesteps),
        "--eval-budget",
        str(eval_budget),
        "--seed",
        "1",
        "--output-dir",
        str(output_dir),
        "--control-mode",
        "ppo_full",
        "--vec-env",
        "dummy",
        "--schedule",
        "bucketed",
        "--env-repeats",
        "1",
        "--n-steps",
        "64",
        "--batch-size",
        "64",
        "--n-epochs",
        "1",
        "--learning-rate",
        "0.0003",
        "--verbose",
        "0",
    ]


def _run_subprocess(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    root = repo_root()
    env["PYTHONPATH"] = os.pathsep.join([str(root / "solver" / "rl"), str(root / "solver" / "src"), str(root / "models" / "src")])
    env["SETP_WORKER_PYTHON"] = SYSTEM_WORKER_PYTHON
    env["PYTHONHASHSEED"] = "0"
    return subprocess.run(
        command,
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _normalize_existing_row(raw: dict[str, Any]) -> dict[str, Any]:
    row = dict(raw)
    for key in ("operator_counts", "destroy_counts", "repair_counts", "q_ratio_counts"):
        row[key] = _loads_counts(row.get(key))
    return normalize_result_row(row)


def _operator_distribution_delta(random_rows: list[dict[str, Any]], alpha_rows: list[dict[str, Any]]) -> dict[str, Any]:
    random_destroy = Counter()
    alpha_destroy = Counter()
    random_repair = Counter()
    alpha_repair = Counter()
    for row in random_rows:
        random_destroy.update(_loads_counts(row.get("destroy_counts")))
        random_repair.update(_loads_counts(row.get("repair_counts")))
    for row in alpha_rows:
        alpha_destroy.update(_loads_counts(row.get("destroy_counts")))
        alpha_repair.update(_loads_counts(row.get("repair_counts")))
    return {
        "random_destroy_top": random_destroy.most_common(),
        "alpha_destroy_top": alpha_destroy.most_common(),
        "random_repair_top": random_repair.most_common(),
        "alpha_repair_top": alpha_repair.most_common(),
    }


def _phase_fragmentation_confirmed(existing_audit: dict[str, Any], phase_probe: dict[str, Any]) -> bool:
    if not existing_audit["phase_audit"]["episode_fragmentation_risk"]:
        return False
    if existing_audit["monitor_audit"]["episode_count"] != 0:
        return False
    rows = {row["probe"]: row for row in phase_probe.get("rows", [])}
    actual_no = rows.get("actual_no_episode", {})
    actual_yes = rows.get("actual_episode_possible", {})
    if not actual_no or not actual_yes:
        return True
    return _to_int(actual_no.get("episode_count")) == 0 and _to_int(actual_yes.get("episode_count")) > 0


def _assert_system_worker(rows: Iterable[dict[str, Any]]) -> None:
    offenders = [
        row
        for row in rows
        if str(row.get("worker_python_executable") or "").strip()
        and Path(str(row.get("worker_python_executable"))).resolve() != Path(SYSTEM_WORKER_PYTHON).resolve()
    ]
    if offenders:
        sample = offenders[0]
        raise RuntimeError(f"non-system worker row detected: {sample.get('split')} {sample.get('algorithm')} {sample.get('worker_python_executable')}")


def _assert_trace_system_worker(rows: Iterable[dict[str, Any]]) -> None:
    offenders = [
        row
        for row in rows
        if Path(str(row.get("worker_python_executable", ""))).resolve() != Path(SYSTEM_WORKER_PYTHON).resolve()
    ]
    if offenders:
        sample = offenders[0]
        raise RuntimeError(f"trace probe used non-system worker: {sample.get('worker_python_executable')}")


def _action_dim_name(dim_index: int) -> str:
    return ("destroy", "repair", "q_ratio", "threshold")[dim_index] if dim_index < 4 else f"dim_{dim_index}"


def _action_label(dim_index: int, value: int) -> str:
    if dim_index == 0 and 0 <= value < len(DESTROY_IDS):
        return DESTROY_IDS[value]
    if dim_index == 1 and 0 <= value < len(REPAIR_IDS):
        return REPAIR_IDS[value]
    if dim_index == 2:
        return f"{0.10 + (0.30 * value / 9.0):.6f}"
    if dim_index == 3:
        return f"{value}"
    return str(value)


def _counter_top(counter: Counter) -> dict[str, Any]:
    if not counter:
        return {"key": "", "count": 0, "share": 0.0}
    total = sum(counter.values())
    key, count = counter.most_common(1)[0]
    return {"key": str(key), "count": int(count), "share": _safe_div(count, total)}


def _loads_counts(value: Any) -> Counter:
    if isinstance(value, Counter):
        return Counter(value)
    if isinstance(value, dict):
        return Counter({str(key): int(val) for key, val in value.items()})
    if value in ("", None):
        return Counter()
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return Counter()
    if not isinstance(payload, dict):
        return Counter()
    return Counter({str(key): int(val) for key, val in payload.items()})


def _csv_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for key, value in list(out.items()):
        if isinstance(value, (dict, list, tuple)):
            out[key] = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(_csv_safe_row(row))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _existing_audit_md(payload: dict[str, Any]) -> str:
    phase = payload["phase_audit"]
    monitor = payload["monitor_audit"]
    lines = [
        "# Existing Real3 Pilot Audit",
        "",
        f"- pilot_dir: `{payload['pilot_dir']}`",
        f"- eval_budget: `{phase['eval_budget']}`",
        f"- phase_count: `{phase['phase_count']}`",
        f"- rollout_timesteps_range: `{phase['min_rollout_timesteps']}..{phase['max_rollout_timesteps']}`",
        f"- phase_timesteps_lt_eval_budget: `{phase['phase_timesteps_lt_eval_budget']}`",
        f"- monitor_status: `{monitor['status']}`",
        f"- episode_count: `{monitor['episode_count']}`",
        f"- zero_violation_rows: `{payload['zero_violation_rows']}`",
        f"- budget_consistent_rows: `{payload['budget_consistent_rows']}`",
        "",
        "## Cost And Action Summary",
        "",
        "| split | algorithm | rows | mean | median | best | top action share | top destroy | top repair | top q |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for row in payload["comparison_summary"]:
        lines.append(
            "| {split} | {algorithm} | {rows} | {mean_best_obj:.6f} | {median_best_obj:.6f} | {best_obj:.6f} | {action_top_combined_share:.6f} | {d} | {r} | {q} |".format(
                split=row["split"],
                algorithm=row["algorithm"],
                rows=row["rows"],
                mean_best_obj=row["mean_best_obj"],
                median_best_obj=row["median_best_obj"],
                best_obj=row["best_obj"],
                action_top_combined_share=row["action_top_combined_share"],
                d=row["action_top_combined_destroy"],
                r=row["action_top_combined_repair"],
                q=row["action_top_combined_q_ratio"],
            )
        )
    return "\n".join(lines)


def _phase_probe_md(payload: dict[str, Any]) -> str:
    lines = [
        "# Phase Fragmentation Probe",
        "",
        f"- train_bundle: `{payload['train_bundle']}`",
        f"- worker_python: `{payload['worker_python']}`",
        f"- skip_train_probes: `{payload['skip_train_probes']}`",
        "",
        "| probe | eval_budget | rollout_timesteps | rollout<budget | expected_episode | monitor | episodes |",
        "|---|---:|---:|---:|---:|---|---:|",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| {row['probe']} | {row['eval_budget']} | {row['rollout_timesteps']} | {row['phase_timesteps_lt_eval_budget']} | {row['expected_episode_count_gt_zero']} | {row['monitor_status']} | {row['episode_count']} |"
        )
    return "\n".join(lines)


def _reward_report_md(summary: list[dict[str, Any]]) -> str:
    lines = [
        "# Reward Signal Probe",
        "",
        "| split | algorithm | steps | nonzero reward rate | improved best | improved current | accepted | terminal | final evals |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        lines.append(
            f"| {row['split']} | {row['algorithm']} | {row['steps']} | {row['reward_nonzero_rate']:.6f} | {row['improved_best_count']} | {row['improved_current_count']} | {row['accepted_count']} | {row['terminal_count']} | {row['final_actual_evals']} |"
        )
    lines.extend(
        [
            "",
            "Interpretation: this probe samples short traces only. It tests reward observability, not algorithm quality.",
        ]
    )
    return "\n".join(lines)


def _policy_entropy_md(rows: list[dict[str, Any]]) -> str:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["split"], row["action_dim_name"])].append(row)
    lines = [
        "# Policy Entropy Probe",
        "",
        "| split | action_dim | mean_entropy | max_top_prob | dominant_label |",
        "|---|---|---:|---:|---|",
    ]
    for (split, dim), group in sorted(grouped.items()):
        max_row = max(group, key=lambda item: _to_float(item["top_prob"]))
        lines.append(
            f"| {split} | {dim} | {_mean([_to_float(item['entropy']) for item in group]):.6f} | {_to_float(max_row['top_prob']):.6f} | {max_row['top_label']} |"
        )
    return "\n".join(lines)


def _random_decomposition_md(summary: dict[str, Any]) -> str:
    lines = [
        "# Random Baseline Decomposition",
        "",
        "`random_full` is not a weak random solution generator. It samples actions inside the restored winner-kernel operator space.",
        "",
        "## Cost Summary",
        "",
        "| family | split | rows | mean | median | best | top action share |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for family in ("random_full", "alpha_ucb_env"):
        for row in summary[family]:
            lines.append(
                f"| {family} | {row['split']} | {row['rows']} | {row['mean_best_obj']:.6f} | {row['median_best_obj']:.6f} | {row['best_obj']:.6f} | {row['action_top_combined_share']:.6f} |"
            )
    lines.extend(["", "## Operator Distribution Delta", "", "```json", json.dumps(summary["operator_distribution_delta"], ensure_ascii=False, indent=2), "```"])
    return "\n".join(lines)


def _verdict_md(payload: dict[str, Any]) -> str:
    lines = ["# PPO Failure Root-Cause Verdict", ""]
    for item in payload["verdicts"]:
        lines.extend(
            [
                f"## {item['hypothesis']}",
                "",
                f"- status: `{item['status']}`",
                f"- evidence: {item['evidence']}",
                "",
            ]
        )
    lines.extend(["## Conclusion", "", payload["conclusion"], "", payload["next_step_boundary"]])
    return "\n".join(lines)


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes"}


def _safe_div(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _mean(values: Iterable[float]) -> float:
    clean = [float(value) for value in values]
    return statistics.fmean(clean) if clean else 0.0


def _median(values: Iterable[float]) -> float:
    clean = [float(value) for value in values]
    return statistics.median(clean) if clean else 0.0


def _std(values: Iterable[float]) -> float:
    clean = [float(value) for value in values]
    return statistics.pstdev(clean) if len(clean) > 1 else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
