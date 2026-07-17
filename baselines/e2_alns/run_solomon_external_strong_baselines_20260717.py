#!/usr/bin/env python3
"""Sealed external strong-baseline interface for SINTEF Solomon.

The default mode is preflight only and performs no search.  Formal execution
requires an explicit CLI authorisation, a post-E7 attestation, and a separately
created immutable tool freeze.  Search tasks never contain BKS values.
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping

import numpy as np


REPO = Path(__file__).resolve().parents[2]
BUNDLES = REPO / "baselines/e2_alns/solomon_sintef_formal_bundles_20260717_v3"
REFERENCES = REPO / "baselines/e2_alns/e2_solomon_sintef_bks_audit_20260717/raw_runs.csv"
E7_ATTESTATION = REPO / "baselines/e7_dynamic/e7_steps_1_to_6_attestation_20260717.json"
E7_ATTESTATION_BUILDER = REPO / "baselines/e7_dynamic/build_e7_steps_1_to_6_attestation_20260717.py"
TOOL_FREEZE = REPO / "baselines/e2_alns/final_external_baseline_freeze/external_baseline_freeze.json"
DEFAULT_OUT = REPO / "baselines/e2_alns/e2_solomon_external_strong_baselines_20260717"
PREFLIGHT_PATH = REPO / "baselines/e2_alns/audit_solomon_external_strong_baseline_preflight_20260717.py"
FORMAL_PATH = REPO / "baselines/e2_alns/run_solomon_sintef_formal_20260717.py"
AUTHORIZATION = "AUTHORIZE_SOLOMON_EXTERNAL_STRONG_BASELINE_SEARCH"
SCHEMA = "resetp.e2.solomon-external-strong-baseline.v1"
TASK_SCHEMA = "resetp.e2.solomon-external-task.v1"
CHECKPOINT_SCHEMA = "resetp.e2.solomon-external-task-checkpoint.v1"
ATTEMPT_MANIFEST_SCHEMA = "resetp.e2.solomon-external-task-artifacts.v1"
FORMAL_SEEDS = tuple(range(1, 11))
EXPECTED_WORKERS = 4
HARD_TIMEOUT_OVERHEAD_SECONDS = 30.0
HARD_TIMEOUT_GRACE_SECONDS = 5.0
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}
_ACTIVE_PROCESS_LOCK = threading.Lock()
_ACTIVE_PROCESSES: dict[int, subprocess.Popen[Any]] = {}
_STOP_REQUESTED = threading.Event()
_STOP_SIGNAL: int | None = None


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PREFLIGHT = _load_module("solomon_external_preflight", PREFLIGHT_PATH)
FORMAL = _load_module("solomon_sintef_formal_helpers", FORMAL_PATH)


class ExternalBaselineError(RuntimeError):
    """A formal contract, tooling, or infrastructure failure."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
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
    atomic_text(path, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")


def atomic_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows({field: row.get(field, "") for field in fields} for row in rows)
    atomic_text(path, buffer.getvalue())


def verify_hash_map(records: Mapping[str, str]) -> None:
    if not records:
        raise ExternalBaselineError("frozen source hash map is empty")
    for raw_path, expected in records.items():
        path = Path(raw_path)
        if not path.is_absolute():
            path = REPO / path
        if not path.is_file() or sha256(path) != expected:
            raise ExternalBaselineError(f"frozen source differs: {raw_path}")


def verify_bundle_hashes(task: Mapping[str, Any]) -> None:
    name = str(task["instance"])
    hashes = task.get("bundle_hashes", {})
    if not hashes:
        raise ExternalBaselineError(f"bundle hash map is empty: {name}")
    for relative, expected in hashes.items():
        path = BUNDLES / name / relative
        if not path.is_file() or sha256(path) != expected:
            raise ExternalBaselineError(f"bundle hash differs: {name}/{relative}")


def verify_contract_payload(contract: Mapping[str, Any], expected_sha256: str | None = None) -> str:
    body = dict(contract)
    recorded = str(body.pop("contract_sha256", ""))
    actual = canonical_sha256(body)
    if not recorded or recorded != actual:
        raise ExternalBaselineError("contract payload hash differs")
    if expected_sha256 is not None and actual != expected_sha256:
        raise ExternalBaselineError("contract identity differs from task/checkpoint")
    return actual


def verify_runtime_freeze(
    task: Mapping[str, Any],
    contract_path: Path,
    expected_contract_sha256: str | None = None,
) -> dict[str, Any]:
    """Fail closed if any formal tool, interface, bundle, or contract drifts.

    This deliberately does not parse the E7 attestation or inspect E7 result
    directories.  It only recomputes the attestation file digest frozen in the
    immutable external-baseline contract.
    """

    if not contract_path.is_file():
        raise ExternalBaselineError("formal contract file is missing")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    expected = expected_contract_sha256 or str(task.get("contract_sha256", ""))
    if not expected:
        raise ExternalBaselineError("task lacks a frozen contract identity")
    verify_contract_payload(contract, expected)
    if task.get("contract_sha256") != expected:
        raise ExternalBaselineError("task contract identity differs")
    if not E7_ATTESTATION.is_file() or sha256(E7_ATTESTATION) != contract.get("e7_attestation_sha256"):
        raise ExternalBaselineError("sealed E7 attestation differs at runtime")
    if not TOOL_FREEZE.is_file() or sha256(TOOL_FREEZE) != contract.get("tool_freeze_sha256"):
        raise ExternalBaselineError("tool-freeze file differs at runtime")
    verify_hash_map(contract.get("tool_source_hashes", {}))
    verify_hash_map(contract.get("interface_source_hashes", {}))
    verify_bundle_hashes(task)
    return contract


def require_e7_attestation() -> dict[str, Any]:
    if not E7_ATTESTATION.is_file():
        raise ExternalBaselineError("E7 steps 1-6 attestation is missing")
    payload = json.loads(E7_ATTESTATION.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "resetp.e7.steps-1-to-6-attestation.v1":
        raise ExternalBaselineError("E7 attestation schema differs")
    if payload.get("steps_1_to_6_complete") is not True or payload.get("search_version_closed") is not True:
        raise ExternalBaselineError("E7 attestation does not close steps 1-6")
    builder_hash = sha256(E7_ATTESTATION_BUILDER) if E7_ATTESTATION_BUILDER.is_file() else ""
    builder_key = str(E7_ATTESTATION_BUILDER.relative_to(REPO))
    if (
        not builder_hash
        or payload.get("builder_sha256") != builder_hash
        or payload.get("evidence_hashes", {}).get(builder_key) != builder_hash
    ):
        raise ExternalBaselineError("E7 attestation is not bound to the frozen zero-search builder")
    verify_hash_map(payload.get("evidence_hashes", {}))
    return payload


def require_tool_freeze() -> dict[str, Any]:
    if not TOOL_FREEZE.is_file():
        raise ExternalBaselineError("external baseline tool freeze is missing")
    payload = json.loads(TOOL_FREEZE.read_text(encoding="utf-8"))
    body = dict(payload)
    recorded_hash = str(body.pop("freeze_payload_sha256", ""))
    if not recorded_hash or recorded_hash != canonical_sha256(body):
        raise ExternalBaselineError("external baseline freeze payload hash differs")
    if payload.get("schema_version") != "resetp.e2.external-baseline-freeze.v1":
        raise ExternalBaselineError("external baseline freeze schema differs")
    if payload.get("formal_search_authorized") is not True:
        raise ExternalBaselineError("external baseline freeze does not authorize formal search")
    if payload.get("baseline_id") != "PyVRP":
        raise ExternalBaselineError("v1 runner supports only the frozen PyVRP VRPTW adapter")
    if int(payload.get("workers", -1)) != EXPECTED_WORKERS or payload.get("single_thread_per_solver") is not True:
        raise ExternalBaselineError("external baseline worker/thread contract differs")
    if tuple(payload.get("seeds", [])) != FORMAL_SEEDS:
        raise ExternalBaselineError("external baseline seeds differ")
    if float(payload.get("wall_clock_seconds", 0)) <= 0:
        raise ExternalBaselineError("wall-clock limit must be positive")
    if int(payload.get("distance_scale", 0)) < 1000:
        raise ExternalBaselineError("distance scale is too coarse for the SINTEF double-precision proxy")
    if payload.get("time_to_best_extractor_verified") is not True:
        raise ExternalBaselineError("PyVRP time-to-best extractor has not passed the frozen API probe")
    verify_hash_map(payload.get("tool_source_hashes", {}))
    verify_hash_map(payload.get("interface_source_hashes", {}))
    found = PREFLIGHT.discover_pyvrp()
    if not found["available"] or found["version"] != payload.get("version"):
        raise ExternalBaselineError("installed PyVRP version differs from freeze")
    if str(Path(sys.executable).resolve()) != str(Path(payload.get("python_executable", "")).resolve()):
        raise ExternalBaselineError("Python executable differs from external baseline freeze")
    return payload


def formal_instances() -> tuple[str, ...]:
    names = tuple(sorted(path.name for path in BUNDLES.iterdir() if path.is_dir() and (path / "instance.json").is_file()))
    if len(names) != 56:
        raise ExternalBaselineError(f"expected 56 BKS-free bundles, found {len(names)}")
    return names


def instance_class(name: str) -> str:
    match = re.fullmatch(r"(RC|C|R)([12])\d{2}", name)
    if not match:
        raise ExternalBaselineError(f"unexpected Solomon instance name: {name}")
    return f"{match.group(1)}{match.group(2)}"


def proved_fixed_vehicle_cost(
    matrix: np.ndarray,
    customer_count: int,
    max_vehicles: int,
    scale: int,
) -> dict[str, int]:
    """Return an integer fixed cost strictly above every feasible route distance.

    The proof is expressed in the same integer arc metric passed to PyVRP.
    Rounding every arc separately can add 0.5 per arc, so scaling a floating
    aggregate is not a valid bound.  A solution serving every customer once
    has at most ``customer_count + max_vehicles`` arcs; each integer arc is at
    most the largest value in the frozen, individually scaled matrix.
    """

    if customer_count <= 0 or max_vehicles <= 0 or scale <= 0:
        raise ExternalBaselineError("lexicographic fixed-cost dimensions must be positive")
    max_integer_arc = max(_scaled(float(value), scale) for value in matrix.flat)
    max_route_arcs = customer_count + max_vehicles
    distance_upper = max_route_arcs * max_integer_arc
    return {
        "max_integer_arc_scaled": max_integer_arc,
        "max_route_arcs": max_route_arcs,
        "all_route_distance_upper_scaled": distance_upper,
        "fixed_vehicle_cost_scaled": distance_upper + 1,
    }


def build_tasks(freeze: Mapping[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for name in formal_instances():
        instance = json.loads((BUNDLES / name / "instance.json").read_text(encoding="utf-8"))
        if any("bks" in key.lower() for key in instance.get("metadata", {})):
            raise ExternalBaselineError(f"search bundle leaks BKS fields: {name}")
        matrix = np.load(BUNDLES / name / "distance_matrix.npy", allow_pickle=False)
        max_vehicles = int(instance["metadata"]["num_cv"])
        scale = int(freeze["distance_scale"])
        fixed_cost_proof = proved_fixed_vehicle_cost(
            matrix,
            len(instance["nodes"]) - 1,
            max_vehicles,
            scale,
        )
        for seed in FORMAL_SEEDS:
            tasks.append(
                {
                    "schema_version": TASK_SCHEMA,
                    "run_mode": "FORMAL_AUTHORIZED",
                    "task_key": f"{name}__seed{seed}",
                    "instance": name,
                    "class": instance_class(name),
                    "seed": seed,
                    "baseline_id": "PyVRP",
                    "wall_clock_seconds": float(freeze["wall_clock_seconds"]),
                    "distance_scale": scale,
                    **fixed_cost_proof,
                    "bundle_hashes": FORMAL.bundle_hashes(name),
                }
            )
    if len(tasks) != 560:
        raise ExternalBaselineError(f"expected 560 tasks, found {len(tasks)}")
    if any("bks" in json.dumps(task, sort_keys=True).lower() for task in tasks):
        raise ExternalBaselineError("BKS leaked into external search tasks")
    return tasks


def _scaled(value: float, scale: int) -> int:
    return int(Decimal(str(value * scale)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def build_pyvrp_model(bundle: Path, scale: int, fixed_cost: int) -> Any:
    from pyvrp import Model  # imported only inside an authorised worker

    raw = json.loads((bundle / "instance.json").read_text(encoding="utf-8"))
    nodes = raw["nodes"]
    distances = np.load(bundle / "distance_matrix.npy", allow_pickle=False)
    model = Model()
    has_location_api = hasattr(model, "add_location")
    client_handles: list[Any] = []
    if has_location_api:
        locations = [model.add_location(float(node["x"]), float(node["y"]), name=node["node_id"]) for node in nodes]
        depot = model.add_depot(
            locations[0],
            tw_early=_scaled(float(nodes[0]["ready_time"]), scale),
            tw_late=_scaled(float(nodes[0]["due_time"]), scale),
            name=nodes[0]["node_id"],
        )
        for idx, node in enumerate(nodes[1:], start=1):
            client_handles.append(model.add_client(
                locations[idx],
                delivery=[int(node["demand"])],
                service_duration=_scaled(float(node["service_time"]), scale),
                tw_early=_scaled(float(node["ready_time"]), scale),
                tw_late=_scaled(float(node["due_time"]), scale),
                name=node["node_id"],
            ))
    else:
        depot = model.add_depot(
            x=float(nodes[0]["x"]),
            y=float(nodes[0]["y"]),
            tw_early=_scaled(float(nodes[0]["ready_time"]), scale),
            tw_late=_scaled(float(nodes[0]["due_time"]), scale),
            name=nodes[0]["node_id"],
        )
        for node in nodes[1:]:
            client_handles.append(model.add_client(
                x=float(node["x"]),
                y=float(node["y"]),
                delivery=int(node["demand"]),
                service_duration=_scaled(float(node["service_time"]), scale),
                tw_early=_scaled(float(node["ready_time"]), scale),
                tw_late=_scaled(float(node["due_time"]), scale),
                name=node["node_id"],
            ))
        locations = [depot, *client_handles]

    capacity: Any = [int(raw["metadata"]["vehicle_capacity"])] if has_location_api else int(raw["metadata"]["vehicle_capacity"])
    model.add_vehicle_type(
        num_available=int(raw["metadata"]["num_cv"]),
        capacity=capacity,
        start_depot=depot,
        end_depot=depot,
        fixed_cost=int(fixed_cost),
    )
    for i, frm in enumerate(locations):
        for j, to in enumerate(locations):
            value = _scaled(float(distances[i, j]), scale)
            model.add_edge(frm, to, distance=value, duration=value)
    return model


def extract_routes(solution: Any) -> list[list[int]]:
    routes: list[list[int]] = []
    for route in solution.routes():
        visits = getattr(route, "visits", None)
        if callable(visits):
            routes.append([int(value) for value in visits()])
            continue
        customers: list[int] = []
        for activity in route:
            if activity.is_client():
                customers.append(int(activity.idx) + 1)
        routes.append(customers)
    return routes


def extract_time_to_best(result: Any) -> float:
    """Extract the first timestamp that reaches the final best feasible cost.

    PyVRP statistics have changed across releases, so the exact supported
    layout must be frozen by an API probe.  This function accepts only the two
    documented historical shapes and fails closed for an unknown layout.
    """

    final_cost = float(result.cost())
    candidates: list[tuple[float, float]] = []
    statistics = result.stats
    # PyVRP 0.13.x stores per-iteration elapsed durations separately from
    # data points.  Their cumulative sum is the timestamp on the same
    # perf_counter clock used by the main search loop (Statistics.collect).
    if hasattr(statistics, "data") and hasattr(statistics, "runtimes"):
        data = list(statistics.data)
        runtimes = [float(value) for value in statistics.runtimes]
        if len(data) != len(runtimes) or int(getattr(statistics, "num_iterations", -1)) != len(data):
            raise ExternalBaselineError("PyVRP statistics data/runtime lengths differ")
        elapsed = 0.0
        for datum, runtime_delta in zip(data, runtimes, strict=True):
            if runtime_delta < 0.0:
                raise ExternalBaselineError("PyVRP statistics contain a negative runtime delta")
            elapsed += runtime_delta
            if not hasattr(datum, "best_cost") or not hasattr(datum, "best_feas"):
                raise ExternalBaselineError("PyVRP 0.13 statistics lack best-cost fields")
            if bool(datum.best_feas):
                candidates.append((elapsed, float(datum.best_cost)))
    else:
        candidates.extend(_historical_time_to_best_candidates(statistics))
    matches = [runtime for runtime, cost in candidates if cost <= final_cost + 1e-9]
    if not matches:
        raise ExternalBaselineError("PyVRP statistics never record the final best feasible cost")
    return min(matches)


def _historical_time_to_best_candidates(statistics: Any) -> list[tuple[float, float]]:
    """Parse explicitly supported pre-0.13 statistics layouts."""

    candidates: list[tuple[float, float]] = []
    for datum in statistics:
        runtime = next(
            (float(getattr(datum, name)) for name in ("runtime", "time", "elapsed") if hasattr(datum, name)),
            None,
        )
        if runtime is None:
            raise ExternalBaselineError("PyVRP statistics datum lacks a runtime field")
        feasible_cost: float | None = None
        for container_name, cost_name in (
            ("feas", "best"),
            ("best_feas", "cost"),
            ("best", "cost"),
        ):
            container = getattr(datum, container_name, None)
            if container is not None and hasattr(container, cost_name):
                feasible_cost = float(getattr(container, cost_name))
                break
        if feasible_cost is None:
            direct = getattr(datum, "best_feas", None)
            if isinstance(direct, (int, float)):
                feasible_cost = float(direct)
        if feasible_cost is None:
            raise ExternalBaselineError("PyVRP statistics datum lacks a supported best-feasible cost field")
        candidates.append((runtime, feasible_cost))
    return candidates


def run_pyvrp_worker(task: Mapping[str, Any]) -> dict[str, Any]:
    if task.get("schema_version") != TASK_SCHEMA or task.get("run_mode") != "FORMAL_AUTHORIZED":
        raise ExternalBaselineError("worker task is not formally authorised")
    from pyvrp.stop import MaxRuntime

    name = str(task["instance"])
    verify_bundle_hashes(task)
    model = build_pyvrp_model(
        BUNDLES / name,
        int(task["distance_scale"]),
        int(task["fixed_vehicle_cost_scaled"]),
    )
    process_start = time.process_time_ns()
    wall_start = time.perf_counter_ns()
    result = model.solve(
        stop=MaxRuntime(float(task["wall_clock_seconds"])),
        seed=int(task["seed"]),
        collect_stats=True,
        display=False,
    )
    elapsed = (time.perf_counter_ns() - wall_start) / 1e9
    process_cpu = (time.process_time_ns() - process_start) / 1e9
    time_to_best = extract_time_to_best(result)
    routes = extract_routes(result.best)
    solution = {
        "routes": [
            {
                "node_sequence": ["D0", *(f"C{customer}" for customer in route), "D0"],
                "vehicle_type": "cv",
            }
            for route in routes
        ]
    }
    recomputed = FORMAL.pure_vrptw_recompute(solution, BUNDLES / name)
    return {
        "task_key": task["task_key"],
        "instance": name,
        "class": task["class"],
        "seed": task["seed"],
        "baseline_id": "PyVRP",
        "status": "OK" if recomputed["passed"] else "ALGORITHM_FAILURE",
        "failure_codes": [] if recomputed["passed"] else ["INDEPENDENT_RECOMPUTE_FAILED"],
        "route_count": recomputed["route_count"],
        "distance_double": recomputed["distance_double"],
        "distance_rounded_2": recomputed["distance_rounded_2"],
        "process_cpu_seconds": process_cpu,
        "elapsed_seconds": elapsed,
        "time_to_best_seconds": time_to_best,
        "feasible": recomputed["passed"],
        "routes": routes,
        "solution_sha256": canonical_sha256(solution),
        "independent_recomputation": recomputed,
    }


def worker_main(task_path: Path, output: Path, contract_path: Path) -> int:
    task = json.loads(task_path.read_text(encoding="utf-8"))
    verify_runtime_freeze(task, contract_path)
    row = run_pyvrp_worker(task)
    verify_runtime_freeze(task, contract_path)
    atomic_json(output, row)
    return 0


def build_contract(freeze: Mapping[str, Any], e7: Mapping[str, Any]) -> dict[str, Any]:
    cpu_metadata_path = PREFLIGHT.CPU_PREFLIGHT / "metadata.json"
    if not cpu_metadata_path.is_file():
        raise ExternalBaselineError("CPU preflight metadata is missing")
    cpu_metadata = json.loads(cpu_metadata_path.read_text(encoding="utf-8"))
    body = {
        "schema_version": SCHEMA,
        "baseline_id": freeze["baseline_id"],
        "baseline_version": freeze["version"],
        "python_executable": freeze["python_executable"],
        "workers": EXPECTED_WORKERS,
        "single_thread_environment": THREAD_ENV,
        "wall_clock_seconds": freeze["wall_clock_seconds"],
        "hard_timeout_overhead_seconds": HARD_TIMEOUT_OVERHEAD_SECONDS,
        "process_group_timeout_policy": f"start_new_session; SIGTERM; wait {HARD_TIMEOUT_GRACE_SECONDS}s; SIGKILL",
        "seeds": list(FORMAL_SEEDS),
        "instances": list(formal_instances()),
        "distance_scale": freeze["distance_scale"],
        "objective_adapter": "scaled double-precision distance plus proved fixed vehicle cost; independent exact recomputation after search",
        "fairness_axis": "same-machine single-thread wall-clock",
        "internal_eval_budget_axis_excluded": True,
        "e7_attestation_sha256": sha256(E7_ATTESTATION),
        "e7_source_version": e7.get("search_version"),
        "tool_freeze_sha256": sha256(TOOL_FREEZE),
        "tool_source_hashes": freeze["tool_source_hashes"],
        "interface_source_hashes": freeze["interface_source_hashes"],
        "cpu_preflight_metadata_sha256": sha256(cpu_metadata_path),
        "machine": cpu_metadata["actual_hardware"],
        "runtime": cpu_metadata["actual_runtime"],
        "command_template": [
            freeze["python_executable"],
            str(Path(__file__).resolve()),
            "--worker-task",
            "<BKS_FREE_TASK_JSON>",
            "--worker-output",
            "<RESULT_JSON>",
            "--worker-contract",
            "<FROZEN_CONTRACT_JSON>",
        ],
        "retain_all_failures": True,
    }
    return {**body, "contract_sha256": canonical_sha256(body)}


def ensure_output(out: Path, contract: Mapping[str, Any]) -> Path:
    """Create a new run directory or resume only the identical contract."""

    out.mkdir(parents=True, exist_ok=True)
    contract_path = out / "contract.json"
    substantive = [item for item in out.iterdir() if not item.name.startswith("._")]
    if not substantive:
        atomic_json(contract_path, contract)
    else:
        if not contract_path.is_file():
            raise ExternalBaselineError("non-empty output lacks a formal contract")
        existing = json.loads(contract_path.read_text(encoding="utf-8"))
        verify_contract_payload(existing, str(contract["contract_sha256"]))
        if canonical_sha256(existing) != canonical_sha256(contract):
            raise ExternalBaselineError("existing output belongs to a different formal contract")
    for relative in (".tasks/attempts", ".tasks/checkpoints"):
        (out / relative).mkdir(parents=True, exist_ok=True)
    return contract_path


def _failure_result(
    task: Mapping[str, Any],
    status: str,
    failure_codes: list[str],
    elapsed_seconds: float,
) -> dict[str, Any]:
    if status not in {"INFRASTRUCTURE_TIMEOUT", "INFRASTRUCTURE_FAILURE"}:
        raise ExternalBaselineError(f"unsupported parent failure status: {status}")
    return {
        "task_key": task["task_key"], "instance": task["instance"], "class": task["class"],
        "seed": task["seed"], "baseline_id": task["baseline_id"], "status": status,
        "failure_codes": failure_codes, "route_count": "", "distance_double": "",
        "distance_rounded_2": "", "process_cpu_seconds": "", "elapsed_seconds": elapsed_seconds,
        "time_to_best_seconds": "", "feasible": False, "solution_sha256": "",
        "routes": [], "independent_recomputation": {},
        "parent_validation": "PARENT_INFRASTRUCTURE_FAILURE_SEMANTICS_VALIDATED",
    }


def _solution_from_routes(routes: Any) -> dict[str, Any]:
    if not isinstance(routes, list) or any(
        not isinstance(route, list) or any(not isinstance(customer, int) or isinstance(customer, bool) for customer in route)
        for route in routes
    ):
        raise ExternalBaselineError("worker routes have an invalid shape")
    return {
        "routes": [
            {
                "node_sequence": ["D0", *(f"C{customer}" for customer in route), "D0"],
                "vehicle_type": "cv",
            }
            for route in routes
        ]
    }


def validate_result_identity_and_semantics(
    task: Mapping[str, Any],
    row: Mapping[str, Any],
) -> dict[str, Any]:
    """Independently validate worker identity, solution hash, and failure semantics."""

    identity = {
        "task_key": task["task_key"],
        "instance": task["instance"],
        "class": task["class"],
        "seed": task["seed"],
        "baseline_id": task["baseline_id"],
    }
    if any(row.get(key) != value for key, value in identity.items()):
        raise ExternalBaselineError(f"worker result identity differs: {task['task_key']}")
    status = row.get("status")
    codes = row.get("failure_codes")
    if not isinstance(codes, list) or any(not isinstance(code, str) for code in codes):
        raise ExternalBaselineError("failure_codes must be a list of strings")
    if status in {"INFRASTRUCTURE_TIMEOUT", "INFRASTRUCTURE_FAILURE"}:
        if row.get("feasible") is not False or row.get("solution_sha256") not in {"", None}:
            raise ExternalBaselineError("infrastructure failure contains solution-success semantics")
        if row.get("routes") not in (None, []):
            raise ExternalBaselineError("infrastructure failure unexpectedly contains routes")
        if row.get("independent_recomputation") not in (None, {}):
            raise ExternalBaselineError("infrastructure failure unexpectedly contains recomputation evidence")
        if any(row.get(key) not in {"", None} for key in ("route_count", "distance_double", "distance_rounded_2")):
            raise ExternalBaselineError("infrastructure failure unexpectedly contains objective values")
        if status == "INFRASTRUCTURE_TIMEOUT" and codes != ["HARD_WALL_TIMEOUT"]:
            raise ExternalBaselineError("hard timeout failure semantics differ")
        if status == "INFRASTRUCTURE_FAILURE" and (
            len(codes) != 1
            or re.fullmatch(r"(?:WORKER_EXIT|WORKER_LAUNCH_ERRNO)_-?\d+", codes[0]) is None
        ):
            raise ExternalBaselineError("worker-exit failure semantics differ")
        return dict(row)
    if status not in {"OK", "ALGORITHM_FAILURE"}:
        raise ExternalBaselineError(f"unsupported worker status: {status}")
    solution = _solution_from_routes(row.get("routes"))
    solution_hash = canonical_sha256(solution)
    if row.get("solution_sha256") != solution_hash:
        raise ExternalBaselineError("worker solution hash differs from routes")
    recomputed = FORMAL.pure_vrptw_recompute(solution, BUNDLES / str(task["instance"]))
    if canonical_sha256(row.get("independent_recomputation", {})) != canonical_sha256(recomputed):
        raise ExternalBaselineError("worker recomputation differs from parent recomputation")
    for key in ("route_count", "distance_double", "distance_rounded_2"):
        worker_value = row.get(key)
        parent_value = recomputed[key]
        if isinstance(parent_value, float):
            if not isinstance(worker_value, (int, float)) or not math.isclose(
                float(worker_value), parent_value, rel_tol=0.0, abs_tol=1e-9
            ):
                raise ExternalBaselineError(f"worker {key} differs from parent recomputation")
        elif worker_value != parent_value:
            raise ExternalBaselineError(f"worker {key} differs from parent recomputation")
    expected_status = "OK" if recomputed["passed"] else "ALGORITHM_FAILURE"
    expected_codes = [] if recomputed["passed"] else ["INDEPENDENT_RECOMPUTE_FAILED"]
    if status != expected_status or codes != expected_codes or row.get("feasible") is not recomputed["passed"]:
        raise ExternalBaselineError("worker success/failure semantics differ from parent recomputation")
    return {
        **dict(row),
        "independent_recomputation": recomputed,
        "parent_validation": "PARENT_IDENTITY_SOLUTION_HASH_AND_RECOMPUTATION_PASSED",
    }


def _terminate_process_group(process: subprocess.Popen[Any]) -> None:
    """Terminate the entire solver process group, escalating TERM to KILL."""

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=HARD_TIMEOUT_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait()


def _register_active_process(process: subprocess.Popen[Any]) -> None:
    with _ACTIVE_PROCESS_LOCK:
        _ACTIVE_PROCESSES[process.pid] = process


def _unregister_active_process(process: subprocess.Popen[Any]) -> None:
    with _ACTIVE_PROCESS_LOCK:
        _ACTIVE_PROCESSES.pop(process.pid, None)


def _parent_stop_signal_handler(signum: int, _frame: Any) -> None:
    """Signal handler deliberately records intent only; it never kills here."""

    global _STOP_SIGNAL
    _STOP_SIGNAL = signum
    _STOP_REQUESTED.set()


def _terminate_all_active_process_groups() -> list[int]:
    """Main-thread batch TERM-to-KILL escalation for all registered children."""

    with _ACTIVE_PROCESS_LOCK:
        processes = list(_ACTIVE_PROCESSES.values())
    pids = [process.pid for process in processes]
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + HARD_TIMEOUT_GRACE_SECONDS
    survivors: list[subprocess.Popen[Any]] = []
    for process in processes:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            survivors.append(process)
    for process in survivors:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    for process in survivors:
        process.wait()
    with _ACTIVE_PROCESS_LOCK:
        for process in processes:
            _ACTIVE_PROCESSES.pop(process.pid, None)
    return pids


def handle_parent_stop_request(
    out: Path,
    contract_sha256: str,
    checkpointed_task_keys: list[str],
) -> Path:
    """Main-thread stop handler: drain process groups and preserve an incident."""

    pids = _terminate_all_active_process_groups()
    incident = {
        "schema_version": "resetp.e2.solomon-external-parent-stop-incident.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "signal_number": _STOP_SIGNAL,
        "signal_name": signal.Signals(_STOP_SIGNAL).name if _STOP_SIGNAL is not None else "UNKNOWN",
        "contract_sha256": contract_sha256,
        "active_process_group_ids_at_stop": pids,
        "checkpointed_task_count_before_stop": len(checkpointed_task_keys),
        "checkpointed_task_keys_before_stop": sorted(checkpointed_task_keys),
        "action": "TERM_THEN_KILL_PROCESS_GROUPS_AND_HALT_WITH_RESUMABLE_CHECKPOINTS",
    }
    path = out / "incidents" / f"parent-stop-{time.time_ns()}.json"
    atomic_json(path, incident)
    return path


def _next_attempt_dir(out: Path, task_key: str) -> Path:
    root = out / ".tasks/attempts" / task_key
    root.mkdir(parents=True, exist_ok=True)
    numbers = [
        int(match.group(1))
        for path in root.iterdir()
        if path.is_dir() and (match := re.fullmatch(r"attempt-(\d{4})", path.name))
    ]
    attempt = root / f"attempt-{(max(numbers, default=0) + 1):04d}"
    attempt.mkdir(parents=False, exist_ok=False)
    return attempt


def run_subprocess_attempt(
    task: Mapping[str, Any],
    attempt: Path,
    freeze: Mapping[str, Any],
    contract_path: Path,
) -> dict[str, Any]:
    task_path = attempt / "task.json"
    result_path = attempt / "worker_result.json"
    stdout_path = attempt / "stdout.log"
    stderr_path = attempt / "stderr.log"
    atomic_json(task_path, task)
    verify_runtime_freeze(task, contract_path)
    env = os.environ.copy()
    env.update(THREAD_ENV)
    env["PYTHONHASHSEED"] = "0"
    started = time.perf_counter_ns()
    command = [
        str(freeze["python_executable"]),
        str(Path(__file__).resolve()),
        "--worker-task",
        str(task_path),
        "--worker-output",
        str(result_path),
        "--worker-contract",
        str(contract_path),
    ]
    hard_timeout = float(task["wall_clock_seconds"]) + HARD_TIMEOUT_OVERHEAD_SECONDS
    atomic_json(
        attempt / "command.json",
        {
            "argv": command,
            "cwd": str(REPO),
            "thread_environment": THREAD_ENV,
            "pythonhashseed": "0",
            "solver_wall_clock_seconds": float(task["wall_clock_seconds"]),
            "parent_hard_timeout_seconds": hard_timeout,
            "start_new_session": True,
            "termination": ["SIGTERM", f"WAIT_{HARD_TIMEOUT_GRACE_SECONDS}_SECONDS", "SIGKILL"],
        },
    )
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            process = subprocess.Popen(
                command,
                cwd=REPO,
                env=env,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            _register_active_process(process)
            try:
                try:
                    returncode = process.wait(timeout=hard_timeout)
                except subprocess.TimeoutExpired:
                    _terminate_process_group(process)
                    if _STOP_REQUESTED.is_set():
                        raise ExternalBaselineError("parent stop interrupted task during hard-timeout cleanup")
                    return _failure_result(
                        task,
                        "INFRASTRUCTURE_TIMEOUT",
                        ["HARD_WALL_TIMEOUT"],
                        (time.perf_counter_ns() - started) / 1e9,
                    )
            finally:
                _unregister_active_process(process)
    except subprocess.TimeoutExpired:
        raise AssertionError("timeout must be handled around Popen.wait")
    except OSError as exc:
        if _STOP_REQUESTED.is_set():
            raise ExternalBaselineError("parent stop interrupted task launch") from exc
        return _failure_result(
            task,
            "INFRASTRUCTURE_FAILURE",
            [f"WORKER_LAUNCH_ERRNO_{exc.errno if exc.errno is not None else -1}"],
            (time.perf_counter_ns() - started) / 1e9,
        )
    if _STOP_REQUESTED.is_set():
        raise ExternalBaselineError("parent stop interrupted active task; attempt retained without checkpoint")
    if returncode != 0 or not result_path.is_file():
        return _failure_result(
            task,
            "INFRASTRUCTURE_FAILURE",
            [f"WORKER_EXIT_{returncode}"],
            (time.perf_counter_ns() - started) / 1e9,
        )
    row = json.loads(result_path.read_text(encoding="utf-8"))
    verify_runtime_freeze(task, contract_path)
    return validate_result_identity_and_semantics(task, row)


def _attempt_artifacts(attempt: Path) -> dict[str, str]:
    return {
        str(path.relative_to(attempt)): sha256(path)
        for path in sorted(attempt.rglob("*"))
        if path.is_file() and path.name != "task_artifact_hashes.json" and not path.name.startswith("._")
    }


def seal_attempt(attempt: Path, task_key: str) -> str:
    manifest = {
        "schema_version": ATTEMPT_MANIFEST_SCHEMA,
        "task_key": task_key,
        "artifacts": _attempt_artifacts(attempt),
    }
    path = attempt / "task_artifact_hashes.json"
    atomic_json(path, manifest)
    return sha256(path)


def verify_attempt_seal(attempt: Path, task_key: str, expected_manifest_sha256: str) -> None:
    manifest_path = attempt / "task_artifact_hashes.json"
    if not manifest_path.is_file() or sha256(manifest_path) != expected_manifest_sha256:
        raise ExternalBaselineError(f"attempt manifest differs: {task_key}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != ATTEMPT_MANIFEST_SCHEMA or manifest.get("task_key") != task_key:
        raise ExternalBaselineError(f"attempt manifest identity differs: {task_key}")
    if manifest.get("artifacts") != _attempt_artifacts(attempt):
        raise ExternalBaselineError(f"attempt artifact hashes differ: {task_key}")


def checkpoint_path(out: Path, task_key: str) -> Path:
    return out / ".tasks/checkpoints" / f"{task_key}.json"


def run_task_and_checkpoint(
    task: Mapping[str, Any],
    out: Path,
    freeze: Mapping[str, Any],
    contract_path: Path,
) -> dict[str, Any]:
    """Run one task and durably checkpoint it before returning to the pool."""

    if _STOP_REQUESTED.is_set():
        raise ExternalBaselineError("parent stop requested before task launch")
    attempt = _next_attempt_dir(out, str(task["task_key"]))
    row = run_subprocess_attempt(task, attempt, freeze, contract_path)
    row = validate_result_identity_and_semantics(task, row)
    parent_result_path = attempt / "parent_result.json"
    atomic_json(parent_result_path, row)
    verify_runtime_freeze(task, contract_path)
    manifest_sha = seal_attempt(attempt, str(task["task_key"]))
    checkpoint = {
        "schema_version": CHECKPOINT_SCHEMA,
        "task_key": task["task_key"],
        "task_sha256": canonical_sha256(task),
        "contract_sha256": task["contract_sha256"],
        "attempt_relative_path": str(attempt.relative_to(out)),
        "task_artifact_hashes_sha256": manifest_sha,
        "parent_result_sha256": sha256(parent_result_path),
        "result": row,
    }
    # Last possible gate before the durable completion marker becomes visible.
    verify_runtime_freeze(task, contract_path)
    atomic_json(checkpoint_path(out, str(task["task_key"])), checkpoint)
    return row


def load_task_checkpoint(
    task: Mapping[str, Any],
    out: Path,
    contract_path: Path,
) -> dict[str, Any] | None:
    path = checkpoint_path(out, str(task["task_key"]))
    if not path.is_file():
        return None
    verify_runtime_freeze(task, contract_path)
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA or checkpoint.get("task_key") != task["task_key"]:
        raise ExternalBaselineError(f"checkpoint identity differs: {task['task_key']}")
    if checkpoint.get("task_sha256") != canonical_sha256(task):
        raise ExternalBaselineError(f"checkpoint task payload differs: {task['task_key']}")
    if checkpoint.get("contract_sha256") != task["contract_sha256"]:
        raise ExternalBaselineError(f"checkpoint contract differs: {task['task_key']}")
    attempt = (out / str(checkpoint.get("attempt_relative_path", ""))).resolve()
    attempts_root = (out / ".tasks/attempts").resolve()
    if attempts_root not in attempt.parents:
        raise ExternalBaselineError(f"checkpoint attempt path escapes run directory: {task['task_key']}")
    verify_attempt_seal(
        attempt,
        str(task["task_key"]),
        str(checkpoint.get("task_artifact_hashes_sha256", "")),
    )
    parent_result_path = attempt / "parent_result.json"
    if not parent_result_path.is_file() or sha256(parent_result_path) != checkpoint.get("parent_result_sha256"):
        raise ExternalBaselineError(f"checkpoint parent result differs: {task['task_key']}")
    disk_row = json.loads(parent_result_path.read_text(encoding="utf-8"))
    if canonical_sha256(disk_row) != canonical_sha256(checkpoint.get("result")):
        raise ExternalBaselineError(f"checkpoint embedded result differs: {task['task_key']}")
    return validate_result_identity_and_semantics(task, disk_row)


def references() -> dict[str, dict[str, Any]]:
    with REFERENCES.open(encoding="utf-8", newline="") as handle:
        rows = {row["instance"]: row for row in csv.DictReader(handle)}
    if len(rows) != 56:
        raise ExternalBaselineError("reference table must contain 56 rows")
    return rows


def join_reference(row: Mapping[str, Any], ref: Mapping[str, Any]) -> dict[str, Any]:
    if row.get("status") != "OK":
        return {**row, "bks_vehicle_count": ref["bks_vehicles"], "bks_distance": ref["bks_distance"], "distance_gap_pct": "", "full_bks_hit": False}
    assessed = FORMAL.reference_assessment(
        int(row["route_count"]),
        float(row["distance_rounded_2"]),
        int(ref["bks_vehicles"]),
        float(ref["bks_distance"]),
    )
    return {
        **row,
        "bks_vehicle_count": int(ref["bks_vehicles"]),
        "bks_distance": float(ref["bks_distance"]),
        **assessed,
    }


RAW_FIELDS = [
    "task_key", "instance", "class", "seed", "baseline_id", "bks_vehicle_count", "bks_distance",
    "route_count", "vehicle_excess", "distance_double", "distance_rounded_2", "reached_bks_vehicle_count",
    "distance_gap_pct", "full_bks_hit", "bks_conflict_candidate", "process_cpu_seconds", "elapsed_seconds", "time_to_best_seconds",
    "feasible", "status", "failure_codes", "solution_sha256",
]


def write_global_task_artifact_index(
    out: Path,
    contract: Mapping[str, Any],
    rows: list[dict[str, Any]],
) -> Path:
    """Bind every checkpoint and every attempt into a root-level index."""

    expected_keys = {str(row["task_key"]) for row in rows}
    expected_count = len(contract.get("instances", [])) * len(contract.get("seeds", []))
    if expected_count <= 0 or len(expected_keys) != expected_count or len(rows) != expected_count:
        raise ExternalBaselineError("global task index row coverage differs from frozen contract")
    checkpoint_root = out / ".tasks/checkpoints"
    checkpoint_files = {
        path.stem: path
        for path in checkpoint_root.glob("*.json")
        if path.is_file() and not path.name.startswith("._")
    }
    if set(checkpoint_files) != expected_keys:
        raise ExternalBaselineError("global task index checkpoint coverage differs from final rows")
    attempts_root = out / ".tasks/attempts"
    attempt_task_keys = {
        path.name for path in attempts_root.iterdir() if path.is_dir() and not path.name.startswith("._")
    }
    if attempt_task_keys != expected_keys:
        raise ExternalBaselineError("global task index attempt coverage differs from final rows")
    entries: dict[str, Any] = {}
    for task_key in sorted(expected_keys):
        checkpoint_path_value = checkpoint_files[task_key]
        checkpoint = json.loads(checkpoint_path_value.read_text(encoding="utf-8"))
        if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA or checkpoint.get("task_key") != task_key:
            raise ExternalBaselineError(f"checkpoint identity differs during global indexing: {task_key}")
        if checkpoint.get("contract_sha256") != contract["contract_sha256"]:
            raise ExternalBaselineError(f"checkpoint contract differs during global indexing: {task_key}")
        attempts: list[dict[str, Any]] = []
        for attempt in sorted((attempts_root / task_key).iterdir()):
            if not attempt.is_dir() or re.fullmatch(r"attempt-\d{4}", attempt.name) is None:
                continue
            manifest_path = attempt / "task_artifact_hashes.json"
            if manifest_path.is_file():
                verify_attempt_seal(attempt, task_key, sha256(manifest_path))
            attempts.append(
                {
                    "relative_path": str(attempt.relative_to(out)),
                    "sealed": manifest_path.is_file(),
                    "task_artifact_hashes_sha256": sha256(manifest_path) if manifest_path.is_file() else "",
                    "artifacts": _attempt_artifacts(attempt),
                }
            )
        if not attempts:
            raise ExternalBaselineError(f"no attempt directory found during global indexing: {task_key}")
        checkpoint_attempt = str(checkpoint.get("attempt_relative_path", ""))
        if checkpoint_attempt not in {attempt["relative_path"] for attempt in attempts if attempt["sealed"]}:
            raise ExternalBaselineError(f"checkpoint does not point to a sealed attempt: {task_key}")
        entries[task_key] = {
            "checkpoint_relative_path": str(checkpoint_path_value.relative_to(out)),
            "checkpoint_sha256": sha256(checkpoint_path_value),
            "task_sha256": checkpoint["task_sha256"],
            "checkpoint_attempt_relative_path": checkpoint_attempt,
            "attempts": attempts,
        }
    payload = {
        "schema_version": "resetp.e2.solomon-external-global-task-artifacts.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_sha256": contract["contract_sha256"],
        "task_count": len(entries),
        "checkpoint_count": len(checkpoint_files),
        "all_attempts_including_incomplete_incidents_retained": True,
        "tasks": entries,
    }
    path = out / "task_artifact_hashes.json"
    atomic_json(path, payload)
    return path


def verify_global_task_artifact_index(
    out: Path,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute all checkpoint/attempt hashes and verify the root index."""

    path = out / "task_artifact_hashes.json"
    if not path.is_file():
        raise ExternalBaselineError("global task artifact index is missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != "resetp.e2.solomon-external-global-task-artifacts.v1"
        or payload.get("contract_sha256") != contract["contract_sha256"]
    ):
        raise ExternalBaselineError("global task artifact index identity differs")
    indexed = payload.get("tasks")
    if not isinstance(indexed, dict) or not indexed:
        raise ExternalBaselineError("global task artifact index is empty")
    expected_count = len(contract.get("instances", [])) * len(contract.get("seeds", []))
    if (
        payload.get("task_count") != expected_count
        or payload.get("checkpoint_count") != expected_count
        or len(indexed) != expected_count
    ):
        raise ExternalBaselineError("global task artifact index count differs")
    checkpoint_root = out / ".tasks/checkpoints"
    actual_checkpoint_keys = {
        item.stem for item in checkpoint_root.glob("*.json") if item.is_file() and not item.name.startswith("._")
    }
    attempts_root = out / ".tasks/attempts"
    actual_attempt_keys = {
        item.name for item in attempts_root.iterdir() if item.is_dir() and not item.name.startswith("._")
    }
    if actual_checkpoint_keys != set(indexed) or actual_attempt_keys != set(indexed):
        raise ExternalBaselineError("global task artifact index task coverage differs")
    for task_key, record in indexed.items():
        checkpoint_path_value = out / str(record.get("checkpoint_relative_path", ""))
        expected_checkpoint_path = checkpoint_root / f"{task_key}.json"
        if checkpoint_path_value.resolve() != expected_checkpoint_path.resolve():
            raise ExternalBaselineError(f"global index checkpoint path differs: {task_key}")
        if not checkpoint_path_value.is_file() or sha256(checkpoint_path_value) != record.get("checkpoint_sha256"):
            raise ExternalBaselineError(f"global index checkpoint hash differs: {task_key}")
        checkpoint = json.loads(checkpoint_path_value.read_text(encoding="utf-8"))
        if (
            checkpoint.get("task_key") != task_key
            or checkpoint.get("contract_sha256") != contract["contract_sha256"]
            or checkpoint.get("task_sha256") != record.get("task_sha256")
            or checkpoint.get("attempt_relative_path") != record.get("checkpoint_attempt_relative_path")
        ):
            raise ExternalBaselineError(f"global index checkpoint content differs: {task_key}")
        attempts = record.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise ExternalBaselineError(f"global index attempts are empty: {task_key}")
        actual_attempt_paths = {
            str(item.relative_to(out))
            for item in (attempts_root / task_key).iterdir()
            if item.is_dir() and re.fullmatch(r"attempt-\d{4}", item.name)
        }
        indexed_attempt_paths = {str(item.get("relative_path", "")) for item in attempts}
        if actual_attempt_paths != indexed_attempt_paths:
            raise ExternalBaselineError(f"global index attempt coverage differs: {task_key}")
        for attempt_record in attempts:
            attempt = out / str(attempt_record["relative_path"])
            if attempt_record.get("artifacts") != _attempt_artifacts(attempt):
                raise ExternalBaselineError(f"global index attempt artifact hash differs: {task_key}/{attempt.name}")
            manifest_path = attempt / "task_artifact_hashes.json"
            sealed = manifest_path.is_file()
            if bool(attempt_record.get("sealed")) is not sealed:
                raise ExternalBaselineError(f"global index attempt seal state differs: {task_key}/{attempt.name}")
            if sealed:
                manifest_sha = sha256(manifest_path)
                if manifest_sha != attempt_record.get("task_artifact_hashes_sha256"):
                    raise ExternalBaselineError(f"global index attempt manifest hash differs: {task_key}/{attempt.name}")
                verify_attempt_seal(attempt, task_key, manifest_sha)
            elif attempt_record.get("task_artifact_hashes_sha256") not in {"", None}:
                raise ExternalBaselineError(f"unsealed attempt has a manifest hash: {task_key}/{attempt.name}")
        checkpoint_attempt = str(record["checkpoint_attempt_relative_path"])
        if checkpoint_attempt not in {
            str(item["relative_path"]) for item in attempts if item.get("sealed") is True
        }:
            raise ExternalBaselineError(f"checkpoint attempt is not sealed in global index: {task_key}")
    return payload


def write_final(out: Path, contract: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [row for row in rows if row["status"] != "OK"]
    conflicts = [row for row in rows if bool(row.get("bks_conflict_candidate"))]
    metadata = {
        "schema_version": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_sha256": contract["contract_sha256"],
        "baseline_id": contract["baseline_id"],
        "baseline_version": contract["baseline_version"],
        "fairness_axis": contract["fairness_axis"],
        "workers": contract["workers"],
        "single_thread_per_solver": True,
        "wall_clock_seconds": contract["wall_clock_seconds"],
        "runs": len(rows),
        "internal_evaluation_budget_comparison_forbidden": True,
    }
    verdict = (
        "FORMAL_EXTERNAL_BASELINE_BKS_CONFLICT_REVIEW_REQUIRED"
        if conflicts
        else "FORMAL_EXTERNAL_BASELINE_COMPLETE" if not failures else "FORMAL_EXTERNAL_BASELINE_COMPLETE_WITH_FAILURES"
    )
    decision = {
        "verdict": verdict,
        "task_count": len(rows),
        "expected_task_count": 560,
        "failure_count": len(failures),
        "failures": [row["task_key"] for row in failures],
        "bks_conflict_candidate_count": len(conflicts),
        "bks_conflict_candidates": [row["task_key"] for row in conflicts],
        "all_unfavorable_results_retained": True,
    }
    atomic_json(out / "metadata.json", metadata)
    atomic_csv(
        out / "raw_runs.csv",
        [{**row, "failure_codes": json.dumps(row.get("failure_codes", []), ensure_ascii=False)} for row in rows],
        RAW_FIELDS,
    )
    atomic_text(
        out / "solutions.jsonl",
        "".join(
            json.dumps(
                {
                    "task_key": row["task_key"],
                    "instance": row["instance"],
                    "seed": row["seed"],
                    "status": row["status"],
                    "solution_sha256": row.get("solution_sha256", ""),
                    "routes": row.get("routes", []),
                    "independent_recomputation": row.get("independent_recomputation", {}),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
            for row in rows
        ),
    )
    atomic_json(out / "decision.json", decision)
    atomic_text(
        out / "report.md",
        "# Solomon现代外部强基线\n\n"
        f"判定：`{decision['verdict']}`。PyVRP按同机单线程、每次{contract['wall_clock_seconds']}秒墙钟上限运行，"
        f"完整保留56例×10种子共{len(rows)}项，其中失败{len(failures)}项。该结果只与同一墙钟轴上的外部算法比较，"
        "不得与本文ALNS/LNS的完整候选评价次数混为同一公平预算。所有路线均由项目双精度独立评价器复算后才关联BKS。\n",
    )
    subprocess.run(["dot_clean", "-m", str(out)], check=True)
    write_global_task_artifact_index(out, contract, rows)
    verify_global_task_artifact_index(out, contract)
    artifacts = {
        str(path.relative_to(out)): sha256(path)
        for path in sorted(out.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and ".tasks" not in path.parts and not path.name.startswith("._")
    }
    atomic_json(out / "artifact_hashes.json", artifacts)
    verify_global_task_artifact_index(out, contract)
    for relative, expected in artifacts.items():
        artifact = out / relative
        if not artifact.is_file() or sha256(artifact) != expected:
            raise ExternalBaselineError(f"final artifact manifest differs after publication: {relative}")
    subprocess.run(["dot_clean", "-m", str(out)], check=True)
    if list(out.rglob("._*")):
        raise ExternalBaselineError("AppleDouble remains after writing the formal artifact manifest")
    return decision


def execute_formal(out: Path, authorization: str) -> dict[str, Any]:
    global _STOP_SIGNAL

    if authorization != AUTHORIZATION:
        raise ExternalBaselineError("explicit formal-search authorisation string differs")
    metadata, _, preflight_decision = PREFLIGHT.build_preflight()
    if preflight_decision["verdict"] != "PASS_EXTERNAL_BASELINE_PREFLIGHT":
        raise ExternalBaselineError(f"preflight not passed: {preflight_decision['failures']}")
    if metadata["search_evaluations"] != 0:
        raise ExternalBaselineError("preflight unexpectedly performed search")
    e7 = require_e7_attestation()
    freeze = require_tool_freeze()
    contract = build_contract(freeze, e7)
    tasks = [
        {**task, "contract_sha256": contract["contract_sha256"]}
        for task in build_tasks(freeze)
    ]
    contract_path = ensure_output(out, contract)
    raw_by_key: dict[str, dict[str, Any]] = {}
    for task in tasks:
        completed = load_task_checkpoint(task, out, contract_path)
        if completed is not None:
            raw_by_key[str(task["task_key"])] = completed
    pending = [task for task in tasks if task["task_key"] not in raw_by_key]
    _STOP_REQUESTED.clear()
    _STOP_SIGNAL = None
    old_handlers = {
        signum: signal.getsignal(signum)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    for signum in old_handlers:
        signal.signal(signum, _parent_stop_signal_handler)
    pool = ThreadPoolExecutor(max_workers=EXPECTED_WORKERS)
    futures = {
        pool.submit(run_task_and_checkpoint, task, out, freeze, contract_path): task
        for task in pending
    }
    active_futures = set(futures)
    try:
        while active_futures:
            if _STOP_REQUESTED.is_set():
                incident = handle_parent_stop_request(
                    out,
                    str(contract["contract_sha256"]),
                    list(raw_by_key),
                )
                for future in active_futures:
                    future.cancel()
                pool.shutdown(wait=True, cancel_futures=True)
                raise ExternalBaselineError(f"parent stop requested; incident preserved at {incident}")
            done, _ = wait(active_futures, timeout=0.5, return_when=FIRST_COMPLETED)
            if _STOP_REQUESTED.is_set():
                continue
            for future in done:
                row = future.result()
                raw_by_key[str(row["task_key"])] = row
            active_futures.difference_update(done)
        pool.shutdown(wait=True)
    except BaseException:
        _terminate_all_active_process_groups()
        for future in active_futures:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    finally:
        for signum, old_handler in old_handlers.items():
            signal.signal(signum, old_handler)
    if len(raw_by_key) != len(tasks):
        raise ExternalBaselineError(f"checkpointed task count differs: {len(raw_by_key)} != {len(tasks)}")
    raw = list(raw_by_key.values())
    raw.sort(key=lambda row: (row["instance"], int(row["seed"])))
    refs = references()
    rows = [join_reference(row, refs[row["instance"]]) for row in raw]
    return write_final(out, contract, rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-formal", action="store_true")
    parser.add_argument("--authorization", default="")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--worker-task", type=Path)
    parser.add_argument("--worker-output", type=Path)
    parser.add_argument("--worker-contract", type=Path)
    args = parser.parse_args()
    if args.worker_task or args.worker_output or args.worker_contract:
        if not (args.worker_task and args.worker_output and args.worker_contract):
            raise ExternalBaselineError("worker task, output, and contract must be provided together")
        return worker_main(args.worker_task, args.worker_output, args.worker_contract)
    if not args.execute_formal:
        _, _, decision = PREFLIGHT.build_preflight()
        print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
        return 2 if decision["verdict"].startswith("HALT") else 0
    decision = execute_formal(args.output, args.authorization)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
