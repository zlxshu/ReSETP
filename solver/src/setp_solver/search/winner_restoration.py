"""Winner-kernel restoration diagnostics.

This runner is isolated from formal experiment runners. It writes only under
``solver/reports/dr_alns_ppo_v2/restoration`` and never changes model cost or
constraint semantics.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict
import inspect
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import time
from typing import Any

from ..check import check_solution
from ..prices import DEFAULT_PRICES
from ..solution import ChargingAction, CrossSiteService, Route, Solution
from . import alns_wouda, candidates
from .alns_crush import COMPONENT_FIELDS, INSTANCE_DIRS, cost_breakdown_row
from .alns_crush_v2 import _parse_seed_list
from .bundle import load_search_bundle
from .winner_operators import (
    WinnerKernelConfig,
    WinnerOperatorSet,
    operator_base_id,
    run_winner_kernel,
    winner_operator_module,
)


RESTORATION_DIR = Path("solver/reports/dr_alns_ppo_v2/restoration")
TARGET_INSTANCE = "L-main-threeshift-200c"
WINNER_VARIANT = "winner_kernel_only"
WINNER_ALGORITHM = "ALNS-Wouda"
GOLD_VERIFY_JSON = Path("solver/reports/alns_crush_v3/taskB_Lmain_best_verify.json")
GOLD_SOLUTIONS_DIR = Path("solver/reports/alns_crush_v2/task3/solutions")
FAIR_SA_MEAN_LMAIN = 8319.837848563908
OLD_GOLD_MEAN = 8351.639754631946
OLD_GOLD_BEST = 8138.269146670922
EPS = 1e-9


def verify_gold(repo_root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Recompute the persisted V3/taskB gold winner solutions."""

    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    bundle = load_search_bundle(root / INSTANCE_DIRS[TARGET_INSTANCE])
    rows: list[dict[str, Any]] = []
    for gold_row in sorted(_gold_rows(root).values(), key=lambda row: int(row["seed"])):
        seed = int(gold_row["seed"])
        solution_path = _gold_solution_path(root, seed, gold_row)
        solution = _solution_from_dict(_load_json(solution_path))
        row = cost_breakdown_row(TARGET_INSTANCE, WINNER_VARIANT, seed, solution, bundle.instance, bundle.carbon_profile)
        expected = float(gold_row["expected_total_cost"])
        recomputed = float(row["total_cost"])
        row.update(
            {
                "solution_path": str(solution_path),
                "expected_total_cost": expected,
                "recomputed_total_cost": recomputed,
                "abs_delta": abs(recomputed - expected),
                "gold_route_count": int(gold_row["route_count"]),
                "gold_cv_routes": int(gold_row["cv_routes"]),
                "gold_ev_routes": int(gold_row["ev_routes"]),
                "gold_charging_actions": int(gold_row["charging_actions"]),
            }
        )
        rows.append(row)
    mean = statistics.fmean(float(row["recomputed_total_cost"]) for row in rows)
    best = min(rows, key=lambda row: float(row["recomputed_total_cost"]))
    max_abs_delta = max(float(row["abs_delta"]) for row in rows)
    zero_violations = sum(1 for row in rows if int(row["violation_count"]) == 0)
    gate = (
        len(rows) == 10
        and max_abs_delta <= EPS
        and abs(mean - OLD_GOLD_MEAN) <= EPS
        and abs(float(best["recomputed_total_cost"]) - OLD_GOLD_BEST) <= EPS
        and zero_violations == 10
    )
    result = {
        "gate": "PASS_GOLD_RECOMPUTE" if gate else "HALT_GOLD_RECOMPUTE_MISMATCH",
        "instance": TARGET_INSTANCE,
        "operator_base_id": operator_base_id,
        "seed_count": len(rows),
        "mean_recomputed_total_cost": mean,
        "expected_old_gold_mean": OLD_GOLD_MEAN,
        "best_seed": int(best["seed"]),
        "best_recomputed_total_cost": float(best["recomputed_total_cost"]),
        "expected_old_gold_best": OLD_GOLD_BEST,
        "max_abs_delta": max_abs_delta,
        "zero_violation_count": zero_violations,
        "elapsed_seconds": time.perf_counter() - started,
        "rows": rows,
    }
    _write_csv(out / "phase1_gold_recompute.csv", rows)
    _write_json(out / "phase1_gold_recompute.json", result)
    (out / "phase1_gold_recompute.md").write_text(_gold_report(result), encoding="utf-8")
    append_log(
        out,
        phase="Phase 1",
        command="python -m setp_solver.search.winner_restoration verify-gold",
        stdout=f"gate={result['gate']} mean={mean:.12f} best={float(best['recomputed_total_cost']):.12f} max_abs_delta={max_abs_delta:.3g}",
        stderr="",
        conclusion="Scoring semantics match gold solutions." if gate else "Gold recompute mismatch; search restoration must stop.",
    )
    return result


