from pathlib import Path

import pytest

from dr_alns_ppo.bundle_manifest import build_manifest, load_manifest, validate_manifest, write_manifest


def test_build_manifest_has_disjoint_train_and_held_out_bundles() -> None:
    manifest = build_manifest()

    assert manifest["schema_version"] == "dr-alns-ppo-bundle-manifest.v1"
    assert set(manifest["train"]).isdisjoint(set(manifest["held_out"]))
    assert set(manifest["train"]).isdisjoint(set(manifest["formal_eval"]))
    assert set(manifest["held_out"]).isdisjoint(set(manifest["formal_eval"]))
    assert len(manifest["train"]) == 4
    assert len(manifest["held_out"]) == 1
    assert len(manifest["formal_eval"]) == 2
    assert "models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113" in manifest["held_out"]
    assert "models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113" in manifest["formal_eval"]
    assert "models/data_bundle/generated_instances/E-UK24h-三班-01" in manifest["formal_eval"]


def test_manifest_validation_checks_required_bundle_files(tmp_path: Path) -> None:
    manifest = {
        "schema_version": "dr-alns-ppo-bundle-manifest.v1",
        "train": ["bundle_a"],
        "held_out": ["bundle_b"],
        "formal_eval": [],
        "excluded_from_training_reason": {},
    }
    for bundle in ("bundle_a", "bundle_b"):
        path = tmp_path / bundle
        path.mkdir()
        (path / "instance.json").write_text("{}", encoding="utf-8")
        (path / "distance_matrix.npy").write_bytes(b"placeholder")

    with pytest.raises(FileNotFoundError, match="carbon_profile.csv"):
        validate_manifest(manifest, root=tmp_path)


def test_write_and_load_manifest_round_trip(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"

    written = write_manifest(output, root=Path.cwd())
    loaded = load_manifest(output, root=Path.cwd())

    assert loaded == written
