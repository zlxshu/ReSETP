"""ALNS Crush V2 fairness audit and lean-winner experiment runner."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import time
from typing import Any

from ..check import check_solution
from ..cost import evaluate
from ..prices import DEFAULT_PRICES
from ..solution import ChargingAction, CrossSiteService, Route, Solution
from .alns_crush import ALNS_DEFAULT_INSTANCE_ORDER, COMPONENT_FIELDS, INSTANCE_DIRS, cost_breakdown_row
from .bundle import load_search_bundle
from .candidates import make_shared_initial_solution, run_candidate
from .winner_operators import (
    WinnerKernelConfig,
    operator_base_id,
    run_winner_kernel,
    run_winner_kernel_plus_route_elimination,
    winner_operator_module,
    winner_variant_flags,
    write_winner_manifest,
)


FAIR_SA_EVAL_BUDGET = 16_000
FAIR_SA_MAX_RUNTIME_SECONDS = 900.0
PHASE0_SA_100_SEED1 = 5331.576889799002
CRUSH_V2_DIR = Path("solver/reports/alns_crush_v2")
V2_INSTANCE_DIRS = {
    name: INSTANCE_DIRS[name]
    for name in ALNS_DEFAULT_INSTANCE_ORDER
}


def sa_config_diff_from_manifests(phase0: dict[str, Any], phase2: dict[str, Any]) -> dict[str, Any]:
    """Return the audit diff that decides whether Phase2 SA was fair."""

    phase0_budget = int(phase0.get("eval_budget", 0))
    phase2_budget = int(phase2.get("eval_budget", 0))
    phase0_runtime = float(phase0.get("max_runtime_seconds", 0.0))
    phase2_runtime = float(phase2.get("max_runtime_seconds", 0.0))
    return {
        "phase0_eval_budget": phase0_budget,
        "phase2_eval_budget": phase2_budget,
        "phase0_max_runtime_seconds": phase0_runtime,
        "phase2_max_runtime_seconds": phase2_runtime,
        "eval_budget_delta": phase2_budget - phase0_budget,
        "max_runtime_delta_seconds": phase2_runtime - phase0_runtime,
        "phase2_sa_weaker_by_config": phase2_budget < phase0_budget or phase2_runtime < phase0_runtime,
        "fair_sa_eval_budget": FAIR_SA_EVAL_BUDGET,
        "fair_sa_max_runtime_seconds": FAIR_SA_MAX_RUNTIME_SECONDS,
    }


def fair_sa_gap(row: dict[str, Any], fair_reference: dict[str, Any]) -> float:
    """Compute gap against Task1 fair SA, never against Prompt1 Phase2 SA."""

    instance_name = str(row["instance"])
    ref = float(fair_reference["instances"][instance_name]["scikit-opt-SA"]["mean_total_cost"])
    return (float(row["total_cost"]) - ref) / ref * 100.0


def run_task1(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int],
    eval_budget: int = FAIR_SA_EVAL_BUDGET,
    max_runtime_seconds: float = FAIR_SA_MAX_RUNTIME_SECONDS,
    instance_dirs: dict[str, Path] | None = None,
    include_sa_config_audit: bool = True,
) -> dict[str, Any]:
    """Run the fair-SA audit and write Task1 artifacts."""

    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    selected_instances = instance_dirs or V2_INSTANCE_DIRS
    if include_sa_config_audit:
        phase0_manifest = json.loads((root / "solver/reports/alns_crush/phase0/manifest.json").read_text(encoding="utf-8"))
        phase2_manifest = json.loads((root / "solver/reports/alns_crush/phase2/optimized/manifest.json").read_text(encoding="utf-8"))
        diff = sa_config_diff_from_manifests(phase0_manifest, phase2_manifest)
    else:
        diff = {
            "phase0_eval_budget": None,
            "phase2_eval_budget": None,
            "phase0_max_runtime_seconds": None,
            "phase2_max_runtime_seconds": None,
            "eval_budget_delta": None,
            "max_runtime_delta_seconds": None,
            "phase2_sa_weaker_by_config": None,
            "audit_note": "Phase0/Phase2 SA config audit not applicable for this explicit instance subset.",
        }
    diff["fair_sa_eval_budget"] = int(eval_budget)
    diff["fair_sa_max_runtime_seconds"] = float(max_runtime_seconds)
    tasks = [
        (str(root / selected_instances[instance_name]), instance_name, int(seed), int(eval_budget), float(max_runtime_seconds))
        for instance_name in selected_instances
        for seed in seeds
    ]
    results = _run_parallel(tasks, _run_sa_task)
    rows: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda item: (item["instance"], item["seed"])):
        bundle = load_search_bundle(root / selected_instances[result["instance"]])
        solution = _solution_from_dict(result["solution"])
        row = cost_breakdown_row(result["instance"], "scikit-opt-SA", int(result["seed"]), solution, bundle.instance, bundle.carbon_profile)
        row.update({"evaluations": int(result["evaluations"]), "run_elapsed_seconds": float(result["elapsed_seconds"])})
        rows.append(row)
        _write_json(out / "solutions" / f"{result['instance']}_scikit-opt-SA_seed{result['seed']}.json", result["solution"])
    summary = _summary_rows(rows, variant="fair_sa")
    reference = _fair_sa_reference(summary, rows, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds)
    reproduce_row = next((row for row in rows if row["instance"] == "L-main" and int(row["seed"]) == 1), None)
    if reproduce_row is not None:
        diff["phase0_sa_100_seed1_target"] = PHASE0_SA_100_SEED1
        diff["fair_sa_100_seed1_reproduced_cost"] = float(reproduce_row["total_cost"])
        diff["reproduction_abs_delta"] = abs(float(reproduce_row["total_cost"]) - PHASE0_SA_100_SEED1)
        diff["reproduction_close"] = diff["reproduction_abs_delta"] <= 1e-6
    _write_csv(out / "fair_sa_10seed_cost_breakdown.csv", rows)
    _write_csv(out / "fair_sa_10seed_summary.csv", summary)
    _write_json(out / "fair_sa_reference_costs.json", reference)
    _write_json(out / "task1_sa_config_diff.json", diff)
    (out / "task1_sa_config_diff.md").write_text(_sa_diff_report(diff, summary), encoding="utf-8")
    manifest = {
        "schema_version": "setp-alns-crush-v2-task1.v1",
        "seeds": seeds,
        "instances": {name: str(path) for name, path in selected_instances.items()},
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "include_sa_config_audit": bool(include_sa_config_audit),
        "elapsed_seconds": time.perf_counter() - started,
        "outputs": [
            "task1_sa_config_diff.md",
            "fair_sa_10seed_cost_breakdown.csv",
            "fair_sa_10seed_summary.csv",
            "fair_sa_reference_costs.json",
        ],
    }
    _write_json(out / "manifest.json", manifest)
    return {"gate": "TASK1_COMPLETE", "manifest": str(out / "manifest.json"), "elapsed_seconds": manifest["elapsed_seconds"]}


def run_task2(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int],
    eval_budget: int = 80_000,
    max_runtime_seconds: float = 3600.0,
    algorithm: str = "ALNS-Wouda",
    fair_reference_path: str | Path | None = None,
    instance_dirs: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Run long-budget winner-kernel true-best estimates and lower bounds."""

    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    selected_instances = instance_dirs or V2_INSTANCE_DIRS
    fair_reference = _load_json(fair_reference_path or out.parent / "task1" / "fair_sa_reference_costs.json")
    rows = _run_winner_rows(root, seeds=seeds, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds, algorithm=algorithm, include_route_elimination=False, variant="winner_kernel_true_best", out=out, instance_dirs=selected_instances)
    for row in rows:
        row["gap_vs_fair_sa_mean_pct"] = fair_sa_gap(row, fair_reference)
    lower_bounds = [_lower_bound_row(instance_name, load_search_bundle(root / rel_dir)) for instance_name, rel_dir in selected_instances.items()]
    _write_csv(out / "task2_true_best_runs.csv", rows)
    _write_csv(out / "task2_lower_bounds.csv", lower_bounds)
    (out / "task2_headroom_report.md").write_text(_headroom_report(rows, lower_bounds, fair_reference), encoding="utf-8")
    manifest = {
        "schema_version": "setp-alns-crush-v2-task2.v1",
        "seeds": seeds,
        "instances": {name: str(path) for name, path in selected_instances.items()},
        "algorithm": algorithm,
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "elapsed_seconds": time.perf_counter() - started,
        "auto_upgrade_to_160000": False,
        "outputs": ["task2_true_best_runs.csv", "task2_lower_bounds.csv", "task2_headroom_report.md"],
    }
    _write_json(out / "manifest.json", manifest)
    return {"gate": "TASK2_COMPLETE", "manifest": str(out / "manifest.json"), "elapsed_seconds": manifest["elapsed_seconds"]}


