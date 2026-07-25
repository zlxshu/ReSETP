#!/usr/bin/env python3
"""Versioned import-only repair for the frozen engineering gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


PACKAGE = Path(__file__).resolve().parent
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

import common  # noqa: E402


common.REGISTRATION = PACKAGE / "g0_registration_v2.json"
common.ENGINEERING = PACKAGE / "engineering_gate_v2"


def load_exact(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load exact module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    exact_test = load_exact(
        "resource_slot_pricing_v2_test_engineering",
        PACKAGE / "test_engineering.py",
    )
    if not hasattr(exact_test, "run_checks"):
        raise ImportError("exact v2 test module lacks run_checks")
    sys.modules["test_engineering"] = exact_test
    runner = load_exact(
        "resource_slot_pricing_v2_engineering_runner",
        PACKAGE / "run_engineering_gate.py",
    )
    if runner.ENGINEERING != common.ENGINEERING:
        raise RuntimeError("v2 engineering output binding failed")
    return int(runner.main())


if __name__ == "__main__":
    raise SystemExit(main())
