from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import wilcoxon

from .action_space import (
    BLOCK_CANDIDATE_GENERATOR_CHOICES,
    BLOCK_SEARCH_CONTROL_CHOICES,
    block_action_nvecs,
)
from .async_block_policy import BlockActorCritic, load_async_block_policy
from .baselines import (
    normalize_result_row,
    run_alpha_ucb_block_policy,
    run_official_winner_kernel,
    run_random_block_policy,
    solution_signature_hash,
)
from .block_env import BlockAlnsEnv
from .bundle_manifest import load_manifest
from .pilot08_eval_tools import DEFAULT_WORKER, REQUIRED_NUMPY, run_sa_row
from .pilot09_rescue_tools import run_alpha_ucb_meta_row


PILOT17_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot17")
PILOT16_TRAIN_FINAL_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot16/train_final")
PILOT16_FINAL_MODEL = PILOT16_TRAIN_FINAL_DIR / "async_block_ppo_model.pt"
PILOT16_CHECKPOINT_DIR = PILOT16_TRAIN_FINAL_DIR / "checkpoints"
ALLSCALE_MANIFEST = Path(
    "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot14b/training_manifest_three_shift_allscale.json"
)

EVAL_BUDGET = 20
BLOCK_SIZE = 4
MAIN_SEEDS = (1, 2, 3, 4, 5)
SECONDARY_SEEDS = (1, 2, 3)
TUNED_META = (0.40, 0.0025, 0.15)

EXTRA_COLUMNS = [
    "elapsed_seconds",
    "runtime_target_seconds",
    "model_label",
    "checkpoint_update",
    "eval_mode",
    "bundle_role",
    "scale",
    "selection_subset",
    "actual_eval_fraction",
    "candidate_generator_mode",
    "search_control_mode",
    "candidate_nondefault_count",
    "search_noncontinue_count",
    "stop_requested_count",
    "meta_q_ratio",
    "meta_threshold_ratio",
    "meta_exploration_ratio",
]

BASE_COLUMNS = [
    "algorithm",
    "bundle",
    "seed",
    "eval_budget",
    "best_obj",
    "actual_evals",
    "candidate_scores",
    "repair_delta_count",
    "operator_base_id",
    "control_mode",
    "violation_count",
    "feasible",
    "solution_signature_hash",
    "operator_counts",
    "destroy_counts",
    "repair_counts",
    "q_ratio_counts",
    "worker_python_executable",
    "worker_python_version",
    "worker_numpy_version",
]
RESULT_COLUMNS = [*BASE_COLUMNS, *EXTRA_COLUMNS]


def infer_block_modes(model: BlockActorCritic) -> tuple[bool, bool]:
    nvec = tuple(int(v) for v in model.action_nvec)
    matches: list[tuple[bool, bool]] = []
    for candidate_generator_mode in (False, True):
        for search_control_mode in (False, True):
            expected = block_action_nvecs(
                candidate_generator_mode=candidate_generator_mode,
                search_control_mode=search_control_mode,
            )
            if tuple(expected) == nvec:
                matches.append((candidate_generator_mode, search_control_mode))
    if len(matches) != 1:
        raise ValueError(f"cannot infer block modes from action_nvec={nvec}")
    return matches[0]


def load_allscale_bundles(manifest_path: str | Path = ALLSCALE_MANIFEST) -> list[str]:
    manifest = load_manifest(manifest_path, validate=False)
    bundles = list(manifest.get("train") or [])
    if len(bundles) != 15:
        raise ValueError(f"expected 15 all-scale train bundles, got {len(bundles)}")
    missing = [bundle for bundle in bundles if not Path(bundle).is_dir()]
    if missing:
        raise FileNotFoundError(f"missing all-scale bundles: {missing}")
    return sorted(bundles, key=lambda value: (scale_from_bundle(value), value))


def selection_bundles(bundles: list[str]) -> list[str]:
    by_scale: dict[int, list[str]] = defaultdict(list)
    for bundle in bundles:
        by_scale[scale_from_bundle(bundle)].append(bundle)
    selected = []
    for scale in sorted(by_scale):
        candidates = sorted(by_scale[scale])
        preferred = [bundle for bundle in candidates if bundle.endswith("-03")]
        selected.append(preferred[0] if preferred else candidates[-1])
    return selected


def discover_checkpoints(checkpoint_dir: str | Path = PILOT16_CHECKPOINT_DIR) -> list[Path]:
    paths = sorted(Path(checkpoint_dir).glob("async_block_ppo_update_*.pt"), key=checkpoint_update)
    if not paths:
        raise FileNotFoundError(f"no Pilot16 checkpoints under {checkpoint_dir}")
    return paths


def checkpoint_update(path: str | Path) -> int:
    match = re.search(r"update_(\d+)", Path(path).name)
    if not match:
        raise ValueError(f"cannot parse checkpoint update from {path}")
    return int(match.group(1))


def final_update(train_dir: str | Path = PILOT16_TRAIN_FINAL_DIR) -> int:
    payload = _read_json(Path(train_dir) / "async_train_summary.json")
    return int(payload.get("policy_version") or -1)


