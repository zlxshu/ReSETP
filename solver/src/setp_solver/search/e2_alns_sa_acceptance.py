"""Gate runner for the E2 ALNS simulated-annealing acceptance continuation."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

import numpy as np

from .alns_crush_v2 import _parse_seed_list
from .bundle import load_search_bundle
from .candidates import make_shared_initial_solution
from .metaheuristic_baselines import run_metaheuristic_baseline
from .winner_operators import WinnerKernelConfig, e2_alns_sa_acceptance_flags, run_e2_alns_sa_acceptance


GATE_INSTANCES = {
    "e2-threeshift-50c-01": {
        "category": "threeshift",
        "bundle_dir": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-50c-01",
        "runtime_seconds": 300.0,
    },
    "e2-threeshift-75c-01": {
        "category": "threeshift",
        "bundle_dir": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-75c-01",
        "runtime_seconds": 300.0,
    },
    "e2-threeshift-100c-01": {
        "category": "threeshift",
        "bundle_dir": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-100c-01",
        "runtime_seconds": 300.0,
    },
    "e2-threeshift-150c-01": {
        "category": "threeshift",
        "bundle_dir": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-150c-01",
        "runtime_seconds": 900.0,
    },
    "e2-threeshift-200c-01": {
        "category": "threeshift",
        "bundle_dir": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-200c-01",
        "runtime_seconds": 900.0,
    },
    "e2-vanilla-100c-01": {
        "category": "vanilla",
        "bundle_dir": "models/data_bundle/generated_instances/e2_benchmark/vanilla/e2-vanilla-100c-01",
        "runtime_seconds": 300.0,
    },
    "e2-vanilla-200c-01": {
        "category": "vanilla",
        "bundle_dir": "models/data_bundle/generated_instances/e2_benchmark/vanilla/e2-vanilla-200c-01",
        "runtime_seconds": 900.0,
    },
    "e2-multidepot-100c-01": {
        "category": "multidepot",
        "bundle_dir": "models/data_bundle/generated_instances/e2_benchmark/multidepot/e2-multidepot-100c-01",
        "runtime_seconds": 300.0,
    },
    "e2-multidepot-200c-01": {
        "category": "multidepot",
        "bundle_dir": "models/data_bundle/generated_instances/e2_benchmark/multidepot/e2-multidepot-200c-01",
        "runtime_seconds": 900.0,
    },
}

ALGORITHMS = ("alns_sa_autofit", "alns_sa_lns_cooling", "LNS")
SA_ALGORITHMS = ("alns_sa_autofit", "alns_sa_lns_cooling")
HARD_TIMEOUT_GRACE_SECONDS = 15.0


def run_gate(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int] | None = None,
    instances: list[str] | None = None,
    eval_budget: int = 16_000,
    runtime_override: float | None = None,
    workers: int = 1,
    update_report: bool = True,
) -> dict[str, Any]:
    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    selected_seeds = [1, 2, 3, 4, 5] if seeds is None else [int(seed) for seed in seeds]
    selected_instances = list(GATE_INSTANCES) if instances is None else [str(item) for item in instances]
    commit_hash = _git(["rev-parse", "HEAD"], root).strip()
    tasks: list[dict[str, Any]] = []
    for instance_name in selected_instances:
        spec = GATE_INSTANCES[instance_name]
        runtime_seconds = float(runtime_override if runtime_override is not None else spec["runtime_seconds"])
        for seed in selected_seeds:
            for algorithm in ALGORITHMS:
                tasks.append(
                    {
                        "repo_root": str(root),
                        "commit_hash": commit_hash,
                        "instance": instance_name,
                        "category": spec["category"],
                        "bundle_dir": spec["bundle_dir"],
                        "algorithm": algorithm,
                        "seed": int(seed),
                        "eval_budget": int(eval_budget),
                        "runtime_cap_seconds": runtime_seconds,
                    }
                )
    started = time.perf_counter()
    rows = _run_tasks(tasks, workers=max(1, int(workers)), repo_root=root)
    rows.sort(key=lambda row: (row["instance"], row["algorithm"], int(row["seed"])))
    _write_convergence_files(out / "convergence", rows)
    summary_rows = _summary_rows(rows)
    verdict = _verdict(rows, summary_rows)
    manifest = {
        "schema_version": "setp-e2-alns-sa-acceptance-gate.v1",
        "status": verdict["verdict"],
        "selected_variant": verdict.get("selected_variant", ""),
        "commit_hash": commit_hash,
        "system_python": sys.executable,
        "numpy": np.__version__,
        "seeds": selected_seeds,
        "instances": selected_instances,
        "algorithms": list(ALGORITHMS),
        "eval_budget_backstop": int(eval_budget),
        "runtime_override": runtime_override,
        "elapsed_seconds": time.perf_counter() - started,
        "wall_clock_fairness": "runtime cap by instance size; eval budget is a high diagnostic backstop only",
    }
    _write_csv(out / "sa_raw_runs.csv", rows)
    _write_csv(out / "sa_summary.csv", summary_rows)
    _write_json(out / "sa_verdict.json", verdict)
    _write_json(out / "verdict.json", verdict)
    _write_json(out / "sa_manifest.json", manifest)
    if update_report:
        _write_markdown_report(out / "sa_acceptance_gate.md", summary_rows, verdict, manifest)
    return {"gate": verdict["verdict"], "manifest": str(out / "sa_manifest.json"), "elapsed_seconds": manifest["elapsed_seconds"]}


def _run_tasks(tasks: list[dict[str, Any]], *, workers: int, repo_root: Path) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="setp_e2_sa_tasks_") as tmp:
        task_root = Path(tmp)
        if workers <= 1:
            return [_run_task_subprocess(task, repo_root=repo_root, task_root=task_root, task_index=idx) for idx, task in enumerate(tasks)]
        rows: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(_run_task_subprocess, task, repo_root=repo_root, task_root=task_root, task_index=idx)
                for idx, task in enumerate(tasks)
            ]
            for future in as_completed(futures):
                rows.append(future.result())
        return rows


def _run_task_subprocess(task: dict[str, Any], *, repo_root: Path, task_root: Path, task_index: int) -> dict[str, Any]:
    task_path = task_root / f"task_{task_index}.json"
    output_path = task_root / f"task_{task_index}_row.json"
    task_path.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    timeout_seconds = float(task["runtime_cap_seconds"]) + HARD_TIMEOUT_GRACE_SECONDS
    command = [
        sys.executable,
        "-m",
        "setp_solver.search.e2_alns_sa_acceptance",
        "--task-json",
        str(task_path),
        "--task-output-json",
        str(output_path),
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
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
    algorithm = str(task["algorithm"])
    seed = int(task["seed"])
    eval_budget = int(task["eval_budget"])
    runtime_cap = float(task["runtime_cap_seconds"])
    started = time.perf_counter()
    flags: dict[str, str] = {}
    history: list[dict[str, Any]] = []
    if algorithm.startswith("alns_sa_"):
        mode = algorithm.removeprefix("alns_sa_")
        flags = e2_alns_sa_acceptance_flags(mode=mode)
        result = run_e2_alns_sa_acceptance(
            bundle_dir,
            config=WinnerKernelConfig(seed=seed, eval_budget=eval_budget, max_runtime_seconds=runtime_cap),
            initial_solution=warm,
            mode=mode,
        )
        solution = result["best_solution"]
        best_cost = float(result["best_cost"])
        evals = int(result["evaluations"])
        violation_count = int(result["violation_count"])
        status = "OK" if violation_count == 0 else "HALT_INFEASIBLE"
        elapsed = float(result["elapsed_seconds"])
        history = list(result.get("history", []))
    elif algorithm == "LNS":
        result = run_metaheuristic_baseline(
            "LNS",
            bundle_dir,
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=runtime_cap,
            initial_solution=warm,
        )
        solution = result.best_solution
        best_cost = float(result.best_cost) if result.best_cost is not None else math.inf
        evals = int(result.evals)
        violation_count = int(result.violation_count)
        status = result.status
        elapsed = float(result.elapsed_seconds)
        history = list(result.history)
    else:
        raise ValueError(f"Unknown SA acceptance gate algorithm: {algorithm}")
    feasible = solution is not None and violation_count == 0 and math.isfinite(best_cost)
    elapsed = max(elapsed, time.perf_counter() - started)
    route_count = len(solution.routes) if solution is not None else 0
    cv_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv") if solution is not None else 0
    ev_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev") if solution is not None else 0
    return {
        "commit_hash": task["commit_hash"],
        "python": sys.executable,
        "numpy": np.__version__,
        "instance": task["instance"],
        "category": task["category"],
        "algorithm": algorithm,
        "seed": seed,
        "runtime_cap_seconds": runtime_cap,
        "elapsed_seconds": elapsed,
        "eval_budget_backstop": eval_budget,
        "actual_evals": evals,
        "best_cost": best_cost,
        "route_count": route_count,
        "cv_route_count": cv_count,
        "ev_route_count": ev_count,
        "violation_count": violation_count,
        "feasible": feasible,
        "status": status,
        "gate_status": "OK" if feasible else "HALT_INFEASIBLE",
        "active_flags": json.dumps(flags, sort_keys=True),
        "_history": history,
    }


def _timeout_row(task: dict[str, Any], *, elapsed: float, stdout: str | bytes | None, stderr: str | bytes | None) -> dict[str, Any]:
    return _failure_row(task, elapsed=elapsed, status="HALT_HARD_TIMEOUT", reason="Worker exceeded runtime cap plus hard-timeout grace.", stdout=stdout, stderr=stderr)


def _worker_error_row(
    task: dict[str, Any],
    *,
    elapsed: float,
    stdout: str | bytes | None,
    stderr: str | bytes | None,
    reason: str = "Worker exited non-zero.",
) -> dict[str, Any]:
    return _failure_row(task, elapsed=elapsed, status="HALT_WORKER_ERROR", reason=reason, stdout=stdout, stderr=stderr)


def _failure_row(
    task: dict[str, Any],
    *,
    elapsed: float,
    status: str,
    reason: str,
    stdout: str | bytes | None,
    stderr: str | bytes | None,
) -> dict[str, Any]:
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
        "best_cost": math.inf,
        "route_count": 0,
        "cv_route_count": 0,
        "ev_route_count": 0,
        "violation_count": -1,
        "feasible": False,
        "status": status,
        "gate_status": status,
        "active_flags": "",
        "failure_reason": reason,
        "worker_stdout_tail": _tail_text(stdout),
        "worker_stderr_tail": _tail_text(stderr),
        "_history": [],
    }


def _tail_text(value: str | bytes | None, *, limit: int = 2000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = value
    return text[-limit:]


def _write_convergence_files(convergence_dir: Path, rows: list[dict[str, Any]]) -> None:
    convergence_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        history = list(row.pop("_history", []))
        path = convergence_dir / f"{row['instance']}__{row['algorithm']}__seed{row['seed']}.csv"
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
                    "current_cost": float(item.get("current_cost", math.nan)),
                    "operator": str(item.get("operator", "")),
                }
            )
        if clean_rows:
            _write_csv(path, clean_rows)
            row["convergence_path"] = str(path)
        else:
            row["convergence_path"] = ""


def _summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    keys = sorted({(row["instance"], row["category"], row["algorithm"]) for row in rows})
    for instance, category, algorithm in keys:
        group = [row for row in rows if row["instance"] == instance and row["algorithm"] == algorithm]
        costs = [float(row["best_cost"]) for row in group]
        out.append(
            {
                "instance": instance,
                "category": category,
                "algorithm": algorithm,
                "n": len(group),
                "mean_cost": statistics.fmean(costs) if costs else math.inf,
                "best_cost": min(costs) if costs else math.inf,
                "std_cost": statistics.stdev(costs) if len(costs) > 1 else 0.0,
                "mean_elapsed_seconds": statistics.fmean(float(row["elapsed_seconds"]) for row in group),
                "mean_actual_evals": statistics.fmean(float(row["actual_evals"]) for row in group),
                "mean_route_count": statistics.fmean(float(row["route_count"]) for row in group),
                "mean_cv_route_count": statistics.fmean(float(row["cv_route_count"]) for row in group),
                "mean_ev_route_count": statistics.fmean(float(row["ev_route_count"]) for row in group),
                "zero_violation_count": sum(1 for row in group if int(row["violation_count"]) == 0),
            }
        )
    return out


def _verdict(rows: list[dict[str, Any]], summary_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if any(row["gate_status"] != "OK" for row in rows):
        return {"verdict": "HALT_INFEASIBLE", "reason": "At least one gate row is infeasible or missing a finite solution."}
    candidate_metrics = {algorithm: _candidate_metrics(rows, summary_rows, algorithm) for algorithm in SA_ALGORITHMS}
    promotions = [metrics for metrics in candidate_metrics.values() if metrics["promote"]]
    if promotions:
        selected = min(promotions, key=lambda item: float(item["overall_gap_pct_alns_minus_lns"]))
        return {
            "verdict": "PROMOTE_SA_E2_ALNS",
            "reason": "A predeclared SA-ALNS variant beats LNS overall, is not worse in any threeshift group, and has LNS-scale variance.",
            "selected_variant": selected["algorithm"],
            "candidate_metrics": candidate_metrics,
        }
    if any(metrics["beaten"] for metrics in candidate_metrics.values()):
        verdict = "HALT_SA_ACCEPTANCE_BEATEN"
        reason = "LNS is significantly better or SA-ALNS is worse by more than 2% in at least two threeshift groups."
    elif any(metrics["tie_not_enough"] for metrics in candidate_metrics.values()):
        verdict = "HALT_ALNS_TIE_NOT_ENOUGH"
        reason = "SA-ALNS reaches the tie band but does not satisfy the user requirement that ALNS win and stabilize."
    else:
        verdict = "HALT_SA_ACCEPTANCE_INCONCLUSIVE"
        reason = "No SA-ALNS variant met promotion, tie, or beaten criteria."
    return {"verdict": verdict, "reason": reason, "selected_variant": "", "candidate_metrics": candidate_metrics}


def _candidate_metrics(rows: list[dict[str, Any]], summary_rows: list[dict[str, Any]], algorithm: str) -> dict[str, Any]:
    paired = _paired_rows(rows, category="threeshift", algorithm=algorithm)
    if not paired:
        return {"algorithm": algorithm, "promote": False, "beaten": False, "tie_not_enough": False, "reason": "No paired threeshift rows."}
    diffs = [pair["alns_cost"] - pair["lns_cost"] for pair in paired]
    p_lns_better = _wilcoxon_lns_better(diffs)
    group_gaps = _instance_gap_percent(paired)
    overall_gap = 100.0 * (statistics.fmean(pair["alns_cost"] for pair in paired) - statistics.fmean(pair["lns_cost"] for pair in paired)) / max(1e-9, statistics.fmean(pair["lns_cost"] for pair in paired))
    wins_or_ties = sum(1 for diff in diffs if diff <= 1e-9)
    std_ratios = _std_ratios(summary_rows, algorithm)
    max_std_ratio = max(std_ratios.values()) if std_ratios else math.inf
    not_worse_every_group = all(gap <= 1e-9 for gap in group_gaps.values())
    tie_band = abs(overall_gap) <= 1.0 and all(abs(gap) <= 2.0 for gap in group_gaps.values())
    beaten_group_count = sum(1 for gap in group_gaps.values() if gap > 2.0)
    promote = (
        not_worse_every_group
        and overall_gap < -1e-9
        and wins_or_ties >= math.ceil(len(diffs) / 2)
        and p_lns_better >= 0.05
        and max_std_ratio <= 2.0
    )
    beaten = p_lns_better < 0.05 or beaten_group_count >= 2
    return {
        "algorithm": algorithm,
        "promote": promote,
        "beaten": beaten,
        "tie_not_enough": tie_band and not promote,
        "overall_gap_pct_alns_minus_lns": overall_gap,
        "group_gap_pct_alns_minus_lns": group_gaps,
        "paired_wins_or_ties_alns": wins_or_ties,
        "paired_count": len(diffs),
        "wilcoxon_p_lns_better": p_lns_better,
        "std_ratio_alns_to_lns": std_ratios,
        "max_std_ratio_alns_to_lns": max_std_ratio,
    }


def _paired_rows(rows: list[dict[str, Any]], *, category: str, algorithm: str) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for row in rows:
        if row["category"] != category:
            continue
        by_key.setdefault((str(row["instance"]), int(row["seed"])), {})[str(row["algorithm"])] = row
    paired: list[dict[str, Any]] = []
    for (instance, seed), algs in sorted(by_key.items()):
        if algorithm not in algs or "LNS" not in algs:
            continue
        paired.append(
            {
                "instance": instance,
                "seed": seed,
                "alns_cost": float(algs[algorithm]["best_cost"]),
                "lns_cost": float(algs["LNS"]["best_cost"]),
            }
        )
    return paired


def _instance_gap_percent(paired: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for instance in sorted({pair["instance"] for pair in paired}):
        group = [pair for pair in paired if pair["instance"] == instance]
        alns = statistics.fmean(pair["alns_cost"] for pair in group)
        lns = statistics.fmean(pair["lns_cost"] for pair in group)
        out[instance] = 100.0 * (alns - lns) / max(1e-9, lns)
    return out


def _std_ratios(summary_rows: list[dict[str, Any]], algorithm: str) -> dict[str, float]:
    by_key = {(row["instance"], row["algorithm"]): row for row in summary_rows if row["category"] == "threeshift"}
    ratios: dict[str, float] = {}
    for instance in sorted({row["instance"] for row in summary_rows if row["category"] == "threeshift"}):
        alg_row = by_key.get((instance, algorithm))
        lns_row = by_key.get((instance, "LNS"))
        if alg_row is None or lns_row is None:
            continue
        ratios[instance] = float(alg_row["std_cost"]) / max(1e-9, float(lns_row["std_cost"]))
    return ratios


def _wilcoxon_lns_better(diffs: list[float]) -> float:
    if not diffs or all(abs(diff) <= 1e-12 for diff in diffs):
        return 1.0
    try:
        from scipy.stats import wilcoxon

        return float(wilcoxon(diffs, alternative="greater").pvalue)
    except Exception:
        positives = sum(1 for diff in diffs if diff > 0)
        return 0.0 if positives == len(diffs) else 1.0


def _write_markdown_report(path: Path, summary_rows: list[dict[str, Any]], verdict: dict[str, Any], manifest: dict[str, Any]) -> None:
    lines = [
        "# E2 ALNS SA Acceptance Gate",
        "",
        f"Gate: `{verdict['verdict']}`",
        "",
        f"Reason: {verdict['reason']}",
        "",
        f"Commit: `{manifest['commit_hash']}`; Python: `{manifest['system_python']}`; NumPy: `{manifest['numpy']}`.",
        "",
        f"Seeds: {manifest['seeds']}; eval budget is a diagnostic backstop `{manifest['eval_budget_backstop']}`.",
        "",
        "| instance | algorithm | n | mean | best | std | mean seconds | mean evals | routes | CV | EV | zero violations |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in sorted(summary_rows, key=lambda item: (item["instance"], item["algorithm"])):
        lines.append(
            "| {instance} | {algorithm} | {n} | {mean_cost:.6f} | {best_cost:.6f} | {std_cost:.6f} | "
            "{mean_elapsed_seconds:.3f} | {mean_actual_evals:.1f} | {mean_route_count:.2f} | "
            "{mean_cv_route_count:.2f} | {mean_ev_route_count:.2f} | {zero_violation_count} |".format(**row)
        )
    lines.extend(["", "## Candidate Metrics", ""])
    for algorithm, metrics in sorted(verdict.get("candidate_metrics", {}).items()):
        lines.extend(
            [
                f"### {algorithm}",
                "",
                f"- Overall threeshift gap ALNS-LNS: `{metrics.get('overall_gap_pct_alns_minus_lns', math.nan):.6f}%`",
                f"- Group gaps: `{json.dumps(metrics.get('group_gap_pct_alns_minus_lns', {}), sort_keys=True)}`",
                f"- Paired wins/ties ALNS: `{metrics.get('paired_wins_or_ties_alns', 0)}/{metrics.get('paired_count', 0)}`",
                f"- Wilcoxon p, LNS better: `{metrics.get('wilcoxon_p_lns_better', math.nan)}`",
                f"- Max std ratio ALNS/LNS: `{metrics.get('max_std_ratio_alns_to_lns', math.nan)}`",
                "",
            ]
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({field for row in rows for field in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: str | Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True).stdout


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the E2 ALNS SA-acceptance gate.")
    parser.add_argument("--repo-root", default=str(_repo_root()))
    parser.add_argument("--output-dir", default="baselines/e2_alns")
    parser.add_argument("--task-json", default="")
    parser.add_argument("--task-output-json", default="")
    parser.add_argument("--seeds", default="1-5")
    parser.add_argument("--instances", default="")
    parser.add_argument("--eval-budget", type=int, default=16_000)
    parser.add_argument("--runtime-override", type=float, default=None)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--no-report-update", action="store_true")
    args = parser.parse_args(argv)
    if args.task_json:
        task = json.loads(Path(args.task_json).read_text(encoding="utf-8"))
        row = _run_one(task)
        if not args.task_output_json:
            raise ValueError("--task-output-json is required with --task-json")
        Path(args.task_output_json).write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        return 0
    instances = [item.strip() for item in args.instances.split(",") if item.strip()] or None
    result = run_gate(
        args.repo_root,
        args.output_dir,
        seeds=_parse_seed_list(args.seeds),
        instances=instances,
        eval_budget=args.eval_budget,
        runtime_override=args.runtime_override,
        workers=args.workers,
        update_report=not args.no_report_update,
    )
    print(f"GATE E2_ALNS_SA_ACCEPTANCE {json.dumps(result, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
