"""Root-cause instrumentation for the ALNS-Wouda benchmark gap.

This module is diagnostic-only. It does not change production search
operators, acceptance criteria, or formal report outputs.
"""

from __future__ import annotations

import csv
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import random
from statistics import mean, median
import time
from typing import Any

import numpy as np

from ..check import check_solution
from ..cost import evaluate
from ..prices import DEFAULT_PRICES
from ..solution import Solution
from . import alns_wouda
from .alns_wouda import AlnsState, SearchPolicy
from .bundle import SearchBundle, load_search_bundle
from .candidates import (
    PRIMARY_ALGORITHM,
    CandidateState,
    _algorithm_seed,
    _candidate_budget_limit,
    _empty_search_diagnostics,
    _run_dr_alns_path,
    _run_sa_path,
    make_shared_initial_solution,
)
from .evaluation import BIG_M, EvalBudget, EvaluationContext, score_reference
from .fleet import infer_fleet_limits


ROOT_CAUSE_ALGORITHMS = [PRIMARY_ALGORITHM, "DR-ALNS", "scikit-opt-SA"]
WANG_ROOT_CAUSE_ALGORITHMS = ["ALNS@wangqianlongucas", "DR-ALNS", "scikit-opt-SA"]
TRACE_FIELDS = [
    "algorithm",
    "instance",
    "seed",
    "iter",
    "best_cost",
    "current_cost",
    "candidate_cost",
    "warm_seed_cost",
    "churn",
    "accepted",
    "improved_best",
    "improved_current",
    "feasible",
    "penalty",
    "violation_count",
    "destroy_op",
    "repair_op",
    "remove_count_q",
    "actual_evals",
    "repair_delta_count",
    "elapsed_seconds",
    "destroy_weights_json",
    "repair_weights_json",
    "selected_destroy_weight",
    "selected_repair_weight",
    "rrt_threshold",
    "temperature",
]


@dataclass(frozen=True)
class ScoreBreakdown:
    raw_cost: float
    objective: float
    penalty: float
    violation_count: int
    feasible: bool


@dataclass(frozen=True)
class DiagnosticRun:
    algorithm: str
    instance: str
    seed: int
    status: str
    trace_path: str
    best_solution: Solution
    warm_seed_cost: float
    final_best_cost: float
    actual_evals: int
    actual_moves: int
    elapsed_seconds: float
    failure_reason: str = ""


