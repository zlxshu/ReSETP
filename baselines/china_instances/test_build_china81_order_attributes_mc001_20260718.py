from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parent
    / "build_china81_order_attributes_mc001_20260718.py"
)
SPEC = importlib.util.spec_from_file_location("china81_mc001_order_builder", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_order_seed_is_stable_and_instance_specific() -> None:
    contract_hash = "a" * 64
    first = MODULE.order_seed("cn-jjj-10c-01-V2-LOCATIONS", contract_hash)
    assert first == MODULE.order_seed(
        "cn-jjj-10c-01-V2-LOCATIONS", contract_hash
    )
    assert first != MODULE.order_seed(
        "cn-jjj-10c-02-V2-LOCATIONS", contract_hash
    )


def test_approved_source_rows_and_locations_are_frozen() -> None:
    contract = MODULE.json.loads(MODULE.CONTRACT.read_text(encoding="utf-8"))
    assert (
        MODULE.sha256(MODULE.SOURCE_ROWS)
        == contract["calibration_evidence"]["empirical_rows_sha256"]
    )
    decision = MODULE.json.loads(
        (MODULE.LOCATIONS / "decision.json").read_text(encoding="utf-8")
    )
    assert decision["verdict"] == "PASS_81_DISJOINT_LOCATION_ASSIGNMENTS_BUILT"
