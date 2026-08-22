"""Focused contract test for typed dynamic-insertion failure handling."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from setp_solver.algorithms.problem_hgs import dynamic_insertion
from setp_solver.algorithms.problem_hgs.dynamic_insertion import (
    DynamicInsertionOperator,
    NOT_INSERTED_CANDIDATE_EXHAUSTED,
)
from setp_solver.algorithms.problem_hgs.model import (
    DutyIndividual,
    PhysicalVehicleDuty,
)




def test_outsourcing_table_fields_keep_numeric_quantity_and_unknown_cost():
    from run_problem_hgs_c8_stream import _event_rows_for_stage

    batch = SimpleNamespace(
        batch_index=5,
        trigger_second=35_817.0,
        cause="demand_threshold",
        event_ids=("E1",),
        customer_ids=("C_NEW",),
    )
    events_by_id = {
        "E1": SimpleNamespace(
            event_id="E1",
            customer_id="C_NEW",
            event_type="new_customer",
            demand_kg=12.5,
        )
    }
    result = SimpleNamespace(
        status="NOT_INSERTED_TIME_INFEASIBLE",
        failure_reason="all candidates exhausted",
        evaluation=None,
        accounting=SimpleNamespace(
            candidate_attempt_count=3,
            candidate_feasible_count=0,
            candidate_failure_reasons=("clock", "clock", "clock"),
            candidate_diagnostics=(),
        ),
    )
    bundle = SimpleNamespace(
        instance=SimpleNamespace(
            nodes=(SimpleNamespace(node_id="C_NEW", demand=12.5),)
        )
    )

    row = _event_rows_for_stage(
        batch=batch,
        events_by_id=events_by_id,
        result=result,
        bundle=bundle,
        active={"C_NEW"},
        inserted=False,
        outsourced_customer_ids=("C_NEW",),
    )[0]

    assert row["outsourcing_customer_count"] == 1
    assert row["outsourcing_demand_kg"] == 12.5
    assert row["outsourcing_cost"] == "UNKNOWN (待用户定价)"
    assert row["post_trigger_total_cost"] == "UNKNOWN (待用户定价)"
    assert row["failure_reason"] == "all candidates exhausted"
