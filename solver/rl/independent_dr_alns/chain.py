from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerOperatorAction,
    WinnerOperatorSet,
    apply_winner_action,
)
from setp_solver.algorithms.resetp_alns.support.construction import build_initial_solution
from setp_solver.algorithms.resetp_alns.support.fleet import infer_fleet_limits
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvalBudget, EvaluationContext, score_reference
from setp_solver.solution import Solution


@dataclass(frozen=True)
class DrAction:
    destroy_id: str
    repair_id: str
    remove_fraction: float
    threshold_ratio: float = 0.0


class IndependentDrSession:
    """One-action-at-a-time DR control over the independent M1 ALNS moves.

    This deliberately has no random replacement, AlphaUCB fallback, block
    repetition, candidate proxy, or legacy DR-ALNS import. Invalid actions are
    rejected. Every response records the requested and executed action plus
    full-evaluator before/candidate/after evidence.
    """

    def __init__(
        self,
        bundle_dir: str | Path,
        *,
        seed: int,
        max_evals: int,
        initial_solution: Solution | None = None,
        carbon_aware_operators: bool = True,
    ) -> None:
        if int(max_evals) < 1:
            raise ValueError("max_evals must be positive")
        self.bundle = load_search_bundle(bundle_dir)
        self.rng = np.random.default_rng(int(seed))
        self.max_evals = int(max_evals)
        self.context = EvaluationContext(
            self.bundle.instance,
            self.bundle.carbon_profile,
            prices=DEFAULT_PRICES,
            budget=EvalBudget(limit=self.max_evals, target=self.max_evals),
        )
        limits = infer_fleet_limits(self.bundle.bundle_dir)
        self.policy = SearchPolicy(require_charging_signal=False, max_cv=limits.cv, max_ev=limits.ev)
        self.operator_set = WinnerOperatorSet.create(carbon_aware=bool(carbon_aware_operators))
        self.destroy_ids = tuple(name for name, _ in self.operator_set.destroy_ops)
        self.repair_ids = tuple(name for name, _ in self.operator_set.repair_ops)
        self.initial_solution = initial_solution or build_initial_solution(
            self.bundle.instance,
            self.bundle.carbon_profile,
            DEFAULT_PRICES,
            fleet_limits=limits,
            introduce_ev=False,
            require_charging_signal=False,
        )
        self.initial_obj = float(score_reference(self.initial_solution, self.context))
        self.current_solution = self.initial_solution
        self.current_obj = self.initial_obj
        self.best_solution = self.initial_solution
        self.best_obj = self.initial_obj
        self.initial_summary = self._summary(self.initial_solution, self.initial_obj)
        self.step_index = 0

    def action_mask(self) -> dict[str, bool]:
        summary = self._summary(self.current_solution, self.current_obj)
        has_charging = bool(self.current_solution.charging_actions)
        mask = {name: True for name in self.destroy_ids}
        for name in ("worst_carbon_removal", "carbon_related_removal"):
            if name in mask:
                mask[name] = has_charging
        # An all-CV start must be able to create the first EV route. The legacy
        # block environment did the opposite and masked this move at the edge.
        if "vehicle_type_swap" in mask:
            mask["vehicle_type_swap"] = bool(
                summary["metrics"].get("n_veh_cv", 0) or summary["metrics"].get("n_veh_ev", 0)
            )
        return mask

    def step(self, action: DrAction) -> dict[str, Any]:
        self._validate_action(action)
        budget = self.context.budget
        if budget is not None and budget.reached_target:
            raise RuntimeError(f"evaluation budget reached: {budget.count} >= {budget.target_count}")

        before_best = float(self.best_obj)
        before = self._summary(self.current_solution, self.current_obj, best_obj=self.best_obj)
        winner_action = WinnerOperatorAction(
            destroy_op_id=action.destroy_id,
            repair_op_id=action.repair_id,
            remove_fraction=float(action.remove_fraction),
            accept_param=0.0,
            temperature=0.0,
            raw_action=(),
        )
        result = apply_winner_action(
            self.current_solution,
            winner_action,
            self.context,
            rng=self.rng,
            operator_set=self.operator_set,
            policy=self.policy,
            current_obj=self.current_obj,
            progress=self._progress(),
        )
        candidate = result["candidate_solution"]
        candidate_obj = float(result["candidate_obj"])
        candidate_summary = self._summary(candidate, candidate_obj, best_obj=self.best_obj)
        threshold = float(action.threshold_ratio) * max(abs(float(self.current_obj)), 1.0)
        changed = bool(result.get("changed"))
        feasible = int(candidate_summary["violation_count"]) == 0
        accepted = bool(changed and feasible and candidate_obj <= float(self.current_obj) + threshold)
        if accepted:
            self.current_solution = candidate
            self.current_obj = candidate_obj
        improved_best = bool(accepted and candidate_obj < float(self.best_obj))
        if improved_best:
            self.best_solution = candidate
            self.best_obj = candidate_obj
        self.step_index += 1

        after = self._summary(self.current_solution, self.current_obj, best_obj=self.best_obj)
        requested = asdict(action)
        executed = {
            "destroy_id": str(result["trace"]["destroy_id"]),
            "repair_id": str(result["trace"]["repair_id"]),
            "remove_fraction": float(result["trace"]["remove_fraction"]),
            "threshold_ratio": float(action.threshold_ratio),
        }
        if requested != executed:
            raise RuntimeError(f"action substitution detected: requested={requested}, executed={executed}")
        reward = (before_best - float(self.best_obj)) / max(abs(float(self.initial_obj)), 1.0)
        return {
            "step_index": int(self.step_index),
            "requested_action": requested,
            "executed_action": executed,
            "before": before,
            "candidate": candidate_summary,
            "after": after,
            "changed": changed,
            "accepted": accepted,
            "improved_best": improved_best,
            "reward": float(reward),
            "initial_obj": float(self.initial_obj),
            "actual_evals_added": int(result.get("actual_evals_added", 0)),
            "kernel_trace": dict(result.get("trace") or {}),
        }

    def _validate_action(self, action: DrAction) -> None:
        if action.destroy_id not in self.destroy_ids:
            raise ValueError(f"unknown destroy_id: {action.destroy_id}")
        if action.repair_id not in self.repair_ids:
            raise ValueError(f"unknown repair_id: {action.repair_id}")
        if not 0.0 < float(action.remove_fraction) <= 1.0:
            raise ValueError("remove_fraction must be in (0, 1]")
        if not 0.0 <= float(action.threshold_ratio) <= 0.02:
            raise ValueError("threshold_ratio must be in [0, 0.02]")
        if not self.action_mask().get(action.destroy_id, False):
            raise ValueError(f"destroy action is not applicable: {action.destroy_id}")
        if action.repair_id == "low_carbon_charging_repair" and not self.current_solution.charging_actions:
            raise ValueError("repair action is not applicable: low_carbon_charging_repair")

    def _summary(self, solution: Solution, objective: float, *, best_obj: float | None = None) -> dict[str, Any]:
        metrics = evaluate(solution, self.bundle.instance, self.bundle.carbon_profile, DEFAULT_PRICES)
        violations = check_solution(solution, self.bundle.instance, DEFAULT_PRICES)
        return {
            "objective": float(objective),
            "best_obj": float(objective if best_obj is None else best_obj),
            "violation_count": int(len(violations)),
            "route_count": int(len(solution.routes)),
            "charging_action_count": int(len(solution.charging_actions)),
            "solution_hash": _solution_hash(solution),
            "metrics": {str(key): _plain(value) for key, value in metrics.items()},
        }

    def _progress(self) -> float:
        budget = self.context.budget
        if budget is None or budget.target_count <= 0:
            return 0.0
        return min(1.0, float(budget.count) / float(budget.target_count))


def _solution_hash(solution: Solution) -> str:
    payload = {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [asdict(item) for item in solution.cross_site_services],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _plain(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value

