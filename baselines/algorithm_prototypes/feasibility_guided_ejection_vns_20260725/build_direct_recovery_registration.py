#!/usr/bin/env python3
"""Freeze the zero-search recovery of the completed behavior-gate artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
ABORT = PACKAGE / "direct_improvement_gate_v1_abort_packaging"
ORIGINAL_REGISTRATION = PACKAGE / "direct_improvement_registration_v1.json"
OUTPUT = PACKAGE / "direct_recovery_registration_v1.json"
SOURCE_PATHS = (
    "baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/build_direct_recovery_registration.py",
    "baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/recover_direct_gate_no_search.py",
    "docs/handoff/e2_feasibility_guided_vns_contract_20260725.md",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/china81.py",
    "solver/src/setp_solver/china81_completion.py",
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/prices.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"recovery registration exists: {OUTPUT}")
    original = read_json(ORIGINAL_REGISTRATION)
    artifacts = {
        path.relative_to(REPO).as_posix(): sha256(path)
        for path in sorted(ABORT.rglob("*"))
        if path.is_file()
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    }
    expected_names = {
        "metadata.json",
        "raw_runs.csv",
        *(
            f"traces/{row['instance_id']}.json"
            for row in original["inputs"]
        ),
        *(
            f"witnesses/{row['instance_id']}.json"
            for row in original["inputs"]
        ),
    }
    actual_names = {
        (REPO / relative).relative_to(ABORT).as_posix()
        for relative in artifacts
    }
    if actual_names != expected_names:
        raise RuntimeError(
            f"unexpected abort artifact set: {sorted(actual_names)}"
        )
    payload = {
        "schema": "resetp.fge-vns-direct-recovery-registration.v1",
        "status": "FROZEN_BEFORE_ZERO_SEARCH_RECOVERY",
        "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "approval_id": "E2-FGE-DIRECT-PACKAGING-012",
        "original_registration": {
            "path": ORIGINAL_REGISTRATION.relative_to(REPO).as_posix(),
            "sha256": sha256(ORIGINAL_REGISTRATION),
        },
        "abort_artifacts": artifacts,
        "source_hashes": {
            relative: sha256(REPO / relative)
            for relative in SOURCE_PATHS
        },
        "inputs": original["inputs"],
        "config": original["config"],
        "authority_registration": original["authority_registration"],
        "search_executions": 0,
        "unrecoverable_fields": [
            "elapsed_seconds_per_instance",
            "peak_rss_per_instance",
        ],
        "claim_boundary": original["claim_boundary"],
    }
    write_json(OUTPUT, payload)
    print(
        "FROZEN_BEFORE_ZERO_SEARCH_RECOVERY",
        len(artifacts),
        len(payload["source_hashes"]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

