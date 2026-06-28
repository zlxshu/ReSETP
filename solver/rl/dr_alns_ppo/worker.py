from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.construction import build_initial_solution
from setp_solver.search.evaluation import BIG_M, EvalBudget, EvaluationContext, fairness_context_for_solution
from setp_solver.search.alns_wouda import AlnsState, SearchPolicy, _make_operator_selector, _remove_customers, _solution_changed
from setp_solver.search.fleet import infer_fleet_limits
from setp_solver.search.winner_operators import (
    WinnerOperatorAction,
    WinnerOperatorSet,
    apply_winner_action,
    decode_winner_action,
    operator_base_id,
    winner_operator_module,
)
from setp_solver.solution import Solution

from .learned_destroy import LEARNED_DESTROY_CONTROL_MODE, LEARNED_DESTROY_ID, customer_feature_payload_json
from .solution_json import solution_to_json


OPERATOR_SET = WinnerOperatorSet.create()
DESTROY_IDS = [name for name, _ in OPERATOR_SET.destroy_ops]
REPAIR_IDS = [name for name, _ in OPERATOR_SET.repair_ops]
ALPHA_UCB_CHOICE = "alpha_ucb"
BLOCK_Q_RATIOS = (0.10, 0.16, 0.23, 0.30, 0.40)
BLOCK_THRESHOLD_RATIOS = (0.0, 0.0025, 0.0075, 0.02)
MAX_THRESHOLD_RATIO = 0.02
SEARCH_CONTROL_CHOICES = {"continue", "stop", "restart"}
RUNTIME_TRACE = {
    "worker_python_executable": sys.executable,
    "worker_python_version": sys.version,
    "worker_numpy_version": np.__version__,
}


@dataclass
class WorkerState:
    context: EvaluationContext
    current_solution: Solution
    current_obj: float
    current_summary: dict[str, Any]
    best_solution: Solution
    best_obj: float
    best_summary: dict[str, Any]
    rng: np.random.Generator
    destroy_counts: dict[str, int]
    repair_counts: dict[str, int]
    alpha_selector: Any | None = None
    step_index: int = 0
    stagnation_steps: int = 0
    last_improvement_step: int = 0


