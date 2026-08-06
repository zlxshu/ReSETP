#!/usr/bin/env python3
"""T8 draft-method probe: split route/vehicle changes from charging retiming.

This driver is isolated under the handoff directory.  It imports the T5
probe's already-audited search driver and reuses its timing selector, but it
does not modify the shared evaluator, checker, cost function, or search
evaluation module.  FIXED_ROUTE_RETIME never calls the search routine: it
copies the same-seed COST completion and changes only charge_start_second.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import UTC, datetime
import csv
import hashlib
import json
from importlib.metadata import version
import math
import os
from pathlib import Path
import sys
import tempfile
from time import perf_counter
import traceback
from typing import Any


REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
T5_DIR = REPO / "docs/handoff/carbon_objective_probe_20260804"
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for entry in (REPO, REPO / "solver/src", REPO / "models/src", PROTOTYPE, T5_DIR):
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

import probe_driver as t5  # noqa: E402
import route_pool_sp  # noqa: E402
from setp_solver.china81 import China81Bundle, load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import exact_china81_score  # noqa: E402
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.cost import (  # noqa: E402
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    charging_action_slot_breakdown,
    carbon_profile_row_for_slot,
    route_departure_second,
    time_profile_rows_for_node,
)
from setp_solver.model_config import ModelConfig, model_config_scope  # noqa: E402
from setp_solver.solution import ChargingAction, Route, Solution, physical_vehicle_id  # noqa: E402
from setp_solver.algorithms.resetp_alns.support import charging as charging_support  # noqa: E402


TASK_ID = "T8-ROUTING-VS-SCHEDULING-SPLIT"
MARKER = "DRAFT_METHOD_AWAITING_USER_APPROVAL"
SCHEMA = "resetp.t8-routing-vs-scheduling-split-runner.v1"
INSTANCE_ID = "cn-jjj-50c-01-V2-LOCATIONS"
SEEDS = tuple(range(1, 9))
BUDGET = 1_000
ARMS = ("COST", "COST_CARBON", "FIXED_ROUTE_RETIME")
CARBON_PRICE_CNY_PER_KG = 0.07502
CHECKPOINT_INTERVAL = 100
ARCHIVE_LIMIT = 8
EXACT_ELITES = 2
SP_SECONDS = 0.5
WALLCLOCK_SAFETY_SECONDS_PER_VIEW = 540.0
SINGLE_RUN_WALLCLOCK_LIMIT_SECONDS = 1_800.0
AUTHORITY = REPO / "data/ChinaInstances/china81_finite_fleet_authority_v3_20260802"
PREREGISTRATION = OUT / "preregistration.json"
PROTECTED_RELATIVE = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)
PROTECTED_HASHES = {
    "solver/src/setp_solver/cost.py": "e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d",
    "solver/src/setp_solver/check.py": "86b813152b2fc7f89500468cc3d73178cb1bdafe9dc659852b437c5fdb07702b",
    "solver/src/setp_solver/search/evaluation.py": "c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3",
}


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
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
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
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def atomic_csv(path: Path, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
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
        writer = csv.DictWriter(handle, fieldnames=fields)
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
                    for field in fields
                }
            )
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def assert_protected_hashes() -> dict[str, str]:
    observed = {relative: file_sha256(REPO / relative) for relative in PROTECTED_RELATIVE}
    mismatches = {
        relative: {"expected": PROTECTED_HASHES[relative], "observed": observed[relative]}
        for relative in PROTECTED_RELATIVE
        if observed[relative] != PROTECTED_HASHES[relative]
    }
    if mismatches:
        raise RuntimeError("protected-file hash drift: " + json.dumps(mismatches, sort_keys=True))
    return observed


def _float(value: Any) -> float:
    return float(value)


def slot_rows_for_solution(
    *, arm: str, seed: int, solution: Solution, bundle: China81Bundle,
) -> list[dict[str, Any]]:
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    by_slot_city: dict[tuple[int, str], float] = defaultdict(float)
    emissions_by_slot: dict[int, float] = defaultdict(float)
    cost_by_slot: dict[int, float] = defaultdict(float)
    for action in solution.charging_actions:
        station = node_lookup[action.station_id]
        city = str(station.city).strip().lower()
        node_profile = time_profile_rows_for_node(bundle.instance, action.station_id, bundle.time_profile)
        price_field = (
            "depot_energy_cny_per_kwh"
            if station.node_type.lower() == "d"
            else "public_total_cny_per_kwh"
        )
        for slot in charging_action_slot_breakdown(
            action, bundle.instance, bundle.prices, n_slots=len(node_profile), cyclic=True,
        ):
            index = int(slot.slot_index) + 1
            energy = float(slot.y_skt_kwh)
            profile_row = carbon_profile_row_for_slot(node_profile, int(slot.slot_index))
            by_slot_city[(index, city)] += energy
            emissions_by_slot[index] += energy * float(profile_row["actual_gco2_per_kwh"]) / 1_000.0
            cost_by_slot[index] += energy * float(profile_row[price_field])
    total_energy = sum(by_slot_city.values())
    return [
        {
            "task_id": TASK_ID,
            "draft_status": MARKER,
            "arm": arm,
            "seed": seed,
            "half_hour_slot": slot,
            "start_minute": (slot - 1) * 30,
            "end_minute": slot * 30,
            "charging_kwh": by_slot_city[(slot, "beijing")] + by_slot_city[(slot, "tianjin")],
            "beijing_kwh": by_slot_city[(slot, "beijing")],
            "tianjin_kwh": by_slot_city[(slot, "tianjin")],
            "share_of_run_charging": (
                0.0
                if total_energy == 0.0
                else (by_slot_city[(slot, "beijing")] + by_slot_city[(slot, "tianjin")]) / total_energy
            ),
            "charging_cost_cny": cost_by_slot[slot],
            "charging_emissions_kg": emissions_by_slot[slot],
        }
        for slot in range(1, 49)
    ]


def action_static_signature(action: ChargingAction) -> tuple[Any, ...]:
    """All action fields except the one field allowed to change in retiming."""

    return (
        action.vehicle_id,
        action.station_id,
        float(action.energy_kwh),
        float(action.occupancy_minutes),
        int(action.charge_day_offset),
        None if action.start_energy_kwh is None else float(action.start_energy_kwh),
        None if action.end_energy_kwh is None else float(action.end_energy_kwh),
        action.charging_curve_id,
    )


def solution_fingerprints(solution: Solution, bundle: China81Bundle) -> dict[str, Any]:
    customer_ids = {
        node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"
    }
    groups, assignments, arcs = t5.canonical_route_structure(solution, customer_ids)
    actions = sorted(action_static_signature(action) for action in solution.charging_actions)
    return {
        "route_structure": groups,
        "route_signature_sha256": canonical_sha256(groups),
        "customer_assignment": assignments,
        "customer_assignment_sha256": canonical_sha256(assignments),
        "arc_set": [list(arc) for arc in sorted(arcs)],
        "arc_set_sha256": canonical_sha256(sorted(arcs)),
        "action_static_signature": actions,
        "action_static_sha256": canonical_sha256(actions),
    }


def direct_check_count(solution: Solution, bundle: China81Bundle) -> tuple[int, list[dict[str, Any]]]:
    violations = check_solution(solution, bundle.instance, bundle.prices)
    return len(violations), [asdict(item) for item in violations]


def build_search_bundles(base: China81Bundle) -> tuple[dict[str, China81Bundle], dict[str, China81Bundle]]:
    # T8 has no T5 P arm.  Reuse only the T5 bundle constructor, with the
    # registered base profile for both search arms.
    search = {
        "COST": t5.bundle_with_profile_and_carbon_price(
            base, base.time_profile, carbon_price=0.0
        ),
        "COST_CARBON": t5.bundle_with_profile_and_carbon_price(
            base,
            base.time_profile,
            carbon_price=CARBON_PRICE_CNY_PER_KG,
            charging_only_carbon_term=True,
        ),
    }
    reporting = {
        "COST": t5.bundle_with_profile_and_carbon_price(
            base, base.time_profile, carbon_price=CARBON_PRICE_CNY_PER_KG
        ),
        "COST_CARBON": t5.bundle_with_profile_and_carbon_price(
            base, base.time_profile, carbon_price=CARBON_PRICE_CNY_PER_KG
        ),
        "FIXED_ROUTE_RETIME": t5.bundle_with_profile_and_carbon_price(
            base, base.time_profile, carbon_price=CARBON_PRICE_CNY_PER_KG
        ),
    }
    return search, reporting


def run_search(
    *, arm: str, seed: int, search_bundle: China81Bundle, initial: Solution,
) -> tuple[Any, float]:
    started = perf_counter()
    with model_config_scope(
        ModelConfig(strict_multitrip=True, depot_charger_capacity_mode="unbounded")
    ):
        run = route_pool_sp.run_hgs_route_pool_recombination(
            search_bundle,
            initial,
            seed=seed,
            hgs_seconds_per_view=None,
            exact_elites_per_view=EXACT_ELITES,
            max_archive_candidates_per_view=ARCHIVE_LIMIT,
            sp_time_limit_seconds=SP_SECONDS,
            hard_home_depot_lock=False,
            max_hgs_iterations_per_view=BUDGET,
            max_no_improvement_iterations_per_view=None,
            wallclock_safety_seconds_per_view=WALLCLOCK_SAFETY_SECONDS_PER_VIEW,
            exact_checkpoint_interval_iterations=CHECKPOINT_INTERVAL,
            preserve_base_pool_recombination=False,
        )
    elapsed = perf_counter() - started
    if elapsed > SINGLE_RUN_WALLCLOCK_LIMIT_SECONDS:
        raise RuntimeError(f"{arm}_seed{seed} wallclock {elapsed:.6f}s exceeded 1800s")
    return run, elapsed


def _route_time_at_node(
    route: Route,
    station_index: int,
    current_actions: dict[str, ChargingAction],
    bundle: China81Bundle,
) -> float:
    """Compute arrival at a public station without changing any route field."""

    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    time_s = float(node_lookup[route.node_sequence[0]].ready_time)
    for index, node_id in enumerate(route.node_sequence[:station_index]):
        node = node_lookup[node_id]
        time_s = max(time_s, float(node.ready_time)) + float(node.service_time)
        action = current_actions.get(node_id)
        if action is not None and node.node_type.lower() != "d":
            time_s = max(time_s, float(action.charge_start_second)) + float(action.occupancy_minutes) * 60.0
        next_id = route.node_sequence[index + 1]
        time_s += charging_support._ev_travel_time(bundle.instance, node_id, next_id, bundle.prices)
    return time_s


def retime_fixed_route(
    *, cost_solution: Solution, bundle: China81Bundle,
) -> tuple[Solution, list[dict[str, Any]]]:
    """Retiming with no fallback: replace only each action's start time."""

    route_by_vehicle = {route.vehicle_id: route for route in cost_solution.routes}
    original_fingerprint = solution_fingerprints(cost_solution, bundle)
    current_actions = {action.vehicle_id: action for action in cost_solution.charging_actions}
    retime_trace: list[dict[str, Any]] = []
    retimed_actions: list[ChargingAction] = []
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}

    for action_index, action in enumerate(cost_solution.charging_actions):
        route = route_by_vehicle.get(action.vehicle_id)
        if route is None:
            raise ValueError(f"action vehicle {action.vehicle_id!r} is absent from COST routes")
        matches = [index for index, node_id in enumerate(route.node_sequence) if node_id == action.station_id]
        if not matches:
            raise ValueError(
                f"station {action.station_id!r} for {action.vehicle_id!r} is absent from frozen route"
            )
        station_index = 0 if node_lookup[action.station_id].node_type.lower() == "d" and 0 in matches else matches[0]
        station = node_lookup[action.station_id]
        occupancy_seconds = float(action.occupancy_minutes) * 60.0
        if station.node_type.lower() == "d":
            earliest = 0.0
            latest = route_departure_second(route, bundle.instance, bundle.prices) - occupancy_seconds
        else:
            arrival = _route_time_at_node(route, station_index, current_actions, bundle)
            earliest = max(arrival, float(station.ready_time))
            latest = charging_support._fixed_charge_latest(
                station_index,
                route.node_sequence,
                node_lookup,
                bundle.instance,
                bundle.prices,
                occupancy_seconds,
            )
        if latest + 1.0e-9 < earliest:
            raise ValueError(
                f"no legal retime window for {action.vehicle_id} at {action.station_id}: "
                f"earliest={earliest:.9f}, latest={latest:.9f}"
            )
        new_start = t5.objective_consistent_charging_start(
            action,
            earliest_start_second=earliest,
            latest_start_second=latest,
            instance=bundle.instance,
            carbon_profile=bundle.time_profile,
            prices=bundle.prices,
        )
        new_action = replace(action, charge_start_second=float(new_start))
        retimed_actions.append(new_action)
        current_actions[action.vehicle_id] = new_action
        retime_trace.append(
            {
                "action_index": action_index,
                "vehicle_id": action.vehicle_id,
                "station_id": action.station_id,
                "old_start_second": float(action.charge_start_second),
                "new_start_second": float(new_start),
                "earliest_start_second": float(earliest),
                "latest_start_second": float(latest),
                "allowed_field_change": "charge_start_second",
            }
        )

    retimed = Solution(
        routes=list(cost_solution.routes),
        charging_actions=retimed_actions,
        cross_site_services=list(cost_solution.cross_site_services),
    )
    new_fingerprint = solution_fingerprints(retimed, bundle)
    for field in (
        "route_signature_sha256",
        "customer_assignment_sha256",
        "arc_set_sha256",
        "action_static_sha256",
    ):
        if original_fingerprint[field] != new_fingerprint[field]:
            raise RuntimeError(f"FIXED_ROUTE_RETIME changed frozen field {field}")
    return retimed, retime_trace


