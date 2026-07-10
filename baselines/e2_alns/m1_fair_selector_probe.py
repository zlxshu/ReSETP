"""Fair current-v3 triage of default ALNS, softmax ALNS, and LNS."""

from __future__ import annotations

import argparse
import copy
from collections import Counter
from dataclasses import replace
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
for _path in (REPO_ROOT, SOLVER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from baselines.e2_alns.m1_joint_repack_fleet_headroom import (
    _cv_start,
    _save_solution,
    _sha256,
    _write_csv,
    evidence_files,
)
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    CHAIN_UCB_SELECTOR_FLAG,
    SOFTMAX_SELECTOR_FLAG,
    TRACE_DIAGNOSTIC_FLAG,
    WinnerKernelConfig,
    _run_winner_kernel_loop,
    e2_alns_throughput_flags,
)
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.search.instance_registry import assert_formal_benchmark_ready, instance_abs_dir
from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline


DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/m1_fair_selector_20260710")
INSTANCES = (
    ("small", "L-main-threeshift-20c-01"),
    ("medium", "L-main-threeshift-50c-01"),
    ("large", "L-main-threeshift-100c-01"),
)
ALNS_PROFILES = ("DEFAULT_ALPHA_UCB", "SOFTMAX")


def classify_selector(rows: Iterable[dict[str, Any]]) -> str:
    items = list(rows)
    if not items or not all(bool(row.get("clean")) for row in items):
        return "FAIR_SOFTMAX_400_NOT_SUPPORTED"
    wins = sum(float(row["softmax_minus_default"]) < -1e-9 for row in items)
    mean_cost = sum(float(row["softmax_minus_default"]) for row in items) / len(items)
    mean_runtime = sum(float(row["softmax_runtime_minus_default"]) for row in items) / len(items)
    if wins >= math.ceil(0.60 * len(items)) and mean_cost < -1e-9 and mean_runtime < -1e-9:
        return "FAIR_SOFTMAX_400_SUPPORTED"
    return "FAIR_SOFTMAX_400_NOT_SUPPORTED"


def _git_value(repo_root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo_root, check=True, capture_output=True, text=True).stdout.strip()


def _alns_flags(profile: str) -> dict[str, str]:
    flags = e2_alns_throughput_flags()
    flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"] = "0"
    flags[TRACE_DIAGNOSTIC_FLAG] = "1"
    flags[SOFTMAX_SELECTOR_FLAG] = "1" if profile == "SOFTMAX" else "0"
    flags[CHAIN_UCB_SELECTOR_FLAG] = "1" if profile == "CHAIN_UCB" else "0"
    return flags


def _run_alns(
    bundle: Any,
    prices: Any,
    start: Any,
    profile: str,
    seed: int,
    eval_budget: int,
    runtime: float,
) -> tuple[dict[str, Any], Any]:
    started = time.perf_counter()
    run = _run_winner_kernel_loop(
        copy.deepcopy(start),
        bundle.instance,
        bundle.carbon_profile,
        config=WinnerKernelConfig(seed=seed, eval_budget=eval_budget, max_runtime_seconds=runtime),
        prices=prices,
        variant_flags=_alns_flags(profile),
    )
    context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
    traces = list(run.operator_counts.get("candidate_trace", []))
    selected = Counter((str(row.get("destroy_id", "")), str(row.get("repair_id", ""))) for row in traces)
    dominant = selected.most_common(1)[0][1] if selected else 0
    score_counts = dict(run.operator_counts.get("score_counts", {}))
    violations = check_solution(run.best_solution, bundle.instance, prices)
    row = {
        "algorithm": profile,
        "seed": seed,
        "eval_budget": eval_budget,
        "actual_evaluations": int(run.evaluations),
        "elapsed_seconds": time.perf_counter() - started,
        "best_cost": float(model_cost(run.best_solution, context)),
        "best_routes": len(run.best_solution.routes),
        "best_ev_routes": sum(route.vehicle_type.lower() == "ev" for route in run.best_solution.routes),
        "feasible": not violations,
        "violation_count": len(violations),
        "selected_pair_count": len(selected),
        "dominant_pair_share": dominant / max(1, sum(selected.values())),
        "vehicle_type_attempts": sum(selected[pair] for pair in selected if pair[0] == "vehicle_type_swap"),
        "hidden_local_search_scores": int(score_counts.get("local_search_full_solution", 0)),
    }
    return row, run.best_solution


