from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from .bundle_manifest import SCHEMA_VERSION, load_manifest, validate_manifest


PILOT07_TRAIN = "models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113"
PILOT07_HELD_OUT = "models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113"
PILOT07_FORMAL = "models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113"
DEFAULT_WORKER = r"C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe"
REQUIRED_NUMPY = "2.3.5"

RESULT_COLUMNS = [
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


def build_pilot_manifest() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "train": [PILOT07_TRAIN],
        "held_out": [PILOT07_HELD_OUT],
        "formal_eval": [PILOT07_FORMAL],
        "excluded_from_training_reason": {
            "reduced_budget_pilot": (
                "Pilot07 trains only on E-UK100_02 to test reduced-budget DR trend on x86; "
                "100-01 remains formal-only and does not leak into training."
            )
        },
    }


def write_pilot_manifest(path: str | Path, *, root: str | Path = ".") -> dict[str, Any]:
    manifest = build_pilot_manifest()
    validate_manifest(manifest, root=root)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def calibration_summary(
    calibration_dirs: list[str | Path],
    *,
    output_dir: str | Path,
    min_projected_episodes: int = 100,
    max_projected_episodes: int = 200,
    projection_hours: float = 3.0,
    memory_limit_mb: float = 12_000.0,
) -> dict[str, Any]:
    rows = [_calibration_row(Path(path), projection_hours=projection_hours) for path in calibration_dirs]
    eligible = [
        row
        for row in rows
        if row["completed_episodes"] > 0
        and row["projected_episodes"] >= min_projected_episodes
        and row["max_system_memory_used_mb"] <= memory_limit_mb
    ]
    selected = None
    if eligible:
        selected = sorted(
            eligible,
            key=lambda row: (
                int(row["eval_budget"]),
                int(row["block_size"]) == 64,
                -abs(float(row["projected_episodes"]) - min(max_projected_episodes, float(row["projected_episodes"]))),
            ),
            reverse=True,
        )[0]
    status = "CALIBRATION_OK" if selected else "HALT_CALIBRATION"
    summary = {
        "schema_version": "resetp-pilot07-calibration.v1",
        "status": status,
        "projection_hours": float(projection_hours),
        "min_projected_episodes": int(min_projected_episodes),
        "max_projected_episodes": int(max_projected_episodes),
        "memory_limit_mb": float(memory_limit_mb),
        "selected": selected,
        "rows": rows,
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "pilot07_calibration_summary.json", summary)
    _write_csv(out / "pilot07_calibration_rows.csv", rows, fieldnames=_calibration_fieldnames())
    (out / "pilot07_calibration_report.md").write_text(_calibration_markdown(summary), encoding="utf-8")
    return summary


def run_reduced_sa(
    *,
    manifest_path: str | Path,
    output_dir: str | Path,
    seeds: list[int],
    eval_budget: int,
    max_runtime_seconds: float,
    required_python: str = DEFAULT_WORKER,
    root: str | Path = ".",
) -> list[dict[str, Any]]:
    _require_worker_process(required_python)

    from setp_solver.check import check_solution
    from setp_solver.search.bundle import load_search_bundle
    from setp_solver.search.candidates import (
        make_shared_initial_solution,
        run_candidate,
        solution_signature_hash,
    )

    manifest = load_manifest(manifest_path, root=root)
    bundles = list(manifest["train"]) + list(manifest["held_out"]) + list(manifest["formal_eval"])
    rows: list[dict[str, Any]] = []
    for bundle_dir in bundles:
        bundle = load_search_bundle(Path(root) / bundle_dir)
        warm = make_shared_initial_solution(bundle)
        for seed in seeds:
            started = time.perf_counter()
            result = run_candidate(
                "scikit-opt-SA",
                bundle.bundle_dir,
                seed=int(seed),
                eval_budget=int(eval_budget),
                max_runtime_seconds=float(max_runtime_seconds),
                initial_solution=warm,
            )
            if result.best_solution is None:
                raise RuntimeError(f"SA returned no solution for bundle={bundle_dir} seed={seed}")
            violations = check_solution(result.best_solution, bundle.instance)
            row = {
                "algorithm": "scikit-opt-SA",
                "bundle": bundle_dir,
                "seed": int(seed),
                "eval_budget": int(eval_budget),
                "best_obj": float(result.best_cost),
                "actual_evals": int(result.evals),
                "candidate_scores": int(result.candidate_scores),
                "repair_delta_count": int(result.repair_delta_count),
                "operator_base_id": "",
                "control_mode": "fair_sa_reduced_budget",
                "violation_count": len(violations),
                "feasible": len(violations) == 0,
                "solution_signature_hash": solution_signature_hash(result.best_solution),
                "operator_counts": result.operator_counts,
                "destroy_counts": {},
                "repair_counts": {},
                "q_ratio_counts": {},
                "worker_python_executable": str(Path(sys.executable).resolve()),
                "worker_python_version": sys.version,
                "worker_numpy_version": np.__version__,
                "elapsed_seconds": time.perf_counter() - started,
            }
            rows.append(_normalize_row(row))
            _write_rows_csv(Path(output_dir) / "sa_reduced_budget.partial.csv", rows)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_rows_csv(out / "sa_reduced_budget.csv", rows)
    _write_json(
        out / "sa_reduced_budget_manifest.json",
        {
            "schema_version": "resetp-pilot07-sa-reduced-budget.v1",
            "manifest": str(manifest_path),
            "seeds": [int(seed) for seed in seeds],
            "eval_budget": int(eval_budget),
            "max_runtime_seconds": float(max_runtime_seconds),
            "worker_python_executable": str(Path(sys.executable).resolve()),
            "worker_numpy_version": np.__version__,
            "row_count": len(rows),
        },
    )
    return rows


