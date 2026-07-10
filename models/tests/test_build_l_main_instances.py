from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest


EXPECTED_SOURCE_SCALES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
EXPECTED_MERGED_COUNTS = (22, 34, 45, 55, 114, 163, 221, 322, 449)


def _load_builder():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "models" / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "build_e2_benchmark_instances_for_lmain_test",
        scripts_dir / "build_e2_benchmark_instances.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load L-main builder")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_lmain_cli():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "models" / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location("build_l_main_instances_for_test", scripts_dir / "build_l_main_instances.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load L-main CLI")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_lmain_audit():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "models" / "scripts"
    spec = importlib.util.spec_from_file_location("audit_l_main_v3_for_test", scripts_dir / "audit_l_main_v3.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load L-main audit")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_full_source_10c_preserves_all_three_sources_and_only_cuts_third_tail(tmp_path: Path) -> None:
    builder = _load_builder()
    raw_index = builder._raw_inventory()
    output_dir = tmp_path / "L-main-threeshift-10c-01"

    row = builder.build_full_source_threeshift(
        raw_index,
        10,
        "01",
        "L-main-threeshift-10c-01",
        output_dir,
    )

    assert row.n_customers_actual == 22
    assert row.three_shift_per_shift_counts == [10, 10, 2]
    manifest = json.loads((output_dir / "three_shift_manifest.json").read_text(encoding="utf-8"))
    assert [child["source_base_id"] for child in manifest["source_children"]] == ["E-UK10_01", "E-UK10_02", "E-UK10_03"]
    assert [child["input_customer_count"] for child in manifest["source_children"]] == [10, 10, 10]
    assert [child["kept_customer_count"] for child in manifest["source_children"]] == [10, 10, 2]
    assert [child["deleted_customer_count"] for child in manifest["source_children"]] == [0, 0, 8]
    assert {item["shift_seconds"] for item in manifest["deleted_customers"]} == {64800.0}
    assert all(item["shifted_due_time"] > 86400.0 for item in manifest["deleted_customers"])
    assert all(item["shifted_due_time"] <= 86400.0 for item in manifest["kept_customers"])


def test_formal_builder_never_calls_historical_count_planner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder = _load_builder()
    raw_index = builder._raw_inventory()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("formal L-main path must not call _choose_child_counts")

    monkeypatch.setattr(builder, "_choose_child_counts", fail_if_called)
    row = builder.build_full_source_threeshift(
        raw_index,
        10,
        "01",
        "L-main-threeshift-10c-01",
        tmp_path / "bundle",
    )
    assert row.n_customers_actual == 22


def test_nine_source_scales_have_locked_natural_24h_counts_and_shared_multidepot_layout(tmp_path: Path) -> None:
    builder = _load_builder()
    raw_index = builder._raw_inventory()
    actual_counts: list[int] = []

    for scale in EXPECTED_SOURCE_SCALES:
        instance_id = f"L-main-threeshift-{scale}c-01"
        output_dir = tmp_path / instance_id
        row = builder.build_full_source_threeshift(raw_index, scale, "01", instance_id, output_dir)
        actual_counts.append(row.n_customers_actual)
        manifest = json.loads((output_dir / "three_shift_manifest.json").read_text(encoding="utf-8"))
        assert manifest["source_scale"] == scale
        assert manifest["merged_customer_count"] == row.n_customers_actual
        assert manifest["source_children"][2]["kept_customer_count"] >= 1

        instance = json.loads((output_dir / "instance.json").read_text(encoding="utf-8"))
        depots = [node for node in instance["nodes"] if node["node_type"] == "d"]
        assert [node["node_id"] for node in depots] == ["D0", "D1"]
        raw_d0 = next(node for node in raw_index[f"E-UK{scale}_01"].nodes if node.node_type == "d")
        assert (depots[0]["x"], depots[0]["y"]) == (raw_d0.x, raw_d0.y)
        assert {node["station_chargers"] for node in depots} == {row.n_customers_actual}

        matrix = np.load(output_dir / "distance_matrix.npy")
        coordinates = np.asarray([(node["x"], node["y"]) for node in instance["nodes"]], dtype=float)
        assert np.allclose(matrix, builder._distance_matrix_from_coordinates(coordinates))

        carbon = (output_dir / "carbon_profile.csv").read_text(encoding="utf-8").splitlines()
        assert len(carbon) == 49
        starts = [int(line.rsplit(",", 1)[1]) for line in carbon[1:]]
        assert starts == list(range(0, 86400, 1800))

    assert actual_counts == list(EXPECTED_MERGED_COUNTS)


