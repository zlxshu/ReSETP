#!/usr/bin/env python3
"""Run the isolated five-evaluation true-SWAP* marginal gate."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import json
import math
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
from setp_solver.algorithms.resetp_alns.kernel.alns_core import (  # noqa: E402
    SearchPolicy,
)
from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    WinnerKernelConfig,
    _run_winner_kernel_loop,
    e2_alns_variant_flags,
)
from setp_solver.algorithms.resetp_alns.operators.true_swapstar import (  # noqa: E402
    TrueSwapStarConfig,
    true_swapstar_intensify,
)
from setp_solver.algorithms.resetp_alns.runtime.budgeted_scoring import (  # noqa: E402
    score_reference_solution,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.search.evaluation import EvalBudget, EvaluationContext  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)


SOURCE_GATE = (
    REPO / "baselines/e2_alns/homberger_g1_sisr_micro_v2_20260718"
)
DEFAULT_OUTPUT = (
    REPO / "baselines/e2_alns/homberger_g1_true_swapstar_micro_20260718"
)
TASK_CARD = (
    REPO / "docs/handoff/e2_alns_g1_true_swapstar_task_card_20260718.md"
)
OPERATOR_SOURCE = (
    REPO
    / "solver/src/setp_solver/algorithms/resetp_alns/operators/true_swapstar.py"
)
TEST_SOURCE = REPO / "solver/tests/test_true_swapstar_20260718.py"
RUNNER_SOURCE = Path(__file__).resolve()
INSTANCES = ("C1_2_1", "R1_2_8")
SEEDS = (1, 2, 3)
MARGINAL_BUDGET = 5
SMOKE_BUDGETS = (0, 1, 2)
TOL = 1e-8


def load_solution(path: Path) -> Solution:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Solution(
        routes=[Route(**row) for row in payload.get("routes", [])],
        charging_actions=[
            ChargingAction(**row)
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(**row)
            for row in payload.get("cross_site_services", [])
        ],
    )


def frozen_checkpoints() -> dict[tuple[str, int], dict[str, Any]]:
    decision = json.loads(
        (SOURCE_GATE / "decision.json").read_text(encoding="utf-8")
    )
    if decision.get("verdict") != "KILL_COMPONENT_MECHANICAL_FAILURE":
        raise DevelopmentGateError("SISR source gate is not the frozen kill result")
    rows: list[dict[str, Any]] = []
    with (SOURCE_GATE / "raw_runs.csv").open(
        newline="",
        encoding="utf-8",
    ) as handle:
        rows.extend(csv.DictReader(handle))
    selected: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        if (
            row["phase"] == "micro_screen"
            and row["arm"] == "baseline"
            and int(row["eval_budget"]) == 40
            and row["instance"] in INSTANCES
            and int(row["seed"]) in SEEDS
        ):
            if row["status"] != "OK":
                raise DevelopmentGateError(
                    f"source checkpoint is not OK: {row['instance']}:{row['seed']}"
                )
            selected[(row["instance"], int(row["seed"]))] = row
    expected = {(name, seed) for name in INSTANCES for seed in SEEDS}
    if set(selected) != expected:
        raise DevelopmentGateError(
            f"source checkpoint set differs: {sorted(set(selected) ^ expected)}"
        )
    return selected


def verify_checkpoint(
    name: str,
    row: dict[str, Any],
    *,
    contract: dict[str, Any],
) -> tuple[Solution, str, dict[str, Any]]:
    path = REPO / row["solution_path"]
    if not path.is_file():
        raise DevelopmentGateError(f"missing source checkpoint: {path}")
    solution = load_solution(path)
    solution_hash = canonical_sha256(solution_payload(solution))
    if solution_hash != row["solution_sha256"]:
        raise DevelopmentGateError(f"source checkpoint hash differs: {name}")
    recompute = independent_vrptw_recompute(
        solution,
        bundle=contract["bundle"],
        capacity=contract["capacity"],
    )
    if not recompute["passed"]:
        raise DevelopmentGateError(
            f"source checkpoint independent recompute failed: {name}"
        )
    return solution, solution_hash, recompute


def run_baseline_continue(
    *,
    name: str,
    seed: int,
    initial: Solution,
    initial_hash: str,
    initial_recompute: dict[str, Any],
    contract: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
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
    started = time.perf_counter()
    cpu_started = time.process_time()
    run = _run_winner_kernel_loop(
        initial,
        bundle.instance,
        bundle.carbon_profile,
        config=WinnerKernelConfig(
            seed=seed,
            eval_budget=MARGINAL_BUDGET,
            max_runtime_seconds=300.0,
        ),
        prices=prices,
        variant_flags=e2_alns_variant_flags(),
        policy=policy,
        carbon_weight=0.0,
        carbon_quota_kg=float("inf"),
    )
    elapsed = time.perf_counter() - started
    cpu_seconds = time.process_time() - cpu_started
    return _finalize_row(
        name=name,
        seed=seed,
        arm="baseline_continue",
        initial=initial,
        initial_hash=initial_hash,
        initial_recompute=initial_recompute,
        solution=run.best_solution,
        objective=float(run.best_obj),
        evaluations=int(run.evaluations),
        candidate_scores=int(run.candidate_scores),
        elapsed=elapsed,
        cpu_seconds=cpu_seconds,
        contract=contract,
        output=output,
        component_trace={
            "actual_moves": int(run.actual_moves),
            "score_counts": run.operator_counts.get("score_counts", {}),
        },
    )


def run_true_swapstar(
    *,
    name: str,
    seed: int,
    budget: int,
    phase: str,
    initial: Solution,
    initial_hash: str,
    initial_recompute: dict[str, Any],
    contract: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    bundle = contract["bundle"]
    prices = vrptw_prices(
        capacity=contract["capacity"],
        big_m=contract["big_m"],
    )
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        carbon_quota_kg=float("inf"),
        carbon_weight=0.0,
        budget=EvalBudget(limit=budget, target=budget),
        allow_cross_depot=False,
    )
    prepared, initial_objective = score_reference_solution(
        initial,
        context,
        phase=f"{phase}_initial",
    )
    started = time.perf_counter()
    cpu_started = time.process_time()
    result = true_swapstar_intensify(
        prepared,
        context,
        incumbent_objective=initial_objective,
        max_evaluations=budget,
        config=TrueSwapStarConfig(),
    )
    elapsed = time.perf_counter() - started
    cpu_seconds = time.process_time() - cpu_started
    return _finalize_row(
        name=name,
        seed=seed,
        arm="candidate_true_swapstar",
        initial=initial,
        initial_hash=initial_hash,
        initial_recompute=initial_recompute,
        solution=result.solution,
        objective=float(result.objective),
        evaluations=int(result.evaluations_used),
        candidate_scores=int(context.score_counts.get("candidate", 0)),
        elapsed=elapsed,
        cpu_seconds=cpu_seconds,
        contract=contract,
        output=output,
        phase=phase,
        eval_budget=budget,
        component_trace={
            "proxy_moves_considered": result.proxy_moves_considered,
            "feasibility_checks": result.feasibility_checks,
            "feasible_candidates": result.feasible_candidates,
            "accepted_move_count": len(result.accepted_moves),
            "accepted_moves": [asdict(move) for move in result.accepted_moves],
            "stop_reason": result.stop_reason,
            "score_counts": dict(context.score_counts),
        },
    )


def _finalize_row(
    *,
    name: str,
    seed: int,
    arm: str,
    initial: Solution,
    initial_hash: str,
    initial_recompute: dict[str, Any],
    solution: Solution,
    objective: float,
    evaluations: int,
    candidate_scores: int,
    elapsed: float,
    cpu_seconds: float,
    contract: dict[str, Any],
    output: Path,
    component_trace: dict[str, Any],
    phase: str = "marginal_screen",
    eval_budget: int = MARGINAL_BUDGET,
) -> dict[str, Any]:
    bundle = contract["bundle"]
    prices = vrptw_prices(
        capacity=contract["capacity"],
        big_m=contract["big_m"],
    )
    recompute = independent_vrptw_recompute(
        solution,
        bundle=bundle,
        capacity=contract["capacity"],
    )
    violations = check_solution(solution, bundle.instance, prices)
    expected_objective = (
        float(contract["big_m"]) * int(recompute["route_count"])
        + float(recompute["distance_double"])
    )
    payload = solution_payload(solution)
    solution_hash = canonical_sha256(payload)
    solution_path = (
        output
        / "solutions"
        / f"{phase}__{name}__seed{seed}__budget{eval_budget}__{arm}.json"
    )
    atomic_json(solution_path, payload)
    failures: list[str] = []
    if evaluations != eval_budget:
        failures.append("INVALID_EVALUATION_COUNT")
    if candidate_scores != eval_budget:
        failures.append("INVALID_CANDIDATE_SCORE_COUNT")
    if not recompute["passed"] or violations:
        failures.append("INFEASIBLE")
    if abs(objective - expected_objective) > TOL:
        failures.append("OBJECTIVE_MISMATCH")
    if elapsed > 301.0:
        failures.append("TIMEOUT")
    return {
        "phase": phase,
        "instance": name,
        "class": name.split("_", maxsplit=1)[0],
        "seed": seed,
        "arm": arm,
        "eval_budget": eval_budget,
        "evaluations": evaluations,
        "candidate_scores": candidate_scores,
        "initial_route_count": int(initial_recompute["route_count"]),
        "initial_distance_double": float(initial_recompute["distance_double"]),
        "initial_solution_sha256": initial_hash,
        "route_count": int(recompute["route_count"]),
        "distance_double": float(recompute["distance_double"]),
        "score": expected_objective,
        "algorithm_objective": objective,
        "big_m": float(contract["big_m"]),
        "elapsed_seconds": elapsed,
        "process_cpu_seconds": cpu_seconds,
        "feasible": bool(recompute["passed"] and not violations),
        "independent_recompute_pass": bool(recompute["passed"]),
        "model_violation_count": len(violations),
        "failure_codes": failures,
        "status": "OK" if not failures else "FAIL",
        "solution_sha256": solution_hash,
        "solution_path": str(solution_path.relative_to(REPO)),
        "bundle_hashes": contract["bundle_hashes"],
        "component_trace": component_trace,
        "source_checkpoint_route_count": len(initial.routes),
        "source_checkpoint_payload_sha256": canonical_sha256(
            solution_payload(initial)
        ),
    }


def paired_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for row in rows:
        if row["phase"] != "marginal_screen":
            continue
        grouped.setdefault((row["instance"], row["seed"]), {})[
            row["arm"]
        ] = row
    pairs: list[dict[str, Any]] = []
    for (name, seed), arms in sorted(grouped.items()):
        if set(arms) != {"baseline_continue", "candidate_true_swapstar"}:
            continue
        baseline = arms["baseline_continue"]
        candidate = arms["candidate_true_swapstar"]
        baseline_score = float(baseline["score"])
        candidate_score = float(candidate["score"])
        pairs.append(
            {
                "instance": name,
                "seed": seed,
                "eval_budget": MARGINAL_BUDGET,
                "baseline_score": baseline_score,
                "candidate_score": candidate_score,
                "improvement_pct": (
                    100.0
                    * (baseline_score - candidate_score)
                    / baseline_score
                ),
                "distance_delta_candidate_minus_baseline": (
                    float(candidate["distance_double"])
                    - float(baseline["distance_double"])
                ),
                "route_count_delta_candidate_minus_baseline": (
                    int(candidate["route_count"])
                    - int(baseline["route_count"])
                ),
                "elapsed_overhead_pct": (
                    100.0
                    * (
                        float(candidate["elapsed_seconds"])
                        - float(baseline["elapsed_seconds"])
                    )
                    / max(TOL, float(baseline["elapsed_seconds"]))
                ),
                "common_initial_hash": (
                    baseline["initial_solution_sha256"]
                    == candidate["initial_solution_sha256"]
                ),
            }
        )
    return pairs


def decide(
    rows: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    marginal_rows = [row for row in rows if row["phase"] == "marginal_screen"]
    candidate_rows = [
        row
        for row in marginal_rows
        if row["arm"] == "candidate_true_swapstar"
    ]
    failures = [
        f"{row['phase']}:{row['instance']}:{row['seed']}:{row['arm']}"
        for row in rows
        if row["status"] != "OK"
    ]
    initial_mismatches = [
        f"{pair['instance']}:{pair['seed']}"
        for pair in pairs
        if not pair["common_initial_hash"]
    ]
    evaluations_by_instance = {
        name: sum(
            int(row["evaluations"])
            for row in candidate_rows
            if row["instance"] == name
        )
        for name in INSTANCES
    }
    accepted_by_instance = {
        name: sum(
            int(row["component_trace"]["accepted_move_count"])
            for row in candidate_rows
            if row["instance"] == name
        )
        for name in INSTANCES
    }
    inactive_instances = [
        name
        for name in INSTANCES
        if evaluations_by_instance[name] == 0 or accepted_by_instance[name] == 0
    ]
    improvements = [float(pair["improvement_pct"]) for pair in pairs]
    overheads = [float(pair["elapsed_overhead_pct"]) for pair in pairs]
    mean_improvement = float(np.mean(improvements)) if improvements else 0.0
    nondegrade = sum(value >= -TOL for value in improvements)
    worst_improvement = min(improvements, default=0.0)
    mean_overhead = float(np.mean(overheads)) if overheads else math.inf
    mechanical_pass = (
        not failures
        and not initial_mismatches
        and len(pairs) == 6
        and not inactive_instances
    )
    directional_pass = (
        mechanical_pass
        and mean_improvement > 0.0
        and nondegrade >= 4
        and worst_improvement >= -2.0
        and mean_overhead <= 25.0
    )
    return {
        "verdict": (
            "PROMOTE_TRUE_SWAPSTAR_TO_G1_INTEGRATION_REVIEW"
            if directional_pass
            else (
                "HOLD_TRUE_SWAPSTAR_RUNTIME_ENGINEERING"
                if (
                    mechanical_pass
                    and mean_improvement > 0.0
                    and nondegrade >= 4
                    and worst_improvement >= -2.0
                    and mean_overhead > 25.0
                )
                else "KILL_TRUE_SWAPSTAR_ISOLATED_COMPONENT"
            )
        ),
        "mechanical_gate_pass": mechanical_pass,
        "directional_gate_pass": directional_pass,
        "full_g1_executed": False,
        "full_g1_pass": False,
        "failures": failures,
        "initial_hash_mismatches": initial_mismatches,
        "evaluations_by_instance": evaluations_by_instance,
        "accepted_moves_by_instance": accepted_by_instance,
        "inactive_instances": inactive_instances,
        "pair_count": len(pairs),
        "mean_improvement_pct": mean_improvement,
        "nondegrade_count": nondegrade,
        "worst_improvement_pct": worst_improvement,
        "mean_elapsed_overhead_pct": mean_overhead,
        "claim_boundary": (
            "This five-evaluation marginal gate can reject or justify an "
            "integration review; it cannot validate G1 performance."
        ),
    }


def report_text(
    *,
    decision: dict[str, Any],
    rows: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
) -> str:
    total_elapsed = sum(float(row["elapsed_seconds"]) for row in rows)
    return "\n".join(
        [
            "# Homberger 真正 SWAP* 最小边际门",
            "",
            f"- 判定：`{decision['verdict']}`",
            f"- 机械门：{decision['mechanical_gate_pass']}",
            f"- 方向门：{decision['directional_gate_pass']}",
            f"- 完整 G1 已运行：{decision['full_g1_executed']}",
            f"- 配对数：{decision['pair_count']}",
            f"- 平均改善：{decision['mean_improvement_pct']:.9f}%",
            f"- 不退化：{decision['nondegrade_count']}/6",
            f"- 最差改善：{decision['worst_improvement_pct']:.9f}%",
            f"- 平均时间开销：{decision['mean_elapsed_overhead_pct']:.3f}%",
            f"- 各实例接受动作：{decision['accepted_moves_by_instance']}",
            f"- 总实耗：{total_elapsed:.3f}s",
            "",
            "本门复用冻结 baseline-B40 检查点，每臂只新增 5 次完整评价；"
            "没有读取 BKS、Solomon 参考解或中国正式结果。即使晋级，也只表示"
            "值得设计正式接入，不表示通过 12×3×1600 的 G1。",
            "",
            "## 配对明细",
            "",
            *[
                (
                    f"- {pair['instance']} seed={pair['seed']}: "
                    f"improvement={pair['improvement_pct']:.9f}%, "
                    f"distance_delta={pair['distance_delta_candidate_minus_baseline']:.6f}, "
                    f"time_overhead={pair['elapsed_overhead_pct']:.3f}%"
                )
                for pair in pairs
            ],
            "",
        ]
    )


def execute(output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise DevelopmentGateError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    checkpoints = frozen_checkpoints()
    rows: list[dict[str, Any]] = []
    verified: dict[tuple[str, int], tuple[Solution, str, dict[str, Any]]] = {}
    contracts = {name: bundle_contract(name) for name in INSTANCES}
    for key, source_row in checkpoints.items():
        verified[key] = verify_checkpoint(
            key[0],
            source_row,
            contract=contracts[key[0]],
        )

    smoke_initial, smoke_hash, smoke_recompute = verified[("C1_2_1", 1)]
    for budget in SMOKE_BUDGETS:
        rows.append(
            run_true_swapstar(
                name="C1_2_1",
                seed=1,
                budget=budget,
                phase="budget_smoke",
                initial=smoke_initial,
                initial_hash=smoke_hash,
                initial_recompute=smoke_recompute,
                contract=contracts["C1_2_1"],
                output=output,
            )
        )

    for instance_index, name in enumerate(INSTANCES):
        for seed in SEEDS:
            initial, initial_hash, initial_recompute = verified[(name, seed)]
            arm_order = (
                ("baseline_continue", "candidate_true_swapstar")
                if (instance_index + seed) % 2 == 0
                else ("candidate_true_swapstar", "baseline_continue")
            )
            for arm in arm_order:
                if arm == "baseline_continue":
                    row = run_baseline_continue(
                        name=name,
                        seed=seed,
                        initial=initial,
                        initial_hash=initial_hash,
                        initial_recompute=initial_recompute,
                        contract=contracts[name],
                        output=output,
                    )
                else:
                    row = run_true_swapstar(
                        name=name,
                        seed=seed,
                        budget=MARGINAL_BUDGET,
                        phase="marginal_screen",
                        initial=initial,
                        initial_hash=initial_hash,
                        initial_recompute=initial_recompute,
                        contract=contracts[name],
                        output=output,
                    )
                row["run_order"] = arm_order.index(arm) + 1
                rows.append(row)

    pairs = paired_results(rows)
    decision = decide(rows, pairs)
    finished_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "schema_version": "resetp.e2.homberger-g1-true-swapstar-micro.v1",
        "created_at_utc": finished_at,
        "started_at_utc": started_at,
        "git_head": git_output("rev-parse", "HEAD"),
        "git_branch": git_output("branch", "--show-current"),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "source_gate": str(SOURCE_GATE.relative_to(REPO)),
        "source_gate_decision_sha256": sha256(SOURCE_GATE / "decision.json"),
        "instances": list(INSTANCES),
        "seeds": list(SEEDS),
        "marginal_budget_per_arm": MARGINAL_BUDGET,
        "full_g1_executed": False,
    }
    task_contract = {
        "task_card": str(TASK_CARD.relative_to(REPO)),
        "candidate": "true_swapstar_free_reinsertion",
        "route_pair_scope": "same_depot_same_vehicle_type",
        "overlap_tolerance": 0.05,
        "top_insertions": 3,
        "proxy": "strictly_negative_double_precision_distance_delta",
        "comparator": "frozen_alns_continue_from_same_baseline_b40_checkpoint",
        "pass_thresholds": {
            "failures": 0,
            "pair_count": 6,
            "mean_improvement_pct_min_exclusive": 0.0,
            "nondegrade_min": 4,
            "worst_improvement_pct_min": -2.0,
            "mean_elapsed_overhead_pct_max": 25.0,
        },
        "forbidden": [
            "full_g1_implicit_launch",
            "Solomon_or_China_formal_data",
            "BKS_or_reference_routes",
            "parameter_rescue_after_results",
        ],
    }
    atomic_json(output / "metadata.json", metadata)
    atomic_json(output / "task_contract.json", task_contract)
    atomic_csv(output / "raw_runs.csv", rows)
    atomic_json(output / "paired_results.json", pairs)
    atomic_json(output / "decision.json", decision)
    atomic_text(
        output / "report.md",
        report_text(decision=decision, rows=rows, pairs=pairs),
    )
    clean_generated_appledouble(output)
    paths = [
        TASK_CARD,
        OPERATOR_SOURCE,
        TEST_SOURCE,
        RUNNER_SOURCE,
        SOURCE_GATE / "decision.json",
        SOURCE_GATE / "raw_runs.csv",
        output / "metadata.json",
        output / "task_contract.json",
        output / "raw_runs.csv",
        output / "paired_results.json",
        output / "decision.json",
        output / "report.md",
        *sorted((output / "solutions").glob("*.json")),
    ]
    hashes = {
        str(path.relative_to(REPO)): sha256(path)
        for path in paths
        if path.is_file()
    }
    atomic_json(output / "artifact_hashes.json", hashes)
    clean_generated_appledouble(output)
    return decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output is None:
        output = DEFAULT_OUTPUT
    else:
        output = args.output if args.output.is_absolute() else REPO / args.output
    decision = execute(output)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
