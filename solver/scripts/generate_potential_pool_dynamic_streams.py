#!/usr/bin/env python3
"""Build the P34 A1 two-shift dynamic stream for the rebuilt PRD instance.

This is a data generator and structural validator.  It never imports or calls
the solver.  The public potential market, the private truth stream, and the
algorithm scenario are deliberately materialised as separate artifacts.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "solver/src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from setp_solver.potential_pool_dynamic import (  # noqa: E402
    DEMAND_THRESHOLD_KG,
    DYNAMIC_ORDER_SHARE,
    QIU_TRIGGER_PROTOCOL,
    TRIGGER_INTERVAL_SECONDS,
    TriggerEvent,
    TriggerProtocol,
    build_trigger_batches,
)


BASE_INSTANCE_ID = "cn-prd-50c-01-V3-TWO-SHIFT-GZ-FS"
DATASET_ID = f"{BASE_INSTANCE_ID}__P34-A1-DYNAMIC-v1"
POTENTIAL_POOL_ID = "cn-prd-gz-fs-71p-01-OSM"
CONTRACT_ID = "P34_A1_TWO_SHIFT_POTENTIAL_MARKET_DYNAMIC_DAY_V2"
OPERATION_DATE = "2025-02-12"

BASE_DATA = Path(
    "data/ChinaInstances/china81_private_rebuild_v1_20260811"
)
SOURCE_STATIC = Path(
    "data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723"
)
SOURCE_MATRICES = Path(
    "data/ChinaInstances/"
    "china81_local_directed_matrices_corrected_v10_20260723"
)
SOURCE_POOL_INSTANCE_ID = "cn-prd-150c-01-V2-LOCATIONS"
DEFAULT_OUTPUT = Path(
    "data/ChinaInstances/china81_dynamic_stream_v1_20260811"
)
DEFAULT_REPORT = Path("solver/reports/dynamic_stream_rebuild_20260811/report.md")

DAILY_CITY_QUOTA = {"guangzhou": 36, "foshan": 14}
INITIAL_CITY_QUOTA = {"guangzhou": 29, "foshan": 11}
DYNAMIC_CITY_QUOTA = {"guangzhou": 7, "foshan": 3}
DYNAMIC_SHIFT_QUOTA = {"AM": 3, "PM": 7}
MIN_PAYLOAD_CAPACITY_KG = 1_700.0
SHIFT_WINDOWS = {
    "AM": (8.0 * 3600.0, 11.0 * 3600.0),
    "PM": (13.0 * 3600.0, 19.0 * 3600.0),
}
OSM_TYPES = {"node", "way"}
_TOL = 1.0e-9

PROTECTED_FILES = (
    Path("solver/src/setp_solver/cost.py"),
    Path("solver/src/setp_solver/check.py"),
    Path("solver/src/setp_solver/search/evaluation.py"),
)


@dataclass(frozen=True)
class BuildResult:
    potential_pool: tuple[dict[str, Any], ...]
    attribute_prior: tuple[dict[str, Any], ...]
    truth_orders: tuple[dict[str, Any], ...]
    dynamic_events: tuple[dict[str, Any], ...]
    initial_orders_public: tuple[dict[str, Any], ...]
    algorithm_scenario: tuple[dict[str, Any], ...]
    truth_trigger_batches: tuple[dict[str, Any], ...]
    scenario_trigger_batches: tuple[dict[str, Any], ...]
    serviceability: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]
    algorithm_visible_payload: dict[str, Any]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the P34 A1 two-shift potential-pool dynamic stream; "
            "no solver is imported or invoked"
        )
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--market-sampling-seed", type=int, default=1)
    parser.add_argument("--true-order-stream-seed", type=int, default=2)
    parser.add_argument("--algorithm-scenario-seed", type=int, default=3)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build and validate in memory, print a summary, write nothing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo = args.repo_root.resolve()
    output = _resolve(repo, args.output)
    report = _resolve(repo, args.report)
    result = build_result(
        repo,
        market_sampling_seed=args.market_sampling_seed,
        true_order_stream_seed=args.true_order_stream_seed,
        algorithm_scenario_seed=args.algorithm_scenario_seed,
    )
    summary = _summary(result)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "DRY_RUN_VALIDATED_NO_FILES_WRITTEN",
                    "solver_invoked": False,
                    **summary,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if output.exists():
        raise FileExistsError(
            f"refusing to overwrite existing dynamic dataset: {output}"
        )
    _write_result(repo, output, report, result)
    print(
        json.dumps(
            {
                "status": "DYNAMIC_STREAM_DONE",
                "solver_invoked": False,
                "output": str(output.relative_to(repo)),
                "report": str(report.relative_to(repo)),
                **summary,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def build_result(
    repo: Path,
    *,
    market_sampling_seed: int,
    true_order_stream_seed: int,
    algorithm_scenario_seed: int,
) -> BuildResult:
    pool, templates, direct_options, source_paths = _load_inputs(repo)
    pool_by_city = {
        city: [row for row in pool if row["city"] == city]
        for city in DAILY_CITY_QUOTA
    }

    market_rng = _independent_rng(
        market_sampling_seed, "public-initial-market-sample"
    )
    truth_rng = _independent_rng(
        true_order_stream_seed, "private-true-future-stream"
    )
    scenario_rng = _independent_rng(
        algorithm_scenario_seed, "algorithm-internal-future-scenario"
    )

    initial_positions = _sample_positions_by_city(
        pool_by_city, INITIAL_CITY_QUOTA, market_rng
    )
    initial_ids = {row["potential_customer_id"] for row in initial_positions}
    remaining_by_city = {
        city: [
            row
            for row in rows
            if row["potential_customer_id"] not in initial_ids
        ]
        for city, rows in pool_by_city.items()
    }
    truth_future_positions = _sample_positions_by_city(
        remaining_by_city, DYNAMIC_CITY_QUOTA, truth_rng
    )
    scenario_positions = _sample_positions_by_city(
        remaining_by_city, DYNAMIC_CITY_QUOTA, scenario_rng
    )

    truth_future_matching, initial_matching = _sample_truth_matchings(
        truth_future_positions,
        initial_positions,
        templates,
        direct_options,
        truth_rng,
    )
    scenario_matching = _sample_future_matching(
        scenario_positions,
        templates,
        direct_options,
        scenario_rng,
    )

    initial_rows = _materialize_initial_orders(
        initial_positions, initial_matching, direct_options
    )
    truth_dynamic_rows, truth_batches = _materialize_future_orders(
        truth_future_positions,
        truth_future_matching,
        direct_options,
        truth_rng,
        prefix="TRUE_DYN",
        stream_class="true_future",
    )
    scenario_rows, scenario_batches = _materialize_future_orders(
        scenario_positions,
        scenario_matching,
        direct_options,
        scenario_rng,
        prefix="SCENARIO",
        stream_class="algorithm_internal_scenario",
    )

    truth_orders = tuple(
        sorted(
            [*initial_rows, *truth_dynamic_rows],
            key=lambda row: (
                float(row["appearance_second"]),
                str(row["event_id"]),
            ),
        )
    )
    serviceability = tuple(
        _serviceability_row(row) for row in truth_dynamic_rows
    )
    _validate_contract(
        pool,
        templates,
        truth_orders,
        truth_dynamic_rows,
        scenario_rows,
        serviceability,
    )

    public_initial = tuple(_public_order(row) for row in initial_rows)
    truth_hash = _payload_hash(truth_orders)
    scenario_hash = _payload_hash(scenario_rows)
    truth_future_ids = {
        row["potential_customer_id"] for row in truth_dynamic_rows
    }
    scenario_ids = {row["potential_customer_id"] for row in scenario_rows}
    unrevealed_candidate_count = len(pool) - len(public_initial)
    false_positive_count = unrevealed_candidate_count - len(truth_dynamic_rows)
    widths = sorted(float(row["time_window_width_minute"]) for row in truth_orders)
    service_slacks = [
        float(row["trigger_service_slack_second"]) for row in serviceability
    ]

    public_paths = {
        "potential_pool": "public/potential_pool.csv",
        "order_attribute_prior": "public/order_attribute_prior.csv",
        "initial_orders": "public/initial_orders_at_0800.csv",
        "algorithm_scenario": (
            f"public/algorithm_scenario_seed_{algorithm_scenario_seed}.csv"
        ),
        "algorithm_scenario_trigger_batches": (
            "public/algorithm_scenario_trigger_batches.csv"
        ),
    }
    private_paths = {
        "truth_orders": "private/truth_orders.csv",
        "true_dynamic_events": "private/true_dynamic_events.csv",
        "true_trigger_batches": "private/true_trigger_batches.csv",
    }
    algorithm_visible_payload = {
        "schema": "resetp.p34-a1.algorithm-visible.v1",
        "operation_date": OPERATION_DATE,
        "contract_id": CONTRACT_ID,
        "dataset_id": DATASET_ID,
        "as_of_second": 8.0 * 3600.0,
        "as_of_clock": "08:00:00",
        "base_instance_structure": BASE_INSTANCE_ID,
        "potential_pool_id": POTENTIAL_POOL_ID,
        "known_daily_order_count": 50,
        "known_dynamic_order_count": 10,
        "daily_city_quota": DAILY_CITY_QUOTA,
        "dynamic_city_quota": DYNAMIC_CITY_QUOTA,
        "dynamic_shift_quota": DYNAMIC_SHIFT_QUOTA,
        "trigger_protocol": {
            "policy_id": QIU_TRIGGER_PROTOCOL.policy_id,
            "interval_seconds": TRIGGER_INTERVAL_SECONDS,
            "demand_threshold_kg": DEMAND_THRESHOLD_KG,
            "source": QIU_TRIGGER_PROTOCOL.source,
        },
        "visible_files": public_paths,
        "algorithm_internal_scenario": {
            "seed": algorithm_scenario_seed,
            "random_stream_id": (
                f"{CONTRACT_ID}:algorithm-internal-future-scenario"
            ),
            "sampling_rule": (
                "independent stratified sample from the registered potential "
                "pool after excluding only orders already revealed at 08:00"
            ),
        },
        "excluded_fields": [
            "market_sampling_seed",
            "true_order_stream_seed",
            "truth_order_ids",
            "truth_event_times",
            "truth_stream_sha256",
            "private_artifact_paths",
        ],
    }

    metadata = {
        "status": "DYNAMIC_STREAM_DONE",
        "schema": "resetp.p34-a1.two-shift-dynamic-dataset.v1",
        "operation_date": OPERATION_DATE,
        "contract_id": CONTRACT_ID,
        "dataset_id": DATASET_ID,
        "base_instance_id": BASE_INSTANCE_ID,
        "potential_pool_id": POTENTIAL_POOL_ID,
        "scenario_class": "constructed_simulation_not_observed_order_day",
        "solver_invoked": False,
        "formal_experiment": False,
        "search_evaluations": 0,
        "static_instance_modified": False,
        "protected_files_modified": False,
        "source_paths": source_paths,
        "public_artifacts": public_paths,
        "private_oracle_artifacts": private_paths,
        "validation_artifact": "validation/dynamic_serviceability.csv",
        "sampling_contract": {
            "potential_position_count": len(pool),
            "actual_order_count": len(truth_orders),
            "initial_visible_order_count": len(initial_rows),
            "dynamic_order_count": len(truth_dynamic_rows),
            "dynamic_order_share": DYNAMIC_ORDER_SHARE,
            "daily_city_quota": DAILY_CITY_QUOTA,
            "initial_city_quota": INITIAL_CITY_QUOTA,
            "dynamic_city_quota": DYNAMIC_CITY_QUOTA,
            "dynamic_shift_quota": DYNAMIC_SHIFT_QUOTA,
            "market_sampling_seed": market_sampling_seed,
            "true_order_stream_seed": true_order_stream_seed,
            "algorithm_scenario_seed": algorithm_scenario_seed,
            "true_random_stream_id": (
                f"{CONTRACT_ID}:private-true-future-stream"
            ),
            "algorithm_random_stream_id": (
                f"{CONTRACT_ID}:algorithm-internal-future-scenario"
            ),
            "truth_and_scenario_rng_objects_are_distinct": True,
        },
        "trigger_protocol": {
            "policy_id": QIU_TRIGGER_PROTOCOL.policy_id,
            "interval_seconds": TRIGGER_INTERVAL_SECONDS,
            "demand_threshold_kg": DEMAND_THRESHOLD_KG,
            "source": QIU_TRIGGER_PROTOCOL.source,
            "reception_windows": {
                shift: {"start_second": start, "end_second": end}
                for shift, (start, end) in SHIFT_WINDOWS.items()
            },
            "500_kg_status": "literature protocol transfer",
            "selected_after_seeing_results": False,
        },
        "time_window_distribution": {
            "count": len(widths),
            "minimum_minute": min(widths),
            "median_minute": statistics.median(widths),
            "maximum_minute": max(widths),
            "inherits_exact_50_value_multiset_from_base_instance": True,
        },
        "information_isolation": {
            "algorithm_receives_only": "public/algorithm_visible_at_0800.json",
            "truth_seed_in_algorithm_view": False,
            "truth_future_list_in_algorithm_view": False,
            "private_paths_in_algorithm_view": False,
            "unrevealed_candidate_position_count_at_0800": (
                unrevealed_candidate_count
            ),
            "true_future_order_count_at_0800": len(truth_dynamic_rows),
            "subtraction_attack_false_positive_count_at_0800": (
                false_positive_count
            ),
            "exact_future_reconstruction_by_subtraction": False,
            "truth_scenario_position_overlap_count": len(
                truth_future_ids & scenario_ids
            ),
            "independence_basis": (
                "separate SHA-256-derived RNG instances; the scenario builder "
                "receives the public pool, public prior, revealed orders, and "
                "scenario seed, but no truth seed or truth future list"
            ),
        },
        "serviceability": {
            "dynamic_order_count": len(serviceability),
            "born_expired_count": sum(
                not row["serviceable_at_appearance"] for row in serviceability
            ),
            "trigger_expired_count": sum(
                not row["serviceable_at_trigger"] for row in serviceability
            ),
            "outside_shift_appearance_count": sum(
                not row["appearance_inside_assigned_shift"]
                for row in serviceability
            ),
            "trigger_outside_assigned_shift_count": sum(
                not row["trigger_inside_assigned_shift"]
                for row in serviceability
            ),
            "minimum_trigger_service_slack_second": min(service_slacks),
            "validator": (
                "direct compatible depot-to-customer travel after appearance "
                "and after actual P10 trigger; capacity and assigned-shift bounds"
            ),
        },
        "hashes": {
            "truth_stream_sha256": truth_hash,
            "algorithm_scenario_sha256": scenario_hash,
        },
    }
    return BuildResult(
        potential_pool=tuple(pool),
        attribute_prior=tuple(templates),
        truth_orders=truth_orders,
        dynamic_events=tuple(truth_dynamic_rows),
        initial_orders_public=public_initial,
        algorithm_scenario=tuple(scenario_rows),
        truth_trigger_batches=tuple(truth_batches),
        scenario_trigger_batches=tuple(scenario_batches),
        serviceability=serviceability,
        metadata=metadata,
        algorithm_visible_payload=algorithm_visible_payload,
    )


def _load_inputs(
    repo: Path,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, Any],
]:
    source_nodes_path = (
        repo
        / SOURCE_STATIC
        / "instances"
        / SOURCE_POOL_INSTANCE_ID
        / "nodes.csv"
    )
    base_orders_path = repo / BASE_DATA / "orders.csv"
    shift_contract_path = repo / BASE_DATA / "shift_contract.json"
    fleet_caps_path = repo / BASE_DATA / "fleet_caps.csv"
    source_nodes = _read_csv(source_nodes_path)
    base_orders = _read_csv(base_orders_path)
    pool_nodes = [
        row
        for row in source_nodes
        if row["node_type"] == "customer"
        and row["city"] in DAILY_CITY_QUOTA
    ]
    if Counter(row["city"] for row in pool_nodes) != Counter(
        {"guangzhou": 50, "foshan": 21}
    ):
        raise RuntimeError("the Guangzhou-Foshan OSM pool is not 50+21 positions")
    if len(base_orders) != 50 or {
        row["instance_id"] for row in base_orders
    } != {BASE_INSTANCE_ID}:
        raise RuntimeError("the rebuilt base instance does not contain 50 orders")

    potential_pool = []
    for row in sorted(pool_nodes, key=lambda item: item["node_id"]):
        osm_type, osm_id = row["source_identity"].split("/", 1)
        if osm_type not in OSM_TYPES or not osm_id.isdigit():
            raise RuntimeError(
                f"potential position lacks a real OSM identity: {row['node_id']}"
            )
        potential_pool.append(
            {
                "potential_pool_id": POTENTIAL_POOL_ID,
                "potential_customer_id": row["node_id"],
                "city": row["city"],
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "osm_type": osm_type,
                "osm_id": osm_id,
                "source_identity": row["source_identity"],
                "source_instance_id": SOURCE_POOL_INSTANCE_ID,
                "source_matrix_node_id": row["node_id"],
            }
        )

    templates = []
    for index, row in enumerate(
        sorted(base_orders, key=lambda item: item["customer_id"]), start=1
    ):
        templates.append(
            {
                "prior_template_id": f"ATTR_{index:03d}",
                "demand_kg": float(row["demand_kg"]),
                "service_second": float(row["service_minutes"]) * 60.0,
                "ready_second": float(row["time_window_early_minute"]) * 60.0,
                "due_second": float(row["time_window_late_minute"]) * 60.0,
                "time_window_width_minute": float(
                    row["time_window_width_minute"]
                ),
                "shift_id": row["shift_id"],
                "attribute_source": (
                    f"{BASE_INSTANCE_ID}: anonymous empirical order-attribute prior"
                ),
            }
        )
    if Counter(row["shift_id"] for row in templates) != Counter(
        {"AM": 17, "PM": 33}
    ):
        raise RuntimeError("base order shift distribution is not 17 AM / 33 PM")

    direct_options = _load_direct_options(repo, potential_pool)
    fleet_caps = _read_csv(fleet_caps_path)
    if any(
        int(row["num_cv"]) < 1 or int(row["num_ev"]) < 1
        for row in fleet_caps
    ):
        raise RuntimeError("a rebuilt depot lacks a compatible vehicle type")
    source_paths = {
        "base_orders": _source_entry(repo, base_orders_path),
        "base_shift_contract": _source_entry(repo, shift_contract_path),
        "base_fleet_caps": _source_entry(repo, fleet_caps_path),
        "potential_pool_nodes": _source_entry(repo, source_nodes_path),
        "source_matrix_instance": {
            "path": str(
                SOURCE_MATRICES / "instances" / SOURCE_POOL_INSTANCE_ID
            ),
            "sha256": _sha256_path(
                repo
                / SOURCE_MATRICES
                / "instances"
                / SOURCE_POOL_INSTANCE_ID
            ),
        },
    }
    return potential_pool, templates, direct_options, source_paths


def _load_direct_options(
    repo: Path, potential_pool: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    options: dict[str, list[tuple[float, str, str]]] = {
        str(row["potential_customer_id"]): [] for row in potential_pool
    }
    matrix_root = (
        repo
        / SOURCE_MATRICES
        / "instances"
        / SOURCE_POOL_INSTANCE_ID
    )
    for vehicle_type in ("cv", "ev"):
        rows = {
            row["node_id"]: row
            for row in _read_csv(
                matrix_root / vehicle_type / "road_duration_s.csv"
            )
        }
        for depot_id in ("D_guangzhou", "D_foshan"):
            matrix_row = rows[depot_id]
            for customer_id in options:
                options[customer_id].append(
                    (
                        float(matrix_row[customer_id]),
                        depot_id,
                        vehicle_type,
                    )
                )
    return {
        customer_id: {
            "direct_travel_second": min(values)[0],
            "compatible_depot_id": min(values)[1],
            "compatible_vehicle_type": min(values)[2],
            "compatible_payload_capacity_kg": MIN_PAYLOAD_CAPACITY_KG,
        }
        for customer_id, values in options.items()
    }


def _sample_positions_by_city(
    rows_by_city: Mapping[str, Sequence[dict[str, Any]]],
    quotas: Mapping[str, int],
    rng: random.Random,
) -> list[dict[str, Any]]:
    selected = []
    for city in sorted(quotas):
        candidates = list(rows_by_city[city])
        quota = int(quotas[city])
        if len(candidates) < quota:
            raise RuntimeError(f"not enough {city} potential positions")
        selected.extend(rng.sample(candidates, quota))
    return sorted(selected, key=lambda row: row["potential_customer_id"])


def _sample_truth_matchings(
    future_positions: Sequence[dict[str, Any]],
    initial_positions: Sequence[dict[str, Any]],
    templates: Sequence[dict[str, Any]],
    direct_options: Mapping[str, Mapping[str, Any]],
    rng: random.Random,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_shift = {
        shift: [row for row in templates if row["shift_id"] == shift]
        for shift in DYNAMIC_SHIFT_QUOTA
    }
    for _ in range(2_000):
        future_templates = []
        for shift in sorted(DYNAMIC_SHIFT_QUOTA):
            future_templates.extend(
                rng.sample(by_shift[shift], DYNAMIC_SHIFT_QUOTA[shift])
            )
        future_matching = _bipartite_match(
            future_positions,
            future_templates,
            direct_options,
            dispatch_mode="after_maximum_trigger_wait",
            rng=rng,
        )
        if future_matching is None:
            continue
        future_template_ids = {
            row["prior_template_id"] for row in future_templates
        }
        initial_templates = [
            row
            for row in templates
            if row["prior_template_id"] not in future_template_ids
        ]
        initial_matching = _bipartite_match(
            initial_positions,
            initial_templates,
            direct_options,
            dispatch_mode="visible_at_day_start",
            rng=rng,
        )
        if initial_matching is not None:
            return future_matching, initial_matching
    raise RuntimeError("could not match the exact base attribute multiset")


def _sample_future_matching(
    positions: Sequence[dict[str, Any]],
    templates: Sequence[dict[str, Any]],
    direct_options: Mapping[str, Mapping[str, Any]],
    rng: random.Random,
) -> dict[str, dict[str, Any]]:
    by_shift = {
        shift: [row for row in templates if row["shift_id"] == shift]
        for shift in DYNAMIC_SHIFT_QUOTA
    }
    for _ in range(2_000):
        sampled = []
        for shift in sorted(DYNAMIC_SHIFT_QUOTA):
            sampled.extend(rng.sample(by_shift[shift], DYNAMIC_SHIFT_QUOTA[shift]))
        matching = _bipartite_match(
            positions,
            sampled,
            direct_options,
            dispatch_mode="after_maximum_trigger_wait",
            rng=rng,
        )
        if matching is not None:
            return matching
    raise RuntimeError("could not sample a serviceable internal scenario")


def _bipartite_match(
    positions: Sequence[dict[str, Any]],
    templates: Sequence[dict[str, Any]],
    direct_options: Mapping[str, Mapping[str, Any]],
    *,
    dispatch_mode: str,
    rng: random.Random,
) -> dict[str, dict[str, Any]] | None:
    template_by_id = {row["prior_template_id"]: row for row in templates}
    candidates: dict[str, list[str]] = {}
    for position in positions:
        position_id = str(position["potential_customer_id"])
        travel = float(direct_options[position_id]["direct_travel_second"])
        eligible = []
        for template in templates:
            if dispatch_mode == "visible_at_day_start":
                dispatch = SHIFT_WINDOWS["AM"][0]
            elif dispatch_mode == "after_maximum_trigger_wait":
                dispatch = (
                    SHIFT_WINDOWS[str(template["shift_id"])][0]
                    + TRIGGER_INTERVAL_SECONDS
                )
            else:
                raise ValueError(f"unknown dispatch mode: {dispatch_mode}")
            if (
                float(template["demand_kg"]) <= MIN_PAYLOAD_CAPACITY_KG + _TOL
                and dispatch + travel <= float(template["due_second"]) + _TOL
            ):
                eligible.append(str(template["prior_template_id"]))
        rng.shuffle(eligible)
        candidates[position_id] = eligible
    ordered_positions = sorted(
        (str(row["potential_customer_id"]) for row in positions),
        key=lambda position_id: (len(candidates[position_id]), position_id),
    )
    matched_template_to_position: dict[str, str] = {}

    def augment(position_id: str, seen: set[str]) -> bool:
        for template_id in candidates[position_id]:
            if template_id in seen:
                continue
            seen.add(template_id)
            occupied = matched_template_to_position.get(template_id)
            if occupied is None or augment(occupied, seen):
                matched_template_to_position[template_id] = position_id
                return True
        return False

    for position_id in ordered_positions:
        if not augment(position_id, set()):
            return None
    return {
        position_id: template_by_id[template_id]
        for template_id, position_id in matched_template_to_position.items()
    }


def _materialize_initial_orders(
    positions: Sequence[dict[str, Any]],
    matching: Mapping[str, Mapping[str, Any]],
    direct_options: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for index, position in enumerate(
        sorted(positions, key=lambda row: row["potential_customer_id"]), start=1
    ):
        position_id = str(position["potential_customer_id"])
        row = _base_order_row(
            position,
            matching[position_id],
            direct_options[position_id],
            event_id=f"INITIAL_{index:03d}_{position_id}",
            stream_class="initial_visible_truth",
        )
        row.update(
            {
                "appearance_second": SHIFT_WINDOWS["AM"][0],
                "appearance_clock": "08:00:00",
                "initially_visible": True,
                "trigger_batch_index": 0,
                "trigger_second": SHIFT_WINDOWS["AM"][0],
                "trigger_clock": "08:00:00",
                "trigger_cause": "initial_visibility",
            }
        )
        rows.append(row)
    return rows


def _materialize_future_orders(
    positions: Sequence[dict[str, Any]],
    matching: Mapping[str, Mapping[str, Any]],
    direct_options: Mapping[str, Mapping[str, Any]],
    rng: random.Random,
    *,
    prefix: str,
    stream_class: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    drafts = []
    for index, position in enumerate(
        sorted(positions, key=lambda row: row["potential_customer_id"]), start=1
    ):
        position_id = str(position["potential_customer_id"])
        template = matching[position_id]
        option = direct_options[position_id]
        shift_id = str(template["shift_id"])
        shift_start, shift_end = SHIFT_WINDOWS[shift_id]
        latest = min(
            math.nextafter(shift_end, -math.inf),
            float(template["due_second"])
            - float(option["direct_travel_second"])
            - TRIGGER_INTERVAL_SECONDS,
        )
        if latest < shift_start - _TOL:
            raise AssertionError("matched future order has no legal appearance time")
        appearance = rng.uniform(shift_start, latest)
        row = _base_order_row(
            position,
            template,
            option,
            event_id=f"{prefix}_{index:03d}_{position_id}",
            stream_class=stream_class,
        )
        row.update(
            {
                "appearance_second": appearance,
                "appearance_clock": _clock(appearance),
                "initially_visible": False,
            }
        )
        drafts.append(row)

    batch_rows: list[dict[str, Any]] = []
    trigger_by_event: dict[str, dict[str, Any]] = {}
    global_batch_index = 0
    for shift_id in ("AM", "PM"):
        shift_start, shift_end = SHIFT_WINDOWS[shift_id]
        protocol = TriggerProtocol(
            policy_id=QIU_TRIGGER_PROTOCOL.policy_id,
            interval_seconds=TRIGGER_INTERVAL_SECONDS,
            demand_threshold_kg=DEMAND_THRESHOLD_KG,
            reception_start_second=shift_start,
            reception_end_second=shift_end,
            source=QIU_TRIGGER_PROTOCOL.source,
        )
        events = [
            TriggerEvent(
                event_id=str(row["event_id"]),
                customer_id=str(row["potential_customer_id"]),
                appearance_second=float(row["appearance_second"]),
                demand_kg=float(row["demand_kg"]),
            )
            for row in drafts
            if row["shift_id"] == shift_id
        ]
        for local_batch in build_trigger_batches(events, protocol):
            global_batch_index += 1
            batch = replace(local_batch, batch_index=global_batch_index)
            batch_row = {
                **asdict(batch),
                "shift_id": shift_id,
                "trigger_clock": _clock(batch.trigger_second),
                "event_ids": "|".join(batch.event_ids),
                "customer_ids": "|".join(batch.customer_ids),
            }
            batch_rows.append(batch_row)
            for event_id in batch.event_ids:
                trigger_by_event[event_id] = batch_row

    rows = []
    for row in drafts:
        batch = trigger_by_event[str(row["event_id"])]
        materialized = dict(row)
        materialized.update(
            {
                "trigger_batch_index": batch["batch_index"],
                "trigger_second": batch["trigger_second"],
                "trigger_clock": batch["trigger_clock"],
                "trigger_cause": batch["cause"],
            }
        )
        rows.append(materialized)
    rows.sort(key=lambda row: (row["appearance_second"], row["event_id"]))
    return rows, batch_rows


def _base_order_row(
    position: Mapping[str, Any],
    template: Mapping[str, Any],
    option: Mapping[str, Any],
    *,
    event_id: str,
    stream_class: str,
) -> dict[str, Any]:
    return {
        "dataset_id": DATASET_ID,
        "event_id": event_id,
        "stream_class": stream_class,
        "potential_pool_id": POTENTIAL_POOL_ID,
        "potential_customer_id": position["potential_customer_id"],
        "city": position["city"],
        "latitude": position["latitude"],
        "longitude": position["longitude"],
        "osm_type": position["osm_type"],
        "osm_id": position["osm_id"],
        "source_identity": position["source_identity"],
        "source_matrix_node_id": position["source_matrix_node_id"],
        "source_attribute_template_id": template["prior_template_id"],
        "demand_kg": template["demand_kg"],
        "service_second": template["service_second"],
        "ready_second": template["ready_second"],
        "ready_clock": _clock(float(template["ready_second"])),
        "due_second": template["due_second"],
        "due_clock": _clock(float(template["due_second"])),
        "time_window_width_minute": template["time_window_width_minute"],
        "shift_id": template["shift_id"],
        "shift_start_second": SHIFT_WINDOWS[str(template["shift_id"])][0],
        "shift_end_second": SHIFT_WINDOWS[str(template["shift_id"])][1],
        "compatible_depot_id": option["compatible_depot_id"],
        "compatible_vehicle_type": option["compatible_vehicle_type"],
        "compatible_payload_capacity_kg": option[
            "compatible_payload_capacity_kg"
        ],
        "direct_travel_second": option["direct_travel_second"],
    }


def _public_order(row: Mapping[str, Any]) -> dict[str, Any]:
    excluded = {"source_attribute_template_id", "stream_class"}
    return {key: value for key, value in row.items() if key not in excluded}


def _serviceability_row(row: Mapping[str, Any]) -> dict[str, Any]:
    appearance = float(row["appearance_second"])
    trigger = float(row["trigger_second"])
    travel = float(row["direct_travel_second"])
    ready = float(row["ready_second"])
    due = float(row["due_second"])
    shift_start = float(row["shift_start_second"])
    shift_end = float(row["shift_end_second"])
    appearance_service_start = max(appearance + travel, ready)
    trigger_service_start = max(trigger + travel, ready)
    return {
        "event_id": row["event_id"],
        "potential_customer_id": row["potential_customer_id"],
        "shift_id": row["shift_id"],
        "appearance_second": appearance,
        "trigger_second": trigger,
        "ready_second": ready,
        "due_second": due,
        "direct_travel_second": travel,
        "appearance_service_start_second": appearance_service_start,
        "trigger_service_start_second": trigger_service_start,
        "appearance_service_slack_second": due - appearance_service_start,
        "trigger_service_slack_second": due - trigger_service_start,
        "payload_pass": (
            float(row["demand_kg"])
            <= float(row["compatible_payload_capacity_kg"]) + _TOL
        ),
        "appearance_inside_assigned_shift": (
            shift_start - _TOL <= appearance < shift_end - _TOL
        ),
        "trigger_inside_assigned_shift": (
            shift_start - _TOL <= trigger <= shift_end + _TOL
        ),
        "serviceable_at_appearance": appearance_service_start <= due + _TOL,
        "serviceable_at_trigger": trigger_service_start <= due + _TOL,
    }


def _validate_contract(
    pool: Sequence[Mapping[str, Any]],
    templates: Sequence[Mapping[str, Any]],
    truth_orders: Sequence[Mapping[str, Any]],
    dynamic_events: Sequence[Mapping[str, Any]],
    scenario_rows: Sequence[Mapping[str, Any]],
    validations: Sequence[Mapping[str, Any]],
) -> None:
    if len(pool) != 71 or len(truth_orders) != 50 or len(dynamic_events) != 10:
        raise AssertionError("pool/day/dynamic cardinality contract failed")
    if len({row["potential_customer_id"] for row in truth_orders}) != 50:
        raise AssertionError("truth day contains duplicate positions")
    if len({row["potential_customer_id"] for row in scenario_rows}) != 10:
        raise AssertionError("algorithm scenario contains duplicate positions")
    if Counter(row["city"] for row in truth_orders) != Counter(DAILY_CITY_QUOTA):
        raise AssertionError("truth day city quota changed")
    if Counter(row["shift_id"] for row in truth_orders) != Counter(
        {"AM": 17, "PM": 33}
    ):
        raise AssertionError("truth day shift structure changed")
    if Counter(row["shift_id"] for row in dynamic_events) != Counter(
        DYNAMIC_SHIFT_QUOTA
    ):
        raise AssertionError("dynamic shift quota changed")
    if Counter(row["city"] for row in dynamic_events) != Counter(
        DYNAMIC_CITY_QUOTA
    ):
        raise AssertionError("dynamic city quota changed")
    widths = sorted(float(row["time_window_width_minute"]) for row in truth_orders)
    source_widths = sorted(
        float(row["time_window_width_minute"]) for row in templates
    )
    if widths != source_widths:
        raise AssertionError("time-window empirical multiset changed")
    if not all(
        row["payload_pass"]
        and row["appearance_inside_assigned_shift"]
        and row["trigger_inside_assigned_shift"]
        and row["serviceable_at_appearance"]
        and row["serviceable_at_trigger"]
        for row in validations
    ):
        raise AssertionError("a dynamic order is born or triggered infeasible")


def _write_result(
    repo: Path,
    output: Path,
    report: Path,
    result: BuildResult,
) -> None:
    def dated(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
        return tuple(
            {**row, "operation_date": OPERATION_DATE}
            for row in rows
        )

    output.mkdir(parents=True, exist_ok=False)
    files: list[tuple[Path, Any]] = [
        (output / "public/potential_pool.csv", result.potential_pool),
        (output / "public/order_attribute_prior.csv", result.attribute_prior),
        (
            output / "public/initial_orders_at_0800.csv",
            dated(result.initial_orders_public),
        ),
        (
            output
            / (
                "public/algorithm_scenario_seed_"
                f"{result.metadata['sampling_contract']['algorithm_scenario_seed']}"
                ".csv"
            ),
            dated(_public_order(row) for row in result.algorithm_scenario),
        ),
        (
            output / "public/algorithm_scenario_trigger_batches.csv",
            dated(result.scenario_trigger_batches),
        ),
        (output / "private/truth_orders.csv", dated(result.truth_orders)),
        (output / "private/true_dynamic_events.csv", dated(result.dynamic_events)),
        (
            output / "private/true_trigger_batches.csv",
            dated(result.truth_trigger_batches),
        ),
        (
            output / "validation/dynamic_serviceability.csv",
            dated(result.serviceability),
        ),
    ]
    for path, rows in files:
        _write_csv(path, rows)
    _write_json(
        output / "public/algorithm_visible_at_0800.json",
        result.algorithm_visible_payload,
    )
    _write_json(output / "metadata.json", result.metadata)

    artifact_hashes = {
        "schema": "resetp.artifact-hashes.v1",
        "dataset_id": DATASET_ID,
        "artifacts": [
            {
                "path": str(path.relative_to(repo)),
                "sha256": _sha256_path(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(
                item
                for item in output.rglob("*")
                if item.is_file() and not item.name.startswith("._")
            )
        ],
    }
    _write_json(output / "artifact_hashes.json", artifact_hashes)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(_render_report(repo, output, result), encoding="utf-8")


def _render_report(repo: Path, output: Path, result: BuildResult) -> str:
    metadata = result.metadata
    isolation = metadata["information_isolation"]
    service = metadata["serviceability"]
    widths = metadata["time_window_distribution"]
    trigger_causes = Counter(
        row["cause"] for row in result.truth_trigger_batches
    )
    truth_ids = {
        row["potential_customer_id"] for row in result.dynamic_events
    }
    scenario_ids = {
        row["potential_customer_id"] for row in result.algorithm_scenario
    }
    protected_rows = []
    for relative in PROTECTED_FILES:
        protected_rows.append(
            f"| `{relative}` | `{_sha256_path(repo / relative)}` |"
        )
    data_relative = output.relative_to(repo)
    return f"""DYNAMIC_STREAM_DONE

