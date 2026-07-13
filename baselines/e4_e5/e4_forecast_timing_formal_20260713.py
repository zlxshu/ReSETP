#!/usr/bin/env python3
"""Formal zero-search replay of forecast-timed charging across all E3 networks.

The experiment freezes every saved E3 route, service assignment, physical
vehicle and charging-energy ledger.  It replays all 28 calendar days for which
the local NESO extract contains the complete preceding and operating day.
Forecast intensity chooses the implementable timing; actual intensity settles
emissions.  The actual-aware schedule is an appendix-only oracle bound.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from pathlib import Path
import csv
import json
import statistics
import subprocess
import sys
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation import e3_v3_runner as legacy
from baselines.e4_e5 import e4_multiday_forecast_probe_20260713 as probe
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.e3_multitrip_runtime import hard_violations
from setp_solver.search.evaluation import EvaluationContext, cross_depot_violations
from setp_solver.search.formal_runner import _solution_from_dict
from setp_solver.search.multitrip_schedule import (
    reschedule_between_trip_charging,
    validate_multitrip_certificate,
)


FORMAL = probe.FORMAL
OWNERSHIP = probe.OWNERSHIP
CARBON_SOURCE = probe.CARBON_SOURCE
OUT = ROOT / "baselines/e4_e5/e4_forecast_timing_formal_20260713"
CONTRACT = ROOT / "baselines/e4_e5/e4_forecast_timing_formal_contract_20260713.md"
CONDITIONS = ("geographic", "mixed")
ARMS = probe.ARMS
SEEDS = probe.SEEDS
STRATEGIES = probe.STRATEGIES
OPERATING_DAYS = probe.OPERATING_DAYS
TOLERANCE = probe.TOLERANCE
SOURCE_FILES = (
    Path(__file__).resolve(),
    ROOT / "baselines/e4_e5/e4_multiday_forecast_probe_20260713.py",
    ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
    ROOT / "solver/src/setp_solver/cost.py",
    ROOT / "solver/src/setp_solver/check.py",
    ROOT / "solver/src/setp_solver/search/e3_multitrip_runtime.py",
    ROOT / "solver/src/setp_solver/search/formal_runner.py",
)


def mean(values: Iterable[float]) -> float:
    materialized = list(values)
    return statistics.fmean(materialized) if materialized else 0.0


def median(values: Iterable[float]) -> float:
    materialized = list(values)
    return statistics.median(materialized) if materialized else 0.0


def pct(numerator: float, denominator: float) -> float:
    return 100.0 * numerator / denominator if abs(denominator) > TOLERANCE else 0.0


def formal_metadata() -> dict[str, Any]:
    return json.loads((FORMAL / "metadata.json").read_text(encoding="utf-8"))


def load_formal_rows(instances: tuple[str, ...]) -> list[dict[str, str]]:
    with (FORMAL / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    expected = {
        (instance, condition, seed, arm)
        for instance in instances
        for condition in CONDITIONS
        for seed in SEEDS
        for arm in ARMS
    }
    found = {
        (row["instance"], row["condition"], int(row["seed"]), row["arm"])
        for row in rows
    }
    if found != expected or len(rows) != len(expected):
        raise RuntimeError(
            f"formal input matrix mismatch: expected={len(expected)}, rows={len(rows)}, "
            f"missing={sorted(expected - found)}, extra={sorted(found - expected)}"
        )
    if any(row["status"] != "PASS" or int(row["violation_count"]) != 0 for row in rows):
        raise RuntimeError("formal E3 input contains a failed or violating row")
    return sorted(
        rows,
        key=lambda row: (row["instance"], row["condition"], int(row["seed"]), row["arm"]),
    )


def ownership_path(instance: str, condition: str) -> Path:
    return OWNERSHIP / "ownership_maps" / f"{instance}__{condition}.csv"


def ownership_map(instance: str, condition: str) -> dict[str, str]:
    with ownership_path(instance, condition).open(newline="", encoding="utf-8") as handle:
        return {row["customer_id"]: row["owner_depot_id"] for row in csv.DictReader(handle)}


def aggregate_pairs(
    rows: list[dict[str, Any]],
    *,
    keys: tuple[str, ...],
    expected_group_size: int,
) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(tuple(row[key] for key in keys), []).append(row)
    out: list[dict[str, Any]] = []
    for group_key in sorted(groups):
        group = groups[group_key]
        if len(group) != expected_group_size:
            raise RuntimeError(f"group {dict(zip(keys, group_key))} has {len(group)} rows")
        immediate_charging = mean(float(row["immediate_actual_charging_kg"]) for row in group)
        forecast_charging = mean(float(row["forecast_actual_charging_kg"]) for row in group)
        direct_fuel = mean(float(row["direct_fuel_emissions_kg"]) for row in group)
        realized = mean(float(row["realized_saving_kg"]) for row in group)
        potential = mean(float(row["oracle_potential_kg"]) for row in group)
        record: dict[str, Any] = dict(zip(keys, group_key))
        record.update(
            {
                "source_row_count": len(group),
                "mean_charging_kwh": mean(float(row["charging_kwh"]) for row in group),
                "mean_immediate_actual_charging_kg": immediate_charging,
                "mean_forecast_actual_charging_kg": forecast_charging,
                "mean_direct_fuel_emissions_kg": direct_fuel,
                "mean_immediate_total_operational_kg": direct_fuel + immediate_charging,
                "mean_forecast_total_operational_kg": direct_fuel + forecast_charging,
                "mean_realized_saving_kg": realized,
                "charging_reduction_pct": pct(realized, immediate_charging),
                "total_operational_reduction_pct": pct(realized, direct_fuel + immediate_charging),
                "charging_share_of_immediate_total_pct": pct(
                    immediate_charging, direct_fuel + immediate_charging
                ),
                "mean_oracle_potential_kg": potential,
                "oracle_potential_pct": pct(potential, immediate_charging),
                "forecast_capture_ratio": realized / potential if potential > TOLERANCE else 0.0,
                "mean_predicted_saving_kg": mean(float(row["predicted_saving_kg"]) for row in group),
                "mean_pre_day_realized_saving_kg": mean(
                    float(row["pre_day_realized_saving_kg"]) for row in group
                ),
                "mean_between_trip_realized_saving_kg": mean(
                    float(row["between_trip_realized_saving_kg"]) for row in group
                ),
                "mean_moved_pre_day_kwh": mean(float(row["moved_pre_day_kwh"]) for row in group),
                "mean_moved_between_trip_kwh": mean(
                    float(row["moved_between_trip_kwh"]) for row in group
                ),
            }
        )
        out.append(record)
    return out


def summarize_dimension(
    cell_rows: list[dict[str, Any]],
    *,
    dimension: str,
    expected_count: int,
) -> list[dict[str, Any]]:
    other = "operating_day" if dimension == "instance" else "instance"
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in cell_rows:
        groups.setdefault((row["condition"], row["arm"], row[dimension]), []).append(row)
    out: list[dict[str, Any]] = []
    for key in sorted(groups):
        rows = groups[key]
        if len(rows) != expected_count:
            raise RuntimeError(f"{dimension} summary {key} has {len(rows)} {other} rows")
        immediate = sum(float(row["mean_immediate_actual_charging_kg"]) for row in rows)
        total_immediate = sum(float(row["mean_immediate_total_operational_kg"]) for row in rows)
        realized = sum(float(row["mean_realized_saving_kg"]) for row in rows)
        potential = sum(float(row["mean_oracle_potential_kg"]) for row in rows)
        reductions = [float(row["charging_reduction_pct"]) for row in rows]
        out.append(
            {
                "condition": key[0],
                "arm": key[1],
                dimension: key[2],
                f"{other}_count": len(rows),
                "pooled_immediate_actual_charging_kg": immediate,
                "pooled_realized_saving_kg": realized,
                "pooled_charging_reduction_pct": pct(realized, immediate),
                "pooled_total_operational_reduction_pct": pct(realized, total_immediate),
                "mean_cell_charging_reduction_pct": mean(reductions),
                "median_cell_charging_reduction_pct": median(reductions),
                "cells_improved": sum(value > TOLERANCE for value in reductions),
                "cells_worsened": sum(value < -TOLERANCE for value in reductions),
                "cells_tied": sum(abs(value) <= TOLERANCE for value in reductions),
                "two_sided_sign_p": probe.exact_sign_p(reductions),
                "pooled_oracle_potential_pct": pct(potential, immediate),
                "pooled_forecast_capture_ratio": realized / potential if potential > TOLERANCE else 0.0,
                "pooled_pre_day_saving_kg": sum(
                    float(row["mean_pre_day_realized_saving_kg"]) for row in rows
                ),
                "pooled_between_trip_saving_kg": sum(
                    float(row["mean_between_trip_realized_saving_kg"]) for row in rows
                ),
            }
        )
    return out


def aggregate_summary(
    cell_rows: list[dict[str, Any]],
    network_rows: list[dict[str, Any]],
    day_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for condition in CONDITIONS:
        for arm in ARMS:
            cells = [
                row for row in cell_rows if row["condition"] == condition and row["arm"] == arm
            ]
            networks = [
                row for row in network_rows if row["condition"] == condition and row["arm"] == arm
            ]
            days = [row for row in day_rows if row["condition"] == condition and row["arm"] == arm]
            immediate = sum(float(row["mean_immediate_actual_charging_kg"]) for row in cells)
            total_immediate = sum(float(row["mean_immediate_total_operational_kg"]) for row in cells)
            realized = sum(float(row["mean_realized_saving_kg"]) for row in cells)
            potential = sum(float(row["mean_oracle_potential_kg"]) for row in cells)
            network_effects = [float(row["pooled_charging_reduction_pct"]) for row in networks]
            day_effects = [float(row["pooled_charging_reduction_pct"]) for row in days]
            pre_day = sum(float(row["mean_pre_day_realized_saving_kg"]) for row in cells)
            between_trip = sum(float(row["mean_between_trip_realized_saving_kg"]) for row in cells)
            out.append(
                {
                    "condition": condition,
                    "arm": arm,
                    "network_count": len(networks),
                    "operating_day_count": len(days),
                    "cell_count": len(cells),
                    "pooled_immediate_actual_charging_kg": immediate,
                    "pooled_realized_saving_kg": realized,
                    "pooled_charging_reduction_pct": pct(realized, immediate),
                    "pooled_total_operational_reduction_pct": pct(realized, total_immediate),
                    "pooled_charging_share_of_total_pct": pct(immediate, total_immediate),
                    "pooled_oracle_potential_pct": pct(potential, immediate),
                    "pooled_forecast_capture_ratio": realized / potential if potential > TOLERANCE else 0.0,
                    "network_mean_reduction_pct": mean(network_effects),
                    "network_median_reduction_pct": median(network_effects),
                    "networks_improved": sum(value > TOLERANCE for value in network_effects),
                    "networks_worsened": sum(value < -TOLERANCE for value in network_effects),
                    "networks_tied": sum(abs(value) <= TOLERANCE for value in network_effects),
                    "network_two_sided_sign_p": probe.exact_sign_p(network_effects),
                    "day_mean_reduction_pct": mean(day_effects),
                    "day_median_reduction_pct": median(day_effects),
                    "days_improved": sum(value > TOLERANCE for value in day_effects),
                    "days_worsened": sum(value < -TOLERANCE for value in day_effects),
                    "days_tied": sum(abs(value) <= TOLERANCE for value in day_effects),
                    "day_two_sided_sign_p": probe.exact_sign_p(day_effects),
                    "pooled_pre_day_saving_kg": pre_day,
                    "pooled_between_trip_saving_kg": between_trip,
                    "pre_day_share_of_positive_total_saving_pct": pct(
                        pre_day, realized
                    ) if realized > TOLERANCE else 0.0,
                }
            )
    return out


def interaction_tables(
    cell_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    index = {
        (row["instance"], row["condition"], row["operating_day"], row["arm"]): row
        for row in cell_rows
    }
    cells: list[dict[str, Any]] = []
    instances = sorted({row["instance"] for row in cell_rows})
    for instance in instances:
        for condition in CONDITIONS:
            for day in OPERATING_DAYS:
                day_key = day.isoformat()
                fixed = index[(instance, condition, day_key, "ownership_fixed")]
                shared = index[(instance, condition, day_key, "reassignment_allowed")]
                cells.append(
                    {
                        "instance": instance,
                        "condition": condition,
                        "operating_day": day_key,
                        "reassignment_minus_fixed_reduction_percentage_points": float(
                            shared["charging_reduction_pct"]
                        )
                        - float(fixed["charging_reduction_pct"]),
                        "reassignment_minus_fixed_total_reduction_percentage_points": float(
                            shared["total_operational_reduction_pct"]
                        )
                        - float(fixed["total_operational_reduction_pct"]),
                        "reassignment_minus_fixed_realized_saving_kg": float(
                            shared["mean_realized_saving_kg"]
                        )
                        - float(fixed["mean_realized_saving_kg"]),
                        "reassignment_minus_fixed_oracle_percentage_points": float(
                            shared["oracle_potential_pct"]
                        )
                        - float(fixed["oracle_potential_pct"]),
                    }
                )

    def summarize(group_field: str, expected: int) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in cells:
            groups.setdefault((row["condition"], row[group_field]), []).append(row)
        out: list[dict[str, Any]] = []
        for key in sorted(groups):
            rows = groups[key]
            if len(rows) != expected:
                raise RuntimeError(f"interaction {group_field} {key} has {len(rows)} rows")
            values = [
                float(row["reassignment_minus_fixed_reduction_percentage_points"]) for row in rows
            ]
            out.append(
                {
                    "condition": key[0],
                    group_field: key[1],
                    "source_cell_count": len(rows),
                    "mean_difference_percentage_points": mean(values),
                    "median_difference_percentage_points": median(values),
                    "reassignment_higher": sum(value > TOLERANCE for value in values),
                    "reassignment_lower": sum(value < -TOLERANCE for value in values),
                    "tied": sum(abs(value) <= TOLERANCE for value in values),
                    "two_sided_sign_p": probe.exact_sign_p(values),
                }
            )
        return out

    by_network = summarize("instance", len(OPERATING_DAYS))
    by_day = summarize("operating_day", len(instances))
    overall: list[dict[str, Any]] = []
    for condition in CONDITIONS:
        network_values = [
            float(row["mean_difference_percentage_points"])
            for row in by_network
            if row["condition"] == condition
        ]
        day_values = [
            float(row["mean_difference_percentage_points"])
            for row in by_day
            if row["condition"] == condition
        ]
        overall.append(
            {
                "condition": condition,
                "network_count": len(network_values),
                "day_count": len(day_values),
                "network_mean_difference_percentage_points": mean(network_values),
                "network_positive": sum(value > TOLERANCE for value in network_values),
                "network_negative": sum(value < -TOLERANCE for value in network_values),
                "network_two_sided_sign_p": probe.exact_sign_p(network_values),
                "day_mean_difference_percentage_points": mean(day_values),
                "day_positive": sum(value > TOLERANCE for value in day_values),
                "day_negative": sum(value < -TOLERANCE for value in day_values),
                "day_two_sided_sign_p": probe.exact_sign_p(day_values),
            }
        )
    return cells, by_network, by_day, overall


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    meta = formal_metadata()
    instances = tuple(meta["instances"])
    formal_rows = load_formal_rows(instances)
    source_carbon = probe.load_national_rows()
    profiles_by_day = {
        day.isoformat(): probe.profiles_for_operating_day(source_carbon, day)
        for day in OPERATING_DAYS
    }
    bundles = {
        instance: load_search_bundle(FORMAL / "assets" / instance / "bundle")
        for instance in instances
    }
    owners = {
        (instance, condition): ownership_map(instance, condition)
        for instance in instances
        for condition in CONDITIONS
    }
    prices = legacy.prices_for("M1", 0.0)
    inputs: set[Path] = {
        CARBON_SOURCE,
        CONTRACT,
        FORMAL / "raw_runs.csv",
        FORMAL / "metadata.json",
        FORMAL / "decision.json",
        FORMAL / "artifact_hashes.json",
    }
    inputs.update(ownership_path(instance, condition) for instance in instances for condition in CONDITIONS)
    raw_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []

    for source_row in formal_rows:
        instance = source_row["instance"]
        condition = source_row["condition"]
        arm = source_row["arm"]
        seed = int(source_row["seed"])
        solution_path = ROOT / source_row["solution_path"]
        certificate_path = ROOT / source_row["certificate_path"]
        inputs.update((solution_path, certificate_path))
        source = _solution_from_dict(json.loads(solution_path.read_text(encoding="utf-8")))
        certificate = probe.load_certificate(certificate_path)
        validate_multitrip_certificate(certificate, source.routes, prices)
        bundle = bundles[instance]
        owner_map = owners[(instance, condition)]
        route_fingerprint = probe.route_hash(source)
        service_fingerprint = probe.service_hash(source)
        energy_fingerprint = probe.energy_hash(source)

        for operating_day in OPERATING_DAYS:
            day_key = operating_day.isoformat()
            profiles = profiles_by_day[day_key]
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
            immediate_times = probe.timing_map(variants["immediate"])
            for strategy in STRATEGIES:
                solution = variants[strategy]
                context = EvaluationContext(
                    bundle.instance,
                    bundle.carbon_profile,
                    prices=prices,
                    carbon_weight=0.0,
                    fairness_enabled=False,
                    customer_home_depot=owner_map,
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
                for action_index, action in enumerate(solution.charging_actions):
                    scope = probe.charge_scope(action, certificate)
                    actual_emissions = probe.action_emissions_kg(
                        action, bundle.instance, profiles, "actual_gco2_per_kwh"
                    )
                    forecast_emissions = probe.action_emissions_kg(
                        action, bundle.instance, profiles, "forecast_gco2_per_kwh"
                    )
                    actual_by_scope[scope] += actual_emissions
                    forecast_by_scope[scope] += forecast_emissions
                    energy_by_scope[scope] += float(action.energy_kwh)
                    earliest, latest = probe.action_window(action, certificate)
                    if latest > earliest + TOLERANCE:
                        eligible_by_scope[scope] += float(action.energy_kwh)
                    moved = (
                        abs(float(action.charge_start_second) - immediate_times[action.vehicle_id])
                        > TOLERANCE
                    )
                    if moved:
                        moved_by_scope[scope] += float(action.energy_kwh)
                    action_rows.append(
                        {
                            "instance": instance,
                            "condition": condition,
                            "arm": arm,
                            "seed": seed,
                            "operating_day": day_key,
                            "previous_day": (operating_day - timedelta(days=1)).isoformat(),
                            "timing_rule": strategy,
                            "action_index": action_index,
                            "vehicle_trip": action.vehicle_id,
                            "station_id": action.station_id,
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

                actual_charging = sum(actual_by_scope.values())
                forecast_charging = sum(forecast_by_scope.values())
                direct_fuel = float(source_row["E_cv_direct"])
                raw_rows.append(
                    {
                        "instance": instance,
                        "condition": condition,
                        "arm": arm,
                        "seed": seed,
                        "operating_day": day_key,
                        "previous_day": (operating_day - timedelta(days=1)).isoformat(),
                        "timing_rule": strategy,
                        "route_fingerprint": probe.route_hash(solution),
                        "service_fingerprint": probe.service_hash(solution),
                        "energy_fingerprint": probe.energy_hash(solution),
                        "route_unchanged": probe.route_hash(solution) == route_fingerprint,
                        "service_unchanged": probe.service_hash(solution) == service_fingerprint,
                        "energy_unchanged": probe.energy_hash(solution) == energy_fingerprint,
                        "hard_violation_count": len(violations),
                        "clock_violation_count": probe.clock_violations(solution, certificate),
                        "charging_kwh": sum(energy_by_scope.values()),
                        "eligible_pre_day_kwh": eligible_by_scope["pre_day_first_trip"],
                        "eligible_between_trip_kwh": eligible_by_scope["same_day_between_trip"],
                        "moved_pre_day_kwh": moved_by_scope["pre_day_first_trip"],
                        "moved_between_trip_kwh": moved_by_scope["same_day_between_trip"],
                        "actual_charging_emissions_kg": actual_charging,
                        "forecast_charging_emissions_kg": forecast_charging,
                        "actual_pre_day_emissions_kg": actual_by_scope["pre_day_first_trip"],
                        "actual_between_trip_emissions_kg": actual_by_scope["same_day_between_trip"],
                        "direct_fuel_emissions_kg": direct_fuel,
                        "actual_total_operational_emissions_kg": direct_fuel + actual_charging,
                    }
                )

    raw_index = {
        (
            row["instance"],
            row["condition"],
            int(row["seed"]),
            row["arm"],
            row["operating_day"],
            row["timing_rule"],
        ): row
        for row in raw_rows
    }
    pair_rows: list[dict[str, Any]] = []
    for source_row in formal_rows:
        instance = source_row["instance"]
        condition = source_row["condition"]
        arm = source_row["arm"]
        seed = int(source_row["seed"])
        for operating_day in OPERATING_DAYS:
            day_key = operating_day.isoformat()
            base_key = (instance, condition, seed, arm, day_key)
            immediate = raw_index[(*base_key, "immediate")]
            forecast = raw_index[(*base_key, "forecast_timed")]
            oracle = raw_index[(*base_key, "actual_oracle")]
            immediate_actual = float(immediate["actual_charging_emissions_kg"])
            forecast_actual = float(forecast["actual_charging_emissions_kg"])
            oracle_actual = float(oracle["actual_charging_emissions_kg"])
            realized = immediate_actual - forecast_actual
            potential = immediate_actual - oracle_actual
            pair_rows.append(
                {
                    "instance": instance,
                    "condition": condition,
                    "arm": arm,
                    "seed": seed,
                    "operating_day": day_key,
                    "charging_kwh": immediate["charging_kwh"],
                    "direct_fuel_emissions_kg": immediate["direct_fuel_emissions_kg"],
                    "immediate_actual_charging_kg": immediate_actual,
                    "forecast_actual_charging_kg": forecast_actual,
                    "oracle_actual_charging_kg": oracle_actual,
                    "realized_saving_kg": realized,
                    "realized_saving_pct": pct(realized, immediate_actual),
                    "total_operational_reduction_pct": pct(
                        realized,
                        float(immediate["actual_total_operational_emissions_kg"]),
                    ),
                    "oracle_potential_kg": potential,
                    "oracle_potential_pct": pct(potential, immediate_actual),
                    "forecast_capture_ratio": realized / potential if potential > TOLERANCE else 0.0,
                    "predicted_saving_kg": float(immediate["forecast_charging_emissions_kg"])
                    - float(forecast["forecast_charging_emissions_kg"]),
                    "pre_day_realized_saving_kg": float(immediate["actual_pre_day_emissions_kg"])
                    - float(forecast["actual_pre_day_emissions_kg"]),
                    "between_trip_realized_saving_kg": float(
                        immediate["actual_between_trip_emissions_kg"]
                    )
                    - float(forecast["actual_between_trip_emissions_kg"]),
                    "moved_pre_day_kwh": forecast["moved_pre_day_kwh"],
                    "moved_between_trip_kwh": forecast["moved_between_trip_kwh"],
                }
            )

    cell_rows = aggregate_pairs(
        pair_rows,
        keys=("instance", "condition", "arm", "operating_day"),
        expected_group_size=len(SEEDS),
    )
    network_rows = summarize_dimension(
        cell_rows, dimension="instance", expected_count=len(OPERATING_DAYS)
    )
    day_rows = summarize_dimension(cell_rows, dimension="operating_day", expected_count=len(instances))
    aggregate_rows = aggregate_summary(cell_rows, network_rows, day_rows)
    interaction_cells, interaction_networks, interaction_days, interaction_overall = interaction_tables(
        cell_rows
    )

    expected_raw = len(formal_rows) * len(OPERATING_DAYS) * len(STRATEGIES)
    expected_pairs = len(formal_rows) * len(OPERATING_DAYS)
    expected_cells = len(instances) * len(CONDITIONS) * len(ARMS) * len(OPERATING_DAYS)
    mechanical_checks = {
        "all_108_frozen_solutions_included": len(formal_rows) == 108,
        "complete_9072_row_strategy_matrix": len(raw_rows) == expected_raw == 9072,
        "complete_3024_seed_day_pairs": len(pair_rows) == expected_pairs == 3024,
        "complete_1008_seed_averaged_cells": len(cell_rows) == expected_cells == 1008,
        "all_nine_networks_included": len(instances) == 9,
        "all_28_eligible_days_included": len(OPERATING_DAYS) == 28,
        "routes_frozen": all(bool(row["route_unchanged"]) for row in raw_rows),
        "services_frozen": all(bool(row["service_unchanged"]) for row in raw_rows),
        "energy_frozen": all(bool(row["energy_unchanged"]) for row in raw_rows),
        "strict_legality": all(int(row["hard_violation_count"]) == 0 for row in raw_rows),
        "clock_legality": all(int(row["clock_violation_count"]) == 0 for row in raw_rows),
        "forecast_rule_improves_forecast_objective": all(
            float(row["predicted_saving_kg"]) >= -TOLERANCE for row in pair_rows
        ),
        "actual_oracle_is_actual_lower_bound": all(
            float(row["oracle_actual_charging_kg"])
            <= float(row["forecast_actual_charging_kg"]) + TOLERANCE
            and float(row["oracle_actual_charging_kg"])
            <= float(row["immediate_actual_charging_kg"]) + TOLERANCE
            for row in pair_rows
        ),
        "national_source_has_1393_verified_rows": len(source_carbon) == 1393,
        "network_summaries_complete": len(network_rows) == len(CONDITIONS) * len(ARMS) * len(instances),
        "day_summaries_complete": len(day_rows) == len(CONDITIONS) * len(ARMS) * len(OPERATING_DAYS),
        "interaction_cells_complete": len(interaction_cells)
        == len(instances) * len(CONDITIONS) * len(OPERATING_DAYS),
    }
    all_pass = all(mechanical_checks.values())

    outputs = {
        "raw_runs.csv": raw_rows,
        "action_runs.csv": action_rows,
        "paired_by_seed_day.csv": pair_rows,
        "cell_summary.csv": cell_rows,
        "network_summary.csv": network_rows,
        "day_summary.csv": day_rows,
        "aggregate_summary.csv": aggregate_rows,
        "interaction_summary.csv": interaction_cells,
        "interaction_network_summary.csv": interaction_networks,
        "interaction_day_summary.csv": interaction_days,
        "interaction_overall.csv": interaction_overall,
    }
    for name, rows in outputs.items():
        probe.write_csv(OUT / name, rows)

    metadata = {
        "schema": "setp.e4.forecast_timing_formal.v1",
        "execution_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "search_evaluations": 0,
        "input_experiment": str(FORMAL.relative_to(ROOT)),
        "input_formal_row_count": len(formal_rows),
        "instances": list(instances),
        "scenario_description": (
            "regional/intercity benchmark constructed from real UK city coordinates; "
            "not observed road trajectories, company orders, or urban last-mile data"
        ),
        "conditions": list(CONDITIONS),
        "arms": list(ARMS),
        "seeds": list(SEEDS),
        "operating_days": [day.isoformat() for day in OPERATING_DAYS],
        "calendar_contract": (
            "source timestamp is NESO interval end; slot 0 uses the row ending 00:30; "
            "pre-day first-trip charging uses the preceding calendar-day profile"
        ),
        "decision_rule": (
            "forecast intensity chooses implementable timing; actual intensity settles all reported emissions"
        ),
        "oracle_role": "diagnostic upper bound only",
        "statistical_units": {
            "seed": "averaged within network-condition-arm-day; never treated as independent reality",
            "operational_axis": "nine base networks",
            "environmental_axis": "28 complete operating days",
            "joint_cells": "descriptive repeated grid, not 252 independent samples",
        },
        "national_profile_reason": (
            "the benchmark has no unique DNO-region identity; a simple average of regional forecasts "
            "is not treated as a physical region"
        ),
        "source_api": probe.NESO_API_TEMPLATE.format(
            from_utc="2025-11-01T00:00Z", to_utc="2025-11-30T00:00Z"
        ),
        "source_methodology": probe.NESO_METHOD_URL,
        "source_csv_sha256": probe.sha256(CARBON_SOURCE),
        "source_api_full_range_reverification": {
            "api_rows": 1393,
            "local_rows": 1393,
            "field_mismatches": 0,
            "verified_on": "2026-07-13",
        },
        "formal_input_provenance_note": (
            "E3 metadata records an outdated source_commit, but its recorded source hashes match commit "
            "90654b3e; the sealed E3 directory is not rewritten here"
        ),
        "input_hashes": {
            str(path.relative_to(ROOT)): probe.sha256(path) for path in sorted(inputs)
        },
        "source_hashes": {
            str(path.relative_to(ROOT)): probe.sha256(path) for path in SOURCE_FILES
        },
        "result_direction_did_not_gate_execution": True,
    }
    decision = {
        "verdict": "PASS_E4_FORECAST_TIMING_FORMAL"
        if all_pass
        else "HALT_E4_FORECAST_TIMING_FORMAL",
        "all_mechanical_checks_pass": all_pass,
        "mechanical_checks": mechanical_checks,
        "result_direction_did_not_gate_execution": True,
        "formal_evidence_status": (
            "mechanically valid formal evidence; manuscript claim must follow both network and day summaries"
            if all_pass
            else "invalid for manuscript interpretation until the failed check is resolved"
        ),
        "claim_guard": (
            "report effect sizes on charging and total operational emissions; do not treat the 252 network-day "
            "grid cells or three search seeds as independent samples; collaboration interaction requires "
            "agreement of the network and day axes"
        ),
    }
    probe.write_json(OUT / "metadata.json", metadata)
    probe.write_json(OUT / "decision.json", decision)

    lines = [
        "# 固定配送方案下的充电时机正式复算",
        "",
        f"判决：`{decision['verdict']}`。本批搜索次数为 0；全部路线、客户服务关系、车辆和充电电量保持不变。",
        "",
        "下表的‘充电排放’只看电动车用电产生的间接排放；‘运营总排放’还把燃油车直接排放放回分母。三个搜索种子先在同一网络和同一天内平均。",
        "",
        "| 客户归属结构 | 经营方式 | 充电排放变化 | 运营总排放变化 | 改善网络 | 改善电网日 | 预测兑现理论空间 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "geographic": "按地理划分",
        "mixed": "空间交错",
        "ownership_fixed": "各车场按原归属经营",
        "reassignment_allowed": "允许跨车场重分配",
    }
    for row in aggregate_rows:
        lines.append(
            "| {condition} | {arm} | {charge:.3f}% | {total:.3f}% | {nw}/{n} | {dw}/{d} | {capture:.1f}% |".format(
                condition=labels[row["condition"]],
                arm=labels[row["arm"]],
                charge=float(row["pooled_charging_reduction_pct"]),
                total=float(row["pooled_total_operational_reduction_pct"]),
                nw=int(row["networks_improved"]),
                n=int(row["network_count"]),
                dw=int(row["days_improved"]),
                d=int(row["operating_day_count"]),
                capture=100.0 * float(row["pooled_forecast_capture_ratio"]),
            )
        )
    lines.extend(
        [
            "",
            "合作是否改变择时收益必须看同一网络、同一天内两种经营方式的差值。下面只给完整汇总，不用单个网络或单日决定方向。",
            "",
            "| 客户归属结构 | 按网络平均的差异 | 网络同向数 | 按电网日平均的差异 | 电网日同向数 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in interaction_overall:
        lines.append(
            "| {condition} | {network:.3f} 个百分点 | {np}/{nn} | {day:.3f} 个百分点 | {dp}/{dn} |".format(
                condition=labels[row["condition"]],
                network=float(row["network_mean_difference_percentage_points"]),
                np=int(row["network_positive"]),
                nn=int(row["network_count"]),
                day=float(row["day_mean_difference_percentage_points"]),
                dp=int(row["day_positive"]),
                dn=int(row["day_count"]),
            )
        )
    lines.extend(
        [
            "",
            "机制拆分已经分别落盘：前夜首趟充电与当天趟间充电不能混为一谈。正文解释应以完整数据为准，并同时报告充电排放和运营总排放，避免夸大一个局部百分比。",
            "",
            "算例是基于英国真实城市坐标构造的区域/城际配送场景，不是城市末端配送或真实道路运行记录。碳数据使用 NESO 全国半小时预测值安排充电，并用对应实际估计值结算。来源和边界见冻结合同。",
        ]
    )
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    artifact_files = [
        *SOURCE_FILES,
        *sorted(inputs),
        OUT / "metadata.json",
        OUT / "decision.json",
        OUT / "report.md",
        *(OUT / name for name in outputs),
    ]
    unique_files = list(dict.fromkeys(artifact_files))
    probe.write_json(
        OUT / "artifact_hashes.json",
        {
            "files": [
                {"path": str(path.relative_to(ROOT)), "sha256": probe.sha256(path)}
                for path in unique_files
            ]
        },
    )
    print(
        json.dumps(
            {
                "decision": decision,
                "aggregate": aggregate_rows,
                "interaction": interaction_overall,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
