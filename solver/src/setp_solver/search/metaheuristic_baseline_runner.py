"""Fair comparison runner for transcript-backed metaheuristic baselines."""

from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import functools
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any

import numpy as np

from ..check import check_solution
from ..prices import DEFAULT_PRICES, UK_2025_PRICES, PriceParameters
from . import candidates as candidates_module
from . import evaluation as evaluation_module
from . import metaheuristic_baselines as baseline_module
from . import repair_scoring as repair_scoring_module
from .alns_crush import ALNS_DEFAULT_INSTANCE_ORDER, INSTANCE_DIRS
from .bundle import load_search_bundle
from .candidates import make_shared_initial_solution, run_candidate
from .metaheuristic_baselines import (
    BASELINE_ALGORITHMS,
    baseline_result_to_dict,
    cost_breakdown_row,
    run_metaheuristic_baseline,
    solution_to_dict,
)
from .winner_operators import WinnerKernelConfig, run_winner_kernel


SYSTEM_PYTHON = os.environ.get("SETP_WORKER_PYTHON", "/opt/anaconda3/bin/python3.13")
SYSTEM_NUMPY = "2.3.5"
DEFAULT_EVAL_BUDGET = 16_000
DEFAULT_MAX_RUNTIME_SECONDS = 900.0
DEFAULT_FALLBACK_MAX_RUNTIME_SECONDS = 3600.0
DEFAULT_PROFILE_EVAL_BUDGET = 100
DEFAULT_INSTANCES = ALNS_DEFAULT_INSTANCE_ORDER
PROFILE_ALGORITHMS = ("IWD", "GWO", "ACO", "VNS")


def run_all(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    instances: list[str],
    seeds: list[int],
    eval_budget: int = DEFAULT_EVAL_BUDGET,
    max_runtime_seconds: float = DEFAULT_MAX_RUNTIME_SECONDS,
    fallback_max_runtime_seconds: float | None = None,
    auto_runtime_fallback: bool = False,
    speed_probe_eval_budget: int = DEFAULT_PROFILE_EVAL_BUDGET,
    algorithms: list[str] | None = None,
    prices: PriceParameters = DEFAULT_PRICES,
) -> dict[str, Any]:
    _ensure_environment()
    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_preflight(root, out)
    selected = _selected_instances(instances)
    selected_algorithms = algorithms or list(BASELINE_ALGORITHMS)
    runtime_caps = _runtime_caps(
        root,
        selected,
        selected_algorithms,
        max_runtime_seconds=float(max_runtime_seconds),
        fallback_max_runtime_seconds=fallback_max_runtime_seconds,
        auto_runtime_fallback=auto_runtime_fallback,
        speed_probe_eval_budget=int(speed_probe_eval_budget),
        target_eval_budget=int(eval_budget),
        prices=prices,
    )
    started = time.perf_counter()

    tasks: list[tuple[str, str, str, int, int, float, PriceParameters]] = []
    for instance_name, rel_dir in selected.items():
        bundle_dir = str(root / rel_dir)
        for seed in seeds:
            tasks.append(("fair-SA", instance_name, bundle_dir, int(seed), int(eval_budget), runtime_caps["fair-SA"], prices))
            tasks.append(("winner-kernel ALNS", instance_name, bundle_dir, int(seed), int(eval_budget), runtime_caps["winner-kernel ALNS"], prices))
            for algorithm in selected_algorithms:
                tasks.append((algorithm, instance_name, bundle_dir, int(seed), int(eval_budget), runtime_caps.get(algorithm, float(max_runtime_seconds)), prices))

    results, fallback_reruns = _run_parallel_with_fallback(
        tasks,
        fallback_max_runtime_seconds=fallback_max_runtime_seconds,
        auto_runtime_fallback=auto_runtime_fallback,
        prices=prices,
    )

    return _write_formal_results(
        root,
        out,
        selected=selected,
        seeds=seeds,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        fallback_max_runtime_seconds=fallback_max_runtime_seconds,
        auto_runtime_fallback=auto_runtime_fallback,
        runtime_caps=runtime_caps,
        selected_algorithms=selected_algorithms,
        results=results,
        started=started,
        fallback_reruns=fallback_reruns,
        previous_output_dir=None,
        prices=prices,
    )


