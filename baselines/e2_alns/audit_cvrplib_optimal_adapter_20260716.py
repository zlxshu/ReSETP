#!/usr/bin/env python3
"""Audit the six-instance CVRPLIB optimal-solution adapter for E2.

This is a zero-search gate.  It verifies the official raw files, reconstructs
the CVRPLIB rounded-Euclidean objective, and then independently re-evaluates
the same published solutions through ReSETP's checker and cost evaluator under
an explicit distance-only CVRP degeneration.  Passing this gate authorizes a
later frozen search contract; it does not claim that ReSETP reaches the optima.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO / "solver/src"
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

from setp_solver.check import check_solution  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.instance_loader import Instance, Node  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.solution import Route, Solution  # noqa: E402


RAW = REPO / "baselines/e2_alns/cvrplib_optimal_benchmark_20260716/raw"
OUT = REPO / "baselines/e2_alns/cvrplib_optimal_benchmark_20260716"
SOURCE_URL = "https://galgos.inf.puc-rio.br/cvrplib/en/instances"
INSTANCES = (
    "X-n101-k25",
    "X-n120-k6",
    "X-n200-k36",
    "X-n214-k11",
    "X-n313-k71",
    "X-n322-k28",
)


@dataclass(frozen=True)
class ParsedCVRP:
    name: str
    dimension: int
    capacity: int
    coordinates: dict[int, tuple[float, float]]
    demands: dict[int, int]
    depot: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_instance(path: Path) -> ParsedCVRP:
    lines = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    headers: dict[str, str] = {}
    sections: dict[str, list[str]] = {"NODE_COORD_SECTION": [], "DEMAND_SECTION": [], "DEPOT_SECTION": []}
    active: str | None = None
    for line in lines:
        if line in sections:
            active = line
            continue
        if line == "EOF":
            break
        if active is not None:
            sections[active].append(line)
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip().strip('"')
    if headers.get("TYPE") != "CVRP" or headers.get("EDGE_WEIGHT_TYPE") != "EUC_2D":
        raise ValueError(f"unsupported CVRPLIB semantics in {path.name}: {headers}")
    coordinates = {
        int(parts[0]): (float(parts[1]), float(parts[2]))
        for parts in (line.split() for line in sections["NODE_COORD_SECTION"])
    }
    demands = {
        int(parts[0]): int(float(parts[1]))
        for parts in (line.split() for line in sections["DEMAND_SECTION"])
    }
    depot_rows = [int(line.split()[0]) for line in sections["DEPOT_SECTION"] if int(line.split()[0]) >= 0]
    if len(depot_rows) != 1:
        raise ValueError(f"expected one depot in {path.name}, got {depot_rows}")
    dimension = int(headers["DIMENSION"])
    if len(coordinates) != dimension or len(demands) != dimension:
        raise ValueError(f"dimension mismatch in {path.name}")
    return ParsedCVRP(
        name=headers["NAME"],
        dimension=dimension,
        capacity=int(headers["CAPACITY"]),
        coordinates=coordinates,
        demands=demands,
        depot=depot_rows[0],
    )


def parse_solution(path: Path) -> tuple[list[list[int]], int]:
    routes: list[list[int]] = []
    cost: int | None = None
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line.startswith("Route #"):
            routes.append([int(value) for value in line.split(":", 1)[1].split()])
        elif line.startswith("Cost"):
            cost = int(round(float(line.split()[-1])))
    if not routes or cost is None:
        raise ValueError(f"invalid CVRPLIB solution file: {path}")
    return routes, cost


def nint(value: float) -> int:
    """TSPLIB/CVRPLIB nearest integer, avoiding Python's bankers rounding."""

    return int(math.floor(float(value) + 0.5))


def distance(problem: ParsedCVRP, source: int, target: int) -> int:
    x1, y1 = problem.coordinates[source]
    x2, y2 = problem.coordinates[target]
    return nint(math.hypot(x1 - x2, y1 - y2))


