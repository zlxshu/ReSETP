#!/usr/bin/env python3
"""E7 v3: exhaustive wiring gate, inherited four-arm execution, and closeout."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict
from datetime import date, timedelta
import hashlib
import importlib.util
import inspect
import json
import math
import multiprocessing
import os
from pathlib import Path
import pickle
import statistics
import sys
import time
from types import ModuleType
from types import MappingProxyType
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for candidate in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from setp_solver.check import check_solution
from setp_solver.china81 import _load_time_profile
from setp_solver.search import dynamic_multitrip_schedule as dynamic_schedule
from setp_solver.search.bundle import SearchBundle
from setp_solver.search.certificate_execution import (
    COMPLETED,
    IN_PROGRESS,
    NOT_STARTED,
    build_certificate_execution_ledger,
)
from setp_solver.search.dynamic import DynamicEvent, RollingParameters
from setp_solver.search.multitrip_schedule import (
    prepare_multitrip_solution,
    reschedule_between_trip_charging,
    validate_multitrip_certificate,
)
from setp_solver.algorithms.resetp_alns.runtime.budgeted_scoring import (
    score_reference_solution,
)


TASK_ID = "E7-DYNAMIC-V3-20260731"
V2_RUNNER = (
    ROOT / "baselines/china_e3_e7/e7_dynamic_v2_20260731/run_e7_dynamic.py"
)
LEGACY_RUNNER = (
    ROOT / "baselines/china_e3_e7/e7_dynamic_20260731/run_e7_dynamic.py"
)
E4_RUNNER = (
    ROOT / "baselines/china_e3_e7/e4_carbon_timing_20260729"
    / "run_e4_carbon_timing.py"
)
TIMING_AUTHORITY = (
    ROOT / "data/ChinaInstances/china81_runtime_parameter_authority_v3_20260723"
)
APPROVED_WRAPPER_AUTHORITY = (
    ROOT / "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
)
CALENDAR_NAME = "tariff_carbon_hourly_calendar.csv"
OPERATING_DAY = date(2025, 2, 12)
PREVIOUS_DAY = OPERATING_DAY - timedelta(days=1)
TOL = 1.0e-6
FORMAL_DEFAULT_WORKERS = 6
FORMAL_MAX_WORKERS = 8
EXPECTED_CHINA81_SOURCE_KEYS = {
    "catalog",
    "facilities",
    "finite_fleet_authority",
    "nodes",
    "orders",
    "road_matrices",
    "tariff_carbon_calendar",
    "vehicle_parameter_lock",
}
REQUIRED_SOURCE_KEYS = {
    "bundle",
    "case",
    "certificate",
    "certificate_path",
    "instance_source_paths",
    "instance_source_sha256",
    "prices",
    "solution",
    "solution_path",
    "timing_profile_authority",
    "timing_profile_sha256",
}
REQUIRED_PROFILE_FIELDS = {
    "actual_gco2_per_kwh",
    "carbon_source_column",
    "city",
    "date",
    "depot_energy_cny_per_kwh",
    "forecast_gco2_per_kwh",
    "hourly_calendar_row",
    "horizon_second_start",
    "price_area_id",
    "public_energy_cny_per_kwh",
    "public_service_fee_cny_per_kwh",
    "public_total_cny_per_kwh",
    "region",
    "tariff_period",
    "time_index",
}
SHARED_E4_TIMING_FIELDS = (
    "city",
    "region",
    "date",
    "hourly_calendar_row",
    "minute_of_day",
    "tariff_period",
    "depot_energy_cny_per_kwh",
    "public_energy_cny_per_kwh",
    "public_service_fee_cny_per_kwh",
    "public_total_cny_per_kwh",
    "carbon_factor_kgco2e_per_kwh",
    "tariff_row_class",
    "service_fee_class",
    "carbon_source_column",
    "price_area_id",
    "diesel_zone",
    "diesel_price_candidate_cny_per_l",
    "diesel_candidate_status",
    "diesel_source_strength",
    "diesel_source_file",
    "diesel_source_sha256",
)
WIRING_FIXES = (
    {
        "id": "W1_CHINA81_MULTI_FILE_SOURCE_CONTRACT",
        "found_in": "round_1",
        "symptom": "instance_json was requested from an eight-source China81 bundle",
        "repair": "resolve and hash all eight named China81 source surfaces",
    },
    {
        "id": "W2_EXPLICIT_CHINA81_PRICES",
        "found_in": "round_2",
        "symptom": "initial timing used DEFAULT_PRICES instead of the China81 bundle prices",
        "repair": "pass sources['prices'] to both initial timing variants",
    },
    {
        "id": "W3_PREVIOUS_DAY_CARBON_PROFILE",
        "found_in": "round_2",
        "symptom": "charge_day_offset=-1 had no frozen calendar profile",
        "repair": "load 2025-02-11 and 2025-02-12 from the E4 timing authority",
    },
    {
        "id": "W4_RESULT_FIELD_NAME_ALIGNMENT",
        "found_in": "v3_static_contract_audit",
        "symptom": "v2 startup validation requested actual_search_evaluations",
        "repair": "use the runner result field actual_evaluations consistently",
    },
    {
        "id": "W5_WHOLE_TRIP_RELEASE_BATTERY_STATE",
        "found_in": "v3_first_state_cut",
        "symptom": (
            "an in-progress route deducted its full drive energy while omitting "
            "a later committed in-route charge"
        ),
        "repair": (
            "release an immutable in-progress trip at its certified return "
            "battery and lock every charging action carried by that trip"
        ),
    },
    {
        "id": "W6_IN_PROGRESS_ROUTE_CHARGING_WITNESS",
        "found_in": "v3_first_state_cut_witness",
        "symptom": (
            "the evidence layer rejected a future public charge carried by an "
            "already-departed immutable trip"
        ),
        "repair": (
            "record the action as whole_trip_in_progress_committed and freeze "
            "its observed start in the charging-window ledger"
        ),
    },
    {
        "id": "W7_ALNS_CURRENT_OBJECTIVE_BINDING",
        "found_in": "v3_convergence_probe_shadow_pass",
        "symptom": (
            "the E7 search adapter called apply_winner_action without the "
            "current complete-solution objective"
        ),
        "repair": (
            "bind a visible reference-channel objective to every current "
            "search structure and cache scored successor objectives"
        ),
    },
    {
        "id": "W8_SPAWN_WORKER_MODULE_IDENTITY",
        "found_in": "v3_formal_50c_pool_start",
        "symptom": (
            "macOS spawn could not pickle the dynamically loaded legacy worker "
            "because its module identity was absent from sys.modules"
        ),
        "repair": (
            "register the inherited runner under its declared module name and "
            "regression-check worker serialization before formal execution"
        ),
    },
    {
        "id": "W9_LEGAL_INFEASIBLE_TASK_CLASSIFICATION",
        "found_in": "v3_formal_50c_static_first_stage",
        "symptom": (
            "a frozen-fleet event-stage infeasibility was raised as a technical "
            "worker failure"
        ),
        "repair": (
            "serialize the unit as LEGAL_INFEASIBLE with null objective, exact "
            "candidate consumption, failure stage, and retained denominator"
        ),
    },
    {
        "id": "W10_TRACE_MODE_GUARD",
        "found_in": "v3_formal_50c_search_first_stage",
        "symptom": (
            "the convergence-trace wrapper required a trace row during a "
            "formal run whose trace_mode was false"
        ),
        "repair": (
            "apply trace-accounting assertions only when convergence tracing "
            "is explicitly enabled"
        ),
    },
    {
        "id": "W11_NO_EXECUTABLE_CONTINUATION_CLASSIFICATION",
        "found_in": "v3_formal_50c_rolling_first_stage",
        "symptom": (
            "the rolling gate raised its dedicated NoExecutableContinuation "
            "terminal after all evaluated candidates were non-executable"
        ),
        "repair": (
            "classify the dedicated terminal as LEGAL_INFEASIBLE while "
            "retaining its exact evaluation count and rejection summary"
        ),
    },
)
ARM_CONFIGS = {
    "STATIC_FIXED_RECOURSE": {
        "route_policy": "fixed_route_event_recourse",
        "cooperation": "inherited_only",
        "participation": "reported",
        "charging": "aware",
        "route_search": False,
    },
    "FULL_ROLLING": {
        "route_policy": "rolling",
        "cooperation": "open",
        "participation": "same_state_floor",
        "charging": "aware",
        "route_search": True,
    },
    "NO_COOPERATION": {
        "route_policy": "rolling",
        "cooperation": "owner_locked",
        "participation": "same_state_floor",
        "charging": "aware",
        "route_search": True,
    },
    "CARBON_BLIND": {
        "route_policy": "rolling",
        "cooperation": "open",
        "participation": "same_state_floor",
        "charging": "earliest_feasible",
        "route_search": True,
    },
}


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V2 = load_module("_e7_v2_inherited_runner", V2_RUNNER)
LEGACY = V2.LEGACY
PROBE = LEGACY.probe
sys.modules[LEGACY.__name__] = LEGACY
LEGACY.HERE = HERE
LEGACY.TASK_ID = TASK_ID
LEGACY.SOURCE_FILES = tuple(
    dict.fromkeys(
        (
            *LEGACY.SOURCE_FILES,
            Path(__file__).resolve(),
            V2_RUNNER.resolve(),
            LEGACY_RUNNER.resolve(),
            E4_RUNNER.resolve(),
        )
    )
)
ORIGINAL_VERIFY_PROTECTED = LEGACY.verify_protected
ORIGINAL_TRACED_SEARCH_STAGE = LEGACY.traced_search_stage
ORIGINAL_CONTROLLED_STAGE_DISPATCH = LEGACY.controlled_stage_dispatch
ORIGINAL_CHARGING_WINDOW_WITNESS = PROBE._charging_window_witness
ORIGINAL_APPLY_WINNER_ACTION = PROBE.base.apply_winner_action
ORIGINAL_RUN_TASK = LEGACY.run_task
WINNER_OBJECTIVE_CACHE: dict[tuple[int, str], float] = {}
_ACTIVE_EVENT_STAGE = 0
_COMPLETED_EVENT_STAGE = 0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve()))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def source_sha256(path: Path) -> str:
    return V2._source_sha256(path)


def validate_e4_calendar_contract() -> dict[str, Any]:
    timing_path = TIMING_AUTHORITY / CALENDAR_NAME
    wrapper_path = APPROVED_WRAPPER_AUTHORITY / CALENDAR_NAME
    timing_rows = read_csv(timing_path)
    wrapper_rows = read_csv(wrapper_path)
    timing_projection = [
        {field: row[field] for field in SHARED_E4_TIMING_FIELDS}
        for row in timing_rows
    ]
    wrapper_projection = [
        {field: row[field] for field in SHARED_E4_TIMING_FIELDS}
        for row in wrapper_rows
    ]
    if timing_projection != wrapper_projection:
        raise RuntimeError("HALT_E4_V3_V4_TIMING_PROJECTION_DRIFT")
    counts = Counter(
        (row["city"].strip().lower(), row["date"]) for row in timing_rows
    )
    dates = sorted({row["date"] for row in timing_rows})
    if set(counts.values()) != {48}:
        raise RuntimeError("HALT_CALENDAR_NOT_48_SLOTS_PER_CITY_DAY")
    for required_day in (PREVIOUS_DAY.isoformat(), OPERATING_DAY.isoformat()):
        if required_day not in dates:
            raise RuntimeError(f"HALT_CALENDAR_DAY_MISSING:{required_day}")
    return {
        "status": "PASS_E4_ALIGNED_DUAL_DAY_CALENDAR",
        "timing_authority": relative(timing_path),
        "timing_authority_sha256": sha256(timing_path),
        "approved_wrapper": relative(wrapper_path),
        "approved_wrapper_sha256": sha256(wrapper_path),
        "shared_timing_fields": list(SHARED_E4_TIMING_FIELDS),
        "shared_timing_projection_sha256": canonical_sha256(timing_projection),
        "shared_timing_rows_equal": True,
        "operating_day": OPERATING_DAY.isoformat(),
        "previous_day_for_offset_minus_one": PREVIOUS_DAY.isoformat(),
        "offset_rule": {
            "-1": PREVIOUS_DAY.isoformat(),
            "0": OPERATING_DAY.isoformat(),
        },
    }


def profiles_for_bundle(bundle: Any) -> dict[int, list[dict[str, Any]]]:
    cities = {
        str(node.city).strip().lower()
        for node in bundle.instance.nodes
        if node.city is not None and str(node.city).strip()
    }
    calendar = TIMING_AUTHORITY / CALENDAR_NAME
    profiles = {
        -1: _load_time_profile(
            calendar,
            cities=cities,
            date=PREVIOUS_DAY.isoformat(),
            require_explicit_mapping=False,
        ),
        0: _load_time_profile(
            calendar,
            cities=cities,
            date=OPERATING_DAY.isoformat(),
            require_explicit_mapping=False,
        ),
    }
    for offset, rows in profiles.items():
        if not rows or len(rows) != 48 * len(cities):
            raise RuntimeError(
                f"HALT_PROFILE_GRID:{offset}:{len(rows)}:{len(cities)}"
            )
        missing = REQUIRED_PROFILE_FIELDS - set(rows[0])
        if missing:
            raise RuntimeError(
                f"HALT_PROFILE_FIELDS:{offset}:{sorted(missing)}"
            )
    return profiles


def current_sources(
    condition: str = "baseline",
    network: str = "50c",
) -> tuple[dict[str, Any], dict[int, list[dict[str, Any]]]]:
    del condition
    scale = str(network)
    if scale not in LEGACY.SCALES:
        raise ValueError(f"unknown scale {scale}")
    bundle = LEGACY.e3_module().load_bundle(LEGACY.INSTANCE_BY_SCALE[scale])
    if bundle.date != OPERATING_DAY.isoformat():
        raise RuntimeError(
            f"HALT_OPERATING_DAY_DRIFT:{bundle.date}!={OPERATING_DAY.isoformat()}"
        )
    solution = LEGACY.solution_from_plan(scale, LEGACY._CURRENT_ALGORITHM_SEED)
    prepared, certificate = prepare_multitrip_solution(
        solution,
        bundle.instance,
        bundle.prices,
    )
    validate_multitrip_certificate(
        certificate,
        list(prepared.routes),
        bundle.prices,
        instance=bundle.instance,
    )
    source_paths = V2._resolved_china81_sources(bundle)
    if set(source_paths) != EXPECTED_CHINA81_SOURCE_KEYS:
        raise RuntimeError("HALT_CHINA81_SOURCE_KEY_SET")
    profiles = profiles_for_bundle(bundle)
    LEGACY._BASE_CHINA_BUNDLE = bundle
    LEGACY._BASE_INSTANCE = bundle.instance
    LEGACY._ALIAS_BY_NODE_ID = {
        node.node_id: node.node_id for node in bundle.instance.nodes
    }
    solution_path = LEGACY.nominal_plan_path(
        scale, LEGACY._CURRENT_ALGORITHM_SEED
    )
    search_bundle = SearchBundle(
        bundle_dir=solution_path.parent,
        instance=bundle.instance,
        carbon_profile=list(profiles[0]),
    )
    sources = {
        "case": (
            f"{LEGACY.INSTANCE_BY_SCALE[scale]}"
            f"__seed{LEGACY._CURRENT_ALGORITHM_SEED}"
        ),
        "bundle": search_bundle,
        "prices": bundle.prices,
        "solution": prepared,
        "certificate": certificate,
        "solution_path": solution_path,
        "certificate_path": solution_path,
        "instance_source_paths": source_paths,
        "instance_source_sha256": {
            key: source_sha256(path)
            for key, path in sorted(source_paths.items())
        },
        "timing_profile_authority": TIMING_AUTHORITY / CALENDAR_NAME,
        "timing_profile_sha256": sha256(TIMING_AUTHORITY / CALENDAR_NAME),
    }
    if set(sources) != REQUIRED_SOURCE_KEYS | {"case"}:
        raise RuntimeError(
            "HALT_CURRENT_SOURCE_FIELDS:"
            f"{sorted(sources)}"
        )
    return sources, profiles


def corrected_initial_plan(
    arm: str,
    sources: Mapping[str, Any],
    profiles: Mapping[int, list[dict[str, Any]]],
) -> tuple[Any, Any, dict[str, Any]]:
    if arm not in {*LEGACY.ARMS, "full"}:
        raise ValueError(f"unknown arm {arm}")
    original_solution = sources["solution"]
    original_certificate = sources["certificate"]
    immediate = reschedule_between_trip_charging(
        original_solution,
        original_certificate,
        sources["bundle"].instance,
        profiles[0],
        strategy="naive",
        prices=sources["prices"],
        carbon_profiles_by_day_offset=profiles,
        intensity_field="forecast_gco2_per_kwh",
    )
    aware = reschedule_between_trip_charging(
        original_solution,
        original_certificate,
        sources["bundle"].instance,
        profiles[0],
        strategy="aware",
        prices=sources["prices"],
        carbon_profiles_by_day_offset=profiles,
        intensity_field="forecast_gco2_per_kwh",
    )
    timing_comparison = PROBE._timing_comparison(
        immediate,
        aware,
        sources["bundle"].instance,
        profiles,
    )
    synced_solution, synced_certificate = prepare_multitrip_solution(
        aware,
        sources["bundle"].instance,
        sources["prices"],
    )
    validate_multitrip_certificate(
        synced_certificate,
        list(synced_solution.routes),
        sources["prices"],
        instance=sources["bundle"].instance,
    )
    if PROBE.route_hash(original_solution) != PROBE.route_hash(synced_solution):
        raise RuntimeError("HALT_INITIAL_TIMING_ROUTE_DRIFT")
    if PROBE.energy_hash(original_solution) != PROBE.energy_hash(synced_solution):
        raise RuntimeError("HALT_INITIAL_TIMING_ENERGY_DRIFT")
    old_starts = {
        action.vehicle_id: float(action.charge_start_second)
        for action in original_solution.charging_actions
    }
    moved = sum(
        abs(float(action.charge_start_second) - old_starts[action.vehicle_id])
        > TOL
        for action in synced_solution.charging_actions
    )
    return synced_solution, synced_certificate, {
        "strategy": "aware",
        "moved_action_count": moved,
        "route_sha256": PROBE.route_hash(synced_solution),
        "energy_sha256": PROBE.energy_hash(synced_solution),
        "prices_sha256": canonical_sha256(asdict(sources["prices"])),
        "profile_offsets": sorted(profiles),
        **timing_comparison,
    }


LEGACY.current_sources = current_sources
PROBE._initial_plan = corrected_initial_plan


def _whole_trip_cut(
    solution: Any,
    certificate: Any,
    instance: Any,
    prices: Any,
    *,
    trigger_second: float,
    inherited_asset_states: Mapping[str, Any] | None = None,
    previous_stage_start_second: float | None = None,
    inherited_locked_charging_actions: Sequence[Any] = (),
) -> Any:
    """Cut at whole-trip release boundaries with the certified terminal battery.

    A route that has departed is immutable through its certified return. Its
    terminal battery already includes every public charge on that trip, even
    when that action starts after the current trigger.
    """

    trigger = float(trigger_second)
    trip_by_id = {trip.route_id: trip for trip in certificate.trips}
    if len(trip_by_id) != len(certificate.trips):
        raise RuntimeError("HALT_DYNAMIC_CUT_DUPLICATE_ROUTE_ID")
    if inherited_asset_states is None:
        ledger = build_certificate_execution_ledger(
            solution,
            certificate,
            instance,
            prices,
        )
        base_states = {
            asset_id: dynamic_schedule.DynamicAssetState(
                physical_vehicle_id=asset_id,
                vehicle_type=asset.vehicle_type,
                home_depot_id=asset.home_depot_id,
                available_second=trigger,
                remaining_battery_kwh=(
                    float(getattr(prices, "initial_ev_battery_kwh"))
                    if asset.vehicle_type == "ev"
                    else 0.0
                ),
                next_trip_index=1,
            )
            for asset_id, asset in ledger.assets.items()
        }
        source_sha256 = ledger.certificate_sha256
    else:
        if previous_stage_start_second is None:
            raise RuntimeError("HALT_DYNAMIC_CUT_PREVIOUS_STAGE_MISSING")
        dynamic_schedule.validate_dynamic_multitrip_certificate(
            solution,
            certificate,
            instance,
            prices,
            asset_states=inherited_asset_states,
            stage_start_second=float(previous_stage_start_second),
            locked_charging_actions=inherited_locked_charging_actions,
        )
        base_states = dict(inherited_asset_states)
        source_sha256 = canonical_sha256(certificate.as_dict())
    status_by_route: dict[str, str] = {}
    completed: list[str] = []
    in_progress: list[str] = []
    editable: list[str] = []
    for trip in certificate.trips:
        if trigger < float(trip.departure_second):
            status = NOT_STARTED
            editable.append(trip.route_id)
        elif trigger < float(trip.return_second):
            status = IN_PROGRESS
            in_progress.append(trip.route_id)
        else:
            status = COMPLETED
            completed.append(trip.route_id)
        status_by_route[trip.route_id] = status
    actions_by_asset: dict[str, list[tuple[float, float, Any]]] = defaultdict(list)
    locked = list(inherited_locked_charging_actions)
    for action in solution.charging_actions:
        trip = trip_by_id.get(action.vehicle_id)
        if trip is None:
            raise RuntimeError(
                f"HALT_DYNAMIC_CUT_DETACHED_ACTION:{action.vehicle_id}"
            )
        start = (
            float(action.charge_start_second)
            + int(action.charge_day_offset) * 86400.0
        )
        end = start + float(action.occupancy_minutes) * 60.0
        actions_by_asset[trip.physical_vehicle_id].append((start, end, action))
        if status_by_route[trip.route_id] != NOT_STARTED or start <= trigger:
            locked.append(action)
    battery_cap = instance.battery_capacity_kwh(
        fallback=float(getattr(prices, "B_battery_kwh"))
    )
    states: dict[str, Any] = {}
    for asset_id, base_state in base_states.items():
        chain = sorted(
            (
                trip
                for trip in certificate.trips
                if trip.physical_vehicle_id == asset_id
            ),
            key=lambda trip: int(trip.trip_index),
        )
        started = [
            trip
            for trip in chain
            if status_by_route[trip.route_id] != NOT_STARTED
        ]
        running = [
            trip
            for trip in chain
            if status_by_route[trip.route_id] == IN_PROGRESS
        ]
        available = max(trigger, float(base_state.available_second))
        if running:
            available = max(
                available,
                max(float(trip.return_second) for trip in running),
            )
        if str(base_state.vehicle_type).lower() == "ev":
            battery = float(base_state.remaining_battery_kwh)
            if started:
                last_started = max(started, key=lambda trip: int(trip.trip_index))
                battery = float(last_started.end_battery_kwh or 0.0)
            for start, end, action in actions_by_asset.get(asset_id, []):
                trip = trip_by_id[action.vehicle_id]
                if (
                    status_by_route[trip.route_id] == NOT_STARTED
                    and start <= trigger
                ):
                    battery += float(action.energy_kwh)
                    if end > trigger:
                        available = max(available, end)
            if battery < -TOL or battery > battery_cap + TOL:
                raise RuntimeError(
                    f"HALT_DYNAMIC_CUT_BATTERY:{asset_id}:{battery}"
                )
            battery = min(battery_cap, max(0.0, battery))
        else:
            battery = 0.0
        next_index = max(
            int(base_state.next_trip_index),
            max(
                (int(trip.trip_index) + 1 for trip in started),
                default=int(base_state.next_trip_index),
            ),
        )
        states[asset_id] = dynamic_schedule.DynamicAssetState(
            physical_vehicle_id=asset_id,
            vehicle_type=str(base_state.vehicle_type).lower(),
            home_depot_id=base_state.home_depot_id,
            available_second=available,
            remaining_battery_kwh=battery,
            next_trip_index=next_index,
        )
    deduplicated = dynamic_schedule._deduplicated_actions(locked)
    return dynamic_schedule.CertificateCut(
        trigger_second=trigger,
        source_certificate_sha256=source_sha256,
        completed_route_ids=tuple(sorted(completed)),
        in_progress_route_ids=tuple(sorted(in_progress)),
        editable_route_ids=tuple(sorted(editable)),
        locked_charging_actions=tuple(deduplicated),
        asset_states=MappingProxyType(states),
    )


def corrected_initial_cut(
    solution: Any,
    certificate: Any,
    instance: Any,
    prices: Any,
    *,
    trigger_second: float,
) -> Any:
    return _whole_trip_cut(
        solution,
        certificate,
        instance,
        prices,
        trigger_second=trigger_second,
    )


def corrected_dynamic_cut(
    solution: Any,
    certificate: Any,
    instance: Any,
    prices: Any,
    *,
    inherited_asset_states: Mapping[str, Any],
    previous_stage_start_second: float,
    trigger_second: float,
    inherited_locked_charging_actions: Sequence[Any] = (),
) -> Any:
    return _whole_trip_cut(
        solution,
        certificate,
        instance,
        prices,
        trigger_second=trigger_second,
        inherited_asset_states=inherited_asset_states,
        previous_stage_start_second=previous_stage_start_second,
        inherited_locked_charging_actions=inherited_locked_charging_actions,
    )


PROBE.cut_certificate_at_trigger = corrected_initial_cut
PROBE.cut_dynamic_certificate_at_trigger = corrected_dynamic_cut


def corrected_charging_window_witness(
    action: Any,
    certificate: Any,
    *,
    capture_stage: int,
    trigger_second: float | None,
) -> dict[str, Any]:
    try:
        return ORIGINAL_CHARGING_WINDOW_WITNESS(
            action,
            certificate,
            capture_stage=capture_stage,
            trigger_second=trigger_second,
        )
    except RuntimeError as exc:
        if (
            trigger_second is None
            or "unstarted charging action was marked locked" not in str(exc)
        ):
            raise
        trip = next(
            (
                row
                for row in certificate.trips
                if row.route_id == action.vehicle_id
            ),
            None,
        )
        if trip is None or not (
            float(trip.departure_second)
            <= float(trigger_second)
            < float(trip.return_second)
        ):
            raise
        observed = float(action.charge_start_second)
        return {
            "schema": PROBE.CHARGING_WINDOW_SCHEMA,
            "capture_stage": int(capture_stage),
            "lock_state": "whole_trip_in_progress_committed",
            "window_source": "immutable_departed_whole_trip",
            "vehicle_id": action.vehicle_id,
            "physical_vehicle_id": trip.physical_vehicle_id,
            "trip_index": int(trip.trip_index),
            "station_id": action.station_id,
            "energy_kwh": float(action.energy_kwh),
            "occupancy_minutes": float(action.occupancy_minutes),
            "charge_day_offset": int(action.charge_day_offset),
            "observed_start_second": observed,
            "earliest_start_second": observed,
            "latest_start_second": observed,
        }


PROBE._charging_window_witness = corrected_charging_window_witness


def search_structure_sha256(solution: Any) -> str:
    return canonical_sha256(PROBE.base.solution_to_dict(solution))


def winner_current_objective(
    solution: Any,
    context: Any,
) -> float:
    key = (id(context), search_structure_sha256(solution))
    cached = WINNER_OBJECTIVE_CACHE.get(key)
    if cached is not None:
        return cached
    _, objective = score_reference_solution(
        solution,
        context,
        phase="e7_dynamic_current_structure",
    )
    value = float(objective)
    if not math.isfinite(value):
        raise RuntimeError("HALT_ALNS_CURRENT_OBJECTIVE_NONFINITE")
    WINNER_OBJECTIVE_CACHE[key] = value
    return value


def corrected_apply_winner_action(
    solution: Any,
    action: Any,
    context: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    if kwargs.get("current_obj") is None:
        kwargs["current_obj"] = winner_current_objective(solution, context)
    result = ORIGINAL_APPLY_WINNER_ACTION(
        solution,
        action,
        context,
        **kwargs,
    )
    candidate = result.get("candidate_solution")
    candidate_objective = result.get("candidate_obj")
    if candidate is not None and candidate_objective is not None:
        WINNER_OBJECTIVE_CACHE[
            (id(context), search_structure_sha256(candidate))
        ] = float(candidate_objective)
    return result


PROBE.base.apply_winner_action = corrected_apply_winner_action


def traced_search_stage_v3(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if not LEGACY._TRACE_MODE:
        return ORIGINAL_TRACED_SEARCH_STAGE(*args, **kwargs)
    before = len(LEGACY._LAST_SEARCH_TRACES)
    result = ORIGINAL_TRACED_SEARCH_STAGE(*args, **kwargs)
    if len(LEGACY._LAST_SEARCH_TRACES) != before + 1:
        raise RuntimeError("HALT_CONVERGENCE_TRACE_ACCOUNTING")
    trace = LEGACY._LAST_SEARCH_TRACES[-1]
    actual = int(result["evaluations"])
    cap = int(kwargs["evaluations"])
    trace["actual_evaluations"] = actual
    trace["candidate_exhausted_before_cap"] = actual < cap
    trace["null_objective_count"] = sum(
        row["complete_objective"] is None
        for row in trace["trace"][:actual]
    )
    return result


LEGACY.traced_search_stage = traced_search_stage_v3


def input_paths() -> list[Path]:
    paths: set[Path] = {
        TIMING_AUTHORITY / CALENDAR_NAME,
        APPROVED_WRAPPER_AUTHORITY / CALENDAR_NAME,
        E4_RUNNER,
    }
    for scale in LEGACY.SCALES:
        paths.add(LEGACY.base_owner_path(scale))
        for stream_seed in range(1, 6):
            paths.add(LEGACY.event_path(scale, stream_seed))
        for seed in range(1, 11):
            paths.add(LEGACY.nominal_plan_path(scale, seed))
    return sorted(paths)


def current_input_hashes() -> dict[str, str]:
    missing = [relative(path) for path in input_paths() if not path.exists()]
    if missing:
        raise RuntimeError(f"HALT_INPUT_MISSING:{missing}")
    return {relative(path): source_sha256(path) for path in input_paths()}


def verify_input_lock() -> dict[str, str]:
    path = HERE / "wiring_selfcheck.json"
    if not path.is_file():
        raise RuntimeError("HALT_WIRING_SELFCHECK_MISSING")
    payload = read_json(path)
    if not payload.get("wiring_selfcheck_all_green"):
        raise RuntimeError("HALT_WIRING_SELFCHECK_NOT_GREEN")
    expected = payload["input_sha256"]
    observed = current_input_hashes()
    if observed != expected:
        drift = {
            key: {
                "expected": expected.get(key),
                "observed": observed.get(key),
            }
            for key in sorted(set(expected) | set(observed))
            if expected.get(key) != observed.get(key)
        }
        raise RuntimeError(
            "HALT_FROZEN_INPUT_HASH_DRIFT:"
            + json.dumps(drift, ensure_ascii=False, sort_keys=True)
        )
    return observed


def verify_protected_and_inputs() -> dict[str, str]:
    protected = ORIGINAL_VERIFY_PROTECTED()
    if (HERE / "wiring_selfcheck.json").is_file():
        verify_input_lock()
    return protected


LEGACY.verify_protected = verify_protected_and_inputs


def guarded_controlled_stage_dispatch(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Recheck protected code and every frozen input before each event stage."""
    global _ACTIVE_EVENT_STAGE, _COMPLETED_EVENT_STAGE
    verify_protected_and_inputs()
    _ACTIVE_EVENT_STAGE = int(kwargs["seed"]) % 1000
    result = ORIGINAL_CONTROLLED_STAGE_DISPATCH(*args, **kwargs)
    _COMPLETED_EVENT_STAGE = _ACTIVE_EVENT_STAGE
    ORIGINAL_VERIFY_PROTECTED()
    return result


