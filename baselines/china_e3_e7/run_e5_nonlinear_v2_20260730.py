#!/usr/bin/env python3
"""Journal-aligned E5 nonlinear-charging experiment (2026-07-30).

The complete-candidate budget is always an explicit CLI argument.  The runner
has three phases: a two-arm convergence probe, one-instance-at-a-time formal
search, and independent verification/closeout.  L/S is retained only as a
diagnostic field and is never a run, admission, or result gate.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import multiprocessing as mp
import os
import platform
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path = [entry for entry in sys.path if Path(entry or ".").resolve() != SCRIPT_DIR]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (REPO, REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from route_pool_sp import run_hgs_route_pool_recombination
from setp_solver.charging_curve import L100_CONTROL, NL90_MILD
from setp_solver.china81 import China81Bundle, load_china81_bundle
from setp_solver.solution import Route, Solution

TASK_ID = "E5-NONLINEAR-CHARGING-V2-20260730"
OUT = REPO / "baselines/china_e3_e7/e5_nonlinear_v2_20260730"
OLD_OUT = REPO / "baselines/china_e3_e7/e5_nonlinear_20260729"
FLEET = REPO / "data/ChinaInstances/china81_finite_fleet_authority_v1_20260723"
CONTRACT = REPO / "docs/handoff/experiment_contract_v2_journal_aligned_20260730.md"
ARMS = (L100_CONTROL.curve_id, NL90_MILD.curve_id)
INSTANCE_SPECS = (
    {
        "instance_id": "cn-prd-50c-01-V2-LOCATIONS",
        "sample_role": "MAIN_EXHIBIT",
        "seeds": tuple(range(1, 11)),
    },
    {
        "instance_id": "cn-prd-100c-02-V2-LOCATIONS",
        "sample_role": "ROBUSTNESS",
        "seeds": tuple(range(1, 11)),
    },
)
PROBE_INSTANCE = "cn-prd-50c-01-V2-LOCATIONS"
PROBE_SEED = 1
MAX_WORKERS_ALLOWED = 2
MAX_HGS_ITERATIONS_PER_VIEW = 5_000
EXACT_ELITES_PER_VIEW = 8
MIP_TIME_LIMIT_SECONDS = 5.0
PLATEAU_RELATIVE_BAND = 1.0e-4
PLATEAU_CONFIRMATION_EVALUATIONS = 200
TERMINAL_CLOSURE_SOURCES = (
    "route_pool_candidate_or_parent",
    "final_independent_certificate",
)
REQUIRED_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}
EXCLUDED_ENUMERATION_DIRS = frozenset({"__pycache__", ".pytest_cache"})
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
    PROTOTYPE / "route_pool_sp.py",
)
LOCKED_SOURCES = (
    Path(__file__).resolve(),
    REPO / "baselines/china_e3_e7/check_e5_nonlinear_v2_20260730.py",
    REPO / "baselines/china_e3_e7/run_e5_nonlinear_20260729.py",
    REPO / "baselines/china_e3_e7/check_e5_nonlinear_20260729.py",
    CONTRACT,
    REPO / "docs/handoff/journal_convention_alignment_20260730/report.md",
    PROTOTYPE / "epochal_hgs.py",
    PROTOTYPE / "route_pool_sp.py",
    PROTOTYPE / "pyvrp_adapter.py",
    REPO / "solver/src/setp_solver/china81.py",
    REPO / "solver/src/setp_solver/china81_completion.py",
    REPO / "solver/src/setp_solver/charging_curve.py",
    REPO / "solver/src/setp_solver/solution.py",
    *PROTECTED[:3],
)


def is_real_artifact_file(path: Path) -> bool:
    """Return true only for a real file, never AppleDouble/cache byproducts."""

    return (
        path.is_file()
        and not path.name.startswith("._")
        and not any(part in EXCLUDED_ENUMERATION_DIRS for part in path.parts)
    )


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")


def payload_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_bytes(payload))
    temporary.replace(path)


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(REPO))


def arithmetic_mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean requires at least one value")
    return sum(values) / len(values)


def median(values: list[float]) -> float:
    if not values:
        raise ValueError("median requires at least one value")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return 0.5 * (ordered[middle - 1] + ordered[middle])


def source_hashes() -> dict[str, str]:
    return {relative(path): file_sha256(path) for path in LOCKED_SOURCES}


def sealed_tree_hashes() -> dict[str, str]:
    if not OLD_OUT.is_dir():
        raise RuntimeError("HALT_E5_V2_OLD_SEALED_EVIDENCE_MISSING")
    return {
        str(path.relative_to(OLD_OUT)): file_sha256(path)
        for path in sorted(
            item for item in OLD_OUT.rglob("*") if is_real_artifact_file(item)
        )
    }


def input_hashes(bundle: China81Bundle) -> dict[str, str]:
    rows: dict[str, str] = {}
    for path_value in sorted(set(bundle.source_paths.values())):
        path = Path(path_value)
        if not path.is_absolute():
            path = REPO / path
        if path.is_file():
            rows[relative(path)] = file_sha256(path)
    witness = FLEET / "witnesses" / f"{bundle.instance_id}.json"
    rows[relative(witness)] = file_sha256(witness)
    return rows


def core_data_hashes() -> dict[str, str]:
    rows: dict[str, str] = {}
    for spec in INSTANCE_SPECS:
        current = input_hashes(load_china81_bundle(REPO, str(spec["instance_id"])))
        for path, digest in current.items():
            if path in rows and rows[path] != digest:
                raise RuntimeError(f"HALT_E5_V2_CORE_DATA_HASH_CONFLICT:{path}")
            rows[path] = digest
    return dict(sorted(rows.items()))


def curve_bundle(bundle: China81Bundle, arm: str) -> China81Bundle:
    if arm == L100_CONTROL.curve_id:
        spec = L100_CONTROL
    elif arm == NL90_MILD.curve_id:
        spec = NL90_MILD
    else:
        raise ValueError(f"unknown E5 arm: {arm}")
    return replace(
        bundle,
        prices=replace(
            bundle.prices,
            charging_curve_id=spec.curve_id,
            charging_soc_breakpoints=spec.soc_breakpoints,
            charging_relative_powers=spec.relative_powers,
        ),
    )


def archive_limits(budget: int) -> dict[str, int]:
    remaining = int(budget) - 8
    if remaining < 3 * EXACT_ELITES_PER_VIEW:
        raise ValueError(
            f"complete-candidate budget {budget} is too small for exact elites"
        )
    base, remainder = divmod(remaining, 3)
    modes = ("cv_only", "naive_ev", "mechanism_ev")
    result = {
        mode: base + (1 if index < remainder else 0)
        for index, mode in enumerate(modes)
    }
    if sum(result.values()) + 8 != int(budget):
        raise RuntimeError("archive-to-budget mapping is not exact")
    return result


def load_initial(instance_id: str) -> Solution:
    payload = json.loads(
        (FLEET / "witnesses" / f"{instance_id}.json").read_text(encoding="utf-8")
    )
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=[str(value) for value in row["node_sequence"]],
            )
            for row in payload["routes"]
        ]
    )


def solution_payload(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(row) for row in solution.routes],
        "charging_actions": [asdict(row) for row in solution.charging_actions],
        "cross_site_services": [asdict(row) for row in solution.cross_site_services],
    }


def initial_hash(solution: Solution) -> str:
    return payload_sha256(solution_payload(solution))


def preflight_environment(workers: int) -> dict[str, Any]:
    if not 1 <= workers <= MAX_WORKERS_ALLOWED:
        raise RuntimeError(f"HALT_E5_V2_WORKERS_OUT_OF_RANGE:{workers}")
    wrong = {
        name: os.environ.get(name)
        for name, expected in REQUIRED_THREAD_ENV.items()
        if os.environ.get(name) != expected
    }
    if wrong:
        raise RuntimeError(f"HALT_E5_V2_THREAD_ENV_NOT_FROZEN:{wrong}")
    for path in LOCKED_SOURCES:
        if not path.is_file():
            raise RuntimeError(f"HALT_E5_V2_MISSING_LOCKED_SOURCE:{path}")
    pyvrp_version = version("pyvrp")
    if pyvrp_version != "0.12.2":
        raise RuntimeError(
            f"HALT_E5_V2_PYVRP_VERSION:{pyvrp_version}!=0.12.2"
        )
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "pyvrp": pyvrp_version,
        "scipy": version("scipy"),
        "thread_environment": dict(REQUIRED_THREAD_ENV),
        "workers": workers,
    }


def prepare(probe_budget: int, workers: int) -> dict[str, Any]:
    if (OUT / "done.json").exists():
        raise RuntimeError("E5 v2 already has a terminal done.json")
    OUT.mkdir(parents=True, exist_ok=True)
    environment = preflight_environment(workers)
    sources = source_hashes()
    core_data = core_data_hashes()
    old_tree = sealed_tree_hashes()
    protected = {relative(path): file_sha256(path) for path in PROTECTED}
    lock = {
        "schema_version": "E5-SOURCE-LOCK-v2",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "source_sha256": sources,
        "core_data_sha256": core_data,
        "protected_source_sha256": protected,
        "old_sealed_e5_20260729_file_sha256": old_tree,
        "old_sealed_e5_20260729_tree_id": payload_sha256(old_tree),
    }
    lock["lock_id"] = payload_sha256(lock)
    task_card = {
        "schema_version": "E5-TASK-CARD-v2",
        "task_id": TASK_ID,
        "contract": relative(CONTRACT),
        "contract_sha256": file_sha256(CONTRACT),
        "prepared_at_utc": now_iso(),
        "instances": [
            {
                "instance_id": spec["instance_id"],
                "sample_role": spec["sample_role"],
                "seeds": list(spec["seeds"]),
            }
            for spec in INSTANCE_SPECS
        ],
        "arms": {
            L100_CONTROL.curve_id: asdict(L100_CONTROL),
            NL90_MILD.curve_id: asdict(NL90_MILD),
        },
        "probe": {
            "instance_id": PROBE_INSTANCE,
            "seed": PROBE_SEED,
            "long_budget": probe_budget,
            "plateau_relative_band": PLATEAU_RELATIVE_BAND,
            "confirmation_evaluations": PLATEAU_CONFIRMATION_EVALUATIONS,
            "terminal_closure_evaluations": list(TERMINAL_CLOSURE_SOURCES),
        },
        "formal_expected_rows": 40,
        "formal_expected_pairs": 20,
        "common_initial_and_seed": True,
        "budget_unit": "complete_candidate_evaluation_attempt",
        "budget_cli_has_no_default": True,
        "L_over_S_role": "diagnostic_only_never_a_gate",
        "max_workers": MAX_WORKERS_ALLOWED,
        "environment": environment,
    }
    atomic_json(OUT / "task_card.json", task_card)
    atomic_json(OUT / "source_lock.json", lock)
    print(
        f"PREPARED task={TASK_ID} probe_budget={probe_budget} "
        f"old_sealed_files={len(old_tree)}",
        flush=True,
    )
    return lock


def verify_source_lock() -> dict[str, Any]:
    lock_path = OUT / "source_lock.json"
    if not lock_path.is_file():
        raise RuntimeError("HALT_E5_V2_SOURCE_LOCK_MISSING")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    checks = (
        ("LOCKED_SOURCE", source_hashes(), lock["source_sha256"]),
        ("CORE_DATA", core_data_hashes(), lock["core_data_sha256"]),
        (
            "OLD_SEALED_EVIDENCE",
            sealed_tree_hashes(),
            lock["old_sealed_e5_20260729_file_sha256"],
        ),
    )
    for label, current, expected in checks:
        if current != expected:
            changed = sorted(
                key
                for key in set(current) | set(expected)
                if current.get(key) != expected.get(key)
            )
            raise RuntimeError(f"HALT_E5_V2_{label}_CHANGED:{changed[:20]}")
    protected = {relative(path): file_sha256(path) for path in PROTECTED}
    if protected != lock["protected_source_sha256"]:
        raise RuntimeError("HALT_E5_V2_PROTECTED_SOURCE_CHANGED")
    return lock


def task_stem(spec: dict[str, Any]) -> str:
    return f"{spec['instance_id']}__seed-{int(spec['seed']):02d}__{spec['arm']}"


def phase_paths(
    root: Path, phase: str, stem: str
) -> tuple[Path, Path, Path | None]:
    if phase == "probe":
        return (
            root / "probe" / "tasks" / f"{stem}.json",
            root / "probe" / "search_traces" / f"{stem}.json",
            None,
        )
    if phase == "formal":
        return (
            root / "formal" / "task_status" / f"{stem}.json",
            root / "formal" / "search_traces" / f"{stem}.json",
            root / "formal" / "plans" / f"{stem}.json",
        )
    raise ValueError(f"unknown phase: {phase}")


def run_search_unit(payload: dict[str, Any]) -> dict[str, Any]:
    for name, value in REQUIRED_THREAD_ENV.items():
        os.environ[name] = value
    spec = dict(payload["spec"])
    phase = str(payload["phase"])
    budget = int(payload["budget"])
    lock_id = str(payload["lock_id"])
    root = Path(str(payload["output_root"]))
    stem = task_stem(spec)
    status_path, trace_path, plan_path = phase_paths(root, phase, stem)
    if status_path.is_file():
        existing = json.loads(status_path.read_text(encoding="utf-8"))
        if (
            existing.get("status") == "PASS"
            and int(existing.get("budget", -1)) == budget
            and existing.get("source_lock_id") == lock_id
        ):
            return existing
        raise RuntimeError(f"HALT_E5_V2_STALE_TASK_ARTIFACT:{status_path}")

    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    base_bundle = load_china81_bundle(REPO, str(spec["instance_id"]))
    bundle = curve_bundle(base_bundle, str(spec["arm"]))
    initial = load_initial(str(spec["instance_id"]))
    archives = archive_limits(budget)
    safety = (
        900.0
        if phase == "probe"
        else max(600.0, 4.0 * (len(bundle.instance.nodes) - 1))
    )
    run = run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=int(spec["seed"]),
        hgs_seconds_per_view=None,
        exact_elites_per_view=EXACT_ELITES_PER_VIEW,
        max_archive_candidates_per_view=archives,
        sp_time_limit_seconds=MIP_TIME_LIMIT_SECONDS,
        hard_home_depot_lock=False,
        max_hgs_iterations_per_view=MAX_HGS_ITERATIONS_PER_VIEW,
        wallclock_safety_seconds_per_view=safety,
        exact_checkpoint_interval_iterations=None,
        preserve_base_pool_recombination=False,
    )
    stats = run.stats
    attempts = int(stats["complete_candidate_evaluation_attempts"])
    expected = int(stats["complete_candidate_budget_expected"])
    if (
        attempts != budget
        or expected != budget
        or not bool(stats["complete_candidate_budget_exactly_consumed"])
    ):
        raise RuntimeError(
            f"HALT_E5_V2_NONEXACT_BUDGET:{stem}:{attempts}:{expected}:{budget}"
        )
    if bool(stats["wallclock_safety_triggered"]):
        raise RuntimeError(f"HALT_E5_V2_WALLCLOCK_SAFETY_TRIGGERED:{stem}")
    trace = stats["complete_candidate_evaluation_trace"]
    if len(trace) != attempts or any(
        row.get("complete_objective") is None for row in trace
    ):
        raise RuntimeError(f"HALT_E5_V2_INVALID_COMPLETE_TRACE:{stem}")
    elapsed_wall = time.perf_counter() - started_wall
    elapsed_cpu = time.process_time() - started_cpu
    trace_payload = {
        "schema_version": f"E5-{phase.upper()}-SEARCH-TRACE-v2",
        "task_id": TASK_ID,
        **spec,
        "budget": budget,
        "complete_candidate_evaluation_trace": trace,
        "view_epoch_stats": {
            mode: epoch.stats for mode, epoch in run.view_epochs.items()
        },
        "route_pool_stats": {
            key: value
            for key, value in stats.items()
            if key != "complete_candidate_evaluation_trace"
        },
    }
    atomic_json(trace_path, trace_payload)
    status = {
        "schema_version": f"E5-{phase.upper()}-SEARCH-UNIT-v2",
        "task_id": TASK_ID,
        **spec,
        "phase": phase,
        "budget": budget,
        "archive_candidates_per_view": archives,
        "complete_candidate_evaluations_S": attempts,
        "last_strict_improvement_evaluation_L": int(
            stats["last_strict_improvement_evaluation"]
        ),
        "last_strict_improvement_fraction_L_over_S": float(
            stats["last_strict_improvement_fraction"]
        ),
        "L_over_S_role": "diagnostic_only_never_a_gate",
        "wallclock_safety_seconds_per_view": safety,
        "wallclock_safety_triggered": False,
        "elapsed_wall_seconds": elapsed_wall,
        "elapsed_cpu_seconds": elapsed_cpu,
        "common_initial_solution_sha256": initial_hash(initial),
        "search_total_cost_cny": float(run.completion.objective),
        "objective_status": "COMPLETE_MODEL_EVALUATED",
        "source_lock_id": lock_id,
        "search_trace_path": relative(trace_path),
        "search_trace_sha256": file_sha256(trace_path),
        "status": "PASS",
    }
    if phase == "formal":
        if plan_path is None:
            raise RuntimeError("formal plan path was not constructed")
        solution = solution_payload(run.solution)
        plan = {
            "schema_version": "E5-FORMAL-PLAN-v2",
            "task_id": TASK_ID,
            **spec,
            "budget": budget,
            "curve_used_in_search": str(spec["arm"]),
            "common_nonlinear_replay_curve": NL90_MILD.curve_id,
            "common_initial_solution_sha256": initial_hash(initial),
            "solution": solution,
            "solution_sha256": payload_sha256(solution),
            "search_total_cost_cny": float(run.completion.objective),
            "search_trace_path": relative(trace_path),
            "search_trace_sha256": file_sha256(trace_path),
            "input_sha256": input_hashes(bundle),
            "source_lock_id": lock_id,
        }
        plan["plan_sha256"] = payload_sha256(plan)
        atomic_json(plan_path, plan)
        status.update(
            {
                "plan_path": relative(plan_path),
                "plan_file_sha256": file_sha256(plan_path),
            }
        )
    atomic_json(status_path, status)
    return status


def run_parallel(
    specs: list[dict[str, Any]],
    *,
    phase: str,
    budget: int,
    lock_id: str,
    workers: int,
) -> list[dict[str, Any]]:
    payloads = [
        {
            "spec": spec,
            "phase": phase,
            "budget": budget,
            "lock_id": lock_id,
            "output_root": str(OUT),
        }
        for spec in specs
    ]
    rows: list[dict[str, Any]] = []
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
        futures = {
            executor.submit(run_search_unit, payload): payload["spec"]
            for payload in payloads
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            spec = futures[future]
            row = future.result()
            rows.append(row)
            print(
                "UNIT_COMPLETE "
                f"instance={spec['instance_id']} seed={int(spec['seed'])} "
                f"arm={spec['arm']} elapsed_seconds="
                f"{float(row['elapsed_wall_seconds']):.3f} "
                f"objective_status={row['objective_status']} "
                f"objective_cny={float(row['search_total_cost_cny']):.6f} "
                f"progress={completed}/{len(futures)}",
                flush=True,
            )
    return sorted(
        rows,
        key=lambda row: (row["instance_id"], int(row["seed"]), row["arm"]),
    )


def probe_specs() -> list[dict[str, Any]]:
    return [
        {
            "instance_id": PROBE_INSTANCE,
            "sample_role": "CONVERGENCE_PROBE",
            "seed": PROBE_SEED,
            "arm": arm,
        }
        for arm in ARMS
    ]


def formal_specs(instance_id: str) -> list[dict[str, Any]]:
    matches = [spec for spec in INSTANCE_SPECS if spec["instance_id"] == instance_id]
    if len(matches) != 1:
        raise ValueError(f"unknown formal instance: {instance_id}")
    spec = matches[0]
    return [
        {
            "instance_id": instance_id,
            "sample_role": str(spec["sample_role"]),
            "seed": int(seed),
            "arm": arm,
        }
        for seed in spec["seeds"]
        for arm in ARMS
    ]


def analyze_probe(rows: list[dict[str, Any]], long_budget: int) -> dict[str, Any]:
    curve_rows: list[dict[str, Any]] = []
    arm_rows: list[dict[str, Any]] = []
    for status in sorted(rows, key=lambda row: row["arm"]):
        trace_payload = json.loads(
            (REPO / status["search_trace_path"]).read_text(encoding="utf-8")
        )
        trace = trace_payload["complete_candidate_evaluation_trace"]
        if tuple(row["source"] for row in trace[-2:]) != TERMINAL_CLOSURE_SOURCES:
            raise RuntimeError(
                f"HALT_E5_V2_UNEXPECTED_TERMINAL_TRACE:{status['arm']}"
            )
        search_trace = trace[:-2]
        search_objectives = [
            float(row["complete_objective"]) for row in search_trace
        ]
        final_search_best = min(search_objectives)
        terminal_best = min(float(row["complete_objective"]) for row in trace)
        incumbent = math.inf
        plateau_start: int | None = None
        for item in trace:
            objective = float(item["complete_objective"])
            incumbent = min(incumbent, objective)
            index = int(item["evaluation_index"])
            segment = (
                "TERMINAL_ROUTE_POOL_CLOSURE"
                if index > len(search_trace)
                else "MULTI_VIEW_SEARCH"
            )
            relative_gap = (
                (incumbent - final_search_best)
                / max(1.0, abs(final_search_best))
                if segment == "MULTI_VIEW_SEARCH"
                else None
            )
            curve_rows.append(
                {
                    "instance_id": PROBE_INSTANCE,
                    "seed": PROBE_SEED,
                    "arm": status["arm"],
                    "evaluation_index": index,
                    "segment": segment,
                    "view": item["view"],
                    "source": item["source"],
                    "complete_objective_cny": objective,
                    "incumbent_best_cny": incumbent,
                    "relative_gap_to_final_search_best": (
                        relative_gap if relative_gap is not None else "NA_TERMINAL"
                    ),
                }
            )
            if (
                segment == "MULTI_VIEW_SEARCH"
                and plateau_start is None
                and relative_gap is not None
                and relative_gap <= PLATEAU_RELATIVE_BAND
            ):
                plateau_start = index
        if plateau_start is None:
            confirmation = None
            candidate_budget = long_budget
            plateau_confirmed = False
        else:
            confirmation = plateau_start + PLATEAU_CONFIRMATION_EVALUATIONS - 1
            plateau_confirmed = confirmation <= len(search_trace)
            candidate_budget = (
                math.ceil((confirmation + 2) / 100.0) * 100
                if plateau_confirmed
                else long_budget
            )
            candidate_budget = min(long_budget, int(candidate_budget))
        arm_rows.append(
            {
                "arm": status["arm"],
                "long_budget": long_budget,
                "multi_view_search_evaluations": len(search_trace),
                "terminal_closure_evaluations": 2,
                "final_multi_view_search_best_cny": final_search_best,
                "terminal_route_pool_best_cny": terminal_best,
                "terminal_route_pool_change_pct_vs_search_best": (
                    100.0
                    * (terminal_best - final_search_best)
                    / final_search_best
                ),
                "plateau_relative_band": PLATEAU_RELATIVE_BAND,
                "plateau_start_evaluation": plateau_start,
                "plateau_confirmation_window": PLATEAU_CONFIRMATION_EVALUATIONS,
                "plateau_confirmation_evaluation": confirmation,
                "plateau_confirmed": plateau_confirmed,
                "arm_recommended_budget_rounded_to_100": candidate_budget,
                "elapsed_wall_seconds": status["elapsed_wall_seconds"],
                "last_strict_improvement_evaluation_L_all_evaluations": status[
                    "last_strict_improvement_evaluation_L"
                ],
                "last_strict_improvement_fraction_L_over_S_diagnostic_only": status[
                    "last_strict_improvement_fraction_L_over_S"
                ],
            }
        )
    selected = max(
        int(row["arm_recommended_budget_rounded_to_100"]) for row in arm_rows
    )
    atomic_csv(OUT / "probe" / "convergence_curve.csv", curve_rows)
    atomic_csv(OUT / "probe" / "convergence_summary.csv", arm_rows)
    summary = {
        "schema_version": "E5-CONVERGENCE-PROBE-v2",
        "task_id": TASK_ID,
        "status": "PASS",
        "created_at_utc": now_iso(),
        "instance_id": PROBE_INSTANCE,
        "seed": PROBE_SEED,
        "arms": list(ARMS),
        "long_complete_candidate_budget": long_budget,
        "plateau_rule": {
            "search_segment": (
                "complete evaluations before the two deterministic terminal "
                "route-pool closure/certificate evaluations"
            ),
            "relative_band": PLATEAU_RELATIVE_BAND,
            "definition": (
                "earliest incumbent within relative_band of the final "
                "multi-view-search incumbent"
            ),
            "confirmation_window_evaluations": PLATEAU_CONFIRMATION_EVALUATIONS,
            "arm_budget": (
                "plateau confirmation evaluation plus two terminal closure "
                "evaluations, rounded upward to 100; if unconfirmed use the "
                "long probe budget"
            ),
            "common_budget": "maximum of the two arm budgets",
        },
        "arm_results": arm_rows,
        "selected_common_formal_budget": selected,
        "selection_uses_L_over_S": False,
        "curve_path": relative(OUT / "probe" / "convergence_curve.csv"),
    }
    summary["probe_id"] = payload_sha256(summary)
    atomic_json(OUT / "probe" / "summary.json", summary)
    lock = {
        "schema_version": "E5-BUDGET-LOCK-v2",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "budget_source": "convergence_probe",
        "probe_id": summary["probe_id"],
        "long_probe_budget": long_budget,
        "selected_common_formal_budget": selected,
        "source_lock_id": rows[0]["source_lock_id"],
    }
    lock["budget_lock_id"] = payload_sha256(lock)
    atomic_json(OUT / "budget_lock.json", lock)
    return summary


def run_probe(budget: int, workers: int) -> None:
    if (OUT / "done.json").exists():
        raise RuntimeError("E5 v2 already has a terminal done.json")
    if (OUT / "source_lock.json").is_file():
        lock = verify_source_lock()
        task_card = json.loads((OUT / "task_card.json").read_text(encoding="utf-8"))
        frozen_probe_budget = int(task_card["probe"]["long_budget"])
        if budget != frozen_probe_budget:
            raise RuntimeError(
                f"HALT_E5_V2_PROBE_BUDGET_CHANGED:{budget}!={frozen_probe_budget}"
            )
    else:
        lock = prepare(budget, workers)
    environment = preflight_environment(workers)
    print(
        f"PREFLIGHT_PASS phase=probe python={platform.python_version()} "
        f"pyvrp={environment['pyvrp']} workers={workers} budget={budget}",
        flush=True,
    )
    rows = run_parallel(
        probe_specs(),
        phase="probe",
        budget=budget,
        lock_id=lock["lock_id"],
        workers=workers,
    )
    summary = analyze_probe(rows, budget)
    verify_source_lock()
    print(
        "PROBE_COMPLETE "
        f"selected_common_formal_budget="
        f"{summary['selected_common_formal_budget']}",
        flush=True,
    )


def verify_pair_invariants(
    rows: list[dict[str, Any]], expected_pairs: int
) -> None:
    if len(rows) != 2 * expected_pairs:
        raise RuntimeError(
            f"HALT_E5_V2_FORMAL_ROW_DENOMINATOR:{len(rows)}!={2*expected_pairs}"
        )
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((str(row["instance_id"]), int(row["seed"])), []).append(
            row
        )
    if len(groups) != expected_pairs:
        raise RuntimeError(
            f"HALT_E5_V2_PAIR_DENOMINATOR:{len(groups)}!={expected_pairs}"
        )
    for key, pair in groups.items():
        if len(pair) != 2 or {row["arm"] for row in pair} != set(ARMS):
            raise RuntimeError(f"HALT_E5_V2_PAIR_ARMS:{key}")
        if len({row["common_initial_solution_sha256"] for row in pair}) != 1:
            raise RuntimeError(f"HALT_E5_V2_COMMON_INITIAL_MISMATCH:{key}")
        if len({int(row["budget"]) for row in pair}) != 1:
            raise RuntimeError(f"HALT_E5_V2_COMMON_BUDGET_MISMATCH:{key}")


def status_manifest_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "instance_id": row["instance_id"],
            "sample_role": row["sample_role"],
            "seed": row["seed"],
            "arm": row["arm"],
            "budget": row["budget"],
            "complete_candidate_evaluations_S": row[
                "complete_candidate_evaluations_S"
            ],
            "last_strict_improvement_evaluation_L": row[
                "last_strict_improvement_evaluation_L"
            ],
            "last_strict_improvement_fraction_L_over_S_diagnostic_only": row[
                "last_strict_improvement_fraction_L_over_S"
            ],
            "elapsed_wall_seconds": row["elapsed_wall_seconds"],
            "elapsed_cpu_seconds": row["elapsed_cpu_seconds"],
            "search_total_cost_cny": row["search_total_cost_cny"],
            "objective_status": row["objective_status"],
            "common_initial_solution_sha256": row[
                "common_initial_solution_sha256"
            ],
            "plan_path": row["plan_path"],
            "plan_file_sha256": row["plan_file_sha256"],
            "search_trace_path": row["search_trace_path"],
            "search_trace_sha256": row["search_trace_sha256"],
            "status": row["status"],
        }
        for row in rows
    ]


def load_budget_lock(submitted_budget: int) -> dict[str, Any]:
    path = OUT / "budget_lock.json"
    if not path.is_file():
        raise RuntimeError("HALT_E5_V2_CONVERGENCE_PROBE_MISSING")
    lock = json.loads(path.read_text(encoding="utf-8"))
    selected = int(lock["selected_common_formal_budget"])
    if submitted_budget != selected:
        raise RuntimeError(
            f"HALT_E5_V2_FORMAL_BUDGET_NOT_PROBE_SELECTED:"
            f"{submitted_budget}!={selected}"
        )
    return lock


def run_formal(instance_id: str, budget: int, workers: int) -> None:
    if (OUT / "done.json").exists():
        raise RuntimeError("E5 v2 already has a terminal done.json")
    lock = verify_source_lock()
    budget_lock = load_budget_lock(budget)
    if budget_lock["source_lock_id"] != lock["lock_id"]:
        raise RuntimeError("HALT_E5_V2_BUDGET_SOURCE_LOCK_MISMATCH")
    environment = preflight_environment(workers)
    print(
        f"PREFLIGHT_PASS phase=formal instance={instance_id} "
        f"python={platform.python_version()} pyvrp={environment['pyvrp']} "
        f"workers={workers} budget={budget}",
        flush=True,
    )
    rows = run_parallel(
        formal_specs(instance_id),
        phase="formal",
        budget=budget,
        lock_id=lock["lock_id"],
        workers=workers,
    )
    verify_pair_invariants(rows, 10)
    manifest_path = (
        OUT / "formal" / "manifests" / f"{instance_id}__manifest.csv"
    )
    atomic_csv(manifest_path, status_manifest_rows(rows))
    verify_source_lock()
    print(
        f"INSTANCE_COMPLETE instance={instance_id} units={len(rows)} "
        f"manifest={relative(manifest_path)}",
        flush=True,
    )


def all_formal_statuses(budget: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in INSTANCE_SPECS:
        for unit in formal_specs(str(spec["instance_id"])):
            path, _, _ = phase_paths(OUT, "formal", task_stem(unit))
            if not path.is_file():
                raise RuntimeError(f"HALT_E5_V2_FORMAL_UNIT_MISSING:{path}")
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("status") != "PASS" or int(row["budget"]) != budget:
                raise RuntimeError(f"HALT_E5_V2_FORMAL_UNIT_INVALID:{path}")
            rows.append(row)
    verify_pair_invariants(rows, 20)
    return sorted(
        rows,
        key=lambda row: (row["instance_id"], int(row["seed"]), row["arm"]),
    )


def run_independent_checker() -> None:
    checker = REPO / "baselines/china_e3_e7/check_e5_nonlinear_v2_20260730.py"
    subprocess.run(
        [sys.executable, "-u", str(checker), "--output-root", str(OUT)],
        cwd=REPO,
        env={**os.environ, **REQUIRED_THREAD_ENV},
        check=True,
    )


def load_certificates() -> list[dict[str, Any]]:
    paths = sorted(
        path
        for path in (OUT / "certificates").glob("*.json")
        if is_real_artifact_file(path)
    )
    if len(paths) != 40:
        raise RuntimeError(f"HALT_E5_V2_CERTIFICATE_DENOMINATOR:{len(paths)}!=40")
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if any(row.get("certificate_status") != "PASS" for row in rows):
        raise RuntimeError("HALT_E5_V2_FAILED_CERTIFICATE")
    return rows


def paired_rows(certs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for row in certs:
        groups.setdefault((str(row["instance_id"]), int(row["seed"])), {})[
            str(row["arm"])
        ] = row
    result: list[dict[str, Any]] = []
    for (instance_id, seed), pair in sorted(groups.items()):
        if set(pair) != set(ARMS):
            raise RuntimeError(f"HALT_E5_V2_CERT_PAIR_ARMS:{instance_id}:{seed}")
        left = pair[L100_CONTROL.curve_id]
        right = pair[NL90_MILD.curve_id]
        both = bool(left["nonlinear_feasible"] and right["nonlinear_feasible"])
        left_cost = left["common_nonlinear_full_model_total_cost_cny"]
        right_cost = right["common_nonlinear_full_model_total_cost_cny"]
        result.append(
            {
                "instance_id": instance_id,
                "seed": seed,
                "both_feasible_under_NL90": int(both),
                "L100_plan_replayed_NL90_cost_cny": (
                    left_cost if both else "NA_NOT_BOTH_FEASIBLE"
                ),
                "NL90_plan_NL90_cost_cny": (
                    right_cost if both else "NA_NOT_BOTH_FEASIBLE"
                ),
                "NL90_minus_L100_cost_cny": (
                    float(right_cost) - float(left_cost)
                    if both
                    else "NA_NOT_BOTH_FEASIBLE"
                ),
                "NL90_minus_L100_cost_pct": (
                    100.0 * (float(right_cost) - float(left_cost)) / float(left_cost)
                    if both
                    else "NA_NOT_BOTH_FEASIBLE"
                ),
            }
        )
    return result


def formal_table(
    certs: list[dict[str, Any]], statuses: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    time_by_key = {
        (row["instance_id"], int(row["seed"]), row["arm"]): float(
            row["elapsed_wall_seconds"]
        )
        for row in statuses
    }
    rows: list[dict[str, Any]] = []
    for spec in INSTANCE_SPECS:
        instance_id = str(spec["instance_id"])
        for arm in ARMS:
            subset = [
                row
                for row in certs
                if row["instance_id"] == instance_id and row["arm"] == arm
            ]
            feasible = [
                row for row in subset if row["planning_physics_feasible"]
            ]
            costs = [
                float(row["planning_full_model_total_cost_cny"]) for row in feasible
            ]
            if not costs:
                best = avg = gap = None
                best_vehicles = None
            else:
                best = min(costs)
                avg = arithmetic_mean(costs)
                gap = 100.0 * (avg - best) / best
                best_row = min(
                    feasible,
                    key=lambda row: float(
                        row["planning_full_model_total_cost_cny"]
                    ),
                )
                best_vehicles = int(best_row["physical_vehicle_count"])
            vehicles = [int(row["physical_vehicle_count"]) for row in feasible]
            times = [
                time_by_key[(instance_id, int(row["seed"]), arm)]
                for row in subset
            ]
            rows.append(
                {
                    "instance_id": instance_id,
                    "sample_role": spec["sample_role"],
                    "arm": arm,
                    "feasible_runs": len(feasible),
                    "runs": len(subset),
                    "Best_CNY": best if best is not None else "NA_INFEASIBLE",
                    "Avg_CNY": avg if avg is not None else "NA_INFEASIBLE",
                    "Gap_pct_Avg_minus_Best_over_Best": (
                        gap if gap is not None else "NA_INFEASIBLE"
                    ),
                    "vehicles_best": (
                        best_vehicles
                        if best_vehicles is not None
                        else "NA_INFEASIBLE"
                    ),
                    "vehicles_avg": (
                        arithmetic_mean([float(value) for value in vehicles])
                        if vehicles
                        else "NA_INFEASIBLE"
                    ),
                    "time_avg_seconds": arithmetic_mean(times),
                    "time_total_seconds": sum(times),
                }
            )
    return rows


def endpoint_summaries(
    certs: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for spec in INSTANCE_SPECS:
        instance_id = str(spec["instance_id"])
        instance_certs = [row for row in certs if row["instance_id"] == instance_id]
        nl_plans = [
            row for row in instance_certs if row["arm"] == NL90_MILD.curve_id
        ]
        linear_plans = [
            row for row in instance_certs if row["arm"] == L100_CONTROL.curve_id
        ]
        instance_pairs = [row for row in pairs if row["instance_id"] == instance_id]
        common = [
            row for row in instance_pairs if row["both_feasible_under_NL90"]
        ]
        effects = [float(row["NL90_minus_L100_cost_pct"]) for row in common]
        false_plans = [row for row in linear_plans if row["linear_plan_false_feasible"]]
        cause_counts: dict[str, int] = {}
        affected: dict[str, int] = {}
        for row in false_plans:
            for category, count in row["nonlinear_infeasibility_categories"].items():
                cause_counts[category] = cause_counts.get(category, 0) + int(count)
                affected[category] = affected.get(category, 0) + 1
        instance_sessions = [
            row for row in sessions if row["instance_id"] == instance_id
        ]
        deltas = [
            float(row["nonlinear_minus_linear_seconds"])
            for row in instance_sessions
        ]
        summaries[instance_id] = {
            "seeds": 10,
            "endpoint_1_NL90_complete_feasibility": {
                "feasible_count": sum(
                    int(row["planning_physics_feasible"]) for row in nl_plans
                ),
                "denominator": len(nl_plans),
            },
            "endpoint_2_linear_false_feasibility": {
                "false_feasible_count": len(false_plans),
                "denominator": len(linear_plans),
                "affected_units_by_cause": affected,
                "violations_by_cause": cause_counts,
            },
            "endpoint_3_common_feasible_cost_effect": {
                "coverage_count": len(common),
                "denominator": len(instance_pairs),
                "mean_NL90_minus_L100_pct": (
                    arithmetic_mean(effects) if effects else None
                ),
                "median_NL90_minus_L100_pct": (
                    median(effects) if effects else None
                ),
                "min_NL90_minus_L100_pct": min(effects) if effects else None,
                "max_NL90_minus_L100_pct": max(effects) if effects else None,
            },
            "endpoint_4_sessions": {
                "session_rows": len(instance_sessions),
                "mean_NL90_minus_L100_duration_seconds": (
                    arithmetic_mean(deltas) if deltas else None
                ),
                "median_NL90_minus_L100_duration_seconds": (
                    median(deltas) if deltas else None
                ),
                "max_NL90_minus_L100_duration_seconds": (
                    max(deltas) if deltas else None
                ),
            },
        }
    return summaries


def render_report(
    probe: dict[str, Any],
    table_rows: list[dict[str, Any]],
    endpoints: dict[str, Any],
    cause_rows: list[dict[str, Any]],
    budget: int,
) -> str:
    probe_lines = []
    for row in probe["arm_results"]:
        probe_lines.append(
            "| {arm} | {long_budget} | {elapsed:.2f} | {start} | "
            "{confirmation} | {recommended} | {terminal:.4f}% |".format(
                arm=row["arm"],
                long_budget=row["long_budget"],
                elapsed=float(row["elapsed_wall_seconds"]),
                start=row["plateau_start_evaluation"],
                confirmation=row["plateau_confirmation_evaluation"],
                recommended=row["arm_recommended_budget_rounded_to_100"],
                terminal=float(row["terminal_route_pool_change_pct_vs_search_best"]),
            )
        )
    formal_lines = []
    for row in table_rows:
        best = (
            row["Best_CNY"]
            if isinstance(row["Best_CNY"], str)
            else f"{float(row['Best_CNY']):.2f}"
        )
        avg = (
            row["Avg_CNY"]
            if isinstance(row["Avg_CNY"], str)
            else f"{float(row['Avg_CNY']):.2f}"
        )
        gap = (
            row["Gap_pct_Avg_minus_Best_over_Best"]
            if isinstance(row["Gap_pct_Avg_minus_Best_over_Best"], str)
            else f"{float(row['Gap_pct_Avg_minus_Best_over_Best']):.3f}%"
        )
        vehicles_avg = (
            row["vehicles_avg"]
            if isinstance(row["vehicles_avg"], str)
            else f"{float(row['vehicles_avg']):.2f}"
        )
        formal_lines.append(
            f"| {row['instance_id']} | {row['arm']} | "
            f"{row['feasible_runs']}/{row['runs']} | {best} | {avg} | {gap} | "
            f"{row['vehicles_best']}/{vehicles_avg} | "
            f"{float(row['time_avg_seconds']):.2f} |"
        )
    endpoint_lines = []
    for instance_id, row in endpoints.items():
        e1 = row["endpoint_1_NL90_complete_feasibility"]
        e2 = row["endpoint_2_linear_false_feasibility"]
        e3 = row["endpoint_3_common_feasible_cost_effect"]
        effect = (
            "不可识别"
            if e3["mean_NL90_minus_L100_pct"] is None
            else f"{float(e3['mean_NL90_minus_L100_pct']):.3f}%"
        )
        endpoint_lines.append(
            f"| {instance_id} | {e1['feasible_count']}/{e1['denominator']} | "
            f"{e2['false_feasible_count']}/{e2['denominator']} | "
            f"{e3['coverage_count']}/{e3['denominator']} | {effect} |"
        )
    cause_lines = [
        f"| {row['instance_id']} | {row['cause_category']} | "
        f"{row['affected_unit_count']} | {row['violation_count']} |"
        for row in cause_rows
    ]
    arm_rule = (
        "对每个臂，先去掉算法固定的最后两次终结评价（路线池候选/父代比较与"
        "独立证书复算），只在前面的多视角随机搜索段计算 incumbent 曲线；"
        f"首次进入最终搜索 incumbent 的 {PLATEAU_RELATIVE_BAND:.4%} 相对带后，"
        f"再观察连续 {PLATEAU_CONFIRMATION_EVALUATIONS} 次完整候选评价作为确认。"
        "确认评价数加回两次终结评价后向上取整到整百；两臂取较大值。两次终结"
        "评价及其目标值仍完整保存在曲线中。"
    )
    return f"""# E5 非线性充电机制正式实验（v2）

