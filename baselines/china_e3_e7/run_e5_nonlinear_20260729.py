#!/usr/bin/env python3
"""Formal E5 nonlinear-charging experiment with blind budget selection."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
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

TASK_ID = "E5-NONLINEAR-CHARGING-01"
OUT = REPO / "baselines/china_e3_e7/e5_nonlinear_20260729"
FLEET = REPO / "data/ChinaInstances/china81_finite_fleet_authority_v1_20260723"
ARMS = (L100_CONTROL.curve_id, NL90_MILD.curve_id)
INSTANCE_SPECS = (
    {
        "instance_id": "cn-prd-50c-01-V2-LOCATIONS",
        "sample_role": "MAIN_EXHIBIT",
        "seeds": tuple(range(1, 11)),
        "sealed_exposure": "5/20 sessions above 90% SOC; max SOC 100%",
    },
    {
        "instance_id": "cn-prd-100c-02-V2-LOCATIONS",
        "sample_role": "MEDIUM_SCALE_VALIDATION",
        "seeds": tuple(range(1, 6)),
        "sealed_exposure": "5/30 sessions above 90% SOC (16.7%); max SOC 100%",
    },
)
EXCLUDED_INSTANCE = {
    "instance_id": "cn-prd-150c-01-V2-LOCATIONS",
    "reason": "0/40 sessions above 90% SOC; max SOC 65.05%",
}
INITIAL_PILOT_BUDGETS = (32, 56, 80)
UPWARD_BUDGET_START = 160
UPWARD_BUDGET_STEP = 80
STARVATION_FRACTION_THRESHOLD = 0.5
STARVED_UNIT_SHARE_LIMIT = 0.20
MAX_WORKERS = 4
MAX_HGS_ITERATIONS_PER_VIEW = 5_000
EXACT_ELITES_PER_VIEW = 8
MIP_TIME_LIMIT_SECONDS = 5.0
REQUIRED_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
)
LOCKED_SOURCES = (
    Path(__file__).resolve(),
    REPO / "baselines/china_e3_e7/check_e5_nonlinear_20260729.py",
    REPO / "baselines/china_e3_e7/watch_e5_report_20260729.py",
    REPO / "docs/handoff/contract_e5e7_blind_01_20260728/report.md",
    REPO / "docs/handoff/advisor_instance_selection_01_20260729/report.md",
    REPO / "docs/paper_v2/paper_main.tex",
    PROTOTYPE / "epochal_hgs.py",
    PROTOTYPE / "route_pool_sp.py",
    PROTOTYPE / "pyvrp_adapter.py",
    REPO / "solver/src/setp_solver/china81.py",
    REPO / "solver/src/setp_solver/china81_completion.py",
    REPO / "solver/src/setp_solver/charging_curve.py",
    REPO / "solver/src/setp_solver/solution.py",
    *PROTECTED,
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def payload_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


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


def source_hashes() -> dict[str, str]:
    return {relative(path): file_sha256(path) for path in LOCKED_SOURCES}


def core_data_hashes() -> dict[str, str]:
    rows: dict[str, str] = {}
    for spec in INSTANCE_SPECS:
        bundle = load_china81_bundle(REPO, str(spec["instance_id"]))
        current = input_hashes(bundle)
        for path, digest in current.items():
            if path in rows and rows[path] != digest:
                raise RuntimeError(f"HALT_E5_CORE_DATA_HASH_CONFLICT:{path}")
            rows[path] = digest
    return dict(sorted(rows.items()))


def task_specs(arms: tuple[str, ...] = ARMS) -> list[dict[str, Any]]:
    return [
        {
            "instance_id": str(spec["instance_id"]),
            "sample_role": str(spec["sample_role"]),
            "seed": int(seed),
            "arm": arm,
        }
        for spec in INSTANCE_SPECS
        for seed in spec["seeds"]
        for arm in arms
    ]


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
        mode: base + (1 if index < remainder else 0) for index, mode in enumerate(modes)
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


def preflight_environment() -> dict[str, Any]:
    wrong = {
        name: os.environ.get(name)
        for name, expected in REQUIRED_THREAD_ENV.items()
        if os.environ.get(name) != expected
    }
    if wrong:
        raise RuntimeError(f"HALT_E5_THREAD_ENV_NOT_FROZEN:{wrong}")
    for path in LOCKED_SOURCES:
        if not path.is_file():
            raise RuntimeError(f"HALT_E5_MISSING_LOCKED_SOURCE:{path}")
    try:
        pyvrp_version = version("pyvrp")
    except Exception as exc:
        raise RuntimeError(f"HALT_E5_PYVRP_UNAVAILABLE:{exc}") from exc
    if pyvrp_version != "0.12.2":
        raise RuntimeError(f"HALT_E5_PYVRP_VERSION:{pyvrp_version}!=0.12.2")
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "pyvrp": pyvrp_version,
        "scipy": version("scipy"),
        "thread_environment": dict(REQUIRED_THREAD_ENV),
        "max_workers": MAX_WORKERS,
    }


def verify_source_lock() -> dict[str, Any]:
    lock_path = OUT / "source_lock.json"
    if not lock_path.is_file():
        raise RuntimeError("HALT_E5_SOURCE_LOCK_MISSING")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    current = source_hashes()
    if current != lock["source_sha256"]:
        changed = sorted(
            key
            for key in set(current) | set(lock["source_sha256"])
            if current.get(key) != lock["source_sha256"].get(key)
        )
        raise RuntimeError(f"HALT_E5_LOCKED_SOURCE_CHANGED:{changed}")
    protected = {relative(path): current[relative(path)] for path in PROTECTED}
    if protected != lock["protected_source_sha256"]:
        raise RuntimeError("HALT_E5_PROTECTED_SOURCE_CHANGED")
    current_core = core_data_hashes()
    if current_core != lock["core_data_sha256"]:
        changed = sorted(
            key
            for key in set(current_core) | set(lock["core_data_sha256"])
            if current_core.get(key) != lock["core_data_sha256"].get(key)
        )
        raise RuntimeError(f"HALT_E5_CORE_DATA_CHANGED:{changed}")
    return lock


def prepare() -> None:
    if (OUT / "done.json").exists():
        raise RuntimeError("E5 already has a terminal done.json")
    OUT.mkdir(parents=True, exist_ok=True)
    environment = preflight_environment()
    sources = source_hashes()
    core_data = core_data_hashes()
    protected = {relative(path): sources[relative(path)] for path in PROTECTED}
    task_card = {
        "schema_version": "E5-TASK-CARD-v1",
        "task_id": TASK_ID,
        "prepared_at_utc": now_iso(),
        "approved_instances": [
            {
                "instance_id": spec["instance_id"],
                "sample_role": spec["sample_role"],
                "seeds": list(spec["seeds"]),
                "sealed_exposure": spec["sealed_exposure"],
            }
            for spec in INSTANCE_SPECS
        ],
        "excluded_instance": EXCLUDED_INSTANCE,
        "arms": {
            L100_CONTROL.curve_id: asdict(L100_CONTROL),
            NL90_MILD.curve_id: asdict(NL90_MILD),
        },
        "common_nonlinear_checker_curve": asdict(NL90_MILD),
        "expected_units_per_arm": 15,
        "expected_total_formal_rows": 30,
        "infeasible_denominator_policy": (
            "retain every expected unit in nonlinear feasibility denominators"
        ),
        "common_initial_and_seed": True,
        "max_workers": MAX_WORKERS,
        "environment": environment,
    }
    preregistration = {
        "schema_version": "E5-PREREGISTRATION-v1",
        "task_id": TASK_ID,
        "sealed_before_any_pilot_or_formal_search": True,
        "pilot": {
            "primary_budget_unit": "complete_candidate_evaluation_attempt",
            "candidate_budgets_in_ascending_order": list(INITIAL_PILOT_BUDGETS),
            "starved_unit_rule": "L/S > 0.5",
            "arm_starvation_rule": "share(starved units) > 0.20",
            "minimum_passing_budget_per_arm": True,
            "common_formal_budget": (
                "larger of the two arm-specific minimum passing budgets"
            ),
            "upward_only_if_32_56_80_fail": (
                "160, 240, 320, ... until passing; never accept a starved tier"
            ),
            "pilot_cost_blinding": (
                "pilot files and parent summaries contain no objective or "
                "between-arm cost difference"
            ),
        },
        "endpoints": {
            "nonlinear_feasibility": (
                "common NL90 checker feasible count / all expected units"
            ),
            "false_feasible_linear_plan": (
                "L100 feasible under L100 but infeasible under common NL90"
            ),
            "full_sample_rank": (
                "infeasible is conceptual +infinity; report W/L/T/both-infeasible"
            ),
            "conditional_cost_effect": (
                "100*(C_L100_replayed_NL90-C_NL90)/C_L100_replayed_NL90 "
                "on paired both-feasible units only, with coverage"
            ),
            "session_duration": (
                "for every session report SOC endpoints and NL90-L100 duration"
            ),
        },
        "result_writing": {
            "POSITIVE": ("report nonlinear-feasibility difference and cost effect"),
            "NEAR_ZERO": (
                "use effective-interval boundary wording and state exactly: "
                "在本情景的充电深度分布下非线性效应有限"
            ),
            "NEGATIVE": "report the negative result without deletion or subset selection",
            "MIXED": "report both directions without collapsing them",
        },
        "display_precision": {
            "rates_percent_decimals": 1,
            "cost_effect_percent_decimals": 1,
        },
        "halt_conditions": [
            "missing or failed independent certificate",
            "non-exact complete-candidate budget consumption",
            "wallclock safety trigger",
            "source or protected-file hash drift",
            "missing expected unit",
            "common initial hash mismatch within an instance-seed pair",
        ],
    }
    lock = {
        "schema_version": "E5-SOURCE-LOCK-v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "source_sha256": sources,
        "core_data_sha256": core_data,
        "protected_source_sha256": protected,
    }
    lock["lock_id"] = payload_sha256(lock)
    atomic_json(OUT / "task_card.json", task_card)
    atomic_json(OUT / "preregistration.json", preregistration)
    atomic_json(OUT / "source_lock.json", lock)
    print(f"PREPARED {OUT}", flush=True)


def strict_improvement_flags(trace: list[dict[str, Any]]) -> list[int]:
    incumbent = float("inf")
    flags: list[int] = []
    for row in trace:
        objective = row.get("complete_objective")
        improved = objective is not None and float(objective) < incumbent - 1.0e-9
        flags.append(int(improved))
        if improved:
            incumbent = float(objective)
    return flags


def task_stem(spec: dict[str, Any]) -> str:
    return f"{spec['instance_id']}__seed-{int(spec['seed']):02d}__{spec['arm']}"


def run_search_unit(payload: dict[str, Any]) -> dict[str, Any]:
    for name, value in REQUIRED_THREAD_ENV.items():
        os.environ[name] = value
    spec = dict(payload["spec"])
    phase = str(payload["phase"])
    budget = int(payload["budget"])
    lock_id = str(payload["lock_id"])
    root = Path(str(payload["output_root"]))
    stem = task_stem(spec)
    if phase == "pilot":
        path = root / "pilot" / f"budget-{budget}" / "tasks" / f"{stem}.json"
    elif phase == "formal":
        path = root / "formal" / "task_status" / f"{stem}.json"
    else:
        raise ValueError(f"unknown phase: {phase}")
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if (
            existing.get("status") == "PASS"
            and int(existing.get("budget", -1)) == budget
            and existing.get("source_lock_id") == lock_id
        ):
            return existing
        raise RuntimeError(f"HALT_E5_STALE_TASK_ARTIFACT:{path}")

    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    base_bundle = load_china81_bundle(REPO, str(spec["instance_id"]))
    bundle = curve_bundle(base_bundle, str(spec["arm"]))
    initial = load_initial(str(spec["instance_id"]))
    archives = archive_limits(budget)
    safety = max(180.0, 2.0 * (len(bundle.instance.nodes) - 1))
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
    last = int(stats["last_strict_improvement_evaluation"])
    fraction = float(stats["last_strict_improvement_fraction"])
    if (
        attempts != budget
        or expected != budget
        or not bool(stats["complete_candidate_budget_exactly_consumed"])
    ):
        raise RuntimeError(
            f"HALT_E5_NONEXACT_BUDGET:{stem}:{attempts}:{expected}:{budget}"
        )
    if bool(stats["wallclock_safety_triggered"]):
        raise RuntimeError(f"HALT_E5_WALLCLOCK_SAFETY_TRIGGERED:{stem}")
    flags = strict_improvement_flags(stats["complete_candidate_evaluation_trace"])
    if len(flags) != attempts or sum(flags) < 1:
        raise RuntimeError(f"HALT_E5_INVALID_BLIND_TRACE:{stem}")
    blind = {
        "schema_version": "E5-BLIND-PILOT-UNIT-v1",
        "task_id": TASK_ID,
        **spec,
        "phase": phase,
        "budget": budget,
        "archive_candidates_per_view": archives,
        "complete_candidate_evaluations_S": attempts,
        "last_strict_improvement_evaluation_L": last,
        "last_strict_improvement_fraction_L_over_S": fraction,
        "starved_L_over_S_gt_0_5": int(fraction > STARVATION_FRACTION_THRESHOLD),
        "strict_improvement_flags_without_objectives": flags,
        "wallclock_safety_seconds_per_view": safety,
        "wallclock_safety_triggered": False,
        "elapsed_wall_seconds": time.perf_counter() - started_wall,
        "elapsed_cpu_seconds": time.process_time() - started_cpu,
        "common_initial_solution_sha256": initial_hash(initial),
        "source_lock_id": lock_id,
        "status": "PASS",
    }
    if phase == "pilot":
        atomic_json(path, blind)
        return blind

    solution = solution_payload(run.solution)
    trace_path = root / "formal" / "search_traces" / f"{stem}.json"
    trace_payload = {
        "schema_version": "E5-FORMAL-SEARCH-TRACE-v1",
        "task_id": TASK_ID,
        **spec,
        "budget": budget,
        "complete_candidate_evaluation_trace": stats[
            "complete_candidate_evaluation_trace"
        ],
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
    plan = {
        "schema_version": "E5-FORMAL-PLAN-v1",
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
    plan_path = root / "formal" / "plans" / f"{stem}.json"
    atomic_json(plan_path, plan)
    status = {
        **blind,
        "schema_version": "E5-FORMAL-SEARCH-UNIT-v1",
        "plan_path": relative(plan_path),
        "plan_file_sha256": file_sha256(plan_path),
        "search_trace_path": relative(trace_path),
        "search_trace_sha256": file_sha256(trace_path),
    }
    atomic_json(path, status)
    return status


def run_parallel(
    specs: list[dict[str, Any]],
    *,
    phase: str,
    budget: int,
    lock_id: str,
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
    with ProcessPoolExecutor(max_workers=MAX_WORKERS, mp_context=context) as executor:
        futures = {
            executor.submit(run_search_unit, payload): payload["spec"]
            for payload in payloads
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            spec = futures[future]
            row = future.result()
            rows.append(row)
            print(
                "PROGRESS "
                f"phase={phase} budget={budget} completed={completed}/"
                f"{len(futures)} unit={task_stem(spec)}",
                flush=True,
            )
    return sorted(
        rows,
        key=lambda row: (row["arm"], row["instance_id"], int(row["seed"])),
    )


def pilot(lock_id: str) -> dict[str, Any]:
    arm_minimum: dict[str, int] = {}
    budget = INITIAL_PILOT_BUDGETS[0]
    tested_budgets: list[int] = []
    while len(arm_minimum) < len(ARMS):
        if budget not in tested_budgets:
            tested_budgets.append(budget)
        active = tuple(arm for arm in ARMS if arm not in arm_minimum)
        rows = run_parallel(
            task_specs(active), phase="pilot", budget=budget, lock_id=lock_id
        )
        atomic_csv(
            OUT / "pilot" / f"budget-{budget}" / "raw_blind.csv",
            [
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
                    "last_strict_improvement_fraction_L_over_S": row[
                        "last_strict_improvement_fraction_L_over_S"
                    ],
                    "starved_L_over_S_gt_0_5": row["starved_L_over_S_gt_0_5"],
                    "wallclock_safety_triggered": row["wallclock_safety_triggered"],
                    "elapsed_wall_seconds": row["elapsed_wall_seconds"],
                    "elapsed_cpu_seconds": row["elapsed_cpu_seconds"],
                    "status": row["status"],
                }
                for row in rows
            ],
        )
        decisions: list[dict[str, Any]] = []
        for arm in active:
            arm_rows = [row for row in rows if row["arm"] == arm]
            if len(arm_rows) != 15:
                raise RuntimeError(f"HALT_E5_PILOT_DENOMINATOR:{arm}:{len(arm_rows)}")
            starved = sum(int(row["starved_L_over_S_gt_0_5"]) for row in arm_rows)
            share = starved / len(arm_rows)
            passed = share <= STARVED_UNIT_SHARE_LIMIT
            decisions.append(
                {
                    "arm": arm,
                    "budget": budget,
                    "unit_count": len(arm_rows),
                    "starved_unit_count": starved,
                    "starved_unit_share": share,
                    "passes_share_le_0_20": passed,
                }
            )
            if passed:
                arm_minimum[arm] = budget
        atomic_json(
            OUT / "pilot" / f"budget-{budget}" / "blind_decision.json",
            {
                "schema_version": "E5-BLIND-PILOT-DECISION-v1",
                "task_id": TASK_ID,
                "budget": budget,
                "objective_or_between_arm_cost_fields_present": False,
                "decisions": decisions,
            },
        )
        if len(arm_minimum) == len(ARMS):
            break
        if budget in INITIAL_PILOT_BUDGETS:
            index = INITIAL_PILOT_BUDGETS.index(budget)
            budget = (
                INITIAL_PILOT_BUDGETS[index + 1]
                if index + 1 < len(INITIAL_PILOT_BUDGETS)
                else UPWARD_BUDGET_START
            )
        else:
            budget += UPWARD_BUDGET_STEP
    selected = max(arm_minimum.values())
    decision = {
        "schema_version": "E5-BLIND-PILOT-SELECTOR-v1",
        "task_id": TASK_ID,
        "status": "PASS",
        "arm_specific_minimum_passing_budget": arm_minimum,
        "selected_common_formal_budget": selected,
        "selection_rule": "max of arm-specific minimum passing budgets",
        "tested_budgets": tested_budgets,
        "cost_blinding_attestation": (
            "no objective or between-arm cost difference was read, serialized, "
            "or used by the selector"
        ),
    }
    decision["pilot_decision_id"] = payload_sha256(decision)
    atomic_json(OUT / "pilot_decision.json", decision)
    lock = {
        "schema_version": "E5-EXECUTION-LOCK-v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "selected_common_formal_budget": selected,
        "pilot_decision_id": decision["pilot_decision_id"],
        "source_lock_id": lock_id,
        "arms": list(ARMS),
        "instances_and_seeds": task_specs((ARMS[0],)),
        "max_workers": MAX_WORKERS,
    }
    lock["execution_lock_id"] = payload_sha256(lock)
    atomic_json(OUT / "execution_lock.json", lock)
    print(f"PILOT_PASS selected_common_formal_budget={selected}", flush=True)
    return lock


def verify_pair_invariants(status_rows: list[dict[str, Any]]) -> None:
    if len(status_rows) != 30:
        raise RuntimeError(f"HALT_E5_FORMAL_ROW_DENOMINATOR:{len(status_rows)}!=30")
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in status_rows:
        key = (str(row["instance_id"]), int(row["seed"]))
        groups.setdefault(key, []).append(row)
    if len(groups) != 15:
        raise RuntimeError(f"HALT_E5_PAIR_DENOMINATOR:{len(groups)}!=15")
    for key, pair in groups.items():
        if {row["arm"] for row in pair} != set(ARMS):
            raise RuntimeError(f"HALT_E5_PAIR_ARMS:{key}")
        if len({row["common_initial_solution_sha256"] for row in pair}) != 1:
            raise RuntimeError(f"HALT_E5_COMMON_INITIAL_MISMATCH:{key}")
        if len({int(row["budget"]) for row in pair}) != 1:
            raise RuntimeError(f"HALT_E5_COMMON_BUDGET_MISMATCH:{key}")


def run_independent_checker() -> None:
    checker = REPO / "baselines/china_e3_e7/check_e5_nonlinear_20260729.py"
    subprocess.run(
        [sys.executable, str(checker), "--output-root", str(OUT)],
        cwd=REPO,
        env={**os.environ, **REQUIRED_THREAD_ENV},
        check=True,
    )


def cert_payloads() -> list[dict[str, Any]]:
    paths = sorted((OUT / "certificates").glob("*.json"))
    if len(paths) != 30:
        raise RuntimeError(f"HALT_E5_CERTIFICATE_DENOMINATOR:{len(paths)}!=30")
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if any(row.get("certificate_status") != "PASS" for row in rows):
        raise RuntimeError("HALT_E5_FAILED_CERTIFICATE")
    return rows


def summary_for_subset(certs: list[dict[str, Any]], label: str) -> dict[str, Any]:
    groups: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for row in certs:
        key = (str(row["instance_id"]), int(row["seed"]))
        groups.setdefault(key, {})[str(row["arm"])] = row
    if any(set(pair) != set(ARMS) for pair in groups.values()):
        raise RuntimeError(f"HALT_E5_INCOMPLETE_CERTIFICATE_PAIR:{label}")
    denominator = len(groups)
    arm_feasible = {
        arm: sum(int(pair[arm]["nonlinear_feasible"]) for pair in groups.values())
        for arm in ARMS
    }
    wins = losses = ties = both_infeasible = 0
    diffs_cny: list[float] = []
    effects_pct: list[float] = []
    pair_rows: list[dict[str, Any]] = []
    for (instance_id, seed), pair in sorted(groups.items()):
        left = pair[L100_CONTROL.curve_id]
        right = pair[NL90_MILD.curve_id]
        left_feasible = bool(left["nonlinear_feasible"])
        right_feasible = bool(right["nonlinear_feasible"])
        left_cost = left["full_model_total_cost_cny"]
        right_cost = right["full_model_total_cost_cny"]
        if right_feasible and not left_feasible:
            rank = "NL90_WIN"
            wins += 1
        elif left_feasible and not right_feasible:
            rank = "NL90_LOSS"
            losses += 1
        elif not left_feasible and not right_feasible:
            rank = "BOTH_INFEASIBLE"
            both_infeasible += 1
        else:
            diff = float(left_cost) - float(right_cost)
            effect = 100.0 * diff / float(left_cost)
            diffs_cny.append(diff)
            effects_pct.append(effect)
            if diff > 1.0e-7:
                rank = "NL90_WIN"
                wins += 1
            elif diff < -1.0e-7:
                rank = "NL90_LOSS"
                losses += 1
            else:
                rank = "TIE"
                ties += 1
        pair_rows.append(
            {
                "summary_scope": label,
                "instance_id": instance_id,
                "seed": seed,
                "L100_nonlinear_feasible": int(left_feasible),
                "NL90_nonlinear_feasible": int(right_feasible),
                "L100_nonlinear_cost_cny": (
                    left_cost if left_feasible else "NA_INFEASIBLE"
                ),
                "NL90_nonlinear_cost_cny": (
                    right_cost if right_feasible else "NA_INFEASIBLE"
                ),
                "rank": rank,
                "L100_minus_NL90_cost_cny_both_feasible": (
                    float(left_cost) - float(right_cost)
                    if left_feasible and right_feasible
                    else "NA_NOT_BOTH_FEASIBLE"
                ),
                "NL90_saving_pct_both_feasible": (
                    100.0 * (float(left_cost) - float(right_cost)) / float(left_cost)
                    if left_feasible and right_feasible
                    else "NA_NOT_BOTH_FEASIBLE"
                ),
            }
        )
    false_feasible = sum(
        int(row["linear_plan_false_feasible"])
        for row in certs
        if row["arm"] == L100_CONTROL.curve_id
    )
    return {
        "scope": label,
        "paired_unit_denominator": denominator,
        "nonlinear_feasible_count": arm_feasible,
        "nonlinear_feasible_rate": {
            arm: arm_feasible[arm] / denominator for arm in ARMS
        },
        "nonlinear_feasible_rate_difference_NL90_minus_L100": (
            arm_feasible[NL90_MILD.curve_id] - arm_feasible[L100_CONTROL.curve_id]
        )
        / denominator,
        "linear_plan_false_feasible_count": false_feasible,
        "linear_plan_false_feasible_rate": false_feasible / denominator,
        "full_sample_rank": {
            "NL90_wins": wins,
            "NL90_losses": losses,
            "ties": ties,
            "both_infeasible": both_infeasible,
            "net_win_share": (wins - losses) / denominator,
        },
        "conditional_both_feasible_cost": {
            "coverage_count": len(diffs_cny),
            "coverage_rate": len(diffs_cny) / denominator,
            "mean_L100_minus_NL90_cny": (
                arithmetic_mean(diffs_cny) if diffs_cny else None
            ),
            "median_L100_minus_NL90_cny": (median(diffs_cny) if diffs_cny else None),
            "mean_NL90_saving_pct": (
                arithmetic_mean(effects_pct) if effects_pct else None
            ),
            "median_NL90_saving_pct": (median(effects_pct) if effects_pct else None),
            "min_NL90_saving_pct": min(effects_pct) if effects_pct else None,
            "max_NL90_saving_pct": max(effects_pct) if effects_pct else None,
        },
        "pair_rows": pair_rows,
    }


def verdict(overall: dict[str, Any]) -> str:
    feasibility_pp = round(
        100.0 * overall["nonlinear_feasible_rate_difference_NL90_minus_L100"],
        1,
    )
    net_pp = round(100.0 * overall["full_sample_rank"]["net_win_share"], 1)
    if feasibility_pp == 0.0 and net_pp == 0.0:
        return "NEAR_ZERO"
    if feasibility_pp >= 0.0 and net_pp >= 0.0:
        return "POSITIVE"
    if feasibility_pp <= 0.0 and net_pp <= 0.0:
        return "NEGATIVE"
    return "MIXED"


def render_report(
    decision: dict[str, Any],
    pilot_decision: dict[str, Any],
    cause_rows: list[dict[str, Any]],
) -> str:
    overall = decision["summaries"]["OVERALL"]
    main = decision["summaries"]["MAIN_EXHIBIT"]
    validation = decision["summaries"]["MEDIUM_SCALE_VALIDATION"]

    def pct(value: float) -> str:
        return f"{100.0 * value:.1f}%"

    def scope_block(title: str, row: dict[str, Any]) -> str:
        conditional = row["conditional_both_feasible_cost"]
        cost_text = (
            "无共同可行单元，条件成本效应不可识别"
            if conditional["coverage_count"] == 0
            else (
                f"共同可行 {conditional['coverage_count']}/"
                f"{row['paired_unit_denominator']}；L100−NL90 平均成本差 "
                f"{conditional['mean_L100_minus_NL90_cny']:.2f} CNY，"
                f"中位数 {conditional['median_L100_minus_NL90_cny']:.2f} CNY；"
                f"NL90 平均节约 {conditional['mean_NL90_saving_pct']:.2f}%"
            )
        )
        return (
            f"### {title}\n\n"
            f"共同非线性检查器下，L100_control 可行 "
            f"{row['nonlinear_feasible_count'][L100_CONTROL.curve_id]}/"
            f"{row['paired_unit_denominator']}（"
            f"{pct(row['nonlinear_feasible_rate'][L100_CONTROL.curve_id])}）；"
            f"NL90_mild 可行 "
            f"{row['nonlinear_feasible_count'][NL90_MILD.curve_id]}/"
            f"{row['paired_unit_denominator']}（"
            f"{pct(row['nonlinear_feasible_rate'][NL90_MILD.curve_id])}）。"
            f"可行率差 NL90−L100 为 "
            f"{100.0 * row['nonlinear_feasible_rate_difference_NL90_minus_L100']:.1f} "
            "个百分点。\n\n"
            f"线性计划假可行为 {row['linear_plan_false_feasible_count']}/"
            f"{row['paired_unit_denominator']}（"
            f"{pct(row['linear_plan_false_feasible_rate'])}）。完整样本排序为 "
            f"W/L/T/双不可行 = {row['full_sample_rank']['NL90_wins']}/"
            f"{row['full_sample_rank']['NL90_losses']}/"
            f"{row['full_sample_rank']['ties']}/"
            f"{row['full_sample_rank']['both_infeasible']}。{cost_text}。\n"
        )

    result_line = {
        "POSITIVE": "结果方向为正向：报告可行率差与成本效应。",
        "NEAR_ZERO": (
            "结果落在预登记的接近零边界：在本情景的充电深度分布下"
            "非线性效应有限；未删除数据或挑选子集。"
        ),
        "NEGATIVE": "结果方向为负向：以下按预登记口径如实报告。",
        "MIXED": "结果方向混合：可行率与完整样本成本排序不作单向合并。",
    }[decision["verdict"]]
    causes = (
        "无共同非线性不可行原因。"
        if not cause_rows
        else "\n".join(
            f"- {row['arm']} / {row['cause_category']}: "
            f"{row['affected_unit_count']} 个单元，{row['violation_count']} 条违反。"
            for row in cause_rows
        )
    )
    return f"""# E5-NONLINEAR-CHARGING-01 报告

