#!/usr/bin/env python3
"""Frozen six-process zero-objective engineering and resource gate."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from common import (
    ENGINEERING,
    artifact_hashes,
    load_bundle,
    load_registered_solutions,
    memory_snapshot,
    peak_rss_bytes,
    set_single_thread_environment,
    sha256,
    verify_registration,
    write_csv,
    write_json,
)
from pricing_core import generate_priced_routes
from test_engineering import run_checks


def run_one(task: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    set_single_thread_environment()
    bundle = load_bundle(task["instance_id"])
    start, parents = load_registered_solutions(task)
    result = generate_priced_routes(
        start,
        parents,
        bundle,
        lane=task["lane"],
        max_extensions=int(config["engineering_max_extensions"]),
        max_routes=int(config["max_generated_routes"]),
        wall_seconds=float(config["engineering_wall_seconds"]),
        dry_run=True,
    )
    if result.extensions > int(config["engineering_max_extensions"]):
        raise RuntimeError("engineering extension cap exceeded")
    if result.complete_labels < 1:
        raise RuntimeError("bidirectional merge produced no complete label")
    if (
        result.lp_primal_residual > 1.0e-7
        or result.lp_stationarity_residual > 1.0e-7
    ):
        raise RuntimeError("LP primal/dual closure failed")
    return {
        "task_id": task["task_id"],
        "instance_id": task["instance_id"],
        "lane": task["lane"],
        "status": "PASS",
        "extensions": result.extensions,
        "complete_labels": result.complete_labels,
        "negative_routes_observed_without_complete_scoring": result.negative_routes,
        "positive_resource_prices": result.positive_resource_prices,
        "peak_rss_bytes": peak_rss_bytes(),
        "candidate_objectives_evaluated": 0,
        "error": "",
    }


def main() -> int:
    if ENGINEERING.exists():
        raise RuntimeError(f"engineering output exists: {ENGINEERING}")
    ENGINEERING.mkdir(parents=True)
    registration = verify_registration()
    config = registration["config"]
    unit_checks = run_checks()
    before = memory_snapshot()
    write_json(
        ENGINEERING / "metadata.json",
        {
            "schema": "resetp.resource-slot-pricing-engineering.v1",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "registration_sha256": sha256(
                Path(__file__).resolve().parent / "g0_registration_v1.json"
            ),
            "workers": int(config["workers"]),
            "candidate_objectives_evaluated": 0,
            "unit_checks": unit_checks,
            "memory_before": before,
        },
    )
    rows = []
    failures = []
    with ProcessPoolExecutor(max_workers=int(config["workers"])) as pool:
        futures = {
            pool.submit(run_one, task, config): task
            for task in registration["tasks"]
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:  # noqa: BLE001
                message = f"{task['task_id']}: {type(exc).__name__}: {exc}"
                failures.append(message)
                rows.append(
                    {
                        "task_id": task["task_id"],
                        "instance_id": task["instance_id"],
                        "lane": task["lane"],
                        "status": "ERROR",
                        "candidate_objectives_evaluated": 0,
                        "error": message,
                    }
                )
    rows.sort(key=lambda row: row["task_id"])
    write_csv(ENGINEERING / "raw_runs.csv", rows)
    ok = [row for row in rows if row["status"] == "PASS"]
    projected = sum(int(row["peak_rss_bytes"]) for row in ok)
    passed = bool(
        not failures
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
        "schema": "resetp.resource-slot-pricing-engineering-decision.v1",
        "verdict": verdict,
        "pass": passed,
        "candidate_objectives_evaluated": 0,
        "completed_tasks": len(ok),
        "expected_tasks": 6,
        "available_memory_percent_before": before["available_percent"],
        "projected_combined_peak_rss_bytes": projected,
        "failures": failures,
        "next_step": "RUN_FROZEN_G0_ONCE" if passed else "STOP_NO_RESCUE",
    }
    write_json(ENGINEERING / "decision.json", decision)
    (ENGINEERING / "report.md").write_text(
        "# Resource-slot pricing zero-objective engineering gate\n\n"
        f"Verdict: `{verdict}`.\n\n"
        "No candidate complete objective was evaluated. The gate covered "
        "deterministic label, dominance and merge checks; frozen input/hash "
        "closure; six real-bundle dry constructions; and the six-worker "
        "memory gate.\n",
        encoding="utf-8",
    )
    write_json(ENGINEERING / "artifact_hashes.json", artifact_hashes(ENGINEERING))
    write_json(
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
