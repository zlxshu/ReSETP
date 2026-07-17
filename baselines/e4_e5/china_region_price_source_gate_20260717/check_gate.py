#!/usr/bin/env python3
"""Structural validation only; this gate never runs an optimizer."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REQUIRED = {"metadata.json", "raw_runs.csv", "decision.json", "artifact_hashes.json", "report.md"}
TVCI = ROOT.parent / "china_tvci_source_gate_20260717_v2" / "tvci_2025_48slot_wide.csv"
TVCI_SHA256 = "099f266558815a34f11b046545fa7bd294e5b823417c4977ef6556967b40c745"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    missing = sorted(name for name in REQUIRED if not (ROOT / name).is_file())
    assert not missing, f"missing required artifacts: {missing}"
    assert not list(ROOT.rglob("._*")), "HASH_CONTAMINATED_APPLEDOUBLE: AppleDouble sidecar present"

    metadata = json.loads((ROOT / "metadata.json").read_text())
    decision = json.loads((ROOT / "decision.json").read_text())
    manifest = json.loads((ROOT / "artifact_hashes.json").read_text())
    assert metadata["search_evaluations"] == 0
    assert metadata["optimization_runs"] == 0
    assert decision["decision"] == "PARTIAL_CHINA_REGION_PRICE_SOURCE_GATE"
    assert set(decision["regions"]) == {"jjj_beijing", "prd_guangdong", "cy_chongqing_sichuan"}
    assert all(item["status"] in {"PASS", "PARTIAL", "HALT"} for item in decision["regions"].values())
    assert "Shanghai" in " ".join(decision["does_not_authorize"])

    with (ROOT / "raw_runs.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == metadata["source_count"], "source count does not match raw_runs.csv"
    required_columns = {
        "source_id", "region_scope", "source_type", "direct_url", "fetched_at_utc",
        "raw_file", "raw_sha256", "license_or_use_restriction", "fetch_status",
    }
    assert required_columns <= set(rows[0]), "raw_runs.csv schema is incomplete"
    for row in rows:
        if row["fetch_status"] == "SAVED":
            path = ROOT / row["raw_file"]
            assert path.is_file(), f"missing source file: {path}"
            assert sha256(path) == row["raw_sha256"], f"source hash mismatch: {path}"

    assert TVCI.is_file() and sha256(TVCI) == TVCI_SHA256, "trusted TVCI derivative changed"
    with TVCI.open(newline="") as handle:
        header = next(csv.reader(handle))
    assert {"Beijing", "Guangdong", "Chongqing"} <= set(header), "required TVCI columns absent"

    for rel, expected in manifest["artifacts"].items():
        path = ROOT / rel
        assert path.is_file(), f"manifest path absent: {rel}"
        assert sha256(path) == expected, f"artifact hash mismatch: {rel}"

    print(f"PASS: {len(rows)} sources, 3 regional decisions, TVCI columns, {len(manifest['artifacts'])} hashes")


if __name__ == "__main__":
    main()
