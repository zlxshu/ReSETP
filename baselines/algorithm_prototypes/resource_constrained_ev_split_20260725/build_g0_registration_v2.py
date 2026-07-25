#!/usr/bin/env python3
"""Freeze the versioned no-result repair after the G0 v1 wiring HALT."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from build_g0_registration import REPO, SOURCE_PATHS, sha256, write_json

PACKAGE = Path(__file__).resolve().parent
V1 = PACKAGE / "g0_registration_v1.json"
V2 = PACKAGE / "g0_registration_v2.json"
EXTRA_SOURCES = (
    "baselines/algorithm_prototypes/resource_constrained_ev_split_20260725/build_g0_registration_v2.py",
)


def main() -> int:
    if V2.exists():
        raise RuntimeError(f"registration already exists: {V2}")
    payload = json.loads(V1.read_text(encoding="utf-8"))
    payload.update(
        {
            "schema": "resetp.rc-ev-split-g0-registration.v2",
            "registered_at_utc": datetime.now(timezone.utc).isoformat(),
            "supersedes_registration": {
                "path": V1.relative_to(REPO).as_posix(),
                "sha256": sha256(V1),
            },
            "repair_scope": (
                "Catch NoFeasibleAssignmentError for one contiguous "
                "segment and continue enumerating other segment boundaries; "
                "no instance, witness, objective, resource limit, or "
                "algorithmic ranking change."
            ),
            "source_hashes": {
                relative: sha256(REPO / relative)
                for relative in (*SOURCE_PATHS, *EXTRA_SOURCES)
            },
        }
    )
    write_json(V2, payload)
    print(
        json.dumps(
            {"registration": str(V2), "inputs": payload["inputs"]},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
