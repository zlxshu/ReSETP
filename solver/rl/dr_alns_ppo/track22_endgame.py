from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from setp_instance_lab.build_curriculum_instances import (
    DEFAULT_TEMPLATE_MANIFEST,
    CurriculumSpec,
    _load_template_config,
    build_config_for_spec,
    build_curriculum_manifest,
    validate_generated_bundle,
)
from setp_instance_lab.generator import generate_scenario
from setp_instance_lab.io import write_scenario_bundle

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.charging import replay_fixed_route_charging
from setp_solver.search.construction import build_initial_solution
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.search.fleet import FleetLimits
from setp_solver.search.winner_operators import WinnerKernelConfig, run_winner_kernel
from setp_solver.solution import Solution

from .action_space import (
    ALPHA_UCB_CHOICE,
    BLOCK_DESTROY_IDS,
    BLOCK_EXPLORATION_RATIOS,
    BLOCK_Q_RATIOS,
    BLOCK_REPAIR_IDS,
    BLOCK_THRESHOLD_RATIOS,
    DESTROY_IDS,
)
from .pilot20_learned_destroy_phaseA import (
    DEFAULT_WORKER,
    REQUIRED_WORKER_NUMPY,
    _episode_row,
    _parse_int_list,
    _require_torch_available,
    _worker_integrity_ok,
    run_operator_select_episode,
    run_random_episode,
)
from .pilot21_learned_destroy_big import (
    DEFAULT_STAGE0_BUNDLES as PILOT21_STAGE0_BUNDLES,
    run_best_of_k_episode,
    run_worst_removal_episode,
)
from .pilot22_grounded_fixes import _run_algorithm_row, flatten_pomo_shared_baseline
from .pilot23_stabilize import (
    linear_annealed_lr,
    ppo_update_learned_stable,
)
from .learned_destroy_policy import (
    load_learned_destroy_policy,
    make_learned_destroy_actor_critic,
    save_learned_destroy_policy,
)
from .schemas import BlockDecodedAction
from .worker_client import WorkerClient


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track22r")
DEFAULT_GENERATED_ROOT = Path("models/data_bundle/generated_instances")
DEFAULT_PPO_PYTHON = Path(r"C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe")

UNDERPOWERED = "UNDERPOWERED"
OK_BUDGET = "OK"
EQUAL_STEPS_ORACLE = "equal_steps_oracle"
EQUAL_EVAL_REFERENCE = "equal_eval_reference"
PILOT21_ANCHOR = "pilot21_anchor_reference"

STAGE2_EVAL_FLOORS = {"25c": 2000, "50c": 3000}
STAGE2_WALL_FLOOR_SECONDS = 60.0
STAGE4_CANDIDATE_EVAL_FLOOR = 200

DESTROY_LEVERAGE_CLEAN = "DESTROY_LEVERAGE_CLEAN"
LEVERAGE_MARGINAL = "LEVERAGE_MARGINAL"
NO_DESTROY_LEVERAGE_CLEAN = "NO_DESTROY_LEVERAGE_CLEAN"

PASS_LEARNED_DESTROY_CLEAN = "PASS_LEARNED_DESTROY_CLEAN"
WEAK_LEARNED_DESTROY_CLEAN = "WEAK_LEARNED_DESTROY_CLEAN"
HALT_LEARNED_DESTROY_CLEAN = "HALT_LEARNED_DESTROY_CLEAN"
SKIP_LEARNED_DESTROY_NO_LEVERAGE = "SKIP_LEARNED_DESTROY_NO_LEVERAGE"

CARBON_TIMING_LEVERAGE = "CARBON_TIMING_LEVERAGE"
CARBON_MECHANISM_WEAK = "CARBON_MECHANISM_WEAK"
CARBON_CEILING_TOO_SMALL_DEFAULT = "CARBON_CEILING_TOO_SMALL_DEFAULT"
HALT_WORKER_INTEGRITY = "HALT_WORKER_INTEGRITY"


TRACK22_SPECS = {
    "stage2_probe": (
        CurriculumSpec("E-UK25_11", 25, 2211),
        CurriculumSpec("E-UK25_12", 25, 2212),
        CurriculumSpec("E-UK25_13", 25, 2213),
        CurriculumSpec("E-UK50_11", 50, 2251),
        CurriculumSpec("E-UK50_12", 50, 2252),
    ),
    "stage3_train": (
        CurriculumSpec("E-UK25_14", 25, 2314),
        CurriculumSpec("E-UK25_15", 25, 2315),
        CurriculumSpec("E-UK25_16", 25, 2316),
        CurriculumSpec("E-UK50_13", 50, 2353),
        CurriculumSpec("E-UK50_14", 50, 2354),
    ),
    "stage3_val": (
        CurriculumSpec("E-UK25_17", 25, 2417),
        CurriculumSpec("E-UK50_15", 50, 2455),
    ),
    "stage3_test": (
        CurriculumSpec("E-UK25_18", 25, 2518),
        CurriculumSpec("E-UK50_16", 50, 2556),
        CurriculumSpec("E-UK50_17", 50, 2557),
    ),
}


