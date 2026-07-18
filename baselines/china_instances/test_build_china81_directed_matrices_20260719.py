from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).with_name(
    "build_china81_directed_matrices_20260718.py"
)
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("china81_matrices", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def complete_rows() -> list[dict]:
    return [
        {"region": region, "profile": profile, "status": "PASS"}
        for region in ("jjj", "prd", "cy")
        for profile in ("cv", "ev")
    ]


def test_complete_decision_requires_exact_batches_and_total() -> None:
    decision = MODULE.build_decision(
        complete_rows(), MODULE.EXPECTED_MATERIALIZED_ORDERED_PAIRS
    )
    assert decision["ordered_pairs_complete"] is True
    assert decision["verdict"].startswith("PASS_")


def test_incomplete_total_cannot_receive_pass_verdict() -> None:
    decision = MODULE.build_decision(
        complete_rows(), MODULE.EXPECTED_MATERIALIZED_ORDERED_PAIRS - 1
    )
    assert decision["ordered_pairs_complete"] is False
    assert decision["verdict"].startswith("HALT_")


def test_missing_batch_cannot_receive_pass_verdict() -> None:
    decision = MODULE.build_decision(
        complete_rows()[:-1], MODULE.EXPECTED_MATERIALIZED_ORDERED_PAIRS
    )
    assert decision["ordered_pairs_complete"] is False
    assert decision["verdict"].startswith("HALT_")