def run_alns_root_cause_diagnostics(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int] | None = None,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 300.0,
    algorithms: list[str] | None = None,
) -> dict[str, Any]:
    """Run the ALNS/DR/SA root-cause trace board into an isolated directory."""

    root = Path(repo_root)
    out = Path(output_dir)
    (out / "traces").mkdir(parents=True, exist_ok=True)
    (out / "tables").mkdir(parents=True, exist_ok=True)
    seeds = seeds or [1]
    run_seeds = [int(seed) for seed in seeds]
    run_algorithms = algorithms or ROOT_CAUSE_ALGORITHMS
    instances = {
        "L-main": root / "models" / "data_bundle" / "generated_instances" / "E-UK24h-三班-01",
        "100-01-24h": root / "models" / "data_bundle" / "generated_instances" / "E-UK100_01__d2_s3_seed1_24h_20251113",
    }
    warm_starts = {
        name: make_shared_initial_solution(load_search_bundle(path))
        for name, path in instances.items()
    }
    tasks = [
        (algorithm, instance_name, str(bundle_dir), seed, int(eval_budget), float(max_runtime_seconds), str(out / "traces"))
        for instance_name, bundle_dir in instances.items()
        for algorithm in run_algorithms
        for seed in run_seeds
    ]
    runs: list[DiagnosticRun] = []
    max_workers = max(1, min(len(tasks), int(os.environ.get("SETP_ALNS_PARALLEL_WORKERS", os.cpu_count() or 2))))
    if max_workers == 1:
        runs = [_run_trace_worker(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_run_trace_worker, task) for task in tasks]
            for future in as_completed(futures):
                runs.append(future.result())
    runs.sort(key=lambda run: (run.instance, run.algorithm, run.seed))
    manifest_rows = [_manifest_row(run) for run in runs]

    trace_rows = _load_trace_rows(out / "traces")
    references = _reference_best_by_instance(trace_rows)
    summary_rows = _summary_rows(trace_rows, references, eval_budget=eval_budget)
    operator_rows = _operator_summary_rows(trace_rows)
    bundle_cache = {name: load_search_bundle(path) for name, path in instances.items()}
    warm_structure_cache = {
        name: solution_structure(warm_starts[name], bundle_cache[name])
        for name in instances
    }
    structure_rows = [
        _structure_row(run, references.get(run.instance, run.final_best_cost), bundle_cache[run.instance], warm_structure_cache[run.instance])
        for run in runs
        if run.status != "failed"
    ]
    gate = _root_cause_gate(structure_rows, manifest_rows)
    _write_csv(out / "tables" / "root_cause_summary.csv", summary_rows)
    _write_csv(out / "tables" / "operator_summary.csv", operator_rows)
    _write_csv(out / "tables" / "best_solution_structure.csv", structure_rows)
    (out / "root_cause_report.md").write_text(
        _root_cause_report(summary_rows, operator_rows, structure_rows, references, gate),
        encoding="utf-8",
    )
    (out / "README.md").write_text(_readme(eval_budget, max_runtime_seconds, gate), encoding="utf-8")
    manifest = {
        "schema_version": "setp-alns-root-cause.v1",
        "gate": gate,
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "algorithms": run_algorithms,
        "runs": manifest_rows,
    }
    (out / "diagnostic_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"gate": gate, "run_count": len(manifest_rows), "manifest": str(out / "diagnostic_manifest.json")}


def _run_trace_worker(task: tuple[str, str, str, int, int, float, str]) -> DiagnosticRun:
    algorithm, instance_name, bundle_dir, seed, eval_budget, max_runtime_seconds, trace_dir = task
    bundle = load_search_bundle(Path(bundle_dir))
    warm_start = make_shared_initial_solution(bundle)
    try:
        return _run_one_trace(
            algorithm,
            instance_name,
            bundle,
            warm_start,
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            trace_dir=Path(trace_dir),
        )
    except Exception as exc:  # pragma: no cover - long diagnostics persist failures.
        return DiagnosticRun(
            algorithm=algorithm,
            instance=instance_name,
            seed=seed,
            status="failed",
            trace_path="",
            best_solution=warm_start,
            warm_seed_cost=math.nan,
            final_best_cost=math.nan,
            actual_evals=0,
            actual_moves=0,
            elapsed_seconds=0.0,
            failure_reason=f"{type(exc).__name__}: {exc}",
        )


def _run_one_trace(
    algorithm: str,
    instance_name: str,
    bundle: SearchBundle,
    initial_solution: Solution,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    trace_dir: Path,
) -> DiagnosticRun:
    if algorithm == PRIMARY_ALGORITHM:
        return _run_alns_wouda_trace(instance_name, bundle, initial_solution, seed=seed, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds, trace_dir=trace_dir)
    if algorithm in {"DR-ALNS", "scikit-opt-SA", "ALNS@wangqianlongucas", "ALNS@wangqianlongucas-strong"}:
        return _run_candidate_trace(algorithm, instance_name, bundle, initial_solution, seed=seed, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds, trace_dir=trace_dir)
    raise ValueError(f"unsupported root-cause algorithm: {algorithm}")


def _run_alns_wouda_trace(
    instance_name: str,
    bundle: SearchBundle,
    initial_solution: Solution,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    trace_dir: Path,
) -> DiagnosticRun:
    alns_wouda._ensure_local_alns_on_path()

    limits = infer_fleet_limits(bundle.bundle_dir)
    policy = SearchPolicy(require_charging_signal=False, max_cv=limits.cv, max_ev=limits.ev)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        budget=EvalBudget(limit=alns_wouda._budget_limit(None, eval_budget), target=max(1, int(eval_budget))),
        repair_delta_mode="fast",
    )
    warm_breakdown = _reference_breakdown(initial_solution, context)
    current = best = AlnsState(initial_solution, context, objective_value=warm_breakdown.objective, policy=policy)
    current_cost = best_cost = warm_breakdown.raw_cost
    destroy_ops = [
        ("random_customer_removal", alns_wouda.random_customer_removal),
        ("worst_customer_removal", alns_wouda.worst_customer_removal),
        ("shaw_related_removal", alns_wouda.shaw_related_removal),
        ("whole_route_removal", alns_wouda.whole_route_removal),
        ("route_segment_removal", alns_wouda.route_segment_removal),
        ("vehicle_type_swap", alns_wouda.vehicle_type_swap_destroy),
    ]
    repair_ops = [
        ("greedy_insert_repair", alns_wouda.greedy_insert_repair),
        ("regret2_insert_repair", alns_wouda.regret2_insert_repair),
        ("regret3_insert_repair", alns_wouda.regret3_insert_repair),
    ]
    rng = np.random.default_rng(seed)
    destroy_weights = {name: 1.0 for name, _ in destroy_ops}
    repair_weights = {name: 1.0 for name, _ in repair_ops}
    temperature = alns_wouda._initial_temperature_from_reference(current, seed + 991, destroy_ops, repair_ops)
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    iteration = 0
    while context.budget is not None and not context.budget.reached_target and (time.perf_counter() - started) < max_runtime_seconds:
        iteration += 1
        previous_current = current
        previous_current_obj = current.objective()
        previous_best_obj = best.objective()
        destroy_name, destroy_op = alns_wouda._weighted_operator(rng, destroy_ops, destroy_weights)
        repair_name, repair_op = alns_wouda._weighted_operator(rng, repair_ops, repair_weights)
        selected_destroy_weight = float(destroy_weights[destroy_name])
        selected_repair_weight = float(repair_weights[repair_name])
        destroyed = destroy_op(current, rng)
        remove_count_q = len(destroyed.removed_customers)
        candidate = repair_op(destroyed, rng)
        if candidate.removed_customers or alns_wouda._hard_violations(candidate.solution, candidate.context) or not alns_wouda._solution_changed(current.solution, candidate.solution):
            candidate = current
        candidate_obj = candidate.objective()
        candidate_breakdown = _breakdown_for(candidate.solution, context)
        improved_current = candidate_obj < previous_current_obj - 1e-9
        improved_best = candidate_breakdown.feasible and candidate_obj < previous_best_obj - 1e-9
        delta = candidate_obj - previous_current_obj
        accepted = alns_wouda._solution_changed(previous_current.solution, candidate.solution) and (delta <= 0.0 or float(rng.random()) < math.exp(-delta / max(1e-9, temperature)))
        reward = 0.0
        if accepted and improved_best:
            best = current = candidate
            best_cost = current_cost = candidate_breakdown.raw_cost
            reward = 20.0
        elif accepted:
            current = candidate
            current_cost = candidate_breakdown.raw_cost
            reward = 8.0 if improved_current else 2.0
        alns_wouda._update_weight(destroy_weights, destroy_name, reward if accepted else 0.0)
        alns_wouda._update_weight(repair_weights, repair_name, reward if accepted else 0.0)
        rows.append(
            _trace_row(
                algorithm=PRIMARY_ALGORITHM,
                instance=instance_name,
                seed=seed,
                iteration=iteration,
                best_cost=best_cost,
                current_cost=current_cost,
                candidate_breakdown=candidate_breakdown,
                warm_seed_cost=warm_breakdown.raw_cost,
                churn=solution_churn(previous_current.solution, candidate.solution, bundle.instance),
                accepted=accepted,
                improved_best=improved_best,
                improved_current=improved_current,
                destroy_op=destroy_name,
                repair_op=repair_name,
                remove_count_q=remove_count_q,
                actual_evals=context.budget.count,
                repair_delta_count=int(context.score_counts.get("repair_delta", 0)),
                elapsed_seconds=time.perf_counter() - started,
                destroy_weights_json=json.dumps([float(destroy_weights[name]) for name, _ in destroy_ops]),
                repair_weights_json=json.dumps([float(repair_weights[name]) for name, _ in repair_ops]),
                selected_destroy_weight=selected_destroy_weight,
                selected_repair_weight=selected_repair_weight,
                temperature=temperature,
            )
        )
        temperature *= 0.999
    trace_path = _trace_path(trace_dir, instance_name, PRIMARY_ALGORITHM, seed)
    _write_csv(trace_path, rows, fieldnames=TRACE_FIELDS)
    status = "completed_budget" if context.budget and context.budget.reached_target else "timeout"
    return DiagnosticRun(
        algorithm=PRIMARY_ALGORITHM,
        instance=instance_name,
        seed=seed,
        status=status,
        trace_path=str(trace_path),
        best_solution=best.solution,
        warm_seed_cost=warm_breakdown.raw_cost,
        final_best_cost=best_cost,
        actual_evals=int(context.budget.count if context.budget else 0),
        actual_moves=len(rows),
        elapsed_seconds=time.perf_counter() - started,
    )


