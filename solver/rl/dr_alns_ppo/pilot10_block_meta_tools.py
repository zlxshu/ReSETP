from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scipy.stats import wilcoxon

from .async_block_policy import load_async_block_policy
from .pilot08_eval_tools import (
    BLOCK_SIZE,
    DEFAULT_WORKER,
    FORMAL_BUNDLE,
    HELD_OUT_BUNDLE,
    REQUIRED_NUMPY,
    TARGET_SECONDS,
    TIMED_EVAL_CAP,
    TRAIN_BUNDLE,
    algorithm_summary,
    final_model_update,
    run_policy_row,
    run_sa_row,
    runtime_summary,
    row_gate_issues,
)
from .pilot09_rescue_tools import (
    RESULT_COLUMNS,
    meta_label,
    normalize_rescue_row,
    rank_meta_configs,
    run_alpha_ucb_meta_row,
    run_block_model_policy,
)


PILOT10_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot10")
PILOT09_RESCUE_FULL = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot09/rescue_full")
PILOT08_CURRICULUM_MANIFEST = Path(
    "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot08/training_bundle_manifest_curriculum.json"
)
PILOT10_TRAIN_FINAL_DIR = PILOT10_DIR / "train_final"
PILOT10_FINAL_MODEL = PILOT10_TRAIN_FINAL_DIR / "async_block_ppo_model.pt"
PILOT10_CHECKPOINT_DIR = PILOT10_TRAIN_FINAL_DIR / "checkpoints"
EVAL_BUDGET_900 = 13_100
CHEAP_BUDGET = 600
DEFAULT_META_LABEL = "default"
BEST_STATIC_LABEL = "best_static_meta"
STATIC_CANDIDATE_ALGORITHM = "static_alpha_ucb_meta"
DEFAULT_META_ALGORITHM = "default_alpha_ucb_meta"
BLOCK_META_BEST_ALGORITHM = "block_meta_best"
BLOCK_META_FINAL_ALGORITHM = "block_meta_final"

FALLBACK_TOP3 = (
    (0.40, 0.0, 0.05),
    (0.40, 0.0025, 0.15),
    (0.16, 0.0, 0.05),
)


@dataclass(frozen=True)
class StaticMetaConfig:
    label: str
    q_ratio: float
    threshold_ratio: float
    exploration_ratio: float
    source: str = ""


def load_top_static_meta_configs(source_dir: str | Path = PILOT09_RESCUE_FULL, *, limit: int = 3) -> list[StaticMetaConfig]:
    source = Path(source_dir)
    ranking = source / "pilot09_meta_screen_ranking.csv"
    rows = source / "pilot09_meta_screen_rows.csv"
    if ranking.is_file():
        loaded = _read_csv(ranking)
        loaded.sort(key=lambda row: int(float(row.get("rank") or 999999)))
        return [_config_from_row(row, source="pilot09_ranking") for row in loaded[: int(limit)]]
    if rows.is_file():
        ranked = rank_meta_configs(_read_csv(rows))
        return [_config_from_row(row, source="pilot09_rows_reconstructed") for row in ranked[: int(limit)]]
    return [
        StaticMetaConfig(
            label=meta_label(q_ratio, threshold_ratio, exploration_ratio),
            q_ratio=float(q_ratio),
            threshold_ratio=float(threshold_ratio),
            exploration_ratio=float(exploration_ratio),
            source="fixed_pilot09_fallback",
        )
        for q_ratio, threshold_ratio, exploration_ratio in FALLBACK_TOP3[: int(limit)]
    ]


