#!/usr/bin/env python3
"""Six-process sandbox transport for the immutable XC2 formal runner.

This module contains no experiment logic.  It launches the immutable runner's
``_run_scenario`` function in six independent Python processes, records each
exit code without retry, and hands the 30 returned scenario files to the
immutable ``_aggregate`` function.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "formal_dynamic_dispatch_20260802_runner.py"
SPEC = importlib.util.spec_from_file_location("xc2_immutable_runner", RUNNER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import immutable XC2 runner: {RUNNER}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _worker(args: argparse.Namespace) -> None:
    result = MODULE._run_scenario((args.policy, int(args.seed), args.scenario_dir))
    print(result, flush=True)


def _coordinator(args: argparse.Namespace) -> None:
    output = Path(args.output).resolve()
    workers = int(args.workers)
    if not 1 <= workers <= 8:
        raise ValueError("workers must be between 1 and 8")
    if (output / "done.json").exists():
        raise RuntimeError("formal output already has a terminal marker")
    preregistration = MODULE._read_json(output / "preregistration.json")
    if MODULE._sha256(output / "preregistration.json") != MODULE._read_json(
        output / "metadata.json"
    )["preregistration_sha256"]:
        raise RuntimeError("preregistration changed before subprocess launch")
    MODULE._assert_source_hashes(preregistration)
    scenarios_root = output / "scenarios"
    if scenarios_root.exists():
        raise RuntimeError("refusing pre-existing scenario directory")
    scenarios_root.mkdir()
    log_root = output / "runtime_logs"
    log_root.mkdir()
    tasks = [
        (policy, seed, scenarios_root / f"{policy}__seed{seed:02d}")
        for policy in MODULE.POLICIES
        for seed in MODULE.SEEDS
    ]
    started = time.perf_counter()
    pending = list(tasks)
    running: dict[subprocess.Popen[str], dict[str, Any]] = {}
    completed: list[Path] = []
    failures: list[dict[str, Any]] = []

    def write_status() -> None:
        MODULE._write_json(
            output / "status.json",
            {
                "status": "XC_DYNAMIC_FORMAL_RUNNING",
                "completed_scenarios": len(completed),
                "runtime_failures": failures,
                "active_scenarios": [
                    {
                        "policy": item["policy"],
                        "stream_seed": item["seed"],
                        "pid": process.pid,
                    }
                    for process, item in running.items()
                ],
                "pending_scenarios": len(pending),
                "total_scenarios": len(tasks),
                "updated_at_utc": MODULE._utc_now(),
            },
        )

    write_status()
    while pending or running:
        while pending and len(running) < workers:
            policy, seed, scenario_dir = pending.pop(0)
            log_path = log_root / f"{policy}__seed{seed:02d}.log"
            handle = log_path.open("w", encoding="utf-8")
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "worker",
                "--policy",
                policy,
                "--seed",
                str(seed),
                "--scenario-dir",
                str(scenario_dir),
            ]
            process = subprocess.Popen(
                command,
                cwd=MODULE.ROOT,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                env=dict(os.environ),
            )
            running[process] = {
                "policy": policy,
                "seed": seed,
                "scenario_dir": scenario_dir,
                "log_path": log_path,
                "handle": handle,
                "command": command,
            }
        write_status()
        if running:
            time.sleep(1.0)
        for process, item in list(running.items()):
            return_code = process.poll()
            if return_code is None:
                continue
            item["handle"].close()
            del running[process]
            result_path = item["scenario_dir"] / "scenario_result.json"
            if return_code == 0 and result_path.is_file():
                completed.append(result_path)
            else:
                failures.append(
                    {
                        "policy": item["policy"],
                        "stream_seed": item["seed"],
                        "return_code": int(return_code),
                        "log_path": str(item["log_path"].relative_to(output)),
                        "scenario_result_exists": result_path.is_file(),
                    }
                )
            write_status()

    if failures:
        MODULE._write_json(
            output / "runtime_failures.json",
            {
                "status": "HALT_XC_DYNAMIC_RUNTIME_FAILURES_RETAINED",
                "failures": failures,
                "completed_scenarios": len(completed),
                "total_scenarios": len(tasks),
            },
        )
        MODULE._write_json(
            output / "done.json",
            {
                "status": "HALT_XC_DYNAMIC_RUNTIME_FAILURES_RETAINED",
                "completed_scenarios": len(completed),
                "runtime_failure_count": len(failures),
                "completed_at_utc": MODULE._utc_now(),
            },
        )
        raise RuntimeError(f"{len(failures)} subprocess workers failed; retained")
    MODULE._aggregate(output, completed, time.perf_counter() - started)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    coordinator = subparsers.add_parser("run")
    coordinator.add_argument("--output", type=Path, default=MODULE.OUTPUT_DIR)
    coordinator.add_argument("--workers", type=int, default=6)
    worker = subparsers.add_parser("worker")
    worker.add_argument("--policy", choices=MODULE.POLICIES, required=True)
    worker.add_argument("--seed", type=int, choices=MODULE.SEEDS, required=True)
    worker.add_argument("--scenario-dir", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    parsed = parse_args()
    if parsed.command == "worker":
        _worker(parsed)
    else:
        _coordinator(parsed)