def run_pilot16_ppo_row(
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
    selection_subset: str = "",
) -> dict[str, Any]:
    policy = load_async_block_policy(model_path)
    candidate_generator_mode, search_control_mode = infer_block_modes(policy.model)
    started = time.perf_counter()
    row = run_block_model_policy(
        model=policy.model,
        bundle=bundle,
        seed=seed,
        eval_budget=eval_budget,
        block_size=block_size,
        candidate_generator_mode=candidate_generator_mode,
        search_control_mode=search_control_mode,
    )
    elapsed = time.perf_counter() - started
    row.update(
        {
            "algorithm": algorithm,
            "elapsed_seconds": float(elapsed),
            "runtime_target_seconds": 0.0,
            "model_label": model_label,
            "checkpoint_update": checkpoint_update_value,
            "eval_mode": "budget",
            "bundle_role": bundle_role,
            "scale": scale_from_bundle(bundle),
            "selection_subset": selection_subset,
            "actual_eval_fraction": float(row["actual_evals"]) / max(float(eval_budget), 1.0),
            "candidate_generator_mode": int(candidate_generator_mode),
            "search_control_mode": int(search_control_mode),
            "meta_q_ratio": "",
            "meta_threshold_ratio": "",
            "meta_exploration_ratio": "",
        }
    )
    validate_row(row, expected_budget=eval_budget, require_full_budget=False)
    return normalize_extended_row(row)


def run_block_model_policy(
    *,
    model: BlockActorCritic,
    bundle: str,
    seed: int,
    eval_budget: int,
    block_size: int,
    candidate_generator_mode: bool,
    search_control_mode: bool,
) -> dict[str, Any]:
    env = BlockAlnsEnv(
        bundle,
        seed=int(seed),
        eval_budget=int(eval_budget),
        block_size=int(block_size),
        candidate_generator_mode=bool(candidate_generator_mode),
        search_control_mode=bool(search_control_mode),
    )
    destroy_counts: dict[str, int] = {}
    repair_counts: dict[str, int] = {}
    q_counts: dict[str, int] = {}
    candidate_nondefault_count = 0
    search_noncontinue_count = 0
    stop_requested_count = 0
    try:
        obs, info = env.reset(seed=int(seed))
        terminated = False
        truncated = False
        best_response = env.last_response or {}
        last_info = env.last_response or {}
        while not (terminated or truncated):
            decision = model.act(obs, deterministic=True, masks=info.get("action_mask"))
            obs, _reward, terminated, truncated, info = env.step(decision["action"])
            trace = dict(info.get("trace", {}) or {})
            _inc(destroy_counts, str(trace.get("block_requested_destroy_id") or trace.get("destroy_id") or ""))
            _inc(repair_counts, str(trace.get("block_requested_repair_id") or trace.get("repair_id") or ""))
            q_value = trace.get("block_requested_q_ratio", trace.get("q_ratio"))
            if q_value not in (None, ""):
                _inc(q_counts, f"{float(q_value):.6f}")
            candidate = str(trace.get("block_requested_candidate_generator", "default") or "default")
            search_control = str(trace.get("search_control", "continue") or "continue")
            candidate_nondefault_count += int(candidate != "default")
            search_noncontinue_count += int(search_control != "continue")
            stop_requested_count += int(bool(trace.get("search_control_stop_requested")) or search_control == "stop")
            if float(info.get("best_obj", float("inf"))) <= float(best_response.get("best_obj", float("inf"))) + 1e-9:
                best_response = info
            last_info = info
        row = normalize_result_row(
            {
                "algorithm": "ppo_block",
                "bundle": bundle,
                "seed": int(seed),
                "eval_budget": int(eval_budget),
                "best_obj": float(last_info.get("best_obj", best_response.get("best_obj", 0.0))),
                "actual_evals": int(last_info.get("actual_evals", 0)),
                "candidate_scores": int(last_info.get("candidate_scores", 0)),
                "repair_delta_count": int(last_info.get("repair_delta_count", 0)),
                "operator_base_id": str((last_info.get("trace", {}) or {}).get("operator_base_id", "")),
                "control_mode": str((last_info.get("trace", {}) or {}).get("control_mode", "")),
                "violation_count": int(best_response.get("violation_count", 1)),
                "feasible": int(best_response.get("violation_count", 1)) == 0,
                "solution_signature_hash": solution_signature_hash(best_response.get("solution", {})),
                "operator_counts": {},
                "destroy_counts": destroy_counts,
                "repair_counts": repair_counts,
                "q_ratio_counts": q_counts,
                "worker_python_executable": str((last_info.get("trace", {}) or {}).get("worker_python_executable", "")),
                "worker_python_version": str((last_info.get("trace", {}) or {}).get("worker_python_version", "")),
                "worker_numpy_version": str((last_info.get("trace", {}) or {}).get("worker_numpy_version", "")),
            }
        )
        row["candidate_nondefault_count"] = candidate_nondefault_count
        row["search_noncontinue_count"] = search_noncontinue_count
        row["stop_requested_count"] = stop_requested_count
        return row
    finally:
        env.close()


