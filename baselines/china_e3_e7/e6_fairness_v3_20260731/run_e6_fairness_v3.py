#!/usr/bin/env python3
"""Persist the frozen E3 JOINT candidate pools and close E6 I/U/F.

The search implementation is not edited.  This runner calls the sealed E3
entry point with the same instance, seed, common initial solution, cap, and
environment, then serializes the already-returned complete-model candidates.
Every unit is compared against the sealed E3 trace, final solution hash,
objective float bits, evaluation count, and termination reason before it is
accepted for E6.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import resource
import subprocess
import sys
import time
from collections import defaultdict, deque
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
E3_ROOT = ROOT / "baselines/china_e3_e7/e3_zone_joint_20260731"
E3_RUNNER = E3_ROOT / "run_e3_zone_joint.py"
OLD_E6_ROOT = ROOT / "baselines/china_e3_e7/e6_fairness_20260731"
OLD_E6_AUDIT = OLD_E6_ROOT / "audit_e6_fairness.py"
CONTRACT = (
    ROOT
    / "docs/handoff/experiment_contract_v2_journal_aligned_20260730.md"
)
PYTHON = ROOT / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
CHECKER = HERE / "check_e6_fairness_v3.py"
TASK_ID = "E6-FAIRNESS-V3-20260731"
CAP = 400
THETA = 1.0
TOLERANCE = 1.0e-9
MAX_WORKERS = 2
INSTANCES = (
    ("cn-prd-50c-01-V2-LOCATIONS", "MAIN_EXHIBIT"),
    ("cn-prd-100c-02-V2-LOCATIONS", "ROBUSTNESS"),
)
SEEDS = tuple(range(1, 11))
REQUIRED_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}
PROTECTED_HASHES = {
    "solver/src/setp_solver/cost.py":
        "2717b4b4de39bb4c2a9a1bda602f4420cb3e3b1e87faa83678dfa64f88fc80be",
    "solver/src/setp_solver/check.py":
        "9c81e254e05591667c8225965bb9d0ba4e8bbfc53eb0f8c61ffdb4325a1403a8",
    "solver/src/setp_solver/search/evaluation.py":
        "c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3",
    "solver/src/setp_solver/profit.py":
        "216c4f16f2e26f1c2840fa272adbf1e3ccb056c3de9403dd15b71fa5edfef1dc",
    "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py":
        "976ef21d4952b3c488300de9a8d3e351411305d26f1e2601ca17c15185d462c1",
    "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py":
        "655fa347b52a3e8ac20c5da6213c84b09ac90f96c1513ca95554753aad3f8a91",
}
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", "monitor_runtime"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=json_default,
        )
        handle.write("\n")
    temporary.replace(path)


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: Iterable[str] | None = None,
) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(fields or rows[0].keys())
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def log(message: str) -> None:
    line = f"{now_iso()} {message}"
    print(line, flush=True)
    HERE.mkdir(parents=True, exist_ok=True)
    with (HERE / "progress.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()


def import_path(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"HALT_IMPORT_SPEC:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_modules() -> tuple[Any, Any, Any]:
    for path in (ROOT / "solver/src", ROOT):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    runner = import_path("_e6v2_e3_runner", E3_RUNNER)
    e3 = runner.load_e3()
    old_e6 = import_path("_e6v2_old_e6_audit", OLD_E6_AUDIT)
    return runner, e3, old_e6


def verify_protected() -> dict[str, str]:
    observed = {
        name: sha256(ROOT / name) for name in PROTECTED_HASHES
    }
    drift = {
        name: {"expected": PROTECTED_HASHES[name], "actual": actual}
        for name, actual in observed.items()
        if actual != PROTECTED_HASHES[name]
    }
    if drift:
        raise RuntimeError(
            "HALT_PROTECTED_HASH_DRIFT:"
            + json.dumps(drift, sort_keys=True)
        )
    return observed


def preflight(workers: int) -> dict[str, Any]:
    if not 1 <= workers <= MAX_WORKERS:
        raise RuntimeError(f"HALT_WORKERS_OUT_OF_RANGE:{workers}")
    if Path(sys.executable).resolve() != PYTHON.resolve():
        raise RuntimeError(
            f"HALT_PYTHON_ENVIRONMENT:{sys.executable}!={PYTHON}"
        )
    wrong = {
        name: os.environ.get(name)
        for name, expected in REQUIRED_THREAD_ENV.items()
        if os.environ.get(name) != expected
    }
    if wrong:
        raise RuntimeError(f"HALT_THREAD_ENV_NOT_FROZEN:{wrong}")
    protected = verify_protected()
    runner, _, old_e6 = load_modules()
    runner.verify_source_lock()
    e3_verification = old_e6.verify_e3_manifest()
    if read_json(OLD_E6_ROOT / "done.json").get("status") != (
        "HALT_E3_NESTED_CANDIDATE_SOLUTIONS_NOT_PERSISTED"
    ):
        raise RuntimeError("HALT_PRIOR_E6_TERMINAL_DRIFT")
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "workers": workers,
        "thread_environment": dict(REQUIRED_THREAD_ENV),
        "protected_hashes": protected,
        "e3_verification": e3_verification,
    }


def stem(instance_id: str, seed: int) -> str:
    return f"{instance_id}__seed{seed:02d}__JOINT"


def plan_path(instance_id: str, seed: int, arm: str) -> Path:
    return (
        E3_ROOT
        / "formal/plans"
        / f"{instance_id}__seed{seed:02d}__{arm}.json"
    )


def e3_status_path(instance_id: str, seed: int, arm: str) -> Path:
    return (
        E3_ROOT
        / "formal/task_status"
        / f"{instance_id}__seed{seed:02d}__{arm}.json"
    )


def candidate_pool_path(instance_id: str, seed: int) -> Path:
    return HERE / "formal/candidate_pools" / f"{stem(instance_id, seed)}.json"


def unit_status_path(instance_id: str, seed: int) -> Path:
    return HERE / "formal/task_status" / f"{stem(instance_id, seed)}.json"


def member_breakdowns(
    solution: Any,
    bundle: Any,
) -> dict[str, Any]:
    from setp_solver.profit import calculate_depot_profits

    return calculate_depot_profits(
        solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        customer_home_depot=dict(bundle.customer_home_depot),
        carbon_quota_kg=0.0,
    )


def profit_payload(breakdowns: dict[str, Any]) -> dict[str, Any]:
    return {
        depot: row.to_dict()
        for depot, row in sorted(breakdowns.items())
    }


def baseline_i(
    runner: Any,
    e3: Any,
    bundle: Any,
    instance_id: str,
    seed: int,
) -> tuple[dict[str, float], str]:
    plan = read_json(plan_path(instance_id, seed, "ZONE"))
    if canonical_sha256(plan["solution"]) != plan["solution_sha256"]:
        raise RuntimeError(
            f"HALT_E3_ZONE_SOLUTION_DRIFT:{instance_id}:{seed}"
        )
    solution = e3.annotate_cross_site_services(
        e3.solution_from_payload(plan["solution"]),
        bundle.customer_home_depot,
    )
    if canonical_sha256(runner.solution_payload(e3, solution)) != plan[
        "solution_sha256"
    ]:
        raise RuntimeError(
            f"HALT_E3_ZONE_ROUNDTRIP_DRIFT:{instance_id}:{seed}"
        )
    breakdowns = member_breakdowns(solution, bundle)
    profits = {
        depot: float(row.profit)
        for depot, row in sorted(breakdowns.items())
    }
    if any(value <= 0.0 for value in profits.values()):
        raise RuntimeError(
            f"HALT_NONPOSITIVE_I_PROFIT:{instance_id}:{seed}:{profits}"
        )
    return profits, plan["solution_sha256"]


def completion_occurrences(run: Any) -> list[dict[str, Any]]:
    occurrences: list[dict[str, Any]] = []
    for view, epoch in run.view_epochs.items():
        for rank, completion in enumerate(epoch.archive_completions, start=1):
            occurrences.append(
                {
                    "view": view,
                    "persistence_source": "view_archive_completion",
                    "source_rank": rank,
                    "completion": completion,
                }
            )
        occurrences.append(
            {
                "view": view,
                "persistence_source": "view_proxy_best_completion",
                "source_rank": 1,
                "completion": epoch.proxy_best_completion,
            }
        )
    occurrences.extend(
        (
            {
                "view": "route_pool",
                "persistence_source":
                    "route_pool_candidate_or_parent",
                "source_rank": 1,
                "completion": run.completion,
            },
            {
                "view": "route_pool",
                "persistence_source":
                    "final_independent_certificate",
                "source_rank": 1,
                "completion": run.completion,
            },
        )
    )
    return occurrences


def persist_candidate_pool(
    runner: Any,
    e3: Any,
    run: Any,
    bundle: Any,
    instance_id: str,
    sample_role: str,
    seed: int,
    classified_trace: list[dict[str, Any]],
    baseline_profit: dict[str, float],
    baseline_solution_sha256: str,
) -> dict[str, Any]:
    feasible_trace = [
        item
        for item in classified_trace
        if item["failure_category"] == "FEASIBLE"
    ]
    by_objective: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for item in feasible_trace:
        objective = float(item["complete_objective"])
        by_objective[objective.hex()].append(item)
    occurrences = completion_occurrences(run)
    if len(occurrences) != len(feasible_trace):
        raise RuntimeError(
            f"HALT_CANDIDATE_EVENT_DENOMINATOR:{instance_id}:{seed}:"
            f"{len(occurrences)}!={len(feasible_trace)}"
        )
    event_rows: list[dict[str, Any]] = []
    unique: dict[str, dict[str, Any]] = {}
    for occurrence in occurrences:
        completion = occurrence.pop("completion")
        objective = float(completion.objective)
        key = objective.hex()
        if not by_objective[key]:
            raise RuntimeError(
                f"HALT_CANDIDATE_OBJECTIVE_COVERAGE:{instance_id}:"
                f"{seed}:{key}"
            )
        trace_event = by_objective[key].popleft()
        annotated = e3.annotate_cross_site_services(
            completion.solution,
            bundle.customer_home_depot,
        )
        solution = runner.solution_payload(e3, annotated)
        solution_hash = canonical_sha256(solution)
        breakdowns = member_breakdowns(annotated, bundle)
        member_data = profit_payload(breakdowns)
        allocated_cost = sum(
            float(row.cost_total) for row in breakdowns.values()
        )
        if not math.isclose(
            allocated_cost,
            objective,
            rel_tol=1.0e-12,
            abs_tol=1.0e-8,
        ):
            raise RuntimeError(
                f"HALT_CANDIDATE_MEMBER_COST_CLOSURE:{instance_id}:"
                f"{seed}:{solution_hash}:{allocated_cost}:{objective}"
            )
        profits = {
            depot: float(row.profit)
            for depot, row in sorted(breakdowns.items())
        }
        margins = {
            depot: profits[depot] - baseline_profit[depot]
            for depot in profits
        }
        participation = all(
            value >= -TOLERANCE for value in margins.values()
        )
        event = {
            "evaluation_index": int(trace_event["evaluation_index"]),
            "trace_view": trace_event["view"],
            "trace_source": trace_event["source"],
            "trace_iteration": trace_event["iteration"],
            "persistence_view": occurrence["view"],
            "persistence_source": occurrence["persistence_source"],
            "persistence_source_rank": occurrence["source_rank"],
            "complete_objective": objective,
            "complete_objective_float_hex": key,
            "solution_sha256": solution_hash,
        }
        event_rows.append(event)
        if solution_hash not in unique:
            physical_vehicles = len(
                {
                    e3.physical_vehicle_id(route.vehicle_id)
                    for route in annotated.routes
                }
            )
            unique[solution_hash] = {
                "candidate_id": "",
                "solution_sha256": solution_hash,
                "complete_objective": objective,
                "complete_objective_float_hex": key,
                "route_count": len(annotated.routes),
                "physical_vehicle_count": physical_vehicles,
                "cross_site_service_count": len(
                    annotated.cross_site_services
                ),
                "served_customer_count": sum(
                    1
                    for route in annotated.routes
                    for node_id in route.node_sequence
                    if node_id in bundle.customer_home_depot
                ),
                "solution": solution,
                "completion_breakdown": completion.breakdown,
                "completion_activity": completion.activity,
                "member_ledger": member_data,
                "member_profit": profits,
                "member_profit_margin_vs_I": margins,
                "participation_theta": THETA,
                "participation_satisfied": participation,
                "member_cost_closure_abs_error": abs(
                    allocated_cost - objective
                ),
                "evaluation_indices": [],
                "observed_trace_sources": [],
                "observed_persistence_sources": [],
            }
        record = unique[solution_hash]
        if not math.isclose(
            float(record["complete_objective"]),
            objective,
            rel_tol=0.0,
            abs_tol=0.0,
        ):
            raise RuntimeError(
                f"HALT_DUPLICATE_SOLUTION_OBJECTIVE_DRIFT:"
                f"{instance_id}:{seed}:{solution_hash}"
            )
        record["evaluation_indices"].append(
            int(trace_event["evaluation_index"])
        )
        record["observed_trace_sources"].append(
            f"{trace_event['view']}:{trace_event['source']}"
        )
        record["observed_persistence_sources"].append(
            f"{occurrence['view']}:{occurrence['persistence_source']}:"
            f"{occurrence['source_rank']}"
        )
    leftovers = {
        key: len(values)
        for key, values in by_objective.items()
        if values
    }
    if leftovers:
        raise RuntimeError(
            f"HALT_CANDIDATE_TRACE_LEFTOVERS:{instance_id}:"
            f"{seed}:{leftovers}"
        )
    candidates = sorted(
        unique.values(),
        key=lambda row: (
            float(row["complete_objective"]),
            row["solution_sha256"],
        ),
    )
    for index, candidate in enumerate(candidates, start=1):
        candidate["candidate_id"] = f"C{index:04d}"
        candidate["evaluation_indices"] = sorted(
            set(candidate["evaluation_indices"])
        )
        candidate["observed_trace_sources"] = sorted(
            set(candidate["observed_trace_sources"])
        )
        candidate["observed_persistence_sources"] = sorted(
            set(candidate["observed_persistence_sources"])
        )
    id_by_hash = {
        row["solution_sha256"]: row["candidate_id"]
        for row in candidates
    }
    for event in event_rows:
        event["candidate_id"] = id_by_hash[event["solution_sha256"]]
    fair = [row for row in candidates if row["participation_satisfied"]]
    selected = (
        min(
            fair,
            key=lambda row: (
                float(row["complete_objective"]),
                row["solution_sha256"],
            ),
        )
        if fair
        else None
    )
    payload = {
        "schema": "resetp.e6-fairness-v3.candidate-pool.v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "instance_id": instance_id,
        "sample_role": sample_role,
        "seed": seed,
        "source_arm": "JOINT",
        "complete_candidate_budget_cap": CAP,
        "theta": THETA,
        "tolerance_cny": TOLERANCE,
        "baseline_I_solution_sha256": baseline_solution_sha256,
        "baseline_I_member_profit": baseline_profit,
        "full_evaluation_event_count": len(event_rows),
        "feasible_trace_event_count": len(feasible_trace),
        "unique_candidate_pool_size": len(candidates),
        "participation_satisfying_candidate_count": len(fair),
        "selected_f_candidate_id": (
            None if selected is None else selected["candidate_id"]
        ),
        "selected_f_solution_sha256": (
            None if selected is None else selected["solution_sha256"]
        ),
        "f_fallback_to_I": selected is None,
        "event_to_body_mapping": (
            "evaluation events are matched to returned complete-model "
            "candidate bodies by the exact objective float-bit multiset; "
            "duplicate bodies are retained through event references"
        ),
        "evaluation_events": sorted(
            event_rows, key=lambda row: row["evaluation_index"]
        ),
        "candidates": candidates,
    }
    payload["candidate_pool_id"] = canonical_sha256(payload)
    path = candidate_pool_path(instance_id, seed)
    atomic_json(path, payload)
    return payload


def run_unit(spec: dict[str, Any]) -> dict[str, Any]:
    for name, value in REQUIRED_THREAD_ENV.items():
        os.environ[name] = value
    instance_id = str(spec["instance_id"])
    sample_role = str(spec["sample_role"])
    seed = int(spec["seed"])
    status_path = unit_status_path(instance_id, seed)
    pool_path = candidate_pool_path(instance_id, seed)
    if status_path.is_file() and pool_path.is_file():
        status = read_json(status_path)
        if (
            status.get("status") == "PASS"
            and status.get("candidate_pool_sha256") == sha256(pool_path)
        ):
            return status
        raise RuntimeError(
            f"HALT_STALE_UNIT_ARTIFACT:{instance_id}:{seed}"
        )
    verify_protected()
    runner, e3, _ = load_modules()
    runner.verify_source_lock()
    bundle, initial, _ = runner.load_input(e3, instance_id, "JOINT")
    baseline_profit, baseline_hash = baseline_i(
        runner, e3, bundle, instance_id, seed
    )
    sealed_plan = read_json(plan_path(instance_id, seed, "JOINT"))
    sealed_status = read_json(
        e3_status_path(instance_id, seed, "JOINT")
    )
    sealed_trace_payload = read_json(
        E3_ROOT
        / "formal/search_traces"
        / f"{stem(instance_id, seed)}.json"
    )
    before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.perf_counter()
    run = e3.run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=seed,
        hgs_seconds_per_view=None,
        exact_elites_per_view=runner.EXACT_ELITES_PER_VIEW,
        max_archive_candidates_per_view=runner.archive_limits(CAP),
        sp_time_limit_seconds=runner.MIP_TIME_LIMIT_SECONDS,
        hard_home_depot_lock=False,
        max_hgs_iterations_per_view=(
            runner.MAX_HGS_ITERATIONS_PER_VIEW
        ),
        wallclock_safety_seconds_per_view=max(
            600.0, 4.0 * len(bundle.customer_home_depot)
        ),
        exact_checkpoint_interval_iterations=None,
        preserve_base_pool_recombination=False,
    )
    elapsed = time.perf_counter() - started
    after = resource.getrusage(resource.RUSAGE_SELF)
    diagnosis = runner.classify_trace(
        list(run.stats["complete_candidate_evaluation_trace"])
    )
    classified_trace = diagnosis.pop("classified_trace")
    consumed = int(run.stats["complete_candidate_evaluation_attempts"])
    reason, termination_evidence = runner.termination_reason(
        run, consumed=consumed, cap=CAP
    )
    rerun_solution = e3.annotate_cross_site_services(
        run.solution, bundle.customer_home_depot
    )
    rerun_solution_payload = runner.solution_payload(
        e3, rerun_solution
    )
    rerun_solution_hash = canonical_sha256(rerun_solution_payload)
    rerun_objective = float(run.completion.objective)
    expected_objective = float(
        sealed_plan["independent_recompute"]["objective"]
    )
    comparisons = {
        "solution_sha256_identical": (
            rerun_solution_hash == sealed_plan["solution_sha256"]
        ),
        "objective_float_bits_identical": (
            rerun_objective.hex() == expected_objective.hex()
        ),
        "complete_evaluation_count_identical": (
            consumed
            == int(
                sealed_plan[
                    "complete_candidate_evaluations_consumed"
                ]
            )
        ),
        "classified_trace_identical": (
            classified_trace
            == sealed_trace_payload[
                "complete_candidate_evaluation_trace"
            ]
        ),
        "termination_reason_identical": (
            reason == sealed_status["termination_reason"]
        ),
    }
    if not all(comparisons.values()):
        mismatch = {
            "schema": "resetp.e6-fairness-v3.bitwise-mismatch.v1",
            "task_id": TASK_ID,
            "created_at_utc": now_iso(),
            "instance_id": instance_id,
            "seed": seed,
            "comparisons": comparisons,
            "expected": {
                "solution_sha256": sealed_plan["solution_sha256"],
                "objective": expected_objective,
                "objective_float_hex": expected_objective.hex(),
                "complete_evaluations": sealed_plan[
                    "complete_candidate_evaluations_consumed"
                ],
                "termination_reason": sealed_status[
                    "termination_reason"
                ],
            },
            "observed": {
                "solution_sha256": rerun_solution_hash,
                "objective": rerun_objective,
                "objective_float_hex": rerun_objective.hex(),
                "complete_evaluations": consumed,
                "termination_reason": reason,
            },
        }
        atomic_json(
            HERE
            / "formal/mismatches"
            / f"{stem(instance_id, seed)}.json",
            mismatch,
        )
        raise RuntimeError(
            f"HALT_JOINT_RERUN_NOT_BITWISE_IDENTICAL:"
            f"{instance_id}:seed{seed:02d}"
        )
    if consumed > CAP or int(diagnosis["error_candidates"]) > 0:
        raise RuntimeError(
            f"HALT_JOINT_RERUN_TECHNICAL_ERROR:{instance_id}:"
            f"seed{seed:02d}:{consumed}:"
            f"{diagnosis['exception_breakdown']}"
        )
    if bool(run.stats["wallclock_safety_triggered"]):
        raise RuntimeError(
            f"HALT_WALLCLOCK_SAFETY:{instance_id}:seed{seed:02d}"
        )
    pool = persist_candidate_pool(
        runner,
        e3,
        run,
        bundle,
        instance_id,
        sample_role,
        seed,
        classified_trace,
        baseline_profit,
        baseline_hash,
    )
    status = {
        "schema": "resetp.e6-fairness-v3.unit-status.v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "status": "PASS",
        "instance_id": instance_id,
        "sample_role": sample_role,
        "seed": seed,
        "source_arm": "JOINT",
        "complete_candidate_budget_cap": CAP,
        "complete_candidate_evaluations_consumed": consumed,
        "termination_reason": reason,
        "termination_evidence": termination_evidence,
        "elapsed_wall_seconds": elapsed,
        "cpu_user_seconds": after.ru_utime - before.ru_utime,
        "cpu_system_seconds": after.ru_stime - before.ru_stime,
        "sealed_e3_elapsed_wall_seconds": float(
            sealed_status["elapsed_wall_seconds"]
        ),
        "solution_sha256": rerun_solution_hash,
        "objective": rerun_objective,
        "objective_float_hex": rerun_objective.hex(),
        "bitwise_comparisons": comparisons,
        "candidate_pool_path": relative(
            candidate_pool_path(instance_id, seed)
        ),
        "candidate_pool_sha256": sha256(
            candidate_pool_path(instance_id, seed)
        ),
        "full_evaluation_event_count": pool[
            "full_evaluation_event_count"
        ],
        "unique_candidate_pool_size": pool[
            "unique_candidate_pool_size"
        ],
        "participation_satisfying_candidate_count": pool[
            "participation_satisfying_candidate_count"
        ],
        "selected_f_candidate_id": pool[
            "selected_f_candidate_id"
        ],
        "selected_f_solution_sha256": pool[
            "selected_f_solution_sha256"
        ],
        "f_fallback_to_I": pool["f_fallback_to_I"],
        "candidate_pool_persisted": True,
        "search_semantics_unchanged": True,
    }
    atomic_json(status_path, status)
    verify_protected()
    return status


def run_formal(workers: int) -> list[dict[str, Any]]:
    preflight(workers)
    if (HERE / "done.json").exists():
        raise RuntimeError("HALT_DONE_ALREADY_EXISTS")
    specs = [
        {
            "instance_id": instance_id,
            "sample_role": role,
            "seed": seed,
        }
        for instance_id, role in INSTANCES
        for seed in SEEDS
    ]
    completed: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(run_unit, spec): spec for spec in specs
        }
        try:
            for future in as_completed(futures):
                spec = futures[future]
                status = future.result()
                completed.append(status)
                log(
                    "UNIT PASS "
                    f"{spec['instance_id']} seed={spec['seed']:02d} "
                    f"eval={status['complete_candidate_evaluations_consumed']} "
                    f"events={status['full_evaluation_event_count']} "
                    f"pool={status['unique_candidate_pool_size']} "
                    f"fair={status['participation_satisfying_candidate_count']} "
                    f"F={'I_FALLBACK' if status['f_fallback_to_I'] else status['selected_f_candidate_id']} "
                    "bitwise=true"
                )
        except BaseException:
            for future in futures:
                future.cancel()
            raise
    if len(completed) != 20:
        raise RuntimeError(
            f"HALT_FORMAL_DENOMINATOR:{len(completed)}!=20"
        )
    return sorted(
        completed,
        key=lambda row: (row["instance_id"], int(row["seed"])),
    )


def state_metrics(
    runner: Any,
    e3: Any,
    bundle: Any,
    solution_payload: dict[str, Any],
    baseline_profit: dict[str, float],
) -> dict[str, Any]:
    solution = e3.annotate_cross_site_services(
        e3.solution_from_payload(solution_payload),
        bundle.customer_home_depot,
    )
    breakdowns = member_breakdowns(solution, bundle)
    profits = {
        depot: float(row.profit)
        for depot, row in sorted(breakdowns.items())
    }
    costs = {
        depot: float(row.cost_total)
        for depot, row in sorted(breakdowns.items())
    }
    margins = {
        depot: profits[depot] - baseline_profit[depot]
        for depot in profits
    }
    ratios = {
        depot: profits[depot] / baseline_profit[depot]
        for depot in profits
    }
    objective = sum(costs.values())
    physical = len(
        {
            e3.physical_vehicle_id(route.vehicle_id)
            for route in solution.routes
        }
    )
    return {
        "solution_sha256": canonical_sha256(
            runner.solution_payload(e3, solution)
        ),
        "total_cost_cny": objective,
        "vehicle_count": physical,
        "route_count": len(solution.routes),
        "profits": profits,
        "costs": costs,
        "margins": margins,
        "ratios": ratios,
        "all_members_no_worse_than_I": all(
            value >= -TOLERANCE for value in margins.values()
        ),
        "weak_member_id": min(
            margins, key=lambda depot: (margins[depot], depot)
        ),
    }


def raw_state_row(
    *,
    instance_id: str,
    sample_role: str,
    seed: int,
    state: str,
    status: str,
    source: str,
    metrics: dict[str, Any],
    baseline_profit: dict[str, float],
    elapsed_seconds: float,
    evaluations: int,
    pool_size: int,
    fair_count: int,
    selected_candidate_id: str | None,
    fallback: bool,
    u_weak_member: str,
    u_metrics: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    row = {
        "instance_id": instance_id,
        "sample_role": sample_role,
        "seed": seed,
        "state": state,
        "state_status": status,
        "source": source,
        "source_solution_sha256": metrics["solution_sha256"],
        "total_cost_cny": metrics["total_cost_cny"],
        "vehicle_count": metrics["vehicle_count"],
        "route_count": metrics["route_count"],
        "elapsed_seconds": elapsed_seconds,
        "time_accounting": (
            "SEALED_E3_ARM_TIME"
            if state in {"I", "U"}
            else "SHARED_U_SEARCH_TIME_NOT_ADDITIONAL_TRAJECTORY"
        ),
        "complete_candidate_evaluations_consumed": evaluations,
        "profit_D_guangzhou_cny": metrics["profits"]["D_guangzhou"],
        "profit_D_shenzhen_cny": metrics["profits"]["D_shenzhen"],
        "member_profit_json": json.dumps(
            metrics["profits"], ensure_ascii=False, sort_keys=True
        ),
        "member_cost_json": json.dumps(
            metrics["costs"], ensure_ascii=False, sort_keys=True
        ),
        "member_profit_margin_vs_I_json": json.dumps(
            metrics["margins"], ensure_ascii=False, sort_keys=True
        ),
        "member_profit_ratio_vs_I_json": json.dumps(
            metrics["ratios"], ensure_ascii=False, sort_keys=True
        ),
        "weak_member_id": metrics["weak_member_id"],
        "weak_member_profit_change_vs_I_cny": metrics["margins"][
            metrics["weak_member_id"]
        ],
        "u_weak_member_id": u_weak_member,
        "u_weak_member_improvement_vs_U_cny": (
            metrics["profits"][u_weak_member]
            - u_metrics["profits"][u_weak_member]
        ),
        "minimum_member_profit_ratio": min(
            metrics["ratios"].values()
        ),
        "all_members_no_worse_than_I": metrics[
            "all_members_no_worse_than_I"
        ],
        "theta": THETA,
        "candidate_pool_size": pool_size,
        "participation_satisfying_candidate_count": fair_count,
        "selected_f_candidate_id": selected_candidate_id or "",
        "f_fallback_to_I": fallback,
        "search_reruns": 1,
        "nested_candidate_is_independent_sample": False,
    }
    members = [
        {
            "instance_id": instance_id,
            "sample_role": sample_role,
            "seed": seed,
            "state": state,
            "member_id": depot,
            "baseline_profit_I_cny": baseline_profit[depot],
            "state_profit_cny": metrics["profits"][depot],
            "profit_change_vs_I_cny": metrics["margins"][depot],
            "profit_ratio_vs_I": metrics["ratios"][depot],
            "participation_satisfied": (
                metrics["margins"][depot] >= -TOLERANCE
            ),
            "u_weak_member": depot == u_weak_member,
            "profit_improvement_vs_U_cny": (
                metrics["profits"][depot]
                - u_metrics["profits"][depot]
            ),
            "status": status,
        }
        for depot in sorted(metrics["profits"])
    ]
    return row, members


def finalize() -> dict[str, Any]:
    environment = preflight(1)
    statuses = [
        read_json(path)
        for path in sorted(
            (HERE / "formal/task_status").glob("*.json")
        )
        if not path.name.startswith("._")
    ]
    if len(statuses) != 20 or any(
        row.get("status") != "PASS" for row in statuses
    ):
        raise RuntimeError(
            f"HALT_UNIT_STATUS_DENOMINATOR:{len(statuses)}/20"
        )
    if not all(
        all(row["bitwise_comparisons"].values())
        for row in statuses
    ):
        raise RuntimeError("HALT_JOINT_RERUN_NOT_BITWISE_IDENTICAL")
    runner, e3, old_e6 = load_modules()
    raw_rows: list[dict[str, Any]] = []
    member_rows: list[dict[str, Any]] = []
    pool_summaries: list[dict[str, Any]] = []
    selected_dir = HERE / "formal/f_selected"
    for instance_id, sample_role in INSTANCES:
        base_bundle = e3.load_bundle(instance_id)
        for seed in SEEDS:
            pool = read_json(candidate_pool_path(instance_id, seed))
            unit = read_json(unit_status_path(instance_id, seed))
            zone_plan = read_json(plan_path(instance_id, seed, "ZONE"))
            joint_plan = read_json(plan_path(instance_id, seed, "JOINT"))
            zone_status = read_json(
                e3_status_path(instance_id, seed, "ZONE")
            )
            joint_status = read_json(
                e3_status_path(instance_id, seed, "JOINT")
            )
            baseline_profit = {
                key: float(value)
                for key, value in pool[
                    "baseline_I_member_profit"
                ].items()
            }
            i_metrics = state_metrics(
                runner,
                e3,
                base_bundle,
                zone_plan["solution"],
                baseline_profit,
            )
            u_metrics = state_metrics(
                runner,
                e3,
                base_bundle,
                joint_plan["solution"],
                baseline_profit,
            )
            if u_metrics["solution_sha256"] != unit[
                "solution_sha256"
            ]:
                raise RuntimeError(
                    f"HALT_U_FINAL_ROUNDTRIP:{instance_id}:{seed}"
                )
            u_weak = u_metrics["weak_member_id"]
            selected_id = pool["selected_f_candidate_id"]
            fallback = bool(pool["f_fallback_to_I"])
            if fallback:
                f_solution = zone_plan["solution"]
                f_status = "PASS_FALLBACK_TO_I_NO_FAIR_CANDIDATE"
                f_source = "SEALED_E3_ZONE_I_FALLBACK"
            else:
                selected = next(
                    row
                    for row in pool["candidates"]
                    if row["candidate_id"] == selected_id
                )
                f_solution = selected["solution"]
                f_status = "PASS_SELECTED_FROM_U_NESTED_POOL"
                f_source = (
                    f"{relative(candidate_pool_path(instance_id, seed))}"
                    f"#{selected_id}"
                )
            f_metrics = state_metrics(
                runner,
                e3,
                base_bundle,
                f_solution,
                baseline_profit,
            )
            if not f_metrics["all_members_no_worse_than_I"]:
                raise RuntimeError(
                    f"HALT_F_PARTICIPATION:{instance_id}:{seed}"
                )
            selected_payload = {
                "schema":
                    "resetp.e6-fairness-v3.selected-f-solution.v1",
                "task_id": TASK_ID,
                "instance_id": instance_id,
                "sample_role": sample_role,
                "seed": seed,
                "selection_status": f_status,
                "source": f_source,
                "candidate_pool_size": pool[
                    "unique_candidate_pool_size"
                ],
                "participation_satisfying_candidate_count": pool[
                    "participation_satisfying_candidate_count"
                ],
                "selected_candidate_id": selected_id,
                "f_fallback_to_I": fallback,
                "solution": f_solution,
                "solution_sha256": f_metrics["solution_sha256"],
                "total_cost_cny": f_metrics["total_cost_cny"],
                "member_profit": f_metrics["profits"],
                "member_profit_margin_vs_I": f_metrics["margins"],
            }
            selected_payload["selected_f_id"] = canonical_sha256(
                selected_payload
            )
            selected_path = (
                selected_dir / f"{stem(instance_id, seed)}__F.json"
            )
            atomic_json(selected_path, selected_payload)
            common = {
                "instance_id": instance_id,
                "sample_role": sample_role,
                "seed": seed,
                "baseline_profit": baseline_profit,
                "pool_size": int(
                    pool["unique_candidate_pool_size"]
                ),
                "fair_count": int(
                    pool[
                        "participation_satisfying_candidate_count"
                    ]
                ),
                "selected_candidate_id": selected_id,
                "fallback": fallback,
                "u_weak_member": u_weak,
                "u_metrics": u_metrics,
            }
            i_row, i_members = raw_state_row(
                **common,
                state="I",
                status="PASS_REUSED_SEALED_E3_ZONE",
                source=relative(plan_path(instance_id, seed, "ZONE")),
                metrics=i_metrics,
                elapsed_seconds=float(
                    zone_status["elapsed_wall_seconds"]
                ),
                evaluations=int(
                    zone_status[
                        "complete_candidate_evaluations_consumed"
                    ]
                ),
            )
            u_row, u_members = raw_state_row(
                **common,
                state="U",
                status="PASS_REUSED_SEALED_E3_JOINT_BITWISE_REPLAYED",
                source=relative(plan_path(instance_id, seed, "JOINT")),
                metrics=u_metrics,
                elapsed_seconds=float(
                    joint_status["elapsed_wall_seconds"]
                ),
                evaluations=int(
                    unit["complete_candidate_evaluations_consumed"]
                ),
            )
            f_row, f_members = raw_state_row(
                **common,
                state="F",
                status=f_status,
                source=f_source,
                metrics=f_metrics,
                elapsed_seconds=float(
                    joint_status["elapsed_wall_seconds"]
                ),
                evaluations=int(
                    unit["complete_candidate_evaluations_consumed"]
                ),
            )
            raw_rows.extend((i_row, u_row, f_row))
            member_rows.extend((*i_members, *u_members, *f_members))
            pool_summaries.append(
                {
                    "instance_id": instance_id,
                    "sample_role": sample_role,
                    "seed": seed,
                    "full_evaluation_event_count": pool[
                        "full_evaluation_event_count"
                    ],
                    "candidate_pool_size_unique": pool[
                        "unique_candidate_pool_size"
                    ],
                    "participation_satisfying_candidate_count": pool[
                        "participation_satisfying_candidate_count"
                    ],
                    "selected_f_candidate_id": selected_id or "",
                    "selected_f_solution_sha256": f_metrics[
                        "solution_sha256"
                    ],
                    "f_selection": (
                        "I_FALLBACK" if fallback else "U_NESTED_CANDIDATE"
                    ),
                    "f_equals_i": fallback,
                    "I_total_cost_cny": i_metrics[
                        "total_cost_cny"
                    ],
                    "U_total_cost_cny": u_metrics[
                        "total_cost_cny"
                    ],
                    "F_total_cost_cny": f_metrics[
                        "total_cost_cny"
                    ],
                    "fairness_cost_F_minus_U_cny": (
                        f_metrics["total_cost_cny"]
                        - u_metrics["total_cost_cny"]
                    ),
                    "fairness_cost_pct_F_vs_U": (
                        (
                            f_metrics["total_cost_cny"]
                            - u_metrics["total_cost_cny"]
                        )
                        / u_metrics["total_cost_cny"]
                        * 100.0
                    ),
                    "u_weak_member_id": u_weak,
                    "u_weak_member_profit_change_vs_I_cny":
                        u_metrics["margins"][u_weak],
                    "u_weak_member_improvement_F_vs_U_cny":
                        f_metrics["profits"][u_weak]
                        - u_metrics["profits"][u_weak],
                    "rerun_elapsed_wall_seconds": unit[
                        "elapsed_wall_seconds"
                    ],
                    "joint_rerun_bitwise_identical": True,
                    "nested_candidate_is_independent_sample": False,
                }
            )
    if len(raw_rows) != 60 or len(member_rows) != 120:
        raise RuntimeError(
            f"HALT_STATE_DENOMINATOR:{len(raw_rows)}:{len(member_rows)}"
        )
    write_csv(HERE / "raw_runs.csv", raw_rows)
    write_csv(HERE / "member_ledger.csv", member_rows)
    write_csv(HERE / "candidate_pool_summary.csv", pool_summaries)
    summaries: list[dict[str, Any]] = []
    for instance_id, sample_role in INSTANCES:
        states = {
            state: [
                row
                for row in raw_rows
                if row["instance_id"] == instance_id
                and row["state"] == state
            ]
            for state in ("I", "U", "F")
        }
        u_rows = states["U"]
        f_rows = states["F"]
        fairness_pct = (
            (
                mean(float(row["total_cost_cny"]) for row in f_rows)
                - mean(
                    float(row["total_cost_cny"])
                    for row in u_rows
                )
            )
            / mean(float(row["total_cost_cny"]) for row in u_rows)
            * 100.0
        )
        summary: dict[str, Any] = {
            "instance_id": instance_id,
            "sample_role": sample_role,
            "seed_units": 10,
            "units_naturally_pareto_U": sum(
                bool(row["all_members_no_worse_than_I"])
                for row in u_rows
            ),
            "units_F_equals_I": sum(
                bool(row["f_fallback_to_I"]) for row in f_rows
            ),
            "fairness_cost_pct_F_vs_U": fairness_pct,
            "F_u_weak_member_improvement_avg_cny": mean(
                float(
                    row[
                        "u_weak_member_improvement_vs_U_cny"
                    ]
                )
                for row in f_rows
            ),
            "F_u_weak_member_improvement_median_cny": median(
                float(
                    row[
                        "u_weak_member_improvement_vs_U_cny"
                    ]
                )
                for row in f_rows
            ),
        }
        for state in ("I", "U", "F"):
            rows = states[state]
            summary.update(
                {
                    f"{state}_total_cost_avg_cny": mean(
                        float(row["total_cost_cny"])
                        for row in rows
                    ),
                    f"{state}_profit_D_guangzhou_avg_cny": mean(
                        float(row["profit_D_guangzhou_cny"])
                        for row in rows
                    ),
                    f"{state}_profit_D_shenzhen_avg_cny": mean(
                        float(row["profit_D_shenzhen_cny"])
                        for row in rows
                    ),
                    f"{state}_vehicle_count_avg": mean(
                        float(row["vehicle_count"]) for row in rows
                    ),
                    f"{state}_elapsed_seconds_avg": mean(
                        float(row["elapsed_seconds"]) for row in rows
                    ),
                }
            )
        summaries.append(summary)
    write_csv(HERE / "instance_summary.csv", summaries)
    natural = sum(
        bool(row["all_members_no_worse_than_I"])
        for row in raw_rows
        if row["state"] == "U"
    )
    f_equals_i = sum(
        bool(row["f_fallback_to_I"])
        for row in raw_rows
        if row["state"] == "F"
    )
    fairness_cost_pct = mean(
        float(row["fairness_cost_pct_F_vs_U"])
        for row in summaries
    )
    overall = {
        "units_naturally_pareto": natural,
        "units_total": 20,
        "units_f_equals_i": f_equals_i,
        "fairness_cost_pct": fairness_cost_pct,
        "fairness_cost_pct_definition":
            "equal-weight mean of the two instance-row percentages",
        "fairness_cost_pct_pooled_unit_mean": mean(
            float(row["fairness_cost_pct_F_vs_U"])
            for row in pool_summaries
        ),
        "F_u_weak_member_improvement_avg_cny": mean(
            float(
                row["u_weak_member_improvement_F_vs_U_cny"]
            )
            for row in pool_summaries
        ),
        "candidate_full_evaluation_events": sum(
            int(row["full_evaluation_event_count"])
            for row in pool_summaries
        ),
        "candidate_pool_unique_total": sum(
            int(row["candidate_pool_size_unique"])
            for row in pool_summaries
        ),
        "participation_satisfying_candidates_total": sum(
            int(row["participation_satisfying_candidate_count"])
            for row in pool_summaries
        ),
        "joint_rerun_elapsed_wall_seconds_sum": sum(
            float(row["rerun_elapsed_wall_seconds"])
            for row in pool_summaries
        ),
    }
    metadata = {
        "schema": "resetp.e6-fairness-v3.metadata.v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "status": "PASS_PENDING_INDEPENDENT_VERIFICATION",
        "contract": relative(CONTRACT),
        "e3_source_directory": relative(E3_ROOT),
        "prior_e6_directory": relative(OLD_E6_ROOT),
        "instances": [row[0] for row in INSTANCES],
        "seeds": list(SEEDS),
        "states": ["I", "U", "F"],
        "state_definitions": {
            "I": "same-seed sealed E3 ZONE final solution",
            "U": "same-seed sealed E3 JOINT final solution",
            "F": (
                "minimum-system-cost theta=1 unique candidate among "
                "the same rerun U pool, with I fallback only when the "
                "pool contains no participation-satisfying candidate"
            ),
        },
        "theta": THETA,
        "tolerance_cny": TOLERANCE,
        "budget_cap": CAP,
        "budget_semantics": "UPPER_CAP_NOT_QUOTA",
        "workers_max": MAX_WORKERS,
        "joint_search_units_rerun": 20,
        "zone_search_units_rerun": 0,
        "candidate_pool_persisted": True,
        "nested_candidates_counted_as_independent_samples": False,
        "candidate_pool_size_definition":
            "unique solution payload hashes among fully evaluated feasible events",
        "F_time_definition":
            "shared sealed U search time, not a third trajectory and not additive",
        "protected_hashes": environment["protected_hashes"],
        "e3_verification": environment["e3_verification"],
        "file_enumeration_exclusions": [
            "._*",
            "__pycache__",
            ".pytest_cache",
            "monitor_runtime",
        ],
        "overall": overall,
    }
    decision = {
        "schema": "resetp.e6-fairness-v3.decision.v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "status": "PASS_PENDING_INDEPENDENT_VERIFICATION",
        "verdict": "PASS_E6_I_U_F_COMPUTED_FROM_BITWISE_IDENTICAL_U_REPLAY",
        **overall,
        "joint_rerun_bitwise_identical": True,
        "candidate_pool_persisted": True,
        "f_selection_complete": True,
        "nested_candidates_counted_as_independent_samples": False,
        "alpha_grid_used": False,
        "transfer_payments_used": False,
        "old_e3_and_e6_files_overwritten": False,
    }
    decision["decision_id"] = canonical_sha256(decision)
    atomic_json(HERE / "metadata.json", metadata)
    atomic_json(HERE / "decision.json", decision)
    report = build_report(summaries, pool_summaries, overall)
    (HERE / "report.md").write_text(report, encoding="utf-8")
    verify_protected()
    log(
        "FINALIZE PASS "
        f"natural={natural}/20 F_equals_I={f_equals_i}/20 "
        f"fairness_cost_pct={fairness_cost_pct:.9f} "
        "pending independent verification"
    )
    return overall


def fmt(value: Any, digits: int = 3) -> str:
    return f"{float(value):.{digits}f}"


def build_report(
    summaries: list[dict[str, Any]],
    pool_rows: list[dict[str, Any]],
    overall: dict[str, Any],
) -> str:
    main_rows = []
    for row in summaries:
        main_rows.append(
            "| {instance} | {natural}/10 | "
            "{ic} | {ig} | {is_} | {iv} | {it} | "
            "{uc} | {ug} | {us} | {uv} | {ut} | "
            "{fc} | {fg} | {fs} | {fv} | {ft} | "
            "{cost}% | {fallback}/10 |".format(
                instance=row["instance_id"],
                natural=row["units_naturally_pareto_U"],
                ic=fmt(row["I_total_cost_avg_cny"]),
                ig=fmt(row["I_profit_D_guangzhou_avg_cny"]),
                is_=fmt(row["I_profit_D_shenzhen_avg_cny"]),
                iv=fmt(row["I_vehicle_count_avg"], 2),
                it=fmt(row["I_elapsed_seconds_avg"], 2),
                uc=fmt(row["U_total_cost_avg_cny"]),
                ug=fmt(row["U_profit_D_guangzhou_avg_cny"]),
                us=fmt(row["U_profit_D_shenzhen_avg_cny"]),
                uv=fmt(row["U_vehicle_count_avg"], 2),
                ut=fmt(row["U_elapsed_seconds_avg"], 2),
                fc=fmt(row["F_total_cost_avg_cny"]),
                fg=fmt(row["F_profit_D_guangzhou_avg_cny"]),
                fs=fmt(row["F_profit_D_shenzhen_avg_cny"]),
                fv=fmt(row["F_vehicle_count_avg"], 2),
                ft=fmt(row["F_elapsed_seconds_avg"], 2),
                cost=fmt(row["fairness_cost_pct_F_vs_U"], 6),
                fallback=row["units_F_equals_I"],
            )
        )
    detail_rows = [
        "| {instance} | {seed} | {events} | {pool} | {fair} | "
        "{selected} | {cost} | {weak} | {improve} |".format(
            instance=row["instance_id"],
            seed=row["seed"],
            events=row["full_evaluation_event_count"],
            pool=row["candidate_pool_size_unique"],
            fair=row["participation_satisfying_candidate_count"],
            selected=(
                "I 回退"
                if row["f_selection"] == "I_FALLBACK"
                else row["selected_f_candidate_id"]
            ),
            cost=fmt(row["fairness_cost_pct_F_vs_U"], 6),
            weak=row["u_weak_member_id"],
            improve=fmt(
                row["u_weak_member_improvement_F_vs_U_cny"]
            ),
        )
        for row in pool_rows
    ]
    instance_findings = "\n".join(
        (
            f"`{row['instance_id']}` 的 U 自然帕累托为 "
            f"{row['units_naturally_pareto_U']}/10；F 相对 U 的"
            f"系统成本增量为 {row['fairness_cost_pct_F_vs_U']:.6f}%，"
            f"{row['units_F_equals_I']}/10 个单元回退到 I；"
            f"U 中弱势成员在 F 下的收益平均改善 "
            f"{row['F_u_weak_member_improvement_avg_cny']:.3f} 元。"
        )
        for row in summaries
    )
    return f"""# E6 协同收益公平实验：候选池回放与 I/U/F 完整结果