def run_fallback_completion(
    repo_root: str | Path,
    previous_output_dir: str | Path,
    output_dir: str | Path,
    *,
    fallback_max_runtime_seconds: float = DEFAULT_FALLBACK_MAX_RUNTIME_SECONDS,
    prices: PriceParameters = DEFAULT_PRICES,
) -> dict[str, Any]:
    _ensure_environment()
    root = Path(repo_root)
    previous = Path(previous_output_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_preflight(root, out)

    manifest = json.loads((previous / "manifest.json").read_text(encoding="utf-8"))
    raw_rows = _read_csv(previous / "raw_runs.csv")
    results = [_result_from_raw_row(previous, row) for row in raw_rows]
    tasks: list[tuple[str, str, str, int, int, float, PriceParameters]] = []
    old_by_key = {_result_key(result): result for result in results}
    for result in results:
        if (
            result["status"] == "HALT_RUNTIME_UNDER_EVAL"
            and int(result["evaluations"]) < int(result["eval_budget"])
            and float(result["max_runtime_seconds"]) < float(fallback_max_runtime_seconds)
        ):
            bundle_dir = Path(str(result["bundle_dir"]))
            if not bundle_dir.is_absolute():
                bundle_dir = root / bundle_dir
            tasks.append(
                (
                    str(result["algorithm"]),
                    str(result["instance"]),
                    str(bundle_dir),
                    int(result["seed"]),
                    int(result["eval_budget"]),
                    float(fallback_max_runtime_seconds),
                    prices,
                )
            )

    started = time.perf_counter()
    fallback_results = _run_parallel(tasks) if tasks else []
    fallback_reruns: list[dict[str, Any]] = []
    for replacement in fallback_results:
        key = _result_key(replacement)
        old = old_by_key.get(key, {})
        old_by_key[key] = replacement
        fallback_reruns.append(
            {
                "instance": replacement["instance"],
                "algorithm": replacement["algorithm"],
                "seed": int(replacement["seed"]),
                "old_evaluations": int(old.get("evaluations", 0) or 0),
                "old_max_runtime_seconds": float(old.get("max_runtime_seconds", 0.0) or 0.0),
                "new_evaluations": int(replacement["evaluations"]),
                "new_max_runtime_seconds": float(replacement["max_runtime_seconds"]),
                "new_status": replacement["status"],
            }
        )
    combined_results = list(old_by_key.values())
    selected = {name: Path(path) for name, path in dict(manifest["instances"]).items()}
    selected_algorithms = [
        str(algorithm)
        for algorithm in manifest.get("algorithms", [])
        if algorithm not in {"fair-SA", "winner-kernel ALNS"}
    ]
    runtime_caps = dict(manifest.get("runtime_caps", {}))
    for rerun in fallback_reruns:
        algorithm = str(rerun["algorithm"])
        runtime_caps[algorithm] = max(float(runtime_caps.get(algorithm, 0.0) or 0.0), float(rerun["new_max_runtime_seconds"]))

    elapsed_override = float(manifest.get("elapsed_seconds", 0.0) or 0.0) + (time.perf_counter() - started)
    return _write_formal_results(
        root,
        out,
        selected=selected,
        seeds=[int(seed) for seed in manifest["seeds"]],
        eval_budget=int(manifest["eval_budget"]),
        max_runtime_seconds=float(manifest["max_runtime_seconds"]),
        fallback_max_runtime_seconds=float(fallback_max_runtime_seconds),
        auto_runtime_fallback=bool(manifest.get("auto_runtime_fallback", True)),
        runtime_caps=runtime_caps,
        selected_algorithms=selected_algorithms,
        results=combined_results,
        started=started,
        fallback_reruns=fallback_reruns,
        previous_output_dir=str(previous),
        elapsed_seconds_override=elapsed_override,
        prices=prices,
    )


def _write_formal_results(
    root: Path,
    out: Path,
    *,
    selected: dict[str, Path],
    seeds: list[int],
    eval_budget: int,
    max_runtime_seconds: float,
    fallback_max_runtime_seconds: float | None,
    auto_runtime_fallback: bool,
    runtime_caps: dict[str, float],
    selected_algorithms: list[str],
    results: list[dict[str, Any]],
    started: float,
    fallback_reruns: list[dict[str, Any]],
    previous_output_dir: str | None,
    elapsed_seconds_override: float | None = None,
    prices: PriceParameters = DEFAULT_PRICES,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    halt_rows: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda row: (row["instance"], row["algorithm"], int(row["seed"]))):
        raw_rows.append(_raw_result_row(result))
        if result["status"] != "OK":
            halt_rows.append(_raw_result_row(result))
        if result.get("solution") is None:
            continue
        bundle = load_search_bundle(result["bundle_dir"])
        solution = _solution_from_result(result)
        row = cost_breakdown_row(
            result["instance"],
            result["algorithm"],
            int(result["seed"]),
            solution,
            bundle.instance,
            bundle.carbon_profile,
            prices,
        )
        row.update(
            {
                "variant": "metaheuristic_baseline",
                "evaluations": int(result["evaluations"]),
                "run_elapsed_seconds": float(result["elapsed_seconds"]),
                "status": result["status"],
                "source": result.get("source", ""),
                "commit_hash": _git_commit(root),
            }
        )
        rows.append(row)
        _write_json(out / "solutions" / f"{result['instance']}_{_safe_name(result['algorithm'])}_seed{result['seed']}.json", result["solution"])

    summary = _summary_rows(rows)
    comparison = _comparison_rows(summary, rows)
    wilcoxon = _wilcoxon_rows(rows)
    verdicts = _verdict_rows(comparison, wilcoxon)
    convergence = _convergence_rows(results)
    _write_csv(out / "raw_runs.csv", raw_rows)
    _write_csv(out / "comparison_table.csv", comparison)
    _write_csv(out / "wilcoxon.csv", wilcoxon)
    _write_csv(out / "verdicts.csv", verdicts)
    _write_csv(out / "convergence_curves.csv", convergence)
    _write_csv(out / "halts.csv", halt_rows)
    manifest = {
        "schema_version": "setp-metaheuristic-baselines.v1",
        "repo_root": str(root),
        "commit_hash": _git_commit(root),
        "system_python": SYSTEM_PYTHON,
        "numpy": np.__version__,
        "instances": {name: str(path) for name, path in selected.items()},
        "seeds": seeds,
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "fallback_max_runtime_seconds": fallback_max_runtime_seconds,
        "auto_runtime_fallback": bool(auto_runtime_fallback),
        "runtime_caps": runtime_caps,
        "fallback_reruns": fallback_reruns,
        "previous_output_dir": previous_output_dir,
        "algorithms": ["fair-SA", "winner-kernel ALNS", *selected_algorithms],
        "elapsed_seconds": float(elapsed_seconds_override) if elapsed_seconds_override is not None else time.perf_counter() - started,
        "status": "HALT_BASELINE_INCOMPARABLE" if halt_rows else "OK",
        "outputs": ["raw_runs.csv", "comparison_table.csv", "wilcoxon.csv", "verdicts.csv", "convergence_curves.csv", "report.md", "manifest.json"],
    }
    _write_json(out / "manifest.json", manifest)
    (out / "report.md").write_text(_report(verdicts, comparison, halt_rows, manifest), encoding="utf-8")
    return {"gate": manifest["status"], "manifest": str(out / "manifest.json"), "elapsed_seconds": manifest["elapsed_seconds"]}


def run_profile(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    instance: str = "L-main",
    seed: int = 1,
    eval_budget: int = DEFAULT_PROFILE_EVAL_BUDGET,
    max_runtime_seconds: float = 300.0,
    algorithms: list[str] | None = None,
    prices: PriceParameters = DEFAULT_PRICES,
) -> dict[str, Any]:
    _ensure_environment()
    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    selected = _selected_instances([instance])
    if instance not in selected:
        raise ValueError(f"Profile instance {instance!r} not selected")
    bundle_dir = root / selected[instance]
    profile_algorithms = algorithms or list(PROFILE_ALGORITHMS)
    rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for algorithm in [*profile_algorithms, "winner-kernel ALNS"]:
        result = _profile_one(
            algorithm,
            str(bundle_dir),
            instance,
            int(seed),
            int(eval_budget),
            float(max_runtime_seconds),
            prices,
        )
        summaries.append(result["summary"])
        rows.extend(result["buckets"])
    _write_csv(out / "profile_timings.csv", rows)
    _write_csv(out / "profile_summary.csv", summaries)
    manifest = {
        "schema_version": "setp-metaheuristic-baseline-profile.v1",
        "repo_root": str(root),
        "commit_hash": _git_commit(root),
        "system_python": SYSTEM_PYTHON,
        "numpy": np.__version__,
        "instance": instance,
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "algorithms": [*profile_algorithms, "winner-kernel ALNS"],
        "outputs": ["profile_report.md", "profile_timings.csv", "profile_summary.csv", "manifest.json"],
    }
    _write_json(out / "manifest.json", manifest)
    (out / "profile_report.md").write_text(_profile_report(summaries, rows, manifest), encoding="utf-8")
    return {"gate": "PROFILE_COMPLETE", "manifest": str(out / "manifest.json")}


def _run_task(
    task: tuple[str, str, str, int, int, float, PriceParameters],
) -> dict[str, Any]:
    algorithm, instance_name, bundle_dir, seed, eval_budget, max_runtime_seconds, prices = task
    bundle = load_search_bundle(bundle_dir)
    warm = make_shared_initial_solution(bundle, prices=prices)
    started = time.perf_counter()
    if algorithm == "fair-SA":
        run = run_candidate(
            "scikit-opt-SA",
            bundle_dir,
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            initial_solution=warm,
            prices=prices,
        )
        solution = run.best_solution
        status = "OK" if solution is not None and int(run.evals) >= int(eval_budget) else run.status
        source = "Existing fair scikit-opt-SA adapter under common referee"
        evaluations = int(run.evals)
        best_cost = run.best_cost
        elapsed = float(run.elapsed_seconds)
        history = list(getattr(run, "history", []) or [])
    elif algorithm == "winner-kernel ALNS":
        run = run_winner_kernel(
            bundle_dir,
            config=WinnerKernelConfig(seed=seed, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds),
            initial_solution=warm,
            prices=prices,
        )
        solution = run["best_solution"]
        status = "OK" if run["feasible"] and int(run["evaluations"]) >= int(eval_budget) else "HALT_WINNER_INCOMPARABLE"
        source = "winner_operators.run_winner_kernel"
        evaluations = int(run["evaluations"])
        best_cost = float(run["best_cost"])
        elapsed = float(run["elapsed_seconds"])
        history = [{"eval": float(evaluations), "best_cost": best_cost, "operator": "winner_final"}]
    else:
        run = run_metaheuristic_baseline(
            algorithm,
            bundle_dir,
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            initial_solution=warm,
            prices=prices,
        )
        solution = run.best_solution
        status = run.status
        source = run.source
        evaluations = int(run.evals)
        best_cost = run.best_cost
        elapsed = float(run.elapsed_seconds)
        history = list(run.history)
    violations = check_solution(solution, bundle.instance, prices) if solution is not None else []
    if solution is not None and violations:
        status = "HALT_VIOLATIONS"
    if evaluations < int(eval_budget):
        status = "HALT_RUNTIME_UNDER_EVAL" if status == "OK" else status
    return {
        "instance": instance_name,
        "bundle_dir": str(bundle_dir),
        "algorithm": algorithm,
        "seed": int(seed),
        "evaluations": evaluations,
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "elapsed_seconds": elapsed,
        "best_cost": best_cost,
        "status": status,
        "source": source,
        "violation_count": len(violations),
        "history": history,
        "solution": solution_to_dict(solution) if solution is not None else None,
    }


def _run_parallel(
    tasks: list[tuple[str, str, str, int, int, float, PriceParameters]],
) -> list[dict[str, Any]]:
    max_workers = max(1, min(len(tasks), int(os.environ.get("SETP_META_PARALLEL_WORKERS", os.cpu_count() or 2))))
    if max_workers == 1:
        return [_run_task(task) for task in tasks]
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_run_task, task) for task in tasks]
        for future in as_completed(futures):
            results.append(future.result())
    return results


