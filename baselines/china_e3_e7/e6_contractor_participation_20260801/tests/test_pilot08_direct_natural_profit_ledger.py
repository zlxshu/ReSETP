#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (HERE, PROTOTYPE, REPO / "solver/src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_pilot08_direct_natural_profit_ledger as runner


def test_sealed_inputs_and_complete_model_close() -> None:
    rows, summary, audit = runner.derive()
    assert len(rows) == 4
    assert audit["input_manifests"]["pilot05"]["all_match"]
    assert audit["input_manifests"]["pilot06"]["all_match"]
    assert summary["grand_cost_cny"] == 6799.044523852713
    assert abs(
        summary["singleton_cost_sum_cny"]
        - sum(row["standalone_cost_cny"] for row in rows)
    ) < 1e-9


def test_output_is_only_the_five_derived_surfaces(tmp_path: Path) -> None:
    output = tmp_path / "pilot08"
    decision = runner.run(output)
    assert {path.name for path in output.iterdir()} == {
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
    }
    with (output / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert decision["formal_result"] is False
    assert "本小试没有出现需要结算才能留下的亏损方" in (
        output / "report.md"
    ).read_text(encoding="utf-8")
    manifest = json.loads((output / "artifact_hashes.json").read_text())[
        "artifacts"
    ]
    assert all(
        hashlib.sha256((output / name).read_bytes()).hexdigest() == expected
        for name, expected in manifest.items()
    )
