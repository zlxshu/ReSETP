#!/usr/bin/env python3
"""Audit whether frozen nine-city public-station rows meet the formal contract."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
POOLS = REPO / "data/ChinaInstances/china9_city_full_pool_20260718/pools"
OUTPUT = (
    REPO / "data/ChinaInstances/china9_public_station_provenance_audit_v1_20260718"
)
CITIES = [
    "beijing",
    "tianjin",
    "shijiazhuang",
    "guangzhou",
    "shenzhen",
    "dongguan",
    "foshan",
    "chengdu",
    "chongqing",
]


def truth(value: str) -> bool:
    return value.strip().lower() == "true"


def audit_city(city: str) -> dict[str, Any]:
    path = POOLS / f"{city}__charging_station.csv"
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    named = [row for row in rows if row["name"].strip()]
    operator = [
        row for row in rows if json.loads(row["tags"]).get("operator", "").strip()
    ]
    powered = [row for row in rows if truth(row["positive_power_tag"])]
    capacity = [row for row in rows if truth(row["positive_capacity_tag"])]
    complete = [
        row
        for row in rows
        if row["name"].strip()
        and json.loads(row["tags"]).get("operator", "").strip()
        and truth(row["positive_power_tag"])
        and truth(row["positive_capacity_tag"])
    ]
    return {
        "city": city,
        "frozen_candidates": len(rows),
        "named_candidates": len(named),
        "operator_tag_candidates": len(operator),
        "positive_power_tag_candidates": len(powered),
        "positive_capacity_tag_candidates": len(capacity),
        "osm_rows_meeting_all_four_fields": len(complete),
        "formal_station_ready": False,
        "formal_gap": (
            "OSM tags alone do not provide operator-source power and gun-count provenance"
        ),
        "source_pool": str(path.relative_to(REPO)),
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = [audit_city(city) for city in CITIES]
    csv_path = OUTPUT / "city_audit.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    raw_runs_path = OUTPUT / "raw_runs.csv"
    with raw_runs_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    payload = {
        "schema": "resetp.china9.public-station-provenance-audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision": "HALT_PUBLIC_STATION_PROVENANCE_0_OF_9_FORMAL_READY",
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "cities": 9,
        "cities_with_any_candidate": sum(row["frozen_candidates"] > 0 for row in rows),
        "cities_formal_ready": 0,
        "boundary": (
            "Frozen OSM identities are discovery candidates, not evidence of rated "
            "power, usable freight connector count, access or applicable tariff."
        ),
    }
    decision_path = OUTPUT / "decision.json"
    decision_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    metadata_path = OUTPUT / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema": "resetp.china9.public-station-provenance-audit.metadata.v1",
                "created_at_utc": payload["created_at_utc"],
                "source_pool_directory": str(POOLS.relative_to(REPO)),
                "source_pool_hashes": {
                    f"{city}__charging_station.csv": sha256(
                        POOLS / f"{city}__charging_station.csv"
                    )
                    for city in CITIES
                },
                "formal_search_allowed": False,
                "search_evaluations": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report = [
        "# 九城公共充电站证据充分性审计",
        "",
        "判决：`HALT_PUBLIC_STATION_PROVENANCE_0_OF_9_FORMAL_READY`。",
        "",
        f"冻结 OSM 池中有候选的城市为 {payload['cities_with_any_candidate']}/9，"
        "但没有城市具备可同时核验的站名、运营方、额定功率、可用枪数及其运营方来源。",
        "因此 OSM 行只能作为后续逐站补证的身份候选，不能直接填入正式实例。",
        "",
        "| 城市 | 候选 | 有名 | 有运营方标签 | 有功率标签 | 有容量标签 | 正式可用 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        report.append(
            f"| {row['city']} | {row['frozen_candidates']} | "
            f"{row['named_candidates']} | {row['operator_tag_candidates']} | "
            f"{row['positive_power_tag_candidates']} | "
            f"{row['positive_capacity_tag_candidates']} | 0 |"
        )
    report_path = OUTPUT / "report.md"
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    hashes = {
        path.name: sha256(path)
        for path in (
            metadata_path,
            raw_runs_path,
            csv_path,
            decision_path,
            report_path,
        )
    }
    (OUTPUT / "artifact_hashes.json").write_text(
        json.dumps(hashes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
