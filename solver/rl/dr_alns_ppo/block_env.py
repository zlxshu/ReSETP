from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .action_space import (
    ALPHA_UCB_CHOICE,
    BLOCK_ACTION_NVECS,
    BLOCK_CANDIDATE_ACTION_NVECS,
    BLOCK_DESTROY_IDS,
    BLOCK_Q_RATIOS,
    BLOCK_REPAIR_IDS,
    BLOCK_SEARCH_CONTROL_CHOICES,
    decode_block_action,
    block_action_nvecs,
)
from .worker_client import WorkerClient


BLOCK_OBSERVATION_SIZE = 24
CURRICULUM_PHASES = ("route", "energy", "carbon", "dynamic")


class BlockAlnsEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(
        self,
        bundle_dir: str,
        seed: int = 1,
        eval_budget: int = 16000,
        block_size: int = 128,
        curriculum_phase: str = "route",
        meta_mode: bool = False,
        candidate_generator_mode: bool = False,
        search_control_mode: bool = False,
    ) -> None:
        super().__init__()
        if int(block_size) < 1:
            raise ValueError("block_size must be >= 1")
        if curriculum_phase not in CURRICULUM_PHASES:
            raise ValueError(f"unknown curriculum_phase: {curriculum_phase}")
        self.bundle_dir = bundle_dir
        self.seed_value = int(seed)
        self.eval_budget = int(eval_budget)
        self.block_size = int(block_size)
        self.curriculum_phase = str(curriculum_phase)
        self.meta_mode = bool(meta_mode)
        self.candidate_generator_mode = bool(candidate_generator_mode)
        self.search_control_mode = bool(search_control_mode)
        self.action_nvecs = _action_nvecs(self.candidate_generator_mode, self.search_control_mode)
        self.action_space = spaces.MultiDiscrete(list(self.action_nvecs))
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
        return self._obs(self.last_response), {
            "actual_evals": int(self.last_response.get("actual_evals", 0)),
            "action_mask": self._action_mask(self.last_response),
        }

    def step(self, action):
        decoded = decode_block_action(
            action,
            block_size=self.block_size,
            candidate_generator_mode=bool(getattr(self, "candidate_generator_mode", False)),
            search_control_mode=bool(getattr(self, "search_control_mode", False)),
        )
        response = self._checked_response(self.client.block_step(decoded))
        self.last_response = response
        trace = response.get("trace", {}) or {}
        terminated = bool(int(response.get("actual_evals", 0)) >= self.eval_budget or trace.get("search_control_stop_requested"))
        reward = self._reward(response, terminated=terminated)
        response["curriculum_phase"] = self.curriculum_phase
        response["action_mask"] = self._action_mask(response)
        truncated = False
        return self._obs(response), reward, terminated, truncated, response

    def _action_mask(self, response: dict[str, Any]) -> list[list[bool]]:
        action_nvecs = _action_nvecs(
            bool(getattr(self, "candidate_generator_mode", False)),
            bool(getattr(self, "search_control_mode", False)),
        )
        masks = [[True for _ in range(int(n))] for n in action_nvecs]
        if bool(getattr(self, "meta_mode", False)):
            _force_single_action(masks[0], BLOCK_DESTROY_IDS.index(ALPHA_UCB_CHOICE))
            _force_single_action(masks[1], BLOCK_REPAIR_IDS.index(ALPHA_UCB_CHOICE))
            return masks

        metrics = response.get("metrics", {}) or {}
        trace = response.get("trace", {}) or {}

        cv_routes = _float(metrics.get("n_veh_cv"), 0.0)
        ev_routes = _float(metrics.get("n_veh_ev"), 0.0)
        total_routes = cv_routes + ev_routes
        ev_share = ev_routes / max(total_routes, 1.0)
        if total_routes > 0 and (ev_share <= 1e-9 or ev_share >= 1.0 - 1e-9):
            _mask_named(masks[0], BLOCK_DESTROY_IDS, {"vehicle_type_swap"})

        best_route_count = int(_float(trace.get("block_end_best_route_count"), _route_count(response)))
        lower_bound = int(_float(trace.get("capacity_route_lower_bound"), 0.0))
        route_gap = (best_route_count - lower_bound) / max(float(best_route_count), 1.0)
        route_delta = _float(trace.get("block_best_route_delta"), 0.0)
        route_delta_no_improve = "block_best_route_delta" in trace and route_delta >= 0.0
        if route_gap <= 0.0 or route_delta_no_improve:
            _mask_named(masks[0], BLOCK_DESTROY_IDS, {"whole_route_removal", "route_segment_removal"})

        actual_evals = _float(response.get("actual_evals"), 0.0)
        budget_progress = actual_evals / max(float(self.eval_budget), 1.0)
        block_iterations = max(1.0, _float(trace.get("block_iterations"), 1.0))
        rejected_rate = _float(trace.get("block_rejected_count"), 0.0) / block_iterations
        best_hits = _float(trace.get("block_improved_best_count"), 0.0)
        current_hits = _float(trace.get("block_improved_current_count"), 0.0)
        stagnation = _float(trace.get("stagnation_steps"), 0.0) / max(float(self.eval_budget), 1.0)
        if (budget_progress >= 0.75 or rejected_rate >= 0.80 or stagnation >= 0.25) and best_hits + current_hits <= 0.0:
            for idx, q_ratio in enumerate(BLOCK_Q_RATIOS):
                if float(q_ratio) >= 0.30:
                    masks[2][idx] = False

        _ensure_head_has_action(masks[0], BLOCK_DESTROY_IDS, [BLOCK_DESTROY_IDS.index(ALPHA_UCB_CHOICE), 0])
        _ensure_head_has_action(masks[1], BLOCK_REPAIR_IDS, [BLOCK_REPAIR_IDS.index(ALPHA_UCB_CHOICE), 0])
        _ensure_head_has_action(masks[2], tuple(str(v) for v in BLOCK_Q_RATIOS), [0])
        _ensure_head_has_action(masks[3], tuple(str(v) for v in range(action_nvecs[3])), [0])
        _ensure_head_has_action(masks[4], tuple(str(v) for v in range(action_nvecs[4])), [0])
        head_idx = len(BLOCK_ACTION_NVECS)
        if bool(getattr(self, "candidate_generator_mode", False)):
            _ensure_head_has_action(masks[head_idx], tuple(str(v) for v in range(action_nvecs[head_idx])), [0])
            head_idx += 1
        if bool(getattr(self, "search_control_mode", False)):
            _ensure_head_has_action(masks[head_idx], BLOCK_SEARCH_CONTROL_CHOICES, [0])
            stop_idx = BLOCK_SEARCH_CONTROL_CHOICES.index("stop")
            if budget_progress < 0.75 and stagnation < 0.25:
                masks[head_idx][stop_idx] = False
        return masks

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

        route_reward = 100.0 * best_gain + 10.0 * current_gain + 1.5 * route_gain - 0.5 * route_penalty
        route_reward += min(2.0, best_hits / iterations)
        route_reward -= no_best_penalty
        reward = route_reward
        requested_candidate_generator = str(trace.get("block_requested_candidate_generator", "default") or "default")
        candidate_count = _float(trace.get("block_candidate_generator_candidate_count"), 0.0)
        candidate_reward = 0.0
        if requested_candidate_generator != "default":
            candidate_reward += 0.05 * min(1.0, candidate_count / 4.0)
            candidate_reward += 0.50 * min(1.0, (best_hits + _float(trace.get("block_improved_current_count"), 0.0)) / iterations)
            if candidate_count <= 0.0:
                candidate_reward -= 0.25
        search_control = str(trace.get("search_control", "continue") or "continue")
        search_reward = 0.0
        if search_control == "restart":
            restart_gain = _float(trace.get("search_control_restart_improvement"), 0.0) / max(abs(start_current), 1.0)
            search_reward += min(0.50, 25.0 * restart_gain)
            if restart_gain <= 0.0:
                search_reward -= 0.05
        elif search_control == "stop":
            budget_progress = _float(response.get("actual_evals"), 0.0) / max(float(self.eval_budget), 1.0)
            search_reward += 0.10 if budget_progress >= 0.80 and best_hits == 0 else -0.25
        reward += candidate_reward + search_reward

        components: dict[str, float | str] = {
            "route": float(route_reward),
            "candidate": float(candidate_reward),
            "search_control": float(search_reward),
            "energy": 0.0,
            "carbon": 0.0,
            "dynamic": 0.0,
            "fallback": "",
        }
        phase = self.curriculum_phase
        if phase in {"energy", "carbon", "dynamic"}:
            charge_ratio = _charge_ratio(response)
            requested_q = _float(trace.get("block_requested_q_ratio"), 0.0)
            requested_threshold = _float(trace.get("block_requested_threshold_ratio"), 0.0)
            block_improvement_rate = (best_hits + _float(trace.get("block_improved_current_count"), 0.0)) / iterations
            energy_reward = 0.75 * min(1.0, charge_ratio) * block_improvement_rate
            energy_reward += 0.25 * max(0.0, 0.40 - requested_q)
            energy_reward -= 0.10 * min(1.0, requested_threshold / 0.02) if requested_threshold > 0.0 else 0.0
            components["energy"] = float(energy_reward)
            reward += energy_reward
        if phase in {"carbon", "dynamic"}:
            metrics = response.get("metrics", {}) or {}
            carbon_reward = _carbon_reward(metrics, trace)
            if carbon_reward is None:
                carbon_reward = 25.0 * best_gain
                components["fallback"] = "no_independent_carbon_or_fairness_signal"
            components["carbon"] = float(carbon_reward)
            reward += float(carbon_reward)
        if phase == "dynamic":
            dynamic_reward = _dynamic_reward(response)
            if dynamic_reward is None:
                dynamic_reward = 10.0 * best_gain
                fallback = str(components.get("fallback") or "")
                components["fallback"] = ";".join(part for part in (fallback, "no_dynamic_signal") if part)
            components["dynamic"] = float(dynamic_reward)
            reward += float(dynamic_reward)
        if int(response.get("violation_count", 0)) != 0:
            reward -= 10.0
            components["violation_penalty"] = -10.0
        if terminated and self.initial_obj is not None:
            final_gain = max(0.0, (float(self.initial_obj) - end_best) / max(abs(float(self.initial_obj)), 1.0))
            terminal_reward = min(10.0, 100.0 * final_gain)
            reward += terminal_reward
            components["terminal"] = float(terminal_reward)
        response["reward_components"] = components
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
                _scale_feature(str(getattr(self, "bundle_dir", ""))),
                _phase_feature(str(getattr(self, "curriculum_phase", "route"))),
                min(1.0, _float(trace.get("block_candidate_generator_candidate_count"), 0.0) / 16.0),
                0.0 if str(trace.get("block_requested_candidate_generator", "default") or "default") == "default" else 1.0,
                0.0 if str(trace.get("search_control", "continue") or "continue") == "continue" else 1.0,
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


