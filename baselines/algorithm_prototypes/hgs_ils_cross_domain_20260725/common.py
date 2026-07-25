"""Shared immutable helpers for the HGS-ILS-XD G0 preflight."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724/full_gate"
)
FLEET_WITNESSES = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v1_20260723/witnesses"
)
REGISTRATION = HERE / "g0_preflight_registration_v1.json"
INPUT_MANIFEST = HERE / "g0_input_manifest_v1.json"
OUT = HERE / "g0_preflight_v1"
ILS_PYTHON = (
    REPO / "build/python_envs/pyvrp-ils-0.13.4/bin/python"
)
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}
LABELS = ("HGS-F", "HGS-E", "HGS-M", "MV-HGS-SP")
SEEDS = (1, 2, 3, 4, 5)


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
    temporary.write_bytes(canonical_bytes(payload))
    temporary.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def customer_sequence(
    route: Mapping[str, Any] | Any,
) -> tuple[str, ...]:
    if isinstance(route, Mapping):
        home = str(route["home_depot_id"])
        sequence = route["node_sequence"]
    else:
        home = str(route.home_depot_id)
        sequence = route.node_sequence
    return tuple(
        str(node)
        for node in sequence
        if str(node) != home and str(node).startswith("C")
    )


def canonical_route_signature(
    customers: Sequence[str],
) -> tuple[str, ...]:
    forward = tuple(str(item) for item in customers)
    reverse = tuple(reversed(forward))
    return min(forward, reverse)


def route_signatures(
    routes: Iterable[Mapping[str, Any] | Any],
    *,
    minimum_customers: int = 2,
) -> set[tuple[str, ...]]:
    signatures: set[tuple[str, ...]] = set()
    for route in routes:
        sequence = customer_sequence(route)
        if len(sequence) >= minimum_customers:
            signatures.add(canonical_route_signature(sequence))
    return signatures


def adjacency_signature(
    routes: Iterable[Mapping[str, Any] | Any],
) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for route in routes:
        sequence = customer_sequence(route)
        for left, right in pairwise(sequence):
            edges.add(tuple(sorted((left, right))))
    return edges


def native_solution_signature(solution: Any) -> tuple[Any, ...]:
    return tuple(
        sorted(
            (
                int(route.vehicle_type()),
                tuple(int(client) for client in route.visits()),
            )
            for route in solution.routes()
        )
    )


def solution_payload(solution: Any) -> dict[str, Any]:
    return {
        "routes": [
            {
                "vehicle_id": str(route.vehicle_id),
                "vehicle_type": str(route.vehicle_type),
                "home_depot_id": str(route.home_depot_id),
                "node_sequence": list(route.node_sequence),
            }
            for route in solution.routes
        ],
        "charging_actions": [
            {
                "vehicle_id": str(action.vehicle_id),
                "station_id": str(action.station_id),
                "energy_kwh": float(action.energy_kwh),
                "occupancy_minutes": float(action.occupancy_minutes),
                "charge_start_second": float(action.charge_start_second),
                "charge_day_offset": int(action.charge_day_offset),
                "start_energy_kwh": action.start_energy_kwh,
                "end_energy_kwh": action.end_energy_kwh,
                "charging_curve_id": action.charging_curve_id,
            }
            for action in solution.charging_actions
        ],
        "cross_site_services": [
            {
                "customer_id": str(item.customer_id),
                "served_by_depot_id": str(item.served_by_depot_id),
            }
            for item in solution.cross_site_services
        ],
    }


def load_route_skeleton(payload: Mapping[str, Any]) -> Any:
    from setp_solver.solution import Route, Solution

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
        ]
    )


def load_complete_solution(payload: Mapping[str, Any]) -> Any:
    from setp_solver.solution import (
        CrossSiteService,
        Route,
        Solution,
        charging_action_from_dict,
    )

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


def task_id(instance_id: str, start_kind: str) -> str:
    return f"HGS-ILS-XD-G0__{instance_id}__{start_kind}"


def source_paths() -> tuple[Path, ...]:
    return (
        REGISTRATION,
        INPUT_MANIFEST,
        HERE / "common.py",
        HERE / "g0_worker.py",
        HERE / "run_g0.py",
        PROTOTYPE / "pyvrp_adapter.py",
        REPO / "solver/src/setp_solver/china81.py",
        REPO / "solver/src/setp_solver/china81_completion.py",
        REPO / "solver/src/setp_solver/prices.py",
        REPO / "solver/src/setp_solver/charging_curve.py",
        REPO / "solver/src/setp_solver/cost.py",
        REPO / "solver/src/setp_solver/check.py",
        CAMPAIGN / "raw_runs.csv",
    )


def source_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): file_sha256(path)
        for path in source_paths()
    }
