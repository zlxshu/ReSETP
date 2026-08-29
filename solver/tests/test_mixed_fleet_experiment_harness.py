from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "solver/scripts/run_mixed_fleet_experiment.py"
INSTANCE = "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
SPEC = importlib.util.spec_from_file_location("mixed_fleet_harness", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = harness
SPEC.loader.exec_module(harness)


def test_paper_protocol_has_four_levels_and_three_repeats() -> None:
    assert harness.REPEAT_COUNT == 3
    assert tuple(harness.ARM_DEFINITIONS) == (
        "cv18_ev2",
        "cv13_ev7",
        "cv7_ev13",
        "cv2_ev18",
    )
    for arm, caps in harness.FLEET_LEVEL_CAPS.items():
        cv = sum(values[0] for values in caps.values())
        ev = sum(values[1] for values in caps.values())
        assert arm == f"cv{cv}_ev{ev}"
        assert cv + ev == 20


def test_real_level_setups_change_fleet_only_without_search() -> None:
    for arm, requested in harness.FLEET_LEVEL_CAPS.items():
        bundle, initial, context = harness._arm_setup(
            REPO,
            INSTANCE,
            arm,
            "literature_pwl",
        )
        assert len(initial.duties) == 20
        assert context.fairness_enabled is False
        assert bundle.fleet_parameter_class_id == arm
        for depot_id, (cv, ev) in requested.items():
            assert dict(bundle.fleet_caps_by_depot[depot_id]) == {
                "num_cv": cv,
                "num_ev": ev,
                "total_fleet_cap": cv + ev,
            }
            charger = bundle.charger_scenario_by_node[depot_id]
            assert charger["charger_count"] == 2
            assert charger["charge_power_kw"] == pytest.approx(60.0)


def test_removed_run_limits_and_random_track_cli_are_rejected(tmp_path: Path) -> None:
    common = [
        "--output-dir",
        str(tmp_path / "out"),
        "--instances",
        INSTANCE,
        "--dry-run",
    ]
    harness._parse_args(common)
    for removed in (
        ("--seeds", "11"),
        ("--wall-clock-seconds", "1200"),
        ("--iterations", "1000"),
    ):
        with pytest.raises(SystemExit):
            harness._parse_args([*common, *removed])


def test_dry_run_is_solver_free_and_plans_three_runs_per_level(
    tmp_path: Path,
) -> None:
    output = tmp_path / "must-not-exist"
    completed = subprocess.run(
        (
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(output),
            "--instances",
            INSTANCE,
            "--dry-run",
        ),
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["solver_entered"] is False
    assert payload["output_directory_created"] is False
    assert payload["repeat_count"] == 3
    assert payload["planned_run_count"] == 12
    assert payload["stop_rule"] == "500 consecutive iterations without improvement"
    assert not ({"seeds", "wall_clock_budget_seconds_per_run"} & payload.keys())
    assert not output.exists()


def test_report_fields_keep_service_fleet_emissions_and_real_failures() -> None:
    required = {
        "customers_served",
        "demand_served",
        "used_cv_vehicles",
        "used_ev_vehicles",
        "cv_trips",
        "ev_trips",
        "fleet_use_by_depot_json",
        "direct_emissions_kg",
        "indirect_emissions_kg",
        "total_emissions_kg",
        "feasible",
        "error_type",
        "error",
    }
    row = dict.fromkeys(required)
    assert required.issubset(set(harness._ordered_fields((row,))))


def test_cost_does_not_override_abnormal_or_incomplete_acceptance() -> None:
    complete = {
        "run_status": "STOPPED_BY_CALLER",
        "total_cost_cny": 100.0,
        "feasible": True,
        "violation_count": 0,
        "customers_served": 10,
        "customers_total": 10,
        "demand_served": 100.0,
        "demand_total": 100.0,
    }
    accepted = {**complete, **harness._assess_row(complete).row_fields()}
    assert harness._successful((accepted,)) == [accepted]

    for changed in (
        {"run_status": "INTERNAL_ERROR"},
        {"feasible": False, "violation_count": 1},
        {"customers_served": 9},
        {"demand_served": 99.0},
    ):
        row = {**complete, **changed}
        row.update(harness._assess_row(row).row_fields())
        assert row["total_cost_cny"] == 100.0
        assert harness._successful((row,)) == []
