from __future__ import annotations

import math

from dr_alns_ppo import pilot18_headroom_probe as tools


def test_select_representative_bundles_prefers_scale_03() -> None:
    bundles = [
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-50c-01",
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-50c-03",
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-75c-01",
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-75c-03",
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-100c-01",
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-100c-03",
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-150c-01",
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-150c-03",
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-200c-01",
        "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-200c-03",
    ]

    selected = tools.select_representative_bundles(bundles)

    assert [item.rsplit("-", 1)[-1] for item in selected] == ["03", "03", "03", "03", "03"]
    assert [tools.p17.scale_from_bundle(item) for item in selected] == [50, 75, 100, 150, 200]


def test_budget_expansion_and_cli_accept_explicit_budgets() -> None:
    assert tools.budget_values(20) == [20, 80, 320]

    args = tools.parse_args(["--budgets", "20,80,320"])

    assert args.budget_multipliers == (1, 4, 16)


def test_headroom_formula_uses_best_extended_objective() -> None:
    assert tools.headroom_pct(100.0, 96.0) == 4.0
    assert tools.headroom_pct(100.0, 101.0) == -1.0
    assert math.isnan(tools.headroom_pct(0.0, 1.0))


def test_wall_clock_capped_rows_are_recorded_not_failed() -> None:
    row = _run_row("winner_static_meta", eval_budget=20, actual_evals=12, wall_clock_capped=1)

    integrity = tools.integrity_summary([row])

    assert integrity["ok"] is True
    assert integrity["wall_clock_capped_count"] == 1


def test_row_gate_rejects_wrong_worker_and_numpy() -> None:
    row = _run_row("winner_static_meta")
    row["worker_python_executable"] = "C:/bad/python.exe"
    row["worker_numpy_version"] = "1.26.0"

    issues = tools.row_gate_issues(row, expected_budget=20)

    assert "worker_python" in issues
    assert "worker_numpy" in issues


def test_scale_verdict_thresholds_and_priority() -> None:
    assert tools.classify_scale_verdict(
        mean_headroom_pct=10.01,
        mean_late_gain_after_dr_stop_pct=0.0,
        mean_dr_eval_fraction=1.0,
    ) == "VERDICT_ROOM_EXISTS"

    assert tools.classify_scale_verdict(
        mean_headroom_pct=2.0,
        mean_late_gain_after_dr_stop_pct=0.5,
        mean_dr_eval_fraction=0.60,
    ) == "VERDICT_DR_INTERFACE_GAP"

    assert tools.classify_scale_verdict(
        mean_headroom_pct=2.999,
        mean_late_gain_after_dr_stop_pct=0.0,
        mean_dr_eval_fraction=1.0,
    ) == "VERDICT_NO_HEADROOM"

    assert tools.classify_scale_verdict(
        mean_headroom_pct=5.0,
        mean_late_gain_after_dr_stop_pct=0.0,
        mean_dr_eval_fraction=1.0,
    ) == "VERDICT_MODEST_ROOM"


def test_overall_verdict_priority() -> None:
    assert tools.classify_overall_verdict([
        {"verdict": "VERDICT_NO_HEADROOM"},
        {"verdict": "VERDICT_DR_INTERFACE_GAP"},
    ]) == "VERDICT_DR_INTERFACE_GAP"
    assert tools.classify_overall_verdict([
        {"verdict": "VERDICT_DR_INTERFACE_GAP"},
        {"verdict": "VERDICT_ROOM_EXISTS"},
    ]) == "VERDICT_ROOM_EXISTS"
    assert tools.classify_overall_verdict([
        {"verdict": "VERDICT_NO_HEADROOM"},
        {"verdict": "VERDICT_NO_HEADROOM"},
    ]) == "VERDICT_NO_HEADROOM"


def test_late_gain_after_dr_stop_uses_static_meta_trajectory() -> None:
    trajectory = [
        _trajectory(actual_evals=8, best_obj=100.0),
        _trajectory(actual_evals=12, best_obj=99.8),
        _trajectory(actual_evals=20, best_obj=99.0),
    ]

    gain = tools.late_gain_after_dr_stop(
        trajectory,
        bundle=trajectory[0]["bundle"],
        seed=1,
        dr_actual_evals=8,
        final_obj=99.0,
    )

    assert gain == 1.0


