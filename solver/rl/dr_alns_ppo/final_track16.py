from __future__ import annotations

import argparse
import csv
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
from setp_solver.search.candidates import make_shared_initial_solution, run_candidate, solution_signature_hash
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.search.metaheuristic_baselines import BASELINE_ALGORITHMS, run_metaheuristic_baseline, solution_to_dict
from setp_solver.search.winner_operators import (
    WinnerKernelConfig,
    _run_winner_variant,
    e2_alns_sa_acceptance_flags,
    e2_alns_scan_bridge_flags,
    e2_alns_variant_flags,
    winner_variant_flags,
    run_winner_kernel,
)

from .pilot20_learned_destroy_phaseA import DEFAULT_WORKER, REQUIRED_WORKER_NUMPY, _parse_int_list
from .pilot22_grounded_fixes import _git_snapshot, _load_state, _log, _run_python_json, _save_state, _write_json


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track16")
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
    "HALT_MAIN_NOT_STRONG",
    "HALT_PREFLIGHT",
    "HALT_WALL_CLOCK",
    "HALT_PROTECTED_DIRTY",
    "STOP_AFTER_BASELINE_HEALTH",
    "STOP_AFTER_METHOD_ABLATION",
}
TRACK15_FROZEN_CONCLUSION = (
    "Track15 is frozen as non-publishable evidence: static DR is not a mainline claim, "
    "the assembled strong_method is rejected because it underperformed the plain/winner anchor, "
    "and PSO returned the warm-start solution after full-budget attempts."
)


