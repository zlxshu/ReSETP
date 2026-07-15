from __future__ import annotations

import json

from baselines.paper_story import audit_20260715_paper_evidence_boundaries as audit


def test_story_audit_manifest_is_exact(tmp_path) -> None:
    payload = b"sealed evidence\n"
    (tmp_path / "report.md").write_bytes(payload)
    (tmp_path / "artifact_hashes.json").write_text(
        json.dumps({"report.md": audit.sha256(tmp_path / "report.md")}),
        encoding="utf-8",
    )
    assert audit.verify_manifest(tmp_path) == []

    (tmp_path / "extra.txt").write_text("unlisted\n", encoding="utf-8")
    failures = audit.verify_manifest(tmp_path)
    assert failures == [f"{tmp_path}: unlisted extra.txt"]

    (tmp_path / "extra.txt").unlink()
    (tmp_path / "report.md").write_text("drift\n", encoding="utf-8")
    failures = audit.verify_manifest(tmp_path)
    assert failures == [f"{tmp_path}: hash drift report.md"]

    (tmp_path / "report.md").unlink()
    failures = audit.verify_manifest(tmp_path)
    assert failures == [f"{tmp_path}: missing report.md"]


def test_story_audit_requires_complete_replay_invariant_counts() -> None:
    decision = {
        "status": "PASS_E7_REPLAY_INVARIANTS_AUDIT",
        **audit.E7_REPLAY_INVARIANT_COUNTS,
    }
    assert audit.replay_invariant_decision_failures(decision) == []

    decision["station_capacity_violation_count"] = 1
    assert audit.replay_invariant_decision_failures(decision) == [
        "E7 replay-invariants field differs: station_capacity_violation_count != 0"
    ]


def test_legacy_manifest_allows_only_declared_historical_exceptions(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    root = tmp_path / "evidence"
    root.mkdir()
    payload = root / "report.md"
    payload.write_text("sealed\n", encoding="utf-8")
    exception = root / "late_parameter_table.csv"
    exception.write_text("name,value\n", encoding="utf-8")
    (root / "artifact_hashes.json").write_text(
        json.dumps(
            {
                "file_count": 1,
                "files": [
                    {
                        "path": "evidence/report.md",
                        "sha256": audit.sha256(payload),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    allowed = {"evidence/late_parameter_table.csv"}
    assert audit.verify_legacy_manifest(root, allowed_unlisted=allowed) == []
    assert audit.verify_legacy_manifest(root) == [
        "evidence: legacy unlisted evidence/late_parameter_table.csv"
    ]


def test_current_paper_build_is_current_and_searchable() -> None:
    failures, info, warnings = audit.verify_paper_build()
    assert failures == []
    assert info["page_count"] >= 20
    assert info["input_file_count"] >= 10
    assert isinstance(warnings, list)
