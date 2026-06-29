from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution, solution_signature_hash
from setp_solver.search.dynamic import RollingParameters, run_rolling_reoptimization
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.search.metaheuristic_baselines import (
    BASELINE_ALGORITHMS,
    run_metaheuristic_baseline,
    solution_to_dict,
)
from setp_solver.search.candidates import run_candidate
from setp_solver.search.winner_operators import (
    WinnerKernelConfig,
    _run_winner_variant,
    e2_alns_throughput_flags,
    run_winner_kernel,
)

from .pilot20_learned_destroy_phaseA import DEFAULT_WORKER, REQUIRED_WORKER_NUMPY, _parse_int_list
from .pilot22_grounded_fixes import _git_snapshot, _load_state, _log, _run_python_json, _save_state, _write_json


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track15")
DEFAULT_BUNDLES = (
    "models/data_bundle/generated_instances/E-UK25_02__curric_d2_s3_seed2_24h",
    "models/data_bundle/generated_instances/E-UK50_01__curric_d2_s3_seed1_24h",
)
PROTECTED_FILES = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/search/winner_operators.py",
)
TERMINAL_STATUSES = {
    "WIN_REAL",
    "MARGIN_SMALL",
    "HALT_BASELINE_NOT_RUNNING",
    "HALT_PREFLIGHT",
    "HALT_WALL_CLOCK",
    "HALT_PROTECTED_DIRTY",
    "DR_DYNAMIC_PROMISING",
    "DR_DYNAMIC_FLAT",
}