class JsonlWorker:
    def __init__(
        self,
        *,
        bundle_dir: str | Path,
        seed: int,
        max_evals: int,
        carbon_quota_kg: float,
        carbon_weight: float,
    ) -> None:
        if int(max_evals) < 0:
            raise ValueError(f"max_evals must be non-negative: {max_evals}")
        self.bundle = load_search_bundle(bundle_dir)
        self.seed = int(seed)
        self.max_evals = int(max_evals)
        self.carbon_quota_kg = float(carbon_quota_kg)
        self.carbon_weight = float(carbon_weight)
        self.state = self._new_state()

    def reset(self, request_id: Any) -> dict[str, Any]:
        self.state = self._new_state()
        return self._state_response(request_id, op="reset")

    def step(self, request_id: Any, action: dict[str, Any]) -> dict[str, Any]:
        return self._apply_single_action(request_id, action, op="step")

    def block_step(self, request_id: Any, action: dict[str, Any]) -> dict[str, Any]:
        if str(action.get("control_mode", "")) == LEARNED_DESTROY_CONTROL_MODE:
            return self._apply_learned_destroy_action(request_id, action, op="block_step")
        state = self.state
        self._ensure_budget_available()
        block_size = int(action.get("block_size", 128))
        if block_size < 1:
            raise ValueError(f"block_size must be >= 1: {block_size}")
        exploration_ratio = float(action.get("exploration_ratio", 0.0) or 0.0)
        if not math.isfinite(exploration_ratio) or exploration_ratio < 0.0 or exploration_ratio > 1.0:
            raise ValueError(f"exploration_ratio must be finite and in [0, 1]: {exploration_ratio!r}")
        search_control = str(action.get("search_control", "continue") or "continue")
        if search_control not in SEARCH_CONTROL_CHOICES:
            raise ValueError(f"unknown search_control: {search_control!r}")

        start_actual_evals = int(state.context.budget.count if state.context.budget else 0)
        start_candidate_scores = int(state.context.score_counts.get("candidate", 0))
        start_repair_delta = int(state.context.score_counts.get("repair_delta", 0))
        start_best_obj = float(state.best_obj)
        start_current_obj = float(state.current_obj)
        start_best_routes = len(state.best_solution.routes)
        start_current_routes = len(state.current_solution.routes)
        if search_control == "stop":
            return self._block_stop_response(
                request_id,
                action,
                start_actual_evals=start_actual_evals,
                start_candidate_scores=start_candidate_scores,
                start_repair_delta=start_repair_delta,
                start_best_obj=start_best_obj,
                start_current_obj=start_current_obj,
                start_best_routes=start_best_routes,
                start_current_routes=start_current_routes,
            )
        restart_improvement = 0.0
        if search_control == "restart":
            restart_improvement = max(0.0, float(state.current_obj) - float(state.best_obj))
            state.current_solution = state.best_solution
            state.current_obj = float(state.best_obj)
            state.current_summary = state.best_summary
            state.stagnation_steps = 0
        accepted_count = 0
        improved_current_count = 0
        improved_best_count = 0
        rejected_count = 0
        first_error = ""
        last_response: dict[str, Any] | None = None
        candidate_generator = str(action.get("candidate_generator", "default") or "default")
        block_candidates: list[Solution] | None = None

        for block_offset in range(block_size):
            budget = state.context.budget
            if budget is not None and budget.reached_target:
                break
            try:
                if candidate_generator != "default":
                    if block_candidates is None:
                        block_candidates = self._candidate_generator_solutions(
                            candidate_generator,
                            seed=self.seed + int(state.step_index),
                        )
                    response = self._apply_candidate_generator_action(
                        request_id,
                        action,
                        op="block_candidate_generator",
                        candidates=block_candidates,
                        candidate_offset=int(block_offset),
                    )
                    internal_action = {}
                else:
                    internal_action = self._resolve_block_internal_action(action)
                    response = self._apply_single_action(request_id, internal_action, op="block_internal")
            except RuntimeError as exc:
                first_error = str(exc)
                break
            last_response = response
            accepted_count += int(bool(response.get("accepted")))
            improved_current_count += int(bool(response.get("improved_current")))
            improved_best_count += int(bool(response.get("improved_best")))
            rejected_count += int(not bool(response.get("accepted")))
            if internal_action.get("_uses_alpha_ucb"):
                self._update_alpha_selector(internal_action, response)

        if last_response is None:
            raise RuntimeError(first_error or "block_step made no progress")

        end_best_obj = float(state.best_obj)
        end_current_obj = float(state.current_obj)
        end_best_routes = len(state.best_solution.routes)
        end_current_routes = len(state.current_solution.routes)
        actual_evals = int(state.context.budget.count if state.context.budget else 0)
        repair_delta_count = int(state.context.score_counts.get("repair_delta", 0))
        best_summary = state.best_summary
        block_iterations = accepted_count + rejected_count
        trace = dict(last_response.get("trace", {}) or {})
        trace.update(
            {
                **RUNTIME_TRACE,
                "op": "block_step",
                "block_size": int(block_size),
                "block_iterations": int(block_iterations),
                "block_evals_added": int(actual_evals - start_actual_evals),
                "block_candidate_scores_added": int(state.context.score_counts.get("candidate", 0) - start_candidate_scores),
                "block_repair_delta_added": int(repair_delta_count - start_repair_delta),
                "block_accepted_count": int(accepted_count),
                "block_rejected_count": int(rejected_count),
                "block_improved_current_count": int(improved_current_count),
                "block_improved_best_count": int(improved_best_count),
                "block_start_best_obj": float(start_best_obj),
                "block_end_best_obj": float(end_best_obj),
                "block_best_delta": float(end_best_obj - start_best_obj),
                "block_start_current_obj": float(start_current_obj),
                "block_end_current_obj": float(end_current_obj),
                "block_current_delta": float(end_current_obj - start_current_obj),
                "block_start_best_route_count": int(start_best_routes),
                "block_end_best_route_count": int(end_best_routes),
                "block_best_route_delta": int(end_best_routes - start_best_routes),
                "block_start_current_route_count": int(start_current_routes),
                "block_end_current_route_count": int(end_current_routes),
                "block_current_route_delta": int(end_current_routes - start_current_routes),
                "capacity_route_lower_bound": int(self._capacity_route_lower_bound()),
                "exploration_ratio": float(exploration_ratio),
                "block_requested_destroy_id": str(action.get("destroy_id", "")),
                "block_requested_repair_id": str(action.get("repair_id", "")),
                "block_requested_q_ratio": float(action.get("q_ratio", 0.0) or 0.0),
                "block_requested_threshold_ratio": float(action.get("threshold_ratio", 0.0) or 0.0),
                "block_requested_candidate_generator": str(candidate_generator),
                "block_candidate_generator_candidate_count": int(len(block_candidates or [])),
                "search_control": str(search_control),
                "search_control_restart_applied": int(search_control == "restart"),
                "search_control_restart_improvement": float(restart_improvement),
                "search_control_stop_requested": False,
                "control_mode": "block_ppo",
                "destroy_counts": dict(state.destroy_counts),
                "repair_counts": dict(state.repair_counts),
            }
        )
        return {
            "request_id": request_id,
            "ok": True,
            "accepted": bool(accepted_count > 0),
            "improved_current": bool(improved_current_count > 0),
            "improved_best": bool(improved_best_count > 0),
            "actual_evals": actual_evals,
            "candidate_scores": int(state.context.score_counts.get("candidate", 0)),
            "repair_delta_count": repair_delta_count,
            "current_obj": float(state.current_obj),
            "best_obj": float(state.best_obj),
            "candidate_obj": float(last_response.get("candidate_obj", state.current_obj)),
            "violation_count": int(best_summary["violation_count"]),
            "metrics": best_summary["metrics"],
            "solution": solution_to_json(state.best_solution),
            "trace": trace,
        }

    def _block_stop_response(
        self,
        request_id: Any,
        action: dict[str, Any],
        *,
        start_actual_evals: int,
        start_candidate_scores: int,
        start_repair_delta: int,
        start_best_obj: float,
        start_current_obj: float,
        start_best_routes: int,
        start_current_routes: int,
    ) -> dict[str, Any]:
        state = self.state
        actual_evals = int(state.context.budget.count if state.context.budget else 0)
        repair_delta_count = int(state.context.score_counts.get("repair_delta", 0))
        best_summary = state.best_summary
        trace = {
            **RUNTIME_TRACE,
            "op": "block_step",
            "block_size": int(action.get("block_size", 128)),
            "block_iterations": 0,
            "block_evals_added": int(actual_evals - int(start_actual_evals)),
            "block_candidate_scores_added": int(state.context.score_counts.get("candidate", 0) - int(start_candidate_scores)),
            "block_repair_delta_added": int(repair_delta_count - int(start_repair_delta)),
            "block_accepted_count": 0,
            "block_rejected_count": 0,
            "block_improved_current_count": 0,
            "block_improved_best_count": 0,
            "block_start_best_obj": float(start_best_obj),
            "block_end_best_obj": float(state.best_obj),
            "block_best_delta": float(state.best_obj - float(start_best_obj)),
            "block_start_current_obj": float(start_current_obj),
            "block_end_current_obj": float(state.current_obj),
            "block_current_delta": float(state.current_obj - float(start_current_obj)),
            "block_start_best_route_count": int(start_best_routes),
            "block_end_best_route_count": int(len(state.best_solution.routes)),
            "block_best_route_delta": int(len(state.best_solution.routes) - int(start_best_routes)),
            "block_start_current_route_count": int(start_current_routes),
            "block_end_current_route_count": int(len(state.current_solution.routes)),
            "block_current_route_delta": int(len(state.current_solution.routes) - int(start_current_routes)),
            "capacity_route_lower_bound": int(self._capacity_route_lower_bound()),
            "exploration_ratio": float(action.get("exploration_ratio", 0.0) or 0.0),
            "block_requested_destroy_id": str(action.get("destroy_id", "")),
            "block_requested_repair_id": str(action.get("repair_id", "")),
            "block_requested_q_ratio": float(action.get("q_ratio", 0.0) or 0.0),
            "block_requested_threshold_ratio": float(action.get("threshold_ratio", 0.0) or 0.0),
            "block_requested_candidate_generator": str(action.get("candidate_generator", "default") or "default"),
            "block_candidate_generator_candidate_count": 0,
            "search_control": "stop",
            "search_control_restart_applied": 0,
            "search_control_restart_improvement": 0.0,
            "search_control_stop_requested": True,
            "control_mode": "block_ppo",
            "destroy_counts": dict(state.destroy_counts),
            "repair_counts": dict(state.repair_counts),
        }
        return {
            "request_id": request_id,
            "ok": True,
            "accepted": False,
            "improved_current": False,
            "improved_best": False,
            "actual_evals": actual_evals,
            "candidate_scores": int(state.context.score_counts.get("candidate", 0)),
            "repair_delta_count": repair_delta_count,
            "current_obj": float(state.current_obj),
            "best_obj": float(state.best_obj),
            "candidate_obj": float(state.current_obj),
            "violation_count": int(best_summary["violation_count"]),
            "metrics": best_summary["metrics"],
            "solution": solution_to_json(state.best_solution),
            "trace": trace,
        }

    def _candidate_generator_solutions(self, variant_name: str, *, seed: int) -> list[Solution]:
        from .pilot14_candidate_generation_tools import generate_candidate_solutions

        limits = infer_fleet_limits(self.bundle.bundle_dir)
        policy = SearchPolicy(require_charging_signal=False, max_cv=limits.cv, max_ev=limits.ev)
        state = AlnsState(
            self.state.current_solution,
            self.state.context,
            objective_value=float(self.state.current_obj),
            policy=policy,
        )
        return generate_candidate_solutions(
            state=state,
            seed=int(seed),
            variant_name=str(variant_name),
            include_route_elimination=True,
            fleet_limits=limits,
        )

    def _apply_candidate_generator_action(
        self,
        request_id: Any,
        action: dict[str, Any],
        *,
        op: str,
        candidates: list[Solution],
        candidate_offset: int,
    ) -> dict[str, Any]:
        state = self.state
        self._ensure_budget_available()
        before_candidate_scores = int(state.context.score_counts.get("candidate", 0))
        old_current_obj = float(state.current_obj)
        old_best_obj = float(state.best_obj)
        if candidates:
            candidate = candidates[int(candidate_offset) % len(candidates)]
            candidate_obj, candidate_summary = self._score_solution(candidate, record_candidate=True)
            changed = bool(_solution_changed(state.current_solution, candidate))
        else:
            candidate = state.current_solution
            candidate_obj, candidate_summary = self._score_solution(candidate, record_candidate=True)
            changed = False

        threshold = float(self._threshold_ratio(action)) * max(float(state.current_obj), 0.0)
        delta = float(candidate_obj - old_current_obj)
        accepted = bool(changed and delta <= threshold)
        improved_current = bool(accepted and candidate_obj < old_current_obj)
        improved_best = bool(accepted and candidate_obj < old_best_obj)

        state.step_index += 1
        if accepted:
            state.current_solution = candidate
            state.current_obj = float(candidate_obj)
            state.current_summary = candidate_summary
        if improved_best:
            state.best_solution = candidate
            state.best_obj = float(candidate_obj)
            state.best_summary = candidate_summary
            state.stagnation_steps = 0
            state.last_improvement_step = state.step_index
        else:
            state.stagnation_steps += 1

        current_summary = state.current_summary
        reward_code = self._reward_code(accepted, improved_current, improved_best)
        actual_evals_added = int(state.context.score_counts.get("candidate", 0) - before_candidate_scores)
        return {
            "request_id": request_id,
            "ok": True,
            "accepted": bool(accepted),
            "improved_current": bool(improved_current),
            "improved_best": bool(improved_best),
            "actual_evals": int(state.context.budget.count if state.context.budget else 0),
            "candidate_scores": int(state.context.score_counts.get("candidate", 0)),
            "repair_delta_count": int(state.context.score_counts.get("repair_delta", 0)),
            "current_obj": float(state.current_obj),
            "best_obj": float(state.best_obj),
            "candidate_obj": float(candidate_obj),
            "violation_count": int(current_summary["violation_count"]),
            "metrics": current_summary["metrics"],
            "solution": solution_to_json(state.current_solution),
            "trace": {
                **RUNTIME_TRACE,
                "op": op,
                "step_index": int(state.step_index),
                "operator_base_id": operator_base_id,
                "winner_operator_module": winner_operator_module,
                "destroy_id": str(action.get("destroy_id", "")),
                "repair_id": str(action.get("repair_id", "")),
                "q_ratio": float(action.get("q_ratio", 0.0) or 0.0),
                "threshold": float(threshold),
                "threshold_ratio": float(self._threshold_ratio(action)),
                "control_mode": str(action.get("control_mode", "block_ppo")),
                "candidate_generator": str(action.get("candidate_generator", "default") or "default"),
                "candidate_generator_candidate_count": int(len(candidates)),
                "delta": float(delta),
                "changed": bool(changed),
                "stagnation_steps": int(state.stagnation_steps),
                "last_improvement_step": int(state.last_improvement_step),
                "repair_delta_added": 0,
                "actual_evals_added": int(actual_evals_added),
                "candidate_violation_count": int(candidate_summary["violation_count"]),
                "candidate_metrics": candidate_summary["metrics"],
                "destroy_counts": dict(state.destroy_counts),
                "repair_counts": dict(state.repair_counts),
                "reward_code": reward_code,
            },
        }

    def _apply_single_action(self, request_id: Any, action: dict[str, Any], *, op: str) -> dict[str, Any]:
        state = self.state
        self._ensure_budget_available()
        winner_action, threshold = self._decode_worker_action(action)
        before_repair_delta = int(state.context.score_counts.get("repair_delta", 0))
        result = apply_winner_action(
            state.current_solution,
            winner_action,
            state.context,
            rng=state.rng,
            operator_set=OPERATOR_SET,
            current_obj=state.current_obj,
            progress=self._progress(),
        )
        candidate = result["candidate_solution"]
        candidate_obj = float(result["candidate_obj"])
        candidate_summary = self._summarize_solution(candidate)
        winner_trace = dict(result.get("trace") or {})

        old_current_obj = state.current_obj
        old_best_obj = state.best_obj
        delta = candidate_obj - old_current_obj
        changed = bool(winner_trace.get("changed", True))
        accepted = bool(changed and delta <= float(threshold))
        improved_current = bool(accepted and candidate_obj < old_current_obj)
        improved_best = bool(accepted and candidate_obj < old_best_obj)

        state.step_index += 1
        if accepted:
            state.current_solution = candidate
            state.current_obj = candidate_obj
            state.current_summary = candidate_summary
        if improved_best:
            state.best_solution = candidate
            state.best_obj = candidate_obj
            state.best_summary = candidate_summary
            state.stagnation_steps = 0
            state.last_improvement_step = state.step_index
        else:
            state.stagnation_steps += 1

        reward_code = self._reward_code(accepted, improved_current, improved_best)
        self._inc(state.destroy_counts, winner_action.destroy_op_id)
        self._inc(state.repair_counts, winner_action.repair_op_id)

        current_summary = state.current_summary
        repair_delta_count = int(state.context.score_counts.get("repair_delta", 0))
        actual_evals_added = int(result.get("actual_evals_added", winner_trace.get("actual_evals_added", 0)))
        response = {
            "request_id": request_id,
            "ok": True,
            "accepted": bool(accepted),
            "improved_current": bool(improved_current),
            "improved_best": bool(improved_best),
            "actual_evals": int(state.context.budget.count if state.context.budget else 0),
            "candidate_scores": int(state.context.score_counts.get("candidate", 0)),
            "repair_delta_count": repair_delta_count,
            "current_obj": float(state.current_obj),
            "best_obj": float(state.best_obj),
            "candidate_obj": candidate_obj,
            "violation_count": int(current_summary["violation_count"]),
            "metrics": current_summary["metrics"],
            "solution": solution_to_json(state.current_solution),
            "trace": {
                **winner_trace,
                **RUNTIME_TRACE,
                "op": op,
                "step_index": int(state.step_index),
                "operator_base_id": operator_base_id,
                "winner_operator_module": winner_operator_module,
                "destroy_id": winner_action.destroy_op_id,
                "repair_id": winner_action.repair_op_id,
                "q_ratio": winner_action.remove_fraction,
                "threshold": float(threshold),
                "threshold_ratio": float(self._threshold_ratio(action)),
                "control_mode": str(action.get("control_mode", "ppo_full")),
                "delta": float(delta),
                "changed": bool(changed),
                "stagnation_steps": int(state.stagnation_steps),
                "last_improvement_step": int(state.last_improvement_step),
                "repair_delta_added": repair_delta_count - before_repair_delta,
                "actual_evals_added": actual_evals_added,
                "candidate_violation_count": int(candidate_summary["violation_count"]),
                "candidate_metrics": candidate_summary["metrics"],
                "destroy_counts": dict(state.destroy_counts),
                "repair_counts": dict(state.repair_counts),
                "reward_code": reward_code,
            },
        }
        return response

    def _apply_learned_destroy_action(self, request_id: Any, action: dict[str, Any], *, op: str) -> dict[str, Any]:
        state = self.state
        self._ensure_budget_available()
        block_size = int(action.get("block_size", 1))
        if block_size != 1:
            raise ValueError("learned_destroy requires block_size=1 so customer features are refreshed before each action")
        repair_id = str(action.get("repair_id", ""))
        if repair_id not in REPAIR_IDS:
            raise ValueError(f"unknown learned_destroy repair_id: {repair_id}")
        remove_customer_ids = tuple(str(value) for value in action.get("remove_customer_ids", ()) if str(value))
        if not remove_customer_ids:
            raise ValueError("learned_destroy requires remove_customer_ids")
        threshold_ratio = self._threshold_ratio(action)
        threshold = float(threshold_ratio) * max(float(state.current_obj), 0.0)
        old_current_obj = float(state.current_obj)
        old_best_obj = float(state.best_obj)
        start_actual_evals = int(state.context.budget.count if state.context.budget else 0)
        start_candidate_scores = int(state.context.score_counts.get("candidate", 0))
        start_repair_delta = int(state.context.score_counts.get("repair_delta", 0))
        start_best_routes = len(state.best_solution.routes)
        start_current_routes = len(state.current_solution.routes)

        previous_state = AlnsState(
            state.current_solution,
            state.context,
            objective_value=float(state.current_obj),
            policy=SearchPolicy(require_charging_signal=False),
        )
        destroyed = _remove_customers(previous_state, list(remove_customer_ids))
        repair_op = OPERATOR_SET.repair_callable(repair_id)
        candidate_state = repair_op(destroyed, state.rng)
        candidate = candidate_state.solution
        changed = bool(_solution_changed(state.current_solution, candidate))
        candidate_obj = float(candidate_state.objective())
        candidate_summary = self._summarize_solution(candidate)

        delta = float(candidate_obj - old_current_obj)
        accepted = bool(changed and delta <= float(threshold))
        improved_current = bool(accepted and candidate_obj < old_current_obj)
        improved_best = bool(
            accepted
            and int(candidate_summary["violation_count"]) == 0
            and candidate_obj < old_best_obj
        )

        state.step_index += 1
        if accepted:
            state.current_solution = candidate
            state.current_obj = candidate_obj
            state.current_summary = candidate_summary
        if improved_best:
            state.best_solution = candidate
            state.best_obj = candidate_obj
            state.best_summary = candidate_summary
            state.stagnation_steps = 0
            state.last_improvement_step = state.step_index
        else:
            state.stagnation_steps += 1

        self._inc(state.destroy_counts, LEARNED_DESTROY_ID)
        self._inc(state.repair_counts, repair_id)
        current_summary = state.current_summary
        actual_evals = int(state.context.budget.count if state.context.budget else 0)
        candidate_scores = int(state.context.score_counts.get("candidate", 0))
        repair_delta_count = int(state.context.score_counts.get("repair_delta", 0))
        reward_code = self._reward_code(accepted, improved_current, improved_best)
        block_iterations = 1
        customer_features = customer_feature_payload_json(
            state.current_solution,
            self.bundle.instance,
            self.bundle.carbon_profile,
        )
        trace = {
            **RUNTIME_TRACE,
            "op": op,
            "step_index": int(state.step_index),
            "operator_base_id": operator_base_id,
            "winner_operator_module": winner_operator_module,
            "destroy_id": LEARNED_DESTROY_ID,
            "repair_id": repair_id,
            "q_ratio": float(action.get("q_ratio", 0.0) or 0.0),
            "threshold": float(threshold),
            "threshold_ratio": float(threshold_ratio),
            "control_mode": LEARNED_DESTROY_CONTROL_MODE,
            "delta": float(delta),
            "changed": bool(changed),
            "accepted": bool(accepted),
            "stagnation_steps": int(state.stagnation_steps),
            "last_improvement_step": int(state.last_improvement_step),
            "repair_delta_added": int(repair_delta_count - start_repair_delta),
            "actual_evals_added": int(actual_evals - start_actual_evals),
            "candidate_violation_count": int(candidate_summary["violation_count"]),
            "candidate_metrics": candidate_summary["metrics"],
            "destroy_counts": dict(state.destroy_counts),
            "repair_counts": dict(state.repair_counts),
            "reward_code": reward_code,
            "learned_destroy_customer_ids": list(remove_customer_ids),
            "learned_destroy_selected_count": int(len(remove_customer_ids)),
            "learned_destroy_repair_id": repair_id,
            "learned_destroy_candidate_violation_count": int(candidate_summary["violation_count"]),
            "block_size": int(block_size),
            "block_iterations": block_iterations,
            "block_evals_added": int(actual_evals - start_actual_evals),
            "block_candidate_scores_added": int(candidate_scores - start_candidate_scores),
            "block_repair_delta_added": int(repair_delta_count - start_repair_delta),
            "block_accepted_count": int(accepted),
            "block_rejected_count": int(not accepted),
            "block_improved_current_count": int(improved_current),
            "block_improved_best_count": int(improved_best),
            "block_start_best_obj": float(old_best_obj),
            "block_end_best_obj": float(state.best_obj),
            "block_best_delta": float(state.best_obj - old_best_obj),
            "block_start_current_obj": float(old_current_obj),
            "block_end_current_obj": float(state.current_obj),
            "block_current_delta": float(state.current_obj - old_current_obj),
            "block_start_best_route_count": int(start_best_routes),
            "block_end_best_route_count": int(len(state.best_solution.routes)),
            "block_best_route_delta": int(len(state.best_solution.routes) - start_best_routes),
            "block_start_current_route_count": int(start_current_routes),
            "block_end_current_route_count": int(len(state.current_solution.routes)),
            "block_current_route_delta": int(len(state.current_solution.routes) - start_current_routes),
            "capacity_route_lower_bound": int(self._capacity_route_lower_bound()),
            "exploration_ratio": 0.0,
            "block_requested_destroy_id": LEARNED_DESTROY_ID,
            "block_requested_repair_id": repair_id,
            "block_requested_q_ratio": float(action.get("q_ratio", 0.0) or 0.0),
            "block_requested_threshold_ratio": float(threshold_ratio),
            "search_control": "continue",
            "search_control_restart_applied": 0,
            "search_control_restart_improvement": 0.0,
            "search_control_stop_requested": False,
        }
        return {
            "request_id": request_id,
            "ok": True,
            "accepted": bool(accepted),
            "improved_current": bool(improved_current),
            "improved_best": bool(improved_best),
            "actual_evals": actual_evals,
            "candidate_scores": candidate_scores,
            "repair_delta_count": repair_delta_count,
            "current_obj": float(state.current_obj),
            "best_obj": float(state.best_obj),
            "candidate_obj": float(candidate_obj),
            "violation_count": int(current_summary["violation_count"]),
            "metrics": current_summary["metrics"],
            "solution": solution_to_json(state.current_solution),
            "customer_features": customer_features,
            "per_customer_features": customer_features,
            "trace": trace,
        }

    def close(self, request_id: Any) -> dict[str, Any]:
        state = self.state
        return {
            "request_id": request_id,
            "ok": True,
            "op": "close",
            "actual_evals": int(state.context.budget.count if state.context.budget else 0),
            "candidate_scores": int(state.context.score_counts.get("candidate", 0)),
            "repair_delta_count": int(state.context.score_counts.get("repair_delta", 0)),
        }

    def error_response(self, request_id: Any, error: str) -> dict[str, Any]:
        context = getattr(getattr(self, "state", None), "context", None)
        budget = getattr(context, "budget", None)
        score_counts = getattr(context, "score_counts", {}) or {}
        return {
            "request_id": request_id,
            "ok": False,
            "error": str(error),
            "actual_evals": int(getattr(budget, "count", 0) or 0),
            "candidate_scores": int(score_counts.get("candidate", 0)),
            "repair_delta_count": int(score_counts.get("repair_delta", 0)),
        }

    def _new_state(self) -> WorkerState:
        budget = EvalBudget(
            limit=self.max_evals,
            target=self.max_evals,
        )
        context = EvaluationContext(
            self.bundle.instance,
            self.bundle.carbon_profile,
            budget=budget,
            carbon_quota_kg=self.carbon_quota_kg,
            carbon_weight=self.carbon_weight,
        )
        initial = build_initial_solution(
            self.bundle.instance,
            self.bundle.carbon_profile,
            introduce_ev=False,
            require_charging_signal=False,
        )
        initial_obj, initial_summary = self._score_solution(initial, context=context, record_candidate=False)
        return WorkerState(
            context=context,
            current_solution=initial,
            current_obj=initial_obj,
            current_summary=initial_summary,
            best_solution=initial,
            best_obj=initial_obj,
            best_summary=initial_summary,
            rng=np.random.default_rng(self.seed),
            destroy_counts={operator_id: 0 for operator_id in DESTROY_IDS},
            repair_counts={operator_id: 0 for operator_id in REPAIR_IDS},
        )

    def _state_response(self, request_id: Any, *, op: str) -> dict[str, Any]:
        state = self.state
        summary = state.current_summary
        customer_features = customer_feature_payload_json(
            state.current_solution,
            self.bundle.instance,
            self.bundle.carbon_profile,
        )
        return {
            "request_id": request_id,
            "ok": True,
            "op": op,
            "accepted": False,
            "improved_current": False,
            "improved_best": False,
            "actual_evals": int(state.context.budget.count if state.context.budget else 0),
            "candidate_scores": int(state.context.score_counts.get("candidate", 0)),
            "repair_delta_count": int(state.context.score_counts.get("repair_delta", 0)),
            "current_obj": float(state.current_obj),
            "best_obj": float(state.best_obj),
            "candidate_obj": float(state.current_obj),
            "violation_count": int(summary["violation_count"]),
            "metrics": summary["metrics"],
            "solution": solution_to_json(state.current_solution),
            "customer_features": customer_features,
            "per_customer_features": customer_features,
            "trace": {
                **RUNTIME_TRACE,
                "op": op,
                "operator_base_id": operator_base_id,
                "winner_operator_module": winner_operator_module,
                "step_index": int(state.step_index),
                "stagnation_steps": int(state.stagnation_steps),
                "last_improvement_step": int(state.last_improvement_step),
                "destroy_counts": dict(state.destroy_counts),
                "repair_counts": dict(state.repair_counts),
            },
        }

    def _score_solution(
        self,
        solution: Solution,
        *,
        context: EvaluationContext | None = None,
        record_candidate: bool,
    ) -> tuple[float, dict[str, Any]]:
        context = self.state.context if context is None else context
        if record_candidate:
            context.score_counts["candidate"] = int(context.score_counts.get("candidate", 0)) + 1
            if context.budget is not None:
                context.budget.record()
        prices = self._effective_prices()
        metrics = evaluate(
            solution,
            context.instance,
            context.carbon_profile,
            prices,
            carbon_quota_kg=context.carbon_quota_kg,
        )
        fairness_context = fairness_context_for_solution(solution, context, prices=prices)
        violations = check_solution(
            solution,
            context.instance,
            prices,
            fairness_context=fairness_context,
            fairness_enabled=context.fairness_enabled,
        )
        penalty = BIG_M * len(violations)
        objective = float(metrics["total_cost"]) + penalty
        context.score_breakdowns[id(solution)] = {
            "raw_cost": float(metrics["total_cost"]),
            "objective": float(objective),
            "penalty": float(penalty),
            "violation_count": int(len(violations)),
            "feasible": len(violations) == 0,
        }
        summary = {
            "violation_count": len(violations),
            "metrics": _jsonable(metrics),
        }
        return objective, summary

    def _summarize_solution(self, solution: Solution) -> dict[str, Any]:
        _, summary = self._score_solution(solution, record_candidate=False)
        return summary

    def _effective_prices(self) -> Any:
        if abs(self.carbon_weight - 1.0) <= 1e-12:
            return DEFAULT_PRICES
        return replace(DEFAULT_PRICES, carbon_price=DEFAULT_PRICES.carbon_price * self.carbon_weight)

    def _ensure_budget_available(self) -> None:
        budget = self.state.context.budget
        if budget is not None and budget.reached_target:
            raise RuntimeError(f"EvalBudget target reached: {budget.count} >= {budget.target_count}")

    def _decode_worker_action(self, action: dict[str, Any]) -> tuple[WinnerOperatorAction, float]:
        destroy_id = str(action["destroy_id"])
        repair_id = str(action["repair_id"])
        if destroy_id not in DESTROY_IDS:
            raise ValueError(f"unknown destroy_id: {destroy_id}")
        if repair_id not in REPAIR_IDS:
            raise ValueError(f"unknown repair_id: {repair_id}")
        mode = str(action.get("control_mode", "ppo_full"))
        raw = tuple(int(value) for value in action.get("raw", ()))
        if mode == "ppo_full":
            if len(raw) != 4:
                raise ValueError(f"ppo_full action raw must have 4 components: {raw!r}")
            customer_count = self._current_customer_count()
            winner_action = decode_winner_action(
                list(raw),
                OPERATOR_SET,
                customer_count=customer_count,
            )
        elif mode == "reduced_full":
            if len(raw) != 4:
                raise ValueError(f"reduced_full action raw must have 4 components: {raw!r}")
            winner_action = WinnerOperatorAction(
                destroy_op_id=destroy_id,
                repair_op_id=repair_id,
                remove_count_q=None,
                accept_param=0.0,
                temperature=0.0,
                remove_fraction=float(action.get("q_ratio", 0.10)),
                raw_action=(raw[0], raw[1], raw[2], raw[3]),
            )
        elif mode in {"operator_only", "kernel_default"}:
            if len(raw) != 2:
                raise ValueError(f"{mode} action raw must have 2 components: {raw!r}")
            winner_action = WinnerOperatorAction(
                destroy_op_id=destroy_id,
                repair_op_id=repair_id,
                remove_count_q=None,
                accept_param=0.0,
                temperature=0.0,
                remove_fraction=None,
                raw_action=(raw[0], raw[1], -1, 0),
            )
        elif mode == "block_ppo":
            if len(raw) not in {5, 6, 7}:
                raise ValueError(f"block_ppo action raw must have 5, 6, or 7 components: {raw!r}")
            winner_action = WinnerOperatorAction(
                destroy_op_id=destroy_id,
                repair_op_id=repair_id,
                remove_count_q=None,
                accept_param=0.0,
                temperature=0.0,
                remove_fraction=float(action.get("q_ratio", 0.10)),
                raw_action=(raw[0], raw[1], raw[2], raw[3], raw[4]),
            )
        else:
            raise ValueError(f"unknown control_mode: {mode}")
        threshold_ratio = self._threshold_ratio(action)
        threshold = float(threshold_ratio) * max(float(self.state.current_obj), 0.0)
        if not math.isfinite(threshold) or threshold < 0.0:
            raise ValueError(f"threshold must be finite and non-negative: {threshold!r}")
        return winner_action, threshold

    @staticmethod
    def _threshold_ratio(action: dict[str, Any]) -> float:
        value = float(action.get("threshold_ratio", 0.0) or 0.0)
        if not math.isfinite(value) or value < 0.0 or value > MAX_THRESHOLD_RATIO + 1e-12:
            raise ValueError(f"threshold_ratio must be finite and in [0, {MAX_THRESHOLD_RATIO}]: {value!r}")
        return value

    def _current_customer_count(self) -> int:
        customer_ids = {
            node.node_id
            for node in self.bundle.instance.nodes
            if node.node_type.lower() == "c"
        }
        return sum(
            1
            for route in self.state.current_solution.routes
            for node_id in route.node_sequence
            if node_id in customer_ids
        )

    def _resolve_block_internal_action(self, action: dict[str, Any]) -> dict[str, Any]:
        requested_destroy = str(action.get("destroy_id", ""))
        requested_repair = str(action.get("repair_id", ""))
        exploration_ratio = float(action.get("exploration_ratio", 0.0) or 0.0)
        uses_alpha = requested_destroy == ALPHA_UCB_CHOICE or requested_repair == ALPHA_UCB_CHOICE
        explore = bool(exploration_ratio > 0.0 and self.state.rng.random() < exploration_ratio)

        destroy_idx: int | None = None
        repair_idx: int | None = None
        if uses_alpha and not explore:
            selector = self._alpha_selector()
            selected_destroy, selected_repair = selector(self.state.rng, None, None)
            destroy_idx = int(selected_destroy)
            repair_idx = int(selected_repair)
        if explore:
            destroy_idx = int(self.state.rng.integers(0, len(DESTROY_IDS)))
            repair_idx = int(self.state.rng.integers(0, len(REPAIR_IDS)))

        destroy_id = DESTROY_IDS[destroy_idx] if destroy_idx is not None else requested_destroy
        repair_id = REPAIR_IDS[repair_idx] if repair_idx is not None else requested_repair
        if destroy_id not in DESTROY_IDS:
            raise ValueError(f"unknown block destroy_id: {destroy_id}")
        if repair_id not in REPAIR_IDS:
            raise ValueError(f"unknown block repair_id: {repair_id}")
        if destroy_idx is None:
            destroy_idx = DESTROY_IDS.index(destroy_id)
        if repair_idx is None:
            repair_idx = REPAIR_IDS.index(repair_id)
        q_ratio = float(action.get("q_ratio", BLOCK_Q_RATIOS[0]) or BLOCK_Q_RATIOS[0])
        if q_ratio not in BLOCK_Q_RATIOS:
            nearest = min(BLOCK_Q_RATIOS, key=lambda value: abs(float(value) - q_ratio))
            q_ratio = float(nearest)
        threshold_ratio = float(action.get("threshold_ratio", 0.0) or 0.0)
        return {
            "destroy_id": destroy_id,
            "repair_id": repair_id,
            "q_ratio": q_ratio,
            "threshold_ratio": threshold_ratio,
            "raw": tuple(int(value) for value in action.get("raw", (0, 0, 0, 0, 0))),
            "control_mode": "block_ppo",
            "candidate_generator": str(action.get("candidate_generator", "default") or "default"),
            "_alpha_destroy_idx": destroy_idx,
            "_alpha_repair_idx": repair_idx,
            "_uses_alpha_ucb": uses_alpha and not explore,
        }

    def _alpha_selector(self) -> Any:
        if self.state.alpha_selector is None:
            self.state.alpha_selector = _make_operator_selector(len(DESTROY_IDS), len(REPAIR_IDS))
        return self.state.alpha_selector

    def _update_alpha_selector(self, action: dict[str, Any], response: dict[str, Any]) -> None:
        selector = self._alpha_selector()
        selector.update(
            None,
            int(action["_alpha_destroy_idx"]),
            int(action["_alpha_repair_idx"]),
            self._outcome_index(response),
        )

    @staticmethod
    def _outcome_index(response: dict[str, Any]) -> int:
        if response.get("improved_best"):
            return 0
        if response.get("improved_current"):
            return 1
        if response.get("accepted"):
            return 2
        return 3

    def _capacity_route_lower_bound(self) -> int:
        total_demand = sum(
            max(0.0, float(node.demand))
            for node in self.bundle.instance.nodes
            if node.node_type.lower() == "c"
        )
        capacity = float(self._effective_prices().Q_capacity)
        if capacity <= 0.0:
            return 0
        return int(math.ceil(total_demand / capacity))

    def _progress(self) -> float:
        budget = self.state.context.budget
        if budget is None or budget.target_count <= 0:
            return 0.0
        return min(1.0, float(budget.count) / float(budget.target_count))

    @staticmethod
    def _reward_code(accepted: bool, improved_current: bool, improved_best: bool) -> str:
        if improved_best:
            return "global_best"
        if improved_current:
            return "current_improved"
        if accepted:
            return "accepted_worse"
        return "rejected"

    @staticmethod
    def _inc(counts: dict[str, int], key: str) -> None:
        counts[key] = int(counts.get(key, 0)) + 1


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if math.isfinite(value):
            return float(value)
        return str(value)
    return value


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JSONL DR-ALNS worker")
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--carbon-quota-kg", default=0.0, type=float)
    parser.add_argument("--carbon-weight", default=1.0, type=float)
    parser.add_argument("--max-evals", required=True, type=int)
    return parser.parse_args(argv)


