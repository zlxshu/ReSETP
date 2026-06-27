from __future__ import annotations

from dr_alns_ppo import pilot17_allscale_eval_tools as tools
from dr_alns_ppo.action_space import block_action_nvecs
from dr_alns_ppo.async_block_policy import make_block_actor_critic


def test_infer_block_modes_from_action_nvec() -> None:
    model = make_block_actor_critic(
        action_nvec=block_action_nvecs(candidate_generator_mode=True, search_control_mode=True)
    )

    assert tools.infer_block_modes(model) == (True, True)


def test_selection_bundles_prefers_third_bundle_per_scale() -> None:
    bundles = [
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-50c-01",
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-50c-03",
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-100c-02",
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-100c-03",
    ]

    assert tools.selection_bundles(bundles) == [
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-50c-03",
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-100c-03",
    ]


def test_row_gate_allows_ppo_underbudget_but_not_baseline_underbudget() -> None:
    row = _row("ppo_block_best", actual_evals=8)

    assert tools.row_gate_issues(row, expected_budget=20, require_full_budget=False) == []
    assert "actual_evals" in tools.row_gate_issues(row, expected_budget=20, require_full_budget=True)


def test_paired_relative_positive_means_dr_better() -> None:
    rows = [
        _row("ppo_block_best", best_obj=90.0, seed=1),
        _row("alpha_ucb_meta_tuned", best_obj=100.0, seed=1),
    ]

    paired = tools.paired_relative_rows(rows, left_algorithm="ppo_block_best")

    assert paired[0]["mean_relative_pct"] == 10.0
    assert paired[0]["wins"] == 1


def test_scale_summary_groups_bundle_relative_values() -> None:
    rows = [
        _row("ppo_block_best", bundle="e2-threeshift-50c-01", best_obj=90.0, seed=1),
        _row("alpha_ucb_meta_tuned", bundle="e2-threeshift-50c-01", best_obj=100.0, seed=1),
        _row("ppo_block_best", bundle="e2-threeshift-50c-02", best_obj=95.0, seed=1),
        _row("alpha_ucb_meta_tuned", bundle="e2-threeshift-50c-02", best_obj=100.0, seed=1),
    ]

    summary = tools.scale_summary(rows, left_algorithm="ppo_block_best")

    assert summary[0]["scale"] == 50
    assert summary[0]["mean_relative_pct"] == 7.5


def test_verdict_target_pass_requires_each_scale_nonnegative() -> None:
    scale_rows = [
        _scale(50, "alpha_ucb_meta_tuned", 12.0, wins=5, n=5),
        _scale(75, "alpha_ucb_meta_tuned", 11.0, wins=5, n=5),
        _scale(100, "alpha_ucb_meta_tuned", 10.0, wins=5, n=5),
        _scale(150, "alpha_ucb_meta_tuned", 9.0, wins=5, n=5),
        _scale(200, "alpha_ucb_meta_tuned", 8.0, wins=5, n=5),
    ]
    verdict = tools.classify_verdict(scale_rows=scale_rows, paired_rows=[], integrity={"ok": True, "ppo_underbudget_count": 0})

    assert verdict["verdict"] == "TARGET_PASS"

    scale_rows[-1]["mean_relative_pct"] = -0.1
    verdict = tools.classify_verdict(scale_rows=scale_rows, paired_rows=[], integrity={"ok": True, "ppo_underbudget_count": 0})
    assert verdict["verdict"] == "WEAK"


def test_build_eval_manifest_marks_all_bundles_as_formal_eval() -> None:
    bundles = ["e2-threeshift-50c-01", "e2-threeshift-75c-01"]

    manifest = tools.build_eval_manifest(bundles)

    assert manifest["train"] == []
    assert manifest["held_out"] == []
    assert manifest["formal_eval"] == bundles


def _row(
    algorithm: str,
    *,
    bundle: str = "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-100c-03",
    seed: int = 1,
    best_obj: float = 100.0,
    actual_evals: int = 20,
) -> dict:
    return {
        "algorithm": algorithm,
        "bundle": bundle,
        "seed": seed,
        "eval_budget": 20,
        "best_obj": best_obj,
        "actual_evals": actual_evals,
        "candidate_scores": actual_evals,
        "repair_delta_count": 0,
        "operator_base_id": "winner_kernel_v1",
        "control_mode": "test",
        "violation_count": 0,
        "feasible": True,
        "solution_signature_hash": f"{algorithm}-{seed}",
        "operator_counts": {},
        "destroy_counts": {},
        "repair_counts": {},
        "q_ratio_counts": {},
        "worker_python_executable": tools.DEFAULT_WORKER,
        "worker_python_version": "3.13",
        "worker_numpy_version": tools.REQUIRED_NUMPY,
        "elapsed_seconds": 1.0,
        "runtime_target_seconds": 0.0,
        "model_label": "",
        "checkpoint_update": -1,
        "eval_mode": "budget",
        "bundle_role": "formal",
        "scale": tools.scale_from_bundle(bundle),
        "selection_subset": "",
        "actual_eval_fraction": actual_evals / 20,
        "candidate_generator_mode": 1 if algorithm.startswith("ppo") else 0,
        "search_control_mode": 1 if algorithm.startswith("ppo") else 0,
        "candidate_nondefault_count": 0,
        "search_noncontinue_count": 0,
        "stop_requested_count": 0,
        "meta_q_ratio": "",
        "meta_threshold_ratio": "",
        "meta_exploration_ratio": "",
    }


def _scale(scale: int, baseline: str, mean: float, *, wins: int, n: int) -> dict:
    return {
        "scale": scale,
        "left_algorithm": "ppo_block_best",
        "baseline_algorithm": baseline,
        "bundle_count": 3,
        "paired_n": n,
        "wins": wins,
        "mean_relative_pct": mean,
        "min_bundle_relative_pct": mean,
        "max_bundle_relative_pct": mean,
    }
