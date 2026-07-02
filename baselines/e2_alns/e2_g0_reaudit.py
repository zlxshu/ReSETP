#!/usr/bin/env python3
"""E2-G0 closure reaudit runner.

This runner is for baseline health / G0 gate evidence only. It keeps the solver
referee and ALNS main path fixed, uses the 280 kWh scenario only as an in-memory
diagnostic override, and writes a dual ledger for every task it runs.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import csv
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterator


REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "solver/src", REPO_ROOT / "models/src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search import metaheuristic_baselines as mb
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution, solution_signature_hash
from setp_solver.search.metaheuristic_baselines import baseline_result_to_dict, run_metaheuristic_baseline, solution_to_dict
from setp_solver.search.winner_operators import WinnerKernelConfig, run_e2_alns_throughput

from baselines.e2_alns.bridge_fix_validation import EXPECTED_GO_EKE_CURRENT_COST, EXPECTED_THREESHIFT_280_COST, run_anchor_parity


GOLD_PYTHON = "/opt/anaconda3/bin/python3.13"
GOLD_NUMPY = "2.3.5"
CARBON_PRICE = 0.05034
BATTERY_KWH = 280.0
INSTANCE_CATEGORY = "threeshift"
INSTANCE_NAME = "e2-threeshift-150c-01"
INSTANCE_ROOT = REPO_ROOT / "models/data_bundle/generated_instances/e2_benchmark"
THREESHIFT_BUNDLE = INSTANCE_ROOT / INSTANCE_CATEGORY / INSTANCE_NAME
GOEKE_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113"
OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/e2_g0_reaudit_20260702"
BASELINES = ("GA", "LNS", "PSO", "VNS")
HASH_EXCLUDE_NAMES = {".DS_Store", "artifact_hashes.json"}
HASH_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--phase", choices=["true-repair-ab", "g0", "scenario", "legacy", "decision", "all"], default="all")
    parser.add_argument("--eval-budget", type=int, default=16000)
    parser.add_argument("--ab-eval-budget", type=int, default=2000)
    parser.add_argument("--runtime-cap-seconds", type=float, default=2700.0)
    parser.add_argument("--ab-runtime-cap-seconds", type=float, default=600.0)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-legacy", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = repo_path(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    clean_artifact_dir(output_dir)
    metadata = build_metadata(args, output_dir)
    write_json(output_dir / "metadata.json", metadata)
    write_json(output_dir / "preflight.json", preflight())

    if args.phase in {"true-repair-ab", "all"}:
        ab_rows = run_true_repair_ab(output_dir, eval_budget=int(args.ab_eval_budget), runtime_cap_seconds=float(args.ab_runtime_cap_seconds), force=bool(args.force))
        write_csv(output_dir / "true_repair_ab.csv", ab_rows)
        write_json(output_dir / "true_repair_decision.json", decide_true_repair_alignment(ab_rows))

    if args.phase in {"g0", "all"}:
        raw_rows, trajectory_rows, lift_rows = run_g0(output_dir, seeds=parse_seeds(args.seeds), eval_budget=int(args.eval_budget), runtime_cap_seconds=float(args.runtime_cap_seconds), force=bool(args.force))
        write_csv(output_dir / "raw_runs.csv", raw_rows)
        write_csv(output_dir / "best_trajectory.csv", trajectory_rows)
        write_csv(output_dir / "channel_lift.csv", lift_rows)
        liveness_rows = liveness_verdicts(raw_rows)
        write_csv(output_dir / "liveness_verdicts.csv", liveness_rows)

    if args.phase in {"scenario", "all"}:
        write_json(output_dir / "scenario_compliance.json", scenario_compliance_audit())

    if args.phase in {"legacy", "all"}:
        legacy = {"status": "SKIPPED"} if args.skip_legacy else legacy_anchor_archaeology()
        write_json(output_dir / "legacy_anchor.json", legacy)

    if args.phase in {"decision", "all"}:
        decision = decide(output_dir)
        write_json(output_dir / "decision.json", decision)
        (output_dir / "report.md").write_text(render_report(output_dir, decision), encoding="utf-8")

    clean_artifact_dir(output_dir)
    write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir))
    clean_artifact_dir(output_dir)
    print(json.dumps(read_json(output_dir / "decision.json") if (output_dir / "decision.json").exists() else {"phase": args.phase, "status": "DONE"}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_metadata(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    return {
        "schema": "setp-e2-g0-reaudit.v1",
        "task": "E2-G0 closure: common flip accounting, liveness gate, true repair alignment, G0 reaudit",
        "head": git_head(),
        "python": sys.executable,
        "numpy": numpy_version(),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "phase": args.phase,
        "output_dir": rel(output_dir),
        "instance": INSTANCE_NAME,
        "battery_override": "dataclasses.replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034)",
        "eval_budget": int(args.eval_budget),
        "ab_eval_budget": int(args.ab_eval_budget),
        "runtime_cap_seconds": float(args.runtime_cap_seconds),
        "ab_runtime_cap_seconds": float(args.ab_runtime_cap_seconds),
        "seeds": parse_seeds(args.seeds),
        "protected_boundary": [
            "no cost.py/check.py/evaluation.py/prices.py default/TeX changes",
            "no feasible_repair.py/resetp_alns/ALNS main path semantic changes",
            "not formal T3; no algorithm win/loss claim",
        ],
        "started_at_epoch": time.time(),
    }


def preflight() -> dict[str, Any]:
    return {
        "env_ok": sys.executable == GOLD_PYTHON and numpy_version() == GOLD_NUMPY and os.environ.get("PYTHONHASHSEED") == "0",
        "python": sys.executable,
        "numpy": numpy_version(),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "protected_diff": protected_diff(),
        "expected_anchor_costs": {
            "goeke80_100_01_seed2_current_q3650": EXPECTED_GO_EKE_CURRENT_COST,
            "threeshift_150c_01_seed1_B280_eval2000": EXPECTED_THREESHIFT_280_COST,
        },
    }


def make_probe_prices() -> Any:
    return replace(DEFAULT_PRICES, B_battery_kwh=BATTERY_KWH, carbon_price=CARBON_PRICE)


def run_true_repair_ab(output_dir: Path, *, eval_budget: int, runtime_cap_seconds: float, force: bool) -> list[dict[str, Any]]:
    rows = read_csv(output_dir / "true_repair_ab.csv")
    completed = {row.get("run_id") for row in rows}
    for algorithm in ("LNS", "GA"):
        for mode in ("true_repair_forced_0", "true_repair_cost_aware_1"):
            run_id = f"AB_{algorithm}_{mode}_seed1"
            if run_id in completed and not force:
                continue
            row = run_baseline_row(
                run_id=run_id,
                phase="D_TRUE_REPAIR_AB",
                algorithm=algorithm,
                seed=1,
                eval_budget=eval_budget,
                runtime_cap_seconds=runtime_cap_seconds,
                true_repair_mode=mode,
                common_flip_preprocess=True,
                output_dir=output_dir,
            )
            rows = [existing for existing in rows if existing.get("run_id") != run_id]
            rows.append(row)
            write_csv(output_dir / "true_repair_ab.csv", rows)
    return sorted_rows(rows)


def run_g0(
    output_dir: Path,
    *,
    seeds: list[int],
    eval_budget: int,
    runtime_cap_seconds: float,
    force: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    raw_rows = read_csv(output_dir / "raw_runs.csv")
    trajectory_rows = read_csv(output_dir / "best_trajectory.csv")
    lift_rows = read_csv(output_dir / "channel_lift.csv")
    completed = {row.get("run_id") for row in raw_rows}
    for seed in seeds:
        for algorithm in BASELINES:
            run_id = f"G0_{algorithm}_seed{seed}"
            if run_id in completed and not force:
                continue
            row = run_baseline_row(
                run_id=run_id,
                phase="E_G0_REAUDIT",
                algorithm=algorithm,
                seed=seed,
                eval_budget=eval_budget,
                runtime_cap_seconds=runtime_cap_seconds,
                true_repair_mode="current",
                common_flip_preprocess=True,
                output_dir=output_dir,
            )
            raw_rows = [existing for existing in raw_rows if existing.get("run_id") != run_id]
            raw_rows.append(row)
            trajectory_rows = [existing for existing in trajectory_rows if existing.get("run_id") != run_id]
            trajectory_rows.extend(history_rows(row))
            lift_rows = [existing for existing in lift_rows if existing.get("run_id") != run_id]
            lift_rows.append(channel_lift_row(row))
            write_csv(output_dir / "raw_runs.csv", sorted_rows(raw_rows))
            write_csv(output_dir / "best_trajectory.csv", sorted_rows(trajectory_rows))
            write_csv(output_dir / "channel_lift.csv", sorted_rows(lift_rows))
        run_id = f"G0_ALNS_seed{seed}"
        if run_id not in completed or force:
            row = run_alns_row(
                run_id=run_id,
                phase="E_G0_REAUDIT",
                seed=seed,
                eval_budget=eval_budget,
                runtime_cap_seconds=runtime_cap_seconds,
            )
            raw_rows = [existing for existing in raw_rows if existing.get("run_id") != run_id]
            raw_rows.append(row)
            trajectory_rows = [existing for existing in trajectory_rows if existing.get("run_id") != run_id]
            trajectory_rows.extend(history_rows(row))
            lift_rows = [existing for existing in lift_rows if existing.get("run_id") != run_id]
            lift_rows.append(channel_lift_row(row))
            write_csv(output_dir / "raw_runs.csv", sorted_rows(raw_rows))
            write_csv(output_dir / "best_trajectory.csv", sorted_rows(trajectory_rows))
            write_csv(output_dir / "channel_lift.csv", sorted_rows(lift_rows))
    return sorted_rows(raw_rows), sorted_rows(trajectory_rows), sorted_rows(lift_rows)


def run_baseline_row(
    *,
    run_id: str,
    phase: str,
    algorithm: str,
    seed: int,
    eval_budget: int,
    runtime_cap_seconds: float,
    true_repair_mode: str,
    common_flip_preprocess: bool,
    output_dir: Path,
) -> dict[str, Any]:
    prices = make_probe_prices()
    bundle = load_search_bundle(THREESHIFT_BUNDLE)
    warm = make_shared_initial_solution(bundle, prices=prices)
    checkpoint = output_dir / "checkpoints" / f"{run_id}.json"
    started = time.perf_counter()
    try:
        with temporary_checkpoint(checkpoint), true_repair_context(true_repair_mode):
            result = run_metaheuristic_baseline(
                algorithm,
                bundle.bundle_dir,
                seed=int(seed),
                eval_budget=int(eval_budget),
                max_runtime_seconds=float(runtime_cap_seconds),
                initial_solution=warm,
                prices=prices,
                common_flip_preprocess=bool(common_flip_preprocess),
            )
        payload = baseline_result_to_dict(result, include_solution=True)
        solution = result.best_solution
        row = {
            "run_id": run_id,
            "phase": phase,
            "algorithm": algorithm,
            "seed": int(seed),
            "status": result.status,
            "gate_status": "OK" if result.status == "OK" else result.status,
            "failure_reason": result.failure_reason,
            "eval_budget": int(eval_budget),
            "actual_evals": int(result.evals),
            "max_runtime_seconds": float(runtime_cap_seconds),
            "elapsed_seconds": float(result.elapsed_seconds),
            "candidate_per_second": safe_ratio(result.evals, result.elapsed_seconds),
            "best_cost": result.best_cost,
            "best_signature": result.solution_signature_hash,
            "feasible": result.feasible,
            "violation_count": result.violation_count,
            "route_count": result.route_count,
            "cv_route_count": result.cv_route_count,
            "ev_route_count": result.ev_route_count,
            "charging_action_count": len(solution.charging_actions) if solution is not None else 0,
            "common_preprocess_cost": result.common_preprocess_cost,
            "common_preprocess_attempts": result.common_preprocess_attempts,
            "common_preprocess_accepted_flips": result.common_preprocess_accepted_flips,
            "common_lift": result.common_lift,
            "native_lift": result.native_lift,
            "flip_lift": result.flip_lift,
            "native_best_updates": result.native_best_updates,
            "flip_best_updates": result.flip_best_updates,
            "common_best_updates": result.common_best_updates,
            "route_count_unique": result.route_count_unique,
            "liveness_verdict": result.liveness_verdict,
            "liveness_flags": "|".join(result.liveness_flags),
            "true_repair_mode": true_repair_mode,
            "common_flip_preprocess": bool(common_flip_preprocess),
            "checkpoint_path": rel(checkpoint) if checkpoint.exists() else "",
            "history_json": json.dumps(payload.get("history", []), ensure_ascii=False, sort_keys=True),
            "operator_counts_json": json.dumps(payload.get("operator_counts", {}), ensure_ascii=False, sort_keys=True),
            "solution_json": json.dumps(payload.get("solution"), ensure_ascii=False, sort_keys=True),
        }
        return row
    except Exception as exc:
        return failure_row(run_id, phase, algorithm, seed, eval_budget, runtime_cap_seconds, started, repr(exc))


def run_alns_row(*, run_id: str, phase: str, seed: int, eval_budget: int, runtime_cap_seconds: float) -> dict[str, Any]:
    prices = make_probe_prices()
    bundle = load_search_bundle(THREESHIFT_BUNDLE)
    preprocess = common_preprocess_solution(bundle, prices)
    checkpoint = OUTPUT_DIR / "checkpoints" / f"{run_id}.json"
    started = time.perf_counter()
    old_checkpoint = os.environ.get("SETP_E2_ALNS_CHECKPOINT_PATH")
    os.environ["SETP_E2_ALNS_CHECKPOINT_PATH"] = str(checkpoint)
    try:
        result = run_e2_alns_throughput(
            THREESHIFT_BUNDLE,
            config=WinnerKernelConfig(seed=int(seed), eval_budget=int(eval_budget), max_runtime_seconds=float(runtime_cap_seconds)),
            initial_solution=preprocess["solution"],
            prices=prices,
        )
    except Exception as exc:
        if old_checkpoint is None:
            os.environ.pop("SETP_E2_ALNS_CHECKPOINT_PATH", None)
        else:
            os.environ["SETP_E2_ALNS_CHECKPOINT_PATH"] = old_checkpoint
        return failure_row(run_id, phase, "ALNS", seed, eval_budget, runtime_cap_seconds, started, repr(exc))
    if old_checkpoint is None:
        os.environ.pop("SETP_E2_ALNS_CHECKPOINT_PATH", None)
    else:
        os.environ["SETP_E2_ALNS_CHECKPOINT_PATH"] = old_checkpoint
    solution = result["best_solution"]
    status = "OK"
    reason = ""
    if not result.get("feasible") or int(result.get("violation_count", 0)) != 0:
        status = "HALT_INFEASIBLE"
        reason = "ALNS returned infeasible best solution."
    elif int(result.get("evaluations", 0)) < int(eval_budget):
        status = "HALT_RUNTIME_UNDER_EVAL" if float(result.get("elapsed_seconds", 0.0)) >= float(runtime_cap_seconds) else "HALT_UNDER_EVAL"
        reason = f"Stopped at {result.get('evaluations')}/{eval_budget} complete evaluations."
    history = normalize_alns_history(result.get("history", []), preprocess)
    return {
        "run_id": run_id,
        "phase": phase,
        "algorithm": "ALNS",
        "seed": int(seed),
        "status": status,
        "gate_status": "OK" if status == "OK" else status,
        "failure_reason": reason,
        "eval_budget": int(eval_budget),
        "actual_evals": int(result.get("evaluations", 0)),
        "max_runtime_seconds": float(runtime_cap_seconds),
        "elapsed_seconds": float(result.get("elapsed_seconds", 0.0)),
        "candidate_per_second": safe_ratio(result.get("evaluations", 0), result.get("elapsed_seconds", 0.0)),
        "best_cost": float(result["best_cost"]),
        "best_signature": solution_signature_hash(solution),
        "feasible": bool(result.get("feasible")),
        "violation_count": int(result.get("violation_count", 0)),
        "route_count": len(solution.routes),
        "cv_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"),
        "ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
        "charging_action_count": len(solution.charging_actions),
        "common_preprocess_cost": preprocess["cost"],
        "common_preprocess_attempts": preprocess["attempts"],
        "common_preprocess_accepted_flips": preprocess["accepted_flips"],
        "common_lift": preprocess["common_lift"],
        "native_lift": max(0.0, float(preprocess["cost"]) - float(result["best_cost"])),
        "flip_lift": 0.0,
        "native_best_updates": len([item for item in history if str(item.get("channel", "")).startswith("native_")]),
        "flip_best_updates": 0,
        "common_best_updates": 1 if preprocess["common_lift"] > 1e-9 else 0,
        "route_count_unique": "",
        "liveness_verdict": "NOT_BASELINE_ALNS_REFERENCE",
        "liveness_flags": "",
        "true_repair_mode": "alns_e2_throughput",
        "common_flip_preprocess": True,
        "checkpoint_path": rel(checkpoint) if checkpoint.exists() else "",
        "history_json": json.dumps(history, ensure_ascii=False, sort_keys=True),
        "operator_counts_json": json.dumps(result.get("operator_counts", {}), ensure_ascii=False, sort_keys=True),
        "solution_json": json.dumps(solution_to_dict(solution), ensure_ascii=False, sort_keys=True),
    }


def common_preprocess_solution(bundle: Any, prices: Any) -> dict[str, Any]:
    warm = make_shared_initial_solution(bundle, prices=prices)
    session = mb._SearchSession("LNS", bundle, 1, 1, 600.0, warm, prices=prices, common_flip_preprocess=True)
    cost = session.best.cost
    return {
        "solution": session.best.solution,
        "cost": float(cost),
        "attempts": int(session.common_preprocess_attempts),
        "accepted_flips": int(session.common_preprocess_accepted_flips),
        "common_lift": max(0.0, float(session.shared_seed_cost) - float(cost)),
        "history": list(session.history),
    }


def normalize_alns_history(history: list[dict[str, Any]], preprocess: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(preprocess.get("history", []))
    for item in history[1:]:
        row = dict(item)
        row["channel"] = f"native_{row.get('operator', '')}"
        rows.append(row)
    return rows


@contextmanager
def true_repair_context(mode: str) -> Iterator[None]:
    if mode == "true_repair_cost_aware_1":
        old_env = os.environ.get("SETP_ALNS_CRUSH_TRUE_REPAIR")
        original_flags = mb._baseline_fast_repair_flags
        os.environ["SETP_ALNS_CRUSH_TRUE_REPAIR"] = "1"
        mb._baseline_fast_repair_flags = lambda: nullcontext()
        try:
            yield
        finally:
            mb._baseline_fast_repair_flags = original_flags
            if old_env is None:
                os.environ.pop("SETP_ALNS_CRUSH_TRUE_REPAIR", None)
            else:
                os.environ["SETP_ALNS_CRUSH_TRUE_REPAIR"] = old_env
    else:
        yield


@contextmanager
def temporary_checkpoint(path: Path) -> Iterator[None]:
    old_value = os.environ.get("SETP_E2_ALNS_CHECKPOINT_PATH")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["SETP_E2_ALNS_CHECKPOINT_PATH"] = str(path)
    try:
        yield
    finally:
        if old_value is None:
            os.environ.pop("SETP_E2_ALNS_CHECKPOINT_PATH", None)
        else:
            os.environ["SETP_E2_ALNS_CHECKPOINT_PATH"] = old_value


def decide_true_repair_alignment(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [row for row in rows if row.get("gate_status") != "OK" or int(as_float(row.get("actual_evals"))) < int(as_float(row.get("eval_budget")))]
    grouped = {(row["algorithm"], row["true_repair_mode"]): row for row in rows}
    comparisons: dict[str, Any] = {}
    alignment_supported = True
    throughput_ok = True
    for algorithm in ("LNS", "GA"):
        zero = grouped.get((algorithm, "true_repair_forced_0"), {})
        one = grouped.get((algorithm, "true_repair_cost_aware_1"), {})
        est_seconds = safe_ratio(16000, safe_ratio(one.get("actual_evals"), one.get("elapsed_seconds")))
        comparisons[algorithm] = {
            "native_updates_0": int(as_float(zero.get("native_best_updates"))),
            "native_updates_1": int(as_float(one.get("native_best_updates"))),
            "best_cost_0": as_float(zero.get("best_cost")),
            "best_cost_1": as_float(one.get("best_cost")),
            "estimated_16000_seconds_true_repair_1": est_seconds,
        }
        if int(as_float(one.get("native_best_updates"))) < int(as_float(zero.get("native_best_updates"))):
            alignment_supported = False
        if as_float(one.get("best_cost")) > as_float(zero.get("best_cost")) + 1e-9 and int(as_float(one.get("native_best_updates"))) == 0:
            alignment_supported = False
        if est_seconds > 2700.0:
            throughput_ok = False
    verdict = "TRUE_REPAIR_ALIGNMENT_RECOMMENDED" if not failures and alignment_supported and throughput_ok else "TRUE_REPAIR_ALIGNMENT_REJECTED"
    return {
        "schema": "setp-e2-g0-true-repair-decision.v1",
        "verdict": verdict if not failures else "HALT_COLLECTION_COST",
        "comparisons": comparisons,
        "failure_count": len(failures),
        "failure_sample": failures[:10],
        "alignment_supported": alignment_supported,
        "throughput_ok": throughput_ok,
    }


def liveness_verdicts(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    baseline_rows = [row for row in raw_rows if row.get("algorithm") in BASELINES]
    for row in baseline_rows:
        rows.append(
            {
                "scope": "run",
                "algorithm": row.get("algorithm"),
                "seed": row.get("seed"),
                "run_id": row.get("run_id"),
                "verdict": row.get("liveness_verdict"),
                "flags": row.get("liveness_flags"),
                "native_best_updates": row.get("native_best_updates"),
                "route_count_unique": row.get("route_count_unique"),
            }
        )
    for algorithm in BASELINES:
        group = [row for row in baseline_rows if row.get("algorithm") == algorithm]
        if not group:
            continue
        costs = {str(row.get("best_cost")) for row in group}
        signatures = {str(row.get("best_signature")) for row in group}
        suspect = len(group) > 1 and len(costs) == 1 and len(signatures) == 1
        rows.append(
            {
                "scope": "algorithm_seed_group",
                "algorithm": algorithm,
                "seed": "|".join(str(row.get("seed")) for row in sorted(group, key=lambda item: int(item.get("seed", 0)))),
                "run_id": "",
                "verdict": "SEED_INVARIANCE_SUSPECT" if suspect else "SEED_VARIATION_OK",
                "flags": "exact_cost_and_signature_repeated_across_seeds" if suspect else "",
                "native_best_updates": sum(int(as_float(row.get("native_best_updates"))) for row in group),
                "route_count_unique": "|".join(str(row.get("route_count_unique")) for row in group),
            }
        )
    signature_to_algorithms: dict[str, set[str]] = {}
    for row in baseline_rows:
        signature_to_algorithms.setdefault(str(row.get("best_signature")), set()).add(str(row.get("algorithm")))
    for signature, algorithms in sorted(signature_to_algorithms.items()):
        if len(algorithms) > 1:
            rows.append(
                {
                    "scope": "cross_algorithm",
                    "algorithm": "|".join(sorted(algorithms)),
                    "seed": "",
                    "run_id": "",
                    "verdict": "CROSS_ALGO_IDENTITY_SUSPECT",
                    "flags": f"shared_signature={signature}",
                    "native_best_updates": "",
                    "route_count_unique": "",
                }
            )
    return rows


def decide(output_dir: Path) -> dict[str, Any]:
    preflight_payload = read_json(output_dir / "preflight.json") if (output_dir / "preflight.json").exists() else {}
    raw_rows = read_csv(output_dir / "raw_runs.csv")
    liveness_rows = read_csv(output_dir / "liveness_verdicts.csv")
    true_repair = read_json(output_dir / "true_repair_decision.json") if (output_dir / "true_repair_decision.json").exists() else {}
    scenario = read_json(output_dir / "scenario_compliance.json") if (output_dir / "scenario_compliance.json").exists() else {}
    failures: list[dict[str, Any]] = []
    if not preflight_payload.get("env_ok"):
        failures.append({"failure_bucket": "environment_mismatch", "preflight": preflight_payload})
    if preflight_payload.get("protected_diff"):
        failures.append({"failure_bucket": "protected_file_diff", "paths": preflight_payload.get("protected_diff")})
    expected = len(BASELINES) * 3 + 3
    if len(raw_rows) < expected:
        failures.append({"failure_bucket": "g0_missing_rows", "actual": len(raw_rows), "expected": expected})
    for row in raw_rows:
        if row.get("gate_status") != "OK":
            failures.append({"failure_bucket": "run_not_ok", "run_id": row.get("run_id"), "status": row.get("gate_status"), "reason": row.get("failure_reason")})
        if row.get("algorithm") in BASELINES and int(as_float(row.get("actual_evals"))) < int(as_float(row.get("eval_budget"))):
            failures.append({"failure_bucket": "baseline_under_eval", "run_id": row.get("run_id"), "actual": row.get("actual_evals"), "expected": row.get("eval_budget")})
    suspect_rows = [row for row in liveness_rows if str(row.get("verdict", "")).endswith("_SUSPECT") or row.get("verdict") == "BASELINE_LIVENESS_FAIL"]
    scenario_blocked = scenario.get("verdict") == "SCENARIO_COMPLIANCE_BLOCKED"
    if failures:
        verdict = "G0_COLLECTION_INCOMPLETE"
    elif suspect_rows:
        verdict = "G0_RESIDUAL_HOMOGENIZATION"
    else:
        verdict = "G0_PASS_BASELINES_HEALTHY"
    return {
        "schema": "setp-e2-g0-reaudit-decision.v1",
        "verdict": verdict,
        "head": git_head(),
        "failure_count": len(failures),
        "failure_sample": failures[:20],
        "suspect_count": len(suspect_rows),
        "suspect_sample": suspect_rows[:20],
        "true_repair_decision": true_repair.get("verdict", "MISSING"),
        "scenario_compliance": scenario.get("verdict", "MISSING"),
        "scenario_compliance_blocked": scenario_blocked,
        "not_formal_t3": True,
        "algorithm_win_loss_claim": False,
        "g4_g5_unfrozen": False,
    }


def scenario_compliance_audit() -> dict[str, Any]:
    override_hits = rg_hits(r"B_battery_kwh\s*=\s*280|BATTERY_KWH\s*=\s*280|280kWh|280\.0")
    formal_suspects = [
        hit for hit in override_hits
        if "diagnostic" not in hit.lower()
        and "probe" not in hit.lower()
        and "autopsy" not in hit.lower()
        and "validation" not in hit.lower()
        and "reaudit" not in hit.lower()
        and "handoff" not in hit.lower()
    ]
    prices_text = (REPO_ROOT / "solver/src/setp_solver/prices.py").read_text(encoding="utf-8")
    default_ok = "B_battery_kwh: float = 80.0" in prices_text and "Q_capacity: float = 3650.0" in prices_text
    verdict = "SCENARIO_COMPLIANCE_OK" if default_ok and not formal_suspects else "SCENARIO_COMPLIANCE_BLOCKED"
    return {
        "schema": "setp-e2-g0-scenario-compliance.v1",
        "verdict": verdict,
        "default_prices_ok": default_ok,
        "override_hit_count": len(override_hits),
        "formal_suspect_count": len(formal_suspects),
        "formal_suspect_sample": formal_suspects[:50],
        "note": "This audit does not edit TeX or model formulas.",
    }


def legacy_anchor_archaeology() -> dict[str, Any]:
    started = time.perf_counter()
    worktree_root = Path(tempfile.mkdtemp(prefix="resetp_legacy_anchor_"))
    worktree = worktree_root / "df608660"
    try:
        add = subprocess.run(["git", "worktree", "add", "--detach", str(worktree), "df608660"], cwd=REPO_ROOT, check=False, text=True, capture_output=True, timeout=300)
        if add.returncode != 0:
            return {"schema": "setp-e2-g0-legacy-anchor.v1", "status": "LEGACY_ANCHOR_STILL_UNEXPLAINED", "failure_reason": add.stderr.strip(), "elapsed_seconds": time.perf_counter() - started}
        code = legacy_anchor_code(worktree)
        proc = subprocess.run(
            [GOLD_PYTHON, "-c", code],
            cwd=worktree,
            check=False,
            text=True,
            capture_output=True,
            timeout=3600,
            env={**os.environ, "PYTHONPATH": "solver/src:models/src:.", "PYTHONHASHSEED": "0"},
        )
        if proc.returncode != 0:
            return {"schema": "setp-e2-g0-legacy-anchor.v1", "status": "LEGACY_ANCHOR_STILL_UNEXPLAINED", "failure_reason": proc.stderr[-2000:], "stdout": proc.stdout[-2000:], "elapsed_seconds": time.perf_counter() - started}
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        cost = float(payload.get("best_cost", math.nan))
        status = "LEGACY_ANCHOR_REPRODUCED" if abs(cost - 4878.331796187524) <= 1e-9 else "LEGACY_ANCHOR_STILL_UNEXPLAINED"
        payload.update({"schema": "setp-e2-g0-legacy-anchor.v1", "status": status, "target": 4878.331796187524, "elapsed_seconds": time.perf_counter() - started})
        return payload
    except subprocess.TimeoutExpired as exc:
        return {"schema": "setp-e2-g0-legacy-anchor.v1", "status": "LEGACY_ANCHOR_STILL_UNEXPLAINED", "failure_reason": f"timeout: {exc}", "elapsed_seconds": time.perf_counter() - started}
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=REPO_ROOT, check=False, text=True, capture_output=True)
        shutil.rmtree(worktree_root, ignore_errors=True)


def legacy_anchor_code(worktree: Path) -> str:
    return f"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path({str(worktree)!r}) / 'solver/src'))
sys.path.insert(0, str(Path({str(worktree)!r}) / 'models/src'))
from setp_solver.search.winner_operators import WinnerKernelConfig, run_winner_kernel
bundle = Path({str(worktree)!r}) / 'models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113'
result = run_winner_kernel(bundle, config=WinnerKernelConfig(seed=2, eval_budget=16000, max_runtime_seconds=900.0))
print(json.dumps({{'best_cost': float(result['best_cost']), 'feasible': bool(result['feasible']), 'violation_count': int(result['violation_count']), 'evaluations': int(result['evaluations'])}}, sort_keys=True))
"""


