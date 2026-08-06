#!/usr/bin/env python3
"""Read-only T12 witness replay; never runs search or edits archived runs."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "solver/src"))

from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.check import CHARGING_TRIP_OVERLAP, check_solution  # noqa: E402
from setp_solver.search.multitrip_schedule import route_timing  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    CrossSiteService,
    Route,
    Solution,
    charging_action_from_dict,
    physical_vehicle_id,
)

INSTANCE = "cn-jjj-50c-01-V2-LOCATIONS"
AUTHORITY = REPO / "data/ChinaInstances/china81_finite_fleet_authority_v3_20260802"
POSITIVE = ("C_seed2_budget1000", "C_seed1_budget100", "C_seed3_budget1000")
T10 = REPO / "docs/handoff/intertrip_charging_fix_20260804"
T9_RAW = REPO / "docs/handoff/intertrip_overlap_scan_20260804/raw_runs.csv"


def solution_from_payload(payload: dict[str, object]) -> Solution:
    return Solution(
        routes=[Route(**row) for row in payload["routes"]],
        charging_actions=[charging_action_from_dict(row) for row in payload.get("charging_actions", [])],
        cross_site_services=[CrossSiteService(**row) for row in payload.get("cross_site_services", [])],
    )


def overlap_seconds(solution: Solution, instance, prices) -> list[dict[str, object]]:
    intervals: dict[str, list[tuple[float, float]]] = {}
    for route in solution.routes:
        if route.vehicle_type.lower() != "ev":
            continue
        timing = route_timing(route, instance, prices, charging_actions=solution.charging_actions)
        intervals.setdefault(physical_vehicle_id(route.vehicle_id), []).append(
            (float(timing.earliest_departure_second), float(timing.return_second))
        )
    route_by_id = {route.vehicle_id: route for route in solution.routes}
    rows = []
    for action in solution.charging_actions:
        route = route_by_id.get(action.vehicle_id)
        if route is None or route.vehicle_type.lower() != "ev":
            continue
        start = int(action.charge_day_offset) * 86400.0 + float(action.charge_start_second)
        end = start + float(action.occupancy_minutes) * 60.0
        overlaps = [
            max(0.0, min(end, returned) - max(start, departure))
            for departure, returned in intervals.get(physical_vehicle_id(route.vehicle_id), ())
        ]
        amount = max(overlaps, default=0.0)
        if amount > 0.0:
            rows.append({"vehicle_id": action.vehicle_id, "station_id": action.station_id, "overlap_seconds": amount})
    return rows


def main() -> int:
    bundle = load_china81_bundle(REPO, INSTANCE, date="2025-02-12", fleet_authority=AUTHORITY)
    t10_data = json.loads((T10 / "solution_witnesses.json").read_text(encoding="utf-8"))
    positive_data = json.loads((REPO / "docs/handoff/eval_chain_carbon_consistency_20260804/solution_witnesses.json").read_text(encoding="utf-8"))

    positive_rows = []
    for key in POSITIVE:
        solution = solution_from_payload(positive_data["runs"][key]["solution"])
        violations = check_solution(solution, bundle.instance, bundle.prices)
        positive_rows.append({
            "key": key,
            "overlap_seconds": overlap_seconds(solution, bundle.instance, bundle.prices),
            "charging_trip_overlap_count": sum(v.type == CHARGING_TRIP_OVERLAP for v in violations),
            "violation_types": [v.type for v in violations],
        })

    t10_rows = []
    for key, row in sorted(t10_data["runs"].items()):
        solution = solution_from_payload(row["solution"])
        violations = check_solution(solution, bundle.instance, bundle.prices)
        t10_rows.append({"key": key, "pass": not violations, "violation_types": [v.type for v in violations]})

    t9_rows = []
    cache: dict[Path, object] = {}
    with T9_RAW.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["instance_id"] != INSTANCE or row["prefilter_pass"] != "true" or row["solution_status"] != "CERTIFICATE_PASS" or row["overlap_action_count"] != "0":
                continue
            source = REPO / row["source_file"]
            if source not in cache:
                cache[source] = json.loads(source.read_text(encoding="utf-8"))
            current = cache[source]
            for token in row["solution_locator"].split("/"):
                current = current[int(token[1:-1])] if token.startswith("[") else current[token]
            solution = solution_from_payload(current)
            violations = check_solution(solution, bundle.instance, bundle.prices)
            t9_rows.append({"solution_locator": row["solution_locator"], "pass": not violations, "violation_types": [v.type for v in violations]})
            if len(t9_rows) == 20:
                break

    result = {
        "schema": "resetp.t12-intertrip-charging-fix-tolerance-regression.v1",
        "feasibility_tol": 1e-9,
        "positive": positive_rows,
        "t10_count": len(t10_rows),
        "t10_passed": sum(row["pass"] for row in t10_rows),
        "t10": t10_rows,
        "t9_count": len(t9_rows),
        "t9_passed": sum(row["pass"] for row in t9_rows),
        "t9": t9_rows,
    }
    (OUT / "witness_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
