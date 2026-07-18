"""Strict Python-to-CLI bridge for the pinned official HGS-CVRP executable.

The C++ engine remains unchanged and isolated.  This module verifies the local
install manifest, runs the executable, and independently checks the returned
CVRP solution.  It intentionally refuses non-CVRP and non-EUC_2D instances.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PINNED_COMMIT = "1a927955cd2861a29d978f0d359d6e647db9319c"
INSTALL_SCHEMA = "resetp.official-hgs-cvrp-install.v1"
RESULT_SCHEMA = "resetp.official-hgs-cvrp-result.v1"


@dataclass(frozen=True)
class CVRPInstance:
    name: str
    dimension: int
    capacity: int
    coordinates: dict[int, tuple[float, float]]
    demands: dict[int, int]
    depot: int


@dataclass(frozen=True)
class HGSConfig:
    seed: int
    time_limit_seconds: float
    round_distances: bool = True
    vehicle_limit: int | None = None

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.time_limit_seconds <= 0:
            raise ValueError("time_limit_seconds must be positive")
        if self.vehicle_limit is not None and self.vehicle_limit <= 0:
            raise ValueError("vehicle_limit must be positive")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_install(manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != INSTALL_SCHEMA:
        raise ValueError("unsupported HGS install manifest schema")
    if payload.get("pinned_commit") != PINNED_COMMIT:
        raise ValueError("HGS install commit differs from the pinned commit")
    if payload.get("license") != "MIT" or payload.get("upstream_tests") != "PASS":
        raise ValueError("HGS install lacks the required license/test evidence")
    binary = Path(str(payload.get("binary", "")))
    if not binary.is_file() or sha256(binary) != payload.get("binary_sha256"):
        raise ValueError("HGS binary is missing or its hash differs")
    return payload


def parse_cvrplib(path: Path) -> CVRPInstance:
    lines = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    headers: dict[str, str] = {}
    sections: dict[str, list[str]] = {
        "NODE_COORD_SECTION": [],
        "DEMAND_SECTION": [],
        "DEPOT_SECTION": [],
    }
    active: str | None = None
    for line in lines:
        if line in sections:
            active = line
            continue
        if line == "EOF":
            break
        if active is not None:
            sections[active].append(line)
        elif ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip().strip('"')
    if headers.get("TYPE") != "CVRP":
        raise ValueError("official HGS bridge accepts TYPE=CVRP only")
    if headers.get("EDGE_WEIGHT_TYPE") != "EUC_2D":
        raise ValueError("this audited bridge accepts EDGE_WEIGHT_TYPE=EUC_2D only")
    coordinates = {
        int(parts[0]): (float(parts[1]), float(parts[2]))
        for parts in (line.split() for line in sections["NODE_COORD_SECTION"])
    }
    demands = {
        int(parts[0]): int(float(parts[1]))
        for parts in (line.split() for line in sections["DEMAND_SECTION"])
    }
    depots = [
        int(line.split()[0])
        for line in sections["DEPOT_SECTION"]
        if int(line.split()[0]) >= 0
    ]
    dimension = int(headers["DIMENSION"])
    if len(depots) != 1 or len(coordinates) != dimension or len(demands) != dimension:
        raise ValueError("instance structure is incomplete or inconsistent")
    return CVRPInstance(
        name=headers["NAME"],
        dimension=dimension,
        capacity=int(headers["CAPACITY"]),
        coordinates=coordinates,
        demands=demands,
        depot=depots[0],
    )


def nint(value: float) -> int:
    return int(math.floor(float(value) + 0.5))


def distance(problem: CVRPInstance, source: int, target: int) -> int:
    x1, y1 = problem.coordinates[source]
    x2, y2 = problem.coordinates[target]
    return nint(math.hypot(x1 - x2, y1 - y2))


def parse_and_validate_solution(problem: CVRPInstance, solution_path: Path) -> dict[str, Any]:
    encoded_routes: list[list[int]] = []
    announced_cost: float | None = None
    for raw in solution_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.startswith("Route #"):
            encoded_routes.append([int(value) for value in line.split(":", 1)[1].split()])
        elif line.startswith("Cost"):
            announced_cost = float(line.split()[-1])
    if not encoded_routes or announced_cost is None:
        raise ValueError("HGS solution file is incomplete")

    customers = sorted(node for node in problem.coordinates if node != problem.depot)
    routes: list[list[int]] = []
    for route in encoded_routes:
        if any(index < 1 or index > len(customers) for index in route):
            raise ValueError("HGS solution contains an out-of-range customer index")
        routes.append([customers[index - 1] for index in route])
    flat = [node for route in routes for node in route]
    failures = []
    if sorted(flat) != customers or len(flat) != len(set(flat)):
        failures.append("CUSTOMER_COVERAGE_NOT_EXACTLY_ONCE")
    route_loads = [sum(problem.demands[node] for node in route) for route in routes]
    if any(load > problem.capacity for load in route_loads):
        failures.append("CAPACITY_EXCEEDED")
    route_costs = []
    for route in routes:
        sequence = [problem.depot, *route, problem.depot]
        route_costs.append(
            sum(distance(problem, source, target) for source, target in zip(sequence, sequence[1:]))
        )
    reconstructed = float(sum(route_costs))
    if abs(reconstructed - announced_cost) > 1.0e-9:
        failures.append("ANNOUNCED_COST_MISMATCH")
    return {
        "passed": not failures,
        "failures": failures,
        "cost": reconstructed,
        "announced_cost": announced_cost,
        "route_count": len(routes),
        "route_loads": route_loads,
        "route_costs": route_costs,
        "routes_original_node_ids": routes,
    }


def run_official_hgs(
    instance_path: Path,
    solution_path: Path,
    install_manifest: Path,
    config: HGSConfig,
) -> dict[str, Any]:
    install = load_install(install_manifest)
    problem = parse_cvrplib(instance_path)
    solution_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(install["binary"]),
        str(instance_path.resolve()),
        str(solution_path.resolve()),
        "-t",
        str(config.time_limit_seconds),
        "-seed",
        str(config.seed),
        "-round",
        "1" if config.round_distances else "0",
        "-log",
        "0",
    ]
    if config.vehicle_limit is not None:
        command.extend(["-veh", str(config.vehicle_limit)])
    began = time.perf_counter()
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=max(60.0, config.time_limit_seconds + 30.0),
        check=False,
    )
    elapsed = time.perf_counter() - began
    if completed.returncode != 0 or not solution_path.is_file():
        raise RuntimeError(
            f"official HGS failed with return code {completed.returncode}: "
            f"{completed.stdout}{completed.stderr}"
        )
    validation = parse_and_validate_solution(problem, solution_path)
    result = {
        "schema_version": RESULT_SCHEMA,
        "algorithm": "official_vidal_hgs_cvrp",
        "official_commit": PINNED_COMMIT,
        "instance": problem.name,
        "instance_sha256": sha256(instance_path),
        "solution_sha256": sha256(solution_path),
        "config": asdict(config),
        "elapsed_seconds": elapsed,
        "returncode": completed.returncode,
        "validation": validation,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "claim_boundary": (
            "Validated CVRP result only; no ReSETP time-window, fleet, SOC, charging, "
            "carbon, fairness, or multi-depot semantics are represented."
        ),
    }
    if not validation["passed"]:
        raise RuntimeError(f"official HGS returned an invalid solution: {validation['failures']}")
    return result
