from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / "baselines/e7_dynamic/e7_dynamic_emission_intensity_formal_20260714"


def read_json(name: str):
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def read_csv(name: str) -> list[dict[str, str]]:
    with (EVIDENCE / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_formal_emission_audit_has_complete_evidence_pack() -> None:
    for name in (
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
    ):
        assert (EVIDENCE / name).is_file(), name


def test_formal_emission_audit_keeps_all_streams_and_directions() -> None:
    rows = read_csv("paired_summary.csv")
    assert [int(row["stream_seed"]) for row in rows] == [1, 2, 3, 4, 5]
    assert all(float(row["E_total_intensity_change_percent"]) > 0 for row in rows)
    assert all(float(row["E_cv_direct_intensity_change_percent"]) > 0 for row in rows)
    assert all(float(row["electricity_kwh_intensity_change_percent"]) < 0 for row in rows)


def test_formal_emission_audit_decision_closes() -> None:
    decision = read_json("decision.json")
    assert decision["status"] == "PASS"
    assert decision["verdict"] == "E7_DYNAMIC_EMISSION_INTENSITY_AUDIT_PASS"
    assert decision["higher_total_emission_intensity_stream_count"] == 5
    assert decision["higher_fuel_emission_intensity_stream_count"] == 5
    assert decision["lower_electricity_intensity_stream_count"] == 5
    assert float(decision["maximum_absolute_emissions_closure_error"]) < 1e-9


def test_formal_emission_audit_artifact_manifest_closes() -> None:
    manifest = read_json("artifact_hashes.json")
    listed = {str(row["path"]): row for row in manifest["artifacts"]}
    actual: dict[str, Path] = {}
    for path in EVIDENCE.rglob("*"):
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._"):
            actual[str(path.relative_to(REPO_ROOT))] = path
    assert set(listed) == set(actual)
    for relative, path in actual.items():
        assert listed[relative]["sha256"] == sha256(path)
        assert int(listed[relative]["bytes"]) == path.stat().st_size
