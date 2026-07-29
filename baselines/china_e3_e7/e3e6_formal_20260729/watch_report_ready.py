#!/usr/bin/env python3
"""Print READY once this task's report exists, then exit immediately."""

from __future__ import annotations

import argparse
from pathlib import Path
from time import sleep


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    args = parser.parse_args()
    report = Path(__file__).resolve().parent / "report.md"
    while not report.is_file():
        sleep(max(0.25, float(args.poll_seconds)))
    print(f"READY {report}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
