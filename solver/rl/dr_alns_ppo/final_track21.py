from __future__ import annotations

import argparse
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

from .final_track16 import (
    _check_wall,
    _parse_csv,
    _read_rows,
    _run_baseline_algorithm,
    _run_method,
    _to_float,
    _warm_start_metrics,
    _write_rows,
    _write_text,
)
from .final_track17 import (
    HEALTHY_BASELINES,
    METHOD_LABELS,
    TRACK17_ABLATION_BUNDLES,
    TRACK17_FORMAL_BUNDLES,
    TRACK17_METHODS,
    _method_ablation_report,
    _scale_from_bundle_name,
    _track17_method_summary,
)
from .final_track19 import (
    _fair_report,
    _scale_args,
    _track19_fair_summary,
    _write_json,
    track19_status,
)
from .pilot20_learned_destroy_phaseA import DEFAULT_WORKER, REQUIRED_WORKER_NUMPY, _parse_int_list
from .pilot22_grounded_fixes import _log, _run_python_json


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track21_reclaim")
PROTECTED_SEMANTIC_FILES = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)


class Track21Halt(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "track21_progress.log"
    started = time.monotonic()
    state: dict[str, Any] = {"final_status": "RUNNING", "final_reason": ""}
    try:
        preflight = run_preflight(args, output_dir)
        state["preflight"] = preflight
        _write_json(output_dir / "track21_preflight.json", preflight)
        _log(progress_path, "Track21 reclaim start")

        ablation = run_stage_ablation(args, output_dir, progress_path, started)
        state["method_ablation"] = ablation
        _write_json(output_dir / "track21_method_ablation_report.json", ablation)
        _write_text(output_dir / "track21_method_ablation_report.md", _method_ablation_report(ablation))
        if ablation["verdict"] == "HALT_MAIN_NOT_STRONG":
            raise Track21Halt("HALT_MAIN_NOT_STRONG", ablation["reason"])
        if args.stop_after == "method_ablation":
            state["final_status"] = "STOP_AFTER_METHOD_ABLATION"
            state["final_reason"] = "Stopped after Track21 method ablation."
            return 0

        fair = run_stage_fair_comparison(args, output_dir, progress_path, started, ablation)
        state["fair_comparison"] = fair
        _write_json(output_dir / "track21_reclaimed_fair_comparison.json", fair)
        _write_text(output_dir / "track21_reclaimed_fair_comparison.md", _fair_report(fair))
        if fair["verdict"] in {"HALT_100C_STILL_STARVED", "HALT_INVALID_COMPARISON"}:
            raise Track21Halt(fair["verdict"], fair["reason"])
        state["final_status"] = fair["verdict"]
        state["final_reason"] = fair["reason"]
        return 0
    except Track21Halt as exc:
        state["final_status"] = exc.status
        state["final_reason"] = exc.message
        _log(progress_path, f"HALT {exc.status}: {exc.message}")
        return 2
    finally:
        state["wall_time_seconds"] = float(time.monotonic() - started)
        _write_json(output_dir / "track21_state.json", state)
        _write_json(output_dir / "final_report.json", state)
        final_text = _final_report(state)
        _write_text(output_dir / "final_report.md", final_text)
        _write_text(Path("final_report.md"), final_text)


def run_preflight(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    protected_status = _git_status_paths(PROTECTED_SEMANTIC_FILES)
    if protected_status:
        raise Track21Halt("HALT_PROTECTED_DIRTY", f"protected semantic files are dirty before run: {protected_status}")
    worker_python = Path(args.worker_python).resolve()
    if not worker_python.exists():
        raise Track21Halt("HALT_PREFLIGHT", f"py313 worker missing: {worker_python}")
    worker = _run_python_json(
        worker_python,
        "import json,sys,numpy; print(json.dumps({'exe':sys.executable,'version':sys.version.split()[0],'numpy':numpy.__version__}))",
    )
    if str(worker.get("numpy")) != REQUIRED_WORKER_NUMPY:
        raise Track21Halt("HALT_PREFLIGHT", f"worker NumPy drift: {worker.get('numpy')} != {REQUIRED_WORKER_NUMPY}")
    if bool(args.require_self_py313) and Path(sys.executable).resolve() != worker_python:
        raise Track21Halt("HALT_PREFLIGHT", f"runner must execute under py313 worker: {sys.executable} != {worker_python}")
    bundle_paths = sorted(set(_parse_csv(args.ablation_bundles) + _parse_csv(args.formal_bundles)))
    missing = [path for path in bundle_paths if not Path(path).exists()]
    if missing:
        raise Track21Halt("HALT_PREFLIGHT", f"bundle missing: {missing}")
    free_gb = shutil.disk_usage(output_dir.resolve().anchor or ".").free / (1024.0**3)
    if free_gb < float(args.min_free_disk_gb):
        raise Track21Halt("HALT_PREFLIGHT", f"free disk {free_gb:.1f}GB < {args.min_free_disk_gb}GB")
    return {
        "worker": worker,
        "runner_executable": sys.executable,
        "protected_semantic_status": protected_status,
        "disk_free_gb": free_gb,
    }


def run_stage_ablation(args: argparse.Namespace, output_dir: Path, progress_path: Path, started: float) -> dict[str, Any]:
    rows_path = output_dir / "track21_method_ablation.csv"
    rows = _read_rows(rows_path) if args.resume and rows_path.exists() else []
    done = {(row["bundle"], int(row["seed"]), row["algorithm"]) for row in rows}
    methods = _parse_csv(args.method_algorithms)
    for bundle_dir in _parse_csv(args.ablation_bundles):
        bundle_name = Path(bundle_dir).name
        warm = _warm_start_metrics(bundle_dir)
        for seed in _parse_int_list(args.ablation_seeds):
            for method in methods:
                if (bundle_name, int(seed), method) in done:
                    continue
                _check_wall(started, float(args.max_wall_seconds))
                _log(progress_path, f"StageA ablation bundle={bundle_name} seed={seed} method={method}")
                scale = _scale_from_bundle_name(bundle_name)
                scale_args = _scale_args(args, scale)
                row, _solution = _run_method(bundle_dir, method, seed=int(seed), args=scale_args, warm=warm, stage="track21_method_ablation")
                row["bundle"] = bundle_name
                row["bundle_dir"] = str(bundle_dir)
                row["seed"] = int(seed)
                row["scale"] = scale
                row["component_label"] = METHOD_LABELS.get(method, method)
                rows.append(row)
                _write_rows(rows_path, rows)
    summary = _track17_method_summary(rows)
    chosen = str(summary.get("chosen_main_method") or args.default_main_method)
    if summary.get("verdict") == "HALT_MAIN_NOT_STRONG":
        return {"verdict": "HALT_MAIN_NOT_STRONG", "reason": str(summary.get("reason")), "rows": rows, "summary": summary}
    return {
        "verdict": "MAIN_METHOD_SELECTED",
        "reason": f"{chosen} selected on Track21 validation; gain vs plain={summary.get('chosen_gain_vs_plain_pct'):.3f}%.",
        "rows": rows,
        "summary": summary,
    }


def run_stage_fair_comparison(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    started: float,
    ablation: dict[str, Any],
) -> dict[str, Any]:
    rows_path = output_dir / "track21_reclaimed_fair_comparison.csv"
    rows = _read_rows(rows_path) if args.resume and rows_path.exists() else []
    done = {(row["bundle"], int(row["seed"]), row["algorithm"]) for row in rows}
    baselines = _parse_csv(args.baseline_algorithms)
    chosen = str((ablation.get("summary") or {}).get("chosen_main_method") or args.default_main_method)
    algorithms = [chosen, *baselines]
    for bundle_dir in _parse_csv(args.formal_bundles):
        bundle_name = Path(bundle_dir).name
        scale = _scale_from_bundle_name(bundle_name)
        warm = _warm_start_metrics(bundle_dir)
        for seed in _parse_int_list(args.formal_seeds):
            for algorithm in algorithms:
                if (bundle_name, int(seed), algorithm) in done:
                    continue
                _check_wall(started, float(args.max_wall_seconds))
                _log(progress_path, f"StageB fair bundle={bundle_name} seed={seed} algorithm={algorithm}")
                scale_args = _scale_args(args, scale)
                if algorithm == chosen:
                    row, _solution = _run_method(bundle_dir, algorithm, seed=int(seed), args=scale_args, warm=warm, stage="track21_fair_comparison")
                else:
                    row, _solution = _run_baseline_algorithm(bundle_dir, algorithm, seed=int(seed), args=scale_args, warm=warm, stage="track21_fair_comparison")
                _annotate_track21_row(row, bundle_dir=bundle_dir, seed=int(seed), args=args)
                rows.append(row)
                _write_rows(rows_path, rows)
                if row.get("algorithm") == chosen and row.get("scale") == "100" and row.get("track21_status") == "INVALID_NOT_RUN":
                    return {
                        "verdict": "HALT_100C_STILL_STARVED",
                        "reason": f"100c main method still starved on {bundle_name}/seed{seed}: eval_ratio={row.get('eval_ratio')}.",
                        "rows": rows,
                        "summary": _track19_fair_summary(rows, chosen, baselines),
                    }
                if str(row.get("track21_status", "")).startswith("INVALID"):
                    return {
                        "verdict": "HALT_INVALID_COMPARISON",
                        "reason": f"{algorithm} invalid on {bundle_name}/seed{seed}: {row.get('track21_status')}.",
                        "rows": rows,
                        "summary": _track19_fair_summary(rows, chosen, baselines),
                    }
    summary = _track19_fair_summary(rows, chosen, baselines)
    min_gain = _to_float(summary.get("min_mean_gain_vs_baseline_pct"))
    all_sig = bool(summary.get("all_wilcoxon_significant", False))
    no_reverse = bool(summary.get("no_reverse_scale", False))
    zero_violations = bool(summary.get("zero_violations", False))
    if zero_violations and all_sig and no_reverse and min_gain >= float(args.weak_win_threshold_pct):
        verdict = "WIN_REAL"
        reason = f"Main method beats every healthy baseline by at least {min_gain:.3f}% mean with Wilcoxon support."
    else:
        verdict = "MARGIN_REAL"
        reason = (
            "Legal comparison completed, but the 10% claim is not fully supported: "
            f"min_gain={min_gain}, wilcoxon={all_sig}, no_reverse_scale={no_reverse}, zero_violations={zero_violations}."
        )
    return {"verdict": verdict, "reason": reason, "rows": rows, "summary": summary}


def _annotate_track21_row(row: dict[str, Any], *, bundle_dir: str, seed: int, args: argparse.Namespace) -> None:
    bundle_name = Path(bundle_dir).name
    row["bundle"] = bundle_name
    row["bundle_dir"] = str(bundle_dir)
    row["seed"] = int(seed)
    row["scale"] = _scale_from_bundle_name(bundle_name)
    row["component_label"] = METHOD_LABELS.get(str(row.get("algorithm")), str(row.get("algorithm")))
    row["track21_status"] = track19_status(
        row,
        min_eval_ratio=float(args.min_eval_ratio),
        min_unique_solution_count=int(args.min_unique_solution_count),
    )
    row["track21_legal"] = row["track21_status"] in {"HEALTHY", "VALID_BUT_WEAK"}


def _git_status_paths(paths: tuple[str, ...]) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--short", "--", *paths],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        return [result.stderr.strip() or f"git status failed with {result.returncode}"]
    return [line for line in result.stdout.splitlines() if line.strip()]


def _final_report(state: dict[str, Any]) -> str:
    ablation = state.get("method_ablation") or {}
    fair = state.get("fair_comparison") or {}
    summary = fair.get("summary") or {}
    return "\n".join(
        [
            "# Final Track21 Reclaim Report",
            "",
            f"Final status: {state.get('final_status', 'RUNNING')}",
            f"Final reason: {state.get('final_reason', '')}",
            "",
            "## Method Ablation",
            f"Verdict: {ablation.get('verdict', 'NOT_RUN')}",
            f"Reason: {ablation.get('reason', '')}",
            "",
            "## Fair Comparison",
            f"Verdict: {fair.get('verdict', 'NOT_RUN')}",
            f"Reason: {fair.get('reason', '')}",
            f"Mean gains vs baselines pct: {summary.get('mean_gain_vs_baseline_pct', {})}",
            f"Scale mean gains pct: {summary.get('scale_mean_gain_pct', {})}",
            f"Wilcoxon p-values: {summary.get('wilcoxon_p_values', {})}",
            "",
            "## Track21 Notes",
            "Track17/Track19 winner rows superseded by `SUPERSEDED_BY_TRACK21_FLEET_FIX` manifest.",
            "PSO remains transparently excluded; comparison uses six Track16-healthy baselines.",
            "DR worker contamination was fixed, but DR was not retrained in this Track21 reclaim run.",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track21 post-fleet-fix reclaim runner.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    parser.add_argument("--require-self-py313", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--min-free-disk-gb", type=float, default=10.0)
    parser.add_argument("--ablation-bundles", default=",".join(TRACK17_ABLATION_BUNDLES))
    parser.add_argument("--formal-bundles", default=",".join(TRACK17_FORMAL_BUNDLES))
    parser.add_argument("--ablation-seeds", default="901")
    parser.add_argument("--formal-seeds", default="901,902,903,904,905,906,907,908,909,910")
    parser.add_argument("--baseline-algorithms", default=",".join(HEALTHY_BASELINES))
    parser.add_argument("--method-algorithms", default=",".join(TRACK17_METHODS))
    parser.add_argument("--default-main-method", default="winner_kernel")
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
    parser.add_argument("--stop-after", choices=("method_ablation", "fair_comparison"), default="fair_comparison")
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
