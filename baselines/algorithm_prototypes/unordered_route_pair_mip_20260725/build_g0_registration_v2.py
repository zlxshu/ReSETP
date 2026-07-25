#!/usr/bin/env python3
"""Freeze G0 v2 after audit-only reporting helpers were added."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import build_g0_registration as v1

REPO = v1.REPO
PACKAGE = v1.PACKAGE
REGISTRATION = PACKAGE / "g0_registration_v2.json"
V1_REGISTRATION = PACKAGE / "g0_registration_v1.json"
V1_DECISION = PACKAGE / "g0_gate_v1/decision.json"
V1_HASHES = PACKAGE / "g0_gate_v1/artifact_hashes.json"
EXTRA_SOURCES = (
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/build_g0_registration_v2.py",
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/run_g0_v2.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if REGISTRATION.exists():
        raise RuntimeError(f"registration already exists: {REGISTRATION}")
    payload = json.loads(V1_REGISTRATION.read_text(encoding="utf-8"))
    payload.update(
        {
            "schema": "resetp.unordered-route-pair-g0-registration.v2",
            "registered_at_utc": datetime.now(timezone.utc).isoformat(),
            "supersedes": {
                "registration_path": (V1_REGISTRATION.relative_to(REPO).as_posix()),
                "registration_sha256": sha256(V1_REGISTRATION),
                "decision_path": V1_DECISION.relative_to(REPO).as_posix(),
                "decision_sha256": sha256(V1_DECISION),
                "artifact_hashes_path": (V1_HASHES.relative_to(REPO).as_posix()),
                "artifact_hashes_sha256": sha256(V1_HASHES),
                "reason": (
                    "pair_core gained audit-only fallback-objective output "
                    "and parent-route-pool construction after v1."
                ),
            },
            "source_hashes": {
                relative: sha256(REPO / relative)
                for relative in (*v1.SOURCE_PATHS, *EXTRA_SOURCES)
            },
        }
    )
    REGISTRATION.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"registration": str(REGISTRATION)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
