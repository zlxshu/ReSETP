from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any

from .final_track16 import (
    Track16Halt,
    _check_wall,
    _fair_summary,
    _parse_csv,
    _read_rows,
    _run_baseline_algorithm,
    _run_method,
    _to_float,
    _warm_start_metrics,
    _write_rows,
    _write_text,
    run_preflight,
)
from .final_track17 import HEALTHY_BASELINES, METHOD_LABELS, TRACK17_FORMAL_BUNDLES
from .pilot20_learned_destroy_phaseA import DEFAULT_WORKER, _parse_int_list
from .pilot22_grounded_fixes import _load_state, _log, _save_state, _write_json


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track19")
TRACK17_ROWS = Path("solver/reports/dr_alns_ppo_v3/final_track17/track17_rows.csv")
DEFAULT_MAIN_METHOD = "winner_kernel_true_repair_adaptive_q"
DEFAULT_DIAGNOSTIC_METHODS = (
    DEFAULT_MAIN_METHOD,
    "plain_alns",
    "winner_kernel",
    "winner_kernel_local_search",
    "winner_kernel_charging_required",
    "winner_kernel_scan_bridge",
    "winner_kernel_sa_lns_cooling",
)
TERMINAL_STATUSES = {
    "WIN_REAL",
    "MARGIN_REAL",
    "HALT_100C_STILL_STARVED",
    "HALT_MAIN_100C_WEAK",
    "HALT_INVALID_COMPARISON",
    "HALT_PREFLIGHT",
    "HALT_PROTECTED_DIRTY",
}