class Track22Halt(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = str(status)
        self.message = str(message)


def run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "track22_progress.log"
    state_path = output_dir / "track22_state.json"
    state = _load_json(state_path) if args.resume and state_path.exists() else {}
    try:
        _log(progress_path, "Track22-R run start")
        state["preflight"] = run_preflight(args, output_dir)
        state["r1"] = r1_instrumentation_summary(output_dir)
        _write_json(output_dir / "track22_preflight.json", state["preflight"])
        _write_json(state_path, state)

        if not _stage_done(state, "stage2"):
            bundle_manifest = ensure_track22_bundles(args, output_dir)
            state["bundle_manifest"] = bundle_manifest
            _write_json(output_dir / "track22_bundle_manifest.json", bundle_manifest)
            rows = run_stage2_destroy_leverage(args, output_dir, progress_path, bundle_manifest)
            stage2 = summarize_stage2_destroy(rows)
            state["stage2"] = stage2
            state["completed_stage"] = "stage2"
            _write_json(output_dir / "stage2_destroy_leverage_summary.json", stage2)
            write_stage2_report(output_dir / "track22_destroy_leverage_report.md", stage2, bundle_manifest)
            _write_json(state_path, state)
            _log(progress_path, f"Stage2 verdict={stage2['status']}: {stage2['reason']}")

        if not _stage_done(state, "stage3"):
            stage2_status = str((state.get("stage2") or {}).get("status", ""))
            if stage2_status not in {DESTROY_LEVERAGE_CLEAN, LEVERAGE_MARGINAL}:
                stage3 = {
                    "status": SKIP_LEARNED_DESTROY_NO_LEVERAGE,
                    "reason": f"Stage2 status={stage2_status}; learned-destroy training skipped by Track22 gate.",
                    "trained": False,
                }
                _write_csv(output_dir / "track22_learned_destroy_test_rows.csv", [{"algorithm": "SKIPPED_STAGE3", **stage3}])
            else:
                stage3 = run_stage3_learned_destroy(args, output_dir, progress_path, state)
            state["stage3"] = stage3
            state["completed_stage"] = "stage3"
            _write_json(output_dir / "stage3_learned_destroy_summary.json", stage3)
            write_stage3_report(output_dir / "track22_learned_destroy_report.md", stage3)
            _write_json(state_path, state)
            _log(progress_path, f"Stage3 verdict={stage3['status']}: {stage3['reason']}")

        if not _stage_done(state, "stage4"):
            stage4 = run_stage4_carbon_timing(args, output_dir, progress_path, state)
            state["stage4"] = stage4
            state["completed_stage"] = "stage4"
            _write_json(output_dir / "stage4_carbon_timing_summary.json", stage4)
            write_stage4_report(output_dir / "track22_carbon_timing_report.md", stage4)
            _write_json(state_path, state)
            _log(progress_path, f"Stage4 verdict={stage4['status']}: {stage4['reason']}")

        state["final_status"] = final_status_from_state(state)
        state["final_reason"] = final_reason_from_state(state)
        state["wall_time_seconds"] = float(time.monotonic() - started)
        _write_json(state_path, state)
        _write_json(output_dir / "track22_final_report.json", state)
        write_final_report(output_dir / "final_report.md", state)
        return 0
    except Track22Halt as exc:
        state["final_status"] = exc.status
        state["final_reason"] = exc.message
        state["wall_time_seconds"] = float(time.monotonic() - started)
        _write_json(state_path, state)
        _write_json(output_dir / "track22_final_report.json", state)
        write_final_report(output_dir / "final_report.md", state)
        _log(progress_path, f"HALT {exc.status}: {exc.message}")
        return 2


def run_preflight(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    worker_python = Path(args.worker_python).resolve()
    if not worker_python.exists():
        raise Track22Halt(HALT_WORKER_INTEGRITY, f"py313 worker missing: {worker_python}")
    worker = _run_python_json(
        worker_python,
        "import json,sys,numpy; print(json.dumps({'exe':sys.executable,'version':sys.version.split()[0],'numpy':numpy.__version__}))",
    )
    if str(worker.get("numpy")) != REQUIRED_WORKER_NUMPY:
        raise Track22Halt(HALT_WORKER_INTEGRITY, f"worker NumPy drift: {worker.get('numpy')} != {REQUIRED_WORKER_NUMPY}")
    os.environ["SETP_WORKER_PYTHON"] = str(worker_python)
    disk = shutil.disk_usage(output_dir.resolve().anchor or ".")
    return {
        "worker": worker,
        "required_worker_numpy": REQUIRED_WORKER_NUMPY,
        "output_dir": str(output_dir),
        "disk_free_gb": float(disk.free) / (1024.0**3),
        "git": _git_snapshot(),
    }


def r1_instrumentation_summary(output_dir: Path) -> dict[str, Any]:
    test_result_path = output_dir / "r1_regression_test_result.json"
    test_result = _load_json(test_result_path) if test_result_path.exists() else {}
    return {
        "status": test_result.get("status", "IMPLEMENTED_TEST_RESULT_NOT_RECORDED_BY_RUNNER"),
        "root_cause": (
            "The original Track22 05:31 silent worker exit did not reproduce under the targeted 50c/q=0.4/20-customer "
            "50-step regression path on this machine. The confirmed instrument bug was empty worker stderr/logging on "
            "process failure; worker-side faulthandler and per-process crash logs were added so a recurrent Stage3 crash "
            "will expose a Python/native stack instead of a silent timeout."
        ),
        "fix": "worker_client now allocates SETP_WORKER_CRASH_LOG, enables PYTHONFAULTHANDLER, and reports stderr/crash-log tails; worker.py records uncaught request exceptions to stderr and the crash log.",
        "regression_test": "solver/rl/tests/test_track22r_worker_crash.py",
        "test_result": test_result,
    }


def ensure_track22_bundles(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    root = Path(".").resolve()
    template = _load_template_config((root / DEFAULT_TEMPLATE_MANIFEST).resolve())
    rows_by_role: dict[str, list[dict[str, Any]]] = {}
    for role, specs in TRACK22_SPECS.items():
        rows: list[dict[str, Any]] = []
        for spec in specs:
            output = root / DEFAULT_GENERATED_ROOT / spec.scenario_id
            if output.exists() and not bool(args.regenerate_bundles):
                manifest = validate_generated_bundle(output, expected_n=spec.n_customers)
            else:
                if output.exists():
                    _remove_existing_output(output, (root / DEFAULT_GENERATED_ROOT).resolve())
                scenario_config, manifest_config = build_config_for_spec(root, template, spec)
                scenario = generate_scenario(scenario_config)
                write_scenario_bundle(scenario, output, config=manifest_config)
                manifest = validate_generated_bundle(output, expected_n=spec.n_customers)
            rows.append(
                {
                    "role": role,
                    "name": spec.scenario_id,
                    "path": _manifest_bundle_path(root, output),
                    "n_customers": int(manifest["validation"]["customer_count"]),
                    "validation_passed": bool(manifest["validation"]["passed"]),
                    "has_carbon_profile": bool((output / "carbon_profile.csv").is_file()),
                    "seed": int(spec.seed),
                    "base_id": spec.base_id,
                }
            )
        role_manifest = build_curriculum_manifest(rows)
        _write_json(output_dir / f"track22_bundle_manifest_{role}.json", role_manifest)
        rows_by_role[role] = rows
    flat = [row for rows in rows_by_role.values() for row in rows]
    return {
        "schema_version": "track22-bundle-manifest.v1",
        "roles": rows_by_role,
        "all": flat,
        "non_overlap_ok": len({row["path"] for row in flat}) == len(flat),
    }


def run_stage2_destroy_leverage(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    bundle_manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    rows_path = output_dir / "track22r_destroy_leverage_equal_steps_rows.csv"
    rows = _read_csv(rows_path) if args.resume else []
    completed = {
        (row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0))
        for row in rows
    }
    bundles = [str(row["path"]) for row in bundle_manifest["roles"]["stage2_probe"]]
    seeds = _parse_int_list(args.stage2_seeds)
    for bundle in bundles:
        for seed in seeds:
            for algorithm in ("operator_select", "worst_removal_fixed", "best_of_k_destroy"):
                key = (algorithm, bundle, int(seed))
                if key in completed:
                    continue
                step_count = stage2_step_count_for_scale(_scale_label(bundle), args)
                _log(progress_path, f"Stage2 equal-steps run {algorithm} bundle={bundle} seed={seed} steps={step_count}")
                if algorithm == "operator_select":
                    row = run_operator_select_steps(bundle, seed=int(seed), step_count=int(step_count))
                elif algorithm == "worst_removal_fixed":
                    row = run_worst_removal_steps(bundle, seed=int(seed), step_count=int(step_count))
                else:
                    row = run_best_of_k_steps(
                        bundle,
                        seed=int(seed),
                        step_count=int(step_count),
                        candidate_k=int(args.stage2_best_of_k),
                    )
                row["algorithm"] = algorithm
                row["track"] = "track22r"
                row["evidence_role"] = "DESTROY_LEVERAGE_GATE"
                row["probe_mode"] = EQUAL_STEPS_ORACLE
                row = annotate_stage2_budget(row)
                rows.append(row)
                _write_csv(rows_path, rows)

    equal_eval_rows_path = output_dir / "track22r_destroy_leverage_equal_eval_rows.csv"
    equal_eval_rows = _read_csv(equal_eval_rows_path) if args.resume else []
    completed_equal_eval = {
        (row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0))
        for row in equal_eval_rows
    }
    for bundle in bundles:
        for seed in seeds:
            for algorithm in ("operator_select", "worst_removal_fixed", "best_of_k_destroy"):
                key = (algorithm, bundle, int(seed))
                if key in completed_equal_eval:
                    continue
                eval_budget = stage2_eval_floor_for_scale(_scale_label(bundle))
                _log(progress_path, f"Stage2 equal-eval reference {algorithm} bundle={bundle} seed={seed} eval_budget={eval_budget}")
                if algorithm == "operator_select":
                    row = run_operator_select_episode(bundle, seed=int(seed), eval_budget=int(eval_budget))
                elif algorithm == "worst_removal_fixed":
                    row = run_worst_removal_episode(bundle, seed=int(seed), eval_budget=int(eval_budget))
                else:
                    row = run_best_of_k_episode(
                        bundle,
                        seed=int(seed),
                        eval_budget=int(eval_budget),
                        candidate_k=int(args.stage2_best_of_k),
                    )
                row["algorithm"] = algorithm
                row["track"] = "track22r"
                row["evidence_role"] = "DESTROY_LEVERAGE_REFERENCE_ONLY"
                row["probe_mode"] = EQUAL_EVAL_REFERENCE
                row = annotate_stage2_budget(row)
                equal_eval_rows.append(row)
                _write_csv(equal_eval_rows_path, equal_eval_rows)

    anchor_rows_path = output_dir / "track22r_pilot21_anchor_rows.csv"
    anchor_rows = _read_csv(anchor_rows_path) if args.resume else []
    completed_anchor = {
        (row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0))
        for row in anchor_rows
    }
    for bundle in list(PILOT21_STAGE0_BUNDLES):
        for seed in _parse_int_list(args.stage2_anchor_seeds):
            for algorithm in ("operator_select", "worst_removal_fixed", "best_of_k_destroy"):
                key = (algorithm, bundle, int(seed))
                if key in completed_anchor:
                    continue
                _log(progress_path, f"Stage2 Pilot21 anchor {algorithm} bundle={bundle} seed={seed}")
                if algorithm == "operator_select":
                    row = run_operator_select_episode(bundle, seed=int(seed), eval_budget=int(args.stage2_anchor_eval_budget))
                elif algorithm == "worst_removal_fixed":
                    row = run_worst_removal_episode(bundle, seed=int(seed), eval_budget=int(args.stage2_anchor_eval_budget))
                else:
                    row = run_best_of_k_episode(
                        bundle,
                        seed=int(seed),
                        eval_budget=int(args.stage2_anchor_eval_budget),
                        candidate_k=int(args.stage2_best_of_k),
                    )
                row["algorithm"] = algorithm
                row["track"] = "track22r"
                row["evidence_role"] = "PILOT21_ANCHOR_REFERENCE_ONLY"
                row["probe_mode"] = PILOT21_ANCHOR
                anchor_rows.append(row)
                _write_csv(anchor_rows_path, anchor_rows)

    combined_rows = [*rows, *equal_eval_rows, *anchor_rows]
    _write_csv(output_dir / "track22r_destroy_leverage_all_rows.csv", combined_rows)
    return combined_rows


def summarize_stage2_destroy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gate_rows = [row for row in rows if str(row.get("probe_mode") or EQUAL_STEPS_ORACLE) == EQUAL_STEPS_ORACLE]
    equal_eval_rows = [row for row in rows if str(row.get("probe_mode") or "") == EQUAL_EVAL_REFERENCE]
    anchor_rows = [row for row in rows if str(row.get("probe_mode") or "") == PILOT21_ANCHOR]
    if not gate_rows:
        raise Track22Halt("HALT_STAGE2_NO_GATE_ROWS", "Stage2 has no equal-steps oracle rows for verdict.")
    assert_no_underpowered_for_verdict(gate_rows, stage="Stage2 equal-steps oracle")
    by_scale: dict[str, dict[str, list[float]]] = {}
    by_bundle: dict[str, dict[str, list[float]]] = {}
    for row in gate_rows:
        algo = str(row.get("algorithm", ""))
        bundle = str(row.get("bundle", ""))
        scale = str(row.get("scale") or _scale_label(bundle))
        best = _float(row.get("best_obj"))
        by_scale.setdefault(scale, {}).setdefault(algo, []).append(best)
        by_bundle.setdefault(bundle, {}).setdefault(algo, []).append(best)
    scale_rows = [_headroom_row(scale, algos) for scale, algos in sorted(by_scale.items())]
    bundle_rows = [_headroom_row(bundle, algos) for bundle, algos in sorted(by_bundle.items())]
    overall = _headroom_row("overall", _merge_algo_values(by_scale.values()))
    max_scale_headroom = max((_finite_or(row["best_of_k_headroom_pct"], -math.inf) for row in scale_rows), default=math.nan)
    worker_ok = all(_truthy(row.get("worker_integrity_ok")) for row in rows)
    zero_violations = _all_zero(gate_rows, "violation_count")
    if not worker_ok:
        status = HALT_WORKER_INTEGRITY
        reason = "At least one Stage2 row did not use the py313/NumPy 2.3.5 worker."
    elif not zero_violations:
        status = "HALT_STAGE2_VIOLATION"
        reason = "At least one Stage2 row has nonzero violation_count."
    elif math.isfinite(max_scale_headroom) and max_scale_headroom >= 3.0:
        status = DESTROY_LEVERAGE_CLEAN
        reason = f"Clean best-of-k destroy leverage >=3% on at least one scale; max_scale={max_scale_headroom:.3f}%."
    elif math.isfinite(max_scale_headroom) and max_scale_headroom >= 1.0:
        status = LEVERAGE_MARGINAL
        reason = f"Clean best-of-k destroy leverage is marginal; max_scale={max_scale_headroom:.3f}%."
    else:
        status = NO_DESTROY_LEVERAGE_CLEAN
        reason = f"Clean best-of-k destroy leverage <1%; max_scale={max_scale_headroom:.3f}%."
    return {
        "status": status,
        "reason": reason,
        "row_count": len(gate_rows),
        "all_row_count": len(rows),
        "worker_integrity_ok": worker_ok,
        "zero_violations": zero_violations,
        "overall": overall,
        "scale_rows": scale_rows,
        "bundle_rows": bundle_rows,
        "budget_summary": budget_summary(gate_rows),
        "equal_eval_reference": reference_headroom_summary(equal_eval_rows),
        "pilot21_anchor_reference": reference_headroom_summary(anchor_rows, old_reference_pct=6.261),
        "max_scale_best_of_k_headroom_pct": max_scale_headroom,
        "gate_rule": "Equal-steps oracle only: DESTROY_LEVERAGE_CLEAN if any scale >=3%; LEVERAGE_MARGINAL if any scale is 1-3%; NO_DESTROY_LEVERAGE_CLEAN if all scales <1%. Equal-eval rows are reference only.",
    }


def stage2_eval_floor_for_scale(scale: str) -> int:
    return int(STAGE2_EVAL_FLOORS.get(str(scale), max(STAGE2_EVAL_FLOORS.values())))


def stage2_step_count_for_scale(scale: str, args: argparse.Namespace) -> int:
    if str(scale) == "25c":
        return max(stage2_eval_floor_for_scale(scale), int(args.stage2_25c_steps))
    if str(scale) == "50c":
        return max(stage2_eval_floor_for_scale(scale), int(args.stage2_50c_steps))
    return stage2_eval_floor_for_scale(scale)


def annotate_stage2_budget(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    scale = str(out.get("scale") or _scale_label(str(out.get("bundle", ""))))
    eval_floor = stage2_eval_floor_for_scale(scale)
    wall_floor = STAGE2_WALL_FLOOR_SECONDS
    actual_evals = _int_or(out.get("actual_evals"), 0)
    wall_seconds = _float(out.get("wall_time_seconds"))
    eval_ratio = float(actual_evals) / max(float(eval_floor), 1.0)
    wall_ratio = float(wall_seconds) / max(float(wall_floor), 1.0) if math.isfinite(wall_seconds) else 0.0
    status = OK_BUDGET if actual_evals >= eval_floor and wall_ratio >= 1.0 else UNDERPOWERED
    out.update(
        {
            "scale": scale,
            "budget_status": status,
            "eval_floor": int(eval_floor),
            "wall_floor_seconds": float(wall_floor),
            "eval_floor_ratio": float(eval_ratio),
            "wall_floor_ratio": float(wall_ratio),
        }
    )
    return out


def assert_no_underpowered_for_verdict(rows: list[dict[str, Any]], *, stage: str) -> None:
    underpowered = [row for row in rows if str(row.get("budget_status", "")) == UNDERPOWERED]
    if underpowered:
        sample = underpowered[0]
        raise Track22Halt(
            "HALT_UNDERPOWERED_VERDICT_ROW",
            (
                f"{stage} contains {len(underpowered)} UNDERPOWERED verdict rows; "
                f"sample algorithm={sample.get('algorithm')} bundle={sample.get('bundle')} "
                f"seed={sample.get('seed')} eval_ratio={sample.get('eval_floor_ratio')} "
                f"wall_ratio={sample.get('wall_floor_ratio')}"
            ),
        )


def budget_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "row_count": len(rows),
        "min_eval_floor_ratio": min((_finite_or(row.get("eval_floor_ratio"), math.inf) for row in rows), default=math.nan),
        "min_wall_floor_ratio": min((_finite_or(row.get("wall_floor_ratio"), math.inf) for row in rows), default=math.nan),
        "underpowered_count": sum(1 for row in rows if str(row.get("budget_status", "")) == UNDERPOWERED),
    }


def reference_headroom_summary(rows: list[dict[str, Any]], *, old_reference_pct: float | None = None) -> dict[str, Any]:
    if not rows:
        return {"row_count": 0}
    by_scale: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        algo = str(row.get("algorithm", ""))
        scale = str(row.get("scale") or _scale_label(str(row.get("bundle", ""))))
        by_scale.setdefault(scale, {}).setdefault(algo, []).append(_float(row.get("best_obj")))
    scale_rows = [_headroom_row(scale, algos) for scale, algos in sorted(by_scale.items())]
    overall = _headroom_row("overall", _merge_algo_values(by_scale.values()))
    max_scale = max((_finite_or(row["best_of_k_headroom_pct"], -math.inf) for row in scale_rows), default=math.nan)
    summary = {
        "row_count": len(rows),
        "overall": overall,
        "scale_rows": scale_rows,
        "max_scale_best_of_k_headroom_pct": max_scale,
        "underpowered_count": sum(1 for row in rows if str(row.get("budget_status", "")) == UNDERPOWERED),
        "verdict_role": "reference_only_not_used_for_track22r_verdict",
    }
    if old_reference_pct is not None:
        summary["old_reference_pct"] = float(old_reference_pct)
        summary["delta_vs_old_reference_pct"] = float(max_scale - float(old_reference_pct)) if math.isfinite(max_scale) else math.nan
    return summary


def run_operator_select_steps(bundle: str, *, seed: int, step_count: int) -> dict[str, Any]:
    alpha_d = BLOCK_DESTROY_IDS.index(ALPHA_UCB_CHOICE)
    alpha_r = BLOCK_REPAIR_IDS.index(ALPHA_UCB_CHOICE)
    q_idx = BLOCK_Q_RATIOS.index(0.40)
    threshold_idx = BLOCK_THRESHOLD_RATIOS.index(0.0025)
    exploration_idx = BLOCK_EXPLORATION_RATIOS.index(0.15)
    action = BlockDecodedAction(
        destroy_id=ALPHA_UCB_CHOICE,
        repair_id=ALPHA_UCB_CHOICE,
        q_ratio=0.40,
        threshold_ratio=0.0025,
        exploration_ratio=0.15,
        block_size=1,
        raw=(alpha_d, alpha_r, q_idx, threshold_idx, exploration_idx),
    )
    return _run_fixed_block_steps("operator_select", bundle, seed=seed, step_count=step_count, action=action)


def run_worst_removal_steps(bundle: str, *, seed: int, step_count: int) -> dict[str, Any]:
    d_idx = BLOCK_DESTROY_IDS.index("worst_customer_removal")
    r_idx = BLOCK_REPAIR_IDS.index(ALPHA_UCB_CHOICE)
    q_idx = BLOCK_Q_RATIOS.index(0.40)
    threshold_idx = BLOCK_THRESHOLD_RATIOS.index(0.0025)
    exploration_idx = BLOCK_EXPLORATION_RATIOS.index(0.0)
    action = BlockDecodedAction(
        destroy_id="worst_customer_removal",
        repair_id=ALPHA_UCB_CHOICE,
        q_ratio=0.40,
        threshold_ratio=0.0025,
        exploration_ratio=0.0,
        block_size=1,
        raw=(d_idx, r_idx, q_idx, threshold_idx, exploration_idx),
    )
    return _run_fixed_block_steps("worst_removal_fixed", bundle, seed=seed, step_count=step_count, action=action)


def _run_fixed_block_steps(
    algorithm: str,
    bundle: str,
    *,
    seed: int,
    step_count: int,
    action: BlockDecodedAction,
) -> dict[str, Any]:
    started = time.monotonic()
    response: dict[str, Any] = {}
    client = WorkerClient(bundle, seed=int(seed), max_evals=int(step_count) * 2 + 10)
    steps = 0
    try:
        response = _checked_worker_response(client.reset())
        for _ in range(int(step_count)):
            response = _checked_worker_response(client.block_step(action))
            steps += 1
    finally:
        client.close()
    row = _stage2_row_from_response(algorithm, bundle, seed=seed, target_steps=step_count, response=response, started=started, steps=steps)
    row["oracle_candidate_evals"] = int(row["actual_evals"])
    row["oracle_eval_overhead_vs_operator"] = 0
    return row


def run_best_of_k_steps(bundle: str, *, seed: int, step_count: int, candidate_k: int) -> dict[str, Any]:
    started = time.monotonic()
    response: dict[str, Any] = {}
    max_evals = stage2_best_of_k_worker_eval_cap(step_count=int(step_count), candidate_k=int(candidate_k))
    client = WorkerClient(bundle, seed=int(seed), max_evals=int(max_evals))
    steps = 0
    oracle_candidate_evals = 0
    try:
        response = _checked_worker_response(client.reset())
        for _ in range(int(step_count)):
            response = _checked_worker_response(
                client.best_of_k_destroy(
                    {
                        "candidate_k": int(candidate_k),
                        "destroy_ids": [value for value in DESTROY_IDS if value != ALPHA_UCB_CHOICE],
                        "repair_id": ALPHA_UCB_CHOICE,
                        "q_ratio": 0.40,
                        "threshold_ratio": 0.0025,
                    }
                )
            )
            steps += 1
            trace = response.get("trace", {}) or {}
            oracle_candidate_evals += int(trace.get("candidate_k_evaluated", 0) or 0)
    finally:
        client.close()
    row = _stage2_row_from_response("best_of_k_destroy", bundle, seed=seed, target_steps=step_count, response=response, started=started, steps=steps)
    row["candidate_k"] = int(candidate_k)
    row["oracle_candidate_evals"] = int(oracle_candidate_evals)
    row["oracle_eval_overhead_vs_operator"] = int(max(0, int(row["actual_evals"]) - int(step_count)))
    return row


def _stage2_row_from_response(
    algorithm: str,
    bundle: str,
    *,
    seed: int,
    target_steps: int,
    response: dict[str, Any],
    started: float,
    steps: int,
) -> dict[str, Any]:
    trace = response.get("trace", {}) or {}
    return {
        "algorithm": algorithm,
        "bundle": str(bundle),
        "scale": _scale_label(str(bundle)),
        "seed": int(seed),
        "target_steps": int(target_steps),
        "best_obj": float(response.get("best_obj", 0.0)),
        "current_obj": float(response.get("current_obj", 0.0)),
        "actual_evals": int(response.get("actual_evals", 0)),
        "candidate_scores": int(response.get("candidate_scores", 0) or 0),
        "violation_count": int(response.get("violation_count", 0)),
        "steps": int(steps),
        "wall_time_seconds": float(time.monotonic() - started),
        "worker_python_executable": str(trace.get("worker_python_executable", "")),
        "worker_numpy_version": str(trace.get("worker_numpy_version", "")),
        "worker_integrity_ok": _worker_integrity_ok(trace),
        "control_mode": str(trace.get("control_mode", "")),
        "trace_destroy_id": str(trace.get("destroy_id", "")),
        "trace_repair_id": str(trace.get("repair_id", "")),
        "candidate_k_evaluated": int(trace.get("candidate_k_evaluated", 0) or 0),
    }


def stage2_best_of_k_worker_eval_cap(*, step_count: int, candidate_k: int) -> int:
    return int(step_count) * max(50, int(candidate_k) * 12) + 100


def _checked_worker_response(response: dict[str, Any]) -> dict[str, Any]:
    if not bool(response.get("ok", False)):
        raise Track22Halt("HALT_WORKER_RESPONSE", str(response.get("error", "worker returned ok=false")))
    return response


def run_stage3_learned_destroy(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    state: dict[str, Any],
) -> dict[str, Any]:
    _require_torch_available()
    import torch

    bundle_manifest = state["bundle_manifest"]
    train_bundles = [str(row["path"]) for row in bundle_manifest["roles"]["stage3_train"]]
    validation_bundles = [str(row["path"]) for row in bundle_manifest["roles"]["stage3_val"]]
    test_bundles = [str(row["path"]) for row in bundle_manifest["roles"]["stage3_test"]]
    overlap = sorted((set(train_bundles) | set(validation_bundles)) & set(test_bundles))
    if overlap:
        raise Track22Halt("HALT_STAGE3_OVERLAP", f"train/validation/test overlap: {overlap}")

    model = make_learned_destroy_actor_critic(seed=int(args.stage3_seed), hidden_size=int(args.stage3_hidden_size))
    optimizer = torch.optim.Adam(model.parameters(), lr=float(args.stage3_learning_rate))
    model_path = output_dir / "track22_learned_destroy_final_model.pt"
    best_model_path = output_dir / "track22_learned_destroy_best_validation_model.pt"
    update_rows: list[dict[str, Any]] = _read_csv(output_dir / "track22_learned_destroy_update_log.csv") if args.resume else []
    episode_rows: list[dict[str, Any]] = _read_csv(output_dir / "track22_learned_destroy_training_rows.csv") if args.resume else []
    validation_rows: list[dict[str, Any]] = _read_csv(output_dir / "track22_learned_destroy_validation_rows.csv") if args.resume else []

    train_started = time.monotonic()
    pending_groups: list[list[Any]] = []
    best_validation_gain = -math.inf
    best_validation_summary: dict[str, Any] | None = None
    total_groups = int(math.ceil(int(args.stage3_train_episodes) / max(1, int(args.stage3_pomo_rollouts))))
    initial_validation = eval_learned_vs_operator(
        model,
        validation_bundles,
        _parse_int_list(args.stage3_validation_seeds),
        eval_budget=int(args.stage3_validation_eval_budget),
        max_customers=int(args.stage3_max_customers),
        rows_path=output_dir / "track22_learned_destroy_validation_detail_rows.csv",
        tag="initial",
    )
    validation_rows.append(initial_validation)
    _write_csv(output_dir / "track22_learned_destroy_validation_rows.csv", validation_rows)
    best_validation_gain = float(initial_validation["avg_improvement_pct_vs_operator_select"])
    best_validation_summary = dict(initial_validation)
    save_learned_destroy_policy(best_model_path, model, metadata={"reason": "initial_validation", **best_validation_summary})

    for group_index in range(total_groups):
        if time.monotonic() - train_started >= float(args.stage3_max_train_seconds):
            break
        bundle = train_bundles[int(group_index) % len(train_bundles)]
        group: list[Any] = []
        for rollout_idx in range(int(args.stage3_pomo_rollouts)):
            episode_index = group_index * int(args.stage3_pomo_rollouts) + rollout_idx
            if episode_index >= int(args.stage3_train_episodes):
                break
            episode = run_learned_episode_for_train(
                model,
                bundle,
                seed=int(args.stage3_seed) + int(episode_index),
                eval_budget=int(args.stage3_train_eval_budget),
                max_customers=int(args.stage3_max_customers),
            )
            group.append(episode)
            row = _episode_row(episode)
            row["pomo_group"] = int(group_index)
            row["pomo_rollout"] = int(rollout_idx)
            episode_rows.append(row)
            _write_csv(output_dir / "track22_learned_destroy_training_rows.csv", episode_rows)
        if group:
            pending_groups.append(group)
        if len(pending_groups) >= int(args.stage3_rollout_min_groups):
            update_index = len(update_rows)
            lr = linear_annealed_lr(
                initial_lr=float(args.stage3_learning_rate),
                final_lr=float(args.stage3_final_learning_rate),
                update_index=update_index,
                total_updates=max(1, total_groups // max(1, int(args.stage3_rollout_min_groups))),
            )
            for param_group in optimizer.param_groups:
                param_group["lr"] = lr
            batch = flatten_pomo_shared_baseline(pending_groups)
            metrics = ppo_update_learned_stable(
                model,
                optimizer,
                batch,
                epochs=int(args.stage3_ppo_epochs),
                minibatch_size=int(args.stage3_minibatch_size),
                clip_range=float(args.stage3_clip_range),
                value_coef=float(args.stage3_value_coef),
                entropy_coef=float(args.stage3_entropy_coef),
                max_grad_norm=float(args.stage3_max_grad_norm),
                target_kl=float(args.stage3_target_kl),
            )
            update_row = {
                "update_index": int(update_index),
                "group_index": int(group_index),
                "learning_rate": float(lr),
                **metrics,
            }
            update_rows.append(update_row)
            _write_csv(output_dir / "track22_learned_destroy_update_log.csv", update_rows)
            if (update_index + 1) % int(args.stage3_validation_every_updates) == 0:
                summary = eval_learned_vs_operator(
                    model,
                    validation_bundles,
                    _parse_int_list(args.stage3_validation_seeds),
                    eval_budget=int(args.stage3_validation_eval_budget),
                    max_customers=int(args.stage3_max_customers),
                    rows_path=output_dir / "track22_learned_destroy_validation_detail_rows.csv",
                    tag=f"update_{update_index + 1:04d}",
                )
                summary["update_index"] = int(update_index)
                validation_rows.append(summary)
                _write_csv(output_dir / "track22_learned_destroy_validation_rows.csv", validation_rows)
                gain = float(summary["avg_improvement_pct_vs_operator_select"])
                if gain > best_validation_gain:
                    best_validation_gain = gain
                    best_validation_summary = dict(summary)
                    save_learned_destroy_policy(best_model_path, model, metadata={"reason": "best_validation", **best_validation_summary})
            pending_groups = []

    save_learned_destroy_policy(model_path, model, metadata={"train_episodes_requested": int(args.stage3_train_episodes)})
    if best_model_path.exists():
        eval_model = load_learned_destroy_policy(best_model_path)
    else:
        eval_model = model
    test_rows = run_learned_test_rows(
        eval_model,
        test_bundles,
        _parse_int_list(args.stage3_test_seeds),
        eval_budget=int(args.stage3_test_eval_budget),
        max_customers=int(args.stage3_max_customers),
        rows_path=output_dir / "track22_learned_destroy_test_rows.csv",
    )
    test_summary = summarize_learned_rows(test_rows)
    status = learned_status(test_summary)
    return {
        "status": status,
        "reason": learned_reason(test_summary),
        "trained": True,
        "train_bundles": train_bundles,
        "validation_bundles": validation_bundles,
        "test_bundles": test_bundles,
        "train_episode_count": len(episode_rows),
        "update_count": len(update_rows),
        "validation_count": len(validation_rows),
        "best_validation_gain_pct_vs_operator_select": best_validation_gain,
        "best_validation_summary": best_validation_summary or {},
        "model_path": str(model_path),
        "best_model_path": str(best_model_path),
        "test_summary": test_summary,
        "wall_time_seconds": float(time.monotonic() - train_started),
    }


def run_learned_episode_for_train(model: Any, bundle: str, *, seed: int, eval_budget: int, max_customers: int) -> Any:
    from .pilot20_learned_destroy_phaseA import run_learned_episode

    return run_learned_episode(
        model,
        bundle,
        seed=int(seed),
        eval_budget=int(eval_budget),
        max_customers=int(max_customers),
        deterministic=False,
    )


def eval_learned_vs_operator(
    model: Any,
    bundles: list[str],
    seeds: list[int],
    *,
    eval_budget: int,
    max_customers: int,
    rows_path: Path,
    tag: str,
) -> dict[str, Any]:
    rows = _read_csv(rows_path)
    completed = {
        (row.get("tag"), row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0))
        for row in rows
    }
    for bundle in bundles:
        for seed in seeds:
            for algorithm in ("learned_destroy", "operator_select"):
                key = (tag, algorithm, bundle, int(seed))
                if key in completed:
                    continue
                row = _run_algorithm_row(
                    algorithm,
                    model,
                    bundle,
                    seed=int(seed),
                    eval_budget=int(eval_budget),
                    max_customers=int(max_customers),
                )
                row["tag"] = tag
                row["evidence_role"] = "VALIDATION"
                row.update(annotate_stage3_budget(row, eval_budget=int(eval_budget)))
                rows.append(row)
                _write_csv(rows_path, rows)
    tagged = [row for row in rows if row.get("tag") == tag]
    summary = summarize_learned_rows(tagged)
    return {
        "tag": tag,
        "validation_mean_obj": summary["learned_mean_obj"],
        "operator_mean_obj": summary["operator_mean_obj"],
        "avg_improvement_pct_vs_operator_select": summary["avg_vs_operator"],
        "min_scale_improvement_pct_vs_operator_select": summary["min_scale_vs_operator"],
        "zero_violations": summary["zero_violations"],
        "worker_integrity_ok": summary["worker_ok"],
        "row_count": len(tagged),
    }


def run_learned_test_rows(
    model: Any,
    bundles: list[str],
    seeds: list[int],
    *,
    eval_budget: int,
    max_customers: int,
    rows_path: Path,
) -> list[dict[str, Any]]:
    rows = _read_csv(rows_path)
    completed = {
        (row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0))
        for row in rows
    }
    for bundle in bundles:
        for seed in seeds:
            for algorithm in ("learned_destroy", "operator_select", "random_operator", "worst_removal_fixed"):
                key = (algorithm, bundle, int(seed))
                if key in completed:
                    continue
                row = _run_algorithm_row(
                    algorithm,
                    model,
                    bundle,
                    seed=int(seed),
                    eval_budget=int(eval_budget),
                    max_customers=int(max_customers),
                )
                row["evidence_role"] = "INDEPENDENT_TEST"
                row.update(annotate_stage3_budget(row, eval_budget=int(eval_budget)))
                rows.append(row)
                _write_csv(rows_path, rows)
    return rows