def collect_completion_trace(
    *, run_id: str, arm: str, seed: int, run: Any,
) -> tuple[list[dict[str, Any]], Counter[str], int, int, int, int]:
    rows: list[dict[str, Any]] = []
    failures: Counter[str] = Counter()
    all_successes = 0
    candidate_attempts = 0
    candidate_successes = 0
    candidate_sources = t5.CANDIDATE_SOURCES
    for item in run.stats["complete_candidate_evaluation_trace"]:
        success = bool(item.get("completion_succeeded"))
        all_successes += int(success)
        message = str(item.get("exception_message") or "")
        category = ""
        if not success:
            category = t5.classify_failure(message, item.get("failure_category"))
            failures[category] += 1
        source = str(item["source"])
        if source in candidate_sources:
            candidate_attempts += 1
            candidate_successes += int(success)
        rows.append(
            {
                "task_id": TASK_ID,
                "draft_status": MARKER,
                "run_id": run_id,
                "arm": arm,
                "seed": seed,
                "budget": BUDGET,
                "evaluation_index": int(item["evaluation_index"]),
                "view": item["view"],
                "source": source,
                "iteration": "" if item.get("iteration") is None else int(item["iteration"]),
                "candidate_id": item.get("candidate_id", ""),
                "completion_succeeded": success,
                "status": item.get("status", ""),
                "search_objective": "" if item.get("complete_objective") is None else float(item["complete_objective"]),
                "exception_type": item.get("exception_type") or "",
                "exception_message": message,
                "failure_category": category,
            }
        )
    return rows, failures, all_successes, len(rows), candidate_successes, candidate_attempts


