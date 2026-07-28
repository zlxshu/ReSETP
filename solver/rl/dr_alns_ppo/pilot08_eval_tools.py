from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import wilcoxon

from .baselines import RESULT_COLUMNS as BASE_RESULT_COLUMNS
from .bundle_manifest import SCHEMA_VERSION, validate_manifest
from .evaluate_policy import _evaluate_one_task


PILOT08_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot08")
TRAIN_FINAL_DIR = PILOT08_DIR / "train_final"
EVAL_FINAL_DIR = PILOT08_DIR / "eval_final"
FINAL_MODEL = TRAIN_FINAL_DIR / "async_block_ppo_model.pt"
CHECKPOINT_DIR = TRAIN_FINAL_DIR / "checkpoints"
TRAIN_BUNDLE = "models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113"
HELD_OUT_BUNDLE = "models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113"
FORMAL_BUNDLE = "models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113"
DEFAULT_WORKER = r"C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe"
REQUIRED_NUMPY = "2.3.5"
BLOCK_SIZE = 32
TARGET_SECONDS = 900.0
TIMED_EVAL_CAP = 1_000_000
TIMED_MIN_RATIO = 0.90
TIMED_MAX_RATIO = 1.20

EXTRA_COLUMNS = [
    "elapsed_seconds",
    "runtime_target_seconds",
    "model_label",
    "checkpoint_update",
    "eval_mode",
    "bundle_role",
]
RESULT_COLUMNS = [*BASE_RESULT_COLUMNS, *EXTRA_COLUMNS]


def build_eval_manifest() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "train": [TRAIN_BUNDLE],
        "held_out": [HELD_OUT_BUNDLE],
        "formal_eval": [FORMAL_BUNDLE],
        "excluded_from_training_reason": {
            "pilot08_eval_only": (
                "Evaluation-only 100c manifest for Pilot08 C. The curriculum training manifest "
                "contains 25c/50c train bundles and must not be reused for 100c verdicts."
            ),
            "same_machine_relative_only": (
                "All reported percentages are same-machine x86 relative comparisons; no M1 "
                "absolute objective comparison is made."
            ),
        },
    }


def write_eval_manifest(path: str | Path, *, root: str | Path = ".") -> dict[str, Any]:
    manifest = build_eval_manifest()
    validate_manifest(manifest, root=root)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def discover_checkpoints(checkpoint_dir: str | Path = CHECKPOINT_DIR) -> list[Path]:
    paths = sorted(Path(checkpoint_dir).glob("async_block_ppo_update_*.pt"), key=checkpoint_update)
    return paths


def checkpoint_update(path: str | Path) -> int:
    match = re.search(r"update_(\d+)", Path(path).stem)
    return int(match.group(1)) if match else -1


def final_model_update(train_dir: str | Path = TRAIN_FINAL_DIR) -> int:
    summary = Path(train_dir) / "async_train_summary.json"
    if not summary.is_file():
        return -1
    payload = json.loads(summary.read_text(encoding="utf-8"))
    return int(payload.get("policy_version") or -1)


def run_policy_row(
    *,
    algorithm: str,
    bundle: str,
    seed: int,
    eval_budget: int,
    model_path: str | Path | None = None,
    model_label: str = "",
    checkpoint_update_value: int | str = "",
    bundle_role: str = "",
    eval_mode: str = "budget",
    runtime_target_seconds: float = 0.0,
    block_size: int = BLOCK_SIZE,
    official_max_runtime_seconds: float = TARGET_SECONDS,
) -> dict[str, Any]:
    worker_args = {
        "model_path": str(model_path or ""),
        "eval_budget": int(eval_budget),
        "base_temperature": 100.0,
        "deterministic": True,
        "official_max_runtime_seconds": float(official_max_runtime_seconds),
        "block_size": int(block_size),
    }
    started = time.perf_counter()
    row = _evaluate_one_task(algorithm, bundle, int(seed), worker_args)
    elapsed = time.perf_counter() - started
    out = _extend_row(
        row,
        elapsed_seconds=elapsed,
        runtime_target_seconds=runtime_target_seconds,
        model_label=model_label,
        checkpoint_update_value=checkpoint_update_value,
        eval_mode=eval_mode,
        bundle_role=bundle_role,
    )
    if model_label == "best" and algorithm == "ppo_block":
        out["algorithm"] = "ppo_block_best"
    elif model_label == "final" and algorithm == "ppo_block":
        out["algorithm"] = "ppo_block_final"
    return normalize_extended_row(out)


