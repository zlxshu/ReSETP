#!/usr/bin/env python3
"""T10 runner: replay the frozen T5 18-run matrix after the charging fix."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[3]
T5_PATH = REPO / "docs/handoff/carbon_objective_probe_20260804/probe_driver.py"
OUT = Path(__file__).resolve().parent


def load_t5_module():
    spec = importlib.util.spec_from_file_location("t5_carbon_probe_t10", T5_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load probe module from {T5_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


t5 = load_t5_module()
t5.OUT = OUT
t5.PREREGISTRATION = REPO / "docs/handoff/carbon_objective_probe_20260804/preregistration.json"
t5.TASK_ID = "T10-INTERTRIP-CHARGING-FIX"
t5.SCHEMA = "resetp.t10-intertrip-charging-fix-runner.v1"
# The frozen T5 runner requires exact equality with the frozen preregistration
# marker before it will load the instance.  T10's technical-only status is
# recorded in its own metadata/decision files below.
t5.MARKER = "DRAFT_METHOD_AWAITING_USER_APPROVAL"

# T5's runner protects the three files against its pre-fix hashes.  T10 is
# intentionally after the approved check.py change, so freeze the observed
# hashes at this run boundary while retaining the same T5 matrix and checks.
t5.PROTECTED_HASHES = {
    relative: t5.file_sha256(REPO / relative)
    for relative in (
        "solver/src/setp_solver/cost.py",
        "solver/src/setp_solver/check.py",
        "solver/src/setp_solver/search/evaluation.py",
    )
}


if __name__ == "__main__":
    sys.argv = [str(Path(__file__)), "--run"]
    raise SystemExit(t5.main())
