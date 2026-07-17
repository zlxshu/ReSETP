from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "data/ChinaInstances/china81_customer_location_assignments_v2_20260718"
CONTRACT = json.loads((REPO / "data/ChinaInstances/china_customer_location_contract_v2_20260718.json").read_text(encoding="utf-8"))


def rows(name: str) -> list[dict[str, str]]:
    with (ROOT / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_assignment_package_has_exactly_81_instances_and_5805_rows() -> None:
    decision = json.loads((ROOT / "decision.json").read_text(encoding="utf-8"))
    assert decision["verdict"] == "PASS_81_DISJOINT_LOCATION_ASSIGNMENTS_BUILT"
    assert decision["instances"] == 81
    assert decision["assignment_rows"] == 5805
    assert decision["search_evaluations"] == 0
    assert len(rows("instance_catalog.csv")) == 81
    assert len(rows("assignments.csv")) == 5805


def test_every_cell_has_three_zero_overlap_replicates_and_frozen_city_quotas() -> None:
    assignments = rows("assignments.csv")
    for region, size_table in CONTRACT["city_quotas"].items():
        for size, quotas in size_table.items():
            cell = [row for row in assignments if row["region"] == region and row["customer_size"] == size]
            identities = [(row["osm_type"], row["osm_id"]) for row in cell]
            assert len(cell) == 3 * int(size)
            assert len(set(identities)) == len(identities)
            for replicate in CONTRACT["replicate_labels"]:
                instance = [row for row in cell if row["replicate"] == replicate]
                assert len(instance) == int(size)
                assert Counter(row["city"] for row in instance) == Counter({city: int(quota) for city, quota in quotas.items()})


def test_selected_rows_keep_valid_coordinates_and_source_hashes() -> None:
    checked: dict[str, str] = {}
    for row in rows("assignments.csv"):
        assert -90 <= float(row["latitude"]) <= 90
        assert -180 <= float(row["longitude"]) <= 180
        path = REPO / row["source_response_path"]
        assert path.is_file(), path
        checked.setdefault(str(path), digest(path))
        assert checked[str(path)] == row["source_response_sha256"]


def test_artifact_hashes_recompute() -> None:
    manifest = json.loads((ROOT / "artifact_hashes.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["files"].items():
        assert digest(REPO / relative) == expected
