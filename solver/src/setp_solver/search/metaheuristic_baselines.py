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
    params = {"population": 200, "elite_fraction": 0.10, "mutation_probability": 0.10}
    population = _ga_initial_population(session, params["population"])
    no_improvement = 0
    generation = 0
    while session.can_score() and population:
        generation += 1
        before = session.best.objective
        population = sorted(population, key=lambda item: (item.objective, item.signature))
        elite_count = max(1, int(math.ceil(len(population) * params["elite_fraction"])))
        next_population = population[:elite_count]
        survivor_pool = population[elite_count:]
        session.rng.shuffle(survivor_pool)
        next_population.extend(survivor_pool[: max(0, len(population) - elite_count) // 4])
        while len(next_population) < len(population) and session.can_score():
            parent_a = _tournament(population, session.rng)
            parent_b = _tournament(population, session.rng)
            operator = "ga_common_nodes" if session.rng.random() < 0.5 else "ga_common_arcs"
            child = _ga_crossover(parent_a.solution, parent_b.solution, session, operator=operator)
            if session.rng.random() < params["mutation_probability"]:
                child = _ga_mutation(child, session)
                operator = f"{operator}_mutation"
            scored = session.score(child, operator=operator)
            if scored is not None:
                next_population.append(scored)
                session.accept_if_better(scored)
        if session.best.objective < before - 1e-9:
            no_improvement = 0
        else:
            no_improvement += 1
        population = sorted(next_population, key=lambda item: (item.objective, item.signature))[: max(1, len(population))]
        if no_improvement >= max(5, len(population) // 4):
            _ga_diversify(population, session)
            no_improvement = 0
    return session.finalize(params)


def _run_pso(session: _SearchSession) -> BaselineRunResult:
    params = {"population": 50, "w": 0.72, "c1": 1.49, "c2": 1.49, "calibration_eval_seed0": 1000}
    particles = _pso_initial_particles(session, params["population"])
    if not particles:
        return session.finalize(params, failure_reason="PSO produced no particles.")
    gbest = min((particle["pbest"] for particle in particles), key=lambda item: (item.objective, item.signature))
    while session.can_score():
        for particle in particles:
            if not session.can_score():
                break
            order = list(particle["order"])
            velocity = list(particle.get("velocity", []))
            kept_velocity = [swap for swap in velocity if session.rng.random() < params["w"]]
            pbest_swaps = _order_swap_sequence(order, _solution_order(particle["pbest"].solution, session.context.instance))
            gbest_swaps = _order_swap_sequence(order, _solution_order(gbest.solution, session.context.instance))
            velocity = kept_velocity
            velocity.extend(swap for swap in pbest_swaps if session.rng.random() < min(1.0, params["c1"] / 2.0))
            velocity.extend(swap for swap in gbest_swaps if session.rng.random() < min(1.0, params["c2"] / 2.0))
            if session.rng.random() < 0.10:
                i, j = session.rng.sample(range(len(order)), 2)
                velocity.append((i, j))
            order = _apply_swaps(order, velocity, session.rng, 1.0)
            if session.rng.random() < 0.05:
                order = _apply_order_move(order, session.rng, session.rng.choice(["swap", "relocate", "two_opt"]))
            candidate = _order_to_solution(order, session, type_hints=_route_type_hints(particle["pbest"].solution, session.context.instance))
            scored = session.score(candidate, operator="pso_velocity_decode")
            if scored is None:
                continue
            particle["order"] = _solution_order(scored.solution, session.context.instance) if scored.feasible else order
            particle["velocity"] = velocity[-max(1, len(order)) :]
            if scored.objective < particle["pbest"].objective - 1e-9:
                particle["pbest"] = scored
            if scored.objective < gbest.objective - 1e-9:
                gbest = scored
            session.accept_if_better(scored)
    return session.finalize(params)


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


def _ga_initial_population(session: _SearchSession, target_population: int) -> list[_ScoredSolution]:
    order = _solution_order(session.current.solution, session.context.instance)
    population: list[_ScoredSolution] = [session.current]
    desired = max(1, min(int(target_population), max(1, session.target)))
    nn_order = _nearest_neighbor_order(session.context.instance, session.rng)
    for idx in range(desired - 1):
        if not session.can_score():
            break
        if idx == 0:
            candidate_order = nn_order
            operator = "ga_nn_initialization"
        elif idx % 5 == 0:
            candidate_order = _nearest_neighbor_order(session.context.instance, session.rng)
            operator = "ga_random_start_nn_initialization"
        else:
            move = ("swap", "relocate", "two_opt", "double_bridge")[idx % 4]
            candidate_order = _apply_order_move(order, session.rng, move)
            operator = f"ga_seeded_{move}"
        candidate = _order_to_solution(candidate_order, session)
        improved = _ga_initial_improvement(candidate, session)
        scored = session.score(improved, operator=operator)
        if scored is not None:
            population.append(scored)
            session.accept_if_better(scored)
    return sorted(population, key=lambda item: (item.objective, item.signature))


def _ga_initial_improvement(solution: Solution, session: _SearchSession) -> Solution:
    outcome = _alns_neighbor(session, solution, "whole_route_removal", "regret2_insert_repair")
    if outcome.produced and outcome.feasible:
        return outcome.solution
    return solution


def _nearest_neighbor_order(instance: Instance, rng: random.Random) -> list[str]:
    remaining = set(_all_customer_ids(instance))
    if not remaining:
        return []
    current = rng.choice(sorted(remaining))
    order = [current]
    remaining.remove(current)
    while remaining:
        current = min(remaining, key=lambda customer_id: (float(instance.distance(current, customer_id)), customer_id))
        order.append(current)
        remaining.remove(current)
    return order


def _tournament(population: list[_ScoredSolution], rng: random.Random) -> _ScoredSolution:
    if len(population) == 1:
        return population[0]
    a, b = rng.sample(population, 2)
    return a if (a.objective, a.signature) <= (b.objective, b.signature) else b


def _ga_crossover(parent_a: Solution, parent_b: Solution, session: _SearchSession, *, operator: str) -> Solution:
    if operator == "ga_common_arcs":
        return _route_crossover(parent_a, parent_b, session.context, session.rng)
    order_a = _solution_order(parent_a, session.context.instance)
    order_b = _solution_order(parent_b, session.context.instance)
    return _order_to_solution(_order_crossover(order_a, order_b, session.rng), session, type_hints=_route_type_hints(parent_a, session.context.instance))


def _ga_mutation(solution: Solution, session: _SearchSession) -> Solution:
    order = _solution_order(solution, session.context.instance)
    mutation = session.rng.choice(["random_node_delete", "random_route_delete", "nearest_node_delete"])
    if mutation == "random_route_delete":
        outcome = _alns_neighbor(session, solution, "whole_route_removal", "regret2_insert_repair")
        return outcome.solution if outcome.produced and outcome.feasible else solution
    if mutation == "nearest_node_delete":
        order = _nearest_node_reinsert_order(order, session.context.instance, session.rng)
    else:
        order = _apply_order_move(order, session.rng, session.rng.choice(["swap", "relocate", "two_opt"]))
    return _order_to_solution(order, session, type_hints=_route_type_hints(solution, session.context.instance))


def _nearest_node_reinsert_order(order: list[str], instance: Instance, rng: random.Random) -> list[str]:
    if len(order) < 2:
        return list(order)
    base = rng.choice(order)
    candidates = [customer_id for customer_id in order if customer_id != base]
    target = min(candidates, key=lambda customer_id: (float(instance.distance(base, customer_id)), customer_id))
    out = [customer_id for customer_id in order if customer_id != target]
    out.insert(rng.randrange(len(out) + 1), target)
    return out


def _ga_diversify(population: list[_ScoredSolution], session: _SearchSession) -> None:
    if len(population) <= 2:
        return
    keep = max(1, len(population) // 2)
    del population[keep:]


def _pso_initial_particles(session: _SearchSession, target_population: int) -> list[dict[str, Any]]:
    base_order = _solution_order(session.current.solution, session.context.instance)
    particles: list[dict[str, Any]] = [
        {"order": base_order, "velocity": [], "pbest": session.current}
    ]
    desired = max(1, min(int(target_population), max(1, session.target)))
    for idx in range(desired - 1):
        if not session.can_score():
            break
        if idx % 4 == 0:
            order = _nearest_neighbor_order(session.context.instance, session.rng)
        else:
            order = _apply_order_move(base_order, session.rng, ("swap", "relocate", "two_opt", "double_bridge")[idx % 4])
        candidate = _order_to_solution(order, session)
        scored = session.score(candidate, operator="pso_initial_particle")
        if scored is None:
            break
        particles.append({"order": order, "velocity": [], "pbest": scored})
        session.accept_if_better(scored)
    return particles


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
