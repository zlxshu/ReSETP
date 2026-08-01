#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (HERE, PROTOTYPE, REPO / "solver/src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_pilot11_montoya_time_metric_reaccounting as runner


def test_90_sealed_units_reaccount_without_missing_inputs() -> None:
    rows, summaries, audit = runner.derive()
    assert len(rows) == 90
    assert len(summaries) == 4
    assert audit["all_artifacts_match"]
    assert sum(row["approximation"] in {"L1", "L2"} for row in rows) == 60
    assert all(
        abs(row["own_minus_pl_minutes"]) < 1e-9
        for row in rows
        if row["approximation"] == "PL"
    )


def test_metric_ignores_service_time() -> None:
    path = next(
        item
        for item in sorted((runner.SOURCE / "units").glob("*.json"))
        if not item.name.startswith("._")
    )
    payload = runner.read_json(path)
    row = payload["row"]
    base = runner.load_china81_bundle(runner.REPO, row["instance_id"])
    bundle = runner.source._bundle_for(
        base,
        capacity_kwh=float(row["capacity_kwh"]),
        approximation=row["approximation"],
    )
    solution = runner.load_solution(payload["solution"])
    changed = replace(
        bundle,
        instance=replace(
            bundle.instance,
            nodes=[replace(node, service_time=node.service_time + 999.0) for node in bundle.instance.nodes],
        ),
    )
    assert runner.time_metric(solution, bundle) == runner.time_metric(solution, changed)


def test_output_has_five_hashed_surfaces(tmp_path: Path) -> None:
    output = tmp_path / "pilot11"
    decision = runner.run(output)
    assert decision["rows_written"] == 90
    assert {path.name for path in output.iterdir()} == {
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
    }
    with (output / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 90
    manifest = json.loads((output / "artifact_hashes.json").read_text())[
        "artifacts"
    ]
    assert all(
        hashlib.sha256((output / name).read_bytes()).hexdigest() == expected
        for name, expected in manifest.items()
    )