def _charge_ratio(response: dict[str, Any]) -> float:
    route_count = max(float(_route_count(response)), 1.0)
    solution = response.get("solution", {}) if isinstance(response, dict) else {}
    actions = solution.get("charging_actions", []) if isinstance(solution, dict) else []
    return float(len(actions) if isinstance(actions, list) else 0) / route_count


def _action_nvecs(candidate_generator_mode: bool, search_control_mode: bool = False) -> tuple[int, ...]:
    return block_action_nvecs(
        candidate_generator_mode=bool(candidate_generator_mode),
        search_control_mode=bool(search_control_mode),
    )


def _carbon_reward(metrics: dict[str, Any], trace: dict[str, Any]) -> float | None:
    if not any(key in metrics for key in ("cost_carbon", "E_total", "electricity_kwh")):
        return None
    start_best = abs(_float(trace.get("block_start_best_obj"), 0.0))
    carbon_cost = abs(_float(metrics.get("cost_carbon"), 0.0))
    energy_total = abs(_float(metrics.get("E_total"), 0.0))
    electricity = abs(_float(metrics.get("electricity_kwh"), 0.0))
    denom = max(start_best, 1.0)
    return -0.25 * min(2.0, carbon_cost / denom) - 0.02 * min(10.0, (energy_total + electricity) / 1000.0)