def _run_parallel_with_fallback(
    tasks: list[tuple[str, str, str, int, int, float, PriceParameters]],
    *,
    fallback_max_runtime_seconds: float | None,
    auto_runtime_fallback: bool,
    prices: PriceParameters,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results = _run_parallel(tasks)
    if not auto_runtime_fallback or fallback_max_runtime_seconds is None:
        return results, []
    fallback_cap = float(fallback_max_runtime_seconds)
    fallback_tasks: list[tuple[str, str, str, int, int, float, PriceParameters]] = []
    for result in results:
        if (
            result["status"] == "HALT_RUNTIME_UNDER_EVAL"
            and int(result["evaluations"]) < int(result["eval_budget"])
            and float(result["max_runtime_seconds"]) < fallback_cap
        ):
            fallback_tasks.append(
                (
                    str(result["algorithm"]),
                    str(result["instance"]),
                    str(result["bundle_dir"]),
                    int(result["seed"]),
                    int(result["eval_budget"]),
                    fallback_cap,
                    prices,
                )
            )
    if not fallback_tasks:
        return results, []
    replacements = _run_parallel(fallback_tasks)
    by_key = {_result_key(result): result for result in results}
    reruns: list[dict[str, Any]] = []
    for replacement in replacements:
        key = _result_key(replacement)
        old = by_key.get(key, {})
        by_key[key] = replacement
        reruns.append(
            {
                "instance": replacement["instance"],
                "algorithm": replacement["algorithm"],
                "seed": int(replacement["seed"]),
                "old_evaluations": int(old.get("evaluations", 0) or 0),
                "old_max_runtime_seconds": float(old.get("max_runtime_seconds", 0.0) or 0.0),
                "new_evaluations": int(replacement["evaluations"]),
                "new_max_runtime_seconds": float(replacement["max_runtime_seconds"]),
                "new_status": replacement["status"],
            }
        )
    return list(by_key.values()), reruns


def _result_key(result: dict[str, Any]) -> tuple[str, str, int]:
    return str(result["instance"]), str(result["algorithm"]), int(result["seed"])


def _runtime_caps(
    root: Path,
    selected: dict[str, Path],
    algorithms: list[str],
    *,
    max_runtime_seconds: float,
    fallback_max_runtime_seconds: float | None,
    auto_runtime_fallback: bool,
    speed_probe_eval_budget: int,
    target_eval_budget: int,
    prices: PriceParameters,
) -> dict[str, float]:
    caps = {"fair-SA": float(max_runtime_seconds), "winner-kernel ALNS": float(max_runtime_seconds)}
    caps.update({algorithm: float(max_runtime_seconds) for algorithm in algorithms})
    if not auto_runtime_fallback or fallback_max_runtime_seconds is None:
        return caps
    if "L-main" not in selected:
        return caps
    bundle_dir = root / selected["L-main"]
    bundle = load_search_bundle(bundle_dir)
    warm = make_shared_initial_solution(bundle, prices=prices)
    for algorithm in algorithms:
        started = time.perf_counter()
        result = run_metaheuristic_baseline(
            algorithm,
            bundle_dir,
            seed=1,
            eval_budget=int(speed_probe_eval_budget),
            max_runtime_seconds=max(60.0, float(fallback_max_runtime_seconds)),
            initial_solution=warm,
            prices=prices,
        )
        elapsed = max(1e-9, time.perf_counter() - started)
        evals_per_second = float(result.evals) / elapsed
        projected = int(target_eval_budget) / evals_per_second if evals_per_second > 1e-12 else math.inf
        if projected > float(max_runtime_seconds):
            caps[algorithm] = float(fallback_max_runtime_seconds)
    return caps


def _convergence_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda row: (row["instance"], row["algorithm"], int(row["seed"]))):
        history = list(result.get("history") or [])
        if not history and result.get("best_cost") is not None:
            history = [{"eval": float(result.get("evaluations", 0)), "best_cost": float(result["best_cost"])}]
        for idx, point in enumerate(history):
            best_value = point.get("best_cost", point.get("best_obj", result.get("best_cost")))
            current_value = point.get("current_cost", point.get("current_obj", ""))
            rows.append(
                {
                    "instance": result["instance"],
                    "algorithm": result["algorithm"],
                    "seed": int(result["seed"]),
                    "point_index": idx,
                    "eval": float(point.get("eval", result.get("evaluations", 0))),
                    "best_cost": float(best_value) if best_value not in {None, ""} else math.nan,
                    "current_cost": float(current_value) if current_value not in {None, ""} else "",
                    "operator": point.get("operator", ""),
                    "eval_budget": int(result.get("eval_budget", 0)),
                    "max_runtime_seconds": float(result.get("max_runtime_seconds", 0.0)),
                    "status": result.get("status", ""),
                }
            )
    return rows


