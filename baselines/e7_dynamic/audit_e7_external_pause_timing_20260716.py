#!/usr/bin/env python3
"""Reject E7 stage timings that are indistinguishable from an external SIGSTOP."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[2]
FORMAL = ROOT / "baselines/e7_dynamic/e7_multinetwork_formal_20260715"
INCIDENT = (
    ROOT
    / "baselines/e7_dynamic/monitor_configs/e7_external_pause_incident_20260716.json"
)
TOL = 1e-6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def contaminated_stages(
    sessions: Iterable[Mapping[str, Any]], pause_duration_seconds: float
) -> list[dict[str, Any]]:
    if pause_duration_seconds <= 0.0:
        raise ValueError("pause_duration_seconds must be positive")
    failures: list[dict[str, Any]] = []
    for payload in sessions:
        if payload.get("execution_status") != "PASS":
            continue
        task_id = (
            f"{payload['network']}__{payload['responsibility_condition']}__"
            f"stream{payload['stream_seed']}__{payload['arm']}"
        )
        for stage in payload.get("rows", []):
            elapsed = float(stage["elapsed_seconds"])
            if elapsed + TOL >= pause_duration_seconds:
                failures.append(
                    {
                        "task_id": task_id,
                        "stage": int(stage["stage"]),
                        "elapsed_seconds": elapsed,
                        "pause_duration_seconds": pause_duration_seconds,
                    }
                )
    return failures


def main() -> int:
    incident = json.loads(INCIDENT.read_text(encoding="utf-8"))
    sessions_path = FORMAL / "sessions.json"
    manifest_path = FORMAL / "artifact_hashes.json"
    sessions = json.loads(sessions_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_sessions_hash = manifest.get("sessions.json")
    if expected_sessions_hash != sha256(sessions_path):
        raise RuntimeError("formal sessions.json is absent from or differs from its manifest")
    duration = float(incident["pause_duration_seconds"])
    failures = contaminated_stages(sessions, duration)
    result = {
        "status": (
            "PASS_E7_EXTERNAL_PAUSE_TIMING_GATE"
            if not failures
            else "HALT_E7_EXTERNAL_PAUSE_TIMING_CONTAMINATION"
        ),
        "pause_incident_sha256": sha256(INCIDENT),
        "pause_duration_seconds": duration,
        "contaminated_stage_count": len(failures),
        "contaminated_stages": failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
