#!/usr/bin/env python3
"""Diagnostic-only structural rescue probe after selector sprint scale failure."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gc
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
from baselines.e2_alns import selector_sprint_probe as sprint
from baselines.e2_alns import strong_bridge_backend_probe as a3_probe
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution, solution_signature_hash
from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline
import setp_solver.search.winner_operators as wo
from setp_solver.search.winner_operators import (
    ELITE_ARCHIVE_RESTART_FLAG,
    ROUTE_POOL_RECOMBINATION_FLAG,
    RVND_SWAPSTAR_FLAG,
    SOFTMAX_SELECTOR_FLAG,
    STRONG_BRIDGE_BACKEND_FLAG,
    TRACE_DIAGNOSTIC_FLAG,
    WinnerKernelConfig,
)


OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/structural_rescue_probe_20260707"
PRECHECK_DIR = REPO_ROOT / "baselines/e2_alns/selector_sprint_failure_analysis_20260707"
SELECTOR_SPRINT_DIR = REPO_ROOT / "baselines/e2_alns/selector_sprint_probe_20260706"
HARD_SUBSET_PATH = REPO_ROOT / "baselines/e2_alns/route_compression_probe_20260705/hard_subset_instances.csv"
RUNTIME_CAP_SECONDS = {4000: 900.0, 8000: 1800.0, 16000: 3600.0}
BASE_PROFILE = "A0_MAIN_LOCAL_SEARCH"
A7_PROFILE = "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH"
LNS_PROFILE = "LNS_REFERENCE"
STRUCTURAL_PROFILES = (
    "A8_ROUTE_POOL_RECOMBINATION",
    "A9_RVND_SWAPSTAR_LOCAL_SEARCH",
    "A10_ELITE_ARCHIVE_RESTART",
)
PROFILES_4000 = (BASE_PROFILE, A7_PROFILE, *STRUCTURAL_PROFILES, LNS_PROFILE)
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

    budgets = sprint.parse_ints(args.budgets)
    seeds = sprint.parse_ints(args.seeds)
    hard_subset = a3_probe.load_hard_subset(HARD_SUBSET_PATH) if HARD_SUBSET_PATH.exists() else []
    metadata = build_metadata(args, output_dir, budgets, seeds)
    fc.write_json(output_dir / "metadata.json", metadata)
    sprint.log_event(logs, "start", budgets=budgets, workers=int(args.workers), head=metadata["head"])

    issues, precheck_not_supported = preflight_issues(hard_subset)
    if issues or precheck_not_supported:
        write_empty_outputs(output_dir)
        decision = preflight_decision(metadata, issues, precheck_not_supported)
        fc.write_json(output_dir / "decision.json", decision)
        write_hashes(output_dir)
        sprint.log_event(logs, "preflight_stop", verdict=decision["verdict"], issues=issues)
        return 2 if decision.get("halt") else 0
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
    structural_profiles = list(STRUCTURAL_PROFILES)

    for budget in budgets:
        if not structural_profiles:
            break
        tasks = build_stage_tasks(output_dir, hard_subset, seeds=seeds, budget=int(budget), structural_profiles=structural_profiles)
        expected_total += len(tasks)
        reference_rows = reusable_reference_rows(hard_subset, seeds=seeds, budget=int(budget))
        runnable_tasks = [task for task in tasks if task["profile"] not in {BASE_PROFILE, A7_PROFILE, LNS_PROFILE}]
        if len(reference_rows) != len(tasks) - len(runnable_tasks):
            reference_rows = []
            runnable_tasks = tasks
        run_rows = run_tasks(output_dir, runnable_tasks, workers=int(args.workers), force=bool(args.force), logs=logs)
        rows = [*reference_rows, *run_rows]
        all_status_rows.extend(sprint.status_rows(rows))

        raw_rows = sprint.raw_run_rows(rows)
        trace_rows = sprint.flatten_alns_traces(rows, [BASE_PROFILE, A7_PROFILE, *structural_profiles])
        all_raw_rows.extend(raw_rows)
        remaining_sample = max(0, 2000 - len(all_trace_sample_rows))
        if remaining_sample:
            all_trace_sample_rows.extend(sprint.trace_sample(trace_rows, limit=remaining_sample))
        profile_summary = sprint.summarize_profiles(
            raw_rows,
            trace_rows,
            budget=int(budget),
            profiles=[BASE_PROFILE, A7_PROFILE, *structural_profiles, LNS_PROFILE],
        )
        usage_rows = sprint.pair_usage_rows(trace_rows, budget=int(budget))
        entropy_rows = sprint.entropy_rows_for_usage(usage_rows, budget=int(budget))
        decomposition_rows = sprint.route_fixed_cost_decomposition(raw_rows, budget=int(budget))
        comparison_rows = compare_structural_vs_a7(raw_rows, budget=int(budget), structural_profiles=structural_profiles)
        gate_rows = gate_rows_for_budget(
            budget=int(budget),
            raw_rows=raw_rows,
            profile_summary=profile_summary,
            comparisons=comparison_rows,
            decomposition_rows=decomposition_rows,
            protected=sprint.protected_diff(),
        )
        all_usage_rows.extend(usage_rows)
        all_entropy_rows.extend(entropy_rows)
        all_decomposition_rows.extend(decomposition_rows)
        all_gate_rows.extend(gate_rows)

        fc.write_csv(output_dir / f"raw_runs_{int(budget)}.csv", raw_rows)
        fc.write_csv(output_dir / f"profile_summary_{int(budget)}.csv", profile_summary)
        sprint.write_trace_gzip(output_dir / f"selector_candidate_trace_{int(budget)}.csv.gz", trace_rows)
        structural_profiles = [str(row["profile"]) for row in gate_rows if sprint.truthy(row.get("pass_gate"))]
        sprint.log_event(logs, "budget_complete", budget=int(budget), rows=len(rows), reused_reference_rows=len(reference_rows), survivors=structural_profiles)
        del rows, raw_rows, trace_rows
        gc.collect()

    winner_board = structural_winner_board(all_gate_rows)
    decision = build_decision(metadata, all_status_rows, expected_total, all_gate_rows)

    fc.write_csv(output_dir / "raw_runs.csv", all_raw_rows)
    fc.write_csv(output_dir / "selector_entropy_by_budget.csv", all_entropy_rows)
    fc.write_csv(output_dir / "pair_usage_by_budget.csv", all_usage_rows)
    fc.write_csv(output_dir / "route_fixed_cost_decomposition_by_budget.csv", all_decomposition_rows)
    fc.write_csv(output_dir / "structural_winner_board.csv", winner_board)
    fc.write_csv(output_dir / "selector_trace_sample.csv", all_trace_sample_rows)
    fc.write_json(output_dir / "tier1_pilot_manifest.json", tier1_manifest(decision, winner_board))
    (output_dir / "diagnosis.md").write_text(write_diagnosis(decision, all_gate_rows), encoding="utf-8")
    (output_dir / "next_action.md").write_text(write_next_action(decision), encoding="utf-8")
    (output_dir / "report.md").write_text(write_diagnosis(decision, all_gate_rows), encoding="utf-8")
    fc.write_json(output_dir / "decision.json", decision)
    write_hashes(output_dir)
    sprint.log_event(logs, "complete", verdict=decision["verdict"], rows=len(all_status_rows), expected=expected_total)
    print(json.dumps({"phase": "structural_rescue_complete", "verdict": decision["verdict"], "rows": f"{len(all_status_rows)}/{expected_total}"}, ensure_ascii=False))
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
    structural_profiles = list(STRUCTURAL_PROFILES)
    expected_total = 0
    for budget in budgets:
        if not structural_profiles:
            break
        tasks = build_stage_tasks(output_dir, hard_subset, seeds=seeds, budget=int(budget), structural_profiles=structural_profiles)
        expected_total += len(tasks)
        raw_rows = [dict(row) for row in fc.read_csv(output_dir / f"raw_runs_{int(budget)}.csv")]
        profile_summary = [dict(row) for row in fc.read_csv(output_dir / f"profile_summary_{int(budget)}.csv")]
        if not raw_rows or not profile_summary:
            decision = build_decision(metadata, [{"status": "HALT_MISSING_EXISTING"}], expected_total, all_gate_rows)
            fc.write_json(output_dir / "decision.json", decision)
            write_hashes(output_dir)
            return 2
        all_raw_rows.extend(raw_rows)
        all_status_rows.extend(sprint.status_rows(raw_rows))
        usage_rows = sprint.pair_usage_from_gzip(output_dir / f"selector_candidate_trace_{int(budget)}.csv.gz", budget=int(budget))
        entropy_rows = sprint.entropy_rows_from_profile_summary(profile_summary, budget=int(budget))
        decomposition_rows = sprint.route_fixed_cost_decomposition(raw_rows, budget=int(budget))
        comparison_rows = compare_structural_vs_a7(raw_rows, budget=int(budget), structural_profiles=structural_profiles)
        gate_rows = gate_rows_for_budget(
            budget=int(budget),
            raw_rows=raw_rows,
            profile_summary=profile_summary,
            comparisons=comparison_rows,
            decomposition_rows=decomposition_rows,
            protected=sprint.protected_diff(),
        )
        all_usage_rows.extend(usage_rows)
        all_entropy_rows.extend(entropy_rows)
        all_decomposition_rows.extend(decomposition_rows)
        all_gate_rows.extend(gate_rows)
        structural_profiles = [str(row["profile"]) for row in gate_rows if sprint.truthy(row.get("pass_gate"))]

    winner_board = structural_winner_board(all_gate_rows)
    decision = build_decision(metadata, all_status_rows, expected_total, all_gate_rows)
    fc.write_csv(output_dir / "raw_runs.csv", all_raw_rows)
    fc.write_csv(output_dir / "selector_entropy_by_budget.csv", all_entropy_rows)
    fc.write_csv(output_dir / "pair_usage_by_budget.csv", all_usage_rows)
    fc.write_csv(output_dir / "route_fixed_cost_decomposition_by_budget.csv", all_decomposition_rows)
    fc.write_csv(output_dir / "structural_winner_board.csv", winner_board)
    fc.write_csv(output_dir / "selector_trace_sample.csv", sprint.trace_sample_from_gzip(output_dir, budgets))
    fc.write_json(output_dir / "tier1_pilot_manifest.json", tier1_manifest(decision, winner_board))
    (output_dir / "diagnosis.md").write_text(write_diagnosis(decision, all_gate_rows), encoding="utf-8")
    (output_dir / "next_action.md").write_text(write_next_action(decision), encoding="utf-8")
    fc.write_json(output_dir / "decision.json", decision)
    write_hashes(output_dir)
    sprint.log_event(logs, "complete", verdict=decision["verdict"], rows=len(all_status_rows), expected=expected_total)
    return 0 if not decision.get("halt") else 2


def profile_flags(profile: str) -> dict[str, str]:
    if profile == LNS_PROFILE:
        raise ValueError("LNS_REFERENCE does not use ALNS flags")
    if profile == BASE_PROFILE:
        flags = sprint.profile_flags(BASE_PROFILE)
    elif profile in {A7_PROFILE, *STRUCTURAL_PROFILES}:
        flags = sprint.profile_flags(A7_PROFILE)
    else:
        raise ValueError(f"Unsupported structural rescue profile: {profile}")
    flags[TRACE_DIAGNOSTIC_FLAG] = "1"
    flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"] = "1"
    flags[STRONG_BRIDGE_BACKEND_FLAG] = "0"
    flags[SOFTMAX_SELECTOR_FLAG] = "1" if profile in {A7_PROFILE, *STRUCTURAL_PROFILES} else "0"
    for name in (ROUTE_POOL_RECOMBINATION_FLAG, RVND_SWAPSTAR_FLAG, ELITE_ARCHIVE_RESTART_FLAG):
        flags[name] = "0"
    if profile == "A8_ROUTE_POOL_RECOMBINATION":
        flags[ROUTE_POOL_RECOMBINATION_FLAG] = "1"
    elif profile == "A9_RVND_SWAPSTAR_LOCAL_SEARCH":
        flags[RVND_SWAPSTAR_FLAG] = "1"
    elif profile == "A10_ELITE_ARCHIVE_RESTART":
        flags[ELITE_ARCHIVE_RESTART_FLAG] = "1"
    wo.structural_component_from_flags(flags)
    return flags


def build_stage_tasks(
    output_dir: Path,
    hard_subset: list[dict[str, Any]],
    *,
    seeds: list[int],
    budget: int,
    structural_profiles: list[str],
) -> list[dict[str, Any]]:
    profiles = [BASE_PROFILE, A7_PROFILE, *structural_profiles, LNS_PROFILE]
    tasks: list[dict[str, Any]] = []
    for item in hard_subset:
        category = str(item["category"])
        instance = str(item["instance"])
        for seed in seeds:
            for profile in profiles:
                run_id = sprint.sanitize_run_id(f"STRUCTURAL_RESCUE__b{int(budget)}__{category}__{instance}__{profile}__seed{int(seed)}")
                tasks.append(
                    {
                        "schema": "setp-e2-structural-rescue-task.v1",
                        "repo_root": str(REPO_ROOT),
                        "phase": f"STRUCTURAL_RESCUE_{int(budget)}",
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
            sprint.log_event(logs, "task_complete", run_id=task["run_id"], status=row.get("status"))
    else:
        with ProcessPoolExecutor(max_workers=int(workers)) as pool:
            futures = {pool.submit(run_task, task): task for task in todo}
            for future in as_completed(futures):
                task = futures[future]
                row = future.result()
                existing[str(row.get("run_id", task["run_id"]))] = row
                fc.write_json(task_row_path(output_dir, str(row.get("run_id", task["run_id"]))), row)
                sprint.log_event(logs, "task_complete", run_id=task["run_id"], status=row.get("status"))
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
            result = wo._run_winner_variant(  # noqa: SLF001
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
        row = result_row(task, started, solution, best_cost, actual_evals, trace, history, operator_counts, flags, bundle, prices)
        return row
    except Exception as exc:
        reason = repr(exc)
        status = "HALT_CONFIG_CONFLICT_STRUCTURAL_FLAGS" if "HALT_CONFIG_CONFLICT_STRUCTURAL_FLAGS" in reason else "HALT_WORKER_EXCEPTION"
        return worker_failure_row(task, status, reason, started)
    finally:
        sprint.restore_env(TRACE_DIAGNOSTIC_FLAG, old_trace)
        sprint.restore_env("SETP_E2_ALNS_CHECKPOINT_PATH", old_checkpoint)


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
        "schema": "setp-e2-structural-rescue-row.v1",
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
        "evals_per_second": sprint.safe_ratio(actual_evals, time.perf_counter() - started),
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


def worker_failure_row(task: dict[str, Any], status: str, reason: str, started: float) -> dict[str, Any]:
    row = sprint.worker_failure_row(task, status, reason, started)
    row["schema"] = "setp-e2-structural-rescue-row.v1"
    return row


def compare_structural_vs_a7(
    raw_rows: list[dict[str, Any]],
    *,
    budget: int,
    structural_profiles: list[str],
) -> list[dict[str, Any]]:
    by_key = {
        (row["category"], row["instance"], sprint.as_int(row["seed"]), row["profile"]): row
        for row in raw_rows
        if row.get("status") == "OK"
    }
    keys = sorted({(category, instance, seed) for category, instance, seed, _profile in by_key})
    out = []
    for profile in structural_profiles:
        wins = losses = ties = wins_lns = losses_lns = 0
        for category, instance, seed in keys:
            a7 = by_key.get((category, instance, seed, A7_PROFILE))
            candidate = by_key.get((category, instance, seed, profile))
            lns = by_key.get((category, instance, seed, LNS_PROFILE))
            if not (a7 and candidate and lns):
                continue
            c_cost = sprint.as_float(candidate["best_cost"])
            a_cost = sprint.as_float(a7["best_cost"])
            l_cost = sprint.as_float(lns["best_cost"])
            if c_cost < a_cost - 1e-9:
                wins += 1
            elif c_cost > a_cost + 1e-9:
                losses += 1
            else:
                ties += 1
            if c_cost < l_cost - 1e-9:
                wins_lns += 1
            elif c_cost > l_cost + 1e-9:
                losses_lns += 1
        out.append(
            {
                "budget": int(budget),
                "profile": profile,
                "wins_vs_a7": wins,
                "losses_vs_a7": losses,
                "ties_vs_a7": ties,
                "wins_vs_lns": wins_lns,
                "losses_vs_lns": losses_lns,
            }
        )
    return out


def gate_rows_for_budget(
    *,
    budget: int,
    raw_rows: list[dict[str, Any]],
    profile_summary: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    decomposition_rows: list[dict[str, Any]],
    protected: list[str],
) -> list[dict[str, Any]]:
    summary = {str(row["profile"]): row for row in profile_summary}
    comp = {str(row["profile"]): row for row in comparisons}
    a7 = summary.get(A7_PROFILE, {})
    a7_route = mean_decomp(decomposition_rows, A7_PROFILE, "route_count_delta_vs_lns")
    a7_fix = mean_decomp(decomposition_rows, A7_PROFILE, "cost_fix_delta_vs_lns")
    a7_throughput = mean_raw(raw_rows, A7_PROFILE, "evals_per_second")
    out = []
    for profile in [name for name in STRUCTURAL_PROFILES if name in summary]:
        candidate = summary.get(profile, {})
        comparison = comp.get(profile, {})
        candidate_gap = sprint.as_float(candidate.get("mean_gap_vs_lns"))
        a7_gap = sprint.as_float(a7.get("mean_gap_vs_lns"))
        route_delta = mean_decomp(decomposition_rows, profile, "route_count_delta_vs_lns")
        fix_delta = mean_decomp(decomposition_rows, profile, "cost_fix_delta_vs_lns")
        throughput = mean_raw(raw_rows, profile, "evals_per_second")
        common_clean = (
            not protected
            and sprint.as_int(candidate.get("fail_rows")) == 0
            and sprint.as_int(candidate.get("infeasible_rows")) == 0
            and sprint.as_int(candidate.get("under_eval_rows")) == 0
        )
        gap_ok = candidate_gap > a7_gap
        wins_ok = sprint.as_int(comparison.get("wins_vs_a7")) >= sprint.as_int(comparison.get("losses_vs_a7"))
        route_ok = route_delta < a7_route - 1e-12
        fix_ok = fix_delta < a7_fix - 1e-12
        throughput_ok = True
        lns_ok = True
        if int(budget) >= 8000:
            wins_ok = sprint.as_int(comparison.get("wins_vs_a7")) > sprint.as_int(comparison.get("losses_vs_a7"))
            throughput_ok = not math.isfinite(a7_throughput) or not math.isfinite(throughput) or throughput >= 0.85 * a7_throughput
        if int(budget) >= 16000:
            lns_ok = (
                candidate_gap >= 0.0
                and sprint.as_int(comparison.get("wins_vs_lns")) >= sprint.as_int(comparison.get("losses_vs_lns"))
                and route_delta <= 0.0
                and fix_delta <= 0.0
            )
        pass_gate = common_clean and gap_ok and wins_ok and route_ok and fix_ok and throughput_ok and lns_ok
        out.append(
            {
                "budget": int(budget),
                "profile": profile,
                "pass_gate": bool(pass_gate),
                "mean_gap_vs_lns": candidate_gap,
                "a7_mean_gap_vs_lns": a7_gap,
                "wins_vs_a7": sprint.as_int(comparison.get("wins_vs_a7")),
                "losses_vs_a7": sprint.as_int(comparison.get("losses_vs_a7")),
                "wins_vs_lns": sprint.as_int(comparison.get("wins_vs_lns")),
                "losses_vs_lns": sprint.as_int(comparison.get("losses_vs_lns")),
                "route_count_delta_vs_lns": route_delta,
                "a7_route_count_delta_vs_lns": a7_route,
                "cost_fix_delta_vs_lns": fix_delta,
                "a7_cost_fix_delta_vs_lns": a7_fix,
                "evals_per_second": throughput,
                "a7_evals_per_second": a7_throughput,
                "gap_gate": gap_ok,
                "wins_gate": wins_ok,
                "route_count_gate": route_ok,
                "cost_fix_gate": fix_ok,
                "throughput_gate": throughput_ok,
                "lns_gate": lns_ok,
                "clean_gate": common_clean,
            }
        )
    return out


def structural_verdict(gate_rows: list[dict[str, Any]], *, halt: bool = False) -> str:
    if halt:
        return "HALT_STRUCTURAL_RESCUE"
    passed = [row for row in gate_rows if sprint.truthy(row.get("pass_gate"))]
    if any(sprint.as_int(row.get("budget")) == 16000 for row in passed):
        return "STRUCTURAL_RESCUE_16000_SUPPORTED"
    if any(sprint.as_int(row.get("budget")) == 8000 for row in passed):
        return "STRUCTURAL_RESCUE_8000_SUPPORTED"
    return "STRUCTURAL_RESCUE_ALL_FAILED"


def build_decision(metadata: dict[str, Any], rows: list[dict[str, Any]], expected_rows: int, gate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    fail_rows = [row for row in rows if row.get("status") != "OK"]
    protected = sprint.protected_diff()
    halt = bool(fail_rows or protected or len(rows) != expected_rows)
    verdict = structural_verdict(gate_rows, halt=halt)
    winners = sorted(
        [row for row in gate_rows if sprint.as_int(row.get("budget")) == 16000 and sprint.truthy(row.get("pass_gate"))],
        key=lambda row: (-sprint.as_float(row.get("mean_gap_vs_lns")), -(sprint.as_int(row.get("wins_vs_lns")) - sprint.as_int(row.get("losses_vs_lns")))),
    )
    return {
        "schema": "setp-e2-structural-rescue-decision.v1",
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


def structural_winner_board(gate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(gate_rows, key=lambda row: (sprint.as_int(row.get("budget")), str(row.get("profile"))))


def tier1_manifest(decision: dict[str, Any], winner_board: list[dict[str, Any]]) -> dict[str, Any]:
    winner = str(decision.get("winner_profile", ""))
    return {
        "schema": "setp-e2-structural-rescue-tier1-pilot-manifest.v1",
        "created": bool(winner),
        "diagnostic_only": True,
        "formal_t3": False,
        "profiles": [BASE_PROFILE, winner, LNS_PROFILE] if winner else [],
        "source_verdict": decision.get("verdict"),
        "source_board_rows": len(winner_board),
    }


def build_metadata(args: argparse.Namespace, output_dir: Path, budgets: list[int], seeds: list[int]) -> dict[str, Any]:
    return {
        "schema": "setp-e2-structural-rescue-metadata.v1",
        "task": "structural_rescue_probe",
        "diagnostic_only": True,
        "formal_t3": False,
        "head": fc.git_head(),
        "python": sys.executable,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "output_dir": fc.rel(output_dir),
        "precheck_source": fc.rel(PRECHECK_DIR),
        "selector_sprint_reference_source": fc.rel(SELECTOR_SPRINT_DIR),
        "hard_subset_source": fc.rel(HARD_SUBSET_PATH),
        "budgets": budgets,
        "seeds": seeds,
        "profiles_4000": list(PROFILES_4000),
        "workers": int(args.workers),
        "boundary": "diagnostic structural rescue only; no cost/check/evaluation/prices/feasible_repair/TeX change",
        "started_at_epoch": time.time(),
    }


def preflight_issues(hard_subset: list[dict[str, Any]]) -> tuple[list[str], bool]:
    issues: list[str] = []
    precheck_not_supported = False
    if len(hard_subset) != 16:
        issues.append(f"hard_subset_count={len(hard_subset)}")
    decision_path = PRECHECK_DIR / "decision.json"
    if not decision_path.exists():
        issues.append(fc.rel(decision_path))
    else:
        verdict = fc.read_json(decision_path).get("verdict")
        if verdict == "STRUCTURAL_RESCUE_PRECHECK_NOT_SUPPORTED":
            precheck_not_supported = True
        elif verdict != "STRUCTURAL_RESCUE_PRECHECK_SUPPORTED":
            issues.append(f"{fc.rel(decision_path)}: verdict={verdict}")
    issues.extend([f"PROTECTED_DIFF:{path}" for path in sprint.protected_diff()])
    return issues, precheck_not_supported


def reusable_reference_rows(
    hard_subset: list[dict[str, Any]],
    *,
    seeds: list[int],
    budget: int,
) -> list[dict[str, Any]]:
    path = SELECTOR_SPRINT_DIR / f"raw_runs_{int(budget)}.csv"
    if not path.exists():
        return []
    expected_keys = {
        (str(item["category"]), str(item["instance"]), int(seed), profile)
        for item in hard_subset
        for seed in seeds
        for profile in (BASE_PROFILE, A7_PROFILE, LNS_PROFILE)
    }
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, str]] = set()
    for row in fc.read_csv(path):
        key = (str(row.get("category")), str(row.get("instance")), sprint.as_int(row.get("seed")), str(row.get("profile")))
        if key not in expected_keys:
            continue
        copied = dict(row)
        copied["schema"] = "setp-e2-structural-rescue-reused-reference-row.v1"
        copied["phase"] = f"STRUCTURAL_RESCUE_{int(budget)}"
        copied["source_phase"] = row.get("phase", "")
        copied["source_run_id"] = row.get("run_id", "")
        copied["run_id"] = sprint.sanitize_run_id(f"STRUCTURAL_RESCUE_REUSE__b{int(budget)}__{key[0]}__{key[1]}__{key[3]}__seed{key[2]}")
        copied["budget"] = int(budget)
        rows.append(copied)
        seen.add(key)
    return rows if seen == expected_keys else []


def preflight_decision(metadata: dict[str, Any], issues: list[str], precheck_not_supported: bool) -> dict[str, Any]:
    if precheck_not_supported and not issues:
        return {
            "schema": "setp-e2-structural-rescue-decision.v1",
            "verdict": "STRUCTURAL_RESCUE_PRECHECK_NOT_SUPPORTED",
            "diagnostic_only": True,
            "formal_t3": False,
            "algorithm_win_loss_claim": False,
            "head": metadata.get("head", ""),
            "halt": False,
            "issues": [],
        }
    return {
        "schema": "setp-e2-structural-rescue-decision.v1",
        "verdict": "HALT_STRUCTURAL_RESCUE",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "head": metadata.get("head", ""),
        "halt": True,
        "issues": issues,
    }


def write_diagnosis(decision: dict[str, Any], gate_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Structural Rescue Diagnosis",
        "",
        f"Verdict: `{decision.get('verdict')}`.",
        "",
        "This is diagnostic-only structural-rescue evidence, not formal T3.",
        "",
        "Gate rows:",
    ]
    for row in gate_rows:
        lines.append(
            f"- budget={row.get('budget')} profile={row.get('profile')} pass={row.get('pass_gate')} "
            f"gap={row.get('mean_gap_vs_lns')} route_delta={row.get('route_count_delta_vs_lns')} "
            f"fix_delta={row.get('cost_fix_delta_vs_lns')} wins/losses={row.get('wins_vs_a7')}/{row.get('losses_vs_a7')}"
        )
    return "\n".join(lines) + "\n"


def write_next_action(decision: dict[str, Any]) -> str:
    verdict = decision.get("verdict")
    if verdict == "STRUCTURAL_RESCUE_16000_SUPPORTED":
        remedy = "prepare Tier1 pilot manifest with A0 vs structural winner vs LNS only"
    elif verdict == "STRUCTURAL_RESCUE_8000_SUPPORTED":
        remedy = "perform one scale/category failure analysis before any parameter tuning"
    elif verdict == "STRUCTURAL_RESCUE_ALL_FAILED":
        remedy = "stop pure ALNS rescue line; move to vehicle_type/fleet-charge audit or redefine hybrid algorithm scope"
    elif verdict == "STRUCTURAL_RESCUE_PRECHECK_NOT_SUPPORTED":
        remedy = "stop structural rescue because precheck did not support route/fixed residual"
    else:
        remedy = "resolve HALT condition before any new run"
    return "\n".join(
        [
            "# Next Action",
            "",
            "problem_symptom -> A7 long-budget residual remains below LNS",
            "evidence -> see decision.json, structural_winner_board.csv, and route_fixed_cost_decomposition_by_budget.csv",
            f"minimal_remedy -> {remedy}",
            "pass_gate -> route/fixed gap improves with zero HALT rows",
            "fail_gate -> under-eval, protected diff, infeasible row, worker failure, or route/fixed gate failure",
            "",
            "Boundary: no LNS weakening, no formal Tier1/Tier2/Tier3 claim, no stacked A8/A9/A10 branch.",
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
        "structural_winner_board.csv",
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
    return output_dir / ".tasks" / "rows" / f"{sprint.sanitize_run_id(run_id)}.json"


def mean_decomp(rows: list[dict[str, Any]], profile: str, field: str) -> float:
    return sprint.mean_float([sprint.as_float(row.get(field)) for row in rows if row.get("profile") == profile])


def mean_raw(rows: list[dict[str, Any]], profile: str, field: str) -> float:
    return sprint.mean_float([sprint.as_float(row.get(field)) for row in rows if row.get("profile") == profile and row.get("status") == "OK"])


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
