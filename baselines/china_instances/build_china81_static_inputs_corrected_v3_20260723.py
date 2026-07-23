#!/usr/bin/env python3
"""Materialize corrected China81 static inputs without solver search."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any


REPO = Path(__file__).resolve().parents[2]
LEGACY_BUILDER = (
    REPO
    / "baselines/china_instances/"
    "build_china_stage2_static_inputs_20260718.py"
)
ORDERS = (
    REPO
    / "data/ChinaInstances/"
    "china81_order_attributes_gis_v2_20260723/orders.csv"
)
PARAMETERS = (
    REPO
    / "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v3_20260723"
)
OUT = (
    REPO
    / "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723"
)
POOL_MEMBERSHIP = (
    REPO
    / "baselines/china_e3_e7/pre_e3_full_chain_audit_20260723/"
    "customer_pool_boundary_audit.csv"
)
LEGACY_NODE_MEMBERSHIP = (
    REPO
    / "baselines/china_e3_e7/pre_e3_full_chain_audit_20260723/"
    "coordinate_inventory.csv"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "resetp_legacy_static_builder",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import builder: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_membership_registry() -> list[dict[str, Any]]:
    pool_status = {
        (row["declared_city"], row["osm_type"], row["osm_id"]): row
        for row in read_csv(POOL_MEMBERSHIP)
    }
    facility_status = {}
    for row in read_csv(LEGACY_NODE_MEMBERSHIP):
        if row["node_type"] not in {"depot", "station"}:
            continue
        key = (
            row["node_type"],
            row["declared_city"],
            f"{float(row['latitude']):.7f}",
            f"{float(row['longitude']):.7f}",
        )
        facility_status[key] = row
    orders = {
        (row["instance_id"], row["customer_id"]): row
        for row in read_csv(ORDERS)
    }

    result = []
    for catalog in read_csv(OUT / "instance_catalog.csv"):
        instance_id = catalog["instance_id"]
        nodes = read_csv(OUT / "instances" / instance_id / "nodes.csv")
        for node in nodes:
            if node["node_type"] == "customer":
                order = orders[(instance_id, node["node_id"])]
                source = pool_status[
                    (order["city"], order["osm_type"], order["osm_id"])
                ]
                source_identity = f"{order['osm_type']}/{order['osm_id']}"
            else:
                source = facility_status[
                    (
                        node["node_type"],
                        node["city"],
                        f"{float(node['latitude']):.7f}",
                        f"{float(node['longitude']):.7f}",
                    )
                ]
                source_identity = node["source_identity"]
            if source["gis_status"] != "PASS_DECLARED_CITY_BOUNDARY":
                raise RuntimeError(
                    f"corrected node is outside its city: "
                    f"{instance_id}/{node['node_id']}"
                )
            result.append(
                {
                    "instance_id": instance_id,
                    "node_id": node["node_id"],
                    "node_type": node["node_type"],
                    "declared_city": node["city"],
                    "latitude": f"{float(node['latitude']):.7f}",
                    "longitude": f"{float(node['longitude']):.7f}",
                    "source_identity": source_identity,
                    "gis_status": source["gis_status"],
                    "boundary_memberships": source[
                        "boundary_memberships"
                    ],
                    "boundary_source_date": source.get(
                        "boundary_source_date",
                        "2026-07-16",
                    ),
                    "boundary_source_class": source.get(
                        "boundary_source_class",
                        (
                            "COMPUTATIONAL_VALIDATION_BOUNDARY_"
                            "NOT_OFFICIAL_CHINA_SURVEY"
                        ),
                    ),
                }
            )
    if len(result) != 6093:
        raise RuntimeError(f"expected 6093 node memberships, got {len(result)}")
    return result


def refresh_hashes() -> None:
    files = {}
    for path in sorted(OUT.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
        ):
            files[str(path.relative_to(OUT))] = sha256(path)
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
            "sha256": files,
        },
    )


def build() -> dict[str, Any]:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite corrected static input: {OUT}")
    parameter_decision = json.loads(
        (PARAMETERS / "decision.json").read_text(encoding="utf-8")
    )
    if (
        parameter_decision.get("verdict")
        != "PASS_TARIFF_CARBON_MAPPING__HOLD_DIESEL_PARAMETER_ACTIVATION"
    ):
        raise RuntimeError("runtime parameter authority has an unexpected status")

    legacy = load_module(LEGACY_BUILDER)
    legacy.OUT = OUT
    legacy.ORDERS = ORDERS
    legacy.build_calendar = lambda: read_csv(
        PARAMETERS / "tariff_carbon_48slot_calendar.csv"
    )
    legacy.main()

    membership = build_membership_registry()
    write_csv(OUT / "node_city_membership.csv", membership)
    if any(
        row["gis_status"] != "PASS_DECLARED_CITY_BOUNDARY"
        for row in membership
    ):
        raise RuntimeError("corrected node membership registry contains a failure")

    metadata_path = OUT / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update(
        {
            "schema": "resetp.china81-stage2-static-inputs.v3",
            "created_date": "2026-07-23",
            "repair_builder": str(Path(__file__).relative_to(REPO)),
            "repair_builder_sha256": sha256(Path(__file__)),
            "orders": str(ORDERS.relative_to(REPO)),
            "orders_sha256": sha256(ORDERS),
            "runtime_parameter_authority": str(PARAMETERS.relative_to(REPO)),
            "runtime_parameter_authority_hash": sha256(
                PARAMETERS / "artifact_hashes.json"
            ),
            "node_city_membership_rows": len(membership),
            "all_node_city_memberships_pass": True,
            "diesel_candidate_values_activated": False,
        }
    )
    write_json(metadata_path, metadata)
    decision_path = OUT / "decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision.update(
        {
            "verdict": (
                "PASS_CORRECTED_STATIC_INPUTS__"
                "HOLD_DIESEL_AND_ROAD_MATRIX_RELEASE"
            ),
            "chengdu_carbon_mapping": "Sichuan",
            "all_node_city_memberships_pass": True,
            "shenzhen_price_area_id": "shenzhen",
            "diesel_candidate_values_activated": False,
            "formal_experiment_authorized": False,
        }
    )
    write_json(decision_path, decision)
    (OUT / "report.md").write_text(
        "# China81 修正版静态输入 v3\n\n"
        "81 份节点和订单已从 GIS 修正版位置包重建；6093 个实例节点均绑定"
        "行政区成员证书。电价数值保持不变，深圳显式绑定独立价区，成都"
        "碳列改为四川。柴油候选值尚未激活，道路矩阵尚待按新坐标重建，"
        "因此继续禁止正式搜索。\n",
        encoding="utf-8",
    )
    parameter_lock_path = OUT / "parameter_lock.json"
    parameter_lock = json.loads(
        parameter_lock_path.read_text(encoding="utf-8")
    )
    parameter_lock.update(
        {
            "schema": "resetp.china.stage2-static-input-lock.v3",
            "status": (
                "CORRECTED_STATIC_INPUTS__"
                "DIESEL_PARAMETER_AND_ROAD_MATRIX_HELD"
            ),
            "runtime_parameter_authority": str(PARAMETERS.relative_to(REPO)),
            "diesel_candidate_values_activated": False,
            "formal_search_allowed": False,
        }
    )
    write_json(parameter_lock_path, parameter_lock)
    refresh_hashes()
    return {
        "verdict": decision["verdict"],
        "instances": 81,
        "orders": 5805,
        "node_city_memberships": len(membership),
        "calendar_rows": 12096,
        "search_evaluations": 0,
        "formal_search_allowed": False,
    }


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, sort_keys=True))
