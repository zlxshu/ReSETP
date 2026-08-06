#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs/handoff/solver_fleetcap_fix_20260804"
EXCLUDED_NAMES = {
    "artifact_hashes.json",
    "__pycache__",
    ".pytest_cache",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


artifacts: dict[str, str] = {}
for path in sorted(OUTPUT.rglob("*")):
    if not path.is_file():
        continue
    relative = path.relative_to(OUTPUT)
    if (
        path.name in EXCLUDED_NAMES
        or path.name.startswith("._")
        or any(part in EXCLUDED_NAMES for part in relative.parts)
        or "checkpoint" in path.name.lower()
        and path.name.lower().endswith((".tmp", ".temp"))
    ):
        continue
    artifacts[str(relative)] = sha256(path)

payload = {
    "schema": "resetp.artifact-hashes.v1",
    "algorithm": "sha256",
    "artifacts": artifacts,
    "exclusions": [
        "artifact_hashes.json",
        "._*",
        "**/__pycache__/**",
        "**/.pytest_cache/**",
        "temporary checkpoint files (*.tmp, *.temp)",
    ],
}
(OUTPUT / "artifact_hashes.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
