"""Short, same-start, price-aware SA recheck against saved M1 ALNS runs."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import time
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
for _path in (REPO_ROOT, SOLVER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setp_solver.algorithms.resetp_alns.support.construction import build_initial_solution
from setp_solver.algorithms.resetp_alns.support.fleet import infer_fleet_limits
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import CandidateState, _algorithm_seed, _run_sa_path, make_shared_initial_solution
from setp_solver.search.evaluation import EvalBudget, EvaluationContext, model_cost, score_reference
from setp_solver.search.instance_registry import assert_formal_benchmark_ready, instance_abs_dir
from setp_solver.solution import Solution


DEFAULT_INSTANCE = "L-main-threeshift-25c-01"
DEFAULT_SCHEDULER_DIR = Path("baselines/e2_alns/m1_scheduler_realization_20260710")
DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/m1_fair_sa_recheck_20260710")


def classify_sa(rows: Iterable[dict[str, Any]]) -> str:
    relevant = [row for row in rows if str(row.get("profile")) == "DEFAULT_ALPHA_UCB"]
    if not relevant or not all(bool(row.get("clean")) for row in relevant):
        return "SA_SHORT_ADVANTAGE_NOT_REPRODUCED"
    wins = sum(float(row["sa_best_cost"]) < float(row["alns_best_cost"]) - 1e-9 for row in relevant)
    mean_delta = sum(float(row["sa_best_cost"]) - float(row["alns_best_cost"]) for row in relevant) / len(relevant)
    if wins >= math.ceil(0.60 * len(relevant)) and mean_delta < -1e-9:
        return "SA_SHORT_ADVANTAGE_REPRODUCED"
    return "SA_SHORT_ADVANTAGE_NOT_REPRODUCED"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_value(repo_root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo_root, check=True, capture_output=True, text=True).stdout.strip()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _starts(bundle: Any, prices: Any) -> dict[str, Solution]:
    return {
        "CV_ONLY": build_initial_solution(
            bundle.instance,
            bundle.carbon_profile,
            prices,
            fleet_limits=infer_fleet_limits(bundle.bundle_dir),
            introduce_ev=False,
            require_charging_signal=False,
        ),
        "SHARED_ONE_EV": make_shared_initial_solution(bundle, prices),
    }


def _run_sa(
    bundle: Any,
    prices: Any,
    start_name: str,
    start: Solution,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], Solution]:
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=EvalBudget(limit=eval_budget, target=eval_budget),
    )
    state = CandidateState(start, context)
    initial_obj = score_reference(start, context)
    initial_cost = model_cost(start, context)
    selected: Counter[str] = Counter()
    trace: list[dict[str, Any]] = []

    def recorder(**payload: Any) -> None:
        operator = str(payload["repair_op"])
        selected[operator] += 1
        candidate = payload["candidate"]
        trace.append(
            {
                "start": start_name,
                "seed": seed,
                "iteration": int(payload["iteration"]),
                "operator": operator,
                "accepted": bool(payload["accepted"]),
                "improved_current": bool(payload["improved_current"]),
                "best_improved": float(payload["candidate_obj"]) < float(payload["previous_best_obj"]) - 1e-9,
                "candidate_routes": len(candidate.routes),
                "candidate_ev_routes": sum(route.vehicle_type.lower() == "ev" for route in candidate.routes),
                "temperature": float(payload["temperature"]),
            }
        )

    best, best_obj, best_cost, _, _ = _run_sa_path(
        state,
        random.Random(_algorithm_seed("scikit-opt-SA", seed)),
        start,
        initial_obj,
        initial_cost,
        start,
        initial_obj,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        started=time.perf_counter(),
        recorder=recorder,
    )
    violations = check_solution(best, bundle.instance, prices)
    dominant_operator, dominant_count = selected.most_common(1)[0] if selected else ("", 0)
    row = {
        "start": start_name,
        "seed": seed,
        "eval_budget": eval_budget,
        "actual_evaluations": int(context.budget.count if context.budget else 0),
        "initial_cost": float(initial_cost),
        "best_cost": float(best_cost),
        "cost_improvement": float(initial_cost - best_cost),
        "best_routes": len(best.routes),
        "best_ev_routes": sum(route.vehicle_type.lower() == "ev" for route in best.routes),
        "feasible": not violations,
        "violation_count": len(violations),
        "operator_calls": int(state.search_diagnostics["operator_calls"]),
        "candidate_changed": int(state.search_diagnostics["candidate_changed"]),
        "candidate_accepted": int(state.search_diagnostics["candidate_accepted"]),
        "best_updates": int(state.search_diagnostics["best_updates"]),
        "selected_operator_count": len(selected),
        "dominant_operator": dominant_operator,
        "dominant_operator_share": dominant_count / max(1, sum(selected.values())),
    }
    return row, trace, best


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    assert_formal_benchmark_ready(repo_root)
    bundle = load_search_bundle(instance_abs_dir(repo_root, args.instance))
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(args.battery_kwh))
    starts = _starts(bundle, prices)
    seeds = [int(item) for item in str(args.seeds).split(",") if item.strip()]
    scheduler_dir = repo_root / args.scheduler_dir
    alns_rows = _read_csv(scheduler_dir / "raw_runs.csv")

    sa_rows: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []
    solutions: dict[tuple[str, int], Solution] = {}
    for start_name, start in starts.items():
        for seed in seeds:
            row, traces, solution = _run_sa(bundle, prices, start_name, start, seed, args.eval_budget, args.max_runtime_seconds)
            matching = [
                item
                for item in alns_rows
                if item["start"] == start_name and int(item["seed"]) == seed
            ]
            if not matching or any(abs(float(item["initial_cost"]) - float(row["initial_cost"])) > 1e-9 for item in matching):
                raise RuntimeError(f"same-start contract mismatch for {start_name} seed {seed}")
            sa_rows.append(row)
            trace_rows.extend(traces)
            solutions[(start_name, seed)] = solution

    comparisons: list[dict[str, Any]] = []
    sa_by_key = {(row["start"], int(row["seed"])): row for row in sa_rows}
    for alns in alns_rows:
        sa = sa_by_key[(alns["start"], int(alns["seed"]))]
        comparisons.append(
            {
                "profile": alns["profile"],
                "start": alns["start"],
                "seed": int(alns["seed"]),
                "eval_budget": int(alns["eval_budget"]),
                "sa_best_cost": float(sa["best_cost"]),
                "alns_best_cost": float(alns["best_cost"]),
                "sa_minus_alns": float(sa["best_cost"]) - float(alns["best_cost"]),
                "sa_routes": int(sa["best_routes"]),
                "alns_routes": int(alns["best_routes"]),
                "sa_ev_routes": int(sa["best_ev_routes"]),
                "alns_ev_routes": int(alns["best_ev_routes"]),
                "clean": bool(sa["feasible"]) and int(sa["actual_evaluations"]) >= int(alns["eval_budget"]),
            }
        )
    verdict = classify_sa(comparisons)

    output_dir = repo_root / args.output_dir
    solution_dir = output_dir / "solutions"
    solution_dir.mkdir(parents=True, exist_ok=True)
    for row in sa_rows:
        path = solution_dir / f"SA__{row['start']}__seed{row['seed']}.json"
        path.write_text(json.dumps(asdict(solutions[(row["start"], int(row["seed"]))]), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        row["best_solution_path"] = str(path.relative_to(repo_root))
    _write_csv(output_dir / "raw_runs.csv", sa_rows)
    _write_csv(output_dir / "comparisons.csv", comparisons)
    _write_csv(output_dir / "trace_rows.csv", trace_rows)

    metadata = {
        "schema_version": "setp-m1-fair-sa-recheck.v1",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "repo_commit": _git_value(repo_root, "rev-parse", "HEAD"),
        "repo_dirty_at_run": bool(_git_value(repo_root, "status", "--porcelain")),
        "instance": args.instance,
        "battery_kwh": float(args.battery_kwh),
        "eval_budget": int(args.eval_budget),
        "seeds": seeds,
        "scheduler_raw_sha256": _sha256(scheduler_dir / "raw_runs.csv"),
        "sa_source_sha256": _sha256(repo_root / "solver/src/setp_solver/search/candidates.py"),
    }
    default_rows = [row for row in comparisons if row["profile"] == "DEFAULT_ALPHA_UCB"]
    decision = {
        "schema_version": "setp-m1-fair-sa-recheck-decision.v1",
        "verdict": verdict,
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "sa_wins_vs_default": sum(float(row["sa_minus_alns"]) < -1e-9 for row in default_rows),
        "sa_losses_vs_default": sum(float(row["sa_minus_alns"]) > 1e-9 for row in default_rows),
        "mean_sa_minus_default": sum(float(row["sa_minus_alns"]) for row in default_rows) / len(default_rows),
        "meaning": "This closes only the current-v3 280kWh 400-evaluation same-start check; it is not a long-budget algorithm ranking.",
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "decision.json").write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = (
        f"# M1 fair SA short recheck\n\nVerdict: `{verdict}`.\n\n"
        f"SA wins/losses versus default ALNS: {decision['sa_wins_vs_default']}/{decision['sa_losses_vs_default']}; "
        f"mean SA minus ALNS cost: {decision['mean_sa_minus_default']:.6f}.\n\n"
        "Both algorithms received the same start object, 280 kWh prices, 400 complete evaluations, and the unchanged checker/evaluator. "
        "This short diagnostic cannot replace a 4000/8000/16000 fair comparison.\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")

    targets = [
        Path(__file__).resolve(),
        repo_root / "solver/src/setp_solver/search/candidates.py",
        scheduler_dir / "raw_runs.csv",
        output_dir / "raw_runs.csv",
        output_dir / "comparisons.csv",
        output_dir / "trace_rows.csv",
        output_dir / "metadata.json",
        output_dir / "decision.json",
        output_dir / "report.md",
        *sorted(path for path in solution_dir.glob("*.json") if not path.name.startswith("._")),
    ]
    (output_dir / "artifact_hashes.json").write_text(
        json.dumps({str(path.relative_to(repo_root)): _sha256(path) for path in targets}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"verdict": verdict, "sa_runs": len(sa_rows), "comparisons": len(comparisons)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=REPO_ROOT)
    parser.add_argument("--instance", default=DEFAULT_INSTANCE)
    parser.add_argument("--scheduler-dir", default=DEFAULT_SCHEDULER_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    parser.add_argument("--eval-budget", type=int, default=400)
    parser.add_argument("--max-runtime-seconds", type=float, default=120.0)
    parser.add_argument("--seeds", default="1,2,3,4,5")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run_probe(parse_args()), indent=2, sort_keys=True))