def summarize_learned_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    verdict_rows = [row for row in rows if row.get("evidence_role") == "INDEPENDENT_TEST"]
    if verdict_rows:
        assert_no_underpowered_for_verdict(verdict_rows, stage="Stage3 independent test")
    by_key = {(row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0)): row for row in rows}
    learned = [row for row in rows if row.get("algorithm") == "learned_destroy"]
    improvements: list[float] = []
    random_improvements: list[float] = []
    worst_improvements: list[float] = []
    by_scale: dict[str, list[float]] = {}
    learned_objs: list[float] = []
    operator_objs: list[float] = []
    for row in learned:
        key = (row.get("bundle"), int(row.get("seed") or 0))
        op = by_key.get(("operator_select", *key))
        random_row = by_key.get(("random_operator", *key))
        worst = by_key.get(("worst_removal_fixed", *key))
        learned_obj = _float(row.get("best_obj"))
        learned_objs.append(learned_obj)
        if op:
            op_obj = _float(op.get("best_obj"))
            operator_objs.append(op_obj)
            value = _improvement_pct(op_obj, learned_obj)
            improvements.append(value)
            by_scale.setdefault(str(row.get("scale") or _scale_label(str(row.get("bundle", "")))), []).append(value)
        if random_row:
            random_improvements.append(_improvement_pct(_float(random_row.get("best_obj")), learned_obj))
        if worst:
            worst_improvements.append(_improvement_pct(_float(worst.get("best_obj")), learned_obj))
    return {
        "avg_vs_operator": _mean(improvements),
        "min_scale_vs_operator": min((_mean(values) for values in by_scale.values()), default=math.nan),
        "avg_vs_random": _mean(random_improvements),
        "avg_vs_worst": _mean(worst_improvements),
        "scale_improvement_pct": {scale: _mean(values) for scale, values in sorted(by_scale.items())},
        "zero_violations": _all_zero(learned, "violation_count"),
        "worker_ok": all(_truthy(row.get("worker_integrity_ok")) for row in rows),
        "learned_mean_obj": _mean(learned_objs),
        "operator_mean_obj": _mean(operator_objs),
        "row_count": len(rows),
        "budget_summary": budget_summary(rows),
    }


