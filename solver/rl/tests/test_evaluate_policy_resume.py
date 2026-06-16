import csv
import json

from dr_alns_ppo.evaluate_policy import _selected_bundles, filter_tasks_for_resume, load_existing_rows


def test_selected_bundles_supports_train_split():
    manifest = {
        "train": ["train-a", "train-b"],
        "held_out": ["held-a"],
        "formal_eval": ["formal-a"],
    }

    assert _selected_bundles(manifest, "train") == ["train-a", "train-b"]


def test_filter_tasks_for_resume_keeps_completed_rows():
    tasks = [
        ("ppo_full", "bundle-a", 1),
        ("random_full", "bundle-a", 1),
        ("alpha_ucb_env", "bundle-a", 1),
    ]
    rows = [
        {
            "algorithm": "ppo_full",
            "bundle": "bundle-a",
            "seed": 1,
            "eval_budget": 16000,
            "best_obj": 1.0,
            "actual_evals": 16000,
            "candidate_scores": 16000,
            "repair_delta_count": 0,
            "operator_base_id": "winner_kernel_v1",
            "control_mode": "ppo_full",
            "violation_count": 0,
            "feasible": True,
            "solution_signature_hash": "abc",
            "operator_counts": {},
            "destroy_counts": {},
            "repair_counts": {},
            "q_ratio_counts": {},
        },
        {
            "algorithm": "random_full",
            "bundle": "bundle-a",
            "seed": 1,
            "eval_budget": 16000,
            "best_obj": 2.0,
            "actual_evals": 15999,
            "candidate_scores": 15999,
            "repair_delta_count": 0,
            "operator_base_id": "winner_kernel_v1",
            "control_mode": "ppo_full",
            "violation_count": 0,
            "feasible": True,
            "solution_signature_hash": "def",
            "operator_counts": {},
            "destroy_counts": {},
            "repair_counts": {},
            "q_ratio_counts": {},
        },
    ]

    assert filter_tasks_for_resume(tasks, rows, eval_budget=16000, rerun_underbudget=False) == [
        ("alpha_ucb_env", "bundle-a", 1)
    ]
    assert filter_tasks_for_resume(tasks, rows, eval_budget=16000, rerun_underbudget=True) == [
        ("random_full", "bundle-a", 1),
        ("alpha_ucb_env", "bundle-a", 1),
    ]


def test_load_existing_rows_parses_json_columns(tmp_path):
    path = tmp_path / "comparison.partial.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "algorithm",
                "bundle",
                "seed",
                "eval_budget",
                "best_obj",
                "actual_evals",
                "candidate_scores",
                "repair_delta_count",
                "operator_base_id",
                "control_mode",
                "violation_count",
                "feasible",
                "solution_signature_hash",
                "operator_counts",
                "destroy_counts",
                "repair_counts",
                "q_ratio_counts",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "algorithm": "ppo_full",
                "bundle": "bundle-a",
                "seed": "1",
                "eval_budget": "16000",
                "best_obj": "1.5",
                "actual_evals": "16000",
                "candidate_scores": "16000",
                "repair_delta_count": "4",
                "operator_base_id": "winner_kernel_v1",
                "control_mode": "ppo_full",
                "violation_count": "0",
                "feasible": "1",
                "solution_signature_hash": "abc",
                "operator_counts": json.dumps({}),
                "destroy_counts": json.dumps({"D3": 2}),
                "repair_counts": json.dumps({"R1": 2}),
                "q_ratio_counts": json.dumps({"0.200000": 2}),
            }
        )

    rows = load_existing_rows(path)

    assert rows[0]["seed"] == 1
    assert rows[0]["actual_evals"] == 16000
    assert rows[0]["feasible"] is True
    assert rows[0]["destroy_counts"] == {"D3": 2}