# P34 A1 潜在客户池与双班次动态订单流重建报告（2026-08-11）

## 结论

已为 `{BASE_INSTANCE_ID}` 生成一套独立的动态日数据；静态算例未修改，求解器未调用，正式搜索次数为 0。

- 潜在客户池：**{len(result.potential_pool)}** 个真实 OSM 实体位置（广州 50、佛山 21）。
- 当日真实订单：**50** 单，其中 08:00 已知 40 单，后续动态揭示 **10** 单；当天不下单位置 **21** 个。
- 动态订单班次：上午 **3** 单、下午 **7** 单；午休出现 0 单，收车后出现 0 单。
- 可服务性：出生即过期 **{service['born_expired_count']}** 单，实际触发后过期 **{service['trigger_expired_count']}** 单。
- 算法情景：从同一潜在池另行独立抽取 10 单；本次样例与真实未来位置偶然重合 **{len(truth_ids & scenario_ids)}** 个，这个重合数没有参与筛选。

当前数据目录：`{data_relative}`。本报告目录中早先的三地区 V2 样例保留为历史文件，不属于本次 V3 双班次数据。

## 1. 数据身份与来源

潜在池取自 `cn-prd-150c-01-V2-LOCATIONS` 中全部广州、佛山客户点。71/71 个位置的 `source_identity` 均为 `node/<OSM id>` 或 `way/<OSM id>`；没有生成坐标，也没有把深圳、东莞位置带入新算例。

