#!/usr/bin/env python3
"""Build the final SHA-256 manifest for the T5 draft probe."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


OUT = Path(__file__).resolve().parent
EXCLUDED_NAMES = {
    "artifact_hashes.json",
    "__pycache__",
    ".pytest_cache",
    ".experiment.monitor",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


artifacts: dict[str, str] = {}
for path in sorted(OUT.rglob("*")):
    if not path.is_file():
        continue
    relative = path.relative_to(OUT)
    if (
        path.name in EXCLUDED_NAMES
        or path.name.startswith("._")
        or any(part in EXCLUDED_NAMES for part in relative.parts)
        or any(part.startswith(".attempt") for part in relative.parts)
        or any(part.startswith(".experiment.monitor") for part in relative.parts)
        or path.suffix in {".pyc", ".tmp", ".temp"}
    ):
        continue
    artifacts[str(relative)] = sha256(path)

payload = {
    "schema": "resetp.artifact-hashes.v1",
    "task_id": "T5-CARBON-OBJ-PROBE",
    "draft_status": "DRAFT_METHOD_AWAITING_USER_APPROVAL",
    "algorithm": "sha256",
    "artifacts": artifacts,
    "exclusions": [
        "artifact_hashes.json",
        "._*",
        "**/__pycache__/**",
        "**/.pytest_cache/**",
        ".experiment.monitor/**",
        ".attempt*/**",
        "*.pyc",
        "temporary files (*.tmp, *.temp)"
    ]
}
(OUT / "artifact_hashes.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
