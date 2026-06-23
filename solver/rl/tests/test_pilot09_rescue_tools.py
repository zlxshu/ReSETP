from __future__ import annotations

from pathlib import Path

import numpy as np

from dr_alns_ppo import pilot09_rescue_tools as tools
from dr_alns_ppo.async_block_policy import make_block_actor_critic


def test_literature_merge_keeps_zotero_repo_and_web_evidence() -> None:
    zotero_status = {"status": "PASS"}
    zotero_searches = {
        "Daysalilar": [
            {
                "key": "GKWV7NHV",
                "title": "A curriculum-based deep reinforcement learning framework for the electric vehicle routing problem",
                "creators": ["A"],
                "year": "2026",
            }
        ]
    }
    web_entries = [{"source_type": "web", "title": "web ref", "finding": "f", "pilot09_implication": "i"}]
    repo_entries = [{"source_type": "repo", "title": "repo ref", "finding": "f", "pilot09_implication": "i"}]

    entries = tools.merge_literature_entries(zotero_status, zotero_searches, web_entries, repo_entries)

    assert {entry["source_type"] for entry in entries} == {"zotero", "repo", "web"}
    assert next(entry for entry in entries if entry["source_type"] == "zotero")["zotero_item_key"] == "GKWV7NHV"


def test_literature_merge_marks_zotero_unavailable() -> None:
    entries = tools.merge_literature_entries(
        {"status": "ZOTERO_UNAVAILABLE", "reason": "not running"},
        {},
        [],
        [],
    )

    assert entries[0]["source_type"] == "zotero_status"
    assert entries[0]["title"] == "ZOTERO_UNAVAILABLE"


def test_repo_baseline_catalog_entries_carry_known_item_keys() -> None:
    entries = tools.repo_baseline_catalog_entries(Path("docs/handoff/memory/baseline-algorithm-catalog.md"), "Daysalilar2026课程PPO-EVRPTW Wan2025 DRL-FSM Narayanan2022 RL-EVRP-V2G")
    keys = {entry["zotero_item_key"] for entry in entries}

    assert {"GKWV7NHV", "6VNYWJ7Q", "BCBMVPMB"} <= keys


def test_meta_action_tuple_uses_alpha_ucb_heads_and_nearest_ratios() -> None:
    action = tools.meta_action_tuple(q_ratio=0.16, threshold_ratio=0.0, exploration_ratio=0.0)

    assert action[0] == tools.BLOCK_DESTROY_IDS.index(tools.ALPHA_UCB_CHOICE)
    assert action[1] == tools.BLOCK_REPAIR_IDS.index(tools.ALPHA_UCB_CHOICE)
    assert tools.BLOCK_Q_RATIOS[action[2]] == min(tools.BLOCK_Q_RATIOS, key=lambda value: abs(float(value) - 0.16))
    assert tools.BLOCK_THRESHOLD_RATIOS[action[3]] == min(tools.BLOCK_THRESHOLD_RATIOS, key=lambda value: abs(float(value) - 0.0))
    assert tools.BLOCK_EXPLORATION_RATIOS[action[4]] == min(tools.BLOCK_EXPLORATION_RATIOS, key=lambda value: abs(float(value) - 0.0))


def test_limited_meta_configs_always_include_default() -> None:
    configs = tools.limited_meta_configs(3)

    assert len(configs) == 3
    assert tools.default_meta_config() in configs


def test_stochastic_action_sampling_is_seed_reproducible() -> None:
    model = make_block_actor_critic(seed=7, hidden_size=16)
    obs = np.zeros(model.obs_dim, dtype=np.float32)
    mask = [[True] * n for n in model.action_nvec]

    first, _ = tools.sample_block_action(model, obs, mask, seed=123, deterministic=False)
    second, _ = tools.sample_block_action(model, obs, mask, seed=123, deterministic=False)

    assert first.tolist() == second.tolist()


def test_normalize_rescue_row_preserves_runtime_and_budget_fields() -> None:
    row = {
        "algorithm": "ppo_block_stochastic",
        "bundle": tools.TRAIN_BUNDLE,
        "seed": 1,
        "eval_budget": 600,
        "best_obj": 100.0,
        "actual_evals": 600,
        "candidate_scores": 600,
        "repair_delta_count": 0,
        "operator_base_id": "winner_kernel_v1",
        "control_mode": "test",
        "violation_count": 0,
        "feasible": True,
        "solution_signature_hash": "sig",
        "operator_counts": {},
        "destroy_counts": {},
        "repair_counts": {},
        "q_ratio_counts": {},
        "worker_python_executable": tools.DEFAULT_WORKER,
        "worker_python_version": "3.13",
        "worker_numpy_version": tools.REQUIRED_NUMPY,
        "elapsed_seconds": 12.5,
        "runtime_target_seconds": 0.0,
        "model_label": "best_stochastic",
        "checkpoint_update": 240,
        "eval_mode": "budget",
        "bundle_role": "train",
    }

    normalized = tools.normalize_rescue_row(row)

    assert normalized["eval_budget"] == 600
    assert normalized["actual_evals"] == 600
    assert normalized["elapsed_seconds"] == 12.5
    assert normalized["model_label"] == "best_stochastic"


