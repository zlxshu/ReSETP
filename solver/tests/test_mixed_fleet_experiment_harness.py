from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "solver/scripts/run_mixed_fleet_experiment.py"
SPEC = importlib.util.spec_from_file_location("mixed_fleet_harness", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = harness
SPEC.loader.exec_module(harness)


def test_pairing_accepts_only_arm_as_the_treatment_difference() -> None:
    identities = harness._pair_identities(
        ("endogenous", "fixed25", "same_total_cap"),
        instance_id="cn-prd-50c-01-V2-LOCATIONS",
        seed=11,
        wall_clock_budget_seconds=1200.0,
        objective_mode="bi_objective",
        input_snapshot_sha256="a" * 64,
    )
    harness.validate_pairing(identities)
    with pytest.raises(harness.PairingMismatchError, match="wall_clock"):
        harness.validate_pairing(
            (identities[0], replace(identities[1], wall_clock_budget_seconds=60.0))
        )


def test_arm_definitions_cover_main_reference_control_and_endpoints() -> None:
    assert harness.ARM_DEFINITIONS["endogenous"].role == "MAIN_TREATMENT"
    assert harness.ARM_DEFINITIONS["fixed25"].role == "HISTORICAL_REFERENCE"
    assert (
        harness.ARM_DEFINITIONS["same_total_cap"].role
        == "FLEET_SIZE_CONFOUND_CONTROL"
    )
    assert harness.ARM_DEFINITIONS["all_cv"].initial_witness_level == "0"
    assert harness.ARM_DEFINITIONS["all_ev"].initial_witness_level == "100"


def test_real_arm_bundles_apply_caps_without_changing_chargers() -> None:
    instance = "cn-prd-50c-01-V2-LOCATIONS"
    fixed = harness._arm_bundle(REPO, instance, "fixed25")
    endogenous = harness._arm_bundle(REPO, instance, "endogenous")
    matched = harness._arm_bundle(REPO, instance, "same_total_cap")
    all_cv = harness._arm_bundle(REPO, instance, "all_cv")
    all_ev = harness._arm_bundle(REPO, instance, "all_ev")

    for depot_id in fixed.fleet_caps_by_depot:
        fixed_caps = fixed.fleet_caps_by_depot[depot_id]
        endogenous_caps = endogenous.fleet_caps_by_depot[depot_id]
        matched_caps = matched.fleet_caps_by_depot[depot_id]
        assert matched_caps["num_cv"] == endogenous_caps["num_cv"]
        assert matched_caps["num_ev"] == endogenous_caps["num_ev"]
        assert matched_caps["total_fleet_cap"] == fixed_caps["total_fleet_cap"]
        assert all_cv.fleet_caps_by_depot[depot_id] == {
            "num_cv": endogenous_caps["num_cv"],
            "num_ev": 0,
            "total_fleet_cap": endogenous_caps["num_cv"],
        }
        assert all_ev.fleet_caps_by_depot[depot_id] == {
            "num_cv": 0,
            "num_ev": endogenous_caps["num_ev"],
            "total_fleet_cap": endogenous_caps["num_ev"],
        }
        for bundle in (fixed, endogenous, matched, all_cv, all_ev):
            charger = bundle.charger_scenario_by_node[depot_id]
            assert charger["charger_count"] == 2
            assert charger["charge_power_kw"] == pytest.approx(22.0)


def test_all_real_arm_setups_materialise_without_search() -> None:
    instance = "cn-prd-50c-01-V2-LOCATIONS"
    expected_registered = {
        "endogenous": 18,
        "fixed25": 8,
        "same_total_cap": 18,
        "all_cv": 9,
        "all_ev": 9,
    }
    for arm, expected_count in expected_registered.items():
        bundle = harness._arm_bundle(REPO, instance, arm)
        values = {depot_id: 1.0 for depot_id in bundle.fleet_caps_by_depot}
        record = {
            "values": values,
            "value_sha256": harness._json_sha256(
                [
                    [key, float(value).hex()]
                    for key, value in sorted(values.items())
                ]
            ),
            "source_id": "SECONDS_ONLY_UNIT_WIRING_NOT_FORMAL",
        }
        checked_bundle, initial, context = harness._arm_setup(
            REPO,
            instance,
            arm,
            record,
        )
        assert checked_bundle.instance_id == instance
        assert len(initial.duties) == expected_count
        assert context.fairness_enabled is True


def test_parser_rejects_more_than_p20_and_duplicate_seeds(tmp_path: Path) -> None:
    common = [
        "--output-dir",
        str(tmp_path / "out"),
        "--instances",
        "cn-prd-50c-01-V2-LOCATIONS",
        "--arms",
        "endogenous",
        "fixed25",
        "--seeds",
        "11",
        "--wall-clock-seconds",
    ]
    with pytest.raises(SystemExit):
        harness._parse_args([*common, "1200.001", "--dry-run"])
    with pytest.raises(SystemExit):
        harness._parse_args(
            [
                *common[:-3],
                "--seeds",
                "11",
                "11",
                "--wall-clock-seconds",
                "1200",
                "--dry-run",
            ]
        )


def test_dry_run_is_solver_free_and_does_not_create_output(tmp_path: Path) -> None:
    output = tmp_path / "must-not-exist"
    completed = subprocess.run(
        (
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(output),
            "--instances",
            "cn-prd-50c-01-V2-LOCATIONS",
            "--arms",
            "endogenous",
            "fixed25",
            "same_total_cap",
            "--seeds",
            "11",
            "29",
            "--wall-clock-seconds",
            "1200",
            "--dry-run",
        ),
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["mode"] == "DRY_RUN"
    assert payload["solver_entered"] is False
    assert payload["output_directory_created"] is False
    assert payload["serial_execution"] is True
    assert payload["objective_mode"] == "bi_objective"
    assert payload["pair_validation"] == "PASSED"
    assert payload["planned_run_count"] == 6
    assert payload["formal_launch_ready"] is False
    assert not output.exists()


def test_report_fields_include_service_fleet_emissions_and_pareto() -> None:
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
        "pareto_point_count",
    }
    assert required.issubset(set(harness._ordered_fields(({},))))
