#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
for path in (HERE, REPO / "solver/src", REPO):
    sys.path.insert(0, str(path))

import run_pilot07_physical_transfer_ledger as ledger


def test_required_trips() -> None:
    assert ledger.required_trips(0.0, 1700.0) == 0
    assert ledger.required_trips(1700.0, 1700.0) == 1
    assert ledger.required_trips(1700.1, 1700.0) == 2


def test_saved_solution_produces_same_quantity_for_both_vehicle_bounds() -> None:
    payload = ledger.json.loads((ledger.SOURCE / "solution.json").read_text(encoding="utf-8"))
    solution = ledger.solution_from_dict(payload["solution"])
    bundle, _, _, _ = ledger.pilot05.load_context()
    rows = ledger.build_rows(bundle, solution)
    assert sum(row["quantity_kg"] for row in rows if row["vehicle_type"] == "cv") == 28614.0
    assert sum(row["quantity_kg"] for row in rows if row["vehicle_type"] == "ev") == 28614.0
    assert all(row["minimum_trip_count"] > 0 for row in rows)
