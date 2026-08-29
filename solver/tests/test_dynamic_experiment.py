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


def _event(
    customer_id: str,
    *,
    demand: float,
    appearance_offset: float,
    event_type: str = "add",
) -> harness.ExperimentOrder:
    return harness.ExperimentOrder(
        event_id=f"event-{customer_id}",
        customer_id=customer_id,
        appearance_second=(
            harness.C8Protocol().reception_start_second + appearance_offset
        ),
        demand_kg=demand,
        x=1.0,
        y=1.0,
        event_type=event_type,
    )


def test_quantity_trigger_counts_only_added_demand() -> None:
    events = (
        _event("A", demand=200.0, appearance_offset=60.0),
        _event(
            "B",
            demand=400.0,
            appearance_offset=120.0,
            event_type="cancel",
        ),
        _event("C", demand=300.0, appearance_offset=180.0),
    )
    stream = harness.construct_shared_event_stream(events)

    assert stream.batches[0].cause == "demand_threshold"
    assert stream.batches[0].customer_ids == ("A", "B", "C")
    assert stream.batches[0].demand_kg == 500.0


def test_paired_pipeline_applies_add_and_cancel_to_both_arms() -> None:
    result = harness.run_paired_pipeline(
        problem=harness._synthetic_problem(),
        backend=harness.ToyBackend(),
    )

    assert len(result["raw_rows"]) == 3
    assert all(row["customers_total"] == 3 for row in result["raw_rows"])
    assert all(row["customers_served"] == 3 for row in result["raw_rows"])
    assert result["paired_rows"][0]["same_service"] is True
    assert "cancel" in "|".join(
        row["event_types"] for row in result["event_rows"]
    )


def test_dry_run_has_no_seed_time_or_identity_sidecars(
    tmp_path: Path,
    capsys,
) -> None:
    output = tmp_path / "dynamic-dry-run"
    assert harness.main([str(output), "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "completed"
    assert {path.name for path in output.iterdir()} == {
        "metadata.json",
        "raw_runs.csv",
        "dynamic_events.csv",
        "paired_results.csv",
        "decision.json",
        "report.md",
    }
    with (output / "raw_runs.csv").open(encoding="utf-8") as handle:
        fields = next(csv.reader(handle))
    assert not any("seed" in field or "hash" in field for field in fields)
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["repetition_count"] == 1
