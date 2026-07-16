from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "baselines/e2_alns/audit_homberger_200_source_gate_20260717.py"


def _module():
    spec = importlib.util.spec_from_file_location("homberger_source_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parser_accepts_minimal_integer_instance() -> None:
    module = _module()
    payload = b"""C1_2_1

VEHICLE
NUMBER     CAPACITY
  50          200

CUSTOMER
CUST NO.  XCOORD. YCOORD. DEMAND READY TIME DUE DATE SERVICE TIME
    0      70      70       0      0        1351       0
    1      33      78      20    750         809      90
"""
    instance = module.parse_instance(payload)
    assert instance.name == "C1_2_1"
    assert instance.vehicle_limit == 50
    assert instance.capacity == 200
    assert [node.idx for node in instance.nodes] == [0, 1]


def test_frozen_source_and_decision_are_bks_free() -> None:
    module = _module()
    snapshot = module.DEFAULT_SNAPSHOT
    output = module.DEFAULT_OUTPUT
    archive = snapshot / "homberger_200_customer_instances.zip"
    assert module.sha256_path(archive) == module.EXPECTED_ARCHIVE_SHA256
    provenance = json.loads((snapshot / "source_provenance.json").read_text(encoding="utf-8"))
    manifest = json.loads((snapshot / "selected_instance_manifest.json").read_text(encoding="utf-8"))
    decision = json.loads((output / "decision.json").read_text(encoding="utf-8"))
    assert provenance["contains_bks_values"] is False
    assert provenance["contains_detailed_solution_routes"] is False
    assert manifest["bks_materialized"] is False
    assert decision["bks_materialized"] is False
    assert decision["verdict"] == "PASS_HOMBERGER_200_ZERO_SEARCH_SOURCE_GATE"


def test_all_12_rows_have_exact_structure_and_zero_search() -> None:
    module = _module()
    with (module.DEFAULT_OUTPUT / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["instance"] for row in rows} == set(module.SELECTED)
    assert len(rows) == 12
    assert all(row["customer_count"] == "200" for row in rows)
    assert all(row["node_count"] == "201" for row in rows)
    assert all(row["vehicle_limit"] == "50" for row in rows)
    assert all(row["ids_contiguous_0_200"] == "1" for row in rows)
    assert all(row["tw_order_violation_count"] == "0" for row in rows)
    assert all(row["source_gate_pass"] == "1" for row in rows)
    assert all(row["search_evaluations"] == "0" for row in rows)
    assert not any("bks" in key.lower() for key in rows[0])


def test_artifact_hashes_and_appledouble_contract() -> None:
    module = _module()
    output = module.DEFAULT_OUTPUT
    artifact_hashes = json.loads((output / "artifact_hashes.json").read_text(encoding="utf-8"))
    for label, expected in artifact_hashes.items():
        path = output / label
        if not path.is_file():
            path = REPO / label
        assert path.is_file(), label
        assert module.sha256_path(path) == expected, label
    assert not list(module.DEFAULT_SNAPSHOT.rglob("._*"))
    assert not list(output.rglob("._*"))
