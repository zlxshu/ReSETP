from __future__ import annotations

from dr_alns_ppo.baselines import run_alpha_ucb_env_policy, run_official_winner_kernel


FIXTURE_DIR = "models/data_bundle/generated_instances/verify_20251113"


def test_alpha_ucb_env_uses_winner_kernel_trace_and_budget() -> None:
    row = run_alpha_ucb_env_policy(FIXTURE_DIR, seed=1, eval_budget=5)

    assert row["algorithm"] == "alpha_ucb_env"
    assert row["actual_evals"] == 5
    assert row["candidate_scores"] == 5
    assert row["operator_base_id"] == "winner_kernel_v1"
    assert row["control_mode"] == "kernel_default"
    assert row["worker_python_executable"]
    assert row["worker_numpy_version"]
    assert row["feasible"] is True
    assert set(row["destroy_counts"]).issubset(
        {
            "random_customer_removal",
            "worst_customer_removal",
            "shaw_related_removal",
            "whole_route_removal",
            "route_segment_removal",
            "vehicle_type_swap",
        }
    )


def test_official_winner_kernel_anchor_returns_same_audit_base() -> None:
    row = run_official_winner_kernel(FIXTURE_DIR, seed=1, eval_budget=5, max_runtime_seconds=60.0)

    assert row["algorithm"] == "official_winner_kernel"
    assert row["actual_evals"] == 5
    assert row["candidate_scores"] == 5
    assert row["operator_base_id"] == "winner_kernel_v1"
    assert row["control_mode"] == "official_kernel"
    assert row["worker_python_executable"]
    assert row["worker_numpy_version"]
    assert row["feasible"] is True
