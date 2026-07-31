#!/usr/bin/env python3
"""Rebuild the finite China81 fleet authority under the new vehicle pair.

Identical rule to v1 (2026-07-23). The only reason this exists is the
D2-A additional condition registered 2026-07-27: R_d must be recomputed
under the new vehicle pair (EV 1700 kg / 77.28 kWh); the old authority
generated under the 1000 kg EV must not be reused.
MAIN_RESERVE_FACTOR, SENSITIVITY_FACTORS, DEPOT_CHARGER_COUNT and
DEPOT_CHARGE_POWER_KW are held at the v1 values on purpose: this is a
recompute, not a new scenario.

The builder performs no optimization. Customers are grouped by their frozen
home depot, sorted by (due, ready, id), and appended by deterministic
first-feasible packing to all-diesel routes. The resulting route count R_d is
the auditable fleet base. The approved main scenario keeps R_d diesel vehicles
and adds ceil(0.25 R_d) electric vehicles per depot.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "solver/src") not in sys.path:
    sys.path.insert(0, str(REPO / "solver/src"))

from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    annotate_cross_site_services,
    exact_china81_score,
)
from setp_solver.cost import route_node_schedule  # noqa: E402
from setp_solver.solution import Route, Solution  # noqa: E402


OUT = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v2_20260731"
)
STATIC = (
    "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723"
)
MATRICES = (
    "data/ChinaInstances/"
    "china81_local_directed_matrices_corrected_v10_20260723"
)
PARAMETERS = (
    "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v4_20260723"
)
APPROVAL = (
    REPO
    / "docs/handoff/model_change_approval_register_20260718.md"
)
APPROVAL_GATE = "`R_d` 必须在**新车型对**（EV 1700 kg / 77.28 kWh）下重算"
V1 = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v1_20260723"
)
MAIN_RESERVE_FACTOR = 1.25
SENSITIVITY_FACTORS = (1.10, 1.25, 1.50)
DEPOT_CHARGER_COUNT = 2
DEPOT_CHARGE_POWER_KW = 22.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _instance_ids() -> list[str]:
    catalog = REPO / STATIC / "instance_catalog.csv"
    with catalog.open(newline="", encoding="utf-8-sig") as handle:
        return sorted(row["instance_id"] for row in csv.DictReader(handle))


def _route_feasible(bundle: Any, depot_id: str, customers: list[str]) -> bool:
    route = Route(
        vehicle_id="FLEET-SIZING-CV",
        vehicle_type="cv",
        home_depot_id=depot_id,
        node_sequence=[depot_id, *customers, depot_id],
    )
    node_lookup = {
        node.node_id: node
        for node in bundle.instance.nodes
    }
    capacity = bundle.instance.payload_capacity_kg(
        "cv",
        fallback=float(bundle.prices.Q_capacity),
    )
    if sum(float(node_lookup[item].demand) for item in customers) > capacity:
        return False
    schedule = route_node_schedule(
        route,
        bundle.instance,
        bundle.prices,
    )
    return all(
        entry.t_start <= float(node_lookup[entry.node_id].due_time) + 1e-9
        for entry in schedule
    )


def _pack_depot(bundle: Any, depot_id: str) -> list[list[str]]:
    node_lookup = {
        node.node_id: node
        for node in bundle.instance.nodes
    }
    customers = sorted(
        (
            node
            for node in bundle.instance.nodes
            if node.node_type.lower() == "c"
            and bundle.customer_home_depot[node.node_id] == depot_id
        ),
        key=lambda node: (
            float(node.due_time),
            float(node.ready_time),
            node.node_id,
        ),
    )
    routes: list[list[str]] = []
    for customer in customers:
        placed = False
        for route_customers in routes:
            candidate = [*route_customers, customer.node_id]
            if _route_feasible(bundle, depot_id, candidate):
                route_customers.append(customer.node_id)
                placed = True
                break
        if placed:
            continue
        if not _route_feasible(bundle, depot_id, [customer.node_id]):
            raise RuntimeError(
                f"single-customer route is infeasible: "
                f"{bundle.instance_id}/{depot_id}/{customer.node_id}"
            )
        routes.append([customer.node_id])
    if sum(len(route) for route in routes) != len(customers):
        raise RuntimeError(
            f"fleet packing lost customers: {bundle.instance_id}/{depot_id}"
        )
    return routes


def build() -> dict[str, Any]:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite existing authority: {OUT}")
    if APPROVAL_GATE not in APPROVAL.read_text(encoding="utf-8"):
        raise RuntimeError("D2-A recompute requirement is missing")
    OUT.mkdir(parents=True)

    fleet_rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    witness_hashes: dict[str, str] = {}
    for instance_id in _instance_ids():
        bundle = load_china81_bundle(
            REPO,
            instance_id,
            static_input_authority=STATIC,
            road_matrix_authority=MATRICES,
            runtime_parameter_authority=PARAMETERS,
        )
        depots = sorted(
            node.node_id
            for node in bundle.instance.nodes
            if node.node_type.lower() == "d"
        )
        routes: list[Route] = []
        depot_details: dict[str, Any] = {}
        next_vehicle = 1
        for depot_id in depots:
            packed = _pack_depot(bundle, depot_id)
            base = len(packed)
            if base < 1:
                raise RuntimeError(
                    f"fleet base is empty: {instance_id}/{depot_id}"
                )
            main_ev = max(
                1,
                math.ceil((MAIN_RESERVE_FACTOR - 1.0) * base),
            )
            sensitivity = {
                f"{factor:.2f}": {
                    "num_cv": base,
                    "num_ev": max(1, math.ceil((factor - 1.0) * base)),
                }
                for factor in SENSITIVITY_FACTORS
            }
            depot_node = bundle.instance.nodes[
                bundle.instance.node_index[depot_id]
            ]
            fleet_rows.append(
                {
                    "instance_id": instance_id,
                    "depot_id": depot_id,
                    "city": depot_node.city,
                    "base_all_cv_routes_Rd": base,
                    "main_reserve_factor": f"{MAIN_RESERVE_FACTOR:.2f}",
                    "num_cv": base,
                    "num_ev": main_ev,
                    "total_fleet_cap": base + main_ev,
                    "depot_charger_count": DEPOT_CHARGER_COUNT,
                    "depot_charge_power_kw": f"{DEPOT_CHARGE_POWER_KW:.1f}",
                    "fleet_parameter_class": (
                        "CONSTRUCTED_DEMAND_TIME_WINDOW_ROAD_SCENARIO"
                    ),
                    "charger_parameter_class": (
                        "CONSTRUCTED_SCENARIO_NOT_OBSERVED_SITE_CONTRACT"
                    ),
                    "sensitivity_json": json.dumps(
                        sensitivity,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )
            depot_details[depot_id] = {
                "city": depot_node.city,
                "base_all_cv_routes_Rd": base,
                "main_num_cv": base,
                "main_num_ev": main_ev,
                "packed_customers": packed,
                "sensitivity": sensitivity,
            }
            for customer_ids in packed:
                routes.append(
                    Route(
                        vehicle_id=f"FLEET-CV-{next_vehicle:04d}",
                        vehicle_type="cv",
                        home_depot_id=depot_id,
                        node_sequence=[
                            depot_id,
                            *customer_ids,
                            depot_id,
                        ],
                    )
                )
                next_vehicle += 1
        witness = annotate_cross_site_services(
            Solution(routes=routes),
            bundle.customer_home_depot,
        )
        objective, metrics, violations = exact_china81_score(witness, bundle)
        if violations:
            raise RuntimeError(
                f"finite-fleet witness is infeasible: "
                f"{instance_id}:{len(violations)}"
            )
        if witness.cross_site_services:
            raise RuntimeError(
                f"finite-fleet witness crosses depots: {instance_id}"
            )
        witness_path = OUT / "witnesses" / f"{instance_id}.json"
        write_json(
            witness_path,
            {
                "schema": "resetp.china81-finite-fleet-witness.v2",
                "instance_id": instance_id,
                "construction_rule": (
                    "home-depot EDF deterministic first-feasible all-CV packing"
                ),
                "depot_details": depot_details,
                "routes": [
                    {
                        "vehicle_id": route.vehicle_id,
                        "vehicle_type": route.vehicle_type,
                        "home_depot_id": route.home_depot_id,
                        "node_sequence": route.node_sequence,
                    }
                    for route in witness.routes
                ],
                "objective_for_integrity_only": objective,
                "metrics_for_integrity_only": metrics,
                "violation_count": 0,
                "cross_site_service_count": 0,
                "formal_search_allowed": False,
                "search_evaluations": 0,
            },
        )
        witness_hashes[instance_id] = sha256(witness_path)
        raw_rows.append(
            {
                "instance_id": instance_id,
                "depot_count": len(depots),
                "route_count": len(routes),
                "customer_count": sum(
                    node.node_type.lower() == "c"
                    for node in bundle.instance.nodes
                ),
                "violation_count": 0,
                "cross_site_service_count": 0,
                "witness_sha256": witness_hashes[instance_id],
                "status": "PASS",
                "search_evaluations": 0,
            }
        )

    if len(raw_rows) != 81 or len(fleet_rows) < 81:
        raise RuntimeError("finite fleet authority does not cover all 81 instances")
    write_csv(OUT / "fleet_caps.csv", fleet_rows)
    write_csv(OUT / "raw_runs.csv", raw_rows)
    write_json(OUT / "witness_hashes.json", witness_hashes)
    decision = {
        "schema": "resetp.china81-finite-fleet-authority.v2",
        "verdict": "PASS_FINITE_FLEET_ZERO_SEARCH_WITNESSES",
        "approval_id": "D2-A-RECOMPUTE-NEW-VEHICLE-PAIR-20260727",
        "instances_passed": len(raw_rows),
        "fleet_rows": len(fleet_rows),
        "main_reserve_factor": MAIN_RESERVE_FACTOR,
        "sensitivity_factors": list(SENSITIVITY_FACTORS),
        "depot_charger_count": DEPOT_CHARGER_COUNT,
        "depot_charge_power_kw": DEPOT_CHARGE_POWER_KW,
        "charger_parameter_class": (
            "CONSTRUCTED_SCENARIO_NOT_OBSERVED_SITE_CONTRACT"
        ),
        "formal_search_allowed": False,
        "search_evaluations": 0,
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.china81-finite-fleet-authority.metadata.v2",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "builder": str(Path(__file__).relative_to(REPO)),
            "approval_sha256": sha256(APPROVAL),
            "static_authority": STATIC,
            "matrix_authority": MATRICES,
            "runtime_parameter_authority": PARAMETERS,
            "formal_search_allowed": False,
            "search_evaluations": 0,
        },
    )
    (OUT / "report.md").write_text(
        "# China81 有限车队与车场充电构造情景\n\n"
        "81 个实例均由所属车场内的确定性最晚时限优先、首次可行装箱形成"
        "全燃油零搜索 witness，完整模型复算均为 0 违约、0 跨场服务。主情景"
        "保留每场 R_d 辆燃油车，并增加 ceil(0.25 R_d) 辆电动车；车队和"
        "2 x 22 kW 车场充电设施均为构造情景，不是园区实测资产。\n",
        encoding="utf-8",
    )
    artifacts: dict[str, str] = {}
    for path in sorted(OUT.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        ):
            artifacts[str(path.relative_to(OUT))] = sha256(path)
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
                "*.tmp",
            ],
            "artifacts": artifacts,
        },
    )
    return decision


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, sort_keys=True))