## 结论

本次按 `experiment_contract_v2_journal_aligned_20260730.md` 完成收敛探针和 40 个正式臂单元。旧的 `L/S>0.5`、饥饿单元占比 20% 和 pilot 阶梯没有进入本 runner 的任何准入或判定路径；`L/S` 只随运行行保留为诊断字段。正式共用预算为 **{budget} 次完整候选评价**，来源为收敛探针，不因正式结果方向而调整。

## 收敛探针与预算来源

主实例 `cn-prd-50c-01-V2-LOCATIONS`、seed=1 的两臂各运行 {probe['long_complete_candidate_budget']} 次完整候选评价。平台规则为：{arm_rule}

| Arm | 长预算 | 耗时(s) | 平台起点 | 确认评价 | 臂预算 | 终结路线池相对搜索最佳变化 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(probe_lines)}

两臂建议预算取大后为 {budget}。逐评价曲线见 `probe/convergence_curve.csv`，可直接复算上述规则。这里的终结路线池变化为负表示路线池使目标值下降；它不被删除，也不被误作随机搜索段的“未收敛”。

## 正式算法结果

Gap% 定义为 `(Avg−Best)/Best×100%`；Best/Avg 只在该臂自身完整物理下可行的正式解上计算，同时显式报告可行分母。车辆数写作“最佳解/可行运行平均物理车辆数”，时间为每个 `instance-seed-arm` 的平均墙钟秒。限时 MIP 只表示 5 秒内取得的路线池重组解，不声称证明最优。

