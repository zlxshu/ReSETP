#!/usr/bin/env python3
"""Diagnostic-only LNS scheduler/acceptance trace audit.

This script runs the hard subset only, under explicit trace instrumentation.
It is not a formal Tier run and does not change solver/evaluator semantics.
"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ProcessPoolExecutor, as_completed
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
from setp_solver.check import check_solution
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution, solution_signature_hash
from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline
import setp_solver.search.winner_operators as wo
from setp_solver.search.winner_operators import TRACE_DIAGNOSTIC_FLAG, WinnerKernelConfig


OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/lns_acceptance_scheduler_audit_20260705"
HARD_SUBSET_PATH = REPO_ROOT / "baselines/e2_alns/route_compression_probe_20260705/hard_subset_instances.csv"
PROFILES = ("LNS_TRACE", "A0_TRACE")
HASH_EXCLUDE_NAMES = {"artifact_hashes.json", ".DS_Store"}
HASH_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".tasks"}
PROTECTED_PATHS = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/prices.py",
    "solver/src/setp_solver/search/feasible_repair.py",
    "docs/paper_submission_final/RETIRED_paper_main.tex",
)


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
        task = fc.read_json(Path(args.task_json))
        row = run_trace_task(task)
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
    if protected or not HARD_SUBSET_PATH.exists():
        decision = halt_decision(metadata, protected, missing=[] if HARD_SUBSET_PATH.exists() else [fc.rel(HARD_SUBSET_PATH)])
        write_empty_outputs(output_dir)
        fc.write_json(output_dir / "decision.json", decision)
        write_hashes(output_dir)
        print_status("lns_acceptance_scheduler_audit_halt", 0, 0, 0, 1, True, "preflight", int(args.workers))
        return 2

    hard_subset = load_hard_subset(HARD_SUBSET_PATH)
    tasks = build_trace_tasks(
        output_dir,
        hard_subset,
        seeds=parse_seeds(args.seeds),
        eval_budget=int(args.eval_budget),
        runtime_cap_seconds=float(args.runtime_cap_seconds),
    )
    expected_rows = len(tasks)
    rows = collect_existing_rows(output_dir, tasks)
    if not args.skip_runs:
        rows = run_trace_tasks(output_dir, tasks, workers=int(args.workers), force=bool(args.force), logs=logs)

    lns_trace = flatten_trace_rows(rows, "LNS_TRACE")
    alns_trace = flatten_trace_rows(rows, "A0_TRACE")
    lns_summary = summarize_lns_path_contributions(lns_trace)
    alns_summary = summarize_alns_revert_reasons(alns_trace)
    diagnosis = write_diagnosis(rows, expected_rows, lns_summary, alns_summary)
    next_action = write_next_action(lns_summary, alns_summary)
    decision = build_decision(
        metadata=metadata,
        rows=rows,
        expected_rows=expected_rows,
        lns_summary=lns_summary,
        alns_summary=alns_summary,
    )

    fc.write_csv(output_dir / "lns_scheduler_trace.csv", lns_trace)
    fc.write_csv(output_dir / "alns_candidate_trace.csv", alns_trace)
    fc.write_csv(output_dir / "lns_path_contribution_summary.csv", lns_summary)
    fc.write_csv(output_dir / "alns_revert_reason_summary.csv", alns_summary)
    (output_dir / "diagnosis.md").write_text(diagnosis, encoding="utf-8")
    (output_dir / "next_action.md").write_text(next_action, encoding="utf-8")
    fc.write_json(output_dir / "decision.json", decision)
    write_hashes(output_dir)
    fail = sum(1 for row in rows if row.get("status") != "OK")
    log_event(logs, "complete", rows=len(rows), expected=expected_rows, fail=fail)
    print_status(
        "lns_acceptance_scheduler_audit_complete",
        len(rows),
        expected_rows,
        len(rows) - fail,
        fail,
        fail > 0 or len(rows) != expected_rows,
        "hard_subset",
        int(args.workers),
    )
    return 0 if fail == 0 and len(rows) == expected_rows else 2


def build_metadata(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    return {
        "schema": "setp-e2-lns-acceptance-scheduler-audit-metadata.v1",
        "task": "lns_acceptance_scheduler_audit",
        "diagnostic_only": True,
        "formal_t3": False,
        "head": fc.git_head(),
        "python": sys.executable,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "output_dir": fc.rel(output_dir),
        "hard_subset_source": fc.rel(HARD_SUBSET_PATH),
        "profiles": list(PROFILES),
        "seeds": parse_seeds(args.seeds),
        "eval_budget": int(args.eval_budget),
        "runtime_cap_seconds": float(args.runtime_cap_seconds),
        "workers": int(args.workers),
        "trace_flag": TRACE_DIAGNOSTIC_FLAG,
        "boundary": "diagnostic trace only; no Tier1/Tier2/Tier3 claim; no solver/evaluator protected edits",
        "started_at_epoch": time.time(),
    }


def load_hard_subset(path: Path = HARD_SUBSET_PATH) -> list[dict[str, str]]:
    rows = fc.read_csv(path)
    return [{"category": str(row["category"]), "instance": str(row["instance"])} for row in rows if row.get("category") and row.get("instance")]


def build_trace_tasks(
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
                run_id = f"LNS_ACCEPTANCE_SCHEDULER_AUDIT__{category}__{instance}__{profile}__seed{int(seed)}"
                tasks.append(
                    {
                        "schema": "setp-e2-lns-acceptance-scheduler-audit-task.v1",
                        "repo_root": str(REPO_ROOT),
                        "phase": "LNS_ACCEPTANCE_SCHEDULER_AUDIT",
                        "run_id": sanitize_run_id(run_id),
                        "category": category,
                        "instance": instance,
                        "bundle_dir": str(Path("models/data_bundle/generated_instances/e2_benchmark") / category / instance),
                        "profile": profile,
                        "algorithm": "LNS" if profile == "LNS_TRACE" else "alns_e2_throughput",
                        "seed": int(seed),
                        "eval_budget": int(eval_budget),
                        "runtime_cap_seconds": float(runtime_cap_seconds),
                        "scenario_type": "formal_goeke80",
                        "checkpoint_path": str(output_dir / "checkpoints" / f"{sanitize_run_id(run_id)}.json"),
                        "head": fc.git_head(),
                    }
                )
    return tasks


def run_trace_tasks(output_dir: Path, tasks: list[dict[str, Any]], *, workers: int, force: bool, logs: Path) -> list[dict[str, Any]]:
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
        log_event(logs, "task_timeout", run_id=task["run_id"], elapsed=time.perf_counter() - started)
        fc.write_json(row_path, row)
        return row
    if completed.returncode != 0 or not row_path.exists():
        reason = f"returncode={completed.returncode}; stdout_tail={completed.stdout[-800:]}; stderr_tail={completed.stderr[-1200:]}"
        row = worker_failure_row(task, "HALT_WORKER_ERROR", reason, started)
        fc.write_json(row_path, row)
        log_event(logs, "task_worker_error", run_id=task["run_id"], returncode=completed.returncode)
        return row
    row = fc.read_json(row_path)
    log_event(logs, "task_complete", run_id=task["run_id"], status=row.get("status"), elapsed=time.perf_counter() - started)
    return row


def run_trace_task(task: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    bundle_dir = REPO_ROOT / str(task["bundle_dir"])
    profile = str(task["profile"])
    old_flag = os.environ.get(TRACE_DIAGNOSTIC_FLAG)
    os.environ[TRACE_DIAGNOSTIC_FLAG] = "1"
    try:
        bundle = load_search_bundle(bundle_dir)
        prices = fc.prices_for_scenario(str(task["scenario_type"]))
        warm = make_shared_initial_solution(bundle, prices=prices)
        if profile == "LNS_TRACE":
            result = run_metaheuristic_baseline(
                "LNS",
                bundle_dir,
                seed=int(task["seed"]),
                eval_budget=int(task["eval_budget"]),
                max_runtime_seconds=float(task["runtime_cap_seconds"]),
                initial_solution=warm,
                prices=prices,
                common_flip_preprocess=True,
            )
            solution = result.best_solution
            best_cost = float(result.best_cost) if result.best_cost is not None else math.inf
            actual_evals = int(result.evals)
            violation_count = int(result.violation_count)
            history = list(result.history)
            trace = list(result.trace)
            operator_counts = dict(result.operator_counts)
            flags = {"baseline": "LNS", TRACE_DIAGNOSTIC_FLAG: "1"}
            status = result.status
            failure_reason = result.failure_reason
        else:
            flags = wo.e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=True)
            flags[TRACE_DIAGNOSTIC_FLAG] = "1"
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
                variant_id="A0_TRACE",
            )
            solution = result["best_solution"]
            best_cost = float(result["best_cost"])
            actual_evals = int(result["evaluations"])
            violation_count = int(result["violation_count"])
            history = list(result.get("history", []))
            operator_counts = dict(result.get("operator_counts", {}))
            trace = list(operator_counts.get("candidate_trace", []))
            status = "OK"
            failure_reason = ""
        violations = check_solution(solution, bundle.instance, prices) if solution is not None else ["missing_solution"]
        if violations:
            status = "HALT_INFEASIBLE"
            failure_reason = "; ".join(str(item) for item in violations[:3])
            violation_count = len(violations)
        elif actual_evals < int(task["eval_budget"]):
            status = "HALT_UNDER_EVAL"
            failure_reason = f"Stopped at {actual_evals}/{task['eval_budget']} evaluations."
        return {
            "schema": "setp-e2-lns-acceptance-scheduler-audit-row.v1",
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
            "violation_count": violation_count,
            "route_count": len(solution.routes) if solution is not None else 0,
            "history": history,
            "trace": trace,
            "operator_counts": operator_counts,
            "flags": flags,
            "head": fc.git_head(),
        }
    except Exception as exc:
        return worker_failure_row(task, "HALT_WORKER_EXCEPTION", repr(exc), started)
    finally:
        if old_flag is None:
            os.environ.pop(TRACE_DIAGNOSTIC_FLAG, None)
        else:
            os.environ[TRACE_DIAGNOSTIC_FLAG] = old_flag


def flatten_trace_rows(rows: list[dict[str, Any]], profile: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("profile") != profile:
            continue
        for idx, item in enumerate(row.get("trace", []) if isinstance(row.get("trace"), list) else []):
            trace = dict(item)
            trace.update(
                {
                    "run_id": row.get("run_id", ""),
                    "category": row.get("category", ""),
                    "instance": row.get("instance", ""),
                    "profile": row.get("profile", ""),
                    "seed": row.get("seed", ""),
                    "trace_index": idx,
                    "run_status": row.get("status", ""),
                }
            )
            out.append(trace)
    return sorted(out, key=lambda item: (str(item.get("category")), str(item.get("instance")), int(as_float(item.get("seed"))), int(as_float(item.get("trace_index")))))


def summarize_lns_path_contributions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row.get("trace_path", "UNKNOWN") or "UNKNOWN"), str(row.get("destroy", "")), str(row.get("repair", "")))
        groups.setdefault(key, []).append(row)
    out: list[dict[str, Any]] = []
    for (path, destroy, repair), items in sorted(groups.items()):
        out.append(
            {
                "trace_path": path,
                "destroy": destroy,
                "repair": repair,
                "attempts": len(items),
                "accepted_count": sum(1 for item in items if truthy(item.get("accepted"))),
                "accepted_worse_count": sum(1 for item in items if truthy(item.get("accepted_worse"))),
                "best_improved_count": sum(1 for item in items if truthy(item.get("best_improved"))),
                "fallback_used_count": sum(1 for item in items if truthy(item.get("fallback_used"))),
                "mean_delta_obj": mean_known(item.get("delta_obj") for item in items),
                "mean_route_count_delta": mean_known(item.get("route_count_delta") for item in items),
            }
        )
    return out


def summarize_alns_revert_reasons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row.get("profile", "A0_TRACE")),
            str(row.get("destroy_id", "UNKNOWN") or "UNKNOWN"),
            str(row.get("repair_id", "UNKNOWN") or "UNKNOWN"),
            str(row.get("revert_reason", "UNKNOWN") or "UNKNOWN"),
        )
        groups.setdefault(key, []).append(row)
    out: list[dict[str, Any]] = []
    for (profile, destroy, repair, reason), items in sorted(groups.items()):
        route_deltas = [item.get("candidate_route_count_delta") for item in items]
        local_flags = [item.get("local_search_improved") for item in items]
        out.append(
            {
                "profile": profile,
                "destroy_id": destroy,
                "repair_id": repair,
                "revert_reason": reason,
                "attempts": len(items),
                "accepted_count": sum(1 for item in items if truthy(item.get("accepted"))),
                "accepted_worse_count": sum(1 for item in items if truthy(item.get("accepted_worse"))),
                "best_improved_count": sum(1 for item in items if truthy(item.get("best_improved"))),
                "hard_violation_count": sum(as_int(item.get("raw_hard_violation_count", item.get("hard_violation_count"))) for item in items),
                "route_count_drop_count": "UNKNOWN" if any_unknown(route_deltas) else sum(1 for value in route_deltas if as_float(value) < 0),
                "local_search_improve_count": "UNKNOWN" if any_unknown(local_flags) else sum(1 for value in local_flags if truthy(value)),
            }
        )
    return out


def write_diagnosis(
    rows: list[dict[str, Any]],
    expected_rows: int,
    lns_summary: list[dict[str, Any]],
    alns_summary: list[dict[str, Any]],
) -> str:
    ok = sum(1 for row in rows if row.get("status") == "OK")
    fail = len(rows) - ok
    lns_by_path = aggregate_counts(lns_summary, "trace_path", ("attempts", "best_improved_count"))
    alns_by_reason = aggregate_counts(alns_summary, "revert_reason", ("attempts", "best_improved_count"))
    lines = [
        "# LNS Scheduler/Acceptance Trace Audit Diagnosis",
        "",
        "Verdict scope: diagnostic only, not formal T3.",
        f"Rows: {len(rows)}/{expected_rows}; OK={ok}; fail={fail}.",
        "",
        "LNS path contribution summary is reported from explicit trace_path values: scan_initial, vehicle_type_mutation, strong_bridge, fallback_relocate.",
        "ALNS candidate summary is reported from diagnostic candidate_trace; UNKNOWN means the trace did not record enough information and is not inferred.",
        "",
        "LNS best-improved counts by path:",
        *aggregate_lines(lns_by_path, "best_improved_count"),
        "",
        "ALNS attempts by revert reason:",
        *aggregate_lines(alns_by_reason, "attempts"),
        "",
    ]
    return "\n".join(lines)


def write_next_action(lns_summary: list[dict[str, Any]], alns_summary: list[dict[str, Any]]) -> str:
    path_best = {
        key: as_int(values.get("best_improved_count"))
        for key, values in aggregate_counts(lns_summary, "trace_path", ("best_improved_count",)).items()
    }
    total_best = sum(path_best.values())
    dominant = max(path_best, key=lambda key: path_best[key]) if path_best else "UNKNOWN"
    if total_best == 0:
        symptom = "trace has no best-improved LNS path"
        remedy = "increase diagnostic trace budget or inspect worker failures"
        evidence = "best_improved_count sums to 0"
    elif dominant == "scan_initial":
        symptom = "LNS advantage concentrates at scan_initial"
        remedy = "compare A0 scan_all_cv_solution / scan restart-rebuild against LNS _angle_scan_order"
        evidence = f"scan_initial best_improved_count={path_best[dominant]} of {total_best}"
    elif dominant == "vehicle_type_mutation":
        symptom = "LNS advantage concentrates at vehicle-type mutation"
        remedy = "audit EV/CV flip plus charging repair trace"
        evidence = f"vehicle_type_mutation best_improved_count={path_best[dominant]} of {total_best}"
    elif dominant in {"strong_bridge", "fallback_relocate"}:
        symptom = f"LNS advantage concentrates at {dominant}"
        remedy = "audit repair/acceptance/scheduler with this trace split; do not design new operators yet"
        evidence = f"{dominant} best_improved_count={path_best[dominant]} of {total_best}"
    else:
        symptom = "dominant LNS path is unresolved"
        remedy = "add narrower trace fields before algorithm changes"
        evidence = f"path counts={json.dumps(path_best, sort_keys=True)}"
    pass_gate = "a follow-up diagnostic identifies a single path/revert mechanism with enough rows and zero HALT rows"
    fail_gate = "UNKNOWN remains dominant or any protected/under-eval/worker-failure condition appears"
    return "\n".join(
        [
            "# Next Action",
            "",
            f"problem_symptom -> {symptom}",
            f"evidence -> {evidence}",
            f"minimal_remedy -> {remedy}",
            f"pass_gate -> {pass_gate}",
            f"fail_gate -> {fail_gate}",
            "",
            "Boundary: no oracle, ejection-chain, cross-exchange, LNS weakening, or RELAXED_ROUTE_COMPRESSION tuning is recommended from this diagnostic alone.",
        ]
    )


def build_decision(
    *,
    metadata: dict[str, Any],
    rows: list[dict[str, Any]],
    expected_rows: int,
    lns_summary: list[dict[str, Any]],
    alns_summary: list[dict[str, Any]],
) -> dict[str, Any]:
    fail_rows = [row for row in rows if row.get("status") != "OK"]
    lns_by_path = aggregate_counts(lns_summary, "trace_path", ("attempts", "best_improved_count"))
    alns_by_reason = aggregate_counts(alns_summary, "revert_reason", ("attempts",))
    return {
        "schema": "setp-e2-lns-acceptance-scheduler-audit-decision.v1",
        "verdict": "TRACE_AUDIT_COMPLETE" if not fail_rows and len(rows) == expected_rows else "HALT_TRACE_AUDIT_INCOMPLETE",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "head": metadata.get("head", ""),
        "expected_rows": int(expected_rows),
        "rows": len(rows),
        "ok_rows": len(rows) - len(fail_rows),
        "fail_rows": len(fail_rows),
        "halt": bool(fail_rows or len(rows) != expected_rows),
        "lns_trace_paths": {key: as_int(values.get("attempts")) for key, values in lns_by_path.items()},
        "lns_best_improved_by_path": {key: as_int(values.get("best_improved_count")) for key, values in lns_by_path.items()},
        "alns_revert_reasons": {key: as_int(values.get("attempts")) for key, values in alns_by_reason.items()},
        "protected_diff": protected_diff(),
    }


def halt_decision(metadata: dict[str, Any], protected: list[str], missing: list[str]) -> dict[str, Any]:
    return {
        "schema": "setp-e2-lns-acceptance-scheduler-audit-decision.v1",
        "verdict": "HALT_PREFLIGHT",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "head": metadata.get("head", ""),
        "protected_diff": protected,
        "missing": missing,
        "halt": True,
    }


def write_empty_outputs(output_dir: Path) -> None:
    fc.write_csv(output_dir / "lns_scheduler_trace.csv", [])
    fc.write_csv(output_dir / "alns_candidate_trace.csv", [])
    fc.write_csv(output_dir / "lns_path_contribution_summary.csv", [])
    fc.write_csv(output_dir / "alns_revert_reason_summary.csv", [])
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
        "schema": "setp-e2-lns-acceptance-scheduler-audit-row.v1",
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
            sort_keys=True,
        )
    )


def summary_lines(rows: list[dict[str, Any]], key: str, value: str) -> list[str]:
    selected = sorted(rows, key=lambda row: as_int(row.get(value)), reverse=True)[:6]
    if not selected:
        return ["- UNKNOWN"]
    return [f"- {row.get(key, 'UNKNOWN')}: {row.get(value, 'UNKNOWN')}" for row in selected]


def aggregate_counts(rows: list[dict[str, Any]], key_field: str, value_fields: tuple[str, ...]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        key = str(row.get(key_field, "UNKNOWN") or "UNKNOWN")
        bucket = out.setdefault(key, {field: 0 for field in value_fields})
        for field in value_fields:
            bucket[field] += as_int(row.get(field))
    return out


def aggregate_lines(groups: dict[str, dict[str, int]], value_field: str) -> list[str]:
    selected = sorted(groups.items(), key=lambda item: as_int(item[1].get(value_field)), reverse=True)
    if not selected:
        return ["- UNKNOWN"]
    return [f"- {key}: {values.get(value_field, 0)}" for key, values in selected]


def parse_seeds(text: str) -> list[int]:
    return [int(part.strip()) for part in str(text).split(",") if part.strip()]


def sanitize_run_id(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._=-" else "_" for ch in str(text))


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes"}


def any_unknown(values: list[Any]) -> bool:
    return any(str(value).upper() == "UNKNOWN" or value in (None, "") for value in values)


def mean_known(values: Any) -> float | str:
    numeric = [as_float(value) for value in values if math.isfinite(as_float(value))]
    return sum(numeric) / len(numeric) if numeric else "UNKNOWN"


def as_float(value: object) -> float:
    try:
        if value in (None, "", "UNKNOWN"):
            return math.nan
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def as_int(value: object) -> int:
    number = as_float(value)
    return int(number) if math.isfinite(number) else 0


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