def _run_lns(bundle: Any, prices: Any, start: Any, seed: int, eval_budget: int, runtime: float) -> tuple[dict[str, Any], Any]:
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
        raise RuntimeError(f"LNS returned no solution: {run.failure_reason}")
    row = {
        "algorithm": "LNS",
        "seed": seed,
        "eval_budget": eval_budget,
        "actual_evaluations": int(run.evals),
        "elapsed_seconds": float(run.elapsed_seconds),
        "best_cost": float(run.best_cost),
        "best_routes": int(run.route_count),
        "best_ev_routes": int(run.ev_route_count),
        "feasible": bool(run.feasible),
        "violation_count": int(run.violation_count),
        "selected_pair_count": 0,
        "dominant_pair_share": 0.0,
        "vehicle_type_attempts": 0,
        "hidden_local_search_scores": 0,
    }
    return row, run.best_solution


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    assert_formal_benchmark_ready(repo_root)
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(args.battery_kwh))
    seeds = [int(value) for value in str(args.seeds).split(",") if value.strip()]
    raw_rows: list[dict[str, Any]] = []
    for scale, instance_name in INSTANCES:
        bundle = load_search_bundle(instance_abs_dir(repo_root, instance_name))
        start = _cv_start(bundle, prices)
        initial_context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
        initial_cost = float(model_cost(start, initial_context))
        for seed in seeds:
            for profile in (*ALNS_PROFILES, "LNS"):
                if profile == "LNS":
                    row, solution = _run_lns(bundle, prices, start, seed, int(args.eval_budget), float(args.max_runtime_seconds))
                else:
                    row, solution = _run_alns(bundle, prices, start, profile, seed, int(args.eval_budget), float(args.max_runtime_seconds))
                run_id = f"{scale}__{instance_name}__{profile}__seed{seed}"
                solution_path = output_dir / "solutions" / f"{run_id}.json"
                _save_solution(solution_path, solution)
                row.update(
                    {
                        "run_id": run_id,
                        "scale": scale,
                        "instance": instance_name,
                        "actual_customer_count": sum(node.node_type.lower() == "c" for node in bundle.instance.nodes),
                        "initial_cost": initial_cost,
                        "clean": bool(row["feasible"])
                        and int(row["actual_evaluations"]) == int(args.eval_budget)
                        and int(row["hidden_local_search_scores"]) == 0,
                        "solution_path": str(solution_path.relative_to(repo_root)),
                    }
                )
                raw_rows.append(row)
                _write_csv(output_dir / "raw_runs.csv", raw_rows)

    grouped: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for row in raw_rows:
        grouped.setdefault((str(row["scale"]), int(row["seed"])), {})[str(row["algorithm"])] = row
    comparisons: list[dict[str, Any]] = []
    for (scale, seed), profiles in sorted(grouped.items()):
        default = profiles["DEFAULT_ALPHA_UCB"]
        softmax = profiles["SOFTMAX"]
        lns = profiles["LNS"]
        comparisons.append(
            {
                "scale": scale,
                "seed": seed,
                "default_cost": default["best_cost"],
                "softmax_cost": softmax["best_cost"],
                "lns_cost": lns["best_cost"],
                "softmax_minus_default": float(softmax["best_cost"]) - float(default["best_cost"]),
                "softmax_minus_lns": float(softmax["best_cost"]) - float(lns["best_cost"]),
                "softmax_gain_vs_lns_pct": (float(lns["best_cost"]) - float(softmax["best_cost"])) / max(1e-9, float(lns["best_cost"])) * 100.0,
                "default_runtime": default["elapsed_seconds"],
                "softmax_runtime": softmax["elapsed_seconds"],
                "lns_runtime": lns["elapsed_seconds"],
                "softmax_runtime_minus_default": float(softmax["elapsed_seconds"]) - float(default["elapsed_seconds"]),
                "clean": bool(default["clean"]) and bool(softmax["clean"]) and bool(lns["clean"]),
            }
        )
    _write_csv(output_dir / "comparisons.csv", comparisons)
    verdict = classify_selector(comparisons)
    mean_softmax_default = sum(float(row["softmax_minus_default"]) for row in comparisons) / len(comparisons)
    mean_gain_lns_pct = sum(float(row["softmax_gain_vs_lns_pct"]) for row in comparisons) / len(comparisons)
    decision = {
        "schema_version": "setp-m1-fair-selector-decision.v1",
        "verdict": verdict,
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "comparison_count": len(comparisons),
        "softmax_wins_vs_default": sum(float(row["softmax_minus_default"]) < -1e-9 for row in comparisons),
        "softmax_losses_vs_default": sum(float(row["softmax_minus_default"]) > 1e-9 for row in comparisons),
        "mean_softmax_minus_default": mean_softmax_default,
        "mean_softmax_gain_vs_lns_pct": mean_gain_lns_pct,
        "softmax_beats_lns_count": sum(float(row["softmax_minus_lns"]) < -1e-9 for row in comparisons),
        "softmax_runtime_below_lns_count": sum(float(row["softmax_runtime"]) < float(row["lns_runtime"]) for row in comparisons),
        "five_percent_target_signal": mean_gain_lns_pct >= 5.0,
    }
    metadata = {
        "schema_version": "setp-m1-fair-selector.v1",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "repo_commit": _git_value(repo_root, "rev-parse", "HEAD"),
        "repo_dirty_at_run": bool(_git_value(repo_root, "status", "--porcelain")),
        "battery_kwh": float(args.battery_kwh),
        "eval_budget": int(args.eval_budget),
        "seeds": seeds,
        "instances": [{"scale": scale, "instance": instance} for scale, instance in INSTANCES],
    }
    (output_dir / "decision.json").write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(
        "# M1 fair selector triage\n\n"
        f"Verdict: `{verdict}`.\n\n"
        f"Softmax versus default: {decision['softmax_wins_vs_default']} wins / {decision['softmax_losses_vs_default']} losses; "
        f"mean cost delta {mean_softmax_default:.6f}. Mean softmax gain versus LNS: {mean_gain_lns_pct:.3f}%.\n\n"
        "All rows use the same CV start, 280 kWh prices, exact complete-evaluation count, no local search, and the unchanged checker/evaluator. This is a three-scale triage, not the nine-instance benchmark.\n",
        encoding="utf-8",
    )
    manifest = repo_root / "models/data_bundle/generated_instances/L-main/resetp-l-main-main-benchmark.v3.json"
    sources = [
        Path(__file__).resolve(),
        manifest,
        repo_root / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
        repo_root / "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
        repo_root / "solver/src/setp_solver/algorithms/resetp_alns/runtime/select.py",
        repo_root / "solver/src/setp_solver/search/metaheuristic_baselines.py",
    ]
    targets = sorted(set([*sources, *evidence_files(output_dir)]))
    (output_dir / "artifact_hashes.json").write_text(
        json.dumps({str(path.relative_to(repo_root)): _sha256(path) for path in targets}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"verdict": verdict, "comparisons": len(comparisons), "gain_vs_lns_pct": mean_gain_lns_pct}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=REPO_ROOT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    parser.add_argument("--eval-budget", type=int, default=400)
    parser.add_argument("--max-runtime-seconds", type=float, default=180.0)
    parser.add_argument("--seeds", default="1,2,3")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run_probe(parse_args()), indent=2, sort_keys=True))