class Track16Halt(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "track16_progress.log"
    state_path = output_dir / "track16_state.json"
    state = _load_state(state_path) if args.resume else {}
    started = time.monotonic()
    final_status = str(state.get("final_status") or "RUNNING")
    final_reason = str(state.get("final_reason") or "")
    try:
        _enforce_resume_guard(state, resume=bool(args.resume))
        _log(progress_path, "Track16 start")
        preflight = run_preflight(args, output_dir)
        os.environ["SETP_WORKER_PYTHON"] = str(Path(args.worker_python).resolve())
        state["preflight"] = preflight
        _save_state(state_path, state)

        if not state.get("baseline_health_done"):
            health = run_baseline_health(args, output_dir, progress_path, started)
            state["baseline_health"] = health
            state["baseline_health_done"] = True
            _save_state(state_path, state)
            _write_json(output_dir / "track16_baseline_health_report.json", health)
            _write_text(output_dir / "track16_baseline_health_report.md", _baseline_health_report(health))
            if health["verdict"] == "HALT_BASELINE_NOT_RUNNING":
                raise Track16Halt(health["verdict"], health["reason"])
            if args.stop_after == "baseline_health":
                final_status = "STOP_AFTER_BASELINE_HEALTH"
                final_reason = "Stopped after Track16 baseline health stage by request."
                state["final_status"] = final_status
                state["final_reason"] = final_reason
                return 0

        if not state.get("method_ablation_done"):
            ablation = run_method_ablation(args, output_dir, progress_path, started)
            state["method_ablation"] = ablation
            state["method_ablation_done"] = True
            _save_state(state_path, state)
            _write_json(output_dir / "track16_method_ablation_report.json", ablation)
            _write_text(output_dir / "track16_method_ablation_report.md", _method_ablation_report(ablation))
            if ablation["verdict"] == "HALT_MAIN_NOT_STRONG":
                raise Track16Halt(ablation["verdict"], ablation["reason"])
            if args.stop_after == "method_ablation":
                final_status = "STOP_AFTER_METHOD_ABLATION"
                final_reason = "Stopped after Track16 method ablation stage by request."
                state["final_status"] = final_status
                state["final_reason"] = final_reason
                return 0

        if not state.get("fair_comparison_done"):
            fair = run_fair_comparison(args, output_dir, progress_path, state, started)
            state["fair_comparison"] = fair
            state["fair_comparison_done"] = True
            _save_state(state_path, state)
            _write_json(output_dir / "track16_fair_comparison_report.json", fair)
            _write_text(output_dir / "track16_fair_comparison_report.md", _fair_comparison_report(fair))

        final = summarize_final(state)
        final_status = final["final_status"]
        final_reason = final["final_reason"]
        state.update(final)
        return 0 if final_status in {"WIN_REAL", "MARGIN_SMALL"} else 2
    except Track16Halt as exc:
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
        final_reason = _canonical_final_reason(state, final_status, final_reason)
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        state["wall_time_seconds"] = float(time.monotonic() - started)
        _ensure_not_run_artifacts(output_dir, state)
        _save_state(state_path, state)
        _write_json(output_dir / "final_report.json", state)
        final_text = _final_report(state)
        _write_text(output_dir / "final_report.md", final_text)
        _write_text(Path("final_report.md"), final_text)


def run_preflight(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    protected_status = _git_status_paths(PROTECTED_FILES)
    if protected_status:
        raise Track16Halt("HALT_PROTECTED_DIRTY", f"protected files are dirty before run: {protected_status}")
    worker_python = Path(args.worker_python).resolve()
    if not worker_python.exists():
        raise Track16Halt("HALT_PREFLIGHT", f"py313 worker missing: {worker_python}")
    worker = _run_python_json(
        worker_python,
        "import json,sys,numpy; print(json.dumps({'exe':sys.executable,'version':sys.version.split()[0],'numpy':numpy.__version__}))",
    )
    if str(worker.get("numpy")) != REQUIRED_WORKER_NUMPY:
        raise Track16Halt("HALT_PREFLIGHT", f"worker NumPy drift: {worker.get('numpy')} != {REQUIRED_WORKER_NUMPY}")
    if bool(args.require_self_py313) and Path(sys.executable).resolve() != worker_python:
        raise Track16Halt("HALT_PREFLIGHT", f"runner must execute under py313 worker: {sys.executable} != {worker_python}")
    free_gb = shutil.disk_usage(output_dir.resolve().anchor or ".").free / (1024.0**3)
    if free_gb < float(args.min_free_disk_gb):
        raise Track16Halt("HALT_PREFLIGHT", f"free disk {free_gb:.1f}GB < {args.min_free_disk_gb}GB")
    bundle_paths = sorted(set(_parse_csv(args.health_bundles) + _parse_csv(args.ablation_bundles) + _parse_csv(args.formal_bundles)))
    missing = [path for path in bundle_paths if not Path(path).exists()]
    if missing:
        raise Track16Halt("HALT_PREFLIGHT", f"bundle missing: {missing}")
    return {
        "git": _git_snapshot(),
        "git_fetch": _git_fetch(),
        "worker": worker,
        "runner_executable": sys.executable,
        "disk_free_gb": free_gb,
        "protected_status": protected_status,
        "track15_frozen_conclusion": TRACK15_FROZEN_CONCLUSION,
    }


def run_baseline_health(args: argparse.Namespace, output_dir: Path, progress_path: Path, started: float) -> dict[str, Any]:
    rows_path = output_dir / "track16_baseline_health_matrix.csv"
    rows = _read_rows(rows_path) if args.resume and rows_path.exists() else []
    done = {(row["bundle"], int(row["seed"]), row["algorithm"]) for row in rows}
    bundles = _parse_csv(args.health_bundles)
    seeds = _parse_int_list(args.health_seeds)
    algorithms = _parse_csv(args.baseline_algorithms) or list(BASELINE_ALGORITHMS)
    for bundle_dir in bundles:
        bundle_name = Path(bundle_dir).name
        warm = _warm_start_metrics(bundle_dir)
        for seed in seeds:
            for algorithm in algorithms:
                key = (bundle_name, int(seed), algorithm)
                if key in done:
                    continue
                _check_wall(started, args.max_wall_seconds)
                _log(progress_path, f"Stage1 baseline health bundle={bundle_name} seed={seed} algorithm={algorithm}")
                row, _solution = _run_baseline_algorithm(bundle_dir, algorithm, seed=int(seed), args=args, warm=warm, stage="baseline_health")
                row["bundle"] = bundle_name
                row["bundle_dir"] = str(bundle_dir)
                row["seed"] = int(seed)
                rows.append(row)
                _write_rows(rows_path, rows)
                if row["health_status"] != "HEALTHY":
                    return {
                        "verdict": "HALT_BASELINE_NOT_RUNNING",
                        "reason": f"{algorithm} failed health on {bundle_name}/seed{seed}: {row['health_status']} {row.get('failure_reason', '')}",
                        "rows": rows,
                        "healthy_algorithms": _healthy_algorithms(rows),
                        "diagnosis": _baseline_failure_diagnosis(row),
                    }
    return {
        "verdict": "BASELINES_HEALTHY",
        "reason": "All requested baseline health rows passed.",
        "rows": rows,
        "healthy_algorithms": _healthy_algorithms(rows),
        "diagnosis": "",
    }


def run_method_ablation(args: argparse.Namespace, output_dir: Path, progress_path: Path, started: float) -> dict[str, Any]:
    rows_path = output_dir / "track16_method_ablation_rows.csv"
    rows = _read_rows(rows_path) if args.resume and rows_path.exists() else []
    done = {(row["bundle"], int(row["seed"]), row["algorithm"]) for row in rows}
    bundles = _parse_csv(args.ablation_bundles)
    seeds = _parse_int_list(args.ablation_seeds)
    methods = _parse_csv(args.method_algorithms)
    solutions_dir = output_dir / "track16_method_solutions"
    solutions_dir.mkdir(parents=True, exist_ok=True)
    for bundle_dir in bundles:
        bundle_name = Path(bundle_dir).name
        warm = _warm_start_metrics(bundle_dir)
        for seed in seeds:
            for method in methods:
                key = (bundle_name, int(seed), method)
                if key in done:
                    continue
                _check_wall(started, args.max_wall_seconds)
                _log(progress_path, f"Stage2 method ablation bundle={bundle_name} seed={seed} method={method}")
                row, solution = _run_method(bundle_dir, method, seed=int(seed), args=args, warm=warm, stage="method_ablation")
                row["bundle"] = bundle_name
                row["bundle_dir"] = str(bundle_dir)
                row["seed"] = int(seed)
                rows.append(row)
                _write_rows(rows_path, rows)
                if solution is not None:
                    _write_json(solutions_dir / f"{bundle_name}_seed{seed}_{method}.json", solution_to_dict(solution))
    summary = _method_summary(rows)
    chosen = choose_main_method(rows, default=args.default_main_method)
    summary["chosen_main_method"] = chosen
    anchor_gain = _gain_vs_anchor(rows, chosen, anchors=("plain_alns", "winner_kernel"))
    if not math.isfinite(anchor_gain) or anchor_gain <= float(args.main_anchor_threshold_pct):
        return {
            "verdict": "HALT_MAIN_NOT_STRONG",
            "reason": f"{chosen} does not beat the plain/winner anchor by > {args.main_anchor_threshold_pct}% (mean gain {anchor_gain}).",
            "rows": rows,
            "summary": summary,
        }
    return {
        "verdict": "MAIN_METHOD_SELECTED",
        "reason": f"{chosen} selected by lowest validation mean and beats anchors by {anchor_gain:.3f}%.",
        "rows": rows,
        "summary": summary,
    }


def run_fair_comparison(args: argparse.Namespace, output_dir: Path, progress_path: Path, state: dict[str, Any], started: float) -> dict[str, Any]:
    rows_path = output_dir / "track16_rows.csv"
    rows = _read_rows(rows_path) if args.resume and rows_path.exists() else []
    done = {(row["bundle"], int(row["seed"]), row["algorithm"]) for row in rows}
    health = state.get("baseline_health") or {}
    healthy_algorithms = list(health.get("healthy_algorithms") or _parse_csv(args.baseline_algorithms))
    chosen = str(((state.get("method_ablation") or {}).get("summary") or {}).get("chosen_main_method") or args.default_main_method)
    algorithms = [chosen, *healthy_algorithms]
    for bundle_dir in _parse_csv(args.formal_bundles):
        bundle_name = Path(bundle_dir).name
        warm = _warm_start_metrics(bundle_dir)
        for seed in _parse_int_list(args.formal_seeds):
            for algorithm in algorithms:
                key = (bundle_name, int(seed), algorithm)
                if key in done:
                    continue
                _check_wall(started, args.max_wall_seconds)
                _log(progress_path, f"Stage3 fair comparison bundle={bundle_name} seed={seed} algorithm={algorithm}")
                if algorithm == chosen:
                    row, solution = _run_method(bundle_dir, algorithm, seed=int(seed), args=args, warm=warm, stage="fair_comparison")
                else:
                    row, solution = _run_baseline_algorithm(bundle_dir, algorithm, seed=int(seed), args=args, warm=warm, stage="fair_comparison")
                row["bundle"] = bundle_name
                row["bundle_dir"] = str(bundle_dir)
                row["seed"] = int(seed)
                rows.append(row)
                _write_rows(rows_path, rows)
                if row.get("role") == "weak_baseline" and row.get("health_status") != "HEALTHY":
                    return {
                        "verdict": "HALT_BASELINE_NOT_RUNNING",
                        "reason": f"{algorithm} failed formal health on {bundle_name}/seed{seed}: {row['health_status']}",
                        "rows": rows,
                        "summary": _fair_summary(rows, chosen, healthy_algorithms),
                    }
                _ = solution
    summary = _fair_summary(rows, chosen, healthy_algorithms)
    min_gain = float(summary.get("min_mean_gain_vs_baseline_pct", math.nan))
    zero_violations = bool(summary.get("zero_violations", False))
    all_significant = bool(summary.get("all_wilcoxon_significant", False))
    no_reverse_scale = bool(summary.get("no_reverse_scale", False))
    if zero_violations and min_gain >= float(args.weak_win_threshold_pct) and all_significant and no_reverse_scale:
        verdict = "WIN_REAL"
        reason = f"{chosen} beats every healthy baseline by at least {min_gain:.3f}% mean with paired Wilcoxon support."
    else:
        verdict = "MARGIN_SMALL"
        reason = f"Fair comparison completed, but 10% claim is not proven: min_gain={min_gain}, wilcoxon={all_significant}, zero_violations={zero_violations}, no_reverse_scale={no_reverse_scale}."
    return {"verdict": verdict, "reason": reason, "rows": rows, "summary": summary}


def summarize_final(state: dict[str, Any]) -> dict[str, str]:
    for key in ("baseline_health", "method_ablation", "fair_comparison"):
        stage = state.get(key) or {}
        verdict = str(stage.get("verdict") or "")
        if verdict in {"HALT_BASELINE_NOT_RUNNING", "HALT_MAIN_NOT_STRONG"}:
            return {"final_status": verdict, "final_reason": str(stage.get("reason", ""))}
    fair = state.get("fair_comparison") or {}
    if fair.get("verdict") == "WIN_REAL":
        return {"final_status": "WIN_REAL", "final_reason": str(fair.get("reason", ""))}
    if fair.get("verdict") == "MARGIN_SMALL":
        return {"final_status": "MARGIN_SMALL", "final_reason": str(fair.get("reason", ""))}
    return {"final_status": "HALT_INCOMPLETE", "final_reason": "Track16 did not reach a fair-comparison verdict."}


def baseline_health(row: dict[str, Any], *, min_eval_ratio: float = 0.9, min_unique_solutions: int = 2) -> str:
    if not bool(row.get("feasible", False)) or int(row.get("violation_count", 1) or 0) != 0:
        return "UNHEALTHY_VIOLATION"
    if float(row.get("eval_ratio", 0.0) or 0.0) < float(min_eval_ratio):
        return "UNHEALTHY_UNDER_EVAL"
    if bool(row.get("returned_warm_start", False)):
        return "UNHEALTHY_WARM_HASH"
    if int(row.get("unique_solution_count", 0) or 0) < int(min_unique_solutions):
        return "UNHEALTHY_NO_DIVERSITY"
    if int(row.get("best_update_count", 0) or 0) <= 0:
        return "UNHEALTHY_NO_BEST_UPDATE"
    if float(row.get("improvement_vs_warm_pct", 0.0) or 0.0) <= 0.0:
        return "UNHEALTHY_NO_IMPROVEMENT"
    return "HEALTHY"


def _run_baseline_algorithm(bundle_dir: str, algorithm: str, *, seed: int, args: argparse.Namespace, warm: dict[str, Any], stage: str) -> tuple[dict[str, Any], Any]:
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
        diagnostics = getattr(run, "search_diagnostics", {}) or {}
        row = {
            "stage": stage,
            "algorithm": "SA",
            "role": "weak_baseline",
            "status": run.status,
            "actual_evals": int(run.evals),
            "elapsed_seconds": float(run.elapsed_seconds),
            "best_cost": float(run.best_cost) if run.best_cost is not None else math.nan,
            "solution_hash": solution_signature_hash(solution) if solution is not None else "",
            "violation_count": len(violations),
            "feasible": solution is not None and not violations,
            "failure_reason": "",
            "operator_counts": json.dumps(getattr(run, "operator_counts", {}), sort_keys=True, default=str),
            "unique_solution_count": _candidate_unique_count_from_diagnostics(diagnostics, solution is not None),
            "best_update_count": int(diagnostics.get("best_updates", 0) or max(0, len(getattr(run, "history", []) or []) - 1)),
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
        diagnostics = dict(result.diagnostics or {})
        row = {
            "stage": stage,
            "algorithm": result.algorithm,
            "role": "weak_baseline",
            "status": result.status,
            "actual_evals": int(result.evals),
            "elapsed_seconds": float(result.elapsed_seconds),
            "best_cost": float(result.best_cost) if result.best_cost is not None else math.nan,
            "solution_hash": result.solution_signature_hash,
            "violation_count": int(result.violation_count),
            "feasible": bool(result.feasible),
            "failure_reason": result.failure_reason,
            "operator_counts": json.dumps(result.operator_counts, sort_keys=True, default=str),
            "unique_solution_count": int(diagnostics.get("unique_solution_count", 0) or 0),
            "best_update_count": int(diagnostics.get("best_update_count", 0) or 0),
            "candidate_objective_min": _to_float(diagnostics.get("candidate_objective_min")),
            "candidate_objective_mean": _to_float(diagnostics.get("candidate_objective_mean")),
            "candidate_objective_max": _to_float(diagnostics.get("candidate_objective_max")),
            "feasible_candidate_count": int(diagnostics.get("feasible_candidate_count", 0) or 0),
            "candidates_better_than_warm": int(diagnostics.get("candidates_better_than_warm", 0) or 0),
        }
    _fill_common_row_fields(row, warm=warm, eval_budget=int(args.eval_budget), max_runtime_seconds=float(args.max_runtime_seconds))
    row["health_status"] = baseline_health(row, min_eval_ratio=float(args.min_eval_ratio), min_unique_solutions=int(args.min_unique_solution_count))
    row["diagnosis"] = _baseline_failure_diagnosis(row)
    row["wall_elapsed_seconds"] = float(time.perf_counter() - started)
    return row, solution


def _run_method(bundle_dir: str, method: str, *, seed: int, args: argparse.Namespace, warm: dict[str, Any], stage: str) -> tuple[dict[str, Any], Any]:
    method = str(method)
    if method == "plain_alns":
        run = run_candidate(
            "ALNS-Wouda",
            bundle_dir,
            seed=int(seed),
            eval_budget=int(args.eval_budget),
            max_runtime_seconds=float(args.max_runtime_seconds),
            initial_solution=warm["solution"],
        )
        solution = run.best_solution
        violations = check_solution(solution, load_search_bundle(bundle_dir).instance, DEFAULT_PRICES) if solution is not None else ["no-solution"]
        row = {
            "stage": stage,
            "algorithm": method,
            "role": "method",
            "status": run.status,
            "actual_evals": int(run.evals),
            "elapsed_seconds": float(run.elapsed_seconds),
            "best_cost": float(run.best_cost) if run.best_cost is not None else math.nan,
            "solution_hash": solution_signature_hash(solution) if solution is not None else "",
            "violation_count": len(violations),
            "feasible": solution is not None and not violations,
            "failure_reason": "",
            "variant": "native_alns_wouda",
            "flags": "{}",
            "operator_counts": json.dumps(getattr(run, "operator_counts", {}), sort_keys=True, default=str),
            "unique_solution_count": 1,
            "best_update_count": max(0, len(getattr(run, "history", []) or []) - 1),
        }
    else:
        config, flags, variant_id = _method_config(method, seed=seed, args=args)
        run = _run_winner_variant(bundle_dir, config, initial_solution=warm["solution"], variant_flags=flags, variant_id=variant_id) if flags is not None else run_winner_kernel(bundle_dir, config=config, initial_solution=warm["solution"])
        solution = run["best_solution"]
        row = {
            "stage": stage,
            "algorithm": method,
            "role": "method",
            "status": "OK" if run.get("feasible") else "HALT_INFEASIBLE",
            "actual_evals": int(run.get("evaluations", 0) or 0),
            "elapsed_seconds": float(run.get("elapsed_seconds", 0.0) or 0.0),
            "best_cost": float(run.get("best_cost", math.nan)),
            "solution_hash": solution_signature_hash(solution),
            "violation_count": int(run.get("violation_count", 0) or 0),
            "feasible": bool(run.get("feasible", False)),
            "failure_reason": "",
            "variant": run.get("variant", variant_id),
            "flags": json.dumps(run.get("flags", flags or {}), sort_keys=True),
            "operator_counts": json.dumps(run.get("operator_counts", {}), sort_keys=True, default=str),
            "unique_solution_count": max(1, len(run.get("history", []) or [])),
            "best_update_count": max(0, len(run.get("history", []) or []) - 1),
        }
    _fill_common_row_fields(row, warm=warm, eval_budget=int(args.eval_budget), max_runtime_seconds=float(args.max_runtime_seconds))
    row["health_status"] = "NOT_BASELINE_GATE"
    return row, solution


def _method_config(method: str, *, seed: int, args: argparse.Namespace) -> tuple[WinnerKernelConfig, dict[str, str] | None, str]:
    base = WinnerKernelConfig(seed=int(seed), eval_budget=int(args.eval_budget), max_runtime_seconds=float(args.max_runtime_seconds))
    if method == "winner_kernel":
        return base, None, "winner_kernel"
    if method == "winner_kernel_local_search":
        flags = winner_variant_flags()
        flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"] = "1"
        return base, flags, "winner_kernel_local_search"
    if method == "winner_kernel_charging_required":
        return WinnerKernelConfig(**{**base.__dict__, "require_charging_signal": True}), winner_variant_flags(), "winner_kernel_charging_required"
    if method == "winner_kernel_true_repair_adaptive_q":
        flags = e2_alns_variant_flags()
        return WinnerKernelConfig(**{**base.__dict__, "include_route_elimination": flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"] == "1"}), flags, "winner_kernel_true_repair_adaptive_q"
    if method == "winner_kernel_scan_bridge":
        flags = e2_alns_scan_bridge_flags()
        return WinnerKernelConfig(**{**base.__dict__, "include_route_elimination": flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"] == "1"}), flags, "winner_kernel_scan_bridge"
    if method == "winner_kernel_sa_lns_cooling":
        flags = e2_alns_sa_acceptance_flags(mode="lns_cooling")
        return WinnerKernelConfig(**{**base.__dict__, "include_route_elimination": flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"] == "1"}), flags, "winner_kernel_sa_lns_cooling"
    raise ValueError(f"unknown Track16 method: {method}")


def choose_main_method(rows: list[dict[str, Any]], *, default: str = "winner_kernel") -> str:
    means: dict[str, list[float]] = {}
    for row in rows:
        if row.get("role") != "method" or not bool(row.get("feasible", False)):
            continue
        cost = _to_float(row.get("best_cost"))
        if math.isfinite(cost):
            means.setdefault(str(row.get("algorithm")), []).append(cost)
    if not means:
        return default
    return min(means, key=lambda name: (_mean(means[name]), name))


def _method_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_method: dict[str, list[float]] = {}
    for row in rows:
        if row.get("role") == "method":
            cost = _to_float(row.get("best_cost"))
            if math.isfinite(cost):
                by_method.setdefault(str(row.get("algorithm")), []).append(cost)
    return {
        "row_count": len(rows),
        "mean_cost_by_method": {name: _mean(values) for name, values in by_method.items()},
        "zero_violations": all(int(row.get("violation_count", 1) or 0) == 0 for row in rows),
    }


def _fair_summary(rows: list[dict[str, Any]], main_method: str, baseline_algorithms: list[str]) -> dict[str, Any]:
    gains: dict[str, list[float]] = {algorithm: [] for algorithm in baseline_algorithms}
    scale_gains: dict[str, dict[str, list[float]]] = {}
    p_values: dict[str, float] = {}
    for algorithm in baseline_algorithms:
        main_costs, base_costs = _paired_costs(rows, main_method, algorithm)
        for main, base in zip(main_costs, base_costs):
            if base > 0:
                gains.setdefault(algorithm, []).append((base - main) / base * 100.0)
        p_values[algorithm] = _wilcoxon_pvalue(main_costs, base_costs)
    for bundle in sorted({str(row.get("bundle")) for row in rows if row.get("bundle")}):
        scale_gains[bundle] = {}
        for algorithm in baseline_algorithms:
            main_costs, base_costs = _paired_costs([row for row in rows if str(row.get("bundle")) == bundle], main_method, algorithm)
            vals = [(base - main) / base * 100.0 for main, base in zip(main_costs, base_costs) if base > 0]
            scale_gains[bundle][algorithm] = vals
    mean_gains = {algorithm: _mean(values) for algorithm, values in gains.items()}
    return {
        "main_method": main_method,
        "row_count": len(rows),
        "mean_gain_vs_baseline_pct": mean_gains,
        "median_gain_vs_baseline_pct": {algorithm: _median(values) for algorithm, values in gains.items()},
        "min_mean_gain_vs_baseline_pct": min(mean_gains.values()) if mean_gains else math.nan,
        "wilcoxon_p_values": p_values,
        "all_wilcoxon_significant": all(math.isfinite(value) and value <= 0.05 for value in p_values.values()) if p_values else False,
        "scale_mean_gains": {bundle: {algorithm: _mean(values) for algorithm, values in algs.items()} for bundle, algs in scale_gains.items()},
        "no_reverse_scale": all(_mean(values) >= -1e-9 for algs in scale_gains.values() for values in algs.values() if values),
        "zero_violations": all(int(row.get("violation_count", 1) or 0) == 0 for row in rows),
        "failure_instance_count": sum(1 for row in rows if row.get("status") not in {"OK", "feasible"}),
    }


def _paired_costs(rows: list[dict[str, Any]], left_algorithm: str, right_algorithm: str) -> tuple[list[float], list[float]]:
    by_key: dict[tuple[str, int], dict[str, float]] = {}
    for row in rows:
        cost = _to_float(row.get("best_cost"))
        if not math.isfinite(cost):
            continue
        key = (str(row.get("bundle")), int(row.get("seed", 0) or 0))
        by_key.setdefault(key, {})[str(row.get("algorithm"))] = cost
    left: list[float] = []
    right: list[float] = []
    for costs in by_key.values():
        if left_algorithm in costs and right_algorithm in costs:
            left.append(costs[left_algorithm])
            right.append(costs[right_algorithm])
    return left, right


def _gain_vs_anchor(rows: list[dict[str, Any]], method: str, anchors: tuple[str, ...]) -> float:
    gains: list[float] = []
    for anchor in anchors:
        main, base = _paired_costs(rows, method, anchor)
        gains.extend((b - m) / b * 100.0 for m, b in zip(main, base) if b > 0)
    return _mean(gains)


def _wilcoxon_pvalue(main_costs: list[float], baseline_costs: list[float]) -> float:
    if len(main_costs) < 2 or len(main_costs) != len(baseline_costs):
        return math.nan
    try:
        from scipy.stats import wilcoxon
    except Exception:
        return math.nan
    try:
        result = wilcoxon(main_costs, baseline_costs, alternative="less", zero_method="wilcox")
    except ValueError:
        return math.nan
    return float(result.pvalue)


def _healthy_algorithms(rows: list[dict[str, Any]]) -> list[str]:
    health: dict[str, bool] = {}
    for row in rows:
        algorithm = str(row.get("algorithm"))
        health[algorithm] = health.get(algorithm, True) and row.get("health_status") == "HEALTHY"
    return [algorithm for algorithm, ok in health.items() if ok]


def _candidate_unique_count_from_diagnostics(diagnostics: dict[str, Any], has_solution: bool) -> int:
    changed = int(diagnostics.get("candidate_changed", 0) or 0)
    accepted_changed = int(diagnostics.get("accepted_changed", 0) or 0)
    best_updates = int(diagnostics.get("best_updates", 0) or 0)
    if changed > 0 or accepted_changed > 0 or best_updates > 0:
        return max(2, best_updates + 1)
    return 1 if has_solution else 0


def _baseline_failure_diagnosis(row: dict[str, Any]) -> str:
    if row.get("health_status") == "HEALTHY":
        return ""
    if bool(row.get("returned_warm_start", False)):
        unique = int(row.get("unique_solution_count", 0) or 0)
        if unique <= 1:
            return "decoded_solution_hash_collapsed_to_warm_start"
        if row.get("candidates_better_than_warm") is not None and int(row.get("candidates_better_than_warm", 0) or 0) <= 0:
            return "candidate_hashes_varied_but_all_scored_candidates_worse_than_warm"
        return "candidate_hashes_varied_but_global_best_never_improved"
    if int(row.get("best_update_count", 0) or 0) <= 0:
        return "score_ran_but_best_update_count_is_zero"
    if float(row.get("eval_ratio", 0.0) or 0.0) < 0.9:
        return "runtime_or_budget_under_eval"
    return "health_gate_failed"


def _fill_common_row_fields(row: dict[str, Any], *, warm: dict[str, Any], eval_budget: int, max_runtime_seconds: float) -> None:
    best_cost = _to_float(row.get("best_cost"))
    warm_cost = float(warm["cost"])
    row["eval_budget"] = int(eval_budget)
    row["eval_ratio"] = float(row.get("actual_evals", 0) or 0) / max(1, int(eval_budget))
    row["max_runtime_seconds"] = float(max_runtime_seconds)
    row["warm_start_cost"] = warm_cost
    row["warm_hash"] = warm["hash"]
    row["warm_start_hash"] = warm["hash"]
    row["returned_warm_start"] = str(row.get("solution_hash", "")) == str(warm["hash"])
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


def _baseline_health_report(health: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Track16 Baseline Health Report",
            "",
            f"Verdict: {health.get('verdict')}",
            f"Reason: {health.get('reason')}",
            f"Diagnosis: {health.get('diagnosis', '')}",
            f"Healthy algorithms: {', '.join(health.get('healthy_algorithms') or [])}",
            "",
            TRACK15_FROZEN_CONCLUSION,
        ]
    )


def _method_ablation_report(ablation: dict[str, Any]) -> str:
    summary = ablation.get("summary") or {}
    return "\n".join(
        [
            "# Track16 Method Ablation Report",
            "",
            f"Verdict: {ablation.get('verdict')}",
            f"Reason: {ablation.get('reason')}",
            f"Chosen main method: {summary.get('chosen_main_method')}",
            f"Mean costs: {json.dumps(summary.get('mean_cost_by_method', {}), sort_keys=True)}",
        ]
    )


def _fair_comparison_report(fair: dict[str, Any]) -> str:
    summary = fair.get("summary") or {}
    return "\n".join(
        [
            "# Track16 Fair Comparison Report",
            "",
            f"Verdict: {fair.get('verdict')}",
            f"Reason: {fair.get('reason')}",
            f"Main method: {summary.get('main_method')}",
            f"Mean gains: {json.dumps(summary.get('mean_gain_vs_baseline_pct', {}), sort_keys=True)}",
            f"Wilcoxon p-values: {json.dumps(summary.get('wilcoxon_p_values', {}), sort_keys=True)}",
        ]
    )


def _ensure_not_run_artifacts(output_dir: Path, state: dict[str, Any]) -> None:
    if "method_ablation" not in state:
        ablation = {
            "verdict": "NOT_RUN",
            "reason": "Skipped because Track16 halted before method ablation.",
            "rows": [],
            "summary": {"chosen_main_method": ""},
        }
        state["method_ablation"] = ablation
        _write_json(output_dir / "track16_method_ablation_report.json", ablation)
        _write_text(output_dir / "track16_method_ablation_report.md", _method_ablation_report(ablation))
    if "fair_comparison" not in state:
        fair = {
            "verdict": "NOT_RUN",
            "reason": "Skipped because Track16 halted before fair comparison.",
            "rows": [],
            "summary": {"main_method": "", "mean_gain_vs_baseline_pct": {}, "wilcoxon_p_values": {}},
        }
        state["fair_comparison"] = fair
        _write_json(output_dir / "track16_fair_comparison_report.json", fair)
        _write_text(output_dir / "track16_fair_comparison_report.md", _fair_comparison_report(fair))
    rows_path = output_dir / "track16_rows.csv"
    if not rows_path.exists():
        _write_text(
            rows_path,
            "stage,algorithm,role,status,actual_evals,best_cost,warm_start_cost,solution_hash,warm_hash,health_status,diagnosis\n",
        )


def _canonical_final_reason(state: dict[str, Any], final_status: str, fallback: str) -> str:
    for key in ("baseline_health", "method_ablation", "fair_comparison"):
        stage = state.get(key) or {}
        if stage.get("verdict") == final_status and stage.get("reason"):
            return str(stage["reason"])
    return fallback


def _final_report(state: dict[str, Any]) -> str:
    health = state.get("baseline_health") or {}
    ablation = state.get("method_ablation") or {}
    fair = state.get("fair_comparison") or {}
    fair_summary = fair.get("summary") or {}
    ablation_summary = ablation.get("summary") or {}
    return "\n".join(
        [
            "# Final Track16 Report",
            "",
            f"Final status: {state.get('final_status')}",
            f"Final reason: {state.get('final_reason')}",
            "",
            "## Frozen Track15 Evidence",
            TRACK15_FROZEN_CONCLUSION,
            "",
            "## Baseline Health",
            f"Verdict: {health.get('verdict', 'NOT_RUN')}",
            f"Reason: {health.get('reason', '')}",
            f"Healthy baselines: {', '.join(health.get('healthy_algorithms') or [])}",
            f"Diagnosis: {health.get('diagnosis', '')}",
            "",
            "## Method Ablation",
            f"Verdict: {ablation.get('verdict', 'NOT_RUN')}",
            f"Chosen main method: {ablation_summary.get('chosen_main_method', '')}",
            "",
            "## Fair Comparison",
            f"Verdict: {fair.get('verdict', 'NOT_RUN')}",
            f"Main method: {fair_summary.get('main_method', '')}",
            f"Min mean gain vs healthy baselines: {fair_summary.get('min_mean_gain_vs_baseline_pct', 'NA')}",
            "",
            "## Decision",
            "DR is excluded from the main claim. Quantitative claims may use only baselines that passed the Track16 health gate.",
        ]
    )


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


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _parse_csv(text: str | None) -> list[str]:
    if not text:
        return []
    return [item.strip() for item in str(text).split(",") if item.strip()]


def _mean(values: list[float]) -> float:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    return sum(clean) / len(clean) if clean else math.nan


def _median(values: list[float]) -> float:
    clean = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not clean:
        return math.nan
    mid = len(clean) // 2
    if len(clean) % 2:
        return clean[mid]
    return (clean[mid - 1] + clean[mid]) / 2.0


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _check_wall(started: float, max_wall_seconds: float) -> None:
    if time.monotonic() - started >= float(max_wall_seconds):
        raise Track16Halt("HALT_WALL_CLOCK", "wall clock limit reached at checkpoint")


def _enforce_resume_guard(state: dict[str, Any], *, resume: bool) -> None:
    status = str(state.get("final_status") or "")
    if resume and status in TERMINAL_STATUSES:
        raise Track16Halt(status, f"refusing to resume terminal Track16 state {status}")


def _git_fetch() -> dict[str, Any]:
    proc = subprocess.run(["git", "fetch", "origin", "dr-x86"], text=True, capture_output=True, check=False)
    return {"returncode": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}


def _git_status_paths(paths: tuple[str, ...] | list[str]) -> list[str]:
    proc = subprocess.run(["git", "status", "--short", "--", *paths], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return [f"git status failed: {proc.stderr.strip()}"]
    return [line for line in proc.stdout.splitlines() if line.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track16 health-gated fair ALNS/baseline comparison runner.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    parser.add_argument("--require-self-py313", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--min-free-disk-gb", type=float, default=10.0)
    parser.add_argument("--health-bundles", default=DEFAULT_BUNDLES[0])
    parser.add_argument("--ablation-bundles", default=DEFAULT_BUNDLES[0])
    parser.add_argument("--formal-bundles", default=",".join(DEFAULT_BUNDLES))
    parser.add_argument("--health-seeds", default="901")
    parser.add_argument("--ablation-seeds", default="901")
    parser.add_argument("--formal-seeds", default="901,902,903,904,905,906,907,908,909,910")
    parser.add_argument("--baseline-algorithms", default="GA,VNS,SA,GWO,ACO,IWD,PSO")
    parser.add_argument(
        "--method-algorithms",
        default="plain_alns,winner_kernel,winner_kernel_local_search,winner_kernel_charging_required,winner_kernel_true_repair_adaptive_q,winner_kernel_scan_bridge,winner_kernel_sa_lns_cooling",
    )
    parser.add_argument("--default-main-method", default="winner_kernel")
    parser.add_argument("--eval-budget", type=int, default=16_000)
    parser.add_argument("--max-runtime-seconds", type=float, default=900.0)
    parser.add_argument("--max-wall-seconds", type=float, default=8 * 3600.0)
    parser.add_argument("--min-eval-ratio", type=float, default=0.90)
    parser.add_argument("--min-unique-solution-count", type=int, default=2)
    parser.add_argument("--main-anchor-threshold-pct", type=float, default=0.0)
    parser.add_argument("--weak-win-threshold-pct", type=float, default=10.0)
    parser.add_argument("--stop-after", choices=("baseline_health", "method_ablation", "fair_comparison"), default="fair_comparison")
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