def official_to_node_id(problem: ParsedCVRP, customer_index: int) -> int:
    """CVRPLIB .sol numbers customers after removing the single depot."""

    customers = sorted(node for node in problem.coordinates if node != problem.depot)
    if not (1 <= customer_index <= len(customers)):
        raise ValueError(f"customer index {customer_index} is outside 1..{len(customers)}")
    return customers[customer_index - 1]


def reconstruct(problem: ParsedCVRP, routes: list[list[int]]) -> tuple[int, list[list[int]]]:
    mapped = [[official_to_node_id(problem, customer) for customer in route] for route in routes]
    objective = 0
    for route in mapped:
        sequence = [problem.depot, *route, problem.depot]
        objective += sum(distance(problem, a, b) for a, b in zip(sequence, sequence[1:]))
    return objective, mapped


def resetp_instance(problem: ParsedCVRP) -> Instance:
    ordered = sorted(problem.coordinates)
    nodes = [
        Node(
            node_id=f"N{node}",
            node_type="d" if node == problem.depot else "c",
            x=problem.coordinates[node][0],
            y=problem.coordinates[node][1],
            demand=float(problem.demands[node]),
            ready_time=0.0,
            due_time=1.0e12,
            service_time=0.0,
        )
        for node in ordered
    ]
    matrix = [[float(distance(problem, a, b)) for b in ordered] for a in ordered]
    return Instance(nodes=nodes, distance_matrix=matrix, num_cv=None, num_ev=0)


def resetp_solution(problem: ParsedCVRP, mapped_routes: list[list[int]]) -> Solution:
    depot_id = f"N{problem.depot}"
    return Solution(
        routes=[
            Route(
                vehicle_id=f"CV{index}",
                vehicle_type="cv",
                home_depot_id=depot_id,
                node_sequence=[depot_id, *(f"N{node}" for node in route), depot_id],
            )
            for index, route in enumerate(mapped_routes, start=1)
        ]
    )


def distance_only_prices(capacity: int):
    # distance_total is interpreted as metres by the generic evaluator;
    # c_km=1000 makes one rounded CVRPLIB distance unit cost exactly one.
    return replace(
        DEFAULT_PRICES,
        Q_capacity=float(capacity),
        c_km=1000.0,
        vehicle_fixed_cost=0.0,
        diesel_price=0.0,
        electricity_price=0.0,
        station_electricity_price=0.0,
        depot_electricity_price=0.0,
        occupancy_fee=0.0,
        cross_site_cost=0.0,
        carbon_price=0.0,
        diesel_ef=0.0,
    )