def test_build_headroom_rows_selects_best_baseline_per_budget() -> None:
    rows = [
        _run_row("winner_static_meta", eval_budget=20, best_obj=100.0),
        _run_row("scikit-opt-SA", eval_budget=20, best_obj=101.0),
        _run_row("winner_static_meta", eval_budget=80, best_obj=98.0),
        _run_row("scikit-opt-SA", eval_budget=80, best_obj=99.0),
        _run_row("winner_static_meta", eval_budget=320, best_obj=97.0),
        _run_row("scikit-opt-SA", eval_budget=320, best_obj=96.0),
    ]

    headroom = tools.build_headroom_rows(rows, base_budget=20)

    assert len(headroom) == 1
    assert headroom[0]["algorithm_at_B"] == "winner_static_meta"
    assert headroom[0]["algorithm_at_16B"] == "scikit-opt-SA"
    assert headroom[0]["headroom_pct"] == 4.0


def test_build_scale_summary_classifies_dr_interface_gap() -> None:
    bundle = "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-100c-03"
    headroom_rows = [
        {
            "scale": 100,
            "bundle": bundle,
            "seed": 1,
            "obj_B": 99.0,
            "headroom_pct": 2.0,
            "wall_clock_capped_B": 0,
            "wall_clock_capped_4B": 0,
            "wall_clock_capped_16B": 0,
        }
    ]
    pilot17_rows = [{"algorithm": "ppo_block_best", "bundle": bundle, "seed": 1, "actual_evals": 8}]
    trajectory = [
        _trajectory(bundle=bundle, actual_evals=8, best_obj=100.0),
        _trajectory(bundle=bundle, actual_evals=20, best_obj=99.0),
    ]

    summary = tools.build_scale_summary(headroom_rows, trajectory, pilot17_rows, base_budget=20)

    assert summary[0]["verdict"] == "VERDICT_DR_INTERFACE_GAP"
    assert summary[0]["dr_early_stop_seed_count"] == 1


def _run_row(
    algorithm: str,
    *,
    bundle: str = "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-100c-03",
    seed: int = 1,
    eval_budget: int = 20,
    actual_evals: int | None = None,
    best_obj: float = 100.0,
    wall_clock_capped: int = 0,
) -> dict:
    actual = eval_budget if actual_evals is None else actual_evals
    return {
        "algorithm": algorithm,
        "bundle": bundle,
        "bundle_id": "e2-threeshift-100c-03",
        "scale": 100,
        "seed": seed,
        "budget_multiplier": eval_budget // 20,
        "eval_budget": eval_budget,
        "best_obj": best_obj,
        "actual_evals": actual,
        "candidate_scores": actual,
        "repair_delta_count": 0,
        "violation_count": 0,
        "feasible": True,
        "wall_clock_capped": wall_clock_capped,
        "budget_reached": int(actual >= eval_budget),
        "elapsed_seconds": 1.0,
        "runtime_target_seconds": 1200.0,
        "worker_python_executable": tools.DEFAULT_WORKER,
        "worker_python_version": "3.13",
        "worker_numpy_version": tools.REQUIRED_NUMPY,
        "solution_signature_hash": f"{algorithm}-{seed}-{eval_budget}",
        "operator_base_id": "winner_kernel_v1",
        "control_mode": "test",
        "operator_counts": {},
        "destroy_counts": {},
        "repair_counts": {},
        "q_ratio_counts": {},
        "meta_q_ratio": "",
        "meta_threshold_ratio": "",
        "meta_exploration_ratio": "",
    }


def _trajectory(
    *,
    bundle: str = "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-100c-03",
    actual_evals: int,
    best_obj: float,
) -> dict:
    return {
        "algorithm": "winner_static_meta",
        "bundle": bundle,
        "bundle_id": "e2-threeshift-100c-03",
        "scale": 100,
        "seed": 1,
        "budget_multiplier": 1,
        "eval_budget": 20,
        "step_index": actual_evals // 4,
        "actual_evals": actual_evals,
        "best_obj": best_obj,
    }
