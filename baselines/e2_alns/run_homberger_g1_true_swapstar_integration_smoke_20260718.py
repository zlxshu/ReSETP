#!/usr/bin/env python3
"""Exercise the default-off true-SWAP* kernel integration on one dev run."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np


REPO = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO / "solver/src"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

from baselines.e2_alns.run_homberger_g1_sisr_20260718 import (  # noqa: E402
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
    / "baselines/e2_alns/homberger_g1_true_swapstar_integration_smoke_20260718"
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
INSTANCE = "C1_2_1"
SEED = 1
BUDGET = 160
TOL = 1e-8


def execute() -> dict:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise DevelopmentGateError(f"output directory is not empty: {OUTPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source_rows = frozen_checkpoints()
    contract = bundle_contract(INSTANCE)
    initial, initial_hash, initial_recompute = verify_checkpoint(
        INSTANCE,
        source_rows[(INSTANCE, SEED)],
        contract=contract,
    )
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
    flags[TRUE_SWAPSTAR_FLAG] = "1"
    flags[TRACE_DIAGNOSTIC_FLAG] = "1"
    started_at = datetime.now(timezone.utc).isoformat()
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
    finished_at = datetime.now(timezone.utc).isoformat()
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
    structural = run.operator_counts.get("structural", {})
    trace = run.operator_counts.get("candidate_trace", [])
    swapstar_trace = [
        row for row in trace if row.get("true_swapstar_attempted")
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
    if swapstar_evaluations <= 0 or not swapstar_trace:
        failures.append("TRUE_SWAPSTAR_NOT_ACTIVATED")
    if elapsed > 301.0:
        failures.append("TIMEOUT")
    verdict = (
        "PASS_TRUE_SWAPSTAR_KERNEL_INTEGRATION_SMOKE"
        if not failures
        else "HOLD_TRUE_SWAPSTAR_KERNEL_INTEGRATION"
    )
    solution_path = OUTPUT / "solution.json"
    atomic_json(solution_path, solution_payload(run.best_solution))
    row = {
        "instance": INSTANCE,
        "seed": SEED,
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
        "true_swapstar_accepted_count": sum(
            int(item.get("true_swapstar_accepted_move_count", 0))
            for item in swapstar_trace
        ),
        "structural_counts": structural,
        "score_counts": score_counts,
        "swapstar_trace": swapstar_trace,
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
    decision = {
        "verdict": verdict,
        "failures": failures,
        "default_flag_remains_off": e2_alns_variant_flags()[
            TRUE_SWAPSTAR_FLAG
        ]
        == "0",
        "budget_exact": (
            run.evaluations == BUDGET and run.candidate_scores == BUDGET
        ),
        "true_swapstar_activated": swapstar_evaluations > 0,
        "true_swapstar_evaluations": swapstar_evaluations,
        "true_swapstar_trace_count": len(swapstar_trace),
        "full_g1_executed": False,
        "performance_claim_allowed": False,
        "next_gate": (
            "12x3x1600_G1_only_after_review"
            if verdict == "PASS_TRUE_SWAPSTAR_KERNEL_INTEGRATION_SMOKE"
            else "repair_integration_without_expanding_budget"
        ),
    }
    metadata = {
        "schema_version": (
            "resetp.e2.homberger-g1-true-swapstar-integration-smoke.v1"
        ),
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "git_head": git_output("rev-parse", "HEAD"),
        "git_branch": git_output("branch", "--show-current"),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "source_gate": str(SOURCE_GATE.relative_to(REPO)),
        "source_gate_decision_sha256": sha256(
            SOURCE_GATE / "decision.json"
        ),
        "search_evaluations": BUDGET,
    }
    task_contract = {
        "task_card": str(TASK_CARD.relative_to(REPO)),
        "purpose": "activation_and_budget_accounting_only",
        "instance": INSTANCE,
        "seed": SEED,
        "budget": BUDGET,
        "trigger": (
            "late_25_percent_and_3x_structural_interval_without_best_improvement"
        ),
        "max_true_swapstar_evaluations_per_trigger": 4,
        "performance_comparison": False,
        "implicit_full_g1_launch": False,
    }
    atomic_json(OUTPUT / "metadata.json", metadata)
    atomic_json(OUTPUT / "task_contract.json", task_contract)
    atomic_csv(OUTPUT / "raw_runs.csv", [row])
    atomic_json(OUTPUT / "decision.json", decision)
    atomic_text(
        OUTPUT / "report.md",
        "\n".join(
            [
                "# 真正 SWAP* winner-kernel 接入冒烟门",
                "",
                f"- 判定：`{verdict}`",
                f"- 总完整评价：{run.evaluations}/{BUDGET}",
                f"- SWAP* 完整评价：{swapstar_evaluations}",
                f"- SWAP* 触发记录：{len(swapstar_trace)}",
                f"- 独立复算：{recompute['passed']}",
                f"- 运行时间：{elapsed:.3f}s",
                "",
                "本门只证明默认关闭的晚期停滞接入能触发且进入统一预算；"
                "它不是性能比较，也没有运行完整 G1。",
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
        OUTPUT / "decision.json",
        OUTPUT / "report.md",
        solution_path,
    ]
    hashes = {
        str(path.relative_to(REPO)): sha256(path)
        for path in paths
        if path.is_file()
    }
    atomic_json(OUTPUT / "artifact_hashes.json", hashes)
    clean_generated_appledouble(OUTPUT)
    return decision


def main() -> int:
    decision = execute()
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
