"""Resumable 4000-evaluation stability gate for the staged ALNS-LNS hybrid."""

from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
for _path in (REPO_ROOT, SOLVER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setp_solver.algorithms.resetp_alns.kernel.winner import WinnerKernelConfig, run_staged_alns_lns_hybrid
from setp_solver.algorithms.resetp_alns.support.construction import build_initial_solution
from setp_solver.algorithms.resetp_alns.support.fleet import infer_fleet_limits
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.search.instance_registry import assert_formal_benchmark_ready, instance_abs_dir
from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline, solution_to_dict


ALGORITHM = "staged ALNS-LNS hybrid"
BASELINE = "LNS"
DEFAULT_INSTANCES = (
    "L-main-threeshift-100c-01",
    "L-main-threeshift-150c-01",
    "L-main-threeshift-200c-01",
)
DEFAULT_SEEDS = (1, 2, 3, 4, 5)


@dataclass(frozen=True)
class StabilityTask:
    instance: str
    algorithm: str
    seed: int

    @property
    def run_id(self) -> str:
        safe_algorithm = self.algorithm.replace(" ", "_")
        return f"{self.instance}__{safe_algorithm}__seed{self.seed}"


def build_tasks(*, instances: Iterable[str], seeds: Iterable[int]) -> list[StabilityTask]:
    return [
        StabilityTask(str(instance), algorithm, int(seed))
        for instance in instances
        for seed in seeds
        for algorithm in (ALGORITHM, BASELINE)
    ]


def run_gate(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    assert_formal_benchmark_ready(repo_root)
    output_dir = repo_root / args.output_dir
    solution_dir = output_dir / "solutions"
    task_dir = output_dir / ".tasks"
    output_dir.mkdir(parents=True, exist_ok=True)
    solution_dir.mkdir(parents=True, exist_ok=True)
    task_dir.mkdir(parents=True, exist_ok=True)
    instances = tuple(item.strip() for item in str(args.instances).split(",") if item.strip())
    seeds = tuple(int(item) for item in str(args.seeds).split(",") if item.strip())
    tasks = build_tasks(instances=instances, seeds=seeds)
    if len(tasks) != len(instances) * len(seeds) * 2:
        raise RuntimeError("HALT_TASK_MATRIX")
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(args.battery_kwh))
    metadata = {
        "schema_version": "setp-m1-staged-hybrid-stability.v1",
        "algorithm": ALGORITHM,
        "baseline": BASELINE,
        "algorithm_identity": "hybrid",
        "carbon_aware_operators": False,
        "battery_kwh": float(args.battery_kwh),
        "paper_default_battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "parameter_status": "modern-battery diagnostic scenario; not paper default",
        "instances": list(instances),
        "seeds": list(seeds),
        "eval_budget": int(args.eval_budget),
        "max_runtime_seconds": float(args.max_runtime_seconds),
        "expected_runs": len(tasks),
        "git_commit": _git_value(repo_root, "rev-parse", "HEAD"),
    }
    _write_json(output_dir / "metadata.json", metadata)
    raw_path = output_dir / "raw_runs.csv"
    rows = _read_csv(raw_path) if raw_path.exists() else []
    completed = {str(row["run_id"]) for row in rows if str(row.get("status")) == "OK"}
    for task in tasks:
        if task.run_id in completed:
            continue
        _write_json(task_dir / f"{task.run_id}.json", {"status": "RUNNING", "run_id": task.run_id})
        row = _run_task(repo_root, solution_dir, task, prices, int(args.eval_budget), float(args.max_runtime_seconds))
        rows = [item for item in rows if str(item.get("run_id")) != task.run_id]
        rows.append(row)
        rows.sort(key=lambda item: (str(item["instance"]), int(item["seed"]), str(item["algorithm"])))
        _write_csv(raw_path, rows)
        _write_json(task_dir / f"{task.run_id}.json", {"status": row["status"], "run_id": task.run_id})
    return _finalize(output_dir, rows, metadata)


def _run_task(repo_root: Path, solution_dir: Path, task: StabilityTask, prices: Any, eval_budget: int, runtime: float) -> dict[str, Any]:
    bundle = load_search_bundle(instance_abs_dir(repo_root, task.instance))
    start = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        prices,
        fleet_limits=infer_fleet_limits(bundle.bundle_dir),
        introduce_ev=False,
        require_charging_signal=False,
    )
    started = time.perf_counter()
    if task.algorithm == ALGORITHM:
        result = run_staged_alns_lns_hybrid(
            bundle.bundle_dir,
            config=WinnerKernelConfig(seed=task.seed, eval_budget=eval_budget, max_runtime_seconds=runtime),
            initial_solution=copy.deepcopy(start),
            prices=prices,
        )
        solution = result["best_solution"]
        evaluations = int(result["evaluations"])
        cost = float(result["best_cost"])
        status = "OK" if result["feasible"] and evaluations == eval_budget else "HALT"
    elif task.algorithm == BASELINE:
        result = run_metaheuristic_baseline(
            BASELINE,
            bundle.bundle_dir,
            seed=task.seed,
            eval_budget=eval_budget,
            max_runtime_seconds=runtime,
            initial_solution=copy.deepcopy(start),
            prices=prices,
            common_flip_preprocess=False,
        )
        solution = result.best_solution
        evaluations = int(result.evals)
        cost = float(result.best_cost) if result.best_cost is not None else float("inf")
        status = str(result.status)
    else:
        raise ValueError(f"unsupported stability algorithm: {task.algorithm}")
    if solution is None:
        raise RuntimeError(f"{task.run_id} returned no solution")
    context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
    violations = check_solution(solution, bundle.instance, prices)
    recomputed_cost = model_cost(solution, context)
    if abs(recomputed_cost - cost) > 1e-6 or violations:
        status = "HALT_RECOMPUTE"
    _write_json(solution_dir / f"{task.run_id}.json", solution_to_dict(solution))
    return {
        "run_id": task.run_id,
        "instance": task.instance,
        "algorithm": task.algorithm,
        "seed": task.seed,
        "eval_budget": eval_budget,
        "evaluations": evaluations,
        "cost": recomputed_cost,
        "elapsed_seconds": time.perf_counter() - started,
        "routes": len(solution.routes),
        "ev_routes": sum(route.vehicle_type.lower() == "ev" for route in solution.routes),
        "violations": len(violations),
        "status": status,
        "battery_kwh": float(getattr(prices, "B_battery_kwh")),
        "carbon_aware_operators": False,
    }


