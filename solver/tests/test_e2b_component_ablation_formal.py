from __future__ import annotations

import json

import pytest

from baselines.e2_alns import e2b_component_ablation_formal_20260715 as formal


INSTANCE = "L-main-threeshift-50c-01"


def _solution_payload(
    *,
    charge_start_second: float = 100.0,
    energy_kwh: float = 12.5,
    vehicle_id: str = "EV1#T1",
) -> dict[str, object]:
    return {
        "routes": [
            {
                "vehicle_id": vehicle_id,
                "vehicle_type": "ev",
                "home_depot_id": "D0",
                "node_sequence": ["D0", "C1", "D0"],
            }
        ],
        "charging_actions": [
            {
                "vehicle_id": vehicle_id,
                "station_id": "D0",
                "energy_kwh": energy_kwh,
                "occupancy_minutes": 15.0,
                "charge_start_second": charge_start_second,
                "charge_day_offset": 0,
            }
        ],
        "cross_site_services": [],
    }


def _complete_unit(eval_budget: int = 1000) -> list[dict[str, object]]:
    expected_staged = json.dumps(formal.probe.expected_staged_budgets(eval_budget))
    common: dict[str, object] = {
        "instance": INSTANCE,
        "seed": 1,
        "condition": formal.CONDITION,
        "start_solution_sha256": "shared-start",
        "source_group": "self",
        "search_performed": True,
        "configured_search_budget": eval_budget,
        "actual_search_evals": eval_budget,
        "source_search_evals": eval_budget,
        "strict_multitrip": True,
        "allow_cross_depot": True,
        "valid": True,
        "violation_count": 0,
        "cost_component_error": 0.0,
        "dedicated_cross_destroy_attempts": 0,
        "dedicated_cross_repair_attempts": 0,
        "charging_actions_moved": 0,
        "charging_actions_moved_from_before": 0,
        "total_cost": 100.0,
        "cost_fix": 10.0,
        "cost_km": 10.0,
        "cost_fuel": 10.0,
        "cost_elec": 10.0,
        "cost_occ": 10.0,
        "cost_transship": 10.0,
        "cost_carbon": 10.0,
        "E_total": 20.0,
        "E_cv_direct": 10.0,
        "E_ev_indirect": 10.0,
        "electricity_kwh": 12.5,
    }
    rows = [
        {
            **common,
            "group_id": "A_continuous",
            "enable_staged_search": False,
            "enable_cross_depot_operator": False,
            "reciprocal_cross_depot": False,
            "stage_budgets_json": json.dumps([eval_budget]),
            "strong_phase_indexes_json": json.dumps([]),
        },
        {
            **common,
            "group_id": "B_staged",
            "enable_staged_search": True,
            "enable_cross_depot_operator": False,
            "reciprocal_cross_depot": False,
            "stage_budgets_json": expected_staged,
            "strong_phase_indexes_json": json.dumps([1]),
            "total_cost": 98.0,
        },
        {
            **common,
            "group_id": "C_staged_cross",
            "enable_staged_search": True,
            "enable_cross_depot_operator": True,
            "reciprocal_cross_depot": True,
            "stage_budgets_json": expected_staged,
            "strong_phase_indexes_json": json.dumps([1]),
            "dedicated_cross_destroy_attempts": 2,
            "dedicated_cross_repair_attempts": 2,
            "total_cost": 97.0,
        },
        {
            **common,
            "group_id": "D_full",
            "source_group": "C_staged_cross",
            "search_performed": False,
            "configured_search_budget": 0,
            "actual_search_evals": 0,
            "source_search_evals": eval_budget,
            "enable_staged_search": "",
            "enable_cross_depot_operator": "",
            "reciprocal_cross_depot": "",
            "stage_budgets_json": expected_staged,
            "strong_phase_indexes_json": json.dumps([1]),
            "dedicated_cross_destroy_attempts": 2,
            "dedicated_cross_repair_attempts": 2,
            "charging_actions_moved": 1,
            "charging_actions_moved_from_before": 1,
            "charging_timing_changed_from_before": True,
            "route_unchanged_from_before": True,
            "vehicle_unchanged_from_before": True,
            "charging_identity_unchanged_from_before": True,
            "total_energy_unchanged_from_before": True,
            "total_cost": 96.0,
            "cost_carbon": 9.0,
            "E_total": 19.0,
            "E_ev_indirect": 9.0,
        },
    ]
    return rows


def test_formal_default_manifest_is_nine_by_five_by_three_searches() -> None:
    tasks = formal.build_formal_tasks(
        formal.FORMAL_INSTANCES,
        formal.FORMAL_SEEDS,
        eval_budget=formal.FORMAL_EVAL_BUDGET,
    )

    assert len(tasks) == 9 * 5 * 3
    assert len({task["input_data_sha256"] for task in tasks}) == 9
    assert all(task["strict_multitrip"] for task in tasks)
    assert all(task["allow_cross_depot"] for task in tasks)
    assert all(task["eval_budget"] == 4000 for task in tasks)
    assert "D_full" not in {task["group_id"] for task in tasks}


