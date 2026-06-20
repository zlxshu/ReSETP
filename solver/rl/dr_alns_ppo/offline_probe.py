from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import statistics
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .action_space import BLOCK_ACTION_NVECS


REPORT_ROOT_FRAGMENT = "solver/reports/dr_alns_ppo_v3_block_dr_alns/offline_bandit"
DEFAULT_DATASET = f"{REPORT_ROOT_FRAGMENT}/dataset/block_trace_rows.csv"
DEFAULT_PARTIAL_DATASET = f"{REPORT_ROOT_FRAGMENT}/dataset/block_trace_rows.partial.csv"
DEFAULT_OUTPUT_DIR = f"{REPORT_ROOT_FRAGMENT}/probe"
OBSERVATION_SIZE = 19
OBS_COLS = tuple(f"obs_{idx:02d}" for idx in range(OBSERVATION_SIZE))
ACTION_COLS = (
    "action_destroy",
    "action_repair",
    "action_q",
    "action_threshold",
    "action_exploration",
)
REQUIRED_COLUMNS = (*OBS_COLS, "reward", *ACTION_COLS, "collection_policy", "episode_index")
MIN_GROUPS_FOR_CV = 5
MIN_FINITE_FOLDS = 6
MIN_OPE_EXACT_MATCHES = 5
GREEDY_CHUNK_ROWS = 32


class RewardModel(Protocol):
    def fit(self, obs: np.ndarray, actions: np.ndarray, rewards: np.ndarray) -> "RewardModel":
        ...

    def predict(self, obs: np.ndarray, actions: np.ndarray) -> np.ndarray:
        ...


@dataclass(frozen=True)
class ProbeConfig:
    seed: int = 20260620
    repeats: int = 5
    folds: int = 5
    bootstrap_samples: int = 2000
    model_kind: str = "auto"
    run_ope: bool = True


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "run":
        return run_cli(args)
    raise ValueError(f"unknown command: {args.command}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline supervised/OPE probe for block DR-ALNS traces.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--dataset", default=DEFAULT_DATASET)
    run.add_argument("--partial-dataset", default=DEFAULT_PARTIAL_DATASET)
    run.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    run.add_argument("--seed", type=int, default=20260620)
    run.add_argument("--repeats", type=int, default=5)
    run.add_argument("--folds", type=int, default=5)
    run.add_argument("--bootstrap-samples", type=int, default=2000)
    run.add_argument("--model-kind", choices=("auto", "gbr", "ridge"), default="auto")
    return parser.parse_args(argv)


