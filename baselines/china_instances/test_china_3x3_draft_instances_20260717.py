from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "data" / "ChinaInstances" / "C31_DRAFT_20260717_osm_map_api_grid"


def test_nine_draft_bundles_are_explicitly_nonformal_and_structurally_gated() -> None:
    manifest = json.loads((ROOT / "build_manifest.json").read_text(encoding="utf-8"))
    assert manifest["draft_only"] is True
    assert manifest["formal_experiment_authorized"] is False
    assert manifest["search_evaluations"] == 0
    assert len(manifest["results"]) == 9
    assert not manifest["failures"]
    expected = {f"c31-{region}-{size}c-01-DRAFT" for region in ("jjj", "prd", "cy") for size in (50, 100, 200)}
    assert {Path(row["bundle"]).name for row in manifest["results"]} == expected
    for row in manifest["results"]:
        assert row["pass"] is True
        assert row["depots"] >= 2
        assert row["stations"] >= 1
        assert row["customers"] in {50, 100, 200}
