#!/usr/bin/env python3
"""Complete E2 as a 9-instance x 9-algorithm x 10-run benchmark.

The first five seeds for the primary method and GA/PSO/VNS/LNS are reused
from the accepted frozen E2 evidence.  Missing rows are executed by the
frozen commit worktree so that later code changes cannot alter the algorithm
identity.  The immediate-charging row is retained as E3 ablation evidence and
is never counted as an E2 competitor.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
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

from baselines.e2_alns import e2_final_closure as closure
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.submission_contract import E2_LANE, load_submission_contract


FREEZE_COMMIT = "0124623e347cd2a6a5548e07e0af66e16d3b634b"
DEFAULT_EXECUTION_ROOT = REPO_ROOT / ".codex/worktrees/e2-frozen-0124623e"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/e2_final_10seed_20260711"
DEFAULT_CONTRACT = REPO_ROOT / "baselines/contract_audit/submission_contract_candidate_20260711/submission_contract.proposed.json"
FROZEN_EVIDENCE = REPO_ROOT / "baselines/e2_alns/e2_submission_20260711/carbon_280/raw_runs.csv"
PRIMARY = "staged_hybrid_carbon_aware"
ABLATION = "staged_hybrid_carbon_naive"
BASELINES = ("GA", "PSO", "VNS", "ACO", "GA-VNS", "LNS", "GWO", "IWD")
ALGORITHMS = (PRIMARY, *BASELINES)
REUSED_ALGORITHMS = (PRIMARY, "GA", "PSO", "VNS", "LNS")
INSTANCES = tuple(f"L-main-threeshift-{size}c-01" for size in (10, 15, 20, 25, 50, 75, 100, 150, 200))
SEEDS = tuple(range(1, 11))
SCENARIO = "diagnostic_280_override"
EVAL_BUDGET = 4000
GOLD_PYTHON = "/opt/anaconda3/bin/python3.13"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("manifest", "smoke", "representative", "formal", "verify"), required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--execution-root", type=Path, default=DEFAULT_EXECUTION_ROOT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def key(row: dict[str, Any]) -> tuple[str, str, int]:
    return str(row.get("instance")), str(row.get("algorithm")), int(float(row.get("seed", 0)))


def logical_run_id(instance: str, algorithm: str, seed: int) -> str:
    value = f"E2_FINAL_10SEED__{SCENARIO}__threeshift__{instance}__{algorithm}__seed{seed}"
    return re.sub(r"[^A-Za-z0-9_.=-]+", "_", value)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execution_head(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def validate_execution_root(root: Path) -> None:
    if execution_head(root) != FREEZE_COMMIT:
        raise RuntimeError(f"HALT_E2_EXECUTION_COMMIT_DRIFT: {execution_head(root)} != {FREEZE_COMMIT}")
    required = root / "baselines/e2_alns/e2_final_closure.py"
    if not required.is_file():
        raise FileNotFoundError(required)


def annotate(row: dict[str, Any], *, provenance: str, source_run_id: str = "") -> dict[str, Any]:
    out = dict(row)
    out["source_run_id"] = source_run_id or str(row.get("run_id", ""))
    out["run_id"] = logical_run_id(str(row["instance"]), str(row["algorithm"]), int(float(row["seed"])))
    out["phase"] = "E2_FINAL_10SEED"
    out["row_provenance"] = provenance
    out["execution_commit"] = FREEZE_COMMIT
    out["harness_commit"] = execution_head(REPO_ROOT)
    return out


def frozen_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = closure.read_csv(FROZEN_EVIDENCE)
    main = [
        annotate(row, provenance="REUSED_FROZEN_E2_5SEED")
        for row in rows
        if row.get("algorithm") in REUSED_ALGORITHMS and int(float(row.get("seed", 0))) <= 5
    ]
    ablation = [
        annotate(row, provenance="REUSED_FROZEN_E3_ABLATION")
        for row in rows
        if row.get("algorithm") == ABLATION and int(float(row.get("seed", 0))) <= 5
    ]
    if len(main) != 225 or len({key(row) for row in main}) != 225:
        raise RuntimeError(f"HALT_FROZEN_REUSE_MATRIX: expected 225 main rows, got {len(main)}")
    if any(
        row.get("gate_status") != "OK"
        or int(float(row.get("actual_evals", -1))) != EVAL_BUDGET
        or int(float(row.get("violation_count", -1))) != 0
        or not str(row.get("solution_json", ""))
        for row in main
    ):
        raise RuntimeError("HALT_FROZEN_REUSE_ROW_CONTRACT")
    if len(ablation) != 45 or len({key(row) for row in ablation}) != 45:
        raise RuntimeError(f"HALT_FROZEN_ABLATION_MATRIX: expected 45 rows, got {len(ablation)}")
    return main, ablation


def gate_rows(output: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    path = output / "representative_gate/raw_runs.csv"
    if not path.exists():
        return [], []
    decision = closure.read_json(output / "representative_gate/decision.json")
    if decision.get("verdict") != "E2_10SEED_REPRESENTATIVE_READY":
        return [], []
    rows = closure.read_csv(path)
    main = [annotate(row, provenance="REUSED_REPRESENTATIVE_4000_GATE") for row in rows if row.get("algorithm") in ALGORITHMS]
    if len(main) != 18 or any(
        row.get("gate_status") != "OK"
        or int(float(row.get("actual_evals", -1))) != EVAL_BUDGET
        or int(float(row.get("violation_count", -1))) != 0
        for row in main
    ):
        raise RuntimeError("HALT_REPRESENTATIVE_REUSE_ROW_CONTRACT")
    ablation_path = output / "representative_gate/ablation_rows.csv"
    ablation = [annotate(row, provenance="REUSED_REPRESENTATIVE_E3_ABLATION") for row in closure.read_csv(ablation_path)]
    return main, ablation


def merge_rows(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, int], dict[str, Any]] = {}
    for group in groups:
        for row in group:
            merged.setdefault(key(row), row)
    return sorted(merged.values(), key=lambda row: (INSTANCES.index(str(row["instance"])), ALGORITHMS.index(str(row["algorithm"])) if row.get("algorithm") in ALGORITHMS else 99, int(float(row["seed"]))))


def reusable_main_row(row: dict[str, Any], *, eval_budget: int, instances: tuple[str, ...], seeds: tuple[int, ...]) -> bool:
    return (
        str(row.get("instance")) in instances
        and str(row.get("algorithm")) in ALGORITHMS
        and int(float(row.get("seed", 0))) in seeds
        and row.get("gate_status") == "OK"
        and int(float(row.get("actual_evals", -1))) == eval_budget
        and int(float(row.get("violation_count", -1))) == 0
        and bool(str(row.get("solution_json", "")))
    )


def build_task(execution_root: Path, phase_dir: Path, instance: str, algorithm: str, seed: int, eval_budget: int) -> dict[str, Any]:
    task_algorithm = "staged_hybrid_carbon_pair" if algorithm == PRIMARY else algorithm
    task = closure.make_task(
        phase="E2_FINAL_10SEED",
        phase_dir=phase_dir,
        category="threeshift",
        instance=instance,
        algorithm=task_algorithm,
        seed=seed,
        eval_budget=eval_budget,
        runtime_cap_seconds=closure.runtime_cap_for_instance(instance),
        scenario_type=SCENARIO,
    )
    # Execute the solver module from the frozen worktree, but read the generated
    # L-main bundle from the active repository.  Generated instance data is not
    # present in the historical worktree; its exact files are protected by the
    # submission-contract hash registry before any task starts.
    task["repo_root"] = str(REPO_ROOT)
    task["head"] = FREEZE_COMMIT
    task["logical_algorithm"] = algorithm
    task["checkpoint_path"] = str(phase_dir / "checkpoints" / f"{task['run_id']}.json")
    return task


def expand_worker_row(row: dict[str, Any], task: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    logical_algorithm = str(task["logical_algorithm"])
    if logical_algorithm != PRIMARY:
        row["algorithm"] = logical_algorithm
        return annotate(row, provenance="NEW_FROZEN_COMMIT_EXECUTION", source_run_id=str(row.get("run_id", ""))), None
    source_run_id = str(row.get("run_id", ""))
    aware = dict(row)
    aware["algorithm"] = PRIMARY
    aware["display_algorithm"] = "staged ALNS-LNS hybrid + carbon-aware charging schedule"
    aware = annotate(aware, provenance="NEW_FROZEN_COMMIT_EXECUTION", source_run_id=source_run_id)
    payload = json.loads(str(row.get("charging_ablation_json", "{}")) or "{}")
    if not payload:
        return aware, None
    naive = dict(row)
    naive["algorithm"] = ABLATION
    naive["display_algorithm"] = "staged ALNS-LNS hybrid + immediate charging ablation"
    naive["charging_strategy"] = "naive"
    for field in (
        "best_cost", "best_signature", "route_structure_signature", "violation_count",
        "charging_action_count", "E_total", "E_cv_direct", "E_ev_indirect",
        "electricity_kwh", "cost_carbon", "solution_json",
    ):
        source_field = "solution" if field == "solution_json" else field
        if source_field in payload:
            naive[field] = json.dumps(payload[source_field], ensure_ascii=False, sort_keys=True) if field == "solution_json" else payload[source_field]
    naive = annotate(naive, provenance="NEW_FROZEN_E3_ABLATION", source_run_id=source_run_id)
    return aware, naive


def execute_task(execution_root: Path, task_root: Path, task: dict[str, Any], index: int) -> tuple[dict[str, Any], dict[str, Any] | None]:
    task_root.mkdir(parents=True, exist_ok=True)
    task_path = task_root / f"task_{index:04d}_{task['run_id']}.json"
    row_path = task_root / f"row_{index:04d}_{task['run_id']}.json"
    closure.write_json(task_path, task)
    worker = execution_root / "baselines/e2_alns/e2_final_closure.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = "solver/src:models/src:."
    env["PYTHONHASHSEED"] = "0"
    started = time.perf_counter()
    try:
        result = subprocess.run(
            [GOLD_PYTHON, str(worker), "--task-json", str(task_path), "--task-output-json", str(row_path)],
            cwd=execution_root,
            env=env,
            text=True,
            capture_output=True,
            timeout=float(task["runtime_cap_seconds"]) + 45.0,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        row = closure.timeout_row(task, time.perf_counter() - started, exc.stdout, exc.stderr)
        return expand_worker_row(row, task)
    if result.returncode != 0 or not row_path.exists():
        row = closure.worker_error_row(task, "HALT_WORKER_ERROR", result.stdout, result.stderr, time.perf_counter() - started)
        return expand_worker_row(row, task)
    return expand_worker_row(closure.read_json(row_path), task)


def persist(phase_dir: Path, main_rows: list[dict[str, Any]], ablation_rows: list[dict[str, Any]]) -> None:
    closure.write_csv(phase_dir / "raw_runs.csv", main_rows)
    closure.write_csv(phase_dir / "ablation_rows.csv", ablation_rows)


def run_tasks(
    execution_root: Path,
    phase_dir: Path,
    tasks: list[dict[str, Any]],
    main_rows: list[dict[str, Any]],
    ablation_rows: list[dict[str, Any]],
    workers: int,
    force: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    main_by_key = {key(row): row for row in main_rows}
    ablation_by_key = {key(row): row for row in ablation_rows}
    todo = [task for task in tasks if force or (str(task["instance"]), str(task["logical_algorithm"]), int(task["seed"])) not in main_by_key]
    task_root = phase_dir / ".tasks"
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        future_map = {pool.submit(execute_task, execution_root, task_root, task, index): task for index, task in enumerate(todo)}
        for future in as_completed(future_map):
            main, ablation = future.result()
            main_by_key[key(main)] = main
            if ablation is not None:
                ablation_by_key[key(ablation)] = ablation
            main_rows = merge_rows(list(main_by_key.values()))
            ablation_rows = sorted(ablation_by_key.values(), key=lambda row: (str(row["instance"]), int(float(row["seed"]))))
            persist(phase_dir, main_rows, ablation_rows)
            if main.get("gate_status") != "OK":
                for pending in future_map:
                    pending.cancel()
                raise RuntimeError(f"{main.get('gate_status')}: {main.get('failure_reason')}")
    return merge_rows(list(main_by_key.values())), sorted(ablation_by_key.values(), key=lambda row: (str(row["instance"]), int(float(row["seed"]))))


def phase_decision(rows: list[dict[str, Any]], *, expected: int, eval_budget: int, representative: bool) -> dict[str, Any]:
    keys = {key(row) for row in rows}
    okay = [row for row in rows if row.get("gate_status") == "OK"]
    closed = [row for row in rows if int(float(row.get("actual_evals", -1))) == eval_budget]
    zero = [row for row in rows if int(float(row.get("violation_count", -1))) == 0]
    active = [row for row in rows if int(float(row.get("algorithm_specific_update_count", 0))) >= 1]
    ready = len(rows) == expected and len(keys) == expected and len(okay) == expected and len(closed) == expected and len(zero) == expected
    if representative:
        ready = ready and len(active) == expected
    verdict = "E2_10SEED_REPRESENTATIVE_READY" if ready and representative else "E2_10SEED_SMOKE_READY" if ready else "HALT_E2_10SEED_GATE"
    return {
        "schema": "resetp.e2-10seed-gate.v1",
        "verdict": verdict,
        "expected_rows": expected,
        "observed_rows": len(rows),
        "unique_keys": len(keys),
        "ok_rows": len(okay),
        "eval_closed_rows": len(closed),
        "zero_violation_rows": len(zero),
        "algorithm_specific_active_rows": len(active),
        "eval_budget": eval_budget,
        "execution_commit": FREEZE_COMMIT,
    }


def manifest_rows(reused: list[dict[str, Any]], gate: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = {key(row): row for row in merge_rows(reused, gate)}
    rows = []
    for instance in INSTANCES:
        for algorithm in ALGORITHMS:
            for seed in SEEDS:
                source = existing.get((instance, algorithm, seed))
                rows.append(
                    {
                        "instance": instance,
                        "algorithm": algorithm,
                        "seed": seed,
                        "action": "REUSE" if source else "RUN",
                        "provenance": source.get("row_provenance", "") if source else "NEW_FROZEN_COMMIT_EXECUTION",
                        "eval_budget": EVAL_BUDGET,
                        "scenario": SCENARIO,
                    }
                )
    return rows


def holm_adjust(pvalues: list[float]) -> list[float]:
    indexed = sorted(enumerate(pvalues), key=lambda item: item[1])
    adjusted = [1.0] * len(pvalues)
    running = 0.0
    total = len(pvalues)
    for rank, (index, value) in enumerate(indexed):
        running = max(running, min(1.0, (total - rank) * value))
        adjusted[index] = running
    return adjusted


def build_statistics(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    by_key = {key(row): row for row in rows}
    summary: list[dict[str, Any]] = []
    ranks: dict[str, list[float]] = {algorithm: [] for algorithm in ALGORITHMS}
    for instance in INSTANCES:
        instance_rows = [row for row in rows if row["instance"] == instance]
        means: dict[str, float] = {}
        for algorithm in ALGORITHMS:
            group = [row for row in instance_rows if row["algorithm"] == algorithm]
            costs = [float(row["best_cost"]) for row in group]
            runtimes = [float(row["elapsed_seconds"]) for row in group]
            best = min(costs)
            avg = statistics.fmean(costs)
            means[algorithm] = avg
            summary.append(
                {
                    "instance": instance,
                    "algorithm": algorithm,
                    "independent_runs": len(group),
                    "best_cost": best,
                    "avg_cost": avg,
                    "std_cost": statistics.stdev(costs) if len(costs) > 1 else 0.0,
                    "worst_cost": max(costs),
                    "feasible_rate": statistics.fmean(1.0 if str(row.get("gate_status")) == "OK" else 0.0 for row in group),
                    "avg_runtime_seconds": statistics.fmean(runtimes),
                }
            )
        levels = sorted(set(means.values()))
        for algorithm, value in means.items():
            ranks[algorithm].append(float(levels.index(value) + 1))

    algorithm_summary = []
    for algorithm in ALGORITHMS:
        items = [row for row in summary if row["algorithm"] == algorithm]
        algorithm_summary.append(
            {
                "algorithm": algorithm,
                "instances": len(items),
                "runs": sum(int(row["independent_runs"]) for row in items),
                "sum_of_instance_avg_costs": sum(float(row["avg_cost"]) for row in items),
                "mean_rank_by_instance_avg": statistics.fmean(ranks[algorithm]),
                "best_instance_avg_count": sum(rank == 1.0 for rank in ranks[algorithm]),
                "mean_runtime_seconds": statistics.fmean(float(row["avg_runtime_seconds"]) for row in items),
            }
        )

    tests = []
    raw_pvalues = []
    try:
        from scipy.stats import wilcoxon
    except Exception:
        wilcoxon = None
    for baseline in BASELINES:
        primary_costs = [float(by_key[(instance, PRIMARY, seed)]["best_cost"]) for instance in INSTANCES for seed in SEEDS]
        baseline_costs = [float(by_key[(instance, baseline, seed)]["best_cost"]) for instance in INSTANCES for seed in SEEDS]
        gains = [100.0 * (right - left) / right for left, right in zip(primary_costs, baseline_costs)]
        if wilcoxon is None or all(abs(left - right) <= 1e-12 for left, right in zip(primary_costs, baseline_costs)):
            statistic, pvalue = math.nan, 1.0
        else:
            result = wilcoxon(primary_costs, baseline_costs, alternative="two-sided", zero_method="wilcox")
            statistic, pvalue = float(result.statistic), float(result.pvalue)
        raw_pvalues.append(pvalue)
        tests.append(
            {
                "primary": PRIMARY,
                "baseline": baseline,
                "pairs": len(gains),
                "wins": sum(value > 1e-9 for value in gains),
                "ties": sum(abs(value) <= 1e-9 for value in gains),
                "losses": sum(value < -1e-9 for value in gains),
                "mean_gain_pct": statistics.fmean(gains),
                "median_gain_pct": statistics.median(gains),
                "wilcoxon_statistic": statistic,
                "wilcoxon_p_raw": pvalue,
            }
        )
    for row, adjusted in zip(tests, holm_adjust(raw_pvalues)):
        row["wilcoxon_p_holm"] = adjusted
    return summary, algorithm_summary, tests


def verify_solutions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    bundles = {instance: load_search_bundle(REPO_ROOT / f"models/data_bundle/generated_instances/L-main/{instance}") for instance in INSTANCES}
    prices = closure.prices_for_scenario(SCENARIO)
    for row in rows:
        payload = json.loads(str(row.get("solution_json", "{}")) or "{}")
        solution = solution_from_dict(payload)
        bundle = bundles[str(row["instance"])]
        violations = check_solution(solution, bundle.instance, prices)
        metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
        recorded = float(row["best_cost"])
        recomputed = float(metrics["total_cost"])
        results.append(
            {
                "run_id": row["run_id"],
                "instance": row["instance"],
                "algorithm": row["algorithm"],
                "seed": row["seed"],
                "violation_count": len(violations),
                "recorded_cost": recorded,
                "recomputed_cost": recomputed,
                "absolute_cost_difference": abs(recorded - recomputed),
                "ok": len(violations) == 0 and abs(recorded - recomputed) <= 1e-6,
            }
        )
    return results


def closeout(output: Path) -> dict[str, Any]:
    phase_dir = output / "formal"
    rows = closure.read_csv(phase_dir / "raw_runs.csv")
    expected = len(INSTANCES) * len(ALGORITHMS) * len(SEEDS)
    matrix_ok = (
        len(rows) == expected
        and len({key(row) for row in rows}) == expected
        and all(row.get("gate_status") == "OK" for row in rows)
        and all(int(float(row.get("actual_evals", -1))) == EVAL_BUDGET for row in rows)
        and all(int(float(row.get("violation_count", -1))) == 0 for row in rows)
    )
    if not matrix_ok:
        decision = {"verdict": "HALT_E2_10SEED_MATRIX_INCOMPLETE", "observed_rows": len(rows), "expected_rows": expected}
        closure.write_json(phase_dir / "decision.json", decision)
        return decision
    verification = verify_solutions(rows)
    summary, algorithm_summary, tests = build_statistics(rows)
    closure.write_csv(phase_dir / "solution_recalculation.csv", verification)
    closure.write_csv(phase_dir / "table_algorithm_by_instance.csv", summary)
    closure.write_csv(phase_dir / "algorithm_summary.csv", algorithm_summary)
    closure.write_csv(phase_dir / "paired_wilcoxon.csv", tests)
    primary_summary = next(row for row in algorithm_summary if row["algorithm"] == PRIMARY)
    ordered = sorted(algorithm_summary, key=lambda row: (float(row["sum_of_instance_avg_costs"]), float(row["mean_rank_by_instance_avg"])))
    all_recomputed = all(bool(row["ok"]) for row in verification)
    verdict = "E2_10SEED_PRIMARY_LEAD_SUPPORTED" if all_recomputed and ordered[0]["algorithm"] == PRIMARY else "E2_10SEED_COMPLETE_PRIMARY_NOT_FIRST" if all_recomputed else "HALT_E2_10SEED_RECALCULATION"
    decision = {
        "schema": "resetp.e2-10seed-closeout.v1",
        "verdict": verdict,
        "matrix_rows": len(rows),
        "instances": len(INSTANCES),
        "algorithms": len(ALGORITHMS),
        "independent_runs_per_algorithm_instance": len(SEEDS),
        "eval_budget": EVAL_BUDGET,
        "zero_violation_rows": sum(int(float(row.get("violation_count", -1))) == 0 for row in rows),
        "recalculation_ok_rows": sum(bool(row["ok"]) for row in verification),
        "ranking_by_sum_of_instance_averages": [row["algorithm"] for row in ordered],
        "primary_sum_of_instance_avg_costs": primary_summary["sum_of_instance_avg_costs"],
        "primary_mean_rank": primary_summary["mean_rank_by_instance_avg"],
        "current_table_rule": "Self-created L-main reports ten-run mean, standard deviation, best, runtime, feasibility, and pairwise statistics; no BKS/Gap table.",
        "standard_benchmark_status": "DEFERRED_POST_E2_WITH_UNMODIFIED_GOEKE_REFERENCE",
        "old_alns_included": False,
        "charging_ablation_in_e2_table": False,
        "execution_commit": FREEZE_COMMIT,
        "harness_commit": execution_head(REPO_ROOT),
    }
    closure.write_json(phase_dir / "decision.json", decision)
    report = [
        "# E2十次运行最终收口",
        "",
        f"判决：`{verdict}`。",
        "",
        f"九个自有算例、九个算法、每组十次，共{len(rows)}行；全部4000评价、零违规并完成成本复算。",
        f"按九个算例平均成本之和排序，顺序为：{' > '.join(row['algorithm'] for row in ordered)}。",
        "自有L-main当前报告十次运行的均值、波动、最好值、时间、可行率和配对统计，不套BKS/Gap表。",
        "公开标准算例的BKS、AVG、Gap%补实验留到E2之后，拟使用未经改动的Goeke原始算法。",
    ]
    (phase_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    solution_dir = phase_dir / "solutions"
    solution_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        closure.write_json(solution_dir / f"{row['run_id']}.json", json.loads(str(row["solution_json"])))
    closure.write_hashes(phase_dir)
    return decision


def main() -> int:
    args = parse_args()
    output = args.output_dir.resolve()
    execution_root = args.execution_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    validate_execution_root(execution_root)
    contract = load_submission_contract(args.contract, repo_root=REPO_ROOT, require_frozen=True, lane=E2_LANE)
    contract_hash = sha256(args.contract)
    reused_main, reused_ablation = frozen_rows()
    gate_main, gate_ablation = gate_rows(output)

    if args.phase == "manifest":
        manifest = manifest_rows(reused_main, gate_main)
        closure.write_csv(output / "task_manifest.csv", manifest)
        decision = {
            "verdict": "E2_10SEED_MANIFEST_READY",
            "logical_rows": len(manifest),
            "reused_rows": sum(row["action"] == "REUSE" for row in manifest),
            "new_search_tasks": sum(row["action"] == "RUN" for row in manifest),
            "algorithms": list(ALGORITHMS),
            "contract_id": contract["contract_id"],
            "contract_sha256": contract_hash,
            "execution_commit": FREEZE_COMMIT,
            "harness_commit": execution_head(REPO_ROOT),
            "workers_default": 2,
        }
        closure.write_json(output / "decision.json", decision)
        closure.write_json(output / "metadata.json", {"schema": "resetp.e2-10seed-metadata.v1", **decision})
        (output / "report.md").write_text(
            "# E2十次运行任务单\n\n大白话：旧ALNS和立即充电消融不参赛。主算法与八个健康基线在九个自有算例上各跑十次；已有合格行复用，只补缺口。\n",
            encoding="utf-8",
        )
        closure.write_hashes(output)
        print(json.dumps(decision, ensure_ascii=False, indent=2))
        return 0

    if args.phase == "verify":
        decision = closeout(output)
        print(json.dumps(decision, ensure_ascii=False, indent=2))
        return 0 if not str(decision["verdict"]).startswith("HALT") else 2

    if args.phase == "smoke":
        phase_dir = output / "smoke"
        instances, seeds, budget, representative = (INSTANCES[2], INSTANCES[4], INSTANCES[7]), (6,), 200, False
        starting_main = [row for row in closure.read_csv(phase_dir / "raw_runs.csv") if reusable_main_row(row, eval_budget=budget, instances=instances, seeds=seeds)]
        starting_ablation = closure.read_csv(phase_dir / "ablation_rows.csv")
    elif args.phase == "representative":
        phase_dir = output / "representative_gate"
        smoke = closure.read_json(output / "smoke/decision.json")
        if smoke.get("verdict") != "E2_10SEED_SMOKE_READY":
            raise RuntimeError("HALT_E2_10SEED_SMOKE_NOT_READY")
        instances, seeds, budget, representative = (INSTANCES[4], INSTANCES[7]), (6,), EVAL_BUDGET, True
        starting_main = [row for row in closure.read_csv(phase_dir / "raw_runs.csv") if reusable_main_row(row, eval_budget=budget, instances=instances, seeds=seeds)]
        starting_ablation = closure.read_csv(phase_dir / "ablation_rows.csv")
    else:
        phase_dir = output / "formal"
        representative_decision = closure.read_json(output / "representative_gate/decision.json")
        if representative_decision.get("verdict") != "E2_10SEED_REPRESENTATIVE_READY":
            raise RuntimeError("HALT_E2_10SEED_REPRESENTATIVE_NOT_READY")
        instances, seeds, budget, representative = INSTANCES, SEEDS, EVAL_BUDGET, False
        resume_main = [row for row in closure.read_csv(phase_dir / "raw_runs.csv") if reusable_main_row(row, eval_budget=EVAL_BUDGET, instances=INSTANCES, seeds=SEEDS)]
        starting_main = merge_rows(reused_main, gate_main, resume_main)
        starting_ablation = merge_rows(reused_ablation, gate_ablation, closure.read_csv(phase_dir / "ablation_rows.csv"))

    phase_dir.mkdir(parents=True, exist_ok=True)
    tasks = [build_task(execution_root, phase_dir, instance, algorithm, seed, budget) for instance in instances for algorithm in ALGORITHMS for seed in seeds]
    closure.write_csv(
        phase_dir / "task_manifest.csv",
        [{"instance": task["instance"], "algorithm": task["logical_algorithm"], "seed": task["seed"], "eval_budget": task["eval_budget"], "execution_commit": FREEZE_COMMIT} for task in tasks],
    )
    main_rows, ablation_rows = run_tasks(execution_root, phase_dir, tasks, starting_main, starting_ablation, args.workers, args.force)
    expected = len(instances) * len(ALGORITHMS) * len(seeds) if args.phase != "formal" else len(INSTANCES) * len(ALGORITHMS) * len(SEEDS)
    decision = phase_decision(main_rows, expected=expected, eval_budget=budget, representative=representative)
    if args.phase in {"smoke", "representative"}:
        gate_verification = verify_solutions(main_rows)
        closure.write_csv(phase_dir / "solution_recalculation.csv", gate_verification)
        verified_count = sum(bool(row["ok"]) for row in gate_verification)
        decision["current_checker_recalculation_ok_rows"] = verified_count
        if verified_count != expected:
            decision["verdict"] = "HALT_E2_10SEED_CURRENT_CHECKER_RECALCULATION"
    decision.update({"workers": args.workers, "contract_id": contract["contract_id"], "contract_sha256": contract_hash, "harness_commit": execution_head(REPO_ROOT)})
    closure.write_json(phase_dir / "decision.json", decision)
    (phase_dir / "report.md").write_text(
        f"# E2十次运行{args.phase}\n\n判决：`{decision['verdict']}`。大白话：这一关只检查入口、预算、可行性和真实搜索活性，不根据谁赢谁输筛结果。\n",
        encoding="utf-8",
    )
    closure.write_hashes(phase_dir)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if not str(decision["verdict"]).startswith("HALT") else 2


if __name__ == "__main__":
    raise SystemExit(main())