def test_manifest_gate_rejects_component_switch_drift_before_search() -> None:
    tasks = formal.build_formal_tasks((INSTANCE,), (1,), eval_budget=17)
    a_task = next(task for task in tasks if task["group_id"] == "A_continuous")
    a_task["enable_staged_search"] = True

    with pytest.raises(ValueError, match="component switch drift"):
        formal.validate_formal_task_manifest(
            tasks,
            instances=(INSTANCE,),
            seeds=(1,),
            eval_budget=17,
        )


def test_cli_supports_workers_six_to_eight_and_tiny_overrides() -> None:
    args = formal.parse_args(
        [
            "--instances",
            INSTANCE,
            "--seeds",
            "3,5",
            "--eval-budget",
            "17",
            "--workers",
            "8",
        ]
    )

    assert args.instances == (INSTANCE,)
    assert args.seeds == (3, 5)
    assert args.eval_budget == 17
    assert args.workers == 8
    with pytest.raises(SystemExit):
        formal.parse_args(["--workers", "5"])


def test_d_fingerprints_allow_timing_only_and_reject_energy_change() -> None:
    start = _solution_payload(charge_start_second=50.0)
    c_payload = _solution_payload(charge_start_second=100.0)
    d_payload = _solution_payload(charge_start_second=200.0)
    rows = [
        {
            "instance": INSTANCE,
            "seed": 1,
            "group_id": "C_staged_cross",
            "_solution_payload": c_payload,
        },
        {
            "instance": INSTANCE,
            "seed": 1,
            "group_id": "D_full",
            "_solution_payload": d_payload,
        },
    ]

    formal.attach_before_after_fingerprints(rows, {(INSTANCE, 1): start})
    d_row = rows[1]
    assert d_row["fingerprint_basis"] == "C_staged_cross_to_D_full"
    assert d_row["route_unchanged_from_before"] is True
    assert d_row["vehicle_unchanged_from_before"] is True
    assert d_row["charging_identity_unchanged_from_before"] is True
    assert d_row["total_energy_unchanged_from_before"] is True
    assert d_row["charging_timing_changed_from_before"] is True
    assert d_row["charging_actions_moved_from_raw_search_output"] == 0
    assert d_row["charging_actions_moved_from_before"] == 1

    rows[1]["_solution_payload"] = _solution_payload(
        charge_start_second=200.0, energy_kwh=13.0
    )
    formal.attach_before_after_fingerprints(rows, {(INSTANCE, 1): start})
    assert rows[1]["charging_identity_unchanged_from_before"] is False
    assert rows[1]["total_energy_unchanged_from_before"] is False


def test_subset_assessment_passes_contract_but_forbids_formal_inference() -> None:
    decision = formal.assess_formal(
        _complete_unit(),
        instances=(INSTANCE,),
        seeds=(1,),
        eval_budget=1000,
    )

    assert decision["verdict"] == "PASS_E2B_SUBSET_ONLY"
    assert decision["formal_inference_allowed"] is False
    assert decision["failure_count"] == 0
    assert decision["d_moved_charging_unit_count"] == 1
    assert decision["d_strict_carbon_improvement_unit_count"] == 1


def test_d_null_carbon_effect_is_valid_evidence_not_performance_filtered() -> None:
    rows = _complete_unit()
    c_row = next(row for row in rows if row["group_id"] == "C_staged_cross")
    d_row = next(row for row in rows if row["group_id"] == "D_full")
    d_row["E_ev_indirect"] = c_row["E_ev_indirect"]

    decision = formal.assess_formal(
        rows,
        instances=(INSTANCE,),
        seeds=(1,),
        eval_budget=1000,
    )

    assert decision["verdict"] == "PASS_E2B_SUBSET_ONLY"
    assert decision["failure_count"] == 0
    assert decision["d_strict_carbon_improvement_unit_count"] == 0


def test_complete_default_matrix_is_the_only_formal_ready_contract() -> None:
    rows: list[dict[str, object]] = []
    for instance in formal.FORMAL_INSTANCES:
        for seed in formal.FORMAL_SEEDS:
            unit = _complete_unit(formal.FORMAL_EVAL_BUDGET)
            for row in unit:
                row["instance"] = instance
                row["seed"] = seed
            rows.extend(unit)

    decision = formal.assess_formal(
        rows,
        instances=formal.FORMAL_INSTANCES,
        seeds=formal.FORMAL_SEEDS,
        eval_budget=formal.FORMAL_EVAL_BUDGET,
    )

    assert decision["verdict"] == "E2B_FORMAL_EVIDENCE_READY"
    assert decision["formal_inference_allowed"] is True
    assert decision["formal_request_shape_complete"] is True
    assert decision["formal_contract_complete"] is True
    assert decision["expected_search_rows"] == 135
    assert decision["expected_evidence_rows"] == 180


