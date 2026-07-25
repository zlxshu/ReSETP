#!/usr/bin/env python3
"""Run G0 once, then replay it in a fresh interpreter."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PACKAGE = Path(__file__).resolve().parent


def main() -> int:
    subprocess.run(
        [sys.executable, str(PACKAGE / "run_g0.py")],
        check=True,
    )
    subprocess.run(
        [sys.executable, str(PACKAGE / "independent_replay.py")],
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