def summarize_pilot(
    *,
    final_comparison: str | Path,
    sa_comparison: str | Path,
    output_dir: str | Path,
    required_worker: str = DEFAULT_WORKER,
    required_numpy: str = REQUIRED_NUMPY,
    checkpoint_comparisons: list[str | Path] | None = None,
    train_log: str | Path | None = None,
    update_log: str | Path | None = None,
) -> dict[str, Any]:
    final_rows = load_rows(final_comparison)
    sa_rows = load_rows(sa_comparison)
    all_rows = [*final_rows, *sa_rows]
    integrity = integrity_summary(all_rows, required_worker=required_worker, required_numpy=required_numpy)
    algorithm_rows = algorithm_summary(all_rows)
    paired = paired_relative_rows(all_rows, left="ppo_block")
    checkpoint_rows = checkpoint_trend_rows(
        checkpoint_comparisons or [],
        baseline_rows=final_rows,
        required_worker=required_worker,
        required_numpy=required_numpy,
    )
    training = training_summary(train_log, update_log)
    verdict = classify_verdict(
        integrity=integrity,
        paired_rows=paired,
        checkpoint_rows=checkpoint_rows,
        training=training,
    )
    summary = {
        "schema_version": "resetp-pilot07-summary.v1",
        "verdict": verdict["verdict"],
        "reason": verdict["reason"],
        "integrity": integrity,
        "training": training,
        "algorithm_summary": algorithm_rows,
        "paired_relative": paired,
        "checkpoint_trend": checkpoint_rows,
        "reproducibility_note": (
            "Reduced-budget single-bundle x86 trend pilot. Costs are compared only within the "
            "same py313/numpy2.3.5 worker environment; no cross-machine absolute objective "
            "comparison is made."
        ),
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "pilot07_summary.json", summary)
    _write_csv(out / "pilot07_algorithm_summary.csv", algorithm_rows, fieldnames=_algorithm_summary_fields())
    _write_csv(out / "pilot07_paired_relative.csv", paired, fieldnames=_paired_fields())
    _write_csv(out / "pilot07_checkpoint_trend.csv", checkpoint_rows, fieldnames=_checkpoint_fields())
    (out / "pilot07_report.md").write_text(_summary_markdown(summary), encoding="utf-8")
    return summary


