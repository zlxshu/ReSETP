from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from setp_solver import main3b_backend


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
