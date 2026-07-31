#!/usr/bin/env python3
"""Pure orchestration for the preregistered E3 mismatch campaign."""

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


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PYTHON = REPO / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
RUNNER = HERE / "run_e3_mismatch.py"
PROGRESS = HERE / "campaign_progress.jsonl"
INSTANCE_ORDER = (
    "cn-prd-200c-01-V2-LOCATIONS",
    "cn-prd-200c-02-V2-LOCATIONS",
    "cn-prd-150c-03-V2-LOCATIONS",
    "cn-prd-150c-01-V2-LOCATIONS",
    "cn-prd-150c-02-V2-LOCATIONS",
    "cn-prd-200c-03-V2-LOCATIONS",
)
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_progress(payload: dict[str, Any]) -> None:
    with PROGRESS.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(payload, ensure_ascii=False, sort_keys=True)
            + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())


def run_runner(
    command: str,
    *,
    cap: int,
    workers: int,
    instance_id: str | None = None,
) -> None:
    argv = [
        str(PYTHON),
        "-u",
        str(RUNNER),
        command,
        "--complete-eval-budget",
        str(cap),
        "--workers",
        str(workers),
    ]
    if instance_id is not None:
        argv.extend(["--instance-id", instance_id])
    append_progress(
        {
            "at_utc": now_iso(),
            "event": "STAGE_START",
            "command": command,
            "cap": cap,
            "workers": workers,
            "instance_id": instance_id,
        }
    )
    subprocess.run(
        argv,
        cwd=REPO,
        env={**os.environ, **THREAD_ENV},
        check=True,
    )
    if command != "seal":
        append_progress(
            {
                "at_utc": now_iso(),
                "event": "STAGE_COMPLETE",
                "command": command,
                "cap": cap,
                "workers": workers,
                "instance_id": instance_id,
            }
        )


def ensure_clean_start() -> None:
    if (HERE / "done.json").exists():
        raise RuntimeError("HALT_CAMPAIGN_ALREADY_COMPLETE")
    if (HERE / "budget_lock.json").exists():
        raise RuntimeError(
            "HALT_CAMPAIGN_BUDGET_LOCK_ALREADY_EXISTS"
        )
    preregistration = json.loads(
        (HERE / "pre_registration.json").read_text(encoding="utf-8")
    )
    if (
        preregistration.get("status") != "LOCKED_BEFORE_ANY_SEARCH"
        or preregistration["instance_population"][
            "formal_execution_order"
        ]
        != list(INSTANCE_ORDER)
    ):
        raise RuntimeError("HALT_CAMPAIGN_PREREGISTRATION_DRIFT")


def other_two_worker_experiments() -> list[dict[str, Any]]:
    own_pgid = os.getpgrp()
    result = subprocess.run(
        ["ps", "-axo", "pid=,pgid=,command="],
        check=True,
        capture_output=True,
        text=True,
    )
    blockers: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(maxsplit=2)
        if len(fields) != 3:
            continue
        pid_text, pgid_text, command = fields
        if (
            int(pgid_text) != own_pgid
            and "/ReSETP/" in command
            and ".py" in command
            and "--workers 2" in command
        ):
            blockers.append(
                {
                    "pid": int(pid_text),
                    "pgid": int(pgid_text),
                    "command": command,
                }
            )
    return blockers


def wait_for_worker_capacity() -> None:
    last_heartbeat = 0.0
    while True:
        blockers = other_two_worker_experiments()
        if not blockers:
            append_progress(
                {
                    "at_utc": now_iso(),
                    "event": "WORKER_CAPACITY_RELEASED",
                    "load_average_1m_5m_15m": list(os.getloadavg()),
                    "workers_requested": 2,
                }
            )
            return
        now = time.monotonic()
        if now - last_heartbeat >= 300:
            append_progress(
                {
                    "at_utc": now_iso(),
                    "event": "WAITING_FOR_WORKER_CAPACITY",
                    "blocking_processes": blockers,
                    "workers_requested": 2,
                }
            )
            last_heartbeat = now
        time.sleep(30)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("run",),
    )
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.workers != 2:
        raise RuntimeError("HALT_CAMPAIGN_WORKERS_MUST_EQUAL_2")
    ensure_clean_start()
    wait_for_worker_capacity()
    append_progress(
        {
            "at_utc": now_iso(),
            "event": "CAMPAIGN_START",
            "instances": list(INSTANCE_ORDER),
            "workers": args.workers,
        }
    )
    run_runner("probe", cap=1500, workers=1)
    budget_lock = json.loads(
        (HERE / "budget_lock.json").read_text(encoding="utf-8")
    )
    cap = int(budget_lock["selected_common_formal_budget_cap"])
    if not 400 <= cap <= 1500:
        raise RuntimeError(f"HALT_CAMPAIGN_BUDGET_LOCK:{cap}")
    for instance_id in INSTANCE_ORDER:
        run_runner(
            "formal",
            cap=cap,
            workers=args.workers,
            instance_id=instance_id,
        )
    run_runner("aggregate", cap=cap, workers=args.workers)
    append_progress(
        {
            "at_utc": now_iso(),
            "event": "CAMPAIGN_READY_TO_SEAL",
            "budget_cap": cap,
            "instances": list(INSTANCE_ORDER),
            "formal_units": 180,
        }
    )
    run_runner("seal", cap=cap, workers=args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