def _finalize(output_dir: Path, rows: list[dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    expected = int(metadata["expected_runs"])
    if len(rows) != expected or any(str(row.get("status")) != "OK" for row in rows):
        decision = {"verdict": "HALT_INCOMPLETE", "completed_runs": len(rows), "expected_runs": expected}
        _write_json(output_dir / "decision.json", decision)
        return decision
    lookup = {(str(row["instance"]), int(row["seed"]), str(row["algorithm"])): row for row in rows}
    paired: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for instance in metadata["instances"]:
        instance_rows = []
        for seed in metadata["seeds"]:
            alns = lookup[(instance, int(seed), ALGORITHM)]
            lns = lookup[(instance, int(seed), BASELINE)]
            gain = (float(lns["cost"]) - float(alns["cost"])) / float(lns["cost"]) * 100.0
            row = {
                "instance": instance,
                "seed": int(seed),
                "hybrid_cost": float(alns["cost"]),
                "lns_cost": float(lns["cost"]),
                "gain_vs_lns_pct": gain,
                "hybrid_seconds": float(alns["elapsed_seconds"]),
                "lns_seconds": float(lns["elapsed_seconds"]),
            }
            paired.append(row)
            instance_rows.append(row)
        mean_hybrid = statistics.mean(float(row["hybrid_cost"]) for row in instance_rows)
        mean_lns = statistics.mean(float(row["lns_cost"]) for row in instance_rows)
        summaries.append(
            {
                "instance": instance,
                "mean_hybrid_cost": mean_hybrid,
                "mean_lns_cost": mean_lns,
                "mean_gain_pct": (mean_lns - mean_hybrid) / mean_lns * 100.0,
                "median_gain_pct": statistics.median(float(row["gain_vs_lns_pct"]) for row in instance_rows),
                "cost_wins": sum(float(row["gain_vs_lns_pct"]) > 1e-9 for row in instance_rows),
                "mean_hybrid_seconds": statistics.mean(float(row["hybrid_seconds"]) for row in instance_rows),
                "mean_lns_seconds": statistics.mean(float(row["lns_seconds"]) for row in instance_rows),
            }
        )
    _write_csv(output_dir / "paired_runs.csv", paired)
    _write_csv(output_dir / "instance_summary.csv", summaries)
    supported = all(float(row["mean_gain_pct"]) >= 0.0 and float(row["median_gain_pct"]) >= 0.0 for row in summaries)
    supported = supported and all(float(row["mean_hybrid_seconds"]) < float(row["mean_lns_seconds"]) for row in summaries)
    supported = supported and sum(int(row["cost_wins"]) for row in summaries) >= 8
    decision = {
        "schema_version": metadata["schema_version"],
        "verdict": "STAGED_HYBRID_STABILITY_SUPPORTED" if supported else "STAGED_HYBRID_STABILITY_NOT_SUPPORTED",
        "formal_t3": False,
        "algorithm_identity": "hybrid",
        "completed_runs": len(rows),
        "expected_runs": expected,
        "all_instance_means_non_losing": all(float(row["mean_gain_pct"]) >= 0.0 for row in summaries),
        "all_instance_medians_non_losing": all(float(row["median_gain_pct"]) >= 0.0 for row in summaries),
        "cost_wins": sum(int(row["cost_wins"]) for row in summaries),
        "next_action": "consider nine-scale/longer-budget gate" if supported else "stop algorithm changes and report hybrid framework",
    }
    _write_json(output_dir / "decision.json", decision)
    report = (
        "# Staged ALNS-LNS hybrid stability gate\n\n"
        f"Completed {len(rows)}/{expected} runs at {metadata['eval_budget']} evaluations and {metadata['battery_kwh']} kWh. "
        "The algorithm is explicitly a hybrid; carbon-aware operators are disabled.\n\n"
        f"Verdict: `{decision['verdict']}`.\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    hashes = {
        str(path.relative_to(output_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and ".tasks" not in path.parts and not path.name.startswith("._")
    }
    _write_json(output_dir / "artifact_hashes.json", hashes)
    return decision


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


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output-dir", default="baselines/e2_alns/m1_staged_hybrid_stability_20260710")
    parser.add_argument("--instances", default=",".join(DEFAULT_INSTANCES))
    parser.add_argument("--seeds", default=",".join(str(seed) for seed in DEFAULT_SEEDS))
    parser.add_argument("--eval-budget", type=int, default=4000)
    parser.add_argument("--max-runtime-seconds", type=float, default=900.0)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    args = parser.parse_args()
    print(json.dumps(run_gate(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
