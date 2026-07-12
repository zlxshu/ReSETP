"""Independent ReSETP ALNS runtime entrypoint.

v2026-06-11: This module is only an adapter shell for paper_main.tex
lines 553 and 661. ``AlnsState.objective`` delegates to ``penalized_obj``;
operators mutate only Solution routes and never duplicate model semantics.
Use ``run_alns_wouda`` for the G4 gate. The function name is retained for
runner compatibility; runtime acceptance and selection now use the project
local ``resetp_alns`` backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import os
from pathlib import Path
import time
from typing import Any, Callable

import numpy as np

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.solution import Route, Solution
from setp_solver.algorithms.resetp_alns.support.charging import repair_route_charging
from setp_solver.algorithms.resetp_alns.support.construction import build_initial_solution
from setp_solver.search.evaluation import BIG_M, EvalBudget, EvaluationContext, fairness_context_for_solution, record_repair_delta, score_candidate, score_reference
from setp_solver.algorithms.resetp_alns.operators.feasible_repair import (
    enumerate_feasible_insertions,
    nearest_depot_id,
    repair_removed_customers,
    route_customers as feasible_route_customers,
    route_distance as feasible_route_distance,
)
from setp_solver.algorithms.resetp_alns.support.fleet import FleetLimits, UNBOUNDED_FLEET, infer_fleet_limits, normalize_solution_vehicle_trips, route_ev_energy_summary
from setp_solver.algorithms.resetp_alns.operators.local_search import improve_solution_locally
from setp_solver.algorithms.resetp_alns.operators.repair_scoring import route_model_cost_delta
from setp_solver.algorithms.resetp_alns.runtime import (
    AlphaUCB,
    BalancedAlphaUCB,
    EpsilonDecayAlphaUCB,
    HillClimbing,
    MinimumCoverageAlphaUCB,
    RecordToRecordTravel,
    SoftmaxAlphaUCB,
    ThompsonPairSelector,
)
from setp_solver.algorithms.resetp_alns.support.timing import timed_section

def _load_search_bundle(path):
    from setp_solver.search.bundle import load_search_bundle
    return load_search_bundle(path)



MAX_VEHICLE_SWAP_CANDIDATES = 8
MAX_REPAIR_ROUTE_CANDIDATES = 6
MAX_REPAIR_POSITIONS_PER_ROUTE = 2


@dataclass(frozen=True)
class SearchPolicy:
    """Search-shell policy switches, not model constraints.

    v2026-06-11: H2/H3/H4 E5 probe policy for paper_main.tex lines 665 and
    673. ``require_charging_signal`` only prevents the search shell from
    deleting the last EV charging route during the E5 probe; it does not alter
    cost.py/check.py semantics.
    """

    require_charging_signal: bool = False
    max_cv: int = UNBOUNDED_FLEET
    max_ev: int = UNBOUNDED_FLEET


@dataclass(frozen=True)
class AlnsState:
    solution: Solution
    context: EvaluationContext
    objective_value: float | None = None
    removed_customers: tuple[str, ...] = ()
    policy: SearchPolicy = field(default_factory=SearchPolicy)
    source_solution: Solution | None = None
    allow_new_route_repair: bool = True

    def objective(self) -> float:
        return score_reference(self.solution, self.context) if self.objective_value is None else float(self.objective_value)


@dataclass(frozen=True)
class AlnsRunResult:
    initial_solution: Solution
    best_solution: Solution
    initial_obj: float
    best_obj: float
    evaluations: int
    feasible: bool
    charging_energy_kwh: float = 0.0
    destroy_operator_counts: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)
    repair_operator_counts: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)
    actual_moves: int = 0
    candidate_scores: int = 0
    repair_scores: int = 0
    repair_delta_count: int = 0
    operator_counts: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)


def run_alns_wouda(
    bundle_dir: str | Path,
    *,
    iterations: int | None = 5,
    seed: int = 1,
    carbon_weight: float = 1.0,
    policy: SearchPolicy | None = None,
    eval_budget: int | None = None,
    max_runtime_seconds: float = 60.0,
    fairness_enabled: bool = False,
    independent_profit: dict[str, float] | None = None,
    fairness_theta: float | None = None,
    customer_home_depot: dict[str, str] | None = None,
    initial_solution: Solution | None = None,
    carbon_quota_kg: float = 0.0,
    prices: Any = DEFAULT_PRICES,
) -> AlnsRunResult:
    """Run a small-budget ReSETP ALNS pass on a generated bundle."""

    bundle = _load_search_bundle(bundle_dir)
    limits = infer_fleet_limits(bundle.bundle_dir)
    search_policy = policy or SearchPolicy(require_charging_signal=False, max_cv=limits.cv, max_ev=limits.ev)
    # v2026-06-12: X1 can seed the cooperative search with the concatenated
    # independent-depot solution, proving theta=1.0 starts from a feasible
    # individual-rational point. Default construction is unchanged.
    initial = initial_solution or build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        fleet_limits=FleetLimits(search_policy.max_cv, search_policy.max_ev, limits.source),
        # v2026-06-12: N0/N1 natural-adoption probes can disable the charging
        # witness without changing the default E5 guard or frozen model logic.
        introduce_ev=search_policy.require_charging_signal,
        require_charging_signal=search_policy.require_charging_signal,
    )
    initial = _normalize_for_policy(initial, bundle.instance, search_policy)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        carbon_weight=carbon_weight,
        budget=EvalBudget(
            limit=_budget_limit(iterations, eval_budget),
            target=int(eval_budget) if eval_budget is not None else None,
        ),
        # v2026-06-12: Z0a/Z4 expose carbon allowance CE to the common
        # evaluator; CE=inf is the no-quota baseline with zero trading cost.
        carbon_quota_kg=float(carbon_quota_kg),
        # v2026-06-12: V2 keeps PROFIT_FAIRNESS off unless explicitly wired by
        # the experiment runner with Pi_d0 and theta.
        fairness_enabled=fairness_enabled,
        independent_profit=independent_profit,
        fairness_theta=fairness_theta,
        customer_home_depot=customer_home_depot,
        repair_delta_mode="exact" if eval_budget is None else "fast",
    )
    initial_obj = score_reference(initial, context)
    initial_state = AlnsState(initial, context, objective_value=initial_obj, policy=search_policy)

    run = _run_adaptive_sa_alns(
        initial_state,
        seed=seed,
        iterations=iterations,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
    )
    best_state = run["best_state"]
    best_obj = best_state.objective()
    feasible = len(_hard_violations(best_state.solution, context)) == 0
    destroy_counts = {name: tuple(row) for name, row in run["destroy_counts"].items()}
    repair_counts = {name: tuple(row) for name, row in run["repair_counts"].items()}
    actual_moves = sum(sum(row) for row in destroy_counts.values())
    operator_counts = {"destroy": destroy_counts, "repair": repair_counts}
    return AlnsRunResult(
        initial,
        best_state.solution,
        initial_obj,
        best_obj,
        context.budget.count if context.budget else 0,
        feasible,
        _charging_energy(best_state.solution),
        destroy_counts,
        repair_counts,
        actual_moves,
        int(context.score_counts.get("candidate", 0)),
        int(context.score_counts.get("repair_delta", 0)),
        int(context.score_counts.get("repair_delta", 0)),
        operator_counts,
    )


class _EvalOrRuntimeStop:
    """Stop local ALNS by evaluation budget or wall-clock time.

    v2026-06-12: K0 real-budget E5 gate for paper_main.tex lines 661-673.
    The ALNS package stops between iterations, so the recorded evaluation
    count may exceed the target slightly; ``EvalBudget`` is given a small
    guard margin by ``_budget_limit`` to avoid turning this normal overrun
    into a hard error.
    """

    def __init__(self, budget: EvalBudget | None, target_evaluations: int, max_runtime_seconds: float):
        self._budget = budget
        self._target_evaluations = int(target_evaluations)
        self._max_runtime_seconds = float(max_runtime_seconds)
        self._start = time.perf_counter()

    def __call__(self, rng: np.random.Generator, best: AlnsState, curr: AlnsState) -> bool:
        _ = rng, best, curr
        if self._budget is not None and self._budget.reached_target:
            return True
        return (time.perf_counter() - self._start) >= self._max_runtime_seconds


def _budget_limit(iterations: int | None, eval_budget: int | None) -> int:
    if eval_budget is None:
        return max(1000, int(iterations or 5) * 200)
    target = int(eval_budget)
    return target + max(1000, target // 10)


def _count_table(counts: Any) -> dict[str, tuple[int, int, int, int]]:
    return {str(name): tuple(int(value) for value in row) for name, row in counts.items()}


def _target_iterations(iterations: int | None, eval_budget: int | None) -> int:
    return max(1, int(eval_budget) if eval_budget is not None else int(iterations or 1))


def _make_acceptance_criterion(initial_state: AlnsState, target_iterations: int) -> Any:
    if not _flag_enabled("SETP_ALNS_CRUSH_TRUE_ACCEPTANCE"):
        return HillClimbing()

    initial_obj = max(1.0, float(initial_state.objective()))
    start_threshold = max(5.0, 0.02 * initial_obj)
    end_threshold = 0.0
    step = (start_threshold - end_threshold) / max(1, int(target_iterations))
    return RecordToRecordTravel(
        start_threshold=start_threshold,
        end_threshold=end_threshold,
        step=step,
        method="linear",
        cmp_best=False,
    )


def _make_operator_selector(
    num_destroy: int,
    num_repair: int,
    *,
    balanced: bool = False,
    selector_kind: str = "alpha_ucb",
    warmup_per_pair: int = 10,
    epsilon: float = 0.10,
    target_iterations: int = 4000,
    op_coupling: np.ndarray | None = None,
    protected_destroy_indices: tuple[int, ...] = (),
) -> Any:
    normalized = str(selector_kind or "alpha_ucb").strip().lower()
    if balanced and normalized == "alpha_ucb":
        normalized = "balanced"
    if normalized == "balanced":
        return BalancedAlphaUCB(
            [20.0, 8.0, 2.0, 0.05],
            alpha=0.08,
            num_destroy=num_destroy,
            num_repair=num_repair,
            op_coupling=op_coupling,
            warmup_per_pair=warmup_per_pair,
            epsilon=epsilon,
        )
    if normalized == "eps_decay":
        return EpsilonDecayAlphaUCB(
            [20.0, 8.0, 2.0, 0.05],
            alpha=0.08,
            num_destroy=num_destroy,
            num_repair=num_repair,
            op_coupling=op_coupling,
            warmup_per_pair=warmup_per_pair,
            epsilon_start=0.15,
            epsilon_end=0.02,
            target_iterations=target_iterations,
        )
    if normalized == "minimum_coverage":
        return MinimumCoverageAlphaUCB(
            [20.0, 8.0, 2.0, 0.05],
            alpha=0.08,
            num_destroy=num_destroy,
            num_repair=num_repair,
            op_coupling=op_coupling,
            protected_destroy_indices=protected_destroy_indices,
            warmup_per_pair=1,
            max_family_gap=50,
        )
    if normalized == "thompson":
        return ThompsonPairSelector(num_destroy, num_repair, op_coupling=op_coupling, warmup_per_pair=5)
    if normalized == "softmax":
        return SoftmaxAlphaUCB(
            [20.0, 8.0, 2.0, 0.05],
            alpha=0.08,
            num_destroy=num_destroy,
            num_repair=num_repair,
            op_coupling=op_coupling,
            temperature_start=1.0,
            temperature_end=0.1,
            target_iterations=target_iterations,
        )
    if normalized == "chain_ucb":
        return AlphaUCB(
            [4.0, 3.0, 2.0, 0.05],
            alpha=0.08,
            num_destroy=num_destroy,
            num_repair=num_repair,
            op_coupling=op_coupling,
        )
    if normalized != "alpha_ucb":
        raise ValueError(f"Unsupported selector_kind: {selector_kind}")
    return AlphaUCB(
        [20.0, 8.0, 2.0, 0.05],
        alpha=0.08,
        num_destroy=num_destroy,
        num_repair=num_repair,
        op_coupling=op_coupling,
    )


def _flag_enabled(name: str) -> bool:
    return os.environ.get(name, "1").lower() not in {"0", "false", "no"}


def _run_adaptive_sa_alns(
    initial_state: AlnsState,
    *,
    seed: int,
    iterations: int | None,
    eval_budget: int | None,
    max_runtime_seconds: float,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    destroy_ops: list[tuple[str, Callable[[AlnsState, np.random.Generator], AlnsState]]] = [
        ("random_customer_removal", random_customer_removal),
        ("worst_customer_removal", worst_customer_removal),
        ("shaw_related_removal", shaw_related_removal),
        ("whole_route_removal", whole_route_removal),
        ("route_segment_removal", route_segment_removal),
        ("vehicle_type_swap", vehicle_type_swap_destroy),
    ]
    if _flag_enabled("SETP_ALNS_CRUSH_ROUTE_ELIMINATION"):
        destroy_ops.insert(4, ("route_elimination_removal", route_elimination_removal))
    repair_ops: list[tuple[str, Callable[[AlnsState, np.random.Generator], AlnsState]]] = [
        ("greedy_insert_repair", greedy_insert_repair),
        ("regret2_insert_repair", regret2_insert_repair),
        ("regret3_insert_repair", regret3_insert_repair),
    ]
    selector = _make_operator_selector(len(destroy_ops), len(repair_ops))
    acceptance = _make_acceptance_criterion(initial_state, _target_iterations(iterations, eval_budget))
    destroy_counts = {name: [0, 0, 0, 0] for name, _ in destroy_ops}
    repair_counts = {name: [0, 0, 0, 0] for name, _ in repair_ops}
    current = best = initial_state
    target = int(eval_budget) if eval_budget is not None else int(iterations or 1)
    started = time.perf_counter()
    moves = 0
    while True:
        if iterations is not None and moves >= int(iterations):
            break
        if initial_state.context.budget is not None and initial_state.context.budget.reached_target:
            break
        if eval_budget is not None and initial_state.context.budget is not None and initial_state.context.budget.count >= target:
            break
        if time.perf_counter() - started >= float(max_runtime_seconds):
            break
        moves += 1
        progress = min(1.0, moves / max(1, target))
        destroy_idx, repair_idx = selector(rng, best, current)
        destroy_name, destroy_op = destroy_ops[int(destroy_idx)]
        repair_name, repair_op = repair_ops[int(repair_idx)]
        previous_obj = current.objective()
        previous_best_obj = best.objective()
        destroyed = destroy_op(current, rng, progress=progress)
        candidate = repair_op(destroyed, rng)
        if not candidate.removed_customers and not _hard_violations(candidate.solution, candidate.context) and _solution_changed(current.solution, candidate.solution):
            improved_solution = improve_solution_locally(candidate.solution, candidate.context)
            if _solution_changed(candidate.solution, improved_solution):
                candidate = replace(candidate, solution=improved_solution, objective_value=None)
        if destroy_name == "route_elimination_removal" and (
            len(candidate.solution.routes) >= len(current.solution.routes) or candidate.objective() >= previous_obj - 1e-9
        ):
            candidate = current
        if candidate.removed_customers or _hard_violations(candidate.solution, candidate.context) or not _solution_changed(current.solution, candidate.solution):
            candidate = current
        candidate_obj = candidate.objective()
        changed = _solution_changed(current.solution, candidate.solution)
        accepted = changed and bool(acceptance(rng, best, current, candidate))
        best_improved = accepted and candidate_obj < previous_best_obj - 1e-9 and not _hard_violations(candidate.solution, candidate.context)
        better_current = accepted and candidate_obj < previous_obj - 1e-9
        outcome_idx = 3
        reward = 0.0
        if accepted:
            current = candidate
            outcome_idx = 2
            reward = 2.0
            if better_current:
                outcome_idx = 1
                reward = 8.0
            if best_improved:
                best = candidate
                outcome_idx = 0
                reward = 20.0
        destroy_counts[destroy_name][outcome_idx] += 1
        repair_counts[repair_name][outcome_idx] += 1
        selector.update(candidate, int(destroy_idx), int(repair_idx), outcome_idx)
    return {
        "best_state": best,
        "current_state": current,
        "destroy_counts": destroy_counts,
        "repair_counts": repair_counts,
        "destroy_weights": {},
        "repair_weights": {},
        "moves": moves,
    }


def _weighted_operator(
    rng: np.random.Generator,
    operators: list[tuple[str, Callable[[AlnsState, np.random.Generator], AlnsState]]],
    weights: dict[str, float],
) -> tuple[str, Callable[[AlnsState, np.random.Generator], AlnsState]]:
    total = sum(max(1e-9, float(weights[name])) for name, _ in operators)
    pick = float(rng.random()) * total
    current = 0.0
    for name, op in operators:
        current += max(1e-9, float(weights[name]))
        if current >= pick:
            return name, op
    return operators[-1]


def _update_weight(weights: dict[str, float], name: str, reward: float) -> None:
    weights[name] = 0.8 * float(weights[name]) + 0.2 * max(0.05, float(reward))


def _adaptive_remove_count(
    customer_count: int,
    rng: np.random.Generator,
    *,
    progress: float = 0.0,
    remove_count_q: int | None = None,
) -> int:
    if customer_count <= 0:
        return 0
    if remove_count_q is not None:
        return max(1, min(int(remove_count_q), int(customer_count)))
    if not _flag_enabled("SETP_ALNS_CRUSH_ADAPTIVE_Q"):
        low = max(2, int(math.ceil(0.10 * customer_count)))
        high = max(low, int(math.ceil(0.40 * customer_count)))
        high = min(high, customer_count, 12)
        low = min(low, high)
        return int(rng.integers(low, high + 1))
    phase = min(1.0, max(0.0, float(progress)))
    low_frac = 0.10 - 0.06 * phase
    high_frac = 0.40 - 0.28 * phase
    low = max(2, int(math.ceil(low_frac * customer_count)))
    high = max(low, int(math.ceil(high_frac * customer_count)))
    high = min(high, customer_count)
    low = min(low, high)
    return int(rng.integers(low, high + 1))


def _hard_violations(solution: Solution, context: EvaluationContext) -> list[Any]:
    try:
        solution = normalize_solution_vehicle_trips(solution, context.instance)
    except ValueError as exc:
        return [exc]
    with timed_section(context, "hard_check"):
        violations = check_solution(
            solution,
            context.instance,
            context.prices,
            fairness_context=fairness_context_for_solution(solution, context),
            fairness_enabled=context.fairness_enabled,
        )
        if os.environ.get("SETP_E3_STRICT_MULTITRIP", "0").lower() not in {"0", "false", "no"}:
            from setp_solver.search.multitrip_schedule import strict_multitrip_violations

            strict_violations = strict_multitrip_violations(solution.routes, context.instance, context.prices)
            context.score_counts["strict_multitrip_schedule_checks"] = int(
                context.score_counts.get("strict_multitrip_schedule_checks", 0)
            ) + 1
            if any("public-station trips are unsupported" in item for item in strict_violations):
                context.score_counts["strict_multitrip_public_station_rejected"] = int(
                    context.score_counts.get("strict_multitrip_public_station_rejected", 0)
                ) + 1
            violations.extend(strict_violations)
        return violations


def _normalize_for_policy(solution: Solution, instance: Instance, policy: SearchPolicy) -> Solution:
    return normalize_solution_vehicle_trips(
        solution,
        instance,
        max_cv=int(policy.max_cv),
        max_ev=int(policy.max_ev),
    )


def _solution_changed(a: Solution, b: Solution) -> bool:
    return _solution_signature(a) != _solution_signature(b)


def _solution_signature(solution: Solution) -> tuple[Any, ...]:
    return (
        tuple((route.vehicle_id, route.vehicle_type.lower(), route.home_depot_id, tuple(route.node_sequence)) for route in solution.routes),
        tuple((action.vehicle_id, action.station_id, round(float(action.charge_start_second), 6), round(float(action.energy_kwh), 6)) for action in solution.charging_actions),
    )


def _initial_temperature_from_reference(
    state: AlnsState,
    seed: int,
    destroy_ops: list[tuple[str, Callable[[AlnsState, np.random.Generator], AlnsState]]],
    repair_ops: list[tuple[str, Callable[[AlnsState, np.random.Generator], AlnsState]]],
) -> float:
    reference_context = replace(state.context, budget=None, score_counts={}, score_breakdowns={})
    reference_state = replace(state, context=reference_context)
    rng = np.random.default_rng(seed)
    positives: list[float] = []
    for _ in range(3):
        _, destroy_op = destroy_ops[int(rng.integers(0, len(destroy_ops)))]
        _, repair_op = repair_ops[int(rng.integers(0, len(repair_ops)))]
        candidate = repair_op(destroy_op(reference_state, rng), rng)
        if candidate.removed_customers or _hard_violations(candidate.solution, candidate.context):
            continue
        delta = candidate.objective() - reference_state.objective()
        if delta > 1e-9:
            positives.append(float(delta))
    if not positives:
        return 250.0
    positives.sort()
    typical = positives[len(positives) // 2]
    return max(1.0, typical / max(1e-9, -math.log(0.4)))


def random_customer_removal(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    customers = _customers_in_solution(state.solution, state.context.instance)
    if not customers:
        return state
    q = _adaptive_remove_count(
        len(customers),
        rng,
        progress=float(kwargs.get("progress", 0.0)),
        remove_count_q=kwargs.get("remove_count_q"),
    )
    return _remove_customers(state, [str(customer_id) for customer_id in rng.choice(customers, size=min(q, len(customers)), replace=False)])


def worst_customer_removal(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    _ = rng
    ranked = _ranked_customers_by_distance_contribution(state.solution, state.context.instance)
    if not ranked:
        return state
    q = _adaptive_remove_count(
        len(ranked),
        rng,
        progress=float(kwargs.get("progress", 0.0)),
        remove_count_q=kwargs.get("remove_count_q"),
    )
    return _remove_customers(state, [customer_id for _, customer_id in ranked[:q]])


def shaw_related_removal(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    _ = kwargs
    customers = _customers_in_solution(state.solution, state.context.instance)
    if not customers:
        return state
    q = _adaptive_remove_count(
        len(customers),
        rng,
        progress=float(kwargs.get("progress", 0.0)),
        remove_count_q=kwargs.get("remove_count_q"),
    )
    seed_customer = str(rng.choice(customers))
    related = sorted(
        ((_shaw_relatedness(state.solution, state.context.instance, seed_customer, customer_id), customer_id) for customer_id in customers if customer_id != seed_customer),
        key=lambda item: (item[0], item[1]),
    )
    return _remove_customers(state, [seed_customer, *[customer_id for _, customer_id in related[: max(0, q - 1)]]])


def multi_customer_removal(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    _ = kwargs
    customers = _customers_in_solution(state.solution, state.context.instance)
    if not customers:
        return state
    remove_count = _adaptive_remove_count(
        len(customers),
        rng,
        progress=float(kwargs.get("progress", 0.0)),
        remove_count_q=kwargs.get("remove_count_q"),
    )
    return _remove_customers(state, [str(customer_id) for customer_id in rng.choice(customers, size=remove_count, replace=False)])


def route_segment_removal(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    routes = [route for route in state.solution.routes if _route_customer_ids(route, state.context.instance)]
    if not routes:
        return state
    route = routes[int(rng.integers(0, len(routes)))]
    customers = _route_customer_ids(route, state.context.instance)
    start = int(rng.integers(0, len(customers)))
    q = _adaptive_remove_count(
        len(_customers_in_solution(state.solution, state.context.instance)),
        rng,
        progress=float(kwargs.get("progress", 0.0)),
        remove_count_q=kwargs.get("remove_count_q"),
    )
    max_len = min(q, len(customers) - start)
    length = int(rng.integers(1, max_len + 1))
    return _remove_customers(state, customers[start : start + length])


def whole_route_removal(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    _ = kwargs
    routes = [route for route in state.solution.routes if _route_customer_ids(route, state.context.instance)]
    if len(routes) < 2:
        return state
    route = routes[int(rng.integers(0, len(routes)))]
    return _remove_customers(state, _route_customer_ids(route, state.context.instance))


def route_elimination_removal(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    """Remove 1-3 weak routes and force repair into the remaining routes."""

    _ = kwargs
    route_items = [(idx, route) for idx, route in enumerate(state.solution.routes) if _route_customer_ids(route, state.context.instance)]
    if len(route_items) < 2:
        return state
    max_remove = min(3, len(route_items) - 1)
    remove_count = int(rng.integers(1, max_remove + 1))
    ranked = sorted(route_items, key=lambda item: _weak_route_key(item[1], state.context.instance))
    selected = ranked[:remove_count]
    removed_customers = [
        customer_id
        for _, route in selected
        for customer_id in _route_customer_ids(route, state.context.instance)
    ]
    if not removed_customers:
        return state
    destroyed = _remove_customers(state, removed_customers)
    if not _solution_changed(state.solution, destroyed.solution):
        return state
    return replace(destroyed, allow_new_route_repair=False)


def greedy_insert_repair(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    _ = rng, kwargs
    return _finalize_candidate_state(_insert_removed(state, mode="greedy"))


def regret2_insert_repair(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    _ = rng, kwargs
    return _finalize_candidate_state(_insert_removed(state, mode="regret2"))


def regret3_insert_repair(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    _ = rng, kwargs
    return _finalize_candidate_state(_insert_removed(state, mode="regret3"))


def vehicle_type_swap_destroy(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    """ALNS destroy operator that only flips vehicle type."""

    _ = kwargs
    return vehicle_type_swap(state, rng)


def identity_repair(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    """Identity repair paired with ``vehicle_type_swap_destroy`` by coupling."""

    _ = rng, kwargs
    return _finalize_candidate_state(state)


def vehicle_type_swap(state: AlnsState, rng: np.random.Generator) -> AlnsState:
    """Try one CV<->EV route type swap while preserving feasibility.

    v2026-06-11: H2 vehicle-type operator for paper_main.tex lines 541, 665,
    and 673. CV->EV calls the shared G2 charging repair; EV->CV removes that
    vehicle's charging actions. When ``require_charging_signal`` is enabled,
    the operator refuses moves that would delete the last nonzero EV charge.
    """

    candidates = [*_try_cv_to_ev_candidates(state, rng), *_try_ev_to_cv_candidates(state, rng)]
    if not candidates:
        return state
    scored = []
    for candidate in candidates:
        record_repair_delta(state.context)
        scored.append((_vehicle_type_route_delta(state.solution, candidate, state.context), candidate))
    if not scored:
        return state
    for _, candidate in sorted(scored, key=lambda item: item[0]):
        candidate = _normalize_for_policy(candidate, state.context.instance, state.policy)
        if not check_solution(candidate, state.context.instance, state.context.prices):
            return replace(state, solution=candidate, objective_value=None)
    return state


def _vehicle_type_route_delta(source: Solution, candidate: Solution, context: EvaluationContext) -> float:
    if len(source.routes) != len(candidate.routes):
        return BIG_M
    for before, after in zip(source.routes, candidate.routes):
        if before.vehicle_type.lower() == after.vehicle_type.lower():
            continue
        before_actions = [action for action in source.charging_actions if action.vehicle_id == before.vehicle_id]
        after_actions = [action for action in candidate.charging_actions if action.vehicle_id == after.vehicle_id]
        return route_model_cost_delta(
            after,
            after_actions,
            context,
            base_route=before,
            base_actions=before_actions,
        )
    return BIG_M


def _remove_customers(state: AlnsState, customer_ids: list[str]) -> AlnsState:
    new_routes: list[Route] = []
    to_remove = set(customer_ids)
    if state.policy.require_charging_signal and _would_remove_last_charging_ev_customer(state, to_remove):
        return state
    removed_vehicle_ids: set[str] = set()
    for route in state.solution.routes:
        seq = [node_id for node_id in route.node_sequence if node_id not in to_remove]
        if len(seq) == 1:
            seq.append(seq[0])
        if not _route_customer_ids(replace(route, node_sequence=seq), state.context.instance):
            removed_vehicle_ids.add(route.vehicle_id)
            continue
        new_routes.append(replace(route, node_sequence=seq))
    removed = tuple(dict.fromkeys((*state.removed_customers, *customer_ids)))
    actions = [
        action
        for action in state.solution.charging_actions
        if action.vehicle_id not in removed_vehicle_ids and action.station_id in {node_id for route in new_routes for node_id in route.node_sequence}
    ]
    return replace(
        state,
        solution=replace(state.solution, routes=new_routes, charging_actions=actions),
        objective_value=None,
        removed_customers=removed,
        source_solution=state.solution if state.source_solution is None else state.source_solution,
    )


def _would_remove_last_charging_ev_customer(state: AlnsState, customer_ids: set[str]) -> bool:
    charging_vehicle_ids = {
        action.vehicle_id
        for action in state.solution.charging_actions
        if float(action.energy_kwh) > 1e-9
    }
    if len(charging_vehicle_ids) != 1:
        return False
    vehicle_id = next(iter(charging_vehicle_ids))
    route = next((item for item in state.solution.routes if item.vehicle_id == vehicle_id), None)
    if route is None:
        return False
    return any(customer_id in customer_ids for customer_id in _route_customer_ids(route, state.context.instance))


def _insert_removed(state: AlnsState, *, mode: str) -> AlnsState:
    repaired = repair_removed_customers(
        state.solution,
        list(state.removed_customers),
        state.context,
        state.policy,
        mode=mode,
        allow_new_route=state.allow_new_route_repair,
    )
    if repaired is None:
        return replace(
            state,
            solution=state.source_solution or state.solution,
            objective_value=None,
            removed_customers=(),
            allow_new_route_repair=True,
        )
    return replace(state, solution=repaired, objective_value=None, removed_customers=(), source_solution=None, allow_new_route_repair=True)


def _try_cv_to_ev(state: AlnsState, rng: np.random.Generator) -> AlnsState:
    candidates = _try_cv_to_ev_candidates(state, rng)
    return state if not candidates else replace(state, solution=candidates[0], objective_value=None)


def _try_cv_to_ev_candidates(state: AlnsState, rng: np.random.Generator) -> list[Solution]:
    if state.policy.max_ev <= 0:
        return []
    routes = list(state.solution.routes)
    indices = [idx for idx, route in enumerate(routes) if route.vehicle_type.lower() == "cv" and _route_customer_ids(route, state.context.instance)]
    rng.shuffle(indices)
    indices = indices[:MAX_VEHICLE_SWAP_CANDIDATES]
    candidates: list[Solution] = []
    for idx in indices:
        route = routes[idx]
        ev_id = _next_vehicle_id(state.solution, "EV")
        ev_route = replace(route, vehicle_id=ev_id, vehicle_type="ev")
        try:
            repaired_route, actions = repair_route_charging(
                ev_route,
                state.context.instance,
                state.context.carbon_profile,
                state.context.prices,
            )
        except ValueError:
            continue
        if state.policy.require_charging_signal and not actions:
            continue
        candidate_routes = list(routes)
        candidate_routes[idx] = repaired_route
        candidate_actions = [
            action
            for action in state.solution.charging_actions
            if action.vehicle_id != route.vehicle_id and action.vehicle_id != ev_id
        ]
        candidate = replace(
            state.solution,
            routes=candidate_routes,
            charging_actions=[*candidate_actions, *actions],
        )
        if state.policy.require_charging_signal and not has_charging_signal(candidate):
            continue
        try:
            candidates.append(_normalize_for_policy(candidate, state.context.instance, state.policy))
        except ValueError:
            continue
    return candidates


def _try_ev_to_cv(state: AlnsState, rng: np.random.Generator) -> AlnsState:
    candidates = _try_ev_to_cv_candidates(state, rng)
    return state if not candidates else replace(state, solution=candidates[0], objective_value=None)


def _try_ev_to_cv_candidates(state: AlnsState, rng: np.random.Generator) -> list[Solution]:
    if state.policy.max_cv <= 0:
        return []
    routes = list(state.solution.routes)
    indices = [idx for idx, route in enumerate(routes) if route.vehicle_type.lower() == "ev"]
    rng.shuffle(indices)
    indices = indices[:MAX_VEHICLE_SWAP_CANDIDATES]
    candidates: list[Solution] = []
    for idx in indices:
        route = routes[idx]
        cv_id = _next_vehicle_id(state.solution, "CV")
        cv_route = replace(
            route,
            vehicle_id=cv_id,
            vehicle_type="cv",
            node_sequence=[node_id for node_id in route.node_sequence if _node_type(node_id, state.context.instance) != "f"],
        )
        candidate_routes = list(routes)
        candidate_routes[idx] = cv_route
        candidate_actions = [action for action in state.solution.charging_actions if action.vehicle_id != route.vehicle_id]
        candidate = replace(state.solution, routes=candidate_routes, charging_actions=candidate_actions)
        if state.policy.require_charging_signal and not has_charging_signal(candidate):
            continue
        try:
            candidates.append(_normalize_for_policy(candidate, state.context.instance, state.policy))
        except ValueError:
            continue
    return candidates


def _insertion_options(
    solution: Solution,
    customer_id: str,
    context: EvaluationContext,
    policy: SearchPolicy,
) -> list[tuple[float, Solution]]:
    return [(option.score, option.solution) for option in enumerate_feasible_insertions(solution, customer_id, context, policy)]


def _ranked_repair_routes(routes: list[Route], customer_id: str, instance: Instance) -> list[tuple[int, Route]]:
    scored = [
        (_route_customer_proximity(route, customer_id, instance), idx, route)
        for idx, route in enumerate(routes)
        if len(route.node_sequence) >= 2
    ]
    scored.sort(key=lambda item: item[0])
    return [(idx, route) for _, idx, route in scored[:MAX_REPAIR_ROUTE_CANDIDATES]]


def _route_customer_proximity(route: Route, customer_id: str, instance: Instance) -> float:
    anchors = route.node_sequence[1:-1] or route.node_sequence
    try:
        return min(float(instance.distance(customer_id, node_id)) for node_id in anchors)
    except Exception:
        return BIG_M


def _ranked_insert_positions(route: Route, customer_id: str, instance: Instance) -> list[int]:
    scored: list[tuple[float, int]] = []
    for pos in range(1, len(route.node_sequence)):
        prev_node = route.node_sequence[pos - 1]
        next_node = route.node_sequence[pos]
        try:
            delta = (
                float(instance.distance(prev_node, customer_id))
                + float(instance.distance(customer_id, next_node))
                - float(instance.distance(prev_node, next_node))
            )
        except Exception:
            delta = BIG_M
        scored.append((delta, pos))
    scored.sort(key=lambda item: item[0])
    return [pos for _, pos in scored[:MAX_REPAIR_POSITIONS_PER_ROUTE]]


def _finalize_candidate_state(state: AlnsState) -> AlnsState:
    solution = _normalize_for_policy(state.solution, state.context.instance, state.policy)
    with timed_section(state.context, "full_candidate_score"):
        objective = score_candidate(solution, state.context)
    return replace(state, solution=solution, objective_value=objective, removed_customers=state.removed_customers)


def _repair_route_delta_score(
    route: Route,
    actions: list[Any],
    context: EvaluationContext,
    *,
    base_route: Route | None = None,
    base_actions: list[Any] | None = None,
) -> float:
    record_repair_delta(context)
    return route_model_cost_delta(route, actions, context, base_route=base_route, base_actions=base_actions)


def _repair_solution_delta_score(solution: Solution, context: EvaluationContext) -> float:
    record_repair_delta(context)
    try:
        if context.repair_delta_mode == "exact":
            return score_reference(solution, context)
        with timed_section(context, "repair_solution_score"):
            return float(evaluate(solution, context.instance, context.carbon_profile, context.prices, carbon_quota_kg=context.carbon_quota_kg)["total_cost"])
    except Exception:
        return BIG_M


def _route_distance(route: Route, instance: Instance) -> float:
    return sum(float(instance.distance(a, b)) for a, b in zip(route.node_sequence, route.node_sequence[1:]))


def _weak_route_key(route: Route, instance: Instance) -> tuple[float, float, str]:
    customers = _route_customer_ids(route, instance)
    distance_per_customer = _route_distance(route, instance) / max(1, len(customers))
    return (float(len(customers)), -float(distance_per_customer), route.vehicle_id)


def _customers_in_solution(solution: Solution, instance: Instance) -> list[str]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    return [
        node_id
        for route in solution.routes
        for node_id in route.node_sequence
        if node_lookup.get(node_id) and node_lookup[node_id].node_type.lower() == "c"
    ]


def has_charging_signal(solution: Solution) -> bool:
    """Return whether the solution contains nonzero EV charging energy."""

    return _charging_energy(solution) > 1e-9


def _charging_energy(solution: Solution) -> float:
    return sum(float(action.energy_kwh) for action in solution.charging_actions)


def _count_routes(solution: Solution, vehicle_type: str) -> int:
    return sum(1 for route in solution.routes if route.vehicle_type.lower() == vehicle_type.lower())


def _route_customer_ids(route: Route, instance: Instance) -> list[str]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    return [
        node_id
        for node_id in route.node_sequence
        if node_lookup.get(node_id) is not None and node_lookup[node_id].node_type.lower() == "c"
    ]


def _node_type(node_id: str, instance: Instance) -> str:
    return next(node.node_type.lower() for node in instance.nodes if node.node_id == node_id)


def _worst_customer_by_distance_contribution(solution: Solution, instance: Instance) -> str | None:
    ranked = _ranked_customers_by_distance_contribution(solution, instance)
    return None if not ranked else ranked[0][1]


def _ranked_customers_by_distance_contribution(solution: Solution, instance: Instance) -> list[tuple[float, str]]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    ranked: list[tuple[float, str]] = []
    for route in solution.routes:
        seq = route.node_sequence
        for idx in range(1, len(seq) - 1):
            node_id = seq[idx]
            if node_lookup.get(node_id) is None or node_lookup[node_id].node_type.lower() != "c":
                continue
            contribution = instance.distance(seq[idx - 1], node_id) + instance.distance(node_id, seq[idx + 1]) - instance.distance(seq[idx - 1], seq[idx + 1])
            ranked.append((float(contribution), node_id))
    return sorted(ranked, reverse=True)


def _shaw_relatedness(solution: Solution, instance: Instance, seed_customer: str, customer_id: str) -> float:
    node_lookup = {node.node_id: node for node in instance.nodes}
    seed = node_lookup[seed_customer]
    customer = node_lookup[customer_id]
    route_of: dict[str, int] = {}
    for idx, route in enumerate(solution.routes):
        for node_id in _route_customer_ids(route, instance):
            route_of[node_id] = idx
    same_route_bonus = 0.0 if route_of.get(seed_customer) == route_of.get(customer_id) else 10_000.0
    return (
        float(instance.distance(seed_customer, customer_id))
        + abs(float(seed.ready_time) - float(customer.ready_time)) * 0.1
        + abs(float(seed.due_time) - float(customer.due_time)) * 0.05
        + abs(float(seed.demand) - float(customer.demand)) * 10.0
        + same_route_bonus
    )


def _nearest_depot(customer_id: str, instance: Instance) -> str:
    depots = [node for node in instance.nodes if node.node_type.lower() == "d"]
    return min(depots, key=lambda depot: instance.distance(depot.node_id, customer_id)).node_id


def _next_vehicle_id(solution: Solution, prefix: str) -> str:
    used = {route.vehicle_id for route in solution.routes}
    idx = 1
    while f"{prefix}{idx}" in used:
        idx += 1
    return f"{prefix}{idx}"
