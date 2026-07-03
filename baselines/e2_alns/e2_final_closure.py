#!/usr/bin/env python3
"""E2 final-closure runner.

This script is evidence plumbing for the E2 submission closeout. It does not
change model semantics, ALNS operators, or paper text. Formal phases use
DEFAULT_PRICES; the 280 kWh arm is restricted to the Phase-A diagnostic gate.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "solver/src", REPO_ROOT / "models/src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.carbon_operators import low_carbon_charging_share
from setp_solver.search.candidates import make_shared_initial_solution, solution_signature_hash
from setp_solver.search.metaheuristic_baselines import (
    BASELINE_ALGORITHMS,
    baseline_result_to_dict,
    run_metaheuristic_baseline,
    solution_to_dict,
)
from setp_solver.search import winner_operators as wo
from setp_solver.search.winner_operators import WinnerKernelConfig


GOLD_PYTHON = "/opt/anaconda3/bin/python3.13"
GOLD_NUMPY = "2.3.5"
CARBON_PRICE = 0.05034
DIAGNOSTIC_BATTERY_KWH = 280.0
INSTANCE_ROOT = REPO_ROOT / "models/data_bundle/generated_instances/e2_benchmark"
OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/e2_final_closure_20260703"

BASE_T3_BASELINES = ("GA", "LNS", "PSO", "VNS")
G3_CANDIDATE_BASELINES = ("ACO", "GA-VNS", "GWO", "IWD")
ALNS_GATE_ALGORITHMS = ("alns_e2_carbon", "alns_e2_carbon_ablation", "alns_e2_throughput")
ALNS_GATE_INSTANCES = (("threeshift", "e2-threeshift-150c-01"), ("vanilla", "e2-vanilla-100c-01"))
G4_INSTANCES = tuple(
    ("threeshift", f"e2-threeshift-{size}c-{idx:02d}")
    for size in (100, 150, 200)
    for idx in (1, 2, 3)
)
COMPONENT_ORDER = ("LOCAL_SEARCH", "ROUTE_ELIMINATION", "RRT_TRUE_ACCEPTANCE")
HASH_EXCLUDE_NAMES = {".DS_Store", "artifact_hashes.json"}
HASH_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".tasks"}
PROTECTED_PATHS = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/prices.py",
    "solver/src/setp_solver/search/feasible_repair.py",
    "solver/src/setp_solver/search/resetp_alns",
    "solver/src/setp_solver/search/alns_wouda.py",
    "solver/src/setp_solver/search/winner_operators.py",
    "docs/paper_submission_final/paper_main.tex",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument(
        "--phase",
        choices=["preflight", "phase-a", "phase-b", "phase-c", "phase-d", "decide", "all"],
        default="all",
    )
    parser.add_argument("--eval-budget", type=int, default=16000)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--task-json", default="")
    parser.add_argument("--task-output-json", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.task_json:
        row = run_task(read_json(Path(args.task_json)))
        write_json(Path(args.task_output_json), row)
        return 0

    output_dir = repo_path(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    clean_artifact_dir(output_dir)
    metadata = metadata_payload(args, output_dir)
    write_json(output_dir / "metadata.json", metadata)
    preflight_payload = preflight()
    write_json(output_dir / "preflight.json", preflight_payload)
    if not preflight_payload["env_ok"] or preflight_payload["protected_diff"]:
        write_json(output_dir / "decision.json", halt_decision("HALT_COLLECTION_COST", preflight_payload))
        write_report(output_dir)
        write_hashes(output_dir)
        return 2

    seeds = parse_seeds(args.seeds)
    if args.phase in {"preflight"}:
        write_hashes(output_dir)
        print(json.dumps(preflight_payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.phase in {"phase-a", "all"}:
        run_phase_a(output_dir / "phase_a_alns_gate", seeds=seeds, eval_budget=args.eval_budget, workers=args.workers, force=args.force)
    if args.phase in {"phase-b", "all"}:
        run_phase_b(output_dir / "phase_b_g3_baseline_health", seeds=seeds, eval_budget=args.eval_budget, workers=args.workers, force=args.force)
    if args.phase in {"phase-c", "all"}:
        run_phase_c(output_dir / "phase_c_g4_stability", output_dir / "phase_a_alns_gate", seeds=seeds, eval_budget=args.eval_budget, workers=args.workers, force=args.force)
    if args.phase in {"phase-d", "all"}:
        run_phase_d(
            output_dir / "phase_d_g5_t3_material",
            output_dir / "phase_a_alns_gate",
            output_dir / "phase_b_g3_baseline_health",
            output_dir / "phase_c_g4_stability",
            seeds=seeds,
            eval_budget=args.eval_budget,
            workers=args.workers,
            force=args.force,
        )
    if args.phase in {"decide", "all"}:
        write_json(output_dir / "decision.json", final_decision(output_dir))
        write_report(output_dir)
    write_hashes(output_dir)
    print(json.dumps(read_json(output_dir / "decision.json") if (output_dir / "decision.json").exists() else {"phase": args.phase, "status": "DONE"}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def metadata_payload(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    return {
        "schema": "setp-e2-final-closure-metadata.v1",
        "task": "E2 final closure: ALNS gate, G3 baseline health, G4 stability, G5 T3/F2 material",
        "head": git_head(),
        "python": sys.executable,
        "numpy": numpy_version(),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "phase": args.phase,
        "output_dir": rel(output_dir),
        "eval_budget": int(args.eval_budget),
        "seeds": parse_seeds(args.seeds),
        "workers": int(args.workers),
        "formal_price_policy": "DEFAULT_PRICES / Goeke80 / zero override",
        "diagnostic_price_policy": "Phase A only: replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034)",
        "not_paper_text": True,
        "not_formal_algorithm_claim": True,
        "protected_paths": list(PROTECTED_PATHS),
        "created_at_epoch": time.time(),
    }


def preflight() -> dict[str, Any]:
    g0_decision_path = REPO_ROOT / "baselines/e2_alns/e2_g0_reaudit_v2_20260703/decision.json"
    g0_decision = read_json(g0_decision_path) if g0_decision_path.exists() else {}
    manifest = tier1_instance_manifest()
    return {
        "schema": "setp-e2-final-closure-preflight.v1",
        "env_ok": sys.executable == GOLD_PYTHON and numpy_version() == GOLD_NUMPY and os.environ.get("PYTHONHASHSEED") == "0",
        "python": sys.executable,
        "numpy": numpy_version(),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "head": git_head(),
        "g0_v2_decision_path": rel(g0_decision_path) if g0_decision_path.exists() else "",
        "g0_v2_verdict": g0_decision.get("verdict"),
        "g0_v2_ok": g0_decision.get("verdict") == "G0_PASS_BASELINES_HEALTHY",
        "tier1_instance_count": len(manifest),
        "tier1_manifest_ok": len(manifest) == 23,
        "protected_diff": protected_diff(),
        "scenario_contract": {
            "phase_a_formal": "DEFAULT_PRICES",
            "phase_a_diagnostic": "B=280/carbon=0.05034 in-memory override",
            "phase_b_c_d": "DEFAULT_PRICES only",
        },
    }


def run_phase_a(phase_dir: Path, *, seeds: list[int], eval_budget: int, workers: int, force: bool) -> None:
    phase_dir.mkdir(parents=True, exist_ok=True)
    tasks: list[dict[str, Any]] = []
    for scenario_type in ("formal_goeke80", "diagnostic_280_override"):
        for category, instance in ALNS_GATE_INSTANCES:
            for algorithm in ALNS_GATE_ALGORITHMS:
                for seed in seeds:
                    tasks.append(
                        make_task(
                            phase="A1_CARBON_GATE",
                            phase_dir=phase_dir,
                            category=category,
                            instance=instance,
                            algorithm=algorithm,
                            seed=seed,
                            eval_budget=eval_budget,
                            runtime_cap_seconds=runtime_cap_for_instance(instance),
                            scenario_type=scenario_type,
                        )
                    )
    for component in ("BASE", *COMPONENT_ORDER):
        algorithm = "alns_e2_throughput" if component == "BASE" else f"alns_component_{component}"
        for seed in seeds:
            tasks.append(
                make_task(
                    phase="A2_COMPONENT_ABLATION",
                    phase_dir=phase_dir,
                    category="threeshift",
                    instance="e2-threeshift-150c-01",
                    algorithm=algorithm,
                    seed=seed,
                    eval_budget=eval_budget,
                    runtime_cap_seconds=runtime_cap_for_instance("e2-threeshift-150c-01"),
                    scenario_type="formal_goeke80",
                    components=[] if component == "BASE" else [component],
                )
            )
    rows = run_tasks(phase_dir, tasks, workers=workers, force=force)
    write_csv(phase_dir / "raw_runs.csv", rows)
    write_csv(phase_dir / "best_trajectory.csv", all_history_rows(rows))
    write_csv(phase_dir / "channel_lift.csv", [channel_lift_row(row) for row in rows])
    decision = decide_phase_a(rows)
    if decision.get("stack_retest_tasks"):
        stack_tasks = [
            make_task(
                phase="A3_COMPONENT_STACK_RETEST",
                phase_dir=phase_dir,
                category="threeshift",
                instance="e2-threeshift-150c-01",
                algorithm="alns_component_stack",
                seed=seed,
                eval_budget=eval_budget,
                runtime_cap_seconds=runtime_cap_for_instance("e2-threeshift-150c-01"),
                scenario_type="formal_goeke80",
                components=list(decision["stack_retest_tasks"]),
            )
            for seed in seeds
        ]
        rows = run_tasks(phase_dir, stack_tasks, workers=workers, force=force)
        write_csv(phase_dir / "raw_runs.csv", rows)
        write_csv(phase_dir / "best_trajectory.csv", all_history_rows(rows))
        write_csv(phase_dir / "channel_lift.csv", [channel_lift_row(row) for row in rows])
        decision = decide_phase_a(rows)
    write_json(phase_dir / "phase_a_decision.json", decision)
    write_json(phase_dir / "decision.json", decision)
    write_csv(phase_dir / "carbon_gate_summary.csv", summarize_rows(rows, keys=("scenario_type", "category", "instance", "algorithm")))
    write_csv(phase_dir / "component_ablation_summary.csv", summarize_rows([row for row in rows if str(row.get("phase")).startswith("A2") or str(row.get("phase")).startswith("A3")], keys=("algorithm", "components")))
    write_phase_report(phase_dir, "Phase A ALNS Gate", decision)
    write_hashes(phase_dir)


def run_phase_b(phase_dir: Path, *, seeds: list[int], eval_budget: int, workers: int, force: bool) -> None:
    phase_dir.mkdir(parents=True, exist_ok=True)
    tasks = [
        make_task(
            phase="B_G3_BASELINE_HEALTH",
            phase_dir=phase_dir,
            category="threeshift",
            instance="e2-threeshift-150c-01",
            algorithm=algorithm,
            seed=seed,
            eval_budget=eval_budget,
            runtime_cap_seconds=runtime_cap_for_instance("e2-threeshift-150c-01"),
            scenario_type="formal_goeke80",
        )
        for algorithm in G3_CANDIDATE_BASELINES
        for seed in seeds
    ]
    rows = run_tasks(phase_dir, tasks, workers=workers, force=force)
    liveness_rows = liveness_verdicts(rows, G3_CANDIDATE_BASELINES)
    decision = decide_phase_b(rows, liveness_rows)
    write_csv(phase_dir / "raw_runs.csv", rows)
    write_csv(phase_dir / "best_trajectory.csv", all_history_rows(rows))
    write_csv(phase_dir / "channel_lift.csv", [channel_lift_row(row) for row in rows])
    write_csv(phase_dir / "liveness_verdicts.csv", liveness_rows)
    write_json(phase_dir / "baseline_set_boundary.json", decision.get("baseline_set_boundary", {}))
    write_json(phase_dir / "decision.json", decision)
    write_phase_report(phase_dir, "Phase B G3 Baseline Health", decision)
    write_hashes(phase_dir)


def run_phase_c(phase_dir: Path, phase_a_dir: Path, *, seeds: list[int], eval_budget: int, workers: int, force: bool) -> None:
    phase_dir.mkdir(parents=True, exist_ok=True)
    phase_a_decision = read_json(phase_a_dir / "phase_a_decision.json")
    if phase_a_decision.get("verdict") != "ALNS_GATE_READY":
        decision = {"schema": "setp-e2-final-phase-c-decision.v1", "verdict": "HALT_G4_SUSPECT", "reason": "Phase A did not produce ALNS_GATE_READY.", "phase_a_verdict": phase_a_decision.get("verdict")}
        write_json(phase_dir / "decision.json", decision)
        write_phase_report(phase_dir, "Phase C G4 Stability", decision)
        write_hashes(phase_dir)
        return
    t3_profile = phase_a_decision["t3_main_profile"]
    tasks: list[dict[str, Any]] = []
    for category, instance in G4_INSTANCES:
        for seed in seeds:
            tasks.append(
                make_task(
                    phase="C_G4_STABILITY",
                    phase_dir=phase_dir,
                    category=category,
                    instance=instance,
                    algorithm="t3_main_alns",
                    seed=seed,
                    eval_budget=eval_budget,
                    runtime_cap_seconds=runtime_cap_for_instance(instance),
                    scenario_type="formal_goeke80",
                    t3_profile=t3_profile,
                )
            )
            tasks.append(
                make_task(
                    phase="C_G4_STABILITY",
                    phase_dir=phase_dir,
                    category=category,
                    instance=instance,
                    algorithm="LNS",
                    seed=seed,
                    eval_budget=eval_budget,
                    runtime_cap_seconds=runtime_cap_for_instance(instance),
                    scenario_type="formal_goeke80",
                )
            )
    rows = run_tasks(phase_dir, tasks, workers=workers, force=force)
    decision = decide_phase_c(rows)
    write_csv(phase_dir / "raw_runs.csv", rows)
    write_csv(phase_dir / "best_trajectory.csv", all_history_rows(rows))
    write_csv(phase_dir / "channel_lift.csv", [channel_lift_row(row) for row in rows])
    write_csv(phase_dir / "g4_gap_by_instance.csv", g4_gap_rows(rows))
    write_json(phase_dir / "decision.json", decision)
    write_phase_report(phase_dir, "Phase C G4 Stability", decision)
    write_hashes(phase_dir)


def run_phase_d(
    phase_dir: Path,
    phase_a_dir: Path,
    phase_b_dir: Path,
    phase_c_dir: Path,
    *,
    seeds: list[int],
    eval_budget: int,
    workers: int,
    force: bool,
) -> None:
    phase_dir.mkdir(parents=True, exist_ok=True)
    phase_a = read_json(phase_a_dir / "phase_a_decision.json")
    phase_b = read_json(phase_b_dir / "decision.json")
    phase_c = read_json(phase_c_dir / "decision.json")
    if phase_c.get("verdict") != "G4_STABILITY_PASS":
        decision = {"schema": "setp-e2-final-phase-d-decision.v1", "verdict": "HALT_T3_SUSPECT", "reason": "Phase C did not pass.", "phase_c_verdict": phase_c.get("verdict")}
        write_json(phase_dir / "decision.json", decision)
        write_phase_report(phase_dir, "Phase D G5 T3 Material", decision)
        write_hashes(phase_dir)
        return
    baseline_set = list(phase_b.get("t3_baseline_set", BASE_T3_BASELINES))
    t3_profile = phase_a["t3_main_profile"]
    manifest = tier1_instance_manifest()
    if len(manifest) != 23:
        decision = {"schema": "setp-e2-final-phase-d-decision.v1", "verdict": "HALT_INSTANCE_MANIFEST_UNRESOLVED", "tier1_count": len(manifest)}
        write_json(phase_dir / "decision.json", decision)
        write_phase_report(phase_dir, "Phase D G5 T3 Material", decision)
        write_hashes(phase_dir)
        return
    write_csv(phase_dir / "instance_manifest.csv", manifest)
    tasks: list[dict[str, Any]] = []
    for item in manifest:
        for seed in seeds:
            tasks.append(
                make_task(
                    phase="D_G5_TIER1",
                    phase_dir=phase_dir,
                    category=str(item["category"]),
                    instance=str(item["instance"]),
                    algorithm="t3_main_alns",
                    seed=seed,
                    eval_budget=eval_budget,
                    runtime_cap_seconds=runtime_cap_for_instance(str(item["instance"])),
                    scenario_type="formal_goeke80",
                    t3_profile=t3_profile,
                )
            )
            for algorithm in baseline_set:
                tasks.append(
                    make_task(
                        phase="D_G5_TIER1",
                        phase_dir=phase_dir,
                        category=str(item["category"]),
                        instance=str(item["instance"]),
                        algorithm=algorithm,
                        seed=seed,
                        eval_budget=eval_budget,
                        runtime_cap_seconds=runtime_cap_for_instance(str(item["instance"])),
                        scenario_type="formal_goeke80",
                    )
                )
    rows = run_tasks(phase_dir, tasks, workers=workers, force=force)
    liveness_rows = liveness_verdicts(rows, tuple(baseline_set))
    decision = decide_phase_d(rows, liveness_rows, baseline_set)
    write_csv(phase_dir / "raw_runs.csv", rows)
    write_csv(phase_dir / "best_trajectory.csv", all_history_rows(rows))
    write_csv(phase_dir / "channel_lift.csv", [channel_lift_row(row) for row in rows])
    write_csv(phase_dir / "liveness_verdicts.csv", liveness_rows)
    write_csv(phase_dir / "t3_table_material.csv", t3_table_material(rows))
    write_csv(phase_dir / "wilcoxon_pairwise.csv", wilcoxon_rows(rows, baseline_set))
    write_csv(phase_dir / "win_tie_loss.csv", win_tie_loss_rows(rows, baseline_set))
    write_csv(phase_dir / "f2_convergence_data.csv", all_history_rows(rows))
    write_json(phase_dir / "baseline_set_boundary.json", {"t3_baseline_set": baseline_set, "phase_b_decision": phase_b})
    write_json(phase_dir / "decision.json", decision)
    write_phase_report(phase_dir, "Phase D G5 T3/F2 Material", decision)
    write_hashes(phase_dir)


def make_task(
    *,
    phase: str,
    phase_dir: Path,
    category: str,
    instance: str,
    algorithm: str,
    seed: int,
    eval_budget: int,
    runtime_cap_seconds: float,
    scenario_type: str,
    components: list[str] | None = None,
    t3_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = run_id_for(phase, scenario_type, category, instance, algorithm, seed, components or [])
    checkpoint = phase_dir / "checkpoints" / f"{run_id}.json"
    return {
        "schema": "setp-e2-final-task.v1",
        "repo_root": str(REPO_ROOT),
        "phase": phase,
        "run_id": run_id,
        "category": category,
        "instance": instance,
        "bundle_dir": str(Path("models/data_bundle/generated_instances/e2_benchmark") / category / instance),
        "algorithm": algorithm,
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "runtime_cap_seconds": float(runtime_cap_seconds),
        "scenario_type": scenario_type,
        "price_override": price_override_payload(scenario_type),
        "components": list(components or []),
        "t3_profile": t3_profile or {},
        "checkpoint_path": str(checkpoint),
        "head": git_head(),
    }


def run_tasks(phase_dir: Path, tasks: list[dict[str, Any]], *, workers: int, force: bool) -> list[dict[str, Any]]:
    rows = read_csv(phase_dir / "raw_runs.csv")
    existing = {row.get("run_id"): row for row in rows}
    todo = [task for task in tasks if force or task["run_id"] not in existing]
    if not todo:
        return sorted_rows(list(existing.values()))
    task_root = phase_dir / ".tasks"
    task_root.mkdir(parents=True, exist_ok=True)
    if workers <= 1:
        for idx, task in enumerate(todo):
            row = execute_task_subprocess(task_root, task, idx)
            existing[str(row.get("run_id", task["run_id"]))] = row
            write_csv(phase_dir / "raw_runs.csv", sorted_rows(list(existing.values())))
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        with ProcessPoolExecutor(max_workers=int(workers)) as pool:
            futures = {pool.submit(execute_task_subprocess, task_root, task, idx): task for idx, task in enumerate(todo)}
            for future in as_completed(futures):
                task = futures[future]
                row = future.result()
                existing[str(row.get("run_id", task["run_id"]))] = row
                write_csv(phase_dir / "raw_runs.csv", sorted_rows(list(existing.values())))
    return sorted_rows(list(existing.values()))


def execute_task_subprocess(task_root: Path, task: dict[str, Any], idx: int) -> dict[str, Any]:
    task_path = task_root / f"{task['run_id']}__{idx}.json"
    row_path = task_root / f"{task['run_id']}__{idx}_row.json"
    write_json(task_path, task)
    command = [GOLD_PYTHON, str(Path(__file__).resolve()), "--task-json", str(task_path), "--task-output-json", str(row_path)]
    env = os.environ.copy()
    env["PYTHONPATH"] = "solver/src:models/src:."
    env["PYTHONHASHSEED"] = "0"
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=float(task["runtime_cap_seconds"]) + 30.0,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return timeout_row(task, time.perf_counter() - started, exc.stdout, exc.stderr)
    if completed.returncode != 0:
        return worker_error_row(task, "HALT_WORKER_ERROR", completed.stdout, completed.stderr, time.perf_counter() - started)
    if not row_path.exists():
        return worker_error_row(task, "HALT_WORKER_ERROR", completed.stdout, "Worker produced no row JSON.", time.perf_counter() - started)
    return read_json(row_path)


def run_task(task: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    root = Path(task["repo_root"])
    bundle_dir = root / str(task["bundle_dir"])
    prices = prices_for_scenario(str(task["scenario_type"]))
    bundle = load_search_bundle(bundle_dir)
    try:
        warm = make_shared_initial_solution(bundle, prices=prices)
    except Exception as exc:
        return failure_row(task, "HALT_WARM_START", repr(exc), started)
    checkpoint_path = Path(str(task["checkpoint_path"]))
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    old_checkpoint = os.environ.get("SETP_E2_ALNS_CHECKPOINT_PATH")
    os.environ["SETP_E2_ALNS_CHECKPOINT_PATH"] = str(checkpoint_path)
    algorithm = str(task["algorithm"])
    history: list[dict[str, Any]] = []
    operator_counts: dict[str, Any] = {}
    flags: dict[str, str] = {}
    try:
        if algorithm in {"alns_e2_throughput", "alns_e2_carbon", "alns_e2_carbon_ablation"}:
            result = run_alns_variant(algorithm, bundle_dir, warm, prices, task)
            solution = result["best_solution"]
            best_cost = float(result["best_cost"])
            actual_evals = int(result["evaluations"])
            violation_count = int(result["violation_count"])
            history = normalize_alns_history(list(result.get("history", [])))
            operator_counts = dict(result.get("operator_counts", {}))
            flags = dict(result.get("flags", {}))
            status = "OK"
            failure_reason = ""
        elif algorithm.startswith("alns_component_") or algorithm == "alns_component_stack" or algorithm == "t3_main_alns":
            result = run_custom_alns_variant(bundle_dir, warm, prices, task)
            solution = result["best_solution"]
            best_cost = float(result["best_cost"])
            actual_evals = int(result["evaluations"])
            violation_count = int(result["violation_count"])
            history = normalize_alns_history(list(result.get("history", [])))
            operator_counts = dict(result.get("operator_counts", {}))
            flags = dict(result.get("flags", {}))
            status = "OK"
            failure_reason = ""
        elif algorithm in BASELINE_ALGORITHMS:
            result = run_metaheuristic_baseline(
                algorithm,
                bundle_dir,
                seed=int(task["seed"]),
                eval_budget=int(task["eval_budget"]),
                max_runtime_seconds=float(task["runtime_cap_seconds"]),
                initial_solution=warm,
                prices=prices,
                common_flip_preprocess=True,
            )
            solution = result.best_solution
            best_cost = float(result.best_cost) if result.best_cost is not None else math.inf
            actual_evals = int(result.evals)
            violation_count = int(result.violation_count)
            history = list(result.history)
            operator_counts = dict(result.operator_counts)
            flags = {"baseline": algorithm}
            status = result.status
            failure_reason = result.failure_reason
        else:
            return failure_row(task, "HALT_UNKNOWN_ALGORITHM", f"Unknown algorithm: {algorithm}", started)
    except Exception as exc:
        return failure_row(task, "HALT_WORKER_EXCEPTION", repr(exc), started)
    finally:
        if old_checkpoint is None:
            os.environ.pop("SETP_E2_ALNS_CHECKPOINT_PATH", None)
        else:
            os.environ["SETP_E2_ALNS_CHECKPOINT_PATH"] = old_checkpoint

    violations = check_solution(solution, bundle.instance, prices) if solution is not None else []
    if violations:
        status = "HALT_INFEASIBLE"
        failure_reason = "; ".join(str(item) for item in violations[:3])
        violation_count = len(violations)
    elif actual_evals < int(task["eval_budget"]):
        status = "HALT_RUNTIME_UNDER_EVAL" if time.perf_counter() - started >= float(task["runtime_cap_seconds"]) else "HALT_UNDER_EVAL"
        failure_reason = f"Stopped at {actual_evals}/{task['eval_budget']} evaluations."
    metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices) if solution is not None else {}
    row = {
        "run_id": task["run_id"],
        "phase": task["phase"],
        "category": task["category"],
        "instance": task["instance"],
        "size": instance_size(str(task["instance"])),
        "algorithm": algorithm,
        "display_algorithm": display_algorithm(algorithm, task),
        "seed": int(task["seed"]),
        "scenario_type": task["scenario_type"],
        "price_override": json.dumps(task.get("price_override"), ensure_ascii=False, sort_keys=True) if task.get("price_override") is not None else "",
        "components": "|".join(task.get("components", [])),
        "status": status,
        "gate_status": "OK" if status == "OK" else status,
        "failure_reason": failure_reason,
        "eval_budget": int(task["eval_budget"]),
        "actual_evals": actual_evals,
        "runtime_cap_seconds": float(task["runtime_cap_seconds"]),
        "elapsed_seconds": time.perf_counter() - started,
        "evals_per_second": safe_ratio(actual_evals, time.perf_counter() - started),
        "best_cost": best_cost,
        "best_signature": solution_signature_hash(solution) if solution is not None else "",
        "feasible": solution is not None and not violations and math.isfinite(best_cost),
        "violation_count": violation_count,
        "route_count": len(solution.routes) if solution is not None else 0,
        "cv_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv") if solution is not None else 0,
        "ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev") if solution is not None else 0,
        "charging_action_count": len(solution.charging_actions) if solution is not None else 0,
        "E_total": metrics.get("E_total", math.nan),
        "E_cv_direct": metrics.get("E_cv_direct", math.nan),
        "E_ev_indirect": metrics.get("E_ev_indirect", math.nan),
        "cost_carbon": metrics.get("cost_carbon", math.nan),
        "low_carbon_charging_share": low_carbon_charging_share(solution, bundle.instance, bundle.carbon_profile, prices) if solution is not None else math.nan,
        "native_best_updates": native_best_updates(history, algorithm),
        "route_count_unique": route_count_unique(history, solution),
        "liveness_verdict": baseline_liveness_verdict(history, solution, algorithm),
        "liveness_flags": "|".join(baseline_liveness_flags(history, solution, algorithm)),
        "common_lift": 0.0,
        "native_lift": native_lift(history, best_cost),
        "flip_lift": flip_lift(history),
        "operator_counts_json": json.dumps(operator_counts, ensure_ascii=False, sort_keys=True),
        "flags_json": json.dumps(flags, ensure_ascii=False, sort_keys=True),
        "history_json": json.dumps(history, ensure_ascii=False, sort_keys=True),
        "solution_json": json.dumps(solution_to_dict(solution), ensure_ascii=False, sort_keys=True) if solution is not None else "",
        "checkpoint_path": rel(checkpoint_path) if checkpoint_path.exists() else "",
        "head": git_head(),
    }
    return row


def run_alns_variant(algorithm: str, bundle_dir: Path, warm: Any, prices: Any, task: dict[str, Any]) -> dict[str, Any]:
    config = WinnerKernelConfig(seed=int(task["seed"]), eval_budget=int(task["eval_budget"]), max_runtime_seconds=float(task["runtime_cap_seconds"]))
    if algorithm == "alns_e2_throughput":
        return wo.run_e2_alns_throughput(bundle_dir, config=config, initial_solution=warm, prices=prices)
    if algorithm == "alns_e2_carbon":
        return wo.run_e2_alns_carbon(bundle_dir, config=config, initial_solution=warm, prices=prices, carbon_bias_weight=1.0, variant_id=algorithm)
    if algorithm == "alns_e2_carbon_ablation":
        return wo.run_e2_alns_carbon(bundle_dir, config=config, initial_solution=warm, prices=prices, carbon_bias_weight=0.0, variant_id=algorithm)
    raise ValueError(f"unsupported ALNS variant: {algorithm}")


def run_custom_alns_variant(bundle_dir: Path, warm: Any, prices: Any, task: dict[str, Any]) -> dict[str, Any]:
    profile = dict(task.get("t3_profile") or {})
    if str(task["algorithm"]) == "t3_main_alns":
        base_variant = str(profile.get("base_variant", "alns_e2_throughput"))
        components = list(profile.get("selected_components", []))
    else:
        base_variant = "alns_e2_throughput"
        components = list(task.get("components", []))
    flags, carbon_bias = flags_for_profile(base_variant, components)
    config = WinnerKernelConfig(
        seed=int(task["seed"]),
        eval_budget=int(task["eval_budget"]),
        max_runtime_seconds=float(task["runtime_cap_seconds"]),
        include_route_elimination=flags.get("SETP_ALNS_CRUSH_ROUTE_ELIMINATION") == "1",
        carbon_aware_operators=base_variant == "alns_e2_carbon",
        carbon_operator_bias=float(carbon_bias),
    )
    return wo._run_winner_variant(  # noqa: SLF001 - experimental runner needs explicit flag injection.
        bundle_dir,
        config,
        initial_solution=warm,
        prices=prices,
        variant_flags=flags,
        variant_id=display_algorithm(str(task["algorithm"]), task),
    )


def flags_for_profile(base_variant: str, components: list[str]) -> tuple[dict[str, str], float]:
    flags = wo.e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=True)
    carbon_bias = 0.0
    if base_variant == "alns_e2_carbon":
        flags["SETP_ALNS_CARBON_OPERATORS"] = "1"
        flags["SETP_ALNS_CARBON_OPERATOR_BIAS"] = "1.0"
        carbon_bias = 1.0
    elif base_variant == "alns_e2_carbon_ablation":
        flags["SETP_ALNS_CARBON_OPERATORS"] = "1"
        flags["SETP_ALNS_CARBON_OPERATOR_BIAS"] = "0.0"
        carbon_bias = 0.0
    for component in components:
        if component == "LOCAL_SEARCH":
            flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"] = "1"
        elif component == "ROUTE_ELIMINATION":
            flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"] = "1"
        elif component == "RRT_TRUE_ACCEPTANCE":
            flags["SETP_ALNS_CRUSH_TRUE_ACCEPTANCE"] = "1"
            flags["SETP_ALNS_CRUSH_SA_ACCEPTANCE"] = "0"
            flags["SETP_ALNS_CRUSH_SA_MODE"] = "off"
        else:
            raise ValueError(f"unknown component: {component}")
    return flags, carbon_bias


def decide_phase_a(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = incomplete_rows(rows)
    if failures:
        return {"schema": "setp-e2-final-phase-a-decision.v1", "verdict": "ALNS_GATE_BLOCKED", "failure_count": len(failures), "failure_sample": failures[:20]}
    component_decisions = component_adoption(rows)
    selected_components = [item["component"] for item in component_decisions if item["adopted"]]
    stack_rows = [row for row in rows if row.get("phase") == "A3_COMPONENT_STACK_RETEST"]
    if len(selected_components) > 1 and not stack_rows:
        return {
            "schema": "setp-e2-final-phase-a-decision.v1",
            "verdict": "ALNS_GATE_READY",
            "stack_retest_tasks": selected_components,
            "component_decisions": component_decisions,
            "note": "Multiple components passed one-at-a-time gate; stack retest has been scheduled.",
        }
    if stack_rows and not component_stack_passes(rows, selected_components):
        selected_components = []
    main_variant, carbon_evidence = choose_t3_main_variant(rows)
    return {
        "schema": "setp-e2-final-phase-a-decision.v1",
        "verdict": "ALNS_GATE_READY",
        "t3_main_variant": main_variant,
        "selected_components": selected_components,
        "t3_main_profile": {"base_variant": main_variant, "selected_components": selected_components},
        "component_decisions": component_decisions,
        "carbon_evidence": carbon_evidence,
        "algorithm_win_loss_claim": False,
    }


def component_adoption(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    base = {int(row["seed"]): row for row in rows if row.get("phase") == "A2_COMPONENT_ABLATION" and row.get("algorithm") == "alns_e2_throughput"}
    for component in COMPONENT_ORDER:
        group = {int(row["seed"]): row for row in rows if row.get("phase") == "A2_COMPONENT_ABLATION" and row.get("components") == component}
        improvements = []
        single_worst = 0.0
        for seed, base_row in base.items():
            comp = group.get(seed)
            if not comp:
                continue
            improvement = safe_ratio(as_float(base_row["best_cost"]) - as_float(comp["best_cost"]), as_float(base_row["best_cost"]))
            improvements.append(improvement)
            single_worst = min(single_worst, improvement)
        mean_improvement = statistics.mean(improvements) if improvements else math.nan
        adopted = bool(improvements) and mean_improvement > 0.005 and single_worst >= -0.01
        decisions.append({"component": component, "mean_improvement_fraction": mean_improvement, "worst_seed_improvement_fraction": single_worst, "adopted": adopted})
    return sorted(decisions, key=lambda item: as_float(item["mean_improvement_fraction"]), reverse=True)


def component_stack_passes(rows: list[dict[str, Any]], components: list[str]) -> bool:
    base = {int(row["seed"]): row for row in rows if row.get("phase") == "A2_COMPONENT_ABLATION" and row.get("algorithm") == "alns_e2_throughput"}
    stack = {int(row["seed"]): row for row in rows if row.get("phase") == "A3_COMPONENT_STACK_RETEST"}
    improvements = [safe_ratio(as_float(base[seed]["best_cost"]) - as_float(stack[seed]["best_cost"]), as_float(base[seed]["best_cost"])) for seed in base if seed in stack]
    return bool(improvements) and statistics.mean(improvements) > 0.005 and min(improvements) >= -0.01


def choose_t3_main_variant(rows: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    formal = [row for row in rows if row.get("phase") == "A1_CARBON_GATE" and row.get("scenario_type") == "formal_goeke80"]
    diagnostic = [row for row in rows if row.get("phase") == "A1_CARBON_GATE" and row.get("scenario_type") == "diagnostic_280_override"]
    formal_mean = {alg: mean_cost([row for row in formal if row.get("algorithm") == alg]) for alg in ALNS_GATE_ALGORITHMS}
    carbon_not_costly = formal_mean["alns_e2_carbon"] <= formal_mean["alns_e2_throughput"] * 1.005
    diag_pairs = paired_by_instance_seed(diagnostic, "alns_e2_carbon", "alns_e2_carbon_ablation")
    e_total_all_lower = all(as_float(pair[0].get("E_total")) < as_float(pair[1].get("E_total")) for pair in diag_pairs) if diag_pairs else False
    carbon_cost_all_lower = all(as_float(pair[0].get("cost_carbon")) < as_float(pair[1].get("cost_carbon")) for pair in diag_pairs) if diag_pairs else False
    carbon_directional = e_total_all_lower or carbon_cost_all_lower
    chosen = "alns_e2_carbon" if carbon_not_costly and carbon_directional else "alns_e2_throughput"
    return chosen, {
        "formal_mean_cost": formal_mean,
        "carbon_not_costly": carbon_not_costly,
        "diagnostic_pair_count": len(diag_pairs),
        "diagnostic_e_total_all_lower": e_total_all_lower,
        "diagnostic_cost_carbon_all_lower": carbon_cost_all_lower,
        "carbon_directional": carbon_directional,
    }


def decide_phase_b(rows: list[dict[str, Any]], liveness_rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = incomplete_rows(rows)
    pass_set: list[str] = []
    excluded: list[str] = []
    for algorithm in G3_CANDIDATE_BASELINES:
        alg_rows = [row for row in rows if row.get("algorithm") == algorithm]
        alg_liveness = [row for row in liveness_rows if row.get("algorithm") == algorithm]
        has_fail = any(row.get("verdict") in {"BASELINE_LIVENESS_FAIL", "SEED_INVARIANCE_SUSPECT", "CROSS_ALGO_IDENTITY_SUSPECT"} for row in alg_liveness)
        if len(alg_rows) == 3 and not has_fail and not incomplete_rows(alg_rows):
            pass_set.append(algorithm)
        else:
            excluded.append(algorithm)
    verdict = "G3_BASELINE_SET_READY" if not excluded and not failures else "G3_WEAK_IMPLEMENTATIONS_EXCLUDED"
    baseline_set = list(BASE_T3_BASELINES) + pass_set
    return {
        "schema": "setp-e2-final-phase-b-decision.v1",
        "verdict": verdict,
        "t3_baseline_set": baseline_set,
        "passed_g3_baselines": pass_set,
        "weak_implementation_excluded": excluded,
        "failure_count": len(failures),
        "failure_sample": failures[:20],
        "baseline_set_boundary": {
            "base": list(BASE_T3_BASELINES),
            "passed_g3": pass_set,
            "excluded": excluded,
            "not_implemented_for_t3_boundary": ["SA", "TS"],
        },
    }


def decide_phase_c(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = incomplete_rows(rows)
    gaps = g4_gap_rows(rows)
    nonnegative_count = sum(1 for row in gaps if as_float(row.get("gap_fraction")) >= 0.0)
    pooled_gap = pooled_g4_gap(rows)
    max_lns_advantage = min([as_float(row.get("gap_fraction")) for row in gaps] or [math.nan])
    direction_ok = len(gaps) == 9 and nonnegative_count >= 6 and pooled_gap >= 0.0 and max_lns_advantage >= -0.02
    verdict = "G4_STABILITY_PASS" if not failures and direction_ok else ("G4_COLLECTION_PARTIAL" if failures else "HALT_G4_SUSPECT")
    return {
        "schema": "setp-e2-final-phase-c-decision.v1",
        "verdict": verdict,
        "failure_count": len(failures),
        "failure_sample": failures[:20],
        "g4_instances": len(gaps),
        "nonnegative_gap_instances": nonnegative_count,
        "pooled_gap_fraction": pooled_gap,
        "worst_instance_gap_fraction": max_lns_advantage,
        "direction_rule": ">=6/9 gap>=0, pooled gap>=0, no instance below -2%",
    }


def decide_phase_d(rows: list[dict[str, Any]], liveness_rows: list[dict[str, Any]], baseline_set: list[str]) -> dict[str, Any]:
    failures = incomplete_rows(rows)
    suspects = [row for row in liveness_rows if str(row.get("verdict", "")).endswith("_SUSPECT") or row.get("verdict") == "BASELINE_LIVENESS_FAIL"]
    if suspects:
        verdict = "HALT_T3_SUSPECT"
    elif failures:
        verdict = "T3_COLLECTION_PARTIAL"
    else:
        verdict = "T3_MATERIAL_READY"
    return {
        "schema": "setp-e2-final-phase-d-decision.v1",
        "verdict": verdict,
        "tier1_rows": len(rows),
        "baseline_set": baseline_set,
        "failure_count": len(failures),
        "failure_sample": failures[:20],
        "suspect_count": len(suspects),
        "suspect_sample": suspects[:20],
        "algorithm_win_loss_claim": False,
    }


def final_decision(output_dir: Path) -> dict[str, Any]:
    phases = {
        "phase_a": read_json(output_dir / "phase_a_alns_gate/decision.json") if (output_dir / "phase_a_alns_gate/decision.json").exists() else {},
        "phase_b": read_json(output_dir / "phase_b_g3_baseline_health/decision.json") if (output_dir / "phase_b_g3_baseline_health/decision.json").exists() else {},
        "phase_c": read_json(output_dir / "phase_c_g4_stability/decision.json") if (output_dir / "phase_c_g4_stability/decision.json").exists() else {},
        "phase_d": read_json(output_dir / "phase_d_g5_t3_material/decision.json") if (output_dir / "phase_d_g5_t3_material/decision.json").exists() else {},
    }
    return {
        "schema": "setp-e2-final-closure-decision.v1",
        "head": git_head(),
        "phase_verdicts": {key: value.get("verdict", "MISSING") for key, value in phases.items()},
        "t3_main_profile": phases["phase_a"].get("t3_main_profile"),
        "t3_baseline_set": phases["phase_b"].get("t3_baseline_set"),
        "final_material_verdict": phases["phase_d"].get("verdict", "MISSING"),
        "not_paper_text": True,
        "algorithm_win_loss_claim": False,
        "user_decisions_remaining": [
            "T3 table wording and paper posture",
            "Whether SA/TS absence is stated as limitation",
            "Whether DR-ALNS waits for x86 lane as future work or extended table",
        ],
    }


def prices_for_scenario(scenario_type: str) -> Any:
    if scenario_type == "formal_goeke80":
        return DEFAULT_PRICES
    if scenario_type == "diagnostic_280_override":
        return replace(DEFAULT_PRICES, B_battery_kwh=DIAGNOSTIC_BATTERY_KWH, carbon_price=CARBON_PRICE)
    raise ValueError(f"unknown scenario_type: {scenario_type}")


def price_override_payload(scenario_type: str) -> dict[str, float] | None:
    if scenario_type == "formal_goeke80":
        return None
    if scenario_type == "diagnostic_280_override":
        return {"B_battery_kwh": DIAGNOSTIC_BATTERY_KWH, "carbon_price": CARBON_PRICE}
    raise ValueError(f"unknown scenario_type: {scenario_type}")


def tier1_instance_manifest() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category_dir in sorted(INSTANCE_ROOT.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name
        for instance_dir in sorted(category_dir.iterdir()):
            if not instance_dir.is_dir() or not instance_dir.name.endswith("-01"):
                continue
            rows.append({"tier": "Tier1", "category": category, "instance": instance_dir.name, "size": instance_size(instance_dir.name), "bundle_dir": rel(instance_dir)})
    rows.sort(key=lambda row: (int(row["size"]), str(row["category"]), str(row["instance"])))
    return rows


def runtime_cap_for_instance(instance: str) -> float:
    size = instance_size(instance)
    if size <= 100:
        return 2700.0
    if size <= 150:
        return 3600.0
    if size <= 200:
        return 5400.0
    raise ValueError(f"HALT_WALLCLOCK_CLASS_UNRESOLVED: {instance}")


def instance_size(instance: str) -> int:
    match = re.search(r"-(\d+)c-", instance)
    if not match:
        raise ValueError(f"cannot parse E2 size from {instance}")
    return int(match.group(1))


def run_id_for(phase: str, scenario_type: str, category: str, instance: str, algorithm: str, seed: int, components: list[str]) -> str:
    suffix = ("__" + "-".join(components)) if components else ""
    safe = f"{phase}__{scenario_type}__{category}__{instance}__{algorithm}{suffix}__seed{seed}"
    return re.sub(r"[^A-Za-z0-9_.=-]+", "_", safe)


def display_algorithm(algorithm: str, task: dict[str, Any]) -> str:
    if algorithm == "t3_main_alns":
        profile = task.get("t3_profile") or {}
        comps = profile.get("selected_components", [])
        return f"{profile.get('base_variant', 'alns_e2_throughput')}+{'+'.join(comps) if comps else 'base'}"
    if algorithm == "alns_component_stack":
        return "alns_e2_throughput+" + "+".join(task.get("components", []))
    if algorithm.startswith("alns_component_"):
        return "alns_e2_throughput+" + algorithm.replace("alns_component_", "")
    return algorithm


def normalize_alns_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in history:
        row = dict(item)
        op = str(row.get("operator", ""))
        if op == "shared_warm_start":
            row.setdefault("channel", "shared_warm_start")
        else:
            row.setdefault("channel", f"native_{op}")
        rows.append(row)
    return rows


def native_best_updates(history: list[dict[str, Any]], algorithm: str) -> int:
    if algorithm not in BASELINE_ALGORITHMS:
        return len([item for item in history if str(item.get("channel", "")).startswith("native_")])
    return len([item for item in history if str(item.get("channel", "")).startswith("native_")])


def route_count_unique(history: list[dict[str, Any]], solution: Any) -> int:
    values = {int(as_float(item.get("route_count"))) for item in history if math.isfinite(as_float(item.get("route_count")))}
    if solution is not None:
        values.add(len(solution.routes))
    return len(values)


def baseline_liveness_flags(history: list[dict[str, Any]], solution: Any, algorithm: str) -> list[str]:
    if algorithm not in BASELINE_ALGORITHMS:
        return []
    flags: list[str] = []
    if native_best_updates(history, algorithm) < 1:
        flags.append("NO_NATIVE_BEST_UPDATE")
    if route_count_unique(history, solution) < 5:
        flags.append("LOW_ROUTE_COUNT_DIVERSITY")
    return flags


def baseline_liveness_verdict(history: list[dict[str, Any]], solution: Any, algorithm: str) -> str:
    flags = baseline_liveness_flags(history, solution, algorithm)
    if algorithm not in BASELINE_ALGORITHMS:
        return "NOT_BASELINE_ALNS_REFERENCE"
    return "BASELINE_LIVENESS_PASS" if not flags else "BASELINE_LIVENESS_FAIL"


def native_lift(history: list[dict[str, Any]], best_cost: float) -> float:
    starts = [as_float(item.get("best_cost")) for item in history if item.get("operator") == "shared_warm_start"]
    if not starts or not math.isfinite(best_cost):
        return 0.0
    return max(0.0, starts[0] - float(best_cost))


def flip_lift(history: list[dict[str, Any]]) -> float:
    return sum(max(0.0, as_float(item.get("best_cost_before")) - as_float(item.get("best_cost"))) for item in history if item.get("channel") == "flip_operator")


def liveness_verdicts(rows: list[dict[str, Any]], algorithms: tuple[str, ...] | list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("algorithm") in algorithms:
            out.append({"scope": "run", "algorithm": row.get("algorithm"), "seed": row.get("seed"), "run_id": row.get("run_id"), "verdict": row.get("liveness_verdict"), "flags": row.get("liveness_flags"), "native_best_updates": row.get("native_best_updates"), "route_count_unique": row.get("route_count_unique")})
    for algorithm in algorithms:
        group = [row for row in rows if row.get("algorithm") == algorithm]
        if len(group) < 2:
            continue
        costs = {str(row.get("best_cost")) for row in group}
        signatures = {str(row.get("best_signature")) for row in group}
        suspect = len(costs) == 1 and len(signatures) == 1
        out.append({"scope": "algorithm_seed_group", "algorithm": algorithm, "seed": "|".join(str(row.get("seed")) for row in group), "run_id": "", "verdict": "SEED_INVARIANCE_SUSPECT" if suspect else "SEED_VARIATION_OK", "flags": "exact_cost_and_signature_repeated_across_seeds" if suspect else ""})
    signature_to_algorithms: dict[str, set[str]] = {}
    for row in rows:
        if row.get("algorithm") in algorithms:
            signature_to_algorithms.setdefault(str(row.get("best_signature")), set()).add(str(row.get("algorithm")))
    for signature, algs in sorted(signature_to_algorithms.items()):
        if len(algs) > 1:
            out.append({"scope": "cross_algorithm", "algorithm": "|".join(sorted(algs)), "seed": "", "run_id": "", "verdict": "CROSS_ALGO_IDENTITY_SUSPECT", "flags": f"shared_signature={signature}"})
    return out


def incomplete_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for row in rows:
        if row.get("gate_status") != "OK":
            failures.append({"run_id": row.get("run_id"), "status": row.get("gate_status"), "reason": row.get("failure_reason")})
        elif int(as_float(row.get("actual_evals"), -1)) < int(as_float(row.get("eval_budget"), -2)):
            failures.append({"run_id": row.get("run_id"), "status": "UNDER_EVAL", "actual": row.get("actual_evals"), "expected": row.get("eval_budget")})
    return failures


def all_history_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            history = json.loads(row.get("history_json") or "[]")
        except json.JSONDecodeError:
            history = []
        for idx, item in enumerate(history):
            out.append({"run_id": row.get("run_id"), "phase": row.get("phase"), "algorithm": row.get("algorithm"), "display_algorithm": row.get("display_algorithm"), "category": row.get("category"), "instance": row.get("instance"), "seed": row.get("seed"), "step": idx, "eval": item.get("eval", ""), "operator": item.get("operator", ""), "channel": item.get("channel", ""), "best_cost": item.get("best_cost", ""), "route_count": item.get("route_count", ""), "time_seconds": item.get("time_seconds", "")})
    return sorted_rows(out)


def channel_lift_row(row: dict[str, Any]) -> dict[str, Any]:
    return {"run_id": row.get("run_id"), "phase": row.get("phase"), "algorithm": row.get("algorithm"), "display_algorithm": row.get("display_algorithm"), "category": row.get("category"), "instance": row.get("instance"), "seed": row.get("seed"), "best_cost": row.get("best_cost"), "common_lift": row.get("common_lift"), "native_lift": row.get("native_lift"), "flip_lift": row.get("flip_lift"), "native_best_updates": row.get("native_best_updates"), "route_count_unique": row.get("route_count_unique")}


def summarize_rows(rows: list[dict[str, Any]], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(tuple(str(row.get(key, "")) for key in keys), []).append(row)
    out: list[dict[str, Any]] = []
    for group_key, group in groups.items():
        costs = [as_float(row.get("best_cost")) for row in group if math.isfinite(as_float(row.get("best_cost")))]
        item = {key: value for key, value in zip(keys, group_key)}
        item.update({"rows": len(group), "ok_rows": len(group) - len(incomplete_rows(group)), "mean_best_cost": statistics.mean(costs) if costs else math.nan, "min_best_cost": min(costs) if costs else math.nan, "mean_E_total": mean_field(group, "E_total"), "mean_cost_carbon": mean_field(group, "cost_carbon"), "mean_low_carbon_charging_share": mean_field(group, "low_carbon_charging_share")})
        out.append(item)
    return sorted_rows(out)


def mean_field(rows: list[dict[str, Any]], field: str) -> float:
    values = [as_float(row.get(field)) for row in rows if math.isfinite(as_float(row.get(field)))]
    return statistics.mean(values) if values else math.nan


def mean_cost(rows: list[dict[str, Any]]) -> float:
    return mean_field(rows, "best_cost")


def paired_by_instance_seed(rows: list[dict[str, Any]], left_alg: str, right_alg: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    left = {(row.get("category"), row.get("instance"), int(row.get("seed", 0))): row for row in rows if row.get("algorithm") == left_alg}
    right = {(row.get("category"), row.get("instance"), int(row.get("seed", 0))): row for row in rows if row.get("algorithm") == right_alg}
    return [(left[key], right[key]) for key in sorted(left) if key in right]


def g4_gap_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for category, instance in G4_INSTANCES:
        group = [row for row in rows if row.get("category") == category and row.get("instance") == instance]
        alns = [row for row in group if row.get("algorithm") == "t3_main_alns"]
        lns = [row for row in group if row.get("algorithm") == "LNS"]
        if len(alns) == 3 and len(lns) == 3:
            mean_alns = mean_cost(alns)
            mean_lns = mean_cost(lns)
            out.append({"category": category, "instance": instance, "mean_alns": mean_alns, "mean_lns": mean_lns, "gap_fraction": safe_ratio(mean_lns - mean_alns, mean_lns), "direction": "ALNS_NOT_WORSE" if mean_alns <= mean_lns else "LNS_LOWER"})
    return out


def pooled_g4_gap(rows: list[dict[str, Any]]) -> float:
    alns = [as_float(row.get("best_cost")) for row in rows if row.get("algorithm") == "t3_main_alns"]
    lns = [as_float(row.get("best_cost")) for row in rows if row.get("algorithm") == "LNS"]
    return safe_ratio(statistics.mean(lns) - statistics.mean(alns), statistics.mean(lns)) if alns and lns else math.nan


def t3_table_material(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return summarize_rows(rows, keys=("category", "instance", "display_algorithm"))


def wilcoxon_rows(rows: list[dict[str, Any]], baseline_set: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for baseline in baseline_set:
        pairs = paired_costs(rows, "t3_main_alns", baseline)
        diffs = [left - right for left, right in pairs]
        p_value = math.nan
        statistic = math.nan
        if diffs:
            try:
                from scipy.stats import wilcoxon  # type: ignore

                result = wilcoxon(diffs, zero_method="wilcox", alternative="less")
                statistic = float(result.statistic)
                p_value = float(result.pvalue)
            except Exception:
                pass
        out.append({"baseline": baseline, "paired_count": len(pairs), "wilcoxon_statistic": statistic, "p_value_alns_less": p_value, "note": "neutral material only; user writes paper claim"})
    return out


def win_tie_loss_rows(rows: list[dict[str, Any]], baseline_set: list[str]) -> list[dict[str, Any]]:
    out = []
    for baseline in baseline_set:
        pairs = paired_costs(rows, "t3_main_alns", baseline)
        wins = sum(1 for left, right in pairs if left < right - 1e-9)
        ties = sum(1 for left, right in pairs if abs(left - right) <= 1e-9)
        losses = sum(1 for left, right in pairs if left > right + 1e-9)
        out.append({"baseline": baseline, "paired_count": len(pairs), "alns_lower": wins, "tie": ties, "alns_higher": losses})
    return out


def paired_costs(rows: list[dict[str, Any]], left_alg: str, right_alg: str) -> list[tuple[float, float]]:
    left = {(row.get("category"), row.get("instance"), int(row.get("seed", 0))): as_float(row.get("best_cost")) for row in rows if row.get("algorithm") == left_alg}
    right = {(row.get("category"), row.get("instance"), int(row.get("seed", 0))): as_float(row.get("best_cost")) for row in rows if row.get("algorithm") == right_alg}
    return [(left[key], right[key]) for key in sorted(left) if key in right and math.isfinite(left[key]) and math.isfinite(right[key])]


def write_report(output_dir: Path) -> None:
    decision = read_json(output_dir / "decision.json") if (output_dir / "decision.json").exists() else {}
    lines = [
        "# E2 Final Closure",
        "",
        "本工程只生成交稿前证据素材：ALNS 定型 gate、G3 baseline health、G4 stability、G5 T3/F2 material。它不自动写 TeX，不写算法胜负主张。",
        "",
        f"Verdict: `{decision.get('final_material_verdict', decision.get('verdict', 'MISSING'))}`",
        "",
        "## Phase Verdicts",
        "",
    ]
    for phase, verdict in (decision.get("phase_verdicts") or {}).items():
        lines.append(f"- {phase}: `{verdict}`")
    lines.extend(["", "## Remaining User Decisions", ""])
    for item in decision.get("user_decisions_remaining", []):
        lines.append(f"- {item}")
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_phase_report(phase_dir: Path, title: str, decision: dict[str, Any]) -> None:
    lines = [f"# {title}", "", f"Verdict: `{decision.get('verdict')}`", "", "本报告是 evidence material，不自动写入 TeX，不构成论文胜负表述。", "", "```json", json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True), "```", ""]
    (phase_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def write_hashes(output_dir: Path) -> None:
    clean_artifact_dir(output_dir)
    write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir))
    clean_artifact_dir(output_dir)


def halt_decision(verdict: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"schema": "setp-e2-final-closure-decision.v1", "verdict": verdict, "payload": payload, "algorithm_win_loss_claim": False}


def failure_row(task: dict[str, Any], status: str, reason: str, started: float) -> dict[str, Any]:
    return {"run_id": task.get("run_id"), "phase": task.get("phase"), "category": task.get("category"), "instance": task.get("instance"), "algorithm": task.get("algorithm"), "display_algorithm": display_algorithm(str(task.get("algorithm")), task), "seed": task.get("seed"), "scenario_type": task.get("scenario_type"), "status": status, "gate_status": status, "failure_reason": reason, "eval_budget": task.get("eval_budget"), "actual_evals": 0, "runtime_cap_seconds": task.get("runtime_cap_seconds"), "elapsed_seconds": time.perf_counter() - started, "best_cost": math.inf, "violation_count": -1}


def timeout_row(task: dict[str, Any], elapsed: float, stdout: Any, stderr: Any) -> dict[str, Any]:
    return {"run_id": task.get("run_id"), "phase": task.get("phase"), "category": task.get("category"), "instance": task.get("instance"), "algorithm": task.get("algorithm"), "display_algorithm": display_algorithm(str(task.get("algorithm")), task), "seed": task.get("seed"), "scenario_type": task.get("scenario_type"), "status": "HALT_HARD_TIMEOUT", "gate_status": "HALT_HARD_TIMEOUT", "failure_reason": f"subprocess timeout after {elapsed:.1f}s; stdout_tail={str(stdout)[-500:]}; stderr_tail={str(stderr)[-500:]}", "eval_budget": task.get("eval_budget"), "actual_evals": 0, "runtime_cap_seconds": task.get("runtime_cap_seconds"), "elapsed_seconds": elapsed, "best_cost": math.inf, "violation_count": -1}


def worker_error_row(task: dict[str, Any], status: str, stdout: str, stderr: str, elapsed: float) -> dict[str, Any]:
    return {"run_id": task.get("run_id"), "phase": task.get("phase"), "category": task.get("category"), "instance": task.get("instance"), "algorithm": task.get("algorithm"), "display_algorithm": display_algorithm(str(task.get("algorithm")), task), "seed": task.get("seed"), "scenario_type": task.get("scenario_type"), "status": status, "gate_status": status, "failure_reason": f"stdout_tail={stdout[-800:]}; stderr_tail={stderr[-1200:]}", "eval_budget": task.get("eval_budget"), "actual_evals": 0, "runtime_cap_seconds": task.get("runtime_cap_seconds"), "elapsed_seconds": elapsed, "best_cost": math.inf, "violation_count": -1}


def protected_diff() -> list[str]:
    proc = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", *PROTECTED_PATHS], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def artifact_hashes(root: Path) -> dict[str, Any]:
    files: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in HASH_EXCLUDE_NAMES or path.name.startswith("._"):
            continue
        if any(part in HASH_EXCLUDE_PARTS for part in path.parts):
            continue
        files.append({"path": rel(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return {"schema": "setp-artifact-hashes.v1", "root": rel(root), "file_count": len(files), "files": files}


def clean_artifact_dir(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    for path in sorted(output_dir.rglob("*"), reverse=True):
        if path.name.startswith("._") or path.name in {"__pycache__", ".pytest_cache"}:
            if path.is_dir():
                import shutil

                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def parse_seeds(text: str) -> list[int]:
    return [int(item.strip()) for item in str(text).split(",") if item.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (str(row.get("phase", "")), str(row.get("scenario_type", "")), str(row.get("category", "")), str(row.get("instance", "")), str(row.get("algorithm", "")), int(as_float(row.get("seed"), 0)), str(row.get("run_id", ""))))


def repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()


def numpy_version() -> str:
    import numpy as np

    return str(np.__version__)


def safe_ratio(num: Any, denom: Any) -> float:
    d = as_float(denom)
    if not math.isfinite(d) or abs(d) <= 1e-12:
        return math.nan
    return as_float(num) / d


def as_float(value: Any, default: float = math.nan) -> float:
    try:
        if value in {"", None}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    raise SystemExit(main())
