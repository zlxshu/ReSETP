#!/usr/bin/env python3
"""Run the minimum paired R-instance integration risk gate for true SWAP*."""

from __future__ import annotations

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
    git_output,
    independent_vrptw_recompute,
    sha256,
    solution_payload,
    vrptw_prices,
)
from baselines.e2_alns.run_homberger_g1_true_swapstar_micro_20260718 import (  # noqa: E402
    SOURCE_GATE,
    frozen_checkpoints,
    verify_checkpoint,
)
from setp_solver.algorithms.resetp_alns.kernel.alns_core import (  # noqa: E402
    SearchPolicy,
)
from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    TRACE_DIAGNOSTIC_FLAG,
    TRUE_SWAPSTAR_FLAG,
    WinnerKernelConfig,
    _run_winner_kernel_loop,
    e2_alns_variant_flags,
)
from setp_solver.check import check_solution  # noqa: E402


OUTPUT = (
    REPO
    / "baselines/e2_alns"
    / "homberger_g1_true_swapstar_risk_gate_20260718"
)
TASK_CARD = (
    REPO / "docs/handoff/e2_alns_g1_true_swapstar_task_card_20260718.md"
)
WINNER_SOURCE = (
    REPO / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py"
)
OPERATOR_SOURCE = (
    REPO
    / "solver/src/setp_solver/algorithms/resetp_alns/operators/true_swapstar.py"
)
RUNNER_SOURCE = Path(__file__).resolve()
INSTANCE = "R1_2_8"
SEED = 1
BUDGET = 160
MAX_DISTANCE_DEGRADATION_PCT = 2.0
MAX_TIME_OVERHEAD_PCT = 25.0
TOL = 1e-8


