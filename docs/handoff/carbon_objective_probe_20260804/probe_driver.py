#!/usr/bin/env python3
"""Isolated three-arm draft-method driver for T5-CARBON-OBJ-PROBE.

This file is a probe-only entrypoint.  It never replaces a formal runner and
never mutates the shared evaluator/checker/cost implementation.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import asdict, replace
from datetime import UTC, datetime
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from time import perf_counter
import traceback
from typing import Any, Iterable


REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for entry in (REPO, REPO / "solver/src", REPO / "models/src", PROTOTYPE):
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

import epochal_hgs  # noqa: E402
import route_pool_sp  # noqa: E402
from setp_solver.algorithms.resetp_alns.support import (  # noqa: E402
    carbon_charging,
    charging as charging_support,
)
from setp_solver.china81 import China81Bundle, load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import exact_china81_score  # noqa: E402
from setp_solver.cost import (  # noqa: E402
    CARBON_SLOT_SECONDS,
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    charging_action_slot_breakdown,
    charging_curve_for_action,
    carbon_profile_row_for_slot,
    time_profile_rows_for_node,
)
from setp_solver.model_config import ModelConfig, model_config_scope  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    Route,
    Solution,
    physical_vehicle_id,
)


SCHEMA = "resetp.t5-carbon-objective-probe-runner.v1"
TASK_ID = "T5-CARBON-OBJ-PROBE"
MARKER = "DRAFT_METHOD_AWAITING_USER_APPROVAL"
INSTANCE_ID = "cn-jjj-50c-01-V2-LOCATIONS"
AUTHORITY = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v3_20260802"
)
PREREGISTRATION = OUT / "preregistration.json"
SEEDS = (1, 2, 3)
BUDGETS = (100, 1_000)
ARMS = ("O", "C", "P")
CHECKPOINT_INTERVAL = 100
ARCHIVE_LIMIT = 8
EXACT_ELITES = 2
SP_SECONDS = 0.5
WALLCLOCK_SAFETY_SECONDS_PER_VIEW = 540.0
SINGLE_RUN_WALLCLOCK_LIMIT_SECONDS = 1_800.0
CARBON_PRICE_CNY_PER_KG = 0.07502
MIDDAY_SLOTS = tuple(range(25, 31))
CANDIDATE_SOURCES = {
    "hgs_iteration_checkpoint",
    "terminal_population_archive",
    "proxy_best_solution",
}
PROTECTED_HASHES = {
    "solver/src/setp_solver/cost.py": (
        "e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d"
    ),
    "solver/src/setp_solver/check.py": (
        "86b813152b2fc7f89500468cc3d73178cb1bdafe9dc659852b437c5fdb07702b"
    ),
    "solver/src/setp_solver/search/evaluation.py": (
        "c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3"
    ),
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


def atomic_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: Iterable[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = tuple(fields)
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


def assert_protected_hashes() -> dict[str, str]:
    observed = {
        relative: file_sha256(REPO / relative)
        for relative in PROTECTED_HASHES
    }
    mismatches = {
        relative: {
            "expected": PROTECTED_HASHES[relative],
            "observed": observed[relative],
        }
        for relative in PROTECTED_HASHES
        if observed[relative] != PROTECTED_HASHES[relative]
    }
    if mismatches:
        raise RuntimeError(
            "protected-file hash drift before/during probe: "
            + json.dumps(mismatches, sort_keys=True)
        )
    return observed


def _price(prices: Any, field: str) -> float:
    if isinstance(prices, dict):
        return float(prices[field])
    return float(getattr(prices, field))


def _timing_candidates(
    action: ChargingAction,
    earliest_start_second: float,
    latest_start_second: float,
    instance: Any,
    prices: Any,
) -> tuple[float, ...]:
    earliest = float(earliest_start_second)
    latest = float(latest_start_second)
    if latest < earliest - 1.0e-9:
        raise ValueError("latest charging start precedes earliest start")
    duration = float(action.occupancy_minutes) * 60.0
    phase_boundaries = {0.0, duration}
    curve_state = charging_curve_for_action(action, instance, prices)
    if curve_state is not None:
        curve, start_energy, end_energy = curve_state
        for phase in curve.phases(start_energy, end_energy):
            phase_boundaries.add(float(phase.relative_start_seconds))
            phase_boundaries.add(float(phase.relative_end_seconds))
    candidates = {earliest, latest}
    first_grid = math.floor(earliest / CARBON_SLOT_SECONDS) - 1
    final_grid = math.ceil((latest + duration) / CARBON_SLOT_SECONDS) + 1
    for index in range(first_grid, final_grid + 1):
        boundary = float(index) * CARBON_SLOT_SECONDS
        for phase_boundary in phase_boundaries:
            candidate = boundary - phase_boundary
            if earliest - 1.0e-9 <= candidate <= latest + 1.0e-9:
                candidates.add(min(latest, max(earliest, candidate)))
    return tuple(sorted(round(value, 9) for value in candidates))


def objective_consistent_charging_start(
    action: ChargingAction,
    *,
    earliest_start_second: float,
    latest_start_second: float,
    instance: Any,
    carbon_profile: list[dict[str, Any]],
    prices: Any,
    intensity_field: str = "actual_gco2_per_kwh",
) -> float:
    """Minimize the arm's monetary charging term over exact breakpoints."""

    if intensity_field != "actual_gco2_per_kwh":
        raise ValueError(
            "T5 probe timing only accepts the actual registered carbon field"
        )
    candidates = _timing_candidates(
        action,
        earliest_start_second,
        latest_start_second,
        instance,
        prices,
    )
    carbon_price = _price(prices, "carbon_price")
    scored: list[tuple[float, float]] = []
    for start in candidates:
        shifted = replace(action, charge_start_second=float(start))
        electricity_cost = charging_action_electricity_cost(
            shifted,
            instance,
            carbon_profile,
            prices,
        )
        charging_emissions = charging_action_emissions_kg(
            shifted,
            instance,
            carbon_profile,
            prices,
        )
        score = electricity_cost + carbon_price * charging_emissions
        scored.append((float(score), float(start)))
    return min(scored, key=lambda item: (item[0], item[1]))[1]


