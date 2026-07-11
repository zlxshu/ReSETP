"""Equal-budget short gates for bounded E2 loss-recovery candidates."""

from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import replace
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
for _path in (REPO_ROOT, SOLVER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerKernelConfig,
    run_proportional_true_lns_middle_alns_hybrid,
    run_restarted_staged_alns_lns_hybrid,
    run_staged_alns_lns_hybrid,
    run_true_lns_middle_alns_hybrid,
)
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.search.instance_registry import assert_formal_benchmark_ready, instance_abs_dir
from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline, solution_to_dict


CANDIDATE_ALGORITHMS = ("restarted", "true_lns_middle", "proportional_true_lns_middle")
DEVELOPMENT_PAIRS = (
    ("L-main-threeshift-20c-01", 3),
    ("L-main-threeshift-50c-01", 5),
    ("L-main-threeshift-150c-01", 3),
    ("L-main-threeshift-100c-01", 2),
    ("L-main-threeshift-15c-01", 2),
    ("L-main-threeshift-75c-01", 1),
)
GUARD_PAIRS = (
    ("L-main-threeshift-100c-01", 4),
    ("L-main-threeshift-150c-01", 4),
    ("L-main-threeshift-75c-01", 5),
)


def _run_task(payload: tuple[str, str, int, int, float, float, str]) -> dict[str, Any]:
    repo_root_text, instance, seed, eval_budget, runtime, battery_kwh, algorithm = payload
    repo_root = Path(repo_root_text)
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(battery_kwh))
    bundle = load_search_bundle(instance_abs_dir(repo_root, instance))
    start = make_shared_initial_solution(bundle, prices=prices)
    config = WinnerKernelConfig(seed=seed, eval_budget=eval_budget, max_runtime_seconds=runtime)
    started = time.perf_counter()
    operator_counts: dict[str, Any] = {}
    if algorithm == "staged":
        result = run_staged_alns_lns_hybrid(
            bundle.bundle_dir,
            config=config,
            initial_solution=copy.deepcopy(start),
            prices=prices,
        )
        solution = result["best_solution"]
        evaluations = int(result["evaluations"])
        reported_cost = float(result["best_cost"])
        status = "OK" if result["feasible"] and evaluations == eval_budget else "HALT"
        operator_counts = dict(result.get("operator_counts", {}))
    elif algorithm == "restarted":
        result = run_restarted_staged_alns_lns_hybrid(
            bundle.bundle_dir,
            config=config,
            initial_solution=copy.deepcopy(start),
            prices=prices,
        )
        solution = result["best_solution"]
        evaluations = int(result["evaluations"])
        reported_cost = float(result["best_cost"])
        status = "OK" if result["feasible"] and evaluations == eval_budget else "HALT"
        operator_counts = dict(result.get("operator_counts", {}))
    elif algorithm == "true_lns_middle":
        result = run_true_lns_middle_alns_hybrid(
            bundle.bundle_dir,
            config=config,
            initial_solution=copy.deepcopy(start),
            prices=prices,
        )
        solution = result["best_solution"]
        evaluations = int(result["evaluations"])
        reported_cost = float(result["best_cost"])
        status = "OK" if result["feasible"] and evaluations == eval_budget else "HALT"
        operator_counts = dict(result.get("operator_counts", {}))
    elif algorithm == "proportional_true_lns_middle":
        result = run_proportional_true_lns_middle_alns_hybrid(
            bundle.bundle_dir,
            config=config,
            initial_solution=copy.deepcopy(start),
            prices=prices,
        )
        solution = result["best_solution"]
        evaluations = int(result["evaluations"])
        reported_cost = float(result["best_cost"])
        status = "OK" if result["feasible"] and evaluations == eval_budget else "HALT"
        operator_counts = dict(result.get("operator_counts", {}))
    elif algorithm == "LNS":
        result = run_metaheuristic_baseline(
            "LNS",
            bundle.bundle_dir,
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=runtime,
            initial_solution=copy.deepcopy(start),
            prices=prices,
            common_flip_preprocess=True,
        )
        solution = result.best_solution
        evaluations = int(result.evals)
        reported_cost = float(result.best_cost) if result.best_cost is not None else float("inf")
        status = str(result.status)
    else:
        raise ValueError(algorithm)
    if solution is None:
        raise RuntimeError(f"{instance}/{seed}/{algorithm} returned no solution")
    context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
    violations = check_solution(solution, bundle.instance, prices)
    recomputed_cost = model_cost(solution, context)
    if abs(recomputed_cost - reported_cost) > 1e-6 or violations or evaluations != eval_budget:
        status = "HALT_RECOMPUTE"
    return {
        "run_id": f"{instance}__seed{seed}__{algorithm}",
        "instance": instance,
        "seed": seed,
        "pair_role": "development" if (instance, seed) in DEVELOPMENT_PAIRS else "guard",
        "algorithm": algorithm,
        "eval_budget": eval_budget,
        "actual_evals": evaluations,
        "cost": recomputed_cost,
        "elapsed_seconds": time.perf_counter() - started,
        "routes": len(solution.routes),
        "ev_routes": sum(route.vehicle_type.lower() == "ev" for route in solution.routes),
        "violations": len(violations),
        "status": status,
        "solution": solution_to_dict(solution),
        "operator_counts": operator_counts,
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _atomic_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _finalize(output_dir: Path, rows: list[dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    expected = int(metadata["expected_runs"])
    complete = len(rows) == expected and all(row["status"] == "OK" for row in rows)
    if not complete:
        decision = {"verdict": "HALT_INCOMPLETE", "completed_runs": len(rows), "expected_runs": expected}
        _atomic_json(output_dir / "decision.json", decision)
        return decision
    lookup = {(row["instance"], int(row["seed"]), row["algorithm"]): row for row in rows}
    candidate_id = str(metadata["candidate_id"])
    paired: list[dict[str, Any]] = []
    for instance, seed in (*DEVELOPMENT_PAIRS, *GUARD_PAIRS):
        staged = lookup[(instance, seed, "staged")]
        candidate = lookup[(instance, seed, candidate_id)]
        lns = lookup[(instance, seed, "LNS")]
        staged_cost = float(staged["cost"])
        candidate_cost = float(candidate["cost"])
        lns_cost = float(lns["cost"])
        paired.append(
            {
                "instance": instance,
                "seed": seed,
                "pair_role": staged["pair_role"],
                "staged_cost": staged_cost,
                "candidate_id": candidate_id,
                "candidate_cost": candidate_cost,
                "lns_cost": lns_cost,
                "candidate_gain_vs_staged_pct": (staged_cost - candidate_cost) / staged_cost * 100.0,
                "staged_gain_vs_lns_pct": (lns_cost - staged_cost) / lns_cost * 100.0,
                "candidate_gain_vs_lns_pct": (lns_cost - candidate_cost) / lns_cost * 100.0,
            }
        )
    _atomic_csv(output_dir / "paired_comparisons.csv", paired)
    development = [row for row in paired if row["pair_role"] == "development"]
    guards = [row for row in paired if row["pair_role"] == "guard"]
    mean_dev_gain = statistics.mean(float(row["candidate_gain_vs_staged_pct"]) for row in development)
    mean_all_gain = statistics.mean(float(row["candidate_gain_vs_staged_pct"]) for row in paired)
    converted = sum(
        float(row["staged_gain_vs_lns_pct"]) < -1e-9 and float(row["candidate_gain_vs_lns_pct"]) >= -1e-9
        for row in development
    )
    worst_guard = min(float(row["candidate_gain_vs_staged_pct"]) for row in guards)
    promoted = mean_dev_gain > 0.0 and mean_all_gain > 0.0 and converted >= 2 and worst_guard >= -2.0
    decision = {
        "verdict": f"{candidate_id.upper()}_SHORT_GATE_PROMOTED" if promoted else f"{candidate_id.upper()}_SHORT_GATE_REJECTED",
        "candidate_id": candidate_id,
        "completed_runs": len(rows),
        "expected_runs": expected,
        "eval_budget": metadata["eval_budget"],
        "zero_violations": all(int(row["violations"]) == 0 for row in rows),
        "mean_development_gain_vs_staged_pct": mean_dev_gain,
        "mean_all_gain_vs_staged_pct": mean_all_gain,
        "development_losses_converted_vs_lns": converted,
        "worst_guard_gain_vs_staged_pct": worst_guard,
        "next_action": "unseen-seed 4000-evaluation validation" if promoted else f"reject {candidate_id} candidate and inspect the next bounded mechanism",
    }
    _atomic_json(output_dir / "decision.json", decision)
    report = (
        f"# E2 {candidate_id} loss-recovery short gate\n\n"
        f"Completed {len(rows)}/{expected} equal-budget runs at {metadata['eval_budget']} evaluations. "
        f"Verdict: `{decision['verdict']}`.\n\n"
        f"Mean development-pair gain over the frozen staged structure: {mean_dev_gain:.3f}%. "
        f"Converted losses versus LNS: {converted}. Worst guard change: {worst_guard:.3f}%.\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    hashes = {
        str(path.relative_to(output_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    _atomic_json(output_dir / "artifact_hashes.json", hashes)
    return decision


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    assert_formal_benchmark_ready(repo_root)
    output_dir = repo_root / args.output_dir
    solution_dir = output_dir / "solutions"
    output_dir.mkdir(parents=True, exist_ok=True)
    solution_dir.mkdir(parents=True, exist_ok=True)
    pairs = (*DEVELOPMENT_PAIRS, *GUARD_PAIRS)
    algorithms = ("staged", str(args.candidate), "LNS")
    tasks = [
        (str(repo_root), instance, seed, int(args.eval_budget), float(args.max_runtime_seconds), float(args.battery_kwh), algorithm)
        for instance, seed in pairs
        for algorithm in algorithms
    ]
    metadata = {
        "schema_version": "setp-e2-loss-recovery-short-gate.v3",
        "candidate_id": str(args.candidate),
        "candidate": {
            "restarted": "restarted staged ALNS-LNS hybrid",
            "true_lns_middle": "ALNS + true LNS middle + ALNS hybrid",
            "proportional_true_lns_middle": "proportional ALNS + true LNS middle + ALNS hybrid",
        }[args.candidate],
        "incumbent": "staged ALNS-LNS hybrid",
        "baseline": "LNS",
        "development_pairs": [list(pair) for pair in DEVELOPMENT_PAIRS],
        "guard_pairs": [list(pair) for pair in GUARD_PAIRS],
        "eval_budget": int(args.eval_budget),
        "battery_kwh": float(args.battery_kwh),
        "start_contract": "formal make_shared_initial_solution with EV introduction and inferred fleet limits",
        "lns_common_flip_preprocess": True,
        "expected_runs": len(tasks),
        "workers": int(args.workers),
        "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, capture_output=True, text=True).stdout.strip(),
    }
    _atomic_json(output_dir / "metadata.json", metadata)
    raw_path = output_dir / "raw_runs.csv"
    existing = _read_csv(raw_path)
    rows: list[dict[str, Any]] = [dict(row) for row in existing if row.get("status") == "OK"]
    completed = {row["run_id"] for row in rows}
    pending = [task for task in tasks if f"{task[1]}__seed{task[2]}__{task[6]}" not in completed]
    with ProcessPoolExecutor(max_workers=max(1, int(args.workers))) as executor:
        futures = {executor.submit(_run_task, task): task for task in pending}
        for future in as_completed(futures):
            result = future.result()
            solution = result.pop("solution")
            operator_counts = result.pop("operator_counts")
            _atomic_json(solution_dir / f"{result['run_id']}.json", solution)
            _atomic_json(solution_dir / f"{result['run_id']}.operators.json", operator_counts)
            rows = [row for row in rows if row["run_id"] != result["run_id"]]
            rows.append(result)
            rows.sort(key=lambda row: (row["instance"], int(row["seed"]), row["algorithm"]))
            _atomic_csv(raw_path, rows)
    return _finalize(output_dir, rows, metadata)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output-dir", default="baselines/e2_alns/e2_loss_recovery_20260711/true_lns_middle_gate")
    parser.add_argument("--candidate", choices=CANDIDATE_ALGORITHMS, default="true_lns_middle")
    parser.add_argument("--eval-budget", type=int, default=1600)
    parser.add_argument("--max-runtime-seconds", type=float, default=600.0)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
