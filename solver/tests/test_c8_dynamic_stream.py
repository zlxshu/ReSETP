from pathlib import Path

from setp_solver.c8_dynamic_stream import (
    active_customers_after_events,
    load_c8_stream,
)


REPO = Path(__file__).resolve().parents[2]
STREAM = (
    REPO
    / "data/dynamic_streams"
    / "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd_mixed_events"
)


def test_paper_stream_contains_all_four_event_types() -> None:
    stream = load_c8_stream(STREAM)

    assert len(stream.events) == 10
    assert {event.event_type for event in stream.events} == {
        "add",
        "cancel",
        "demand_change",
        "time_window_change",
    }
    assert len(stream.added_customer_ids) == 5


def test_only_added_demand_triggers_quantity_batch() -> None:
    batches = load_c8_stream(STREAM).trigger_batches

    assert batches[0].customer_ids == ("C051",)
    assert batches[0].trigger_second == 30_600.0
    assert batches[1].customer_ids == ("C007", "C017", "C020", "C004")
    assert batches[1].demand_kg == 0.0
    assert batches[2].cause == "demand_threshold"
    assert batches[2].demand_kg == 834.0


def test_final_lifecycle_has_fifty_three_active_customers() -> None:
    stream = load_c8_stream(STREAM)
    initial = tuple(f"C{index:03d}" for index in range(1, 51))
    active = active_customers_after_events(initial, stream.events)

    assert len(active) == 53
    assert {"C051", "C052", "C053", "C054", "C055"} <= active
    assert "C007" not in active
    assert "C017" not in active
