#!/usr/bin/env python3
"""Run the isolated Homberger SISR component gates.

``micro`` is the default and intentionally cheap: one Homberger budget
closure ladder plus two pre-registered paired screens.  ``g1`` is the frozen
12 instances x 3 seeds x 1600 evaluations gate and is never selected
implicitly.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping

import numpy as np


REPO = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO / "solver/src"
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy  # noqa: E402
from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    WinnerKernelConfig,
    _run_winner_kernel_loop,
    e2_alns_variant_flags,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import PriceParameters  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import Route, Solution  # noqa: E402


BUNDLES = REPO / "baselines/e2_alns/homberger_200_development_bundles_20260717"
DEFAULT_MICRO_OUT = REPO / "baselines/e2_alns/homberger_g1_sisr_micro_20260718"
DEFAULT_G1_OUT = REPO / "baselines/e2_alns/homberger_g1_sisr_formal_20260718"
TASK_CARD = REPO / "docs/handoff/e2_alns_g1_sisr_task_card_20260718.md"
OPERATOR_SOURCE = (
    REPO
    / "solver/src/setp_solver/algorithms/resetp_alns/operators/sisr_string_removal.py"
)
WINNER_SOURCE = (
    REPO / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py"
)
RUNNER_SOURCE = Path(__file__).resolve()
MICRO_INSTANCES = ("C1_2_1", "R1_2_8")
MICRO_SEEDS = (1, 2, 3)
G1_INSTANCES = (
    "C1_2_1",
    "C1_2_8",
    "C2_2_1",
    "C2_2_8",
    "R1_2_1",
    "R1_2_8",
    "R2_2_1",
    "R2_2_8",
    "RC1_2_1",
    "RC1_2_8",
    "RC2_2_1",
    "RC2_2_8",
)
G1_SEEDS = (1, 2, 3)
G1_BUDGET = 1600
SMOKE_BUDGETS = (0, 1, 2, 5)
TOL = 1e-8


class DevelopmentGateError(RuntimeError):
    """A contract or infrastructure failure in the development gate."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    data = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def clean_generated_appledouble(root: Path) -> int:
    """Remove macOS AppleDouble sidecars only inside this generated output."""
    removed = 0
    for path in sorted(root.rglob("._*"), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink()
            removed += 1
    leftovers = [path for path in root.rglob("._*") if path.exists()]
    if leftovers:
        raise DevelopmentGateError(
            f"AppleDouble cleanup incomplete under {root}: {leftovers}"
        )
    return removed


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_text(
        path,
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
    )


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(
        {
            key: (
                json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (dict, list, tuple))
                else value
            )
            for key, value in row.items()
        }
        for row in rows
    )
    atomic_text(path, buffer.getvalue())


