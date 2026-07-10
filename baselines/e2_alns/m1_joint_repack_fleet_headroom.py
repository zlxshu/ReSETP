"""Current-v3 headroom test for route repacking followed by fleet closure.

This is a diagnostic, not a promoted ALNS operator.  It first obtains matched
400-evaluation route sets from ALNS, LNS, and SA.  It then compares route
repacking alone, fleet-type closure alone, and their sequential combination
under the unchanged checker and evaluator.
"""

from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
for _path in (REPO_ROOT, SOLVER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setp_solver.algorithms.resetp_alns.kernel.winner import (
    TRACE_DIAGNOSTIC_FLAG,
    WinnerKernelConfig,
    _run_winner_kernel_loop,
    e2_alns_throughput_flags,
)
from setp_solver.algorithms.resetp_alns.support.construction import build_initial_solution
from setp_solver.algorithms.resetp_alns.support.fleet import infer_fleet_limits
from setp_solver.algorithms.resetp_alns.support.fleet_charge_corepair import propose_fleet_charge_corepair
from setp_solver.algorithms.resetp_alns.support.global_order_repack import order_perturbations
from setp_solver.algorithms.resetp_alns.support.order_decoder import (
    OrderDecodeContext,
    order_to_solution,
    route_type_hints,
    solution_order,
)
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import CandidateState, _algorithm_seed, _run_sa_path
from setp_solver.search.evaluation import EvalBudget, EvaluationContext, model_cost, score_reference
from setp_solver.search.instance_registry import assert_formal_benchmark_ready, instance_abs_dir
from setp_solver.search.metaheuristic_baselines import (
    run_metaheuristic_baseline,
    solution_from_dict,
    solution_to_dict,
)
from setp_solver.solution import Solution


DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/m1_joint_repack_fleet_headroom_20260710")
DEFAULT_CALIBRATION_DIR = Path("baselines/e2_alns/m1_fleet_opportunity_20260710")
DEFAULT_INSTANCES = (
    ("small", "L-main-threeshift-20c-01"),
    ("medium", "L-main-threeshift-50c-01"),
    ("large", "L-main-threeshift-100c-01"),
)
ALGORITHMS = ("ALNS_T3", "LNS", "SA")


@dataclass(frozen=True)
class FleetClosureOutcome:
    solution: Solution
    cost: float
    attempts: int
    accepted_flips: int
    trace_rows: list[dict[str, Any]]


@dataclass(frozen=True)
class RepackCandidate:
    label: str
    solution: Solution


def classify_headroom(rows: Iterable[dict[str, Any]]) -> str:
    items = list(rows)
    positive = [row for row in items if float(row.get("joint_beyond_separate", 0.0)) > 1e-9]
    if not positive:
        return "JOINT_REPACK_FLEET_HEADROOM_NOT_FOUND"
    scales = {str(row.get("scale")) for row in items}
    positive_scales = {str(row.get("scale")) for row in positive}
    positive_algorithms = {str(row.get("algorithm")) for row in positive}
    required = {"small", "medium", "large"}
    clean = bool(items) and all(bool(row.get("clean")) for row in items)
    broad = len(positive) >= math.ceil(0.60 * len(items))
    if clean and required.issubset(scales) and required.issubset(positive_scales) and len(positive_algorithms) >= 2 and broad:
        return "JOINT_REPACK_FLEET_HEADROOM_STRONG"
    return "JOINT_REPACK_FLEET_HEADROOM_PARTIAL"


def greedy_fleet_closure(
    solution: Solution,
    context: EvaluationContext,
    *,
    max_accepted_flips: int = 64,
) -> FleetClosureOutcome:
    current = solution
    current_cost = _feasible_cost(current, context)
    attempts = 0
    trace_rows: list[dict[str, Any]] = []
    if not math.isfinite(current_cost):
        return FleetClosureOutcome(current, current_cost, attempts, 0, trace_rows)
    while len(trace_rows) < max_accepted_flips:
        outcome = propose_fleet_charge_corepair(current, context, max_attempts=len(current.routes))
        attempts += int(outcome.attempts)
        if outcome.solution is None or not outcome.best_improved:
            break
        next_cost = _feasible_cost(outcome.solution, context)
        if not math.isfinite(next_cost) or next_cost >= current_cost - 1e-9:
            break
        trace_rows.append(
            {
                "flip": len(trace_rows) + 1,
                "route_index": int(outcome.route_index),
                "source_route_type": outcome.source_route_type,
                "target_route_type": outcome.target_route_type,
                "before_cost": current_cost,
                "after_cost": next_cost,
            }
        )
        current = outcome.solution
        current_cost = next_cost
    return FleetClosureOutcome(current, current_cost, attempts, len(trace_rows), trace_rows)


def repack_candidates(
    source: Solution,
    context: EvaluationContext,
    rng: random.Random,
    *,
    trials: int = 4,
) -> list[RepackCandidate]:
    decode_context = OrderDecodeContext(context.instance, context.prices, context.carbon_profile, rng)
    order = solution_order(source, context.instance)
    hints = route_type_hints(source, context.instance)
    rows: list[RepackCandidate] = []
    for trial in range(max(1, int(trials))):
        for perturbation in order_perturbations(order, context.instance, rng):
            candidate = order_to_solution(
                perturbation.order,
                decode_context,
                current_solution=source,
                type_hints=hints,
            )
            rows.append(RepackCandidate(f"trial{trial + 1}:{perturbation.label}", candidate))
    return rows


def evidence_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if path.name.startswith("._") or path.name == "artifact_hashes.json":
            continue
        if ".tasks" in relative.parts or "__pycache__" in relative.parts or ".pytest_cache" in relative.parts:
            continue
        if path.suffix == ".pyc":
            continue
        files.append(path)
    return sorted(files)


def _feasible_cost(solution: Solution, context: EvaluationContext) -> float:
    if check_solution(solution, context.instance, context.prices):
        return math.inf
    return float(model_cost(solution, context))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_value(repo_root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo_root, check=True, capture_output=True, text=True).stdout.strip()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_solution(path: Path) -> Solution:
    return solution_from_dict(json.loads(path.read_text(encoding="utf-8")))


def _save_solution(path: Path, solution: Solution) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(solution_to_dict(solution), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _cv_start(bundle: Any, prices: Any) -> Solution:
    return build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        prices,
        fleet_limits=infer_fleet_limits(bundle.bundle_dir),
        introduce_ev=False,
        require_charging_signal=False,
    )


def _run_alns(bundle: Any, prices: Any, start: Solution, seed: int, eval_budget: int, runtime: float) -> tuple[Solution, int, str]:
    flags = e2_alns_throughput_flags()
    flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"] = "1"
    flags[TRACE_DIAGNOSTIC_FLAG] = "0"
    run = _run_winner_kernel_loop(
        copy.deepcopy(start),
        bundle.instance,
        bundle.carbon_profile,
        config=WinnerKernelConfig(seed=seed, eval_budget=eval_budget, max_runtime_seconds=runtime),
        prices=prices,
        variant_flags=flags,
    )
    status = "OK" if run.evaluations >= eval_budget and not check_solution(run.best_solution, bundle.instance, prices) else "HALT_UNDER_EVAL"
    return run.best_solution, int(run.evaluations), status


def _run_lns(bundle: Any, prices: Any, start: Solution, seed: int, eval_budget: int, runtime: float) -> tuple[Solution, int, str]:
    run = run_metaheuristic_baseline(
        "LNS",
        bundle.bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=runtime,
        initial_solution=copy.deepcopy(start),
        prices=prices,
        common_flip_preprocess=False,
    )
    if run.best_solution is None:
        raise RuntimeError(f"LNS failed to return a solution: {run.failure_reason}")
    return run.best_solution, int(run.evals), str(run.status)


def _run_sa(bundle: Any, prices: Any, start: Solution, seed: int, eval_budget: int, runtime: float) -> tuple[Solution, int, str]:
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=EvalBudget(limit=eval_budget, target=eval_budget),
    )
    warm = copy.deepcopy(start)
    state = CandidateState(warm, context)
    initial_obj = score_reference(warm, context)
    initial_cost = model_cost(warm, context)
    best, _best_obj, _best_cost, _current, _current_obj = _run_sa_path(
        state,
        random.Random(_algorithm_seed("scikit-opt-SA", seed)),
        warm,
        initial_obj,
        initial_cost,
        warm,
        initial_obj,
        eval_budget=eval_budget,
        max_runtime_seconds=runtime,
        started=time.perf_counter(),
    )
    actual = int(context.budget.count if context.budget else 0)
    status = "OK" if actual >= eval_budget and not check_solution(best, bundle.instance, prices) else "HALT_UNDER_EVAL"
    return best, actual, status


