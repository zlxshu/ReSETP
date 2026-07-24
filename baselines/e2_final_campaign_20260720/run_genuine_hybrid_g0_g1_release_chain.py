#!/usr/bin/env python3
"""Wait for protected E2 v7, then run genuine-hybrid G0 and G1 in order."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
REGISTRATION = PACKAGE / "g0_g1_release_chain_registration_v1.json"
OUT = PACKAGE / "g0_g1_release_chain_v1"
PROGRESS = OUT / "progress.json"
PYTHON = REPO / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
G0_RUNNER = PACKAGE / "run_g0_real_bundle_preflight.py"
G1_RUNNER = PACKAGE / "run_g1_micro_gate.py"
G0_GATE = PACKAGE / "g0_real_bundle_gate_v1"
G1_GATE = PACKAGE / "g1_micro_gate_v2"
FORMAL_CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
RELEASE_DECISION = FORMAL_CAMPAIGN / "release_chain/decision.json"
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}

for path in (
    REPO,
    REPO / "solver/src",
    REPO / "models/src",
    REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720",
    PACKAGE,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_g0_real_bundle_preflight as g0_runtime  # noqa: E402


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
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("release-chain rows cannot be empty")
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


def verify_registration() -> dict[str, Any]:
    registration = read_json(REGISTRATION)
    if (
        registration.get("schema")
        != "resetp.genuine-hybrid-g0-g1-release-chain-registration.v1"
    ):
        raise RuntimeError("unexpected genuine-hybrid release registration")
    if registration.get("status") != "FROZEN_BEFORE_RELEASE":
        raise RuntimeError("genuine-hybrid release registration status drift")
    sources = registration.get("source_hashes")
    if not isinstance(sources, dict) or not sources:
        raise RuntimeError("release registration has no source hashes")
    for relative, expected in sources.items():
        path = REPO / str(relative)
        if not path.is_file():
            raise RuntimeError(f"registered source missing: {relative}")
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(
                f"registered source hash mismatch: {relative}:{expected}:{actual}"
            )
    return registration


def verify_artifacts(root: Path) -> dict[str, str]:
    manifest_path = root / "artifact_hashes.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"artifact manifest missing: {manifest_path}")
    manifest = read_json(manifest_path)
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError(f"artifact manifest empty: {manifest_path}")
    for relative, expected in files.items():
        path = root / str(relative)
        if not path.is_file():
            raise RuntimeError(f"artifact missing: {path}")
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"artifact hash mismatch: {path}:{expected}:{actual}")
    return {str(key): str(value) for key, value in files.items()}


def update_progress(
    *,
    stage: str,
    status: str,
    detail: str,
) -> None:
    write_json(
        PROGRESS,
        {
            "schema": "resetp.genuine-hybrid-g0-g1-progress.v1",
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "status": status,
            "detail": detail,
        },
    )


def wait_for_release(
    registration: dict[str, Any],
    poll_seconds: float,
) -> tuple[str, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    required = str(registration["required_v7_release_verdict"])
    while True:
        release_verdict = "MISSING"
        if RELEASE_DECISION.is_file():
            release_verdict = str(read_json(RELEASE_DECISION).get("verdict", "UNKNOWN"))
        resource = g0_runtime.formal_resource_state()
        if release_verdict not in {"MISSING", required}:
            rows.append(
                {
                    "stage": "protected_e2_v7_release",
                    "status": "STOP",
                    "decision": release_verdict,
                    "detail": "upstream release did not pass",
                }
            )
            return "STOP_UPSTREAM_E2_V7_RELEASE", rows
        if release_verdict == required and not resource["formal_running"]:
            rows.append(
                {
                    "stage": "protected_e2_v7_release",
                    "status": "PASS",
                    "decision": release_verdict,
                    "detail": "release passed and protected processes exited",
                }
            )
            return "READY", rows
        update_progress(
            stage="protected_e2_v7_release",
            status="WAITING",
            detail=(
                f"release={release_verdict};"
                f"formal_running={resource['formal_running']};"
                f"completed_tasks={resource['completed_tasks']}"
            ),
        )
        time.sleep(poll_seconds)


def run_stage(
    *,
    stage: str,
    command: list[str],
    gate: Path,
    decision_field: str,
) -> tuple[str, int]:
    if gate.exists():
        verify_artifacts(gate)
        decision = str(read_json(gate / "decision.json").get(decision_field, "UNKNOWN"))
        return decision, 0
    update_progress(stage=stage, status="RUNNING", detail="subprocess started")
    environment = dict(os.environ)
    environment.update(THREAD_ENV)
    log_path = OUT / f"{stage}.log"
    with log_path.open("a", encoding="utf-8") as handle:
        completed = subprocess.run(
            command,
            cwd=REPO,
            env=environment,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if not (gate / "decision.json").is_file():
        raise RuntimeError(
            f"{stage} exited {completed.returncode} without decision artifact"
        )
    verify_artifacts(gate)
    decision = str(read_json(gate / "decision.json").get(decision_field, "UNKNOWN"))
    return decision, int(completed.returncode)


def terminal_write(
    registration: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    decision: str,
) -> None:
    write_csv(OUT / "raw_runs.csv", rows)
    decision_payload = {
        "schema": "resetp.genuine-hybrid-g0-g1-release-chain-decision.v1",
        "decision": decision,
        "required_v7_release_verdict": registration["required_v7_release_verdict"],
        "g0_decision": next(
            (row["decision"] for row in rows if row["stage"] == "g0_real_bundle"),
            "NOT_RUN",
        ),
        "g1_decision": next(
            (row["decision"] for row in rows if row["stage"] == "g1_micro"),
            "NOT_RUN",
        ),
        "claim_boundary": (
            "This chain only preserves execution order. G0 proves wiring only; "
            "G1 is a three-development-instance micro gate and cannot support "
            "formal China81, BKS, or SOTA claims."
        ),
    }
    write_json(OUT / "decision.json", decision_payload)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.genuine-hybrid-g0-g1-release-chain-metadata.v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO,
                text=True,
            ).strip(),
            "registration_sha256": sha256(REGISTRATION),
            "source_hashes": registration["source_hashes"],
            "thread_environment": THREAD_ENV,
        },
    )
    report = "\n".join(
        [
            "# Genuine hybrid G0--G1 release chain",
            "",
            f"Decision: `{decision}`.",
            "",
            *[
                (
                    f"- `{row['stage']}`: {row['status']} / "
                    f"`{row['decision']}` — {row['detail']}"
                )
                for row in rows
            ],
            "",
            (
                "The chain did not change algorithms, budgets, inputs, "
                "evaluators, or acceptance gates."
            ),
            "",
        ]
    )
    (OUT / "report.md").write_text(report, encoding="utf-8")
    targets = (
        OUT / "metadata.json",
        OUT / "raw_runs.csv",
        OUT / "decision.json",
        OUT / "report.md",
    )
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "files": {path.name: sha256(path) for path in targets},
        },
    )
    write_json(
        OUT / "done.json",
        {
            "schema": "resetp.genuine-hybrid-g0-g1-done.v1",
            "decision": decision,
            "artifact_hashes_sha256": sha256(OUT / "artifact_hashes.json"),
        },
    )
    update_progress(stage="terminal", status="COMPLETE", detail=decision)


def execute(poll_seconds: float) -> int:
    registration = verify_registration()
    if (OUT / "done.json").is_file():
        raise RuntimeError("release chain already has a terminal done marker")
    OUT.mkdir(parents=True, exist_ok=True)
    release_state, rows = wait_for_release(registration, poll_seconds)
    if release_state != "READY":
        terminal_write(registration, rows, decision=release_state)
        return 0

    g0_decision, g0_returncode = run_stage(
        stage="g0_real_bundle",
        command=[str(PYTHON), str(G0_RUNNER), "--execute"],
        gate=G0_GATE,
        decision_field="decision",
    )
    g0_pass = g0_decision == str(registration["required_g0_decision"])
    rows.append(
        {
            "stage": "g0_real_bundle",
            "status": "PASS" if g0_pass else "STOP",
            "decision": g0_decision,
            "detail": f"returncode={g0_returncode}",
        }
    )
    if not g0_pass:
        terminal_write(registration, rows, decision="STOP_G0_REAL_BUNDLE")
        return 0

    g1_decision, g1_returncode = run_stage(
        stage="g1_micro",
        command=[str(PYTHON), str(G1_RUNNER), "--workers", "3"],
        gate=G1_GATE,
        decision_field="decision",
    )
    valid_g1 = g1_decision in {
        "PASS_G1_COOPERATIVE_HYBRID_GAIN",
        "STOP_G1_NO_HYBRID_GAIN",
    }
    if not valid_g1:
        raise RuntimeError(f"unexpected G1 decision: {g1_decision}")
    rows.append(
        {
            "stage": "g1_micro",
            "status": (
                "PASS" if g1_decision == "PASS_G1_COOPERATIVE_HYBRID_GAIN" else "STOP"
            ),
            "decision": g1_decision,
            "detail": f"returncode={g1_returncode}",
        }
    )
    terminal = (
        "PASS_G0_G1_RELEASE_CHAIN"
        if g1_decision == "PASS_G1_COOPERATIVE_HYBRID_GAIN"
        else "STOP_G1_NO_HYBRID_GAIN"
    )
    terminal_write(registration, rows, decision=terminal)
    return 0


def check_contract() -> int:
    registration = verify_registration()
    resource = g0_runtime.formal_resource_state()
    print(
        json.dumps(
            {
                "contract": "PASS",
                "registered_sources": len(registration["source_hashes"]),
                "required_v7_release_verdict": registration[
                    "required_v7_release_verdict"
                ],
                "required_g0_decision": registration["required_g0_decision"],
                "formal_resource_state": resource,
                "output": str(OUT.relative_to(REPO)),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-contract", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    args = parser.parse_args()
    if args.check_contract:
        return check_contract()
    if float(args.poll_seconds) < 10.0:
        raise ValueError("poll interval must be at least 10 seconds")
    return execute(float(args.poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
