#!/usr/bin/env python3
"""09u wall-clock and 100 kWh battery preflight.

This runner is diagnostic only.  It does not change the default paper
parameters or solver semantics.  Battery values are applied inside each worker
process by replacing DEFAULT_PRICES before importing the search modules.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any


BENCHMARK_ROOT = Path("models/data_bundle/generated_instances/e2_benchmark")
OUTPUT_DIR = Path("baselines/e2_alns/wallclock_battery_preflight_data")
REPORT_PATH = Path("baselines/e2_alns/wallclock_battery_preflight.md")
ALGORITHMS = ("alns_e2_throughput", "LNS")
VANILLA_MULTIDEPOT_SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
THREESHIFT_SIZES = (50, 75, 100, 150, 200)
GOLD_PYTHON = "/opt/anaconda3/bin/python3.13"
GOLD_NUMPY = "2.3.5"
HARD_TIMEOUT_GRACE_SECONDS = 15.0
WALLCLOCK_BACKSTOP_EVALS = 16_000
LOWERED_FIXED_EVALS = 8_000
HIGH_TENSION_SCENARIOS = ("wc80", "wc100", "wc150", "wc280")
HIGH_TENSION_BATTERY_LABELS = {
    "wc80": "80 (Goeke old anchor)",
    "wc100": "100 (boundary)",
    "wc150": "150 (source-supported vehicle class)",
    "wc280": "280 (modern truck)",
}

SCENARIOS: dict[str, dict[str, Any]] = {
    "wc80": {
        "battery_kwh": 80.0,
        "mode": "wallclock",
        "eval_budget": WALLCLOCK_BACKSTOP_EVALS,
        "label": "Goeke80 same wall-clock",
    },
    "wc100": {
        "battery_kwh": 100.0,
        "mode": "wallclock",
        "eval_budget": WALLCLOCK_BACKSTOP_EVALS,
        "label": "100kWh same wall-clock",
    },
    "wc150": {
        "battery_kwh": 150.0,
        "mode": "wallclock",
        "eval_budget": WALLCLOCK_BACKSTOP_EVALS,
        "label": "150kWh same wall-clock",
    },
    "wc280": {
        "battery_kwh": 280.0,
        "mode": "wallclock",
        "eval_budget": WALLCLOCK_BACKSTOP_EVALS,
        "label": "280kWh same wall-clock",
    },
    "budget8k80": {
        "battery_kwh": 80.0,
        "mode": "fixed_budget",
        "eval_budget": LOWERED_FIXED_EVALS,
        "label": "Goeke80 lowered fixed budget",
    },
    "budget8k100": {
        "battery_kwh": 100.0,
        "mode": "fixed_budget",
        "eval_budget": LOWERED_FIXED_EVALS,
        "label": "100kWh lowered fixed budget",
    },
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--report-path", default=str(REPORT_PATH))
    parser.add_argument("--worker-task-json", default="")
    parser.add_argument("--worker-output-json", default="")
    parser.add_argument("--phase0-only", action="store_true")
    parser.add_argument("--instances", choices=("smoke", "gradient01", "gradient01_75_200", "all"), default="smoke")
    parser.add_argument("--scenarios", default="wc80,wc100,budget8k80,budget8k100")
    parser.add_argument("--report-kind", choices=("preflight", "high_tension"), default="preflight")
    parser.add_argument("--seeds", default="1")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--cap-scale", type=float, default=1.0)
    parser.add_argument("--max-cap-seconds", type=float, default=0.0)
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--retry-failures", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--artifact-commit-hash", default="")
    args = parser.parse_args(argv)

    if args.worker_task_json:
        row = run_worker_task(Path(args.worker_task_json))
        Path(args.worker_output_json).write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        return 0

    repo_root = Path(args.repo_root).resolve()
    output_dir = repo_root / args.output_dir
    report_path = repo_root / args.report_path
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    metadata = build_metadata(repo_root, args)
    phase0 = phase0_audit(repo_root)
    write_json(output_dir / "phase0_audit.json", phase0)

    rows: list[dict[str, Any]] = []
    if phase0["phase0_ok"] and not args.phase0_only:
        tasks = build_tasks(
            repo_root=repo_root,
            output_dir=output_dir,
            instances=select_instances(args.instances),
            seeds=parse_seeds(args.seeds),
            scenarios=parse_scenarios(args.scenarios),
            cap_scale=float(args.cap_scale),
            max_cap_seconds=float(args.max_cap_seconds),
        )
        if args.summarize_only:
            rows = collect_existing_rows(output_dir)
        else:
            rows = run_tasks(repo_root, output_dir, tasks, workers=max(1, int(args.workers)), resume=bool(args.resume), retry_failures=bool(args.retry_failures))
        rows = enrich_rows(repo_root, rows)
        write_csv(output_dir / "raw_runs.csv", rows)
        pairs = pair_summary(rows)
        write_csv(output_dir / "paired_summary.csv", pairs)
        write_csv(output_dir / "scale_summary.csv", scale_summary(rows))
        write_csv(output_dir / "scenario_summary.csv", scenario_summary(rows))
        if args.report_kind == "high_tension":
            write_csv(output_dir / "mechanism_summary.csv", mechanism_summary(rows))
            write_csv(output_dir / "wilcoxon_summary.csv", wilcoxon_summary(pairs))

    conclusion = conclude(
        phase0,
        rows,
        expected_count=len(
            build_tasks(
                repo_root=repo_root,
                output_dir=output_dir,
                instances=select_instances(args.instances),
                seeds=parse_seeds(args.seeds),
                scenarios=parse_scenarios(args.scenarios),
                cap_scale=float(args.cap_scale),
                max_cap_seconds=float(args.max_cap_seconds),
            )
        )
        if phase0["phase0_ok"] and not args.phase0_only
        else 0,
        report_kind=args.report_kind,
        instances_mode=args.instances,
    )
    metadata["elapsed_seconds"] = round(time.perf_counter() - started, 6)
    metadata["verdict"] = conclusion["verdict"]
    write_json(output_dir / "metadata.json", metadata)
    write_json(output_dir / "conclusion.json", conclusion)
    if args.report_kind == "high_tension":
        write_json(output_dir / "stage_decision.json", conclusion)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(metadata, phase0, conclusion), encoding="utf-8")
    if args.report_kind == "high_tension":
        write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir, report_path))
    print(json.dumps(conclusion, ensure_ascii=False, indent=2))
    return 0 if not conclusion["verdict"].startswith("HALT") else 2


def build_metadata(repo_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "script": "baselines/e2_alns/wallclock_battery_preflight.py",
        "command": " ".join(sys.argv),
        "repo_root": str(repo_root),
        "head": git_output(repo_root, "rev-parse", "HEAD"),
        "artifact_commit_hash": args.artifact_commit_hash or "pending",
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "instances": args.instances,
        "scenarios": args.scenarios,
        "report_kind": args.report_kind,
        "seeds": args.seeds,
        "output_dir": str(args.output_dir),
        "report_path": str(args.report_path),
        "cap_scale": float(args.cap_scale),
        "max_cap_seconds": float(args.max_cap_seconds),
        "notes": [
            "Diagnostic only: no default parameter or model semantic change.",
            "Wall-clock lanes accept zero-violation incumbents even when eval backstop is not reached.",
            "Lowered-budget lanes require the fixed eval budget to close.",
            "Goeke80 is treated as a baseline scene, not a modern mixed-fleet story by itself.",
        ],
    }


def phase0_audit(repo_root: Path) -> dict[str, Any]:
    code = (
        "from setp_solver.prices import DEFAULT_PRICES; "
        "import json, numpy as np, sys; "
        "print(json.dumps({'python': sys.executable, 'numpy': np.__version__, "
        "'Q': DEFAULT_PRICES.Q_capacity, 'B': DEFAULT_PRICES.B_battery_kwh, "
        "'v': DEFAULT_PRICES.v_speed_ms, 'carbon': DEFAULT_PRICES.carbon_price}))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": "solver/src:models/src", "PYTHONHASHSEED": "0"},
    )
    payload: dict[str, Any] = {}
    if completed.returncode == 0:
        try:
            payload = json.loads(completed.stdout.strip())
        except json.JSONDecodeError:
            payload = {}
    defaults_ok = (
        payload.get("python") == GOLD_PYTHON
        and payload.get("numpy") == GOLD_NUMPY
        and abs(float(payload.get("Q", math.nan)) - 3650.0) <= 1e-9
        and abs(float(payload.get("B", math.nan)) - 80.0) <= 1e-9
        and abs(float(payload.get("v", math.nan)) - 25.0) <= 1e-9
        and abs(float(payload.get("carbon", math.nan)) - 0.05034) <= 1e-12
    )
    rescue = repo_root / "baselines/e2_alns/goeke80_multitrip_rescue_gate_data/phase1_warm_start_gate.csv"
    warm_rows = list(csv.DictReader(rescue.open(newline="", encoding="utf-8"))) if rescue.exists() else []
    warm_ok = len(warm_rows) == 69 and all(row.get("status") == "OK" and int(float(row.get("violation_count", 99))) == 0 for row in warm_rows)
    return {
        "phase0_ok": bool(defaults_ok and warm_ok),
        "defaults_ok": bool(defaults_ok),
        "warm_start_09s_ok": bool(warm_ok),
        "warm_start_rows": len(warm_rows),
        "default_probe": payload,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def select_instances(mode: str) -> list[tuple[str, str, int, int]]:
    if mode == "smoke":
        return [
            ("vanilla", "e2-vanilla-10c-01", 10, 1),
            ("multidepot", "e2-multidepot-100c-01", 100, 1),
            ("threeshift", "e2-threeshift-200c-01", 200, 1),
        ]
    replicates = (1,) if mode in {"gradient01", "gradient01_75_200"} else (1, 2, 3)
    rows: list[tuple[str, str, int, int]] = []
    for category, sizes in (("vanilla", VANILLA_MULTIDEPOT_SIZES), ("multidepot", VANILLA_MULTIDEPOT_SIZES), ("threeshift", THREESHIFT_SIZES)):
        for size in sizes:
            if mode == "gradient01_75_200" and size < 75:
                continue
            for replicate in replicates:
                rows.append((category, f"e2-{category}-{size}c-{replicate:02d}", int(size), int(replicate)))
    return rows


def parse_scenarios(value: str) -> list[str]:
    out = [part.strip() for part in str(value).split(",") if part.strip()]
    unknown = [name for name in out if name not in SCENARIOS]
    if unknown:
        raise ValueError(f"Unknown scenarios: {unknown}")
    return out


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


def runtime_cap(size: int) -> float:
    if size <= 25:
        return 300.0
    if size <= 50:
        return 600.0
    return 900.0


def scaled_runtime_cap(size: int, *, cap_scale: float, max_cap_seconds: float) -> float:
    cap = runtime_cap(size) * max(0.0, float(cap_scale))
    if float(max_cap_seconds) > 0:
        cap = min(cap, float(max_cap_seconds))
    return max(1.0, cap)


def build_tasks(
    *,
    repo_root: Path,
    output_dir: Path,
    instances: list[tuple[str, str, int, int]],
    seeds: list[int],
    scenarios: list[str],
    cap_scale: float,
    max_cap_seconds: float,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for scenario_name in scenarios:
        scenario = SCENARIOS[scenario_name]
        for category, instance, size, replicate in instances:
            for seed in seeds:
                for algorithm in ALGORITHMS:
                    tasks.append(
                        {
                            "repo_root": str(repo_root),
                            "output_dir": str(output_dir),
                            "scenario": scenario_name,
                            "scenario_label": scenario["label"],
                            "battery_kwh": float(scenario["battery_kwh"]),
                            "comparison_mode": scenario["mode"],
                            "category": category,
                            "instance": instance,
                            "size": int(size),
                            "replicate": int(replicate),
                            "seed": int(seed),
                            "algorithm": algorithm,
                            "bundle_dir": str(BENCHMARK_ROOT / category / instance),
                            "eval_budget": int(scenario["eval_budget"]),
                            "runtime_cap_seconds": scaled_runtime_cap(int(size), cap_scale=cap_scale, max_cap_seconds=max_cap_seconds),
                            "checkpoint_path": str(output_dir / "checkpoints" / scenario_name / f"{instance}__{algorithm}__seed{seed}.json"),
                            "commit_hash": git_output(repo_root, "rev-parse", "HEAD"),
                        }
                    )
    return tasks


def run_tasks(
    repo_root: Path,
    output_dir: Path,
    tasks: list[dict[str, Any]],
    *,
    workers: int,
    resume: bool,
    retry_failures: bool,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    task_root = output_dir / ".tasks"
    task_root.mkdir(parents=True, exist_ok=True)
    prior = load_existing_rows(output_dir / "raw_runs.csv") if resume else {}
    rows: list[dict[str, Any]] = []
    pending: list[tuple[int, dict[str, Any]]] = []
    queue_rows: list[dict[str, Any]] = []
    for idx, task in enumerate(tasks):
        key = task_key(task)
        row = prior.get(key)
        if row is not None and (not retry_failures or not is_retryable(row)):
            rows.append(row | {"queue_action": "SKIPPED_EXISTING"})
            queue_rows.append(queue_row(task, "SKIPPED_EXISTING", row.get("status", "")))
            continue
        pending.append((idx, task))
        queue_rows.append(queue_row(task, "PENDING" if row is None else "RETRY", row.get("status", "") if row else ""))
    write_csv(output_dir / "task_queue.csv", queue_rows)
    if workers <= 1:
        for idx, task in pending:
            rows.append(execute_task(repo_root, task_root, task, idx))
    else:
        with ProcessPoolExecutor(max_workers=int(workers)) as pool:
            futures = {pool.submit(execute_task, repo_root, task_root, task, idx): idx for idx, task in pending}
            for future in as_completed(futures):
                rows.append(future.result())
    rows.sort(key=lambda row: (str(row.get("scenario")), str(row.get("instance")), int(float(row.get("seed", 0))), str(row.get("algorithm"))))
    return rows


def execute_task(repo_root: Path, task_root: Path, task: dict[str, Any], idx: int) -> dict[str, Any]:
    task_path = task_root / f"task_{idx}.json"
    out_path = task_root / f"task_{idx}_row.json"
    task_path.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker-task-json",
        str(task_path),
        "--worker-output-json",
        str(out_path),
    ]
    env = {**os.environ, "PYTHONPATH": "solver/src:models/src", "PYTHONHASHSEED": "0"}
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=float(task["runtime_cap_seconds"]) + HARD_TIMEOUT_GRACE_SECONDS,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return timeout_row_from_checkpoint(repo_root, task, time.perf_counter() - started, exc.stdout, exc.stderr)
    if completed.returncode != 0:
        return failure_row(task, time.perf_counter() - started, "HALT_WORKER_ERROR", "Worker exited non-zero.", completed.stdout, completed.stderr)
    if not out_path.exists():
        return failure_row(task, time.perf_counter() - started, "HALT_WORKER_ERROR", "Worker produced no row JSON.", completed.stdout, completed.stderr)
    return json.loads(out_path.read_text(encoding="utf-8"))


def run_worker_task(task_path: Path) -> dict[str, Any]:
    task = json.loads(task_path.read_text(encoding="utf-8"))
    prices = apply_battery_override(float(task["battery_kwh"]))

    from setp_solver.check import check_solution
    from setp_solver.cost import evaluate
    from setp_solver.search.bundle import load_search_bundle
    from setp_solver.search.candidates import make_shared_initial_solution
    from setp_solver.search.e2_alns_throughput import _write_convergence_files
    from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline, solution_to_dict
    from setp_solver.search.winner_operators import WinnerKernelConfig, e2_alns_throughput_flags, run_e2_alns_throughput

    root = Path(task["repo_root"])
    bundle_dir = root / str(task["bundle_dir"])
    bundle = load_search_bundle(bundle_dir)
    checkpoint_path = Path(task["checkpoint_path"])
    os.environ["SETP_E2_ALNS_CHECKPOINT_PATH"] = str(checkpoint_path)
    started = time.perf_counter()
    try:
        warm = make_shared_initial_solution(bundle, prices=prices)
    except Exception as exc:
        return failure_row(task, time.perf_counter() - started, "HALT_WARM_START", str(exc), "", "")
    warm_cost = float(evaluate(warm, bundle.instance, bundle.carbon_profile, prices)["total_cost"])
    write_checkpoint(checkpoint_path, solution_to_dict(warm), warm_cost, 0, 0.0, "shared_warm_start")

    algorithm = str(task["algorithm"])
    flags: dict[str, str] = {}
    history: list[dict[str, Any]] = []
    timings: dict[str, Any] = {}
    try:
        if algorithm == "alns_e2_throughput":
            flags = e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=True)
            result = run_e2_alns_throughput(
                bundle_dir,
                config=WinnerKernelConfig(
                    seed=int(task["seed"]),
                    eval_budget=int(task["eval_budget"]),
                    max_runtime_seconds=float(task["runtime_cap_seconds"]),
                ),
                initial_solution=warm,
                route_cost_cache=True,
                repair_structure_cache=True,
                timing_ledger=True,
            )
            solution = result["best_solution"]
            best_cost = float(result["best_cost"])
            actual_evals = int(result["evaluations"])
            violation_count = int(result["violation_count"])
            elapsed = float(result["elapsed_seconds"])
            history = list(result.get("history", []))
            timings = dict(result.get("timings", {}))
        elif algorithm == "LNS":
            result = run_metaheuristic_baseline(
                "LNS",
                bundle_dir,
                seed=int(task["seed"]),
                eval_budget=int(task["eval_budget"]),
                max_runtime_seconds=float(task["runtime_cap_seconds"]),
                initial_solution=warm,
            )
            solution = result.best_solution
            best_cost = float(result.best_cost) if result.best_cost is not None else math.inf
            actual_evals = int(result.evals)
            violation_count = int(result.violation_count)
            elapsed = float(result.elapsed_seconds)
            history = list(result.history)
        else:
            raise ValueError(f"unknown algorithm: {algorithm}")
    except Exception as exc:
        return failure_row(task, time.perf_counter() - started, "HALT_WORKER_EXCEPTION", repr(exc), "", "")

    elapsed = max(elapsed, time.perf_counter() - started)
    violations = check_solution(solution, bundle.instance, prices) if solution is not None else []
    if solution is not None and not violations:
        best_cost = float(evaluate(solution, bundle.instance, bundle.carbon_profile, prices)["total_cost"])
    feasible = solution is not None and not violations and math.isfinite(best_cost)
    mode = str(task["comparison_mode"])
    eval_complete = actual_evals >= int(task["eval_budget"])
    if feasible and (mode == "wallclock" or eval_complete):
        status = "OK"
        gate_status = "OK"
    elif feasible:
        status = "HALT_RUNTIME_UNDER_EVAL"
        gate_status = status
    else:
        status = "HALT_INFEASIBLE"
        gate_status = status
    if solution is not None:
        write_checkpoint(checkpoint_path, solution_to_dict(solution), best_cost, actual_evals, elapsed, "final")
    convergence_dir = Path(task["output_dir"]) / "convergence" / str(task["scenario"])
    try:
        _write_convergence_files(convergence_dir, [row_for_convergence(task, history)])
    except Exception:
        pass
    return row_from_solution(task, solution, best_cost, actual_evals, len(violations), status, gate_status, elapsed, flags, timings)


def apply_battery_override(battery_kwh: float) -> Any:
    from dataclasses import replace

    import setp_solver.prices as prices_mod

    override = replace(prices_mod.DEFAULT_PRICES, B_battery_kwh=float(battery_kwh))
    prices_mod.DEFAULT_PRICES = override
    return override


def write_checkpoint(path: Path, solution_dict: dict[str, Any], best_cost: float, eval_count: int, elapsed: float, operator: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "setp-09u-checkpoint.v1",
        "eval": int(eval_count),
        "time_seconds": float(elapsed),
        "best_cost": float(best_cost),
        "best_obj": float(best_cost),
        "operator": str(operator),
        "solution": solution_dict,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read_checkpoint(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "solution" not in payload:
            return None
        return payload
    except Exception:
        return None


def timeout_row_from_checkpoint(repo_root: Path, task: dict[str, Any], elapsed: float, stdout: str | bytes | None, stderr: str | bytes | None) -> dict[str, Any]:
    checkpoint = read_checkpoint(Path(task["checkpoint_path"]))
    if checkpoint is None:
        return failure_row(task, elapsed, "HALT_HARD_TIMEOUT", "Worker exceeded runtime cap plus grace and no checkpoint was readable.", stdout, stderr)

    from setp_solver.check import check_solution
    from setp_solver.cost import evaluate
    from setp_solver.search.bundle import load_search_bundle
    from setp_solver.search.metaheuristic_baselines import solution_from_dict

    prices = apply_battery_override(float(task["battery_kwh"]))
    bundle = load_search_bundle(repo_root / str(task["bundle_dir"]))
    solution = solution_from_dict(checkpoint["solution"])
    violations = check_solution(solution, bundle.instance, prices)
    best_cost = float(evaluate(solution, bundle.instance, bundle.carbon_profile, prices)["total_cost"]) if not violations else math.inf
    actual_evals = int(checkpoint.get("eval", 0))
    status = "OK" if str(task.get("comparison_mode")) == "wallclock" and not violations and math.isfinite(best_cost) else "HALT_HARD_TIMEOUT_WITH_INCUMBENT"
    row = row_from_solution(
        task,
        solution,
        best_cost,
        actual_evals,
        len(violations),
        status,
        status,
        elapsed,
        {},
        {},
    )
    return row | {
        "failure_reason": "Worker exceeded runtime cap plus hard-timeout grace; returned last readable checkpoint.",
        "checkpoint_operator": str(checkpoint.get("operator", "")),
        "worker_stdout_tail": tail_text(stdout),
        "worker_stderr_tail": tail_text(stderr),
    }


def row_for_convergence(task: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "instance": task["instance"],
        "algorithm": task["algorithm"],
        "seed": task["seed"],
        "history": history,
    }


def row_from_solution(
    task: dict[str, Any],
    solution: Any,
    best_cost: float,
    actual_evals: int,
    violation_count: int,
    status: str,
    gate_status: str,
    elapsed: float,
    flags: dict[str, str],
    timings: dict[str, Any],
) -> dict[str, Any]:
    routes = list(solution.routes) if solution is not None else []
    charging_actions = list(solution.charging_actions) if solution is not None else []
    cv_routes = [route for route in routes if str(route.vehicle_type).lower() == "cv"]
    ev_routes = [route for route in routes if str(route.vehicle_type).lower() == "ev"]
    trip_counts = Counter(physical_vehicle_id(str(route.vehicle_id)) for route in routes)
    return base_row(task) | {
        "python": sys.executable,
        "numpy": numpy_version(),
        "elapsed_seconds": float(elapsed),
        "actual_evals": int(actual_evals),
        "evals_per_second": float(actual_evals) / float(elapsed) if elapsed > 0 else 0.0,
        "best_cost": float(best_cost),
        "route_count": len(routes),
        "cv_route_count": len(cv_routes),
        "ev_route_count": len(ev_routes),
        "charging_action_count": len(charging_actions),
        "winner_ev_route_share": len(ev_routes) / len(routes) if routes else 0.0,
        "winner_all_cv": bool(routes and not ev_routes),
        "winner_all_ev": bool(routes and not cv_routes),
        "cv_physical_vehicle_count": len({physical_vehicle_id(str(route.vehicle_id)) for route in cv_routes}),
        "ev_physical_vehicle_count": len({physical_vehicle_id(str(route.vehicle_id)) for route in ev_routes}),
        "max_trips_per_physical_vehicle": max(trip_counts.values()) if trip_counts else 0,
        "violation_count": int(violation_count),
        "feasible": bool(solution is not None and violation_count == 0 and math.isfinite(best_cost)),
        "status": status,
        "gate_status": gate_status,
        "active_flags": json.dumps(flags, sort_keys=True),
        "timings": json.dumps(timings, sort_keys=True),
    }


def failure_row(task: dict[str, Any], elapsed: float, status: str, reason: str, stdout: str | bytes | None, stderr: str | bytes | None) -> dict[str, Any]:
    return base_row(task) | {
        "python": sys.executable,
        "numpy": numpy_version(),
        "elapsed_seconds": float(elapsed),
        "actual_evals": 0,
        "evals_per_second": 0.0,
        "best_cost": math.inf,
        "route_count": 0,
        "cv_route_count": 0,
        "ev_route_count": 0,
        "charging_action_count": 0,
        "winner_ev_route_share": 0.0,
        "winner_all_cv": False,
        "winner_all_ev": False,
        "cv_physical_vehicle_count": 0,
        "ev_physical_vehicle_count": 0,
        "max_trips_per_physical_vehicle": 0,
        "violation_count": -1,
        "feasible": False,
        "status": status,
        "gate_status": status,
        "failure_reason": reason,
        "worker_stdout_tail": tail_text(stdout),
        "worker_stderr_tail": tail_text(stderr),
    }


def base_row(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "commit_hash": task["commit_hash"],
        "scenario": task["scenario"],
        "scenario_label": task["scenario_label"],
        "comparison_mode": task["comparison_mode"],
        "battery_kwh": float(task["battery_kwh"]),
        "category": task["category"],
        "instance": task["instance"],
        "size": int(task["size"]),
        "replicate": int(task["replicate"]),
        "algorithm": task["algorithm"],
        "seed": int(task["seed"]),
        "runtime_cap_seconds": float(task["runtime_cap_seconds"]),
        "eval_budget_backstop": int(task["eval_budget"]),
        "checkpoint_path": task["checkpoint_path"],
    }


def physical_vehicle_id(vehicle_id: str) -> str:
    return str(vehicle_id).split("#", 1)[0]


def numpy_version() -> str:
    try:
        import numpy as np

        return str(np.__version__)
    except Exception:
        return ""


def tail_text(value: str | bytes | None, limit: int = 1200) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value)[-limit:]


def load_existing_rows(path: Path) -> dict[tuple[str, str, int, str], dict[str, Any]]:
    if not path.exists():
        return {}
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    return {task_key(row): row for row in rows}


def collect_existing_rows(output_dir: Path) -> list[dict[str, Any]]:
    raw = output_dir / "raw_runs.csv"
    return list(csv.DictReader(raw.open(newline="", encoding="utf-8"))) if raw.exists() else []


def task_key(row: dict[str, Any]) -> tuple[str, str, int, str]:
    return (str(row.get("scenario")), str(row.get("instance")), int(float(row.get("seed", 0))), str(row.get("algorithm")))


def is_retryable(row: dict[str, Any]) -> bool:
    return str(row.get("status")) not in {"OK"}


def queue_row(task: dict[str, Any], action: str, prior_status: str) -> dict[str, Any]:
    return {
        "scenario": task["scenario"],
        "instance": task["instance"],
        "size": task["size"],
        "replicate": task["replicate"],
        "seed": task["seed"],
        "algorithm": task["algorithm"],
        "battery_kwh": task["battery_kwh"],
        "comparison_mode": task["comparison_mode"],
        "runtime_cap_seconds": task["runtime_cap_seconds"],
        "eval_budget": task["eval_budget"],
        "queue_action": action,
        "prior_status": prior_status,
    }


def enrich_rows(repo_root: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        path_text = str(item.get("checkpoint_path", ""))
        checkpoint = Path(path_text)
        if path_text and not checkpoint.is_absolute():
            checkpoint = repo_root / checkpoint
        item["checkpoint_readable"] = checkpoint.exists() if path_text else False
        out.append(item)
    return out


def pair_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_pair: dict[tuple[str, str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_pair[(str(row.get("scenario")), str(row.get("instance")), int(float(row.get("seed", 0))))][str(row.get("algorithm"))] = row
    out: list[dict[str, Any]] = []
    for (scenario, instance, seed), algs in sorted(by_pair.items()):
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
                "scenario": scenario,
                "comparison_mode": alns.get("comparison_mode") or lns.get("comparison_mode"),
                "battery_kwh": as_float(alns.get("battery_kwh", lns.get("battery_kwh"))),
                "category": alns.get("category") or lns.get("category"),
                "instance": instance,
                "size": int(float(alns.get("size", lns.get("size", 0)) or 0)),
                "replicate": int(float(alns.get("replicate", lns.get("replicate", 0)) or 0)),
                "seed": seed,
                "alns_status": alns.get("status"),
                "lns_status": lns.get("status"),
                "alns_evals": int(float(alns.get("actual_evals", 0) or 0)),
                "lns_evals": int(float(lns.get("actual_evals", 0) or 0)),
                "alns_charging_action_count": int(float(alns.get("charging_action_count", 0) or 0)),
                "lns_charging_action_count": int(float(lns.get("charging_action_count", 0) or 0)),
                "alns_cost": alns_cost,
                "lns_cost": lns_cost,
                "gap_pct_alns_minus_lns": gap_pct,
                "paired_winner": winner,
                "winner_algorithm_for_composition": winner_row.get("algorithm"),
                "winner_charging_action_count": int(float(winner_row.get("charging_action_count", 0) or 0)),
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
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in pairs:
        groups[(str(row["scenario"]), str(row["category"]), int(row["size"]))].append(row)
    out: list[dict[str, Any]] = []
    for (scenario, category, size), items in sorted(groups.items()):
        gaps = [as_float(row["gap_pct_alns_minus_lns"]) for row in items if math.isfinite(as_float(row["gap_pct_alns_minus_lns"]))]
        ev_shares = [as_float(row["winner_ev_route_share"]) for row in items if math.isfinite(as_float(row["winner_ev_route_share"]))]
        charging_actions = [as_float(row.get("winner_charging_action_count", 0)) for row in items if math.isfinite(as_float(row.get("winner_charging_action_count", 0)))]
        winner_counts = Counter(str(row["paired_winner"]) for row in items)
        all_cv_count = sum(1 for row in items if boolish(row["winner_all_cv"]))
        all_ev_count = sum(1 for row in items if boolish(row["winner_all_ev"]))
        out.append(
            {
                "scenario": scenario,
                "category": category,
                "size": size,
                "pairs": len(items),
                "mean_gap_pct_alns_minus_lns": statistics.fmean(gaps) if gaps else math.inf,
                "best_gap_pct_alns_minus_lns": min(gaps) if gaps else math.inf,
                "mean_winner_ev_route_share": statistics.fmean(ev_shares) if ev_shares else 0.0,
                "mean_winner_charging_action_count": statistics.fmean(charging_actions) if charging_actions else 0.0,
                "all_cv_winner_share": all_cv_count / len(items) if items else 0.0,
                "all_ev_winner_share": all_ev_count / len(items) if items else 0.0,
                "paired_winner_counts": json.dumps(dict(winner_counts), sort_keys=True),
            }
        )
    return out


def scenario_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs = pair_summary(rows)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pairs:
        groups[str(row["scenario"])].append(row)
    failures = collection_failures(rows)
    failures_by_scenario = Counter(str(row.get("scenario")) for row in failures)
    out: list[dict[str, Any]] = []
    for scenario, items in sorted(groups.items()):
        gaps = [as_float(row["gap_pct_alns_minus_lns"]) for row in items if math.isfinite(as_float(row["gap_pct_alns_minus_lns"]))]
        ev_shares_75 = [as_float(row["winner_ev_route_share"]) for row in items if int(row.get("size", 0)) >= 75]
        charging_75 = [as_float(row.get("winner_charging_action_count", 0)) for row in items if int(row.get("size", 0)) >= 75]
        winner_counts = Counter(str(row["paired_winner"]) for row in items)
        out.append(
            {
                "scenario": scenario,
                "comparison_mode": items[0].get("comparison_mode", "") if items else "",
                "battery_kwh": items[0].get("battery_kwh", "") if items else "",
                "pairs": len(items),
                "paired_winner_counts": json.dumps(dict(winner_counts), sort_keys=True),
                "mean_gap_pct_alns_minus_lns": statistics.fmean(gaps) if gaps else math.inf,
                "mean_winner_ev_route_share_75_200": statistics.fmean(ev_shares_75) if ev_shares_75 else 0.0,
                "mean_winner_charging_action_count_75_200": statistics.fmean(charging_75) if charging_75 else 0.0,
                "collection_failures": int(failures_by_scenario.get(scenario, 0)),
            }
        )
    return out


def mechanism_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs = pair_summary(rows)
    wilcoxon_by_scenario = {str(row["scenario"]): row for row in wilcoxon_summary(pairs)}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pairs:
        grouped[str(row["scenario"])].append(row)

    baseline = _core_mechanism_metrics(grouped.get("wc80", []))
    out: list[dict[str, Any]] = []
    for scenario in sorted(grouped, key=lambda name: (as_float(SCENARIOS.get(name, {}).get("battery_kwh", math.inf)), name)):
        metrics = _core_mechanism_metrics(grouped[scenario])
        wilcox = wilcoxon_by_scenario.get(scenario, {})
        ev_delta = metrics["mean_winner_ev_route_share_75_200"] - baseline["mean_winner_ev_route_share_75_200"]
        gap_delta = metrics["mean_gap_pct_alns_minus_lns_75_200"] - baseline["mean_gap_pct_alns_minus_lns_75_200"]
        nondegenerate = not metrics["majority_all_cv_or_all_ev"]
        stage_a_signal = (
            scenario != "wc80"
            and ev_delta >= 0.10
            and metrics["mean_winner_charging_action_count_75_200"] >= 1.0
            and nondegenerate
            and (gap_delta < -1e-9 or metrics["alns_wins_75_200"] > metrics["lns_wins_75_200"])
        )
        out.append(
            {
                "scenario": scenario,
                "battery_label": HIGH_TENSION_BATTERY_LABELS.get(scenario, scenario),
                "battery_kwh": SCENARIOS.get(scenario, {}).get("battery_kwh", ""),
                **metrics,
                "ev_share_delta_vs_wc80": ev_delta,
                "gap_delta_vs_wc80": gap_delta,
                "wilcoxon_p_less_alns_minus_lns": wilcox.get("p_value_less", math.nan),
                "wilcoxon_method": wilcox.get("method", ""),
                "stage_a_signal_for_stage_b": bool(stage_a_signal),
            }
        )
    return out


def _core_mechanism_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    core = [row for row in items if int(row.get("size", 0)) >= 75]
    selected = core or list(items)
    gaps = [as_float(row.get("gap_pct_alns_minus_lns")) for row in selected if math.isfinite(as_float(row.get("gap_pct_alns_minus_lns")))]
    ev_shares = [as_float(row.get("winner_ev_route_share")) for row in selected if math.isfinite(as_float(row.get("winner_ev_route_share")))]
    charging = [as_float(row.get("winner_charging_action_count", 0)) for row in selected if math.isfinite(as_float(row.get("winner_charging_action_count", 0)))]
    winner_counts = Counter(str(row.get("paired_winner")) for row in selected)
    all_cv = sum(1 for row in selected if boolish(row.get("winner_all_cv")))
    all_ev = sum(1 for row in selected if boolish(row.get("winner_all_ev")))
    pairs = len(selected)
    non_ties = winner_counts.get("alns", 0) + winner_counts.get("lns", 0)
    return {
        "pairs_75_200": pairs,
        "alns_wins_75_200": int(winner_counts.get("alns", 0)),
        "ties_75_200": int(winner_counts.get("tie", 0)),
        "lns_wins_75_200": int(winner_counts.get("lns", 0)),
        "non_tie_pairs_75_200": int(non_ties),
        "mean_gap_pct_alns_minus_lns_75_200": statistics.fmean(gaps) if gaps else math.inf,
        "mean_winner_ev_route_share_75_200": statistics.fmean(ev_shares) if ev_shares else 0.0,
        "mean_winner_charging_action_count_75_200": statistics.fmean(charging) if charging else 0.0,
        "all_cv_winner_share_75_200": all_cv / pairs if pairs else 0.0,
        "all_ev_winner_share_75_200": all_ev / pairs if pairs else 0.0,
        "majority_all_cv_or_all_ev": bool(pairs and (all_cv / pairs > 0.5 or all_ev / pairs > 0.5)),
    }


def wilcoxon_summary(pair_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pair_rows:
        if int(row.get("size", 0)) >= 75:
            groups[str(row["scenario"])].append(row)
    out: list[dict[str, Any]] = []
    for scenario, items in sorted(groups.items()):
        diffs = [as_float(row.get("alns_cost")) - as_float(row.get("lns_cost")) for row in items if math.isfinite(as_float(row.get("alns_cost"))) and math.isfinite(as_float(row.get("lns_cost")))]
        p_value, method = wilcoxon_less(diffs)
        out.append(
            {
                "scenario": scenario,
                "battery_kwh": SCENARIOS.get(scenario, {}).get("battery_kwh", ""),
                "pairs_75_200": len(diffs),
                "nonzero_pairs": sum(1 for value in diffs if abs(value) > 1e-9),
                "wins_alns_lower": sum(1 for value in diffs if value < -1e-9),
                "wins_lns_lower": sum(1 for value in diffs if value > 1e-9),
                "p_value_less": p_value,
                "method": method,
            }
        )
    return out


def wilcoxon_less(diffs: list[float]) -> tuple[float, str]:
    nonzero = [float(value) for value in diffs if abs(float(value)) > 1e-9]
    if not nonzero:
        return 1.0, "all_zero"
    try:
        from scipy.stats import wilcoxon

        try:
            result = wilcoxon(nonzero, alternative="less", zero_method="wilcox", method="auto")
        except TypeError:
            result = wilcoxon(nonzero, alternative="less", zero_method="wilcox")
        return float(result.pvalue), "scipy_wilcoxon_less"
    except Exception:
        return sign_test_less(nonzero), "fallback_sign_test_less"


def sign_test_less(diffs: list[float]) -> float:
    nonzero = [float(value) for value in diffs if abs(float(value)) > 1e-9]
    if not nonzero:
        return 1.0
    wins = sum(1 for value in nonzero if value < 0.0)
    n = len(nonzero)
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / (2 ** n)


def high_tension_decision(rows: list[dict[str, Any]], *, expected_count: int, instances_mode: str) -> dict[str, Any]:
    failures = collection_failures(rows)
    pairs = pair_summary(rows)
    mechanism = mechanism_summary(rows)
    wilcoxon_rows = wilcoxon_summary(pairs)
    if len(rows) != expected_count or failures:
        return {
            "verdict": "HALT_COLLECTION_COST",
            "plain": "09v 数据没有闭合，或存在非零违约/环境漂移/不可读 checkpoint；这是 PROBE，不能下算法结论。",
            "rows": len(rows),
            "expected_rows": expected_count,
            "paired_rows": len(pairs),
            "collection_failure_count": len(failures) + (0 if len(rows) == expected_count else 1),
            "stage_b_recommended": False,
            "mechanism_summary": mechanism,
            "wilcoxon_summary": wilcoxon_rows,
            "failure_sample": _failure_sample(failures),
            "report_kind": "high_tension",
        }

    baseline = next((row for row in mechanism if row["scenario"] == "wc80"), {})
    active = [
        row
        for row in mechanism
        if row["scenario"] != "wc80"
        and row["ev_share_delta_vs_wc80"] >= 0.10
        and row["mean_winner_charging_action_count_75_200"] >= 1.0
        and not boolish(row["majority_all_cv_or_all_ev"])
    ]
    stage_b_candidates = [row for row in active if boolish(row["stage_a_signal_for_stage_b"])]
    pass_rows = [
        row
        for row in active
        if as_float(row.get("wilcoxon_p_less_alns_minus_lns")) < 0.05
        and int(row.get("alns_wins_75_200", 0)) > int(row.get("lns_wins_75_200", 0))
        and as_float(row.get("mean_gap_pct_alns_minus_lns_75_200")) < as_float(baseline.get("mean_gap_pct_alns_minus_lns_75_200", math.inf))
    ]

    if pass_rows:
        verdict = "PASS_MECHANISM_SEPARATION"
        plain = "09v PROBE 显示：至少一个高机制活跃度档中 ALNS 相对 LNS 出现统计支持的分离。下一步应另起正式场景化与 T3 提示词。"
    elif active:
        verdict = "INCONCLUSIVE_FAIL_NO_SEPARATION"
        plain = "09v PROBE 找到了非退化的高机制活跃度档，但 vanilla ALNS 仍未相对 LNS 清晰分离；停止继续用电池/regime 调 vanilla ALNS，算法创新转向 DR-ALNS。"
    else:
        verdict = "INCONCLUSIVE_NO_NONDEGENERATE_TENSION"
        plain = "09v PROBE 未找到非退化且充电/EV 机制真正咬合的高张力档；all-CV/all-EV 退化档的打平不证伪机制假设，但也不能支撑正式 T3。"

    stage_b_recommended = bool(instances_mode == "gradient01" and stage_b_candidates and not pass_rows)
    return {
        "verdict": verdict,
        "plain": plain,
        "rows": len(rows),
        "expected_rows": expected_count,
        "paired_rows": len(pairs),
        "collection_failure_count": 0,
        "stage_b_recommended": stage_b_recommended,
        "stage_b_reason": "Stage A detected high-tension nondegenerate signal." if stage_b_recommended else "Stage B not triggered by the preregistered Stage A rule.",
        "stage_b_candidate_scenarios": [row["scenario"] for row in stage_b_candidates],
        "pass_candidate_scenarios": [row["scenario"] for row in pass_rows],
        "mechanism_summary": mechanism,
        "wilcoxon_summary": wilcoxon_rows,
        "failure_sample": [],
        "report_kind": "high_tension",
    }


def _failure_sample(failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "scenario": row.get("scenario"),
            "instance": row.get("instance"),
            "algorithm": row.get("algorithm"),
            "seed": row.get("seed"),
            "status": row.get("status"),
            "bucket": row.get("failure_bucket"),
        }
        for row in failures[:10]
    ]


def collection_failures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("python")) != GOLD_PYTHON:
            failures.append(row | {"failure_bucket": "python_mismatch"})
        if str(row.get("numpy")) != GOLD_NUMPY:
            failures.append(row | {"failure_bucket": "numpy_mismatch"})
        if str(row.get("gate_status")) != "OK":
            failures.append(row | {"failure_bucket": "status_not_ok"})
        if int(float(row.get("violation_count", 99))) != 0:
            failures.append(row | {"failure_bucket": "nonzero_violation"})
        if not boolish(row.get("checkpoint_readable")):
            failures.append(row | {"failure_bucket": "checkpoint_unreadable"})
    return failures


def conclude(
    phase0: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    expected_count: int,
    report_kind: str = "preflight",
    instances_mode: str = "smoke",
) -> dict[str, Any]:
    if not phase0.get("phase0_ok"):
        return {"verdict": "HALT_SEMANTIC_DRIFT", "phase0_ok": False, "plain": "默认参数、环境或09s warm-start锚点不一致，先不跑比较。"}
    if expected_count == 0:
        return {"verdict": "PHASE0_OK", "phase0_ok": True, "plain": "只完成Phase0。"}
    if report_kind == "high_tension":
        return high_tension_decision(rows, expected_count=expected_count, instances_mode=instances_mode) | {"phase0_ok": True}
    failures = collection_failures(rows)
    pairs = pair_summary(rows)
    scenario_rows = scenario_summary(rows)
    if len(rows) != expected_count or failures:
        verdict = "HALT_COLLECTION_COST"
        plain = "数据还没收完整，或有场景没有返回零违约 incumbent；不能下正式算法结论。"
    else:
        verdict = "PREFLIGHT_COMPLETE"
        plain = "测试数据收齐，可以比较同等时间、降预算和100kWh对车队构成的影响。"
    return {
        "verdict": verdict,
        "phase0_ok": True,
        "rows": len(rows),
        "expected_rows": expected_count,
        "paired_rows": len(pairs),
        "collection_failure_count": len(failures) + (0 if len(rows) == expected_count else 1),
        "plain": plain,
        "scenario_summary": scenario_rows,
        "failure_sample": _failure_sample(failures),
    }


def render_report(metadata: dict[str, Any], phase0: dict[str, Any], conclusion: dict[str, Any]) -> str:
    if metadata.get("report_kind") == "high_tension":
        return render_high_tension_report(metadata, phase0, conclusion)
    scenario_lines = []
    for row in conclusion.get("scenario_summary", []):
        scenario_lines.append(
            "| {scenario} | {mode} | {battery} | {pairs} | {wins} | {gap:.4f} | {ev:.4f} | {failures} |".format(
                scenario=row.get("scenario", ""),
                mode=row.get("comparison_mode", ""),
                battery=row.get("battery_kwh", ""),
                pairs=row.get("pairs", 0),
                wins=row.get("paired_winner_counts", "{}"),
                gap=float(row.get("mean_gap_pct_alns_minus_lns", math.inf)),
                ev=float(row.get("mean_winner_ev_route_share_75_200", 0.0)),
                failures=row.get("collection_failures", 0),
            )
        )
    lines = [
        "# 09u Wall-Clock Battery Preflight",
        "",
        f"Verdict: `{conclusion['verdict']}`",
        "",
        "## Plain Reading",
        "",
        str(conclusion.get("plain", "")),
        "",
        "## Phase 0",
        "",
        f"- Phase0 OK: `{phase0.get('phase0_ok')}`",
        f"- Defaults probe: `{json.dumps(phase0.get('default_probe', {}), sort_keys=True)}`",
        f"- 09s warm start rows OK: `{phase0.get('warm_start_09s_ok')}` with `{phase0.get('warm_start_rows')}` rows",
        "",
        "## Scenario Summary",
        "",
        "| scenario | mode | battery kWh | pairs | paired winners | mean gap % ALNS-LNS | mean EV route share 75-200 | failures |",
        "|---|---|---:|---:|---|---:|---:|---:|",
        *scenario_lines,
        "",
        "## Artifacts",
        "",
        f"- Data dir: `{metadata.get('output_dir')}`",
        f"- Raw rows: `{metadata.get('output_dir')}/raw_runs.csv`",
        f"- Paired summary: `{metadata.get('output_dir')}/paired_summary.csv`",
        f"- Scale summary: `{metadata.get('output_dir')}/scale_summary.csv`",
        f"- Scenario summary: `{metadata.get('output_dir')}/scenario_summary.csv`",
        f"- Report: `{metadata.get('report_path')}`",
        f"- HEAD at run start: `{metadata.get('head')}`",
        f"- Artifact commit hash: `{metadata.get('artifact_commit_hash')}`",
        "",
        "## Interpretation Rules",
        "",
        "- `wc80/wc100` compare algorithms by equal wall-clock caps; under-eval is acceptable if a zero-violation incumbent is returned.",
        "- `budget8k80/budget8k100` test whether a lower fixed budget can close inside the same caps; under-eval remains a collection failure.",
        "- `100kWh` is an in-memory diagnostic override only. It is not promoted to a default parameter by this report.",
        "- Goeke80 is interpreted as a Goeke baseline scene unless a later evidence-backed scenario is selected for the mixed-fleet story.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_high_tension_report(metadata: dict[str, Any], phase0: dict[str, Any], conclusion: dict[str, Any]) -> str:
    mechanism_lines = []
    for row in conclusion.get("mechanism_summary", []):
        wins = f"{int(row.get('alns_wins_75_200', 0))}/{int(row.get('ties_75_200', 0))}/{int(row.get('lns_wins_75_200', 0))}"
        p_value = as_float(row.get("wilcoxon_p_less_alns_minus_lns"))
        p_text = f"{p_value:.4g}" if math.isfinite(p_value) else "nan"
        mechanism_lines.append(
            "| {label} | {ev:.4f} | {charge:.2f} | {wins} | {gap:.4f} | {p} | {degenerate} |".format(
                label=row.get("battery_label", row.get("scenario", "")),
                ev=as_float(row.get("mean_winner_ev_route_share_75_200")),
                charge=as_float(row.get("mean_winner_charging_action_count_75_200")),
                wins=wins,
                gap=as_float(row.get("mean_gap_pct_alns_minus_lns_75_200")),
                p=p_text,
                degenerate=row.get("majority_all_cv_or_all_ev"),
            )
        )

    failure_lines = []
    for row in conclusion.get("failure_sample", []):
        failure_lines.append(
            f"| {row.get('scenario', '')} | {row.get('instance', '')} | {row.get('algorithm', '')} | {row.get('seed', '')} | {row.get('status', '')} | {row.get('bucket', '')} |"
        )

    lines = [
        "# 09v High-Tension ALNS vs LNS Separation Probe",
        "",
        "Evidence level: **PROBE / 非正式 T3**. This report does not claim formal algorithm dominance.",
        "",
        f"Verdict: `{conclusion['verdict']}`",
        "",
        "## Plain Reading",
        "",
        str(conclusion.get("plain", "")),
        "",
        "本步服务的目标：验证 ALNS 在 Goeke80/100 下与 LNS 打平，是否只是因为 EV/充电/碳机制几乎不活跃；若电池档提高后机制咬合，ALNS-LNS 配对差是否随之分离。",
        "",
        "## Phase 0",
        "",
        f"- Phase0 OK: `{phase0.get('phase0_ok')}`",
        f"- Defaults probe: `{json.dumps(phase0.get('default_probe', {}), sort_keys=True)}`",
        f"- 09s warm start rows OK: `{phase0.get('warm_start_09s_ok')}` with `{phase0.get('warm_start_rows')}` rows",
        "",
        "## Mechanism Separation Summary",
        "",
        "| battery tier | mean EV route share (75-200) | mean charging actions | ALNS/tie/LNS | mean gap % ALNS-LNS | Wilcoxon p | majority all-CV/all-EV |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *mechanism_lines,
        "",
        "## Stage Decision",
        "",
        f"- Stage B recommended: `{conclusion.get('stage_b_recommended')}`",
        f"- Stage B reason: {conclusion.get('stage_b_reason', '')}",
        f"- Stage B candidate scenarios: `{json.dumps(conclusion.get('stage_b_candidate_scenarios', []), ensure_ascii=False)}`",
        f"- PASS candidate scenarios: `{json.dumps(conclusion.get('pass_candidate_scenarios', []), ensure_ascii=False)}`",
        "",
        "## Caveat",
        "",
        "If a battery tier degenerates into majority all-CV or majority all-EV, a tie there is not evidence against the target hypothesis. The hypothesis concerns non-degenerate contested regimes where EV use and charging actually bind.",
        "",
        "## Artifacts",
        "",
        f"- Data dir: `{metadata.get('output_dir')}`",
        f"- Raw rows: `{metadata.get('output_dir')}/raw_runs.csv`",
        f"- Paired summary: `{metadata.get('output_dir')}/paired_summary.csv`",
        f"- Mechanism summary: `{metadata.get('output_dir')}/mechanism_summary.csv`",
        f"- Wilcoxon summary: `{metadata.get('output_dir')}/wilcoxon_summary.csv`",
        f"- Stage decision: `{metadata.get('output_dir')}/stage_decision.json`",
        f"- Artifact hashes: `{metadata.get('output_dir')}/artifact_hashes.json`",
        f"- Report: `{metadata.get('report_path')}`",
        f"- HEAD at run start: `{metadata.get('head')}`",
        f"- Artifact commit hash: `{metadata.get('artifact_commit_hash')}`",
        "",
        "## Collection Failures",
        "",
        "| scenario | instance | algorithm | seed | status | bucket |",
        "|---|---|---|---:|---|---|",
        *(failure_lines or ["|  |  |  |  | none |  |"]),
        "",
        "## Interpretation Rules",
        "",
        "- `80/100/150/280kWh` are in-memory diagnostic battery overrides only.",
        "- Carbon price stays fixed at `0.05034`; no cost/check/evaluation/default-parameter semantics are changed.",
        "- Stage A is a trend probe. Stage B only runs if the preregistered Stage A signal appears.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def artifact_hashes(output_dir: Path, report_path: Path) -> dict[str, Any]:
    candidates = [
        output_dir / "phase0_audit.json",
        output_dir / "raw_runs.csv",
        output_dir / "paired_summary.csv",
        output_dir / "scale_summary.csv",
        output_dir / "scenario_summary.csv",
        output_dir / "mechanism_summary.csv",
        output_dir / "wilcoxon_summary.csv",
        output_dir / "stage_decision.json",
        output_dir / "metadata.json",
        output_dir / "conclusion.json",
        report_path,
    ]
    return {
        "schema": "setp-09v-artifact-hashes.v1",
        "files": [
            {
                "path": str(path),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in candidates
            if path.exists()
        ],
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    try:
        return subprocess.check_output(["git", *args], cwd=repo_root, text=True).strip()
    except Exception:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