def run_baseline_row(
    *,
    algorithm: str,
    bundle: str,
    seed: int,
    eval_budget: int,
    block_size: int,
    bundle_role: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    if algorithm == "alpha_ucb_block":
        row = run_alpha_ucb_block_policy(bundle, seed=seed, eval_budget=eval_budget, block_size=block_size)
    elif algorithm == "random_block":
        row = run_random_block_policy(bundle, seed=seed, eval_budget=eval_budget, block_size=block_size)
    elif algorithm == "official_winner_kernel":
        row = run_official_winner_kernel(
            bundle,
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=900.0,
        )
    elif algorithm == "alpha_ucb_meta_tuned":
        row = run_alpha_ucb_meta_row(
            bundle=bundle,
            seed=seed,
            eval_budget=eval_budget,
            block_size=block_size,
            q_ratio=TUNED_META[0],
            threshold_ratio=TUNED_META[1],
            exploration_ratio=TUNED_META[2],
            bundle_role=bundle_role,
            model_label="alpha_ucb_meta_tuned",
        )
    elif algorithm == "scikit-opt-SA":
        row = run_sa_row(
            bundle=bundle,
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=900.0,
            bundle_role=bundle_role,
        )
    else:
        raise ValueError(f"unknown baseline algorithm: {algorithm}")
    elapsed = time.perf_counter() - started
    row.update(
        {
            "algorithm": algorithm,
            "elapsed_seconds": float(row.get("elapsed_seconds") or elapsed),
            "runtime_target_seconds": 0.0,
            "model_label": "",
            "checkpoint_update": -1,
            "eval_mode": "budget",
            "bundle_role": bundle_role,
            "scale": scale_from_bundle(bundle),
            "selection_subset": "",
            "actual_eval_fraction": float(row["actual_evals"]) / max(float(eval_budget), 1.0),
            "candidate_generator_mode": 0,
            "search_control_mode": 0,
            "candidate_nondefault_count": 0,
            "search_noncontinue_count": 0,
            "stop_requested_count": 0,
            "meta_q_ratio": TUNED_META[0] if algorithm == "alpha_ucb_meta_tuned" else "",
            "meta_threshold_ratio": TUNED_META[1] if algorithm == "alpha_ucb_meta_tuned" else "",
            "meta_exploration_ratio": TUNED_META[2] if algorithm == "alpha_ucb_meta_tuned" else "",
        }
    )
    validate_row(row, expected_budget=eval_budget, require_full_budget=True)
    return normalize_extended_row(row)


def screen_checkpoints(
    *,
    output_dir: str | Path,
    checkpoints: list[Path],
    bundles: list[str],
    eval_budget: int = EVAL_BUDGET,
    block_size: int = BLOCK_SIZE,
    resume: bool = True,
) -> list[dict[str, Any]]:
    out = Path(output_dir)
    selected = selection_bundles(bundles)
    partial = out / "pilot17_checkpoint_screen_rows.partial.csv"
    rows = load_rows(partial) if resume else []
    existing = {_model_eval_key(row) for row in rows}
    for path in checkpoints:
        update = checkpoint_update(path)
        for bundle in selected:
            key = (bundle, 1, f"checkpoint_{update:04d}", update)
            if key in existing:
                continue
            row = run_pilot16_ppo_row(
                model_path=path,
                bundle=bundle,
                seed=1,
                eval_budget=eval_budget,
                block_size=block_size,
                algorithm="ppo_block_screen",
                model_label=f"checkpoint_{update:04d}",
                checkpoint_update_value=update,
                bundle_role="selection",
                selection_subset="scale_03",
            )
            rows.append(row)
            existing.add(key)
            write_rows(partial, rows)
    ranking = rank_models(rows, final_update=final_update())
    write_rows(out / "pilot17_checkpoint_screen_rows.csv", rows)
    write_csv(out / "pilot17_checkpoint_screen_ranking.csv", ranking, ranking_fields())
    return ranking


def refine_checkpoints(
    *,
    output_dir: str | Path,
    screen_ranking: list[dict[str, Any]],
    bundles: list[str],
    eval_budget: int = EVAL_BUDGET,
    block_size: int = BLOCK_SIZE,
    top_k: int = 5,
    resume: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    out = Path(output_dir)
    selected = selection_bundles(bundles)
    candidates: list[tuple[str, Path, int]] = []
    for row in screen_ranking[: int(top_k)]:
        update = int(row["checkpoint_update"])
        candidates.append((str(row["model_label"]), checkpoint_path(update), update))
    f_update = final_update()
    candidates.append(("final", PILOT16_FINAL_MODEL, f_update))
    partial = out / "pilot17_checkpoint_refine_rows.partial.csv"
    rows = load_rows(partial) if resume else []
    existing = {_model_eval_key(row) for row in rows}
    for label, path, update in candidates:
        for bundle in selected:
            for seed in (1, 2, 3):
                key = (bundle, seed, label, update)
                if key in existing:
                    continue
                row = run_pilot16_ppo_row(
                    model_path=path,
                    bundle=bundle,
                    seed=seed,
                    eval_budget=eval_budget,
                    block_size=block_size,
                    algorithm="ppo_block_refine",
                    model_label=label,
                    checkpoint_update_value=update,
                    bundle_role="selection",
                    selection_subset="scale_03",
                )
                rows.append(row)
                existing.add(key)
                write_rows(partial, rows)
    ranking = rank_models(rows, final_update=f_update)
    if not ranking:
        raise RuntimeError("HALT_PILOT17_EVAL: no refined checkpoint rows")
    write_rows(out / "pilot17_checkpoint_refine_rows.csv", rows)
    write_csv(out / "pilot17_checkpoint_refine_ranking.csv", ranking, ranking_fields())
    return ranking[0], ranking


def run_formal_comparison(
    *,
    output_dir: str | Path,
    best_model: dict[str, Any],
    bundles: list[str],
    eval_budget: int = EVAL_BUDGET,
    block_size: int = BLOCK_SIZE,
    resume: bool = True,
) -> list[dict[str, Any]]:
    out = Path(output_dir)
    partial = out / "pilot17_comparison_rows.partial.csv"
    rows = load_rows(partial) if resume else []
    existing = {_comparison_key(row) for row in rows}
    best_path = Path(str(best_model["model_path"]))
    best_update = int(best_model["checkpoint_update"])
    if not best_path.is_file():
        raise FileNotFoundError(f"best model missing: {best_path}")
    tasks = formal_tasks(best_path=best_path, best_update=best_update, final_update_value=final_update(), bundles=bundles)
    for task in tasks:
        key = (
            str(task["algorithm"]),
            str(task["bundle"]),
            int(task["seed"]),
            str(task.get("model_label", "")),
            int(task.get("checkpoint_update") or -1),
        )
        if key in existing:
            continue
        if str(task["algorithm"]).startswith("ppo_block"):
            row = run_pilot16_ppo_row(
                model_path=task["model_path"],
                bundle=task["bundle"],
                seed=task["seed"],
                eval_budget=eval_budget,
                block_size=block_size,
                algorithm=task["algorithm"],
                model_label=task["model_label"],
                checkpoint_update_value=task["checkpoint_update"],
                bundle_role="formal",
            )
        else:
            row = run_baseline_row(
                algorithm=task["algorithm"],
                bundle=task["bundle"],
                seed=task["seed"],
                eval_budget=eval_budget,
                block_size=block_size,
                bundle_role="formal",
            )
        rows.append(row)
        existing.add(key)
        write_rows(partial, rows)
    rows.sort(key=lambda row: (int(row["scale"]), str(row["bundle"]), int(row["seed"]), str(row["algorithm"]), str(row["model_label"])))
    write_rows(out / "pilot17_comparison_rows.csv", rows)
    return rows


def formal_tasks(*, best_path: Path, best_update: int, final_update_value: int, bundles: list[str]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for bundle in bundles:
        for seed in MAIN_SEEDS:
            tasks.append(
                {
                    "algorithm": "ppo_block_best",
                    "bundle": bundle,
                    "seed": seed,
                    "model_path": str(best_path),
                    "model_label": "best",
                    "checkpoint_update": best_update,
                }
            )
            for baseline in ("alpha_ucb_block", "alpha_ucb_meta_tuned"):
                tasks.append({"algorithm": baseline, "bundle": bundle, "seed": seed})
        for seed in SECONDARY_SEEDS:
            tasks.append(
                {
                    "algorithm": "ppo_block_final",
                    "bundle": bundle,
                    "seed": seed,
                    "model_path": str(PILOT16_FINAL_MODEL),
                    "model_label": "final",
                    "checkpoint_update": final_update_value,
                }
            )
            for baseline in ("random_block", "official_winner_kernel", "scikit-opt-SA"):
                tasks.append({"algorithm": baseline, "bundle": bundle, "seed": seed})
    return tasks


def summarize_and_write(
    *,
    output_dir: str | Path,
    bundles: list[str],
    best_model: dict[str, Any],
    screen_ranking: list[dict[str, Any]],
    refine_ranking: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
    eval_budget: int,
    block_size: int,
) -> dict[str, Any]:
    out = Path(output_dir)
    algorithm_rows = algorithm_summary(comparison_rows)
    scale_rows = scale_summary(comparison_rows, left_algorithm="ppo_block_best")
    paired_rows = paired_relative_rows(comparison_rows, left_algorithm="ppo_block_best")
    wilcoxon = wilcoxon_rows(comparison_rows, left_algorithm="ppo_block_best")
    runtime_rows = runtime_summary(comparison_rows)
    integrity = integrity_summary(comparison_rows, expected_budget=eval_budget)
    verdict = classify_verdict(scale_rows=scale_rows, paired_rows=paired_rows, integrity=integrity)
    manifest = build_eval_manifest(bundles)
    summary = {
        "schema_version": "resetp-pilot17-allscale-eval.v1",
        "status": verdict["verdict"],
        "eval_budget": int(eval_budget),
        "block_size": int(block_size),
        "bundle_count": len(bundles),
        "scales": sorted({scale_from_bundle(bundle) for bundle in bundles}),
        "selection_bundles": selection_bundles(bundles),
        "best_model": best_model,
        "screen_top5": screen_ranking[:5],
        "refine_ranking": refine_ranking,
        "integrity": integrity,
        "algorithm_summary": algorithm_rows,
        "scale_summary": scale_rows,
        "paired_relative": paired_rows,
        "wilcoxon": wilcoxon,
        "runtime_summary": runtime_rows,
        "verdict": verdict,
        "same_machine_note": "All percentages are x86 same-machine, same-budget relative values; no M1 absolute objective comparison is made.",
        "heldout_caveat": "Only 15 generated all-scale three-shift bundles are present locally. Checkpoint selection uses the *-03 subset; formal comparison reports all 15 bundles but is not an independent held-out benchmark.",
    }
    write_json(out / "pilot17_eval_manifest.json", manifest)
    write_csv(out / "pilot17_algorithm_summary.csv", algorithm_rows, algorithm_summary_fields())
    write_csv(out / "pilot17_scale_summary.csv", scale_rows, scale_summary_fields())
    write_csv(out / "pilot17_paired_relative.csv", paired_rows, paired_fields())
    write_csv(out / "pilot17_wilcoxon.csv", wilcoxon, wilcoxon_fields())
    write_csv(out / "pilot17_runtime_summary.csv", runtime_rows, runtime_fields())
    write_json(out / "pilot17_summary.json", summary)
    (out / "pilot17_final_report.md").write_text(report_markdown(summary), encoding="utf-8")
    return summary


def build_eval_manifest(bundles: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "resetp-pilot17-allscale-eval.v1",
        "train": [],
        "held_out": [],
        "formal_eval": list(bundles),
        "note": "Pilot17 evaluates the existing 15 generated all-scale three-shift bundles. No extra independent all-scale held-out bundles exist locally.",
    }


def run_all(args: argparse.Namespace) -> dict[str, Any]:
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    bundles = load_allscale_bundles(args.manifest)
    checkpoints = discover_checkpoints()
    screen = load_ranking(out / "pilot17_checkpoint_screen_ranking.csv")
    if not screen or not args.resume:
        screen = screen_checkpoints(output_dir=out, checkpoints=checkpoints, bundles=bundles, eval_budget=args.eval_budget, block_size=args.block_size, resume=args.resume)
    refine = load_ranking(out / "pilot17_checkpoint_refine_ranking.csv")
    if not refine or not args.resume:
        best_model, refine = refine_checkpoints(output_dir=out, screen_ranking=screen, bundles=bundles, eval_budget=args.eval_budget, block_size=args.block_size, resume=args.resume)
    else:
        best_model = refine[0]
    rows = load_rows(out / "pilot17_comparison_rows.csv")
    if not rows or not args.resume:
        rows = run_formal_comparison(output_dir=out, best_model=best_model, bundles=bundles, eval_budget=args.eval_budget, block_size=args.block_size, resume=args.resume)
    return summarize_and_write(
        output_dir=out,
        bundles=bundles,
        best_model=best_model,
        screen_ranking=screen,
        refine_ranking=refine,
        comparison_rows=rows,
        eval_budget=args.eval_budget,
        block_size=args.block_size,
    )


def validate_row(row: dict[str, Any], *, expected_budget: int, require_full_budget: bool) -> None:
    issues = row_gate_issues(row, expected_budget=expected_budget, require_full_budget=require_full_budget)
    if issues:
        raise RuntimeError(f"HALT_PILOT17_EVAL row failed gates {issues}: {row_id(row)}")


def row_gate_issues(row: dict[str, Any], *, expected_budget: int, require_full_budget: bool) -> list[str]:
    issues: list[str] = []
    worker = str(Path(str(row.get("worker_python_executable", ""))).resolve())
    if worker != str(Path(DEFAULT_WORKER).resolve()):
        issues.append("worker_python")
    if str(row.get("worker_numpy_version")) != REQUIRED_NUMPY:
        issues.append("worker_numpy")
    if int(row.get("violation_count") or 0) != 0 or not _bool(row.get("feasible")):
        issues.append("feasibility")
    if not math.isfinite(float(row.get("best_obj", math.nan))):
        issues.append("best_obj")
    if float(row.get("elapsed_seconds") or 0.0) <= 0.0:
        issues.append("elapsed_seconds")
    actual = int(row.get("actual_evals") or 0)
    if actual <= 0 or actual > int(expected_budget):
        issues.append("actual_evals_range")
    if require_full_budget and actual != int(expected_budget):
        issues.append("actual_evals")
    return issues


def integrity_summary(rows: list[dict[str, Any]], *, expected_budget: int) -> dict[str, Any]:
    failures = []
    ppo_underbudget = []
    for row in rows:
        require_full = not str(row.get("algorithm", "")).startswith("ppo_block")
        issues = row_gate_issues(row, expected_budget=expected_budget, require_full_budget=require_full)
        if issues:
            failures.append({"row": row_id(row), "issues": issues})
        if str(row.get("algorithm", "")).startswith("ppo_block") and int(row.get("actual_evals") or 0) != int(expected_budget):
            ppo_underbudget.append(
                {
                    "row": row_id(row),
                    "actual_evals": int(row.get("actual_evals") or 0),
                    "eval_budget": int(expected_budget),
                }
            )
    return {
        "ok": not failures,
        "row_count": len(rows),
        "failures": failures,
        "ppo_underbudget_count": len(ppo_underbudget),
        "ppo_underbudget_rows": ppo_underbudget[:20],
    }


def rank_models(rows: list[dict[str, Any]], *, final_update: int | None = None) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("model_label", "")), int(row.get("checkpoint_update") or -1))].append(row)
    ranked = []
    for (label, update), group in grouped.items():
        values = [float(row["best_obj"]) for row in group]
        under = [float(row.get("actual_eval_fraction") or 0.0) for row in group]
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
                "mean_actual_eval_fraction": statistics.fmean(under),
                "model_path": str(PILOT16_FINAL_MODEL if label == "final" else checkpoint_path(update)),
            }
        )
    final_update_value = int(final_update) if final_update is not None else -1
    ranked.sort(
        key=lambda row: (
            float(row["mean_best_obj"]),
            0 if row["model_label"] == "final" else 1,
            -int(row["checkpoint_update"] if row["checkpoint_update"] != -1 else final_update_value),
        )
    )
    for idx, row in enumerate(ranked, start=1):
        row["rank"] = idx
    return ranked


