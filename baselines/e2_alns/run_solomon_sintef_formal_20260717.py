#!/usr/bin/env python3
"""Run the sealed SINTEF Solomon benchmark after every upstream gate passes.

The 56 Solomon instances are a final test set.  Search workers receive only
the instance bundle, seed, budget, runtime and a proved lexicographic scalar;
they never receive BKS values, reference routes or reference codes.  BKS data
are joined by the parent process only after independent solution recomputation.
"""

from __future__ import annotations

import argparse
from collections import deque
import csv
import hashlib
import inspect
import io
import json
import math
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping

import numpy as np


REPO = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO / "solver/src"
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

from setp_solver.search.bundle import load_search_bundle  # noqa: E402


REFERENCE_ROOT = REPO / "baselines/e2_alns/e2_solomon_sintef_bks_audit_20260717"
REFERENCE = REFERENCE_ROOT / "raw_runs.csv"
BUNDLES = REPO / "baselines/e2_alns/solomon_sintef_formal_bundles_20260717_v3"
CPU_CONTRACT = REPO / "baselines/e2_alns/solomon_cpu_contract_20260717.json"
CPU_PREFLIGHT = REPO / "baselines/e2_alns/solomon_cpu_preflight_20260717_v5"
ALGORITHM_FREEZE = REPO / "baselines/e2_alns/final_algorithm_freeze/algorithm_freeze.json"
DEFAULT_OUT = REPO / "baselines/e2_alns/e2_solomon_sintef_formal_20260717"
E7_ROOTS = {
    "formal": REPO / "baselines/e7_dynamic/e7_multinetwork_formal_20260715",
    "replay": REPO / "baselines/e7_dynamic/e7_multiday_zero_search_replay_20260715",
    "replay_invariants": REPO / "baselines/e7_dynamic/e7_replay_invariants_audit_20260715",
    "independent_audit": REPO / "baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715",
}
FORMAL_SEEDS = tuple(range(1, 11))
FORMAL_EVAL_BUDGET = 4000
FORMAL_WORKERS = 8
FORMAL_MAX_RUNTIME_SECONDS = 1800.0
HARD_TIMEOUT_GRACE_SECONDS = 5.0
WORKER_POLL_SECONDS = 0.2
GOLD_PYTHON = "/opt/anaconda3/bin/python3.13"
GOLD_NUMPY = "2.3.5"
CONTRACT_SCHEMA = "resetp.e2.solomon-sintef-formal.v1"
TASK_SCHEMA = "resetp.e2.solomon-sintef-task.v1"
CHECKPOINT_SCHEMA = "resetp.e2.solomon-sintef-checkpoint.v1"
TOL = 1e-8
ROUND_2 = Decimal("0.01")
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}


class FormalRunError(RuntimeError):
    """A contract or infrastructure failure that must stop the formal run."""


class BKSConflictError(FormalRunError):
    """A candidate improves the frozen BKS tuple and requires independent review."""


class CheckpointError(FormalRunError):
    """A resumable task checkpoint is missing identity or integrity evidence."""


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
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
    )


def atomic_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows({field: row.get(field, "") for field in fields} for row in rows)
    atomic_text(path, buffer.getvalue())


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def round_half_up_2(value: float) -> float:
    return float(Decimal(str(value)).quantize(ROUND_2, rounding=ROUND_HALF_UP))


def lex_key(route_count: int, distance: float) -> tuple[int, float]:
    return int(route_count), float(distance)


def reference_assessment(
    route_count: int,
    rounded_distance: float,
    bks_vehicles: int,
    bks_distance: float,
) -> dict[str, Any]:
    """Apply the frozen SINTEF BKS and conditional-Gap rules."""

    route_count = int(route_count)
    bks_vehicles = int(bks_vehicles)
    rounded_distance = round_half_up_2(rounded_distance)
    bks_distance = round_half_up_2(bks_distance)
    reached = route_count == bks_vehicles
    vehicle_excess = route_count - bks_vehicles
    distance_gap: float | str = ""
    full_hit = False
    conflict = route_count < bks_vehicles
    if reached:
        distance_gap = 100.0 * (rounded_distance - bks_distance) / bks_distance
        full_hit = rounded_distance == bks_distance
        conflict = rounded_distance < bks_distance
    return {
        "reached_bks_vehicle_count": reached,
        "vehicle_excess": vehicle_excess,
        "distance_gap_pct": distance_gap,
        "full_bks_hit": full_hit,
        "bks_conflict_candidate": conflict,
    }


