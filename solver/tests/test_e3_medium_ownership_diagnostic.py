from __future__ import annotations

import csv
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baselines.e3_ablation.e3_medium_ownership_diagnostic_20260715 import (  # noqa: E402
    OWNERSHIP_ROOT,
    RestorePair,
    build_medium_maps,
    select_restored_pairs,
)


def _owners(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["customer_id"]: row["owner_depot_id"] for row in csv.DictReader(handle)}


def test_restoration_selector_is_deterministic_and_uses_pairs() -> None:
    pairs = [
        RestorePair((0, 0), "C001", "C002", 10.0, 2.0),
        RestorePair((0, 0), "C003", "C004", 30.0, -2.0),
        RestorePair((1, 0), "C005", "C006", 20.0, 1.0),
        RestorePair((1, 0), "C007", "C008", 40.0, -1.0),
    ]
    first = select_restored_pairs(
        pairs,
        mixed_d0_demand=100.0,
        geographic_d0_demand=100.0,
        max_absolute_demand_drift=10.0,
    )
    second = select_restored_pairs(
        pairs,
        mixed_d0_demand=100.0,
        geographic_d0_demand=100.0,
        max_absolute_demand_drift=10.0,
    )
    assert first == second
    assert len(first) == 2
    assert sum(pairs[index].removed_mismatch_numerator for index in first) == 50.0


def test_formal_medium_maps_preserve_block_counts_and_are_repeatable(tmp_path: Path) -> None:
    out_one = tmp_path / "one"
    out_two = tmp_path / "two"
    structures_one, _, hashes_one = build_medium_maps(out_one)
    structures_two, _, hashes_two = build_medium_maps(out_two)

    assert len(hashes_one) == len(hashes_two) == 9
    assert sorted(hashes_one.values()) == sorted(hashes_two.values())
    checks = [row for row in structures_one if row["condition"] == "medium_generation_check"]
    assert len(checks) == 9
    for row in checks:
        assert abs(float(row["medium_minus_target"])) <= 0.05 * float(row["mixed_index"]) + 1e-12
        available = int(row["available_pair_count"])
        restored = int(row["restored_pair_count"])
        assert restored in {available // 2, (available + 1) // 2}

    instance = "L-main-threeshift-200c-01"
    geographic = _owners(OWNERSHIP_ROOT / "ownership_maps" / f"{instance}__geographic.csv")
    medium = _owners(out_one / "ownership_maps" / f"{instance}__medium.csv")
    mixed = _owners(OWNERSHIP_ROOT / "ownership_maps" / f"{instance}__mixed.csv")
    assert set(geographic) == set(medium) == set(mixed)
    assert medium != geographic
    assert medium != mixed


def test_fallback_preview_keeps_original_observation_separate() -> None:
    fixed_cost = 100.0
    observed_shared_cost = 106.0
    fallback_cost = min(fixed_cost, observed_shared_cost)
    original_observed_saving = (fixed_cost - observed_shared_cost) / fixed_cost * 100.0
    fallback_preview_saving = (fixed_cost - fallback_cost) / fixed_cost * 100.0
    assert original_observed_saving == -6.0
    assert fallback_preview_saving == 0.0
