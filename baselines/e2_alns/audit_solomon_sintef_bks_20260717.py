#!/usr/bin/env python3
"""Fetch and independently audit the SINTEF Solomon-100 BKS table.

This is a zero-search source and arithmetic gate.  It verifies the published
hierarchical BKS pairs (vehicle count, double-precision distance) against the
56 detailed route files and the frozen local Solomon instance archive.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from bs4 import BeautifulSoup


REPO = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO / "baselines/e2_alns/reference_snapshots/sintef_solomon_100_20260717.html"
SOLUTIONS = REPO / "baselines/e2_alns/reference_snapshots/sintef_solomon_solutions_20260717"
DEFAULT_ZIP = Path("/Volumes/移动硬盘（512G）/VRP/算例/solomon-100.zip")
DEFAULT_OUT = REPO / "baselines/e2_alns/e2_solomon_sintef_bks_audit_20260717"
BASE_URL = "https://www.sintef.no"
EXPECTED_HTML_SHA256 = "e5aeb667eb858a2b6d52cedf15770ad66c001cb456af4001f2dc4165b8cb8294"
EXPECTED_ZIP_SHA256 = "8a0a72cbe6b7f8f9988ace4ebde0378ec34943acaaac47f2c408915e41887747"
EXPECTED_CLASS_COUNTS = {"C1": 9, "C2": 8, "R1": 12, "R2": 11, "RC1": 8, "RC2": 8}
DISPLAY_ALIASES = {"R205B": "R205", "RC101B": "RC101"}
TOL = 1e-7


class AuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class Node:
    idx: int
    x: int
    y: int
    demand: int
    ready: int
    due: int
    service: int


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
        if temporary.exists():
            temporary.unlink()


def atomic_json(path: Path, payload: Any) -> None:
    atomic_text(path, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    buffer = io.StringIO(newline="")
    fields = list(rows[0]) if rows else []
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(path, buffer.getvalue())


def instance_class(name: str) -> str:
    match = re.fullmatch(r"(RC|C|R)([12])\d{2}", name)
    if not match:
        raise AuditError(f"unexpected Solomon instance name: {name}")
    return f"{match.group(1)}{match.group(2)}"


def parse_instance(data: bytes) -> tuple[str, int, int, dict[int, Node]]:
    text = data.decode("ascii")
    name = next(line.strip().upper() for line in text.splitlines() if line.strip())
    vehicle_match = re.search(r"NUMBER\s+CAPACITY\s+(\d+)\s+(\d+)", text, re.DOTALL)
    if not vehicle_match:
        raise AuditError(f"vehicle header missing in {name}")
    max_vehicles, capacity = map(int, vehicle_match.groups())
    nodes: dict[int, Node] = {}
    for line in text.splitlines():
        values = re.fullmatch(r"\s*(\d+)\s+(-?\d+)\s+(-?\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*", line)
        if values:
            node = Node(*map(int, values.groups()))
            nodes[node.idx] = node
    if set(nodes) != set(range(101)):
        raise AuditError(f"node set differs for {name}")
    return name, max_vehicles, capacity, nodes


def parse_bks_table(snapshot: Path) -> list[dict[str, Any]]:
    soup = BeautifulSoup(snapshot.read_text(encoding="utf-8"), "html.parser")
    table = next(
        table for table in soup.find_all("table")
        if [cell.get_text(" ", strip=True) for cell in table.find_all("td")[:5]]
        == ["Instance", "Vehicles", "Distance", "Reference", "Comment"]
    )
    rows: list[dict[str, Any]] = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all("td")
        if len(cells) != 5:
            continue
        values = [cell.get_text(" ", strip=True) for cell in cells]
        if not values[0]:
            continue
        display_name = values[0].upper()
        name = DISPLAY_ALIASES.get(display_name, display_name)
        link = cells[0].find("a")
        distance_text = values[2].replace("*", "")
        rows.append(
            {
                "instance": name,
                "display_name": display_name,
                "class": instance_class(name),
                "bks_vehicles": int(values[1]),
                "bks_distance": float(distance_text),
                "reference_code": values[3],
                "comment": values[4],
                "solution_url": urllib.parse.urljoin(BASE_URL, str(link["href"])),
            }
        )
    return rows


def fetch_solutions(rows: list[dict[str, Any]], root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for row in rows:
        target = root / f"{row['instance'].lower()}.txt"
        if target.is_file():
            continue
        request = urllib.request.Request(str(row["solution_url"]), headers={"User-Agent": "ReSETP-research-audit/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
        if b"Route" not in payload:
            raise AuditError(f"detailed solution is malformed: {row['instance']}")
        temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
        temporary.write_bytes(payload)
        os.replace(temporary, target)


def parse_routes(path: Path) -> list[list[int]]:
    routes: list[list[int]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = re.fullmatch(r"\s*Route\s+\d+\s*:\s*(.*?)\s*", line)
        if match:
            routes.append([int(value) for value in match.group(1).split()])
    if not routes:
        raise AuditError(f"no routes found in {path}")
    return routes


def distance(a: Node, b: Node) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def round_two(value: float) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def recompute(routes: list[list[int]], nodes: dict[int, Node], capacity: int) -> dict[str, Any]:
    failures: list[str] = []
    visited: list[int] = []
    total_distance = 0.0
    for route_number, customers in enumerate(routes, start=1):
        visited.extend(customers)
        load = sum(nodes[idx].demand for idx in customers)
        if load > capacity:
            failures.append(f"route {route_number} capacity {load}>{capacity}")
        sequence = [0, *customers, 0]
        clock = float(nodes[0].ready)
        for source, target in zip(sequence, sequence[1:]):
            leg = distance(nodes[source], nodes[target])
            total_distance += leg
            arrival = clock + leg
            service_start = max(arrival, float(nodes[target].ready))
            if service_start > float(nodes[target].due) + TOL:
                failures.append(f"route {route_number} time window at {target}: {service_start}>{nodes[target].due}")
            clock = service_start + float(nodes[target].service)
    if len(visited) != 100 or len(set(visited)) != 100 or set(visited) != set(range(1, 101)):
        failures.append("customer coverage is not exactly once")
    return {
        "valid": not failures,
        "failures": failures,
        "route_count": len(routes),
        "distance_double": total_distance,
        "distance_rounded_2": round_two(total_distance),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    parser.add_argument("--solutions", type=Path, default=SOLUTIONS)
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--fetch-solutions", action="store_true")
    args = parser.parse_args()

    if args.output.exists() and any(item for item in args.output.iterdir() if not item.name.startswith("._")):
        raise SystemExit(f"refuse to overwrite non-empty output directory: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    if sha256_path(args.snapshot) != EXPECTED_HTML_SHA256:
        failures.append("SINTEF HTML snapshot hash differs")
    if sha256_path(args.zip) != EXPECTED_ZIP_SHA256:
        failures.append("Solomon instance archive hash differs")

    bks_rows = parse_bks_table(args.snapshot)
    if len(bks_rows) != 56 or len({row["instance"] for row in bks_rows}) != 56:
        failures.append(f"expected 56 unique BKS rows, got {len(bks_rows)}")
    if args.fetch_solutions:
        fetch_solutions(bks_rows, args.solutions)

    with ZipFile(args.zip) as archive:
        members = {Path(name).name.lower(): name for name in archive.namelist() if name.lower().endswith(".txt")}
        audited: list[dict[str, Any]] = []
        for row in bks_rows:
            name = str(row["instance"])
            solution_path = args.solutions / f"{name.lower()}.txt"
            member = members.get(f"{name.lower()}.txt")
            if member is None or not solution_path.is_file():
                failures.append(f"missing frozen input or solution for {name}")
                continue
            parsed_name, max_vehicles, capacity, nodes = parse_instance(archive.read(member))
            result = recompute(parse_routes(solution_path), nodes, capacity)
            vehicle_match = result["route_count"] == row["bks_vehicles"]
            distance_match = result["distance_rounded_2"] == f"{row['bks_distance']:.2f}"
            if parsed_name != name:
                failures.append(f"instance name mismatch for {name}: {parsed_name}")
            if not result["valid"]:
                failures.append(f"infeasible detailed solution for {name}: {result['failures']}")
            if not vehicle_match:
                failures.append(f"vehicle BKS mismatch for {name}")
            if not distance_match:
                failures.append(
                    f"distance BKS mismatch for {name}: {result['distance_rounded_2']} != {row['bks_distance']:.2f}"
                )
            audited.append(
                {
                    **row,
                    "max_vehicles": max_vehicles,
                    "capacity": capacity,
                    "computed_vehicles": result["route_count"],
                    "computed_distance_double": f"{result['distance_double']:.12f}",
                    "computed_distance_rounded_2": result["distance_rounded_2"],
                    "vehicle_match": int(vehicle_match),
                    "distance_match": int(distance_match),
                    "solution_feasible": int(result["valid"]),
                    "solution_sha256": sha256_path(solution_path),
                    "search_evaluations": 0,
                }
            )

    class_counts = Counter(str(row["class"]) for row in audited)
    if dict(class_counts) != EXPECTED_CLASS_COUNTS:
        failures.append(f"class counts differ: {dict(class_counts)}")
    atomic_csv(args.output / "raw_runs.csv", audited)
    metadata = {
        "schema_version": "resetp.e2.solomon-sintef-bks-audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "search_performed": False,
        "source_url": "https://www.sintef.no/projectweb/top/vrptw/100-customers/",
        "snapshot_path": str(args.snapshot),
        "snapshot_sha256": sha256_path(args.snapshot),
        "instance_zip_path": str(args.zip),
        "instance_zip_sha256": sha256_path(args.zip),
        "objective": ["minimize vehicle count", "then minimize double-precision total distance"],
        "distance_reporting": "double precision; total rounded to two decimals",
        "expected_instances": 56,
        "class_counts": dict(class_counts),
        "detailed_solution_hashes": {
            path.name: sha256_path(path)
            for path in sorted(args.solutions.glob("*.txt"))
            if not path.name.startswith("._")
        },
    }
    atomic_json(args.output / "metadata.json", metadata)
    verdict = "PASS_SOLOMON_SINTEF_BKS_ZERO_SEARCH_AUDIT" if not failures else "FAIL_SOLOMON_SINTEF_BKS_ZERO_SEARCH_AUDIT"
    decision = {
        "verdict": verdict,
        "failures": failures,
        "instances_verified": len(audited),
        "formal_search_authorized": False,
        "search_evaluations": 0,
        "next_gate": "freeze the final algorithm without reading Solomon results",
    }
    atomic_json(args.output / "decision.json", decision)
    report = [
        "# Solomon/SINTEF BKS零搜索审计",
        "",
        f"判定：`{verdict}`。",
        "",
        f"逐项复算 {len(audited)}/56 份官方详细解；搜索评价次数为0。",
        "目标口径为先最少车辆、再最短总距离；弧长和行驶时间采用双精度欧氏距离，总距离保留两位小数。",
        "每份详细解均检查客户恰好服务一次、载重、硬时间窗、车辆数和总距离。",
        "BKS在后续正式测试中只作为事后评价基准，不向搜索器提供详细路线。",
    ]
    if failures:
        report.extend(["", "## 失败项", "", *[f"- {item}" for item in failures]])
    atomic_text(args.output / "report.md", "\n".join(report) + "\n")
    artifacts = {
        str(path.relative_to(args.output)): sha256_path(path)
        for path in sorted(args.output.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    artifacts[str(Path(__file__).relative_to(REPO))] = sha256_path(Path(__file__))
    atomic_json(args.output / "artifact_hashes.json", artifacts)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
