#!/usr/bin/env python3
"""Run G0 once and independently decide it; preserve STOP as a terminal result."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PACKAGE = Path(__file__).resolve().parent


def main() -> int:
    subprocess.run(
        [sys.executable, str(PACKAGE / "run_g0.py")],
        cwd=PACKAGE,
        check=True,
    )
    result = subprocess.run(
        [sys.executable, str(PACKAGE / "independent_replay.py")],
        cwd=PACKAGE,
        check=False,
    )
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
