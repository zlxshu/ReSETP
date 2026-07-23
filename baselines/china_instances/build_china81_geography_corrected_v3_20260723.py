#!/usr/bin/env python3
"""Rebuild China81 locations and order rows after the GIS/physical-identity gate.

The registered location seeds, city quotas, replicate labels and order seeds
remain unchanged. Before seeded selection this builder removes rows outside
their declared administrative boundary and collapses exact physical-coordinate
duplicates within each city. Historical v2 packages are never overwritten.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any


REPO = Path(__file__).resolve().parents[2]
LEGACY_LOCATION_BUILDER = (
    REPO
    / "baselines/china_instances/"
    "build_china81_customer_location_assignments_v2_20260718.py"
)
LEGACY_ORDER_BUILDER = (
    REPO
    / "baselines/china_instances/"
    "build_china81_order_attributes_mc001_20260718.py"
)
BOUNDARY_AUDIT = (
    REPO
    / "baselines/china_e3_e7/pre_e3_full_chain_audit_20260723/"
    "customer_pool_boundary_audit.csv"
)
LOCATION_OUT = (
    REPO
    / "data/ChinaInstances/"
    "china81_customer_location_assignments_gis_v3_20260723"
)
ORDER_OUT = (
    REPO
    / "data/ChinaInstances/"
    "china81_order_attributes_gis_v2_20260723"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import builder: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def refresh_hashes(root: Path) -> None:
    files = {}
    for path in sorted(root.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
        ):
            files[str(path.relative_to(root))] = sha256(path)
    write_json(
        root / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
                "*.tmp",
            ],
            "files": files,
        },
    )


def filtered_pools(
    legacy: ModuleType,
) -> tuple[
    dict[str, dict[tuple[str, str], dict[str, str]]],
    dict[str, dict[str, int]],
]:
    membership = {
        (row["declared_city"], row["osm_type"], row["osm_id"]): row[
            "gis_status"
        ]
        for row in read_csv(BOUNDARY_AUDIT)
    }
    pools = legacy.load_pools()
    if sum(len(rows) for rows in pools.values()) != len(membership):
        raise RuntimeError("active pools and GIS membership register disagree")

    filtered: dict[str, dict[tuple[str, str], dict[str, str]]] = {}
    counts: dict[str, dict[str, int]] = {}
    for city, rows in sorted(pools.items()):
        valid = []
        for identity, row in sorted(rows.items()):
            status = membership.get((city, *identity))
            if status is None:
                raise RuntimeError(f"missing GIS membership: {city}/{identity}")
            if status == "PASS_DECLARED_CITY_BOUNDARY":
                valid.append((identity, row))
            elif status != "FAIL_CITY_BOUNDARY":
                raise RuntimeError(
                    f"unsupported GIS status {status!r}: {city}/{identity}"
                )

        physical: dict[tuple[str, str], tuple[tuple[str, str], dict[str, str]]] = {}
        for identity, row in valid:
            coordinate = (
                f"{float(row['latitude']):.7f}",
                f"{float(row['longitude']):.7f}",
            )
            physical.setdefault(coordinate, (identity, row))
        kept = {identity: row for identity, row in physical.values()}
        filtered[city] = kept
        counts[city] = {
            "input_rows": len(rows),
            "outside_boundary_removed": len(rows) - len(valid),
            "physical_duplicates_removed": len(valid) - len(kept),
            "eligible_rows": len(kept),
        }
    return filtered, counts


def build() -> dict[str, Any]:
    if LOCATION_OUT.exists() or ORDER_OUT.exists():
        raise RuntimeError("refusing to overwrite an existing v3 geography package")

    location_builder = load_module(
        LEGACY_LOCATION_BUILDER,
        "resetp_legacy_location_builder",
    )
    pools, counts = filtered_pools(location_builder)
    location_builder.load_pools = lambda: pools
    location_decision = location_builder.build(LOCATION_OUT)
    if (
        location_decision.get("verdict")
        != "PASS_81_DISJOINT_LOCATION_ASSIGNMENTS_BUILT"
    ):
        raise RuntimeError("filtered location build did not pass")

    location_metadata_path = LOCATION_OUT / "metadata.json"
    location_metadata = json.loads(
        location_metadata_path.read_text(encoding="utf-8")
    )
    location_metadata.update(
        {
            "schema": "resetp.china81.location-assignment.metadata.v3",
            "repair_builder": str(Path(__file__).relative_to(REPO)),
            "repair_builder_sha256": sha256(Path(__file__)),
            "boundary_audit": str(BOUNDARY_AUDIT.relative_to(REPO)),
            "boundary_audit_sha256": sha256(BOUNDARY_AUDIT),
            "pre_seed_boundary_filter": True,
            "pre_seed_exact_coordinate_deduplication": True,
            "pool_repair_counts": counts,
        }
    )
    write_json(location_metadata_path, location_metadata)
    decision_path = LOCATION_OUT / "decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision.update(
        {
            "schema": "resetp.china81.location-assignment.decision.v3",
            "gis_boundary_failures_retained": 0,
            "physical_coordinate_overlap_policy": (
                "ONE_LEXICOGRAPHICALLY_FIRST_OSM_IDENTITY_PER_EXACT_WGS84_POINT"
            ),
            "pool_rows_removed_outside_boundary": sum(
                row["outside_boundary_removed"] for row in counts.values()
            ),
            "pool_rows_removed_physical_duplicate": sum(
                row["physical_duplicates_removed"] for row in counts.values()
            ),
        }
    )
    write_json(decision_path, decision)
    (LOCATION_OUT / "report.md").write_text(
        "# China81 客户位置 GIS 修正版\n\n"
        f"判定：`{decision['verdict']}`。在原预注册种子抽样前，"
        f"剔除 {decision['pool_rows_removed_outside_boundary']} 个越界候选，"
        f"并合并 {decision['pool_rows_removed_physical_duplicate']} 个"
        "同城同坐标重复身份。城市配额、种子规则与三复本互斥规则不变；"
        "本包零求解器搜索且不覆盖 v2 历史证据。\n",
        encoding="utf-8",
    )
    refresh_hashes(LOCATION_OUT)

    order_builder = load_module(
        LEGACY_ORDER_BUILDER,
        "resetp_legacy_order_builder",
    )
    order_builder.LOCATIONS = LOCATION_OUT
    order_decision = order_builder.build(ORDER_OUT)
    if (
        order_decision.get("verdict")
        != "PASS_CHINA81_MC001_ORDER_ATTRIBUTE_LAYER_BUILT"
    ):
        raise RuntimeError("corrected order build did not pass")
    order_metadata_path = ORDER_OUT / "metadata.json"
    order_metadata = json.loads(
        order_metadata_path.read_text(encoding="utf-8")
    )
    order_metadata.update(
        {
            "schema": "resetp.china81.mc001-order-layer.metadata.v2",
            "repair_builder": str(Path(__file__).relative_to(REPO)),
            "repair_builder_sha256": sha256(Path(__file__)),
            "location_authority": str(LOCATION_OUT.relative_to(REPO)),
            "location_authority_hash": sha256(
                LOCATION_OUT / "artifact_hashes.json"
            ),
            "order_attribute_sampling_rule_changed": False,
        }
    )
    write_json(order_metadata_path, order_metadata)
    (ORDER_OUT / "report.md").write_text(
        "# China81 MC-001 订单属性层（GIS 修正版位置）\n\n"
        "判定：`PASS_CHINA81_MC001_ORDER_ATTRIBUTE_LAYER_BUILT`。"
        "订单属性仍按原合同、原实例 ID 和原种子抽取完整经验行；"
        "仅位置输入切换到通过行政边界与物理坐标去重的 v3 包。"
        "本包零求解器搜索，不授权正式实验。\n",
        encoding="utf-8",
    )
    refresh_hashes(ORDER_OUT)

    return {
        "location_verdict": decision["verdict"],
        "order_verdict": order_decision["verdict"],
        "pool_rows_removed_outside_boundary": decision[
            "pool_rows_removed_outside_boundary"
        ],
        "pool_rows_removed_physical_duplicate": decision[
            "pool_rows_removed_physical_duplicate"
        ],
        "location_rows": decision["assignment_rows"],
        "order_rows": order_decision["order_rows"],
        "search_evaluations": 0,
        "formal_search_allowed": False,
    }


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, sort_keys=True))
