from __future__ import annotations

import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / "baselines/e7_dynamic/e7_full_day_value_audit_formal_20260714"


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


def test_formal_audit_has_complete_evidence_pack() -> None:
    for name in (
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
    ):
        assert (EVIDENCE / name).is_file(), name


def test_formal_audit_retains_all_streams_and_the_unfavourable_result() -> None:
    rows = read_csv("paired_value_summary.csv")
    assert [int(row["stream_seed"]) for row in rows] == [1, 2, 3, 4, 5]
    assert all(row["workload_equal"] == "False" for row in rows)
    changes = [Decimal(row["net_benefit_change_percent"]) for row in rows]
    assert sum(value > 0 for value in changes) == 4
    assert sum(value < 0 for value in changes) == 1
    assert changes[1] == Decimal("-0.4065938240221788946458884595")


def test_formal_audit_mechanical_decision_and_summary_close() -> None:
    decision = read_json("decision.json")
    summary = decision["paper_summary"]
    assert decision["status"] == "PASS"
    assert decision["independent_record_replay"] == "RECORD_LAYER_PASS"
    assert decision["event_coverage"]["recorded_disposition_count"] == 550
    assert decision["event_coverage"]["every_event_covered_exactly_once_per_arm"]
    assert summary["positive_stream_count"] == 4
    assert Decimal(summary["mean_net_benefit_change_percent"]) == Decimal(
        "1.117775993918489192814948134"
    )
    assert Decimal(summary["median_net_benefit_change_percent"]) == Decimal(
        "0.5596755454228787589192106475"
    )


def test_formal_audit_raw_ledger_and_artifact_manifest_close() -> None:
    raw_rows = read_csv("raw_runs.csv")
    assert len(raw_rows) == 10
    assert sum(int(row["event_disposition_count"]) for row in raw_rows) == 550
    assert all(row["cost_closure_pass"] == "True" for row in raw_rows)

    manifest = read_json("artifact_hashes.json")
    listed = {str(row["path"]): row for row in manifest["artifacts"]}
    actual: dict[str, Path] = {}
    for path in EVIDENCE.rglob("*"):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        ):
            actual[str(path.relative_to(REPO_ROOT))] = path
    assert set(listed) == set(actual)
    for relative, path in actual.items():
        assert listed[relative]["sha256"] == sha256(path)
        assert int(listed[relative]["bytes"]) == path.stat().st_size
