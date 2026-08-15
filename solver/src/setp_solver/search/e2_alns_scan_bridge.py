"""Gate runner for the E2 ALNS scan-bridge continuation."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any

import numpy as np

from .alns_crush_v2 import _parse_seed_list
from .bundle import load_search_bundle
from .candidates import make_shared_initial_solution
from .metaheuristic_baselines import run_metaheuristic_baseline
from ..prices import UK_2025_PRICES
from .winner_operators import WinnerKernelConfig, e2_alns_scan_bridge_flags, run_e2_alns_scan_bridge


GATE_INSTANCES = {
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
    "e2-multidepot-100c-01": {
        "category": "multidepot",
        "bundle_dir": "models/data_bundle/generated_instances/e2_benchmark/multidepot/e2-multidepot-100c-01",
        "runtime_seconds": 300.0,
    },
}

ALGORITHMS = ("alns_scan_bridge", "LNS")


def run_gate(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int] | None = None,
    instances: list[str] | None = None,
    eval_budget: int = 16_000,
    runtime_override: float | None = None,
    workers: int = 1,
    update_reports: bool = True,
) -> dict[str, Any]:
    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    selected_seeds = [1, 2, 3] if seeds is None else [int(seed) for seed in seeds]
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
    rows = _run_tasks(tasks, workers=max(1, int(workers)))
    rows.sort(key=lambda row: (row["instance"], row["algorithm"], int(row["seed"])))
    summary_rows = _summary_rows(rows)
    verdict = _verdict(rows)
    manifest = {
        "schema_version": "setp-e2-alns-scan-bridge-gate.v1",
        "status": verdict["verdict"],
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
    _write_csv(out / "scan_bridge_raw_runs.csv", rows)
    _write_csv(out / "scan_bridge_summary.csv", summary_rows)
    _write_json(out / "scan_bridge_verdict.json", verdict)
    _write_json(out / "scan_bridge_manifest.json", manifest)
    if update_reports:
        _update_markdown_reports(root, summary_rows, verdict, manifest)
    return {"gate": verdict["verdict"], "manifest": str(out / "scan_bridge_manifest.json"), "elapsed_seconds": manifest["elapsed_seconds"]}


def _run_tasks(tasks: list[dict[str, Any]], *, workers: int) -> list[dict[str, Any]]:
    if workers <= 1:
        return [_run_one(task) for task in tasks]
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run_one, task) for task in tasks]
        for future in as_completed(futures):
            rows.append(future.result())
    return rows


def _run_one(task: dict[str, Any]) -> dict[str, Any]:
    root = Path(task["repo_root"])
    bundle_dir = root / str(task["bundle_dir"])
    bundle = load_search_bundle(bundle_dir)
    warm = make_shared_initial_solution(bundle, UK_2025_PRICES)
    algorithm = str(task["algorithm"])
    seed = int(task["seed"])
    eval_budget = int(task["eval_budget"])
    runtime_cap = float(task["runtime_cap_seconds"])
    started = time.perf_counter()
    flags: dict[str, str] = {}
    if algorithm == "alns_scan_bridge":
        flags = e2_alns_scan_bridge_flags()
        result = run_e2_alns_scan_bridge(
            bundle_dir,
            config=WinnerKernelConfig(seed=seed, eval_budget=eval_budget, max_runtime_seconds=runtime_cap),
            initial_solution=warm,
            prices=UK_2025_PRICES,
        )
        solution = result["best_solution"]
        best_cost = float(result["best_cost"])
        evals = int(result["evaluations"])
        violation_count = int(result["violation_count"])
        status = "OK" if violation_count == 0 else "HALT_INFEASIBLE"
        elapsed = float(result["elapsed_seconds"])
    elif algorithm == "LNS":
        result = run_metaheuristic_baseline(
            "LNS",
            bundle_dir,
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=runtime_cap,
            initial_solution=warm,
            prices=UK_2025_PRICES,
        )
        solution = result.best_solution
        best_cost = float(result.best_cost) if result.best_cost is not None else math.inf
        evals = int(result.evals)
        violation_count = int(result.violation_count)
        status = result.status
        elapsed = float(result.elapsed_seconds)
    else:
        raise ValueError(f"Unknown scan bridge gate algorithm: {algorithm}")
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
    }


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


def _verdict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if any(row["gate_status"] != "OK" for row in rows):
        return {"verdict": "HALT_INFEASIBLE", "reason": "At least one gate row is infeasible or missing a finite solution."}
    paired = _paired_rows(rows, category="threeshift")
    if not paired:
        return {"verdict": "HALT_NO_THREESHIFT_PAIRS", "reason": "No paired threeshift rows were produced."}
    diffs = [pair["alns_cost"] - pair["lns_cost"] for pair in paired]
    p_lns_better = _wilcoxon_lns_better(diffs)
    group_gaps = _instance_gap_percent(paired)
    overall_gap = 100.0 * (statistics.fmean(pair["alns_cost"] for pair in paired) - statistics.fmean(pair["lns_cost"] for pair in paired)) / max(1e-9, statistics.fmean(pair["lns_cost"] for pair in paired))
    wins_or_ties = sum(1 for diff in diffs if diff <= 1e-9)
    not_worse_every_group = all(gap <= 1e-9 for gap in group_gaps.values())
    tie_band = abs(overall_gap) <= 1.0 and all(abs(gap) <= 2.0 for gap in group_gaps.values())
    beaten_group_count = sum(1 for gap in group_gaps.values() if gap > 2.0)
    if not_worse_every_group and wins_or_ties >= math.ceil(len(diffs) / 2) and p_lns_better >= 0.05:
        verdict = "PROMOTE_SCAN_BRIDGE"
        reason = "ALNS scan bridge is not worse than LNS on every threeshift group and LNS is not significantly better."
    elif tie_band:
        verdict = "HALT_FIRST_TIER_TIE_FOR_USER"
        reason = "ALNS scan bridge is within the predeclared first-tier tie band but does not clearly beat LNS."
    elif p_lns_better < 0.05 or beaten_group_count >= 2:
        verdict = "HALT_SCAN_BRIDGE_BEATEN"
        reason = "LNS is significantly better or ALNS is worse by more than 2% in at least two threeshift groups."
    else:
        verdict = "HALT_SCAN_BRIDGE_INCONCLUSIVE"
        reason = "The gate did not meet promotion, tie, or beaten criteria."
    return {
        "verdict": verdict,
        "reason": reason,
        "overall_gap_pct_alns_minus_lns": overall_gap,
        "group_gap_pct_alns_minus_lns": group_gaps,
        "paired_wins_or_ties_alns": wins_or_ties,
        "paired_count": len(diffs),
        "wilcoxon_p_lns_better": p_lns_better,
    }


def _paired_rows(rows: list[dict[str, Any]], *, category: str) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for row in rows:
        if row["category"] != category:
            continue
        by_key.setdefault((str(row["instance"]), int(row["seed"])), {})[str(row["algorithm"])] = row
    paired: list[dict[str, Any]] = []
    for (instance, seed), algs in sorted(by_key.items()):
        if "alns_scan_bridge" not in algs or "LNS" not in algs:
            continue
        paired.append(
            {
                "instance": instance,
                "seed": seed,
                "alns_cost": float(algs["alns_scan_bridge"]["best_cost"]),
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


def _wilcoxon_lns_better(diffs: list[float]) -> float:
    if not diffs or all(abs(diff) <= 1e-12 for diff in diffs):
        return 1.0
    try:
        from scipy.stats import wilcoxon

        return float(wilcoxon(diffs, alternative="greater").pvalue)
    except Exception:
        positives = sum(1 for diff in diffs if diff > 0)
        return 0.0 if positives == len(diffs) else 1.0


def _update_markdown_reports(root: Path, summary_rows: list[dict[str, Any]], verdict: dict[str, Any], manifest: dict[str, Any]) -> None:
    section = _markdown_section(summary_rows, verdict, manifest)
    _replace_section(root / "baselines/e2_alns/ablation.md", "09b Scan Bridge Gate", section)
    _replace_section(root / "baselines/e2_alns/final_report.md", "09b Scan Bridge Gate", section)


def _markdown_section(summary_rows: list[dict[str, Any]], verdict: dict[str, Any], manifest: dict[str, Any]) -> str:
    lines = [
        "## 09b Scan Bridge Gate",
        "",
        f"- Gate: `{verdict['verdict']}`",
        f"- Reason: {verdict['reason']}",
        f"- Commit: `{manifest['commit_hash']}`",
        f"- Python: `{manifest['system_python']}`; NumPy `{manifest['numpy']}`",
        f"- Seeds: {manifest['seeds']}; eval budget is a diagnostic backstop `{manifest['eval_budget_backstop']}`",
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
    lines.extend(
        [
            "",
            f"- Overall threeshift gap ALNS-LNS: `{verdict.get('overall_gap_pct_alns_minus_lns', math.nan):.6f}%`",
            f"- Group gaps: `{json.dumps(verdict.get('group_gap_pct_alns_minus_lns', {}), sort_keys=True)}`",
            f"- Paired wins/ties ALNS: `{verdict.get('paired_wins_or_ties_alns', 0)}/{verdict.get('paired_count', 0)}`",
            f"- Wilcoxon p, LNS better: `{verdict.get('wilcoxon_p_lns_better', math.nan)}`",
        ]
    )
    return "\n".join(lines)


def _replace_section(path: Path, title: str, section: str) -> None:
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    marker = f"## {title}"
    if marker in original:
        before = original.split(marker, 1)[0].rstrip()
        path.write_text(before + "\n\n" + section.rstrip() + "\n", encoding="utf-8")
    else:
        sep = "\n\n" if original.strip() else ""
        path.write_text(original.rstrip() + sep + section.rstrip() + "\n", encoding="utf-8")


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
    parser = argparse.ArgumentParser(description="Run the E2 ALNS scan-bridge gate.")
    parser.add_argument("--repo-root", default=str(_repo_root()))
    parser.add_argument("--output-dir", default="baselines/e2_alns")
    parser.add_argument("--seeds", default="1-3")
    parser.add_argument("--instances", default="")
    parser.add_argument("--eval-budget", type=int, default=16_000)
    parser.add_argument("--runtime-override", type=float, default=None)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--no-report-update", action="store_true")
    args = parser.parse_args(argv)
    instances = [item.strip() for item in args.instances.split(",") if item.strip()] or None
    result = run_gate(
        args.repo_root,
        args.output_dir,
        seeds=_parse_seed_list(args.seeds),
        instances=instances,
        eval_budget=args.eval_budget,
        runtime_override=args.runtime_override,
        workers=args.workers,
        update_reports=not args.no_report_update,
    )
    print(f"GATE E2_ALNS_SCAN_BRIDGE {json.dumps(result, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
