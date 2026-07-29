#!/usr/bin/env python3
"""E4-CARBON-TIMING-01: fixed-solution, zero-search charging-timing replay."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Any, Iterable, Sequence

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix, vstack


ROOT = Path(__file__).resolve().parents[3]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from setp_solver.check import check_solution
from setp_solver.china81 import _load_time_profile, load_china81_bundle
from setp_solver.china81_completion import (
    annotate_cross_site_services,
    exact_china81_score,
)
from setp_solver.cost import (
    CARBON_SLOT_SECONDS,
    carbon_profile_row_for_slot,
    charging_action_slot_breakdown,
    charging_curve_for_action,
    evaluate,
    route_departure_second,
    route_node_schedule,
    time_profile_rows_for_node,
)
from setp_solver.search.charging import _fixed_charge_latest
from setp_solver.solution import (
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
    charging_action_from_dict,
)


TASK_ID = "E4-CARBON-TIMING-01"
OUT = Path(__file__).resolve().parent
INPUT_ROOT = ROOT / "baselines/e2_rerun_unified_01_20260727/tasks"
PARAMETER_AUTHORITY = (
    ROOT
    / "data/ChinaInstances/china81_runtime_parameter_authority_v3_20260723"
)
APPROVED_WRAPPER_AUTHORITY = (
    ROOT
    / "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
)
DATES = tuple(f"2025-02-{day:02d}" for day in range(1, 29))
EXPECTED_SOLUTIONS = 405
EXPECTED_ROWS = EXPECTED_SOLUTIONS * len(DATES)
SIZE_AXIS = (10, 15, 20, 25, 50, 75, 100, 150, 200)
TOL = 1.0e-9
START_TOL = 1.0e-6
PROTECTED = (
    ROOT / "solver/src/setp_solver/cost.py",
    ROOT / "solver/src/setp_solver/check.py",
    ROOT / "solver/src/setp_solver/search/evaluation.py",
)
REGION_LABELS = {"jjj": "京津冀", "prd": "珠三角", "cy": "成渝"}


@dataclass(frozen=True)
class ActionSpec:
    index: int
    vehicle_id: str
    station_id: str
    station_type: str
    station_city: str
    capacity: int
    earliest: float
    latest: float
    starts: tuple[float, ...]


@dataclass(frozen=True)
class Candidate:
    start: float
    predicted_kg: float
    actual_kg: float
    occupied_slots: tuple[int, ...]


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def solution_from_dict(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=[str(node_id) for node_id in row["node_sequence"]],
            )
            for row in payload.get("routes", [])
        ],
        charging_actions=[
            charging_action_from_dict(row)
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                customer_id=str(row["customer_id"]),
                served_by_depot_id=str(row["served_by_depot_id"]),
            )
            for row in payload.get("cross_site_services", [])
        ],
    )


def fixed_solution_payload(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "cross_site_services": [
            asdict(service) for service in solution.cross_site_services
        ],
        "charging_actions_without_start": [
            {
                key: value
                for key, value in asdict(action).items()
                if key != "charge_start_second"
            }
            for action in solution.charging_actions
        ],
    }


def parse_instance(instance_id: str) -> tuple[str, int, int]:
    match = re.fullmatch(
        r"cn-(jjj|prd|cy)-(\d+)c-(\d+)-V2-LOCATIONS",
        instance_id,
    )
    if match is None:
        raise ValueError(f"unexpected China81 instance id: {instance_id}")
    return match.group(1), int(match.group(2)), int(match.group(3))


def discover_inputs() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for witness_path in sorted(
        INPUT_ROOT.glob("*__MV__attempt0__k3000/solution_witness.json")
    ):
        if witness_path.parent.name.startswith("._"):
            continue
        result_path = witness_path.with_name("result.json")
        if not result_path.is_file():
            raise RuntimeError(f"missing result.json beside {witness_path}")
        witness = read_json(witness_path)
        result = read_json(result_path)
        if (
            witness.get("arm") != "MV"
            or result.get("arm") != "MV"
            or witness.get("attempt") != 0
            or int(witness.get("k", -1)) != 3000
        ):
            raise RuntimeError(f"input identity mismatch: {witness_path}")
        if (
            result.get("status") != "PASS"
            or not bool(result.get("feasible"))
            or int(result.get("independent_violation_count", -1)) != 0
        ):
            raise RuntimeError(f"input is not a sealed feasible MV unit: {result_path}")
        instance_id = str(witness["instance_id"])
        seed = int(witness["seed"])
        region, customer_size, map_index = parse_instance(instance_id)
        if result.get("region") != region:
            raise RuntimeError(f"region mismatch in {result_path}")
        solution = solution_from_dict(witness["solution"])
        rows.append(
            {
                "instance_id": instance_id,
                "region": region,
                "customer_size": customer_size,
                "map_index": map_index,
                "seed": seed,
                "witness_path": str(witness_path.relative_to(ROOT)),
                "result_path": str(result_path.relative_to(ROOT)),
                "witness_sha256": sha256_path(witness_path),
                "result_sha256": sha256_path(result_path),
                "fixed_solution_sha256": canonical_hash(
                    fixed_solution_payload(solution)
                ),
                "charging_action_count": len(solution.charging_actions),
                "charging_energy_kwh": sum(
                    float(action.energy_kwh)
                    for action in solution.charging_actions
                ),
            }
        )
    if len(rows) != EXPECTED_SOLUTIONS:
        raise RuntimeError(
            f"expected {EXPECTED_SOLUTIONS} MV solutions, found {len(rows)}"
        )
    identities = {
        (row["instance_id"], row["seed"])
        for row in rows
    }
    if len(identities) != EXPECTED_SOLUTIONS:
        raise RuntimeError("duplicate instance/seed input identity")
    by_instance: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        by_instance[row["instance_id"]].add(int(row["seed"]))
    if len(by_instance) != 81:
        raise RuntimeError(f"expected 81 instances, found {len(by_instance)}")
    bad_seeds = {
        instance_id: sorted(seeds)
        for instance_id, seeds in by_instance.items()
        if seeds != {1, 2, 3, 4, 5}
    }
    if bad_seeds:
        raise RuntimeError(f"input seed matrix mismatch: {bad_seeds}")
    return rows


def validate_calendar() -> dict[str, Any]:
    path = PARAMETER_AUTHORITY / "tariff_carbon_48slot_calendar.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    cities = sorted({row["city"].strip().lower() for row in rows})
    dates = sorted({row["date"] for row in rows})
    counts = Counter((row["city"].strip().lower(), row["date"]) for row in rows)
    if len(cities) != 9 or dates != list(DATES):
        raise RuntimeError(
            f"calendar grid mismatch: cities={len(cities)}, dates={dates}"
        )
    if set(counts.values()) != {48} or len(rows) != 9 * 28 * 48:
        raise RuntimeError("calendar must contain 48 rows for every city/date")
    wrapper_path = (
        APPROVED_WRAPPER_AUTHORITY / "tariff_carbon_48slot_calendar.csv"
    )
    with wrapper_path.open(newline="", encoding="utf-8") as handle:
        wrapper_rows = list(csv.DictReader(handle))
    shared_fields = (
        "city",
        "region",
        "date",
        "half_hour_slot",
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
    projection = [
        {field: row[field] for field in shared_fields}
        for row in rows
    ]
    wrapper_projection = [
        {field: row[field] for field in shared_fields}
        for row in wrapper_rows
    ]
    if projection != wrapper_projection:
        raise RuntimeError(
            "v3 and approved-wrapper v4 timing fields differ row by row"
        )
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": sha256_path(path),
        "city_count": len(cities),
        "date_count": len(dates),
        "row_count": len(rows),
        "cities": cities,
        "formal_v3_loader_status": (
            "REJECTED_MISSING_LATER_APPROVAL_COLUMNS"
        ),
        "timing_profile_source": "v3_direct_validated",
        "approved_wrapper_calendar_path": str(
            wrapper_path.relative_to(ROOT)
        ),
        "approved_wrapper_calendar_sha256": sha256_path(wrapper_path),
        "shared_timing_fields_match_v4": True,
        "shared_timing_projection_sha256": canonical_hash(projection),
    }


def load_e4_bundle(instance_id: str, date: str) -> Any:
    """Load physical authorities through v4, but timing values from v3.

    The v3 calendar predates the two formal-release status columns. Its timing
    values are validated independently and row-identical to the corresponding
    v4 projection before this function is called.
    """

    base = load_china81_bundle(
        ROOT,
        instance_id,
        date=date,
        runtime_parameter_authority=APPROVED_WRAPPER_AUTHORITY,
    )
    cities = {
        str(node.city).strip().lower()
        for node in base.instance.nodes
        if node.city is not None and str(node.city).strip()
    }
    profile = _load_time_profile(
        PARAMETER_AUTHORITY / "tariff_carbon_48slot_calendar.csv",
        cities=cities,
        date=date,
        require_explicit_mapping=False,
    )
    source_paths = dict(base.source_paths)
    source_paths["timing_calendar"] = str(
        (
            PARAMETER_AUTHORITY
            / "tariff_carbon_48slot_calendar.csv"
        ).relative_to(ROOT)
    )
    source_paths["approved_bundle_wrapper"] = str(
        APPROVED_WRAPPER_AUTHORITY.relative_to(ROOT)
    )
    return replace(
        base,
        time_profile=profile,
        source_paths=source_paths,
        runtime_parameter_authority=(
            f"{PARAMETER_AUTHORITY.relative_to(ROOT)}"
            "__TIMING_PROFILE_WITH__"
            f"{APPROVED_WRAPPER_AUTHORITY.relative_to(ROOT)}"
            "__NON_TIMING_WRAPPER"
        ),
    )


def action_start_candidates(
    action: ChargingAction,
    earliest: float,
    latest: float,
    bundle: Any,
) -> tuple[float, ...]:
    if latest < earliest - TOL:
        raise ValueError(
            f"empty window for {action.vehicle_id}@{action.station_id}: "
            f"{earliest}>{latest}"
        )
    duration = float(action.occupancy_minutes) * 60.0
    boundaries = {0.0, duration}
    curve_state = charging_curve_for_action(
        action,
        bundle.instance,
        bundle.prices,
    )
    if curve_state is not None:
        curve, start_energy, end_energy = curve_state
        for phase in curve.phases(start_energy, end_energy):
            boundaries.add(float(phase.relative_start_seconds))
            boundaries.add(float(phase.relative_end_seconds))
    starts = {float(earliest), float(latest)}
    first_grid = math.floor(float(earliest) / CARBON_SLOT_SECONDS) - 1
    final_grid = (
        math.ceil((float(latest) + duration) / CARBON_SLOT_SECONDS) + 1
    )
    for index in range(first_grid, final_grid + 1):
        boundary = float(index) * CARBON_SLOT_SECONDS
        for phase_boundary in boundaries:
            candidate = boundary - phase_boundary
            if earliest - TOL <= candidate <= latest + TOL:
                starts.add(min(float(latest), max(float(earliest), candidate)))
    # Rounding only removes floating duplicates created by equal phase boundaries.
    return tuple(sorted({round(value, 9) for value in starts}))


def prepare_action_specs(
    solution: Solution,
    bundle: Any,
) -> tuple[ActionSpec, ...]:
    route_by_vehicle = {route.vehicle_id: route for route in solution.routes}
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    specs: list[ActionSpec] = []
    for index, action in enumerate(solution.charging_actions):
        route = route_by_vehicle.get(action.vehicle_id)
        node = node_lookup.get(action.station_id)
        if route is None or node is None:
            raise ValueError(
                f"action has no route/node: {action.vehicle_id}@{action.station_id}"
            )
        duration = float(action.occupancy_minutes) * 60.0
        station_type = str(node.node_type).lower()
        if station_type == "d":
            earliest = 0.0
            latest = (
                route_departure_second(
                    route,
                    bundle.instance,
                    bundle.prices,
                )
                - duration
            )
        elif station_type == "f":
            schedule = route_node_schedule(
                route,
                bundle.instance,
                bundle.prices,
                charging_actions=[],
            )
            times = {
                row.node_id: row
                for row in schedule
            }
            earliest = max(
                float(times[action.station_id].t_arrive),
                float(node.ready_time),
            )
            station_index = route.node_sequence.index(action.station_id)
            latest = _fixed_charge_latest(
                station_index,
                route.node_sequence,
                node_lookup,
                bundle.instance,
                bundle.prices,
                duration,
            )
        else:
            raise ValueError(
                f"charging action points to non-chargeable node {action.station_id}"
            )
        starts = action_start_candidates(
            action,
            float(earliest),
            float(latest),
            bundle,
        )
        capacity_raw = getattr(node, "station_chargers", None)
        capacity = (
            int(capacity_raw)
            if capacity_raw is not None
            else (1 if station_type == "f" else 10**6)
        )
        if capacity <= 0:
            raise ValueError(f"nonpositive charger capacity at {action.station_id}")
        specs.append(
            ActionSpec(
                index=index,
                vehicle_id=action.vehicle_id,
                station_id=action.station_id,
                station_type=station_type,
                station_city=str(node.city).strip().lower(),
                capacity=capacity,
                earliest=float(earliest),
                latest=float(latest),
                starts=starts,
            )
        )
    return tuple(specs)


def occupied_slots(
    action: ChargingAction,
    start: float,
    bundle: Any,
) -> tuple[int, ...]:
    shifted = replace(action, charge_start_second=float(start))
    node_profile = time_profile_rows_for_node(
        bundle.instance,
        action.station_id,
        bundle.time_profile,
    )
    return tuple(
        sorted(
            {
                int(slot.slot_index)
                for slot in charging_action_slot_breakdown(
                    shifted,
                    bundle.instance,
                    bundle.prices,
                    n_slots=len(node_profile),
                    cyclic=True,
                )
            }
        )
    )


def action_emissions(
    action: ChargingAction,
    start: float,
    bundle: Any,
    *,
    intensity_field: str,
) -> float:
    shifted = replace(action, charge_start_second=float(start))
    node_profile = time_profile_rows_for_node(
        bundle.instance,
        action.station_id,
        bundle.time_profile,
    )
    total_g = 0.0
    for slot in charging_action_slot_breakdown(
        shifted,
        bundle.instance,
        bundle.prices,
        n_slots=len(node_profile),
        cyclic=True,
    ):
        row = carbon_profile_row_for_slot(node_profile, int(slot.slot_index))
        total_g += float(slot.y_skt_kwh) * float(row[intensity_field])
    return total_g / 1000.0


def score_candidates(
    solution: Solution,
    specs: Sequence[ActionSpec],
    bundle: Any,
) -> dict[int, tuple[Candidate, ...]]:
    scored: dict[int, tuple[Candidate, ...]] = {}
    for spec in specs:
        action = solution.charging_actions[spec.index]
        scored[spec.index] = tuple(
            Candidate(
                start=float(start),
                predicted_kg=action_emissions(
                    action,
                    start,
                    bundle,
                    intensity_field="forecast_gco2_per_kwh",
                ),
                actual_kg=action_emissions(
                    action,
                    start,
                    bundle,
                    intensity_field="actual_gco2_per_kwh",
                ),
                occupied_slots=occupied_slots(action, start, bundle),
            )
            for start in spec.starts
        )
    return scored


def schedule_asap(
    specs: Sequence[ActionSpec],
    scored: dict[int, tuple[Candidate, ...]],
) -> dict[int, Candidate]:
    selected: dict[int, Candidate] = {}
    by_station: dict[tuple[str, int], list[ActionSpec]] = defaultdict(list)
    for spec in specs:
        by_station[(spec.station_id, 0)].append(spec)
    for _, station_specs in sorted(by_station.items()):
        occupancy: dict[int, set[str]] = defaultdict(set)
        ordered = sorted(
            station_specs,
            key=lambda spec: (
                spec.earliest,
                spec.latest,
                spec.vehicle_id,
                spec.station_id,
            ),
        )
        for spec in ordered:
            choice = None
            for candidate in sorted(
                scored[spec.index],
                key=lambda item: item.start,
            ):
                if all(
                    len(
                        occupancy[slot]
                        | {spec.vehicle_id}
                    )
                    <= spec.capacity
                    for slot in candidate.occupied_slots
                ):
                    choice = candidate
                    break
            if choice is None:
                raise RuntimeError(
                    f"ASAP has no capacity-feasible candidate for "
                    f"{spec.vehicle_id}@{spec.station_id}"
                )
            selected[spec.index] = choice
            for slot in choice.occupied_slots:
                occupancy[slot].add(spec.vehicle_id)
    return selected


def solve_station_carbon(
    station_specs: Sequence[ActionSpec],
    scored: dict[int, tuple[Candidate, ...]],
) -> tuple[dict[int, Candidate], dict[str, Any]]:
    if len(station_specs) == 1:
        spec = station_specs[0]
        choice = min(
            scored[spec.index],
            key=lambda item: (item.predicted_kg, item.start),
        )
        return {spec.index: choice}, {
            "solver": "direct_single_session",
            "variables": len(scored[spec.index]),
            "mip_status": "NOT_APPLICABLE",
        }

    variables: list[tuple[ActionSpec, Candidate, int]] = []
    for spec in sorted(station_specs, key=lambda row: row.index):
        for candidate_index, candidate in enumerate(scored[spec.index]):
            variables.append((spec, candidate, candidate_index))
    n = len(variables)
    row_ids: list[int] = []
    col_ids: list[int] = []
    values: list[float] = []
    lower: list[float] = []
    upper: list[float] = []
    constraint_row = 0

    for spec in sorted(station_specs, key=lambda row: row.index):
        for column, (candidate_spec, _, _) in enumerate(variables):
            if candidate_spec.index == spec.index:
                row_ids.append(constraint_row)
                col_ids.append(column)
                values.append(1.0)
        lower.append(1.0)
        upper.append(1.0)
        constraint_row += 1

    slots = sorted(
        {
            slot
            for _, candidate, _ in variables
            for slot in candidate.occupied_slots
        }
    )
    capacity = min(spec.capacity for spec in station_specs)
    if any(spec.capacity != capacity for spec in station_specs):
        raise RuntimeError("station capacity differs within one station")
    for slot in slots:
        for column, (_, candidate, _) in enumerate(variables):
            if slot in candidate.occupied_slots:
                row_ids.append(constraint_row)
                col_ids.append(column)
                values.append(1.0)
        lower.append(-np.inf)
        upper.append(float(capacity))
        constraint_row += 1

    matrix = coo_matrix(
        (values, (row_ids, col_ids)),
        shape=(constraint_row, n),
    ).tocsr()
    carbon = np.asarray(
        [candidate.predicted_kg for _, candidate, _ in variables],
        dtype=float,
    )
    base_constraint = LinearConstraint(
        matrix,
        np.asarray(lower, dtype=float),
        np.asarray(upper, dtype=float),
    )
    common = {
        "integrality": np.ones(n, dtype=int),
        "bounds": Bounds(np.zeros(n), np.ones(n)),
        "constraints": base_constraint,
        "options": {"presolve": True},
    }
    primary = milp(c=carbon, **common)
    if not bool(primary.success) or int(primary.status) != 0:
        raise RuntimeError(
            f"carbon timing MILP failed: status={primary.status}, "
            f"message={primary.message}"
        )
    optimum = float(primary.fun)

    carbon_row = coo_matrix(carbon.reshape(1, -1)).tocsr()
    tie_matrix = vstack([matrix, carbon_row], format="csr")
    tie_lower = np.asarray([*lower, -np.inf], dtype=float)
    tie_upper = np.asarray([*upper, optimum + 1.0e-9], dtype=float)
    tie_objective = np.asarray(
        [
            candidate.start / 86_400.0
            + spec.index * 1.0e-9
            + candidate_index * 1.0e-12
            for spec, candidate, candidate_index in variables
        ],
        dtype=float,
    )
    tie = milp(
        c=tie_objective,
        integrality=np.ones(n, dtype=int),
        bounds=Bounds(np.zeros(n), np.ones(n)),
        constraints=LinearConstraint(tie_matrix, tie_lower, tie_upper),
        options={"presolve": True},
    )
    if not bool(tie.success) or int(tie.status) != 0:
        raise RuntimeError(
            f"carbon timing tie-break MILP failed: status={tie.status}, "
            f"message={tie.message}"
        )
    selected: dict[int, Candidate] = {}
    for spec in station_specs:
        matching = [
            (float(tie.x[column]), candidate)
            for column, (candidate_spec, candidate, _) in enumerate(variables)
            if candidate_spec.index == spec.index
        ]
        value, candidate = max(matching, key=lambda item: item[0])
        if value < 0.5:
            raise RuntimeError("MILP returned no integral candidate for an action")
        selected[spec.index] = candidate
    selected_carbon = sum(item.predicted_kg for item in selected.values())
    if selected_carbon > optimum + 1.0e-7:
        raise RuntimeError(
            f"tie-break changed primary carbon optimum: "
            f"{selected_carbon}>{optimum}"
        )
    return selected, {
        "solver": "scipy.optimize.milp/HiGHS",
        "variables": n,
        "mip_status": "OPTIMAL",
        "primary_optimum_predicted_kg": optimum,
        "selected_predicted_kg": selected_carbon,
        "primary_mip_gap": float(getattr(primary, "mip_gap", 0.0) or 0.0),
        "tie_mip_gap": float(getattr(tie, "mip_gap", 0.0) or 0.0),
    }


def schedule_carbon(
    specs: Sequence[ActionSpec],
    scored: dict[int, tuple[Candidate, ...]],
) -> tuple[dict[int, Candidate], list[dict[str, Any]]]:
    selected: dict[int, Candidate] = {}
    diagnostics: list[dict[str, Any]] = []
    by_station: dict[str, list[ActionSpec]] = defaultdict(list)
    for spec in specs:
        by_station[spec.station_id].append(spec)
    for station_id, station_specs in sorted(by_station.items()):
        station_selected, diag = solve_station_carbon(
            station_specs,
            scored,
        )
        selected.update(station_selected)
        diagnostics.append(
            {
                "station_id": station_id,
                "action_count": len(station_specs),
                **diag,
            }
        )
    return selected, diagnostics


def solution_at(
    source: Solution,
    selected: dict[int, Candidate],
) -> Solution:
    if set(selected) != set(range(len(source.charging_actions))):
        raise RuntimeError("timing selection does not cover all charging actions")
    return Solution(
        routes=list(source.routes),
        charging_actions=[
            replace(
                action,
                charge_start_second=float(selected[index].start),
            )
            for index, action in enumerate(source.charging_actions)
        ],
        cross_site_services=list(source.cross_site_services),
    )


def violation_row(
    *,
    instance_id: str,
    seed: int,
    grid_date: str,
    arm: str,
    violation: Any,
) -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "instance_id": instance_id,
        "seed": seed,
        "grid_date": grid_date,
        "arm": arm,
        "violation_type": violation.type,
        "vehicle_id": violation.vehicle_id,
        "location": violation.location,
        "detail": violation.detail,
        "severity": violation.severity,
    }


def independent_score(
    solution: Solution,
    bundle: Any,
) -> tuple[dict[str, float], list[Any], float]:
    exact_objective, exact_breakdown, exact_violations = exact_china81_score(
        solution,
        bundle,
    )
    annotated = annotate_cross_site_services(
        solution,
        bundle.customer_home_depot,
    )
    independent_violations = check_solution(
        annotated,
        bundle.instance,
        bundle.prices,
    )
    independent_breakdown = evaluate(
        annotated,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    if [
        asdict(item) for item in exact_violations
    ] != [
        asdict(item) for item in independent_violations
    ]:
        raise RuntimeError("exact and independent violation ledgers disagree")
    fields = sorted(set(exact_breakdown) | set(independent_breakdown))
    max_residual = max(
        abs(
            float(exact_breakdown[field])
            - float(independent_breakdown[field])
        )
        for field in fields
    )
    if abs(float(exact_objective) - float(exact_breakdown["total_cost"])) > TOL:
        raise RuntimeError("exact objective does not close to total_cost")
    if max_residual > TOL:
        raise RuntimeError(
            f"independent evaluator residual {max_residual} exceeds tolerance"
        )
    return exact_breakdown, exact_violations, max_residual


def classify_immovable(
    spec: ActionSpec,
    asap: Candidate,
    carbon: Candidate,
    choices: Sequence[Candidate],
) -> str | None:
    if abs(float(asap.start) - float(carbon.start)) > START_TOL:
        return None
    if len({round(choice.start, 6) for choice in choices}) <= 1:
        return "WINDOW_TOO_NARROW"
    individual_best = min(choice.predicted_kg for choice in choices)
    if asap.predicted_kg <= individual_best + 1.0e-9:
        return "ALREADY_LOWEST_CARBON"
    if spec.station_type == "d":
        return "DEPOT_CAPACITY_CONSTRAINED"
    return "UNCLASSIFIED_IMMOVABLE"


def process_solution_day(
    *,
    source: Solution,
    source_meta: dict[str, Any],
    specs: Sequence[ActionSpec],
    bundle: Any,
    source_fixed_hash: str,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    scored = score_candidates(source, specs, bundle)
    asap_selected = schedule_asap(specs, scored)
    carbon_selected, solver_diagnostics = schedule_carbon(specs, scored)
    asap_solution = solution_at(source, asap_selected)
    carbon_solution = solution_at(source, carbon_selected)

    if (
        canonical_hash(fixed_solution_payload(asap_solution))
        != source_fixed_hash
        or canonical_hash(fixed_solution_payload(carbon_solution))
        != source_fixed_hash
    ):
        raise RuntimeError("fixed route/vehicle/service/energy invariant changed")

    asap_breakdown, asap_violations, asap_residual = independent_score(
        asap_solution,
        bundle,
    )
    carbon_breakdown, carbon_violations, carbon_residual = independent_score(
        carbon_solution,
        bundle,
    )
    violations = [
        violation_row(
            instance_id=source_meta["instance_id"],
            seed=int(source_meta["seed"]),
            grid_date=bundle.date,
            arm=arm,
            violation=violation,
        )
        for arm, arm_violations in (
            ("ASAP", asap_violations),
            ("CARBON", carbon_violations),
        )
        for violation in arm_violations
    ]

    total_energy = sum(
        float(action.energy_kwh)
        for action in source.charging_actions
    )
    movable_energy = 0.0
    reason_energy: Counter[str] = Counter()
    action_rows: list[dict[str, Any]] = []
    for spec in specs:
        action = source.charging_actions[spec.index]
        asap = asap_selected[spec.index]
        carbon = carbon_selected[spec.index]
        moved = abs(asap.start - carbon.start) > START_TOL
        if moved:
            movable_energy += float(action.energy_kwh)
            reason = "MOVED"
        else:
            reason = classify_immovable(
                spec,
                asap,
                carbon,
                scored[spec.index],
            )
            if reason is None:
                raise RuntimeError("immovable classification returned None")
            reason_energy[reason] += float(action.energy_kwh)
        action_rows.append(
            {
                "task_id": TASK_ID,
                "instance_id": source_meta["instance_id"],
                "region": source_meta["region"],
                "customer_size": source_meta["customer_size"],
                "map_index": source_meta["map_index"],
                "seed": source_meta["seed"],
                "grid_date": bundle.date,
                "action_index": spec.index,
                "vehicle_id": spec.vehicle_id,
                "station_id": spec.station_id,
                "station_type": spec.station_type,
                "station_city": spec.station_city,
                "station_capacity": spec.capacity,
                "energy_kwh": float(action.energy_kwh),
                "occupancy_minutes": float(action.occupancy_minutes),
                "start_energy_kwh": action.start_energy_kwh,
                "end_energy_kwh": action.end_energy_kwh,
                "charging_curve_id": action.charging_curve_id,
                "earliest_start_second": spec.earliest,
                "latest_start_second": spec.latest,
                "candidate_count": len(spec.starts),
                "asap_start_second": asap.start,
                "carbon_start_second": carbon.start,
                "start_moved": int(moved),
                "immovable_reason": "" if moved else reason,
                "asap_predicted_emissions_kg": asap.predicted_kg,
                "carbon_predicted_emissions_kg": carbon.predicted_kg,
                "asap_actual_emissions_kg": asap.actual_kg,
                "carbon_actual_emissions_kg": carbon.actual_kg,
            }
        )

    if abs(
        total_energy
        - movable_energy
        - sum(reason_energy.values())
    ) > 1.0e-7:
        raise RuntimeError("movable/immovable energy ledger does not close")
    charging_asap = float(asap_breakdown["E_ev_indirect"])
    charging_carbon = float(carbon_breakdown["E_ev_indirect"])
    total_asap = float(asap_breakdown["E_total"])
    total_carbon = float(carbon_breakdown["E_total"])
    elec_asap = float(asap_breakdown["cost_elec"])
    elec_carbon = float(carbon_breakdown["cost_elec"])
    row = {
        "task_id": TASK_ID,
        "pair_id": (
            f"{source_meta['instance_id']}__seed{source_meta['seed']}"
            f"__{bundle.date}"
        ),
        "instance_id": source_meta["instance_id"],
        "region": source_meta["region"],
        "customer_size": source_meta["customer_size"],
        "map_index": source_meta["map_index"],
        "seed": source_meta["seed"],
        "grid_date": bundle.date,
        "fixed_solution_sha256": source_fixed_hash,
        "source_witness_sha256": source_meta["witness_sha256"],
        "route_count": len(source.routes),
        "charging_action_count": len(source.charging_actions),
        "charging_energy_kwh": total_energy,
        "city_count": len({spec.station_city for spec in specs}),
        "cities": "|".join(sorted({spec.station_city for spec in specs})),
        "asap_charging_emissions_kg": charging_asap,
        "carbon_charging_emissions_kg": charging_carbon,
        "charging_emissions_change_pct": (
            100.0 * (charging_carbon - charging_asap) / charging_asap
        ),
        "charging_emissions_reduction_pct": (
            100.0 * (charging_asap - charging_carbon) / charging_asap
        ),
        "asap_system_total_emissions_kg": total_asap,
        "carbon_system_total_emissions_kg": total_carbon,
        "system_total_emissions_change_pct": (
            100.0 * (total_carbon - total_asap) / total_asap
        ),
        "system_total_emissions_reduction_pct": (
            100.0 * (total_asap - total_carbon) / total_asap
        ),
        "asap_charging_electricity_cost_cny": elec_asap,
        "carbon_charging_electricity_cost_cny": elec_carbon,
        "charging_electricity_cost_change_pct": (
            100.0 * (elec_carbon - elec_asap) / elec_asap
        ),
        "charging_electricity_cost_reduction_pct": (
            100.0 * (elec_asap - elec_carbon) / elec_asap
        ),
        "asap_full_model_cost_cny": float(asap_breakdown["total_cost"]),
        "carbon_full_model_cost_cny": float(carbon_breakdown["total_cost"]),
        "movable_energy_kwh": movable_energy,
        "movable_energy_share_pct": 100.0 * movable_energy / total_energy,
        "immovable_energy_kwh": total_energy - movable_energy,
        "immovable_energy_share_pct": (
            100.0 * (total_energy - movable_energy) / total_energy
        ),
        "window_too_narrow_kwh": reason_energy["WINDOW_TOO_NARROW"],
        "already_lowest_carbon_kwh": reason_energy["ALREADY_LOWEST_CARBON"],
        "depot_capacity_constrained_kwh": reason_energy[
            "DEPOT_CAPACITY_CONSTRAINED"
        ],
        "unclassified_immovable_kwh": reason_energy[
            "UNCLASSIFIED_IMMOVABLE"
        ],
        "asap_violation_count": len(asap_violations),
        "carbon_violation_count": len(carbon_violations),
        "independent_max_residual": max(asap_residual, carbon_residual),
        "fixed_invariants_match": 1,
        "forecast_equals_actual_profile": 1,
        "search_candidate_count": 0,
    }
    return row, action_rows, violations, solver_diagnostics


def process_instance(
    instance_id: str,
    source_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    started_cpu = time.process_time()
    first_bundle = load_e4_bundle(instance_id, DATES[0])
    prepared: list[
        tuple[dict[str, Any], Solution, str, tuple[ActionSpec, ...]]
    ] = []
    source_checks: list[dict[str, Any]] = []
    for meta in sorted(source_rows, key=lambda row: int(row["seed"])):
        witness = read_json(ROOT / meta["witness_path"])
        source = solution_from_dict(witness["solution"])
        fixed_hash = canonical_hash(fixed_solution_payload(source))
        if fixed_hash != meta["fixed_solution_sha256"]:
            raise RuntimeError("parent/worker fixed-solution hash mismatch")
        _, source_violations, source_residual = independent_score(
            source,
            first_bundle,
        )
        source_checks.append(
            {
                "instance_id": instance_id,
                "seed": meta["seed"],
                "violation_count": len(source_violations),
                "independent_max_residual": source_residual,
            }
        )
        prepared.append(
            (
                meta,
                source,
                fixed_hash,
                prepare_action_specs(source, first_bundle),
            )
        )

    raw_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    solver_diags: list[dict[str, Any]] = []
    for grid_date in DATES:
        bundle = (
            first_bundle
            if grid_date == DATES[0]
            else load_e4_bundle(instance_id, grid_date)
        )
        for meta, source, fixed_hash, specs in prepared:
            row, actions, unit_violations, diagnostics = process_solution_day(
                source=source,
                source_meta=meta,
                specs=specs,
                bundle=bundle,
                source_fixed_hash=fixed_hash,
            )
            raw_rows.append(row)
            action_rows.extend(actions)
            violations.extend(unit_violations)
            for diag in diagnostics:
                solver_diags.append(
                    {
                        "instance_id": instance_id,
                        "seed": meta["seed"],
                        "grid_date": grid_date,
                        **diag,
                    }
                )
    return {
        "instance_id": instance_id,
        "raw_rows": raw_rows,
        "action_rows": action_rows,
        "violations": violations,
        "solver_diagnostics": solver_diags,
        "source_checks": source_checks,
        "worker_cpu_seconds": time.process_time() - started_cpu,
    }


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for field in row:
            if field not in seen:
                fields.append(field)
                seen.add(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def pooled_summary(
    rows: Sequence[dict[str, Any]],
    *,
    level: str,
    label: str,
) -> dict[str, Any]:
    asap_charge = sum(float(row["asap_charging_emissions_kg"]) for row in rows)
    carbon_charge = sum(
        float(row["carbon_charging_emissions_kg"]) for row in rows
    )
    asap_total = sum(
        float(row["asap_system_total_emissions_kg"]) for row in rows
    )
    carbon_total = sum(
        float(row["carbon_system_total_emissions_kg"]) for row in rows
    )
    asap_elec = sum(
        float(row["asap_charging_electricity_cost_cny"]) for row in rows
    )
    carbon_elec = sum(
        float(row["carbon_charging_electricity_cost_cny"]) for row in rows
    )
    energy = sum(float(row["charging_energy_kwh"]) for row in rows)
    movable = sum(float(row["movable_energy_kwh"]) for row in rows)
    unit_effects = np.asarray(
        [float(row["charging_emissions_reduction_pct"]) for row in rows],
        dtype=float,
    )
    return {
        "summary_level": level,
        "summary_label": label,
        "row_count": len(rows),
        "solution_count": len(
            {(row["instance_id"], int(row["seed"])) for row in rows}
        ),
        "grid_day_count": len({row["grid_date"] for row in rows}),
        "asap_charging_emissions_kg": asap_charge,
        "carbon_charging_emissions_kg": carbon_charge,
        "charging_emissions_reduction_pct": (
            100.0 * (asap_charge - carbon_charge) / asap_charge
        ),
        "unit_reduction_min_pct": float(np.min(unit_effects)),
        "unit_reduction_q1_pct": float(np.quantile(unit_effects, 0.25)),
        "unit_reduction_median_pct": float(np.quantile(unit_effects, 0.50)),
        "unit_reduction_q3_pct": float(np.quantile(unit_effects, 0.75)),
        "unit_reduction_max_pct": float(np.max(unit_effects)),
        "asap_system_total_emissions_kg": asap_total,
        "carbon_system_total_emissions_kg": carbon_total,
        "system_total_emissions_reduction_pct": (
            100.0 * (asap_total - carbon_total) / asap_total
        ),
        "asap_charging_electricity_cost_cny": asap_elec,
        "carbon_charging_electricity_cost_cny": carbon_elec,
        "charging_electricity_cost_reduction_pct": (
            100.0 * (asap_elec - carbon_elec) / asap_elec
        ),
        "charging_energy_kwh": energy,
        "movable_energy_kwh": movable,
        "movable_energy_share_pct": 100.0 * movable / energy,
        "immovable_energy_kwh": energy - movable,
        "immovable_energy_share_pct": 100.0 * (energy - movable) / energy,
        "window_too_narrow_kwh": sum(
            float(row["window_too_narrow_kwh"]) for row in rows
        ),
        "already_lowest_carbon_kwh": sum(
            float(row["already_lowest_carbon_kwh"]) for row in rows
        ),
        "depot_capacity_constrained_kwh": sum(
            float(row["depot_capacity_constrained_kwh"]) for row in rows
        ),
        "unclassified_immovable_kwh": sum(
            float(row["unclassified_immovable_kwh"]) for row in rows
        ),
        "asap_violation_count": sum(
            int(row["asap_violation_count"]) for row in rows
        ),
        "carbon_violation_count": sum(
            int(row["carbon_violation_count"]) for row in rows
        ),
        "max_independent_residual": max(
            float(row["independent_max_residual"]) for row in rows
        ),
    }


def build_group_summaries(
    raw_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    out = [pooled_summary(raw_rows, level="overall", label="all")]
    for region in ("jjj", "prd", "cy"):
        group = [row for row in raw_rows if row["region"] == region]
        out.append(pooled_summary(group, level="region", label=region))
    for size in SIZE_AXIS:
        group = [
            row
            for row in raw_rows
            if int(row["customer_size"]) == size
        ]
        out.append(
            pooled_summary(group, level="customer_size", label=str(size))
        )
    for region in ("jjj", "prd", "cy"):
        for size in SIZE_AXIS:
            group = [
                row
                for row in raw_rows
                if row["region"] == region
                and int(row["customer_size"]) == size
            ]
            out.append(
                pooled_summary(
                    group,
                    level="region_x_customer_size",
                    label=f"{region}__{size}",
                )
            )
    return out


def build_day_boxplots(
    raw_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for grid_date in DATES:
        date_rows = [row for row in raw_rows if row["grid_date"] == grid_date]
        for region in ("overall", "jjj", "prd", "cy"):
            rows = (
                date_rows
                if region == "overall"
                else [row for row in date_rows if row["region"] == region]
            )
            summary = pooled_summary(
                rows,
                level="grid_date_region",
                label=f"{grid_date}__{region}",
            )
            out.append(
                {
                    "grid_date": grid_date,
                    "region": region,
                    **{
                        key: value
                        for key, value in summary.items()
                        if key not in {"summary_level", "summary_label"}
                    },
                }
            )
    return out


def effective_intervals(
    group_summaries: Sequence[dict[str, Any]],
) -> list[list[int]]:
    active = [
        size
        for size in SIZE_AXIS
        if round(
            float(
                next(
                    row["charging_emissions_reduction_pct"]
                    for row in group_summaries
                    if row["summary_level"] == "customer_size"
                    and int(row["summary_label"]) == size
                )
            ),
            2,
        )
        != 0.0
    ]
    if not active:
        return []
    intervals: list[list[int]] = []
    current = [active[0], active[0]]
    for size in active[1:]:
        previous_index = SIZE_AXIS.index(current[1])
        if previous_index + 1 < len(SIZE_AXIS) and SIZE_AXIS[
            previous_index + 1
        ] == size:
            current[1] = size
        else:
            intervals.append(current)
            current = [size, size]
    intervals.append(current)
    return intervals


def reason_summary(
    overall: dict[str, Any],
) -> list[dict[str, Any]]:
    total = float(overall["charging_energy_kwh"])
    immovable = float(overall["immovable_energy_kwh"])
    fields = (
        ("WINDOW_TOO_NARROW", "window_too_narrow_kwh"),
        ("ALREADY_LOWEST_CARBON", "already_lowest_carbon_kwh"),
        (
            "DEPOT_CAPACITY_CONSTRAINED",
            "depot_capacity_constrained_kwh",
        ),
        ("UNCLASSIFIED_IMMOVABLE", "unclassified_immovable_kwh"),
    )
    return [
        {
            "reason": reason,
            "energy_kwh": float(overall[field]),
            "share_of_all_energy_pct": (
                100.0 * float(overall[field]) / total
            ),
            "share_of_immovable_energy_pct": (
                100.0 * float(overall[field]) / immovable
                if immovable > TOL
                else 0.0
            ),
        }
        for reason, field in fields
    ]


def md_float(value: Any, decimals: int) -> str:
    return f"{float(value):.{decimals}f}"


def render_report(
    *,
    overall: dict[str, Any],
    group_summaries: Sequence[dict[str, Any]],
    day_rows: Sequence[dict[str, Any]],
    reasons: Sequence[dict[str, Any]],
    intervals: Sequence[Sequence[int]],
    verdict: str,
    evidence_status: str,
    worker_mode: str,
    workers_used: int,
    runtime_wall: float,
    runtime_cpu: float,
    verification: dict[str, Any],
) -> str:
    region_rows = {
        row["summary_label"]: row
        for row in group_summaries
        if row["summary_level"] == "region"
    }
    size_rows = [
        row
        for row in group_summaries
        if row["summary_level"] == "customer_size"
    ]
    overall_days = [row for row in day_rows if row["region"] == "overall"]
    day_pooled = [
        float(row["charging_emissions_reduction_pct"])
        for row in overall_days
    ]
    interval_text = (
        "、".join(
            f"[{interval[0]}, {interval[1]}]"
            for interval in intervals
        )
        if intervals
        else "无"
    )
    verdict_text = {
        "POSITIVE": (
            "总体主要终点按预注册 0.01% 精度为正向。该结论只描述冻结的 "
            "405 个 MV 解、28 个电网日和预测等于结算碳强度的 v3 情景，"
            "不外推为一般规律。"
        ),
        "NEAR_ZERO": (
            "总体主要终点按预注册 0.01% 精度接近零。"
            "在本情景的碳强度波动幅度下择时空间有限。全部地区、规模、"
            "地图、种子和电网日仍保留，未删除数据或挑选子集；"
            "该分类不是等效性检验。"
        ),
        "NEGATIVE": (
            "总体主要终点按预注册 0.01% 精度为负向。负向结果原样保留，"
            "未删除单元、挑选子集或追加预算救援。"
        ),
        "DRAFT_INVALID": (
            "结果矩阵已保留，但独立检查、守恒或原因分类未闭合，"
            "因此不能发布科学结论。"
        ),
    }[verdict]
    lines = [
        "# E4-CARBON-TIMING-01：固定路线下的碳感知充电择时",
        "",
        f"**证据状态**：`{evidence_status}`  ",
        f"**预注册结局**：`{verdict}`",
        "",
        "## 结论",
        "",
        verdict_text,
        "",
        (
            f"总体充电侧间接排放由 "
            f"{md_float(overall['asap_charging_emissions_kg'], 3)} kgCO2e "
            f"变为 {md_float(overall['carbon_charging_emissions_kg'], 3)} "
            f"kgCO2e，减幅 "
            f"{md_float(overall['charging_emissions_reduction_pct'], 2)}%。"
            f"系统总排放减幅为 "
            f"{md_float(overall['system_total_emissions_reduction_pct'], 2)}%，"
            f"充电电费减幅为 "
            f"{md_float(overall['charging_electricity_cost_reduction_pct'], 2)}%，"
            f"实际移动电量占比为 "
            f"{md_float(overall['movable_energy_share_pct'], 1)}%。"
        ),
        "",
        (
            "沿预注册客户规模轴的观测有效区间为 "
            f"{interval_text}。这里的“有效区间”只表示主要减幅按 0.01% "
            "精度不再显示为零，不是统计显著性或等效性结论。"
        ),
        "",
        "## 总体与城市群",
        "",
        "| 层级 | 解数 | 配对日单元 | 充电排放减幅(%) | 总排放减幅(%) | 充电电费减幅(%) | 可移动电量(%) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, row in [
        ("总体", overall),
        ("京津冀", region_rows["jjj"]),
        ("珠三角", region_rows["prd"]),
        ("成渝", region_rows["cy"]),
    ]:
        lines.append(
            f"| {label} | {row['solution_count']} | {row['row_count']} | "
            f"{md_float(row['charging_emissions_reduction_pct'], 2)} | "
            f"{md_float(row['system_total_emissions_reduction_pct'], 2)} | "
            f"{md_float(row['charging_electricity_cost_reduction_pct'], 2)} | "
            f"{md_float(row['movable_energy_share_pct'], 1)} |"
        )
    lines.extend(
        [
            "",
            "百分比均以汇总层分子、分母分别求和后计算，不是单元百分比的简单平均。",
            "",
            "## 分规模",
            "",
            "| 客户数 | 解数 | 配对日单元 | 充电排放减幅(%) | 总排放减幅(%) | 电费减幅(%) | 可移动电量(%) |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in sorted(size_rows, key=lambda item: int(item["summary_label"])):
        lines.append(
            f"| {row['summary_label']} | {row['solution_count']} | "
            f"{row['row_count']} | "
            f"{md_float(row['charging_emissions_reduction_pct'], 2)} | "
            f"{md_float(row['system_total_emissions_reduction_pct'], 2)} | "
            f"{md_float(row['charging_electricity_cost_reduction_pct'], 2)} | "
            f"{md_float(row['movable_energy_share_pct'], 1)} |"
        )
    lines.extend(
        [
            "",
            "完整的 27 个“城市群×规模”单元见 `group_summary.csv`。",
            "",
            "## 28 日分布",
            "",
            (
                "逐日电网日的 405 个配对效应箱线数据见 `day_boxplot.csv`。"
                f"28 个日汇总减幅的范围为 {min(day_pooled):.2f}% 至 "
                f"{max(day_pooled):.2f}%，中位数为 "
                f"{statistics.median(day_pooled):.2f}%。"
                "文件同时给出每日电网日总体及三个城市群的最小值、"
                "Q1、中位数、Q3、最大值和汇总效应。"
            ),
            "",
            "## 不可移动电量",
            "",
            (
                f"不可移动电量为 "
                f"{md_float(overall['immovable_energy_kwh'], 2)} kWh，"
                f"占全部充电电量 "
                f"{md_float(overall['immovable_energy_share_pct'], 1)}%。"
            ),
            "",
            "| 原因 | 电量(kWh) | 占全部电量(%) | 占不可移动电量(%) |",
            "|---|---:|---:|---:|",
        ]
    )
    reason_labels = {
        "WINDOW_TOO_NARROW": "窗口太窄",
        "ALREADY_LOWEST_CARBON": "ASAP 已在最低碳时段",
        "DEPOT_CAPACITY_CONSTRAINED": "车场容量受限",
        "UNCLASSIFIED_IMMOVABLE": "未分类（触发无效）",
    }
    for row in reasons:
        lines.append(
            f"| {reason_labels[row['reason']]} | "
            f"{md_float(row['energy_kwh'], 2)} | "
            f"{md_float(row['share_of_all_energy_pct'], 1)} | "
            f"{md_float(row['share_of_immovable_energy_pct'], 1)} |"
        )
    lines.extend(
        [
            "",
            "会话级候选窗口、两臂开始时刻和原因标签见 `action_timing_audit.csv`。",
            "",
            "## 可行性、守恒与独立复算",
            "",
            (
                f"输入源解复算 {verification['source_solution_checks']} 个；"
                f"两臂独立复算 {verification['arm_solution_checks']} 个；"
                f"ASAP 违约 {verification['asap_violation_count']} 个，"
                f"CARBON 违约 {verification['carbon_violation_count']} 个。"
                f"评价器最大闭合残差为 "
                f"{verification['max_independent_residual']:.3e}。"
            ),
            "",
            (
                "每一行都验证路线、客户服务、车辆、充电站、充电量、"
                "非线性充电曲线和持续时间的共同固定哈希；"
                "两臂只替换 `charge_start_second`。"
            ),
            "",
            (
                "v3 运行参数装载器把同一日历碳因子同时写入预测和结算字段，"
                "所以本报告不包含预测误差层。系统总排放差只来自充电侧"
                "间接排放，燃油直接排放和行驶结构保持不变。"
            ),
            "",
            (
                "用户指定的 v3 日历缺少后来正式放行新增的状态列，不能单独"
                "通过完整 bundle 的批准门。本任务直接使用 v3 的碳强度和"
                "充电电价，并在运行前逐行证明这些择时字段与 v4 相同；"
                "实例、道路、车辆、车队、充电设施和检查器参数由 v4 已批准"
                "bundle 外壳装载。该边界不把 v4 数值拼入 v3 的碳强度或"
                "充电电价。"
            ),
            "",
            "## 执行与并发纪律",
            "",
            (
                "系统进程列表在沙箱中不可读，预运行记录为 "
                "`PROCESS_INVENTORY_UNAVAILABLE_SANDBOX`，因此不能声称"
                "已证明没有其他实验池。"
                f"实际执行模式为 `{worker_mode}`，worker 数为 "
                f"{workers_used}（用户上限 4）；总墙钟 "
                f"{runtime_wall:.1f} s，累计 worker CPU "
                f"{runtime_cpu:.1f} s。"
            ),
            "",
            (
                "本任务完整候选搜索数为 0。SciPy/HiGHS 只求解固定会话"
                "开始时刻的 0-1 容量耦合子问题，不生成路线、车型、服务关系"
                "或充电量候选。"
            ),
            "",
            "## 文件说明",
            "",
            (
                "`raw_runs.csv` 为 11340 个“固定解×电网日”的宽表，"
                "同一行同时保存 ASAP/CARBON 排放、电费、完整模型成本、"
                "移动电量与独立检查结果。`group_summary.csv`、"
                "`day_boxplot.csv`、`immovable_reason_summary.csv` 和"
                "`action_timing_audit.csv` 是从完整原始分母机械汇总的"
                "诊断层；没有删除行或挑选子集。"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= int(args.workers) <= 4:
        raise SystemExit("--workers must be between 1 and 4")

    start_wall = time.perf_counter()
    protected_before = {
        str(path.relative_to(ROOT)): sha256_path(path)
        for path in PROTECTED
    }
    prereg = read_json(OUT / "pre_registration.json")
    if protected_before != prereg["protected_sha256_before"]:
        raise RuntimeError(
            "protected file hash differs from the frozen pre-registration"
        )
    calendar = validate_calendar()
    if calendar["sha256"] != prereg["calendar_sha256"]:
        raise RuntimeError("calendar hash differs from pre-registration")
    inputs = discover_inputs()
    write_csv(OUT / "input_manifest.csv", inputs)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in inputs:
        grouped[row["instance_id"]].append(row)
    instance_jobs = sorted(grouped.items())

    results: list[dict[str, Any]] = []
    worker_mode = "sequential"
    workers_used = 1
    parallel_error = ""
    if int(args.workers) > 1:
        try:
            with ProcessPoolExecutor(max_workers=int(args.workers)) as executor:
                futures = {
                    executor.submit(process_instance, instance_id, rows): instance_id
                    for instance_id, rows in instance_jobs
                }
                for future in as_completed(futures):
                    results.append(future.result())
            worker_mode = "process_pool"
            workers_used = int(args.workers)
        except (OSError, PermissionError) as exc:
            # Frozen mechanical fallback: discard any partial in-memory results.
            results = [
                process_instance(instance_id, rows)
                for instance_id, rows in instance_jobs
            ]
            worker_mode = "sequential_fallback_sandbox"
            workers_used = 1
            parallel_error = f"{type(exc).__name__}: {exc}"
    else:
        results = [
            process_instance(instance_id, rows)
            for instance_id, rows in instance_jobs
        ]

    raw_rows = sorted(
        [
            row
            for result in results
            for row in result["raw_rows"]
        ],
        key=lambda row: (
            row["region"],
            int(row["customer_size"]),
            int(row["map_index"]),
            row["instance_id"],
            int(row["seed"]),
            row["grid_date"],
        ),
    )
    action_rows = sorted(
        [
            row
            for result in results
            for row in result["action_rows"]
        ],
        key=lambda row: (
            row["instance_id"],
            int(row["seed"]),
            row["grid_date"],
            int(row["action_index"]),
        ),
    )
    violations = sorted(
        [
            row
            for result in results
            for row in result["violations"]
        ],
        key=lambda row: (
            row["instance_id"],
            int(row["seed"]),
            row["grid_date"],
            row["arm"],
            row["violation_type"],
        ),
    )
    source_checks = [
        row
        for result in results
        for row in result["source_checks"]
    ]
    solver_diags = [
        row
        for result in results
        for row in result["solver_diagnostics"]
    ]
    if len(raw_rows) != EXPECTED_ROWS:
        raise RuntimeError(
            f"expected {EXPECTED_ROWS} raw rows, found {len(raw_rows)}"
        )
    if len(
        {
            (row["instance_id"], int(row["seed"]), row["grid_date"])
            for row in raw_rows
        }
    ) != EXPECTED_ROWS:
        raise RuntimeError("duplicate raw pair identity")
    if len(action_rows) != sum(
        int(row["charging_action_count"]) for row in inputs
    ) * len(DATES):
        raise RuntimeError("action audit row count does not close")

    write_csv(OUT / "raw_runs.csv", raw_rows)
    write_csv(OUT / "action_timing_audit.csv", action_rows)
    write_csv(OUT / "violation_ledger.csv", violations)
    write_csv(OUT / "solver_diagnostics.csv", solver_diags)
    group_summaries = build_group_summaries(raw_rows)
    day_rows = build_day_boxplots(raw_rows)
    write_csv(OUT / "group_summary.csv", group_summaries)
    write_csv(OUT / "day_boxplot.csv", day_rows)
    overall = next(
        row
        for row in group_summaries
        if row["summary_level"] == "overall"
    )
    reasons = reason_summary(overall)
    write_csv(OUT / "immovable_reason_summary.csv", reasons)
    intervals = effective_intervals(group_summaries)

    source_violation_count = sum(
        int(row["violation_count"]) for row in source_checks
    )
    asap_violation_count = sum(
        int(row["asap_violation_count"]) for row in raw_rows
    )
    carbon_violation_count = sum(
        int(row["carbon_violation_count"]) for row in raw_rows
    )
    unclassified = float(overall["unclassified_immovable_kwh"])
    invariant_failures = sum(
        int(row["fixed_invariants_match"]) != 1 for row in raw_rows
    )
    evidence_valid = (
        len(raw_rows) == EXPECTED_ROWS
        and source_violation_count == 0
        and asap_violation_count == 0
        and carbon_violation_count == 0
        and invariant_failures == 0
        and unclassified <= TOL
        and float(overall["max_independent_residual"]) <= TOL
    )
    evidence_status = (
        "PASS_COMPLETE_ZERO_SEARCH_REPLAY"
        if evidence_valid
        else "DRAFT_INVALID_EVIDENCE_NOT_CLOSED"
    )
    rounded_primary = round(
        float(overall["charging_emissions_reduction_pct"]),
        2,
    )
    if not evidence_valid:
        verdict = "DRAFT_INVALID"
    elif rounded_primary > 0.0:
        verdict = "POSITIVE"
    elif rounded_primary < 0.0:
        verdict = "NEGATIVE"
    else:
        verdict = "NEAR_ZERO"

    protected_after = {
        str(path.relative_to(ROOT)): sha256_path(path)
        for path in PROTECTED
    }
    if protected_after != protected_before:
        raise RuntimeError("protected file changed during execution")
    runtime_wall = time.perf_counter() - start_wall
    runtime_cpu = sum(float(result["worker_cpu_seconds"]) for result in results)
    verification = {
        "schema": "resetp.e4-carbon-timing.verification.v1",
        "task_id": TASK_ID,
        "source_solution_checks": len(source_checks),
        "arm_solution_checks": len(raw_rows) * 2,
        "source_violation_count": source_violation_count,
        "asap_violation_count": asap_violation_count,
        "carbon_violation_count": carbon_violation_count,
        "fixed_invariant_failure_count": invariant_failures,
        "unclassified_immovable_kwh": unclassified,
        "max_independent_residual": float(
            overall["max_independent_residual"]
        ),
        "protected_sha256_before": protected_before,
        "protected_sha256_after": protected_after,
        "status": evidence_status,
    }
    (OUT / "independent_verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    singapore = timezone(timedelta(hours=8))
    metadata = {
        "schema": "resetp.e4-carbon-timing.metadata.v1",
        "task_id": TASK_ID,
        "created_at": datetime.now(singapore).isoformat(),
        "status": evidence_status,
        "design": "zero_search_fixed_solution_charge_start_replay",
        "input_solution_count": len(inputs),
        "grid_day_count": len(DATES),
        "expected_pair_rows": EXPECTED_ROWS,
        "observed_pair_rows": len(raw_rows),
        "action_day_rows": len(action_rows),
        "source_charging_action_count": sum(
            int(row["charging_action_count"]) for row in inputs
        ),
        "source_charging_energy_kwh": sum(
            float(row["charging_energy_kwh"]) for row in inputs
        ),
        "runtime_parameter_authority": str(
            PARAMETER_AUTHORITY.relative_to(ROOT)
        ),
        "calendar": calendar,
        "input_root": str(INPUT_ROOT.relative_to(ROOT)),
        "input_manifest_sha256": sha256_path(OUT / "input_manifest.csv"),
        "pre_registration_sha256": sha256_path(
            OUT / "pre_registration.json"
        ),
        "task_card_sha256": sha256_path(OUT / "task_card.md"),
        "runner_sha256": sha256_path(Path(__file__)),
        "python_executable": sys.executable,
        "numpy_version": np.__version__,
        "workers_requested": int(args.workers),
        "workers_used": workers_used,
        "worker_mode": worker_mode,
        "parallel_error": parallel_error,
        "process_inventory": "PROCESS_INVENTORY_UNAVAILABLE_SANDBOX",
        "runtime_wall_seconds": runtime_wall,
        "worker_cpu_seconds_sum": runtime_cpu,
        "search_candidate_count": 0,
        "metaheuristic_called": False,
        "forecast_equals_actual_profile": True,
        "protected_sha256": protected_after,
        "git_commit": os.environ.get("GIT_COMMIT", "UNRECORDED_DIRTY_WORKTREE"),
    }
    (OUT / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    decision = {
        "schema": "resetp.e4-carbon-timing.decision.v1",
        "task_id": TASK_ID,
        "evidence_status": evidence_status,
        "verdict": verdict,
        "primary_endpoint": "charging_emissions_reduction_pct",
        "primary_endpoint_value": float(
            overall["charging_emissions_reduction_pct"]
        ),
        "primary_endpoint_display_2dp": rounded_primary,
        "effective_intervals_customer_size": intervals,
        "all_rows_retained": True,
        "observed_pair_rows": len(raw_rows),
        "expected_pair_rows": EXPECTED_ROWS,
        "search_candidate_count": 0,
        "rescue_tuning": False,
        "reason": (
            "pre-registered display rule and complete independent evidence"
            if evidence_valid
            else "evidence closure failure; scientific verdict withheld"
        ),
    }
    (OUT / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = render_report(
        overall=overall,
        group_summaries=group_summaries,
        day_rows=day_rows,
        reasons=reasons,
        intervals=intervals,
        verdict=verdict,
        evidence_status=evidence_status,
        worker_mode=worker_mode,
        workers_used=workers_used,
        runtime_wall=runtime_wall,
        runtime_cpu=runtime_cpu,
        verification=verification,
    )
    (OUT / "report.md").write_text(report, encoding="utf-8")

    artifact_names = (
        "task_card.md",
        "pre_registration.json",
        "run_e4_carbon_timing.py",
        "input_manifest.csv",
        "raw_runs.csv",
        "action_timing_audit.csv",
        "violation_ledger.csv",
        "solver_diagnostics.csv",
        "group_summary.csv",
        "day_boxplot.csv",
        "immovable_reason_summary.csv",
        "independent_verification.json",
        "metadata.json",
        "decision.json",
        "report.md",
    )
    artifacts = {
        name: sha256_path(OUT / name)
        for name in artifact_names
    }
    artifact_hashes = {
        "schema": "resetp.e4-carbon-timing.artifact-hashes.v1",
        "task_id": TASK_ID,
        "artifacts": artifacts,
        "protected_sources": protected_after,
        "input_manifest_sha256": artifacts["input_manifest.csv"],
        "calendar_sha256": calendar["sha256"],
    }
    (OUT / "artifact_hashes.json").write_text(
        json.dumps(artifact_hashes, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": evidence_status,
                "verdict": verdict,
                "rows": len(raw_rows),
                "primary_reduction_pct": overall[
                    "charging_emissions_reduction_pct"
                ],
                "workers_used": workers_used,
                "worker_mode": worker_mode,
                "runtime_wall_seconds": runtime_wall,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0 if evidence_valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
