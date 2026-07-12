#!/usr/bin/env python3
"""Run the approved eight-run E2 16000-evaluation preflight.

This is a resumable evidence runner.  It executes the already frozen E2
closure in ``.codex/worktrees/e2-frozen-0124623e`` and never changes the
810-row 4000-evaluation table.  A two-evaluation wiring smoke test is kept in
a separate directory and must pass before the formal eight tasks are started.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from baselines.e2_alns import e2_final_10seed_runner as harness  # noqa: E402
from baselines.e2_alns import e2_final_closure as closure  # noqa: E402


FREEZE_COMMIT = harness.FREEZE_COMMIT
EXECUTION_ROOT = harness.DEFAULT_EXECUTION_ROOT
FORMAL_RAW = REPO_ROOT / "baselines/e2_alns/e2_final_10seed_20260711/formal/raw_runs.csv"
PRIMARY = harness.PRIMARY
LNS = "LNS"
TASKS = (
    ("L-main-threeshift-20c-01", 3, "old_4000_loss"),
    ("L-main-threeshift-50c-01", 5, "second_worst_4000_loss"),
    ("L-main-threeshift-150c-01", 3, "large_scale_4000_loss"),
    ("L-main-threeshift-200c-01", 4, "slowest_pair_and_strong_win_guard"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "baselines/e2_alns/e2_16000_preflight_20260712")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--smoke", action="store_true", help="run only the two-evaluation wiring smoke")
    parser.add_argument("--formal", action="store_true", help="run or resume the eight formal tasks")
    parser.add_argument("--verify", action="store_true", help="write the final gate decision from completed rows")
    return parser.parse_args()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_metadata(root: Path) -> None:
    for path in root.rglob("._*"):
        if path.is_file():
            path.unlink(missing_ok=True)


def task_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return str(row.get("instance")), str(row.get("algorithm")), int(float(row.get("seed", 0)))


def make_task(phase_dir: Path, instance: str, algorithm: str, seed: int, budget: int) -> dict[str, Any]:
    task_algorithm = "staged_hybrid_carbon_pair" if algorithm == PRIMARY else algorithm
    task = closure.make_task(
        phase="E2_16000_PREFLIGHT",
        phase_dir=phase_dir,
        category="threeshift",
        instance=instance,
        algorithm=task_algorithm,
        seed=seed,
        eval_budget=budget,
        runtime_cap_seconds=closure.runtime_cap_for_instance(instance),
        scenario_type="diagnostic_280_override",
    )
    # The active repository supplies the generated L-main bundles; only the
    # solver executable is taken from the validated frozen worktree.
    task["repo_root"] = str(REPO_ROOT)
    task["head"] = FREEZE_COMMIT
    task["logical_algorithm"] = algorithm
    task["checkpoint_path"] = str(phase_dir / "checkpoints" / f"{instance}__{algorithm}__seed{seed}.json")
    return task


def relabel(row: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    logical = str(task["logical_algorithm"])
    out["algorithm"] = logical
    out["display_algorithm"] = "staged ALNS-LNS hybrid" if logical == PRIMARY else logical
    out["phase"] = "E2_16000_PREFLIGHT"
    out["preflight_role"] = str(task.get("selection_role", ""))
    out["preflight_run_id"] = f"E2_16000_PREFLIGHT__{task['instance']}__{logical}__seed{task['seed']}"
    out["execution_commit"] = FREEZE_COMMIT
    return out


def task_from_spec(phase_dir: Path, instance: str, seed: int, role: str, algorithm: str, budget: int) -> dict[str, Any]:
    task = make_task(phase_dir, instance, algorithm, seed, budget)
    task["selection_role"] = role
    return task


def run_one(execution_root: Path, phase_dir: Path, task: dict[str, Any], index: int) -> dict[str, Any]:
    task_root = phase_dir / ".tasks"
    task_root.mkdir(parents=True, exist_ok=True)
    # Use the hardened formal harness worker: it validates the frozen commit,
    # isolates the subprocess, and performs the same checker/evaluation path.
    raw_row, _ablation = harness.execute_task(execution_root, task_root, task, index)
    return relabel(raw_row, task)


def run_tasks(output: Path, execution_root: Path, tasks: list[dict[str, Any]], workers: int) -> list[dict[str, Any]]:
    raw_path = output / "raw_runs.csv"
    # A failed row is a stop marker, not a completed task.  Keep it visible in
    # the CSV for diagnosis, but let the next invocation replace it after the
    # minimal fix instead of silently treating it as a finished key.
    existing = {task_key(row): row for row in read_rows(raw_path) if row.get("gate_status") == "OK"}
    todo = [task for task in tasks if task_key({"instance": task["instance"], "algorithm": task["logical_algorithm"], "seed": task["seed"]}) not in existing]
    if not todo:
        return sorted(existing.values(), key=lambda row: task_key(row))
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        futures = {pool.submit(run_one, execution_root, output, task, idx): task for idx, task in enumerate(todo)}
        for future in as_completed(futures):
            task = futures[future]
            row = future.result()
            existing[task_key(row)] = row
            write_rows(raw_path, sorted(existing.values(), key=lambda item: task_key(item)))
            if row.get("gate_status") != "OK":
                for pending in futures:
                    pending.cancel()
                raise RuntimeError(f"{row.get('gate_status')}: {row.get('failure_reason')}")
    return sorted(existing.values(), key=lambda row: task_key(row))


def save_solution_files(output: Path, rows: list[dict[str, Any]]) -> None:
    solution_dir = output / "solutions"
    solution_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        payload = str(row.get("solution_json", "") or "")
        if not payload:
            continue
        path = solution_dir / f"{row['instance']}__{row['algorithm']}__seed{row['seed']}.json"
        path.write_text(payload + ("\n" if not payload.endswith("\n") else ""), encoding="utf-8")


def smoke(args: argparse.Namespace) -> int:
    output = args.output_dir / "smoke"
    output.mkdir(parents=True, exist_ok=True)
    harness.validate_execution_root(EXECUTION_ROOT)
    task = task_from_spec(output, "L-main-threeshift-20c-01", 3, "wiring_smoke_2eval", PRIMARY, 2)
    row = run_one(EXECUTION_ROOT, output, task, 0)
    write_rows(output / "raw_runs.csv", [row])
    ok = row.get("gate_status") == "OK" and int(float(row.get("actual_evals", -1))) == 2 and int(float(row.get("violation_count", -1))) == 0
    decision = {
        "schema": "resetp.e2-16000-preflight-smoke.v1",
        "verdict": "E2_16000_PREFLIGHT_WIRING_READY" if ok else "HALT_E2_16000_PREFLIGHT_WIRING",
        "expected_rows": 1,
        "actual_evals": row.get("actual_evals"),
        "zero_violations": row.get("violation_count") == 0,
        "execution_commit": FREEZE_COMMIT,
        "harness_commit": harness.execution_head(REPO_ROOT),
    }
    write_json(output / "decision.json", decision)
    write_json(output / "metadata.json", {"budget": 2, "task": task, "created_at_epoch": time.time()})
    clean_metadata(output)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 2


def formal(args: argparse.Namespace) -> int:
    output = args.output_dir / "formal"
    output.mkdir(parents=True, exist_ok=True)
    smoke_decision = read_json(args.output_dir / "smoke/decision.json")
    if smoke_decision.get("verdict") != "E2_16000_PREFLIGHT_WIRING_READY":
        raise RuntimeError("HALT: run the successful two-evaluation smoke before formal preflight")
    harness.validate_execution_root(EXECUTION_ROOT)
    tasks = [task_from_spec(output, instance, seed, role, algorithm, 16000) for instance, seed, role in TASKS for algorithm in (PRIMARY, LNS)]
    rows = run_tasks(output, EXECUTION_ROOT, tasks, args.workers)
    save_solution_files(output, rows)
    write_json(output / "metadata.json", {
        "schema": "resetp.e2-16000-preflight.v1",
        "execution_commit": FREEZE_COMMIT,
        "harness_commit": harness.execution_head(REPO_ROOT),
        "eval_budget": 16000,
        "workers": args.workers,
        "task_count": len(tasks),
        "source_formal_raw": str(FORMAL_RAW),
        "source_formal_raw_sha256": sha256(FORMAL_RAW),
    })
    return verify(args)


def f(row: dict[str, Any], field: str) -> float:
    try:
        return float(row[field])
    except (KeyError, TypeError, ValueError):
        return float("nan")


def verify(args: argparse.Namespace) -> int:
    output = args.output_dir / "formal"
    rows = read_rows(output / "raw_runs.csv")
    expected_keys = {(instance, algorithm, seed) for instance, seed, _role in TASKS for algorithm in (PRIMARY, LNS)}
    observed_keys = {task_key(row) for row in rows}
    complete = [row for row in rows if row.get("gate_status") == "OK" and int(f(row, "actual_evals")) == 16000 and int(f(row, "violation_count")) == 0 and row.get("solution_json")]
    by_pair: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_pair.setdefault((str(row.get("instance")), int(f(row, "seed"))), {})[str(row.get("algorithm"))] = row
    pair_rows = []
    for (instance, seed), pair in sorted(by_pair.items()):
        if PRIMARY not in pair or LNS not in pair:
            continue
        hybrid, lns = pair[PRIMARY], pair[LNS]
        pair_rows.append({
            "instance": instance,
            "seed": seed,
            "hybrid_cost": f(hybrid, "best_cost"),
            "lns_cost": f(lns, "best_cost"),
            "hybrid_minus_lns_pct": (f(lns, "best_cost") - f(hybrid, "best_cost")) / f(lns, "best_cost") * 100.0,
            "hybrid_improves_4000": None,
        })
    formal_rows = read_rows(FORMAL_RAW)
    four = {(str(row.get("instance")), str(row.get("algorithm")), int(f(row, "seed"))): row for row in formal_rows}
    for row in pair_rows:
        old = four.get((row["instance"], PRIMARY, row["seed"]))
        if old is not None:
            row["hybrid_improves_4000"] = row["hybrid_cost"] < f(old, "best_cost") - 1e-9
    write_rows(output / "paired_comparisons.csv", pair_rows)
    write_rows(output / "task_manifest.csv", [
        {
            "instance": instance,
            "seed": seed,
            "selection_role": role,
            "algorithm": algorithm,
            "eval_budget": 16000,
            "scenario_type": "diagnostic_280_override",
            "execution_commit": FREEZE_COMMIT,
        }
        for instance, seed, role in TASKS
        for algorithm in (PRIMARY, LNS)
    ])
    old_loss_keys = [(instance, seed) for instance, seed, _role in TASKS if instance != "L-main-threeshift-200c-01"]
    old_loss_improved = sum(1 for instance, seed in old_loss_keys for row in pair_rows if row["instance"] == instance and row["seed"] == seed and row["hybrid_improves_4000"] is True)
    aggregate_hybrid = sum(row["hybrid_cost"] for row in pair_rows if row["hybrid_cost"] == row["hybrid_cost"])
    aggregate_lns = sum(row["lns_cost"] for row in pair_rows if row["lns_cost"] == row["lns_cost"])
    guard = [row for row in pair_rows if row["instance"] == "L-main-threeshift-200c-01" and row["seed"] == 4]
    gate = (
        observed_keys == expected_keys
        and len(rows) == 8
        and len(complete) == 8
        and aggregate_hybrid <= aggregate_lns + 1e-9
        and old_loss_improved >= 2
        and guard
        and guard[0]["hybrid_cost"] <= guard[0]["lns_cost"] + 1e-9
    )
    decision = {
        "schema": "resetp.e2-16000-preflight-decision.v1",
        "verdict": "E2_16000_PREFLIGHT_SUPPORTED" if gate else "E2_16000_PREFLIGHT_NOT_SUPPORTED",
        "expected_rows": 8,
        "observed_rows": len(rows),
        "unique_keys": len(observed_keys),
        "exact_key_contract": observed_keys == expected_keys,
        "complete_rows": len(complete),
        "zero_violation_rows": sum(1 for row in complete if int(f(row, "violation_count")) == 0),
        "eval_budget": 16000,
        "aggregate_hybrid_cost": aggregate_hybrid,
        "aggregate_lns_cost": aggregate_lns,
        "old_loss_hybrid_improved_count": old_loss_improved,
        "old_loss_required_count": 2,
        "two_hundred_c_strong_win_guard": guard[0] if guard else {},
        "execution_commit": FREEZE_COMMIT,
        "harness_commit": harness.execution_head(REPO_ROOT),
        "promotion_gate": [
            "8/8 exact 16000 evaluations, zero violations, solution JSON present",
            "aggregate hybrid no worse than LNS",
            "at least 2 of the 3 selected 4000-loss hybrid runs improve",
            "200c seed4 strong-win guard no worse than LNS",
        ],
    }
    write_json(output / "decision.json", decision)
    clean_metadata(args.output_dir)
    report_path = args.output_dir / "report.md"
    report_path.write_text(
        "# E2 16000评价代表预检\n\n"
        f"判决：`{decision['verdict']}`。8个任务必须全部完成16000次完整评价、零违规；本预检不改写E2的810行4000评价主表。\n",
        encoding="utf-8",
    )
    file_hashes = {}
    excluded_dirs = {".tasks", "checkpoints", "__pycache__", ".pytest_cache"}
    for path in sorted(args.output_dir.rglob("*")):
        if (
            path.is_file()
            and not path.name.startswith("._")
            and path.name != "artifact_hashes.json"
            and not any(part in excluded_dirs for part in path.parts)
        ):
            file_hashes[str(path.relative_to(args.output_dir))] = sha256(path)
    write_json(args.output_dir / "artifact_hashes.json", file_hashes)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate else 2


def main() -> int:
    args = parse_args()
    args.output_dir = args.output_dir.resolve()
    if not (args.smoke or args.formal or args.verify):
        args.smoke = True
    if args.smoke:
        return smoke(args)
    if args.formal:
        return formal(args)
    return verify(args)


if __name__ == "__main__":
    raise SystemExit(main())
