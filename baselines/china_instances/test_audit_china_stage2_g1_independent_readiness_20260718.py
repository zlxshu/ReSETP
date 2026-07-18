from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).with_name(
        "audit_china_stage2_g1_independent_readiness_20260718.py"
    )
)
SPEC = importlib.util.spec_from_file_location("readiness", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_formal_merge_is_always_held_before_g1_freeze() -> None:
    rows = {row["id"]: row for row in MODULE.build_items()}
    assert rows["G1-FREEZE-MERGE"]["state"] == "HELD_BY_DESIGN"
    assert rows["G1-FREEZE-MERGE"]["blocks_formal_acceptance"] is True


def test_result_blind_numeric_effects_are_frozen() -> None:
    rows = {row["id"]: row for row in MODULE.build_items()}
    assert rows["STATS-E5-MATERIAL-EFFECT"]["state"] == "PASS"
    assert rows["STATS-E7-MATERIAL-EFFECTS"]["state"] == "PASS"


def test_finished_location_and_order_layers_pass() -> None:
    rows = {row["id"]: row for row in MODULE.build_items()}
    assert rows["DATA-LOCATIONS"]["state"] == "PASS"
    assert rows["DATA-ORDERS"]["state"] == "PASS"
