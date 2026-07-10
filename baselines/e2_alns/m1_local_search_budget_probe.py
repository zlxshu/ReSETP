"""Measure complete-solution scoring hidden inside the current T3 local search."""

from __future__ import annotations

import argparse
import copy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
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
    WinnerKernelConfig,
    _run_winner_kernel_loop,
    e2_alns_throughput_flags,
)
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.search.instance_registry import assert_formal_benchmark_ready, instance_abs_dir


DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/m1_local_search_budget_20260710")
INSTANCES = (
    ("small", "L-main-threeshift-20c-01"),
    ("medium", "L-main-threeshift-50c-01"),
    ("large", "L-main-threeshift-100c-01"),
)
PROFILES = ("CURRENT_T3", "NO_LOCAL_SEARCH")


def classify_budget(rows: Iterable[dict[str, Any]]) -> str:
    items = list(rows)
    current = [row for row in items if str(row.get("profile")) == "CURRENT_T3"]
    controls = [row for row in items if str(row.get("profile")) == "NO_LOCAL_SEARCH"]
    if (
        current
        and controls
        and all(bool(row.get("clean")) for row in items)
        and any(int(row.get("hidden_full_solution_scores", 0)) > 0 for row in current)
        and all(int(row.get("hidden_full_solution_scores", 0)) == 0 for row in controls)
    ):
        return "LOCAL_SEARCH_BUDGET_UNDERCOUNT_CONFIRMED"
    return "LOCAL_SEARCH_BUDGET_UNDERCOUNT_NOT_SHOWN"


def _git_value(repo_root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo_root, check=True, capture_output=True, text=True).stdout.strip()


