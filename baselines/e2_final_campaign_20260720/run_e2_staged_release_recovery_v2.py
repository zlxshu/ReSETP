#!/usr/bin/env python3
"""Recover the frozen E2 v7 release chain after a monitor-only failure.

The original chain completed the formal campaign and full witness replay, but
its nested monitor remained alive on a defunct child and blocked the stage
transition. This recovery never reruns either completed stage. It verifies
their sealed evidence, preserves the original anomaly, and continues only the
already preregistered result-strength, S3, S4, and S5 stages.
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
REGISTRATION = CAMPAIGN / "release_recovery_registration_v2.json"
RECOVERY = CAMPAIGN / "release_recovery_v2"
CANONICAL = CAMPAIGN / "release_chain"
FORMAL = CAMPAIGN / "full_gate"
REPLAY = CAMPAIGN / "full_witness_replay"
ORIGINAL_MONITOR = CAMPAIGN / ".e2-staged-v7-release-chain.monitor"
PYTHON = REPO / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"

FORMAL_PASS = (
    "PASS_D6_CORRECTED_CHINA81_E2_STAGED_V7_SMALL_ARCHIVE_LEDGER"
)
REPLAY_PASS = "PASS_D6_STAGED_FULL_WITNESS_REPLAY"
RELEASE_PASS = "PASS_E2_STAGED_V7_RELEASE_CHAIN"
RELEASE_HALT = "HALT_E2_STAGED_V7_RELEASE_CHAIN"

THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}

STAGES = (
    {
        "name": "result_strength",
        "command": [
            str(PYTHON),
            "baselines/e2_final_campaign_20260720/"
            "run_e2_staged_result_strength_audit.py",
        ],
        "gate": CAMPAIGN / "result_strength_gate",
        "expected": "PASS_E2_STAGED_PORTFOLIO_PAPER_STRENGTH",
    },
    {
        "name": "s3_trajectory",
        "command": [
            str(PYTHON),
            "baselines/e2_final_campaign_20260720/"
            "run_e2_staged_s3_trajectory_gate.py",
            "--workers",
            "3",
        ],
        "gate": CAMPAIGN / "s3_trajectory_gate",
        "expected": "PASS_S3_STAGED_GENUINE_ITERATION_CURVES",
    },
    {
        "name": "s4_route_detail",
        "command": [
            str(PYTHON),
            "baselines/e2_final_campaign_20260720/"
            "run_e2_staged_s4_route_detail_v3.py",
        ],
        "gate": CAMPAIGN / "table4_gate",
        "expected": "PASS_D6_CORRECTED_S4_ROUTE_DETAIL",
    },
    {
        "name": "s5_artifacts",
        "command": [
            str(PYTHON),
            "baselines/e2_final_campaign_20260720/"
            "run_e2_staged_s5_artifacts.py",
        ],
        "gate": CAMPAIGN / "artifacts",
        "expected": "PASS_E2_STAGED_V7_S5_ARTIFACTS",
    },
)


class StageHalt(RuntimeError):
    """A frozen downstream scientific or presentation gate did not pass."""

    def __init__(self, message: str, row: dict[str, Any]) -> None:
        super().__init__(message)
        self.row = row


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("release recovery rows cannot be empty")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def verdict(root: Path) -> str:
    decision = root / "decision.json"
    if not decision.is_file():
        return "MISSING"
    return str(read_json(decision).get("verdict", "UNKNOWN"))


def verify_manifest(root: Path) -> int:
    manifest_path = root / "artifact_hashes.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"artifact manifest missing: {manifest_path}")
    manifest = read_json(manifest_path)
    entries = manifest.get("artifacts", manifest.get("files", {}))
    if not isinstance(entries, dict) or not entries:
        raise RuntimeError(f"artifact manifest empty: {manifest_path}")
    for relative, expected in entries.items():
        raw = Path(str(relative))
        candidates = [raw] if raw.is_absolute() else [root / raw, REPO / raw]
        artifact = next(
            (candidate for candidate in candidates if candidate.is_file()),
            None,
        )
        if artifact is None:
            raise RuntimeError(f"artifact missing: {root}:{relative}")
        actual = sha256(artifact)
        if actual != str(expected):
            raise RuntimeError(
                f"artifact hash mismatch: {artifact}:{expected}:{actual}"
            )
    return len(entries)


def verify_registration() -> dict[str, Any]:
    if not REGISTRATION.is_file():
        raise RuntimeError("release recovery registration is missing")
    registration = read_json(REGISTRATION)
    if (
        registration.get("schema")
        != "resetp.e2-v7-release-recovery-registration.v2"
    ):
        raise RuntimeError("unexpected release recovery registration schema")
    if registration.get("status") != "FROZEN_AFTER_REPLAY_BEFORE_STRENGTH":
        raise RuntimeError("release recovery registration status drift")
    sources = registration.get("source_hashes")
    if not isinstance(sources, dict) or not sources:
        raise RuntimeError("release recovery registration has no source hashes")
    for relative, expected in sources.items():
        source = REPO / str(relative)
        if not source.is_file():
            raise RuntimeError(f"registered source missing: {relative}")
        actual = sha256(source)
        if actual != str(expected):
            raise RuntimeError(
                f"registered source drift: {relative}:{expected}:{actual}"
            )
    return registration


def legacy_release_process_running() -> bool:
    output = subprocess.check_output(
        ["ps", "-axo", "command"],
        text=True,
    )
    return any(
        "run_e2_staged_release_chain.py" in line
        for line in output.splitlines()
    )


def verify_completed_upstream() -> list[dict[str, Any]]:
    if legacy_release_process_running():
        raise RuntimeError("legacy release process is still running")
    original_status_path = ORIGINAL_MONITOR / "status.json"
    original_runtime_path = ORIGINAL_MONITOR / "runtime.json"
    if not original_status_path.is_file() or not original_runtime_path.is_file():
        raise RuntimeError("original monitor anomaly evidence is missing")
    original_status = read_json(original_status_path)
    original_runtime = read_json(original_runtime_path)
    codes = {
        str(item.get("code"))
        for item in original_status.get("findings", [])
        if isinstance(item, dict)
    }
    if original_status.get("state") != "ANOMALY":
        raise RuntimeError("original release monitor is not sealed as ANOMALY")
    if "PROGRESS_STALLED" not in codes:
        raise RuntimeError("original release anomaly reason drift")
    if not original_runtime.get("manual_stop_at"):
        raise RuntimeError("original release process lacks approved safe stop")

    formal_decision = read_json(FORMAL / "decision.json")
    replay_decision = read_json(REPLAY / "decision.json")
    if verdict(FORMAL) != FORMAL_PASS:
        raise RuntimeError("formal E2 v7 did not pass")
    if formal_decision.get("task_count") != 405:
        raise RuntimeError("formal E2 task count is not 405")
    if formal_decision.get("returned_solution_count") != 1620:
        raise RuntimeError("formal E2 solution count is not 1620")
    if formal_decision.get("full_model_feasible_solution_count") != 1620:
        raise RuntimeError("formal E2 feasible solution count is not 1620")
    if verdict(REPLAY) != REPLAY_PASS:
        raise RuntimeError("full witness replay did not pass")
    if replay_decision.get("task_count") != 405:
        raise RuntimeError("witness replay task count is not 405")
    if replay_decision.get("solution_count") != 1620:
        raise RuntimeError("witness replay solution count is not 1620")
    if replay_decision.get("all_costs_reproduced") is not True:
        raise RuntimeError("witness replay did not reproduce every cost")
    if replay_decision.get("all_full_model_feasible") is not True:
        raise RuntimeError("witness replay contains an infeasible solution")

    formal_manifest_count = verify_manifest(FORMAL)
    replay_manifest_count = verify_manifest(REPLAY)
    return [
        {
            "stage": "formal_e2",
            "status": "REUSED_PASS",
            "observed": FORMAL_PASS,
            "required": FORMAL_PASS,
            "returncode": 0,
            "manifest_entries": formal_manifest_count,
            "detail": "405 tasks and 1620 feasible solutions; no rerun",
        },
        {
            "stage": "full_witness_replay",
            "status": "REUSED_PASS",
            "observed": REPLAY_PASS,
            "required": REPLAY_PASS,
            "returncode": 0,
            "manifest_entries": replay_manifest_count,
            "detail": "1620 costs reproduced and feasible; no replay rerun",
        },
    ]


def heartbeat(stage: str, status: str, detail: str = "") -> None:
    payload = {
        "schema": "resetp.e2-v7-release-recovery-progress.v2",
        "updated_at_utc": datetime.now(UTC).isoformat(),
        "stage": stage,
        "status": status,
        "detail": detail,
    }
    write_json(RECOVERY / "progress.json", payload)
    write_json(
        CANONICAL / "progress.json",
        {
            "schema": "resetp.e2-staged-release-chain-progress.v1",
            "stage": stage,
            "status": status,
            "detail": f"recovery_v2:{detail}",
            "updated_at_epoch": datetime.now(UTC).timestamp(),
        },
    )


def run_stage(stage: dict[str, Any]) -> dict[str, Any]:
    name = str(stage["name"])
    gate = Path(stage["gate"])
    expected = str(stage["expected"])
    observed = verdict(gate)
    if (
        observed == expected
        and (gate / "done.json").is_file()
    ):
        manifest_count = verify_manifest(gate)
        heartbeat(name, "PASS_ALREADY_PRESENT", expected)
        return {
            "stage": name,
            "status": "REUSED_PASS",
            "observed": observed,
            "required": expected,
            "returncode": 0,
            "manifest_entries": manifest_count,
            "detail": "sealed PASS already present; no rerun",
        }
    if gate.exists() and any(gate.iterdir()):
        raise RuntimeError(f"{name} has incomplete pre-existing output: {gate}")

    heartbeat(name, "RUNNING", "frozen runner started")
    environment = dict(os.environ)
    environment.update(THREAD_ENV)
    log_path = RECOVERY / f"{name}.log"
    with log_path.open("a", encoding="utf-8") as handle:
        completed = subprocess.run(
            list(stage["command"]),
            cwd=REPO,
            env=environment,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    observed = verdict(gate)
    if not (gate / "decision.json").is_file():
        raise RuntimeError(
            f"{name} exited {completed.returncode} without decision"
        )
    manifest_count = verify_manifest(gate)
    row = {
        "stage": name,
        "status": "PASS" if observed == expected else "HALT",
        "observed": observed,
        "required": expected,
        "returncode": int(completed.returncode),
        "manifest_entries": manifest_count,
        "detail": "frozen downstream stage",
    }
    if observed != expected:
        raise StageHalt(
            f"{name} verdict mismatch: expected {expected}, got {observed}",
            row,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{name} returned {completed.returncode} despite PASS decision"
        )
    heartbeat(name, "PASS", expected)
    return row


def write_recovery_evidence(
    registration: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    release_verdict: str,
    reason: str,
) -> None:
    write_csv(RECOVERY / "raw_runs.csv", rows)
    decision = {
        "schema": "resetp.e2-v7-release-recovery-decision.v2",
        "verdict": (
            "PASS_E2_V7_RELEASE_RECOVERY"
            if release_verdict == RELEASE_PASS
            else "HALT_E2_V7_RELEASE_RECOVERY"
        ),
        "canonical_release_verdict": release_verdict,
        "reason": reason,
        "formal_search_rerun": False,
        "witness_replay_rerun": False,
        "claim_boundary": (
            "This recovery repairs monitor orchestration only. It does not "
            "change algorithms, inputs, budgets, seeds, evaluators, stage "
            "verdicts, paper-strength criteria, or sealed E2 scores."
        ),
    }
    write_json(RECOVERY / "decision.json", decision)
    metadata = {
        "schema": "resetp.e2-v7-release-recovery-metadata.v2",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            text=True,
        ).strip(),
        "registration_sha256": sha256(REGISTRATION),
        "source_hashes": registration["source_hashes"],
        "original_monitor_status_sha256": sha256(
            ORIGINAL_MONITOR / "status.json"
        ),
        "original_monitor_runtime_sha256": sha256(
            ORIGINAL_MONITOR / "runtime.json"
        ),
        "thread_environment": THREAD_ENV,
    }
    write_json(RECOVERY / "metadata.json", metadata)
    (RECOVERY / "report.md").write_text(
        "\n".join(
            [
                "# E2 v7 release-chain recovery",
                "",
                f"Recovery decision: `{decision['verdict']}`.",
                "",
                f"Canonical release decision: `{release_verdict}`.",
                "",
                f"Reason: {reason}",
                "",
                (
                    "The formal 405-task campaign and 1620-solution witness "
                    "replay were verified and reused without rerunning."
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    targets = (
        RECOVERY / "metadata.json",
        RECOVERY / "raw_runs.csv",
        RECOVERY / "decision.json",
        RECOVERY / "report.md",
    )
    write_json(
        RECOVERY / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "files": {path.name: sha256(path) for path in targets},
            "exclusions": [
                "artifact_hashes.json",
                "done.json",
                "progress.json",
                "*.log",
                "._*",
                "__pycache__",
                ".pytest_cache",
                "*.tmp",
            ],
        },
    )
    write_json(
        RECOVERY / "done.json",
        {
            "schema": "resetp.e2-v7-release-recovery-done.v2",
            "verdict": decision["verdict"],
            "artifact_hashes_sha256": sha256(
                RECOVERY / "artifact_hashes.json"
            ),
        },
    )


def write_canonical_release(
    rows: list[dict[str, Any]],
    *,
    release_verdict: str,
    reason: str,
) -> None:
    decision = {
        "schema": "resetp.e2-staged-release-chain-decision.v1",
        "verdict": release_verdict,
        "formal_verdict": FORMAL_PASS,
        "replay_verdict": REPLAY_PASS,
        "recovered_after_monitor_anomaly": True,
        "recovery_evidence": str(RECOVERY.relative_to(REPO)),
        "reason": reason,
        "stages": [row["stage"] for row in rows],
    }
    write_json(CANONICAL / "decision.json", decision)
    (CANONICAL / "report.md").write_text(
        "\n".join(
            [
                "# E2 staged-v7 release chain",
                "",
                f"Decision: `{release_verdict}`.",
                "",
                (
                    "The original nested witness monitor stalled after the "
                    "sealed replay PASS. Recovery v2 verified and reused that "
                    "evidence, then continued the frozen downstream stages."
                ),
                "",
                f"Reason: {reason}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    canonical_targets = (
        CANONICAL / "decision.json",
        CANONICAL / "report.md",
    )
    write_json(
        CANONICAL / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "artifacts": {
                path.name: sha256(path)
                for path in canonical_targets
                if path.is_file()
            },
            "exclusions": [
                "artifact_hashes.json",
                "done.json",
                "._*",
            ],
        },
    )
    if release_verdict == RELEASE_PASS:
        write_json(
            CANONICAL / "done.json",
            {
                "schema": "resetp.e2-staged-release-chain-done.v1",
                "verdict": release_verdict,
                "decision_sha256": sha256(CANONICAL / "decision.json"),
                "recovery_done_sha256": sha256(RECOVERY / "done.json"),
            },
        )


def execute() -> int:
    registration = verify_registration()
    if RECOVERY.exists():
        raise RuntimeError(f"recovery output already exists: {RECOVERY}")
    if (CANONICAL / "decision.json").exists():
        raise RuntimeError("canonical release already has a terminal decision")
    RECOVERY.mkdir(parents=True, exist_ok=False)
    rows: list[dict[str, Any]] = []
    try:
        rows.extend(verify_completed_upstream())
        heartbeat(
            "upstream_integrity",
            "PASS",
            "formal and replay evidence verified without rerun",
        )
        for stage in STAGES:
            rows.append(run_stage(stage))
        release_verdict = RELEASE_PASS
        reason = "all frozen downstream stages passed"
        write_recovery_evidence(
            registration,
            rows,
            release_verdict=release_verdict,
            reason=reason,
        )
        write_canonical_release(
            rows,
            release_verdict=release_verdict,
            reason=reason,
        )
        heartbeat("release_recovery", "PASS", release_verdict)
        return 0
    except Exception as exc:
        release_verdict = RELEASE_HALT
        reason = str(exc)
        if isinstance(exc, StageHalt):
            rows.append(exc.row)
        if not rows:
            rows.append(
                {
                    "stage": "recovery_precondition",
                    "status": "HALT",
                    "observed": type(exc).__name__,
                    "required": "all preconditions pass",
                    "returncode": 2,
                    "manifest_entries": 0,
                    "detail": reason,
                }
            )
        write_recovery_evidence(
            registration,
            rows,
            release_verdict=release_verdict,
            reason=reason,
        )
        write_canonical_release(
            rows,
            release_verdict=release_verdict,
            reason=reason,
        )
        heartbeat("release_recovery", "HALT", reason)
        return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="run the registered downstream recovery",
    )
    args = parser.parse_args()
    registration = verify_registration()
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "CONTRACT_ONLY_PASS",
                    "registration": str(REGISTRATION.relative_to(REPO)),
                    "source_hash_count": len(registration["source_hashes"]),
                    "recovery_output_exists": RECOVERY.exists(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    return execute()


if __name__ == "__main__":
    raise SystemExit(main())
