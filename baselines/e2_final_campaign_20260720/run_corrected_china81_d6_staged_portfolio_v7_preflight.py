#!/usr/bin/env python3
"""Result-blind V7 preflight on one small, medium, and large China81 task."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


CAMPAIGN_NAME = (
    "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
os.environ["RESET_D6_CAMPAIGN_NAME"] = CAMPAIGN_NAME
LAUNCHER = (
    Path(__file__).resolve().parent
    / "run_corrected_china81_d6_staged_portfolio_"
    "v7_small_archive_ledger.py"
)
os.environ["RESET_D6_LAUNCHER_SOURCE"] = str(LAUNCHER)

import run_corrected_china81_d6_staged_portfolio_v6_budget_recheck as registered  # noqa: E402


REPO = registered.REPO
CAMPAIGN_ROOT = registered.frozen.CAMPAIGN_ROOT / CAMPAIGN_NAME
OUT = CAMPAIGN_ROOT / "preflight_gate"
PREREGISTRATION = CAMPAIGN_ROOT / "formal_preregistration_v4.json"
TASKS = (
    ("cn-cy-10c-01-V2-LOCATIONS", 1),
    ("cn-cy-100c-01-V2-LOCATIONS", 1),
    ("cn-cy-200c-01-V2-LOCATIONS", 1),
)


def _write_root_records(rows: list[dict[str, Any]]) -> dict[str, Any]:
    registered.frozen.corrected_base.write_csv(
        OUT / "raw_runs.csv",
        rows,
    )
    mechanical_pass = (
        len(rows) == len(TASKS)
        and all(row["status"] == "PASS" for row in rows)
        and all(
            int(row["complete_candidate_attempts"]) == 280
            for row in rows
        )
        and all(
            int(row["historical_population_snapshot_count"]) == 120
            for row in rows
        )
        and all(
            bool(row["historical_archive_selection_complete"])
            for row in rows
        )
        and all(
            bool(row["all_independently_feasible"])
            for row in rows
        )
    )
    verdict = (
        "PASS_D6_E2_STAGED_V7_PREFLIGHT"
        if mechanical_pass
        else "HALT_D6_E2_STAGED_V7_PREFLIGHT"
    )
    decision = {
        "schema": "resetp.d6-e2-staged-v7-preflight.decision.v1",
        "verdict": verdict,
        "task_count": len(rows),
        "tasks": [row["task_id"] for row in rows],
        "mechanical_pass": mechanical_pass,
        "formal_results_reused": False,
        "formal_start_allowed": mechanical_pass,
        "claim_boundary": (
            "Mechanical preflight only; no comparative paper result or "
            "formal China81 observation."
        ),
    }
    registered.frozen.corrected_base.write_json(
        OUT / "decision.json",
        decision,
    )
    registered.frozen.corrected_base.write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.d6-e2-staged-v7-preflight.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "preregistration_sha256": (
                registered.frozen.corrected_base.file_sha256(
                    PREREGISTRATION
                )
            ),
            "source_hashes": registered.frozen._source_hashes(),
            "thread_environment": (
                registered.frozen.REQUIRED_THREAD_ENV
            ),
            "formal_output_directory": str(
                CAMPAIGN_ROOT / "full_gate"
            ),
            "formal_output_written": False,
        },
    )
    (OUT / "report.md").write_text(
        "# V7 small-archive ledger preflight\n\n"
        f"Verdict: `{verdict}`.\n\n"
        "The preflight executes the frozen V7 task path on one 10-, 100-, "
        "and 200-customer instance. The small task must pass by selecting "
        "every available archive candidate; larger tasks must retain the "
        "quality-diversity split. All returned solutions are checked under "
        "the complete model. These task outputs are isolated from and may "
        "not be reused by the 405-task formal campaign.\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(OUT)): (
            registered.frozen.corrected_base.file_sha256(path)
        )
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
            and ".pytest_cache" not in path.parts
        )
    }
    registered.frozen.corrected_base.write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
            ],
            "artifacts": artifacts,
        },
    )
    return decision


def main() -> int:
    if not PREREGISTRATION.is_file():
        raise FileNotFoundError(PREREGISTRATION)
    if any(
        os.environ.get(key) != expected
        for key, expected in registered.frozen.REQUIRED_THREAD_ENV.items()
    ):
        raise RuntimeError("single-thread environment is not fully locked")

    OUT.mkdir(parents=True, exist_ok=True)
    registered.OUT = OUT
    registered.frozen.OUT = OUT
    registered.PREREGISTRATION = PREREGISTRATION
    registered.frozen.PREREGISTRATION = PREREGISTRATION

    rows = [
        registered._run_unit_v6(instance_id, seed)
        for instance_id, seed in TASKS
    ]
    decision = _write_root_records(rows)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if decision["mechanical_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