class Track19Halt(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "track19_progress.log"
    state_path = output_dir / "track19_state.json"
    state = _load_state(state_path) if args.resume else {}
    started = time.monotonic()
    final_status = str(state.get("final_status") or "RUNNING")
    final_reason = str(state.get("final_reason") or "")
    try:
        _enforce_resume_guard(state, resume=bool(args.resume), force=bool(args.force))
        if bool(args.force):
            state["final_status"] = "RUNNING"
            state["final_reason"] = "Force recompute requested."
            if args.stop_after in {"calibration", "fair_comparison"}:
                state["calibration_done"] = False
            if args.stop_after in {"method_diagnostic", "fair_comparison"}:
                state["method_diagnostic_done"] = False
            if args.stop_after == "fair_comparison":
                state["fair_comparison_done"] = False
        _log(progress_path, "Track19 start")
        preflight = run_preflight(args, output_dir)
        os.environ["SETP_WORKER_PYTHON"] = str(Path(args.worker_python).resolve())
        state["preflight"] = preflight
        _save_state(state_path, state)

        if not state.get("budget_audit_done"):
            audit = run_stage0_budget_audit(args, output_dir)
            state["budget_audit"] = audit
            state["budget_audit_done"] = True
            _save_state(state_path, state)
            _write_json(output_dir / "track19_budget_audit.json", audit)
            _write_text(output_dir / "track19_budget_audit.md", _budget_audit_report(audit))

        if args.stop_after == "budget_audit":
            final_status = "STOP_AFTER_BUDGET_AUDIT"
            final_reason = "Stopped after Track19 budget audit."
            state["final_status"] = final_status
            state["final_reason"] = final_reason
            return 0

        if not state.get("calibration_done"):
            calibration = run_stage1_calibration(args, output_dir, progress_path, started)
            state["calibration"] = calibration
            state["calibration_done"] = True
            _save_state(state_path, state)
            _write_json(output_dir / "track19_100c_calibration.json", calibration)
            _write_text(output_dir / "track19_100c_calibration.md", _calibration_report(calibration))
            if calibration["verdict"] == "HALT_100C_STILL_STARVED":
                raise Track19Halt(calibration["verdict"], calibration["reason"])

        if args.stop_after == "calibration":
            final_status = "STOP_AFTER_CALIBRATION"
            final_reason = "Stopped after Track19 100c calibration."
            state["final_status"] = final_status
            state["final_reason"] = final_reason
            return 0

        if args.stop_after == "method_diagnostic" and not state.get("method_diagnostic_done"):
            diagnostic = run_stage1b_method_diagnostic(args, output_dir, progress_path, started)
            state["method_diagnostic"] = diagnostic
            state["method_diagnostic_done"] = True
            _save_state(state_path, state)
            _write_json(output_dir / "track19_100c_method_diagnostic.json", diagnostic)
            _write_text(output_dir / "track19_100c_method_diagnostic.md", _method_diagnostic_report(diagnostic))

        if args.stop_after == "method_diagnostic":
            diagnostic = state.get("method_diagnostic") or {}
            if diagnostic.get("verdict") == "DIAGNOSTIC_MAIN_100C_WEAK":
                final_status = "HALT_MAIN_100C_WEAK"
                final_reason = str(diagnostic.get("reason", "100c main method diagnostic found no moving Track19 candidate."))
            elif diagnostic.get("verdict") == "DIAGNOSTIC_RESELECT_MAIN":
                final_status = "HALT_RESELECT_MAIN_100C"
                final_reason = str(diagnostic.get("reason", "100c diagnostic rejected the current main method."))
            else:
                final_status = "STOP_AFTER_METHOD_DIAGNOSTIC"
                final_reason = "Stopped after Track19 100c method diagnostic."
            state["final_status"] = final_status
            state["final_reason"] = final_reason
            return 0 if final_status == "STOP_AFTER_METHOD_DIAGNOSTIC" else 2

        if not state.get("fair_comparison_done"):
            fair = run_stage2_fair_comparison(args, output_dir, progress_path, started)
            state["fair_comparison"] = fair
            state["fair_comparison_done"] = fair["verdict"] in {"WIN_REAL", "MARGIN_REAL"}
            _save_state(state_path, state)
            _write_json(output_dir / "track19_fair_report.json", fair)
            _write_text(output_dir / "track19_fair_report.md", _fair_report(fair))
            if fair["verdict"] in {"HALT_100C_STILL_STARVED", "HALT_INVALID_COMPARISON"}:
                raise Track19Halt(fair["verdict"], fair["reason"])

        final_status, final_reason = _summarize_final(state)
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        return 0 if final_status in {"WIN_REAL", "MARGIN_REAL"} else 2
    except Track16Halt as exc:
        final_status = exc.status
        final_reason = exc.message
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _log(progress_path, f"HALT {final_status}: {final_reason}")
        return 2
    except Track19Halt as exc:
        final_status = exc.status
        final_reason = exc.message
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _log(progress_path, f"HALT {final_status}: {final_reason}")
        return 2
    finally:
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        state["wall_time_seconds"] = float(time.monotonic() - started)
        _write_json(state_path, state)
        _write_json(output_dir / "final_report.json", state)
        _write_text(output_dir / "final_report.md", _final_report(state))
        _write_text(Path("final_report.md"), _final_report(state))


def run_stage0_budget_audit(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    source = Path(args.track17_rows)
    rows = _read_rows(source) if source.exists() else []
    audit_rows: list[dict[str, Any]] = []
    expected = [args.main_method, *_parse_csv(args.baseline_algorithms)]
    for algorithm in expected:
        matches = [
            row
            for row in rows
            if str(row.get("scale")) == "100" and int(row.get("seed", 0) or 0) == int(args.audit_seed) and str(row.get("algorithm")) == algorithm
        ]
        if matches:
            row = matches[-1]
            eval_ratio = _to_float(row.get("eval_ratio"))
            audit_rows.append(
                {
                    "source": str(source),
                    "algorithm": algorithm,
                    "seed": int(args.audit_seed),
                    "scale": "100",
                    "track17_status": row.get("status", ""),
                    "actual_evals": int(float(row.get("actual_evals", 0) or 0)),
                    "eval_budget": int(float(row.get("eval_budget", 0) or 0)),
                    "eval_ratio": eval_ratio,
                    "best_cost": _to_float(row.get("best_cost")),
                    "warm_start_cost": _to_float(row.get("warm_start_cost")),
                    "returned_warm_start": str(row.get("solution_hash")) == str(row.get("warm_hash")),
                    "unique_solution_count": int(float(row.get("unique_solution_count", 0) or 0)),
                    "best_update_count": int(float(row.get("best_update_count", 0) or 0)),
                    "track17_health_status": row.get("health_status", ""),
                    "diagnosis": "100c_starved" if algorithm == args.main_method and eval_ratio < float(args.min_eval_ratio) else row.get("diagnosis", ""),
                }
            )
        else:
            audit_rows.append(
                {
                    "source": str(source),
                    "algorithm": algorithm,
                    "seed": int(args.audit_seed),
                    "scale": "100",
                    "track17_status": "MISSING_AFTER_TRACK17_HALT",
                    "actual_evals": 0,
                    "eval_budget": 0,
                    "eval_ratio": math.nan,
                    "best_cost": math.nan,
                    "warm_start_cost": math.nan,
                    "returned_warm_start": "",
                    "unique_solution_count": 0,
                    "best_update_count": 0,
                    "track17_health_status": "MISSING",
                    "diagnosis": "not_run_because_track17_halted_early",
                }
            )
    _write_rows(output_dir / "track19_budget_audit.csv", audit_rows)
    main = next((row for row in audit_rows if row["algorithm"] == args.main_method), {})
    main_starved = _to_float(main.get("eval_ratio")) < float(args.min_eval_ratio)
    return {
        "verdict": "BUDGET_AUDIT_DONE",
        "reason": "Track17 100c evidence audited; main method was under-evaluated." if main_starved else "Track17 100c evidence audited.",
        "source_rows": str(source),
        "rows": audit_rows,
        "main_method": args.main_method,
        "main_100c_starved": bool(main_starved),
    }


def run_stage1_calibration(args: argparse.Namespace, output_dir: Path, progress_path: Path, started: float) -> dict[str, Any]:
    rows_path = output_dir / "track19_100c_calibration.csv"
    rows = _read_rows(rows_path) if args.resume and rows_path.exists() else []
    for row in rows:
        _reclassify_existing_row(row, args=args)
    if rows:
        _write_rows(rows_path, rows)
    bundle_dir = args.calibration_bundle
    bundle_name = Path(bundle_dir).name
    warm = _warm_start_metrics(bundle_dir)
    done = {(row["algorithm"], int(row["seed"])) for row in rows}
    for seed in _parse_int_list(args.calibration_seeds):
        key = (args.main_method, int(seed))
        if key in done:
            continue
        _check_wall(started, float(args.max_wall_seconds))
        _log(progress_path, f"Stage1 100c calibration bundle={bundle_name} seed={seed} algorithm={args.main_method}")
        scale_args = _scale_args(args, "100")
        row, _solution = _run_method(bundle_dir, args.main_method, seed=int(seed), args=scale_args, warm=warm, stage="budget_calibration")
        _annotate_track19_row(row, bundle_dir=bundle_dir, seed=int(seed), args=args)
        rows.append(row)
        _write_rows(rows_path, rows)
    invalid = [row for row in rows if row.get("track19_status") == "INVALID_NOT_RUN"]
    if invalid:
        worst = min(_to_float(row.get("eval_ratio")) for row in invalid)
        return {
            "verdict": "HALT_100C_STILL_STARVED",
            "reason": f"100c main method still failed the Track19 not-run gate after increased runtime; min_observed_eval_ratio={worst:.3f}.",
            "rows": rows,
        }
    return {
        "verdict": "CALIBRATION_PASS",
        "reason": "100c main method reached the Track19 not-starved gate on calibration seed(s).",
        "rows": rows,
    }


def run_stage1b_method_diagnostic(args: argparse.Namespace, output_dir: Path, progress_path: Path, started: float) -> dict[str, Any]:
    rows_path = output_dir / "track19_100c_method_diagnostic.csv"
    rows = [] if args.force else (_read_rows(rows_path) if args.resume and rows_path.exists() else [])
    for row in rows:
        _reclassify_existing_row(row, args=args)
        _annotate_diagnostic_metrics(row)
    if rows:
        _write_rows(rows_path, rows)
    bundle_dir = args.diagnostic_bundle
    bundle_name = Path(bundle_dir).name
    warm = _warm_start_metrics(bundle_dir)
    methods = _dedupe([*_parse_csv(args.diagnostic_methods), args.main_method])
    done = {(row["bundle"], int(row["seed"]), row["algorithm"]) for row in rows}
    for seed in _parse_int_list(args.diagnostic_seeds):
        for method in methods:
            if (bundle_name, int(seed), method) in done:
                continue
            _check_wall(started, float(args.max_wall_seconds))
            _log(progress_path, f"Stage1b 100c method diagnostic bundle={bundle_name} seed={seed} method={method}")
            scale_args = _scale_args(args, "100")
            scale_args.eval_budget = int(args.diagnostic_eval_budget)
            scale_args.max_runtime_seconds = float(args.diagnostic_max_runtime_seconds)
            row, _solution = _run_method(bundle_dir, method, seed=int(seed), args=scale_args, warm=warm, stage="method_diagnostic_100c")
            _annotate_track19_row(row, bundle_dir=bundle_dir, seed=int(seed), args=args)
            _annotate_diagnostic_metrics(row)
            rows.append(row)
            _write_rows(rows_path, rows)
    summary = _method_diagnostic_summary(rows, args.main_method)
    improving = list(summary.get("methods_improving_warm") or [])
    current = summary.get("current_main") or {}
    current_improves = bool(current.get("improves_warm", False))
    if current_improves:
        verdict = "DIAGNOSTIC_MAIN_100C_CAN_MOVE"
        reason = f"{args.main_method} improved warm start in the 100c diagnostic."
    elif improving:
        verdict = "DIAGNOSTIC_RESELECT_MAIN"
        reason = f"{args.main_method} stayed at warm start, while {', '.join(improving)} improved it in the 100c diagnostic."
    else:
        verdict = "DIAGNOSTIC_MAIN_100C_WEAK"
        reason = "No tested Track19 candidate improved the 100c warm start in the diagnostic budget."
    return {
        "verdict": verdict,
        "reason": reason,
        "bundle": bundle_name,
        "bundle_dir": str(bundle_dir),
        "seeds": _parse_int_list(args.diagnostic_seeds),
        "eval_budget": int(args.diagnostic_eval_budget),
        "max_runtime_seconds": float(args.diagnostic_max_runtime_seconds),
        "rows": rows,
        "summary": summary,
    }


def run_stage2_fair_comparison(args: argparse.Namespace, output_dir: Path, progress_path: Path, started: float) -> dict[str, Any]:
    rows_path = output_dir / "track19_rows.csv"
    rows = _read_rows(rows_path) if args.resume and rows_path.exists() else []
    for row in rows:
        _reclassify_existing_row(row, args=args)
    done = {(row["bundle"], int(row["seed"]), row["algorithm"]) for row in rows}
    baselines = _parse_csv(args.baseline_algorithms)
    algorithms = [args.main_method, *baselines]
    for bundle_dir in _parse_csv(args.formal_bundles):
        bundle_name = Path(bundle_dir).name
        scale = _scale_from_bundle_name(bundle_name)
        warm = _warm_start_metrics(bundle_dir)
        for seed in _parse_int_list(args.formal_seeds):
            for algorithm in algorithms:
                if (bundle_name, int(seed), algorithm) in done:
                    continue
                _check_wall(started, float(args.max_wall_seconds))
                _log(progress_path, f"Stage2 fair bundle={bundle_name} seed={seed} algorithm={algorithm}")
                scale_args = _scale_args(args, scale)
                if algorithm == args.main_method:
                    row, _solution = _run_method(bundle_dir, algorithm, seed=int(seed), args=scale_args, warm=warm, stage="fair_comparison")
                else:
                    row, _solution = _run_baseline_algorithm(bundle_dir, algorithm, seed=int(seed), args=scale_args, warm=warm, stage="fair_comparison")
                _annotate_track19_row(row, bundle_dir=bundle_dir, seed=int(seed), args=args)
                rows.append(row)
                _write_rows(rows_path, rows)
                if row.get("algorithm") == args.main_method and row.get("scale") == "100" and row.get("track19_status") == "INVALID_NOT_RUN":
                    return {
                        "verdict": "HALT_100C_STILL_STARVED",
                        "reason": f"100c main method still starved on {bundle_name}/seed{seed}: eval_ratio={row.get('eval_ratio')}.",
                        "rows": rows,
                        "summary": _track19_fair_summary(rows, args.main_method, baselines),
                    }
                if row.get("track19_status", "").startswith("INVALID"):
                    return {
                        "verdict": "HALT_INVALID_COMPARISON",
                        "reason": f"{algorithm} invalid on {bundle_name}/seed{seed}: {row.get('track19_status')}.",
                        "rows": rows,
                        "summary": _track19_fair_summary(rows, args.main_method, baselines),
                    }
    summary = _track19_fair_summary(rows, args.main_method, baselines)
    min_gain = _to_float(summary.get("min_mean_gain_vs_baseline_pct"))
    all_sig = bool(summary.get("all_wilcoxon_significant", False))
    no_reverse = bool(summary.get("no_reverse_scale", False))
    zero_violations = bool(summary.get("zero_violations", False))
    if zero_violations and all_sig and no_reverse and min_gain >= float(args.weak_win_threshold_pct):
        verdict = "WIN_REAL"
        reason = f"Main method beats every non-invalid baseline by at least {min_gain:.3f}% mean with Wilcoxon support."
    else:
        verdict = "MARGIN_REAL"
        reason = (
            "Legal comparison completed, but the 10% claim is not fully supported: "
            f"min_gain={min_gain}, wilcoxon={all_sig}, no_reverse_scale={no_reverse}, zero_violations={zero_violations}."
        )
    return {"verdict": verdict, "reason": reason, "rows": rows, "summary": summary}


def _scale_args(args: argparse.Namespace, scale: str) -> argparse.Namespace:
    data = vars(args).copy()
    if str(scale) == "100":
        data["eval_budget"] = int(args.eval_budget_100c)
        data["max_runtime_seconds"] = float(args.max_runtime_seconds_100c)
    else:
        data["eval_budget"] = int(args.eval_budget)
        data["max_runtime_seconds"] = float(args.max_runtime_seconds)
    return argparse.Namespace(**data)


def _annotate_track19_row(row: dict[str, Any], *, bundle_dir: str, seed: int, args: argparse.Namespace) -> None:
    bundle_name = Path(bundle_dir).name
    row["bundle"] = bundle_name
    row["bundle_dir"] = str(bundle_dir)
    row["seed"] = int(seed)
    row["scale"] = _scale_from_bundle_name(bundle_name)
    row["component_label"] = METHOD_LABELS.get(str(row.get("algorithm")), str(row.get("algorithm")))
    row["track19_status"] = track19_status(row, min_eval_ratio=float(args.min_eval_ratio), min_unique_solution_count=int(args.min_unique_solution_count))
    row["track19_legal"] = row["track19_status"] in {"HEALTHY", "VALID_BUT_WEAK"}
    row["exploration_proxy_count"] = _exploration_proxy_count(row)


def _reclassify_existing_row(row: dict[str, Any], *, args: argparse.Namespace) -> None:
    row["track19_status"] = track19_status(row, min_eval_ratio=float(args.min_eval_ratio), min_unique_solution_count=int(args.min_unique_solution_count))
    row["track19_legal"] = row["track19_status"] in {"HEALTHY", "VALID_BUT_WEAK"}
    row["exploration_proxy_count"] = _exploration_proxy_count(row)


def track19_status(row: dict[str, Any], *, min_eval_ratio: float = 0.9, min_unique_solution_count: int = 2) -> str:
    if int(row.get("violation_count", 1) or 0) != 0 or str(row.get("feasible", "True")).lower() in {"false", "0"}:
        return "INVALID_VIOLATION"
    if _to_float(row.get("eval_ratio")) < float(min_eval_ratio):
        return "INVALID_NOT_RUN"
    if _exploration_proxy_count(row) < int(min_unique_solution_count):
        return "INVALID_NOT_RUN"
    warm_cost = _to_float(row.get("warm_start_cost"))
    best_cost = _to_float(row.get("best_cost"))
    hash_changed = str(row.get("solution_hash", "")) != str(row.get("warm_hash", row.get("warm_start_hash", "")))
    if math.isfinite(best_cost) and math.isfinite(warm_cost) and best_cost < warm_cost - 1e-9 and hash_changed:
        return "HEALTHY"
    return "VALID_BUT_WEAK"


def _exploration_proxy_count(row: dict[str, Any]) -> int:
    unique = int(float(row.get("unique_solution_count", 0) or 0))
    if unique > 1:
        return unique
    attempts = _operator_attempt_count(row.get("operator_counts"))
    return max(unique, attempts)


def _operator_attempt_count(operator_counts: Any) -> int:
    if not operator_counts:
        return 0
    if isinstance(operator_counts, str):
        try:
            operator_counts = json.loads(operator_counts)
        except json.JSONDecodeError:
            return 0
    if not isinstance(operator_counts, dict):
        return 0
    destroy = operator_counts.get("destroy") or {}
    if not isinstance(destroy, dict):
        return 0
    total = 0
    for counts in destroy.values():
        if isinstance(counts, (list, tuple)):
            total += sum(int(float(value or 0)) for value in counts)
    return int(total)


def _operator_outcome_counts(operator_counts: Any) -> dict[str, int]:
    parsed = _coerce_operator_counts(operator_counts)
    if not isinstance(parsed, dict):
        return {"best": 0, "better_current": 0, "accepted": 0, "rejected": 0, "attempts": 0}
    destroy = parsed.get("destroy") or {}
    if not isinstance(destroy, dict):
        return {"best": 0, "better_current": 0, "accepted": 0, "rejected": 0, "attempts": 0}
    best = better_current = accepted = rejected = 0
    for counts in destroy.values():
        if not isinstance(counts, (list, tuple)):
            continue
        padded = list(counts) + [0, 0, 0, 0]
        best += int(float(padded[0] or 0))
        better_current += int(float(padded[1] or 0))
        accepted += int(float(padded[2] or 0))
        rejected += int(float(padded[3] or 0))
    return {
        "best": int(best),
        "better_current": int(better_current),
        "accepted": int(best + better_current + accepted),
        "rejected": int(rejected),
        "attempts": int(best + better_current + accepted + rejected),
    }


def _coerce_operator_counts(operator_counts: Any) -> Any:
    if isinstance(operator_counts, str):
        try:
            return json.loads(operator_counts)
        except json.JSONDecodeError:
            return None
    return operator_counts


def _annotate_diagnostic_metrics(row: dict[str, Any]) -> None:
    outcomes = _operator_outcome_counts(row.get("operator_counts"))
    warm_cost = _to_float(row.get("warm_start_cost"))
    best_cost = _to_float(row.get("best_cost"))
    improves = math.isfinite(best_cost) and math.isfinite(warm_cost) and best_cost < warm_cost - 1e-9
    row["diagnostic_best_outcome_count"] = int(outcomes["best"])
    row["diagnostic_accepted_move_count"] = int(outcomes["accepted"])
    row["diagnostic_rejected_move_count"] = int(outcomes["rejected"])
    row["diagnostic_operator_attempts"] = int(outcomes["attempts"])
    row["diagnostic_improves_warm"] = bool(improves)
    if int(outcomes["attempts"]) > 0 and int(outcomes["accepted"]) == 0:
        row["diagnostic_note"] = "all_operator_attempts_rejected"
    elif improves:
        row["diagnostic_note"] = "improved_warm_start"
    else:
        row["diagnostic_note"] = "no_warm_start_improvement"


def _method_diagnostic_summary(rows: list[dict[str, Any]], main_method: str) -> dict[str, Any]:
    by_method: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_method.setdefault(str(row.get("algorithm")), []).append(row)
    methods: dict[str, dict[str, Any]] = {}
    for method, method_rows in sorted(by_method.items()):
        finite_costs = [_to_float(row.get("best_cost")) for row in method_rows if math.isfinite(_to_float(row.get("best_cost")))]
        warm_costs = [_to_float(row.get("warm_start_cost")) for row in method_rows if math.isfinite(_to_float(row.get("warm_start_cost")))]
        improvements = [_to_float(row.get("improvement_vs_warm_pct")) for row in method_rows if math.isfinite(_to_float(row.get("improvement_vs_warm_pct")))]
        methods[method] = {
            "row_count": len(method_rows),
            "mean_best_cost": sum(finite_costs) / len(finite_costs) if finite_costs else math.nan,
            "mean_warm_start_cost": sum(warm_costs) / len(warm_costs) if warm_costs else math.nan,
            "mean_improvement_vs_warm_pct": sum(improvements) / len(improvements) if improvements else math.nan,
            "improves_warm": any(str(row.get("diagnostic_improves_warm")).lower() == "true" for row in method_rows),
            "best_update_count": sum(int(float(row.get("best_update_count", 0) or 0)) for row in method_rows),
            "accepted_move_count": sum(int(float(row.get("diagnostic_accepted_move_count", 0) or 0)) for row in method_rows),
            "rejected_move_count": sum(int(float(row.get("diagnostic_rejected_move_count", 0) or 0)) for row in method_rows),
            "status_counts": _status_counts(method_rows),
        }
    improving = [method for method, data in methods.items() if bool(data.get("improves_warm"))]
    finite_methods = [(method, _to_float(data.get("mean_best_cost"))) for method, data in methods.items()]
    finite_methods = [(method, cost) for method, cost in finite_methods if math.isfinite(cost)]
    best_method = min(finite_methods, key=lambda item: (item[1], item[0]))[0] if finite_methods else ""
    return {
        "main_method": main_method,
        "current_main": methods.get(main_method, {}),
        "methods": methods,
        "methods_improving_warm": improving,
        "best_method_by_mean_cost": best_method,
    }


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _track19_fair_summary(rows: list[dict[str, Any]], main_method: str, baseline_algorithms: list[str]) -> dict[str, Any]:
    legal_rows = [row for row in rows if str(row.get("track19_status")) in {"HEALTHY", "VALID_BUT_WEAK"} or row.get("algorithm") == main_method]
    legal_baselines = [
        algorithm
        for algorithm in baseline_algorithms
        if not any(row.get("algorithm") == algorithm and str(row.get("track19_status", "")).startswith("INVALID") for row in rows)
    ]
    summary = _fair_summary(legal_rows, main_method, legal_baselines)
    scale_mean_gains: dict[str, dict[str, float]] = {}
    for scale in sorted({str(row.get("scale")) for row in legal_rows if row.get("scale")}):
        scale_rows = [row for row in legal_rows if str(row.get("scale")) == scale]
        scale_mean_gains[scale] = dict(_fair_summary(scale_rows, main_method, legal_baselines).get("mean_gain_vs_baseline_pct", {}))
    summary["scale_mean_gains"] = scale_mean_gains
    summary["legal_baselines"] = legal_baselines
    summary["invalid_rows"] = [row for row in rows if str(row.get("track19_status", "")).startswith("INVALID")]
    summary["main_label"] = METHOD_LABELS.get(main_method, main_method)
    summary["status_counts"] = _status_counts(rows)
    return summary


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("track19_status", "UNKNOWN"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _budget_audit_report(audit: dict[str, Any]) -> str:
    lines = [
        "# Track19 Budget Audit",
        "",
        f"Verdict: {audit.get('verdict')}",
        f"Reason: {audit.get('reason')}",
        f"Main method: {audit.get('main_method')}",
        f"Main 100c starved: {audit.get('main_100c_starved')}",
        "",
        "Rows are also written to `track19_budget_audit.csv`.",
    ]
    return "\n".join(lines) + "\n"


def _calibration_report(calibration: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Track19 100c Calibration",
            "",
            f"Verdict: {calibration.get('verdict')}",
            f"Reason: {calibration.get('reason')}",
            f"Rows: {len(calibration.get('rows') or [])}",
        ]
    ) + "\n"


def _method_diagnostic_report(diagnostic: dict[str, Any]) -> str:
    summary = diagnostic.get("summary") or {}
    methods = summary.get("methods") or {}
    lines = [
        "# Track19 100c Method Diagnostic",
        "",
        f"Verdict: {diagnostic.get('verdict')}",
        f"Reason: {diagnostic.get('reason')}",
        f"Bundle: {diagnostic.get('bundle')}",
        f"Seeds: {', '.join(str(seed) for seed in diagnostic.get('seeds') or [])}",
        f"Diagnostic eval budget: {diagnostic.get('eval_budget')}",
        f"Diagnostic max runtime seconds: {diagnostic.get('max_runtime_seconds')}",
        f"Best method by mean cost: {summary.get('best_method_by_mean_cost', '')}",
        "",
        "| method | rows | improves_warm | mean_best_cost | mean_improvement_pct | best_updates | accepted | rejected |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for method, data in sorted(methods.items()):
        lines.append(
            "| {method} | {rows} | {improves} | {cost:.6f} | {gain:.6f} | {updates} | {accepted} | {rejected} |".format(
                method=method,
                rows=int(data.get("row_count", 0) or 0),
                improves=bool(data.get("improves_warm", False)),
                cost=_to_float(data.get("mean_best_cost")),
                gain=_to_float(data.get("mean_improvement_vs_warm_pct")),
                updates=int(data.get("best_update_count", 0) or 0),
                accepted=int(data.get("accepted_move_count", 0) or 0),
                rejected=int(data.get("rejected_move_count", 0) or 0),
            )
        )
    lines.extend(
        [
            "",
            "Rows are also written to `track19_100c_method_diagnostic.csv`.",
            "This is a diagnostic route-selection artifact, not a final paper claim.",
        ]
    )
    return "\n".join(lines) + "\n"


def _fair_report(fair: dict[str, Any]) -> str:
    summary = fair.get("summary") or {}
    return "\n".join(
        [
            "# Track19 Fair Report",
            "",
            f"Verdict: {fair.get('verdict')}",
            f"Reason: {fair.get('reason')}",
            f"Main method: {summary.get('main_method')} ({summary.get('main_label')})",
            f"Legal baselines: {', '.join(summary.get('legal_baselines') or [])}",
            f"Status counts: {json.dumps(summary.get('status_counts', {}), sort_keys=True)}",
            f"Mean gains vs baselines pct: {json.dumps(summary.get('mean_gain_vs_baseline_pct', {}), sort_keys=True)}",
            f"Median gains vs baselines pct: {json.dumps(summary.get('median_gain_vs_baseline_pct', {}), sort_keys=True)}",
            f"Scale mean gains pct: {json.dumps(summary.get('scale_mean_gains', {}), sort_keys=True)}",
            f"Wilcoxon p-values: {json.dumps(summary.get('wilcoxon_p_values', {}), sort_keys=True)}",
            f"Invalid row count: {len(summary.get('invalid_rows') or [])}",
        ]
    ) + "\n"


def _summarize_final(state: dict[str, Any]) -> tuple[str, str]:
    fair = state.get("fair_comparison") or {}
    if fair.get("verdict") in {"WIN_REAL", "MARGIN_REAL", "HALT_100C_STILL_STARVED", "HALT_INVALID_COMPARISON"}:
        return str(fair["verdict"]), str(fair.get("reason", ""))
    calibration = state.get("calibration") or {}
    if calibration.get("verdict") == "HALT_100C_STILL_STARVED":
        return str(calibration["verdict"]), str(calibration.get("reason", ""))
    diagnostic = state.get("method_diagnostic") or {}
    if diagnostic.get("verdict") == "DIAGNOSTIC_MAIN_100C_WEAK":
        return "HALT_MAIN_100C_WEAK", str(diagnostic.get("reason", ""))
    return "RUNNING", "Track19 is not complete."


def _final_report(state: dict[str, Any]) -> str:
    audit = state.get("budget_audit") or {}
    calibration = state.get("calibration") or {}
    diagnostic = state.get("method_diagnostic") or {}
    diagnostic_summary = diagnostic.get("summary") or {}
    fair = state.get("fair_comparison") or {}
    fair_summary = fair.get("summary") or {}
    if diagnostic.get("verdict") == "DIAGNOSTIC_MAIN_100C_WEAK":
        decision = (
            "HALT_MAIN_100C_WEAK: 100c budget legality is fixed, but the tested Track19 ALNS main-method candidates "
            "did not improve the 100c warm start in the diagnostic budget. Do not resume the formal 100c claim with "
            "the current main method."
        )
    else:
        decision = "Track19 separates under-run invalid rows from legal-but-weak rows. Only non-invalid baselines can support a paper claim."
    lines = [
        "# Final Track19 Report",
        "",
        f"Final status: {state.get('final_status')}",
        f"Final reason: {state.get('final_reason')}",
        "",
        "## Budget Audit",
        f"Verdict: {audit.get('verdict', 'NOT_RUN')}",
        f"Main 100c starved in Track17: {audit.get('main_100c_starved', '')}",
        "",
        "## 100c Calibration",
        f"Verdict: {calibration.get('verdict', 'NOT_RUN')}",
        f"Reason: {calibration.get('reason', '')}",
        "",
        "## 100c Method Diagnostic",
        f"Verdict: {diagnostic.get('verdict', 'NOT_RUN')}",
        f"Reason: {diagnostic.get('reason', '')}",
        f"Best diagnostic method: {diagnostic_summary.get('best_method_by_mean_cost', '')}",
        "",
        "## Fair Comparison",
        f"Verdict: {fair.get('verdict', 'NOT_RUN')}",
        f"Main method: {fair_summary.get('main_method', DEFAULT_MAIN_METHOD)}",
        f"Legal baselines: {', '.join(fair_summary.get('legal_baselines') or [])}",
        f"Status counts: {json.dumps(fair_summary.get('status_counts', {}), sort_keys=True)}",
        f"Mean gains vs baselines pct: {json.dumps(fair_summary.get('mean_gain_vs_baseline_pct', {}), sort_keys=True)}",
        f"Scale mean gains pct: {json.dumps(fair_summary.get('scale_mean_gains', {}), sort_keys=True)}",
        "",
        "## Decision",
        decision,
    ]
    return "\n".join(lines) + "\n"


def _scale_from_bundle_name(name: str) -> str:
    if "E-UK25" in name:
        return "25"
    if "E-UK50" in name:
        return "50"
    if "E-UK100" in name:
        return "100"
    return "unknown"


def _enforce_resume_guard(state: dict[str, Any], *, resume: bool, force: bool) -> None:
    status = str(state.get("final_status") or "")
    if force or resume or not status or status in {"RUNNING", "HALT_WALL_CLOCK", "STOP_AFTER_BUDGET_AUDIT", "STOP_AFTER_CALIBRATION", "STOP_AFTER_METHOD_DIAGNOSTIC"}:
        return
    if status in TERMINAL_STATUSES:
        raise Track19Halt(status, f"Existing terminal Track19 state found ({status}); use a fresh output-dir to rerun.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track19 budget-legal fair comparison runner.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    parser.add_argument("--require-self-py313", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--min-free-disk-gb", type=float, default=10.0)
    parser.add_argument("--track17-rows", default=str(TRACK17_ROWS))
    parser.add_argument("--audit-seed", type=int, default=901)
    parser.add_argument("--main-method", default=DEFAULT_MAIN_METHOD)
    parser.add_argument("--baseline-algorithms", default=",".join(HEALTHY_BASELINES))
    parser.add_argument("--formal-bundles", default=",".join(TRACK17_FORMAL_BUNDLES))
    parser.add_argument("--formal-seeds", default="901,902,903,904,905,906,907,908,909,910")
    parser.add_argument("--calibration-bundle", default=TRACK17_FORMAL_BUNDLES[2])
    parser.add_argument("--calibration-seeds", default="901")
    parser.add_argument("--diagnostic-bundle", default=TRACK17_FORMAL_BUNDLES[2])
    parser.add_argument("--diagnostic-seeds", default="901")
    parser.add_argument("--diagnostic-methods", default=",".join(DEFAULT_DIAGNOSTIC_METHODS))
    parser.add_argument("--diagnostic-eval-budget", type=int, default=4_000)
    parser.add_argument("--diagnostic-max-runtime-seconds", type=float, default=1200.0)
    parser.add_argument("--eval-budget", type=int, default=16_000)
    parser.add_argument("--max-runtime-seconds", type=float, default=900.0)
    parser.add_argument("--eval-budget-100c", type=int, default=16_000)
    parser.add_argument("--max-runtime-seconds-100c", type=float, default=4200.0)
    parser.add_argument("--max-wall-seconds", type=float, default=8 * 3600.0)
    parser.add_argument("--min-eval-ratio", type=float, default=0.90)
    parser.add_argument("--min-unique-solution-count", type=int, default=2)
    parser.add_argument("--weak-win-threshold-pct", type=float, default=10.0)
    parser.add_argument("--health-bundles", default=TRACK17_FORMAL_BUNDLES[0])
    parser.add_argument("--health-seeds", default="901")
    parser.add_argument("--ablation-bundles", default=TRACK17_FORMAL_BUNDLES[0])
    parser.add_argument("--stop-after", choices=("budget_audit", "calibration", "method_diagnostic", "fair_comparison"), default="fair_comparison")
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
