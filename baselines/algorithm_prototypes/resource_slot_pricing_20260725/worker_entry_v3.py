"""Stable importable worker entry points for spawned v3 processes."""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any

from common import (
    PACKAGE,
    load_bundle,
    load_registered_solutions,
    peak_rss_bytes,
    set_single_thread_environment,
)
from pricing_core import generate_priced_routes


def smoke_worker(token: int) -> dict[str, Any]:
    """Prove spawn deserialization/import before any real input is loaded."""

    set_single_thread_environment()
    time.sleep(0.75)
    return {
        "token": int(token),
        "pid": os.getpid(),
        "module": __name__,
        "file": str(Path(__file__).resolve()),
    }


def engineering_worker(
    task: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Unchanged v1 engineering unit, exposed from an importable module."""

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
        "negative_routes_observed_without_complete_scoring": (
            result.negative_routes
        ),
        "positive_resource_prices": result.positive_resource_prices,
        "peak_rss_bytes": peak_rss_bytes(),
        "candidate_objectives_evaluated": 0,
        "error": "",
    }


def g0_worker(
    task: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Call the unchanged frozen G0 unit after binding versioned paths."""

    import common
    import run_g0

    common.REGISTRATION = PACKAGE / "g0_registration_v3.json"
    common.ENGINEERING = PACKAGE / "engineering_gate_v3"
    common.OUTPUT = PACKAGE / "g0_gate_v3"
    run_g0.ENGINEERING = common.ENGINEERING
    run_g0.OUTPUT = common.OUTPUT
    return run_g0.run_one(task, config)
