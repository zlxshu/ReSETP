from __future__ import annotations

import csv
import importlib.util
import json
import math
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
    "test_solomon_sintef_audit",
    "baselines/e2_alns/audit_solomon_sintef_bks_20260717.py",
)
builder = load_script(
    "test_solomon_sintef_builder",
    "baselines/e2_alns/build_solomon_sintef_bundles_20260717.py",
)


def test_sintef_bks_audit_covers_all_instances_without_search() -> None:
    root = ROOT / "baselines/e2_alns/e2_solomon_sintef_bks_audit_20260717"
    decision = json.loads((root / "decision.json").read_text(encoding="utf-8"))
    with (root / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert decision["verdict"] == "PASS_SOLOMON_SINTEF_BKS_ZERO_SEARCH_AUDIT"
    assert decision["search_evaluations"] == 0
    assert len(rows) == 56
    assert all(row["vehicle_match"] == "1" for row in rows)
    assert all(row["distance_match"] == "1" for row in rows)
    assert all(row["solution_feasible"] == "1" for row in rows)


def test_sintef_distance_uses_double_precision_not_dimacs_truncation() -> None:
    left = audit.Node(0, 0, 0, 0, 0, 10, 0)
    right = audit.Node(1, 1, 1, 0, 0, 10, 0)
    assert audit.distance(left, right) == math.sqrt(2)
    assert audit.distance(left, right) != 1.4


def test_c101_detailed_solution_recomputes_published_bks() -> None:
    with ZipFile(builder.DEFAULT_ZIP) as archive:
        _, _, capacity, nodes = audit.parse_instance(archive.read("In/c101.txt"))
    routes = audit.parse_routes(audit.SOLUTIONS / "c101.txt")
    result = audit.recompute(routes, nodes, capacity)
    assert result["valid"] is True
    assert result["route_count"] == 10
    assert result["distance_rounded_2"] == "828.94"


def test_all_sintef_bundles_roundtrip_through_generic_loader() -> None:
    root = builder.DEFAULT_OUTPUT
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    decision = json.loads((root / "decision.json").read_text(encoding="utf-8"))
    assert decision["verdict"] == "PASS_SOLOMON_SINTEF_BUNDLE_GATE"
    assert manifest["bundle_count"] == 56
    assert manifest["search_performed"] is False
    assert all(row["generic_loader_match"] == 1 for row in manifest["rows"])
    assert manifest["search_facing_bundles_contain_bks"] is False
    search_payload = json.loads((root / "C101" / "instance.json").read_text(encoding="utf-8"))
    assert not any("bks" in key.lower() for key in search_payload["metadata"])
    assert "828.94" not in (root / "C101" / "instance.json").read_text(encoding="utf-8")
    c101 = builder.load_search_bundle(root / "C101").instance
    matrix = np.asarray(c101.distance_matrix, dtype=float)
    assert matrix.shape == (101, 101)
    assert matrix[0, 1] == math.hypot(40 - 45, 50 - 68)
    assert matrix[0, 1] != math.floor(10 * matrix[0, 1]) / 10