class Track15Halt(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "track15_progress.log"
    state_path = output_dir / "track15_state.json"
    state = _load_state(state_path) if args.resume else {}
    started = time.monotonic()
    final_status = str(state.get("final_status") or "RUNNING")
    final_reason = str(state.get("final_reason") or "")
    try:
        _enforce_resume_guard(state, resume=bool(args.resume))
        _log(progress_path, "Track15 start")
        preflight = run_preflight(args, output_dir)
        os.environ["SETP_WORKER_PYTHON"] = str(Path(args.worker_python).resolve())
        state["preflight"] = preflight
        _save_state(state_path, state)

        if not state.get("trackA_done"):
            track_a = run_track_a(args, output_dir, progress_path, state, started)
            state["trackA"] = track_a
            state["trackA_done"] = True
            _save_state(state_path, state)
            _write_json(output_dir / "trackA_fair_report.json", track_a)
            (output_dir / "trackA_fair_report.md").write_text(_track_a_report(track_a), encoding="utf-8")
            if track_a["verdict"] == "HALT_BASELINE_NOT_RUNNING":
                raise Track15Halt(track_a["verdict"], track_a["reason"])

        if not state.get("trackB_done"):
            _check_wall(started, args.max_wall_seconds)
            track_b = run_track_b(args, output_dir, progress_path, started)
            state["trackB"] = track_b
            state["trackB_done"] = True
            _save_state(state_path, state)
            _write_json(output_dir / "trackB_dynamic_report.json", track_b)
            (output_dir / "trackB_dynamic_report.md").write_text(_track_b_report(track_b), encoding="utf-8")

        final = summarize_final(state)
        final_status = final["final_status"]
        final_reason = final["final_reason"]
        state.update(final)
        return 0 if final_status in {"WIN_REAL", "MARGIN_SMALL", "DR_DYNAMIC_PROMISING", "DR_DYNAMIC_FLAT"} else 2
    except Track15Halt as exc:
        final_status = exc.status
        final_reason = exc.message
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _save_state(state_path, state)
        _log(progress_path, f"HALT {final_status}: {final_reason}")
        return 2
    except KeyboardInterrupt:
        final_status = "HALT_INTERRUPTED"
        final_reason = "Interrupted; checkpoint is intact."
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _save_state(state_path, state)
        _log(progress_path, f"HALT {final_status}: {final_reason}")
        return 130
    finally:
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        state["wall_time_seconds"] = float(time.monotonic() - started)
        _save_state(state_path, state)
        _write_json(output_dir / "final_report.json", state)
        final_text = _final_report(state)
        (output_dir / "final_report.md").write_text(final_text, encoding="utf-8")
        Path("final_report.md").write_text(final_text, encoding="utf-8")


def run_preflight(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    git_fetch = _git_fetch()
    docs_status = _git_status_paths(
        [
            "HANDOFF.md",
            "docs/handoff/codex_prompts/15_final_trackA_fair_baselines_trackB_dynamic_dr.md",
        ]
    )
    if docs_status:
        raise Track15Halt("HALT_PREFLIGHT", f"handoff docs are not committed: {docs_status}")
    protected_status = _git_status_paths(PROTECTED_FILES)
    if protected_status:
        raise Track15Halt("HALT_PROTECTED_DIRTY", f"protected files are dirty before run: {protected_status}")
    worker_python = Path(args.worker_python).resolve()
    if not worker_python.exists():
        raise Track15Halt("HALT_PREFLIGHT", f"py313 worker missing: {worker_python}")
    worker = _run_python_json(
        worker_python,
        "import json,sys,numpy; print(json.dumps({'exe':sys.executable,'version':sys.version.split()[0],'numpy':numpy.__version__}))",
    )
    if str(worker.get("numpy")) != REQUIRED_WORKER_NUMPY:
        raise Track15Halt("HALT_PREFLIGHT", f"worker NumPy drift: {worker.get('numpy')} != {REQUIRED_WORKER_NUMPY}")
    if bool(args.require_self_py313) and Path(sys.executable).resolve() != worker_python:
        raise Track15Halt("HALT_PREFLIGHT", f"runner must execute under py313 worker: {sys.executable} != {worker_python}")
    free_gb = shutil.disk_usage(output_dir.resolve().anchor or ".").free / (1024.0**3)
    if free_gb < float(args.min_free_disk_gb):
        raise Track15Halt("HALT_PREFLIGHT", f"free disk {free_gb:.1f}GB < {args.min_free_disk_gb}GB")
    missing = [path for path in _parse_csv(args.bundles) if not Path(path).exists()]
    if missing:
        raise Track15Halt("HALT_PREFLIGHT", f"bundle missing: {missing}")
    return {
        "git_fetch": git_fetch,
        "git": _git_snapshot(),
        "worker": worker,
        "runner_executable": sys.executable,
        "disk_free_gb": free_gb,
        "bundles": _parse_csv(args.bundles),
        "protected_status": protected_status,
    }


def run_track_a(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    state: dict[str, Any],
    started: float,
) -> dict[str, Any]:
    rows_path = output_dir / "trackA_rows.csv"
    solutions_dir = output_dir / "trackA_strong_solutions"
    solutions_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_rows(rows_path) if args.resume and rows_path.exists() else []
    done_keys = {(row["bundle"], int(row["seed"]), row["algorithm"]) for row in rows}
    bundles = _parse_csv(args.bundles)
    seeds = _parse_int_list(args.seeds)
    algorithms = _parse_csv(args.baseline_algorithms)
    if not algorithms:
        algorithms = list(BASELINE_ALGORITHMS)
    for bundle_dir in bundles:
        bundle_name = Path(bundle_dir).name
        warm = _warm_start_metrics(bundle_dir)
        for seed in seeds:
            for algorithm in ["plain_alns", "strong_method", *algorithms]:
                key = (bundle_name, int(seed), algorithm)
                if key in done_keys:
                    continue
                _check_wall(started, args.max_wall_seconds)
                _log(progress_path, f"TrackA run bundle={bundle_name} seed={seed} algorithm={algorithm}")
                if algorithm == "plain_alns":
                    row, _solution = _run_plain_alns(bundle_dir, seed=seed, args=args, warm=warm)
                elif algorithm == "strong_method":
                    row, solution = _run_strong_method(bundle_dir, seed=seed, args=args, warm=warm)
                    _write_json(
                        solutions_dir / f"{bundle_name}_seed{seed}_strong_solution.json",
                        solution_to_dict(solution),
                    )
                else:
                    row, _solution = _run_baseline_algorithm(bundle_dir, algorithm, seed=seed, args=args, warm=warm)
                row["track"] = "A"
                row["bundle"] = bundle_name
                row["bundle_dir"] = str(bundle_dir)
                row["seed"] = int(seed)
                rows.append(row)
                _write_rows(rows_path, rows)
                if row["role"] == "weak_baseline" and row["health_status"] != "HEALTHY":
                    track_a = summarize_track_a(rows, args)
                    track_a["verdict"] = "HALT_BASELINE_NOT_RUNNING"
                    track_a["reason"] = f"{algorithm} failed baseline health on {bundle_name}/seed{seed}: {row['health_status']} {row.get('failure_reason', '')}"
                    return track_a
    return summarize_track_a(rows, args)


def run_track_b(args: argparse.Namespace, output_dir: Path, progress_path: Path, started: float) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    rows_path = output_dir / "trackB_dynamic_rows.csv"
    bundles = _parse_csv(args.bundles)[: max(1, int(args.dynamic_bundles))]
    seeds = _parse_int_list(args.dynamic_seeds)
    for bundle_dir in bundles:
        for seed in seeds:
            _check_wall(started, args.max_wall_seconds)
            bundle_name = Path(bundle_dir).name
            out_json = output_dir / "trackB_dynamic_payloads" / f"{bundle_name}_seed{seed}.json"
            _log(progress_path, f"TrackB rolling ALNS control bundle={bundle_name} seed={seed}")
            payload = run_rolling_reoptimization(
                bundle_dir,
                output_json_path=out_json,
                seed=int(seed),
                eval_budget=int(args.dynamic_eval_budget),
                max_runtime_seconds=float(args.dynamic_max_runtime_seconds),
                stage_eval_budget=int(args.dynamic_stage_eval_budget),
                stage_max_runtime_seconds=float(args.dynamic_stage_max_runtime_seconds),
                params=RollingParameters(stages=int(args.dynamic_stages)),
            )
            rows.append(
                {
                    "bundle": bundle_name,
                    "seed": int(seed),
                    "algorithm": "rolling_alns_resolve",
                    "status": payload.get("status", payload.get("gate", "UNKNOWN")),
                    "total_evaluations": int(payload.get("total_evaluations", 0) or 0),
                    "final_cost": float(payload.get("final_total_cost", payload.get("cumulative_cost", math.nan)) or math.nan),
                    "dr_online_available": False,
                    "payload_path": str(out_json),
                }
            )
            _write_rows(rows_path, rows)
    return {
        "verdict": "DR_DYNAMIC_FLAT",
        "reason": "No trained dynamic DR-online policy entrypoint exists in this checkout; TrackB ran the rolling ALNS control only and refuses to label a heuristic surrogate as DR.",
        "rows": rows,
        "row_count": len(rows),
    }


def summarize_track_a(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    health_failures = [row for row in rows if row.get("role") == "weak_baseline" and row.get("health_status") != "HEALTHY"]
    if health_failures:
        return {
            "verdict": "HALT_BASELINE_NOT_RUNNING",
            "reason": f"{len(health_failures)} weak-baseline rows failed health gates.",
            "rows": rows,
            "summary": _track_a_stats(rows),
        }
    stats = _track_a_stats(rows)
    strong_plain_gain = float(stats.get("strong_vs_plain_mean_gain_pct", math.nan))
    weak_min_gain = float(stats.get("strong_vs_weak_min_mean_gain_pct", math.nan))
    zero_violations = all(int(row.get("violation_count", 1) or 0) == 0 for row in rows)
    if zero_violations and strong_plain_gain > float(args.strong_plain_threshold_pct) and weak_min_gain >= float(args.weak_win_threshold_pct):
        verdict = "WIN_REAL"
        reason = f"strong beats plain by {strong_plain_gain:.2f}% and every healthy weak baseline by at least {weak_min_gain:.2f}% mean."
    else:
        verdict = "MARGIN_SMALL"
        reason = f"health gates passed, but margin is short or mixed: strong/plain={strong_plain_gain:.2f}%, min weak={weak_min_gain:.2f}%, zero_violations={zero_violations}."
    return {"verdict": verdict, "reason": reason, "rows": rows, "summary": stats}


def summarize_final(state: dict[str, Any]) -> dict[str, str]:
    track_a = state.get("trackA") or {}
    track_b = state.get("trackB") or {}
    if track_a.get("verdict") == "WIN_REAL":
        return {"final_status": "WIN_REAL", "final_reason": str(track_a.get("reason", ""))}
    if track_a.get("verdict") == "HALT_BASELINE_NOT_RUNNING":
        return {"final_status": "HALT_BASELINE_NOT_RUNNING", "final_reason": str(track_a.get("reason", ""))}
    if track_b.get("verdict") == "DR_DYNAMIC_PROMISING":
        return {"final_status": "DR_DYNAMIC_PROMISING", "final_reason": str(track_b.get("reason", ""))}
    if track_a.get("verdict") == "MARGIN_SMALL":
        return {"final_status": "MARGIN_SMALL", "final_reason": str(track_a.get("reason", ""))}
    return {"final_status": "DR_DYNAMIC_FLAT", "final_reason": str(track_b.get("reason", "TrackB did not produce a DR breakthrough."))}


def baseline_health(row: dict[str, Any], *, min_eval_ratio: float = 0.9) -> str:
    if not bool(row.get("feasible", False)) or int(row.get("violation_count", 1) or 0) != 0:
        return "UNHEALTHY_VIOLATION"
    if float(row.get("eval_ratio", 0.0) or 0.0) < float(min_eval_ratio):
        return "UNHEALTHY_UNDER_EVAL"
    if bool(row.get("returned_warm_start", False)):
        return "UNHEALTHY_WARM_HASH"
    if float(row.get("improvement_vs_warm_pct", 0.0) or 0.0) <= 0.0:
        return "UNHEALTHY_NO_IMPROVEMENT"
    return "HEALTHY"


def _run_plain_alns(bundle_dir: str, *, seed: int, args: argparse.Namespace, warm: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    run = run_winner_kernel(
        bundle_dir,
        config=WinnerKernelConfig(seed=int(seed), eval_budget=int(args.eval_budget), max_runtime_seconds=float(args.max_runtime_seconds)),
        initial_solution=warm["solution"],
    )
    return _winner_row(run, role="plain_alns", warm=warm, health_gate=False), run["best_solution"]


def _run_strong_method(bundle_dir: str, *, seed: int, args: argparse.Namespace, warm: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    flags = e2_alns_throughput_flags()
    flags.update(
        {
            "SETP_ALNS_CRUSH_ROUTE_ELIMINATION": "1",
            "SETP_ALNS_CRUSH_LOCAL_SEARCH": "1",
        }
    )
    config = WinnerKernelConfig(
        seed=int(seed),
        eval_budget=int(args.eval_budget),
        max_runtime_seconds=float(args.max_runtime_seconds),
        require_charging_signal=True,
        include_route_elimination=True,
    )
    run = _run_winner_variant(bundle_dir, config, initial_solution=warm["solution"], variant_flags=flags, variant_id="track15_strong_method")
    return _winner_row(run, role="strong_method", warm=warm, health_gate=False), run["best_solution"]


def _run_baseline_algorithm(
    bundle_dir: str,
    algorithm: str,
    *,
    seed: int,
    args: argparse.Namespace,
    warm: dict[str, Any],
) -> tuple[dict[str, Any], Any]:
    started = time.perf_counter()
    if algorithm == "SA":
        run = run_candidate(
            "scikit-opt-SA",
            bundle_dir,
            seed=int(seed),
            eval_budget=int(args.eval_budget),
            max_runtime_seconds=float(args.max_runtime_seconds),
            initial_solution=warm["solution"],
        )
        solution = run.best_solution
        violations = check_solution(solution, load_search_bundle(bundle_dir).instance, DEFAULT_PRICES) if solution is not None else ["no-solution"]
        row = {
            "algorithm": "SA",
            "role": "weak_baseline",
            "status": run.status,
            "actual_evals": int(run.evals),
            "elapsed_seconds": float(run.elapsed_seconds),
            "best_cost": float(run.best_cost) if run.best_cost is not None else math.nan,
            "solution_signature_hash": solution_signature_hash(solution) if solution is not None else "",
            "violation_count": len(violations),
            "feasible": solution is not None and not violations,
            "failure_reason": "",
        }
    else:
        result = run_metaheuristic_baseline(
            algorithm,
            bundle_dir,
            seed=int(seed),
            eval_budget=int(args.eval_budget),
            max_runtime_seconds=float(args.max_runtime_seconds),
            initial_solution=warm["solution"],
        )
        solution = result.best_solution
        row = {
            "algorithm": result.algorithm,
            "role": "weak_baseline",
            "status": result.status,
            "actual_evals": int(result.evals),
            "elapsed_seconds": float(result.elapsed_seconds),
            "best_cost": float(result.best_cost) if result.best_cost is not None else math.nan,
            "solution_signature_hash": result.solution_signature_hash,
            "violation_count": int(result.violation_count),
            "feasible": bool(result.feasible),
            "failure_reason": result.failure_reason,
        }
    _fill_common_row_fields(row, warm=warm, eval_budget=int(args.eval_budget), max_runtime_seconds=float(args.max_runtime_seconds))
    row["health_status"] = baseline_health(row, min_eval_ratio=float(args.min_eval_ratio))
    row["wall_elapsed_seconds"] = float(time.perf_counter() - started)
    return row, solution


def _winner_row(run: dict[str, Any], *, role: str, warm: dict[str, Any], health_gate: bool) -> dict[str, Any]:
    solution = run["best_solution"]
    row = {
        "algorithm": "strong_method" if role == "strong_method" else "plain_alns",
        "role": role,
        "status": "OK" if run.get("feasible") else "HALT_INFEASIBLE",
        "actual_evals": int(run.get("evaluations", 0) or 0),
        "elapsed_seconds": float(run.get("elapsed_seconds", 0.0) or 0.0),
        "best_cost": float(run.get("best_cost", math.nan)),
        "solution_signature_hash": solution_signature_hash(solution),
        "violation_count": int(run.get("violation_count", 0) or 0),
        "feasible": bool(run.get("feasible", False)),
        "failure_reason": "",
        "variant": run.get("variant", ""),
        "flags": json.dumps(run.get("flags", {}), sort_keys=True),
        "operator_counts": json.dumps(run.get("operator_counts", {}), sort_keys=True, default=str),
    }
    _fill_common_row_fields(row, warm=warm, eval_budget=int(run.get("eval_budget", 0) or 0), max_runtime_seconds=float(run.get("max_runtime_seconds", 0.0) or 0.0))
    row["health_status"] = baseline_health(row) if health_gate else "NOT_BASELINE_GATE"
    return row


def _fill_common_row_fields(row: dict[str, Any], *, warm: dict[str, Any], eval_budget: int, max_runtime_seconds: float) -> None:
    best_cost = float(row.get("best_cost", math.nan))
    warm_cost = float(warm["cost"])
    row["eval_budget"] = int(eval_budget)
    row["eval_ratio"] = float(row.get("actual_evals", 0) or 0) / max(1, int(eval_budget))
    row["max_runtime_seconds"] = float(max_runtime_seconds)
    row["warm_start_cost"] = warm_cost
    row["warm_start_hash"] = warm["hash"]
    row["returned_warm_start"] = str(row.get("solution_signature_hash", "")) == str(warm["hash"])
    row["improvement_vs_warm_pct"] = ((warm_cost - best_cost) / warm_cost * 100.0) if math.isfinite(best_cost) and warm_cost > 0 else math.nan


def _warm_start_metrics(bundle_dir: str | Path) -> dict[str, Any]:
    bundle = load_search_bundle(bundle_dir)
    solution = make_shared_initial_solution(bundle)
    context = EvaluationContext(bundle.instance, bundle.carbon_profile)
    violations = check_solution(solution, bundle.instance, DEFAULT_PRICES)
    return {
        "solution": solution,
        "cost": float(model_cost(solution, context)),
        "hash": solution_signature_hash(solution),
        "violation_count": len(violations),
    }


def _track_a_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pairs: dict[tuple[str, int], dict[str, float]] = {}
    for row in rows:
        if row.get("best_cost") in {None, ""}:
            continue
        key = (str(row.get("bundle")), int(row.get("seed", 0) or 0))
        pairs.setdefault(key, {})[str(row.get("algorithm"))] = float(row.get("best_cost"))
    strong_plain: list[float] = []
    weak_by_algorithm: dict[str, list[float]] = {}
    for costs in pairs.values():
        strong = costs.get("strong_method")
        plain = costs.get("plain_alns")
        if strong is not None and plain is not None and plain > 0:
            strong_plain.append((plain - strong) / plain * 100.0)
        for algorithm, cost in costs.items():
            if algorithm in {"strong_method", "plain_alns"} or strong is None or cost <= 0:
                continue
            weak_by_algorithm.setdefault(algorithm, []).append((cost - strong) / cost * 100.0)
    weak_mean = {algorithm: _mean(values) for algorithm, values in weak_by_algorithm.items()}
    return {
        "row_count": len(rows),
        "strong_vs_plain_mean_gain_pct": _mean(strong_plain),
        "strong_vs_weak_mean_gain_pct_by_algorithm": weak_mean,
        "strong_vs_weak_min_mean_gain_pct": min(weak_mean.values()) if weak_mean else math.nan,
        "health_failures": [row for row in rows if row.get("role") == "weak_baseline" and row.get("health_status") != "HEALTHY"],
    }


def _mean(values: list[float]) -> float:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    return sum(clean) / len(clean) if clean else math.nan


def _parse_csv(text: str | None) -> list[str]:
    if not text:
        return []
    return [item.strip() for item in str(text).split(",") if item.strip()]


def _read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def _check_wall(started: float, max_wall_seconds: float) -> None:
    if time.monotonic() - started >= float(max_wall_seconds):
        raise Track15Halt("HALT_WALL_CLOCK", "wall clock limit reached at checkpoint")


def _enforce_resume_guard(state: dict[str, Any], *, resume: bool) -> None:
    status = str(state.get("final_status") or "")
    if resume and status in TERMINAL_STATUSES:
        raise Track15Halt(status, f"refusing to resume terminal Track15 state {status}")


def _git_fetch() -> dict[str, Any]:
    proc = subprocess.run(["git", "fetch", "origin", "dr-x86"], text=True, capture_output=True, check=False)
    return {"returncode": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}


def _git_status_paths(paths: tuple[str, ...] | list[str]) -> list[str]:
    proc = subprocess.run(["git", "status", "--short", "--", *paths], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return [f"git status failed: {proc.stderr.strip()}"]
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _track_a_report(track_a: dict[str, Any]) -> str:
    stats = track_a.get("summary") or {}
    return "\n".join(
        [
            "# Track A Fair Baselines Report",
            "",
            f"Verdict: {track_a.get('verdict')}",
            f"Reason: {track_a.get('reason')}",
            f"Strong vs plain mean gain: {stats.get('strong_vs_plain_mean_gain_pct')}",
            f"Strong vs weakest weak-baseline mean gain: {stats.get('strong_vs_weak_min_mean_gain_pct')}",
            f"Rows: {stats.get('row_count')}",
        ]
    )


def _track_b_report(track_b: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Track B Dynamic DR Report",
            "",
            f"Verdict: {track_b.get('verdict')}",
            f"Reason: {track_b.get('reason')}",
            f"Rows: {track_b.get('row_count')}",
        ]
    )


def _final_report(state: dict[str, Any]) -> str:
    track_a = state.get("trackA") or {}
    track_b = state.get("trackB") or {}
    stats = track_a.get("summary") or {}
    return "\n".join(
        [
            "# Final Track15 Report",
            "",
            f"Final status: {state.get('final_status')}",
            f"Final reason: {state.get('final_reason')}",
            "",
            "## Track A",
            f"Verdict: {track_a.get('verdict', 'NOT_RUN')}",
            f"Reason: {track_a.get('reason', '')}",
            f"Strong beats plain mean gain: {stats.get('strong_vs_plain_mean_gain_pct', 'NA')}",
            f"Strong beats weak baselines min mean gain: {stats.get('strong_vs_weak_min_mean_gain_pct', 'NA')}",
            "",
            "## Track B",
            f"Verdict: {track_b.get('verdict', 'NOT_RUN')}",
            f"Reason: {track_b.get('reason', '')}",
            "",
            "## Decision",
            "DR-static remains excluded from claims. Track A is publishable only if baselines pass health and the strong-method margin is real. Track B is not a DR win unless a real dynamic DR-online policy beats rolling ALNS.",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Final Track15 fair-baseline and dynamic-DR runner.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    parser.add_argument("--require-self-py313", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--min-free-disk-gb", type=float, default=10.0)
    parser.add_argument("--bundles", default=",".join(DEFAULT_BUNDLES))
    parser.add_argument("--seeds", default="901,902,903,904,905,906,907,908,909,910")
    parser.add_argument("--baseline-algorithms", default="GA,PSO,ACO,IWD,VNS,GWO,SA")
    parser.add_argument("--eval-budget", type=int, default=16_000)
    parser.add_argument("--max-runtime-seconds", type=float, default=900.0)
    parser.add_argument("--max-wall-seconds", type=float, default=8 * 3600.0)
    parser.add_argument("--min-eval-ratio", type=float, default=0.90)
    parser.add_argument("--strong-plain-threshold-pct", type=float, default=2.0)
    parser.add_argument("--weak-win-threshold-pct", type=float, default=10.0)
    parser.add_argument("--dynamic-bundles", type=int, default=1)
    parser.add_argument("--dynamic-seeds", default="951,952")
    parser.add_argument("--dynamic-eval-budget", type=int, default=1000)
    parser.add_argument("--dynamic-max-runtime-seconds", type=float, default=120.0)
    parser.add_argument("--dynamic-stage-eval-budget", type=int, default=1000)
    parser.add_argument("--dynamic-stage-max-runtime-seconds", type=float, default=90.0)
    parser.add_argument("--dynamic-stages", type=int, default=3)
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
