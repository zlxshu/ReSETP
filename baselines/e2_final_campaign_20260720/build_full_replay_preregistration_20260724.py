#!/usr/bin/env python3
"""Freeze the corrected E2 v4 no-search witness replay inputs."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CAMPAIGN_NAME = os.environ.get(
    "RESET_D6_CAMPAIGN_NAME",
    "corrected_china81_rerun_v4_20260724",
)
if (
    not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", CAMPAIGN_NAME)
    or not CAMPAIGN_NAME.startswith("corrected_china81_rerun_")
):
    raise RuntimeError(
        f"invalid RESET_D6_CAMPAIGN_NAME: {CAMPAIGN_NAME!r}"
    )
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / CAMPAIGN_NAME
)
FULL = CAMPAIGN / "full_gate"
OUT = CAMPAIGN / "full_witness_replay_preregistration.json"
REPLAY_SCRIPT = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / "corrected_china81_rerun_20260723"
    / "replay_corrected_d6_witnesses.py"
)
FORMAL_HELPER = (
    REPO / "baselines/china_e3_e7/formal_e3_runner.py"
)
RELEASE_CONFIG = (
    REPO / "baselines/china_e3_e7/release_v6_config.py"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(REPO))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite replay freeze: {OUT}")
    decision_path = FULL / "decision.json"
    raw_path = FULL / "raw_runs.csv"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if (
        decision.get("verdict")
        != "PASS_D6_CORRECTED_CHINA81_E2_RAW"
        or decision.get("task_count") != 405
    ):
        raise RuntimeError("corrected E2 full decision is not 405-task PASS")
    source_paths = (
        raw_path,
        decision_path,
        REPLAY_SCRIPT,
        FORMAL_HELPER,
        RELEASE_CONFIG,
        REPO / "solver/src/setp_solver/china81.py",
        REPO / "solver/src/setp_solver/china81_completion.py",
        REPO / "solver/src/setp_solver/cost.py",
        REPO / "solver/src/setp_solver/check.py",
        REPO / "solver/src/setp_solver/prices.py",
        REPO / "solver/src/setp_solver/solution.py",
        REPO / "solver/src/setp_solver/instance_loader.py",
        REPO / "solver/src/setp_solver/charging_curve.py",
        REPO / "solver/src/setp_solver/search/charging.py",
        REPO
        / "solver/src/setp_solver/algorithms/resetp_alns"
        / "support/charging.py",
    )
    payload = {
        "schema": "resetp.d6-full-witness-replay-preregistration.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "campaign_name": CAMPAIGN_NAME,
        "operation": "NO_SEARCH_INDEPENDENT_REPLAY_ONLY",
        "expected_tasks": 405,
        "expected_solutions": 1620,
        "expected_instances": 81,
        "expected_seeds_per_instance": [1, 2, 3, 4, 5],
        "expected_complete_candidate_attempts_per_task": 80,
        "required_verdict": "PASS_D6_CORRECTED_CHINA81_E2_RAW",
        "source_hashes": {
            relative(path): sha256(path)
            for path in source_paths
        },
        "failure_policy": (
            "halt on any missing file, hash drift, duplicate task, "
            "infeasible solution, cost or emissions mismatch, mixed "
            "city/date/slot identity, charging-date breach, charging after "
            "departure, or depot-by-powertrain fleet-cap breach"
        ),
        "search_evaluations": 0,
    }
    write_json(OUT, payload)
    print(
        json.dumps(
            {
                "status": "PASS_D6_REPLAY_PREREGISTRATION_FROZEN",
                "campaign_name": CAMPAIGN_NAME,
                "sha256": sha256(OUT),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
