#!/usr/bin/env python3
"""Zero-search E4 wiring probe on one predeclared strict E3 pair.

The four cells are customer ownership fixed/reassignment allowed crossed with
immediate/low-carbon charging.  Routes, physical vehicles, and charging energy
are frozen within each operating arm.  Result direction never gates PASS.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation import e3_v3_runner as legacy
from setp_solver.cost import carbon_profile_row_for_slot, charging_slot_breakdown, evaluate
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.e3_multitrip_runtime import hard_violations
from setp_solver.search.evaluation import EvaluationContext, cross_depot_violations
from setp_solver.search.formal_runner import _solution_from_dict
from setp_solver.search.multitrip_schedule import (
    STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET,
    STATIC_PREHORIZON_SECONDS,
    MultiTripCertificate,
    ScheduledTrip,
    reschedule_between_trip_charging,
    validate_multitrip_certificate,
)
from setp_solver.solution import Solution


FORMAL = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
OWNERSHIP = ROOT / "baselines/e3_ablation/e3_ownership_class_design_v4_20260713"
OUT = ROOT / "baselines/e4_e5/e4_four_cell_probe_20260713"
INSTANCE = "L-main-threeshift-50c-01"
CONDITION = "mixed"
SEED = 1
ARMS = ("ownership_fixed", "reassignment_allowed")
STRATEGIES = (("immediate", "naive"), ("low_carbon", "aware"))
TOLERANCE = 1e-6
REPLAY_METRICS = (
    "total_cost",
    "cost_fix",
    "cost_km",
    "cost_fuel",
    "cost_elec",
    "cost_occ",
    "cost_transship",
    "cost_carbon",
    "E_total",
    "E_cv_direct",
    "E_ev_indirect",
    "electricity_kwh",
    "distance_total",
)
SOURCE_FILES = (
    ROOT / "solver/src/setp_solver/cost.py",
    ROOT / "solver/src/setp_solver/check.py",
    ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
    ROOT / "solver/src/setp_solver/search/e3_multitrip_runtime.py",
    ROOT / "solver/src/setp_solver/search/formal_runner.py",
    Path(__file__).resolve(),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def canonical_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def route_hash(solution: Solution) -> str:
    return canonical_hash([asdict(route) for route in solution.routes])


def service_hash(solution: Solution) -> str:
    return canonical_hash([asdict(service) for service in solution.cross_site_services])


def energy_ledger_hash(solution: Solution) -> str:
    return canonical_hash(
        sorted(
            (
                action.vehicle_id,
                action.station_id,
                round(float(action.energy_kwh), 12),
                round(float(action.occupancy_minutes), 12),
                int(action.charge_day_offset),
            )
            for action in solution.charging_actions
        )
    )


def timing_hash(solution: Solution) -> str:
    return canonical_hash(
        sorted(
            (
                action.vehicle_id,
                action.station_id,
                round(float(action.charge_start_second), 9),
                int(action.charge_day_offset),
            )
            for action in solution.charging_actions
        )
    )


def load_certificate(path: Path) -> MultiTripCertificate:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return MultiTripCertificate(
        contract_id=str(payload["contract_id"]),
        status=str(payload["status"]),
        vehicle_counts={str(key): int(value) for key, value in payload["vehicle_counts"].items()},
        trips=tuple(ScheduledTrip(**trip) for trip in payload["trips"]),
        recharge_mode=str(payload["recharge_mode"]),
        depot_charge_power_kw=float(payload["depot_charge_power_kw"]),
        first_trip_charge_day_offset=int(payload["first_trip_charge_day_offset"]),
    )


def read_formal_rows() -> dict[str, dict[str, str]]:
    with (FORMAL / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {
        row["arm"]: row
        for row in rows
        if row["instance"] == INSTANCE and row["condition"] == CONDITION and int(row["seed"]) == SEED
    }


def read_owners() -> dict[str, str]:
    path = OWNERSHIP / "ownership_maps" / f"{INSTANCE}__{CONDITION}.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["customer_id"]: row["owner_depot_id"] for row in csv.DictReader(handle)}


def replay_difference(row: dict[str, str], metrics: dict[str, float]) -> float:
    return max(abs(float(row[key]) - float(metrics[key])) for key in REPLAY_METRICS)


def charge_scope(action: Any, certificate: MultiTripCertificate) -> str:
    trip = next(trip for trip in certificate.trips if trip.route_id == action.vehicle_id)
    return "pre_day_first_trip" if trip.trip_index == 1 else "same_day_between_trip"


def action_window(action: Any, certificate: MultiTripCertificate) -> tuple[float, float]:
    trip_by_id = {trip.route_id: trip for trip in certificate.trips}
    trip = trip_by_id[action.vehicle_id]
    duration = float(action.occupancy_minutes) * 60.0
    if trip.trip_index == 1:
        return 0.0, STATIC_PREHORIZON_SECONDS - duration
    chain = sorted(
        (item for item in certificate.trips if item.physical_vehicle_id == trip.physical_vehicle_id),
        key=lambda item: item.trip_index,
    )
    previous = chain[trip.trip_index - 2]
    return float(previous.return_second), float(trip.departure_second) - duration


def action_emissions_kg(action: Any, bundle: Any) -> float:
    total = 0.0
    for slot in charging_slot_breakdown(
        float(action.charge_start_second),
        float(action.occupancy_minutes) * 60.0,
        float(action.energy_kwh),
        bundle.instance,
        n_slots=len(bundle.carbon_profile),
        cyclic=True,
    ):
        intensity = float(carbon_profile_row_for_slot(bundle.carbon_profile, slot.slot_index)["actual_gco2_per_kwh"])
        total += float(slot.y_skt_kwh) * intensity / 1000.0
    return total


def absolute_clock_checks(solution: Solution, certificate: MultiTripCertificate) -> dict[str, int]:
    trip_by_id = {trip.route_id: trip for trip in certificate.trips}
    trips_by_vehicle: dict[str, list[ScheduledTrip]] = defaultdict(list)
    for trip in certificate.trips:
        trips_by_vehicle[trip.physical_vehicle_id].append(trip)
    charge_intervals: dict[str, list[tuple[float, float]]] = defaultdict(list)
    first_trip_wrong_day = 0
    outside_legal_window = 0
    for action in solution.charging_actions:
        trip = trip_by_id[action.vehicle_id]
        if action.station_id != trip.home_depot_id:
            continue
        day_offset = int(action.charge_day_offset)
        if trip.trip_index == 1 and day_offset != STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET:
            first_trip_wrong_day += 1
        earliest, latest = action_window(action, certificate)
        start_in_day = float(action.charge_start_second)
        if start_in_day < earliest - TOLERANCE or start_in_day > latest + TOLERANCE:
            outside_legal_window += 1
        absolute_start = start_in_day + day_offset * STATIC_PREHORIZON_SECONDS
        absolute_end = absolute_start + float(action.occupancy_minutes) * 60.0
        charge_intervals[trip.physical_vehicle_id].append((absolute_start, absolute_end))

    charge_trip_overlap = 0
    charge_charge_overlap = 0
    for vehicle_id, trips in trips_by_vehicle.items():
        route_intervals = [(float(trip.departure_second), float(trip.return_second)) for trip in trips]
        charges = sorted(charge_intervals.get(vehicle_id, []))
        charge_charge_overlap += sum(left[1] > right[0] + TOLERANCE for left, right in zip(charges, charges[1:]))
        for charge_start, charge_end in charges:
            charge_trip_overlap += sum(
                max(charge_start, trip_start) < min(charge_end, trip_end) - TOLERANCE
                for trip_start, trip_end in route_intervals
            )
    return {
        "first_trip_wrong_day_offset": first_trip_wrong_day,
        "charge_outside_legal_window": outside_legal_window,
        "same_vehicle_charge_trip_overlaps": charge_trip_overlap,
        "same_vehicle_charge_charge_overlaps": charge_charge_overlap,
    }


def slot_and_action_rows(
    arm: str,
    strategy: str,
    solution: Solution,
    certificate: MultiTripCertificate,
    bundle: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    action_rows: list[dict[str, Any]] = []
    slot_totals: dict[tuple[str, int, int], float] = defaultdict(float)
    for index, action in enumerate(solution.charging_actions, start=1):
        scope = charge_scope(action, certificate)
        earliest, latest = action_window(action, certificate)
        action_rows.append(
            {
                "arm": arm,
                "timing_rule": strategy,
                "action_index": index,
                "vehicle_trip": action.vehicle_id,
                "station": action.station_id,
                "charge_scope": scope,
                "charge_day_offset": int(action.charge_day_offset),
                "charge_start_second": float(action.charge_start_second),
                "charge_end_second": float(action.charge_start_second) + float(action.occupancy_minutes) * 60.0,
                "energy_kwh": float(action.energy_kwh),
                "earliest_start_second": earliest,
                "latest_start_second": latest,
                "timing_slack_hours": max(0.0, latest - earliest) / 3600.0,
                "emissions_kg": action_emissions_kg(action, bundle),
            }
        )
        for slot in charging_slot_breakdown(
            float(action.charge_start_second),
            float(action.occupancy_minutes) * 60.0,
            float(action.energy_kwh),
            bundle.instance,
            n_slots=len(bundle.carbon_profile),
            cyclic=True,
        ):
            slot_totals[(scope, int(action.charge_day_offset), int(slot.slot_index))] += float(slot.y_skt_kwh)
    slot_rows = []
    for (scope, day_offset, slot_index), energy in sorted(slot_totals.items()):
        row = carbon_profile_row_for_slot(bundle.carbon_profile, slot_index)
        slot_rows.append(
            {
                "arm": arm,
                "timing_rule": strategy,
                "charge_scope": scope,
                "charge_day_offset": day_offset,
                "slot_index": slot_index,
                "slot_start_hour": slot_index / 2.0,
                "carbon_intensity_g_per_kwh": float(row["actual_gco2_per_kwh"]),
                "charging_kwh": energy,
            }
        )
    return action_rows, slot_rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    bundle_dir = FORMAL / "assets" / INSTANCE / "bundle"
    bundle = load_search_bundle(bundle_dir)
    prices = legacy.prices_for("M1", 0.0)
    owners = read_owners()
    formal_rows = read_formal_rows()
    if set(formal_rows) != set(ARMS):
        raise RuntimeError(f"predeclared formal pair is incomplete: {sorted(formal_rows)}")

    raw_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    slot_rows: list[dict[str, Any]] = []
    variants: dict[str, dict[str, Solution]] = {}
    certificates: dict[str, MultiTripCertificate] = {}
    input_paths: list[Path] = []

    for arm in ARMS:
        formal_row = formal_rows[arm]
        solution_path = ROOT / formal_row["solution_path"]
        certificate_path = ROOT / formal_row["certificate_path"]
        input_paths.extend((solution_path, certificate_path))
        source = _solution_from_dict(json.loads(solution_path.read_text(encoding="utf-8")))
        certificate = load_certificate(certificate_path)
        certificates[arm] = certificate
        validate_multitrip_certificate(certificate, source.routes, prices)
        source_metrics = evaluate(source, bundle.instance, bundle.carbon_profile, prices)
        source_replay_difference = replay_difference(formal_row, source_metrics)
        variants[arm] = {
            label: reschedule_between_trip_charging(
                source,
                certificate,
                bundle.instance,
                bundle.carbon_profile,
                strategy=internal,
            )
            for label, internal in STRATEGIES
        }
        for label, solution in variants[arm].items():
            context = EvaluationContext(
                bundle.instance,
                bundle.carbon_profile,
                prices=prices,
                carbon_weight=0.0,
                fairness_enabled=False,
                customer_home_depot=owners,
                allow_cross_depot=arm == "reassignment_allowed",
            )
            with legacy.strict_mode():
                violations = list(hard_violations(solution, context))
                if arm == "ownership_fixed":
                    violations.extend(cross_depot_violations(solution, context))
            clock = absolute_clock_checks(solution, certificate)
            metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
            per_scope_emissions = Counter()
            per_scope_energy = Counter()
            eligible_energy = Counter()
            for action in solution.charging_actions:
                scope = charge_scope(action, certificate)
                per_scope_emissions[scope] += action_emissions_kg(action, bundle)
                per_scope_energy[scope] += float(action.energy_kwh)
                earliest, latest = action_window(action, certificate)
                if latest > earliest + TOLERANCE:
                    eligible_energy[scope] += float(action.energy_kwh)
            cell_actions, cell_slots = slot_and_action_rows(arm, label, solution, certificate, bundle)
            action_rows.extend(cell_actions)
            slot_rows.extend(cell_slots)
            slot_energy = sum(float(row["charging_kwh"]) for row in cell_slots)
            raw_rows.append(
                {
                    "arm": arm,
                    "timing_rule": label,
                    "route_fingerprint": route_hash(solution),
                    "service_fingerprint": service_hash(solution),
                    "energy_ledger_fingerprint": energy_ledger_hash(solution),
                    "timing_fingerprint": timing_hash(solution),
                    "source_replay_max_difference": source_replay_difference,
                    "hard_violation_count": len(violations),
                    "hard_violation_types": json.dumps(dict(Counter(str(item.type) for item in violations)), sort_keys=True),
                    **clock,
                    "total_cost": metrics["total_cost"],
                    "total_operational_emissions_kg": metrics["E_total"],
                    "direct_fuel_emissions_kg": metrics["E_cv_direct"],
                    "charging_emissions_kg": metrics["E_ev_indirect"],
                    "total_charging_kwh": metrics["electricity_kwh"],
                    "pre_day_charging_kwh": per_scope_energy["pre_day_first_trip"],
                    "between_trip_charging_kwh": per_scope_energy["same_day_between_trip"],
                    "pre_day_charging_emissions_kg": per_scope_emissions["pre_day_first_trip"],
                    "between_trip_charging_emissions_kg": per_scope_emissions["same_day_between_trip"],
                    "eligible_pre_day_kwh": eligible_energy["pre_day_first_trip"],
                    "eligible_between_trip_kwh": eligible_energy["same_day_between_trip"],
                    "slot_energy_closure_error": abs(slot_energy - float(metrics["electricity_kwh"])),
                }
            )

    summaries: list[dict[str, Any]] = []
    mechanical_checks: dict[str, bool] = {}
    for arm in ARMS:
        immediate = next(row for row in raw_rows if row["arm"] == arm and row["timing_rule"] == "immediate")
        aware = next(row for row in raw_rows if row["arm"] == arm and row["timing_rule"] == "low_carbon")
        immediate_actions = {row["vehicle_trip"]: row for row in action_rows if row["arm"] == arm and row["timing_rule"] == "immediate"}
        aware_actions = {row["vehicle_trip"]: row for row in action_rows if row["arm"] == arm and row["timing_rule"] == "low_carbon"}
        moved = [
            key
            for key in immediate_actions
            if abs(float(immediate_actions[key]["charge_start_second"]) - float(aware_actions[key]["charge_start_second"])) > TOLERANCE
        ]
        moved_by_scope = Counter()
        for key in moved:
            moved_by_scope[immediate_actions[key]["charge_scope"]] += float(immediate_actions[key]["energy_kwh"])
        charging_saved = float(immediate["charging_emissions_kg"]) - float(aware["charging_emissions_kg"])
        total_saved = float(immediate["total_operational_emissions_kg"]) - float(aware["total_operational_emissions_kg"])
        summaries.append(
            {
                "arm": arm,
                "changed_charging_actions": len(moved),
                "moved_charging_kwh": sum(moved_by_scope.values()),
                "moved_pre_day_kwh": moved_by_scope["pre_day_first_trip"],
                "moved_between_trip_kwh": moved_by_scope["same_day_between_trip"],
                "charging_emissions_immediate_kg": immediate["charging_emissions_kg"],
                "charging_emissions_low_carbon_kg": aware["charging_emissions_kg"],
                "charging_emissions_reduction_kg": charging_saved,
                "charging_emissions_reduction_pct": 100.0 * charging_saved / float(immediate["charging_emissions_kg"]) if float(immediate["charging_emissions_kg"]) else 0.0,
                "total_operational_emissions_reduction_kg": total_saved,
                "total_operational_emissions_reduction_pct": 100.0 * total_saved / float(immediate["total_operational_emissions_kg"]) if float(immediate["total_operational_emissions_kg"]) else 0.0,
                "pre_day_emissions_reduction_kg": float(immediate["pre_day_charging_emissions_kg"]) - float(aware["pre_day_charging_emissions_kg"]),
                "between_trip_emissions_reduction_kg": float(immediate["between_trip_charging_emissions_kg"]) - float(aware["between_trip_charging_emissions_kg"]),
            }
        )
        mechanical_checks[f"{arm}_same_routes"] = immediate["route_fingerprint"] == aware["route_fingerprint"]
        mechanical_checks[f"{arm}_same_services"] = immediate["service_fingerprint"] == aware["service_fingerprint"]
        mechanical_checks[f"{arm}_same_energy_ledger"] = immediate["energy_ledger_fingerprint"] == aware["energy_ledger_fingerprint"]
        mechanical_checks[f"{arm}_same_cost"] = abs(float(immediate["total_cost"]) - float(aware["total_cost"])) <= TOLERANCE
        mechanical_checks[f"{arm}_nonincreasing_emissions"] = float(aware["charging_emissions_kg"]) <= float(immediate["charging_emissions_kg"]) + TOLERANCE
        source_solution = _solution_from_dict(json.loads((ROOT / formal_rows[arm]["solution_path"]).read_text(encoding="utf-8")))
        mechanical_checks[f"{arm}_immediate_matches_sealed_timing"] = timing_hash(variants[arm]["immediate"]) == timing_hash(source_solution)

    for row in raw_rows:
        cell = f"{row['arm']}_{row['timing_rule']}"
        mechanical_checks[f"{cell}_sealed_replay"] = float(row["source_replay_max_difference"]) <= TOLERANCE
        mechanical_checks[f"{cell}_strict_legal"] = int(row["hard_violation_count"]) == 0 and all(
            int(row[key]) == 0
            for key in (
                "first_trip_wrong_day_offset",
                "charge_outside_legal_window",
                "same_vehicle_charge_trip_overlaps",
                "same_vehicle_charge_charge_overlaps",
            )
        )
        mechanical_checks[f"{cell}_slot_energy_closed"] = float(row["slot_energy_closure_error"]) <= TOLERANCE

    all_pass = len(raw_rows) == 4 and all(mechanical_checks.values())
    summary_by_arm = {row["arm"]: row for row in summaries}
    decision = {
        "verdict": "PASS_E4_FOUR_CELL_WIRING" if all_pass else "HALT_E4_FOUR_CELL_WIRING",
        "all_mechanical_checks_pass": all_pass,
        "mechanical_checks": mechanical_checks,
        "result_direction_did_not_gate_execution": True,
        "formal_evidence_status": "diagnostic only; one network and one representative carbon day cannot support a paper-wide effect estimate",
        "observed_direction": {
            "ownership_fixed_charging_reduction_pct": summary_by_arm["ownership_fixed"]["charging_emissions_reduction_pct"],
            "reassignment_allowed_charging_reduction_pct": summary_by_arm["reassignment_allowed"]["charging_emissions_reduction_pct"],
            "difference_in_reduction_percentage_points": summary_by_arm["reassignment_allowed"]["charging_emissions_reduction_pct"] - summary_by_arm["ownership_fixed"]["charging_emissions_reduction_pct"],
        },
        "next_gate": "design the network-by-carbon-day replay only if this probe passes; do not infer direction from this one case",
    }
    metadata = {
        "schema": "setp.e4.four_cell_probe.v1",
        "execution_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "search_evaluations": 0,
        "predeclared_case": {"instance": INSTANCE, "condition": CONDITION, "seed": SEED},
        "selection_rule": "middle network of the frozen nine-network scale list; mixed ownership activates both operating arms; first registered seed",
        "selection_was_not_based_on_timing_result": True,
        "four_cells": "ownership fixed/reassignment allowed crossed with immediate/low-carbon charging",
        "representative_day_contract": "the same frozen 48-slot carbon profile is repeated for pre-day first-trip charging and day-0 between-trip charging",
        "paper_boundary": "wiring probe only; no statistical or general claim",
        "input_files": {str(path.relative_to(ROOT)): sha256(path) for path in input_paths},
        "bundle_files": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in sorted(bundle_dir.iterdir())
            if path.is_file() and not path.name.startswith("._")
        },
        "source_hashes": {str(path.relative_to(ROOT)): sha256(path) for path in SOURCE_FILES},
    }
    write_csv(OUT / "raw_runs.csv", raw_rows)
    write_csv(OUT / "paired_summary.csv", summaries)
    write_csv(OUT / "charging_actions.csv", action_rows)
    write_csv(OUT / "slot_loads.csv", slot_rows)
    write_json(OUT / "metadata.json", metadata)
    write_json(OUT / "decision.json", decision)
    fixed = summary_by_arm["ownership_fixed"]
    shared = summary_by_arm["reassignment_allowed"]
    report = "\n".join(
        [
            "# 充电时机四格最小探针",
            "",
            f"判决：`{decision['verdict']}`。本批没有重新搜索，只在两份严格排班保存解的合法充电窗口内移动固定电量。",
            "",
            "四格分别是：客户仍由原车场服务或允许重新分配客户，再分别采用有空即充和优先低碳时段充电。每种经营方式内部，路线、实体车辆、客户服务关系、充电总量和运营成本完全相同；四格均无排班、电量或时间冲突。" if all_pass else "至少一个机械检查未通过，正式碳复算继续冻结；失败项见 decision.json。",
            "",
            f"在这个单一诊断案例中，固定客户归属方案移动 {fixed['changed_charging_actions']} 次充电、{fixed['moved_charging_kwh']:.3f} 千瓦时，充电排放变化 {fixed['charging_emissions_reduction_pct']:.3f}%；允许重新分配客户的方案移动 {shared['changed_charging_actions']} 次充电、{shared['moved_charging_kwh']:.3f} 千瓦时，充电排放变化 {shared['charging_emissions_reduction_pct']:.3f}%。",
            "",
            "这两个百分比只能说明接线有真实反应，不能进论文结论：这里只有一张网络和一个代表日电网。前一晚首趟充电与当天趟间充电已分开落盘，后续正式设计必须跨冻结网络和真实电网日复算，并以网络和电网日为证据单位。",
        ]
    ) + "\n"
    (OUT / "report.md").write_text(report, encoding="utf-8")
    artifact_files = [
        Path(__file__).resolve(),
        OUT / "metadata.json",
        OUT / "raw_runs.csv",
        OUT / "paired_summary.csv",
        OUT / "charging_actions.csv",
        OUT / "slot_loads.csv",
        OUT / "decision.json",
        OUT / "report.md",
        *input_paths,
        *SOURCE_FILES[:-1],
    ]
    write_json(
        OUT / "artifact_hashes.json",
        {"files": [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in artifact_files]},
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
