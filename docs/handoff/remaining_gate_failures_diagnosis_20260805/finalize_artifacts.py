from __future__ import annotations

import hashlib
import json
from pathlib import Path


OUT = Path(__file__).resolve().parent
EXCLUDED_NAMES = {"artifact_hashes.json"}


def excluded(path: Path) -> bool:
    if path.name in EXCLUDED_NAMES or path.name.startswith("._"):
        return True
    return any(part in {"__pycache__", ".pytest_cache"} for part in path.parts)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


files = sorted(
    path for path in OUT.rglob("*") if path.is_file() and not excluded(path)
)
payload = {
    "schema": "resetp.t13-artifact-hashes.v1",
    "task_id": "T13-REMAINING-GATE-FAILURES-DIAGNOSIS",
    "algorithm": "SHA-256",
    "root": str(OUT),
    "exclusions": [
        "artifact_hashes.json",
        "._*",
        "**/__pycache__/**",
        "**/.pytest_cache/**",
    ],
    "artifacts": {
        str(path.relative_to(OUT)): sha256(path) for path in files
    },
}
(OUT / "artifact_hashes.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(payload, ensure_ascii=False, indent=2))