def run_sa_row(
    *,
    bundle: str,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    bundle_role: str = "",
    required_python: str = DEFAULT_WORKER,
) -> dict[str, Any]:
    repo_root = Path.cwd()
    script = r"""
import json
import sys
import time
from pathlib import Path

import numpy as np

from setp_solver.check import check_solution
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution, run_candidate, solution_signature_hash

bundle_dir = Path(sys.argv[1])
seed = int(sys.argv[2])
eval_budget = int(sys.argv[3])
max_runtime_seconds = float(sys.argv[4])
started = time.perf_counter()
bundle = load_search_bundle(bundle_dir)
warm = make_shared_initial_solution(bundle)
result = run_candidate(
    "scikit-opt-SA",
    bundle.bundle_dir,
    seed=seed,
    eval_budget=eval_budget,
    max_runtime_seconds=max_runtime_seconds,
    initial_solution=warm,
)
if result.best_solution is None:
    raise RuntimeError("SA returned no solution")
violations = check_solution(result.best_solution, bundle.instance)
payload = {
    "algorithm": "scikit-opt-SA",
    "bundle": str(bundle_dir),
    "seed": seed,
    "eval_budget": eval_budget,
    "best_obj": float(result.best_cost),
    "actual_evals": int(result.evals),
    "candidate_scores": int(result.candidate_scores),
    "repair_delta_count": int(result.repair_delta_count),
    "operator_base_id": "",
    "control_mode": "fair_sa_timed",
    "violation_count": len(violations),
    "feasible": len(violations) == 0,
    "solution_signature_hash": solution_signature_hash(result.best_solution),
    "operator_counts": result.operator_counts,
    "destroy_counts": {},
    "repair_counts": {},
    "q_ratio_counts": {},
    "worker_python_executable": sys.executable,
    "worker_python_version": sys.version,
    "worker_numpy_version": np.__version__,
    "elapsed_seconds": time.perf_counter() - started,
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
"""
    bundle_path = str((repo_root / bundle).resolve())
    started = time.perf_counter()
    proc = subprocess.run(
        [str(Path(required_python).resolve()), "-c", script, bundle_path, str(seed), str(eval_budget), str(max_runtime_seconds)],
        cwd=repo_root,
        env=_worker_env(repo_root),
        text=True,
        capture_output=True,
        check=False,
        timeout=max(60.0, float(max_runtime_seconds) + 180.0),
    )
    wrapper_elapsed = time.perf_counter() - started
    if proc.returncode != 0:
        raise RuntimeError(f"SA subprocess failed rc={proc.returncode}: {proc.stderr[-4000:]}")
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"SA subprocess produced no JSON output; stderr={proc.stderr[-4000:]}")
    row = json.loads(lines[-1])
    row["bundle"] = bundle
    elapsed = float(row.get("elapsed_seconds") or wrapper_elapsed)
    return normalize_extended_row(
        _extend_row(
            row,
            elapsed_seconds=elapsed,
            runtime_target_seconds=max_runtime_seconds,
            model_label="",
            checkpoint_update_value="",
            eval_mode="timed",
            bundle_role=bundle_role,
        )
    )


