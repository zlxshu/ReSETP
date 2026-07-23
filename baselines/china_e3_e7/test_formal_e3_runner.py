from __future__ import annotations

from copy import deepcopy
import json

import pytest

from baselines.china_e3_e7.formal_e3_runner import (
    ARMS,
    REPO,
    _bundle_input_file_manifest,
    _require_depot_charge_before_departure,
    _require_depot_fleet_caps,
    _require_single_day_charging,
    _solution_payload,
    _validate_formal_rows,
    _verify_go_release,
    file_sha256,
    preflight,
)
from baselines.china_e3_e7.run_e3_independent_recalc import (
    load_solution,
)
from setp_solver.china81 import load_china81_bundle
from setp_solver.solution import ChargingAction, Route, Solution


def _paired_rows() -> list[dict[str, str]]:
    common = {
        "pair_id": "E3__instance__seed1",
        "instance_id": "instance",
        "seed": "1",
        "status": "complete",
        "complete_candidate_attempts": "80",
        "wallclock_safety_triggered": "False",
        "all_charge_day_offsets_zero": "True",
        "all_charging_within_registered_day": "True",
        "all_depot_charging_finishes_before_departure": "True",
        "all_depot_fleet_caps_respected": "True",
        "input_manifest_sha256": "input",
        "spatiotemporal_crosswalk_sha256": "crosswalk",
        "responsibility_map_sha256": "responsibility",
        "initial_solution_sha256": "initial",
        "algorithm_source_sha256": "algorithm",
        "evaluator_source_sha256": "evaluator",
        "go_decision_sha256": "go",
    }
    return [
        {
            **common,
            "task_id": f"task-{index}",
            "arm_id": arm,
        }
        for index, arm in enumerate(ARMS, start=1)
    ]


def test_formal_runner_remains_fail_closed_without_go(
    tmp_path,
) -> None:
    result = preflight(tmp_path / "missing-go")
    assert result["status"] == "HOLD_E3_FORMAL_RUNNER"
    assert result["formal_search_allowed"] is False
    assert result["checks"]["go_decision_pass"] is False


