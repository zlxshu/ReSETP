"""Shared Homberger development-bundle helpers retained after SISR retirement."""

from __future__ import annotations

from dataclasses import asdict
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np


REPO = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO / "solver/src"
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

from setp_solver.prices import PriceParameters  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import Route, Solution  # noqa: E402


BUNDLES = REPO / "baselines/e2_alns/homberger_200_development_bundles_20260717"
TOL = 1e-8


class DevelopmentGateError(RuntimeError):
    """A contract or infrastructure failure in a development gate."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    data = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def clean_generated_appledouble(root: Path) -> int:
    """Remove macOS AppleDouble sidecars only inside this generated output."""
    removed = 0
    for path in sorted(root.rglob("._*"), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink()
            removed += 1
    leftovers = [path for path in root.rglob("._*") if path.exists()]
    if leftovers:
        raise DevelopmentGateError(
            f"AppleDouble cleanup incomplete under {root}: {leftovers}"
        )
    return removed


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
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
    )


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(
        {
            key: (
                json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (dict, list, tuple))
                else value
            )
            for key, value in row.items()
        }
        for row in rows
    )
    atomic_text(path, buffer.getvalue())


def git_output(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def solution_payload(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [
            asdict(item) for item in solution.cross_site_services
        ],
    }


def bundle_contract(name: str) -> dict[str, Any]:
    root = BUNDLES / name
    payload = json.loads((root / "instance.json").read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
    if "bks" in serialized or "reference_code" in serialized:
        raise DevelopmentGateError(f"development bundle leaks reference data: {name}")
    bundle = load_search_bundle(root)
    matrix = np.asarray(bundle.instance.distance_matrix, dtype=float)
    customer_count = sum(
        str(node.node_type).lower() == "c" for node in bundle.instance.nodes
    )
    max_vehicles = int(bundle.instance.num_cv or 0)
    max_edge = float(np.max(matrix))
    upper_bound = float((customer_count + max_vehicles) * max_edge)
    big_m = float(math.floor(upper_bound) + 1)
    if not big_m > upper_bound:
        raise DevelopmentGateError(f"big-M proof failed: {name}")
    metadata = payload["metadata"]
    return {
        "bundle": bundle,
        "capacity": float(metadata["vehicle_capacity"]),
        "customer_count": customer_count,
        "max_vehicles": max_vehicles,
        "max_edge": max_edge,
        "distance_upper_bound": upper_bound,
        "big_m": big_m,
        "bundle_hashes": {
            filename: sha256(root / filename)
            for filename in (
                "instance.json",
                "distance_matrix.npy",
                "carbon_profile.csv",
            )
        },
    }


def vrptw_prices(*, capacity: float, big_m: float) -> PriceParameters:
    """Map the shared evaluator exactly to big_M * vehicles + distance."""

    return PriceParameters(
        Q_capacity=float(capacity),
        v_speed_ms=1.0,
        diesel_price=0.0,
        carbon_price=0.0,
        diesel_ef=0.0,
        vehicle_fixed_cost=float(big_m),
        occupancy_fee=0.0,
        cross_site_cost=0.0,
        revenue_per_kg=0.0,
        c_km=1000.0,
    )


def deterministic_common_initial_solution(
    instance: Any,
    *,
    capacity: float,
) -> Solution:
    """Build a BKS-blind feasible start by earliest due time then proximity."""

    depots = [
        node for node in instance.nodes if str(node.node_type).lower() == "d"
    ]
    if len(depots) != 1:
        raise DevelopmentGateError("Homberger development requires one depot")
    depot = depots[0]
    customers = {
        node.node_id: node
        for node in instance.nodes
        if str(node.node_type).lower() == "c"
    }
    remaining = set(customers)
    plans: list[list[str]] = []
    while remaining:
        sequence: list[str] = []
        load = 0.0
        current = depot.node_id
        clock = float(depot.ready_time)
        while True:
            feasible: list[tuple[tuple[float, float, str], str, float]] = []
            for customer_id in remaining:
                node = customers[customer_id]
                if load + float(node.demand) > float(capacity) + TOL:
                    continue
                arrival = clock + float(instance.distance(current, customer_id))
                service_start = max(arrival, float(node.ready_time))
                finish = service_start + float(node.service_time)
                depot_arrival = finish + float(
                    instance.distance(customer_id, depot.node_id)
                )
                if (
                    service_start <= float(node.due_time) + TOL
                    and depot_arrival <= float(depot.due_time) + TOL
                ):
                    feasible.append(
                        (
                            (
                                float(node.due_time),
                                float(instance.distance(current, customer_id)),
                                customer_id,
                            ),
                            customer_id,
                            finish,
                        )
                    )
            if not feasible:
                break
            _, customer_id, finish = min(feasible, key=lambda item: item[0])
            sequence.append(customer_id)
            remaining.remove(customer_id)
            load += float(customers[customer_id].demand)
            current = customer_id
            clock = finish
        if not sequence:
            raise DevelopmentGateError(
                "common-start constructor found no feasible single customer"
            )
        plans.append(sequence)
    if len(plans) > int(instance.num_cv or 0):
        raise DevelopmentGateError(
            f"common start exceeds fleet cap: {len(plans)}>{instance.num_cv}"
        )
    return Solution(
        routes=[
            Route(
                f"CV{index}",
                "cv",
                depot.node_id,
                [depot.node_id, *sequence, depot.node_id],
            )
            for index, sequence in enumerate(plans, start=1)
        ]
    )


def independent_vrptw_recompute(
    solution: Solution,
    *,
    bundle: Any,
    capacity: float,
) -> dict[str, Any]:
    instance = bundle.instance
    nodes = {node.node_id: node for node in instance.nodes}
    customers = {
        node.node_id
        for node in instance.nodes
        if str(node.node_type).lower() == "c"
    }
    depots = [
        node.node_id
        for node in instance.nodes
        if str(node.node_type).lower() == "d"
    ]
    failures: list[str] = []
    if len(depots) != 1:
        return {"passed": False, "failures": [f"depot count: {len(depots)}"]}
    depot = depots[0]
    visited: list[str] = []
    distance = 0.0
    if len(solution.routes) > int(instance.num_cv or 0):
        failures.append("FLEET_SIZE")
    for route_index, route in enumerate(solution.routes, start=1):
        sequence = list(route.node_sequence)
        if (
            len(sequence) < 3
            or sequence[0] != depot
            or sequence[-1] != depot
            or route.vehicle_type.lower() != "cv"
        ):
            failures.append(f"ROUTE_SHAPE:{route_index}")
            continue
        interior = sequence[1:-1]
        if any(node_id not in customers for node_id in interior):
            failures.append(f"ROUTE_INTERIOR:{route_index}")
        visited.extend(interior)
        load = sum(float(nodes[node_id].demand) for node_id in interior)
        if load > float(capacity) + TOL:
            failures.append(f"CAPACITY:{route_index}")
        clock = float(nodes[depot].ready_time)
        for source, target in zip(sequence, sequence[1:]):
            travel = float(instance.distance(source, target))
            distance += travel
            arrival = clock + travel
            service_start = max(arrival, float(nodes[target].ready_time))
            if service_start > float(nodes[target].due_time) + TOL:
                failures.append(f"TIME_WINDOW:{route_index}:{target}")
            clock = service_start + float(nodes[target].service_time)
    if (
        len(visited) != len(customers)
        or len(set(visited)) != len(customers)
        or set(visited) != customers
    ):
        failures.append("COVERAGE")
    return {
        "passed": not failures,
        "failures": failures,
        "route_count": len(solution.routes),
        "distance_double": distance,
        "visited_customer_count": len(visited),
    }
