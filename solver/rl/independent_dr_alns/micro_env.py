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


__all__ = ["CONTEXT_ACTIONS", "IndependentDrContextEnv", "IndependentDrMicroEnv", "MICRO_ACTIONS"]
