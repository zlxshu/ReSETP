from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name(
    "audit_china9_public_station_provenance_20260718.py"
)
SPEC = importlib.util.spec_from_file_location("station_audit", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_all_nine_cities_are_audited() -> None:
    rows = [MODULE.audit_city(city) for city in MODULE.CITIES]
    assert len(rows) == 9
    assert {row["city"] for row in rows} == set(MODULE.CITIES)


def test_osm_candidates_never_self_approve_formal_provenance() -> None:
    rows = [MODULE.audit_city(city) for city in MODULE.CITIES]
    assert all(row["formal_station_ready"] is False for row in rows)