def annotate_stage3_budget(row: dict[str, Any], *, eval_budget: int) -> dict[str, Any]:
    actual = _int_or(row.get("actual_evals"), 0)
    ratio = float(actual) / max(float(eval_budget), 1.0)
    return {
        "budget_status": OK_BUDGET if actual >= int(eval_budget) else UNDERPOWERED,
        "eval_floor": int(eval_budget),
        "eval_floor_ratio": float(ratio),
        "wall_floor_seconds": "",
        "wall_floor_ratio": "",
    }


def learned_status(summary: dict[str, Any]) -> str:
    if not summary["worker_ok"]:
        return HALT_WORKER_INTEGRITY
    if not summary["zero_violations"]:
        return "HALT_STAGE3_VIOLATION"
    if summary["avg_vs_operator"] >= 2.0 and summary["min_scale_vs_operator"] >= 0.0 and summary["avg_vs_random"] > 0.0 and summary["avg_vs_worst"] > 0.0:
        return PASS_LEARNED_DESTROY_CLEAN
    if summary["avg_vs_operator"] >= 0.0 and summary["min_scale_vs_operator"] >= 0.0:
        return WEAK_LEARNED_DESTROY_CLEAN
    return HALT_LEARNED_DESTROY_CLEAN


def learned_reason(summary: dict[str, Any]) -> str:
    return (
        f"avg_vs_operator={summary['avg_vs_operator']:.3f}%, "
        f"min_scale={summary['min_scale_vs_operator']:.3f}%, "
        f"avg_vs_random={summary['avg_vs_random']:.3f}%, "
        f"avg_vs_worst={summary['avg_vs_worst']:.3f}%, "
        f"zero_violations={summary['zero_violations']}, worker_ok={summary['worker_ok']}"
    )


