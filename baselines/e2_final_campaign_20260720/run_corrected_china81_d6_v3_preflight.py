#!/usr/bin/env python3
"""Three-size preflight for corrected China81 D6 v3."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
for path in (REPO / "solver/src", Path(__file__).resolve().parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_corrected_china81_d6 as d6  # noqa: E402


OUT = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / d6.CAMPAIGN_NAME
    / "preflight_gate"
)
TASKS = (
    ("cn-prd-10c-01-V2-LOCATIONS", 1),
    ("cn-prd-75c-01-V2-LOCATIONS", 1),
    ("cn-prd-200c-01-V2-LOCATIONS", 1),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    if any(
        os.environ.get(key) != value
        for key, value in d6.REQUIRED_THREAD_ENV.items()
    ):
        raise RuntimeError("single-thread environment is not fully locked")
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite preflight: {OUT}")
    OUT.mkdir(parents=True)
    d6.OUT = OUT
    rows = [d6._run_unit(task) for task in TASKS]
    ev_counts: dict[str, dict[str, int]] = {}
    for row in rows:
        task_id = str(row["task_id"])
        witnesses = json.loads(
            (
                OUT
                / "tasks"
                / task_id
                / "solution_witnesses.json"
            ).read_text(encoding="utf-8")
        )
        ev_counts[task_id] = {
            arm: sum(
                route["vehicle_type"].lower() == "ev"
                for route in payload["routes"]
            )
            for arm, payload in witnesses.items()
        }
    all_pass = all(
        row["status"] == "PASS"
        and row["all_charging_on_registered_date"]
        and row["all_depot_charging_finishes_before_departure"]
        and row["all_depot_fleet_caps_respected"]
        and int(row["complete_candidate_attempts"]) == 80
        and not row["wallclock_safety_triggered"]
        for row in rows
    )
    ev_observed = any(
        count > 0
        for by_arm in ev_counts.values()
        for count in by_arm.values()
    )
    write_csv(OUT / "raw_runs.csv", rows)
    decision = {
        "schema": "resetp.d6-e2-corrected-v3-preflight.v1",
        "verdict": (
            "PASS_D6_V3_PREFLIGHT"
            if all_pass and ev_observed
            else "HALT_D6_V3_PREFLIGHT"
        ),
        "task_count": len(rows),
        "all_tasks_passed": all_pass,
        "ev_routes_observed": ev_observed,
        "ev_route_counts": ev_counts,
        "formal_e3_search_allowed": False,
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.d6-e2-corrected-v3-preflight.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "builder": str(Path(__file__).relative_to(REPO)),
            "source_hashes": {
                str(Path(__file__).relative_to(REPO)): sha256(
                    Path(__file__)
                ),
                str(d6.CONTRACT.relative_to(REPO)): sha256(
                    d6.CONTRACT
                ),
                str(
                    Path(d6.__file__).resolve().relative_to(REPO)
                ): sha256(Path(d6.__file__).resolve()),
            },
        },
    )
    (OUT / "report.md").write_text(
        "# China81 corrected v3 preflight\n\n"
        "Three registered PRD sizes were run once under the corrected "
        "same-day predeparture charging checker and hard depot-by-type "
        "fleet caps. The gate also requires at least one returned EV "
        "route, so an accidental all-diesel collapse cannot pass.\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if decision["verdict"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
