#!/usr/bin/env python3
"""Run the bounded four-instance Homberger G1a gate for true SWAP*."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys
import time
from typing import Any

import numpy as np


REPO = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO / "solver/src"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

from baselines.e2_alns.homberger_g1_helpers_20260718 import (  # noqa: E402
    DevelopmentGateError,
    atomic_csv,
    atomic_json,
    atomic_text,
    bundle_contract,
    canonical_sha256,
    clean_generated_appledouble,
    deterministic_common_initial_solution,
    git_output,
    independent_vrptw_recompute,
    sha256,
    solution_payload,
    vrptw_prices,
)
from setp_solver.algorithms.resetp_alns.kernel.alns_core import (  # noqa: E402
    SearchPolicy,
)
from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    TRUE_SWAPSTAR_FLAG,
    WinnerKernelConfig,
    _run_winner_kernel_loop,
    e2_alns_variant_flags,
)
from setp_solver.check import check_solution  # noqa: E402


OUTPUT = (
    REPO / "baselines/e2_alns/homberger_g1a_true_swapstar_20260718"
)
TASK_CARD = (
    REPO / "docs/handoff/e2_alns_g1a_true_swapstar_contract_20260718.md"
)
WINNER_SOURCE = (
    REPO / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py"
)
OPERATOR_SOURCE = (
    REPO
    / "solver/src/setp_solver/algorithms/resetp_alns/operators/true_swapstar.py"
)
RUNNER_SOURCE = Path(__file__).resolve()
INSTANCES = ("C1_2_1", "C2_2_8", "R1_2_8", "RC2_2_8")
SEEDS = (1, 2, 3)
BUDGET = 400
WORKERS = 6
MAX_RUNTIME_SECONDS = 900.0
TOL = 1e-8


def run_arm(task: tuple[int, str, int, str]) -> dict[str, Any]:
    task_index, name, seed, arm = task
    contract = bundle_contract(name)
    bundle = contract["bundle"]
    prices = vrptw_prices(
        capacity=contract["capacity"],
        big_m=contract["big_m"],
    )
    initial = deterministic_common_initial_solution(
        bundle.instance,
        capacity=contract["capacity"],
    )
    initial_payload = solution_payload(initial)
    initial_hash = canonical_sha256(initial_payload)
    initial_recompute = independent_vrptw_recompute(
        initial,
        bundle=bundle,
        capacity=contract["capacity"],
    )
    initial_violations = check_solution(initial, bundle.instance, prices)
    if not initial_recompute["passed"] or initial_violations:
        raise DevelopmentGateError(
            f"common initial solution is infeasible: {name}"
        )
    flags = e2_alns_variant_flags()
    if flags[TRUE_SWAPSTAR_FLAG] != "0":
        raise DevelopmentGateError("true SWAP* must remain default off")
    if arm == "candidate_true_swapstar":
        flags[TRUE_SWAPSTAR_FLAG] = "1"
    policy = SearchPolicy(
        require_charging_signal=False,
        max_cv=contract["max_vehicles"],
        max_ev=0,
        allow_cross_depot=False,
        enable_cross_depot_operator=False,
    )
    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    run = _run_winner_kernel_loop(
        initial,
        bundle.instance,
        bundle.carbon_profile,
        config=WinnerKernelConfig(
            seed=seed,
            eval_budget=BUDGET,
            max_runtime_seconds=MAX_RUNTIME_SECONDS,
        ),
        prices=prices,
        variant_flags=flags,
        policy=policy,
        carbon_weight=0.0,
        carbon_quota_kg=float("inf"),
    )
    elapsed = time.perf_counter() - wall_started
    cpu_seconds = time.process_time() - cpu_started
    recompute = independent_vrptw_recompute(
        run.best_solution,
        bundle=bundle,
        capacity=contract["capacity"],
    )
    violations = check_solution(run.best_solution, bundle.instance, prices)
    expected_score = (
        float(contract["big_m"]) * int(recompute["route_count"])
        + float(recompute["distance_double"])
    )
    score_counts = run.operator_counts.get("score_counts", {})
    true_evaluations = int(
        score_counts.get("candidate_channel:true_swapstar", 0)
    )
    failures: list[str] = []
    if run.evaluations != BUDGET:
        failures.append("INVALID_EVALUATION_COUNT")
    if run.candidate_scores != BUDGET:
        failures.append("INVALID_CANDIDATE_SCORE_COUNT")
    if not run.feasible or not recompute["passed"] or violations:
        failures.append("INFEASIBLE")
    if abs(float(run.best_obj) - expected_score) > TOL:
        failures.append("OBJECTIVE_MISMATCH")
    if elapsed > MAX_RUNTIME_SECONDS + 1.0:
        failures.append("TIMEOUT")
    payload = solution_payload(run.best_solution)
    solution_path = (
        OUTPUT
        / "solutions"
        / f"{name}__seed{seed}__budget{BUDGET}__{arm}.json"
    )
    atomic_json(solution_path, payload)
    return {
        "task_index": task_index,
        "instance": name,
        "class": name.split("_", maxsplit=1)[0],
        "geometry_family": name.split("_", maxsplit=1)[0].rstrip("12"),
        "seed": seed,
        "arm": arm,
        "eval_budget": BUDGET,
        "evaluations": int(run.evaluations),
        "candidate_scores": int(run.candidate_scores),
        "initial_solution_sha256": initial_hash,
        "initial_route_count": int(initial_recompute["route_count"]),
        "initial_distance_double": float(
            initial_recompute["distance_double"]
        ),
        "route_count": int(recompute["route_count"]),
        "distance_double": float(recompute["distance_double"]),
        "lexicographic_score": expected_score,
        "algorithm_best_obj": float(run.best_obj),
        "true_swapstar_evaluations": true_evaluations,
        "true_swapstar_attempts": int(
            run.operator_counts.get("structural", {}).get("attempts", 0)
        ),
        "elapsed_seconds": elapsed,
        "process_cpu_seconds": cpu_seconds,
        "independent_recompute_pass": bool(recompute["passed"]),
        "model_violation_count": len(violations),
        "failure_codes": failures,
        "status": "OK" if not failures else "FAIL",
        "solution_sha256": canonical_sha256(payload),
        "solution_path": str(solution_path.relative_to(REPO)),
        "score_counts": score_counts,
        "structural_counts": run.operator_counts.get("structural", {}),
        "bundle_hashes": contract["bundle_hashes"],
    }


def paired_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(
            (str(row["instance"]), int(row["seed"])),
            {},
        )[str(row["arm"])] = row
    pairs: list[dict[str, Any]] = []
    for (name, seed), arms in sorted(grouped.items()):
        if set(arms) != {"baseline", "candidate_true_swapstar"}:
            continue
        baseline = arms["baseline"]
        candidate = arms["candidate_true_swapstar"]
        baseline_score = float(baseline["lexicographic_score"])
        candidate_score = float(candidate["lexicographic_score"])
        improvement = (
            (baseline_score - candidate_score) / baseline_score * 100.0
        )
        overhead = (
            (
                float(candidate["elapsed_seconds"])
                - float(baseline["elapsed_seconds"])
            )
            / float(baseline["elapsed_seconds"])
            * 100.0
        )
        pairs.append(
            {
                "instance": name,
                "class": baseline["class"],
                "geometry_family": baseline["geometry_family"],
                "seed": seed,
                "eval_budget": BUDGET,
                "common_initial_solution": (
                    baseline["initial_solution_sha256"]
                    == candidate["initial_solution_sha256"]
                ),
                "baseline_route_count": baseline["route_count"],
                "candidate_route_count": candidate["route_count"],
                "baseline_distance_double": baseline["distance_double"],
                "candidate_distance_double": candidate["distance_double"],
                "baseline_score": baseline_score,
                "candidate_score": candidate_score,
                "improvement_pct": improvement,
                "elapsed_overhead_pct": overhead,
                "true_swapstar_evaluations": candidate[
                    "true_swapstar_evaluations"
                ],
            }
        )
    return pairs


def decide(
    rows: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    failures = [
        f"{row['instance']}:{row['seed']}:{row['arm']}:{code}"
        for row in rows
        for code in row["failure_codes"]
    ]
    common_starts = all(pair["common_initial_solution"] for pair in pairs)
    improvements = [float(pair["improvement_pct"]) for pair in pairs]
    overheads = [float(pair["elapsed_overhead_pct"]) for pair in pairs]
    active_families = sorted(
        {
            str(pair["geometry_family"])
            for pair in pairs
            if int(pair["true_swapstar_evaluations"]) > 0
        }
    )
    mean_improvement = float(np.mean(improvements))
    nondegrade = sum(value >= -TOL for value in improvements)
    worst = min(improvements)
    mean_overhead = float(np.mean(overheads))
    passed = (
        not failures
        and len(rows) == 24
        and len(pairs) == 12
        and common_starts
        and {"C", "R", "RC"}.issubset(set(active_families))
        and mean_improvement > 0.0
        and nondegrade >= 8
        and worst >= -2.0
        and mean_overhead <= 25.0
    )
    return {
        "verdict": (
            "PASS_G1A_TRUE_SWAPSTAR_PROMOTE_TO_FULL_G1"
            if passed
            else "STOP_TRUE_SWAPSTAR_BEFORE_FULL_G1"
        ),
        "failures": failures,
        "task_count": len(rows),
        "pair_count": len(pairs),
        "common_starts": common_starts,
        "active_geometry_families": active_families,
        "mean_improvement_pct": mean_improvement,
        "nondegrade_count": nondegrade,
        "worst_improvement_pct": worst,
        "mean_elapsed_overhead_pct": mean_overhead,
        "full_g1_executed": False,
        "performance_claim_allowed": False,
        "next_gate": (
            "12x3x1600_full_G1"
            if passed
            else "close_true_swapstar_candidate"
        ),
    }


def report_text(
    decision: dict[str, Any],
    pairs: list[dict[str, Any]],
) -> str:
    lines = [
        "# Homberger G1a 真正 SWAP* 顺序门",
        "",
        f"判定：`{decision['verdict']}`",
        "",
        f"- 任务：{decision['task_count']}/24",
        f"- 配对：{decision['pair_count']}/12",
        f"- 活跃几何族：{decision['active_geometry_families']}",
        f"- 平均改善：{decision['mean_improvement_pct']:.6f}%",
        f"- 不退化：{decision['nondegrade_count']}/12",
        f"- 最差改善：{decision['worst_improvement_pct']:.6f}%",
        f"- 平均计时开销：{decision['mean_elapsed_overhead_pct']:.3f}%",
        "",
        "| 实例 | 种子 | 改善% | 路线数 基线→候选 | SWAP*评价 | 时间差% |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for pair in pairs:
        lines.append(
            f"| {pair['instance']} | {pair['seed']} | "
            f"{pair['improvement_pct']:.6f} | "
            f"{pair['baseline_route_count']}→"
            f"{pair['candidate_route_count']} | "
            f"{pair['true_swapstar_evaluations']} | "
            f"{pair['elapsed_overhead_pct']:.3f} |"
        )
    lines.extend(
        [
            "",
            "本门只决定完整G1是否值得运行；不支持性能或论文主张。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise DevelopmentGateError(f"output directory is not empty: {OUTPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    tasks: list[tuple[int, str, int, str]] = []
    for instance_index, name in enumerate(INSTANCES):
        for seed in SEEDS:
            arms = (
                ("baseline", "candidate_true_swapstar")
                if (instance_index + seed) % 2 == 0
                else ("candidate_true_swapstar", "baseline")
            )
            for arm in arms:
                tasks.append((len(tasks), name, seed, arm))
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(run_arm, task): task for task in tasks}
        for future in as_completed(futures):
            rows.append(future.result())
    rows.sort(key=lambda row: int(row["task_index"]))
    pairs = paired_rows(rows)
    decision = decide(rows, pairs)
    metadata = {
        "schema_version": "resetp.e2.homberger-g1a-true-swapstar.v1",
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git_output("rev-parse", "HEAD"),
        "git_diff_sha256": canonical_sha256(
            git_output("diff", "--binary")
        ),
        "python": sys.version,
        "python_executable": sys.executable,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "instances": list(INSTANCES),
        "seeds": list(SEEDS),
        "budget_per_arm": BUDGET,
        "workers": WORKERS,
        "total_search_evaluations": len(tasks) * BUDGET,
        "full_g1_fraction": (len(tasks) * BUDGET) / 115200.0,
    }
    task_contract = {
        "task_card": str(TASK_CARD.relative_to(REPO)),
        "result_blind_matrix": True,
        "instances": list(INSTANCES),
        "seeds": list(SEEDS),
        "arms": ["baseline", "candidate_true_swapstar"],
        "budget_per_arm": BUDGET,
        "common_initial_solution": (
            "earliest_due_time_then_current_distance_then_customer_id"
        ),
        "thresholds": {
            "task_count": 24,
            "pair_count": 12,
            "failure_count": 0,
            "active_geometry_families": ["C", "R", "RC"],
            "mean_improvement_pct_strictly_greater_than": 0.0,
            "nondegrade_minimum": 8,
            "worst_improvement_pct_minimum": -2.0,
            "mean_elapsed_overhead_pct_maximum": 25.0,
        },
        "implicit_parameter_tuning": False,
        "performance_claim": False,
    }
    atomic_json(OUTPUT / "metadata.json", metadata)
    atomic_json(OUTPUT / "task_contract.json", task_contract)
    atomic_csv(OUTPUT / "raw_runs.csv", rows)
    atomic_json(OUTPUT / "paired_results.json", pairs)
    atomic_json(OUTPUT / "decision.json", decision)
    atomic_text(OUTPUT / "report.md", report_text(decision, pairs))
    clean_generated_appledouble(OUTPUT)
    paths = [
        TASK_CARD,
        WINNER_SOURCE,
        OPERATOR_SOURCE,
        RUNNER_SOURCE,
        OUTPUT / "metadata.json",
        OUTPUT / "task_contract.json",
        OUTPUT / "raw_runs.csv",
        OUTPUT / "paired_results.json",
        OUTPUT / "decision.json",
        OUTPUT / "report.md",
        *sorted((OUTPUT / "solutions").glob("*.json")),
    ]
    atomic_json(
        OUTPUT / "artifact_hashes.json",
        {
            str(path.relative_to(REPO)): sha256(path)
            for path in paths
            if path.is_file()
        },
    )
    clean_generated_appledouble(OUTPUT)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