def _run_candidate_trace(
    algorithm: str,
    instance_name: str,
    bundle: SearchBundle,
    initial_solution: Solution,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    trace_dir: Path,
) -> DiagnosticRun:
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        budget=EvalBudget(limit=_candidate_budget_limit(eval_budget), target=max(1, int(eval_budget))),
        repair_delta_mode="fast",
    )
    warm_breakdown = _reference_breakdown(initial_solution, context)
    state = CandidateState(
        solution=initial_solution,
        context=context,
        adapter_type="root_cause_diagnostic",
        import_status="not_checked",
        package_loaded=False,
        search_diagnostics=_empty_search_diagnostics(),
    )
    rng = random.Random(_algorithm_seed(algorithm, seed))
    rows: list[dict[str, Any]] = []
    current_cost = warm_breakdown.raw_cost
    best_cost = warm_breakdown.raw_cost
    started = time.perf_counter()

    def recorder(**event: Any) -> None:
        nonlocal current_cost, best_cost
        candidate = event["candidate"]
        candidate_breakdown = _breakdown_for(candidate, context)
        accepted = bool(event["accepted"])
        improved_best = candidate_breakdown.feasible and float(event["candidate_obj"]) < float(event["previous_best_obj"]) - 1e-9
        if accepted:
            current_cost = candidate_breakdown.raw_cost
        if improved_best:
            best_cost = candidate_breakdown.raw_cost
        rows.append(
            _trace_row(
                algorithm=algorithm,
                instance=instance_name,
                seed=seed,
                iteration=int(event["iteration"]),
                best_cost=best_cost,
                current_cost=current_cost,
                candidate_breakdown=candidate_breakdown,
                warm_seed_cost=warm_breakdown.raw_cost,
                churn=solution_churn(event["previous_current"], candidate, bundle.instance),
                accepted=accepted,
                improved_best=improved_best,
                improved_current=bool(event["improved_current"]),
                destroy_op=str(event.get("destroy_op", "")),
                repair_op=str(event.get("repair_op", "")),
                remove_count_q=int(event.get("remove_count_q", 0)),
                actual_evals=int(context.budget.count if context.budget else 0),
                repair_delta_count=int(context.score_counts.get("repair_delta", 0)),
                elapsed_seconds=time.perf_counter() - started,
                temperature=float(event["temperature"]) if "temperature" in event else "",
            )
        )

    if algorithm == "DR-ALNS":
        runner = _run_dr_alns_path
    elif algorithm == "ALNS@wangqianlongucas":
        from .candidates import _run_alns_thin_path

        runner = _run_alns_thin_path
    elif algorithm == "ALNS@wangqianlongucas-strong":
        from .candidates import _run_alns_strong_path

        runner = _run_alns_strong_path
    else:
        runner = _run_sa_path
    best_solution = initial_solution
    best_obj = warm_breakdown.objective
    best_model_cost = warm_breakdown.raw_cost
    current = initial_solution
    current_obj = warm_breakdown.objective
    best_solution, best_obj, best_model_cost, _, _ = runner(
        state,
        rng,
        best_solution,
        best_obj,
        best_model_cost,
        current,
        current_obj,
        eval_budget=max(1, int(eval_budget)),
        max_runtime_seconds=max_runtime_seconds,
        started=started,
        recorder=recorder,
    )
    trace_path = _trace_path(trace_dir, instance_name, algorithm, seed)
    _write_csv(trace_path, rows, fieldnames=TRACE_FIELDS)
    status = "completed_budget" if context.budget and context.budget.reached_target else "timeout"
    return DiagnosticRun(
        algorithm=algorithm,
        instance=instance_name,
        seed=seed,
        status=status,
        trace_path=str(trace_path),
        best_solution=best_solution,
        warm_seed_cost=warm_breakdown.raw_cost,
        final_best_cost=best_model_cost,
        actual_evals=int(context.budget.count if context.budget else 0),
        actual_moves=len(rows),
        elapsed_seconds=time.perf_counter() - started,
    )