def history_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        history = json.loads(row.get("history_json") or "[]")
    except json.JSONDecodeError:
        history = []
    for idx, item in enumerate(history):
        rows.append(
            {
                "run_id": row.get("run_id"),
                "phase": row.get("phase"),
                "algorithm": row.get("algorithm"),
                "seed": row.get("seed"),
                "step": idx,
                "eval": item.get("eval", ""),
                "operator": item.get("operator", ""),
                "channel": item.get("channel", ""),
                "best_cost": item.get("best_cost", ""),
                "best_cost_before": item.get("best_cost_before", ""),
                "route_count": item.get("route_count", ""),
                "signature": item.get("signature", ""),
                "time_seconds": item.get("time_seconds", ""),
            }
        )
    return rows


def channel_lift_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": row.get("run_id"),
        "phase": row.get("phase"),
        "algorithm": row.get("algorithm"),
        "seed": row.get("seed"),
        "best_cost": row.get("best_cost"),
        "common_lift": row.get("common_lift"),
        "native_lift": row.get("native_lift"),
        "flip_lift": row.get("flip_lift"),
        "native_best_updates": row.get("native_best_updates"),
        "flip_best_updates": row.get("flip_best_updates"),
        "common_best_updates": row.get("common_best_updates"),
    }


def failure_row(run_id: str, phase: str, algorithm: str, seed: int, eval_budget: int, runtime_cap_seconds: float, started: float, reason: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "phase": phase,
        "algorithm": algorithm,
        "seed": int(seed),
        "status": "HALT_WORKER_EXCEPTION",
        "gate_status": "HALT_WORKER_EXCEPTION",
        "failure_reason": reason,
        "eval_budget": int(eval_budget),
        "actual_evals": 0,
        "max_runtime_seconds": float(runtime_cap_seconds),
        "elapsed_seconds": time.perf_counter() - started,
        "candidate_per_second": 0.0,
    }


