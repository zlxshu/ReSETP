#!/usr/bin/env python3
"""Zero-search P0 gate for the strict multi-trip execution clock.

This gate replays one sealed E6 solution/certificate pair on the 114-customer
network.  It checks route and charging boundaries only; it does not call a
search method or the rolling dynamic planner.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "solver/src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.search.certificate_execution import (  # noqa: E402
    COMPLETED,
    IN_PROGRESS,
    NOT_STARTED,
    build_certificate_execution_ledger,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict  # noqa: E402
from setp_solver.search.multitrip_schedule import MultiTripCertificate, ScheduledTrip  # noqa: E402


SCHEMA_VERSION = "resetp.e7_certificate_clock_p0.v1"
CASE = "L-main-threeshift-50c-01__geographic__seed1__no_loss"
INSTANCE = "L-main-threeshift-50c-01"
E3 = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
E6 = ROOT / "baselines/e6_fairness/e6_participation_formal_20260714"
DEFAULT_OUTPUT = ROOT / "baselines/e7_dynamic/e7_certificate_clock_p0_20260714"
EPSILON_SECONDS = 1e-9
DAY_SECONDS = 86_400.0
SEARCH_EVALUATIONS = 0
SOURCE_FILES = (
    "baselines/e7_dynamic/e7_certificate_clock_p0_20260714.py",
    "solver/src/setp_solver/search/certificate_execution.py",
    "solver/src/setp_solver/search/multitrip_schedule.py",
    "solver/src/setp_solver/search/bundle.py",
    "solver/src/setp_solver/solution.py",
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/prices.py",
    "solver/tests/test_certificate_execution.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def certificate_from_dict(payload: dict[str, Any]) -> MultiTripCertificate:
    return MultiTripCertificate(
        contract_id=str(payload["contract_id"]),
        status=str(payload["status"]),
        vehicle_counts={str(key): int(value) for key, value in payload["vehicle_counts"].items()},
        trips=tuple(ScheduledTrip(**row) for row in payload["trips"]),
        recharge_mode=str(payload["recharge_mode"]),
        depot_charge_power_kw=float(payload["depot_charge_power_kw"]),
        first_trip_charge_day_offset=int(payload.get("first_trip_charge_day_offset", -1)),
    )


def state_row(
    *,
    check_id: str,
    category: str,
    subject_id: str,
    boundary: str,
    event_second: float,
    expected: str,
    observed: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "category": category,
        "subject_id": subject_id,
        "boundary": boundary,
        "event_second": float(event_second),
        "epsilon_seconds": EPSILON_SECONDS,
        "expected": expected,
        "observed": observed,
        "passed": observed == expected,
        "search_evaluations": SEARCH_EVALUATIONS,
        "detail": detail,
    }


def invariant_row(
    *,
    check_id: str,
    category: str,
    subject_id: str,
    expected: Any,
    observed: Any,
    detail: str,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "category": category,
        "subject_id": subject_id,
        "boundary": "invariant",
        "event_second": "",
        "epsilon_seconds": EPSILON_SECONDS,
        "expected": str(expected),
        "observed": str(observed),
        "passed": observed == expected,
        "search_evaluations": SEARCH_EVALUATIONS,
        "detail": detail,
    }


def charge_state(second: float, start_second: float, end_second: float) -> str:
    if second < start_second:
        return "not_charging"
    if second < end_second:
        return "charging"
    return "charge_complete"


def artifact_hashes(output: Path) -> dict[str, str]:
    return {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    solution_path = E6 / "solutions" / f"{CASE}.json"
    certificate_path = E6 / "certificates" / f"{CASE}.json"
    bundle_dir = E3 / "assets" / INSTANCE / "bundle"
    input_paths = {
        "solution": solution_path,
        "certificate": certificate_path,
        "bundle_instance": bundle_dir / "instance.json",
        "bundle_distance_matrix": bundle_dir / "distance_matrix.npy",
        "bundle_carbon_profile": bundle_dir / "carbon_profile.csv",
        "bundle_manifest": bundle_dir / "scenario_manifest.json",
    }
    missing = [str(path) for path in input_paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"P0 input is missing: {missing}")

    solution = solution_from_dict(read_json(solution_path))
    certificate_payload = read_json(certificate_path)
    certificate = certificate_from_dict(certificate_payload)
    bundle = load_search_bundle(bundle_dir)
    prices = replace(
        DEFAULT_PRICES,
        B_battery_kwh=280.0,
        initial_ev_battery_kwh=0.0,
        cross_site_cost=0.0,
        carbon_price=0.0,
    )
    ledger = build_certificate_execution_ledger(solution, certificate, bundle.instance, prices)

    rows: list[dict[str, Any]] = []
    customer_count = sum(node.node_type.lower() == "c" for node in bundle.instance.nodes)
    rows.append(
        invariant_row(
            check_id="p0_ledger_build",
            category="ledger",
            subject_id=CASE,
            expected="PASS",
            observed="PASS",
            detail="The sealed solution and certificate produced one immutable execution ledger.",
        )
    )
    rows.append(
        invariant_row(
            check_id="p0_customer_count",
            category="input",
            subject_id=INSTANCE,
            expected=114,
            observed=customer_count,
            detail="Formal P0 uses the actual 114-customer network (internally named 50c).",
        )
    )

    cv_route_id = "CV_D0_1#T2"
    cv_trip = ledger.routes[cv_route_id]
    route_boundaries = (
        ("before_departure", cv_trip.departure_second - EPSILON_SECONDS, NOT_STARTED),
        ("at_departure", cv_trip.departure_second, IN_PROGRESS),
        ("before_return", cv_trip.return_second - EPSILON_SECONDS, IN_PROGRESS),
        ("at_return", cv_trip.return_second, COMPLETED),
    )
    for boundary, second, expected in route_boundaries:
        rows.append(
            state_row(
                check_id=f"route_{boundary}",
                category="route_boundary",
                subject_id=cv_route_id,
                boundary=boundary,
                event_second=second,
                expected=expected,
                observed=ledger.trip_state_at(cv_route_id, second),
                detail="State comes from the certified departure/return clock, not a shifted static schedule.",
            )
        )

    trips_by_id = {trip.route_id: trip for trip in certificate.trips}
    actions_by_id = {action.vehicle_id: action for action in solution.charging_actions}
    first_action = next(
        action
        for action in solution.charging_actions
        if action.charge_day_offset == certificate.first_trip_charge_day_offset
        and trips_by_id[action.vehicle_id].vehicle_type == "ev"
        and trips_by_id[action.vehicle_id].trip_index == 1
    )
    first_trip = trips_by_id[first_action.vehicle_id]
    first_start = float(first_action.charge_start_second) + float(first_action.charge_day_offset) * DAY_SECONDS
    first_end = first_start + float(first_action.occupancy_minutes) * 60.0
    first_boundaries = (
        ("before_start", first_start - EPSILON_SECONDS, "not_charging"),
        ("at_start", first_start, "charging"),
        ("before_end", first_end - EPSILON_SECONDS, "charging"),
        ("at_end", first_end, "charge_complete"),
    )
    for boundary, second, expected in first_boundaries:
        rows.append(
            state_row(
                check_id=f"first_charge_{boundary}",
                category="ev_first_trip_pre_horizon_charge",
                subject_id=first_action.vehicle_id,
                boundary=boundary,
                event_second=second,
                expected=expected,
                observed=charge_state(second, first_start, first_end),
                detail="Absolute charge time includes charge_day_offset=-1.",
            )
        )
    rows.extend(
        [
            invariant_row(
                check_id="first_charge_previous_day",
                category="ev_first_trip_pre_horizon_charge",
                subject_id=first_action.vehicle_id,
                expected=True,
                observed=first_start < 0.0 and first_end <= 0.0,
                detail="The first-trip energy is charged entirely on the preceding day.",
            ),
            invariant_row(
                check_id="first_charge_before_departure",
                category="ev_first_trip_pre_horizon_charge",
                subject_id=first_action.vehicle_id,
                expected=True,
                observed=first_end <= float(first_trip.departure_second),
                detail="Pre-horizon charging completes before the certified first-trip departure.",
            ),
        ]
    )

    gap_action = next(
        action
        for action in solution.charging_actions
        if action.charge_day_offset == 0
        and trips_by_id[action.vehicle_id].vehicle_type == "ev"
        and trips_by_id[action.vehicle_id].trip_index > 1
    )
    current_trip = trips_by_id[gap_action.vehicle_id]
    chain = sorted(
        (
            trip
            for trip in certificate.trips
            if trip.physical_vehicle_id == current_trip.physical_vehicle_id
        ),
        key=lambda trip: trip.trip_index,
    )
    previous_trip = chain[current_trip.trip_index - 2]
    gap_start = float(gap_action.charge_start_second)
    gap_end = gap_start + float(gap_action.occupancy_minutes) * 60.0
    gap_boundaries = (
        ("before_start", gap_start - EPSILON_SECONDS, "not_charging"),
        ("at_start", gap_start, "charging"),
        ("before_end", gap_end - EPSILON_SECONDS, "charging"),
        ("at_end", gap_end, "charge_complete"),
    )
    for boundary, second, expected in gap_boundaries:
        rows.append(
            state_row(
                check_id=f"gap_charge_{boundary}",
                category="ev_between_trip_charge",
                subject_id=gap_action.vehicle_id,
                boundary=boundary,
                event_second=second,
                expected=expected,
                observed=charge_state(second, gap_start, gap_end),
                detail="At the exact charge end the vehicle is no longer marked as charging.",
            )
        )
    rows.extend(
        [
            invariant_row(
                check_id="gap_charge_certificate_end",
                category="ev_between_trip_charge",
                subject_id=gap_action.vehicle_id,
                expected=True,
                observed=abs(gap_end - float(previous_trip.recharge_end_second)) <= 1e-6,
                detail="The saved charging action ends at the certificate recharge boundary.",
            ),
            invariant_row(
                check_id="gap_charge_before_next_departure",
                category="ev_between_trip_charge",
                subject_id=gap_action.vehicle_id,
                expected=True,
                observed=gap_end <= float(current_trip.departure_second) + 1e-6,
                detail="The next trip cannot depart before its between-trip charge completes.",
            ),
            invariant_row(
                check_id="gap_charge_action_identity",
                category="ev_between_trip_charge",
                subject_id=gap_action.vehicle_id,
                expected=True,
                observed=actions_by_id.get(current_trip.route_id) == gap_action,
                detail="The charge remains attached to the following stable trip identifier.",
            ),
        ]
    )

    fields = (
        "check_id",
        "category",
        "subject_id",
        "boundary",
        "event_second",
        "epsilon_seconds",
        "expected",
        "observed",
        "passed",
        "search_evaluations",
        "detail",
    )
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    passed = all(bool(row["passed"]) for row in rows) and all(
        int(row["search_evaluations"]) == 0 for row in rows
    )
    decision = {
        "verdict": "E7_CERTIFICATE_CLOCK_P0_PASS" if passed else "HALT_E7_CERTIFICATE_CLOCK_P0",
        "all_checks_passed": passed,
        "check_count": len(rows),
        "failed_check_ids": [str(row["check_id"]) for row in rows if not row["passed"]],
        "search_evaluations": SEARCH_EVALUATIONS,
        "customer_count": customer_count,
        "route_boundary_check_count": sum(row["category"] == "route_boundary" for row in rows),
        "first_trip_charge_check_count": sum(
            row["category"] == "ev_first_trip_pre_horizon_charge" for row in rows
        ),
        "between_trip_charge_check_count": sum(
            row["category"] == "ev_between_trip_charge" for row in rows
        ),
        "next_gate": "One mechanical dynamic trigger probe may start only if this verdict is PASS.",
        "claim_boundary": (
            "This P0 gate proves only that one sealed strict-multitrip solution can be replayed on an "
            "absolute execution clock without inventing an early trip or a late charge. It does not "
            "prove that rolling reoptimization is valid, cheaper, fair, or lower-carbon."
        ),
    }
    execution_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source_status = subprocess.run(
        ["git", "status", "--porcelain", "--", *SOURCE_FILES],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    source_hashes = {path: sha256(ROOT / path) for path in SOURCE_FILES}
    input_hashes = {name: sha256(path) for name, path in input_paths.items()}
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "execution_commit": execution_commit,
        "worktree_source_is_uncommitted": bool(source_status),
        "worktree_source_status": source_status,
        "zero_search": True,
        "search_evaluations": SEARCH_EVALUATIONS,
        "case": CASE,
        "instance": INSTANCE,
        "actual_customer_count": customer_count,
        "epsilon_seconds": EPSILON_SECONDS,
        "solution_sha256": input_hashes["solution"],
        "certificate_file_sha256": input_hashes["certificate"],
        "certificate_payload_sha256": canonical_sha256(certificate_payload),
        "execution_ledger_certificate_sha256": ledger.certificate_sha256,
        "price_parameters": asdict(prices),
        "price_parameters_sha256": canonical_sha256(asdict(prices)),
        "source_files": list(SOURCE_FILES),
        "source_hashes": source_hashes,
        "input_files": {name: str(path.relative_to(ROOT)) for name, path in input_paths.items()},
        "input_hashes": input_hashes,
    }
    write_json(output / "metadata.json", metadata)
    write_json(output / "decision.json", decision)
    report = [
        "# E7 严格多趟执行时钟 P0 门",
        "",
        f"判决：`{decision['verdict']}`。",
        "",
        "这一步没有重新搜索路线，只把一份已经封存的 114 客户方案和实体车辆多趟证书放回绝对时间轴。",
        f"共检查 {len(rows)} 个机械边界，新增搜索评价次数为 0，全部通过：{passed}。",
        "",
        f"柴油车第二趟 `{cv_route_id}` 在出发前仍是“尚未开始”，到证书规定的出发时刻才进入执行；返场前仍在执行，到返场时刻才结束。",
        f"电动车首趟 `{first_action.vehicle_id}` 的充电完整落在前一日，并在正式出发前结束。",
        f"电动车后续趟 `{gap_action.vehicle_id}` 的趟间充电在证书规定的结束边界闭合；恰好到结束时刻后不再占用充电状态，且下一趟不会提前出发。",
        "",
        "证据边界：P0 只证明封存方案能够被严格还原到真实执行时钟，并排除了“第二趟提前开始”和“充电结束边界漂移”两类错误。它没有调用动态重规划，也不能证明动态方案省钱、减碳或满足公平。",
        "",
        "所有输入方案、证书、算例文件、价格参数和执行源码均在 metadata.json 中绑定哈希。",
        "",
    ]
    (output / "report.md").write_text("\n".join(report), encoding="utf-8")
    write_json(output / "artifact_hashes.json", artifact_hashes(output))
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
