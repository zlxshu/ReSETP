#!/usr/bin/env python3
"""Run the approved E3/E6 pre-formal gates without formal search.

Gate 1 rebuilds the finite-fleet authority under the current vehicle pair.
Gate 2 replays the four-layer home-depot semantics on the current sources.
Gate 3 is started only if both earlier gates pass.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path = [
    entry
    for entry in sys.path
    if Path(entry or ".").resolve() != SCRIPT_DIR
]
for path in (PROTOTYPE, REPO / "solver/src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from pyvrp.solve import SolveParams  # noqa: E402

from baselines.china_instances.build_china81_finite_fleet_authority_v1_20260723 import (  # noqa: E402
    _pack_depot,
)
from epochal_hgs import HgsExactEpoch  # noqa: E402
from pyvrp_adapter import build_pyvrp_problem  # noqa: E402
from route_pool_sp import _route_pool_records, _solve_set_partitioning  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    China81CompletionResult,
    annotate_cross_site_services,
    exact_china81_score,
)
from setp_solver.solution import Route, Solution  # noqa: E402


TASK_ID = "E3E6-GATES-01"
OUT = (
    REPO
    / "baselines/china_e3_e7/"
    "e3e6_gates_01_20260729"
)
STATIC = (
    REPO
    / "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723"
)
MATRICES = (
    REPO
    / "data/ChinaInstances/"
    "china81_local_directed_matrices_corrected_v10_20260723"
)
PARAMETERS = (
    REPO
    / "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v4_20260723"
)
OLD_FLEET = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v1_20260723"
)
APPROVAL = (
    REPO
    / "docs/handoff/"
    "model_change_approval_register_20260718.md"
)
PREFLIGHT = (
    REPO
    / "baselines/china_e3_e7/"
    "e3e6_binding_preflight_01_20260727/report.md"
)
CURRENT_BUILDER = Path(__file__).resolve()
OLD_BUILDER = (
    REPO
    / "baselines/china_instances/"
    "build_china81_finite_fleet_authority_v1_20260723.py"
)
PYVRP_ADAPTER = PROTOTYPE / "pyvrp_adapter.py"
EPOCHAL_HGS = PROTOTYPE / "epochal_hgs.py"
ROUTE_POOL_SP = PROTOTYPE / "route_pool_sp.py"
FORMAL_E3_RUNNER = REPO / "baselines/china_e3_e7/formal_e3_runner.py"
RELEASE_CONFIG = REPO / "baselines/china_e3_e7/release_v6_config.py"
CHINA81 = REPO / "solver/src/setp_solver/china81.py"
CHINA81_COMPLETION = (
    REPO / "solver/src/setp_solver/china81_completion.py"
)
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
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
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    fieldnames: list[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows and not fieldnames:
        raise ValueError(f"empty CSV requires fieldnames: {path}")
    names = fieldnames or list(rows[0])
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def git_text(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(REPO))


def artifact_manifest(root: Path) -> dict[str, Any]:
    artifacts: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
            and ".pytest_cache" not in path.parts
            and not path.name.endswith(".tmp")
        ):
            artifacts[str(path.relative_to(root))] = sha256(path)
    return {
        "schema": "resetp.artifact-hashes.v1",
        "exclusions": [
            "artifact_hashes.json",
            "._*",
            "__pycache__",
            ".pytest_cache",
            "*.tmp",
        ],
        "artifacts": artifacts,
    }


def write_artifact_manifest(root: Path) -> None:
    write_json(root / "artifact_hashes.json", artifact_manifest(root))


def instance_ids() -> list[str]:
    return sorted(
        row["instance_id"]
        for row in read_csv(STATIC / "instance_catalog.csv")
    )


def source_hashes(paths: tuple[Path, ...]) -> dict[str, str]:
    return {relative(path): sha256(path) for path in paths}


def vehicle_pair(bundle: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    assert bundle.instance.vehicle_parameters is not None
    for vehicle_type in ("cv", "ev"):
        params = bundle.instance.vehicle_parameters[vehicle_type]
        result[vehicle_type] = {
            "vehicle_type_id": params.vehicle_type_id,
            "payload_capacity_kg": float(params.payload_capacity_kg),
            "curb_mass_kg": float(params.curb_mass_kg),
            "gross_mass_kg": float(params.gross_mass_kg),
            "battery_kwh": (
                None
                if params.battery_kwh is None
                else float(params.battery_kwh)
            ),
        }
    return result


def require_approved_vehicle_pair(pair: dict[str, dict[str, Any]]) -> None:
    cv = pair["cv"]
    ev = pair["ev"]
    expected = {
        "cv": {
            "vehicle_type_id": "JAC-WL-K7-G12J8-G12K8-box",
            "payload_capacity_kg": 1735.0,
            "curb_mass_kg": 2565.0,
        },
        "ev": {
            "vehicle_type_id": "FOTON-AUMARK-ES1-EXPRESS-STAKE",
            "payload_capacity_kg": 1700.0,
            "curb_mass_kg": 2600.0,
            "battery_kwh": 77.28,
        },
    }
    for kind, fields in expected.items():
        for field, value in fields.items():
            actual = pair[kind][field]
            if actual != value:
                raise RuntimeError(
                    "HALT_D2A_VEHICLE_PAIR_MISMATCH:"
                    f"{kind}.{field}={actual!r},expected={value!r}"
                )


def solution_from_witness(path: Path) -> Solution:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Solution(
        routes=[
            Route(
                vehicle_id=row["vehicle_id"],
                vehicle_type=row["vehicle_type"],
                home_depot_id=row["home_depot_id"],
                node_sequence=list(row["node_sequence"]),
            )
            for row in payload["routes"]
        ]
    )


def gate1_d2a(stage: Path) -> dict[str, Any]:
    gate = stage / "gate1_d2a"
    gate.mkdir(parents=True)
    ids = instance_ids()
    old_rows = read_csv(OLD_FLEET / "fleet_caps.csv")
    old_by_key = {
        (row["instance_id"], row["depot_id"]): row
        for row in old_rows
    }
    packed_by_instance: dict[str, dict[str, list[list[str]]]] = {}
    fleet_rows: list[dict[str, Any]] = []
    pair: dict[str, dict[str, Any]] | None = None

    for instance_id in ids:
        bundle = load_china81_bundle(
            REPO,
            instance_id,
            static_input_authority=STATIC,
            road_matrix_authority=MATRICES,
            runtime_parameter_authority=PARAMETERS,
            fleet_authority=OLD_FLEET,
        )
        current_pair = vehicle_pair(bundle)
        require_approved_vehicle_pair(current_pair)
        if pair is None:
            pair = current_pair
        elif pair != current_pair:
            raise RuntimeError(
                f"HALT_D2A_VEHICLE_PAIR_VARIES:{instance_id}"
            )
        depots = sorted(
            node.node_id
            for node in bundle.instance.nodes
            if node.node_type.lower() == "d"
        )
        packed_by_instance[instance_id] = {}
        for depot_id in depots:
            packed = _pack_depot(bundle, depot_id)
            route_count = len(packed)
            if route_count < 1:
                raise RuntimeError(
                    f"HALT_D2A_EMPTY_RD:{instance_id}/{depot_id}"
                )
            packed_by_instance[instance_id][depot_id] = packed
            sensitivity = {
                f"{rho:.2f}": {
                    "num_cv": route_count,
                    "num_ev": max(
                        1,
                        math.ceil((rho - 1.0) * route_count),
                    ),
                }
                for rho in SENSITIVITY_FACTORS
            }
            main_ev = sensitivity["1.25"]["num_ev"]
            depot_node = bundle.instance.nodes[
                bundle.instance.node_index[depot_id]
            ]
            fleet_rows.append(
                {
                    "instance_id": instance_id,
                    "depot_id": depot_id,
                    "city": depot_node.city,
                    "base_all_cv_routes_Rd": route_count,
                    "main_reserve_factor": "1.25",
                    "num_cv": route_count,
                    "num_ev": main_ev,
                    "total_fleet_cap": route_count + main_ev,
                    "depot_charger_count": DEPOT_CHARGER_COUNT,
                    "depot_charge_power_kw": "22.0",
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

    if pair is None or len(ids) != 81:
        raise RuntimeError("HALT_D2A_INSTANCE_COVERAGE")
    write_csv(gate / "fleet_caps.csv", fleet_rows)

    raw_rows: list[dict[str, Any]] = []
    witness_hashes: dict[str, str] = {}
    for instance_id in ids:
        bundle = load_china81_bundle(
            REPO,
            instance_id,
            static_input_authority=STATIC,
            road_matrix_authority=MATRICES,
            runtime_parameter_authority=PARAMETERS,
            fleet_authority=gate,
        )
        require_approved_vehicle_pair(vehicle_pair(bundle))
        routes: list[Route] = []
        depot_details: dict[str, Any] = {}
        vehicle_index = 1
        for depot_id, packed in sorted(
            packed_by_instance[instance_id].items()
        ):
            route_count = len(packed)
            sensitivity = {
                f"{rho:.2f}": {
                    "num_cv": route_count,
                    "num_ev": max(
                        1,
                        math.ceil((rho - 1.0) * route_count),
                    ),
                }
                for rho in SENSITIVITY_FACTORS
            }
            depot_details[depot_id] = {
                "base_all_cv_routes_Rd": route_count,
                "main_num_cv": route_count,
                "main_num_ev": sensitivity["1.25"]["num_ev"],
                "packed_customers": packed,
                "sensitivity": sensitivity,
            }
            for customers in packed:
                routes.append(
                    Route(
                        vehicle_id=f"FLEET-CV-{vehicle_index:04d}",
                        vehicle_type="cv",
                        home_depot_id=depot_id,
                        node_sequence=[depot_id, *customers, depot_id],
                    )
                )
                vehicle_index += 1
        witness = annotate_cross_site_services(
            Solution(routes=routes),
            bundle.customer_home_depot,
        )
        objective, metrics, violations = exact_china81_score(
            witness,
            bundle,
        )
        if violations or witness.cross_site_services:
            raise RuntimeError(
                "HALT_D2A_WITNESS_REPLAY:"
                f"{instance_id}:violations={len(violations)}:"
                f"cross_site={len(witness.cross_site_services)}"
            )
        witness_path = gate / "witnesses" / f"{instance_id}.json"
        write_json(
            witness_path,
            {
                "schema": (
                    "resetp.china81-finite-fleet-witness.d2a.v1"
                ),
                "task_id": TASK_ID,
                "instance_id": instance_id,
                "construction_rule": (
                    "per-home-depot deterministic first-feasible packing "
                    "after sorting by (due_time,ready_time,customer_id)"
                ),
                "vehicle_pair": pair,
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
                "depot_count": len(
                    packed_by_instance[instance_id]
                ),
                "customer_count": sum(
                    node.node_type.lower() == "c"
                    for node in bundle.instance.nodes
                ),
                "route_count": len(routes),
                "violation_count": 0,
                "cross_site_service_count": 0,
                "witness_sha256": witness_hashes[instance_id],
                "status": "PASS",
                "search_evaluations": 0,
            }
        )

    comparison_rows: list[dict[str, Any]] = []
    new_keys: set[tuple[str, str]] = set()
    for row in fleet_rows:
        key = (str(row["instance_id"]), str(row["depot_id"]))
        new_keys.add(key)
        if key not in old_by_key:
            raise RuntimeError(f"HALT_D2A_OLD_KEY_MISSING:{key}")
        old = old_by_key[key]
        old_sensitivity = json.loads(old["sensitivity_json"])
        new_sensitivity = json.loads(str(row["sensitivity_json"]))
        comparison: dict[str, Any] = {
            "instance_id": key[0],
            "depot_id": key[1],
            "city": row["city"],
            "old_base_all_cv_routes_Rd": int(
                old["base_all_cv_routes_Rd"]
            ),
            "new_base_all_cv_routes_Rd": int(
                row["base_all_cv_routes_Rd"]
            ),
            "delta_Rd": (
                int(row["base_all_cv_routes_Rd"])
                - int(old["base_all_cv_routes_Rd"])
            ),
            "old_num_cv_rho_1_25": int(old["num_cv"]),
            "new_num_cv_rho_1_25": int(row["num_cv"]),
            "old_num_ev_rho_1_25": int(old["num_ev"]),
            "new_num_ev_rho_1_25": int(row["num_ev"]),
            "old_total_fleet_cap_rho_1_25": int(
                old["total_fleet_cap"]
            ),
            "new_total_fleet_cap_rho_1_25": int(
                row["total_fleet_cap"]
            ),
        }
        for rho in SENSITIVITY_FACTORS:
            label = f"{rho:.2f}"
            slug = label.replace(".", "_")
            comparison[f"old_num_cv_rho_{slug}"] = int(
                old_sensitivity[label]["num_cv"]
            )
            comparison[f"new_num_cv_rho_{slug}"] = int(
                new_sensitivity[label]["num_cv"]
            )
            comparison[f"old_num_ev_rho_{slug}"] = int(
                old_sensitivity[label]["num_ev"]
            )
            comparison[f"new_num_ev_rho_{slug}"] = int(
                new_sensitivity[label]["num_ev"]
            )
        comparison_rows.append(comparison)
    if new_keys != set(old_by_key):
        raise RuntimeError("HALT_D2A_OLD_NEW_KEY_SET_MISMATCH")

    write_csv(gate / "old_new_comparison.csv", comparison_rows)
    write_csv(gate / "raw_runs.csv", raw_rows)
    write_json(gate / "witness_hashes.json", witness_hashes)
    changed_rd = sum(int(row["delta_Rd"]) != 0 for row in comparison_rows)
    changed_main_caps = sum(
        (
            int(row["old_num_cv_rho_1_25"])
            != int(row["new_num_cv_rho_1_25"])
            or int(row["old_num_ev_rho_1_25"])
            != int(row["new_num_ev_rho_1_25"])
        )
        for row in comparison_rows
    )
    decision = {
        "schema": "resetp.e3e6-gates.d2a.decision.v1",
        "task_id": TASK_ID,
        "gate": "D2-A",
        "verdict": "PASS",
        "instances_passed": len(raw_rows),
        "fleet_rows": len(fleet_rows),
        "witnesses_passed": len(witness_hashes),
        "old_authority": relative(OLD_FLEET),
        "old_authority_overwritten": False,
        "changed_Rd_rows": changed_rd,
        "changed_main_cap_rows": changed_main_caps,
        "main_reserve_factor": MAIN_RESERVE_FACTOR,
        "sensitivity_factors": list(SENSITIVITY_FACTORS),
        "vehicle_pair": pair,
        "formal_search_allowed": False,
        "search_evaluations": 0,
    }
    write_json(gate / "decision.json", decision)
    write_json(
        gate / "metadata.json",
        {
            "schema": "resetp.e3e6-gates.d2a.metadata.v1",
            "task_id": TASK_ID,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "builder": relative(CURRENT_BUILDER),
            "static_authority": relative(STATIC),
            "matrix_authority": relative(MATRICES),
            "runtime_parameter_authority": relative(PARAMETERS),
            "old_fleet_authority": relative(OLD_FLEET),
            "source_hashes": source_hashes(
                (
                    CURRENT_BUILDER,
                    OLD_BUILDER,
                    CHINA81,
                    CHINA81_COMPLETION,
                    *PROTECTED,
                    APPROVAL,
                    PREFLIGHT,
                    OLD_FLEET / "fleet_caps.csv",
                )
            ),
            "worker_count": 1,
            "formal_search_allowed": False,
            "search_evaluations": 0,
        },
    )
    (gate / "report.md").write_text(
        "# 门一 D2-A：按当前车型重算车队规模\n\n"
        "**结论：PASS。** 81 个实例、"
        f"{len(fleet_rows)} 个实例-车场行均按 `(due_time, ready_time, "
        "customer_id)` 固定排序执行确定性首次可行装箱。每个实例均保存"
        "全燃油零搜索 witness，完整模型复算为 0 违约、0 跨场服务。\n\n"
        "当前车型绑定为：CV 威铃 K7，额定载质量 1735 kg、整备质量 "
        "2565 kg；EV 福田 ES1 快递版栏板，额定载质量 1700 kg、"
        "整备质量 2600 kg、电池 77.28 kWh。主情景为 "
        "`num_cv=R_d`、`num_ev=max(1,ceil(0.25 R_d))`；同时保存 "
        "rho=1.10、1.25、1.50 三档。\n\n"
        "逐实例逐车场的 `R_d` 与三档车队数见 `fleet_caps.csv`；"
        "相对旧只读权威的逐行对比见 `old_new_comparison.csv`。旧权威"
        "没有被覆盖。此次重算中 "
        f"`R_d` 变化行数为 {changed_rd}/{len(comparison_rows)}，"
        f"rho=1.25 主情景车队上限变化行数为 "
        f"{changed_main_caps}/{len(comparison_rows)}。这两个计数只是"
        "新旧输入闭合检查，不替代新的车型绑定与 witness 重放。\n",
        encoding="utf-8",
    )
    write_artifact_manifest(gate)
    return decision


def verify_control_encoding(bundle: Any, data: Any) -> None:
    depots = list(data.depots())
    depot_index = {
        depot.name: index for index, depot in enumerate(depots)
    }
    if data.num_load_dimensions != 1 + len(depots):
        raise RuntimeError("control arm lacks home-depot load dimensions")
    for client in data.clients():
        owner = bundle.customer_home_depot[client.name]
        dimensions = list(client.delivery[1:])
        if sum(dimensions) != 1:
            raise RuntimeError("control owner marker is not one-hot")
        if dimensions[depot_index[owner]] != 1:
            raise RuntimeError("control owner marker is wrong")
    for vehicle_type in data.vehicle_types():
        home = depots[vehicle_type.start_depot].name
        if vehicle_type.start_depot != vehicle_type.end_depot:
            raise RuntimeError(
                "control vehicle has different start/end depots"
            )
        for depot_id, index in depot_index.items():
            admitted = vehicle_type.capacity[1 + index] > 0
            if admitted != (depot_id == home):
                raise RuntimeError(
                    "control vehicle owner capacity is wrong"
                )


def source_guard_evidence() -> dict[str, Any]:
    epochal = EPOCHAL_HGS.read_text(encoding="utf-8")
    pool = ROUTE_POOL_SP.read_text(encoding="utf-8")
    final = FORMAL_E3_RUNNER.read_text(encoding="utf-8")
    complete_guard_tokens = (
        "problem.hard_home_depot_lock",
        "completion.solution.cross_site_services",
        "common_completion.solution.cross_site_services",
        "proxy_best_completion.solution.cross_site_services",
    )
    route_pool_tokens = (
        "if hard_home_depot_lock and any(",
        "if hard_home_depot_lock:",
        "bundle.customer_home_depot[customer_id]",
        "record.route.home_depot_id",
    )
    final_guard = (
        "if ARMS[arm_id] and solution.cross_site_services:"
    )
    evidence = {
        "complete_candidate_guard_tokens": {
            token: token in epochal for token in complete_guard_tokens
        },
        "complete_candidate_guard_pass": all(
            token in epochal for token in complete_guard_tokens
        ),
        "route_pool_guard_tokens": {
            token: token in pool for token in route_pool_tokens
        },
        "route_pool_guard_pass": all(
            token in pool for token in route_pool_tokens
        ),
        "final_certificate_guard_token": final_guard,
        "final_certificate_guard_pass": final_guard in final,
    }
    if not all(
        (
            evidence["complete_candidate_guard_pass"],
            evidence["route_pool_guard_pass"],
            evidence["final_certificate_guard_pass"],
        )
    ):
        raise RuntimeError(
            f"HALT_D3_CURRENT_SOURCE_GUARD_MISSING:{evidence}"
        )
    return evidence


def gate2_d3(stage: Path, gate1: dict[str, Any]) -> dict[str, Any]:
    gate = stage / "gate2_d3"
    gate.mkdir(parents=True)
    fleet = stage / "gate1_d2a"
    guard_evidence = source_guard_evidence()
    params = SolveParams()
    rows: list[dict[str, Any]] = []

    for instance_id in instance_ids():
        bundle = load_china81_bundle(
            REPO,
            instance_id,
            static_input_authority=STATIC,
            road_matrix_authority=MATRICES,
            runtime_parameter_authority=PARAMETERS,
            fleet_authority=fleet,
        )
        control = build_pyvrp_problem(
            bundle,
            hard_home_depot_lock=True,
        )
        treatment = build_pyvrp_problem(
            bundle,
            hard_home_depot_lock=False,
        )
        control_data = control.model.data()
        treatment_data = treatment.model.data()
        verify_control_encoding(bundle, control_data)
        if treatment_data.num_load_dimensions != 1:
            raise RuntimeError(
                f"HALT_D3_TREATMENT_RETAINED_LOCK:{instance_id}"
            )
        active_node_operators = [
            operator.__name__
            for operator in params.node_ops
            if operator.supports(treatment_data)
        ]
        if "Exchange11" not in active_node_operators:
            raise RuntimeError(
                f"HALT_D3_EXCHANGE11_INACTIVE:{instance_id}"
            )

        witness = annotate_cross_site_services(
            solution_from_witness(
                fleet / "witnesses" / f"{instance_id}.json"
            ),
            bundle.customer_home_depot,
        )
        _, _, violations = exact_china81_score(witness, bundle)
        if violations or witness.cross_site_services:
            raise RuntimeError(
                f"HALT_D3_CONTROL_WITNESS:{instance_id}"
            )

        depots = sorted(
            node.node_id
            for node in bundle.instance.nodes
            if node.node_type.lower() == "d"
        )
        treatment_constructible = len(depots) >= 2
        adversarial_cross_count = 0
        route_pool_control_records = 0
        route_pool_treatment_records = 0
        mip_filter_status = "NOT_APPLICABLE_SINGLE_DEPOT"
        if treatment_constructible:
            customer_id = sorted(bundle.customer_home_depot)[0]
            owner = bundle.customer_home_depot[customer_id]
            wrong_depot = next(
                depot_id for depot_id in depots if depot_id != owner
            )
            adversarial = annotate_cross_site_services(
                Solution(
                    routes=[
                        Route(
                            vehicle_id="D3-ADVERSARIAL-CV",
                            vehicle_type="cv",
                            home_depot_id=wrong_depot,
                            node_sequence=[
                                wrong_depot,
                                customer_id,
                                wrong_depot,
                            ],
                        )
                    ]
                ),
                bundle.customer_home_depot,
            )
            adversarial_cross_count = len(
                adversarial.cross_site_services
            )
            if adversarial_cross_count != 1:
                raise RuntimeError(
                    f"HALT_D3_ADVERSARIAL_ANNOTATION:{instance_id}"
                )
            completion = China81CompletionResult(
                solution=adversarial,
                objective=0.0,
                breakdown={},
                activity={"source": "zero_search_adversarial_probe"},
            )
            epoch = HgsExactEpoch(
                elite_skeletons=(),
                elite_completions=(completion,),
                proxy_best_completion=completion,
                elapsed_seconds=0.0,
                stats={},
                archive_completions=(completion,),
                base_archive_completions=(),
            )
            view_epochs = {"zero_search_probe": epoch}
            control_records = _route_pool_records(
                bundle,
                view_epochs,
                hard_home_depot_lock=True,
            )
            treatment_records = _route_pool_records(
                bundle,
                view_epochs,
                hard_home_depot_lock=False,
            )
            route_pool_control_records = len(control_records)
            route_pool_treatment_records = len(treatment_records)
            if route_pool_control_records != 0:
                raise RuntimeError(
                    f"HALT_D3_ROUTE_POOL_CONTROL_LEAK:{instance_id}"
                )
            if route_pool_treatment_records != 1:
                raise RuntimeError(
                    f"HALT_D3_ROUTE_POOL_TREATMENT_BLOCKED:{instance_id}"
                )
            mip_solution, mip_stats = _solve_set_partitioning(
                bundle,
                treatment_records,
                time_limit_seconds=0.01,
                hard_home_depot_lock=True,
            )
            if (
                mip_solution is not None
                or mip_stats["status_class"] != "NO_COLUMNS"
            ):
                raise RuntimeError(
                    f"HALT_D3_MIP_FILTER_LEAK:{instance_id}"
                )
            mip_filter_status = "PASS_REJECTED_TO_NO_COLUMNS"

        row_status = (
            "PASS"
            if treatment_constructible
            else "HALT_TREATMENT_CROSS_SITE_TOPOLOGICALLY_IMPOSSIBLE"
        )
        rows.append(
            {
                "instance_id": instance_id,
                "depot_count": len(depots),
                "control_load_dimensions": (
                    control_data.num_load_dimensions
                ),
                "treatment_load_dimensions": (
                    treatment_data.num_load_dimensions
                ),
                "search_space_hard_lock_pass": True,
                "control_full_model_violation_count": len(violations),
                "control_cross_site_service_count": len(
                    witness.cross_site_services
                ),
                "complete_candidate_guard_source_pass": (
                    guard_evidence[
                        "complete_candidate_guard_pass"
                    ]
                ),
                "route_pool_first_filter_control_record_count": (
                    route_pool_control_records
                ),
                "route_pool_open_treatment_record_count": (
                    route_pool_treatment_records
                ),
                "route_pool_mip_second_filter_status": mip_filter_status,
                "final_certificate_guard_source_pass": (
                    guard_evidence[
                        "final_certificate_guard_pass"
                    ]
                ),
                "treatment_lock_removed": True,
                "treatment_exchange11_active": True,
                "treatment_cross_site_constructible": (
                    treatment_constructible
                ),
                "adversarial_cross_site_service_count": (
                    adversarial_cross_count
                ),
                "topology_note": (
                    "MULTI_DEPOT_CROSS_SITE_CONSTRUCTIBLE"
                    if treatment_constructible
                    else "SINGLE_DEPOT_NO_DISTINCT_OTHER_DEPOT_EXISTS"
                ),
                "status": row_status,
                "search_evaluations": 0,
            }
        )

    strict_pass_count = sum(
        row["status"] == "PASS" for row in rows
    )
    single_depot_count = sum(
        int(row["depot_count"]) == 1 for row in rows
    )
    if strict_pass_count == len(rows):
        verdict = "PASS"
        formal_allowed = True
    else:
        verdict = (
            "HALT_TREATMENT_CROSS_SITE_NOT_CONSTRUCTIBLE_"
            f"FOR_{single_depot_count}_SINGLE_DEPOT_INSTANCES"
        )
        formal_allowed = False
    write_csv(gate / "raw_runs.csv", rows)
    decision = {
        "schema": "resetp.e3e6-gates.d3.decision.v1",
        "task_id": TASK_ID,
        "gate": "D3",
        "verdict": verdict,
        "strict_user_condition": (
            "for every one of 81 instances, control hard lock makes "
            "cross-site service impossible and treatment can produce it"
        ),
        "instances_total": len(rows),
        "instances_strict_pass": strict_pass_count,
        "instances_strict_halt": len(rows) - strict_pass_count,
        "single_depot_instances": single_depot_count,
        "multi_depot_instances": len(rows) - single_depot_count,
        "four_layer_guard_evidence": guard_evidence,
        "old_pass_reused": False,
        "current_source_replay": True,
        "formal_search_allowed": formal_allowed,
        "search_evaluations": 0,
    }
    write_json(gate / "decision.json", decision)
    write_json(
        gate / "metadata.json",
        {
            "schema": "resetp.e3e6-gates.d3.metadata.v1",
            "task_id": TASK_ID,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "builder": relative(CURRENT_BUILDER),
            "fleet_authority": (
                "baselines/china_e3_e7/"
                "e3e6_gates_01_20260729/gate1_d2a"
            ),
            "source_hashes": source_hashes(
                (
                    CURRENT_BUILDER,
                    PYVRP_ADAPTER,
                    EPOCHAL_HGS,
                    ROUTE_POOL_SP,
                    FORMAL_E3_RUNNER,
                    CHINA81,
                    CHINA81_COMPLETION,
                    *PROTECTED,
                )
            ),
            "pyvrp_version": version("pyvrp"),
            "worker_count": 1,
            "formal_search_allowed": formal_allowed,
            "search_evaluations": 0,
            "upstream_gate1_verdict": gate1["verdict"],
        },
    )
    halt_ids = [
        row["instance_id"]
        for row in rows
        if row["status"] != "PASS"
    ]
    (gate / "report.md").write_text(
        "# 门二 D3：当前源码零搜索重放\n\n"
        f"**结论：{verdict}。** 当前源码哈希已重新登记，未沿用 "
        "2026-07-24 的旧 PASS。搜索空间硬锁、完整候选守卫、路线池"
        "初筛与 MIP 二次过滤、最终证书守卫均在当前源码上闭合；新 D2-A "
        "witness 对 81 个实例的控制臂重放均为 0 违约、0 跨场。\n\n"
        "严格逐实例条件仍未通过：只有 "
        f"{strict_pass_count}/81 个多车场实例能够构造处理臂跨场服务；"
        f"其余 {single_depot_count}/81 个实例只有一个车场，不存在"
        "不同的服务车场，因此即使 `hard_home_depot_lock=False` 且 "
        "`Exchange11` 启用，跨车场服务仍在拓扑上不可能。不能把“删除"
        "锁维度/算子启用”的结构开放性改写为这 36 个实例上“可以产生"
        "跨车场服务”。\n\n"
        "36 个反例为：\n\n"
        + "\n".join(f"- `{instance_id}`" for instance_id in halt_ids)
        + "\n\n逐实例四层结果和反例字段见 `raw_runs.csv`，当前源码哈希见 "
        "`metadata.json`。\n",
        encoding="utf-8",
    )
    write_artifact_manifest(gate)
    return decision


def fixed_budget_precheck() -> dict[str, Any]:
    epochal = EPOCHAL_HGS.read_text(encoding="utf-8")
    pool = ROUTE_POOL_SP.read_text(encoding="utf-8")
    formal = FORMAL_E3_RUNNER.read_text(encoding="utf-8")
    release = RELEASE_CONFIG.read_text(encoding="utf-8")
    checks = {
        "epochal_imports_MaxIterations": (
            "from pyvrp.stop import MaxIterations" in epochal
            or (
                "from pyvrp.stop import MaxIterations, MaxRuntime, "
                "MultipleCriteria"
            )
            in epochal
        ),
        "epochal_does_not_import_NoImprovement": (
            "NoImprovement" not in epochal
        ),
        "route_pool_expected_budget_formula_present": (
            "len(modes) * (int(max_archive_candidates_per_view) + 2) + 2"
            in pool
        ),
        "formal_archive_candidates_24": (
            "ARCHIVE_CANDIDATES_PER_VIEW = 24" in formal
        ),
        "release_complete_candidate_budget_80": (
            "COMPLETE_CANDIDATE_BUDGET = 80" in release
        ),
        "formal_imports_release_complete_budget": (
            "COMPLETE_CANDIDATE_BUDGET as RELEASE_COMPLETE_BUDGET"
            in formal
            and "COMPLETE_CANDIDATE_BUDGET = RELEASE_COMPLETE_BUDGET"
            in formal
        ),
        "formal_fixed_iteration_argument_present": (
            "max_hgs_iterations_per_view=(" in formal
        ),
    }
    return {
        "verdict": (
            "PASS_FIXED_COMPLETE_CANDIDATE_BUDGET_SOURCE_PRECHECK"
            if all(checks.values())
            else "HALT_FIXED_BUDGET_SOURCE_PRECHECK"
        ),
        "checks": checks,
        "interpretation": (
            "Current E3/E6 path binds 80 complete candidate evaluations "
            "under MaxIterations plus a wallclock safety cap; it is not "
            "the NoImprovement convergence-stopping path."
        ),
    }


def gate3_not_run(stage: Path, upstream: dict[str, Any]) -> dict[str, Any]:
    gate = stage / "gate3_d4"
    gate.mkdir(parents=True)
    precheck = fixed_budget_precheck()
    decision = {
        "schema": "resetp.e3e6-gates.d4.decision.v1",
        "task_id": TASK_ID,
        "gate": "D4",
        "verdict": "NOT_RUN_UPSTREAM_GATE_2_HALT",
        "upstream_gate_2_verdict": upstream["verdict"],
        "fixed_budget_source_precheck": precheck,
        "pilot_started": False,
        "arm_costs_read_or_reported": False,
        "formal_search_allowed": False,
        "search_evaluations": 0,
    }
    write_csv(
        gate / "raw_runs.csv",
        [
            {
                "gate": "D4",
                "status": "NOT_RUN",
                "reason": "UPSTREAM_GATE_2_HALT",
                "pilot_started": False,
                "arm_costs_read_or_reported": False,
                "search_evaluations": 0,
            }
        ],
    )
    write_json(gate / "decision.json", decision)
    write_json(
        gate / "metadata.json",
        {
            "schema": "resetp.e3e6-gates.d4.metadata.v1",
            "task_id": TASK_ID,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_hashes": source_hashes(
                (
                    EPOCHAL_HGS,
                    ROUTE_POOL_SP,
                    FORMAL_E3_RUNNER,
                    RELEASE_CONFIG,
                    *PROTECTED,
                )
            ),
            "worker_count": 1,
            "pilot_started": False,
            "search_evaluations": 0,
        },
    )
    (gate / "report.md").write_text(
        "# 门三 D4：结果盲吞吐 pilot\n\n"
        "**结论：NOT RUN。** 门二已经 HALT，按“任一门失败立即停下”"
        "要求，没有启动任何 pilot，没有读取或报告任何臂间成本。\n\n"
        "只读源码预检确认当前 E3/E6 路径使用 `MaxIterations` 加墙钟安全"
        "上限，并由 24 个 archive candidates/视图闭合为固定 80 次完整"
        "候选评价；该路径没有使用 `NoImprovement` 收敛停机。因此用户"
        "给定的 `L/S` 判据在机制上适用于原计划 pilot，但因上游 HALT "
        "未实际计算 `L`、`S` 或选择档位。\n",
        encoding="utf-8",
    )
    write_artifact_manifest(gate)
    return decision


def build(stage: Path) -> dict[str, Any]:
    protected_before = source_hashes(PROTECTED)
    gate1 = gate1_d2a(stage)
    if gate1["verdict"] != "PASS":
        raise RuntimeError("gate 1 did not pass")
    gate2 = gate2_d3(stage, gate1)
    if gate2["verdict"] == "PASS":
        raise RuntimeError(
            "unexpected full D3 PASS; D4 pilot implementation is not "
            "reachable under the observed 36 single-depot instances"
        )
    gate3 = gate3_not_run(stage, gate2)
    protected_after = source_hashes(PROTECTED)
    if protected_before != protected_after:
        raise RuntimeError("HALT_PROTECTED_SOURCE_DRIFT_DURING_TASK")

    root_rows = [
        {
            "gate": "D2-A",
            "status": gate1["verdict"],
            "search_evaluations": 0,
            "reason": "CURRENT_VEHICLE_PAIR_ZERO_SEARCH_WITNESSES",
        },
        {
            "gate": "D3",
            "status": "HALT",
            "search_evaluations": 0,
            "reason": gate2["verdict"],
        },
        {
            "gate": "D4",
            "status": "NOT_RUN",
            "search_evaluations": 0,
            "reason": "UPSTREAM_GATE_2_HALT",
        },
    ]
    write_csv(stage / "raw_runs.csv", root_rows)
    decision = {
        "schema": "resetp.e3e6-gates.decision.v1",
        "task_id": TASK_ID,
        "verdict": "HALT_AT_GATE_2_D3",
        "gate_1": gate1,
        "gate_2": gate2,
        "gate_3": gate3,
        "formal_e3_e6_allowed": False,
        "rescue_attempted": False,
        "worker_count": 1,
        "search_evaluations": 0,
    }
    write_json(stage / "decision.json", decision)
    write_json(
        stage / "metadata.json",
        {
            "schema": "resetp.e3e6-gates.metadata.v1",
            "task_id": TASK_ID,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "git_head": git_text("rev-parse", "HEAD"),
            "git_branch": git_text(
                "rev-parse", "--abbrev-ref", "HEAD"
            ),
            "worktree_dirty": bool(git_text("status", "--porcelain")),
            "python_executable": sys.executable,
            "python_version": platform.python_version(),
            "packages": {
                name: version(name)
                for name in ("pyvrp", "numpy", "scipy")
            },
            "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
            "worker_count": 1,
            "worker_limit_from_user": 2,
            "load_average_observed_before_run": [2.93, 4.04, 5.67],
            "process_table_probe": (
                "UNAVAILABLE_SANDBOX_PERMISSION_DENIED"
            ),
            "resource_decision": (
                "single process; zero-search gates only; D4 not run"
            ),
            "approval": relative(APPROVAL),
            "preflight": relative(PREFLIGHT),
            "source_hashes": source_hashes(
                (
                    CURRENT_BUILDER,
                    APPROVAL,
                    PREFLIGHT,
                    OLD_BUILDER,
                    PYVRP_ADAPTER,
                    EPOCHAL_HGS,
                    ROUTE_POOL_SP,
                    FORMAL_E3_RUNNER,
                    RELEASE_CONFIG,
                    CHINA81,
                    CHINA81_COMPLETION,
                    *PROTECTED,
                )
            ),
            "protected_hashes_before": protected_before,
            "protected_hashes_after": protected_after,
            "protected_files_unchanged": True,
            "formal_e3_e6_allowed": False,
            "search_evaluations": 0,
        },
    )
    (stage / "report.md").write_text(
        "# E3E6-GATES-01 正式实验前置门\n\n"
        "**总判决：HALT_AT_GATE_2_D3。E3/E6 正式实验不得启动。**\n\n"
        "门一 D2-A 为 PASS：在当前 CV 威铃 K7（1735/2565 kg）与 "
        "EV 福田 ES1 快递版栏板（1700/2600 kg、77.28 kWh）绑定下，"
        f"81 个实例、{gate1['fleet_rows']} 个实例-车场行全部重算；"
        "每个实例均保存零搜索全燃油 witness 并通过完整模型复算。旧 "
        "`china81_finite_fleet_authority_v1_20260723` 仅用于只读逐行"
        "对比，没有覆盖。\n\n"
        "门二 D3 为 HALT：当前源码上的四层控制守卫均存在并通过行为/源码"
        "重放，45 个多车场实例的处理臂也确实能构造跨场服务；但 36 个"
        "实例只有一个车场，处理臂在这些实例上无法产生跨车场服务。用户"
        "要求的是全部 81 个实例逐实例成立，不能把“锁已移除、Exchange11 "
        "已启用”替代为不存在第二车场时的实际可产生性。因此旧的结构性 "
        "PASS 不能复用为本次强门 PASS。\n\n"
        "门三 D4 未运行：遵守上游任一门失败立即停止的要求，没有启动 "
        "pilot，没有查看或报告任何臂间成本。只读源码预检确认当前 E3/E6 "
        "确实是固定 80 次完整候选评价、`MaxIterations` 加墙钟安全上限，"
        "不是 `NoImprovement` 收敛停机；但未计算 `L/S`，也未选择 "
        "80/56/32 或更高档位。\n\n"
        "逐门证据分别位于 `gate1_d2a/`、`gate2_d3/`、`gate3_d4/`。"
        "本任务固定单进程，搜索评价数为 0，未修改 `cost.py`、"
        "`check.py` 或 `search/evaluation.py`，且未执行任何救援调参。\n",
        encoding="utf-8",
    )
    write_artifact_manifest(stage)
    return decision


def main() -> None:
    if OUT.exists():
        raise RuntimeError(
            f"refusing to overwrite existing task output: {OUT}"
        )
    approval_text = APPROVAL.read_text(encoding="utf-8")
    if "APPROVED_BY_USER_20260728" not in approval_text:
        raise RuntimeError("approved execution binding is missing")
    temporary_root = Path(
        tempfile.mkdtemp(
            prefix=".resetp-e3e6-gates-01-",
            dir=OUT.parent,
        )
    )
    stage = temporary_root / OUT.name
    stage.mkdir()
    try:
        decision = build(stage)
        shutil.move(str(stage), str(OUT))
        temporary_root.rmdir()
    except BaseException:
        print(f"UNPUBLISHED_STAGE={stage}", file=sys.stderr)
        raise
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