def _run_one(
    bundle: Any,
    prices: Any,
    start: Any,
    profile: str,
    seed: int,
    eval_budget: int,
    runtime: float,
) -> tuple[dict[str, Any], Any]:
    flags = e2_alns_throughput_flags()
    flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"] = "1" if profile == "CURRENT_T3" else "0"
    run = _run_winner_kernel_loop(
        copy.deepcopy(start),
        bundle.instance,
        bundle.carbon_profile,
        config=WinnerKernelConfig(seed=seed, eval_budget=eval_budget, max_runtime_seconds=runtime),
        prices=prices,
        variant_flags=flags,
    )
    score_counts = dict(run.operator_counts.get("score_counts", {}))
    hidden = int(score_counts.get("local_search_full_solution", 0))
    neighbor = int(score_counts.get("local_search_neighbor", 0))
    context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
    violations = check_solution(run.best_solution, bundle.instance, prices)
    row = {
        "profile": profile,
        "seed": seed,
        "eval_budget": eval_budget,
        "official_evaluations": int(run.evaluations),
        "candidate_scores": int(run.candidate_scores),
        "hidden_full_solution_scores": hidden,
        "hidden_neighbor_scores": neighbor,
        "effective_full_solution_scores": int(run.candidate_scores) + hidden,
        "effective_to_official_ratio": (int(run.candidate_scores) + hidden) / max(1, int(run.evaluations)),
        "best_cost": float(model_cost(run.best_solution, context)),
        "best_routes": len(run.best_solution.routes),
        "best_ev_routes": sum(route.vehicle_type.lower() == "ev" for route in run.best_solution.routes),
        "feasible": not violations,
        "violation_count": len(violations),
        "clean": not violations and int(run.evaluations) >= eval_budget,
        "official_budget_overshoot": max(0, int(run.evaluations) - eval_budget),
    }
    return row, run.best_solution


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    assert_formal_benchmark_ready(repo_root)
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(args.battery_kwh))
    seeds = [int(value) for value in str(args.seeds).split(",") if value.strip()]
    rows: list[dict[str, Any]] = []
    for scale, instance_name in INSTANCES:
        bundle = load_search_bundle(instance_abs_dir(repo_root, instance_name))
        start = _cv_start(bundle, prices)
        initial_context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
        initial_cost = float(model_cost(start, initial_context))
        for seed in seeds:
            for profile in PROFILES:
                row, solution = _run_one(
                    bundle,
                    prices,
                    start,
                    profile,
                    seed,
                    int(args.eval_budget),
                    float(args.max_runtime_seconds),
                )
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
                        "solution_path": str(solution_path.relative_to(repo_root)),
                    }
                )
                rows.append(row)
                _write_csv(output_dir / "raw_runs.csv", rows)

    by_key: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_key.setdefault((str(row["scale"]), int(row["seed"])), {})[str(row["profile"])] = row
    comparisons: list[dict[str, Any]] = []
    for (scale, seed), profiles in sorted(by_key.items()):
        current = profiles["CURRENT_T3"]
        control = profiles["NO_LOCAL_SEARCH"]
        comparisons.append(
            {
                "scale": scale,
                "seed": seed,
                "current_t3_cost": current["best_cost"],
                "no_local_search_cost": control["best_cost"],
                "current_minus_control": float(current["best_cost"]) - float(control["best_cost"]),
                "current_official_evaluations": current["official_evaluations"],
                "control_official_evaluations": control["official_evaluations"],
                "current_hidden_full_solution_scores": current["hidden_full_solution_scores"],
                "current_effective_to_official_ratio": current["effective_to_official_ratio"],
            }
        )
    _write_csv(output_dir / "comparisons.csv", comparisons)
    verdict = classify_budget(rows)
    current_rows = [row for row in rows if row["profile"] == "CURRENT_T3"]
    decision = {
        "schema_version": "setp-m1-local-search-budget-decision.v1",
        "verdict": verdict,
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "run_count": len(rows),
        "current_t3_run_count": len(current_rows),
        "hidden_full_solution_scores_total": sum(int(row["hidden_full_solution_scores"]) for row in current_rows),
        "hidden_full_solution_scores_min": min(int(row["hidden_full_solution_scores"]) for row in current_rows),
        "hidden_full_solution_scores_max": max(int(row["hidden_full_solution_scores"]) for row in current_rows),
        "effective_to_official_ratio_mean": sum(float(row["effective_to_official_ratio"]) for row in current_rows) / len(current_rows),
        "official_budget_overshoot_runs": sum(int(row["official_budget_overshoot"]) > 0 for row in current_rows),
        "meaning": "The current T3 profile evaluates complete local-search solutions without charging those calls to its reported evaluation budget.",
    }
    metadata = {
        "schema_version": "setp-m1-local-search-budget.v1",
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
    report = [
        "# M1 local-search budget accounting",
        "",
        f"Verdict: `{verdict}`.",
        "",
        f"Across {len(current_rows)} current-T3 runs, hidden complete-solution scores totalled {decision['hidden_full_solution_scores_total']}; "
        f"the per-run range was {decision['hidden_full_solution_scores_min']}--{decision['hidden_full_solution_scores_max']}. "
        f"The mean effective/reported evaluation ratio was {decision['effective_to_official_ratio_mean']:.3f}.",
        "",
        "The no-local-search control used the same starts, seeds, instances, prices, and reported budget. This is an accounting diagnosis, not a fair performance ranking, because the current profile consumed unreported evaluator work.",
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(report), encoding="utf-8")

    manifest = repo_root / "models/data_bundle/generated_instances/L-main/resetp-l-main-main-benchmark.v3.json"
    sources = [
        Path(__file__).resolve(),
        repo_root / "baselines/e2_alns/m1_joint_repack_fleet_headroom.py",
        manifest,
        repo_root / "solver/src/setp_solver/algorithms/resetp_alns/operators/local_search.py",
        repo_root / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    ]
    targets = sorted(set([*sources, *evidence_files(output_dir)]))
    (output_dir / "artifact_hashes.json").write_text(
        json.dumps({str(path.relative_to(repo_root)): _sha256(path) for path in targets}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"verdict": verdict, "runs": len(rows), "hidden_scores": decision["hidden_full_solution_scores_total"]}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=REPO_ROOT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    parser.add_argument("--eval-budget", type=int, default=100)
    parser.add_argument("--max-runtime-seconds", type=float, default=120.0)
    parser.add_argument("--seeds", default="1,2,3")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run_probe(parse_args()), indent=2, sort_keys=True))
