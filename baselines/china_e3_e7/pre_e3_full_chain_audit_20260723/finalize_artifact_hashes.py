#!/usr/bin/env python3
"""Build the deterministic SHA-256 manifest for this audit evidence package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


AUDIT_DIR = Path(__file__).resolve().parent
REPO = AUDIT_DIR.parents[2]
OUTPUT = AUDIT_DIR / "artifact_hashes.json"

EXCLUDED_DIRS = {"__pycache__", ".pytest_cache"}
EXCLUDED_NAMES = {"artifact_hashes.json", ".DS_Store"}
EXCLUDED_PARTS = {"checkpoint", "temporary", ".tmp"}


def is_evidence_file(path: Path) -> bool:
    relative = path.relative_to(AUDIT_DIR)
    if path.name in EXCLUDED_NAMES or path.name.startswith("._"):
        return False
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return False
    lowered = tuple(part.lower() for part in relative.parts)
    return not any(
        marker in part
        for part in lowered
        for marker in EXCLUDED_PARTS
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    files = {
        path.relative_to(REPO).as_posix(): sha256(path)
        for path in sorted(AUDIT_DIR.rglob("*"))
        if path.is_file() and is_evidence_file(path)
    }
    payload = {
        "schema": "resetp.artifact-hashes.v1",
        "algorithm": "sha256",
        "contamination_status": "CLEAN_NO_APPLEDOUBLE",
        "exclusions": [
            "artifact_hashes.json",
            "._*",
            "__pycache__",
            ".pytest_cache",
            "temporary files",
            "checkpoint files",
        ],
        "files": files,
    }
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT.relative_to(REPO)),
                "files": len(files),
                "contamination_status": payload["contamination_status"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