def objective_consistent_select_charge_option(
    options: Iterable[Any],
    instance: Any,
    carbon_profile: list[dict[str, object]],
    prices: Any,
    *,
    carbon_weight: float = 1.0,
) -> Any:
    """Select a station/timing without a hidden emissions tie-break."""

    scored = [
        carbon_charging.score_charge_option(
            option,
            instance,
            carbon_profile,
            prices,
            carbon_weight=carbon_weight,
        )
        for option in options
    ]
    if not scored:
        raise ValueError("at least one charge option is required")
    return min(
        scored,
        key=lambda item: (
            item.total_incremental_cost,
            item.option.detour_m,
            item.option.station_id,
            item.timing.start_second,
        ),
    )


def install_probe_local_timing_hooks() -> dict[str, str]:
    before = {
        "charging.best_charging_action_start": (
            charging_support.best_charging_action_start.__module__
            + "."
            + charging_support.best_charging_action_start.__name__
        ),
        "carbon_charging.best_charging_action_start": (
            carbon_charging.best_charging_action_start.__module__
            + "."
            + carbon_charging.best_charging_action_start.__name__
        ),
        "charging.select_charge_option": (
            charging_support.select_charge_option.__module__
            + "."
            + charging_support.select_charge_option.__name__
        ),
    }
    charging_support.best_charging_action_start = (
        objective_consistent_charging_start
    )
    carbon_charging.best_charging_action_start = (
        objective_consistent_charging_start
    )
    charging_support.select_charge_option = (
        objective_consistent_select_charge_option
    )
    carbon_charging.select_charge_option = (
        objective_consistent_select_charge_option
    )
    return before