def run_current(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int],
    eval_budget: int,
    max_runtime_seconds: float,
) -> dict[str, Any]:
    """Run current winner kernel and compare every seed to the gold cohort."""

    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    tasks = [
        (str(root / INSTANCE_DIRS[TARGET_INSTANCE]), int(seed), int(eval_budget), float(max_runtime_seconds))
        for seed in seeds
    ]
    results = _run_parallel(tasks, _run_winner_task)
    bundle = load_search_bundle(root / INSTANCE_DIRS[TARGET_INSTANCE])
    current_rows: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda item: int(item["seed"])):
        solution = _solution_from_dict(result["solution"])
        row = cost_breakdown_row(TARGET_INSTANCE, WINNER_VARIANT, int(result["seed"]), solution, bundle.instance, bundle.carbon_profile)
        row.update(
            {
                "evaluations": int(result["evaluations"]),
                "run_elapsed_seconds": float(result["elapsed_seconds"]),
                "operator_base_id": operator_base_id,
                "solution_path": str(out / "solutions" / f"{TARGET_INSTANCE}_{WINNER_VARIANT}_{WINNER_ALGORITHM}_seed{result['seed']}.json"),
            }
        )
        current_rows.append(row)
        _write_json(row["solution_path"], result["solution"])
    gold_rows = _gold_rows(root)
    diff_rows = compare_to_gold(current_rows, gold_rows)
    summary = _summary(diff_rows)
    static_audit = static_recipe_audit()
    classification = classify_regression(diff_rows, static_audit)
    result = {
        "gate": "PASS_CURRENT_RUN_CLASSIFIED",
        "instance": TARGET_INSTANCE,
        "seeds": [int(seed) for seed in seeds],
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "operator_base_id": operator_base_id,
        "winner_operator_module": winner_operator_module,
        "elapsed_seconds": time.perf_counter() - started,
        "summary": summary,
        "classification": classification,
        "static_recipe_audit": static_audit,
    }
    _write_csv(out / "phase2_current_winner_cost_breakdown.csv", current_rows)
    _write_csv(out / "phase2_current_vs_gold.csv", diff_rows)
    _write_json(out / "phase2_current_vs_gold.json", {**result, "rows": diff_rows})
    _write_json(out / "phase2_static_recipe_audit.json", static_audit)
    (out / "phase2_regression_report.md").write_text(_phase2_report(result, diff_rows), encoding="utf-8")
    append_log(
        out,
        phase="Phase 2",
        command=(
            "PYTHONHASHSEED=0 SETP_ALNS_PARALLEL_WORKERS=6 "
            "python -m setp_solver.search.winner_restoration run-current "
            f"--seeds {_format_seed_list(seeds)} --eval-budget {eval_budget} --max-runtime-seconds {max_runtime_seconds}"
        ),
        stdout=(
            f"mean_current={summary['mean_current_total_cost']:.6f} "
            f"mean_gold={summary['mean_gold_total_cost']:.6f} "
            f"mean_delta={summary['mean_total_delta']:.6f} "
            f"classification={classification['classification']}"
        ),
        stderr="",
        conclusion=classification["conclusion"],
    )
    return result