def run_d1_static_meta(
    *,
    output_dir: str | Path = PILOT10_DIR,
    source_dir: str | Path = PILOT09_RESCUE_FULL,
    eval_budget: int = EVAL_BUDGET_900,
    block_size: int = BLOCK_SIZE,
    resume: bool = False,
) -> dict[str, Any]:
    out = Path(output_dir)
    if out.exists() and any(out.iterdir()) and not resume:
        raise RuntimeError(f"HALT_PILOT10_PREFLIGHT: output dir exists and is non-empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    preflight = preflight_checks(require_clean=True, allow_output_dir=out)
    configs = load_top_static_meta_configs(source_dir)
    all_configs = [
        StaticMetaConfig(DEFAULT_META_LABEL, 0.16, 0.0, 0.0, source="default_alpha_ucb"),
        *configs,
    ]
    partial_path = out / "pilot10_d1_static_meta_rows.partial.csv"
    rows = _load_rows(partial_path)
    existing = {_d1_key(row) for row in rows}
    for role, bundle in (("train", TRAIN_BUNDLE), ("held_out", HELD_OUT_BUNDLE)):
        for config in all_configs:
            for seed in range(1, 6):
                key = (bundle, seed, config.label)
                if key in existing:
                    continue
                row = run_alpha_ucb_meta_row(
                    bundle=bundle,
                    seed=seed,
                    eval_budget=eval_budget,
                    block_size=block_size,
                    q_ratio=config.q_ratio,
                    threshold_ratio=config.threshold_ratio,
                    exploration_ratio=config.exploration_ratio,
                    bundle_role=role,
                    model_label=config.label,
                )
                row["algorithm"] = DEFAULT_META_ALGORITHM if config.label == DEFAULT_META_LABEL else STATIC_CANDIDATE_ALGORITHM
                row["eval_mode"] = "budget"
                row["runtime_target_seconds"] = TARGET_SECONDS
                _validate_budget_row(row, expected_budget=eval_budget)
                rows.append(normalize_rescue_row(row))
                existing.add(key)
                _write_rows(partial_path, rows)
    candidate_labels = [config.label for config in configs]
    gate = classify_d1_gate(rows, candidate_labels=candidate_labels)
    paired = paired_relative_rows(_d1_rows_for_paired(rows, gate), left_algorithm=BEST_STATIC_LABEL, baseline_algorithm=DEFAULT_META_ALGORITHM)
    summary = {
        "schema_version": "resetp-pilot10-d1.v1",
        "status": gate["status"],
        "eval_budget_900": int(eval_budget),
        "block_size": int(block_size),
        "preflight": preflight,
        "top3_source": [config.__dict__ for config in configs],
        "d1_gate": gate,
        "paired_relative": paired,
        "same_machine_relative_note": "Pilot10 reports x86 same-machine relative percentages only; no M1 absolute comparison is made.",
    }
    _write_rows(out / "pilot10_d1_static_meta_rows.csv", rows)
    _write_csv(out / "pilot10_d1_paired_relative.csv", paired, _paired_fields())
    _write_json(out / "pilot10_summary.json", summary)
    (out / "pilot10_final_report.md").write_text(_report_markdown(summary), encoding="utf-8")
    return summary


def run_block_meta_row(
    *,
    model_path: str | Path,
    bundle: str,
    seed: int,
    eval_budget: int,
    block_size: int,
    algorithm: str,
    model_label: str,
    checkpoint_update_value: int | str,
    bundle_role: str,
    eval_mode: str = "budget",
    runtime_target_seconds: float = TARGET_SECONDS,
) -> dict[str, Any]:
    policy = load_async_block_policy(model_path)
    started = time.perf_counter()
    row, _trace = run_block_model_policy(
        model=policy.model,
        bundle=bundle,
        seed=seed,
        eval_budget=eval_budget,
        block_size=block_size,
        stochastic=False,
        collect_trace=False,
        meta_mode=True,
    )
    elapsed = time.perf_counter() - started
    row.update(
        {
            "algorithm": algorithm,
            "elapsed_seconds": elapsed,
            "runtime_target_seconds": runtime_target_seconds,
            "model_label": model_label,
            "checkpoint_update": checkpoint_update_value,
            "eval_mode": eval_mode,
            "bundle_role": bundle_role,
            "selection_mode": "block_meta_masked",
            "meta_q_ratio": "",
            "meta_threshold_ratio": "",
            "meta_exploration_ratio": "",
        }
    )
    _validate_budget_row(row, expected_budget=eval_budget)
    return normalize_rescue_row(row)


def run_training(
    *,
    output_dir: str | Path = PILOT10_TRAIN_FINAL_DIR,
    ppo_python: str | Path,
) -> None:
    out = Path(output_dir)
    if out.exists() and any(out.iterdir()):
        raise RuntimeError(f"HALT_PILOT10_TRAIN: output dir exists and is non-empty: {out}")
    cmd = [
        str(ppo_python),
        "-m",
        "dr_alns_ppo.train_async_block_ppo",
        "train",
        "--curriculum",
        "--meta-mode",
        "--manifest",
        str(PILOT08_CURRICULUM_MANIFEST),
        "--output-dir",
        str(out),
        "--seed",
        "20260621",
        "--num-actors",
        "6",
        "--eval-budget",
        "600",
        "--block-size",
        "32",
        "--device",
        "cuda",
        "--curriculum-schedule",
        "route,energy,carbon",
        "--phase-min-episodes",
        "100",
        "--phase-learning-rates",
        "3e-4,2e-4,1e-4",
        "--phase-clip-ranges",
        "0.2,0.15,0.1",
        "--phase-entropy-coefs",
        "0.01,0.01,0.015",
        "--phase-value-clip-ranges",
        "0.2,0.2,0.2",
        "--phase-advantage-clip-ranges",
        "2.5,2.0,1.5",
        "--max-grad-norm",
        "0.5",
        "--timesteps",
        "160000",
        "--rollout-min-episodes",
        "24",
        "--rollout-min-steps",
        "256",
        "--checkpoint-every-updates",
        "10",
        "--poll-seconds",
        "2",
        "--cpu-sample-interval-seconds",
        "60",
    ]
    proc = subprocess.run(cmd, cwd=Path.cwd(), env=_driver_env(Path.cwd()), text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"HALT_PILOT10_TRAIN: train command failed rc={proc.returncode}")


def training_health(train_dir: str | Path = PILOT10_TRAIN_FINAL_DIR) -> dict[str, Any]:
    root = Path(train_dir)
    config = _load_json(root / "async_training_config.json") or {}
    summary = _load_json(root / "async_train_summary.json") or {}
    episode_rows = _read_csv(root / "async_episode_log.csv") if (root / "async_episode_log.csv").is_file() else []
    transitions = _read_csv(root / "phase_transitions.csv") if (root / "phase_transitions.csv").is_file() else []
    entropy = _read_csv(root / "policy_entropy.csv") if (root / "policy_entropy.csv").is_file() else []
    update_rows = _read_csv(root / "async_update_log.csv") if (root / "async_update_log.csv").is_file() else []
    checkpoints = sorted(PILOT10_CHECKPOINT_DIR.glob("async_block_ppo_update_*.pt"), key=checkpoint_update)
    workers = {str(row.get("worker_python_executable", "")) for row in episode_rows}
    numpy_versions = {str(row.get("worker_numpy_version", "")) for row in episode_rows}
    violations = sum(int(float(row.get("violation_count") or 0)) for row in episode_rows)
    finite_rewards = all(_finite(row.get("reward_sum")) and _finite(row.get("best_obj")) for row in episode_rows)
    phases = [str(row.get("to_phase")) for row in transitions]
    entropy_values = [float(row["entropy"]) for row in entropy if _finite(row.get("entropy"))]
    ok = bool(
        len(config.get("train_bundles", [])) == 12
        and str(config.get("resolved_device")) == "cuda"
        and bool(config.get("meta_mode")) is True
        and str(Path(next(iter(workers), "")).resolve()) == str(Path(DEFAULT_WORKER).resolve())
        and numpy_versions == {REQUIRED_NUMPY}
        and violations == 0
        and finite_rewards
        and {"energy", "carbon"}.issubset(set(phases))
        and bool(config.get("shared_baseline_by_bundle", False))
        and bool(checkpoints)
        and PILOT10_FINAL_MODEL.is_file()
    )
    return {
        "ok": ok,
        "train_bundles": len(config.get("train_bundles", [])),
        "device": config.get("resolved_device"),
        "meta_mode": config.get("meta_mode"),
        "episode_count": len(episode_rows),
        "update_count": len(update_rows),
        "workers": sorted(workers),
        "numpy_versions": sorted(numpy_versions),
        "violation_count_sum": violations,
        "finite_rewards_and_objectives": finite_rewards,
        "phase_transitions": transitions,
        "checkpoint_count": len(checkpoints),
        "checkpoints": [str(path) for path in checkpoints],
        "entropy_first": entropy_values[0] if entropy_values else "",
        "entropy_mid": entropy_values[len(entropy_values) // 2] if entropy_values else "",
        "entropy_final": entropy_values[-1] if entropy_values else "",
        "summary": summary,
    }


def run_checkpoint_screen(
    *,
    output_dir: str | Path = PILOT10_DIR,
    cheap_budget: int = CHEAP_BUDGET,
) -> list[dict[str, Any]]:
    out = Path(output_dir)
    checkpoints = sorted(PILOT10_CHECKPOINT_DIR.glob("async_block_ppo_update_*.pt"), key=checkpoint_update)
    if not checkpoints:
        raise RuntimeError(f"HALT_PILOT10_EVAL: no checkpoints under {PILOT10_CHECKPOINT_DIR}")
    partial = out / "pilot10_checkpoint_cheap_rows.partial.csv"
    rows = _load_rows(partial)
    existing = {_model_key(row) for row in rows}
    for path in checkpoints:
        update = checkpoint_update(path)
        label = f"checkpoint_{update:04d}"
        key = (HELD_OUT_BUNDLE, 1, label, update)
        if key in existing:
            continue
        rows.append(
            run_block_meta_row(
                model_path=path,
                bundle=HELD_OUT_BUNDLE,
                seed=1,
                eval_budget=cheap_budget,
                block_size=BLOCK_SIZE,
                algorithm="block_meta_checkpoint",
                model_label=label,
                checkpoint_update_value=update,
                bundle_role="held_out",
                eval_mode="cheap",
                runtime_target_seconds=0.0,
            )
        )
        _write_rows(partial, rows)
    ranking = rank_models(rows)
    _write_rows(out / "pilot10_checkpoint_cheap_rows.csv", rows)
    _write_csv(out / "pilot10_checkpoint_cheap_ranking.csv", ranking, _ranking_fields())
    return ranking


def run_checkpoint_refine(
    *,
    output_dir: str | Path = PILOT10_DIR,
    cheap_ranking: list[dict[str, Any]],
    eval_budget: int = EVAL_BUDGET_900,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    out = Path(output_dir)
    final_update = final_model_update(PILOT10_TRAIN_FINAL_DIR)
    candidates: list[tuple[str, Path, int]] = []
    for row in cheap_ranking[:3]:
        update = int(row["checkpoint_update"])
        candidates.append((str(row["model_label"]), PILOT10_CHECKPOINT_DIR / f"async_block_ppo_update_{update:04d}.pt", update))
    candidates.append(("final", PILOT10_FINAL_MODEL, final_update))
    partial = out / "pilot10_checkpoint_refine_rows.partial.csv"
    rows = _load_rows(partial)
    existing = {_model_key(row) for row in rows}
    for label, model_path, update in candidates:
        for seed in (1, 2, 3):
            key = (HELD_OUT_BUNDLE, seed, label, update)
            if key in existing:
                continue
            rows.append(
                run_block_meta_row(
                    model_path=model_path,
                    bundle=HELD_OUT_BUNDLE,
                    seed=seed,
                    eval_budget=eval_budget,
                    block_size=BLOCK_SIZE,
                    algorithm="block_meta_refine",
                    model_label=label,
                    checkpoint_update_value=update,
                    bundle_role="held_out",
                    eval_mode="refine",
                    runtime_target_seconds=TARGET_SECONDS,
                )
            )
            _write_rows(partial, rows)
    ranking = rank_models(rows)
    _write_rows(out / "pilot10_checkpoint_refine_rows.csv", rows)
    _write_csv(out / "pilot10_checkpoint_refine_ranking.csv", ranking, _ranking_fields())
    if not ranking:
        raise RuntimeError("HALT_PILOT10_EVAL: no refined checkpoint rows")
    return ranking[0], ranking


def run_formal_comparison(
    *,
    output_dir: str | Path = PILOT10_DIR,
    best_model: dict[str, Any],
    best_static_meta: dict[str, Any],
    eval_budget: int = EVAL_BUDGET_900,
) -> list[dict[str, Any]]:
    out = Path(output_dir)
    partial = out / "pilot10_comparison_rows.partial.csv"
    rows = _load_rows(partial)
    existing = {_formal_key(row) for row in rows}
    tasks = _formal_tasks(best_model=best_model, best_static_meta=best_static_meta, eval_budget=eval_budget)
    for task in tasks:
        key = _formal_task_key(task)
        if key in existing:
            continue
        if task["kind"] == "block_meta":
            row = run_block_meta_row(
                model_path=task["model_path"],
                bundle=task["bundle"],
                seed=task["seed"],
                eval_budget=task["eval_budget"],
                block_size=BLOCK_SIZE,
                algorithm=task["algorithm"],
                model_label=task["model_label"],
                checkpoint_update_value=task["checkpoint_update"],
                bundle_role=task["bundle_role"],
                eval_mode="budget",
                runtime_target_seconds=TARGET_SECONDS,
            )
        elif task["kind"] == "static_meta":
            row = run_alpha_ucb_meta_row(
                bundle=task["bundle"],
                seed=task["seed"],
                eval_budget=task["eval_budget"],
                block_size=BLOCK_SIZE,
                q_ratio=task["q_ratio"],
                threshold_ratio=task["threshold_ratio"],
                exploration_ratio=task["exploration_ratio"],
                bundle_role=task["bundle_role"],
                model_label=task["model_label"],
            )
            row["algorithm"] = task["algorithm"]
            row["runtime_target_seconds"] = TARGET_SECONDS
            _validate_budget_row(row, expected_budget=eval_budget)
            row = normalize_rescue_row(row)
        elif task["kind"] == "sa":
            row = run_sa_row(
                bundle=task["bundle"],
                seed=task["seed"],
                eval_budget=TIMED_EVAL_CAP,
                max_runtime_seconds=TARGET_SECONDS,
                bundle_role=task["bundle_role"],
            )
        else:
            row = run_policy_row(
                algorithm=task["algorithm"],
                bundle=task["bundle"],
                seed=task["seed"],
                eval_budget=task["eval_budget"],
                bundle_role=task["bundle_role"],
                eval_mode=task["eval_mode"],
                runtime_target_seconds=task["runtime_target_seconds"],
                block_size=BLOCK_SIZE,
                official_max_runtime_seconds=TARGET_SECONDS,
            )
        _validate_row(row, expected_budget=eval_budget if row.get("eval_mode") == "budget" else None)
        rows.append(normalize_rescue_row(row))
        _write_rows(partial, rows)
    _write_rows(out / "pilot10_comparison_rows.csv", rows)
    return rows


def summarize_final(
    *,
    output_dir: str | Path,
    d1_summary: dict[str, Any],
    training: dict[str, Any] | None,
    best_model: dict[str, Any] | None,
    refine_ranking: list[dict[str, Any]] | None,
    comparison_rows: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    out = Path(output_dir)
    if d1_summary.get("status") != "PASS_D1":
        summary = dict(d1_summary)
        summary["verdict"] = "HALT_META_BUDGET_ARTIFACT"
    else:
        if not training or not training.get("ok"):
            summary = {
                "schema_version": "resetp-pilot10-summary.v1",
                "verdict": "HALT_PILOT10_TRAIN",
                "reason": "block_meta training health gate failed",
                "d1": d1_summary,
                "training": training or {},
            }
        else:
            rows = comparison_rows or []
            paired = paired_relative_rows(rows, left_algorithm=BLOCK_META_BEST_ALGORITHM, baseline_algorithm=BEST_STATIC_LABEL)
            wilcox = wilcoxon_rows(rows, left_algorithm=BLOCK_META_BEST_ALGORITHM, baseline_algorithm=BEST_STATIC_LABEL)
            verdict = classify_final_verdict(paired, wilcox, d1_status="PASS_D1")
            summary = {
                "schema_version": "resetp-pilot10-summary.v1",
                "verdict": verdict["verdict"],
                "reason": verdict["reason"],
                "eval_budget_900": EVAL_BUDGET_900,
                "d1": d1_summary,
                "training": training,
                "best_meta_checkpoint": best_model or {},
                "refine_ranking": refine_ranking or [],
                "algorithm_summary": algorithm_summary(rows),
                "runtime_summary": runtime_summary(rows),
                "paired_relative": paired,
                "wilcoxon": wilcox,
                "same_machine_relative_note": "Pilot10 reports x86 same-machine relative percentages only; no M1 absolute comparison is made.",
            }
            _write_csv(out / "pilot10_algorithm_summary.csv", summary["algorithm_summary"], _algorithm_summary_fields())
            _write_csv(out / "pilot10_runtime_summary.csv", summary["runtime_summary"], _runtime_fields())
            _write_csv(out / "pilot10_paired_relative.csv", paired, _paired_fields())
            _write_csv(out / "pilot10_wilcoxon.csv", wilcox, _wilcoxon_fields())
    _write_json(out / "pilot10_summary.json", summary)
    (out / "pilot10_final_report.md").write_text(_report_markdown(summary), encoding="utf-8")
    return summary


def classify_d1_gate(rows: list[dict[str, Any]], *, candidate_labels: list[str]) -> dict[str, Any]:
    default_by_bundle = _mean_by_label(rows, DEFAULT_META_LABEL)
    meta_by_label = {
        str(row.get("model_label")): (
            row.get("meta_q_ratio", ""),
            row.get("meta_threshold_ratio", ""),
            row.get("meta_exploration_ratio", ""),
        )
        for row in rows
        if str(row.get("model_label")) in set(candidate_labels)
    }
    candidates = []
    for label in candidate_labels:
        means = _mean_by_label(rows, label)
        train_rel, train_wins = _relative_vs_default(rows, label, TRAIN_BUNDLE)
        held_rel, held_wins = _relative_vs_default(rows, label, HELD_OUT_BUNDLE)
        q_ratio, threshold_ratio, exploration_ratio = meta_by_label.get(label, ("", "", ""))
        candidates.append(
            {
                "model_label": label,
                "meta_q_ratio": q_ratio,
                "meta_threshold_ratio": threshold_ratio,
                "meta_exploration_ratio": exploration_ratio,
                "train_best_obj": means.get(TRAIN_BUNDLE, math.inf),
                "held_out_best_obj": means.get(HELD_OUT_BUNDLE, math.inf),
                "train_relative_pct_vs_default": train_rel,
                "held_out_relative_pct_vs_default": held_rel,
                "train_wins_vs_default": train_wins,
                "held_out_wins_vs_default": held_wins,
            }
        )
    candidates.sort(key=lambda row: (float(row["held_out_best_obj"]), float(row["train_best_obj"]), str(row["model_label"])))
    best = candidates[0] if candidates else {}
    passed = bool(
        best
        and float(best["held_out_relative_pct_vs_default"]) > 1.0
        and int(best["held_out_wins_vs_default"]) >= 3
    )
    return {
        "status": "PASS_D1" if passed else "HALT_META_BUDGET_ARTIFACT",
        "best_static_meta": best,
        "default": {
            "model_label": DEFAULT_META_LABEL,
            "train_best_obj": default_by_bundle.get(TRAIN_BUNDLE, math.inf),
            "held_out_best_obj": default_by_bundle.get(HELD_OUT_BUNDLE, math.inf),
        },
        "candidates": candidates,
        "rule": "D1 passes only if the held-out best top-3 static meta has mean relative > +1% and wins >= 3/5 versus default.",
    }


def paired_relative_rows(
    rows: list[dict[str, Any]],
    *,
    left_algorithm: str,
    baseline_algorithm: str,
) -> list[dict[str, Any]]:
    index = {(str(row["bundle"]), int(row["seed"]), str(row["algorithm"])): row for row in rows}
    bundles = sorted({str(row["bundle"]) for row in rows})
    out: list[dict[str, Any]] = []
    for bundle in bundles:
        values = []
        wins = 0
        for (b, seed, algorithm), left_row in sorted(index.items()):
            if b != bundle or algorithm != left_algorithm:
                continue
            base_row = index.get((bundle, seed, baseline_algorithm))
            if base_row is None:
                continue
            left_cost = float(left_row["best_obj"])
            base_cost = float(base_row["best_obj"])
            if abs(base_cost) <= 1e-12:
                continue
            values.append((base_cost - left_cost) / base_cost * 100.0)
            wins += int(left_cost < base_cost)
        if values:
            out.append(
                {
                    "bundle": bundle,
                    "left_algorithm": left_algorithm,
                    "baseline_algorithm": baseline_algorithm,
                    "paired_n": len(values),
                    "wins": wins,
                    "mean_relative_pct": statistics.fmean(values),
                    "std_relative_pct": statistics.stdev(values) if len(values) > 1 else 0.0,
                    "min_relative_pct": min(values),
                    "max_relative_pct": max(values),
                }
            )
    return out


def wilcoxon_rows(
    rows: list[dict[str, Any]],
    *,
    left_algorithm: str,
    baseline_algorithm: str,
) -> list[dict[str, Any]]:
    index = {(str(row["bundle"]), int(row["seed"]), str(row["algorithm"])): row for row in rows}
    bundles = sorted({str(row["bundle"]) for row in rows})
    out: list[dict[str, Any]] = []
    for bundle in bundles:
        diffs = []
        for (b, seed, algorithm), left_row in sorted(index.items()):
            if b != bundle or algorithm != left_algorithm:
                continue
            base_row = index.get((bundle, seed, baseline_algorithm))
            if base_row is None:
                continue
            diffs.append(float(base_row["best_obj"]) - float(left_row["best_obj"]))
        if len(diffs) >= 5:
            try:
                result = wilcoxon(diffs, alternative="greater", zero_method="wilcox", method="exact")
                statistic = float(result.statistic)
                p_value: float | str = float(result.pvalue)
            except ValueError:
                statistic = math.nan
                p_value = math.nan
            used = True
        else:
            statistic = ""
            p_value = ""
            used = False
        out.append(
            {
                "bundle": bundle,
                "left_algorithm": left_algorithm,
                "baseline_algorithm": baseline_algorithm,
                "paired_n": len(diffs),
                "wins": sum(1 for diff in diffs if diff > 0.0),
                "statistic": statistic,
                "p_value": p_value,
                "alternative": "greater",
                "used_for_gate": used,
            }
        )
    return out


def rank_models(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("model_label", "")), int(row.get("checkpoint_update") or -1))].append(row)
    ranked = []
    for (label, update), group in grouped.items():
        values = [float(row["best_obj"]) for row in group]
        ranked.append(
            {
                "rank": 0,
                "model_label": label,
                "checkpoint_update": update,
                "n": len(group),
                "mean_best_obj": statistics.fmean(values),
                "std_best_obj": statistics.stdev(values) if len(values) > 1 else 0.0,
                "min_best_obj": min(values),
                "max_best_obj": max(values),
                "model_path": _model_path_for_label(label, update),
            }
        )
    ranked.sort(key=lambda row: (float(row["mean_best_obj"]), 0 if row["model_label"] == "final" else 1, -int(row["checkpoint_update"])))
    for idx, row in enumerate(ranked, start=1):
        row["rank"] = idx
    return ranked


def classify_final_verdict(
    paired_rows: list[dict[str, Any]],
    wilcoxon_stats: list[dict[str, Any]],
    *,
    d1_status: str,
) -> dict[str, str]:
    if d1_status != "PASS_D1":
        return {"verdict": d1_status, "reason": "Pilot10 stopped before block_meta training because D1 did not pass."}
    paired = {(row["bundle"], row["baseline_algorithm"]): row for row in paired_rows}
    train = paired.get((TRAIN_BUNDLE, BEST_STATIC_LABEL))
    held = paired.get((HELD_OUT_BUNDLE, BEST_STATIC_LABEL))
    if (
        train is None
        or held is None
        or float(train["mean_relative_pct"]) <= 0.0
        or float(held["mean_relative_pct"]) <= 0.0
        or int(train["wins"]) < 4
        or int(held["wins"]) < 4
    ):
        return {
            "verdict": "WEAK_RETUNE",
            "reason": "Static meta beat default, but learned block_meta did not beat BEST_STATIC_META on train and held-out with positive mean and >=4/5 wins.",
        }
    held_w = next(
        (row for row in wilcoxon_stats if row["bundle"] == HELD_OUT_BUNDLE and row["baseline_algorithm"] == BEST_STATIC_LABEL),
        None,
    )
    held_p = _to_float(held_w.get("p_value") if held_w else "")
    if math.isfinite(held_p) and held_p <= 0.05:
        return {
            "verdict": "STRONG",
            "reason": "block_meta beat BEST_STATIC_META on train and held-out, and held-out one-sided Wilcoxon p <= 0.05.",
        }
    return {
        "verdict": "PROMISING_RESCUE",
        "reason": "block_meta beat BEST_STATIC_META on train and held-out by mean relative percent with >=4/5 wins.",
    }


def preflight_checks(*, require_clean: bool, allow_output_dir: Path | None = None) -> dict[str, Any]:
    repo = Path.cwd()
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    if branch != "dr-x86":
        raise RuntimeError(f"HALT_PILOT10_PREFLIGHT: expected dr-x86, got {branch}")
    status_lines = [line for line in _git(["status", "--short"]).splitlines() if line.strip()]
    if require_clean:
        allowed_prefix = None
        if allow_output_dir is not None:
            try:
                allowed_prefix = str(allow_output_dir.resolve())
            except OSError:
                allowed_prefix = None
        unexpected = []
        for line in status_lines:
            path_text = line[3:].strip()
            if allowed_prefix and str((repo / path_text).resolve()).startswith(allowed_prefix):
                continue
            unexpected.append(line)
        if unexpected:
            raise RuntimeError(f"HALT_PILOT10_PREFLIGHT: dirty worktree {unexpected}")
    if os.environ.get("SETP_WORKER_PYTHON") != DEFAULT_WORKER:
        raise RuntimeError("HALT_PILOT10_PREFLIGHT: SETP_WORKER_PYTHON is not the py313 worker")
    worker_numpy = _worker_numpy_version(DEFAULT_WORKER)
    if worker_numpy != REQUIRED_NUMPY:
        raise RuntimeError(f"HALT_PILOT10_PREFLIGHT: worker NumPy {worker_numpy}, expected {REQUIRED_NUMPY}")
    if not (PILOT09_RESCUE_FULL / "pilot09_meta_screen_ranking.csv").is_file() and not (
        PILOT09_RESCUE_FULL / "pilot09_meta_screen_rows.csv"
    ).is_file():
        raise RuntimeError("HALT_PILOT10_PREFLIGHT: Pilot09 meta evidence is missing")
    return {
        "branch": branch,
        "head": _git(["rev-parse", "HEAD"]),
        "worker_python": DEFAULT_WORKER,
        "worker_numpy": worker_numpy,
        "pilot09_evidence_dir": str(PILOT09_RESCUE_FULL),
    }


def checkpoint_update(path: str | Path) -> int:
    name = Path(path).stem
    digits = "".join(ch for ch in name.split("update_")[-1] if ch.isdigit())
    return int(digits) if digits else -1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot10 block_meta rescue tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    d1 = sub.add_parser("run-d1")
    d1.add_argument("--output-dir", default=str(PILOT10_DIR))
    d1.add_argument("--source-dir", default=str(PILOT09_RESCUE_FULL))
    d1.add_argument("--resume", action="store_true")
    train = sub.add_parser("train")
    train.add_argument("--output-dir", default=str(PILOT10_TRAIN_FINAL_DIR))
    train.add_argument("--ppo-python", required=True)
    health = sub.add_parser("training-health")
    health.add_argument("--train-dir", default=str(PILOT10_TRAIN_FINAL_DIR))
    ev = sub.add_parser("run-ev")
    ev.add_argument("--output-dir", default=str(PILOT10_DIR))
    ev.add_argument("--resume", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "run-d1":
        summary = run_d1_static_meta(output_dir=args.output_dir, source_dir=args.source_dir, resume=args.resume)
        print(f"PILOT10_D1_DONE status={summary['status']} output={args.output_dir}")
        return 0 if summary["status"] == "PASS_D1" else 2
    if args.command == "train":
        run_training(output_dir=args.output_dir, ppo_python=args.ppo_python)
        print(f"PILOT10_TRAIN_DONE output={args.output_dir}")
        return 0
    if args.command == "training-health":
        health = training_health(args.train_dir)
        print(json.dumps(health, ensure_ascii=False, sort_keys=True))
        return 0 if health["ok"] else 2
    if args.command == "run-ev":
        existing = _load_json(Path(args.output_dir) / "pilot10_summary.json") or {}
        d1 = existing if existing.get("schema_version") == "resetp-pilot10-d1.v1" else existing.get("d1", {})
        if d1.get("status") != "PASS_D1":
            raise RuntimeError("HALT_PILOT10_EVAL: D1 summary is missing or did not pass")
        health = training_health()
        if not health["ok"]:
            summarize_final(output_dir=args.output_dir, d1_summary=d1, training=health, best_model=None, refine_ranking=None, comparison_rows=None)
            return 2
        cheap = run_checkpoint_screen(output_dir=args.output_dir)
        best, refine = run_checkpoint_refine(output_dir=args.output_dir, cheap_ranking=cheap)
        comparison = run_formal_comparison(
            output_dir=args.output_dir,
            best_model=best,
            best_static_meta=d1["d1_gate"]["best_static_meta"],
        )
        summary = summarize_final(
            output_dir=args.output_dir,
            d1_summary=d1,
            training=health,
            best_model=best,
            refine_ranking=refine,
            comparison_rows=comparison,
        )
        print(f"PILOT10_EV_DONE verdict={summary['verdict']} output={args.output_dir}")
        return 0 if summary["verdict"] in {"STRONG", "PROMISING_RESCUE", "WEAK_RETUNE"} else 2
    raise ValueError(f"unknown command {args.command}")


def _formal_tasks(*, best_model: dict[str, Any], best_static_meta: dict[str, Any], eval_budget: int) -> list[dict[str, Any]]:
    best_label = str(best_model["model_label"])
    best_update = int(best_model["checkpoint_update"])
    best_path = PILOT10_FINAL_MODEL if best_label == "final" else PILOT10_CHECKPOINT_DIR / f"async_block_ppo_update_{best_update:04d}.pt"
    final_update = final_model_update(PILOT10_TRAIN_FINAL_DIR)
    bundles = (("train", TRAIN_BUNDLE), ("held_out", HELD_OUT_BUNDLE), ("formal_eval", FORMAL_BUNDLE))
    tasks: list[dict[str, Any]] = []
    for role, bundle in bundles:
        for seed in (1, 2, 3, 4, 5):
            tasks.append(
                {
                    "kind": "block_meta",
                    "algorithm": BLOCK_META_BEST_ALGORITHM,
                    "bundle": bundle,
                    "bundle_role": role,
                    "seed": seed,
                    "eval_budget": eval_budget,
                    "model_path": str(best_path),
                    "model_label": best_label,
                    "checkpoint_update": best_update,
                }
            )
            tasks.append(
                {
                    "kind": "static_meta",
                    "algorithm": BEST_STATIC_LABEL,
                    "bundle": bundle,
                    "bundle_role": role,
                    "seed": seed,
                    "eval_budget": eval_budget,
                    "q_ratio": float(best_static_meta["meta_q_ratio"]),
                    "threshold_ratio": float(best_static_meta["meta_threshold_ratio"]),
                    "exploration_ratio": float(best_static_meta["meta_exploration_ratio"]),
                    "model_label": BEST_STATIC_LABEL,
                }
            )
        for seed in (1, 2, 3):
            tasks.append(
                {
                    "kind": "block_meta",
                    "algorithm": BLOCK_META_FINAL_ALGORITHM,
                    "bundle": bundle,
                    "bundle_role": role,
                    "seed": seed,
                    "eval_budget": eval_budget,
                    "model_path": str(PILOT10_FINAL_MODEL),
                    "model_label": "final",
                    "checkpoint_update": final_update,
                }
            )
            tasks.append(
                {
                    "kind": "policy",
                    "algorithm": "alpha_ucb_block",
                    "bundle": bundle,
                    "bundle_role": role,
                    "seed": seed,
                    "eval_budget": eval_budget,
                    "eval_mode": "budget",
                    "runtime_target_seconds": TARGET_SECONDS,
                }
            )
            tasks.append(
                {
                    "kind": "policy",
                    "algorithm": "random_block",
                    "bundle": bundle,
                    "bundle_role": role,
                    "seed": seed,
                    "eval_budget": eval_budget,
                    "eval_mode": "budget",
                    "runtime_target_seconds": TARGET_SECONDS,
                }
            )
            tasks.append(
                {
                    "kind": "sa",
                    "algorithm": "scikit-opt-SA",
                    "bundle": bundle,
                    "bundle_role": role,
                    "seed": seed,
                    "eval_budget": TIMED_EVAL_CAP,
                    "eval_mode": "timed",
                    "runtime_target_seconds": TARGET_SECONDS,
                }
            )
            tasks.append(
                {
                    "kind": "policy",
                    "algorithm": "official_winner_kernel",
                    "bundle": bundle,
                    "bundle_role": role,
                    "seed": seed,
                    "eval_budget": TIMED_EVAL_CAP,
                    "eval_mode": "timed",
                    "runtime_target_seconds": TARGET_SECONDS,
                }
            )
    return tasks


def _formal_task_key(task: dict[str, Any]) -> tuple[str, str, int, str, int | str]:
    return (
        str(task["algorithm"]),
        str(task["bundle"]),
        int(task["seed"]),
        str(task.get("model_label", "")),
        task.get("checkpoint_update", ""),
    )


def _formal_key(row: dict[str, Any]) -> tuple[str, str, int, str, int | str]:
    return (
        str(row["algorithm"]),
        str(row["bundle"]),
        int(row["seed"]),
        str(row.get("model_label", "")),
        row.get("checkpoint_update", ""),
    )


def _d1_key(row: dict[str, Any]) -> tuple[str, int, str]:
    return (str(row["bundle"]), int(row["seed"]), str(row["model_label"]))


def _model_key(row: dict[str, Any]) -> tuple[str, int, str, int]:
    return (str(row["bundle"]), int(row["seed"]), str(row.get("model_label", "")), int(row.get("checkpoint_update") or -1))


def _d1_rows_for_paired(rows: list[dict[str, Any]], gate: dict[str, Any]) -> list[dict[str, Any]]:
    best_label = str((gate.get("best_static_meta") or {}).get("model_label", ""))
    out = []
    for row in rows:
        item = dict(row)
        if str(item.get("model_label")) == best_label:
            item["algorithm"] = BEST_STATIC_LABEL
        elif str(item.get("model_label")) == DEFAULT_META_LABEL:
            item["algorithm"] = DEFAULT_META_ALGORITHM
        out.append(item)
    return out


def _mean_by_label(rows: list[dict[str, Any]], label: str) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if str(row.get("model_label")) == label:
            grouped[str(row["bundle"])].append(float(row["best_obj"]))
    return {bundle: statistics.fmean(values) for bundle, values in grouped.items() if values}


def _relative_vs_default(rows: list[dict[str, Any]], label: str, bundle: str) -> tuple[float, int]:
    target = {(int(row["seed"]), str(row["model_label"])): row for row in rows if str(row["bundle"]) == bundle}
    relatives = []
    wins = 0
    for seed in range(1, 6):
        row = target.get((seed, label))
        default = target.get((seed, DEFAULT_META_LABEL))
        if row is None or default is None:
            continue
        row_cost = float(row["best_obj"])
        default_cost = float(default["best_obj"])
        relatives.append((default_cost - row_cost) / max(abs(default_cost), 1.0) * 100.0)
        wins += int(row_cost < default_cost)
    return (statistics.fmean(relatives) if relatives else math.nan, wins)


def _config_from_row(row: dict[str, Any], *, source: str) -> StaticMetaConfig:
    q = float(row.get("meta_q_ratio") or 0.0)
    threshold = float(row.get("meta_threshold_ratio") or 0.0)
    exploration = float(row.get("meta_exploration_ratio") or 0.0)
    return StaticMetaConfig(
        label=str(row.get("model_label") or meta_label(q, threshold, exploration)),
        q_ratio=q,
        threshold_ratio=threshold,
        exploration_ratio=exploration,
        source=source,
    )


def _validate_budget_row(row: dict[str, Any], *, expected_budget: int) -> None:
    _validate_row(row, expected_budget=expected_budget)


def _validate_row(row: dict[str, Any], *, expected_budget: int | None) -> None:
    issues = row_gate_issues(row, expected_budget=expected_budget)
    if issues:
        raise RuntimeError(f"HALT_PILOT10_ROW_GATE: {issues}: {_row_id(row)}")


def _row_id(row: dict[str, Any]) -> str:
    return f"{row.get('algorithm')} bundle={row.get('bundle')} seed={row.get('seed')} label={row.get('model_label')}"


def _read_csv(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    with p.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _load_rows(path: str | Path) -> list[dict[str, Any]]:
    rows = _read_csv(path)
    return [normalize_rescue_row(row) for row in rows]


def _write_rows(path: str | Path, rows: list[dict[str, Any]]) -> None:
    _write_csv(path, rows, RESULT_COLUMNS)


def _write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(_csv_row(row, fieldnames))


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json(path: str | Path) -> dict[str, Any] | None:
    p = Path(path)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _csv_row(row: dict[str, Any], fieldnames: list[str]) -> dict[str, Any]:
    out = {}
    for key in fieldnames:
        value = row.get(key, "")
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        elif isinstance(value, bool):
            value = int(value)
        out[key] = value
    return out


def _ranking_fields() -> list[str]:
    return ["rank", "model_label", "checkpoint_update", "n", "mean_best_obj", "std_best_obj", "min_best_obj", "max_best_obj", "model_path"]


def _paired_fields() -> list[str]:
    return [
        "bundle",
        "left_algorithm",
        "baseline_algorithm",
        "paired_n",
        "wins",
        "mean_relative_pct",
        "std_relative_pct",
        "min_relative_pct",
        "max_relative_pct",
    ]


def _wilcoxon_fields() -> list[str]:
    return ["bundle", "left_algorithm", "baseline_algorithm", "paired_n", "wins", "statistic", "p_value", "alternative", "used_for_gate"]


def _algorithm_summary_fields() -> list[str]:
    return ["bundle", "algorithm", "n", "mean_best_obj", "std_best_obj", "min_best_obj", "max_best_obj", "mean_elapsed_seconds", "feasibility_rate"]


def _runtime_fields() -> list[str]:
    return ["bundle", "algorithm", "n", "mean_elapsed_seconds", "min_elapsed_seconds", "max_elapsed_seconds", "mean_actual_evals", "eval_mode"]


def _model_path_for_label(label: str, update: int) -> str:
    if label == "final":
        return str(PILOT10_FINAL_MODEL)
    if update > 0:
        return str(PILOT10_CHECKPOINT_DIR / f"async_block_ppo_update_{update:04d}.pt")
    return ""


def _driver_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["SETP_WORKER_PYTHON"] = DEFAULT_WORKER
    env["PYTHONPATH"] = os.pathsep.join(
        [str(repo_root / "models" / "src"), str(repo_root / "solver" / "rl"), str(repo_root / "solver" / "src")]
    )
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _worker_numpy_version(worker: str) -> str:
    proc = subprocess.run(
        [worker, "-c", "import numpy as np; print(np.__version__)"],
        cwd=Path.cwd(),
        env=_driver_env(Path.cwd()),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"worker numpy probe failed rc={proc.returncode}: {proc.stderr[-1000:]}")
    return proc.stdout.strip().splitlines()[-1]


def _git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], cwd=Path.cwd(), text=True, capture_output=True, check=False, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr[-1000:]}")
    return proc.stdout.strip()


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _report_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Pilot10 Block-Meta Rescue",
        "",
        f"Verdict: `{summary.get('verdict', summary.get('status'))}`.",
        "",
        "This report uses same-machine x86 relative percentages only. It does not compare x86 absolute objectives to M1 results.",
        "",
    ]
    d1 = summary.get("d1", summary)
    gate = d1.get("d1_gate", {})
    if gate:
        best = gate.get("best_static_meta", {})
        lines.extend(
            [
                "## D1 Static Meta",
                "",
                f"- status: `{d1.get('status')}`",
                f"- BEST_STATIC_META: `{best.get('model_label')}` q={best.get('meta_q_ratio')} threshold={best.get('meta_threshold_ratio')} exploration={best.get('meta_exploration_ratio')}",
                f"- train relative vs default: `{best.get('train_relative_pct_vs_default')}`",
                f"- held relative vs default: `{best.get('held_out_relative_pct_vs_default')}` wins `{best.get('held_out_wins_vs_default')}/5`",
                "",
            ]
        )
    if summary.get("training"):
        training = summary["training"]
        lines.extend(["## Training Health", "", f"- ok: `{training.get('ok')}`", f"- episodes: `{training.get('episode_count')}`", f"- updates: `{training.get('update_count')}`", ""])
    if summary.get("paired_relative"):
        lines.extend(["## Paired Relative Percent", ""])
        for row in summary["paired_relative"]:
            lines.append(
                "- "
                f"{row['bundle']} {row['left_algorithm']} vs {row['baseline_algorithm']}: "
                f"mean={float(row['mean_relative_pct']):.4f}% wins={row['wins']}/{row['paired_n']}"
            )
        lines.append("")
    if summary.get("wilcoxon"):
        lines.extend(["## Wilcoxon", ""])
        for row in summary["wilcoxon"]:
            p = row["p_value"]
            p_text = "" if p == "" else f"{float(p):.6g}"
            lines.append(f"- {row['bundle']} vs {row['baseline_algorithm']}: n={row['paired_n']} wins={row['wins']} p={p_text}")
        lines.append("")
    reason = summary.get("reason")
    if reason:
        lines.extend(["## Reason", "", str(reason), ""])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