def metric_row(
    *, run_id: str, arm: str, seed: int, solution: Solution, search_bundle: China81Bundle | None,
    reporting_bundle: China81Bundle, elapsed: float, search_objective_value: float | None,
    search_trace: list[dict[str, Any]], failures: Counter[str], all_successes: int,
    all_attempts: int, candidate_successes: int, candidate_attempts: int,
    retime_target_objective_cny: float | None = None, direct_check_violations: list[dict[str, Any]] | None = None,
    retime_trace: list[dict[str, Any]] | None = None, source_cost_run_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    full_objective, breakdown, exact_violations = exact_china81_score(solution, reporting_bundle)
    direct_count, direct_violations = direct_check_count(solution, reporting_bundle)
    if direct_check_violations is not None:
        direct_violations = direct_check_violations
        direct_count = len(direct_violations)
    violations = [asdict(item) for item in exact_violations] + direct_violations
    fingerprint = solution_fingerprints(solution, reporting_bundle)
    all_customers = {
        node.node_id: node for node in reporting_bundle.instance.nodes if node.node_type.lower() == "c"
    }
    completed = set(fingerprint["customer_assignment"])
    completed_demand = sum(float(all_customers[node_id].demand) for node_id in completed if node_id in all_customers)
    required_demand = sum(float(node.demand) for node in all_customers.values())
    operating_cost = float(full_objective) - float(breakdown["cost_carbon"])
    charging_energy = float(breakdown["electricity_kwh"])
    charging_emissions = float(breakdown["E_ev_indirect"])
    actual_intensity = "" if charging_energy <= 1.0e-12 else charging_emissions / charging_energy
    expected_search = None
    closure = None
    if search_bundle is not None and search_objective_value is not None:
        expected_search = operating_cost + CARBON_PRICE_CNY_PER_KG * charging_emissions if arm == "COST_CARBON" else operating_cost
        closure = abs(float(search_objective_value) - expected_search)
    status = "PASS_FULL_LEGAL_SOLUTION" if not violations else "FAIL_FULL_OR_DIRECT_CHECK"
    if arm == "FIXED_ROUTE_RETIME" and violations:
        status = "HALT_RETIME_INFEASIBLE"
    row = {
        "task_id": TASK_ID,
        "draft_status": MARKER,
        "formal_search_allowed": False,
        "run_id": run_id,
        "instance_id": INSTANCE_ID,
        "scenario_date": reporting_bundle.date,
        "arm": arm,
        "budget": BUDGET,
        "seed": seed,
        "status": status,
        "error_message": "" if not violations else json.dumps(violations, ensure_ascii=False, sort_keys=True),
        "source_cost_run_id": source_cost_run_id or "",
        "search_objective_value": "" if search_objective_value is None else float(search_objective_value),
        "search_objective_source": "NO_SEARCH_FIXED_ROUTE_RETIME" if search_bundle is None else "ROUTE_POOL_COMPLETION_OBJECTIVE",
        "search_objective_expected_cny": "" if expected_search is None else expected_search,
        "search_objective_closure_abs": "" if closure is None else closure,
        "retime_target_objective_cny": "" if retime_target_objective_cny is None else retime_target_objective_cny,
        "full_model_objective_cny": float(full_objective),
        "operating_cost_cny": operating_cost,
        "carbon_cost_cny": float(breakdown["cost_carbon"]),
        "fuel_direct_emissions_kg": float(breakdown["E_cv_direct"]),
        "charging_emissions_kg": charging_emissions,
        "system_emissions_kg": float(breakdown["E_total"]),
        "actual_carbon_intensity_kg_per_kwh": actual_intensity,
        "enabled_physical_vehicles": int(breakdown["n_veh_cv"] + breakdown["n_veh_ev"]),
        "assigned_cv": int(breakdown["n_veh_cv"]),
        "assigned_ev": int(breakdown["n_veh_ev"]),
        "total_trips": len(solution.routes),
        "total_distance_m": float(breakdown["distance_total"]),
        "total_distance_km": float(breakdown["distance_total"]) / 1_000.0,
        "charging_energy_kwh": charging_energy,
        "charging_cost_cny": float(breakdown["cost_elec"]),
        "completed_customer_count": len(completed & set(all_customers)),
        "required_customer_count": len(all_customers),
        "completed_demand": completed_demand,
        "required_demand": required_demand,
        "route_count": len(solution.routes),
        "route_signature_sha256": fingerprint["route_signature_sha256"],
        "customer_assignment_sha256": fingerprint["customer_assignment_sha256"],
        "arc_set_sha256": fingerprint["arc_set_sha256"],
        "action_static_sha256": fingerprint["action_static_sha256"],
        "completion_attempts_all": all_attempts,
        "completion_successes_all": all_successes,
        "completion_failures_all": all_attempts - all_successes,
        "candidate_completion_attempts": candidate_attempts,
        "candidate_completion_successes": candidate_successes,
        "candidate_completion_failures": candidate_attempts - candidate_successes,
        "failure_category_distribution": dict(sorted(failures.items())),
        "selected_source": "" if search_bundle is None else search_trace[0].get("source", "") if search_trace else "",
        "hgs_iterations_by_view": "" if search_bundle is None else {},
        "wallclock_safety_triggered": False,
        "elapsed_seconds": elapsed,
        "exact_violation_count": len(exact_violations),
        "direct_check_violation_count": direct_count,
        "retime_action_count": 0 if retime_trace is None else len(retime_trace),
        "slot_energy_closure_abs": "",
        "slot_cost_closure_abs": "",
        "slot_emissions_closure_abs": "",
    }
    slots = slot_rows_for_solution(arm=arm, seed=seed, solution=solution, bundle=reporting_bundle)
    slot_energy_sum = sum(float(item["charging_kwh"]) for item in slots)
    slot_cost_sum = sum(float(item["charging_cost_cny"]) for item in slots)
    slot_emissions_sum = sum(float(item["charging_emissions_kg"]) for item in slots)
    row["slot_energy_closure_abs"] = abs(slot_energy_sum - charging_energy)
    row["slot_cost_closure_abs"] = abs(slot_cost_sum - float(breakdown["cost_elec"]))
    row["slot_emissions_closure_abs"] = abs(slot_emissions_sum - charging_emissions)
    witness = {
        "run_id": run_id,
        "task_id": TASK_ID,
        "draft_status": MARKER,
        "arm": arm,
        "seed": seed,
        "budget": BUDGET,
        "status": status,
        "solution": asdict(solution),
        "route_fingerprints": fingerprint,
        "full_breakdown": dict(breakdown),
        "search_objective_value": search_objective_value,
        "search_objective_expected_cny": expected_search,
        "search_objective_closure_abs": closure,
        "retime_target_objective_cny": retime_target_objective_cny,
        "retime_trace": retime_trace or [],
        "exact_violations": [asdict(item) for item in exact_violations],
        "direct_check_violations": direct_violations,
        "completion_trace": search_trace,
    }
    return row, witness, slots


RUN_FIELDS = (
    "task_id", "draft_status", "formal_search_allowed", "run_id", "instance_id", "scenario_date", "arm", "budget", "seed", "status", "error_message", "source_cost_run_id", "search_objective_value", "search_objective_source", "search_objective_expected_cny", "search_objective_closure_abs", "retime_target_objective_cny", "full_model_objective_cny", "operating_cost_cny", "carbon_cost_cny", "fuel_direct_emissions_kg", "charging_emissions_kg", "system_emissions_kg", "actual_carbon_intensity_kg_per_kwh", "enabled_physical_vehicles", "assigned_cv", "assigned_ev", "total_trips", "total_distance_m", "total_distance_km", "charging_energy_kwh", "charging_cost_cny", "completed_customer_count", "required_customer_count", "completed_demand", "required_demand", "route_count", "route_signature_sha256", "customer_assignment_sha256", "arc_set_sha256", "action_static_sha256", "completion_attempts_all", "completion_successes_all", "completion_failures_all", "candidate_completion_attempts", "candidate_completion_successes", "candidate_completion_failures", "failure_category_distribution", "selected_source", "hgs_iterations_by_view", "wallclock_safety_triggered", "elapsed_seconds", "exact_violation_count", "direct_check_violation_count", "retime_action_count", "slot_energy_closure_abs", "slot_cost_closure_abs", "slot_emissions_closure_abs",
)
TRACE_FIELDS = (
    "task_id", "draft_status", "run_id", "arm", "seed", "budget", "evaluation_index", "view", "source", "iteration", "candidate_id", "completion_succeeded", "status", "search_objective", "exception_type", "exception_message", "failure_category",
)
SLOT_FIELDS = (
    "task_id", "draft_status", "arm", "seed", "half_hour_slot", "start_minute", "end_minute", "charging_kwh", "beijing_kwh", "tianjin_kwh", "share_of_run_charging", "charging_cost_cny", "charging_emissions_kg",
)


def empty_failure_row(*, run_id: str, arm: str, seed: int, message: str, status: str) -> dict[str, Any]:
    row = {field: "" for field in RUN_FIELDS}
    row.update(
        {
            "task_id": TASK_ID,
            "draft_status": MARKER,
            "formal_search_allowed": False,
            "run_id": run_id,
            "instance_id": INSTANCE_ID,
            "scenario_date": "2025-02-12",
            "arm": arm,
            "budget": BUDGET,
            "seed": seed,
            "status": status,
            "error_message": message,
        }
    )
    return row


def load_initial_and_bundles() -> tuple[China81Bundle, dict[str, China81Bundle], dict[str, China81Bundle], Solution]:
    config = ModelConfig(strict_multitrip=True, depot_charger_capacity_mode="unbounded")
    base = load_china81_bundle(REPO, INSTANCE_ID, fleet_authority=AUTHORITY, model_config=config)
    if base.date != "2025-02-12":
        raise RuntimeError(f"unexpected scenario date {base.date!r}")
    search_bundles, reporting_bundles = build_search_bundles(base)
    initial = t5.initial_solution()
    return base, search_bundles, reporting_bundles, initial


def run_one_arm(
    *, arm: str, seed: int, cost_results: dict[int, dict[str, Any]], search_bundles: dict[str, China81Bundle], reporting_bundles: dict[str, China81Bundle], initial: Solution,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    run_id = f"{arm}_seed{seed}_budget{BUDGET}"
    print(f"START arm={arm} seed={seed} run_id={run_id}", flush=True)
    if arm == "FIXED_ROUTE_RETIME":
        source = cost_results.get(seed)
        if source is None or source.get("status") != "PASS_FULL_LEGAL_SOLUTION":
            message = "same-seed COST final solution is unavailable or failed"
            row = empty_failure_row(run_id=run_id, arm=arm, seed=seed, message=message, status="HALT_RETIME_INFEASIBLE")
            return row, {"run_id": run_id, "status": row["status"], "error_message": message}, [], [{"task_id": TASK_ID, "draft_status": MARKER, "run_id": run_id, "arm": arm, "seed": seed, "budget": BUDGET, "evaluation_index": 0, "view": "fixed_route_retime", "source": "fixed_route_retime", "iteration": "", "candidate_id": "", "completion_succeeded": False, "status": row["status"], "search_objective": "", "exception_type": "DependencyError", "exception_message": message, "failure_category": "HALT_RETIME_INFEASIBLE"}]
        started = perf_counter()
        cost_solution = source["solution_object"]
        try:
            retimed, retime_trace = retime_fixed_route(cost_solution=cost_solution, bundle=reporting_bundles[arm])
            direct_count, direct_violations = direct_check_count(retimed, reporting_bundles[arm])
            retime_target = (
                float(source["row"]["operating_cost_cny"])
                + CARBON_PRICE_CNY_PER_KG * float(source["row"]["charging_emissions_kg"])
            )
            row, witness, slots = metric_row(
                run_id=run_id,
                arm=arm,
                seed=seed,
                solution=retimed,
                search_bundle=None,
                reporting_bundle=reporting_bundles[arm],
                elapsed=perf_counter() - started,
                search_objective_value=None,
                search_trace=[],
                failures=Counter(),
                all_successes=0,
                all_attempts=0,
                candidate_successes=0,
                candidate_attempts=0,
                retime_target_objective_cny=retime_target,
                direct_check_violations=direct_violations,
                retime_trace=retime_trace,
                source_cost_run_id=source["row"]["run_id"],
            )
            witness["source_cost_route_fingerprints"] = source["witness"]["route_fingerprints"]
            witness["source_cost_run_id"] = source["row"]["run_id"]
            trace = [{"task_id": TASK_ID, "draft_status": MARKER, "run_id": run_id, "arm": arm, "seed": seed, "budget": BUDGET, "evaluation_index": 0, "view": "fixed_route_retime", "source": "fixed_route_retime", "iteration": "", "candidate_id": "", "completion_succeeded": row["status"] == "PASS_FULL_LEGAL_SOLUTION", "status": row["status"], "search_objective": "", "exception_type": "" if row["status"] == "PASS_FULL_LEGAL_SOLUTION" else "CheckError", "exception_message": row["error_message"], "failure_category": "" if row["status"] == "PASS_FULL_LEGAL_SOLUTION" else "HALT_RETIME_INFEASIBLE"}]
            return row, witness, slots, trace
        except Exception as exc:  # preserve the failed arm exactly; no fallback
            message = f"{type(exc).__name__}: {exc}"
            row = empty_failure_row(run_id=run_id, arm=arm, seed=seed, message=message, status="HALT_RETIME_INFEASIBLE")
            trace = [{"task_id": TASK_ID, "draft_status": MARKER, "run_id": run_id, "arm": arm, "seed": seed, "budget": BUDGET, "evaluation_index": 0, "view": "fixed_route_retime", "source": "fixed_route_retime", "iteration": "", "candidate_id": "", "completion_succeeded": False, "status": row["status"], "search_objective": "", "exception_type": type(exc).__name__, "exception_message": message, "failure_category": "HALT_RETIME_INFEASIBLE"}]
            return row, {"run_id": run_id, "status": row["status"], "error_message": message, "source_cost_run_id": source["row"]["run_id"]}, [], trace

    search_bundle = search_bundles[arm]
    report_bundle = reporting_bundles[arm]
    run, elapsed = run_search(arm=arm, seed=seed, search_bundle=search_bundle, initial=initial)
    solution = run.completion.solution
    search_trace, failures, all_successes, all_attempts, candidate_successes, candidate_attempts = collect_completion_trace(run_id=run_id, arm=arm, seed=seed, run=run)
    full_search_objective, search_breakdown, search_violations = exact_china81_score(solution, search_bundle)
    if search_violations:
        raise ValueError(f"{run_id} search-bundle exact violations: {len(search_violations)}")
    report_breakdown_objective = float(run.completion.objective)
    row, witness, slots = metric_row(
        run_id=run_id,
        arm=arm,
        seed=seed,
        solution=solution,
        search_bundle=search_bundle,
        reporting_bundle=report_bundle,
        elapsed=elapsed,
        search_objective_value=float(run.completion.objective),
        search_trace=search_trace,
        failures=failures,
        all_successes=all_successes,
        all_attempts=all_attempts,
        candidate_successes=candidate_successes,
        candidate_attempts=candidate_attempts,
    )
    row["hgs_iterations_by_view"] = {view: int(epoch.stats["hgs_iterations"]) for view, epoch in run.view_epochs.items()}
    row["selected_source"] = run.stats["selected_source"]
    row["wallclock_safety_triggered"] = bool(run.stats["wallclock_safety_triggered"])
    if row["wallclock_safety_triggered"]:
        raise RuntimeError(f"{run_id} hit wallclock safety stop")
    row["search_bundle_full_model_objective_cny"] = float(full_search_objective)
    row["search_bundle_charging_emissions_kg"] = float(search_breakdown["E_ev_indirect"])
    witness["search_bundle_full_model_objective_cny"] = float(full_search_objective)
    witness["search_bundle_breakdown"] = dict(search_breakdown)
    witness["run_activity"] = run.completion.activity
    witness["view_epochs"] = {view: asdict(epoch.stats) for view, epoch in run.view_epochs.items()}
    if arm == "COST":
        cost_results[seed] = {"row": row, "witness": witness, "solution_object": solution}
    print(f"DONE arm={arm} seed={seed} full={row['full_model_objective_cny']:.12f} status={row['status']} elapsed={elapsed:.3f}s", flush=True)
    return row, witness, slots, search_trace


def write_progress(run_rows: list[dict[str, Any]], trace_rows: list[dict[str, Any]], slot_rows: list[dict[str, Any]], witnesses: dict[str, Any], state: dict[str, Any]) -> None:
    atomic_csv(OUT / "raw_runs.csv", run_rows, RUN_FIELDS)
    atomic_csv(OUT / "slot_distribution.csv", slot_rows, SLOT_FIELDS)
    atomic_csv(OUT / "completion_trace.csv", trace_rows, TRACE_FIELDS)
    atomic_json(OUT / "solution_witnesses.json", {"schema": "resetp.t8-solution-witnesses.v1", "task_id": TASK_ID, "draft_status": MARKER, "runs": witnesses})
    atomic_json(OUT / "runner_state.json", state)


def format_value(value: Any, digits: int = 6) -> str:
    if value in (None, ""):
        return "NA"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return str(value)


def write_report(*, run_rows: list[dict[str, Any]], slot_rows: list[dict[str, Any]], terminal_status: str, protected_before: dict[str, str], protected_after: dict[str, str]) -> dict[str, Any]:
    by_key = {(int(row["seed"]), row["arm"]): row for row in run_rows if row.get("seed") not in (None, "")}
    lines = [
        "# T8：路径层与排程层减排贡献切分（草案方法探针）",
        "",
        f"`{MARKER}`",
        "",
        "任务性质：草案方法探针，不是正式实验，不构成论文结论。",
        "",
        "## FACT：冻结设计、执行终态与边界",
        "",
        f"算例为 `cn-jjj-50c-01-V2-LOCATIONS`，情景日期为 `2025-02-12`，预算为每搜索视图 `1000` 次迭代，种子为 `1–8`，预期 24 次运行。碳价固定为 `0.07502 CNY/kgCO2e`，来源为 `docs/handoff/china_policy_scenario_contract_20260717.md` 第 3 节。预注册文件为 `preregistration.json`，其写入发生在本批任何 T8 结果之前。",
        "",
        "三个臂唯一差异是：`COST` 只以运营成本搜索并按电费择时；`COST_CARBON` 以运营成本加碳价乘充电侧排放搜索并按同一货币目标择时；`FIXED_ROUTE_RETIME` 不搜索，直接复制同种子 `COST` 最终解，只替换每次充电的起始时刻。路线、车型、实体车、趟、客户服务关系、充电地点、电量、占用时长、充电曲线字段和充电日偏移均作静态指纹核对。",
        "",
        f"终态：`{terminal_status}`；所有记录均保留 `{MARKER}`、`formal_search_allowed=false`、`paper_claim_allowed=false`。单次运行上限为 1800 秒；任何重排后不合法的固定解都应记为 `HALT_RETIME_INFEASIBLE`，不放宽约束、不改电量、不改地点、不试第二套重排方案。",
        "",
        "受保护文件开工前哈希：",
        "",
        "| 文件 | SHA-256 |",
        "|---|---|",
    ]
    for path, digest in protected_before.items():
        lines.append(f"| `{path}` | `{digest}` |")
    lines.extend(["", "收工后哈希：", "", "| 文件 | SHA-256 |", "|---|---|"])
    for path, digest in protected_after.items():
        lines.append(f"| `{path}` | `{digest}` |")
    lines.extend([
        "",
        "## FACT：逐次运行主读数",
        "",
        "以下为 24 条逐次记录。`实际碳强度`定义为充电侧排放除以充电电量；服务量红线列保留客户数与需求量。完整 48 槽分布见 `slot_distribution.csv`。",
        "",
        "| 种子 | 臂 | 状态 | 完整目标 | 运营成本 | 燃油排放 | 充电排放 | 系统排放 | 实际碳强度 kg/kWh | 电量 kWh | 电费 | 里程 km | 车数 | CV/EV | 趟数 | 服务客户 | 服务需求 |",
        "|---:|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---|---:|:---:|:---:|",
    ])
    for seed in SEEDS:
        for arm in ARMS:
            row = by_key.get((seed, arm), {})
            service = f"{row.get('completed_customer_count', 'NA')}/{row.get('required_customer_count', 'NA')}"
            demand = f"{format_value(row.get('completed_demand'), 3)}/{format_value(row.get('required_demand'), 3)}"
            lines.append(
                "| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {}/{} | {} | {} | {} |".format(
                    seed, arm, row.get("status", "NA"), format_value(row.get("full_model_objective_cny")), format_value(row.get("operating_cost_cny")), format_value(row.get("fuel_direct_emissions_kg")), format_value(row.get("charging_emissions_kg")), format_value(row.get("system_emissions_kg")), format_value(row.get("actual_carbon_intensity_kg_per_kwh")), format_value(row.get("charging_energy_kwh")), format_value(row.get("charging_cost_cny")), format_value(row.get("total_distance_km")), row.get("enabled_physical_vehicles", "NA"), row.get("assigned_cv", "NA"), row.get("assigned_ev", "NA"), row.get("total_trips", "NA"), service, demand,
                )
            )
    lines.extend([
        "",
        "### FACT：路线、指派、有向弧与闭合",
        "",
        "| 种子 | 臂 | 路线签名 SHA-256 | 客户指派签名 SHA-256 | 有向弧集合签名 SHA-256 | 搜索目标来源 | 搜索目标值 | 目标闭合误差 | 完整检查违约 | 直接 check_solution 违约 |",
        "|---:|:---|:---|:---|:---|:---|---:|---:|---:|---:|",
    ])
    for seed in SEEDS:
        for arm in ARMS:
            row = by_key.get((seed, arm), {})
            lines.append(
                f"| {seed} | {arm} | `{row.get('route_signature_sha256', 'NA')}` | `{row.get('customer_assignment_sha256', 'NA')}` | `{row.get('arc_set_sha256', 'NA')}` | {row.get('search_objective_source', 'NA')} | {format_value(row.get('search_objective_value'))} | {format_value(row.get('search_objective_closure_abs'), 12)} | {row.get('exact_violation_count', 'NA')} | {row.get('direct_check_violation_count', 'NA')} |"
            )
    lines.extend(["", "`FIXED_ROUTE_RETIME` 的搜索目标列为 `NA`，因为该臂按预注册定义不搜索；它另行记录了从冻结 COST 解的运营成本和充电侧碳项重算出的 `retime_target_objective_cny`。这不是把固定重排伪装成搜索结果。", ""])
    lines.extend(["### FACT：48 槽分布", "", "非零槽以 `槽号:电量` 摘要列出；完整 48 行/运行、城市拆分、电费和排放在 `slot_distribution.csv`。", "", "| 种子 | 臂 | 非零槽及电量 kWh |", "|---:|:---|:---|"])
    slot_by_key: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in slot_rows:
        slot_by_key[(int(row["seed"]), row["arm"])].append(row)
    for seed in SEEDS:
        for arm in ARMS:
            summary = "; ".join(f"{int(row['half_hour_slot'])}:{float(row['charging_kwh']):.6f}" for row in slot_by_key.get((seed, arm), []) if abs(float(row["charging_kwh"])) > 1.0e-9)
            lines.append(f"| {seed} | {arm} | {summary or '无'} |")
    lines.extend(["", "## FACT：逐种子分解", "", "定义：排程层减排 = COST 系统排放 − FIXED_ROUTE_RETIME 系统排放；总减排 = COST 系统排放 − COST_CARBON 系统排放；路径层贡献 = 总减排 − 排程层减排。正值表示减排贡献，负值保留为负。EV 工作量混杂规则为 `abs(COST_CARBON 充电量 − COST 充电量) > 10 kWh`。路线改变按规范化路线、客户指派和有向弧签名共同核对。", "", "| 种子 | 排程层减排 kg | 总减排 kg | 路径层贡献 kg | COST_CARBON−COST 电量差 kWh | 里程差 km | EV 工作量混杂 | 路线是否改变 |", "|---:|---:|---:|---:|---:|---:|:---:|:---|"])
    decompositions: list[dict[str, Any]] = []
    for seed in SEEDS:
        cost = by_key.get((seed, "COST"), {})
        carbon = by_key.get((seed, "COST_CARBON"), {})
        fixed = by_key.get((seed, "FIXED_ROUTE_RETIME"), {})
        usable = all(row.get("status") == "PASS_FULL_LEGAL_SOLUTION" for row in (cost, carbon, fixed))
        if usable:
            schedule = float(cost["system_emissions_kg"]) - float(fixed["system_emissions_kg"])
            total = float(cost["system_emissions_kg"]) - float(carbon["system_emissions_kg"])
            path = total - schedule
            energy_diff = float(carbon["charging_energy_kwh"]) - float(cost["charging_energy_kwh"])
            distance_diff = float(carbon["total_distance_km"]) - float(cost["total_distance_km"])
            route_changed = any(cost.get(field) != carbon.get(field) for field in ("route_signature_sha256", "customer_assignment_sha256", "arc_set_sha256"))
            mixed = abs(energy_diff) > 10.0
            lines.append(f"| {seed} | {schedule:.6f} | {total:.6f} | {path:.6f} | {energy_diff:.6f} | {distance_diff:.6f} | {'是' if mixed else '否'} | {'是' if route_changed else '否'} |")
            decompositions.append({"seed": seed, "schedule": schedule, "total": total, "path": path, "energy_diff": energy_diff, "distance_diff": distance_diff, "mixed": mixed, "route_changed": route_changed})
        else:
            lines.append(f"| {seed} | NA | NA | NA | NA | NA | NA | NA |")
            decompositions.append({"seed": seed, "status": "NOT_COMPARABLE_MISSING_OR_FAILED_ARM"})
    lines.extend(["", "## INFERENCE：只限本草案探针的归纳", ""])
    valid = [item for item in decompositions if "path" in item]
    positive = [item for item in valid if item["path"] > 0.0]
    mixed = [item for item in valid if item["mixed"]]
    if valid:
        schedule_abs = [abs(item["schedule"]) for item in valid]
        positive_schedule_abs = [abs(item["schedule"]) for item in positive]
        ratio_text = "NA"
        if positive_schedule_abs and sum(positive_schedule_abs) > 0:
            ratio_text = f"{sum(item['path'] for item in positive) / sum(positive_schedule_abs):.6f}"
        lines.append(f"在 {len(valid)} 个可完整比较的种子中，路径层贡献为正的有 **{len(positive)} 个**；这些正贡献的路径层贡献绝对值合计相对对应排程层减排绝对值合计为 **{ratio_text}**。充电电量差超过 10 kWh 而被标记为 EV 工作量混杂的有 **{len(mixed)} 个**。上述“量级相对”使用逐种子正路径层贡献之和除以对应排程层减排绝对值之和，并同时保留每个种子的原始值。")
    else:
        lines.append("当前没有一个种子满足三臂均为完整合法解，因此不能计算这组分解；失败分类见下文。")
    lines.extend([
        "",
        "这只是固定算例、固定日期和 8 个种子的构造探针观察；它不支持总体统计、政策效果或论文发现，也不把结果定性为“路径优化问题”或“排程问题”。",
        "",
        "## FACT：失败、红线与保留的反例",
        "",
        "任何 `status` 非 `PASS_FULL_LEGAL_SOLUTION` 的行均未被删除或替换。服务量不是 50/50 客户或 13264/13264 需求的行必须在表中直接识别；重排失败必须保留 `HALT_RETIME_INFEASIBLE`。候选补全失败分类保留在 `raw_runs.csv` 与 `completion_trace.csv`。",
        "",
        "## DECISION",
        "",
        f"本批结构化终态为 `{terminal_status}`。方法仍为 `{MARKER}`，`formal_search_allowed=false`，`paper_claim_allowed=false`；本报告不批准碳项进入正式搜索，不批准本探针进入论文正文。",
        "",
        "## HALT_REQUIRES_PROTECTED_FILE_CHANGE / HALT_AWAITING_USER_APPROVAL / HALT_RETIME_INFEASIBLE",
        "",
        "以上标签只在对应事实发生时使用。若受保护文件哈希漂移，终态必须为 `HALT_REQUIRES_PROTECTED_FILE_CHANGE`；若需要改变模型语义、目标函数经济含义、参数方案或算例，终态必须为 `HALT_AWAITING_USER_APPROVAL`；若固定路线在不放宽约束下无法合法重排，逐种子终态必须为 `HALT_RETIME_INFEASIBLE`。",
        "",
        "证据文件：`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`preregistration.json`、`slot_distribution.csv`、`solution_witnesses.json`、`completion_trace.csv`。",
    ])
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"decompositions": decompositions, "positive_path_count": len(positive), "valid_seed_count": len(valid), "mixed_seed_count": len(mixed)}


def build_artifact_hashes() -> dict[str, Any]:
    excluded_names = {"artifact_hashes.json"}
    excluded_parts = {"__pycache__", ".pytest_cache"}
    files: dict[str, str] = {}
    for path in sorted(OUT.rglob("*")):
        if not path.is_file() or path.name in excluded_names or path.name.startswith("._"):
            continue
        if any(part in excluded_parts for part in path.parts):
            continue
        if path.name.startswith("."):
            continue
        files[str(path.relative_to(REPO))] = file_sha256(path)
    return {
        "schema": "resetp.t8-artifact-hashes.v1",
        "task_id": TASK_ID,
        "draft_status": MARKER,
        "excluded": ["._*", "__pycache__", ".pytest_cache", "artifact_hashes.json", "temporary files"],
        "files": files,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.self_test == args.run:
        parser.error("choose exactly one of --self-test or --run")
    if args.self_test:
        assert_protected_hashes()
        prereg = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
        if prereg["status"] != MARKER or prereg["expected_run_count"] != 24:
            raise RuntimeError("T8 preregistration is missing or inconsistent")
        base, search_bundles, reporting_bundles, initial = load_initial_and_bundles()
        if search_bundles["COST"].prices.carbon_price != 0.0:
            raise RuntimeError("COST carbon price is not zero")
        if not math.isclose(search_bundles["COST_CARBON"].prices.carbon_price, CARBON_PRICE_CNY_PER_KG, rel_tol=0.0, abs_tol=0.0):
            raise RuntimeError("COST_CARBON carbon price drift")
        if search_bundles["COST_CARBON"].prices.diesel_ef != 0.0:
            raise RuntimeError("COST_CARBON search must contain charging-only carbon")
        if reporting_bundles["COST_CARBON"].prices.diesel_ef == 0.0:
            raise RuntimeError("reporting bundle must restore fuel direct emissions")
        t5.install_probe_local_timing_hooks()
        assert_protected_hashes()
        print("SELF_TEST_PASS", flush=True)
        return 0

    if os.environ.get("PYTHONHASHSEED") != "0":
        raise RuntimeError("PYTHONHASHSEED must equal 0")
    prereg = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    if prereg.get("status") != MARKER or prereg.get("formal_search_allowed") is not False or prereg.get("paper_claim_allowed") is not False:
        raise RuntimeError("preregistration status or claim boundary is invalid")
    protected_before = assert_protected_hashes()
    started_at = datetime.now(UTC).isoformat()
    run_rows: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []
    slot_rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    cost_results: dict[int, dict[str, Any]] = {}
    terminal_status = "RUNNER_COMPLETE"
    failure: dict[str, Any] | None = None
    try:
        base, search_bundles, reporting_bundles, initial = load_initial_and_bundles()
        t5.install_probe_local_timing_hooks()
        for seed in SEEDS:
            for arm in ARMS:
                assert_protected_hashes()
                try:
                    row, witness, slots, traces = run_one_arm(
                        arm=arm,
                        seed=seed,
                        cost_results=cost_results,
                        search_bundles=search_bundles,
                        reporting_bundles=reporting_bundles,
                        initial=initial,
                    )
                except Exception as exc:  # run-local failure is retained, not replaced
                    run_id = f"{arm}_seed{seed}_budget{BUDGET}"
                    message = f"{type(exc).__name__}: {exc}"
                    row = empty_failure_row(run_id=run_id, arm=arm, seed=seed, message=message, status="RUN_FAILURE_RECORDED")
                    witness = {"run_id": run_id, "task_id": TASK_ID, "draft_status": MARKER, "status": row["status"], "error_message": message, "traceback": traceback.format_exc()}
                    slots = []
                    traces = []
                    if arm == "COST":
                        cost_results.pop(seed, None)
                run_rows.append(row)
                witnesses[row["run_id"]] = witness
                slot_rows.extend(slots)
                trace_rows.extend(traces)
                state = {
                    "schema": SCHEMA,
                    "task_id": TASK_ID,
                    "draft_status": MARKER,
                    "formal_search_allowed": False,
                    "paper_claim_allowed": False,
                    "terminal_status": "RUNNING",
                    "started_at": started_at,
                    "updated_at": datetime.now(UTC).isoformat(),
                    "expected_run_count": 24,
                    "completed_run_count": len(run_rows),
                    "protected_hashes_before": protected_before,
                    "runs": run_rows,
                }
                write_progress(run_rows, trace_rows, slot_rows, witnesses, state)
        protected_after = assert_protected_hashes()
        if len(run_rows) != 24:
            raise RuntimeError(f"expected 24 runs, observed {len(run_rows)}")
        report_summary = write_report(run_rows=run_rows, slot_rows=slot_rows, terminal_status=terminal_status, protected_before=protected_before, protected_after=protected_after)
        decision_status = "PROBE_COMPLETE_DRAFT_METHOD"
        if any(row.get("status") == "HALT_RETIME_INFEASIBLE" for row in run_rows):
            decision_status = "PROBE_COMPLETE_WITH_HALT_RETIME_INFEASIBLE"
        if protected_before != protected_after:
            decision_status = "HALT_REQUIRES_PROTECTED_FILE_CHANGE"
        decision = {
            "schema": "resetp.t8-decision.v1",
            "task_id": TASK_ID,
            "status": decision_status,
            "method_status": MARKER,
            "formal_search_allowed": False,
            "paper_claim_allowed": False,
            "expected_runs": 24,
            "observed_runs": len(run_rows),
            "all_three_arm_comparisons_usable": report_summary["valid_seed_count"] == 8,
            "positive_path_layer_contribution_count": report_summary["positive_path_count"],
            "ev_workload_confounded_seed_count": report_summary["mixed_seed_count"],
            "reason": "T8 is a draft-method probe; no result authorizes formal search or manuscript claims.",
        }
        atomic_json(OUT / "decision.json", decision)
        metadata = {
            "schema": "resetp.t8-metadata.v1",
            "task_id": TASK_ID,
            "draft_status": MARKER,
            "formal_search_allowed": False,
            "paper_claim_allowed": False,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "python": sys.version.split()[0],
            "numpy": version("numpy"),
            "scipy": version("scipy"),
            "pyvrp": version("pyvrp"),
            "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
            "instance_id": INSTANCE_ID,
            "scenario_date": base.date,
            "budget": BUDGET,
            "seeds": list(SEEDS),
            "arms": list(ARMS),
            "carbon_price_cny_per_kg": CARBON_PRICE_CNY_PER_KG,
            "preregistration_sha256": file_sha256(PREREGISTRATION),
            "protected_hashes_before": protected_before,
            "protected_hashes_after": protected_after,
            "run_count": len(run_rows),
            "run_status_counts": dict(Counter(row.get("status", "") for row in run_rows)),
            "report_summary": report_summary,
        }
        atomic_json(OUT / "metadata.json", metadata)
        atomic_json(OUT / "artifact_hashes.json", build_artifact_hashes())
        atomic_json(OUT / "done.json", {"schema": "resetp.t8-done.v1", "task_id": TASK_ID, "draft_status": MARKER, "status": decision_status, "finished_at": datetime.now(UTC).isoformat(), "failure": None})
    except Exception as exc:  # preserve terminal evidence
        terminal_status = "HALT_REQUIRES_PROTECTED_FILE_CHANGE" if "protected-file hash drift" in str(exc) else "RUNNER_HALT"
        failure = {"exception_type": type(exc).__name__, "exception_message": str(exc), "traceback": traceback.format_exc(), "completed_run_count": len(run_rows)}
        protected_after = {relative: file_sha256(REPO / relative) for relative in PROTECTED_RELATIVE}
        write_progress(run_rows, trace_rows, slot_rows, witnesses, {"schema": SCHEMA, "task_id": TASK_ID, "draft_status": MARKER, "formal_search_allowed": False, "paper_claim_allowed": False, "terminal_status": terminal_status, "started_at": started_at, "finished_at": datetime.now(UTC).isoformat(), "expected_run_count": 24, "completed_run_count": len(run_rows), "protected_hashes_before": protected_before, "protected_hashes_after": protected_after, "failure": failure, "runs": run_rows})
        atomic_json(OUT / "decision.json", {"schema": "resetp.t8-decision.v1", "task_id": TASK_ID, "status": terminal_status, "method_status": MARKER, "formal_search_allowed": False, "paper_claim_allowed": False, "paper_claim_allowed": False, "reason": failure["exception_message"]})
        atomic_json(OUT / "metadata.json", {"schema": "resetp.t8-metadata.v1", "task_id": TASK_ID, "draft_status": MARKER, "formal_search_allowed": False, "paper_claim_allowed": False, "started_at": started_at, "finished_at": datetime.now(UTC).isoformat(), "protected_hashes_before": protected_before, "protected_hashes_after": protected_after, "run_count": len(run_rows), "failure": failure})
        atomic_json(OUT / "done.json", {"schema": "resetp.t8-done.v1", "task_id": TASK_ID, "draft_status": MARKER, "status": terminal_status, "finished_at": datetime.now(UTC).isoformat(), "failure": failure})
    if failure is not None:
        print(f"RUNNER_HALT {failure['exception_type']}: {failure['exception_message']}", flush=True)
        return 1
    print("RUNNER_COMPLETE run_count=24", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