def run_arm(
    *,
    arm: str,
    initial: Any,
    initial_hash: str,
    initial_recompute: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[dict[str, Any], Any]:
    bundle = contract["bundle"]
    prices = vrptw_prices(
        capacity=contract["capacity"],
        big_m=contract["big_m"],
    )
    policy = SearchPolicy(
        require_charging_signal=False,
        max_cv=contract["max_vehicles"],
        max_ev=0,
        allow_cross_depot=False,
        enable_cross_depot_operator=False,
    )
    flags = e2_alns_variant_flags()
    if flags[TRUE_SWAPSTAR_FLAG] != "0":
        raise DevelopmentGateError("true SWAP* must remain default off")
    if arm == "candidate_true_swapstar":
        flags[TRUE_SWAPSTAR_FLAG] = "1"
        flags[TRACE_DIAGNOSTIC_FLAG] = "1"
    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    run = _run_winner_kernel_loop(
        initial,
        bundle.instance,
        bundle.carbon_profile,
        config=WinnerKernelConfig(
            seed=SEED,
            eval_budget=BUDGET,
            max_runtime_seconds=300.0,
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
    expected_objective = (
        float(contract["big_m"]) * int(recompute["route_count"])
        + float(recompute["distance_double"])
    )
    score_counts = run.operator_counts.get("score_counts", {})
    trace = run.operator_counts.get("candidate_trace", [])
    swapstar_trace = [
        item for item in trace if item.get("true_swapstar_attempted")
    ]
    swapstar_evaluations = int(
        score_counts.get("candidate_channel:true_swapstar", 0)
    )
    failures: list[str] = []
    if run.evaluations != BUDGET or run.candidate_scores != BUDGET:
        failures.append("INVALID_EVALUATION_COUNT")
    if not run.feasible or not recompute["passed"] or violations:
        failures.append("INFEASIBLE")
    if abs(float(run.best_obj) - expected_objective) > TOL:
        failures.append("OBJECTIVE_MISMATCH")
    if arm == "candidate_true_swapstar" and (
        swapstar_evaluations <= 0 or not swapstar_trace
    ):
        failures.append("TRUE_SWAPSTAR_NOT_ACTIVATED")
    row = {
        "instance": INSTANCE,
        "seed": SEED,
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
        "objective": float(run.best_obj),
        "expected_objective": expected_objective,
        "true_swapstar_evaluations": swapstar_evaluations,
        "true_swapstar_trace_count": len(swapstar_trace),
        "true_swapstar_accepted_move_count": sum(
            int(item.get("true_swapstar_accepted_move_count", 0))
            for item in swapstar_trace
        ),
        "structural_counts": run.operator_counts.get("structural", {}),
        "score_counts": score_counts,
        "elapsed_seconds": elapsed,
        "process_cpu_seconds": cpu_seconds,
        "independent_recompute_pass": bool(recompute["passed"]),
        "model_violation_count": len(violations),
        "failure_codes": failures,
        "status": "OK" if not failures else "FAIL",
        "solution_sha256": canonical_sha256(
            solution_payload(run.best_solution)
        ),
    }
    return row, run.best_solution


def main() -> int:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise DevelopmentGateError(f"output directory is not empty: {OUTPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    contract = bundle_contract(INSTANCE)
    checkpoints = frozen_checkpoints()
    initial, initial_hash, initial_recompute = verify_checkpoint(
        INSTANCE,
        checkpoints[(INSTANCE, SEED)],
        contract=contract,
    )
    rows: list[dict[str, Any]] = []
    solution_paths: list[Path] = []
    for arm in ("baseline", "candidate_true_swapstar"):
        row, solution = run_arm(
            arm=arm,
            initial=initial,
            initial_hash=initial_hash,
            initial_recompute=initial_recompute,
            contract=contract,
        )
        path = OUTPUT / f"solution__{arm}.json"
        atomic_json(path, solution_payload(solution))
        row["solution_path"] = str(path.relative_to(REPO))
        rows.append(row)
        solution_paths.append(path)
    baseline, candidate = rows
    if baseline["route_count"] == candidate["route_count"]:
        improvement_pct = (
            (
                float(baseline["distance_double"])
                - float(candidate["distance_double"])
            )
            / float(baseline["distance_double"])
            * 100.0
        )
    else:
        improvement_pct = None
    overhead_pct = (
        (
            float(candidate["elapsed_seconds"])
            - float(baseline["elapsed_seconds"])
        )
        / float(baseline["elapsed_seconds"])
        * 100.0
    )
    failures = list(baseline["failure_codes"]) + list(
        candidate["failure_codes"]
    )
    if candidate["initial_solution_sha256"] != baseline[
        "initial_solution_sha256"
    ]:
        failures.append("COMMON_START_MISMATCH")
    if int(candidate["route_count"]) > int(baseline["route_count"]):
        failures.append("ROUTE_COUNT_DEGRADATION")
    if (
        improvement_pct is not None
        and improvement_pct < -MAX_DISTANCE_DEGRADATION_PCT
    ):
        failures.append("DISTANCE_DEGRADATION_OVER_2PCT")
    if overhead_pct > MAX_TIME_OVERHEAD_PCT:
        failures.append("TIME_OVERHEAD_OVER_25PCT")
    failures = sorted(set(failures))
    verdict = (
        "PASS_TRUE_SWAPSTAR_RISK_GATE"
        if not failures
        else "HOLD_TRUE_SWAPSTAR_BEFORE_FORMAL_G1"
    )
    comparison = {
        "instance": INSTANCE,
        "seed": SEED,
        "common_start_sha256": initial_hash,
        "baseline_route_count": baseline["route_count"],
        "candidate_route_count": candidate["route_count"],
        "baseline_distance_double": baseline["distance_double"],
        "candidate_distance_double": candidate["distance_double"],
        "candidate_improvement_pct": improvement_pct,
        "elapsed_overhead_pct": overhead_pct,
        "true_swapstar_evaluations": candidate[
            "true_swapstar_evaluations"
        ],
    }
    decision = {
        "verdict": verdict,
        "failures": failures,
        "comparison": comparison,
        "performance_claim_allowed": False,
        "full_g1_executed": False,
        "formal_g1_automatic_launch": False,
        "next_gate": (
            "human_review_before_12x3x1600_formal_G1"
            if not failures
            else "repair_or_kill_before_any_formal_G1"
        ),
    }
    metadata = {
        "schema_version": (
            "resetp.e2.homberger-g1-true-swapstar-risk-gate.v1"
        ),
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git_output("rev-parse", "HEAD"),
        "git_branch": git_output("branch", "--show-current"),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "source_gate": str(SOURCE_GATE.relative_to(REPO)),
        "source_gate_decision_sha256": sha256(
            SOURCE_GATE / "decision.json"
        ),
        "total_search_evaluations": 2 * BUDGET,
    }
    task_contract = {
        "purpose": "minimum_random_instance_integration_risk_screen",
        "pre_registered_instance": INSTANCE,
        "pre_registered_seed": SEED,
        "arms": ["baseline", "candidate_true_swapstar"],
        "budget_per_arm": BUDGET,
        "common_frozen_checkpoint": True,
        "kill_or_hold_thresholds": {
            "route_count_increase": 0,
            "distance_degradation_pct": MAX_DISTANCE_DEGRADATION_PCT,
            "elapsed_overhead_pct": MAX_TIME_OVERHEAD_PCT,
        },
        "single_seed_performance_claim": False,
        "implicit_full_g1_launch": False,
    }
    atomic_json(OUTPUT / "metadata.json", metadata)
    atomic_json(OUTPUT / "task_contract.json", task_contract)
    atomic_csv(OUTPUT / "raw_runs.csv", rows)
    atomic_json(OUTPUT / "paired_result.json", comparison)
    atomic_json(OUTPUT / "decision.json", decision)
    atomic_text(
        OUTPUT / "report.md",
        "\n".join(
            [
                "# 真正 SWAP* 的 R 类最小集成风险门",
                "",
                f"- 判定：`{verdict}`",
                f"- 路线数：{baseline['route_count']} → "
                f"{candidate['route_count']}",
                f"- 距离改善：{improvement_pct:.6f}%"
                if improvement_pct is not None
                else "- 距离改善：路线数不同，不作同层比较",
                f"- 计时时间差：{overhead_pct:.3f}%",
                f"- SWAP* 完整评价："
                f"{candidate['true_swapstar_evaluations']}",
                "",
                "这是一个预注册单实例、单种子排雷门，只排除明显的 R 类"
                "集成风险；它不支持性能结论，也不会自动启动正式 G1。",
                "",
            ]
        ),
    )
    clean_generated_appledouble(OUTPUT)
    paths = [
        TASK_CARD,
        WINNER_SOURCE,
        OPERATOR_SOURCE,
        RUNNER_SOURCE,
        OUTPUT / "metadata.json",
        OUTPUT / "task_contract.json",
        OUTPUT / "raw_runs.csv",
        OUTPUT / "paired_result.json",
        OUTPUT / "decision.json",
        OUTPUT / "report.md",
        *solution_paths,
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