def audit_one(name: str) -> dict[str, object]:
    vrp_path = RAW / f"{name}.vrp"
    sol_path = RAW / f"{name}.sol"
    problem = parse_instance(vrp_path)
    routes, official_cost = parse_solution(sol_path)
    reconstructed, mapped_routes = reconstruct(problem, routes)
    flat = [node for route in mapped_routes for node in route]
    expected_customers = sorted(node for node in problem.coordinates if node != problem.depot)
    all_customers_once = sorted(flat) == expected_customers and len(flat) == len(set(flat))
    route_loads = [sum(problem.demands[node] for node in route) for route in mapped_routes]
    capacity_feasible = all(load <= problem.capacity for load in route_loads)

    instance = resetp_instance(problem)
    solution = resetp_solution(problem, mapped_routes)
    prices = distance_only_prices(problem.capacity)
    violations = check_solution(solution, instance, prices)
    evaluated = evaluate(solution, instance, [], prices, carbon_quota_kg=math.inf)
    resetp_cost = float(evaluated["total_cost"])

    k_match = re.search(r"-k([0-9]+)$", name)
    advertised_k = int(k_match.group(1)) if k_match else None
    capacity_lb = math.ceil(sum(problem.demands.values()) / problem.capacity)
    passed = (
        reconstructed == official_cost
        and abs(resetp_cost - official_cost) <= 1e-9
        and all_customers_once
        and capacity_feasible
        and not violations
    )
    return {
        "instance": name,
        "customers": problem.dimension - 1,
        "capacity": problem.capacity,
        "advertised_min_vehicles_k": advertised_k,
        "capacity_lower_bound": capacity_lb,
        "published_solution_routes": len(routes),
        "published_optimum": official_cost,
        "independent_reconstruction": reconstructed,
        "resetp_distance_only_evaluation": resetp_cost,
        "all_customers_once": all_customers_once,
        "capacity_feasible": capacity_feasible,
        "resetp_violation_count": len(violations),
        "max_route_load": max(route_loads),
        "instance_sha256": sha256(vrp_path),
        "solution_sha256": sha256(sol_path),
        "passed": passed,
    }


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [audit_one(name) for name in INSTANCES]
    all_passed = all(bool(row["passed"]) for row in rows)
    verdict = "PASS_CVRPLIB_OPTIMAL_ADAPTER_GATE" if all_passed else "HALT_CVRPLIB_OPTIMAL_ADAPTER_GATE"
    write_csv(rows, OUT / "raw_runs.csv")

    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "schema_version": "resetp.e2.cvrplib-optimal-adapter.v1",
        "created_at_utc": now,
        "source": SOURCE_URL,
        "downloaded_at": "2026-07-16",
        "official_status_at_download": "Opt=yes for all six selected instances",
        "instance_tiers": {
            "small": ["X-n101-k25", "X-n120-k6"],
            "medium": ["X-n200-k36", "X-n214-k11"],
            "large": ["X-n313-k71", "X-n322-k28"],
        },
        "objective_contract": "CVRPLIB EUC_2D nearest-integer total distance; no fixed, energy, carbon, charging, time-window, or cross-site term",
        "claim_boundary": "adapter and evaluator semantics only; no ReSETP search-performance claim",
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    decision = {
        "verdict": verdict,
        "passed": all_passed,
        "authorized_next_step": "freeze a separate multi-seed same-budget search contract" if all_passed else "none",
        "forbidden_claims": [
            "ReSETP reaches the published optima",
            "the full mixed-fleet time-varying-carbon model is externally validated",
        ],
    }
    (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# CVRPLIB公开最优算例适配门",
        "",
        f"判决：`{verdict}`。本门不运行搜索，只检验公开原始文件、距离取整、容量约束、解文件编号和本文评价器的退化语义。",
        "",
        "六个算例均来自CVRPLIB X集，下载时官网均标为`Opt=yes`。算例按100--119、199--213、312--321个客户分为小、中、大三档，每档两个。",
        "",
        "| 算例 | 客户数 | 官网最优值 | 独立复算 | 本文评价器 | 路线数 | k | 容量下界 | 结论 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['instance']} | {row['customers']} | {row['published_optimum']} | "
            f"{row['independent_reconstruction']} | {row['resetp_distance_only_evaluation']:.0f} | "
            f"{row['published_solution_routes']} | {row['advertised_min_vehicles_k']} | "
            f"{row['capacity_lower_bound']} | {'通过' if row['passed'] else '失败'} |"
        )
    lines.extend(
        [
            "",
            "这里的`k`是实例标识中的最小车辆数信息，不是本文多趟实体车上限。正式适配采用无车辆固定费的距离目标，并以每条路线独立编号；公开最优解可能使用多于`k`条路线，因此不能把`k`错误写成严格路线数上限。",
            "",
            "通过本门只说明：公开最优解在CVRPLIB标准取整下可被逐弧复算，且同一解经本文通用容量检查器与距离目标评价器得到完全相同的数值。下一步仍需单独冻结搜索预算、随机种子、失败记录和训练/测试隔离，之后才能报告算法Gap。",
        ]
    )
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    hash_targets = [
        *(RAW / f"{name}.{suffix}" for name in INSTANCES for suffix in ("vrp", "sol")),
        OUT / "raw_runs.csv",
        OUT / "metadata.json",
        OUT / "decision.json",
        OUT / "report.md",
    ]
    hashes = {str(path.relative_to(REPO)): sha256(path) for path in hash_targets}
    (OUT / "artifact_hashes.json").write_text(json.dumps(hashes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "rows": rows}, ensure_ascii=False, indent=2))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
