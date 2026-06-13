"""Adapter for the local N-Wouda ALNS package.

v2026-06-11: This module is only an adapter shell for paper_main.tex
lines 553 and 661. ``AlnsState.objective`` delegates to ``penalized_obj``;
operators mutate only Solution routes and never duplicate model semantics.
Use ``run_alns_wouda`` for the G4 gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import sys
import time
import types
from typing import Any

import numpy as np

from ..check import check_solution
from ..instance_loader import Instance
from ..prices import DEFAULT_PRICES
from ..solution import Route, Solution
from .bundle import load_search_bundle
from .charging import repair_route_charging
from .construction import build_initial_solution
from .evaluation import EvalBudget, EvaluationContext, fairness_context_for_solution, penalized_obj
from .fleet import FleetLimits, UNBOUNDED_FLEET, infer_fleet_limits, route_ev_energy_summary


@dataclass(frozen=True)
class SearchPolicy:
    """Search-shell policy switches, not model constraints.

    v2026-06-11: H2/H3/H4 E5 probe policy for paper_main.tex lines 665 and
    673. ``require_charging_signal`` only prevents the search shell from
    deleting the last EV charging route during the E5 probe; it does not alter
    cost.py/check.py semantics.
    """

    require_charging_signal: bool = True
    max_cv: int = UNBOUNDED_FLEET
    max_ev: int = UNBOUNDED_FLEET


@dataclass(frozen=True)
class AlnsState:
    solution: Solution
    context: EvaluationContext
    removed_customers: tuple[str, ...] = ()
    policy: SearchPolicy = field(default_factory=SearchPolicy)

    def objective(self) -> float:
        return penalized_obj(self.solution, self.context)


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
) -> AlnsRunResult:
    """Run a small-budget ALNS-Wouda pass on a generated bundle."""

    _ensure_local_alns_on_path()
    from alns import ALNS
    from alns.accept import RecordToRecordTravel
    from alns.select import RouletteWheel
    from alns.stop import MaxIterations

    bundle = load_search_bundle(bundle_dir)
    limits = infer_fleet_limits(bundle.bundle_dir)
    search_policy = policy or SearchPolicy(require_charging_signal=True, max_cv=limits.cv, max_ev=limits.ev)
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
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        carbon_weight=carbon_weight,
        budget=EvalBudget(limit=_budget_limit(iterations, eval_budget)),
        # v2026-06-12: Z0a/Z4 expose carbon allowance CE to the common
        # evaluator; CE=inf is the no-quota baseline with zero trading cost.
        carbon_quota_kg=float(carbon_quota_kg),
        # v2026-06-12: V2 keeps PROFIT_FAIRNESS off unless explicitly wired by
        # the experiment runner with Pi_d0 and theta.
        fairness_enabled=fairness_enabled,
        independent_profit=independent_profit,
        fairness_theta=fairness_theta,
        customer_home_depot=customer_home_depot,
    )
    initial_state = AlnsState(initial, context, policy=search_policy)
    initial_obj = initial_state.objective()

    alns = ALNS(np.random.default_rng(seed))
    alns.add_destroy_operator(random_customer_removal, name="random_customer_removal")
    alns.add_destroy_operator(worst_customer_removal, name="worst_customer_removal")
    alns.add_destroy_operator(vehicle_type_swap_destroy, name="vehicle_type_swap")
    alns.add_repair_operator(greedy_insert_repair, name="greedy_insert_repair")
    alns.add_repair_operator(regret2_insert_repair, name="regret2_insert_repair")
    alns.add_repair_operator(identity_repair, name="identity_repair")
    coupling = np.array(
        [
            [True, True, False],
            [True, True, False],
            [False, False, True],
        ],
        dtype=bool,
    )
    selector = RouletteWheel([20.0, 8.0, 2.0, 0.0], 0.8, 3, 3, op_coupling=coupling)
    stopping_iterations = iterations if iterations is not None else max(1, int((eval_budget or 3000) / 25))
    accept = RecordToRecordTravel(
        start_threshold=1_000_000.0,
        end_threshold=0.0,
        step=1_000_000.0 / max(1, stopping_iterations),
    )
    stop = (
        MaxIterations(iterations)
        if iterations is not None
        else _EvalOrRuntimeStop(context.budget, int(eval_budget or 3000), max_runtime_seconds)
    )
    result = alns.iterate(initial_state, selector, accept, stop)
    best_state = result.best_state
    best_obj = best_state.objective()
    feasible = len(
        check_solution(
            best_state.solution,
            bundle.instance,
            DEFAULT_PRICES,
            fairness_context=fairness_context_for_solution(best_state.solution, context),
            fairness_enabled=fairness_enabled,
        )
    ) == 0
    return AlnsRunResult(
        initial,
        best_state.solution,
        initial_obj,
        best_obj,
        context.budget.count if context.budget else 0,
        feasible,
        _charging_energy(best_state.solution),
        _count_table(result.statistics.destroy_operator_counts),
        _count_table(result.statistics.repair_operator_counts),
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
        if self._budget is not None and self._budget.count >= self._target_evaluations:
            return True
        return (time.perf_counter() - self._start) >= self._max_runtime_seconds


def _budget_limit(iterations: int | None, eval_budget: int | None) -> int:
    if eval_budget is None:
        return max(1000, int(iterations or 5) * 200)
    target = int(eval_budget)
    return target + max(100, target // 10)


def _count_table(counts: Any) -> dict[str, tuple[int, int, int, int]]:
    return {str(name): tuple(int(value) for value in row) for name, row in counts.items()}


def random_customer_removal(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    customers = _customers_in_solution(state.solution, state.context.instance)
    if not customers:
        return state
    customer_id = str(rng.choice(customers))
    return _remove_customers(state, [customer_id])


def worst_customer_removal(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    _ = rng, kwargs
    customer_id = _worst_customer_by_distance_contribution(state.solution, state.context.instance)
    return _remove_customers(state, [customer_id]) if customer_id else state


def greedy_insert_repair(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    _ = rng, kwargs
    return _insert_removed(state, regret=False)


def regret2_insert_repair(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    _ = rng, kwargs
    return _insert_removed(state, regret=True)


def vehicle_type_swap_destroy(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    """ALNS destroy operator that only flips vehicle type."""

    _ = kwargs
    return vehicle_type_swap(state, rng)


def identity_repair(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
    """Identity repair paired with ``vehicle_type_swap_destroy`` by coupling."""

    _ = rng, kwargs
    return state


def vehicle_type_swap(state: AlnsState, rng: np.random.Generator) -> AlnsState:
    """Try one CV<->EV route type swap while preserving feasibility.

    v2026-06-11: H2 vehicle-type operator for paper_main.tex lines 541, 665,
    and 673. CV->EV calls the shared G2 charging repair; EV->CV removes that
    vehicle's charging actions. When ``require_charging_signal`` is enabled,
    the operator refuses moves that would delete the last nonzero EV charge.
    """

    cv_candidate = _try_cv_to_ev(state, rng)
    if cv_candidate is not state:
        return cv_candidate
    return _try_ev_to_cv(state, rng)


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
    return replace(state, solution=replace(state.solution, routes=new_routes, charging_actions=actions), removed_customers=removed)


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


def _insert_removed(state: AlnsState, *, regret: bool) -> AlnsState:
    current = state.solution
    removed = list(state.removed_customers)
    while removed:
        scored = []
        for customer_id in removed:
            options = _insertion_options(current, customer_id, state.context, state.policy)
            if not options:
                continue
            best = options[0]
            second_obj = options[1][0] if len(options) > 1 else best[0]
            primary = -(second_obj - best[0]) if regret else best[0]
            scored.append((primary, best[0], customer_id, best[1]))
        if not scored:
            break
        _, _, customer_id, solution = min(scored)
        current = solution
        removed.remove(customer_id)
    return replace(state, solution=current, removed_customers=tuple(removed))


def _try_cv_to_ev(state: AlnsState, rng: np.random.Generator) -> AlnsState:
    if _count_routes(state.solution, "ev") >= state.policy.max_ev:
        return state
    routes = list(state.solution.routes)
    indices = [idx for idx, route in enumerate(routes) if route.vehicle_type.lower() == "cv" and _route_customer_ids(route, state.context.instance)]
    rng.shuffle(indices)
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
        if not check_solution(candidate, state.context.instance, state.context.prices):
            return replace(state, solution=candidate)
    return state


def _try_ev_to_cv(state: AlnsState, rng: np.random.Generator) -> AlnsState:
    if _count_routes(state.solution, "cv") >= state.policy.max_cv:
        return state
    routes = list(state.solution.routes)
    indices = [idx for idx, route in enumerate(routes) if route.vehicle_type.lower() == "ev"]
    rng.shuffle(indices)
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
        if not check_solution(candidate, state.context.instance, state.context.prices):
            return replace(state, solution=candidate)
    return state


def _insertion_options(
    solution: Solution,
    customer_id: str,
    context: EvaluationContext,
    policy: SearchPolicy,
) -> list[tuple[float, Solution]]:
    options: list[tuple[float, Solution]] = []
    for route_idx, route in enumerate(solution.routes):
        if route.vehicle_type.lower() != "cv":
            continue
        for pos in range(1, len(route.node_sequence)):
            seq = list(route.node_sequence)
            seq.insert(pos, customer_id)
            routes = list(solution.routes)
            routes[route_idx] = replace(route, node_sequence=seq)
            candidate = replace(solution, routes=routes)
            options.append((penalized_obj(candidate, context), candidate))
    # v2026-06-11: G3/G4 shell respects the same fleet cap as check.py; the
    # default policy is m^g=10 from paper_main.tex:582-584.
    if len([route for route in solution.routes if route.vehicle_type.lower() == "cv"]) < policy.max_cv:
        depot_id = _nearest_depot(customer_id, context.instance)
        vehicle_id = _next_vehicle_id(solution, "CV")
        candidate = replace(
            solution,
            routes=[*solution.routes, Route(vehicle_id, "cv", depot_id, [depot_id, customer_id, depot_id])],
        )
        options.append((penalized_obj(candidate, context), candidate))
    return sorted(options, key=lambda item: item[0])


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
    node_lookup = {node.node_id: node for node in instance.nodes}
    worst: tuple[float, str] | None = None
    for route in solution.routes:
        seq = route.node_sequence
        for idx in range(1, len(seq) - 1):
            node_id = seq[idx]
            if node_lookup.get(node_id) is None or node_lookup[node_id].node_type.lower() != "c":
                continue
            contribution = instance.distance(seq[idx - 1], node_id) + instance.distance(node_id, seq[idx + 1]) - instance.distance(seq[idx - 1], seq[idx + 1])
            if worst is None or contribution > worst[0]:
                worst = (contribution, node_id)
    return None if worst is None else worst[1]


def _nearest_depot(customer_id: str, instance: Instance) -> str:
    depots = [node for node in instance.nodes if node.node_type.lower() == "d"]
    return min(depots, key=lambda depot: instance.distance(depot.node_id, customer_id)).node_id


def _next_vehicle_id(solution: Solution, prefix: str) -> str:
    used = {route.vehicle_id for route in solution.routes}
    idx = 1
    while f"{prefix}{idx}" in used:
        idx += 1
    return f"{prefix}{idx}"


def _ensure_local_alns_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    alns_path = repo_root / "Reference Algorithm" / "ALNS-7.0.0@N-Wouda"
    if str(alns_path) not in sys.path:
        sys.path.insert(0, str(alns_path))
    _ensure_matplotlib_stub()


def _ensure_matplotlib_stub() -> None:
    # v2026-06-11: local ALNS imports matplotlib only for optional plotting;
    # tests and gates never plot, so provide a no-op stub instead of installing.
    if "matplotlib.pyplot" in sys.modules:
        return
    matplotlib = types.ModuleType("matplotlib")
    pyplot = types.ModuleType("matplotlib.pyplot")

    class _Axes:
        def plot(self, *args: Any, **kwargs: Any) -> None:
            return None

        def barh(self, *args: Any, **kwargs: Any) -> None:
            return None

        def set_title(self, *args: Any, **kwargs: Any) -> None:
            return None

        def set_ylabel(self, *args: Any, **kwargs: Any) -> None:
            return None

        def set_xlabel(self, *args: Any, **kwargs: Any) -> None:
            return None

        def legend(self, *args: Any, **kwargs: Any) -> None:
            return None

    class _Figure:
        def subplots(self, *args: Any, **kwargs: Any) -> tuple[_Axes, _Axes]:
            return _Axes(), _Axes()

        def subplots_adjust(self, *args: Any, **kwargs: Any) -> None:
            return None

        def suptitle(self, *args: Any, **kwargs: Any) -> None:
            return None

    def subplots(*args: Any, **kwargs: Any) -> tuple[_Figure, _Axes]:
        return _Figure(), _Axes()

    pyplot.Axes = _Axes
    pyplot.Figure = _Figure
    pyplot.subplots = subplots
    pyplot.draw_if_interactive = lambda *args, **kwargs: None
    matplotlib.pyplot = pyplot
    sys.modules["matplotlib"] = matplotlib
    sys.modules["matplotlib.pyplot"] = pyplot
