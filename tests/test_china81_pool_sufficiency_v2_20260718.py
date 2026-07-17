from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "baselines/china_instances/audit_china81_pool_sufficiency_v2_20260718.py"
SPEC = importlib.util.spec_from_file_location("pool_gate", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_contract_is_exactly_9_by_3_by_3() -> None:
    contract = json.loads(MODULE.CONTRACT.read_text(encoding="utf-8"))
    assert contract["customer_sizes"] == [10, 15, 20, 25, 50, 75, 100, 150, 200]
    assert set(contract["city_quotas"]) == {"jjj", "prd", "cy"}
    assert contract["replicates_per_region_size"] == 3
    assert contract["replicate_labels"] == ["01", "02", "03"]
    assert contract["within_cell_identity_overlap_allowed"] is False
    assert sum(len(table) for table in contract["city_quotas"].values()) == 27
    for table in contract["city_quotas"].values():
        for size, quotas in table.items():
            assert sum(quotas.values()) == int(size)


def test_gate_requires_three_times_each_city_quota(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    pools = pool / "pools"
    pools.mkdir(parents=True)
    (pool / "decision.json").write_text('{"verdict":"PASS_P1_FULL_POOL_EXTRACTED"}\n', encoding="utf-8")
    contract = json.loads(MODULE.CONTRACT.read_text(encoding="utf-8"))
    maxima: dict[str, int] = {}
    for table in contract["city_quotas"].values():
        for quotas in table.values():
            for city, quota in quotas.items():
                maxima[city] = max(maxima.get(city, 0), 3 * quota)
    for city, count in maxima.items():
        with (pools / f"{city}__named_poi.csv").open("w", encoding="utf-8") as handle:
            handle.write("osm_type,osm_id\n")
            handle.writelines(f"node,{city}_{index}\n" for index in range(count))
    decision = MODULE.audit(pool, tmp_path / "out")
    assert decision["verdict"] == "PASS_81_MUTUAL_EXCLUSIVITY_POOL_GATE"
    assert decision["region_size_cells_passed"] == 27
    assert all(count == 0 for count in decision["cross_city_identity_overlaps"].values())


def test_gate_halts_one_identity_short(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    pools = pool / "pools"
    pools.mkdir(parents=True)
    (pool / "decision.json").write_text('{"verdict":"PASS_P1_FULL_POOL_EXTRACTED"}\n', encoding="utf-8")
    with (pools / "beijing__named_poi.csv").open("w", encoding="utf-8") as handle:
        handle.write("osm_type,osm_id\n")
        handle.writelines(f"node,{index}\n" for index in range(389))
    decision = MODULE.audit(pool, tmp_path / "out")
    assert decision["verdict"] == "HALT_81_POOL_INSUFFICIENT_OR_INCOMPLETE"
    assert "jjj/200" in decision["failed_cells"]