def algorithm_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(int(row["scale"]), str(row["algorithm"]))].append(row)
    out = []
    for (scale, algorithm), group in sorted(grouped.items()):
        values = [float(row["best_obj"]) for row in group]
        out.append(
            {
                "scale": scale,
                "algorithm": algorithm,
                "n": len(group),
                "mean_best_obj": statistics.fmean(values),
                "std_best_obj": statistics.stdev(values) if len(values) > 1 else 0.0,
                "min_best_obj": min(values),
                "max_best_obj": max(values),
                "mean_actual_evals": statistics.fmean(int(row["actual_evals"]) for row in group),
                "mean_elapsed_seconds": statistics.fmean(float(row["elapsed_seconds"]) for row in group),
                "feasibility_rate": sum(1 for row in group if _bool(row["feasible"])) / max(1, len(group)),
            }
        )
    return out


def paired_relative_rows(rows: list[dict[str, Any]], *, left_algorithm: str) -> list[dict[str, Any]]:
    index = {(str(row["bundle"]), int(row["seed"]), str(row["algorithm"])): row for row in rows}
    bundles = sorted({str(row["bundle"]) for row in rows})
    algorithms = sorted({str(row["algorithm"]) for row in rows if str(row["algorithm"]) != left_algorithm})
    out = []
    for bundle in bundles:
        for baseline in algorithms:
            values = []
            wins = 0
            for seed in sorted({int(row["seed"]) for row in rows if str(row["bundle"]) == bundle and str(row["algorithm"]) == left_algorithm}):
                left = index.get((bundle, seed, left_algorithm))
                base = index.get((bundle, seed, baseline))
                if left is None or base is None:
                    continue
                base_obj = float(base["best_obj"])
                left_obj = float(left["best_obj"])
                if abs(base_obj) <= 1e-12:
                    continue
                values.append((base_obj - left_obj) / base_obj * 100.0)
                wins += int(left_obj < base_obj)
            if values:
                out.append(
                    {
                        "scale": scale_from_bundle(bundle),
                        "bundle": bundle,
                        "left_algorithm": left_algorithm,
                        "baseline_algorithm": baseline,
                        "paired_n": len(values),
                        "wins": wins,
                        "mean_relative_pct": statistics.fmean(values),
                        "std_relative_pct": statistics.stdev(values) if len(values) > 1 else 0.0,
                        "min_relative_pct": min(values),
                        "max_relative_pct": max(values),
                    }
                )
    return out