def run_stage4_carbon_timing(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    state: dict[str, Any],
) -> dict[str, Any]:
    manifest = state.get("bundle_manifest") or ensure_track22_bundles(args, output_dir)
    bundles = [str(row["path"]) for row in manifest["roles"]["stage2_probe"][: int(args.stage4_bundle_count)]]
    rows_path = output_dir / "track22_carbon_timing_rows.csv"
    rows = _read_csv(rows_path) if args.resume else []
    completed = {(row.get("bundle"), int(row.get("seed") or 0), row.get("diagnostic_role", "")) for row in rows}
    for bundle in bundles:
        for seed in _parse_int_list(args.stage4_seeds):
            key = (bundle, int(seed), "default_winner_route_replay")
            if key in completed:
                continue
            _log(progress_path, f"Stage4 carbon replay bundle={bundle} seed={seed}")
            row = carbon_replay_row(
                bundle,
                seed=int(seed),
                eval_budget=int(args.stage4_eval_budget),
                max_runtime_seconds=float(args.stage4_max_runtime_seconds),
                diagnostic_role="default_winner_route_replay",
                candidate_evals=int(args.stage4_candidate_evals),
            )
            rows.append(row)
            _write_csv(rows_path, rows)
    summary = summarize_carbon_rows(rows)
    if summary["status"] == CARBON_CEILING_TOO_SMALL_DEFAULT or summary["avg_improvement_pct"] < 2.0:
        diagnostic = run_ev_heavy_diagnostic(args, output_dir, progress_path, manifest)
        if diagnostic:
            rows.append(diagnostic)
            _write_csv(rows_path, rows)
            summary = summarize_carbon_rows(rows)
            summary["ev_heavy_diagnostic"] = diagnostic
    return summary


def carbon_replay_row(
    bundle: str,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    diagnostic_role: str,
    candidate_evals: int,
) -> dict[str, Any]:
    loaded = load_search_bundle(bundle)
    result = run_winner_kernel(
        bundle,
        config=WinnerKernelConfig(seed=int(seed), eval_budget=int(eval_budget), max_runtime_seconds=float(max_runtime_seconds)),
    )
    solution = result["best_solution"]
    return carbon_compare_solution(
        bundle,
        loaded,
        solution,
        seed=seed,
        diagnostic_role=diagnostic_role,
        source="winner_kernel",
        candidate_evals=int(candidate_evals),
        prices=DEFAULT_PRICES,
    )


def carbon_compare_solution(
    bundle: str,
    loaded: Any,
    solution: Any,
    *,
    seed: int,
    diagnostic_role: str,
    source: str,
    candidate_evals: int = STAGE4_CANDIDATE_EVAL_FLOOR,
    prices: Any = DEFAULT_PRICES,
) -> dict[str, Any]:
    aware = replay_fixed_route_charging(solution, loaded.instance, loaded.carbon_profile, prices, strategy="aware")
    naive = replay_fixed_route_charging(solution, loaded.instance, loaded.carbon_profile, prices, strategy="naive")
    aware_violations = check_solution(aware, loaded.instance, prices)
    naive_violations = check_solution(naive, loaded.instance, prices)
    aware_metrics = evaluate(aware, loaded.instance, loaded.carbon_profile, prices)
    naive_metrics = evaluate(naive, loaded.instance, loaded.carbon_profile, prices)
    aware_cost = float(aware_metrics.get("total_cost", model_cost(aware, EvaluationContext(loaded.instance, loaded.carbon_profile))))
    naive_cost = float(naive_metrics.get("total_cost", model_cost(naive, EvaluationContext(loaded.instance, loaded.carbon_profile))))
    candidate_summary = evaluate_carbon_candidate_set(
        loaded,
        naive=naive,
        aware=aware,
        prices=prices,
        candidate_evals=int(candidate_evals),
    )
    best_aware_cost = float(candidate_summary["best_aware_cost"])
    if best_aware_cost > float(naive_cost) + 1e-9:
        raise Track22Halt("HALT_CARBON_AWARE_WORSE_THAN_NAIVE", f"aware candidate set failed to include naive: aware={best_aware_cost} naive={naive_cost}")
    row = {
        "bundle": str(bundle),
        "scale": _scale_label(str(bundle)),
        "seed": int(seed),
        "diagnostic_role": diagnostic_role,
        "source": source,
        "route_count": len(solution.routes),
        "ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
        "aware_charging_actions": len(aware.charging_actions),
        "naive_charging_actions": len(naive.charging_actions),
        "aware_cost": float(aware_cost),
        "naive_cost": float(naive_cost),
        "best_aware_cost": best_aware_cost,
        "best_aware_policy": str(candidate_summary["best_aware_policy"]),
        "improvement_pct": _improvement_pct(float(naive_cost), best_aware_cost),
        "aware_violation_count": len(aware_violations),
        "naive_violation_count": len(naive_violations),
        "best_aware_violation_count": int(candidate_summary["best_aware_violation_count"]),
        "candidate_evaluate_count": int(candidate_summary["candidate_evaluate_count"]),
        "candidate_unique_count": int(candidate_summary["candidate_unique_count"]),
        "aware_charging_carbon_kg": float(aware_metrics.get("E_ev_indirect", 0.0)),
        "naive_charging_carbon_kg": float(naive_metrics.get("E_ev_indirect", 0.0)),
        "aware_cost_carbon": float(aware_metrics.get("cost_carbon", 0.0)),
        "naive_cost_carbon": float(naive_metrics.get("cost_carbon", 0.0)),
        "aware_total_cost": float(aware_metrics.get("total_cost", aware_cost)),
        "naive_total_cost": float(naive_metrics.get("total_cost", naive_cost)),
        "carbon_cost_share_pct": carbon_cost_share_pct(naive_metrics),
    }
    row.update(annotate_stage4_budget(row))
    return row


