#!/usr/bin/env python3
"""SCOUT3: exploratory effect detection for three ReSETP mechanisms.

This runner is additive and deliberately reuses the audited China81 completion
and dynamic-execution machinery.  It never edits solver or paper sources.
Every MV-HGS-SP call uses exactly 25,000 iterations in each of the registered
cv_only, naive_ev, and mechanism_ev views, with no no-improvement stop.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


RUNNER = Path(__file__).resolve()
REPO = RUNNER.parents[2]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
# Avoid baselines/china_e3_e7/statistics.py shadowing Python's stdlib module.
while str(RUNNER.parent) in sys.path:
    sys.path.remove(str(RUNNER.parent))
for entry in (REPO, REPO / "solver/src", REPO / "models/src", PROTOTYPE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from setp_solver.charging_curve import L100_CONTROL, NL90_MILD
from setp_solver.china81 import (
    CHINA81_HORIZON_END_SECOND,
    CHINA81_HORIZON_START_SECOND,
    load_china81_bundle,
)
from setp_solver.china81_completion import exact_china81_score
from setp_solver.model_config import ModelConfig, model_config_scope
from setp_solver.search.multitrip_schedule import prepare_multitrip_solution
from setp_solver.solution import Route, Solution, physical_vehicle_id


TASK_ID = "SCOUT3"
INSTANCE_ID = "cn-cy-100c-01-V2-LOCATIONS"
SEEDS = tuple(range(1, 11))
LEVELS = (0, 25, 50, 75, 100)
VIEWS = ("cv_only", "naive_ev", "mechanism_ev")
ITERATIONS_PER_VIEW = 25_000
NO_IMPROVEMENT_STOP = None
EXACT_ELITES_PER_VIEW = 8
ARCHIVE_PER_VIEW = 24
SP_SECONDS = 5.0
WALLCLOCK_SAFETY_SECONDS_PER_VIEW = 86_400.0
FIXED_COST_CNY = 170.0
MODEL_CONFIG = ModelConfig(
    strict_multitrip=True,
    depot_charger_capacity_mode="unbounded",
)
AUTHORITY = REPO / "data/ChinaInstances/china81_finite_fleet_authority_v3_20260802"
AUTHORITY_EVIDENCE = REPO / "baselines/china_e3_e7/fleet_authority_v3_20260802"
OUTPUT = REPO / "baselines/china_e3_e7/scout_three_mechanisms_20260803"
ARMS = {
    "fleet": OUTPUT / "arm_fleet",
    "dynamic": OUTPUT / "arm_dynamic",
    "nonlinear": OUTPUT / "arm_nonlinear",
}
TOL = 1e-9

PER_ORDER = "per_order"
FIXED_10800 = "fixed_10800_seconds"
HYBRID_8_OR_10800 = "hybrid_8_orders_or_10800_seconds"
DYNAMIC_POLICIES = (PER_ORDER, FIXED_10800, HYBRID_8_OR_10800)
DYNAMIC_LABELS = {
    PER_ORDER: "continuous_per_order",
    FIXED_10800: "periodic_10800_seconds",
    HYBRID_8_OR_10800: "current_code_qbar8_or_delta10800",
}

HASH_EXCLUDES = {
    "artifact_hashes.json",
    "done.json",
    "progress.json",
    "status.json",
    "run.log",
}


def now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    temporary.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return value


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    if not fields:
        fields = ["status"]
        rows = [{"status": "NO_ROWS"}]
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field)) for field in fields})
    temporary.replace(path)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip()


def source_paths() -> list[Path]:
    paths: set[Path] = {RUNNER}
    paths.update(
        p.resolve()
        for root in (REPO / "solver/src/setp_solver", PROTOTYPE)
        for p in root.rglob("*.py")
        if not p.name.startswith("._") and "__pycache__" not in p.parts
    )
    paths.update(
        {
            (REPO / "baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py").resolve(),
            (REPO / "baselines/china_e3_e7/formal_dynamic_dispatch_20260802_runner.py").resolve(),
            (REPO / "baselines/china_e3_e7/e7_o1_replanning_20260801/policy.py").resolve(),
            (REPO / "docs/paper_submission_final/RETIRED_paper_main.tex").resolve(),
            (AUTHORITY / "fleet_caps.csv").resolve(),
            (AUTHORITY / "metadata.json").resolve(),
            (AUTHORITY / "decision.json").resolve(),
            (AUTHORITY / "witnesses" / f"{INSTANCE_ID}.json").resolve(),
        }
    )
    return sorted(path for path in paths if path.is_file())


def source_hashes() -> dict[str, str]:
    return {str(path.relative_to(REPO)): file_sha(path) for path in source_paths()}


def verify_source_lock(expected: Mapping[str, str]) -> None:
    observed = source_hashes()
    if observed != dict(expected):
        changed = sorted(
            key for key in set(observed) | set(expected) if observed.get(key) != expected.get(key)
        )
        raise RuntimeError("SOURCE_DRIFT: " + ", ".join(changed[:30]))


def input_hashes() -> dict[str, str]:
    bundle = load_china81_bundle(
        REPO, INSTANCE_ID, fleet_authority=AUTHORITY, model_config=MODEL_CONFIG
    )
    paths = {REPO / str(value) for value in bundle.source_paths.values()}
    paths.update({AUTHORITY / "metadata.json", AUTHORITY / "decision.json"})
    return {str(path.relative_to(REPO)): file_sha(path) for path in sorted(paths) if path.is_file()}


def artifact_hashes(root: Path) -> dict[str, Any]:
    artifacts: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("._") or path.name in HASH_EXCLUDES:
            continue
        if "__pycache__" in path.parts or ".pytest_cache" in path.parts:
            continue
        artifacts[str(path.relative_to(root))] = file_sha(path)
    return {
        "schema": "resetp.scout3.artifact-hashes.v1",
        "algorithm": "sha256",
        "excluded": ["artifact_hashes.json", "done.json", "progress.json", "status.json", "run.log", "._*", "**/__pycache__/**"],
        "artifacts": artifacts,
    }


def solution_hash(solution: Solution | Mapping[str, Any]) -> str:
    return canonical_sha(asdict(solution) if isinstance(solution, Solution) else solution)


def route_structure(solution: Mapping[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "vehicle_type": row["vehicle_type"],
                "home_depot_id": row["home_depot_id"],
                "node_sequence": row["node_sequence"],
            }
            for row in solution.get("routes", [])
        ],
        key=lambda row: (row["home_depot_id"], row["vehicle_type"], row["node_sequence"]),
    )


def charging_structure(solution: Mapping[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        [dict(row) for row in solution.get("charging_actions", [])],
        key=lambda row: (
            row.get("station_id", ""), row.get("charge_day_offset", 0),
            row.get("charge_start_second", 0), row.get("vehicle_id", ""),
        ),
    )


def percent(delta: float, baseline: float) -> float | None:
    return None if abs(float(baseline)) <= TOL else 100.0 * float(delta) / float(baseline)


def prepare(output: Path) -> None:
    if output.exists():
        raise RuntimeError(f"refusing to overwrite existing SCOUT3 directory {output}")
    output.mkdir(parents=True)
    for path in ARMS.values():
        path.mkdir()
    hashes = source_hashes()
    inputs = input_hashes()
    with (AUTHORITY / "fleet_caps.csv").open(newline="", encoding="utf-8-sig") as handle:
        selected = [row for row in csv.DictReader(handle) if row["instance_id"] == INSTANCE_ID]
    prereg = {
        "schema": "resetp.scout3.preregistration.v1",
        "task_id": TASK_ID,
        "formal_result": False,
        "registered_at": now(),
        "instance_id": INSTANCE_ID,
        "seeds": list(SEEDS),
        "budget_authority": "V7_FIXED_25000_ITERATIONS_PER_VIEW",
        "iterations_per_view": ITERATIONS_PER_VIEW,
        "views": list(VIEWS),
        "no_improvement_stop": None,
        "prohibited_old_budget": {"iterations": 2000, "no_improvement": 150, "used": False},
        "arms": {
            "fleet": {"levels_percent": list(LEVELS), "paired_arms": ["COST_ONLY", "COST_PLUS_CARBON"]},
            "dynamic": {
                "policies": list(DYNAMIC_POLICIES),
                "arms": ["carbon_aware", "carbon_blind"],
                "current_code_q_bar_orders": 8,
                "current_code_delta_t_seconds": 10800,
                "paper_trigger_kg": 500,
                "paper_example_trigger_seconds": 60,
                "parameter_delay_seconds": 10740,
                "parameter_delay_minutes": 179,
            },
            "nonlinear": {"curves": [L100_CONTROL.curve_id, NL90_MILD.curve_id], "nl90_breakpoint_soc": 0.9, "reported_exposure_soc": 0.85},
        },
        "model_config": MODEL_CONFIG.as_metadata(),
        "multitrip_enabled": True,
        "fixed_cost_cny": FIXED_COST_CNY,
        "fixed_cost_basis": "unique physical_vehicle_id",
        "depot_charging_concurrency": "unbounded",
        "fleet_authority_version": "v3_20260802",
        "fleet_authority_path": str(AUTHORITY.relative_to(REPO)),
        "fleet_authority_evidence": str(AUTHORITY_EVIDENCE.relative_to(REPO)),
        "selected_authority_rows": selected,
        "source_files_sha256": hashes,
        "source_tree_sha256": canonical_sha(hashes),
        "input_files_sha256": inputs,
        "input_tree_sha256": canonical_sha(inputs),
        "git_commit": git("rev-parse", "HEAD"),
        "git_branch": git("branch", "--show-current"),
        "protected_files_not_modified": [
            "docs/paper_submission_final/RETIRED_paper_main.tex",
            "solver/src/setp_solver/check.py",
            "solver/src/setp_solver/search/evaluation.py",
        ],
        "no_rescue": {"change_seed": False, "change_instance": False, "increase_budget": False},
    }
    write_json(output / "preregistration.json", prereg)
    write_json(
        output / "metadata.json",
        {
            "schema": "resetp.scout3.metadata.v1",
            "task_id": TASK_ID,
            "status": "SCOUT3_PREPARED",
            "formal_result": False,
            "started_at": now(),
            "preregistration_sha256": file_sha(output / "preregistration.json"),
            **{key: prereg[key] for key in ("instance_id", "git_commit", "git_branch", "source_files_sha256", "source_tree_sha256", "input_files_sha256", "input_tree_sha256", "model_config", "fixed_cost_cny", "fixed_cost_basis", "depot_charging_concurrency", "fleet_authority_version", "fleet_authority_path")},
        },
    )
    write_json(output / "progress.json", {"status": "SCOUT3_PREPARED", "completed_arms": [], "updated_at": now()})


def prepare_retry(output: Path) -> None:
    """Prepare a clean retry while retaining an archived technical attempt."""

    allowed = {"attempt_01_technical_halt"}
    observed = {path.name for path in output.iterdir()} if output.exists() else set()
    if not output.exists() or not observed or not observed.issubset(allowed):
        raise RuntimeError(
            "retry preparation requires only the retained attempt_01_technical_halt archive; "
            f"observed={sorted(observed)}"
        )
    output.mkdir(parents=True, exist_ok=True)
    for path in ARMS.values():
        if path.exists():
            raise RuntimeError(f"refusing to overwrite retry arm {path}")
        path.mkdir()
    hashes = source_hashes()
    inputs = input_hashes()
    archived_decision = output / "attempt_01_technical_halt" / "decision.json"
    with (AUTHORITY / "fleet_caps.csv").open(newline="", encoding="utf-8-sig") as handle:
        selected = [row for row in csv.DictReader(handle) if row["instance_id"] == INSTANCE_ID]
    prereg = {
        "schema": "resetp.scout3.preregistration.v1",
        "task_id": TASK_ID,
        "attempt": 2,
        "formal_result": False,
        "registered_at": now(),
        "retry_reason": "attempt 1 consumed zero search units because managed macOS denied ProcessPoolExecutor SC_SEM_NSEMS_MAX sysconf",
        "retry_change_only": "execution backend ProcessPoolExecutor -> explicit subprocess pool",
        "attempt_01_decision_sha256": file_sha(archived_decision),
        "instance_id": INSTANCE_ID,
        "seeds": list(SEEDS),
        "budget_authority": "V7_FIXED_25000_ITERATIONS_PER_VIEW",
        "iterations_per_view": ITERATIONS_PER_VIEW,
        "views": list(VIEWS),
        "no_improvement_stop": None,
        "prohibited_old_budget": {"iterations": 2000, "no_improvement": 150, "used": False},
        "worker_backend": "explicit_subprocess_pool_without_posix_semaphore_api",
        "arms": {
            "fleet": {"levels_percent": list(LEVELS), "paired_arms": ["COST_ONLY", "COST_PLUS_CARBON"]},
            "dynamic": {"policies": list(DYNAMIC_POLICIES), "arms": ["carbon_aware", "carbon_blind"], "current_code_q_bar_orders": 8, "current_code_delta_t_seconds": 10800, "paper_trigger_kg": 500, "paper_example_trigger_seconds": 60, "parameter_delay_seconds": 10740, "parameter_delay_minutes": 179},
            "nonlinear": {"curves": [L100_CONTROL.curve_id, NL90_MILD.curve_id], "nl90_breakpoint_soc": 0.9, "reported_exposure_soc": 0.85},
        },
        "model_config": MODEL_CONFIG.as_metadata(),
        "multitrip_enabled": True,
        "fixed_cost_cny": FIXED_COST_CNY,
        "fixed_cost_basis": "unique physical_vehicle_id",
        "depot_charging_concurrency": "unbounded",
        "fleet_authority_version": "v3_20260802",
        "fleet_authority_path": str(AUTHORITY.relative_to(REPO)),
        "fleet_authority_evidence": str(AUTHORITY_EVIDENCE.relative_to(REPO)),
        "selected_authority_rows": selected,
        "source_files_sha256": hashes,
        "source_tree_sha256": canonical_sha(hashes),
        "input_files_sha256": inputs,
        "input_tree_sha256": canonical_sha(inputs),
        "git_commit": git("rev-parse", "HEAD"),
        "git_branch": git("branch", "--show-current"),
        "protected_files_not_modified": ["docs/paper_submission_final/RETIRED_paper_main.tex", "solver/src/setp_solver/check.py", "solver/src/setp_solver/search/evaluation.py"],
        "no_rescue": {"change_seed": False, "change_instance": False, "increase_budget": False},
    }
    write_json(output / "preregistration.json", prereg)
    write_json(output / "metadata.json", {
        "schema": "resetp.scout3.metadata.v1", "task_id": TASK_ID,
        "attempt": 2, "status": "SCOUT3_PREPARED", "formal_result": False,
        "started_at": now(), "preregistration_sha256": file_sha(output / "preregistration.json"),
        **{key: prereg[key] for key in ("instance_id", "git_commit", "git_branch", "source_files_sha256", "source_tree_sha256", "input_files_sha256", "input_tree_sha256", "model_config", "fixed_cost_cny", "fixed_cost_basis", "depot_charging_concurrency", "fleet_authority_version", "fleet_authority_path", "worker_backend")},
    })
    write_json(output / "progress.json", {"status": "SCOUT3_PREPARED", "attempt": 2, "completed_arms": [], "updated_at": now()})


def run_subprocess_pool(
    jobs: Sequence[tuple[list[str], Path, Mapping[str, Any]]],
    *,
    workers: int,
    on_complete: Any,
) -> list[dict[str, Any]]:
    """Run independent commands without multiprocessing semaphore APIs."""

    pending = list(jobs)
    running: dict[int, tuple[subprocess.Popen[Any], Any, Path, Mapping[str, Any]]] = {}
    failures: list[dict[str, Any]] = []
    while pending or running:
        while pending and len(running) < max(1, int(workers)):
            command, log_path, label = pending.pop(0)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handle = log_path.open("wb")
            process = subprocess.Popen(command, cwd=REPO, stdout=handle, stderr=subprocess.STDOUT)
            running[process.pid] = (process, handle, log_path, label)
        progressed = False
        for pid, (process, handle, log_path, label) in list(running.items()):
            return_code = process.poll()
            if return_code is None:
                continue
            progressed = True
            handle.close()
            running.pop(pid)
            if return_code != 0:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-8000:]
                failures.append({**dict(label), "return_code": return_code, "log": str(log_path), "log_tail": tail})
            on_complete(label, return_code)
        if not progressed and running:
            time.sleep(0.25)
    return failures


def _configure_fleet() -> Any:
    import baselines.china_e3_e7.run_formal_fleet_levels_xb_20260802 as old

    old.INSTANCE_ID = INSTANCE_ID
    old.MAX_ITERATIONS = ITERATIONS_PER_VIEW
    old.MAX_NO_IMPROVEMENT = ITERATIONS_PER_VIEW
    original_authority_rows = old.authority_rows
    original_allocations = old.allocations_by_level
    old.authority_rows = lambda instance_id=INSTANCE_ID: original_authority_rows(instance_id)
    old.allocations_by_level = lambda instance_id=INSTANCE_ID: original_allocations(instance_id)

    class IterationOnlyPatch:
        def __init__(self, ignored: int) -> None:
            self.original_builder: Any = None

        def __enter__(self) -> "IterationOnlyPatch":
            self.original_builder = old.route_pool_sp.build_pyvrp_problem

            def builder(bundle: Any, *, route_proxy_mode: str = "mechanism_ev", hard_home_depot_lock: bool = False) -> Any:
                return old.pyvrp_adapter.build_pyvrp_problem(
                    old._proxy_only_positive_type_caps(bundle),
                    route_proxy_mode=route_proxy_mode,
                    hard_home_depot_lock=hard_home_depot_lock,
                )

            old.route_pool_sp.build_pyvrp_problem = builder
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            old.route_pool_sp.build_pyvrp_problem = self.original_builder

    old._HgsContractPatch = IterationOnlyPatch
    old.infer_stop_reason = lambda observed, maximum, ignored: (
        "MAX_ITERATIONS" if int(observed) == int(maximum) else "UNEXPECTED_EARLY_STOP"
    )
    return old


def fleet_worker(task: tuple[int, int, dict[str, str]]) -> dict[str, Any]:
    level, seed, expected = task
    old = _configure_fleet()
    # The reused unit has its own narrower lock; the SCOUT3 parent separately
    # verifies the superset lock (including this wrapper and dynamic sources).
    _ = expected
    return old.run_unit(
        level,
        seed,
        old.source_hashes(),
        ITERATIONS_PER_VIEW,
        ITERATIONS_PER_VIEW,
    )


def _enrich_fleet_row(result: dict[str, Any]) -> dict[str, Any]:
    row = dict(result["row"])
    payload = result["payload"]
    for arm, prefix in (("COST_PLUS_CARBON", "aware"), ("COST_ONLY", "blind")):
        value = payload.get("arms", {}).get(arm)
        if not value:
            continue
        stats = value["search_stats"]
        row[f"{prefix}_complete_candidate_evaluation_attempts"] = int(stats["complete_candidate_evaluation_attempts"])
        row[f"{prefix}_objective_float_hex"] = float(value["objective"]).hex()
        row[f"{prefix}_route_structure_sha256"] = canonical_sha(route_structure(value["solution"]))
        row[f"{prefix}_charging_structure_sha256"] = canonical_sha(charging_structure(value["solution"]))
        row[f"{prefix}_iterations_exact_25000_all_views"] = all(int(v) == ITERATIONS_PER_VIEW for v in value["hgs_iterations_by_view"].values())
    return row


def run_fleet(root: Path, workers: int, expected: dict[str, str]) -> None:
    arm = ARMS["fleet"]
    started = time.perf_counter()
    specs = [(level, seed, expected) for level in LEVELS for seed in SEEDS]
    results: list[dict[str, Any]] = []
    receipts = arm / "worker_receipts"
    jobs = []
    for level, seed, _ in specs:
        receipt = receipts / f"level_{level:03d}__seed_{seed:02d}.json"
        command = [sys.executable, str(RUNNER), "worker-fleet", "--level", str(level), "--seed", str(seed), "--receipt", str(receipt)]
        jobs.append((command, arm / "worker_logs" / f"level_{level:03d}__seed_{seed:02d}.log", {"level": level, "seed": seed, "receipt": str(receipt)}))

    def completed(label: Mapping[str, Any], return_code: int) -> None:
        if return_code == 0:
            receipt = Path(str(label["receipt"]))
            result = json.loads(receipt.read_text(encoding="utf-8"))
            results.append(result)
            row = result["row"]
            path = arm / "solutions" / f"level_{int(row['fleet_level_percent']):03d}" / f"seed_{int(row['seed']):02d}.json"
            if path.exists():
                raise RuntimeError(f"refusing to overwrite fleet unit {path}")
            write_json(path, result["payload"])
        write_json(root / "progress.json", {"status": "SCOUT3_RUNNING_FLEET", "completed_fleet_units": len(results), "expected_fleet_units": len(specs), "updated_at": now()})

    process_failures = run_subprocess_pool(jobs, workers=workers, on_complete=completed)
    if process_failures:
        write_json(arm / "worker_failures.json", process_failures)
        raise RuntimeError(f"{len(process_failures)} fleet subprocess workers failed")
    rows = sorted((_enrich_fleet_row(item) for item in results), key=lambda row: (int(row["fleet_level_percent"]), int(row["seed"])))
    write_csv(arm / "raw_runs.csv", rows)
    passed = [row for row in rows if row["status"] == "PASS"]
    technical = [row for row in rows if row["status"] == "TECHNICAL_ERROR"]
    summaries: list[dict[str, Any]] = []
    for level in LEVELS:
        group = [row for row in passed if int(row["fleet_level_percent"]) == level]
        summaries.append({
            "fleet_level_percent": level,
            "run_count": len(group),
            "available_cv": group[0]["available_cv"] if group else None,
            "available_ev": group[0]["available_ev"] if group else None,
            **{
                f"mean_{field}": (sum(float(row[field]) for row in group) / len(group) if group else None)
                for field in (
                    "aware_dispatched_cv", "aware_dispatched_ev", "aware_used_physical_vehicles",
                    "aware_route_count", "aware_full_model_cost_cny", "aware_system_emissions_kg",
                    "emissions_difference_vs_blind_kg", "charging_timing_change_count",
                    "vehicle_type_change_customer_count", "route_change_customer_count",
                )
            },
            "complete_evaluation_attempts": sum(int(row.get("aware_complete_candidate_evaluation_attempts", 0)) + int(row.get("blind_complete_candidate_evaluation_attempts", 0)) for row in group),
            "all_views_exact_25000": bool(group) and all(row.get("aware_iterations_exact_25000_all_views") and row.get("blind_iterations_exact_25000_all_views") for row in group),
        })
    write_csv(arm / "level_summary.csv", summaries)
    metrics = ("mean_aware_full_model_cost_cny", "mean_aware_system_emissions_kg", "mean_aware_used_physical_vehicles", "mean_aware_route_count")
    gaps: list[dict[str, Any]] = []
    for metric in metrics:
        valid = [row for row in summaries if row[metric] is not None]
        for left in valid:
            for right in valid:
                if int(left["fleet_level_percent"]) >= int(right["fleet_level_percent"]):
                    continue
                delta = float(right[metric]) - float(left[metric])
                gaps.append({"metric": metric, "left_level": left["fleet_level_percent"], "right_level": right["fleet_level_percent"], "difference": delta, "relative_percent_vs_left": percent(delta, float(left[metric]))})
    max_gap = max(gaps, key=lambda row: abs(float(row["difference"])), default=None)
    changed_layers = []
    charging_across_levels = any(
        len({row.get("aware_charging_structure_sha256") for row in passed if int(row["seed"]) == seed}) > 1
        for seed in SEEDS
    )
    type_across_levels = any(
        len({(row.get("aware_dispatched_cv"), row.get("aware_dispatched_ev")) for row in passed if int(row["seed"]) == seed}) > 1
        for seed in SEEDS
    )
    route_across_levels = any(
        len({row.get("aware_route_structure_sha256") for row in passed if int(row["seed"]) == seed}) > 1
        for seed in SEEDS
    )
    if charging_across_levels or any(abs(float(row.get("charging_timing_change_count") or 0)) > 0 for row in passed):
        changed_layers.append("charging")
    if type_across_levels or any(abs(float(row.get("vehicle_type_change_customer_count") or 0)) > 0 for row in passed):
        changed_layers.append("vehicle_type")
    if route_across_levels or any(abs(float(row.get("route_change_customer_count") or 0)) > 0 for row in passed):
        changed_layers.append("route")
    effect = bool(max_gap and abs(float(max_gap["difference"])) > TOL) or bool(changed_layers)
    status = "HALT_TECHNICAL" if technical or len(rows) != 50 else ("MEASURABLE_EFFECT" if effect else "NO_MEASURABLE_EFFECT")
    decision = {
        "schema": "resetp.scout3.fleet.decision.v1", "task_id": TASK_ID, "status": status,
        "formal_result": False, "question": "混合车队机制是否产生可测效应？",
        "answer": None if status.startswith("HALT") else ("有效应" if effect else "无效应"),
        "observed_units": len(rows), "expected_units": 50, "pass_units": len(passed),
        "technical_error_units": len(technical), "maximum_level_gap": max_gap,
        "effect_layers": changed_layers, "iterations_per_view": ITERATIONS_PER_VIEW,
        "no_improvement_stop": None, "complete_evaluation_attempts": sum(int(row.get("aware_complete_candidate_evaluation_attempts", 0)) + int(row.get("blind_complete_candidate_evaluation_attempts", 0)) for row in rows),
        "all_objective_float_hex": {row["unit_id"]: {"aware": row.get("aware_objective_float_hex"), "blind": row.get("blind_objective_float_hex")} for row in rows},
        "all_solution_structure_sha256": {row["unit_id"]: {"aware_route": row.get("aware_route_structure_sha256"), "blind_route": row.get("blind_route_structure_sha256"), "aware_charging": row.get("aware_charging_structure_sha256"), "blind_charging": row.get("blind_charging_structure_sha256")} for row in rows},
        "elapsed_seconds": time.perf_counter() - started,
    }
    write_json(arm / "decision.json", decision)
    write_json(arm / "metadata.json", arm_metadata("fleet", status, expected, len(list((arm / "solutions").rglob("seed_*.json"))), decision["elapsed_seconds"]))
    report = ["# SCOUT3-A 混合车队效应探路", "", f"终态：`{status}`；`formal_result=false`。", "", "## FACT", "", "算例固定为 `%s`，五档 0/25/50/75/100%%，每档 10 种子；每个碳盲/碳感知搜索均为三个视角各 25000 次迭代，无无改善早停。" % INSTANCE_ID, ""]
    if status.startswith("HALT"):
        report += [f"技术 HALT：{len(technical)} 个单元发生技术错误；全部证据已保留。", ""]
    elif effect:
        report += [f"## INFERENCE", "", f"结论：有效应。最大档间差为 `{max_gap}`；观测到的响应层为 `{changed_layers}`。", ""]
    else:
        report += ["## INFERENCE", "", f"结论：无效应。50 个配对单元的逐位目标、完整评价数和解结构哈希见 `decision.json`；实际总完整评价次数为 {decision['complete_evaluation_attempts']}。", ""]
    report += ["## DECISION", "", "本组只回答效应是否可测，不升级为正式论文结果，也不选择论文保留机制数。", ""]
    write_text(arm / "report.md", "\n".join(report))
    write_json(arm / "artifact_hashes.json", artifact_hashes(arm))
    write_json(arm / "done.json", {"status": status, "completed_at": now(), "decision_sha256": file_sha(arm / "decision.json"), "artifact_hashes_sha256": file_sha(arm / "artifact_hashes.json")})


def _configure_dynamic(output: Path) -> Any:
    import baselines.china_e3_e7.formal_dynamic_dispatch_20260802_runner as old
    import route_pool_sp
    from setp_solver.search.dynamic import DynamicEvent, RollingParameters, _build_trigger_batches

    old.INSTANCE_ID = INSTANCE_ID
    old.OUTPUT_DIR = output
    old.MAX_GENERATIONS = ITERATIONS_PER_VIEW
    old.PER_ORDER = PER_ORDER
    old.FIXED_30_MINUTES = FIXED_10800
    old.HYBRID_500KG_OR_30_MINUTES = HYBRID_8_OR_10800
    old.POLICIES = DYNAMIC_POLICIES
    old.POLICY_LABELS = DYNAMIC_LABELS
    old.INTERVAL_SECONDS = 10_800.0
    old.DEMAND_THRESHOLD_KG = 8.0

    def batches(events: Sequence[Any], policy: str) -> tuple[Any, ...]:
        ordered = sorted(events, key=lambda item: (item.appearance_second, item.event_id))
        if policy == PER_ORDER:
            return tuple(old._batch(policy, index, event.appearance_second, "new_information", [event]) for index, event in enumerate(ordered, start=1))
        if policy == FIXED_10800:
            result: list[Any] = []
            pending: list[Any] = []
            cursor = 0
            trigger = CHINA81_HORIZON_START_SECOND + 10_800.0
            while trigger <= CHINA81_HORIZON_END_SECOND:
                while cursor < len(ordered) and ordered[cursor].appearance_second <= trigger:
                    pending.append(ordered[cursor]); cursor += 1
                if pending:
                    result.append(old._batch(policy, len(result) + 1, trigger, "delta_t", pending)); pending = []
                trigger += 10_800.0
            if pending:
                result.append(old._batch(policy, len(result) + 1, CHINA81_HORIZON_END_SECOND, "window_end", pending))
            return tuple(result)
        if policy != HYBRID_8_OR_10800:
            raise ValueError(policy)
        converted = [DynamicEvent(event_id=str(event.event_id), event_type="add", t_appear=float(event.appearance_second), customer_id=str(event.customer_id), old_demand=0.0, new_demand=float(event.demand_kg), seed=0) for event in ordered]
        by_id = {str(event.event_id): event for event in ordered}
        current = _build_trigger_batches(converted, RollingParameters(delta_t_seconds=10_800.0, q_bar=8))
        result = []
        for row in current:
            if not row["events"]:
                continue
            original = [by_id[str(event.event_id)] for event in row["events"]]
            result.append(old._batch(policy, len(result) + 1, float(row["trigger_time"]), str(row["trigger_reason"]), original))
        return tuple(result)

    def hgs(bundle: Any, warm_start: Solution, *, seed: int) -> tuple[list[Solution], dict[str, Any]]:
        started = time.perf_counter()
        run = route_pool_sp.run_hgs_route_pool_recombination(
            bundle, warm_start, seed=int(seed), hgs_seconds_per_view=None,
            exact_elites_per_view=EXACT_ELITES_PER_VIEW,
            max_archive_candidates_per_view=ARCHIVE_PER_VIEW,
            sp_time_limit_seconds=SP_SECONDS, hard_home_depot_lock=False,
            max_hgs_iterations_per_view=ITERATIONS_PER_VIEW,
            max_no_improvement_iterations_per_view=None,
            wallclock_safety_seconds_per_view=WALLCLOCK_SAFETY_SECONDS_PER_VIEW,
            exact_checkpoint_interval_iterations=None,
            preserve_base_pool_recombination=False,
        )
        candidates = [run.completion.solution]
        for epoch in run.view_epochs.values():
            candidates.extend(item.solution for item in epoch.elite_completions)
        unique: dict[str, Solution] = {}
        for candidate in candidates:
            unique.setdefault(solution_hash(candidate), candidate)
        iterations = {view: int(epoch.stats["hgs_iterations"]) for view, epoch in run.view_epochs.items()}
        if run.stats.get("wallclock_safety_triggered") or any(value != ITERATIONS_PER_VIEW for value in iterations.values()):
            raise RuntimeError(f"dynamic MV-HGS-SP did not consume 25000 iterations in every view: {iterations}")
        return list(unique.values()), {
            "engine": "MV-HGS-SP", "search_seed": int(seed), "views": list(VIEWS),
            "iterations_by_view": iterations, "stop_rule": "MaxIterations(25000)_only",
            "secondary_stop_rule": None, "complete_candidate_evaluation_attempts": int(run.stats["complete_candidate_evaluation_attempts"]),
            "terminal_exact_rerank_count": len(unique), "wall_seconds": time.perf_counter() - started,
        }

    old._build_batches = batches
    old._hgs_skeletons = hgs
    return old


def dynamic_worker(task: tuple[str, int, str]) -> str:
    output = Path(task[2]).parents[1]
    old = _configure_dynamic(output)
    return old._run_scenario(task)


def _dynamic_effect(scenarios: Sequence[Mapping[str, Any]]) -> tuple[bool, dict[str, Any], list[str]]:
    stage = [row for scenario in scenarios for row in scenario["stage_rows"]]
    paired = [row for scenario in scenarios for row in scenario["paired_rows"]]
    stage_map = {(row.get("policy"), int(row.get("stream_seed", 0)), int(row.get("stage", 0)), row.get("arm")): row for row in stage if row.get("status") == "PASS_COMPLETE_OPTIMIZATION"}
    comparisons: list[dict[str, Any]] = []
    for row in paired:
        key = (row["policy"], int(row["stream_seed"]), int(row["stage"]))
        blind = stage_map.get((*key, "carbon_blind"), {})
        for metric, baseline_field in (("aware_minus_blind_cost_cny", "total_cost_cny"), ("aware_minus_blind_emissions_kg", "total_emissions_kg")):
            delta = float(row[metric])
            baseline = float(blind.get(baseline_field, 0.0) or 0.0)
            comparisons.append({"policy": key[0], "seed": key[1], "stage": key[2], "metric": metric, "difference": delta, "relative_percent_vs_blind": percent(delta, baseline)})
    maximum = max(comparisons, key=lambda row: abs(row["difference"]), default={})
    layers = []
    if any(abs(float(row.get("aware_minus_blind_charging_action_changes", 0))) > 0 for row in paired) or any(int(row.get("charging_action_change_count", 0) or 0) > 0 for row in stage):
        layers.append("charging")
    if any(abs(float(row.get("aware_minus_blind_vehicle_type_customer_changes", 0))) > 0 for row in paired) or any(int(row.get("vehicle_type_customer_change_count", 0) or 0) > 0 for row in stage):
        layers.append("vehicle_type")
    if any(abs(float(row.get("aware_minus_blind_route_arc_changes", 0))) > 0 for row in paired) or any(int(row.get("route_arc_change_count", 0) or 0) > 0 for row in stage):
        layers.append("route")
    effect = any(abs(float(row["difference"])) > TOL for row in comparisons) or bool(layers)
    return effect, maximum, layers


def run_dynamic(root: Path, workers: int, expected: dict[str, str]) -> None:
    arm = ARMS["dynamic"]
    started = time.perf_counter()
    scenarios_root = arm / "scenarios"
    scenarios_root.mkdir()
    tasks = [(policy, seed, str(scenarios_root / f"{policy}__seed{seed:02d}")) for policy in DYNAMIC_POLICIES for seed in SEEDS]
    paths: list[Path] = []
    failures: list[dict[str, Any]] = []
    jobs = []
    for policy, seed, output_text in tasks:
        command = [sys.executable, str(RUNNER), "worker-dynamic", "--policy", policy, "--seed", str(seed), "--scenario-output", output_text]
        jobs.append((command, arm / "worker_logs" / f"{policy}__seed{seed:02d}.log", {"policy": policy, "seed": seed, "result": str(Path(output_text) / "scenario_result.json")}))

    def completed(label: Mapping[str, Any], return_code: int) -> None:
        if return_code == 0:
            paths.append(Path(str(label["result"])))
        write_json(root / "progress.json", {"status": "SCOUT3_RUNNING_DYNAMIC", "completed_dynamic_scenarios": len(paths), "failed_dynamic_scenarios": len(failures), "expected_dynamic_scenarios": len(tasks), "updated_at": now()})

    failures.extend(run_subprocess_pool(jobs, workers=workers, on_complete=completed))
    scenarios = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(paths)]
    arm_rows = [row for item in scenarios for row in item["arm_summaries"]]
    stage_rows = [row for item in scenarios for row in item["stage_rows"]]
    event_rows = [row for item in scenarios for row in item["event_rows"]]
    paired_rows = [row for item in scenarios for row in item["paired_rows"]]
    write_csv(arm / "raw_runs.csv", arm_rows)
    write_csv(arm / "stage_runs.csv", stage_rows)
    write_csv(arm / "event_state_table.csv", event_rows)
    write_csv(arm / "paired_differences.csv", paired_rows)
    technical = bool(failures) or len(scenarios) != 30
    effect, maximum, layers = _dynamic_effect(scenarios)
    statuses = Counter(str(item["status"]) for item in scenarios)
    # A proved HARD_INFEASIBLE necessary condition is a retained mechanism
    # outcome, not a technical runner failure. SEARCH_NOT_FOUND is indeterminate.
    if statuses.get("SEARCH_NOT_FOUND", 0):
        technical = True
    hard_by_policy = {
        policy: sum(
            item["status"] == "HARD_INFEASIBLE"
            for item in scenarios
            if item["policy"] == policy
        )
        for policy in DYNAMIC_POLICIES
    }
    if len(set(hard_by_policy.values())) > 1 or any(hard_by_policy.values()):
        effect = True
        if "route_service_feasibility" not in layers:
            layers.append("route_service_feasibility")
    status = "HALT_TECHNICAL" if technical else ("MEASURABLE_EFFECT" if effect else "NO_MEASURABLE_EFFECT")
    saved_solutions = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(scenarios_root.rglob("*.json"))
        if "solutions" in path.parts
    ]
    all_hgs = [dict(item.get("hgs", {})) for item in saved_solutions if item.get("hgs")]
    evaluations = sum(int(row.get("complete_candidate_evaluation_attempts", 0)) for row in all_hgs)
    exact_budget = bool(all_hgs) and all(
        row.get("iterations_by_view") == {view: ITERATIONS_PER_VIEW for view in VIEWS}
        for row in all_hgs
    )
    decision = {
        "schema": "resetp.scout3.dynamic.decision.v1", "task_id": TASK_ID, "status": status,
        "formal_result": False, "question": "动态需求机制是否产生可测效应？",
        "answer": None if status.startswith("HALT") else ("有效应" if effect else "无效应"),
        "scenario_count": len(scenarios), "expected_scenario_count": 30,
        "scenario_status_counts": dict(statuses), "worker_failures": failures,
        "hard_infeasible_count_by_policy": hard_by_policy,
        "maximum_paired_difference": maximum, "effect_layers": layers,
        "iterations_per_view": ITERATIONS_PER_VIEW, "no_improvement_stop": None,
        "complete_evaluation_attempts": evaluations,
        "all_searches_exact_25000_each_view": exact_budget,
        "all_stage_objective_float_hex": {
            f"{row['policy']}__seed{int(row['stream_seed']):02d}__stage{int(row['stage']):03d}__{row['arm']}": {
                "cost": float(row["total_cost_cny"]).hex(),
                "emissions": float(row["total_emissions_kg"]).hex(),
                "solution_sha256": row["solution_sha256"],
            }
            for row in stage_rows
            if row.get("status") == "PASS_COMPLETE_OPTIMIZATION"
        },
        "trigger_contract": {"code_q_bar_orders": 8, "code_delta_t_seconds": 10800, "paper_eq_trigger_kg": 500, "paper_example_trigger_seconds": 60, "threshold_delay_seconds": 10740, "threshold_delay_minutes": 179},
        "actual_first_hybrid_trigger_seconds_by_seed": {str(item["stream_seed"]): min((float(row["trigger_second"]) for row in item["stage_rows"] if row.get("arm") == "carbon_aware" and row.get("stage") is not None), default=None) for item in scenarios if item["policy"] == HYBRID_8_OR_10800},
        "elapsed_seconds": time.perf_counter() - started,
    }
    write_json(arm / "decision.json", decision)
    solution_count = len([path for path in arm.rglob("*.json") if "solutions" in path.parts])
    write_json(arm / "metadata.json", arm_metadata("dynamic", status, expected, solution_count, decision["elapsed_seconds"]))
    report = ["# SCOUT3-B 动态需求效应探路", "", f"终态：`{status}`；`formal_result=false`。", "", "## FACT", "", f"同一 `{INSTANCE_ID}`、10 个流种子比较逐单触发、每 10800 秒触发、以及当前代码的 8 单或 10800 秒混合触发；每次碳感知/碳盲优化均为三个视角各 25000 次迭代，无无改善早停。", "", "代码合同与论文不一致：`dynamic.py` 为 `q_bar=8`、`delta_t=10800 s`，论文 `eq:trigger` 写累计 500 kg。论文同例 60 s 触发与代码时间阈值 10800 s 相差 10740 s，即 179 分钟；本轮按代码而非论文运行。", ""]
    if status.startswith("HALT"):
        report += ["## HALT", "", f"30 个场景中完成 {len(scenarios)} 个；状态计数 `{dict(statuses)}`，worker 技术错误 {len(failures)} 个。证据均保留，未换种子或救援调参。", ""]
    elif effect:
        report += ["## INFERENCE", "", f"结论：有效应。最大碳感知减碳盲配对差为 `{maximum}`；效应层为 `{layers}`。", ""]
    else:
        report += ["## INFERENCE", "", f"结论：无效应。各臂逐位目标与完整解保存在场景 solution JSON；总完整评价次数为 {evaluations}，结构比较见 `paired_differences.csv`。", ""]
    report += ["## DECISION", "", "该探路不修订论文触发公式，也不把代码合同结果升级为正式结果。", ""]
    write_text(arm / "report.md", "\n".join(report))
    write_json(arm / "artifact_hashes.json", artifact_hashes(arm))
    write_json(arm / "done.json", {"status": status, "completed_at": now(), "decision_sha256": file_sha(arm / "decision.json"), "artifact_hashes_sha256": file_sha(arm / "artifact_hashes.json")})


def _curve_bundle(curve: Any) -> Any:
    base = load_china81_bundle(REPO, INSTANCE_ID, fleet_authority=AUTHORITY, model_config=MODEL_CONFIG)
    prices = replace(base.prices, charging_curve_id=curve.curve_id, charging_soc_breakpoints=curve.soc_breakpoints, charging_relative_powers=curve.relative_powers)
    return replace(base, prices=prices, formal_search_allowed=True)


def _level25_initial() -> Solution:
    payload = json.loads((AUTHORITY / "witnesses" / f"{INSTANCE_ID}.json").read_text(encoding="utf-8"))
    routes: list[Route] = []
    for depot, values in sorted(payload["levels"]["25"]["depots"].items()):
        for vehicle_type in ("cv", "ev"):
            for row in values[f"{vehicle_type}_routes"]:
                routes.append(Route(vehicle_id=f"SCOUT3-C-INIT-{len(routes)+1:03d}", vehicle_type=vehicle_type, home_depot_id=depot, node_sequence=[depot, *row["customers"], depot]))
    return Solution(routes=routes)


def nonlinear_worker(task: tuple[int, str]) -> dict[str, Any]:
    seed, curve_id = task
    import route_pool_sp
    curve = {L100_CONTROL.curve_id: L100_CONTROL, NL90_MILD.curve_id: NL90_MILD}[curve_id]
    bundle = _curve_bundle(curve)
    started = time.perf_counter()
    with model_config_scope(MODEL_CONFIG):
        run = route_pool_sp.run_hgs_route_pool_recombination(
            bundle, _level25_initial(), seed=int(seed), hgs_seconds_per_view=None,
            exact_elites_per_view=EXACT_ELITES_PER_VIEW, max_archive_candidates_per_view=ARCHIVE_PER_VIEW,
            sp_time_limit_seconds=SP_SECONDS, hard_home_depot_lock=False,
            max_hgs_iterations_per_view=ITERATIONS_PER_VIEW,
            max_no_improvement_iterations_per_view=None,
            wallclock_safety_seconds_per_view=WALLCLOCK_SAFETY_SECONDS_PER_VIEW,
            exact_checkpoint_interval_iterations=None, preserve_base_pool_recombination=False,
        )
        prepared, certificate = prepare_multitrip_solution(run.solution, bundle.instance, bundle.prices)
        objective, breakdown, violations = exact_china81_score(prepared, bundle)
    iterations = {view: int(epoch.stats["hgs_iterations"]) for view, epoch in run.view_epochs.items()}
    if violations:
        raise RuntimeError(f"nonlinear final violations: {violations[:3]}")
    if run.stats.get("wallclock_safety_triggered") or any(value != ITERATIONS_PER_VIEW for value in iterations.values()):
        raise RuntimeError(f"nonlinear MV-HGS-SP did not consume 25000 iterations in every view: {iterations}")
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    capacity = bundle.instance.battery_capacity_kwh(fallback=bundle.prices.B_battery_kwh)
    public = [action for action in prepared.charging_actions if nodes[action.station_id].node_type.lower() == "f"]
    over85 = [action for action in public if action.end_energy_kwh is not None and float(action.end_energy_kwh) > 0.85 * capacity + TOL]
    cross85 = [action for action in public if action.start_energy_kwh is not None and action.end_energy_kwh is not None and float(action.start_energy_kwh) <= 0.85 * capacity + TOL < float(action.end_energy_kwh)]
    ledger = [row for row in certificate.depot_charge_ledger if row.relation == "between_solution_trips"]
    solution = asdict(prepared)
    return {
        "row": {
            "seed": seed, "curve_id": curve_id, "status": "PASS", "objective": float(objective),
            "objective_float_hex": float(objective).hex(), "total_cost_cny": float(breakdown["total_cost"]),
            "system_emissions_kg": float(breakdown["E_total"]), "public_station_charging_count": len(public),
            "public_actions_ending_above_85pct": len(over85), "public_actions_crossing_85pct": len(cross85),
            "between_trip_recharge_count": len(ledger), "between_trip_recharge_energy_kwh": sum(float(row.energy_kwh) for row in ledger),
            "route_count": len(prepared.routes), "used_physical_vehicle_count": len({physical_vehicle_id(route.vehicle_id) for route in prepared.routes}),
            "route_structure_sha256": canonical_sha(route_structure(solution)), "charging_structure_sha256": canonical_sha(charging_structure(solution)),
            "solution_sha256": solution_hash(solution), "iterations_by_view": iterations,
            "complete_candidate_evaluation_attempts": int(run.stats["complete_candidate_evaluation_attempts"]),
            "elapsed_seconds": time.perf_counter() - started,
        },
        "solution": solution, "certificate": certificate.as_dict(), "completion_activity": run.completion.activity,
        "search_stats": {key: value for key, value in run.stats.items() if key != "complete_candidate_evaluation_trace"},
    }


def run_nonlinear(root: Path, workers: int, expected: dict[str, str]) -> None:
    arm = ARMS["nonlinear"]
    started = time.perf_counter()
    tasks = [(seed, curve) for seed in SEEDS for curve in (L100_CONTROL.curve_id, NL90_MILD.curve_id)]
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    jobs = []
    for seed, curve in tasks:
        receipt = arm / "worker_receipts" / f"seed_{seed:02d}__{curve}.json"
        command = [sys.executable, str(RUNNER), "worker-nonlinear", "--seed", str(seed), "--curve", curve, "--receipt", str(receipt)]
        jobs.append((command, arm / "worker_logs" / f"seed_{seed:02d}__{curve}.log", {"seed": seed, "curve_id": curve, "receipt": str(receipt)}))

    def completed(label: Mapping[str, Any], return_code: int) -> None:
        if return_code == 0:
            item = json.loads(Path(str(label["receipt"])).read_text(encoding="utf-8"))
            results.append(item)
            path = arm / "solutions" / f"seed_{int(label['seed']):02d}" / f"{label['curve_id']}.json"
            if path.exists():
                raise RuntimeError(f"refusing to overwrite nonlinear unit {path}")
            write_json(path, item)
        write_json(root / "progress.json", {"status": "SCOUT3_RUNNING_NONLINEAR", "completed_nonlinear_units": len(results), "failed_nonlinear_units": len(failures), "expected_nonlinear_units": len(tasks), "updated_at": now()})

    failures.extend(run_subprocess_pool(jobs, workers=workers, on_complete=completed))
    rows = sorted((item["row"] for item in results), key=lambda row: (int(row["seed"]), str(row["curve_id"])))
    paired: list[dict[str, Any]] = []
    for seed in SEEDS:
        group = {row["curve_id"]: row for row in rows if int(row["seed"]) == seed}
        if set(group) != {L100_CONTROL.curve_id, NL90_MILD.curve_id}:
            continue
        linear, nonlinear = group[L100_CONTROL.curve_id], group[NL90_MILD.curve_id]
        cost_delta = float(nonlinear["total_cost_cny"]) - float(linear["total_cost_cny"])
        emission_delta = float(nonlinear["system_emissions_kg"]) - float(linear["system_emissions_kg"])
        paired.append({
            "seed": seed, "nl90_minus_linear_cost_cny": cost_delta, "cost_relative_percent_vs_linear": percent(cost_delta, float(linear["total_cost_cny"])),
            "nl90_minus_linear_emissions_kg": emission_delta, "emissions_relative_percent_vs_linear": percent(emission_delta, float(linear["system_emissions_kg"])),
            "route_changed": nonlinear["route_structure_sha256"] != linear["route_structure_sha256"],
            "charging_changed": nonlinear["charging_structure_sha256"] != linear["charging_structure_sha256"],
            "linear_objective_float_hex": linear["objective_float_hex"], "nl90_objective_float_hex": nonlinear["objective_float_hex"],
            "linear_solution_sha256": linear["solution_sha256"], "nl90_solution_sha256": nonlinear["solution_sha256"],
            "linear_complete_evaluations": linear["complete_candidate_evaluation_attempts"], "nl90_complete_evaluations": nonlinear["complete_candidate_evaluation_attempts"],
        })
    write_csv(arm / "raw_runs.csv", rows)
    write_csv(arm / "paired_differences.csv", paired)
    technical = bool(failures) or len(paired) != 10
    candidates = [
        {"seed": row["seed"], "metric": metric, "difference": row[metric], "relative_percent": row[relative]}
        for row in paired
        for metric, relative in (("nl90_minus_linear_cost_cny", "cost_relative_percent_vs_linear"), ("nl90_minus_linear_emissions_kg", "emissions_relative_percent_vs_linear"))
    ]
    maximum = max(candidates, key=lambda row: abs(float(row["difference"])), default={})
    layers = []
    if any(row["charging_changed"] for row in paired): layers.append("charging")
    if any(row["route_changed"] for row in paired): layers.append("route")
    effect = any(abs(float(row["difference"])) > TOL for row in candidates) or bool(layers)
    status = "HALT_TECHNICAL" if technical else ("MEASURABLE_EFFECT" if effect else "NO_MEASURABLE_EFFECT")
    evaluations = sum(int(row["complete_candidate_evaluation_attempts"]) for row in rows)
    decision = {
        "schema": "resetp.scout3.nonlinear.decision.v1", "task_id": TASK_ID, "status": status, "formal_result": False,
        "question": "非线性充电机制是否产生可测效应？", "answer": None if technical else ("有效应" if effect else "无效应"),
        "completed_units": len(rows), "expected_units": 20, "paired_seed_count": len(paired), "worker_failures": failures,
        "maximum_paired_difference": maximum, "effect_layers": layers, "iterations_per_view": ITERATIONS_PER_VIEW,
        "no_improvement_stop": None, "complete_evaluation_attempts": evaluations,
        "all_objectives_digitwise": {
            str(seed): {
                row["curve_id"]: row["objective_float_hex"]
                for row in rows
                if int(row["seed"]) == seed
            }
            for seed in SEEDS
        },
        "all_structure_equal": bool(paired) and all(not row["route_changed"] and not row["charging_changed"] for row in paired),
        "elapsed_seconds": time.perf_counter() - started,
    }
    write_json(arm / "decision.json", decision)
    write_json(arm / "metadata.json", arm_metadata("nonlinear", status, expected, len(rows), decision["elapsed_seconds"]))
    report = ["# SCOUT3-C 非线性充电效应探路", "", f"终态：`{status}`；`formal_result=false`。", "", "## FACT", "", f"在 `{INSTANCE_ID}` 与 v3 默认 25% 车队上，10 种子逐一配对比较 `{L100_CONTROL.curve_id}` 与 `{NL90_MILD.curve_id}`；每臂三个视角各 25000 次迭代，无无改善早停。85% 指标是用户指定的暴露诊断；NL90 的实际折点仍是 90%，没有改曲线。", ""]
    if technical:
        report += ["## HALT", "", f"完成 {len(rows)}/20 个搜索臂、{len(paired)}/10 个配对；技术错误 {len(failures)} 个。证据全部保留。", ""]
    elif effect:
        report += ["## INFERENCE", "", f"结论：有效应。最大配对差为 `{maximum}`；效应层为 `{layers}`。", ""]
    else:
        report += ["## INFERENCE", "", f"结论：无效应。20 个搜索臂逐位目标见 `decision.json`，总完整评价次数 {evaluations}；路线与充电结构均逐种子相同。", ""]
    report += ["## DECISION", "", "本组仅判断效应可测性；不因不利或零差结果改变曲线、种子、算例或预算。", ""]
    write_text(arm / "report.md", "\n".join(report))
    write_json(arm / "artifact_hashes.json", artifact_hashes(arm))
    write_json(arm / "done.json", {"status": status, "completed_at": now(), "decision_sha256": file_sha(arm / "decision.json"), "artifact_hashes_sha256": file_sha(arm / "artifact_hashes.json")})


def arm_metadata(name: str, status: str, expected: Mapping[str, str], solution_count: int, elapsed: float) -> dict[str, Any]:
    return {
        "schema": f"resetp.scout3.{name}.metadata.v1", "task_id": TASK_ID, "arm": name,
        "status": status, "formal_result": False, "completed_at": now(), "elapsed_seconds": elapsed,
        "git_commit": git("rev-parse", "HEAD"), "instance_id": INSTANCE_ID, "seeds": list(SEEDS),
        "iterations_per_view": ITERATIONS_PER_VIEW, "views": list(VIEWS), "no_improvement_stop": None,
        "strict_multitrip": True, "fixed_cost_cny": FIXED_COST_CNY, "fixed_cost_basis": "unique physical_vehicle_id",
        "depot_charging_concurrency": "unbounded", "fleet_authority_version": "v3_20260802",
        "fleet_authority_path": str(AUTHORITY.relative_to(REPO)), "solution_count": solution_count,
        "source_files_sha256": dict(expected), "source_tree_sha256": canonical_sha(expected),
    }


def halt_arm(name: str, expected: dict[str, str], exc: Exception) -> None:
    arm = ARMS[name]
    failure = {"arm": name, "status": "HALT_TECHNICAL", "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(), "retained_at": now()}
    write_csv(arm / "raw_runs.csv", [failure])
    write_json(arm / "decision.json", {"schema": f"resetp.scout3.{name}.decision.v1", "task_id": TASK_ID, "status": "HALT_TECHNICAL", "formal_result": False, "answer": None, "failure": failure})
    write_json(arm / "metadata.json", arm_metadata(name, "HALT_TECHNICAL", expected, len(list((arm / "solutions").rglob("*.json"))) if (arm / "solutions").exists() else 0, 0.0))
    write_text(arm / "report.md", f"# SCOUT3-{name} 技术 HALT\n\n## HALT\n\n`{failure['error']}`。已有证据全部保留；未换种子、算例或预算。\n")
    write_json(arm / "artifact_hashes.json", artifact_hashes(arm))
    write_json(arm / "done.json", {"status": "HALT_TECHNICAL", "completed_at": now(), "decision_sha256": file_sha(arm / "decision.json")})


def finalize_root(output: Path) -> None:
    decisions = {name: json.loads((path / "decision.json").read_text(encoding="utf-8")) for name, path in ARMS.items()}
    halts = [name for name, item in decisions.items() if str(item["status"]).startswith("HALT")]
    status = "SCOUT3_COMPLETE" if not halts else "SCOUT3_TERMINAL_WITH_GROUP_HALT"
    decision = {"schema": "resetp.scout3.decision.v1", "task_id": TASK_ID, "status": status, "formal_result": False, "arm_statuses": {name: item["status"] for name, item in decisions.items()}, "arm_answers": {name: item.get("answer") for name, item in decisions.items()}, "halted_arms": halts, "paper_mechanism_count_selected": False, "completed_at": now()}
    write_json(output / "decision.json", decision)
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    metadata.update({"status": status, "completed_at": now(), "arm_statuses": decision["arm_statuses"], "source_drift": False})
    write_json(output / "metadata.json", metadata)
    rows = [{"arm": name, "status": item["status"], "answer": item.get("answer"), "maximum_difference": item.get("maximum_level_gap") or item.get("maximum_paired_difference"), "effect_layers": item.get("effect_layers", [])} for name, item in decisions.items()]
    write_csv(output / "raw_runs.csv", rows)
    lines = ["# SCOUT3 三个机制效应探路总报告", "", f"终态：`{status}`；`formal_result=false`。", "", "## FACT", ""]
    for row in rows:
        lines.append(f"{row['arm']}：`{row['status']}`，回答 `{row['answer']}`，最大差 `{row['maximum_difference']}`，层 `{row['effect_layers']}`。")
        lines.append("")
    lines += ["## DECISION", "", "本包只给用户判断论文保留机制数所需的探路证据；没有代替用户选择机制数，也没有修改论文。", ""]
    if halts:
        lines += ["## HALT", "", f"技术 HALT 组：`{halts}`；其余组已继续并保留。因并非三组均形成有/无效应结论，不使用 `SCOUT3_COMPLETE`。", ""]
    write_text(output / "report.md", "\n".join(lines))
    write_json(output / "artifact_hashes.json", artifact_hashes(output))
    write_json(output / "done.json", {"status": status, "completed_at": now(), "decision_sha256": file_sha(output / "decision.json"), "artifact_hashes_sha256": file_sha(output / "artifact_hashes.json")})
    write_json(output / "progress.json", {"status": status, "completed_arms": list(ARMS), "updated_at": now()})


def preflight() -> None:
    if ITERATIONS_PER_VIEW != 25_000 or NO_IMPROVEMENT_STOP is not None:
        raise RuntimeError("budget contract drift")
    with model_config_scope(MODEL_CONFIG):
        bundle = load_china81_bundle(REPO, INSTANCE_ID, fleet_authority=AUTHORITY, model_config=MODEL_CONFIG)
        if sum(int(value["total_fleet_cap"]) for value in bundle.fleet_caps_by_depot.values()) != 16:
            raise RuntimeError("v3 default fleet total is not 16")
        initial = _level25_initial()
        _, _, violations = exact_china81_score(initial, bundle)
        if not violations:
            pass
    old = _configure_fleet()
    allocations = old.allocations_by_level()
    if {level: sum(value["total_fleet_cap"] for value in depots.values()) for level, depots in allocations.items()} != {level: 16 for level in LEVELS}:
        raise RuntimeError("fleet level totals drifted")
    dynamic = _configure_dynamic(ARMS["dynamic"])
    base = dynamic._load_bundle()
    from baselines.china_e3_e7.e7_o1_replanning_20260801.policy import build_o1_stream
    for seed in SEEDS:
        stream = build_o1_stream(base.instance, instance_id=INSTANCE_ID, stream_seed=seed)
        for policy in DYNAMIC_POLICIES:
            batches = dynamic._build_batches(stream.events, policy)
            ids = [event_id for batch in batches for event_id in batch.event_ids]
            if len(ids) != 20 or len(set(ids)) != 20:
                raise RuntimeError(f"dynamic event ledger does not close: seed={seed} policy={policy}")
    print("PASS_SCOUT3_PREFLIGHT")


def run_all(output: Path, workers: int) -> None:
    prereg = json.loads((output / "preregistration.json").read_text(encoding="utf-8"))
    if file_sha(output / "preregistration.json") != json.loads((output / "metadata.json").read_text(encoding="utf-8"))["preregistration_sha256"]:
        raise RuntimeError("preregistration drift")
    expected = dict(prereg["source_files_sha256"])
    verify_source_lock(expected)
    for name, function in (("fleet", run_fleet), ("nonlinear", run_nonlinear), ("dynamic", run_dynamic)):
        try:
            verify_source_lock(expected)
            function(output, workers, expected)
            verify_source_lock(expected)
        except Exception as exc:
            halt_arm(name, expected, exc)
        completed = [arm for arm, path in ARMS.items() if (path / "done.json").exists()]
        write_json(output / "progress.json", {"status": "SCOUT3_RUNNING", "completed_arms": completed, "current_or_next_arm": None, "updated_at": now()})
    finalize_root(output)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "prepare", "prepare-retry", "preflight", "run",
            "worker-fleet", "worker-nonlinear", "worker-dynamic",
        ),
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--level", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--curve")
    parser.add_argument("--policy")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--scenario-output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "prepare":
        prepare(args.output)
    elif args.command == "prepare-retry":
        prepare_retry(args.output)
    elif args.command == "preflight":
        preflight()
    elif args.command == "run":
        run_all(args.output, max(1, int(args.workers)))
    elif args.command == "worker-fleet":
        if args.level is None or args.seed is None or args.receipt is None:
            raise ValueError("worker-fleet requires --level --seed --receipt")
        write_json(args.receipt, fleet_worker((args.level, args.seed, {})))
    elif args.command == "worker-nonlinear":
        if args.seed is None or args.curve is None or args.receipt is None:
            raise ValueError("worker-nonlinear requires --seed --curve --receipt")
        write_json(args.receipt, nonlinear_worker((args.seed, args.curve)))
    else:
        if args.seed is None or args.policy is None or args.scenario_output is None:
            raise ValueError("worker-dynamic requires --seed --policy --scenario-output")
        dynamic_worker((args.policy, args.seed, str(args.scenario_output)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
