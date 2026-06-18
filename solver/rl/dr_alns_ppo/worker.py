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
from setp_solver.search.winner_operators import (
    WinnerOperatorAction,
    WinnerOperatorSet,
    apply_winner_action,
    decode_winner_action,
    operator_base_id,
    winner_operator_module,
)
from setp_solver.solution import Solution

from .solution_json import solution_to_json


OPERATOR_SET = WinnerOperatorSet.create()
DESTROY_IDS = [name for name, _ in OPERATOR_SET.destroy_ops]
REPAIR_IDS = [name for name, _ in OPERATOR_SET.repair_ops]
MAX_THRESHOLD_RATIO = 0.02
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
                "op": "step",
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
