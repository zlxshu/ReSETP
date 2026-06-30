from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

from setp_solver.search.metaheuristic_baselines import solution_to_dict

from .final_track16 import (
    Track16Halt,
    _check_wall,
    _fair_summary,
    _method_summary,
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
from .pilot20_learned_destroy_phaseA import DEFAULT_WORKER, _parse_int_list
from .pilot22_grounded_fixes import _load_state, _log, _save_state, _write_json


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track17")
TRACK16_MATRIX = Path("solver/reports/dr_alns_ppo_v3/final_track16/track16_baseline_health_matrix.csv")
HEALTHY_BASELINES = ("GA", "VNS", "SA", "GWO", "ACO", "IWD")
PSO_EXCLUSION = (
    "PSO adapter failed the common-referee health gate (3978 unique candidates but "
    "best_update_count=0, no candidate improved on warm start; search-direction failure, "
    "not an encoding bug); excluded from quantitative claims; root cause documented."
)
TRACK17_FORMAL_BUNDLES = (
    "models/data_bundle/generated_instances/E-UK25_02__curric_d2_s3_seed2_24h",
    "models/data_bundle/generated_instances/E-UK50_01__curric_d2_s3_seed1_24h",
    "models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113",
)
TRACK17_ABLATION_BUNDLES = TRACK17_FORMAL_BUNDLES[:2]
TRACK17_METHODS = (
    "plain_alns",
    "winner_kernel",
    "winner_kernel_local_search",
    "winner_kernel_charging_required",
    "winner_kernel_true_repair_adaptive_q",
    "winner_kernel_scan_bridge",
    "winner_kernel_sa_lns_cooling",
)
METHOD_LABELS = {
    "plain_alns": "plain_alns",
    "winner_kernel": "winner_kernel",
    "winner_kernel_local_search": "winner_kernel+local_search",
    "winner_kernel_charging_required": "winner_kernel+charging_aware",
    "winner_kernel_true_repair_adaptive_q": "winner_kernel+true_repair+adaptive_q",
    "winner_kernel_scan_bridge": "winner_kernel+scan_bridge",
    "winner_kernel_sa_lns_cooling": "winner_kernel+sa_lns_cooling",
}
UNSUPPORTED_COMPONENT_NOTES = (
    "No separate callable carbon-aware timing or fairness component is exposed by winner_operators.py; "
    "carbon profile is already part of the common objective, and fairness.py is a separate fairness experiment harness."
)
TERMINAL_STATUSES = {"WIN_REAL", "MARGIN_REAL", "HALT_MAIN_NOT_STRONG", "HALT_PREFLIGHT", "HALT_PROTECTED_DIRTY"}


class Track17Halt(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "track17_progress.log"
    state_path = output_dir / "track17_state.json"
    state = _load_state(state_path) if args.resume else {}
    started = time.monotonic()
    final_status = str(state.get("final_status") or "RUNNING")
    final_reason = str(state.get("final_reason") or "")
    try:
        _enforce_resume_guard(state, resume=bool(args.resume))
        _log(progress_path, "Track17 start")
        preflight = run_preflight(args, output_dir)
        os.environ["SETP_WORKER_PYTHON"] = str(Path(args.worker_python).resolve())
        state["preflight"] = preflight
        _save_state(state_path, state)

        if not state.get("baseline_set_done"):
            baseline_set = run_stage_a(args, output_dir)
            state["baseline_set"] = baseline_set
            state["baseline_set_done"] = True
            _save_state(state_path, state)
            _write_json(output_dir / "track17_baseline_set_report.json", baseline_set)
            _write_text(output_dir / "track17_baseline_set_report.md", _baseline_set_report(baseline_set))

        if args.stop_after == "baseline_set":
            final_status = "STOP_AFTER_BASELINE_SET"
            final_reason = "Stopped after Track17 baseline set freeze."
            state["final_status"] = final_status
            state["final_reason"] = final_reason
            return 0

        if not state.get("method_ablation_done"):
            ablation = run_stage_b(args, output_dir, progress_path, started)
            state["method_ablation"] = ablation
            state["method_ablation_done"] = True
            _save_state(state_path, state)
            _write_json(output_dir / "track17_method_ablation_report.json", ablation)
            _write_text(output_dir / "track17_method_ablation_report.md", _method_ablation_report(ablation))
            if ablation["verdict"] == "HALT_MAIN_NOT_STRONG":
                raise Track17Halt(ablation["verdict"], ablation["reason"])

        if args.stop_after == "method_ablation":
            final_status = "STOP_AFTER_METHOD_ABLATION"
            final_reason = "Stopped after Track17 method ablation."
            state["final_status"] = final_status
            state["final_reason"] = final_reason
            return 0

        if not state.get("fair_comparison_done"):
            fair = run_stage_c(args, output_dir, progress_path, state, started)
            state["fair_comparison"] = fair
            state["fair_comparison_done"] = True
            _save_state(state_path, state)
            _write_json(output_dir / "track17_fair_comparison_report.json", fair)
            _write_text(output_dir / "track17_fair_comparison_report.md", _fair_comparison_report(fair))
            if fair["verdict"] == "HALT_BASELINE_NOT_RUNNING":
                raise Track17Halt(fair["verdict"], fair["reason"])

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
    except Track17Halt as exc:
        final_status = exc.status
        final_reason = exc.message
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _log(progress_path, f"HALT {final_status}: {final_reason}")
        return 2
    finally:
        state["final_status"] = final_status
        state["final_reason"] = _canonical_final_reason(state, final_status, final_reason)
        state["wall_time_seconds"] = float(time.monotonic() - started)
        _ensure_track17_artifacts(output_dir, state)
        _save_state(state_path, state)
        _write_json(output_dir / "final_report.json", state)
        final_text = _final_report(state)
        _write_text(output_dir / "final_report.md", final_text)
        _write_text(Path("final_report.md"), final_text)


def run_stage_a(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    matrix_path = Path(args.track16_matrix)
    rows = _read_csv_rows(matrix_path)
    by_algorithm = {str(row.get("algorithm")): row for row in rows}
    missing = [algorithm for algorithm in HEALTHY_BASELINES if algorithm not in by_algorithm]
    unhealthy = [
        algorithm
        for algorithm in HEALTHY_BASELINES
        if str(by_algorithm.get(algorithm, {}).get("health_status")) != "HEALTHY"
    ]
    pso = by_algorithm.get("PSO", {})
    pso_excluded = (
        str(pso.get("health_status")) != "HEALTHY"
        and int(float(pso.get("unique_solution_count", 0) or 0)) >= int(args.pso_min_unique)
        and int(float(pso.get("best_update_count", 0) or 0)) == 0
        and int(float(pso.get("candidates_better_than_warm", 0) or 0)) == 0
    )
    if missing or unhealthy or not pso_excluded:
        raise Track17Halt(
            "HALT_BASELINE_SET_INVALID",
            f"Track16 matrix does not prove Track17 baseline set: missing={missing}, unhealthy={unhealthy}, pso_excluded={pso_excluded}",
        )
    copied = output_dir / "track17_baseline_health_matrix.csv"
    _write_rows(copied, [dict(row) for row in rows if str(row.get("algorithm")) in (*HEALTHY_BASELINES, "PSO")])
    return {
        "verdict": "BASELINE_SET_FROZEN",
        "reason": "Six healthy baselines are frozen and PSO is transparently excluded.",
        "source_matrix": str(matrix_path),
        "healthy_algorithms": list(HEALTHY_BASELINES),
        "pso_row": pso,
        "pso_exclusion": PSO_EXCLUSION,
        "rows": rows,
    }


def run_stage_b(args: argparse.Namespace, output_dir: Path, progress_path: Path, started: float) -> dict[str, Any]:
    rows_path = output_dir / "track17_method_ablation.csv"
    rows = _read_rows(rows_path) if args.resume and rows_path.exists() else []
    done = {(row["bundle"], int(row["seed"]), row["algorithm"]) for row in rows}
    methods = _parse_csv(args.method_algorithms)
    solutions_dir = output_dir / "track17_method_solutions"
    solutions_dir.mkdir(parents=True, exist_ok=True)
    for bundle_dir in _parse_csv(args.ablation_bundles):
        bundle_name = Path(bundle_dir).name
        warm = _warm_start_metrics(bundle_dir)
        for seed in _parse_int_list(args.ablation_seeds):
            for method in methods:
                if (bundle_name, int(seed), method) in done:
                    continue
                _check_wall(started, args.max_wall_seconds)
                _log(progress_path, f"StageB ablation bundle={bundle_name} seed={seed} method={method}")
                row, solution = _run_method(bundle_dir, method, seed=int(seed), args=args, warm=warm, stage="method_ablation")
                row["bundle"] = bundle_name
                row["bundle_dir"] = str(bundle_dir)
                row["seed"] = int(seed)
                row["scale"] = _scale_from_bundle_name(bundle_name)
                row["component_label"] = METHOD_LABELS.get(method, method)
                rows.append(row)
                _write_rows(rows_path, rows)
                if solution is not None:
                    _write_json(solutions_dir / f"{bundle_name}_seed{seed}_{method}.json", solution_to_dict(solution))
    summary = _track17_method_summary(rows)
    chosen = str(summary.get("chosen_main_method") or args.default_main_method)
    if summary.get("verdict") == "HALT_MAIN_NOT_STRONG":
        return {"verdict": "HALT_MAIN_NOT_STRONG", "reason": str(summary.get("reason")), "rows": rows, "summary": summary}
    return {
        "verdict": "MAIN_METHOD_SELECTED",
        "reason": f"{chosen} selected on validation; gain vs plain={summary.get('chosen_gain_vs_plain_pct'):.3f}%.",
        "rows": rows,
        "summary": summary,
    }


def run_stage_c(args: argparse.Namespace, output_dir: Path, progress_path: Path, state: dict[str, Any], started: float) -> dict[str, Any]:
    rows_path = output_dir / "track17_rows.csv"
    rows = _read_rows(rows_path) if args.resume and rows_path.exists() else []
    done = {(row["bundle"], int(row["seed"]), row["algorithm"]) for row in rows}
    baseline_set = state.get("baseline_set") or {}
    baselines = list(baseline_set.get("healthy_algorithms") or HEALTHY_BASELINES)
    chosen = str(((state.get("method_ablation") or {}).get("summary") or {}).get("chosen_main_method") or args.default_main_method)
    algorithms = [chosen, *baselines]
    for bundle_dir in _parse_csv(args.formal_bundles):
        bundle_name = Path(bundle_dir).name
        warm = _warm_start_metrics(bundle_dir)
        for seed in _parse_int_list(args.formal_seeds):
            for algorithm in algorithms:
                if (bundle_name, int(seed), algorithm) in done:
                    continue
                _check_wall(started, args.max_wall_seconds)
                _log(progress_path, f"StageC fair bundle={bundle_name} seed={seed} algorithm={algorithm}")
                if algorithm == chosen:
                    row, solution = _run_method(bundle_dir, algorithm, seed=int(seed), args=args, warm=warm, stage="fair_comparison")
                else:
                    row, solution = _run_baseline_algorithm(bundle_dir, algorithm, seed=int(seed), args=args, warm=warm, stage="fair_comparison")
                row["bundle"] = bundle_name
                row["bundle_dir"] = str(bundle_dir)
                row["seed"] = int(seed)
                row["scale"] = _scale_from_bundle_name(bundle_name)
                row["component_label"] = METHOD_LABELS.get(algorithm, algorithm)
                rows.append(row)
                _write_rows(rows_path, rows)
                if row.get("role") == "weak_baseline" and row.get("health_status") != "HEALTHY":
                    return {
                        "verdict": "HALT_BASELINE_NOT_RUNNING",
                        "reason": f"{algorithm} failed formal health on {bundle_name}/seed{seed}: {row['health_status']}",
                        "rows": rows,
                        "summary": _track17_fair_summary(rows, chosen, baselines),
                    }
                _ = solution
    summary = _track17_fair_summary(rows, chosen, baselines)
    min_gain = float(summary.get("min_mean_gain_vs_baseline_pct", math.nan))
    zero_violations = bool(summary.get("zero_violations", False))
    all_significant = bool(summary.get("all_wilcoxon_significant", False))
    no_reverse_scale = bool(summary.get("no_reverse_scale", False))
    if zero_violations and min_gain >= float(args.weak_win_threshold_pct) and all_significant and no_reverse_scale:
        verdict = "WIN_REAL"
        reason = f"{chosen} beats every healthy baseline by at least {min_gain:.3f}% mean with paired Wilcoxon support."
    else:
        verdict = "MARGIN_REAL"
        reason = (
            "Fair comparison completed; report true margin without a 10% claim: "
            f"min_gain={min_gain}, wilcoxon={all_significant}, zero_violations={zero_violations}, no_reverse_scale={no_reverse_scale}."
        )
    return {"verdict": verdict, "reason": reason, "rows": rows, "summary": summary}


def _track17_method_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    base = _method_summary(rows)
    mean_costs = dict(base.get("mean_cost_by_method", {}))
    plain = _to_float(mean_costs.get("plain_alns"))
    winner = _to_float(mean_costs.get("winner_kernel"))
    if not math.isfinite(plain):
        return {**base, "verdict": "HALT_MAIN_NOT_STRONG", "reason": "plain_alns did not produce a finite validation mean."}
    retention: dict[str, dict[str, Any]] = {}
    eligible = ["plain_alns"]
    if math.isfinite(winner):
        eligible.append("winner_kernel")
    for method, mean_cost in mean_costs.items():
        if method in {"plain_alns", "winner_kernel"}:
            continue
        retained = math.isfinite(winner) and math.isfinite(float(mean_cost)) and float(mean_cost) <= winner + 1e-9
        retention[method] = {
            "label": METHOD_LABELS.get(method, method),
            "mean_cost": float(mean_cost),
            "gain_vs_plain_pct": _gain_pct(plain, float(mean_cost)),
            "gain_vs_winner_pct": _gain_pct(winner, float(mean_cost)) if math.isfinite(winner) else math.nan,
            "decision": "keep" if retained else "drop",
        }
        if retained:
            eligible.append(method)
    if math.isfinite(winner) and winner > plain + 1e-9:
        reason = f"winner_kernel mean cost {winner:.6f} is worse than plain_alns {plain:.6f}; plain_alns remains eligible."
    else:
        reason = "Main method chosen from plain_alns, winner_kernel, and individually retained components."
    chosen = min(eligible, key=lambda name: (_to_float(mean_costs.get(name)), name))
    chosen_cost = _to_float(mean_costs.get(chosen))
    return {
        **base,
        "verdict": "MAIN_METHOD_SELECTED",
        "reason": reason,
        "chosen_main_method": chosen,
        "chosen_label": METHOD_LABELS.get(chosen, chosen),
        "chosen_gain_vs_plain_pct": _gain_pct(plain, chosen_cost),
        "plain_mean_cost": plain,
        "winner_mean_cost": winner,
        "retention": retention,
        "unsupported_component_notes": UNSUPPORTED_COMPONENT_NOTES,
    }


def _track17_fair_summary(rows: list[dict[str, Any]], main_method: str, baseline_algorithms: list[str]) -> dict[str, Any]:
    summary = _fair_summary(rows, main_method, baseline_algorithms)
    scale_mean_gains: dict[str, dict[str, float]] = {}
    for scale in sorted({str(row.get("scale")) for row in rows if row.get("scale")}):
        scale_rows = [row for row in rows if str(row.get("scale")) == scale]
        scale_mean_gains[scale] = dict(_fair_summary(scale_rows, main_method, baseline_algorithms).get("mean_gain_vs_baseline_pct", {}))
    summary["scale_mean_gains"] = scale_mean_gains
    summary["pso_exclusion"] = PSO_EXCLUSION
    summary["main_label"] = METHOD_LABELS.get(main_method, main_method)
    return summary


def _baseline_set_report(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Track17 Baseline Set Report",
            "",
            f"Verdict: {report.get('verdict')}",
            f"Reason: {report.get('reason')}",
            f"Healthy baselines: {', '.join(report.get('healthy_algorithms') or [])}",
            f"PSO exclusion: {report.get('pso_exclusion')}",
            f"Source matrix: {report.get('source_matrix')}",
        ]
    )


def _method_ablation_report(ablation: dict[str, Any]) -> str:
    summary = ablation.get("summary") or {}
    retention = summary.get("retention") or {}
    lines = [
        "# Track17 Method Ablation Report",
        "",
        f"Verdict: {ablation.get('verdict')}",
        f"Reason: {ablation.get('reason')}",
        f"Chosen main method: {summary.get('chosen_main_method')} ({summary.get('chosen_label')})",
        f"Chosen gain vs plain_alns pct: {summary.get('chosen_gain_vs_plain_pct')}",
        f"Mean costs: {json.dumps(summary.get('mean_cost_by_method', {}), sort_keys=True)}",
        f"Component decisions: {json.dumps(retention, sort_keys=True)}",
        f"Unsupported component notes: {summary.get('unsupported_component_notes', '')}",
    ]
    return "\n".join(lines)


def _fair_comparison_report(fair: dict[str, Any]) -> str:
    summary = fair.get("summary") or {}
    return "\n".join(
        [
            "# Track17 Fair Comparison Report",
            "",
            f"Verdict: {fair.get('verdict')}",
            f"Reason: {fair.get('reason')}",
            f"Main method: {summary.get('main_method')} ({summary.get('main_label')})",
            f"Mean gains vs baselines pct: {json.dumps(summary.get('mean_gain_vs_baseline_pct', {}), sort_keys=True)}",
            f"Median gains vs baselines pct: {json.dumps(summary.get('median_gain_vs_baseline_pct', {}), sort_keys=True)}",
            f"Scale mean gains pct: {json.dumps(summary.get('scale_mean_gains', {}), sort_keys=True)}",
            f"Wilcoxon p-values: {json.dumps(summary.get('wilcoxon_p_values', {}), sort_keys=True)}",
            f"Failure instance count: {summary.get('failure_instance_count')}",
            f"PSO exclusion: {summary.get('pso_exclusion', PSO_EXCLUSION)}",
        ]
    )


def _final_report(state: dict[str, Any]) -> str:
    baseline = state.get("baseline_set") or {}
    ablation = state.get("method_ablation") or {}
    ablation_summary = ablation.get("summary") or {}
    fair = state.get("fair_comparison") or {}
    fair_summary = fair.get("summary") or {}
    return "\n".join(
        [
            "# Final Track17 Report",
            "",
            f"Final status: {state.get('final_status')}",
            f"Final reason: {state.get('final_reason')}",
            "",
            "## Baseline Set",
            f"Healthy baselines: {', '.join(baseline.get('healthy_algorithms') or [])}",
            f"PSO exclusion: {baseline.get('pso_exclusion', PSO_EXCLUSION)}",
            "",
            "## Method Ablation",
            f"Verdict: {ablation.get('verdict', 'NOT_RUN')}",
            f"Chosen main method: {ablation_summary.get('chosen_main_method', '')} ({ablation_summary.get('chosen_label', '')})",
            f"Chosen gain vs plain_alns pct: {ablation_summary.get('chosen_gain_vs_plain_pct', 'NA')}",
            f"Component decisions: {json.dumps(ablation_summary.get('retention', {}), sort_keys=True)}",
            "",
            "## Fair Comparison",
            f"Verdict: {fair.get('verdict', 'NOT_RUN')}",
            f"Main method: {fair_summary.get('main_method', '')} ({fair_summary.get('main_label', '')})",
            f"Mean gains vs baselines pct: {json.dumps(fair_summary.get('mean_gain_vs_baseline_pct', {}), sort_keys=True)}",
            f"Median gains vs baselines pct: {json.dumps(fair_summary.get('median_gain_vs_baseline_pct', {}), sort_keys=True)}",
            f"Scale mean gains pct: {json.dumps(fair_summary.get('scale_mean_gains', {}), sort_keys=True)}",
            f"Wilcoxon p-values: {json.dumps(fair_summary.get('wilcoxon_p_values', {}), sort_keys=True)}",
            "",
            "## Decision",
            "DR static learning is not used as evidence in Track17; DR remains future work pending Track18 dynamic headroom and held-out tests.",
            "Quantitative claims exclude PSO and use only the six Track16-healthy baselines.",
        ]
    )


def _ensure_track17_artifacts(output_dir: Path, state: dict[str, Any]) -> None:
    if "method_ablation" not in state:
        ablation = {"verdict": "NOT_RUN", "reason": "Skipped before method ablation.", "rows": [], "summary": {}}
        state["method_ablation"] = ablation
        _write_json(output_dir / "track17_method_ablation_report.json", ablation)
        _write_text(output_dir / "track17_method_ablation_report.md", _method_ablation_report(ablation))
    if "fair_comparison" not in state:
        fair = {"verdict": "NOT_RUN", "reason": "Skipped before fair comparison.", "rows": [], "summary": {}}
        state["fair_comparison"] = fair
        _write_json(output_dir / "track17_fair_comparison_report.json", fair)
        _write_text(output_dir / "track17_fair_comparison_report.md", _fair_comparison_report(fair))
    if not (output_dir / "track17_rows.csv").exists():
        _write_text(
            output_dir / "track17_rows.csv",
            "stage,algorithm,role,status,actual_evals,best_cost,warm_start_cost,solution_hash,warm_hash,health_status,diagnosis\n",
        )


def _summarize_final(state: dict[str, Any]) -> tuple[str, str]:
    for key in ("method_ablation", "fair_comparison"):
        stage = state.get(key) or {}
        verdict = str(stage.get("verdict") or "")
        if verdict in {"HALT_MAIN_NOT_STRONG", "HALT_BASELINE_NOT_RUNNING"}:
            return verdict, str(stage.get("reason", ""))
    fair = state.get("fair_comparison") or {}
    if fair.get("verdict") in {"WIN_REAL", "MARGIN_REAL"}:
        return str(fair["verdict"]), str(fair.get("reason", ""))
    return "RUNNING", "Track17 is not complete."


def _canonical_final_reason(state: dict[str, Any], final_status: str, fallback: str) -> str:
    for key in ("baseline_set", "method_ablation", "fair_comparison"):
        stage = state.get(key) or {}
        if stage.get("verdict") == final_status and stage.get("reason"):
            return str(stage["reason"])
    return fallback


def _enforce_resume_guard(state: dict[str, Any], *, resume: bool) -> None:
    status = str(state.get("final_status") or "")
    if resume and status in TERMINAL_STATUSES:
        raise Track17Halt(status, f"refusing to resume terminal Track17 state {status}")


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with Path(path).open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _scale_from_bundle_name(name: str) -> str:
    match = re.search(r"E-UK(\d+)", str(name))
    return match.group(1) if match else "unknown"


def _gain_pct(reference_cost: float, candidate_cost: float) -> float:
    if not math.isfinite(reference_cost) or not math.isfinite(candidate_cost) or reference_cost <= 0:
        return math.nan
    return (reference_cost - candidate_cost) / reference_cost * 100.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track17 fair comparison runner with PSO transparent exclusion.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    parser.add_argument("--require-self-py313", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--min-free-disk-gb", type=float, default=10.0)
    parser.add_argument("--track16-matrix", default=str(TRACK16_MATRIX))
    parser.add_argument("--pso-min-unique", type=int, default=100)
    parser.add_argument("--ablation-bundles", default=",".join(TRACK17_ABLATION_BUNDLES))
    parser.add_argument("--formal-bundles", default=",".join(TRACK17_FORMAL_BUNDLES))
    parser.add_argument("--ablation-seeds", default="901")
    parser.add_argument("--formal-seeds", default="901,902,903,904,905,906,907,908,909,910")
    parser.add_argument("--baseline-algorithms", default=",".join(HEALTHY_BASELINES))
    parser.add_argument("--method-algorithms", default=",".join(TRACK17_METHODS))
    parser.add_argument("--default-main-method", default="winner_kernel")
    parser.add_argument("--eval-budget", type=int, default=16_000)
    parser.add_argument("--max-runtime-seconds", type=float, default=900.0)
    parser.add_argument("--max-wall-seconds", type=float, default=8 * 3600.0)
    parser.add_argument("--min-eval-ratio", type=float, default=0.90)
    parser.add_argument("--min-unique-solution-count", type=int, default=2)
    parser.add_argument("--weak-win-threshold-pct", type=float, default=10.0)
    parser.add_argument("--health-bundles", default=TRACK17_FORMAL_BUNDLES[0])
    parser.add_argument("--health-seeds", default="901")
    parser.add_argument("--main-anchor-threshold-pct", type=float, default=0.0)
    parser.add_argument("--stop-after", choices=("baseline_set", "method_ablation", "fair_comparison"), default="fair_comparison")
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
