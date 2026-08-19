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


def test_exhausted_direct_candidates_return_typed_outsourcing_result(monkeypatch):
    initial = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D0_1",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(),
            ),
        ),
        unserved_customers=("C_NEW",),
    )
    state = SimpleNamespace(
        cut=SimpleNamespace(
            trigger_second=0.0,
            completed_route_ids=(),
            in_progress_route_ids=(),
            locked_charging_actions=(),
        ),
        customer_appearance_second={"C_NEW": 0.0},
        prior_committed_solution=SimpleNamespace(routes=(), charging_actions=()),
        source_solution=SimpleNamespace(routes=(), charging_actions=()),
    )

    class _Statistics:
        num_updates = 0
        num_moves = 0
        num_improving = 0

    class _LocalSearch:
        statistics = _Statistics()

        def repair_required(self, individual, _booster):
            return individual

    class _PenaltyManager:
        def booster_cost_evaluator(self):
            return lambda _candidate: 0.0

    class _Engine:
        def __init__(self, *_args, **_kwargs):
            self.local_search = _LocalSearch()
            self.penalty_manager = _PenaltyManager()

        def project(self, individual):
            return individual

        def decode_replacements(self, _initial, _solution):
            return ()

    class _Evaluator:
        context = SimpleNamespace(
            dynamic_state=state,
            rebuilt_route_constraints=None,
        )
        full_calls = 0

        def evaluate(self, _candidate):
            self.full_calls += 1
            raise ValueError(
                "E7_DYNAMIC_MULTITRIP_V1: route has no feasible clock"
            )

    monkeypatch.setattr(
        dynamic_insertion,
        "IndependentKernelDutyRouteProposalEngine",
        _Engine,
    )
    evaluator = _Evaluator()

    result = DynamicInsertionOperator(enabled=True).apply(
        initial,
        evaluator=evaluator,
        charging_policy=SimpleNamespace(),
        newly_revealed_customer_ids=("C_NEW",),
    )

    assert result.status == NOT_INSERTED_CANDIDATE_EXHAUSTED
    assert result.outsourced_customer_ids == ("C_NEW",)
    assert result.evaluation is None
    assert result.accounting.candidate_attempt_count == 2
    assert result.accounting.candidate_diagnostics[-1].failure_reason.startswith(
        "ValueError: E7_DYNAMIC_MULTITRIP_V1"
    )
    assert "candidate_diagnostics.json" in result.failure_reason


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
