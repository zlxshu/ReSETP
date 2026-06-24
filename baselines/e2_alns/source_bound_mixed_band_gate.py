"""09l source-bound practical mixed-band gate.

This diagnostic does not change promoted model defaults or solver semantics.
It asks a narrower question than 09k: among battery capacities explicitly
present in literature or vehicle sources, excluding the known-too-small 80kWh
legacy anchor as a main candidate, is there any value whose winner fleet
composition stays in a practical 20%-80% EV/CV route band across the full E2
gradient and stability instances?
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterable

import battery_spectrum_transition as b9k
import numpy as np

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES, PriceParameters
from setp_solver.search.alns_wouda import SearchPolicy, run_alns_wouda
from setp_solver.search.bundle import SearchBundle, load_search_bundle
from setp_solver.search.feasible_repair import route_customers, route_distance
from setp_solver.search.winner_operators import e2_alns_throughput_flags
from setp_solver.solution import Solution


CARBON_PRICE = 0.05034
BENCHMARK_ROOT = Path("models/data_bundle/generated_instances/e2_benchmark")
DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/source_bound_mixed_band_gate_data")
DEFAULT_REPORT = Path("baselines/e2_alns/source_bound_mixed_band_gate.md")

LOWER_REFERENCE_VALUES = {80.0}
DIAGNOSTIC_ONLY_VALUES = {160.0}
SECONDARY_ONLY_VALUES = {82.6, 123.9}
SOURCE_BOUND_VALUES = {
    60.0,
    81.0,
    82.6,
    89.0,
    100.0,
    113.0,
    123.9,
    140.0,
    141.0,
    150.0,
    176.0,
    180.0,
    194.0,
    200.0,
    210.0,
    240.0,
    280.0,
    282.0,
    291.0,
}

VARIANT_ORDER = ("free_mixed", "cv_shell", "ev_shell")
TERMINAL_STATUSES = {
    "OK",
    "VIOLATION",
    "INIT_INFEASIBLE",
    "TIMEOUT",
    "ERROR",
    "JSON_PARSE_ERROR",
    "SUBPROCESS_NONZERO",
}
COLLECTION_FAILURE_STATUSES = {"TIMEOUT", "ERROR", "JSON_PARSE_ERROR", "SUBPROCESS_NONZERO"}

PRACTICAL_MIN = 0.20
PRACTICAL_MAX = 0.80
NEAR_MIN = 0.15
NEAR_MAX = 0.85


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT))
    parser.add_argument("--phase0-only", action="store_true")
    parser.add_argument("--screen-only", action="store_true")
    parser.add_argument("--full-gate", action="store_true")
    parser.add_argument("--confirm-gate", action="store_true", help="Run Stage C for Stage B pass/near-pass candidates.")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--retry-timeouts", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--battery-values", nargs="*", type=float, default=[], help="Override screen batteries; useful for smoke only.")
    parser.add_argument("--stage-b-battery-values", nargs="*", type=float, default=[])
    parser.add_argument("--stage-c-battery-values", nargs="*", type=float, default=[])
    parser.add_argument("--stage-a-seeds", nargs="*", type=int, default=[1])
    parser.add_argument("--stage-b-seeds", nargs="*", type=int, default=[1, 2, 3])
    parser.add_argument("--stage-c-seeds", nargs="*", type=int, default=[1, 2, 3, 4, 5])
    parser.add_argument("--stage-a-eval-budget", type=int, default=1000)
    parser.add_argument("--stage-b-eval-budget", type=int, default=3000)
    parser.add_argument("--stage-c-eval-budget", type=int, default=16000)
    parser.add_argument("--runtime-small", type=float, default=180.0)
    parser.add_argument("--runtime-medium", type=float, default=300.0)
    parser.add_argument("--runtime-large", type=float, default=900.0)
    parser.add_argument("--task-timeout-buffer", type=float, default=90.0)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--single-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--single-phase", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-category", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-instance", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-variant", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-seed", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--single-battery-kwh", type=float, default=0.0, help=argparse.SUPPRESS)
    parser.add_argument("--single-eval-budget", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--single-runtime-cap", type=float, default=0.0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    if args.single_run:
        return single_run_cli(repo_root, args)

    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = repo_root / args.report_path
    started = time.perf_counter()

    evidence_rows = b9k.evidence_matrix_rows()
    candidate_rows = candidate_rows_from_evidence(evidence_rows, args)
    screen_batteries = [float(row["battery_kwh"]) for row in candidate_rows if bool(row["screen_scan"])]
    metadata = build_metadata(repo_root, args, screen_batteries)

    b9k.write_csv(output_dir / "evidence_matrix.csv", evidence_rows)
    b9k.write_csv(output_dir / "candidate_sources.csv", candidate_rows)
    phase0 = b9k.phase0_override_audit(repo_root, sorted({*screen_batteries, 100.0, 280.0}))
    b9k.write_json(output_dir / "phase0_override_audit.json", phase0)

    stage_a_rows: list[dict[str, Any]] = []
    stage_a_winners: list[dict[str, Any]] = []
    stage_a_candidate_summary: list[dict[str, Any]] = []
    stage_a_by_scale: list[dict[str, Any]] = []
    stage_a_failures: list[dict[str, Any]] = []
    stage_b_rows: list[dict[str, Any]] = []
    stage_b_winners: list[dict[str, Any]] = []
    stage_b_candidate_summary: list[dict[str, Any]] = []
    stage_b_by_scale: list[dict[str, Any]] = []
    stage_b_failures: list[dict[str, Any]] = []
    stage_c_rows: list[dict[str, Any]] = []
    stage_c_winners: list[dict[str, Any]] = []
    stage_c_candidate_summary: list[dict[str, Any]] = []
    stage_c_by_scale: list[dict[str, Any]] = []
    stage_c_failures: list[dict[str, Any]] = []

    if phase0.get("status") == "OK" and not args.phase0_only:
        stage_a_instances = smoke_instances(repo_root) if args.smoke else stage_a_instance_keys(repo_root)
        stage_a_rows = run_task_grid(
            repo_root,
            output_dir,
            args,
            phase="stage_a",
            instances=stage_a_instances,
            batteries=screen_batteries,
            seeds=list(args.stage_a_seeds),
            eval_budget=int(args.stage_a_eval_budget),
        )
        b9k.write_csv(output_dir / "stage_a_raw_runs.csv", stage_a_rows)
        stage_a_winners = winner_rows_from_raw(stage_a_rows)
        b9k.write_csv(output_dir / "stage_a_winners.csv", stage_a_winners)
        stage_a_by_scale = by_scale_rows(stage_a_winners, candidate_rows, phase="stage_a")
        b9k.write_csv(output_dir / "stage_a_by_scale.csv", stage_a_by_scale)
        stage_a_candidate_summary = candidate_summary_rows(stage_a_winners, stage_a_by_scale, candidate_rows, phase="stage_a")
        b9k.write_csv(output_dir / "stage_a_candidate_summary.csv", stage_a_candidate_summary)
        stage_a_failures = failure_instance_rows(stage_a_winners, candidate_rows, phase="stage_a")
        b9k.write_csv(output_dir / "stage_a_failure_instances.csv", stage_a_failures)

    if (
        phase0.get("status") == "OK"
        and not args.phase0_only
        and not args.screen_only
        and args.full_gate
        and stage_a_rows
    ):
        stage_b_batteries = stage_b_values(args, stage_a_candidate_summary, candidate_rows)
        stage_b_rows = run_task_grid(
            repo_root,
            output_dir,
            args,
            phase="stage_b",
            instances=all_instance_keys(repo_root),
            batteries=stage_b_batteries,
            seeds=list(args.stage_b_seeds),
            eval_budget=int(args.stage_b_eval_budget),
        )
        b9k.write_csv(output_dir / "stage_b_raw_runs.csv", stage_b_rows)
        stage_b_winners = winner_rows_from_raw(stage_b_rows)
        b9k.write_csv(output_dir / "stage_b_winners.csv", stage_b_winners)
        stage_b_by_scale = by_scale_rows(stage_b_winners, candidate_rows, phase="stage_b")
        b9k.write_csv(output_dir / "stage_b_by_scale.csv", stage_b_by_scale)
        stage_b_candidate_summary = candidate_summary_rows(stage_b_winners, stage_b_by_scale, candidate_rows, phase="stage_b")
        b9k.write_csv(output_dir / "stage_b_candidate_summary.csv", stage_b_candidate_summary)
        stage_b_failures = failure_instance_rows(stage_b_winners, candidate_rows, phase="stage_b")
        b9k.write_csv(output_dir / "stage_b_failure_instances.csv", stage_b_failures)

    if (
        phase0.get("status") == "OK"
        and not args.phase0_only
        and args.confirm_gate
        and stage_b_candidate_summary
    ):
        stage_c_batteries = stage_c_values(args, stage_b_candidate_summary, candidate_rows)
        if stage_c_batteries:
            stage_c_rows = run_task_grid(
                repo_root,
                output_dir,
                args,
                phase="stage_c",
                instances=all_instance_keys(repo_root),
                batteries=stage_c_batteries,
                seeds=list(args.stage_c_seeds),
                eval_budget=int(args.stage_c_eval_budget),
            )
            b9k.write_csv(output_dir / "stage_c_raw_runs.csv", stage_c_rows)
            stage_c_winners = winner_rows_from_raw(stage_c_rows)
            b9k.write_csv(output_dir / "stage_c_winners.csv", stage_c_winners)
            stage_c_by_scale = by_scale_rows(stage_c_winners, candidate_rows, phase="stage_c")
            b9k.write_csv(output_dir / "stage_c_by_scale.csv", stage_c_by_scale)
            stage_c_candidate_summary = candidate_summary_rows(stage_c_winners, stage_c_by_scale, candidate_rows, phase="stage_c")
            b9k.write_csv(output_dir / "stage_c_candidate_summary.csv", stage_c_candidate_summary)
            stage_c_failures = failure_instance_rows(stage_c_winners, candidate_rows, phase="stage_c")
            b9k.write_csv(output_dir / "stage_c_failure_instances.csv", stage_c_failures)

    all_raw_rows = [*stage_a_rows, *stage_b_rows, *stage_c_rows]
    all_winner_rows = [*stage_a_winners, *stage_b_winners, *stage_c_winners]
    b9k.write_csv(output_dir / "raw_runs.csv", all_raw_rows)
    b9k.write_csv(output_dir / "winners.csv", all_winner_rows)
    conclusion = summarize_conclusion(
        metadata,
        phase0,
        stage_a_rows,
        stage_a_candidate_summary,
        stage_b_rows,
        stage_b_candidate_summary,
        stage_c_rows,
        stage_c_candidate_summary,
        args,
    )
    metadata["elapsed_seconds"] = time.perf_counter() - started
    b9k.write_json(output_dir / "metadata.json", metadata)
    b9k.write_json(output_dir / "conclusion.json", conclusion)
    report_path.write_text(
        render_report(
            metadata,
            candidate_rows,
            phase0,
            stage_a_candidate_summary,
            stage_a_by_scale,
            stage_a_failures,
            stage_b_candidate_summary,
            stage_b_by_scale,
            stage_b_failures,
            stage_c_candidate_summary,
            stage_c_by_scale,
            stage_c_failures,
            conclusion,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "schema_version": "setp-09l-source-bound-mixed-band-stdout.v1",
                "verdict": conclusion["verdict"],
                "report": args.report_path,
                "output_dir": args.output_dir,
                "stage_a_rows": len(stage_a_rows),
                "stage_b_rows": len(stage_b_rows),
                "stage_c_rows": len(stage_c_rows),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 2 if str(conclusion["verdict"]).startswith("HALT_") else 0


def candidate_rows_from_evidence(evidence_rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    requested = {round(float(value), 6) for value in args.battery_values}
    allowed_values = requested or SOURCE_BOUND_VALUES
    grouped: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for row in evidence_rows:
        value = round(float(row["battery_kwh"]), 6)
        if value not in allowed_values and value not in LOWER_REFERENCE_VALUES:
            continue
        tier = str(row["evidence_tier"])
        if tier == "future_heavy_class":
            continue
        grouped[value].append(row)

    rows: list[dict[str, Any]] = []
    for value in sorted(grouped):
        sources = grouped[value]
        tiers = sorted({str(row["evidence_tier"]) for row in sources})
        source_ids = sorted({str(row["source_id"]) for row in sources})
        source_types = sorted({str(row["source_type"]) for row in sources})
        is_reference = value in LOWER_REFERENCE_VALUES
        is_diagnostic = value in DIAGNOSTIC_ONLY_VALUES or all(tier == "diagnostic_threshold" for tier in tiers)
        is_secondary_only = value in SECONDARY_ONLY_VALUES or all(source_type == "secondary_web" for source_type in source_types)
        main_eligible = (value in SOURCE_BOUND_VALUES) and not is_reference and not is_diagnostic
        screen_scan = (value in requested) if requested else main_eligible
        rows.append(
            {
                "battery_kwh": float(value),
                "source_ids": ";".join(source_ids),
                "source_types": ";".join(source_types),
                "evidence_tiers": ";".join(tiers),
                "reference_only": bool(is_reference),
                "diagnostic_only": bool(is_diagnostic),
                "secondary_only": bool(is_secondary_only),
                "main_candidate_eligible": bool(main_eligible),
                "screen_scan": bool(screen_scan),
                "promotion_allowed_without_extra_source": bool(main_eligible and not is_secondary_only),
                "source_count": len(sources),
            }
        )
    if not any(bool(row["screen_scan"]) for row in rows):
        raise SystemExit("No source-bound battery candidates selected for Stage A.")
    return rows


def build_metadata(repo_root: Path, args: argparse.Namespace, screen_batteries: list[float]) -> dict[str, Any]:
    return {
        "schema_version": "setp-09l-source-bound-mixed-band.v1",
        "repo_root": str(repo_root),
        "commit_hash": b9k.git_output(repo_root, "rev-parse", "HEAD"),
        "git_status_short": b9k.git_output(repo_root, "status", "--short", "--untracked-files=all"),
        "python": sys.executable,
        "python_version": sys.version.replace("\n", " "),
        "numpy": np.__version__,
        "command": " ".join([sys.executable, *sys.argv]),
        "output_dir": str(args.output_dir),
        "report_path": str(args.report_path),
        "default_B_battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "v_speed_ms": float(DEFAULT_PRICES.v_speed_ms),
        "carbon_price": float(CARBON_PRICE),
        "screen_battery_values": screen_batteries,
        "practical_band": [PRACTICAL_MIN, PRACTICAL_MAX],
        "stage_a_seeds": list(args.stage_a_seeds),
        "stage_b_seeds": list(args.stage_b_seeds),
        "stage_c_seeds": list(args.stage_c_seeds),
        "stage_a_eval_budget": int(args.stage_a_eval_budget),
        "stage_b_eval_budget": int(args.stage_b_eval_budget),
        "stage_c_eval_budget": int(args.stage_c_eval_budget),
        "full_gate_requested": bool(args.full_gate),
        "confirm_gate_requested": bool(args.confirm_gate),
        "resume": bool(args.resume),
        "retry_timeouts": bool(args.retry_timeouts),
        "workers": int(args.workers),
        "diagnostic_artifact_commit": "PENDING_COMMIT",
    }


def run_task_grid(
    repo_root: Path,
    output_dir: Path,
    args: argparse.Namespace,
    *,
    phase: str,
    instances: list[str],
    batteries: list[float],
    seeds: list[int],
    eval_budget: int,
) -> list[dict[str, Any]]:
    tasks = build_tasks(
        phase,
        instances,
        batteries,
        seeds,
        eval_budget,
        runtime_caps=(float(args.runtime_small), float(args.runtime_medium), float(args.runtime_large)),
    )
    completed = load_completed_rows(output_dir, phase, retry_timeouts=bool(args.retry_timeouts)) if args.resume else {}
    rows: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for task in tasks:
        existing = completed.get(task_key(task))
        if existing is None:
            pending.append(task)
        else:
            rows.append(existing)
    b9k.write_csv(output_dir / f"{phase}_task_queue.csv", task_queue_rows(tasks, completed, pending))
    b9k.write_csv(output_dir / f"{phase}_raw_runs.partial.csv", b9k.sorted_rows(rows))
    flags = e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=False)
    workers = max(1, int(args.workers))
    if workers == 1:
        for task in pending:
            row = execute_task(repo_root, args, flags, task)
            rows.append(row)
            completed[task_key(row)] = row
            refresh_queue(output_dir, phase, tasks, completed, pending, rows)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(execute_task, repo_root, args, flags, task): task for task in pending}
            for future in as_completed(futures):
                row = future.result()
                rows.append(row)
                completed[task_key(row)] = row
                refresh_queue(output_dir, phase, tasks, completed, pending, rows)
    return b9k.sorted_rows(rows)


def refresh_queue(
    output_dir: Path,
    phase: str,
    tasks: list[dict[str, Any]],
    completed: dict[tuple[str, float, str, str, int, str, int], dict[str, Any]],
    pending: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> None:
    b9k.write_csv(output_dir / f"{phase}_raw_runs.partial.csv", b9k.sorted_rows(rows))
    b9k.write_csv(output_dir / f"{phase}_task_queue.csv", task_queue_rows(tasks, completed, [task for task in pending if task_key(task) not in completed]))


def build_tasks(
    phase: str,
    instances: list[str],
    batteries: list[float],
    seeds: list[int],
    eval_budget: int,
    *,
    runtime_caps: tuple[float, float, float],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for battery in batteries:
        for item in instances:
            category, instance = item.split("/", 1)
            cap = runtime_cap(instance, runtime_caps)
            for seed in seeds:
                for variant in VARIANT_ORDER:
                    tasks.append(
                        {
                            "phase": phase,
                            "battery_kwh": float(battery),
                            "category": category,
                            "instance": instance,
                            "seed": int(seed),
                            "variant": variant,
                            "eval_budget": int(eval_budget),
                            "runtime_cap_seconds": float(cap),
                        }
                    )
    return tasks


def execute_task(repo_root: Path, args: argparse.Namespace, flags: dict[str, str], task: dict[str, Any]) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--repo-root",
        str(repo_root),
        "--single-run",
        "--single-phase",
        str(task["phase"]),
        "--single-category",
        str(task["category"]),
        "--single-instance",
        str(task["instance"]),
        "--single-variant",
        str(task["variant"]),
        "--single-seed",
        str(task["seed"]),
        "--single-battery-kwh",
        str(task["battery_kwh"]),
        "--single-eval-budget",
        str(task["eval_budget"]),
        "--single-runtime-cap",
        str(task["runtime_cap_seconds"]),
    ]
    timeout = float(task["runtime_cap_seconds"]) + float(args.task_timeout_buffer)
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=repo_root, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return b9k.timeout_row(repo_root, task, timeout, time.perf_counter() - started, exc)
    stdout = completed.stdout.strip()
    try:
        payload = json.loads(stdout.splitlines()[-1]) if stdout else {}
    except Exception as exc:  # noqa: BLE001
        return b9k.subprocess_error_row(repo_root, task, "JSON_PARSE_ERROR", time.perf_counter() - started, completed.returncode, stdout, completed.stderr, repr(exc))
    if completed.returncode != 0 and payload.get("status") not in {"INIT_INFEASIBLE"}:
        return b9k.subprocess_error_row(repo_root, task, "SUBPROCESS_NONZERO", time.perf_counter() - started, completed.returncode, stdout, completed.stderr, "")
    payload.setdefault("subprocess_returncode", int(completed.returncode))
    payload.setdefault("subprocess_stdout_tail", b9k.tail_text(stdout))
    payload.setdefault("subprocess_stderr_tail", b9k.tail_text(completed.stderr))
    return payload


def single_run_cli(repo_root: Path, args: argparse.Namespace) -> int:
    row = run_one(
        repo_root,
        repo_root / BENCHMARK_ROOT / str(args.single_category) / str(args.single_instance),
        str(args.single_phase),
        str(args.single_category),
        str(args.single_instance),
        str(args.single_variant),
        int(args.single_seed),
        float(args.single_battery_kwh),
        int(args.single_eval_budget),
        float(args.single_runtime_cap),
        e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=False),
    )
    print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return 1 if row.get("status") in COLLECTION_FAILURE_STATUSES else 0


def run_one(
    repo_root: Path,
    bundle_dir: Path,
    phase: str,
    category: str,
    instance: str,
    variant: str,
    seed: int,
    battery_kwh: float,
    eval_budget: int,
    runtime_cap_seconds: float,
    flags: dict[str, str],
) -> dict[str, Any]:
    started = time.perf_counter()
    prices = replace(DEFAULT_PRICES, carbon_price=CARBON_PRICE, B_battery_kwh=float(battery_kwh))
    row = b9k.base_run_row(repo_root, phase, category, instance, variant, seed, battery_kwh, eval_budget, runtime_cap_seconds, flags)
    try:
        bundle = load_search_bundle(bundle_dir)
        warm = b9k.warm_for_variant(bundle, prices, variant)
        policy = policy_for_variant(variant)
        with b9k.temporary_env(flags):
            result = run_alns_wouda(
                bundle_dir,
                iterations=None,
                seed=seed,
                eval_budget=eval_budget,
                max_runtime_seconds=runtime_cap_seconds,
                policy=policy,
                initial_solution=warm,
                prices=prices,
            )
        solution = result.best_solution
        metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
        violations = check_solution(solution, bundle.instance, prices)
        cv_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv")
        ev_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev")
        row.update(b9k.metric_subset(metrics))
        row.update(solution_share_metrics(solution, bundle))
        row.update(
            {
                "status": "OK" if not violations else "VIOLATION",
                "elapsed_seconds": time.perf_counter() - started,
                "actual_evals": int(result.evaluations),
                "best_penalized_obj": float(result.best_obj),
                "solver_reported_feasible": bool(result.feasible),
                "violation_count": len(violations),
                "route_count": len(solution.routes),
                "cv_route_count": cv_count,
                "ev_route_count": ev_count,
                "composition": classify_practical_composition(cv_count, ev_count),
                "ev_route_share": safe_div(ev_count, len(solution.routes)),
                "cv_route_share": safe_div(cv_count, len(solution.routes)),
            }
        )
    except ValueError as exc:
        message = str(exc)
        status = "INIT_INFEASIBLE" if "warm start" in message.lower() or "unable to build" in message.lower() else "ERROR"
        row.update(
            {
                "status": status,
                "elapsed_seconds": time.perf_counter() - started,
                "actual_evals": 0,
                "violation_count": -1,
                "route_count": 0,
                "cv_route_count": 0,
                "ev_route_count": 0,
                "composition": "infeasible" if status == "INIT_INFEASIBLE" else "error",
                "total_cost": math.inf,
                "error_type": type(exc).__name__,
                "error": message,
            }
        )
    except Exception as exc:  # noqa: BLE001
        row.update(
            {
                "status": "ERROR",
                "elapsed_seconds": time.perf_counter() - started,
                "actual_evals": 0,
                "violation_count": -1,
                "route_count": 0,
                "cv_route_count": 0,
                "ev_route_count": 0,
                "composition": "error",
                "total_cost": math.inf,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
    return row


def policy_for_variant(variant: str) -> SearchPolicy:
    if variant == "cv_shell":
        return SearchPolicy(require_charging_signal=False, max_ev=0)
    if variant == "ev_shell":
        return SearchPolicy(require_charging_signal=False, max_cv=0)
    if variant == "free_mixed":
        return SearchPolicy(require_charging_signal=False)
    raise ValueError(f"unknown variant: {variant}")


def solution_share_metrics(solution: Solution, bundle: SearchBundle) -> dict[str, float]:
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    total_customers = 0
    ev_customers = 0
    total_demand = 0.0
    ev_demand = 0.0
    total_distance = 0.0
    ev_distance = 0.0
    for route in solution.routes:
        customers = route_customers(route, bundle.instance)
        demand = sum(float(node_lookup[customer_id].demand) for customer_id in customers if customer_id in node_lookup)
        distance = float(route_distance(route, bundle.instance))
        total_customers += len(customers)
        total_demand += demand
        total_distance += distance
        if route.vehicle_type.lower() == "ev":
            ev_customers += len(customers)
            ev_demand += demand
            ev_distance += distance
    return {
        "total_customer_count": float(total_customers),
        "ev_customer_count": float(ev_customers),
        "ev_customer_share": safe_div(ev_customers, total_customers),
        "total_demand": float(total_demand),
        "ev_demand": float(ev_demand),
        "ev_demand_share": safe_div(ev_demand, total_demand),
        "total_distance_m": float(total_distance),
        "ev_distance_m": float(ev_distance),
        "ev_distance_share": safe_div(ev_distance, total_distance),
    }


def winner_rows_from_raw(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, float, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["phase"]), round(float(row["battery_kwh"]), 6), str(row["category"]), str(row["instance"]), int(row["seed"]))].append(row)
    winners: list[dict[str, Any]] = []
    for key, candidates in sorted(grouped.items()):
        phase, battery, category, instance, seed = key
        feasible = [row for row in candidates if row.get("status") == "OK" and int(float(row.get("violation_count", 999))) == 0]
        if not feasible:
            winners.append(
                {
                    "phase": phase,
                    "battery_kwh": battery,
                    "category": category,
                    "instance": instance,
                    "seed": seed,
                    "winner_status": "NO_FEASIBLE_ROW",
                }
            )
            continue
        best = min(feasible, key=lambda row: float(row["total_cost"]))
        winner = {
            "phase": phase,
            "battery_kwh": battery,
            "category": category,
            "instance": instance,
            "seed": seed,
            "size": b9k.customer_count(instance),
            "winner_status": "OK",
            "winner_variant": best["variant"],
            "winner_total_cost": float(best["total_cost"]),
            "winner_composition": best["composition"],
            "winner_route_count": int(float(best["route_count"])),
            "winner_cv_route_count": int(float(best["cv_route_count"])),
            "winner_ev_route_count": int(float(best["ev_route_count"])),
            "winner_ev_route_share": float(best.get("ev_route_share", 0.0)),
            "winner_ev_customer_share": float(best.get("ev_customer_share", math.nan)),
            "winner_ev_demand_share": float(best.get("ev_demand_share", math.nan)),
            "winner_ev_distance_share": float(best.get("ev_distance_share", math.nan)),
            "winner_total_customer_count": float(best.get("total_customer_count", math.nan)),
            "winner_total_demand": float(best.get("total_demand", math.nan)),
            "winner_total_distance_m": float(best.get("total_distance_m", math.nan)),
        }
        for row in feasible:
            prefix = str(row["variant"])
            winner[f"{prefix}_cost"] = float(row["total_cost"])
            winner[f"{prefix}_composition"] = row["composition"]
            winner[f"{prefix}_ev_route_share"] = float(row.get("ev_route_share", 0.0))
            winner[f"{prefix}_ev_customer_share"] = float(row.get("ev_customer_share", math.nan))
            winner[f"{prefix}_ev_demand_share"] = float(row.get("ev_demand_share", math.nan))
            winner[f"{prefix}_ev_distance_share"] = float(row.get("ev_distance_share", math.nan))
        winners.append(winner)
    return winners


def by_scale_rows(winners: list[dict[str, Any]], candidate_rows: list[dict[str, Any]], *, phase: str) -> list[dict[str, Any]]:
    candidate_by_value = {float(row["battery_kwh"]): row for row in candidate_rows}
    grouped: dict[tuple[float, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in winners:
        grouped[(float(row["battery_kwh"]), str(row["category"]), int(float(row.get("size", b9k.customer_count(str(row["instance"]))))))].append(row)
    rows: list[dict[str, Any]] = []
    for (battery, category, size), items in sorted(grouped.items()):
        ok = [row for row in items if row.get("winner_status") == "OK"]
        candidate = candidate_by_value.get(battery, {})
        route_shares = [float(row["winner_ev_route_share"]) for row in ok]
        customer_shares = [float(row["winner_ev_customer_share"]) for row in ok]
        demand_shares = [float(row["winner_ev_demand_share"]) for row in ok]
        distance_shares = [float(row["winner_ev_distance_share"]) for row in ok]
        counts = composition_counts(ok)
        mean_route = mean(route_shares)
        rows.append(
            {
                "phase": phase,
                "battery_kwh": battery,
                "category": category,
                "size": size,
                "winner_count": len(ok),
                "expected_winner_rows": len(items),
                "missing_or_infeasible_winner_rows": len(items) - len(ok),
                "mean_ev_route_share": mean_route,
                "mean_ev_customer_share": mean(customer_shares),
                "mean_ev_demand_share": mean(demand_shares),
                "mean_ev_distance_share": mean(distance_shares),
                "route_share_in_practical_band": in_band(mean_route),
                "all_ev_count": counts.get("all_ev", 0),
                "ev_heavy_count": counts.get("ev_heavy_mixed", 0),
                "balanced_count": counts.get("balanced_mixed", 0),
                "cv_heavy_count": counts.get("cv_heavy_mixed", 0),
                "all_cv_count": counts.get("all_cv", 0),
                "main_candidate_eligible": bool(candidate.get("main_candidate_eligible", False)),
                "secondary_only": bool(candidate.get("secondary_only", False)),
                "source_ids": candidate.get("source_ids", ""),
            }
        )
    return rows


def candidate_summary_rows(
    winners: list[dict[str, Any]],
    by_scale: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    *,
    phase: str,
) -> list[dict[str, Any]]:
    candidate_by_value = {float(row["battery_kwh"]): row for row in candidate_rows}
    grouped: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for row in winners:
        grouped[float(row["battery_kwh"])].append(row)
    scale_grouped: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for row in by_scale:
        scale_grouped[float(row["battery_kwh"])].append(row)

    rows: list[dict[str, Any]] = []
    for battery in sorted(grouped):
        items = grouped[battery]
        ok = [row for row in items if row.get("winner_status") == "OK"]
        candidate = candidate_by_value.get(battery, {})
        counts = composition_counts(ok)
        route_shares = [float(row["winner_ev_route_share"]) for row in ok]
        customer_shares = [float(row["winner_ev_customer_share"]) for row in ok]
        demand_shares = [float(row["winner_ev_demand_share"]) for row in ok]
        distance_shares = [float(row["winner_ev_distance_share"]) for row in ok]
        instance_pass = instance_majority_pass_count(ok)
        scale_rows = scale_grouped.get(battery, [])
        scale_pass = sum(1 for row in scale_rows if bool_value(row.get("route_share_in_practical_band")))
        failure_count = len(scale_rows) - scale_pass
        total_instances = len({(str(row["category"]), str(row["instance"])) for row in items})
        expected_winners = len(items)
        status = candidate_stage_status(
            ok_count=len(ok),
            expected_winners=expected_winners,
            instance_pass=instance_pass,
            total_instances=total_instances,
            scale_pass=scale_pass,
            total_scales=len(scale_rows),
        )
        rows.append(
            {
                "phase": phase,
                "battery_kwh": battery,
                "candidate_stage_status": status,
                "winner_count": len(ok),
                "expected_winner_rows": expected_winners,
                "total_instances": total_instances,
                "instance_majority_pass_count": instance_pass,
                "instance_majority_fail_count": max(0, total_instances - instance_pass),
                "scale_bucket_pass_count": scale_pass,
                "scale_bucket_fail_count": max(0, failure_count),
                "scale_bucket_count": len(scale_rows),
                "mean_ev_route_share": mean(route_shares),
                "mean_ev_customer_share": mean(customer_shares),
                "mean_ev_demand_share": mean(demand_shares),
                "mean_ev_distance_share": mean(distance_shares),
                "min_ev_route_share": min(route_shares) if route_shares else math.nan,
                "max_ev_route_share": max(route_shares) if route_shares else math.nan,
                "all_ev_winner_count": counts.get("all_ev", 0),
                "ev_heavy_winner_count": counts.get("ev_heavy_mixed", 0),
                "balanced_winner_count": counts.get("balanced_mixed", 0),
                "cv_heavy_winner_count": counts.get("cv_heavy_mixed", 0),
                "all_cv_winner_count": counts.get("all_cv", 0),
                "main_candidate_eligible": bool(candidate.get("main_candidate_eligible", False)),
                "secondary_only": bool(candidate.get("secondary_only", False)),
                "promotion_allowed_without_extra_source": bool(candidate.get("promotion_allowed_without_extra_source", False)),
                "source_ids": candidate.get("source_ids", ""),
                "evidence_tiers": candidate.get("evidence_tiers", ""),
            }
        )
    return rows


def candidate_stage_status(
    *,
    ok_count: int,
    expected_winners: int,
    instance_pass: int,
    total_instances: int,
    scale_pass: int,
    total_scales: int,
) -> str:
    if ok_count < expected_winners:
        return "incomplete"
    if total_instances and instance_pass == total_instances and total_scales and scale_pass == total_scales:
        return "pass"
    if total_instances and instance_pass >= math.ceil(total_instances * 0.90) and total_scales and scale_pass >= math.ceil(total_scales * 0.90):
        return "near_pass"
    return "fail"


def failure_instance_rows(winners: list[dict[str, Any]], candidate_rows: list[dict[str, Any]], *, phase: str) -> list[dict[str, Any]]:
    candidate_by_value = {float(row["battery_kwh"]): row for row in candidate_rows}
    grouped: dict[tuple[float, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in winners:
        grouped[(float(row["battery_kwh"]), str(row["category"]), str(row["instance"]))].append(row)
    rows: list[dict[str, Any]] = []
    for (battery, category, instance), items in sorted(grouped.items()):
        ok = [row for row in items if row.get("winner_status") == "OK"]
        in_band_count = sum(1 for row in ok if in_band(float(row["winner_ev_route_share"])))
        required = math.floor(len(ok) / 2) + 1 if ok else 1
        mean_share = mean(float(row["winner_ev_route_share"]) for row in ok)
        pass_instance = bool(ok) and in_band_count >= required
        if pass_instance:
            continue
        candidate = candidate_by_value.get(battery, {})
        rows.append(
            {
                "phase": phase,
                "battery_kwh": battery,
                "category": category,
                "instance": instance,
                "size": b9k.customer_count(instance),
                "winner_count": len(ok),
                "in_band_count": in_band_count,
                "required_majority": required,
                "mean_ev_route_share": mean_share,
                "mean_ev_customer_share": mean(float(row["winner_ev_customer_share"]) for row in ok),
                "mean_ev_demand_share": mean(float(row["winner_ev_demand_share"]) for row in ok),
                "mean_ev_distance_share": mean(float(row["winner_ev_distance_share"]) for row in ok),
                "reason": "missing_or_infeasible" if not ok else "route_share_outside_practical_band",
                "main_candidate_eligible": bool(candidate.get("main_candidate_eligible", False)),
                "source_ids": candidate.get("source_ids", ""),
            }
        )
    return rows


def stage_b_values(args: argparse.Namespace, stage_a_summary: list[dict[str, Any]], candidate_rows: list[dict[str, Any]]) -> list[float]:
    if args.stage_b_battery_values:
        requested = {round(float(value), 6) for value in args.stage_b_battery_values}
        return [float(row["battery_kwh"]) for row in candidate_rows if round(float(row["battery_kwh"]), 6) in requested]
    values = [
        float(row["battery_kwh"])
        for row in stage_a_summary
        if bool(row.get("main_candidate_eligible")) and str(row.get("candidate_stage_status")) in {"pass", "near_pass"}
    ]
    return sorted(set(values))


def stage_c_values(args: argparse.Namespace, stage_b_summary: list[dict[str, Any]], candidate_rows: list[dict[str, Any]]) -> list[float]:
    if args.stage_c_battery_values:
        requested = {round(float(value), 6) for value in args.stage_c_battery_values}
        return [float(row["battery_kwh"]) for row in candidate_rows if round(float(row["battery_kwh"]), 6) in requested]
    return sorted(
        {
            float(row["battery_kwh"])
            for row in stage_b_summary
            if bool(row.get("main_candidate_eligible")) and str(row.get("candidate_stage_status")) in {"pass", "near_pass"}
        }
    )


def summarize_conclusion(
    metadata: dict[str, Any],
    phase0: dict[str, Any],
    stage_a_rows: list[dict[str, Any]],
    stage_a_summary: list[dict[str, Any]],
    stage_b_rows: list[dict[str, Any]],
    stage_b_summary: list[dict[str, Any]],
    stage_c_rows: list[dict[str, Any]],
    stage_c_summary: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    if phase0.get("status") != "OK":
        return {"verdict": "HALT_OVERRIDE_NOT_TRUSTWORTHY", "interpretation": "Battery override propagation failed; stop before drawing conclusions."}
    failures = [row for row in [*stage_a_rows, *stage_b_rows, *stage_c_rows] if row.get("status") in COLLECTION_FAILURE_STATUSES]
    if failures:
        return {"verdict": "HALT_COLLECTION_COST", "interpretation": "At least one required optimization task timed out or errored.", "failed_rows": len(failures)}
    if args.phase0_only:
        return {"verdict": "PHASE0_ONLY", "interpretation": "Only source matrix and override audit were run."}
    if not args.full_gate or args.screen_only:
        stage_a_survivors = [
            row
            for row in stage_a_summary
            if bool(row.get("main_candidate_eligible")) and str(row.get("candidate_stage_status")) in {"pass", "near_pass"}
        ]
        if stage_a_summary and not stage_a_survivors:
            return {
                "verdict": "BATTERY_ONLY_INSUFFICIENT",
                "interpretation": (
                    "Stage A source-bound screen found no pass or near-pass non-80kWh candidate across the full gradient "
                    "of -01 instances, so Stage B/C were not triggered. Treat this as a screen-gated insufficiency result, "
                    "not as a Stage C confirmation."
                ),
                "decision_stage": "stage_a",
                "stage_a_rows": len(stage_a_rows),
                "stage_b_rows": len(stage_b_rows),
                "stage_c_rows": len(stage_c_rows),
                "passing_candidates": [],
                "secondary_only_passing_candidates": [],
                "near_candidates": [],
                "stage_a_candidate_status": compact_status(stage_a_summary),
                "stage_b_candidate_status": compact_status(stage_b_summary),
                "stage_c_candidate_status": compact_status(stage_c_summary),
            }
        return {
            "verdict": "SOURCE_BOUND_NEAR_BAND_NEEDS_CONFIRMATION",
            "interpretation": (
                "Stage A found pass/near-pass candidates, but Stage B/Stage C were not collected. "
                "Do not promote any parameter until the full gate is run."
            ),
            "stage_a_candidate_status": compact_status(stage_a_summary),
            "stage_b_candidate_values": stage_b_values(args, stage_a_summary, []),
        }
    if not stage_b_rows and stage_b_values(args, stage_a_summary, []):
        return {"verdict": "HALT_COLLECTION_COST", "interpretation": "Stage B had triggered candidates but was not collected."}
    if args.confirm_gate:
        decision_rows = stage_c_summary
        decision_stage = "stage_c"
        if stage_c_values(args, stage_b_summary, []) and not stage_c_rows:
            return {"verdict": "HALT_COLLECTION_COST", "interpretation": "Stage C confirmation was triggered but not collected."}
    else:
        decision_rows = stage_b_summary
        decision_stage = "stage_b"

    pass_rows = [
        row
        for row in decision_rows
        if bool(row.get("main_candidate_eligible"))
        and str(row.get("candidate_stage_status")) == "pass"
        and bool(row.get("promotion_allowed_without_extra_source"))
    ]
    secondary_only_pass = [
        row
        for row in decision_rows
        if bool(row.get("main_candidate_eligible"))
        and str(row.get("candidate_stage_status")) == "pass"
        and bool(row.get("secondary_only"))
    ]
    near_rows = [
        row
        for row in decision_rows
        if bool(row.get("main_candidate_eligible")) and str(row.get("candidate_stage_status")) == "near_pass"
    ]
    if pass_rows and decision_stage == "stage_c":
        verdict = "SOURCE_BOUND_MIXED_BAND_FOUND"
        interpretation = "At least one non-80kWh source-backed candidate passed the full 69-instance, seeds1-5 practical mixed-band gate."
    elif pass_rows or secondary_only_pass or near_rows:
        verdict = "SOURCE_BOUND_NEAR_BAND_NEEDS_CONFIRMATION"
        interpretation = (
            "A source-backed candidate is pass/near-pass before final confirmation, or the only pass relies on secondary-source kWh. "
            "Do not promote a default parameter yet."
        )
    elif decision_rows:
        verdict = "BATTERY_ONLY_INSUFFICIENT"
        interpretation = "No source-backed non-80kWh battery candidate kept winner route share inside 20%-80% across the required gradient."
    else:
        verdict = "HALT_COLLECTION_COST"
        interpretation = "No decision-stage data were collected."
    return {
        "verdict": verdict,
        "interpretation": interpretation,
        "decision_stage": decision_stage,
        "stage_a_rows": len(stage_a_rows),
        "stage_b_rows": len(stage_b_rows),
        "stage_c_rows": len(stage_c_rows),
        "passing_candidates": [float(row["battery_kwh"]) for row in pass_rows],
        "secondary_only_passing_candidates": [float(row["battery_kwh"]) for row in secondary_only_pass],
        "near_candidates": [float(row["battery_kwh"]) for row in near_rows],
        "stage_a_candidate_status": compact_status(stage_a_summary),
        "stage_b_candidate_status": compact_status(stage_b_summary),
        "stage_c_candidate_status": compact_status(stage_c_summary),
    }


def render_report(
    metadata: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
    phase0: dict[str, Any],
    stage_a_summary: list[dict[str, Any]],
    stage_a_by_scale: list[dict[str, Any]],
    stage_a_failures: list[dict[str, Any]],
    stage_b_summary: list[dict[str, Any]],
    stage_b_by_scale: list[dict[str, Any]],
    stage_b_failures: list[dict[str, Any]],
    stage_c_summary: list[dict[str, Any]],
    stage_c_by_scale: list[dict[str, Any]],
    stage_c_failures: list[dict[str, Any]],
    conclusion: dict[str, Any],
) -> str:
    lines = [
        "# 09l Source-Bound Practical Mixed-Band Gate",
        "",
        f"Commit: `{metadata['commit_hash'][:8]}`.",
        f"Python: `{metadata['python']}`; NumPy: `{metadata['numpy']}`.",
        f"Frozen defaults: `B_battery_kwh={metadata['default_B_battery_kwh']}`, `v_speed_ms={metadata['v_speed_ms']}`, `carbon_price={metadata['carbon_price']}`.",
        "Battery values in this report are in-memory overrides only; `prices.py`, `cost.py`, `check.py`, `evaluation.py`, bundle data, and algorithm semantics are not changed.",
        f"Command: `{metadata['command']}`.",
        "",
        "## Verdict",
        "",
        f"`{conclusion['verdict']}`.",
        "",
        str(conclusion["interpretation"]),
        "",
        "Important reading rule: `80kWh` is treated only as a historical/literature reference. It is not eligible to rescue the main scenario, because earlier large-scale diagnosis showed that the 80kWh setting makes EVs too weak in the cross-city regime.",
        "",
        "## Candidate Sources",
        "",
        "| battery kWh | scan | eligible | reference | secondary-only | promotion without extra source | sources | tiers |",
        "|---:|---|---|---|---|---|---|---|",
    ]
    for row in candidate_rows:
        lines.append(
            f"| {float(row['battery_kwh']):.1f} | {row['screen_scan']} | {row['main_candidate_eligible']} | "
            f"{row['reference_only']} | {row['secondary_only']} | {row['promotion_allowed_without_extra_source']} | "
            f"{row['source_ids']} | {row['evidence_tiers']} |"
        )
    lines.extend(
        [
            "",
            "## Override Audit",
            "",
            f"Phase 0 status: `{phase0.get('status')}`. The runner uses explicit override warm starts and independently replays every winner through `evaluate/check(..., override)`.",
            "",
        ]
    )
    append_stage(lines, "Stage A Screen", stage_a_summary, stage_a_by_scale, stage_a_failures)
    append_stage(lines, "Stage B Full 69-Instance Gate", stage_b_summary, stage_b_by_scale, stage_b_failures)
    append_stage(lines, "Stage C Confirmation", stage_c_summary, stage_c_by_scale, stage_c_failures)
    lines.extend(
        [
            "## Output Files",
            "",
            f"- `{metadata['output_dir']}/metadata.json`",
            f"- `{metadata['output_dir']}/candidate_sources.csv`",
            f"- `{metadata['output_dir']}/phase0_override_audit.json`",
            f"- `{metadata['output_dir']}/stage_a_raw_runs.csv`",
            f"- `{metadata['output_dir']}/stage_a_winners.csv`",
            f"- `{metadata['output_dir']}/stage_a_candidate_summary.csv`",
            f"- `{metadata['output_dir']}/stage_a_by_scale.csv`",
            f"- `{metadata['output_dir']}/stage_a_failure_instances.csv`",
            f"- `{metadata['output_dir']}/stage_b_raw_runs.csv`",
            f"- `{metadata['output_dir']}/stage_b_winners.csv`",
            f"- `{metadata['output_dir']}/stage_b_candidate_summary.csv`",
            f"- `{metadata['output_dir']}/stage_b_by_scale.csv`",
            f"- `{metadata['output_dir']}/stage_b_failure_instances.csv`",
            f"- `{metadata['output_dir']}/stage_c_raw_runs.csv`",
            f"- `{metadata['output_dir']}/stage_c_winners.csv`",
            f"- `{metadata['output_dir']}/stage_c_candidate_summary.csv`",
            f"- `{metadata['output_dir']}/stage_c_by_scale.csv`",
            f"- `{metadata['output_dir']}/stage_c_failure_instances.csv`",
            f"- `{metadata['output_dir']}/raw_runs.csv`",
            f"- `{metadata['output_dir']}/winners.csv`",
            f"- `{metadata['output_dir']}/conclusion.json`",
            "",
            "## Decision Boundary",
            "",
            "If no non-80kWh source-backed candidate passes across all scales and stability instances, do not keep tuning battery capacity. The next honest route is an operational-constraint fork, such as charging-capacity limits, EV capital/fleet-count limits, public charger scarcity, or long-route eligibility constraints.",
            "",
        ]
    )
    return "\n".join(lines)


def append_stage(
    lines: list[str],
    title: str,
    summary: list[dict[str, Any]],
    by_scale: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> None:
    lines.extend([f"## {title}", ""])
    if not summary:
        lines.extend(["Not collected.", ""])
        return
    lines.extend(
        [
            "| battery | status | winners | instance pass/fail | scale pass/fail | mean route/customer/demand/distance EV share | composition counts | sources |",
            "|---:|---|---:|---|---|---|---|---|",
        ]
    )
    for row in summary:
        counts = (
            f"allEV={row['all_ev_winner_count']}, EVheavy={row['ev_heavy_winner_count']}, "
            f"balanced={row['balanced_winner_count']}, CVheavy={row['cv_heavy_winner_count']}, allCV={row['all_cv_winner_count']}"
        )
        shares = (
            f"{fmt(row['mean_ev_route_share'])}/{fmt(row['mean_ev_customer_share'])}/"
            f"{fmt(row['mean_ev_demand_share'])}/{fmt(row['mean_ev_distance_share'])}"
        )
        lines.append(
            f"| {float(row['battery_kwh']):.1f} | {row['candidate_stage_status']} | {row['winner_count']}/{row['expected_winner_rows']} | "
            f"{row['instance_majority_pass_count']}/{row['instance_majority_fail_count']} | "
            f"{row['scale_bucket_pass_count']}/{row['scale_bucket_fail_count']} | {shares} | {counts} | {row['source_ids']} |"
        )
    lines.append("")
    if by_scale:
        lines.extend(["By-scale detail is in the CSV. Rows outside the 20%-80% route-share band are shown below.", ""])
        bad_scale = [row for row in by_scale if not bool_value(row.get("route_share_in_practical_band"))]
        lines.extend(["| battery | family | size | route/customer/demand/distance EV share | source |", "|---:|---|---:|---|---|"])
        for row in bad_scale[:80]:
            shares = f"{fmt(row['mean_ev_route_share'])}/{fmt(row['mean_ev_customer_share'])}/{fmt(row['mean_ev_demand_share'])}/{fmt(row['mean_ev_distance_share'])}"
            lines.append(f"| {float(row['battery_kwh']):.1f} | {row['category']} | {row['size']} | {shares} | {row['source_ids']} |")
        if len(bad_scale) > 80:
            lines.append(f"| ... | ... | ... | {len(bad_scale) - 80} more rows in CSV | ... |")
        lines.append("")
    if failures:
        lines.extend(["Failure instances are also retained in CSV; this table shows the first 80.", ""])
        lines.extend(["| battery | family | instance | reason | mean route/customer/demand/distance EV share |", "|---:|---|---|---|---|"])
        for row in failures[:80]:
            shares = f"{fmt(row['mean_ev_route_share'])}/{fmt(row['mean_ev_customer_share'])}/{fmt(row['mean_ev_demand_share'])}/{fmt(row['mean_ev_distance_share'])}"
            lines.append(f"| {float(row['battery_kwh']):.1f} | {row['category']} | {row['instance']} | {row['reason']} | {shares} |")
        if len(failures) > 80:
            lines.append(f"| ... | ... | ... | {len(failures) - 80} more rows in CSV | ... |")
        lines.append("")


def all_instance_keys(repo_root: Path) -> list[str]:
    root = repo_root / BENCHMARK_ROOT
    keys = []
    for category in ("vanilla", "multidepot", "threeshift"):
        for path in sorted((root / category).iterdir()):
            if path.is_dir() and path.name.startswith("e2-"):
                keys.append(f"{category}/{path.name}")
    return sorted(keys, key=instance_sort_key)


def stage_a_instance_keys(repo_root: Path) -> list[str]:
    return [key for key in all_instance_keys(repo_root) if key.endswith("-01")]


def smoke_instances(repo_root: Path) -> list[str]:
    candidates = [
        "vanilla/e2-vanilla-25c-01",
        "multidepot/e2-multidepot-100c-01",
        "threeshift/e2-threeshift-200c-01",
    ]
    available = set(all_instance_keys(repo_root))
    return [key for key in candidates if key in available]


def instance_sort_key(key: str) -> tuple[int, int, int, str]:
    category, instance = key.split("/", 1)
    family_rank = {"vanilla": 0, "multidepot": 1, "threeshift": 2}.get(category, 9)
    size = b9k.customer_count(instance)
    suffix = int(instance.rsplit("-", 1)[-1]) if instance.rsplit("-", 1)[-1].isdigit() else 0
    return family_rank, size, suffix, instance


def runtime_cap(instance: str, caps: tuple[float, float, float]) -> float:
    small, medium, large = caps
    n = b9k.customer_count(instance)
    if n >= 150:
        return float(large)
    if n >= 100:
        return float(medium)
    return float(small)


def load_completed_rows(output_dir: Path, phase: str, *, retry_timeouts: bool) -> dict[tuple[str, float, str, str, int, str, int], dict[str, Any]]:
    completed: dict[tuple[str, float, str, str, int, str, int], dict[str, Any]] = {}
    for name in (f"{phase}_raw_runs.csv", f"{phase}_raw_runs.partial.csv"):
        path = output_dir / name
        if not path.exists() or path.stat().st_size == 0:
            continue
        for row in b9k.read_csv(path):
            status = str(row.get("status", ""))
            if status == "TIMEOUT" and retry_timeouts:
                continue
            if status in TERMINAL_STATUSES:
                completed[task_key(row)] = row
    return completed


def task_queue_rows(
    tasks: list[dict[str, Any]],
    completed: dict[tuple[str, float, str, str, int, str, int], dict[str, Any]],
    pending: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pending_keys = {task_key(row) for row in pending}
    rows = []
    for task in tasks:
        key = task_key(task)
        existing = completed.get(key)
        rows.append(
            {
                **task,
                "queue_status": "pending" if key in pending_keys else "terminal",
                "run_status": existing.get("status", "") if existing else "",
                "total_cost": existing.get("total_cost", "") if existing else "",
                "composition": existing.get("composition", "") if existing else "",
            }
        )
    return rows


def task_key(row: dict[str, Any]) -> tuple[str, float, str, str, int, str, int]:
    return (
        str(row["phase"]),
        round(float(row["battery_kwh"]), 6),
        str(row["category"]),
        str(row["instance"]),
        int(row["seed"]),
        str(row["variant"]),
        int(row["eval_budget"]),
    )


def classify_practical_composition(cv_count: int, ev_count: int) -> str:
    total = int(cv_count) + int(ev_count)
    if total == 0:
        return "empty"
    if ev_count == 0:
        return "all_cv"
    if cv_count == 0:
        return "all_ev"
    share = ev_count / total
    if share > PRACTICAL_MAX:
        return "ev_heavy_mixed"
    if share < PRACTICAL_MIN:
        return "cv_heavy_mixed"
    return "balanced_mixed"


def instance_majority_pass_count(rows: list[dict[str, Any]]) -> int:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["category"]), str(row["instance"]))].append(row)
    count = 0
    for items in grouped.values():
        in_band_count = sum(1 for row in items if in_band(float(row["winner_ev_route_share"])))
        if items and in_band_count >= math.floor(len(items) / 2) + 1:
            count += 1
    return count


def composition_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("winner_composition", ""))
        counts[key] = counts.get(key, 0) + 1
    return counts


def compact_status(rows: list[dict[str, Any]]) -> dict[str, str]:
    return {str(row["battery_kwh"]): str(row.get("candidate_stage_status", "")) for row in rows}


def in_band(value: float, *, lower: float = PRACTICAL_MIN, upper: float = PRACTICAL_MAX) -> bool:
    return math.isfinite(value) and lower <= value <= upper


def near_band(value: float) -> bool:
    return math.isfinite(value) and NEAR_MIN <= value <= NEAR_MAX


def safe_div(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if float(denominator) else 0.0


def mean(values: Iterable[float]) -> float:
    items = [float(value) for value in values if math.isfinite(float(value))]
    return sum(items) / len(items) if items else math.nan


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def fmt(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{number:.3f}" if math.isfinite(number) else ""


if __name__ == "__main__":
    raise SystemExit(main())