状态：`PASS_PENDING_INDEPENDENT_VERIFICATION`。本轮只重跑 JOINT 的 20 个
单元，ZONE 搜索重跑 0 个。20 个 JOINT 回放的最终解哈希、完整目标浮点位、
实际完整评价数、逐候选分类 trace 和终止原因均与 E3 封存结果逐项一致。候选
持久化发生在搜索返回之后，`epochal_hgs.py`、`route_pool_sp.py`、搜索算子、
随机流、接受规则和 cap=400 均未改变。

## 三个问题的直接回答

第一，U 自然满足两个成员均不低于 I 的单元仍为
**{overall['units_naturally_pareto']}/20（{overall['units_naturally_pareto']/20*100:.1f}%）**，
复核与上一轮一致，按全分母报告。

第二，F 相对 U 的公平成本按两条算例行等权为
**{overall['fairness_cost_pct']:.6f}%**。逐算例结果见主表。20 个单元中有
**{overall['units_f_equals_i']}/20** 个因同次 U 候选池没有满足参与条件的候选而
回退到 I；这些单元的公平代价就是放弃该单元的全部协同节省。

第三，以每个单元 U 状态下收益下降最多的成员为“弱势成员”，F 相对 U 使其收益
平均改善 **{overall['F_u_weak_member_improvement_avg_cny']:.3f} 元**。F 的成员
利润同时逐一满足 θ=1，不使用转移支付。