def test_formal_runner_rejects_stale_release_evidence(
    tmp_path,
) -> None:
    go_root = tmp_path / "go"
    go_root.mkdir()
    lock = {
        "schema": "resetp.china-e3-release-evidence-lock.v1",
        "files": {
            "baselines/china_e3_e7/formal_e3_runner.py": "0" * 64,
        },
    }
    lock_path = go_root / "release_evidence_lock.json"
    lock_path.write_text(
        json.dumps(lock, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lock_hash = file_sha256(lock_path)
    decision = {
        "verdict": "GO_E3_FORMAL_SEARCH",
        "formal_search_allowed": True,
        "release_evidence_lock_sha256": lock_hash,
    }
    metadata = {
        "release_evidence_lock_sha256": lock_hash,
        "source_hashes": {
            "baselines/china_e3_e7/formal_e3_runner.py": file_sha256(
                REPO
                / "baselines/china_e3_e7/formal_e3_runner.py"
            ),
        },
    }
    (go_root / "decision.json").write_text(
        json.dumps(decision, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (go_root / "metadata.json").write_text(
        json.dumps(metadata, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    package_hashes = {
        path.name: file_sha256(path)
        for path in go_root.iterdir()
        if path.is_file()
    }
    (go_root / "artifact_hashes.json").write_text(
        json.dumps(
            {"artifacts": package_hashes},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    result = _verify_go_release(go_root)
    assert result["passed"] is False
    assert "release_evidence_files_current" in result["failed_checks"]


def test_bundle_input_manifest_hashes_actual_files() -> None:
    bundle = load_china81_bundle(
        REPO,
        "cn-prd-10c-01-V2-LOCATIONS",
    )
    manifest = _bundle_input_file_manifest(bundle)
    assert manifest
    assert any(key.startswith("nodes:") for key in manifest)
    assert any(key.startswith("road_matrices:") for key in manifest)
    for key, observed in manifest.items():
        relative = key.split(":", 1)[1]
        assert observed == file_sha256(REPO / relative)


def test_solution_payload_preserves_charge_day_offset() -> None:
    payload = _solution_payload(
        Solution(
            charging_actions=[
                ChargingAction(
                    vehicle_id="EV1",
                    station_id="F1",
                    energy_kwh=4.0,
                    occupancy_minutes=30.0,
                    charge_start_second=1_800.0,
                    charge_day_offset=1,
                )
            ]
        )
    )
    assert payload["charging_actions"][0]["charge_day_offset"] == 1
    replayed = load_solution(payload)
    assert replayed.charging_actions[0].charge_day_offset == 1


@pytest.mark.parametrize(
    ("day_offset", "start_second"),
    ((1, 1_800.0), (0, 86_399.0)),
)
def test_formal_runner_rejects_charging_outside_registered_day(
    day_offset: int,
    start_second: float,
) -> None:
    solution = Solution(
        charging_actions=[
            ChargingAction(
                vehicle_id="EV1",
                station_id="F1",
                energy_kwh=4.0,
                occupancy_minutes=30.0,
                charge_start_second=start_second,
                charge_day_offset=day_offset,
            )
        ]
    )
    with pytest.raises(
        RuntimeError,
        match="HALT_E3_CHARGING_OUTSIDE_REGISTERED_SCENARIO_DATE",
    ):
        _require_single_day_charging(solution)


def test_formal_runner_rejects_depot_level_fleet_overuse() -> None:
    bundle = load_china81_bundle(
        REPO,
        "cn-jjj-10c-01-V2-LOCATIONS",
    )
    depot_id = next(iter(bundle.fleet_caps_by_depot))
    cap = int(bundle.fleet_caps_by_depot[depot_id]["num_cv"])
    solution = Solution(
        routes=[
            Route(
                vehicle_id=f"CV-{index}",
                vehicle_type="cv",
                home_depot_id=depot_id,
                node_sequence=[depot_id, depot_id],
            )
            for index in range(cap + 1)
        ]
    )
    with pytest.raises(RuntimeError, match="DEPOT_FLEET_CAP"):
        _require_depot_fleet_caps(solution, bundle)


def test_formal_runner_rejects_depot_charge_after_departure() -> None:
    bundle = load_china81_bundle(
        REPO,
        "cn-jjj-10c-01-V2-LOCATIONS",
    )
    depot_id = next(iter(bundle.fleet_caps_by_depot))
    solution = Solution(
        routes=[
            Route(
                vehicle_id="EV1",
                vehicle_type="ev",
                home_depot_id=depot_id,
                node_sequence=[depot_id, depot_id],
            )
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id="EV1",
                station_id=depot_id,
                energy_kwh=1.0,
                occupancy_minutes=10.0,
                charge_start_second=22_000.0,
                charge_day_offset=0,
            )
        ],
    )
    with pytest.raises(
        RuntimeError,
        match="HALT_E3_DEPOT_CHARGE_AFTER_ROUTE_DEPARTURE",
    ):
        _require_depot_charge_before_departure(solution, bundle)


def test_formal_pair_validator_accepts_exact_pair() -> None:
    pair_count, fields = _validate_formal_rows(
        _paired_rows(),
        expected=2,
    )
    assert pair_count == 1
    assert "input_manifest_sha256" in fields
    assert "initial_solution_sha256" in fields


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("input_manifest_sha256", "different-input"),
        ("responsibility_map_sha256", "different-responsibility"),
        ("initial_solution_sha256", "different-initial"),
        ("complete_candidate_attempts", "79"),
        ("wallclock_safety_triggered", "True"),
    ),
)
def test_formal_pair_validator_fails_closed(
    field: str,
    value: str,
) -> None:
    rows = deepcopy(_paired_rows())
    rows[1][field] = value
    with pytest.raises(RuntimeError):
        _validate_formal_rows(rows, expected=2)
