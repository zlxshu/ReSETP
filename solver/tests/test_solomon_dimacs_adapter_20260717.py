from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import numpy as np


ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = load_script(
    "test_solomon_dimacs_audit",
    "baselines/e2_alns/audit_solomon_dimacs_adapter_20260717.py",
)
builder = load_script(
    "test_solomon_dimacs_builder",
    "baselines/e2_alns/build_solomon_dimacs_bundles_20260717.py",
)


def test_zero_search_audit_covers_all_six_families() -> None:
    root = ROOT / "baselines/e2_alns/e2_solomon_dimacs_adapter_20260717"
    decision = json.loads((root / "decision.json").read_text(encoding="utf-8"))
    with (root / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert decision["verdict"] == "PASS_SOLOMON_DIMACS_ZERO_SEARCH_ADAPTER_GATE"
    assert len(rows) == 56
    assert {row["class"] for row in rows} == {"C1", "C2", "R1", "R2", "RC1", "RC2"}
    assert all(row["optimal_flag"] == "1" for row in rows)
    assert all(row["search_evaluations"] == "0" for row in rows)


def test_dimacs_distance_is_truncated_not_rounded() -> None:
    left = audit.Node(0, 0, 0, 0, 0, 1, 0)
    right = audit.Node(1, 1, 1, 0, 0, 1, 0)
    assert audit.truncated_distance(left, right) == 1.4


def test_c101_source_parser_keeps_time_window_semantics() -> None:
    with ZipFile(builder.DEFAULT_ZIP) as archive:
        data = archive.read("In/c101.txt")
    name, max_vehicles, capacity, nodes = audit.parse_instance(data)
    assert (name, max_vehicles, capacity, len(nodes)) == ("C101", 25, 200, 101)
    assert nodes[1] == audit.Node(1, 45, 68, 10, 912, 967, 90)


def test_all_generated_bundles_roundtrip_through_generic_loader() -> None:
    root = builder.DEFAULT_OUTPUT
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    decision = json.loads((root / "decision.json").read_text(encoding="utf-8"))
    assert decision["verdict"] == "PASS_SOLOMON_DIMACS_BUNDLE_GATE"
    assert manifest["bundle_count"] == 56
    assert manifest["search_performed"] is False
    assert all(row["generic_loader_match"] == 1 for row in manifest["rows"])
    for row in manifest["rows"]:
        bundle = builder.load_search_bundle(root / row["instance"]).instance
        matrix = np.asarray(bundle.distance_matrix, dtype=float)
        assert matrix.shape == (101, 101)
        assert bundle.num_cv == row["max_vehicles"]
        assert bundle.num_ev == 0