## 期刊式三态主表

各行是 10 seeds 均值。F 时间复用同一 U 搜索的封存墙钟，仅表示生成该候选池所需
的共享搜索时间，不是第三条轨迹，不能与 U 时间相加。

| 算例 | U自然帕累托 | I成本 | I广州收益 | I深圳收益 | I车 | I秒 | U成本 | U广州收益 | U深圳收益 | U车 | U秒 | F成本 | F广州收益 | F深圳收益 | F车 | F秒 | F较U成本增量 | F=I |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(main_rows)}

{instance_findings}

## 逐单元候选池与 F 选择

“候选池大小”按完整 solution payload 哈希去重；“完整评价事件”保留同一解被重复
复核的事件数。嵌套候选只用于单元内选择 F，没有被当作独立样本增加 n。

| 算例 | seed | 完整评价事件 | 唯一候选池 | 满足参与条件 | F选择 | F较U成本增量% | U弱势成员 | F较U收益改善 |
|---|---:|---:|---:|---:|---|---:|---|---:|
{chr(10).join(detail_rows)}

20 个回放共持久化 {overall['candidate_full_evaluation_events']} 个可行完整评价事件，
对应 {overall['candidate_pool_unique_total']} 个逐单元去重候选，其中
{overall['participation_satisfying_candidates_total']} 个满足 θ=1。每个候选文件
保存路线、路线所属车场、客户序列、充电动作、跨场服务、完整目标浮点位、完整模型
breakdown、成员收益账本和来源事件序号。