def _breakdown_for(solution: Solution, context: EvaluationContext) -> ScoreBreakdown:
    cached = context.score_breakdowns.get(id(solution))
    if cached is None:
        score_reference(solution, context)
        cached = context.score_breakdowns.get(id(solution))
    if cached is None:
        raise RuntimeError("score breakdown cache missing after scoring")
    return ScoreBreakdown(
        raw_cost=float(cached["raw_cost"]),
        objective=float(cached["objective"]),
        penalty=float(cached["penalty"]),
        violation_count=int(cached["violation_count"]),
        feasible=bool(cached["feasible"]),
    )


def _reference_breakdown(solution: Solution, context: EvaluationContext) -> ScoreBreakdown:
    score_reference(solution, context)
    return _breakdown_for(solution, context)


def solution_churn(previous: Solution, candidate: Solution, instance: Any) -> int:
    """Count customers whose route/customer-position changed."""

    before = _customer_position_map(previous, instance)
    after = _customer_position_map(candidate, instance)
    return sum(1 for customer_id in set(before) | set(after) if before.get(customer_id) != after.get(customer_id))


def _customer_position_map(solution: Solution, instance: Any) -> dict[str, tuple[int, int]]:
    node_type = {node.node_id: node.node_type.lower() for node in instance.nodes}
    out: dict[str, tuple[int, int]] = {}
    for route_idx, route in enumerate(solution.routes):
        customer_pos = 0
        for node_id in route.node_sequence:
            if node_type.get(node_id) != "c":
                continue
            out[node_id] = (route_idx, customer_pos)
            customer_pos += 1
    return out


def solution_structure(solution: Solution, bundle: SearchBundle) -> dict[str, Any]:
    metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)
    violations = check_solution(solution, bundle.instance, DEFAULT_PRICES)
    return {
        "route_count": len(solution.routes),
        "ev_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
        "cv_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"),
        "charging_events": len(solution.charging_actions),
        "total_cost": float(metrics["total_cost"]),
        "E_total": float(metrics["E_total"]),
        "feasible": not violations,
        "violation_count": len(violations),
    }