def read_references(path: Path = REFERENCE) -> dict[str, dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        raw = list(csv.DictReader(handle))
    if len(raw) != 56 or len({row["instance"] for row in raw}) != 56:
        raise FormalRunError("SINTEF BKS audit does not contain 56 unique instances")
    expected_classes = {"C1": 9, "C2": 8, "R1": 12, "R2": 11, "RC1": 8, "RC2": 8}
    observed = {name: sum(row["class"] == name for row in raw) for name in expected_classes}
    if observed != expected_classes:
        raise FormalRunError(f"SINTEF class counts differ: {observed}")
    rows: dict[str, dict[str, Any]] = {}
    for row in raw:
        if row["vehicle_match"] != "1" or row["distance_match"] != "1" or row["solution_feasible"] != "1":
            raise FormalRunError(f"reference audit does not pass: {row['instance']}")
        if int(row["search_evaluations"]) != 0:
            raise FormalRunError("reference audit unexpectedly used search")
        rows[row["instance"]] = {
            "instance": row["instance"],
            "class": row["class"],
            "capacity": int(row["capacity"]),
            "max_vehicles": int(row["max_vehicles"]),
            "bks_vehicle_count": int(row["bks_vehicles"]),
            "bks_distance_published_2dp": float(row["bks_distance"]),
            "bks_distance_recomputed_double": float(row["computed_distance_double"]),
            "reference_code": row["reference_code"],
            "solution_sha256": row["solution_sha256"],
        }
    return rows


FORMAL_INSTANCES = (
    "C101", "C102", "C103", "C104", "C105", "C106", "C107", "C108", "C109",
    "C201", "C202", "C203", "C204", "C205", "C206", "C207", "C208",
    "R101", "R102", "R103", "R104", "R105", "R106", "R107", "R108", "R109",
    "R110", "R111", "R112", "R201", "R202", "R203", "R204", "R205", "R206",
    "R207", "R208", "R209", "R210", "R211", "RC101", "RC102", "RC103", "RC104",
    "RC105", "RC106", "RC107", "RC108", "RC201", "RC202", "RC203", "RC204",
    "RC205", "RC206", "RC207", "RC208",
)


def manifest_items(payload: Any) -> dict[str, str]:
    if isinstance(payload, dict) and "artifacts" in payload:
        artifacts = payload["artifacts"]
        if isinstance(artifacts, dict):
            return {str(key): str(value) for key, value in artifacts.items()}
        return {
            str(item.get("path") or item.get("file")): str(item["sha256"])
            for item in artifacts
        }
    if isinstance(payload, dict):
        return {str(key): str(value) for key, value in payload.items()}
    raise FormalRunError("artifact manifest has an unsupported shape")


def verify_artifact_manifest(
    root: Path,
    *,
    require_five_surfaces: bool = True,
    exact_inventory: bool = True,
) -> dict[str, str]:
    if not root.is_dir():
        raise FormalRunError(f"evidence directory is missing: {root}")
    sidecars = sorted(str(path.relative_to(root)) for path in root.rglob("._*") if path.is_file())
    if sidecars:
        raise FormalRunError(f"AppleDouble contamination at {root}: {sidecars[:5]}")
    five = {"metadata.json", "raw_runs.csv", "decision.json", "artifact_hashes.json", "report.md"}
    if require_five_surfaces and any(not (root / name).is_file() for name in five):
        missing = sorted(name for name in five if not (root / name).is_file())
        raise FormalRunError(f"five evidence surfaces are incomplete at {root}: {missing}")
    manifest_path = root / "artifact_hashes.json"
    if not manifest_path.is_file():
        raise FormalRunError(f"artifact manifest is missing: {root}")
    items = manifest_items(json.loads(manifest_path.read_text(encoding="utf-8")))
    for relative, expected in items.items():
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            raise FormalRunError(f"artifact hash differs: {root.name}/{relative}")
    if exact_inventory:
        observed = {
            str(path.relative_to(root))
            for path in root.rglob("*")
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and ".tasks" not in path.parts
            and not path.name.startswith("._")
        }
        if observed != set(items):
            raise FormalRunError(
                f"artifact inventory differs at {root}: "
                f"unlisted={sorted(observed-set(items))[:5]}, missing={sorted(set(items)-observed)[:5]}"
            )
    return {relative: sha256(root / relative) for relative in sorted(items)}


def verify_repo_aware_manifest(root: Path) -> dict[str, str]:
    """Verify manifests that intentionally include both package and repo files."""

    sidecars = sorted(root.rglob("._*"))
    if sidecars:
        raise FormalRunError(f"AppleDouble contamination at {root}")
    items = manifest_items(json.loads((root / "artifact_hashes.json").read_text(encoding="utf-8")))
    verified: dict[str, str] = {}
    for relative, expected in items.items():
        package_path = root / relative
        repo_path = REPO / relative
        path = package_path if package_path.is_file() else repo_path
        if not path.is_file() or sha256(path) != expected:
            raise FormalRunError(f"repo-aware artifact hash differs: {relative}")
        verified[relative] = expected
    observed = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    package_listed = {relative for relative in items if (root / relative).is_file()}
    if observed != package_listed:
        raise FormalRunError(
            f"repo-aware artifact inventory differs at {root}: "
            f"unlisted={sorted(observed-package_listed)[:5]}, missing={sorted(package_listed-observed)[:5]}"
        )
    return verified


def verify_gold_environment() -> None:
    if str(Path(sys.executable).resolve()) != str(Path(GOLD_PYTHON).resolve()):
        raise FormalRunError(f"gold Python required: {GOLD_PYTHON}; got {sys.executable}")
    if np.__version__ != GOLD_NUMPY:
        raise FormalRunError(f"gold NumPy required: {GOLD_NUMPY}; got {np.__version__}")
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise FormalRunError("PYTHONHASHSEED=0 must be set before Python starts")
    drift = {key: os.environ.get(key) for key, expected in THREAD_ENV.items() if os.environ.get(key) != expected}
    if drift:
        raise FormalRunError(f"single-thread environment differs: {drift}")


def require_bks_and_bundle_gates() -> dict[str, Any]:
    required = {"metadata.json", "raw_runs.csv", "decision.json", "artifact_hashes.json", "report.md"}
    if any(not (REFERENCE_ROOT / name).is_file() for name in required):
        raise FormalRunError("SINTEF BKS evidence lacks one of the five required surfaces")
    verify_repo_aware_manifest(REFERENCE_ROOT)
    reference_decision = json.loads((REFERENCE_ROOT / "decision.json").read_text(encoding="utf-8"))
    if reference_decision.get("verdict") != "PASS_SOLOMON_SINTEF_BKS_ZERO_SEARCH_AUDIT":
        raise FormalRunError("SINTEF BKS zero-search audit does not pass")
    verify_repo_aware_manifest(BUNDLES)
    bundle_decision = json.loads((BUNDLES / "decision.json").read_text(encoding="utf-8"))
    if bundle_decision.get("verdict") != "PASS_SOLOMON_SINTEF_BUNDLE_GATE" or bundle_decision.get("failures"):
        raise FormalRunError("SINTEF bundle gate does not pass")
    for name in FORMAL_INSTANCES:
        payload = json.loads((BUNDLES / name / "instance.json").read_text(encoding="utf-8"))
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
        if "bks_" in serialized or "reference_code" in serialized or "solution_sha256" in serialized:
            raise FormalRunError(f"search-facing bundle leaks reference metadata: {name}")
    return {
        "reference_manifest_sha256": sha256(REFERENCE_ROOT / "artifact_hashes.json"),
        "bundle_manifest_sha256": sha256(BUNDLES / "artifact_hashes.json"),
    }


def require_cpu_preflight() -> dict[str, Any]:
    verify_artifact_manifest(CPU_PREFLIGHT)
    decision = json.loads((CPU_PREFLIGHT / "decision.json").read_text(encoding="utf-8"))
    if decision != {
        "verdict": "PASS_SOLOMON_CPU_CONTRACT",
        "failures": [],
        "formal_search_authorized": False,
        "appledouble_count": 0,
    }:
        raise FormalRunError(f"CPU preflight v5 differs: {decision}")
    return json.loads(CPU_CONTRACT.read_text(encoding="utf-8"))


def require_e7_closeout() -> dict[str, Any]:
    hashes = {
        name: {
            "artifact_manifest_sha256": sha256(root / "artifact_hashes.json"),
            "artifacts": verify_artifact_manifest(root),
        }
        for name, root in E7_ROOTS.items()
    }
    formal = json.loads((E7_ROOTS["formal"] / "decision.json").read_text(encoding="utf-8"))
    if formal.get("verdict") not in {
        "E7_FORMAL_EVIDENCE_COMPLETE",
        "E7_FORMAL_EVIDENCE_COMPLETE_WITH_ARM_FAILURES",
    } or formal.get("failures"):
        raise FormalRunError("E7 formal decision does not pass the frozen completion rule")
    replay = json.loads((E7_ROOTS["replay"] / "decision.json").read_text(encoding="utf-8"))
    if replay.get("status") != "PASS_E7_28DAY_ZERO_SEARCH_CHARGING_REPLAY" or int(replay.get("route_search_evaluations", -1)) != 0:
        raise FormalRunError("E7 28-day replay does not pass")
    invariants = json.loads((E7_ROOTS["replay_invariants"] / "decision.json").read_text(encoding="utf-8"))
    expected_counts = {
        "full_task_count": 30,
        "task_day_row_count": 840,
        "window_violation_count": 0,
        "station_capacity_violation_count": 0,
        "route_hash_failure_count": 0,
        "energy_hash_failure_count": 0,
        "emissions_recalculation_failure_count": 0,
        "route_search_evaluations": 0,
    }
    if invariants.get("status") != "PASS_E7_REPLAY_INVARIANTS_AUDIT" or any(
        int(invariants.get(key, -1)) != value for key, value in expected_counts.items()
    ) or not all(invariants.get("checks", {}).values()):
        raise FormalRunError("E7 replay invariant audit does not pass exact counts")
    independent = json.loads((E7_ROOTS["independent_audit"] / "decision.json").read_text(encoding="utf-8"))
    empty_lists = (
        "formal_hash_failures",
        "replay_hash_failures",
        "replay_invariant_hash_failures",
        "replay_row_failures",
        "economic_closure_failures",
        "external_pause_timing_contamination",
    )
    if (
        independent.get("verdict") != "PASS_E7_MULTINETWORK_FORMAL_AND_REPLAY_INDEPENDENT_AUDIT"
        or not all(independent.get("checks", {}).values())
        or any(independent.get(key) for key in empty_lists)
    ):
        raise FormalRunError("E7 independent total audit does not pass")
    return hashes


def required_freeze_sources() -> tuple[str, ...]:
    package = REPO / "solver/src/setp_solver/algorithms/resetp_alns"
    paths = list(package.rglob("*.py"))
    paths.extend(
        [
            Path(__file__).resolve(),
            REPO / "solver/src/setp_solver/cost.py",
            REPO / "solver/src/setp_solver/check.py",
            REPO / "solver/src/setp_solver/prices.py",
            REPO / "solver/src/setp_solver/solution.py",
            REPO / "solver/src/setp_solver/search/bundle.py",
            REPO / "solver/src/setp_solver/search/evaluation.py",
            CPU_CONTRACT,
        ]
    )
    return tuple(sorted(str(path.relative_to(REPO)) for path in paths if path.is_file()))


def require_algorithm_freeze() -> dict[str, Any]:
    if not ALGORITHM_FREEZE.is_file():
        raise FormalRunError("algorithm freeze is missing; Solomon search remains unauthorized")
    freeze = json.loads(ALGORITHM_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("schema_version") != "resetp.e2.final-algorithm-freeze.v1":
        raise FormalRunError("algorithm freeze schema differs")
    if freeze.get("solomon_test_results_seen") is not False:
        raise FormalRunError("algorithm freeze was not declared before Solomon results")
    hashes = freeze.get("source_hashes")
    if not isinstance(hashes, dict) or set(hashes) != set(required_freeze_sources()):
        raise FormalRunError("algorithm freeze source closure is incomplete or has extras")
    for relative, expected in hashes.items():
        path = REPO / relative
        if not path.is_file() or sha256(path) != expected:
            raise FormalRunError(f"frozen source differs: {relative}")
    if freeze.get("entry_point") != "run_solomon_path_core":
        raise FormalRunError("frozen algorithm entry point differs")
    from setp_solver.algorithms.resetp_alns.kernel import winner  # noqa: PLC0415

    entry = getattr(winner, "run_solomon_path_core", None)
    if not callable(entry):
        raise FormalRunError("frozen algorithm entry point is not callable")
    signature = str(inspect.signature(entry))
    if canonical_sha256(signature) != freeze.get("entry_signature_sha256"):
        raise FormalRunError("frozen algorithm entry signature differs")
    if not freeze.get("git_commit") or not freeze.get("algorithm_version"):
        raise FormalRunError("algorithm freeze lacks version or Git commit")
    return freeze


def bundle_bounds(name: str) -> dict[str, float | int]:
    bundle = load_search_bundle(BUNDLES / name)
    matrix = np.asarray(bundle.instance.distance_matrix, dtype=float)
    customer_count = sum(str(node.node_type).lower() == "c" for node in bundle.instance.nodes)
    max_vehicles = int(bundle.instance.num_cv or 0)
    max_edge = float(np.max(matrix))
    distance_upper_bound = float((customer_count + max_vehicles) * max_edge)
    big_m = float(math.floor(distance_upper_bound) + 1)
    if not big_m > distance_upper_bound:
        raise FormalRunError(f"lexicographic big-M proof failed: {name}")
    return {
        "customer_count": customer_count,
        "max_vehicles": max_vehicles,
        "max_edge_distance": max_edge,
        "distance_upper_bound": distance_upper_bound,
        "big_m": big_m,
    }


def bundle_hashes(name: str) -> dict[str, str]:
    root = BUNDLES / name
    expected = ("instance.json", "distance_matrix.npy", "carbon_profile.csv")
    if any(not (root / item).is_file() for item in expected):
        raise FormalRunError(f"bundle is incomplete: {name}")
    return {item: sha256(root / item) for item in expected}


def pure_vrptw_recompute(solution: Mapping[str, Any], bundle_dir: Path) -> dict[str, Any]:
    """Independently recompute coverage, capacity, hard time windows and distance."""

    bundle = load_search_bundle(bundle_dir)
    instance = bundle.instance
    payload = json.loads((bundle_dir / "instance.json").read_text(encoding="utf-8"))
    capacity = float(payload["metadata"]["vehicle_capacity"])
    nodes = {node.node_id: node for node in instance.nodes}
    customers = {node.node_id for node in instance.nodes if str(node.node_type).lower() == "c"}
    depots = [node.node_id for node in instance.nodes if str(node.node_type).lower() == "d"]
    failures: list[str] = []
    if len(depots) != 1:
        return {"passed": False, "failures": [f"expected one depot: {depots}"]}
    depot = depots[0]
    visited: list[str] = []
    total_distance = 0.0
    routes = list(solution.get("routes", []))
    if len(routes) > int(instance.num_cv or 0):
        failures.append(f"vehicle cap exceeded: {len(routes)}>{instance.num_cv}")
    for route_index, route in enumerate(routes, start=1):
        sequence = [str(node) for node in route.get("node_sequence", [])]
        if len(sequence) < 3 or sequence[0] != depot or sequence[-1] != depot:
            failures.append(f"route {route_index} has invalid depot endpoints")
            continue
        if route.get("vehicle_type") not in (None, "cv"):
            failures.append(f"route {route_index} is not a conventional vehicle route")
        unknown = [node for node in sequence if node not in nodes]
        if unknown:
            failures.append(f"route {route_index} has unknown nodes: {unknown}")
            continue
        interior = sequence[1:-1]
        if depot in interior or any(node not in customers for node in interior):
            failures.append(f"route {route_index} has a non-customer interior node")
        visited.extend(interior)
        load = sum(float(nodes[node].demand) for node in interior)
        if load > capacity + TOL:
            failures.append(f"route {route_index} exceeds capacity: {load}>{capacity}")
        clock = float(nodes[depot].ready_time)
        for source, target in zip(sequence, sequence[1:]):
            travel = float(instance.distance(source, target))
            total_distance += travel
            arrival = clock + travel
            service_start = max(arrival, float(nodes[target].ready_time))
            if service_start > float(nodes[target].due_time) + TOL:
                failures.append(
                    f"route {route_index} violates {target}: {service_start}>{nodes[target].due_time}"
                )
            clock = service_start + float(nodes[target].service_time)
    if len(visited) != len(customers) or len(set(visited)) != len(customers) or set(visited) != customers:
        failures.append("customer coverage is not exactly once")
    return {
        "passed": not failures,
        "failures": failures,
        "route_count": len(routes),
        "distance_double": total_distance,
        "distance_rounded_2": round_half_up_2(total_distance),
        "visited_customer_count": len(visited),
        "expected_customer_count": len(customers),
    }


def solution_payload(solution: Any) -> dict[str, Any]:
    if isinstance(solution, Mapping):
        return json.loads(json.dumps(solution, ensure_ascii=False))
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [asdict(item) for item in solution.cross_site_services],
    }


def task_key(name: str, seed: int) -> str:
    return f"{name}__seed{seed}"


def build_search_tasks(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    tasks = [
        {
            "schema_version": TASK_SCHEMA,
            "task_key": task_key(name, seed),
            "instance": name,
            "class": contract["classes"][name],
            "seed": seed,
            "capacity": contract["capacities"][name],
            "eval_budget": contract["eval_budget"],
            "max_runtime_seconds": contract["max_runtime_seconds"],
            "big_m": contract["big_m_proofs"][name]["big_m"],
            "bundle_hashes": contract["bundle_hashes"][name],
            "algorithm_freeze_sha256": contract["algorithm_freeze_sha256"],
            "algorithm_version": contract["algorithm_version"],
        }
        for name in contract["instances"]
        for seed in contract["seeds"]
    ]
    forbidden = ("bks", "reference", "solution_sha256")
    for task in tasks:
        serialized = json.dumps(task, sort_keys=True).lower()
        if any(term in serialized for term in forbidden):
            raise FormalRunError(f"search task leaks post-run reference data: {task['task_key']}")
    if len(tasks) != 560 or len({task["task_key"] for task in tasks}) != 560:
        raise FormalRunError("formal task matrix must be exactly 56 instances x 10 seeds")
    return tasks


def verify_task_runtime_contract(task: Mapping[str, Any]) -> None:
    """Reject bundle or algorithm drift before/after every search task."""

    name = str(task["instance"])
    expected_bundle = task.get("bundle_hashes")
    if not isinstance(expected_bundle, Mapping) or bundle_hashes(name) != dict(expected_bundle):
        raise FormalRunError(f"worker bundle hashes differ: {name}")
    expected_freeze = str(task.get("algorithm_freeze_sha256", ""))
    if not expected_freeze or sha256(ALGORITHM_FREEZE) != expected_freeze:
        raise FormalRunError("worker algorithm-freeze hash differs")
    freeze = require_algorithm_freeze()
    if freeze.get("algorithm_version") != task.get("algorithm_version"):
        raise FormalRunError("worker algorithm version differs")


def run_task(task: Mapping[str, Any]) -> dict[str, Any]:
    """Run one task.  Unexpected exceptions escape and are never checkpointed."""

    verify_gold_environment()
    verify_task_runtime_contract(task)
    from setp_solver.algorithms.resetp_alns.kernel import winner  # noqa: PLC0415

    entry = getattr(winner, "run_solomon_path_core", None)
    if not callable(entry):
        raise FormalRunError("run_solomon_path_core is not callable")
    name = str(task["instance"])
    started_at = datetime.now(timezone.utc).isoformat()
    task_started = time.perf_counter_ns()
    process_started = time.process_time_ns()
    solver_started = time.perf_counter_ns()
    result = entry(
        BUNDLES / name,
        seed=int(task["seed"]),
        eval_budget=int(task["eval_budget"]),
        max_runtime_seconds=float(task["max_runtime_seconds"]),
        big_m=float(task["big_m"]),
        objective="lexicographic_vehicle_count_then_distance",
    )
    solver_elapsed = (time.perf_counter_ns() - solver_started) / 1e9
    process_cpu = (time.process_time_ns() - process_started) / 1e9
    verify_task_runtime_contract(task)
    required = {
        "best_solution",
        "best_lexicographic_score",
        "evaluations",
        "candidate_scores",
        "repair_delta_count",
        "feasible",
        "time_to_best_seconds",
    }
    missing = sorted(required - set(result))
    if missing:
        raise FormalRunError(f"algorithm result fields missing: {missing}")
    payload = solution_payload(result["best_solution"])
    recomputed = pure_vrptw_recompute(payload, BUNDLES / name)
    task_elapsed = (time.perf_counter_ns() - task_started) / 1e9
    route_count = int(recomputed["route_count"])
    distance_double = float(recomputed["distance_double"])
    lexicographic_score = float(task["big_m"]) * route_count + distance_double
    failures: list[str] = []
    if int(result["evaluations"]) != int(task["eval_budget"]):
        failures.append("INVALID_EVALUATION_COUNT")
    if int(result["candidate_scores"]) != int(task["eval_budget"]):
        failures.append("INVALID_CANDIDATE_SCORE_COUNT")
    if int(result["repair_delta_count"]) < 0:
        failures.append("INVALID_REPAIR_DELTA_COUNT")
    if not bool(result["feasible"]) or not recomputed["passed"]:
        failures.append("INFEASIBLE")
    if abs(float(result["best_lexicographic_score"]) - lexicographic_score) > TOL:
        failures.append("LEXICOGRAPHIC_OBJECTIVE_MISMATCH")
    first_best = float(result["time_to_best_seconds"])
    if first_best < 0 or first_best > solver_elapsed + TOL:
        failures.append("INVALID_TIME_TO_BEST")
    if solver_elapsed > float(task["max_runtime_seconds"]) + 1.0:
        failures.append("TIMEOUT")
    solution_feasible = bool(result["feasible"]) and bool(recomputed["passed"])
    return {
        "task_key": str(task["task_key"]),
        "instance": name,
        "class": str(task["class"]),
        "seed": int(task["seed"]),
        "algorithm_id": "TVCI-ALNS",
        "route_count": route_count,
        "distance_double": distance_double,
        "distance_rounded_2": float(recomputed["distance_rounded_2"]),
        "lexicographic_score": lexicographic_score,
        "eval_budget": int(task["eval_budget"]),
        "evaluations": int(result["evaluations"]),
        "candidate_scores": int(result["candidate_scores"]),
        "repair_delta_count": int(result["repair_delta_count"]),
        "process_cpu_seconds": process_cpu,
        "elapsed_seconds": solver_elapsed,
        "task_elapsed_seconds": task_elapsed,
        "time_to_best_seconds": first_best,
        "algorithm_reported_feasible": bool(result["feasible"]),
        "feasible": solution_feasible,
        "independent_recompute_pass": bool(recomputed["passed"]),
        "violation_count": len(recomputed["failures"]),
        "timeout": "TIMEOUT" in failures,
        "status": "OK" if not failures else "ALGORITHM_FAILURE",
        "failure_codes": failures,
        "solution_sha256": canonical_sha256(payload),
        "solution": payload,
        "independent_recomputation": recomputed,
        "operator_counts": result.get("operator_counts", {}),
        "score_counts": result.get("score_counts", {}),
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_contract() -> dict[str, Any]:
    verify_gold_environment()
    gate_hashes = require_bks_and_bundle_gates()
    cpu = require_cpu_preflight()
    e7_hashes = require_e7_closeout()
    freeze = require_algorithm_freeze()
    refs = read_references()
    body = {
        "schema_version": CONTRACT_SCHEMA,
        "instances": list(FORMAL_INSTANCES),
        "seeds": list(FORMAL_SEEDS),
        "eval_budget": FORMAL_EVAL_BUDGET,
        "workers": FORMAL_WORKERS,
        "max_runtime_seconds": FORMAL_MAX_RUNTIME_SECONDS,
        "environment": {
            "python": GOLD_PYTHON,
            "numpy": GOLD_NUMPY,
            "pythonhashseed": "0",
            "single_thread_environment": THREAD_ENV,
        },
        "objective": ["minimize_vehicle_count", "then_minimize_double_precision_total_distance"],
        "distance_rule": "double_precision_euclidean; round total half-up to two decimals for BKS comparison",
        "classes": {name: refs[name]["class"] for name in FORMAL_INSTANCES},
        "capacities": {name: refs[name]["capacity"] for name in FORMAL_INSTANCES},
        "bundle_hashes": {name: bundle_hashes(name) for name in FORMAL_INSTANCES},
        "big_m_proofs": {name: bundle_bounds(name) for name in FORMAL_INSTANCES},
        "reference_join_boundary": "BKS records remain parent-only and are joined after worker recomputation.",
        "gate_hashes": gate_hashes,
        "cpu_contract_sha256": sha256(CPU_CONTRACT),
        "cpu_contract": cpu,
        "cpu_reporting": cpu["literature_reporting_semantics"],
        "e7_closeout_hashes": e7_hashes,
        "algorithm_freeze_sha256": sha256(ALGORITHM_FREEZE),
        "algorithm_version": freeze["algorithm_version"],
        "algorithm_git_commit": freeze["git_commit"],
        "source_hashes": freeze["source_hashes"],
        "test_set_no_tuning": True,
        "retain_all_unfavorable_results": True,
    }
    return {**body, "contract_sha256": canonical_sha256(body)}


def ensure_contract(out: Path, requested: Mapping[str, Any]) -> dict[str, Any]:
    path = out / "contract.json"
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        comparable = {key: value for key, value in existing.items() if key not in {"created_at_utc", "git_head_at_start"}}
        if comparable != dict(requested):
            raise FormalRunError("existing formal contract differs")
        return existing
    if out.exists() and any(item for item in out.iterdir() if not item.name.startswith("._")):
        raise FormalRunError("output is non-empty without a matching formal contract")
    out.mkdir(parents=True, exist_ok=True)
    stored = {
        **requested,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head_at_start": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
    }
    atomic_json(path, stored)
    return stored


def checkpoint_path(root: Path, key: str) -> Path:
    return root / ".tasks" / "rows" / f"{key}.json"


def save_checkpoint(path: Path, contract_sha: str, task: Mapping[str, Any], row: Mapping[str, Any]) -> None:
    identity = {
        key: task[key]
        for key in (
            "schema_version", "task_key", "instance", "class", "seed", "eval_budget",
            "max_runtime_seconds", "big_m", "bundle_hashes", "algorithm_freeze_sha256",
            "algorithm_version",
        )
    }
    payload = {
        "schema_version": CHECKPOINT_SCHEMA,
        "contract_sha256": contract_sha,
        "task_identity": identity,
        "row": dict(row),
        "row_sha256": canonical_sha256(row),
    }
    atomic_json(path, payload)


def load_checkpoint(path: Path, contract_sha: str, task: Mapping[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CheckpointError(f"cannot read checkpoint {path}: {exc}") from exc
    identity = {
        key: task[key]
        for key in (
            "schema_version", "task_key", "instance", "class", "seed", "eval_budget",
            "max_runtime_seconds", "big_m", "bundle_hashes", "algorithm_freeze_sha256",
            "algorithm_version",
        )
    }
    if payload.get("schema_version") != CHECKPOINT_SCHEMA:
        raise CheckpointError(f"checkpoint schema differs: {path}")
    if payload.get("contract_sha256") != contract_sha or payload.get("task_identity") != identity:
        raise CheckpointError(f"checkpoint contract or identity differs: {path}")
    row = payload.get("row")
    if not isinstance(row, dict) or canonical_sha256(row) != payload.get("row_sha256"):
        raise CheckpointError(f"checkpoint row hash differs: {path}")
    if row.get("task_key") != task["task_key"] or int(row.get("seed", -1)) != int(task["seed"]):
        raise CheckpointError(f"checkpoint row identity differs: {path}")
    return row


def load_completed(out: Path, contract_sha: str, tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    root = out / ".tasks" / "rows"
    root.mkdir(parents=True, exist_ok=True)
    expected = {task["task_key"]: task for task in tasks}
    unexpected = sorted(path.stem for path in root.glob("*.json") if path.stem not in expected)
    if unexpected:
        raise CheckpointError(f"unexpected formal task checkpoints: {unexpected}")
    return {
        key: load_checkpoint(checkpoint_path(out, key), contract_sha, task)
        for key, task in expected.items()
        if checkpoint_path(out, key).is_file()
    }


def join_reference(row: Mapping[str, Any], reference: Mapping[str, Any], algorithm_version: str) -> dict[str, Any]:
    assessment = reference_assessment(
        int(row["route_count"]),
        float(row["distance_rounded_2"]),
        int(reference["bks_vehicle_count"]),
        float(reference["bks_distance_published_2dp"]),
    )
    return {
        **row,
        "algorithm_version": algorithm_version,
        "bks_vehicle_count": reference["bks_vehicle_count"],
        "bks_distance": reference["bks_distance_published_2dp"],
        **assessment,
    }


def valid_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in rows if row.get("status") == "OK" and bool(row.get("feasible"))]


def build_instance_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name in FORMAL_INSTANCES:
        group = [row for row in rows if row["instance"] == name]
        good = valid_rows(group)
        best = min(good, key=lambda row: lex_key(int(row["route_count"]), float(row["distance_double"]))) if good else None
        gap_rows = [row for row in good if bool(row["reached_bks_vehicle_count"])]
        out.append(
            {
                "instance": name,
                "class": group[0]["class"],
                "bks_vehicle_count": group[0]["bks_vehicle_count"],
                "bks_distance": group[0]["bks_distance"],
                "best_route_count": best["route_count"] if best else "",
                "best_distance": best["distance_rounded_2"] if best else "",
                "avg_route_count": fmean(float(row["route_count"]) for row in good) if good else "",
                "avg_distance": fmean(float(row["distance_double"]) for row in good) if good else "",
                "avg_gap_pct": fmean(float(row["distance_gap_pct"]) for row in gap_rows) if gap_rows else "",
                "gap_valid_runs": len(gap_rows),
                "avg_process_cpu_seconds": fmean(float(row["process_cpu_seconds"]) for row in group),
                "avg_elapsed_seconds": fmean(float(row["elapsed_seconds"]) for row in group),
                "avg_time_to_best_seconds": fmean(float(row["time_to_best_seconds"]) for row in group),
                "bks_hits": sum(bool(row["full_bks_hit"]) for row in good),
                "runs": len(group),
                "valid_runs": len(good),
                "failure_runs": len(group) - len(good),
            }
        )
    return out


def build_class_summary(instance_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for class_name in ("C1", "C2", "R1", "R2", "RC1", "RC2"):
        group = [row for row in instance_rows if row["class"] == class_name]
        completed = [row for row in group if row["best_route_count"] != ""]
        complete_class = len(completed) == len(group)
        output.append(
            {
                "class": class_name,
                "instance_count": len(group),
                "complete_instance_count": len(completed),
                "avg_best_route_count": fmean(float(row["best_route_count"]) for row in completed) if complete_class else "",
                "avg_best_distance": fmean(float(row["best_distance"]) for row in completed) if complete_class else "",
                "CNV": sum(int(row["best_route_count"]) for row in completed) if complete_class else "",
                "CTD": sum(float(row["best_distance"]) for row in completed) if complete_class else "",
                "avg_process_cpu_seconds": fmean(float(row["avg_process_cpu_seconds"]) for row in group),
                "avg_elapsed_seconds": fmean(float(row["avg_elapsed_seconds"]) for row in group),
                "avg_time_to_best_seconds": fmean(float(row["avg_time_to_best_seconds"]) for row in group),
                "Runs": sum(int(row["runs"]) for row in group),
                "valid_runs": sum(int(row["valid_runs"]) for row in group),
            }
        )
    return output


RAW_FIELDS = [
    "task_key", "instance", "class", "seed", "algorithm_id", "algorithm_version",
    "bks_vehicle_count", "bks_distance", "route_count", "vehicle_excess", "distance_double",
    "distance_rounded_2", "reached_bks_vehicle_count", "distance_gap_pct", "full_bks_hit",
    "bks_conflict_candidate", "lexicographic_score", "eval_budget", "evaluations", "candidate_scores",
    "repair_delta_count", "process_cpu_seconds", "elapsed_seconds", "task_elapsed_seconds",
    "time_to_best_seconds", "algorithm_reported_feasible", "feasible",
    "independent_recompute_pass", "violation_count", "timeout",
    "status", "failure_codes", "solution_sha256", "started_at_utc", "finished_at_utc",
]


def write_final_evidence(out: Path, contract: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    instance_summary = build_instance_summary(rows)
    class_summary = build_class_summary(instance_summary)
    failures = [row for row in rows if row["status"] != "OK"]
    conflicts = [row for row in rows if bool(row["bks_conflict_candidate"])]
    verdict = "FORMAL_COMPLETE" if not failures else "FORMAL_COMPLETE_WITH_ALGORITHM_FAILURES"
    metadata = {
        "schema_version": CONTRACT_SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_sha256": contract["contract_sha256"],
        "algorithm_version": contract["algorithm_version"],
        "task_count": len(rows),
        "instance_count": len(instance_summary),
        "runs_per_instance": len(FORMAL_SEEDS),
        "objective": contract["objective"],
        "cpu_field_definition": "process_cpu_seconds is this study's operational process-CPU measure",
        "elapsed_field_definition": "elapsed_seconds is solver wall-clock time",
        "time_to_best_definition": "time_to_best_seconds is wall-clock time to the final run-best solution",
        "machine": contract["cpu_contract"]["machine"],
        "runtime": contract["cpu_contract"]["runtime"],
        "workers": contract["workers"],
        "single_thread_per_solver": contract["cpu_contract"]["execution_rules"][
            "single_thread_per_solver"
        ],
        "test_set_used_for_tuning": False,
    }
    decision = {
        "verdict": verdict,
        "failures": [row["task_key"] for row in failures],
        "failure_count": len(failures),
        "bks_conflict_candidate_count": len(conflicts),
        "task_count": len(rows),
        "expected_task_count": 560,
        "all_unfavorable_results_retained": True,
    }
    atomic_json(out / "metadata.json", metadata)
    atomic_json(out / "cpu_contract_snapshot.json", contract["cpu_contract"])
    raw_rows = [
        {
            **row,
            "failure_codes": canonical_json(row.get("failure_codes", [])),
        }
        for row in rows
    ]
    atomic_csv(out / "raw_runs.csv", raw_rows, RAW_FIELDS)
    solution_records = [
        {
            "task_key": row["task_key"],
            "instance": row["instance"],
            "seed": row["seed"],
            "status": row["status"],
            "solution_sha256": row["solution_sha256"],
            "solution": row["solution"],
            "independent_recomputation": row["independent_recomputation"],
            "operator_counts": row.get("operator_counts", {}),
            "score_counts": row.get("score_counts", {}),
        }
        for row in rows
    ]
    atomic_text(
        out / "solutions.jsonl",
        "".join(canonical_json(record) + "\n" for record in solution_records),
    )
    atomic_csv(out / "instance_summary.csv", instance_summary, list(instance_summary[0]))
    atomic_csv(out / "class_summary.csv", class_summary, list(class_summary[0]))
    atomic_json(out / "decision.json", decision)
    atomic_json(
        out / "run_state.json",
        {
            "verdict": verdict,
            "completed_task_count": len(rows),
            "expected_task_count": 560,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    atomic_text(
        out / "report.md",
        "# Solomon 56例SINTEF正式基准\n\n"
        f"判定：`{verdict}`。按先最少车辆、再最短双精度总距离的SINTEF口径，"
        f"完整保留56例×10种子共{len(rows)}次运行；其中算法失败{len(failures)}次。"
        "BKS只在父进程独立复算后关联，未进入搜索任务。CPU/s为本文操作性定义的进程CPU时间，"
        "RT/s为墙钟时间；两者均不作为跨论文硬件速度优越性的直接证据。\n",
    )
    task_artifacts = {
        str(path.relative_to(out)): sha256(path)
        for path in sorted((out / ".tasks").rglob("*"))
        if path.is_file() and not path.name.startswith("._")
    }
    atomic_json(out / "task_artifact_hashes.json", task_artifacts)
    subprocess.run(["dot_clean", "-m", str(out)], check=True)
    sidecars = list(out.rglob("._*"))
    if sidecars:
        raise FormalRunError("AppleDouble remains after formal evidence cleanup")
    artifacts = {
        str(path.relative_to(out)): sha256(path)
        for path in sorted(out.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and ".tasks" not in path.parts
        and not path.name.startswith("._")
    }
    atomic_json(out / "artifact_hashes.json", artifacts)
    return decision


def worker_paths(out: Path, key: str, attempt_id: str) -> dict[str, Path]:
    root = out / ".tasks" / "attempts" / key / attempt_id
    return {
        "task": root / "task.json",
        "result": root / "result.json",
        "stdout": root / "stdout.log",
        "stderr": root / "stderr.log",
        "incident": root / "incident.json",
    }


def launch_worker(out: Path, task: Mapping[str, Any]) -> dict[str, Any]:
    attempt_id = f"{time.time_ns()}-{os.getpid()}"
    paths = worker_paths(out, str(task["task_key"]), attempt_id)
    atomic_json(paths["task"], dict(task))
    paths["stdout"].parent.mkdir(parents=True, exist_ok=True)
    stdout_handle = paths["stdout"].open("w", encoding="utf-8")
    stderr_handle = paths["stderr"].open("w", encoding="utf-8")
    command = [
        GOLD_PYTHON,
        str(Path(__file__).resolve()),
        "--worker-task",
        str(paths["task"]),
        "--worker-output",
        str(paths["result"]),
    ]
    try:
        process = subprocess.Popen(
            command,
            cwd=REPO,
            env=os.environ.copy(),
            stdout=stdout_handle,
            stderr=stderr_handle,
            start_new_session=True,
        )
    except BaseException:
        stdout_handle.close()
        stderr_handle.close()
        raise
    return {
        "task": dict(task),
        "paths": paths,
        "process": process,
        "stdout_handle": stdout_handle,
        "stderr_handle": stderr_handle,
        "started_ns": time.perf_counter_ns(),
    }


def close_worker_handles(record: Mapping[str, Any]) -> None:
    for key in ("stdout_handle", "stderr_handle"):
        handle = record.get(key)
        if handle is not None and not handle.closed:
            handle.close()


def stop_workers(active: Mapping[str, Mapping[str, Any]]) -> None:
    for record in active.values():
        process = record["process"]
        if process.poll() is None:
            if not record["paths"]["incident"].is_file():
                record_worker_incident(
                    record,
                    "PARENT_ABORTED_INFLIGHT",
                    "parent stopped all in-flight workers after a formal-run halt",
                )
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 2.0
    for record in active.values():
        process = record["process"]
        remaining = max(0.0, deadline - time.monotonic())
        if process.poll() is None:
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        close_worker_handles(record)


def record_worker_incident(record: Mapping[str, Any], code: str, detail: str) -> None:
    paths = record["paths"]
    process = record["process"]
    if paths["incident"].is_file():
        return
    atomic_json(
        paths["incident"],
        {
            "code": code,
            "detail": detail,
            "task": record["task"],
            "pid": process.pid,
            "returncode": process.poll(),
            "elapsed_seconds": (time.perf_counter_ns() - record["started_ns"]) / 1e9,
            "stdout_log": str(paths["stdout"].relative_to(out_root(paths["task"]))),
            "stderr_log": str(paths["stderr"].relative_to(out_root(paths["task"]))),
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )


def out_root(task_path: Path) -> Path:
    """Return the formal output root for a path beneath ``.tasks``."""

    for parent in task_path.parents:
        if parent.name == ".tasks":
            return parent.parent
    raise FormalRunError(f"worker IPC path is outside .tasks: {task_path}")


def collect_worker_result(record: Mapping[str, Any]) -> dict[str, Any]:
    process = record["process"]
    close_worker_handles(record)
    if process.returncode != 0:
        record_worker_incident(
            record,
            "WORKER_EXIT_NONZERO",
            f"worker exited with code {process.returncode}",
        )
        raise FormalRunError(
            f"worker failed for {record['task']['task_key']}; see {record['paths']['stderr']}"
        )
    path = record["paths"]["result"]
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        record_worker_incident(record, "WORKER_RESULT_INVALID", str(exc))
        raise FormalRunError(
            f"worker result is invalid for {record['task']['task_key']}: {exc}"
        ) from exc
    if row.get("task_key") != record["task"]["task_key"]:
        record_worker_incident(record, "WORKER_RESULT_IDENTITY_MISMATCH", "task key differs")
        raise FormalRunError(f"worker result identity differs: {record['task']['task_key']}")
    return row


def execute_pending_tasks(
    out: Path,
    contract: Mapping[str, Any],
    tasks: list[dict[str, Any]],
    completed: dict[str, dict[str, Any]],
    references: Mapping[str, Mapping[str, Any]],
) -> None:
    queue = deque(task for task in tasks if task["task_key"] not in completed)
    active: dict[str, dict[str, Any]] = {}
    previous_handlers: dict[int, Any] = {}
    interrupted_signum: int | None = None

    def handle_parent_signal(signum: int, _frame: Any) -> None:
        nonlocal interrupted_signum
        interrupted_signum = signum

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, handle_parent_signal)
    try:
        while queue or active:
            if interrupted_signum is not None:
                for record in active.values():
                    record_worker_incident(
                        record,
                        "PARENT_SIGNAL_ABORT",
                        f"parent received signal {interrupted_signum}",
                    )
                raise FormalRunError(
                    f"formal runner interrupted by signal {interrupted_signum}"
                )
            while queue and len(active) < FORMAL_WORKERS:
                task = queue.popleft()
                key = str(task["task_key"])
                old_mask = signal.pthread_sigmask(
                    signal.SIG_BLOCK,
                    {signal.SIGINT, signal.SIGTERM},
                )
                try:
                    active[key] = launch_worker(out, task)
                finally:
                    signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
                if interrupted_signum is not None:
                    break
            progressed = False
            for key, record in list(active.items()):
                process = record["process"]
                elapsed = (time.perf_counter_ns() - record["started_ns"]) / 1e9
                hard_limit = float(record["task"]["max_runtime_seconds"]) + HARD_TIMEOUT_GRACE_SECONDS
                if process.poll() is None and elapsed > hard_limit:
                    record_worker_incident(
                        record,
                        "WORKER_HARD_TIMEOUT",
                        f"elapsed {elapsed:.3f}s exceeded hard limit {hard_limit:.3f}s",
                    )
                    raise FormalRunError(f"worker hard timeout: {key}")
                if process.poll() is None:
                    continue
                row = collect_worker_result(record)
                del active[key]
                progressed = True
                task = record["task"]
                verify_task_runtime_contract(task)
                joined = join_reference(
                    row,
                    references[str(task["instance"])],
                    str(contract["algorithm_version"]),
                )
                save_checkpoint(
                    checkpoint_path(out, key),
                    str(contract["contract_sha256"]),
                    task,
                    joined,
                )
                completed[key] = joined
                if joined["bks_conflict_candidate"]:
                    raise BKSConflictError(
                        f"BKS conflict candidate preserved at {checkpoint_path(out, key)}"
                    )
            if active and not progressed:
                time.sleep(WORKER_POLL_SECONDS)
    except BaseException:
        stop_workers(active)
        raise
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--worker-task", type=Path)
    parser.add_argument("--worker-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    worker_task = getattr(args, "worker_task", None)
    worker_output = getattr(args, "worker_output", None)
    if worker_task is not None or worker_output is not None:
        if worker_task is None or worker_output is None:
            raise FormalRunError("worker mode requires both task and output paths")
        task = json.loads(worker_task.read_text(encoding="utf-8"))
        row = run_task(task)
        atomic_json(worker_output, row)
        return 0
    contract_request = build_contract()
    tasks = build_search_tasks(contract_request)
    if args.preflight_only:
        print(json.dumps({"status": "PASS_FORMAL_PREFLIGHT", "task_count": len(tasks)}, ensure_ascii=False))
        return 0
    contract = ensure_contract(args.output, contract_request)
    completed = load_completed(args.output, contract["contract_sha256"], tasks)
    conflicts = [key for key, row in completed.items() if bool(row.get("bks_conflict_candidate"))]
    if conflicts:
        raise BKSConflictError(f"existing BKS conflict checkpoints require independent audit: {conflicts}")
    refs = read_references()
    try:
        execute_pending_tasks(args.output, contract, tasks, completed, refs)
    except BaseException:
        atomic_json(
            args.output / "run_state.json",
            {
                "verdict": "INCOMPLETE_INFRASTRUCTURE_HALT",
                "completed_task_count": len(completed),
                "expected_task_count": len(tasks),
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
        raise
    ordered = [completed[task["task_key"]] for task in tasks]
    decision = write_final_evidence(args.output, contract, ordered)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