def test_d1_is_deterministic_for_same_full_source_request(tmp_path: Path) -> None:
    builder = _load_builder()
    raw_index = builder._raw_inventory()
    d1_locations = []
    for suffix in ("a", "b"):
        output_dir = tmp_path / suffix
        builder.build_full_source_threeshift(raw_index, 50, "01", "L-main-threeshift-50c-01", output_dir)
        nodes = json.loads((output_dir / "instance.json").read_text(encoding="utf-8"))["nodes"]
        d1 = next(node for node in nodes if node["node_id"] == "D1")
        d1_locations.append((d1["x"], d1["y"]))
    assert d1_locations[0] == d1_locations[1]


def test_candidate_cli_writes_v3_manifest_and_rejects_active_directory(tmp_path: Path) -> None:
    cli = _load_lmain_cli()
    candidate = tmp_path / "candidate"
    manifest = cli.build_l_main_instances(candidate)

    assert manifest["schema_version"] == "resetp-l-main-main-benchmark.v3"
    assert manifest["source_scales"] == list(EXPECTED_SOURCE_SCALES)
    assert [item["merged_customer_count"] for item in manifest["instances"]] == list(EXPECTED_MERGED_COUNTS)
    assert all(item["carbon_slot_count"] == 48 for item in manifest["instances"])
    assert all(item["depot_ids"] == ["D0", "D1"] for item in manifest["instances"])
    assert (candidate / cli.MANIFEST_NAME).is_file()

    with pytest.raises(ValueError, match="refusing to write active"):
        cli.build_l_main_instances(cli.ACTIVE_ROOT)


def test_manifest_hashes_exclude_appledouble_sidecars(tmp_path: Path) -> None:
    builder = _load_builder()
    cli = _load_lmain_cli()
    raw_index = builder._raw_inventory()
    bundle_dir = tmp_path / "L-main-threeshift-10c-01"
    row = builder.build_full_source_threeshift(raw_index, 10, "01", "L-main-threeshift-10c-01", bundle_dir)
    (bundle_dir / "._instance.json").write_bytes(b"appledouble-noise")

    record = cli._instance_record(bundle_dir, row, raw_index, 10, "01")

    assert all(not name.startswith("._") for name in record["bundle_file_hashes"])


def test_audit_emits_ready_decision_and_required_record_surfaces(tmp_path: Path) -> None:
    cli = _load_lmain_cli()
    audit = _load_lmain_audit()
    candidate = tmp_path / "candidate"
    output = tmp_path / "audit"
    cli.build_l_main_instances(candidate)
    decision = audit.audit_l_main_v3(candidate, output)

    assert decision["verdict"] == "LMAIN_V3_READY", decision
    for name in ("metadata.json", "raw_runs.csv", "decision.json", "artifact_hashes.json", "report.md"):
        assert (output / name).is_file()


def test_audit_output_hashes_exclude_appledouble_sidecars(tmp_path: Path) -> None:
    _load_lmain_cli()
    audit = _load_lmain_audit()
    output = tmp_path / "audit"
    output.mkdir()
    (output / "._decision.json").write_bytes(b"appledouble-noise")
    decision = {
        "candidate_root": str(tmp_path / "candidate"),
        "verdict": "HALT_LMAIN_V3_AUDIT",
        "failure_count": 1,
        "instances": [],
    }

    audit._write_outputs(output, decision)

    hashes = json.loads((output / "artifact_hashes.json").read_text(encoding="utf-8"))
    assert all(not name.startswith("._") for name in hashes)


