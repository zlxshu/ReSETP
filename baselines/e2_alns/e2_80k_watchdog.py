#!/usr/bin/env python3
"""Low-frequency watchdog for the 24-task 80 kWh mirror ledger."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import time
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase_dir")
    parser.add_argument("--expected", type=int, default=24)
    parser.add_argument("--interval-seconds", type=int, default=1800)
    parser.add_argument("--stale-seconds", type=int, default=7200)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def snapshot(phase_dir: Path, expected: int, stale_seconds: int) -> dict[str, Any]:
    ledger = phase_dir / "task_runs.csv"
    rows = list(csv.DictReader(ledger.open(encoding="utf-8"))) if ledger.exists() else []
    healthy = [
        row
        for row in rows
        if row.get("gate_status") == "OK"
        and int(float(row.get("actual_evals", -1))) == int(float(row.get("eval_budget", -2)))
        and int(float(row.get("violation_count", -1))) == 0
    ]
    failures = [row for row in rows if row not in healthy]
    now = time.time()
    last_progress = ledger.stat().st_mtime if ledger.exists() else now
    seconds_since_progress = max(0.0, now - last_progress)
    return {
        "schema": "setp-e2-80k-watchdog.v1",
        "phase_dir": str(phase_dir),
        "ledger": "task_runs.csv",
        "expected_search_tasks": int(expected),
        "completed_search_tasks": len(healthy),
        "remaining_search_tasks": max(0, int(expected) - len(healthy)),
        "failure_count": len(failures),
        "failure_sample": [
            {
                "run_id": row.get("run_id"),
                "gate_status": row.get("gate_status"),
                "failure_reason": row.get("failure_reason"),
            }
            for row in failures[:10]
        ],
        "seconds_since_progress": seconds_since_progress,
        "stale": len(healthy) < int(expected) and seconds_since_progress >= int(stale_seconds),
        "complete": len(healthy) == int(expected) and not failures,
        "checked_at_epoch": now,
    }


def write_snapshot(phase_dir: Path, payload: dict[str, Any]) -> None:
    target = phase_dir / "watchdog.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(target)
    with (phase_dir / "watchdog_history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    args = parse_args()
    phase_dir = Path(args.phase_dir).resolve()
    phase_dir.mkdir(parents=True, exist_ok=True)
    while True:
        payload = snapshot(phase_dir, int(args.expected), int(args.stale_seconds))
        write_snapshot(phase_dir, payload)
        if args.once or payload["complete"] or payload["failure_count"] or payload["stale"]:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
            return 0 if not payload["failure_count"] and not payload["stale"] else 2
        time.sleep(max(1800, int(args.interval_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
