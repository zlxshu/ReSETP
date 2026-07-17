from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "baselines/china_instances/replenish_china81_customer_pools_v2_20260718.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("replenish", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_expansion_doubles_total_span_and_uses_four_original_area_tiles() -> None:
    box = {"south": 10.0, "west": 20.0, "north": 12.0, "east": 24.0, "city": "x"}
    tiles = MODULE.expanded_tiles(box)
    assert set(tiles) == {"sw", "se", "nw", "ne"}
    assert min(tile["south"] for tile in tiles.values()) == 9.0
    assert max(tile["north"] for tile in tiles.values()) == 13.0
    assert min(tile["west"] for tile in tiles.values()) == 18.0
    assert max(tile["east"] for tile in tiles.values()) == 26.0
    for tile in tiles.values():
        assert tile["north"] - tile["south"] == 2.0
        assert tile["east"] - tile["west"] == 4.0


def test_replenishment_scope_is_only_the_two_shortfall_cities() -> None:
    assert MODULE.CITIES == ("shijiazhuang", "chongqing")
    assert MODULE.BOX_SCALE == 2.0