def run_task3(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int],
    eval_budget: int = FAIR_SA_EVAL_BUDGET,
    max_runtime_seconds: float = FAIR_SA_MAX_RUNTIME_SECONDS,
    algorithm: str = "ALNS-Wouda",
    fair_reference_path: str | Path | None = None,
    instance_dirs: dict[str, Path] | None = None,
    include_route_elimination_variant: bool = True,
) -> dict[str, Any]:
    """Run lean V2 winner variants against Task1 fair SA."""

    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    selected_instances = instance_dirs or V2_INSTANCE_DIRS
    fair_reference = _load_json(fair_reference_path or out.parent / "task1" / "fair_sa_reference_costs.json")
    rows: list[dict[str, Any]] = []
    rows.extend(_run_winner_rows(root, seeds=seeds, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds, algorithm=algorithm, include_route_elimination=False, variant="winner_kernel_only", out=out, instance_dirs=selected_instances))
    if include_route_elimination_variant:
        rows.extend(_run_winner_rows(root, seeds=seeds, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds, algorithm=algorithm, include_route_elimination=True, variant="winner_kernel_route_elimination", out=out, instance_dirs=selected_instances))
    for row in rows:
        row["gap_vs_fair_sa_mean_pct"] = fair_sa_gap(row, fair_reference)
    summary = _summary_rows(rows, variant="")
    wilcoxon = _wilcoxon_vs_fair_sa(rows, fair_reference)
    verdicts = _task3_verdicts(summary, wilcoxon, fair_reference)
    _write_csv(out / "task3_comparison_cost_breakdown.csv", rows)
    _write_csv(out / "task3_summary.csv", summary)
    _write_csv(out / "task3_wilcoxon_vs_fair_sa.csv", wilcoxon)
    (out / "task3_verdict.md").write_text(_task3_verdict_report(verdicts, summary, wilcoxon), encoding="utf-8")
    manifest = {
        "schema_version": "setp-alns-crush-v2-task3.v1",
        "seeds": seeds,
        "instances": {name: str(path) for name, path in selected_instances.items()},
        "algorithm": algorithm,
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "include_route_elimination_variant": bool(include_route_elimination_variant),
        "elapsed_seconds": time.perf_counter() - started,
        "outputs": ["task3_comparison_cost_breakdown.csv", "task3_summary.csv", "task3_wilcoxon_vs_fair_sa.csv", "task3_verdict.md"],
    }
    _write_json(out / "manifest.json", manifest)
    return {"gate": "TASK3_COMPLETE", "manifest": str(out / "manifest.json"), "elapsed_seconds": manifest["elapsed_seconds"]}


