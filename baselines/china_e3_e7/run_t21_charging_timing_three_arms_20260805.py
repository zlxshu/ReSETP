#!/usr/bin/env python3
"""Independent exploratory runner for the T26 uncapped charging batch."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import platform
import sys
import tempfile
from time import perf_counter
import traceback
from typing import Any, Iterable


REPO = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
# Avoid shadowing the standard-library ``statistics`` module with the sibling
# ``baselines/china_e3_e7/statistics.py`` when this file is executed by path.
sys.path = [
    entry
    for entry in sys.path
    if Path(entry or ".").resolve() != SCRIPT_DIR
]
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for entry in (REPO / "solver/src", REPO / "models/src", PROTOTYPE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

for name in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[name] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

from route_pool_sp import run_hgs_route_pool_recombination  # noqa: E402
from setp_solver.charge_timing import select_charge_timing_start  # noqa: E402
from setp_solver.china81 import China81Bundle, load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    DEFAULT_PUBLIC_STATION_CANDIDATE_MODE,
    exact_china81_score,
)
from setp_solver.cost import (  # noqa: E402
    charging_action_slot_breakdown,
    carbon_profile_row_for_slot,
    time_profile_rows_for_node,
)
from setp_solver.instance_loader import Instance, Node  # noqa: E402
from setp_solver.model_config import ModelConfig, model_config_scope  # noqa: E402
from setp_solver.prices import PriceParameters  # noqa: E402
from setp_solver.search.multitrip_schedule import route_timing  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    Route,
    Solution,
    physical_vehicle_id,
)


SCHEMA = "resetp.t28-charging-timing-thresholded-runner.v1"
TASK_ID = "T28"
PAPER_CLAIM_ALLOWED = False
AUTHORITY = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v3_20260802"
)
MODEL_CONFIG = ModelConfig(
    strict_multitrip=True,
    depot_charger_capacity_mode="unbounded",
)
INSTANCES = (
    ("cn-cy-100c-01-V2-LOCATIONS", "CY"),
    ("cn-jjj-100c-01-V2-LOCATIONS", "JJJ"),
    ("cn-prd-100c-01-V2-LOCATIONS", "PRD"),
)
ARMS = (
    ("ASAP", "asap"),
    ("COST", "cost_min"),
    ("COST_CARBON", "cost_plus_carbon"),
)
SEEDS = tuple(range(2026080201, 2026080211))
T23_REFERENCE_ITERATIONS = {
    "cv_only": 600,
    "naive_ev": 600,
    "mechanism_ev": 800,
}
DEFAULT_FULL_ITERATIONS = {
    "cv_only": 6_000,
    "naive_ev": 6_000,
    "mechanism_ev": 8_000,
}
VIEW_ORDER = ("cv_only", "naive_ev", "mechanism_ev")
REFERENCE_CHECKPOINTS = {mode: 100 for mode in VIEW_ORDER}
REFERENCE_ARCHIVES = {mode: 24 for mode in VIEW_ORDER}
SMOKE_ITERATIONS = {mode: 60 for mode in VIEW_ORDER}
SMOKE_CHECKPOINTS = {mode: 20 for mode in VIEW_ORDER}
SMOKE_ARCHIVES = {mode: 4 for mode in VIEW_ORDER}
NO_IMPROVEMENT_SECONDS = 180.0
MINIMUM_RELATIVE_IMPROVEMENT = 0.01
SP_TIME_LIMIT_SECONDS = 10.0
MAX_UNIT_WORKERS = 3
MAX_BATCH_UNITS = 5
PROTECTED_FILES = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)

RUN_FIELDS = tuple(
    "task_id instance_id region arm charge_timing_policy seed terminal_status "
    "paper_claim_allowed full_model_objective_cny operating_cost_cny "
    "fixed_cost_cny fuel_cost_cny charging_electricity_cost_cny "
    "distance_cost_cny fuel_direct_emissions_kgco2e "
    "charging_emissions_kgco2e system_emissions_kgco2e "
    "charging_energy_kwh actual_carbon_intensity_kgco2e_per_kwh "
    "total_distance_km ev_distance_km physical_vehicle_count "
    "dispatched_cv_count dispatched_ev_count trip_count ev_trip_count "
    "completed_customer_count required_customer_count completed_demand "
    "required_demand service_redline_status violation_count "
    "violation_types_json search_objective final_full_evaluation_objective "
    "closure_error completion_success_count completion_attempt_count "
    "completion_failure_classification_original_json route_signature "
    "customer_assignment_signature directed_arc_set_signature "
    "hgs_iterations_total last_improvement_iteration wall_seconds "
    "hgs_search_end_elapsed_seconds "
    "stop_trigger_reason stop_trigger_global_iteration "
    "no_improvement_window_seconds iteration_limit_applied "
    "route_pool_mip_initial_limit_seconds route_pool_mip_actual_seconds "
    "route_pool_mip_extended route_pool_mip_extension_count "
    "route_pool_mip_status depot_charge_window_mode "
    "public_station_candidate_mode unit_succeeded failure_stage "
    "exception_type exception_message traceback_text "
    "last_persisted_state_json configured_hgs_iterations_total "
    "hgs_iterations_by_view_json hgs_iteration_limit_by_view_json "
    "iterations_by_view_reference_json hgs_stop_reasons_by_view_json "
    "hgs_stop_trigger_iterations_by_view_json "
    "hgs_last_improvement_elapsed_by_view_json "
    "hgs_no_improvement_elapsed_by_view_json "
    "last_improvement_global_iteration last_improvement_by_view_json "
    "improvement_at_any_view_limit improvement_at_total_iteration_limit "
    "charging_start_signature charging_start_times_json"
    .split()
)
IMPROVEMENT_FIELDS = tuple(
    "task_id instance_id region arm charge_timing_policy seed view "
    "improvement_sequence iteration global_iteration elapsed_seconds "
    "global_elapsed_seconds objective_before objective_after "
    "improvement_absolute improvement_relative timer_reset "
    "timer_reset_threshold_relative objective_type"
    .split()
)
FAILURE_ONLY_RUN_FIELDS = {
    "failure_stage",
    "exception_type",
    "exception_message",
    "traceback_text",
    "last_persisted_state_json",
}
SLOT_FIELDS = tuple(
    "task_id instance_id region arm charge_timing_policy seed depot_id "
    "slot_index slot_start_second slot_end_second charging_energy_kwh "
    "electricity_cost_cny charging_emissions_kgco2e"
    .split()
)
MIP_FIELDS = tuple(
    "task_id instance_id region arm charge_timing_policy seed solver "
    "mip_invoked initial_time_limit_seconds final_time_limit_seconds "
    "actual_elapsed_seconds time_limit_reached finished_before_time_limit "
    "incumbent_available status status_class optimality_proven "
    "extended extension_count extension_supported "
    "incumbent_trace_supported extension_unavailable_reason"
    .split()
)
PAIRED_FIELDS = tuple(
    "instance_id region seed baseline_arm comparison_arm "
    "baseline_actual_carbon_intensity comparison_actual_carbon_intensity "
    "intensity_layer_reduction_pct charging_emissions_reduction_pct "
    "system_emissions_reduction_pct outcome"
    .split()
)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def atomic_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: Iterable[str],
) -> None:
    fieldnames = tuple(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    field: (
                        json.dumps(
                            row.get(field),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                        if isinstance(row.get(field), (dict, list, tuple))
                        else row.get(field, "")
                    )
                    for field in fieldnames
                }
            )
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def protected_hashes() -> dict[str, str]:
    return {
        relative: file_sha256(REPO / relative)
        for relative in PROTECTED_FILES
    }


def full_manifest() -> list[dict[str, Any]]:
    return [
        {
            "task_id": (
                f"T26__{region}__{arm}__S{seed}"
            ),
            "instance_id": instance_id,
            "region": region,
            "arm": arm,
            "charge_timing_policy": policy,
            "seed": seed,
        }
        for instance_id, region in INSTANCES
        for arm, policy in ARMS
        for seed in SEEDS
    ]


def smoke_manifest() -> list[dict[str, Any]]:
    return [
        {
            "task_id": "T26_SMOKE__JJJ__COST_CARBON__S2026080201",
            "instance_id": "cn-jjj-100c-01-V2-LOCATIONS",
            "region": "JJJ",
            "arm": "COST_CARBON",
            "charge_timing_policy": "cost_plus_carbon",
            "seed": 2026080201,
        }
    ]


def preregistration(
    *,
    mode: str,
    executed_manifest: list[dict[str, Any]],
    configured_iterations: dict[str, int],
) -> dict[str, Any]:
    return {
        "schema_version": "resetp.t26-charging-timing-preregistration.v1",
        "task_id": TASK_ID,
        "created_at_utc": utc_now(),
        "created_before_any_result": True,
        "batch_type": "EXPLORATORY",
        "execution_mode": mode,
        "paper_claim_allowed": PAPER_CLAIM_ALLOWED,
        "question": (
            "在取消迭代上限、仅由相对改善至少1%重置180秒无改善计时，"
            "并把路线池MIP时限设为10秒后，三条充电择时策略的"
            "收敛轨迹、MIP实耗和完整模型读数是什么？"
        ),
        "comparisons": [
            {
                "arm": arm,
                "charge_timing_policy": policy,
            }
            for arm, policy in ARMS
        ],
        "only_changed_factor": "charge_timing_policy",
        "held_constant": {
            "instances": [item[0] for item in INSTANCES],
            "date": "instance-bound operating date; no arm override",
            "seeds": list(SEEDS),
            "iteration_budget_by_view": None,
            "iterations_by_view_record_reference_only": configured_iterations,
            "t23_reference_iterations_by_view": T23_REFERENCE_ITERATIONS,
            "iteration_budget_is_run_limit_not_scientific_stop_rule": True,
            "evaluator": "shared complete China81 evaluator",
            "checker": (
                "shared complete checker plus independent half-open-interval "
                "charging/trip overlap audit"
            ),
            "fleet_contract": "strict multitrip, fleet authority v3",
            "carbon_calendar": "same within each instance-seed pair",
            "electricity_tariff": "same within each instance-seed pair",
            "carbon_price": "unchanged active bundle value",
            "depot_charge_window_mode": DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
            "public_station_candidate_mode": (
                DEFAULT_PUBLIC_STATION_CANDIDATE_MODE
            ),
            "global_hgs_wallclock": None,
            "route_pool_mip_initial_limit_seconds": (
                SP_TIME_LIMIT_SECONDS
            ),
        },
        "pairing_unit": "same instance and same seed",
        "falsification": (
            "若三条线在48槽充电分布与每kWh实际充电碳强度上均无差异，"
            "则这些算例不支持充电时刻是可用减排杠杆的主张。"
        ),
        "full_registered_manifest": full_manifest(),
        "executed_manifest": executed_manifest,
        "stopping_boundary": {
            "automatic_no_improvement_stop_enabled": True,
            "no_improvement_wallclock_seconds_per_view": (
                NO_IMPROVEMENT_SECONDS
            ),
            "any_proxy_objective_improvement_resets_timer": False,
            "material_improvement_threshold_implemented": True,
            "minimum_relative_improvement": (
                MINIMUM_RELATIVE_IMPROVEMENT
            ),
            "fixed_iteration_limit_by_view": None,
            "fixed_iteration_limit_total": None,
            "iterations_by_view_record_reference_only": configured_iterations,
            "global_wallclock_enabled": False,
            "total_runtime_wallclock_cap_enabled": False,
        },
        "mip_backend_boundary": {
            "backend": "scipy.optimize.milp/HiGHS",
            "incumbent_callback_available": False,
            "resumable_handle_available": False,
            "extension_implemented": False,
            "time_limit_seconds": SP_TIME_LIMIT_SECONDS,
        },
        "approved_changes_from_t25": [
            "reset the timer only for relative proxy-objective improvements "
            "of at least 1 percent",
            "use 180 seconds since the last qualifying improvement",
            "use a 10-second route-pool MIP time limit",
            "configure 5 unit workers and use at most 4 units per batch",
        ],
    }


def load_bundle(instance_id: str) -> China81Bundle:
    return load_china81_bundle(
        REPO,
        instance_id,
        fleet_authority=AUTHORITY,
        model_config=MODEL_CONFIG,
    )


def common_initial(instance_id: str) -> Solution:
    witness = json.loads(
        (
            AUTHORITY / "witnesses" / f"{instance_id}.json"
        ).read_text(encoding="utf-8")
    )
    level = witness["levels"]["25"]
    if level["status"] != "CERTIFIED" or level["violations"]:
        raise RuntimeError("fleet-authority level-25 witness is not certified")
    routes: list[Route] = []
    for depot_id, depot in sorted(level["depots"].items()):
        for vehicle_type in ("cv", "ev"):
            for index, timed in enumerate(
                depot[f"{vehicle_type}_routes"], start=1
            ):
                routes.append(
                    Route(
                        vehicle_id=(
                            f"T21-INITIAL-{depot_id}-"
                            f"{vehicle_type.upper()}-{index:03d}"
                        ),
                        vehicle_type=vehicle_type,
                        home_depot_id=depot_id,
                        node_sequence=[
                            depot_id,
                            *[str(item) for item in timed["customers"]],
                            depot_id,
                        ],
                    )
                )
    return Solution(routes=routes)


def trip_index(vehicle_id: str) -> int:
    if "#T" not in vehicle_id:
        return 1
    try:
        return int(vehicle_id.rsplit("#T", 1)[1])
    except ValueError:
        return 1


def canonical_route_structure(
    solution: Solution,
    customer_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, str], list[tuple[str, str]]]:
    raw_groups: dict[str, list[Route]] = defaultdict(list)
    for route in solution.routes:
        raw_groups[physical_vehicle_id(route.vehicle_id)].append(route)
    groups: list[dict[str, Any]] = []
    for raw_id, routes in raw_groups.items():
        types = {route.vehicle_type.lower() for route in routes}
        depots = {route.home_depot_id for route in routes}
        if len(types) != 1 or len(depots) != 1:
            raise RuntimeError("one physical vehicle mixes type or depot")
        groups.append(
            {
                "_raw_id": raw_id,
                "vehicle_type": next(iter(types)),
                "home_depot_id": next(iter(depots)),
                "trips": [
                    list(route.node_sequence)
                    for route in sorted(
                        routes,
                        key=lambda item: (
                            trip_index(item.vehicle_id),
                            tuple(item.node_sequence),
                        ),
                    )
                ],
            }
        )
    groups.sort(
        key=lambda item: (
            item["vehicle_type"],
            item["home_depot_id"],
            tuple(tuple(trip) for trip in item["trips"]),
        )
    )
    counters: Counter[tuple[str, str]] = Counter()
    labels: dict[str, str] = {}
    clean: list[dict[str, Any]] = []
    for group in groups:
        identity = (group["home_depot_id"], group["vehicle_type"])
        counters[identity] += 1
        label = (
            f"{group['home_depot_id']}:{group['vehicle_type']}:"
            f"{counters[identity]:03d}"
        )
        labels[group["_raw_id"]] = label
        clean.append(
            {
                "canonical_vehicle": label,
                "vehicle_type": group["vehicle_type"],
                "home_depot_id": group["home_depot_id"],
                "trips": group["trips"],
            }
        )
    assignments: dict[str, str] = {}
    arcs: set[tuple[str, str]] = set()
    for route in solution.routes:
        label = labels[physical_vehicle_id(route.vehicle_id)]
        for node_id in route.node_sequence[1:-1]:
            if node_id in customer_ids:
                if node_id in assignments:
                    raise RuntimeError(f"customer {node_id!r} served twice")
                assignments[node_id] = label
        arcs.update(zip(route.node_sequence, route.node_sequence[1:]))
    return clean, assignments, sorted(arcs)


def overlap_audit(
    solution: Solution, bundle: China81Bundle
) -> list[dict[str, Any]]:
    timings = {
        route.vehicle_id: route_timing(
            route,
            bundle.instance,
            bundle.prices,
            charging_actions=solution.charging_actions,
        )
        for route in solution.routes
        if route.vehicle_type.lower() == "ev"
    }
    route_by_id = {route.vehicle_id: route for route in solution.routes}
    node_by_id = {node.node_id: node for node in bundle.instance.nodes}
    rows: list[dict[str, Any]] = []
    for action in solution.charging_actions:
        route = route_by_id.get(action.vehicle_id)
        station = node_by_id.get(action.station_id)
        if route is None:
            continue
        if (
            station is not None
            and station.node_type.lower() == "f"
            and action.station_id in route.node_sequence
            and int(action.charge_day_offset) == 0
        ):
            continue
        charge_start = (
            int(action.charge_day_offset) * 86_400.0
            + float(action.charge_start_second)
        )
        charge_end = charge_start + float(action.occupancy_minutes) * 60.0
        for trip_id, timing in timings.items():
            if physical_vehicle_id(trip_id) != physical_vehicle_id(
                action.vehicle_id
            ):
                continue
            overlap = max(
                0.0,
                min(charge_end, timing.return_second)
                - max(charge_start, timing.earliest_departure_second),
            )
            if overlap > 1.0e-9:
                rows.append(
                    {
                        "action_vehicle_id": action.vehicle_id,
                        "trip_vehicle_id": trip_id,
                        "overlap_seconds": float(overlap),
                    }
                )
    return rows


def slot_rows(
    spec: dict[str, Any],
    solution: Solution,
    bundle: China81Bundle,
) -> list[dict[str, Any]]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    location_ids = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
    }
    location_ids.update(
        action.station_id for action in solution.charging_actions
    )
    totals: dict[tuple[str, int], dict[str, float]] = defaultdict(
        lambda: {"energy": 0.0, "cost": 0.0, "emissions": 0.0}
    )
    for action in solution.charging_actions:
        node = nodes[action.station_id]
        profile = time_profile_rows_for_node(
            bundle.instance,
            action.station_id,
            bundle.time_profile,
        )
        price_field = (
            "depot_energy_cny_per_kwh"
            if node.node_type.lower() == "d"
            else "public_total_cny_per_kwh"
        )
        for slot in charging_action_slot_breakdown(
            action,
            bundle.instance,
            bundle.prices,
            n_slots=len(profile),
            cyclic=True,
        ):
            index = int(slot.slot_index)
            energy = float(slot.y_skt_kwh)
            profile_row = carbon_profile_row_for_slot(profile, index)
            item = totals[(action.station_id, index)]
            item["energy"] += energy
            item["cost"] += energy * float(profile_row[price_field])
            item["emissions"] += (
                energy
                * float(profile_row["actual_gco2_per_kwh"])
                / 1_000.0
            )
    rows: list[dict[str, Any]] = []
    for location_id in sorted(location_ids):
        for index in range(48):
            item = totals[(location_id, index)]
            rows.append(
                {
                    **{key: spec[key] for key in (
                        "task_id", "instance_id", "region", "arm",
                        "charge_timing_policy", "seed",
                    )},
                    "depot_id": location_id,
                    "slot_index": index,
                    "slot_start_second": index * 1_800,
                    "slot_end_second": (index + 1) * 1_800,
                    "charging_energy_kwh": item["energy"],
                    "electricity_cost_cny": item["cost"],
                    "charging_emissions_kgco2e": item["emissions"],
                }
            )
    return rows


def timing_policy_smoke() -> dict[str, Any]:
    instance = Instance(
        nodes=[Node("D0", "d", 0.0, 0.0, city="test")],
        distance_matrix=[[0.0]],
    )
    profile = [
        {
            "city": "test",
            "horizon_second_start": index * 1_800.0,
            "actual_gco2_per_kwh": carbon,
            "depot_energy_cny_per_kwh": price,
            "public_total_cny_per_kwh": price,
        }
        for index, (price, carbon) in enumerate(
            ((1.0, 500.0), (0.1, 1_000.0), (2.0, 100.0), (0.5, 200.0))
        )
    ]
    prices = PriceParameters(carbon_price=5.0)
    action = ChargingAction(
        vehicle_id="EV0",
        station_id="D0",
        energy_kwh=10.0,
        occupancy_minutes=30.0,
        charge_start_second=0.0,
    )
    starts = {
        policy: select_charge_timing_start(
            action,
            earliest_start_second=0.0,
            latest_start_second=5_400.0,
            instance=instance,
            carbon_profile=profile,
            prices=prices,
            charge_timing_policy=policy,
        )
        for policy in ("asap", "cost_min", "cost_plus_carbon")
    }
    return {
        "starts_by_policy": starts,
        "all_three_selectable": set(starts) == {
            "asap", "cost_min", "cost_plus_carbon"
        },
        "all_three_start_times_distinct": len(set(starts.values())) == 3,
    }


def unit_state_path(state_dir: Path, task_id: str) -> Path:
    return state_dir / f"{task_id}.json"


def write_unit_state(
    state_dir: Path,
    spec: dict[str, Any],
    stage: str,
    *,
    elapsed_seconds: float,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = {
        "schema_version": "resetp.t24-unit-state.v1",
        "updated_at_utc": utc_now(),
        "task": spec,
        "stage": stage,
        "elapsed_seconds": float(elapsed_seconds),
        "details": details or {},
    }
    atomic_json(unit_state_path(state_dir, str(spec["task_id"])), state)
    return state


def read_unit_state(state_dir: Path, spec: dict[str, Any]) -> dict[str, Any]:
    path = unit_state_path(state_dir, str(spec["task_id"]))
    if not path.exists():
        return {
            "stage": "NO_CHILD_STATE_PERSISTED",
            "elapsed_seconds": 0.0,
            "details": {},
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "stage": "UNIT_STATE_UNREADABLE",
            "elapsed_seconds": 0.0,
            "details": {
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            },
        }


def failure_result(
    spec: dict[str, Any],
    *,
    execution_mode: str,
    state: dict[str, Any],
    exception_type: str,
    exception_message: str,
    traceback_text: str,
) -> dict[str, Any]:
    row = {field: "" for field in RUN_FIELDS}
    row.update(
        {key: spec[key] for key in (
            "task_id", "instance_id", "region", "arm",
            "charge_timing_policy", "seed",
        )}
    )
    row.update(
        {
            "terminal_status": f"{execution_mode.upper()}_FAILED_EXCEPTION",
            "paper_claim_allowed": PAPER_CLAIM_ALLOWED,
            "unit_succeeded": False,
            "failure_stage": str(state.get("stage", "UNKNOWN")),
            "exception_type": exception_type,
            "exception_message": exception_message,
            "traceback_text": traceback_text,
            "last_persisted_state_json": state,
            "wall_seconds": float(state.get("elapsed_seconds", 0.0)),
            "service_redline_status": "NOT_EVALUATED_UNIT_FAILED",
        }
    )
    failure = {
        "task": spec,
        "terminal_status": row["terminal_status"],
        "failure_stage": row["failure_stage"],
        "exception_type": exception_type,
        "exception_message": exception_message,
        "traceback_text": traceback_text,
        "last_persisted_state": state,
    }
    return {
        "run": row,
        "improvements": [],
        "slots": [],
        "mip": None,
        "witness": {"task": spec, "failure": failure},
        "failure": failure,
    }


def run_one(
    spec: dict[str, Any],
    *,
    execution_mode: str,
    iterations: dict[str, int],
    checkpoints: dict[str, int],
    archives: dict[str, int],
    exact_elites: int,
    unit_state_dir: Path,
) -> dict[str, Any]:
    started = perf_counter()
    write_unit_state(
        unit_state_dir,
        spec,
        "STARTED",
        elapsed_seconds=0.0,
    )
    with model_config_scope(MODEL_CONFIG):
        bundle = load_bundle(str(spec["instance_id"]))
        write_unit_state(
            unit_state_dir,
            spec,
            "BUNDLE_LOADED",
            elapsed_seconds=perf_counter() - started,
        )
        initial = common_initial(str(spec["instance_id"]))
        write_unit_state(
            unit_state_dir,
            spec,
            "SEARCH_STARTING",
            elapsed_seconds=perf_counter() - started,
            details={
                "iteration_limits_by_view": None,
                "iterations_by_view_reference_only": iterations,
                "no_improvement_seconds_per_view": (
                    NO_IMPROVEMENT_SECONDS
                ),
                "route_pool_mip_time_limit_seconds": (
                    SP_TIME_LIMIT_SECONDS
                ),
            },
        )
        run = run_hgs_route_pool_recombination(
            bundle,
            initial,
            seed=int(spec["seed"]),
            hgs_seconds_per_view=None,
            exact_elites_per_view=exact_elites,
            max_archive_candidates_per_view=archives,
            sp_time_limit_seconds=SP_TIME_LIMIT_SECONDS,
            hard_home_depot_lock=False,
            max_hgs_iterations_per_view=None,
            wallclock_safety_seconds_per_view=None,
            hgs_no_improvement_seconds_per_view=(
                NO_IMPROVEMENT_SECONDS
            ),
            hgs_no_improvement_minimum_relative_improvement=(
                MINIMUM_RELATIVE_IMPROVEMENT
            ),
            exact_checkpoint_interval_iterations=checkpoints,
            preserve_base_pool_recombination=False,
            charge_timing_policy=str(spec["charge_timing_policy"]),
        )
        write_unit_state(
            unit_state_dir,
            spec,
            "SEARCH_FINISHED",
            elapsed_seconds=perf_counter() - started,
            details={
                "hgs_iterations_by_view": {
                    view: int(epoch.stats["hgs_iterations"])
                    for view, epoch in run.view_epochs.items()
                },
                "proxy_improvement_count": len(
                    run.stats["proxy_improvement_trace"]
                ),
                "route_pool_mip": run.stats["route_pool_mip"],
            },
        )
        objective, breakdown, violations = exact_china81_score(
            run.completion.solution,
            bundle,
        )
        write_unit_state(
            unit_state_dir,
            spec,
            "FINAL_EVALUATION_FINISHED",
            elapsed_seconds=perf_counter() - started,
            details={
                "final_full_evaluation_objective": float(objective),
                "shared_violation_count": len(violations),
            },
        )
    elapsed = perf_counter() - started
    customers = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    groups, assignments, arcs = canonical_route_structure(
        run.completion.solution,
        set(customers),
    )
    completed = set(assignments)
    completed_demand = sum(
        float(customers[item].demand) for item in completed
    )
    required_demand = sum(float(item.demand) for item in customers.values())
    overlaps = overlap_audit(run.completion.solution, bundle)
    all_violations = [*violations]
    if overlaps:
        all_violations.extend(
            f"INDEPENDENT_CHARGING_TRIP_OVERLAP:{item}"
            for item in overlaps
        )
    completion_trace = run.stats["complete_candidate_evaluation_trace"]
    successes = sum(
        bool(item.get("completion_succeeded"))
        for item in completion_trace
    )
    failures = [
        {
            "view": item.get("view"),
            "source": item.get("source"),
            "status": item.get("status"),
            "exception_type": item.get("exception_type"),
            "exception_message": item.get("exception_message"),
            "failure_category": item.get("failure_category"),
        }
        for item in completion_trace
        if not bool(item.get("completion_succeeded"))
    ]
    hgs_iterations_by_view = {
        view: int(run.view_epochs[view].stats["hgs_iterations"])
        for view in VIEW_ORDER
    }
    iteration_offsets: dict[str, int] = {}
    cumulative_iterations = 0
    for view in VIEW_ORDER:
        iteration_offsets[view] = cumulative_iterations
        cumulative_iterations += hgs_iterations_by_view[view]
    view_start_elapsed_seconds = {
        view: float(run.stats["view_start_elapsed_seconds"][view])
        for view in VIEW_ORDER
    }
    improvements = [
        {
            **{key: spec[key] for key in (
                "task_id", "instance_id", "region", "arm",
                "charge_timing_policy", "seed",
            )},
            **item,
            "global_iteration": (
                iteration_offsets[str(item["view"])]
                + int(item["iteration"])
            ),
            "global_elapsed_seconds": (
                view_start_elapsed_seconds[str(item["view"])]
                + float(item["elapsed_seconds"])
            ),
            "improvement_relative": (
                0.0
                if int(item["objective_before"]) == 0
                else float(item["improvement_absolute"])
                / abs(float(item["objective_before"]))
            ),
            "timer_reset": bool(item["timer_reset"]),
            "timer_reset_threshold_relative": float(
                item["timer_reset_threshold_relative"]
            ),
            "objective_type": "PyVRP integer proxy objective",
        }
        for item in run.stats["proxy_improvement_trace"]
    ]
    slots = slot_rows(spec, run.completion.solution, bundle)
    energy_closure = abs(
        sum(float(item["charging_energy_kwh"]) for item in slots)
        - float(breakdown["electricity_kwh"])
    )
    cost_closure = abs(
        sum(float(item["electricity_cost_cny"]) for item in slots)
        - float(breakdown["cost_elec"])
    )
    emissions_closure = abs(
        sum(float(item["charging_emissions_kgco2e"]) for item in slots)
        - float(breakdown["E_ev_indirect"])
    )
    if max(energy_closure, cost_closure, emissions_closure) > 1.0e-7:
        raise RuntimeError(
            "48-slot distribution does not close to the shared evaluator: "
            f"energy={energy_closure} cost={cost_closure} "
            f"emissions={emissions_closure}"
        )
    service_full = (
        completed == set(customers)
        and math.isclose(
            completed_demand,
            required_demand,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        )
    )
    mip = dict(run.stats["route_pool_mip"])
    violation_payload = [
        asdict(item) if hasattr(item, "type") else str(item)
        for item in all_violations
    ]
    charging_energy = float(breakdown["electricity_kwh"])
    hgs_stop_reasons_by_view = {
        view: str(run.view_epochs[view].stats["hgs_stop_reason"])
        for view in VIEW_ORDER
    }
    hgs_stop_trigger_iterations_by_view = {
        view: int(
            run.view_epochs[view].stats[
                "no_improvement_trigger_iteration"
            ]
        )
        for view in VIEW_ORDER
    }
    hgs_last_improvement_elapsed_by_view = {
        view: float(
            run.view_epochs[view].stats[
                "no_improvement_last_improvement_elapsed_seconds"
            ]
        )
        for view in VIEW_ORDER
    }
    hgs_no_improvement_elapsed_by_view = {
        view: float(
            run.view_epochs[view].stats[
                "no_improvement_elapsed_seconds_at_trigger"
            ]
        )
        for view in VIEW_ORDER
    }
    improvements_by_view: dict[str, list[dict[str, Any]]] = {
        view: [
            item for item in improvements if str(item["view"]) == view
        ]
        for view in VIEW_ORDER
    }
    last_improvement_by_view = {
        view: (
            int(items[-1]["iteration"])
            if items
            else 0
        )
        for view, items in improvements_by_view.items()
    }
    charging_start_times = sorted(
        {
            (
                str(action.station_id),
                int(action.charge_day_offset),
                float(action.charge_start_second),
            )
            for action in run.completion.solution.charging_actions
        }
    )
    run_row = {
        **{key: spec[key] for key in (
            "task_id", "instance_id", "region", "arm",
            "charge_timing_policy", "seed",
        )},
        "terminal_status": (
            f"{execution_mode.upper()}_PASS_ZERO_VIOLATIONS"
            if not all_violations and service_full
            else f"{execution_mode.upper()}_FAIL_REDLINE"
        ),
        "paper_claim_allowed": PAPER_CLAIM_ALLOWED,
        "full_model_objective_cny": float(objective),
        "operating_cost_cny": float(objective) - float(breakdown["cost_carbon"]),
        "fixed_cost_cny": float(breakdown["cost_fix"]),
        "fuel_cost_cny": float(breakdown["cost_fuel"]),
        "charging_electricity_cost_cny": float(breakdown["cost_elec"]),
        "distance_cost_cny": float(breakdown["cost_km"]),
        "fuel_direct_emissions_kgco2e": float(breakdown["E_cv_direct"]),
        "charging_emissions_kgco2e": float(breakdown["E_ev_indirect"]),
        "system_emissions_kgco2e": float(breakdown["E_total"]),
        "charging_energy_kwh": charging_energy,
        "actual_carbon_intensity_kgco2e_per_kwh": (
            0.0
            if charging_energy == 0.0
            else float(breakdown["E_ev_indirect"]) / charging_energy
        ),
        "total_distance_km": float(breakdown["distance_total"]) / 1_000.0,
        "ev_distance_km": float(breakdown["distance_ev"]) / 1_000.0,
        "physical_vehicle_count": int(
            breakdown["n_veh_cv"] + breakdown["n_veh_ev"]
        ),
        "dispatched_cv_count": int(breakdown["n_veh_cv"]),
        "dispatched_ev_count": int(breakdown["n_veh_ev"]),
        "trip_count": len(run.completion.solution.routes),
        "ev_trip_count": sum(
            route.vehicle_type.lower() == "ev"
            for route in run.completion.solution.routes
        ),
        "completed_customer_count": len(completed),
        "required_customer_count": len(customers),
        "completed_demand": completed_demand,
        "required_demand": required_demand,
        "service_redline_status": "PASS_FULL_SERVICE" if service_full else "FAIL",
        "violation_count": len(all_violations),
        "violation_types_json": violation_payload,
        "search_objective": float(run.completion.objective),
        "final_full_evaluation_objective": float(objective),
        "closure_error": abs(float(run.completion.objective) - float(objective)),
        "completion_success_count": successes,
        "completion_attempt_count": len(completion_trace),
        "completion_failure_classification_original_json": failures,
        "route_signature": canonical_sha256(groups),
        "customer_assignment_signature": canonical_sha256(assignments),
        "directed_arc_set_signature": canonical_sha256(arcs),
        "hgs_iterations_total": sum(
            int(epoch.stats["hgs_iterations"])
            for epoch in run.view_epochs.values()
        ),
        "last_improvement_iteration": max(
            int(item["iteration"]) for item in improvements
        ) if improvements else 0,
        "wall_seconds": elapsed,
        "hgs_search_end_elapsed_seconds": max(
            view_start_elapsed_seconds[view]
            + float(run.view_epochs[view].elapsed_seconds)
            for view in VIEW_ORDER
        ),
        "stop_trigger_reason": (
            "NO_IMPROVEMENT_WALLCLOCK_ALL_VIEWS"
            if set(hgs_stop_reasons_by_view.values())
            == {"NO_IMPROVEMENT_WALLCLOCK"}
            else "UNEXPECTED_MIXED_VIEW_STOP_REASONS"
        ),
        "stop_trigger_global_iteration": sum(
            hgs_iterations_by_view.values()
        ),
        "no_improvement_window_seconds": NO_IMPROVEMENT_SECONDS,
        "iteration_limit_applied": False,
        "route_pool_mip_initial_limit_seconds": float(
            mip["initial_time_limit_seconds"]
        ),
        "route_pool_mip_actual_seconds": float(mip["actual_elapsed_seconds"]),
        "route_pool_mip_extended": bool(mip["extended"]),
        "route_pool_mip_extension_count": int(mip["extension_count"]),
        "route_pool_mip_status": str(mip["status_class"]),
        "depot_charge_window_mode": DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
        "public_station_candidate_mode": (
            DEFAULT_PUBLIC_STATION_CANDIDATE_MODE
        ),
        "unit_succeeded": True,
        "failure_stage": "",
        "exception_type": "",
        "exception_message": "",
        "traceback_text": "",
        "last_persisted_state_json": {},
        "configured_hgs_iterations_total": 0,
        "hgs_iterations_by_view_json": hgs_iterations_by_view,
        "hgs_iteration_limit_by_view_json": {},
        "iterations_by_view_reference_json": iterations,
        "hgs_stop_reasons_by_view_json": hgs_stop_reasons_by_view,
        "hgs_stop_trigger_iterations_by_view_json": (
            hgs_stop_trigger_iterations_by_view
        ),
        "hgs_last_improvement_elapsed_by_view_json": (
            hgs_last_improvement_elapsed_by_view
        ),
        "hgs_no_improvement_elapsed_by_view_json": (
            hgs_no_improvement_elapsed_by_view
        ),
        "last_improvement_global_iteration": (
            max(int(item["global_iteration"]) for item in improvements)
            if improvements
            else 0
        ),
        "last_improvement_by_view_json": last_improvement_by_view,
        "improvement_at_any_view_limit": False,
        "improvement_at_total_iteration_limit": False,
        "charging_start_signature": canonical_sha256(charging_start_times),
        "charging_start_times_json": [list(item) for item in charging_start_times],
    }
    mip_row = {
        **{key: spec[key] for key in (
            "task_id", "instance_id", "region", "arm",
            "charge_timing_policy", "seed",
        )},
        **{field: mip.get(field) for field in MIP_FIELDS if field not in spec},
    }
    witness = {
        "task": spec,
        "solution": asdict(run.completion.solution),
        "full_breakdown": dict(breakdown),
        "violations": violation_payload,
        "independent_overlap_audit": overlaps,
        "route_structure": groups,
        "customer_assignment": assignments,
        "directed_arc_set": [list(item) for item in arcs],
        "per_view_search_instrumentation": run.stats[
            "view_search_instrumentation"
        ],
        "completion_activity": run.completion.activity,
        "slot_closure": {
            "energy_abs": energy_closure,
            "cost_abs": cost_closure,
            "emissions_abs": emissions_closure,
        },
    }
    completed_state = write_unit_state(
        unit_state_dir,
        spec,
        "COMPLETED",
        elapsed_seconds=elapsed,
        details={
            "terminal_status": run_row["terminal_status"],
            "hgs_iterations_by_view": hgs_iterations_by_view,
            "last_improvement_global_iteration": run_row[
                "last_improvement_global_iteration"
            ],
            "violation_count": run_row["violation_count"],
            "service_redline_status": run_row["service_redline_status"],
        },
    )
    run_row["last_persisted_state_json"] = completed_state
    return {
        "run": run_row,
        "improvements": improvements,
        "slots": slots,
        "mip": mip_row,
        "witness": witness,
        "failure": None,
    }


def captured_run_one(
    spec: dict[str, Any],
    *,
    execution_mode: str,
    iterations: dict[str, int],
    checkpoints: dict[str, int],
    archives: dict[str, int],
    exact_elites: int,
    unit_state_dir: Path,
) -> dict[str, Any]:
    started = perf_counter()
    try:
        return run_one(
            spec,
            execution_mode=execution_mode,
            iterations=iterations,
            checkpoints=checkpoints,
            archives=archives,
            exact_elites=exact_elites,
            unit_state_dir=unit_state_dir,
        )
    except Exception as exc:
        trace = traceback.format_exc()
        state = read_unit_state(unit_state_dir, spec)
        state = write_unit_state(
            unit_state_dir,
            spec,
            "FAILED_EXCEPTION",
            elapsed_seconds=perf_counter() - started,
            details={
                "previous_state": state,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "traceback": trace,
            },
        )
        return failure_result(
            spec,
            execution_mode=execution_mode,
            state=state,
            exception_type=type(exc).__name__,
            exception_message=str(exc),
            traceback_text=trace,
        )


def collected_rows(
    results: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    ordered = sorted(results, key=lambda item: item["run"]["task_id"])
    runs = [item["run"] for item in ordered]
    improvements = [
        row for item in ordered for row in item["improvements"]
    ]
    slots = [row for item in ordered for row in item["slots"]]
    mips = [item["mip"] for item in ordered if item["mip"] is not None]
    witnesses = [item["witness"] for item in ordered]
    failures = [item["failure"] for item in ordered if item["failure"]]
    return runs, improvements, slots, mips, witnesses, failures


def persist_batch_progress(
    output: Path,
    results: list[dict[str, Any]],
    *,
    expected_count: int,
) -> None:
    runs, improvements, slots, mips, witnesses, failures = collected_rows(
        results
    )
    successful_runs = [
        row for row in runs if bool(row.get("unit_succeeded"))
    ]
    effects, counts = paired_effects(successful_runs)
    atomic_csv(output / "raw_runs.csv", runs, RUN_FIELDS)
    atomic_csv(
        output / "improvement_trace.csv",
        improvements,
        IMPROVEMENT_FIELDS,
    )
    atomic_csv(output / "slot_distribution.csv", slots, SLOT_FIELDS)
    atomic_csv(output / "mip_timing_audit.csv", mips, MIP_FIELDS)
    atomic_csv(output / "paired_effects.csv", effects, PAIRED_FIELDS)
    atomic_json(output / "paired_counts.json", counts)
    atomic_json(
        output / "solution_witnesses.json",
        {
            "schema_version": "resetp.t24-solution-witnesses.v1",
            "paper_claim_allowed": PAPER_CLAIM_ALLOWED,
            "witnesses": witnesses,
        },
    )
    atomic_json(
        output / "failed_units.json",
        {
            "schema_version": "resetp.t24-failed-units.v1",
            "failed_unit_count": len(failures),
            "failures": failures,
        },
    )
    atomic_json(
        output / "run_progress.json",
        {
            "schema_version": "resetp.t24-run-progress.v1",
            "updated_at_utc": utc_now(),
            "expected_unit_count": expected_count,
            "materialized_unit_count": len(runs),
            "successful_unit_count": len(successful_runs),
            "failed_unit_count": len(failures),
            "materialized_task_ids": [row["task_id"] for row in runs],
            "complete": len(runs) == expected_count,
        },
    )


def paired_effects(rows: list[dict[str, Any]]) -> tuple[
    list[dict[str, Any]], dict[str, Any]
]:
    index = {
        (str(row["instance_id"]), int(row["seed"]), str(row["arm"])): row
        for row in rows
    }
    output: list[dict[str, Any]] = []
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for instance_id, region in INSTANCES:
        for seed in SEEDS:
            comparison = index.get((instance_id, seed, "COST_CARBON"))
            if comparison is None:
                continue
            for baseline_arm in ("ASAP", "COST"):
                baseline = index.get((instance_id, seed, baseline_arm))
                if baseline is None:
                    continue
                before = float(
                    baseline["actual_carbon_intensity_kgco2e_per_kwh"]
                )
                after = float(
                    comparison["actual_carbon_intensity_kgco2e_per_kwh"]
                )
                delta = before - after
                outcome = (
                    "improved" if delta > 1.0e-12
                    else "worsened" if delta < -1.0e-12
                    else "tied"
                )
                counts[baseline_arm][outcome] += 1
                output.append(
                    {
                        "instance_id": instance_id,
                        "region": region,
                        "seed": seed,
                        "baseline_arm": baseline_arm,
                        "comparison_arm": "COST_CARBON",
                        "baseline_actual_carbon_intensity": before,
                        "comparison_actual_carbon_intensity": after,
                        "intensity_layer_reduction_pct": (
                            0.0 if before == 0.0 else 100.0 * delta / before
                        ),
                        "charging_emissions_reduction_pct": (
                            0.0
                            if float(baseline["charging_emissions_kgco2e"]) == 0.0
                            else 100.0
                            * (
                                float(baseline["charging_emissions_kgco2e"])
                                - float(comparison["charging_emissions_kgco2e"])
                            )
                            / float(baseline["charging_emissions_kgco2e"])
                        ),
                        "system_emissions_reduction_pct": (
                            0.0
                            if float(baseline["system_emissions_kgco2e"]) == 0.0
                            else 100.0
                            * (
                                float(baseline["system_emissions_kgco2e"])
                                - float(comparison["system_emissions_kgco2e"])
                            )
                            / float(baseline["system_emissions_kgco2e"])
                        ),
                        "outcome": outcome,
                    }
                )
    return output, {
        "counts": {
            arm: dict(sorted(counter.items()))
            for arm, counter in sorted(counts.items())
        },
        "representative_counterexamples": {
            arm: min(
                (
                    row
                    for row in output
                    if row["baseline_arm"] == arm
                ),
                key=lambda row: float(
                    row["intensity_layer_reduction_pct"]
                ),
                default=None,
            )
            for arm in ("ASAP", "COST")
        },
    }


def artifact_hashes(output: Path) -> dict[str, str]:
    return {
        str(path.relative_to(output)): file_sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    }


def run_tasks(
    specs: list[dict[str, Any]],
    *,
    mode: str,
    workers: int,
    output: Path,
    full_iterations: dict[str, int],
) -> list[dict[str, Any]]:
    state_dir = output / "unit_states"
    state_dir.mkdir(parents=True, exist_ok=True)
    if mode == "smoke":
        configuration = {
            "iterations": SMOKE_ITERATIONS,
            "checkpoints": SMOKE_CHECKPOINTS,
            "archives": SMOKE_ARCHIVES,
            "exact_elites": 2,
        }
        results: list[dict[str, Any]] = []
        for spec in specs:
            result = captured_run_one(
                spec,
                execution_mode=mode,
                unit_state_dir=state_dir,
                **configuration,
            )
            results.append(result)
            persist_batch_progress(
                output,
                results,
                expected_count=len(specs),
            )
            print(
                f"DONE {result['run']['task_id']} "
                f"{result['run']['terminal_status']}",
                flush=True,
            )
        return sorted(results, key=lambda item: item["run"]["task_id"])
    configuration = {
        "iterations": full_iterations,
        "checkpoints": REFERENCE_CHECKPOINTS,
        "archives": REFERENCE_ARCHIVES,
        "exact_elites": 8,
    }
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                run_one,
                spec,
                execution_mode=mode,
                unit_state_dir=state_dir,
                **configuration,
            ): spec
            for spec in specs
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                trace = traceback.format_exc()
                state = read_unit_state(state_dir, spec)
                result = failure_result(
                    spec,
                    execution_mode=mode,
                    state=state,
                    exception_type=type(exc).__name__,
                    exception_message=str(exc),
                    traceback_text=trace,
                )
            results.append(result)
            persist_batch_progress(
                output,
                results,
                expected_count=len(specs),
            )
            print(
                f"DONE {result['run']['task_id']} "
                f"{result['run']['terminal_status']}",
                flush=True,
            )
    return sorted(results, key=lambda item: item["run"]["task_id"])


def numeric_median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (float(ordered[middle - 1]) + float(ordered[middle])) / 2.0


def detailed_report(
    *,
    mode: str,
    status: str,
    runs: list[dict[str, Any]],
    improvements: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    configured_iterations: dict[str, int],
    protected_unchanged: bool,
) -> str:
    successful = [row for row in runs if bool(row.get("unit_succeeded"))]
    events_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in improvements:
        events_by_task[str(row["task_id"])].append(row)
    for events in events_by_task.values():
        events.sort(key=lambda item: int(item["global_iteration"]))

    lines = [
        f"# T24 充电时刻三条线 {mode} 报告",
        "",
        "## FACT",
        "",
        f"终态：`{status}`。单元 {len(runs)}，成功 {len(successful)}，"
        f"失败 {len(failures)}。`paper_claim_allowed=false`。",
        "",
        "迭代上限："
        + " / ".join(
            f"{view}={configured_iterations[view]}" for view in VIEW_ORDER
        )
        + f"，合计 {sum(configured_iterations.values())}。"
        "这是运行上限，不是科学停机判据；"
        "本报告未设定“长期平缓”阈值。",
        "",
        "### 1. 最后改善位置与幅度变化",
        "",
        "全局迭代号按 cv_only→naive_ev→mechanism_ev 串联。"
        "首次/末次幅度是各种子首条/末条改善绝对值的中位数，"
        "只是轨迹摘要，不是平缓判据。",
        "",
        "| 地区 | 策略 | 种子:最后改善全局迭代 | 首次幅度中位数 | 末次幅度中位数 |",
        "|---|---|---|---:|---:|",
    ]
    for _, region in INSTANCES:
        for arm, _ in ARMS:
            group = sorted(
                (
                    row for row in successful
                    if row["region"] == region and row["arm"] == arm
                ),
                key=lambda item: int(item["seed"]),
            )
            positions: list[str] = []
            first_values: list[float] = []
            last_values: list[float] = []
            for row in group:
                positions.append(
                    f"{row['seed']}:{row['last_improvement_global_iteration']}"
                )
                events = events_by_task.get(str(row["task_id"]), [])
                if events:
                    first_values.append(float(events[0]["improvement_absolute"]))
                    last_values.append(float(events[-1]["improvement_absolute"]))
            lines.append(
                f"| {region} | {arm} | {', '.join(positions) or '无'} | "
                f"{numeric_median(first_values):.9g} | "
                f"{numeric_median(last_values):.9g} |"
            )

    total_limit = sum(configured_iterations.values())
    boundary_rows = [
        row for row in successful
        if bool(row.get("improvement_at_total_iteration_limit"))
    ]
    lines.extend(["", "### 2. 迭代上限边界", ""])
    if total_limit == 20_000 and boundary_rows:
        lines.append(
            f"原始轨迹中有 {len(boundary_rows)} 个单元在 "
            "`global_iteration=20000` 恰好出现新改善："
        )
        lines.extend(f"- `{row['task_id']}`" for row in boundary_rows)
    elif total_limit == 20_000:
        lines.append(
            "原始轨迹中没有单元在 `global_iteration=20000` "
            "恰好出现新改善。"
        )
    else:
        lines.append(f"本次合计迭代 {total_limit}，没有第 20000 次观察。")

    slot_vectors: dict[tuple[str, str], list[float]] = defaultdict(
        lambda: [0.0] * 48
    )
    for row in slots:
        slot_vectors[(str(row["region"]), str(row["arm"]))][
            int(row["slot_index"])
        ] += float(row["charging_energy_kwh"])
    counts = Counter(
        (str(row["region"]), str(row["arm"])) for row in successful
    )
    for key, vector in slot_vectors.items():
        divisor = max(1, counts[key])
        slot_vectors[key] = [value / divisor for value in vector]

    lines.extend(
        [
            "",
            "### 3. 48 槽分布与每 kWh 实际碳强度",
            "",
            "峰值槽是按各地区、各策略对所有地点与种子取每单元平均"
            "后的前三槽。逐车场逐槽原值见 `slot_distribution.csv`。",
            "",
            "| 地区 | 策略 | kgCO2e/kWh | 峰值槽（槽号:平均kWh） |",
            "|---|---|---:|---|",
        ]
    )
    for _, region in INSTANCES:
        for arm, _ in ARMS:
            group = [
                row for row in successful
                if row["region"] == region and row["arm"] == arm
            ]
            energy = sum(float(row["charging_energy_kwh"]) for row in group)
            emissions = sum(
                float(row["charging_emissions_kgco2e"]) for row in group
            )
            intensity = 0.0 if energy == 0.0 else emissions / energy
            vector = slot_vectors[(region, arm)]
            peaks = sorted(range(48), key=lambda index: vector[index], reverse=True)[:3]
            peaks_text = ", ".join(
                f"{index}:{vector[index]:.6f}" for index in peaks
            )
            lines.append(f"| {region} | {arm} | {intensity:.9f} | {peaks_text} |")
        pair_values: list[str] = []
        for left, right in (
            ("ASAP", "COST"),
            ("ASAP", "COST_CARBON"),
            ("COST", "COST_CARBON"),
        ):
            distance = sum(
                abs(a - b)
                for a, b in zip(
                    slot_vectors[(region, left)],
                    slot_vectors[(region, right)],
                )
            )
            pair_values.append(f"{left}-{right}={distance:.6f} kWh")
        lines.extend(["", f"{region} 平均 48 槽向量 L1 差：" + "；".join(pair_values) + "。", ""])

    lines.extend(
        [
            "### 4. 逐单元服务量、违反数与闭合误差",
            "",
            "| 单元 | 最后改善 cv/naive/mechanism/global | 客户 | 需求 | 违反数 | 闭合误差 | 终态 |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in sorted(runs, key=lambda item: str(item["task_id"])):
        if not bool(row.get("unit_succeeded")):
            lines.append(
                f"| `{row['task_id']}` | **⚠️未评价** | **⚠️未评价** | "
                f"**⚠️未评价** | **⚠️未评价** | "
                f"**⚠️未评价** | **⚠️{row['terminal_status']}** |"
            )
            continue
        last_by_view = row["last_improvement_by_view_json"]
        last_text = (
            f"{last_by_view['cv_only']}/{last_by_view['naive_ev']}/"
            f"{last_by_view['mechanism_ev']}/"
            f"{row['last_improvement_global_iteration']}"
        )
        service_ok = str(row["service_redline_status"]) == "PASS_FULL_SERVICE"
        customer_text = f"{row['completed_customer_count']}/{row['required_customer_count']}"
        demand_text = f"{float(row['completed_demand']):.9f}/{float(row['required_demand']):.9f}"
        if not service_ok:
            customer_text = f"**⚠️{customer_text}**"
            demand_text = f"**⚠️{demand_text}**"
        lines.append(
            f"| `{row['task_id']}` | {last_text} | {customer_text} | "
            f"{demand_text} | {int(row['violation_count'])} | "
            f"{float(row['closure_error']):.12g} | {row['terminal_status']} |"
        )

    lines.extend(["", "### 5. 失败单元", ""])
    if failures:
        for failure in failures:
            lines.append(
                f"- `{failure['task']['task_id']}`: {failure['exception_type']}: "
                f"{failure['exception_message']}; 最后阶段 "
                f"`{failure['failure_stage']}`。"
            )
    else:
        lines.append("无失败单元。")

    lines.extend(
        [
            "",
            "### 6. T23 HALT 记录",
            "",
            "T23 的 `HALT_T23_RUNNER_STOP_AND_FAILURE_CONTRACT_UNAVAILABLE_NO_SEARCH` "
            "原始报告保留为 `T23_HALT_record.md`。",
            "",
            "## INFERENCE",
            "",
            "改善幅度只按原始事件描述；未定义、未判定“长期平缓”。",
            "",
            "## DECISION",
            "",
            "`paper_claim_allowed=false`。所有结果不按方向筛选。",
            "",
            "## HALT_*",
            "",
            (f"`{status}`。" if status.startswith("HALT_") else "无。"),
            "",
            f"保护文件开收工 SHA-256 一致：{protected_unchanged}。",
        ]
    )
    return "\n".join(lines) + "\n"


def numeric_quantile(values: list[float], probability: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * float(probability)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def finite_improvements(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if int(event["objective_before"]) != 9_223_372_036_854_775_807
    ]


def reached_fraction_iteration(
    events: list[dict[str, Any]], fraction: float
) -> int:
    usable = finite_improvements(events)
    total = sum(float(event["improvement_absolute"]) for event in usable)
    if total <= 0.0:
        return 0
    target = total * float(fraction)
    cumulative = 0.0
    for event in sorted(usable, key=lambda item: int(item["global_iteration"])):
        cumulative += float(event["improvement_absolute"])
        if cumulative >= target:
            return int(event["global_iteration"])
    return int(usable[-1]["global_iteration"])


def t26_detailed_report(
    *,
    mode: str,
    status: str,
    runs: list[dict[str, Any]],
    improvements: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    mips: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    configured_iterations: dict[str, int],
    protected_unchanged: bool,
) -> str:
    successful = [row for row in runs if bool(row.get("unit_succeeded"))]
    events_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in improvements:
        events_by_task[str(row["task_id"])].append(row)
    for events in events_by_task.values():
        events.sort(key=lambda item: int(item["global_iteration"]))

    lines = [
        f"# T28 1% 改善门槛、180 秒停机与 10 秒 MIP {mode} 报告",
        "",
        "## FACT",
        "",
        f"终态：`{status}`。材料化单元 {len(runs)}，成功 {len(successful)}，"
        f"失败 {len(failures)}。`paper_claim_allowed=false`。",
        "",
        "HGS 不设迭代上限或总墙钟上限；三个视角各自只以相对改善至少 1% 的"
        "代理目标改善重置 180 秒计时器，低于 1% 的严格改善仍保留在轨迹。"
        "`iterations_by_view` 只保留 T25 参考记录，不参与停机。"
        f"路线池 MIP 初始时限为 {SP_TIME_LIMIT_SECONDS:.0f} 秒。",
        "",
        "### 1. 逐单元停机读数",
        "",
        "| 单元 | 总迭代数 | 最后改善全局迭代 | 触发全局迭代 | 总墙钟秒 | 触发原因 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in sorted(runs, key=lambda item: str(item["task_id"])):
        if not bool(row.get("unit_succeeded")):
            lines.append(
                f"| `{row['task_id']}` | **⚠️未完成** | **⚠️未完成** | "
                f"**⚠️未完成** | {float(row.get('wall_seconds') or 0.0):.6f} | "
                f"**⚠️{row['terminal_status']}** |"
            )
            continue
        lines.append(
            f"| `{row['task_id']}` | {int(row['hgs_iterations_total'])} | "
            f"{int(row['last_improvement_global_iteration'])} | "
            f"{int(row['stop_trigger_global_iteration'])} | "
            f"{float(row['wall_seconds']):.6f} | "
            f"{row['stop_trigger_reason']} |"
        )

    lines.extend(
        [
            "",
            "### 2. 改善幅度随发生时刻的分布",
            "",
            "每个单元以 HGS 搜索墙钟的前、中、后三分之一分段；"
            "每格依次为 `最大/中位/合计（事件数）`。"
            "各视角的 64 位无穷大哨兵到首个有限解不计入幅度。",
            "",
            "| 单元 | 前段 | 中段 | 后段 |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in sorted(successful, key=lambda item: str(item["task_id"])):
        duration = float(row["hgs_search_end_elapsed_seconds"])
        segments: list[list[float]] = [[], [], []]
        for event in finite_improvements(
            events_by_task.get(str(row["task_id"]), [])
        ):
            ratio = (
                0.0
                if duration <= 0.0
                else float(event["global_elapsed_seconds"]) / duration
            )
            index = min(2, max(0, int(ratio * 3.0)))
            segments[index].append(float(event["improvement_absolute"]))
        rendered = []
        for values in segments:
            rendered.append(
                f"{max(values, default=0.0):.9g}/"
                f"{numeric_median(values):.9g}/"
                f"{sum(values):.9g}（{len(values)}）"
            )
        lines.append(
            f"| `{row['task_id']}` | {rendered[0]} | {rendered[1]} | "
            f"{rendered[2]} |"
        )

    wall_values = [float(row["wall_seconds"]) for row in successful]
    iteration_values = [float(row["hgs_iterations_total"]) for row in successful]
    wall_q1 = numeric_quantile(wall_values, 0.25)
    wall_q3 = numeric_quantile(wall_values, 0.75)
    iteration_q1 = numeric_quantile(iteration_values, 0.25)
    iteration_q3 = numeric_quantile(iteration_values, 0.75)
    wall_cut = wall_q3 + 1.5 * (wall_q3 - wall_q1)
    iteration_cut = iteration_q3 + 1.5 * (iteration_q3 - iteration_q1)
    long_rows = [
        row
        for row in successful
        if float(row["wall_seconds"]) > wall_cut
        or float(row["hgs_iterations_total"]) > iteration_cut
    ]
    lines.extend(
        [
            "",
            "### 3. 持续改善导致的异常长单元",
            "",
            "这里只用 Tukey 描述性异常值标记：墙钟或迭代数超过各自"
            f" `Q3+1.5×IQR`（{wall_cut:.6f} 秒；{iteration_cut:.0f} 次）。"
            "该标记不作为停机阈值。",
            "",
        ]
    )
    if long_rows:
        lines.extend(
            [
                "| 单元 | 总迭代数 | 最后改善全局迭代 | 总墙钟秒 |",
                "|---|---:|---:|---:|",
            ]
        )
        for row in sorted(long_rows, key=lambda item: str(item["task_id"])):
            lines.append(
                f"| `{row['task_id']}` | {int(row['hgs_iterations_total'])} | "
                f"{int(row['last_improvement_global_iteration'])} | "
                f"{float(row['wall_seconds']):.6f} |"
            )
    else:
        lines.append("没有单元超过上述描述性异常值界限。")

    mip_elapsed = [float(row["actual_elapsed_seconds"]) for row in mips]
    mip_optimal = sum(bool(row["optimality_proven"]) for row in mips)
    mip_limited = sum(bool(row["time_limit_reached"]) for row in mips)
    lines.extend(
        [
            "",
            "### 4. 路线池 MIP 实耗",
            "",
            (
                "实耗秒 min/median/p90/max = "
                f"{min(mip_elapsed, default=0.0):.6f}/"
                f"{numeric_median(mip_elapsed):.6f}/"
                f"{numeric_quantile(mip_elapsed, 0.90):.6f}/"
                f"{max(mip_elapsed, default=0.0):.6f}。"
            ),
            f"真正求到最优并提前结束：{mip_optimal}/{len(mips)} "
            f"({(100.0 * mip_optimal / len(mips) if mips else 0.0):.3f}%)；"
            f"10 秒仍撞满：{mip_limited}/{len(mips)} "
            f"({(100.0 * mip_limited / len(mips) if mips else 0.0):.3f}%)。",
            "",
            "| 单元 | 初始时限秒 | 实耗秒 | 最优证明 | 撞满 | 状态 |",
            "|---|---:|---:|---|---|---|",
        ]
    )
    for row in sorted(mips, key=lambda item: str(item["task_id"])):
        lines.append(
            f"| `{row['task_id']}` | {float(row['initial_time_limit_seconds']):.3f} | "
            f"{float(row['actual_elapsed_seconds']):.6f} | "
            f"{bool(row['optimality_proven'])} | {bool(row['time_limit_reached'])} | "
            f"{row['status_class']} |"
        )

    slot_vectors: dict[tuple[str, str], list[float]] = defaultdict(
        lambda: [0.0] * 48
    )
    for row in slots:
        slot_vectors[(str(row["region"]), str(row["arm"]))][
            int(row["slot_index"])
        ] += float(row["charging_energy_kwh"])
    group_counts = Counter(
        (str(row["region"]), str(row["arm"])) for row in successful
    )
    for key, vector in slot_vectors.items():
        divisor = max(1, group_counts[key])
        slot_vectors[key] = [value / divisor for value in vector]

    lines.extend(
        [
            "",
            "### 5. 三条线的每 kWh 碳强度、48 槽分布与路线签名",
            "",
            "| 算例 | 策略 | 平均电量 kWh/单元 | 平均充电排放 kgCO2e/单元 | kgCO2e/kWh |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for instance_id, region in INSTANCES:
        for arm, _ in ARMS:
            group = [
                row
                for row in successful
                if row["instance_id"] == instance_id and row["arm"] == arm
            ]
            if not group:
                continue
            energy = sum(float(row["charging_energy_kwh"]) for row in group)
            emissions = sum(
                float(row["charging_emissions_kgco2e"]) for row in group
            )
            lines.append(
                f"| `{instance_id}` | {arm} | {energy / len(group):.9f} | "
                f"{emissions / len(group):.9f} | "
                f"{(0.0 if energy == 0.0 else emissions / energy):.9f} |"
            )
            vector = slot_vectors[(region, arm)]
            lines.extend(
                [
                    "",
                    f"`{region} {arm}` 48 槽均值向量：",
                    "",
                    "`" + ", ".join(f"{value:.6f}" for value in vector) + "`",
                    "",
                ]
            )

    signature_index = {
        (str(row["instance_id"]), int(row["seed"]), str(row["arm"])): str(
            row["route_signature"]
        )
        for row in successful
    }
    signature_summary: dict[str, tuple[int, int]] = {}
    for instance_id, _ in INSTANCES:
        comparable = 0
        identical = 0
        for seed in SEEDS:
            signatures = [
                signature_index.get((instance_id, seed, arm))
                for arm, _ in ARMS
            ]
            if all(signature is not None for signature in signatures):
                comparable += 1
                identical += len(set(signatures)) == 1
        signature_summary[instance_id] = (identical, comparable)
    lines.extend(["路线签名三条线全同计数：", ""])
    for instance_id, _ in INSTANCES:
        identical, comparable = signature_summary[instance_id]
        lines.append(f"- `{instance_id}`：{identical}/{comparable}。")

    lines.extend(
        [
            "",
            "### 6. 服务量红线、违反、闭合误差与失败单元",
            "",
            "| 单元 | 客户完成/要求 | 需求完成/要求 | 服务红线 | 违反数 | 闭合误差 |",
            "|---|---:|---:|---|---:|---:|",
        ]
    )
    for row in sorted(runs, key=lambda item: str(item["task_id"])):
        if not bool(row.get("unit_succeeded")):
            lines.append(
                f"| `{row['task_id']}` | **⚠️未评价** | **⚠️未评价** | "
                f"**⚠️{row['terminal_status']}** | **⚠️未评价** | **⚠️未评价** |"
            )
            continue
        service_ok = str(row["service_redline_status"]) == "PASS_FULL_SERVICE"
        customer = f"{row['completed_customer_count']}/{row['required_customer_count']}"
        demand = f"{float(row['completed_demand']):.9f}/{float(row['required_demand']):.9f}"
        if not service_ok:
            customer = f"**⚠️{customer}**"
            demand = f"**⚠️{demand}**"
        violation = int(row["violation_count"])
        violation_text = str(violation) if violation == 0 else f"**⚠️{violation}**"
        lines.append(
            f"| `{row['task_id']}` | {customer} | {demand} | "
            f"{row['service_redline_status']} | {violation_text} | "
            f"{float(row['closure_error']):.12g} |"
        )
    lines.extend(["", "失败单元清单：", ""])
    if failures:
        for failure in failures:
            lines.append(
                f"- `{failure['task']['task_id']}`："
                f"{failure['exception_type']}: {failure['exception_message']}；"
                f"最后阶段 `{failure['failure_stage']}`。"
            )
    else:
        lines.append("无失败单元。")

    lines.extend(
        [
            "",
            "### 7. 额度该怎么定：仅列事实",
            "",
            "95%/99% 指各单元三个代理视角串联后，有限改善幅度累计达到"
            "该单元最终有限改善合计的 95%/99% 时的全局迭代号；"
            "不把这一读数直接换算成推荐额度。",
            "",
            "| 算例 | 策略 | 总迭代 min/median/max | 末次改善 min/median/max | 95%迭代 min/median/max | 99%迭代 min/median/max |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for instance_id, _ in INSTANCES:
        for arm, _ in ARMS:
            group = [
                row
                for row in successful
                if row["instance_id"] == instance_id and row["arm"] == arm
            ]
            if not group:
                continue
            totals = [float(row["hgs_iterations_total"]) for row in group]
            lasts = [
                float(row["last_improvement_global_iteration"])
                for row in group
            ]
            at95 = [
                float(
                    reached_fraction_iteration(
                        events_by_task.get(str(row["task_id"]), []), 0.95
                    )
                )
                for row in group
            ]
            at99 = [
                float(
                    reached_fraction_iteration(
                        events_by_task.get(str(row["task_id"]), []), 0.99
                    )
                )
                for row in group
            ]

            def triple(values: list[float]) -> str:
                return (
                    f"{min(values):.0f}/{numeric_median(values):.1f}/"
                    f"{max(values):.0f}"
                )

            lines.append(
                f"| `{instance_id}` | {arm} | {triple(totals)} | "
                f"{triple(lasts)} | {triple(at95)} | {triple(at99)} |"
            )

    lines.extend(
        [
            "",
            "## INFERENCE",
            "",
        "本节仅采用用户已定的 1% 改善门槛，不自定其他阈值。",
            "",
            "## DECISION",
            "",
            "`paper_claim_allowed=false`。结果未按方向筛选，未挑种子，未补跑。",
            "",
            "## HALT_*",
            "",
            (f"`{status}`。" if status.startswith("HALT_") else "无。"),
            "",
            f"保护文件开收工 SHA-256 一致：{protected_unchanged}。",
        ]
    )
    return "\n".join(lines) + "\n"


def materialize(
    output: Path,
    mode: str,
    workers: int,
    full_iterations: dict[str, int],
) -> int:
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise RuntimeError("PYTHONHASHSEED must equal 0")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    specs = smoke_manifest() if mode == "smoke" else full_manifest()
    configured_iterations = (
        SMOKE_ITERATIONS if mode == "smoke" else full_iterations
    )
    before = protected_hashes()
    atomic_json(
        output / "preregistration.json",
        preregistration(
            mode=mode,
            executed_manifest=specs,
            configured_iterations=configured_iterations,
        ),
    )
    atomic_json(
        output / "metadata.pre_run.json",
        {
            "schema_version": SCHEMA,
            "status": "PREREGISTERED_BEFORE_RESULTS",
            "created_at_utc": utc_now(),
            "mode": mode,
            "paper_claim_allowed": PAPER_CLAIM_ALLOWED,
            "configured_iterations_by_view": configured_iterations,
            "protected_file_sha256_before": before,
            "environment": {
                "python": sys.version,
                "python_executable": sys.executable,
                "numpy": version("numpy"),
                "scipy": version("scipy"),
                "pyvrp": version("pyvrp"),
                "platform": platform.platform(),
                "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED"),
                "PYTHONPATH": os.environ.get("PYTHONPATH"),
            },
        },
    )
    if mode == "prepare":
        return 0
    persist_batch_progress(output, [], expected_count=len(specs))
    policy_smoke = timing_policy_smoke()
    atomic_json(output / "strategy_selection_smoke.json", policy_smoke)
    results = run_tasks(
        specs,
        mode=mode,
        workers=workers,
        output=output,
        full_iterations=full_iterations,
    )
    runs, improvements, slots, mips, _, failures = collected_rows(results)
    by_task_view: dict[tuple[str, str], list[int]] = defaultdict(list)
    for row in improvements:
        by_task_view[(str(row["task_id"]), str(row["view"]))].append(
            int(row["iteration"])
        )
    trace_monotone = all(
        all(left < right for left, right in zip(values, values[1:]))
        for values in by_task_view.values()
    )
    success_runs = [row for row in runs if bool(row.get("unit_succeeded"))]
    mandatory_success_fields = [
        field for field in RUN_FIELDS if field not in FAILURE_ONLY_RUN_FIELDS
    ]
    required_fields_present = all(
        all(row.get(field) not in (None, "") for field in mandatory_success_fields)
        for row in success_runs
    )
    actual_start_signatures = {
        str(row["arm"]): str(row["charging_start_signature"])
        for row in success_runs
    }
    improvement_counts_by_task = Counter(
        str(row["task_id"]) for row in improvements
    )
    no_improvement_elapsed_values = [
        float(value)
        for row in success_runs
        for value in row[
            "hgs_no_improvement_elapsed_by_view_json"
        ].values()
    ]
    ignored_subthreshold_improvements = [
        row
        for row in improvements
        if float(row["improvement_relative"])
        < MINIMUM_RELATIVE_IMPROVEMENT
        and not bool(row["timer_reset"])
    ]
    smoke_checks = {
        "paper_claim_allowed": PAPER_CLAIM_ALLOWED,
        "run_count": len(runs),
        "expected_run_count": len(specs),
        "successful_unit_count": len(success_runs),
        "failed_unit_count": len(failures),
        "all_registered_units_materialized": len(runs) == len(specs),
        "no_unit_failures": not failures,
        "improvement_trace_nonempty": bool(improvements),
        "improvement_row_count_by_task": {
            str(row["task_id"]): improvement_counts_by_task[str(row["task_id"])]
            for row in success_runs
        },
        "all_unit_improvement_traces_nonempty": all(
            improvement_counts_by_task[str(row["task_id"])] > 0
            for row in success_runs
        ),
        "improvement_iterations_strictly_monotone_within_view": trace_monotone,
        "mip_actual_time_recorded": all(
            float(row["actual_elapsed_seconds"]) > 0.0 for row in mips
        ),
        "mip_extension_count_values": [
            int(row["extension_count"]) for row in mips
        ],
        "mip_initial_time_limit_values": [
            float(row["initial_time_limit_seconds"]) for row in mips
        ],
        "all_mip_initial_limits_are_10_seconds": all(
            math.isclose(
                float(row["initial_time_limit_seconds"]),
                SP_TIME_LIMIT_SECONDS,
                rel_tol=0.0,
                abs_tol=0.0,
            )
            for row in mips
        ),
        "all_views_stopped_for_no_improvement_wallclock": all(
            set(row["hgs_stop_reasons_by_view_json"].values())
            == {"NO_IMPROVEMENT_WALLCLOCK"}
            for row in success_runs
        ),
        "all_unit_stop_reasons_recorded": all(
            row["stop_trigger_reason"]
            == "NO_IMPROVEMENT_WALLCLOCK_ALL_VIEWS"
            for row in success_runs
        ),
        "all_no_improvement_windows_reached_180_seconds": all(
            value >= NO_IMPROVEMENT_SECONDS
            for value in no_improvement_elapsed_values
        ),
        "no_improvement_elapsed_seconds_by_view": (
            no_improvement_elapsed_values
        ),
        "minimum_relative_improvement": MINIMUM_RELATIVE_IMPROVEMENT,
        "subthreshold_improvements_recorded_without_timer_reset": bool(
            ignored_subthreshold_improvements
        ),
        "subthreshold_improvement_count_without_timer_reset": len(
            ignored_subthreshold_improvements
        ),
        "unit_worker_setting": workers,
        "unit_worker_ceiling": MAX_UNIT_WORKERS,
        "unit_worker_setting_within_ceiling": (
            1 <= workers <= MAX_UNIT_WORKERS
        ),
        "batch_unit_ceiling": MAX_BATCH_UNITS,
        "no_iteration_limit_applied": all(
            not bool(row["iteration_limit_applied"])
            and row["hgs_iteration_limit_by_view_json"] == {}
            for row in success_runs
        ),
        "smoke_total_iterations_exceeded_t25_cap": (
            mode != "smoke"
            or all(
                int(row["hgs_iterations_total"]) > 20_000
                for row in success_runs
            )
        ),
        "all_required_run_fields_have_values": required_fields_present,
        "all_three_timing_policies_selectable": policy_smoke[
            "all_three_selectable"
        ],
        "all_three_timing_policies_have_distinct_starts": policy_smoke[
            "all_three_start_times_distinct"
        ],
        "actual_three_arm_charging_start_signatures": actual_start_signatures,
        "actual_three_arm_charging_starts_distinct": (
            len(actual_start_signatures) == 3
            and len(set(actual_start_signatures.values())) == 3
        ),
        "all_violation_counts_zero": all(
            int(row["violation_count"]) == 0 for row in success_runs
        ),
        "all_customers_and_demand_fully_served": all(
            int(row["completed_customer_count"])
            == int(row["required_customer_count"])
            and math.isclose(
                float(row["completed_demand"]),
                float(row["required_demand"]),
                rel_tol=0.0,
                abs_tol=1.0e-9,
            )
            for row in success_runs
        ),
        "closure_errors_by_task": {
            str(row["task_id"]): float(row["closure_error"])
            for row in success_runs
        },
    }
    required_check_keys = {
        "all_registered_units_materialized",
        "no_unit_failures",
        "improvement_trace_nonempty",
        "improvement_iterations_strictly_monotone_within_view",
        "mip_actual_time_recorded",
        "all_mip_initial_limits_are_10_seconds",
        "all_views_stopped_for_no_improvement_wallclock",
        "all_unit_stop_reasons_recorded",
        "all_no_improvement_windows_reached_180_seconds",
        "subthreshold_improvements_recorded_without_timer_reset",
        "unit_worker_setting_within_ceiling",
        "no_iteration_limit_applied",
        "all_required_run_fields_have_values",
        "all_three_timing_policies_selectable",
        "all_three_timing_policies_have_distinct_starts",
        "all_violation_counts_zero",
        "all_customers_and_demand_fully_served",
    }
    if mode == "smoke":
        required_check_keys.add("all_unit_improvement_traces_nonempty")
    smoke_checks["required_check_keys"] = sorted(required_check_keys)
    smoke_checks["passed"] = all(
        bool(smoke_checks[key]) for key in required_check_keys
    )
    checks_path = (
        output / "smoke_checks.json"
        if mode == "smoke"
        else output / "run_checks.json"
    )
    atomic_json(checks_path, smoke_checks)
    after = protected_hashes()
    if smoke_checks["passed"]:
        status = (
            "PASS_T28_SMOKE"
            if mode == "smoke"
            else "T28_EXPLORATORY_90_UNITS_COMPLETE"
        )
    elif failures:
        status = f"HALT_T28_{mode.upper()}_UNIT_FAILURES_RECORDED"
    else:
        status = f"HALT_T28_{mode.upper()}_VALIDATION_FAILED"
    metadata = {
        "schema_version": SCHEMA,
        "status": status,
        "created_at_utc": utc_now(),
        "mode": mode,
        "paper_claim_allowed": PAPER_CLAIM_ALLOWED,
        "run_count": len(runs),
        "successful_unit_count": len(success_runs),
        "failed_unit_count": len(failures),
        "improvement_row_count": len(improvements),
        "slot_row_count": len(slots),
        "mip_audit_row_count": len(mips),
        "protected_file_sha256_before": before,
        "protected_file_sha256_after": after,
        "protected_files_unchanged": before == after,
        "iteration_limit_by_view": None,
        "iteration_limit_total": None,
        "iterations_by_view_reference_only": configured_iterations,
        "no_improvement_wallclock_seconds_per_view": (
            NO_IMPROVEMENT_SECONDS
        ),
        "minimum_relative_improvement": MINIMUM_RELATIVE_IMPROVEMENT,
        "unit_worker_setting": workers,
        "unit_worker_ceiling": MAX_UNIT_WORKERS,
        "batch_unit_ceiling": MAX_BATCH_UNITS,
        "global_hgs_wallclock_seconds": None,
        "mip_backend_capability": {
            "scipy_milp_signature": (
                "(c, *, integrality=None, bounds=None, constraints=None, "
                "options=None)"
            ),
            "incumbent_callback_available": False,
            "resumable_handle_available": False,
            "extension_count": 0,
        },
    }
    atomic_json(output / "metadata.json", metadata)
    decision = {
        "schema_version": "resetp.t28-decision.v1",
        "status": metadata["status"],
        "FACT": smoke_checks,
        "INFERENCE": (
            "The user-specified 1-percent threshold controls timer resets; "
            "all strict improvements remain recorded."
        ),
        "DECISION": "paper_claim_allowed=false",
        "HALT": None if smoke_checks["passed"] else metadata["status"],
    }
    atomic_json(output / "decision.json", decision)
    report = t26_detailed_report(
        mode=mode,
        status=status,
        runs=runs,
        improvements=improvements,
        slots=slots,
        mips=mips,
        failures=failures,
        configured_iterations=configured_iterations,
        protected_unchanged=before == after,
    )
    atomic_text(output / "report.md", report)
    atomic_json(
        output / "done.json",
        {
            "schema_version": "resetp.t28-done.v1",
            "status": status,
            "completed_at_utc": utc_now(),
            "registered_unit_count": len(specs),
            "materialized_unit_count": len(runs),
            "successful_unit_count": len(success_runs),
            "failed_unit_count": len(failures),
            "paper_claim_allowed": PAPER_CLAIM_ALLOWED,
        },
    )
    atomic_json(
        output / "artifact_hashes.json",
        {
            "schema_version": "resetp.clean-artifact-hashes.v1",
            "excluded": ["._*", "__pycache__", ".pytest_cache"],
            "files": artifact_hashes(output),
        },
    )
    if before != after:
        raise RuntimeError("protected-file hashes changed during runner execution")
    return 0 if smoke_checks["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("prepare", "smoke", "full"),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=MAX_UNIT_WORKERS)
    parser.add_argument(
        "--cv-only-iterations",
        type=int,
        default=DEFAULT_FULL_ITERATIONS["cv_only"],
    )
    parser.add_argument(
        "--naive-ev-iterations",
        type=int,
        default=DEFAULT_FULL_ITERATIONS["naive_ev"],
    )
    parser.add_argument(
        "--mechanism-ev-iterations",
        type=int,
        default=DEFAULT_FULL_ITERATIONS["mechanism_ev"],
    )
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    if args.workers > MAX_UNIT_WORKERS:
        parser.error(
            f"--workers must not exceed {MAX_UNIT_WORKERS} for T28"
        )
    if args.mode == "smoke" and args.workers != 1:
        parser.error("smoke mode requires --workers 1")
    full_iterations = {
        "cv_only": args.cv_only_iterations,
        "naive_ev": args.naive_ev_iterations,
        "mechanism_ev": args.mechanism_ev_iterations,
    }
    if any(value < 1 for value in full_iterations.values()):
        parser.error("all HGS iteration limits must be positive")
    return materialize(
        args.output.resolve(),
        args.mode,
        args.workers,
        full_iterations,
    )


if __name__ == "__main__":
    raise SystemExit(main())
