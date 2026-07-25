#!/usr/bin/env python3
"""Release genuine-hybrid development from mechanically valid E2 v7 evidence.

This gate does not run search, replay solutions, or reinterpret paper-strength
results. It may execute only after the existing staged release chain reaches a
terminal decision. A paper-strength or presentation-stage failure is allowed
to coexist with this mechanical release, but the formal E2 campaign and its
full independent witness replay must both have passed exactly.
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
REGISTRATION = CAMPAIGN / "mechanical_release_registration_v1.json"
OUT = CAMPAIGN / "mechanical_release_gate_v1"
FORMAL = CAMPAIGN / "full_gate"
REPLAY = CAMPAIGN / "full_witness_replay"
ORIGINAL_RELEASE = CAMPAIGN / "release_chain"

FORMAL_PASS = (
    "PASS_D6_CORRECTED_CHINA81_E2_STAGED_V7_SMALL_ARCHIVE_LEDGER"
)
REPLAY_PASS = "PASS_D6_STAGED_FULL_WITNESS_REPLAY"
ORIGINAL_TERMINAL = {
    "PASS_E2_STAGED_V7_RELEASE_CHAIN",
    "HALT_E2_STAGED_V7_RELEASE_CHAIN",
}
MECHANICAL_PASS = "PASS_E2_V7_MECHANICAL_INTEGRITY_RELEASE"


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
        raise ValueError("mechanical release evidence rows cannot be empty")
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


def verify_manifest(root: Path) -> tuple[int, list[str]]:
    manifest_path = root / "artifact_hashes.json"
    if not manifest_path.is_file():
        return 0, ["artifact_hashes.json missing"]
    manifest = read_json(manifest_path)
    entries = manifest.get("artifacts", manifest.get("files", {}))
    if not isinstance(entries, dict) or not entries:
        return 0, ["artifact manifest has no entries"]
    failures: list[str] = []
    for relative, expected in entries.items():
        raw = Path(str(relative))
        candidates = (
            [raw]
            if raw.is_absolute()
            else [root / raw, REPO / raw]
        )
        artifact = next(
            (candidate for candidate in candidates if candidate.is_file()),
            None,
        )
        if artifact is None:
            failures.append(f"{relative}:missing")
        elif sha256(artifact) != str(expected):
            failures.append(f"{relative}:hash_mismatch")
    return len(entries), failures


def verify_registration() -> dict[str, Any]:
    if not REGISTRATION.is_file():
        raise RuntimeError("mechanical release registration is missing")
    registration = read_json(REGISTRATION)
    if (
        registration.get("schema")
        != "resetp.e2-v7-mechanical-release-registration.v1"
    ):
        raise RuntimeError("unexpected mechanical release registration schema")
    if registration.get("status") != "FROZEN_BEFORE_TERMINAL_E2_RESULTS":
        raise RuntimeError("mechanical release registration status drift")
    source_hashes = registration.get("source_hashes")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise RuntimeError("mechanical release registration has no source hashes")
    for relative, expected in source_hashes.items():
        source = REPO / str(relative)
        if not source.is_file():
            raise RuntimeError(f"registered source missing: {relative}")
        actual = sha256(source)
        if actual != str(expected):
            raise RuntimeError(
                f"registered source drift: {relative}:{expected}:{actual}"
            )
    return registration


def evidence_state() -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    failures: list[str] = []

    checks = (
        ("formal_e2", FORMAL, FORMAL_PASS),
        ("full_witness_replay", REPLAY, REPLAY_PASS),
    )
    for stage, root, required in checks:
        decision_path = root / "decision.json"
        done_path = root / "done.json"
        observed = "MISSING"
        decision: dict[str, Any] = {}
        if decision_path.is_file():
            decision = read_json(decision_path)
            observed = str(decision.get("verdict", "UNKNOWN"))
        manifest_count, manifest_failures = verify_manifest(root)
        count_checks = (
            (
                decision.get("task_count") == 405
                and decision.get("returned_solution_count") == 1620
                and decision.get("full_model_feasible_solution_count") == 1620
            )
            if stage == "formal_e2"
            else (
                decision.get("task_count") == 405
                and decision.get("solution_count") == 1620
                and decision.get("unique_task_arm_count") == 1620
                and decision.get("all_costs_reproduced") is True
                and decision.get("all_full_model_feasible") is True
            )
        )
        passed = (
            observed == required
            and done_path.is_file()
            and manifest_count > 0
            and not manifest_failures
            and count_checks
        )
        rows.append(
            {
                "stage": stage,
                "observed": observed,
                "required": required,
                "done_present": done_path.is_file(),
                "count_checks": count_checks,
                "manifest_entries": manifest_count,
                "manifest_failures": "|".join(manifest_failures),
                "status": "PASS" if passed else "FAIL",
            }
        )
        if not passed:
            failures.append(stage)

    release_decision_path = ORIGINAL_RELEASE / "decision.json"
    release_done_path = ORIGINAL_RELEASE / "done.json"
    release_observed = "MISSING"
    if release_decision_path.is_file():
        release_observed = str(
            read_json(release_decision_path).get("verdict", "UNKNOWN")
        )
    release_terminal = release_observed in ORIGINAL_TERMINAL
    rows.append(
        {
            "stage": "original_release_chain_terminal",
            "observed": release_observed,
            "required": "|".join(sorted(ORIGINAL_TERMINAL)),
            "done_present": release_done_path.is_file(),
            "count_checks": "",
            "manifest_entries": "",
            "manifest_failures": "",
            "status": "PASS" if release_terminal else "FAIL",
        }
    )
    if not release_terminal:
        failures.append("original_release_chain_terminal")

    task_root = FORMAL / "tasks"
    task_count = (
        sum(
            1
            for path in task_root.iterdir()
            if path.is_dir() and not path.name.startswith("._")
        )
        if task_root.is_dir()
        else 0
    )
    rows.append(
        {
            "stage": "formal_task_directory_count",
            "observed": task_count,
            "required": 405,
            "done_present": "",
            "count_checks": task_count == 405,
            "manifest_entries": "",
            "manifest_failures": "",
            "status": "PASS" if task_count == 405 else "FAIL",
        }
    )
    if task_count != 405:
        failures.append("formal_task_directory_count")

    return rows, failures


def seal(
    registration: dict[str, Any],
    rows: list[dict[str, Any]],
    failures: list[str],
) -> str:
    OUT.mkdir(parents=True, exist_ok=False)
    verdict = (
        MECHANICAL_PASS
        if not failures
        else "HALT_E2_V7_MECHANICAL_INTEGRITY_RELEASE"
    )
    write_csv(OUT / "raw_runs.csv", rows)
    decision = {
        "schema": "resetp.e2-v7-mechanical-release-decision.v1",
        "verdict": verdict,
        "failure_checks": failures,
        "formal_search_performed": False,
        "search_evaluations": 0,
        "claim_boundary": (
            "This gate releases only low-cost genuine-hybrid development after "
            "the corrected E2 v7 campaign and all 1620 saved solutions pass "
            "independent replay. It does not override the original paper-"
            "strength, trajectory, route-detail, artifact, BKS, or SOTA gates."
        ),
    }
    write_json(OUT / "decision.json", decision)
    metadata = {
        "schema": "resetp.e2-v7-mechanical-release-metadata.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            text=True,
        ).strip(),
        "registration_sha256": sha256(REGISTRATION),
        "source_hashes": registration["source_hashes"],
        "formal_search_performed": False,
        "search_evaluations": 0,
    }
    write_json(OUT / "metadata.json", metadata)
    original_release = next(
        row["observed"]
        for row in rows
        if row["stage"] == "original_release_chain_terminal"
    )
    (OUT / "report.md").write_text(
        "\n".join(
            [
                "# E2 v7 mechanical integrity release",
                "",
                f"Decision: `{verdict}`.",
                "",
                f"Original staged release verdict: `{original_release}`.",
                "",
                (
                    "This zero-search gate separates mechanical integrity from "
                    "paper-strength and presentation acceptance. Existing "
                    "upstream PASS/HALT evidence remains unchanged."
                ),
                "",
                f"Failed checks: `{failures}`.",
                "",
            ]
        ),
        encoding="utf-8",
    )
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
            "exclusions": [
                "artifact_hashes.json",
                "done.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
                "*.tmp",
            ],
        },
    )
    write_json(
        OUT / "done.json",
        {
            "schema": "resetp.e2-v7-mechanical-release-done.v1",
            "verdict": verdict,
            "artifact_hashes_sha256": sha256(OUT / "artifact_hashes.json"),
        },
    )
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="seal the terminal gate; without this flag only validate registration",
    )
    args = parser.parse_args()

    registration = verify_registration()
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "CONTRACT_ONLY_PASS",
                    "registration": str(REGISTRATION.relative_to(REPO)),
                    "output_exists": OUT.exists(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if OUT.exists():
        raise RuntimeError(f"mechanical release output already exists: {OUT}")
    rows, failures = evidence_state()
    verdict = seal(registration, rows, failures)
    return 0 if verdict == MECHANICAL_PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
