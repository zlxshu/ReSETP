"""No-instance spawn worker identity probe."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import time
from typing import Any

from .paths import validate_project_root


EXPECTED_MODULE = (
    "baselines.experiment_infrastructure."
    "absolute_execution_harness_20260725.worker_probe"
)
EXPECTED_FILE = Path(__file__).resolve()


def probe_worker(
    task: tuple[int, str, str, str, float],
) -> dict[str, Any]:
    worker_index, root_raw, python_raw, expected_cwd_raw, release_at = task
    while time.time() < release_at:
        time.sleep(0.01)
    root = validate_project_root(Path(root_raw))
    python = Path(python_raw).resolve()
    expected_cwd = Path(expected_cwd_raw).resolve()
    actual_file = Path(__file__).resolve()
    actual_cwd = Path.cwd().resolve()
    actual_python = Path(sys.executable).resolve()
    if __name__ != EXPECTED_MODULE:
        raise RuntimeError(f"worker module mismatch: {__name__}")
    if actual_file != EXPECTED_FILE:
        raise RuntimeError(f"worker file mismatch: {actual_file}")
    if actual_cwd != expected_cwd or actual_cwd != root:
        raise RuntimeError(
            f"worker cwd mismatch: {actual_cwd} != {expected_cwd}"
        )
    if actual_python != python:
        raise RuntimeError(
            f"worker Python mismatch: {actual_python} != {python}"
        )
    forbidden = sorted(
        name
        for name in sys.modules
        if name == "setp_solver"
        or name.startswith("setp_solver.")
        or name.endswith("china81")
        or ".china81" in name
    )
    if forbidden:
        raise RuntimeError(
            f"no-instance worker imported experiment modules: {forbidden}"
        )
    time.sleep(0.35)
    return {
        "worker_index": worker_index,
        "pid": os.getpid(),
        "module": __name__,
        "module_file": str(actual_file),
        "cwd": str(actual_cwd),
        "project_root": str(root),
        "python": str(actual_python),
        "real_instance_loaded": False,
    }
