from __future__ import annotations

import csv
from pathlib import Path

from dr_alns_ppo import pilot10_block_meta_tools as tools


def test_top3_configs_fallback_when_pilot09_files_missing(tmp_path: Path) -> None:
    configs = tools.load_top_static_meta_configs(tmp_path)

    assert [(c.q_ratio, c.threshold_ratio, c.exploration_ratio) for c in configs] == [
        (0.40, 0.0, 0.05),
        (0.40, 0.0025, 0.15),
        (0.16, 0.0, 0.05),
    ]


def test_top3_configs_prefer_ranking_csv(tmp_path: Path) -> None:
    path = tmp_path / "pilot09_meta_screen_ranking.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["rank", "model_label", "meta_q_ratio", "meta_threshold_ratio", "meta_exploration_ratio"],
        )
        writer.writeheader()
        writer.writerow({"rank": 2, "model_label": "b", "meta_q_ratio": 0.23, "meta_threshold_ratio": 0.0025, "meta_exploration_ratio": 0.15})
        writer.writerow({"rank": 1, "model_label": "a", "meta_q_ratio": 0.40, "meta_threshold_ratio": 0.0, "meta_exploration_ratio": 0.05})
        writer.writerow({"rank": 3, "model_label": "c", "meta_q_ratio": 0.16, "meta_threshold_ratio": 0.0, "meta_exploration_ratio": 0.05})
        writer.writerow({"rank": 4, "model_label": "d", "meta_q_ratio": 0.10, "meta_threshold_ratio": 0.0, "meta_exploration_ratio": 0.0})

    configs = tools.load_top_static_meta_configs(tmp_path)

    assert [config.label for config in configs] == ["a", "b", "c"]


def test_d1_gate_passes_only_with_held_out_headroom_and_wins() -> None:
    rows = []
    for seed in range(1, 6):
        rows.append(_row("static_default", tools.HELD_OUT_BUNDLE, seed, 100.0, "default"))
        rows.append(_row("static_candidate", tools.HELD_OUT_BUNDLE, seed, 97.0 if seed <= 3 else 100.0, "candidate"))
        rows.append(_row("static_default", tools.TRAIN_BUNDLE, seed, 100.0, "default"))
        rows.append(_row("static_candidate", tools.TRAIN_BUNDLE, seed, 97.0, "candidate"))

    result = tools.classify_d1_gate(rows, candidate_labels=["candidate"])

    assert result["status"] == "PASS_D1"
    assert result["best_static_meta"]["model_label"] == "candidate"
    assert result["best_static_meta"]["held_out_wins_vs_default"] == 3


def test_d1_gate_halts_budget_artifact_when_no_candidate_survives() -> None:
    rows = []
    for seed in range(1, 6):
        rows.append(_row("static_default", tools.HELD_OUT_BUNDLE, seed, 100.0, "default"))
        rows.append(_row("static_candidate", tools.HELD_OUT_BUNDLE, seed, 100.5, "candidate"))

    result = tools.classify_d1_gate(rows, candidate_labels=["candidate"])

    assert result["status"] == "HALT_META_BUDGET_ARTIFACT"


def test_paired_relative_positive_means_left_is_better() -> None:
    rows = [
        _row("block_meta_best", tools.TRAIN_BUNDLE, 1, 90.0, "learned"),
        _row("best_static_meta", tools.TRAIN_BUNDLE, 1, 100.0, "static"),
    ]

    paired = tools.paired_relative_rows(rows, left_algorithm="block_meta_best", baseline_algorithm="best_static_meta")

    assert paired[0]["mean_relative_pct"] == 10.0
    assert paired[0]["wins"] == 1


def test_wilcoxon_uses_one_sided_only_for_five_pairs() -> None:
    rows = []
    for seed in range(1, 6):
        rows.append(_row("block_meta_best", tools.HELD_OUT_BUNDLE, seed, 90.0, "learned"))
        rows.append(_row("best_static_meta", tools.HELD_OUT_BUNDLE, seed, 100.0, "static"))

    stats = tools.wilcoxon_rows(rows, left_algorithm="block_meta_best", baseline_algorithm="best_static_meta")

    assert stats[0]["paired_n"] == 5
    assert stats[0]["wins"] == 5
    assert float(stats[0]["p_value"]) <= 0.05


def test_rank_models_prefers_lower_mean_and_final_tie() -> None:
    rows = [
        _row("block_meta", tools.HELD_OUT_BUNDLE, 1, 100.0, "checkpoint_0010", checkpoint_update=10),
        _row("block_meta", tools.HELD_OUT_BUNDLE, 2, 100.0, "checkpoint_0010", checkpoint_update=10),
        _row("block_meta_final", tools.HELD_OUT_BUNDLE, 1, 100.0, "final", checkpoint_update=20),
        _row("block_meta_final", tools.HELD_OUT_BUNDLE, 2, 100.0, "final", checkpoint_update=20),
    ]

    ranked = tools.rank_models(rows)

    assert ranked[0]["model_label"] == "final"


def test_classify_final_verdict_routes_promising_and_retune() -> None:
    paired = [
        _paired(tools.TRAIN_BUNDLE, "best_static_meta", mean=1.0, wins=4, n=5),
        _paired(tools.HELD_OUT_BUNDLE, "best_static_meta", mean=2.0, wins=4, n=5),
    ]
    wilcoxon = [_wilcox(tools.HELD_OUT_BUNDLE, "best_static_meta", wins=4, p=0.0625)]

    assert tools.classify_final_verdict(paired, wilcoxon, d1_status="PASS_D1")["verdict"] == "PROMISING_RESCUE"

    paired[1]["wins"] = 2
    assert tools.classify_final_verdict(paired, wilcoxon, d1_status="PASS_D1")["verdict"] == "WEAK_RETUNE"


def _row(
    algorithm: str,
    bundle: str,
    seed: int,
    best_obj: float,
    model_label: str,
    *,
    checkpoint_update: int | str = "",
) -> dict:
    return {
        "algorithm": algorithm,
        "bundle": bundle,
        "seed": seed,
        "eval_budget": 13100,
        "best_obj": best_obj,
        "actual_evals": 13100,
        "candidate_scores": 13100,
        "repair_delta_count": 0,
        "operator_base_id": "winner_kernel_v1",
        "control_mode": "test",
        "violation_count": 0,
        "feasible": True,
        "solution_signature_hash": f"{algorithm}-{bundle}-{seed}",
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
        "meta_q_ratio": "",
        "meta_threshold_ratio": "",
        "meta_exploration_ratio": "",
    }


def _paired(bundle: str, baseline: str, *, mean: float, wins: int, n: int) -> dict:
    return {
        "bundle": bundle,
        "left_algorithm": "block_meta_best",
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
        "left_algorithm": "block_meta_best",
        "baseline_algorithm": baseline,
        "paired_n": 5,
        "wins": wins,
        "statistic": 10.0,
        "p_value": p,
        "alternative": "greater",
        "used_for_gate": True,
    }
