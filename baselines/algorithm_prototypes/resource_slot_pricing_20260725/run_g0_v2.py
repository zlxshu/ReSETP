#!/usr/bin/env python3
"""Versioned path binding for the unchanged frozen G0 runner."""

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
common.OUTPUT = PACKAGE / "g0_gate_v2"


def main() -> int:
    spec = importlib.util.spec_from_file_location(
        "resource_slot_pricing_v2_g0_runner",
        PACKAGE / "run_g0.py",
    )
    if spec is None or spec.loader is None:
        raise ImportError("cannot load exact frozen G0 runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if (
        module.ENGINEERING != common.ENGINEERING
        or module.OUTPUT != common.OUTPUT
    ):
        raise RuntimeError("v2 G0 path binding failed")
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