当日城市结构保持新算例的 36 个广州单、14 个佛山单。需求量、服务时长和时间窗使用新静态算例 50 条匿名属性模板；真实日完整继承这 50 个时间窗宽度值，因此范围为 **{widths['minimum_minute']:.1f}–{widths['maximum_minute']:.1f} 分钟**，中位数 **{widths['median_minute']:.1f} 分钟**。它是披露的构造仿真日，不是现实观测订单日。

## 2. P10 触发与两班次约束

触发规则逐班次应用“累计需求达到 500 kg，或等待 30 分钟，先到者触发”。500 kg 按邱莹莹论文第 23–24 页式 3-2/3-3作**协议移植**，没有根据本次结果倒选。

真实动态流共形成 {len(result.truth_trigger_batches)} 个触发批次：{dict(sorted(trigger_causes.items()))}。上午的出现和触发都落在 08:00–11:00，下午都落在 13:00–19:00；11:00–13:00 不生成事件。

## 3. 信息隔离论证

算法在 08:00 只能得到 `public/algorithm_visible_at_0800.json` 指向的五类信息：71 个预登记位置、匿名订单属性分布、40 个已揭示订单、P10 触发协议、以及用算法自己的 seed 3 生成的内部情景。

算法看不到：真实未来 10 单的位置与属性映射、真实出现时刻、真实触发批次、市场抽样 seed、真实事件流 seed、私有真值文件路径和真值哈希。真值文件只给事件回放器与最终评价读取。

