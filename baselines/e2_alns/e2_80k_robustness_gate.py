#!/usr/bin/env python3
"""Resumable 80 kWh mirror gate executed by the frozen E2 solver commit.

The orchestrator lives on the active reporting branch, but every search worker
is launched from the detached ``e2-submission-20260711`` worktree.  This keeps
the accepted 280 kWh algorithm identity frozen while evaluating the original
Goeke 80 kWh parameter contract.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "solver/src", REPO_ROOT / "models/src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from baselines.e2_alns import e2_final_closure as closure
from baselines.e2_alns.m1_e2_submission_runner import (
    expand_carbon_pair_rows,
    export_solutions,
    paired_comparisons,
    per_instance_summary,
)


FROZEN_COMMIT = "0124623e347cd2a6a5548e07e0af66e16d3b634b"
FROZEN_TAG = "e2-submission-20260711"
GOLD_PYTHON = "/opt/anaconda3/bin/python3.13"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "baselines/e2_alns/e2_80k_robustness_20260711"
DEFAULT_EXECUTION_ROOT = REPO_ROOT / ".codex/worktrees/e2-frozen-0124623e"
ACTIVE_INSTANCE_ROOT = REPO_ROOT / "models/data_bundle/generated_instances/L-main"
ACTIVE_INSTANCE_MANIFEST = ACTIVE_INSTANCE_ROOT / "resetp-l-main-main-benchmark.v3.json"
FORMAL_INSTANCES = tuple(f"L-main-threeshift-{size}c-01" for size in (15, 50, 100, 200))
TASK_ALGORITHMS = ("staged_hybrid_carbon_pair", "LNS")
EVIDENCE_ALGORITHMS = (
    "staged_hybrid_carbon_aware",
    "staged_hybrid_carbon_naive",
    "LNS",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("preflight", "formal"), required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--execution-root", default=str(DEFAULT_EXECUTION_ROOT))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--eval-budget", type=int, default=4000)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root).resolve()
    phase_dir = output_root / args.phase
    execution_root = Path(args.execution_root).resolve()
    phase_dir.mkdir(parents=True, exist_ok=True)

    identity = execution_identity(execution_root)
    closure.write_json(phase_dir / "execution_identity.json", identity)
    if identity["verdict"] != "FROZEN_E2_EXECUTION_IDENTITY_OK":
        decision = collection_decision([], [], args.phase, 0, 0, identity)
        closure.write_json(phase_dir / "collection_decision.json", decision)
        closure.write_json(phase_dir / "decision.json", decision)
        write_report(phase_dir, decision)
        closure.write_hashes(phase_dir)
        print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    instances = ("L-main-threeshift-50c-01",) if args.phase == "preflight" else FORMAL_INSTANCES
    seeds = [1] if args.phase == "preflight" else [1, 2, 3]
    eval_budget = min(200, int(args.eval_budget)) if args.phase == "preflight" else int(args.eval_budget)
    expected_tasks = len(instances) * len(seeds) * len(TASK_ALGORITHMS)
    expected_evidence_rows = len(instances) * len(seeds) * len(EVIDENCE_ALGORITHMS)
    metadata = {
        "schema": "setp-e2-80k-robustness-metadata.v1",
        "phase": args.phase,
        "scenario_type": "formal_goeke80",
        "battery_kwh": 80.0,
        "instances": list(instances),
        "seeds": seeds,
        "task_algorithms": list(TASK_ALGORITHMS),
        "evidence_algorithms": list(EVIDENCE_ALGORITHMS),
        "eval_budget": eval_budget,
        "expected_tasks": expected_tasks,
        "expected_evidence_rows": expected_evidence_rows,
        "workers": int(args.workers),
        "frozen_execution_commit": FROZEN_COMMIT,
        "frozen_execution_tag": FROZEN_TAG,
        "execution_root": str(execution_root),
        "instance_root": str(ACTIVE_INSTANCE_ROOT),
        "instance_manifest_sha256": sha256_file(ACTIVE_INSTANCE_MANIFEST),
        "orchestrator_commit": closure.git_head(),
        "shared_start": "make_shared_initial_solution(introduce_ev=True)",
        "lns_common_flip_preprocess": True,
        "legacy_carbon_search_operators": False,
        "task_ledger": "task_runs.csv",
        "evidence_table": "raw_runs.csv",
        "mechanism_exclusion": {
            "L-main-threeshift-15c-01": "STRUCTURAL_NO_EV_AVAILABLE; performance comparison only",
        },
    }
    closure.write_json(phase_dir / "metadata.json", metadata)
    tasks = build_tasks(phase_dir, execution_root, instances, seeds, eval_budget, args.phase)
    closure.write_csv(phase_dir / "task_manifest.csv", tasks)
    manifest_ok = len(tasks) == expected_tasks and len({task["run_id"] for task in tasks}) == expected_tasks
    manifest_decision = {
        "schema": "setp-e2-80k-task-manifest-decision.v1",
        "verdict": "E2_80K_TASK_MANIFEST_READY" if manifest_ok else "HALT_E2_80K_TASK_MANIFEST",
        "observed_tasks": len(tasks),
        "expected_tasks": expected_tasks,
        "unique_run_ids": len({task["run_id"] for task in tasks}),
        "expected_evidence_rows": expected_evidence_rows,
        "execution_commit": FROZEN_COMMIT,
    }
    closure.write_json(phase_dir / "task_manifest_decision.json", manifest_decision)
    if args.dry_run or not manifest_ok:
        closure.write_hashes(phase_dir)
        print(json.dumps(manifest_decision, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if manifest_ok else 2

    task_rows = run_tasks(
        phase_dir,
        execution_root,
        tasks,
        workers=max(1, int(args.workers)),
        force=bool(args.force),
    )
    evidence_rows = expand_carbon_pair_rows(task_rows)
    closure.write_csv(phase_dir / "raw_runs.csv", evidence_rows)
    export_solutions(phase_dir, evidence_rows)
    closure.write_csv(phase_dir / "paired_comparisons.csv", paired_comparisons(evidence_rows))
    closure.write_csv(phase_dir / "per_instance_summary.csv", per_instance_summary(evidence_rows))
    decision = collection_decision(
        task_rows,
        evidence_rows,
        args.phase,
        expected_tasks,
        expected_evidence_rows,
        identity,
    )
    closure.write_json(phase_dir / "collection_decision.json", decision)
    closure.write_json(phase_dir / "decision.json", decision)
    write_report(phase_dir, decision)
    closure.write_hashes(phase_dir)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["collection_ready"] else 2


def execution_identity(execution_root: Path) -> dict[str, Any]:
    problems: list[str] = []
    if not execution_root.is_dir():
        problems.append(f"missing execution root: {execution_root}")
        head = ""
        status = ""
    else:
        head = git_output(execution_root, "rev-parse", "HEAD")
        raw_status = git_output(execution_root, "status", "--porcelain")
        status_lines = [line for line in raw_status.splitlines() if not apple_double_status(line)]
        status = "\n".join(status_lines)
        if head != FROZEN_COMMIT:
            problems.append(f"execution HEAD {head} != frozen {FROZEN_COMMIT}")
        if status.strip():
            problems.append("frozen execution worktree is dirty")
        if not (execution_root / "baselines/e2_alns/e2_final_closure.py").is_file():
            problems.append("frozen closure worker missing")
        if not ACTIVE_INSTANCE_ROOT.is_dir():
            problems.append("active audited L-main instance root missing")
        if not ACTIVE_INSTANCE_MANIFEST.is_file():
            problems.append("active L-main v3 manifest missing")
    if not Path(GOLD_PYTHON).is_file():
        problems.append(f"gold Python missing: {GOLD_PYTHON}")
    return {
        "schema": "setp-e2-frozen-execution-identity.v1",
        "verdict": "FROZEN_E2_EXECUTION_IDENTITY_OK" if not problems else "HALT_FROZEN_E2_EXECUTION_IDENTITY",
        "execution_root": str(execution_root),
        "expected_commit": FROZEN_COMMIT,
        "observed_commit": head,
        "worktree_clean": not bool(status.strip()),
        "gold_python": GOLD_PYTHON,
        "instance_root": str(ACTIVE_INSTANCE_ROOT),
        "instance_manifest_sha256": sha256_file(ACTIVE_INSTANCE_MANIFEST),
        "problems": problems,
    }


def build_tasks(
    phase_dir: Path,
    execution_root: Path,
    instances: tuple[str, ...],
    seeds: list[int],
    eval_budget: int,
    phase: str,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    phase_name = "E2_80K_PREFLIGHT" if phase == "preflight" else "E2_80K_FORMAL"
    for instance in instances:
        for seed in seeds:
            for algorithm in TASK_ALGORITHMS:
                task = closure.make_task(
                    phase=phase_name,
                    phase_dir=phase_dir,
                    category="threeshift",
                    instance=instance,
                    algorithm=algorithm,
                    seed=seed,
                    eval_budget=eval_budget,
                    runtime_cap_seconds=closure.runtime_cap_for_instance(instance),
                    scenario_type="formal_goeke80",
                )
                task["repo_root"] = str(execution_root)
                task["bundle_dir"] = str(ACTIVE_INSTANCE_ROOT / instance)
                task["checkpoint_path"] = str(phase_dir / "checkpoints" / f"{task['run_id']}.json")
                task["head"] = FROZEN_COMMIT
                task["execution_commit"] = FROZEN_COMMIT
                task["orchestrator_commit"] = closure.git_head()
                tasks.append(task)
    return tasks


def run_tasks(
    phase_dir: Path,
    execution_root: Path,
    tasks: list[dict[str, Any]],
    *,
    workers: int,
    force: bool,
) -> list[dict[str, Any]]:
    manifest = {str(task["run_id"]): task for task in tasks}
    existing_rows = closure.read_csv(phase_dir / "task_runs.csv")
    existing = {str(row.get("run_id")): row for row in existing_rows if str(row.get("run_id")) in manifest}
    todo = [
        task
        for task in tasks
        if force or not task_row_complete(existing.get(str(task["run_id"])), task)
    ]
    write_task_state(phase_dir, tasks, existing, running=len(todo))
    if not todo:
        return closure.sorted_rows(list(existing.values()))

    task_root = phase_dir / ".tasks"
    logs = phase_dir / "logs"
    task_root.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {
            pool.submit(execute_task, execution_root, task_root, logs, task, idx): task
            for idx, task in enumerate(todo)
        }
        for future in concurrent.futures.as_completed(future_map):
            task = future_map[future]
            try:
                row = future.result()
            except Exception as exc:  # noqa: BLE001 - preserve collection evidence.
                row = failure_row(task, "HALT_ORCHESTRATOR_EXCEPTION", repr(exc))
            prior = existing.get(str(task["run_id"]))
            if prior and not task_row_complete(prior, task):
                append_jsonl(phase_dir / "failed_attempts.jsonl", prior)
            existing[str(task["run_id"])] = row
            closure.write_csv(phase_dir / "task_runs.csv", closure.sorted_rows(list(existing.values())))
            write_task_state(phase_dir, tasks, existing, running=sum(not item.done() for item in future_map))
    return closure.sorted_rows(list(existing.values()))


def execute_task(
    execution_root: Path,
    task_root: Path,
    logs: Path,
    task: dict[str, Any],
    idx: int,
) -> dict[str, Any]:
    run_id = str(task["run_id"])
    task_path = task_root / f"{run_id}__{idx}.json"
    row_path = task_root / f"{run_id}__{idx}_row.json"
    closure.write_json(task_path, task)
    command = [
        GOLD_PYTHON,
        str(execution_root / "baselines/e2_alns/e2_final_closure.py"),
        "--task-json",
        str(task_path),
        "--task-output-json",
        str(row_path),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = "solver/src:models/src:."
    env["PYTHONHASHSEED"] = "0"
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=execution_root,
            text=True,
            capture_output=True,
            timeout=float(task["runtime_cap_seconds"]) + 60.0,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        (logs / f"{run_id}.stderr.log").write_text(str(exc), encoding="utf-8")
        return failure_row(task, "HALT_WORKER_TIMEOUT", str(exc), time.perf_counter() - started)
    (logs / f"{run_id}.stdout.log").write_text(completed.stdout or "", encoding="utf-8")
    (logs / f"{run_id}.stderr.log").write_text(completed.stderr or "", encoding="utf-8")
    if completed.returncode != 0:
        return failure_row(
            task,
            "HALT_WORKER_ERROR",
            f"returncode={completed.returncode}; see logs/{run_id}.stderr.log",
            time.perf_counter() - started,
        )
    if not row_path.is_file():
        return failure_row(task, "HALT_WORKER_NO_ROW", "worker produced no row JSON", time.perf_counter() - started)
    row = closure.read_json(row_path)
    row["execution_commit_expected"] = FROZEN_COMMIT
    row["execution_commit_observed"] = str(row.get("head", ""))
    row["orchestrator_commit"] = closure.git_head()
    row["worker_stdout_sha256"] = sha256_text(completed.stdout or "")
    row["worker_stderr_sha256"] = sha256_text(completed.stderr or "")
    return row


def task_row_complete(row: dict[str, Any] | None, task: dict[str, Any]) -> bool:
    if not row:
        return False
    pair_payload_ok = True
    if str(task["algorithm"]) == "staged_hybrid_carbon_pair":
        try:
            pair_payload_ok = bool(json.loads(str(row.get("charging_ablation_json", "{}"))))
        except json.JSONDecodeError:
            pair_payload_ok = False
    return (
        str(row.get("run_id")) == str(task["run_id"])
        and str(row.get("gate_status")) == "OK"
        and int(closure.as_float(row.get("actual_evals"), -1)) == int(task["eval_budget"])
        and int(closure.as_float(row.get("violation_count"), -1)) == 0
        and bool(str(row.get("solution_json", "")))
        and str(row.get("head", "")) == FROZEN_COMMIT
        and pair_payload_ok
    )


def write_task_state(
    phase_dir: Path,
    tasks: list[dict[str, Any]],
    rows: dict[str, dict[str, Any]],
    *,
    running: int,
) -> None:
    completed = sum(task_row_complete(rows.get(str(task["run_id"])), task) for task in tasks)
    failures = [
        rows[str(task["run_id"])]
        for task in tasks
        if str(task["run_id"]) in rows and not task_row_complete(rows[str(task["run_id"])], task)
    ]
    payload = {
        "schema": "setp-e2-80k-task-state.v1",
        "expected_tasks": len(tasks),
        "completed_tasks": completed,
        "remaining_tasks": len(tasks) - completed,
        "running_or_queued_tasks": int(running),
        "failure_count": len(failures),
        "failure_sample": [
            {
                "run_id": row.get("run_id"),
                "gate_status": row.get("gate_status"),
                "failure_reason": row.get("failure_reason"),
            }
            for row in failures[:10]
        ],
        "complete": completed == len(tasks) and not failures,
        "updated_at_epoch": time.time(),
    }
    atomic_write_json(phase_dir / "task_state.json", payload)


def collection_decision(
    task_rows: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    phase: str,
    expected_tasks: int,
    expected_evidence_rows: int,
    identity: dict[str, Any],
) -> dict[str, Any]:
    task_ok = sum(
        str(row.get("gate_status")) == "OK"
        and int(closure.as_float(row.get("actual_evals"), -1)) == int(closure.as_float(row.get("eval_budget"), -2))
        and int(closure.as_float(row.get("violation_count"), -1)) == 0
        and str(row.get("head", "")) == FROZEN_COMMIT
        for row in task_rows
    )
    evidence_ok = sum(
        str(row.get("gate_status")) == "OK"
        and int(closure.as_float(row.get("actual_evals"), -1)) == int(closure.as_float(row.get("eval_budget"), -2))
        and int(closure.as_float(row.get("violation_count"), -1)) == 0
        and bool(str(row.get("solution_json", "")))
        for row in evidence_rows
    )
    ready = (
        identity.get("verdict") == "FROZEN_E2_EXECUTION_IDENTITY_OK"
        and len(task_rows) == expected_tasks
        and task_ok == expected_tasks
        and len(evidence_rows) == expected_evidence_rows
        and evidence_ok == expected_evidence_rows
    )
    verdict = (
        "E2_80K_PREFLIGHT_READY"
        if ready and phase == "preflight"
        else "E2_80K_COLLECTION_COMPLETE_PENDING_VERIFY"
        if ready
        else "HALT_E2_80K_COLLECTION"
    )
    return {
        "schema": "setp-e2-80k-collection-decision.v1",
        "verdict": verdict,
        "phase": phase,
        "collection_ready": ready,
        "expected_tasks": expected_tasks,
        "observed_tasks": len(task_rows),
        "ok_tasks": task_ok,
        "expected_evidence_rows": expected_evidence_rows,
        "observed_evidence_rows": len(evidence_rows),
        "ok_evidence_rows": evidence_ok,
        "frozen_execution_commit": FROZEN_COMMIT,
        "algorithm_performance_claim": False,
        "note": "Formal performance and mechanism decisions require the independent verifier.",
    }


def failure_row(task: dict[str, Any], status: str, reason: str, elapsed: float = 0.0) -> dict[str, Any]:
    return {
        "run_id": task["run_id"],
        "phase": task["phase"],
        "category": task["category"],
        "instance": task["instance"],
        "algorithm": task["algorithm"],
        "seed": task["seed"],
        "scenario_type": task["scenario_type"],
        "status": status,
        "gate_status": status,
        "failure_reason": reason,
        "eval_budget": task["eval_budget"],
        "actual_evals": 0,
        "violation_count": -1,
        "elapsed_seconds": elapsed,
        "solution_json": "",
        "head": FROZEN_COMMIT,
    }


def write_report(phase_dir: Path, decision: dict[str, Any]) -> None:
    lines = [
        "# E2 80 kWh mirror collection",
        "",
        f"Verdict: `{decision['verdict']}`",
        "",
        (
            f"Search tasks: {decision['ok_tasks']}/{decision['expected_tasks']} healthy; "
            f"expanded evidence rows: {decision['ok_evidence_rows']}/{decision['expected_evidence_rows']} healthy."
        ),
        "",
        f"All search workers were executed from frozen commit `{FROZEN_COMMIT}`.",
        "",
        "This collection report does not make a performance or mechanism claim. Run the independent verifier for the formal decision.",
    ]
    (phase_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def git_output(root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.STDOUT).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return f"ERROR:{exc}"


def apple_double_status(line: str) -> bool:
    """Ignore ExFAT AppleDouble sidecars without hiding real source changes."""

    path_text = line[3:].strip() if len(line) >= 4 else line.strip()
    return any(part.startswith("._") for part in Path(path_text).parts)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