def _dispatch(worker: JsonlWorker, request: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    request_id = request.get("request_id")
    op = str(request.get("op", ""))
    if op == "reset":
        return worker.reset(request_id), False
    if op == "step":
        action = request.get("action")
        if not isinstance(action, dict):
            raise ValueError("step request requires an action object")
        return worker.step(request_id, action), False
    if op == "block_step":
        action = request.get("action")
        if not isinstance(action, dict):
            raise ValueError("block_step request requires an action object")
        return worker.block_step(request_id, action), False
    if op == "close":
        return worker.close(request_id), True
    raise ValueError(f"unknown op: {op}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    worker = JsonlWorker(
        bundle_dir=args.bundle_dir,
        seed=args.seed,
        max_evals=args.max_evals,
        carbon_quota_kg=args.carbon_quota_kg,
        carbon_weight=args.carbon_weight,
    )
    for line in sys.stdin:
        request_id: Any = None
        try:
            request = json.loads(line, parse_constant=_reject_json_constant)
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            request_id = request.get("request_id")
            response, should_close = _dispatch(worker, request)
        except Exception as exc:
            response = worker.error_response(request_id, str(exc))
            should_close = False
        sys.stdout.write(json.dumps(response, separators=(",", ":"), allow_nan=False) + "\n")
        sys.stdout.flush()
        if should_close:
            break
    return 0


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


if __name__ == "__main__":
    raise SystemExit(main())