def run_cli(args: argparse.Namespace) -> int:
    output_dir = _checked_output_dir(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = _select_dataset(Path(args.dataset), Path(args.partial_dataset))
    rows = _read_csv(dataset_path)
    audit = audit_rows(rows, dataset_path=dataset_path)
    _write_json(output_dir / "audit.json", audit)
    _write_text(output_dir / "audit.md", audit_markdown(audit))
    if audit["status"] != "PASS":
        return 2

    config = ProbeConfig(
        seed=int(args.seed),
        repeats=int(args.repeats),
        folds=int(args.folds),
        bootstrap_samples=int(args.bootstrap_samples),
        model_kind=str(args.model_kind),
    )
    report = analyze_rows(rows, config=config)
    report["dataset_path"] = str(dataset_path)
    report["code_commit"] = _git_commit()
    report["audit_summary"] = {
        "row_count": audit["row_count"],
        "policy_counts": audit["policy_counts"],
        "random_block_behavior_probability": audit["propensity"]["random_block_behavior_probability"],
    }
    _write_json(output_dir / "offline_probe_report.json", report)
    _write_text(output_dir / "offline_probe_report.md", probe_report_markdown(report))
    _write_text(output_dir / "curriculum_training_plan.md", curriculum_plan_markdown(report))
    return 0 if report["verdict"]["status"] in {"PROMISING", "WEAK"} else 2


def audit_rows(rows: list[dict[str, Any]], *, dataset_path: Path) -> dict[str, Any]:
    columns = list(rows[0].keys()) if rows else []
    missing = [col for col in REQUIRED_COLUMNS if col not in columns]
    policy_counts: dict[str, int] = {}
    for row in rows:
        policy = str(row.get("collection_policy", ""))
        policy_counts[policy] = policy_counts.get(policy, 0) + 1
    behavior_product = int(np.prod(np.asarray(BLOCK_ACTION_NVECS, dtype=np.int64)))
    audit = {
        "status": "PASS" if rows and not missing else "HALT_SCHEMA",
        "dataset_path": str(dataset_path),
        "row_count": len(rows),
        "column_count": len(columns),
        "required_columns": list(REQUIRED_COLUMNS),
        "missing_columns": missing,
        "policy_counts": dict(sorted(policy_counts.items())),
        "episode_count": len({str(row.get("episode_index", "")) for row in rows}),
        "block_action_nvecs": [int(v) for v in BLOCK_ACTION_NVECS],
        "propensity": {
            "random_block_behavior_probability": 1.0 / float(behavior_product),
            "random_block_behavior_probability_formula": "prod(1 / BLOCK_ACTION_NVECS[i])",
            "random_block_action_count": behavior_product,
            "excluded_from_importance_sampling": ["alpha_ucb_block", "stratified_random"],
            "reason": "alpha_ucb_block and stratified_random are deterministic collection policies here, so no random behavior propensity is available for IS.",
        },
    }
    if not rows:
        audit["reason"] = "dataset is missing or empty"
    elif missing:
        audit["reason"] = "dataset is missing required offline-probe columns"
    else:
        audit["reason"] = "schema and Phase 0 propensity checks passed"
    return audit


def analyze_rows(rows: list[dict[str, Any]], *, config: ProbeConfig | None = None) -> dict[str, Any]:
    cfg = config or ProbeConfig()
    arrays = _arrays_from_rows(rows)
    probe_a = run_supervised_probe(arrays, config=cfg)
    probe_b = (
        run_ope_probe(arrays, config=cfg)
        if cfg.run_ope
        else {"status": "SKIPPED", "reason": "OPE disabled by ProbeConfig.run_ope"}
    )
    verdict = verdict_from_probe(probe_a, probe_b)
    report = {
        "format": "dr_alns_offline_probe.v1",
        "config": {
            "seed": cfg.seed,
            "repeats": cfg.repeats,
            "folds": cfg.folds,
            "bootstrap_samples": cfg.bootstrap_samples,
            "model_kind": cfg.model_kind,
            "run_ope": cfg.run_ope,
        },
        "row_count": int(arrays["rewards"].shape[0]),
        "episode_count": int(len(np.unique(arrays["groups"]))),
        "probe_a_supervised_context": probe_a,
        "probe_b_random_block_ope": probe_b,
        "verdict": verdict,
        "counterfactual_spearman_note": (
            "The requested Spearman correlation for model-selected unexecuted actions is not identifiable "
            "from one logged action per state. The reported Spearman is the held-out proxy between model2 "
            "predictions for observed actions and observed rewards; counterfactual policy value is handled "
            "separately by random-block OPE support diagnostics."
        ),
    }
    if verdict["status"] == "INCONCLUSIVE":
        report["learning_curve"] = learning_curve(arrays, config=cfg)
    return report


def run_supervised_probe(arrays: dict[str, np.ndarray], *, config: ProbeConfig) -> dict[str, Any]:
    obs = arrays["obs"]
    actions = arrays["actions"]
    rewards = arrays["rewards"]
    groups = arrays["groups"]
    unique_groups = np.unique(groups)
    if len(unique_groups) < MIN_GROUPS_FOR_CV:
        return {
            "status": "INCONCLUSIVE",
            "reason": f"need at least {MIN_GROUPS_FOR_CV} episode groups for grouped CV",
            "unique_groups": int(len(unique_groups)),
            "folds": [],
        }

    fold_rows: list[dict[str, Any]] = []
    predictions = np.full_like(rewards, np.nan, dtype=np.float64)
    for split in _repeated_group_splits(groups, repeats=config.repeats, folds=config.folds, seed=config.seed):
        train_idx, test_idx, repeat_idx, fold_idx = split
        if len(np.unique(rewards[test_idx])) < 2:
            continue
        baseline = ActionMeanModel().fit(obs[train_idx], actions[train_idx], rewards[train_idx])
        model = _make_context_model(config, fold_seed=config.seed + repeat_idx * 100 + fold_idx)
        model.fit(obs[train_idx], actions[train_idx], rewards[train_idx])
        pred_action = baseline.predict(obs[test_idx], actions[test_idx])
        pred_context = model.predict(obs[test_idx], actions[test_idx])
        predictions[test_idx] = pred_context
        r2_action = _r2_score(rewards[test_idx], pred_action)
        r2_context = _r2_score(rewards[test_idx], pred_context)
        rho = _spearman(pred_context, rewards[test_idx])
        fold_rows.append(
            {
                "repeat": repeat_idx,
                "fold": fold_idx,
                "test_rows": int(test_idx.shape[0]),
                "test_episode_count": int(len(np.unique(groups[test_idx]))),
                "r2_action_only": r2_action,
                "r2_context_action": r2_context,
                "r2_delta": r2_context - r2_action if _finite(r2_action) and _finite(r2_context) else math.nan,
                "spearman_observed_action_proxy": rho,
            }
        )

    finite_delta = [row["r2_delta"] for row in fold_rows if _finite(row["r2_delta"])]
    if len(finite_delta) < MIN_FINITE_FOLDS:
        return {
            "status": "INCONCLUSIVE",
            "reason": f"only {len(finite_delta)} finite grouped-CV folds",
            "folds": fold_rows,
            "minimum_finite_folds": MIN_FINITE_FOLDS,
        }

    summary = {
        "r2_action_only": _metric_summary([row["r2_action_only"] for row in fold_rows], config=config),
        "r2_context_action": _metric_summary([row["r2_context_action"] for row in fold_rows], config=config),
        "r2_delta": _metric_summary(finite_delta, config=config),
        "spearman_observed_action_proxy": _metric_summary(
            [row["spearman_observed_action_proxy"] for row in fold_rows],
            config=config,
        ),
    }
    status = "PROMISING" if summary["r2_delta"]["ci95"][0] > 0.0 else "WEAK"
    reason = (
        "context-aware model improves held-out R2 with a positive lower CI"
        if status == "PROMISING"
        else "context-aware R2 improvement CI does not clear zero"
    )
    return {
        "status": status,
        "reason": reason,
        "model1": "full-action reward mean table with global fallback",
        "model2": _model_description(config),
        "grouping": "episode_index",
        "fold_count": len(fold_rows),
        "finite_delta_fold_count": len(finite_delta),
        "summary": summary,
        "folds": fold_rows,
    }


def run_ope_probe(arrays: dict[str, np.ndarray], *, config: ProbeConfig) -> dict[str, Any]:
    policies = arrays["policies"]
    random_mask = policies == "random_block"
    random_indices = np.flatnonzero(random_mask)
    behavior_prob = 1.0 / float(np.prod(np.asarray(BLOCK_ACTION_NVECS, dtype=np.int64)))
    action_count = int(round(1.0 / behavior_prob))
    if random_indices.size == 0:
        return {
            "status": "INCONCLUSIVE",
            "reason": "no random_block rows for propensity-known OPE",
            "random_rows": 0,
            "behavior_probability": behavior_prob,
        }

    crossfit = crossfit_target_policy(arrays, config=config)
    target_actions = crossfit["target_actions"][random_indices]
    q_target = crossfit["q_target"][random_indices]
    q_observed = crossfit["q_observed"][random_indices]
    rewards = arrays["rewards"][random_indices]
    observed_actions = arrays["actions"][random_indices]
    matches = np.asarray([np.array_equal(left, right) for left, right in zip(target_actions, observed_actions)], dtype=bool)
    rho = matches.astype(np.float64) / behavior_prob
    is_values = rho * rewards
    dr_values = q_target + rho * (rewards - q_observed)
    behavior_summary = _bootstrap_mean_summary(rewards, config=config)
    is_summary = _bootstrap_mean_summary(is_values, config=config)
    dr_summary = _bootstrap_mean_summary(dr_values, config=config)
    direct_summary = _bootstrap_mean_summary(q_target, config=config)
    ess = _effective_sample_size(rho)
    support_ok = int(matches.sum()) >= MIN_OPE_EXACT_MATCHES and ess >= float(MIN_OPE_EXACT_MATCHES)
    status = "OK" if support_ok else "INCONCLUSIVE_SUPPORT"
    reason = (
        "random-block support is sufficient for auxiliary OPE"
        if support_ok
        else "too few exact target-policy action matches under uniform random logging; OPE is diagnostic only"
    )
    return {
        "status": status,
        "reason": reason,
        "random_rows": int(random_indices.size),
        "random_episode_count": int(len(np.unique(arrays["groups"][random_indices]))),
        "behavior_probability": behavior_prob,
        "behavior_action_count": action_count,
        "target_policy": "greedy argmax over all block actions under cross-fitted model2",
        "exact_match_count": int(matches.sum()),
        "expected_exact_matches_under_uniform_random": float(random_indices.size * behavior_prob),
        "effective_sample_size": ess,
        "minimum_exact_matches": MIN_OPE_EXACT_MATCHES,
        "behavior_reward": behavior_summary,
        "target_is": is_summary,
        "target_doubly_robust": dr_summary,
        "target_direct_method": direct_summary,
        "excluded_policies": ["alpha_ucb_block", "stratified_random"],
    }


def crossfit_target_policy(arrays: dict[str, np.ndarray], *, config: ProbeConfig) -> dict[str, np.ndarray]:
    obs = arrays["obs"]
    actions = arrays["actions"]
    rewards = arrays["rewards"]
    groups = arrays["groups"]
    n = rewards.shape[0]
    q_observed = np.full(n, np.nan, dtype=np.float64)
    q_target = np.full(n, np.nan, dtype=np.float64)
    target_actions = np.full((n, len(ACTION_COLS)), -1, dtype=np.int64)
    action_grid = _all_actions()
    splits = list(_repeated_group_splits(groups, repeats=1, folds=config.folds, seed=config.seed))
    if not splits:
        model = _make_context_model(config, fold_seed=config.seed)
        model.fit(obs, actions, rewards)
        indices = np.arange(n)
        _fill_target_predictions(model, obs, actions, indices, action_grid, q_observed, q_target, target_actions)
        return {"q_observed": q_observed, "q_target": q_target, "target_actions": target_actions}
    for train_idx, test_idx, repeat_idx, fold_idx in splits:
        model = _make_context_model(config, fold_seed=config.seed + repeat_idx * 100 + fold_idx)
        model.fit(obs[train_idx], actions[train_idx], rewards[train_idx])
        _fill_target_predictions(model, obs, actions, test_idx, action_grid, q_observed, q_target, target_actions)
    missing = np.isnan(q_observed)
    if np.any(missing):
        model = _make_context_model(config, fold_seed=config.seed + 9999)
        model.fit(obs[~missing], actions[~missing], rewards[~missing])
        _fill_target_predictions(model, obs, actions, np.flatnonzero(missing), action_grid, q_observed, q_target, target_actions)
    return {"q_observed": q_observed, "q_target": q_target, "target_actions": target_actions}


def verdict_from_probe(probe_a: dict[str, Any], probe_b: dict[str, Any]) -> dict[str, Any]:
    if probe_a["status"] == "PROMISING":
        caution = None if probe_b["status"] == "OK" else "OPE support is weak, so the verdict rests on supervised context signal."
        return {
            "status": "PROMISING",
            "basis": "Probe A",
            "reason": probe_a["reason"],
            "ope_caution": caution,
        }
    if probe_a["status"] == "WEAK":
        return {
            "status": "WEAK",
            "basis": "Probe A",
            "reason": probe_a["reason"],
            "ope_caution": None if probe_b["status"] == "OK" else "OPE support is weak and does not rescue the supervised result.",
        }
    return {
        "status": "INCONCLUSIVE",
        "basis": "Probe A",
        "reason": probe_a.get("reason", "grouped CV did not produce a stable result"),
        "minimum_rows": None,
    }


def learning_curve(arrays: dict[str, np.ndarray], *, config: ProbeConfig) -> dict[str, Any]:
    n = arrays["rewards"].shape[0]
    groups = np.unique(arrays["groups"])
    sizes = sorted({min(n, value) for value in (250, 500, 1000, 2000, 4000, n) if value <= max(n, 250)})
    rows: list[dict[str, Any]] = []
    for size in sizes:
        rng = np.random.default_rng(config.seed + int(size))
        chosen_groups: list[int] = []
        chosen_indices: list[int] = []
        shuffled = groups.copy()
        rng.shuffle(shuffled)
        for group in shuffled:
            idx = np.flatnonzero(arrays["groups"] == group)
            chosen_groups.append(int(group))
            chosen_indices.extend(int(i) for i in idx)
            if len(chosen_indices) >= size:
                break
        if len(chosen_groups) < MIN_GROUPS_FOR_CV:
            rows.append({"rows": len(chosen_indices), "episode_count": len(chosen_groups), "status": "TOO_FEW_GROUPS"})
            continue
        subset_idx = np.asarray(chosen_indices, dtype=np.int64)
        subset = {key: value[subset_idx] for key, value in arrays.items() if isinstance(value, np.ndarray)}
        result = run_supervised_probe(subset, config=ProbeConfig(seed=config.seed, repeats=2, folds=min(3, len(chosen_groups)), bootstrap_samples=500, model_kind=config.model_kind))
        summary = result.get("summary", {}).get("r2_delta", {})
        rows.append(
            {
                "rows": int(len(subset_idx)),
                "episode_count": int(len(chosen_groups)),
                "status": result["status"],
                "delta_mean": summary.get("mean"),
                "delta_ci95": summary.get("ci95"),
            }
        )
    minimum = next((row["rows"] for row in rows if row["status"] in {"PROMISING", "WEAK"}), max(4000, n))
    return {"rows": rows, "projected_minimum_rows": int(minimum)}


class ActionMeanModel:
    def __init__(self) -> None:
        self.global_mean = 0.0
        self.means: dict[tuple[int, ...], float] = {}

    def fit(self, obs: np.ndarray, actions: np.ndarray, rewards: np.ndarray) -> "ActionMeanModel":
        _ = obs
        self.global_mean = float(np.mean(rewards)) if rewards.size else 0.0
        buckets: dict[tuple[int, ...], list[float]] = {}
        for action, reward in zip(actions, rewards):
            buckets.setdefault(tuple(int(v) for v in action), []).append(float(reward))
        self.means = {key: float(np.mean(values)) for key, values in buckets.items()}
        return self

    def predict(self, obs: np.ndarray, actions: np.ndarray) -> np.ndarray:
        _ = obs
        return np.asarray([self.means.get(tuple(int(v) for v in action), self.global_mean) for action in actions], dtype=np.float64)


class GradientBoostingRewardModel:
    def __init__(self, *, seed: int) -> None:
        from sklearn.ensemble import GradientBoostingRegressor

        self.model = GradientBoostingRegressor(
            random_state=int(seed),
            n_estimators=80,
            max_depth=2,
            learning_rate=0.05,
            subsample=0.8,
        )

    def fit(self, obs: np.ndarray, actions: np.ndarray, rewards: np.ndarray) -> "GradientBoostingRewardModel":
        self.model.fit(_joined_features(obs, actions), rewards)
        return self

    def predict(self, obs: np.ndarray, actions: np.ndarray) -> np.ndarray:
        return np.asarray(self.model.predict(_joined_features(obs, actions)), dtype=np.float64)


class RidgeRewardModel:
    def __init__(self, *, alpha: float = 1.0) -> None:
        self.alpha = float(alpha)
        self.coef: np.ndarray | None = None
        self.feature_mean: np.ndarray | None = None
        self.feature_scale: np.ndarray | None = None

    def fit(self, obs: np.ndarray, actions: np.ndarray, rewards: np.ndarray) -> "RidgeRewardModel":
        features = _ridge_features(obs, actions)
        self.feature_mean = features.mean(axis=0)
        self.feature_scale = features.std(axis=0)
        self.feature_scale[self.feature_scale < 1e-8] = 1.0
        scaled = (features - self.feature_mean) / self.feature_scale
        design = np.column_stack([np.ones(scaled.shape[0]), scaled])
        penalty = np.eye(design.shape[1]) * self.alpha
        penalty[0, 0] = 0.0
        self.coef = np.linalg.pinv(design.T @ design + penalty) @ design.T @ rewards
        return self

    def predict(self, obs: np.ndarray, actions: np.ndarray) -> np.ndarray:
        if self.coef is None or self.feature_mean is None or self.feature_scale is None:
            raise RuntimeError("RidgeRewardModel must be fit before predict")
        features = _ridge_features(obs, actions)
        scaled = (features - self.feature_mean) / self.feature_scale
        design = np.column_stack([np.ones(scaled.shape[0]), scaled])
        return np.asarray(design @ self.coef, dtype=np.float64)


def _make_context_model(config: ProbeConfig, *, fold_seed: int) -> RewardModel:
    if config.model_kind == "ridge":
        return RidgeRewardModel(alpha=1.0)
    if config.model_kind in {"auto", "gbr"}:
        try:
            return GradientBoostingRewardModel(seed=fold_seed)
        except Exception:
            if config.model_kind == "gbr":
                raise
    return RidgeRewardModel(alpha=1.0)


def _model_description(config: ProbeConfig) -> str:
    if config.model_kind == "ridge":
        return "deterministic NumPy ridge over obs, action one-hot, and obs/action interactions"
    try:
        import sklearn  # noqa: F401
    except Exception:
        return "deterministic NumPy ridge over obs, action one-hot, and obs/action interactions"
    return "sklearn GradientBoostingRegressor over obs + action"


def _arrays_from_rows(rows: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    return {
        "obs": np.asarray([[float(row[col]) for col in OBS_COLS] for row in rows], dtype=np.float64),
        "actions": np.asarray([[int(float(row[col])) for col in ACTION_COLS] for row in rows], dtype=np.int64),
        "rewards": np.asarray([float(row["reward"]) for row in rows], dtype=np.float64),
        "groups": np.asarray([int(float(row["episode_index"])) for row in rows], dtype=np.int64),
        "policies": np.asarray([str(row["collection_policy"]) for row in rows], dtype=object),
    }


def _repeated_group_splits(
    groups: np.ndarray,
    *,
    repeats: int,
    folds: int,
    seed: int,
) -> list[tuple[np.ndarray, np.ndarray, int, int]]:
    unique_groups = np.asarray(sorted(np.unique(groups)), dtype=np.int64)
    if unique_groups.size < 2:
        return []
    fold_count = min(int(folds), int(unique_groups.size))
    rng = np.random.default_rng(int(seed))
    splits: list[tuple[np.ndarray, np.ndarray, int, int]] = []
    for repeat_idx in range(int(repeats)):
        shuffled = unique_groups.copy()
        rng.shuffle(shuffled)
        for fold_idx, test_groups in enumerate(np.array_split(shuffled, fold_count)):
            if test_groups.size == 0:
                continue
            test_mask = np.isin(groups, test_groups)
            train_mask = ~test_mask
            if not np.any(test_mask) or not np.any(train_mask):
                continue
            splits.append((np.flatnonzero(train_mask), np.flatnonzero(test_mask), repeat_idx, fold_idx))
    return splits


def _fill_target_predictions(
    model: RewardModel,
    obs: np.ndarray,
    actions: np.ndarray,
    indices: np.ndarray,
    action_grid: np.ndarray,
    q_observed: np.ndarray,
    q_target: np.ndarray,
    target_actions: np.ndarray,
) -> None:
    if indices.size == 0:
        return
    q_observed[indices] = model.predict(obs[indices], actions[indices])
    for start in range(0, indices.shape[0], GREEDY_CHUNK_ROWS):
        chunk = indices[start : start + GREEDY_CHUNK_ROWS]
        obs_grid = np.repeat(obs[chunk], action_grid.shape[0], axis=0)
        action_grid_tiled = np.tile(action_grid, (chunk.shape[0], 1))
        preds = model.predict(obs_grid, action_grid_tiled).reshape(chunk.shape[0], action_grid.shape[0])
        best = np.argmax(preds, axis=1)
        q_target[chunk] = preds[np.arange(chunk.shape[0]), best]
        target_actions[chunk] = action_grid[best]


def _joined_features(obs: np.ndarray, actions: np.ndarray) -> np.ndarray:
    return np.concatenate([obs.astype(np.float64), actions.astype(np.float64)], axis=1)


def _ridge_features(obs: np.ndarray, actions: np.ndarray) -> np.ndarray:
    one_hot_parts = []
    for head_idx, n in enumerate(BLOCK_ACTION_NVECS):
        part = np.zeros((actions.shape[0], int(n)), dtype=np.float64)
        part[np.arange(actions.shape[0]), actions[:, head_idx].astype(int)] = 1.0
        one_hot_parts.append(part)
    action_hot = np.concatenate(one_hot_parts, axis=1)
    interactions = np.einsum("ni,nj->nij", obs.astype(np.float64), action_hot).reshape(obs.shape[0], -1)
    return np.concatenate([obs.astype(np.float64), action_hot, interactions], axis=1)


def _all_actions() -> np.ndarray:
    return np.asarray(list(itertools.product(*(range(int(n)) for n in BLOCK_ACTION_NVECS))), dtype=np.int64)


def _r2_score(actual: np.ndarray, predicted: np.ndarray) -> float:
    denom = float(np.sum((actual - float(np.mean(actual))) ** 2))
    if denom <= 1e-12:
        return math.nan
    return float(1.0 - np.sum((actual - predicted) ** 2) / denom)


def _spearman(left: np.ndarray, right: np.ndarray) -> float:
    if left.size < 2 or right.size < 2:
        return math.nan
    left_rank = _rankdata(left)
    right_rank = _rankdata(right)
    return _pearson(left_rank, right_rank)


def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.shape[0], dtype=np.float64)
    sorted_values = values[order]
    start = 0
    while start < values.shape[0]:
        end = start + 1
        while end < values.shape[0] and sorted_values[end] == sorted_values[start]:
            end += 1
        rank = 0.5 * (start + end - 1) + 1.0
        ranks[order[start:end]] = rank
        start = end
    return ranks


def _pearson(left: np.ndarray, right: np.ndarray) -> float:
    left_centered = left - float(np.mean(left))
    right_centered = right - float(np.mean(right))
    denom = float(np.sqrt(np.sum(left_centered**2) * np.sum(right_centered**2)))
    if denom <= 1e-12:
        return math.nan
    return float(np.sum(left_centered * right_centered) / denom)


def _metric_summary(values: list[float], *, config: ProbeConfig) -> dict[str, Any]:
    clean = np.asarray([float(v) for v in values if _finite(v)], dtype=np.float64)
    if clean.size == 0:
        return {"n": 0, "mean": math.nan, "std": math.nan, "ci95": [math.nan, math.nan]}
    mean = float(np.mean(clean))
    std = float(np.std(clean, ddof=1)) if clean.size > 1 else 0.0
    ci = _bootstrap_ci(clean, seed=config.seed, samples=config.bootstrap_samples)
    return {"n": int(clean.size), "mean": mean, "std": std, "ci95": [ci[0], ci[1]]}


def _bootstrap_mean_summary(values: np.ndarray, *, config: ProbeConfig) -> dict[str, Any]:
    clean = np.asarray([float(v) for v in values if _finite(float(v))], dtype=np.float64)
    if clean.size == 0:
        return {"n": 0, "mean": math.nan, "ci95": [math.nan, math.nan]}
    ci = _bootstrap_ci(clean, seed=config.seed, samples=config.bootstrap_samples)
    return {"n": int(clean.size), "mean": float(np.mean(clean)), "ci95": [ci[0], ci[1]]}


def _bootstrap_ci(values: np.ndarray, *, seed: int, samples: int) -> tuple[float, float]:
    if values.size == 1:
        value = float(values[0])
        return value, value
    rng = np.random.default_rng(int(seed))
    means = np.empty(int(samples), dtype=np.float64)
    for idx in range(int(samples)):
        sample = rng.choice(values, size=values.size, replace=True)
        means[idx] = float(np.mean(sample))
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _effective_sample_size(weights: np.ndarray) -> float:
    total = float(np.sum(weights))
    denom = float(np.sum(weights**2))
    if denom <= 1e-12:
        return 0.0
    return float(total * total / denom)


def _finite(value: float) -> bool:
    return math.isfinite(float(value))


def _select_dataset(dataset: Path, partial_dataset: Path) -> Path:
    if dataset.exists():
        return dataset
    return partial_dataset


def _checked_output_dir(path: Path) -> Path:
    text = str(path)
    if REPORT_ROOT_FRAGMENT not in text:
        raise ValueError(f"offline probe reports must stay under {REPORT_ROOT_FRAGMENT}: {path}")
    return path


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def audit_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# Offline Probe Audit",
        "",
        f"Status: `{audit['status']}`.",
        f"Dataset: `{audit['dataset_path']}`.",
        f"Rows: {audit['row_count']}. Columns: {audit['column_count']}. Episodes: {audit['episode_count']}.",
        "",
        "Required columns are present." if not audit["missing_columns"] else f"Missing columns: `{audit['missing_columns']}`.",
        "",
        "| collection_policy | rows |",
        "| --- | ---: |",
    ]
    for policy, count in audit["policy_counts"].items():
        lines.append(f"| {policy} | {count} |")
    propensity = audit["propensity"]
    lines.extend(
        [
            "",
            f"`random_block` behavior probability is `1/{propensity['random_block_action_count']}` = `{propensity['random_block_behavior_probability']:.12f}`.",
            "`alpha_ucb_block` and `stratified_random` are excluded from IS because they are deterministic collection policies in this dataset.",
        ]
    )
    return "\n".join(lines)