def git_output(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def solution_payload(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [
            asdict(item) for item in solution.cross_site_services
        ],
    }


def bundle_contract(name: str) -> dict[str, Any]:
    root = BUNDLES / name
    payload = json.loads((root / "instance.json").read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
    if "bks" in serialized or "reference_code" in serialized:
        raise DevelopmentGateError(f"development bundle leaks reference data: {name}")
    bundle = load_search_bundle(root)
    matrix = np.asarray(bundle.instance.distance_matrix, dtype=float)
    customer_count = sum(
        str(node.node_type).lower() == "c" for node in bundle.instance.nodes
    )
    max_vehicles = int(bundle.instance.num_cv or 0)
    max_edge = float(np.max(matrix))
    upper_bound = float((customer_count + max_vehicles) * max_edge)
    big_m = float(math.floor(upper_bound) + 1)
    if not big_m > upper_bound:
        raise DevelopmentGateError(f"big-M proof failed: {name}")
    metadata = payload["metadata"]
    return {
        "bundle": bundle,
        "capacity": float(metadata["vehicle_capacity"]),
        "customer_count": customer_count,
        "max_vehicles": max_vehicles,
        "max_edge": max_edge,
        "distance_upper_bound": upper_bound,
        "big_m": big_m,
        "bundle_hashes": {
            filename: sha256(root / filename)
            for filename in (
                "instance.json",
                "distance_matrix.npy",
                "carbon_profile.csv",
            )
        },
    }


def vrptw_prices(*, capacity: float, big_m: float) -> PriceParameters:
    """Map the shared evaluator exactly to big_M * vehicles + distance."""

    return PriceParameters(
        Q_capacity=float(capacity),
        v_speed_ms=1.0,
        diesel_price=0.0,
        carbon_price=0.0,
        diesel_ef=0.0,
        vehicle_fixed_cost=float(big_m),
        occupancy_fee=0.0,
        cross_site_cost=0.0,
        revenue_per_kg=0.0,
        c_km=1000.0,
    )


def deterministic_common_initial_solution(
    instance: Any,
    *,
    capacity: float,
) -> Solution:
    """Build a BKS-blind feasible start by earliest due time then proximity."""

    depots = [
        node
        for node in instance.nodes
        if str(node.node_type).lower() == "d"
    ]
    if len(depots) != 1:
        raise DevelopmentGateError("Homberger development requires one depot")
    depot = depots[0]
    customers = {
        node.node_id: node
        for node in instance.nodes
        if str(node.node_type).lower() == "c"
    }
    remaining = set(customers)
    plans: list[list[str]] = []
    while remaining:
        sequence: list[str] = []
        load = 0.0
        current = depot.node_id
        clock = float(depot.ready_time)
        while True:
            feasible: list[tuple[tuple[float, float, str], str, float]] = []
            for customer_id in remaining:
                node = customers[customer_id]
                if load + float(node.demand) > float(capacity) + TOL:
                    continue
                arrival = clock + float(instance.distance(current, customer_id))
                service_start = max(arrival, float(node.ready_time))
                finish = service_start + float(node.service_time)
                depot_arrival = finish + float(
                    instance.distance(customer_id, depot.node_id)
                )
                if (
                    service_start <= float(node.due_time) + TOL
                    and depot_arrival <= float(depot.due_time) + TOL
                ):
                    feasible.append(
                        (
                            (
                                float(node.due_time),
                                float(instance.distance(current, customer_id)),
                                customer_id,
                            ),
                            customer_id,
                            finish,
                        )
                    )
            if not feasible:
                break
            _, customer_id, finish = min(feasible, key=lambda item: item[0])
            sequence.append(customer_id)
            remaining.remove(customer_id)
            load += float(customers[customer_id].demand)
            current = customer_id
            clock = finish
        if not sequence:
            raise DevelopmentGateError(
                "common-start constructor found no feasible single customer"
            )
        plans.append(sequence)
    if len(plans) > int(instance.num_cv or 0):
        raise DevelopmentGateError(
            f"common start exceeds fleet cap: {len(plans)}>{instance.num_cv}"
        )
    return Solution(
        routes=[
            Route(
                f"CV{index}",
                "cv",
                depot.node_id,
                [depot.node_id, *sequence, depot.node_id],
            )
            for index, sequence in enumerate(plans, start=1)
        ]
    )


def independent_vrptw_recompute(
    solution: Solution,
    *,
    bundle: Any,
    capacity: float,
) -> dict[str, Any]:
    instance = bundle.instance
    nodes = {node.node_id: node for node in instance.nodes}
    customers = {
        node.node_id
        for node in instance.nodes
        if str(node.node_type).lower() == "c"
    }
    depots = [
        node.node_id
        for node in instance.nodes
        if str(node.node_type).lower() == "d"
    ]
    failures: list[str] = []
    if len(depots) != 1:
        return {"passed": False, "failures": [f"depot count: {len(depots)}"]}
    depot = depots[0]
    visited: list[str] = []
    distance = 0.0
    if len(solution.routes) > int(instance.num_cv or 0):
        failures.append("FLEET_SIZE")
    for route_index, route in enumerate(solution.routes, start=1):
        sequence = list(route.node_sequence)
        if (
            len(sequence) < 3
            or sequence[0] != depot
            or sequence[-1] != depot
            or route.vehicle_type.lower() != "cv"
        ):
            failures.append(f"ROUTE_SHAPE:{route_index}")
            continue
        interior = sequence[1:-1]
        if any(node_id not in customers for node_id in interior):
            failures.append(f"ROUTE_INTERIOR:{route_index}")
        visited.extend(interior)
        load = sum(float(nodes[node_id].demand) for node_id in interior)
        if load > float(capacity) + TOL:
            failures.append(f"CAPACITY:{route_index}")
        clock = float(nodes[depot].ready_time)
        for source, target in zip(sequence, sequence[1:]):
            travel = float(instance.distance(source, target))
            distance += travel
            arrival = clock + travel
            service_start = max(arrival, float(nodes[target].ready_time))
            if service_start > float(nodes[target].due_time) + TOL:
                failures.append(f"TIME_WINDOW:{route_index}:{target}")
            clock = service_start + float(nodes[target].service_time)
    if (
        len(visited) != len(customers)
        or len(set(visited)) != len(customers)
        or set(visited) != customers
    ):
        failures.append("COVERAGE")
    return {
        "passed": not failures,
        "failures": failures,
        "route_count": len(solution.routes),
        "distance_double": distance,
        "visited_customer_count": len(visited),
    }


def run_arm(
    name: str,
    *,
    seed: int,
    budget: int,
    arm: str,
    phase: str,
    run_order: int,
    max_runtime_seconds: float,
    output: Path,
) -> dict[str, Any]:
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
    initial_recompute = independent_vrptw_recompute(
        initial,
        bundle=bundle,
        capacity=contract["capacity"],
    )
    initial_model_violations = check_solution(initial, bundle.instance, prices)
    if not initial_recompute["passed"] or initial_model_violations:
        raise DevelopmentGateError(f"common initial solution is infeasible: {name}")

    candidate = arm == "candidate_sisr"
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
            seed=int(seed),
            eval_budget=int(budget),
            max_runtime_seconds=float(max_runtime_seconds),
            include_sisr_string_removal=candidate,
        ),
        prices=prices,
        variant_flags=e2_alns_variant_flags(),
        policy=policy,
        carbon_weight=0.0,
        carbon_quota_kg=float("inf"),
    )
    elapsed = time.perf_counter() - started
    cpu_seconds = time.process_time() - cpu_started
    recompute = independent_vrptw_recompute(
        run.best_solution,
        bundle=bundle,
        capacity=contract["capacity"],
    )
    model_violations = check_solution(run.best_solution, bundle.instance, prices)
    expected_score = (
        float(contract["big_m"]) * int(recompute["route_count"])
        + float(recompute["distance_double"])
    )
    payload = solution_payload(run.best_solution)
    solution_hash = canonical_sha256(payload)
    solution_path = (
        output
        / "solutions"
        / f"{phase}__{name}__seed{seed}__budget{budget}__{arm}.json"
    )
    atomic_json(solution_path, payload)
    sisr_counts = run.destroy_operator_counts.get(
        "sisr_string_removal",
        (0, 0, 0, 0),
    )
    failures: list[str] = []
    if int(run.evaluations) != int(budget):
        failures.append("INVALID_EVALUATION_COUNT")
    if int(run.candidate_scores) != int(budget):
        failures.append("INVALID_CANDIDATE_SCORE_COUNT")
    if not run.feasible or not recompute["passed"] or model_violations:
        failures.append("INFEASIBLE")
    if abs(float(run.best_obj) - expected_score) > TOL:
        failures.append("OBJECTIVE_MISMATCH")
    if elapsed > float(max_runtime_seconds) + 1.0:
        failures.append("TIMEOUT")
    return {
        "phase": phase,
        "instance": name,
        "class": name.split("_", maxsplit=1)[0],
        "seed": int(seed),
        "arm": arm,
        "run_order": int(run_order),
        "eval_budget": int(budget),
        "evaluations": int(run.evaluations),
        "candidate_scores": int(run.candidate_scores),
        "repair_delta_count": int(run.repair_delta_count),
        "actual_moves": int(run.actual_moves),
        "initial_route_count": int(initial_recompute["route_count"]),
        "initial_distance_double": float(initial_recompute["distance_double"]),
        "initial_solution_sha256": canonical_sha256(solution_payload(initial)),
        "route_count": int(recompute["route_count"]),
        "distance_double": float(recompute["distance_double"]),
        "lexicographic_score": expected_score,
        "algorithm_best_obj": float(run.best_obj),
        "big_m": float(contract["big_m"]),
        "distance_upper_bound": float(contract["distance_upper_bound"]),
        "elapsed_seconds": elapsed,
        "process_cpu_seconds": cpu_seconds,
        "sisr_attempt_count": int(sum(sisr_counts)),
        "sisr_outcomes": list(sisr_counts),
        "feasible": bool(
            run.feasible and recompute["passed"] and not model_violations
        ),
        "independent_recompute_pass": bool(recompute["passed"]),
        "model_violation_count": len(model_violations),
        "failure_codes": failures,
        "status": "OK" if not failures else "FAIL",
        "solution_sha256": solution_hash,
        "solution_path": str(solution_path.relative_to(REPO)),
        "bundle_hashes": contract["bundle_hashes"],
        "score_counts": run.operator_counts.get("score_counts", {}),
        "destroy_operator_counts": run.destroy_operator_counts,
        "repair_operator_counts": run.repair_operator_counts,
    }