def _dynamic_reward(response: dict[str, Any]) -> float | None:
    trace = response.get("trace", {}) or {}
    metrics = response.get("metrics", {}) or {}
    keys = set(trace) | set(metrics) | set(response)
    if not any("dynamic" in str(key).lower() or "rolling" in str(key).lower() for key in keys):
        return None
    return 0.0


def _scale_feature(bundle_dir: str) -> float:
    lowered = str(bundle_dir).lower()
    for customers in (200, 150, 100, 75, 50):
        if f"{customers}c" in lowered:
            return min(1.0, float(customers) / 200.0)
    return 0.0


def _phase_feature(phase: str) -> float:
    try:
        return float(CURRICULUM_PHASES.index(str(phase))) / max(float(len(CURRICULUM_PHASES) - 1), 1.0)
    except ValueError:
        return 0.0


def _mask_named(mask: list[bool], names: tuple[str, ...], blocked: set[str]) -> None:
    for idx, name in enumerate(names):
        if name in blocked:
            mask[idx] = False


def _force_single_action(mask: list[bool], forced_idx: int) -> None:
    for idx in range(len(mask)):
        mask[idx] = idx == int(forced_idx)


def _ensure_head_has_action(mask: list[bool], _names: tuple[str, ...], fallback_indices: list[int]) -> None:
    if any(mask):
        return
    for idx in fallback_indices:
        if 0 <= int(idx) < len(mask):
            mask[int(idx)] = True
            return
    mask[0] = True


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not np.isfinite(result):
        return float(default)
    return result


__all__ = ["BLOCK_OBSERVATION_SIZE", "CURRICULUM_PHASES", "BlockAlnsEnv"]
