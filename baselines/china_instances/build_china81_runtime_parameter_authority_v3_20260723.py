#!/usr/bin/env python3
"""Build the corrected, explicit China81 runtime-parameter authority.

This is a zero-search data repair. It preserves the frozen v1 tariff numbers,
replaces only the mis-mapped Chengdu carbon column, and attaches reviewed
city/price-area/carbon/diesel-zone identities to every calendar row. Candidate
February 2025 diesel values remain marked as awaiting the separate parameter
approval required by PRE-E3-FULL-CHAIN-REVIEWER-AUDIT-001.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
OUT = (
    REPO
    / "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v3_20260723"
)
LEGACY_CALENDAR = (
    REPO
    / "data/ChinaInstances/"
    "china81_stage2_static_inputs_v1_20260718/"
    "tariff_carbon_48slot_calendar.csv"
)
TVCI = (
    REPO
    / "baselines/e4_e5/china_2025_formal_month_selection_20260718/"
    "tvci_2025_february_48slot_wide.csv"
)
MAPPING = (
    REPO
    / "baselines/china_e3_e7/pre_e3_full_chain_audit_20260723/"
    "city_parameter_mapping_registry.csv"
)
DIESEL = (
    REPO
    / "baselines/china_e3_e7/pre_e3_full_chain_audit_20260723/"
    "diesel_price_2025_02_12_source_register.csv"
)
SHENZHEN_CLOSURE = (
    REPO
    / "baselines/e4_e5/shenzhen_2025_02_tariff_closure_20260723/"
    "decision.json"
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


def build() -> dict[str, Any]:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite existing authority: {OUT}")
    OUT.mkdir(parents=True)

    mappings = {row["city"]: row for row in read_csv(MAPPING)}
    diesel_rows = {row["city"]: row for row in read_csv(DIESEL)}
    if set(mappings) != set(diesel_rows) or len(mappings) != 9:
        raise RuntimeError("reviewed city mapping and diesel registers disagree")
    if mappings["chengdu"]["carbon_column"] != "Sichuan":
        raise RuntimeError("reviewed Chengdu carbon mapping is not Sichuan")

    tvci_rows = {
        (row["date"], int(row["half_hour_slot"])): row
        for row in read_csv(TVCI)
    }
    calendar_rows: list[dict[str, Any]] = []
    changed = 0
    for legacy in read_csv(LEGACY_CALENDAR):
        city = legacy["city"].strip().lower()
        mapping = mappings[city]
        diesel = diesel_rows[city]
        slot = int(legacy["half_hour_slot"])
        minute = int(legacy["minute_of_day"])
        if minute != (slot - 1) * 30:
            raise RuntimeError(f"noncanonical slot-minute pair in {city}")
        expected_carbon = tvci_rows[
            (legacy["date"], slot)
        ][mapping["carbon_column"]]
        old_carbon = float(legacy["carbon_factor_kgco2e_per_kwh"])
        new_carbon = float(expected_carbon)
        if not math.isfinite(new_carbon) or new_carbon < 0.0:
            raise RuntimeError(f"invalid carbon factor for {city}")
        if not math.isclose(old_carbon, new_carbon, abs_tol=1e-12):
            changed += 1
        energy = float(legacy["public_energy_cny_per_kwh"])
        service = float(legacy["public_service_fee_cny_per_kwh"])
        total = float(legacy["public_total_cny_per_kwh"])
        if not math.isclose(
            energy + service,
            total,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise RuntimeError(f"public tariff components do not close for {city}")
        calendar_rows.append(
            {
                **legacy,
                "carbon_factor_kgco2e_per_kwh": f"{new_carbon:.8f}",
                "carbon_source_column": mapping["carbon_column"],
                "price_area_id": mapping["price_area_id"],
                "diesel_zone": mapping["diesel_zone"],
                "diesel_price_candidate_cny_per_l": (
                    diesel["reviewed_price_cny_per_l"]
                ),
                "diesel_candidate_status": (
                    "PENDING_EXPLICIT_PARAMETER_APPROVAL"
                ),
                "diesel_source_strength": diesel[
                    "reviewed_source_strength"
                ],
                "diesel_source_file": diesel["source_file"],
                "diesel_source_sha256": diesel["source_sha256"],
            }
        )

    if len(calendar_rows) != 9 * 28 * 48:
        raise RuntimeError(
            f"expected 12096 calendar rows, got {len(calendar_rows)}"
        )
    if changed != 28 * 48:
        raise RuntimeError(
            f"expected 1344 corrected Chengdu rows, got {changed}"
        )
    shenzhen = json.loads(SHENZHEN_CLOSURE.read_text(encoding="utf-8"))
    if (
        shenzhen.get("verdict")
        != "PASS_SHENZHEN_2025_02_EV_CHARGING_SCENARIO_ROW_CLOSED"
        or shenzhen.get("numeric_change_from_frozen_static_input") is not False
    ):
        raise RuntimeError("Shenzhen scenario-row closure is not reusable")

    register_rows = []
    for city in sorted(mappings):
        mapping = mappings[city]
        diesel = diesel_rows[city]
        register_rows.append(
            {
                "city": city,
                "region": mapping["region"],
                "province_or_municipality": mapping[
                    "province_or_municipality"
                ],
                "price_area_id": mapping["price_area_id"],
                "carbon_source_column": mapping["carbon_column"],
                "diesel_zone": mapping["diesel_zone"],
                "diesel_price_candidate_cny_per_l": diesel[
                    "reviewed_price_cny_per_l"
                ],
                "diesel_candidate_status": (
                    "PENDING_EXPLICIT_PARAMETER_APPROVAL"
                ),
                "diesel_source_strength": diesel[
                    "reviewed_source_strength"
                ],
                "diesel_source_url": diesel["reviewed_source_url"],
                "diesel_source_file": diesel["source_file"],
                "diesel_source_sha256": diesel["source_sha256"],
                "mapping_status": "PASS_EXPLICIT_RUNTIME_IDENTITY",
            }
        )

    calendar_path = OUT / "tariff_carbon_48slot_calendar.csv"
    register_path = OUT / "city_runtime_parameter_register.csv"
    write_csv(calendar_path, calendar_rows)
    write_csv(register_path, register_rows)
    raw_runs = [
        {
            "check_id": "V3-ROW-COUNT",
            "status": "PASS",
            "observed": len(calendar_rows),
            "expected": 12096,
            "search_evaluations": 0,
        },
        {
            "check_id": "V3-CHENGDU-CARBON-CORRECTION",
            "status": "PASS",
            "observed": changed,
            "expected": 1344,
            "search_evaluations": 0,
        },
        {
            "check_id": "V3-SHENZHEN-NUMERIC-REUSE",
            "status": "PASS",
            "observed": "no tariff numeric change",
            "expected": "closed Shenzhen scenario row",
            "search_evaluations": 0,
        },
        {
            "check_id": "V3-DIESEL-PARAMETER-APPROVAL",
            "status": "HOLD",
            "observed": "9 candidate city rows",
            "expected": "explicit user approval before runtime activation",
            "search_evaluations": 0,
        },
    ]
    write_csv(OUT / "raw_runs.csv", raw_runs)
    decision = {
        "schema": "resetp.china81-runtime-parameter-authority.v3",
        "verdict": (
            "PASS_TARIFF_CARBON_MAPPING__"
            "HOLD_DIESEL_PARAMETER_ACTIVATION"
        ),
        "tariff_numeric_change": False,
        "chengdu_carbon_rows_corrected": changed,
        "shenzhen_price_area_explicit": True,
        "diesel_city_zone_selector_materialized": True,
        "diesel_candidate_values_activated": False,
        "formal_search_allowed": False,
        "search_evaluations": 0,
    }
    write_json(OUT / "decision.json", decision)
    metadata = {
        "schema": "resetp.china81-runtime-parameter-authority.metadata.v3",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "builder": str(Path(__file__).relative_to(REPO)),
        "source_hashes": {
            str(path.relative_to(REPO)): sha256(path)
            for path in (
                LEGACY_CALENDAR,
                TVCI,
                MAPPING,
                DIESEL,
                SHENZHEN_CLOSURE,
            )
        },
        "search_evaluations": 0,
        "formal_search_allowed": False,
    }
    write_json(OUT / "metadata.json", metadata)
    (OUT / "report.md").write_text(
        "# China81 运行时参数权威 v3\n\n"
        "该零搜索修复保留 v1 电价数值，显式绑定九城价区、碳列与柴油区，"
        "并将成都 2025-02 的 1344 个半小时槽由误用的重庆列改为四川列。"
        "深圳继续使用已闭合且数值不变的独立充电情景行。"
        "2025-02-12 柴油候选值虽已形成来源链，但依审计合同尚未激活；"
        "因此本包不授权正式搜索。\n",
        encoding="utf-8",
    )
    artifacts = {}
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