def _profile_one(
    algorithm: str,
    bundle_dir: str,
    instance_name: str,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    prices: PriceParameters,
) -> dict[str, Any]:
    bundle = load_search_bundle(bundle_dir)
    warm = make_shared_initial_solution(bundle, prices=prices)
    with _profile_timers() as timers:
        started = time.perf_counter()
        if algorithm == "winner-kernel ALNS":
            run = run_winner_kernel(
                bundle_dir,
                config=WinnerKernelConfig(seed=seed, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds),
                initial_solution=warm,
                prices=prices,
            )
            evals = int(run["evaluations"])
            status = "OK" if run["feasible"] else "HALT_WINNER_INCOMPARABLE"
            best_cost = float(run["best_cost"])
        else:
            result = run_metaheuristic_baseline(
                algorithm,
                bundle_dir,
                seed=seed,
                eval_budget=eval_budget,
                max_runtime_seconds=max_runtime_seconds,
                initial_solution=warm,
                prices=prices,
            )
            evals = int(result.evals)
            status = result.status
            best_cost = result.best_cost
        elapsed = time.perf_counter() - started
    evals_per_second = evals / max(1e-9, elapsed)
    projected = DEFAULT_EVAL_BUDGET / evals_per_second if evals_per_second > 1e-12 else math.inf
    summary = {
        "instance": instance_name,
        "algorithm": algorithm,
        "seed": int(seed),
        "status": status,
        "evals": evals,
        "elapsed_seconds": float(elapsed),
        "evals_per_second": float(evals_per_second),
        "projected_16000_seconds": float(projected),
        "meets_16000_900s": projected <= DEFAULT_MAX_RUNTIME_SECONDS,
        "best_cost": best_cost,
    }
    bucket_rows: list[dict[str, Any]] = []
    accounted = 0.0
    for bucket, row in sorted(timers.items()):
        seconds = float(row["seconds"])
        accounted += seconds
        bucket_rows.append(
            {
                **summary,
                "bucket": bucket,
                "bucket_count": int(row["count"]),
                "bucket_seconds": seconds,
                "bucket_share_pct": seconds / max(1e-9, elapsed) * 100.0,
            }
        )
    other = max(0.0, float(elapsed) - accounted)
    bucket_rows.append({**summary, "bucket": "other_or_uninstrumented", "bucket_count": 0, "bucket_seconds": other, "bucket_share_pct": other / max(1e-9, elapsed) * 100.0})
    return {"summary": summary, "buckets": bucket_rows}


