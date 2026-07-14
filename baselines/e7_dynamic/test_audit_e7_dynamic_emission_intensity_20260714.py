from __future__ import annotations

from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import audit_e7_dynamic_emission_intensity_20260714 as audit


def test_stream_one_arm_ledgers_close() -> None:
    cooperative = audit.arm_row(1, "cooperative")
    independent = audit.arm_row(1, "independent")
    assert abs(cooperative["emissions_closure_error"]) < 1e-9
    assert abs(independent["emissions_closure_error"]) < 1e-9
    assert cooperative["served_demand_kg"] > 0
    assert independent["served_demand_kg"] > 0


def test_stream_one_pair_keeps_workload_warning() -> None:
    row = audit.paired_row(
        audit.arm_row(1, "cooperative"), audit.arm_row(1, "independent")
    )
    assert not row["workload_equal"]
    assert row["E_total_intensity_change_percent"] > 0
    assert row["E_cv_direct_intensity_change_percent"] > 0
    assert row["electricity_kwh_intensity_change_percent"] < 0
