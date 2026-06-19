"""Transcript-backed metaheuristic baselines for the ReSETP paper.

The algorithms in this module differ in representation and search policy, but
they all submit complete :class:`Solution` objects to the same
``evaluate/check`` referee through ``score_candidate`` and ``EvalBudget``.
Route feasibility, EV charging repair, time windows, multi-depot assignment,
and cross-site bookkeeping are delegated to the existing construction/repair
layer; this module only owns the metaheuristic search shells.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import math
from pathlib import Path
import random
import time
from typing import Any, Callable

from ..check import check_solution
from ..cost import evaluate
from ..instance_loader import Instance, Node
from ..prices import DEFAULT_PRICES
from ..solution import ChargingAction, CrossSiteService, Route, Solution
from .bundle import SearchBundle, load_search_bundle
from .candidates import (
    _OperatorOutcome,
    _apply_strong_alns_destroy_repair,
    _customer_positions,
    _rebuild_solution,
    _route_crossover,
    _route_customers,
    _route_with_customers,
    make_shared_initial_solution,
    random_key_to_solution,
    solution_signature_hash,
)
from .evaluation import EvalBudget, EvaluationContext, model_cost, score_candidate, score_reference


BASELINE_ALGORITHMS = ("GA", "PSO", "VNS", "ACO", "GA-VNS", "LNS", "GWO", "IWD")

BASELINE_SOURCES = {
    "GA": "Narayanan et al. 2022 arXiv:2204.05545 sec.2.3",
    "PSO": "Transcript-backed discrete VRPTW PSO",
    "VNS": "Woller et al. 2025 arXiv:2511.09570 algorithm 1",
    "ACO": "He Meiling et al. 2023 IACO transcript",
    "GA-VNS": "Narayanan GA plus Woller VNS memetic hybrid",
    "LNS": "Gao Jiaojiao et al. 2024 GLNS transcript",
    "GWO": "Ma Xiangli et al. 2025 HGWO transcript",
    "IWD": "Zhang Jingwen et al. 2025 IIWD transcript",
}


@dataclass(frozen=True)
class BaselineRunResult:
    algorithm: str
    source: str
    feasible: bool
    status: str
    evals: int
    elapsed_seconds: float
    best_cost: float | None
    best_penalized_obj: float | None
    best_solution: Solution | None
    history: list[dict[str, Any]] = field(default_factory=list)
    failure_reason: str = ""
    shared_seed_cost: float | None = None
    solution_signature_hash: str = ""
    route_count: int = 0
    cv_route_count: int = 0
    ev_route_count: int = 0
    violation_count: int = 0
    operator_counts: dict[str, int] = field(default_factory=dict)
    parameter_notes: dict[str, Any] = field(default_factory=dict)


@dataclass
class _ScoredSolution:
    solution: Solution
    objective: float
    cost: float
    feasible: bool
    signature: str


@dataclass(frozen=True)
class _ThinPolicy:
    require_charging_signal: bool = False
    max_cv: int = 10**9
    max_ev: int = 10**9


class _SearchSession:
    def __init__(
        self,
        algorithm: str,
        bundle: SearchBundle,
        seed: int,
        eval_budget: int,
        max_runtime_seconds: float,
        initial_solution: Solution,
    ) -> None:
        self.algorithm = str(algorithm)
        self.bundle = bundle
        self.rng = random.Random(int(seed))
        self.started = time.perf_counter()
        self.max_runtime_seconds = float(max_runtime_seconds)
        self.context = EvaluationContext(
            bundle.instance,
            bundle.carbon_profile,
            prices=DEFAULT_PRICES,
            budget=EvalBudget(limit=int(eval_budget), target=int(eval_budget)),
        )
        self.shared_seed_cost = model_cost(initial_solution, self.context)
        seed_obj = score_reference(initial_solution, self.context)
        self.current = _ScoredSolution(
            solution=initial_solution,
            objective=float(seed_obj),
            cost=float(self.shared_seed_cost),
            feasible=_is_feasible(initial_solution, self.context),
            signature=solution_signature_hash(initial_solution),
        )
        self.best = self.current
        self.history: list[dict[str, Any]] = [
            {
                "eval": 0,
                "best_cost": self.best.cost,
                "current_cost": self.current.cost,
                "operator": "shared_warm_start",
            }
        ]
        self.operator_counts: dict[str, int] = {}

    @property
    def evals(self) -> int:
        return int(self.context.budget.count if self.context.budget is not None else 0)

    @property
    def target(self) -> int:
        return int(self.context.budget.target_count if self.context.budget is not None else 0)

    def can_score(self) -> bool:
        if self.context.budget is not None and self.context.budget.reached_target:
            return False
        return (time.perf_counter() - self.started) < self.max_runtime_seconds

    def time_expired(self) -> bool:
        return (time.perf_counter() - self.started) >= self.max_runtime_seconds

    def count_operator(self, name: str) -> None:
        self.operator_counts[name] = self.operator_counts.get(name, 0) + 1

    def score(self, solution: Solution, *, operator: str) -> _ScoredSolution | None:
        if not self.can_score():
            return None
        self.count_operator(operator)
        objective = float(score_candidate(solution, self.context, label="candidate"))
        feasible = _is_feasible(solution, self.context)
        cost = float(model_cost(solution, self.context)) if feasible else math.inf
        scored = _ScoredSolution(
            solution=solution,
            objective=objective,
            cost=cost,
            feasible=feasible,
            signature=solution_signature_hash(solution),
        )
        if feasible and objective < self.best.objective - 1e-9:
            self.best = scored
            self.history.append(
                {
                    "eval": self.evals,
                    "best_cost": cost,
                    "current_cost": self.current.cost if self.current.feasible else math.inf,
                    "operator": operator,
                }
            )
        return scored

    def accept_if_better(self, scored: _ScoredSolution | None) -> bool:
        if scored is None:
            return False
        if scored.feasible and scored.objective <= self.current.objective + 1e-9:
            self.current = scored
            return True
        return False

    def accept_metropolis(self, scored: _ScoredSolution | None, temperature: float) -> bool:
        if scored is None or not scored.feasible:
            return False
        delta = scored.objective - self.current.objective
        if delta <= 1e-9:
            self.current = scored
            return True
        if temperature <= 1e-12:
            return False
        if self.rng.random() < math.exp(-delta / temperature):
            self.current = scored
            return True
        return False

    def finalize(self, parameter_notes: dict[str, Any] | None = None, failure_reason: str = "") -> BaselineRunResult:
        elapsed = time.perf_counter() - self.started
        best_solution = self.best.solution if self.best.feasible else None
        violations = check_solution(best_solution, self.context.instance, DEFAULT_PRICES) if best_solution is not None else []
        status = "OK"
        reason = failure_reason
        if best_solution is None or violations:
            status = "HALT_INFEASIBLE"
            reason = reason or "No zero-violation complete solution was produced."
        elif self.evals < self.target:
            status = "HALT_RUNTIME_UNDER_EVAL" if self.time_expired() else "HALT_UNDER_EVAL"
            reason = reason or f"Stopped at {self.evals}/{self.target} complete evaluations."
        return BaselineRunResult(
            algorithm=self.algorithm,
            source=BASELINE_SOURCES[self.algorithm],
            feasible=best_solution is not None and not violations,
            status=status,
            evals=self.evals,
            elapsed_seconds=float(elapsed),
            best_cost=float(self.best.cost) if self.best.feasible else None,
            best_penalized_obj=float(self.best.objective) if self.best.feasible else None,
            best_solution=best_solution,
            history=list(self.history),
            failure_reason=reason,
            shared_seed_cost=float(self.shared_seed_cost),
            solution_signature_hash=solution_signature_hash(best_solution) if best_solution is not None else "",
            route_count=len(best_solution.routes) if best_solution is not None else 0,
            cv_route_count=sum(1 for route in best_solution.routes if route.vehicle_type.lower() == "cv") if best_solution is not None else 0,
            ev_route_count=sum(1 for route in best_solution.routes if route.vehicle_type.lower() == "ev") if best_solution is not None else 0,
            violation_count=len(violations),
            operator_counts=dict(self.operator_counts),
            parameter_notes=parameter_notes or {},
        )


def run_metaheuristic_baseline(
    algorithm: str,
    bundle_dir: str | Path,
    *,
    seed: int = 1,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 900.0,
    initial_solution: Solution | None = None,
) -> BaselineRunResult:
    """Run one formal metaheuristic baseline under the common referee."""

    name = _normalize_algorithm(algorithm)
    bundle = load_search_bundle(bundle_dir)
    warm = initial_solution or make_shared_initial_solution(bundle)
    session = _SearchSession(name, bundle, seed, eval_budget, max_runtime_seconds, warm)
    runner = {
        "GA": _run_ga,
        "PSO": _run_pso,
        "VNS": _run_vns,
        "ACO": _run_aco,
        "GA-VNS": _run_ga_vns,
        "LNS": _run_lns,
        "GWO": _run_gwo,
        "IWD": _run_iwd,
    }[name]
    return runner(session)


def baseline_result_to_dict(result: BaselineRunResult, *, include_solution: bool = False) -> dict[str, Any]:
    row = {
        "algorithm": result.algorithm,
        "source": result.source,
        "feasible": result.feasible,
        "status": result.status,
        "evals": result.evals,
        "actual_evals": result.evals,
        "elapsed_seconds": result.elapsed_seconds,
        "best_cost": result.best_cost,
        "best_penalized_obj": result.best_penalized_obj,
        "failure_reason": result.failure_reason,
        "shared_seed_cost": result.shared_seed_cost,
        "solution_signature_hash": result.solution_signature_hash,
        "route_count": result.route_count,
        "cv_route_count": result.cv_route_count,
        "ev_route_count": result.ev_route_count,
        "violation_count": result.violation_count,
        "operator_counts": result.operator_counts,
        "parameter_notes": result.parameter_notes,
        "history": result.history,
    }
    if include_solution:
        row["solution"] = solution_to_dict(result.best_solution) if result.best_solution is not None else None
    return row


def solution_to_dict(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [asdict(item) for item in solution.cross_site_services],
    }


def solution_from_dict(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[Route(str(row["vehicle_id"]), str(row["vehicle_type"]), str(row["home_depot_id"]), [str(node) for node in row["node_sequence"]]) for row in payload.get("routes", [])],
        charging_actions=[ChargingAction(str(row["vehicle_id"]), str(row["station_id"]), float(row["energy_kwh"]), float(row["occupancy_minutes"]), float(row["charge_start_second"])) for row in payload.get("charging_actions", [])],
        cross_site_services=[CrossSiteService(str(row["customer_id"]), str(row["served_by_depot_id"])) for row in payload.get("cross_site_services", [])],
    )


def cost_breakdown_row(
    instance_name: str,
    algorithm: str,
    seed: int,
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics = evaluate(solution, instance, carbon_profile, DEFAULT_PRICES)
    violations = check_solution(solution, instance, DEFAULT_PRICES)
    row: dict[str, Any] = {
        "instance": instance_name,
        "algorithm": algorithm,
        "seed": int(seed),
        "total_cost": float(metrics["total_cost"]),
        "route_count": len(solution.routes),
        "cv_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"),
        "ev_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
        "charging_actions": len(solution.charging_actions),
        "violation_count": len(violations),
        "feasible": len(violations) == 0,
    }
    for field_name, value in metrics.items():
        if field_name.startswith("cost_") or field_name in {"E_total", "E_CV", "E_EV"}:
            try:
                row[field_name] = float(value)
            except (TypeError, ValueError):
                pass
    return row


def _run_ga(session: _SearchSession) -> BaselineRunResult:
    return session.finalize(failure_reason="GA baseline not implemented in this commit.")


def _run_pso(session: _SearchSession) -> BaselineRunResult:
    return session.finalize(failure_reason="PSO baseline not implemented in this commit.")


def _run_vns(session: _SearchSession) -> BaselineRunResult:
    return session.finalize(failure_reason="VNS baseline not implemented in this commit.")


def _run_aco(session: _SearchSession) -> BaselineRunResult:
    return session.finalize(failure_reason="ACO baseline not implemented in this commit.")


def _run_ga_vns(session: _SearchSession) -> BaselineRunResult:
    return session.finalize(failure_reason="GA-VNS baseline not implemented in this commit.")


def _run_lns(session: _SearchSession) -> BaselineRunResult:
    return session.finalize(failure_reason="LNS baseline not implemented in this commit.")


def _run_gwo(session: _SearchSession) -> BaselineRunResult:
    return session.finalize(failure_reason="GWO baseline not implemented in this commit.")


def _run_iwd(session: _SearchSession) -> BaselineRunResult:
    return session.finalize(failure_reason="IWD baseline not implemented in this commit.")


def _normalize_algorithm(algorithm: str) -> str:
    name = str(algorithm).strip()
    aliases = {item.lower(): item for item in BASELINE_ALGORITHMS}
    aliases.update({"ga_vns": "GA-VNS", "gavns": "GA-VNS", "grey-wolf": "GWO"})
    key = name.lower()
    if key not in aliases:
        raise ValueError(f"Unknown metaheuristic baseline {algorithm!r}; expected one of {BASELINE_ALGORITHMS}")
    return aliases[key]


def _is_feasible(solution: Solution, context: EvaluationContext) -> bool:
    return not check_solution(solution, context.instance, DEFAULT_PRICES)


def _all_customer_ids(instance: Instance) -> list[str]:
    return [node.node_id for node in instance.nodes if node.node_type.lower() == "c"]


def _solution_order(solution: Solution, instance: Instance) -> list[str]:
    order: list[str] = []
    for route in solution.routes:
        order.extend(_route_customers(route, instance))
    return order


def _route_type_hints(solution: Solution, instance: Instance) -> dict[str, float]:
    hints: dict[str, float] = {}
    for route in solution.routes:
        value = 0.95 if route.vehicle_type.lower() == "ev" else 0.05
        for customer_id in _route_customers(route, instance):
            hints[customer_id] = value
    return hints


def _order_to_solution(
    order: list[str],
    session: _SearchSession,
    *,
    type_hints: dict[str, float] | None = None,
    ev_threshold: float = 0.82,
) -> Solution:
    ordered = _complete_order(order, session.context.instance)
    width = max(1, len(ordered) - 1)
    hints = type_hints or _route_type_hints(session.current.solution, session.context.instance)
    chromosome = {
        "customer_keys": {customer_id: idx / width for idx, customer_id in enumerate(ordered)},
        "vehicle_type_keys": {customer_id: float(hints.get(customer_id, 0.05)) for customer_id in ordered},
        "ev_threshold": float(ev_threshold),
    }
    return random_key_to_solution(chromosome, session.context.instance, session.context.carbon_profile, DEFAULT_PRICES)


def _complete_order(order: list[str], instance: Instance) -> list[str]:
    seen: set[str] = set()
    all_customers = set(_all_customer_ids(instance))
    complete = [customer_id for customer_id in order if customer_id in all_customers and not (customer_id in seen or seen.add(customer_id))]
    missing = sorted(all_customers - set(complete))
    return [*complete, *missing]


def _distance(instance: Instance, a: str, b: str) -> float:
    return float(instance.distance(a, b))


def _node_lookup(instance: Instance) -> dict[str, Node]:
    return {node.node_id: node for node in instance.nodes}


def _apply_order_move(order: list[str], rng: random.Random, move: str) -> list[str]:
    if len(order) < 2:
        return list(order)
    out = list(order)
    if move == "swap":
        i, j = sorted(rng.sample(range(len(out)), 2))
        out[i], out[j] = out[j], out[i]
    elif move == "relocate":
        i, j = rng.sample(range(len(out)), 2)
        item = out.pop(i)
        out.insert(j, item)
    elif move == "two_opt":
        i, j = sorted(rng.sample(range(len(out)), 2))
        out[i : j + 1] = reversed(out[i : j + 1])
    elif move == "double_bridge":
        if len(out) < 8:
            rng.shuffle(out)
        else:
            cuts = sorted(rng.sample(range(1, len(out)), 4))
            a, b, c, d = cuts
            out = out[:a] + out[c:d] + out[b:c] + out[a:b] + out[d:]
    elif move == "nearest_delete":
        base = rng.choice(out)
        neighbors = sorted(out, key=lambda node: (_distance_placeholder(base, node), node))
        target = neighbors[1] if len(neighbors) > 1 else base
        out.remove(target)
        out.insert(rng.randrange(len(out) + 1), target)
    else:
        rng.shuffle(out)
    return out


def _distance_placeholder(a: str, b: str) -> float:
    return 0.0 if a == b else 1.0


def _order_swap_sequence(source: list[str], target: list[str]) -> list[tuple[int, int]]:
    current = list(source)
    pos = {customer_id: idx for idx, customer_id in enumerate(current)}
    swaps: list[tuple[int, int]] = []
    for idx, customer_id in enumerate(target):
        j = pos.get(customer_id)
        if j is None or j == idx:
            continue
        swaps.append((idx, j))
        other = current[idx]
        current[idx], current[j] = current[j], current[idx]
        pos[customer_id] = idx
        pos[other] = j
    return swaps


def _apply_swaps(order: list[str], swaps: list[tuple[int, int]], rng: random.Random, probability: float) -> list[str]:
    out = list(order)
    for i, j in swaps:
        if i < len(out) and j < len(out) and rng.random() < probability:
            out[i], out[j] = out[j], out[i]
    return out


def _order_crossover(parent_a: list[str], parent_b: list[str], rng: random.Random) -> list[str]:
    if len(parent_a) < 2:
        return list(parent_a)
    i, j = sorted(rng.sample(range(len(parent_a)), 2))
    block = parent_a[i : j + 1]
    used = set(block)
    fill = [customer_id for customer_id in parent_b if customer_id not in used]
    return [*fill[:i], *block, *fill[i:]]


def _alns_neighbor(session: _SearchSession, solution: Solution, destroy: str, repair: str) -> _OperatorOutcome:
    return _apply_strong_alns_destroy_repair(solution, session.context, session.rng, destroy, repair)


def _local_order_search(session: _SearchSession, solution: Solution, *, max_trials: int = 6) -> Solution:
    best = solution
    best_obj = score_reference(best, session.context)
    order = _solution_order(solution, session.context.instance)
    for move in ("swap", "relocate", "two_opt"):
        for _ in range(max(1, max_trials)):
            if not session.can_score():
                return best
            candidate = _order_to_solution(_apply_order_move(order, session.rng, move), session)
            scored = session.score(candidate, operator=f"local_{move}")
            if scored is not None and scored.feasible and scored.objective < best_obj - 1e-9:
                best = scored.solution
                best_obj = scored.objective
                order = _solution_order(best, session.context.instance)
    return best


def _solution_from_routes(routes: list[Route], session: _SearchSession) -> Solution:
    rebuilt = _rebuild_solution(routes, session.context)
    return rebuilt if rebuilt is not None else session.current.solution
