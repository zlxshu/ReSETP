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
