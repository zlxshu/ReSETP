from __future__ import annotations

import csv
import json
from pathlib import Path

from setp_solver.china81 import (
    FLEET_AUTHORITY_V3_RELATIVE,
    load_china81_bundle,
)


REPO = Path(__file__).resolve().parents[2]
AUTHORITY = REPO / FLEET_AUTHORITY_V3_RELATIVE


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))




def test_v3_has_144_depot_rows_and_exact_hamilton_allocations() -> None:
    rows = read_csv(AUTHORITY / "fleet_caps.csv")
    assert len(rows) == 144
    assert sum(int(row["total_fleet_cap"]) for row in rows) == 943
    assert {row["depot_charger_capacity_default"] for row in rows} == {
        "UNBOUNDED"
    }
    assert {
        row["fleet_parameter_class"] for row in rows
    } == {"DERIVED_FIXED_TOTAL_MULTITRIP_ZERO_SEARCH_AUTHORITY"}
    for row in rows:
        levels = json.loads(row["fleet_level_allocations_json_metadata_only"])
        assert set(levels) == {"0", "25", "50", "75", "100"}
        for allocation in levels.values():
            assert allocation["num_cv"] + allocation["num_ev"] == int(
                row["total_fleet_cap"]
            )


def test_v3_zero_search_certifies_all_405_units_without_violations() -> None:
    rows = read_csv(AUTHORITY / "zero_search_certification.csv")
    assert len(rows) == 405
    assert {row["status"] for row in rows} == {"CERTIFIED"}
    assert sum(int(row["violation_count"]) for row in rows) == 0
    assert {row["route_search_executed"] for row in rows} == {"False"}
    assert {row["search_evaluations"] for row in rows} == {"0"}
    counts = {
        level: sum(
            row["target_ev_percent"] == level and row["status"] == "CERTIFIED"
            for row in rows
        )
        for level in ("0", "25", "50", "75", "100")
    }
    assert counts == {level: 81 for level in counts}


def test_v3_determinants_respect_endpoint_lower_bounds() -> None:
    determinants = read_csv(AUTHORITY / "fleet_determinants.csv")

    assert len(determinants) == 144
    assert all(
        int(row["selected_Td"]) >= int(row["endpoint_lower_Td"])
        for row in determinants
    )
