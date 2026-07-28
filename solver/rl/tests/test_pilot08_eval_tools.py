from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from dr_alns_ppo import pilot08_eval_tools as tools


def test_build_eval_manifest_uses_100c_train_not_curriculum() -> None:
    manifest = tools.build_eval_manifest()

    assert manifest["train"] == [tools.TRAIN_BUNDLE]
    assert manifest["held_out"] == [tools.HELD_OUT_BUNDLE]
    assert manifest["formal_eval"] == [tools.FORMAL_BUNDLE]
    assert not any("E-UK25" in bundle or "E-UK50" in bundle for bundle in manifest["train"])


def test_extended_rows_preserve_runtime_fields(tmp_path: Path) -> None:
    row = _row("ppo_block_best", tools.TRAIN_BUNDLE, 1)
    row["elapsed_seconds"] = 901.5
    row["runtime_target_seconds"] = 900.0
    row["model_label"] = "best"
    row["checkpoint_update"] = 350
    row["eval_mode"] = "budget"
    row["bundle_role"] = "train"
    path = tmp_path / "rows.csv"

    tools._write_extended_rows(path, [row])
    loaded = tools._load_existing_extended(path)

    assert loaded[0]["elapsed_seconds"] == pytest.approx(901.5)
    assert loaded[0]["runtime_target_seconds"] == pytest.approx(900.0)
    assert loaded[0]["model_label"] == "best"
    assert loaded[0]["checkpoint_update"] == 350


def test_row_gate_distinguishes_budget_and_timed_modes() -> None:
    budget_row = _row("alpha_ucb_block", tools.TRAIN_BUNDLE, 1, actual_evals=899, eval_budget=900)
    budget_row.update({"eval_mode": "budget", "elapsed_seconds": 1.0})

    timed_row = _row("official_winner_kernel", tools.TRAIN_BUNDLE, 1, actual_evals=2500, eval_budget=tools.TIMED_EVAL_CAP)
    timed_row.update({"eval_mode": "timed", "elapsed_seconds": 905.0, "runtime_target_seconds": 900.0})

    fast_timed = dict(timed_row)
    fast_timed["elapsed_seconds"] = 120.0

    assert "actual_evals" in tools.row_gate_issues(budget_row, expected_budget=900)
    assert tools.row_gate_issues(timed_row, expected_budget=None) == []
    assert "timed_runtime" in tools.row_gate_issues(fast_timed, expected_budget=None)


def test_one_sided_wilcoxon_all_five_wins_can_be_significant() -> None:
    rows = []
    for seed in range(1, 6):
        rows.append(_row("ppo_block_best", tools.HELD_OUT_BUNDLE, seed, best_obj=90.0 + seed))
        rows.append(_row("alpha_ucb_block", tools.HELD_OUT_BUNDLE, seed, best_obj=100.0 + seed))

    stats = tools.wilcoxon_rows_for_paired(rows, left_algorithm="ppo_block_best")
    alpha = next(row for row in stats if row["baseline_algorithm"] == "alpha_ucb_block")

    assert alpha["paired_n"] == 5
    assert alpha["wins"] == 5
    assert float(alpha["p_value"]) <= 0.05


def test_secondary_three_seed_comparisons_are_descriptive() -> None:
    rows = []
    for seed in range(1, 4):
        rows.append(_row("ppo_block_best", tools.TRAIN_BUNDLE, seed, best_obj=90.0))
        rows.append(_row("random_block", tools.TRAIN_BUNDLE, seed, best_obj=100.0))

    stats = tools.wilcoxon_rows_for_paired(rows, left_algorithm="ppo_block_best")
    random = next(row for row in stats if row["baseline_algorithm"] == "random_block")

    assert random["paired_n"] == 3
    assert random["p_value"] == ""
    assert random["used_for_gate"] is False


def test_verdict_thresholds_strong_and_weak() -> None:
    paired = [
        _paired(tools.TRAIN_BUNDLE, "alpha_ucb_block", mean=1.0, wins=4, n=5),
        _paired(tools.HELD_OUT_BUNDLE, "alpha_ucb_block", mean=2.0, wins=5, n=5),
        _paired(tools.TRAIN_BUNDLE, "random_block", mean=10.0, wins=3, n=3),
        _paired(tools.HELD_OUT_BUNDLE, "random_block", mean=11.0, wins=3, n=3),
    ]
    wilcoxon = [
        _wilcox(tools.TRAIN_BUNDLE, "alpha_ucb_block", wins=4, p=0.0625),
        _wilcox(tools.HELD_OUT_BUNDLE, "alpha_ucb_block", wins=5, p=0.03125),
    ]

    assert tools.classify_verdict(paired, wilcoxon)["verdict"] == "STRONG"

    paired[1]["mean_relative_pct"] = -0.1
    assert tools.classify_verdict(paired, wilcoxon)["verdict"] == "WEAK"


def test_rank_models_prefers_final_on_exact_tie() -> None:
    rows = [
        _row("ppo_block", tools.HELD_OUT_BUNDLE, 1, best_obj=100.0, model_label="checkpoint_0350", checkpoint_update=350),
        _row("ppo_block_final", tools.HELD_OUT_BUNDLE, 1, best_obj=100.0, model_label="final", checkpoint_update=350),
    ]

    ranked = tools.rank_models(rows, final_update=350)

    assert ranked[0]["model_label"] == "final"
    assert ranked[0]["rank"] == 1


def _row(
    algorithm: str,
    bundle: str,
    seed: int,
    *,
    best_obj: float = 100.0,
    eval_budget: int = 900,
    actual_evals: int = 900,
    model_label: str = "",
    checkpoint_update: int = -1,
) -> dict:
    return {
        "algorithm": algorithm,
        "bundle": bundle,
        "seed": seed,
        "eval_budget": eval_budget,
        "best_obj": best_obj,
        "actual_evals": actual_evals,
        "candidate_scores": actual_evals,
        "repair_delta_count": 0,
        "operator_base_id": "winner_kernel_v1",
        "control_mode": "test",
        "violation_count": 0,
        "feasible": True,
        "solution_signature_hash": f"sig-{algorithm}-{seed}",
        "operator_counts": {},
        "destroy_counts": {},
        "repair_counts": {},
        "q_ratio_counts": {},
        "worker_python_executable": tools.DEFAULT_WORKER,
        "worker_python_version": "3.13",
        "worker_numpy_version": tools.REQUIRED_NUMPY,
        "elapsed_seconds": 1.0,
        "runtime_target_seconds": 0.0,
        "model_label": model_label,
        "checkpoint_update": checkpoint_update,
        "eval_mode": "budget",
        "bundle_role": "train",
    }


def _paired(bundle: str, baseline: str, *, mean: float, wins: int, n: int) -> dict:
    return {
        "bundle": bundle,
        "left_algorithm": "ppo_block_best",
        "baseline_algorithm": baseline,
        "paired_n": n,
        "wins": wins,
        "mean_relative_pct": mean,
        "std_relative_pct": 0.0,
        "min_relative_pct": mean,
        "max_relative_pct": mean,
    }


def _wilcox(bundle: str, baseline: str, *, wins: int, p: float) -> dict:
    return {
        "bundle": bundle,
        "left_algorithm": "ppo_block_best",
        "baseline_algorithm": baseline,
        "paired_n": 5,
        "wins": wins,
        "statistic": 15.0,
        "p_value": p,
        "alternative": "greater",
        "used_for_gate": True,
    }