def load_rows(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [_normalize_row(row) for row in csv.DictReader(handle)]


def integrity_summary(
    rows: list[dict[str, Any]],
    *,
    required_worker: str = DEFAULT_WORKER,
    required_numpy: str = REQUIRED_NUMPY,
) -> dict[str, Any]:
    required_worker_resolved = str(Path(required_worker).resolve())
    worker_mismatches = []
    numpy_mismatches = []
    budget_mismatches = []
    violations = []
    non_finite = []
    for row in rows:
        row_id = _row_id(row)
        worker = str(row.get("worker_python_executable", ""))
        if str(Path(worker).resolve()) != required_worker_resolved:
            worker_mismatches.append(row_id)
        if str(row.get("worker_numpy_version", "")) != required_numpy:
            numpy_mismatches.append(row_id)
        if int(row.get("actual_evals") or 0) != int(row.get("eval_budget") or 0):
            budget_mismatches.append(row_id)
        if int(row.get("violation_count") or 0) != 0 or not bool(row.get("feasible")):
            violations.append(row_id)
        if not math.isfinite(float(row.get("best_obj", math.nan))):
            non_finite.append(row_id)
    return {
        "ok": not (worker_mismatches or numpy_mismatches or budget_mismatches or violations or non_finite),
        "row_count": len(rows),
        "worker_mismatches": worker_mismatches,
        "numpy_mismatches": numpy_mismatches,
        "budget_mismatches": budget_mismatches,
        "violations": violations,
        "non_finite": non_finite,
    }


def algorithm_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["bundle"]), str(row["algorithm"]))].append(row)
    out = []
    for (bundle, algorithm), group in sorted(grouped.items()):
        values = [float(row["best_obj"]) for row in group]
        feasible_count = sum(1 for row in group if bool(row["feasible"]))
        out.append(
            {
                "bundle": bundle,
                "algorithm": algorithm,
                "n": len(group),
                "mean_best_obj": statistics.fmean(values),
                "std_best_obj": statistics.stdev(values) if len(values) > 1 else 0.0,
                "min_best_obj": min(values),
                "max_best_obj": max(values),
                "feasibility_rate": feasible_count / max(1, len(group)),
            }
        )
    return out


def paired_relative_rows(rows: list[dict[str, Any]], *, left: str = "ppo_block") -> list[dict[str, Any]]:
    index = {(str(row["bundle"]), int(row["seed"]), str(row["algorithm"])): row for row in rows}
    bundles = sorted({str(row["bundle"]) for row in rows})
    algorithms = sorted({str(row["algorithm"]) for row in rows if str(row["algorithm"]) != left})
    out: list[dict[str, Any]] = []
    for bundle in bundles:
        for baseline in algorithms:
            values = []
            for (b, seed, algorithm), left_row in sorted(index.items()):
                if b != bundle or algorithm != left:
                    continue
                baseline_row = index.get((bundle, seed, baseline))
                if baseline_row is None:
                    continue
                left_obj = float(left_row["best_obj"])
                base_obj = float(baseline_row["best_obj"])
                if abs(base_obj) <= 1e-12:
                    continue
                values.append((base_obj - left_obj) / base_obj * 100.0)
            if not values:
                continue
            out.append(
                {
                    "bundle": bundle,
                    "left_algorithm": left,
                    "baseline_algorithm": baseline,
                    "paired_n": len(values),
                    "mean_relative_pct": statistics.fmean(values),
                    "std_relative_pct": statistics.stdev(values) if len(values) > 1 else 0.0,
                    "min_relative_pct": min(values),
                    "max_relative_pct": max(values),
                }
            )
    return out


def checkpoint_trend_rows(
    paths: list[str | Path],
    *,
    baseline_rows: list[dict[str, Any]],
    required_worker: str,
    required_numpy: str,
) -> list[dict[str, Any]]:
    baseline_index = {
        (str(row["bundle"]), int(row["seed"])): row
        for row in baseline_rows
        if str(row["algorithm"]) == "alpha_ucb_block"
    }
    out: list[dict[str, Any]] = []
    for index, path in enumerate(paths):
        rows = [row for row in load_rows(path) if str(row["algorithm"]) == "ppo_block"]
        integrity = integrity_summary(rows, required_worker=required_worker, required_numpy=required_numpy)
        grouped: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            baseline = baseline_index.get((str(row["bundle"]), int(row["seed"])))
            if baseline is None:
                continue
            base_obj = float(baseline["best_obj"])
            if abs(base_obj) <= 1e-12:
                continue
            rel = (base_obj - float(row["best_obj"])) / base_obj * 100.0
            grouped[str(row["bundle"])].append(rel)
        for bundle, values in sorted(grouped.items()):
            out.append(
                {
                    "checkpoint_order": index,
                    "checkpoint_source": str(path),
                    "bundle": bundle,
                    "paired_n": len(values),
                    "mean_relative_pct_vs_alpha_ucb_block": statistics.fmean(values),
                    "std_relative_pct_vs_alpha_ucb_block": statistics.stdev(values) if len(values) > 1 else 0.0,
                    "integrity_ok": bool(integrity["ok"]),
                }
            )
    return out


