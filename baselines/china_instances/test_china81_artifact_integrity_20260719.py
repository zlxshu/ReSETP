from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).with_name("china81_artifact_integrity_20260719.py")
SPEC = importlib.util.spec_from_file_location("china81_integrity", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_manifest(package: Path, entries: dict[str, str]) -> None:
    (package / "artifact_hashes.json").write_text(
        json.dumps({"sha256": entries}), encoding="utf-8"
    )


def test_valid_artifact_package_passes(tmp_path: Path) -> None:
    target = tmp_path / "result.txt"
    target.write_text("frozen", encoding="utf-8")
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    write_manifest(tmp_path, {"result.txt": expected})
    assert MODULE.verify_artifact_package(tmp_path) == 1


def test_hash_drift_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "result.txt"
    target.write_text("original", encoding="utf-8")
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    write_manifest(tmp_path, {"result.txt": expected})
    target.write_text("tampered", encoding="utf-8")
    with pytest.raises(MODULE.ArtifactIntegrityError, match="hash drift"):
        MODULE.verify_artifact_package(tmp_path)


@pytest.mark.parametrize("relative", ["._result.txt", "../result.txt", "/result.txt"])
def test_unsafe_manifest_paths_fail_closed(tmp_path: Path, relative: str) -> None:
    write_manifest(tmp_path, {relative: "0" * 64})
    with pytest.raises(MODULE.ArtifactIntegrityError, match="unsafe"):
        MODULE.verify_artifact_package(tmp_path)


def test_decision_requires_verdict_and_fields(tmp_path: Path) -> None:
    decision = tmp_path / "decision.json"
    decision.write_text(
        json.dumps({"verdict": "PASS_EXAMPLE", "complete": False}),
        encoding="utf-8",
    )
    with pytest.raises(MODULE.ArtifactIntegrityError, match="field mismatch"):
        MODULE.require_decision(decision, "PASS_", {"complete": True})


def test_required_hash_entry_must_be_covered(tmp_path: Path) -> None:
    payload = tmp_path / "payload.txt"
    payload.write_text("ok\n", encoding="utf-8")
    expected = hashlib.sha256(payload.read_bytes()).hexdigest()
    write_manifest(tmp_path, {"payload.txt": expected})
    with pytest.raises(MODULE.ArtifactIntegrityError, match="critical files absent"):
        MODULE.verify_artifact_package(tmp_path, ("decision.json",))
