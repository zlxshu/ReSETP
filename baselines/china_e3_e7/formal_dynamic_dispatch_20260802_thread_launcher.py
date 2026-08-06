#!/usr/bin/env python3
"""Sandbox-only launcher for the immutable XC2 formal runner.

The managed macOS sandbox denies ``os.sysconf('SC_SEM_NSEMS_MAX')`` before a
``ProcessPoolExecutor`` can create any worker.  This launcher changes only the
executor transport to six in-process threads.  Every task, seed, optimizer
budget, model input, state, and writer remains owned by the preregistered
runner whose SHA-256 is unchanged.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path


RUNNER = Path(__file__).with_name("formal_dynamic_dispatch_20260802_runner.py")
SPEC = importlib.util.spec_from_file_location("xc2_immutable_runner", RUNNER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import immutable XC2 runner: {RUNNER}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE.ProcessPoolExecutor = ThreadPoolExecutor


if __name__ == "__main__":
    MODULE.main()