def training_summary(train_log: str | Path | None, update_log: str | Path | None) -> dict[str, Any]:
    episodes = _load_csv(train_log) if train_log and Path(train_log).is_file() else []
    updates = _load_csv(update_log) if update_log and Path(update_log).is_file() else []
    reward_values = [float(row["reward_sum"]) for row in episodes if str(row.get("reward_finite", "1")) in {"1", "true", "True"}]
    phases = [str(row.get("curriculum_phase", "")) for row in episodes]
    return {
        "episode_count": len(episodes),
        "zero_violations": all(int(row.get("violation_count") or 0) == 0 for row in episodes),
        "phases_seen": sorted({phase for phase in phases if phase}),
        "entered_carbon": "carbon" in phases,
        "reward_first_third_mean": _third_mean(reward_values, first=True),
        "reward_last_third_mean": _third_mean(reward_values, first=False),
        "reward_slope": _linear_slope(reward_values),
        "update_count": len(updates),
        "mean_entropy": _mean_float(updates, "entropy_loss"),
        "mean_mask_invalid_rate_head_0": _mean_float(updates, "mask_invalid_rate_head_0"),
    }


def classify_verdict(
    *,
    integrity: dict[str, Any],
    paired_rows: list[dict[str, Any]],
    checkpoint_rows: list[dict[str, Any]],
    training: dict[str, Any],
) -> dict[str, str]:
    if not integrity["ok"]:
        return {"verdict": "HALT_INTEGRITY", "reason": "At least one comparison row failed worker, NumPy, budget, feasibility, or finite-objective gates."}
    if not training.get("zero_violations", True) or not training.get("entered_carbon", False):
        return {"verdict": "HALT_TRAINING_GATE", "reason": "Training did not stay zero-violation or did not enter the carbon phase."}
    lookup = {
        (row["bundle"], row["baseline_algorithm"]): float(row["mean_relative_pct"])
        for row in paired_rows
    }
    train_alpha = lookup.get((PILOT07_TRAIN, "alpha_ucb_block"))
    formal_alpha = lookup.get((PILOT07_FORMAL, "alpha_ucb_block"))
    train_random = lookup.get((PILOT07_TRAIN, "random_block"))
    formal_random = lookup.get((PILOT07_FORMAL, "random_block"))
    direct_promising = (
        train_alpha is not None
        and formal_alpha is not None
        and train_alpha >= 0.0
        and formal_alpha >= 0.0
        and (train_random is None or train_random > 0.0)
        and (formal_random is None or formal_random > 0.0)
    )
    trend_promising = _trend_improved(checkpoint_rows) and float(training.get("reward_slope") or 0.0) > 0.0
    if direct_promising or trend_promising:
        return {"verdict": "PROMISING", "reason": "DR met the reduced-budget AlphaUCB/random relative gate or showed a positive checkpoint and reward trend under valid py313 rows."}
    return {"verdict": "WEAK", "reason": "Valid reduced-budget pilot completed, but DR did not non-worsen AlphaUCB(block) on the required train/formal checks and no sufficient trend override was present."}


