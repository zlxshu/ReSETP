from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from setp_solver import main3b_backend
from setp_solver.algorithms.problem_hgs.model import (
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "solver/scripts/run_dynamic_experiment.py"
SPEC = importlib.util.spec_from_file_location("main3b_protocol_harness", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = harness
SPEC.loader.exec_module(harness)


def _event(event_id: str, appearance: float, demand: float) -> harness.TriggerEvent:
    return harness.TriggerEvent(
        event_id=event_id,
        customer_id=event_id,
        appearance_second=appearance,
        demand_kg=demand,
    )


def test_default_protocol_delegates_to_existing_builder() -> None:
    start = harness.QIU_TRIGGER_PROTOCOL.reception_start_second
    events = (
        _event("A", start + 60.0, 200.0),
        _event("B", start + 120.0, 300.0),
        _event("C", start + 180.0, 100.0),
    )
    actual = harness._build_protocol_batches(events, harness.QIU_TRIGGER_PROTOCOL)
    expected = harness.build_trigger_batches(events, harness.QIU_TRIGGER_PROTOCOL)
    assert actual == expected


def test_q569_dual_shift_never_triggers_during_lunch() -> None:
    protocol = harness.Q569_4_T30_DUALSHIFT
    batches = harness._build_protocol_batches(
        (
            _event("AM", 8.0 * 3600.0 + 60.0, 300.0),
            _event("PM", 13.0 * 3600.0 + 60.0, 300.0),
        ),
        protocol,
    )
    assert [batch.trigger_second for batch in batches] == [
        8.0 * 3600.0 + 30.0 * 60.0,
        13.0 * 3600.0 + 30.0 * 60.0,
    ]
    assert all(
        8.0 * 3600.0 <= batch.trigger_second < 11.0 * 3600.0
        or 13.0 * 3600.0 <= batch.trigger_second < 19.0 * 3600.0
        for batch in batches
    )
    with pytest.raises(ValueError, match="lunch interval"):
        harness._build_protocol_batches(
            (_event("LUNCH", 12.0 * 3600.0, 600.0),),
            protocol,
        )


def test_q417_contract_builds_six_batches_for_the_frozen_stream() -> None:
    events = tuple(
        _event(event_id, appearance, demand)
        for event_id, appearance, demand in (
            ("C8_ADD_001", 35817.0, 208.0),
            ("C8_ADD_002", 33928.0, 417.0),
            ("C8_ADD_003", 32848.0, 417.0),
            ("C8_ADD_004", 28952.0, 139.0),
            ("C8_ADD_005", 34677.0, 347.0),
            ("C8_ADD_006", 31235.0, 347.0),
            ("C8_ADD_007", 32116.0, 347.0),
            ("C8_ADD_008", 31535.0, 139.0),
            ("C8_ADD_009", 30163.0, 139.0),
            ("C8_ADD_010", 34865.0, 347.0),
        )
    )
    batches = harness._build_protocol_batches(
        events,
        harness.Q417_T30_DUALSHIFT,
    )

    assert len(batches) == 6
    assert [batch.trigger_second for batch in batches] == [
        30600.0,
        31535.0,
        32848.0,
        33928.0,
        34865.0,
        36665.0,
    ]
    assert all(
        not 11.0 * 3600.0 <= batch.trigger_second < 13.0 * 3600.0
        for batch in batches
    )


def test_full_information_static_uses_exactly_one_hgs_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    individual = main3b_backend.DutyIndividual(duties=(), source="test")
    evaluation = SimpleNamespace(
        feasible=True,
        prepared_solution=SimpleNamespace(routes=(), charging_actions=()),
        certificate=SimpleNamespace(trips=()),
    )
    problem = SimpleNamespace(
        base_context=object(),
        base_bundle=object(),
        full_bundle=object(),
        base_initial=individual,
        static_customer_ids=frozenset(),
        dynamic_customer_ids=frozenset(),
    )
    calls: list[tuple[float, str]] = []

    class _Evaluator:
        def __init__(self, context: object) -> None:
            del context

        def evaluate(self, candidate: object) -> object:
            assert candidate is individual
            return evaluation

    def _one_hgs(
        self: object,
        candidate: object,
        context: object,
        deadline_seconds: float,
        *,
        arm: str,
        stage_index: int,
    ) -> tuple[object, object, object]:
        del self, context, stage_index
        assert candidate is individual
        calls.append((deadline_seconds, arm))
        return individual, evaluation, SimpleNamespace(
            termination_status="TIME_LIMIT"
        )

    monkeypatch.setattr(main3b_backend, "DutyFullEvaluator", _Evaluator)
    monkeypatch.setattr(
        main3b_backend,
        "_static_context",
        lambda context, bundle: context,
    )
    monkeypatch.setattr(
        main3b_backend,
        "_context_with_bundle",
        lambda context, bundle, current_problem: context,
    )
    monkeypatch.setattr(main3b_backend.ProductionBackend, "_run_hgs", _one_hgs)
    monkeypatch.setattr(
        main3b_backend.ProductionBackend,
        "initial_plan",
        lambda *args, **kwargs: pytest.fail("hidden preliminary HGS call"),
    )

    state = main3b_backend.ProductionBackend(seed=11).full_information_static(
        problem,
        (),
        387.0,
    )

    assert state.evaluation is evaluation
    assert calls == [(387.0, "full_information_static_reference")]
    assert state.diagnostics[-1]["kind"] == "problem_hgs_stage"


def test_route_change_stat_counts_removed_old_arc_and_changed_assets() -> None:
    before = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_A",
                "cv",
                "D0",
                (DutyTrip(1, ("A", "B", "C")),),
            ),
            PhysicalVehicleDuty(
                "CV_B",
                "cv",
                "D0",
                (DutyTrip(1, ("D",)),),
            ),
        ),
        unserved_customers=("X",),
    )
    after = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_A",
                "cv",
                "D0",
                (DutyTrip(1, ("A", "X", "B", "C", "D")),),
            ),
        ),
    )
    old = {"A", "B", "C", "D"}

    before_arcs = main3b_backend._old_customer_arcs(before, old)
    after_arcs = main3b_backend._old_customer_arcs(after, old)
    before_assets = main3b_backend._customer_vehicle_assignment(before, old)
    after_assets = main3b_backend._customer_vehicle_assignment(after, old)

    assert before_arcs == {("A", "B"), ("B", "C")}
    assert before_arcs - after_arcs == {("A", "B")}
    assert before_assets["D"] == "CV_B"
    assert after_assets["D"] == "CV_A"


def test_production_backend_rejects_returned_internal_error() -> None:
    abnormal = SimpleNamespace(
        termination_status="INTERNAL_ERROR",
        termination_error_type="RuntimeError",
        termination_error="boom",
    )
    with pytest.raises(main3b_backend.ProductionBackendHalt, match="INTERNAL_ERROR"):
        main3b_backend._require_normal_hgs_termination(
            abnormal,
            arm="rolling_dynamic",
        )