def scale_summary(rows: list[dict[str, Any]], *, left_algorithm: str) -> list[dict[str, Any]]:
    paired = paired_relative_rows(rows, left_algorithm=left_algorithm)
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in paired:
        grouped[(int(row["scale"]), str(row["baseline_algorithm"]))].append(row)
    out = []
    for (scale, baseline), group in sorted(grouped.items()):
        values = [float(row["mean_relative_pct"]) for row in group]
        wins = sum(int(row["wins"]) for row in group)
        n = sum(int(row["paired_n"]) for row in group)
        out.append(
            {
                "scale": scale,
                "left_algorithm": left_algorithm,
                "baseline_algorithm": baseline,
                "bundle_count": len(group),
                "paired_n": n,
                "wins": wins,
                "mean_relative_pct": statistics.fmean(values),
                "min_bundle_relative_pct": min(values),
                "max_bundle_relative_pct": max(values),
            }
        )
    return out


def wilcoxon_rows(rows: list[dict[str, Any]], *, left_algorithm: str) -> list[dict[str, Any]]:
    index = {(str(row["bundle"]), int(row["seed"]), str(row["algorithm"])): row for row in rows}
    grouped: dict[tuple[int, str], list[float]] = defaultdict(list)
    baselines = sorted({str(row["algorithm"]) for row in rows if str(row["algorithm"]) != left_algorithm})
    for bundle in sorted({str(row["bundle"]) for row in rows}):
        for baseline in baselines:
            for seed in MAIN_SEEDS:
                left = index.get((bundle, seed, left_algorithm))
                base = index.get((bundle, seed, baseline))
                if left is None or base is None:
                    continue
                grouped[(scale_from_bundle(bundle), baseline)].append(float(base["best_obj"]) - float(left["best_obj"]))
    out = []
    for (scale, baseline), diffs in sorted(grouped.items()):
        if len(diffs) >= 5:
            try:
                result = wilcoxon(diffs, alternative="greater", zero_method="wilcox", method="auto")
                statistic: float | str = float(result.statistic)
                p_value: float | str = float(result.pvalue)
            except ValueError:
                statistic = ""
                p_value = ""
            used = True
        else:
            statistic = ""
            p_value = ""
            used = False
        out.append(
            {
                "scale": scale,
                "left_algorithm": left_algorithm,
                "baseline_algorithm": baseline,
                "paired_n": len(diffs),
                "wins": sum(1 for diff in diffs if diff > 0.0),
                "statistic": statistic,
                "p_value": p_value,
                "alternative": "greater",
                "used_for_gate": used,
            }
        )
    return out


