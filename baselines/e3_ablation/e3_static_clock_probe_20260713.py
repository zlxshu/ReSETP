#!/usr/bin/env python3
"""Replay one sealed E3 solution after the static first-trip clock repair.

This is a mechanical compatibility probe, not a new paper result.  It performs
no search and writes a small, auditable five-file evidence bundle.
"""

from __future__ import annotations

from dataclasses import asdict, replace
import csv
import hashlib
import json
import os
from pathlib import Path
from collections import Counter
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.e3_multitrip_runtime import hard_violations
from setp_solver.search.evaluation import EvaluationContext
from setp_solver.search.multitrip_schedule import (
    STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET,
    STATIC_PREHORIZON_SECONDS,
    prepare_multitrip_solution,
    reschedule_between_trip_charging,
)
from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution, physical_vehicle_id


V11 = ROOT / "baselines/e3_ablation/e3_v11_clean_20260713"
INPUT = V11 / "solutions/E3__200c__M1__seed1__fee0__eval4000__search.json"
BUNDLE = V11 / "assets/200c/derived_bundles/actual_gamma"
OUT = ROOT / "baselines/e3_ablation/e3_static_clock_probe_20260713"
SOURCE_FILES = [
    ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
    ROOT / "solver/src/setp_solver/search/e3_multitrip_runtime.py",
    Path(__file__).resolve(),
]
TOL = 1e-6


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_solution(path: Path) -> Solution:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Solution(
        routes=[Route(**row) for row in payload.get("routes", [])],
        charging_actions=[ChargingAction(**row) for row in payload.get("charging_actions", [])],
        cross_site_services=[CrossSiteService(**row) for row in payload.get("cross_site_services", [])],
    )


