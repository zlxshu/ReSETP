#!/usr/bin/env python3
"""Run G0 v2 with current route-pair sources; preserve v1."""

from __future__ import annotations

from pathlib import Path

import run_g0

PACKAGE = Path(__file__).resolve().parent


def main() -> int:
    run_g0.REGISTRATION = PACKAGE / "g0_registration_v2.json"
    run_g0.OUTPUT = PACKAGE / "g0_gate_v2"
    return run_g0.main()


if __name__ == "__main__":
    raise SystemExit(main())
