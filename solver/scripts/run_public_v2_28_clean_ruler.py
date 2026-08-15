#!/usr/bin/env python3
"""Run the approved 28-instance exact-x1000 public comparison serially.

The same file acts as a detached batch controller and as an isolated one-arm
worker.  The controller starts exactly one worker at a time, in the matching
Python environment.  Each worker saves the full solution, a per-iteration
incumbent trace, provenance, and an immediate raw-precision feasibility audit.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import math
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
INSTANCE_ROOT = (
    REPO
    / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
    / "sources/normalised_instances"
)
DEFAULT_OUTPUT = (
    REPO / "solver/reports/public_v2_28_clean_ruler_20260810"
)
INDEPENDENT_PYTHON = (
    REPO / "build/python_envs/setp-independent-hgs/bin/python"
)
FROZEN_PYTHON = Path("/opt/anaconda3/bin/python3.13")
INSTANCES = tuple(
    f"PR{number}{suffix}"
    for number in range(11, 25)
    for suffix in ("A", "B")
)
ARMS = ("independent", "frozen_pyvrp")
INTEGER_SCALE = 1_000
ROUND_FUNC = "exact"
BISECTION_STEPS = 100
EPS = 1e-9
REQUIRED_RUN_FILES = (
    "best_solution.json",
    "raw_runs.csv",
    "metadata.json",
    "audit.json",
)


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _json(path: Path, payload: Any) -> None:
    _atomic_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _safe_command(*args: str) -> str | None:
    try:
        return subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(
            ("/usr/bin/git", *args),
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _machine_identity() -> dict[str, Any]:
    memory_bytes: int | None = None
    try:
        memory_bytes = int(os.sysconf("SC_PHYS_PAGES")) * int(
            os.sysconf("SC_PAGE_SIZE")
        )
    except (OSError, ValueError):
        pass

    return {
        "benchmark_machine_role": "M1 (ARM) paper baseline",
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "memory_bytes": memory_bytes,
        "hw_model": _safe_command("/usr/sbin/sysctl", "-n", "hw.model"),
        "process_pid": os.getpid(),
        "parent_pid": os.getppid(),
    }


def _hash_files(paths: list[Path]) -> dict[str, str]:
    identities: dict[str, str] = {}
    for path in sorted(set(path.resolve() for path in paths)):
        if not path.is_file() or path.name.startswith("._"):
            continue
        try:
            label = str(path.relative_to(REPO))
        except ValueError:
            label = str(path)
        identities[label] = _sha256(path)
    return identities


def _common_source_identity(instance_path: Path) -> dict[str, Any]:
    return {
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_porcelain": _git("status", "--porcelain"),
        "runner_sha256": _sha256(Path(__file__).resolve()),
        "instance_sha256": _sha256(instance_path),
    }


def _independent_source_identity(instance_path: Path) -> dict[str, Any]:
    import setp_hgs_kernel

    problem_sources = list(
        (REPO / "solver/src/setp_solver/algorithms/problem_hgs").glob("*.py")
    )
    copied_sources = list(
        (REPO / "third_party/setp_hgs_kernel/setp_hgs_kernel").rglob("*.py")
    )
    copied_metadata = [
        REPO / "third_party/setp_hgs_kernel/UPSTREAM_COMMIT",
        REPO / "third_party/setp_hgs_kernel/LICENSE.md",
        REPO / "third_party/setp_hgs_kernel/meson.build",
        REPO / "third_party/setp_hgs_kernel/pyproject.toml",
    ]
    installed_root = Path(setp_hgs_kernel.__file__).resolve().parent
    compiled = list(installed_root.rglob("*.so"))
    return {
        **_common_source_identity(instance_path),
        "implementation": "independent Problem-HGS current serial chain",
        "setp_hgs_kernel_version": importlib.metadata.version(
            "setp-hgs-kernel"
        ),
        "setp_hgs_kernel_package": str(installed_root),
        "pyvrp_importable": importlib.util.find_spec("pyvrp") is not None,
        "source_sha256": _hash_files(
            [*problem_sources, *copied_sources, *copied_metadata, *compiled]
        ),
    }


def _frozen_source_identity(instance_path: Path) -> dict[str, Any]:
    import pyvrp

    package_root = Path(pyvrp.__file__).resolve().parent
    package_files = [
        path
        for path in package_root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".so"}
    ]
    return {
        **_common_source_identity(instance_path),
        "implementation": "unmodified frozen PyVRP 0.12.2 HGS",
        "pyvrp_version": importlib.metadata.version("pyvrp"),
        "pyvrp_package": str(package_root),
        "setp_hgs_kernel_importable": (
            importlib.util.find_spec("setp_hgs_kernel") is not None
        ),
        "source_sha256": _hash_files(package_files),
    }


def _prepare_independent_imports() -> None:
    solver_src = str(REPO / "solver/src")
    if solver_src not in sys.path:
        sys.path.insert(0, solver_src)

    import setp_hgs_kernel

    source_package = str(
        REPO / "third_party/setp_hgs_kernel/setp_hgs_kernel"
    )
    if source_package not in setp_hgs_kernel.__path__:
        setp_hgs_kernel.__path__.insert(0, source_package)
    if not hasattr(setp_hgs_kernel, "__version__"):
        setp_hgs_kernel.__version__ = importlib.metadata.version(
            "setp-hgs-kernel"
        )


@dataclass
class _TraceRow:
    iteration: int
    elapsed_seconds: float
    best_cost: float


class _TracingStop:
    """The same max-runtime and no-improvement stop, with one row per step."""

    def __init__(self, max_runtime_seconds: float, no_improvement: int) -> None:
        self.max_runtime_seconds = float(max_runtime_seconds)
        self.no_improvement_limit = int(no_improvement)
        self.rows: list[_TraceRow] = []
        self._started: float | None = None
        self._target: float | None = None
        self._without_improvement = 0
        self._calls = 0
        self.termination_reason: str | None = None
        self.time_to_best_seconds: float | None = None

    def __call__(self, best_cost: float) -> bool:
        now = time.perf_counter()
        if self._started is None:
            self._started = now
        elapsed = now - self._started
        value = float(best_cost)

        if self._calls > 0:
            self.rows.append(
                _TraceRow(
                    iteration=self._calls,
                    elapsed_seconds=elapsed,
                    best_cost=value,
                )
            )
        self._calls += 1

        if self._target is None or value < self._target:
            self._target = value
            self._without_improvement = 0
            self.time_to_best_seconds = elapsed
        else:
            self._without_improvement += 1

        if self._without_improvement >= self.no_improvement_limit:
            self.termination_reason = "NO_IMPROVEMENT"
            return True
        if elapsed > self.max_runtime_seconds:
            self.termination_reason = "MAX_RUNTIME"
            return True
        return False


def _service(data: Any, solution: Any) -> dict[str, Any]:
    visits = [
        int(client)
        for route in solution.routes()
        for client in route.visits()
    ]
    clients = set(range(data.num_depots, data.num_locations))
    total_delivery = sum(
        sum(int(value) for value in data.location(client).delivery)
        for client in clients
    )
    completed_delivery = sum(
        sum(int(value) for value in data.location(client).delivery)
        for client in set(visits)
    )
    return {
        "complete": bool(solution.is_complete()),
        "scaled_feasible": bool(solution.is_feasible()),
        "completed_clients": len(set(visits)),
        "total_clients": len(clients),
        "completed_delivery": completed_delivery,
        "total_delivery": total_delivery,
        "no_duplicate_clients": len(visits) == len(set(visits)),
    }


def _routes(solution: Any) -> list[dict[str, Any]]:
    return [
        {
            "vehicle_type": int(route.vehicle_type()),
            "start_depot": int(route.start_depot()),
            "end_depot": int(route.end_depot()),
            "customer_nodes": list(map(int, route.visits())),
        }
        for route in solution.routes()
    ]


def _solve_independent(
    instance_path: Path,
    seed: int,
    max_runtime_seconds: float,
    no_improvement: int,
    sisr_enabled: bool,
) -> tuple[Any, int, int, float, _TracingStop, dict[str, Any]]:
    if importlib.util.find_spec("pyvrp") is not None:
        raise RuntimeError(
            "independent environment must not make PyVRP importable"
        )
    _prepare_independent_imports()
    if importlib.metadata.version("setp-hgs-kernel") != "0.12.2":
        raise RuntimeError("independent copied kernel must be 0.12.2")

    from setp_solver.algorithms.problem_hgs.public_search import (
        build_integrated_public_hgs,
        read_public_instance,
    )

    data = read_public_instance(instance_path)
    bundle = build_integrated_public_hgs(
        data,
        seed=seed,
        enable_vidal_compound=True,
        enable_customer_relocation=True,
        refinement_scope="new_incumbent",
        enable_sisr=sisr_enabled,
    )
    stop = _TracingStop(max_runtime_seconds, no_improvement)
    algorithm_cpu_started = time.process_time()
    result = bundle.algorithm.run(stop)
    algorithm_cpu_seconds = time.process_time() - algorithm_cpu_started
    solution = result.best.solution
    cost = int(result.best.evaluation.objective)
    accounting = {
        "integrated_run": {
            key: value for key, value in vars(result.accounting).items()
        },
        "serial_compound": {
            key: value for key, value in vars(bundle.vidal_accounting).items()
        },
        "sisr": {
            **{
                key: value
                for key, value in vars(bundle.sisr_accounting).items()
            },
            "enabled": bool(sisr_enabled),
            "parameters": {
                "average_removed_customers": 10.0,
                "maximum_string_length": 10.0,
                "blink_probability": 0.01,
                "insertion_order_weights": {
                    "random": 4,
                    "demand": 4,
                    "far": 2,
                    "close": 1,
                },
            },
            "algorithm_cpu_seconds": algorithm_cpu_seconds,
            "cpu_share_percent": (
                100.0
                * bundle.sisr_accounting.cpu_seconds
                / algorithm_cpu_seconds
                if algorithm_cpu_seconds > 0
                else 0.0
            ),
        },
    }
    return (
        data,
        solution,
        cost,
        int(result.accounting.iterations),
        float(result.accounting.elapsed_seconds),
        stop,
        accounting,
    )


def _solve_frozen(
    instance_path: Path,
    seed: int,
    max_runtime_seconds: float,
    no_improvement: int,
) -> tuple[Any, int, int, float, _TracingStop, dict[str, Any]]:
    if importlib.util.find_spec("setp_hgs_kernel") is not None:
        raise RuntimeError(
            "frozen PyVRP environment must not contain copied kernel"
        )
    if importlib.metadata.version("pyvrp") != "0.12.2":
        raise RuntimeError("frozen baseline must be PyVRP 0.12.2")

    from pyvrp import read, solve

    data = read(instance_path, round_func=ROUND_FUNC)
    stop = _TracingStop(max_runtime_seconds, no_improvement)
    result = solve(
        data,
        stop,
        seed=seed,
        collect_stats=False,
        display=False,
    )
    return (
        data,
        result.best,
        int(result.cost()),
        int(result.num_iterations),
        float(result.runtime),
        stop,
        {},
    )


def _as_vector(value: object, size: int, *, dtype=float):
    import numpy as np

    if np.isscalar(value):
        return np.full(size, value, dtype=dtype)
    array = np.asarray(value, dtype=dtype)
    if array.shape != (size,):
        raise ValueError(f"expected vector of length {size}, got {array.shape}")
    return array


def _schedule(
    *,
    route: list[int],
    start_depot: int,
    end_depot: int,
    departure: float,
    edge_weight: Any,
    service_time: Any,
    time_window: Any,
) -> dict[str, Any]:
    current_time = float(departure)
    previous = start_depot
    max_client_violation = 0.0
    violated_customers: list[int] = []
    for customer in route:
        current_time += float(edge_weight[previous, customer])
        service_start = max(
            current_time, float(time_window[customer, 0])
        )
        violation = max(
            0.0, service_start - float(time_window[customer, 1])
        )
        if violation > EPS:
            violated_customers.append(customer)
            max_client_violation = max(max_client_violation, violation)
        current_time = service_start + float(service_time[customer])
        previous = customer

    return_arrival = current_time + float(edge_weight[previous, end_depot])
    return_violation = max(
        0.0, return_arrival - float(time_window[end_depot, 1])
    )
    route_end = max(return_arrival, float(time_window[end_depot, 0]))
    return {
        "departure": float(departure),
        "return_arrival": return_arrival,
        "duration": route_end - float(departure),
        "max_client_tw_violation": max_client_violation,
        "depot_return_tw_violation": return_violation,
        "violated_customers": violated_customers,
        "time_windows_feasible": (
            max_client_violation <= EPS and return_violation <= EPS
        ),
    }


def _audit_route(
    *,
    route_number: int,
    route: dict[str, Any],
    instance: dict[str, Any],
    max_duration: float,
    capacity: float,
) -> dict[str, Any]:
    import numpy as np

    dimension = int(instance["dimension"])
    edge_weight = np.asarray(instance["edge_weight"], dtype=float)
    time_window = np.asarray(instance["time_window"], dtype=float)
    service_time = _as_vector(instance.get("service_time", 0), dimension)
    demand = _as_vector(instance.get("demand", 0), dimension)

    start_depot = int(route["start_depot"])
    end_depot = int(route["end_depot"])
    customers = [int(customer) for customer in route["customer_nodes"]]
    earliest = float(time_window[start_depot, 0])
    latest = float(time_window[start_depot, 1])
    earliest_schedule = _schedule(
        route=customers,
        start_depot=start_depot,
        end_depot=end_depot,
        departure=earliest,
        edge_weight=edge_weight,
        service_time=service_time,
        time_window=time_window,
    )

    latest_tw_departure = earliest
    latest_tw_schedule = earliest_schedule
    time_windows_possible = bool(
        earliest_schedule["time_windows_feasible"]
    )
    if time_windows_possible:
        latest_schedule = _schedule(
            route=customers,
            start_depot=start_depot,
            end_depot=end_depot,
            departure=latest,
            edge_weight=edge_weight,
            service_time=service_time,
            time_window=time_window,
        )
        if latest_schedule["time_windows_feasible"]:
            latest_tw_departure = latest
            latest_tw_schedule = latest_schedule
        else:
            low = earliest
            high = latest
            for _ in range(BISECTION_STEPS):
                middle = (low + high) / 2
                schedule = _schedule(
                    route=customers,
                    start_depot=start_depot,
                    end_depot=end_depot,
                    departure=middle,
                    edge_weight=edge_weight,
                    service_time=service_time,
                    time_window=time_window,
                )
                if schedule["time_windows_feasible"]:
                    low = middle
                    latest_tw_schedule = schedule
                else:
                    high = middle
            latest_tw_departure = low

    chosen_departure: float | None = None
    chosen_schedule: dict[str, Any] | None = None
    duration_possible = bool(
        time_windows_possible
        and float(latest_tw_schedule["duration"]) <= max_duration + EPS
    )
    if duration_possible:
        if float(earliest_schedule["duration"]) <= max_duration + EPS:
            chosen_departure = earliest
            chosen_schedule = earliest_schedule
        else:
            low = earliest
            high = latest_tw_departure
            for _ in range(BISECTION_STEPS):
                middle = (low + high) / 2
                schedule = _schedule(
                    route=customers,
                    start_depot=start_depot,
                    end_depot=end_depot,
                    departure=middle,
                    edge_weight=edge_weight,
                    service_time=service_time,
                    time_window=time_window,
                )
                if float(schedule["duration"]) <= max_duration + EPS:
                    high = middle
                    chosen_schedule = schedule
                else:
                    low = middle
            chosen_departure = high
            if chosen_schedule is None:
                chosen_schedule = _schedule(
                    route=customers,
                    start_depot=start_depot,
                    end_depot=end_depot,
                    departure=chosen_departure,
                    edge_weight=edge_weight,
                    service_time=service_time,
                    time_window=time_window,
                )

    load = float(sum(demand[customer] for customer in customers))
    capacity_violation = max(0.0, load - capacity)
    exists = bool(duration_possible and capacity_violation <= EPS)
    violations: list[str] = []
    if not time_windows_possible:
        if float(earliest_schedule["max_client_tw_violation"]) > EPS:
            violations.append("customer_time_window")
        if float(earliest_schedule["depot_return_tw_violation"]) > EPS:
            violations.append("depot_return_time_window")
    elif not duration_possible:
        violations.append("max_route_duration")
    if capacity_violation > EPS:
        violations.append("capacity")

    reference_schedule = chosen_schedule or latest_tw_schedule
    return {
        "route_number": route_number,
        "vehicle_type": int(route["vehicle_type"]),
        "start_depot": start_depot,
        "end_depot": end_depot,
        "customer_nodes": customers,
        "customers": len(customers),
        "load": load,
        "capacity": capacity,
        "exists_feasible_departure": exists,
        "chosen_departure": chosen_departure,
        "latest_tw_feasible_departure": latest_tw_departure,
        "duration_at_reference": float(reference_schedule["duration"]),
        "max_route_duration": max_duration,
        "max_route_duration_violation": max(
            0.0,
            float(latest_tw_schedule["duration"]) - max_duration,
        ),
        "max_customer_tw_violation": float(
            earliest_schedule["max_client_tw_violation"]
        ),
        "depot_return_tw_violation": float(
            earliest_schedule["depot_return_tw_violation"]
        ),
        "violated_customer_nodes": earliest_schedule[
            "violated_customers"
        ],
        "constraint_violations": violations,
    }


def _vehicle_value(value: Any, vehicle_type: int) -> float:
    import numpy as np

    if np.isscalar(value):
        return float(value)
    values = np.asarray(value, dtype=float).reshape(-1)
    if not 0 <= vehicle_type < len(values):
        raise IndexError(
            f"vehicle type {vehicle_type} outside {len(values)} values"
        )
    return float(values[vehicle_type])


def _audit_solution(
    instance_path: Path,
    solution_payload: dict[str, Any],
    service: dict[str, Any],
) -> dict[str, Any]:
    import numpy as np
    import vrplib

    instance = vrplib.read_instance(
        instance_path,
        instance_format="vrplib",
    )
    capacity_value = instance["capacity"]
    if not np.isscalar(capacity_value):
        raise ValueError("public raw audit expects scalar vehicle capacity")
    capacity = float(capacity_value)
    max_duration_value = instance["vehicles_max_duration"]
    edge_weight = np.asarray(instance["edge_weight"], dtype=float)

    route_rows: list[dict[str, Any]] = []
    all_visits: list[int] = []
    raw_distance = 0.0
    for route_number, route in enumerate(
        solution_payload["routes"], start=1
    ):
        vehicle_type = int(route["vehicle_type"])
        audited = _audit_route(
            route_number=route_number,
            route=route,
            instance=instance,
            max_duration=_vehicle_value(
                max_duration_value, vehicle_type
            ),
            capacity=capacity,
        )
        customers = [int(node) for node in route["customer_nodes"]]
        nodes = [
            int(route["start_depot"]),
            *customers,
            int(route["end_depot"]),
        ]
        raw_distance += sum(
            float(edge_weight[before, after])
            for before, after in zip(nodes, nodes[1:])
        )
        all_visits.extend(customers)
        route_rows.append(audited)

    num_depots = len(np.asarray(instance["depot"]))
    clients = set(range(num_depots, int(instance["dimension"])))
    unique_visits = set(all_visits)
    raw_demand = _as_vector(
        instance.get("demand", 0), int(instance["dimension"])
    )
    completed_raw_demand = float(
        sum(raw_demand[client] for client in unique_visits)
    )
    total_raw_demand = float(
        sum(raw_demand[client] for client in clients)
    )
    feasible_routes = sum(
        bool(row["exists_feasible_departure"]) for row in route_rows
    )
    coverage_complete = bool(
        unique_visits == clients
        and len(all_visits) == len(unique_visits)
    )
    demand_complete = bool(
        math.isclose(
            completed_raw_demand,
            total_raw_demand,
            rel_tol=0,
            abs_tol=EPS,
        )
        and service["completed_delivery"] == service["total_delivery"]
    )
    summary = {
        "audit_method": (
            "unscaled floating distances and time windows; a route is "
            "feasible iff at least one departure within its start-depot "
            "window satisfies customer windows, return-depot window, "
            "maximum route duration, and capacity"
        ),
        "raw_precision_distance": raw_distance,
        "feasible_routes": feasible_routes,
        "total_routes": len(route_rows),
        "all_routes_raw_precision_feasible": (
            feasible_routes == len(route_rows)
        ),
        "violating_route_numbers": [
            int(row["route_number"])
            for row in route_rows
            if not row["exists_feasible_departure"]
        ],
        "completed_clients": len(unique_visits),
        "total_clients": len(clients),
        "coverage_complete": coverage_complete,
        "completed_demand_raw": completed_raw_demand,
        "total_demand_raw": total_raw_demand,
        "demand_complete": demand_complete,
        "service_complete": bool(coverage_complete and demand_complete),
    }
    return {
        "status": "COMPLETE",
        "created_at": _timestamp(),
        "summary": summary,
        "routes": route_rows,
    }


def _write_trace(path: Path, stop: _TracingStop) -> None:
    rows = [
        {
            "iteration": row.iteration,
            "elapsed_seconds": f"{row.elapsed_seconds:.9f}",
            "best_cost": (
                ""
                if not math.isfinite(row.best_cost)
                else f"{row.best_cost:.12g}"
            ),
        }
        for row in stop.rows
    ]
    if not rows:
        raise RuntimeError("solver produced no completed iteration trace")
    _write_csv(path, rows)


def _write_artifact_hashes(output: Path) -> None:
    files = [
        path
        for path in output.iterdir()
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    ]
    _json(
        output / "artifact_hashes.json",
        {path.name: _sha256(path) for path in sorted(files)},
    )


def _worker_failure(
    output: Path,
    metadata: dict[str, Any],
    error: BaseException,
    stop: _TracingStop | None,
) -> None:
    metadata["status"] = "FAILED"
    metadata["finished_at"] = _timestamp()
    _json(output / "metadata.json", metadata)
    if stop is not None and stop.rows:
        _write_trace(output / "raw_runs.csv", stop)
    else:
        _atomic_text(
            output / "raw_runs.csv",
            "iteration,elapsed_seconds,best_cost\n",
        )
    _json(
        output / "audit.json",
        {
            "status": "NOT_AVAILABLE_RUN_FAILED",
            "created_at": _timestamp(),
        },
    )
    _json(
        output / "decision.json",
        {
            "verdict": "RUN_FAILED",
            "error_type": type(error).__name__,
            "error": str(error),
            "traceback": traceback.format_exc(),
        },
    )
    _atomic_text(
        output / "report.md",
        "# 运行失败\n\n"
        f"{type(error).__name__}: {error}\n",
    )
    _write_artifact_hashes(output)


def _worker_main(args: argparse.Namespace) -> int:
    instance_path = INSTANCE_ROOT / f"{args.instance}.vrp"
    if args.instance not in INSTANCES or not instance_path.is_file():
        raise ValueError(f"unknown public instance: {args.instance}")
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)

    metadata: dict[str, Any] = {
        "status": "RUNNING",
        "run_kind": args.run_kind,
        "formal_candidate_result": args.run_kind == "formal",
        "started_at": _timestamp(),
        "instance": args.instance,
        "arm": args.arm,
        "seed": args.seed,
        "max_runtime_seconds": args.max_runtime_seconds,
        "no_improvement_iterations": args.no_improvement,
        "sisr_enabled": bool(args.sisr_enabled),
        "components": {
            "copied_hgs": True,
            "sisr_adjacent_string_ruin_recreate": bool(args.sisr_enabled),
        },
        "round_func": ROUND_FUNC,
        "rounding_definition": "np.round(1000 * value).astype(np.int64)",
        "integer_scale": INTEGER_SCALE,
        "machine": _machine_identity(),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "argv": list(sys.argv),
    }
    _json(output / "metadata.json", metadata)
    stop: _TracingStop | None = None
    try:
        if args.arm == "independent":
            solved = _solve_independent(
                instance_path,
                args.seed,
                args.max_runtime_seconds,
                args.no_improvement,
                args.sisr_enabled,
            )
            source_identity = _independent_source_identity(instance_path)
        else:
            if args.sisr_enabled:
                raise ValueError("SISR is only available on the independent arm")
            solved = _solve_frozen(
                instance_path,
                args.seed,
                args.max_runtime_seconds,
                args.no_improvement,
            )
            source_identity = _frozen_source_identity(instance_path)

        (
            data,
            solution,
            cost,
            iterations,
            runtime_seconds,
            stop,
            algorithm_accounting,
        ) = solved
        service = _service(data, solution)
        solution_payload = {
            "instance": args.instance,
            "arm": args.arm,
            "seed": args.seed,
            "cost_scaled": cost,
            "cost_original_units": cost / INTEGER_SCALE,
            **service,
            "routes": _routes(solution),
        }
        _json(output / "best_solution.json", solution_payload)
        _write_trace(output / "raw_runs.csv", stop)

        # The raw-precision audit is intentionally the next operation after
        # the solution and trajectory are durable.
        audit = _audit_solution(instance_path, solution_payload, service)
        _json(output / "audit.json", audit)
        audit_summary = audit["summary"]

        service_ok = bool(
            service["complete"]
            and service["scaled_feasible"]
            and service["no_duplicate_clients"]
            and service["completed_clients"] == service["total_clients"]
            and service["completed_delivery"] == service["total_delivery"]
        )
        raw_ok = bool(
            audit_summary["all_routes_raw_precision_feasible"]
            and audit_summary["service_complete"]
        )
        verdict = (
            "FORMAL_RUN_COMPLETE"
            if service_ok and raw_ok
            else "FORMAL_RUN_COMPLETE_WITH_AUDIT_FAILURE"
        )
        decision = {
            "verdict": verdict,
            "run_kind": args.run_kind,
            "instance": args.instance,
            "arm": args.arm,
            "seed": args.seed,
            "cost_scaled": cost,
            "cost_original_units": cost / INTEGER_SCALE,
            "iterations": iterations,
            "runtime_seconds": runtime_seconds,
            "time_to_best_seconds": stop.time_to_best_seconds,
            "termination_reason": stop.termination_reason,
            **service,
            "raw_precision_audit": audit_summary,
            "algorithm_accounting": algorithm_accounting,
        }
        _json(output / "decision.json", decision)
        metadata.update(
            {
                "status": "COMPLETE",
                "finished_at": _timestamp(),
                "source_identity": source_identity,
                "termination_reason": stop.termination_reason,
                "actual_iterations": iterations,
                "actual_runtime_seconds": runtime_seconds,
            }
        )
        _json(output / "metadata.json", metadata)
        _atomic_text(
            output / "report.md",
            "# 单次公开对照运行\n\n"
            f"{args.instance}，{args.arm}，seed {args.seed}；"
            f"成本 {cost}（细缩放后整数），运行 {runtime_seconds:.6f} 秒，"
            f"完成客户 {service['completed_clients']}/{service['total_clients']}，"
            f"完成需求 {service['completed_delivery']}/{service['total_delivery']}。\n\n"
            f"原始精度审计：{audit_summary['feasible_routes']}/"
            f"{audit_summary['total_routes']} 条路线可行。\n",
        )
        _write_artifact_hashes(output)
        print(json.dumps(decision, ensure_ascii=False), flush=True)
        return 0
    except BaseException as error:  # preserve the full failed run package
        _worker_failure(output, metadata, error, stop)
        traceback.print_exc()
        return 1


def _run_dir(output: Path, instance: str, arm: str, seed: int) -> Path:
    return output / f"{instance}_{arm}_seed{seed}"


def _worker_command(
    *,
    output_dir: Path,
    instance: str,
    arm: str,
    seed: int,
    max_runtime_seconds: float,
    no_improvement: int,
    run_kind: str,
    sisr_enabled: bool = False,
) -> tuple[list[str], dict[str, str]]:
    python = INDEPENDENT_PYTHON if arm == "independent" else FROZEN_PYTHON
    if not python.is_file():
        raise FileNotFoundError(f"missing Python environment: {python}")
    command = [
        str(python),
        str(Path(__file__).resolve()),
        "worker",
        str(output_dir),
        "--instance",
        instance,
        "--arm",
        arm,
        "--seed",
        str(seed),
        "--max-runtime-seconds",
        str(max_runtime_seconds),
        "--no-improvement",
        str(no_improvement),
        "--run-kind",
        run_kind,
    ]
    if sisr_enabled:
        command.append("--sisr-enabled")
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    return command, environment


def _run_one_subprocess(**kwargs: Any) -> int:
    command, environment = _worker_command(**kwargs)
    return subprocess.run(
        command,
        cwd=REPO,
        env=environment,
        check=False,
    ).returncode


def _validate_run_package(output: Path) -> dict[str, Any]:
    missing = [
        name
        for name in REQUIRED_RUN_FILES
        if not (output / name).is_file() or (output / name).stat().st_size == 0
    ]
    if missing:
        raise RuntimeError(f"{output} missing nonempty files: {missing}")
    metadata = json.loads((output / "metadata.json").read_text("utf-8"))
    solution = json.loads(
        (output / "best_solution.json").read_text("utf-8")
    )
    audit = json.loads((output / "audit.json").read_text("utf-8"))
    decision = json.loads((output / "decision.json").read_text("utf-8"))
    with (output / "raw_runs.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        trace = list(csv.DictReader(handle))
    if metadata.get("status") != "COMPLETE":
        raise RuntimeError(f"run metadata is not complete: {output}")
    if not solution.get("routes"):
        raise RuntimeError(f"saved solution has no routes: {output}")
    if audit.get("status") != "COMPLETE":
        raise RuntimeError(f"raw audit is not complete: {output}")
    if not trace:
        raise RuntimeError(f"per-iteration trajectory is empty: {output}")
    return {
        "metadata": metadata,
        "solution": solution,
        "audit": audit,
        "decision": decision,
        "trace_rows": len(trace),
    }


def _append_progress(
    progress: Path,
    instance: str,
    arm: str,
    package: dict[str, Any],
) -> None:
    decision = package["decision"]
    audit = package["audit"]["summary"]
    line = (
        f"{_timestamp()} instance={instance} arm={arm} "
        f"cost_scaled={decision['cost_scaled']} "
        f"raw_feasible_routes={audit['feasible_routes']}/"
        f"{audit['total_routes']} "
        f"completed_clients={decision['completed_clients']}/"
        f"{decision['total_clients']} "
        f"completed_demand={decision['completed_delivery']}/"
        f"{decision['total_delivery']}\n"
    )
    with progress.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _pair_summary(output: Path, seed: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for instance in INSTANCES:
        packages = {
            arm: _validate_run_package(
                _run_dir(output, instance, arm, seed)
            )
            for arm in ARMS
        }
        own = packages["independent"]["decision"]
        frozen = packages["frozen_pyvrp"]["decision"]
        own_audit = packages["independent"]["audit"]["summary"]
        frozen_audit = packages["frozen_pyvrp"]["audit"]["summary"]
        own_cost = int(own["cost_scaled"])
        frozen_cost = int(frozen["cost_scaled"])
        difference = own_cost - frozen_cost
        if difference < 0:
            winner = "independent"
        elif difference > 0:
            winner = "frozen_pyvrp"
        else:
            winner = "tie"
        rows.append(
            {
                "instance": instance,
                "seed": seed,
                "independent_cost_scaled": own_cost,
                "frozen_cost_scaled": frozen_cost,
                "independent_minus_frozen_scaled": difference,
                "independent_minus_frozen_original": f"{difference / INTEGER_SCALE:.6f}",
                "independent_minus_frozen_percent": f"{100 * difference / frozen_cost:.9f}",
                "winner_by_scaled_cost": winner,
                "independent_raw_feasible_routes": (
                    f"{own_audit['feasible_routes']}/"
                    f"{own_audit['total_routes']}"
                ),
                "frozen_raw_feasible_routes": (
                    f"{frozen_audit['feasible_routes']}/"
                    f"{frozen_audit['total_routes']}"
                ),
                "independent_all_routes_raw_feasible": own_audit[
                    "all_routes_raw_precision_feasible"
                ],
                "frozen_all_routes_raw_feasible": frozen_audit[
                    "all_routes_raw_precision_feasible"
                ],
                "independent_completed_clients": own["completed_clients"],
                "independent_total_clients": own["total_clients"],
                "frozen_completed_clients": frozen["completed_clients"],
                "frozen_total_clients": frozen["total_clients"],
                "independent_completed_delivery": own[
                    "completed_delivery"
                ],
                "independent_total_delivery": own["total_delivery"],
                "frozen_completed_delivery": frozen["completed_delivery"],
                "frozen_total_delivery": frozen["total_delivery"],
                "independent_runtime_seconds": f"{float(own['runtime_seconds']):.9f}",
                "frozen_runtime_seconds": f"{float(frozen['runtime_seconds']):.9f}",
                "independent_iterations": own["iterations"],
                "frozen_iterations": frozen["iterations"],
            }
        )
    return rows


def _batch_report(rows: list[dict[str, Any]]) -> str:
    independent_wins = sum(
        row["winner_by_scaled_cost"] == "independent" for row in rows
    )
    frozen_wins = sum(
        row["winner_by_scaled_cost"] == "frozen_pyvrp" for row in rows
    )
    ties = sum(row["winner_by_scaled_cost"] == "tie" for row in rows)
    lines = [
        "# 公开 28 例 ×1000 干净对照",
        "",
        "两臂均使用 seed 11、相同 1200 秒上限和 exact = "
        "round(1000 × value) 口径；逐题先运行当前串行自研算法，再运行冻结 "
        "PyVRP 0.12.2。下表不筛除任何完成运行。",
        "",
        f"按细缩放整数成本计，自研胜 {independent_wins} 题，冻结臂胜 "
        f"{frozen_wins} 题，平 {ties} 题。",
        "",
        "| 题号 | 自研成本 | 冻结成本 | 自研-冻结 | 胜方 | 自研原始可行路线 | 冻结原始可行路线 | 自研客户 | 冻结客户 |",
        "|---|---:|---:|---:|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['instance']} | {row['independent_cost_scaled']} | "
            f"{row['frozen_cost_scaled']} | "
            f"{row['independent_minus_frozen_scaled']} | "
            f"{row['winner_by_scaled_cost']} | "
            f"{row['independent_raw_feasible_routes']} | "
            f"{row['frozen_raw_feasible_routes']} | "
            f"{row['independent_completed_clients']}/"
            f"{row['independent_total_clients']} | "
            f"{row['frozen_completed_clients']}/"
            f"{row['frozen_total_clients']} |"
        )
    lines.extend(
        [
            "",
            "每次运行的完整路线、逐代轨迹、环境与代码指纹、原始精度逐路线审计，"
            "保存在对应运行目录。完成需求量见顶层 raw_runs.csv。",
            "",
        ]
    )
    return "\n".join(lines)


def _batch_artifact_hashes(output: Path, seed: int) -> None:
    files = [
        output / "batch_metadata.json",
        output / "raw_runs.csv",
        output / "decision.json",
        output / "report.md",
        output / "progress.log",
        output / "launch_report.md",
    ]
    for instance in INSTANCES:
        for arm in ARMS:
            package = _run_dir(output, instance, arm, seed)
            files.extend(
                package / name
                for name in (
                    "metadata.json",
                    "raw_runs.csv",
                    "best_solution.json",
                    "audit.json",
                    "decision.json",
                    "artifact_hashes.json",
                    "report.md",
                )
            )
    _json(output / "artifact_hashes.json", _hash_files(files))


def _probe_main(args: argparse.Namespace) -> int:
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite probe {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    returncode = _run_one_subprocess(
        output_dir=output,
        instance=args.instance,
        arm=args.arm,
        seed=args.seed,
        max_runtime_seconds=args.max_runtime_seconds,
        no_improvement=args.no_improvement,
        run_kind="probe",
        sisr_enabled=args.sisr_enabled,
    )
    if returncode != 0:
        return returncode
    package = _validate_run_package(output)
    print(
        json.dumps(
            {
                "probe": "COMPLETE",
                "output": str(output),
                "trace_rows": package["trace_rows"],
                "audit": package["audit"]["summary"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


def _batch_main(args: argparse.Namespace) -> int:
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    progress = output / "progress.log"
    if progress.exists() or (output / "DONE").exists():
        raise FileExistsError(
            "refusing to start over an existing formal batch state"
        )
    for instance in INSTANCES:
        for arm in ARMS:
            if _run_dir(output, instance, arm, args.seed).exists():
                raise FileExistsError(
                    f"formal run directory already exists: {instance} {arm}"
                )
    _atomic_text(progress, "")
    _atomic_text(output / "batch.pid", f"{os.getpid()}\n")
    batch_metadata = {
        "status": "RUNNING",
        "evidence_level": "approved formal candidate comparison",
        "started_at": _timestamp(),
        "orchestrator_pid": os.getpid(),
        "launch_label": args.launch_label,
        "instances": list(INSTANCES),
        "arms_in_order_per_instance": list(ARMS),
        "run_count": len(INSTANCES) * len(ARMS),
        "seed": args.seed,
        "max_runtime_seconds_per_run": args.max_runtime_seconds,
        "no_improvement_iterations": args.no_improvement,
        "round_func": ROUND_FUNC,
        "integer_scale": INTEGER_SCALE,
        "strictly_serial": True,
        "machine": _machine_identity(),
        "controller_python": sys.executable,
        "runner_sha256": _sha256(Path(__file__).resolve()),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_porcelain": _git("status", "--porcelain"),
    }
    _json(output / "batch_metadata.json", batch_metadata)

    try:
        for instance in INSTANCES:
            for arm in ARMS:
                run_output = _run_dir(output, instance, arm, args.seed)
                returncode = _run_one_subprocess(
                    output_dir=run_output,
                    instance=instance,
                    arm=arm,
                    seed=args.seed,
                    max_runtime_seconds=args.max_runtime_seconds,
                    no_improvement=args.no_improvement,
                    run_kind="formal",
                    sisr_enabled=False,
                )
                if returncode != 0:
                    raise RuntimeError(
                        f"worker failed: {instance} {arm} exit={returncode}"
                    )
                package = _validate_run_package(run_output)
                _append_progress(progress, instance, arm, package)
    except BaseException as error:
        batch_metadata.update(
            {
                "status": "FAILED",
                "finished_at": _timestamp(),
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
        _json(output / "batch_metadata.json", batch_metadata)
        _json(
            output / "batch_failure.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
            },
        )
        traceback.print_exc()
        return 1

    rows = _pair_summary(output, args.seed)
    _write_csv(output / "raw_runs.csv", rows)
    decision = {
        "verdict": "FORMAL_CANDIDATE_BATCH_COMPLETE",
        "completed_runs": len(INSTANCES) * len(ARMS),
        "instances": len(INSTANCES),
        "independent_wins_by_scaled_cost": sum(
            row["winner_by_scaled_cost"] == "independent" for row in rows
        ),
        "frozen_wins_by_scaled_cost": sum(
            row["winner_by_scaled_cost"] == "frozen_pyvrp" for row in rows
        ),
        "ties_by_scaled_cost": sum(
            row["winner_by_scaled_cost"] == "tie" for row in rows
        ),
        "all_independent_routes_raw_feasible": all(
            bool(row["independent_all_routes_raw_feasible"])
            for row in rows
        ),
        "all_frozen_routes_raw_feasible": all(
            bool(row["frozen_all_routes_raw_feasible"]) for row in rows
        ),
        "selection_or_filtering_applied": False,
    }
    _json(output / "decision.json", decision)
    _atomic_text(output / "report.md", _batch_report(rows))
    batch_metadata.update(
        {"status": "COMPLETE", "finished_at": _timestamp()}
    )
    _json(output / "batch_metadata.json", batch_metadata)
    _batch_artifact_hashes(output, args.seed)
    _atomic_text(
        output / "DONE",
        f"FORMAL_CANDIDATE_BATCH_COMPLETE {_timestamp()}\n",
    )
    print(json.dumps(decision, ensure_ascii=False), flush=True)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    worker = commands.add_parser("worker")
    worker.add_argument("output_dir", type=Path)
    worker.add_argument("--instance", choices=INSTANCES, required=True)
    worker.add_argument("--arm", choices=ARMS, required=True)
    worker.add_argument("--seed", type=int, default=11)
    worker.add_argument("--max-runtime-seconds", type=float, required=True)
    worker.add_argument("--no-improvement", type=int, default=5_000)
    worker.add_argument("--run-kind", choices=("probe", "formal"), required=True)
    worker.add_argument("--sisr-enabled", action="store_true")

    probe = commands.add_parser("probe")
    probe.add_argument("output_dir", type=Path)
    probe.add_argument("--instance", choices=INSTANCES, default="PR11A")
    probe.add_argument("--arm", choices=ARMS, default="independent")
    probe.add_argument("--seed", type=int, default=11)
    probe.add_argument("--max-runtime-seconds", type=float, default=60.0)
    probe.add_argument("--no-improvement", type=int, default=5_000)
    probe.add_argument("--sisr-enabled", action="store_true")

    batch = commands.add_parser("batch")
    batch.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    batch.add_argument("--seed", type=int, default=11)
    batch.add_argument("--max-runtime-seconds", type=float, default=1200.0)
    batch.add_argument("--no-improvement", type=int, default=5_000)
    batch.add_argument("--launch-label")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "batch" and args.seed != 11:
        raise ValueError("this approved batch is fixed to seed 11")
    if args.max_runtime_seconds <= 0 or args.max_runtime_seconds > 1200:
        raise ValueError("runtime must be in (0, 1200] seconds")
    if args.no_improvement < 1:
        raise ValueError("no-improvement iterations must be positive")
    if args.command == "worker":
        return _worker_main(args)
    if args.command == "probe":
        return _probe_main(args)
    return _batch_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