| Instance | Arm | Feasible | Best (CNY) | Avg (CNY) | Gap% | Vehicles best/avg | Time avg(s) |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(formal_lines)}

## 四个科学端点

端点 3 使用共同 NL90 物理：把 L100 方案的路线、车辆、站点、开始时刻和充电量全部固定，只把占用时长换成 NL90 真值；只有两方案均在 NL90 下完整可行的配对单元进入成本效应。正值表示 NL90 方案成本高于 L100 方案的 NL90 物理复算成本，负值表示下降。

| Instance | NL90 完整可行 | L100 假可行 | 共同可行配对 | NL90−L100 平均成本变化 |
|---|---:|---:|---:|---:|
{chr(10).join(endpoint_lines)}

线性计划假可行的原因分类如下。`CHARGING_DURATION_OR_POWER` 表示充电时长/功率不足，`ELECTRIC_ENERGY_SHORTFALL_OR_SOC` 表示电量或 SOC 不足，`TIME_WINDOW_OVERRUN` 表示时间窗违约；其余类别按共同检查器台账原名保留。

| Instance | Cause | Affected units | Violations |
|---|---|---:|---:|
{chr(10).join(cause_lines)}

端点 4 的每个充电会话均写入 `charging_sessions.csv`：实例、种子、臂、车辆、站点、起止 SOC、线性时长、非线性时长及差值。汇总值与四个端点的机器可读结构见 `decision.json`；逐配对成本见 `paired_cost_effects.csv`。

