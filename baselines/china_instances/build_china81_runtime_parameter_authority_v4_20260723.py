#!/usr/bin/env python3
"""Activate the user-approved, date-aligned China81 runtime parameters.

This is a zero-search version lift from v3. It does not alter electricity or
carbon values. It promotes the reviewed 2025-02-12 city diesel values from
candidate fields to effective runtime fields and makes the common
city/date/slot identity explicit on every row.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
SOURCE = (
    REPO
    / "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v3_20260723"
)
OUT = (
    REPO
    / "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v4_20260723"
)
APPROVAL = (
    REPO
    / "docs/handoff/china_e3_formal_release_contract_20260723.md"
)
EXPECTED_DIESEL = {
    "beijing": 7.48,
    "tianjin": 7.43,
    "shijiazhuang": 7.43,
    "guangzhou": 7.44,
    "shenzhen": 7.44,
    "dongguan": 7.44,
    "foshan": 7.44,
    "chengdu": 7.48,
    "chongqing": 7.50,
}
APPROVED_STATUS = "APPROVED_CHINA_E3_FORMAL_RELEASE_001"


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
    if not APPROVAL.is_file():
        raise RuntimeError("approved China E3 release contract is missing")
    approval_text = APPROVAL.read_text(encoding="utf-8")
    if "CHINA-E3-FORMAL-RELEASE-001" not in approval_text:
        raise RuntimeError("approved China E3 release contract ID is missing")
    OUT.mkdir(parents=True)

    source_register = read_csv(SOURCE / "city_runtime_parameter_register.csv")
    if {row["city"] for row in source_register} != set(EXPECTED_DIESEL):
        raise RuntimeError("v3 city register does not cover the approved nine cities")
    register_rows: list[dict[str, Any]] = []
    for row in source_register:
        city = row["city"]
        candidate = float(row["diesel_price_candidate_cny_per_l"])
        if candidate != EXPECTED_DIESEL[city]:
            raise RuntimeError(f"approved diesel value disagrees for {city}")
        register_rows.append(
            {
                **row,
                "scenario_date": "2025-02-12",
                "diesel_price_cny_per_l": f"{candidate:.2f}",
                "diesel_parameter_status": APPROVED_STATUS,
                "joint_key_status": "PASS_CITY_DATE_PARAMETER_IDENTITY",
            }
        )

    source_calendar = read_csv(SOURCE / "tariff_carbon_48slot_calendar.csv")
    calendar_rows: list[dict[str, Any]] = []
    keys: set[tuple[str, str, int]] = set()
    for row in source_calendar:
        city = row["city"]
        value = float(row["diesel_price_candidate_cny_per_l"])
        if value != EXPECTED_DIESEL[city]:
            raise RuntimeError(f"calendar diesel value disagrees for {city}")
        key = (city, row["date"], int(row["half_hour_slot"]))
        if key in keys:
            raise RuntimeError(f"duplicate city/date/slot key: {key}")
        keys.add(key)
        calendar_rows.append(
            {
                **row,
                "diesel_price_cny_per_l": f"{value:.2f}",
                "diesel_parameter_status": APPROVED_STATUS,
                "joint_key_status": "PASS_CITY_DATE_SLOT_PARAMETER_IDENTITY",
            }
        )
    if len(calendar_rows) != 9 * 28 * 48:
        raise RuntimeError("calendar row count is not 9 x 28 x 48")

    write_csv(OUT / "city_runtime_parameter_register.csv", register_rows)
    write_csv(OUT / "tariff_carbon_48slot_calendar.csv", calendar_rows)
    raw_rows = [
        {
            "check_id": "V4-CITY-DIESEL-ACTIVATION",
            "status": "PASS",
            "observed": len(register_rows),
            "expected": 9,
            "search_evaluations": 0,
        },
        {
            "check_id": "V4-JOINT-CITY-DATE-SLOT-KEY",
            "status": "PASS",
            "observed": len(keys),
            "expected": 9 * 28 * 48,
            "search_evaluations": 0,
        },
        {
            "check_id": "V4-ELECTRICITY-CARBON-NUMERIC-REUSE",
            "status": "PASS",
            "observed": sha256(
                SOURCE / "tariff_carbon_48slot_calendar.csv"
            ),
            "expected": "v3 numeric rows reused; only approval fields appended",
            "search_evaluations": 0,
        },
    ]
    write_csv(OUT / "raw_runs.csv", raw_rows)
    decision = {
        "schema": "resetp.china81-runtime-parameter-authority.v4",
        "verdict": "PASS_CITY_DATE_SLOT_PARAMETER_AUTHORITY",
        "approval_id": "CHINA-E3-FORMAL-RELEASE-001",
        "scenario_date": "2025-02-12",
        "city_count": 9,
        "calendar_rows": len(calendar_rows),
        "diesel_city_values_activated": True,
        "electricity_numeric_change_from_v3": False,
        "carbon_numeric_change_from_v3": False,
        "formal_search_allowed": False,
        "search_evaluations": 0,
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.china81-runtime-parameter-authority.metadata.v4",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "builder": str(Path(__file__).relative_to(REPO)),
            "approval_id": "CHINA-E3-FORMAL-RELEASE-001",
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    SOURCE / "city_runtime_parameter_register.csv",
                    SOURCE / "tariff_carbon_48slot_calendar.csv",
                    SOURCE / "decision.json",
                    APPROVAL,
                )
            },
            "formal_search_allowed": False,
            "search_evaluations": 0,
        },
    )
    (OUT / "report.md").write_text(
        "# China81 运行时参数权威 v4\n\n"
        "本包是零搜索参数版本提升。九城 2025-02-12 柴油价已按"
        "`CHINA-E3-FORMAL-RELEASE-001` 激活；电价和碳强度数值逐行复用 v3。"
        "每行显式携带城市、价区、碳列、柴油区、日期和半小时槽，不允许城市群"
        "均值回退。该包本身仍不授权正式搜索。\n",
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
