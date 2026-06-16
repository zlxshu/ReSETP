import csv
import json
from pathlib import Path

from dr_alns_ppo.baselines import RESULT_COLUMNS
from dr_alns_ppo.report_smoke import build_summary, load_comparison, write_summary


def test_smoke_summary_gates_and_counts(tmp_path: Path) -> None:
    rows = [
        _row("ppo_full", "bundle_a", 1, 10.0, {"random_customer_removal": 2}, {"regret2_insert_repair": 2}),
        _row("random_full", "bundle_a", 1, 12.0, {"random_customer_removal": 1}, {"greedy_insert_repair": 1}),
        _row("alpha_ucb_env", "bundle_a", 1, 9.0, {"whole_route_removal": [0, 0, 0, 1]}, {"regret2_insert_repair": [0, 1, 0, 1]}),
    ]
    summary = build_summary(rows)

    assert summary["gate_vs_random"] == "PASS_RANDOM"
    assert summary["gate_vs_alpha_ucb_env"] == "FUTURE_WORK"
    assert summary["operator_base_id_ok"] is True
    assert summary["zero_violation"] is True
    assert summary["destroy_operator_usage"]["random_customer_removal"] == 3
    assert summary["destroy_operator_usage"]["whole_route_removal"] == 1
    assert summary["repair_operator_usage"]["regret2_insert_repair"] == 4

    write_summary(summary, tmp_path)
    assert (tmp_path / "smoke_100k_summary.json").is_file()
    assert "Gate versus random: `PASS_RANDOM`." in (tmp_path / "smoke_100k_summary.md").read_text(encoding="utf-8")


def test_smoke_summary_blocks_gates_on_budget_mismatch() -> None:
    rows = [
        _row("ppo_full", "bundle_a", 1, 10.0, {"random_customer_removal": 2}, {"regret2_insert_repair": 2}),
        _row("random_full", "bundle_a", 1, 12.0, {"random_customer_removal": 1}, {"greedy_insert_repair": 1}),
        _row("alpha_ucb_env", "bundle_a", 1, 15.0, {}, {}),
    ]
    rows[0]["actual_evals"] = 4
    rows[1]["actual_evals"] = 5
    rows[2]["actual_evals"] = 6

    summary = build_summary(rows)

    assert summary["gate_vs_random"] == "HALT_RANDOM"
    assert summary["gate_vs_alpha_ucb_env"] == "FUTURE_WORK"
    assert summary["budget_matched"] is False
    assert len(summary["under_budget_runs"]) == 1
    assert len(summary["over_budget_runs"]) == 1


def test_load_comparison_parses_json_count_columns(tmp_path: Path) -> None:
    path = tmp_path / "comparison.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerow(
            {
                **_row("ppo_full", "bundle_a", 1, 10.0, {"random_customer_removal": 2}, {"regret2_insert_repair": 2}),
                "operator_counts": "{}",
                "destroy_counts": json.dumps({"random_customer_removal": 2}),
                "repair_counts": json.dumps({"regret2_insert_repair": 2}),
                "q_ratio_counts": json.dumps({"0.200000": 2}),
                "feasible": "1",
            }
        )

    rows = load_comparison(path)

    assert rows[0]["destroy_counts"] == {"random_customer_removal": 2}
    assert rows[0]["q_ratio_counts"] == {"0.200000": 2}


def _row(algorithm: str, bundle: str, seed: int, best_obj: float, destroy: dict, repair: dict) -> dict:
    return {
        "algorithm": algorithm,
        "bundle": bundle,
        "seed": seed,
        "eval_budget": 5,
        "best_obj": best_obj,
        "actual_evals": 5,
        "candidate_scores": 5,
        "repair_delta_count": 7,
        "operator_base_id": "winner_kernel_v1",
        "control_mode": "ppo_full" if algorithm == "ppo_full" else "kernel_default",
        "violation_count": 0,
        "feasible": True,
        "solution_signature_hash": "hash",
        "operator_counts": {},
        "destroy_counts": destroy,
        "repair_counts": repair,
        "q_ratio_counts": {"0.200000": 1},
    }
