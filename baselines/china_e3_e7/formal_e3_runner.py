#!/usr/bin/env python3
"""Fail-closed formal E3 paired runner for corrected China81.

Formal search is impossible until ``e3_go_gate_20260723/decision.json``
contains ``GO_E3_FORMAL_SEARCH``. Every task binds the corrected authorities,
finite-fleet witness, responsibility map, algorithm/evaluator sources, result
solution, settlement trace, and independent recomputation by hash.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from importlib.metadata import version
import json
import multiprocessing as mp
import os
import platform
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any


REPO = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path = [
    entry
    for entry in sys.path
    if Path(entry or ".").resolve() != SCRIPT_DIR
]
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for path in (REPO, REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pyvrp  # noqa: E402
from route_pool_sp import run_hgs_route_pool_recombination  # noqa: E402
import numpy  # noqa: E402
import scipy  # noqa: E402
from baselines.china_e3_e7.build_e3_environment_authority import (  # noqa: E402
    distribution_tree_sha256,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    annotate_cross_site_services,
    exact_china81_score,
)
from setp_solver.cost import (  # noqa: E402
    carbon_profile_row_for_slot,
    charging_action_slot_breakdown,
    diesel_price_for_route,
    evaluate,
    route_departure_second,
    time_profile_rows_for_node,
)
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
    physical_vehicle_id,
)


CONTRACT = (
    REPO
    / "data/ChinaInstances/"
    "china_e3_formal_release_contract_v4_20260723.json"
)
GO_DECISION = (
    REPO
    / "baselines/china_e3_e7/"
    "e3_go_gate_20260723/decision.json"
)
GO_ROOT = GO_DECISION.parent
GO_METADATA = GO_ROOT / "metadata.json"
GO_ARTIFACT_HASHES = GO_ROOT / "artifact_hashes.json"
GO_RELEASE_LOCK = GO_ROOT / "release_evidence_lock.json"
FLEET = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v1_20260723"
)
SETTLEMENT = (
    REPO
    / "data/ChinaInstances/"
    "china81_spatiotemporal_settlement_authority_v1_20260723"
)
ENVIRONMENT = (
    REPO
    / "baselines/china_e3_e7/"
    "e3_environment_authority_20260723"
)
DEFAULT_OUT = (
    REPO
    / "baselines/china_e3_e7/"
    "e3_formal_20260723"
)
SEEDS = (1, 2, 3, 4, 5)
ARMS = {
    "status_quo_responsibility": True,
    "optimized_responsibility_cooperation": False,
}
MAX_HGS_ITERATIONS_PER_VIEW = 5_000
ARCHIVE_CANDIDATES_PER_VIEW = 24
EXACT_ELITES_PER_VIEW = 8
COMPLETE_CANDIDATE_BUDGET = 80
MIP_TIME_LIMIT_SECONDS = 5.0
SECONDS_PER_DAY = 24 * 60 * 60
REQUIRED_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}
EXPECTED_FORMAL_PACKAGES = {
    "pyvrp": "0.12.2",
    "numpy": "2.5.1",
    "scipy": "1.16.3",
}


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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"
    return result.stdout.strip()


def _map_index(instance_id: str) -> int:
    match = re.search(r"-(\d\d)-V2-LOCATIONS$", instance_id)
    if match is None:
        raise ValueError(
            f"cannot parse China81 map index: {instance_id}"
        )
    return int(match.group(1))


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _bundle_input_file_manifest(bundle: Any) -> dict[str, str]:
    """Hash the actual bytes behind every bundle input path."""

    manifest: dict[str, str] = {}
    for label, relative in sorted(bundle.source_paths.items()):
        path = REPO / relative
        if path.is_file():
            manifest[f"{label}:{relative}"] = file_sha256(path)
            continue
        if not path.is_dir():
            raise RuntimeError(
                f"bundle source path is missing: {label}={relative}"
            )
        files = [
            item
            for item in sorted(path.rglob("*"))
            if (
                item.is_file()
                and not item.name.startswith("._")
                and "__pycache__" not in item.parts
            )
        ]
        if not files:
            raise RuntimeError(
                f"bundle source directory is empty: {label}={relative}"
            )
        for item in files:
            manifest[
                f"{label}:{item.relative_to(REPO)}"
            ] = file_sha256(item)
    return manifest


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("cannot write an empty formal raw ledger")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _require_single_thread_environment() -> None:
    mismatches = {
        key: os.environ.get(key)
        for key, expected in REQUIRED_THREAD_ENV.items()
        if os.environ.get(key) != expected
    }
    if mismatches:
        raise RuntimeError(
            f"formal single-thread environment is not locked: {mismatches}"
        )


def _verify_formal_environment(
    *,
    full_hash: bool,
) -> dict[str, Any]:
    decision_path = ENVIRONMENT / "decision.json"
    if not decision_path.is_file():
        return {"passed": False, "failures": ["decision_missing"]}
    authority = json.loads(decision_path.read_text(encoding="utf-8"))
    prefix = Path(sys.prefix).resolve()
    modules = {
        "pyvrp": pyvrp,
        "numpy": numpy,
        "scipy": scipy,
    }
    failures: list[str] = []
    for name, expected in EXPECTED_FORMAL_PACKAGES.items():
        module_path = Path(modules[name].__file__).resolve()
        if version(name) != expected:
            failures.append(f"{name}_version")
        if not module_path.is_relative_to(prefix):
            failures.append(f"{name}_outside_prefix")
        if full_hash:
            recorded = authority.get("package_tree_hashes", {}).get(
                name
            )
            if (
                not recorded
                or distribution_tree_sha256(name) != recorded
            ):
                failures.append(f"{name}_tree_hash")
    if (
        authority.get("verdict")
        != "PASS_E3_FORMAL_ENVIRONMENT_AUTHORITY"
    ):
        failures.append("authority_verdict")
    return {
        "passed": not failures,
        "failures": failures,
        "python_prefix": str(prefix),
        "package_paths": {
            name: str(Path(module.__file__).resolve())
            for name, module in modules.items()
        },
    }


def _require_formal_environment() -> None:
    verification = _verify_formal_environment(full_hash=False)
    if not verification["passed"]:
        raise RuntimeError(
            "HOLD_E3_FORMAL_ENVIRONMENT:"
            + ",".join(verification["failures"])
        )


def _require_go() -> dict[str, Any]:
    verification = _verify_go_release()
    if not verification["passed"]:
        raise RuntimeError(
            "HOLD_E3_GO_RELEASE_NOT_CURRENT:"
            + ",".join(verification["failed_checks"])
        )
    return verification["decision"]


def _safe_relative_path(root: Path, relative: str) -> Path:
    raw = Path(relative)
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError(f"unsafe release-lock path: {relative}")
    path = (root / raw).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"release-lock path escapes root: {relative}")
    return path


def _verify_go_release(
    go_root: Path = GO_ROOT,
) -> dict[str, Any]:
    """Revalidate the GO package and every evidence byte it locked."""

    decision_path = go_root / "decision.json"
    metadata_path = go_root / "metadata.json"
    manifest_path = go_root / "artifact_hashes.json"
    lock_path = go_root / "release_evidence_lock.json"
    required = (
        decision_path,
        metadata_path,
        manifest_path,
        lock_path,
    )
    missing = [
        path.name for path in required if not path.is_file()
    ]
    checks: dict[str, bool] = {
        "go_package_complete": not missing,
    }
    failures: list[str] = []
    if missing:
        failures.append("go_package_complete")
        return {
            "passed": False,
            "failed_checks": failures,
            "missing_files": missing,
            "checks": checks,
            "decision": {},
        }

    try:
        decision_payload = json.loads(
            decision_path.read_text(encoding="utf-8")
        )
        metadata_payload = json.loads(
            metadata_path.read_text(encoding="utf-8")
        )
        manifest_payload = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        lock_payload = json.loads(
            lock_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        checks["go_package_parseable"] = False
        failures.append("go_package_parseable")
        return {
            "passed": False,
            "failed_checks": failures,
            "missing_files": [],
            "checks": checks,
            "decision": {},
        }
    checks["go_package_parseable"] = True
    checks["go_decision_pass"] = (
        decision_payload.get("verdict") == "GO_E3_FORMAL_SEARCH"
        and decision_payload.get("formal_search_allowed") is True
    )

    package_entries = manifest_payload.get("artifacts", {})
    package_current = bool(package_entries)
    if package_current:
        for relative, expected in package_entries.items():
            try:
                path = _safe_relative_path(go_root, relative)
            except ValueError:
                package_current = False
                break
            if not path.is_file() or file_sha256(path) != expected:
                package_current = False
                break
    checks["go_package_manifest_current"] = package_current

    lock_hash = file_sha256(lock_path)
    checks["release_lock_bound_to_metadata"] = (
        metadata_payload.get("release_evidence_lock_sha256")
        == lock_hash
        and decision_payload.get("release_evidence_lock_sha256")
        == lock_hash
    )
    locked_files = lock_payload.get("files", {})
    evidence_current = bool(locked_files)
    if evidence_current:
        for relative, expected in locked_files.items():
            try:
                path = _safe_relative_path(REPO, relative)
            except ValueError:
                evidence_current = False
                break
            if not path.is_file() or file_sha256(path) != expected:
                evidence_current = False
                break
    checks["release_evidence_files_current"] = evidence_current

    source_hashes = metadata_payload.get("source_hashes", {})
    sources_current = bool(source_hashes)
    if sources_current:
        for relative, expected in source_hashes.items():
            try:
                path = _safe_relative_path(REPO, relative)
            except ValueError:
                sources_current = False
                break
            if not path.is_file() or file_sha256(path) != expected:
                sources_current = False
                break
    checks["formal_and_post_run_sources_current"] = sources_current

    failures.extend(
        key for key, passed in checks.items() if not passed
    )
    return {
        "passed": not failures,
        "failed_checks": failures,
        "missing_files": [],
        "checks": checks,
        "locked_file_count": len(locked_files),
        "decision": decision_payload,
    }


def _catalog() -> list[dict[str, str]]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    path = REPO / contract["data"]["catalog"]
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return sorted(
            csv.DictReader(handle),
            key=lambda row: row["instance_id"],
        )


def _load_initial(instance_id: str) -> Solution:
    payload = json.loads(
        (FLEET / "witnesses" / f"{instance_id}.json").read_text(
            encoding="utf-8"
        )
    )
    return Solution(
        routes=[
            Route(
                vehicle_id=row["vehicle_id"],
                vehicle_type=row["vehicle_type"],
                home_depot_id=row["home_depot_id"],
                node_sequence=list(row["node_sequence"]),
            )
            for row in payload["routes"]
        ]
    )


def _solution_payload(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [
            {
                "vehicle_id": route.vehicle_id,
                "vehicle_type": route.vehicle_type,
                "home_depot_id": route.home_depot_id,
                "node_sequence": list(route.node_sequence),
            }
            for route in solution.routes
        ],
        "charging_actions": [
            {
                "vehicle_id": action.vehicle_id,
                "station_id": action.station_id,
                "energy_kwh": float(action.energy_kwh),
                "occupancy_minutes": float(action.occupancy_minutes),
                "charge_start_second": float(
                    action.charge_start_second
                ),
                "charge_day_offset": int(
                    action.charge_day_offset
                ),
                "start_energy_kwh": action.start_energy_kwh,
                "end_energy_kwh": action.end_energy_kwh,
                "charging_curve_id": action.charging_curve_id,
            }
            for action in solution.charging_actions
        ],
        "cross_site_services": [
            {
                "customer_id": item.customer_id,
                "served_by_depot_id": item.served_by_depot_id,
            }
            for item in solution.cross_site_services
        ],
    }


def _require_single_day_charging(solution: Solution) -> None:
    """Keep the fixed 2025-02-12 experiment inside its registered day."""

    for action in solution.charging_actions:
        start = float(action.charge_start_second)
        end = start + float(action.occupancy_minutes) * 60.0
        if (
            int(action.charge_day_offset) != 0
            or not 0.0 <= start < SECONDS_PER_DAY
            or end > SECONDS_PER_DAY + 1.0e-9
        ):
            raise RuntimeError(
                "HALT_E3_CHARGING_OUTSIDE_REGISTERED_SCENARIO_DATE:"
                f"{action.vehicle_id}:{action.station_id}:"
                f"day_offset={action.charge_day_offset}:"
                f"start={start}:end={end}"
            )


def _require_depot_charge_before_departure(
    solution: Solution,
    bundle: Any,
) -> None:
    """Prevent a route from borrowing energy charged after it departed."""

    routes = {
        route.vehicle_id: route
        for route in solution.routes
    }
    for action in solution.charging_actions:
        node = bundle.instance.nodes[
            bundle.instance.node_index[action.station_id]
        ]
        if node.node_type.lower() != "d":
            continue
        route = routes[action.vehicle_id]
        end = (
            float(action.charge_start_second)
            + float(action.occupancy_minutes) * 60.0
        )
        departure = route_departure_second(
            route,
            bundle.instance,
            bundle.prices,
        )
        if end > departure + 1.0e-9:
            raise RuntimeError(
                "HALT_E3_DEPOT_CHARGE_AFTER_ROUTE_DEPARTURE:"
                f"{action.vehicle_id}:{action.station_id}:"
                f"end={end}:departure={departure}"
            )


def _require_depot_fleet_caps(
    solution: Solution,
    bundle: Any,
) -> None:
    """Independently enforce every depot-by-powertrain physical cap."""

    used: dict[tuple[str, str], set[str]] = {}
    for route in solution.routes:
        depot_id = str(route.home_depot_id)
        vehicle_type = str(route.vehicle_type).strip().lower()
        if depot_id not in bundle.fleet_caps_by_depot:
            raise RuntimeError("HALT_E3_UNKNOWN_FLEET_DEPOT")
        if vehicle_type not in {"cv", "ev"}:
            raise RuntimeError("HALT_E3_UNKNOWN_FLEET_TYPE")
        used.setdefault((depot_id, vehicle_type), set()).add(
            physical_vehicle_id(route.vehicle_id)
        )
    for (depot_id, vehicle_type), physical_ids in used.items():
        cap = int(
            bundle.fleet_caps_by_depot[depot_id][
                f"num_{vehicle_type}"
            ]
        )
        if len(physical_ids) > cap:
            raise RuntimeError(
                "HALT_E3_DEPOT_FLEET_CAP:"
                f"{depot_id}:{vehicle_type}:{len(physical_ids)}>{cap}"
            )


def _settlement_trace(
    solution: Solution,
    bundle: Any,
) -> dict[str, Any]:
    diesel_rows = []
    for route in solution.routes:
        if route.vehicle_type.lower() != "cv":
            continue
        depot = bundle.instance.nodes[
            bundle.instance.node_index[route.home_depot_id]
        ]
        city = str(depot.city).strip().lower()
        diesel_rows.append(
            {
                "vehicle_id": route.vehicle_id,
                "route_origin_depot": route.home_depot_id,
                "city": city,
                "diesel_zone": bundle.diesel_zone_by_city[city],
                "scenario_date": bundle.date,
                "diesel_price_cny_per_l": diesel_price_for_route(
                    route,
                    bundle.instance,
                    bundle.prices,
                ),
            }
        )

    charging_rows = []
    for action in solution.charging_actions:
        node = bundle.instance.nodes[
            bundle.instance.node_index[action.station_id]
        ]
        city = str(node.city).strip().lower()
        profile = time_profile_rows_for_node(
            bundle.instance,
            action.station_id,
            bundle.time_profile,
        )
        price_field = (
            "depot_energy_cny_per_kwh"
            if node.node_type.lower() == "d"
            else "public_total_cny_per_kwh"
        )
        for slot in charging_action_slot_breakdown(
            action,
            bundle.instance,
            bundle.prices,
            n_slots=len(profile),
            cyclic=True,
        ):
            row = carbon_profile_row_for_slot(
                profile,
                slot.slot_index,
            )
            if (
                row["date"] != bundle.date
                or row["price_area_id"]
                != bundle.price_area_by_city[city]
                or row["carbon_source_column"]
                != bundle.carbon_source_column_by_city[city]
                or row["diesel_zone"]
                != bundle.diesel_zone_by_city[city]
                or row["joint_key_status"]
                != "PASS_CITY_DATE_SLOT_PARAMETER_IDENTITY"
            ):
                raise RuntimeError(
                    "charging settlement joint key failed closed"
                )
            charging_rows.append(
                {
                    "vehicle_id": action.vehicle_id,
                    "station_id": action.station_id,
                    "node_type": node.node_type,
                    "city": city,
                    "price_area_id": row["price_area_id"],
                    "carbon_source_column": (
                        row["carbon_source_column"]
                    ),
                    "diesel_zone": row["diesel_zone"],
                    "scenario_date": row["date"],
                    "half_hour_slot": int(row["half_hour_slot"]),
                    "energy_kwh": float(slot.y_skt_kwh),
                    "electricity_price_field": price_field,
                    "electricity_price_cny_per_kwh": float(
                        row[price_field]
                    ),
                    "carbon_factor_kgco2e_per_kwh": (
                        float(row["actual_gco2_per_kwh"]) / 1000.0
                    ),
                }
            )
    return {
        "schema": "resetp.china81-task-settlement-trace.v1",
        "joint_key_policy": "FAIL_CLOSED_NO_CITY_GROUP_FALLBACK",
        "scenario_date": bundle.date,
        "diesel_routes": diesel_rows,
        "charging_slot_segments": charging_rows,
    }


def _source_hashes() -> dict[str, str]:
    paths = (
        CONTRACT,
        GO_DECISION,
        GO_METADATA,
        GO_ARTIFACT_HASHES,
        GO_RELEASE_LOCK,
        ENVIRONMENT / "artifact_hashes.json",
        SETTLEMENT / "artifact_hashes.json",
        FLEET / "artifact_hashes.json",
        PROTOTYPE / "pyvrp_adapter.py",
        PROTOTYPE / "epochal_hgs.py",
        PROTOTYPE / "route_pool_sp.py",
        REPO / "solver/src/setp_solver/china81.py",
        REPO / "solver/src/setp_solver/china81_completion.py",
        REPO / "solver/src/setp_solver/cost.py",
        REPO / "solver/src/setp_solver/check.py",
        REPO / "solver/src/setp_solver/prices.py",
        REPO / "solver/src/setp_solver/solution.py",
        REPO / "solver/src/setp_solver/instance_loader.py",
        REPO / "solver/src/setp_solver/charging_curve.py",
        REPO
        / "solver/src/setp_solver/algorithms/resetp_alns/"
        "support/charging.py",
        REPO
        / "baselines/china_e3_e7/"
        "build_e3_environment_authority.py",
        Path(__file__).resolve(),
    )
    return {
        str(path.relative_to(REPO)): file_sha256(path)
        for path in paths
    }


def _task_id(instance_id: str, seed: int, arm_id: str) -> str:
    return f"E3__{instance_id}__seed{seed}__{arm_id}"


def run_task(
    instance_id: str,
    seed: int,
    arm_id: str,
    out_root: Path,
) -> dict[str, Any]:
    _require_single_thread_environment()
    _require_formal_environment()
    go = _require_go()
    if arm_id not in ARMS:
        raise ValueError(f"unknown E3 arm: {arm_id}")
    task_id = _task_id(instance_id, seed, arm_id)
    task_dir = out_root / "tasks" / task_id
    decision_path = task_dir / "decision.json"
    if decision_path.is_file():
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        if decision.get("verdict") == "PASS_E3_TASK":
            metadata = json.loads(
                (task_dir / "metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            if metadata.get("source_hashes") != _source_hashes():
                raise RuntimeError(
                    f"HALT_E3_RESUME_SOURCE_HASH_DRIFT:{task_id}"
                )
            manifest = json.loads(
                (task_dir / "artifact_hashes.json").read_text(
                    encoding="utf-8"
                )
            )
            for name, expected in manifest["artifacts"].items():
                path = task_dir / name
                if not path.is_file() or file_sha256(path) != expected:
                    raise RuntimeError(
                        f"HALT_E3_RESUME_ARTIFACT_DRIFT:"
                        f"{task_id}:{name}"
                    )
            return decision["raw_row"]
        raise RuntimeError(f"existing task is not PASS: {task_id}")

    bundle = load_china81_bundle(REPO, instance_id)
    input_file_manifest = _bundle_input_file_manifest(bundle)
    initial = _load_initial(instance_id)
    responsibility_payload = dict(bundle.customer_home_depot)
    initial_payload = _solution_payload(initial)
    customer_count = sum(
        node.node_type.lower() == "c"
        for node in bundle.instance.nodes
    )
    safety_seconds = max(180.0, 2.0 * customer_count)
    started = perf_counter()
    run = run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=int(seed),
        hgs_seconds_per_view=None,
        exact_elites_per_view=EXACT_ELITES_PER_VIEW,
        max_archive_candidates_per_view=(
            ARCHIVE_CANDIDATES_PER_VIEW
        ),
        sp_time_limit_seconds=MIP_TIME_LIMIT_SECONDS,
        hard_home_depot_lock=ARMS[arm_id],
        max_hgs_iterations_per_view=(
            MAX_HGS_ITERATIONS_PER_VIEW
        ),
        wallclock_safety_seconds_per_view=safety_seconds,
    )
    solution = annotate_cross_site_services(
        run.solution,
        bundle.customer_home_depot,
    )
    objective, breakdown, violations = exact_china81_score(
        solution,
        bundle,
    )
    independent_violations = check_solution(
        solution,
        bundle.instance,
        bundle.prices,
    )
    independent_breakdown = evaluate(
        solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    if violations or independent_violations:
        raise RuntimeError(
            f"formal E3 result is infeasible: {task_id}"
        )
    if abs(
        float(independent_breakdown["total_cost"]) - objective
    ) > 1e-9:
        raise RuntimeError("independent E3 objective recomputation differs")
    if ARMS[arm_id] and solution.cross_site_services:
        raise RuntimeError("control E3 task contains cross-site service")
    if run.stats["wallclock_safety_triggered"]:
        raise RuntimeError("HALT_SAFETY_WALLCLOCK")
    if (
        run.stats["complete_candidate_evaluation_attempts"]
        != COMPLETE_CANDIDATE_BUDGET
        or not run.stats[
            "complete_candidate_budget_exactly_consumed"
        ]
    ):
        raise RuntimeError("HALT_COMPLETE_CANDIDATE_BUDGET_MISMATCH")
    if not ARMS[arm_id] and not all(
        epoch.stats[
            "reciprocal_cross_depot_neighbourhood_enabled"
        ]
        for epoch in run.view_epochs.values()
    ):
        raise RuntimeError("treatment reciprocal neighborhood is inactive")

    _require_depot_fleet_caps(solution, bundle)
    _require_single_day_charging(solution)
    _require_depot_charge_before_departure(solution, bundle)
    settlement_trace = _settlement_trace(solution, bundle)
    solution_payload = _solution_payload(solution)
    source_hashes = _source_hashes()
    algorithm_hash = payload_sha256(
        {
            key: value
            for key, value in source_hashes.items()
            if (
                "algorithm_prototypes" in key
                or key.endswith("formal_e3_runner.py")
            )
        }
    )
    evaluator_hash = payload_sha256(
        {
            key: value
            for key, value in source_hashes.items()
            if "/solver/src/setp_solver/" in f"/{key}"
        }
    )
    independent_payload = {
        "objective": float(independent_breakdown["total_cost"]),
        "breakdown": independent_breakdown,
        "violation_count": len(independent_violations),
    }
    cross_directions: dict[str, int] = {}
    for service in solution.cross_site_services:
        owner = bundle.customer_home_depot[service.customer_id]
        key = f"{owner}->{service.served_by_depot_id}"
        cross_directions[key] = cross_directions.get(key, 0) + 1
    observed_candidate_directions: dict[str, int] = {}
    for epoch in run.view_epochs.values():
        for direction, count in epoch.stats[
            "cross_depot_direction_counts"
        ].items():
            observed_candidate_directions[direction] = (
                observed_candidate_directions.get(direction, 0)
                + int(count)
            )
    mip = run.stats["route_pool_mip"]
    elapsed = perf_counter() - started
    raw_row = {
        # Common China E3--E7 evidence schema. These governance aliases are
        # emitted alongside the more detailed E3 task fields below so the
        # sealed formal output can enter the preregistered paired aggregator
        # without a result-dependent conversion step.
        "record_type": "formal_run",
        "experiment_id": "CHINA-E3-FORMAL-RELEASE-001",
        "family": "E3",
        "task_id": task_id,
        "pair_id": f"E3__{instance_id}__seed{seed}",
        "instance_id": instance_id,
        "region": bundle.region,
        "customer_size": customer_count,
        "customer_count": customer_count,
        "map_index": _map_index(instance_id),
        "seed": int(seed),
        "arm": arm_id,
        "arm_id": arm_id,
        "calendar_date": bundle.date,
        "all_charge_day_offsets_zero": True,
        "all_charging_within_registered_day": True,
        "all_depot_charging_finishes_before_departure": True,
        "all_depot_fleet_caps_respected": True,
        "feasible": True,
        "hard_home_depot_lock": ARMS[arm_id],
        "reciprocal_cross_depot_neighbourhood": (
            not ARMS[arm_id]
        ),
        "complete_candidate_budget": COMPLETE_CANDIDATE_BUDGET,
        "complete_candidate_attempts": run.stats[
            "complete_candidate_evaluation_attempts"
        ],
        "wallclock_safety_seconds_per_view": safety_seconds,
        "wallclock_safety_triggered": False,
        "elapsed_seconds": float(elapsed),
        "runtime_seconds": float(elapsed),
        "total_cost": float(objective),
        "charging_emissions": float(breakdown["E_ev_indirect"]),
        "total_emissions": float(breakdown["E_total"]),
        "total_emissions_kg": float(breakdown["E_total"]),
        "infeasibility_count": 0,
        "service_level": 1.0,
        "cross_site_service_count": len(
            solution.cross_site_services
        ),
        "cross_site_directions_json": json.dumps(
            cross_directions,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "cross_depot_candidate_attempts": sum(
            int(epoch.stats["cross_depot_candidate_attempts"])
            for epoch in run.view_epochs.values()
        ),
        "cross_depot_candidate_directions_json": json.dumps(
            observed_candidate_directions,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "mip_status": mip["status"],
        "mip_status_class": mip["status_class"],
        "mip_message": mip["message"],
        "mip_incumbent_available": mip["incumbent_available"],
        "mip_objective": mip["objective"],
        "mip_dual_bound": mip["dual_bound"],
        "mip_gap": mip["mip_gap"],
        "mip_node_count": mip["mip_node_count"],
        "mip_time_limit_seconds": mip["time_limit_seconds"],
        "mip_optimality_proven": mip["optimality_proven"],
        "selected_source": run.stats["selected_source"],
        "input_manifest_sha256": payload_sha256(
            input_file_manifest
        ),
        "spatiotemporal_crosswalk_sha256": file_sha256(
            SETTLEMENT / "artifact_hashes.json"
        ),
        "responsibility_map_sha256": payload_sha256(
            responsibility_payload
        ),
        "initial_solution_sha256": payload_sha256(initial_payload),
        "algorithm_source_sha256": algorithm_hash,
        "evaluator_source_sha256": evaluator_hash,
        "solution_sha256": payload_sha256(solution_payload),
        "settlement_trace_sha256": payload_sha256(
            settlement_trace
        ),
        "independent_recompute_sha256": payload_sha256(
            independent_payload
        ),
        "git_head": _git_head(),
        "contract_sha256": file_sha256(CONTRACT),
        "algorithm_id": "MV-HGS-SP",
        "evaluator_id": evaluator_hash,
        "search_evaluations": COMPLETE_CANDIDATE_BUDGET,
        "solution_path": _display_path(
            task_dir / "solution_witness.json"
        ),
        "certificate_path": _display_path(
            task_dir / "certificate.json"
        ),
        "source_hash": payload_sha256(source_hashes),
        "status_reason": "",
        "go_decision_sha256": file_sha256(GO_DECISION),
        "formal_task_status": "PASS",
        "status": "complete",
    }
    certificate = {
        "schema": "resetp.china-e3-task-certificate.v1",
        "task_id": task_id,
        "contract_sha256": file_sha256(CONTRACT),
        "go_decision": go,
        "source_hashes": source_hashes,
        "bundle_authorities": {
            "static": bundle.static_input_authority,
            "road": bundle.road_matrix_authority,
            "runtime": bundle.runtime_parameter_authority,
            "fleet": bundle.fleet_authority,
        },
        "input_file_manifest": input_file_manifest,
        "responsibility_map": responsibility_payload,
        "initial_solution": initial_payload,
        "run_stats": run.stats,
        "settlement_trace": settlement_trace,
        "independent_recompute": independent_payload,
        "raw_row": raw_row,
    }
    write_json(task_dir / "solution_witness.json", solution_payload)
    write_json(task_dir / "certificate.json", certificate)
    raw_row["certificate_sha256"] = file_sha256(
        task_dir / "certificate.json"
    )
    write_csv(task_dir / "raw_runs.csv", [raw_row])
    write_json(
        task_dir / "metadata.json",
        {
            "schema": "resetp.china-e3-task-metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "task_id": task_id,
            "python": sys.version,
            "platform": platform.platform(),
            "pyvrp_version": version("pyvrp"),
            "numpy_version": numpy.__version__,
            "numpy_path": str(Path(numpy.__file__).resolve()),
            "scipy_version": scipy.__version__,
            "scipy_path": str(Path(scipy.__file__).resolve()),
            "thread_environment": {
                key: os.environ.get(key)
                for key in REQUIRED_THREAD_ENV
            },
            "source_hashes": source_hashes,
        },
    )
    decision = {
        "schema": "resetp.china-e3-task-decision.v1",
        "verdict": "PASS_E3_TASK",
        "formal_search_allowed": True,
        "raw_row": raw_row,
    }
    write_json(decision_path, decision)
    (task_dir / "report.md").write_text(
        f"# E3 formal task {task_id}\n\n"
        "The paired-arm task consumed exactly 80 complete-candidate "
        "submissions, did not trigger the wallclock safety cap, passed the "
        "complete checker and independent recomputation, and emitted a "
        "city/date/slot settlement trace.\n",
        encoding="utf-8",
    )
    hashes = {
        path.name: file_sha256(path)
        for path in sorted(task_dir.iterdir())
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    write_json(
        task_dir / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": hashes,
        },
    )
    return raw_row


def _worker(args: tuple[str, int, str, str]) -> dict[str, Any]:
    instance_id, seed, arm_id, out_root = args
    return run_task(instance_id, seed, arm_id, Path(out_root))


def run_all(out_root: Path, workers: int) -> None:
    _require_go()
    tasks = [
        (row["instance_id"], seed, arm_id, str(out_root))
        for row in _catalog()
        for seed in SEEDS
        for arm_id in ARMS
    ]
    if workers < 1:
        raise ValueError("workers must be positive")
    with mp.get_context("spawn").Pool(processes=workers) as pool:
        for row in pool.imap_unordered(_worker, tasks):
            print(
                f"[E3] {row['task_id']} PASS "
                f"cost={row['total_cost']:.6f}",
                flush=True,
            )
    finalize(out_root)


def _validate_formal_rows(
    rows: list[dict[str, str]],
    *,
    expected: int,
) -> tuple[int, tuple[str, ...]]:
    if len(rows) != expected:
        raise RuntimeError(
            f"cannot finalize E3: expected {expected}, found {len(rows)}"
        )
    if any(row["status"] != "complete" for row in rows):
        raise RuntimeError("cannot finalize E3 with non-complete tasks")
    if len({row["task_id"] for row in rows}) != expected:
        raise RuntimeError("cannot finalize E3 with duplicate task ids")
    if any(
        int(row["complete_candidate_attempts"])
        != COMPLETE_CANDIDATE_BUDGET
        or row["wallclock_safety_triggered"].lower() == "true"
        or row["all_charge_day_offsets_zero"].lower() != "true"
        or row["all_charging_within_registered_day"].lower() != "true"
        or row[
            "all_depot_charging_finishes_before_departure"
        ].lower()
        != "true"
        or row["all_depot_fleet_caps_respected"].lower() != "true"
        for row in rows
    ):
        raise RuntimeError(
            "cannot finalize E3 with budget, safety-cap, or date mismatch"
        )
    pairs: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        pairs.setdefault(row["pair_id"], []).append(row)
    if len(pairs) != expected // 2:
        raise RuntimeError("cannot finalize E3 with missing pair ids")
    paired_hash_fields = (
        "instance_id",
        "seed",
        "input_manifest_sha256",
        "spatiotemporal_crosswalk_sha256",
        "responsibility_map_sha256",
        "initial_solution_sha256",
        "algorithm_source_sha256",
        "evaluator_source_sha256",
        "go_decision_sha256",
    )
    for pair_id, pair in pairs.items():
        if len(pair) != 2 or {
            row["arm_id"] for row in pair
        } != set(ARMS):
            raise RuntimeError(f"invalid E3 arm pair: {pair_id}")
        for field in paired_hash_fields:
            if len({row[field] for row in pair}) != 1:
                raise RuntimeError(
                    f"E3 pair differs on {field}: {pair_id}"
                )
    return len(pairs), paired_hash_fields


def finalize(out_root: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    source_hash_sets: set[str] = set()
    current_sources = _source_hashes()
    for path in sorted((out_root / "tasks").glob("*/raw_runs.csv")):
        task_dir = path.parent
        metadata = json.loads(
            (task_dir / "metadata.json").read_text(encoding="utf-8")
        )
        source_hashes = metadata.get("source_hashes")
        if source_hashes != current_sources:
            raise RuntimeError(
                f"cannot finalize E3 with source drift: {task_dir.name}"
            )
        source_hash_sets.add(
            json.dumps(
                source_hashes,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        manifest = json.loads(
            (task_dir / "artifact_hashes.json").read_text(
                encoding="utf-8"
            )
        )
        for name, expected_hash in manifest["artifacts"].items():
            artifact = task_dir / name
            if (
                not artifact.is_file()
                or file_sha256(artifact) != expected_hash
            ):
                raise RuntimeError(
                    f"cannot finalize E3 with artifact drift: "
                    f"{task_dir.name}/{name}"
                )
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows.extend(csv.DictReader(handle))
    expected = len(_catalog()) * len(SEEDS) * len(ARMS)
    if len(source_hash_sets) != 1:
        raise RuntimeError("cannot finalize E3 with mixed source hashes")
    pair_count, paired_hash_fields = _validate_formal_rows(
        rows,
        expected=expected,
    )
    write_csv(out_root / "raw_runs.csv", rows)
    decision = {
        "schema": "resetp.china-e3-formal-decision.v1",
        "verdict": "PASS_E3_FORMAL_RAW_COMPLETE",
        "task_count": len(rows),
        "pair_count": pair_count,
        "paired_hash_fields_verified": list(paired_hash_fields),
        "source_hash_set_count": len(source_hash_sets),
        "complete_candidate_budget_per_task": (
            COMPLETE_CANDIDATE_BUDGET
        ),
        "scientific_claim_allowed": False,
        "next_gate": "independent paired statistics and claim audit",
    }
    write_json(out_root / "decision.json", decision)
    write_json(
        out_root / "metadata.json",
        {
            "schema": "resetp.china-e3-formal-metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "contract_sha256": file_sha256(CONTRACT),
            "go_decision_sha256": file_sha256(GO_DECISION),
            "task_count": len(rows),
        },
    )
    (out_root / "report.md").write_text(
        "# China81 E3 formal raw campaign\n\n"
        "All paired raw tasks and task-level certificates are present. This "
        "decision closes raw execution only; it does not itself authorize a "
        "scientific effect claim before paired statistical aggregation and "
        "claim audit.\n",
        encoding="utf-8",
    )
    hashes = {
        str(path.relative_to(out_root)): file_sha256(path)
        for path in sorted(out_root.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    write_json(
        out_root / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
                "*.tmp",
            ],
            "artifacts": hashes,
        },
    )
    return decision


def preflight(go_root: Path = GO_ROOT) -> dict[str, Any]:
    go_verification = _verify_go_release(go_root)
    environment_verification = _verify_formal_environment(
        full_hash=True
    )
    checks = {
        "contract_present": CONTRACT.is_file(),
        "formal_environment_current": (
            environment_verification["passed"]
        ),
        "settlement_authority_pass": (
            json.loads(
                (SETTLEMENT / "decision.json").read_text(
                    encoding="utf-8"
                )
            )["verdict"]
            == "PASS_FAIL_CLOSED_SPATIOTEMPORAL_SETTLEMENT_AUTHORITY"
        ),
        "fleet_authority_pass": (
            json.loads(
                (FLEET / "decision.json").read_text(encoding="utf-8")
            )["verdict"]
            == "PASS_FINITE_FLEET_ZERO_SEARCH_WITNESSES"
        ),
        "pyvrp_0_12_2": version("pyvrp") == "0.12.2",
        "single_thread_environment": all(
            os.environ.get(key) == value
            for key, value in REQUIRED_THREAD_ENV.items()
        ),
        "go_decision_present": (go_root / "decision.json").is_file(),
        "go_release_evidence_current": go_verification["passed"],
    }
    checks["go_decision_pass"] = go_verification["checks"].get(
        "go_decision_pass",
        False,
    )
    return {
        "schema": "resetp.china-e3-formal-preflight.v1",
        "status": (
            "PASS_E3_FORMAL_RUNNER_READY"
            if all(checks.values())
            else "HOLD_E3_FORMAL_RUNNER"
        ),
        "checks": checks,
        "go_release_verification": go_verification,
        "environment_verification": environment_verification,
        "formal_search_allowed": bool(all(checks.values())),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight")
    one = subparsers.add_parser("run-task")
    one.add_argument("--instance", required=True)
    one.add_argument("--seed", required=True, type=int)
    one.add_argument("--arm", required=True, choices=sorted(ARMS))
    one.add_argument("--out", type=Path, default=DEFAULT_OUT)
    all_parser = subparsers.add_parser("run-all")
    all_parser.add_argument("--workers", type=int, default=6)
    all_parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    final = subparsers.add_parser("finalize")
    final.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if args.command == "preflight":
        print(json.dumps(preflight(), ensure_ascii=False, sort_keys=True))
    elif args.command == "run-task":
        row = run_task(args.instance, args.seed, args.arm, args.out)
        print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    elif args.command == "run-all":
        run_all(args.out, args.workers)
    elif args.command == "finalize":
        print(
            json.dumps(
                finalize(args.out),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