def probe_report_markdown(report: dict[str, Any]) -> str:
    verdict = report["verdict"]
    probe_a = report["probe_a_supervised_context"]
    probe_b = report["probe_b_random_block_ope"]
    lines = [
        "# Offline Probe Report",
        "",
        f"Verdict: `{verdict['status']}`.",
        "",
        _plain_verdict(report),
        "",
        f"Code commit: `{report.get('code_commit', 'UNKNOWN')}`.",
        f"Rows: {report['row_count']}. Episodes: {report['episode_count']}.",
        "",
        "## Probe A: Supervised Context Signal",
        "",
        f"Status: `{probe_a['status']}`. Reason: {probe_a['reason']}.",
    ]
    if "summary" in probe_a:
        lines.extend(
            [
                "",
                "| metric | n | mean | ci95 low | ci95 high |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for name, summary in probe_a["summary"].items():
            low, high = summary["ci95"]
            lines.append(f"| {name} | {summary['n']} | {summary['mean']:.6f} | {low:.6f} | {high:.6f} |")
    lines.extend(
        [
            "",
            "Counterfactual Spearman note: the model-selected unexecuted action reward is not identifiable from this one-action-per-state log. The Spearman reported above is the held-out observed-action proxy.",
            "",
            "## Probe B: Random-Block OPE",
            "",
            f"Status: `{probe_b['status']}`. Reason: {probe_b['reason']}.",
            f"Random rows: {probe_b.get('random_rows', 0)}. Exact target-action matches: {probe_b.get('exact_match_count', 0)}. Effective sample size: {probe_b.get('effective_sample_size', 0.0):.3f}.",
        ]
    )
    for label, key in (
        ("Behavior random reward", "behavior_reward"),
        ("Target direct method", "target_direct_method"),
        ("Target IS", "target_is"),
        ("Target doubly robust", "target_doubly_robust"),
    ):
        if key in probe_b:
            summary = probe_b[key]
            low, high = summary["ci95"]
            lines.append(f"{label}: mean `{summary['mean']:.6f}`, CI `[{low:.6f}, {high:.6f}]`.")
    return "\n".join(lines)


def _plain_verdict(report: dict[str, Any]) -> str:
    status = report["verdict"]["status"]
    if status == "PROMISING":
        return "白话结论：已有 block 轨迹里确实有上下文可学信号，值得上 GPU 做课程式重训；但 random-block OPE 支持太薄，不能把它当成最终性能证明。"
    if status == "WEAK":
        return "白话结论：当前离线证据没有显示状态上下文能稳定改进动作选择，不建议继续烧训练资源。"
    return "白话结论：当前数据不足以判定，需要按学习曲线补到最小行数后再判断。"


def curriculum_plan_markdown(report: dict[str, Any]) -> str:
    code_commit = report.get("code_commit", "UNKNOWN")
    return f"""# Curriculum Training Plan

Code commit for this offline-probe design: `{code_commit}`.

This is an implementation plan only. It must not change `solver/src/setp_solver/cost.py`, `solver/src/setp_solver/check.py`, or `solver/src/setp_solver/search/evaluation.py`; final evaluation always uses the true solver objective and feasibility checks.

## Source Ideas

Daysalilar et al. 2026, ["A curriculum-based deep RL framework for the EVRP"](https://arxiv.org/abs/2601.15038), motivates a staged constraint curriculum: learn route topology first, then energy, then time-window/full EV routing. Wan et al. 2025, ["Deep Reinforcement Learning for Solving the Fleet Size and Mix Vehicle Routing Problem"](https://arxiv.org/abs/2512.24251), motivates reducing instance-level return variance with same-instance shared baselines. Narayanan et al. 2022, ["A Reinforcement Learning Approach for Electric Vehicle Routing Problem with Vehicle-to-Grid Supply"](https://arxiv.org/abs/2204.05545), motivates masking infeasible or degenerate actions before selection.

## Reward Curriculum

Add a phase argument in `solver/rl/dr_alns_ppo/block_env.py`, store it as `self.curriculum_phase`, and branch only inside `_reward()`. Phase A should keep route-count and distance/current-improvement terms, suppressing EV, carbon, fairness, and dynamic terms. Phase B should add EV charging efficiency signals from `charge_ratio`, requested q/threshold, and block improvement rates. Phase C should add carbon and fairness-shaped terms from worker response metrics when present, while still treating `violation_count` as a hard negative signal. Phase D should add dynamic-demand or rolling-replan terms only when the worker response exposes those fields.

The CLI in `solver/rl/dr_alns_ppo/train_async_block_ppo.py` should accept `--curriculum-schedule route,energy,carbon,dynamic`, `--phase-min-episodes`, and phase-specific `--learning-rate`, `--entropy-coef`, `--clip-range`, and value/advantage clipping settings. Stage switching should require both a minimum episode count and stable feasibility: zero violations plus non-degrading median best objective over the most recent completed same-bundle rollout window.

## Action Masking

Add an optional `action_mask` to the `info` dictionary returned by the block environment step path, shaped as one boolean vector per MultiDiscrete head. The mask should be computed from current response fields and observation-derived facts, not by running extra solver evaluations. Mask `vehicle_type_swap` when `ev_share` is effectively 0 or 1 and the solution is homogeneous. Mask route-removal style choices when `route_gap <= 0` or recent `route_delta`/best improvement data says route elimination cannot reduce routes. Mask oversized q values in late budget or high rejection/stagnation states when they repeatedly yield no block improvement.

Update `solver/rl/dr_alns_ppo/async_block_policy.py` so `BlockActorCritic.forward()` can accept masks and set invalid logits to a large negative value before constructing `Categorical` distributions. Update `act()` and `evaluate_actions()` to consume masks during rollout and PPO update, and log mask hit rates in `train_async_block_ppo.py` to detect accidental always-on masks.

## Shared Baseline

In `solver/rl/dr_alns_ppo/train_async_block_ppo.py`, collect rollout batches in same-bundle groups before calling `flatten_episodes()`. For each bundle group with N completed rollouts, compute the group mean return and subtract it from each episode return before advantage normalization. Keep the current critic value head, but make this shared baseline an additional variance-reduction step before the existing standardized advantage calculation.

Acceptance for the later GPU run is still external: after training, evaluate with the gold system-Python worker and true `cost.py` objective on the formal seed set. Curriculum reward is training shaping only, not a paper metric.
"""


def _git_commit() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            text=True,
            capture_output=True,
        )
    except Exception:
        return "UNKNOWN"
    return proc.stdout.strip() if proc.returncode == 0 else "UNKNOWN"


if __name__ == "__main__":
    raise SystemExit(main())
