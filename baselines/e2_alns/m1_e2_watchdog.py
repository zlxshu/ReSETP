#!/usr/bin/env python3
"""Low-cost local watchdog for long E2 submission runs."""

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
    parser.add_argument("--expected", type=int, required=True)
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--stale-seconds", type=int, default=5400)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def snapshot(phase_dir: Path, expected: int, stale_seconds: int) -> dict[str, Any]:
    raw_path = phase_dir / "raw_runs.csv"
    rows = list(csv.DictReader(raw_path.open(encoding="utf-8"))) if raw_path.exists() else []
    failures = [row for row in rows if row.get("gate_status") not in {"OK", ""}]
    now = time.time()
    last_progress = raw_path.stat().st_mtime if raw_path.exists() else now
    completed = len(rows)
    elapsed_since_progress = max(0.0, now - last_progress)
    return {
        "schema": "setp-e2-watchdog.v1",
        "phase_dir": str(phase_dir),
        "expected_tasks": int(expected),
        "completed_tasks": completed,
        "remaining_tasks": max(0, int(expected) - completed),
        "failure_count": len(failures),
        "failure_sample": [
            {
                "run_id": row.get("run_id"),
                "status": row.get("gate_status"),
                "reason": row.get("failure_reason"),
            }
            for row in failures[:10]
        ],
        "last_progress_epoch": last_progress,
        "seconds_since_progress": elapsed_since_progress,
        "stale": completed < int(expected) and elapsed_since_progress >= int(stale_seconds),
        "complete": completed >= int(expected) and not failures,
        "checked_at_epoch": now,
    }


def write_snapshot(phase_dir: Path, payload: dict[str, Any]) -> None:
    path = phase_dir / "watchdog.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    with (phase_dir / "watchdog_history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    args = parse_args()
    phase_dir = Path(args.phase_dir).resolve()
    phase_dir.mkdir(parents=True, exist_ok=True)
    while True:
        payload = snapshot(phase_dir, args.expected, args.stale_seconds)
        write_snapshot(phase_dir, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
        if args.once or payload["complete"] or payload["failure_count"] or payload["stale"]:
            return 0 if not payload["failure_count"] and not payload["stale"] else 2
        time.sleep(max(60, int(args.interval_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
