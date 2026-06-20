"""Fair comparison runner for transcript-backed metaheuristic baselines."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
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
from ..prices import DEFAULT_PRICES
from .alns_crush import INSTANCE_DIRS
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


SYSTEM_PYTHON = "/opt/anaconda3/bin/python3.13"
SYSTEM_NUMPY = "2.3.5"
DEFAULT_EVAL_BUDGET = 16_000
DEFAULT_MAX_RUNTIME_SECONDS = 900.0
DEFAULT_INSTANCES = ("100-01-24h", "L-main", "Scale-150", "Scale-200")


def run_all(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    instances: list[str],
    seeds: list[int],
    eval_budget: int = DEFAULT_EVAL_BUDGET,
    max_runtime_seconds: float = DEFAULT_MAX_RUNTIME_SECONDS,
    algorithms: list[str] | None = None,
) -> dict[str, Any]:
    _ensure_environment()
    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_preflight(root, out)
    selected = _selected_instances(instances)
    selected_algorithms = algorithms or list(BASELINE_ALGORITHMS)
    started = time.perf_counter()

    tasks: list[tuple[str, str, str, int, int, float]] = []
    for instance_name, rel_dir in selected.items():
        bundle_dir = str(root / rel_dir)
        for seed in seeds:
            tasks.append(("fair-SA", instance_name, bundle_dir, int(seed), int(eval_budget), float(max_runtime_seconds)))
            tasks.append(("winner-kernel ALNS", instance_name, bundle_dir, int(seed), int(eval_budget), float(max_runtime_seconds)))
            for algorithm in selected_algorithms:
                tasks.append((algorithm, instance_name, bundle_dir, int(seed), int(eval_budget), float(max_runtime_seconds)))

    results = _run_parallel(tasks)
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
        row = cost_breakdown_row(result["instance"], result["algorithm"], int(result["seed"]), solution, bundle.instance, bundle.carbon_profile)
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
    _write_csv(out / "raw_runs.csv", raw_rows)
    _write_csv(out / "comparison_table.csv", comparison)
    _write_csv(out / "wilcoxon.csv", wilcoxon)
    _write_csv(out / "verdicts.csv", verdicts)
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
        "algorithms": ["fair-SA", "winner-kernel ALNS", *selected_algorithms],
        "elapsed_seconds": time.perf_counter() - started,
        "status": "HALT_BASELINE_INCOMPARABLE" if halt_rows else "OK",
        "outputs": ["raw_runs.csv", "comparison_table.csv", "wilcoxon.csv", "verdicts.csv", "report.md", "manifest.json"],
    }
    _write_json(out / "manifest.json", manifest)
    (out / "report.md").write_text(_report(verdicts, comparison, halt_rows, manifest), encoding="utf-8")
    return {"gate": manifest["status"], "manifest": str(out / "manifest.json"), "elapsed_seconds": manifest["elapsed_seconds"]}


def _run_task(task: tuple[str, str, str, int, int, float]) -> dict[str, Any]:
    algorithm, instance_name, bundle_dir, seed, eval_budget, max_runtime_seconds = task
    bundle = load_search_bundle(bundle_dir)
    warm = make_shared_initial_solution(bundle)
    started = time.perf_counter()
    if algorithm == "fair-SA":
        run = run_candidate(
            "scikit-opt-SA",
            bundle_dir,
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            initial_solution=warm,
        )
        solution = run.best_solution
        status = "OK" if solution is not None and int(run.evals) >= int(eval_budget) else run.status
        source = "Existing fair scikit-opt-SA adapter under common referee"
        evaluations = int(run.evals)
        best_cost = run.best_cost
        elapsed = float(run.elapsed_seconds)
    elif algorithm == "winner-kernel ALNS":
        run = run_winner_kernel(
            bundle_dir,
            config=WinnerKernelConfig(seed=seed, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds),
            initial_solution=warm,
        )
        solution = run["best_solution"]
        status = "OK" if run["feasible"] and int(run["evaluations"]) >= int(eval_budget) else "HALT_WINNER_INCOMPARABLE"
        source = "winner_operators.run_winner_kernel"
        evaluations = int(run["evaluations"])
        best_cost = float(run["best_cost"])
        elapsed = float(run["elapsed_seconds"])
    else:
        run = run_metaheuristic_baseline(
            algorithm,
            bundle_dir,
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            initial_solution=warm,
        )
        solution = run.best_solution
        status = run.status
        source = run.source
        evaluations = int(run.evals)
        best_cost = run.best_cost
        elapsed = float(run.elapsed_seconds)
    violations = check_solution(solution, bundle.instance, DEFAULT_PRICES) if solution is not None else []
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
        "solution": solution_to_dict(solution) if solution is not None else None,
    }


def _run_parallel(tasks: list[tuple[str, str, str, int, int, float]]) -> list[dict[str, Any]]:
    max_workers = max(1, min(len(tasks), int(os.environ.get("SETP_META_PARALLEL_WORKERS", os.cpu_count() or 2))))
    if max_workers == 1:
        return [_run_task(task) for task in tasks]
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_run_task, task) for task in tasks]
        for future in as_completed(futures):
            results.append(future.result())
    return results


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
    parser.add_argument("stage", choices=["all"])
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[4]))
    parser.add_argument("--output-dir", default="baselines")
    parser.add_argument("--instances", default="100-01-24h,L-main,Scale-150,Scale-200")
    parser.add_argument("--seeds", default="1-10")
    parser.add_argument("--eval-budget", type=int, default=DEFAULT_EVAL_BUDGET)
    parser.add_argument("--max-runtime-seconds", type=float, default=DEFAULT_MAX_RUNTIME_SECONDS)
    parser.add_argument("--algorithms", default=",".join(BASELINE_ALGORITHMS))
    args = parser.parse_args(argv)
    result = run_all(
        args.repo_root,
        args.output_dir,
        instances=_parse_instances(args.instances),
        seeds=_parse_seed_list(args.seeds),
        eval_budget=args.eval_budget,
        max_runtime_seconds=args.max_runtime_seconds,
        algorithms=[item.strip() for item in args.algorithms.split(",") if item.strip()],
    )
    print(f"GATE METAHEURISTIC_BASELINES {result['gate']} {json.dumps(result, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
