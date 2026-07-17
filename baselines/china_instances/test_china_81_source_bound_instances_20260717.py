from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "data" / "ChinaInstances" / "CHINA81_DRAFT_20260717_source_bound"
SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
REGIONS = ("jjj", "prd", "cy")
VARIANTS = ("01", "02", "03")
SHIFT_LABELS = {"00-08", "08-16", "16-24"}


def bundles() -> list[Path]:
    return sorted(path for path in ROOT.iterdir() if path.is_dir() and path.name.startswith("cn-"))


def test_china81_catalog_is_complete_and_search_free() -> None:
    assert len(bundles()) == 81
    decision = json.loads((ROOT / "decision.json").read_text(encoding="utf-8"))
    assert decision["decision"] == "DRAFT_SET_BUILT_NOT_AUTHORIZED_FOR_SEARCH"
    assert decision["formal_search_allowed"] is False
    assert decision["search_evaluations"] == 0
    assert decision["pass_count"] == 81


def test_each_bundle_has_exact_structure_source_mapping_and_valid_time_windows() -> None:
    expected_by_factor: defaultdict[tuple[str, int], set[str]] = defaultdict(set)
    for bundle in bundles():
        parts = bundle.name.split("-")
        region = parts[1]
        size = int(parts[2][:-1])
        depot_count = int(parts[3][:-1])
        variant = parts[4]
        expected_by_factor[(region, size)].add(variant)
        data = json.loads((bundle / "instance.json").read_text(encoding="utf-8"))
        metadata = data["metadata"]
        gate = json.loads((bundle / "structure_gate.json").read_text(encoding="utf-8"))
        assert gate["pass"] is True
        assert gate["search_evaluations"] == 0
        assert metadata["customer_count_actual"] == size
        assert metadata["n_depots"] == depot_count
        assert metadata["n_depots"] == (1 if size <= 25 else 2 if size <= 100 else 3)
        assert metadata["formal_experiment_authorized"] is False
        customers = [row for row in data["nodes"] if row["node_type"] == "c"]
        stations = [row for row in data["nodes"] if row["node_type"] == "f"]
        assert len(customers) == size
        assert stations
        assert {row["shift_label"] for row in customers} == SHIFT_LABELS
        for row in customers:
            assert 0 <= float(row["ready_time"]) < float(row["due_time"]) <= 86400
            assert 0 < float(row["service_time"]) <= float(row["due_time"]) - float(row["ready_time"])
        matrix = np.load(bundle / "distance_matrix.npy")
        assert matrix.shape == (len(data["nodes"]), len(data["nodes"]))
        assert np.allclose(matrix, matrix.T)
        assert np.allclose(np.diag(matrix), 0.0)
        assert len(json.loads((bundle / "source_manifest.json").read_text(encoding="utf-8"))["goeke_order_mapping"]) == size
        with (bundle / "nodes.csv").open(encoding="utf-8", newline="") as handle:
            assert len(list(csv.DictReader(handle))) == len(data["nodes"])
    assert set(expected_by_factor) == {(region, size) for region in REGIONS for size in SIZES}
    assert all(variants == set(VARIANTS) for variants in expected_by_factor.values())


def test_three_variants_use_different_real_customer_location_sets() -> None:
    fingerprints: defaultdict[tuple[str, int], set[tuple[tuple[str, str], ...]]] = defaultdict(set)
    for bundle in bundles():
        parts = bundle.name.split("-")
        key = (parts[1], int(parts[2][:-1]))
        with (bundle / "nodes.csv").open(encoding="utf-8", newline="") as handle:
            fingerprint = tuple(sorted((row["osm_type"], row["osm_id"]) for row in csv.DictReader(handle) if row["node_type"] == "c"))
        fingerprints[key].add(fingerprint)
    assert len(fingerprints) == 27
    assert all(len(values) == 3 for values in fingerprints.values())

