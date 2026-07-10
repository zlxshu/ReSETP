from __future__ import annotations

from pathlib import Path
from typing import Any

import gymnasium as gym
from gymnasium import spaces
import numpy as np

from .chain import DrAction, IndependentDrSession


MICRO_ACTIONS = (
    DrAction("random_customer_removal", "greedy_insert_repair", 0.10, 0.0),
    DrAction("vehicle_type_swap", "greedy_insert_repair", 0.10, 0.0),
)

CONTEXT_ACTIONS = (
    DrAction("worst_customer_removal", "regret2_insert_repair", 0.10, 0.0),
    DrAction("vehicle_type_swap", "greedy_insert_repair", 0.10, 0.0),
    DrAction("shaw_related_removal", "greedy_insert_repair", 0.10, 0.0),
)

FULL_SEARCH_ACTIONS = tuple(
    DrAction(destroy_id, repair_id, 0.10, 0.02)
    for destroy_id in (
        "random_customer_removal",
        "worst_customer_removal",
        "shaw_related_removal",
        "whole_route_removal",
        "route_segment_removal",
        "vehicle_type_swap",
    )
    for repair_id in (
        "greedy_insert_repair",
        "regret2_insert_repair",
        "regret3_insert_repair",
    )
)

# The three insertion repairs frequently produce the same complete candidate
# for a fixed destroy move, so repair choice is held at stable regret-2.  The
# q audit did show material and state-dependent differences at 5/10/20/30%,
# therefore the real DR surface is six distinct destroy moves by four destroy
# sizes. FULL_SEARCH_ACTIONS remains available for repair diagnostics.
SEARCH_ACTIONS = tuple(
    DrAction(destroy_id, "regret2_insert_repair", remove_fraction, 0.02)
    for destroy_id in (
        "random_customer_removal",
        "worst_customer_removal",
        "shaw_related_removal",
        "whole_route_removal",
        "route_segment_removal",
        "vehicle_type_swap",
    )
    for remove_fraction in (0.05, 0.10, 0.20, 0.30)
)


class IndependentDrMicroEnv(gym.Env):
    """One-decision proof that a policy can learn a real independent action.

    This is intentionally not the formal DR environment. Both actions are
    applicable at the all-CV start, their meanings never change, and the reward
    is only the full-evaluator best-cost decrease. It exists solely as the
    pre-training gate requested for E2.
    """

    metadata = {"render_modes": []}

    def __init__(self, bundle_dir: str | Path, *, seed: int = 1) -> None:
        super().__init__()
        self.bundle_dir = Path(bundle_dir)
        self.seed_value = int(seed)
        self.action_space = spaces.Discrete(len(MICRO_ACTIONS))
        self.observation_space = spaces.Box(0.0, 1.0, shape=(6,), dtype=np.float32)
        self.session: IndependentDrSession | None = None

    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        _ = options
        super().reset(seed=seed)
        if seed is not None:
            self.seed_value = int(seed)
        self.session = IndependentDrSession(self.bundle_dir, seed=self.seed_value, max_evals=1)
        return self._observation(), {"initial_obj": float(self.session.initial_obj)}

    def step(self, action: int):
        if self.session is None:
            raise RuntimeError("reset must be called before step")
        index = int(action)
        if not 0 <= index < len(MICRO_ACTIONS):
            raise ValueError(f"action index out of range: {index}")
        result = self.session.step(MICRO_ACTIONS[index])
        reward = float(result["reward"]) * 100.0
        return self._observation(), reward, True, False, result

    def _observation(self) -> np.ndarray:
        if self.session is None:
            return np.zeros(6, dtype=np.float32)
        return _session_observation(self.session)


