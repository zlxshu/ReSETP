#!/usr/bin/env python3
"""Freeze the V13 MDVRPTW comparison foundation without solver search.

The script downloads and freezes:

* the original Vidal et al. (2013) benchmark archive;
* the 28 normalised instances and current BKS routes from PyVRP/Instances;
* the classic HGSADC paper, the 2026 MDFIHA paper, and license/citation files.

It then checks that the original and normalised instances are semantically
equivalent, validates every BKS with both PyVRP and a small independent
validator, extracts the published VCGP/MDFIHA/MDFIHA-ETGA targets, and emits
the five mandatory evidence surfaces.  It never calls a solver or evaluates a
search candidate.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import re
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import pyvrp


REPO = Path(__file__).resolve().parents[1]
OUTPUT = (
    REPO
    / "baselines"
    / "algorithm_foundation"
    / "mdvrptw_v13_comparison_20260719"
)

INSTANCES_COMMIT = "1cf23a5969fabf23c80f8002e42ed501a47aca61"
PYVRP_TAG = "v0.13.4"
PYVRP_TAG_COMMIT = "18815548d04a90a0e5eea2a0bed53a81ea9d2d49"
ORIGINAL_ZIP_URL = (
    "https://w1.cirrelt.ca/~vidalt/resources/"
    "Vidal_al13_C%26OR_benchmark.zip"
)
VCGP_PAPER_URL = (
    "https://www.cirrelt.ca/documentstravail/cirrelt-2011-61.pdf"
)
MDFIHA_PAPER_URL = "https://arxiv.org/pdf/2605.05208v1"
PYVRP_RAW = f"https://raw.githubusercontent.com/PyVRP/PyVRP/{PYVRP_TAG_COMMIT}"
INSTANCES_RAW = (
    "https://raw.githubusercontent.com/PyVRP/Instances/"
    f"{INSTANCES_COMMIT}"
)

INSTANCE_NAMES = tuple(
    f"PR{number}{variant}"
    for number in range(11, 25)
    for variant in ("A", "B")
)
DEVELOPMENT = (
    "PR11A",
    "PR11B",
    "PR17A",
    "PR17B",
    "PR21A",
    "PR21B",
)
CONFIRMATION = (
    "PR16A",
    "PR16B",
    "PR20A",
    "PR20B",
    "PR24A",
    "PR24B",
)
REPRESENTATIVE = "PR17A"
CORE_OUTPUTS = (
    "metadata.json",
    "raw_runs.csv",
    "opponent_targets.csv",
    "selection.json",
    "decision.json",
    "report.md",
    "artifact_hashes.json",
)


@dataclass(frozen=True)
class Node:
    node_id: int
    x: float
    y: float
    service: float
    demand: float
    tw_early: float
    tw_late: float


@dataclass(frozen=True)
class OriginalInstance:
    problem_type: int
    vehicles_per_depot: int
    num_clients: int
    num_depots: int
    max_durations: tuple[float, ...]
    capacities: tuple[float, ...]
    clients: tuple[Node, ...]
    depots: tuple[Node, ...]


@dataclass(frozen=True)
class NormalisedInstance:
    name: str
    dimension: int
    num_vehicles: int
    capacity: float
    max_duration: float
    coords: dict[int, tuple[float, float]]
    demands: dict[int, float]
    services: dict[int, float]
    time_windows: dict[int, tuple[float, float]]
    vehicle_depots: dict[int, int]
    depot_ids: tuple[int, ...]

    @property
    def num_depots(self) -> int:
        return len(self.depot_ids)

    @property
    def num_clients(self) -> int:
        return self.dimension - self.num_depots


def fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "ReSETP-foundation-freezer/1"})
    with urlopen(request, timeout=90) as response:
        return response.read()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_original(text: str) -> OriginalInstance:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header = [int(token) for token in lines[0].split()]
    if len(header) != 4:
        raise ValueError(f"unexpected original header: {lines[0]}")
    problem_type, vehicles_per_depot, num_clients, num_depots = header
    if problem_type != 6:
        raise ValueError(f"unexpected original problem type: {problem_type}")

    max_durations: list[float] = []
    capacities: list[float] = []
    for line in lines[1 : 1 + num_depots]:
        duration, capacity = (float(token) for token in line.split())
        max_durations.append(duration)
        capacities.append(capacity)

    nodes: list[Node] = []
    for line in lines[1 + num_depots :]:
        tokens = line.split()
        node_id = int(tokens[0])
        x = float(tokens[1])
        y = float(tokens[2])
        service = float(tokens[3])
        demand = float(tokens[4])
        num_combinations = int(tokens[6])
        tw_offset = 7 + num_combinations
        tw_early = float(tokens[tw_offset])
        tw_late = float(tokens[tw_offset + 1])
        if len(tokens) != tw_offset + 2:
            raise ValueError(f"unexpected original row width: {line}")
        nodes.append(
            Node(
                node_id,
                x,
                y,
                service,
                demand,
                tw_early,
                tw_late,
            )
        )
    if len(nodes) != num_clients + num_depots:
        raise ValueError("original instance node count mismatch")
    clients = tuple(nodes[:num_clients])
    depots = tuple(nodes[num_clients:])
    return OriginalInstance(
        problem_type,
        vehicles_per_depot,
        num_clients,
        num_depots,
        tuple(max_durations),
        tuple(capacities),
        clients,
        depots,
    )


def parse_normalised(text: str) -> NormalisedInstance:
    headers: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line == "EOF":
            continue
        if line.endswith("_SECTION"):
            current = line
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()

    def pairs(section: str) -> dict[int, float]:
        return {
            int(parts[0]): float(parts[1])
            for parts in (
                line.split() for line in sections.get(section, [])
            )
        }

    coords = {
        int(parts[0]): (float(parts[1]), float(parts[2]))
        for parts in (
            line.split() for line in sections["NODE_COORD_SECTION"]
        )
    }
    time_windows = {
        int(parts[0]): (float(parts[1]), float(parts[2]))
        for parts in (
            line.split() for line in sections["TIME_WINDOW_SECTION"]
        )
    }
    vehicle_depots = {
        int(parts[0]): int(parts[1])
        for parts in (
            line.split() for line in sections["VEHICLES_DEPOT_SECTION"]
        )
    }
    depot_ids = tuple(
        int(line)
        for line in sections["DEPOT_SECTION"]
        if int(line) >= 0
    )
    return NormalisedInstance(
        name=headers["NAME"].upper(),
        dimension=int(headers["DIMENSION"]),
        num_vehicles=int(headers["VEHICLES"]),
        capacity=float(headers["CAPACITY"]),
        max_duration=float(headers["VEHICLES_MAX_DURATION"]),
        coords=coords,
        demands=pairs("DEMAND_SECTION"),
        services=pairs("SERVICE_TIME_SECTION"),
        time_windows=time_windows,
        vehicle_depots=vehicle_depots,
        depot_ids=depot_ids,
    )


def same_number(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0, abs_tol=1e-9)


def compare_semantics(
    original: OriginalInstance,
    normalised: NormalisedInstance,
) -> dict[str, Any]:
    checks: list[tuple[str, bool]] = []

    def add(label: str, passed: bool) -> None:
        checks.append((label, bool(passed)))

    add("num_clients", original.num_clients == normalised.num_clients)
    add("num_depots", original.num_depots == normalised.num_depots)
    add(
        "num_vehicles",
        original.vehicles_per_depot * original.num_depots
        == normalised.num_vehicles,
    )
    add(
        "uniform_capacity",
        len(set(original.capacities)) == 1
        and same_number(original.capacities[0], normalised.capacity),
    )
    add(
        "uniform_max_duration",
        len(set(original.max_durations)) == 1
        and same_number(
            original.max_durations[0],
            normalised.max_duration,
        ),
    )
    add(
        "depot_ids",
        normalised.depot_ids == tuple(range(1, original.num_depots + 1)),
    )

    for index, node in enumerate(original.depots, start=1):
        add(f"depot_{index}_coords", normalised.coords[index] == (node.x, node.y))
        add(
            f"depot_{index}_time_window",
            normalised.time_windows[index]
            == (node.tw_early, node.tw_late),
        )
        add(
            f"depot_{index}_vehicle_count",
            sum(
                depot == index
                for depot in normalised.vehicle_depots.values()
            )
            == original.vehicles_per_depot,
        )

    offset = original.num_depots
    for client in original.clients:
        node_id = offset + client.node_id
        add(
            f"client_{client.node_id}_coords",
            normalised.coords[node_id] == (client.x, client.y),
        )
        add(
            f"client_{client.node_id}_demand",
            same_number(normalised.demands[node_id], client.demand),
        )
        add(
            f"client_{client.node_id}_service",
            same_number(normalised.services[node_id], client.service),
        )
        add(
            f"client_{client.node_id}_time_window",
            normalised.time_windows[node_id]
            == (client.tw_early, client.tw_late),
        )

    failed = [label for label, passed in checks if not passed]
    return {
        "checks": len(checks),
        "failed_checks": failed,
        "all_checks_pass": not failed,
    }


def parse_solution(text: str, num_vehicles: int) -> tuple[dict[int, list[int]], int]:
    routes: dict[int, list[int]] = {}
    declared_cost: int | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        route_match = re.match(r"^Route\s+#(\d+):\s*(.*)$", line)
        if route_match:
            route_id = int(route_match.group(1))
            payload = route_match.group(2).strip()
            routes[route_id] = (
                [int(token) for token in payload.split()] if payload else []
            )
            continue
        cost_match = re.match(r"^Cost:\s*(\d+)\s*$", line)
        if cost_match:
            declared_cost = int(cost_match.group(1))
    if tuple(sorted(routes)) != tuple(range(1, num_vehicles + 1)):
        raise ValueError("solution does not enumerate every vehicle route")
    if declared_cost is None:
        raise ValueError("solution has no declared cost")
    return routes, declared_cost


def scaled(value: float) -> int:
    return int(round(value * 1000))


def arc_distance(
    coords: dict[int, tuple[float, float]],
    left: int,
    right: int,
) -> int:
    x1, y1 = coords[left]
    x2, y2 = coords[right]
    return int(round(math.hypot(x1 - x2, y1 - y2) * 1000))


def validate_solution_independently(
    instance: NormalisedInstance,
    routes: dict[int, list[int]],
    declared_cost: int,
) -> dict[str, Any]:
    # PyVRP solution files use zero-based internal location indices, whereas
    # the VRPLIB instance sections use one-based node identifiers.  Convert
    # every route token back to the instance identifier before checking it.
    instance_routes = {
        vehicle: [client + 1 for client in route]
        for vehicle, route in routes.items()
    }
    expected_clients = set(range(instance.num_depots + 1, instance.dimension + 1))
    observed_clients = [
        client for route in instance_routes.values() for client in route
    ]
    coverage_ok = (
        set(observed_clients) == expected_clients
        and len(observed_clients) == len(expected_clients)
    )
    no_depot_as_client = all(
        client not in instance.depot_ids for client in observed_clients
    )

    total_distance = 0
    load_failures: list[int] = []
    schedule_failures: list[int] = []
    duration_failures: list[int] = []
    max_load = scaled(instance.capacity)
    max_duration = scaled(instance.max_duration)
    demands = {node: scaled(value) for node, value in instance.demands.items()}
    services = {
        node: scaled(value) for node, value in instance.services.items()
    }
    windows = {
        node: (scaled(early), scaled(late))
        for node, (early, late) in instance.time_windows.items()
    }

    for vehicle, route in instance_routes.items():
        depot = instance.vehicle_depots[vehicle]
        path = [depot, *route, depot]
        total_distance += sum(
            arc_distance(instance.coords, left, right)
            for left, right in zip(path, path[1:])
        )
        if sum(demands[node] for node in route) > max_load:
            load_failures.append(vehicle)
        if not route:
            continue

        next_node = depot
        latest_next = windows[depot][1]
        latest_service: dict[int, int] = {}
        feasible = True
        for node in reversed(route):
            candidate = (
                latest_next
                - arc_distance(instance.coords, node, next_node)
                - services[node]
            )
            latest = min(windows[node][1], candidate)
            if latest < windows[node][0]:
                feasible = False
            latest_service[node] = latest
            latest_next = latest
            next_node = node
        start = min(
            windows[depot][1],
            latest_next - arc_distance(instance.coords, depot, next_node),
        )
        if start < windows[depot][0]:
            feasible = False

        current = start
        previous = depot
        for node in route:
            arrival = (
                current
                + services[previous]
                + arc_distance(instance.coords, previous, node)
            )
            current = max(arrival, windows[node][0])
            if current > windows[node][1]:
                feasible = False
            previous = node
        end_time = (
            current
            + services[previous]
            + arc_distance(instance.coords, previous, depot)
        )
        if end_time > windows[depot][1]:
            feasible = False
        if not feasible:
            schedule_failures.append(vehicle)
        if end_time - start > max_duration:
            duration_failures.append(vehicle)

    return {
        "coverage_ok": coverage_ok,
        "no_depot_as_client": no_depot_as_client,
        "load_failures": load_failures,
        "schedule_failures": schedule_failures,
        "duration_failures": duration_failures,
        "recomputed_cost": total_distance,
        "declared_cost": declared_cost,
        "cost_match": total_distance == declared_cost,
        "all_checks_pass": (
            coverage_ok
            and no_depot_as_client
            and not load_failures
            and not schedule_failures
            and not duration_failures
            and total_distance == declared_cost
        ),
    }


def validate_with_pyvrp(instance_path: Path, solution_path: Path) -> dict[str, Any]:
    data = pyvrp.read(instance_path, round_func="exact")
    solution = pyvrp.read_solution(solution_path, data)
    return {
        "complete": solution.is_complete(),
        "feasible": solution.is_feasible(),
        "num_clients": solution.num_clients(),
        "num_missing_clients": solution.num_missing_clients(),
        "num_routes": solution.num_routes(),
        "distance": solution.distance(),
        "all_checks_pass": solution.is_complete() and solution.is_feasible(),
    }


def extract_mdfiha_targets(pdf_path: Path) -> dict[str, dict[str, float]]:
    completed = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"pdftotext failed: {completed.stderr}")
    text = completed.stdout
    start = text.find("Table A8")
    end = text.find("Mean", start)
    if start < 0 or end < 0:
        raise ValueError("could not locate MDFIHA Table A8")

    rows: dict[str, dict[str, float]] = {}
    pattern = re.compile(
        r"^\s*(pr\d+[ab])\s+"
        r"(\d+)\s+(\d+)\s+(\d+)\s+"
        r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+"
        r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([-\d.]+)\s+"
        r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([-\d.]+)\s*$"
    )
    for line in text[start:end].splitlines():
        match = pattern.match(line)
        if not match:
            continue
        (
            name,
            clients,
            depots,
            vehicles_per_depot,
            vcgp_best,
            vcgp_mean,
            vcgp_time,
            mdfiha_best,
            mdfiha_mean,
            mdfiha_time,
            mdfiha_gap,
            etga_best,
            etga_mean,
            etga_time,
            etga_gap,
        ) = match.groups()
        rows[name.upper()] = {
            "clients": int(clients),
            "depots": int(depots),
            "vehicles_per_depot": int(vehicles_per_depot),
            "vcgp_best": float(vcgp_best),
            "vcgp_mean": float(vcgp_mean),
            "vcgp_converted_time_s": float(vcgp_time),
            "mdfiha_best": float(mdfiha_best),
            "mdfiha_mean": float(mdfiha_mean),
            "mdfiha_time_s": float(mdfiha_time),
            "mdfiha_gap_percent_vs_vcgp": float(mdfiha_gap),
            "mdfiha_etga_best": float(etga_best),
            "mdfiha_etga_mean": float(etga_mean),
            "mdfiha_etga_time_s": float(etga_time),
            "mdfiha_etga_gap_percent_vs_vcgp": float(etga_gap),
        }
    if tuple(sorted(rows)) != tuple(sorted(INSTANCE_NAMES)):
        raise ValueError(
            f"MDFIHA Table A8 mismatch: extracted {len(rows)} rows"
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_hash_manifest(root: Path) -> dict[str, Any]:
    entries = []
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or path.name == "artifact_hashes.json"
            or path.name.startswith("._")
        ):
            continue
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "algorithm": "sha256",
        "root": root.name,
        "files": entries,
    }


def main() -> int:
    for filename in CORE_OUTPUTS:
        if (OUTPUT / filename).exists():
            raise FileExistsError(
                f"refusing to overwrite existing evidence: {OUTPUT / filename}"
            )

    started = datetime.now(timezone.utc)
    sources = OUTPUT / "sources"
    original_dir = sources / "original_mdvrptw"
    instance_dir = sources / "normalised_instances"
    solution_dir = sources / "current_bks"
    paper_dir = sources / "papers"
    legal_dir = sources / "licenses_and_citations"
    for directory in (
        original_dir,
        instance_dir,
        solution_dir,
        paper_dir,
        legal_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    original_zip_bytes = fetch(ORIGINAL_ZIP_URL)
    original_zip_path = sources / "Vidal_al13_COR_benchmark.zip"
    original_zip_path.write_bytes(original_zip_bytes)
    with zipfile.ZipFile(BytesIO(original_zip_bytes)) as archive:
        for name in INSTANCE_NAMES:
            member = (
                "Vidal_al13_C&OR_benchmark/MDVRPTW/"
                f"{name.lower()}.txt"
            )
            (original_dir / f"{name.lower()}.txt").write_bytes(
                archive.read(member)
            )
        (original_dir / "README.txt").write_bytes(
            archive.read("Vidal_al13_C&OR_benchmark/README.txt")
        )

    downloads = {
        paper_dir / "vidal_hgsadc_2013.pdf": VCGP_PAPER_URL,
        paper_dir / "lei_hao_wu_mdfiha_2026_v1.pdf": MDFIHA_PAPER_URL,
        legal_dir / "pyvrp_LICENSE.md": f"{PYVRP_RAW}/LICENSE.md",
        legal_dir / "pyvrp_CITATION.cff": f"{PYVRP_RAW}/CITATION.cff",
        legal_dir
        / "pyvrp_instances_LICENSE": f"{INSTANCES_RAW}/LICENSE",
        legal_dir
        / "pyvrp_instances_README.md": f"{INSTANCES_RAW}/MDVRPTW/README.md",
    }
    for path, url in downloads.items():
        path.write_bytes(fetch(url))

    semantic_results: dict[str, dict[str, Any]] = {}
    independent_results: dict[str, dict[str, Any]] = {}
    pyvrp_results: dict[str, dict[str, Any]] = {}
    normalised_instances: dict[str, NormalisedInstance] = {}
    current_bks: dict[str, float] = {}

    for name in INSTANCE_NAMES:
        instance_bytes = fetch(
            f"{INSTANCES_RAW}/MDVRPTW/{name}.vrp"
        )
        solution_bytes = fetch(
            f"{INSTANCES_RAW}/MDVRPTW/{name}.sol"
        )
        instance_path = instance_dir / f"{name}.vrp"
        solution_path = solution_dir / f"{name}.sol"
        instance_path.write_bytes(instance_bytes)
        solution_path.write_bytes(solution_bytes)

        original = parse_original(
            (original_dir / f"{name.lower()}.txt").read_text(
                encoding="utf-8",
                errors="replace",
            )
        )
        normalised = parse_normalised(
            instance_bytes.decode("utf-8")
        )
        if normalised.name != name:
            raise ValueError(f"{name}: normalised name mismatch")
        semantic = compare_semantics(original, normalised)
        if not semantic["all_checks_pass"]:
            raise ValueError(f"{name}: semantic mismatch: {semantic}")

        routes, declared_cost = parse_solution(
            solution_bytes.decode("utf-8"),
            normalised.num_vehicles,
        )
        independent = validate_solution_independently(
            normalised,
            routes,
            declared_cost,
        )
        official = validate_with_pyvrp(instance_path, solution_path)
        if not independent["all_checks_pass"]:
            raise ValueError(
                f"{name}: independent BKS validation failed: {independent}"
            )
        if (
            not official["all_checks_pass"]
            or official["distance"] != declared_cost
        ):
            raise ValueError(
                f"{name}: PyVRP BKS validation failed: {official}"
            )
        semantic_results[name] = semantic
        independent_results[name] = independent
        pyvrp_results[name] = official
        normalised_instances[name] = normalised
        current_bks[name] = declared_cost / 1000

    mdfiha_targets = extract_mdfiha_targets(
        paper_dir / "lei_hao_wu_mdfiha_2026_v1.pdf"
    )
    raw_rows: list[dict[str, Any]] = []
    target_rows: list[dict[str, Any]] = []
    for index, name in enumerate(INSTANCE_NAMES, start=1):
        instance = normalised_instances[name]
        paper = mdfiha_targets[name]
        if (
            paper["clients"] != instance.num_clients
            or paper["depots"] != instance.num_depots
            or paper["vehicles_per_depot"]
            != instance.num_vehicles // instance.num_depots
        ):
            raise ValueError(f"{name}: paper/instance dimensions differ")
        split = (
            "development"
            if name in DEVELOPMENT
            else "confirmation"
            if name in CONFIRMATION
            else "sealed_holdout"
        )
        values = {
            "current_verified_bks": current_bks[name],
            "vcgp_best_2013": paper["vcgp_best"],
            "mdfiha_best_2026": paper["mdfiha_best"],
            "mdfiha_etga_best_2026": paper["mdfiha_etga_best"],
        }
        strongest = min(values.values())
        strongest_sources = sorted(
            source for source, value in values.items() if value == strongest
        )
        raw_rows.append(
            {
                "index": index,
                "instance": name,
                "clients": instance.num_clients,
                "depots": instance.num_depots,
                "vehicles_per_depot": (
                    instance.num_vehicles // instance.num_depots
                ),
                "variant": name[-1],
                "split": split,
                "representative": str(name == REPRESENTATIVE).lower(),
                "semantic_checks": semantic_results[name]["checks"],
                "semantic_failures": len(
                    semantic_results[name]["failed_checks"]
                ),
                "independent_bks_valid": str(
                    independent_results[name]["all_checks_pass"]
                ).lower(),
                "pyvrp_bks_valid": str(
                    pyvrp_results[name]["all_checks_pass"]
                ).lower(),
                "current_verified_bks": current_bks[name],
                "vcgp_best_2013": paper["vcgp_best"],
                "vcgp_mean_2013": paper["vcgp_mean"],
                "mdfiha_best_2026": paper["mdfiha_best"],
                "mdfiha_mean_2026": paper["mdfiha_mean"],
                "mdfiha_etga_best_2026": paper["mdfiha_etga_best"],
                "mdfiha_etga_mean_2026": paper["mdfiha_etga_mean"],
                "strongest_known_target": strongest,
                "strongest_target_sources": "|".join(strongest_sources),
            }
        )
        target_rows.append(
            {
                "instance": name,
                **values,
                "strongest_known_target": strongest,
                "strongest_target_sources": "|".join(strongest_sources),
                "strict_new_bks_target": f"< {strongest:.3f}",
                "target_route_certificate_available": str(
                    "current_verified_bks" in strongest_sources
                ).lower(),
            }
        )

    write_csv(OUTPUT / "raw_runs.csv", raw_rows)
    write_csv(OUTPUT / "opponent_targets.csv", target_rows)

    selection = {
        "public_family": "V13_MDVRPTW_28",
        "selection_order": (
            "algorithm_roles_then_common_benchmark_intersection"
        ),
        "representative_instance": REPRESENTATIVE,
        "representative_rule": [
            "select the median depot-count stratum (6 depots)",
            "select the smallest client count in that stratum",
            "break the A/B tie lexicographically",
        ],
        "development": list(DEVELOPMENT),
        "confirmation": list(CONFIRMATION),
        "sealed_holdout": [
            name
            for name in INSTANCE_NAMES
            if name not in DEVELOPMENT and name not in CONFIRMATION
        ],
        "development_rule": (
            "smallest instance in every depot-count x A/B stratum"
        ),
        "confirmation_rule": (
            "largest instance in every depot-count x A/B stratum"
        ),
        "final_public_table_requires_all_28": True,
        "china81_is_only_full_model_family": True,
        "china81_search_performed": False,
    }
    write_json(OUTPUT / "selection.json", selection)

    finished = datetime.now(timezone.utc)
    metadata = {
        "contract": "ALGO-COMPARE-FOUNDATION-003",
        "purpose": (
            "zero-search source, opponent, BKS, and split freeze for "
            "V13 MDVRPTW"
        ),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "pyvrp_validator_version": version("pyvrp"),
        },
        "sources": {
            "original_zip": {
                "url": ORIGINAL_ZIP_URL,
                "sha256": sha256_file(original_zip_path),
            },
            "instances_repo_commit": INSTANCES_COMMIT,
            "pyvrp_release": PYVRP_TAG,
            "pyvrp_release_commit": PYVRP_TAG_COMMIT,
            "vcgp_paper_url": VCGP_PAPER_URL,
            "mdfiha_paper_url": MDFIHA_PAPER_URL,
        },
        "counts": {
            "instances": len(INSTANCE_NAMES),
            "semantic_equivalence_pass": sum(
                result["all_checks_pass"]
                for result in semantic_results.values()
            ),
            "independent_bks_pass": sum(
                result["all_checks_pass"]
                for result in independent_results.values()
            ),
            "pyvrp_bks_pass": sum(
                result["all_checks_pass"]
                for result in pyvrp_results.values()
            ),
            "paper_target_rows": len(mdfiha_targets),
            "search_evaluations": 0,
            "solver_calls": 0,
        },
        "prohibited_actions_confirmed": {
            "performance_search": False,
            "parameter_tuning": False,
            "china81_read_or_solved": False,
            "stage2_started": False,
        },
    }
    write_json(OUTPUT / "metadata.json", metadata)

    decision = {
        "verdict": "PASS_MDVRPTW_V13_COMPARISON_FOUNDATION_ZERO_SEARCH",
        "all_28_original_normalised_semantics_match": True,
        "all_28_current_bks_independently_valid": True,
        "all_28_current_bks_pyvrp_valid": True,
        "all_28_published_opponent_rows_extracted": True,
        "representative_instance": REPRESENTATIVE,
        "performance_search_authorized": False,
        "china81_authorized": False,
        "stage2_authorized": False,
        "next_allowed_action": (
            "build and run a no-performance same-path wiring gate"
        ),
        "honest_boundary": (
            "This proves the comparison foundation, not algorithm superiority."
        ),
    }
    write_json(OUTPUT / "decision.json", decision)

    report = f"""# V13-MDVRPTW-28 比较基础零搜索报告