并存的新静态算例 50 客户表也不是本动态日的真值全集：它只提供匿名订单属性分布和双班次结构，动态日的 50 个位置重新从 71 点潜在池抽取。因此，即使仓库里保留静态算例，也不能拿“静态 50 客户表减去当前可见客户表”得到动态未来。

为什么不能用“全集减可见集”反推：08:00 时，71 个候选位置减去 40 个已揭示位置，还剩 **{isolation['unrevealed_candidate_position_count_at_0800']}** 个；真实未来只有 **{isolation['true_future_order_count_at_0800']}** 个，其余 **{isolation['subtraction_attack_false_positive_count_at_0800']}** 个当天不下单。减法得到的是 31 个候选，不是 10 个真实未来。

真实未来与算法情景分别由两个 SHA-256 派生、彼此独立的随机数对象生成。算法情景生成器只接收公开潜在池、公开属性分布、40 个已揭示订单和算法情景 seed；代码路径不接收真实 seed 或真实未来名单。因此，即使本次两个样例有随机重合，也不能据此重建真值。

## 4. 可服务性体检

对每个真实动态订单都复算两次：

1. 出现时刻从可用场站直接出车，到达后必要时等到时间窗开启，是否仍不晚于截止时间；
2. 按真实 P10 批次触发后再直接出车，是否仍不晚于截止时间。