class IndependentDrContextEnv(gym.Env):
    """Small contextual gate over fixed, always-identical action meanings."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        bundle_dirs: list[str | Path],
        *,
        seed: int = 1,
        reward_scales: dict[str, float] | None = None,
    ) -> None:
        super().__init__()
        if not bundle_dirs:
            raise ValueError("bundle_dirs must not be empty")
        self.bundle_dirs = tuple(Path(path) for path in bundle_dirs)
        self.reward_scales = {
            str(Path(path).resolve()): float(scale)
            for path, scale in (reward_scales or {}).items()
        }
        if any(not np.isfinite(scale) or scale <= 0.0 for scale in self.reward_scales.values()):
            raise ValueError("reward scales must be finite and positive")
        self.seed_value = int(seed)
        self.action_space = spaces.Discrete(len(CONTEXT_ACTIONS))
        self.observation_space = spaces.Box(0.0, 1.0, shape=(6,), dtype=np.float32)
        self._initial_solutions = tuple(
            IndependentDrSession(path, seed=self.seed_value, max_evals=1).initial_solution
            for path in self.bundle_dirs
        )
        self.session: IndependentDrSession | None = None
        self.bundle_index = 0

    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        _ = options
        super().reset(seed=seed)
        if seed is not None:
            self.seed_value = int(seed)
        self.bundle_index = int(self.np_random.integers(0, len(self.bundle_dirs)))
        self.session = IndependentDrSession(
            self.bundle_dirs[self.bundle_index],
            seed=self.seed_value,
            max_evals=1,
            initial_solution=self._initial_solutions[self.bundle_index],
        )
        return _session_observation(self.session), {"bundle_index": int(self.bundle_index)}

    def step(self, action: int):
        if self.session is None:
            raise RuntimeError("reset must be called before step")
        index = int(action)
        if not 0 <= index < len(CONTEXT_ACTIONS):
            raise ValueError(f"action index out of range: {index}")
        result = self.session.step(CONTEXT_ACTIONS[index])
        raw_reward = float(result["reward"]) * 100.0
        scale = self.reward_scales.get(str(self.bundle_dirs[self.bundle_index].resolve()), 1.0)
        reward = raw_reward / scale
        result["bundle_index"] = int(self.bundle_index)
        result["raw_cost_reward"] = float(raw_reward)
        result["training_reward_scale"] = float(scale)
        return _session_observation(self.session), reward, True, False, result


class IndependentDrSearchEnv(gym.Env):
    """Multi-step DR control with fixed action meanings and cost-only reward.

    The policy chooses again after every complete candidate evaluation.  There
    is no random replacement or fallback selector.  The observation contains
    only the current solution, elapsed budget, and outcomes of past actions in
    this episode; it cannot contain future events or a static full-information
    answer.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        bundle_dirs: list[str | Path],
        *,
        horizon: int,
        seed: int = 1,
        reward_scales: dict[str, float] | None = None,
        training_warmup_action_indices: list[int] | None = None,
    ) -> None:
        super().__init__()
        if not bundle_dirs:
            raise ValueError("bundle_dirs must not be empty")
        if int(horizon) < 1:
            raise ValueError("horizon must be positive")
        self.bundle_dirs = tuple(Path(path) for path in bundle_dirs)
        self.horizon = int(horizon)
        self.seed_value = int(seed)
        self.training_warmup_action_indices = tuple(int(index) for index in (training_warmup_action_indices or ()))
        if len(self.training_warmup_action_indices) >= self.horizon:
            raise ValueError("training warmup must leave at least one policy decision")
        if any(not 0 <= index < len(SEARCH_ACTIONS) for index in self.training_warmup_action_indices):
            raise ValueError("training warmup action index out of range")
        self.reward_scales = {
            str(Path(path).resolve()): float(scale)
            for path, scale in (reward_scales or {}).items()
        }
        if any(not np.isfinite(scale) or scale <= 0.0 for scale in self.reward_scales.values()):
            raise ValueError("reward scales must be finite and positive")
        self.action_space = spaces.Discrete(len(SEARCH_ACTIONS))
        self.observation_space = spaces.Box(0.0, 1.0, shape=(17 + 2 * len(SEARCH_ACTIONS),), dtype=np.float32)
        self.session: IndependentDrSession | None = None
        self.bundle_index = 0
        self.steps = 0
        self.stagnation = 0
        self.last_reward = 0.0
        self.accept_ema = np.zeros(len(SEARCH_ACTIONS), dtype=np.float32)
        self.improve_ema = np.zeros(len(SEARCH_ACTIONS), dtype=np.float32)

    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        _ = options
        super().reset(seed=seed)
        if seed is not None:
            self.seed_value = int(seed)
        self.bundle_index = int(self.np_random.integers(0, len(self.bundle_dirs)))
        self.session = IndependentDrSession(
            self.bundle_dirs[self.bundle_index],
            seed=self.seed_value,
            max_evals=self.horizon,
            carbon_aware_operators=False,
        )
        missing = [
            action
            for action in SEARCH_ACTIONS
            if action.destroy_id not in self.session.destroy_ids or action.repair_id not in self.session.repair_ids
        ]
        if missing:
            raise RuntimeError(f"independent kernel action contract changed: {missing}")
        self.steps = 0
        self.stagnation = 0
        self.last_reward = 0.0
        self.accept_ema.fill(0.0)
        self.improve_ema.fill(0.0)
        warmup_reward = 0.0
        for action_index in self.training_warmup_action_indices:
            _, reward, terminated, _, _ = self.step(action_index)
            if terminated:
                raise RuntimeError("training warmup exhausted the episode")
            warmup_reward += float(reward)
        return self._observation(), {
            "bundle_index": int(self.bundle_index),
            "initial_obj": float(self.session.initial_obj),
            "training_warmup_steps": len(self.training_warmup_action_indices),
            "training_warmup_reward_discarded": float(warmup_reward),
        }

    def step(self, action: int):
        if self.session is None:
            raise RuntimeError("reset must be called before step")
        index = int(action)
        if not 0 <= index < len(SEARCH_ACTIONS):
            raise ValueError(f"action index out of range: {index}")
        result = self.session.step(SEARCH_ACTIONS[index])
        self.steps += 1
        initial = max(abs(float(result["initial_obj"])), 1.0)
        best_cost_reward = float(result["reward"]) * 100.0
        current_cost_reward = (
            float(result["before"]["objective"]) - float(result["after"]["objective"])
        ) / initial * 100.0
        terminated = self.steps >= self.horizon
        terminal_reconciliation = 0.0
        if terminated:
            terminal_reconciliation = (
                float(result["after"]["objective"]) - float(result["after"]["best_obj"])
            ) / initial * 100.0
        raw_reward = current_cost_reward + terminal_reconciliation
        scale = self.reward_scales.get(str(self.bundle_dirs[self.bundle_index].resolve()), 1.0)
        reward = raw_reward / scale
        self.stagnation = 0 if bool(result["improved_best"]) else self.stagnation + 1
        self.last_reward = max(0.0, min(1.0, reward))
        self.accept_ema *= 0.95
        self.improve_ema *= 0.95
        self.accept_ema[index] += 0.05 * float(bool(result["accepted"]))
        self.improve_ema[index] += 0.05 * float(bool(result["improved_best"]))
        result.update(
            {
                "action_index": index,
                "bundle_index": int(self.bundle_index),
                "raw_cost_reward": float(raw_reward),
                "best_cost_reward": float(best_cost_reward),
                "current_cost_reward": float(current_cost_reward),
                "terminal_reconciliation": float(terminal_reconciliation),
                "training_reward_scale": float(scale),
            }
        )
        return self._observation(), reward, terminated, False, result

    def _observation(self) -> np.ndarray:
        if self.session is None:
            return np.zeros(self.observation_space.shape, dtype=np.float32)
        initial = max(abs(float(self.session.initial_obj)), 1.0)
        current_gap = max(0.0, float(self.session.current_obj - self.session.best_obj) / initial)
        prefix = np.concatenate(
            [
                _session_observation(self.session),
                _route_bottleneck_observation(self.session),
                np.array(
                    [
                        min(1.0, current_gap),
                        min(1.0, float(self.stagnation) / float(self.horizon)),
                        float(self.last_reward),
                    ],
                    dtype=np.float32,
                ),
            ]
        )
        return np.concatenate([prefix, self.accept_ema, self.improve_ema]).astype(np.float32, copy=False)