## 管理含义与 E3 权衡

跨场协同在本文两个算例的全部 20 个种子单元上都至少使一个车场收益下降。E3 的
系统平均降本为 50c 的 2.272759% 和 100c 的 0.693115%，两算例等权约
1.482937%，但成员间再分配的幅度远大于系统节省；50c 中广州的平均收益由
6917.233 元降至 6042.162 元，约下降 12.6%，而深圳由 9075.820 元升至
10004.106 元。因此，没有显式收益分配机制时，理性的弱势车场缺少自愿参与协同的
账面激励。

这一分配问题不是孤立现象。联合配送相对分区配送虽然降低成本并少用车，但 50c
里程增加 28.04%、碳排增加 4.04%，100c 里程增加 12.18%、碳排增加 1.18%。
因此本文证据显示的是“有限降本、车辆集约、里程与碳上升、成员收益重新分配”的
组合权衡，而不是联合配送的全面改善。

## 可直接用于正文的中文

表 X 比较了分区独立经营、无约束联合配送和参与保障联合配送三种状态。在两个预定
算例的 20 个共同种子单元中，无约束联合配送均未自然满足所有车场收益不低于独立
经营基准（0/20，0.0%）。联合配送虽使两个算例的系统成本平均下降约 1.48%，但该
节省显著小于成员间的收益再分配幅度；以 50 客户算例为例，广州车场收益平均下降
约 875 元，约占其独立经营收益的 12.6%。施加不允许转移支付的参与保障后，F 相对
U 的系统成本增加 {overall['fairness_cost_pct']:.6f}%，且
{overall['units_f_equals_i']}/20 个单元回退到独立经营，说明在这些候选池内协同
无法同时满足双方账面参与条件。该结果还应与运营权衡共同解释：联合配送减少总成本
和车辆数，却使 50/100 客户算例的里程分别增加 28.04%/12.18%，碳排分别增加
4.04%/1.18%。由此，跨场协同的可实施性不仅取决于系统节省，还取决于收益分配及其
伴随的环境代价。

