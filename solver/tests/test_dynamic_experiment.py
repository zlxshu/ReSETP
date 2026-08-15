from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "solver/scripts/run_dynamic_experiment.py"
SPEC = importlib.util.spec_from_file_location("dynamic_experiment_harness", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = harness
SPEC.loader.exec_module(harness)


def _order(
    customer_id: str,
    *,
    demand: float,
    x: float,
    appearance_offset: float = 60.0,
    initially_visible: bool = False,
):
    start = harness.QIU_TRIGGER_PROTOCOL.reception_start_second
    return harness.ExperimentOrder(
        event_id=f"event-{customer_id}",
        customer_id=customer_id,
        appearance_second=start + appearance_offset,
        demand_kg=demand,
        x=x,
        y=0.0,
        initially_visible=initially_visible,
    )


def test_shared_event_stream_applies_rule_e_once() -> None:
    events = (
        _order("A", demand=200.0, x=1.0, appearance_offset=60.0),
        _order("B", demand=300.0, x=2.0, appearance_offset=120.0),
        _order("C", demand=100.0, x=3.0, appearance_offset=180.0),
    )
    stream = harness.construct_shared_event_stream(events)

    assert len(stream.batches) == 2
    assert stream.batches[0].cause == "demand_threshold"
    assert stream.batches[0].customer_ids == ("A", "B")
    assert stream.batches[0].trigger_second == events[1].appearance_second
    assert stream.batches[1].cause == "maximum_wait"
    assert stream.batches[1].customer_ids == ("C",)
    assert stream.batches[1].trigger_second == (
        events[1].appearance_second
        + harness.QIU_TRIGGER_PROTOCOL.interval_seconds
    )
    assert stream.sha256 == harness.construct_shared_event_stream(events).sha256


def test_tiny_rolling_and_all_three_mechanical_candidate_classes() -> None:
    backend = harness.ToyBackend()
    vehicles = (
        harness.ToyVehicle("V1", 2.0, 1.0, 1.0, 0.1, max_trips=2),
        harness.ToyVehicle("V2", 2.0, 1.0, 1.0, 0.1, max_trips=1),
    )
    orders = (
        _order("A", demand=1.0, x=1.0, initially_visible=True),
        _order("B", demand=1.0, x=2.0),
        _order("C", demand=1.0, x=3.0),
        _order("D", demand=2.0, x=4.0),
    )
    problem = harness.ToyProblem(
        "tiny-arm-logic", vehicles, (orders[0],), orders[1:]
    )
    state = harness._state_from_mapping({"V1": [["A"]]})

    inserted = backend.mechanical_insert_one(problem, state, "B")
    assert inserted.candidate_class == "1_existing_planned_trip"

    full_trip = harness._state_from_mapping({"V1": [["A", "B"]]})
    appended = backend.mechanical_insert_one(problem, full_trip, "C")
    assert appended.candidate_class == "2_append_used_vehicle_trip"

    used_up = harness._state_from_mapping({"V1": [["A", "B"], ["C"]]})
    dispatched = backend.mechanical_insert_one(problem, used_up, "D")
    assert dispatched.candidate_class == "3_dispatch_unused_vehicle"

    rolling_state, detail = backend.rolling_reoptimize(
        problem, state, ("A", "B", "C"), 1.0
    )
    rolling_eval = backend.evaluate(problem, rolling_state)
    assert detail == "global_reoptimization_over_visible_orders"
    assert rolling_eval.customers_served == 3
    assert rolling_eval.demand_served_kg == 3.0


def test_paired_pipeline_reuses_stream_information_and_computes_benefit() -> None:
    problem = harness._synthetic_problem()
    result = harness.run_paired_pipeline(
        problem=problem,
        seeds=(11,),
        wall_clock_seconds=0.01,
        backend=harness.ToyBackend(),
    )
    online_rows = result["event_rows"]
    dynamic_rows = [row for row in online_rows if row["arm"] == harness.ARM_DYNAMIC]
    mechanical_rows = [
        row for row in online_rows if row["arm"] == harness.ARM_MECHANICAL
    ]
    assert [row["event_stream_sha256"] for row in dynamic_rows] == [
        row["event_stream_sha256"] for row in mechanical_rows
    ]
    assert [row["information_sha256"] for row in dynamic_rows] == [
        row["information_sha256"] for row in mechanical_rows
    ]
    paired = result["paired_rows"][0]
    assert paired["dynamic_benefit_cny"] == (
        paired["mechanical_realized_cost"] - paired["dynamic_realized_cost"]
    )
    assert paired["benefit_is_reportable"] is True
    static = next(
        row for row in result["raw_rows"] if row["arm"] == harness.ARM_STATIC
    )
    assert static["role"] == harness.REFERENCE_ROLE
    assert static["eligible_for_dynamic_benefit"] is False


def test_dry_run_writes_complete_synthetic_package(tmp_path: Path, capsys) -> None:
    output = tmp_path / "dynamic-dry-run"
    assert (
        harness.main(
            [
                str(output),
                "--seeds",
                "11",
                "--wall-clock-seconds",
                "0.01",
                "--dry-run",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "DRY_RUN_COMPLETED"
    expected = {
        "metadata.json",
        "raw_runs.csv",
        "per_reveal_events.csv",
        "fleet_usage.csv",
        "paired_results.csv",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
    }
    assert expected <= {path.name for path in output.iterdir() if path.is_file()}
    assert (output / "shared_event_streams/seed_11.json").is_file()
    with (output / "paired_results.csv").open(encoding="utf-8") as handle:
        paired = next(csv.DictReader(handle))
    assert paired["dynamic_benefit_cny"] == str(
        float(paired["mechanical_realized_cost"])
        - float(paired["dynamic_realized_cost"])
    )
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["run_class"] == "synthetic_dry_run"
    assert metadata["event_stream_constructed_once_per_seed"] is True
