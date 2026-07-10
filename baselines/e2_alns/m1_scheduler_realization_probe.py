"""Check whether the current ALNS selector realizes known-good structure moves.

The companion one-step probe proves that useful structure-changing candidates
exist.  This script runs the unchanged winner loop from the same starts and
compares its current AlphaUCB selector with the already-existing diagnostic
balanced selector.  It is a mechanism test, not an algorithm ranking.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
for _path in (REPO_ROOT, SOLVER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setp_solver.algorithms.resetp_alns.kernel.winner import (
    BALANCED_SELECTOR_FLAG,
    MINIMUM_COVERAGE_SELECTOR_FLAG,
    TRACE_DIAGNOSTIC_FLAG,
    WinnerKernelConfig,
    _run_winner_kernel_loop,
    e2_alns_throughput_flags,
)
from setp_solver.algorithms.resetp_alns.support.construction import build_initial_solution
from setp_solver.algorithms.resetp_alns.support.fleet import infer_fleet_limits
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.search.instance_registry import assert_formal_benchmark_ready, instance_abs_dir
from setp_solver.solution import Solution


DEFAULT_INSTANCE = "L-main-threeshift-25c-01"
DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/m1_scheduler_realization_20260710")
PROFILES = ("DEFAULT_ALPHA_UCB", "BALANCED_COVERAGE", "MINIMUM_COVERAGE")


def classify_scheduler(rows: Iterable[dict[str, Any]]) -> str:
    by_key: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_key[(str(row.get("start", "")), int(row.get("seed", 0)))][str(row.get("profile", ""))] = row

    starvation_seen = False
    causal_seen = False
    for profiles in by_key.values():
        default = profiles.get("DEFAULT_ALPHA_UCB")
        balanced = profiles.get("BALANCED_COVERAGE")
        if default is None or balanced is None:
            continue
        starved = float(default.get("dominant_pair_share", 0.0)) >= 0.90 and int(default.get("selected_pair_count", 0)) <= 2
        if not starved:
            continue
        starvation_seen = True
        wider_coverage = int(balanced.get("selected_pair_count", 0)) > int(default.get("selected_pair_count", 0))
        lower_cost = float(balanced.get("best_cost", float("inf"))) < float(default.get("best_cost", float("inf"))) - 1e-9
        if wider_coverage and lower_cost:
            causal_seen = True
    if causal_seen:
        return "DEFAULT_SELECTOR_STARVATION_CONFIRMED"
    if starvation_seen:
        return "SELECTOR_STARVATION_PRESENT_NOT_CAUSAL"
    return "SELECTOR_NOT_PRIMARY_BARRIER"


def classify_minimum_coverage(rows: Iterable[dict[str, Any]]) -> str:
    by_key: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_key[(str(row.get("start", "")), int(row.get("seed", 0)))][str(row.get("profile", ""))] = row

    paired: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for profiles in by_key.values():
        default = profiles.get("DEFAULT_ALPHA_UCB")
        minimum = profiles.get("MINIMUM_COVERAGE")
        if default is not None and minimum is not None:
            paired.append((default, minimum))
    if not paired:
        return "MINIMUM_COVERAGE_400_NOT_SUPPORTED"
    clean_coverage = all(
        bool(minimum.get("feasible"))
        and int(minimum.get("actual_evaluations", 0)) >= int(minimum.get("eval_budget", 0))
        and int(minimum.get("vehicle_type_swap_attempts", 0)) > 0
        for _, minimum in paired
    )
    wins = sum(
        1
        for default, minimum in paired
        if float(minimum.get("best_cost", float("inf"))) < float(default.get("best_cost", float("inf"))) - 1e-9
    )
    mean_delta = sum(float(minimum["best_cost"]) - float(default["best_cost"]) for default, minimum in paired) / len(paired)
    majority_gate = wins >= math.ceil(0.60 * len(paired))
    if clean_coverage and majority_gate and mean_delta < -1e-9:
        return "MINIMUM_COVERAGE_400_SUPPORTED"
    return "MINIMUM_COVERAGE_400_NOT_SUPPORTED"


def _git_value(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _solution_metrics(solution: Solution) -> dict[str, int]:
    return {
        "route_count": len(solution.routes),
        "ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
        "charging_action_count": len(solution.charging_actions),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _starts(bundle: Any, prices: Any) -> dict[str, Solution]:
    cv_only = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        prices,
        fleet_limits=infer_fleet_limits(bundle.bundle_dir),
        introduce_ev=False,
        require_charging_signal=False,
    )
    return {
        "CV_ONLY": cv_only,
        "SHARED_ONE_EV": make_shared_initial_solution(bundle, prices),
    }


def _flags(profile: str) -> dict[str, str]:
    flags = e2_alns_throughput_flags()
    flags[TRACE_DIAGNOSTIC_FLAG] = "1"
    flags[BALANCED_SELECTOR_FLAG] = "1" if profile == "BALANCED_COVERAGE" else "0"
    flags[MINIMUM_COVERAGE_SELECTOR_FLAG] = "1" if profile == "MINIMUM_COVERAGE" else "0"
    return flags


def _trace_row(run_id: str, profile: str, start: str, seed: int, row: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "move",
        "eval",
        "destroy_id",
        "repair_id",
        "changed",
        "hard_violation_count",
        "candidate_obj",
        "previous_obj",
        "previous_best_obj",
        "accepted",
        "best_improved",
        "accepted_worse",
        "better_current",
        "revert_reason",
        "candidate_route_count_delta",
        "raw_candidate_route_count_delta",
        "selector_type",
        "selector_phase",
        "selector_pair_times",
        "selector_value",
    }
    return {
        "run_id": run_id,
        "profile": profile,
        "start": start,
        "seed": seed,
        **{key: value for key, value in row.items() if key in keep},
    }


def _run_one(
    bundle: Any,
    prices: Any,
    start_name: str,
    start: Solution,
    profile: str,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], Solution]:
    run_id = f"{profile}__{start_name}__seed{seed}"
    run = _run_winner_kernel_loop(
        start,
        bundle.instance,
        bundle.carbon_profile,
        config=WinnerKernelConfig(
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
        ),
        prices=prices,
        variant_flags=_flags(profile),
    )
    traces = list(run.operator_counts.get("candidate_trace", []))
    selected = Counter((str(row.get("destroy_id", "")), str(row.get("repair_id", ""))) for row in traces)
    accepted = Counter((str(row.get("destroy_id", "")), str(row.get("repair_id", ""))) for row in traces if row.get("accepted"))
    best_updates = Counter((str(row.get("destroy_id", "")), str(row.get("repair_id", ""))) for row in traces if row.get("best_improved"))
    attempts = sum(selected.values())
    dominant_pair, dominant_count = selected.most_common(1)[0] if selected else (("", ""), 0)
    initial_metrics = _solution_metrics(start)
    best_metrics = _solution_metrics(run.best_solution)
    context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
    violations = check_solution(run.best_solution, bundle.instance, prices)
    raw = {
        "run_id": run_id,
        "profile": profile,
        "start": start_name,
        "seed": seed,
        "eval_budget": eval_budget,
        "actual_evaluations": int(run.evaluations),
        "trace_rows": len(traces),
        "initial_cost": float(run.initial_obj),
        "best_cost": float(model_cost(run.best_solution, context)),
        "cost_improvement": float(run.initial_obj - run.best_obj),
        "initial_routes": initial_metrics["route_count"],
        "best_routes": best_metrics["route_count"],
        "initial_ev_routes": initial_metrics["ev_route_count"],
        "best_ev_routes": best_metrics["ev_route_count"],
        "initial_charging_actions": initial_metrics["charging_action_count"],
        "best_charging_actions": best_metrics["charging_action_count"],
        "feasible": not violations,
        "violation_count": len(violations),
        "best_update_count": sum(best_updates.values()),
        "accepted_count": sum(accepted.values()),
        "accepted_worse_count": sum(1 for row in traces if row.get("accepted_worse")),
        "selected_pair_count": len(selected),
        "dominant_destroy": dominant_pair[0],
        "dominant_repair": dominant_pair[1],
        "dominant_pair_count": dominant_count,
        "dominant_pair_share": dominant_count / max(1, attempts),
        "vehicle_type_swap_attempts": sum(count for (destroy, _), count in selected.items() if destroy == "vehicle_type_swap"),
        "whole_route_attempts": sum(count for (destroy, _), count in selected.items() if destroy == "whole_route_removal"),
        "route_drop_candidate_rows": sum(1 for row in traces if int(row.get("candidate_route_count_delta", 0) or 0) < 0),
        "vehicle_type_swap_best_updates": sum(count for (destroy, _), count in best_updates.items() if destroy == "vehicle_type_swap"),
    }
    pair_rows = [
        {
            "run_id": run_id,
            "profile": profile,
            "start": start_name,
            "seed": seed,
            "destroy": pair[0],
            "repair": pair[1],
            "selected": count,
            "accepted": accepted[pair],
            "best_updates": best_updates[pair],
        }
        for pair, count in sorted(selected.items())
    ]
    return raw, pair_rows, [_trace_row(run_id, profile, start_name, seed, row) for row in traces], run.best_solution


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    manifest = assert_formal_benchmark_ready(repo_root)
    bundle = load_search_bundle(instance_abs_dir(repo_root, args.instance))
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(args.battery_kwh))
    starts = _starts(bundle, prices)
    seeds = [int(value) for value in str(args.seeds).split(",") if value.strip()]

    raw_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []
    solutions: dict[str, Solution] = {}
    for start_name, start in starts.items():
        for seed in seeds:
            for profile in PROFILES:
                raw, pairs, traces, solution = _run_one(
                    bundle,
                    prices,
                    start_name,
                    start,
                    profile,
                    seed,
                    args.eval_budget,
                    args.max_runtime_seconds,
                )
                raw_rows.append(raw)
                pair_rows.extend(pairs)
                trace_rows.extend(traces)
                solutions[str(raw["run_id"])] = solution

    verdict = classify_scheduler(raw_rows)
    minimum_coverage_verdict = classify_minimum_coverage(raw_rows)
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    solution_dir = output_dir / "solutions"
    solution_dir.mkdir(parents=True, exist_ok=True)
    for row in raw_rows:
        solution_path = solution_dir / f"{row['run_id']}.json"
        solution_path.write_text(
            json.dumps(asdict(solutions[str(row["run_id"])]), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        row["best_solution_path"] = str(solution_path.relative_to(repo_root))
    _write_csv(output_dir / "raw_runs.csv", raw_rows)
    _write_csv(output_dir / "operator_pair_summary.csv", pair_rows)
    _write_csv(output_dir / "trace_rows.csv", trace_rows)

    manifest_path = repo_root / "models/data_bundle/generated_instances/L-main/resetp-l-main-main-benchmark.v3.json"
    metadata = {
        "schema_version": "setp-m1-scheduler-realization.v1",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "repo_commit": _git_value(repo_root, "rev-parse", "HEAD"),
        "repo_dirty_at_run": bool(_git_value(repo_root, "status", "--porcelain")),
        "instance": args.instance,
        "actual_customer_count": sum(1 for node in bundle.instance.nodes if node.node_type.lower() == "c"),
        "battery_kwh": float(args.battery_kwh),
        "eval_budget": int(args.eval_budget),
        "max_runtime_seconds": float(args.max_runtime_seconds),
        "seeds": seeds,
        "profiles": list(PROFILES),
        "formal_manifest_schema": manifest.get("schema_version"),
        "formal_manifest_sha256": _sha256(manifest_path),
        "one_step_decision": "baselines/e2_alns/m1_structure_reachability_20260710/decision.json",
        "algorithm_source_sha256": {
            str(path.relative_to(repo_root)): _sha256(path)
            for path in (
                repo_root / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
                repo_root / "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
                repo_root / "solver/src/setp_solver/algorithms/resetp_alns/runtime/select.py",
            )
        },
    }
    decision = {
        "schema_version": "setp-m1-scheduler-realization-decision.v1",
        "verdict": verdict,
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "run_count": len(raw_rows),
        "minimum_coverage_verdict": minimum_coverage_verdict,
        "meaning": {
            "DEFAULT_SELECTOR_STARVATION_CONFIRMED": "At least one matched start/seed collapsed to at most two pairs, while forced coverage reached more pairs and a lower cost.",
            "SELECTOR_STARVATION_PRESENT_NOT_CAUSAL": "At least one default run collapsed, but wider coverage did not improve that matched run.",
            "SELECTOR_NOT_PRIMARY_BARRIER": "The default runs did not meet the predeclared starvation condition.",
        }[verdict],
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "decision.json").write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = [
        "# M1 scheduler realization diagnostic",
        "",
        f"Verdict: `{verdict}`.",
        f"Minimum-coverage gate: `{minimum_coverage_verdict}`.",
        "",
        "The one-step probe already showed that ALNS can make useful route and vehicle-type changes. "
        "This experiment asks whether the unchanged full loop actually gives those moves a chance. "
        "It is diagnostic only and makes no ALNS-versus-SA win claim.",
        "",
        f"Instance: `{args.instance}`; actual customers: `{metadata['actual_customer_count']}`; "
        f"battery: `{args.battery_kwh}` kWh; budget: `{args.eval_budget}` evaluations; seeds: `{seeds}`.",
        "",
        "## Matched runs",
        "",
    ]
    for row in raw_rows:
        report.append(
            f"- {row['start']} / seed {row['seed']} / {row['profile']}: best {row['best_cost']:.6f}, "
            f"routes {row['best_routes']}, EV routes {row['best_ev_routes']}, "
            f"selected pairs {row['selected_pair_count']}, dominant share {row['dominant_pair_share']:.3f}, "
            f"vehicle-type attempts {row['vehicle_type_swap_attempts']}."
        )
    report.extend(
        [
            "",
            "## Boundary",
            "",
            "A coverage improvement at this short budget proves that early pair starvation can cause a missed result. "
            "The minimum-coverage branch passes only if it covers vehicle-type moves in every matched run, wins at least 60% of pairs, and lowers mean cost. "
            "Even a 400-evaluation pass does not prove long-budget or cross-instance superiority.",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(report), encoding="utf-8")

    targets = [
        Path(__file__).resolve(),
        manifest_path,
        repo_root / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
        repo_root / "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
        repo_root / "solver/src/setp_solver/algorithms/resetp_alns/runtime/select.py",
        output_dir / "raw_runs.csv",
        output_dir / "operator_pair_summary.csv",
        output_dir / "trace_rows.csv",
        output_dir / "metadata.json",
        output_dir / "decision.json",
        output_dir / "report.md",
        *sorted(solution_dir.glob("*.json")),
    ]
    (output_dir / "artifact_hashes.json").write_text(
        json.dumps(
            {str(path.relative_to(repo_root)): _sha256(path) for path in targets},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "verdict": verdict,
        "minimum_coverage_verdict": minimum_coverage_verdict,
        "run_count": len(raw_rows),
        "trace_row_count": len(trace_rows),
        "output_dir": str(output_dir),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=REPO_ROOT)
    parser.add_argument("--instance", default=DEFAULT_INSTANCE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    parser.add_argument("--eval-budget", type=int, default=400)
    parser.add_argument("--max-runtime-seconds", type=float, default=120.0)
    parser.add_argument("--seeds", default="1,2,3,4,5")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run_probe(parse_args()), indent=2, sort_keys=True))
