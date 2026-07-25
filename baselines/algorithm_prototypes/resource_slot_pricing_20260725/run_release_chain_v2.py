#!/usr/bin/env python3
"""Run the frozen v2 G0 once, then its unchanged independent replay."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


PACKAGE = Path(__file__).resolve().parent


def main() -> int:
    subprocess.run(
        [sys.executable, str(PACKAGE / "run_g0_v2.py")],
        cwd=PACKAGE,
        check=True,
    )
    result = subprocess.run(
        [sys.executable, str(PACKAGE / "independent_replay_v2.py")],
        cwd=PACKAGE,
        check=False,
    )
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
