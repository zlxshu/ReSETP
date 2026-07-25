"""Run the isolated G0 once and then the unchanged independent decision."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    subprocess.run(
        [sys.executable, "-m", "rsp_final_isolated_20260725.g0"],
        check=True,
    )
    result = subprocess.run(
        [sys.executable, "-m", "rsp_final_isolated_20260725.replay"],
        check=False,
    )
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())