def test_build_trace_row_tolerates_missing_trace_fields() -> None:
    obs = np.zeros(19, dtype=np.float32)
    action = np.array([0, 1, 2, 3, 0], dtype=np.int64)
    row = tools.build_trace_row(
        algorithm="ppo_block_stochastic",
        bundle=tools.HELD_OUT_BUNDLE,
        seed=1,
        step_index=1,
        obs=obs,
        action=action,
        decision={},
        reward=0.0,
        info={"best_obj": 10.0, "current_obj": 11.0},
    )

    assert row["block_best_delta"] == 0.0
    assert row["worker_python_executable"] == ""
    assert row["top_destroy"] == ""


def test_stochastic_gate_requires_five_pairs_before_verdict() -> None:
    rows = []
    for seed in (1, 2, 3):
        rows.append(_row("ppo_block_stochastic", tools.TRAIN_BUNDLE, seed, 90.0))
        rows.append(_row("alpha_ucb_block_meta", tools.TRAIN_BUNDLE, seed, 100.0))
        rows.append(_row("ppo_block_stochastic", tools.HELD_OUT_BUNDLE, seed, 90.0))
        rows.append(_row("alpha_ucb_block_meta", tools.HELD_OUT_BUNDLE, seed, 100.0))

    gate = tools.classify_stochastic_gate(rows)

    assert gate["status"] == "INCONCLUSIVE_STOCHASTIC"


def test_stochastic_gate_promising_requires_train_and_held_four_of_five() -> None:
    rows = []
    for seed in range(1, 6):
        ppo_train = 90.0 if seed <= 4 else 101.0
        ppo_held = 90.0 if seed <= 4 else 101.0
        rows.append(_row("ppo_block_stochastic", tools.TRAIN_BUNDLE, seed, ppo_train))
        rows.append(_row("alpha_ucb_block_meta", tools.TRAIN_BUNDLE, seed, 100.0))
        rows.append(_row("ppo_block_stochastic", tools.HELD_OUT_BUNDLE, seed, ppo_held))
        rows.append(_row("alpha_ucb_block_meta", tools.HELD_OUT_BUNDLE, seed, 100.0))

    gate = tools.classify_stochastic_gate(rows)

    assert gate["status"] == "PROMISING_STOCHASTIC"


def test_meta_gate_is_screen_not_training_permission() -> None:
    ranking = [
        {
            "model_label": tools.meta_label(0.24, 0.02, 0.1),
            "train_best_obj": 90.0,
            "held_out_best_obj": 90.0,
        },
        {
            "model_label": tools.meta_label(0.16, 0.0, 0.0),
            "train_best_obj": 100.0,
            "held_out_best_obj": 100.0,
        },
    ]

    gate = tools.classify_meta_gate(ranking)

    assert gate["status"] == "PROMISING_META_SCREEN"
    assert tools.recommendation_from_gates({"status": "WEAK_STOCHASTIC"}, gate) == "REFINE_ALPHA_UCB_META_NEXT"


def test_rank_meta_configs_prefers_lower_train_and_held_mean() -> None:
    rows = [
        _meta_row("a", tools.TRAIN_BUNDLE, 100.0),
        _meta_row("a", tools.HELD_OUT_BUNDLE, 100.0),
        _meta_row("b", tools.TRAIN_BUNDLE, 90.0),
        _meta_row("b", tools.HELD_OUT_BUNDLE, 95.0),
    ]

    ranking = tools.rank_meta_configs(rows)

    assert ranking[0]["model_label"] == "b"


def _row(algorithm: str, bundle: str, seed: int, best_obj: float) -> dict:
    return {
        "algorithm": algorithm,
        "bundle": bundle,
        "seed": seed,
        "best_obj": best_obj,
    }


def _meta_row(label: str, bundle: str, best_obj: float) -> dict:
    return {
        "model_label": label,
        "bundle": bundle,
        "best_obj": best_obj,
        "meta_q_ratio": 0.16,
        "meta_threshold_ratio": 0.0,
        "meta_exploration_ratio": 0.0,
    }
