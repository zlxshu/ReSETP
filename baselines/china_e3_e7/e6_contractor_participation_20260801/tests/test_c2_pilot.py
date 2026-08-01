from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
for path in (HERE, REPO / "solver/src", REPO):
    sys.path.insert(0, str(path))

from run_c2_pilot import build_evidence


def test_scattered_original_fleet_hits_registered_stop() -> None:
    metadata, rows, decision = build_evidence()
    assert metadata["same_city_or_nearest_owner_used"] is False
    assert len(rows) == 40
    assert decision["blocked_singletons"] == {
        "Uniform_Balanced": ["D_dongguan", "D_foshan"],
        "Uniform_Unbalanced": ["D_dongguan", "D_foshan"],
    }
    balanced = decision["family_details"]["Uniform_Balanced"]["owners"]
    unbalanced = decision["family_details"]["Uniform_Unbalanced"]["owners"]
    assert balanced["D_dongguan"]["capacity_route_lower_bound"] == 6
    assert unbalanced["D_dongguan"]["capacity_route_lower_bound"] == 10
    assert not any(row["route_search_executed"] for row in rows)