10/10 单两次都通过，最小“触发后直接到达/等待至可服务”余量为 **{service['minimum_trigger_service_slack_second'] / 60.0:.2f} 分钟**。每单需求也均低于两车型中较小的 1700 kg 载重。这个检查证明至少存在一条直接服务机会，不替代后续完整路线优化。

逐单结果：`{data_relative}/validation/dynamic_serviceability.csv`。

## 5. 交付文件

- `public/potential_pool.csv`：算法可见的 71 个真实 OSM 候选位置。
- `public/order_attribute_prior.csv`：算法可用的匿名需求、服务与时间窗先验。
- `public/initial_orders_at_0800.csv`：08:00 已揭示的 40 单。
- `public/algorithm_scenario_seed_3.csv`：与真值独立抽样的 10 单算法情景数据。
- `private/truth_orders.csv`、`private/true_dynamic_events.csv`：仅供事件回放和最终评价的真实日与真实动态流。
- `validation/dynamic_serviceability.csv`：10 个动态订单的逐单体检。
- `metadata.json`、`artifact_hashes.json`：种子、来源、隔离边界、统计与哈希。

## 6. 红线核对

三个受保护文件当前哈希如下；本生成器不导入它们，也不调用求解器：

| 文件 | SHA-256 |
|---|---|
{chr(10).join(protected_rows)}