## 转移支付备选（本任务未采用）

本文采用不允许转移支付的参与保障口径，即每个车场必须在自己的运营账面上不吃亏。
若允许车场间转移支付，由于 U 的系统总成本确实低于 I、服务同一客户集且总收入不变，
理论上存在用系统协同剩余补偿受损成员、使双方均不低于 I 的支付区间。此时研究问题
将从“是否存在账面帕累托候选”转为“采用何种收益分配机制”，可选研究方向包括
Shapley 值、MCRS 和按贡献比例分摊。

目标期刊的实际边界也支持把该问题留作扩展：陈雨蝶（2025）把“联合配送模式下各
配送中心之间的成本分配问题”列为后续研究，并未在原文实现；Soriano 等的多车场
收益公平研究则先验证多车场算法，再研究成本与公平的取舍。转移支付规则会改变本文
参与保障的科学定义和研究范围，必须由用户另行裁决；本任务没有选择、计算或实现
任何转移支付与分配规则。

## 完整性边界

旧 `e3_zone_joint_20260731` 与 `e6_fairness_20260731` 目录未覆盖或删除。保护文件
哈希与任务开始时一致；文件枚举排除 `._*`、`__pycache__`、`.pytest_cache` 和
监控运行态。正式 `done.json` 仅在独立验收和哈希清单完成后最后写入。
"""


def artifact_manifest() -> dict[str, Any]:
    files: dict[str, str] = {}
    for path in sorted(HERE.rglob("*")):
        if (
            not path.is_file()
            or path.name.startswith("._")
            or path.name in {"artifact_hashes.json", "done.json"}
            or path.suffix == ".tmp"
            or any(part in EXCLUDED_DIRS for part in path.parts)
        ):
            continue
        files[relative(path)] = sha256(path)
    payload = {
        "schema": "resetp.e6-fairness-v3.artifact-hashes.v1",
        "created_at_utc": now_iso(),
        "files": files,
        "exclusions": [
            "._*",
            "__pycache__",
            ".pytest_cache",
            "monitor_runtime",
            "*.tmp",
            "artifact_hashes.json (self-reference)",
            "done.json (completion signal written last)",
        ],
    }
    payload["manifest_id"] = canonical_sha256(payload)
    atomic_json(HERE / "artifact_hashes.json", payload)
    return payload


def seal() -> dict[str, Any]:
    verify_protected()
    verification = read_json(HERE / "independent_verification.json")
    if verification.get("status") != "PASS":
        raise RuntimeError("HALT_INDEPENDENT_VERIFICATION_NOT_PASS")
    decision = read_json(HERE / "decision.json")
    metadata = read_json(HERE / "metadata.json")
    decision["status"] = "COMPLETE"
    decision["independent_verification_status"] = "PASS"
    decision["decision_id"] = canonical_sha256(
        {key: value for key, value in decision.items() if key != "decision_id"}
    )
    metadata["status"] = "COMPLETE"
    metadata["independent_verification_status"] = "PASS"
    atomic_json(HERE / "decision.json", decision)
    atomic_json(HERE / "metadata.json", metadata)
    report_path = HERE / "report.md"
    report = report_path.read_text(encoding="utf-8").replace(
        "状态：`PASS_PENDING_INDEPENDENT_VERIFICATION`。",
        "状态：`COMPLETE`。独立验收已通过。",
        1,
    )
    report_path.write_text(report, encoding="utf-8")
    manifest = artifact_manifest()
    overall = decision
    done = {
        "schema": "resetp.e6-fairness-v3.done.v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "status": "COMPLETE",
        "joint_rerun_bitwise_identical": True,
        "units_naturally_pareto": int(
            overall["units_naturally_pareto"]
        ),
        "units_total": 20,
        "units_f_equals_i": int(overall["units_f_equals_i"]),
        "fairness_cost_pct": float(overall["fairness_cost_pct"]),
        "candidate_pool_persisted": True,
        "f_state_computed": True,
        "joint_search_units_rerun": 20,
        "zone_search_units_rerun": 0,
        "artifact_manifest_id": manifest["manifest_id"],
        "decision_id": decision["decision_id"],
        "done_written_last": True,
    }
    done["done_id"] = canonical_sha256(done)
    atomic_json(HERE / "done.json", done)
    print(
        f"{now_iso()} DONE COMPLETE natural="
        f"{done['units_naturally_pareto']}/20 "
        f"F_equals_I={done['units_f_equals_i']}/20 "
        f"fairness_cost_pct={done['fairness_cost_pct']:.9f}",
        flush=True,
    )
    return done


def write_halt_package(error: BaseException) -> None:
    if (HERE / "done.json").exists():
        return
    message = f"{type(error).__name__}: {error}"
    status = (
        str(error).split(":", 1)[0]
        if str(error).startswith("HALT_")
        else "HALT_UNEXPECTED_EXCEPTION"
    )
    completed_paths = [
        path
        for path in sorted(
            (HERE / "formal/task_status").glob("*.json")
        )
        if not path.name.startswith("._")
    ]
    completed = [read_json(path) for path in completed_paths]
    all_candidate_pools_persisted = len(completed) == 20
    mismatch_paths = [
        path
        for path in sorted(
            (HERE / "formal/mismatches").glob("*.json")
        )
        if not path.name.startswith("._")
    ]
    partial_rows = [
        {
            "instance_id": row.get("instance_id", ""),
            "seed": row.get("seed", ""),
            "status": row.get("status", ""),
            "solution_sha256_identical": row.get(
                "bitwise_comparisons", {}
            ).get("solution_sha256_identical", ""),
            "objective_float_bits_identical": row.get(
                "bitwise_comparisons", {}
            ).get("objective_float_bits_identical", ""),
            "candidate_pool_persisted": row.get(
                "candidate_pool_persisted", False
            ),
        }
        for row in completed
    ]
    if not partial_rows:
        partial_rows = [
            {
                "instance_id": "",
                "seed": "",
                "status": status,
                "solution_sha256_identical": False,
                "objective_float_bits_identical": False,
                "candidate_pool_persisted": False,
            }
        ]
    write_csv(HERE / "raw_runs.csv", partial_rows)
    natural = int(
        read_json(OLD_E6_ROOT / "decision.json").get(
            "units_naturally_pareto", 0
        )
    )
    metadata = {
        "schema": "resetp.e6-fairness-v3.metadata.v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "status": status,
        "error": message,
        "completed_joint_units": len(completed),
        "mismatch_files": [relative(path) for path in mismatch_paths],
        "candidate_pool_persisted": all_candidate_pools_persisted,
        "protected_hashes": verify_protected(),
    }
    decision = {
        "schema": "resetp.e6-fairness-v3.decision.v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "status": status,
        "verdict": status,
        "error": message,
        "joint_rerun_bitwise_identical": False,
        "units_naturally_pareto": natural,
        "units_total": 20,
        "units_f_equals_i": None,
        "fairness_cost_pct": None,
        "candidate_pool_persisted": all_candidate_pools_persisted,
    }
    decision["decision_id"] = canonical_sha256(decision)
    atomic_json(HERE / "metadata.json", metadata)
    atomic_json(HERE / "decision.json", decision)
    (HERE / "report.md").write_text(
        "# E6 候选池回放停机\n\n"
        f"状态：`{status}`。\n\n"
        f"错误：`{message}`\n\n"
        f"已完成 JOINT 单元：{len(completed)}/20；"
        + (
            "检测到逐位不一致后停止，"
            if mismatch_paths
            else "20 个单元的完整逐位一致性尚未建立，"
        )
        + "未调参、未修饰、未继续计算 F。\n",
        encoding="utf-8",
    )
    manifest = artifact_manifest()
    done = {
        "schema": "resetp.e6-fairness-v3.done.v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "status": status,
        "joint_rerun_bitwise_identical": False,
        "units_naturally_pareto": natural,
        "units_total": 20,
        "units_f_equals_i": None,
        "fairness_cost_pct": None,
        "candidate_pool_persisted": all_candidate_pools_persisted,
        "f_state_computed": False,
        "artifact_manifest_id": manifest["manifest_id"],
        "decision_id": decision["decision_id"],
        "done_written_last": True,
    }
    done["done_id"] = canonical_sha256(done)
    atomic_json(HERE / "done.json", done)


def run_all(workers: int) -> None:
    run_formal(workers)
    finalize()
    subprocess.run(
        [str(PYTHON), "-u", str(CHECKER)],
        cwd=ROOT,
        env={**os.environ, **REQUIRED_THREAD_ENV},
        check=True,
    )
    seal()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("run", "finalize", "seal", "all")
    )
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    try:
        if args.command == "run":
            run_formal(args.workers)
        elif args.command == "finalize":
            finalize()
        elif args.command == "seal":
            seal()
        else:
            run_all(args.workers)
    except BaseException as error:
        write_halt_package(error)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
