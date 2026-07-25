#!/usr/bin/env python3
"""Render the disclosed mechanism-case trajectory with the paper style."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = (
    Path(__file__).parent
    / "algorithm_repair_diagnostic_20260724/"
    "chen_style_mechanism_case_trajectory/representative_gate/"
    "trajectories"
)
OUT = ROOT / "figure"
SOURCE = (
    Path(__file__).parent
    / "corrected_china81_rerun_20260723/run_corrected_s5.py"
)


def main() -> int:
    spec = importlib.util.spec_from_file_location(
        "chen_style_figure_renderer",
        SOURCE,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load paper renderer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    OUT.mkdir(parents=True, exist_ok=True)
    module.TRAJ = ROOT
    module.OUT = OUT
    module.configure_publication_fonts()
    result = module.plot_convergence()
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