def _route_bottleneck_observation(session: IndependentDrSession) -> np.ndarray:
    """Cheap current-route shape signals; no candidate lookahead or future data."""

    solution = session.current_solution
    instance = session.bundle.instance
    routes = list(solution.routes)
    if not routes:
        return np.zeros(8, dtype=np.float32)
    node_lookup = {node.node_id: node for node in instance.nodes}
    customer_counts: list[float] = []
    distances: list[float] = []
    loads: list[float] = []
    depot_counts: dict[str, int] = {}
    for route in routes:
        customers = [
            node_id
            for node_id in route.node_sequence
            if node_id in node_lookup and str(node_lookup[node_id].node_type).lower() == "c"
        ]
        customer_counts.append(float(len(customers)))
        distances.append(
            sum(
                float(instance.distance(left, right))
                for left, right in zip(route.node_sequence, route.node_sequence[1:])
            )
        )
        loads.append(sum(float(node_lookup[node_id].demand) for node_id in customers))
        depot_counts[route.home_depot_id] = depot_counts.get(route.home_depot_id, 0) + 1
    count_array = np.asarray(customer_counts, dtype=float)
    distance_array = np.asarray(distances, dtype=float)
    load_array = np.asarray(loads, dtype=float)
    total_customers = max(float(count_array.sum()), 1.0)
    total_distance = max(float(distance_array.sum()), 1.0)
    capacity = max(float(getattr(session.context.prices, "Q_capacity", 1.0)), 1.0)
    route_count = max(float(len(routes)), 1.0)
    return np.asarray(
        [
            min(1.0, total_customers / 200.0),
            float(np.count_nonzero(count_array <= 1.0)) / route_count,
            min(1.0, float(count_array.max(initial=0.0)) / total_customers),
            min(1.0, float(count_array.std()) / max(float(count_array.mean()), 1.0)),
            min(1.0, float(distance_array.max(initial=0.0)) / total_distance),
            min(1.0, float(distance_array.std()) / max(float(distance_array.mean()), 1.0)),
            min(1.0, float(load_array.max(initial=0.0)) / capacity),
            min(1.0, max(depot_counts.values(), default=0) / route_count),
        ],
        dtype=np.float32,
    )