def classify_regression(rows: list[dict[str, Any]], static_audit: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify the dominant regression dimension."""

    if not rows:
        raise ValueError("rows must not be empty")
    mean_total_delta = statistics.fmean(float(row["total_delta"]) for row in rows)
    mean_route_delta = statistics.fmean(float(row["route_count_delta"]) for row in rows)
    route_high_count = sum(1 for row in rows if float(row["route_count_delta"]) > 0)
    mean_cost_fix_delta = statistics.fmean(float(row["cost_fix_delta"]) for row in rows)
    mean_cost_km_delta = statistics.fmean(float(row["cost_km_delta"]) for row in rows)
    fix_share = _positive_share(mean_cost_fix_delta, mean_total_delta)
    km_share = _positive_share(mean_cost_km_delta, mean_total_delta)
    vehicle_changed_count = sum(
        1
        for row in rows
        if abs(float(row["cv_routes_delta"])) >= 2 or abs(float(row["ev_routes_delta"])) >= 2
    )
    charging_changed_count = sum(1 for row in rows if abs(float(row["charging_actions_delta"])) >= 3)
    if mean_total_delta <= 0:
        classification = "not_regressed"
        conclusion = "Current winner is not worse than gold on mean; restoration should not change search logic without more evidence."
    elif ((mean_route_delta >= 1.5 or route_high_count >= 7) and fix_share >= 0.5):
        classification = "route_count_cost_fix_dominant"
        conclusion = "Regression is dominated by route count / fixed cost; inspect route-removal and reinsertion compression."
    elif abs(mean_route_delta) < 1.0 and km_share >= 0.5:
        classification = "cost_km_dominant"
        conclusion = "Regression is dominated by route sequencing distance; inspect repair ordering/local improvement."
    elif vehicle_changed_count >= 7:
        classification = "vehicle_mix_dominant"
        conclusion = "Regression is dominated by CV/EV mix changes; inspect vehicle_type_swap and route type decisions."
    elif charging_changed_count >= 7:
        classification = "charging_actions_dominant"
        conclusion = "Regression is dominated by charging-action changes; inspect EV charging repair behavior."
    else:
        classification = "mixed_or_unclear"
        conclusion = "No single regression dimension meets the gate; stop before code changes."
    mismatches = list((static_audit or {}).get("mismatches", []))
    if classification != "mixed_or_unclear" and len(mismatches) > 2:
        conclusion = "Static recipe has more than two mismatches; stop before code changes."
    return {
        "classification": classification,
        "mean_total_delta": mean_total_delta,
        "mean_route_count_delta": mean_route_delta,
        "route_high_count": route_high_count,
        "mean_cost_fix_delta": mean_cost_fix_delta,
        "mean_cost_km_delta": mean_cost_km_delta,
        "cost_fix_explained_share": fix_share,
        "cost_km_explained_share": km_share,
        "vehicle_changed_count": vehicle_changed_count,
        "charging_changed_count": charging_changed_count,
        "static_mismatch_count": len(mismatches),
        "static_mismatches": mismatches,
        "conclusion": conclusion,
    }


def static_recipe_audit() -> dict[str, Any]:
    """Check current winner-kernel wiring against the stated recipe."""

    mismatches: list[str] = []
    ops = WinnerOperatorSet.create(include_route_elimination=False)
    destroy_names = [name for name, _ in ops.destroy_ops]
    repair_names = [name for name, _ in ops.repair_ops]
    expected_destroy = [
        "random_customer_removal",
        "worst_customer_removal",
        "shaw_related_removal",
        "whole_route_removal",
        "route_segment_removal",
        "vehicle_type_swap",
    ]
    expected_repair = ["greedy_insert_repair", "regret2_insert_repair", "regret3_insert_repair"]
    if destroy_names != expected_destroy:
        mismatches.append(f"destroy_ops={destroy_names} expected={expected_destroy}")
    if repair_names != expected_repair:
        mismatches.append(f"repair_ops={repair_names} expected={expected_repair}")
    selector_source = inspect.getsource(alns_wouda._make_operator_selector)
    acceptance_source = inspect.getsource(alns_wouda._make_acceptance_criterion)
    insertion_source = inspect.getsource(candidates._path_insertion_options)
    config = WinnerKernelConfig()
    if "AlphaUCB" not in selector_source or "[20.0, 8.0, 2.0, 0.05]" not in selector_source or "alpha=0.08" not in selector_source:
        mismatches.append("operator selector is not AlphaUCB([20,8,2,0.05], alpha=0.08)")
    if "HillClimbing" not in acceptance_source:
        mismatches.append("default acceptance source does not contain HillClimbing")
    if bool(config.require_charging_signal):
        mismatches.append("WinnerKernelConfig.require_charging_signal default is not False")
    if "for route_idx, route in enumerate(routes)" not in insertion_source or "for insert_at in range(len(customers) + 1)" not in insertion_source:
        mismatches.append("candidate regret insertion does not enumerate every route x position")
    if "Route(vehicle_id, \"cv\"" not in insertion_source and "Route(vehicle_id, 'cv'" not in insertion_source:
        mismatches.append("candidate insertion does not expose new CV route fallback")
    return {
        "gate": "PASS_STATIC_RECIPE_AUDIT" if not mismatches else "WARN_STATIC_RECIPE_MISMATCH",
        "operator_base_id": operator_base_id,
        "winner_operator_module": winner_operator_module,
        "destroy_ops": destroy_names,
        "repair_ops": repair_names,
        "alpha_ucb_expected": "AlphaUCB([20,8,2,0.05], alpha=0.08)",
        "acceptance_expected": "HillClimbing when SETP_ALNS_CRUSH_TRUE_ACCEPTANCE=0",
        "require_charging_signal_default": bool(config.require_charging_signal),
        "path_insertion_all_route_position": "for route_idx, route in enumerate(routes)" in insertion_source
        and "for insert_at in range(len(customers) + 1)" in insertion_source,
        "new_cv_route_fallback": "Route(vehicle_id, \"cv\"" in insertion_source or "Route(vehicle_id, 'cv'" in insertion_source,
        "mismatches": mismatches,
    }


def verify_restored(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int],
    eval_budget: int,
    max_runtime_seconds: float,
) -> dict[str, Any]:
    """Run restored verification and write the replacement reproducible anchor."""

    result = run_current(
        repo_root,
        output_dir,
        seeds=seeds,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
    )
    summary = result["summary"]
    crush_restored = (
        float(summary["mean_current_total_cost"]) < FAIR_SA_MEAN_LMAIN
        and int(summary["zero_violation_count"]) == len(seeds)
    )
    commit_hash = _git(["rev-parse", "HEAD"], Path(repo_root)).strip()
    restored = {
        "gate": "PASS_RESTORED_BASELINE" if crush_restored else "HALT_RESTORED_BASELINE_NOT_CRUSHING",
        "commit_hash": commit_hash,
        "operator_base_id": operator_base_id,
        "fair_sa_mean_reference": FAIR_SA_MEAN_LMAIN,
        "old_gold_mean_reference": OLD_GOLD_MEAN,
        "old_gold_best_reference": OLD_GOLD_BEST,
        "summary": summary,
        "classification": result["classification"],
    }
    _write_json(Path(output_dir) / "restored_baseline.json", restored)
    (Path(output_dir) / "restored_baseline.md").write_text(_restored_report(restored), encoding="utf-8")
    append_log(
        output_dir,
        phase="Phase 4/5",
        command="python -m setp_solver.search.winner_restoration verify-restored",
        stdout=f"gate={restored['gate']} mean={summary['mean_current_total_cost']:.6f}",
        stderr="",
        conclusion="Restored winner baseline established." if crush_restored else "Restored verification did not beat fair SA.",
    )
    return restored


def compare_to_gold(current_rows: list[dict[str, Any]], gold_rows: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    diff_rows: list[dict[str, Any]] = []
    for row in current_rows:
        seed = int(row["seed"])
        gold = gold_rows[seed]
        diff = dict(row)
        diff.update(
            {
                "gold_total_cost": float(gold["recomputed_total_cost"]),
                "total_delta": float(row["total_cost"]) - float(gold["recomputed_total_cost"]),
                "gold_route_count": int(gold["route_count"]),
                "route_count_delta": int(row["route_count"]) - int(gold["route_count"]),
                "gold_cv_routes": int(gold["cv_routes"]),
                "cv_routes_delta": int(row["cv_routes"]) - int(gold["cv_routes"]),
                "gold_ev_routes": int(gold["ev_routes"]),
                "ev_routes_delta": int(row["ev_routes"]) - int(gold["ev_routes"]),
                "gold_charging_actions": int(gold["charging_actions"]),
                "charging_actions_delta": int(row["charging_actions"]) - int(gold["charging_actions"]),
            }
        )
        for field in COMPONENT_FIELDS:
            diff[f"gold_{field}"] = float(gold[field])
            diff[f"{field}_delta"] = float(row[field]) - float(gold[field])
        diff_rows.append(diff)
    return diff_rows


def append_log(
    output_dir: str | Path,
    *,
    phase: str,
    command: str,
    stdout: str,
    stderr: str,
    conclusion: str,
) -> None:
    path = Path(output_dir) / "diagnosis_log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    commit_hash = "unknown"
    try:
        commit_hash = _git(["rev-parse", "HEAD"], _repo_root()).strip()
    except Exception:
        pass
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Winner Kernel Restoration Diagnosis Log\n"
    entry = (
        f"\n## {phase} - {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"- Commit: `{commit_hash}`\n"
        f"- Command: `{command}`\n"
        f"- Stdout: `{stdout}`\n"
        f"- Stderr: `{stderr}`\n"
        f"- Conclusion: {conclusion}\n"
    )
    path.write_text(existing.rstrip() + "\n" + entry, encoding="utf-8")


def _run_winner_task(task: tuple[str, int, int, float]) -> dict[str, Any]:
    bundle_dir, seed, eval_budget, max_runtime_seconds = task
    started = time.perf_counter()
    result = run_winner_kernel(
        bundle_dir,
        config=WinnerKernelConfig(
            seed=int(seed),
            eval_budget=int(eval_budget),
            max_runtime_seconds=float(max_runtime_seconds),
        ),
    )
    return {
        "seed": int(seed),
        "evaluations": int(result["evaluations"]),
        "elapsed_seconds": time.perf_counter() - started,
        "solution": _solution_to_dict(result["best_solution"]),
    }


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


def _gold_rows(repo_root: Path) -> dict[int, dict[str, Any]]:
    verified_path = repo_root / RESTORATION_DIR / "phase1_gold_recompute.json"
    if verified_path.exists():
        payload = _load_json(verified_path)
        return {int(row["seed"]): row for row in payload["rows"]}
    gold_path = repo_root / GOLD_VERIFY_JSON
    if gold_path.exists():
        return _gold_rows_from_verify(repo_root, _load_json(gold_path))
    return _gold_rows_from_solutions(repo_root)


def _gold_rows_from_verify(repo_root: Path, payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for gold_row in payload.get("audit_rows", payload.get("rows", [])):
        seed = int(gold_row.get("seed", 0))
        if not seed:
            continue
        expected = float(gold_row.get("expected_total_cost", gold_row.get("recomputed_total_cost", 0.0)))
        recomputed = float(gold_row.get("recomputed_total_cost", expected))
        row = {
            "seed": seed,
            "expected_total_cost": expected,
            "recomputed_total_cost": recomputed,
            "route_count": int(gold_row.get("route_count", gold_row.get("gold_route_count", 0))),
            "cv_routes": int(gold_row.get("cv_routes", gold_row.get("gold_cv_routes", 0))),
            "ev_routes": int(gold_row.get("ev_routes", gold_row.get("gold_ev_routes", 0))),
            "charging_actions": int(gold_row.get("charging_actions", gold_row.get("gold_charging_actions", 0))),
            "solution_path": str(gold_row.get("solution_path", _gold_solution_path(repo_root, seed, {}).resolve())),
            "abs_delta": float(gold_row.get("abs_delta", abs(recomputed - expected))),
            "violation_count": int(gold_row.get("violation_count", 0)),
        }
        rows.append(row)
    return {int(row["seed"]): row for row in rows}


def _gold_rows_from_solutions(repo_root: Path) -> dict[int, dict[str, Any]]:
    bundle = load_search_bundle(repo_root / INSTANCE_DIRS[TARGET_INSTANCE])
    rows = {}
    for seed in range(1, 11):
        solution_path = _gold_solution_path(repo_root, seed, {"seed": seed})
        if not solution_path.exists():
            continue
        solution = _solution_from_dict(_load_json(solution_path))
        breakdown = cost_breakdown_row(TARGET_INSTANCE, WINNER_VARIANT, seed, solution, bundle.instance, bundle.carbon_profile)
        total_cost = float(breakdown["total_cost"])
        rows[seed] = {
            **breakdown,
            "seed": seed,
            "expected_total_cost": total_cost,
            "recomputed_total_cost": total_cost,
            "abs_delta": 0.0,
            "gold_total_cost": total_cost,
            "route_count": int(breakdown["route_count"]),
            "cv_routes": int(breakdown["cv_routes"]),
            "ev_routes": int(breakdown["ev_routes"]),
            "charging_actions": int(breakdown["charging_actions"]),
            "gold_route_count": int(breakdown["route_count"]),
            "gold_cv_routes": int(breakdown["cv_routes"]),
            "gold_ev_routes": int(breakdown["ev_routes"]),
            "gold_charging_actions": int(breakdown["charging_actions"]),
            "violation_count": 0,
        }
    return rows


def _gold_solution_path(repo_root: Path, seed: int, gold_row: dict[str, Any]) -> Path:
    path = Path(str(gold_row.get("solution_path", "")))
    if path.exists():
        return path
    return repo_root / GOLD_SOLUTIONS_DIR / f"{TARGET_INSTANCE}_{WINNER_VARIANT}_{WINNER_ALGORITHM}_seed{seed}.json"


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    current_costs = [float(row["total_cost"]) for row in rows]
    gold_costs = [float(row["gold_total_cost"]) for row in rows]
    total_deltas = [float(row["total_delta"]) for row in rows]
    route_deltas = [float(row["route_count_delta"]) for row in rows]
    return {
        "seed_count": len(rows),
        "mean_current_total_cost": statistics.fmean(current_costs),
        "median_current_total_cost": statistics.median(current_costs),
        "best_current_total_cost": min(current_costs),
        "std_current_total_cost": statistics.stdev(current_costs) if len(current_costs) > 1 else 0.0,
        "mean_gold_total_cost": statistics.fmean(gold_costs),
        "mean_total_delta": statistics.fmean(total_deltas),
        "median_total_delta": statistics.median(total_deltas),
        "mean_route_count": statistics.fmean(float(row["route_count"]) for row in rows),
        "mean_gold_route_count": statistics.fmean(float(row["gold_route_count"]) for row in rows),
        "mean_route_count_delta": statistics.fmean(route_deltas),
        "zero_violation_count": sum(1 for row in rows if int(row["violation_count"]) == 0),
    }


def _positive_share(component_delta: float, total_delta: float) -> float:
    if total_delta <= EPS or component_delta <= 0:
        return 0.0
    return float(component_delta) / max(EPS, float(total_delta))


def _gold_report(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Phase 1 Gold Recompute",
            "",
            f"- gate: `{result['gate']}`",
            f"- seed_count: {result['seed_count']}",
            f"- mean_recomputed_total_cost: £{result['mean_recomputed_total_cost']:.12f}",
            f"- best_seed: {result['best_seed']}",
            f"- best_recomputed_total_cost: £{result['best_recomputed_total_cost']:.12f}",
            f"- max_abs_delta: {result['max_abs_delta']:.12g}",
            f"- zero_violation_count: {result['zero_violation_count']}",
        ]
    )


def _phase2_report(result: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    summary = result["summary"]
    classification = result["classification"]
    lines = [
        "# Phase 2 Current Winner vs Gold",
        "",
        f"- mean_current_total_cost: £{summary['mean_current_total_cost']:.6f}",
        f"- mean_gold_total_cost: £{summary['mean_gold_total_cost']:.6f}",
        f"- mean_total_delta: £{summary['mean_total_delta']:.6f}",
        f"- mean_route_count_delta: {summary['mean_route_count_delta']:.3f}",
        f"- classification: `{classification['classification']}`",
        f"- conclusion: {classification['conclusion']}",
        "",
        "## Static Recipe Audit",
        "",
        f"- gate: `{result['static_recipe_audit']['gate']}`",
        f"- mismatches: {json.dumps(result['static_recipe_audit']['mismatches'], ensure_ascii=False)}",
        "",
        "## Seeds",
    ]
    for row in rows:
        lines.append(
            f"- seed {int(row['seed'])}: current=£{float(row['total_cost']):.6f}, "
            f"gold=£{float(row['gold_total_cost']):.6f}, delta=£{float(row['total_delta']):.6f}, "
            f"routes={row['route_count']} vs {row['gold_route_count']}, "
            f"cv/ev={row['cv_routes']}/{row['ev_routes']} vs {row['gold_cv_routes']}/{row['gold_ev_routes']}, "
            f"charges={row['charging_actions']} vs {row['gold_charging_actions']}."
        )
    return "\n".join(lines)


def _restored_report(result: dict[str, Any]) -> str:
    summary = result["summary"]
    return "\n".join(
        [
            "# Restored Winner Baseline",
            "",
            f"- gate: `{result['gate']}`",
            f"- commit_hash: `{result['commit_hash']}`",
            f"- mean_current_total_cost: £{summary['mean_current_total_cost']:.6f}",
            f"- best_current_total_cost: £{summary['best_current_total_cost']:.6f}",
            f"- fair_sa_mean_reference: £{result['fair_sa_mean_reference']:.6f}",
            f"- old_gold_mean_reference: £{result['old_gold_mean_reference']:.6f}",
            f"- old_gold_best_reference: £{result['old_gold_best_reference']:.6f}",
            f"- zero_violation_count: {summary['zero_violation_count']}",
        ]
    )


def _solution_to_dict(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [asdict(item) for item in solution.cross_site_services],
    }


def _solution_from_dict(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(str(row["vehicle_id"]), str(row["vehicle_type"]), str(row["home_depot_id"]), [str(node) for node in row["node_sequence"]])
            for row in payload.get("routes", [])
        ],
        charging_actions=[
            ChargingAction(str(row["vehicle_id"]), str(row["station_id"]), float(row["energy_kwh"]), float(row["occupancy_minutes"]), float(row["charge_start_second"]), int(row.get("charge_day_offset", 0)))
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(str(row["customer_id"]), str(row["served_by_depot_id"]))
            for row in payload.get("cross_site_services", [])
        ],
    )


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({field for row in rows for field in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)
    return proc.stdout


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _format_seed_list(seeds: list[int]) -> str:
    return ",".join(str(seed) for seed in seeds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run winner-kernel restoration diagnostics.")
    parser.add_argument("stage", choices=["verify-gold", "run-current", "classify-regression", "verify-restored", "static-audit"])
    parser.add_argument("--repo-root", default=str(_repo_root()))
    parser.add_argument("--output-dir", default=str(_repo_root() / RESTORATION_DIR))
    parser.add_argument("--seeds", default="1-10")
    parser.add_argument("--eval-budget", type=int, default=16_000)
    parser.add_argument("--max-runtime-seconds", type=float, default=900.0)
    args = parser.parse_args(argv)
    out = Path(args.output_dir)
    if args.stage == "verify-gold":
        result = verify_gold(args.repo_root, out)
    elif args.stage == "run-current":
        result = run_current(
            args.repo_root,
            out,
            seeds=_parse_seed_list(args.seeds),
            eval_budget=args.eval_budget,
            max_runtime_seconds=args.max_runtime_seconds,
        )
    elif args.stage == "verify-restored":
        result = verify_restored(
            args.repo_root,
            out,
            seeds=_parse_seed_list(args.seeds),
            eval_budget=args.eval_budget,
            max_runtime_seconds=args.max_runtime_seconds,
        )
    elif args.stage == "static-audit":
        result = static_recipe_audit()
        _write_json(out / "phase2_static_recipe_audit.json", result)
    else:
        rows = _read_csv(out / "phase2_current_vs_gold.csv")
        result = classify_regression([_coerce_row(row) for row in rows], static_recipe_audit())
        _write_json(out / "phase2_regression_classification.json", result)
    print(f"GATE WINNER_RESTORATION {args.stage} {json.dumps(result if args.stage != 'run-current' else {'gate': result['gate'], 'summary': result['summary'], 'classification': result['classification']}, ensure_ascii=False)}")
    return 0


def _read_csv(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _coerce_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            out[key] = value
            continue
        out[key] = int(number) if number.is_integer() else number
    return out


if __name__ == "__main__":
    raise SystemExit(main())