def paired_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int, int], dict[str, Mapping[str, Any]]] = {}
    for row in rows:
        if row["phase"] not in {"micro_screen", "g1"}:
            continue
        key = (str(row["instance"]), int(row["seed"]), int(row["eval_budget"]))
        grouped.setdefault(key, {})[str(row["arm"])] = row
    pairs: list[dict[str, Any]] = []
    for (name, seed, budget), arms in sorted(grouped.items()):
        if set(arms) != {"baseline", "candidate_sisr"}:
            continue
        baseline = arms["baseline"]
        candidate = arms["candidate_sisr"]
        baseline_score = float(baseline["lexicographic_score"])
        candidate_score = float(candidate["lexicographic_score"])
        pairs.append(
            {
                "instance": name,
                "seed": seed,
                "eval_budget": budget,
                "baseline_score": baseline_score,
                "candidate_score": candidate_score,
                "improvement_pct": (
                    100.0 * (baseline_score - candidate_score) / baseline_score
                ),
                "route_count_delta_candidate_minus_baseline": (
                    int(candidate["route_count"]) - int(baseline["route_count"])
                ),
                "distance_delta_candidate_minus_baseline": (
                    float(candidate["distance_double"])
                    - float(baseline["distance_double"])
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


def decide(mode: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = paired_rows(rows)
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
    candidate_screen_rows = [
        row
        for row in rows
        if row["phase"] in {"micro_screen", "g1"}
        and row["arm"] == "candidate_sisr"
    ]
    sisr_attempts = sum(int(row["sisr_attempt_count"]) for row in candidate_screen_rows)
    sisr_attempts_by_instance = {
        instance: sum(
            int(row["sisr_attempt_count"])
            for row in candidate_screen_rows
            if row["instance"] == instance
        )
        for instance in sorted(
            {str(row["instance"]) for row in candidate_screen_rows}
        )
    }
    inactive_instances = [
        instance
        for instance, attempts in sisr_attempts_by_instance.items()
        if attempts == 0
    ]
    inactive_candidate_rows = [
        f"{row['instance']}:{row['seed']}"
        for row in candidate_screen_rows
        if int(row["sisr_attempt_count"]) == 0
    ]
    improvements = [float(pair["improvement_pct"]) for pair in pairs]
    overheads = [float(pair["elapsed_overhead_pct"]) for pair in pairs]
    mean_improvement = float(np.mean(improvements)) if improvements else 0.0
    worst_improvement = min(improvements, default=0.0)
    nondegrade = sum(value >= -TOL for value in improvements)
    mean_overhead = float(np.mean(overheads)) if overheads else 0.0
    mechanical_pass = (
        not failures
        and not initial_mismatches
        and bool(pairs)
        and sisr_attempts > 0
        and not inactive_instances
    )
    if mode == "micro":
        directional_signal = (
            mechanical_pass
            and mean_improvement > 0.0
            and any(value > TOL for value in improvements)
        )
        verdict = (
            "PROMOTE_TO_FULL_G1"
            if directional_signal
            else (
                "HOLD_NO_DIRECTIONAL_SIGNAL"
                if mechanical_pass
                else "KILL_COMPONENT_MECHANICAL_FAILURE"
            )
        )
        return {
            "verdict": verdict,
            "mode": mode,
            "mechanical_gate_pass": mechanical_pass,
            "directional_signal_only": directional_signal,
            "full_g1_pass": False,
            "full_g1_executed": False,
            "failures": failures,
            "initial_hash_mismatches": initial_mismatches,
            "sisr_attempt_count": sisr_attempts,
            "sisr_attempts_by_instance": sisr_attempts_by_instance,
            "inactive_instances": inactive_instances,
            "inactive_candidate_rows": inactive_candidate_rows,
            "pair_count": len(pairs),
            "mean_improvement_pct": mean_improvement,
            "nondegrade_count": nondegrade,
            "worst_improvement_pct": worst_improvement,
            "mean_elapsed_overhead_pct": mean_overhead,
            "claim_boundary": (
                "Micro screening can reject mechanical failures or justify "
                "running G1; it cannot validate performance or support a paper claim."
            ),
        }

    full_pass = (
        mechanical_pass
        and len(pairs) == 36
        and mean_improvement > 0.0
        and nondegrade >= 24
        and worst_improvement >= -2.0
        and mean_overhead <= 25.0
    )
    return {
        "verdict": "PASS_G1_SISR" if full_pass else "FAIL_G1_SISR_DELETE_COMPONENT",
        "mode": mode,
        "mechanical_gate_pass": mechanical_pass,
        "full_g1_pass": full_pass,
        "full_g1_executed": True,
        "failures": failures,
        "initial_hash_mismatches": initial_mismatches,
        "sisr_attempt_count": sisr_attempts,
        "sisr_attempts_by_instance": sisr_attempts_by_instance,
        "inactive_instances": inactive_instances,
        "inactive_candidate_rows": inactive_candidate_rows,
        "pair_count": len(pairs),
        "mean_improvement_pct": mean_improvement,
        "nondegrade_count": nondegrade,
        "worst_improvement_pct": worst_improvement,
        "mean_elapsed_overhead_pct": mean_overhead,
    }


def report_text(
    *,
    mode: str,
    rows: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    decision: Mapping[str, Any],
) -> str:
    lines = [
        "# Homberger G1 SISR 组件开发报告",
        "",
        f"判定：`{decision['verdict']}`。",
        "",
        (
            "本报告只比较冻结连续 ALNS 与单独增加 SISR 串移除的候选；"
            "未使用 Solomon、中国正式实例或 BKS。"
        ),
        "",
        "## 运行摘要",
        "",
        f"- 模式：`{mode}`",
        f"- 原始任务：{len(rows)}",
        f"- 有效配对：{len(pairs)}",
        f"- SISR 被选择次数：{decision['sisr_attempt_count']}",
        f"- 各实例 SISR 次数：`{decision['sisr_attempts_by_instance']}`",
        f"- 零调用候选行：`{decision['inactive_candidate_rows']}`",
        f"- 平均配对改善：{decision['mean_improvement_pct']:.6f}%",
        f"- 不退化配对：{decision['nondegrade_count']}/{len(pairs)}",
        f"- 最差配对改善：{decision['worst_improvement_pct']:.6f}%",
        f"- 平均运行时开销：{decision['mean_elapsed_overhead_pct']:.3f}%",
        "",
        "## 配对明细",
        "",
        "| 实例 | 种子 | 预算 | 改善% | 路线数差 | 距离差 | 时间开销% |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        (
            f"| {pair['instance']} | {pair['seed']} | {pair['eval_budget']} | "
            f"{pair['improvement_pct']:.6f} | "
            f"{pair['route_count_delta_candidate_minus_baseline']} | "
            f"{pair['distance_delta_candidate_minus_baseline']:.6f} | "
            f"{pair['elapsed_overhead_pct']:.3f} |"
        )
        for pair in pairs
    )
    lines.extend(
        [
            "",
            "## 证据边界",
            "",
            (
                "微型筛查只用于预算闭合、可行性、活性和方向性判断；"
                "即使判 `PROMOTE_TO_FULL_G1`，也不表示组件已通过 G1。"
            ),
            (
                "正式 G1 仍须执行 12 例×3 种子×1600 次完整评价，"
                "并按冻结阈值一次判定，不得用本结果调参数。"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_evidence(
    *,
    output: Path,
    mode: str,
    rows: list[dict[str, Any]],
    started_at: str,
    finished_at: str,
    screen_budget: int,
) -> dict[str, Any]:
    pairs = paired_rows(rows)
    decision = decide(mode, rows)
    metadata = {
        "schema_version": "resetp.e2.homberger-g1-sisr.v1",
        "mode": mode,
        "status": decision["verdict"],
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "git_head": git_output("rev-parse", "HEAD"),
        "git_diff_sha256": canonical_sha256(git_output("diff", "--binary")),
        "python": sys.version,
        "python_executable": sys.executable,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "baseline_flags": e2_alns_variant_flags(),
        "candidate_delta": {
            "include_sisr_string_removal": True,
            "all_other_config_equal": True,
        },
        "sisr_parameters": {
            "max_string_length": 10,
            "average_removed_customers": 10,
            "split_probability": 0.5,
            "preserved_segment_stop_probability": 0.01,
        },
        "micro_instances": list(MICRO_INSTANCES),
        "micro_seeds": list(MICRO_SEEDS),
        "screen_budget": int(screen_budget),
        "g1_instances": list(G1_INSTANCES),
        "g1_seeds": list(G1_SEEDS),
        "g1_budget": G1_BUDGET,
        "task_card": str(TASK_CARD.relative_to(REPO)),
        "external_reference_implementation": {
            "repository": "https://github.com/hankarudova/open-source-sisr-routing",
            "branch": "vrptw",
            "commit": "857c8eeafd95cbdf8245620486d309369f1aab20",
            "license": "Apache-2.0",
        },
    }
    task_contract = {
        "mode": mode,
        "smoke_budgets": list(SMOKE_BUDGETS) if mode == "micro" else [],
        "screen_budget": int(screen_budget) if mode == "micro" else G1_BUDGET,
        "instances": list(MICRO_INSTANCES if mode == "micro" else G1_INSTANCES),
        "seeds": list(MICRO_SEEDS) if mode == "micro" else list(G1_SEEDS),
        "objective": [
            "minimize_vehicle_count",
            "then_minimize_double_precision_total_distance",
        ],
        "common_initial_solution": (
            "earliest_due_time_then_current_distance_then_customer_id"
        ),
        "full_g1_thresholds": {
            "failure_count": 0,
            "mean_improvement_pct_strictly_greater_than": 0.0,
            "nondegrade_minimum": 24,
            "pair_count": 36,
            "worst_improvement_pct_minimum": -2.0,
            "mean_elapsed_overhead_pct_maximum": 25.0,
        },
    }
    atomic_json(output / "metadata.json", metadata)
    atomic_json(output / "task_contract.json", task_contract)
    atomic_csv(output / "raw_runs.csv", rows)
    atomic_json(output / "paired_results.json", pairs)
    atomic_json(output / "decision.json", decision)
    atomic_text(
        output / "report.md",
        report_text(mode=mode, rows=rows, pairs=pairs, decision=decision),
    )
    clean_generated_appledouble(output)
    paths = [
        TASK_CARD,
        OPERATOR_SOURCE,
        WINNER_SOURCE,
        RUNNER_SOURCE,
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


def execute(
    *,
    mode: str,
    output: Path,
    screen_budget: int,
    max_runtime_seconds: float,
) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise DevelopmentGateError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    if mode == "micro":
        for order, budget in enumerate(SMOKE_BUDGETS, start=1):
            rows.append(
                run_arm(
                    MICRO_INSTANCES[0],
                    seed=1,
                    budget=budget,
                    arm="candidate_sisr",
                    phase="budget_smoke",
                    run_order=order,
                    max_runtime_seconds=max_runtime_seconds,
                    output=output,
                )
            )
        for instance_index, name in enumerate(MICRO_INSTANCES):
            for seed in MICRO_SEEDS:
                arms = (
                    ("baseline", "candidate_sisr")
                    if (instance_index + seed) % 2 == 0
                    else ("candidate_sisr", "baseline")
                )
                for run_order, arm in enumerate(arms, start=1):
                    rows.append(
                        run_arm(
                            name,
                            seed=seed,
                            budget=screen_budget,
                            arm=arm,
                            phase="micro_screen",
                            run_order=run_order,
                            max_runtime_seconds=max_runtime_seconds,
                            output=output,
                        )
                    )
    else:
        for instance_index, name in enumerate(G1_INSTANCES):
            for seed in G1_SEEDS:
                arms = (
                    ("baseline", "candidate_sisr")
                    if (instance_index + seed) % 2 == 0
                    else ("candidate_sisr", "baseline")
                )
                for run_order, arm in enumerate(arms, start=1):
                    rows.append(
                        run_arm(
                            name,
                            seed=seed,
                            budget=G1_BUDGET,
                            arm=arm,
                            phase="g1",
                            run_order=run_order,
                            max_runtime_seconds=max_runtime_seconds,
                            output=output,
                        )
                    )
    finished_at = datetime.now(timezone.utc).isoformat()
    return write_evidence(
        output=output,
        mode=mode,
        rows=rows,
        started_at=started_at,
        finished_at=finished_at,
        screen_budget=screen_budget,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("micro", "g1"), default="micro")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--screen-budget", type=int, default=40)
    parser.add_argument("--max-runtime-seconds", type=float, default=300.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.screen_budget <= 0:
        raise DevelopmentGateError("screen budget must be positive")
    if args.output is None:
        output = DEFAULT_MICRO_OUT if args.mode == "micro" else DEFAULT_G1_OUT
    else:
        output = args.output if args.output.is_absolute() else REPO / args.output
    decision = execute(
        mode=args.mode,
        output=output,
        screen_budget=args.screen_budget,
        max_runtime_seconds=args.max_runtime_seconds,
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
