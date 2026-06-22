"""09d E2 ALNS throughput profiling and gate runner."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

import numpy as np

from ..check import check_solution
from ..cost import evaluate
from ..prices import DEFAULT_PRICES
from .bundle import load_search_bundle
from .candidates import make_shared_initial_solution
from .metaheuristic_baselines import run_metaheuristic_baseline, solution_from_dict, solution_to_dict
from .winner_operators import WinnerKernelConfig, e2_alns_throughput_flags, run_e2_alns_throughput


ALGORITHMS = ("alns_e2_throughput", "LNS")
GATE_INSTANCES = (
    ("threeshift", "e2-threeshift-50c-01", 300.0),
    ("threeshift", "e2-threeshift-75c-01", 300.0),
    ("threeshift", "e2-threeshift-100c-01", 300.0),
    ("threeshift", "e2-threeshift-150c-01", 900.0),
    ("threeshift", "e2-threeshift-200c-01", 900.0),
    ("vanilla", "e2-vanilla-100c-01", 300.0),
    ("vanilla", "e2-vanilla-200c-01", 900.0),
    ("multidepot", "e2-multidepot-100c-01", 300.0),
    ("multidepot", "e2-multidepot-200c-01", 900.0),
)
HARD_TIMEOUT_GRACE_SECONDS = 15.0
GOLD_PYTHON = "/opt/anaconda3/bin/python3.13"
GOLD_NUMPY = "2.3.5"


def run_profile(
    repo_root: Path,
    output_dir: Path,
    *,
    phase: str,
    instance: str,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
) -> dict[str, Any]:
    phase = str(phase).strip().lower()
    if phase not in {"before", "after"}:
        raise ValueError("phase must be before or after")
    output_dir.mkdir(parents=True, exist_ok=True)
    task = _task(repo_root, output_dir, "threeshift", instance, "alns_e2_throughput", seed, eval_budget, max_runtime_seconds, profile_phase=phase)
    row = _execute_task_subprocess(repo_root, task, task_index=0, timeout_seconds=max_runtime_seconds + HARD_TIMEOUT_GRACE_SECONDS)
    timings = _timing_rows(row)
    profile_path = output_dir / f"throughput_profile_{phase}.csv"
    _write_csv(profile_path, timings)
    report_path = output_dir / f"throughput_profile_{phase}.md"
    explained = sum(float(item["seconds"]) for item in timings)
    elapsed = float(row.get("elapsed_seconds", 0.0))
    ratio = explained / elapsed if elapsed > 0 else 0.0
    report_path.write_text(
        "\n".join(
            [
                f"# E2 ALNS Throughput Profile {phase}",
                "",
                f"Instance: `{instance}`; seed: `{seed}`; eval budget: `{eval_budget}`; cap: `{max_runtime_seconds}`.",
                f"Status: `{row.get('status')}`; elapsed: `{elapsed:.3f}`; evals: `{row.get('actual_evals')}`; explained ratio: `{ratio:.3f}`.",
                "",
                "If explained ratio is below 0.90, run cProfile before optimizing further.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(output_dir / f"throughput_profile_{phase}.json", {"row": row, "explained_ratio": ratio})
    return {"gate": "PROFILE_COMPLETE" if ratio >= 0.90 else "HALT_PROFILE_UNEXPLAINED", "profile": str(profile_path), "explained_ratio": ratio}


def run_smoke(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    return run_gate(
        repo_root,
        output_dir,
        seeds=[1],
        eval_budget=32,
        workers=1,
        instance_rows=[("vanilla", "e2-vanilla-10c-01", 120.0)],
        command_name="smoke",
    )


def run_gate(
    repo_root: Path,
    output_dir: Path,
    *,
    seeds: list[int],
    eval_budget: int,
    workers: int,
    instance_rows: tuple[tuple[str, str, float], ...] | list[tuple[str, str, float]] = GATE_INSTANCES,
    command_name: str = "gate",
) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "convergence_throughput").mkdir(parents=True, exist_ok=True)
    (output_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
    tasks: list[dict[str, Any]] = []
    for category, instance, cap in instance_rows:
        for seed in seeds:
            for algorithm in ALGORITHMS:
                tasks.append(_task(repo_root, output_dir, category, instance, algorithm, seed, eval_budget, cap))
    rows: list[dict[str, Any]] = []
    if workers <= 1:
        for idx, task in enumerate(tasks):
            rows.append(_execute_task_subprocess(repo_root, task, task_index=idx, timeout_seconds=float(task["runtime_cap_seconds"]) + HARD_TIMEOUT_GRACE_SECONDS))
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        with ProcessPoolExecutor(max_workers=int(workers)) as pool:
            futures = {
                pool.submit(
                    _execute_task_subprocess,
                    repo_root,
                    task,
                    task_index=idx,
                    timeout_seconds=float(task["runtime_cap_seconds"]) + HARD_TIMEOUT_GRACE_SECONDS,
                ): idx
                for idx, task in enumerate(tasks)
            }
            for future in as_completed(futures):
                rows.append(future.result())
    rows.sort(key=lambda row: (str(row["instance"]), int(row["seed"]), str(row["algorithm"])))
    _write_convergence_files(output_dir / "convergence_throughput", rows)
    raw_name = "throughput_raw_runs.csv" if command_name == "gate" else f"throughput_{command_name}_raw_runs.csv"
    _write_csv(output_dir / raw_name, rows)
    summary = _summary_rows(rows)
    _write_csv(output_dir / ("throughput_summary.csv" if command_name == "gate" else f"throughput_{command_name}_summary.csv"), summary)
    verdict = _verdict(rows, summary, repo_root=repo_root, elapsed=time.perf_counter() - started, command_name=command_name)
    _write_json(output_dir / ("throughput_verdict.json" if command_name == "gate" else f"throughput_{command_name}_verdict.json"), verdict)
    if command_name == "gate":
        _write_markdown_report(output_dir / "throughput_gate.md", summary, verdict)
    return {"gate": verdict["verdict"], "elapsed_seconds": verdict["elapsed_seconds"], "rows": len(rows)}


def _task(
    repo_root: Path,
    output_dir: Path,
    category: str,
    instance: str,
    algorithm: str,
    seed: int,
    eval_budget: int,
    runtime_cap_seconds: float,
    *,
    profile_phase: str = "after",
) -> dict[str, Any]:
    checkpoint = output_dir / "checkpoints" / f"{instance}__{algorithm}__seed{seed}.json"
    return {
        "repo_root": str(repo_root),
        "output_dir": str(output_dir),
        "category": category,
        "instance": instance,
        "bundle_dir": str(Path("models/data_bundle/generated_instances/e2_benchmark") / category / instance),
        "algorithm": algorithm,
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "runtime_cap_seconds": float(runtime_cap_seconds),
        "profile_phase": str(profile_phase),
        "checkpoint_path": str(checkpoint),
        "commit_hash": _git_commit(repo_root),
    }


def _execute_task_subprocess(repo_root: Path, task: dict[str, Any], *, task_index: int, timeout_seconds: float) -> dict[str, Any]:
    task_root = Path(task["output_dir"]) / ".throughput_tasks"
    task_root.mkdir(parents=True, exist_ok=True)
    task_path = task_root / f"task_{task_index}.json"
    output_path = task_root / f"task_{task_index}_row.json"
    task_path.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "setp_solver.search.e2_alns_throughput",
        "--task-json",
        str(task_path),
        "--task-output-json",
        str(output_path),
    ]
    env = os.environ.copy()
    env["SETP_E2_ALNS_CHECKPOINT_PATH"] = str(task["checkpoint_path"])
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=repo_root, text=True, capture_output=True, timeout=timeout_seconds, check=False, env=env)
    except subprocess.TimeoutExpired as exc:
        return _timeout_row(task, elapsed=time.perf_counter() - started, stdout=exc.stdout, stderr=exc.stderr)
    if completed.returncode != 0:
        return _worker_error_row(task, elapsed=time.perf_counter() - started, stdout=completed.stdout, stderr=completed.stderr)
    if not output_path.exists():
        return _worker_error_row(task, elapsed=time.perf_counter() - started, stdout=completed.stdout, stderr=completed.stderr, reason="Worker produced no row JSON.")
    return json.loads(output_path.read_text(encoding="utf-8"))


def _run_one(task: dict[str, Any]) -> dict[str, Any]:
    root = Path(task["repo_root"])
    bundle_dir = root / str(task["bundle_dir"])
    bundle = load_search_bundle(bundle_dir)
    warm = make_shared_initial_solution(bundle)
    checkpoint_path = Path(task["checkpoint_path"])
    os.environ["SETP_E2_ALNS_CHECKPOINT_PATH"] = str(checkpoint_path)
    warm_cost = float(evaluate(warm, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)["total_cost"])
    _write_checkpoint(checkpoint_path, warm, best_cost=warm_cost, best_obj=warm_cost, eval_count=0, elapsed_seconds=0.0, operator="shared_warm_start")
    algorithm = str(task["algorithm"])
    seed = int(task["seed"])
    eval_budget = int(task["eval_budget"])
    runtime_cap = float(task["runtime_cap_seconds"])
    started = time.perf_counter()
    history: list[dict[str, Any]] = []
    timings: dict[str, dict[str, float]] = {}
    flags: dict[str, str] = {}
    if algorithm == "alns_e2_throughput":
        profile_phase = str(task.get("profile_phase", "after"))
        route_cache = profile_phase != "before"
        flags = e2_alns_throughput_flags(route_cost_cache=route_cache, timing_ledger=True)
        result = run_e2_alns_throughput(
            bundle_dir,
            config=WinnerKernelConfig(seed=seed, eval_budget=eval_budget, max_runtime_seconds=runtime_cap),
            initial_solution=warm,
            route_cost_cache=route_cache,
            timing_ledger=True,
        )
        solution = result["best_solution"]
        best_cost = float(result["best_cost"])
        evals = int(result["evaluations"])
        violation_count = int(result["violation_count"])
        status = "OK" if violation_count == 0 else "HALT_INFEASIBLE"
        elapsed = float(result["elapsed_seconds"])
        history = list(result.get("history", []))
        timings = dict(result.get("timings", {}))
    elif algorithm == "LNS":
        result = run_metaheuristic_baseline("LNS", bundle_dir, seed=seed, eval_budget=eval_budget, max_runtime_seconds=runtime_cap, initial_solution=warm)
        solution = result.best_solution
        best_cost = float(result.best_cost) if result.best_cost is not None else math.inf
        evals = int(result.evals)
        violation_count = int(result.violation_count)
        status = result.status
        elapsed = float(result.elapsed_seconds)
        history = list(result.history)
    else:
        raise ValueError(f"Unknown throughput algorithm: {algorithm}")
    feasible = solution is not None and violation_count == 0 and math.isfinite(best_cost)
    elapsed = max(elapsed, time.perf_counter() - started)
    return _row_from_solution(task, solution, best_cost, evals, violation_count, status, elapsed, feasible, flags, history, timings)


def _row_from_solution(
    task: dict[str, Any],
    solution: Any,
    best_cost: float,
    evals: int,
    violation_count: int,
    status: str,
    elapsed: float,
    feasible: bool,
    flags: dict[str, str],
    history: list[dict[str, Any]],
    timings: dict[str, dict[str, float]],
) -> dict[str, Any]:
    route_count = len(solution.routes) if solution is not None else 0
    cv_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv") if solution is not None else 0
    ev_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev") if solution is not None else 0
    return {
        "commit_hash": task["commit_hash"],
        "python": sys.executable,
        "numpy": np.__version__,
        "instance": task["instance"],
        "category": task["category"],
        "algorithm": task["algorithm"],
        "seed": int(task["seed"]),
        "runtime_cap_seconds": float(task["runtime_cap_seconds"]),
        "elapsed_seconds": float(elapsed),
        "eval_budget_backstop": int(task["eval_budget"]),
        "actual_evals": int(evals),
        "evals_per_second": float(evals) / float(elapsed) if elapsed > 0 else 0.0,
        "best_cost": float(best_cost),
        "route_count": route_count,
        "cv_route_count": cv_count,
        "ev_route_count": ev_count,
        "violation_count": int(violation_count),
        "feasible": bool(feasible),
        "status": status,
        "gate_status": "OK" if feasible else status,
        "active_flags": json.dumps(flags, sort_keys=True),
        "timings": json.dumps(timings, sort_keys=True),
        "_history": history,
    }


def _timeout_row(task: dict[str, Any], *, elapsed: float, stdout: str | bytes | None, stderr: str | bytes | None) -> dict[str, Any]:
    checkpoint = _read_checkpoint(Path(task["checkpoint_path"]))
    if checkpoint is not None:
        solution = solution_from_dict(checkpoint["solution"])
        bundle = load_search_bundle(Path(task["repo_root"]) / str(task["bundle_dir"]))
        violations = check_solution(solution, bundle.instance, DEFAULT_PRICES)
        cost = float(evaluate(solution, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)["total_cost"]) if not violations else math.inf
        return _row_from_solution(
            task,
            solution,
            cost,
            int(checkpoint.get("eval", 0)),
            len(violations),
            "HALT_HARD_TIMEOUT_WITH_INCUMBENT",
            elapsed,
            len(violations) == 0 and math.isfinite(cost),
            {},
            [],
            {},
        ) | {"failure_reason": "Worker exceeded runtime cap plus hard-timeout grace; returned last feasible checkpoint.", "worker_stdout_tail": _tail_text(stdout), "worker_stderr_tail": _tail_text(stderr)}
    return _failure_row(task, elapsed=elapsed, status="HALT_HARD_TIMEOUT", reason="Worker exceeded runtime cap plus hard-timeout grace and no checkpoint was readable.", stdout=stdout, stderr=stderr)


def _worker_error_row(task: dict[str, Any], *, elapsed: float, stdout: str | bytes | None, stderr: str | bytes | None, reason: str = "Worker exited non-zero.") -> dict[str, Any]:
    return _failure_row(task, elapsed=elapsed, status="HALT_WORKER_ERROR", reason=reason, stdout=stdout, stderr=stderr)


def _failure_row(task: dict[str, Any], *, elapsed: float, status: str, reason: str, stdout: str | bytes | None, stderr: str | bytes | None) -> dict[str, Any]:
    return {
        "commit_hash": task["commit_hash"],
        "python": sys.executable,
        "numpy": np.__version__,
        "instance": task["instance"],
        "category": task["category"],
        "algorithm": task["algorithm"],
        "seed": int(task["seed"]),
        "runtime_cap_seconds": float(task["runtime_cap_seconds"]),
        "elapsed_seconds": float(elapsed),
        "eval_budget_backstop": int(task["eval_budget"]),
        "actual_evals": 0,
        "evals_per_second": 0.0,
        "best_cost": math.inf,
        "route_count": 0,
        "cv_route_count": 0,
        "ev_route_count": 0,
        "violation_count": -1,
        "feasible": False,
        "status": status,
        "gate_status": status,
        "active_flags": "",
        "timings": "{}",
        "failure_reason": reason,
        "worker_stdout_tail": _tail_text(stdout),
        "worker_stderr_tail": _tail_text(stderr),
        "_history": [],
    }


def _write_checkpoint(path: Path, solution: Any, *, best_cost: float, best_obj: float, eval_count: int, elapsed_seconds: float, operator: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "setp-e2-checkpoint.v1",
        "eval": int(eval_count),
        "time_seconds": float(elapsed_seconds),
        "best_cost": float(best_cost),
        "best_obj": float(best_obj),
        "operator": str(operator),
        "solution": solution_to_dict(solution),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_checkpoint(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "solution" not in payload:
            return None
        return payload
    except Exception:
        return None


def _write_convergence_files(convergence_dir: Path, rows: list[dict[str, Any]]) -> None:
    convergence_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        history = list(row.pop("_history", []))
        clean_rows = []
        for item in history:
            clean_rows.append(
                {
                    "instance": row["instance"],
                    "algorithm": row["algorithm"],
                    "seed": row["seed"],
                    "eval": int(item.get("eval", 0)),
                    "time_seconds": float(item.get("time_seconds", math.nan)),
                    "best_cost": float(item.get("best_cost", math.inf)),
                    "best_obj": float(item.get("best_obj", item.get("best_cost", math.inf))),
                    "operator": str(item.get("operator", "")),
                }
            )
        if clean_rows:
            path = convergence_dir / f"{row['instance']}__{row['algorithm']}__seed{row['seed']}.csv"
            _write_csv(path, clean_rows)
            row["convergence_path"] = str(path)
        else:
            row["convergence_path"] = ""


def _timing_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        timings = json.loads(row.get("timings", "{}"))
    except Exception:
        timings = {}
    out = []
    for label, payload in sorted(timings.items()):
        seconds = float(payload.get("seconds", 0.0))
        count = float(payload.get("count", 0.0))
        out.append(
            {
                "instance": row.get("instance", ""),
                "algorithm": row.get("algorithm", ""),
                "seed": row.get("seed", ""),
                "label": label,
                "seconds": seconds,
                "count": count,
                "seconds_per_count": seconds / count if count > 0 else math.nan,
                "share_of_elapsed": seconds / float(row.get("elapsed_seconds", 1.0)) if float(row.get("elapsed_seconds", 0.0)) > 0 else math.nan,
            }
        )
    return out


def _summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["instance"]), str(row["algorithm"])), []).append(row)
    out = []
    for (instance, algorithm), group in sorted(grouped.items()):
        finite = [float(row["best_cost"]) for row in group if math.isfinite(float(row["best_cost"]))]
        eval_rates = [float(row["evals_per_second"]) for row in group if float(row["evals_per_second"]) > 0]
        out.append(
            {
                "instance": instance,
                "algorithm": algorithm,
                "n": len(group),
                "finite_n": len(finite),
                "mean": statistics.fmean(finite) if finite else math.inf,
                "best": min(finite) if finite else math.inf,
                "std": statistics.stdev(finite) if len(finite) > 1 else 0.0,
                "mean_seconds": statistics.fmean(float(row["elapsed_seconds"]) for row in group),
                "mean_evals": statistics.fmean(float(row["actual_evals"]) for row in group),
                "mean_evals_per_second": statistics.fmean(eval_rates) if eval_rates else 0.0,
                "zero_violations": sum(1 for row in group if int(row["violation_count"]) == 0),
                "status_counts": json.dumps(dict(sorted(_counts(str(row["status"]) for row in group).items())), sort_keys=True),
            }
        )
    return out


def _verdict(rows: list[dict[str, Any]], summary_rows: list[dict[str, Any]], *, repo_root: Path, elapsed: float, command_name: str) -> dict[str, Any]:
    env_ok = all(str(row["python"]) == GOLD_PYTHON and str(row["numpy"]) == GOLD_NUMPY for row in rows)
    finite_ok = all(math.isfinite(float(row["best_cost"])) for row in rows)
    zero_ok = all(int(row["violation_count"]) == 0 for row in rows)
    if command_name != "gate":
        return {"verdict": "SMOKE_OK" if env_ok and finite_ok and zero_ok else "HALT_SMOKE", "elapsed_seconds": elapsed}
    summary = {(row["instance"], row["algorithm"]): row for row in summary_rows}
    threeshift = [name for category, name, _ in GATE_INSTANCES if category == "threeshift"]
    group_gaps: dict[str, float] = {}
    throughput_ratios: dict[str, float] = {}
    all_size_not_worse = True
    for instance in threeshift:
        lns = summary.get((instance, "LNS"))
        alns = summary.get((instance, "alns_e2_throughput"))
        if not lns or not alns or not math.isfinite(float(lns["mean"])) or not math.isfinite(float(alns["mean"])):
            all_size_not_worse = False
            continue
        gap = 100.0 * (float(alns["mean"]) - float(lns["mean"])) / float(lns["mean"])
        ratio = float(alns["mean_evals_per_second"]) / max(1e-9, float(lns["mean_evals_per_second"]))
        group_gaps[instance] = gap
        throughput_ratios[instance] = ratio
        if gap > 0.5:
            all_size_not_worse = False
    alns_costs = [float(row["best_cost"]) for row in rows if row["category"] == "threeshift" and row["algorithm"] == "alns_e2_throughput" and math.isfinite(float(row["best_cost"]))]
    lns_costs = [float(row["best_cost"]) for row in rows if row["category"] == "threeshift" and row["algorithm"] == "LNS" and math.isfinite(float(row["best_cost"]))]
    overall_better = bool(alns_costs and lns_costs and statistics.fmean(alns_costs) < statistics.fmean(lns_costs))
    wins_ties = _paired_wins_ties(rows)
    wilcoxon_lns_better = _wilcoxon_lns_better(rows)
    throughput_ok = all(value >= 0.80 for value in throughput_ratios.values()) and float(summary.get(("e2-threeshift-100c-01", "alns_e2_throughput"), {}).get("mean_evals_per_second", 0.0)) >= 25.0
    if not env_ok:
        verdict = "HALT_ENVIRONMENT_MISMATCH"
    elif not finite_ok or not zero_ok:
        verdict = "HALT_THROUGHPUT_INFEASIBLE_OR_MISSING"
    elif throughput_ok and not all_size_not_worse:
        verdict = "HALT_TRUE_GLNS_BETTER_AFTER_THROUGHPUT"
    elif throughput_ok and all_size_not_worse and overall_better and wins_ties["wins_ties"] >= wins_ties["pairs"] / 2 and not wilcoxon_lns_better:
        verdict = "PROMOTE_E2_ALNS_THROUGHPUT"
    else:
        verdict = "HALT_THROUGHPUT_NOT_PROMOTED"
    return {
        "verdict": verdict,
        "elapsed_seconds": elapsed,
        "commit_hash": _git_commit(repo_root),
        "env_ok": env_ok,
        "finite_ok": finite_ok,
        "zero_violation_ok": zero_ok,
        "throughput_ok": throughput_ok,
        "group_gap_pct_alns_minus_lns": group_gaps,
        "throughput_ratio_alns_over_lns": throughput_ratios,
        "paired": wins_ties,
        "wilcoxon_lns_better": wilcoxon_lns_better,
    }


def _paired_wins_ties(rows: list[dict[str, Any]]) -> dict[str, int]:
    by_key: dict[tuple[str, int], dict[str, float]] = {}
    for row in rows:
        if row["category"] != "threeshift" or not math.isfinite(float(row["best_cost"])):
            continue
        by_key.setdefault((str(row["instance"]), int(row["seed"])), {})[str(row["algorithm"])] = float(row["best_cost"])
    pairs = wins = ties = losses = 0
    for pair in by_key.values():
        if "LNS" not in pair or "alns_e2_throughput" not in pair:
            continue
        pairs += 1
        diff = pair["alns_e2_throughput"] - pair["LNS"]
        if abs(diff) <= 1e-9:
            ties += 1
        elif diff < 0:
            wins += 1
        else:
            losses += 1
    return {"pairs": pairs, "wins": wins, "ties": ties, "losses": losses, "wins_ties": wins + ties}


def _wilcoxon_lns_better(rows: list[dict[str, Any]]) -> bool:
    pairs = []
    by_key: dict[tuple[str, int], dict[str, float]] = {}
    for row in rows:
        if row["category"] != "threeshift" or not math.isfinite(float(row["best_cost"])):
            continue
        by_key.setdefault((str(row["instance"]), int(row["seed"])), {})[str(row["algorithm"])] = float(row["best_cost"])
    for pair in by_key.values():
        if "LNS" in pair and "alns_e2_throughput" in pair:
            pairs.append(pair["alns_e2_throughput"] - pair["LNS"])
    if len(pairs) < 2 or all(abs(value) <= 1e-12 for value in pairs):
        return False
    try:
        from scipy.stats import wilcoxon

        return bool(wilcoxon(pairs, alternative="greater").pvalue < 0.05)
    except Exception:
        return False


def _write_markdown_report(path: Path, summary_rows: list[dict[str, Any]], verdict: dict[str, Any]) -> None:
    lines = [
        "# E2 ALNS Throughput Gate",
        "",
        f"Gate: `{verdict['verdict']}`",
        "",
        f"Commit: `{verdict.get('commit_hash', '')}`; elapsed seconds: `{verdict.get('elapsed_seconds', 0.0):.3f}`.",
        "",
        f"Group gaps: `{json.dumps(verdict.get('group_gap_pct_alns_minus_lns', {}), sort_keys=True)}`",
        f"Throughput ratios: `{json.dumps(verdict.get('throughput_ratio_alns_over_lns', {}), sort_keys=True)}`",
        "",
        "| instance | algorithm | n | finite | mean | best | std | mean eval/s | zero violations | statuses |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary_rows:
        lines.append(
            f"| {row['instance']} | {row['algorithm']} | {row['n']} | {row['finite_n']} | {float(row['mean']):.6f} | {float(row['best']):.6f} | {float(row['std']):.6f} | {float(row['mean_evals_per_second']):.3f} | {row['zero_violations']} | `{row['status_counts']}` |"
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row.keys() if not key.startswith("_")})
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not fields:
            return
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_json(path: str | Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _counts(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[str(value)] = out.get(str(value), 0) + 1
    return out


def _tail_text(value: str | bytes | None, *, limit: int = 2000) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    return text[-limit:]


def _git_commit(repo_root: Path) -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True, capture_output=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    profile = sub.add_parser("profile")
    profile.add_argument("--output-dir", default="baselines/e2_alns")
    profile.add_argument("--phase", choices=["before", "after"], default="before")
    profile.add_argument("--instance", default="e2-threeshift-100c-01")
    profile.add_argument("--seed", type=int, default=1)
    profile.add_argument("--eval-budget", type=int, default=256)
    profile.add_argument("--max-runtime-seconds", type=float, default=120.0)
    smoke = sub.add_parser("smoke")
    smoke.add_argument("--output-dir", default="baselines/e2_alns/throughput_smoke")
    gate = sub.add_parser("gate")
    gate.add_argument("--output-dir", default="baselines/e2_alns")
    gate.add_argument("--seeds", default="1-5")
    gate.add_argument("--eval-budget", type=int, default=16_000)
    gate.add_argument("--workers", type=int, default=3)
    parser.add_argument("--task-json", default="")
    parser.add_argument("--task-output-json", default="")
    args = parser.parse_args(argv)
    if args.task_json:
        task = json.loads(Path(args.task_json).read_text(encoding="utf-8"))
        row = _run_one(task)
        if not args.task_output_json:
            raise ValueError("--task-output-json is required with --task-json")
        Path(args.task_output_json).write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        return
    repo_root = Path(__file__).resolve().parents[4]
    if args.command == "profile":
        result = run_profile(repo_root, Path(args.output_dir), phase=args.phase, instance=args.instance, seed=args.seed, eval_budget=args.eval_budget, max_runtime_seconds=args.max_runtime_seconds)
    elif args.command == "smoke":
        result = run_smoke(repo_root, Path(args.output_dir))
    elif args.command == "gate":
        result = run_gate(repo_root, Path(args.output_dir), seeds=_parse_seeds(args.seeds), eval_budget=args.eval_budget, workers=args.workers)
    else:
        parser.error("choose profile, smoke, or gate")
    print(f"GATE E2_ALNS_THROUGHPUT {json.dumps(result, ensure_ascii=False)}")


def _parse_seeds(value: str) -> list[int]:
    out: list[int] = []
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


if __name__ == "__main__":
    main()