def run_all(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int],
    headroom_seeds: list[int],
    fair_eval_budget: int,
    fair_max_runtime_seconds: float,
    headroom_eval_budget: int,
    headroom_max_runtime_seconds: float,
    algorithm: str,
) -> dict[str, Any]:
    """Run all V2 tasks in order."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    _write_preflight(Path(repo_root), out)
    task1 = run_task1(repo_root, out / "task1", seeds=seeds, eval_budget=fair_eval_budget, max_runtime_seconds=fair_max_runtime_seconds)
    task2 = run_task2(repo_root, out / "task2", seeds=headroom_seeds, eval_budget=headroom_eval_budget, max_runtime_seconds=headroom_max_runtime_seconds, algorithm=algorithm, fair_reference_path=out / "task1/fair_sa_reference_costs.json")
    task3 = run_task3(repo_root, out / "task3", seeds=seeds, eval_budget=fair_eval_budget, max_runtime_seconds=fair_max_runtime_seconds, algorithm=algorithm, fair_reference_path=out / "task1/fair_sa_reference_costs.json")
    winner_manifest = write_winner_manifest(out)
    manifest = {
        "schema_version": "setp-alns-crush-v2.v1",
        "algorithm": algorithm,
        "seeds": seeds,
        "headroom_seeds": headroom_seeds,
        "fair_eval_budget": int(fair_eval_budget),
        "fair_max_runtime_seconds": float(fair_max_runtime_seconds),
        "headroom_eval_budget": int(headroom_eval_budget),
        "headroom_max_runtime_seconds": float(headroom_max_runtime_seconds),
        "elapsed_seconds": time.perf_counter() - started,
        "task1": task1,
        "task2": task2,
        "task3": task3,
        "winner_operator_manifest": str(winner_manifest),
    }
    _write_json(out / "manifest.json", manifest)
    return {"gate": "ALNS_CRUSH_V2_COMPLETE", "manifest": str(out / "manifest.json"), "elapsed_seconds": manifest["elapsed_seconds"]}


def _run_sa_task(task: tuple[str, str, int, int, float]) -> dict[str, Any]:
    bundle_dir, instance_name, seed, eval_budget, max_runtime_seconds = task
    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    warm = make_shared_initial_solution(bundle)
    run = run_candidate("scikit-opt-SA", bundle.bundle_dir, seed=seed, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds, initial_solution=warm)
    if run.best_solution is None:
        raise RuntimeError(f"SA returned no solution for {instance_name} seed {seed}")
    return {
        "instance": instance_name,
        "seed": int(seed),
        "evaluations": int(run.evals),
        "elapsed_seconds": time.perf_counter() - started,
        "solution": _solution_to_dict(run.best_solution),
    }


def _run_winner_task(task: tuple[str, str, int, int, float, str, bool, str]) -> dict[str, Any]:
    bundle_dir, instance_name, seed, eval_budget, max_runtime_seconds, algorithm, include_route_elimination, variant = task
    config = WinnerKernelConfig(algorithm=algorithm, seed=seed, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds, include_route_elimination=include_route_elimination)
    run = (
        run_winner_kernel_plus_route_elimination(bundle_dir, config=config)
        if include_route_elimination
        else run_winner_kernel(bundle_dir, config=config)
    )
    return {
        "instance": instance_name,
        "algorithm": algorithm,
        "variant": variant,
        "seed": int(seed),
        "evaluations": int(run["evaluations"]),
        "elapsed_seconds": float(run["elapsed_seconds"]),
        "solution": _solution_to_dict(run["best_solution"]),
    }


def _run_winner_rows(
    root: Path,
    *,
    seeds: list[int],
    eval_budget: int,
    max_runtime_seconds: float,
    algorithm: str,
    include_route_elimination: bool,
    variant: str,
    out: Path,
    instance_dirs: dict[str, Path] | None = None,
) -> list[dict[str, Any]]:
    selected_instances = instance_dirs or V2_INSTANCE_DIRS
    tasks = [
        (str(root / rel_dir), instance_name, int(seed), int(eval_budget), float(max_runtime_seconds), algorithm, bool(include_route_elimination), variant)
        for instance_name, rel_dir in selected_instances.items()
        for seed in seeds
    ]
    results = _run_parallel(tasks, _run_winner_task)
    rows: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda item: (item["instance"], item["seed"], item["variant"])):
        bundle = load_search_bundle(root / selected_instances[result["instance"]])
        solution = _solution_from_dict(result["solution"])
        row = cost_breakdown_row(result["instance"], result["variant"], int(result["seed"]), solution, bundle.instance, bundle.carbon_profile)
        row.update(
            {
                "algorithm": result["algorithm"],
                "variant": result["variant"],
                "evaluations": int(result["evaluations"]),
                "run_elapsed_seconds": float(result["elapsed_seconds"]),
                "operator_base_id": operator_base_id,
            }
        )
        rows.append(row)
        _write_json(out / "solutions" / f"{result['instance']}_{variant}_{algorithm}_seed{result['seed']}.json", result["solution"])
    return rows


def _run_parallel(tasks: list[tuple[Any, ...]], worker: Any) -> list[dict[str, Any]]:
    max_workers = max(1, min(len(tasks), int(os.environ.get("SETP_ALNS_PARALLEL_WORKERS", os.cpu_count() or 2))))
    if max_workers == 1:
        return [worker(task) for task in tasks]
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(worker, task) for task in tasks]
        for future in as_completed(futures):
            results.append(future.result())
    return results


def _summary_rows(rows: list[dict[str, Any]], *, variant: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        row_variant = str(row.get("variant") or variant)
        grouped.setdefault((row_variant, str(row["instance"]), str(row["algorithm"])), []).append(row)
    out: list[dict[str, Any]] = []
    for (row_variant, instance_name, algorithm), items in sorted(grouped.items()):
        costs = [float(row["total_cost"]) for row in items]
        routes = [float(row["route_count"]) for row in items]
        out.append(
            {
                "variant": row_variant,
                "instance": instance_name,
                "algorithm": algorithm,
                "n": len(items),
                "mean_total_cost": statistics.fmean(costs),
                "median_total_cost": statistics.median(costs),
                "best_total_cost": min(costs),
                "std_total_cost": statistics.stdev(costs) if len(costs) > 1 else 0.0,
                "mean_route_count": statistics.fmean(routes),
                "median_route_count": statistics.median(routes),
                "zero_violation_count": sum(1 for row in items if int(row["violation_count"]) == 0),
            }
        )
    return out


def _fair_sa_reference(
    summary: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    *,
    eval_budget: int = FAIR_SA_EVAL_BUDGET,
    max_runtime_seconds: float = FAIR_SA_MAX_RUNTIME_SECONDS,
) -> dict[str, Any]:
    instances: dict[str, Any] = {}
    for row in summary:
        if row["algorithm"] != "scikit-opt-SA":
            continue
        instance_rows = [item for item in rows if item["instance"] == row["instance"] and item["algorithm"] == "scikit-opt-SA"]
        baseline = dict(row)
        baseline["seed_total_costs"] = {
            str(int(item["seed"])): float(item["total_cost"])
            for item in sorted(instance_rows, key=lambda item: int(item["seed"]))
        }
        instances[str(row["instance"])] = {"scikit-opt-SA": baseline}
    return {
        "schema_version": "setp-alns-crush-v2-fair-sa-reference.v1",
        "baseline_algorithm": "scikit-opt-SA",
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "instances": instances,
        "row_count": len(rows),
    }


def _wilcoxon_vs_fair_sa(rows: list[dict[str, Any]], fair_reference: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["variant"]), str(row["instance"]), str(row["algorithm"])), []).append(row)
    out: list[dict[str, Any]] = []
    for (variant, instance_name, algorithm), items in sorted(grouped.items()):
        fair = fair_reference["instances"][instance_name]["scikit-opt-SA"]
        seed_costs = {str(seed): float(cost) for seed, cost in fair.get("seed_total_costs", {}).items()}
        paired_diffs = [
            float(row["total_cost"]) - seed_costs[str(int(row["seed"]))]
            for row in sorted(items, key=lambda row: int(row["seed"]))
            if str(int(row["seed"])) in seed_costs
        ]
        missing = len(items) - len(paired_diffs)
        p_value, method = _wilcoxon_less(paired_diffs)
        out.append(
            {
                "variant": variant,
                "instance": instance_name,
                "algorithm": algorithm,
                "baseline": "fair_scikit-opt-SA_paired_seed",
                "n_pairs": len(paired_diffs),
                "missing_fair_sa_seed_pairs": missing,
                "mean_diff_alg_minus_fair_sa": statistics.fmean(paired_diffs) if paired_diffs else math.nan,
                "median_diff_alg_minus_fair_sa": statistics.median(paired_diffs) if paired_diffs else math.nan,
                "wins_alg_lower": sum(1 for value in paired_diffs if value < -1e-9),
                "p_value_less": p_value,
                "method": method,
            }
        )
    return out


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


def _task3_verdicts(summary: list[dict[str, Any]], wilcoxon: list[dict[str, Any]], fair_reference: dict[str, Any]) -> list[dict[str, Any]]:
    p_lookup = {(row["variant"], row["instance"], row["algorithm"]): row for row in wilcoxon}
    out: list[dict[str, Any]] = []
    for row in summary:
        fair = fair_reference["instances"][row["instance"]]["scikit-opt-SA"]
        p_row = p_lookup[(row["variant"], row["instance"], row["algorithm"])]
        mean_delta = float(row["mean_total_cost"]) - float(fair["mean_total_cost"])
        std_ok = float(row["std_total_cost"]) <= 1.25 * float(fair["std_total_cost"])
        wins = int(p_row["wins_alg_lower"])
        p_value = float(p_row["p_value_less"])
        if mean_delta < 0 and p_value < 0.05 and wins >= 8 and std_ok:
            verdict = "碾压"
        elif mean_delta < 0 and (p_value >= 0.05 or 6 <= wins <= 7):
            verdict = "小幅领先"
        elif abs(mean_delta) <= max(1e-9, 0.0025 * float(fair["mean_total_cost"])):
            verdict = "持平"
        else:
            verdict = "失败"
        out.append({**row, "fair_sa_mean": fair["mean_total_cost"], "mean_delta_vs_fair_sa": mean_delta, "wins_alg_lower": wins, "p_value_less": p_value, "std_ok": std_ok, "verdict": verdict})
    return out


def _lower_bound_row(instance_name: str, bundle: Any) -> dict[str, Any]:
    customers = [node for node in bundle.instance.nodes if node.node_type.lower() == "c"]
    depots = [node for node in bundle.instance.nodes if node.node_type.lower() == "d"]
    total_demand = sum(max(0.0, float(node.demand)) for node in customers)
    capacity = _price(DEFAULT_PRICES, "Q_capacity")
    vehicle_fixed_cost = _price(DEFAULT_PRICES, "vehicle_fixed_cost")
    c_km = _price(DEFAULT_PRICES, "c_km")
    min_vehicle_count = int(math.ceil(total_demand / max(1e-9, capacity)))
    weak_distance_m = 0.5 * sum(min(float(bundle.instance.distance(depot.node_id, customer.node_id)) * 2.0 for depot in depots) for customer in customers)
    return {
        "instance": instance_name,
        "total_positive_demand": total_demand,
        "capacity": capacity,
        "min_vehicle_count_capacity_only": min_vehicle_count,
        "fixed_cost_lower_bound": min_vehicle_count * vehicle_fixed_cost,
        "weak_distance_m_lower_bound": weak_distance_m,
        "weak_distance_cost_lower_bound": (weak_distance_m / 1000.0) * c_km,
        "weak_total_lower_bound": min_vehicle_count * vehicle_fixed_cost + (weak_distance_m / 1000.0) * c_km,
        "bound_note": "Weak capacity+distance relaxation only; not a proof of optimality.",
    }


def _sa_diff_report(diff: dict[str, Any], summary: list[dict[str, Any]]) -> str:
    lines = [
        "# Task1 SA Fairness Audit",
        "",
        f"- Phase0 eval budget/runtime: {diff['phase0_eval_budget']} / {diff['phase0_max_runtime_seconds']}s",
        f"- Prompt1 Phase2 eval budget/runtime: {diff['phase2_eval_budget']} / {diff['phase2_max_runtime_seconds']}s",
        f"- Phase2 SA weaker by config: {diff['phase2_sa_weaker_by_config']}",
    ]
    if "audit_note" in diff:
        lines.append(f"- Audit note: {diff['audit_note']}")
    if "fair_sa_100_seed1_reproduced_cost" in diff:
        lines.extend(
            [
                f"- 100-01 seed1 reproduction cost: {diff['fair_sa_100_seed1_reproduced_cost']:.12f}",
                f"- Phase0 target: {diff['phase0_sa_100_seed1_target']:.12f}",
                f"- Absolute delta: {diff['reproduction_abs_delta']:.12f}",
            ]
        )
    lines.extend(["", "Fair SA means:"])
    for row in summary:
        lines.append(f"- {row['instance']}: mean={row['mean_total_cost']:.6f}, best={row['best_total_cost']:.6f}, std={row['std_total_cost']:.6f}, routes={row['mean_route_count']:.3f}")
    lines.append("")
    lines.append("V2 crush claims must be computed against this fair SA baseline, not Prompt1 Phase2 SA.")
    return "\n".join(lines)


def _headroom_report(rows: list[dict[str, Any]], lower_bounds: list[dict[str, Any]], fair_reference: dict[str, Any]) -> str:
    lines = ["# Task2 True Headroom", "", "Winner-kernel long-budget runs are compared to Task1 fair SA means.", ""]
    best_by_instance: dict[str, float] = {}
    for row in rows:
        best_by_instance[row["instance"]] = min(best_by_instance.get(row["instance"], math.inf), float(row["total_cost"]))
    for instance_name, best_cost in sorted(best_by_instance.items()):
        fair = float(fair_reference["instances"][instance_name]["scikit-opt-SA"]["mean_total_cost"])
        gap = (best_cost - fair) / fair * 100.0
        lb = next(row for row in lower_bounds if row["instance"] == instance_name)
        lb_gap = (best_cost - float(lb["weak_total_lower_bound"])) / max(1e-9, float(lb["weak_total_lower_bound"])) * 100.0
        verdict = "headroom supports crush" if gap <= -1.0 else "headroom thin or not proven"
        lines.append(f"- {instance_name}: true-best={best_cost:.6f}, fair-SA-mean={fair:.6f}, gap={gap:.3f}%, weak-LB={float(lb['weak_total_lower_bound']):.6f}, gap-to-weak-LB={lb_gap:.3f}%, verdict={verdict}.")
    return "\n".join(lines)


def _task3_verdict_report(verdicts: list[dict[str, Any]], summary: list[dict[str, Any]], wilcoxon: list[dict[str, Any]]) -> str:
    lines = [
        "# Task3 Lean ALNS Verdict",
        "",
        "Methodological note: V2 keeps the kernel threshold-style acceptance when selected; the ALNS-vs-SA distinction is the large destroy-repair neighborhood, not the acceptance criterion.",
        "",
    ]
    for row in verdicts:
        lines.append(
            f"- {row['instance']} {row['variant']} {row['algorithm']}: {row['verdict']}; "
            f"mean={float(row['mean_total_cost']):.6f}, fair-SA={float(row['fair_sa_mean']):.6f}, "
            f"delta={float(row['mean_delta_vs_fair_sa']):.6f}, wins={row['wins_alg_lower']}/10, p={float(row['p_value_less']):.6g}."
        )
    return "\n".join(lines)


def _write_preflight(repo_root: Path, out: Path) -> None:
    preflight = out / "preflight"
    preflight.mkdir(parents=True, exist_ok=True)
    for name, cmd in {
        "git_status": ["git", "status", "--short"],
        "protected_diff": ["git", "diff", "--name-only", "--", "solver/src/setp_solver/cost.py", "solver/src/setp_solver/check.py", "solver/src/setp_solver/search/evaluation.py", "solver/src/setp_solver/search/candidates.py", "solver/src/setp_solver/search/alns_wouda.py"],
    }.items():
        proc = subprocess.run(cmd, cwd=repo_root, text=True, capture_output=True, check=False)
        (preflight / f"{name}.stdout.txt").write_text(proc.stdout, encoding="utf-8")
        (preflight / f"{name}.stderr.txt").write_text(proc.stderr, encoding="utf-8")


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


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


def _solution_to_dict(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [asdict(item) for item in solution.cross_site_services],
    }


def _solution_from_dict(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[Route(str(row["vehicle_id"]), str(row["vehicle_type"]), str(row["home_depot_id"]), [str(node) for node in row["node_sequence"]]) for row in payload.get("routes", [])],
        charging_actions=[ChargingAction(str(row["vehicle_id"]), str(row["station_id"]), float(row["energy_kwh"]), float(row["occupancy_minutes"]), float(row["charge_start_second"]), int(row.get("charge_day_offset", 0))) for row in payload.get("charging_actions", [])],
        cross_site_services=[CrossSiteService(str(row["customer_id"]), str(row["served_by_depot_id"])) for row in payload.get("cross_site_services", [])],
    )


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ALNS Crush V2 fairness audit.")
    parser.add_argument("stage", choices=["all", "task1", "task2", "task3", "manifest"])
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[4]))
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parents[4] / CRUSH_V2_DIR))
    parser.add_argument("--seeds", default="1-10")
    parser.add_argument("--headroom-seeds", default="1-3")
    parser.add_argument("--fair-eval-budget", type=int, default=FAIR_SA_EVAL_BUDGET)
    parser.add_argument("--fair-max-runtime-seconds", type=float, default=FAIR_SA_MAX_RUNTIME_SECONDS)
    parser.add_argument("--headroom-eval-budget", type=int, default=80_000)
    parser.add_argument("--headroom-max-runtime-seconds", type=float, default=3600.0)
    parser.add_argument("--algorithm", default="ALNS-Wouda")
    args = parser.parse_args(argv)
    if args.stage == "manifest":
        path = write_winner_manifest(args.output_dir)
        print(f"GATE ALNS_CRUSH_V2_MANIFEST {json.dumps({'manifest': str(path)}, ensure_ascii=False)}")
        return 0
    _write_preflight(Path(args.repo_root), Path(args.output_dir))
    if args.stage == "task1":
        result = run_task1(args.repo_root, Path(args.output_dir) / "task1", seeds=_parse_seed_list(args.seeds), eval_budget=args.fair_eval_budget, max_runtime_seconds=args.fair_max_runtime_seconds)
    elif args.stage == "task2":
        result = run_task2(args.repo_root, Path(args.output_dir) / "task2", seeds=_parse_seed_list(args.headroom_seeds), eval_budget=args.headroom_eval_budget, max_runtime_seconds=args.headroom_max_runtime_seconds, algorithm=args.algorithm)
    elif args.stage == "task3":
        result = run_task3(args.repo_root, Path(args.output_dir) / "task3", seeds=_parse_seed_list(args.seeds), eval_budget=args.fair_eval_budget, max_runtime_seconds=args.fair_max_runtime_seconds, algorithm=args.algorithm)
    else:
        result = run_all(
            args.repo_root,
            args.output_dir,
            seeds=_parse_seed_list(args.seeds),
            headroom_seeds=_parse_seed_list(args.headroom_seeds),
            fair_eval_budget=args.fair_eval_budget,
            fair_max_runtime_seconds=args.fair_max_runtime_seconds,
            headroom_eval_budget=args.headroom_eval_budget,
            headroom_max_runtime_seconds=args.headroom_max_runtime_seconds,
            algorithm=args.algorithm,
        )
    print(f"GATE ALNS_CRUSH_V2 {result['gate']} {json.dumps(result, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
