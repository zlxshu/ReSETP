"""Diagnostic global-order repack helpers for ALNS structural probes."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random

from setp_solver.check import check_solution
from setp_solver.solution import Solution
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.algorithms.resetp_alns.support.order_decoder import OrderDecodeContext, order_to_solution, route_type_hints, solution_order


@dataclass(frozen=True)
class OrderPerturbation:
    label: str
    order: list[str]


@dataclass(frozen=True)
class GlobalRepackOutcome:
    solution: Solution | None
    attempts: int
    feasible: int
    accepted: bool
    best_improved: bool
    route_count_delta: int
    cost_fix_delta: float
    order_source: str
    trace_rows: list[dict[str, object]]


def order_perturbations(order: list[str], instance: object, rng: random.Random) -> list[OrderPerturbation]:
    base = list(order)
    return [
        OrderPerturbation("current_order", base),
        OrderPerturbation("two_opt_order", _two_opt_order(base, rng)),
        OrderPerturbation("double_bridge_order", _double_bridge_order(base)),
        OrderPerturbation("depot_group_shuffle_order", _depot_group_shuffle_order(base, instance, rng)),
    ]


def propose_global_order_repack(
    current_solution: Solution,
    best_solution: Solution,
    context: EvaluationContext,
    rng: random.Random,
) -> GlobalRepackOutcome:
    decode_context = OrderDecodeContext(context.instance, context.prices, context.carbon_profile, rng)
    sources = (("current", current_solution), ("best", best_solution))
    current_cost = _feasible_model_cost(current_solution, context)
    best_candidate: Solution | None = None
    best_cost = current_cost
    attempts = 0
    feasible = 0
    trace_rows: list[dict[str, object]] = []
    source_label = ""
    source_route_count = len(current_solution.routes)
    for source_name, source_solution in sources:
        base_order = solution_order(source_solution, context.instance)
        hints = route_type_hints(source_solution, context.instance)
        for perturbation in order_perturbations(base_order, context.instance, rng):
            attempts += 1
            candidate = order_to_solution(perturbation.order, decode_context, current_solution=source_solution, type_hints=hints)
            violations = check_solution(candidate, context.instance, context.prices)
            candidate_cost = math.inf if violations else _feasible_model_cost(candidate, context)
            if not violations:
                feasible += 1
            improved = not violations and candidate_cost < best_cost - 1e-9
            trace_rows.append(
                {
                    "order_source": f"{source_name}:{perturbation.label}",
                    "feasible": not violations,
                    "candidate_cost": candidate_cost if math.isfinite(candidate_cost) else "UNKNOWN",
                    "route_count_delta": len(candidate.routes) - len(source_solution.routes),
                    "cost_fix_delta": _fixed_cost_delta(candidate, source_solution, context),
                }
            )
            if improved:
                best_candidate = candidate
                best_cost = candidate_cost
                source_label = f"{source_name}:{perturbation.label}"
                source_route_count = len(source_solution.routes)
    if best_candidate is None:
        return GlobalRepackOutcome(None, attempts, feasible, False, False, 0, 0.0, "", trace_rows)
    return GlobalRepackOutcome(
        best_candidate,
        attempts,
        feasible,
        True,
        best_cost < current_cost - 1e-9,
        len(best_candidate.routes) - source_route_count,
        _fixed_cost_delta(best_candidate, current_solution, context),
        source_label,
        trace_rows,
    )


def _two_opt_order(order: list[str], rng: random.Random) -> list[str]:
    if len(order) < 4:
        return list(reversed(order))
    left = rng.randrange(0, len(order) - 2)
    right = rng.randrange(left + 2, len(order))
    changed = list(order)
    changed[left : right + 1] = reversed(changed[left : right + 1])
    return changed


def _double_bridge_order(order: list[str]) -> list[str]:
    if len(order) < 8:
        mid = len(order) // 2
        return [*order[mid:], *order[:mid]]
    q1 = len(order) // 4
    q2 = len(order) // 2
    q3 = (3 * len(order)) // 4
    return [*order[:q1], *order[q2:q3], *order[q1:q2], *order[q3:]]


def _depot_group_shuffle_order(order: list[str], instance: object, rng: random.Random) -> list[str]:
    depots = [node for node in getattr(instance, "nodes", []) if str(getattr(node, "node_type", "")).lower() == "d"]
    if len(depots) <= 1:
        changed = list(order)
        rng.shuffle(changed)
        return changed
    groups: dict[str, list[str]] = {depot.node_id: [] for depot in depots}
    for customer_id in order:
        depot = min(depots, key=lambda item, cid=customer_id: (float(instance.distance(item.node_id, cid)), item.node_id))
        groups[depot.node_id].append(customer_id)
    keys = sorted(groups)
    rng.shuffle(keys)
    out: list[str] = []
    for key in keys:
        out.extend(groups[key])
    return out


def _feasible_model_cost(solution: Solution, context: EvaluationContext) -> float:
    if check_solution(solution, context.instance, context.prices):
        return math.inf
    return float(model_cost(solution, context))


def _fixed_cost_delta(candidate: Solution, source: Solution, context: EvaluationContext) -> float:
    price = context.prices["vehicle_fixed_cost"] if isinstance(context.prices, dict) else getattr(context.prices, "vehicle_fixed_cost")
    return float(len(candidate.routes) - len(source.routes)) * float(price)