def route_fingerprint(solution: Solution) -> str:
    payload = [asdict(route) for route in solution.routes]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def absolute_clock_checks(solution: Solution, certificate: Any) -> dict[str, int]:
    trips_by_id = {trip.route_id: trip for trip in certificate.trips}
    trips_by_vehicle: dict[str, list[Any]] = {}
    for trip in certificate.trips:
        trips_by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)

    first_trip_late = 0
    first_trip_wrong_day = 0
    charge_trip_overlap = 0
    charge_charge_overlap = 0
    charge_intervals: dict[str, list[tuple[float, float]]] = {}
    for action in solution.charging_actions:
        trip = trips_by_id.get(action.vehicle_id)
        if trip is None or action.station_id != trip.home_depot_id:
            continue
        day_offset = int(action.charge_day_offset)
        if trip.trip_index == 1 and day_offset != certificate.first_trip_charge_day_offset:
            first_trip_wrong_day += 1
        start = float(action.charge_start_second) + day_offset * STATIC_PREHORIZON_SECONDS
        end = start + float(action.occupancy_minutes) * 60.0
        charge_intervals.setdefault(trip.physical_vehicle_id, []).append((start, end))
        if trip.trip_index == 1 and end > float(trip.departure_second) + TOL:
            first_trip_late += 1

    for vehicle_id, trips in trips_by_vehicle.items():
        route_intervals = [(float(trip.departure_second), float(trip.return_second)) for trip in trips]
        charges = sorted(charge_intervals.get(vehicle_id, []))
        charge_charge_overlap += sum(left[1] > right[0] + TOL for left, right in zip(charges, charges[1:]))
        for charge_start, charge_end in charges:
            charge_trip_overlap += sum(
                max(charge_start, trip_start) < min(charge_end, trip_end) - TOL
                for trip_start, trip_end in route_intervals
            )
    return {
        "first_trip_charge_after_departure": first_trip_late,
        "first_trip_charge_wrong_day_offset": first_trip_wrong_day,
        "same_vehicle_charge_trip_overlaps": charge_trip_overlap,
        "same_vehicle_charge_charge_overlaps": charge_charge_overlap,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    source_solution = read_solution(INPUT)
    bundle = load_search_bundle(BUNDLE)
    prices = replace(
        DEFAULT_PRICES,
        B_battery_kwh=280.0,
        initial_ev_battery_kwh=0.0,
        carbon_price=0.0,
        cross_site_cost=0.0,
    )
    prepared, certificate = prepare_multitrip_solution(source_solution, bundle.instance, prices)
    variants = {
        strategy: reschedule_between_trip_charging(
            prepared,
            certificate,
            bundle.instance,
            bundle.carbon_profile,
            strategy=strategy,
        )
        for strategy in ("naive", "aware")
    }

    os.environ["SETP_E3_STRICT_MULTITRIP"] = "1"
    rows: list[dict[str, Any]] = []
    route_hashes = {name: route_fingerprint(solution) for name, solution in variants.items()}
    energy = {name: sum(float(action.energy_kwh) for action in solution.charging_actions) for name, solution in variants.items()}
    all_pass = certificate.first_trip_charge_day_offset == STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET
    for strategy, solution in variants.items():
        context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
        violations = hard_violations(solution, context)
        violation_types = Counter(str(item.type) for item in violations)
        clock = absolute_clock_checks(solution, certificate)
        metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
        checks_pass = not violations and all(value == 0 for value in clock.values())
        all_pass = all_pass and checks_pass
        rows.append(
            {
                "strategy": strategy,
                "route_fingerprint": route_hashes[strategy],
                "total_charging_kwh": energy[strategy],
                "first_trip_charge_day_offset": certificate.first_trip_charge_day_offset,
                "hard_violation_count": len(violations),
                "hard_violation_types": json.dumps(dict(sorted(violation_types.items())), sort_keys=True),
                "hard_violation_sample": " | ".join(
                    f"{item.type}:{item.vehicle_id}:{item.detail}" for item in violations[:3]
                ),
                **clock,
                "total_cost": metrics["total_cost"],
                "ev_charging_emissions_kg": metrics["E_ev_indirect"],
            }
        )
    same_route = len(set(route_hashes.values())) == 1
    same_energy = max(energy.values()) - min(energy.values()) <= TOL
    all_pass = all_pass and same_route and same_energy

    raw_path = OUT / "raw_runs.csv"
    with raw_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    metadata = {
        "schema": "setp.e3.static_clock_probe.v1",
        "purpose": "mechanical replay only; not paper evidence",
        "input_solution": str(INPUT.relative_to(ROOT)),
        "input_solution_sha256": sha256(INPUT),
        "bundle": str(BUNDLE.relative_to(ROOT)),
        "source_commit": commit,
        "source_hashes": {str(path.relative_to(ROOT)): sha256(path) for path in SOURCE_FILES},
        "search_evaluations": 0,
        "first_trip_charge_day_offset": certificate.first_trip_charge_day_offset,
        "static_carbon_time_contract": "representative 48-slot daily profile repeated for day -1 and day 0",
    }
    write_json(OUT / "metadata.json", metadata)
    decision = {
        "status": "PASS" if all_pass else "HALT",
        "same_routes_between_timing_rules": same_route,
        "same_total_energy_between_timing_rules": same_energy,
        "all_mechanical_checks_pass": all_pass,
        "paper_use": "forbidden; compatibility probe only",
    }
    write_json(OUT / "decision.json", decision)
    violation_total = sum(int(row["hard_violation_count"]) for row in rows)
    closing = (
        "这只证明新时间表达能兼容一份真实规模方案，不能把本次排放差写进论文。后续碳实验仍需按预先登记的正式比较另跑。\n"
        if all_pass
        else "时间表达或既有方案仍未闭合，碳实验继续冻结；先修复并重做同一份零搜索回放，不得启动正式批次。\n"
    )
    check_sentence = (
        "完整严格检查报告 0 条问题，因此这份大方案的机械兼容性通过。\n\n"
        if all_pass
        else f"完整严格检查仍累计报告 {violation_total} 条问题，因此不能判定兼容通过；具体类型和样例保存在 raw_runs.csv。\n\n"
    )
    report = (
        "# 静态首趟充电时间最小回放\n\n"
        f"判决：{'通过' if all_pass else '停止'}。本次没有重新搜索，只回放了一份已封存的 200 客户合作方案。\n\n"
        "两种充电时机使用完全相同的路线和总电量。首趟充电在排班证书中明确属于第 -1 日；"
        "按绝对时间检查，首趟充电没有晚于出发，同一辆车的充电没有与行程或另一段充电重叠。"
        + check_sentence
        + closing
    )
    (OUT / "report.md").write_text(report, encoding="utf-8")

    artifact_hashes = {
        str(path.relative_to(ROOT)): sha256(path)
        for path in [
            Path(__file__).resolve(),
            INPUT,
            OUT / "metadata.json",
            raw_path,
            OUT / "decision.json",
            OUT / "report.md",
            *SOURCE_FILES[:2],
        ]
    }
    write_json(OUT / "artifact_hashes.json", artifact_hashes)
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