def calibrate_budget(
    *,
    output_dir: str | Path,
    model_path: str | Path = FINAL_MODEL,
    start_budget: int = 2700,
    target_seconds: float = TARGET_SECONDS,
    max_attempts: int = 3,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    budget = int(start_budget)
    for attempt in range(1, int(max_attempts) + 1):
        row = run_policy_row(
            algorithm="ppo_block",
            bundle=TRAIN_BUNDLE,
            seed=1,
            eval_budget=budget,
            model_path=model_path,
            model_label="final",
            checkpoint_update_value=final_model_update(),
            bundle_role="train",
            eval_mode="calibration",
            runtime_target_seconds=target_seconds,
        )
        row["calibration_attempt"] = attempt
        rows.append(row)
        _write_csv(Path(output_dir) / "pilot08_budget_calibration.csv", rows, fieldnames=[*RESULT_COLUMNS, "calibration_attempt"])
        elapsed = float(row["elapsed_seconds"])
        if elapsed > 0:
            projected = int(round((budget * float(target_seconds) / elapsed) / 100.0) * 100)
            projected = max(100, projected)
        else:
            projected = budget
        if float(target_seconds) * 0.90 <= elapsed <= float(target_seconds) * 1.10:
            break
        budget = projected
    selected = min(rows, key=lambda item: abs(float(item["elapsed_seconds"]) - float(target_seconds)))
    summary = {
        "schema_version": "resetp-pilot08-budget-calibration.v1",
        "target_seconds": float(target_seconds),
        "selected_eval_budget": int(selected["eval_budget"]),
        "selected_elapsed_seconds": float(selected["elapsed_seconds"]),
        "attempts": rows,
    }
    _write_json(Path(output_dir) / "pilot08_budget_calibration.json", summary)
    return summary


def screen_checkpoints(
    *,
    output_dir: str | Path,
    checkpoint_paths: list[Path],
    eval_budget: int = 600,
) -> list[dict[str, Any]]:
    rows = _load_existing_extended(Path(output_dir) / "pilot08_checkpoint_cheap_rows.partial.csv")
    existing = {_selection_key(row) for row in rows}
    for path in checkpoint_paths:
        update = checkpoint_update(path)
        key = ("cheap", "ppo_block", HELD_OUT_BUNDLE, 1, f"checkpoint_{update:04d}", update)
        if key in existing:
            continue
        row = run_policy_row(
            algorithm="ppo_block",
            bundle=HELD_OUT_BUNDLE,
            seed=1,
            eval_budget=eval_budget,
            model_path=path,
            model_label=f"checkpoint_{update:04d}",
            checkpoint_update_value=update,
            bundle_role="held_out",
            eval_mode="cheap",
            runtime_target_seconds=0.0,
        )
        rows.append(row)
        _write_extended_rows(Path(output_dir) / "pilot08_checkpoint_cheap_rows.partial.csv", rows)
    ranking = rank_models(rows)
    _write_csv(Path(output_dir) / "pilot08_checkpoint_cheap_ranking.csv", ranking, fieldnames=_ranking_fields())
    _write_extended_rows(Path(output_dir) / "pilot08_checkpoint_cheap_rows.csv", rows)
    return ranking


def refine_models(
    *,
    output_dir: str | Path,
    candidates: list[tuple[str, Path, int]],
    eval_budget: int,
    final_update: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = _load_existing_extended(Path(output_dir) / "pilot08_checkpoint_refine_rows.partial.csv")
    existing = {_selection_key(row) for row in rows}
    for label, model_path, update in candidates:
        for seed in (1, 2, 3):
            key = ("refine", "ppo_block", HELD_OUT_BUNDLE, seed, label, update)
            if key in existing:
                continue
            row = run_policy_row(
                algorithm="ppo_block",
                bundle=HELD_OUT_BUNDLE,
                seed=seed,
                eval_budget=eval_budget,
                model_path=model_path,
                model_label=label,
                checkpoint_update_value=update,
                bundle_role="held_out",
                eval_mode="refine",
                runtime_target_seconds=TARGET_SECONDS,
            )
            rows.append(row)
            _write_extended_rows(Path(output_dir) / "pilot08_checkpoint_refine_rows.partial.csv", rows)
    ranking = rank_models(rows, final_update=final_update)
    _write_csv(Path(output_dir) / "pilot08_checkpoint_refine_ranking.csv", ranking, fieldnames=_ranking_fields())
    _write_extended_rows(Path(output_dir) / "pilot08_checkpoint_refine_rows.csv", rows)
    if not ranking:
        raise RuntimeError("HALT_C_EVAL: no refined checkpoint rows")
    return ranking[0], ranking


def run_formal_comparison(
    *,
    output_dir: str | Path,
    eval_budget: int,
    best_model_path: str | Path,
    best_label: str,
    best_update: int,
    final_update: int,
    target_seconds: float = TARGET_SECONDS,
) -> list[dict[str, Any]]:
    path = Path(output_dir) / "pilot08_comparison_rows.partial.csv"
    rows = _load_existing_extended(path)
    existing = {_formal_key(row) for row in rows}
    tasks = _formal_tasks(
        eval_budget=eval_budget,
        best_model_path=best_model_path,
        best_label=best_label,
        best_update=best_update,
        final_update=final_update,
        target_seconds=target_seconds,
    )
    for task in tasks:
        key = _formal_task_key(task)
        if key in existing:
            continue
        if task["kind"] == "sa":
            row = run_sa_row(
                bundle=task["bundle"],
                seed=task["seed"],
                eval_budget=TIMED_EVAL_CAP,
                max_runtime_seconds=target_seconds,
                bundle_role=task["bundle_role"],
            )
        else:
            row = run_policy_row(
                algorithm=task["algorithm"],
                bundle=task["bundle"],
                seed=task["seed"],
                eval_budget=task["eval_budget"],
                model_path=task.get("model_path"),
                model_label=task.get("model_label", ""),
                checkpoint_update_value=task.get("checkpoint_update", ""),
                bundle_role=task["bundle_role"],
                eval_mode=task["eval_mode"],
                runtime_target_seconds=task["runtime_target_seconds"],
                official_max_runtime_seconds=target_seconds,
            )
        validate_result_row(row, expected_budget=eval_budget if row["eval_mode"] == "budget" else None)
        rows.append(row)
        _write_extended_rows(path, rows)
    _write_extended_rows(Path(output_dir) / "pilot08_comparison_rows.csv", rows)
    return rows


def summarize_eval(
    *,
    output_dir: str | Path,
    eval_budget: int,
    best_model: dict[str, Any],
    refine_ranking: list[dict[str, Any]],
    cheap_ranking: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    out = Path(output_dir)
    integrity = integrity_summary(comparison_rows, expected_budget=eval_budget)
    if not integrity["ok"]:
        summary = {
            "schema_version": "resetp-pilot08-eval-summary.v1",
            "verdict": "HALT_C_EVAL",
            "reason": "At least one comparison row failed worker, NumPy, budget/timing, feasibility, finite objective, or runtime gates.",
            "integrity": integrity,
        }
        _write_json(out / "pilot08_summary.json", summary)
        (out / "pilot08_final_report.md").write_text(_report_markdown(summary), encoding="utf-8")
        return summary
    algorithm_rows = algorithm_summary(comparison_rows)
    paired = paired_relative_rows(comparison_rows, left_algorithm="ppo_block_best")
    wilcoxon_rows = wilcoxon_rows_for_paired(comparison_rows, left_algorithm="ppo_block_best")
    verdict = classify_verdict(paired, wilcoxon_rows)
    runtime_rows = runtime_summary(comparison_rows)
    summary = {
        "schema_version": "resetp-pilot08-eval-summary.v1",
        "verdict": verdict["verdict"],
        "reason": verdict["reason"],
        "eval_budget_900": int(eval_budget),
        "runtime_target_seconds": TARGET_SECONDS,
        "best_model": best_model,
        "final_model_rank": _find_final_rank(refine_ranking),
        "cheap_top3": cheap_ranking[:3],
        "refine_ranking": refine_ranking,
        "integrity": integrity,
        "runtime_summary": runtime_rows,
        "equal_wall_clock_note": _equal_wall_clock_note(runtime_rows),
        "algorithm_summary": algorithm_rows,
        "paired_relative": paired,
        "wilcoxon": wilcoxon_rows,
        "reproducibility_note": (
            "Pilot08 C reports same-machine x86 relative percentages only under py313/numpy2.3.5 "
            "worker rows. It does not compare x86 absolute objectives to M1 results."
        ),
    }
    _write_json(out / "pilot08_summary.json", summary)
    _write_csv(out / "pilot08_algorithm_summary.csv", algorithm_rows, fieldnames=_algorithm_summary_fields())
    _write_csv(out / "pilot08_paired_relative.csv", paired, fieldnames=_paired_fields())
    _write_csv(out / "pilot08_wilcoxon.csv", wilcoxon_rows, fieldnames=_wilcoxon_fields())
    _write_csv(out / "pilot08_runtime_summary.csv", runtime_rows, fieldnames=_runtime_fields())
    (out / "pilot08_final_report.md").write_text(_report_markdown(summary), encoding="utf-8")
    return summary


def validate_result_row(row: dict[str, Any], *, expected_budget: int | None) -> None:
    issues = row_gate_issues(row, expected_budget=expected_budget)
    if issues:
        raise RuntimeError(f"HALT_C_EVAL row failed gates {issues}: {_row_id(row)}")


def row_gate_issues(row: dict[str, Any], *, expected_budget: int | None) -> list[str]:
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
    if expected_budget is not None and int(row.get("actual_evals") or 0) != int(expected_budget):
        issues.append("actual_evals")
    if str(row.get("eval_mode")) == "timed":
        target = float(row.get("runtime_target_seconds") or TARGET_SECONDS)
        elapsed = float(row.get("elapsed_seconds") or 0.0)
        if elapsed < target * TIMED_MIN_RATIO or elapsed > target * TIMED_MAX_RATIO:
            issues.append("timed_runtime")
        if int(row.get("actual_evals") or 0) >= int(row.get("eval_budget") or 0):
            issues.append("timed_eval_cap")
    return issues


def integrity_summary(rows: list[dict[str, Any]], *, expected_budget: int) -> dict[str, Any]:
    failures = []
    for row in rows:
        expected = expected_budget if str(row.get("eval_mode")) == "budget" else None
        issues = row_gate_issues(row, expected_budget=expected)
        if issues:
            failures.append({"row": _row_id(row), "issues": issues})
    return {"ok": not failures, "row_count": len(rows), "failures": failures}


def rank_models(rows: list[dict[str, Any]], *, final_update: int | None = None) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("model_label", "")), int(row.get("checkpoint_update") or -1))].append(row)
    ranked = []
    for (label, update), group in grouped.items():
        values = [float(row["best_obj"]) for row in group]
        ranked.append(
            {
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
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["bundle"]), str(row["algorithm"]))].append(row)
    out = []
    for (bundle, algorithm), group in sorted(grouped.items()):
        values = [float(row["best_obj"]) for row in group]
        out.append(
            {
                "bundle": bundle,
                "algorithm": algorithm,
                "n": len(group),
                "mean_best_obj": statistics.fmean(values),
                "std_best_obj": statistics.stdev(values) if len(values) > 1 else 0.0,
                "min_best_obj": min(values),
                "max_best_obj": max(values),
                "mean_elapsed_seconds": statistics.fmean(float(row["elapsed_seconds"]) for row in group),
                "feasibility_rate": sum(1 for row in group if _bool(row["feasible"])) / max(1, len(group)),
            }
        )
    return out


