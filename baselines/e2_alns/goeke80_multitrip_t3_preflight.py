#!/usr/bin/env python3
"""09t Goeke-80 multi-trip E2/T3 preflight gate.

This is a diagnostic gate, not the formal T3 experiment.  It keeps the 09s
semantics fixed: Goeke Q=3650, Goeke B=80, physical vehicle caps, and reusable
physical vehicles represented as route trip ids such as CV1#T1.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.construction import build_initial_solution
from setp_solver.search.e2_alns_throughput import (
    ALGORITHMS,
    GOLD_NUMPY,
    GOLD_PYTHON,
    HARD_TIMEOUT_GRACE_SECONDS,
    _execute_task_subprocess,
    _task,
)
from setp_solver.solution import physical_vehicle_id


BENCHMARK_ROOT = Path("models/data_bundle/generated_instances/e2_benchmark")
OUTPUT_DIR = Path("baselines/e2_alns/goeke80_multitrip_t3_preflight_data")
REPORT_PATH = Path("baselines/e2_alns/goeke80_multitrip_t3_preflight.md")
VANILLA_MULTIDEPOT_SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
THREESHIFT_SIZES = (50, 75, 100, 150, 200)
REPLICATES = (1, 2, 3)
STAGE_A_REPLICATES = (1,)
STAGE_A_SEEDS = (1, 2, 3)
STAGE_B_SEEDS = (1, 2, 3)
STAGE_A_EVAL_BUDGET = 3_000
STAGE_B_EVAL_BUDGET = 16_000
SMOKE_EVAL_BUDGET = 64


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--report-path", default=str(REPORT_PATH))
    parser.add_argument("--phase0-only", action="store_true")
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--stage-a-only", action="store_true")
    parser.add_argument("--stage-b-only", action="store_true")
    parser.add_argument("--no-auto-stage-b", action="store_true")
    parser.add_argument("--summarize-existing-only", action="store_true")
    parser.add_argument("--summarize-stage", choices=("smoke", "stage_a", "stage_b"), default="stage_b")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--retry-timeouts", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--smoke-eval-budget", type=int, default=SMOKE_EVAL_BUDGET)
    parser.add_argument("--stage-a-eval-budget", type=int, default=STAGE_A_EVAL_BUDGET)
    parser.add_argument("--stage-b-eval-budget", type=int, default=STAGE_B_EVAL_BUDGET)
    parser.add_argument("--stage-a-seeds", default="1-3")
    parser.add_argument("--stage-b-seeds", default="1-3")
    parser.add_argument("--artifact-commit-hash", default="")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    output_dir = repo_root / args.output_dir
    report_path = repo_root / args.report_path
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    metadata = build_metadata(repo_root, args)
    phase0 = phase0_audit(repo_root)
    write_json(output_dir / "phase0_audit.json", phase0)

    smoke_result: dict[str, Any] | None = None
    stage_a_result: dict[str, Any] | None = None
    stage_b_result: dict[str, Any] | None = None
    conclusion: dict[str, Any]

    if not phase0["phase0_ok"] or args.phase0_only:
        conclusion = decide_final(phase0, smoke_result, stage_a_result, stage_b_result, elapsed=time.perf_counter() - started)
        finish(metadata, output_dir, report_path, phase0, smoke_result, stage_a_result, stage_b_result, conclusion, started)
        print(json.dumps(conclusion, ensure_ascii=False, indent=2))
        return 0 if not conclusion["verdict"].startswith("HALT") else 2

    if args.summarize_existing_only:
        smoke_result = load_stage_result(repo_root, output_dir, "smoke")
        stage_a_result = load_stage_result(repo_root, output_dir, "stage_a")
        if args.summarize_stage == "smoke":
            smoke_result = summarize_existing_stage(repo_root, output_dir, "smoke", smoke_instances(), [1], int(args.smoke_eval_budget))
        elif args.summarize_stage == "stage_a":
            stage_a_result = summarize_existing_stage(repo_root, output_dir, "stage_a", instance_rows(replicates=STAGE_A_REPLICATES), parse_seeds(args.stage_a_seeds), int(args.stage_a_eval_budget))
        else:
            stage_b_result = summarize_existing_stage(repo_root, output_dir, "stage_b", instance_rows(replicates=REPLICATES), parse_seeds(args.stage_b_seeds), int(args.stage_b_eval_budget))
        conclusion = decide_final(phase0, smoke_result, stage_a_result, stage_b_result, elapsed=time.perf_counter() - started)
        finish(metadata, output_dir, report_path, phase0, smoke_result, stage_a_result, stage_b_result, conclusion, started)
        print(json.dumps(conclusion, ensure_ascii=False, indent=2))
        return 0 if not conclusion["verdict"].startswith("HALT") else 2

    if args.smoke_only:
        smoke_result = run_named_stage(
            repo_root,
            output_dir,
            stage="smoke",
            instance_rows=smoke_instances(),
            seeds=[1],
            eval_budget=int(args.smoke_eval_budget),
            workers=max(1, int(args.workers)),
            resume=bool(args.resume),
            retry_timeouts=bool(args.retry_timeouts),
        )
        conclusion = decide_final(phase0, smoke_result, stage_a_result, stage_b_result, elapsed=time.perf_counter() - started)
        finish(metadata, output_dir, report_path, phase0, smoke_result, stage_a_result, stage_b_result, conclusion, started)
        print(json.dumps(conclusion, ensure_ascii=False, indent=2))
        return 0 if not conclusion["verdict"].startswith("HALT") else 2

    if not args.stage_b_only:
        stage_a_result = run_named_stage(
            repo_root,
            output_dir,
            stage="stage_a",
            instance_rows=instance_rows(replicates=STAGE_A_REPLICATES),
            seeds=parse_seeds(args.stage_a_seeds),
            eval_budget=int(args.stage_a_eval_budget),
            workers=max(1, int(args.workers)),
            resume=bool(args.resume),
            retry_timeouts=bool(args.retry_timeouts),
        )

    should_run_b = bool(args.stage_b_only)
    if stage_a_result is not None and not args.stage_a_only and not args.no_auto_stage_b:
        should_run_b = stage_a_result["stage_gate"] == "STAGE_PASS_TO_NEXT"
    if should_run_b:
        stage_b_result = run_named_stage(
            repo_root,
            output_dir,
            stage="stage_b",
            instance_rows=instance_rows(replicates=REPLICATES),
            seeds=parse_seeds(args.stage_b_seeds),
            eval_budget=int(args.stage_b_eval_budget),
            workers=max(1, int(args.workers)),
            resume=bool(args.resume),
            retry_timeouts=bool(args.retry_timeouts),
        )

    conclusion = decide_final(phase0, smoke_result, stage_a_result, stage_b_result, elapsed=time.perf_counter() - started)
    finish(metadata, output_dir, report_path, phase0, smoke_result, stage_a_result, stage_b_result, conclusion, started)
    print(json.dumps(conclusion, ensure_ascii=False, indent=2))
    return 0 if not conclusion["verdict"].startswith("HALT") else 2


def build_metadata(repo_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "script": "baselines/e2_alns/goeke80_multitrip_t3_preflight.py",
        "command": " ".join(sys.argv),
        "repo_root": str(repo_root),
        "head": git_output(repo_root, "rev-parse", "HEAD"),
        "artifact_commit_hash": args.artifact_commit_hash or "pending",
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "output_dir": str(args.output_dir),
        "report_path": str(args.report_path),
        "runtime_cap_policy": "10-25c=300s; 50c=600s; 75-200c=900s for Stage B retry collection",
    }


def phase0_audit(repo_root: Path) -> dict[str, Any]:
    tex = (repo_root / "docs/paper_submission_final/paper_main.tex").read_text(encoding="utf-8", errors="ignore")
    rescue = repo_root / "baselines/e2_alns/goeke80_multitrip_rescue_gate.md"
    rescue_text = rescue.read_text(encoding="utf-8", errors="ignore") if rescue.exists() else ""
    warm_rows = []
    warm_csv = repo_root / "baselines/e2_alns/goeke80_multitrip_rescue_gate_data/phase1_warm_start_gate.csv"
    if warm_csv.exists():
        warm_rows = list(csv.DictReader(warm_csv.open(newline="", encoding="utf-8")))
    warm_ok = len(warm_rows) == 69 and all(row.get("status") == "OK" and int(float(row.get("violation_count", 99))) == 0 for row in warm_rows)
    params_ok = (
        abs(float(DEFAULT_PRICES.Q_capacity) - 3650.0) <= 1e-9
        and abs(float(DEFAULT_PRICES.B_battery_kwh) - 80.0) <= 1e-9
        and abs(float(DEFAULT_PRICES.v_speed_ms) - 25.0) <= 1e-9
        and abs(float(DEFAULT_PRICES.carbon_price) - 0.05034) <= 1e-12
    )
    tex_ok = ("Q=3650" in tex or "Q=3\\,650" in tex) and ("B=80" in tex or "$B$ & 电池容量 & 80 & kWh" in tex)
    rescue_ok = "Verdict: `RESCUE_SMOKE_COMPLETE`" in rescue_text
    phase0_ok = params_ok and tex_ok and warm_ok and rescue_ok
    return {
        "phase0_ok": phase0_ok,
        "params_ok": params_ok,
        "tex_ok": tex_ok,
        "warm_start_09s_ok": warm_ok,
        "rescue_report_ok": rescue_ok,
        "Q_capacity": float(DEFAULT_PRICES.Q_capacity),
        "B_battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "v_speed_ms": float(DEFAULT_PRICES.v_speed_ms),
        "carbon_price": float(DEFAULT_PRICES.carbon_price),
        "warm_start_rows": len(warm_rows),
    }


def run_named_stage(
    repo_root: Path,
    output_dir: Path,
    *,
    stage: str,
    instance_rows: list[tuple[str, str, float, int, int]],
    seeds: list[int],
    eval_budget: int,
    workers: int,
    resume: bool,
    retry_timeouts: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    stage_dir = output_dir / stage
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
    (stage_dir / "convergence_throughput").mkdir(parents=True, exist_ok=True)

    tasks = build_tasks(repo_root, stage_dir, stage, instance_rows, seeds, eval_budget)
    raw_path = stage_dir / f"{stage}_raw_runs.csv"
    existing = load_existing_rows(raw_path) if resume else {}
    rows: list[dict[str, Any]] = []
    queue_rows: list[dict[str, Any]] = []
    missing_tasks: list[tuple[int, dict[str, Any]]] = []
    for idx, task in enumerate(tasks):
        key = task_key(task)
        prior = existing.get(key)
        should_retry = prior is not None and retry_timeouts and is_retryable_failure(prior)
        if prior is not None and not should_retry:
            rows.append(prior | {"queue_action": "SKIPPED_EXISTING"})
            queue_rows.append(queue_row(task, "SKIPPED_EXISTING", prior.get("status", "")))
        else:
            missing_tasks.append((idx, task))
            queue_rows.append(queue_row(task, "PENDING" if prior is None else "RETRY", prior.get("status", "") if prior else ""))

    if missing_tasks:
        if workers <= 1:
            for idx, task in missing_tasks:
                rows.append(run_one_task(repo_root, task, idx))
        else:
            with ProcessPoolExecutor(max_workers=int(workers)) as pool:
                futures = {pool.submit(run_one_task, repo_root, task, idx): idx for idx, task in missing_tasks}
                for future in as_completed(futures):
                    rows.append(future.result())

    rows = [enrich_row(repo_root, row) for row in rows]
    rows.sort(key=lambda row: (str(row.get("instance")), int(row.get("seed", 0)), str(row.get("algorithm"))))
    write_csv(raw_path, rows)
    write_csv(stage_dir / f"{stage}_task_queue.csv", queue_rows)
    pair_rows = pair_summary(rows)
    scale_rows = scale_summary(rows)
    write_csv(stage_dir / f"{stage}_paired_summary.csv", pair_rows)
    write_csv(stage_dir / f"{stage}_scale_summary.csv", scale_rows)
    verdict = stage_verdict(stage, rows, pair_rows, scale_rows, expected_count=len(tasks), elapsed=time.perf_counter() - started)
    write_json(stage_dir / f"{stage}_verdict.json", verdict)
    return {
        "stage": stage,
        "stage_gate": verdict["stage_gate"],
        "verdict": verdict["verdict"],
        "rows": len(rows),
        "expected_rows": len(tasks),
        "elapsed_seconds": verdict["elapsed_seconds"],
        "raw_path": str(raw_path.relative_to(repo_root)),
        "paired_path": str((stage_dir / f"{stage}_paired_summary.csv").relative_to(repo_root)),
        "scale_path": str((stage_dir / f"{stage}_scale_summary.csv").relative_to(repo_root)),
        "metrics": verdict,
    }


def build_tasks(
    repo_root: Path,
    stage_dir: Path,
    stage: str,
    instance_rows_: list[tuple[str, str, float, int, int]],
    seeds: list[int],
    eval_budget: int,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for category, instance, cap, size, replicate in instance_rows_:
        for seed in seeds:
            for algorithm in ALGORITHMS:
                task = _task(repo_root, stage_dir, category, instance, algorithm, seed, eval_budget, cap)
                task["stage"] = stage
                task["size"] = int(size)
                task["replicate"] = int(replicate)
                tasks.append(task)
    return tasks


def run_one_task(repo_root: Path, task: dict[str, Any], idx: int) -> dict[str, Any]:
    row = _execute_task_subprocess(
        repo_root,
        task,
        task_index=idx,
        timeout_seconds=float(task["runtime_cap_seconds"]) + HARD_TIMEOUT_GRACE_SECONDS,
    )
    return add_task_metadata(row, task)


def add_task_metadata(row: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    # The reused throughput worker intentionally reports only solver-level fields.
    # Keep the gate metadata here so resume, summaries, and checkpoint enrichment
    # stay keyed to the exact stage task that produced the row.
    row["stage"] = task["stage"]
    row["size"] = int(task["size"])
    row["replicate"] = int(task["replicate"])
    row["checkpoint_path"] = task["checkpoint_path"]
    return row


def summarize_existing_stage(
    repo_root: Path,
    output_dir: Path,
    stage: str,
    instance_rows_: list[tuple[str, str, float, int, int]],
    seeds: list[int],
    eval_budget: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    stage_dir = output_dir / stage
    tasks = build_tasks(repo_root, stage_dir, stage, instance_rows_, seeds, eval_budget)
    rows = collect_existing_task_rows(repo_root, stage_dir)
    rows = [enrich_row(repo_root, row) for row in rows]
    rows.sort(key=lambda row: (str(row.get("instance")), int(row.get("seed", 0)), str(row.get("algorithm"))))
    raw_path = stage_dir / f"{stage}_raw_runs.csv"
    write_csv(raw_path, rows)
    pair_rows = pair_summary(rows)
    scale_rows = scale_summary(rows)
    write_csv(stage_dir / f"{stage}_paired_summary.csv", pair_rows)
    write_csv(stage_dir / f"{stage}_scale_summary.csv", scale_rows)
    verdict = stage_verdict(stage, rows, pair_rows, scale_rows, expected_count=len(tasks), elapsed=time.perf_counter() - started)
    write_json(stage_dir / f"{stage}_verdict.json", verdict)
    return stage_result_from_verdict(repo_root, stage, stage_dir, raw_path, verdict, len(tasks), len(rows))


def collect_existing_task_rows(repo_root: Path, stage_dir: Path) -> list[dict[str, Any]]:
    task_root = stage_dir / ".throughput_tasks"
    rows: list[dict[str, Any]] = []
    if not task_root.exists():
        return rows
    for task_path in sorted(task_root.glob("task_*.json")):
        if task_path.name.endswith("_row.json"):
            continue
        suffix = task_path.stem.replace("task_", "")
        row_path = task_root / f"task_{suffix}_row.json"
        if not row_path.exists():
            continue
        try:
            task = json.loads(task_path.read_text(encoding="utf-8"))
            row = json.loads(row_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append(add_task_metadata(row, task))
    return rows


def load_stage_result(repo_root: Path, output_dir: Path, stage: str) -> dict[str, Any] | None:
    stage_dir = output_dir / stage
    verdict_path = stage_dir / f"{stage}_verdict.json"
    raw_path = stage_dir / f"{stage}_raw_runs.csv"
    if not verdict_path.exists():
        return None
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    expected = int(verdict.get("expected_rows", 0))
    rows = int(verdict.get("rows", 0))
    return stage_result_from_verdict(Path.cwd(), stage, stage_dir, raw_path, verdict, expected, rows)


def stage_result_from_verdict(
    repo_root: Path,
    stage: str,
    stage_dir: Path,
    raw_path: Path,
    verdict: dict[str, Any],
    expected_rows: int,
    rows: int,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "stage_gate": verdict["stage_gate"],
        "verdict": verdict["verdict"],
        "rows": rows,
        "expected_rows": expected_rows,
        "elapsed_seconds": verdict["elapsed_seconds"],
        "raw_path": str(raw_path.relative_to(repo_root)) if raw_path.is_absolute() else str(raw_path),
        "paired_path": str((stage_dir / f"{stage}_paired_summary.csv").relative_to(repo_root)) if stage_dir.is_absolute() else str(stage_dir / f"{stage}_paired_summary.csv"),
        "scale_path": str((stage_dir / f"{stage}_scale_summary.csv").relative_to(repo_root)) if stage_dir.is_absolute() else str(stage_dir / f"{stage}_scale_summary.csv"),
        "metrics": verdict,
    }


def enrich_row(repo_root: Path, row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    checkpoint_path = checkpoint_for_row(repo_root, out)
    out["checkpoint_path"] = str(checkpoint_path.relative_to(repo_root)) if checkpoint_path else ""
    solution = read_checkpoint_solution(checkpoint_path) if checkpoint_path else None
    if solution is None:
        out |= empty_composition()
        out["checkpoint_readable"] = False
        return out
    out |= composition_from_solution_dict(solution)
    out["checkpoint_readable"] = True
    return out


def checkpoint_for_row(repo_root: Path, row: dict[str, Any]) -> Path | None:
    explicit = str(row.get("checkpoint_path", "")).strip()
    if explicit:
        path = Path(explicit)
        return path if path.is_absolute() else repo_root / path
    stage = str(row.get("stage", "")).strip()
    instance = str(row.get("instance", "")).strip()
    algorithm = str(row.get("algorithm", "")).strip()
    seed = str(row.get("seed", "")).strip()
    if not stage or not instance or not algorithm or not seed:
        return None
    return repo_root / OUTPUT_DIR / stage / "checkpoints" / f"{instance}__{algorithm}__seed{seed}.json"


def read_checkpoint_solution(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("solution")
    except Exception:
        return None


def composition_from_solution_dict(solution: dict[str, Any]) -> dict[str, Any]:
    routes = list(solution.get("routes", []))
    route_count = len(routes)
    cv_routes = [route for route in routes if str(route.get("vehicle_type", "")).lower() == "cv"]
    ev_routes = [route for route in routes if str(route.get("vehicle_type", "")).lower() == "ev"]
    trip_counts = Counter(physical_vehicle_id(str(route.get("vehicle_id", ""))) for route in routes)
    cv_physical = {physical_vehicle_id(str(route.get("vehicle_id", ""))) for route in cv_routes}
    ev_physical = {physical_vehicle_id(str(route.get("vehicle_id", ""))) for route in ev_routes}
    return {
        "winner_ev_route_share": len(ev_routes) / route_count if route_count else 0.0,
        "winner_all_cv": route_count > 0 and len(ev_routes) == 0,
        "winner_all_ev": route_count > 0 and len(cv_routes) == 0,
        "cv_physical_vehicle_count": len(cv_physical),
        "ev_physical_vehicle_count": len(ev_physical),
        "max_trips_per_physical_vehicle": max(trip_counts.values()) if trip_counts else 0,
        "reused_physical_vehicle_count": sum(1 for value in trip_counts.values() if value > 1),
    }


def empty_composition() -> dict[str, Any]:
    return {
        "winner_ev_route_share": 0.0,
        "winner_all_cv": False,
        "winner_all_ev": False,
        "cv_physical_vehicle_count": 0,
        "ev_physical_vehicle_count": 0,
        "max_trips_per_physical_vehicle": 0,
        "reused_physical_vehicle_count": 0,
    }


def pair_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_pair: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_pair[(str(row.get("instance")), int(row.get("seed", 0)))][str(row.get("algorithm"))] = row
    out: list[dict[str, Any]] = []
    for (instance, seed), algs in sorted(by_pair.items()):
        if "alns_e2_throughput" not in algs or "LNS" not in algs:
            continue
        alns = algs["alns_e2_throughput"]
        lns = algs["LNS"]
        alns_cost = as_float(alns.get("best_cost"))
        lns_cost = as_float(lns.get("best_cost"))
        if math.isfinite(alns_cost) and math.isfinite(lns_cost) and lns_cost != 0.0:
            gap_pct = 100.0 * (alns_cost - lns_cost) / lns_cost
        else:
            gap_pct = math.inf
        winner = "tie"
        if math.isfinite(gap_pct) and abs(alns_cost - lns_cost) > 1e-9:
            winner = "alns" if alns_cost < lns_cost else "lns"
        winner_row = alns if winner == "alns" else lns if winner == "lns" else alns
        out.append(
            {
                "category": alns.get("category") or lns.get("category"),
                "instance": instance,
                "size": int(float(alns.get("size", lns.get("size", 0)) or 0)),
                "replicate": int(float(alns.get("replicate", lns.get("replicate", 0)) or 0)),
                "seed": seed,
                "alns_cost": alns_cost,
                "lns_cost": lns_cost,
                "gap_pct_alns_minus_lns": gap_pct,
                "paired_winner": winner,
                "winner_algorithm_for_composition": winner_row.get("algorithm"),
                "winner_ev_route_share": as_float(winner_row.get("winner_ev_route_share")),
                "winner_all_cv": boolish(winner_row.get("winner_all_cv")),
                "winner_all_ev": boolish(winner_row.get("winner_all_ev")),
                "winner_cv_physical": int(float(winner_row.get("cv_physical_vehicle_count", 0) or 0)),
                "winner_ev_physical": int(float(winner_row.get("ev_physical_vehicle_count", 0) or 0)),
                "winner_max_trips_per_vehicle": int(float(winner_row.get("max_trips_per_physical_vehicle", 0) or 0)),
            }
        )
    return out


def scale_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs = pair_summary(rows)
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in pairs:
        groups[(str(row["category"]), int(row["size"]))].append(row)
    out: list[dict[str, Any]] = []
    for (category, size), items in sorted(groups.items()):
        gaps = [as_float(row["gap_pct_alns_minus_lns"]) for row in items if math.isfinite(as_float(row["gap_pct_alns_minus_lns"]))]
        ev_shares = [as_float(row["winner_ev_route_share"]) for row in items if math.isfinite(as_float(row["winner_ev_route_share"]))]
        winner_counts = Counter(str(row["paired_winner"]) for row in items)
        all_cv_count = sum(1 for row in items if boolish(row["winner_all_cv"]))
        out.append(
            {
                "category": category,
                "size": size,
                "pairs": len(items),
                "mean_gap_pct_alns_minus_lns": statistics.fmean(gaps) if gaps else math.inf,
                "best_gap_pct_alns_minus_lns": min(gaps) if gaps else math.inf,
                "mean_winner_ev_route_share": statistics.fmean(ev_shares) if ev_shares else 0.0,
                "all_cv_winner_count": all_cv_count,
                "all_cv_winner_share": all_cv_count / len(items) if items else 0.0,
                "paired_winner_counts": json.dumps(dict(winner_counts), sort_keys=True),
            }
        )
    return out


def stage_verdict(
    stage: str,
    rows: list[dict[str, Any]],
    pair_rows: list[dict[str, Any]],
    scale_rows: list[dict[str, Any]],
    *,
    expected_count: int,
    elapsed: float,
) -> dict[str, Any]:
    collection_failures = collection_failure_rows(rows, expected_count)
    paired_counts = Counter(str(row.get("paired_winner")) for row in pair_rows)
    lns_dominant_groups = [
        row
        for row in scale_rows
        if int(row.get("size", 0)) >= 75 and as_float(row.get("mean_gap_pct_alns_minus_lns")) > 0.5
    ]
    all_cv_rows_75_200 = [
        row for row in pair_rows if int(row.get("size", 0)) >= 75 and boolish(row.get("winner_all_cv"))
    ]
    pairs_75_200 = [row for row in pair_rows if int(row.get("size", 0)) >= 75]
    all_cv_share = len(all_cv_rows_75_200) / len(pairs_75_200) if pairs_75_200 else 0.0
    ev_shares_75_200 = [as_float(row.get("winner_ev_route_share")) for row in pairs_75_200]
    mean_ev_share_75_200 = statistics.fmean(ev_shares_75_200) if ev_shares_75_200 else 0.0
    wilcoxon_lns_better = wilcoxon_lns_better_from_pairs(pair_rows)
    wins_ties = int(paired_counts.get("alns", 0)) + int(paired_counts.get("tie", 0))
    pairs = len(pair_rows)
    cost_competitive = pairs > 0 and wins_ties >= math.ceil(pairs / 2) and not wilcoxon_lns_better and len(lns_dominant_groups) == 0

    if collection_failures:
        verdict = "HALT_COLLECTION_COST"
        stage_gate = "STAGE_HALT"
    elif stage == "smoke":
        verdict = "SMOKE_OK"
        stage_gate = "STAGE_SMOKE_OK"
    elif len(lns_dominant_groups) >= 2 or wilcoxon_lns_better:
        verdict = "HALT_LNS_DOMINANT"
        stage_gate = "STAGE_HALT"
    elif all_cv_share > 0.5:
        verdict = "HALT_ALL_CV_DEGENERATION"
        stage_gate = "STAGE_HALT"
    elif stage == "stage_b" and cost_competitive and mean_ev_share_75_200 < 0.10:
        verdict = "COMPETITIVE_BUT_STORY_WEAK"
        stage_gate = "STAGE_FINAL"
    elif stage == "stage_b" and cost_competitive:
        verdict = "PROMOTE_TO_FORMAL_T3_PREP"
        stage_gate = "STAGE_FINAL"
    elif stage == "stage_a":
        verdict = "STAGE_A_PASS"
        stage_gate = "STAGE_PASS_TO_NEXT"
    else:
        verdict = "HALT_LNS_DOMINANT"
        stage_gate = "STAGE_HALT"

    return {
        "stage": stage,
        "verdict": verdict,
        "stage_gate": stage_gate,
        "elapsed_seconds": round(float(elapsed), 6),
        "rows": len(rows),
        "expected_rows": expected_count,
        "collection_failure_count": len(collection_failures),
        "paired_counts": dict(paired_counts),
        "paired_count": pairs,
        "wins_ties": wins_ties,
        "lns_dominant_group_count": len(lns_dominant_groups),
        "lns_dominant_groups": [f"{row['category']}:{row['size']}" for row in lns_dominant_groups],
        "wilcoxon_lns_better": bool(wilcoxon_lns_better),
        "all_cv_share_75_200": all_cv_share,
        "mean_ev_route_share_75_200": mean_ev_share_75_200,
        "collection_failures_sample": collection_failures[:10],
    }


def collection_failure_rows(rows: list[dict[str, Any]], expected_count: int) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if len(rows) != expected_count:
        failures.append({"reason": "missing_rows", "rows": len(rows), "expected": expected_count})
    for row in rows:
        if str(row.get("python")) != GOLD_PYTHON:
            failures.append({"reason": "python_mismatch", "instance": row.get("instance"), "algorithm": row.get("algorithm"), "seed": row.get("seed"), "python": row.get("python")})
        if str(row.get("numpy")) != GOLD_NUMPY:
            failures.append({"reason": "numpy_mismatch", "instance": row.get("instance"), "algorithm": row.get("algorithm"), "seed": row.get("seed"), "numpy": row.get("numpy")})
        if str(row.get("status")) != "OK" or str(row.get("gate_status")) != "OK":
            failures.append({"reason": "status_not_ok", "instance": row.get("instance"), "algorithm": row.get("algorithm"), "seed": row.get("seed"), "status": row.get("status")})
        if int(float(row.get("violation_count", 99))) != 0:
            failures.append({"reason": "nonzero_violation", "instance": row.get("instance"), "algorithm": row.get("algorithm"), "seed": row.get("seed"), "violation_count": row.get("violation_count")})
        if not boolish(row.get("checkpoint_readable")):
            failures.append({"reason": "checkpoint_unreadable", "instance": row.get("instance"), "algorithm": row.get("algorithm"), "seed": row.get("seed")})
    return failures


def decide_final(
    phase0: dict[str, Any],
    smoke: dict[str, Any] | None,
    stage_a: dict[str, Any] | None,
    stage_b: dict[str, Any] | None,
    *,
    elapsed: float,
) -> dict[str, Any]:
    if not phase0.get("phase0_ok"):
        verdict = "HALT_SEMANTIC_DRIFT"
    elif stage_b is not None:
        verdict = str(stage_b["verdict"])
    elif stage_a is not None:
        verdict = str(stage_a["verdict"])
    elif smoke is not None:
        verdict = str(smoke["verdict"])
    else:
        verdict = "PHASE0_OK"
    return {
        "verdict": verdict,
        "elapsed_seconds": round(float(elapsed), 6),
        "phase0_ok": bool(phase0.get("phase0_ok")),
        "smoke": smoke,
        "stage_a": stage_a,
        "stage_b": stage_b,
    }


def finish(
    metadata: dict[str, Any],
    output_dir: Path,
    report_path: Path,
    phase0: dict[str, Any],
    smoke: dict[str, Any] | None,
    stage_a: dict[str, Any] | None,
    stage_b: dict[str, Any] | None,
    conclusion: dict[str, Any],
    started: float,
) -> None:
    metadata["elapsed_seconds"] = round(time.perf_counter() - started, 6)
    metadata["verdict"] = conclusion["verdict"]
    write_json(output_dir / "metadata.json", metadata)
    write_json(output_dir / "conclusion.json", conclusion)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(metadata, phase0, smoke, stage_a, stage_b, conclusion), encoding="utf-8")


def render_report(
    metadata: dict[str, Any],
    phase0: dict[str, Any],
    smoke: dict[str, Any] | None,
    stage_a: dict[str, Any] | None,
    stage_b: dict[str, Any] | None,
    conclusion: dict[str, Any],
) -> str:
    lines = [
        "# 09t Goeke80 Multi-Trip T3 Preflight",
        "",
        f"Verdict: `{conclusion['verdict']}`",
        "",
        "## Plain Reading",
        "",
        plain_reading(conclusion),
        "",
        "## Phase 0",
        "",
        f"- Phase0 OK: `{phase0.get('phase0_ok')}`",
        f"- Q/B/v/carbon: `{phase0.get('Q_capacity')}` / `{phase0.get('B_battery_kwh')}` / `{phase0.get('v_speed_ms')}` / `{phase0.get('carbon_price')}`",
        f"- 09s warm start rows OK: `{phase0.get('warm_start_09s_ok')}` with `{phase0.get('warm_start_rows')}` rows",
        f"- 09s rescue report OK: `{phase0.get('rescue_report_ok')}`",
        "",
    ]
    for result in (smoke, stage_a, stage_b):
        if result is None:
            continue
        metrics = result.get("metrics", result)
        lines.extend(
            [
                f"## {str(result.get('stage', '')).replace('_', ' ').title()}",
                "",
                f"- Verdict: `{result.get('verdict')}`",
                f"- Stage gate: `{result.get('stage_gate', '')}`",
                f"- Rows: `{result.get('rows')}/{result.get('expected_rows')}`",
                f"- Paired counts: `{json.dumps(metrics.get('paired_counts', {}), sort_keys=True)}`",
                f"- LNS-dominant groups: `{json.dumps(metrics.get('lns_dominant_groups', []), ensure_ascii=False)}`",
                f"- Mean EV route share, 75-200 winners: `{float(metrics.get('mean_ev_route_share_75_200', 0.0)):.6f}`",
                f"- All-CV winner share, 75-200: `{float(metrics.get('all_cv_share_75_200', 0.0)):.6f}`",
                f"- Collection failures: `{metrics.get('collection_failure_count', 0)}`",
                f"- Failure sample: `{json.dumps(metrics.get('collection_failures_sample', []), ensure_ascii=False)}`",
                f"- Raw rows: `{result.get('raw_path')}`",
                f"- Paired summary: `{result.get('paired_path', '')}`",
                f"- Scale summary: `{result.get('scale_path', '')}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Artifacts",
            "",
            f"- Data dir: `{metadata.get('output_dir')}`",
            f"- Report: `{metadata.get('report_path')}`",
            f"- HEAD at run start: `{metadata.get('head')}`",
            f"- Artifact commit hash: `{metadata.get('artifact_commit_hash')}`",
            f"- Runtime cap policy: `{metadata.get('runtime_cap_policy')}`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def plain_reading(conclusion: dict[str, Any]) -> str:
    verdict = str(conclusion.get("verdict"))
    if verdict == "PROMOTE_TO_FORMAL_T3_PREP":
        return "大白话：预演门槛通过，可以规划正式 T3/F2；但正式表还必须加入 8 个文献基线，不能直接拿本预演当论文最终结果。"
    if verdict == "COMPETITIVE_BUT_STORY_WEAK":
        return "大白话：算法对比有继续价值，但 Goeke80 下 EV 使用很弱；它适合作为 Goeke baseline，不适合包装成现代稳定混合车队主故事。"
    if verdict == "HALT_LNS_DOMINANT":
        return "大白话：在当前正确语义下，LNS 仍系统性更强；不要进入正式 T3，先回查算法可靠性或接受 ALNS 不占优的事实。"
    if verdict == "HALT_ALL_CV_DEGENERATION":
        return "大白话：Goeke80 下结果系统性退回全燃油；这能做 baseline，但不能支撑稳定混合车队故事。"
    if verdict == "HALT_COLLECTION_COST":
        return "大白话：数据没有收完整或有 timeout/违约/环境漂移；不能下科学结论，先修采集问题。"
    if verdict == "HALT_SEMANTIC_DRIFT":
        return "大白话：参数、TeX 或 09s 多趟实体车语义和预期不一致；先修语义，不跑算法对比。"
    return "大白话：当前只完成了阶段性检查，还不能进入正式算法结论。"


def instance_rows(*, replicates: tuple[int, ...]) -> list[tuple[str, str, float, int, int]]:
    rows: list[tuple[str, str, float, int, int]] = []
    for category, sizes in (("vanilla", VANILLA_MULTIDEPOT_SIZES), ("multidepot", VANILLA_MULTIDEPOT_SIZES), ("threeshift", THREESHIFT_SIZES)):
        for size in sizes:
            for replicate in replicates:
                instance = f"e2-{category}-{size}c-{replicate:02d}"
                rows.append((category, instance, runtime_cap(size, category), int(size), int(replicate)))
    return rows


def smoke_instances() -> list[tuple[str, str, float, int, int]]:
    return [
        ("vanilla", "e2-vanilla-10c-01", 120.0, 10, 1),
        ("multidepot", "e2-multidepot-100c-01", 180.0, 100, 1),
        ("threeshift", "e2-threeshift-200c-01", 240.0, 200, 1),
    ]


def runtime_cap(size: int, category: str) -> float:
    if size <= 25:
        return 300.0
    if size <= 50:
        return 600.0
    return 900.0


def task_key(task_or_row: dict[str, Any]) -> tuple[str, str, int, str]:
    return (
        str(task_or_row.get("stage", "")),
        str(task_or_row.get("instance", "")),
        int(float(task_or_row.get("seed", 0))),
        str(task_or_row.get("algorithm", "")),
    )


def load_existing_rows(path: Path) -> dict[tuple[str, str, int, str], dict[str, Any]]:
    if not path.exists():
        return {}
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    return {task_key(row): row for row in rows}


def is_retryable_failure(row: dict[str, Any]) -> bool:
    status = str(row.get("status", ""))
    return status.startswith("HALT_HARD_TIMEOUT") or status in {
        "HALT_RUNTIME_UNDER_EVAL",
        "HALT_WORKER_ERROR",
        "TIMEOUT",
        "ERROR",
        "SUBPROCESS_NONZERO",
        "JSON_PARSE_ERROR",
    }


def queue_row(task: dict[str, Any], action: str, prior_status: str) -> dict[str, Any]:
    return {
        "stage": task["stage"],
        "category": task["category"],
        "instance": task["instance"],
        "size": task["size"],
        "replicate": task["replicate"],
        "seed": task["seed"],
        "algorithm": task["algorithm"],
        "eval_budget": task["eval_budget"],
        "runtime_cap_seconds": task["runtime_cap_seconds"],
        "queue_action": action,
        "prior_status": prior_status,
    }


def wilcoxon_lns_better_from_pairs(pair_rows: list[dict[str, Any]]) -> bool:
    diffs = [as_float(row.get("gap_pct_alns_minus_lns")) for row in pair_rows if math.isfinite(as_float(row.get("gap_pct_alns_minus_lns")))]
    if len(diffs) < 2 or all(abs(value) <= 1e-12 for value in diffs):
        return False
    try:
        from scipy.stats import wilcoxon

        return bool(wilcoxon(diffs, alternative="greater").pvalue < 0.05)
    except Exception:
        return False


def parse_seeds(value: str) -> list[int]:
    out: list[int] = []
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def as_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return math.inf


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row.keys() if not str(key).startswith("_")})
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not fields:
            return
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def git_output(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo_root, text=True, capture_output=True, check=False)
    return proc.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