## 结论

{result_line} 所有 15 个配对单元均保留在可行率分母中；成本效应只在共同可行单元上另行条件报告，不以条件样本替代完整样本结论。

## 冻结设计与预算

主展品为 `cn-prd-50c-01-V2-LOCATIONS`（种子 1--10），中规模验证为 `cn-prd-100c-02-V2-LOCATIONS`（种子 1--5）。`cn-prd-150c-01-V2-LOCATIONS` 因封存解中 0/40 个会话进入 SOC>90% 区间、最大 SOC 65.05%，按用户批准决定排除。两臂只在充电物理上不同，初始解、种子、订单、时间窗、车场与候选评价预算完全相同。

结果盲 pilot 给出的臂内最小无饥饿预算为 `{json.dumps(pilot_decision["arm_specific_minimum_passing_budget"], ensure_ascii=False, sort_keys=True)}`；正式共同预算取较大者 `{pilot_decision["selected_common_formal_budget"]}` 次完整候选评价。判据为每单元 `L/S>0.5`，该类单元占比超过 20% 才判该臂饥饿。pilot 文件不含目标值或臂间成本差。

## 主要结果

{scope_block("全部 15 个配对单元", overall)}

{scope_block("主展品：50c-01", main)}

{scope_block("中规模验证：100c-02", validation)}

