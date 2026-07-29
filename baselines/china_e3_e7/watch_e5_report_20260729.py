#!/usr/bin/env python3
"""One-shot E5 report sentinel: print READY once and exit."""

from __future__ import annotations

import argparse
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()
    report = args.report.resolve()
    if args.poll_seconds <= 0:
        raise ValueError("poll interval must be positive")
    while not report.is_file():
        time.sleep(args.poll_seconds)
    print(f"READY {report}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
