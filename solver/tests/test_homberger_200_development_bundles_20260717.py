from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "baselines/e2_alns/build_homberger_200_development_bundles_20260717.py"


def _module():
    spec = importlib.util.spec_from_file_location("homberger_bundle_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_frozen_output_is_zero_search_and_development_only() -> None:
    module = _module()
    decision = json.loads((module.DEFAULT_OUTPUT / "decision.json").read_text(encoding="utf-8"))
    manifest = json.loads((module.DEFAULT_OUTPUT / "manifest.json").read_text(encoding="utf-8"))
    assert decision["verdict"] == "PASS_HOMBERGER_200_DEVELOPMENT_BUNDLE_GATE"
    assert decision["formal_search_authorized"] is False
    assert decision["search_evaluations"] == 0
    assert manifest["role"] == "algorithm-development-only"
    assert manifest["search_performed"] is False
    assert manifest["reference_results_materialized"] is False
    assert manifest["bundle_count"] == 12


def test_all_12_bundles_load_and_preserve_double_precision() -> None:
    module = _module()
    with (module.DEFAULT_OUTPUT / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["instance"] for row in rows} == set(module.SOURCE_AUDIT.SELECTED)
    assert len(rows) == 12
    assert all(row["customers"] == "200" for row in rows)
    assert all(row["max_vehicles"] == "50" for row in rows)
    assert all(row["source_gate_pass"] == "1" for row in rows)
    assert all(row["generic_loader_match"] == "1" for row in rows)
    assert all(row["search_evaluations"] == "0" for row in rows)
    for row in rows:
        bundle = module.DEFAULT_OUTPUT / row["instance"]
        raw = json.loads((bundle / "instance.json").read_text(encoding="utf-8"))
        assert "bks" not in json.dumps(raw, ensure_ascii=False).lower()
        loaded = module.load_search_bundle(bundle).instance
        matrix = np.load(bundle / "distance_matrix.npy")
        assert len(loaded.nodes) == 201
        assert np.asarray(loaded.distance_matrix).shape == (201, 201)
        assert np.allclose(np.asarray(loaded.distance_matrix), matrix, atol=module.TOL, rtol=0)


def test_artifact_manifest_and_appledouble_close() -> None:
    module = _module()
    hashes = json.loads((module.DEFAULT_OUTPUT / "artifact_hashes.json").read_text(encoding="utf-8"))
    for label, expected in hashes.items():
        path = module.DEFAULT_OUTPUT / label
        if not path.is_file():
            path = REPO / label
        assert path.is_file(), label
        assert module.sha256(path) == expected, label
    assert not list(module.DEFAULT_OUTPUT.rglob("._*"))


def test_builder_refuses_nonempty_output(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "occupied"
    output.mkdir()
    (output / "keep.txt").write_text("user-owned", encoding="utf-8")
    try:
        module.build(module.DEFAULT_SNAPSHOT, module.DEFAULT_SOURCE_GATE, output)
    except module.BundleGateError as exc:
        assert "refuse to overwrite" in str(exc)
    else:
        raise AssertionError("builder should refuse to overwrite a non-empty output")
