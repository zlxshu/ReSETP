#!/usr/bin/env python3
"""Diagnostic-only A3 strong-bridge backend alignment probe."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
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
from setp_solver.check import check_solution
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution, solution_signature_hash
import setp_solver.search.winner_operators as wo
from setp_solver.search.winner_operators import STRONG_BRIDGE_BACKEND_FLAG, TRACE_DIAGNOSTIC_FLAG, WinnerKernelConfig


OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/strong_bridge_backend_probe_local_search_check_20260706"
HARD_SUBSET_PATH = REPO_ROOT / "baselines/e2_alns/route_compression_probe_20260705/hard_subset_instances.csv"
LNS_REFERENCE_DIR = REPO_ROOT / "baselines/e2_alns/lns_acceptance_scheduler_audit_20260705"
ALNS_PROFILES = (
    "A0_THROUGHPUT_ONLY",
    "A3_BACKEND_ONLY",
    "A0_MAIN_LOCAL_SEARCH",
    "A3_BACKEND_LOCAL_SEARCH",
)
PROFILES = (*ALNS_PROFILES, "LNS_TRACE_REFERENCE")
PROFILE_COMPARISONS = {
    "BACKEND_ONLY": {
        "a0": "A0_THROUGHPUT_ONLY",
        "a3": "A3_BACKEND_ONLY",
        "promising": "A3_BACKEND_ONLY_PROMISING",
        "not_supported": "A3_BACKEND_ONLY_NOT_SUPPORTED",
    },
    "MAIN_LOCAL_SEARCH": {
        "a0": "A0_MAIN_LOCAL_SEARCH",
        "a3": "A3_BACKEND_LOCAL_SEARCH",
        "promising": "A3_BACKEND_LOCAL_SEARCH_PROMISING",
        "not_supported": "A3_BACKEND_LOCAL_SEARCH_NOT_SUPPORTED",
    },
}
HASH_EXCLUDE_NAMES = {"artifact_hashes.json", ".DS_Store"}
HASH_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".tasks"}
PROTECTED_PATHS = trace_audit.PROTECTED_PATHS
APPROVED_WORKTREE_SHA256 = {
    "solver/src/setp_solver/cost.py": "e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--eval-budget", type=int, default=4000)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--runtime-cap-seconds", type=float, default=900.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-runs", action="store_true")
    parser.add_argument("--task-json", default="")
    parser.add_argument("--task-output-json", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.task_json:
        row = run_probe_task(fc.read_json(Path(args.task_json)))
        if args.task_output_json:
            fc.write_json(Path(args.task_output_json), row)
        return 0

    output_dir = fc.repo_path(Path(args.output_dir))
    if output_dir.exists() and args.force:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs = output_dir / "logs/full_run.log"
    logs.parent.mkdir(parents=True, exist_ok=True)
    metadata = build_metadata(args, output_dir)
    fc.write_json(output_dir / "metadata.json", metadata)
    log_event(logs, "start", head=metadata["head"])

    protected = protected_diff()
    reference_issues = validate_lns_reference(
        load_hard_subset(HARD_SUBSET_PATH) if HARD_SUBSET_PATH.exists() else [],
        parse_seeds(args.seeds),
        int(args.eval_budget),
    )
    if protected or not HARD_SUBSET_PATH.exists() or reference_issues:
        decision = halt_decision(
            metadata,
            protected,
            ([] if HARD_SUBSET_PATH.exists() else [fc.rel(HARD_SUBSET_PATH)]) + reference_issues,
        )
        write_empty_outputs(output_dir)
        fc.write_json(output_dir / "decision.json", decision)
        write_hashes(output_dir)
        print_status("strong_bridge_backend_probe_halt", 0, 0, 0, 1, True, "preflight", int(args.workers))
        return 2

    hard_subset = load_hard_subset(HARD_SUBSET_PATH)
    tasks = build_probe_tasks(
        output_dir,
        hard_subset,
        seeds=parse_seeds(args.seeds),
        eval_budget=int(args.eval_budget),
        runtime_cap_seconds=float(args.runtime_cap_seconds),
    )
    expected_rows = len(tasks)
    rows = collect_existing_rows(output_dir, tasks)
    if not args.skip_runs:
        rows = run_probe_tasks(output_dir, tasks, workers=int(args.workers), force=bool(args.force), logs=logs)

    raw_rows = raw_run_rows(rows)
    candidate_trace: list[dict[str, Any]] = []
    for profile in ALNS_PROFILES:
        candidate_trace.extend(trace_audit.flatten_trace_rows(rows, profile))
    profile_summary = summarize_profiles(raw_rows, candidate_trace)
    pair_comparison = compare_a3_vs_a0(raw_rows, candidate_trace)
    diagnosis = write_diagnosis(rows, expected_rows, profile_summary, pair_comparison)
    next_action = write_next_action(profile_summary, pair_comparison)
    decision = build_decision(
        metadata=metadata,
        rows=rows,
        expected_rows=expected_rows,
        profile_summary=profile_summary,
        pair_comparison=pair_comparison,
    )

    fc.write_csv(output_dir / "raw_runs.csv", raw_rows)
    fc.write_csv(output_dir / "alns_candidate_trace.csv", candidate_trace)
    fc.write_csv(output_dir / "profile_summary.csv", profile_summary)
    fc.write_csv(output_dir / "a3_vs_a0_pair_comparison.csv", pair_comparison)
    write_flags_by_profile(output_dir)
    (output_dir / "diagnosis.md").write_text(diagnosis, encoding="utf-8")
    (output_dir / "next_action.md").write_text(next_action, encoding="utf-8")
    fc.write_json(output_dir / "decision.json", decision)
    write_hashes(output_dir)
    fail = sum(1 for row in rows if row.get("status") != "OK")
    log_event(logs, "complete", rows=len(rows), expected=expected_rows, fail=fail, verdict=decision["verdict"])
    print_status(
        "strong_bridge_backend_probe_complete",
        len(rows),
        expected_rows,
        len(rows) - fail,
        fail,
        bool(decision.get("halt")),
        "hard_subset",
        int(args.workers),
    )
    return 0 if not decision.get("halt") else 2


def build_metadata(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    return {
        "schema": "setp-e2-strong-bridge-backend-probe-metadata.v1",
        "task": "strong_bridge_backend_probe",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "head": fc.git_head(),
        "python": sys.executable,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "output_dir": fc.rel(output_dir),
        "hard_subset_source": fc.rel(HARD_SUBSET_PATH),
        "lns_reference_source": fc.rel(LNS_REFERENCE_DIR),
        "profiles": list(PROFILES),
        "seeds": parse_seeds(args.seeds),
        "eval_budget": int(args.eval_budget),
        "runtime_cap_seconds": float(args.runtime_cap_seconds),
        "workers": int(args.workers),
        "trace_flag": TRACE_DIAGNOSTIC_FLAG,
        "strong_bridge_backend_flag": STRONG_BRIDGE_BACKEND_FLAG,
        "boundary": "diagnostic A3 backend alignment only; no Tier1/Tier2/Tier3 claim",
        "started_at_epoch": time.time(),
    }


def load_hard_subset(path: Path = HARD_SUBSET_PATH) -> list[dict[str, str]]:
    rows = fc.read_csv(path)
    return [{"category": str(row["category"]), "instance": str(row["instance"])} for row in rows if row.get("category") and row.get("instance")]


def profile_flags(profile: str) -> dict[str, str]:
    normalized = str(profile)
    if normalized not in ALNS_PROFILES:
        raise ValueError(f"Unsupported ALNS probe profile: {profile}")
    flags = wo.e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=True)
    flags[TRACE_DIAGNOSTIC_FLAG] = "1"
    flags[STRONG_BRIDGE_BACKEND_FLAG] = "1" if normalized.startswith("A3_") else "0"
    flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"] = "1" if normalized.endswith("_LOCAL_SEARCH") else "0"
    assert_profile_flags(normalized, flags)
    return flags


def assert_profile_flags(profile: str, flags: dict[str, str]) -> None:
    expected_local = "1" if str(profile).endswith("_LOCAL_SEARCH") else "0"
    expected_backend = "1" if str(profile).startswith("A3_") else "0"
    actual_local = str(flags.get("SETP_ALNS_CRUSH_LOCAL_SEARCH"))
    actual_backend = str(flags.get(STRONG_BRIDGE_BACKEND_FLAG))
    if actual_local != expected_local:
        raise AssertionError(f"{profile} expected SETP_ALNS_CRUSH_LOCAL_SEARCH={expected_local}, got {actual_local}")
    if actual_backend != expected_backend:
        raise AssertionError(f"{profile} expected {STRONG_BRIDGE_BACKEND_FLAG}={expected_backend}, got {actual_backend}")


def flags_by_profile() -> dict[str, dict[str, str]]:
    return {profile: profile_flags(profile) for profile in ALNS_PROFILES}


def write_flags_by_profile(output_dir: Path) -> None:
    fc.write_json(
        output_dir / "flags_by_profile.json",
        {
            "schema": "setp-e2-strong-bridge-backend-flags-by-profile.v1",
            "profiles": flags_by_profile(),
        },
    )


def build_probe_tasks(
    output_dir: Path,
    hard_subset: list[dict[str, Any]],
    *,
    seeds: list[int],
    eval_budget: int,
    runtime_cap_seconds: float,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for item in hard_subset:
        category = str(item["category"])
        instance = str(item["instance"])
        for seed in seeds:
            for profile in PROFILES:
                run_id = f"STRONG_BRIDGE_BACKEND_PROBE__{category}__{instance}__{profile}__seed{int(seed)}"
                tasks.append(
                    {
                        "schema": "setp-e2-strong-bridge-backend-probe-task.v1",
                        "repo_root": str(REPO_ROOT),
                        "phase": "STRONG_BRIDGE_BACKEND_PROBE",
                        "run_id": sanitize_run_id(run_id),
                        "category": category,
                        "instance": instance,
                        "bundle_dir": str(Path("models/data_bundle/generated_instances/e2_benchmark") / category / instance),
                        "profile": profile,
                        "algorithm": "LNS" if profile == "LNS_TRACE_REFERENCE" else "alns_e2_throughput",
                        "seed": int(seed),
                        "eval_budget": int(eval_budget),
                        "runtime_cap_seconds": float(runtime_cap_seconds),
                        "scenario_type": "formal_goeke80",
                        "checkpoint_path": str(output_dir / "checkpoints" / f"{sanitize_run_id(run_id)}.json"),
                        "head": fc.git_head(),
                    }
                )
    return tasks


def run_probe_tasks(output_dir: Path, tasks: list[dict[str, Any]], *, workers: int, force: bool, logs: Path) -> list[dict[str, Any]]:
    existing = {str(row.get("run_id")): row for row in collect_existing_rows(output_dir, tasks)}
    todo = [task for task in tasks if force or task["run_id"] not in existing]
    task_root = output_dir / ".tasks"
    task_root.mkdir(parents=True, exist_ok=True)
    if workers <= 1:
        for idx, task in enumerate(todo):
            row = execute_task_subprocess(task_root, task, idx, logs)
            existing[str(row.get("run_id", task["run_id"]))] = row
            fc.write_json(task_row_path(output_dir, str(row.get("run_id", task["run_id"]))), row)
    else:
        with ProcessPoolExecutor(max_workers=int(workers)) as pool:
            futures = {pool.submit(execute_task_subprocess, task_root, task, idx, logs): task for idx, task in enumerate(todo)}
            for future in as_completed(futures):
                task = futures[future]
                row = future.result()
                existing[str(row.get("run_id", task["run_id"]))] = row
                fc.write_json(task_row_path(output_dir, str(row.get("run_id", task["run_id"]))), row)
    for row in existing.values():
        fc.write_json(task_row_path(output_dir, str(row.get("run_id"))), row)
    return [existing[task["run_id"]] for task in tasks if task["run_id"] in existing]


def execute_task_subprocess(task_root: Path, task: dict[str, Any], idx: int, logs: Path) -> dict[str, Any]:
    task_path = task_root / f"{task['run_id']}__{idx}.json"
    row_path = task_root / f"{task['run_id']}__{idx}_row.json"
    fc.write_json(task_path, task)
    env = os.environ.copy()
    env["PYTHONPATH"] = "solver/src:models/src:."
    env["PYTHONHASHSEED"] = "0"
    command = [fc.GOLD_PYTHON, str(Path(__file__).resolve()), "--task-json", str(task_path), "--task-output-json", str(row_path)]
    started = time.perf_counter()
    log_event(logs, "task_start", run_id=task["run_id"], profile=task["profile"])
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=float(task["runtime_cap_seconds"]) + 30.0,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        row = worker_failure_row(task, "HALT_WORKER_TIMEOUT", f"stdout_tail={str(exc.stdout)[-800:]}; stderr_tail={str(exc.stderr)[-1200:]}", started)
        fc.write_json(row_path, row)
        return row
    if completed.returncode != 0 or not row_path.exists():
        reason = f"returncode={completed.returncode}; stdout_tail={completed.stdout[-800:]}; stderr_tail={completed.stderr[-1200:]}"
        row = worker_failure_row(task, "HALT_WORKER_ERROR", reason, started)
        fc.write_json(row_path, row)
        return row
    row = fc.read_json(row_path)
    log_event(logs, "task_complete", run_id=task["run_id"], status=row.get("status"), elapsed=time.perf_counter() - started)
    return row


def run_probe_task(task: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    profile = str(task["profile"])
    if profile == "LNS_TRACE_REFERENCE":
        return lns_reference_row(task, started)
    old_trace = os.environ.get(TRACE_DIAGNOSTIC_FLAG)
    old_backend = os.environ.get(STRONG_BRIDGE_BACKEND_FLAG)
    os.environ[TRACE_DIAGNOSTIC_FLAG] = "1"
    try:
        bundle_dir = REPO_ROOT / str(task["bundle_dir"])
        bundle = load_search_bundle(bundle_dir)
        prices = fc.prices_for_scenario(str(task["scenario_type"]))
        warm = make_shared_initial_solution(bundle, prices=prices)
        flags = profile_flags(profile)
        os.environ[STRONG_BRIDGE_BACKEND_FLAG] = flags[STRONG_BRIDGE_BACKEND_FLAG]
        config = WinnerKernelConfig(
            seed=int(task["seed"]),
            eval_budget=int(task["eval_budget"]),
            max_runtime_seconds=float(task["runtime_cap_seconds"]),
            include_route_elimination=flags.get("SETP_ALNS_CRUSH_ROUTE_ELIMINATION") == "1",
        )
        result = wo._run_winner_variant(  # noqa: SLF001 - diagnostic runner needs explicit flag injection.
            bundle_dir,
            config,
            initial_solution=warm,
            prices=prices,
            variant_flags=flags,
            variant_id=profile,
        )
        solution = result["best_solution"]
        best_cost = float(result["best_cost"])
        actual_evals = int(result["evaluations"])
        violations = check_solution(solution, bundle.instance, prices) if solution is not None else ["missing_solution"]
        status = "OK"
        failure_reason = ""
        if violations:
            status = "HALT_INFEASIBLE"
            failure_reason = "; ".join(str(item) for item in violations[:3])
        elif actual_evals < int(task["eval_budget"]):
            status = "HALT_UNDER_EVAL"
            failure_reason = f"Stopped at {actual_evals}/{task['eval_budget']} evaluations."
        operator_counts = dict(result.get("operator_counts", {}))
        return {
            "schema": "setp-e2-strong-bridge-backend-probe-row.v1",
            "run_id": task["run_id"],
            "phase": task["phase"],
            "category": task["category"],
            "instance": task["instance"],
            "profile": profile,
            "algorithm": task["algorithm"],
            "seed": int(task["seed"]),
            "status": status,
            "failure_reason": failure_reason,
            "eval_budget": int(task["eval_budget"]),
            "actual_evals": actual_evals,
            "runtime_cap_seconds": float(task["runtime_cap_seconds"]),
            "elapsed_seconds": time.perf_counter() - started,
            "best_cost": best_cost,
            "best_signature": solution_signature_hash(solution) if solution is not None else "",
            "feasible": solution is not None and not violations and math.isfinite(best_cost),
            "violation_count": len(violations),
            "route_count": len(solution.routes) if solution is not None else 0,
            "history": list(result.get("history", [])),
            "trace": list(operator_counts.get("candidate_trace", [])),
            "operator_counts": operator_counts,
            "flags": flags,
            "head": fc.git_head(),
        }
    except Exception as exc:
        return worker_failure_row(task, "HALT_WORKER_EXCEPTION", repr(exc), started)
    finally:
        restore_env(TRACE_DIAGNOSTIC_FLAG, old_trace)
        restore_env(STRONG_BRIDGE_BACKEND_FLAG, old_backend)


def lns_reference_row(task: dict[str, Any], started: float) -> dict[str, Any]:
    rows = lns_reference_trace_rows(str(task["category"]), str(task["instance"]), int(task["seed"]))
    if len(rows) < int(task["eval_budget"]):
        return worker_failure_row(task, "HALT_LNS_REFERENCE_INCOMPLETE", f"reference_trace_rows={len(rows)}", started)
    best_cost = best_lns_reference_cost(rows)
    best_candidates = [row for row in rows if as_float(row.get("candidate_obj")) <= best_cost + 1e-9]
    route_count = int(as_float((best_candidates[-1] if best_candidates else rows[-1]).get("candidate_route_count", 0)))
    return {
        "schema": "setp-e2-strong-bridge-backend-probe-row.v1",
        "run_id": task["run_id"],
        "phase": task["phase"],
        "category": task["category"],
        "instance": task["instance"],
        "profile": "LNS_TRACE_REFERENCE",
        "algorithm": "LNS",
        "seed": int(task["seed"]),
        "status": "OK",
        "failure_reason": "",
        "eval_budget": int(task["eval_budget"]),
        "actual_evals": int(task["eval_budget"]),
        "runtime_cap_seconds": float(task["runtime_cap_seconds"]),
        "elapsed_seconds": time.perf_counter() - started,
        "best_cost": float(best_cost),
        "best_signature": str(rows[-1].get("signature", "")),
        "feasible": True,
        "violation_count": 0,
        "route_count": route_count,
        "history": [],
        "trace": [],
        "operator_counts": {},
        "flags": {"baseline": "LNS_TRACE_REFERENCE", "source": fc.rel(LNS_REFERENCE_DIR)},
        "head": fc.git_head(),
    }


def lns_reference_trace_rows(category: str, instance: str, seed: int) -> list[dict[str, Any]]:
    path = LNS_REFERENCE_DIR / "lns_scheduler_trace.csv"
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("category") == category and row.get("instance") == instance and int(as_float(row.get("seed"))) == int(seed):
                out.append(row)
    return out


def best_lns_reference_cost(rows: list[dict[str, Any]]) -> float:
    candidates: list[float] = []
    for row in rows:
        candidates.extend([as_float(row.get("previous_best_obj")), as_float(row.get("candidate_obj"))])
    finite = [value for value in candidates if math.isfinite(value)]
    return min(finite) if finite else math.inf


def validate_lns_reference(hard_subset: list[dict[str, str]], seeds: list[int], eval_budget: int) -> list[str]:
    issues: list[str] = []
    decision_path = LNS_REFERENCE_DIR / "decision.json"
    trace_path = LNS_REFERENCE_DIR / "lns_scheduler_trace.csv"
    if not decision_path.exists() or not trace_path.exists():
        return [fc.rel(decision_path), fc.rel(trace_path)]
    decision = fc.read_json(decision_path)
    if decision.get("verdict") != "TRACE_AUDIT_COMPLETE" or decision.get("halt"):
        issues.append(f"{fc.rel(decision_path)}: verdict={decision.get('verdict')} halt={decision.get('halt')}")
    counts: dict[tuple[str, str, int], int] = {}
    with trace_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (str(row.get("category")), str(row.get("instance")), int(as_float(row.get("seed"))))
            counts[key] = counts.get(key, 0) + 1
    for item in hard_subset:
        for seed in seeds:
            key = (str(item["category"]), str(item["instance"]), int(seed))
            if counts.get(key, 0) < int(eval_budget):
                issues.append(f"LNS reference incomplete for {key}: {counts.get(key, 0)}/{eval_budget}")
    return issues


def raw_run_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = [
        "run_id",
        "phase",
        "category",
        "instance",
        "profile",
        "algorithm",
        "seed",
        "status",
        "failure_reason",
        "eval_budget",
        "actual_evals",
        "best_cost",
        "best_signature",
        "feasible",
        "violation_count",
        "route_count",
    ]
    return [{key: row.get(key, "") for key in keys} for row in rows]


def summarize_profiles(raw_rows: list[dict[str, Any]], trace_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lns_by_key = {
        (row["category"], row["instance"], int(as_float(row["seed"]))): as_float(row["best_cost"])
        for row in raw_rows
        if row.get("profile") == "LNS_TRACE_REFERENCE" and row.get("status") == "OK"
    }
    trace_by_profile: dict[str, list[dict[str, Any]]] = {}
    for row in trace_rows:
        trace_by_profile.setdefault(str(row.get("profile")), []).append(row)
    out: list[dict[str, Any]] = []
    for profile in PROFILES:
        items = [row for row in raw_rows if row.get("profile") == profile]
        ok_items = [row for row in items if row.get("status") == "OK"]
        gaps = []
        for row in ok_items:
            key = (row["category"], row["instance"], int(as_float(row["seed"])))
            lns = lns_by_key.get(key)
            if lns and math.isfinite(lns):
                gaps.append((lns - as_float(row["best_cost"])) / lns)
        traces = trace_by_profile.get(profile, [])
        out.append(
            {
                "profile": profile,
                "rows": len(items),
                "ok_rows": len(ok_items),
                "fail_rows": len(items) - len(ok_items),
                "infeasible_rows": sum(1 for row in items if row.get("status") == "HALT_INFEASIBLE" or as_int(row.get("violation_count")) > 0),
                "under_eval_rows": sum(1 for row in items if row.get("status") == "HALT_UNDER_EVAL" or as_int(row.get("actual_evals")) < as_int(row.get("eval_budget"))),
                "mean_best_cost": mean_known(row.get("best_cost") for row in ok_items),
                "mean_gap_vs_lns": mean_known(gaps),
                "unchanged_rate": rate(traces, lambda row: str(row.get("revert_reason")) == "unchanged"),
                "best_improved_rate": rate(traces, lambda row: truthy(row.get("best_improved"))),
                "strong_bridge_backend_rate": rate(traces, lambda row: str(row.get("candidate_backend")) == "strong_bridge_backend"),
            }
        )
    return out


def compare_a3_vs_a0(raw_rows: list[dict[str, Any]], trace_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key_profile = {
        (row["category"], row["instance"], int(as_float(row["seed"])), row["profile"]): row
        for row in raw_rows
        if row.get("status") == "OK"
    }
    trace_by_profile = {profile: [row for row in trace_rows if row.get("profile") == profile] for profile in ALNS_PROFILES}
    rows: list[dict[str, Any]] = []
    aggregate_rows: list[dict[str, Any]] = []
    keys = sorted({(category, instance, seed) for category, instance, seed, _profile in by_key_profile})
    for group, spec in PROFILE_COMPARISONS.items():
        a0_profile = str(spec["a0"])
        a3_profile = str(spec["a3"])
        wins = losses = ties = 0
        a0_gaps: list[float] = []
        a3_gaps: list[float] = []
        for category, instance, seed in keys:
            a0 = by_key_profile.get((category, instance, seed, a0_profile))
            a3 = by_key_profile.get((category, instance, seed, a3_profile))
            lns = by_key_profile.get((category, instance, seed, "LNS_TRACE_REFERENCE"))
            if not (a0 and a3 and lns):
                continue
            lns_cost = as_float(lns["best_cost"])
            a0_cost = as_float(a0["best_cost"])
            a3_cost = as_float(a3["best_cost"])
            a0_gap = (lns_cost - a0_cost) / lns_cost
            a3_gap = (lns_cost - a3_cost) / lns_cost
            a0_gaps.append(a0_gap)
            a3_gaps.append(a3_gap)
            if a3_cost < a0_cost - 1e-9:
                outcome = "A3_BETTER"
                wins += 1
            elif a3_cost > a0_cost + 1e-9:
                outcome = "A3_WORSE"
                losses += 1
            else:
                outcome = "TIE"
                ties += 1
            rows.append(
                {
                    "scope": "run",
                    "comparison_group": group,
                    "category": category,
                    "instance": instance,
                    "seed": seed,
                    "a0_profile": a0_profile,
                    "a3_profile": a3_profile,
                    "a0_best_cost": a0_cost,
                    "a3_best_cost": a3_cost,
                    "lns_best_cost": lns_cost,
                    "a0_gap_vs_lns": a0_gap,
                    "a3_gap_vs_lns": a3_gap,
                    "outcome_vs_a0": outcome,
                }
            )
        aggregate_rows.append(
            {
                "scope": "ALL",
                "comparison_group": group,
                "category": "ALL",
                "instance": "ALL",
                "seed": "ALL",
                "a0_profile": a0_profile,
                "a3_profile": a3_profile,
                "wins_vs_a0": wins,
                "losses_vs_a0": losses,
                "ties_vs_a0": ties,
                "a0_mean_gap_vs_lns": mean_known(a0_gaps),
                "a3_mean_gap_vs_lns": mean_known(a3_gaps),
                "a0_unchanged_rate": rate(trace_by_profile.get(a0_profile, []), lambda row: str(row.get("revert_reason")) == "unchanged"),
                "a3_unchanged_rate": rate(trace_by_profile.get(a3_profile, []), lambda row: str(row.get("revert_reason")) == "unchanged"),
                "a0_best_improved_rate": rate(trace_by_profile.get(a0_profile, []), lambda row: truthy(row.get("best_improved"))),
                "a3_best_improved_rate": rate(trace_by_profile.get(a3_profile, []), lambda row: truthy(row.get("best_improved"))),
            }
        )
    rows = aggregate_rows + rows
    return rows


def comparison_aggregate(pair_comparison: list[dict[str, Any]], group: str) -> dict[str, Any]:
    return next((row for row in pair_comparison if row.get("scope") == "ALL" and row.get("comparison_group") == group), {})


def comparison_supported(
    group: str,
    summary: dict[str, dict[str, Any]],
    aggregate: dict[str, Any],
) -> bool:
    spec = PROFILE_COMPARISONS[group]
    a0 = summary.get(str(spec["a0"]), {})
    a3 = summary.get(str(spec["a3"]), {})
    return (
        as_float(a3.get("mean_gap_vs_lns")) > as_float(a0.get("mean_gap_vs_lns"))
        and as_int(aggregate.get("wins_vs_a0")) >= as_int(aggregate.get("losses_vs_a0"))
        and as_float(a3.get("unchanged_rate")) < as_float(a0.get("unchanged_rate"))
        and as_float(a3.get("best_improved_rate")) > as_float(a0.get("best_improved_rate"))
        and as_int(a3.get("infeasible_rows")) == 0
        and as_int(a3.get("under_eval_rows")) == 0
    )


def build_comparison_results(profile_summary: list[dict[str, Any]], pair_comparison: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary = {str(row.get("profile")): row for row in profile_summary}
    out: dict[str, dict[str, Any]] = {}
    for group, spec in PROFILE_COMPARISONS.items():
        aggregate = comparison_aggregate(pair_comparison, group)
        supported = comparison_supported(group, summary, aggregate)
        verdict = str(spec["promising"] if supported else spec["not_supported"])
        out[group] = {
            "verdict": verdict,
            "a0_profile": spec["a0"],
            "a3_profile": spec["a3"],
            "aggregate": aggregate,
        }
    return out


def build_decision(
    *,
    metadata: dict[str, Any],
    rows: list[dict[str, Any]],
    expected_rows: int,
    profile_summary: list[dict[str, Any]],
    pair_comparison: list[dict[str, Any]],
) -> dict[str, Any]:
    fail_rows = [row for row in rows if row.get("status") != "OK"]
    protected = protected_diff()
    if fail_rows or len(rows) != expected_rows or protected:
        verdict = "HALT_STRONG_BRIDGE_BACKEND_PROFILE_ALIGNMENT"
        halt = True
        comparison_results = build_comparison_results(profile_summary, pair_comparison)
    else:
        comparison_results = build_comparison_results(profile_summary, pair_comparison)
        verdict = str(comparison_results.get("MAIN_LOCAL_SEARCH", {}).get("verdict", "A3_BACKEND_LOCAL_SEARCH_NOT_SUPPORTED"))
        halt = False
    return {
        "schema": "setp-e2-strong-bridge-backend-probe-decision.v1",
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
        "profile_summary": profile_summary,
        "comparison_results": comparison_results,
        "a3_vs_a0": comparison_results.get("MAIN_LOCAL_SEARCH", {}).get("aggregate", {}),
        "a3_vs_a0_by_group": {group: data.get("aggregate", {}) for group, data in comparison_results.items()},
        "protected_diff": protected,
    }


def write_diagnosis(rows: list[dict[str, Any]], expected_rows: int, profile_summary: list[dict[str, Any]], pair_comparison: list[dict[str, Any]]) -> str:
    ok = sum(1 for row in rows if row.get("status") == "OK")
    comparison_results = build_comparison_results(profile_summary, pair_comparison)
    return "\n".join(
        [
            "# A3 Strong-Bridge Backend Profile-Alignment Diagnosis",
            "",
            "Verdict scope: diagnostic only, not formal T3.",
            f"Rows: {len(rows)}/{expected_rows}; OK={ok}; fail={len(rows) - ok}.",
            "",
            "Root-cause correction: this run separates backend-only from the current main profile with LOCAL_SEARCH.",
            "",
            "Profile summary:",
            *[
                f"- {row['profile']}: mean_gap_vs_lns={row.get('mean_gap_vs_lns')}, unchanged_rate={row.get('unchanged_rate')}, best_improved_rate={row.get('best_improved_rate')}"
                for row in profile_summary
            ],
            "",
            "Comparison summary:",
            *[
                (
                    f"- {group}: verdict={data.get('verdict')}, "
                    f"a0={data.get('a0_profile')}, a3={data.get('a3_profile')}, "
                    f"wins={data.get('aggregate', {}).get('wins_vs_a0')}, "
                    f"losses={data.get('aggregate', {}).get('losses_vs_a0')}, "
                    f"ties={data.get('aggregate', {}).get('ties_vs_a0')}, "
                    f"a0_mean_gap={data.get('aggregate', {}).get('a0_mean_gap_vs_lns')}, "
                    f"a3_mean_gap={data.get('aggregate', {}).get('a3_mean_gap_vs_lns')}"
                )
                for group, data in comparison_results.items()
            ],
        ]
    )


def write_next_action(profile_summary: list[dict[str, Any]], pair_comparison: list[dict[str, Any]]) -> str:
    decision = build_decision(metadata={}, rows=[{"status": "OK"}], expected_rows=1, profile_summary=profile_summary, pair_comparison=pair_comparison)
    if decision["verdict"] == "A3_BACKEND_LOCAL_SEARCH_PROMISING":
        symptom = "A3 backend alignment improved the current main LOCAL_SEARCH profile"
        remedy = "rerun A3 at 8000 eval hard subset before any additional algorithm change"
        pass_gate = "8000 eval repeats mean-gap, win/loss, unchanged-rate, and best-improved-rate improvements with zero HALT rows"
        fail_gate = "8000 eval loses the 4000 eval improvements or any protected/under-eval/worker-failure condition appears"
    else:
        symptom = "A3 backend alignment did not pass the corrected main LOCAL_SEARCH direction-support gate"
        remedy = "stop backend tuning and split q-size, scheduler, and acceptance as separate one-variable probes"
        pass_gate = "a later single-variable probe passes without protected/under-eval/worker failures"
        fail_gate = "the same unsupported backend pattern repeats or UNKNOWN dominates trace fields"
    return "\n".join(
        [
            "# Next Action",
            "",
            f"problem_symptom -> {symptom}",
            "evidence -> see decision.json and a3_vs_a0_pair_comparison.csv",
            f"minimal_remedy -> {remedy}",
            f"pass_gate -> {pass_gate}",
            f"fail_gate -> {fail_gate}",
            "",
            "Boundary: no Tier1/Tier2/Tier3, no LNS weakening, no RELAXED_ROUTE_COMPRESSION tuning, no oracle/ejection-chain/cross-exchange.",
        ]
    )


def halt_decision(metadata: dict[str, Any], protected: list[str], missing: list[str]) -> dict[str, Any]:
    return {
        "schema": "setp-e2-strong-bridge-backend-probe-decision.v1",
        "verdict": "HALT_PREFLIGHT",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "head": metadata.get("head", ""),
        "protected_diff": protected,
        "missing_or_incomplete": missing,
        "halt": True,
    }


def write_empty_outputs(output_dir: Path) -> None:
    fc.write_csv(output_dir / "raw_runs.csv", [])
    fc.write_csv(output_dir / "alns_candidate_trace.csv", [])
    fc.write_csv(output_dir / "profile_summary.csv", [])
    fc.write_csv(output_dir / "a3_vs_a0_pair_comparison.csv", [])
    fc.write_json(output_dir / "flags_by_profile.json", {"schema": "setp-e2-strong-bridge-backend-flags-by-profile.v1", "profiles": {}})
    (output_dir / "diagnosis.md").write_text("", encoding="utf-8")
    (output_dir / "next_action.md").write_text("", encoding="utf-8")


def collect_existing_rows(output_dir: Path, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        path = task_row_path(output_dir, str(task["run_id"]))
        if path.exists():
            rows.append(fc.read_json(path))
    return rows


def task_row_path(output_dir: Path, run_id: str) -> Path:
    return output_dir / ".tasks" / "rows" / f"{sanitize_run_id(run_id)}.json"


def worker_failure_row(task: dict[str, Any], status: str, reason: str, started: float) -> dict[str, Any]:
    return {
        "schema": "setp-e2-strong-bridge-backend-probe-row.v1",
        "run_id": task.get("run_id", ""),
        "phase": task.get("phase", ""),
        "category": task.get("category", ""),
        "instance": task.get("instance", ""),
        "profile": task.get("profile", ""),
        "algorithm": task.get("algorithm", ""),
        "seed": task.get("seed", ""),
        "status": status,
        "failure_reason": reason,
        "eval_budget": task.get("eval_budget", 0),
        "actual_evals": 0,
        "runtime_cap_seconds": task.get("runtime_cap_seconds", 0),
        "elapsed_seconds": time.perf_counter() - started,
        "best_cost": math.inf,
        "best_signature": "",
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
    return sorted(
        relative
        for relative in changed
        if not (
            relative in APPROVED_WORKTREE_SHA256
            and (REPO_ROOT / relative).is_file()
            and sha256_file(REPO_ROOT / relative)
            == APPROVED_WORKTREE_SHA256[relative]
        )
    )


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


def print_status(phase: str, rows: int, expected: int, ok: int, fail: int, halt: bool, current: str, workers: int) -> None:
    print(
        json.dumps(
            {
                "phase": phase,
                "rows": f"{rows}/{expected}",
                "ok": ok,
                "fail": fail,
                "halt": halt,
                "current_instance": current,
                "workers": int(workers),
                "decision_needed": False,
            },
            ensure_ascii=False,
        )
    )


def parse_seeds(text: str) -> list[int]:
    return [int(part.strip()) for part in str(text).split(",") if part.strip()]


def sanitize_run_id(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(text))


def restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def as_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return math.nan


def as_int(value: Any) -> int:
    try:
        return int(float(value))
    except Exception:
        return 0


def mean_known(values: Any) -> float | str:
    finite = [float(value) for value in values if math.isfinite(as_float(value))]
    if not finite:
        return "UNKNOWN"
    return sum(finite) / len(finite)


def rate(rows: list[dict[str, Any]], predicate: Any) -> float | str:
    if not rows:
        return "UNKNOWN"
    return sum(1 for row in rows if predicate(row)) / len(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def log_event(path: Path, event: str, **fields: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"event": event, "time": time.time(), **fields}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
