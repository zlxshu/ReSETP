"""Independently certify full-reproduction witnesses without importing PyVRP."""

from __future__ import annotations

import json
import math
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
INSTANCE_DIR = (
    ROOT
    / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
    / "sources/normalised_instances"
)


def _parse_vrp(path: Path) -> dict[str, Any]:
    header: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.rstrip()
        if not value or value == "EOF":
            continue
        if value.endswith("SECTION"):
            current = value
            sections[current] = []
            continue
        if current is None:
            if ":" in value:
                key, item = value.split(":", 1)
                header[key.strip()] = item.strip()
            continue
        sections[current].append(value)
    coordinates = {}
    demand = {}
    service = {}
    windows = {}
    for row in sections["NODE_COORD_SECTION"]:
        parts = row.split()
        coordinates[int(parts[0])] = (float(parts[1]), float(parts[2]))
    for row in sections["DEMAND_SECTION"]:
        parts = row.split()
        demand[int(parts[0])] = int(float(parts[1]))
    for row in sections["SERVICE_TIME_SECTION"]:
        parts = row.split()
        service[int(parts[0])] = float(parts[1])
    for row in sections["TIME_WINDOW_SECTION"]:
        parts = row.split()
        windows[int(parts[0])] = (float(parts[1]), float(parts[2]))
    depots = [
        int(row.split()[0]) for row in sections["DEPOT_SECTION"] if row.strip() != "-1"
    ]
    vehicle_depots = [int(row.split()[1]) for row in sections["VEHICLES_DEPOT_SECTION"]]
    return {
        "coordinates": coordinates,
        "demand": demand,
        "service": service,
        "windows": windows,
        "depots": depots,
        "vehicle_depots": vehicle_depots,
        "capacity": int(header["CAPACITY"]),
        "max_duration": float(header.get("VEHICLES_MAX_DURATION", "inf")),
        "dimension": int(header["DIMENSION"]),
    }


def _distance(left: int, right: int, coordinates) -> int:
    x1, y1 = coordinates[left]
    x2, y2 = coordinates[right]
    return round(math.hypot(x1 - x2, y1 - y2) * 1000)


def _certificate(instance_id: str, witness: dict[str, Any]) -> dict[str, Any]:
    data = _parse_vrp(INSTANCE_DIR / f"{instance_id}.vrp")
    routes = []
    for route_key in witness["routes"]:
        vehicle_type, visits = route_key.split("|", 1)
        routes.append(
            (
                int(vehicle_type),
                [int(value) + 1 for value in visits.split(",") if value],
            )
        )
    total = 0
    for vehicle_type, visits in routes:
        depot = data["depots"][vehicle_type]
        sequence = [depot, *visits, depot]
        total += sum(
            _distance(left, right, data["coordinates"])
            for left, right in pairwise(sequence)
        )
    served = [client for _, visits in routes for client in visits]
    clients = set(range(len(data["depots"]) + 1, data["dimension"] + 1))
    served_once = (
        len(served) == len(set(served)) == len(clients) and set(served) == clients
    )
    fleet_caps = Counter(data["vehicle_depots"])
    fleet_used = Counter(data["depots"][vehicle_type] for vehicle_type, _ in routes)
    vehicle_caps_ok = all(
        fleet_used[depot] <= fleet_caps[depot] for depot in fleet_used
    )
    capacity_violations = 0
    time_window_violations = 0
    duration_violations = 0
    for vehicle_type, visits in routes:
        depot = data["depots"][vehicle_type]
        if sum(data["demand"][client] for client in visits) > data["capacity"]:
            capacity_violations += 1
        sequence = [depot, *visits, depot]
        time = data["windows"][depot][0] * 1000
        start = time
        waiting = 0.0
        for left, right in pairwise(sequence):
            if left != depot:
                time += data["service"].get(left, 0.0) * 1000
            time += _distance(left, right, data["coordinates"])
            earliest, latest = data["windows"][right]
            if time > latest * 1000 + 1e-6:
                time_window_violations += 1
            if time < earliest * 1000:
                waiting += earliest * 1000 - time
                time = earliest * 1000
        if time - start - waiting > data["max_duration"] * 1000 + 1e-6:
            duration_violations += 1
    claimed = int(witness["cost_scaled"])
    passed = (
        total == claimed
        and served_once
        and vehicle_caps_ok
        and capacity_violations == 0
        and time_window_violations == 0
        and duration_violations == 0
    )
    return {
        "schema": "resetp.mvhgssp-bks-full.certificate.v1",
        "instance_id": instance_id,
        "claimed_scaled": claimed,
        "recomputed_scaled": total,
        "cost_match": total == claimed,
        "served_once": served_once,
        "vehicle_caps_ok": vehicle_caps_ok,
        "capacity_violations": capacity_violations,
        "time_window_violations": time_window_violations,
        "duration_violations_after_shift": duration_violations,
        "certificate": "PASS" if passed else "FAIL",
    }


def main() -> int:
    rows = json.loads((HERE / "raw_runs.json").read_text(encoding="utf-8"))
    reports = []
    for row in rows:
        witness_path = ROOT / row["witness_path"]
        witness = json.loads(witness_path.read_text(encoding="utf-8"))
        report = _certificate(row["instance_id"], witness)
        output = witness_path.parent / "independent_certificate.json"
        output.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        reports.append(report)
        print(f"{row['instance_id']}: {report['certificate']}", flush=True)
    summary = {
        "schema": "resetp.mvhgssp-bks-full.certificate-summary.v1",
        "evaluated": len(reports),
        "passed": sum(report["certificate"] == "PASS" for report in reports),
        "failed": sum(report["certificate"] != "PASS" for report in reports),
        "reports": reports,
    }
    (HERE / "certificate_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
