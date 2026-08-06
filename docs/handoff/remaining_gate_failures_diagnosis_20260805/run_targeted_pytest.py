#!/usr/bin/env python3
"""Capture the five-target T13 regression command without pytest caches."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


OUT = Path(__file__).resolve().parent
REPO = OUT.parents[2]
tests = [
    "solver/tests/test_refined_carbon_charging.py::test_integrated_route_repair_inserts_station_and_remains_fully_feasible",
    "solver/tests/test_refined_carbon_charging.py::test_refined_reset_and_reconstruction_consumes_one_candidate_evaluation",
    "solver/tests/test_search.py::SearchGateTests::test_h2_initial_solution_contains_deterministic_ev_charging_witness",
    "solver/tests/test_search.py::SearchGateTests::test_h3_short_alns_has_nonzero_charging_signal",
    "solver/tests/test_search.py::SearchGateTests::test_m0_evheavy_initial_solution_respects_fleet_limits_and_charges",
]
env = os.environ.copy()
env.update(
    {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONPATH": "solver/src:models/src",
    }
)
command = [
    "/opt/anaconda3/bin/python3.13",
    "-m",
    "pytest",
    "-p",
    "no:cacheprovider",
    "-q",
    *tests,
]
completed = subprocess.run(command, cwd=REPO, env=env, text=True, capture_output=True)
payload = {
    "command": "PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 PYTHONPATH=solver/src:models/src /opt/anaconda3/bin/python3.13 -m pytest -p no:cacheprovider -q " + " ".join(tests),
    "returncode": completed.returncode,
    "stdout": completed.stdout,
    "stderr": completed.stderr,
}
(OUT / "targeted_pytest_output.json").write_text(
    __import__("json").dumps(payload, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
(OUT / "targeted_pytest_output.txt").write_text(
    completed.stdout + ("\n" + completed.stderr if completed.stderr else ""),
    encoding="utf-8",
)
print(completed.stdout, end="")
print(completed.stderr, end="")
raise SystemExit(completed.returncode)