LEGACY.controlled_stage_dispatch = guarded_controlled_stage_dispatch


def required_dataclass_fields(cls: type[Any]) -> set[str]:
    return set(inspect.signature(cls).parameters)


def objective_for_solution(solution: Any, sources: Mapping[str, Any]) -> float:
    violations = check_solution(
        solution,
        sources["bundle"].instance,
        sources["prices"],
    )
    if violations:
        raise RuntimeError(
            "HALT_ZERO_SEARCH_MODEL_VIOLATIONS:"
            + json.dumps(
                [asdict(row) for row in violations[:10]],
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    objective = float(
        PROBE.base.evaluate_parts(
            solution.routes,
            solution.charging_actions,
            sources["bundle"].instance,
            sources,
        )["total_cost"]
    )
    if not math.isfinite(objective):
        raise RuntimeError("HALT_ZERO_SEARCH_NONFINITE_OBJECTIVE")
    return objective


def first_stage_search_state_objectives(
    sources: Mapping[str, Any],
    profiles: Mapping[int, list[dict[str, Any]]],
) -> dict[str, float]:
    LEGACY.install_adapter()
    initial_solution, initial_certificate, _ = corrected_initial_plan(
        "FULL_ROLLING",
        sources,
        profiles,
    )
    events, owners, _, _ = LEGACY.current_stream(1, "seed1", "50c")
    batch = LEGACY.validated_batches("50c", 1, events)[0]
    trigger = float(batch["trigger_time"])
    cut = corrected_initial_cut(
        initial_solution,
        initial_certificate,
        sources["bundle"].instance,
        sources["prices"],
        trigger_second=trigger,
    )
    locked_ids = [*cut.completed_route_ids, *cut.in_progress_route_ids]
    locked_routes = PROBE.base.gate._cut_routes(initial_solution, locked_ids)
    committed_customers = {
        customer_id
        for route in locked_routes
        for customer_id in PROBE.base.p2.route_customers(
            route,
            sources["bundle"].instance,
        )
    }
    construction = PROBE.base.gate.build_open_stage(
        PROBE.base.gate._cut_routes(
            initial_solution,
            cut.editable_route_ids,
        ),
        sources["bundle"].instance,
        batch["events"],
        trigger,
        committed_customers,
        owners,
        sources["prices"],
        stage_index=1,
        isolate_changed_customers=True,
    )
    PROBE.base._validate_stage_application(construction, batch["events"])
    try:
        prepared, _, _ = (
            PROBE.base.gate.prepare_stage_with_singleton_type_choices(
                construction,
                sources["prices"],
                asset_states=cut.asset_states,
                stage_start_second=trigger,
                locked_charging_actions=cut.locked_charging_actions,
            )
        )
        structure = PROBE.base.normalized_search_solution(
            prepared,
            construction.effective_instance,
            owners,
        )
    except RuntimeError:
        structure = construction.solution
    search_instance = PROBE.base.p2.future_only_instance(
        construction.effective_instance,
        committed_customers,
    )
    values: dict[str, float] = {}
    for arm, allow_cross in (
        ("FULL_ROLLING", True),
        ("NO_COOPERATION", False),
        ("CARBON_BLIND", True),
    ):
        context = PROBE.base.EvaluationContext(
            search_instance,
            sources["bundle"].carbon_profile,
            prices=sources["prices"],
            budget=PROBE.base.EvalBudget(limit=0, target=0),
            customer_home_depot=owners,
            allow_cross_depot=allow_cross,
            repair_delta_mode="fast",
        )
        values[arm] = winner_current_objective(structure, context)
        if context.budget.count != 0:
            raise RuntimeError("HALT_ZERO_SEARCH_STATE_OBJECTIVE_BUDGET")
    return values


def render_selfcheck_report(payload: Mapping[str, Any]) -> str:
    lines = [
        "# E7 动态需求实验",
        "",
        "状态：`PASS_WIRING_SELFCHECK_ALL_GREEN`。正式探针尚未启动，"
        "完整候选搜索评价数为 0。",
        "",
        "## 启动接线自检",
        "",
        "| 门 | 结果 | 证据 |",
        "|---|---|---|",
    ]
    for row in payload["checks"]:
        lines.append(
            f"| {row['name']} | `{row['status']}` | {row['evidence']} |"
        )
    lines.extend(
        [
            "",
            f"本轮系统审计登记并修复 {payload['wiring_issues_found']} 项接线问题："
            "China81 八源文件字段、"
            "显式 China81 prices、offset −1 前一日电网曲线，以及"
            "`actual_evaluations` 结果字段对齐与整趟路线终态电量释放。"
            "运行日为 2025-02-12，"
            "首趟预充按 E4 权威口径使用 2025-02-11；v3 与批准 v4 的共享"
            "时变字段已逐行闭合。",
            "",
            "四臂零搜索最小模型评价均已返回有限目标值：",
            "",
            "| 臂 | 路线搜索 | 目标值 | 硬违反 |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in payload["arm_minimum_model_evaluations"]:
        lines.append(
            f"| {row['arm']} | {str(row['route_search']).lower()} | "
            f"{float(row['objective_cny']):.6f} | "
            f"{int(row['hard_violation_count'])} |"
        )
    lines.extend(
        [
            "",
            "## 待运行阶段",
            "",
            "收敛探针、50c、100c、150c、独立复算与正式统计表将在后续"
            "阶段逐项写入本报告。",
            "",
        ]
    )
    return "\n".join(lines)


def run_wiring_selfcheck(workers: int) -> dict[str, Any]:
    if workers < 1 or workers > 2:
        raise RuntimeError("HALT_WORKERS_MUST_BE_1_OR_2")
    if Path(sys.executable).resolve() != LEGACY.PYTHON.resolve():
        raise RuntimeError(
            f"HALT_WRONG_PYTHON:{sys.executable}!={LEGACY.PYTHON}"
        )
    thread_environment = LEGACY.verify_thread_environment()
    protected = ORIGINAL_VERIFY_PROTECTED()
    calendar = validate_e4_calendar_contract()
    owner_manifest = LEGACY.build_owner_inputs()
    event_type_fields = required_dataclass_fields(DynamicEvent)
    rolling_fields = required_dataclass_fields(RollingParameters)
    event_manifest: list[dict[str, Any]] = []
    source_contracts: list[dict[str, Any]] = []
    cut_contracts: list[dict[str, Any]] = []
    plan_manifest: list[dict[str, Any]] = []
    all_batches = 0
    total_events = 0
    for scale in LEGACY.SCALES:
        for seed in range(1, 11):
            plan = LEGACY.nominal_plan_path(scale, seed)
            payload = read_json(plan)
            if scale in {"50c", "100c"}:
                if payload.get("arm") != "JOINT":
                    raise RuntimeError(f"HALT_PLAN_ARM:{scale}:{seed}")
                if int(payload.get("seed", -1)) != seed:
                    raise RuntimeError(f"HALT_PLAN_SEED:{scale}:{seed}")
            plan_manifest.append(
                {
                    "scale": scale,
                    "seed": seed,
                    "path": relative(plan),
                    "sha256": sha256(plan),
                    "source_role": (
                        "E3_SEALED_JOINT"
                        if scale in {"50c", "100c"}
                        else "FOUNDATION_FROZEN_COMMON_INITIAL"
                    ),
                }
            )
        LEGACY._CURRENT_ALGORITHM_SEED = 1
        sources, profiles = current_sources(network=scale)
        missing_sources = REQUIRED_SOURCE_KEYS - set(sources)
        if missing_sources:
            raise RuntimeError(
                f"HALT_REQUIRED_SOURCE_FIELDS:{scale}:{sorted(missing_sources)}"
            )
        source_contracts.append(
            {
                "scale": scale,
                "source_fields": sorted(sources),
                "china81_source_fields": sorted(
                    sources["instance_source_paths"]
                ),
                "profile_offsets": sorted(profiles),
                "profile_rows": {
                    str(offset): len(rows)
                    for offset, rows in sorted(profiles.items())
                },
                "profile_fields": sorted(profiles[0][0]),
                "charge_day_offsets": sorted(
                    {
                        int(action.charge_day_offset)
                        for action in sources["solution"].charging_actions
                    }
                ),
                "prices_sha256": canonical_sha256(asdict(sources["prices"])),
            }
        )
        if set(profiles) != {-1, 0}:
            raise RuntimeError(f"HALT_PROFILE_OFFSET_SET:{scale}")
        initial_solution, initial_certificate, _ = corrected_initial_plan(
            "FULL_ROLLING",
            sources,
            profiles,
        )
        first_stream = LEGACY.load_event_payload(scale, 1)
        first_events = [DynamicEvent(**row) for row in first_stream["events"]]
        first_trigger = float(
            LEGACY.validated_batches(scale, 1, first_events)[0]["trigger_time"]
        )
        first_cut = corrected_initial_cut(
            initial_solution,
            initial_certificate,
            sources["bundle"].instance,
            sources["prices"],
            trigger_second=first_trigger,
        )
        ev_batteries = [
            float(state.remaining_battery_kwh)
            for state in first_cut.asset_states.values()
            if state.vehicle_type == "ev"
        ]
        if not ev_batteries or min(ev_batteries) < -TOL:
            raise RuntimeError(f"HALT_FIRST_CUT_BATTERY:{scale}")
        charging_witnesses = [
            corrected_charging_window_witness(
                action,
                initial_certificate,
                capture_stage=1,
                trigger_second=first_trigger,
            )
            for action in first_cut.locked_charging_actions
        ]
        cut_contracts.append(
            {
                "scale": scale,
                "trigger_second": first_trigger,
                "completed_route_count": len(first_cut.completed_route_ids),
                "in_progress_route_count": len(first_cut.in_progress_route_ids),
                "editable_route_count": len(first_cut.editable_route_ids),
                "locked_charging_action_count": len(
                    first_cut.locked_charging_actions
                ),
                "charging_witness_count": len(charging_witnesses),
                "whole_trip_future_charge_witness_count": sum(
                    row["lock_state"]
                    == "whole_trip_in_progress_committed"
                    for row in charging_witnesses
                ),
                "minimum_ev_release_battery_kwh": min(ev_batteries),
                "maximum_ev_release_battery_kwh": max(ev_batteries),
            }
        )
        for stream_seed in range(1, 6):
            payload = LEGACY.load_event_payload(scale, stream_seed)
            events = payload["events"]
            if any(set(row) != event_type_fields for row in events):
                raise RuntimeError(
                    f"HALT_EVENT_FIELD_SET:{scale}:{stream_seed}"
                )
            if set(payload["rolling_parameters"]) != rolling_fields:
                raise RuntimeError(
                    f"HALT_ROLLING_FIELD_SET:{scale}:{stream_seed}"
                )
            typed = [DynamicEvent(**row) for row in events]
            batches = LEGACY.validated_batches(scale, stream_seed, typed)
            all_batches += len(batches)
            total_events += len(events)
            event_manifest.append(
                {
                    "scale": scale,
                    "stream_seed": stream_seed,
                    "event_count": len(events),
                    "batch_count": len(batches),
                    "event_types": dict(
                        sorted(Counter(row["event_type"] for row in events).items())
                    ),
                    "path": relative(LEGACY.event_path(scale, stream_seed)),
                    "sha256": sha256(LEGACY.event_path(scale, stream_seed)),
                }
            )
    if len(event_manifest) != 15:
        raise RuntimeError(f"HALT_EVENT_STREAM_COUNT:{len(event_manifest)}")
    LEGACY._CURRENT_ALGORITHM_SEED = 1
    model_sources, model_profiles = current_sources(network="50c")
    aware, _, aware_timing = corrected_initial_plan(
        "FULL_ROLLING", model_sources, model_profiles
    )
    immediate = reschedule_between_trip_charging(
        model_sources["solution"],
        model_sources["certificate"],
        model_sources["bundle"].instance,
        model_profiles[0],
        strategy="naive",
        prices=model_sources["prices"],
        carbon_profiles_by_day_offset=model_profiles,
        intensity_field="forecast_gco2_per_kwh",
    )
    immediate, immediate_certificate = prepare_multitrip_solution(
        immediate,
        model_sources["bundle"].instance,
        model_sources["prices"],
    )
    validate_multitrip_certificate(
        immediate_certificate,
        list(immediate.routes),
        model_sources["prices"],
        instance=model_sources["bundle"].instance,
    )
    arm_rows: list[dict[str, Any]] = []
    search_state_objectives = first_stage_search_state_objectives(
        model_sources,
        model_profiles,
    )
    for arm in LEGACY.ARMS:
        selected = immediate if arm == "CARBON_BLIND" else aware
        objective = objective_for_solution(selected, model_sources)
        arm_rows.append(
            {
                "arm": arm,
                **ARM_CONFIGS[arm],
                "objective_cny": objective,
                "hard_violation_count": 0,
                "complete_model_evaluations": 1,
                "search_evaluations": 0,
                "first_stage_search_state_objective_cny": (
                    search_state_objectives.get(arm)
                ),
                "solution_sha256": canonical_sha256(
                    PROBE.base.solution_to_dict(selected)
                ),
            }
        )
    legal_static = run_task_with_legal_infeasibility(
        "50c",
        1,
        "STATIC_FIXED_RECOURSE",
        per_pass_cap=1,
        max_stages=1,
    )
    if (
        legal_static["status"] != "LEGAL_INFEASIBLE"
        or legal_static["final_total_cost"] is not None
        or int(legal_static["actual_evaluations"]) != 0
        or int(legal_static["failure_stage"]) != 1
    ):
        raise RuntimeError("HALT_LEGAL_INFEASIBLE_CLASSIFICATION_SELFCHECK")
    input_hashes = current_input_hashes()
    worker_pickle = pickle.dumps(LEGACY.formal_worker)
    if not worker_pickle:
        raise RuntimeError("HALT_FORMAL_WORKER_PICKLE_EMPTY")
    checks = [
        {
            "name": "protected_hashes",
            "status": "PASS",
            "evidence": f"{len(protected)} frozen files matched",
        },
        {
            "name": "all_input_files",
            "status": "PASS",
            "evidence": f"{len(input_hashes)} frozen input paths loaded and hashed",
        },
        {
            "name": "china81_source_fields",
            "status": "PASS",
            "evidence": "8/8 named source fields matched for all three scales",
        },
        {
            "name": "event_and_rolling_fields",
            "status": "PASS",
            "evidence": (
                f"15 streams, {total_events} events, {all_batches} trigger batches"
            ),
        },
        {
            "name": "e4_dual_day_calendar",
            "status": "PASS",
            "evidence": "offset -1=2025-02-11; offset 0=2025-02-12",
        },
        {
            "name": "explicit_prices",
            "status": "PASS",
            "evidence": "China81 PriceParameters supplied to both initial variants",
        },
        {
            "name": "arm_construction",
            "status": "PASS",
            "evidence": "4/4 arm configurations constructed",
        },
        {
            "name": "minimum_complete_model_evaluation",
            "status": "PASS",
            "evidence": "4/4 finite objectives; 0 hard violations; 0 search evaluations",
        },
        {
            "name": "whole_trip_release_state",
            "status": "PASS",
            "evidence": (
                "first trigger cut passed for 50c, 100c, and 150c with "
                "certified terminal EV batteries"
            ),
        },
        {
            "name": "in_progress_route_charging_witness",
            "status": "PASS",
            "evidence": (
                "every locked action at the first trigger has a contemporaneous "
                "window witness in all three scales"
            ),
        },
        {
            "name": "result_field_alignment",
            "status": "PASS",
            "evidence": "actual_evaluations is the canonical task result field",
        },
        {
            "name": "alns_current_objective_binding",
            "status": "PASS",
            "evidence": (
                "FULL_ROLLING, NO_COOPERATION, and CARBON_BLIND first-stage "
                "search states have finite reference objectives with zero "
                "candidate evaluations"
            ),
        },
        {
            "name": "spawn_worker_serialization",
            "status": "PASS",
            "evidence": (
                f"v3 worker pickled under module {LEGACY.__name__} "
                f"({len(worker_pickle)} bytes)"
            ),
        },
        {
            "name": "legal_infeasible_classification",
            "status": "PASS",
            "evidence": (
                "50c STATIC_FIXED_RECOURSE stage 1 retained as "
                "LEGAL_INFEASIBLE with null objective and 0 evaluations"
            ),
        },
        {
            "name": "trace_mode_guard",
            "status": "PASS",
            "evidence": (
                "formal trace_mode=false dispatches directly without "
                "convergence-trace row assertions"
            ),
        },
        {
            "name": "no_executable_continuation_classification",
            "status": "PASS",
            "evidence": (
                "the rolling gate dedicated NoExecutableContinuation class "
                "is included in the LEGAL_INFEASIBLE terminal predicate"
            ),
        },
    ]
    payload = {
        "schema": "resetp.china81.e7.wiring-selfcheck.v1",
        "task_id": TASK_ID,
        "status": "PASS_WIRING_SELFCHECK_ALL_GREEN",
        "created_at_utc": LEGACY.now_iso(),
        "wiring_selfcheck_all_green": True,
        "wiring_issues_found": len(WIRING_FIXES),
        "wiring_issues": [
            {**row, "status": "FIXED_AND_REGRESSION_CHECKED"}
            for row in WIRING_FIXES
        ],
        "search_evaluations": 0,
        "workers_checked": workers,
        "thread_environment": thread_environment,
        "protected_hashes": protected,
        "input_sha256": input_hashes,
        "calendar_contract": calendar,
        "source_contracts": source_contracts,
        "whole_trip_release_contracts": cut_contracts,
        "plan_manifest": plan_manifest,
        "event_manifest": event_manifest,
        "owner_manifest": owner_manifest,
        "arm_configs": ARM_CONFIGS,
        "arm_minimum_model_evaluations": arm_rows,
        "initial_aware_timing": aware_timing,
        "checks": checks,
        "upstream_use": {
            "E3": "50c and 100c sealed JOINT plans plus responsibility maps",
            "E6": "no sealed E6 outcome is consumed by the E7 runtime",
            "foundation_150c": "frozen mismatch00 common initial solution and responsibility map",
        },
        "failed_startup_attempts": [
            {
                "round": "v1",
                "halt": "HALT_PROBE_STARTUP_KEYERROR_INSTANCE_PATH",
                "actual_candidate_evaluations": 0,
            },
            {
                "round": "v2",
                "halt": "HALT_PROBE_STARTUP_CURVE_CALENDAR_CONTRACT",
                "actual_candidate_evaluations": 0,
            },
            {
                "round": "v3_probe_attempt_1",
                "halt": "WHOLE_TRIP_RELEASE_BATTERY_STATE",
                "actual_candidate_evaluations": 0,
            },
            {
                "round": "v3_probe_attempt_2",
                "halt": "IN_PROGRESS_ROUTE_CHARGING_WITNESS",
                "actual_candidate_evaluations": 0,
            },
            {
                "round": "v3_probe_attempt_3",
                "halt": "ALNS_CURRENT_OBJECTIVE_BINDING",
                "actual_candidate_evaluations": 400,
            },
            {
                "round": "v3_formal_50c_attempt_1",
                "halt": "SPAWN_WORKER_MODULE_IDENTITY",
                "actual_candidate_evaluations": 0,
            },
            {
                "round": "v3_formal_50c_attempt_2",
                "halt": "LEGAL_INFEASIBLE_TASK_CLASSIFICATION",
                "actual_candidate_evaluations": 0,
            },
            {
                "round": "v3_formal_50c_attempt_3",
                "halt": "TRACE_MODE_GUARD",
                "actual_candidate_evaluations": None,
                "actual_candidate_evaluations_upper_bound": 600,
            },
            {
                "round": "v3_formal_50c_attempt_4",
                "halt": "NO_EXECUTABLE_CONTINUATION_CLASSIFICATION",
                "actual_candidate_evaluations": None,
                "actual_candidate_evaluations_upper_bound": 1200,
            },
        ],
    }
    payload["selfcheck_sha256"] = canonical_sha256(payload)
    LEGACY.atomic_json(HERE / "wiring_selfcheck.json", payload)
    LEGACY.atomic_csv(HERE / "inputs/event_manifest.csv", event_manifest)
    LEGACY.atomic_csv(HERE / "inputs/plan_manifest.csv", plan_manifest)
    (HERE / "report.md").write_text(
        render_selfcheck_report(payload),
        encoding="utf-8",
    )
    LEGACY.append_progress(
        {
            "phase": "wiring-selfcheck",
            "status": "PASS",
            "wiring_issues_found": len(WIRING_FIXES),
            "search_evaluations": 0,
        }
    )
    verify_input_lock()
    return payload


def round_up_hundred_with_margin(value: int) -> int:
    if value < 1:
        return 100
    rounded = int(math.ceil(value / 100.0) * 100)
    return rounded + 100 if rounded == value else rounded


def run_probe() -> dict[str, Any]:
    verify_protected_and_inputs()
    attempts: list[dict[str, Any]] = []
    for cap in (800, 1600):
        result = LEGACY.run_task(
            "50c",
            1,
            "FULL_ROLLING",
            per_pass_cap=cap,
            max_stages=1,
            trace_mode=True,
        )
        traces = result["convergence_search_traces"]
        if len(traces) != 2:
            raise RuntimeError(
                f"HALT_PROBE_EXPECTED_TWO_SEARCH_PASSES:{len(traces)}"
            )
        latest = max(
            int(row["last_strict_improvement_evaluation"])
            for row in traces
        )
        exhausted_points = [
            int(row["actual_evaluations"])
            for row in traces
            if row["candidate_exhausted_before_cap"]
        ]
        candidate_exhausted = len(exhausted_points) == len(traces)
        plateau_observed = latest <= int(0.9 * cap)
        basis = max(exhausted_points) if candidate_exhausted else latest
        attempt = {
            "per_pass_long_cap": cap,
            "per_stage_long_cap": 2 * cap,
            "last_shadow_improvement_evaluation": int(
                traces[0]["last_strict_improvement_evaluation"]
            ),
            "last_main_improvement_evaluation": int(
                traces[1]["last_strict_improvement_evaluation"]
            ),
            "latest_improvement_evaluation": latest,
            "shadow_actual_evaluations": int(traces[0]["actual_evaluations"]),
            "main_actual_evaluations": int(traces[1]["actual_evaluations"]),
            "candidate_exhausted_in_both_passes": candidate_exhausted,
            "plateau_observed": plateau_observed,
            "selection_basis_evaluation": basis,
            "null_objective_count": sum(
                int(row["null_objective_count"]) for row in traces
            ),
            "result_sha256": result["result_sha256"],
            "convergence_search_traces": traces,
        }
        attempts.append(attempt)
        LEGACY.atomic_json(HERE / "probe" / f"cap_{cap}.json", result)
        if candidate_exhausted or plateau_observed:
            selected_per_pass = round_up_hundred_with_margin(basis)
            break
        if cap == 1600:
            halt = {
                "schema": "resetp.china81.e7.budget-lock.v1",
                "task_id": TASK_ID,
                "status": "HALT_NEEDS_LONGER_BUDGET_DECISION",
                "attempts": attempts,
            }
            LEGACY.atomic_json(HERE / "budget_lock.json", halt)
            raise RuntimeError("HALT_NEEDS_LONGER_BUDGET_DECISION")
    else:
        raise AssertionError("unreachable")
    lock = {
        "schema": "resetp.china81.e7.budget-lock.v1",
        "task_id": TASK_ID,
        "status": "PASS_BUDGET_SELECTED",
        "created_at_utc": LEGACY.now_iso(),
        "budget_semantics": "UPPER_CAP_NOT_QUOTA",
        "selection_rule": (
            "use the later candidate-exhaustion point when both passes exhaust; "
            "otherwise use the later strict-improvement point after an observed "
            "10% plateau; round upward to a hundred with positive margin"
        ),
        "attempts": attempts,
        "selected_per_search_pass_cap": selected_per_pass,
        "selected_total_stage_cap": 2 * selected_per_pass,
        "protected_hashes": verify_protected_and_inputs(),
    }
    lock["budget_lock_sha256"] = canonical_sha256(lock)
    LEGACY.atomic_json(HERE / "budget_lock.json", lock)
    LEGACY.append_progress(
        {
            "phase": "probe",
            "status": "PASS",
            "selected_per_search_pass_cap": selected_per_pass,
            "selected_total_stage_cap": 2 * selected_per_pass,
        }
    )
    return lock


def is_legal_infeasibility(error: BaseException) -> bool:
    return (
        isinstance(error, PROBE.base.NoExecutableContinuation)
        or (
            isinstance(error, RuntimeError)
            and "no feasible vehicle type assignment for separate event trips"
            in str(error)
        )
    )


def legal_infeasible_task(
    scale: str,
    seed: int,
    arm: str,
    per_pass_cap: int,
    *,
    error: BaseException,
    actual_evaluations: int,
    wall_seconds: float,
    cpu_user_seconds: float,
    cpu_system_seconds: float,
) -> dict[str, Any]:
    stream_seed = LEGACY.stream_for_algorithm_seed(seed)
    sources, profiles = current_sources(f"seed{seed}", scale)
    owners = LEGACY.load_owners(scale, stream_seed)
    nominal_solution, _, nominal_timing = PROBE._initial_plan(
        "full",
        sources,
        profiles,
    )
    nominal_ledger = PROBE._profit_closure(
        nominal_solution,
        sources["bundle"].instance,
        sources,
        owners,
    )
    initial_cross = LEGACY.initial_cross_ids(
        nominal_solution,
        sources["bundle"].instance,
        owners,
    )
    failure_stage = max(1, int(_ACTIVE_EVENT_STAGE))
    completed_stages = min(int(_COMPLETED_EVENT_STAGE), failure_stage - 1)
    attempted_stages = completed_stages + 1
    stage_cap = 2 * int(per_pass_cap)
    if int(actual_evaluations) > attempted_stages * stage_cap:
        raise RuntimeError(
            "HALT_ACTUAL_EVALUATIONS_ABOVE_ATTEMPTED_STAGE_CAP:"
            f"{actual_evaluations}>{attempted_stages * stage_cap}"
        )
    event_file = LEGACY.event_path(scale, stream_seed)
    owner_file = LEGACY.owner_input_path(scale, stream_seed)
    plan_file = LEGACY.nominal_plan_path(scale, seed)
    result = {
        "schema": "resetp.china81.e7.task.v3",
        "task_id": TASK_ID,
        "status": "LEGAL_INFEASIBLE",
        "feasible": False,
        "created_at_utc": LEGACY.now_iso(),
        "scale": scale,
        "instance_id": LEGACY.INSTANCE_BY_SCALE[scale],
        "algorithm_seed": int(seed),
        "stream_seed": stream_seed,
        "arm": arm,
        "per_search_pass_cap": int(per_pass_cap),
        "per_stage_total_cap": stage_cap,
        "stage_count": completed_stages,
        "completed_stage_count": completed_stages,
        "attempted_stage_count": attempted_stages,
        "failure_stage": failure_stage,
        "actual_evaluations": int(actual_evaluations),
        "legal_infeasibility_reason": str(error),
        "nominal_total_cost": float(nominal_ledger["total_cost"]),
        "nominal_total_profit": float(nominal_ledger["total_profit"]),
        "nominal_depot_profit": nominal_ledger["depot_profit"],
        "nominal_timing": nominal_timing,
        "initial_cross_site_customer_ids": sorted(initial_cross),
        "final_total_cost": None,
        "final_total_profit": None,
        "final_depot_profit": None,
        "final_actual_emissions_kg": None,
        "final_actual_charging_emissions_kg": None,
        "final_charging_energy_kwh": None,
        "vehicle_count": None,
        "physical_vehicle_ids": [],
        "wall_seconds": wall_seconds,
        "cpu_user_seconds": cpu_user_seconds,
        "cpu_system_seconds": cpu_system_seconds,
        "event_path": relative(event_file),
        "event_sha256": sha256(event_file),
        "owner_path": relative(owner_file),
        "owner_sha256": sha256(owner_file),
        "nominal_plan_path": relative(plan_file),
        "nominal_plan_sha256": sha256(plan_file),
        "cross_depot_reassignment_after_event": None,
        "new_cross_site_customer_ids": [],
        "member_profit_shift_after_event": None,
        "carbon_aware_charging_shift_after_event": None,
        "moved_charge_actions_after_event": None,
        "payload": None,
        "convergence_search_traces": list(LEGACY._LAST_SEARCH_TRACES),
        "protected_hashes": verify_protected_and_inputs(),
    }
    result["result_sha256"] = canonical_sha256(result)
    return result


def run_task_with_legal_infeasibility(
    scale: str,
    seed: int,
    arm: str,
    *,
    per_pass_cap: int,
    max_stages: int,
    trace_mode: bool = False,
) -> dict[str, Any]:
    global _ACTIVE_EVENT_STAGE, _COMPLETED_EVENT_STAGE
    _ACTIVE_EVENT_STAGE = 0
    _COMPLETED_EVENT_STAGE = 0
    actual_evaluations = 0
    budget_class = PROBE.base.EvalBudget
    original_record = budget_class.record
    started = time.perf_counter()
    before = LEGACY.resource.getrusage(LEGACY.resource.RUSAGE_SELF)

    def counted_record(budget: Any) -> Any:
        nonlocal actual_evaluations
        result = original_record(budget)
        actual_evaluations += 1
        return result

    budget_class.record = counted_record
    try:
        result = ORIGINAL_RUN_TASK(
            scale,
            seed,
            arm,
            per_pass_cap=per_pass_cap,
            max_stages=max_stages,
            trace_mode=trace_mode,
        )
        if int(result["actual_evaluations"]) != actual_evaluations:
            raise RuntimeError(
                "HALT_EVALUATION_COUNTER_MISMATCH:"
                f"{result['actual_evaluations']}!={actual_evaluations}"
            )
        return result
    except Exception as error:
        if not is_legal_infeasibility(error):
            raise
        after = LEGACY.resource.getrusage(LEGACY.resource.RUSAGE_SELF)
        return legal_infeasible_task(
            scale,
            seed,
            arm,
            per_pass_cap,
            error=error,
            actual_evaluations=actual_evaluations,
            wall_seconds=time.perf_counter() - started,
            cpu_user_seconds=after.ru_utime - before.ru_utime,
            cpu_system_seconds=after.ru_stime - before.ru_stime,
        )
    finally:
        budget_class.record = original_record
        LEGACY._TRACE_MODE = False


LEGACY.run_task = run_task_with_legal_infeasibility


def formal_worker(spec: tuple[str, int, str, int, int]) -> dict[str, Any]:
    scale, seed, arm, per_pass_cap, max_stages = spec
    output = LEGACY.task_path(scale, seed, arm)
    if output.is_file():
        existing = read_json(output)
        if (
            existing.get("status") in {"PASS", "LEGAL_INFEASIBLE"}
            and int(existing.get("per_search_pass_cap", -1)) == per_pass_cap
            and existing.get("protected_hashes") == verify_protected_and_inputs()
        ):
            expected_hash = existing.pop("result_sha256", None)
            observed_hash = canonical_sha256(existing)
            existing["result_sha256"] = expected_hash
            if expected_hash != observed_hash:
                raise RuntimeError(f"HALT_STALE_TASK_HASH:{output}")
            return existing
        raise RuntimeError(f"HALT_STALE_TASK:{output}")
    result = run_task_with_legal_infeasibility(
        scale,
        seed,
        arm,
        per_pass_cap=per_pass_cap,
        max_stages=max_stages,
    )
    LEGACY.atomic_json(output, result)
    return result


formal_worker.__module__ = LEGACY.__name__
formal_worker.__qualname__ = "formal_worker"
setattr(LEGACY, "formal_worker", formal_worker)


def run_formal(scale: str, workers: int) -> dict[str, Any]:
    if scale not in LEGACY.SCALES:
        raise ValueError(scale)
    if workers < 1 or workers > FORMAL_MAX_WORKERS:
        raise RuntimeError(
            f"HALT_WORKERS_MUST_BE_1_TO_{FORMAL_MAX_WORKERS}"
        )
    verify_protected_and_inputs()
    LEGACY.verify_thread_environment()
    lock = LEGACY.load_budget_lock()
    cap = int(lock["selected_per_search_pass_cap"])
    specs = [
        (scale, seed, arm, cap, 99)
        for seed in range(1, 11)
        for arm in LEGACY.ARMS
    ]
    LEGACY.append_progress(
        {
            "phase": f"formal-{scale}",
            "status": "START",
            "unit_count": len(specs),
            "workers": workers,
            "per_search_pass_cap": cap,
        }
    )
    completed = 0
    feasible = 0
    legal_infeasible = 0
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as executor:
        futures = {
            executor.submit(LEGACY.formal_worker, spec): spec for spec in specs
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                result = future.result()
            except Exception:
                for pending in futures:
                    pending.cancel()
                LEGACY.append_progress(
                    {
                        "phase": f"formal-{scale}",
                        "status": "HALT",
                        "failed_spec": list(spec),
                    }
                )
                raise
            completed += 1
            status = str(result["status"])
            feasible += int(status == "PASS")
            legal_infeasible += int(status == "LEGAL_INFEASIBLE")
            LEGACY.append_progress(
                {
                    "phase": f"formal-{scale}",
                    "status": status,
                    "completed": completed,
                    "total": len(specs),
                    "seed": result["algorithm_seed"],
                    "arm": result["arm"],
                    "wall_seconds": result["wall_seconds"],
                    "actual_evaluations": result["actual_evaluations"],
                }
            )
            objective = (
                "INFEASIBLE"
                if result["final_total_cost"] is None
                else f"{float(result['final_total_cost']):.6f}"
            )
            print(
                f"[{scale}] {completed}/{len(specs)} "
                f"seed={result['algorithm_seed']} arm={result['arm']} "
                f"status={status} cost={objective}",
                flush=True,
            )
    marker = {
        "schema": "resetp.china81.e7.scale-complete.v3",
        "task_id": TASK_ID,
        "status": f"COMPLETE_{scale}",
        "created_at_utc": LEGACY.now_iso(),
        "scale": scale,
        "instance_id": LEGACY.INSTANCE_BY_SCALE[scale],
        "task_count": len(specs),
        "feasible_task_count": feasible,
        "legal_infeasible_task_count": legal_infeasible,
        "per_search_pass_cap": cap,
        "per_stage_total_cap": 2 * cap,
        "protected_hashes": verify_protected_and_inputs(),
    }
    marker["marker_sha256"] = canonical_sha256(marker)
    LEGACY.atomic_json(HERE / "formal" / scale / "scale_complete.json", marker)
    LEGACY.append_progress(
        {
            "phase": f"formal-{scale}",
            "status": "COMPLETE",
            "unit_count": len(specs),
            "feasible_task_count": feasible,
            "legal_infeasible_task_count": legal_infeasible,
        }
    )
    return marker


def all_task_results() -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for scale in LEGACY.SCALES:
        for seed in range(1, 11):
            for arm in LEGACY.ARMS:
                path = LEGACY.task_path(scale, seed, arm)
                if not path.is_file():
                    raise RuntimeError(f"HALT_TASK_MISSING:{path}")
                task = read_json(path)
                if task.get("status") not in {"PASS", "LEGAL_INFEASIBLE"}:
                    raise RuntimeError(f"HALT_NONTERMINAL_TASK:{path}")
                tasks.append(task)
    return tasks


def raw_row(task: Mapping[str, Any]) -> dict[str, Any]:
    feasible = task["status"] == "PASS"
    charging_energy = (
        float(task["final_charging_energy_kwh"]) if feasible else None
    )
    weighted = (
        1000.0
        * float(task["final_actual_charging_emissions_kg"])
        / charging_energy
        if charging_energy is not None and charging_energy > TOL
        else None
    )
    nominal = float(task["nominal_total_cost"])
    final = float(task["final_total_cost"]) if feasible else None
    return {
        "instance_id": task["instance_id"],
        "scale": task["scale"],
        "seed": task["algorithm_seed"],
        "stream_seed": task["stream_seed"],
        "arm": task["arm"],
        "status": task["status"],
        "feasible": feasible,
        "nominal_total_cost_cny": nominal,
        "final_total_cost_cny": final,
        "cost_change_vs_nominal_pct": (
            100.0 * (final - nominal) / nominal if final is not None else None
        ),
        "vehicle_count": task["vehicle_count"],
        "wall_seconds": task["wall_seconds"],
        "actual_evaluations": task["actual_evaluations"],
        "per_stage_budget_cap": task["per_stage_total_cap"],
        "completed_stage_count": task.get(
            "completed_stage_count", task["stage_count"]
        ),
        "attempted_stage_count": task.get(
            "attempted_stage_count", task["stage_count"]
        ),
        "failure_stage": task.get("failure_stage"),
        "legal_infeasibility_reason": task.get("legal_infeasibility_reason"),
        "final_total_profit_cny": task["final_total_profit"],
        "final_actual_emissions_kg": task["final_actual_emissions_kg"],
        "final_actual_charging_emissions_kg":
            task["final_actual_charging_emissions_kg"],
        "charging_weighted_carbon_gco2_per_kwh": weighted,
        "cross_depot_reassignment_after_event":
            task["cross_depot_reassignment_after_event"],
        "new_cross_site_customer_count": (
            len(task["new_cross_site_customer_ids"]) if feasible else None
        ),
        "member_profit_shift_after_event":
            task["member_profit_shift_after_event"],
        "carbon_aware_charging_shift_after_event":
            task["carbon_aware_charging_shift_after_event"],
        "moved_charge_actions_after_event":
            task["moved_charge_actions_after_event"],
        "event_sha256": task["event_sha256"],
        "nominal_plan_sha256": task["nominal_plan_sha256"],
        "result_sha256": task["result_sha256"],
    }


def paired_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    indexed = {
        (str(row["scale"]), int(row["seed"]), str(row["arm"])): row
        for row in rows
    }
    output: list[dict[str, Any]] = []
    for scale in LEGACY.SCALES:
        for seed in range(1, 11):
            static = indexed[(scale, seed, "STATIC_FIXED_RECOURSE")]
            full = indexed[(scale, seed, "FULL_ROLLING")]
            nominal = float(static["nominal_total_cost_cny"])
            static_cost = static["final_total_cost_cny"]
            full_cost = full["final_total_cost_cny"]
            computable = static_cost is not None and full_cost is not None
            loss = float(static_cost) - nominal if computable else None
            output.append(
                {
                    "scale": scale,
                    "instance_id": static["instance_id"],
                    "seed": seed,
                    "stream_seed": static["stream_seed"],
                    "static_status": static["status"],
                    "full_rolling_status": full["status"],
                    "computable_pair": computable,
                    "nominal_cost_cny": nominal,
                    "static_actual_cost_cny": static_cost,
                    "full_dynamic_cost_cny": full_cost,
                    "static_degradation_pct": (
                        100.0 * loss / nominal if loss is not None else None
                    ),
                    "dynamic_saving_vs_static_pct": (
                        100.0
                        * (float(static_cost) - float(full_cost))
                        / float(static_cost)
                        if computable
                        else None
                    ),
                    "dynamic_recovery_pct": (
                        100.0
                        * (float(static_cost) - float(full_cost))
                        / loss
                        if loss is not None and abs(loss) > TOL
                        else None
                    ),
                }
            )
    return output


def load_task_rows() -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    tasks = all_task_results()
    rows = [raw_row(task) for task in tasks]
    if len(rows) != 120:
        raise RuntimeError(f"HALT_MATRIX_INCOMPLETE:{len(rows)}")
    paired = paired_metrics(rows)
    if len(paired) != 30:
        raise RuntimeError(f"HALT_PAIRED_MATRIX_INCOMPLETE:{len(paired)}")
    return tasks, rows, paired


def arm_summary(tasks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for task in tasks:
        grouped[(str(task["scale"]), str(task["arm"]))].append(task)
    output: list[dict[str, Any]] = []
    for scale in LEGACY.SCALES:
        row: dict[str, Any] = {
            "scale": scale,
            "instance_id": LEGACY.INSTANCE_BY_SCALE[scale],
        }
        for arm in LEGACY.ARMS:
            group = grouped[(scale, arm)]
            feasible = [item for item in group if item["status"] == "PASS"]
            costs = [float(item["final_total_cost"]) for item in feasible]
            best = min(costs) if costs else None
            average = statistics.fmean(costs) if costs else None
            prefix = arm.lower()
            row[f"{prefix}_total_runs"] = len(group)
            row[f"{prefix}_feasible_runs"] = len(feasible)
            row[f"{prefix}_legal_infeasible_runs"] = (
                len(group) - len(feasible)
            )
            row[f"{prefix}_best_cny"] = best
            row[f"{prefix}_avg_cny"] = average
            row[f"{prefix}_gap_pct"] = (
                100.0 * (average - best) / best
                if average is not None and best is not None
                else None
            )
            row[f"{prefix}_avg_vehicle_count"] = (
                statistics.fmean(
                    float(item["vehicle_count"]) for item in feasible
                )
                if feasible
                else None
            )
            row[f"{prefix}_avg_time_seconds"] = statistics.fmean(
                float(item["wall_seconds"]) for item in group
            )
            row[f"{prefix}_avg_actual_evaluations"] = statistics.fmean(
                float(item["actual_evaluations"]) for item in group
            )
        output.append(row)
    return output


def scale_dynamic_summary(
    paired: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for scale in LEGACY.SCALES:
        group = [row for row in paired if row["scale"] == scale]
        computable = [row for row in group if row["computable_pair"]]
        recoveries = [
            float(row["dynamic_recovery_pct"])
            for row in computable
            if row["dynamic_recovery_pct"] is not None
        ]
        output.append(
            {
                "scale": scale,
                "instance_id": LEGACY.INSTANCE_BY_SCALE[scale],
                "paired_units": len(group),
                "computable_pairs": len(computable),
                "static_legal_infeasible_units": sum(
                    row["static_status"] == "LEGAL_INFEASIBLE"
                    for row in group
                ),
                "full_legal_infeasible_units": sum(
                    row["full_rolling_status"] == "LEGAL_INFEASIBLE"
                    for row in group
                ),
                "static_degradation_pct": (
                    statistics.fmean(
                        float(row["static_degradation_pct"])
                        for row in computable
                    )
                    if computable
                    else None
                ),
                "dynamic_saving_vs_static_pct": (
                    statistics.fmean(
                        float(row["dynamic_saving_vs_static_pct"])
                        for row in computable
                    )
                    if computable
                    else None
                ),
                "dynamic_recovery_pct": (
                    statistics.fmean(recoveries) if recoveries else None
                ),
                "recovery_denominator_nonzero_units": len(recoveries),
            }
        )
    return output


def mechanism_summary(
    tasks: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for scale in LEGACY.SCALES:
        all_full = [
            task
            for task in tasks
            if task["scale"] == scale and task["arm"] == "FULL_ROLLING"
        ]
        full = [
            task
            for task in all_full
            if task["status"] == "PASS"
        ]
        blind = {
            int(task["algorithm_seed"]): task
            for task in tasks
            if (
                task["scale"] == scale
                and task["arm"] == "CARBON_BLIND"
                and task["status"] == "PASS"
            )
        }
        profit_l1: list[float] = []
        rank_changes = 0
        minimum_margins: list[float] = []
        moved_kwh = 0.0
        aware_lower = 0
        carbon_pairs = 0
        for task in full:
            nominal = {
                str(key): float(value)
                for key, value in task["nominal_depot_profit"].items()
            }
            final = {
                str(key): float(value)
                for key, value in task["final_depot_profit"].items()
            }
            depots = sorted(set(nominal) | set(final))
            profit_l1.append(
                sum(abs(final.get(key, 0.0) - nominal.get(key, 0.0)) for key in depots)
            )
            if sorted(nominal, key=nominal.get) != sorted(final, key=final.get):
                rank_changes += 1
            minimum_margins.extend(
                float(row["minimum_profit_margin"])
                for row in task["payload"]["rows"]
            )
            moved_kwh += sum(
                float(row["aware_vs_immediate_moved_energy_kwh"])
                for row in task["payload"]["rows"]
            )
            blind_task = blind.get(int(task["algorithm_seed"]))
            if blind_task is None:
                continue
            carbon_pairs += 1
            aware_energy = float(task["final_charging_energy_kwh"])
            blind_energy = float(blind_task["final_charging_energy_kwh"])
            aware_intensity = (
                1000.0
                * float(task["final_actual_charging_emissions_kg"])
                / aware_energy
                if aware_energy > TOL
                else None
            )
            blind_intensity = (
                1000.0
                * float(blind_task["final_actual_charging_emissions_kg"])
                / blind_energy
                if blind_energy > TOL
                else None
            )
            if (
                aware_intensity is not None
                and blind_intensity is not None
                and aware_intensity < blind_intensity - TOL
            ):
                aware_lower += 1
        output.append(
            {
                "scale": scale,
                "instance_id": LEGACY.INSTANCE_BY_SCALE[scale],
                "full_rolling_total_units": len(all_full),
                "full_rolling_units": len(full),
                "full_rolling_legal_infeasible_units": len(all_full) - len(full),
                "cross_reassignment_units": sum(
                    bool(task["cross_depot_reassignment_after_event"])
                    for task in full
                ),
                "new_cross_site_customer_count": sum(
                    len(task["new_cross_site_customer_ids"]) for task in full
                ),
                "member_profit_shift_units": sum(
                    bool(task["member_profit_shift_after_event"])
                    for task in full
                ),
                "member_profit_rank_change_units": rank_changes,
                "mean_member_profit_l1_shift_cny": (
                    statistics.fmean(profit_l1) if profit_l1 else None
                ),
                "minimum_stage_participation_margin_cny": (
                    min(minimum_margins) if minimum_margins else None
                ),
                "carbon_timing_shift_units": sum(
                    bool(task["carbon_aware_charging_shift_after_event"])
                    for task in full
                ),
                "moved_charge_action_count": sum(
                    int(task["moved_charge_actions_after_event"]) for task in full
                ),
                "moved_charge_energy_kwh": moved_kwh,
                "aware_blind_computable_pairs": carbon_pairs,
                "aware_lower_weighted_carbon_than_blind_units": aware_lower,
            }
        )
    overall = {
        "cross_depot_reassignment": any(
            row["cross_reassignment_units"] > 0 for row in output
        ),
        "member_profit_shift": any(
            row["member_profit_shift_units"] > 0 for row in output
        ),
        "carbon_aware_charging_shift": (
            any(row["carbon_timing_shift_units"] > 0 for row in output)
            and any(
                row["aware_lower_weighted_carbon_than_blind_units"] > 0
                for row in output
            )
        ),
        "cross_reassignment_cell_count": sum(
            row["cross_reassignment_units"] for row in output
        ),
        "profit_shift_cell_count": sum(
            row["member_profit_shift_units"] for row in output
        ),
        "charging_shift_cell_count": sum(
            row["carbon_timing_shift_units"] for row in output
        ),
        "aware_lower_than_blind_cell_count": sum(
            row["aware_lower_weighted_carbon_than_blind_units"]
            for row in output
        ),
        "full_rolling_terminal_cell_count": sum(
            row["full_rolling_units"] for row in output
        ),
        "full_rolling_legal_infeasible_cell_count": sum(
            row["full_rolling_legal_infeasible_units"] for row in output
        ),
        "aware_blind_computable_pair_count": sum(
            row["aware_blind_computable_pairs"] for row in output
        ),
    }
    return output, overall


def number_or_na(value: Any, digits: int = 2) -> str:
    return "NA" if value is None else f"{float(value):.{digits}f}"


def arm_cell(row: Mapping[str, Any], arm: str) -> str:
    prefix = arm.lower()
    return (
        f"{int(row[f'{prefix}_feasible_runs'])}/"
        f"{int(row[f'{prefix}_total_runs'])}; "
        f"{number_or_na(row[f'{prefix}_best_cny'])} / "
        f"{number_or_na(row[f'{prefix}_avg_cny'])} / "
        f"{number_or_na(row[f'{prefix}_gap_pct'])}% / "
        f"{number_or_na(row[f'{prefix}_avg_vehicle_count'])} / "
        f"{number_or_na(row[f'{prefix}_avg_time_seconds'])} / "
        f"{number_or_na(row[f'{prefix}_avg_actual_evaluations'], 1)}"
    )


def render_final_report(
    selfcheck: Mapping[str, Any],
    lock: Mapping[str, Any],
    main_rows: Sequence[Mapping[str, Any]],
    dynamic_rows: Sequence[Mapping[str, Any]],
    mechanism_rows: Sequence[Mapping[str, Any]],
    mechanism: Mapping[str, Any],
    decision: Mapping[str, Any],
    independent: Mapping[str, Any],
) -> str:
    lines = [
        "# E7 动态需求压力测试",
        "",
        "状态：`COMPLETE`。3 个冻结算例依次完成，四臂各运行 10 个算法种子；"
        "5 条冻结事件流按 `1 + ((seed - 1) mod 5)` 各复用两次，共 120 个实验单元。",
        "统计单位为算例—算法种子—实验臂；排除单元为 0。",
        "",
        "## 启动接线与预算",
        "",
        f"零搜索自检共登记 {selfcheck['wiring_issues_found']} 项接线问题，"
        "全部修复并通过回归检查。China81 八源文件字段、显式 prices、"
        "2025-02-11/12 双日电网曲线和 `actual_evaluations` 字段已闭合；"
        "四臂最小模型评价均取得有限目标值，硬违反为 0，搜索评价数为 0。",
        "",
        "启动历史按发生顺序保留：v1 的 `instance_json` 路径键和 v2 的 "
        "prices/offset −1 日历契约均在搜索前终止；v3 依次修复整趟路线电量"
        "释放、在途充电见证、当前目标绑定、spawn 模块身份、合法不可行终态"
        "分类和 trace-mode 门。已知失败尝试的搜索消费依次为 "
        "0、0、0、0、400、0、0；trace-mode 尝试消费未被旧诊断层落盘，"
        "单 pass 上界为 600；专用不可执行续解尝试的阶段上界为 1200。",
        "",
        f"收敛探针在 50c、算法种子 1、事件流 1、FULL_ROLLING 第一阶段运行。"
        f"正式预算为每个搜索 pass 上限 "
        f"{int(lock['selected_per_search_pass_cap'])}，每阶段双 pass 总上限 "
        f"{int(lock['selected_total_stage_cap'])}。该值为上限，提前耗尽候选或"
        "提前停止均按实际评价数记录。",
        "",
        "## 期刊式主表",
        "",
        "表内每格依次为可行数/10；Best / Avg / Gap% / 车辆数 / "
        "时间(s) / 实际评价数。成本、Gap 和车辆数按可行终局统计，时间与"
        "实际评价数按全部 10 个单元统计；每行对应一个冻结算例。",
        "",
        "| 算例 | STATIC_FIXED_RECOURSE | FULL_ROLLING | NO_COOPERATION | CARBON_BLIND |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in main_rows:
        lines.append(
            f"| {row['instance_id']} | "
            f"{arm_cell(row, 'STATIC_FIXED_RECOURSE')} | "
            f"{arm_cell(row, 'FULL_ROLLING')} | "
            f"{arm_cell(row, 'NO_COOPERATION')} | "
            f"{arm_cell(row, 'CARBON_BLIND')} |"
        )
    lines.extend(
        [
            "",
            "## 动态性主问题",
            "",
            "| 算例 | 配对单元 | 可计算配对 | 静态不可行 | 动态不可行 | "
            "静态成本变化% | 动态相对静态节省% | 动态挽回% |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in dynamic_rows:
        lines.append(
            f"| {row['instance_id']} | {row['paired_units']} | "
            f"{row['computable_pairs']} | "
            f"{row['static_legal_infeasible_units']} | "
            f"{row['full_legal_infeasible_units']} | "
            f"{number_or_na(row['static_degradation_pct'], 6)} | "
            f"{number_or_na(row['dynamic_saving_vs_static_pct'], 6)} | "
            f"{number_or_na(row['dynamic_recovery_pct'], 6)} |"
        )
    lines.append("")
    if decision["computable_paired_rows"]:
        lines.append(
            f"{decision['computable_paired_rows']} 个可计算配对单元等权平均下，"
            "扰动后固定路线方案的成本相对扰动前变化 "
            f"{number_or_na(decision['static_degradation_pct'], 6)}%；"
            "FULL_ROLLING 相对固定路线实际方案节省 "
            f"{number_or_na(decision['dynamic_saving_vs_static_pct'], 6)}%，"
            "动态挽回率为 "
            f"{number_or_na(decision['dynamic_recovery_pct'], 6)}%。"
        )
    else:
        lines.append(
            f"固定路线臂在 {decision['static_legal_infeasible_rows']}/30 个"
            "配对单元中均无可执行终局，静态成本变化、动态相对静态节省和"
            "动态挽回率没有有限数值。"
        )
    lines.extend(
        [
            "",
            "## 机制参与",
            "",
            "| 算例 | 跨场重分配单元 | 新跨场客户 | 收益变化单元 | 收益排序变化单元 | "
            "平均收益 L1 变化(CNY) | 最小参与余量(CNY) | 终局数 | "
            "充电移动单元 | 移动动作 | 移动电量(kWh) | "
            "碳强度优于 CARBON_BLIND 单元 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in mechanism_rows:
        lines.append(
            f"| {row['instance_id']} | {row['cross_reassignment_units']} | "
            f"{row['new_cross_site_customer_count']} | "
            f"{row['member_profit_shift_units']} | "
            f"{row['member_profit_rank_change_units']} | "
            f"{number_or_na(row['mean_member_profit_l1_shift_cny'], 6)} | "
            f"{number_or_na(row['minimum_stage_participation_margin_cny'], 6)} | "
            f"{row['full_rolling_units']}/10 | "
            f"{row['carbon_timing_shift_units']} | "
            f"{row['moved_charge_action_count']} | "
            f"{float(row['moved_charge_energy_kwh']):.6f} | "
            f"{row['aware_lower_weighted_carbon_than_blind_units']} |"
        )
    lines.extend(
        [
            "",
            "跨场责任重新分配："
            f"`{str(bool(mechanism['cross_depot_reassignment'])).lower()}`，"
            f"发生于 {mechanism['cross_reassignment_cell_count']}/"
            f"{mechanism['full_rolling_terminal_cell_count']} 个有完整终局的 "
            "FULL_ROLLING 单元。成员收益格局变化："
            f"`{str(bool(mechanism['member_profit_shift'])).lower()}`，"
            f"发生于 {mechanism['profit_shift_cell_count']}/"
            f"{mechanism['full_rolling_terminal_cell_count']} 个单元。"
            "碳感知充电时刻调整："
            f"`{str(bool(mechanism['carbon_aware_charging_shift'])).lower()}`，"
            f"发生于 {mechanism['charging_shift_cell_count']}/"
            f"{mechanism['full_rolling_terminal_cell_count']} 个单元，"
            f"其中 {mechanism['aware_lower_than_blind_cell_count']}/"
            f"{mechanism['aware_blind_computable_pair_count']} 个可比单元的"
            "充电加权碳强度低于 CARBON_BLIND。",
            "",
            "## 独立复算",
            "",
            f"独立复算覆盖 {independent['task_count']} 个任务、"
            f"其中 {independent['feasible_task_count']} 个完整终局、"
            f"{independent['legal_infeasible_task_count']} 个合法不可行终态；"
            f"{independent['recomputed_cost_count']} 次终局成本评价和"
            f"{independent['recomputed_profit_count']} 次收益闭合；"
            f"最大成本绝对差为 {float(independent['max_cost_abs_diff']):.12g} CNY，"
            f"最大收益绝对差为 {float(independent['max_profit_abs_diff']):.12g} CNY，"
            "客户覆盖、预算上限、任务哈希与六个保护哈希全部闭合。",
            "",
            "## 全文脉络与正文表述",
            "",
            "E3 的 40 个 ZONE–JOINT 单元中，JOINT 平均节省 1.482937%；"
            "50c 的里程和碳排分别增加 28.04% 与 4.04%，100c 分别增加 "
            "12.18% 与 1.18%，车辆数由 9 降至 8、由 18 降至 17.2。"
            "E6 的自然帕累托为 0/20；无转移支付时 F 在 20/20 单元回退到 I，"
            "公平代价为 1.511784%；事后转移支付下 19/20 单元存在双方均获益的"
            "核内分配。E5 的非线性充电效应为 0.000%，可行率 100%，假可行为 "
            "0/20。E4 的碳感知充电使充电排放下降 54.9704%、系统排放下降 "
            "9.7463%，同时电费增加 134.8798%、系统总成本增加 1.8454%。",
            "",
            "E7 将协同重分配、成员参与和时变充电置于同一不可撤回执行过程。"
            f"固定路线臂产生 {decision['static_legal_infeasible_rows']}/30 个"
            "合法不可行终态；"
            f"{decision['computable_paired_rows']} 个单元同时取得固定路线与"
            "滚动重规划有限终局。静态成本变化、动态相对静态节省和动态挽回率"
            f"分别为 {number_or_na(decision['static_degradation_pct'], 2)}%、"
            f"{number_or_na(decision['dynamic_saving_vs_static_pct'], 2)}% 和 "
            f"{number_or_na(decision['dynamic_recovery_pct'], 2)}%。"
            "50c/100c 使用 E3 封存 JOINT 解；150c 使用 foundation 冻结 common "
            "initial solution，统计角色为大规模压力稳健性算例。",
            "",
            "## 正文图表取舍",
            "",
            "建议正文保留三项。第一，四臂主表一行一算例，直接承载期刊要求的"
            "Best、Avg、Gap%、车辆数、时间和评价数，删除后四臂性能缺少统一"
            "可核对载体。第二，动态性配对表直接给出静态成本变化、动态节省与"
            "挽回率，承担核心研究问题。第三，机制参与表同时给出责任、收益与"
            "充电三条机制的发生频数和幅度，承担机制识别。",
            "",
            "建议正文增加一幅 30 单元终态矩阵图，横轴为种子、纵轴为规模，"
            "并列标识 STATIC_FIXED_RECOURSE 与 FULL_ROLLING 的有限终局或"
            "合法不可行；它直接展示动态策略是否把冻结扰动转化为可执行终局。"
            "收敛轨迹、逐阶段日志、资源负载、各 seed "
            "终局轨迹和完整候选空值序列保留在交付目录，作为复核档案。",
            "",
            "## 数据口径",
            "",
            "样本量为 3 个冻结算例 × 10 个算法种子 × 4 个实验臂。事件流共 "
            "15 条，每条在对应规模内使用两次；比较基准为同 seed 的扰动前"
            "冻结名义方案和 STATIC_FIXED_RECOURSE。评价空值按合法技术不可行"
            "候选计入实际消费；合法不可行任务保留在可行率和时间/评价数统计，"
            "有限成本统计使用取得完整终局的单元。所有 120 个单元进入统计，"
            "排除数为 0。",
            "",
        ]
    )
    return "\n".join(lines)


def is_manifest_artifact(path: Path) -> bool:
    if not path.is_file() or path.name.startswith("._"):
        return False
    parts = path.relative_to(HERE).parts
    excluded_parts = {
        "__pycache__",
        ".pytest_cache",
        "monitor_runtime",
        "monitor_runs",
    }
    return not any(part in excluded_parts for part in parts)


def collect_hashes() -> dict[str, str]:
    excluded_names = {"artifact_hashes.json", "done.json"}
    return {
        str(path.relative_to(HERE)): sha256(path)
        for path in sorted(HERE.rglob("*"))
        if is_manifest_artifact(path) and path.name not in excluded_names
    }


def finalize() -> dict[str, Any]:
    verify_protected_and_inputs()
    for scale in LEGACY.SCALES:
        marker = HERE / "formal" / scale / "scale_complete.json"
        if not marker.is_file():
            raise RuntimeError(f"HALT_SCALE_INCOMPLETE:{scale}")
    independent_path = HERE / "independent_verification.json"
    if not independent_path.is_file():
        raise RuntimeError("HALT_INDEPENDENT_VERIFICATION_MISSING")
    independent = read_json(independent_path)
    if independent.get("status") != "PASS_INDEPENDENT_RECOMPUTATION":
        raise RuntimeError("HALT_INDEPENDENT_VERIFICATION_NONPASS")
    tasks, raw_rows, paired = load_task_rows()
    main_rows = arm_summary(tasks)
    dynamic_rows = scale_dynamic_summary(paired)
    mechanism_rows, mechanism = mechanism_summary(tasks)
    LEGACY.atomic_csv(HERE / "raw_runs.csv", raw_rows)
    LEGACY.atomic_csv(HERE / "paired_dynamic_metrics.csv", paired)
    LEGACY.atomic_csv(HERE / "table_main.csv", main_rows)
    LEGACY.atomic_csv(HERE / "table_dynamic_question.csv", dynamic_rows)
    LEGACY.atomic_csv(HERE / "table_mechanism_participation.csv", mechanism_rows)
    computable = [row for row in paired if row["computable_pair"]]
    static_degradation = (
        statistics.fmean(
            float(row["static_degradation_pct"]) for row in computable
        )
        if computable
        else None
    )
    dynamic_saving = (
        statistics.fmean(
            float(row["dynamic_saving_vs_static_pct"]) for row in computable
        )
        if computable
        else None
    )
    recoveries = [
        float(row["dynamic_recovery_pct"])
        for row in paired
        if row["dynamic_recovery_pct"] is not None
    ]
    dynamic_recovery = statistics.fmean(recoveries) if recoveries else None
    status_counts = Counter(str(task["status"]) for task in tasks)
    decision = {
        "schema": "resetp.china81.e7.decision.v3",
        "task_id": TASK_ID,
        "status": "COMPLETE",
        "verdict": "VALID_DYNAMIC_PRESSURE_RESULT",
        "statistical_unit": "instance_algorithm_seed_arm",
        "matrix_rows": len(raw_rows),
        "paired_rows": len(paired),
        "computable_paired_rows": len(computable),
        "static_legal_infeasible_rows": sum(
            row["static_status"] == "LEGAL_INFEASIBLE" for row in paired
        ),
        "full_rolling_legal_infeasible_rows": sum(
            row["full_rolling_status"] == "LEGAL_INFEASIBLE" for row in paired
        ),
        "feasible_task_rows": status_counts["PASS"],
        "legal_infeasible_task_rows": status_counts["LEGAL_INFEASIBLE"],
        "excluded_units": 0,
        "static_degradation_pct": static_degradation,
        "dynamic_saving_vs_static_pct": dynamic_saving,
        "dynamic_recovery_pct": dynamic_recovery,
        "mechanism_participation": mechanism,
    }
    decision["decision_sha256"] = canonical_sha256(decision)
    selfcheck = read_json(HERE / "wiring_selfcheck.json")
    lock = read_json(HERE / "budget_lock.json")
    report = render_final_report(
        selfcheck,
        lock,
        main_rows,
        dynamic_rows,
        mechanism_rows,
        mechanism,
        decision,
        independent,
    )
    (HERE / "report.md").write_text(report, encoding="utf-8")
    metadata = {
        "schema": "resetp.china81.e7.metadata.v3",
        "task_id": TASK_ID,
        "status": "COMPLETE",
        "created_at_utc": LEGACY.now_iso(),
        "instances": [
            LEGACY.INSTANCE_BY_SCALE[scale] for scale in LEGACY.SCALES
        ],
        "arms": list(LEGACY.ARMS),
        "seeds": list(range(1, 11)),
        "event_streams_found": 15,
        "workers_maximum": FORMAL_MAX_WORKERS,
        "formal_workers_used": FORMAL_DEFAULT_WORKERS,
        "thread_environment": LEGACY.REQUIRED_THREAD_ENV,
        "budget_lock": lock,
        "wiring_selfcheck": {
            "all_green": True,
            "issues_found": selfcheck["wiring_issues_found"],
            "sha256": sha256(HERE / "wiring_selfcheck.json"),
        },
        "independent_verification_sha256": sha256(independent_path),
        "protected_hashes": verify_protected_and_inputs(),
        "source_hashes": LEGACY.source_hashes(),
        "input_hashes": selfcheck["input_sha256"],
        "matrix_rows": len(raw_rows),
        "paired_rows": len(paired),
        "computable_paired_rows": len(computable),
        "feasible_task_rows": status_counts["PASS"],
        "legal_infeasible_task_rows": status_counts["LEGAL_INFEASIBLE"],
        "excluded_units": 0,
        "mechanism_participation": mechanism,
    }
    metadata["metadata_sha256"] = canonical_sha256(metadata)
    LEGACY.atomic_json(HERE / "metadata.json", metadata)
    LEGACY.atomic_json(HERE / "decision.json", decision)
    hashes = {
        "schema": "resetp.china81.e7.artifact-hashes.v3",
        "task_id": TASK_ID,
        "excluded": [
            "artifact_hashes.json",
            "done.json",
            "._*",
            "__pycache__",
            ".pytest_cache",
            "monitor_runtime",
            "monitor_runs",
        ],
        "files": collect_hashes(),
    }
    hashes["manifest_sha256"] = canonical_sha256(hashes["files"])
    LEGACY.atomic_json(HERE / "artifact_hashes.json", hashes)
    return {
        "metadata": metadata,
        "decision": decision,
        "artifact_hashes": hashes,
    }


def write_done() -> dict[str, Any]:
    verify_protected_and_inputs()
    required = (
        "pre_registration.json",
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
        "independent_verification.json",
    )
    missing = [name for name in required if not (HERE / name).is_file()]
    if missing:
        raise RuntimeError(f"HALT_FINAL_ARTIFACTS_MISSING:{missing}")
    decision = read_json(HERE / "decision.json")
    lock = read_json(HERE / "budget_lock.json")
    selfcheck = read_json(HERE / "wiring_selfcheck.json")
    done = {
        "status": "COMPLETE",
        "wiring_selfcheck_all_green": bool(
            selfcheck["wiring_selfcheck_all_green"]
        ),
        "wiring_issues_found": int(selfcheck["wiring_issues_found"]),
        "arms": list(LEGACY.ARMS),
        "instances_completed": [
            LEGACY.INSTANCE_BY_SCALE[scale] for scale in LEGACY.SCALES
        ],
        "seeds": 10,
        "budget_cap": int(lock["selected_total_stage_cap"]),
        "static_degradation_pct": decision["static_degradation_pct"],
        "dynamic_recovery_pct": decision["dynamic_recovery_pct"],
        "mechanism_participation": {
            "cross_depot_reassignment": bool(
                decision["mechanism_participation"][
                    "cross_depot_reassignment"
                ]
            ),
            "member_profit_shift": bool(
                decision["mechanism_participation"]["member_profit_shift"]
            ),
            "carbon_aware_charging_shift": bool(
                decision["mechanism_participation"][
                    "carbon_aware_charging_shift"
                ]
            ),
        },
        "decision_sha256": sha256(HERE / "decision.json"),
        "artifact_hashes_sha256": sha256(HERE / "artifact_hashes.json"),
    }
    done["done_sha256"] = canonical_sha256(done)
    LEGACY.atomic_json(HERE / "done.json", done)
    return done


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    selfcheck_parser = sub.add_parser("selfcheck")
    selfcheck_parser.add_argument("--workers", type=int, default=2)
    sub.add_parser("probe")
    formal_parser = sub.add_parser("formal")
    formal_parser.add_argument("--scale", choices=LEGACY.SCALES, required=True)
    formal_parser.add_argument(
        "--workers", type=int, default=FORMAL_DEFAULT_WORKERS
    )
    sub.add_parser("finalize")
    sub.add_parser("write-done")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "selfcheck":
        output = run_wiring_selfcheck(args.workers)
    elif args.command == "probe":
        output = run_probe()
    elif args.command == "formal":
        output = run_formal(args.scale, args.workers)
    elif args.command == "finalize":
        output = finalize()["decision"]
    elif args.command == "write-done":
        output = write_done()
    else:
        raise AssertionError(args.command)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