def _calibration_row(path: Path, *, projection_hours: float) -> dict[str, Any]:
    episodes = _load_csv(path / "async_episode_log.csv")
    throughput = _load_csv(path / "worker_throughput.csv")
    cpu = _load_csv(path / "cpu_probe.csv")
    summary = json.loads((path / "async_train_summary.json").read_text(encoding="utf-8")) if (path / "async_train_summary.json").is_file() else {}
    final_throughput = throughput[-1] if throughput else {}
    config = _parse_calibration_config(path)
    eval_budget = int(config.get("eval_budget") or 0) or (int(statistics.median([int(row.get("actual_evals") or 0) for row in episodes])) if episodes else 0)
    block_size = int(config.get("block_size") or 0) or 0
    num_actors = int(config.get("num_actors") or 0) or int(final_throughput.get("num_actors") or 0)
    episodes_per_hour = float(final_throughput.get("episodes_per_hour") or 0.0)
    max_system_memory_used = max([float(row.get("system_memory_used_mb") or 0.0) for row in cpu] or [0.0])
    max_worker_rss = max([float(row.get("total_worker_rss_mb") or 0.0) for row in cpu] or [0.0])
    return {
        "calibration_dir": path.as_posix(),
        "eval_budget": eval_budget,
        "block_size": block_size,
        "num_actors": num_actors,
        "completed_episodes": len(episodes),
        "train_wall_time_seconds": float(summary.get("train_wall_time_seconds") or 0.0),
        "episodes_per_hour": episodes_per_hour,
        "projected_episodes": episodes_per_hour * float(projection_hours),
        "max_system_memory_used_mb": max_system_memory_used,
        "max_worker_rss_mb": max_worker_rss,
        "zero_violations": all(int(row.get("violation_count") or 0) == 0 for row in episodes),
        "worker_ok": len({str(row.get("worker_python_executable", "")) for row in episodes}) <= 1,
        "numpy_ok": all(str(row.get("worker_numpy_version", "")) == REQUIRED_NUMPY for row in episodes),
    }


def _parse_calibration_config(path: Path) -> dict[str, int]:
    match = re.search(r"budget(?P<budget>\d+)_block(?P<block>\d+)(?:_actors(?P<actors>\d+))?", path.name)
    if not match:
        return {}
    return {
        "eval_budget": int(match.group("budget")),
        "block_size": int(match.group("block")),
        "num_actors": int(match.group("actors") or 0),
    }


def _calibration_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Pilot07 Calibration",
        "",
        f"Status: `{summary['status']}`.",
        f"Projection hours: `{summary['projection_hours']}`.",
        f"Memory limit MB: `{summary['memory_limit_mb']}`.",
        "",
    ]
    if summary["selected"]:
        selected = summary["selected"]
        lines.extend(
            [
                "## Selected",
                "",
                f"- eval_budget: `{selected['eval_budget']}`",
                f"- block_size: `{selected['block_size']}`",
                f"- num_actors: `{selected['num_actors']}`",
                f"- projected_episodes: `{selected['projected_episodes']}`",
                f"- max_system_memory_used_mb: `{selected['max_system_memory_used_mb']}`",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "No calibration row met the required projected episode count and memory gate.",
                "",
            ]
        )
    lines.append("## Rows")
    lines.append("")
    for row in summary["rows"]:
        lines.append(
            "- "
            f"{row['calibration_dir']}: budget={row['eval_budget']}, block={row['block_size']}, "
            f"actors={row['num_actors']}, episodes/hour={row['episodes_per_hour']:.3f}, "
            f"projected={row['projected_episodes']:.1f}, memoryMB={row['max_system_memory_used_mb']:.1f}"
        )
    return "\n".join(lines) + "\n"


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Pilot07 Reduced-Budget DR Trend Report",
        "",
        f"Verdict: `{summary['verdict']}`.",
        f"Reason: {summary['reason']}",
        "",
        "This report uses same-machine relative percentages only. It does not compare x86 absolute objectives to M1 results.",
        "",
        "## Integrity",
        "",
        f"- ok: `{summary['integrity']['ok']}`",
        f"- row_count: `{summary['integrity']['row_count']}`",
        f"- worker_mismatches: `{len(summary['integrity']['worker_mismatches'])}`",
        f"- numpy_mismatches: `{len(summary['integrity']['numpy_mismatches'])}`",
        f"- budget_mismatches: `{len(summary['integrity']['budget_mismatches'])}`",
        f"- violations: `{len(summary['integrity']['violations'])}`",
        "",
        "## Training",
        "",
        f"- episode_count: `{summary['training']['episode_count']}`",
        f"- phases_seen: `{summary['training']['phases_seen']}`",
        f"- entered_carbon: `{summary['training']['entered_carbon']}`",
        f"- reward_slope: `{summary['training']['reward_slope']}`",
        "",
        "## Paired Relative Percent",
        "",
    ]
    for row in summary["paired_relative"]:
        lines.append(
            "- "
            f"{row['bundle']} ppo_block vs {row['baseline_algorithm']}: "
            f"mean={float(row['mean_relative_pct']):.4f}% n={row['paired_n']}"
        )
    return "\n".join(lines) + "\n"


