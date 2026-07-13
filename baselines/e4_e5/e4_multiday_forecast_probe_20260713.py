#!/usr/bin/env python3
"""Zero-search E4 probe using forecast decisions and actual settlement.

The probe freezes one middle-sized strict E3 network, both operating arms and
all three saved search seeds.  It replays 28 operating days for which the local
NESO extract contains both the complete preceding day and the complete
operating day.  Routes, services, physical vehicles and charging energy never
change.  Result direction does not determine the mechanical verdict.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation import e3_v3_runner as legacy
from setp_solver.cost import carbon_profile_row_for_slot, charging_slot_breakdown
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
CARBON_SOURCE = ROOT / "data/Carbon/时变碳强度/Carbon_Intensity_Data.csv"
OUT = ROOT / "baselines/e4_e5/e4_multiday_forecast_probe_20260713"
INSTANCE = "L-main-threeshift-50c-01"
CONDITION = "mixed"
SEEDS = (1, 2, 3)
ARMS = ("ownership_fixed", "reassignment_allowed")
STRATEGIES = ("immediate", "forecast_timed", "actual_oracle")
FIRST_OPERATING_DAY = date(2025, 11, 2)
LAST_OPERATING_DAY = date(2025, 11, 29)
OPERATING_DAYS = tuple(
    FIRST_OPERATING_DAY + timedelta(days=index)
    for index in range((LAST_OPERATING_DAY - FIRST_OPERATING_DAY).days + 1)
)
TOLERANCE = 1e-6
NESO_API_TEMPLATE = "https://api.carbonintensity.org.uk/intensity/{from_utc}/{to_utc}"
NESO_METHOD_URL = (
    "https://www.neso.energy/data-portal/national-carbon-intensity-forecast/"
    "national_carbon_intensity_forecast_methodology"
)
SOURCE_FILES = (
    ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
    ROOT / "solver/src/setp_solver/cost.py",
    ROOT / "solver/src/setp_solver/check.py",
    Path(__file__).resolve(),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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


def route_hash(solution: Solution) -> str:
    return canonical_hash([asdict(route) for route in solution.routes])


def service_hash(solution: Solution) -> str:
    return canonical_hash([asdict(service) for service in solution.cross_site_services])


def energy_hash(solution: Solution) -> str:
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


def timing_map(solution: Solution) -> dict[str, float]:
    return {action.vehicle_id: float(action.charge_start_second) for action in solution.charging_actions}


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


def formal_rows() -> list[dict[str, str]]:
    with (FORMAL / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    selected = [
        row
        for row in rows
        if row["instance"] == INSTANCE
        and row["condition"] == CONDITION
        and int(row["seed"]) in SEEDS
        and row["arm"] in ARMS
    ]
    expected = {(seed, arm) for seed in SEEDS for arm in ARMS}
    found = {(int(row["seed"]), row["arm"]) for row in selected}
    if found != expected:
        raise RuntimeError(f"incomplete frozen pair set: expected={sorted(expected)}, found={sorted(found)}")
    return sorted(selected, key=lambda row: (int(row["seed"]), row["arm"]))


def ownership_map() -> dict[str, str]:
    path = OWNERSHIP / "ownership_maps" / f"{INSTANCE}__{CONDITION}.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["customer_id"]: row["owner_depot_id"] for row in csv.DictReader(handle)}


def parse_utc_label(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


def load_national_rows() -> dict[datetime, dict[str, str]]:
    with CARBON_SOURCE.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {parse_utc_label(row["Datetime (UTC)"]): row for row in rows}


def calendar_day_profile(source: dict[datetime, dict[str, str]], day: date) -> list[dict[str, Any]]:
    """Build 48 settlement intervals; the source timestamp is the interval end."""

    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    profile: list[dict[str, Any]] = []
    for index in range(48):
        interval_end = midnight + timedelta(minutes=30 * (index + 1))
        if interval_end not in source:
            raise ValueError(f"missing national carbon interval ending {interval_end.isoformat()}")
        raw = source[interval_end]
        profile.append(
            {
                "time_index": index,
                "datetime_utc": interval_end.isoformat(),
                "actual_gco2_per_kwh": float(raw["Actual Carbon Intensity (gCO2/kWh)"]),
                "forecast_gco2_per_kwh": float(raw["Forecast Carbon Intensity (gCO2/kWh)"]),
                "index_label": raw["Index"],
                "index_code": 0,
                "horizon_second_start": float(index * 1800),
            }
        )
    return profile


def profiles_for_operating_day(
    source: dict[datetime, dict[str, str]], operating_day: date
) -> dict[int, list[dict[str, Any]]]:
    return {
        -1: calendar_day_profile(source, operating_day - timedelta(days=1)),
        0: calendar_day_profile(source, operating_day),
    }


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


def action_emissions_kg(
    action: Any,
    instance: Any,
    profiles: dict[int, list[dict[str, Any]]],
    field: str,
) -> float:
    profile = profiles[int(action.charge_day_offset)]
    total = 0.0
    for slot in charging_slot_breakdown(
        float(action.charge_start_second),
        float(action.occupancy_minutes) * 60.0,
        float(action.energy_kwh),
        instance,
        n_slots=len(profile),
        cyclic=True,
    ):
        row = carbon_profile_row_for_slot(profile, slot.slot_index)
        total += float(slot.y_skt_kwh) * float(row[field]) / 1000.0
    return total


def clock_violations(solution: Solution, certificate: MultiTripCertificate) -> int:
    violations = 0
    for action in solution.charging_actions:
        earliest, latest = action_window(action, certificate)
        start = float(action.charge_start_second)
        if start < earliest - TOLERANCE or start > latest + TOLERANCE:
            violations += 1
        scope = charge_scope(action, certificate)
        if scope == "pre_day_first_trip" and int(action.charge_day_offset) != STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET:
            violations += 1
        if scope == "same_day_between_trip" and int(action.charge_day_offset) != 0:
            violations += 1
    return violations


def exact_sign_p(values: list[float]) -> float:
    positives = sum(value > TOLERANCE for value in values)
    negatives = sum(value < -TOLERANCE for value in values)
    n = positives + negatives
    if n == 0:
        return 1.0
    smaller = min(positives, negatives)
    tail = sum(math.comb(n, k) for k in range(smaller + 1)) / (2**n)
    return min(1.0, 2.0 * tail)


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    source_carbon = load_national_rows()
    bundle_dir = FORMAL / "assets" / INSTANCE / "bundle"
    bundle = load_search_bundle(bundle_dir)
    prices = legacy.prices_for("M1", 0.0)
    owners = ownership_map()
    inputs: list[Path] = [CARBON_SOURCE]
    raw_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []

    for formal_row in formal_rows():
        seed = int(formal_row["seed"])
        arm = formal_row["arm"]
        solution_path = ROOT / formal_row["solution_path"]
        certificate_path = ROOT / formal_row["certificate_path"]
        inputs.extend((solution_path, certificate_path))
        source = _solution_from_dict(json.loads(solution_path.read_text(encoding="utf-8")))
        certificate = load_certificate(certificate_path)
        validate_multitrip_certificate(certificate, source.routes, prices)
        source_route_hash = route_hash(source)
        source_service_hash = service_hash(source)
        source_energy_hash = energy_hash(source)

        for operating_day in OPERATING_DAYS:
            profiles = profiles_for_operating_day(source_carbon, operating_day)
            variants = {
                "immediate": reschedule_between_trip_charging(
                    source,
                    certificate,
                    bundle.instance,
                    profiles[0],
                    strategy="naive",
                    carbon_profiles_by_day_offset=profiles,
                ),
                "forecast_timed": reschedule_between_trip_charging(
                    source,
                    certificate,
                    bundle.instance,
                    profiles[0],
                    strategy="aware",
                    carbon_profiles_by_day_offset=profiles,
                    intensity_field="forecast_gco2_per_kwh",
                ),
                "actual_oracle": reschedule_between_trip_charging(
                    source,
                    certificate,
                    bundle.instance,
                    profiles[0],
                    strategy="aware",
                    carbon_profiles_by_day_offset=profiles,
                    intensity_field="actual_gco2_per_kwh",
                ),
            }
            immediate_times = timing_map(variants["immediate"])
            for strategy in STRATEGIES:
                solution = variants[strategy]
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

                actual_by_scope: Counter[str] = Counter()
                forecast_by_scope: Counter[str] = Counter()
                energy_by_scope: Counter[str] = Counter()
                eligible_by_scope: Counter[str] = Counter()
                moved_by_scope: Counter[str] = Counter()
                for action in solution.charging_actions:
                    scope = charge_scope(action, certificate)
                    actual_emissions = action_emissions_kg(
                        action, bundle.instance, profiles, "actual_gco2_per_kwh"
                    )
                    forecast_emissions = action_emissions_kg(
                        action, bundle.instance, profiles, "forecast_gco2_per_kwh"
                    )
                    actual_by_scope[scope] += actual_emissions
                    forecast_by_scope[scope] += forecast_emissions
                    energy_by_scope[scope] += float(action.energy_kwh)
                    earliest, latest = action_window(action, certificate)
                    if latest > earliest + TOLERANCE:
                        eligible_by_scope[scope] += float(action.energy_kwh)
                    moved = abs(float(action.charge_start_second) - immediate_times[action.vehicle_id]) > TOLERANCE
                    if moved:
                        moved_by_scope[scope] += float(action.energy_kwh)
                    action_rows.append(
                        {
                            "operating_day": operating_day.isoformat(),
                            "previous_day": (operating_day - timedelta(days=1)).isoformat(),
                            "seed": seed,
                            "arm": arm,
                            "timing_rule": strategy,
                            "vehicle_trip": action.vehicle_id,
                            "charge_scope": scope,
                            "charge_day_offset": int(action.charge_day_offset),
                            "charge_start_second": float(action.charge_start_second),
                            "energy_kwh": float(action.energy_kwh),
                            "earliest_start_second": earliest,
                            "latest_start_second": latest,
                            "timing_slack_hours": max(0.0, latest - earliest) / 3600.0,
                            "moved_from_immediate": moved,
                            "actual_emissions_kg": actual_emissions,
                            "forecast_emissions_kg": forecast_emissions,
                        }
                    )
                charging_actual = sum(actual_by_scope.values())
                charging_forecast = sum(forecast_by_scope.values())
                direct_fuel = float(formal_row["E_cv_direct"])
                raw_rows.append(
                    {
                        "operating_day": operating_day.isoformat(),
                        "previous_day": (operating_day - timedelta(days=1)).isoformat(),
                        "seed": seed,
                        "arm": arm,
                        "timing_rule": strategy,
                        "route_fingerprint": route_hash(solution),
                        "service_fingerprint": service_hash(solution),
                        "energy_fingerprint": energy_hash(solution),
                        "route_unchanged": route_hash(solution) == source_route_hash,
                        "service_unchanged": service_hash(solution) == source_service_hash,
                        "energy_unchanged": energy_hash(solution) == source_energy_hash,
                        "hard_violation_count": len(violations),
                        "clock_violation_count": clock_violations(solution, certificate),
                        "charging_kwh": sum(energy_by_scope.values()),
                        "eligible_pre_day_kwh": eligible_by_scope["pre_day_first_trip"],
                        "eligible_between_trip_kwh": eligible_by_scope["same_day_between_trip"],
                        "moved_pre_day_kwh": moved_by_scope["pre_day_first_trip"],
                        "moved_between_trip_kwh": moved_by_scope["same_day_between_trip"],
                        "actual_charging_emissions_kg": charging_actual,
                        "forecast_charging_emissions_kg": charging_forecast,
                        "actual_pre_day_emissions_kg": actual_by_scope["pre_day_first_trip"],
                        "actual_between_trip_emissions_kg": actual_by_scope["same_day_between_trip"],
                        "direct_fuel_emissions_kg": direct_fuel,
                        "actual_total_operational_emissions_kg": direct_fuel + charging_actual,
                    }
                )

    indexed = {
        (row["operating_day"], int(row["seed"]), row["arm"], row["timing_rule"]): row
        for row in raw_rows
    }
    pair_rows: list[dict[str, Any]] = []
    for operating_day in OPERATING_DAYS:
        day_key = operating_day.isoformat()
        for seed in SEEDS:
            for arm in ARMS:
                immediate = indexed[(day_key, seed, arm, "immediate")]
                forecast = indexed[(day_key, seed, arm, "forecast_timed")]
                oracle = indexed[(day_key, seed, arm, "actual_oracle")]
                immediate_actual = float(immediate["actual_charging_emissions_kg"])
                forecast_actual = float(forecast["actual_charging_emissions_kg"])
                oracle_actual = float(oracle["actual_charging_emissions_kg"])
                realized = immediate_actual - forecast_actual
                potential = immediate_actual - oracle_actual
                pair_rows.append(
                    {
                        "operating_day": day_key,
                        "seed": seed,
                        "arm": arm,
                        "charging_kwh": immediate["charging_kwh"],
                        "immediate_actual_kg": immediate_actual,
                        "forecast_timed_actual_kg": forecast_actual,
                        "oracle_actual_kg": oracle_actual,
                        "realized_saving_kg": realized,
                        "realized_saving_pct": 100.0 * realized / immediate_actual if immediate_actual else 0.0,
                        "oracle_potential_kg": potential,
                        "oracle_potential_pct": 100.0 * potential / immediate_actual if immediate_actual else 0.0,
                        "forecast_capture_ratio": realized / potential if potential > TOLERANCE else 0.0,
                        "predicted_saving_kg": float(immediate["forecast_charging_emissions_kg"])
                        - float(forecast["forecast_charging_emissions_kg"]),
                        "pre_day_realized_saving_kg": float(immediate["actual_pre_day_emissions_kg"])
                        - float(forecast["actual_pre_day_emissions_kg"]),
                        "between_trip_realized_saving_kg": float(immediate["actual_between_trip_emissions_kg"])
                        - float(forecast["actual_between_trip_emissions_kg"]),
                        "moved_pre_day_kwh": forecast["moved_pre_day_kwh"],
                        "moved_between_trip_kwh": forecast["moved_between_trip_kwh"],
                    }
                )

    day_arm_rows: list[dict[str, Any]] = []
    for operating_day in OPERATING_DAYS:
        day_key = operating_day.isoformat()
        for arm in ARMS:
            rows = [row for row in pair_rows if row["operating_day"] == day_key and row["arm"] == arm]
            immediate = mean([float(row["immediate_actual_kg"]) for row in rows])
            realized = mean([float(row["realized_saving_kg"]) for row in rows])
            potential = mean([float(row["oracle_potential_kg"]) for row in rows])
            day_arm_rows.append(
                {
                    "operating_day": day_key,
                    "arm": arm,
                    "seed_count": len(rows),
                    "mean_immediate_actual_kg": immediate,
                    "mean_realized_saving_kg": realized,
                    "mean_realized_saving_pct": 100.0 * realized / immediate if immediate else 0.0,
                    "mean_oracle_potential_kg": potential,
                    "mean_oracle_potential_pct": 100.0 * potential / immediate if immediate else 0.0,
                    "mean_forecast_capture_ratio": realized / potential if potential > TOLERANCE else 0.0,
                    "mean_predicted_saving_kg": mean([float(row["predicted_saving_kg"]) for row in rows]),
                    "mean_pre_day_realized_saving_kg": mean(
                        [float(row["pre_day_realized_saving_kg"]) for row in rows]
                    ),
                    "mean_between_trip_realized_saving_kg": mean(
                        [float(row["between_trip_realized_saving_kg"]) for row in rows]
                    ),
                }
            )

    aggregate_rows: list[dict[str, Any]] = []
    for arm in ARMS:
        rows = [row for row in day_arm_rows if row["arm"] == arm]
        reductions = [float(row["mean_realized_saving_pct"]) for row in rows]
        pooled_immediate = sum(float(row["mean_immediate_actual_kg"]) for row in rows)
        pooled_realized = sum(float(row["mean_realized_saving_kg"]) for row in rows)
        pooled_potential = sum(float(row["mean_oracle_potential_kg"]) for row in rows)
        aggregate_rows.append(
            {
                "arm": arm,
                "operating_day_count": len(rows),
                "days_actual_improved": sum(value > TOLERANCE for value in reductions),
                "days_actual_worsened": sum(value < -TOLERANCE for value in reductions),
                "days_actual_tied": sum(abs(value) <= TOLERANCE for value in reductions),
                "mean_day_reduction_pct": mean(reductions),
                "median_day_reduction_pct": statistics.median(reductions),
                "pooled_reduction_pct": 100.0 * pooled_realized / pooled_immediate if pooled_immediate else 0.0,
                "pooled_oracle_potential_pct": 100.0 * pooled_potential / pooled_immediate if pooled_immediate else 0.0,
                "pooled_forecast_capture_ratio": pooled_realized / pooled_potential if pooled_potential > TOLERANCE else 0.0,
                "mean_pre_day_saving_kg": mean([float(row["mean_pre_day_realized_saving_kg"]) for row in rows]),
                "mean_between_trip_saving_kg": mean(
                    [float(row["mean_between_trip_realized_saving_kg"]) for row in rows]
                ),
                "two_sided_sign_p": exact_sign_p(reductions),
            }
        )

    day_by_arm = {(row["operating_day"], row["arm"]): row for row in day_arm_rows}
    cross_arm_rows: list[dict[str, Any]] = []
    for operating_day in OPERATING_DAYS:
        day_key = operating_day.isoformat()
        fixed = day_by_arm[(day_key, "ownership_fixed")]
        shared = day_by_arm[(day_key, "reassignment_allowed")]
        cross_arm_rows.append(
            {
                "operating_day": day_key,
                "reassignment_minus_fixed_reduction_percentage_points": float(shared["mean_realized_saving_pct"])
                - float(fixed["mean_realized_saving_pct"]),
                "reassignment_minus_fixed_oracle_potential_percentage_points": float(shared["mean_oracle_potential_pct"])
                - float(fixed["mean_oracle_potential_pct"]),
            }
        )

    expected_raw = len(OPERATING_DAYS) * len(SEEDS) * len(ARMS) * len(STRATEGIES)
    mechanical_checks = {
        "complete_expected_matrix": len(raw_rows) == expected_raw,
        "routes_frozen": all(bool(row["route_unchanged"]) for row in raw_rows),
        "services_frozen": all(bool(row["service_unchanged"]) for row in raw_rows),
        "energy_frozen": all(bool(row["energy_unchanged"]) for row in raw_rows),
        "strict_legality": all(int(row["hard_violation_count"]) == 0 for row in raw_rows),
        "clock_legality": all(int(row["clock_violation_count"]) == 0 for row in raw_rows),
        "forecast_rule_improves_its_forecast_objective": all(
            float(row["predicted_saving_kg"]) >= -TOLERANCE for row in pair_rows
        ),
        "actual_oracle_is_actual_lower_bound": all(
            float(row["oracle_actual_kg"]) <= float(row["forecast_timed_actual_kg"]) + TOLERANCE
            and float(row["oracle_actual_kg"]) <= float(row["immediate_actual_kg"]) + TOLERANCE
            for row in pair_rows
        ),
        "source_has_1393_verified_rows": len(source_carbon) == 1393,
        "operating_days_have_previous_day": len(OPERATING_DAYS) == 28,
    }
    all_pass = all(mechanical_checks.values())

    write_csv(OUT / "raw_runs.csv", raw_rows)
    write_csv(OUT / "action_runs.csv", action_rows)
    write_csv(OUT / "paired_by_seed_day.csv", pair_rows)
    write_csv(OUT / "day_arm_summary.csv", day_arm_rows)
    write_csv(OUT / "aggregate_summary.csv", aggregate_rows)
    write_csv(OUT / "cross_arm_by_day.csv", cross_arm_rows)

    metadata = {
        "schema": "setp.e4.multiday_forecast_probe.v1",
        "execution_commit_before_probe": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "search_evaluations": 0,
        "network": INSTANCE,
        "ownership_condition": CONDITION,
        "seeds": list(SEEDS),
        "operating_days": [day.isoformat() for day in OPERATING_DAYS],
        "calendar_contract": (
            "source timestamp is NESO interval end; operating-day slot 0 uses the row ending 00:30; "
            "pre-day first-trip charging uses the preceding calendar-day profile"
        ),
        "decision_rule": "forecast_timed minimizes forecast intensity; all reported emissions use actual intensity",
        "oracle_role": "diagnostic upper bound only; never presented as an implementable operating policy",
        "national_profile_reason": (
            "the benchmark spans real UK city coordinates but does not preserve a unique DNO-region identity; "
            "a simple average of regional forecasts is not treated as a physical region"
        ),
        "source_api": NESO_API_TEMPLATE.format(
            from_utc="2025-11-01T00:00Z", to_utc="2025-11-30T00:00Z"
        ),
        "source_methodology": NESO_METHOD_URL,
        "source_csv_sha256": sha256(CARBON_SOURCE),
        "source_api_full_range_reverification": {
            "api_rows": 1393,
            "local_rows": 1393,
            "field_mismatches": 0,
            "verified_on": "2026-07-13",
        },
        "input_hashes": {str(path.relative_to(ROOT)): sha256(path) for path in sorted(set(inputs))},
        "source_hashes": {str(path.relative_to(ROOT)): sha256(path) for path in SOURCE_FILES},
        "paper_boundary": "one-network multiday diagnostic; no network-general claim",
        "result_direction_did_not_gate_execution": True,
    }
    decision = {
        "verdict": "PASS_E4_MULTIDAY_FORECAST_PROBE" if all_pass else "HALT_E4_MULTIDAY_FORECAST_PROBE",
        "all_mechanical_checks_pass": all_pass,
        "mechanical_checks": mechanical_checks,
        "result_direction_did_not_gate_execution": True,
        "formal_evidence_status": "diagnostic only; 28 grid days but one operational network",
        "next_gate": (
            "use this result to decide whether a nine-network zero-search replay is scientifically worthwhile; "
            "do not rerun routes or tune dates"
        ),
    }
    write_json(OUT / "metadata.json", metadata)
    write_json(OUT / "decision.json", decision)

    by_arm = {row["arm"]: row for row in aggregate_rows}
    fixed = by_arm["ownership_fixed"]
    shared = by_arm["reassignment_allowed"]
    report = "\n".join(
        [
            "# 按预测择时、按实际结算：多日最小探针",
            "",
            f"判决：`{decision['verdict']}`。本批没有重新搜索路线，只把同一固定电量放进合法充电窗口。",
            "",
            (
                f"客户仍由原车场服务时，按预测择时在 {fixed['days_actual_improved']}/28 天降低了实际充电排放，"
                f"在 {fixed['days_actual_worsened']}/28 天反而升高；28 天合计变化 {fixed['pooled_reduction_pct']:.3f}%。"
            ),
            (
                f"允许重新分配客户时，按预测择时在 {shared['days_actual_improved']}/28 天降低了实际充电排放，"
                f"在 {shared['days_actual_worsened']}/28 天反而升高；28 天合计变化 {shared['pooled_reduction_pct']:.3f}%。"
            ),
            "",
            (
                f"如果事先知道实际碳强度，理论上最多可分别降低 {fixed['pooled_oracle_potential_pct']:.3f}% 和 "
                f"{shared['pooled_oracle_potential_pct']:.3f}%。预测策略兑现了其中 "
                f"{fixed['pooled_forecast_capture_ratio']:.3f} 和 {shared['pooled_forecast_capture_ratio']:.3f}。"
            ),
            "",
            (
                "这些数字只用于判断研究方向：它们覆盖多个真实电网日，但只有一张运营网络，不能直接写成普遍结论。"
                "正式扩大前应先看收益是否主要来自前夜首趟充电、当天趟间空档，还是预测误差；三者已经分列落盘。"
            ),
        ]
    ) + "\n"
    (OUT / "report.md").write_text(report, encoding="utf-8")

    artifact_files = [
        Path(__file__).resolve(),
        OUT / "metadata.json",
        OUT / "decision.json",
        OUT / "raw_runs.csv",
        OUT / "action_runs.csv",
        OUT / "paired_by_seed_day.csv",
        OUT / "day_arm_summary.csv",
        OUT / "aggregate_summary.csv",
        OUT / "cross_arm_by_day.csv",
        OUT / "report.md",
        *sorted(set(inputs)),
        *SOURCE_FILES[:-1],
    ]
    write_json(
        OUT / "artifact_hashes.json",
        {"files": [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in artifact_files]},
    )
    print(json.dumps({"decision": decision, "aggregate": aggregate_rows}, ensure_ascii=False, indent=2))
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