def _session_observation(session: IndependentDrSession) -> np.ndarray:
    summary = session._summary(session.current_solution, session.current_obj, best_obj=session.best_obj)
    metrics = summary["metrics"]
    total = max(abs(float(metrics.get("total_cost", 0.0))), 1.0)
    ev = float(metrics.get("n_veh_ev", 0.0))
    cv = float(metrics.get("n_veh_cv", 0.0))
    routes = max(float(summary["route_count"]), 1.0)
    budget = session.context.budget
    progress = 0.0 if budget is None else float(budget.count) / max(float(budget.target_count), 1.0)
    return np.array(
        [
            min(1.0, routes / 20.0),
            ev / max(ev + cv, 1.0),
            float(summary["charging_action_count"]) / routes,
            min(1.0, abs(float(metrics.get("cost_fix", 0.0))) / total),
            min(1.0, abs(float(metrics.get("cost_km", 0.0))) / total),
            min(1.0, progress),
        ],
        dtype=np.float32,
    )


__all__ = [
    "CONTEXT_ACTIONS",
    "IndependentDrContextEnv",
    "IndependentDrMicroEnv",
    "IndependentDrSearchEnv",
    "FULL_SEARCH_ACTIONS",
    "MICRO_ACTIONS",
    "SEARCH_ACTIONS",
]
