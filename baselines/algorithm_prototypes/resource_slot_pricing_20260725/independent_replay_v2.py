#!/usr/bin/env python3
"""Versioned path binding for the unchanged independent replay."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


PACKAGE = Path(__file__).resolve().parent
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

import common  # noqa: E402


common.REGISTRATION = PACKAGE / "g0_registration_v2.json"
common.OUTPUT = PACKAGE / "g0_gate_v2"


def main() -> int:
    spec = importlib.util.spec_from_file_location(
        "resource_slot_pricing_v2_independent_replay",
        PACKAGE / "independent_replay.py",
    )
    if spec is None or spec.loader is None:
        raise ImportError("cannot load exact frozen independent replay")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if module.OUTPUT != common.OUTPUT:
        raise RuntimeError("v2 replay output binding failed")
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