def render_report(output_dir: Path, decision: dict[str, Any]) -> str:
    true_repair = read_json(output_dir / "true_repair_decision.json") if (output_dir / "true_repair_decision.json").exists() else {}
    scenario = read_json(output_dir / "scenario_compliance.json") if (output_dir / "scenario_compliance.json").exists() else {}
    legacy = read_json(output_dir / "legacy_anchor.json") if (output_dir / "legacy_anchor.json").exists() else {}
    raw_rows = read_csv(output_dir / "raw_runs.csv")
    lines = [
        "# E2-G0 Closure Reaudit",
        "",
        "本任务目标：把 E2-G0 从同质化假象整改到可重审状态，输出 baseline health / G0 gate 证据。它不是正式 T3，不写算法胜负。",
        "",
        f"Verdict: `{decision.get('verdict')}`",
        "",
        f"- HEAD: `{decision.get('head')}`",
        f"- G0 rows: `{len(raw_rows)}`",
        f"- TRUE_REPAIR decision: `{true_repair.get('verdict', 'MISSING')}`",
        f"- Scenario compliance: `{scenario.get('verdict', 'MISSING')}`",
        f"- Legacy anchor: `{legacy.get('status', 'MISSING')}`",
        f"- Suspect count: `{decision.get('suspect_count')}`",
        f"- Failure count: `{decision.get('failure_count')}`",
        "",
        "## Plain Reading",
        "",
        plain_decision(decision),
        "",
        "## Artifacts",
        "",
        "- `metadata.json`, `preflight.json`, `true_repair_ab.csv`, `raw_runs.csv`, `best_trajectory.csv`, `channel_lift.csv`, `liveness_verdicts.csv`",
        "- `true_repair_decision.json`, `scenario_compliance.json`, `legacy_anchor.json`, `decision.json`, `artifact_hashes.json`",
        "",
    ]
    if decision.get("suspect_sample"):
        lines.extend(["## Suspect Sample", "", "```json", json.dumps(decision["suspect_sample"], ensure_ascii=False, indent=2), "```", ""])
    if decision.get("failure_sample"):
        lines.extend(["## Failure Sample", "", "```json", json.dumps(decision["failure_sample"], ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def plain_decision(decision: dict[str, Any]) -> str:
    verdict = decision.get("verdict")
    if verdict == "G0_PASS_BASELINES_HEALTHY":
        return "四个 baseline 的 liveness 门禁通过，未触发 seed/cross-algorithm 同质化嫌疑；这里只说明 G0 健康门通过，不构成正式 T3 胜负主张。"
    if verdict == "G0_RESIDUAL_HOMOGENIZATION":
        return "采集闭合，但仍触发 liveness 或同质化嫌疑；按预注册停下，不扩跑 G4/G5。"
    return "采集、环境、under-eval 或 protected-file 门未闭合；按 G0_COLLECTION_INCOMPLETE 收口。"


def rg_hits(pattern: str) -> list[str]:
    proc = subprocess.run(["rg", "-n", pattern, "solver", "baselines", "docs", "-g", "*.py", "-g", "*.md", "-g", "*.tex"], cwd=REPO_ROOT, check=False, text=True, capture_output=True)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def protected_diff() -> list[str]:
    cmd = [
        "git",
        "diff",
        "--name-only",
        "HEAD",
        "--",
        "solver/src/setp_solver/cost.py",
        "solver/src/setp_solver/check.py",
        "solver/src/setp_solver/search/evaluation.py",
        "solver/src/setp_solver/prices.py",
        "docs/paper_submission_final/paper_main.tex",
        "solver/src/setp_solver/search/feasible_repair.py",
        "solver/src/setp_solver/search/resetp_alns",
        "solver/src/setp_solver/search/alns_wouda.py",
        "solver/src/setp_solver/search/winner_operators.py",
        "solver/src/setp_solver/search/carbon_operators.py",
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False, text=True, capture_output=True)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def artifact_hashes(root: Path) -> dict[str, Any]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if path.name.startswith("._") or path.name in HASH_EXCLUDE_NAMES or any(part in HASH_EXCLUDE_PARTS for part in rel_parts):
            continue
        files[str(path.relative_to(root))] = sha256_file(path)
    return {
        "schema": "setp-artifact-hashes.v1",
        "root": rel(root),
        "generated_at_epoch": time.time(),
        "exclude": sorted([*HASH_EXCLUDE_NAMES, *HASH_EXCLUDE_PARTS, "._*"]),
        "files": files,
    }


def clean_artifact_dir(output_dir: Path) -> None:
    for path in sorted(output_dir.rglob("._*")):
        if path.is_file():
            path.unlink(missing_ok=True)
    for cache_name in HASH_EXCLUDE_PARTS:
        for path in sorted(output_dir.rglob(cache_name)):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)


def parse_seeds(text: str) -> list[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (str(row.get("phase", "")), str(row.get("algorithm", "")), int(as_float(row.get("seed"), 0.0)), str(row.get("run_id", ""))))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_payload(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def git_head() -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, text=True, capture_output=True)
    return proc.stdout.strip()


def numpy_version() -> str:
    import numpy as np

    return str(np.__version__)


def repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def safe_ratio(num: Any, denom: Any) -> float:
    denominator = as_float(denom)
    if abs(denominator) <= 1e-12:
        return 0.0
    return as_float(num) / denominator


def as_float(value: Any, default: float = math.nan) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    raise SystemExit(main())