## 不可行原因分类

{causes}

其中 `ELECTRIC_ENERGY_SHORTFALL_OR_SOC` 对应电量不足或 SOC 约束，`TIME_WINDOW_OVERRUN` 对应时间窗超限，`INTER_TRIP_CONNECTION_OR_ROUTE_CONTINUITY` 对应趟间衔接或车辆连续性失败。为防止零类被误认为遗漏，完整分类计数同时见 `infeasibility_causes.csv`。

## 每个充电会话

`charging_sessions.csv` 对 30 个臂单元中的每个充电会话逐条给出起止 SOC、额定功率、线性持续时间、非线性持续时间及二者之差。线性臂的共同非线性复算仅替换占用时长与曲线标识；路线、车辆、站点、充电开始时刻和电量均不修复，并由证书中的前后结构哈希相等证明。

## 独立复算与审计边界

30 个方案均由独立进程 `check_e5_nonlinear_20260729.py` 复算。该进程直接调用共同 `check_solution`/`evaluate`，并与 `exact_china81_score` 的违反台账和成本分解逐单元比对。科学终态由同目录的 `done.json` 以及 `metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json` 和本报告共同定义。限时 MIP 仅表示在 5 秒限时内所得路线池重组方案，不声称已证明最优。
"""


def aggregate(execution_lock: dict[str, Any]) -> None:
    verify_source_lock()
    certs = cert_payloads()
    raw_rows: list[dict[str, Any]] = []
    session_rows: list[dict[str, Any]] = []
    unit_categories: dict[tuple[str, str, int, str], int] = {}
    cause_counts: dict[tuple[str, str], int] = {}
    for row in sorted(
        certs,
        key=lambda item: (item["instance_id"], int(item["seed"]), item["arm"]),
    ):
        categories = row["nonlinear_infeasibility_categories"]
        raw_rows.append(
            {
                "task_id": TASK_ID,
                "instance_id": row["instance_id"],
                "sample_role": row["sample_role"],
                "seed": row["seed"],
                "arm": row["arm"],
                "formal_complete_candidate_budget": execution_lock[
                    "selected_common_formal_budget"
                ],
                "planning_physics_feasible": int(row["planning_physics_feasible"]),
                "common_nonlinear_feasible": int(row["nonlinear_feasible"]),
                "linear_plan_false_feasible": int(row["linear_plan_false_feasible"]),
                "common_nonlinear_full_model_cost_cny": (
                    row["full_model_total_cost_cny"]
                    if row["nonlinear_feasible"]
                    else "NA_INFEASIBLE"
                ),
                "nonlinear_violation_count": len(row["nonlinear_violations"]),
                "nonlinear_infeasibility_categories_json": json.dumps(
                    categories, ensure_ascii=False, sort_keys=True
                ),
                "charging_session_count": len(row["sessions"]),
                "certificate_id": row["certificate_id"],
                "certificate_status": row["certificate_status"],
            }
        )
        for category, count in categories.items():
            unit_categories[
                (
                    row["arm"],
                    category,
                    int(row["seed"]),
                    row["instance_id"],
                )
            ] = count
            cause_counts[(row["arm"], category)] = (
                cause_counts.get((row["arm"], category), 0) + count
            )
        session_rows.extend(row["sessions"])
    if len(raw_rows) != 30:
        raise RuntimeError("HALT_E5_RAW_ROW_DENOMINATOR")
    atomic_csv(OUT / "raw_runs.csv", raw_rows)
    if session_rows:
        atomic_csv(
            OUT / "charging_sessions.csv",
            sorted(
                session_rows,
                key=lambda row: (
                    row["instance_id"],
                    int(row["seed"]),
                    row["arm"],
                    int(row["session_index"]),
                ),
            ),
        )
    else:
        raise RuntimeError("HALT_E5_NO_CHARGING_SESSIONS")

    all_categories = (
        "ELECTRIC_ENERGY_SHORTFALL_OR_SOC",
        "TIME_WINDOW_OVERRUN",
        "INTER_TRIP_CONNECTION_OR_ROUTE_CONTINUITY",
        "CHARGING_TIMING_INCONSISTENCY",
        "CHARGING_DURATION_OR_POWER",
        "CHARGER_CAPACITY_OR_CONCURRENCY",
        "FLEET_CAPACITY",
    )
    discovered = sorted(
        {category for _, category in cause_counts} - set(all_categories)
    )
    cause_rows = []
    for arm in ARMS:
        for category in (*all_categories, *discovered):
            affected = sum(
                1 for key in unit_categories if key[0] == arm and key[1] == category
            )
            violations = cause_counts.get((arm, category), 0)
            cause_rows.append(
                {
                    "arm": arm,
                    "cause_category": category,
                    "affected_unit_count": affected,
                    "violation_count": violations,
                }
            )
    atomic_csv(OUT / "infeasibility_causes.csv", cause_rows)

    overall = summary_for_subset(certs, "OVERALL")
    main = summary_for_subset(
        [row for row in certs if row["sample_role"] == "MAIN_EXHIBIT"],
        "MAIN_EXHIBIT",
    )
    validation = summary_for_subset(
        [row for row in certs if row["sample_role"] == "MEDIUM_SCALE_VALIDATION"],
        "MEDIUM_SCALE_VALIDATION",
    )
    pair_rows = (
        overall.pop("pair_rows") + main.pop("pair_rows") + validation.pop("pair_rows")
    )
    atomic_csv(OUT / "paired_cost_effects.csv", pair_rows)
    decision = {
        "schema_version": "E5-DECISION-v1",
        "task_id": TASK_ID,
        "status": "PASS",
        "verdict": verdict(overall),
        "denominator_policy": (
            "all 15 expected paired units retained in feasibility rates"
        ),
        "summaries": {
            "OVERALL": overall,
            "MAIN_EXHIBIT": main,
            "MEDIUM_SCALE_VALIDATION": validation,
        },
        "result_writing_applied": True,
    }
    decision["decision_id"] = payload_sha256(decision)
    atomic_json(OUT / "decision.json", decision)
    pilot_decision = json.loads(
        (OUT / "pilot_decision.json").read_text(encoding="utf-8")
    )
    metadata = {
        "schema_version": "E5-METADATA-v1",
        "task_id": TASK_ID,
        "status": "PASS",
        "completed_at_utc": now_iso(),
        "instances": [spec["instance_id"] for spec in INSTANCE_SPECS],
        "excluded_instance": EXCLUDED_INSTANCE,
        "arms": list(ARMS),
        "seeds": {
            str(spec["instance_id"]): list(spec["seeds"]) for spec in INSTANCE_SPECS
        },
        "expected_units_per_arm": 15,
        "actual_units_per_arm": {
            arm: sum(1 for row in raw_rows if row["arm"] == arm) for arm in ARMS
        },
        "selected_common_formal_budget": execution_lock[
            "selected_common_formal_budget"
        ],
        "max_workers": MAX_WORKERS,
        "common_nonlinear_checker": {
            "curve": asdict(NL90_MILD),
            "independent_process": True,
            "verification_path": relative(OUT / "independent_verification.json"),
        },
        "source_lock_id": execution_lock["source_lock_id"],
        "execution_lock_id": execution_lock["execution_lock_id"],
        "pilot_decision_id": pilot_decision["pilot_decision_id"],
        "decision_id": decision["decision_id"],
        "environment": preflight_environment(),
    }
    atomic_json(OUT / "metadata.json", metadata)
    report = render_report(
        decision,
        pilot_decision,
        [row for row in cause_rows if row["violation_count"] > 0],
    )
    atomic_text(OUT / "report.md", report)

    protected_now = {relative(path): file_sha256(path) for path in PROTECTED}
    source_lock = json.loads((OUT / "source_lock.json").read_text(encoding="utf-8"))
    if protected_now != source_lock["protected_source_sha256"]:
        raise RuntimeError("HALT_E5_PROTECTED_SOURCE_CHANGED_AT_CLOSEOUT")
    excluded_prefixes = ("monitor_runtime/",)
    excluded_names = {"artifact_hashes.json", "done.json"}
    artifact_rows = []
    for path in sorted(item for item in OUT.rglob("*") if item.is_file()):
        rel = str(path.relative_to(OUT))
        if rel in excluded_names or rel.startswith(excluded_prefixes):
            continue
        artifact_rows.append(
            {"path": rel, "sha256": file_sha256(path), "bytes": path.stat().st_size}
        )
    manifest = {
        "schema_version": "E5-ARTIFACT-HASHES-v1",
        "task_id": TASK_ID,
        "status": "PASS",
        "hash_algorithm": "sha256",
        "excluded_as_volatile_or_self_referential": [
            "artifact_hashes.json",
            "done.json",
            "monitor_runtime/**",
        ],
        "artifacts": artifact_rows,
        "protected_source_sha256_at_closeout": protected_now,
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
        raise RuntimeError("HALT_E5_REQUIRED_TERMINAL_ARTIFACT_MISSING")
    done = {
        "schema_version": "E5-DONE-v1",
        "task_id": TASK_ID,
        "status": "PASS",
        "completed_at_utc": now_iso(),
        "required_artifacts": list(required),
        "required_artifact_sha256": {
            name: file_sha256(OUT / name) for name in required
        },
        "manifest_id": manifest["manifest_id"],
        "decision_id": decision["decision_id"],
    }
    done["done_id"] = payload_sha256(done)
    atomic_json(OUT / "done.json", done)
    print(f"DONE {OUT / 'done.json'}", flush=True)


def run() -> None:
    lock = verify_source_lock()
    environment = preflight_environment()
    print(
        f"PREFLIGHT_PASS python={platform.python_version()} "
        f"pyvrp={environment['pyvrp']} max_workers={MAX_WORKERS}",
        flush=True,
    )
    if (OUT / "execution_lock.json").is_file():
        execution_lock = json.loads(
            (OUT / "execution_lock.json").read_text(encoding="utf-8")
        )
        if execution_lock["source_lock_id"] != lock["lock_id"]:
            raise RuntimeError("HALT_E5_EXECUTION_LOCK_SOURCE_MISMATCH")
    else:
        execution_lock = pilot(lock["lock_id"])
    budget = int(execution_lock["selected_common_formal_budget"])
    formal_rows = run_parallel(
        task_specs(), phase="formal", budget=budget, lock_id=lock["lock_id"]
    )
    verify_pair_invariants(formal_rows)
    atomic_csv(
        OUT / "formal_search_manifest.csv",
        [
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
                "last_strict_improvement_fraction_L_over_S": row[
                    "last_strict_improvement_fraction_L_over_S"
                ],
                "elapsed_wall_seconds": row["elapsed_wall_seconds"],
                "elapsed_cpu_seconds": row["elapsed_cpu_seconds"],
                "common_initial_solution_sha256": row["common_initial_solution_sha256"],
                "plan_path": row["plan_path"],
                "plan_file_sha256": row["plan_file_sha256"],
                "search_trace_path": row["search_trace_path"],
                "search_trace_sha256": row["search_trace_sha256"],
                "status": row["status"],
            }
            for row in formal_rows
        ],
    )
    run_independent_checker()
    aggregate(execution_lock)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "run"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    else:
        run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
