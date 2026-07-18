#!/usr/bin/env python3
"""Reject E7 stage timings that are indistinguishable from an external SIGSTOP."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[2]
FORMAL = ROOT / "baselines/e7_dynamic/e7_multinetwork_formal_20260715"
TIMING_RERUN = (
    ROOT
    / "baselines/e7_dynamic/e7_multinetwork_formal_timing_clean_rerun_20260717"
)
INCIDENT = (
    ROOT
    / "baselines/e7_dynamic/monitor_configs/e7_external_pause_incident_20260716.json"
)
TOL = 1e-6
EXPECTED_RERUN_SCHEMA = "setp.e7.timing_clean_rerun.v2"
EXPECTED_RERUN_STATUS = "PASS_E7_TIMING_CLEAN_RERUN_COMPLETE"
EXPECTED_ACCEPTANCE_STATUS = "PASS_PAIRED_TIMING_ACCEPTANCE_V2"


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


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def verified_effective_timing_gate(
    sessions: Iterable[Mapping[str, Any]],
    pause_duration_seconds: float,
    *,
    incident_sha256: str,
    timing_rerun: Path = TIMING_RERUN,
) -> dict[str, Any]:
    """Verify the approved v2 rerun and return unresolved timing contamination.

    The original formal package remains immutable.  Its nine suspect stage
    timings are superseded only when the sealed rerun package proves the exact
    same stage identities, checkpoint hashes, non-timing semantics, and
    pre-registered paired acceptance rule.  Any other suspect stage remains a
    hard failure.
    """

    historical_failures = contaminated_stages(sessions, pause_duration_seconds)
    finished_path = timing_rerun / "RERUN_FINISHED.json"
    manifest_path = timing_rerun / "rerun_manifest.json"
    if not finished_path.is_file() or not manifest_path.is_file():
        raise RuntimeError("approved timing rerun completion markers are missing")
    finished = json.loads(finished_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    shared_requirements = {
        "schema": EXPECTED_RERUN_SCHEMA,
        "status": EXPECTED_RERUN_STATUS,
        "historical_packages_unchanged": True,
        "semantic_non_timing_match": True,
        "formal_timing_source": "all_nine_rerun_checkpoints",
    }
    for field, expected in shared_requirements.items():
        if finished.get(field) != expected or manifest.get(field) != expected:
            raise RuntimeError(f"timing rerun {field} is not sealed as expected")
    if manifest.get("incident_sha256") != incident_sha256:
        raise RuntimeError("timing rerun refers to a different pause incident")
    if manifest.get("result_direction_used_for_inclusion") is not False:
        raise RuntimeError("timing rerun inclusion must be blind to result direction")

    finished_acceptance = finished.get("paired_timing_acceptance", {})
    manifest_acceptance = manifest.get("paired_timing_acceptance", {})
    if finished_acceptance != manifest_acceptance:
        raise RuntimeError("timing rerun acceptance evidence differs between markers")
    if (
        finished_acceptance.get("schema") != "setp.e7.timing_acceptance.v2"
        or finished_acceptance.get("status") != EXPECTED_ACCEPTANCE_STATUS
        or int(finished_acceptance.get("parent_task_count", -1)) != 4
        or int(finished_acceptance.get("child_task_count", -1)) != 5
    ):
        raise RuntimeError("timing rerun paired acceptance gate is incomplete")
    acceptance_tasks = list(finished_acceptance.get("tasks", []))
    if len(acceptance_tasks) != 9 or not all(
        task.get("accepted") is True for task in acceptance_tasks
    ):
        raise RuntimeError("not all nine rerun timing tasks were accepted")

    historical_keys = {
        (str(row["task_id"]), int(row["stage"])) for row in historical_failures
    }
    manifest_rows = list(manifest.get("contaminated_stages", []))
    manifest_keys = {
        (str(row["task_id"]), int(row["stage"])) for row in manifest_rows
    }
    acceptance_keys = {
        (str(row["task_id"]), int(row["stage"])) for row in acceptance_tasks
    }
    if (
        len(historical_keys) != 9
        or historical_keys != manifest_keys
        or historical_keys != acceptance_keys
    ):
        raise RuntimeError("timing rerun does not replace the exact nine suspect stages")

    task_ids = sorted(task_id for task_id, _ in historical_keys)
    if sorted(finished.get("task_ids", [])) != task_ids:
        raise RuntimeError("timing rerun completion task identities differ")
    if sorted(manifest.get("task_ids", [])) != task_ids:
        raise RuntimeError("timing rerun manifest task identities differ")
    if int(manifest.get("contaminated_stage_count", -1)) != len(historical_keys):
        raise RuntimeError("timing rerun contaminated-stage count differs")

    finished_checkpoint_hashes = dict(finished.get("task_checkpoint_sha256", {}))
    manifest_checkpoint_hashes = dict(manifest.get("task_checkpoint_sha256", {}))
    payload_hashes = dict(manifest.get("payload_sha256", {}))
    if (
        set(finished_checkpoint_hashes) != set(task_ids)
        or set(manifest_checkpoint_hashes) != set(task_ids)
    ):
        raise RuntimeError("timing rerun checkpoint hash inventory differs")
    if finished_checkpoint_hashes != manifest_checkpoint_hashes:
        raise RuntimeError("timing rerun checkpoint hashes differ between markers")
    if set(payload_hashes) != set(task_ids):
        raise RuntimeError("timing rerun payload hash inventory differs")
    for task_id in task_ids:
        checkpoint = timing_rerun / ".tasks" / f"{task_id}.json"
        if not checkpoint.is_file():
            raise RuntimeError(f"timing rerun checkpoint is missing: {task_id}")
        if sha256(checkpoint) != finished_checkpoint_hashes[task_id]:
            raise RuntimeError(f"timing rerun checkpoint hash differs: {task_id}")
        wrapper = json.loads(checkpoint.read_text(encoding="utf-8"))
        payload = wrapper.get("payload")
        if (
            wrapper.get("status") != "completed"
            or not isinstance(payload, dict)
            or payload.get("execution_status") != "PASS"
        ):
            raise RuntimeError(f"timing rerun checkpoint did not pass: {task_id}")
        if wrapper.get("payload_sha256") != canonical_sha256(payload):
            raise RuntimeError(f"timing rerun wrapper payload hash differs: {task_id}")
        if payload_hashes[task_id] != canonical_sha256(payload):
            raise RuntimeError(f"timing rerun manifest payload hash differs: {task_id}")

    return {
        "status": "PASS_E7_EXTERNAL_PAUSE_TIMING_GATE_V2",
        "pause_duration_seconds": pause_duration_seconds,
        "historical_contaminated_stage_count": len(historical_failures),
        "approved_replacement_stage_count": len(historical_keys),
        "unresolved_contaminated_stage_count": 0,
        "unresolved_contaminated_stages": [],
        "timing_rerun_schema": EXPECTED_RERUN_SCHEMA,
        "timing_rerun_completion_sha256": sha256(finished_path),
        "timing_rerun_manifest_sha256": sha256(manifest_path),
        "paired_timing_acceptance_status": EXPECTED_ACCEPTANCE_STATUS,
        "replacement_stage_keys": [
            {"task_id": task_id, "stage": stage}
            for task_id, stage in sorted(historical_keys)
        ],
    }


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
    result = verified_effective_timing_gate(
        sessions,
        duration,
        incident_sha256=sha256(INCIDENT),
    )
    result.update(
        {
            "pause_incident_sha256": sha256(INCIDENT),
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