def _trace_row(
    *,
    algorithm: str,
    instance: str,
    seed: int,
    iteration: int,
    best_cost: float,
    current_cost: float,
    candidate_breakdown: ScoreBreakdown,
    warm_seed_cost: float,
    churn: int,
    accepted: bool,
    improved_best: bool,
    improved_current: bool,
    destroy_op: str,
    repair_op: str,
    remove_count_q: int,
    actual_evals: int,
    repair_delta_count: int,
    elapsed_seconds: float,
    destroy_weights_json: str = "",
    repair_weights_json: str = "",
    selected_destroy_weight: float | str = "",
    selected_repair_weight: float | str = "",
    rrt_threshold: float | str = "",
    temperature: float | str = "",
) -> dict[str, Any]:
    return {
        "algorithm": algorithm,
        "instance": instance,
        "seed": int(seed),
        "iter": int(iteration),
        "best_cost": float(best_cost),
        "current_cost": float(current_cost),
        "candidate_cost": float(candidate_breakdown.raw_cost),
        "warm_seed_cost": float(warm_seed_cost),
        "churn": int(churn),
        "accepted": bool(accepted),
        "improved_best": bool(improved_best),
        "improved_current": bool(improved_current),
        "feasible": bool(candidate_breakdown.feasible),
        "penalty": float(candidate_breakdown.penalty),
        "violation_count": int(candidate_breakdown.violation_count),
        "destroy_op": destroy_op,
        "repair_op": repair_op,
        "remove_count_q": int(remove_count_q),
        "actual_evals": int(actual_evals),
        "repair_delta_count": int(repair_delta_count),
        "elapsed_seconds": float(elapsed_seconds),
        "destroy_weights_json": destroy_weights_json,
        "repair_weights_json": repair_weights_json,
        "selected_destroy_weight": selected_destroy_weight,
        "selected_repair_weight": selected_repair_weight,
        "rrt_threshold": rrt_threshold,
        "temperature": temperature,
    }


def _trace_path(trace_dir: Path, instance: str, algorithm: str, seed: int) -> Path:
    safe_algorithm = algorithm.replace("@", "_").replace("/", "_")
    safe_instance = instance.replace("/", "_")
    return trace_dir / f"{safe_instance}_{safe_algorithm}_seed{int(seed)}_steps.csv"


def _write_csv(path: Path, rows: list[dict[str, Any]], *, fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = fieldnames or sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in names})


def _load_trace_rows(trace_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(trace_dir.glob("*_steps.csv")):
        if path.name.startswith("._"):
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                rows.append(row)
    return rows


def _reference_best_by_instance(rows: list[dict[str, Any]]) -> dict[str, float]:
    refs: dict[str, float] = {}
    for row in rows:
        if str(row.get("feasible")) != "True":
            continue
        instance = str(row["instance"])
        cost = float(row["best_cost"])
        refs[instance] = cost if instance not in refs else min(refs[instance], cost)
    return refs


def _summary_rows(rows: list[dict[str, Any]], references: dict[str, float], *, eval_budget: int = 16_000) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["instance"], row["algorithm"], row["seed"]), []).append(row)
    out: list[dict[str, Any]] = []
    for (instance, algorithm, seed), items in sorted(grouped.items()):
        reference = references.get(instance, float(items[-1]["best_cost"]))
        warm = float(items[0]["warm_seed_cost"])
        final = float(items[-1]["best_cost"])
        accepted = [row for row in items if str(row["accepted"]) == "True"]
        improved_current_not_accepted = [
            row for row in items
            if str(row["improved_current"]) == "True" and str(row["accepted"]) != "True" and str(row["feasible"]) == "True"
        ]
        out.append(
            {
                "instance": instance,
                "algorithm": algorithm,
                "seed": seed,
                "warm_seed_cost": round(warm, 6),
                "final_best_cost": round(final, 6),
                "reference_best": round(reference, 6),
                "warm_seed_gap_pct": round(_gap(warm, reference), 3),
                "final_gap_pct": round(_gap(final, reference), 3),
                "gap_improvement_pct_points": round(_gap(warm, reference) - _gap(final, reference), 3),
                "iterations": len(items),
                "actual_evals": int(float(items[-1]["actual_evals"])),
                "churn_rate": round(mean(1.0 if int(float(row["churn"])) > 0 else 0.0 for row in items), 6),
                "median_churn": round(float(median(int(float(row["churn"])) for row in items)), 3),
                "mean_churn": round(mean(int(float(row["churn"])) for row in items), 3),
                "avg_remove_count_q": round(mean(int(float(row["remove_count_q"])) for row in items), 3),
                "acceptance_rate": round(len(accepted) / max(1, len(items)), 6),
                "best_improvement_rate": round(mean(1.0 if str(row["improved_best"]) == "True" else 0.0 for row in items), 6),
                "improved_current_not_accepted_rate": round(len(improved_current_not_accepted) / max(1, len(items)), 6),
                "feasible_rate": round(mean(1.0 if str(row["feasible"]) == "True" else 0.0 for row in items), 6),
                "avg_penalty": round(mean(float(row["penalty"]) for row in items), 3),
                "max_current_minus_best": round(max(float(row["current_cost"]) - float(row["best_cost"]) for row in items), 3),
                "final_repair_delta_count": int(float(items[-1]["repair_delta_count"])),
                "status": "completed_budget" if int(float(items[-1]["actual_evals"])) >= int(eval_budget) else "timeout_or_low_budget",
            }
        )
    return out


