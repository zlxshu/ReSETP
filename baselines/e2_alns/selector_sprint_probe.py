#!/usr/bin/env python3
"""Diagnostic-only selector sprint for ALNS operator scheduling."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import gc
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "solver/src", REPO_ROOT / "models/src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from baselines.e2_alns import e2_final_closure as fc
from baselines.e2_alns import lns_acceptance_scheduler_audit as trace_audit
from baselines.e2_alns import selector_pathology_audit as selector_audit
from baselines.e2_alns import strong_bridge_backend_probe as a3_probe
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution, solution_signature_hash
from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline
import setp_solver.search.winner_operators as wo
from setp_solver.search.winner_operators import (
    BALANCED_SELECTOR_FLAG,
    EPS_DECAY_SELECTOR_FLAG,
    SOFTMAX_SELECTOR_FLAG,
    STRONG_BRIDGE_BACKEND_FLAG,
    THOMPSON_SELECTOR_FLAG,
    TRACE_DIAGNOSTIC_FLAG,
    WinnerKernelConfig,
)


OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/selector_sprint_probe_20260706"
HARD_SUBSET_PATH = REPO_ROOT / "baselines/e2_alns/route_compression_probe_20260705/hard_subset_instances.csv"
SELECTOR_AUDIT_DIR = REPO_ROOT / "baselines/e2_alns/selector_pathology_audit_20260706"
BALANCED_PROBE_DIR = REPO_ROOT / "baselines/e2_alns/balanced_selector_probe_20260706"
PROTECTED_PATHS = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/prices.py",
    "solver/src/setp_solver/search/feasible_repair.py",
    "docs/paper_submission_final/paper_main.tex",
    "paper_main.tex",
)
RUNTIME_CAP_SECONDS = {4000: 900.0, 8000: 1800.0, 16000: 3600.0}
BASE_PROFILE = "A0_MAIN_LOCAL_SEARCH"
LNS_PROFILE = "LNS_REFERENCE"
SELECTOR_PROFILES = (
    "A4_BALANCED_SELECTOR_LOCAL_SEARCH",
    "A5_EPS_DECAY_SELECTOR_LOCAL_SEARCH",
    "A6_THOMPSON_SELECTOR_LOCAL_SEARCH",
    "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH",
)
PROFILES_4000 = (BASE_PROFILE, *SELECTOR_PROFILES, LNS_PROFILE)
HASH_EXCLUDE_NAMES = {"artifact_hashes.json", ".DS_Store"}
HASH_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".tasks"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--budgets", default="4000,8000,16000")
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-runs", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = fc.repo_path(Path(args.output_dir))
    if output_dir.exists() and args.force:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs = output_dir / "logs/full_run.log"
    logs.parent.mkdir(parents=True, exist_ok=True)

    budgets = parse_ints(args.budgets)
    seeds = parse_ints(args.seeds)
    hard_subset = a3_probe.load_hard_subset(HARD_SUBSET_PATH) if HARD_SUBSET_PATH.exists() else []
    metadata = build_metadata(args, output_dir, budgets, seeds)
    fc.write_json(output_dir / "metadata.json", metadata)
    log_event(logs, "start", budgets=budgets, workers=int(args.workers), head=metadata["head"])

    issues = preflight_issues(hard_subset)
    if issues:
        write_empty_outputs(output_dir)
        decision = halt_decision(metadata, issues)
        fc.write_json(output_dir / "decision.json", decision)
        write_hashes(output_dir)
        log_event(logs, "halt", issues=issues)
        return 2
    if args.skip_runs:
        return finalize_from_existing_outputs(output_dir, metadata, budgets, seeds, hard_subset, logs)

    all_status_rows: list[dict[str, Any]] = []
    all_raw_rows: list[dict[str, Any]] = []
    all_usage_rows: list[dict[str, Any]] = []
    all_entropy_rows: list[dict[str, Any]] = []
    all_decomposition_rows: list[dict[str, Any]] = []
    all_trace_sample_rows: list[dict[str, Any]] = []
    all_gate_rows: list[dict[str, Any]] = []
    expected_total = 0
    selector_profiles = list(SELECTOR_PROFILES)

    for budget in budgets:
        if not selector_profiles:
            break
        tasks = build_stage_tasks(output_dir, hard_subset, seeds=seeds, budget=int(budget), selector_profiles=selector_profiles)
        expected_total += len(tasks)
        rows = collect_existing_rows(output_dir, tasks)
        if not args.skip_runs:
            rows = run_tasks(output_dir, tasks, workers=int(args.workers), force=bool(args.force), logs=logs)
        all_status_rows.extend(status_rows(rows))

        raw_rows = raw_run_rows(rows)
        trace_rows = flatten_alns_traces(rows, [BASE_PROFILE, *selector_profiles])
        all_raw_rows.extend(raw_rows)
        remaining_sample = max(0, 2000 - len(all_trace_sample_rows))
        if remaining_sample:
            all_trace_sample_rows.extend(trace_sample(trace_rows, limit=remaining_sample))
        profile_summary = summarize_profiles(raw_rows, trace_rows, budget=int(budget), profiles=[BASE_PROFILE, *selector_profiles, LNS_PROFILE])
        usage_rows = pair_usage_rows(trace_rows, budget=int(budget))
        entropy_rows = entropy_rows_for_usage(usage_rows, budget=int(budget))
        decomposition_rows = route_fixed_cost_decomposition(raw_rows, budget=int(budget))
        all_usage_rows.extend(usage_rows)
        all_entropy_rows.extend(entropy_rows)
        all_decomposition_rows.extend(decomposition_rows)
        comparison_rows = compare_selectors_vs_a0(raw_rows, trace_rows, budget=int(budget), selector_profiles=selector_profiles)
        previous_gaps = previous_gap_by_profile(all_gate_rows, previous_budget=int(budget))
        gate_rows = gate_rows_for_budget(
            budget=int(budget),
            profile_summary=profile_summary,
            comparisons=comparison_rows,
            entropy_rows=entropy_rows,
            decomposition_rows=decomposition_rows,
            previous_gaps=previous_gaps,
            protected=protected_diff(),
        )
        all_gate_rows.extend(gate_rows)

        fc.write_csv(output_dir / f"raw_runs_{int(budget)}.csv", raw_rows)
        fc.write_csv(output_dir / f"profile_summary_{int(budget)}.csv", profile_summary)
        write_trace_gzip(output_dir / f"selector_candidate_trace_{int(budget)}.csv.gz", trace_rows)
        selector_profiles = [str(row["profile"]) for row in gate_rows if truthy(row.get("pass_gate"))]
        log_event(logs, "budget_complete", budget=int(budget), rows=len(rows), survivors=selector_profiles)
        del rows, raw_rows, trace_rows
        gc.collect()

    winner_board = selector_winner_board(all_gate_rows)
    decision = build_decision(metadata, all_status_rows, expected_total, all_gate_rows)

    fc.write_csv(output_dir / "raw_runs.csv", all_raw_rows)
    fc.write_csv(output_dir / "selector_entropy_by_budget.csv", all_entropy_rows)
    fc.write_csv(output_dir / "pair_usage_by_budget.csv", all_usage_rows)
    fc.write_csv(output_dir / "route_fixed_cost_decomposition_by_budget.csv", all_decomposition_rows)
    fc.write_csv(output_dir / "selector_winner_board.csv", winner_board)
    fc.write_csv(output_dir / "selector_trace_sample.csv", all_trace_sample_rows)
    fc.write_json(output_dir / "tier1_pilot_manifest.json", tier1_manifest(decision, winner_board))
    (output_dir / "diagnosis.md").write_text(write_diagnosis(decision, all_gate_rows), encoding="utf-8")
    (output_dir / "next_action.md").write_text(write_next_action(decision), encoding="utf-8")
    (output_dir / "report.md").write_text(write_diagnosis(decision, all_gate_rows), encoding="utf-8")
    fc.write_json(output_dir / "decision.json", decision)
    write_hashes(output_dir)
    log_event(logs, "complete", verdict=decision["verdict"], rows=len(all_status_rows), expected=expected_total)
    print(json.dumps({"phase": "selector_sprint_complete", "verdict": decision["verdict"], "rows": f"{len(all_status_rows)}/{expected_total}"}, ensure_ascii=False))
    return 0 if not decision.get("halt") else 2


def finalize_from_existing_outputs(
    output_dir: Path,
    metadata: dict[str, Any],
    budgets: list[int],
    seeds: list[int],
    hard_subset: list[dict[str, Any]],
    logs: Path,
) -> int:
    all_raw_rows: list[dict[str, Any]] = []
    all_status_rows: list[dict[str, Any]] = []
    all_usage_rows: list[dict[str, Any]] = []
    all_entropy_rows: list[dict[str, Any]] = []
    all_decomposition_rows: list[dict[str, Any]] = []
    all_gate_rows: list[dict[str, Any]] = []
    expected_total = 0
    selector_profiles = list(SELECTOR_PROFILES)

    for budget in budgets:
        if not selector_profiles:
            break
        tasks = build_stage_tasks(output_dir, hard_subset, seeds=seeds, budget=int(budget), selector_profiles=selector_profiles)
        expected_total += len(tasks)
        raw_rows = [dict(row) for row in fc.read_csv(output_dir / f"raw_runs_{int(budget)}.csv")]
        profile_summary = [dict(row) for row in fc.read_csv(output_dir / f"profile_summary_{int(budget)}.csv")]
        if not raw_rows or not profile_summary:
            issues = [f"missing_existing_budget_outputs:{int(budget)}"]
            decision = halt_decision(metadata, issues)
            fc.write_json(output_dir / "decision.json", decision)
            write_hashes(output_dir)
            log_event(logs, "halt", issues=issues)
            return 2
        all_raw_rows.extend(raw_rows)
        all_status_rows.extend(status_rows(raw_rows))
        all_usage_rows.extend(pair_usage_from_gzip(output_dir / f"selector_candidate_trace_{int(budget)}.csv.gz", budget=int(budget)))
        entropy_rows = entropy_rows_from_profile_summary(profile_summary, budget=int(budget))
        decomposition_rows = route_fixed_cost_decomposition(raw_rows, budget=int(budget))
        comparison_rows = compare_selectors_vs_a0(raw_rows, [], budget=int(budget), selector_profiles=selector_profiles)
        previous_gaps = previous_gap_by_profile(all_gate_rows, previous_budget=int(budget))
        gate_rows = gate_rows_for_budget(
            budget=int(budget),
            profile_summary=profile_summary,
            comparisons=comparison_rows,
            entropy_rows=entropy_rows,
            decomposition_rows=decomposition_rows,
            previous_gaps=previous_gaps,
            protected=protected_diff(),
        )
        all_entropy_rows.extend(entropy_rows)
        all_decomposition_rows.extend(decomposition_rows)
        all_gate_rows.extend(gate_rows)
        selector_profiles = [str(row["profile"]) for row in gate_rows if truthy(row.get("pass_gate"))]

    winner_board = selector_winner_board(all_gate_rows)
    decision = build_decision(metadata, all_status_rows, expected_total, all_gate_rows)
    fc.write_csv(output_dir / "raw_runs.csv", all_raw_rows)
    fc.write_csv(output_dir / "selector_entropy_by_budget.csv", all_entropy_rows)
    fc.write_csv(output_dir / "pair_usage_by_budget.csv", all_usage_rows)
    fc.write_csv(output_dir / "route_fixed_cost_decomposition_by_budget.csv", all_decomposition_rows)
    fc.write_csv(output_dir / "selector_winner_board.csv", winner_board)
    fc.write_csv(output_dir / "selector_trace_sample.csv", trace_sample_from_gzip(output_dir, budgets))
    fc.write_json(output_dir / "tier1_pilot_manifest.json", tier1_manifest(decision, winner_board))
    (output_dir / "diagnosis.md").write_text(write_diagnosis(decision, all_gate_rows), encoding="utf-8")
    (output_dir / "next_action.md").write_text(write_next_action(decision), encoding="utf-8")
    (output_dir / "report.md").write_text(write_diagnosis(decision, all_gate_rows), encoding="utf-8")
    fc.write_json(output_dir / "decision.json", decision)
    write_hashes(output_dir)
    log_event(logs, "complete", verdict=decision["verdict"], rows=len(all_status_rows), expected=expected_total)
    print(json.dumps({"phase": "selector_sprint_complete", "verdict": decision["verdict"], "rows": f"{len(all_status_rows)}/{expected_total}"}, ensure_ascii=False))
    return 0 if not decision.get("halt") else 2


def profile_flags(profile: str) -> dict[str, str]:
    if profile == LNS_PROFILE:
        raise ValueError("LNS_REFERENCE does not use ALNS flags")
    if profile not in {BASE_PROFILE, *SELECTOR_PROFILES}:
        raise ValueError(f"Unsupported selector sprint profile: {profile}")
    flags = wo.e2_alns_throughput_flags()
    flags[TRACE_DIAGNOSTIC_FLAG] = "1"
    flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"] = "1"
    flags[STRONG_BRIDGE_BACKEND_FLAG] = "0"
    for name in (BALANCED_SELECTOR_FLAG, EPS_DECAY_SELECTOR_FLAG, THOMPSON_SELECTOR_FLAG, SOFTMAX_SELECTOR_FLAG):
        flags[name] = "0"
    if profile == "A4_BALANCED_SELECTOR_LOCAL_SEARCH":
        flags[BALANCED_SELECTOR_FLAG] = "1"
    elif profile == "A5_EPS_DECAY_SELECTOR_LOCAL_SEARCH":
        flags[EPS_DECAY_SELECTOR_FLAG] = "1"
    elif profile == "A6_THOMPSON_SELECTOR_LOCAL_SEARCH":
        flags[THOMPSON_SELECTOR_FLAG] = "1"
    elif profile == "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH":
        flags[SOFTMAX_SELECTOR_FLAG] = "1"
    return flags


def build_stage_tasks(
    output_dir: Path,
    hard_subset: list[dict[str, Any]],
    *,
    seeds: list[int],
    budget: int,
    selector_profiles: list[str],
) -> list[dict[str, Any]]:
    profiles = [BASE_PROFILE, *selector_profiles, LNS_PROFILE]
    tasks: list[dict[str, Any]] = []
    for item in hard_subset:
        category = str(item["category"])
        instance = str(item["instance"])
        for seed in seeds:
            for profile in profiles:
                run_id = sanitize_run_id(f"SELECTOR_SPRINT__b{int(budget)}__{category}__{instance}__{profile}__seed{int(seed)}")
                tasks.append(
                    {
                        "schema": "setp-e2-selector-sprint-task.v1",
                        "repo_root": str(REPO_ROOT),
                        "phase": f"SELECTOR_SPRINT_{int(budget)}",
                        "budget": int(budget),
                        "run_id": run_id,
                        "category": category,
                        "instance": instance,
                        "bundle_dir": str(Path("models/data_bundle/generated_instances/e2_benchmark") / category / instance),
                        "profile": profile,
                        "algorithm": "LNS" if profile == LNS_PROFILE else "alns_e2_throughput",
                        "seed": int(seed),
                        "eval_budget": int(budget),
                        "runtime_cap_seconds": float(RUNTIME_CAP_SECONDS.get(int(budget), 900.0)),
                        "scenario_type": "formal_goeke80",
                        "checkpoint_path": str(output_dir / "checkpoints" / f"{run_id}.json"),
                        "head": fc.git_head(),
                    }
                )
    return tasks


def run_tasks(output_dir: Path, tasks: list[dict[str, Any]], *, workers: int, force: bool, logs: Path) -> list[dict[str, Any]]:
    existing = {str(row.get("run_id")): row for row in collect_existing_rows(output_dir, tasks)}
    todo = [task for task in tasks if force or task["run_id"] not in existing]
    if workers <= 1:
        for task in todo:
            row = run_task(task)
            existing[str(row.get("run_id", task["run_id"]))] = row
            fc.write_json(task_row_path(output_dir, str(row.get("run_id", task["run_id"]))), row)
            log_event(logs, "task_complete", run_id=task["run_id"], status=row.get("status"))
    else:
        with ProcessPoolExecutor(max_workers=int(workers)) as pool:
            futures = {pool.submit(run_task, task): task for task in todo}
            for future in as_completed(futures):
                task = futures[future]
                row = future.result()
                existing[str(row.get("run_id", task["run_id"]))] = row
                fc.write_json(task_row_path(output_dir, str(row.get("run_id", task["run_id"]))), row)
                log_event(logs, "task_complete", run_id=task["run_id"], status=row.get("status"))
    return [existing[task["run_id"]] for task in tasks if task["run_id"] in existing]


def run_task(task: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    old_trace = os.environ.get(TRACE_DIAGNOSTIC_FLAG)
    old_checkpoint = os.environ.get("SETP_E2_ALNS_CHECKPOINT_PATH")
    os.environ[TRACE_DIAGNOSTIC_FLAG] = "1"
    os.environ["SETP_E2_ALNS_CHECKPOINT_PATH"] = str(fc.repo_path(Path(task["checkpoint_path"])))
    try:
        bundle_dir = REPO_ROOT / str(task["bundle_dir"])
        bundle = load_search_bundle(bundle_dir)
        prices = fc.prices_for_scenario(str(task["scenario_type"]))
        warm = make_shared_initial_solution(bundle, prices=prices)
        if task["profile"] == LNS_PROFILE:
            result = run_metaheuristic_baseline(
                "LNS",
                bundle_dir,
                seed=int(task["seed"]),
                eval_budget=int(task["eval_budget"]),
                max_runtime_seconds=float(task["runtime_cap_seconds"]),
                initial_solution=warm,
                prices=prices,
                common_flip_preprocess=False,
            )
            solution = result.best_solution
            best_cost = float(result.best_cost)
            actual_evals = int(result.evals)
            trace = list(result.trace)
            history = list(result.history)
            operator_counts: dict[str, Any] = dict(result.operator_counts)
            flags = {"baseline": LNS_PROFILE, "trace_diagnostic": "1"}
        else:
            flags = profile_flags(str(task["profile"]))
            config = WinnerKernelConfig(
                seed=int(task["seed"]),
                eval_budget=int(task["eval_budget"]),
                max_runtime_seconds=float(task["runtime_cap_seconds"]),
            )
            result = wo._run_winner_variant(  # noqa: SLF001 - diagnostic runner needs explicit flag injection.
                bundle_dir,
                config,
                initial_solution=warm,
                prices=prices,
                variant_flags=flags,
                variant_id=str(task["profile"]),
            )
            solution = result["best_solution"]
            best_cost = float(result["best_cost"])
            actual_evals = int(result["evaluations"])
            operator_counts = dict(result.get("operator_counts", {}))
            trace = list(operator_counts.get("candidate_trace", []))
            history = list(result.get("history", []))
        return result_row(task, started, solution, best_cost, actual_evals, trace, history, operator_counts, flags, bundle, prices)
    except Exception as exc:
        return worker_failure_row(task, "HALT_WORKER_EXCEPTION", repr(exc), started)
    finally:
        restore_env(TRACE_DIAGNOSTIC_FLAG, old_trace)
        restore_env("SETP_E2_ALNS_CHECKPOINT_PATH", old_checkpoint)


def result_row(
    task: dict[str, Any],
    started: float,
    solution: Any,
    best_cost: float,
    actual_evals: int,
    trace: list[dict[str, Any]],
    history: list[dict[str, Any]],
    operator_counts: dict[str, Any],
    flags: dict[str, str],
    bundle: Any,
    prices: Any,
) -> dict[str, Any]:
    violations = check_solution(solution, bundle.instance, prices) if solution is not None else ["missing_solution"]
    status = "OK"
    failure_reason = ""
    if violations:
        status = "HALT_INFEASIBLE"
        failure_reason = "; ".join(str(item) for item in violations[:3])
    elif actual_evals < int(task["eval_budget"]):
        status = "HALT_UNDER_EVAL"
        failure_reason = f"Stopped at {actual_evals}/{task['eval_budget']} evaluations."
    metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices) if solution is not None else {}
    return {
        "schema": "setp-e2-selector-sprint-row.v1",
        "run_id": task["run_id"],
        "phase": task["phase"],
        "budget": int(task["budget"]),
        "category": task["category"],
        "instance": task["instance"],
        "profile": task["profile"],
        "algorithm": task["algorithm"],
        "seed": int(task["seed"]),
        "status": status,
        "failure_reason": failure_reason,
        "eval_budget": int(task["eval_budget"]),
        "actual_evals": int(actual_evals),
        "runtime_cap_seconds": float(task["runtime_cap_seconds"]),
        "elapsed_seconds": time.perf_counter() - started,
        "evals_per_second": safe_ratio(actual_evals, time.perf_counter() - started),
        "best_cost": best_cost,
        "best_signature": solution_signature_hash(solution) if solution is not None else "",
        "feasible": solution is not None and not violations and math.isfinite(best_cost),
        "violation_count": len(violations),
        "route_count": len(solution.routes) if solution is not None else 0,
        "cv_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv") if solution is not None else 0,
        "ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev") if solution is not None else 0,
        "charging_action_count": len(solution.charging_actions) if solution is not None else 0,
        "E_total": metrics.get("E_total", math.nan),
        "cost_fix": metrics.get("cost_fix", math.nan),
        "cost_km": metrics.get("cost_km", math.nan),
        "cost_carbon": metrics.get("cost_carbon", math.nan),
        "cost_fuel": metrics.get("cost_fuel", math.nan),
        "cost_elec": metrics.get("cost_elec", math.nan),
        "cost_occ": metrics.get("cost_occ", math.nan),
        "cost_transship": metrics.get("cost_transship", math.nan),
        "solution_json": json.dumps(fc.solution_to_dict(solution), ensure_ascii=False, sort_keys=True) if solution is not None else "",
        "checkpoint_path": fc.rel(fc.repo_path(Path(task["checkpoint_path"]))) if fc.repo_path(Path(task["checkpoint_path"])).exists() else "",
        "history": history,
        "trace": trace,
        "operator_counts": operator_counts,
        "flags": flags,
        "head": fc.git_head(),
    }


def raw_run_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = [
        "run_id",
        "phase",
        "budget",
        "category",
        "instance",
        "profile",
        "algorithm",
        "seed",
        "status",
        "failure_reason",
        "eval_budget",
        "actual_evals",
        "elapsed_seconds",
        "evals_per_second",
        "best_cost",
        "best_signature",
        "feasible",
        "violation_count",
        "route_count",
        "cv_route_count",
        "ev_route_count",
        "charging_action_count",
        "E_total",
        "cost_fix",
        "cost_km",
        "cost_carbon",
        "cost_fuel",
        "cost_elec",
        "cost_occ",
        "cost_transship",
        "solution_json",
        "checkpoint_path",
        "head",
    ]
    return [{key: row.get(key, "") for key in keys} for row in rows]


def status_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = [
        "run_id",
        "budget",
        "category",
        "instance",
        "profile",
        "seed",
        "status",
        "failure_reason",
        "actual_evals",
        "eval_budget",
        "violation_count",
    ]
    return [{key: row.get(key, "") for key in keys} for row in rows]


def entropy_rows_from_profile_summary(profile_summary: list[dict[str, Any]], *, budget: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in profile_summary:
        rows.append(
            {
                "budget": int(budget),
                "profile": row.get("profile", ""),
                "normalized_pair_entropy": row.get("normalized_pair_entropy", "UNKNOWN"),
                "top1_pair_share": row.get("top1_pair_share", "UNKNOWN"),
                "top2_pair_share": row.get("top2_pair_share", "UNKNOWN"),
            }
        )
    return rows


def flatten_alns_traces(rows: list[dict[str, Any]], profiles: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for profile in profiles:
        out.extend(trace_audit.flatten_trace_rows(rows, profile))
    for row in out:
        source = next((item for item in rows if item.get("run_id") == row.get("run_id")), {})
        row["budget"] = source.get("budget", row.get("budget", ""))
    return out


def summarize_profiles(
    raw_rows: list[dict[str, Any]],
    trace_rows: list[dict[str, Any]],
    *,
    budget: int,
    profiles: list[str],
) -> list[dict[str, Any]]:
    lns_by_key = {
        (row["category"], row["instance"], as_int(row["seed"])): as_float(row["best_cost"])
        for row in raw_rows
        if row.get("profile") == LNS_PROFILE and row.get("status") == "OK"
    }
    usage = pair_usage_rows(trace_rows, budget=budget)
    entropy = {row["profile"]: row for row in entropy_rows_for_usage(usage, budget=budget)}
    out = []
    for profile in profiles:
        items = [row for row in raw_rows if row.get("profile") == profile]
        ok_items = [row for row in items if row.get("status") == "OK"]
        gaps = []
        for row in ok_items:
            lns = lns_by_key.get((row["category"], row["instance"], as_int(row["seed"])))
            if lns and math.isfinite(lns):
                gaps.append((lns - as_float(row["best_cost"])) / lns)
        traces = [row for row in trace_rows if row.get("profile") == profile]
        ent = entropy.get(profile, {})
        out.append(
            {
                "budget": int(budget),
                "profile": profile,
                "rows": len(items),
                "ok_rows": len(ok_items),
                "fail_rows": len(items) - len(ok_items),
                "infeasible_rows": sum(1 for row in items if row.get("status") == "HALT_INFEASIBLE" or as_int(row.get("violation_count")) > 0),
                "under_eval_rows": sum(1 for row in items if row.get("status") == "HALT_UNDER_EVAL" or as_int(row.get("actual_evals")) < as_int(row.get("eval_budget"))),
                "mean_best_cost": mean_known(row.get("best_cost") for row in ok_items),
                "mean_gap_vs_lns": mean_known(gaps),
                "mean_route_count": mean_known(row.get("route_count") for row in ok_items),
                "mean_cost_fix": mean_known(row.get("cost_fix") for row in ok_items),
                "unchanged_rate": rate(traces, lambda row: str(row.get("revert_reason")) == "unchanged"),
                "best_improved_rate": rate(traces, lambda row: truthy(row.get("best_improved"))),
                "normalized_pair_entropy": ent.get("normalized_pair_entropy", "UNKNOWN"),
                "top1_pair_share": ent.get("top1_pair_share", "UNKNOWN"),
                "top2_pair_share": ent.get("top2_pair_share", "UNKNOWN"),
            }
        )
    return out


def pair_usage_rows(trace_rows: list[dict[str, Any]], *, budget: int | None = None) -> list[dict[str, Any]]:
    rows = selector_audit.selector_pair_usage(trace_rows)
    for row in rows:
        row["budget"] = budget if budget is not None else row.get("budget", "ALL")
    return rows


def entropy_rows_for_usage(usage_rows: list[dict[str, Any]], *, budget: int | None = None) -> list[dict[str, Any]]:
    rows = selector_audit.selector_entropy_by_profile(
        usage_rows,
        expected_pair_count_by_profile=selector_audit.expected_pair_counts(usage_rows),
    )
    for row in rows:
        row["budget"] = budget if budget is not None else row.get("budget", "ALL")
    return rows


def compare_selectors_vs_a0(
    raw_rows: list[dict[str, Any]],
    trace_rows: list[dict[str, Any]],
    *,
    budget: int,
    selector_profiles: list[str],
) -> list[dict[str, Any]]:
    by_key = {
        (row["category"], row["instance"], as_int(row["seed"]), row["profile"]): row
        for row in raw_rows
        if row.get("status") == "OK"
    }
    keys = sorted({(category, instance, seed) for category, instance, seed, _profile in by_key})
    out: list[dict[str, Any]] = []
    for profile in selector_profiles:
        wins = losses = ties = wins_lns = losses_lns = 0
        for category, instance, seed in keys:
            a0 = by_key.get((category, instance, seed, BASE_PROFILE))
            selector = by_key.get((category, instance, seed, profile))
            lns = by_key.get((category, instance, seed, LNS_PROFILE))
            if not (a0 and selector and lns):
                continue
            s_cost = as_float(selector["best_cost"])
            a_cost = as_float(a0["best_cost"])
            l_cost = as_float(lns["best_cost"])
            if s_cost < a_cost - 1e-9:
                wins += 1
            elif s_cost > a_cost + 1e-9:
                losses += 1
            else:
                ties += 1
            if s_cost < l_cost - 1e-9:
                wins_lns += 1
            elif s_cost > l_cost + 1e-9:
                losses_lns += 1
        selector_traces = [row for row in trace_rows if row.get("profile") == profile]
        a0_traces = [row for row in trace_rows if row.get("profile") == BASE_PROFILE]
        out.append(
            {
                "budget": int(budget),
                "scope": "ALL",
                "profile": profile,
                "wins_vs_a0": wins,
                "losses_vs_a0": losses,
                "ties_vs_a0": ties,
                "wins_vs_lns": wins_lns,
                "losses_vs_lns": losses_lns,
                "selector_best_improved_rate": rate(selector_traces, lambda row: truthy(row.get("best_improved"))),
                "a0_best_improved_rate": rate(a0_traces, lambda row: truthy(row.get("best_improved"))),
            }
        )
    return out


def gate_rows_for_budget(
    *,
    budget: int,
    profile_summary: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    entropy_rows: list[dict[str, Any]],
    decomposition_rows: list[dict[str, Any]],
    previous_gaps: dict[str, float],
    protected: list[str],
) -> list[dict[str, Any]]:
    summary = {str(row["profile"]): row for row in profile_summary}
    comp = {str(row["profile"]): row for row in comparisons}
    entropy = {str(row["profile"]): row for row in entropy_rows}
    a0 = summary.get(BASE_PROFILE, {})
    out = []
    for profile in [name for name in SELECTOR_PROFILES if name in summary]:
        selector = summary.get(profile, {})
        comparison = comp.get(profile, {})
        selector_gap = as_float(selector.get("mean_gap_vs_lns"))
        a0_gap = as_float(a0.get("mean_gap_vs_lns"))
        entropy_ok = as_float(selector.get("normalized_pair_entropy", entropy.get(profile, {}).get("normalized_pair_entropy"))) > as_float(a0.get("normalized_pair_entropy", entropy.get(BASE_PROFILE, {}).get("normalized_pair_entropy")))
        top_ok = (
            as_float(selector.get("top1_pair_share", entropy.get(profile, {}).get("top1_pair_share"))) < as_float(a0.get("top1_pair_share", entropy.get(BASE_PROFILE, {}).get("top1_pair_share")))
            and as_float(selector.get("top2_pair_share", entropy.get(profile, {}).get("top2_pair_share"))) < as_float(a0.get("top2_pair_share", entropy.get(BASE_PROFILE, {}).get("top2_pair_share")))
        )
        common_clean = (
            not protected
            and as_int(selector.get("fail_rows")) == 0
            and as_int(selector.get("infeasible_rows")) == 0
            and as_int(selector.get("under_eval_rows")) == 0
        )
        gap_ok = selector_gap > a0_gap
        wins_ok = as_int(comparison.get("wins_vs_a0")) >= as_int(comparison.get("losses_vs_a0"))
        scale_ok = True
        lns_ok = True
        fixed_ok = True
        if budget >= 8000:
            wins_ok = as_int(comparison.get("wins_vs_a0")) > as_int(comparison.get("losses_vs_a0"))
            previous_gap = previous_gaps.get(profile, math.nan)
            scale_ok = not math.isfinite(previous_gap) or selector_gap >= previous_gap - 0.005
        if budget >= 16000:
            lns_ok = selector_gap >= 0.0 and as_int(comparison.get("wins_vs_lns")) >= as_int(comparison.get("losses_vs_lns"))
            fixed_ok = route_fixed_not_worse(decomposition_rows, profile)
        pass_gate = common_clean and gap_ok and wins_ok and entropy_ok and top_ok and scale_ok and lns_ok and fixed_ok
        out.append(
            {
                "budget": int(budget),
                "profile": profile,
                "pass_gate": bool(pass_gate),
                "mean_gap_vs_lns": selector_gap,
                "a0_mean_gap_vs_lns": a0_gap,
                "wins_vs_a0": as_int(comparison.get("wins_vs_a0")),
                "losses_vs_a0": as_int(comparison.get("losses_vs_a0")),
                "wins_vs_lns": as_int(comparison.get("wins_vs_lns")),
                "losses_vs_lns": as_int(comparison.get("losses_vs_lns")),
                "normalized_entropy": selector.get("normalized_pair_entropy"),
                "a0_normalized_entropy": a0.get("normalized_pair_entropy"),
                "top1_pair_share": selector.get("top1_pair_share"),
                "top2_pair_share": selector.get("top2_pair_share"),
                "gap_gate": gap_ok,
                "wins_gate": wins_ok,
                "entropy_gate": entropy_ok,
                "top_share_gate": top_ok,
                "scale_gate": scale_ok,
                "lns_gate": lns_ok,
                "fixed_cost_gate": fixed_ok,
                "clean_gate": common_clean,
            }
        )
    return out


def route_fixed_cost_decomposition(raw_rows: list[dict[str, Any]], *, budget: int | None = None) -> list[dict[str, Any]]:
    by_key = {
        (row["category"], row["instance"], as_int(row["seed"]), row["profile"]): row
        for row in raw_rows
        if row.get("status") == "OK"
    }
    out: list[dict[str, Any]] = []
    for (category, instance, seed, profile), row in sorted(by_key.items()):
        lns = by_key.get((category, instance, seed, LNS_PROFILE), {})
        a0 = by_key.get((category, instance, seed, BASE_PROFILE), {})
        out.append(
            {
                "budget": budget if budget is not None else row.get("budget", "ALL"),
                "category": category,
                "instance": instance,
                "seed": seed,
                "profile": profile,
                "route_count": row.get("route_count", ""),
                "cv_route_count": row.get("cv_route_count", ""),
                "ev_route_count": row.get("ev_route_count", ""),
                "charging_action_count": row.get("charging_action_count", ""),
                "cost_fix": row.get("cost_fix", ""),
                "cost_km": row.get("cost_km", ""),
                "cost_carbon": row.get("cost_carbon", ""),
                "cost_fuel": row.get("cost_fuel", ""),
                "cost_elec": row.get("cost_elec", ""),
                "cost_occ": row.get("cost_occ", ""),
                "cost_transship": row.get("cost_transship", ""),
                "route_count_delta_vs_lns": as_float(row.get("route_count")) - as_float(lns.get("route_count")),
                "cost_fix_delta_vs_lns": as_float(row.get("cost_fix")) - as_float(lns.get("cost_fix")),
                "cost_fix_delta_vs_a0": as_float(row.get("cost_fix")) - as_float(a0.get("cost_fix")),
            }
        )
    return out


def route_fixed_not_worse(decomposition_rows: list[dict[str, Any]], profile: str) -> bool:
    selector_values = [as_float(row.get("cost_fix_delta_vs_lns")) for row in decomposition_rows if row.get("profile") == profile]
    a0_values = [as_float(row.get("cost_fix_delta_vs_lns")) for row in decomposition_rows if row.get("profile") == BASE_PROFILE]
    selector_mean = mean_float(selector_values)
    a0_mean = mean_float(a0_values)
    return not math.isfinite(selector_mean) or not math.isfinite(a0_mean) or selector_mean <= a0_mean + 1e-9


def previous_gap_by_profile(gate_rows: list[dict[str, Any]], *, previous_budget: int) -> dict[str, float]:
    previous_budget_map = {8000: 4000, 16000: 8000}
    wanted = previous_budget_map.get(int(previous_budget))
    if wanted is None:
        return {}
    return {str(row["profile"]): as_float(row.get("mean_gap_vs_lns")) for row in gate_rows if as_int(row.get("budget")) == wanted}


def sprint_verdict(gate_rows: list[dict[str, Any]], *, halt: bool = False) -> str:
    if halt:
        return "HALT_SELECTOR_SPRINT"
    passed = [row for row in gate_rows if truthy(row.get("pass_gate"))]
    if any(as_int(row.get("budget")) == 16000 for row in passed):
        return "SELECTOR_SPRINT_16000_SUPPORTED"
    if any(as_int(row.get("budget")) == 8000 for row in passed):
        return "SELECTOR_SPRINT_8000_SUPPORTED"
    if any(as_int(row.get("budget")) == 4000 for row in passed):
        return "SELECTOR_SPRINT_4000_ONLY"
    return "SELECTOR_SPRINT_NO_BRANCH_SUPPORTED"


def build_decision(metadata: dict[str, Any], rows: list[dict[str, Any]], expected_rows: int, gate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    fail_rows = [row for row in rows if row.get("status") != "OK"]
    protected = protected_diff()
    halt = bool(fail_rows or protected or len(rows) != expected_rows)
    verdict = sprint_verdict(gate_rows, halt=halt)
    winners = sorted(
        [row for row in gate_rows if as_int(row.get("budget")) == 16000 and truthy(row.get("pass_gate"))],
        key=lambda row: (
            -as_float(row.get("mean_gap_vs_lns")),
            -(as_int(row.get("wins_vs_lns")) - as_int(row.get("losses_vs_lns"))),
            abs(as_float(row.get("normalized_entropy")) - 0.75),
        ),
    )
    return {
        "schema": "setp-e2-selector-sprint-decision.v1",
        "verdict": verdict,
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "head": metadata.get("head", ""),
        "expected_rows": int(expected_rows),
        "rows": len(rows),
        "ok_rows": len(rows) - len(fail_rows),
        "fail_rows": len(fail_rows),
        "halt": halt,
        "protected_diff": protected,
        "gate_rows": gate_rows,
        "winner_profile": winners[0]["profile"] if winners else "",
    }


def selector_winner_board(gate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(gate_rows, key=lambda row: (as_int(row.get("budget")), str(row.get("profile"))))


def tier1_manifest(decision: dict[str, Any], winner_board: list[dict[str, Any]]) -> dict[str, Any]:
    winner = str(decision.get("winner_profile", ""))
    return {
        "schema": "setp-e2-selector-sprint-tier1-pilot-manifest.v1",
        "created": bool(winner),
        "diagnostic_only": True,
        "formal_t3": False,
        "profiles": [BASE_PROFILE, winner, LNS_PROFILE] if winner else [],
        "source_verdict": decision.get("verdict"),
        "source_board_rows": len(winner_board),
    }


def trace_sample(trace_rows: list[dict[str, Any]], *, limit: int = 2000) -> list[dict[str, Any]]:
    keys = [
        "budget",
        "run_id",
        "category",
        "instance",
        "profile",
        "seed",
        "trace_index",
        "destroy_id",
        "repair_id",
        "accepted",
        "best_improved",
        "revert_reason",
        "selector_type",
        "selector_phase",
        "selector_iter",
        "selector_pair_times",
        "selector_value",
        "selector_probability",
        "selector_epsilon",
        "selector_temperature",
    ]
    return [{key: row.get(key, "") for key in keys} for row in trace_rows[:limit]]


def trace_sample_from_gzip(output_dir: Path, budgets: list[int], *, limit: int = 2000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for budget in budgets:
        path = output_dir / f"selector_candidate_trace_{int(budget)}.csv.gz"
        if not path.exists():
            continue
        with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                rows.append(row)
                if len(rows) >= limit:
                    return rows
    return rows


def pair_usage_from_gzip(path: Path, *, budget: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    route_delta_sums: dict[tuple[str, str, str], float] = {}
    route_delta_counts: dict[tuple[str, str, str], int] = {}
    with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            profile = str(row.get("profile", "UNKNOWN") or "UNKNOWN")
            destroy = str(row.get("destroy_id", "UNKNOWN") or "UNKNOWN")
            repair = str(row.get("repair_id", "UNKNOWN") or "UNKNOWN")
            key = (profile, destroy, repair)
            bucket = buckets.setdefault(
                key,
                {
                    "budget": int(budget),
                    "profile": profile,
                    "destroy_id": destroy,
                    "repair_id": repair,
                    "pair": f"{destroy}+{repair}",
                    "attempts": 0,
                    "accepted_count": 0,
                    "best_improved_count": 0,
                    "unchanged_count": 0,
                },
            )
            bucket["attempts"] += 1
            if truthy(row.get("accepted")):
                bucket["accepted_count"] += 1
            if truthy(row.get("best_improved")):
                bucket["best_improved_count"] += 1
            if str(row.get("revert_reason")) == "unchanged":
                bucket["unchanged_count"] += 1
            delta = as_float(row.get("candidate_route_count_delta"))
            if math.isfinite(delta):
                route_delta_sums[key] = route_delta_sums.get(key, 0.0) + delta
                route_delta_counts[key] = route_delta_counts.get(key, 0) + 1
    rows: list[dict[str, Any]] = []
    for key, bucket in buckets.items():
        attempts = int(bucket["attempts"])
        delta_count = route_delta_counts.get(key, 0)
        row = {
            **bucket,
            "accepted_rate": safe_ratio(float(bucket["accepted_count"]), float(attempts)),
            "best_improved_rate": safe_ratio(float(bucket["best_improved_count"]), float(attempts)),
            "unchanged_rate": safe_ratio(float(bucket["unchanged_count"]), float(attempts)),
            "mean_candidate_route_count_delta": safe_ratio(route_delta_sums.get(key, 0.0), float(delta_count)) if delta_count else "UNKNOWN",
        }
        rows.append(row)
    selector_audit.mark_best_improved_top_members(rows, top_n=3)
    return sorted(rows, key=lambda row: (as_int(row.get("budget")), str(row["profile"]), -as_int(row["attempts"]), str(row["pair"])))


def write_trace_gzip(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write("")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with gzip.open(path, "wt", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_metadata(args: argparse.Namespace, output_dir: Path, budgets: list[int], seeds: list[int]) -> dict[str, Any]:
    return {
        "schema": "setp-e2-selector-sprint-metadata.v1",
        "task": "selector_sprint_probe",
        "diagnostic_only": True,
        "formal_t3": False,
        "head": fc.git_head(),
        "python": sys.executable,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "output_dir": fc.rel(output_dir),
        "hard_subset_source": fc.rel(HARD_SUBSET_PATH),
        "selector_audit_source": fc.rel(SELECTOR_AUDIT_DIR),
        "balanced_probe_source": fc.rel(BALANCED_PROBE_DIR),
        "budgets": budgets,
        "seeds": seeds,
        "profiles_4000": list(PROFILES_4000),
        "workers": int(args.workers),
        "boundary": "diagnostic selector scheduling only; no backend/q-size/acceptance/local-search depth change",
        "started_at_epoch": time.time(),
    }


def preflight_issues(hard_subset: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    if len(hard_subset) != 16:
        issues.append(f"hard_subset_count={len(hard_subset)}")
    for path, expected in (
        (SELECTOR_AUDIT_DIR / "decision.json", "SELECTOR_PATHOLOGY_SUPPORTED"),
        (BALANCED_PROBE_DIR / "decision.json", "A4_BALANCED_SELECTOR_PROMISING"),
    ):
        if not path.exists():
            issues.append(fc.rel(path))
            continue
        verdict = fc.read_json(path).get("verdict")
        if verdict != expected:
            issues.append(f"{fc.rel(path)}: verdict={verdict}")
    issues.extend([f"PROTECTED_DIFF:{path}" for path in protected_diff()])
    return issues


def halt_decision(metadata: dict[str, Any], issues: list[str]) -> dict[str, Any]:
    return {
        "schema": "setp-e2-selector-sprint-decision.v1",
        "verdict": "HALT_SELECTOR_SPRINT",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "head": metadata.get("head", ""),
        "halt": True,
        "issues": issues,
    }


def write_diagnosis(decision: dict[str, Any], gate_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Selector Sprint Diagnosis",
        "",
        f"Verdict: `{decision.get('verdict')}`.",
        "",
        "This is diagnostic-only selector scheduling evidence, not formal T3.",
        "",
        "Gate rows:",
    ]
    for row in gate_rows:
        lines.append(
            f"- budget={row.get('budget')} profile={row.get('profile')} pass={row.get('pass_gate')} "
            f"gap={row.get('mean_gap_vs_lns')} wins/losses={row.get('wins_vs_a0')}/{row.get('losses_vs_a0')}"
        )
    return "\n".join(lines) + "\n"


def write_next_action(decision: dict[str, Any]) -> str:
    verdict = decision.get("verdict")
    if verdict == "SELECTOR_SPRINT_16000_SUPPORTED":
        remedy = "generate and run Tier1 pilot manifest with A0 vs selector winner vs LNS only"
    elif verdict == "SELECTOR_SPRINT_8000_SUPPORTED":
        remedy = "perform one scale/category failure analysis; do not tune selector parameters in this round"
    elif verdict == "SELECTOR_SPRINT_4000_ONLY":
        remedy = "stop selector line at scale gate; do not promote to Tier1"
    elif verdict == "SELECTOR_SPRINT_NO_BRANCH_SUPPORTED":
        remedy = "stop selector line and move to another source-level root-cause audit"
    else:
        remedy = "fix HALT condition before any further diagnostic"
    return "\n".join(
        [
            "# Next Action",
            "",
            "problem_symptom -> selector pathology supported and A4 passed the first hard-subset gate",
            "evidence -> see decision.json, selector_winner_board.csv, and profile_summary_*.csv",
            f"minimal_remedy -> {remedy}",
            "pass_gate -> selector branch keeps budget-specific gates with zero HALT rows",
            "fail_gate -> any under-eval, protected diff, worker failure, or branch gate failure",
            "",
            "Boundary: no LNS weakening, no backend/q-size/acceptance stacking, no formal Tier1/Tier2/Tier3 claim.",
        ]
    )


def write_empty_outputs(output_dir: Path) -> None:
    for name in (
        "raw_runs.csv",
        "raw_runs_4000.csv",
        "profile_summary_4000.csv",
        "selector_entropy_by_budget.csv",
        "pair_usage_by_budget.csv",
        "route_fixed_cost_decomposition_by_budget.csv",
        "selector_winner_board.csv",
        "selector_trace_sample.csv",
    ):
        fc.write_csv(output_dir / name, [])
    fc.write_json(output_dir / "tier1_pilot_manifest.json", {"created": False})
    (output_dir / "diagnosis.md").write_text("", encoding="utf-8")
    (output_dir / "next_action.md").write_text("", encoding="utf-8")


def collect_existing_rows(output_dir: Path, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for task in tasks:
        path = task_row_path(output_dir, str(task["run_id"]))
        if path.exists():
            rows.append(fc.read_json(path))
    return rows


def task_row_path(output_dir: Path, run_id: str) -> Path:
    return output_dir / ".tasks" / "rows" / f"{sanitize_run_id(run_id)}.json"


def worker_failure_row(task: dict[str, Any], status: str, reason: str, started: float) -> dict[str, Any]:
    return {
        "schema": "setp-e2-selector-sprint-row.v1",
        "run_id": task.get("run_id", ""),
        "phase": task.get("phase", ""),
        "budget": task.get("budget", ""),
        "category": task.get("category", ""),
        "instance": task.get("instance", ""),
        "profile": task.get("profile", ""),
        "algorithm": task.get("algorithm", ""),
        "seed": task.get("seed", ""),
        "status": status,
        "failure_reason": reason,
        "eval_budget": task.get("eval_budget", 0),
        "actual_evals": 0,
        "elapsed_seconds": time.perf_counter() - started,
        "best_cost": math.inf,
        "feasible": False,
        "violation_count": -1,
        "route_count": 0,
        "history": [],
        "trace": [],
        "operator_counts": {},
        "flags": {},
        "head": fc.git_head(),
    }


def protected_diff() -> list[str]:
    changed: set[str] = set()
    for args in (["git", "diff", "--name-only", "--"], ["git", "diff", "--cached", "--name-only", "--"]):
        result = subprocess.run([*args, *PROTECTED_PATHS], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
        if result.stdout:
            changed.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return sorted(changed)


def write_hashes(output_dir: Path) -> None:
    files: dict[str, str] = {}
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(output_dir)
        if path.name.startswith("._") or path.name in HASH_EXCLUDE_NAMES:
            continue
        if any(part in HASH_EXCLUDE_PARTS for part in rel.parts):
            continue
        files[str(rel)] = sha256_file(path)
    fc.write_json(
        output_dir / "artifact_hashes.json",
        {
            "schema": "setp-artifact-hashes.v1",
            "root": fc.rel(output_dir),
            "excluded_names": sorted(HASH_EXCLUDE_NAMES),
            "excluded_parts": sorted(HASH_EXCLUDE_PARTS),
            "files": files,
        },
    )


def parse_ints(text: str) -> list[int]:
    return [int(part.strip()) for part in str(text).split(",") if part.strip()]


def sanitize_run_id(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._=-" else "_" for ch in str(text))


def restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes"}


def rate(rows: list[dict[str, Any]], predicate: Any) -> float:
    return sum(1 for row in rows if predicate(row)) / len(rows) if rows else 0.0


def mean_known(values: Any) -> float | str:
    numeric = [as_float(value) for value in values if math.isfinite(as_float(value))]
    return sum(numeric) / len(numeric) if numeric else "UNKNOWN"


def mean_float(values: list[float]) -> float:
    numeric = [value for value in values if math.isfinite(value)]
    return sum(numeric) / len(numeric) if numeric else math.nan


def as_float(value: object) -> float:
    try:
        if value in (None, "", "UNKNOWN", "N/A"):
            return math.nan
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def as_int(value: object) -> int:
    number = as_float(value)
    return int(number) if math.isfinite(number) else 0


def safe_ratio(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if float(denominator) > 0 else math.nan


def log_event(path: Path, event: str, **payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": event, "time": time.time(), **payload}, ensure_ascii=False, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
