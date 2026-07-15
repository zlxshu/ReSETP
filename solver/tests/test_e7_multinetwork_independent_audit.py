from __future__ import annotations

import hashlib
import json

from baselines.e7_dynamic import audit_e7_multinetwork_formal_20260715 as audit


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_manifest_verification_is_exact_but_ignores_resumable_tasks(tmp_path) -> None:
    payload = b"sealed evidence\n"
    (tmp_path / "result.txt").write_bytes(payload)
    (tmp_path / ".tasks").mkdir()
    (tmp_path / ".tasks" / "checkpoint.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "artifact_hashes.json").write_text(
        json.dumps({"result.txt": _sha256(payload)}), encoding="utf-8"
    )

    count, failures = audit.verify_manifest(tmp_path)

    assert count == 1
    assert failures == []

    (tmp_path / "unlisted.txt").write_text("extra\n", encoding="utf-8")
    _, failures = audit.verify_manifest(tmp_path)
    assert failures == ["unlisted:unlisted.txt"]

    (tmp_path / "unlisted.txt").unlink()
    (tmp_path / "result.txt").write_text("changed\n", encoding="utf-8")
    _, failures = audit.verify_manifest(tmp_path)
    assert failures == ["hash:result.txt"]


def test_replay_coverage_requires_30_full_tasks_with_28_unique_days() -> None:
    rows = [
        {
            "network": network,
            "condition": condition,
            "stream": str(stream),
            "arm": "full",
            "operating_day": f"2025-11-{day:02d}",
        }
        for network in ("N114", "N221", "N322")
        for condition in ("geographic", "historical_mixed")
        for stream in range(1, 6)
        for day in range(1, 29)
    ]
    assert all(audit.replay_coverage_checks(rows).values())

    rows[-1] = dict(rows[-2])
    checks = audit.replay_coverage_checks(rows)
    assert not checks["replay_unique_row_keys_840"]
    assert not checks["replay_30_tasks_each_28_distinct_days"]


def test_formal_matrix_requires_exact_120_unique_tasks() -> None:
    sessions = [
        {
            "network": network,
            "responsibility_condition": condition,
            "stream_seed": stream,
            "arm": arm,
        }
        for network in audit.NETWORKS
        for condition in audit.CONDITIONS
        for stream in audit.STREAMS
        for arm in audit.ARMS
    ]
    assert audit.formal_task_matrix_failures(sessions) == []

    sessions[-1] = dict(sessions[-2])
    failures = audit.formal_task_matrix_failures(sessions)
    assert failures[0] == "formal sessions contain duplicate task identities"
    assert failures[1].startswith("formal sessions missing tasks:")
