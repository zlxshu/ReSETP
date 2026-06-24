#!/usr/bin/env python3
"""Lightweight autonomous monitor for the 09q Stage A collection run."""

from __future__ import annotations

import csv
import json
import subprocess
import time
from collections import Counter
from pathlib import Path


OUT = Path("baselines/e2_alns/source_bound_operational_mix_map_data")
EXPECTED_ROWS = 9177
ALLOWED_STATUSES = {"OK", "INIT_INFEASIBLE"}


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    log_path = OUT / "stage_a_monitor.log"
    alert_path = OUT / "stage_a_monitor_alert.txt"
    while True:
        OUT.mkdir(parents=True, exist_ok=True)
        partial_rows = read_rows(OUT / "stage_a_raw_runs.partial.csv")
        queue_rows = read_rows(OUT / "stage_a_task_queue.csv")
        status = Counter(row.get("status", "") for row in partial_rows)
        queue_status = Counter(row.get("queue_status", "") for row in queue_rows)
        bad = {key: value for key, value in status.items() if key not in ALLOWED_STATUSES}
        lines = [
            f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"partial_rows {len(partial_rows)} pct {round(len(partial_rows) / EXPECTED_ROWS * 100, 2)} status {dict(status)}",
            f"queue {dict(queue_status)}",
        ]
        with log_path.open("a", encoding="utf-8") as handle:
            for line in lines:
                handle.write(line + "\n")
        if bad:
            alert_path.write_text(
                "collection failure detected: " + json.dumps(bad, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["pkill", "-TERM", "-f", "source_bound_operational_mix_map.py --stage-a --resume --workers 3"],
                check=False,
            )
            subprocess.run(
                ["pkill", "-TERM", "-f", "source_bound_operational_mix_map.py --repo-root .* --single-run --single-phase stage_a"],
                check=False,
            )
            return 3
        if len(partial_rows) >= EXPECTED_ROWS:
            return 0
        time.sleep(1200)


if __name__ == "__main__":
    raise SystemExit(main())