@contextmanager
def _profile_timers() -> Any:
    timers: dict[str, dict[str, float | int]] = {
        "decode_order_to_solution": {"count": 0, "seconds": 0.0},
        "evaluate": {"count": 0, "seconds": 0.0},
        "check_solution": {"count": 0, "seconds": 0.0},
        "repair_route_charging": {"count": 0, "seconds": 0.0},
    }
    originals: list[tuple[Any, str, Any]] = []

    def patch(module: Any, name: str, bucket: str) -> None:
        original = getattr(module, name)

        @functools.wraps(original)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                timers[bucket]["count"] = int(timers[bucket]["count"]) + 1
                timers[bucket]["seconds"] = float(timers[bucket]["seconds"]) + (time.perf_counter() - started)

        setattr(module, name, wrapper)
        originals.append((module, name, original))

    try:
        patch(baseline_module, "_decode_order_like_random_key", "decode_order_to_solution")
        patch(baseline_module, "evaluate", "evaluate")
        patch(baseline_module, "check_solution", "check_solution")
        patch(baseline_module, "repair_route_charging", "repair_route_charging")
        patch(evaluation_module, "evaluate", "evaluate")
        patch(evaluation_module, "check_solution", "check_solution")
        patch(candidates_module, "check_solution", "check_solution")
        patch(candidates_module, "repair_route_charging", "repair_route_charging")
        patch(repair_scoring_module, "evaluate", "evaluate")
        yield timers
    finally:
        for module, name, original in reversed(originals):
            setattr(module, name, original)


def _solution_from_result(result: dict[str, Any]) -> Any:
    from .metaheuristic_baselines import solution_from_dict

    return solution_from_dict(result["solution"])


def _summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["instance"]), str(row["algorithm"])), []).append(row)
    out: list[dict[str, Any]] = []
    for (instance_name, algorithm), items in sorted(grouped.items()):
        costs = [float(row["total_cost"]) for row in items]
        out.append(
            {
                "instance": instance_name,
                "algorithm": algorithm,
                "n": len(items),
                "mean_total_cost": statistics.fmean(costs),
                "best_total_cost": min(costs),
                "std_total_cost": statistics.stdev(costs) if len(costs) > 1 else 0.0,
                "mean_route_count": statistics.fmean(float(row["route_count"]) for row in items),
                "mean_cv_routes": statistics.fmean(float(row["cv_routes"]) for row in items),
                "mean_ev_routes": statistics.fmean(float(row["ev_routes"]) for row in items),
                "zero_violation_count": sum(1 for row in items if int(row["violation_count"]) == 0),
                "mean_evaluations": statistics.fmean(float(row["evaluations"]) for row in items),
                "mean_runtime_seconds": statistics.fmean(float(row["run_elapsed_seconds"]) for row in items),
                "commit_hash": items[0].get("commit_hash", ""),
                "source": items[0].get("source", ""),
            }
        )
    return out