def runtime_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(int(row["scale"]), str(row["algorithm"]))].append(row)
    out = []
    for (scale, algorithm), group in sorted(grouped.items()):
        out.append(
            {
                "scale": scale,
                "algorithm": algorithm,
                "n": len(group),
                "mean_elapsed_seconds": statistics.fmean(float(row["elapsed_seconds"]) for row in group),
                "min_elapsed_seconds": min(float(row["elapsed_seconds"]) for row in group),
                "max_elapsed_seconds": max(float(row["elapsed_seconds"]) for row in group),
                "mean_actual_evals": statistics.fmean(int(row["actual_evals"]) for row in group),
                "mean_actual_eval_fraction": statistics.fmean(float(row.get("actual_eval_fraction") or 0.0) for row in group),
            }
        )
    return out


def classify_verdict(
    *,
    scale_rows: list[dict[str, Any]],
    paired_rows: list[dict[str, Any]],
    integrity: dict[str, Any],
) -> dict[str, Any]:
    if not integrity.get("ok"):
        return {"verdict": "HALT_DR", "reason": "Integrity gates failed; no performance verdict."}
    scales = sorted({int(row["scale"]) for row in scale_rows})
    baselines = sorted({str(row["baseline_algorithm"]) for row in scale_rows})
    external_rows = [
        row for row in scale_rows
        if not str(row["baseline_algorithm"]).startswith("ppo_block")
    ]
    strongest_by_scale: dict[int, dict[str, Any]] = {}
    for scale in scales:
        candidates = [row for row in external_rows if int(row["scale"]) == scale]
        if not candidates:
            candidates = [row for row in scale_rows if int(row["scale"]) == scale]
        strongest_by_scale[scale] = min(candidates, key=lambda row: float(row["mean_relative_pct"]))
    mean_vs_second = statistics.fmean(float(row["mean_relative_pct"]) for row in strongest_by_scale.values())
    min_vs_second = min(float(row["mean_relative_pct"]) for row in strongest_by_scale.values())
    target = mean_vs_second >= 10.0 and min_vs_second >= 0.0
    acceptable = min_vs_second >= 0.0 and all(
        float(strongest_by_scale[scale]["mean_relative_pct"]) > 0.0 for scale in (100, 150, 200) if scale in strongest_by_scale
    )
    underbudget = int(integrity.get("ppo_underbudget_count") or 0)
    if target and underbudget == 0:
        verdict = "TARGET_PASS"
        reason = "DR beat the strongest same-budget baseline by >=10% on average and no scale was negative."
    elif target:
        verdict = "TARGET_PASS_WITH_UNDERBUDGET_CAVEAT"
        reason = "DR met the relative target but some PPO rows stopped before the full budget; treat as caveated."
    elif acceptable:
        verdict = "ACCEPTABLE_PASS"
        reason = "DR was non-worse across scales and positive on the main large scales, but did not reach +10% average."
    else:
        verdict = "WEAK"
        reason = "DR did not meet the all-scale non-worse or +10% target against the strongest baseline."
    return {
        "verdict": verdict,
        "reason": reason,
        "mean_relative_pct_vs_second": mean_vs_second,
        "min_scale_relative_pct_vs_second": min_vs_second,
        "strongest_baseline_by_scale": strongest_by_scale,
        "baselines": baselines,
        "target_baseline_rule": "Target/second-place gate excludes ppo_block_final; final is reported as a DR variant, not an external baseline.",
    }