def evaluate_carbon_candidate_set(
    loaded: Any,
    *,
    naive: Solution,
    aware: Solution,
    prices: Any,
    candidate_evals: int,
) -> dict[str, Any]:
    candidates = [("naive", naive), ("aware", aware)]
    best_policy = ""
    best_cost = math.inf
    best_violations: list[Any] = []
    unique_signatures: set[str] = set()
    evaluated = 0
    for idx in range(max(int(candidate_evals), STAGE4_CANDIDATE_EVAL_FLOOR)):
        policy, solution = candidates[idx % len(candidates)]
        violations = check_solution(solution, loaded.instance, prices)
        if violations:
            raise Track22Halt("HALT_CARBON_CANDIDATE_VIOLATION", f"candidate policy={policy} has {len(violations)} violations")
        metrics = evaluate(solution, loaded.instance, loaded.carbon_profile, prices)
        cost = float(metrics.get("total_cost", model_cost(solution, EvaluationContext(loaded.instance, loaded.carbon_profile))))
        evaluated += 1
        unique_signatures.add(_solution_signature(solution))
        if cost < best_cost:
            best_cost = cost
            best_policy = policy
            best_violations = violations
    return {
        "candidate_evaluate_count": int(evaluated),
        "candidate_unique_count": int(len(unique_signatures)),
        "best_aware_cost": float(best_cost),
        "best_aware_policy": best_policy,
        "best_aware_violation_count": int(len(best_violations)),
    }


def annotate_stage4_budget(row: dict[str, Any]) -> dict[str, Any]:
    candidate_count = _int_or(row.get("candidate_evaluate_count"), 0)
    ratio = float(candidate_count) / float(STAGE4_CANDIDATE_EVAL_FLOOR)
    return {
        "budget_status": OK_BUDGET if candidate_count >= STAGE4_CANDIDATE_EVAL_FLOOR else UNDERPOWERED,
        "candidate_evaluate_floor": int(STAGE4_CANDIDATE_EVAL_FLOOR),
        "candidate_evaluate_floor_ratio": float(ratio),
    }


def carbon_cost_share_pct(metrics: dict[str, Any]) -> float:
    total = abs(_float(metrics.get("total_cost")))
    if total <= 1e-12 or not math.isfinite(total):
        return math.nan
    return float(_float(metrics.get("cost_carbon")) / total * 100.0)


def _solution_signature(solution: Solution) -> str:
    routes = [
        (route.vehicle_id, route.vehicle_type, route.home_depot_id, tuple(route.node_sequence))
        for route in solution.routes
    ]
    actions = [
        (action.vehicle_id, action.station_id, round(float(action.energy_kwh), 9), round(float(action.occupancy_minutes), 9), round(float(action.charge_start_second), 9))
        for action in solution.charging_actions
    ]
    return json.dumps({"routes": routes, "actions": actions}, sort_keys=True)