def test_audit_rejects_appledouble_entries_in_manifest(tmp_path: Path) -> None:
    builder = _load_builder()
    cli = _load_lmain_cli()
    audit = _load_lmain_audit()
    candidate = tmp_path / "candidate"
    output = tmp_path / "audit"
    bundle_dir = candidate / "L-main-threeshift-10c-01"
    raw_index = builder._raw_inventory()
    row = builder.build_full_source_threeshift(raw_index, 10, "01", "L-main-threeshift-10c-01", bundle_dir)
    entry = cli._instance_record(bundle_dir, row, raw_index, 10, "01")
    manifest = {
        "schema_version": "resetp-l-main-main-benchmark.v3",
        "source_scales": list(EXPECTED_SOURCE_SCALES),
        "instances": [entry],
    }
    candidate.mkdir(parents=True, exist_ok=True)
    sidecar = bundle_dir / "._instance.json"
    sidecar.write_bytes(b"appledouble-noise")
    entry["bundle_file_hashes"][sidecar.name] = cli.sha256_file(sidecar)
    (candidate / cli.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    decision = audit.audit_l_main_v3(candidate, output)

    assert decision["verdict"] == "HALT_LMAIN_V3_AUDIT"
    assert any("appledouble" in failure for failure in decision["failures"])


def test_audit_rejects_deleted_customer_with_wrong_reason(tmp_path: Path) -> None:
    builder = _load_builder()
    cli = _load_lmain_cli()
    audit = _load_lmain_audit()
    candidate = tmp_path / "candidate"
    output = tmp_path / "audit"
    bundle_dir = candidate / "L-main-threeshift-10c-01"
    raw_index = builder._raw_inventory()
    row = builder.build_full_source_threeshift(raw_index, 10, "01", "L-main-threeshift-10c-01", bundle_dir)
    three_path = bundle_dir / "three_shift_manifest.json"
    three = json.loads(three_path.read_text(encoding="utf-8"))
    three["deleted_customers"][0]["reason"] = "count_target_trim"
    three_path.write_text(json.dumps(three), encoding="utf-8")
    entry = cli._instance_record(bundle_dir, row, raw_index, 10, "01")
    manifest = {
        "schema_version": "resetp-l-main-main-benchmark.v3",
        "source_scales": list(EXPECTED_SOURCE_SCALES),
        "instances": [entry],
    }
    (candidate / cli.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    decision = audit.audit_l_main_v3(candidate, output)

    assert any("invalid_deletion_reason" in failure for failure in decision["failures"])


def test_audit_rejects_wrong_shared_facility_source(tmp_path: Path) -> None:
    builder = _load_builder()
    cli = _load_lmain_cli()
    audit = _load_lmain_audit()
    candidate = tmp_path / "candidate"
    output = tmp_path / "audit"
    bundle_dir = candidate / "L-main-threeshift-10c-01"
    raw_index = builder._raw_inventory()
    row = builder.build_full_source_threeshift(raw_index, 10, "01", "L-main-threeshift-10c-01", bundle_dir)
    three_path = bundle_dir / "three_shift_manifest.json"
    three = json.loads(three_path.read_text(encoding="utf-8"))
    three["facility_layout_source"] = "unrelated-layout"
    three_path.write_text(json.dumps(three), encoding="utf-8")
    entry = cli._instance_record(bundle_dir, row, raw_index, 10, "01")
    manifest = {
        "schema_version": "resetp-l-main-main-benchmark.v3",
        "source_scales": list(EXPECTED_SOURCE_SCALES),
        "instances": [entry],
    }
    (candidate / cli.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    decision = audit.audit_l_main_v3(candidate, output)

    assert any("shared_facility_layout" in failure for failure in decision["failures"])