def _comparison_rows(summary: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lookup = {(row["instance"], row["algorithm"]): row for row in summary}
    out: list[dict[str, Any]] = []
    for row in summary:
        instance_name = row["instance"]
        algorithm = row["algorithm"]
        winner = lookup.get((instance_name, "winner-kernel ALNS"))
        fair = lookup.get((instance_name, "fair-SA"))
        winner_mean = float(winner["mean_total_cost"]) if winner else math.nan
        fair_mean = float(fair["mean_total_cost"]) if fair else math.nan
        alg_mean = float(row["mean_total_cost"])
        paired_vs_winner = _paired_wins(rows, instance_name, algorithm, "winner-kernel ALNS")
        paired_vs_fair = _paired_wins(rows, instance_name, algorithm, "fair-SA")
        out.append(
            {
                **row,
                "gap_vs_winner_pct": (alg_mean - winner_mean) / winner_mean * 100.0 if winner and abs(winner_mean) > 1e-12 else math.nan,
                "gap_vs_fair_sa_pct": (alg_mean - fair_mean) / fair_mean * 100.0 if fair and abs(fair_mean) > 1e-12 else math.nan,
                "paired_wins_alg_lower_vs_winner": paired_vs_winner["wins"],
                "paired_pairs_vs_winner": paired_vs_winner["pairs"],
                "paired_wins_alg_lower_vs_fair_sa": paired_vs_fair["wins"],
                "paired_pairs_vs_fair_sa": paired_vs_fair["pairs"],
            }
        )
    return out


def _wilcoxon_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    algorithms = sorted({row["algorithm"] for row in rows})
    instances = sorted({row["instance"] for row in rows})
    for instance_name in instances:
        for algorithm in algorithms:
            for baseline in ("winner-kernel ALNS", "fair-SA"):
                if algorithm == baseline:
                    continue
                diffs = _paired_diffs(rows, instance_name, algorithm, baseline)
                p_value, method = _wilcoxon_less(diffs)
                out.append(
                    {
                        "instance": instance_name,
                        "algorithm": algorithm,
                        "baseline": baseline,
                        "n_pairs": len(diffs),
                        "mean_diff_alg_minus_baseline": statistics.fmean(diffs) if diffs else math.nan,
                        "wins_alg_lower": sum(1 for value in diffs if value < -1e-9),
                        "p_value_less": p_value,
                        "method": method,
                    }
                )
    return out


def _verdict_rows(comparison: list[dict[str, Any]], wilcoxon: list[dict[str, Any]]) -> list[dict[str, Any]]:
    p_lookup = {(row["instance"], row["algorithm"], row["baseline"]): row for row in wilcoxon}
    out: list[dict[str, Any]] = []
    for row in comparison:
        algorithm = row["algorithm"]
        if algorithm in {"winner-kernel ALNS", "fair-SA"}:
            continue
        p_row = p_lookup.get((row["instance"], algorithm, "winner-kernel ALNS"), {})
        gap = float(row["gap_vs_winner_pct"])
        wins = int(p_row.get("wins_alg_lower", 0))
        p_value = float(p_row.get("p_value_less", math.nan))
        if gap > 0 and wins <= 2:
            verdict = "ALNS碾压"
        elif gap > 0:
            verdict = "ALNS小幅领先"
        elif abs(gap) <= 0.25:
            verdict = "持平"
        else:
            verdict = "ALNS失败"
        out.append({**row, "baseline": "winner-kernel ALNS", "winner_lower_is_better_gap_pct": -gap, "p_value_alg_less_than_winner": p_value, "wins_alg_lower_than_winner": wins, "verdict": verdict})
    return out


def _paired_diffs(rows: list[dict[str, Any]], instance_name: str, algorithm: str, baseline: str) -> list[float]:
    alg = {int(row["seed"]): float(row["total_cost"]) for row in rows if row["instance"] == instance_name and row["algorithm"] == algorithm}
    base = {int(row["seed"]): float(row["total_cost"]) for row in rows if row["instance"] == instance_name and row["algorithm"] == baseline}
    seeds = sorted(set(alg) & set(base))
    return [alg[seed] - base[seed] for seed in seeds]


def _paired_wins(rows: list[dict[str, Any]], instance_name: str, algorithm: str, baseline: str) -> dict[str, int]:
    diffs = _paired_diffs(rows, instance_name, algorithm, baseline)
    return {"pairs": len(diffs), "wins": sum(1 for value in diffs if value < -1e-9)}


def _wilcoxon_less(diffs: list[float]) -> tuple[float, str]:
    nonzero = [value for value in diffs if abs(value) > 1e-9]
    if not nonzero:
        return 1.0, "all_zero"
    try:
        from scipy.stats import wilcoxon

        result = wilcoxon(nonzero, alternative="less", zero_method="wilcox", method="auto")
        return float(result.pvalue), "scipy_wilcoxon_less"
    except Exception:
        wins = sum(1 for value in nonzero if value < 0.0)
        return sum(math.comb(len(nonzero), k) for k in range(wins, len(nonzero) + 1)) / (2 ** len(nonzero)), "fallback_sign_test_less"


def _report(verdicts: list[dict[str, Any]], comparison: list[dict[str, Any]], halt_rows: list[dict[str, Any]], manifest: dict[str, Any]) -> str:
    lines = ["# Metaheuristic Baseline Comparison", ""]
    if halt_rows:
        lines.append("One-line conclusion: at least one run is incomparable because it failed the zero-violation or full-evaluation gate; no dominance claim should be made from this report.")
    else:
        pieces = [
            f"{row['instance']} {row['algorithm']}={row['verdict']}"
            for row in verdicts
            if row["algorithm"] not in {"fair-SA", "winner-kernel ALNS"}
        ]
        lines.append("One-line conclusion: " + "; ".join(pieces))
    lines.extend(
        [
            "",
            f"Commit: {manifest['commit_hash']}",
            f"Environment: {manifest['system_python']}, numpy {manifest['numpy']}",
            f"Eval budget/runtime: {manifest['eval_budget']} / {manifest['max_runtime_seconds']}s",
            "",
            "## Verdicts",
        ]
    )
    for row in verdicts:
        lines.append(
            f"- {row['instance']} {row['algorithm']}: {row['verdict']}; "
            f"mean={float(row['mean_total_cost']):.6f}, gap_vs_winner={float(row['gap_vs_winner_pct']):.3f}%, "
            f"wins_alg_lower_than_winner={row['wins_alg_lower_than_winner']}/{row['paired_pairs_vs_winner']}, "
            f"p={float(row['p_value_alg_less_than_winner']):.6g}, commit={row['commit_hash']}."
        )
    if halt_rows:
        lines.extend(["", "## HALT Rows"])
        for row in halt_rows[:40]:
            lines.append(f"- {row['instance']} {row['algorithm']} seed{row['seed']}: {row['status']} evals={row['evaluations']}/{row['eval_budget']} violations={row['violation_count']}.")
    lines.extend(["", "## Method"])
    lines.append("All complete candidates are scored by evaluate/check through EvalBudget; model_cost is used only for final unpenalized reporting. Runs with violations or under-target evaluations are marked HALT and are not evidence for wins.")
    return "\n".join(lines) + "\n"


def _profile_report(summaries: list[dict[str, Any]], bucket_rows: list[dict[str, Any]], manifest: dict[str, Any]) -> str:
    lines = [
        "# Metaheuristic Baseline Profile",
        "",
        "One-line conclusion: profile is a throughput diagnostic only; dominance claims require the formal comparison gate.",
        "",
        f"Commit: {manifest['commit_hash']}",
        f"Environment: {manifest['system_python']}, numpy {manifest['numpy']}",
        f"Instance/seed/evals: {manifest['instance']} / {manifest['seed']} / {manifest['eval_budget']}",
        "",
        "## Throughput",
    ]
    for row in sorted(summaries, key=lambda item: str(item["algorithm"])):
        projected = float(row["projected_16000_seconds"])
        decision = "900s" if bool(row["meets_16000_900s"]) else "3600s/HALT"
        lines.append(
            f"- {row['algorithm']}: status={row['status']}, eval/s={float(row['evals_per_second']):.3f}, "
            f"projected_16000={projected:.1f}s, cap_decision={decision}, best_cost={row['best_cost']}."
        )
    lines.extend(["", "## Time Buckets"])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in bucket_rows:
        grouped.setdefault(str(row["algorithm"]), []).append(row)
    for algorithm in sorted(grouped):
        pieces = []
        for row in sorted(grouped[algorithm], key=lambda item: float(item["bucket_seconds"]), reverse=True):
            if float(row["bucket_seconds"]) <= 1e-9 and int(row["bucket_count"]) == 0:
                continue
            pieces.append(f"{row['bucket']}={float(row['bucket_share_pct']):.1f}%/{int(row['bucket_count'])}x")
        lines.append(f"- {algorithm}: " + "; ".join(pieces))
    lines.extend(
        [
            "",
            "## Method",
            "The profile wraps decode, evaluate, check_solution, and EV charging repair call sites in-process. Bucket shares are diagnostic and may overlap less than cProfile; the formal gate is still full eval count, zero violations, and system Python/numpy.",
        ]
    )
    return "\n".join(lines) + "\n"


def _ensure_environment() -> None:
    if Path(sys.executable) != Path(SYSTEM_PYTHON):
        raise SystemExit(f"HALT_ENVIRONMENT: expected {SYSTEM_PYTHON}, got {sys.executable}")
    if np.__version__ != SYSTEM_NUMPY:
        raise SystemExit(f"HALT_ENVIRONMENT: expected numpy {SYSTEM_NUMPY}, got {np.__version__}")


def _selected_instances(names: list[str]) -> dict[str, Path]:
    if names == ["all"]:
        requested = list(DEFAULT_INSTANCES)
    else:
        requested = names
    selected: dict[str, Path] = {}
    for name in requested:
        if name not in INSTANCE_DIRS:
            raise ValueError(f"Unknown instance {name!r}; available={sorted(INSTANCE_DIRS)}")
        selected[name] = INSTANCE_DIRS[name]
    return selected


def _raw_result_row(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "solution"}


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _result_from_raw_row(previous_output_dir: Path, row: dict[str, str]) -> dict[str, Any]:
    solution_path = previous_output_dir / "solutions" / f"{row['instance']}_{_safe_name(row['algorithm'])}_seed{row['seed']}.json"
    solution = json.loads(solution_path.read_text(encoding="utf-8")) if solution_path.exists() else None
    try:
        history = ast.literal_eval(row.get("history", "[]") or "[]")
    except (SyntaxError, ValueError):
        history = []
    return {
        "instance": row["instance"],
        "bundle_dir": row["bundle_dir"],
        "algorithm": row["algorithm"],
        "seed": int(row["seed"]),
        "evaluations": int(float(row["evaluations"])),
        "eval_budget": int(float(row["eval_budget"])),
        "max_runtime_seconds": float(row["max_runtime_seconds"]),
        "elapsed_seconds": float(row["elapsed_seconds"]),
        "best_cost": float(row["best_cost"]) if row.get("best_cost") not in {"", None} else math.inf,
        "status": row["status"],
        "source": row.get("source", ""),
        "violation_count": int(float(row.get("violation_count", 0) or 0)),
        "history": history if isinstance(history, list) else [],
        "solution": solution,
    }


def _write_preflight(repo_root: Path, out: Path) -> None:
    preflight = out / "preflight"
    preflight.mkdir(parents=True, exist_ok=True)
    commands = {
        "git_status": ["git", "status", "--short"],
        "protected_diff": ["git", "diff", "--name-only", "--", "solver/src/setp_solver/cost.py", "solver/src/setp_solver/check.py", "solver/src/setp_solver/search/evaluation.py"],
    }
    for name, cmd in commands.items():
        proc = subprocess.run(cmd, cwd=repo_root, text=True, capture_output=True, check=False)
        (preflight / f"{name}.stdout.txt").write_text(proc.stdout, encoding="utf-8")
        (preflight / f"{name}.stderr.txt").write_text(proc.stderr, encoding="utf-8")


def _git_commit(repo_root: Path) -> str:
    proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_root, text=True, capture_output=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else "UNKNOWN"


def _write_json(path: str | Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({field for row in rows for field in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _safe_name(value: str) -> str:
    return str(value).replace("/", "_").replace(" ", "_")


def _parse_seed_list(text: str) -> list[int]:
    seeds: list[int] = []
    for part in str(text).split(","):
        chunk = part.strip()
        if not chunk:
            continue
        if "-" in chunk:
            left, right = chunk.split("-", 1)
            seeds.extend(range(int(left), int(right) + 1))
        else:
            seeds.append(int(chunk))
    return sorted(dict.fromkeys(seeds))


def _parse_instances(text: str) -> list[str]:
    values = [item.strip() for item in str(text).split(",") if item.strip()]
    return values or ["all"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ReSETP metaheuristic baseline comparison.")
    parser.add_argument("stage", choices=["all", "profile", "complete-fallback"])
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[4]))
    parser.add_argument("--output-dir", default="baselines")
    parser.add_argument("--previous-output-dir", default="")
    parser.add_argument("--instances", default="all")
    parser.add_argument("--profile-instance", default=ALNS_DEFAULT_INSTANCE_ORDER[0])
    parser.add_argument("--seeds", default="1-10")
    parser.add_argument("--eval-budget", type=int, default=DEFAULT_EVAL_BUDGET)
    parser.add_argument("--max-runtime-seconds", type=float, default=DEFAULT_MAX_RUNTIME_SECONDS)
    parser.add_argument("--fallback-max-runtime-seconds", type=float, default=DEFAULT_FALLBACK_MAX_RUNTIME_SECONDS)
    parser.add_argument("--auto-runtime-fallback", action="store_true")
    parser.add_argument("--speed-probe-eval-budget", type=int, default=DEFAULT_PROFILE_EVAL_BUDGET)
    parser.add_argument("--algorithms", default=",".join(BASELINE_ALGORITHMS))
    args = parser.parse_args(argv)
    selected_algorithms = [item.strip() for item in args.algorithms.split(",") if item.strip()]
    if args.stage == "profile":
        result = run_profile(
            args.repo_root,
            args.output_dir,
            instance=args.profile_instance,
            seed=_parse_seed_list(args.seeds)[0],
            eval_budget=args.speed_probe_eval_budget,
            max_runtime_seconds=args.max_runtime_seconds,
            algorithms=selected_algorithms or list(PROFILE_ALGORITHMS),
            prices=UK_2025_PRICES,
        )
        print(f"GATE METAHEURISTIC_BASELINES_PROFILE {result['gate']} {json.dumps(result, ensure_ascii=False)}")
        return 0
    if args.stage == "complete-fallback":
        if not args.previous_output_dir:
            raise SystemExit("HALT_ARGUMENTS: --previous-output-dir is required for complete-fallback")
        result = run_fallback_completion(
            args.repo_root,
            args.previous_output_dir,
            args.output_dir,
            fallback_max_runtime_seconds=args.fallback_max_runtime_seconds,
            prices=UK_2025_PRICES,
        )
        print(f"GATE METAHEURISTIC_BASELINES_FALLBACK {result['gate']} {json.dumps(result, ensure_ascii=False)}")
        return 0
    result = run_all(
        args.repo_root,
        args.output_dir,
        instances=_parse_instances(args.instances),
        seeds=_parse_seed_list(args.seeds),
        eval_budget=args.eval_budget,
        max_runtime_seconds=args.max_runtime_seconds,
        fallback_max_runtime_seconds=args.fallback_max_runtime_seconds,
        auto_runtime_fallback=args.auto_runtime_fallback,
        speed_probe_eval_budget=args.speed_probe_eval_budget,
        algorithms=selected_algorithms,
        prices=UK_2025_PRICES,
    )
    print(f"GATE METAHEURISTIC_BASELINES {result['gate']} {json.dumps(result, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