## 独立复算与证据边界

40 个方案均由独立进程 `check_e5_nonlinear_v2_20260730.py` 复算；该进程不导入 v2 runner，并逐方案核对共同 `check_solution`/`evaluate` 与 `exact_china81_score` 的违反台账和成本分解。旧目录 `e5_nonlinear_20260729/` 的整树文件摘要被写入 `source_lock.json`，启动与收口都要求完全一致。受保护的 `cost.py`、`check.py`、`search/evaluation.py` 和 `route_pool_sp.py` 同样在收口复核。科学终态由 `metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、本报告和最后写入的 `done.json` 共同定义。
"""


def aggregate_and_close(budget: int, workers: int) -> None:
    lock = verify_source_lock()
    budget_lock = load_budget_lock(budget)
    statuses = all_formal_statuses(budget)
    atomic_csv(OUT / "formal_search_manifest.csv", status_manifest_rows(statuses))
    run_independent_checker()
    certs = load_certificates()

    status_by_key = {
        (row["instance_id"], int(row["seed"]), row["arm"]): row
        for row in statuses
    }
    raw_rows: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    for cert in sorted(
        certs, key=lambda row: (row["instance_id"], int(row["seed"]), row["arm"])
    ):
        status = status_by_key[
            (cert["instance_id"], int(cert["seed"]), cert["arm"])
        ]
        raw_rows.append(
            {
                "task_id": TASK_ID,
                "instance_id": cert["instance_id"],
                "sample_role": cert["sample_role"],
                "seed": cert["seed"],
                "arm": cert["arm"],
                "formal_complete_candidate_budget": budget,
                "complete_candidate_evaluations_S": status[
                    "complete_candidate_evaluations_S"
                ],
                "last_strict_improvement_evaluation_L": status[
                    "last_strict_improvement_evaluation_L"
                ],
                "last_strict_improvement_fraction_L_over_S_diagnostic_only": status[
                    "last_strict_improvement_fraction_L_over_S"
                ],
                "elapsed_wall_seconds": status["elapsed_wall_seconds"],
                "elapsed_cpu_seconds": status["elapsed_cpu_seconds"],
                "search_total_cost_cny": status["search_total_cost_cny"],
                "objective_status": status["objective_status"],
                "planning_physics_feasible": int(
                    cert["planning_physics_feasible"]
                ),
                "common_NL90_feasible": int(cert["nonlinear_feasible"]),
                "linear_plan_false_feasible": int(
                    cert["linear_plan_false_feasible"]
                ),
                "planning_full_model_total_cost_cny": (
                    cert["planning_full_model_total_cost_cny"]
                    if cert["planning_physics_feasible"]
                    else "NA_INFEASIBLE"
                ),
                "common_NL90_full_model_total_cost_cny": (
                    cert["common_nonlinear_full_model_total_cost_cny"]
                    if cert["nonlinear_feasible"]
                    else "NA_INFEASIBLE"
                ),
                "physical_vehicle_count": cert["physical_vehicle_count"],
                "nonlinear_violation_count": len(cert["nonlinear_violations"]),
                "nonlinear_infeasibility_categories_json": json.dumps(
                    cert["nonlinear_infeasibility_categories"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "charging_session_count": len(cert["sessions"]),
                "certificate_id": cert["certificate_id"],
                "certificate_status": cert["certificate_status"],
            }
        )
        sessions.extend(cert["sessions"])
    if len(raw_rows) != 40:
        raise RuntimeError("HALT_E5_V2_RAW_ROW_DENOMINATOR")
    atomic_csv(OUT / "raw_runs.csv", raw_rows)
    if not sessions:
        raise RuntimeError("HALT_E5_V2_NO_CHARGING_SESSIONS")
    atomic_csv(
        OUT / "charging_sessions.csv",
        sorted(
            sessions,
            key=lambda row: (
                row["instance_id"],
                int(row["seed"]),
                row["arm"],
                int(row["session_index"]),
            ),
        ),
    )

    pairs = paired_rows(certs)
    atomic_csv(OUT / "paired_cost_effects.csv", pairs)
    categories = (
        "CHARGING_DURATION_OR_POWER",
        "ELECTRIC_ENERGY_SHORTFALL_OR_SOC",
        "TIME_WINDOW_OVERRUN",
        "INTER_TRIP_CONNECTION_OR_ROUTE_CONTINUITY",
        "CHARGING_TIMING_INCONSISTENCY",
        "CHARGER_CAPACITY_OR_CONCURRENCY",
        "FLEET_CAPACITY",
    )
    discovered = sorted(
        {
            category
            for cert in certs
            if cert["linear_plan_false_feasible"]
            for category in cert["nonlinear_infeasibility_categories"]
        }
        - set(categories)
    )
    cause_rows: list[dict[str, Any]] = []
    for spec in INSTANCE_SPECS:
        instance_id = str(spec["instance_id"])
        false_certs = [
            cert
            for cert in certs
            if cert["instance_id"] == instance_id
            and cert["arm"] == L100_CONTROL.curve_id
            and cert["linear_plan_false_feasible"]
        ]
        for category in (*categories, *discovered):
            cause_rows.append(
                {
                    "instance_id": instance_id,
                    "cause_category": category,
                    "affected_unit_count": sum(
                        int(
                            category
                            in cert["nonlinear_infeasibility_categories"]
                        )
                        for cert in false_certs
                    ),
                    "violation_count": sum(
                        int(
                            cert["nonlinear_infeasibility_categories"].get(
                                category, 0
                            )
                        )
                        for cert in false_certs
                    ),
                }
            )
    atomic_csv(OUT / "false_feasibility_causes.csv", cause_rows)
    table_rows = formal_table(certs, statuses)
    atomic_csv(OUT / "formal_instance_arm_summary.csv", table_rows)
    endpoints = endpoint_summaries(certs, pairs, sessions)
    decision = {
        "schema_version": "E5-DECISION-v2",
        "task_id": TASK_ID,
        "status": "COMPLETE",
        "budget_used": budget,
        "budget_source": "convergence_probe",
        "endpoints_answered": 4,
        "endpoint_definitions": {
            "1": "NL90-arm complete-physics feasibility count",
            "2": "L100-feasible but fixed-plan NL90-infeasible count and causes",
            "3": "NL90 minus L100 percent cost on common-NL90 feasible pairs",
            "4": "per-session SOC endpoints and NL90 minus L100 duration",
        },
        "summaries_by_instance": endpoints,
        "formal_instance_arm_summary": table_rows,
        "p_value_gate_used": False,
        "result_filtering_used": False,
        "L_over_S_gate_used": False,
    }
    decision["decision_id"] = payload_sha256(decision)
    atomic_json(OUT / "decision.json", decision)
    probe = json.loads((OUT / "probe" / "summary.json").read_text(encoding="utf-8"))
    environment = preflight_environment(workers)
    try:
        git_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip()
        git_branch = subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=REPO, text=True
        ).strip()
    except subprocess.SubprocessError:
        git_head = git_branch = "UNAVAILABLE"
    metadata = {
        "schema_version": "E5-METADATA-v2",
        "task_id": TASK_ID,
        "status": "COMPLETE",
        "completed_at_utc": now_iso(),
        "contract": relative(CONTRACT),
        "contract_sha256": file_sha256(CONTRACT),
        "instances": [spec["instance_id"] for spec in INSTANCE_SPECS],
        "seeds": {spec["instance_id"]: list(spec["seeds"]) for spec in INSTANCE_SPECS},
        "arms": list(ARMS),
        "expected_formal_rows": 40,
        "actual_formal_rows": len(raw_rows),
        "budget_used": budget,
        "budget_source": "convergence_probe",
        "probe_id": probe["probe_id"],
        "budget_lock_id": budget_lock["budget_lock_id"],
        "source_lock_id": lock["lock_id"],
        "max_workers_allowed": MAX_WORKERS_ALLOWED,
        "closeout_workers_argument": workers,
        "independent_checker": {
            "path": relative(
                REPO
                / "baselines/china_e3_e7/check_e5_nonlinear_v2_20260730.py"
            ),
            "independent_process": True,
            "verification_path": relative(
                OUT / "independent_verification.json"
            ),
        },
        "environment": environment,
        "git_branch": git_branch,
        "git_head": git_head,
    }
    atomic_json(OUT / "metadata.json", metadata)
    report = render_report(probe, table_rows, endpoints, cause_rows, budget)
    atomic_text(OUT / "report.md", report)

    verify_source_lock()
    excluded_names = {"artifact_hashes.json", "done.json"}
    artifact_rows = []
    for path in sorted(
        item for item in OUT.rglob("*") if is_real_artifact_file(item)
    ):
        rel = str(path.relative_to(OUT))
        parts = set(path.relative_to(OUT).parts)
        if (
            rel in excluded_names
            or rel.startswith("monitor_runtime/")
            or path.name.startswith("._")
            or "__pycache__" in parts
            or ".pytest_cache" in parts
        ):
            continue
        artifact_rows.append(
            {"path": rel, "sha256": file_sha256(path), "bytes": path.stat().st_size}
        )
    protected_now = {relative(path): file_sha256(path) for path in PROTECTED}
    manifest = {
        "schema_version": "E5-ARTIFACT-HASHES-v2",
        "task_id": TASK_ID,
        "status": "COMPLETE",
        "hash_algorithm": "sha256",
        "excluded": [
            "artifact_hashes.json",
            "done.json",
            "monitor_runtime/**",
            "._*",
            "__pycache__/**",
            ".pytest_cache/**",
        ],
        "artifacts": artifact_rows,
        "protected_source_sha256_at_closeout": protected_now,
        "old_sealed_e5_20260729_tree_id_at_closeout": payload_sha256(
            sealed_tree_hashes()
        ),
    }
    manifest["manifest_id"] = payload_sha256(manifest)
    atomic_json(OUT / "artifact_hashes.json", manifest)
    required = (
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
    )
    if any(not (OUT / name).is_file() for name in required):
        raise RuntimeError("HALT_E5_V2_REQUIRED_TERMINAL_ARTIFACT_MISSING")
    done = {
        "schema_version": "E5-DONE-v2",
        "task_id": TASK_ID,
        "status": "COMPLETE",
        "completed_at_utc": now_iso(),
        "budget_used": budget,
        "budget_source": "convergence_probe",
        "instances_completed": [spec["instance_id"] for spec in INSTANCE_SPECS],
        "seeds": 10,
        "endpoints_answered": 4,
        "required_artifacts": list(required),
        "required_artifact_sha256": {
            name: file_sha256(OUT / name) for name in required
        },
        "manifest_id": manifest["manifest_id"],
        "decision_id": decision["decision_id"],
    }
    done["done_id"] = payload_sha256(done)
    atomic_json(OUT / "done.json", done)
    print(f"DONE path={OUT / 'done.json'} status=COMPLETE", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("probe", "formal", "finalize"))
    parser.add_argument(
        "--complete-eval-budget",
        required=True,
        type=int,
        help="fixed complete-candidate evaluation budget; no default",
    )
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument(
        "--instance-id",
        choices=tuple(str(spec["instance_id"]) for spec in INSTANCE_SPECS),
    )
    args = parser.parse_args()
    archive_limits(args.complete_eval_budget)
    if args.command == "probe":
        if args.instance_id is not None:
            parser.error("--instance-id is not valid for probe")
        run_probe(args.complete_eval_budget, args.workers)
    elif args.command == "formal":
        if args.instance_id is None:
            parser.error("--instance-id is required for formal")
        run_formal(args.instance_id, args.complete_eval_budget, args.workers)
    else:
        if args.instance_id is not None:
            parser.error("--instance-id is not valid for finalize")
        aggregate_and_close(args.complete_eval_budget, args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
