#!/usr/bin/env python3
"""Materialize the fail-closed China81 settlement join.

The output separates the stable node-to-city relation from the
city/date/half-hour parameter relation. Their declared composite key is the
only admissible bridge used by the formal China evaluation:

instance/node -> city/price area/carbon column/diesel zone
              -> scenario date -> half-hour slot.

Coordinates are retained as a geographic certificate only. They never select
tariffs, carbon factors, or fuel prices implicitly.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "solver/src") not in sys.path:
    sys.path.insert(0, str(REPO / "solver/src"))

from setp_solver.china81 import (  # noqa: E402
    DEFAULT_CHINA81_DATE,
    load_china81_bundle,
)


STATIC = (
    REPO
    / "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723"
)
RUNTIME = (
    REPO
    / "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v4_20260723"
)
FLEET = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v1_20260723"
)
OUT = (
    REPO
    / "data/ChinaInstances/"
    "china81_spatiotemporal_settlement_authority_v1_20260723"
)
APPROVAL_ID = "CHINA-E3-FORMAL-RELEASE-001"


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
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _instance_ids() -> list[str]:
    return sorted(
        row["instance_id"]
        for row in read_csv(STATIC / "instance_catalog.csv")
    )


def build() -> dict[str, Any]:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite existing authority: {OUT}")
    OUT.mkdir(parents=True)

    node_rows: list[dict[str, Any]] = []
    slot_rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    node_keys: set[tuple[str, str]] = set()
    slot_keys: set[tuple[str, str, str, int]] = set()
    active_cities: set[str] = set()

    for instance_id in _instance_ids():
        bundle = load_china81_bundle(REPO, instance_id)
        if bundle.date != DEFAULT_CHINA81_DATE:
            raise RuntimeError(
                f"scenario date drifted for {instance_id}: {bundle.date}"
            )
        profile_by_city: dict[str, list[dict[str, Any]]] = {}
        for row in bundle.time_profile:
            profile_by_city.setdefault(str(row["city"]), []).append(row)

        for node in bundle.instance.nodes:
            city = "" if node.city is None else str(node.city).strip().lower()
            if not city:
                raise RuntimeError(
                    f"node has no city binding: {instance_id}/{node.node_id}"
                )
            key = (instance_id, node.node_id)
            if key in node_keys:
                raise RuntimeError(f"duplicate node binding: {key}")
            node_keys.add(key)
            active_cities.add(city)
            node_rows.append(
                {
                    "instance_id": instance_id,
                    "node_id": node.node_id,
                    "node_type": node.node_type,
                    "declared_city": city,
                    "latitude": f"{float(node.y):.7f}",
                    "longitude": f"{float(node.x):.7f}",
                    "geography_role": (
                        "VALIDATION_ONLY_NOT_PARAMETER_SELECTOR"
                    ),
                    "price_area_id": bundle.price_area_by_city[city],
                    "carbon_source_column": (
                        bundle.carbon_source_column_by_city[city]
                    ),
                    "diesel_zone": bundle.diesel_zone_by_city[city],
                    "scenario_date": bundle.date,
                    "electricity_carbon_settlement_location": (
                        "CHARGING_NODE_CITY"
                    ),
                    "diesel_settlement_location": (
                        "ROUTE_ORIGIN_DEPOT_CITY"
                    ),
                    "joint_key_status": "PASS_FAIL_CLOSED_NODE_CITY_BINDING",
                }
            )

        for city, rows in sorted(profile_by_city.items()):
            if len(rows) != 48:
                raise RuntimeError(
                    f"not 48 slots: {instance_id}/{city}/{len(rows)}"
                )
            for row in sorted(rows, key=lambda item: item["half_hour_slot"]):
                slot = int(row["half_hour_slot"])
                key = (instance_id, city, bundle.date, slot)
                if key in slot_keys:
                    raise RuntimeError(f"duplicate settlement key: {key}")
                slot_keys.add(key)
                slot_rows.append(
                    {
                        "instance_id": instance_id,
                        "city": city,
                        "price_area_id": row["price_area_id"],
                        "carbon_source_column": (
                            row["carbon_source_column"]
                        ),
                        "diesel_zone": row["diesel_zone"],
                        "scenario_date": row["date"],
                        "half_hour_slot": slot,
                        "minute_of_day": int(
                            row["horizon_second_start"] / 60
                        ),
                        "tariff_period": row["tariff_period"],
                        "depot_energy_cny_per_kwh": (
                            row["depot_energy_cny_per_kwh"]
                        ),
                        "public_energy_cny_per_kwh": (
                            row["public_energy_cny_per_kwh"]
                        ),
                        "public_service_fee_cny_per_kwh": (
                            row["public_service_fee_cny_per_kwh"]
                        ),
                        "public_total_cny_per_kwh": (
                            row["public_total_cny_per_kwh"]
                        ),
                        "carbon_factor_kgco2e_per_kwh": (
                            float(row["actual_gco2_per_kwh"]) / 1000.0
                        ),
                        "diesel_price_cny_per_l": (
                            row["diesel_price_cny_per_l"]
                        ),
                        "diesel_parameter_status": (
                            row["diesel_parameter_status"]
                        ),
                        "joint_key_status": row["joint_key_status"],
                    }
                )
        raw_rows.append(
            {
                "instance_id": instance_id,
                "node_bindings": len(bundle.instance.nodes),
                "active_city_count": len(profile_by_city),
                "city_slot_bindings": sum(
                    len(rows)
                    for rows in profile_by_city.values()
                ),
                "scenario_date": bundle.date,
                "parameter_authority": (
                    bundle.runtime_parameter_authority
                ),
                "fleet_authority": bundle.fleet_authority,
                "status": "PASS",
                "search_evaluations": 0,
            }
        )

    expected_slot_rows = sum(
        int(row["active_city_count"]) * 48
        for row in raw_rows
    )
    if len(slot_rows) != expected_slot_rows:
        raise RuntimeError("materialized settlement row count is incomplete")

    write_csv(OUT / "node_parameter_binding.csv", node_rows)
    write_csv(OUT / "city_date_slot_parameter_binding.csv", slot_rows)
    write_csv(OUT / "raw_runs.csv", raw_rows)
    decision = {
        "schema": "resetp.china81-spatiotemporal-settlement.v1",
        "verdict": "PASS_FAIL_CLOSED_SPATIOTEMPORAL_SETTLEMENT_AUTHORITY",
        "approval_id": APPROVAL_ID,
        "joint_key": [
            "instance_id",
            "node_id",
            "declared_city",
            "price_area_id",
            "carbon_source_column",
            "diesel_zone",
            "scenario_date",
            "half_hour_slot",
        ],
        "scenario_date": DEFAULT_CHINA81_DATE,
        "instance_count": len(raw_rows),
        "active_city_count": len(active_cities),
        "node_binding_count": len(node_rows),
        "city_date_slot_binding_count": len(slot_rows),
        "coordinate_semantics": (
            "validation only; never an implicit parameter selector"
        ),
        "electricity_carbon_semantics": (
            "charging-node city and charging timestamp half-hour slot"
        ),
        "diesel_semantics": "route-origin depot city",
        "missing_or_mixed_key_policy": "FAIL_CLOSED",
        "city_group_fallback_allowed": False,
        "formal_search_allowed": False,
        "search_evaluations": 0,
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": (
                "resetp.china81-spatiotemporal-settlement.metadata.v1"
            ),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "builder": str(Path(__file__).relative_to(REPO)),
            "approval_id": APPROVAL_ID,
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    STATIC / "instance_catalog.csv",
                    STATIC / "node_city_membership.csv",
                    RUNTIME / "tariff_carbon_48slot_calendar.csv",
                    RUNTIME / "decision.json",
                    FLEET / "fleet_caps.csv",
                    FLEET / "decision.json",
                    REPO
                    / "docs/handoff/"
                    "china_e3_formal_release_contract_20260723.md",
                )
            },
            "formal_search_allowed": False,
            "search_evaluations": 0,
        },
    )
    (OUT / "report.md").write_text(
        "# China81 时空能源结算联合权威 v1\n\n"
        "本包把 81 个算例的节点—城市关系与城市—2025-02-12—48 个"
        "半小时槽参数关系显式物化。电价和碳强度按充电地点城市及充电时刻"
        "结算；柴油价按路线出发车场城市结算。经纬度只核验行政区归属，"
        "不参与隐式参数选择。任何缺失、混城、混日、错槽、错碳列或错价区"
        "均失败关闭；无城市群均值回退。该包为零搜索证据，本身不授权正式"
        "搜索。\n",
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