def _require_worker_process(required_python: str) -> None:
    actual = Path(sys.executable).resolve()
    required = Path(required_python).resolve()
    if actual != required:
        raise RuntimeError(f"HALT_WORKER_PYTHON: expected {required}, got {actual}")
    if np.__version__ != REQUIRED_NUMPY:
        raise RuntimeError(f"HALT_WORKER_NUMPY: expected {REQUIRED_NUMPY}, got {np.__version__}")


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: row.get(key, "") for key in RESULT_COLUMNS}
    normalized["seed"] = int(normalized["seed"])
    normalized["eval_budget"] = int(normalized["eval_budget"])
    normalized["best_obj"] = float(normalized["best_obj"])
    normalized["actual_evals"] = int(normalized["actual_evals"])
    normalized["candidate_scores"] = int(normalized.get("candidate_scores") or 0)
    normalized["repair_delta_count"] = int(normalized.get("repair_delta_count") or 0)
    normalized["violation_count"] = int(normalized.get("violation_count") or 0)
    normalized["feasible"] = _bool(normalized.get("feasible"))
    normalized["worker_python_executable"] = str(normalized.get("worker_python_executable", "") or "")
    normalized["worker_python_version"] = str(normalized.get("worker_python_version", "") or "")
    normalized["worker_numpy_version"] = str(normalized.get("worker_numpy_version", "") or "")
    for key in ("operator_counts", "destroy_counts", "repair_counts", "q_ratio_counts"):
        value = normalized.get(key)
        if isinstance(value, str):
            normalized[key] = json.loads(value) if value else {}
        elif value in (None, ""):
            normalized[key] = {}
    return normalized


def _write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
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


def _csv_row(row: dict[str, Any], *, fieldnames: list[str]) -> dict[str, Any]:
    out = {}
    for key in fieldnames:
        value = row.get(key, "")
        if key == "feasible":
            value = int(bool(value))
        elif isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        out[key] = value
    return out


def _load_csv(path: str | Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _third_mean(values: list[float], *, first: bool) -> float | None:
    if not values:
        return None
    third = max(1, len(values) // 3)
    sample = values[:third] if first else values[-third:]
    return statistics.fmean(sample)


def _linear_slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    x_mean = (len(values) - 1) / 2.0
    y_mean = statistics.fmean(values)
    numerator = sum((idx - x_mean) * (value - y_mean) for idx, value in enumerate(values))
    denominator = sum((idx - x_mean) ** 2 for idx in range(len(values)))
    return numerator / denominator if denominator else 0.0


def _mean_float(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if str(row.get(field, "")).strip() not in {"", "nan", "None"}]
    return statistics.fmean(values) if values else None


def _trend_improved(rows: list[dict[str, Any]]) -> bool:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["bundle"])].append(row)
    required = [PILOT07_TRAIN, PILOT07_FORMAL]
    for bundle in required:
        values = sorted(grouped.get(bundle, []), key=lambda row: int(row["checkpoint_order"]))
        if len(values) < 2:
            return False
        if float(values[-1]["mean_relative_pct_vs_alpha_ucb_block"]) <= float(values[0]["mean_relative_pct_vs_alpha_ucb_block"]):
            return False
    return True


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes"}


def _row_id(row: dict[str, Any]) -> str:
    return f"{row.get('algorithm')}|{row.get('bundle')}|seed{row.get('seed')}"


def _calibration_fieldnames() -> list[str]:
    return [
        "calibration_dir",
        "eval_budget",
        "block_size",
        "num_actors",
        "completed_episodes",
        "train_wall_time_seconds",
        "episodes_per_hour",
        "projected_episodes",
        "max_system_memory_used_mb",
        "max_worker_rss_mb",
        "zero_violations",
        "worker_ok",
        "numpy_ok",
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
        "feasibility_rate",
    ]


