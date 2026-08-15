#!/usr/bin/env python3
"""Replay the frozen 100 duty-crossover charging rejections after station restore."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "solver/scripts/run_problem_hgs_private_technical.py"
SNAPSHOTS = REPO / (
    "solver/reports/charging_rejection_diagnosis_20260812/"
    "duty_crossover_rejected_candidates.jsonl"
)
CLASSIFICATION = REPO / (
    "solver/reports/charging_rejection_diagnosis_20260812/relaxation_probe.csv"
)
OUTPUT = REPO / "solver/reports/station_restore_20260812"
INSTANCE_ID = "cn-cy-50c-01-V3-TWO-SHIFT-PRDFIX"
PROTECTED = (
    Path("solver/src/setp_solver/cost.py"),
    Path("solver/src/setp_solver/check.py"),
    Path("solver/src/setp_solver/search/evaluation.py"),
)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load_module("station_restore_replay_runner_20260812", RUNNER)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
) -> None:
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def individual_from_payload(payload: Mapping[str, Any]) -> Any:
    model = runner.importlib.import_module(
        "setp_solver.algorithms.problem_hgs.model"
    )
    duties = []
    for duty_row in payload["duties"]:
        if duty_row.get("schedule") is not None:
            raise ValueError("frozen replay unexpectedly contains ScheduledDuty")
        duties.append(
            model.PhysicalVehicleDuty(
                physical_vehicle_id=str(duty_row["physical_vehicle_id"]),
                vehicle_type=str(duty_row["vehicle_type"]),
                home_depot_id=str(duty_row["home_depot_id"]),
                trips=tuple(
                    model.DutyTrip(
                        trip_index=int(row["trip_index"]),
                        customer_ids=tuple(row["customer_ids"]),
                        locked_customer_prefix=tuple(
                            row.get("locked_customer_prefix", ())
                        ),
                        route_visits=tuple(row.get("route_visits", ())),
                    )
                    for row in duty_row["trips"]
                ),
                charging_sessions=tuple(
                    model.DutyChargingSession(**row)
                    for row in duty_row.get("charging_sessions", ())
                ),
                has_dynamic_commitment=bool(
                    duty_row.get("has_dynamic_commitment", False)
                ),
            )
        )
    return model.DutyIndividual(
        duties=tuple(duties),
        unserved_customers=tuple(payload.get("unserved_customers", ())),
        version=int(payload.get("version", 1)),
        source=str(payload.get("source", "frozen-station-replay")),
    )


def public_charging_details(
    case_id: str,
    individual: Any,
    public_station_ids: set[str],
) -> list[dict[str, Any]]:
    rows = []
    for duty in individual.duties:
        trips = {int(trip.trip_index): trip for trip in duty.trips}
        for session in duty.charging_sessions:
            if session.station_id not in public_station_ids:
                continue
            trip = trips[int(session.trip_index)]
            visits = list(trip.effective_route_visits)
            positions = [
                index + 1
                for index, node_id in enumerate(visits)
                if node_id == session.station_id
            ]
            if len(positions) != 1:
                raise RuntimeError(
                    f"{case_id}: public station {session.station_id} occurs "
                    f"{len(positions)} times in trip {session.trip_index}"
                )
            position = positions[0]
            full_route = [duty.home_depot_id, *visits, duty.home_depot_id]
            rows.append(
                {
                    "case_id": case_id,
                    "physical_vehicle_id": duty.physical_vehicle_id,
                    "trip_index": int(session.trip_index),
                    "station_id": session.station_id,
                    "energy_kwh": f"{float(session.energy_kwh):.12f}",
                    "route_interior_position_1based": position,
                    "previous_node": full_route[position - 1],
                    "next_node": full_route[position + 1],
                    "route_sequence": "|".join(full_route),
                    "charge_start_second": f"{float(session.charge_start_second):.9f}",
                    "charge_day_offset": int(session.charge_day_offset),
                }
            )
    return rows


def main() -> int:
    rows_by_case = {row["case_id"]: row for row in read_csv(CLASSIFICATION)}
    if len(rows_by_case) != 100:
        raise RuntimeError("classification table is not a unique 100-case table")
    protected_before = {str(path): sha256(REPO / path) for path in PROTECTED}
    bundle, _, _, context = runner._build_prdfix_suite_context(
        REPO,
        INSTANCE_ID,
        fleet_parameters=runner.ENDOGENOUS_FLEET_PARAMETERS,
    )
    context = replace(context, depot_charge_window_mode="full_gap")
    evaluator = runner.DutyFullEvaluator(context)
    policy = runner._policy(
        evaluator,
        first_trip_prev_night_enabled=True,
        charge_timing_policy="cost_plus_carbon",
        frvcpy_enabled=False,
    )
    public_station_ids = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "f"
    }
    if not public_station_ids:
        raise RuntimeError("restored instance has no public station nodes")

    replay_rows = []
    detail_rows = []
    seen = set()
    with SNAPSHOTS.open(encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            case_id = str(payload["case_id"])
            if case_id in seen:
                raise RuntimeError(f"duplicate replay case: {case_id}")
            seen.add(case_id)
            classification = rows_by_case[case_id]
            reference = individual_from_payload(payload["reference"])
            candidate = individual_from_payload(payload["raw_candidate"])
            if reference.fingerprint != payload["reference_fingerprint"]:
                raise RuntimeError(f"{case_id}: reference fingerprint mismatch")
            if candidate.fingerprint != payload["raw_candidate_fingerprint"]:
                raise RuntimeError(f"{case_id}: candidate fingerprint mismatch")

            repaired = None
            error_type = None
            error_text = None
            reason_code = None
            full_feasible = False
            try:
                repaired = runner.repair_changed_duties(
                    reference,
                    candidate,
                    changed_duty_ids=set(payload["changed_duty_ids"]),
                    context=context,
                    policy=policy,
                    cache=None,
                )
                full = evaluator.evaluate(repaired)
                full_feasible = bool(full.feasible)
                if not full.feasible:
                    reason_code = "FULL_EVALUATION_INFEASIBLE"
                    error_type = "FullEvaluation"
                    error_text = "; ".join(str(item) for item in full.violations)
            except (TypeError, ValueError) as error:
                reason_code = runner.charging_rejection_reason(error)
                error_type = type(error).__name__
                error_text = str(error)

            feasible = repaired is not None and full_feasible
            details = (
                public_charging_details(case_id, repaired, public_station_ids)
                if feasible
                else []
            )
            detail_rows.extend(details)
            replay_rows.append(
                {
                    "case_id": case_id,
                    "capture_order": int(payload["capture_order"]),
                    "iteration": payload["iteration"],
                    "original_reason_code": classification["original_reason_code"],
                    "frvcpy_reason_code": classification["frvcpy_reason_code"],
                    "changed_duty_ids": ";".join(payload["changed_duty_ids"]),
                    "reference_fingerprint_verified": True,
                    "raw_candidate_fingerprint_verified": True,
                    "restored_station_ids": ";".join(sorted(public_station_ids)),
                    "replay_feasible_after_station_restore": feasible,
                    "replay_reason_code": reason_code or "",
                    "replay_error_type": error_type or "",
                    "replay_error": error_text or "",
                    "repaired_fingerprint": (
                        repaired.fingerprint if repaired is not None else ""
                    ),
                    "public_station_charging_session_count": len(details),
                    "public_station_energy_kwh": f"{sum(float(row['energy_kwh']) for row in details):.12f}",
                }
            )

    if len(seen) != 100:
        raise RuntimeError(f"expected 100 replay cases, observed {len(seen)}")
    replay_rows.sort(key=lambda row: int(row["capture_order"]))
    write_csv(
        OUTPUT / "replay_rows.csv",
        replay_rows,
        tuple(replay_rows[0]),
    )
    write_csv(
        OUTPUT / "replay_charging_details.csv",
        detail_rows,
        (
            "case_id",
            "physical_vehicle_id",
            "trip_index",
            "station_id",
            "energy_kwh",
            "route_interior_position_1based",
            "previous_node",
            "next_node",
            "route_sequence",
            "charge_start_second",
            "charge_day_offset",
        ),
    )
    groups = {}
    for reason in ("NO_FEASIBLE_WINDOW", "SCHEDULE_CONFLICT"):
        group = [row for row in replay_rows if row["original_reason_code"] == reason]
        feasible = [
            row
            for row in group
            if bool(row["replay_feasible_after_station_restore"])
        ]
        groups[reason] = {
            "case_count": len(group),
            "became_feasible_count": len(feasible),
            "became_feasible_fraction": (
                0.0 if not group else len(feasible) / len(group)
            ),
        }
    protected_after = {str(path): sha256(REPO / path) for path in PROTECTED}
    summary = {
        "completion": "REPLAY_COMPLETE",
        "instance_id": INSTANCE_ID,
        "case_count": len(replay_rows),
        "public_station_ids": sorted(public_station_ids),
        "policy": {
            "depot_charge_window_mode": policy.depot_charge_window_mode,
            "first_trip_prev_night_enabled": policy.first_trip_prev_night_enabled,
            "charge_timing_policy": policy.charge_timing_policy,
            "public_station_candidate_mode": policy.public_station_candidate_mode,
            "charge_amount_strategy": policy.charge_amount_strategy,
        },
        "groups": groups,
        "became_feasible_total": sum(
            bool(row["replay_feasible_after_station_restore"])
            for row in replay_rows
        ),
        "public_station_charging_detail_rows": len(detail_rows),
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
    }
    (OUTPUT / "replay_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if protected_before != protected_after:
        raise RuntimeError("protected evaluator hash changed during replay")
    if groups["SCHEDULE_CONFLICT"]["became_feasible_count"]:
        raise RuntimeError("schedule-conflict controls changed feasibility")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
