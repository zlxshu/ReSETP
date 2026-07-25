#!/usr/bin/env python3
"""Spawn-safe v3 zero-objective engineering and resource gate."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import importlib.util
import json
from multiprocessing import get_context
from pathlib import Path
import sys
from typing import Any


PACKAGE = Path(__file__).resolve().parent
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

import common  # noqa: E402
from worker_entry_v3 import engineering_worker, smoke_worker  # noqa: E402


REGISTRATION = PACKAGE / "g0_registration_v3.json"
ENGINEERING = PACKAGE / "engineering_gate_v3"
common.REGISTRATION = REGISTRATION
common.ENGINEERING = ENGINEERING


def exact_unit_checks() -> dict[str, bool]:
    spec = importlib.util.spec_from_file_location(
        "resource_slot_pricing_v3_exact_test",
        PACKAGE / "test_engineering.py",
    )
    if spec is None or spec.loader is None:
        raise ImportError("cannot load exact v3 unit-check module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return dict(module.run_checks())


def error_row(task: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "task_id": task["task_id"],
        "instance_id": task["instance_id"],
        "lane": task["lane"],
        "status": "ERROR",
        "extensions": 0,
        "complete_labels": 0,
        "negative_routes_observed_without_complete_scoring": 0,
        "positive_resource_prices": 0,
        "peak_rss_bytes": 0,
        "candidate_objectives_evaluated": 0,
        "error": message,
    }


def run_spawn_smoke(workers: int) -> list[dict[str, Any]]:
    context = get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
    ) as pool:
        results = list(pool.map(smoke_worker, range(workers)))
    expected_file = str((PACKAGE / "worker_entry_v3.py").resolve())
    if len(results) != workers:
        raise RuntimeError("spawn smoke did not return six rows")
    if len({int(row["pid"]) for row in results}) != workers:
        raise RuntimeError("spawn smoke did not use six distinct worker processes")
    if any(
        row["module"] != "worker_entry_v3" or row["file"] != expected_file
        for row in results
    ):
        raise RuntimeError("spawn smoke imported an unexpected worker module")
    return sorted(results, key=lambda row: int(row["token"]))


def main() -> int:
    if ENGINEERING.exists():
        raise RuntimeError(f"v3 engineering output exists: {ENGINEERING}")
    ENGINEERING.mkdir(parents=True)
    registration = common.verify_registration()
    config = registration["config"]
    unit_checks = exact_unit_checks()
    before = common.memory_snapshot()
    smoke_results: list[dict[str, Any]] = []
    smoke_error = ""
    try:
        smoke_results = run_spawn_smoke(int(config["workers"]))
    except Exception as exc:  # noqa: BLE001
        smoke_error = f"{type(exc).__name__}: {exc}"
    common.write_json(
        ENGINEERING / "metadata.json",
        {
            "schema": "resetp.resource-slot-pricing-engineering.v3",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "registration_sha256": common.sha256(REGISTRATION),
            "workers": int(config["workers"]),
            "candidate_objectives_evaluated": 0,
            "unit_checks": unit_checks,
            "spawn_smoke_results": smoke_results,
            "spawn_smoke_error": smoke_error,
            "real_instance_loaded_before_smoke_pass": False,
            "memory_before": before,
        },
    )
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    if smoke_error:
        failures.append(f"spawn_smoke: {smoke_error}")
        rows = [
            error_row(task, f"spawn smoke failed before real input: {smoke_error}")
            for task in registration["tasks"]
        ]
    else:
        context = get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=int(config["workers"]),
            mp_context=context,
        ) as pool:
            futures = {
                pool.submit(engineering_worker, task, config): task
                for task in registration["tasks"]
            }
            for future in as_completed(futures):
                task = futures[future]
                try:
                    rows.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    message = (
                        f"{task['task_id']}: {type(exc).__name__}: {exc}"
                    )
                    failures.append(message)
                    rows.append(error_row(task, message))
    rows.sort(key=lambda row: row["task_id"])
    common.write_csv(ENGINEERING / "raw_runs.csv", rows)
    ok = [row for row in rows if row["status"] == "PASS"]
    projected = sum(int(row["peak_rss_bytes"]) for row in ok)
    passed = bool(
        not failures
        and len(smoke_results) == 6
        and len(ok) == 6
        and before["available_percent"]
        >= float(config["minimum_available_memory_percent"])
        and projected <= int(config["maximum_projected_peak_rss_bytes"])
    )
    verdict = (
        "PASS_ZERO_OBJECTIVE_ENGINEERING_AND_SIX_WORKER_RESOURCE_GATE"
        if passed
        else "HALT_ZERO_OBJECTIVE_ENGINEERING_OR_RESOURCE_GATE"
    )
    decision = {
        "schema": "resetp.resource-slot-pricing-engineering-decision.v3",
        "verdict": verdict,
        "pass": passed,
        "spawn_smoke_pass": len(smoke_results) == 6 and not smoke_error,
        "spawn_smoke_distinct_pids": len(
            {int(row["pid"]) for row in smoke_results}
        ),
        "real_instance_loaded_before_smoke_pass": False,
        "candidate_objectives_evaluated": 0,
        "completed_tasks": len(ok),
        "expected_tasks": 6,
        "available_memory_percent_before": before["available_percent"],
        "projected_combined_peak_rss_bytes": projected,
        "failures": failures,
        "next_step": "RUN_FROZEN_G0_ONCE" if passed else "STOP_NO_RESCUE",
    }
    common.write_json(ENGINEERING / "decision.json", decision)
    (ENGINEERING / "report.md").write_text(
        "# Resource-slot pricing v3 zero-objective engineering gate\n\n"
        f"Verdict: `{verdict}`.\n\n"
        f"Spawn smoke: {len(smoke_results)}/6 rows, "
        f"{len({int(row['pid']) for row in smoke_results})}/6 distinct PIDs. "
        f"Real engineering tasks: {len(ok)}/6. Candidate complete objectives: "
        "0.\n",
        encoding="utf-8",
    )
    common.write_json(
        ENGINEERING / "artifact_hashes.json",
        common.artifact_hashes(ENGINEERING),
    )
    common.write_json(
        ENGINEERING / "done.json",
        {
            "verdict": verdict,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    print(json.dumps(decision, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
