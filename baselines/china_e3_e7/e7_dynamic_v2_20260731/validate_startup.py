#!/usr/bin/env python3
"""Run one minimal E7 unit after the source-contract regression check."""

from __future__ import annotations

import json
from pathlib import Path

import run_e7_dynamic as runner


def main() -> None:
    runner.LEGACY.preflight(workers=1)
    result = runner.LEGACY.run_task(
        scale="50c",
        seed=1,
        arm="FULL_ROLLING",
        per_pass_cap=10,
        max_stages=1,
        trace_mode=False,
    )
    rows = result["payload"]["rows"]
    actual = int(result["actual_search_evaluations"])
    if not rows or int(result["stage_count"]) < 1:
        raise RuntimeError("HALT_STARTUP_VALIDATION_NO_COMPLETED_STAGE")
    if actual <= 0 or actual > 20:
        raise RuntimeError(
            f"HALT_STARTUP_VALIDATION_BUDGET:{actual}:expected_1_to_20"
        )
    if not all(bool(row["customer_accounting_pass"]) for row in rows):
        raise RuntimeError("HALT_STARTUP_VALIDATION_CUSTOMER_ACCOUNTING")
    output_dir = runner.HERE / "startup_validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    runner.LEGACY.atomic_json(output_dir / "task.json", result)
    summary = {
        "status": "PASS_PROBE_STARTUP_ONE_UNIT",
        "entered_probe_run_probe_arm": True,
        "completed_unit": {
            "scale": "50c",
            "seed": 1,
            "stream_seed": 1,
            "arm": "FULL_ROLLING",
            "max_stages": 1,
            "stage_count": int(result["stage_count"]),
        },
        "per_pass_cap": 10,
        "actual_search_evaluations": actual,
        "result_sha256": result["result_sha256"],
    }
    runner.LEGACY.atomic_json(output_dir / "startup_validation.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
