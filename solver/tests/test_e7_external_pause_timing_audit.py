from __future__ import annotations

from datetime import datetime
import json

import pytest

from baselines.e7_dynamic import audit_e7_external_pause_timing_20260716 as audit


def _session(elapsed: float, *, status: str = "PASS") -> dict:
    return {
        "network": "N114",
        "responsibility_condition": "geographic",
        "stream_seed": 1,
        "arm": "full",
        "execution_status": status,
        "rows": [{"stage": 3, "elapsed_seconds": elapsed}],
    }


def test_pause_gate_accepts_clean_stage_and_skips_controlled_failure() -> None:
    rows = [_session(120.0), _session(20_000.0, status="HALT_NO_EXECUTABLE_CONTINUATION")]
    assert audit.contaminated_stages(rows, 13_934.0) == []


def test_pause_gate_rejects_stage_indistinguishable_from_sigstop() -> None:
    failures = audit.contaminated_stages([_session(13_934.0)], 13_934.0)
    assert failures == [
        {
            "task_id": "N114__geographic__stream1__full",
            "stage": 3,
            "elapsed_seconds": 13_934.0,
            "pause_duration_seconds": 13_934.0,
        }
    ]


def test_pause_gate_requires_positive_duration() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        audit.contaminated_stages([_session(1.0)], 0.0)


def test_recorded_pause_duration_matches_event_timestamps() -> None:
    incident = json.loads(audit.INCIDENT.read_text(encoding="utf-8"))
    observed = (
        datetime.fromisoformat(incident["resumed_at_utc"])
        - datetime.fromisoformat(incident["paused_at_utc"])
    ).total_seconds()
    assert observed == incident["pause_duration_seconds"] == 13_934.0
    assert all(
        len(record["sha256"]) == 64
        for record in incident["event_evidence"].values()
    )


def test_approved_v2_rerun_replaces_exact_nine_suspect_stages() -> None:
    sessions = json.loads(
        (audit.FORMAL / "sessions.json").read_text(encoding="utf-8")
    )
    incident = json.loads(audit.INCIDENT.read_text(encoding="utf-8"))
    result = audit.verified_effective_timing_gate(
        sessions,
        float(incident["pause_duration_seconds"]),
        incident_sha256=audit.sha256(audit.INCIDENT),
    )
    assert result["status"] == "PASS_E7_EXTERNAL_PAUSE_TIMING_GATE_V2"
    assert result["historical_contaminated_stage_count"] == 9
    assert result["approved_replacement_stage_count"] == 9
    assert result["unresolved_contaminated_stage_count"] == 0