静态目录 `{BASE_DATA}` 只读，未写入任何文件；全部新增动态数据写入 `{data_relative}`。
"""


def _summary(result: BuildResult) -> dict[str, Any]:
    service = result.metadata["serviceability"]
    return {
        "dataset_id": DATASET_ID,
        "potential_position_count": len(result.potential_pool),
        "actual_order_count": len(result.truth_orders),
        "initial_visible_order_count": len(result.initial_orders_public),
        "dynamic_order_count": len(result.dynamic_events),
        "algorithm_scenario_order_count": len(result.algorithm_scenario),
        "born_expired_count": service["born_expired_count"],
        "trigger_expired_count": service["trigger_expired_count"],
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = list(rows)
    if not materialized:
        raise ValueError(f"refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(materialized[0]))
        writer.writeheader()
        writer.writerows(materialized)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _source_entry(repo: Path, path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(repo)),
        "sha256": _sha256_path(path),
        "bytes": path.stat().st_size,
    }


def _sha256_path(path: Path) -> str:
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    if path.is_dir():
        digest = hashlib.sha256()
        for member in sorted(item for item in path.rglob("*") if item.is_file()):
            relative = str(member.relative_to(path)).encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            digest.update(bytes.fromhex(_sha256_path(member)))
        return digest.hexdigest()
    raise FileNotFoundError(path)


def _payload_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _independent_rng(seed: int, stream_name: str) -> random.Random:
    material = json.dumps(
        {
            "contract_id": CONTRACT_ID,
            "dataset_id": DATASET_ID,
            "seed": int(seed),
            "stream_name": stream_name,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(material).digest()
    return random.Random(int.from_bytes(digest[:16], "big"))


def _resolve(repo: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo / path


def _clock(second: float) -> str:
    rounded = int(round(float(second)))
    hour, remainder = divmod(rounded, 3600)
    minute, value = divmod(remainder, 60)
    return f"{hour:02d}:{minute:02d}:{value:02d}"


if __name__ == "__main__":
    raise SystemExit(main())
