from __future__ import annotations

import json

from baselines.e2_alns import e2b_component_ablation_probe_20260715 as probe


def test_probe_manifest_has_three_searches_and_no_fourth_search_task() -> None:
    instance = "L-main-threeshift-50c-01"
    tasks = probe.build_search_tasks([instance], [1], eval_budget=1000, condition="mixed")

    assert [task["group_id"] for task in tasks] == [
        "A_continuous",
        "B_staged",
        "C_staged_cross",
    ]
    assert len({task["start_solution_sha256"] for task in tasks}) == 1
    assert len({task["eval_budget"] for task in tasks}) == 1
    assert all(task["eval_budget"] == 1000 for task in tasks)
    assert all("D_full" != task["group_id"] for task in tasks)
    assert [task["enable_staged_search"] for task in tasks] == [False, True, True]
    assert [task["enable_cross_depot_operator"] for task in tasks] == [False, False, True]
    assert [task["reciprocal_cross_depot"] for task in tasks] == [False, False, True]
    assert probe.expected_staged_budgets(1000) == [400, 200, 400]
    assert probe.expected_staged_budgets(4000) == [400, 3200, 400]


def test_probe_assessment_requires_group_d_to_reuse_group_c_routes() -> None:
    common = {
        "instance": "L-main-threeshift-50c-01",
        "seed": 1,
        "start_solution_sha256": "same-start",
        "actual_search_evals": 1000,
        "valid": True,
        "strict_multitrip": True,
        "allow_cross_depot": True,
        "dedicated_cross_destroy_attempts": 0,
        "route_signature": "route-a",
        "search_performed": True,
        "stage_budgets_json": json.dumps([400, 200, 400]),
        "strong_phase_indexes_json": json.dumps([1]),
    }
    rows = [
        {
            **common,
            "group_id": "A_continuous",
            "stage_budgets_json": json.dumps([1000]),
            "strong_phase_indexes_json": json.dumps([]),
        },
        {**common, "group_id": "B_staged"},
        {**common, "group_id": "C_staged_cross", "dedicated_cross_destroy_attempts": 1, "route_signature": "route-c"},
        {
            **common,
            "group_id": "D_full",
            "route_signature": "route-c",
            "search_performed": False,
            "actual_search_evals": 0,
        },
    ]

    decision = probe.assess_probe(rows, 1000)

    assert decision["status"] == "PASS_WIRING_ONLY"
    assert decision["formal_inference_allowed"] is False


def test_probe_assessment_stops_if_charging_replay_changes_routes() -> None:
    instance = "L-main-threeshift-50c-01"
    rows = []
    for group in ("A_continuous", "B_staged", "C_staged_cross", "D_full"):
        rows.append(
            {
                "instance": instance,
                "seed": 1,
                "group_id": group,
                "start_solution_sha256": "same-start",
                "actual_search_evals": 0 if group == "D_full" else 1000,
                "valid": True,
                "strict_multitrip": True,
                "allow_cross_depot": True,
                "dedicated_cross_destroy_attempts": 1 if group == "C_staged_cross" else 0,
                "route_signature": "changed" if group == "D_full" else "source",
                "search_performed": group != "D_full",
                "stage_budgets_json": json.dumps([1000] if group == "A_continuous" else [400, 200, 400]),
                "strong_phase_indexes_json": json.dumps([] if group == "A_continuous" else [1]),
            }
        )

    decision = probe.assess_probe(rows, 1000)

    assert decision["status"] == "HALT_WIRING"
    assert any("charging replay changed routes" in reason for reason in decision["failures"])
