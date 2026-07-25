"""Stable spawned-worker entry points for the isolated final gate."""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any

from . import runtime
from .frozen_loader import load_frozen_stack


def identity_worker(token: int) -> dict[str, Any]:
    """Resolve and report all runner identities before any real input is loaded."""

    runtime.set_single_thread_environment()
    loaded = load_frozen_stack()
    time.sleep(0.75)
    return {
        "token": int(token),
        "pid": os.getpid(),
        "worker_module": __name__,
        "worker_file": str(Path(__file__).resolve()),
        **loaded["identities"],
    }


def engineering_worker(
    task: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    runtime.set_single_thread_environment()
    loaded = load_frozen_stack()
    identity = loaded["identities"]
    bundle = runtime.load_bundle(task["instance_id"])
    start, parents = runtime.load_registered_solutions(task)
    result = loaded["pricing"].generate_priced_routes(
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
        "peak_rss_bytes": runtime.peak_rss_bytes(),
        "candidate_objectives_evaluated": 0,
        "worker_module": __name__,
        "worker_file": str(Path(__file__).resolve()),
        "runner_module": identity["runner_module"],
        "runner_file": identity["runner_file"],
        "error": "",
    }


def g0_worker(
    task: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    runtime.set_single_thread_environment()
    loaded = load_frozen_stack()
    identity = loaded["identities"]
    row = loaded["runner"].run_one(task, config)
    row.update(
        {
            "worker_module": __name__,
            "worker_file": str(Path(__file__).resolve()),
            "runner_module": identity["runner_module"],
            "runner_file": identity["runner_file"],
        }
    )
    return row

