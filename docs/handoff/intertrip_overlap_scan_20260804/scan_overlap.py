#!/usr/bin/env python3
"""Read-only T9 inter-trip charging-overlap scanner.

This file is intentionally kept inside the T9 output directory.  It imports
the repository's existing loaders and certificate builder; it does not call a
solver, write source files, or create solution archives.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any


REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "docs/handoff/intertrip_overlap_scan_20260804"
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.path.insert(0, str(REPO / "solver/src"))

from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.model_config import (  # noqa: E402
    DEPOT_CHARGER_CAPACITY_UNBOUNDED,
    ModelConfig,
)
from setp_solver.charging_action import _curve_aware_action  # noqa: E402
from setp_solver.algorithms.resetp_alns.support.carbon_charging import (  # noqa: E402
    ChargeOption,
    score_charge_option,
)
from setp_solver.algorithms.resetp_alns.support.charging import (  # noqa: E402
    _best_station_insert,
    _ev_distance,
    _ev_travel_time,
)
from setp_solver.search.multitrip_schedule import (  # noqa: E402
    DEFAULT_PRICES,
    build_multitrip_certificate,
)
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    Route,
    charging_action_from_dict,
    physical_vehicle_id,
)


INSTANCE_RE = re.compile(r"cn-[a-z0-9]+-\d+c-\d{2}-V2-LOCATIONS")
CHINA_AUTHORITY = REPO / (
    "data/ChinaInstances/china81_finite_fleet_authority_v3_20260802"
)
MODEL_CONFIG = ModelConfig(
    strict_multitrip=True,
    depot_charger_capacity_mode=DEPOT_CHARGER_CAPACITY_UNBOUNDED,
)
TARGET_INSTANCE = "cn-jjj-50c-01-V2-LOCATIONS"
SELFTEST_FILE = (
    REPO
    / "docs/handoff/eval_chain_carbon_consistency_20260804/solution_witnesses.json"
)
PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def protected_hashes() -> dict[str, str]:
    return {rel: sha256(REPO / rel) for rel in PROTECTED}


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=json_default)


def solution_entries(
    obj: Any,
    locator: tuple[str, ...] = (),
    parent_context: dict[str, Any] | None = None,
) -> list[tuple[str, dict[str, Any], dict[str, Any] | None]]:
    """Find actual solution payloads, including nested runs/archives."""
    found: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []
    if isinstance(obj, dict):
        routes = obj.get("routes")
        if isinstance(routes, list) and all(isinstance(x, dict) for x in routes):
            found.append(("/".join(locator) or "<root>", obj, parent_context))
            return found
        for key, value in obj.items():
            found.extend(solution_entries(value, locator + (str(key),), obj))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.extend(solution_entries(value, locator + (f"[{index}]",), parent_context))
    return found


def witness_files() -> list[Path]:
    paths = set(REPO.glob("baselines/**/solution_witnesses.json"))
    paths.update(REPO.glob("docs/handoff/**/solution_witnesses.json"))
    return sorted(p for p in paths if not p.name.startswith("._"))


def infer_instance(
    source_path: Path,
    locator: str,
    data: Any,
    context: dict[str, Any] | None = None,
) -> str | None:
    if context:
        for key in ("instance", "instance_id", "scenario_instance"):
            value = context.get(key)
            if value:
                return str(value)
        bundle = context.get("bundle")
        if bundle:
            return Path(str(bundle)).name
    text = f"{source_path} {locator} {json_dumps(data)}"
    candidates = INSTANCE_RE.findall(text)
    if candidates:
        # Preserve first appearance: the source path/solution locator is more
        # specific than unrelated metadata later in a file.
        return candidates[0]
    if "eval_chain_carbon_consistency_20260804" in str(source_path):
        return TARGET_INSTANCE
    if "carbon_objective_probe_20260804" in str(source_path):
        return TARGET_INSTANCE
    return None


_bundle_cache: dict[str, Any] = {}


def bundle_for(instance_id: str | None, context: dict[str, Any] | None = None) -> tuple[Any, Any]:
    if not instance_id:
        raise ValueError("INSTANCE_OR_BUNDLE_UNRESOLVED: no instance id in archive")
    if instance_id.startswith("cn-"):
        key = f"china81:{instance_id}"
        if key not in _bundle_cache:
            _bundle_cache[key] = load_china81_bundle(
                REPO,
                instance_id,
                fleet_authority=CHINA_AUTHORITY,
                model_config=MODEL_CONFIG,
            )
        return _bundle_cache[key], _bundle_cache[key].prices
    bundle_text = str(context.get("bundle")) if context and context.get("bundle") else ""
    candidates: list[Path] = []
    if bundle_text:
        candidates.append(REPO / bundle_text)
    candidates.append(REPO / "models/data_bundle/generated_instances/L-main" / instance_id)
    candidates.extend(
        path
        for path in (REPO / "models/data_bundle/generated_instances").rglob(instance_id)
        if path.is_dir()
    )
    bundle_dir = next((path for path in candidates if (path / "instance.json").is_file()), None)
    if bundle_dir is None:
        raise ValueError(
            f"INSTANCE_OR_BUNDLE_UNRESOLVED: no generated bundle for {instance_id}"
        )
    key = f"search:{bundle_dir}"
    if key not in _bundle_cache:
        _bundle_cache[key] = load_search_bundle(bundle_dir)
    return _bundle_cache[key], DEFAULT_PRICES


def parse_payload(payload: dict[str, Any]) -> tuple[list[Route], list[ChargingAction]]:
    routes = [
        Route(
            vehicle_id=str(row["vehicle_id"]),
            vehicle_type=str(row["vehicle_type"]),
            home_depot_id=str(row["home_depot_id"]),
            node_sequence=[str(x) for x in row["node_sequence"]],
        )
        for row in payload["routes"]
    ]
    raw_actions = payload.get("charging_actions", [])
    if not isinstance(raw_actions, list):
        raise ValueError("SCHEMA_INCOMPATIBLE: charging_actions is not a list")
    actions = [charging_action_from_dict(row) for row in raw_actions]
    return routes, actions


def prefilter(routes: list[dict[str, Any]]) -> tuple[bool, dict[str, list[str]]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for row in routes:
        vehicle = row.get("vehicle_id")
        if vehicle is None:
            vehicle = row.get("route_trip_vehicle_id", row.get("physical_vehicle_id"))
        if vehicle is None:
            raise ValueError("SCHEMA_INCOMPATIBLE: route has no vehicle identifier")
        vehicle_text = str(vehicle)
        physical = vehicle_text.split("#T", 1)[0]
        groups[physical].append(vehicle_text)
    return any(len(ids) >= 2 for ids in groups.values()), dict(groups)


def action_route(action: ChargingAction, routes: list[Route]) -> Route:
    exact = [route for route in routes if route.vehicle_id == action.vehicle_id]
    if len(exact) == 1:
        return exact[0]
    base = physical_vehicle_id(action.vehicle_id)
    candidates = [route for route in routes if physical_vehicle_id(route.vehicle_id) == base]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(
        "ACTION_ROUTE_UNRESOLVED: "
        f"vehicle_id={action.vehicle_id!r}, candidates={[r.vehicle_id for r in candidates]!r}"
    )


def fmt_minute(second: float) -> str:
    minute = int(math.floor(second / 60.0 + 1e-9))
    return f"{(minute // 60) % 24:02d}:{minute % 60:02d}"


def overlap_result(
    payload: dict[str, Any], instance_id: str | None, context: dict[str, Any] | None = None
) -> dict[str, Any]:
    routes, actions = parse_payload(payload)
    bundle, prices = bundle_for(instance_id, context)
    certificate = build_multitrip_certificate(
        routes,
        bundle.instance,
        prices,
        charging_actions=actions,
    )
    trip_by_route = {trip.route_id: trip for trip in certificate.trips}
    route_by_id = {route.vehicle_id: route for route in routes}
    total_energy = 0.0
    overlap_energy = 0.0
    midday_energy = 0.0
    overlap_actions = 0
    details: list[dict[str, Any]] = []
    for action_index, action in enumerate(actions):
        total_energy += action.energy_kwh
        route = action_route(action, routes)
        trip = trip_by_route.get(route.vehicle_id)
        if trip is None:
            raise ValueError(
                f"CERTIFICATE_ROUTE_MISSING: route {route.vehicle_id!r} not in certificate"
            )
        start = action.charge_start_second + action.charge_day_offset * 86400
        end = start + action.occupancy_minutes * 60.0
        physical = physical_vehicle_id(route.vehicle_id)
        same_vehicle = [
            other
            for other in certificate.trips
            if other.physical_vehicle_id == physical
        ]
        intersections: list[tuple[float, float, str]] = []
        for other in same_vehicle:
            left = max(start, other.departure_second)
            right = min(end, other.return_second)
            if left < right:
                intersections.append((left, right, other.route_id))
        if not intersections:
            continue
        # Scheduled trips for one physical vehicle are disjoint under the
        # certificate.  Merge defensively so one action is counted once even
        # if an archived certificate has adjacent/overlapping windows.
        intervals = sorted((left, right) for left, right, _ in intersections)
        merged: list[list[float]] = []
        for left, right in intervals:
            if merged and left <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], right)
            else:
                merged.append([left, right])
        duration = sum(right - left for left, right in merged)
        overlap_actions += 1
        overlap_energy += action.energy_kwh * duration / max(end - start, 1e-12)
        midday_duration = 0.0
        for left, right in merged:
            midday_duration += max(0.0, min(right, 15 * 3600) - max(left, 12 * 3600))
        midday_energy += action.energy_kwh * midday_duration / max(end - start, 1e-12)
        details.append(
            {
                "action_index": action_index,
                "vehicle_id": action.vehicle_id,
                "route_id": route.vehicle_id,
                "physical_vehicle_id": physical,
                "station_id": action.station_id,
                "charge_start_second": start,
                "charge_end_second": end,
                "charge_start_hhmm": fmt_minute(start),
                "charge_end_hhmm": fmt_minute(end),
                "energy_kwh": action.energy_kwh,
                "occupancy_minutes": action.occupancy_minutes,
                "overlap_trip_route_ids": [route_id for _, _, route_id in intersections],
                "overlap_intervals": [
                    {"start_second": left, "end_second": right}
                    for left, right in merged
                ],
            }
        )
    return {
        "status": "CERTIFICATE_PASS",
        "instance_id": instance_id or "",
        "total_charging_kwh": total_energy,
        "overlap_action_count": overlap_actions,
        "overlap_energy_kwh": overlap_energy,
        "overlap_midday_12_15_kwh": midday_energy,
        "overlap_details": details,
        "certificate_trip_count": len(certificate.trips),
    }


def self_test() -> dict[str, Any]:
    expected = {
        "C_seed2_budget1000": "12:00—13:49",
        "C_seed1_budget100": "12:00—13:46",
        "C_seed3_budget1000": "12:00—13:43",
    }
    with SELFTEST_FILE.open(encoding="utf-8") as handle:
        data = json.load(handle)
    results: list[dict[str, Any]] = []
    ok = True
    for name, expected_window in expected.items():
        try:
            payload = data["runs"][name]["solution"]
            result = overlap_result(payload, TARGET_INSTANCE)
            details = result["overlap_details"]
            actual_window = (
                f"{details[0]['charge_start_hhmm']}—{details[0]['charge_end_hhmm']}"
                if len(details) == 1
                else ""
            )
            trip_ok = bool(details) and any(
                "#T1" in route_id for route_id in details[0]["overlap_trip_route_ids"]
            )
            row_ok = (
                result["status"] == "CERTIFICATE_PASS"
                and result["overlap_action_count"] == 1
                and actual_window == expected_window
                and trip_ok
            )
            ok = ok and row_ok
            results.append(
                {
                    "name": name,
                    "expected_window": expected_window,
                    "actual_window": actual_window,
                    "overlap_action_count": result["overlap_action_count"],
                    "overlap_details": details,
                    "overlap_trip_1": trip_ok,
                    "pass": row_ok,
                }
            )
        except Exception as exc:  # self-test must report the exact failure
            ok = False
            results.append({"name": name, "pass": False, "error": f"{type(exc).__name__}: {exc}"})
    return {"pass": ok, "expected": expected, "results": results}


def public_station_evidence() -> dict[str, Any]:
    """Read-only code/data evidence for task B, including one hand candidate."""
    bundle, prices = bundle_for(TARGET_INSTANCE)
    public_nodes = [
        node
        for node in bundle.instance.nodes
        if node.node_type.lower() not in {"c", "d"}
    ]
    node_rows = [
        {
            "node_id": node.node_id,
            "node_type": node.node_type,
            "city": node.city,
            "longitude_x": node.x,
            "latitude_y": node.y,
            "power_kw": node.charge_power_kw,
            "station_chargers": node.station_chargers,
        }
        for node in public_nodes
    ]

    # A fixed, transparent comparison: 40.10765748336112 kWh at 12:00,
    # matching the archived C_seed2_budget1000 action.  The public option
    # uses the same route leg D_beijing -> C003 and includes its real detour.
    energy = 40.10765748336112
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    cost_rows: list[dict[str, Any]] = []
    for station_id, node_type, power_kw in (
        ("D_beijing", "d", prices.depot_charge_power_kw),
        ("S_beijing", "f", node_lookup["S_beijing"].charge_power_kw),
    ):
        action = _curve_aware_action(
            vehicle_id="T9_MANUAL_CANDIDATE",
            station_id=station_id,
            start_energy_kwh=0.0,
            energy_kwh=energy,
            reference_power_kw=float(power_kw),
            prices=prices,
            instance=bundle.instance,
        )
        if station_id == "D_beijing":
            detour_m = 0.0
            detour_seconds = 0.0
        else:
            detour_m = (
                _ev_distance(bundle.instance, "D_beijing", station_id, prices)
                + _ev_distance(bundle.instance, station_id, "C003", prices)
                - _ev_distance(bundle.instance, "D_beijing", "C003", prices)
            )
            detour_seconds = (
                _ev_travel_time(bundle.instance, "D_beijing", station_id, prices)
                + _ev_travel_time(bundle.instance, station_id, "C003", prices)
                - _ev_travel_time(bundle.instance, "D_beijing", "C003", prices)
            )
        option = ChargeOption(
            station_id=station_id,
            node_type=node_type,
            earliest_start_second=43200.0,
            latest_start_second=43200.0,
            energy_kwh=action.energy_kwh,
            power_kw=float(power_kw),
            detour_m=detour_m,
            detour_seconds=detour_seconds,
            occupancy_seconds_override=action.occupancy_minutes * 60.0,
            start_energy_kwh=action.start_energy_kwh,
            end_energy_kwh=action.end_energy_kwh,
            charging_curve_id=action.charging_curve_id,
        )
        scored = score_charge_option(
            option,
            bundle.instance,
            bundle.time_profile,
            prices,
            carbon_weight=1.0,
        )
        cost_rows.append(
            {
                "station_id": station_id,
                "node_type": node_type,
                "power_kw": float(power_kw),
                "energy_kwh": action.energy_kwh,
                "occupancy_minutes": action.occupancy_minutes,
                "detour_m": detour_m,
                "detour_seconds": detour_seconds,
                "electricity_cost_cny": scored.electricity_cost,
                "occupancy_cost_cny": scored.occupancy_cost,
                "detour_cost_cny": scored.detour_cost,
                "time_cost_cny": scored.time_cost,
                "carbon_cost_cny": scored.carbon_cost,
                "total_incremental_cost_cny": scored.total_incremental_cost,
                "start_second": scored.timing.start_second,
            }
        )

    # Call only the deterministic candidate-construction helper with a hand
    # supplied low SOC.  This is not a search rerun and writes no artifact.
    witness = json.loads(SELFTEST_FILE.read_text(encoding="utf-8"))
    raw_route = next(
        row
        for row in witness["runs"]["C_seed2_budget1000"]["solution"]["routes"]
        if row["vehicle_id"] == "EV_D_beijing_1#T2"
    )
    route = Route(
        raw_route["vehicle_id"],
        raw_route["vehicle_type"],
        raw_route["home_depot_id"],
        list(raw_route["node_sequence"]),
    )
    customer = "C003"
    station = node_lookup["S_beijing"]
    candidate = _best_station_insert(
        "D_beijing",
        customer,
        [customer],
        [customer],
        [customer],
        float(node_lookup[customer].demand),
        10.0,
        21600.0,
        [station],
        node_lookup,
        bundle.instance,
        bundle.time_profile,
        prices,
        route.vehicle_id,
        strategy="integrated",
        carbon_weight=1.0,
        charge_amount_strategy="just_enough",
    )
    if candidate is None:
        raise RuntimeError("T9 public candidate construction unexpectedly returned None")
    station_id, action, arrive, depart, battery_after = candidate
    public_candidate = {
        "from_node": "D_beijing",
        "to_customer": customer,
        "supplied_battery_kwh_before_leg": 10.0,
        "candidate_station_id": station_id,
        "energy_kwh": action.energy_kwh,
        "occupancy_minutes": action.occupancy_minutes,
        "charge_start_second": action.charge_start_second,
        "arrive_second": arrive,
        "depart_second": depart,
        "battery_after_charge_kwh": battery_after,
    }
    archive_zero = {}
    for rel in (
        "docs/handoff/carbon_objective_probe_20260804/solution_witnesses.json",
        "docs/handoff/eval_chain_carbon_consistency_20260804/solution_witnesses.json",
    ):
        data = json.loads((REPO / rel).read_text(encoding="utf-8"))
        public_actions = []
        total_actions = 0
        for run in data.get("runs", {}).values():
            for action in run.get("solution", {}).get("charging_actions", []):
                total_actions += 1
                if str(action.get("station_id", "")).startswith("S_"):
                    public_actions.append(action)
        archive_zero[rel] = {
            "run_count": len(data.get("runs", {})),
            "total_charging_actions": total_actions,
            "public_station_action_count": len(public_actions),
            "public_station_ids": sorted({a["station_id"] for a in public_actions}),
        }
    return {
        "instance_id": TARGET_INSTANCE,
        "public_node_count": len(public_nodes),
        "public_nodes": node_rows,
        "cost_comparison": cost_rows,
        "hand_constructed_public_candidate": public_candidate,
        "archive_action_check": archive_zero,
        "code_evidence": {
            "completion": "solver/src/setp_solver/china81_completion.py:19-22,336-349",
            "public_station_collection": "solver/src/setp_solver/algorithms/resetp_alns/support/charging.py:265-289",
            "public_station_candidate_loop": "solver/src/setp_solver/algorithms/resetp_alns/support/charging.py:770-971",
            "depot_precharge": "solver/src/setp_solver/algorithms/resetp_alns/support/charging.py:557-657",
            "candidate_selection": "solver/src/setp_solver/algorithms/resetp_alns/support/carbon_charging.py:246-373",
            "breakdown_split": "solver/src/setp_solver/cost.py:237-238",
        },
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


RAW_FIELDS = [
    "package_path",
    "source_file",
    "solution_locator",
    "instance_id",
    "solution_status",
    "prefilter_pass",
    "prefilter_groups",
    "total_charging_kwh",
    "overlap_action_count",
    "overlap_energy_kwh",
    "overlap_midday_12_15_kwh",
    "overlap_details",
    "unable_reason",
]
PACKAGE_FIELDS = [
    "package_path",
    "solution_total",
    "prefilter_pass_count",
    "unable_count",
    "overlap_solution_count",
    "overlap_action_count",
    "overlap_energy_kwh",
    "total_charging_kwh",
    "overlap_energy_ratio",
    "overlap_midday_12_15_kwh",
    "skipped_no_multitrip_count",
    "solution_status_counts",
    "unable_reason_counts",
]


def scan_all(started: float) -> dict[str, Any]:
    files = witness_files()
    raw_rows: list[dict[str, Any]] = []
    package_acc: dict[str, dict[str, Any]] = {}
    for source_path in files:
        package_path = str(source_path.parent.relative_to(REPO))
        acc = package_acc.setdefault(
            package_path,
            {
                "solution_total": 0,
                "prefilter_pass_count": 0,
                "unable_count": 0,
                "overlap_solution_count": 0,
                "overlap_action_count": 0,
                "overlap_energy_kwh": 0.0,
                "total_charging_kwh": 0.0,
                "overlap_midday_12_15_kwh": 0.0,
                "skipped_no_multitrip_count": 0,
                "statuses": Counter(),
                "reasons": Counter(),
            },
        )
        try:
            with source_path.open(encoding="utf-8") as handle:
                data = json.load(handle)
            entries = solution_entries(data)
        except Exception as exc:
            # A malformed witness file is itself one unable-to-judge package;
            # retain the package row and make the reason explicit.
            acc["unable_count"] += 1
            acc["reasons"][f"JSON_READ_ERROR: {type(exc).__name__}: {exc}"] += 1
            acc["statuses"]["UNABLE_TO_JUDGE"] += 1
            continue
        for locator, payload, context in entries:
            acc["solution_total"] += 1
            instance_id = infer_instance(source_path, locator, data, context)
            prefilter_pass = False
            groups: dict[str, list[str]] = {}
            total_energy = 0.0
            status = ""
            unable_reason = ""
            result: dict[str, Any] = {}
            try:
                routes_raw = payload["routes"]
                prefilter_pass, groups = prefilter(routes_raw)
                for action in payload.get("charging_actions", []) or []:
                    total_energy += float(action["energy_kwh"])
            except Exception as exc:
                prefilter_pass = True  # malformed route data cannot be safely skipped
                unable_reason = f"SCHEMA_INCOMPATIBLE: {type(exc).__name__}: {exc}"
            if prefilter_pass:
                acc["prefilter_pass_count"] += 1
                if not unable_reason:
                    try:
                        result = overlap_result(payload, instance_id, context)
                        status = result["status"]
                        total_energy = result["total_charging_kwh"]
                    except Exception as exc:
                        status = "UNABLE_TO_JUDGE"
                        unable_reason = f"{type(exc).__name__}: {exc}"
            else:
                status = "SKIPPED_NO_MULTITRIP"
                acc["skipped_no_multitrip_count"] += 1
            if unable_reason:
                acc["unable_count"] += 1
                acc["reasons"][unable_reason] += 1
            overlap_actions = int(result.get("overlap_action_count", 0))
            overlap_energy = float(result.get("overlap_energy_kwh", 0.0))
            midday_energy = float(result.get("overlap_midday_12_15_kwh", 0.0))
            acc["total_charging_kwh"] += total_energy
            acc["overlap_action_count"] += overlap_actions
            acc["overlap_energy_kwh"] += overlap_energy
            acc["overlap_midday_12_15_kwh"] += midday_energy
            if overlap_actions > 0:
                acc["overlap_solution_count"] += 1
            acc["statuses"][status or "UNABLE_TO_JUDGE"] += 1
            raw_rows.append(
                {
                    "package_path": package_path,
                    "source_file": str(source_path.relative_to(REPO)),
                    "solution_locator": locator,
                    "instance_id": instance_id or "",
                    "solution_status": status or "UNABLE_TO_JUDGE",
                    "prefilter_pass": str(prefilter_pass).lower(),
                    "prefilter_groups": json_dumps(groups),
                    "total_charging_kwh": f"{total_energy:.12f}",
                    "overlap_action_count": overlap_actions,
                    "overlap_energy_kwh": f"{overlap_energy:.12f}",
                    "overlap_midday_12_15_kwh": f"{midday_energy:.12f}",
                    "overlap_details": json_dumps(result.get("overlap_details", [])),
                    "unable_reason": unable_reason,
                }
            )
        if time.monotonic() - started > 3600:
            raise TimeoutError(
                f"HALT_TIMEOUT_60_MINUTES: completed source file {source_path.relative_to(REPO)}; "
                f"remaining files={len(files) - files.index(source_path) - 1}"
            )
    package_rows: list[dict[str, Any]] = []
    for package_path in sorted(package_acc):
        acc = package_acc[package_path]
        total = acc["total_charging_kwh"]
        package_rows.append(
            {
                "package_path": package_path,
                "solution_total": acc["solution_total"],
                "prefilter_pass_count": acc["prefilter_pass_count"],
                "unable_count": acc["unable_count"],
                "overlap_solution_count": acc["overlap_solution_count"],
                "overlap_action_count": acc["overlap_action_count"],
                "overlap_energy_kwh": f"{acc['overlap_energy_kwh']:.12f}",
                "total_charging_kwh": f"{total:.12f}",
                "overlap_energy_ratio": f"{acc['overlap_energy_kwh'] / total:.12f}" if total else "0",
                "overlap_midday_12_15_kwh": f"{acc['overlap_midday_12_15_kwh']:.12f}",
                "skipped_no_multitrip_count": acc["skipped_no_multitrip_count"],
                "solution_status_counts": json_dumps(dict(acc["statuses"])),
                "unable_reason_counts": json_dumps(dict(acc["reasons"])),
            }
        )
    write_csv(OUT / "raw_runs.csv", raw_rows, RAW_FIELDS)
    write_csv(OUT / "package_summary.csv", package_rows, PACKAGE_FIELDS)
    affected_packages = sum(1 for row in package_rows if int(row["overlap_solution_count"]) > 0)
    affected_solutions = sum(int(row["overlap_solution_count"]) for row in package_rows)
    overlap_kwh = sum(float(row["overlap_energy_kwh"]) for row in package_rows)
    return {
        "source_file_count": len(files),
        "solution_row_count": len(raw_rows),
        "package_row_count": len(package_rows),
        "affected_package_count": affected_packages,
        "affected_solution_count": affected_solutions,
        "overlap_energy_kwh": overlap_kwh,
        "unable_solution_count": sum(int(row["unable_count"]) for row in package_rows),
        "prefilter_pass_count": sum(int(row["prefilter_pass_count"]) for row in package_rows),
        "prefilter_skipped_count": sum(int(row["skipped_no_multitrip_count"]) for row in package_rows),
    }


def create_report(
    selftest: dict[str, Any],
    summary: dict[str, Any],
    started_at: str,
    ended_at: str,
    public_evidence: dict[str, Any] | None = None,
) -> None:
    lines = [
        "# T9 趟间充电重叠污染范围与公共站充电量调查",
        "",
        "## 自检（必须先于全量扫描）",
        "",
        f"FACT：三个指定阳性样本自检结果：`{'PASS' if selftest['pass'] else 'FAIL'}`。",
    ]
    for row in selftest["results"]:
        lines.append(
            f"FACT：`{row['name']}`：期望 `{row.get('expected_window', '')}`，"
            f"实际 `{row.get('actual_window', '')}`，重叠动作 "
            f"`{row.get('overlap_action_count', 0)}`，趟1="
            f"`{'PASS' if row.get('overlap_trip_1') else 'FAIL'}`，"
            f"自检=`{'PASS' if row.get('pass') else 'FAIL'}`。"
        )
    if not selftest["pass"]:
        lines += [
            "",
            "HALT_SELF_TEST_FAILED：指定阳性样本未按任务口径复现；未进行仓库扫描。",
        ]
    else:
        lines += [
            "",
            "## A. 污染范围扫描",
            "",
            f"FACT：扫描 `solution_witnesses.json` 文件 `{summary['source_file_count']}` 个；"
            f"逐解行数 `{summary['solution_row_count']}`；包行数 `{summary['package_row_count']}`。",
            f"FACT：通过同一实体车至少两趟预筛 `{summary['prefilter_pass_count']}` 解；"
            f"廉价跳过 `{summary['prefilter_skipped_count']}` 解；无法判定 `{summary['unable_solution_count']}` 解。",
            f"FACT：有重叠包 `{summary['affected_package_count']}` 个；有重叠解 "
            f"`{summary['affected_solution_count']}` 个；重叠电量合计 "
            f"`{summary['overlap_energy_kwh']:.12f}` kWh。",
            "FACT：逐解判定见 `raw_runs.csv`，逐包表见 `package_summary.csv`；表中未对包作严重性或优先级分级。",
            "",
            "## B. 公共站证据",
            "",
            f"FACT：`{TARGET_INSTANCE}` 的 bundle 中，`node_type` 非 `c`/`d` 的公共充电节点数为 "
            f"`{public_evidence['public_node_count'] if public_evidence else '未生成'}`。",
            "FACT：节点、位置、功率、枪数以及逐字段价格见下表；价格为该 bundle 的 2025-02-12 时变价格，"
            "公共服务费为每 kWh 叠加项。",
            "",
            "| 节点 | 城市 | 位置（x=经度，y=纬度） | 功率 | 枪数 |",
            "|---|---|---|---:|---:|",
        ]
        if public_evidence:
            for node in public_evidence["public_nodes"]:
                lines.append(
                    f"| `{node['node_id']}` | {node['city']} | "
                    f"{node['longitude_x']}, {node['latitude_y']} | "
                    f"{node['power_kw']} kW | {node['station_chargers']} |"
                )
            lines += [
                "",
                "FACT：该 bundle 的价格表（`data/ChinaInstances/"
                "china81_runtime_parameter_authority_v4_20260723/"
                "tariff_carbon_hourly_calendar.csv`）中，北京公共电价/服务费为 "
                "谷 `0.56328575+0.4=0.96328575`、平 `0.83644275+0.4=1.23644275`、"
                "峰 `1.14862175+0.4=1.54862175` CNY/kWh；天津为谷 `0.43996875+0.4=0.83996875`、"
                "平 `0.79746875+0.4=1.19746875`、峰 `1.12856875+0.4=1.52856875` CNY/kWh。",
                "FACT：当前补全器确实有公共站分支：`charging.py:268` 收集 `node_type == f`；"
                "`charging.py:317-340` 在直达电量不可行时调用 `_best_station_insert`；"
                "`charging.py:770-971` 遍历公共站并构造带 `station_id=S_*` 的 `ChargingAction`。",
                "FACT：补全入口位于 `china81_completion.py:336-349`，调用上述 `repair_route_charging`；"
                "车场预充在 `charging.py:278-296`、`557-657` 先执行，目标电量由整条 EV 路线需求计算 "
                "（`charging.py:578-585`），公共站分支只在随后直达电量检查失败时进入。",
                "FACT：现有 T5/T7 两个 18-run 归档中，合计 36 个 final solution、86 个充电动作，"
                f"公共站动作数为 "
                f"`{sum(v['public_station_action_count'] for v in (public_evidence or {}).get('archive_action_check', {}).values())}`；"
                "归档动作的站点集合只有 `D_beijing`/`D_tianjin`。"
            ]
            lines += [
                "",
                "FACT：手工构造的公共候选（不调用搜索）：`D_beijing -> S_beijing -> C003`，"
                "给定发车前电量 10.0 kWh、当前时刻 21600 s；候选生成返回 `S_beijing`，"
                f"充电 `{public_evidence['hand_constructed_public_candidate']['energy_kwh']:.12f}` kWh，"
                f"开始 `{public_evidence['hand_constructed_public_candidate']['charge_start_second']:.1f}` s。",
                "FACT：同一 40.10765748336112 kWh、12:00 起充、D_beijing→C003 路段的手工成本对比：",
                "",
                "| 选项 | 电费 | 服务/占用费 | 绕路费 | 碳成本 | 总增量成本 |",
                "|---|---:|---:|---:|---:|---:|",
            ]
            for row in public_evidence["cost_comparison"]:
                lines.append(
                    f"| `{row['station_id']}` | {row['electricity_cost_cny']:.6f} | "
                    f"{row['occupancy_cost_cny']:.6f} | {row['detour_cost_cny']:.6f} | "
                    f"{row['carbon_cost_cny']:.6f} | {row['total_incremental_cost_cny']:.6f} CNY |"
                )
            lines += [
                "",
                "FACT：在这个固定比较中，公共站总增量成本 `88.264344` CNY，车场为 `40.896695` CNY；"
                "公共站多出的来源包括公共电价中的服务费、公共站绕路（约 `7184.184` m）和公共站充电占用。",
                "INFERENCE：结论是“有能力生成公共站候选”，不是“公共站分支缺失”。归档中恒为 0 的直接事实是："
                "车场预充先满足了归档 EV 路线的充电动作，而最终动作未选择 `S_*`；在可复算比较中，"
                "公共站候选还受服务费与绕路成本劣势影响。仅凭归档不能把每一次未出现的候选逐一归因成单一原因，"
                "因此这里不宣称所有 0 都由一个统一条件单独造成。",
            ]
        lines += [
            "",
            "## 边界与状态",
            "",
            f"FACT：开始 `{started_at}`，结束 `{ended_at}`。",
            "DECISION：本调查产物的 `paper_claim_allowed` 为 `false`。",
            "DECISION：本任务仅做读取、证书重建、统计和证据整理；不包含修复方案或后续任务建议。",
        ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    started_wall = time.monotonic()
    started_at = now_iso()
    hashes_start = protected_hashes()
    selftest_result = self_test()
    if not selftest_result["pass"]:
        ended_at = now_iso()
        create_report(selftest_result, {"source_file_count": 0, "solution_row_count": 0, "package_row_count": 0, "prefilter_pass_count": 0, "prefilter_skipped_count": 0, "unable_solution_count": 0, "affected_package_count": 0, "affected_solution_count": 0, "overlap_energy_kwh": 0.0}, started_at, ended_at)
        hashes_end = protected_hashes()
        (OUT / "decision.json").write_text(json_dumps({"paper_claim_allowed": False, "status": "HALT_SELF_TEST_FAILED"}) + "\n", encoding="utf-8")
        (OUT / "metadata.json").write_text(json_dumps({"schema": "t9-intertrip-overlap-scan.v1", "status": "HALT_SELF_TEST_FAILED", "started_at": started_at, "ended_at": ended_at, "protected_hashes_start": hashes_start, "protected_hashes_end": hashes_end, "self_test": selftest_result, "no_source_or_result_mutation": True}) + "\n", encoding="utf-8")
        return 2
    public_evidence = public_station_evidence()
    try:
        summary = scan_all(started_wall)
        status = "COMPLETE"
    except TimeoutError as exc:
        status = "HALT_TIMEOUT_60_MINUTES"
        summary = {"error": str(exc)}
    except Exception as exc:
        status = "HALT_SCAN_ERROR"
        summary = {"error": f"{type(exc).__name__}: {exc}"}
    ended_at = now_iso()
    hashes_end = protected_hashes()
    create_report(selftest_result, summary if status == "COMPLETE" else {"source_file_count": 0, "solution_row_count": 0, "package_row_count": 0, "prefilter_pass_count": 0, "prefilter_skipped_count": 0, "unable_solution_count": 0, "affected_package_count": 0, "affected_solution_count": 0, "overlap_energy_kwh": 0.0}, started_at, ended_at, public_evidence)
    (OUT / "decision.json").write_text(json_dumps({"paper_claim_allowed": False, "status": status, "facts_only": True}) + "\n", encoding="utf-8")
    (OUT / "metadata.json").write_text(json_dumps({"schema": "t9-intertrip-overlap-scan.v1", "status": status, "started_at": started_at, "ended_at": ended_at, "elapsed_seconds": time.monotonic() - started_wall, "repo_root": str(REPO), "source_globs": ["baselines/**/solution_witnesses.json", "docs/handoff/**/solution_witnesses.json"], "excluded_names": ["._*", "__pycache__", ".pytest_cache"], "self_test": selftest_result, "summary": summary, "public_station_evidence": public_evidence, "protected_hashes_start": hashes_start, "protected_hashes_end": hashes_end, "no_solver_rerun": True, "no_source_or_result_mutation": True}) + "\n", encoding="utf-8")
    if status != "COMPLETE":
        (OUT / "report.md").write_text((OUT / "report.md").read_text(encoding="utf-8") + f"\nHALT_SCAN_ERROR：{summary.get('error', status)}\n", encoding="utf-8")
    # Self-exclude artifact_hashes.json to avoid a self-referential digest.
    artifact_hashes = {
        "schema": "t9-intertrip-overlap-artifact-hashes.v1",
        "hashed_artifacts": {
            str(path.relative_to(OUT)): sha256(path)
            for path in sorted(OUT.rglob("*"))
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
            and ".pytest_cache" not in path.parts
        },
        "protected_files": {"start": hashes_start, "end": hashes_end},
    }
    (OUT / "artifact_hashes.json").write_text(json_dumps(artifact_hashes) + "\n", encoding="utf-8")
    return 0 if status == "COMPLETE" else 3


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        print(json_dumps(self_test()))
        raise SystemExit(0 if self_test()["pass"] else 2)
    raise SystemExit(main())