## 结论

判定：`{decision["verdict"]}`。

- 作者原始 28 题与 PyVRP 规范化 28 题逐字段语义核对全部通过；
- 当前 28 个 BKS 路线由 PyVRP 官方解析器与项目独立解析器双重验真；
- 2026 MDFIHA 论文 Table A8 的 VCGP、MDFIHA、MDFIHA-ETGA 逐题值
  28/28 抽取；
- 开发 6 题、确认 6 题、封存 16 题及代表题 `{REPRESENTATIVE}`
  均由结果盲结构规则生成；
- 搜索评价 0、求解器调用 0、China81 未读未跑、阶段二未启动。

## 诚实边界

这个 PASS 只说明题、对手、最好解和划分方式已经闭合。它不说明本文算法已经赢，
也不放行性能搜索。下一步最多允许做关闭增强时逐位退回母体的接线检查。

## 冻结版本

- PyVRP/Instances：`{INSTANCES_COMMIT}`
- PyVRP：`{PYVRP_TAG}` / `{PYVRP_TAG_COMMIT}`
- 本次校验环境 PyVRP：`{version("pyvrp")}`
- 作者原始压缩包 SHA-256：`{sha256_file(original_zip_path)}`
"""
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    write_json(
        OUTPUT / "artifact_hashes.json",
        build_hash_manifest(OUTPUT),
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
