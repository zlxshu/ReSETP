#!/usr/bin/env python3
"""Read-only completion watcher for an XC2 job hidden by the managed sandbox.

The watcher never launches, retries, edits, or terminates a scenario.  It exits
successfully only when the experiment-owned done.json says
XC_DYNAMIC_FORMAL_COMPLETE.  Its stdout supplies a lightweight heartbeat to the
external experiment monitor while the detached computation remains invisible
to process inspection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args()
    output = args.output.resolve()
    preregistration = json.loads((output / "preregistration.json").read_text())
    frozen = preregistration["source_sha256"]
    repo = output.parents[2]

    while True:
        drifts = []
        for relative, expected in frozen.items():
            path = repo / relative
            observed = sha256(path) if path.is_file() else None
            if observed != expected:
                drifts.append(
                    {"path": relative, "expected": expected, "observed": observed}
                )
        if drifts:
            print(json.dumps({"status": "PROTECTED_SOURCE_DRIFT", "drifts": drifts}), flush=True)
            return 3

        done_path = output / "done.json"
        if done_path.is_file():
            done = json.loads(done_path.read_text())
            print(json.dumps({"authoritative_done": done}, ensure_ascii=False), flush=True)
            return 0 if done.get("status") == "XC_DYNAMIC_FORMAL_COMPLETE" else 2

        scenarios = output / "scenarios"
        stage_count = sum(1 for _ in scenarios.glob("*/solutions/*/stage_*.json"))
        result_count = sum(1 for _ in scenarios.glob("*/scenario_result.json"))
        status = {}
        status_path = output / "status.json"
        if status_path.is_file():
            status = json.loads(status_path.read_text())
        print(
            json.dumps(
                {
                    "status": status.get("status", "WAITING_FOR_STATUS"),
                    "completed_scenarios": result_count,
                    "stage_solution_files": stage_count,
                    "authoritative_done": False,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        time.sleep(max(10, int(args.poll_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