def scale_from_bundle(bundle: str | Path) -> int:
    text = str(bundle)
    match = re.search(r"(\d+)c", text)
    if match:
        return int(match.group(1))
    match = re.search(r"E-UK(\d+)_", text)
    if match:
        return int(match.group(1))
    raise ValueError(f"cannot infer scale from bundle path: {bundle}")


def checkpoint_path(update: int) -> Path:
    return PILOT16_CHECKPOINT_DIR / f"async_block_ppo_update_{int(update):04d}.pt"


def normalize_extended_row(row: dict[str, Any]) -> dict[str, Any]:
    base = normalize_result_row(row)
    out = {**base}
    for key in EXTRA_COLUMNS:
        out[key] = row.get(key, "")
    out["elapsed_seconds"] = float(out.get("elapsed_seconds") or 0.0)
    out["runtime_target_seconds"] = float(out.get("runtime_target_seconds") or 0.0)
    out["checkpoint_update"] = int(out.get("checkpoint_update") or -1)
    out["scale"] = int(out.get("scale") or scale_from_bundle(out["bundle"]))
    out["actual_eval_fraction"] = float(out.get("actual_eval_fraction") or 0.0)
    for key in ("candidate_generator_mode", "search_control_mode", "candidate_nondefault_count", "search_noncontinue_count", "stop_requested_count"):
        out[key] = int(out.get(key) or 0)
    return out


def write_rows(path: str | Path, rows: list[dict[str, Any]]) -> None:
    write_csv(Path(path), rows, RESULT_COLUMNS)


def write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = fieldnames or sorted({key for row in rows for key in row})
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(csv_row(row, fields))


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def load_rows(path: str | Path) -> list[dict[str, Any]]:
    value = Path(path)
    if not value.is_file():
        return []
    with value.open(newline="", encoding="utf-8") as handle:
        rows = []
        for raw in csv.DictReader(handle):
            row = dict(raw)
            for key in ("operator_counts", "destroy_counts", "repair_counts", "q_ratio_counts"):
                if isinstance(row.get(key), str) and row.get(key):
                    row[key] = json.loads(str(row[key]))
            rows.append(normalize_extended_row(row))
        return rows


