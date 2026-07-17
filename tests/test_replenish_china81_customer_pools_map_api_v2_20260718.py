from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "baselines/china_instances/replenish_china81_customer_pools_map_api_v2_20260718.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("map_replenish", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_grid_is_fixed_four_by_four_over_doubled_box() -> None:
    result = MODULE.tiles({"south": 10, "west": 20, "north": 12, "east": 24})
    assert len(result) == 16
    assert min(tile["south"] for tile in result.values()) == 9
    assert max(tile["north"] for tile in result.values()) == 13
    assert min(tile["west"] for tile in result.values()) == 18
    assert max(tile["east"] for tile in result.values()) == 26


def test_parser_keeps_named_customer_nodes_and_ways(tmp_path: Path) -> None:
    raw = tmp_path / "sample.osm"
    raw.write_text(
        """<osm version="0.6">
<node id="1" lat="1" lon="2"><tag k="name" v="店A"/><tag k="shop" v="convenience"/></node>
<node id="2" lat="1" lon="3"/><node id="3" lat="2" lon="3"/>
<way id="4"><nd ref="2"/><nd ref="3"/><tag k="name" v="店B"/><tag k="office" v="company"/></way>
<node id="5" lat="4" lon="5"><tag k="shop" v="yes"/></node>
</osm>\n""",
        encoding="utf-8",
    )
    rows = MODULE.parse_customers(raw, "shijiazhuang")
    assert {(row["osm_type"], row["osm_id"]) for row in rows} == {("node", "1"), ("way", "4")}
