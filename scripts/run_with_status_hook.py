#!/usr/bin/env python3
"""Run a long command and write sparse machine-readable status files."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def probe_seconds(expected_minutes: float) -> int:
    if expected_minutes <= 30.0:
        return 5 * 60
    if expected_minutes > 60.0:
        return 15 * 60
    return 10 * 60


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-dir", type=Path, required=True)
    parser.add_argument("--expected-minutes", type=float, required=True)
    parser.add_argument("--declared-workers", type=int, default=1)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("a command is required after --")
    return args


def main() -> int:
    args = parse_args()
    status_dir = args.status_dir.resolve()
    status_dir.mkdir(parents=True, exist_ok=True)
    log_path = status_dir / "run.log"
    status_path = status_dir / "status.json"
    done_path = status_dir / "done.json"
    if done_path.exists():
        done_path.unlink()
    interval = probe_seconds(args.expected_minutes)
    started = time.time()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            args.command,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=os.getcwd(),
            text=True,
        )
        base = {
            "command": args.command,
            "pid": process.pid,
            "declared_workers": args.declared_workers,
            "expected_minutes": args.expected_minutes,
            "probe_interval_seconds": interval,
            "started_at": now_iso(),
            "log_path": str(log_path),
        }
        atomic_json(status_path, {**base, "state": "running", "elapsed_seconds": 0.0})
        while True:
            try:
                return_code = process.wait(timeout=interval)
                break
            except subprocess.TimeoutExpired:
                pass
            atomic_json(
                status_path,
                {
                    **base,
                    "state": "running",
                    "elapsed_seconds": round(time.time() - started, 3),
                    "checked_at": now_iso(),
                    "log_bytes": log_path.stat().st_size,
                },
            )
        finished = {
            **base,
            "state": "completed" if return_code == 0 else "failed",
            "return_code": return_code,
            "elapsed_seconds": round(time.time() - started, 3),
            "finished_at": now_iso(),
            "log_bytes": log_path.stat().st_size,
        }
        atomic_json(status_path, finished)
        atomic_json(done_path, finished)
        return int(return_code)


if __name__ == "__main__":
    sys.exit(main())