def load_ranking(path: str | Path) -> list[dict[str, Any]]:
    value = Path(path)
    if not value.is_file():
        return []
    with value.open(newline="", encoding="utf-8") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    for row in rows:
        for key in ("rank", "checkpoint_update", "n"):
            row[key] = int(float(row[key]))
        for key in ("mean_best_obj", "std_best_obj", "min_best_obj", "max_best_obj", "mean_actual_eval_fraction"):
            row[key] = float(row[key])
    return rows


def csv_row(row: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    out = {}
    for key in fields:
        value = row.get(key, "")
        if key == "feasible":
            value = int(_bool(value))
        elif isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        out[key] = value
    return out


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _selection_key(row: dict[str, Any]) -> tuple[str, str, int, str, int]:
    return (
        str(row["algorithm"]),
        str(row["bundle"]),
        int(row["seed"]),
        str(row.get("model_label", "")),
        int(row.get("checkpoint_update") or -1),
    )


def _comparison_key(row: dict[str, Any]) -> tuple[str, str, int, str, int]:
    return _selection_key(row)


def _model_eval_key(row: dict[str, Any]) -> tuple[str, int, str, int]:
    return (
        str(row["bundle"]),
        int(row["seed"]),
        str(row.get("model_label", "")),
        int(row.get("checkpoint_update") or -1),
    )


def row_id(row: dict[str, Any]) -> str:
    return f"{row.get('algorithm')}|{row.get('bundle')}|seed{row.get('seed')}|{row.get('model_label')}|u{row.get('checkpoint_update')}"


def _inc(counts: dict[str, int], key: str) -> None:
    if key:
        counts[key] = int(counts.get(key, 0)) + 1


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes"}


def ranking_fields() -> list[str]:
    return ["rank", "model_label", "checkpoint_update", "n", "mean_best_obj", "std_best_obj", "min_best_obj", "max_best_obj", "mean_actual_eval_fraction", "model_path"]


def algorithm_summary_fields() -> list[str]:
    return ["scale", "algorithm", "n", "mean_best_obj", "std_best_obj", "min_best_obj", "max_best_obj", "mean_actual_evals", "mean_elapsed_seconds", "feasibility_rate"]


def scale_summary_fields() -> list[str]:
    return ["scale", "left_algorithm", "baseline_algorithm", "bundle_count", "paired_n", "wins", "mean_relative_pct", "min_bundle_relative_pct", "max_bundle_relative_pct"]


def paired_fields() -> list[str]:
    return ["scale", "bundle", "left_algorithm", "baseline_algorithm", "paired_n", "wins", "mean_relative_pct", "std_relative_pct", "min_relative_pct", "max_relative_pct"]


def wilcoxon_fields() -> list[str]:
    return ["scale", "left_algorithm", "baseline_algorithm", "paired_n", "wins", "statistic", "p_value", "alternative", "used_for_gate"]


def runtime_fields() -> list[str]:
    return ["scale", "algorithm", "n", "mean_elapsed_seconds", "min_elapsed_seconds", "max_elapsed_seconds", "mean_actual_evals", "mean_actual_eval_fraction"]


def report_markdown(summary: dict[str, Any]) -> str:
    verdict = summary["verdict"]
    lines = [
        "# Pilot17 All-Scale DR-ALNS Evaluation",
        "",
        f"Status: `{verdict['verdict']}`.",
        f"Reason: {verdict['reason']}",
        "",
        f"Budget: eval_budget `{summary['eval_budget']}`, block_size `{summary['block_size']}`.",
        f"Best model: `{summary['best_model']['model_label']}` update `{summary['best_model']['checkpoint_update']}`.",
        "",
        "This is x86 same-machine, same-budget relative evaluation only. It is not an M1 absolute-number comparison.",
        "",
        summary["heldout_caveat"],
        "",
        "## Scale Gate",
        "",
        "| scale | strongest baseline | mean relative % vs strongest | min bundle % | wins/n |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for scale, row in sorted(verdict["strongest_baseline_by_scale"].items(), key=lambda item: int(item[0])):
        lines.append(
            f"| {scale} | {row['baseline_algorithm']} | {float(row['mean_relative_pct']):.3f} | "
            f"{float(row['min_bundle_relative_pct']):.3f} | {int(row['wins'])}/{int(row['paired_n'])} |"
        )
    lines.extend(["", "## Underbudget", ""])
    lines.append(
        f"PPO rows that stopped before the full budget: `{summary['integrity']['ppo_underbudget_count']}`. "
        "If this is nonzero, any positive result is caveated because the learned stop head changed budget use."
    )
    lines.extend(["", "## Baselines", ""])
    lines.append("Formal comparison includes `alpha_ucb_block`, tuned `alpha_ucb_meta_tuned`, `random_block`, `scikit-opt-SA`, and `official_winner_kernel`.")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Pilot17 all-scale DR-ALNS evaluation.")
    parser.add_argument("--manifest", default=str(ALLSCALE_MANIFEST))
    parser.add_argument("--output-dir", default=str(PILOT17_DIR))
    parser.add_argument("--eval-budget", type=int, default=EVAL_BUDGET)
    parser.add_argument("--block-size", type=int, default=BLOCK_SIZE)
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    summary = run_all(parse_args(argv))
    print(f"PILOT17_EVAL_DONE status={summary['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
