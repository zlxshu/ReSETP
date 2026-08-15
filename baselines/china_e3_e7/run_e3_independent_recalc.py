#!/usr/bin/env python3
"""Independently replay sealed formal E3 witnesses before aggregation.

The script performs no search. It reloads every solution witness, rebuilds
the corrected China81 bundle, checks feasibility, recomputes cost and
emissions, reconstructs the city/date/half-hour settlement trace, verifies
the task manifests, and only then releases the paired statistics adapter.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for path in (REPO, REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from baselines.china_e3_e7.statistics import (  # noqa: E402
    aggregate_raw,
)
from baselines.china_e3_e7.release_v6_config import (  # noqa: E402
    E3_AGGREGATE as DEFAULT_OUT,
    E3_FORMAL as DEFAULT_FORMAL,
    E3_EXPECTED_TASKS as EXPECTED_TASKS,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    exact_china81_score,
)
from setp_solver.cost import (  # noqa: E402
    carbon_profile_row_for_slot,
    charging_action_slot_breakdown,
    diesel_price_for_route,
    evaluate,
    route_departure_second,
    time_profile_rows_for_node,
)
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
    physical_vehicle_id,
)

def require_depot_fleet_caps(
    solution: Solution,
    bundle: Any,
) -> None:
    used: dict[tuple[str, str], set[str]] = {}
    for route in solution.routes:
        depot_id = str(route.home_depot_id)
        vehicle_type = str(route.vehicle_type).strip().lower()
        if (
            depot_id not in bundle.fleet_caps_by_depot
            or vehicle_type not in {"cv", "ev"}
        ):
            raise RuntimeError("independent fleet identity is unknown")
        used.setdefault((depot_id, vehicle_type), set()).add(
            physical_vehicle_id(route.vehicle_id)
        )
    for (depot_id, vehicle_type), physical_ids in used.items():
        cap = int(
            bundle.fleet_caps_by_depot[depot_id][
                f"num_{vehicle_type}"
            ]
        )
        if len(physical_ids) > cap:
            raise RuntimeError(
                "independent depot fleet cap exceeded:"
                f"{depot_id}:{vehicle_type}"
            )


def canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def payload_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty replay ledger")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def load_solution(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=[
                    str(item) for item in row["node_sequence"]
                ],
            )
            for row in payload["routes"]
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id=str(row["vehicle_id"]),
                station_id=str(row["station_id"]),
                energy_kwh=float(row["energy_kwh"]),
                occupancy_minutes=float(row["occupancy_minutes"]),
                charge_start_second=float(
                    row["charge_start_second"]
                ),
                charge_day_offset=int(
                    row.get("charge_day_offset", 0)
                ),
                start_energy_kwh=(
                    None
                    if row.get("start_energy_kwh") is None
                    else float(row["start_energy_kwh"])
                ),
                end_energy_kwh=(
                    None
                    if row.get("end_energy_kwh") is None
                    else float(row["end_energy_kwh"])
                ),
                charging_curve_id=row.get("charging_curve_id"),
            )
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                customer_id=str(row["customer_id"]),
                served_by_depot_id=str(
                    row["served_by_depot_id"]
                ),
            )
            for row in payload.get("cross_site_services", [])
        ],
    )


def bundle_input_file_manifest(bundle: Any) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for label, relative in sorted(bundle.source_paths.items()):
        path = REPO / relative
        if path.is_file():
            manifest[f"{label}:{relative}"] = file_sha256(path)
            continue
        if not path.is_dir():
            raise RuntimeError(
                f"bundle source path is missing: {label}={relative}"
            )
        files = [
            item
            for item in sorted(path.rglob("*"))
            if (
                item.is_file()
                and not item.name.startswith("._")
                and "__pycache__" not in item.parts
            )
        ]
        if not files:
            raise RuntimeError(
                f"bundle source directory is empty: {label}={relative}"
            )
        for item in files:
            manifest[
                f"{label}:{item.relative_to(REPO)}"
            ] = file_sha256(item)
    return manifest


def independent_settlement_trace(
    solution: Solution,
    bundle: Any,
) -> dict[str, Any]:
    diesel_rows = []
    for route in solution.routes:
        if route.vehicle_type.lower() != "cv":
            continue
        depot = bundle.instance.nodes[
            bundle.instance.node_index[route.home_depot_id]
        ]
        city = str(depot.city).strip().lower()
        diesel_rows.append(
            {
                "vehicle_id": route.vehicle_id,
                "route_origin_depot": route.home_depot_id,
                "city": city,
                "diesel_zone": bundle.diesel_zone_by_city[city],
                "scenario_date": bundle.date,
                "diesel_price_cny_per_l": diesel_price_for_route(
                    route,
                    bundle.instance,
                    bundle.prices,
                ),
            }
        )
    charging_rows = []
    for action in solution.charging_actions:
        node = bundle.instance.nodes[
            bundle.instance.node_index[action.station_id]
        ]
        city = str(node.city).strip().lower()
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
            row = carbon_profile_row_for_slot(
                profile,
                slot.slot_index,
            )
            expected = {
                "date": bundle.date,
                "price_area_id": (
                    bundle.price_area_by_city[city]
                ),
                "carbon_source_column": (
                    bundle.carbon_source_column_by_city[city]
                ),
                "diesel_zone": bundle.diesel_zone_by_city[city],
                "joint_key_status": (
                    "PASS_CITY_DATE_SLOT_PARAMETER_IDENTITY"
                ),
            }
            observed = {key: row[key] for key in expected}
            if observed != expected:
                raise RuntimeError(
                    "independent settlement joint key failed closed: "
                    f"{action.station_id}:{observed}"
                )
            charging_rows.append(
                {
                    "vehicle_id": action.vehicle_id,
                    "station_id": action.station_id,
                    "node_type": node.node_type,
                    "city": city,
                    "price_area_id": row["price_area_id"],
                    "carbon_source_column": (
                        row["carbon_source_column"]
                    ),
                    "diesel_zone": row["diesel_zone"],
                    "scenario_date": row["date"],
                    "hourly_calendar_row": int(
                        row["hourly_calendar_row"]
                    ),
                    "energy_kwh": float(slot.y_skt_kwh),
                    "electricity_price_field": price_field,
                    "electricity_price_cny_per_kwh": float(
                        row[price_field]
                    ),
                    "carbon_factor_kgco2e_per_kwh": (
                        float(row["actual_gco2_per_kwh"])
                        / 1000.0
                    ),
                }
            )
    return {
        "schema": "resetp.china81-task-settlement-trace.v1",
        "joint_key_policy": "FAIL_CLOSED_NO_CITY_GROUP_FALLBACK",
        "scenario_date": bundle.date,
        "diesel_routes": diesel_rows,
        "charging_slot_segments": charging_rows,
    }


def verify_task_artifacts(task_dir: Path) -> None:
    manifest = json.loads(
        (task_dir / "artifact_hashes.json").read_text(
            encoding="utf-8"
        )
    )
    for name, expected in manifest["artifacts"].items():
        path = task_dir / name
        if not path.is_file() or file_sha256(path) != expected:
            raise RuntimeError(
                f"formal task artifact drift: {task_dir.name}/{name}"
            )


def main(formal_root: Path, out_dir: Path) -> dict[str, Any]:
    decision = json.loads(
        (formal_root / "decision.json").read_text(encoding="utf-8")
    )
    if (
        decision.get("verdict")
        != "PASS_E3_FORMAL_RAW_COMPLETE"
    ):
        raise RuntimeError("formal E3 raw campaign is not PASS")
    raw_path = formal_root / "raw_runs.csv"
    with raw_path.open(
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != EXPECTED_TASKS:
        raise RuntimeError(
            f"expected {EXPECTED_TASKS} formal rows, found {len(rows)}"
        )
    if len({row["task_id"] for row in rows}) != EXPECTED_TASKS:
        raise RuntimeError("formal E3 raw task ids are not unique")

    bundle_cache: dict[str, Any] = {}
    manifest_cache: dict[str, str] = {}
    replay_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        task_dir = formal_root / "tasks" / row["task_id"]
        verify_task_artifacts(task_dir)
        if file_sha256(task_dir / "certificate.json") != row[
            "certificate_sha256"
        ]:
            raise RuntimeError(
                f"certificate hash mismatch: {row['task_id']}"
            )
        payload = json.loads(
            (task_dir / "solution_witness.json").read_text(
                encoding="utf-8"
            )
        )
        if payload_sha256(payload) != row["solution_sha256"]:
            raise RuntimeError(
                f"solution hash mismatch: {row['task_id']}"
            )
        instance_id = row["instance_id"]
        bundle = bundle_cache.get(instance_id)
        if bundle is None:
            bundle = load_china81_bundle(REPO, instance_id)
            bundle_cache[instance_id] = bundle
            manifest_cache[instance_id] = payload_sha256(
                bundle_input_file_manifest(bundle)
            )
        if (
            manifest_cache[instance_id]
            != row["input_manifest_sha256"]
        ):
            raise RuntimeError(
                f"input byte manifest mismatch: {row['task_id']}"
            )
        solution = load_solution(payload)
        require_depot_fleet_caps(solution, bundle)
        routes = {
            route.vehicle_id: route
            for route in solution.routes
        }
        for action in solution.charging_actions:
            start = float(action.charge_start_second)
            end = start + float(action.occupancy_minutes) * 60.0
            if (
                int(action.charge_day_offset) != 0
                or not 0.0 <= start < 86_400.0
                or end > 86_400.0 + 1.0e-9
            ):
                raise RuntimeError(
                    "formal E3 witness leaves registered scenario date: "
                    f"{row['task_id']}"
                )
            node = bundle.instance.nodes[
                bundle.instance.node_index[action.station_id]
            ]
            if node.node_type.lower() == "d":
                departure = route_departure_second(
                    routes[action.vehicle_id],
                    bundle.instance,
                    bundle.prices,
                )
                if end > departure + 1.0e-9:
                    raise RuntimeError(
                        "formal E3 witness borrows depot energy after "
                        f"departure: {row['task_id']}"
                    )
        if (
            row.get("all_charge_day_offsets_zero", "").lower()
            != "true"
            or row.get(
                "all_charging_within_registered_day",
                "",
            ).lower()
            != "true"
            or row.get(
                "all_depot_charging_finishes_before_departure",
                "",
            ).lower()
            != "true"
            or row.get(
                "all_depot_fleet_caps_respected",
                "",
            ).lower()
            != "true"
        ):
            raise RuntimeError(
                f"formal date-boundary flag missing: {row['task_id']}"
            )
        violations = check_solution(
            solution,
            bundle.instance,
            bundle.prices,
        )
        objective, breakdown, exact_violations = exact_china81_score(
            solution,
            bundle,
        )
        direct = evaluate(
            solution,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
        )
        if violations or exact_violations:
            raise RuntimeError(
                f"independent feasibility failure: {row['task_id']}"
            )
        recorded_cost = float(row["total_cost"])
        recorded_emissions = float(row["total_emissions"])
        if not (
            math.isclose(
                objective,
                recorded_cost,
                rel_tol=0.0,
                abs_tol=1.0e-9,
            )
            and math.isclose(
                float(direct["total_cost"]),
                recorded_cost,
                rel_tol=0.0,
                abs_tol=1.0e-9,
            )
            and math.isclose(
                float(breakdown["E_total"]),
                recorded_emissions,
                rel_tol=0.0,
                abs_tol=1.0e-9,
            )
        ):
            raise RuntimeError(
                f"independent metric mismatch: {row['task_id']}"
            )
        independent_payload = {
            "objective": float(direct["total_cost"]),
            "breakdown": direct,
            "violation_count": len(violations),
        }
        if (
            payload_sha256(independent_payload)
            != row["independent_recompute_sha256"]
        ):
            raise RuntimeError(
                "original independent payload differs: "
                f"{row['task_id']}"
            )
        trace = independent_settlement_trace(solution, bundle)
        if (
            payload_sha256(trace)
            != row["settlement_trace_sha256"]
        ):
            raise RuntimeError(
                f"settlement trace mismatch: {row['task_id']}"
            )
        replay_rows.append(
            {
                "task_id": row["task_id"],
                "pair_id": row["pair_id"],
                "instance_id": instance_id,
                "seed": row["seed"],
                "arm": row["arm"],
                "input_manifest_sha256": (
                    manifest_cache[instance_id]
                ),
                "recorded_cost": recorded_cost,
                "recomputed_cost": float(
                    direct["total_cost"]
                ),
                "recorded_emissions": recorded_emissions,
                "recomputed_emissions": float(
                    breakdown["E_total"]
                ),
                "violation_count": 0,
                "settlement_trace_sha256": payload_sha256(trace),
                "all_charge_day_offsets_zero": True,
                "all_charging_within_registered_day": True,
                "all_depot_charging_finishes_before_departure": True,
                "all_depot_fleet_caps_respected": True,
                "status": "PASS",
            }
        )
        if index % 50 == 0:
            print(
                f"[E3-RECALC] {index}/{EXPECTED_TASKS}",
                flush=True,
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    replay_path = out_dir / "independent_recalc_rows.csv"
    write_csv(replay_path, replay_rows)
    experiment_ids = {
        row["experiment_id"] for row in rows
    }
    if experiment_ids != {"CHINA-E3-FORMAL-RELEASE-001"}:
        raise RuntimeError(
            f"mixed E3 experiment ids: {sorted(experiment_ids)}"
        )
    certificate = {
        "schema": "resetp.china-e3-independent-recalc.v1",
        "status": "PASS_INDEPENDENT_RECALC",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "contract_id": "CHINA-E3-FORMAL-RELEASE-001",
        "raw_runs_sha256": file_sha256(raw_path),
        "formal_decision_sha256": file_sha256(
            formal_root / "decision.json"
        ),
        "task_count": len(replay_rows),
        "pair_count": len(
            {row["pair_id"] for row in replay_rows}
        ),
        "feasible_count": len(replay_rows),
        "cost_tolerance_abs": 1.0e-9,
        "emissions_tolerance_abs": 1.0e-9,
        "joint_key_policy": (
            "FAIL_CLOSED_NO_CITY_GROUP_FALLBACK"
        ),
        "scenario_date": "2025-02-12",
        "all_charge_day_offsets_zero": True,
        "all_charging_within_registered_day": True,
        "all_depot_charging_finishes_before_departure": True,
        "all_depot_fleet_caps_respected": True,
        "search_evaluations": 0,
        "replay_rows_sha256": file_sha256(replay_path),
    }
    write_json(
        out_dir / "independent_recalc_certificate.json",
        certificate,
    )
    aggregate_decision = aggregate_raw(
        raw_path,
        out_dir,
        repo_root=REPO,
    )
    if (
        aggregate_decision["status"]
        != "AGGREGATE_READY_FOR_REVIEW"
        or aggregate_decision[
            "independent_recalc_complete"
        ]
        is not True
    ):
        raise RuntimeError(
            "paired aggregation did not pass after independent replay"
        )
    manifest = {
        str(path.relative_to(out_dir)): file_sha256(path)
        for path in sorted(out_dir.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
        )
    }
    write_json(
        out_dir / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
                "*.tmp",
            ],
            "artifacts": manifest,
        },
    )
    write_json(
        out_dir / "done.json",
        {
            "schema": "resetp.china-e3-independent-recalc.done.v1",
            "status": "PASS_E3_INDEPENDENT_RECALC_AND_AGGREGATION",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "formal_raw_runs_sha256": file_sha256(raw_path),
            "independent_recalc_certificate_sha256": file_sha256(
                out_dir / "independent_recalc_certificate.json"
            ),
            "aggregate_decision_sha256": file_sha256(
                out_dir / "decision.json"
            ),
            "artifact_hashes_sha256": file_sha256(
                out_dir / "artifact_hashes.json"
            ),
            "task_count": len(replay_rows),
            "pair_count": len(
                {row["pair_id"] for row in replay_rows}
            ),
            "search_evaluations": 0,
        },
    )
    return aggregate_decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--formal-root",
        type=Path,
        default=DEFAULT_FORMAL,
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT,
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    result = main(
        arguments.formal_root.resolve(),
        arguments.out_dir.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
