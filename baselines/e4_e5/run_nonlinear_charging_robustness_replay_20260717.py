#!/usr/bin/env python3
"""Zero-search nonlinear-charging robustness replay on the sealed E4 matrix.

The replay never changes routes, customer assignments, vehicles, charging
locations, or charging quantities.  It reconstructs the battery level before
and after every depot charge from the sealed E3 multi-trip certificate, then
recomputes duration and half-hour energy under two pre-registered normalized
charging-curve shapes.  Unfavourable feasibility and emissions outcomes are
reported, not repaired or filtered.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
import csv
import hashlib
import json
import math
import statistics
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e4_e5 import e4_multiday_forecast_probe_20260713 as probe  # noqa: E402
from baselines.e4_e5.nonlinear_charging_replay_20260717 import (  # noqa: E402
    ChargingCurveError,
    PiecewiseChargingCurve,
    best_start_by_weight,
    half_hour_boundaries,
    scale_normalized_curve,
    slot_energy_kwh,
)
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.search.multitrip_schedule import MultiTripCertificate  # noqa: E402


E3 = probe.FORMAL
E4 = ROOT / "baselines/e4_e5/e4_forecast_timing_formal_20260713"
OUT = ROOT / "baselines/e4_e5/nonlinear_charging_robustness_replay_20260717"
CONTRACT = ROOT / "docs/handoff/nonlinear_charging_robustness_contract_20260717.md"
BATTERY_KWH = 280.0
INITIAL_BATTERY_KWH = 0.0
DEPOT_POWER_KW = 22.0
TOLERANCE = 1e-6
RULES = ("L->NL-F", "L->NL-E", "L->NL-C")
CURVE_SPECS = {
    "NL90_mild": {
        "role": "primary",
        "soc_breakpoints": (0.0, 0.90, 1.0),
        "relative_powers": (1.0, 0.50),
        "constant_power_end_soc": 0.90,
    },
    "NL80_stress": {
        "role": "secondary_stress",
        "soc_breakpoints": (0.0, 0.80, 0.90, 1.0),
        "relative_powers": (1.0, 0.50, 0.25),
        "constant_power_end_soc": 0.80,
    },
}
SOURCE_FILES = (
    Path(__file__).resolve(),
    ROOT / "baselines/e4_e5/nonlinear_charging_replay_20260717.py",
    CONTRACT,
)


@dataclass(frozen=True)
class ActionContext:
    vehicle_trip: str
    station_id: str
    charge_scope: str
    charge_day_offset: int
    start_energy_kwh: float
    end_energy_kwh: float
    earliest_start_second: float
    latest_finish_second: float

    @property
    def energy_kwh(self) -> float:
        return self.end_energy_kwh - self.start_energy_kwh


def mean(values: Iterable[float]) -> float:
    materialized = list(values)
    return statistics.fmean(materialized) if materialized else 0.0


def median(values: Iterable[float]) -> float:
    materialized = list(values)
    return statistics.median(materialized) if materialized else 0.0


def pct(numerator: float, denominator: float) -> float:
    return 100.0 * numerator / denominator if abs(denominator) > TOLERANCE else 0.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def curve(name: str) -> PiecewiseChargingCurve:
    spec = CURVE_SPECS[name]
    return scale_normalized_curve(
        capacity_kwh=BATTERY_KWH,
        soc_breakpoints=spec["soc_breakpoints"],
        relative_powers=spec["relative_powers"],
        reference_power_kw=DEPOT_POWER_KW,
    )


def action_contexts(certificate: MultiTripCertificate) -> dict[str, ActionContext]:
    """Reconstruct pre/post-charge SOC and immutable completion deadlines."""

    if abs(float(certificate.depot_charge_power_kw) - DEPOT_POWER_KW) > TOLERANCE:
        raise ValueError("sealed certificate does not use the frozen 22 kW depot power")
    by_vehicle: dict[str, list[Any]] = defaultdict(list)
    for trip in certificate.trips:
        by_vehicle[trip.physical_vehicle_id].append(trip)
    output: dict[str, ActionContext] = {}
    for trips in by_vehicle.values():
        ordered = sorted(trips, key=lambda item: item.trip_index)
        for index, trip in enumerate(ordered):
            if trip.vehicle_type != "ev":
                continue
            if index == 0:
                start = INITIAL_BATTERY_KWH
                end = float(trip.start_battery_kwh or 0.0)
                earliest = 0.0
                latest_finish = 86_400.0
                scope = "pre_day_first_trip"
                day_offset = -1
            else:
                previous = ordered[index - 1]
                start = float(previous.end_battery_kwh or 0.0)
                end = float(trip.start_battery_kwh or 0.0)
                earliest = float(previous.return_second)
                latest_finish = float(trip.departure_second)
                scope = "same_day_between_trip"
                day_offset = 0
            energy = end - start
            if energy <= TOLERANCE:
                continue
            if not (-TOLERANCE <= start < end <= BATTERY_KWH + TOLERANCE):
                raise ValueError(f"invalid reconstructed battery interval for {trip.route_id}")
            output[trip.route_id] = ActionContext(
                vehicle_trip=trip.route_id,
                station_id=trip.home_depot_id,
                charge_scope=scope,
                charge_day_offset=day_offset,
                start_energy_kwh=max(0.0, start),
                end_energy_kwh=min(BATTERY_KWH, end),
                earliest_start_second=earliest,
                latest_finish_second=latest_finish,
            )
    return output


def max_exact_concurrency(intervals: Sequence[tuple[float, float, str]]) -> int:
    """Maximum overlap of half-open charging intervals [start, end)."""

    events: list[tuple[float, int, str]] = []
    for start, end, vehicle in intervals:
        if end <= start:
            continue
        events.append((start, 1, vehicle))
        events.append((end, -1, vehicle))
    active: set[str] = set()
    maximum = 0
    for _time, delta, vehicle in sorted(events, key=lambda row: (row[0], row[1])):
        if delta < 0:
            active.discard(vehicle)
        else:
            active.add(vehicle)
            maximum = max(maximum, len(active))
    return maximum


def max_slot_concurrency(intervals: Sequence[tuple[float, float, str]]) -> int:
    """Maximum distinct vehicles occupying any frozen half-hour paper slot."""

    occupied: dict[int, set[str]] = defaultdict(set)
    for start, end, vehicle in intervals:
        for slot in range(48):
            left = slot * 1800.0
            right = left + 1800.0
            if min(end, right) > max(start, left) + 1e-12:
                occupied[slot].add(vehicle)
    return max((len(vehicles) for vehicles in occupied.values()), default=0)


def station_capacity(bundle: Any, station_id: str) -> int:
    node = next(node for node in bundle.instance.nodes if node.node_id == station_id)
    raw = node.station_chargers
    if raw is not None:
        return int(raw)
    customers = sum(node.node_type.lower() == "c" for node in bundle.instance.nodes)
    return customers if node.node_type.lower() == "d" else 1


def weights(profile: list[dict[str, Any]], field: str) -> tuple[float, ...]:
    return tuple(float(row[field]) for row in profile)


def evaluate_action(
    *,
    action_row: dict[str, str],
    context: ActionContext,
    charging_curve: PiecewiseChargingCurve,
    rule: str,
    profile: list[dict[str, Any]],
) -> dict[str, Any]:
    """Replay one frozen-energy action; infeasibility is an ordinary result."""

    if rule not in RULES:
        raise ValueError(f"unknown replay rule {rule}")
    duration = charging_curve.duration_seconds(
        context.start_energy_kwh, context.end_energy_kwh
    )
    latest_start = context.latest_finish_second - duration
    feasible = latest_start >= context.earliest_start_second - TOLERANCE
    reason = ""
    start: float | None
    if not feasible:
        start = None
        reason = "nonlinear_duration_exceeds_immutable_window"
    elif rule == "L->NL-F":
        start = float(action_row["charge_start_second"])
        if (
            start < context.earliest_start_second - TOLERANCE
            or start > latest_start + TOLERANCE
        ):
            feasible = False
            reason = "linear_forecast_start_is_nonlinear_infeasible"
    elif rule == "L->NL-E":
        start = context.earliest_start_second
    else:
        try:
            start, _objective, _energy = best_start_by_weight(
                charging_curve,
                start_energy_kwh=context.start_energy_kwh,
                end_energy_kwh=context.end_energy_kwh,
                earliest_start_seconds=context.earliest_start_second,
                latest_finish_seconds=context.latest_finish_second,
                slot_boundaries_seconds=half_hour_boundaries(),
                weights_per_kwh=weights(profile, "forecast_gco2_per_kwh"),
            )
        except ChargingCurveError:
            start = None
            feasible = False
            reason = "no_nonlinear_forecast_timing_candidate"

    energy_by_slot: tuple[float, ...] = ()
    actual_kg = math.nan
    forecast_kg = math.nan
    end_second = math.nan
    if feasible and start is not None:
        end_second = start + duration
        energy_by_slot = slot_energy_kwh(
            charging_curve,
            start_energy_kwh=context.start_energy_kwh,
            end_energy_kwh=context.end_energy_kwh,
            charging_start_seconds=start,
            slot_boundaries_seconds=half_hour_boundaries(),
        )
        actual_kg = sum(
            energy * float(row["actual_gco2_per_kwh"])
            for energy, row in zip(energy_by_slot, profile, strict=True)
        ) / 1000.0
        forecast_kg = sum(
            energy * float(row["forecast_gco2_per_kwh"])
            for energy, row in zip(energy_by_slot, profile, strict=True)
        ) / 1000.0
    linear_duration = context.energy_kwh / DEPOT_POWER_KW * 3600.0
    return {
        "replay_rule": rule,
        "feasible": feasible,
        "infeasibility_reason": reason,
        "start_energy_kwh": context.start_energy_kwh,
        "end_energy_kwh": context.end_energy_kwh,
        "start_soc": context.start_energy_kwh / BATTERY_KWH,
        "end_soc": context.end_energy_kwh / BATTERY_KWH,
        "energy_kwh": context.energy_kwh,
        "earliest_start_second": context.earliest_start_second,
        "latest_finish_second": context.latest_finish_second,
        "charge_start_second": start if start is not None else "",
        "charge_end_second": end_second if math.isfinite(end_second) else "",
        "linear_duration_second": linear_duration,
        "nonlinear_duration_second": duration,
        "duration_increase_second": duration - linear_duration,
        "actual_emissions_kg": actual_kg if math.isfinite(actual_kg) else "",
        "forecast_emissions_kg": forecast_kg if math.isfinite(forecast_kg) else "",
        "slot_energy_sum_kwh": sum(energy_by_slot) if energy_by_slot else "",
    }


def verify_recorded_e4_hashes() -> tuple[dict[str, str], dict[str, str]]:
    payload = json.loads((E4 / "artifact_hashes.json").read_text(encoding="utf-8"))
    recorded = {row["path"]: row["sha256"] for row in payload["files"]}
    required = (
        E4 / "metadata.json",
        E4 / "decision.json",
        E4 / "raw_runs.csv",
        E4 / "action_runs.csv",
        E3 / "raw_runs.csv",
    )
    checked: dict[str, str] = {}
    e3_manifest = json.loads((E3 / "artifact_hashes.json").read_text(encoding="utf-8"))
    for path in required:
        relative = str(path.relative_to(ROOT))
        expected = recorded.get(relative)
        if expected is None:
            if path == E3 / "raw_runs.csv":
                expected = e3_manifest.get("raw_runs.csv")
            else:
                raise RuntimeError(f"sealed E4 manifest omits {relative}")
        if expected is None:
            raise RuntimeError(f"sealed E3 manifest omits {path.name}")
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"sealed input drifted: {relative}")
        checked[relative] = actual
    decision = json.loads((E4 / "decision.json").read_text(encoding="utf-8"))
    if decision.get("verdict") != "PASS_E4_FORECAST_TIMING_FORMAL":
        raise RuntimeError("E4 input is not a passed formal experiment")
    return checked, recorded


def plan_key(row: dict[str, str]) -> tuple[str, str, str, int]:
    return row["instance"], row["condition"], row["arm"], int(row["seed"])


def day_plan_key(row: dict[str, str]) -> tuple[str, str, str, int, str]:
    return (*plan_key(row), row["operating_day"])


def summarize_cells(pair_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], ...]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in pair_rows:
        key = (
            row["curve"],
            row["instance"],
            row["condition"],
            row["arm"],
            row["operating_day"],
        )
        groups[key].append(row)
    cells: list[dict[str, Any]] = []
    for key, rows in sorted(groups.items()):
        if len(rows) != 3:
            raise RuntimeError(f"seed-averaging cell {key} has {len(rows)} rows")
        cells.append(
            {
                "curve": key[0],
                "instance": key[1],
                "condition": key[2],
                "arm": key[3],
                "operating_day": key[4],
                "seed_count": len(rows),
                "all_nonlinear_feasible": all(bool(row["nonlinear_feasible"]) for row in rows),
                "nl_saving_kg": mean(float(row["nl_saving_kg"]) for row in rows if row["nl_saving_kg"] != ""),
                "nl_saving_pct": mean(float(row["nl_saving_pct"]) for row in rows if row["nl_saving_pct"] != ""),
                "total_operational_reduction_pct": mean(
                    float(row["total_operational_reduction_pct"])
                    for row in rows
                    if row["total_operational_reduction_pct"] != ""
                ),
                "linear_saving_kg": mean(float(row["linear_saving_kg"]) for row in rows),
                "direction_reversal_count": sum(bool(row["direction_reversal"]) for row in rows),
                "fixed_start_infeasible_count": sum(not bool(row["fixed_start_feasible"]) for row in rows),
            }
        )

    def dimension_summary(dimension: str, expected: int) -> list[dict[str, Any]]:
        grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for row in cells:
            key = (row["curve"], row["condition"], row["arm"], row[dimension])
            grouped[key].append(row)
        output: list[dict[str, Any]] = []
        for key, rows in sorted(grouped.items()):
            if len(rows) != expected:
                raise RuntimeError(f"{dimension} summary {key} has {len(rows)} rows")
            values = [float(row["nl_saving_pct"]) for row in rows]
            output.append(
                {
                    "curve": key[0],
                    "condition": key[1],
                    "arm": key[2],
                    dimension: key[3],
                    "cell_count": len(rows),
                    "all_nonlinear_feasible": all(bool(row["all_nonlinear_feasible"]) for row in rows),
                    "mean_nl_saving_pct": mean(values),
                    "positive_cells": sum(value > TOLERANCE for value in values),
                    "negative_cells": sum(value < -TOLERANCE for value in values),
                    "direction_reversal_count": sum(int(row["direction_reversal_count"]) for row in rows),
                    "fixed_start_infeasible_count": sum(int(row["fixed_start_infeasible_count"]) for row in rows),
                }
            )
        return output

    networks = dimension_summary("instance", len(probe.OPERATING_DAYS))
    days = dimension_summary("operating_day", 9)
    aggregates: list[dict[str, Any]] = []
    for curve_name in CURVE_SPECS:
        for condition in ("geographic", "mixed"):
            for arm in probe.ARMS:
                network_rows = [
                    row
                    for row in networks
                    if row["curve"] == curve_name
                    and row["condition"] == condition
                    and row["arm"] == arm
                ]
                day_rows = [
                    row
                    for row in days
                    if row["curve"] == curve_name
                    and row["condition"] == condition
                    and row["arm"] == arm
                ]
                aggregates.append(
                    {
                        "curve": curve_name,
                        "curve_role": CURVE_SPECS[curve_name]["role"],
                        "condition": condition,
                        "arm": arm,
                        "network_count": len(network_rows),
                        "day_count": len(day_rows),
                        "all_nonlinear_feasible": all(
                            bool(row["all_nonlinear_feasible"]) for row in network_rows
                        ),
                        "network_mean_nl_saving_pct": mean(
                            float(row["mean_nl_saving_pct"]) for row in network_rows
                        ),
                        "network_positive": sum(
                            float(row["mean_nl_saving_pct"]) > TOLERANCE for row in network_rows
                        ),
                        "network_negative": sum(
                            float(row["mean_nl_saving_pct"]) < -TOLERANCE for row in network_rows
                        ),
                        "day_mean_nl_saving_pct": mean(
                            float(row["mean_nl_saving_pct"]) for row in day_rows
                        ),
                        "day_positive": sum(
                            float(row["mean_nl_saving_pct"]) > TOLERANCE for row in day_rows
                        ),
                        "day_negative": sum(
                            float(row["mean_nl_saving_pct"]) < -TOLERANCE for row in day_rows
                        ),
                        "direction_reversal_count": sum(
                            int(row["direction_reversal_count"]) for row in network_rows
                        ),
                        "fixed_start_infeasible_count": sum(
                            int(row["fixed_start_infeasible_count"]) for row in network_rows
                        ),
                    }
                )
    return cells, networks, days, aggregates


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    input_hashes, recorded_e4_hashes = verify_recorded_e4_hashes()
    e3_rows = read_csv(E3 / "raw_runs.csv")
    if len(e3_rows) != 108 or any(row["status"] != "PASS" for row in e3_rows):
        raise RuntimeError("sealed E3 matrix is incomplete or contains a failure")
    e3_index = {plan_key(row): row for row in e3_rows}
    if len(e3_index) != 108:
        raise RuntimeError("sealed E3 plan keys are not unique")

    action_rows = read_csv(E4 / "action_runs.csv")
    raw_rows = read_csv(E4 / "raw_runs.csv")
    if len(action_rows) != 132_300 or len(raw_rows) != 9_072:
        raise RuntimeError("sealed E4 row matrix is incomplete")
    raw_index = {
        (*day_plan_key(row), row["timing_rule"]): row
        for row in raw_rows
    }
    forecast_actions = [row for row in action_rows if row["timing_rule"] == "forecast_timed"]
    if len(forecast_actions) != 44_100:
        raise RuntimeError("sealed E4 forecast action matrix is incomplete")
    action_groups: dict[tuple[str, str, str, int, str], list[dict[str, str]]] = defaultdict(list)
    for row in forecast_actions:
        action_groups[day_plan_key(row)].append(row)

    source_carbon = probe.load_national_rows()
    profiles_by_day = {
        day.isoformat(): probe.profiles_for_operating_day(source_carbon, day)
        for day in probe.OPERATING_DAYS
    }
    bundles = {
        instance: load_search_bundle(E3 / "assets" / instance / "bundle")
        for instance in sorted({row["instance"] for row in e3_rows})
    }
    contexts_by_plan: dict[tuple[str, str, str, int], dict[str, ActionContext]] = {}
    certificate_paths: set[Path] = set()
    for key, row in e3_index.items():
        path = ROOT / row["certificate_path"]
        relative = str(path.relative_to(ROOT))
        expected = recorded_e4_hashes.get(relative)
        if expected is None:
            raise RuntimeError(f"sealed E4 manifest omits certificate {relative}")
        if sha256(path) != expected:
            raise RuntimeError(f"sealed certificate drifted: {relative}")
        certificate_paths.add(path)
        certificate = probe.load_certificate(path)
        contexts_by_plan[key] = action_contexts(certificate)

    # L->L closure: the independent constant-power integrator must reproduce
    # all sealed E4 action emissions before any nonlinear result is accepted.
    linear_curve = scale_normalized_curve(
        capacity_kwh=BATTERY_KWH,
        soc_breakpoints=(0.0, 1.0),
        relative_powers=(1.0,),
        reference_power_kw=DEPOT_POWER_KW,
    )
    closure_errors: list[dict[str, Any]] = []
    max_actual_error = 0.0
    max_forecast_error = 0.0
    max_energy_error = 0.0
    for row in action_rows:
        context = contexts_by_plan[plan_key(row)][row["vehicle_trip"]]
        if abs(context.energy_kwh - float(row["energy_kwh"])) > TOLERANCE:
            raise RuntimeError(f"E4 action energy disagrees with certificate for {row['vehicle_trip']}")
        profile = profiles_by_day[row["operating_day"]][context.charge_day_offset]
        energy = slot_energy_kwh(
            linear_curve,
            start_energy_kwh=context.start_energy_kwh,
            end_energy_kwh=context.end_energy_kwh,
            charging_start_seconds=float(row["charge_start_second"]),
            slot_boundaries_seconds=half_hour_boundaries(),
        )
        actual = sum(
            value * float(profile[index]["actual_gco2_per_kwh"])
            for index, value in enumerate(energy)
        ) / 1000.0
        forecast = sum(
            value * float(profile[index]["forecast_gco2_per_kwh"])
            for index, value in enumerate(energy)
        ) / 1000.0
        actual_error = abs(actual - float(row["actual_emissions_kg"]))
        forecast_error = abs(forecast - float(row["forecast_emissions_kg"]))
        energy_error = abs(sum(energy) - context.energy_kwh)
        max_actual_error = max(max_actual_error, actual_error)
        max_forecast_error = max(max_forecast_error, forecast_error)
        max_energy_error = max(max_energy_error, energy_error)
        if max(actual_error, forecast_error, energy_error) > TOLERANCE:
            closure_errors.append(
                {
                    "instance": row["instance"],
                    "condition": row["condition"],
                    "arm": row["arm"],
                    "seed": int(row["seed"]),
                    "operating_day": row["operating_day"],
                    "timing_rule": row["timing_rule"],
                    "vehicle_trip": row["vehicle_trip"],
                    "actual_error": actual_error,
                    "forecast_error": forecast_error,
                    "energy_error": energy_error,
                }
            )

    replay_actions: list[dict[str, Any]] = []
    plan_rows: list[dict[str, Any]] = []
    plan_index: dict[tuple[Any, ...], dict[str, Any]] = {}
    for day_key, base_actions in sorted(action_groups.items()):
        instance, condition, arm, seed, operating_day = day_key
        context_map = contexts_by_plan[(instance, condition, arm, seed)]
        profiles = profiles_by_day[operating_day]
        bundle = bundles[instance]
        for curve_name in CURVE_SPECS:
            charging_curve = curve(curve_name)
            threshold = float(CURVE_SPECS[curve_name]["constant_power_end_soc"])
            for rule in RULES:
                evaluated: list[dict[str, Any]] = []
                intervals: dict[tuple[str, int], list[tuple[float, float, str]]] = defaultdict(list)
                for action in sorted(base_actions, key=lambda row: row["vehicle_trip"]):
                    context = context_map[action["vehicle_trip"]]
                    profile = profiles[context.charge_day_offset]
                    replay = evaluate_action(
                        action_row=action,
                        context=context,
                        charging_curve=charging_curve,
                        rule=rule,
                        profile=profile,
                    )
                    enriched = {
                        "instance": instance,
                        "condition": condition,
                        "arm": arm,
                        "seed": seed,
                        "operating_day": operating_day,
                        "curve": curve_name,
                        "curve_role": CURVE_SPECS[curve_name]["role"],
                        "vehicle_trip": context.vehicle_trip,
                        "station_id": context.station_id,
                        "charge_scope": context.charge_scope,
                        "charge_day_offset": context.charge_day_offset,
                        "above_constant_power_end": replay["end_soc"] > threshold + TOLERANCE,
                        **replay,
                    }
                    evaluated.append(enriched)
                    replay_actions.append(enriched)
                    if bool(replay["feasible"]):
                        intervals[(context.station_id, context.charge_day_offset)].append(
                            (
                                float(replay["charge_start_second"]),
                                float(replay["charge_end_second"]),
                                context.vehicle_trip,
                            )
                        )

                exact_excess = 0
                slot_excess = 0
                max_exact = 0
                max_slot = 0
                min_capacity = math.inf
                for (station_id, _day_offset), station_intervals in intervals.items():
                    capacity = station_capacity(bundle, station_id)
                    exact = max_exact_concurrency(station_intervals)
                    slot = max_slot_concurrency(station_intervals)
                    max_exact = max(max_exact, exact)
                    max_slot = max(max_slot, slot)
                    min_capacity = min(min_capacity, capacity)
                    exact_excess += max(0, exact - capacity)
                    slot_excess += max(0, slot - capacity)
                feasible_actions = [row for row in evaluated if bool(row["feasible"])]
                plan = {
                    "instance": instance,
                    "condition": condition,
                    "arm": arm,
                    "seed": seed,
                    "operating_day": operating_day,
                    "curve": curve_name,
                    "curve_role": CURVE_SPECS[curve_name]["role"],
                    "replay_rule": rule,
                    "action_count": len(evaluated),
                    "infeasible_action_count": len(evaluated) - len(feasible_actions),
                    "plan_feasible": len(feasible_actions) == len(evaluated)
                    and exact_excess == 0
                    and slot_excess == 0,
                    "above_constant_power_end_count": sum(
                        bool(row["above_constant_power_end"]) for row in evaluated
                    ),
                    "above_constant_power_end_pct": pct(
                        sum(bool(row["above_constant_power_end"]) for row in evaluated),
                        len(evaluated),
                    ),
                    "charging_kwh": sum(float(row["energy_kwh"]) for row in evaluated),
                    "actual_charging_emissions_kg": (
                        sum(float(row["actual_emissions_kg"]) for row in feasible_actions)
                        if len(feasible_actions) == len(evaluated)
                        else ""
                    ),
                    "forecast_charging_emissions_kg": (
                        sum(float(row["forecast_emissions_kg"]) for row in feasible_actions)
                        if len(feasible_actions) == len(evaluated)
                        else ""
                    ),
                    "mean_duration_increase_minute": mean(
                        float(row["duration_increase_second"]) / 60.0 for row in evaluated
                    ),
                    "median_duration_increase_minute": median(
                        float(row["duration_increase_second"]) / 60.0 for row in evaluated
                    ),
                    "max_duration_increase_minute": max(
                        (float(row["duration_increase_second"]) / 60.0 for row in evaluated),
                        default=0.0,
                    ),
                    "max_exact_concurrency": max_exact,
                    "max_half_hour_slot_occupancy": max_slot,
                    "minimum_station_capacity": 0 if math.isinf(min_capacity) else int(min_capacity),
                    "exact_capacity_excess": exact_excess,
                    "half_hour_capacity_excess": slot_excess,
                }
                plan_rows.append(plan)
                plan_index[(*day_key, curve_name, rule)] = plan

    pair_rows: list[dict[str, Any]] = []
    for day_key in sorted(action_groups):
        instance, condition, arm, seed, operating_day = day_key
        linear_early = raw_index[(*day_key, "immediate")]
        linear_carbon = raw_index[(*day_key, "forecast_timed")]
        linear_saving = float(linear_early["actual_charging_emissions_kg"]) - float(
            linear_carbon["actual_charging_emissions_kg"]
        )
        direct_fuel = float(linear_early["direct_fuel_emissions_kg"])
        for curve_name in CURVE_SPECS:
            fixed = plan_index[(*day_key, curve_name, "L->NL-F")]
            early = plan_index[(*day_key, curve_name, "L->NL-E")]
            carbon = plan_index[(*day_key, curve_name, "L->NL-C")]
            nl_feasible = bool(early["plan_feasible"]) and bool(carbon["plan_feasible"])
            nl_saving: float | str = ""
            nl_saving_pct: float | str = ""
            total_reduction: float | str = ""
            if nl_feasible:
                early_actual = float(early["actual_charging_emissions_kg"])
                carbon_actual = float(carbon["actual_charging_emissions_kg"])
                nl_saving = early_actual - carbon_actual
                nl_saving_pct = pct(nl_saving, early_actual)
                total_reduction = pct(nl_saving, direct_fuel + early_actual)
            fixed_regret: float | str = ""
            if bool(fixed["plan_feasible"]) and bool(carbon["plan_feasible"]):
                fixed_regret = float(fixed["actual_charging_emissions_kg"]) - float(
                    carbon["actual_charging_emissions_kg"]
                )
            direction_reversal = False
            if nl_saving != "" and abs(linear_saving) > TOLERANCE and abs(float(nl_saving)) > TOLERANCE:
                direction_reversal = (linear_saving > 0.0) != (float(nl_saving) > 0.0)
            pair_rows.append(
                {
                    "instance": instance,
                    "condition": condition,
                    "arm": arm,
                    "seed": seed,
                    "operating_day": operating_day,
                    "curve": curve_name,
                    "curve_role": CURVE_SPECS[curve_name]["role"],
                    "nonlinear_feasible": nl_feasible,
                    "fixed_start_feasible": bool(fixed["plan_feasible"]),
                    "linear_early_actual_kg": float(linear_early["actual_charging_emissions_kg"]),
                    "linear_carbon_actual_kg": float(linear_carbon["actual_charging_emissions_kg"]),
                    "linear_saving_kg": linear_saving,
                    "nl_early_actual_kg": early["actual_charging_emissions_kg"],
                    "nl_carbon_actual_kg": carbon["actual_charging_emissions_kg"],
                    "nl_saving_kg": nl_saving,
                    "nl_saving_pct": nl_saving_pct,
                    "total_operational_reduction_pct": total_reduction,
                    "fixed_start_regret_kg": fixed_regret,
                    "direction_reversal": direction_reversal,
                    "infeasible_nl_early_actions": int(early["infeasible_action_count"]),
                    "infeasible_nl_carbon_actions": int(carbon["infeasible_action_count"]),
                    "infeasible_fixed_start_actions": int(fixed["infeasible_action_count"]),
                    "exact_capacity_excess": max(
                        int(early["exact_capacity_excess"]), int(carbon["exact_capacity_excess"])
                    ),
                    "half_hour_capacity_excess": max(
                        int(early["half_hour_capacity_excess"]),
                        int(carbon["half_hour_capacity_excess"]),
                    ),
                }
            )

    cells, networks, days, aggregates = summarize_cells(pair_rows)
    expected_action_rows = len(forecast_actions) * len(CURVE_SPECS) * len(RULES)
    expected_plan_rows = len(action_groups) * len(CURVE_SPECS) * len(RULES)
    expected_pair_rows = len(action_groups) * len(CURVE_SPECS)
    mechanical_checks = {
        "sealed_e4_passed": True,
        "complete_108_solution_matrix": len(e3_rows) == 108,
        "complete_28_day_matrix": len(probe.OPERATING_DAYS) == 28,
        "complete_44100_base_action_matrix": len(forecast_actions) == 44_100,
        "linear_replay_closes_all_132300_actions": not closure_errors,
        "linear_actual_emissions_tolerance": max_actual_error <= TOLERANCE,
        "linear_forecast_emissions_tolerance": max_forecast_error <= TOLERANCE,
        "linear_energy_tolerance": max_energy_error <= TOLERANCE,
        "both_preregistered_curves_reported": set(CURVE_SPECS)
        == {row["curve"] for row in aggregates},
        "complete_action_replay_matrix": len(replay_actions) == expected_action_rows,
        "complete_plan_replay_matrix": len(plan_rows) == expected_plan_rows,
        "complete_paired_matrix": len(pair_rows) == expected_pair_rows,
        "zero_search_evaluations": True,
        "result_direction_did_not_gate_execution": True,
    }
    mechanical_pass = all(mechanical_checks.values())
    primary_pairs = [row for row in pair_rows if row["curve"] == "NL90_mild"]
    stress_pairs = [row for row in pair_rows if row["curve"] == "NL80_stress"]
    primary_infeasible = sum(not bool(row["nonlinear_feasible"]) for row in primary_pairs)
    primary_reversals = sum(bool(row["direction_reversal"]) for row in primary_pairs)
    stress_infeasible = sum(not bool(row["nonlinear_feasible"]) for row in stress_pairs)
    stress_reversals = sum(bool(row["direction_reversal"]) for row in stress_pairs)
    core_upgrade_required = primary_infeasible > 0 or primary_reversals > 0

    outputs = {
        "raw_runs.csv": plan_rows,
        "action_replay.csv": replay_actions,
        "plan_replay.csv": plan_rows,
        "paired_by_seed_day.csv": pair_rows,
        "cell_summary.csv": cells,
        "network_summary.csv": networks,
        "day_summary.csv": days,
        "aggregate_summary.csv": aggregates,
        "linear_closure_failures.csv": closure_errors,
    }
    for name, rows in outputs.items():
        probe.write_csv(OUT / name, rows)
    closure = {
        "checked_action_count": len(action_rows),
        "failure_count": len(closure_errors),
        "max_actual_emissions_error_kg": max_actual_error,
        "max_forecast_emissions_error_kg": max_forecast_error,
        "max_energy_error_kwh": max_energy_error,
        "verdict": "PASS_L_TO_L_INDEPENDENT_REPLAY" if not closure_errors else "HALT_L_TO_L_REPLAY",
    }
    probe.write_json(OUT / "linear_closure.json", closure)
    metadata = {
        "schema": "setp.e4.nonlinear_charging_robustness.v1",
        "execution_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "search_evaluations": 0,
        "input_e3": str(E3.relative_to(ROOT)),
        "input_e4": str(E4.relative_to(ROOT)),
        "battery_kwh": BATTERY_KWH,
        "initial_battery_kwh": INITIAL_BATTERY_KWH,
        "depot_charge_power_kw": DEPOT_POWER_KW,
        "curves": CURVE_SPECS,
        "curve_interpretation": (
            "normalized shape-stress curves, not engineering calibration of a specific vehicle"
        ),
        "replay_rules": list(RULES),
        "statistical_units": {
            "seed": "averaged within network-condition-arm-day",
            "network_axis": "nine base networks",
            "environmental_axis": "28 complete operating days",
        },
        "station_capacity_guard": (
            "D0/D1 capacities use the generated customer-count route upper bound; zero conflicts do not "
            "establish finite shared-charger effectiveness"
        ),
        "input_hashes": {
            **input_hashes,
            **{str(path.relative_to(ROOT)): sha256(path) for path in sorted(certificate_paths)},
            str(probe.CARBON_SOURCE.relative_to(ROOT)): sha256(probe.CARBON_SOURCE),
        },
        "source_hashes": {
            str(path.relative_to(ROOT)): sha256(path) for path in SOURCE_FILES
        },
        "result_direction_did_not_gate_execution": True,
    }
    decision = {
        "verdict": (
            "HALT_NL_CHARGING_ROBUSTNESS_REPLAY"
            if not mechanical_pass
            else (
                "PASS_NL_CHARGING_REPLAY_CORE_UPGRADE_REQUIRED"
                if core_upgrade_required
                else "PASS_NL_CHARGING_ROBUSTNESS_REPLAY_COMPLETE"
            )
        ),
        "mechanical_checks": mechanical_checks,
        "mechanical_pass": mechanical_pass,
        "core_model_upgrade_required": core_upgrade_required,
        "primary_curve": "NL90_mild",
        "primary_infeasible_seed_day_plans": primary_infeasible,
        "primary_infeasible_scope": "L->NL-E or L->NL-C seed-day plans; excludes L->NL-F",
        "primary_direction_reversals": primary_reversals,
        "stress_curve": "NL80_stress",
        "stress_infeasible_seed_day_plans": stress_infeasible,
        "stress_infeasible_scope": "L->NL-E or L->NL-C seed-day plans; excludes L->NL-F",
        "stress_direction_reversals": stress_reversals,
        "claim_guard": (
            "An unfavourable or infeasible replay is a scientific result.  Do not repair routes, select one "
            "curve, or suppress reversals.  Zero charger conflicts are non-informative because depot "
            "capacity is a generated upper bound."
        ),
        "result_direction_did_not_gate_execution": True,
    }
    probe.write_json(OUT / "metadata.json", metadata)
    probe.write_json(OUT / "decision.json", decision)

    lines = [
        "# 非线性充电固定方案稳健性复算",
        "",
        f"判决：`{decision['verdict']}`。搜索次数为0，路线、客户归属、车辆、充电地点和充电量均未改变。",
        "",
        f"独立L->L复算覆盖{len(action_rows)}次动作，最大实际排放误差为{max_actual_error:.3e} kg，最大电量误差为{max_energy_error:.3e} kWh。",
        "",
        "| 曲线 | 客户归属 | 经营方式 | 网络轴平均充电减排 | 改善网络 | 改善电网日 | 固定原时刻不可行 | 方向反转 |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in aggregates:
        lines.append(
            f"| {row['curve']} | {row['condition']} | {row['arm']} | "
            f"{float(row['network_mean_nl_saving_pct']):.3f}% | "
            f"{row['network_positive']}/{row['network_count']} | "
            f"{row['day_positive']}/{row['day_count']} | "
            f"{row['fixed_start_infeasible_count']} | {row['direction_reversal_count']} |"
        )
    lines.extend(
        [
            "",
            f"主曲线需升级核心模型：`{core_upgrade_required}`；主曲线不可行seed-day方案{primary_infeasible}个，方向反转{primary_reversals}个。",
            "",
            f"强压力曲线不可行seed-day方案{stress_infeasible}个，方向反转{stress_reversals}个。两条曲线必须同时保留。",
            "",
            "车场桩容量使用客户数上界，因而零冲突只能说明容量不绑定，不能证明有限共享桩机制有效。",
        ]
    )
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    output_paths = [
        *(OUT / name for name in outputs),
        OUT / "linear_closure.json",
        OUT / "metadata.json",
        OUT / "decision.json",
        OUT / "report.md",
    ]
    artifact_hashes = {
        str(path.relative_to(ROOT)): sha256(path) for path in sorted(output_paths)
    }
    probe.write_json(OUT / "artifact_hashes.json", artifact_hashes)
    print(decision["verdict"])
    return 0 if mechanical_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
