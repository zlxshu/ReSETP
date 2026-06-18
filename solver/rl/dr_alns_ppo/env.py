from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .action_space import FULL_ACTION_NVECS, OPERATOR_ONLY_NVECS, REDUCED_ACTION_NVECS, decode_action
from .worker_client import WorkerClient


OBSERVATION_SIZE = 11


class SetpAlnsEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(
        self,
        bundle_dir: str,
        seed: int = 1,
        eval_budget: int = 16000,
        base_temperature: float = 100.0,
        control_mode: str = "ppo_full",
    ) -> None:
        super().__init__()
        self.bundle_dir = bundle_dir
        self.seed_value = int(seed)
        self.eval_budget = int(eval_budget)
        self.base_temperature = float(base_temperature)
        self.control_mode = str(control_mode)
        if self.control_mode not in {"ppo_full", "reduced_full", "operator_only", "kernel_default"}:
            raise ValueError(f"unknown control_mode: {control_mode}")
        if self.control_mode == "ppo_full":
            nvec = FULL_ACTION_NVECS
        elif self.control_mode == "reduced_full":
            nvec = REDUCED_ACTION_NVECS
        else:
            nvec = OPERATOR_ONLY_NVECS
        self.action_space = spaces.MultiDiscrete(list(nvec))
        self.observation_space = spaces.Box(
            low=-10.0,
            high=10.0,
            shape=(OBSERVATION_SIZE,),
            dtype=np.float32,
        )
        self.client = WorkerClient(bundle_dir, seed=self.seed_value, max_evals=self.eval_budget)
        self.last_response: dict[str, Any] | None = None
        self.initial_obj: float | None = None

    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        _ = options
        super().reset(seed=seed)
        if seed is not None and int(seed) != self.seed_value:
            self.client.close()
            self.seed_value = int(seed)
            self.client = WorkerClient(self.bundle_dir, seed=self.seed_value, max_evals=self.eval_budget)
        self.last_response = self._checked_response(self.client.reset())
        self.initial_obj = _float(self.last_response.get("best_obj"), 0.0)
        return self._obs(self.last_response), {"actual_evals": int(self.last_response.get("actual_evals", 0))}

    def step(self, action):
        decoded = decode_action(action, base_temperature=self.base_temperature, control_mode=self.control_mode)
        response = self._checked_response(self.client.step(decoded))
        self.last_response = response
        terminated = bool(int(response.get("actual_evals", 0)) >= self.eval_budget)
        reward = self._reward(response, terminated=terminated)
        truncated = False
        return self._obs(response), reward, terminated, truncated, response

    def close(self) -> None:
        self.client.close()
        super().close()

    def _reward(self, response: dict[str, Any], *, terminated: bool = False) -> float:
        reward = 0.0
        if response.get("improved_best"):
            reward += 5.0
        elif response.get("improved_current"):
            trace = response.get("trace", {}) or {}
            delta = _float(trace.get("delta"), 0.0)
            candidate_obj = _float(response.get("candidate_obj"), 0.0)
            previous_obj = candidate_obj - delta
            relative = max(0.0, -delta / max(abs(previous_obj), 1.0))
            reward += float(max(0.01, min(1.0, relative * 100.0)))
        if terminated and self.initial_obj is not None:
            best_obj = _float(response.get("best_obj"), self.initial_obj)
            terminal_gain = max(0.0, (float(self.initial_obj) - best_obj) / max(abs(float(self.initial_obj)), 1.0))
            reward += float(min(10.0, terminal_gain * 100.0))
        return reward

    def _obs(self, response: dict[str, Any]) -> np.ndarray:
        metrics = response.get("metrics", {}) or {}
        trace = response.get("trace", {}) or {}
        solution = response.get("solution", {}) or {}

        current_obj = _float(response.get("current_obj"), 0.0)
        best_obj = _float(response.get("best_obj"), current_obj)
        gap = (current_obj - best_obj) / max(abs(best_obj), 1.0)

        delta = _float(trace.get("delta"), 0.0)
        candidate_obj = _float(response.get("candidate_obj"), current_obj)
        previous_obj = candidate_obj - delta
        last_improvement = max(0.0, -delta / max(abs(previous_obj), 1.0))

        stagnation = _float(trace.get("stagnation_steps"), 0.0) / max(float(self.eval_budget), 1.0)
        budget_progress = _float(response.get("actual_evals"), 0.0) / max(float(self.eval_budget), 1.0)
        temperature_norm = _float(trace.get("threshold_ratio"), 0.0) / 0.02

        ev_routes = _float(metrics.get("n_veh_ev"), 0.0)
        cv_routes = _float(metrics.get("n_veh_cv"), 0.0)
        ev_cv_ratio = ev_routes / max(cv_routes, 1.0)

        routes = solution.get("routes", []) if isinstance(solution, dict) else []
        charging_actions = solution.get("charging_actions", []) if isinstance(solution, dict) else []
        route_count = len(routes) if isinstance(routes, list) else 0
        charge_count = len(charging_actions) if isinstance(charging_actions, list) else 0
        charge_ratio = float(charge_count) / max(float(route_count), 1.0)

        total_cost = _float(metrics.get("total_cost"), 0.0)
        carbon_cost_share = abs(_float(metrics.get("cost_carbon"), 0.0)) / max(abs(total_cost), 1.0)

        emissions = _float(metrics.get("E_total"), 0.0)
        quota = _float(metrics.get("carbon_quota_kg"), 0.0)
        quota_slack = (quota - emissions) / max(abs(emissions), 1.0)

        violations = min(10.0, max(0.0, _float(response.get("violation_count"), 0.0))) / 10.0

        values = np.array(
            [
                gap,
                last_improvement,
                1.0 if current_obj <= best_obj + 1e-9 else 0.0,
                stagnation,
                budget_progress,
                temperature_norm,
                ev_cv_ratio,
                charge_ratio,
                carbon_cost_share,
                quota_slack,
                violations,
            ],
            dtype=np.float32,
        )
        return np.clip(values, self.observation_space.low, self.observation_space.high).astype(np.float32)

    @staticmethod
    def _checked_response(response: dict[str, Any]) -> dict[str, Any]:
        if not response.get("ok", False):
            raise RuntimeError(f"DR-ALNS worker returned an error: {response}")
        return response


def _float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not np.isfinite(result):
        return float(default)
    return result


__all__ = ["SetpAlnsEnv"]