def paired_relative_rows(rows: list[dict[str, Any]], *, left_algorithm: str) -> list[dict[str, Any]]:
    index = {(str(row["bundle"]), int(row["seed"]), str(row["algorithm"])): row for row in rows}
    bundles = sorted({str(row["bundle"]) for row in rows})
    algorithms = sorted({str(row["algorithm"]) for row in rows if str(row["algorithm"]) != left_algorithm})
    out: list[dict[str, Any]] = []
    for bundle in bundles:
        for baseline in algorithms:
            values = []
            wins = 0
            for (b, seed, algorithm), left_row in sorted(index.items()):
                if b != bundle or algorithm != left_algorithm:
                    continue
                base_row = index.get((bundle, seed, baseline))
                if base_row is None:
                    continue
                left_obj = float(left_row["best_obj"])
                base_obj = float(base_row["best_obj"])
                if abs(base_obj) <= 1e-12:
                    continue
                values.append((base_obj - left_obj) / base_obj * 100.0)
                if left_obj < base_obj:
                    wins += 1
            if not values:
                continue
            out.append(
                {
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


def wilcoxon_rows_for_paired(rows: list[dict[str, Any]], *, left_algorithm: str) -> list[dict[str, Any]]:
    index = {(str(row["bundle"]), int(row["seed"]), str(row["algorithm"])): row for row in rows}
    bundles = sorted({str(row["bundle"]) for row in rows})
    algorithms = sorted({str(row["algorithm"]) for row in rows if str(row["algorithm"]) != left_algorithm})
    out: list[dict[str, Any]] = []
    for bundle in bundles:
        for baseline in algorithms:
            diffs = []
            for (b, seed, algorithm), left_row in sorted(index.items()):
                if b != bundle or algorithm != left_algorithm:
                    continue
                base_row = index.get((bundle, seed, baseline))
                if base_row is None:
                    continue
                diffs.append(float(base_row["best_obj"]) - float(left_row["best_obj"]))
            if len(diffs) < 5:
                out.append(
                    {
                        "bundle": bundle,
                        "left_algorithm": left_algorithm,
                        "baseline_algorithm": baseline,
                        "paired_n": len(diffs),
                        "wins": sum(1 for diff in diffs if diff > 0.0),
                        "statistic": "",
                        "p_value": "",
                        "alternative": "greater",
                        "used_for_gate": False,
                    }
                )
                continue
            try:
                result = wilcoxon(diffs, alternative="greater", zero_method="wilcox", method="exact")
                statistic = float(result.statistic)
                p_value = float(result.pvalue)
            except ValueError:
                statistic = math.nan
                p_value = math.nan
            out.append(
                {
                    "bundle": bundle,
                    "left_algorithm": left_algorithm,
                    "baseline_algorithm": baseline,
                    "paired_n": len(diffs),
                    "wins": sum(1 for diff in diffs if diff > 0.0),
                    "statistic": statistic,
                    "p_value": p_value,
                    "alternative": "greater",
                    "used_for_gate": True,
                }
            )
    return out


def classify_verdict(paired_rows: list[dict[str, Any]], wilcoxon_rows: list[dict[str, Any]]) -> dict[str, str]:
    paired = {(row["bundle"], row["baseline_algorithm"]): row for row in paired_rows}
    wilcox = {(row["bundle"], row["baseline_algorithm"]): row for row in wilcoxon_rows}
    train_alpha = paired.get((TRAIN_BUNDLE, "alpha_ucb_block"))
    held_alpha = paired.get((HELD_OUT_BUNDLE, "alpha_ucb_block"))
    train_random = paired.get((TRAIN_BUNDLE, "random_block"))
    held_random = paired.get((HELD_OUT_BUNDLE, "random_block"))
    required = [train_alpha, held_alpha]
    if any(row is None or float(row["mean_relative_pct"]) <= 0.0 or int(row["wins"]) < 3 for row in required):
        return {"verdict": "WEAK", "reason": "DR(BEST) did not stably beat AlphaUCB on both 100_02 and 100_03."}
    if train_random is None or held_random is None or float(train_random["mean_relative_pct"]) <= 0.0 or float(held_random["mean_relative_pct"]) <= 0.0:
        return {"verdict": "WEAK", "reason": "DR(BEST) did not beat random_block by mean relative percent on both train and held-out bundles."}
    promising = int(train_alpha["wins"]) >= 4 and int(held_alpha["wins"]) >= 4
    if not promising:
        return {"verdict": "WEAK", "reason": "DR(BEST) beat AlphaUCB on average but did not reach the 4/5 train+held win gate."}
    held_w = wilcox.get((HELD_OUT_BUNDLE, "alpha_ucb_block"))
    train_wins = int(train_alpha["wins"])
    held_p = _float_or_nan(held_w.get("p_value") if held_w else "")
    if math.isfinite(held_p) and held_p <= 0.05 and train_wins >= 4:
        return {"verdict": "STRONG", "reason": "DR(BEST) met PROMISING gates and the held-out one-sided Wilcoxon gate versus AlphaUCB."}
    return {"verdict": "PROMISING", "reason": "DR(BEST) beat AlphaUCB by mean relative percent with at least 4/5 wins on train and held-out, and beat random_block on both."}


def runtime_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["bundle"]), str(row["algorithm"]))].append(row)
    out = []
    for (bundle, algorithm), group in sorted(grouped.items()):
        elapsed = [float(row["elapsed_seconds"]) for row in group]
        evals = [int(row["actual_evals"]) for row in group]
        out.append(
            {
                "bundle": bundle,
                "algorithm": algorithm,
                "n": len(group),
                "mean_elapsed_seconds": statistics.fmean(elapsed),
                "min_elapsed_seconds": min(elapsed),
                "max_elapsed_seconds": max(elapsed),
                "mean_actual_evals": statistics.fmean(evals),
                "eval_mode": sorted({str(row["eval_mode"]) for row in group})[0],
            }
        )
    return out


