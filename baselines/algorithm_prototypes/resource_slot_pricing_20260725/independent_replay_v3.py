#!/usr/bin/env python3
"""Bind the unchanged independent replay to v3 paths."""

from __future__ import annotations

from pathlib import Path
import sys


PACKAGE = Path(__file__).resolve().parent
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

import common  # noqa: E402


common.REGISTRATION = PACKAGE / "g0_registration_v3.json"
common.OUTPUT = PACKAGE / "g0_gate_v3"

import independent_replay  # noqa: E402


independent_replay.OUTPUT = common.OUTPUT


if __name__ == "__main__":
    raise SystemExit(independent_replay.main())
