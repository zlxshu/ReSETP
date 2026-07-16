from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
import subprocess
import sys

from baselines.e7_dynamic import audit_e7_replay_invariants_20260715 as audit


def test_replay_key_normalizes_identity_fields() -> None:
    assert audit.replay_key(
        {
            "network": "N114",
            "condition": "geographic",
            "stream": "3",
            "arm": "full",
            "operating_day": "2025-11-13",
        }
    ) == ("N114", "geographic", 3, "full", "2025-11-13")


def test_close_uses_scale_aware_tolerance() -> None:
    assert audit.close(1_000_000.0, 1_000_000.5)
    assert not audit.close(1.0, 1.001)


def test_invariant_manifest_requires_exact_inventory_and_hashes(tmp_path) -> None:
    payload = b"sealed invariant evidence\n"
    (tmp_path / "decision.json").write_bytes(payload)
    (tmp_path / "artifact_hashes.json").write_text(
        json.dumps({"decision.json": hashlib.sha256(payload).hexdigest()}),
        encoding="utf-8",
    )
    assert audit.verify_manifest(tmp_path) == []

    (tmp_path / "unexpected.txt").write_text("extra\n", encoding="utf-8")
    assert audit.verify_manifest(tmp_path) == ["unlisted:unexpected.txt"]


def test_invariant_audit_loads_from_outside_repository_without_pythonpath(
    tmp_path,
) -> None:
    script = Path(audit.__file__).resolve()
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import runpy; "
                f"runpy.run_path({str(script)!r}, run_name='e7_invariant_import_probe')"
            ),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
