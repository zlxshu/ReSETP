"""Isolated diagnostics and measurement helpers for the ALNS crush lane.

This module is intentionally outside the formal E1-E7 runners. It records
evidence under ``solver/reports/alns_crush`` and does not change model semantics.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import time
from typing import Any

from ..check import check_solution
from ..cost import evaluate
from ..instance_loader import Instance
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import ChargingAction, CrossSiteService, Route, Solution
from .alns_wouda import SearchPolicy, run_alns_wouda
from .bundle import load_search_bundle
from .candidates import make_shared_initial_solution, run_candidate
from .charging import repair_route_charging
from .instance_registry import (
    FORMAL_INSTANCE_ORDER,
    INSTANCE_REL_DIRS,
    L_MAIN_THREESHIFT_SIZES,
)


COMPONENT_FIELDS = [
    "cost_fix",
    "cost_km",
    "cost_fuel",
    "cost_elec",
    "cost_occ",
    "cost_carbon",
    "cost_transship",
]

# Formal default (2026-07-09): 9-step threeshift-only L-main. Vanilla/multidepot
# remain ARCHIVE_ONLY under L-main_mixed23_archive_20260709 / e2_benchmark.
L_MAIN_INSTANCE_ORDER = FORMAL_INSTANCE_ORDER
INSTANCE_DIRS = dict(INSTANCE_REL_DIRS)
ALNS_DEFAULT_INSTANCE_ORDER = L_MAIN_INSTANCE_ORDER

ALGORITHMS = ["scikit-opt-SA", "DR-ALNS", "ALNS-Wouda"]

CRUSH_FLAG_NAMES = [
    "SETP_ALNS_CRUSH_TRUE_REPAIR",
    "SETP_ALNS_CRUSH_ROUTE_ELIMINATION",
    "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE",
    "SETP_ALNS_CRUSH_LOCAL_SEARCH",
    "SETP_ALNS_CRUSH_ADAPTIVE_Q",
]

ABLATION_VARIANTS = {
    "winner_kernel": {
        "SETP_ALNS_CRUSH_TRUE_REPAIR": "0",
        "SETP_ALNS_CRUSH_ROUTE_ELIMINATION": "0",
        "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE": "0",
        "SETP_ALNS_CRUSH_LOCAL_SEARCH": "0",
        "SETP_ALNS_CRUSH_ADAPTIVE_Q": "0",
    },
    "true_cost_repair": {
        "SETP_ALNS_CRUSH_TRUE_REPAIR": "1",
        "SETP_ALNS_CRUSH_ROUTE_ELIMINATION": "0",
        "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE": "0",
        "SETP_ALNS_CRUSH_LOCAL_SEARCH": "0",
        "SETP_ALNS_CRUSH_ADAPTIVE_Q": "0",
    },
    "route_elimination": {
        "SETP_ALNS_CRUSH_TRUE_REPAIR": "1",
        "SETP_ALNS_CRUSH_ROUTE_ELIMINATION": "1",
        "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE": "0",
        "SETP_ALNS_CRUSH_LOCAL_SEARCH": "0",
        "SETP_ALNS_CRUSH_ADAPTIVE_Q": "1",
    },
    "true_acceptance": {
        "SETP_ALNS_CRUSH_TRUE_REPAIR": "1",
        "SETP_ALNS_CRUSH_ROUTE_ELIMINATION": "1",
        "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE": "1",
        "SETP_ALNS_CRUSH_LOCAL_SEARCH": "0",
        "SETP_ALNS_CRUSH_ADAPTIVE_Q": "1",
    },
    "local_search": {
        "SETP_ALNS_CRUSH_TRUE_REPAIR": "1",
        "SETP_ALNS_CRUSH_ROUTE_ELIMINATION": "1",
        "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE": "1",
        "SETP_ALNS_CRUSH_LOCAL_SEARCH": "1",
        "SETP_ALNS_CRUSH_ADAPTIVE_Q": "1",
    },
}


@dataclass(frozen=True)
class RouteEliminationProbeResult:
    original_solution: Solution
    best_solution: Solution
    improved: bool
    original_route_count: int
    best_route_count: int
    original_cost: float
    best_cost: float
    attempts: int
    accepted_merges: int
    verdict: str


def cost_breakdown_row(
    instance_name: str,
    algorithm: str,
    seed: int,
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> dict[str, Any]:
    """Return a flat evidence row with complete evaluate() decomposition."""

    metrics = evaluate(solution, instance, carbon_profile, prices)
    violations = check_solution(solution, instance, prices)
    total = float(metrics["total_cost"])
    row: dict[str, Any] = {
        "instance": instance_name,
        "algorithm": algorithm,
        "seed": int(seed),
        "total_cost": total,
        "route_count": len(solution.routes),
        "ev_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
        "cv_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"),
        "all_cv_flag": not any(route.vehicle_type.lower() == "ev" for route in solution.routes),
        "charging_actions": len(solution.charging_actions),
        "violation_count": len(violations),
        "feasible": len(violations) == 0,
    }
    for field in COMPONENT_FIELDS:
        value = float(metrics.get(field, 0.0))
        row[field] = value
        row[f"{field}_share_pct"] = (value / total * 100.0) if abs(total) > 1e-12 else math.nan
    return row


def low_utilization_route_elimination_probe(
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    max_rounds: int = 3,
    beam_width: int = 8,
    max_route_attempts: int = 20,
    max_removed_customers: int = 3,
    max_seconds: float = 45.0,
) -> RouteEliminationProbeResult:
    """Try to remove weak routes and reinsert their customers into existing routes.

    This is a Phase 0 headroom probe, not a production search operator. It accepts
    a merge only when the final full solution is feasible, uses fewer routes, and
    has lower model cost.
    """

    original_cost = _solution_cost(solution, instance, carbon_profile, prices)
    best_solution = solution
    best_cost = original_cost
    attempts = 0
    accepted = 0
    deadline = time.perf_counter() + max(1.0, float(max_seconds))
    for _ in range(max(1, int(max_rounds))):
        improved_this_round = False
        for route_idx, route in _weak_route_order(best_solution, instance, carbon_profile, prices)[: max(1, int(max_route_attempts))]:
            if time.perf_counter() >= deadline:
                break
            if len(_route_customers(route, instance)) > max(1, int(max_removed_customers)):
                continue
            attempts += 1
            candidate = _try_eliminate_route(
                best_solution,
                route_idx,
                instance,
                carbon_profile,
                prices,
                beam_width=max(1, int(beam_width)),
            )
            if candidate is None:
                continue
            candidate_cost = _solution_cost(candidate, instance, carbon_profile, prices)
            if len(candidate.routes) < len(best_solution.routes) and candidate_cost < best_cost - 1e-9:
                best_solution = candidate
                best_cost = candidate_cost
                accepted += 1
                improved_this_round = True
                break
        if not improved_this_round:
            break
        if time.perf_counter() >= deadline:
            break

    improved = len(best_solution.routes) < len(solution.routes) and best_cost < original_cost - 1e-9
    verdict = "route_count_headroom_found" if improved else "route_count_not_reduced_by_probe"
    return RouteEliminationProbeResult(
        original_solution=solution,
        best_solution=best_solution,
        improved=improved,
        original_route_count=len(solution.routes),
        best_route_count=len(best_solution.routes),
        original_cost=original_cost,
        best_cost=best_cost,
        attempts=attempts,
        accepted_merges=accepted,
        verdict=verdict,
    )


def run_phase0(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seed: int = 1,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 300.0,
) -> dict[str, Any]:
    """Run Phase 0 diagnostics and write all artifacts under output_dir."""

    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "solutions").mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    _write_command_capture(root, out)
    grep_evidence = _grep_evidence(root)
    (out / "grep_evidence.json").write_text(json.dumps(grep_evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    breakdown_rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    headroom_rows: list[dict[str, Any]] = []
    references: dict[str, Any] = {"schema_version": "setp-alns-crush-reference-costs.v1", "seed": int(seed), "instances": {}}

    bundles = {instance_name: load_search_bundle(root / rel_dir) for instance_name, rel_dir in INSTANCE_DIRS.items()}
    warm_solutions = {instance_name: make_shared_initial_solution(bundle) for instance_name, bundle in bundles.items()}
    solutions_by_instance: dict[str, dict[str, Solution]] = {
        instance_name: {"warm_seed": warm}
        for instance_name, warm in warm_solutions.items()
    }
    tasks = [
        (instance_name, str(bundle.bundle_dir), algorithm, int(seed), int(eval_budget), float(max_runtime_seconds), warm_solutions[instance_name])
        for instance_name, bundle in bundles.items()
        for algorithm in ["scikit-opt-SA", "DR-ALNS", "ALNS-Wouda"]
    ]
    max_workers = max(1, min(len(tasks), int(os.environ.get("SETP_ALNS_PARALLEL_WORKERS", os.cpu_count() or 2))))
    if max_workers == 1:
        results = [_run_phase0_algorithm(task) for task in tasks]
    else:
        results = []
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_run_phase0_algorithm, task) for task in tasks]
            for future in as_completed(futures):
                results.append(future.result())
    for instance_name, algorithm, solution in results:
        solutions_by_instance.setdefault(instance_name, {})[algorithm] = solution

    for instance_name, bundle in bundles.items():
        solutions = solutions_by_instance[instance_name]
        references["instances"][instance_name] = {}
        for algorithm in ["warm_seed", "scikit-opt-SA", "DR-ALNS", "ALNS-Wouda"]:
            solution = solutions[algorithm]
            row = cost_breakdown_row(instance_name, algorithm, seed, solution, bundle.instance, bundle.carbon_profile)
            breakdown_rows.append(row)
            route_rows.append(
                {
                    "instance": instance_name,
                    "algorithm": algorithm,
                    "seed": int(seed),
                    "route_count": row["route_count"],
                    "ev_routes": row["ev_routes"],
                    "cv_routes": row["cv_routes"],
                    "all_cv_flag": row["all_cv_flag"],
                    "total_cost": row["total_cost"],
                    "feasible": row["feasible"],
                    "violation_count": row["violation_count"],
                }
            )
            references["instances"][instance_name][algorithm] = {
                "total_cost": row["total_cost"],
                "route_count": row["route_count"],
                "feasible": row["feasible"],
                "violation_count": row["violation_count"],
                "solution_path": f"solutions/{instance_name}_{algorithm}_seed{seed}.json",
            }
            _write_json(out / "solutions" / f"{instance_name}_{algorithm}_seed{seed}.json", _solution_to_dict(solution))

        for algorithm in ["warm_seed", "scikit-opt-SA", "DR-ALNS"]:
            probe = low_utilization_route_elimination_probe(
                solutions[algorithm],
                bundle.instance,
                bundle.carbon_profile,
                max_rounds=3,
                beam_width=8,
                max_route_attempts=20,
                max_removed_customers=3,
                max_seconds=45.0,
            )
            headroom_rows.append(
                {
                    "instance": instance_name,
                    "algorithm": algorithm,
                    "seed": int(seed),
                    "original_route_count": probe.original_route_count,
                    "best_route_count": probe.best_route_count,
                    "route_delta": probe.best_route_count - probe.original_route_count,
                    "original_cost": probe.original_cost,
                    "best_cost": probe.best_cost,
                    "cost_delta": probe.best_cost - probe.original_cost,
                    "attempts": probe.attempts,
                    "accepted_merges": probe.accepted_merges,
                    "improved": probe.improved,
                    "verdict": probe.verdict,
                }
            )
            _write_json(out / "solutions" / f"{instance_name}_{algorithm}_route_elimination_probe_seed{seed}.json", _solution_to_dict(probe.best_solution))

    _write_csv(out / "cost_breakdown.csv", breakdown_rows)
    _write_csv(out / "route_counts.csv", route_rows)
    _write_csv(out / "route_elimination_headroom.csv", headroom_rows)
    references["elapsed_seconds"] = time.perf_counter() - started
    _write_json(out / "reference_costs.json", references)
    report = _phase0_report(breakdown_rows, route_rows, headroom_rows, grep_evidence, references)
    (out / "phase0_report.md").write_text(report, encoding="utf-8")
    manifest = {
        "schema_version": "setp-alns-crush-phase0.v1",
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "elapsed_seconds": references["elapsed_seconds"],
        "outputs": [
            "reference_costs.json",
            "cost_breakdown.csv",
            "route_counts.csv",
            "route_elimination_headroom.csv",
            "grep_evidence.json",
            "phase0_report.md",
        ],
    }
    _write_json(out / "manifest.json", manifest)
    return {"gate": "PHASE0_COMPLETE", "manifest": str(out / "manifest.json"), "elapsed_seconds": references["elapsed_seconds"]}


def run_compare(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int],
    eval_budget: int,
    max_runtime_seconds: float,
    variant: str = "optimized",
    algorithms: list[str] | None = None,
    instance_names: list[str] | None = None,
    reference_path: str | Path | None = None,
    variant_flags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run isolated algorithm comparisons and write decomposed evidence."""

    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "solutions").mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    selected_algorithms = algorithms or list(ALGORITHMS)
    selected_instances = instance_names or [name for name in ALNS_DEFAULT_INSTANCE_ORDER if name in INSTANCE_DIRS]
    flags = dict(variant_flags or ABLATION_VARIANTS.get(variant, ABLATION_VARIANTS["local_search"]))
    references = _load_reference_costs(reference_path)
    tasks = [
        (
            str(root / INSTANCE_DIRS[instance_name]),
            instance_name,
            algorithm,
            int(seed),
            int(eval_budget),
            float(max_runtime_seconds),
            str(variant),
            flags,
        )
        for instance_name in selected_instances
        for seed in seeds
        for algorithm in selected_algorithms
    ]
    max_workers = max(1, min(len(tasks), int(os.environ.get("SETP_ALNS_PARALLEL_WORKERS", os.cpu_count() or 2))))
    if max_workers == 1:
        results = [_run_compare_algorithm(task) for task in tasks]
    else:
        results = []
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_run_compare_algorithm, task) for task in tasks]
            for future in as_completed(futures):
                results.append(future.result())
    rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda item: (item["instance"], item["seed"], item["algorithm"])):
        if result.get("error"):
            raise RuntimeError(f"{result['instance']} {result['algorithm']} seed {result['seed']} failed: {result['error']}")
        bundle = load_search_bundle(root / INSTANCE_DIRS[result["instance"]])
        solution = _solution_from_dict(result["solution"])
        row = cost_breakdown_row(result["instance"], result["algorithm"], int(result["seed"]), solution, bundle.instance, bundle.carbon_profile)
        row.update(
            {
                "variant": variant,
                "eval_budget": int(eval_budget),
                "run_elapsed_seconds": float(result["elapsed_seconds"]),
                "search_evaluations": int(result.get("evaluations", 0)),
                "gap_vs_sa_anchor_pct": _gap_vs_reference(row, references, result["instance"], "scikit-opt-SA"),
                "gap_vs_dr_anchor_pct": _gap_vs_reference(row, references, result["instance"], "DR-ALNS"),
                "gap_vs_algorithm_anchor_pct": _gap_vs_reference(row, references, result["instance"], result["algorithm"]),
            }
        )
        rows.append(row)
        route_rows.append(
            {
                "variant": variant,
                "instance": row["instance"],
                "algorithm": row["algorithm"],
                "seed": row["seed"],
                "route_count": row["route_count"],
                "total_cost": row["total_cost"],
                "feasible": row["feasible"],
                "violation_count": row["violation_count"],
                "all_cv_flag": row["all_cv_flag"],
            }
        )
        _write_json(out / "solutions" / f"{result['instance']}_{result['algorithm']}_{variant}_seed{result['seed']}.json", result["solution"])
    summary_rows = _summary_rows(rows)
    wilcoxon_rows = _wilcoxon_rows(rows)
    _write_csv(out / "cost_breakdown.csv", rows)
    _write_csv(out / "route_counts.csv", route_rows)
    _write_csv(out / "summary.csv", summary_rows)
    _write_csv(out / "wilcoxon_vs_sa.csv", wilcoxon_rows)
    manifest = {
        "schema_version": "setp-alns-crush-compare.v1",
        "variant": variant,
        "seeds": seeds,
        "algorithms": selected_algorithms,
        "instances": selected_instances,
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "reference_path": str(reference_path) if reference_path else "",
        "flags": flags,
        "elapsed_seconds": time.perf_counter() - started,
        "outputs": ["cost_breakdown.csv", "route_counts.csv", "summary.csv", "wilcoxon_vs_sa.csv", "solutions/"],
    }
    _write_json(out / "manifest.json", manifest)
    (out / "compare_report.md").write_text(_compare_report(summary_rows, wilcoxon_rows, rows, manifest), encoding="utf-8")
    return {"gate": "COMPARE_COMPLETE", "manifest": str(out / "manifest.json"), "elapsed_seconds": manifest["elapsed_seconds"]}


