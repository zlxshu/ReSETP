from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .action_space import BLOCK_ACTION_NVECS, decode_block_action
from .worker_client import WorkerClient


BLOCK_OBSERVATION_SIZE = 19


class BlockAlnsEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(
        self,
        bundle_dir: str,
        seed: int = 1,
        eval_budget: int = 16000,
        block_size: int = 128,
    ) -> None:
        super().__init__()
        if int(block_size) < 1:
            raise ValueError("block_size must be >= 1")
        self.bundle_dir = bundle_dir
        self.seed_value = int(seed)
        self.eval_budget = int(eval_budget)
        self.block_size = int(block_size)
        self.action_space = spaces.MultiDiscrete(list(BLOCK_ACTION_NVECS))
        self.observation_space = spaces.Box(
            low=-10.0,
            high=10.0,
            shape=(BLOCK_OBSERVATION_SIZE,),
            dtype=np.float32,
        )
        self.client = WorkerClient(bundle_dir, seed=self.seed_value, max_evals=self.eval_budget)
        self.last_response: dict[str, Any] | None = None
        self.initial_obj: float | None = None
        self.initial_route_count: int | None = None

    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        _ = options
        super().reset(seed=seed)
        if seed is not None and int(seed) != self.seed_value:
            self.client.close()
            self.seed_value = int(seed)
            self.client = WorkerClient(self.bundle_dir, seed=self.seed_value, max_evals=self.eval_budget)
        self.last_response = self._checked_response(self.client.reset())
        self.initial_obj = _float(self.last_response.get("best_obj"), 0.0)
        self.initial_route_count = _route_count(self.last_response)
        return self._obs(self.last_response), {"actual_evals": int(self.last_response.get("actual_evals", 0))}

    def step(self, action):
        decoded = decode_block_action(action, block_size=self.block_size)
        response = self._checked_response(self.client.block_step(decoded))
        self.last_response = response
        terminated = bool(int(response.get("actual_evals", 0)) >= self.eval_budget)
        reward = self._reward(response, terminated=terminated)
        truncated = False
        return self._obs(response), reward, terminated, truncated, response

    def close(self) -> None:
        self.client.close()
        super().close()

    def _reward(self, response: dict[str, Any], *, terminated: bool) -> float:
        trace = response.get("trace", {}) or {}
        start_best = _float(trace.get("block_start_best_obj"), response.get("best_obj", 0.0))
        end_best = _float(trace.get("block_end_best_obj"), response.get("best_obj", start_best))
        best_gain = max(0.0, (start_best - end_best) / max(abs(start_best), 1.0))

        start_current = _float(trace.get("block_start_current_obj"), response.get("current_obj", 0.0))
        end_current = _float(trace.get("block_end_current_obj"), response.get("current_obj", start_current))
        current_gain = max(0.0, (start_current - end_current) / max(abs(start_current), 1.0))

        route_delta = int(_float(trace.get("block_best_route_delta"), 0.0))
        route_gain = max(0, -route_delta)
        route_penalty = max(0, route_delta)
        best_hits = int(_float(trace.get("block_improved_best_count"), 0.0))
        iterations = max(1.0, _float(trace.get("block_iterations"), 1.0))
        no_best_penalty = 0.02 if best_hits == 0 else 0.0

        reward = 100.0 * best_gain + 10.0 * current_gain + 1.5 * route_gain - 0.5 * route_penalty
        reward += min(2.0, best_hits / iterations)
        reward -= no_best_penalty
        if int(response.get("violation_count", 0)) != 0:
            reward -= 10.0
        if terminated and self.initial_obj is not None:
            final_gain = max(0.0, (float(self.initial_obj) - end_best) / max(abs(float(self.initial_obj)), 1.0))
            reward += min(10.0, 100.0 * final_gain)
        return float(reward)

    def _obs(self, response: dict[str, Any]) -> np.ndarray:
        metrics = response.get("metrics", {}) or {}
        trace = response.get("trace", {}) or {}
        current_obj = _float(response.get("current_obj"), 0.0)
        best_obj = _float(response.get("best_obj"), current_obj)
        gap = (current_obj - best_obj) / max(abs(best_obj), 1.0)
        budget_progress = _float(response.get("actual_evals"), 0.0) / max(float(self.eval_budget), 1.0)

        block_iterations = max(1.0, _float(trace.get("block_iterations"), 1.0))
        accepted_rate = _float(trace.get("block_accepted_count"), 0.0) / block_iterations
        improved_current_rate = _float(trace.get("block_improved_current_count"), 0.0) / block_iterations
        improved_best_rate = _float(trace.get("block_improved_best_count"), 0.0) / block_iterations
        rejected_rate = _float(trace.get("block_rejected_count"), 0.0) / block_iterations

        best_delta = -_float(trace.get("block_best_delta"), 0.0) / max(abs(_float(trace.get("block_start_best_obj"), best_obj)), 1.0)
        current_delta = -_float(trace.get("block_current_delta"), 0.0) / max(abs(_float(trace.get("block_start_current_obj"), current_obj)), 1.0)

        route_count = _route_count(response)
        best_route_count = int(_float(trace.get("block_end_best_route_count"), route_count))
        lower_bound = int(_float(trace.get("capacity_route_lower_bound"), 0.0))
        route_gap = (best_route_count - lower_bound) / max(float(best_route_count), 1.0)
        route_delta = _float(trace.get("block_best_route_delta"), 0.0) / max(float(max(best_route_count, 1)), 1.0)

        cv_routes = _float(metrics.get("n_veh_cv"), 0.0)
        ev_routes = _float(metrics.get("n_veh_ev"), 0.0)
        ev_share = ev_routes / max(ev_routes + cv_routes, 1.0)
        charge_count = len((response.get("solution", {}) or {}).get("charging_actions", []) or [])
        charge_ratio = float(charge_count) / max(float(route_count), 1.0)

        total_cost = _float(metrics.get("total_cost"), 0.0)
        fix_share = abs(_float(metrics.get("cost_fix"), 0.0)) / max(abs(total_cost), 1.0)
        km_share = abs(_float(metrics.get("cost_km"), 0.0)) / max(abs(total_cost), 1.0)

        values = np.array(
            [
                gap,
                budget_progress,
                best_delta,
                current_delta,
                accepted_rate,
                improved_current_rate,
                improved_best_rate,
                rejected_rate,
                route_gap,
                route_delta,
                ev_share,
                charge_ratio,
                fix_share,
                km_share,
                _float(trace.get("block_requested_q_ratio"), 0.0),
                _float(trace.get("block_requested_threshold_ratio"), 0.0) / 0.02,
                _float(trace.get("exploration_ratio"), 0.0),
                _float(trace.get("stagnation_steps"), 0.0) / max(float(self.eval_budget), 1.0),
                min(1.0, max(0.0, _float(response.get("violation_count"), 0.0))),
            ],
            dtype=np.float32,
        )
        return np.clip(values, self.observation_space.low, self.observation_space.high).astype(np.float32)

    @staticmethod
    def _checked_response(response: dict[str, Any]) -> dict[str, Any]:
        if not response.get("ok", False):
            raise RuntimeError(f"DR-ALNS block worker returned an error: {response}")
        return response


def _route_count(response: dict[str, Any]) -> int:
    solution = response.get("solution", {}) if isinstance(response, dict) else {}
    routes = solution.get("routes", []) if isinstance(solution, dict) else []
    return len(routes) if isinstance(routes, list) else 0


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not np.isfinite(result):
        return float(default)
    return result


__all__ = ["BLOCK_OBSERVATION_SIZE", "BlockAlnsEnv"]
