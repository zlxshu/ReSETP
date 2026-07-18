"""Isolated HGS-style outer search with the frozen ReSETP ALNS as educator.

This file is development-only.  It does not modify the formal solver entry
point.  All complete candidate scores pass through EvalBudget.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
import time
from pathlib import Path
from typing import Any

from setp_solver.algorithms.resetp_alns.kernel.winner import WinnerKernelConfig, run_winner_kernel
from setp_solver.algorithms.resetp_alns.operators.local_search import (
    _candidate_with_route_customers,
)
from setp_solver.algorithms.resetp_alns.runtime.budgeted_scoring import score_search_candidate
from setp_solver.algorithms.resetp_alns.support.fleet_charge_corepair import (
    propose_fleet_charge_corepair,
)
from setp_solver.algorithms.resetp_alns.support.order_decoder import (
    OrderDecodeContext,
    mutated_type_hints,
    order_to_solution,
    route_customers,
    route_type_hints,
    solution_order,
)
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.evaluation import EvalBudget, EvaluationContext, score_reference
from setp_solver.solution import Solution


@dataclass
class Individual:
    order: list[str]
    solution: Solution
    objective: float


@dataclass
class ArmResult:
    algorithm: str
    best_solution: Solution
    best_cost: float
    evaluations: int
    elapsed_seconds: float
    route_count: int
    feasible: bool
    mechanism_activity: dict[str, int]


def ordered_crossover(left: list[str], right: list[str], rng: random.Random) -> list[str]:
    """Order crossover: keep one block from left, fill remaining from right."""

    if len(left) < 2:
        return list(left)
    a = rng.randrange(0, len(left) - 1)
    b = rng.randrange(a + 1, len(left))
    block = left[a : b + 1]
    remainder = [item for item in right if item not in set(block)]
    return [*remainder[:a], *block, *remainder[a:]]


def mutate_order(order: list[str], rng: random.Random) -> list[str]:
    changed = list(order)
    if len(changed) < 4:
        changed.reverse()
        return changed
    mode = rng.randrange(3)
    a, b = sorted(rng.sample(range(len(changed)), 2))
    if mode == 0:
        changed[a], changed[b] = changed[b], changed[a]
    elif mode == 1:
        changed[a : b + 1] = reversed(changed[a : b + 1])
    else:
        item = changed.pop(b)
        changed.insert(a, item)
    return changed


def order_distance(left: list[str], right: list[str]) -> float:
    if not left:
        return 0.0
    position = {item: idx for idx, item in enumerate(right)}
    return sum(abs(idx - position.get(item, idx)) for idx, item in enumerate(left)) / max(1, len(left) ** 2)


def _select_parents(population: list[Individual], rng: random.Random) -> tuple[Individual, Individual]:
    ranked = sorted(population, key=lambda item: item.objective)
    first = ranked[rng.randrange(min(4, len(ranked)))]
    candidates = sorted(
        (item for item in population if item is not first),
        key=lambda item: (-order_distance(first.order, item.order), item.objective),
    )
    second = candidates[0] if candidates else first
    return first, second


def route_block_crossover(
    left: Individual,
    right: Individual,
    instance: Any,
    rng: random.Random,
) -> list[str]:
    """Preserve one complete route block and fill the rest from the other parent.

    The previous prototype preserved an arbitrary slice of a flattened order.
    This version preserves a route discovered by the search, so a useful
    multi-depot responsibility/sequence block is not immediately torn apart.
    """

    blocks = [
        route_customers(route, instance)
        for route in left.solution.routes
        if route_customers(route, instance)
    ]
    if not blocks:
        return ordered_crossover(left.order, right.order, rng)
    block = list(blocks[rng.randrange(len(blocks))])
    blocked = set(block)
    remainder = [customer_id for customer_id in right.order if customer_id not in blocked]
    anchor = rng.randrange(len(remainder) + 1)
    return [*remainder[:anchor], *block, *remainder[anchor:]]


def _survivors(population: list[Individual], limit: int = 8) -> list[Individual]:
    """Keep quality first, then retain order diversity among near-duplicates."""

    ranked = sorted(population, key=lambda item: item.objective)
    survivors: list[Individual] = []
    for individual in ranked:
        if not survivors or all(
            order_distance(individual.order, kept.order) > 1e-12
            for kept in survivors
        ):
            survivors.append(individual)
        if len(survivors) >= limit:
            break
    if not survivors:
        survivors.append(ranked[0])
    return survivors


def run_outer_search(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    initial_solution: Solution | None = None,
) -> ArmResult:
    """Run the population/recombination part without ALNS education."""

    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    warm = initial_solution or make_shared_initial_solution(bundle, prices=prices)
    rng = random.Random(seed)
    budget = EvalBudget(limit=max(0, int(eval_budget)), target=max(0, int(eval_budget)))
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=budget,
    )
    warm_cost = score_reference(warm, context)
    warm_order = solution_order(warm, bundle.instance)
    decode = OrderDecodeContext(bundle.instance, prices, bundle.carbon_profile, rng)
    hints = route_type_hints(warm, bundle.instance)
    population = [Individual(warm_order, warm, warm_cost)]
    best = population[0]
    activity = {
        "outer_candidates": 0,
        "ordered_crossovers": 0,
        "order_mutations": 0,
        "diversity_rejections": 0,
        "improvements": 0,
    }

    while budget.count < budget.target_count:
        if len(population) == 1:
            child_order = mutate_order(warm_order, rng)
            activity["order_mutations"] += 1
        else:
            left, right = _select_parents(population, rng)
            child_order = ordered_crossover(left.order, right.order, rng)
            activity["ordered_crossovers"] += 1
            if rng.random() < 0.35:
                child_order = mutate_order(child_order, rng)
                activity["order_mutations"] += 1
        if any(order_distance(child_order, item.order) < 1e-12 for item in population):
            child_order = mutate_order(child_order, rng)
            activity["diversity_rejections"] += 1
            activity["order_mutations"] += 1
        candidate = order_to_solution(
            child_order,
            decode,
            current_solution=best.solution,
            type_hints=hints,
        )
        candidate, objective = score_search_candidate(
            candidate,
            context,
            channel="isolated_hgs_outer",
        )
        activity["outer_candidates"] += 1
        individual = Individual(child_order, candidate, objective)
        population.append(individual)
        population = sorted(population, key=lambda item: item.objective)[:8]
        if objective < best.objective - 1e-9:
            best = individual
            activity["improvements"] += 1

    violations = check_solution(best.solution, bundle.instance, prices)
    return ArmResult(
        algorithm="pure_hgs_style_outer",
        best_solution=best.solution,
        best_cost=float(best.objective),
        evaluations=budget.count,
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(best.solution.routes),
        feasible=not violations,
        mechanism_activity=activity,
    )


def run_pure_alns(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    initial_solution: Solution | None = None,
) -> ArmResult:
    started = time.perf_counter()
    result = run_winner_kernel(
        bundle_dir,
        config=WinnerKernelConfig(
            seed=seed,
            eval_budget=int(eval_budget),
            max_runtime_seconds=3600.0,
            require_charging_signal=False,
        ),
        initial_solution=initial_solution,
        prices=prices,
    )
    return ArmResult(
        algorithm="pure_alns",
        best_solution=result["best_solution"],
        best_cost=float(result["best_cost"]),
        evaluations=int(result["evaluations"]),
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(result["best_solution"].routes),
        feasible=bool(result["feasible"]),
        mechanism_activity={"alns_actual_moves": int(result.get("actual_moves", 0))},
    )


def run_combined(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    outer_share: float = 0.25,
    inner_basins: int = 1,
    prices: Any = DEFAULT_PRICES,
) -> ArmResult:
    """Spend one global budget: outer exploration first, ALNS education second."""

    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    warm = make_shared_initial_solution(bundle, prices=prices)
    total = max(0, int(eval_budget))
    outer_budget = min(total, max(0, int(round(total * float(outer_share)))))
    inner_budget = total - outer_budget
    outer = run_outer_search(
        bundle_dir,
        seed=seed,
        eval_budget=outer_budget,
        prices=prices,
        initial_solution=warm,
    )
    if inner_budget:
        basin_count = max(1, min(int(inner_basins), inner_budget))
        allocations = [inner_budget // basin_count] * basin_count
        for index in range(inner_budget % basin_count):
            allocations[index] += 1
        starts = [outer.best_solution]
        if basin_count > 1:
            starts = [warm, outer.best_solution]
            while len(starts) < basin_count:
                starts.append(outer.best_solution)
        inner_runs = [
            run_pure_alns(
                bundle_dir,
                seed=seed + 1009 * index,
                eval_budget=allocation,
                prices=prices,
                initial_solution=starts[index],
            )
            for index, allocation in enumerate(allocations)
        ]
        candidates = [outer, *inner_runs]
        winner = min(candidates, key=lambda item: item.best_cost)
        best_solution = winner.best_solution
        best_cost = winner.best_cost
        feasible = all(item.feasible for item in candidates)
        inner_activity = {
            "alns_actual_moves": sum(item.mechanism_activity.get("alns_actual_moves", 0) for item in inner_runs),
            "educated_basins": basin_count,
        }
    else:
        best_solution = outer.best_solution
        best_cost = outer.best_cost
        feasible = outer.feasible
        inner_activity = {"alns_actual_moves": 0}
    return ArmResult(
        algorithm="mechanism_hgs_alns_skeleton",
        best_solution=best_solution,
        best_cost=float(best_cost),
        evaluations=outer.evaluations + inner_budget,
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(best_solution.routes),
        feasible=feasible,
        mechanism_activity={
            **outer.mechanism_activity,
            **inner_activity,
            "outer_budget": outer_budget,
            "inner_budget": inner_budget,
        },
    )


def run_memetic_combined(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    educator_depth: int = 4,
    prices: Any = DEFAULT_PRICES,
) -> ArmResult:
    """Always educate each HGS-style offspring with a short ALNS search.

    This is the first genuinely interleaved prototype.  One complete
    evaluation creates an offspring, then up to ``educator_depth`` evaluations
    improve that same offspring with ALNS.  The global complete-evaluation
    budget is exact: offspring and educator evaluations share one ledger.
    """

    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    warm = make_shared_initial_solution(bundle, prices=prices)
    warm_cost = float(evaluate(warm, bundle.instance, bundle.carbon_profile, prices)["total_cost"])
    total = max(0, int(eval_budget))
    rng = random.Random(seed)
    decode = OrderDecodeContext(bundle.instance, prices, bundle.carbon_profile, rng)
    warm_order = solution_order(warm, bundle.instance)
    population = [Individual(warm_order, warm, warm_cost)]
    best = population[0]
    candidate_budget = EvalBudget(limit=total, target=total)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=candidate_budget,
    )
    spent = 0
    generation = 0
    activity = {
        "offspring_candidates": 0,
        "route_block_crossovers": 0,
        "order_mutations": 0,
        "type_hint_mutations": 0,
        "educated_offspring": 0,
        "educator_evaluations": 0,
        "educator_improvements": 0,
        "population_improvements": 0,
    }

    while spent < total:
        generation += 1
        if len(population) == 1:
            child_order = mutate_order(population[0].order, rng)
            activity["order_mutations"] += 1
            hint_source = route_type_hints(population[0].solution, bundle.instance)
        else:
            left, right = _select_parents(population, rng)
            child_order = route_block_crossover(left, right, bundle.instance, rng)
            activity["route_block_crossovers"] += 1
            if rng.random() < 0.35:
                child_order = mutate_order(child_order, rng)
                activity["order_mutations"] += 1
            left_hints = route_type_hints(left.solution, bundle.instance)
            right_hints = route_type_hints(right.solution, bundle.instance)
            hint_source = {
                customer_id: (
                    left_hints.get(customer_id, right_hints.get(customer_id, 0.05))
                    if rng.random() < 0.5
                    else right_hints.get(customer_id, left_hints.get(customer_id, 0.05))
                )
                for customer_id in child_order
            }
        hints = mutated_type_hints(
            hint_source,
            child_order,
            decode,
            flip_probability=0.10,
            force_ev=(generation % 5 == 0),
        )
        activity["type_hint_mutations"] += 1
        child = order_to_solution(
            child_order,
            decode,
            current_solution=best.solution,
            type_hints=hints,
        )
        child, child_cost = score_search_candidate(
            child,
            context,
            channel="isolated_memetic_offspring",
        )
        spent += 1
        activity["offspring_candidates"] += 1
        chosen_solution = child
        chosen_cost = float(child_cost)

        education = min(max(0, int(educator_depth)), total - spent)
        if education:
            educated = run_pure_alns(
                bundle_dir,
                seed=seed * 1_000_003 + generation,
                eval_budget=education,
                prices=prices,
                initial_solution=child,
            )
            spent += educated.evaluations
            activity["educated_offspring"] += 1
            activity["educator_evaluations"] += educated.evaluations
            if educated.best_cost < chosen_cost - 1e-9:
                chosen_solution = educated.best_solution
                chosen_cost = educated.best_cost
                activity["educator_improvements"] += 1

        individual = Individual(
            solution_order(chosen_solution, bundle.instance),
            chosen_solution,
            float(chosen_cost),
        )
        population = _survivors([*population, individual], limit=8)
        if individual.objective < best.objective - 1e-9:
            best = individual
            activity["population_improvements"] += 1

    violations = check_solution(best.solution, bundle.instance, prices)
    return ArmResult(
        algorithm="mechanism_hgs_alns_memetic",
        best_solution=best.solution,
        best_cost=float(best.objective),
        evaluations=spent,
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(best.solution.routes),
        feasible=not violations,
        mechanism_activity=activity,
    )


def _route_distance(home_depot_id: str, customers: list[str], instance: Any) -> float:
    sequence = [home_depot_id, *customers, home_depot_id]
    return sum(
        float(instance.distance(left, right))
        for left, right in zip(sequence, sequence[1:], strict=False)
    )


def _best_insertion(
    home_depot_id: str,
    customers: list[str],
    customer_id: str,
    instance: Any,
) -> tuple[int, float]:
    base = _route_distance(home_depot_id, customers, instance)
    candidates: list[tuple[float, int]] = []
    for position in range(len(customers) + 1):
        changed = list(customers)
        changed.insert(position, customer_id)
        candidates.append(
            (_route_distance(home_depot_id, changed, instance) - base, position)
        )
    delta, position = min(candidates)
    return position, float(delta)


def cross_depot_swapstar_intensify(
    solution: Solution,
    context: EvaluationContext,
    *,
    incumbent_objective: float,
    max_evaluations: int,
) -> tuple[Solution, float, dict[str, Any]]:
    """Exchange customers across different depots with free reinsertion.

    This is the mechanism-specific extension missing from the existing
    same-depot SWAP* component.  It preserves each route's physical home depot,
    but exchanges responsibility for two customers and freely reinserts them.
    """

    best = solution
    best_objective = float(incumbent_objective)
    used = 0
    counters = {
        "cross_depot_proxy_moves": 0,
        "cross_depot_full_candidates": 0,
        "cross_depot_feasible_candidates": 0,
        "cross_depot_accepted_moves": 0,
        "cross_depot_rejection_examples": [],
    }
    while used < max(0, int(max_evaluations)):
        ranked: list[tuple[float, str, int, int, str, str, int, int]] = []
        route_customers_by_index = [
            route_customers(route, context.instance) for route in best.routes
        ]
        for left_idx, left_route in enumerate(best.routes):
            left_customers = route_customers_by_index[left_idx]
            if not left_customers:
                continue
            for right_idx in range(left_idx + 1, len(best.routes)):
                right_route = best.routes[right_idx]
                if left_route.home_depot_id == right_route.home_depot_id:
                    continue
                right_customers = route_customers_by_index[right_idx]
                if not right_customers:
                    continue
                left_base = _route_distance(
                    left_route.home_depot_id, left_customers, context.instance
                )
                right_base = _route_distance(
                    right_route.home_depot_id, right_customers, context.instance
                )
                for source_idx, target_idx in (
                    (left_idx, right_idx),
                    (right_idx, left_idx),
                ):
                    source_route = best.routes[source_idx]
                    target_route = best.routes[target_idx]
                    source_customers = route_customers_by_index[source_idx]
                    target_customers = route_customers_by_index[target_idx]
                    if len(source_customers) <= 1:
                        continue
                    source_base = _route_distance(
                        source_route.home_depot_id,
                        source_customers,
                        context.instance,
                    )
                    target_base = _route_distance(
                        target_route.home_depot_id,
                        target_customers,
                        context.instance,
                    )
                    for customer_id in source_customers:
                        new_source = [
                            item for item in source_customers if item != customer_id
                        ]
                        target_pos, _ = _best_insertion(
                            target_route.home_depot_id,
                            target_customers,
                            customer_id,
                            context.instance,
                        )
                        new_target = list(target_customers)
                        new_target.insert(target_pos, customer_id)
                        delta = (
                            _route_distance(
                                source_route.home_depot_id,
                                new_source,
                                context.instance,
                            )
                            + _route_distance(
                                target_route.home_depot_id,
                                new_target,
                                context.instance,
                            )
                            - source_base
                            - target_base
                        )
                        if delta < -1e-9:
                            ranked.append(
                                (
                                    float(delta),
                                    "relocate",
                                    source_idx,
                                    target_idx,
                                    customer_id,
                                    "",
                                    -1,
                                    target_pos,
                                )
                            )
                for left_customer in left_customers:
                    stripped_left = [
                        item for item in left_customers if item != left_customer
                    ]
                    for right_customer in right_customers:
                        stripped_right = [
                            item for item in right_customers if item != right_customer
                        ]
                        left_pos, _ = _best_insertion(
                            left_route.home_depot_id,
                            stripped_left,
                            right_customer,
                            context.instance,
                        )
                        right_pos, _ = _best_insertion(
                            right_route.home_depot_id,
                            stripped_right,
                            left_customer,
                            context.instance,
                        )
                        new_left = list(stripped_left)
                        new_right = list(stripped_right)
                        new_left.insert(left_pos, right_customer)
                        new_right.insert(right_pos, left_customer)
                        delta = (
                            _route_distance(
                                left_route.home_depot_id,
                                new_left,
                                context.instance,
                            )
                            + _route_distance(
                                right_route.home_depot_id,
                                new_right,
                                context.instance,
                            )
                            - left_base
                            - right_base
                        )
                        if delta < -1e-9:
                            ranked.append(
                                (
                                    float(delta),
                                    "swapstar",
                                    left_idx,
                                    right_idx,
                                    left_customer,
                                    right_customer,
                                    left_pos,
                                    right_pos,
                                )
                            )
        ranked.sort()
        counters["cross_depot_proxy_moves"] += len(ranked)
        if not ranked:
            break
        improved = False
        for (
            _delta,
            move_kind,
            left_idx,
            right_idx,
            left_customer,
            right_customer,
            left_pos,
            right_pos,
        ) in ranked:
            if used >= max_evaluations:
                break
            left_customers = route_customers(best.routes[left_idx], context.instance)
            right_customers = route_customers(best.routes[right_idx], context.instance)
            new_left = [item for item in left_customers if item != left_customer]
            new_right = list(right_customers)
            if move_kind == "relocate":
                new_right.insert(right_pos, left_customer)
            else:
                new_right = [
                    item for item in right_customers if item != right_customer
                ]
                new_left.insert(left_pos, right_customer)
                new_right.insert(right_pos, left_customer)
            candidate = _candidate_with_route_customers(
                best,
                context,
                {left_idx: new_left, right_idx: new_right},
            )
            counters["cross_depot_full_candidates"] += 1
            if candidate is None:
                if len(counters["cross_depot_rejection_examples"]) < 3:
                    counters["cross_depot_rejection_examples"].append(
                        "candidate_builder_rejected"
                    )
                continue
            violations = check_solution(candidate, context.instance, context.prices)
            if violations:
                if len(counters["cross_depot_rejection_examples"]) < 3:
                    counters["cross_depot_rejection_examples"].append(
                        str(violations[0])
                    )
                continue
            counters["cross_depot_feasible_candidates"] += 1
            candidate, objective = score_search_candidate(
                candidate,
                context,
                channel="isolated_cross_depot_swapstar",
            )
            used += 1
            if objective < best_objective - 1e-9:
                best = candidate
                best_objective = float(objective)
                counters["cross_depot_accepted_moves"] += 1
                improved = True
                break
        if not improved:
            break
    counters["cross_depot_evaluations"] = used
    return best, best_objective, counters


def run_mechanism_intensified(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
) -> ArmResult:
    """ALNS plus always-on cross-depot and fleet/charging closure."""

    started = time.perf_counter()
    total = max(0, int(eval_budget))
    if total == 0:
        bundle = load_search_bundle(bundle_dir)
        warm = make_shared_initial_solution(bundle, prices=prices)
        return ArmResult(
            algorithm="mechanism_hgs_alns_intensified",
            best_solution=warm,
            best_cost=independent_cost(bundle_dir, warm, prices),
            evaluations=0,
            elapsed_seconds=time.perf_counter() - started,
            route_count=len(warm.routes),
            feasible=not check_solution(warm, bundle.instance, prices),
            mechanism_activity={},
        )
    base_budget = max(1, int(round(total * 0.80)))
    base_budget = min(base_budget, total)
    base = run_pure_alns(
        bundle_dir,
        seed=seed,
        eval_budget=base_budget,
        prices=prices,
    )
    bundle = load_search_bundle(bundle_dir)
    remaining = total - base.evaluations
    shared_budget = EvalBudget(limit=remaining, target=remaining)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=shared_budget,
    )
    cross_limit = min(remaining, max(1, int(round(total * 0.15))))
    solution, objective, cross_counts = cross_depot_swapstar_intensify(
        base.best_solution,
        context,
        incumbent_objective=base.best_cost,
        max_evaluations=cross_limit,
    )
    fleet_counts = {
        "fleet_charge_attempts": 0,
        "fleet_charge_evaluations": 0,
        "fleet_charge_improvements": 0,
    }
    fleet_room = remaining - shared_budget.count
    if fleet_room > 0:
        outcome = propose_fleet_charge_corepair(
            solution,
            context,
            max_attempts=min(len(solution.routes), fleet_room),
            current_objective=objective,
        )
        fleet_counts["fleet_charge_attempts"] += int(outcome.attempts)
        fleet_counts["fleet_charge_evaluations"] += int(outcome.evaluations_used)
        if outcome.solution is not None and outcome.objective is not None:
            solution = outcome.solution
            objective = float(outcome.objective)
            fleet_counts["fleet_charge_improvements"] += int(outcome.best_improved)
    used_special = shared_budget.count
    filler = remaining - used_special
    filler_activity = 0
    if filler > 0:
        continuation = run_pure_alns(
            bundle_dir,
            seed=seed + 9_999_991,
            eval_budget=filler,
            prices=prices,
            initial_solution=solution,
        )
        filler_activity = continuation.evaluations
        if continuation.best_cost < objective - 1e-9:
            solution = continuation.best_solution
            objective = continuation.best_cost
    violations = check_solution(solution, bundle.instance, prices)
    return ArmResult(
        algorithm="mechanism_hgs_alns_intensified",
        best_solution=solution,
        best_cost=float(objective),
        evaluations=base.evaluations + used_special + filler_activity,
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(solution.routes),
        feasible=not violations,
        mechanism_activity={
            **cross_counts,
            **fleet_counts,
            "base_alns_evaluations": base.evaluations,
            "filler_alns_evaluations": filler_activity,
        },
    )


def independent_cost(bundle_dir: str | Path, solution: Solution, prices: Any = DEFAULT_PRICES) -> float:
    bundle = load_search_bundle(bundle_dir)
    return float(
        evaluate(
            solution,
            bundle.instance,
            bundle.carbon_profile,
            prices,
        )["total_cost"]
    )