def _source_fingerprint(repo_root: Path, args: argparse.Namespace) -> str:
    manifest = repo_root / "models/data_bundle/generated_instances/L-main/resetp-l-main-main-benchmark.v3.json"
    payload = {
        "script": _sha256(Path(__file__).resolve()),
        "manifest": _sha256(manifest),
        "winner": _sha256(repo_root / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py"),
        "baseline": _sha256(repo_root / "solver/src/setp_solver/search/metaheuristic_baselines.py"),
        "candidates": _sha256(repo_root / "solver/src/setp_solver/search/candidates.py"),
        "battery_kwh": float(args.battery_kwh),
        "eval_budget": int(args.eval_budget),
        "repack_trials": int(args.repack_trials),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _obtain_source(
    repo_root: Path,
    output_dir: Path,
    scale: str,
    instance_name: str,
    algorithm: str,
    seed: int,
    args: argparse.Namespace,
    fingerprint: str,
) -> tuple[dict[str, Any], Solution, Any, Any]:
    run_id = f"{scale}__{instance_name}__{algorithm}__seed{seed}"
    task_path = output_dir / ".tasks" / f"{run_id}.json"
    solution_path = output_dir / "sources" / f"{run_id}.json"
    bundle = load_search_bundle(instance_abs_dir(repo_root, instance_name))
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(args.battery_kwh))
    if task_path.exists() and solution_path.exists() and not args.force:
        task = json.loads(task_path.read_text(encoding="utf-8"))
        if task.get("fingerprint") == fingerprint:
            return dict(task["row"]), _load_solution(solution_path), bundle, prices

    start = _cv_start(bundle, prices)
    initial_context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
    initial_cost = _feasible_cost(start, initial_context)
    started = time.perf_counter()
    runner = {"ALNS_T3": _run_alns, "LNS": _run_lns, "SA": _run_sa}[algorithm]
    solution, actual_evals, status = runner(bundle, prices, start, seed, int(args.eval_budget), float(args.max_runtime_seconds))
    context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
    source_cost = _feasible_cost(solution, context)
    violations = check_solution(solution, bundle.instance, prices)
    row = {
        "run_id": run_id,
        "scale": scale,
        "instance": instance_name,
        "actual_customer_count": sum(node.node_type.lower() == "c" for node in bundle.instance.nodes),
        "algorithm": algorithm,
        "seed": seed,
        "eval_budget": int(args.eval_budget),
        "actual_evaluations": int(actual_evals),
        "status": status,
        "elapsed_seconds": time.perf_counter() - started,
        "initial_cost": initial_cost,
        "source_cost": source_cost,
        "source_routes": len(solution.routes),
        "source_ev_routes": sum(route.vehicle_type.lower() == "ev" for route in solution.routes),
        "violation_count": len(violations),
        "source_solution_path": str(solution_path.relative_to(repo_root)),
    }
    _save_solution(solution_path, solution)
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(json.dumps({"fingerprint": fingerprint, "row": row}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return row, solution, bundle, prices


def _measure_source(
    source_row: dict[str, Any],
    source: Solution,
    bundle: Any,
    prices: Any,
    *,
    repack_trials: int,
    output_dir: Path,
    repo_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], Solution]:
    context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
    source_cost = _feasible_cost(source, context)
    fleet_only = greedy_fleet_closure(source, context)
    candidates = repack_candidates(
        source,
        context,
        random.Random(_algorithm_seed("joint-repack-fleet", int(source_row["seed"]))),
        trials=repack_trials,
    )
    trace_rows: list[dict[str, Any]] = []
    best_repack_cost = source_cost
    best_joint_cost = fleet_only.cost
    best_joint_solution = fleet_only.solution
    best_joint_label = "fleet_only"
    for candidate in candidates:
        violations = check_solution(candidate.solution, bundle.instance, prices)
        repack_cost = _feasible_cost(candidate.solution, context)
        closure = greedy_fleet_closure(candidate.solution, context)
        trace_rows.append(
            {
                "run_id": source_row["run_id"],
                "scale": source_row["scale"],
                "instance": source_row["instance"],
                "algorithm": source_row["algorithm"],
                "seed": source_row["seed"],
                "candidate": candidate.label,
                "repack_feasible": not violations,
                "repack_cost": repack_cost if math.isfinite(repack_cost) else "N/A",
                "repack_routes": len(candidate.solution.routes),
                "repack_ev_routes": sum(route.vehicle_type.lower() == "ev" for route in candidate.solution.routes),
                "joint_cost": closure.cost if math.isfinite(closure.cost) else "N/A",
                "joint_routes": len(closure.solution.routes),
                "joint_ev_routes": sum(route.vehicle_type.lower() == "ev" for route in closure.solution.routes),
                "closure_attempts": closure.attempts,
                "closure_accepted_flips": closure.accepted_flips,
            }
        )
        if repack_cost < best_repack_cost - 1e-9:
            best_repack_cost = repack_cost
        if closure.cost < best_joint_cost - 1e-9:
            best_joint_cost = closure.cost
            best_joint_solution = closure.solution
            best_joint_label = candidate.label

    separate_best = min(source_cost, fleet_only.cost, best_repack_cost)
    joint_path = output_dir / "joint_solutions" / f"{source_row['run_id']}.json"
    _save_solution(joint_path, best_joint_solution)
    clean = (
        source_row["status"] == "OK"
        and int(source_row["actual_evaluations"]) >= int(source_row["eval_budget"])
        and int(source_row["violation_count"]) == 0
        and math.isfinite(best_joint_cost)
        and not check_solution(best_joint_solution, bundle.instance, prices)
    )
    result = {
        **source_row,
        "fleet_only_cost": fleet_only.cost,
        "fleet_only_gain": max(0.0, source_cost - fleet_only.cost),
        "fleet_only_accepted_flips": fleet_only.accepted_flips,
        "best_repack_cost": best_repack_cost,
        "repack_only_gain": max(0.0, source_cost - best_repack_cost),
        "best_joint_cost": best_joint_cost,
        "joint_total_gain": max(0.0, source_cost - best_joint_cost),
        "joint_beyond_separate": max(0.0, separate_best - best_joint_cost),
        "best_joint_label": best_joint_label,
        "best_joint_routes": len(best_joint_solution.routes),
        "best_joint_ev_routes": sum(route.vehicle_type.lower() == "ev" for route in best_joint_solution.routes),
        "repack_candidate_count": len(candidates),
        "clean": clean,
        "joint_solution_path": str(joint_path.relative_to(repo_root)),
    }
    return result, trace_rows, best_joint_solution


def _calibrate_closure(repo_root: Path, calibration_dir: Path, battery_kwh: float) -> list[dict[str, Any]]:
    summaries = _read_csv(calibration_dir / "summary.csv")
    rows: list[dict[str, Any]] = []
    for summary in summaries:
        if abs(float(summary["battery_kwh"]) - float(battery_kwh)) > 1e-9:
            continue
        source_path = repo_root / summary["source_solution_path"]
        source = _load_solution(source_path)
        instance_name = "L-main-threeshift-25c-01"
        bundle = load_search_bundle(instance_abs_dir(repo_root, instance_name))
        prices = replace(DEFAULT_PRICES, B_battery_kwh=float(battery_kwh))
        context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
        closure = greedy_fleet_closure(source, context)
        exact_cost = float(summary["best_cost"])
        rows.append(
            {
                "source_profile": summary["source_profile"],
                "source_start": summary["source_start"],
                "source_seed": int(summary["source_seed"]),
                "route_count": int(summary["route_count"]),
                "exact_cost": exact_cost,
                "greedy_cost": closure.cost,
                "gap": closure.cost - exact_cost,
                "matched": abs(closure.cost - exact_cost) <= 1e-6,
            }
        )
    return rows


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    assert_formal_benchmark_ready(repo_root)
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = _source_fingerprint(repo_root, args)
    seeds = [int(value) for value in str(args.seeds).split(",") if value.strip()]
    instances = list(DEFAULT_INSTANCES)

    source_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []
    for scale, instance_name in instances:
        for seed in seeds:
            for algorithm in ALGORITHMS:
                source_row, source, bundle, prices = _obtain_source(
                    repo_root,
                    output_dir,
                    scale,
                    instance_name,
                    algorithm,
                    seed,
                    args,
                    fingerprint,
                )
                source_rows.append(source_row)
                result, traces, _solution = _measure_source(
                    source_row,
                    source,
                    bundle,
                    prices,
                    repack_trials=int(args.repack_trials),
                    output_dir=output_dir,
                    repo_root=repo_root,
                )
                result_rows.append(result)
                trace_rows.extend(traces)
                _write_csv(output_dir / "source_runs.csv", source_rows)
                _write_csv(output_dir / "raw_runs.csv", result_rows)
                _write_csv(output_dir / "candidate_trace.csv", trace_rows)

    calibration_dir = repo_root / args.calibration_dir
    calibration_rows = _calibrate_closure(repo_root, calibration_dir, float(args.battery_kwh))
    _write_csv(output_dir / "closure_calibration.csv", calibration_rows)
    calibration_clean = bool(calibration_rows) and all(bool(row["matched"]) for row in calibration_rows)
    verdict = classify_headroom(result_rows)
    if not calibration_clean:
        verdict = "HALT_FLEET_CLOSURE_NOT_CALIBRATED"

    manifest_path = repo_root / "models/data_bundle/generated_instances/L-main/resetp-l-main-main-benchmark.v3.json"
    metadata = {
        "schema_version": "setp-m1-joint-repack-fleet-headroom.v1",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "repo_commit": _git_value(repo_root, "rev-parse", "HEAD"),
        "repo_dirty_at_run": bool(_git_value(repo_root, "status", "--porcelain")),
        "source_fingerprint": fingerprint,
        "instances": [{"scale": scale, "instance": name} for scale, name in instances],
        "algorithms": list(ALGORITHMS),
        "seeds": seeds,
        "battery_kwh": float(args.battery_kwh),
        "eval_budget": int(args.eval_budget),
        "max_runtime_seconds": float(args.max_runtime_seconds),
        "repack_trials": int(args.repack_trials),
        "formal_manifest_sha256": _sha256(manifest_path),
        "calibration_source": str(calibration_dir.relative_to(repo_root)),
    }
    positive = [row for row in result_rows if float(row["joint_beyond_separate"]) > 1e-9]
    decision = {
        "schema_version": "setp-m1-joint-repack-fleet-headroom-decision.v1",
        "verdict": verdict,
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "source_count": len(result_rows),
        "clean_source_count": sum(bool(row["clean"]) for row in result_rows),
        "joint_beyond_separate_count": len(positive),
        "joint_beyond_separate_by_scale": {
            scale: sum(row["scale"] == scale and float(row["joint_beyond_separate"]) > 1e-9 for row in result_rows)
            for scale, _name in instances
        },
        "closure_calibration_count": len(calibration_rows),
        "closure_calibration_matched": sum(bool(row["matched"]) for row in calibration_rows),
        "meaning": "Only joint gain beyond both route repacking alone and fleet closure alone counts as sequential headroom.",
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "decision.json").write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = [
        "# M1 joint route-repack and fleet-closure headroom",
        "",
        f"Verdict: `{verdict}`.",
        "",
        "This probe does not add an operator to ALNS. It asks whether route regrouping followed by repeated vehicle-type and charging repair beats either step used alone.",
        "",
        f"Fleet closure calibration against exact fixed-route enumeration: {decision['closure_calibration_matched']}/{decision['closure_calibration_count']} matched.",
        "",
    ]
    for row in result_rows:
        report.append(
            f"- {row['scale']} / {row['algorithm']} / seed {row['seed']}: source {row['source_cost']:.6f}, "
            f"fleet-only {row['fleet_only_cost']:.6f}, repack-only {row['best_repack_cost']:.6f}, "
            f"joint {row['best_joint_cost']:.6f}, joint-beyond-separate {row['joint_beyond_separate']:.6f}, "
            f"routes {row['source_routes']}->{row['best_joint_routes']}, EV {row['source_ev_routes']}->{row['best_joint_ev_routes']}."
        )
    report.extend(
        [
            "",
            "Boundary: a positive value means the sequential combination exposes headroom missed by both isolated steps. It does not yet prove that scheduling this move inside ALNS improves a long run.",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(report), encoding="utf-8")

    source_paths = [
        Path(__file__).resolve(),
        manifest_path,
        repo_root / "solver/src/setp_solver/algorithms/resetp_alns/support/global_order_repack.py",
        repo_root / "solver/src/setp_solver/algorithms/resetp_alns/support/fleet_charge_corepair.py",
        repo_root / "solver/src/setp_solver/algorithms/resetp_alns/support/order_decoder.py",
        repo_root / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
        repo_root / "solver/src/setp_solver/search/candidates.py",
        repo_root / "solver/src/setp_solver/search/metaheuristic_baselines.py",
        calibration_dir / "summary.csv",
    ]
    targets = sorted(set([*source_paths, *evidence_files(output_dir)]))
    (output_dir / "artifact_hashes.json").write_text(
        json.dumps({str(path.relative_to(repo_root)): _sha256(path) for path in targets}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.clean_task_state:
        shutil.rmtree(output_dir / ".tasks", ignore_errors=True)
    return {"verdict": verdict, "sources": len(result_rows), "joint_beyond_separate": len(positive)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=REPO_ROOT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--calibration-dir", default=DEFAULT_CALIBRATION_DIR)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    parser.add_argument("--eval-budget", type=int, default=400)
    parser.add_argument("--max-runtime-seconds", type=float, default=180.0)
    parser.add_argument("--repack-trials", type=int, default=4)
    parser.add_argument("--seeds", default="1")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--clean-task-state", action="store_true", default=True)
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run_probe(parse_args()), indent=2, sort_keys=True))
