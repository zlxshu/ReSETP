from __future__ import annotations

from dr_alns_ppo.pilot13_changed_candidate_tools import (
    classify_changed_candidate_headroom,
    _initial_mode_flags,
    paired_relative_percent,
    render_report,
    summarize_charging_rows,
    summarize_repair_rows,
    threeshift_probe_bundles,
)


def test_paired_relative_percent_positive_means_candidate_better() -> None:
    assert paired_relative_percent(candidate_cost=90.0, baseline_cost=100.0) == 10.0


def test_threeshift_probe_bundles_are_50c_train_75c_held() -> None:
    bundles = threeshift_probe_bundles()
    names = [row["bundle_name"] for row in bundles]
    assert names == [
        "e2-threeshift-50c-01",
        "e2-threeshift-50c-02",
        "e2-threeshift-50c-03",
        "e2-threeshift-75c-01",
        "e2-threeshift-75c-02",
        "e2-threeshift-75c-03",
    ]
    assert {row["bundle_role"] for row in bundles[:3]} == {"train_probe"}
    assert {row["bundle_role"] for row in bundles[3:]} == {"held_probe"}
    assert not any("100c" in row["bundle_name"] for row in bundles)


def test_initial_mode_flags_keep_worker_cv_default() -> None:
    assert _initial_mode_flags("worker_cv") == (False, False)
    assert _initial_mode_flags("ev_optional") == (True, False)
    assert _initial_mode_flags("ev_required") == (True, True)


def test_gate_halts_when_destroy_never_removes_customers() -> None:
    rows = [
        {
            "destroy_changed": False,
            "destroy_removed_count": 0,
            "repair_options_total": 0,
            "default_changed_any": False,
            "alternative_changed_count": 0,
            "alternative_improving_count": 0,
            "best_alternative_relative_percent": float("-inf"),
        }
    ]
    gate = classify_changed_candidate_headroom(rows, [])
    assert gate["status"] == "HALT_DESTROY_NO_REMOVAL"


def test_gate_halts_when_repair_has_no_options() -> None:
    rows = [
        {
            "destroy_changed": True,
            "destroy_removed_count": 5,
            "repair_options_total": 0,
            "default_changed_any": False,
            "alternative_changed_count": 0,
            "alternative_improving_count": 0,
            "best_alternative_relative_percent": float("-inf"),
        }
    ]
    gate = classify_changed_candidate_headroom(rows, [])
    assert gate["status"] == "HALT_REPAIR_NO_OPTIONS"


def test_gate_passes_on_improving_repair_alternative() -> None:
    rows = [
        {
            "destroy_changed": True,
            "destroy_removed_count": 5,
            "repair_options_total": 12,
            "default_changed_any": False,
            "alternative_changed_count": 2,
            "alternative_improving_count": 1,
            "best_alternative_relative_percent": 1.2,
        }
    ]
    gate = classify_changed_candidate_headroom(rows, [])
    assert gate["status"] == "PASS_REPAIR_IMPROVING_HEADROOM"


def test_gate_reports_charging_no_landing_point_when_no_ev_candidates() -> None:
    rows = [
        {
            "destroy_changed": True,
            "destroy_removed_count": 5,
            "repair_options_total": 12,
            "default_changed_any": False,
            "alternative_changed_count": 0,
            "alternative_improving_count": 0,
            "best_alternative_relative_percent": float("-inf"),
        }
    ]
    gate = classify_changed_candidate_headroom(
        rows,
        [
            {
                "cv_to_ev_candidate_count": 0,
                "changed_cv_to_ev_count": 0,
                "feasible_cv_to_ev_count": 0,
                "best_cv_to_ev_relative_percent": float("-inf"),
            }
        ],
    )
    assert gate["status"] == "HALT_NO_CHANGED_CANDIDATE_HEADROOM"
    assert gate["charging_gate"] == "HALT_CHARGING_NO_LANDING_POINT"


def test_gate_passes_on_charging_landing_point() -> None:
    rows = [
        {
            "destroy_changed": True,
            "destroy_removed_count": 5,
            "repair_options_total": 12,
            "default_changed_any": False,
            "alternative_changed_count": 0,
            "alternative_improving_count": 0,
            "best_alternative_relative_percent": float("-inf"),
        }
    ]
    gate = classify_changed_candidate_headroom(
        rows,
        [
            {
                "cv_to_ev_candidate_count": 2,
                "changed_cv_to_ev_count": 1,
                "feasible_cv_to_ev_count": 1,
                "best_cv_to_ev_relative_percent": -0.5,
            }
        ],
    )
    assert gate["status"] == "PASS_CHARGING_LANDING_POINT"


def test_gate_rejects_infeasible_charging_shape_changes() -> None:
    rows = [
        {
            "destroy_changed": True,
            "destroy_removed_count": 5,
            "repair_options_total": 12,
            "default_changed_any": False,
            "alternative_changed_count": 0,
            "alternative_improving_count": 0,
            "best_alternative_relative_percent": float("-inf"),
        }
    ]
    gate = classify_changed_candidate_headroom(
        rows,
        [
            {
                "cv_to_ev_candidate_count": 2,
                "changed_cv_to_ev_count": 2,
                "feasible_cv_to_ev_count": 0,
                "best_cv_to_ev_relative_percent": float("-inf"),
            }
        ],
    )
    assert gate["status"] == "HALT_NO_CHANGED_CANDIDATE_HEADROOM"
    assert gate["charging_gate"] == "HALT_CHARGING_NO_LANDING_POINT"


def test_summaries_keep_role_level_counts() -> None:
    repair = summarize_repair_rows(
        [
            {
                "bundle_role": "held_probe",
                "destroy_removed_count": 5,
                "destroy_changed": True,
                "repair_options_total": 12,
                "default_changed_any": False,
                "alternative_changed_count": 2,
                "alternative_improving_count": 1,
                "best_alternative_relative_percent": 0.7,
            }
        ]
    )
    charging = summarize_charging_rows(
        [
            {
                "bundle_role": "held_probe",
                "initial_cv_routes": 11,
                "initial_ev_routes": 0,
                "initial_charging_actions": 0,
                "cv_to_ev_candidate_count": 3,
                "changed_cv_to_ev_count": 2,
                "feasible_cv_to_ev_count": 2,
                "best_cv_to_ev_relative_percent": -0.1,
            }
        ]
    )
    assert repair[0]["alternative_improving_count"] == 1
    assert charging[0]["cv_to_ev_candidate_count"] == 3


def test_report_mentions_no_training_and_decision() -> None:
    summary = {
        "gate": {"status": "HALT_NO_CHANGED_CANDIDATE_HEADROOM"},
        "repair_summary": [],
        "charging_summary": [],
    }
    text = render_report(summary=summary, repair_rows=[], charging_rows=[])
    assert "no training" in text
    assert "changed candidate" in text or "changed-candidate" in text