def initial_solution() -> Solution:
    witness = json.loads(
        (AUTHORITY / "witnesses" / f"{INSTANCE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    level = witness["levels"]["25"]
    if level["status"] != "CERTIFIED" or level["violations"]:
        raise RuntimeError("v3 level-25 witness is not certified")
    routes: list[Route] = []
    for depot_id, depot in sorted(level["depots"].items()):
        for vehicle_type in ("cv", "ev"):
            for timed in depot[f"{vehicle_type}_routes"]:
                routes.append(
                    Route(
                        vehicle_id=f"T5-INIT-{len(routes) + 1:04d}",
                        vehicle_type=vehicle_type,
                        home_depot_id=depot_id,
                        node_sequence=[
                            depot_id,
                            *timed["customers"],
                            depot_id,
                        ],
                    )
                )
    return Solution(routes=routes)


def _period_template(
    rows: list[dict[str, Any]],
    period: str,
) -> dict[str, Any]:
    candidates = [row for row in rows if row["tariff_period"] == period]
    if not candidates:
        raise RuntimeError(f"no {period!r} tariff template")
    fields = (
        "depot_energy_cny_per_kwh",
        "public_energy_cny_per_kwh",
        "public_service_fee_cny_per_kwh",
        "public_total_cny_per_kwh",
        "tariff_period",
        "tariff_row_class",
        "service_fee_class",
    )
    signatures = {
        tuple(row[field] for field in fields)
        for row in candidates
    }
    if len(signatures) != 1:
        raise RuntimeError(
            f"{period!r} tariff template is not unique: {signatures!r}"
        )
    return {field: candidates[0][field] for field in fields}


def build_midday_valley_profile(
    profile: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_city = {
        city: [row for row in profile if row["city"] == city]
        for city in ("beijing", "tianjin")
    }
    templates = {
        city: _period_template(rows, "valley")
        for city, rows in by_city.items()
    }
    changed: list[dict[str, Any]] = []
    scenario: list[dict[str, Any]] = []
    price_fields = (
        "depot_energy_cny_per_kwh",
        "public_energy_cny_per_kwh",
        "public_service_fee_cny_per_kwh",
        "public_total_cny_per_kwh",
    )
    for original in profile:
        row = dict(original)
        slot = int(row["hourly_calendar_row"])
        city = str(row["city"])
        if city in templates and slot in MIDDAY_SLOTS:
            before = {
                "tariff_period": row["tariff_period"],
                **{field: float(row[field]) for field in price_fields},
            }
            row.update(templates[city])
            after = {
                "tariff_period": row["tariff_period"],
                **{field: float(row[field]) for field in price_fields},
            }
            changed.append(
                {
                    "city": city,
                    "hourly_calendar_row": slot,
                    "start_second": float(row["horizon_second_start"]),
                    "before": before,
                    "after": after,
                    "carbon_gco2_per_kwh": float(
                        row["actual_gco2_per_kwh"]
                    ),
                }
            )
        scenario.append(row)
    if len(changed) != 12:
        raise RuntimeError(
            f"midday-valley construction changed {len(changed)} rows, expected 12"
        )
    for original, row in zip(profile, scenario, strict=True):
        allowed = {
            "tariff_period",
            "tariff_row_class",
            "service_fee_class",
            *price_fields,
        }
        if int(original["hourly_calendar_row"]) not in MIDDAY_SLOTS:
            if canonical_bytes(original) != canonical_bytes(row):
                raise RuntimeError("P arm changed a row outside slots 25-30")
        else:
            for key in original:
                if key not in allowed and original[key] != row[key]:
                    raise RuntimeError(
                        f"P arm changed forbidden field {key!r}"
                    )
    return scenario, changed


def bundle_with_profile_and_carbon_price(
    base: China81Bundle,
    profile: list[dict[str, Any]],
    *,
    carbon_price: float,
    charging_only_carbon_term: bool = False,
) -> China81Bundle:
    depot_mean = sum(
        float(row["depot_energy_cny_per_kwh"])
        for row in profile
    ) / len(profile)
    public_mean = sum(
        float(row["public_total_cny_per_kwh"])
        for row in profile
    ) / len(profile)
    prices = replace(
        base.prices,
        carbon_price=float(carbon_price),
        electricity_price=public_mean,
        station_electricity_price=public_mean,
        depot_electricity_price=depot_mean,
        diesel_ef=(
            0.0
            if charging_only_carbon_term
            else float(base.prices.diesel_ef)
        ),
    )
    return replace(
        base,
        time_profile=[dict(row) for row in profile],
        prices=prices,
    )


def arm_bundles(
    base: China81Bundle,
) -> tuple[
    dict[str, China81Bundle],
    dict[str, China81Bundle],
    list[dict[str, Any]],
]:
    scenario_profile, changes = build_midday_valley_profile(
        base.time_profile
    )
    search = {
        "O": bundle_with_profile_and_carbon_price(
            base,
            base.time_profile,
            carbon_price=0.0,
        ),
        "C": bundle_with_profile_and_carbon_price(
            base,
            base.time_profile,
            carbon_price=CARBON_PRICE_CNY_PER_KG,
            charging_only_carbon_term=True,
        ),
        "P": bundle_with_profile_and_carbon_price(
            base,
            scenario_profile,
            carbon_price=0.0,
        ),
    }
    reporting = {
        "O": bundle_with_profile_and_carbon_price(
            base,
            base.time_profile,
            carbon_price=CARBON_PRICE_CNY_PER_KG,
        ),
        "C": bundle_with_profile_and_carbon_price(
            base,
            base.time_profile,
            carbon_price=CARBON_PRICE_CNY_PER_KG,
        ),
        "P": bundle_with_profile_and_carbon_price(
            base,
            scenario_profile,
            carbon_price=CARBON_PRICE_CNY_PER_KG,
        ),
    }
    if search["O"].time_profile != search["C"].time_profile:
        raise RuntimeError("O and C tariff/carbon profiles differ")
    return search, reporting, changes


def _trip_index(vehicle_id: str) -> int:
    marker = "#T"
    if marker not in vehicle_id:
        return 1
    try:
        return int(vehicle_id.rsplit(marker, 1)[1])
    except ValueError:
        return 1


def canonical_route_structure(
    solution: Solution,
    customer_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, str], set[tuple[str, str]]]:
    raw_groups: dict[str, list[Route]] = defaultdict(list)
    for route in solution.routes:
        raw_groups[physical_vehicle_id(route.vehicle_id)].append(route)
    structural_groups: list[dict[str, Any]] = []
    raw_group_key: dict[str, tuple[Any, ...]] = {}
    for raw_id, routes in raw_groups.items():
        types = {route.vehicle_type.lower() for route in routes}
        depots = {route.home_depot_id for route in routes}
        if len(types) != 1 or len(depots) != 1:
            raise RuntimeError("one physical vehicle mixes type or depot")
        trips = [
            list(route.node_sequence)
            for route in sorted(
                routes,
                key=lambda item: (
                    _trip_index(item.vehicle_id),
                    tuple(item.node_sequence),
                ),
            )
        ]
        record = {
            "vehicle_type": next(iter(types)),
            "home_depot_id": next(iter(depots)),
            "trips": trips,
        }
        key = (
            record["vehicle_type"],
            record["home_depot_id"],
            tuple(tuple(trip) for trip in trips),
        )
        raw_group_key[raw_id] = key
        structural_groups.append({"_raw_id": raw_id, **record})
    structural_groups.sort(
        key=lambda item: (
            item["vehicle_type"],
            item["home_depot_id"],
            tuple(tuple(trip) for trip in item["trips"]),
        )
    )
    labels: dict[str, str] = {}
    clean_groups: list[dict[str, Any]] = []
    counters: Counter[tuple[str, str]] = Counter()
    for group in structural_groups:
        identity = (group["home_depot_id"], group["vehicle_type"])
        counters[identity] += 1
        label = (
            f"{group['home_depot_id']}:{group['vehicle_type']}:"
            f"{counters[identity]:03d}"
        )
        labels[group["_raw_id"]] = label
        clean_groups.append(
            {
                "canonical_vehicle": label,
                "vehicle_type": group["vehicle_type"],
                "home_depot_id": group["home_depot_id"],
                "trips": group["trips"],
            }
        )
    customer_assignment: dict[str, str] = {}
    arcs: set[tuple[str, str]] = set()
    for route in solution.routes:
        label = labels[physical_vehicle_id(route.vehicle_id)]
        for node_id in route.node_sequence[1:-1]:
            if node_id in customer_ids:
                if node_id in customer_assignment:
                    raise RuntimeError(f"customer {node_id!r} served twice")
                customer_assignment[node_id] = label
        arcs.update(zip(route.node_sequence, route.node_sequence[1:]))
    return clean_groups, customer_assignment, arcs


def slot_rows_for_solution(
    *,
    arm: str,
    budget: int,
    seed: int,
    solution: Solution,
    bundle: China81Bundle,
) -> list[dict[str, Any]]:
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    by_slot_city: dict[tuple[int, str], float] = defaultdict(float)
    emissions_by_slot: dict[int, float] = defaultdict(float)
    cost_by_slot: dict[int, float] = defaultdict(float)
    for action in solution.charging_actions:
        station = node_lookup[action.station_id]
        city = str(station.city).strip().lower()
        node_profile = time_profile_rows_for_node(
            bundle.instance,
            action.station_id,
            bundle.time_profile,
        )
        price_field = (
            "depot_energy_cny_per_kwh"
            if station.node_type.lower() == "d"
            else "public_total_cny_per_kwh"
        )
        for slot in charging_action_slot_breakdown(
            action,
            bundle.instance,
            bundle.prices,
            n_slots=len(node_profile),
            cyclic=True,
        ):
            index = int(slot.slot_index) + 1
            energy = float(slot.y_skt_kwh)
            profile_row = carbon_profile_row_for_slot(
                node_profile,
                int(slot.slot_index),
            )
            by_slot_city[(index, city)] += energy
            emissions_by_slot[index] += (
                energy
                * float(profile_row["actual_gco2_per_kwh"])
                / 1_000.0
            )
            cost_by_slot[index] += energy * float(profile_row[price_field])
    total_energy = sum(by_slot_city.values())
    rows: list[dict[str, Any]] = []
    for slot in range(1, 49):
        beijing = by_slot_city[(slot, "beijing")]
        tianjin = by_slot_city[(slot, "tianjin")]
        energy = beijing + tianjin
        rows.append(
            {
                "task_id": TASK_ID,
                "draft_status": MARKER,
                "arm": arm,
                "budget": budget,
                "seed": seed,
                "hourly_calendar_row": slot,
                "start_minute": (slot - 1) * 30,
                "end_minute": slot * 30,
                "charging_kwh": energy,
                "beijing_kwh": beijing,
                "tianjin_kwh": tianjin,
                "share_of_run_charging": (
                    0.0 if total_energy == 0.0 else energy / total_energy
                ),
                "charging_cost_cny": cost_by_slot[slot],
                "charging_emissions_kg": emissions_by_slot[slot],
            }
        )
    return rows


def classify_failure(message: str, supplied: str | None) -> str:
    if supplied:
        return str(supplied)
    if message.startswith("SEARCH_NOT_FOUND:"):
        return "搜索未找到"
    if message.startswith("BUSINESS_HARD_INFEASIBLE:"):
        return "业务硬不可行"
    return "代理找到但完成失败"


def run_one(
    *,
    arm: str,
    budget: int,
    seed: int,
    search_bundle: China81Bundle,
    reporting_bundle: China81Bundle,
    initial: Solution,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    run_id = f"{arm}_seed{seed}_budget{budget}"
    print(
        f"START arm={arm} seed={seed} budget={budget} run_id={run_id}",
        flush=True,
    )
    started = perf_counter()
    with model_config_scope(
        ModelConfig(
            strict_multitrip=True,
            depot_charger_capacity_mode="unbounded",
        )
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
            max_hgs_iterations_per_view=budget,
            max_no_improvement_iterations_per_view=None,
            wallclock_safety_seconds_per_view=(
                WALLCLOCK_SAFETY_SECONDS_PER_VIEW
            ),
            exact_checkpoint_interval_iterations=CHECKPOINT_INTERVAL,
            preserve_base_pool_recombination=False,
        )
    elapsed = perf_counter() - started
    full_objective, breakdown, violations = exact_china81_score(
        run.completion.solution,
        reporting_bundle,
    )
    if violations:
        raise ValueError(
            f"{run_id} final full-check violations: "
            + repr([asdict(item) for item in violations[:5]])
        )
    if elapsed > SINGLE_RUN_WALLCLOCK_LIMIT_SECONDS:
        raise RuntimeError(
            f"{run_id} wallclock {elapsed:.6f}s exceeded 1800s"
        )
    all_customers = {
        node.node_id: node
        for node in reporting_bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    groups, assignments, arcs = canonical_route_structure(
        run.completion.solution,
        set(all_customers),
    )
    route_hash = canonical_sha256(groups)
    completed = set(assignments)
    unknown = completed - set(all_customers)
    if unknown:
        raise RuntimeError(f"solution serves unknown customers: {unknown!r}")
    missing = set(all_customers) - completed
    if missing:
        raise RuntimeError(f"solution omits customers: {sorted(missing)!r}")
    completed_demand = sum(
        float(all_customers[node_id].demand)
        for node_id in completed
    )
    required_demand = sum(
        float(node.demand) for node in all_customers.values()
    )
    trace_rows: list[dict[str, Any]] = []
    failures: Counter[str] = Counter()
    all_successes = 0
    candidate_attempts = 0
    candidate_successes = 0
    for item in run.stats["complete_candidate_evaluation_trace"]:
        success = bool(item.get("completion_succeeded"))
        all_successes += int(success)
        message = str(item.get("exception_message") or "")
        category = ""
        if not success:
            category = classify_failure(
                message,
                item.get("failure_category"),
            )
            failures[category] += 1
        source = str(item["source"])
        if source in CANDIDATE_SOURCES:
            candidate_attempts += 1
            candidate_successes += int(success)
        trace_rows.append(
            {
                "task_id": TASK_ID,
                "draft_status": MARKER,
                "run_id": run_id,
                "arm": arm,
                "budget": budget,
                "seed": seed,
                "evaluation_index": int(item["evaluation_index"]),
                "view": item["view"],
                "source": source,
                "iteration": (
                    "" if item.get("iteration") is None else int(item["iteration"])
                ),
                "candidate_id": item.get("candidate_id", ""),
                "completion_succeeded": success,
                "status": item.get("status", ""),
                "search_objective": (
                    ""
                    if item.get("complete_objective") is None
                    else float(item["complete_objective"])
                ),
                "exception_type": item.get("exception_type") or "",
                "exception_message": message,
                "failure_category": category,
            }
        )
    operating_cost = float(full_objective) - float(breakdown["cost_carbon"])
    expected_search_objective = operating_cost + (
        CARBON_PRICE_CNY_PER_KG * float(breakdown["E_ev_indirect"])
        if arm == "C"
        else 0.0
    )
    if not math.isclose(
        float(run.completion.objective),
        expected_search_objective,
        rel_tol=1.0e-9,
        abs_tol=1.0e-7,
    ):
        raise RuntimeError(
            f"{run_id} search objective does not close to the frozen arm formula: "
            f"observed={run.completion.objective!r}, "
            f"expected={expected_search_objective!r}"
        )
    solution_payload = asdict(run.completion.solution)
    slot_rows = slot_rows_for_solution(
        arm=arm,
        budget=budget,
        seed=seed,
        solution=run.completion.solution,
        bundle=reporting_bundle,
    )
    slot_energy_sum = sum(float(row["charging_kwh"]) for row in slot_rows)
    if not math.isclose(
        slot_energy_sum,
        float(breakdown["electricity_kwh"]),
        rel_tol=0.0,
        abs_tol=1.0e-7,
    ):
        raise RuntimeError(f"{run_id} slot energy does not close")
    slot_cost_sum = sum(float(row["charging_cost_cny"]) for row in slot_rows)
    if not math.isclose(
        slot_cost_sum,
        float(breakdown["cost_elec"]),
        rel_tol=0.0,
        abs_tol=1.0e-7,
    ):
        raise RuntimeError(f"{run_id} slot charging cost does not close")
    slot_emissions_sum = sum(
        float(row["charging_emissions_kg"]) for row in slot_rows
    )
    if not math.isclose(
        slot_emissions_sum,
        float(breakdown["E_ev_indirect"]),
        rel_tol=0.0,
        abs_tol=1.0e-7,
    ):
        raise RuntimeError(f"{run_id} slot charging emissions do not close")
    row = {
        "task_id": TASK_ID,
        "draft_status": MARKER,
        "formal_search_allowed": False,
        "run_id": run_id,
        "instance_id": INSTANCE_ID,
        "scenario_date": reporting_bundle.date,
        "arm": arm,
        "budget": budget,
        "seed": seed,
        "status": "PASS_FULL_LEGAL_SOLUTION",
        "search_objective_value": float(run.completion.objective),
        "search_objective_closure_abs": abs(
            float(run.completion.objective) - expected_search_objective
        ),
        "full_model_objective_cny": float(full_objective),
        "operating_cost_cny": operating_cost,
        "carbon_cost_cny": float(breakdown["cost_carbon"]),
        "fuel_direct_emissions_kg": float(breakdown["E_cv_direct"]),
        "charging_emissions_kg": float(breakdown["E_ev_indirect"]),
        "system_emissions_kg": float(breakdown["E_total"]),
        "enabled_physical_vehicles": int(
            breakdown["n_veh_cv"] + breakdown["n_veh_ev"]
        ),
        "assigned_cv": int(breakdown["n_veh_cv"]),
        "assigned_ev": int(breakdown["n_veh_ev"]),
        "total_trips": len(run.completion.solution.routes),
        "total_distance_m": float(breakdown["distance_total"]),
        "total_distance_km": float(breakdown["distance_total"]) / 1_000.0,
        "charging_energy_kwh": float(breakdown["electricity_kwh"]),
        "charging_cost_cny": float(breakdown["cost_elec"]),
        "completed_customer_count": len(completed),
        "required_customer_count": len(all_customers),
        "completed_demand": completed_demand,
        "required_demand": required_demand,
        "route_count": len(run.completion.solution.routes),
        "route_signature_sha256": route_hash,
        "solution_sha256": canonical_sha256(solution_payload),
        "customer_assignment_sha256": canonical_sha256(assignments),
        "arc_set_sha256": canonical_sha256(sorted(arcs)),
        "completion_attempts_all": len(trace_rows),
        "completion_successes_all": all_successes,
        "completion_failures_all": len(trace_rows) - all_successes,
        "candidate_completion_attempts": candidate_attempts,
        "candidate_completion_successes": candidate_successes,
        "candidate_completion_failures": (
            candidate_attempts - candidate_successes
        ),
        "failure_category_distribution": dict(sorted(failures.items())),
        "selected_source": run.stats["selected_source"],
        "hgs_iterations_by_view": {
            view: int(epoch.stats["hgs_iterations"])
            for view, epoch in run.view_epochs.items()
        },
        "wallclock_safety_triggered": bool(
            run.stats["wallclock_safety_triggered"]
        ),
        "elapsed_seconds": elapsed,
        "full_violation_count": len(violations),
        "slot_energy_closure_abs": abs(
            slot_energy_sum - float(breakdown["electricity_kwh"])
        ),
        "slot_cost_closure_abs": abs(
            slot_cost_sum - float(breakdown["cost_elec"])
        ),
        "slot_emissions_closure_abs": abs(
            slot_emissions_sum - float(breakdown["E_ev_indirect"])
        ),
    }
    witness = {
        "run_id": run_id,
        "arm": arm,
        "budget": budget,
        "seed": seed,
        "route_structure": groups,
        "customer_assignment": assignments,
        "arc_set": [list(arc) for arc in sorted(arcs)],
        "solution": solution_payload,
        "full_breakdown": dict(breakdown),
        "search_completion_activity": run.completion.activity,
    }
    print(
        f"DONE arm={arm} seed={seed} budget={budget} "
        f"search={row['search_objective_value']:.12f} "
        f"full={row['full_model_objective_cny']:.12f} "
        f"success={all_successes}/{len(trace_rows)} "
        f"elapsed={elapsed:.3f}s",
        flush=True,
    )
    return row, trace_rows, slot_rows, witness


RUN_FIELDS = (
    "task_id",
    "draft_status",
    "formal_search_allowed",
    "run_id",
    "instance_id",
    "scenario_date",
    "arm",
    "budget",
    "seed",
    "status",
    "search_objective_value",
    "search_objective_closure_abs",
    "full_model_objective_cny",
    "operating_cost_cny",
    "carbon_cost_cny",
    "fuel_direct_emissions_kg",
    "charging_emissions_kg",
    "system_emissions_kg",
    "enabled_physical_vehicles",
    "assigned_cv",
    "assigned_ev",
    "total_trips",
    "total_distance_m",
    "total_distance_km",
    "charging_energy_kwh",
    "charging_cost_cny",
    "completed_customer_count",
    "required_customer_count",
    "completed_demand",
    "required_demand",
    "route_count",
    "route_signature_sha256",
    "solution_sha256",
    "customer_assignment_sha256",
    "arc_set_sha256",
    "completion_attempts_all",
    "completion_successes_all",
    "completion_failures_all",
    "candidate_completion_attempts",
    "candidate_completion_successes",
    "candidate_completion_failures",
    "failure_category_distribution",
    "selected_source",
    "hgs_iterations_by_view",
    "wallclock_safety_triggered",
    "elapsed_seconds",
    "full_violation_count",
    "slot_energy_closure_abs",
    "slot_cost_closure_abs",
    "slot_emissions_closure_abs",
)

TRACE_FIELDS = (
    "task_id",
    "draft_status",
    "run_id",
    "arm",
    "budget",
    "seed",
    "evaluation_index",
    "view",
    "source",
    "iteration",
    "candidate_id",
    "completion_succeeded",
    "status",
    "search_objective",
    "exception_type",
    "exception_message",
    "failure_category",
)

SLOT_FIELDS = (
    "task_id",
    "draft_status",
    "arm",
    "budget",
    "seed",
    "hourly_calendar_row",
    "start_minute",
    "end_minute",
    "charging_kwh",
    "beijing_kwh",
    "tianjin_kwh",
    "share_of_run_charging",
    "charging_cost_cny",
    "charging_emissions_kg",
)


def self_test() -> int:
    assert_protected_hashes()
    config = ModelConfig(
        strict_multitrip=True,
        depot_charger_capacity_mode="unbounded",
    )
    base = load_china81_bundle(
        REPO,
        INSTANCE_ID,
        fleet_authority=AUTHORITY,
        model_config=config,
    )
    search, reporting, changes = arm_bundles(base)
    assert len(changes) == 12
    assert search["O"].prices.carbon_price == 0.0
    assert search["P"].prices.carbon_price == 0.0
    assert math.isclose(
        search["C"].prices.carbon_price,
        CARBON_PRICE_CNY_PER_KG,
        rel_tol=0.0,
        abs_tol=0.0,
    )
    assert search["C"].prices.diesel_ef == 0.0
    assert reporting["C"].prices.diesel_ef == base.prices.diesel_ef
    assert reporting["O"].time_profile == reporting["C"].time_profile
    initial = initial_solution()
    assert initial.routes
    customer_ids = {
        node.node_id
        for node in base.instance.nodes
        if node.node_type.lower() == "c"
    }
    _, initial_assignments, _ = canonical_route_structure(
        initial,
        customer_ids,
    )
    assert set(initial_assignments) == customer_ids
    before = install_probe_local_timing_hooks()
    assert before
    assert (
        charging_support.best_charging_action_start
        is objective_consistent_charging_start
    )
    assert_protected_hashes()
    print("SELF_TEST_PASS", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.self_test == args.run:
        parser.error("choose exactly one of --self-test or --run")
    if args.self_test:
        return self_test()

    started_at = datetime.now(UTC).isoformat()
    run_rows: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []
    slot_rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    terminal_status = "RUNNER_COMPLETE"
    failure: dict[str, Any] | None = None
    try:
        if os.environ.get("PYTHONHASHSEED") != "0":
            raise RuntimeError("PYTHONHASHSEED must equal 0")
        prereg = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
        if prereg["status"] != MARKER:
            raise RuntimeError("preregistration draft marker is missing")
        protected_before = assert_protected_hashes()
        config = ModelConfig(
            strict_multitrip=True,
            depot_charger_capacity_mode="unbounded",
        )
        base = load_china81_bundle(
            REPO,
            INSTANCE_ID,
            fleet_authority=AUTHORITY,
            model_config=config,
        )
        if base.date != "2025-02-12":
            raise RuntimeError(f"unexpected scenario date {base.date!r}")
        search_bundles, reporting_bundles, tariff_changes = arm_bundles(base)
        hook_origins = install_probe_local_timing_hooks()
        initial = initial_solution()
        for budget in BUDGETS:
            for seed in SEEDS:
                for arm in ARMS:
                    assert_protected_hashes()
                    row, trace, slots, witness = run_one(
                        arm=arm,
                        budget=budget,
                        seed=seed,
                        search_bundle=search_bundles[arm],
                        reporting_bundle=reporting_bundles[arm],
                        initial=initial,
                    )
                    run_rows.append(row)
                    trace_rows.extend(trace)
                    slot_rows.extend(slots)
                    witnesses[row["run_id"]] = witness
        protected_after = assert_protected_hashes()
        if len(run_rows) != 18:
            raise RuntimeError(f"expected 18 runs, observed {len(run_rows)}")
        if any(row["full_violation_count"] != 0 for row in run_rows):
            raise RuntimeError("at least one final solution has violations")
        if any(row["wallclock_safety_triggered"] for row in run_rows):
            raise RuntimeError("at least one HGS view hit wallclock safety")
        runner_state = {
            "schema": SCHEMA,
            "task_id": TASK_ID,
            "draft_status": MARKER,
            "terminal_status": terminal_status,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "preregistration_sha256": file_sha256(PREREGISTRATION),
            "instance_id": INSTANCE_ID,
            "scenario_date": base.date,
            "run_count": len(run_rows),
            "expected_run_count": 18,
            "protected_hashes_before": protected_before,
            "protected_hashes_after": protected_after,
            "tariff_changes": tariff_changes,
            "probe_local_hook_origins": hook_origins,
            "environment": {
                "python": sys.version.split()[0],
                "numpy": version("numpy"),
                "scipy": version("scipy"),
                "pyvrp": version("pyvrp"),
                "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
            },
            "runs": run_rows,
        }
        atomic_csv(OUT / "probe_raw.csv", run_rows, RUN_FIELDS)
        atomic_csv(OUT / "raw_runs.csv", run_rows, RUN_FIELDS)
        atomic_csv(
            OUT / "completion_trace.csv",
            trace_rows,
            TRACE_FIELDS,
        )
        atomic_csv(
            OUT / "slot_distribution.csv",
            slot_rows,
            SLOT_FIELDS,
        )
        atomic_json(
            OUT / "solution_witnesses.json",
            {
                "schema": "resetp.t5-solution-witnesses.v1",
                "task_id": TASK_ID,
                "draft_status": MARKER,
                "runs": witnesses,
            },
        )
        atomic_json(OUT / "runner_state.json", runner_state)
    except Exception as exc:  # noqa: BLE001 - preserve terminal evidence
        terminal_status = "RUNNER_HALT"
        failure = {
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": traceback.format_exc(),
            "completed_run_count": len(run_rows),
        }
        atomic_json(
            OUT / "runner_state.json",
            {
                "schema": SCHEMA,
                "task_id": TASK_ID,
                "draft_status": MARKER,
                "terminal_status": terminal_status,
                "started_at": started_at,
                "finished_at": datetime.now(UTC).isoformat(),
                "failure": failure,
                "partial_runs": run_rows,
            },
        )
    finally:
        atomic_json(
            OUT / "done.json",
            {
                "schema": "resetp.t5-runner-done.v1",
                "task_id": TASK_ID,
                "draft_status": MARKER,
                "status": terminal_status,
                "finished_at": datetime.now(UTC).isoformat(),
                "failure": failure,
            },
        )
    if failure is not None:
        print(
            f"RUNNER_HALT {failure['exception_type']}: "
            f"{failure['exception_message']}",
            flush=True,
        )
        return 1
    print("RUNNER_COMPLETE run_count=18", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
