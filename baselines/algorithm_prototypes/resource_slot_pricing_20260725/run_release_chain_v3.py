#!/usr/bin/env python3
"""Run v3 G0 once and then the unchanged independent decision."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


PACKAGE = Path(__file__).resolve().parent


def main() -> int:
    subprocess.run(
        [sys.executable, str(PACKAGE / "run_g0_v3.py")],
        cwd=PACKAGE,
        check=True,
    )
    result = subprocess.run(
        [sys.executable, str(PACKAGE / "independent_replay_v3.py")],
        cwd=PACKAGE,
        check=False,
    )
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