def run_ev_heavy_diagnostic(args: argparse.Namespace, output_dir: Path, progress_path: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    bundle = str(manifest["roles"]["stage2_probe"][0]["path"])
    try:
        loaded = load_search_bundle(bundle)
        customer_count = len([node for node in loaded.instance.nodes if node.node_type.lower() == "c"])
        limits = ev_heavy_fleet_limits_for_counts(
            num_cv=int(loaded.instance.num_cv or 0),
            num_ev=int(loaded.instance.num_ev or 0),
            customer_count=customer_count,
        )
        prices = replace(DEFAULT_PRICES, carbon_price=float(DEFAULT_PRICES.carbon_price) * float(args.stage4_ev_heavy_carbon_price_factor))
        ev_instance = replace(loaded.instance, num_cv=int(limits.cv), num_ev=int(limits.ev))
        seed_solution = build_initial_solution(
            ev_instance,
            loaded.carbon_profile,
            prices,
            fleet_limits=limits,
            introduce_ev=True,
            require_charging_signal=True,
        )
        synthetic_loaded = replace(loaded, instance=ev_instance)
        row = carbon_compare_solution(
            bundle,
            synthetic_loaded,
            seed_solution,
            seed=int(args.stage4_ev_heavy_seed),
            diagnostic_role="ev_heavy_diagnostic_only",
            source="ev_heavy_initial_solution",
            candidate_evals=int(args.stage4_candidate_evals),
            prices=prices,
        )
        row["diagnostic_only"] = True
        row["carbon_price_factor"] = float(args.stage4_ev_heavy_carbon_price_factor)
        row["ev_heavy_cv_cap"] = int(limits.cv)
        row["ev_heavy_ev_cap"] = int(limits.ev)
        _log(progress_path, "Stage4 EV-heavy diagnostic succeeded")
        return row
    except Exception as exc:
        _log(progress_path, f"Stage4 EV-heavy diagnostic failed: {type(exc).__name__}: {exc}")
        return {
            "bundle": bundle,
            "scale": _scale_label(bundle),
            "seed": int(args.stage4_ev_heavy_seed),
            "diagnostic_role": "ev_heavy_diagnostic_only",
            "source": "ev_heavy_initial_solution",
            "error": f"{type(exc).__name__}: {exc}",
            "improvement_pct": math.nan,
        }


def ev_heavy_fleet_limits_for_counts(*, num_cv: int, num_ev: int, customer_count: int) -> FleetLimits:
    cv_cap = max(1, int(num_cv))
    extra_ev = max(1, int(math.ceil(max(int(customer_count), 1) * 0.20)))
    ev_cap = max(int(num_ev) + 1, int(num_ev) + extra_ev)
    return FleetLimits(cv=cv_cap, ev=ev_cap, source="track22r_ev_heavy_diagnostic")


def summarize_carbon_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gate_rows = [row for row in rows if row.get("diagnostic_role") == "default_winner_route_replay"]
    if not gate_rows:
        raise Track22Halt("HALT_CARBON_NO_GATE_ROWS", "Stage4 has no default scenario gate rows.")
    assert_no_underpowered_for_verdict(gate_rows, stage="Stage4 carbon timing")
    worse = [
        row for row in gate_rows
        if _is_number(row.get("best_aware_cost"))
        and _is_number(row.get("naive_cost"))
        and float(row["best_aware_cost"]) > float(row["naive_cost"]) + 1e-9
    ]
    if worse:
        sample = worse[0]
        raise Track22Halt(
            "HALT_CARBON_AWARE_WORSE_THAN_NAIVE",
            f"aware candidate set worse than naive for bundle={sample.get('bundle')} seed={sample.get('seed')}: aware={sample.get('best_aware_cost')} naive={sample.get('naive_cost')}",
        )
    improvements = [_float(row.get("improvement_pct")) for row in gate_rows if _is_number(row.get("improvement_pct"))]
    zero_violations = (
        _all_zero(gate_rows, "aware_violation_count")
        and _all_zero(gate_rows, "naive_violation_count")
        and _all_zero(gate_rows, "best_aware_violation_count")
    )
    avg = _mean(improvements)
    carbon_shares = [_float(row.get("carbon_cost_share_pct")) for row in gate_rows if _is_number(row.get("carbon_cost_share_pct"))]
    ceiling = max(carbon_shares, default=math.nan)
    if not zero_violations:
        status = "HALT_CARBON_TIMING_VIOLATION"
        reason = "At least one aware/naive carbon replay row has nonzero violations."
    elif math.isfinite(ceiling) and ceiling < 0.5:
        status = CARBON_CEILING_TOO_SMALL_DEFAULT
        reason = f"Default Goeke80 carbon-cost ceiling is too small for a timing verdict: max cost_carbon/total_cost={ceiling:.3f}%."
    elif avg >= 2.0:
        status = CARBON_TIMING_LEVERAGE
        reason = f"Carbon-aware timing eats >=2% in a default scenario with enough carbon-cost ceiling: avg={avg:.3f}%, ceiling={ceiling:.3f}%."
    else:
        status = CARBON_MECHANISM_WEAK
        reason = f"Default carbon ceiling is not the hard stop, but timing did not eat >=2%: avg={avg:.3f}%, ceiling={ceiling:.3f}%."
    return {
        "status": status,
        "reason": reason,
        "avg_improvement_pct": avg,
        "default_carbon_ceiling_pct": ceiling,
        "row_count": len(rows),
        "gate_row_count": len(gate_rows),
        "zero_violations": zero_violations,
        "budget_summary": {
            "row_count": len(gate_rows),
            "min_candidate_evaluate_floor_ratio": min((_finite_or(row.get("candidate_evaluate_floor_ratio"), math.inf) for row in gate_rows), default=math.nan),
            "underpowered_count": sum(1 for row in gate_rows if str(row.get("budget_status", "")) == UNDERPOWERED),
        },
        "gate_rule": "Default rows first compute cost_carbon/total_cost ceiling. If all rows are <0.5%, verdict is CARBON_CEILING_TOO_SMALL_DEFAULT; otherwise >=2% timing improvement passes, and lower improvement is CARBON_MECHANISM_WEAK. EV-heavy rows are diagnostic only.",
    }


def write_stage2_report(path: Path, summary: dict[str, Any], manifest: dict[str, Any]) -> None:
    equal_eval = summary.get("equal_eval_reference") or {}
    anchor = summary.get("pilot21_anchor_reference") or {}
    budget = summary.get("budget_summary") or {}
    lines = [
        "# Track22-R Destroy Leverage Clean Probe",
        "",
        f"Verdict: `{summary['status']}`",
        f"Reason: {summary['reason']}",
        "",
        "## R0 Budget",
        "",
        f"- Verdict rows: {budget.get('row_count')}",
        f"- Min eval/lower-bound ratio: {_float(budget.get('min_eval_floor_ratio')):.3f}",
        f"- Min wall-clock/lower-bound ratio: {_float(budget.get('min_wall_floor_ratio')):.3f}",
        f"- UNDERPOWERED verdict rows: {budget.get('underpowered_count')}",
        "",
        "## Evidence",
        "",
        f"- Rows: {summary['row_count']}",
        f"- Worker integrity: {summary['worker_integrity_ok']}",
        f"- Zero violations: {summary['zero_violations']}",
        f"- Max scale best-of-k headroom: {summary['max_scale_best_of_k_headroom_pct']:.3f}%",
        f"- Fresh bundle non-overlap: {manifest['non_overlap_ok']}",
        "",
        "## Scale Rows",
        "",
    ]
    for row in summary["scale_rows"]:
        lines.append(
            f"- {row['label']}: operator={row['operator_select_mean']:.6f}, "
            f"best_of_k={row['best_of_k_mean']:.6f}, headroom={row['best_of_k_headroom_pct']:.3f}%, "
            f"worst_fixed={row['worst_removal_mean']:.6f}, worst_gain={row['worst_improvement_pct']:.3f}%"
        )
    lines.extend(
        [
            "",
            "## Equal-Eval Reference",
            "",
            f"- Rows: {equal_eval.get('row_count', 0)}",
            f"- Overall headroom: {_float((equal_eval.get('overall') or {}).get('best_of_k_headroom_pct')):.3f}%",
            f"- Max-scale headroom: {_float(equal_eval.get('max_scale_best_of_k_headroom_pct')):.3f}%",
            "- This table is deployment-cost reference only and is not used for the Track22-R verdict.",
            "",
            "## Pilot21 Anchor",
            "",
            f"- Rows: {anchor.get('row_count', 0)}",
            f"- Old Pilot21 reference: {_float(anchor.get('old_reference_pct')):.3f}%",
            f"- New max-scale headroom: {_float(anchor.get('max_scale_best_of_k_headroom_pct')):.3f}%",
            f"- Delta vs old reference: {_float(anchor.get('delta_vs_old_reference_pct')):.3f} pp",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_stage3_report(path: Path, summary: dict[str, Any]) -> None:
    test = summary.get("test_summary") or {}
    lines = [
        "# Track22 Learned-Destroy Clean Report",
        "",
        f"Verdict: `{summary['status']}`",
        f"Reason: {summary['reason']}",
        "",
        "## Evidence",
        "",
        f"- Trained: {summary.get('trained')}",
        f"- Train episodes: {summary.get('train_episode_count', 0)}",
        f"- Updates: {summary.get('update_count', 0)}",
        f"- Best validation gain vs operator-select: {summary.get('best_validation_gain_pct_vs_operator_select')}",
        f"- Test avg vs operator-select: {test.get('avg_vs_operator')}",
        f"- Test min-scale vs operator-select: {test.get('min_scale_vs_operator')}",
        f"- Test zero violations: {test.get('zero_violations')}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_stage4_report(path: Path, summary: dict[str, Any]) -> None:
    budget = summary.get("budget_summary") or {}
    lines = [
        "# Track22-R Carbon Timing Leverage Probe",
        "",
        f"Verdict: `{summary['status']}`",
        f"Reason: {summary['reason']}",
        "",
        "## Evidence",
        "",
        f"- Gate rows: {summary['gate_row_count']}",
        f"- Default carbon ceiling: {_float(summary.get('default_carbon_ceiling_pct')):.3f}%",
        f"- Average improvement: {summary['avg_improvement_pct']:.3f}%",
        f"- Zero violations: {summary['zero_violations']}",
        f"- Min candidate-evaluate/lower-bound ratio: {_float(budget.get('min_candidate_evaluate_floor_ratio')):.3f}",
        f"- UNDERPOWERED verdict rows: {budget.get('underpowered_count')}",
        f"- Rule: {summary['gate_rule']}",
    ]
    if summary.get("ev_heavy_diagnostic"):
        lines.extend(["", "## EV-heavy diagnostic", "", json.dumps(summary["ev_heavy_diagnostic"], ensure_ascii=False)])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_final_report(path: Path, state: dict[str, Any]) -> None:
    stage2 = state.get("stage2") or {}
    stage3 = state.get("stage3") or {}
    stage4 = state.get("stage4") or {}
    r1 = state.get("r1") or {}
    preflight = state.get("preflight") or {}
    stage2_budget = stage2.get("budget_summary") or {}
    stage2_equal_eval = stage2.get("equal_eval_reference") or {}
    stage2_anchor = stage2.get("pilot21_anchor_reference") or {}
    stage3_budget = (stage3.get("test_summary") or {}).get("budget_summary") or {}
    stage4_budget = stage4.get("budget_summary") or {}
    lines = [
        "# Track22-R Final Report",
        "",
        f"Final verdict: `{state.get('final_status', 'UNKNOWN')}`",
        f"Final reason: {state.get('final_reason', '')}",
        "",
        "## 人话结论",
        "",
        _plain_final_answer(state),
        "",
        "## R0 预算完整性",
        "",
        f"- R2/Stage2 equal-steps verdict rows: rows `{stage2_budget.get('row_count')}`; min eval ratio `{_float(stage2_budget.get('min_eval_floor_ratio')):.3f}`; min wall ratio `{_float(stage2_budget.get('min_wall_floor_ratio')):.3f}`; UNDERPOWERED `{stage2_budget.get('underpowered_count')}`.",
        f"- R3/Stage3 independent test rows: rows `{stage3_budget.get('row_count', 0)}`; min eval ratio `{_float(stage3_budget.get('min_eval_floor_ratio')):.3f}`; UNDERPOWERED `{stage3_budget.get('underpowered_count', 0)}`.",
        f"- R4/Stage4 carbon rows: rows `{stage4_budget.get('row_count')}`; min candidate-evaluate ratio `{_float(stage4_budget.get('min_candidate_evaluate_floor_ratio')):.3f}`; UNDERPOWERED `{stage4_budget.get('underpowered_count')}`.",
        "",
        "## R1 worker 崩溃修复",
        "",
        f"- Status: `{r1.get('status')}`.",
        f"- Root cause / evidence: {r1.get('root_cause')}",
        f"- Fix: {r1.get('fix')}",
        f"- Regression test: `{r1.get('regression_test')}`; recorded result `{(r1.get('test_result') or {}).get('summary', '')}`.",
        f"- Worker: `{(preflight.get('worker') or {}).get('exe')}`; NumPy `{(preflight.get('worker') or {}).get('numpy')}`.",
        "",
        "## R2 破坏杠杆",
        "",
        f"- Equal-steps oracle verdict: `{stage2.get('status', 'NOT_RUN')}`; max-scale headroom `{_float(stage2.get('max_scale_best_of_k_headroom_pct')):.3f}%`; overall headroom `{_float((stage2.get('overall') or {}).get('best_of_k_headroom_pct')):.3f}%`.",
        f"- Equal-eval reference only: rows `{stage2_equal_eval.get('row_count', 0)}`; max-scale headroom `{_float(stage2_equal_eval.get('max_scale_best_of_k_headroom_pct')):.3f}%`; overall `{_float((stage2_equal_eval.get('overall') or {}).get('best_of_k_headroom_pct')):.3f}%`.",
        f"- Pilot21 anchor: old `+{_float(stage2_anchor.get('old_reference_pct')):.3f}%`; new max-scale `{_float(stage2_anchor.get('max_scale_best_of_k_headroom_pct')):.3f}%`; delta `{_float(stage2_anchor.get('delta_vs_old_reference_pct')):.3f}` pp.",
        "",
        "## R3 learned-destroy",
        "",
        f"- Verdict: `{stage3.get('status', 'NOT_RUN')}`.",
        f"- Reason: {stage3.get('reason', '')}",
        f"- Test avg vs operator-select: {_float((stage3.get('test_summary') or {}).get('avg_vs_operator')):.3f}%; min-scale {_float((stage3.get('test_summary') or {}).get('min_scale_vs_operator')):.3f}%; avg vs random {_float((stage3.get('test_summary') or {}).get('avg_vs_random')):.3f}%; avg vs worst {_float((stage3.get('test_summary') or {}).get('avg_vs_worst')):.3f}%.",
        "",
        "## R4 碳时刻",
        "",
        f"- Verdict: `{stage4.get('status', 'NOT_RUN')}`.",
        f"- Default carbon ceiling: {_float(stage4.get('default_carbon_ceiling_pct')):.3f}% of total cost.",
        f"- Probe improvement actually eaten: {_float(stage4.get('avg_improvement_pct')):.3f}%.",
        f"- EV-heavy diagnostic: `{(stage4.get('ev_heavy_diagnostic') or {}).get('source', 'NOT_RUN')}`; improvement `{_float((stage4.get('ev_heavy_diagnostic') or {}).get('improvement_pct')):.3f}%`; diagnostic only.",
        "",
        "## 与首跑被驳回版的差异",
        "",
        "- 首跑 Stage2 的 `-1.405%` 来自 80 eval / 2-5 秒 / 等 eval 记账，best_of_k 实际只走约 10 步而 operator_select 走 80 步；Track22-R 主判据改为等步数 oracle，且判级行必须过 eval 与墙钟下限。",
        "- 首跑 Stage3 不是正常跳过，而是 worker 在 learned-destroy 首次真跑时静默崩溃；Track22-R 先给 worker 加 faulthandler、crash log、stderr tail，并新增 50c/q=0.4/20-customer 回归测试。",
        "- 首跑 Stage4 只测 3 个 25c 解，候选集没包含 naive，且 EV-heavy 把 CV 上限设为 0；Track22-R 默认场景先报碳份额天花板，候选集强制含 naive，并用合规 EV-heavy 诊断。",
        "",
        "## 总判级",
        "",
        f"- Overall: `{state.get('final_status', 'UNKNOWN')}`.",
        f"- 一句话：{_dr_main_algorithm_sentence(state)}",
        "",
        "## 主要证据文件",
        "",
        "- `track22_preflight.json`",
        "- `track22_bundle_manifest.json`",
        "- `track22r_destroy_leverage_equal_steps_rows.csv`",
        "- `track22r_destroy_leverage_equal_eval_rows.csv`",
        "- `track22r_pilot21_anchor_rows.csv`",
        "- `stage2_destroy_leverage_summary.json`",
        "- `track22_learned_destroy_test_rows.csv`",
        "- `track22_carbon_timing_rows.csv`",
        "- `track22_final_report.json`",
    ]
    if state.get("final_status") in {"DR_COMPETITIVE_CANDIDATE", "DR_PARTIAL"}:
        lines.extend(
            [
                "",
                "## M1 最小移植清单",
                "",
                "- `solver/rl/dr_alns_ppo/worker.py` learned-destroy/crash logging changes.",
                "- `solver/rl/dr_alns_ppo/worker_client.py` worker stderr/crash-log propagation.",
                "- `solver/rl/dr_alns_ppo/track22_endgame.py` Track22-R runner and budget gates.",
                "- `solver/rl/tests/test_track22r_worker_crash.py` and `solver/rl/tests/test_final_track22r.py`.",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def final_status_from_state(state: dict[str, Any]) -> str:
    stage3 = str((state.get("stage3") or {}).get("status", ""))
    stage4 = str((state.get("stage4") or {}).get("status", ""))
    if stage3 == PASS_LEARNED_DESTROY_CLEAN and stage4 == CARBON_TIMING_LEVERAGE:
        return "DR_COMPETITIVE_CANDIDATE"
    if stage3 == PASS_LEARNED_DESTROY_CLEAN:
        return "DR_PARTIAL"
    if stage4 == CARBON_TIMING_LEVERAGE:
        return "DR_PARTIAL"
    if stage3 == WEAK_LEARNED_DESTROY_CLEAN:
        return "DR_PARTIAL"
    if stage3 == SKIP_LEARNED_DESTROY_NO_LEVERAGE and stage4 in {CARBON_CEILING_TOO_SMALL_DEFAULT, CARBON_MECHANISM_WEAK}:
        return "DR_CLEAN_NEGATIVE"
    return "TRACK22_COMPLETED_WITH_HALTS"


def _plain_final_answer(state: dict[str, Any]) -> str:
    status = str(state.get("final_status", "UNKNOWN"))
    if status == "DR_COMPETITIVE_CANDIDATE":
        return "这次 Track22-R 给出了干净正结果：learned-destroy 和碳时刻两个杠杆都过闸，DR-ALNS 可以作为未来主算法候选继续推进。"
    if status == "DR_PARTIAL":
        return "这次 Track22-R 只给出部分正结果：至少一个杠杆有可用信号，但还不足以把 DR-ALNS 直接定为主算法。"
    if status == "DR_CLEAN_NEGATIVE":
        return "这次 Track22-R 给出干净负/场景受限结果：判级行先过预算闸，再看杠杆；如果 learned-destroy 没有过 R2/R3，默认碳场景又只有场景天花板结论，就不应把这条 DR-ALNS 推成主算法。"
    return "这次 Track22-R 没有形成完整可判级结论，原因见各 Stage halt；不能据此给 DR-ALNS 下正负总判。"


def _dr_main_algorithm_sentence(state: dict[str, Any]) -> str:
    status = str(state.get("final_status", "UNKNOWN"))
    if status == "DR_COMPETITIVE_CANDIDATE":
        return "配继续当未来主算法候选，但仍需跨机/M1 正式复验。"
    if status == "DR_PARTIAL":
        return "只能当部分候选或 future-work，不配现在独立扛主算法结论。"
    if status == "DR_CLEAN_NEGATIVE":
        return "不配；当前干净证据不足以支持把 DR-ALNS 作为未来主算法。"
    return "暂不能判；先修完 halt 指向的仪器或预算问题。"


def final_reason_from_state(state: dict[str, Any]) -> str:
    return (
        f"stage2={((state.get('stage2') or {}).get('status'))}; "
        f"stage3={((state.get('stage3') or {}).get('status'))}; "
        f"stage4={((state.get('stage4') or {}).get('status'))}"
    )


def _headroom_row(label: str, algos: dict[str, list[float]]) -> dict[str, Any]:
    op = _mean(algos.get("operator_select", []))
    worst = _mean(algos.get("worst_removal_fixed", []))
    best = _mean(algos.get("best_of_k_destroy", []))
    return {
        "label": label,
        "operator_select_mean": op,
        "worst_removal_mean": worst,
        "best_of_k_mean": best,
        "best_of_k_headroom_pct": _improvement_pct(op, best) if math.isfinite(op) and math.isfinite(best) else math.nan,
        "worst_improvement_pct": _improvement_pct(op, worst) if math.isfinite(op) and math.isfinite(worst) else math.nan,
    }


def _merge_algo_values(items: Iterable[dict[str, list[float]]]) -> dict[str, list[float]]:
    merged: dict[str, list[float]] = {}
    for item in items:
        for key, values in item.items():
            merged.setdefault(key, []).extend(values)
    return merged


def _stage_done(state: dict[str, Any], stage: str) -> bool:
    order = {"stage2": 2, "stage3": 3, "stage4": 4}
    completed = str(state.get("completed_stage", "") or "")
    return completed in order and order[completed] >= order[stage]


def _git_snapshot() -> dict[str, Any]:
    def git(*parts: str) -> str:
        proc = subprocess.run(["git", *parts], text=True, capture_output=True, check=False, timeout=30)
        return (proc.stdout or proc.stderr).strip()

    return {
        "status_short_branch": git("status", "--short", "--branch"),
        "head": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
    }


def _run_python_json(python: Path, code: str) -> dict[str, Any]:
    env = os.environ.copy()
    root = Path.cwd()
    env["PYTHONPATH"] = os.pathsep.join([str(root / "solver" / "rl"), str(root / "solver" / "src"), str(root / "models" / "src")])
    proc = subprocess.run([str(python), "-c", code], cwd=root, env=env, text=True, capture_output=True, check=False, timeout=30)
    if proc.returncode != 0:
        raise Track22Halt("HALT_PREFLIGHT", proc.stderr.strip() or proc.stdout.strip())
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _manifest_bundle_path(root: Path, output_dir: Path) -> str:
    try:
        return output_dir.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(output_dir.resolve())


def _remove_existing_output(output_dir: Path, output_root: Path) -> None:
    resolved_output = output_dir.resolve()
    resolved_root = output_root.resolve()
    if resolved_output == resolved_root or resolved_root not in resolved_output.parents:
        raise ValueError(f"Refusing to remove output outside generated root: {resolved_output}")
    shutil.rmtree(resolved_output)


def _scale_label(bundle: str) -> str:
    text = str(bundle)
    for marker in ("E-UK25", "E-UK50", "E-UK100", "E-UK150", "E-UK200"):
        if marker in text:
            return marker.replace("E-UK", "") + "c"
    return "unknown"


def _improvement_pct(base: float, candidate: float) -> float:
    return (float(base) - float(candidate)) / max(abs(float(base)), 1.0) * 100.0


def _mean(values: Iterable[float]) -> float:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    return float(sum(finite) / len(finite)) if finite else math.nan


def _finite_or(value: Any, default: float) -> float:
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return default
    return value_f if math.isfinite(value_f) else default


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _is_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _int_or(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, str) and value.strip() == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _all_zero(rows: Iterable[dict[str, Any]], key: str) -> bool:
    return all(_int_or(row.get(key), 1) == 0 for row in rows)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8", newline="\n")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{stamp}\t{message}\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track22 clean DR-ALNS endgame runner")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    run_parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    run_parser.add_argument("--resume", action="store_true", default=True)
    run_parser.add_argument("--no-resume", dest="resume", action="store_false")
    run_parser.add_argument("--regenerate-bundles", action="store_true")
    run_parser.add_argument("--stage2-seeds", default="1201,1202,1203")
    run_parser.add_argument("--stage2-25c-steps", type=int, default=2000)
    run_parser.add_argument("--stage2-50c-steps", type=int, default=3000)
    run_parser.add_argument("--stage2-anchor-seeds", default="11,12")
    run_parser.add_argument("--stage2-anchor-eval-budget", type=int, default=80)
    run_parser.add_argument("--stage2-best-of-k", type=int, default=4)
    run_parser.add_argument("--stage3-seed", type=int, default=2601)
    run_parser.add_argument("--stage3-train-episodes", type=int, default=1000)
    run_parser.add_argument("--stage3-train-eval-budget", type=int, default=120)
    run_parser.add_argument("--stage3-validation-eval-budget", type=int, default=120)
    run_parser.add_argument("--stage3-test-eval-budget", type=int, default=180)
    run_parser.add_argument("--stage3-validation-seeds", default="2701")
    run_parser.add_argument("--stage3-test-seeds", default="2801,2802,2803,2804,2805")
    run_parser.add_argument("--stage3-pomo-rollouts", type=int, default=4)
    run_parser.add_argument("--stage3-rollout-min-groups", type=int, default=1)
    run_parser.add_argument("--stage3-validation-every-updates", type=int, default=10)
    run_parser.add_argument("--stage3-max-train-seconds", type=float, default=28800.0)
    run_parser.add_argument("--stage3-max-customers", type=int, default=128)
    run_parser.add_argument("--stage3-hidden-size", type=int, default=128)
    run_parser.add_argument("--stage3-learning-rate", type=float, default=1e-4)
    run_parser.add_argument("--stage3-final-learning-rate", type=float, default=1e-5)
    run_parser.add_argument("--stage3-ppo-epochs", type=int, default=1)
    run_parser.add_argument("--stage3-minibatch-size", type=int, default=64)
    run_parser.add_argument("--stage3-clip-range", type=float, default=0.1)
    run_parser.add_argument("--stage3-target-kl", type=float, default=0.08)
    run_parser.add_argument("--stage3-value-coef", type=float, default=0.5)
    run_parser.add_argument("--stage3-entropy-coef", type=float, default=0.01)
    run_parser.add_argument("--stage3-max-grad-norm", type=float, default=0.5)
    run_parser.add_argument("--stage4-bundle-count", type=int, default=5)
    run_parser.add_argument("--stage4-seeds", default="2901,2902,2903")
    run_parser.add_argument("--stage4-eval-budget", type=int, default=300)
    run_parser.add_argument("--stage4-candidate-evals", type=int, default=200)
    run_parser.add_argument("--stage4-max-runtime-seconds", type=float, default=120.0)
    run_parser.add_argument("--stage4-ev-heavy-seed", type=int, default=2999)
    run_parser.add_argument("--stage4-ev-heavy-carbon-price-factor", type=float, default=10.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "run":
        return run(args)
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
