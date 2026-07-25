"""Spawn-safe resource measurement around the frozen read-only start gate."""

from __future__ import annotations

import os
from pathlib import Path
import resource
import time
from typing import Any

from .worker_entry import inspect_task


def inspect_task_with_resource(
    payload: tuple[dict[str, Any], float],
) -> dict[str, Any]:
    task, release_at = payload
    while time.time() < release_at:
        time.sleep(0.01)
    row = inspect_task(task)
    row.update(
        {
            "worker_pid": os.getpid(),
            "worker_module_file": str(Path(__file__).resolve()),
            "worker_cwd": str(Path.cwd().resolve()),
            "peak_rss_mib": resource.getrusage(
                resource.RUSAGE_SELF
            ).ru_maxrss
            / 1024.0**2,
            "real_neighborhood_search_launched": False,
        }
    )
    return row