def run_all(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    if output_dir.exists() and any(output_dir.iterdir()) and not args.resume:
        raise RuntimeError(f"HALT_C_EVAL: output dir already exists and is non-empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    write_eval_manifest(output_dir / "pilot08_eval_manifest_100c.json", root=Path.cwd())
    checkpoints = discover_checkpoints()
    if not FINAL_MODEL.is_file():
        raise RuntimeError(f"HALT_C_EVAL: missing final model {FINAL_MODEL}")
    if len(checkpoints) != 35:
        raise RuntimeError(f"HALT_C_EVAL: expected 35 checkpoints, found {len(checkpoints)}")
    final_update = final_model_update()
    calibration = _load_json(output_dir / "pilot08_budget_calibration.json")
    if calibration:
        eval_budget = int(calibration["selected_eval_budget"])
    else:
        calibration = calibrate_budget(output_dir=output_dir, start_budget=args.start_budget, target_seconds=args.target_seconds)
        eval_budget = int(calibration["selected_eval_budget"])
    cheap_ranking = _load_ranking(output_dir / "pilot08_checkpoint_cheap_ranking.csv")
    if not cheap_ranking:
        cheap_ranking = screen_checkpoints(output_dir=output_dir, checkpoint_paths=checkpoints, eval_budget=args.cheap_budget)
    top3 = cheap_ranking[:3]
    candidates: list[tuple[str, Path, int]] = []
    for row in top3:
        update = int(row["checkpoint_update"])
        candidates.append((str(row["model_label"]), CHECKPOINT_DIR / f"async_block_ppo_update_{update:04d}.pt", update))
    candidates.append(("final", FINAL_MODEL, final_update))
    refine_ranking = _load_ranking(output_dir / "pilot08_checkpoint_refine_ranking.csv")
    if refine_ranking:
        best_model = refine_ranking[0]
    else:
        best_model, refine_ranking = refine_models(
            output_dir=output_dir,
            candidates=candidates,
            eval_budget=eval_budget,
            final_update=final_update,
        )
    best_label = str(best_model["model_label"])
    best_update = int(best_model["checkpoint_update"])
    best_path = FINAL_MODEL if best_label == "final" else CHECKPOINT_DIR / f"async_block_ppo_update_{best_update:04d}.pt"
    comparison = run_formal_comparison(
        output_dir=output_dir,
        eval_budget=eval_budget,
        best_model_path=best_path,
        best_label=best_label,
        best_update=best_update,
        final_update=final_update,
        target_seconds=args.target_seconds,
    )
    summary = summarize_eval(
        output_dir=output_dir,
        eval_budget=eval_budget,
        best_model={**best_model, "model_path": str(best_path)},
        refine_ranking=refine_ranking,
        cheap_ranking=cheap_ranking,
        comparison_rows=comparison,
    )
    return summary


def normalize_extended_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: row.get(key, "") for key in RESULT_COLUMNS}
    normalized["seed"] = int(normalized["seed"])
    normalized["eval_budget"] = int(normalized["eval_budget"])
    normalized["best_obj"] = float(normalized["best_obj"])
    normalized["actual_evals"] = int(normalized["actual_evals"])
    normalized["candidate_scores"] = int(normalized.get("candidate_scores") or 0)
    normalized["repair_delta_count"] = int(normalized.get("repair_delta_count") or 0)
    normalized["violation_count"] = int(normalized.get("violation_count") or 0)
    normalized["feasible"] = _bool(normalized.get("feasible"))
    normalized["elapsed_seconds"] = float(normalized.get("elapsed_seconds") or 0.0)
    normalized["runtime_target_seconds"] = float(normalized.get("runtime_target_seconds") or 0.0)
    normalized["model_label"] = str(normalized.get("model_label", "") or "")
    normalized["checkpoint_update"] = int(normalized.get("checkpoint_update") or -1)
    normalized["eval_mode"] = str(normalized.get("eval_mode", "") or "")
    normalized["bundle_role"] = str(normalized.get("bundle_role", "") or "")
    for key in ("operator_counts", "destroy_counts", "repair_counts", "q_ratio_counts"):
        value = normalized.get(key)
        if isinstance(value, str):
            normalized[key] = json.loads(value) if value else {}
        elif value in (None, ""):
            normalized[key] = {}
    return normalized


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot08 C 900s equal-wall-clock evaluation tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write-manifest")
    write.add_argument("--output", default=str(EVAL_FINAL_DIR / "pilot08_eval_manifest_100c.json"))
    write.add_argument("--root", default=".")

    run = sub.add_parser("run-all")
    run.add_argument("--output-dir", default=str(EVAL_FINAL_DIR))
    run.add_argument("--resume", action="store_true")
    run.add_argument("--start-budget", type=int, default=2700)
    run.add_argument("--target-seconds", type=float, default=TARGET_SECONDS)
    run.add_argument("--cheap-budget", type=int, default=600)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "write-manifest":
        write_eval_manifest(args.output, root=args.root)
        print(f"PILOT08_EVAL_MANIFEST_OK output={args.output}")
        return 0
    if args.command == "run-all":
        summary = run_all(args)
        print(f"PILOT08_EVAL_OK verdict={summary['verdict']} output={args.output_dir}")
        return 0 if not str(summary["verdict"]).startswith("HALT") else 2
    raise ValueError(f"unknown command {args.command}")


def _formal_tasks(
    *,
    eval_budget: int,
    best_model_path: str | Path,
    best_label: str,
    best_update: int,
    final_update: int,
    target_seconds: float,
) -> list[dict[str, Any]]:
    bundles = [("train", TRAIN_BUNDLE), ("held_out", HELD_OUT_BUNDLE), ("formal_eval", FORMAL_BUNDLE)]
    tasks: list[dict[str, Any]] = []
    for role, bundle in bundles:
        for seed in (1, 2, 3, 4, 5):
            tasks.append(
                {
                    "kind": "policy",
                    "algorithm": "ppo_block",
                    "bundle": bundle,
                    "bundle_role": role,
                    "seed": seed,
                    "eval_budget": eval_budget,
                    "model_path": str(best_model_path),
                    "model_label": "best",
                    "checkpoint_update": best_update,
                    "eval_mode": "budget",
                    "runtime_target_seconds": target_seconds,
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
                    "runtime_target_seconds": target_seconds,
                }
            )
        for seed in (1, 2, 3):
            tasks.append(
                {
                    "kind": "policy",
                    "algorithm": "ppo_block",
                    "bundle": bundle,
                    "bundle_role": role,
                    "seed": seed,
                    "eval_budget": eval_budget,
                    "model_path": str(FINAL_MODEL),
                    "model_label": "final",
                    "checkpoint_update": final_update,
                    "eval_mode": "budget",
                    "runtime_target_seconds": target_seconds,
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
                    "runtime_target_seconds": target_seconds,
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
                    "runtime_target_seconds": target_seconds,
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
                    "runtime_target_seconds": target_seconds,
                }
            )
    return tasks


def _formal_task_key(task: dict[str, Any]) -> tuple[Any, ...]:
    algorithm = task["algorithm"]
    if algorithm == "ppo_block" and task.get("model_label") == "best":
        algorithm = "ppo_block_best"
    elif algorithm == "ppo_block" and task.get("model_label") == "final":
        algorithm = "ppo_block_final"
    return (
        str(task["eval_mode"]),
        str(algorithm),
        str(task["bundle"]),
        int(task["seed"]),
        str(task.get("model_label", "")),
        int(task.get("checkpoint_update") or -1),
    )


def _formal_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(row["eval_mode"]),
        str(row["algorithm"]),
        str(row["bundle"]),
        int(row["seed"]),
        str(row.get("model_label", "")),
        int(row.get("checkpoint_update") or -1),
    )