def _paired_fields() -> list[str]:
    return [
        "bundle",
        "left_algorithm",
        "baseline_algorithm",
        "paired_n",
        "mean_relative_pct",
        "std_relative_pct",
        "min_relative_pct",
        "max_relative_pct",
    ]


def _checkpoint_fields() -> list[str]:
    return [
        "checkpoint_order",
        "checkpoint_source",
        "bundle",
        "paired_n",
        "mean_relative_pct_vs_alpha_ucb_block",
        "std_relative_pct_vs_alpha_ucb_block",
        "integrity_ok",
    ]


def parse_seeds(text: str) -> list[int]:
    seeds = [int(part.strip()) for part in str(text).split(",") if part.strip()]
    if not seeds:
        raise ValueError("at least one seed is required")
    return seeds


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot07 reduced-budget DR trend tools.")
    sub = parser.add_subparsers(dest="command", required=True)

    write = sub.add_parser("write-manifest")
    write.add_argument("--output", required=True)
    write.add_argument("--root", default=".")

    cal = sub.add_parser("calibration-summary")
    cal.add_argument("--output-dir", required=True)
    cal.add_argument("--projection-hours", type=float, default=3.0)
    cal.add_argument("--min-projected-episodes", type=int, default=100)
    cal.add_argument("--max-projected-episodes", type=int, default=200)
    cal.add_argument("--memory-limit-mb", type=float, default=12_000.0)
    cal.add_argument("calibration_dirs", nargs="+")

    sa = sub.add_parser("reduced-sa")
    sa.add_argument("--manifest", required=True)
    sa.add_argument("--output-dir", required=True)
    sa.add_argument("--seeds", default="1,2,3,4,5")
    sa.add_argument("--eval-budget", type=int, required=True)
    sa.add_argument("--max-runtime-seconds", type=float, default=900.0)
    sa.add_argument("--required-python", default=os.environ.get("SETP_WORKER_PYTHON", DEFAULT_WORKER))
    sa.add_argument("--root", default=".")

    summary = sub.add_parser("summarize")
    summary.add_argument("--final-comparison", required=True)
    summary.add_argument("--sa-comparison", required=True)
    summary.add_argument("--output-dir", required=True)
    summary.add_argument("--required-worker", default=os.environ.get("SETP_WORKER_PYTHON", DEFAULT_WORKER))
    summary.add_argument("--required-numpy", default=REQUIRED_NUMPY)
    summary.add_argument("--checkpoint-comparison", action="append", default=[])
    summary.add_argument("--train-log")
    summary.add_argument("--update-log")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "write-manifest":
        manifest = write_pilot_manifest(args.output, root=args.root)
        _ = load_manifest(args.output, root=args.root)
        print(f"PILOT07_MANIFEST_OK train={len(manifest['train'])} output={args.output}")
        return 0
    if args.command == "calibration-summary":
        summary = calibration_summary(
            args.calibration_dirs,
            output_dir=args.output_dir,
            min_projected_episodes=args.min_projected_episodes,
            max_projected_episodes=args.max_projected_episodes,
            projection_hours=args.projection_hours,
            memory_limit_mb=args.memory_limit_mb,
        )
        print(f"PILOT07_CALIBRATION_{summary['status']} output={args.output_dir}")
        return 0 if summary["status"] == "CALIBRATION_OK" else 2
    if args.command == "reduced-sa":
        rows = run_reduced_sa(
            manifest_path=args.manifest,
            output_dir=args.output_dir,
            seeds=parse_seeds(args.seeds),
            eval_budget=args.eval_budget,
            max_runtime_seconds=args.max_runtime_seconds,
            required_python=args.required_python,
            root=args.root,
        )
        print(f"PILOT07_SA_OK rows={len(rows)} output={args.output_dir}")
        return 0
    if args.command == "summarize":
        summary = summarize_pilot(
            final_comparison=args.final_comparison,
            sa_comparison=args.sa_comparison,
            output_dir=args.output_dir,
            required_worker=args.required_worker,
            required_numpy=args.required_numpy,
            checkpoint_comparisons=args.checkpoint_comparison,
            train_log=args.train_log,
            update_log=args.update_log,
        )
        print(f"PILOT07_SUMMARY_OK verdict={summary['verdict']} output={args.output_dir}")
        return 0 if not str(summary["verdict"]).startswith("HALT") else 2
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