def run_phase2(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int],
    ablation_seeds: list[int],
    eval_budget: int,
    max_runtime_seconds: float,
    reference_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run Phase 2 optimized comparison plus staged ablation."""

    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    phase0_reference = Path(reference_path) if reference_path else root / "solver" / "reports" / "alns_crush" / "phase0" / "reference_costs.json"
    frozen_reference = out / "reference_costs.json"
    if phase0_reference.exists() and not frozen_reference.exists():
        shutil.copy2(phase0_reference, frozen_reference)
        frozen_reference.chmod(0o444)
    reference_for_runs = frozen_reference if frozen_reference.exists() else phase0_reference
    optimized = run_compare(
        root,
        out / "optimized",
        seeds=seeds,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        variant="local_search",
        reference_path=reference_for_runs,
    )
    ablation_results: list[dict[str, Any]] = []
    for variant in ["winner_kernel", "true_cost_repair", "route_elimination", "true_acceptance", "local_search"]:
        result = run_compare(
            root,
            out / "ablation" / variant,
            seeds=ablation_seeds,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            variant=variant,
            algorithms=["DR-ALNS", "ALNS-Wouda"],
            reference_path=reference_for_runs,
        )
        ablation_results.append({"variant": variant, **result})
    manifest = {
        "schema_version": "setp-alns-crush-phase2.v1",
        "seeds": seeds,
        "ablation_seeds": ablation_seeds,
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "reference_costs": str(reference_for_runs),
        "optimized": optimized,
        "ablation": ablation_results,
    }
    _write_json(out / "manifest.json", manifest)
    _write_phase2_rollup(out)
    return {"gate": "PHASE2_COMPLETE", "manifest": str(out / "manifest.json")}


def _phase0_solutions(
    bundle_dir: Path,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
) -> dict[str, Solution]:
    bundle = load_search_bundle(bundle_dir)
    warm = make_shared_initial_solution(bundle)
    sa = run_candidate(
        "scikit-opt-SA",
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        initial_solution=warm,
    )
    dr = run_candidate(
        "DR-ALNS",
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        initial_solution=warm,
    )
    alns = run_alns_wouda(
        bundle_dir,
        iterations=None,
        seed=seed,
        policy=SearchPolicy(require_charging_signal=False),
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        initial_solution=warm,
    )
    if sa.best_solution is None or dr.best_solution is None:
        raise RuntimeError("Phase 0 candidate run did not return a feasible best solution")
    return {
        "warm_seed": warm,
        "scikit-opt-SA": sa.best_solution,
        "DR-ALNS": dr.best_solution,
        "ALNS-Wouda": alns.best_solution,
    }


def _run_phase0_algorithm(task: tuple[str, str, str, int, int, float, Solution]) -> tuple[str, str, Solution]:
    instance_name, bundle_dir, algorithm, seed, eval_budget, max_runtime_seconds, warm = task
    bundle_path = Path(bundle_dir)
    if algorithm == "ALNS-Wouda":
        result = run_alns_wouda(
            bundle_path,
            iterations=None,
            seed=seed,
            policy=SearchPolicy(require_charging_signal=False),
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            initial_solution=warm,
        )
        return instance_name, algorithm, result.best_solution
    result = run_candidate(
        algorithm,
        bundle_path,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        initial_solution=warm,
    )
    if result.best_solution is None:
        raise RuntimeError(f"{algorithm} returned no feasible best solution for {instance_name}")
    return instance_name, algorithm, result.best_solution


def _run_compare_algorithm(task: tuple[str, str, str, int, int, float, str, dict[str, str]]) -> dict[str, Any]:
    bundle_dir, instance_name, algorithm, seed, eval_budget, max_runtime_seconds, variant, flags = task
    old_env = {name: os.environ.get(name) for name in CRUSH_FLAG_NAMES}
    try:
        for name, value in flags.items():
            os.environ[name] = str(value)
        started = time.perf_counter()
        bundle_path = Path(bundle_dir)
        bundle = load_search_bundle(bundle_path)
        warm = make_shared_initial_solution(bundle)
        if algorithm == "ALNS-Wouda":
            run = run_alns_wouda(
                bundle_path,
                iterations=None,
                seed=seed,
                policy=SearchPolicy(require_charging_signal=False),
                eval_budget=eval_budget,
                max_runtime_seconds=max_runtime_seconds,
                initial_solution=warm,
            )
            solution = run.best_solution
            evaluations = run.evaluations
        else:
            run = run_candidate(
                algorithm,
                bundle_path,
                seed=seed,
                eval_budget=eval_budget,
                max_runtime_seconds=max_runtime_seconds,
                initial_solution=warm,
            )
            if run.best_solution is None:
                raise RuntimeError("no feasible best_solution")
            solution = run.best_solution
            evaluations = run.evals
        return {
            "instance": instance_name,
            "algorithm": algorithm,
            "seed": int(seed),
            "variant": variant,
            "elapsed_seconds": time.perf_counter() - started,
            "evaluations": int(evaluations),
            "solution": _solution_to_dict(solution),
            "error": "",
        }
    except Exception as exc:  # pragma: no cover - experiment manifests preserve failures.
        return {
            "instance": instance_name,
            "algorithm": algorithm,
            "seed": int(seed),
            "variant": variant,
            "elapsed_seconds": 0.0,
            "evaluations": 0,
            "solution": _solution_to_dict(Solution()),
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _load_reference_costs(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    reference_path = Path(path)
    if not reference_path.exists():
        return {}
    return json.loads(reference_path.read_text(encoding="utf-8"))


def _gap_vs_reference(row: dict[str, Any], references: dict[str, Any], instance_name: str, algorithm: str) -> float:
    try:
        ref = float(references["instances"][instance_name][algorithm]["total_cost"])
    except Exception:
        return math.nan
    if abs(ref) <= 1e-12:
        return math.nan
    return (float(row["total_cost"]) - ref) / ref * 100.0


def _summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["variant"]), str(row["instance"]), str(row["algorithm"])), []).append(row)
    out: list[dict[str, Any]] = []
    for (variant, instance_name, algorithm), items in sorted(grouped.items()):
        costs = [float(row["total_cost"]) for row in items]
        routes = [float(row["route_count"]) for row in items]
        out.append(
            {
                "variant": variant,
                "instance": instance_name,
                "algorithm": algorithm,
                "n": len(items),
                "mean_total_cost": statistics.fmean(costs),
                "median_total_cost": statistics.median(costs),
                "best_total_cost": min(costs),
                "std_total_cost": statistics.stdev(costs) if len(costs) > 1 else 0.0,
                "mean_route_count": statistics.fmean(routes),
                "median_route_count": statistics.median(routes),
                "feasible_count": sum(1 for row in items if row["feasible"]),
                "zero_violation_count": sum(1 for row in items if int(row["violation_count"]) == 0),
                "mean_gap_vs_sa_anchor_pct": _safe_fmean([float(row["gap_vs_sa_anchor_pct"]) for row in items]),
                "mean_gap_vs_dr_anchor_pct": _safe_fmean([float(row["gap_vs_dr_anchor_pct"]) for row in items]),
            }
        )
    return out


def _safe_fmean(values: list[float]) -> float:
    finite = [value for value in values if math.isfinite(value)]
    return statistics.fmean(finite) if finite else math.nan


def _wilcoxon_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {(str(row["variant"]), str(row["instance"]), str(row["algorithm"]), int(row["seed"])): float(row["total_cost"]) for row in rows}
    variants = sorted({str(row["variant"]) for row in rows})
    instances = sorted({str(row["instance"]) for row in rows})
    algorithms = sorted({str(row["algorithm"]) for row in rows if str(row["algorithm"]) != "scikit-opt-SA"})
    out: list[dict[str, Any]] = []
    for variant in variants:
        for instance_name in instances:
            seeds = sorted({int(row["seed"]) for row in rows if str(row["variant"]) == variant and str(row["instance"]) == instance_name})
            baseline = [by_key.get((variant, instance_name, "scikit-opt-SA", seed)) for seed in seeds]
            for algorithm in algorithms:
                diffs = []
                for seed, base_cost in zip(seeds, baseline):
                    alg_cost = by_key.get((variant, instance_name, algorithm, seed))
                    if base_cost is None or alg_cost is None:
                        continue
                    diffs.append(float(alg_cost) - float(base_cost))
                if not diffs:
                    continue
                p_value, method = _wilcoxon_less(diffs)
                out.append(
                    {
                        "variant": variant,
                        "instance": instance_name,
                        "algorithm": algorithm,
                        "baseline": "scikit-opt-SA",
                        "n_pairs": len(diffs),
                        "mean_diff_alg_minus_sa": statistics.fmean(diffs),
                        "median_diff_alg_minus_sa": statistics.median(diffs),
                        "wins_alg_lower": sum(1 for value in diffs if value < -1e-9),
                        "p_value_less": p_value,
                        "method": method,
                    }
                )
    return out


def _wilcoxon_less(diffs: list[float]) -> tuple[float, str]:
    nonzero = [value for value in diffs if abs(value) > 1e-9]
    if not nonzero:
        return 1.0, "all_zero"
    try:
        from scipy.stats import wilcoxon

        result = wilcoxon(nonzero, alternative="less", zero_method="wilcox", method="auto")
        return float(result.pvalue), "scipy_wilcoxon_less"
    except Exception:
        wins = sum(1 for value in nonzero if value < 0.0)
        return _sign_test_pvalue_greater_equal(wins, len(nonzero)), "fallback_sign_test_less"


def _sign_test_pvalue_greater_equal(wins: int, n: int) -> float:
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / (2**n)


def _compare_report(summary_rows: list[dict[str, Any]], wilcoxon_rows: list[dict[str, Any]], rows: list[dict[str, Any]], manifest: dict[str, Any]) -> str:
    lines = [
        f"# ALNS Crush Compare: {manifest['variant']}",
        "",
        f"Seeds: {manifest['seeds']}; eval_budget={manifest['eval_budget']}; reference={manifest.get('reference_path', '')}",
        "",
        "## Summary",
        "",
    ]
    for row in summary_rows:
        lines.append(
            f"- {row['instance']} {row['algorithm']}: mean={row['mean_total_cost']:.6f}, "
            f"median={row['median_total_cost']:.6f}, best={row['best_total_cost']:.6f}, "
            f"std={row['std_total_cost']:.6f}, routes_mean={row['mean_route_count']:.3f}, "
            f"zero_viol={row['zero_violation_count']}/{row['n']}."
        )
    lines.extend(["", "## Paired Wilcoxon vs SA", ""])
    if wilcoxon_rows:
        for row in wilcoxon_rows:
            lines.append(
                f"- {row['instance']} {row['algorithm']}: mean_diff={row['mean_diff_alg_minus_sa']:.6f}, "
                f"wins={row['wins_alg_lower']}/{row['n_pairs']}, p_less={row['p_value_less']:.6g} ({row['method']})."
            )
    else:
        lines.append("- No paired SA rows available for this variant.")
    violations = [row for row in rows if int(row["violation_count"]) != 0]
    lines.extend(["", "## Feasibility Gate", ""])
    lines.append("- PASS: all reported rows have zero violations." if not violations else f"- FAIL: {len(violations)} rows have violations.")
    return "\n".join(lines)


def _write_phase2_rollup(out: Path) -> None:
    lines = ["# ALNS Crush Phase 2", "", "Generated from isolated compare/ablation artifacts.", ""]
    optimized_summary = out / "optimized" / "summary.csv"
    optimized_wilcoxon = out / "optimized" / "wilcoxon_vs_sa.csv"
    if optimized_summary.exists():
        lines.extend(["## Optimized Summary", "", optimized_summary.read_text(encoding="utf-8"), ""])
    if optimized_wilcoxon.exists():
        lines.extend(["## Optimized Wilcoxon", "", optimized_wilcoxon.read_text(encoding="utf-8"), ""])
    for variant in ["winner_kernel", "true_cost_repair", "route_elimination", "true_acceptance", "local_search"]:
        summary = out / "ablation" / variant / "summary.csv"
        if summary.exists():
            lines.extend([f"## Ablation {variant}", "", summary.read_text(encoding="utf-8"), ""])
    (out / "phase2_report.md").write_text("\n".join(lines), encoding="utf-8")


def _parse_seed_list(text: str) -> list[int]:
    seeds: list[int] = []
    for part in str(text).split(","):
        chunk = part.strip()
        if not chunk:
            continue
        if "-" in chunk:
            left, right = chunk.split("-", 1)
            seeds.extend(range(int(left), int(right) + 1))
        else:
            seeds.append(int(chunk))
    return sorted(dict.fromkeys(seeds))


def _try_eliminate_route(
    solution: Solution,
    route_idx: int,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
    *,
    beam_width: int,
) -> Solution | None:
    if len(solution.routes) < 2 or route_idx >= len(solution.routes):
        return None
    removed_route = solution.routes[route_idx]
    removed_customers = _route_customers(removed_route, instance)
    if not removed_customers:
        return None
    partial_routes = [route for idx, route in enumerate(solution.routes) if idx != route_idx]
    if not partial_routes:
        return None
    partial = Solution(
        routes=partial_routes,
        charging_actions=_actions_for_routes(solution.charging_actions, partial_routes),
        cross_site_services=list(solution.cross_site_services),
    )
    states = [partial]
    for customer_id in removed_customers:
        next_states: list[tuple[float, Solution]] = []
        for state in states:
            for candidate in _insert_customer_existing_route_options(state, customer_id, instance, carbon_profile, prices):
                score = _fast_solution_score(candidate, instance, prices)
                next_states.append((score, candidate))
        if not next_states:
            return None
        next_states.sort(key=lambda item: (item[0], _solution_key(item[1])))
        states = [item[1] for item in next_states[:beam_width]]

    feasible = [
        state
        for state in states
        if not check_solution(state, instance, prices) and len(state.routes) < len(solution.routes)
    ]
    if not feasible:
        return None
    return min(feasible, key=lambda item: (_solution_cost(item, instance, carbon_profile, prices), _solution_key(item)))


def _insert_customer_existing_route_options(
    solution: Solution,
    customer_id: str,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
) -> list[Solution]:
    options: list[Solution] = []
    for route_idx, route in enumerate(solution.routes):
        customers = _route_customers(route, instance)
        for pos in range(len(customers) + 1):
            candidate_customers = [*customers[:pos], customer_id, *customers[pos:]]
            built = _replace_route_customers(solution, route_idx, candidate_customers, instance, carbon_profile, prices)
            if built is not None:
                options.append(built)
    return options


def _replace_route_customers(
    solution: Solution,
    route_idx: int,
    customers: list[str],
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
) -> Solution | None:
    route = solution.routes[route_idx]
    clean = Route(route.vehicle_id, route.vehicle_type.lower(), route.home_depot_id, [route.home_depot_id, *customers, route.home_depot_id])
    route_actions: list[ChargingAction] = []
    if clean.vehicle_type == "ev":
        try:
            clean, route_actions = repair_route_charging(clean, instance, carbon_profile, prices)
        except ValueError:
            return None
    routes = list(solution.routes)
    routes[route_idx] = clean
    preserved_actions = [action for action in solution.charging_actions if action.vehicle_id != route.vehicle_id]
    return Solution(routes=routes, charging_actions=[*preserved_actions, *route_actions], cross_site_services=list(solution.cross_site_services))


def _weak_route_order(
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
) -> list[tuple[int, Route]]:
    scored: list[tuple[int, float, str, int, Route]] = []
    for idx, route in enumerate(solution.routes):
        customers = _route_customers(route, instance)
        if not customers:
            continue
        route_cost = _solution_cost(
            Solution(routes=[route], charging_actions=[action for action in solution.charging_actions if action.vehicle_id == route.vehicle_id]),
            instance,
            carbon_profile,
            prices,
        )
        scored.append((len(customers), -route_cost / max(1, len(customers)), route.vehicle_id, idx, route))
    scored.sort()
    return [(idx, route) for _, _, _, idx, route in scored]


def _route_customers(route: Route, instance: Instance) -> list[str]:
    node_type = {node.node_id: node.node_type.lower() for node in instance.nodes}
    return [node_id for node_id in route.node_sequence if node_type.get(node_id) == "c"]


def _actions_for_routes(actions: list[ChargingAction], routes: list[Route]) -> list[ChargingAction]:
    vehicle_ids = {route.vehicle_id for route in routes}
    route_nodes = {node_id for route in routes for node_id in route.node_sequence}
    return [action for action in actions if action.vehicle_id in vehicle_ids and action.station_id in route_nodes]


def _solution_cost(
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
) -> float:
    return float(evaluate(solution, instance, carbon_profile, prices)["total_cost"])


def _fast_solution_score(
    solution: Solution,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
) -> float:
    fixed = len(solution.routes) * _price(prices, "vehicle_fixed_cost")
    distance = sum(
        float(instance.distance(a, b))
        for route in solution.routes
        for a, b in zip(route.node_sequence, route.node_sequence[1:])
    )
    return fixed + (distance / 1000.0) * _price(prices, "c_km")


def _price(prices: PriceParameters | dict[str, float] | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def _solution_key(solution: Solution) -> tuple[Any, ...]:
    return tuple((route.vehicle_type.lower(), route.home_depot_id, tuple(route.node_sequence)) for route in solution.routes)


def _solution_to_dict(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [asdict(item) for item in solution.cross_site_services],
    }


def _solution_from_dict(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=[str(node_id) for node_id in row["node_sequence"]],
            )
            for row in payload.get("routes", [])
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id=str(row["vehicle_id"]),
                station_id=str(row["station_id"]),
                energy_kwh=float(row["energy_kwh"]),
                occupancy_minutes=float(row["occupancy_minutes"]),
                charge_start_second=float(row["charge_start_second"]),
            )
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(customer_id=str(row["customer_id"]), served_by_depot_id=str(row["served_by_depot_id"]))
            for row in payload.get("cross_site_services", [])
        ],
    )


def _grep_evidence(repo_root: Path) -> dict[str, list[str]]:
    checks = {
        "dr_repair_distance_score": ["rg", "-n", "_path_repair_delta_score|_route_sequence_distance", "solver/src/setp_solver/search/candidates.py"],
        "wouda_repair_distance_score": ["rg", "-n", "_delta_score|route_distance\\(|_route_distance", "solver/src/setp_solver/search/feasible_repair.py", "solver/src/setp_solver/search/alns_wouda.py"],
        "wouda_metropolis": ["rg", "-n", "math\\.exp\\(-delta|temperature \\*=", "solver/src/setp_solver/search/alns_wouda.py"],
    }
    out: dict[str, list[str]] = {}
    for name, cmd in checks.items():
        proc = subprocess.run(cmd, cwd=repo_root, text=True, capture_output=True, check=False)
        out[name] = [line for line in proc.stdout.splitlines() if line.strip()]
    return out


def _write_command_capture(repo_root: Path, out: Path) -> None:
    commands = {
        "git_status": ["git", "status", "--short"],
        "git_boundary": [
            "git",
            "diff",
            "--name-only",
            "--",
            "solver/src/setp_solver/cost.py",
            "solver/src/setp_solver/check.py",
            "solver/src/setp_solver/search/evaluation.py",
            "solver/src/setp_solver/search/alns_wouda.py",
            "solver/src/setp_solver/search/candidates.py",
            "solver/src/setp_solver/search/feasible_repair.py",
            "solver/tests/test_search.py",
        ],
    }
    for name, cmd in commands.items():
        proc = subprocess.run(cmd, cwd=repo_root, text=True, capture_output=True, check=False)
        (out / f"{name}.stdout.txt").write_text(proc.stdout, encoding="utf-8")
        (out / f"{name}.stderr.txt").write_text(proc.stderr, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({field for row in rows for field in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _phase0_report(
    breakdown_rows: list[dict[str, Any]],
    route_rows: list[dict[str, Any]],
    headroom_rows: list[dict[str, Any]],
    grep_evidence: dict[str, list[str]],
    references: dict[str, Any],
) -> str:
    lines = [
        "# ALNS Crush Phase 0",
        "",
        "This report is diagnostic-only and does not update formal E1-E7 outputs.",
        "",
        "## Fixed-Cost Dominance",
        "",
    ]
    for row in breakdown_rows:
        if row["algorithm"] not in {"warm_seed", "scikit-opt-SA", "DR-ALNS"}:
            continue
        lines.append(
            f"- {row['instance']} {row['algorithm']} seed {row['seed']}: "
            f"total={row['total_cost']:.6f}, routes={row['route_count']}, "
            f"cost_fix={row['cost_fix']:.6f} ({row['cost_fix_share_pct']:.3f}%)."
        )
    lines.extend(["", "## Route-Elimination Headroom", ""])
    for row in headroom_rows:
        label = "HEADROOM" if row["improved"] else "NO_ROUTE_COUNT_DROP_BY_PROBE"
        lines.append(
            f"- {row['instance']} {row['algorithm']}: {label}; "
            f"routes {row['original_route_count']} -> {row['best_route_count']}, "
            f"cost {row['original_cost']:.6f} -> {row['best_cost']:.6f}."
        )
    lines.extend(["", "## Grep Evidence", ""])
    for name, matches in grep_evidence.items():
        lines.append(f"- {name}: {len(matches)} matches")
    lines.extend(["", "## Frozen Anchors", "", "`reference_costs.json` contains the frozen denominators for later gap calculations.", ""])
    lines.append(f"Elapsed seconds: {float(references.get('elapsed_seconds', 0.0)):.3f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run isolated ALNS crush diagnostics.")
    parser.add_argument("stage", choices=["phase0", "compare", "quick_compare", "phase2"])
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[4]))
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parents[4] / "solver" / "reports" / "alns_crush" / "phase0"))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--seeds", default="1")
    parser.add_argument("--ablation-seeds", default="1")
    parser.add_argument("--eval-budget", type=int, default=16_000)
    parser.add_argument("--max-runtime-seconds", type=float, default=300.0)
    parser.add_argument("--reference-costs", default="")
    args = parser.parse_args(argv)
    if args.stage == "phase0":
        result = run_phase0(args.repo_root, args.output_dir, seed=args.seed, eval_budget=args.eval_budget, max_runtime_seconds=args.max_runtime_seconds)
        print(f"GATE ALNS_CRUSH_PHASE0 {result['gate']} {json.dumps(result, ensure_ascii=False)}")
    elif args.stage in {"compare", "quick_compare"}:
        result = run_compare(
            args.repo_root,
            args.output_dir,
            seeds=_parse_seed_list(args.seeds if args.stage == "compare" else str(args.seed)),
            eval_budget=args.eval_budget,
            max_runtime_seconds=args.max_runtime_seconds,
            variant="local_search",
            reference_path=args.reference_costs or None,
        )
        print(f"GATE ALNS_CRUSH_COMPARE {result['gate']} {json.dumps(result, ensure_ascii=False)}")
    elif args.stage == "phase2":
        result = run_phase2(
            args.repo_root,
            args.output_dir,
            seeds=_parse_seed_list(args.seeds),
            ablation_seeds=_parse_seed_list(args.ablation_seeds),
            eval_budget=args.eval_budget,
            max_runtime_seconds=args.max_runtime_seconds,
            reference_path=args.reference_costs or None,
        )
        print(f"GATE ALNS_CRUSH_PHASE2 {result['gate']} {json.dumps(result, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
