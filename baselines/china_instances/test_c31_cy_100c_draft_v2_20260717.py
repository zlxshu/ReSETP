from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "data" / "ChinaInstances" / "C31_DRAFT_20260717_osm_map_api_grid_v2"
BUNDLE = ROOT / "c31-cy-100c-01-DRAFT-v2"


def test_cy_100c_draft_v2_is_nonformal_and_meets_the_registered_structure_contract() -> None:
    decision = json.loads((ROOT / "decision.json").read_text(encoding="utf-8"))
    assert decision["draft_only"] is True
    assert decision["formal_experiment_authorized"] is False
    assert decision["search_evaluations"] == 0
    root_gate = json.loads((ROOT / "structure_gate.json").read_text(encoding="utf-8"))
    if decision["verdict"] == "PASS_DRAFT_STRUCTURE_GATE / NOT_READY_FOR_V2_FREEZE":
        gate = json.loads((BUNDLE / "structure_gate.json").read_text(encoding="utf-8"))
        assert gate["pass"] is True
        assert gate["customers"] == 100
        assert gate["depots"] == 2
        assert gate["stations"] >= 3
        assert gate["carbon_rows"] == 48
        assert 80.0 <= gate["coverage_radius_km"] <= 150.0
    else:
        assert decision["verdict"] == "HALT_C31_CY_100C_SELECTED_REAL_MAP_API_POOL_INSUFFICIENT"
        assert root_gate["pass"] is False
        assert root_gate["customers"] == 0
        assert root_gate["search_evaluations"] == 0
        assert not BUNDLE.exists()