def _selection_key(row: dict[str, Any]) -> tuple[Any, ...]:
    algorithm = "ppo_block" if str(row["algorithm"]).startswith("ppo_block") else str(row["algorithm"])
    return (
        str(row["eval_mode"]),
        algorithm,
        str(row["bundle"]),
        int(row["seed"]),
        str(row.get("model_label", "")),
        int(row.get("checkpoint_update") or -1),
    )


def _extend_row(
    row: dict[str, Any],
    *,
    elapsed_seconds: float,
    runtime_target_seconds: float,
    model_label: str,
    checkpoint_update_value: int | str,
    eval_mode: str,
    bundle_role: str,
) -> dict[str, Any]:
    out = dict(row)
    out["elapsed_seconds"] = float(elapsed_seconds)
    out["runtime_target_seconds"] = float(runtime_target_seconds)
    out["model_label"] = str(model_label or "")
    out["checkpoint_update"] = checkpoint_update_value if checkpoint_update_value != "" else -1
    out["eval_mode"] = str(eval_mode)
    out["bundle_role"] = str(bundle_role)
    return out


def _write_extended_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    _write_csv(path, rows, fieldnames=RESULT_COLUMNS)


def _write_csv(path: Path, rows: list[dict[str, Any]], *, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(_csv_row(row, fieldnames=fieldnames))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_existing_extended(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [normalize_extended_row(dict(row)) for row in csv.DictReader(handle)]


def _load_ranking(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    for row in rows:
        row["rank"] = int(row["rank"])
        row["checkpoint_update"] = int(row["checkpoint_update"])
        row["n"] = int(row["n"])
        for key in ("mean_best_obj", "std_best_obj", "min_best_obj", "max_best_obj"):
            row[key] = float(row[key])
    return rows


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _csv_row(row: dict[str, Any], *, fieldnames: list[str]) -> dict[str, Any]:
    out = {}
    for key in fieldnames:
        value = row.get(key, "")
        if key == "feasible":
            value = int(_bool(value))
        elif isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        out[key] = value
    return out


def _worker_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(repo_root / "models" / "src"), str(repo_root / "solver" / "src")])
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _model_path_for_label(label: str, update: int) -> str:
    if label == "final":
        return str(FINAL_MODEL)
    if update > 0:
        return str(CHECKPOINT_DIR / f"async_block_ppo_update_{update:04d}.pt")
    return ""


def _find_final_rank(rows: list[dict[str, Any]]) -> int | None:
    for row in rows:
        if row.get("model_label") == "final":
            return int(row["rank"])
    return None


def _ranking_fields() -> list[str]:
    return [
        "rank",
        "model_label",
        "checkpoint_update",
        "n",
        "mean_best_obj",
        "std_best_obj",
        "min_best_obj",
        "max_best_obj",
        "model_path",
    ]


def _algorithm_summary_fields() -> list[str]:
    return [
        "bundle",
        "algorithm",
        "n",
        "mean_best_obj",
        "std_best_obj",
        "min_best_obj",
        "max_best_obj",
        "mean_elapsed_seconds",
        "feasibility_rate",
    ]


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
    return [
        "bundle",
        "left_algorithm",
        "baseline_algorithm",
        "paired_n",
        "wins",
        "statistic",
        "p_value",
        "alternative",
        "used_for_gate",
    ]


def _runtime_fields() -> list[str]:
    return [
        "bundle",
        "algorithm",
        "n",
        "mean_elapsed_seconds",
        "min_elapsed_seconds",
        "max_elapsed_seconds",
        "mean_actual_evals",
        "eval_mode",
    ]


def _report_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Pilot08 C 900s Equal-Wall-Clock Evaluation",
        "",
        f"Verdict: `{summary.get('verdict')}`.",
        f"Reason: {summary.get('reason')}",
        "",
        "This report uses same-machine x86 relative percentages only. It does not compare x86 absolute objectives to M1 results.",
        "",
    ]
    if summary.get("verdict") == "HALT_C_EVAL":
        lines.extend(["## Integrity", "", f"- ok: `{summary.get('integrity', {}).get('ok')}`"])
        for failure in summary.get("integrity", {}).get("failures", []):
            lines.append(f"- {failure['row']}: {failure['issues']}")
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            "## Budget And Model",
            "",
            f"- EVAL_BUDGET_900: `{summary['eval_budget_900']}`",
            f"- BEST_MODEL: `{summary['best_model']['model_label']}` update `{summary['best_model']['checkpoint_update']}`",
            f"- Final model refine rank: `{summary['final_model_rank']}`",
            "",
            "## Equal-Wall-Clock Check",
            "",
            summary["equal_wall_clock_note"],
            "",
            "## Runtime",
            "",
        ]
    )
    for row in summary["runtime_summary"]:
        lines.append(
            "- "
            f"{row['bundle']} {row['algorithm']}: mean {float(row['mean_elapsed_seconds']):.1f}s "
            f"({row['eval_mode']}), mean evals {float(row['mean_actual_evals']):.1f}"
        )
    lines.extend(["", "## Paired Relative Percent", ""])
    for row in summary["paired_relative"]:
        lines.append(
            "- "
            f"{row['bundle']} DR(BEST) vs {row['baseline_algorithm']}: "
            f"mean={float(row['mean_relative_pct']):.4f}% wins={row['wins']}/{row['paired_n']}"
        )
    lines.extend(["", "## Wilcoxon", ""])
    for row in summary["wilcoxon"]:
        p_value = row["p_value"]
        p_text = "" if p_value == "" else f"{float(p_value):.6g}"
        lines.append(
            "- "
            f"{row['bundle']} DR(BEST) vs {row['baseline_algorithm']}: "
            f"n={row['paired_n']} wins={row['wins']} p={p_text}"
        )
    lines.extend(
        [
            "",
            "## Gates",
            "",
            f"- integrity_ok: `{summary['integrity']['ok']}`",
            f"- row_count: `{summary['integrity']['row_count']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _equal_wall_clock_note(runtime_rows: list[dict[str, Any]]) -> str:
    timed = [row for row in runtime_rows if str(row.get("eval_mode")) == "timed"]
    budget = [row for row in runtime_rows if str(row.get("eval_mode")) == "budget"]
    timed_ok = all(
        TARGET_SECONDS * TIMED_MIN_RATIO
        <= float(row.get("mean_elapsed_seconds") or 0.0)
        <= TARGET_SECONDS * TIMED_MAX_RATIO
        for row in timed
    )
    slow_budget = [
        row
        for row in budget
        if float(row.get("mean_elapsed_seconds") or 0.0) > TARGET_SECONDS * TIMED_MAX_RATIO
        or float(row.get("mean_elapsed_seconds") or 0.0) < TARGET_SECONDS * TIMED_MIN_RATIO
    ]
    if timed_ok and not slow_budget:
        return "Timed and budget-mode algorithms stayed within the 900s tolerance window on mean runtime."
    parts = []
    if timed_ok:
        parts.append("SA and official winner rows used true timed mode and stayed near 900s on mean runtime.")
    else:
        parts.append("At least one timed SA/official row group was outside the 900s tolerance window.")
    if slow_budget:
        names = ", ".join(
            f"{row['algorithm']} on {Path(str(row['bundle'])).name} mean={float(row['mean_elapsed_seconds']):.1f}s"
            for row in slow_budget
        )
        parts.append(
            "Budget-mode block algorithms shared EVAL_BUDGET_900, but observed runtimes were not uniformly near 900s: "
            + names
            + ". Interpret relative percentages with this same-machine runtime caveat."
        )
    return " ".join(parts)


def _row_id(row: dict[str, Any]) -> str:
    return f"{row.get('algorithm')}|{row.get('bundle')}|seed{row.get('seed')}|{row.get('model_label')}|{row.get('eval_mode')}"


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes"}


def _float_or_nan(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


if __name__ == "__main__":
    raise SystemExit(main())