def test_strict_multitrip_and_cross_depot_domain_cannot_be_ablated() -> None:
    rows = _complete_unit()
    b_row = next(row for row in rows if row["group_id"] == "B_staged")
    b_row["strict_multitrip"] = False
    b_row["allow_cross_depot"] = False

    decision = formal.assess_formal(
        rows,
        instances=(INSTANCE,),
        seeds=(1,),
        eval_budget=1000,
    )

    assert decision["verdict"] == "HALT_E2B_FORMAL_EVIDENCE"
    assert decision["formal_contract_complete"] is False
    assert any("feasible-domain contract failed" in failure for failure in decision["failures"])


def test_assessment_halts_on_d_energy_or_search_invariant_failure() -> None:
    rows = _complete_unit()
    d_row = next(row for row in rows if row["group_id"] == "D_full")
    d_row["total_energy_unchanged_from_before"] = False
    d_row["actual_search_evals"] = 1

    decision = formal.assess_formal(
        rows,
        instances=(INSTANCE,),
        seeds=(1,),
        eval_budget=1000,
    )

    assert decision["verdict"] == "HALT_E2B_FORMAL_EVIDENCE"
    assert any("unexpected route search" in failure for failure in decision["failures"])
    assert any("total_energy_unchanged_from_before" in failure for failure in decision["failures"])


def test_file_fingerprint_excludes_appledouble(tmp_path) -> None:
    real = tmp_path / "instance.json"
    sidecar = tmp_path / "._instance.json"
    real.write_text("real", encoding="utf-8")
    sidecar.write_text("noise-1", encoding="utf-8")

    hashes, first = formal.fingerprint_files((real, sidecar))
    sidecar.write_text("noise-2", encoding="utf-8")
    _, second = formal.fingerprint_files((real, sidecar))

    assert list(hashes) == [str(real.resolve())]
    assert first == second


def test_post_run_input_recheck_detects_frozen_data_drift(tmp_path) -> None:
    data = tmp_path / "instance.json"
    data.write_text("frozen", encoding="utf-8")
    hashes, fingerprint = formal.fingerprint_files((data,))
    task = {
        "instance": INSTANCE,
        "input_file_hashes_json": json.dumps(hashes, sort_keys=True),
        "input_data_sha256": fingerprint,
    }

    assert formal.input_drift_failures((task,)) == []
    data.write_text("drifted", encoding="utf-8")
    failures = formal.input_drift_failures((task,))
    assert len(failures) == 1
    assert "frozen input drift after run" in failures[0]


def test_output_directory_must_be_empty_to_exclude_interrupted_run_residue(tmp_path) -> None:
    out = tmp_path / "formal"
    out.mkdir()
    formal.validate_fresh_output_dir(out)
    (out / "worker_failures.json").write_text("[]", encoding="utf-8")

    with pytest.raises(FileExistsError, match="non-empty E2b output directory"):
        formal.validate_fresh_output_dir(out)


def test_evidence_writer_generates_four_piece_bundle_and_report(tmp_path) -> None:
    decision = formal.assess_formal(
        _complete_unit(),
        instances=(INSTANCE,),
        seeds=(1,),
        eval_budget=1000,
    )
    formal.write_evidence_bundle(
        tmp_path,
        rows=_complete_unit(),
        metadata={"schema": "test"},
        decision=decision,
    )

    assert all((tmp_path / name).is_file() for name in formal.REQUIRED_EVIDENCE)
    inventory = json.loads((tmp_path / "artifact_hashes.json").read_text(encoding="utf-8"))
    assert {"metadata.json", "raw_runs.csv", "decision.json", "report.md"} <= set(inventory)
    for name, digest in inventory.items():
        assert formal.sha256(tmp_path / name) == digest


def test_formal_contract_requires_exact_default_matrix() -> None:
    assert formal.full_formal_contract(
        formal.FORMAL_INSTANCES,
        formal.FORMAL_SEEDS,
        formal.FORMAL_EVAL_BUDGET,
    )
    assert not formal.full_formal_contract(
        formal.FORMAL_INSTANCES[:-1],
        formal.FORMAL_SEEDS,
        formal.FORMAL_EVAL_BUDGET,
    )
    assert not formal.full_formal_contract(
        formal.FORMAL_INSTANCES,
        formal.FORMAL_SEEDS,
        formal.FORMAL_EVAL_BUDGET - 1,
    )