def _operator_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["instance"], row["algorithm"], row["destroy_op"], row["repair_op"]), []).append(row)
    out: list[dict[str, Any]] = []
    for (instance, algorithm, destroy, repair), items in sorted(grouped.items()):
        out.append(
            {
                "instance": instance,
                "algorithm": algorithm,
                "destroy_op": destroy,
                "repair_op": repair,
                "used": len(items),
                "accepted": sum(1 for row in items if str(row["accepted"]) == "True"),
                "best_improved": sum(1 for row in items if str(row["improved_best"]) == "True"),
                "avg_churn": round(mean(int(float(row["churn"])) for row in items), 3),
                "avg_remove_count_q": round(mean(int(float(row["remove_count_q"])) for row in items), 3),
                "feasible_rate": round(mean(1.0 if str(row["feasible"]) == "True" else 0.0 for row in items), 6),
                "avg_penalty": round(mean(float(row["penalty"]) for row in items), 3),
                "last_destroy_weights_json": items[-1].get("destroy_weights_json", ""),
                "last_repair_weights_json": items[-1].get("repair_weights_json", ""),
            }
        )
    return out


def _structure_row(
    run: DiagnosticRun,
    reference_best: float,
    bundle: SearchBundle | None = None,
    warm_structure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if bundle is None:
        bundle = load_search_bundle(
            Path(__file__).resolve().parents[4] / (
                "models/data_bundle/generated_instances/E-UK24h-三班-01"
                if run.instance == "L-main"
                else "models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113"
            )
        )
    structure = solution_structure(run.best_solution, bundle)
    warm_structure = warm_structure or solution_structure(make_shared_initial_solution(bundle), bundle)
    return {
        "instance": run.instance,
        "algorithm": run.algorithm,
        "seed": run.seed,
        "best_cost": round(structure["total_cost"], 6),
        "gap_to_reference_pct": round(_gap(float(structure["total_cost"]), reference_best), 3),
        "route_count": structure["route_count"],
        "ev_routes": structure["ev_routes"],
        "cv_routes": structure["cv_routes"],
        "charging_events": structure["charging_events"],
        "E_total": round(structure["E_total"], 6),
        "feasible": structure["feasible"],
        "violation_count": structure["violation_count"],
        "all_cv_flag": structure["ev_routes"] == 0,
        "warm_route_count": warm_structure["route_count"],
        "warm_ev_routes": warm_structure["ev_routes"],
        "warm_cv_routes": warm_structure["cv_routes"],
        "warm_charging_events": warm_structure["charging_events"],
        "route_count_delta_vs_warm": structure["route_count"] - warm_structure["route_count"],
        "ev_routes_delta_vs_warm": structure["ev_routes"] - warm_structure["ev_routes"],
        "charging_events_delta_vs_warm": structure["charging_events"] - warm_structure["charging_events"],
    }


def _manifest_row(run: DiagnosticRun) -> dict[str, Any]:
    return {
        "algorithm": run.algorithm,
        "instance": run.instance,
        "seed": run.seed,
        "status": run.status,
        "trace_path": run.trace_path,
        "warm_seed_cost": run.warm_seed_cost,
        "final_best_cost": run.final_best_cost,
        "actual_evals": run.actual_evals,
        "actual_moves": run.actual_moves,
        "elapsed_seconds": run.elapsed_seconds,
        "failure_reason": run.failure_reason,
    }


def _root_cause_gate(structure_rows: list[dict[str, Any]], manifest_rows: list[dict[str, Any]]) -> str:
    if any(row.get("status") == "failed" for row in manifest_rows):
        return "HALT_ROOT_CAUSE_RUN_FAILED"
    if any(row["algorithm"] in {"DR-ALNS", "scikit-opt-SA"} and not row["feasible"] for row in structure_rows):
        return "HALT_ROOT_CAUSE_BEST_INFEASIBLE"
    return "PASS"


def _root_cause_report(
    summary_rows: list[dict[str, Any]],
    operator_rows: list[dict[str, Any]],
    structure_rows: list[dict[str, Any]],
    references: dict[str, float],
    gate: str,
) -> str:
    alns_rows = [row for row in summary_rows if row["algorithm"] == PRIMARY_ALGORITHM]
    sa_rows = [row for row in summary_rows if row["algorithm"] == "scikit-opt-SA"]
    dr_rows = [row for row in summary_rows if row["algorithm"] == "DR-ALNS"]
    verdicts = _hypothesis_verdicts(alns_rows, sa_rows, dr_rows, operator_rows)
    lines = [
        "# ALNS-Wouda Root-Cause Report",
        "",
        f"Gate: `{gate}`",
        "",
        "## Reference Best",
    ]
    for instance, value in sorted(references.items()):
        lines.append(f"- {instance}: {value:.6f}")
    lines.extend(["", "## H1-H5 Verdicts"])
    for name, verdict in verdicts.items():
        lines.append(f"- {name}: {verdict}")
    lines.extend(["", "## Summary Metrics"])
    for row in summary_rows:
        lines.append(
            "- {instance} {algorithm}: warm_gap={warm_seed_gap_pct}%, final_gap={final_gap_pct}%, "
            "churn_rate={churn_rate}, median_churn={median_churn}, accept_rate={acceptance_rate}, "
            "best_improve_rate={best_improvement_rate}, feasible_rate={feasible_rate}, avg_q={avg_remove_count_q}, "
            "avg_penalty={avg_penalty}".format(**row)
        )
    lines.extend(["", "## Best Solution Structure"])
    for row in structure_rows:
        lines.append(
            "- {instance} {algorithm}: cost={best_cost}, gap={gap_to_reference_pct}%, routes={route_count}, "
            "EV={ev_routes}, CV={cv_routes}, charging={charging_events}, E_total={E_total}, "
            "feasible={feasible}, all_cv={all_cv_flag}, warm_routes={warm_route_count}, "
            "warm_EV={warm_ev_routes}, warm_charging={warm_charging_events}, "
            "delta_routes={route_count_delta_vs_warm}, delta_EV={ev_routes_delta_vs_warm}, "
            "delta_charging={charging_events_delta_vs_warm}".format(**row)
        )
    lines.extend(["", "## Operator Evidence"])
    for row in operator_rows:
        if row["algorithm"] != PRIMARY_ALGORITHM:
            continue
        lines.append(
            "- {instance} {destroy_op}+{repair_op}: used={used}, accepted={accepted}, best_improved={best_improved}, "
            "avg_churn={avg_churn}, avg_q={avg_remove_count_q}, feasible_rate={feasible_rate}".format(**row)
        )
    lines.append("")
    return "\n".join(lines)


def _hypothesis_verdicts(
    alns_rows: list[dict[str, Any]],
    sa_rows: list[dict[str, Any]],
    dr_rows: list[dict[str, Any]],
    operator_rows: list[dict[str, Any]],
) -> dict[str, str]:
    alns_churn = mean(float(row["churn_rate"]) for row in alns_rows) if alns_rows else math.nan
    alns_median_churn = mean(float(row["median_churn"]) for row in alns_rows) if alns_rows else math.nan
    alns_accept = mean(float(row["acceptance_rate"]) for row in alns_rows) if alns_rows else math.nan
    alns_current_gap = mean(float(row["max_current_minus_best"]) for row in alns_rows) if alns_rows else math.nan
    alns_false_reject = mean(float(row["improved_current_not_accepted_rate"]) for row in alns_rows) if alns_rows else math.nan
    alns_gap = mean(float(row["final_gap_pct"]) for row in alns_rows) if alns_rows else math.nan
    best_competitor_gap = min(
        [mean(float(row["final_gap_pct"]) for row in rows) for rows in (sa_rows, dr_rows) if rows],
        default=math.nan,
    )
    alns_improvement = mean(float(row["gap_improvement_pct_points"]) for row in alns_rows) if alns_rows else math.nan
    competitor_improvement = max(
        [mean(float(row["gap_improvement_pct_points"]) for row in rows) for rows in (sa_rows, dr_rows) if rows],
        default=math.nan,
    )
    alns_feasible = mean(float(row["feasible_rate"]) for row in alns_rows) if alns_rows else math.nan
    alns_penalty = mean(float(row["avg_penalty"]) for row in alns_rows) if alns_rows else math.nan
    alns_op_rows = [row for row in operator_rows if row["algorithm"] == PRIMARY_ALGORITHM]
    total_op_uses = sum(int(row["used"]) for row in alns_op_rows)
    pair_uses: dict[tuple[str, str], int] = {}
    for row in alns_op_rows:
        key = (str(row["destroy_op"]), str(row["repair_op"]))
        pair_uses[key] = pair_uses.get(key, 0) + int(row["used"])
    top_pair, top_pair_uses = max(pair_uses.items(), key=lambda item: item[1], default=(("", ""), 0))
    top_share = top_pair_uses / max(1, total_op_uses)
    non_swap_rows = [row for row in alns_op_rows if row["destroy_op"] != "vehicle_type_swap"]
    non_swap_uses = sum(int(row["used"]) for row in non_swap_rows)
    non_swap_feasible = (
        sum(float(row["feasible_rate"]) * int(row["used"]) for row in non_swap_rows) / max(1, non_swap_uses)
        if non_swap_rows
        else math.nan
    )
    non_swap_penalty = (
        sum(float(row["avg_penalty"]) * int(row["used"]) for row in non_swap_rows) / max(1, non_swap_uses)
        if non_swap_rows
        else math.nan
    )
    zero_best_ops = sum(1 for row in alns_op_rows if int(row["best_improved"]) == 0)
    return {
        "H1_neighborhood_degeneration": (
            f"{_support(alns_churn < 0.2 or alns_median_churn == 0)}; "
            f"ALNS churn_rate_avg={alns_churn:.3f}, median_churn_avg={alns_median_churn:.3f}, "
            f"ALNS_gap={alns_gap:.3f}%, best_competitor_gap={best_competitor_gap:.3f}%"
        ),
        "H2_acceptance_miscalibration": (
            f"{_support((alns_accept > 0.95 and alns_current_gap > 200.0) or alns_false_reject > 0.05)}; "
            f"ALNS acceptance_rate_avg={alns_accept:.3f}, max_current_minus_best_avg={alns_current_gap:.3f}, "
            f"improved_current_not_accepted_rate_avg={alns_false_reject:.3f}"
        ),
        "H3_neighborhood_scale_too_small": (
            f"{_support((competitor_improvement - alns_improvement) > 3.0)}; "
            f"ALNS_gap_improvement={alns_improvement:.3f}pp, best_competitor_improvement={competitor_improvement:.3f}pp"
        ),
        "H4_feasibility_waste": (
            f"{_support(non_swap_feasible < 0.5 or non_swap_penalty > BIG_M)}; "
            f"ALNS aggregate_feasible_rate_avg={alns_feasible:.3f}, aggregate_avg_penalty={alns_penalty:.3f}, "
            f"non_swap_destroy_repair_feasible_rate={non_swap_feasible:.3f}, non_swap_avg_penalty={non_swap_penalty:.3f}"
        ),
        "H5_weight_not_learning": (
            f"{_support(top_share > 0.7 or zero_best_ops >= max(1, len(alns_op_rows) // 2))}; "
            f"top_operator_pair={top_pair[0]}+{top_pair[1]}, top_operator_pair_use_share={top_share:.3f}, "
            f"zero_best_improvement_operator_pairs={zero_best_ops}/{len(alns_op_rows)}"
        ),
    }


def _support(condition: bool) -> str:
    return "SUPPORTED" if condition else "NOT_SUPPORTED"


def _gap(cost: float, reference: float) -> float:
    return (float(cost) - float(reference)) / float(reference) * 100.0 if reference else math.nan


def _readme(eval_budget: int, max_runtime_seconds: float, gate: str) -> str:
    return "\n".join(
        [
            "# ALNS Root-Cause Diagnostics",
            "",
            f"Gate: `{gate}`",
            "",
            "This directory is diagnostic-only. It does not replace formal reports or manuscript tables.",
            "",
            "## Command",
            "",
            "```bash",
            "PYTHONPATH=solver/src python -m setp_solver.search.formal_runner ALNS_ROOT_CAUSE "
            f"--output-dir solver/reports/alns_root_cause --eval-budget {int(eval_budget)} "
            f"--max-runtime-seconds {float(max_runtime_seconds)} --seeds 1",
            "```",
            "",
            "## Stdout Summary",
            "",
            "```text",
            f"GATE ALNS_ROOT_CAUSE {gate} {{\"gate\": \"{gate}\", \"run_count\": 6, \"manifest\": \"solver/reports/alns_root_cause/diagnostic_manifest.json\"}}",
            "```",
            "",
            "## Budget And Fields",
            "",
            "- `actual_evals` is the number of complete candidate solutions submitted to acceptance/selection.",
            "- `repair_delta_count` is a transparent repair-internal work counter; it does not consume eval budget.",
            "- `actual_moves` is the number of recorded search iterations in the trace.",
            "- `churn` counts customer route/position changes only; depots and charging stations are ignored.",
            "- `penalty` is `BIG_M * violation_count`; `feasible=True` means `violation_count == 0`.",
            "",
            "## Outputs",
            "",
            "- `traces/*_steps.csv`: per-iteration trace rows for ALNS-Wouda, DR-ALNS, and scikit-opt-SA.",
            "- `tables/root_cause_summary.csv`: H1-H4 aggregate metrics by algorithm and instance.",
            "- `tables/operator_summary.csv`: H5 operator use, acceptance, improvement, churn, and feasibility evidence.",
            "- `tables/best_solution_structure.csv`: anti-cheat legality and structure check for best solutions.",
            "- `root_cause_report.md`: H1-H5 verdicts grounded in the tables above.",
            "- `diagnostic_manifest.json`: run statuses, trace paths, budgets, and elapsed times.",
        ]
    )
