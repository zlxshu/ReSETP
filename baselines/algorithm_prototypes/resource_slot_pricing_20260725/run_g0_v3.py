#!/usr/bin/env python3
"""Spawn-safe orchestration of the unchanged frozen six-task G0."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from multiprocessing import get_context
from pathlib import Path
import sys


PACKAGE = Path(__file__).resolve().parent
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

import common  # noqa: E402
from worker_entry_v3 import g0_worker  # noqa: E402


REGISTRATION = PACKAGE / "g0_registration_v3.json"
ENGINEERING = PACKAGE / "engineering_gate_v3"
OUTPUT = PACKAGE / "g0_gate_v3"
common.REGISTRATION = REGISTRATION
common.ENGINEERING = ENGINEERING
common.OUTPUT = OUTPUT


def error_row(task: dict, message: str) -> dict:
    return {
        "task_id": task["task_id"],
        "instance_id": task["instance_id"],
        "lane": task["lane"],
        "status": "ERROR",
        "start_objective": "",
        "output_objective": "",
        "complete_candidate_evaluations": 0,
        "label_extensions": 0,
        "violation_count": 1,
        "error": message,
    }


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"v3 G0 output exists: {OUTPUT}")
    engineering = common.read_json(ENGINEERING / "decision.json")
    if not engineering.get("pass"):
        raise RuntimeError("v3 engineering gate did not pass")
    registration = common.verify_registration()
    config = registration["config"]
    OUTPUT.mkdir(parents=True)
    common.write_json(
        OUTPUT / "metadata.json",
        {
            "schema": "resetp.resource-slot-pricing-g0.v3",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "workers": int(config["workers"]),
            "tasks": len(registration["tasks"]),
            "claim_boundary": registration["claim_boundary"],
        },
    )
    rows = []
    failures = []
    context = get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=int(config["workers"]),
        mp_context=context,
    ) as pool:
        futures = {
            pool.submit(g0_worker, task, config): task
            for task in registration["tasks"]
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:  # noqa: BLE001
                message = f"{task['task_id']}: {type(exc).__name__}: {exc}"
                failures.append(message)
                rows.append(error_row(task, message))
    rows.sort(key=lambda row: row["task_id"])
    common.write_csv(OUTPUT / "raw_runs.csv", rows)
    common.write_json(
        OUTPUT / "run_status.json",
        {
            "schema": "resetp.resource-slot-pricing-run-status.v3",
            "failures": failures,
            "completed_rows": sum(row["status"] == "OK" for row in rows),
            "expected_rows": 6,
        },
    )
    print(json.dumps({"rows": len(rows), "failures": failures}, ensure_ascii=False))
    return 0 if not failures and len(rows) == 6 else 2


if __name__ == "__main__":
    raise SystemExit(main())
