#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from pytest import MonkeyPatch

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (HERE, PROTOTYPE, REPO / "solver/src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_e6a_panel as panel
import run_pilot06_direct_15 as runner


def _fake_unit(instance: str, seed: int, output: Path) -> None:
    runner.write_json(
        output / "metadata.json",
        {
            "instance_id": instance,
            "seed": seed,
            "evidence_role": "FORMAL_PANEL_UNIT",
            "iterations_per_view": panel.formal.FORMAL_ITERATIONS,
            "archive_candidates_per_view": panel.formal.FORMAL_ARCHIVE,
            "route_pool_sp_seconds": panel.formal.FORMAL_SP_SECONDS,
        },
    )
    runner.write_json(
        output / "decision.json",
        {
            "status": "PASS_E6A_FORMAL_UNIT",
            "instance_id": instance,
            "seed": seed,
            "coalitions_solved": 15,
            "all_coalitions_legal": True,
            "grand_saving_percent": -float(seed),
            "grand_cross_contractor_customers": seed,
            "method_A_core_nonempty": False,
            "method_A_shapley_in_core": False,
        },
    )
    runner.write_rows(
        output / "raw_runs.csv",
        [
            {
                "instance_id": instance,
                "seed": seed,
                "coalition": f"coalition_{index:02d}",
                "status": "PASS",
            }
            for index in range(15)
        ],
    )
    runner.write_json(
        output / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "artifacts": {
                name: runner.sha256(output / name)
                for name in ("metadata.json", "decision.json", "raw_runs.csv")
            },
        },
    )


def test_fixed_panel_has_60_distinct_units(tmp_path: Path) -> None:
    units = panel.panel_units(tmp_path)
    assert len(units) == 60
    assert len({path for _, _, path in units}) == 60
    assert {seed for _, seed, _ in units} == set(range(1, 11))


def test_unit_command_uses_formal_entry_without_smoke(tmp_path: Path) -> None:
    command = panel._unit_command("cn-prd-150c-01-V2-LOCATIONS", 3, tmp_path)
    assert command[0] == sys.executable
    assert command[1].endswith("run_e6a_formal.py")
    assert "--smoke" not in command
    assert command[-1] == str(tmp_path)


def test_finalize_accepts_negative_effect_and_writes_terminal_last(
    tmp_path: Path,
) -> None:
    for instance, seed, output in panel.panel_units(tmp_path):
        _fake_unit(instance, seed, output)

    decision = panel.finalize_panel(tmp_path)
    assert decision["status"] == "PASS_E6A_PANEL_COMPLETE"
    assert decision["unit_count"] == 60
    assert decision["coalition_row_count"] == 900
    assert decision["descriptive_summary"]["grand_saving_percent_max"] < 0
    assert decision["descriptive_summary"]["core_nonempty_units"] == 0
    assert runner.verify_manifest(tmp_path)
    assert panel.completed_panel(tmp_path) == decision
    with (tmp_path / "panel_raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 900


def test_failed_child_preserves_error(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    class Failed:
        returncode = 7
        stdout = "child stdout"
        stderr = "child stderr"

    monkeypatch.setattr(panel.subprocess, "run", lambda *args, **kwargs: Failed())
    result = panel.run_subprocess_unit("cn-prd-150c-01-V2-LOCATIONS", 1, tmp_path)
    assert not result["ok"]
    payload = json.loads((tmp_path / "last_error.json").read_text(encoding="utf-8"))
    assert payload["returncode"] == 7
    assert payload["stdout"] == "child stdout"


def test_failed_panel_has_no_terminal(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        panel,
        "run_subprocess_unit",
        lambda instance, seed, output: {
            "instance_id": instance,
            "seed": seed,
            "ok": False,
            "error": "test failure",
        },
    )
    code, decision = panel.run_panel(tmp_path, workers=4)
    assert code == 1
    assert decision["status"] == "HALT_E6A_PANEL_UNIT_FAILURE"
    assert not (tmp_path / "panel_complete.json").exists()
